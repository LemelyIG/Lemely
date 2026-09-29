"""Bounds on scan geometry, checked before anything is rendered or decoded.

Spec 2026-09-26 §6 (#2). A scan's byte size bounds nothing: a PDF under 2 KB
can declare a 14,400 pt page (40,000 x 40,000 px at 200 DPI -- 4.8 GB of RGB)
and a PNG of a few hundred KB can declare tens of megapixels. Before this
module, `rasterise.py` rendered whatever the file declared, inside a 1 GiB
worker. The rule is a hybrid: up to :data:`MAX_PAGE_PX` a page is used as is;
between the target and :data:`MAX_DECODE_PX` it is downscaled to fit; beyond
that, or past :data:`MAX_SCAN_PAGES`, it is rejected with a
:class:`ScanTooLargeError` whose message names the limit.

Pure: pypdfium2 and Pillow only, no I/O of its own. The web upload routes
call :func:`check_scan_bytes` on the uploaded body (headers and page sizes
only -- nothing is rendered) so the user gets a clear 422; `rasterise.py`
applies the same plans at extraction time as a second line of defence.
"""

from __future__ import annotations

import io
import math
import re
import zlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

import pymupdf
import pypdfium2 as pdfium
from PIL import Image

from lemely.runtime.errors import LemelyError

if TYPE_CHECKING:
    from pathlib import Path

#: The committed question paper has 16 pages; answer booklets with
#: continuation sheets reach the low 30s. Also bounds the number of page
#: images one extraction call carries.
MAX_SCAN_PAGES = 40
#: The target after any downscale. A4 at 400 DPI is 3307x4677 = 15.5 Mpx,
#: the top of what a document scanner produces; the corpus at 200 DPI is
#: 1655x2339 = 3.87 Mpx.
MAX_PAGE_PX = 16_000_000
#: The reject boundary -- the crop route's existing "too big to open" number
#: (it admits a 600 dpi A4 scan, ~35 Mpx, and any phone photo not in a
#: high-resolution mode), moved here so the app has ONE such number. It is
#: 2.5x the target, which is the downscale band.
MAX_DECODE_PX = 40_000_000
#: Google's documented recommendation for image/PDF inputs; keeps a rendered
#: page's image-tokenisation cost at the "medium" tier (560 tokens/page).
EXTRACTION_DPI: float = 200.0
#: The PDF header. One definition: two spellings of it once drifted between
#: the extractor and the crop route.
PDF_MAGIC = b"%PDF-"
#: Integer reductions Pillow can apply; JPEG can also decode natively at
#: 1/2, 1/4 and 1/8.
_REDUCE_FACTORS = (1, 2, 4, 8)
#: Task 11b. The decoded size of one page's content streams plus every Form
#: XObject reachable from the page, each xref counted once. The committed
#: fixture's largest page content is 47 bytes (a scanned page is
#: ``q ... cm /Im0 Do Q``); a dense born-digital vector page runs 20-100 KB.
#: pdfium's parse footprint measured ~20x the decoded content (112 MB ->
#: 2,251 MB), so 8 MB caps a page's parse near 160 MB inside the 1 GiB worker.
MAX_PAGE_CONTENT_BYTES = 8_000_000
#: The sum of the per-page totals over the scan: pages render one at a time,
#: so this bounds cumulative parse time (~28 MB/s measured) and guards against
#: parsed pages kept alive across the loop.
MAX_SCAN_CONTENT_BYTES = 64_000_000
#: Bounded inflate step: the most decoded content held at once.
_INFLATE_CHUNK = 1 << 20
#: An image XObject's declared pixels, read from its dictionary. Reuses
#: MAX_DECODE_PX (40 Mpx): a 600 dpi A4 scan is ~35 Mpx and passes.
_IMAGE_TOO_LARGE_MESSAGE = (
    "Page {page} of this PDF contains an image of about {mpx} megapixels, which is "
    "too large to process safely. Rescan at 600 dpi or lower."
)
#: The message when the scan cap, not the page cap, is what bit.
_WHOLE_SCAN_MESSAGE = (
    "This PDF's pages contain far more drawing data than a scanned paper can "
    f"(over {MAX_SCAN_CONTENT_BYTES // 1_000_000} MB across the whole scan). "
    "Re-export it as a plain scan."
)
#: Every distinct object a page's content walk (Form XObjects,
#: tiling patterns, Type3 CharProcs, annotation appearance streams, and their
#: own nested resources) may visit before it is refused outright -- a second,
#: independent bound alongside the byte caps: a document engineered with a
#: huge *number* of small, cheap-to-decode objects costs real time to walk
#: and classify one by one even though no single stream is large.
_MAX_OBJECTS_PER_PAGE = 10_000
#: The spellings of Flate compression this module can bound without a full
#: decode. ``/Fl`` is the inline-image abbreviation (PDF spec Table 93);
#: legitimate, not an evasion, so accepted alongside the full name.
_FLATE_FILTER_NAMES = ("/FlateDecode", "/Fl")
#: The filter token is deliberately not named in the message --
#: it is attacker-controlled PDF syntax, not information a re-export needs.
_UNSUPPORTED_FILTER_MESSAGE = (
    "Page {page} of this PDF uses a content encoding this service cannot measure "
    "safely; re-export the PDF with standard (Flate) compression."
)
#: The per-page object cap bit.
_TOO_MANY_OBJECTS_MESSAGE = (
    "Page {page} of this PDF references far more drawing objects than a scanned "
    "page can. Re-export it as a plain scan."
)
#: An unforeseen error raised inside the walk
#: itself (as opposed to opening the document, or accessing its page tree)
#: rejects the file rather than passing it through -- see
#: :func:`check_pdf_content`'s inner ``try``.
_WALK_FAILED_MESSAGE = (
    "Page {page} of this PDF could not be measured safely. Re-export it as a plain scan."
)
#: A page's structure is malformed in a way that could hide drawn content:
#: its drawing resources, ``/Contents`` or ``/Annots`` name a page-tree node,
#: or a ``/Contents`` entry is not a stream. See :func:`check_pdf_content`.
_MALFORMED_STRUCTURE_MESSAGE = (
    "Page {page} of this PDF has a malformed structure that cannot be measured safely. "
    "Re-export it as a plain scan."
)


