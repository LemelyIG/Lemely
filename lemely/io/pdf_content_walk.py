"""The content walk of an opened PDF: page tree, resources, annotations, images.

#262: moved out of :mod:`lemely.io.scan_limits`, which re-exports its public
names. Owns the bounded inflate (:func:`decoded_stream_size`), the page-tree
descent, the resource-graph and annotation walks, the image checks, the
object-stream and object-count bound on the opened document, and
:func:`check_pdf_content` / :func:`check_pdf_page_content`. Imports only
:mod:`lemely.io._scan_common`.
"""

from __future__ import annotations

import itertools
import re
import zlib
from dataclasses import dataclass, field
from typing import Literal

import pymupdf
import pymupdf.mupdf as _mupdf

from lemely.io._scan_common import (
    _CROP_PAGES_MESSAGE,
    _FLATE_FILTER_NAMES,
    _IMAGE_TOO_LARGE_MESSAGE,
    _INFLATE_CHUNK,
    _MALFORMED_STRUCTURE_MESSAGE,
    _MAX_OBJECTS_PER_PAGE,
    _OBJECT_STREAM_ENCODING_MESSAGE,
    _OBJECT_STREAMS_MESSAGE,
    _PAGE_COUNT_UNREADABLE_MESSAGE,
    _PAGE_STRUCTURE_MALFORMED_MESSAGE,
    _PAGE_TREE_TOO_COMPLEX_MESSAGE,
    _PAGE_UNREADABLE_MESSAGE,
    _SCAN_PAGES_MESSAGE,
    _TOO_MANY_OBJECTS_MESSAGE,
    _TOO_MANY_PDF_OBJECTS_MESSAGE,
    _UNCHECKABLE_MESSAGE,
    _UNSUPPORTED_FILTER_MESSAGE,
    _WALK_FAILED_MESSAGE,
    _WHOLE_SCAN_MESSAGE,
    MAX_CROP_PAGES,
    MAX_OBJECT_STREAM_BYTES,
    MAX_PAGE_CONTENT_BYTES,
    MAX_PDF_OBJECTS,
    MAX_SCAN_CONTENT_BYTES,
    MAX_SCAN_PAGES,
    ScanRejectedError,
    ScanTooLargeError,
    ScanUnsupportedEncodingError,
    decode_pixel_cap,
)


def _bounded_inflate_size(raw: bytes, *, budget: int, page_index: int) -> int:
    """The decoded length of a Flate stream, or ``ScanTooLargeError`` past ``budget``.

    Never holds more than :data:`_INFLATE_CHUNK` of decoded bytes: the 112 MB
    bomb is refused after 8 MB in ~12 ms. A corrupt or truncated stream
    (``zlib.error``) counts what it yielded -- pdfium renders what it can of
    such a stream, so the cap measures the same thing.
    """
    decompressor = zlib.decompressobj()
    size = 0
    data = raw
    try:
        while data:
            size += len(decompressor.decompress(data, _INFLATE_CHUNK))
            if size > budget:
                raise ScanTooLargeError(
                    f"Page {page_index + 1} of this PDF contains far more drawing data than a "
                    f"scanned page can (over {MAX_PAGE_CONTENT_BYTES // 1_000_000} MB once "
                    "decompressed). Re-export it as a plain scan.",
                    reason="page_content",
                )
            data = decompressor.unconsumed_tail
            if decompressor.eof:
                break
    except zlib.error:
        return size
    return size


def _normalise_filter(doc: pymupdf.Document, kind: str, value: str) -> list[str] | None:
    """The declared ``/Filter`` name(s), resolving every legitimate spelling.

    ``None`` means unfiltered. Handles a bare name, a filter *array*
    (``decoded_stream_size`` itself still rejects one with more than one
    entry -- only the single-element spelling, ``[/FlateDecode]``, is
    legitimate), and one level of indirection (``/Filter 5 0 R`` where
    object 5 is itself a name or array) -- no PDF producer chains an
    indirect ``/Filter`` further than that, so a single resolution step is
    all this needs.
    """
    if kind == "xref":
        text = doc.xref_object(int(value.split()[0])).strip()  # type: ignore[no-untyped-call]
        if text.startswith("["):
            kind, value = "array", text
        elif text.startswith("/"):
            kind, value = "name", text
        else:
            return None
    if kind == "name":
        return [value]
    if kind == "array":
        return re.findall(r"/[^\s/\[\]<>]+", value)
    return None


def decoded_stream_size(doc: pymupdf.Document, xref: int, *, budget: int, page_index: int) -> int:
    """The decoded size of stream ``xref``, measured without decoding it wholesale.

    An unfiltered stream is its raw length. A single ``/FlateDecode`` (or
    its ``/Fl`` abbreviation, plain or one-element-array or one level of
    indirection -- see :func:`_normalise_filter`) is inflated in bounded
    chunks. Anything else -- ``/LZWDecode``, ``/ASCII85Decode``, a
    multi-entry filter array, ``/Crypt`` -- cannot be bounded without a full
    decode and is refused: every mainstream producer writes Flate content
    streams, so this costs nothing real and closes the obvious evasion.
    """
    raw = doc.xref_stream_raw(xref)  # type: ignore[no-untyped-call]
    if raw is None:
        raw = b""
    kind, value = doc.xref_get_key(xref, "Filter")  # type: ignore[no-untyped-call]
    filters = _normalise_filter(doc, kind, value)
    if filters is None:
        size = len(raw)
        if size > budget:
            raise ScanTooLargeError(
                f"Page {page_index + 1} of this PDF contains far more drawing data than a "
                f"scanned page can (over {MAX_PAGE_CONTENT_BYTES // 1_000_000} MB). "
                "Re-export it as a plain scan.",
                reason="page_content",
            )
        return size
    if len(filters) == 1 and filters[0] in _FLATE_FILTER_NAMES:
        return _bounded_inflate_size(raw, budget=budget, page_index=page_index)
    raise ScanUnsupportedEncodingError(
        _UNSUPPORTED_FILTER_MESSAGE.format(page=page_index + 1), reason="content_encoding"
    )


_REF_RE = re.compile(r"(\d+)\s+\d+\s+R")
#: The resource categories a content stream can name (ISO 32000-1 Table 33),
#: minus ``/Font`` (walked separately, see :func:`_resources_refs`) and
#: ``/ProcSet`` (an array of names). A renderer looks resources up only under
#: these keys, so nothing filed under any other ``/Resources`` key is drawn.
_RESOURCE_CATEGORIES = ("XObject", "Pattern", "ExtGState", "Shading", "ColorSpace", "Properties")


@dataclass
class _ContentBudget:
    """Running totals shared across the scan's page walks.

    ``scan_total`` is fixed for the duration of a page (everything counted
    on *earlier* pages); ``page_total`` and ``objects`` accumulate as the
    current page is walked, then fold into ``scan_total`` once it is done.
    """

    scan_total: int = 0
    page_total: int = 0
    objects: int = 0


@dataclass(frozen=True)
class _PageTree:
    """The document's page tree, by object number, read before any page is walked.

    ``xrefs`` is the catalog, its ``/Pages`` root, every node reached from
    the root through ``/Kids`` -- the path both renderers take to find a
    page -- and every page. Membership is by object identity, found by
    following the structure a renderer follows, never by a ``/Type`` or a
    key name, so an object cannot talk its way out of (or into) the set.
    ``/Parent`` does not add to it: a page's ``/Parent`` can name any
    object, and one it named would otherwise be hidden from the walk.

    ``holders`` maps a page to the node(s) whose ``/Resources`` it uses.
    ``/Resources`` is inheritable (ISO 32000-1 Table 30) and resolved up
    ``/Parent``; the two renderers pick the ancestor differently -- MuPDF
    the nearest node that has the key at all, pdfium the nearest whose
    value resolves to an object -- so both are kept, and a page's walk
    starts from each.
    """

    xrefs: frozenset[int]
    holders: dict[int, tuple[int, ...]]


