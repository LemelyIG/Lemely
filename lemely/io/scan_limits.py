"""Bounds on scan geometry, checked before anything is rendered or decoded.

Spec 2026-09-26 §6 (#2). A scan's byte size bounds nothing: a PDF under 2 KB
can declare a 14,400 pt page (40,000 x 40,000 px at 200 DPI -- 4.8 GB of RGB)
and a PNG of a few hundred KB can declare tens of megapixels. Before this
module, `rasterise.py` rendered whatever the file declared, inside a 1 GiB
worker. The rule is a hybrid: up to :data:`MAX_PAGE_PX` a page is used as is;
between the target and :data:`MAX_DECODE_PX` it is downscaled to fit; beyond
that, or past :data:`MAX_SCAN_PAGES`, it is rejected with a
:class:`ScanTooLargeError` whose message names the limit. For a raster image
the reject boundary is per mode (#256, :func:`decode_pixel_cap`): colour keeps
:data:`MAX_DECODE_PX`, a bilevel or greyscale scan gets
:data:`MAX_DECODE_PX_GREY`. The same hybrid applies to the whole scan: pages
summing past :data:`MAX_SCAN_TOTAL_PX` all render at one uniformly lower DPI,
rejected below :data:`MIN_EXTRACTION_DPI`.

Pure: pypdfium2, pymupdf and Pillow only, no I/O of its own. The web upload routes
call :func:`check_scan_bytes` on the uploaded body (headers and page sizes
only -- nothing is rendered) so the user gets a clear 422; `rasterise.py`
applies the same plans at extraction time as a second line of defence.
"""

from __future__ import annotations

import io
import itertools
import math
import re
import zlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

import pymupdf
import pymupdf.mupdf as _mupdf
import pypdfium2 as pdfium
from PIL import Image

from lemely.runtime.errors import LemelyError

if TYPE_CHECKING:
    from collections.abc import Callable