class ScanRejectedError(LemelyError):
    """A scan this service will not render; the message says why and what to do."""


class ScanTooLargeError(ScanRejectedError):
    """A scan's declared geometry or content is beyond what extraction will render."""


class ScanUnsupportedEncodingError(ScanRejectedError):
    """A page content stream uses an encoding whose decoded size cannot be bounded."""


@dataclass(frozen=True)
class PagePlan:
    """How to render one PDF page: at ``dpi`` (never above the requested DPI)."""

    index: int
    dpi: float


def looks_like_pdf(data: bytes) -> bool:
    """True when *data* starts with the PDF magic bytes."""
    return data.startswith(PDF_MAGIC)


def plan_page_dpi(
    width_pt: float, height_pt: float, *, dpi: float = EXTRACTION_DPI, index: int = 0
) -> float:
    """The DPI a ``width_pt`` x ``height_pt`` page renders at under the limits.

    Up to the target: ``dpi``. Within the band: ``floor(dpi * sqrt(MAX_PAGE_PX
    / px))`` -- the crop route's own formula. Beyond: :class:`ScanTooLargeError`.
    """
    px = width_pt * height_pt * (dpi / 72.0) ** 2
    if px <= MAX_PAGE_PX:
        return dpi
    if px <= MAX_DECODE_PX:
        return float(math.floor(dpi * math.sqrt(MAX_PAGE_PX / px)))
    raise ScanTooLargeError(
        f"Page {index + 1} of this scan is too large to process "
        f"(limit {MAX_DECODE_PX // 1_000_000} megapixels). Rescan at a lower resolution."
    )


