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
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import pypdfium2 as pdfium

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

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator
    from pathlib import Path

    from PIL.Image import Image as PILImage

__all__ = [
    "EXTRACTION_DPI",
    "PDF_MAGIC",
    "SCAN_PAGES_TARGET",
    "RasterisedPage",
    "ScanRejectedError",
    "ScanTooLargeError",
    "iter_scan_pages",
    "looks_like_pdf",
    "rasterise_pdf_to_pages",
    "rasterise_scan_to_pages",
    "single_channel_or_rgb",
]


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
                bitmap = page.render(scale=plan.dpi / 72.0)
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
#: 16-bit PNG or TIFF as "I;16"; a 32-bit TIFF opens as "I" or "F", whose
#: range the mode does not say -- they are read as 16-bit samples too, the
#: range Pillow itself uses "I" for, and anything past 65535 is white.
_WIDE_GREY_MODES = frozenset({"I;16", "I;16L", "I;16B", "I;16N", "I", "F"})

#: 65535 -> 255: the 16-bit range onto the 8-bit one.
_SIXTEEN_TO_EIGHT_BITS = 255 / 65535

#: Pixels converted per strip by :func:`_wide_grey_to_l`: its working copies
#: ("I" is four bytes a pixel) stay at a few MB whatever the page's size.
_WIDE_STRIP_PX = 1 << 20


def _wide_grey_to_l(image: PILImage) -> PILImage:
    """``image`` (a :data:`_WIDE_GREY_MODES` mode) as "L", scaled from 0-65535.

    In strips, so the only full-size allocation is the "L" result: the peak
    is what Pillow's own clipping conversion costs. Each strip goes to "I"
    (the one wide mode besides "F" that ``point`` scales), is scaled, and
    only then converted to "L", which clips nothing left in range.
    """
    from PIL import Image

    width, height = image.size
    result = Image.new("L", image.size)
    rows = max(1, _WIDE_STRIP_PX // max(1, width))
    for top in range(0, height, rows):
        strip = image.crop((0, top, width, min(height, top + rows)))
        if strip.mode not in ("I", "F"):
            strip = strip.convert("I")
        scaled = strip.point(lambda value: value * _SIXTEEN_TO_EIGHT_BITS)
        result.paste(scaled.convert("L"), (0, top))
    return result


def single_channel_or_rgb(image: PILImage) -> PILImage:
    """``image`` in a mode Pillow can ``reduce`` and resample well: "L" or "RGB".

    #256: a bilevel ("1") or other single-channel scan is taken to "L" (the
    same size as "1": Pillow holds both at one byte per pixel), never
    straight to RGB at full size; a palette or other multi-channel mode goes
    to RGB, which is why :func:`~lemely.io.scan_limits.decode_pixel_cap`
    gives it the colour ceiling. "L" and "RGB" are returned as they are. A
    16- or 32-bit single-channel image is scaled to 8 bits, not clipped
    (:func:`_wide_grey_to_l`). Extraction and the review crop route both
    convert through here, so the model and the teacher see the same tones.
    """
    if image.mode in ("L", "RGB"):
        return image
    if image.mode in _WIDE_GREY_MODES:
        return _wide_grey_to_l(image)
    if image.mode in _ONE_CHANNEL_MODES:
        return image.convert("L")
    return image.convert("RGB")


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
        with open_scan_image(image_path) as opened:
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
            pil_image = single_channel_or_rgb(opened)
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
    pages (:func:`iter_scan_pages`), so it holds one at a time; this process
    collects them all. A scan refusal arrives as itself; any other failure is
    a :class:`~lemely.runtime.sandbox.SandboxFailure`, which the grading
    pipeline records as a failed run like any other exception. Raises
    :class:`ValueError` when the scan produced no pages.
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
    with contextlib.closing(stream):
        pages = list(stream)
    if not pages:
        raise ValueError(f"{scan_path} produced no pages")
    return pages