#: How the walk met a reference, which decides how a renderer uses it.
#: ``"xobject"``: filed under a ``/XObject`` resource map and drawn by its
#: ``/Subtype`` -- an image is decoded, anything else is run as a form.
#: ``"font"``: filed under ``/Font`` and loaded by the font engine.
#: ``"any"``: everywhere else -- an annotation appearance, a glyph
#: procedure, a soft mask's group, a pattern cell, an entry of a container
#: -- where a renderer runs a stream as a form whatever its ``/Subtype``.
_Role = Literal["xobject", "font", "any"]


@dataclass
class _PageWalk:
    """One page's walk: its budget, the page tree, and what it has visited.

    One set per kind of work, each done at most once per object:
    ``seen`` -- expanded in full (decoded bytes counted if a stream, every
    reference followed); ``image_seen`` -- declared size pixel-checked;
    ``font_seen`` -- met as a non-Type3 ``/Font`` and deliberately not
    expanded; ``annot_seen`` -- ``/AP`` read as an ``/Annots`` entry. Doing
    one kind of work never marks another done, so what happens to an
    object depends only on the set of roles it is reached in, never on the
    order the walk meets them.

    ``deferred`` maps an object expanded as a drawn Form XObject to the
    references its :data:`_FORM_PRIVATE_KEYS` named, which that expansion
    did not follow. Met again in any other role, the object is already in
    ``seen``, so the walk follows them then (see :func:`_walk_resource_graph`).
    """

    page_index: int
    tree: frozenset[int]
    budget: _ContentBudget
    seen: set[int] = field(default_factory=set)
    font_seen: set[int] = field(default_factory=set)
    image_seen: set[int] = field(default_factory=set)
    annot_seen: set[int] = field(default_factory=set)
    deferred: dict[int, list[int]] = field(default_factory=dict)


def _key(doc: pymupdf.Document, xref: int, key: str) -> tuple[str, str]:
    """One ``xref_get_key`` result, typed."""
    kind, value = doc.xref_get_key(xref, key)  # type: ignore[no-untyped-call]
    return str(kind), str(value)


def _ref_target(doc: pymupdf.Document, kind: str, value: str) -> int:
    """The object number of an ``xref``-kind value, or 0 if it names no object.

    An out-of-range reference resolves to ``null`` in every reader, so it
    leads nowhere; 0 lets callers drop it without reading it.
    """
    if kind != "xref":
        return 0
    target = int(value.split()[0])
    return target if 0 < target < doc.xref_length() else 0  # type: ignore[no-untyped-call]


def _name(doc: pymupdf.Document, xref: int, key: str) -> str:
    """``xref``'s ``key`` as a name (``"/Form"``), or ``""`` if it is not one.

    Resolves one level of indirection: a renderer reads ``/Subtype 7 0 R``,
    object 7 being ``/Form``, exactly as it reads ``/Subtype /Form``.
    """
    kind, value = _key(doc, xref, key)
    if kind == "xref":
        target = _ref_target(doc, kind, value)
        value = doc.xref_object(target).strip() if target else ""  # type: ignore[no-untyped-call]
        kind = "name" if value.startswith("/") else ""
    return value if kind == "name" else ""


def _collection_refs(
    doc: pymupdf.Document, kind: str, value: str, *, limit: int | None = None
) -> list[int]:
    """Every indirect reference named inside a dict/array-shaped value.

    ``kind``/``value`` are one ``xref_get_key`` result. An inline dict or
    array is scanned as written; an indirect one (``kind == "xref"``) is
    read and its own text scanned instead, so a map stored as its own
    object (``/XObject 6 0 R``) yields the references *inside* it. A
    reference's name within the map (a resource name, an appearance-state
    name, a glyph name) plays no part: every reference found is returned
    -- or only the first ``limit``, for a caller that refuses past it.
    """
    if kind == "xref":
        target = _ref_target(doc, kind, value)
        if not target:
            return []
        text = doc.xref_object(target)  # type: ignore[no-untyped-call]
    elif kind in ("dict", "array"):
        text = value
    else:
        return []
    return [int(m.group(1)) for m in itertools.islice(_REF_RE.finditer(text), limit)]


def _enter(xref: int, seen: set[int], walk: _PageWalk) -> bool:
    """Register a visit to ``xref`` in ``seen``; ``False`` if already there (skip it).

    The single choke point for cycle prevention and the per-page object cap
    (:data:`_MAX_OBJECTS_PER_PAGE`): every object the walk looks at is
    registered here before it is expanded.
    """
    if xref in seen:
        return False
    seen.add(xref)
    walk.budget.objects += 1
    if walk.budget.objects > _MAX_OBJECTS_PER_PAGE:
        raise ScanTooLargeError(
            _TOO_MANY_OBJECTS_MESSAGE.format(page=walk.page_index + 1), reason="page_objects"
        )
    return True


def _count_stream(doc: pymupdf.Document, xref: int, walk: _PageWalk) -> None:
    """Add ``xref``'s decoded size to the page total, or refuse."""
    budget = walk.budget
    page_budget = MAX_PAGE_CONTENT_BYTES - budget.page_total
    scan_budget = MAX_SCAN_CONTENT_BYTES - budget.scan_total - budget.page_total
    try:
        size = decoded_stream_size(
            doc, xref, budget=min(page_budget, scan_budget), page_index=walk.page_index
        )
    except ScanTooLargeError:
        if scan_budget < page_budget:
            # The scan cap bit, not the page cap: say so.
            raise ScanTooLargeError(_WHOLE_SCAN_MESSAGE, reason="scan_content") from None
        raise
    budget.page_total += size


def _parent(doc: pymupdf.Document, xref: int) -> int:
    """``xref``'s ``/Parent`` object number, or 0 for none."""
    return _ref_target(doc, *_key(doc, xref, "Parent"))


def _resources_state(doc: pymupdf.Document, xref: int) -> tuple[bool, bool]:
    """Whether ``xref`` has a ``/Resources`` key, and whether it resolves to an object."""
    kind, value = _key(doc, xref, "Resources")
    if kind == "null":
        return False, False
    if kind != "xref":
        return True, True
    target = _ref_target(doc, kind, value)
    resolves = bool(target) and doc.xref_object(target).strip() != "null"  # type: ignore[no-untyped-call]
    return True, resolves


@dataclass(frozen=True)
class _PageBound:
    """How many pages :func:`_page_tree` may find, and what to say past it."""

    pages: int
    message: str
    reason: str

    @property
    def work(self) -> int:
        """How many ``/Kids`` references the descent may take on, repeats included.

        Generous against any real tree of ``pages`` pages: one reference per
        page plus one per inner node, and the spec lets an inner node have a
        single kid, so a page may sit under several one-kid wrappers. Eight
        per page (plus slack for the root and a few grouping nodes) admits
        up to about seven wrappers above every page, far past any writer
        seen. It bounds work, not pages: past it the refusal says so
        (:data:`_PAGE_TREE_TOO_COMPLEX_MESSAGE`), never "more than N pages".
        """
        return 8 * self.pages + 16


