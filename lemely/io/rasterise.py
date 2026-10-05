"""Rasterise a scanned exam PDF to per-page PNG images for vision extraction (I1).

Feeds :class:`~lemely.io.answer_extraction.GeminiAnswerExtractor` one image part
per page instead of the whole PDF, which is what makes Gemini's bounding-box
output (``source_box`` on :class:`~lemely.core.schemas.ExtractedAnswer``)
possible at all — bounding boxes are documented for image inputs only, not PDF
inputs (ai.google.dev/gemini-api/docs/image-understanding, re-verified
2026-09-02).

Uses the same renderer as ``scripts/rasterise_handwritten_fixtures.py``
(pypdfium2, ``page.render(scale=dpi/72)``) but at 200 DPI rather than 150 —
200 DPI is Google's own recommendation for PDF/image inputs and keeps each
page under the 2,240-token "ultra" tokenisation tier the plan is pinned
against; 150 DPI is that script's *own* concern (matching the synthetic
corpus's render scale for #59) and is unrelated to this budget. Pages are
returned as in-memory PNG bytes rather than written back out to a flattened
PDF — I1's extraction call sends one image part per page directly.

Spec 2026-09-26 §6: every page is planned by `lemely.io.scan_limits` before
any page is rendered — over-long documents and over-size pages are refused,
pages within the band render at a lower DPI, recorded on `RasterisedPage.dpi`,
and a scan whose pages sum past `MAX_SCAN_TOTAL_PX` renders every page at one
uniformly lower DPI (or is refused below `MIN_EXTRACTION_DPI`).
"""

from __future__ import annotations

import contextlib
import io
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import pypdfium2 as pdfium
import structlog

from lemely.io.scan_limits import (
    EXTRACTION_DPI,
    GREY_CEILING_MODES,
    PDF_MAGIC,
    ScanRejectedError,
    ScanTooLargeError,
    canonical_pdf_bytes,
    check_pdf_content_bytes,
    looks_like_pdf,
    open_scan_image,
    plan_image,
    plan_pdf_pages,
)
from lemely.runtime import sandbox
from lemely.runtime.errors import LemelyError

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator
    from pathlib import Path

    from PIL.Image import Image as PILImage

log = structlog.get_logger(__name__)

__all__ = [
    "EXTRACTION_DPI",
    "PDF_MAGIC",
    "RENDER_FAILED_MESSAGE",
    "SCAN_PAGES_TARGET",
    "RasterisedPage",
    "ScanRejectedError",
    "ScanRenderFailedError",
    "ScanTooLargeError",
    "iter_scan_pages",
    "looks_like_pdf",
    "rasterise_pdf_to_pages",
    "rasterise_scan_to_pages",
    "single_channel_or_rgb",
]


#: What a user is told when the extraction worker could not render a scan.
#: The same words the preview and crop routes answer (``SANDBOX_FAILED_DETAIL``).
RENDER_FAILED_MESSAGE = "Could not render this scan"


class ScanRenderFailedError(LemelyError):
    """The extraction worker produced no pages; ``str()`` is :data:`RENDER_FAILED_MESSAGE`.

    Both grading flows show an extraction error's ``str()`` to the user (the
    student's SSE error frame, the teacher's failed row), so the worker's
    own failure -- an exception's repr, a library message -- travels only
    as ``__cause__`` and on the ``scan_render_failed`` log line.

    Pickles: ``BaseException.__reduce__`` rebuilds it from its ``args`` (the
    message), which ``__init__`` accepts and ignores, so it can cross a
    worker's pipe as every other ``LemelyError`` does (final review R3).
    """

    def __init__(self, *_: object) -> None:
        super().__init__(RENDER_FAILED_MESSAGE)


