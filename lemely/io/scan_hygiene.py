"""Scan-hygiene gate (T2.6): flags blurred/blank pages and a page-count mismatch.

Never silently drops a bad scan — every finding is surfaced in
``ScanQualityReport.warnings``, which the caller must publish, never
swallowed. Uses only PIL/numpy (already dependencies); no OpenCV/SciPy
dependency is added.

**Ink-masked Laplacian variance, not whole-page variance (I1 review
MUST-FIX 1).** The first cut of this gate computed the variance of a
``uint8``-clipped Laplacian over the *whole page*, DPI-scaled by
``(dpi/96)**2``. Verified against all 16 real committed pages of
``tests/fixtures/handwritten-59/0625_w24_qp_42.pdf`` at 200 DPI, that metric
measured ink coverage, not sharpness: a page's raw variance is dominated by
how much of the page is written on (a huge near-uniform white background
pulls the population variance down for a sparsely-answered page), not by how
sharp the ink itself is. 44% of the 16 clean pages were flagged as blurred
purely for being sparse. The fix computes the Laplacian in float (no
``uint8`` clipping, which independently compressed the true signal ~5-6x on
a sharp page) and takes its variance **only over ink pixels** (grayscale
below :data:`_INK_THRESHOLD`) — a measure of how sharp the actual content is,
invariant to how much of the page it covers. Confirmed on a synthetic page
with 1/3/6/12/35 lines of identical strokes: the masked variance is constant
across line count (unmasked whole-page variance grows with line count and
would misjudge a sparse page as blurred). Re-verified against all 16 real
pages and their Gaussian-blur-sigma-3 counterparts, at 96/150/200/250/300/
350/400/450/500/550/600 DPI (I1 review round 4, SHOULD-FIX H, re-measured
post-approval after the reviewer could not reproduce the round-4 numbers:
restated again from "clean-page variance is 1000x+ above blurred-page
variance at every DPI tested", which measured false at the two DPIs
closest to production -- the per-page clean/blurred ratio is min **299.9x**
at the production 200 DPI (:data:`EXTRACTION_DPI`) and min **61.5x** at
300 DPI, only 1000x+ or better at 96/150 DPI; ink-masked variance measured
381.7-26020.4 on clean pages and 3.6-21.7 on their sigma=3-blurred
counterparts across the full 96-600 DPI sweep). The separation is still
comfortable in absolute terms at every DPI measured: **zero false
positives and zero false negatives across all 16 pages at every DPI from 96
to 600**, which is the result that actually justifies a single flat
threshold (not DPI-scaled -- the old ``(dpi/96)**2`` formula scaled in the
wrong direction for this metric over most of that range: masked variance
*decreases* as DPI increases from 96 to ~400, since a real ink edge spreads
over more pixels at finer sampling, then jumps back up by roughly **12x**
between 400 and 450 DPI (clean-page minimum 381.7 -> 4547.6) rather than
reversing smoothly -- a cliff, not a gradual turn, well past the production
200 DPI, and not further characterised between those two sample points).
``dpi`` is kept as a parameter for future recalibration/reporting but no
longer scales the threshold -- a deviation from the plan's "DPI-relative
threshold" (``docs/plans/ai-improvements-plan.md`` I1 Approach), recorded
there alongside this measurement.
"""

from __future__ import annotations

import io

import numpy as np
from PIL import Image

from lemely.core.schemas import StrictModel
from lemely.io.rasterise import EXTRACTION_DPI, RasterisedPage

# Re-derived against tests/fixtures/handwritten-59 (all 16 pages, 96-300 DPI)
# and a synthetic 1/3/6/12/35-line page: clean ink-masked variance measured
# 807.9-26020.4, Gaussian-blur-sigma-3 ink-masked variance measured
# 3.6-16.9 across that same range (re-measured, I1 review round 4 item 2:
# an earlier version of this comment said 3.74-19.44, not reproduced). 100
# sits with wide margin below every clean measurement and above every
# blurred one observed.
_BLUR_VARIANCE_THRESHOLD: float = 100.0

# A page whose pixels are almost all one value (a blank/near-blank scan) has
# near-zero intensity variance regardless of sharpness -- checked separately
# from blur so a blank page is never misreported as "sharp".
_BLANK_STDDEV_THRESHOLD: float = 3.0

# Grayscale intensity below which a pixel counts as "ink" rather than
# background/paper. 240 (not 255) so anti-aliased pixel edges around strokes
# are included -- the point is to isolate the population whose sharpness
# actually varies, not to segment ink with pixel-perfect precision.
_INK_THRESHOLD: int = 240