#: :func:`check_pdf_content`'s bound: the page cap, held against the real tree.
_SCAN_PAGE_BOUND = _PageBound(MAX_SCAN_PAGES, _SCAN_PAGES_MESSAGE, "page_cap")
#: :func:`check_pdf_page_content`'s bound, the crop route's.
_CROP_PAGE_BOUND = _PageBound(MAX_CROP_PAGES, _CROP_PAGES_MESSAGE, "crop_page_cap")


def _page_tree(doc: pymupdf.Document, *, bound: _PageBound) -> _PageTree:
    """The page tree's object numbers and each page's resource holders.

    Descends ``/Kids`` from the catalog's ``/Pages`` root, reading each
    node once (a node met again -- a ``/Kids`` cycle -- is not re-read).
    Climbs ``/Parent`` from every page for the holders only; a node already
    climbed from an earlier page ends the climb (its answer is reused), and
    a node met twice on one climb (a ``/Parent`` cycle) ends it too. A page
    whose number pymupdf cannot give stops the build there:
    :func:`check_pdf_content` meets the same failure on the same page and
    refuses the file, and :func:`check_pdf_page_content`, which can be
    asked for a later page, refuses that page (see :func:`_check_page`).

    Both halves cost time in proportion to the tree's size, whatever
    ``/Count`` declares -- and ``doc.page_count`` is that ``/Count``, so a
    cap checked against it alone is dodged by understating it. ``bound``
    (:data:`MAX_SCAN_PAGES` for :func:`check_pdf_content`,
    :data:`MAX_CROP_PAGES` for :func:`check_pdf_page_content`) holds the
    cap against the real tree, and bounds the work, with two counts:

    * Pages. MuPDF's rule: ``/Type`` decides, and ``/Kids`` only when
      ``/Type`` is neither. A ``/Type /Page`` is a page -- and one that
      names ``/Kids`` is refused outright as malformed
      (:data:`_PAGE_STRUCTURE_MALFORMED_MESSAGE`, T9b review round 1):
      MuPDF takes the node as a page while pdfium descends its kids, so the
      readers disagree on which object a page index names even when their
      counts match. A ``/Type /Pages`` is not a page, even with ``/Kids []``
      -- MuPDF and pdfium both count an empty one as zero pages; a node with
      neither type is a page if it names no ``/Kids``. Every reference to
      a *page* counts, repeats included: a reader counts a page named
      twice as two. A repeated inner node is descended once, so the pages
      under it count once; that can only undercount, and undercounting is
      safe here because both readers find and render pages by ``/Count``,
      which ``doc.page_count`` already held to the cap before this read.
      Past ``bound.pages`` the descent stops with
      :class:`ScanTooLargeError` (``bound.message``), which is then true.
    * Work. Every ``/Kids`` reference the descent takes on counts, pages or
      not, repeats included, and no ``/Kids`` array is read further than
      the budget left. Past ``bound.work`` it stops with
      :class:`ScanTooLargeError` (:data:`_PAGE_TREE_TOO_COMPLEX_MESSAGE`),
      which says the tree is too complex, not that it has too many pages.
      The spec lets an inner node have a single kid, so node count says
      nothing about page count; this is a generous cost bound only.

    So the descent reads at most ``bound.work`` references and a node each,
    whatever the file declares. The climb stops with
    :class:`ScanRejectedError` once it has read more than ``bound.work``
    distinct objects: every ancestor of a page in a well-formed tree is a
    descended node, and the descent took on no more than that.

    Defence in depth (T9b review round 1): the set of pages the descent
    found, by object number, must equal the set MuPDF numbers
    (``page_xref`` over ``doc.page_count``, collected in the climb loop at
    no extra read). A page the tree holds that MuPDF does not number -- a
    ``/Count`` short of the real kids, or any other way the readers could
    resolve the tree differently -- is refused with
    :data:`_PAGE_STRUCTURE_MALFORMED_MESSAGE`. A page past a
    ``page_xref`` failure is left to :func:`_check_page`, which refuses it.
    """
    budget = bound.work
    nodes: set[int] = set()
    # node -> whether it is a page; a node is read once, however often named.
    is_page: dict[int, bool] = {}
    pages = 0
    xref_length = doc.xref_length()  # type: ignore[no-untyped-call]
    catalog = doc.pdf_catalog()  # type: ignore[no-untyped-call]
    pending: list[int] = []
    if 0 < catalog < xref_length:
        nodes.add(catalog)
        is_page[catalog] = False  # named from /Kids, it leads nowhere new
        pending.append(_ref_target(doc, *_key(doc, catalog, "Pages")))
    taken = len(pending)
    while pending:
        node = pending.pop()
        if not 0 < node < xref_length:
            continue
        if node not in is_page:
            nodes.add(node)
            kids = _collection_refs(doc, *_key(doc, node, "Kids"), limit=budget - taken + 1)
            taken += len(kids)
            if taken > budget:
                raise ScanTooLargeError(_PAGE_TREE_TOO_COMPLEX_MESSAGE, reason="page_tree")
            node_type = _name(doc, node, "Type")
            if node_type == "/Page" and kids:
                # MuPDF takes this node as one page, pdfium descends its kids:
                # not valid PDF, and the readers disagree on which object a
                # page index names, whatever their counts (T9b review round 1).
                raise ScanRejectedError(_PAGE_STRUCTURE_MALFORMED_MESSAGE, reason="malformed")
            is_page[node] = node_type == "/Page" or (not kids and node_type != "/Pages")
            pending.extend(kids)
        if is_page[node]:
            pages += 1
            if pages > bound.pages:
                raise ScanTooLargeError(bound.message, reason=bound.reason)
    # node -> (nearest node at or above it with a /Resources key,
    #          nearest node at or above it whose /Resources resolves)
    nearest: dict[int, tuple[int | None, int | None]] = {}
    numbered: set[int] = set()
    for index in range(doc.page_count):
        try:
            page_xref = doc.page_xref(index)  # type: ignore[no-untyped-call]
        except Exception:
            break
        nodes.add(page_xref)
        numbered.add(page_xref)
        chain: list[int] = []
        node = page_xref
        while node and node not in nearest and node not in chain:
            chain.append(node)
            if len(nearest) + len(chain) > budget:
                raise ScanRejectedError(
                    _MALFORMED_STRUCTURE_MESSAGE.format(page=index + 1), reason="malformed"
                )
            node = _parent(doc, node)
        above = nearest.get(node, (None, None))
        for member in reversed(chain):
            has_key, resolves = _resources_state(doc, member)
            above = (member if has_key else above[0], member if resolves else above[1])
            nearest[member] = above
    # Defence in depth (T9b review round 1): the pages the descent found must
    # be the pages MuPDF numbers. A page it holds that MuPDF does not number
    # is one a reader resolving the tree its own way may render unmeasured.
    if numbered != {node for node, page in is_page.items() if page}:
        raise ScanRejectedError(_PAGE_STRUCTURE_MALFORMED_MESSAGE, reason="malformed")
    holders = {
        node: tuple(sorted({h for h in pair if h is not None})) for node, pair in nearest.items()
    }
    return _PageTree(xrefs=frozenset(nodes), holders=holders)