@dataclass(frozen=True)
class RasterisedPage:
    """One rendered page.

    0-based ``index`` matches the image-part order sent to Gemini, which is
    also the ``page`` index Gemini must echo back in
    ``ExtractedAnswer.source_box`` (see ``build_extractor_user_prompt``).
    ``dpi`` is the DPI the page was rendered at: :data:`EXTRACTION_DPI`
    unless the geometry plan lowered it (spec 2026-09-26 §6); nominal for an
    image upload, which has no DPI of its own.
    """

    index: int
    width: int
    height: int
    png_bytes: bytes
    dpi: float = EXTRACTION_DPI


def _iter_pdf_pages(pdf_path: Path, *, dpi: float) -> Iterator[RasterisedPage]:
    """Render the pages of *pdf_path* one at a time, each yielded as it is made.

    The body of :func:`rasterise_pdf_to_pages`, as a generator: in the
    extraction worker (#260) each page is sent to the parent before the next
    is rendered, so the child never holds every page's PNG at once. Closing
    the generator early closes pdfium's document. Refuses as
    :func:`rasterise_pdf_to_pages` does; a PDF with no pages raises
    ``ValueError`` from :func:`~lemely.io.scan_limits.canonical_pdf_bytes`
    and otherwise yields nothing.
    """
    # The stored file's bytes are released as soon as the rewrite exists
    # (the call holds the only reference), so at most the file and its
    # rewrite are held at once; pdfium then keeps only the rewrite.
    yield from _iter_canonical_pages(canonical_pdf_bytes(pdf_path.read_bytes()), dpi=dpi)


def _iter_canonical_pages(canonical: bytes, *, dpi: float) -> Iterator[RasterisedPage]:
    """:func:`_iter_pdf_pages` once the rewrite exists: plan, check, render."""
    # `canonical_pdf_bytes` is the only sanctioned source of pdfium input.
    pdf = pdfium.PdfDocument(canonical)
    try:
        # #274: pdfium draws no form field's value until the document's forms
        # are initialised, so a student's typed answer -- ink the teacher's
        # MuPDF preview shows -- reached the model as a blank box. This parses
        # the rewrite's /AcroForm, which MuPDF copies unwalked; it is bounded
        # by the object-stream bound and the upload cap, and runs in the
        # extraction worker (#260) with the rest of the render. pdfium can
        # refuse the form environment; the scan is then rendered without its
        # field values rather than not at all, and the refusal is logged.
        try:
            pdf.init_forms()
        except pdfium.PdfiumError as exc:
            log.warning("scan_forms_not_drawn", error=str(exc))
        # Planning reads the page count and page sizes only (no page is
        # loaded), so the page cap applies before the content walk below
        # visits every page (final review M1).
        plans = plan_pdf_pages(pdf, dpi=dpi)
        # Task 11b: an old stored upload can pre-date the upload-time check,
        # and pypdfium2 parses a page's whole content stream on render --
        # measured at 2.2 GB for a 218 KB bomb. Refuse from the raw streams
        # before any render. The walk reads with MuPDF but this renders with
        # pdfium, so it is given pdfium's page count (Task 9b). Over the same
        # canonical bytes the counts should always agree (Task 9c); the
        # comparison stays as a guard.
        check_pdf_content_bytes(canonical, pdfium_pages=len(pdf))
        for plan in plans:
            # Final review N1: a loaded page keeps its decoded images alive
            # until it is closed, and `pdf.close()` alone would hold every
            # page's at once (1037 MB peak RSS on a 1.13 MB 40-page scan,
            # 553 MB closing per page). Close the page and its bitmap as soon
            # as the RGB copy exists; `.convert` copies, so nothing the PNG
            # encode below reads still points into pdfium's buffer.
            page = pdf[plan.index]
            try:
                # pypdfium2's scale is in units of 72dpi-points.
                # `may_draw_forms` is pypdfium2's default (5.11); spelled out
                # so the form values above survive a change of default.
                bitmap = page.render(scale=plan.dpi / 72.0, may_draw_forms=True)
                try:
                    pil_image = bitmap.to_pil().convert("RGB")
                finally:
                    bitmap.close()
            finally:
                page.close()
            rasterised = _png_page(pil_image, index=plan.index, dpi=plan.dpi)
            # Dropped before the yield: a suspended generator would otherwise
            # keep this page's full-size RGB copy alive through the next render.
            del pil_image
            yield rasterised
            # And the page itself once it is handed on: the child sends it
            # and drops its own reference, so nothing holds it through the
            # next render.
            del rasterised
    finally:
        pdf.close()


