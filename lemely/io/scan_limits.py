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
from dataclasses import dataclass
from typing import TYPE_CHECKING

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
#: Rev 2: an image XObject's declared pixels, read from its dictionary. Reuses
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
#: Fix round 1. Every distinct object a page's content walk (Form XObjects,
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
#: Fix round 1: the filter token is deliberately not named in the message --
#: it is attacker-controlled PDF syntax, not information a re-export needs.
_UNSUPPORTED_FILTER_MESSAGE = (
    "Page {page} of this PDF uses a content encoding this service cannot measure "
    "safely; re-export the PDF with standard (Flate) compression."
)
#: Fix round 1.
_TOO_MANY_OBJECTS_MESSAGE = (
    "Page {page} of this PDF references far more drawing objects than a scanned "
    "page can. Re-export it as a plain scan."
)
#: Fix round 3, Important 1: an unforeseen error raised inside the walk
#: itself (as opposed to opening the document, or accessing its page tree)
#: rejects the file rather than passing it through -- see
#: :func:`check_pdf_content`'s inner ``try``.
_WALK_FAILED_MESSAGE = (
    "Page {page} of this PDF could not be measured safely. Re-export it as a plain scan."
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


@dataclass
class _ContentBudget:
    """Running totals shared across one page's content walk.

    ``scan_total`` is fixed for the duration of a page (everything counted
    on *earlier* pages); ``page_total`` and ``objects`` accumulate as the
    current page is walked, then fold into ``scan_total`` once it is done.
    """

    scan_total: int = 0
    page_total: int = 0
    objects: int = 0


def _collection_refs(doc: pymupdf.Document, kind: str, value: str) -> list[int]:
    """Every indirect reference named inside a dict/array-shaped value.

    Covers both an inline sub-dictionary or array (``kind`` is ``"dict"``
    or ``"array"``, ``value`` is pymupdf's literal source text for it) and
    one stored as its own object (``kind == "xref"``: read *that* object's
    own source instead, so a two-level structure -- a ``/Resources`` object
    whose own ``/XObject``/``/Pattern``/``/Font`` sub-dictionaries are
    themselves inline -- is flattened in the same pass). A reference's PDF
    *name* (which resource-map key it sits under, an appearance state's
    name, a glyph name) is never needed here -- only whether it is
    reachable at all -- so one regex over the whole resolved text finds
    every reference regardless of how many dictionary levels it is nested
    inside, without a bespoke parser for each of the differently-shaped
    dictionaries (``/Resources``, ``/AP``, ``/CharProcs``) this walk visits.
    """
    if kind == "xref":
        text = doc.xref_object(int(value.split()[0]))  # type: ignore[no-untyped-call]
    elif kind in ("dict", "array"):
        text = value
    else:
        return []
    return [int(m.group(1)) for m in _REF_RE.finditer(text)]


def _enter(xref: int, *, seen: set[int], budget: _ContentBudget, page_index: int) -> bool:
    """Register a visit to ``xref``; ``False`` if already visited (skip it).

    The single choke point for both cycle prevention (``seen``) and the
    per-page object cap (:data:`_MAX_OBJECTS_PER_PAGE`) -- every walker
    below visits an object through this before doing anything else with it.
    """
    if xref in seen:
        return False
    seen.add(xref)
    budget.objects += 1
    if budget.objects > _MAX_OBJECTS_PER_PAGE:
        raise ScanTooLargeError(_TOO_MANY_OBJECTS_MESSAGE.format(page=page_index + 1))
    return True


def _count_stream(
    doc: pymupdf.Document, xref: int, *, page_index: int, budget: _ContentBudget
) -> None:
    """Add ``xref``'s decoded size to ``budget.page_total``, or refuse."""
    page_budget = MAX_PAGE_CONTENT_BYTES - budget.page_total
    scan_budget = MAX_SCAN_CONTENT_BYTES - budget.scan_total - budget.page_total
    try:
        size = decoded_stream_size(
            doc, xref, budget=min(page_budget, scan_budget), page_index=page_index
        )
    except ScanTooLargeError:
        if scan_budget < page_budget:
            # The scan cap bit, not the page cap: say so.
            raise ScanTooLargeError(_WHOLE_SCAN_MESSAGE) from None
        raise
    budget.page_total += size


#: Fix round 3, Important 2. Keys under which a reference can lead back into
#: the page tree or across to another page's own content -- the fallback
#: below must never chase these, however it reaches an object that carries
#: one (honestly, or because a malicious PDF planted it there).
_FALLBACK_SKIP_KEYS = frozenset({"Parent", "P", "Kids", "Contents", "Annots", "B", "Dest"})
#: Fix round 3, Important 2. An object of one of these types is never
#: resource-graph content; entering one -- reached through a resources
#: entry that happens to name it, deliberately or not -- risks pulling in
#: the whole page tree. The page's own content and annotations are already
#: reached from their named starting points, so nothing legitimate is lost
#: by refusing to enter one of these another way.
_SKIP_TYPES = frozenset({"/Page", "/Pages", "/Catalog"})


def _resources_refs(doc: pymupdf.Document, container_xref: int) -> list[int]:
    """Every ref named in ``container_xref``'s own ``/Resources`` dict."""
    kind, value = doc.xref_get_key(container_xref, "Resources")  # type: ignore[no-untyped-call]
    return _collection_refs(doc, kind, value)


def _charprocs_refs(doc: pymupdf.Document, font_xref: int) -> list[int]:
    """Every glyph-procedure ref in a Type3 font's ``/CharProcs``."""
    kind, value = doc.xref_get_key(font_xref, "CharProcs")  # type: ignore[no-untyped-call]
    return _collection_refs(doc, kind, value)


def _scoped_fallback_refs(doc: pymupdf.Document, ref: int) -> list[int]:
    """Refs found among ``ref``'s own keys, minus :data:`_FALLBACK_SKIP_KEYS`.

    Fix round 3, Important 2. The round-2 fallback handed ``ref``'s FULL
    object text to :func:`_collection_refs` in one call, so a plain dict
    carrying a ``/Parent``, ``/Kids`` or other page-tree/back-reference key
    was walked exactly like any other reference -- in the worst case
    pulling in every other page's own content (up to :data:`MAX_SCAN_PAGES`
    x :data:`_MAX_OBJECTS_PER_PAGE` visits). Reading ``ref``'s keys one at a
    time instead lets the keys on that list be skipped by name, with no
    bespoke parser needed for the arbitrarily-shaped dictionary this
    fallback may have landed on.

    A key whose own value is a direct reference (``kind == "xref"``, e.g.
    ``/Fm1 5 0 R``) names object 5 itself as the next candidate -- unlike
    :func:`_collection_refs`'s ``"xref"`` handling, which reads the
    referenced object's own text for FURTHER embedded refs (the right
    reading for a structural key already known to hold a dict-of-refs
    container, such as an indirect ``/Resources``, but the wrong one here:
    the value found under an arbitrary fallback key is the resource, not a
    wrapper around more of them). An inline sub-dict or array value
    (``kind`` ``"dict"``/``"array"``) is still flattened via
    :func:`_collection_refs`, since that text may embed several refs at
    once.
    """
    refs: list[int] = []
    for key in doc.xref_get_keys(ref):  # type: ignore[no-untyped-call]
        if key in _FALLBACK_SKIP_KEYS:
            continue
        kind, value = doc.xref_get_key(ref, key)  # type: ignore[no-untyped-call]
        if kind == "xref":
            refs.append(int(value.split()[0]))
        elif kind in ("dict", "array"):
            refs.extend(_collection_refs(doc, kind, value))
    return refs


def _walk_resource_graph(
    doc: pymupdf.Document,
    start: list[int],
    *,
    page_index: int,
    seen: set[int],
    budget: _ContentBudget,
) -> None:
    """Iteratively visit every object reachable from ``start`` -- no recursion.

    Fix round 3, Important 1. Classifies one object at a time exactly as
    the round-1/round-2 recursive ``_visit_resource`` did (a Form XObject
    or tiling Pattern is content: count its stream, then queue its own
    ``/Resources``; an image is not content, checked separately from
    ``page.get_images``; a Type3 font's glyph procedures and its own
    ``/Resources`` are content; anything left over is one level further
    from a leaf -- an indirect ``/XObject``/``/Font``/``/Pattern``/
    ``/ColorSpace``/``/ExtGState`` dict, an ``/AP`` appearance-state dict,
    an ExtGState's ``/SMask`` -> ``/G`` form -- so it is treated as another
    collection via :func:`_scoped_fallback_refs`), but with an explicit
    ``stack`` in place of a Python call per level: a chain of nested Form
    XObjects, or of round-2's fallback plain dicts, has no bound on how
    many levels deep it goes, and a few thousand levels exceeds
    ``sys.getrecursionlimit()`` (~1,000) well before
    :data:`_MAX_OBJECTS_PER_PAGE` (10,000) would refuse it -- raising
    ``RecursionError``, which used to be swallowed by
    ``check_pdf_content``'s caller and let the file (and whatever bomb
    followed the chain) through silently. An explicit stack has no such
    limit.

    Fix round 3, Important 2: before classifying, an object identified as
    ``/Page``, ``/Pages`` or ``/Catalog`` (:data:`_SKIP_TYPES`) is refused
    outright, wherever it was reached from.
    """
    stack: list[int] = list(start)
    while stack:
        ref = stack.pop()
        if not _enter(ref, seen=seen, budget=budget, page_index=page_index):
            continue
        type_kind, type_value = doc.xref_get_key(ref, "Type")  # type: ignore[no-untyped-call]
        if type_kind == "name" and type_value in _SKIP_TYPES:
            continue
        if doc.xref_is_xobject(ref):  # type: ignore[no-untyped-call]
            _count_stream(doc, ref, page_index=page_index, budget=budget)
            stack.extend(_resources_refs(doc, ref))
            continue
        if doc.xref_is_image(ref):  # type: ignore[no-untyped-call]
            continue
        if doc.xref_is_font(ref):  # type: ignore[no-untyped-call]
            if doc.xref_get_key(ref, "Subtype") == ("name", "/Type3"):  # type: ignore[no-untyped-call]
                stack.extend(_charprocs_refs(doc, ref))
                stack.extend(_resources_refs(doc, ref))
            continue
        pattern_kind, _pattern_value = doc.xref_get_key(ref, "PatternType")  # type: ignore[no-untyped-call]
        if pattern_kind != "null":
            _count_stream(doc, ref, page_index=page_index, budget=budget)
            stack.extend(_resources_refs(doc, ref))
            continue
        if doc.xref_is_stream(ref):  # type: ignore[no-untyped-call]
            _count_stream(doc, ref, page_index=page_index, budget=budget)
            continue
        stack.extend(_scoped_fallback_refs(doc, ref))


def _walk_resources(
    doc: pymupdf.Document,
    container_xref: int,
    *,
    page_index: int,
    seen: set[int],
    budget: _ContentBudget,
) -> None:
    """Every Form XObject / tiling Pattern / Type3 font reachable from ``container_xref``.

    Reads ``container_xref``'s ``/Resources`` and hands the refs it names
    to :func:`_walk_resource_graph`. ``container_xref`` is a page, a Form
    XObject, a Pattern or a Type3 font -- every PDF object that carries its
    own ``/Resources`` dict.
    """
    _walk_resource_graph(
        doc,
        _resources_refs(doc, container_xref),
        page_index=page_index,
        seen=seen,
        budget=budget,
    )


def _walk_annotations(
    doc: pymupdf.Document,
    page_xref: int,
    *,
    page_index: int,
    seen: set[int],
    budget: _ContentBudget,
) -> None:
    """Every annotation appearance stream reachable from the page.

    ``/Annots`` -> ``/AP`` -> ``/N``, ``/R``, ``/D``, whichever are present,
    each either a stream directly or a dict of appearance states each
    pointing to one. An appearance stream is itself a Form XObject per
    spec, so every one found is handed to :func:`_walk_resource_graph`,
    which counts it and recurses into its own ``/Resources`` exactly like
    any other form.
    """
    kind, value = doc.xref_get_key(page_xref, "Annots")  # type: ignore[no-untyped-call]
    ap_refs: list[int] = []
    for annot_ref in _collection_refs(doc, kind, value):
        if not _enter(annot_ref, seen=seen, budget=budget, page_index=page_index):
            continue
        ap_kind, ap_value = doc.xref_get_key(annot_ref, "AP")  # type: ignore[no-untyped-call]
        ap_refs.extend(_collection_refs(doc, ap_kind, ap_value))
    _walk_resource_graph(doc, ap_refs, page_index=page_index, seen=seen, budget=budget)


def _resolve_int(doc: pymupdf.Document, kind: str, value: str) -> int | None:
    r"""An integer-or-real dict value, resolving one level of indirection.

    Mirrors :func:`_normalise_filter`'s handling of an indirect ``/Filter``:
    ``kind == "xref"`` means the value itself is a bare number object
    (``5 0 obj\n40000\nendobj``), read back via ``xref_object`` and parsed.
    Fix round 3, minor: ``/Width``/``/Height`` written as a PDF *real*
    (``40000.0``, direct or indirect) is legal and just as large a
    declared size as the integer spelling -- ``pymupdf`` reports this
    ``kind`` as ``"float"``, not ``"int"``, and used to fall through to
    ``None`` (a silent pass) below. ``int(float(value))`` parses both
    spellings uniformly.
    """
    if kind == "xref":
        text = doc.xref_object(int(value.split()[0])).strip()  # type: ignore[no-untyped-call]
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


def _check_mask_pixels(doc: pymupdf.Document, xref: int, *, page_index: int) -> None:
    """:data:`MAX_DECODE_PX` against a mask stream's own declared size.

    Fix round 2, Important 2: an indirect ``/Width``/``/Height`` (unusual
    but legal, the same spelling :func:`_normalise_filter` already resolves
    for ``/Filter``) used to make this silently return without checking.
    """
    width = _resolve_int(doc, *doc.xref_get_key(xref, "Width"))  # type: ignore[no-untyped-call]
    height = _resolve_int(doc, *doc.xref_get_key(xref, "Height"))  # type: ignore[no-untyped-call]
    if width is None or height is None:
        return
    if width * height > MAX_DECODE_PX:
        raise ScanTooLargeError(
            _IMAGE_TOO_LARGE_MESSAGE.format(page=page_index + 1, mpx=width * height // 1_000_000)
        )


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

    Covers the image itself (rev 2) and its ``/SMask``/``/Mask`` (fix round
    1). ``image`` is one entry of ``page.get_images(full=True)``:
    ``(xref, smask_xref, width, height, ...)``. ``/SMask`` is always a
    stream when present (``smask_xref`` is 0 for "none"); ``/Mask`` is
    either a stream (a stencil mask, checked the same way) or an array
    (colour-key masking -- not a decode-sized allocation, left alone).
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
    if smask_xref:
        _check_mask_pixels(doc, smask_xref, page_index=page_index)
    mask_kind, mask_value = doc.xref_get_key(xref, "Mask")  # type: ignore[no-untyped-call]
    if mask_kind == "xref":
        mask_xref = int(mask_value.split()[0])
        if doc.xref_is_stream(mask_xref):  # type: ignore[no-untyped-call]
            _check_mask_pixels(doc, mask_xref, page_index=page_index)


def check_pdf_content(doc: pymupdf.Document) -> None:
    """Refuse a document whose page content would blow the render (Task 11b).

    Per page, counted into the same :data:`MAX_PAGE_CONTENT_BYTES` /
    :data:`MAX_SCAN_CONTENT_BYTES` budgets, each xref counted once
    (deduped by a per-page ``seen`` set, which also terminates a cycle --
    two Form XObjects, or two annotations, referencing each other): the
    page's own content stream(s) (``page.get_contents()``); every Form
    XObject reachable from the page's ``/Resources``, recursively (a form
    can itself use forms, patterns or Type3 fonts); every tiling Pattern
    (fix round 1); every Type3 font's glyph procedures (fix round 1); and
    every annotation's appearance stream(s) (fix round 1). A second,
    independent cap (:data:`_MAX_OBJECTS_PER_PAGE`) bounds the number of
    distinct objects one page's walk may visit, regardless of their size --
    a document engineered with a huge count of small objects costs real
    time to classify one by one even though no single stream is large.

    Image XObjects are not content and their streams are never read;
    instead each image's DECLARED ``/Width x /Height`` -- and (fix round 1)
    its ``/SMask``'s and stream-valued ``/Mask``'s, each own image objects
    with their own declared size -- is checked against
    :data:`MAX_DECODE_PX`, because pdfium decodes an image at its declared
    size to render it, regardless of what its stream actually holds.

    Left alone: an encrypted document (its streams cannot be read, and
    extraction fails on it later as today) and a non-PDF document (an
    ``image/*`` upload opened by :mod:`pymupdf` for its own preview render
    has no PDF page tree to walk at all -- ``page.get_contents()`` asserts
    on one).

    Inline images (``BI ... ID ... EI``) are not walked for a declared
    size the way an Image XObject is: their raw bytes already count toward
    the page's content-stream budget (they live inside the content stream
    itself), but a maliciously large *declared* width/height on a small
    inline-image byte run is a known gap this round does not close --
    tracked for the render-sandbox follow-up the brief's decision 4
    recommends, not solved by a bigger content-byte budget.

    Fix round 3, Important 1: ``load_page`` and ``page_xref`` -- simple
    page-tree lookups -- are left unguarded here, so their failure on a
    document whose page tree does not fully parse is exactly the "not our
    call to make" case :func:`check_scan_bytes`'s docstring already
    describes, and still propagates to
    :func:`check_pdf_content_bytes`/:func:`check_pdf_content_path`'s own
    ``except Exception: return``, unchanged. Everything past that --
    including ``get_images``/``get_contents`` themselves, since
    ``get_images(full=True)`` was found to walk nested Form XObjects
    looking for images the same way this module's own walk does, and can
    raise the identical ``RecursionError`` on the identical deep chain --
    is wrapped instead: any exception other than this module's own
    :class:`ScanRejectedError` rejects the page rather than silently
    passing it through, so a bug or an unforeseen ``pymupdf`` quirk inside
    the walk fails closed.
    """
    if not doc.is_pdf:
        return
    if doc.needs_pass:
        return
    budget = _ContentBudget()
    for page_index in range(doc.page_count):
        page = doc.load_page(page_index)  # type: ignore[no-untyped-call]
        page_xref = doc.page_xref(page_index)  # type: ignore[no-untyped-call]
        budget.page_total = 0
        budget.objects = 0
        seen: set[int] = set()
        try:
            for image in page.get_images(full=True):
                _check_image_and_masks(doc, image, page_index=page_index)
            for xref in page.get_contents():
                xref = int(xref)
                seen.add(xref)
                _count_stream(doc, xref, page_index=page_index, budget=budget)
            _walk_resources(doc, page_xref, page_index=page_index, seen=seen, budget=budget)
            _walk_annotations(doc, page_xref, page_index=page_index, seen=seen, budget=budget)
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