def plan_pdf_pages(pdf: pdfium.PdfDocument, *, dpi: float = EXTRACTION_DPI) -> list[PagePlan]:
    """One :class:`PagePlan` per page, computed from page sizes alone.

    The page cap is checked first, so an over-long document is refused before
    a single page is looked at, let alone rendered. Reads each page's size via
    :meth:`~pypdfium2.PdfDocument.get_page_size` rather than indexing into the
    document (``pdf[index].get_size()``) -- the latter loads the full page
    object, which :func:`~lemely.io.rasterise.rasterise_pdf_to_pages` then
    loads a second time to render it; this way a page is loaded at most once.
    """
    count = len(pdf)
    if count > MAX_SCAN_PAGES:
        raise ScanTooLargeError(f"The scan has {count} pages; the limit is {MAX_SCAN_PAGES}.")
    plans: list[PagePlan] = []
    for index in range(count):
        width_pt, height_pt = pdf.get_page_size(index)
        plans.append(
            PagePlan(index=index, dpi=plan_page_dpi(width_pt, height_pt, dpi=dpi, index=index))
        )
    return plans


def plan_image(width: int, height: int) -> int:
    """The integer reduce factor that brings ``width`` x ``height`` under the target.

    ``1`` when the image already fits; :class:`ScanTooLargeError` beyond
    :data:`MAX_DECODE_PX`.
    """
    px = width * height
    if px > MAX_DECODE_PX:
        raise ScanTooLargeError(
            f"This scan is too large to process (limit {MAX_DECODE_PX // 1_000_000} "
            "megapixels). Rescan at a lower resolution."
        )
    for factor in _REDUCE_FACTORS:
        if px / (factor * factor) <= MAX_PAGE_PX:
            return factor
    return _REDUCE_FACTORS[-1]  # pragma: no cover -- 40 Mpx / 64 is always under the target


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
                    "decompressed). Re-export it as a plain scan."
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
                "Re-export it as a plain scan."
            )
        return size
    if len(filters) == 1 and filters[0] in _FLATE_FILTER_NAMES:
        return _bounded_inflate_size(raw, budget=budget, page_index=page_index)
    raise ScanUnsupportedEncodingError(_UNSUPPORTED_FILTER_MESSAGE.format(page=page_index + 1))


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
    """

    page_index: int
    tree: frozenset[int]
    budget: _ContentBudget
    seen: set[int] = field(default_factory=set)
    font_seen: set[int] = field(default_factory=set)
    image_seen: set[int] = field(default_factory=set)
    annot_seen: set[int] = field(default_factory=set)


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


def _collection_refs(doc: pymupdf.Document, kind: str, value: str) -> list[int]:
    """Every indirect reference named inside a dict/array-shaped value.

    ``kind``/``value`` are one ``xref_get_key`` result. An inline dict or
    array is scanned as written; an indirect one (``kind == "xref"``) is
    read and its own text scanned instead, so a map stored as its own
    object (``/XObject 6 0 R``) yields the references *inside* it. A
    reference's name within the map (a resource name, an appearance-state
    name, a glyph name) plays no part: every reference found is returned.
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
    return [int(m.group(1)) for m in _REF_RE.finditer(text)]


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
        raise ScanTooLargeError(_TOO_MANY_OBJECTS_MESSAGE.format(page=walk.page_index + 1))
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
            raise ScanTooLargeError(_WHOLE_SCAN_MESSAGE) from None
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


