"""The scan limits every scan module shares: constants, messages, errors, planning.

#262 split ``scan_limits`` into this leaf and three PDF modules. This module
owns the numeric limits (:data:`MAX_SCAN_PAGES` and the rest), every
user-facing refusal message, the error types, the page and image planners
(:func:`plan_page_dpi`, :func:`plan_pdf_pages`, :func:`decode_pixel_cap`,
:func:`plan_image`) and the scan-image opener (:func:`open_scan_image`, with
its format allowlist). It imports none of the other scan modules; they and
:mod:`lemely.io.scan_limits`, which re-exports every name here, import it.
See :mod:`lemely.io.scan_limits` for the rules these numbers enforce.

Every refusal carries a ``reason`` code (:data:`REFUSAL_REASONS`), which the
upload check logs beside the error class (#276, #273):

* ``page_px``: one PDF page's pixels are past the decode ceiling.
* ``scan_px``: the pages' summed pixels are past the whole-scan budget.
* ``page_cap``: more pages than :data:`MAX_SCAN_PAGES`.
* ``crop_page_cap``: more pages than :data:`MAX_CROP_PAGES` (the crop and
  preview routes).
* ``image_px``: an image's pixels are past its mode's ceiling, as declared by
  the file, a PDF's image object, or Pillow's own bomb guard.
* ``webp_px``: a WebP past its lower ceiling.
* ``format_not_allowed``: an image format outside :data:`SCAN_IMAGE_FORMATS`.
* ``page_content``: one page's drawing data is over its decoded-size budget.
* ``scan_content``: the whole scan's drawing data is over its budget.
* ``content_encoding``: a content stream's filter cannot be size-bounded.
* ``page_objects``: one page reaches more objects than the per-page cap.
* ``page_tree``: the page tree is too big to read within the work bound.
* ``malformed``: a page's structure could hide drawn content from the walk.
* ``prescan_tokens``: the raw object-stream scan hit its token budget.
* ``objstm_unreadable``: an object stream holds no readable data.
* ``objstm_separator``: as ``objstm_unreadable``, but a tab, NUL or form feed
  follows ``stream``.
* ``objstm_encoding``: an object stream's filter cannot be size-bounded.
* ``objstm_bomb``: the object streams decode to more than the total cap.
* ``encrypted_objstm``: an encrypted file's object streams, counted at
  Flate's worst case, are over the total cap (S4).
* ``too_many_objects``: more objects in the file than :data:`MAX_PDF_OBJECTS`.
* ``uncheckable``: a reader failed on the file, so it cannot be measured.
* ``reader_disagreement``: pdfium and MuPDF disagree about the pages.
"""

from __future__ import annotations

import io
import math
import warnings
from dataclasses import dataclass
from typing import IO, TYPE_CHECKING, NoReturn

from PIL import Image

from lemely.runtime.errors import LemelyError

if TYPE_CHECKING:
    import pypdfium2 as pdfium
    from PIL import ImageFile