#: Keys of a Form XObject's own dictionary that hold no drawing data:
#: ``/PieceInfo`` (page-piece dictionaries, ISO 32000-1 section 14.5) and
#: ``/Metadata`` (metadata streams, section 14.3.2). pdfTeX copies
#: Illustrator's ``/PieceInfo`` into every form it includes (#261). The
#: names mean this only on a form a renderer draws as a form: the same
#: object read as a container (a Type3 ``/CharProcs`` dict, an appearance
#: state dict) is looked up by arbitrary names, and a glyph or a state named
#: ``/PieceInfo`` is drawn. So :func:`_dict_refs` holds them back only for a
#: ``/Subtype /Form`` stream met in the ``"xobject"`` role, and the walk
#: follows them if it meets the same object in any other role.
_FORM_PRIVATE_KEYS = frozenset({"PieceInfo", "Metadata"})


def _names_a_dict(doc: pymupdf.Document, kind: str, value: str) -> bool:
    """Whether one ``xref_get_key`` result is a dictionary, inline or indirect.

    A stream is not one here, though it has a dictionary: what a renderer
    can run as a form or a glyph is a stream, never a plain dict.
    """
    if kind == "dict":
        return True
    target = _ref_target(doc, kind, value)
    if not target or doc.xref_is_stream(target):  # type: ignore[no-untyped-call]
        return False
    return str(doc.xref_object(target)).lstrip().startswith("<<")  # type: ignore[no-untyped-call]


def _dict_refs(
    doc: pymupdf.Document, xref: int, *, drawn_form: bool
) -> tuple[list[int], list[int]]:
    """Every reference in ``xref``'s dictionary, and the ones held back.

    Returns ``(follow, held)``. Works for a stream's dictionary and a plain
    dict alike. A reference's key decides nothing, with two exceptions:

    * ``/Resources`` naming a dictionary (inline or indirect) is left to
      :func:`_resources_refs`, which reads it by category and keeps each
      reference's role. Naming anything else -- a stream, a bare reference
      -- it is followed like any key: in a ``/CharProcs`` or appearance
      state dict, ``/Resources`` is just the name of a glyph or a state,
      and a renderer draws the stream it names.
    * With ``drawn_form`` (``xref`` is a ``/Subtype /Form`` stream met in
      the ``"xobject"`` role), references under :data:`_FORM_PRIVATE_KEYS`
      are returned in ``held`` instead of ``follow``.

    Otherwise an object used as a container (a graphics state, an
    appearance state dict, a glyph-procedure dict, a stream that is also a
    soft mask) is read by whatever key the renderer looks up, and nothing
    here assumes which.
    """
    follow: list[int] = []
    held: list[int] = []
    for key in doc.xref_get_keys(xref):  # type: ignore[no-untyped-call]
        kind, value = _key(doc, xref, key)
        if key == "Resources" and _names_a_dict(doc, kind, value):
            continue
        refs = held if drawn_form and key in _FORM_PRIVATE_KEYS else follow
        if kind == "xref":
            target = _ref_target(doc, kind, value)
            if target:
                refs.append(target)
        elif kind in ("dict", "array"):
            refs.extend(int(m.group(1)) for m in _REF_RE.finditer(value))
    return follow, held


def _resources_refs(doc: pymupdf.Document, container_xref: int) -> list[tuple[int, _Role]]:
    """Every ref in ``container_xref``'s ``/Resources``, tagged with its :data:`_Role`.

    Reads only the categories a content stream can name
    (:data:`_RESOURCE_CATEGORIES`, plus ``/Font``), each directly or through
    one indirect map. The role comes from the category the reference is
    filed under, never from the object's own ``/Type``. An object with no
    ``/Resources`` key at all costs one read.
    """
    refs: list[tuple[int, _Role]] = []
    if _key(doc, container_xref, "Resources")[0] == "null":
        return refs
    for category in _RESOURCE_CATEGORIES:
        role: _Role = "xobject" if category == "XObject" else "any"
        kind, value = _key(doc, container_xref, f"Resources/{category}")
        refs.extend((ref, role) for ref in _collection_refs(doc, kind, value))
    kind, value = _key(doc, container_xref, "Resources/Font")
    refs.extend((ref, "font") for ref in _collection_refs(doc, kind, value))
    return refs


def _walk_resource_graph(
    doc: pymupdf.Document, start: list[tuple[int, _Role]], walk: _PageWalk
) -> None:
    """Count every drawable object reachable from ``start``, iteratively.

    Guarantees, for every object reached:

    * Any object reachable from a page is expanded in full exactly once,
      regardless of role or visit order: a stream has its decoded size
      counted once, and every object has its ``/Resources`` (by category,
      with roles, when it names a dictionary) and every other reference in
      its dictionary -- or, for an array, every reference in it -- walked.
      An object used as a container (a graphics state, an appearance state
      dict, a glyph-procedure dict, a soft mask) is read by whatever key
      the renderer looks up, so no key is assumed (see :func:`_dict_refs`).
      Over-counting a stream that is never drawn is accepted: it can only
      reject.
    * One edge depends on the role (#261): a ``/Subtype /Form`` stream met
      under ``/XObject`` is drawn as a form, so its
      :data:`_FORM_PRIVATE_KEYS` are page-piece data and XMP, not drawing,
      and are not followed. They are kept in ``walk.deferred``; met again
      in any other role -- read as ``/CharProcs``, as an appearance state
      dict, or as any other container -- the object is already expanded,
      but those references are followed then. Either order of meeting
      gives the same count.
    * Two roles narrow this, and only for that role: an image met under
      ``/XObject`` is decoded as an image, so its declared size and its
      masks' are checked against their own mode's pixel cap
      (:func:`_image_pixel_cap`) instead; a
      non-Type3 font met under ``/Font`` is loaded by the font engine, so it
      is not expanded. Reached in any other role too, the same object is
      also expanded in full (an appearance stream labelled ``/Image`` is
      run as a form). Every image-labelled stream is size-checked once,
      whatever role it is reached in. Classification reads ``/Subtype``
      through one level of indirection, never ``/Type``.
    * Reaching a page-tree node (``walk.tree``, see :class:`_PageTree`) in
      any role, even one already handled, rejects the file with
      :class:`ScanRejectedError`; the check runs before any visited-set
      test. A tree node can double as any container a renderer draws
      through, so it can be neither skipped (a bomb behind it would pass)
      nor expanded (the walk would climb into every other page). A
      well-formed file never draws from its own page tree; like the rest of
      this module's fail-closed rules, the accepted cost is a 422 for a
      malformed but harmless file that does. An annotation's ``/Dest``,
      ``/A``, ``/P``, ``/Parent`` or ``/Popup`` is never followed (see
      :func:`_walk_annotations`), so a link to another page still passes.
    * The walk uses an explicit stack, so nesting depth is bounded only by
      :data:`_MAX_OBJECTS_PER_PAGE`, never by Python's recursion limit.
    """
    xref_length = doc.xref_length()  # type: ignore[no-untyped-call]
    stack = list(start)
    while stack:
        ref, role = stack.pop()
        if not 0 < ref < xref_length:
            continue  # an out-of-range reference is null in every reader
        if ref in walk.tree:
            raise ScanRejectedError(
                _MALFORMED_STRUCTURE_MESSAGE.format(page=walk.page_index + 1), reason="malformed"
            )
        if ref in walk.seen:
            # Expanded in full already, except for the edges a drawn form
            # held back, which any other role must follow.
            if role != "xobject":
                stack.extend((target, "any") for target in walk.deferred.pop(ref, ()))
            continue
        is_stream = bool(doc.xref_is_stream(ref))  # type: ignore[no-untyped-call]
        subtype = _name(doc, ref, "Subtype")
        if role == "font" and subtype != "/Type3":
            _enter(ref, walk.font_seen, walk)
            continue
        if is_stream and subtype == "/Image":
            if _enter(ref, walk.image_seen, walk):
                _check_image_xref(doc, ref, page_index=walk.page_index)
            if role == "xobject":
                continue
        _enter(ref, walk.seen, walk)
        if is_stream:
            _count_stream(doc, ref, walk)
        if is_stream or doc.xref_get_keys(ref):  # type: ignore[no-untyped-call]
            stack.extend(_resources_refs(doc, ref))
            drawn_form = is_stream and role == "xobject" and subtype == "/Form"
            follow, held = _dict_refs(doc, ref, drawn_form=drawn_form)
            stack.extend((target, "any") for target in follow)
            if held:
                walk.deferred[ref] = held
        else:
            text = doc.xref_object(ref)  # type: ignore[no-untyped-call]
            stack.extend((int(m.group(1)), "any") for m in _REF_RE.finditer(text))


