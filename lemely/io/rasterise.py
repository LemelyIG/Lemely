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
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pypdfium2 as pdfium

if TYPE_CHECKING:
    from pathlib import Path

# Google's documented recommendation for image/PDF inputs (re-verified
# 2026-09-02); keeps a rendered page's image-tokenisation cost at the
# "medium" tier (560 tokens/page) rather than the ultra tier a higher DPI
# would push it into.
EXTRACTION_DPI: float = 200.0


@dataclass(frozen=True)
class RasterisedPage:
    """One rendered page.

    0-based ``index`` matches the image-part order sent to Gemini, which is
    also the ``page`` index Gemini must echo back in
    ``ExtractedAnswer.source_box`` (see ``build_extractor_user_prompt``).
    """

    index: int
    width: int
    height: int
    png_bytes: bytes


def rasterise_pdf_to_pages(pdf_path: Path, *, dpi: float = EXTRACTION_DPI) -> list[RasterisedPage]:
    """Render every page of *pdf_path* to a PNG image at *dpi*.

    Raises :class:`ValueError` if the PDF has no pages — an empty extraction
    call would silently carry no evidence at all rather than fail loudly.
    """
    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        scale = dpi / 72.0  # pypdfium2's scale is in units of 72dpi-points.
        pages: list[RasterisedPage] = []
        for index, page in enumerate(pdf):
            pil_image = page.render(scale=scale).to_pil().convert("RGB")
            buf = io.BytesIO()
            pil_image.save(buf, format="PNG")
            pages.append(
                RasterisedPage(
                    index=index,
                    width=pil_image.width,
                    height=pil_image.height,
                    png_bytes=buf.getvalue(),
                )
            )
    finally:
        pdf.close()

    if not pages:
        raise ValueError(f"{pdf_path} produced no pages")
    return pages


def _looks_like_pdf(path: Path) -> bool:
    """Sniff the magic bytes rather than trust the file extension.

    ``lemely.web.services.grading.extract_answers``'s own docstring says
    ``scan_path`` is "PDF / image" — the teacher/student portals accept
    ``image/*`` uploads as well as PDFs (``lemely/web/routers/teacher.py``),
    and a client-supplied filename is not authoritative (see
    ``lemely.web.upload_utils.safe_upload_name``, which does not trust it as
    a path either). The PDF magic bytes are ``%PDF-``.
    """
    with path.open("rb") as handle:
        header = handle.read(5)
    return header == b"%PDF-"


def _rasterise_single_image(image_path: Path) -> list[RasterisedPage]:
    """Wrap a plain (non-PDF) scan upload as a single-page result.

    A raw ``image/*`` upload is already a raster image — it is loaded and
    re-encoded as PNG so :class:`RasterisedPage` always carries the same
    format regardless of scan type, but it is not re-rasterised at
    :data:`EXTRACTION_DPI`: it has no vector content to render at a chosen
    DPI, unlike a PDF page.
    """
    from PIL import Image

    with Image.open(image_path) as opened:
        pil_image = opened.convert("RGB")
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
