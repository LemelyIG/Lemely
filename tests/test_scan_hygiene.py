"""Unit tests for lemely.io.scan_hygiene (T2.6, I1 acceptance criterion 3)."""

from __future__ import annotations

import io
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from lemely.io.rasterise import RasterisedPage, rasterise_pdf_to_pages
from lemely.io.scan_hygiene import (
    _BLUR_VARIANCE_THRESHOLD,
    _MIN_INK_PIXELS_FOR_BLUR_CHECK,
    _ink_masked_laplacian_variance,
    _laplacian_response,
    check_scan_hygiene,
)

_FIXTURE = Path(__file__).parent / "fixtures" / "handwritten-59" / "0625_w24_qp_42.pdf"


def _text_like_page(width: int = 1654, height: int = 2339) -> Image.Image:
    """A page with real high-frequency detail: a grid of thin black lines and
    text-sized rectangles on a white background -- a blank page or a heavily
    blurred one both fail to have this, for different reasons the hygiene
    gate must tell apart (blank: near-zero stddev; blurred: low Laplacian
    variance despite non-trivial stddev)."""
    img = Image.new("L", (width, height), color=255)
    draw = ImageDraw.Draw(img)
    for y in range(40, height - 40, 24):
        for x in range(40, width - 40, 140):
            draw.rectangle([x, y, x + 90, y + 14], outline=0, width=2)
    return img.convert("RGB")


def _lined_page(n_lines: int, width: int = 1654, height: int = 2339) -> Image.Image:
    """A page carrying exactly *n_lines* identical strokes -- used to prove
    the ink-masked variance metric does not track how much of the page is
    written on (I1 review MUST-FIX 1: the un-masked metric did)."""
    img = Image.new("L", (width, height), color=255)
    draw = ImageDraw.Draw(img)
    for i in range(n_lines):
        y = 100 + i * 60
        draw.line([(100, y), (width - 100, y)], fill=0, width=3)
    return img.convert("RGB")


def _page_from_image(index: int, image: Image.Image) -> RasterisedPage:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return RasterisedPage(
        index=index, width=image.width, height=image.height, png_bytes=buf.getvalue()
    )