def _png_page(image: PILImage, *, index: int, dpi: float = EXTRACTION_DPI) -> RasterisedPage:
    """``image`` encoded as PNG, as the :class:`RasterisedPage` at ``index``."""
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return RasterisedPage(
        index=index, width=image.width, height=image.height, png_bytes=buf.getvalue(), dpi=dpi
    )


def rasterise_pdf_to_pages(pdf_path: Path, *, dpi: float = EXTRACTION_DPI) -> list[RasterisedPage]:
    """Render every page of *pdf_path* to a PNG image at *dpi* (or the planned lower DPI).

    Runs in the calling process; extraction calls
    :func:`rasterise_scan_to_pages`, which renders in the extraction worker.

    Raises :class:`ScanTooLargeError` before any render when the document
    has more than ``MAX_SCAN_PAGES`` pages or a page beyond
    ``MAX_DECODE_PX``, or pages that fit ``MAX_SCAN_TOTAL_PX`` only below
    ``MIN_EXTRACTION_DPI`` (a scan over that total but above the floor is
    rendered at one uniformly lower DPI instead, recorded on each page's
    ``dpi``), or a page whose content streams decode past
    ``MAX_PAGE_CONTENT_BYTES`` (``ScanTooLargeError``), or a content encoding
    that cannot be bounded (``ScanUnsupportedEncodingError``), and
    :class:`ValueError` if the PDF has no pages — an empty extraction call
    would silently carry no evidence at all rather than fail loudly.

    Task 9c: pdfium never opens the stored file. It renders MuPDF's rewrite
    of it (:func:`~lemely.io.scan_limits.canonical_pdf_bytes`), and those
    same bytes are what the content check measures, so a file the two
    readers would repair differently cannot show pdfium an object MuPDF did
    not check. A file MuPDF cannot open or rewrite raises
    :class:`ScanRejectedError`.
    """
    pages = list(_iter_pdf_pages(pdf_path, dpi=dpi))
    if not pages:
        raise ValueError(f"{pdf_path} produced no pages")
    return pages


def _looks_like_pdf(path: Path) -> bool:
    """Sniff the magic bytes rather than trust the file extension.

    A client-supplied filename is not authoritative (see
    ``lemely.web.upload_utils.safe_upload_name``). Delegates to
    :func:`looks_like_pdf` so this module and the crop route cannot disagree
    about what a PDF looks like.
    """
    with path.open("rb") as handle:
        header = handle.read(len(PDF_MAGIC))
    return looks_like_pdf(header)


#: Single-channel modes that go to "L" (one byte per pixel) rather than to a
#: full-size RGB: Pillow cannot ``reduce`` "1" or "I;16*", and resamples "1"
#: by nearest neighbour. Derived from ``scan_limits.GREY_CEILING_MODES``, so
#: every mode given the grey ceiling lands on "L" and the re-plan after the
#: conversion can never refuse what the header check admitted. "I" and "F"
#: are added, one channel instead of three.
_ONE_CHANNEL_MODES = GREY_CEILING_MODES | {"I", "F"}

#: Single-channel modes whose samples are wider than a byte. Pillow's own
#: conversion to "L" CLIPS these to 0-255 rather than scaling them (final
#: review, Important 2: ink at 5000 on paper at 60000 became an all-white
#: page), so :func:`_wide_grey_to_l` scales them instead. Pillow opens a
#: 16-bit PNG or TIFF as "I;16"; a 32-bit TIFF opens as "I" or "F". None of
#: these modes says how many bits the samples really use, so the full scale
#: is inferred from the image's maximum (:func:`_full_scale`, #275).
_WIDE_GREY_MODES = frozenset({"I;16", "I;16L", "I;16B", "I;16N", "I", "F"})