#: The committed question paper has 16 pages; answer booklets with
#: continuation sheets reach the low 30s. Also bounds the number of page
#: images one extraction call carries.
MAX_SCAN_PAGES = 40
#: The review crop route's page bound (user decision, review round 1 on
#: triage F8), separate from :data:`MAX_SCAN_PAGES`: the crop renders one
#: page, so a stored scan over 40 pages keeps its crops, but its content
#: check reads the page tree (:func:`_page_tree`), which costs about 33 us
#: per page -- tens of seconds for the million-odd pages a 25 MB file can
#: declare. Counted from the tree a reader descends, not from ``/Count``,
#: by MuPDF's rule: a ``/Type /Page`` is a page, a ``/Type /Pages`` is not,
#: and an untyped node is one if it names no ``/Kids`` (see :func:`_page_tree`).
MAX_CROP_PAGES = 200
#: Task 9c: extraction renders MuPDF's rewrite of a stored PDF
#: (:func:`canonical_pdf_bytes`), and the rewrite costs time per object in
#: the file (about 50-65 us each: 13.7 s for a 21 MB file of 200,000 small
#: objects). The largest committed PDF, a 20-page born-digital mark scheme,
#: has 1,334; a 40-page scan has a few hundred. Over this, the file is
#: refused before it is rewritten.
MAX_PDF_OBJECTS = 50_000
#: Task 9c review round 1: the decoded size of all of a PDF's object streams
#: together. An object stream packs many objects into one Flate stream, and
#: MuPDF parses every object in one as soon as any is needed, so a few KB on
#: disk can parse into hundreds of MB (an array of zeros costs ~43 bytes of
#: memory per element, ~21x its decoded text). Measured with the bounded
#: inflate before any object is loaded. Real producers' object streams hold
#: small dictionaries -- a 40-page born-digital file's total well under 1 MB --
#: and 16 MB keeps a compressed object no worse than an uncompressed one the
#: 25 MB upload cap already admits.
MAX_OBJECT_STREAM_BYTES = 16_000_000
#: Task 9c review round 2: how many tokens (object headers included) the raw
#: object-stream scan (:func:`check_object_stream_bytes`) may read. The
#: committed PDFs need at most 8,429; a dense 40-page born-digital file with
#: 800 annotations, 95,357. Crafted dictionaries can hold millions (25 MB of
#: names took the tokenizer 17 s), so past this the file is refused as too
#: complex to check -- at ~1.6 us a token, a second or two at most.
MAX_PRESCAN_TOKENS = 1_000_000
#: The target after any downscale. A4 at 400 DPI is 3307x4677 = 15.5 Mpx,
#: the top of what a document scanner produces; the corpus at 200 DPI is
#: 1655x2339 = 3.87 Mpx.
MAX_PAGE_PX = 16_000_000
#: The reject boundary -- the crop route's existing "too big to open" number
#: (it admits a 600 dpi A4 scan, ~35 Mpx, and any phone photo not in a
#: high-resolution mode), moved here so the app has ONE such number. It is
#: 2.5x the target, which is the downscale band.
MAX_DECODE_PX = 40_000_000
#: #256 (user decision 1, 2026-09-29): the image ceiling is PER MODE. Pillow
#: holds every mode at whole bytes per pixel -- "1" and "L" at one (measured:
#: 100 Mpx of either costs 96 MB), 16-bit grey at two, "RGB" at three -- so a
#: 1200 dpi bilevel A4 office scan (9921 x 14031 = 139 Mpx, 0.04 MB on disk)
#: is a 139 MB decode where the same pixels in colour would be 417 MB. Bilevel
#: and 8-bit greyscale therefore get this ceiling, 16-bit grey half of it, and
#: colour (and "P", converted to RGB before it can be reduced, and "LA") keeps
#: MAX_DECODE_PX. Equal to MAX_SCAN_TOTAL_PX on purpose: one grey page may
#: cost what a whole scan may, never more. A PDF page is always rendered as
#: RGB, so :func:`plan_page_dpi` keeps MAX_DECODE_PX.
MAX_DECODE_PX_GREY = 160_000_000
#: The sum of every page's pixels at its planned DPI, over the whole scan
#: (final review I1, user decision: hybrid). The per-page target alone does
#: not bound a scan: 40 pages at 16 Mpx is 640 Mpx, ~1.5 GB of rendered
#: pages held at once in a 1 GiB worker. An honest 40-page A4 scan at 200
#: DPI is 40 x 3.87 = 155 Mpx and fits unchanged. Over it, every page's DPI
#: is lowered by one uniform factor (:func:`plan_pdf_pages`).
MAX_SCAN_TOTAL_PX = 160_000_000
#: The floor of that uniform downscale: a scan that would need a page below
#: 100 DPI to fit :data:`MAX_SCAN_TOTAL_PX` is rejected instead, since
#: handwriting at that resolution is too coarse to read reliably.
MIN_EXTRACTION_DPI = 100
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
#: The page-tree descent (:func:`_page_tree`) found more real pages than
#: :data:`MAX_SCAN_PAGES` under a ``/Count`` that claimed no more. "More
#: than": the descent stops as soon as it is over, so it never knows how many.
_SCAN_PAGES_MESSAGE = (
    f"The scan has more than {MAX_SCAN_PAGES} pages; the limit is {MAX_SCAN_PAGES}."
)
#: The review crop route's page bound (:data:`MAX_CROP_PAGES`) bit.
_CROP_PAGES_MESSAGE = (
    f"The scan has more than {MAX_CROP_PAGES} pages; the limit for a review crop "
    f"is {MAX_CROP_PAGES}."
)
#: The page-tree descent (:func:`_page_tree`) ran past its work bound
#: (:attr:`_PageBound.work`) before it could count the pages. Says nothing
#: about how many pages there are: it could not tell.
_PAGE_TREE_TOO_COMPLEX_MESSAGE = (
    "This PDF's page tree is too complex to check safely. Re-export it as a plain scan."
)
#: MuPDF counted a page it then could not load or number (Task 9b): what
#: pdfium renders there went unmeasured, so the file is refused.
_PAGE_UNREADABLE_MESSAGE = (
    "Page {page} of this PDF could not be read, so it could not be checked safely. "
    "Re-export it as a plain scan."
)
#: MuPDF could not count the pages, or counted a different number from
#: pdfium, which renders extraction (Task 9b): the check cannot say it has
#: measured every page a reader will render.
_PAGE_COUNT_UNREADABLE_MESSAGE = (
    "This PDF's pages could not be counted reliably, so it could not be checked safely. "
    "Re-export it as a plain scan."
)
#: The page tree is not one both readers can agree on (T9b review round 1):
#: a ``/Type /Page`` naming ``/Kids`` (MuPDF takes the node as a page,
#: pdfium descends its kids), or the pages the tree holds are not the pages
#: MuPDF numbers. Says nothing about how many pages there are.
_PAGE_STRUCTURE_MALFORMED_MESSAGE = (
    "This PDF's page structure is malformed. Re-export it as a plain scan."
)
#: The file holds more objects than :data:`MAX_PDF_OBJECTS` (Task 9c).
_TOO_MANY_PDF_OBJECTS_MESSAGE = (
    "This PDF holds far more internal objects than a scanned paper does "
    f"(over {MAX_PDF_OBJECTS:,}). Re-export it as a plain scan."
)
#: The object streams together inflate past :data:`MAX_OBJECT_STREAM_BYTES`.
_OBJECT_STREAMS_MESSAGE = (
    "This PDF's compressed internal data is far larger than a scanned paper's "
    f"(over {MAX_OBJECT_STREAM_BYTES // 1_000_000} MB once decompressed). "
    "Re-export it as a plain scan."
)
#: The raw scan ran past :data:`MAX_PRESCAN_TOKENS`.
_STRUCTURE_TOO_COMPLEX_MESSAGE = (
    "This PDF's internal structure is too complex to check safely. Re-export it as a plain scan."
)
#: A Flate object stream no reader could inflate from any start it might use
#: (scanner review): refused rather than scored as 0 bytes.
_OBJECT_STREAM_UNREADABLE_MESSAGE = (
    "This PDF's compressed internal data could not be read, so it could not be checked "
    "safely. Re-export it as a plain scan."
)
#: An object stream uses an encoding the bounded inflate cannot measure.
_OBJECT_STREAM_ENCODING_MESSAGE = (
    "This PDF's compressed internal data uses an encoding this service cannot measure "
    "safely; re-export the PDF with standard (Flate) compression."
)
#: Anything else going wrong once MuPDF has opened the file (Task 9b):
#: fail closed, never pass it unmeasured.
_UNCHECKABLE_MESSAGE = "This PDF could not be checked safely. Re-export it as a plain scan."
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

    After the per-page rule, the scan-wide one: when the pages' summed
    pixels exceed :data:`MAX_SCAN_TOTAL_PX`, every page's DPI is multiplied
    by the same ``s = sqrt(MAX_SCAN_TOTAL_PX / total)`` and floored, so the
    sum fits; if that takes any page below :data:`MIN_EXTRACTION_DPI`, the
    scan is refused with :class:`ScanTooLargeError`.
    """
    count = len(pdf)
    if count > MAX_SCAN_PAGES:
        raise ScanTooLargeError(f"The scan has {count} pages; the limit is {MAX_SCAN_PAGES}.")
    sizes = [pdf.get_page_size(index) for index in range(count)]
    plans = [
        PagePlan(index=index, dpi=plan_page_dpi(width_pt, height_pt, dpi=dpi, index=index))
        for index, (width_pt, height_pt) in enumerate(sizes)
    ]
    total = sum(
        width_pt * height_pt * (plan.dpi / 72.0) ** 2
        for plan, (width_pt, height_pt) in zip(plans, sizes, strict=True)
    )
    if total <= MAX_SCAN_TOTAL_PX:
        return plans
    scale = math.sqrt(MAX_SCAN_TOTAL_PX / total)
    scaled = [PagePlan(index=plan.index, dpi=float(math.floor(plan.dpi * scale))) for plan in plans]
    if any(plan.dpi < MIN_EXTRACTION_DPI for plan in scaled):
        raise ScanTooLargeError(
            f"This scan's {count} pages are too large to process together (limit "
            f"{MAX_SCAN_TOTAL_PX // 1_000_000} megapixels per scan). Split it into smaller "
            "scans or rescan at a lower resolution."
        )
    return scaled


_ONE_BYTE_GREY_MODES = frozenset({"1", "L"})
_TWO_BYTE_GREY_MODES = frozenset({"I;16", "I;16L", "I;16B", "I;16N"})


def decode_pixel_cap(mode: str) -> int:
    """The most pixels an image in Pillow ``mode`` may decode to (see :data:`MAX_DECODE_PX_GREY`).

    The one rule for every image path: upload (:func:`check_scan_bytes`),
    extraction (via :func:`plan_image`) and the review crop route.
    """
    if mode in _ONE_BYTE_GREY_MODES:
        return MAX_DECODE_PX_GREY
    if mode in _TWO_BYTE_GREY_MODES:
        return MAX_DECODE_PX_GREY // 2
    return MAX_DECODE_PX


def plan_image(width: int, height: int, mode: str = "RGB") -> int:
    """The integer reduce factor that brings ``width`` x ``height`` under the target.

    ``1`` when the image already fits; :class:`ScanTooLargeError` beyond
    :func:`decode_pixel_cap` for ``mode`` (#256: per mode, so a cheap bilevel
    or greyscale scan is not refused for a pixel count only a colour decode
    would make expensive, while colour keeps :data:`MAX_DECODE_PX`).
    """
    px = width * height
    cap = decode_pixel_cap(mode)
    if px > cap:
        kind = "colour" if cap == MAX_DECODE_PX else "greyscale"
        raise ScanTooLargeError(
            f"This scan is too large to process (limit {cap // 1_000_000} megapixels "
            f"for a {kind} image). Rescan at a lower resolution."
        )
    for factor in _REDUCE_FACTORS:
        if px / (factor * factor) <= MAX_PAGE_PX:
            return factor
    return _REDUCE_FACTORS[-1]  # pragma: no cover -- 160 Mpx / 16 is already under the target


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


@dataclass(frozen=True)
class _PageBound:
    """How many pages :func:`_page_tree` may find, and what to say past it."""

    pages: int
    message: str

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
_SCAN_PAGE_BOUND = _PageBound(MAX_SCAN_PAGES, _SCAN_PAGES_MESSAGE)
#: :func:`check_pdf_page_content`'s bound, the crop route's.
_CROP_PAGE_BOUND = _PageBound(MAX_CROP_PAGES, _CROP_PAGES_MESSAGE)


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
                raise ScanTooLargeError(_PAGE_TREE_TOO_COMPLEX_MESSAGE)
            node_type = _name(doc, node, "Type")
            if node_type == "/Page" and kids:
                # MuPDF takes this node as one page, pdfium descends its kids:
                # not valid PDF, and the readers disagree on which object a
                # page index names, whatever their counts (T9b review round 1).
                raise ScanRejectedError(_PAGE_STRUCTURE_MALFORMED_MESSAGE)
            is_page[node] = node_type == "/Page" or (not kids and node_type != "/Pages")
            pending.extend(kids)
        if is_page[node]:
            pages += 1
            if pages > bound.pages:
                raise ScanTooLargeError(bound.message)
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
                raise ScanRejectedError(_MALFORMED_STRUCTURE_MESSAGE.format(page=index + 1))
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
        raise ScanRejectedError(_PAGE_STRUCTURE_MALFORMED_MESSAGE)
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


#: PDF whitespace (ISO 32000-1 Table 1) and the delimiters that end a token.
_WS = rb"\x00\t\n\x0c\r "
_REGULAR = rb"[^\x00\t\n\x0c\r ()<>\[\]{}/%]"
#: An indirect-object header: ``12 0 obj``, "obj" a whole keyword.
_OBJ_HEADER_RE = re.compile(
    rb"(?<![0-9])[0-9]+[" + _WS + rb"]+[0-9]+[" + _WS + rb"]+obj(?!" + _REGULAR + rb")"
)
#: One PDF token; a literal string's ``(`` is followed by hand (nesting, escapes).
_TOKEN_RE = re.compile(
    rb"(?P<skip>(?:[" + _WS + rb"]+|%[^\r\n]*)+)"
    rb"|(?P<open><<)|(?P<close>>>)"
    rb"|(?P<hex><[0-9A-Fa-f" + _WS + rb"]*>)"
    rb"|(?P<string>\()"
    rb"|(?P<name>/" + _REGULAR + rb"*)"
    rb"|(?P<bracket>[\[\]])"
    rb"|(?P<word>" + _REGULAR + rb"+)"
    rb"|(?P<other>.)",
    re.DOTALL,
)
_STRING_SPECIAL_RE = re.compile(rb"[()\\]")
_NAME_ESCAPE_RE = re.compile(rb"#([0-9A-Fa-f]{2})")
_ENDSTREAM_AT_RE = re.compile(rb"[" + _WS + rb"]*endstream")
_EOL_RE = re.compile(rb"[\r\n]")
#: The name ``/Encrypt``, whole, spelled plainly -- and any name holding a
#: ``#xx`` escape, which is decoded and compared (encrypt parity).
_ENCRYPT_NAME_RE = re.compile(rb"/Encrypt(?!" + _REGULAR + rb")")
_ESCAPED_NAME_RE = re.compile(rb"/" + _REGULAR + rb"*?#[0-9A-Fa-f]{2}" + _REGULAR + rb"*")


def _declares_encryption(data: bytes, budget: _ScanBudget) -> bool:
    """Whether ``/Encrypt`` appears anywhere in ``data`` as a name, escapes decoded.

    Encrypt parity: MuPDF takes ``/Encrypt`` from a ``trailer`` dictionary,
    an xref stream's dictionary, and -- when it repairs a broken xref -- any
    top-level dictionary at all, keyword or none. None of those is ever
    compressed, so the name is always in the raw bytes. Looking for it
    anywhere over-detects (a string or comment that spells it counts), which
    is safe: an encrypted file's object streams only count at their Flate
    ceiling. The plain spelling is found by one C-speed search; each name
    holding an escape is decoded and costs a token of ``budget``.
    """
    if _ENCRYPT_NAME_RE.search(data):
        return True
    for escaped in _ESCAPED_NAME_RE.finditer(data):
        budget.spend()
        if _pdf_name(escaped.group()) == b"Encrypt":
            return True
    return False


#: The most a Flate stream can expand: deflate's longest match (258 bytes)
#: costs at least two bits, so 1032 decoded bytes per compressed byte, and
#: ``1032 x length`` bounds any Flate object stream without decoding it.
_FLATE_MAX_RATIO = 1032


def _stream_data_starts(data: bytes, pos: int) -> list[int]:
    """Every offset a reader may take a stream's data to start at; ``pos`` follows ``stream``.

    Scanner review: the spec's end-of-line after ``stream`` is not what
    readers do. MuPDF (``pdf_parse_ind_obj``) skips any run of spaces, then
    takes a carriage return and an optional line feed -- or else consumes
    exactly one byte, whatever it is. pdfium skips to the end of the line.
    The strict reading takes one CR LF, LF or CR. For every standard
    separator the three agree; where they do not, each is measured and the
    largest counts.
    """
    starts = set()
    strict = pos
    if data[pos : pos + 2] == b"\r\n":
        strict += 2
    elif data[pos : pos + 1] in (b"\n", b"\r"):
        strict += 1
    starts.add(strict)
    mupdf = pos
    while data[mupdf : mupdf + 1] == b" ":
        mupdf += 1
    if data[mupdf : mupdf + 1] == b"\r":
        mupdf += 2 if data[mupdf + 1 : mupdf + 2] == b"\n" else 1
    elif mupdf < len(data):
        mupdf += 1
    starts.add(mupdf)
    eol = _EOL_RE.search(data, pos)
    if eol is not None:
        line = eol.end()
        if eol.group() == b"\r" and data[line : line + 1] == b"\n":
            line += 1
        starts.add(line)
    return sorted(starts)


def _stream_data_end(data: bytes, start: int, length: tuple[str, object] | None) -> int:
    """Where stream data from ``start`` ends, never short of what a reader inflates.

    By ``/Length`` if ``endstream`` follows it, and at least up to the next
    ``endstream`` -- whichever is later.
    """
    found = data.find(b"endstream", start)
    end = found if found >= 0 else len(data)
    if length and length[0] == "number":
        candidate = start + int(length[1])  # type: ignore[call-overload]
        if candidate <= len(data) and _ENDSTREAM_AT_RE.match(data, candidate):
            end = max(end, candidate)
    return end


def _strict_inflate_size(raw: bytes, *, budget: int) -> int | None:
    """:func:`_bounded_inflate_size` for the raw object-stream scan, failing closed.

    ``None`` when the data yields nothing -- a ``zlib.error`` before any
    output, or a stream that decodes to 0 bytes -- where the lenient helper
    would count 0 and pass. A stream that decodes some bytes and then fails
    counts what it yielded, as a reader inflates it.
    """
    decompressor = zlib.decompressobj()
    size = 0
    pending = raw
    try:
        while pending:
            size += len(decompressor.decompress(pending, _INFLATE_CHUNK))
            if size > budget:
                raise ScanTooLargeError(_OBJECT_STREAMS_MESSAGE)
            pending = decompressor.unconsumed_tail
            if decompressor.eof:
                break
    except zlib.error:
        return size or None
    return size or None


@dataclass
class _ScanBudget:
    """Tokens the raw object-stream scan may still read (:data:`MAX_PRESCAN_TOKENS`)."""

    left: int = MAX_PRESCAN_TOKENS

    def spend(self) -> None:
        self.left -= 1
        if self.left < 0:
            raise ScanTooLargeError(_STRUCTURE_TOO_COMPLEX_MESSAGE)


def _pdf_name(token: bytes) -> bytes:
    """A name token's value, ``#xx`` escapes decoded as MuPDF's lexer does."""
    return _NAME_ESCAPE_RE.sub(lambda m: bytes([int(m.group(1), 16)]), token[1:])


def _next_token(data: bytes, pos: int, budget: _ScanBudget) -> tuple[str, bytes, int]:
    """The token at ``pos`` after whitespace and comments: ``(kind, text, end)``.

    ``kind`` is ``"open"``, ``"close"``, ``"hex"``, ``"string"``, ``"name"``,
    ``"bracket"``, ``"word"`` (numbers, ``R``, keywords), ``"other"`` or
    ``"eof"``. A literal string is skipped whole, nested parentheses and
    backslash escapes included, jumping between its special characters.
    """
    while True:
        match = _TOKEN_RE.match(data, pos)
        if match is None:
            return "eof", b"", len(data)
        kind = match.lastgroup or "other"
        if kind == "skip":
            pos = match.end()
            continue
        budget.spend()
        if kind != "string":
            return kind, match.group(), match.end()
        depth, cursor = 1, match.end()
        while depth:
            special = _STRING_SPECIAL_RE.search(data, cursor)
            if special is None:
                return "string", b"", len(data)
            budget.spend()  # each parenthesis or escape in a string counts
            char = data[special.start()]
            cursor = special.end() + (1 if char == 0x5C else 0)  # a backslash escapes one byte
            depth += 1 if char == 0x28 else -1 if char == 0x29 else 0
        return "string", b"", cursor


def _stream_dict(
    data: bytes, pos: int, budget: _ScanBudget
) -> tuple[dict[bytes, tuple[str, object]], int] | None:
    """Parse the dictionary at ``pos``; its top-level entries and where it ends.

    Only what the object-stream scan needs is kept, per top-level key: a
    name value, a number, a reference (``N G R``), or a list of names for an
    array. ``None`` when ``pos`` does not start a dictionary.
    """
    kind, _, pos = _next_token(data, pos, budget)
    if kind != "open":
        return None
    entries: dict[bytes, tuple[str, object]] = {}
    depth, key = 1, None
    while depth:
        kind, text, pos = _next_token(data, pos, budget)
        if kind == "eof":
            return entries, pos
        if kind == "open":
            if depth == 1 and key is not None:
                entries[key] = ("dict", None)  # a top-level key whose value is a dictionary
            depth += 1
            key = None
        elif kind == "close":
            depth -= 1
        elif depth == 1 and key is None:
            key = _pdf_name(text) if kind == "name" else None
        elif depth == 1 and key is not None:
            if kind == "name":
                entries[key] = ("name", _pdf_name(text))
            elif kind == "word" and text.isdigit():
                after_kind, after, after_end = _next_token(data, pos, budget)
                last_kind, last, last_end = _next_token(data, after_end, budget)
                if after_kind == "word" and after.isdigit() and (last_kind, last) == ("word", b"R"):
                    entries[key] = ("ref", None)
                    pos = last_end
                else:
                    entries[key] = ("number", int(text))
            elif kind == "bracket" and text == b"[":
                names: list[bytes] = []
                simple = True
                while True:
                    kind, text, pos = _next_token(data, pos, budget)
                    if kind in ("eof", "close") or (kind, text) == ("bracket", b"]"):
                        break
                    if kind == "name":
                        names.append(_pdf_name(text))
                    else:
                        simple = False
                entries[key] = ("array", names if simple else None)
            else:
                entries[key] = ("other", None)
            key = None
    return entries, pos


def check_object_stream_bytes(data: bytes) -> None:
    """Bound a PDF's object streams from its raw bytes, before any reader opens it.

    Task 9c review round 2. With a damaged xref, MuPDF repairs it while the
    file is being OPENED, and repair loads every object stream it finds --
    parsing each whole, container-mates and all -- so a 20 KB file took a
    bare ``pymupdf.open`` to 459 MB, before :func:`_check_object_streams`
    (which reads the opened xref) can run. So the streams are found here, in
    the raw bytes, the way repair finds them: an indirect object whose
    dictionary names ``/Type /ObjStm`` directly (the name may be spelled
    ``/Type/ObjStm``, split by whitespace or a comment, or ``#xx``-escaped;
    this parses it as MuPDF's lexer does). Each one's data is taken by a
    direct ``/Length`` when ``endstream`` follows it, else up to the next
    ``endstream``, and measured with the bounded inflate: unfiltered it is
    its length, a single ``/FlateDecode`` or ``/Fl`` (bare or in a
    one-element array) is inflated in bounded chunks, anything else
    (another filter, a chain, a ``/Filter`` given by reference) cannot be
    measured and is refused (:data:`_OBJECT_STREAM_ENCODING_MESSAGE`). Past
    :data:`MAX_OBJECT_STREAM_BYTES` in total the file is refused
    (:data:`_OBJECT_STREAMS_MESSAGE`).

    Past :data:`MAX_PRESCAN_TOKENS` tokens the file is refused as too
    complex to check (:data:`_STRUCTURE_TOO_COMPLEX_MESSAGE`).

    O(file bytes): each byte is tokenized at most once -- a header found
    inside a span already parsed (a dictionary, or a stream's data) is
    skipped, since its dictionary is part of that span -- and a stream's
    data is inflated in bounded chunks, never held decoded. Anything that
    only looks like a header inside a string or a comment can only add to
    the total, never hide a container from it.

    Upload, extraction and the whole-document check run this first; a
    caller that opens a stored PDF with MuPDF itself must run it before
    ``pymupdf.open``.
    """
    budget = _ScanBudget()
    containers: list[tuple[tuple[str, object] | None, list[tuple[int, int]]]] = []
    scanned_to = 0
    for header in _OBJ_HEADER_RE.finditer(data):
        budget.spend()
        if header.start() < scanned_to:
            continue
        parsed = _stream_dict(data, header.end(), budget)
        if parsed is None:
            scanned_to = header.end()
            continue
        entries, dict_end = parsed
        scanned_to = dict_end
        kind, keyword, start = _next_token(data, dict_end, budget)
        if (kind, keyword) != ("word", b"stream"):
            continue
        starts = _stream_data_starts(data, start)
        spans = [(begin, _stream_data_end(data, begin, entries.get(b"Length"))) for begin in starts]
        scanned_to = max(scanned_to, *(end for _, end in spans))
        if entries.get(b"Type") == ("name", b"ObjStm"):
            containers.append((entries.get(b"Filter"), spans))
    encrypted = _declares_encryption(data, budget)
    total = 0
    for filters, spans in containers:
        longest = max(end - begin for begin, end in spans)
        if filters is None or filters == ("array", []):
            size = longest
        elif filters in (("name", b"FlateDecode"), ("name", b"Fl")) or filters in (
            ("array", [b"FlateDecode"]),
            ("array", [b"Fl"]),
        ):
            if encrypted:
                # Ciphertext: inflating it proves nothing, and with an empty user
                # password its plaintext is the attacker's to choose. Count the
                # most Flate can expand this many bytes to.
                size = longest * _FLATE_MAX_RATIO
            else:
                sizes = [
                    _strict_inflate_size(data[begin:end], budget=MAX_OBJECT_STREAM_BYTES - total)
                    for begin, end in spans
                ]
                decoded = [found for found in sizes if found]
                if not decoded and longest > 0:
                    raise ScanRejectedError(_OBJECT_STREAM_UNREADABLE_MESSAGE)
                size = max(decoded, default=0)
        else:
            raise ScanRejectedError(_OBJECT_STREAM_ENCODING_MESSAGE)
        total += size
        if total > MAX_OBJECT_STREAM_BYTES:
            raise ScanTooLargeError(_OBJECT_STREAMS_MESSAGE)


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
        raise ScanTooLargeError(_TOO_MANY_PDF_OBJECTS_MESSAGE)
    try:
        pdf = _mupdf.pdf_document_from_fz_document(doc.this)  # type: ignore[no-untyped-call]
        containers: set[int] = set()
        for number in range(1, xref_length):
            entry = _mupdf.ll_pdf_get_xref_entry_no_null(pdf.m_internal, number)  # type: ignore[no-untyped-call]
            if entry.type == "o" and 0 < entry.ofs < xref_length:
                containers.add(int(entry.ofs))
    except Exception as exc:
        raise ScanRejectedError(_UNCHECKABLE_MESSAGE) from exc
    total = 0
    for container in sorted(containers):
        if not doc.xref_is_stream(container):  # type: ignore[no-untyped-call]
            continue  # names no stream: MuPDF resolves its objects to null
        try:
            total += decoded_stream_size(
                doc, container, budget=MAX_OBJECT_STREAM_BYTES - total, page_index=0
            )
        except ScanUnsupportedEncodingError as exc:
            raise ScanRejectedError(_OBJECT_STREAM_ENCODING_MESSAGE) from exc
        except ScanTooLargeError as exc:
            raise ScanTooLargeError(_OBJECT_STREAMS_MESSAGE) from exc


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

    Images are not content and their streams are never read; instead each
    image's DECLARED ``/Width x /Height`` -- and its ``/SMask``'s and
    stream ``/Mask``'s -- is checked against :data:`MAX_DECODE_PX`,
    because the renderer allocates for the declared size whatever the
    stream holds. Images are found both by ``page.get_images(full=True)``
    and by the walk, which reaches the ones ``get_images`` does not list.

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
        raise ScanRejectedError(_PAGE_COUNT_UNREADABLE_MESSAGE) from exc
    # Final review M1: the walk visits every page, so a document over the
    # page cap is refused before any of it is read, whoever the caller is.
    # `page_count` is the declared `/Count`; `_page_tree` holds the same cap
    # against the real tree, so understating `/Count` does not dodge it.
    if page_count > MAX_SCAN_PAGES:
        raise ScanTooLargeError(f"The scan has {page_count} pages; the limit is {MAX_SCAN_PAGES}.")
    # Task 9b: extraction renders with pdfium. A page it counts that MuPDF
    # does not is a page this walk never measures (a `/Count 0` over real
    # kids: MuPDF sees none, pdfium renders them all).
    if pdfium_pages is not None and page_count != pdfium_pages:
        raise ScanRejectedError(_PAGE_COUNT_UNREADABLE_MESSAGE)
    try:
        tree = _page_tree(doc, bound=_SCAN_PAGE_BOUND)
    except ScanRejectedError:
        raise
    except Exception as exc:
        raise ScanRejectedError(_WALK_FAILED_MESSAGE.format(page=1)) from exc
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
        raise ScanRejectedError(_PAGE_UNREADABLE_MESSAGE.format(page=page_index + 1)) from exc
    holders = tree.holders.get(page_xref)
    if holders is None:
        raise ScanRejectedError(_MALFORMED_STRUCTURE_MESSAGE.format(page=page_index + 1))
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
                raise ScanRejectedError(_MALFORMED_STRUCTURE_MESSAGE.format(page=page_index + 1))
            start.append((xref, "any"))
        start.extend(ref for holder in holders for ref in _resources_refs(doc, holder))
        _walk_resource_graph(doc, start, walk)
        _walk_annotations(doc, page_xref, walk)
    except ScanRejectedError:
        raise
    except Exception as exc:
        raise ScanRejectedError(_WALK_FAILED_MESSAGE.format(page=page_index + 1)) from exc
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
        raise ScanTooLargeError(_CROP_PAGES_MESSAGE)
    try:
        tree = _page_tree(doc, bound=_CROP_PAGE_BOUND)
    except ScanRejectedError:
        raise
    except Exception as exc:
        raise ScanRejectedError(_WALK_FAILED_MESSAGE.format(page=1)) from exc
    _check_page(doc, tree, _ContentBudget(), page_index)


def _check_opened(open_doc: Callable[[], pymupdf.Document], pdfium_pages: int | None) -> None:
    """:func:`check_pdf_content` on the document ``open_doc`` opens, failing closed.

    The one exemption is narrow (Task 9b): MuPDF will not open the bytes at
    all AND pdfium counted no pages either -- garbage with a ``%PDF``
    header, which extraction fails on too (the upload routes' tests post
    ``%PDF-1.4 fake``). If pdfium counted pages MuPDF cannot open, the
    readers disagree and pdfium would render pages never measured: refused.
    Once MuPDF has opened the file, anything but a clean pass is a refusal.

    ``pdfium_pages`` of ``None`` (pdfium could not open the file, or no
    caller asked it) and ``0`` (pdfium opened it and found no pages) are
    treated alike, and both pass when MuPDF cannot open the file either:
    then neither renderer has a page to render. Extraction renders only the
    pages pdfium plans, none here (``rasterise_pdf_to_pages`` then raises
    for an empty result), and the preview and crop routes render with
    MuPDF, which cannot open it.
    """
    try:
        doc = open_doc()
    except Exception as exc:
        if pdfium_pages:
            raise ScanRejectedError(_PAGE_COUNT_UNREADABLE_MESSAGE) from exc
        return
    try:
        check_pdf_content(doc, pdfium_pages=pdfium_pages)
    except ScanRejectedError:
        raise
    except Exception as exc:
        raise ScanRejectedError(_UNCHECKABLE_MESSAGE) from exc
    finally:
        doc.close()  # type: ignore[no-untyped-call]


def check_pdf_content_bytes(data: bytes, *, pdfium_pages: int | None = None) -> None:
    """:func:`check_pdf_content` on an in-memory PDF (see :func:`_check_opened`).

    ``pdfium_pages``: pdfium's page count for the same bytes, when the
    caller has it, so the two readers' counts are compared.
    """
    check_object_stream_bytes(data)  # before any open: repair parses containers at open
    _check_opened(
        lambda: pymupdf.open(stream=data, filetype="pdf"),  # type: ignore[no-untyped-call]
        pdfium_pages,
    )


def canonical_pdf_bytes(data: bytes) -> bytes:
    """MuPDF's pages-only rewrite of ``data``: the one sanctioned source of pdfium input.

    Nothing may hand pdfium a PDF for rendering except through this function
    (Task 9c): the rewrite holds exactly what the content check measured.

    Task 9c (user decision): extraction renders with pdfium but this module
    measures with MuPDF, and the two repair a damaged file differently -- an
    object defined twice under an xref with 19-byte entries is the clean
    first definition to MuPDF (it reads the xref) and a content bomb to
    pdfium (it rebuilds the xref by scanning). Extraction therefore checks
    and renders these bytes, never the stored file, so pdfium can only see
    the objects MuPDF resolved.

    It resolves only what the content check has bounded (review round 1):

    1. The whole-document check (:func:`check_pdf_content`) runs on the
       original first: the object-stream and object-count bounds, the page
       cap, the page-tree bounds and the walk of every page's content,
       resources and annotation appearances. Anything it refuses is refused.
    2. Then the pages alone are copied into a new document --
       ``insert_pdf(links=False, annots=True, widgets=True)`` plus each
       page's ``/Group`` -- and that is written with ``tobytes(garbage=1)``.
       The copy resolves each page's ``/Contents``, ``/Resources``, page
       boxes, ``/Rotate``, ``/UserUnit``, ``/Group`` and annotations (form
       fields through pymupdf's widget copy), and nothing else: an object
       hung off the catalog, the trailer or a page-dict key no renderer
       reads is never parsed, whatever its size. ``links=False`` because
       rebuilding links loads every page and resolves link destinations
       through the catalog; a ``/Link`` annotation draws nothing in pdfium
       without an appearance stream, which link annotations do not carry in
       practice. ``/Group`` is added back because ``insert_pdf`` omits it
       and a page's transparency group changes how it composites.
       Streams are copied as stored: nothing is decompressed, re-encoded
       or rewritten (no ``deflate``, ``expand`` or ``clean`` -- ``clean``
       parses content streams, the very work a bomb exploits), and no page
       is loaded, so no annotation appearance is regenerated. All 26
       committed PDFs (171 pages) render pixel-identical from the rewrite.

    What an annotation's own keys or the form-field tree reference is
    copied without being walked; a compressed object there is bounded by
    the object-stream bound, an uncompressed one by the upload size cap.

    Raises :class:`ScanRejectedError` (or :class:`ScanTooLargeError`) for
    anything the check refuses, and when MuPDF cannot open or rewrite the
    bytes (garbage, or a password-protected file: extraction failed on both
    before, in pdfium, and nothing here can check what it cannot open).
    When MuPDF finds no pages, pdfium is asked for its count of the same
    bytes -- a count only, nothing is rendered: pages pdfium would find
    are pages MuPDF never measured, so that is refused too
    (:data:`_PAGE_COUNT_UNREADABLE_MESSAGE`); a PDF neither reader finds a
    page in is a :class:`ValueError`, extraction's contract for an empty
    PDF (MuPDF will not write one).
    """
    check_object_stream_bytes(data)  # before any open: repair parses containers at open
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")  # type: ignore[no-untyped-call]
    except Exception as exc:
        raise ScanRejectedError(_UNCHECKABLE_MESSAGE) from exc
    try:
        if doc.needs_pass:
            raise ScanRejectedError(_UNCHECKABLE_MESSAGE)
        try:
            check_pdf_content(doc)
            page_count = int(doc.page_count)
        except ScanRejectedError:
            raise
        except Exception as exc:
            raise ScanRejectedError(_UNCHECKABLE_MESSAGE) from exc
        if page_count == 0:
            if _pdfium_page_count(data):
                raise ScanRejectedError(_PAGE_COUNT_UNREADABLE_MESSAGE)
            raise ValueError("the PDF has no pages")
        try:
            return _copy_pages(doc)
        except Exception as exc:
            raise ScanRejectedError(_UNCHECKABLE_MESSAGE) from exc
    finally:
        doc.close()  # type: ignore[no-untyped-call]


def _copy_pages(doc: pymupdf.Document) -> bytes:
    """``doc``'s pages -- and only what they reference -- written as a new PDF.

    See :func:`canonical_pdf_bytes` for what is copied and why. Everything
    here goes through ONE graft map, so an object reached twice -- a layer
    named by a page's ``/OC`` and by ``/OCProperties``, a colour space shared
    by a page's resources and its ``/Group`` -- is one object in the copy.
    ``insert_pdf`` ignores its ``_gmap`` argument and uses the map
    registered for the source in ``out.Graftmaps`` (pymupdf 1.28), so the
    map is registered there first.
    """
    mupdf = _mupdf
    out = pymupdf.open()  # type: ignore[no-untyped-call]
    try:
        graft_map = pymupdf.Graftmap(out)  # type: ignore[no-untyped-call]
        out.Graftmaps[doc._graft_id] = graft_map
        out.insert_pdf(doc, links=False, annots=True, widgets=True)  # type: ignore[no-untyped-call]
        source = mupdf.pdf_document_from_fz_document(doc.this)  # type: ignore[no-untyped-call]
        target = mupdf.pdf_document_from_fz_document(out.this)  # type: ignore[no-untyped-call]
        for index in range(int(doc.page_count)):
            source_page = mupdf.pdf_lookup_page_obj(source, index)  # type: ignore[no-untyped-call]
            group = mupdf.pdf_dict_gets(source_page, "Group")  # type: ignore[no-untyped-call]
            if group.m_internal:
                target_page = mupdf.pdf_lookup_page_obj(target, index)  # type: ignore[no-untyped-call]
                grafted = mupdf.pdf_graft_mapped_object(graft_map.this, group)  # type: ignore[no-untyped-call]
                mupdf.pdf_dict_puts(target_page, "Group", grafted)  # type: ignore[no-untyped-call]
        # Task 9c review round 2: a page's optional content is drawn or
        # hidden by the catalog's /OCProperties, not by the page; without it
        # every layer renders, so content a file hides by default would reach
        # the marker while the teacher's preview (MuPDF, on the stored file)
        # hides it. Only /OCGs and /D, the default configuration a renderer
        # applies, are carried; the alternative /Configs a viewer can switch
        # to are not.
        source_catalog = mupdf.pdf_dict_gets(mupdf.pdf_trailer(source), "Root")  # type: ignore[no-untyped-call]
        properties = mupdf.pdf_dict_gets(source_catalog, "OCProperties")  # type: ignore[no-untyped-call]
        if properties.m_internal and mupdf.pdf_is_dict(properties):  # type: ignore[no-untyped-call]
            copied = mupdf.pdf_new_dict(target, 2)  # type: ignore[no-untyped-call]
            for key in ("OCGs", "D"):
                value = mupdf.pdf_dict_gets(properties, key)  # type: ignore[no-untyped-call]
                if value.m_internal:
                    grafted = mupdf.pdf_graft_mapped_object(graft_map.this, value)  # type: ignore[no-untyped-call]
                    mupdf.pdf_dict_puts(copied, key, grafted)  # type: ignore[no-untyped-call]
            target_catalog = mupdf.pdf_dict_gets(mupdf.pdf_trailer(target), "Root")  # type: ignore[no-untyped-call]
            added = mupdf.pdf_add_object(target, copied)  # type: ignore[no-untyped-call]
            mupdf.pdf_dict_puts(target_catalog, "OCProperties", added)  # type: ignore[no-untyped-call]
        rewrite: bytes = out.tobytes(garbage=1)  # type: ignore[no-untyped-call]
        return rewrite
    finally:
        out.close()  # type: ignore[no-untyped-call]


def _pdfium_page_count(data: bytes) -> int:
    """The page count pdfium gives ``data``, or 0 if it cannot open it. Renders nothing."""
    try:
        pdf = pdfium.PdfDocument(data)
    except Exception:
        return 0
    try:
        return len(pdf)
    except Exception:
        return 0
    finally:
        pdf.close()


def _pdfium_plan(data: bytes) -> int | None:
    """Plan ``data``'s pages as extraction will; pdfium's page count, or ``None``.

    Raises :class:`ScanTooLargeError` for a geometry extraction refuses.
    ``None`` when pdfium cannot open the bytes or count their pages. A page
    pdfium cannot size (``plan_pdf_pages`` raising pypdfium2's own
    ``PdfiumError``) still returns the count: extraction's own planning
    refuses that file before rendering any of it, but the crop route
    renders with MuPDF, so :func:`check_scan_bytes` runs the MuPDF check
    either way (Task 9b; it used to be skipped here).
    """
    try:
        pdf = pdfium.PdfDocument(data)
    except Exception:
        return None
    count: int | None = None
    try:
        count = len(pdf)
        plan_pdf_pages(pdf)
    except ScanTooLargeError:
        raise
    except Exception:
        return count
    finally:
        pdf.close()
    return count


def check_scan_bytes(data: bytes) -> None:
    """The upload-time check: page sizes and image headers only, nothing rendered.

    Bytes that neither pypdfium2 nor Pillow can open are NOT rejected here --
    extraction fails on them later, exactly as it does today -- so the only
    422 this produces is a measured, over-limit geometry (or Pillow's
    decompression-bomb guard, which fires on the declared size before any
    pixel is decoded). A document pdfium opens but cannot size a page of
    (``plan_pdf_pages`` raising pypdfium2's own ``PdfiumError``) is not
    refused for that alone: extraction's planning refuses it before
    rendering anything, as it does today.

    And, for a PDF, the decoded size of each page's content streams (Task
    11b) -- read from the raw streams with a bounded inflate, never rendered
    -- which runs whenever MuPDF can open the file, whatever pdfium made of
    it (Task 9b: skipping it on a pdfium planning failure let a page tree
    too deep for pdfium through unmeasured, and the crop route renders with
    MuPDF). It is given pdfium's page count, and refuses a file the two
    readers count differently, or whose pages MuPDF counted but cannot
    read (:func:`check_pdf_content`).
    """
    if looks_like_pdf(data):
        # Task 9c review round 2: object streams first, from the raw bytes --
        # MuPDF's xref repair parses them while opening, before any check.
        check_object_stream_bytes(data)
        # Task 11b: geometry first, then content -- with pdfium's count, so
        # a page only pdfium would render is not left unmeasured (Task 9b).
        check_pdf_content_bytes(data, pdfium_pages=_pdfium_plan(data))
        return
    try:
        with Image.open(io.BytesIO(data)) as opened:
            # #256: judged against its own mode's ceiling, from the header.
            plan_image(opened.width, opened.height, opened.mode)
    except Image.DecompressionBombError as exc:
        raise ScanTooLargeError(
            "This scan's image is too large to process safely. Rescan at a lower resolution."
        ) from exc
    except ScanTooLargeError:
        raise
    except Exception:
        return