def _walk_annotations(doc: pymupdf.Document, page_xref: int, walk: _PageWalk) -> None:
    """Every annotation appearance stream reachable from the page.

    ``/Annots`` -> ``/AP`` -> ``/N``, ``/R``, ``/D``, each either a stream
    or a dict of appearance states each naming one. Every reference found
    under ``/AP`` is handed to :func:`_walk_resource_graph` in the
    ``"any"`` role: a renderer runs an appearance stream as a form whatever
    its ``/Subtype`` says, and a state dict is expanded as a container.

    Each entry's ``/AP`` is read even if the same object was already walked
    as content (``annot_seen`` is its own set). An entry that is a
    page-tree node rejects the file, as in :func:`_walk_resource_graph`.
    Nothing else of an annotation is followed -- not ``/Dest``, ``/A``,
    ``/P``, ``/Parent`` or ``/Popup`` -- so a link to another page passes.
    """
    ap_refs: list[tuple[int, _Role]] = []
    xref_length = doc.xref_length()  # type: ignore[no-untyped-call]
    for annot_ref in _collection_refs(doc, *_key(doc, page_xref, "Annots")):
        if not 0 < annot_ref < xref_length:
            continue
        if annot_ref in walk.tree:
            raise ScanRejectedError(
                _MALFORMED_STRUCTURE_MESSAGE.format(page=walk.page_index + 1), reason="malformed"
            )
        if not _enter(annot_ref, walk.annot_seen, walk):
            continue
        ap_refs.extend((ref, "any") for ref in _collection_refs(doc, *_key(doc, annot_ref, "AP")))
    _walk_resource_graph(doc, ap_refs, walk)


def _resolve_int(doc: pymupdf.Document, kind: str, value: str) -> int | None:
    r"""An integer-or-real dict value, resolving one level of indirection.

    ``kind == "xref"`` means the value is a bare number object
    (``5 0 obj\n40000\nendobj``), read back and parsed. A real
    (``40000.0``, pymupdf kind ``"float"``) is as large a declared size as
    the integer spelling; ``int(float(value))`` reads both.
    """
    if kind == "xref":
        target = _ref_target(doc, kind, value)
        if not target:
            return None
        text = doc.xref_object(target).strip()  # type: ignore[no-untyped-call]
        try:
            return int(float(text))
        except ValueError:
            return None
    if kind in ("int", "float"):
        try:
            return int(float(value))
        except ValueError:
            return None
    return None


#: The filters an unmasked one-component image may carry and still be judged
#: by its own mode (#273 item 3, owner decision S6). Each was measured inside
#: both workers at 159 Mpx (80 Mpx at 16 bits), and so was no filter: every
#: render path ended ``ok`` and pixel-identical to an unlimited render, the
#: worst single image at 31% of the worker's ``RLIMIT_DATA`` (a 25 MiB
#: sequential grey JPEG in extraction; Tasks 21 and 22). Many on one page add
#: up only for CCITT in extraction, about 19 MiB an image: still identical at
#: 27, a ``SandboxMemory`` refusal from 28; 20 grey Flate images reach 30%.
#: The gate guards against a silent failure, not a loud one: when pdfium
#: cannot get an image's buffer it can draw nothing and report no error, so
#: a page over its budget comes back blank (the Task 22 review saw a white
#: page under the limit that had ink without it). Excluded, so keeping the
#: colour cap: a progressive JPEG (68% of the limit, 429 MiB of 640 in
#: extraction, for one grey 159 Mpx image), and any DCT image whose stream is
#: not a sequential one-component JPEG (:func:`_is_sequential_grey_jpeg`),
#: since a JPEG holding 3 or 4 components decodes as such whatever the
#: dictionary says; JBIG2 (not generatable here), JPX (OpenJPEG holds 32-bit
#: samples) and every other filter or chain, until measured.
_GREY_PROVEN_FILTERS = frozenset({"/FlateDecode", "/CCITTFaxDecode", "/DCTDecode"})
#: The colour-space families that declare one component, read bare or as an
#: array's first name. ``/ICCBased`` is read by its ``/N``; anything else
#: (``/Indexed``, ``/Separation``, an inline-image abbreviation) is not.
_ONE_COMPONENT_FAMILIES = frozenset({"/DeviceGray", "/CalGray"})
#: How much of a DCT image's raw stream is read for its frame header.
_JPEG_HEADER_PREFIX_BYTES = 64 * 1024
#: The start-of-frame markers a sequential (non-progressive) JPEG opens with:
#: SOF0 baseline and SOF1 extended sequential, both Huffman-coded.
_SEQUENTIAL_SOF_MARKERS = frozenset({0xC0, 0xC1})
#: Every start-of-frame marker: ``0xC0``-``0xCF`` but DHT, JPG and DAC.
_SOF_MARKERS = frozenset(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}
#: Markers with no length field: TEM and the restart markers.
_STANDALONE_MARKERS = frozenset({0x01, *range(0xD0, 0xD8)})
#: SOI, EOI, SOS, DHP and EXP: met before any frame header, the stream is not
#: a plain sequential JPEG this check can vouch for.
_NO_FRAME_MARKERS = frozenset({0xD8, 0xD9, 0xDA, 0xDE, 0xDF})


def _resolved_text(doc: pymupdf.Document, kind: str, value: str) -> tuple[str, str]:
    """``(kind, value)`` with one level of indirection followed, as text.

    An ``xref`` value is read back as its object's text, its kind ``"name"``,
    ``"array"`` or ``"other"`` by its first character; an out-of-range
    reference becomes ``("null", "")``.
    """
    if kind != "xref":
        return kind, value
    target = _ref_target(doc, kind, value)
    if not target:
        return "null", ""
    text = doc.xref_object(target).strip()  # type: ignore[no-untyped-call]
    if text.startswith("/"):
        return "name", text
    if text.startswith("["):
        return "array", text
    return "other", text


def _is_one_component(doc: pymupdf.Document, xref: int) -> bool:
    """Whether image ``xref``'s ``/ColorSpace`` declares exactly one component.

    Reads a bare name, an array whose first name is one of
    :data:`_ONE_COMPONENT_FAMILIES` (``[/CalGray << ... >>]``), and
    ``[/ICCBased n 0 R]`` by its profile stream's ``/N``, following one
    indirection for the colour space and one for ``/N``. Anything else,
    unreadable included, is not.
    """
    kind, value = _resolved_text(doc, *_key(doc, xref, "ColorSpace"))
    if kind == "name":
        return value in _ONE_COMPONENT_FAMILIES
    if kind != "array":
        return False
    names = re.findall(r"/[^\s/\[\]<>()]+", value)
    if not names or not value.lstrip("[ \t\r\n").startswith(names[0]):
        return False
    if names[0] != "/ICCBased":
        return names[0] in _ONE_COMPONENT_FAMILIES
    ref = _REF_RE.search(value)
    profile = _ref_target(doc, "xref", f"{ref.group(1)} 0 R") if ref else 0
    if not profile or not doc.xref_is_stream(profile):  # type: ignore[no-untyped-call]
        return False
    return _resolve_int(doc, *_key(doc, profile, "N")) == 1