#: The committed question paper has 16 pages; answer booklets with
#: continuation sheets reach the low 30s. Also bounds the number of page
#: images one extraction call carries.
MAX_SCAN_PAGES = 40
#: The crop and preview routes' page bound (user decision, review round 1 on
#: triage F8; the preview by owner decision S3, #269), separate from
#: :data:`MAX_SCAN_PAGES`: each renders one page, so a stored scan over 40
#: pages keeps its crops and previews, but their content check reads the page
#: tree (:func:`_page_tree`), which costs about 33 us per page -- tens of
#: seconds for the million-odd pages a 25 MB file can declare. Counted from
#: the tree a reader descends, not from ``/Count``, by MuPDF's rule: a
#: ``/Type /Page`` is a page, a ``/Type /Pages`` is not, and an untyped node
#: is one if it names no ``/Kids`` (see :func:`_page_tree`).
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
#: 100 Mpx of either costs 96 MB), 16-bit grey at two, "RGB" at four (stored
#: padded, as RGBX) -- so a 1200 dpi bilevel A4 office scan (9921 x 14031 =
#: 139 Mpx, 0.04 MB on disk) is a 139 MB decode where the same pixels in colour
#: would be 556 MB. Bilevel
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
#: The crop and preview routes' page bound (:data:`MAX_CROP_PAGES`) bit; the
#: one text serves both, so it names both.
_CROP_PAGES_MESSAGE = (
    f"The scan has more than {MAX_CROP_PAGES} pages; the limit for a crop or a preview "
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
#: The same refusal when the byte after ``stream`` is a tab, NUL or form feed
#: (#273 item 2): the reader starts the checker tries do not agree with the
#: ones MuPDF and pdfium use there, so the message names the cause. Acceptance
#: is deferred until the ``objstm_separator`` log shows real uploads.
_OBJECT_STREAM_SEPARATOR_MESSAGE = (
    "This PDF separates its data with characters the checker does not accept. "
    "Re-export it as a plain scan."
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
    """A scan this service will not render; the message says why and what to do.

    ``reason`` is a short code from :data:`REFUSAL_REASONS` naming which rule
    refused it, for the logs (#276, #273). It never reaches a user: ``str()``
    is the message alone, so every ``detail=str(exc)`` is unchanged. Both go
    to ``args``, so a pickle round trip (a render worker's refusal crossing
    its process boundary) rebuilds the error with its reason.
    """

    def __init__(self, message: str, reason: str = "unspecified") -> None:
        super().__init__(message, reason)
        self.reason = reason

    def __str__(self) -> str:
        return str(self.args[0])


#: The reason codes a refusal may carry; see the module docstring. A refusal
#: left on the default ``"unspecified"`` is a bug the AST sweep in
#: ``tests/test_refusal_reasons.py`` fails on.
REFUSAL_REASONS = frozenset(
    {
        "crop_page_cap",
        "content_encoding",
        "encrypted_objstm",
        "format_not_allowed",
        "image_px",
        "malformed",
        "objstm_bomb",
        "objstm_encoding",
        "objstm_separator",
        "objstm_unreadable",
        "page_cap",
        "page_content",
        "page_objects",
        "page_px",
        "page_tree",
        "prescan_tokens",
        "reader_disagreement",
        "scan_content",
        "scan_px",
        "too_many_objects",
        "uncheckable",
        "webp_px",
    }
)


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
        f"(limit {MAX_DECODE_PX // 1_000_000} megapixels). Rescan at a lower resolution.",
        reason="page_px",
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
        raise ScanTooLargeError(
            f"The scan has {count} pages; the limit is {MAX_SCAN_PAGES}.", reason="page_cap"
        )
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
            "scans or rescan at a lower resolution.",
            reason="scan_px",
        )
    return scaled


_ONE_BYTE_GREY_MODES = frozenset({"1", "L"})
_TWO_BYTE_GREY_MODES = frozenset({"I;16", "I;16L", "I;16B", "I;16N"})
#: Every mode :func:`decode_pixel_cap` lets past :data:`MAX_DECODE_PX`.
#: ``rasterise.single_channel_or_rgb`` takes each of them to "L" (derived
#: from this set, not a copy of it), so no mode given the grey ceiling is
#: ever expanded to three channels before its reduce.
GREY_CEILING_MODES = _ONE_BYTE_GREY_MODES | _TWO_BYTE_GREY_MODES


#: #256 review round 2: Pillow 12 decodes every WebP, still or animated,
#: through ``WebPAnimDecoder``, which keeps extra full-canvas RGBA buffers,
#: and a grey WebP decodes as RGB. Measured: extracting a 39.7 Mpx WebP cost
#: 609 MB over baseline against 192 MB for the same PNG -- about three times
#: the colour budget -- so WebP gets a third of it, whatever its mode.
MAX_DECODE_PX_WEBP = MAX_DECODE_PX // 3


#: Task 11 review (owner decision 1): bytes per pixel a colour mode decodes
#: to at 8 bits a sample -- the samples as MuPDF holds them for the preview,
#: before its 8-bit pixmap (measured: an image there costs its samples plus
#: that pixmap, 6.1 bytes a pixel for 8-bit RGB, 8.2 for RGBA and CMYK, 9.2
#: for 16-bit RGB, 12.4 for 16-bit RGBA). ``I`` and ``F`` are one 32-bit
#: sample. Two-channel and palette modes stay at RGB's ceiling (a palette is
#: drawn as RGB). Grey has its own ceilings above.
_COLOUR_BYTES_PER_PIXEL = {
    "RGB": 3,
    "YCbCr": 3,
    "LAB": 3,
    "HSV": 3,
    "RGBA": 4,
    "RGBX": 4,
    "RGBa": 4,
    "CMYK": 4,
    "I": 4,
    "F": 4,
}
#: Modes whose 4 bytes are one 32-bit sample: a 32-bit file is not charged twice.
_WIDE_SAMPLE_MODES = frozenset({"I", "F"})
#: :data:`MAX_DECODE_PX` is set for 8-bit RGB, three bytes a pixel.
_COLOUR_CEILING_BYTES = 3


def decode_pixel_cap(mode: str, image_format: str | None = None, *, sample_bits: int = 8) -> int:
    """The most pixels an image may decode to, by Pillow ``mode`` and ``image_format``.

    The one rule for every image path: upload (:func:`check_scan_bytes`),
    extraction (via :func:`plan_image`) and the review crop route, each
    passing the opened image's ``mode`` and ``format``. A WebP gets
    :data:`MAX_DECODE_PX_WEBP` whatever its mode; grey its own ceilings (see
    :data:`MAX_DECODE_PX_GREY`). Colour is charged by the bytes a pixel
    decodes to (owner decision, Task 11 review): ``MAX_DECODE_PX`` (40 Mpx)
    for 8-bit RGB's three, and proportionally fewer above, ``MAX_DECODE_PX *
    3 // bytes``: RGBA, CMYK and 32-bit ``I``/``F`` 30 Mpx, 16-bit RGB 20 Mpx,
    16-bit RGBA or CMYK 15 Mpx. ``sample_bits`` is the file's depth a sample
    (:func:`_image_sample_bits`): Pillow names a 16-bit RGB image ``"RGB"``,
    so the mode alone cannot say. ``image_format`` is ``None`` for an image
    that is not straight from a file (a converted copy).
    """
    if image_format == "WEBP":
        return MAX_DECODE_PX_WEBP
    if mode in _ONE_BYTE_GREY_MODES:
        return MAX_DECODE_PX_GREY
    if mode in _TWO_BYTE_GREY_MODES:
        return MAX_DECODE_PX_GREY // 2
    per_pixel = _COLOUR_BYTES_PER_PIXEL.get(mode, _COLOUR_CEILING_BYTES)
    if sample_bits > 8 and mode not in _WIDE_SAMPLE_MODES:
        per_pixel *= -(-sample_bits // 8)
    return MAX_DECODE_PX * _COLOUR_CEILING_BYTES // max(_COLOUR_CEILING_BYTES, per_pixel)


#: The endings of a raw mode naming 16 bits a SAMPLE: the depth, then the
#: byte order (``"RGB;16B"`` for a 16-bit RGB PNG, ``"LA;16B"``). Not
#: ``"BGR;16"``: a 5-6-5 BMP's two bytes a PIXEL, which decode to 8-bit RGB.
_SIXTEEN_BIT_SAMPLE_RAWMODES = (";16B", ";16L", ";16N")


def _image_sample_bits(opened: ImageFile.ImageFile) -> int:
    """The file's bits a sample, as far as the colour cap is concerned: 8 unless it says more.

    Read from the header, before anything is decoded. A TIFF says it in
    ``BitsPerSample`` (tag 258): its raw modes cannot be trusted for it,
    since an uncompressed planar TIFF gets one raw mode a band (``"R"``,
    ``"G"``, ...) with no depth at all (Task 11 re-review). Anything else
    says it in the decoder's raw mode (:data:`_SIXTEEN_BIT_SAMPLE_RAWMODES`).
    """
    tags = getattr(opened, "tag_v2", None)
    if tags is not None:
        declared = tags.get(258)
        if isinstance(declared, tuple) and declared:
            return max(int(bits) for bits in declared)
        if isinstance(declared, int):
            return declared
    for tile in opened.tile:
        args = tile.args
        raw = args if isinstance(args, str) else args[0] if args else None
        if isinstance(raw, str) and raw.endswith(_SIXTEEN_BIT_SAMPLE_RAWMODES):
            return 16
    return 8


def _refuse_over_cap(cap: int, mode: str, image_format: str | None) -> NoReturn:
    """Raise the too-large refusal for an image over ``cap``, worded for its kind."""
    mpx = cap // 1_000_000
    if image_format == "WEBP":
        raise ScanTooLargeError(
            f"This WebP image is too large to process (limit {mpx} megapixels for WebP, "
            "which costs far more to decode than other formats). Save it as a PNG or "
            "JPEG, or at a lower resolution.",
            reason="webp_px",
        )
    if mode in _ONE_BYTE_GREY_MODES:
        limit = f"{mpx} megapixels for a black-and-white or greyscale image"
    elif mode in _TWO_BYTE_GREY_MODES:
        limit = f"{mpx} megapixels for a 16-bit greyscale image"
    else:
        # Colour, but also "LA", "I" and "F": say what the limit is and
        # how to get the larger one, rather than name the image's kind.
        limit = (
            f"{mpx} megapixels; a black-and-white or 8-bit greyscale scan may be up "
            f"to {MAX_DECODE_PX_GREY // 1_000_000}"
        )
    raise ScanTooLargeError(
        f"This scan is too large to process (limit {limit}). Rescan at a lower resolution.",
        reason="image_px",
    )


def plan_image(width: int, height: int, mode: str = "RGB", image_format: str | None = None) -> int:
    """The integer reduce factor that brings ``width`` x ``height`` under the target.

    ``1`` when the image already fits; :class:`ScanTooLargeError` beyond
    :func:`decode_pixel_cap` for ``mode`` and ``image_format`` (#256: per
    mode, so a cheap bilevel or greyscale scan is not refused for a pixel
    count only a colour decode would make expensive, while colour keeps
    :data:`MAX_DECODE_PX`; and WebP, dearer to decode, its own lower cap).
    """
    px = width * height
    cap = decode_pixel_cap(mode, image_format)
    if px > cap:
        _refuse_over_cap(cap, mode, image_format)
    for factor in _REDUCE_FACTORS:
        if px / (factor * factor) <= MAX_PAGE_PX:
            return factor
    return _REDUCE_FACTORS[-1]  # pragma: no cover -- 160 Mpx / 16 is already under the target


#: #256 review: the raster formats a scan image may be, by Pillow format name.
#: An allowlist, not a denylist: some formats decode inside ``Image.open``
#: itself, before any pixel cap can run -- ICO decodes the image it wraps
#: (measured: a 76 KB ICO wrapping a 64 Mpx PNG grew RSS by 68 MB in the open
#: alone), ICNS embeds PNG and JPEG 2000 -- and six of Pillow's plugins (IM,
#: IMT, IPTC, PCD, SPIDER, TGA) have no prefix sniffer to recognise them by.
#: These open from their headers (measured: under 7 MB for 64 Mpx) and are
#: what scanners and phones write. Opening is not decoding, though: a WebP
#: DECODES at about three times a PNG's cost, so it has its own lower pixel
#: cap (:data:`MAX_DECODE_PX_WEBP`). "JPEG" covers MPO too (a phone JPEG with
#: a second picture): Pillow's JPEG opener returns it, and "MPO" has no
#: opener of its own to list.
SCAN_IMAGE_FORMATS = ("JPEG", "PNG", "TIFF", "WEBP", "BMP")
_UNSUPPORTED_IMAGE_MESSAGE = (
    "This scan's image format ({format}) cannot be processed safely. "
    "Save it as a PDF, JPEG, PNG or TIFF and upload it again."
)


class ScanUnsupportedFormatError(ScanRejectedError):
    """A scan image in a format outside :data:`SCAN_IMAGE_FORMATS`."""


#: #256 review: Pillow's ``DecompressionBombWarning`` fires from 89.5 Mpx
#: (``MAX_IMAGE_PIXELS``), below :data:`MAX_DECODE_PX_GREY`, so it would warn
#: on every grey scan the cap admits on purpose. Every image this module
#: opens is capped by :func:`decode_pixel_cap` from its header before a pixel
#: is decoded, which makes the warning redundant, so it is ignored
#: process-wide, by design. The app's other ``Image.open`` calls read its own
#: rendered pages and crops (at most :data:`MAX_PAGE_PX`, under the
#: threshold) or, in the avatar route, open and ``verify()`` without
#: decoding. Pillow's bomb ERROR, at twice ``MAX_IMAGE_PIXELS`` and above
#: every cap, is left alone, as is ``MAX_IMAGE_PIXELS`` itself; it is what
#: guards the avatar route.
_IGNORE_CAPPED_BOMB_WARNING = ("ignore", None, Image.DecompressionBombWarning, None, 0)


def _ignore_capped_bomb_warning() -> None:
    """Make :data:`_IGNORE_CAPPED_BOMB_WARNING` the filter that decides this warning.

    Called at import and again before every open: a ``catch_warnings``
    block elsewhere (pytest wraps collection, where this module is
    imported, in one) restores the filter list it saved and drops a filter
    added inside it, and a broader filter added later (``simplefilter``,
    ``-W``) sits in front of it. So unless the first filter that can apply
    to this category is already this one, it is (re-)inserted at the
    front. Only ever this one entry is removed and inserted, never the list
    replaced, so two threads racing here can at worst add it twice --
    unlike ``catch_warnings``, which swaps the whole list and can clobber
    another thread's filters.
    """
    for entry in warnings.filters:
        if issubclass(Image.DecompressionBombWarning, entry[2]):
            if entry == _IGNORE_CAPPED_BOMB_WARNING:
                return
            break
    warnings.filterwarnings("ignore", category=Image.DecompressionBombWarning)


_ignore_capped_bomb_warning()


def _pillow_claims(image_format: str, prefix: bytes) -> bool:
    """Whether Pillow's ``image_format`` plugin would try to open bytes starting ``prefix``."""
    accept = Image.OPEN[image_format][1]
    if accept is None:
        return False
    try:
        return bool(accept(prefix))
    except Exception:
        return False


def open_scan_image(source: bytes | IO[bytes]) -> ImageFile.ImageFile:
    """``Image.open`` for a scan image: allowlisted formats only, and no bomb warning.

    The one opener for upload (:func:`check_scan_bytes`), extraction, the
    review crop and the paper preview. ``source`` is the image's bytes or an
    open binary file, never a path: opened by name, Pillow memory-maps an
    uncompressed single-strip image, and for a TIFF tagged with orientation
    5-8 it maps the stored rows into the already turned size, so the page
    came back scrambled (#275).

    Bytes that one of Pillow's other plugins would claim by their prefix
    (an ICO, an ICNS, a GIF, ...) raise
    :class:`ScanUnsupportedFormatError` naming the format, found from those
    16 bytes without running that plugin's opener -- the step that decodes.
    Everything else is opened with ``formats=SCAN_IMAGE_FORMATS``, so no
    other plugin ever runs; bytes none of them recognise raise
    ``PIL.UnidentifiedImageError`` exactly as ``Image.open`` does.

    Pillow's ``DecompressionBombWarning`` is ignored process-wide (see
    :data:`_IGNORE_CAPPED_BOMB_WARNING`; re-asserted here before the open):
    every caller applies :func:`decode_pixel_cap` to the header's size
    before a pixel is decoded, and the warning's threshold (89.5 Mpx) is
    below :data:`MAX_DECODE_PX_GREY`. Its error, above every cap, stands.
    """
    if isinstance(source, bytes):
        source = io.BytesIO(source)
    Image.init()
    position = source.tell()
    prefix = source.read(16)
    source.seek(position)
    claimed = [image_format for image_format in Image.ID if _pillow_claims(image_format, prefix)]
    if claimed and not any(image_format in SCAN_IMAGE_FORMATS for image_format in claimed):
        raise ScanUnsupportedFormatError(
            _UNSUPPORTED_IMAGE_MESSAGE.format(format=claimed[0]), reason="format_not_allowed"
        )
    _ignore_capped_bomb_warning()
    opened = Image.open(source, formats=SCAN_IMAGE_FORMATS)
    # Task 11 review: Pillow names a 16-bit colour image by its 8-bit mode
    # ("RGB", "RGBA"), so a caller judging the mode alone would allow it the
    # 8-bit ceiling. Its depth is known here, from the header, before any
    # pixel is decoded, and every image path opens through here.
    sample_bits = _image_sample_bits(opened)
    if sample_bits > 8:
        cap = decode_pixel_cap(opened.mode, opened.format, sample_bits=sample_bits)
        if opened.width * opened.height > cap:
            mode, image_format = opened.mode, opened.format
            opened.close()
            _refuse_over_cap(cap, mode, image_format)
    return opened
