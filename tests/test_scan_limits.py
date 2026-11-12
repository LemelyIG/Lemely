"""Unit tests for lemely.io.scan_limits (spec 2026-09-26 §6).

#262 split the module and its tests. This file keeps what ``scan_limits``
and ``_scan_common`` own -- page and image planning, the per-scan pixel
budget, ``check_scan_bytes`` and the image allowlist -- plus the sweeps over
``lemely/`` and the split itself. The PDF checks are tested beside their
modules: ``test_pdf_prescan.py``, ``test_pdf_content_walk.py`` and
``test_pdf_canonical.py``, which share the helpers defined here.
"""

from __future__ import annotations

import ast
import contextlib
import functools
import io
import math
import os
import subprocess
import symtable
import sys
import textwrap
import unittest
import warnings
from pathlib import Path
from typing import ClassVar
from unittest.mock import patch

import pymupdf
import pypdfium2 as pdfium
from PIL import Image

import lemely.io._scan_common as _scan_common
import lemely.io.pdf_canonical as pdf_canonical
import lemely.io.pdf_content_walk as pdf_content_walk
import lemely.io.pdf_prescan as pdf_prescan
import lemely.io.scan_limits as scan_limits
from lemely.io.scan_limits import (
    MAX_DECODE_PX,
    MAX_DECODE_PX_GREY,
    MAX_DECODE_PX_WEBP,
    MAX_PAGE_PX,
    MAX_SCAN_PAGES,
    MAX_SCAN_TOTAL_PX,
    MIN_EXTRACTION_DPI,
    SCAN_IMAGE_FORMATS,
    ScanRejectedError,
    ScanTooLargeError,
    ScanUnsupportedFormatError,
    check_scan_bytes,
    decode_pixel_cap,
    plan_image,
    plan_page_dpi,
    plan_pdf_pages,
)
from tests.pdf_fakes import (
    bilevel_png,
    declared_image,
    encrypted_pdf_bytes,
    ico_wrapping,
    pdf_with_inflated_count,
    pdf_with_missing_kid_object,
    plain_webp,
)

_FIXTURE = Path(__file__).parent / "fixtures" / "handwritten-59" / "0625_w24_qp_42.pdf"


def _require_committed_fixture(path: Path) -> None:
    """Fail -- never skip -- when a fixture committed to the repo is missing.

    Final review, item 9: ``skipUnless(fixture.is_file())`` turned a deleted
    or renamed fixture into a silent skip, so the tests that pin real scans
    stopped running without anyone seeing a failure.
    """
    assert path.is_file(), f"committed fixture missing: {path}"


def _readers_trapped() -> contextlib.ExitStack:
    """Fail the test if any reader opens the file.

    Shared by ``test_pdf_prescan.py`` and ``test_pdf_canonical.py``: the
    pre-scan must refuse what it refuses before MuPDF or pdfium sees a byte.
    """
    stack = contextlib.ExitStack()
    for target, name in ((pymupdf, "open"), (pdfium, "PdfDocument")):
        stack.enter_context(
            patch.object(target, name, side_effect=AssertionError(f"{name} was called"))
        )
    return stack


def _pdf_bytes(*sizes_pt: tuple[float, float]) -> bytes:
    """A PDF declaring the given page sizes (points), as bytes.

    ``PdfDocument.save`` takes a path or a binary file object; if the
    installed pypdfium2 rejects the ``BytesIO``, save to a ``tempfile``
    path and ``read_bytes()`` it instead.
    """
    pdf = pdfium.PdfDocument.new()
    for width, height in sizes_pt:
        pdf.new_page(width, height)
    buf = io.BytesIO()
    pdf.save(buf)
    pdf.close()
    return buf.getvalue()


def _png_bytes(width: int, height: int, mode: str = "1") -> bytes:
    buf = io.BytesIO()
    Image.new(mode, (width, height), color=1 if mode == "1" else "white").save(buf, "PNG")
    return buf.getvalue()


class PagePlanTests(unittest.TestCase):
    def test_a4_at_200_dpi_is_rendered_as_is(self) -> None:
        self.assertEqual(plan_page_dpi(595.0, 842.0), 200.0)

    def test_a_page_within_the_band_is_planned_at_a_lower_dpi(self) -> None:
        # A1: 1684x2384 pt is ~31 Mpx at 200 DPI -- over the 16 Mpx target,
        # under the 40 Mpx reject boundary -- so it renders at floor(200 *
        # sqrt(16e6 / 31e6)) = 143 DPI and lands under the target.
        dpi = plan_page_dpi(1684.0, 2384.0)
        self.assertEqual(dpi, 143.0)
        self.assertLessEqual(1684 * 2384 * (dpi / 72) ** 2, MAX_PAGE_PX)

    def test_a_page_beyond_the_decode_bound_is_rejected(self) -> None:
        with self.assertRaises(ScanTooLargeError) as ctx:
            plan_page_dpi(14400.0, 14400.0)
        self.assertIn("too large to process", str(ctx.exception))

    def test_more_than_max_pages_is_rejected_before_any_render(self) -> None:
        pdf = pdfium.PdfDocument(_pdf_bytes(*([(595.0, 842.0)] * (MAX_SCAN_PAGES + 1))))
        try:
            with (
                patch.object(pdfium.PdfPage, "render") as render,
                self.assertRaises(ScanTooLargeError),
            ):
                plan_pdf_pages(pdf)
            render.assert_not_called()
        finally:
            pdf.close()

    def test_plans_carry_page_indices_in_order(self) -> None:
        pdf = pdfium.PdfDocument(_pdf_bytes((595.0, 842.0), (1684.0, 2384.0)))
        try:
            plans = plan_pdf_pages(pdf)
        finally:
            pdf.close()
        self.assertEqual([(p.index, p.dpi) for p in plans], [(0, 200.0), (1, 143.0)])