def _is_image_mask(doc: pymupdf.Document, xref: int) -> bool:
    kind, value = _resolved_text(doc, *_key(doc, xref, "ImageMask"))
    return value.strip() == "true" and kind in ("bool", "other")


def _jpeg_frame(prefix: bytes) -> tuple[int, int] | None:
    """``(SOF marker, component count)`` of the first frame header in ``prefix``, or ``None``.

    Walks the marker segments from SOI, skipping fill bytes, standalone
    markers and every other segment by its length. ``None`` when ``prefix``
    is not a JPEG, a segment is malformed, a marker in
    :data:`_NO_FRAME_MARKERS` (scan data, a hierarchical frame) comes first,
    or the header lies past the prefix.
    """
    if prefix[:2] != b"\xff\xd8":
        return None
    at = 2
    while at + 4 <= len(prefix):
        if prefix[at] != 0xFF:
            return None
        marker = prefix[at + 1]
        if marker == 0xFF:  # a fill byte before the marker
            at += 1
            continue
        if marker in _STANDALONE_MARKERS:
            at += 2
            continue
        if marker in _NO_FRAME_MARKERS:
            return None
        length = int.from_bytes(prefix[at + 2 : at + 4], "big")
        if length < 2:
            return None
        if marker in _SOF_MARKERS:
            # FF Cn, length (2), precision (1), height (2), width (2), components (1)
            return (marker, prefix[at + 9]) if at + 10 <= len(prefix) else None
        at += 2 + length
    return None


def _is_sequential_grey_jpeg(doc: pymupdf.Document, xref: int) -> bool:
    """Whether DCT image ``xref``'s JPEG opens with a sequential one-component frame.

    Reads at most :data:`_JPEG_HEADER_PREFIX_BYTES` of the raw stream (the
    whole stream if shorter) and never decodes it. True only for SOF0 or
    SOF1 declaring exactly one component (:func:`_jpeg_frame`); a stream
    MuPDF cannot open raw is not vouched for.
    """
    try:
        pdf = _mupdf.pdf_document_from_fz_document(doc.this)  # type: ignore[no-untyped-call]
        raw = _mupdf.pdf_open_raw_stream_number(pdf, xref)  # type: ignore[no-untyped-call]
        head = _mupdf.fz_open_null_filter(raw, _JPEG_HEADER_PREFIX_BYTES, 0)  # type: ignore[no-untyped-call]
        buffer = _mupdf.fz_read_all(head, 4096)  # type: ignore[no-untyped-call]
        prefix = bytes(buffer.fz_buffer_extract())
    except Exception:  # an unreadable stream keeps the colour cap, as before #273
        return False
    frame = _jpeg_frame(prefix[:_JPEG_HEADER_PREFIX_BYTES])
    return frame is not None and frame[0] in _SEQUENTIAL_SOF_MARKERS and frame[1] == 1


def _image_mode(doc: pymupdf.Document, xref: int) -> str:
    """The Pillow mode :func:`decode_pixel_cap` judges image ``xref`` as.

    Read from its dictionary (``/ImageMask``, ``/BitsPerComponent``,
    ``/ColorSpace``, ``/Filter``) and, for ``/DCTDecode`` only, its JPEG
    frame header; nothing is decoded. For an image with no filter or one
    filter in :data:`_GREY_PROVEN_FILTERS` (DCT only as a sequential grey
    JPEG):

    * ``"1"``: an image mask, or a one-component image at 1 bit;
    * ``"L"``: one component at 8 bits, or at a depth that cannot be read;
    * ``"I;16"``: one component at 16 bits.

    Everything else is ``"RGB"``, the flat colour cap: colour of any depth or
    component count, ``/Indexed``, an unknown or unreadable colour space,
    2- or 4-bit grey, and any other filter, chain or unreadable ``/Filter``.
    None of those was measured, so none is widened. An image with a mask is
    judged by :func:`_image_pixel_cap`, not here.
    """
    image_mask = _is_image_mask(doc, xref)
    if not (image_mask or _is_one_component(doc, xref)):
        return "RGB"
    kind, value = _key(doc, xref, "Filter")
    if kind != "null":  # absent: unfiltered, measured too
        filters = _normalise_filter(doc, kind, value)  # None: a /Filter of no readable shape
        if filters is None or len(filters) != 1 or filters[0] not in _GREY_PROVEN_FILTERS:
            return "RGB"
        if filters[0] == "/DCTDecode" and not _is_sequential_grey_jpeg(doc, xref):
            return "RGB"
    bits = _resolve_int(doc, *_key(doc, xref, "BitsPerComponent"))
    if image_mask or bits == 1:
        return "1"
    if bits is None or bits == 8:
        return "L"
    if bits == 16:
        return "I;16"
    return "RGB"


def _image_masks(doc: pymupdf.Document, xref: int, smask_xref: int = 0) -> tuple[list[int], bool]:
    """Image ``xref``'s mask streams, and whether it is masked, from its own dictionary.

    Returns ``(masks, masked)``. ``masks`` are the ``/SMask`` and ``/Mask``
    streams, each an image object decoded at its own declared size to render
    the image; ``smask_xref`` (``get_images``' column, 0 for none) is added
    only if it names a stream in range, since pymupdf puts an indirect
    ``/Mask`` there too, even one naming a colour-key array. A ``/Mask``
    array, direct or indirect (colour-key masking), is no allocation and
    leaves the image unmasked. Any other ``/SMask`` or ``/Mask`` value -- a
    dangling reference, a dictionary, a name -- makes ``masked`` true without
    a stream to judge: a key that cannot be read never widens the cap.
    """
    masks: list[int] = []
    unreadable = False
    for key in ("SMask", "Mask"):
        kind, value = _key(doc, xref, key)
        if kind == "null":
            continue
        target = _ref_target(doc, kind, value)
        if target and doc.xref_is_stream(target):  # type: ignore[no-untyped-call]
            masks.append(target)
        elif key == "Mask" and _resolved_text(doc, kind, value)[0] == "array":
            continue
        else:
            unreadable = True
    in_range = 0 < smask_xref < doc.xref_length()  # type: ignore[no-untyped-call]
    if in_range and smask_xref not in masks and doc.xref_is_stream(smask_xref):  # type: ignore[no-untyped-call]
        masks.append(smask_xref)
    return masks, unreadable or bool(masks)


def _image_pixel_cap(doc: pymupdf.Document, xref: int, *, masked: bool) -> int:
    """The most pixels image ``xref`` may declare.

    :func:`decode_pixel_cap` of its :func:`_image_mode`, unless it is
    ``masked``: an image drawn through a soft mask or a stream mask, and
    each such mask, keeps the colour cap. Rendering one costs the image and
    its mask together, and the Task 22 review measured a widened grey image
    with a widened grey soft mask rendering blank under the extraction
    worker's limit.
    """
    return decode_pixel_cap("RGB" if masked else _image_mode(doc, xref))


