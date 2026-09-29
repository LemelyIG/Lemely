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

import io
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pypdfium2 as pdfium

from lemely.io.scan_limits import (
    EXTRACTION_DPI,
    PDF_MAGIC,
    ScanRejectedError,
    ScanTooLargeError,
    check_pdf_content_path,
    looks_like_pdf,
    plan_image,
    plan_pdf_pages,
)

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "EXTRACTION_DPI",
    "PDF_MAGIC",
    "RasterisedPage",
    "ScanRejectedError",
    "ScanTooLargeError",
    "looks_like_pdf",
    "rasterise_pdf_to_pages",
    "rasterise_scan_to_pages",
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


def rasterise_pdf_to_pages(pdf_path: Path, *, dpi: float = EXTRACTION_DPI) -> list[RasterisedPage]:
    """Render every page of *pdf_path* to a PNG image at *dpi* (or the planned lower DPI).

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
    """
    # Task 11b: an old stored upload can pre-date the upload-time check, and
    # pypdfium2 parses a page's whole content stream on render -- measured at
    # 2.2 GB for a 218 KB bomb. Refuse from the raw streams first.
    check_pdf_content_path(pdf_path)
    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        plans = plan_pdf_pages(pdf, dpi=dpi)
        pages: list[RasterisedPage] = []
        for plan in plans:
            page = pdf[plan.index]
            # pypdfium2's scale is in units of 72dpi-points.
            pil_image = page.render(scale=plan.dpi / 72.0).to_pil().convert("RGB")
            buf = io.BytesIO()
            pil_image.save(buf, format="PNG")
            pages.append(
                RasterisedPage(
                    index=plan.index,
                    width=pil_image.width,
                    height=pil_image.height,
                    png_bytes=buf.getvalue(),
                    dpi=plan.dpi,
                )
            )
    finally:
        pdf.close()

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


def _rasterise_single_image(image_path: Path) -> list[RasterisedPage]:
    """Wrap a plain (non-PDF) scan upload as a single-page result.

    A raw ``image/*`` upload is already a raster image — it is loaded and
    re-encoded as PNG so :class:`RasterisedPage` always carries the same
    format regardless of scan type. Spec 2026-09-26 §6: an image within the
    band is reduced to fit ``MAX_PAGE_PX`` — a JPEG (which includes MPO)
    through Pillow's native reduced-scale decode first, anything else by an
    integer ``reduce`` after decoding — and one beyond ``MAX_DECODE_PX`` is
    refused from its header, before any pixel is decoded.
    """
    from PIL import Image, JpegImagePlugin

    try:
        with Image.open(image_path) as opened:
            factor = plan_image(opened.width, opened.height)
            if factor > 1 and isinstance(opened, JpegImagePlugin.JpegImageFile):
                opened.draft(None, (opened.width // factor, opened.height // factor))
            pil_image = opened.convert("RGB")
    except Image.DecompressionBombError as exc:
        raise ScanTooLargeError("image declares too many pixels to decode") from exc
    # Re-planned against the post-open dimensions: a JPEG's `.draft()` above picks
    # the nearest supported DCT scale, not exactly `factor`, so the image may still
    # need an extra integer `.reduce()` here to land under MAX_PAGE_PX.
    factor = plan_image(pil_image.width, pil_image.height)
    if factor > 1:
        pil_image = pil_image.reduce(factor)
    buf = io.BytesIO()
    pil_image.save(buf, format="PNG")
    return [
        RasterisedPage(
            index=0,
            width=pil_image.width,
            height=pil_image.height,
            png_bytes=buf.getvalue(),
        )
    ]


def rasterise_scan_to_pages(
    scan_path: Path, *, dpi: float = EXTRACTION_DPI
) -> list[RasterisedPage]:
    """Rasterise a scanned exam paper to per-page PNG images.

    Dispatches on the file's actual content (not its extension or a caller's
    claimed content type): a PDF is rendered page-by-page via
    :func:`rasterise_pdf_to_pages`; anything else is treated as a single
    already-rasterised image (``image/*`` uploads are accepted alongside PDFs
    — see ``lemely.web.routers.teacher``) and wrapped as one
    :class:`RasterisedPage`.
    """
    if _looks_like_pdf(scan_path):
        return rasterise_pdf_to_pages(scan_path, dpi=dpi)
    return _rasterise_single_image(scan_path)