#: #256: the modes that keep the 40 Mpx colour ceiling, one per kind -- three
#: and four channels, CMYK, palette (converted to RGB before it can be
#: reduced) and grey with alpha (two channels).
_COLOUR_MODES = ("RGB", "RGBA", "CMYK", "P", "LA")
#: #256: 6500 x 6400 = 41.6 Mpx, just over the colour ceiling.
_COLOUR_OVER_CAP = (6500, 6400)
#: #256 (probe ``be_probe_img.py``): a 1-bit A4 office scan at 1200 dpi, 139 Mpx.
_A4_AT_1200_DPI = (9921, 14031)
#: #256: 12600^2 = 158.8 Mpx is under the grey ceiling, 12700^2 = 161.3 Mpx over it.
_GREY_UNDER_CAP = (12600, 12600)
_GREY_OVER_CAP = (12700, 12700)
#: #256, the WebP ceiling: 3650^2 = 13.32 Mpx is under it, 3700^2 = 13.69 Mpx over.
_WEBP_UNDER_CAP = (3650, 3650)
_WEBP_OVER_CAP = (3700, 3700)


class ImagePlanTests(unittest.TestCase):
    def test_image_under_the_target_is_not_reduced(self) -> None:
        self.assertEqual(plan_image(1655, 2339), 1)

    def test_image_within_the_band_is_reduced_by_the_smallest_factor_that_fits(self) -> None:
        self.assertEqual(plan_image(5000, 5000), 2)  # 25 Mpx -> 6.25 Mpx

    def test_a_colour_image_just_over_forty_megapixels_is_still_refused(self) -> None:
        """User decision 1 (2026-09-29): colour keeps its ceiling."""
        for mode in _COLOUR_MODES:
            with self.subTest(mode=mode), self.assertRaises(ScanTooLargeError):
                plan_image(*_COLOUR_OVER_CAP, mode)
        # The default mode is colour: a caller that names none gets 40 Mpx.
        with self.assertRaises(ScanTooLargeError):
            plan_image(*_COLOUR_OVER_CAP)

    def test_a_bilevel_office_scan_at_1200_dpi_is_admitted_and_reduced(self) -> None:
        """#256 (probe ``be_probe_img.py``): a 1-bit A4 at 1200 dpi is 139 Mpx
        in a 0.04 MB file and was refused at upload with "limit 40
        megapixels". Bilevel and 8-bit greyscale go to 160 Mpx; it is reduced
        by 4 to 8.7 Mpx for the model."""
        self.assertEqual(plan_image(*_A4_AT_1200_DPI, "1"), 4)
        self.assertEqual(plan_image(*_A4_AT_1200_DPI, "L"), 4)

    def test_greyscale_just_over_the_grey_ceiling_is_refused(self) -> None:
        self.assertEqual(plan_image(*_GREY_UNDER_CAP, "L"), 4)  # 158.8 Mpx: admitted
        self.assertEqual(plan_image(*_GREY_UNDER_CAP, "1"), 4)
        for mode in ("1", "L"):
            with self.subTest(mode=mode), self.assertRaises(ScanTooLargeError) as caught:
                plan_image(*_GREY_OVER_CAP, mode)  # 161.3 Mpx
            self.assertIn("limit 160 megapixels", str(caught.exception))

    def test_the_refusal_names_a_limit_that_is_true_for_the_mode(self) -> None:
        """#256 review: "LA", "I" and "F" get a colour-sized ceiling without
        being colour, so the message states the limit and how to reach the
        larger one instead of calling every such image "colour". Task 11
        review: "I" and "F" decode to 4 bytes a pixel, so 30 Mpx."""
        for mode, mpx in (("RGB", 40), ("LA", 40), ("P", 40), ("I", 30), ("F", 30)):
            with self.subTest(mode=mode), self.assertRaises(ScanTooLargeError) as caught:
                plan_image(*_COLOUR_OVER_CAP, mode)
            message = str(caught.exception)
            self.assertIn(f"limit {mpx} megapixels; a black-and-white or 8-bit greyscale", message)
            self.assertNotIn("colour", message)
        with self.assertRaises(ScanTooLargeError) as caught:
            plan_image(9000, 9000, "I;16")
        self.assertIn("limit 80 megapixels for a 16-bit greyscale image", str(caught.exception))

    def test_sixteen_bit_grey_gets_half_the_grey_ceiling(self) -> None:
        self.assertEqual(plan_image(8900, 8900, "I;16"), 4)  # 79.2 Mpx: admitted
        with self.assertRaises(ScanTooLargeError):
            plan_image(9000, 9000, "I;16B")  # 81 Mpx

    def test_a_webp_gets_a_third_of_the_colour_ceiling_whatever_its_mode(self) -> None:
        """#256, the WebP ceiling: Pillow 12 decodes every WebP through
        ``WebPAnimDecoder`` (extra full-canvas RGBA buffers; grey decodes as
        RGB) -- measured 609 MB to extract 39.7 Mpx against 192 MB for the
        same PNG -- so WebP is capped at a third of the colour budget."""
        self.assertEqual(MAX_DECODE_PX_WEBP, MAX_DECODE_PX // 3)
        for mode in ("RGB", "RGBA", "L", "1"):
            with self.subTest(mode=mode):
                self.assertEqual(decode_pixel_cap(mode, "WEBP"), MAX_DECODE_PX_WEBP)
        self.assertEqual(decode_pixel_cap("RGB", "PNG"), MAX_DECODE_PX)
        self.assertEqual(decode_pixel_cap("L", "PNG"), MAX_DECODE_PX_GREY)
        self.assertEqual(plan_image(*_WEBP_UNDER_CAP, "RGB", "WEBP"), 1)  # 13.32 Mpx
        with self.assertRaises(ScanTooLargeError) as caught:
            plan_image(*_WEBP_OVER_CAP, "RGB", "WEBP")  # 13.69 Mpx
        message = str(caught.exception)
        self.assertIn("This WebP image is too large to process (limit 13 megapixels", message)
        self.assertIn("Save it as a PNG or JPEG", message)

    def test_decode_pixel_cap_charges_what_pillow_holds(self) -> None:
        """Pillow keeps mode "1" at one byte per pixel (measured: 100 Mpx of
        "1" and of "L" both cost 96 MB), so both get the grey ceiling; 16-bit
        grey is two bytes, so half; "P" is converted to RGB before it can be
        reduced and "LA" is two channels, so both keep the colour ceiling.
        Four-byte modes get three quarters of it (Task 11 review; the full
        rule is tested in ``test_colour_decode_caps.py``)."""
        self.assertEqual(decode_pixel_cap("1"), MAX_DECODE_PX_GREY)
        self.assertEqual(decode_pixel_cap("L"), MAX_DECODE_PX_GREY)
        for mode in ("I;16", "I;16L", "I;16B", "I;16N"):
            with self.subTest(mode=mode):
                self.assertEqual(decode_pixel_cap(mode), MAX_DECODE_PX_GREY // 2)
        for mode in ("LA", "P", "RGB", "no-such-mode"):
            with self.subTest(mode=mode):
                self.assertEqual(decode_pixel_cap(mode), MAX_DECODE_PX)
        for mode in ("I", "F", "RGBA", "CMYK"):
            with self.subTest(mode=mode):
                self.assertEqual(decode_pixel_cap(mode), MAX_DECODE_PX * 3 // 4)

    def test_the_grey_ceiling_fits_the_scan_budget_and_the_page_target(self) -> None:
        """#256 consistency: one grey image may cost what a whole PDF scan
        may (``MAX_SCAN_TOTAL_PX``), never more; at the ceiling it still
        reduces under ``MAX_PAGE_PX`` with a factor short of the last one,
        so the ``pragma: no cover`` fallthrough stays unreachable; and
        Pillow's own bomb error (twice ``MAX_IMAGE_PIXELS``) sits above it,
        so ``Image.open`` never refuses an image this module admits."""
        self.assertLessEqual(MAX_DECODE_PX_GREY, MAX_SCAN_TOTAL_PX)
        side = math.isqrt(MAX_DECODE_PX_GREY)
        factor = plan_image(side, side, "L")
        self.assertLess(factor, 8)
        self.assertLessEqual((side / factor) ** 2, MAX_PAGE_PX)
        bomb_warning_px = Image.MAX_IMAGE_PIXELS
        assert bomb_warning_px is not None, "the app never disables Pillow's bomb guard"
        self.assertLess(MAX_DECODE_PX_GREY, 2 * bomb_warning_px)


def _planned_total_px(pdf: pdfium.PdfDocument, plans: list[scan_limits.PagePlan]) -> float:
    total = 0.0
    for plan in plans:
        width_pt, height_pt = pdf.get_page_size(plan.index)
        total += width_pt * height_pt * (plan.dpi / 72.0) ** 2
    return total


class ScanTotalPixelTests(unittest.TestCase):
    """Final review I1: the per-page cap alone let 40 pages of ~16 Mpx each
    (the reviewer's 1.13 MB PDF of 1439 pt squares sharing one JPEG) plan to
    ~640 Mpx, ~1.5 GB of rendered pages in a 1 GiB worker. The scan's summed
    planned pixels are capped at MAX_SCAN_TOTAL_PX by one uniform DPI factor,
    floored at MIN_EXTRACTION_DPI. Planning only -- nothing here renders."""

    def _plans(self, *sizes_pt: tuple[float, float]) -> tuple[list[float], float]:
        pdf = pdfium.PdfDocument(_pdf_bytes(*sizes_pt))
        try:
            with patch.object(pdfium.PdfPage, "render") as render:
                plans = plan_pdf_pages(pdf)
            render.assert_not_called()
            return [p.dpi for p in plans], _planned_total_px(pdf, plans)
        finally:
            pdf.close()

    def test_the_bounds_are_the_decided_values(self) -> None:
        self.assertEqual((MAX_SCAN_TOTAL_PX, MIN_EXTRACTION_DPI), (160_000_000, 100))

    def test_the_reviewer_aggregate_shape_is_downscaled_uniformly_to_fit(self) -> None:
        dpis, total = self._plans(*([(1439.0, 1439.0)] * MAX_SCAN_PAGES))
        self.assertEqual(len(set(dpis)), 1, dpis)
        self.assertEqual(dpis[0], 100.0)  # floor(200 * sqrt(160 / 639.1)) = floor(100.06)
        self.assertLessEqual(total, MAX_SCAN_TOTAL_PX)

    def test_mixed_page_sizes_share_one_scale_factor(self) -> None:
        # 10 A1 pages (per-page band, planned at 143 DPI, 15.8 Mpx each) plus
        # 30 A4 pages at 200 DPI (3.87 Mpx each): 274 Mpx, so every page's
        # planned DPI is multiplied by the same s = sqrt(160 / 274) = 0.764,
        # then floored: 143 -> 109, 200 -> 152.
        sizes = [(1684.0, 2384.0)] * 10 + [(595.0, 842.0)] * 30
        dpis, total = self._plans(*sizes)
        self.assertEqual(dpis, [109.0] * 10 + [152.0] * 30)
        self.assertLessEqual(total, MAX_SCAN_TOTAL_PX)

    def test_an_honest_40_page_a4_scan_is_unchanged(self) -> None:
        dpis, total = self._plans(*([(595.0, 842.0)] * MAX_SCAN_PAGES))
        self.assertEqual(dpis, [200.0] * MAX_SCAN_PAGES)
        self.assertGreater(total, 150_000_000)  # ~155 Mpx: close to, but under, the cap

    def test_the_committed_fixture_is_unchanged(self) -> None:
        pdf = pdfium.PdfDocument(str(_FIXTURE))
        try:
            dpis = [p.dpi for p in plan_pdf_pages(pdf)]
        finally:
            pdf.close()
        self.assertEqual(dpis, [200.0] * 16)

    def test_a_scan_that_cannot_fit_at_the_minimum_dpi_is_rejected(self) -> None:
        # 1700 pt squares plan at 169 DPI each (per-page band); 40 of them
        # need s = 0.50, i.e. 84 DPI -- under the 100 DPI floor.
        pdf = pdfium.PdfDocument(_pdf_bytes(*([(1700.0, 1700.0)] * MAX_SCAN_PAGES)))
        try:
            with self.assertRaises(ScanTooLargeError) as ctx:
                plan_pdf_pages(pdf)
        finally:
            pdf.close()
        self.assertIn("160 megapixels", str(ctx.exception))

    def test_a_scan_that_cannot_fit_is_rejected_at_upload(self) -> None:
        with self.assertRaises(ScanTooLargeError):
            check_scan_bytes(_pdf_bytes(*([(1700.0, 1700.0)] * MAX_SCAN_PAGES)))

    def test_the_reviewer_aggregate_shape_passes_the_upload_check(self) -> None:
        """It fits once downscaled, so the upload must not refuse it."""
        check_scan_bytes(_pdf_bytes(*([(1439.0, 1439.0)] * MAX_SCAN_PAGES)))


class CheckScanBytesTests(unittest.TestCase):
    def test_a4_pdf_passes(self) -> None:
        check_scan_bytes(_pdf_bytes((595.0, 842.0)))

    def test_oversized_pdf_page_is_rejected_from_bytes(self) -> None:
        with self.assertRaises(ScanTooLargeError):
            check_scan_bytes(_pdf_bytes((14400.0, 14400.0)))

    def test_too_many_pdf_pages_are_rejected_from_bytes(self) -> None:
        with self.assertRaises(ScanTooLargeError):
            check_scan_bytes(_pdf_bytes(*([(595.0, 842.0)] * (MAX_SCAN_PAGES + 1))))

    def test_oversized_image_is_rejected_from_its_header(self) -> None:
        """A header only: the check must refuse before a pixel is decoded
        (the file holds none), in every colour mode (#256: colour keeps 40 Mpx)."""
        for mode in _COLOUR_MODES:
            with self.subTest(mode=mode), self.assertRaises(ScanTooLargeError):
                check_scan_bytes(declared_image(mode, *_COLOUR_OVER_CAP))

    def test_a_bilevel_scan_over_forty_megapixels_is_accepted_at_upload(self) -> None:
        """#256: the regression against develop, which accepted this file."""
        check_scan_bytes(_png_bytes(7000, 7000))  # 49 Mpx of mode "1"

    def test_a_bilevel_a4_office_scan_at_1200_dpi_is_accepted_at_upload(self) -> None:
        """#256 (probe ``be_probe_img.py``): the issue's own file shape, a real
        1-bit PNG of ~40 KB declaring 139 Mpx."""
        scan = bilevel_png(*_A4_AT_1200_DPI)
        self.assertLess(len(scan), 100_000)
        check_scan_bytes(scan)

    def test_an_admitted_grey_scan_opens_without_pillows_bomb_warning(self) -> None:
        """#256 review: Pillow warns from 89.5 Mpx, below the grey ceiling, so
        every admitted 90-160 Mpx grey scan warned. The cap bounds the decode,
        so the opener silences that one warning (never ``MAX_IMAGE_PIXELS``
        itself: its error, above the cap, still stands)."""
        # Why the filter exists: Pillow's warning threshold is under the grey cap.
        assert Image.MAX_IMAGE_PIXELS is not None, "the app never disables Pillow's bomb guard"
        self.assertLess(Image.MAX_IMAGE_PIXELS, MAX_DECODE_PX_GREY)
        # "always" is put in FRONT of the module's filter, as pytest's -W or a
        # caller's own filter would be; the opener must still win for the
        # scans it caps, and report nothing.
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            check_scan_bytes(bilevel_png(*_A4_AT_1200_DPI))
            decides = next(
                entry
                for entry in warnings.filters
                if issubclass(Image.DecompressionBombWarning, entry[2])
            )
        self.assertEqual(
            [w for w in caught if issubclass(w.category, Image.DecompressionBombWarning)], []
        )
        self.assertEqual(decides, ("ignore", None, Image.DecompressionBombWarning, None, 0))

    def test_an_ico_wrapping_a_big_png_is_refused_without_being_opened(self) -> None:
        """#256 review: Pillow's ICO opener decodes the image it wraps inside
        ``Image.open`` -- a 16x16 ICO around a 158.8 Mpx PNG cost 154 MB in
        this check. It must be named from its first bytes and never opened:
        the opener is booby-trapped, and this check swallows unexpected
        errors, so a refusal that ran it would pass instead of raising."""
        from PIL import IcoImagePlugin

        scan = ico_wrapping(bilevel_png(*_A4_AT_1200_DPI))
        with (
            patch.object(IcoImagePlugin.IcoImageFile, "_open", side_effect=AssertionError),
            self.assertRaises(ScanUnsupportedFormatError) as caught,
        ):
            check_scan_bytes(scan)
        self.assertIn("image format (ICO) cannot be processed safely", str(caught.exception))

    def test_formats_outside_the_allowlist_are_refused_at_upload(self) -> None:
        for image_format in ("ICNS", "GIF", "PCX"):
            with self.subTest(format=image_format):
                buf = io.BytesIO()
                Image.new("RGB", (16, 16)).save(buf, image_format)
                with self.assertRaises(ScanUnsupportedFormatError):
                    check_scan_bytes(buf.getvalue())

    def test_scan_formats_still_pass_at_upload(self) -> None:
        """JPEG, MPO, PNG, TIFF, WebP and BMP -- what scanners and phones write."""
        second = Image.new("RGB", (8, 8))
        for image_format in (*SCAN_IMAGE_FORMATS, "MPO"):
            with self.subTest(format=image_format):
                buf = io.BytesIO()
                extra = (
                    {"save_all": True, "append_images": [second]} if image_format == "MPO" else {}
                )
                Image.new("RGB", (64, 64), "white").save(buf, image_format, **extra)
                with Image.open(io.BytesIO(buf.getvalue())) as reopened:
                    self.assertEqual(reopened.format, image_format)
                check_scan_bytes(buf.getvalue())

    def test_a_webp_is_judged_against_the_webp_ceiling_at_upload(self) -> None:
        check_scan_bytes(plain_webp(*_WEBP_UNDER_CAP))
        with self.assertRaises(ScanTooLargeError) as caught:
            check_scan_bytes(plain_webp(*_WEBP_OVER_CAP))
        self.assertIn("This WebP image is too large", str(caught.exception))

    def test_greyscale_is_judged_against_the_grey_ceiling_at_upload(self) -> None:
        check_scan_bytes(declared_image("L", *_GREY_UNDER_CAP))  # 158.8 Mpx
        for mode in ("1", "L"):
            with self.subTest(mode=mode), self.assertRaises(ScanTooLargeError):
                check_scan_bytes(declared_image(mode, *_GREY_OVER_CAP))  # 161.3 Mpx

    def test_image_within_the_band_passes(self) -> None:
        check_scan_bytes(_png_bytes(5000, 5000))

    def test_decompression_bomb_is_reported_as_too_large(self) -> None:
        data = _png_bytes(100, 100)
        with patch.object(Image, "MAX_IMAGE_PIXELS", 1000), self.assertRaises(ScanTooLargeError):
            check_scan_bytes(data)

    def test_unparseable_bytes_are_not_rejected(self) -> None:
        """A fake `%PDF-1.4 scan` body or random bytes must pass the upload
        check: extraction fails on them later, exactly as today (existing
        upload tests post such bodies)."""
        check_scan_bytes(b"%PDF-1.4 fake")
        check_scan_bytes(b"not an image at all")

    def test_a_page_tree_with_a_missing_kids_object_is_not_rejected(self) -> None:
        """Regression: a document that opens but has a page that will not
        load used to crash 500 (`plan_pdf_pages` raised pypdfium2's own
        `PdfiumError` and only the outer `PdfDocument(data)` open was
        guarded). It must pass through like any other geometry this module
        cannot fully make sense of -- extraction fails on it later.

        Task 9b keeps this: pdfium cannot size page 2, so extraction renders
        nothing, and MuPDF (the crop route's renderer) resolves both pages
        and its content check measures them."""
        check_scan_bytes(pdf_with_missing_kid_object())

    def test_a_page_tree_with_an_inflated_count_is_rejected(self) -> None:
        """Task 9b, fail closed: ``/Count 2`` over one real page. Neither
        reader can resolve page 2, so the content check cannot cover every
        page a reader will try to render -- refused, where it used to pass
        because pdfium's planning failure skipped the MuPDF check."""
        with self.assertRaises(ScanRejectedError):
            check_scan_bytes(pdf_with_inflated_count())

    def test_an_encrypted_pdf_is_not_rejected(self) -> None:
        check_scan_bytes(encrypted_pdf_bytes())

    def test_bounds_are_the_documented_values(self) -> None:
        self.assertEqual(
            (
                MAX_SCAN_PAGES,
                MAX_PAGE_PX,
                MAX_DECODE_PX,
                MAX_DECODE_PX_GREY,
                MAX_DECODE_PX_WEBP,
                MAX_SCAN_TOTAL_PX,
            ),
            (40, 16_000_000, 40_000_000, 160_000_000, 13_333_333, 160_000_000),
        )


class SanctionedOpenerSweepTests(unittest.TestCase):
    """Sweeps over ``lemely/``: user PDF bytes reach MuPDF only through the
    sanctioned openers, and only :func:`prescan_pdf` vouches for a pre-scan.
    Each reads every module's source, so neither belongs to one module."""

    def test_every_mupdf_open_of_user_bytes_goes_through_the_sanctioned_openers(self) -> None:
        """Final review, item 4: "pre-scan before any MuPDF open" is enforced
        by code, not by each caller remembering. Every ``pymupdf.open`` (or
        ``fitz.open``/``Document``, through any import, ``from`` import or
        one-level alias) given anything to open, and every ``insert_pdf`` /
        ``insert_file``, anywhere in ``lemely/``, is inside
        :func:`open_checked_pdf` or ``_copy_pages`` (an image scan never
        reaches MuPDF: final review R3, I1). A bare ``pymupdf.open()`` makes a new, empty document.
        The sweep, and the forms it cannot see, are in ``tests/mupdf_sweep.py``."""
        from tests.mupdf_sweep import ALLOWED_OPENS, find_mupdf_opens, sweep

        found = sweep(Path(__file__).resolve().parents[1], find_mupdf_opens)
        self.assertEqual(
            found - ALLOWED_OPENS, set(), "a MuPDF open outside the sanctioned openers"
        )
        self.assertEqual(found, ALLOWED_OPENS)

    def test_only_prescan_pdf_makes_a_prescanned_pdf(self) -> None:
        """Final review, item 5: a :class:`PrescannedPdf` is how a caller skips
        the pre-scan in ``open_checked_pdf``, so nothing in ``lemely/`` makes
        one except :func:`prescan_pdf`, which has just run it."""
        from tests.mupdf_sweep import ALLOWED_PRESCANNED, find_prescanned_constructions, sweep

        found = sweep(Path(__file__).resolve().parents[1], find_prescanned_constructions)
        self.assertEqual(found, ALLOWED_PRESCANNED)


#: The split modules by import path. A name any of them re-exports is one object
#: in all of them, and a patch on any of them is checked by the sweep below.
_SCAN_MODULES = {
    module.__name__: module
    for module in (_scan_common, pdf_prescan, pdf_content_walk, pdf_canonical, scan_limits)
}
#: ``patch.multiple``'s own keywords, which name no attribute.
_MULTIPLE_OPTIONS = frozenset({"target", "spec", "create", "spec_set", "autospec", "new_callable"})


def _dotted(expr: ast.expr) -> str | None:
    """``a.b.c`` for an attribute chain ending in a name, else ``None``."""
    parts: list[str] = []
    while isinstance(expr, ast.Attribute):
        parts.append(expr.attr)
        expr = expr.value
    if not isinstance(expr, ast.Name):
        return None
    parts.append(expr.id)
    return ".".join(reversed(parts))


def _argument(call: ast.Call, position: int, *keywords: str) -> ast.expr | None:
    """``call``'s argument at ``position``, or the one passed by any of ``keywords``."""
    if len(call.args) > position:
        return call.args[position]
    return next((kw.value for kw in call.keywords if kw.arg in keywords), None)


def _scan_module_patches(source: str) -> list[tuple[int, str, str | None]]:
    """``(line, module, name)`` for every patch in ``source`` of ``name`` on a split module.

    Finds ``patch.object(m, "name")``, ``patch.multiple(m, name=...)``,
    ``monkeypatch.setattr(m, "name", ...)``, ``setattr(m, "name", ...)`` --
    with the module and the attribute passed by position or by keyword
    (``target=``, ``attribute=``, ``name=``) -- and the string forms
    ``patch("lemely.io.<module>.name")`` and
    ``monkeypatch.setattr("lemely.io.<module>.name", ...)``. ``m`` is any of
    the five split modules, under any alias the file imports it as, or
    spelled out in full. ``name`` is ``None`` when the attribute is not a
    string literal (a variable, ``**kwargs``): the sweep cannot tell what
    such a patch replaces, so it counts as a miss.
    """
    tree = ast.parse(source)
    aliases = {path: path for path in _SCAN_MODULES}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in _SCAN_MODULES and alias.asname:
                    aliases[alias.asname] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module == "lemely.io":
            for alias in node.names:
                if f"lemely.io.{alias.name}" in _SCAN_MODULES:
                    aliases[alias.asname or alias.name] = f"lemely.io.{alias.name}"
    found: list[tuple[int, str, str | None]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        verb = (_dotted(node.func) or "").rpartition(".")[2]
        target = _argument(node, 0, "target")
        if verb not in ("patch", "object", "multiple", "setattr") or target is None:
            continue
        if isinstance(target, ast.Constant) and isinstance(target.value, str):
            module, _, name = target.value.rpartition(".")
            if verb in ("patch", "setattr") and module in _SCAN_MODULES:
                found.append((node.lineno, module, name))
            continue
        module = aliases.get(_dotted(target) or "")
        if module is None:
            continue
        if verb == "multiple":
            found.extend(
                (node.lineno, module, kw.arg)
                for kw in node.keywords
                if kw.arg not in _MULTIPLE_OPTIONS
            )
        elif verb in ("object", "setattr"):
            attribute = _argument(node, 1, "attribute", "name")
            literal = isinstance(attribute, ast.Constant) and isinstance(attribute.value, str)
            found.append((node.lineno, module, attribute.value if literal else None))  # type: ignore[union-attr]
    return sorted(found, key=lambda patch: (patch[0], patch[1], patch[2] or ""))


#: The re-exporting modules. A patch on one reaches only code that looks the
#: name up there, so every other reader of the name counts against it.
_FACADES = frozenset({"lemely.io.scan_limits", "lemely.io._scan_common"})


class _ModuleScopeReads(ast.NodeVisitor):
    """Names read at module scope: outside any function, lambda or class body
    (those are their own scopes, read by :func:`_global_reads` from the
    symbol table), and not a comprehension's own loop variable."""

    def __init__(self) -> None:
        self.reads: set[str] = set()
        self._comprehension_names: list[set[str]] = []

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        # Decorators and defaults run at module scope; the body does not.
        for expr in (*node.decorator_list, *node.args.defaults, *node.args.kw_defaults):
            if expr is not None:
                self.visit(expr)

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

    def visit_Lambda(self, node: ast.Lambda) -> None:
        for expr in (*node.args.defaults, *node.args.kw_defaults):
            if expr is not None:
                self.visit(expr)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for expr in (*node.decorator_list, *node.bases, *(kw.value for kw in node.keywords)):
            self.visit(expr)

    def _comprehension(
        self, node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp
    ) -> None:
        self._comprehension_names.append(
            {
                name.id
                for generator in node.generators
                for name in ast.walk(generator.target)
                if isinstance(name, ast.Name)
            }
        )
        self.generic_visit(node)
        self._comprehension_names.pop()

    visit_ListComp = visit_SetComp = visit_DictComp = visit_GeneratorExp = _comprehension

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load) and not any(
            node.id in names for names in self._comprehension_names
        ):
            self.reads.add(node.id)


@functools.cache
def _global_reads(source: str) -> frozenset[str]:
    """Every name ``source`` reads as a module global.

    At module scope, any read of the name (:class:`_ModuleScopeReads`). In a
    function, lambda, comprehension or class body, only a read the symbol
    table resolves to the module global: a parameter or local variable of
    the same name, or a closure's free variable, is not one.
    """
    reads: set[str] = set()

    def scope(table: symtable.SymbolTable) -> None:
        reads.update(
            symbol.get_name()
            for symbol in table.get_symbols()
            if symbol.is_referenced() and symbol.is_global()
        )
        for child in table.get_children():
            scope(child)

    for child in symtable.symtable(source, "<module>", "exec").get_children():
        scope(child)
    module_scope = _ModuleScopeReads()
    module_scope.visit(ast.parse(source))
    return frozenset(reads | module_scope.reads)


def _unreached_readers(patched: str, name: str) -> list[str]:
    """The modules whose reads of ``name`` a patch of ``name`` on ``patched``
    never reaches: every module but ``patched`` that binds ``patched.name``'s
    object to ``name`` and reads it as a global (:func:`_global_reads`).

    A split module binds it if its own ``name`` is the same object (defined
    there, or imported); any other module under ``lemely/`` or ``scripts/``
    binds it by importing ``name`` from a split module.

    On a facade (``scan_limits``, ``_scan_common``) that is the whole rule:
    every such reader is a miss, even when the facade reads ``name`` too.
    On one of the three owning modules, patching the owner's own binding is
    the idiom for driving the owner's code, so the list is empty when the
    owner reads ``name`` as a global itself.
    """
    sentinel = object()
    target = getattr(_SCAN_MODULES[patched], name, sentinel)
    if target is sentinel:
        return []
    root = Path(scan_limits.__file__).resolve().parents[2]
    readers: list[str] = []
    for path in sorted([*(root / "lemely").rglob("*.py"), *(root / "scripts").rglob("*.py")]):
        module = path.relative_to(root).with_suffix("").as_posix().replace("/", ".")
        source = path.read_text(encoding="utf-8")
        if name not in source:
            continue
        reads = name in _global_reads(source)
        if module == patched:
            if reads and patched not in _FACADES:
                return []
            continue
        if module in _SCAN_MODULES:
            binds = getattr(_SCAN_MODULES[module], name, sentinel) is target
        else:
            binds = any(
                isinstance(node, ast.ImportFrom)
                and node.module in _SCAN_MODULES
                and getattr(_SCAN_MODULES[node.module], name, sentinel) is target
                and any(alias.name == name and alias.asname in (None, name) for alias in node.names)
                for node in ast.walk(ast.parse(source))
            )
        if reads and binds:
            readers.append(module)
    return readers


class SplitModuleTests(unittest.TestCase):
    """#262: ``scan_limits`` was split into ``_scan_common``, ``pdf_prescan``,
    ``pdf_content_walk`` and ``pdf_canonical`` as a pure move, and still
    re-exports every name its callers import from it."""

    _MODULES = (
        "lemely.io._scan_common",
        "lemely.io.pdf_prescan",
        "lemely.io.pdf_content_walk",
        "lemely.io.pdf_canonical",
        "lemely.io.scan_limits",
    )

    def test_every_name_in_all_imports_from_scan_limits(self) -> None:
        for name in scan_limits.__all__:
            with self.subTest(name=name):
                getattr(scan_limits, name)
        expected = {
            "check_pdf_content",
            "check_pdf_page_content",
            "check_pdf_content_bytes",
            "check_scan_bytes",
            "prescan_pdf",
            "PrescannedPdf",
            "check_object_stream_bytes",
            "open_checked_pdf",
            "canonical_pdf_bytes",
            "plan_pdf_pages",
            "plan_page_dpi",
            "plan_image",
            "decode_pixel_cap",
            "open_scan_image",
            "decoded_stream_size",
            "looks_like_pdf",
            "PagePlan",
            "MAX_SCAN_PAGES",
            "MAX_CROP_PAGES",
            "MAX_DECODE_PX",
            "MAX_DECODE_PX_GREY",
            "MAX_DECODE_PX_WEBP",
            "MAX_PAGE_PX",
            "MAX_SCAN_TOTAL_PX",
            "MAX_PAGE_CONTENT_BYTES",
            "MAX_SCAN_CONTENT_BYTES",
            "MAX_OBJECT_STREAM_BYTES",
            "MAX_PDF_OBJECTS",
            "MAX_PRESCAN_TOKENS",
            "MIN_EXTRACTION_DPI",
            "EXTRACTION_DPI",
            "PDF_MAGIC",
            "SCAN_IMAGE_FORMATS",
            "GREY_CEILING_MODES",
            "ScanRejectedError",
            "ScanTooLargeError",
            "ScanUnsupportedEncodingError",
            "ScanUnsupportedFormatError",
        }
        self.assertEqual(expected - set(scan_limits.__all__), set())

    #: Each module, imported first, and the scan modules that import loads: the
    #: import direction (``_scan_common`` is the leaf, ``pdf_prescan`` and
    #: ``pdf_content_walk`` sit on it alone, ``pdf_canonical`` on those three,
    #: ``scan_limits`` on all four).
    _LOADS: ClassVar[dict[str, set[str]]] = {
        "lemely.io._scan_common": {"lemely.io._scan_common"},
        "lemely.io.pdf_prescan": {"lemely.io._scan_common", "lemely.io.pdf_prescan"},
        "lemely.io.pdf_content_walk": {"lemely.io._scan_common", "lemely.io.pdf_content_walk"},
        "lemely.io.pdf_canonical": {
            "lemely.io._scan_common",
            "lemely.io.pdf_prescan",
            "lemely.io.pdf_content_walk",
            "lemely.io.pdf_canonical",
        },
        "lemely.io.scan_limits": set(_MODULES),
    }

    #: Run in a fresh interpreter: argv is the repo root, the module to import
    #: first, the scan modules that import must load, and the five scan modules
    #: (comma-joined). Only the scan modules are compared, so another
    #: ``lemely.io`` module a scan module comes to import does not trip it.
    _CHILD = textwrap.dedent(
        """
        import importlib, sys
        from pathlib import Path

        root, first = Path(sys.argv[1]), sys.argv[2]
        expected, scan = set(sys.argv[3].split(",")), set(sys.argv[4].split(","))
        module = importlib.import_module(first)
        assert Path(module.__file__).resolve().is_relative_to(root), module.__file__
        loaded = scan.intersection(sys.modules)
        assert loaded == expected, f"{first} loaded {sorted(loaded)}"
        import lemely.io.scan_limits as s
        s.open_checked_pdf; s.check_pdf_content; s.MAX_SCAN_PAGES
        """
    )

    def test_the_split_modules_import_in_any_order(self) -> None:
        """Each module imported first, in a fresh interpreter run from this
        repo's root: it resolves to this checkout (the shared venv's editable
        install may point at another), loads exactly the scan modules the
        import direction allows, and leaves ``scan_limits`` importable after
        it -- no cycle."""
        self.assertEqual(set(self._LOADS), set(self._MODULES))
        root = Path(__file__).resolve().parents[1]
        for module, loads in self._LOADS.items():
            with self.subTest(module=module):
                result = subprocess.run(  # noqa: S603 -- our own interpreter, a fixed script
                    [
                        sys.executable,
                        "-c",
                        self._CHILD,
                        str(root),
                        module,
                        ",".join(loads),
                        ",".join(self._MODULES),
                    ],
                    cwd=root,
                    env={**os.environ, "PYTHONPATH": str(root)},
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_moved_names_are_the_same_objects(self) -> None:
        self.assertIs(scan_limits.check_pdf_content, pdf_content_walk.check_pdf_content)
        self.assertIs(scan_limits.open_checked_pdf, pdf_canonical.open_checked_pdf)
        self.assertIs(scan_limits.prescan_pdf, pdf_prescan.prescan_pdf)
        self.assertIs(scan_limits.canonical_pdf_bytes, pdf_canonical.canonical_pdf_bytes)
        self.assertIs(scan_limits.ScanRejectedError, _scan_common.ScanRejectedError)

    def test_the_patch_finder_sees_a_patch_that_misses_its_reader(self) -> None:
        """The sweep below, held to known cases. Flagged, each with the
        reader the patch never reaches: ``_page_tree`` patched on
        ``scan_limits`` (``pdf_content_walk`` defines and calls it), by
        position or by keyword; ``_MAX_OBJECTS_PER_PAGE`` patched on
        ``_scan_common`` (``pdf_content_walk`` binds and reads its own);
        ``MAX_SCAN_PAGES`` patched on ``_scan_common``, which reads it too
        but is a facade, so ``pdf_content_walk``'s own binding still counts;
        and ``check_pdf_content`` patched on ``pdf_content_walk``, an owner
        that never calls it, while ``pdf_canonical`` calls its own binding.
        Found with no name, so counted as misses: an attribute that is not a
        string literal, and ``patch.multiple`` given ``**kwargs``. Not
        flagged: a patch on the owning module (``pdf_content_walk._page_tree``);
        one on a name only its own module reads (``MAX_SCAN_TOTAL_PX``, read
        by ``plan_pdf_pages`` in ``_scan_common``); and one on an owning
        module's own binding that the owner reads as a global
        (``pdf_prescan.MAX_OBJECT_STREAM_BYTES``, read by
        ``check_object_stream_bytes``), the idiom for driving the owner."""
        source = textwrap.dedent(
            """
            import lemely.io.scan_limits as limits
            from lemely.io import _scan_common, pdf_content_walk, pdf_prescan
            patch.object(limits, "_page_tree")
            patch("lemely.io._scan_common._MAX_OBJECTS_PER_PAGE", 5)
            patch.object(pdf_content_walk, "_page_tree")
            patch.object(_scan_common, "MAX_SCAN_TOTAL_PX", 40_000)
            patch.object(target=limits, attribute="_parent")
            monkeypatch.setattr(limits, name="_collection_refs", value=None)
            patch.object(pdf_content_walk, "check_pdf_content")
            patch.object(pdf_prescan, "MAX_OBJECT_STREAM_BYTES", 1)
            patch.object(_scan_common, "MAX_SCAN_PAGES", 1)
            patch.object(pdf_content_walk, attribute)
            patch.multiple(limits, **overrides)
            """
        )
        common, walk = "lemely.io._scan_common", "lemely.io.pdf_content_walk"
        limits, prescan = "lemely.io.scan_limits", "lemely.io.pdf_prescan"
        patched = _scan_module_patches(source)
        self.assertEqual(
            patched,
            [
                (4, limits, "_page_tree"),
                (5, common, "_MAX_OBJECTS_PER_PAGE"),
                (6, walk, "_page_tree"),
                (7, common, "MAX_SCAN_TOTAL_PX"),
                (8, limits, "_parent"),
                (9, limits, "_collection_refs"),
                (10, walk, "check_pdf_content"),
                (11, prescan, "MAX_OBJECT_STREAM_BYTES"),
                (12, common, "MAX_SCAN_PAGES"),
                (13, walk, None),
                (14, limits, None),
            ],
        )
        readers = {line: _unreached_readers(module, name) for line, module, name in patched if name}
        self.assertEqual(
            {line: found for line, found in readers.items() if line not in (10, 12)},
            {4: [walk], 5: [walk], 6: [], 7: [], 8: [walk], 9: [walk], 11: []},
        )
        self.assertIn("lemely.io.pdf_canonical", readers[10])
        self.assertIn(walk, readers[12])
        self.assertIn("MAX_SCAN_PAGES", _global_reads(Path(_scan_common.__file__).read_text()))

    def test_a_local_of_the_same_name_is_not_a_global_read(self) -> None:
        """What counts as reading a name, for the sweep: a read the symbol
        table resolves to the module global, in any function, lambda or
        class body, or any read at module scope. A parameter, a local
        variable, a closure's free variable or a comprehension's loop
        variable of the same name is not one, so an owner that only shadows
        the name never excuses a patch of its global."""
        source = textwrap.dedent(
            """
            def parameter(SHADOWED_ARG):
                return SHADOWED_ARG

            def local():
                SHADOWED_LOCAL = 1
                return SHADOWED_LOCAL

            def outer():
                FREE = 1
                def inner():
                    return FREE + GLOBAL_IN_CLOSURE
                return inner

            def function():
                return GLOBAL_IN_FUNCTION

            class Holder:
                value = GLOBAL_IN_CLASS

            squares = [LOOP for LOOP in GLOBAL_ITERABLE]
            GLOBAL_AT_MODULE
            """
        )
        self.assertEqual(
            _global_reads(source),
            {
                "GLOBAL_IN_CLOSURE",
                "GLOBAL_IN_FUNCTION",
                "GLOBAL_IN_CLASS",
                "GLOBAL_ITERABLE",
                "GLOBAL_AT_MODULE",
            },
        )

    def test_no_test_patches_a_name_where_its_reader_cannot_see_it(self) -> None:
        """#262: ``patch.object(scan_limits, name)`` replaces ``scan_limits``'s
        attribute only, so it never reaches a module that bound ``name`` for
        itself -- the module that defines it, or one that imported it from a
        scan module. Such a patch would leave the code it targets running
        unpatched, and an ``assert_not_called`` on it would pass vacuously.
        No test anywhere patches a name on any of the five split modules
        that another module binds and reads, and every such patch spells its
        attribute out, so the sweep can check it."""
        tests = Path(__file__).resolve().parent
        misses = []
        for path in sorted(tests.rglob("*.py")):
            for line, module, name in _scan_module_patches(path.read_text(encoding="utf-8")):
                where = f"{path.relative_to(tests)}:{line} patches {module}"
                if name is None:
                    misses.append(f"{where} with an attribute that is not a string literal")
                elif readers := _unreached_readers(module, name):
                    misses.append(f"{where}.{name}, read by {', '.join(readers)}")
        self.assertEqual(misses, [])


if __name__ == "__main__":
    unittest.main()