# Below this many ink pixels there is not enough content to estimate a
# variance the blur check can trust; such a page is left unflagged for
# blur (it may still be flagged as blank by the stddev check above, which
# uses the whole page and does not depend on ink-pixel count).
_MIN_INK_PIXELS_FOR_BLUR_CHECK: int = 200


def _laplacian_response(gray: np.ndarray) -> np.ndarray:
    """Discrete 3x3 Laplacian ``[[0,1,0],[1,-4,1],[0,1,0]]`` in float64.

    Computed directly over a numpy array (edge-padded) rather than via
    ``PIL.ImageFilter.Kernel``, which clips its result to ``uint8`` — on a
    sharp real page 8.3% of the true (signed) Laplacian response falls
    outside ``[0, 255]`` (measured range roughly -382 to 638), and that
    clipping alone compressed the shipped statistic ~5-6x against the true
    float Laplacian. No SciPy/OpenCV needed for a fixed 3x3 kernel.
    """
    padded = np.pad(gray, 1, mode="edge").astype(np.float64)
    return (
        padded[:-2, 1:-1]
        + padded[2:, 1:-1]
        + padded[1:-1, :-2]
        + padded[1:-1, 2:]
        - 4.0 * padded[1:-1, 1:-1]
    )


def _ink_masked_laplacian_variance(gray: np.ndarray) -> float | None:
    """Variance of the Laplacian response restricted to ink pixels.

    Returns ``None`` when there are too few ink pixels
    (:data:`_MIN_INK_PIXELS_FOR_BLUR_CHECK`) to estimate a trustworthy
    variance -- the caller must not flag such a page as blurred on this
    metric alone.
    """
    mask = gray < _INK_THRESHOLD
    if int(mask.sum()) < _MIN_INK_PIXELS_FOR_BLUR_CHECK:
        return None
    lap = _laplacian_response(gray)
    return float(lap[mask].var())


class PageQuality(StrictModel):
    page: int
    laplacian_variance: float | None
    """``None`` when there was not enough ink on the page to judge sharpness
    (see :data:`_MIN_INK_PIXELS_FOR_BLUR_CHECK`); such a page is never
    flagged as blurred on this metric."""
    is_blurred: bool
    is_blank: bool


class ScanQualityReport(StrictModel):
    """Never silent.

    ``warnings`` lists every human-readable finding, and the caller is
    expected to surface it (e.g. via a bus event) rather than only branch on
    ``passed``.
    """

    pages: list[PageQuality]
    page_count_expected: int | None
    page_count_actual: int
    page_count_mismatch: bool
    warnings: list[str]

    @property
    def passed(self) -> bool:
        return not self.warnings


def check_scan_hygiene(
    pages: list[RasterisedPage],
    *,
    expected_page_count: int | None = None,
    dpi: float = EXTRACTION_DPI,
) -> ScanQualityReport:
    """Run the T2.6 hygiene gate over a rasterised scan.

    ``expected_page_count`` is the question paper's page count when known
    (not currently threaded through from :class:`~lemely.core.loose_schemas.MarkScheme`,
    which does not carry it) — pass ``None`` to skip that check rather than
    fabricate an expectation. ``dpi`` is recorded in warning text only; see
    the module docstring for why it no longer scales the threshold.
    """
    page_reports: list[PageQuality] = []
    warnings: list[str] = []

    for page in pages:
        gray = np.asarray(Image.open(io.BytesIO(page.png_bytes)).convert("L"), dtype=np.float64)
        stddev = float(gray.std())
        is_blank = stddev < _BLANK_STDDEV_THRESHOLD
        variance = None if is_blank else _ink_masked_laplacian_variance(gray)
        is_blurred = variance is not None and variance < _BLUR_VARIANCE_THRESHOLD
        page_reports.append(
            PageQuality(
                page=page.index,
                laplacian_variance=variance,
                is_blurred=is_blurred,
                is_blank=is_blank,
            )
        )
        if is_blank:
            warnings.append(f"page {page.index}: blank or near-blank scan (stddev={stddev:.2f})")
        elif is_blurred:
            warnings.append(
                f"page {page.index}: blurred scan (ink-masked Laplacian variance="
                f"{variance:.1f}, threshold={_BLUR_VARIANCE_THRESHOLD:.1f}, "
                f"rendered at {dpi:.0f} DPI)"
            )

    mismatch = expected_page_count is not None and expected_page_count != len(pages)
    if mismatch:
        warnings.append(
            f"page count mismatch: scan has {len(pages)} page(s), "
            f"question paper has {expected_page_count}"
        )

    return ScanQualityReport(
        pages=page_reports,
        page_count_expected=expected_page_count,
        page_count_actual=len(pages),
        page_count_mismatch=mismatch,
        warnings=warnings,
    )