def _refuse_over(width: int, height: int, cap: int, *, page_index: int) -> None:
    if width * height > cap:
        raise ScanTooLargeError(
            _IMAGE_TOO_LARGE_MESSAGE.format(page=page_index + 1, mpx=width * height // 1_000_000),
            reason="image_px",
        )


def _check_declared_pixels(doc: pymupdf.Document, xref: int, *, cap: int, page_index: int) -> None:
    """Image object ``xref``'s own declared size against ``cap``.

    ``/Width`` and ``/Height`` may be integers or reals, direct or
    indirect (:func:`_resolve_int`). Used for images the walk reaches and
    for every image's ``/SMask`` and stream ``/Mask``.
    """
    width = _resolve_int(doc, *_key(doc, xref, "Width"))
    height = _resolve_int(doc, *_key(doc, xref, "Height"))
    if width is not None and height is not None:
        _refuse_over(width, height, cap, page_index=page_index)


def _check_masks(doc: pymupdf.Document, masks: list[int], *, page_index: int) -> None:
    """Each of an image's mask streams (:func:`_image_masks`) against the colour cap."""
    for mask in masks:
        _check_declared_pixels(doc, mask, cap=decode_pixel_cap("RGB"), page_index=page_index)


def _check_image_xref(doc: pymupdf.Document, xref: int, *, page_index: int) -> None:
    """An image the walk reached: its declared size, then its masks'.

    ``page.get_images(full=True)`` does not list images inside annotation
    appearance streams or tiling patterns, so the walk checks every image
    it reaches itself. The per-image limit has no running total, so an
    image checked both here and via ``get_images`` is judged the same way
    twice.
    """
    masks, masked = _image_masks(doc, xref)
    cap = _image_pixel_cap(doc, xref, masked=masked)
    _check_declared_pixels(doc, xref, cap=cap, page_index=page_index)
    _check_masks(doc, masks, page_index=page_index)


def _tuple_int(value: object) -> int:
    """``int()`` for one element of an untyped-library tuple.

    pymupdf ships no type stubs, so ``page.get_images(full=True)``'s tuples
    are ``object`` as far as mypy is concerned, even though every element is
    really an ``int``.
    """
    return int(value)  # type: ignore[call-overload,no-any-return]


def _check_image_and_masks(
    doc: pymupdf.Document, image: tuple[object, ...], *, page_index: int
) -> None:
    """Reject an image or its mask whose declared pixels exceed its cap.

    ``image`` is one entry of ``page.get_images(full=True)``:
    ``(xref, smask_xref, width, height, ...)``, sizes as pymupdf read them.
    The cap is :func:`_image_pixel_cap` of ``xref``'s own dictionary and
    masks; the tuple's depth and colour-space fields are not used, so this
    and the walk's :func:`_check_image_xref` judge one image alike.
    """
    xref, smask_xref, width, height = (
        _tuple_int(image[0]),
        _tuple_int(image[1]),
        _tuple_int(image[2]),
        _tuple_int(image[3]),
    )
    masks, masked = _image_masks(doc, xref, smask_xref)
    _refuse_over(width, height, _image_pixel_cap(doc, xref, masked=masked), page_index=page_index)
    _check_masks(doc, masks, page_index=page_index)


def _check_object_streams(doc: pymupdf.Document) -> None:
    """Bound the file's object count and its object streams, before any object loads.

    Task 9c review round 1. MuPDF parses every object in an object stream as
    soon as any one of them is needed, so this runs first, straight after
    the open, on the xref table alone: each entry of type ``"o"`` names its
    container, and no object is loaded to find them. Each container's
    decoded size then goes through the bounded inflate
    (:func:`decoded_stream_size`), which reads only the raw stream and its
    dictionary. Over :data:`MAX_OBJECT_STREAM_BYTES` in total, or more
    objects than :data:`MAX_PDF_OBJECTS`, the file is refused.

    Residual, not closable here: MuPDF's open has already loaded the catalog
    (and pymupdf the trailer ``/Info``), so a container holding one of those
    was parsed before this ran -- as it is by every MuPDF open, upload's
    included.
    """
    xref_length = int(doc.xref_length())  # type: ignore[no-untyped-call]
    if xref_length > MAX_PDF_OBJECTS:
        raise ScanTooLargeError(_TOO_MANY_PDF_OBJECTS_MESSAGE, reason="too_many_objects")
    try:
        pdf = _mupdf.pdf_document_from_fz_document(doc.this)  # type: ignore[no-untyped-call]
        containers: set[int] = set()
        for number in range(1, xref_length):
            entry = _mupdf.ll_pdf_get_xref_entry_no_null(pdf.m_internal, number)  # type: ignore[no-untyped-call]
            if entry.type == "o" and 0 < entry.ofs < xref_length:
                containers.add(int(entry.ofs))
    except Exception as exc:
        raise ScanRejectedError(_UNCHECKABLE_MESSAGE, reason="uncheckable") from exc
    total = 0
    for container in sorted(containers):
        if not doc.xref_is_stream(container):  # type: ignore[no-untyped-call]
            continue  # names no stream: MuPDF resolves its objects to null
        try:
            total += decoded_stream_size(
                doc, container, budget=MAX_OBJECT_STREAM_BYTES - total, page_index=0
            )
        except ScanUnsupportedEncodingError as exc:
            raise ScanRejectedError(
                _OBJECT_STREAM_ENCODING_MESSAGE, reason="objstm_encoding"
            ) from exc
        except ScanTooLargeError as exc:
            raise ScanTooLargeError(_OBJECT_STREAMS_MESSAGE, reason="objstm_bomb") from exc


def check_pdf_content(doc: pymupdf.Document, *, pdfium_pages: int | None = None) -> None:
    """Refuse a document whose page content would blow the render (Task 11b).

    Per page, into the shared :data:`MAX_PAGE_CONTENT_BYTES` /
    :data:`MAX_SCAN_CONTENT_BYTES` budgets, each object counted at most
    once per page: the page's own content stream(s), and everything
    :func:`_walk_resource_graph` reaches from the page's ``/Resources``
    (its own or inherited, see :class:`_PageTree`) and from its
    annotations' appearance streams -- every stream a renderer may run as
    drawing operators (forms, appearance streams, tiling patterns, Type3
    glyph procedures, soft-mask groups), at any depth. A second, independent cap
    (:data:`_MAX_OBJECTS_PER_PAGE`) bounds how many objects one page's walk
    may look at, however small each is.

    Images are not content and their streams are never read (but for the
    first 64 KiB of a DCT image, for its frame header); instead each
    image's DECLARED ``/Width x /Height`` -- and its ``/SMask``'s and
    stream ``/Mask``'s -- is checked against :func:`_image_pixel_cap`:
    :func:`decode_pixel_cap` for the mode an unmasked image declares
    (:func:`_image_mode`), the colour cap for a masked image and its masks,
    because the renderer allocates for the declared size whatever the
    stream holds.
    Images are found both by ``page.get_images(full=True)`` and by the
    walk, which reaches the ones ``get_images`` does not list.

    The page tree (:func:`_page_tree`) is read once, up front: a walk that
    reaches it from a page's drawing resources rejects the file (see
    :func:`_walk_resource_graph`), and each page's walk starts from the
    ``/Resources`` it inherits. That read also holds :data:`MAX_SCAN_PAGES`
    against the tree's real pages, not only the declared ``/Count``, and
    stops once past it, so its cost is bounded by the cap too.

    Left alone: an encrypted document (its streams cannot be read;
    extraction fails on it later) and a non-PDF document (an ``image/*``
    upload opened by :mod:`pymupdf` for its preview has no page tree).

    Task 9b: the check must cover every page a renderer will render, so it
    fails closed when it cannot. A ``page_count`` MuPDF cannot read, a
    page it counted but cannot load or number (``load_page``/``page_xref``
    raising -- pdfium may still render that page, as the page-kids bomb
    showed), and, when the caller passes ``pdfium_pages`` (the count pdfium
    renders extraction by), a different count from MuPDF's: each is a
    :class:`ScanRejectedError`. They used to propagate and pass.

    Fails closed: any other exception while reading the page tree or
    walking a page -- a pymupdf quirk, a ``RecursionError`` inside
    ``get_images``, a bug here -- rejects the file with
    :class:`ScanRejectedError`. The accepted cost is that some malformed
    but harmless files get a 422 asking for a re-export instead of
    passing: a page whose ``/Contents`` is a name or names an object that
    is not a stream, or whose ``/Contents``, ``/Annots`` or drawing
    resources name a page-tree node, or a ``/Count`` past the real pages.

    Known gap: an inline image (``BI ... ID ... EI``) is not checked for
    its declared size. Its bytes count toward the page's content budget
    (they live in the content stream), but a large *declared* size on a
    small inline image is left to the render-sandbox follow-up the brief's
    decision 4 recommends.
    """
    if not doc.is_pdf:
        return
    if doc.needs_pass:
        return
    _check_object_streams(doc)
    # Task 9b: read once. MuPDF can lower its own count mid-walk, after a
    # page it counted fails to resolve; every page counted here is walked.
    try:
        page_count = int(doc.page_count)
    except Exception as exc:
        raise ScanRejectedError(_PAGE_COUNT_UNREADABLE_MESSAGE, reason="uncheckable") from exc
    # Final review M1: the walk visits every page, so a document over the
    # page cap is refused before any of it is read, whoever the caller is.
    # `page_count` is the declared `/Count`; `_page_tree` holds the same cap
    # against the real tree, so understating `/Count` does not dodge it.
    if page_count > MAX_SCAN_PAGES:
        raise ScanTooLargeError(
            f"The scan has {page_count} pages; the limit is {MAX_SCAN_PAGES}.", reason="page_cap"
        )
    # Task 9b: extraction renders with pdfium. A page it counts that MuPDF
    # does not is a page this walk never measures (a `/Count 0` over real
    # kids: MuPDF sees none, pdfium renders them all).
    if pdfium_pages is not None and page_count != pdfium_pages:
        raise ScanRejectedError(_PAGE_COUNT_UNREADABLE_MESSAGE, reason="reader_disagreement")
    try:
        tree = _page_tree(doc, bound=_SCAN_PAGE_BOUND)
    except ScanRejectedError:
        raise
    except Exception as exc:
        raise ScanRejectedError(_WALK_FAILED_MESSAGE.format(page=1), reason="uncheckable") from exc
    budget = _ContentBudget()
    for page_index in range(page_count):
        _check_page(doc, tree, budget, page_index)


def _check_page(
    doc: pymupdf.Document, tree: _PageTree, budget: _ContentBudget, page_index: int
) -> None:
    """One page's share of :func:`check_pdf_content`: images, contents, resources, annotations.

    Fails closed on a page ``tree`` has no holders entry for. Every page
    :func:`_page_tree` reached has one, so this refuses only a page past
    the point where the tree build stopped -- which :func:`check_pdf_content`
    never reaches, and :func:`check_pdf_page_content` can be asked for.
    Walking it with no holders would skip its inherited ``/Resources``.

    Fails closed on a page MuPDF counted but cannot load or number (Task
    9b): another reader can still render it, unmeasured.
    """
    try:
        page = doc.load_page(page_index)  # type: ignore[no-untyped-call]
        page_xref = doc.page_xref(page_index)  # type: ignore[no-untyped-call]
    except Exception as exc:
        raise ScanRejectedError(
            _PAGE_UNREADABLE_MESSAGE.format(page=page_index + 1), reason="uncheckable"
        ) from exc
    holders = tree.holders.get(page_xref)
    if holders is None:
        raise ScanRejectedError(
            _MALFORMED_STRUCTURE_MESSAGE.format(page=page_index + 1), reason="malformed"
        )
    budget.page_total = 0
    budget.objects = 0
    walk = _PageWalk(page_index=page_index, tree=tree.xrefs, budget=budget)
    try:
        for image in page.get_images(full=True):
            _check_image_and_masks(doc, image, page_index=page_index)
        start: list[tuple[int, _Role]] = []
        for xref in page.get_contents():
            xref = int(xref)
            if xref in tree.xrefs or not doc.xref_is_stream(xref):  # type: ignore[no-untyped-call]
                raise ScanRejectedError(
                    _MALFORMED_STRUCTURE_MESSAGE.format(page=page_index + 1), reason="malformed"
                )
            start.append((xref, "any"))
        start.extend(ref for holder in holders for ref in _resources_refs(doc, holder))
        _walk_resource_graph(doc, start, walk)
        _walk_annotations(doc, page_xref, walk)
    except ScanRejectedError:
        raise
    except Exception as exc:
        raise ScanRejectedError(
            _WALK_FAILED_MESSAGE.format(page=page_index + 1), reason="uncheckable"
        ) from exc
    budget.scan_total += budget.page_total


def check_pdf_page_content(doc: pymupdf.Document, page_index: int) -> None:
    """:func:`check_pdf_content` for the ONE page a caller is about to render.

    Triage F8: the crop route renders one page but used to pay for the
    whole-document walk on every request (35-48 ms against a 60-78 ms crop
    render on a normal paper), and a bomb on some OTHER page refused a crop
    that never touched it. A renderer parses only the page it renders, so only
    that page's content, resources and annotations need bounding. The same
    rules apply as in :func:`check_pdf_content` -- encrypted and non-PDF
    documents left alone, fail-closed on any walk failure -- with a fresh
    budget, since no other page contributes to it.

    Not :data:`MAX_SCAN_PAGES` (user decision 2, 2026-09-29): that cap
    bounds whole-document work, and a one-page render is not that, so a
    stored scan of 41-200 pages keeps its review crops. Extraction and the
    preview route still go through :func:`check_pdf_content` and keep it
    (issue #269 is about the preview route alone from here on). But the
    page tree this check reads (:func:`_page_tree`) costs time in
    proportion to its size, so it has its own bound, :data:`MAX_CROP_PAGES`
    (review round 1 on F8): ``doc.page_count`` is checked against it before
    anything is read, and, since an understated ``/Count`` would dodge
    that, :func:`_page_tree` stops its descent once the real tree is over
    it. Either way the refusal is a :class:`ScanTooLargeError` and costs
    at most a bound's worth of reads. The caller has already bounds-checked
    ``page_index`` (``review._require_page_in_range``).
    """
    if not doc.is_pdf:
        return
    if doc.needs_pass:
        return
    _check_object_streams(doc)
    if doc.page_count > MAX_CROP_PAGES:
        raise ScanTooLargeError(_CROP_PAGES_MESSAGE, reason="crop_page_cap")
    try:
        tree = _page_tree(doc, bound=_CROP_PAGE_BOUND)
    except ScanRejectedError:
        raise
    except Exception as exc:
        raise ScanRejectedError(_WALK_FAILED_MESSAGE.format(page=1), reason="uncheckable") from exc
    _check_page(doc, tree, _ContentBudget(), page_index)