#: The sample depths a 16-bit container is taken to hold (#275): a scanner
#: writing 8-, 10-, 12- or 14-bit samples into 16 bits leaves the top bits
#: unused, and scaled from 65535 its white paper came out near black.
_SIXTEEN_BIT_CONTAINER_SCALES = tuple(2**bits - 1 for bits in (8, 10, 12, 14, 16))

#: The same for a 32-bit "I" image, or an "F" image holding integers. "I"
#: samples are signed, so the widest container is 2**31 - 1.
_THIRTY_TWO_BIT_CONTAINER_SCALES = _SIXTEEN_BIT_CONTAINER_SCALES + tuple(
    2**bits - 1 for bits in (20, 24, 31)
)

#: An "F" page whose maximum is below this is normalised (0-1), with at most
#: a scanner's overshoot past 1.0; its maximum, or 1.0, maps to white.
_NORMALISED_FLOAT_CEILING = 2.0

#: Pixels converted per strip by :func:`_wide_grey_to_l`: its working copies
#: ("I" is four bytes a pixel) stay at a few MB whatever the page's size.
_WIDE_STRIP_PX = 1 << 20


#: The wide modes Pillow's ``getextrema`` reads directly; it refuses the
#: byte-ordered "I;16" variants (a big-endian 16-bit TIFF opens as "I;16B").
_EXTREMA_MODES = frozenset({"I;16", "I", "F"})