class ScanHygieneTests(unittest.TestCase):
    def test_clean_sharp_page_passes(self) -> None:
        page = _page_from_image(0, _text_like_page())
        report = check_scan_hygiene([page])
        self.assertTrue(report.passed, report.warnings)
        self.assertFalse(report.pages[0].is_blurred)
        self.assertFalse(report.pages[0].is_blank)

    def test_gaussian_blur_sigma_3_is_flagged(self) -> None:
        """Acceptance (3): a deliberately blurred fixture page (Gaussian blur
        sigma=3) is flagged; the clean version of the same page passes."""
        sharp = _text_like_page()
        blurred = sharp.filter(ImageFilter.GaussianBlur(radius=3))

        clean_report = check_scan_hygiene([_page_from_image(0, sharp)])
        blurred_report = check_scan_hygiene([_page_from_image(0, blurred)])

        self.assertTrue(clean_report.passed, clean_report.warnings)
        self.assertFalse(clean_report.pages[0].is_blurred)

        self.assertFalse(blurred_report.passed)
        self.assertTrue(blurred_report.pages[0].is_blurred)
        assert clean_report.pages[0].laplacian_variance is not None
        assert blurred_report.pages[0].laplacian_variance is not None
        self.assertLess(
            blurred_report.pages[0].laplacian_variance,
            clean_report.pages[0].laplacian_variance,
        )

    def test_blank_page_is_flagged_as_blank_not_blurred(self) -> None:
        blank = Image.new("RGB", (200, 280), color=255)
        report = check_scan_hygiene([_page_from_image(0, blank)])
        self.assertFalse(report.passed)
        self.assertTrue(report.pages[0].is_blank)
        self.assertFalse(report.pages[0].is_blurred)
        self.assertIsNone(report.pages[0].laplacian_variance)

    def test_page_count_mismatch_is_reported(self) -> None:
        page = _page_from_image(0, _text_like_page())
        report = check_scan_hygiene([page], expected_page_count=16)
        self.assertTrue(report.page_count_mismatch)
        self.assertIn(
            "page count mismatch",
            " ".join(report.warnings),
        )

    def test_page_count_match_does_not_add_a_warning(self) -> None:
        page = _page_from_image(0, _text_like_page())
        report = check_scan_hygiene([page], expected_page_count=1)
        self.assertFalse(report.page_count_mismatch)

    def test_ink_masked_variance_does_not_track_how_much_is_written(self) -> None:
        """I1 review MUST-FIX 1: the un-masked whole-page Laplacian variance
        measured ink coverage, not sharpness -- a sparsely-answered page (1
        line of writing) measured 71.5 against a threshold of 434 and was
        flagged as blurred purely for being sparse. The ink-masked metric
        must be (near-)invariant to how many identical strokes are on the
        page, and none of 1/3/6/12/35 lines may be flagged as blurred."""
        variances = []
        for n_lines in (1, 3, 6, 12, 35):
            page = _page_from_image(0, _lined_page(n_lines))
            report = check_scan_hygiene([page])
            self.assertFalse(
                report.pages[0].is_blurred,
                f"{n_lines} line(s) of identical, unblurred strokes must not be "
                f"flagged as blurred (variance={report.pages[0].laplacian_variance})",
            )
            assert report.pages[0].laplacian_variance is not None
            variances.append(report.pages[0].laplacian_variance)

        # Every measurement is the same synthetic stroke rendered at the same
        # sharpness -- the metric should not drift by orders of magnitude
        # just because there are more of them.
        self.assertLess(max(variances) / min(variances), 1.5, variances)

    def test_too_little_ink_is_not_judged_blurred(self) -> None:
        """Below the minimum-ink-pixel floor there is not enough content to
        estimate a trustworthy variance -- such a page must not be flagged as
        blurred (it may still be judged blank by the separate stddev check,
        which does not depend on ink-pixel count)."""
        tiny_mark = Image.new("L", (1654, 2339), color=255)
        draw = ImageDraw.Draw(tiny_mark)
        draw.point((827, 1169), fill=0)  # a single dark pixel: not blank, not enough ink
        report = check_scan_hygiene([_page_from_image(0, tiny_mark.convert("RGB"))])
        self.assertFalse(report.pages[0].is_blurred)
        self.assertIsNone(report.pages[0].laplacian_variance)

    @unittest.skipUnless(_FIXTURE.is_file(), "handwritten-59 fixture not present")
    def test_every_real_clean_fixture_page_is_not_flagged(self) -> None:
        """I1 review MUST-FIX 1: acceptance criterion 3 requires the gate to
        pass THE clean page, and the corpus has 16 of them -- checking only
        page 0 (the densest, printed cover page) missed that 7 of the other
        15 tripped the old metric. Every page must pass."""
        pages = rasterise_pdf_to_pages(_FIXTURE)
        report = check_scan_hygiene(pages)
        flagged = [p.page for p in report.pages if p.is_blurred or p.is_blank]
        self.assertEqual(flagged, [], report.warnings)

    @unittest.skipUnless(_FIXTURE.is_file(), "handwritten-59 fixture not present")
    def test_every_real_fixture_page_blurred_sigma_3_is_flagged(self) -> None:
        """Acceptance (3) against the whole real fixture, not one page: every
        one of the 16 pages, deliberately Gaussian-blurred (sigma=3), must be
        flagged; every corresponding unmodified page must pass."""
        pages = rasterise_pdf_to_pages(_FIXTURE)
        blurred_pages = []
        for page in pages:
            image = Image.open(io.BytesIO(page.png_bytes))
            blurred = image.filter(ImageFilter.GaussianBlur(radius=3))
            blurred_pages.append(_page_from_image(page.index, blurred))

        clean_report = check_scan_hygiene(pages)
        blurred_report = check_scan_hygiene(blurred_pages)

        clean_flagged = [p.page for p in clean_report.pages if p.is_blurred]
        blurred_not_flagged = [p.page for p in blurred_report.pages if not p.is_blurred]
        self.assertEqual(clean_flagged, [], "no clean page may be flagged as blurred")
        self.assertEqual(blurred_not_flagged, [], "every sigma=3 blurred page must be flagged")

    def test_laplacian_response_is_true_float_not_uint8_clipped(self) -> None:
        """I1 review round 2 addendum: a mutation reverting
        ``_laplacian_response`` to ``PIL.ImageFilter.Kernel`` on a
        ``uint8``-cast image (the ORIGINAL defect: that clipping compressed
        the true signal ~5-6x on a sharp page and is what let the
        un-normalised metric mistake ink coverage for sharpness) broke zero
        tests -- the threshold/fixture tests only check pass/fail, not the
        magnitude of the intermediate value. Pin the computation directly: a
        single black ink pixel on a white background has a true
        (edge-padded) Laplacian response of ``255*4 - 4*0 = 1020`` at that
        pixel, a value no ``uint8`` array (capped to ``[0, 255]``) can ever
        hold."""
        gray = np.full((5, 5), 255.0)
        gray[2, 2] = 0.0
        response = _laplacian_response(gray)
        self.assertEqual(response[2, 2], 1020.0)

    def test_blur_variance_threshold_is_pinned(self) -> None:
        """I1 review round 2 addendum: mutating the derived threshold
        (100.0 -> 434.0, the value round 1 shipped and was rejected for)
        broke zero tests -- the real-corpus separation is wide enough that
        many values in that neighbourhood also happen to work. Pin the
        exact derived literal directly, the same treatment already given to
        ``REREAD_UPSCALE``/``REREAD_PADDING_FRAC``."""
        self.assertEqual(_BLUR_VARIANCE_THRESHOLD, 100.0)

    def test_ink_pixel_floor_is_pinned(self) -> None:
        self.assertEqual(_MIN_INK_PIXELS_FOR_BLUR_CHECK, 200)

    def test_ink_pixel_floor_boundary_is_exact(self) -> None:
        """One pixel short of the floor abstains (``None``); exactly at the
        floor, a variance is computed -- pins the boundary itself, not just
        its value, so shifting the floor by even one breaks this."""
        below = Image.new("L", (1654, 2339), color=255)
        draw_below = ImageDraw.Draw(below)
        for i in range(_MIN_INK_PIXELS_FOR_BLUR_CHECK - 1):
            draw_below.point((100 + i, 100), fill=0)
        gray_below = np.asarray(below, dtype=np.float64)
        self.assertIsNone(_ink_masked_laplacian_variance(gray_below))

        at_floor = Image.new("L", (1654, 2339), color=255)
        draw_at = ImageDraw.Draw(at_floor)
        for i in range(_MIN_INK_PIXELS_FOR_BLUR_CHECK):
            draw_at.point((100 + i, 100), fill=0)
        gray_at = np.asarray(at_floor, dtype=np.float64)
        self.assertIsNotNone(_ink_masked_laplacian_variance(gray_at))

    @unittest.skipUnless(_FIXTURE.is_file(), "handwritten-59 fixture not present")
    def test_threshold_sits_strictly_between_every_real_clean_and_blurred_variance(
        self,
    ) -> None:
        """I1 review round 2 addendum: pin the threshold from both sides
        against the real corpus, not just its literal value -- a value at or
        below any real sigma=3-blurred page's variance would fail to flag
        it; a value at or above any real clean page's variance would
        misflag it."""
        pages = rasterise_pdf_to_pages(_FIXTURE)
        clean_variances: list[float] = []
        blurred_variances: list[float] = []
        for page in pages:
            image = Image.open(io.BytesIO(page.png_bytes))
            gray_clean = np.asarray(image.convert("L"), dtype=np.float64)
            clean_variance = _ink_masked_laplacian_variance(gray_clean)
            assert clean_variance is not None
            clean_variances.append(clean_variance)

            blurred = image.filter(ImageFilter.GaussianBlur(radius=3))
            gray_blurred = np.asarray(blurred.convert("L"), dtype=np.float64)
            blurred_variance = _ink_masked_laplacian_variance(gray_blurred)
            assert blurred_variance is not None
            blurred_variances.append(blurred_variance)

        self.assertGreater(_BLUR_VARIANCE_THRESHOLD, max(blurred_variances))
        self.assertLess(_BLUR_VARIANCE_THRESHOLD, min(clean_variances))


if __name__ == "__main__":
    unittest.main()