def _page_tree(doc: pymupdf.Document) -> _PageTree:
    """The page tree's object numbers and each page's resource holders.

    Descends ``/Kids`` from the catalog's ``/Pages`` root, reading each
    node once (a node met again -- a ``/Kids`` cycle -- is not re-read).
    Climbs ``/Parent`` from every page for the holders only; a node already
    climbed from an earlier page ends the climb (its answer is reused), and
    a node met twice on one climb (a ``/Parent`` cycle) ends it too. A page
    whose number pymupdf cannot give stops the build there:
    :func:`check_pdf_content` meets the same failure on the same page and
    treats it as a malformed page tree.
    """
    nodes: set[int] = set()
    xref_length = doc.xref_length()  # type: ignore[no-untyped-call]
    catalog = doc.pdf_catalog()  # type: ignore[no-untyped-call]
    pending: list[int] = []
    if 0 < catalog < xref_length:
        nodes.add(catalog)
        pending.append(_ref_target(doc, *_key(doc, catalog, "Pages")))
    while pending:
        node = pending.pop()
        if not 0 < node < xref_length or node in nodes:
            continue
        nodes.add(node)
        pending.extend(_collection_refs(doc, *_key(doc, node, "Kids")))
    # node -> (nearest node at or above it with a /Resources key,
    #          nearest node at or above it whose /Resources resolves)
    nearest: dict[int, tuple[int | None, int | None]] = {}
    for index in range(doc.page_count):
        try:
            page_xref = doc.page_xref(index)  # type: ignore[no-untyped-call]
        except Exception:
            break
        nodes.add(page_xref)
        chain: list[int] = []
        node = page_xref
        while node and node not in nearest and node not in chain:
            chain.append(node)
            node = _parent(doc, node)
        above = nearest.get(node, (None, None))
        for member in reversed(chain):
            has_key, resolves = _resources_state(doc, member)
            above = (member if has_key else above[0], member if resolves else above[1])
            nearest[member] = above
    holders = {
        node: tuple(sorted({h for h in pair if h is not None})) for node, pair in nearest.items()
    }
    return _PageTree(xrefs=frozenset(nodes), holders=holders)


def _dict_refs(doc: pymupdf.Document, xref: int) -> list[int]:
    """Every reference in ``xref``'s dictionary outside ``/Resources``.

    Works for a stream's dictionary and a plain dict alike. ``/Resources``
    is read by :func:`_resources_refs` instead, which keeps each
    reference's role. A reference's key plays no other part: an object
    used as a container (a graphics state, an appearance state dict, a
    stream that is also a soft mask) is read by whatever key the renderer
    looks up, and nothing here assumes which.
    """
    refs: list[int] = []
    for key in doc.xref_get_keys(xref):  # type: ignore[no-untyped-call]
        if key == "Resources":
            continue
        kind, value = _key(doc, xref, key)
        if kind == "xref":
            target = _ref_target(doc, kind, value)
            if target:
                refs.append(target)
        elif kind in ("dict", "array"):
            refs.extend(int(m.group(1)) for m in _REF_RE.finditer(value))
    return refs


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
      with roles) and every other reference in its dictionary -- or, for an
      array, every reference in it -- walked. An object used as a
      container (a graphics state, an appearance state dict, a soft mask)
      is read by whatever key the renderer looks up, so no key is assumed.
      Over-counting a stream that is never drawn is accepted: it can only
      reject.
    * Two roles narrow this, and only for that role: an image met under
      ``/XObject`` is decoded as an image, so its declared size and its
      masks' are checked against :data:`MAX_DECODE_PX` instead; a
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
            raise ScanRejectedError(_MALFORMED_STRUCTURE_MESSAGE.format(page=walk.page_index + 1))
        if ref in walk.seen:
            continue  # expanded in full already: every role's work is done
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
            stack.extend((target, "any") for target in _dict_refs(doc, ref))
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
            raise ScanRejectedError(_MALFORMED_STRUCTURE_MESSAGE.format(page=walk.page_index + 1))
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