def _row_strips(image: PILImage) -> Iterator[tuple[int, PILImage]]:
    """``image`` in horizontal strips of about :data:`_WIDE_STRIP_PX` pixels.

    Each is ``(top, strip)``, a copy in ``image``'s own mode that keeps its
    palette and ``info`` (a transparency key among them), so the working
    copies stay at a few MB whatever the page's size.
    """
    width, height = image.size
    rows = max(1, _WIDE_STRIP_PX // max(1, width))
    for top in range(0, height, rows):
        yield top, image.crop((0, top, width, min(height, top + rows)))


def _wide_strips(image: PILImage) -> Iterator[tuple[int, PILImage]]:
    """:func:`_row_strips`, each strip in "I" or "F".

    The wide modes ``point`` scales and ``getextrema`` reads.
    """
    for top, strip in _row_strips(image):
        yield top, strip if strip.mode in ("I", "F") else strip.convert("I")


def _extrema(image: PILImage) -> tuple[float, float]:
    """``image``'s smallest and largest sample.

    One C-level pass, with no copy, for the modes Pillow reads directly
    (:data:`_EXTREMA_MODES`); strip by strip for the others. Of the finite
    samples only: an infinite sample in an "F" page (Pillow's own extrema
    include it), or a NaN first sample (which makes them NaN), would
    otherwise set the full scale and turn every other sample black, so such
    a page is read again (:func:`_finite_extrema`). A page with no finite
    sample reads as flat. Infinite samples themselves still scale to white
    (or black, negative), and a NaN sample to black.
    """
    if image.mode in _EXTREMA_MODES:
        lo, hi = cast("tuple[float, float]", image.getextrema())
        if math.isfinite(lo) and math.isfinite(hi):
            return lo, hi
        return _finite_extrema(image)
    lows, highs = zip(
        *(cast("tuple[float, float]", strip.getextrema()) for _, strip in _wide_strips(image)),
        strict=True,
    )
    return min(lows), max(highs)


#: The largest finite float32, which an "F" sample cannot pass.
_FLOAT32_MAX = 3.4028234663852886e38


def _finite_extrema(image: PILImage) -> tuple[float, float]:
    """The smallest and largest finite sample of an "F" ``image``, strip by strip.

    In Pillow alone: numpy's import starts OpenBLAS threads that the
    extraction worker's address-space limit refuses. Per strip, ``a + a * 0``
    is ``a`` where finite and NaN elsewhere; ``ImageMath``'s ``min`` and
    ``max`` keep their second operand where the first is NaN, so the NaNs
    become :data:`_FLOAT32_MAX` for the minimum and its negative for the
    maximum, where they cannot win. (Pillow's ``getextrema`` cannot skip a
    NaN itself: a NaN first sample makes the result NaN.) ``(0.0, 0.0)`` --
    flat, so white -- when no sample is finite.
    """
    from PIL import ImageMath

    lo, hi = math.inf, -math.inf
    for _, strip in _wide_strips(image):
        finite = ImageMath.lambda_eval(lambda args: args["a"] + args["a"] * 0.0, a=strip)
        low = ImageMath.lambda_eval(lambda args: args["min"](args["f"], _FLOAT32_MAX), f=finite)
        high = ImageMath.lambda_eval(lambda args: args["max"](args["f"], -_FLOAT32_MAX), f=finite)
        lo = min(lo, cast("tuple[float, float]", low.getextrema())[0])
        hi = max(hi, cast("tuple[float, float]", high.getextrema())[1])
    return (lo, hi) if lo <= hi else (0.0, 0.0)


def _full_scale(image: PILImage) -> float | None:
    """The sample value that maps to white for ``image`` (a :data:`_WIDE_GREY_MODES` mode).

    #275: inferred from the image's largest finite sample, ``hi``
    (:func:`_extrema`): the smallest usual container depth
    (``2**bits - 1``) that holds it -- 8 to 16 bits for an "I;16*" image,
    8 to 31 bits for "I", and the same for "F" whose samples reach 2.0
    (integers stored as floats). An "F" image whose maximum is below 2.0 is
    normalised: its full scale is 1.0, or its maximum when a sample
    overshoots 1.0 (one 1.02 pixel used to turn the page black). ``None``
    for a flat image (``lo == hi``), which says nothing about its depth:
    blank paper. A maximum past every listed depth (an "F" image only) is
    its own full scale.
    """
    lo, hi = _extrema(image)
    if lo == hi:
        return None
    if image.mode == "F" and hi < _NORMALISED_FLOAT_CEILING:
        return max(1.0, hi)
    scales = (
        _SIXTEEN_BIT_CONTAINER_SCALES
        if image.mode.startswith("I;16")
        else _THIRTY_TWO_BIT_CONTAINER_SCALES
    )
    return next((scale for scale in scales if scale >= hi), hi)


def _wide_grey_to_l(image: PILImage, full_scale: float | None) -> PILImage:
    """``image`` (a :data:`_WIDE_GREY_MODES` mode) as "L", ``full_scale`` mapped to white.

    ``full_scale`` is :func:`_full_scale` of ``image``, or of the whole
    image ``image`` was cut from. ``None`` (a flat image) gives white.
    Otherwise in strips (:func:`_wide_strips`), so
    the only full-size allocation is the "L" result: the peak is what
    Pillow's own clipping conversion costs, after one pass for the extrema
    (:func:`_extrema`). Each strip is scaled -- linearly, so Pillow's
    scale-and-offset path applies -- and only then converted to "L", which
    clips nothing left in range: no sample passes the full scale. The half
    added rounds, since both conversions to "L" truncate (0.05 of a
    normalised float is 12.75, so 13).
    """
    from PIL import Image

    if full_scale is None:
        return Image.new("L", image.size, 255)
    factor = 255 / full_scale
    result = Image.new("L", image.size)
    for top, strip in _wide_strips(image):
        scaled = strip.point(lambda value: value * factor + 0.5)
        result.paste(scaled.convert("L"), (0, top))
    return result


#: Modes whose pixels carry an alpha band.
_ALPHA_MODES = frozenset({"RGBA", "LA", "PA"})

#: The premultiplied alpha modes, and the plain mode each is taken to first.
#: Pillow opens no file in these (a TIFF with associated alpha decodes to
#: "RGBA"); handled so no caller can pass one through with its alpha lost.
_PREMULTIPLIED_MODES = {"RGBa": "RGBA", "La": "LA"}


def _has_transparency(image: PILImage) -> bool:
    """Whether ``image`` has an alpha band or a transparency key (``info["transparency"]``)."""
    return image.mode in _ALPHA_MODES or "transparency" in image.info


def _opacity(strip: PILImage) -> PILImage:
    """``strip``'s opacity as "L": its alpha band, or its transparency key made one.

    A key is turned into alpha by Pillow's own conversion, which knows how
    each mode stores it (a palette's per-index alphas or index, a grey
    sample, an RGB triple), except for a wide grey key (a 16-bit PNG's
    ``tRNS``): Pillow compares that after clipping the samples to 8 bits, so
    a key above 255 never matches, and it is compared here at full width.
    """
    from PIL import ImageMath

    if strip.mode in _WIDE_GREY_MODES:
        key = strip.info["transparency"]
        wide = strip if strip.mode in ("I", "F") else strip.convert("I")
        opaque = cast(
            "PILImage",
            ImageMath.lambda_eval(lambda args: args["notequal"](args["a"], key) * 255, a=wide),
        )
        return opaque.convert("L")
    if strip.mode not in _ALPHA_MODES:
        strip = strip.convert("RGBA" if strip.mode in ("RGB", "P") else "LA")
    return strip.getchannel(len(strip.getbands()) - 1)


def _onto_white(opaque: PILImage, source: PILImage, *, in_place: bool) -> PILImage:
    """``opaque`` (``source`` in "L" or "RGB") composited onto white by ``source``'s opacity.

    Strip by strip (:func:`_row_strips`), so besides ``opaque`` only a few
    MB are held. ``opaque`` is written in place when it is a new image, and
    when it is ``source`` itself (an "L" or "RGB" image with a transparency
    key) only if ``in_place``: otherwise ``source`` belongs to the caller
    and is copied first. In place, each strip's opacity is read before its
    rows are written.
    """
    from PIL import Image

    result = opaque.copy() if opaque is source and not in_place else opaque
    white: int | tuple[int, int, int] = 255 if result.mode == "L" else (255, 255, 255)
    for top, strip in _row_strips(source):
        box = (0, top, strip.width, top + strip.height)
        backdrop = Image.new(result.mode, strip.size, white)
        backdrop.paste(result.crop(box), (0, 0), _opacity(strip))
        result.paste(backdrop, box[:2])
    result.info.pop("transparency", None)
    return result


def _opaque_single_channel_or_rgb(image: PILImage, scale_of: PILImage | None) -> PILImage:
    """:func:`single_channel_or_rgb` before any compositing: alpha and keys ignored."""
    if image.mode in ("L", "RGB"):
        return image
    if image.mode in _WIDE_GREY_MODES:
        source = scale_of if scale_of is not None and scale_of.mode == image.mode else image
        return _wide_grey_to_l(image, _full_scale(source))
    if image.mode in _ONE_CHANNEL_MODES or image.mode == "LA":
        return image.convert("L")
    return image.convert("RGB")


def single_channel_or_rgb(
    image: PILImage, *, scale_of: PILImage | None = None, in_place: bool = False
) -> PILImage:
    """``image`` in a mode Pillow can ``reduce`` and resample well: "L" or "RGB".

    #256: a bilevel ("1") or other single-channel scan is taken to "L" (the
    same size as "1": Pillow holds both at one byte per pixel), never
    straight to RGB at full size; a palette or other multi-channel mode goes
    to RGB, which is why :func:`~lemely.io.scan_limits.decode_pixel_cap`
    gives it the colour ceiling. "L" and "RGB" are returned as they are. A
    16- or 32-bit single-channel image is scaled to 8 bits, not clipped
    (:func:`_wide_grey_to_l`). Extraction, the review crop and the paper
    preview all convert through here, so the model and the teacher see the
    same tones.

    An image with alpha ("RGBA", "LA", "PA") or a transparency key is
    composited onto white (:func:`_onto_white`), grey ("LA", a keyed grey)
    staying "L". Pillow's own conversions drop the alpha and keep the colour
    under it, and a drawing or tablet app exports its transparent canvas as
    black under alpha 0: the model read an all-black page, and the crop
    showed one, while the student's ink was there (final review R3, I2).

    ``scale_of``: for a region cut from a larger wide-grey image, that
    whole image (in the same mode). The full scale is inferred from it
    rather than from the region (#275), so a crop has extraction's tones: a
    region that is all ink is flat, and inferred alone it would be white.

    ``in_place``: the caller is done with ``image``. An "L" or "RGB" image
    with a transparency key, the one case that would otherwise be copied
    before it is composited, is then written in place: a 40 Mpx keyed RGB
    page's preview measured 426 MiB ``VmData`` with the copy (final fix B).
    Every other mode converts to a new image either way.
    """
    if image.mode in _PREMULTIPLIED_MODES:
        image = image.convert(_PREMULTIPLIED_MODES[image.mode])
    opaque = _opaque_single_channel_or_rgb(image, scale_of)
    if not _has_transparency(image):
        return opaque
    return _onto_white(opaque, image, in_place=in_place)


def _rasterise_single_image(image_path: Path) -> list[RasterisedPage]:
    """Wrap a plain (non-PDF) scan upload as a single-page result.

    A raw ``image/*`` upload is already a raster image — it is loaded and
    re-encoded as PNG so :class:`RasterisedPage` always carries the same
    format regardless of scan type. Spec 2026-09-26 §6: an image within the
    band is reduced to fit ``MAX_PAGE_PX`` — a JPEG (which includes MPO)
    through Pillow's native reduced-scale decode first, anything else by an
    integer ``reduce`` after decoding — and one beyond ``decode_pixel_cap`` for
    its mode (40 Mpx colour, 160 Mpx bilevel/greyscale, #256) is refused from
    its header, before any pixel is decoded. The EXIF orientation flag is
    applied (#255), so the page, and every source_box read from it, is
    upright. The reduce happens before the RGB conversion (#256), so a large
    bilevel or greyscale scan is never expanded to three channels at full
    size.
    """
    from PIL import Image, ImageOps, JpegImagePlugin

    try:
        # #256 review: allowlisted formats only (no plugin decodes in the open).
        # #275: from a file object, never by name. Opened by name, Pillow
        # memory-maps an uncompressed single-strip image, and for a TIFF whose
        # orientation tag is 5-8 it maps the stored rows into the already
        # swapped (upright) size: the page came back scrambled. A file object
        # takes the ordinary decode, which turns a TIFF upright at load.
        with image_path.open("rb") as handle, open_scan_image(handle) as opened:
            # The format too: a WebP has its own, lower cap (#256 review round 2).
            image_format = opened.format
            factor = plan_image(opened.width, opened.height, opened.mode, image_format)
            if factor > 1 and isinstance(opened, JpegImagePlugin.JpegImageFile):
                opened.draft(None, (opened.width // factor, opened.height // factor))
            # #255: a phone stores a portrait photo as a landscape sensor frame
            # plus an EXIF orientation flag. Apply it, so the model reads the
            # page upright and every `source_box` from here on is in the
            # upright frame -- the crop route (`scan_render.crop_image_scan`)
            # transposes the same way before cutting. `draft()` above has
            # already picked the reduced decode, so this transposes at most
            # the reduced size; `in_place` avoids a second full-size copy when
            # there is no flag.
            ImageOps.exif_transpose(opened, in_place=True)
            # #256: into a mode `reduce` takes ("L" or "RGB") WITHOUT expanding
            # a one-channel scan to RGB at full size; the RGB conversion waits
            # until after the reduce below. The transpose above is untouched:
            # pixel caps are areas, which a transpose does not change.
            # `in_place`: nothing reads `opened` afterwards.
            pil_image = single_channel_or_rgb(opened, in_place=True)
            # Decoded here, while the file is open: an "L" or "RGB" image
            # comes back as `opened` itself, and the reduce below runs after
            # the `with` has closed the file. `exif_transpose` happens to load
            # it already (measured, Pillow 12.2, with or without a flag); this
            # keeps that from being load-bearing.
            pil_image.load()
    except Image.DecompressionBombError as exc:
        raise ScanTooLargeError(
            "image declares too many pixels to decode", reason="image_px"
        ) from exc
    # Re-planned against the post-open dimensions: a JPEG's `.draft()` above picks
    # the nearest supported DCT scale, not exactly `factor`, so the image may still
    # need an extra integer `.reduce()` here to land under MAX_PAGE_PX. Against the
    # converted mode, whose ceiling is never lower than the header's, and the
    # header's format (a converted copy has none of its own).
    factor = plan_image(pil_image.width, pil_image.height, pil_image.mode, image_format)
    if factor > 1:
        pil_image = pil_image.reduce(factor)
    pil_image = pil_image.convert("RGB") if pil_image.mode != "RGB" else pil_image
    return [_png_page(pil_image, index=0)]


#: The child-side function :func:`rasterise_scan_to_pages` streams from the
#: extraction worker; a module attribute, read per call, so a test can name
#: another target.
SCAN_PAGES_TARGET = "lemely.io.rasterise.iter_scan_pages"


def iter_scan_pages(scan_path: Path, dpi: float) -> Iterator[RasterisedPage]:
    """The pages of a scan, one at a time: what the extraction worker's child runs.

    Dispatches on the file's actual content, as :func:`rasterise_scan_to_pages`
    documents. ``dpi`` is positional because the worker passes arguments so.
    A PDF neither reader finds a page in yields nothing (the caller raises
    the ``ValueError``): only that ``ValueError``, from the rewrite, before
    any page is rendered, is caught, so a failure part-way through can never
    pass for a shorter scan.
    """
    if not _looks_like_pdf(scan_path):
        yield from _rasterise_single_image(scan_path)
        return
    try:
        canonical = canonical_pdf_bytes(scan_path.read_bytes())
    except ValueError:  # "the PDF has no pages"
        return
    yield from _iter_canonical_pages(canonical, dpi=dpi)


def rasterise_scan_to_pages(
    scan_path: Path, *, dpi: float = EXTRACTION_DPI
) -> list[RasterisedPage]:
    """Rasterise a scanned exam paper to per-page PNG images, in the extraction worker.

    Dispatches on the file's actual content (not its extension or a caller's
    claimed content type): a PDF is rendered page-by-page as
    :func:`rasterise_pdf_to_pages` renders it; anything else is treated as a
    single already-rasterised image (``image/*`` uploads are accepted
    alongside PDFs — see ``lemely.web.routers.teacher``) and wrapped as one
    :class:`RasterisedPage`.

    #260: the decoding runs in :data:`~lemely.runtime.sandbox.EXTRACTION_WORKER`,
    a child bounded in memory and killed past
    ``sandbox_settings().extraction_timeout_seconds``. The child streams the
    pages (:func:`iter_scan_pages`) and lets go of each once it is sent, so
    besides the page it is rendering it holds at most the one being sent;
    this process collects them all. A scan refusal arrives as itself. Any
    other worker failure is logged (``scan_render_failed``, with its
    ``reason`` and text) and raised as :class:`ScanRenderFailedError`, whose
    message is the fixed :data:`RENDER_FAILED_MESSAGE`: both grading flows
    show the error's text to the user. Raises :class:`ValueError` when the
    scan produced no pages.
    """
    # `stream` is a generator function, so its result has `close()`.
    stream = cast(
        "Generator[RasterisedPage]",
        sandbox.EXTRACTION_WORKER.stream(
            SCAN_PAGES_TARGET,
            scan_path,
            dpi,
            timeout=sandbox.sandbox_settings().extraction_timeout_seconds,
            item_type=RasterisedPage,
        ),
    )
    # Closed on every exit: an abandoned stream holds the worker until it is
    # garbage-collected.
    try:
        with contextlib.closing(stream):
            pages = list(stream)
    except sandbox.SandboxFailure as exc:
        log.warning("scan_render_failed", reason=exc.reason, error=str(exc))
        raise ScanRenderFailedError from exc
    if not pages:
        raise ValueError(f"{scan_path} produced no pages")
    return pages
