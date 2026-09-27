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
from dataclasses import dataclass

import pypdfium2 as pdfium
from PIL import Image

from lemely.runtime.errors import LemelyError

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


class ScanTooLargeError(LemelyError):
    """A scan's declared geometry is beyond what extraction will render."""


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