def _check_declared_pixels(doc: pymupdf.Document, xref: int, *, page_index: int) -> None:
    """:data:`MAX_DECODE_PX` against image object ``xref``'s own declared size.

    ``/Width`` and ``/Height`` may be integers or reals, direct or
    indirect (:func:`_resolve_int`). Used for images the walk reaches and
    for every image's ``/SMask`` and stream ``/Mask``.
    """
    width = _resolve_int(doc, *_key(doc, xref, "Width"))
    height = _resolve_int(doc, *_key(doc, xref, "Height"))
    if width is None or height is None:
        return
    if width * height > MAX_DECODE_PX:
        raise ScanTooLargeError(
            _IMAGE_TOO_LARGE_MESSAGE.format(page=page_index + 1, mpx=width * height // 1_000_000)
        )


def _check_masks(doc: pymupdf.Document, xref: int, *, smask_xref: int, page_index: int) -> None:
    """Check image ``xref``'s ``/SMask`` (``smask_xref``, 0 for none) and stream ``/Mask``.

    Each is an image object with its own declared size, decoded at that
    size to render the image. A ``/Mask`` array (colour-key masking) is not
    a decode-sized allocation and is left alone.
    """
    if smask_xref:
        _check_declared_pixels(doc, smask_xref, page_index=page_index)
    mask_xref = _ref_target(doc, *_key(doc, xref, "Mask"))
    if mask_xref and doc.xref_is_stream(mask_xref):  # type: ignore[no-untyped-call]
        _check_declared_pixels(doc, mask_xref, page_index=page_index)


def _check_image_xref(doc: pymupdf.Document, xref: int, *, page_index: int) -> None:
    """An image the walk reached: its declared size, then its masks'.

    ``page.get_images(full=True)`` does not list images inside annotation
    appearance streams or tiling patterns, so the walk checks every image
    it reaches itself. The per-image limit has no running total, so an
    image checked both here and via ``get_images`` is judged the same way
    twice.
    """
    _check_declared_pixels(doc, xref, page_index=page_index)
    smask_xref = _ref_target(doc, *_key(doc, xref, "SMask"))
    _check_masks(doc, xref, smask_xref=smask_xref, page_index=page_index)


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
    """Reject an image or its mask whose declared pixels exceed :data:`MAX_DECODE_PX`.

    ``image`` is one entry of ``page.get_images(full=True)``:
    ``(xref, smask_xref, width, height, ...)``, sizes as pymupdf read them.
    """
    xref, smask_xref, width, height = (
        _tuple_int(image[0]),
        _tuple_int(image[1]),
        _tuple_int(image[2]),
        _tuple_int(image[3]),
    )
    if width * height > MAX_DECODE_PX:
        raise ScanTooLargeError(
            _IMAGE_TOO_LARGE_MESSAGE.format(page=page_index + 1, mpx=width * height // 1_000_000)
        )
    _check_masks(doc, xref, smask_xref=smask_xref, page_index=page_index)


def check_pdf_content(doc: pymupdf.Document) -> None:
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

    Images are not content and their streams are never read; instead each
    image's DECLARED ``/Width x /Height`` -- and its ``/SMask``'s and
    stream ``/Mask``'s -- is checked against :data:`MAX_DECODE_PX`,
    because the renderer allocates for the declared size whatever the
    stream holds. Images are found both by ``page.get_images(full=True)``
    and by the walk, which reaches the ones ``get_images`` does not list.

    The page tree (:func:`_page_tree`) is read once, up front: a walk that
    reaches it from a page's drawing resources rejects the file (see
    :func:`_walk_resource_graph`), and each page's walk starts from the
    ``/Resources`` it inherits.

    Left alone: an encrypted document (its streams cannot be read;
    extraction fails on it later) and a non-PDF document (an ``image/*``
    upload opened by :mod:`pymupdf` for its preview has no page tree).
    Opening the document, ``load_page`` and ``page_xref`` are page-tree
    lookups whose failure means a malformed page tree -- that propagates to
    :func:`check_pdf_content_bytes`/:func:`check_pdf_content_path` and
    passes, the same rule as :func:`check_scan_bytes`'s geometry check.

    Fails closed: any other exception while reading the page tree or
    walking a page -- a pymupdf quirk, a ``RecursionError`` inside
    ``get_images``, a bug here -- rejects the file with
    :class:`ScanRejectedError`. The accepted cost is that some malformed
    but harmless files get a 422 asking for a re-export instead of
    passing: a page whose ``/Contents`` is a name or names an object that
    is not a stream, or whose ``/Contents``, ``/Annots`` or drawing
    resources name a page-tree node.

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
    try:
        tree = _page_tree(doc)
    except Exception as exc:
        raise ScanRejectedError(_WALK_FAILED_MESSAGE.format(page=1)) from exc
    budget = _ContentBudget()
    for page_index in range(doc.page_count):
        page = doc.load_page(page_index)  # type: ignore[no-untyped-call]
        page_xref = doc.page_xref(page_index)  # type: ignore[no-untyped-call]
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
                        _MALFORMED_STRUCTURE_MESSAGE.format(page=page_index + 1)
                    )
                start.append((xref, "any"))
            start.extend(
                ref
                for holder in tree.holders.get(page_xref, ())
                for ref in _resources_refs(doc, holder)
            )
            _walk_resource_graph(doc, start, walk)
            _walk_annotations(doc, page_xref, walk)
        except ScanRejectedError:
            raise
        except Exception as exc:
            raise ScanRejectedError(_WALK_FAILED_MESSAGE.format(page=page_index + 1)) from exc
        budget.scan_total += budget.page_total


def check_pdf_content_bytes(data: bytes) -> None:
    """:func:`check_pdf_content` on an in-memory PDF; bytes pymupdf cannot open pass."""
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")  # type: ignore[no-untyped-call]
    except Exception:
        return
    try:
        check_pdf_content(doc)
    except ScanRejectedError:
        raise
    except Exception:
        return
    finally:
        doc.close()  # type: ignore[no-untyped-call]


def check_pdf_content_path(path: Path) -> None:
    """:func:`check_pdf_content` on a file; the extraction and CLI entry point."""
    try:
        doc = pymupdf.open(str(path))  # type: ignore[no-untyped-call]
    except Exception:
        return
    try:
        check_pdf_content(doc)
    except ScanRejectedError:
        raise
    except Exception:
        return
    finally:
        doc.close()  # type: ignore[no-untyped-call]


def check_scan_bytes(data: bytes) -> None:
    """The upload-time check: page sizes and image headers only, nothing rendered.

    Bytes that neither pypdfium2 nor Pillow can open are NOT rejected here --
    extraction fails on them later, exactly as it does today -- so the only
    422 this produces is a measured, over-limit geometry (or Pillow's
    decompression-bomb guard, which fires on the declared size before any
    pixel is decoded). A document that opens but has a page that does not
    (a malformed ``/Kids`` entry, a ``/Count`` past the real page array) is
    the same case: ``plan_pdf_pages`` can raise pypdfium2's own
    ``PdfiumError`` reading such a page's size, and that is not our call to
    make either -- extraction fails on it later exactly as it does today.
    And, for a PDF, the decoded size of each page's content streams (Task
    11b) -- read from the raw streams with a bounded inflate, never rendered.
    """
    if looks_like_pdf(data):
        try:
            pdf = pdfium.PdfDocument(data)
        except Exception:
            return
        try:
            plan_pdf_pages(pdf)
        except ScanTooLargeError:
            raise
        except Exception:
            return
        finally:
            pdf.close()
        check_pdf_content_bytes(data)  # Task 11b: geometry first, then content
        return
    try:
        with Image.open(io.BytesIO(data)) as opened:
            plan_image(opened.width, opened.height)
    except Image.DecompressionBombError as exc:
        raise ScanTooLargeError(
            "This scan's image is too large to process safely. Rescan at a lower resolution."
        ) from exc
    except ScanTooLargeError:
        raise
    except Exception:
        return
