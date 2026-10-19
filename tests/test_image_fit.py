"""Spec 2026-10-19 §2: greyscale, enhancement, token and byte budgets, floor, real-size fixture."""

from __future__ import annotations

import functools
import io
import random
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from lemely.io.llm import image_fit
from lemely.io.llm.image_fit import (
    DEFAULT_BYTE_LIMIT,
    DEFAULT_TOKEN_BUDGET,
    IMG_FIT_VERSION,
    IMG_FIT_VERSION_PLAIN,
    enhance_page,
    estimate_tokens,
    fit,
    img_fit_version,
    steps_for,
    thumbnails,
)
from lemely.io.providers import ProviderError

_REAL_W, _REAL_H = 2430, 3439
#: Paper noise levels per channel; calibrated in Task 2a step 6 against the real script.
_NOISE_LEVELS = 7


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _page(width: int, height: int, *, inks: tuple[tuple[int, int, int], ...] = ()) -> bytes:
    """A white RGB page with a thick stroke in each ink colour."""
    img = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    for i, ink in enumerate(inks):
        top = height // 4 + i * height // 4
        draw.rectangle([width // 10, top, width * 9 // 10, top + height // 20], fill=ink)
    return _png(img)


@functools.lru_cache(maxsize=1)
def _realistic_page() -> bytes:
    """One 2430x3439 RGB scan page: noisy near-white paper and 40 lines of blue writing."""
    rng = random.Random(41)
    noise = np.random.default_rng(41).integers(
        255 - _NOISE_LEVELS, 255, (_REAL_H, _REAL_W, 3), dtype=np.uint8
    )
    page = Image.fromarray(noise, "RGB")
    draw = ImageDraw.Draw(page)
    for line in range(40):
        y = 300 + line * 75
        for x in range(200, 2200, 9):
            draw.line(
                [(x, y + rng.randint(-12, 12)), (x + 9, y + rng.randint(-12, 12))],
                fill=(30, 40, 140),
                width=3,
            )
    return _png(page)


def _grey_with_lines(
    width: int, height: int, *, paper: tuple[int, int], ink: int, rows: tuple[int, ...]
) -> Image.Image:
    """A grey page shaded left to right from ``paper[0]`` to ``paper[1]``, with 3 px strokes."""
    shade = np.linspace(paper[0], paper[1], width).round().astype(np.uint8)
    img = Image.fromarray(np.tile(shade, (height, 1)), "L")
    draw = ImageDraw.Draw(img)
    for y in rows:
        draw.line([(width // 8, y), (width * 7 // 8, y)], fill=ink, width=3)
    return img


def _mean(img: Image.Image, box: tuple[int, int, int, int]) -> float:
    return float(np.asarray(img.crop(box)).mean())


def _stdev(img: Image.Image, box: tuple[int, int, int, int]) -> float:
    return float(np.asarray(img.crop(box)).std())


class EnhanceTests(unittest.TestCase):
    _W, _H = 800, 1000
    _ROWS = tuple(range(150, 900, 60))

    def test_faint_pencil_keeps_or_gains_contrast_and_is_not_clipped_to_white(self) -> None:
        page = _grey_with_lines(self._W, self._H, paper=(225, 225), ink=185, rows=self._ROWS)
        out = enhance_page(page)
        stroke_after = _mean(out, (400, 149, 420, 152))
        paper_after = _mean(out, (400, 160, 420, 180))
        # Flattening alone lifts the paper to 255 and gives a contrast of about 45; the
        # levels stretch is what doubles it.
        self.assertGreaterEqual(paper_after - stroke_after, 2 * (225 - 185))
        self.assertLess(stroke_after, 120)

    def test_dark_ink_stays_dark_and_paper_goes_white(self) -> None:
        page = _grey_with_lines(self._W, self._H, paper=(230, 230), ink=30, rows=self._ROWS)
        out = enhance_page(page)
        self.assertLess(_mean(out, (400, 149, 420, 152)), 60)
        self.assertGreater(_mean(out, (400, 160, 420, 180)), 245)

    def test_shaded_paper_is_flattened(self) -> None:
        """A left-to-right shading from 150 to 250 loses most of its spread."""
        page = _grey_with_lines(
            self._W,
            self._H,
            paper=(150, 250),
            ink=40,
            rows=self._ROWS,
        )
        band = (0, 160, self._W, 200)
        self.assertGreater(_stdev(page, band), 25)
        self.assertLess(_stdev(enhance_page(page), band), 6)

    def test_edges_are_sharpened(self) -> None:
        """A soft-edged band gets a steeper edge than with the unsharp mask turned off."""
        band = Image.new("L", (self._W, self._H), 230)
        ImageDraw.Draw(band).rectangle([200, 300, 600, 700], fill=40)
        soft = band.filter(ImageFilter.GaussianBlur(2))

        def steepest(img: Image.Image) -> int:
            row = np.asarray(img, dtype=np.int16)[500]
            return int(np.abs(np.diff(row)).max())

        with patch.object(image_fit, "_SHARPEN_PERCENT", 0):
            unsharpened = steepest(enhance_page(soft))
        self.assertGreater(steepest(enhance_page(soft)), unsharpened)

    def test_blank_noisy_paper_is_not_stretched_into_writing(self) -> None:
        noise = np.random.default_rng(3).integers(232, 239, (self._H, self._W), dtype=np.uint8)
        out = enhance_page(Image.fromarray(noise, "L"))
        self.assertGreater(int(np.asarray(out).min()), 225)
        self.assertLess(_stdev(out, (0, 0, self._W, self._H)), 5)

    def test_enhancement_is_deterministic(self) -> None:
        page = _grey_with_lines(self._W, self._H, paper=(200, 200), ink=60, rows=self._ROWS)
        self.assertEqual(enhance_page(page).tobytes(), enhance_page(page).tobytes())

    def test_enhanced_pages_differ_from_plain_ones(self) -> None:
        page = _png(_grey_with_lines(400, 500, paper=(220, 220), ink=60, rows=(100, 200)))
        plain = fit([page], enhance=False).images[0]
        self.assertNotEqual(fit([page]).images[0], plain)
        with Image.open(io.BytesIO(plain)) as img:
            self.assertEqual(img.getpixel((10, 10)), 220)

    def test_cache_version_differs_between_variants(self) -> None:
        self.assertEqual(img_fit_version(), IMG_FIT_VERSION)
        self.assertEqual(img_fit_version(enhance=False), IMG_FIT_VERSION_PLAIN)
        self.assertEqual(IMG_FIT_VERSION, "v2")
        self.assertNotEqual(IMG_FIT_VERSION, IMG_FIT_VERSION_PLAIN)


class GreyscaleTests(unittest.TestCase):
    def test_every_mode_is_sent_as_greyscale(self) -> None:
        fills: tuple[tuple[str, float | tuple[float, ...]], ...] = (
            ("L", 200),
            ("RGB", (200, 10, 10)),
            ("1", 1),
            ("P", 3),
            ("LA", (200, 255)),
            ("RGBA", (200, 10, 10, 255)),
        )
        for mode, fill in fills:
            with self.subTest(mode=mode):
                fitted = fit([_png(Image.new(mode, (40, 40), fill))])
                with Image.open(io.BytesIO(fitted.images[0])) as sent:
                    self.assertEqual(sent.mode, "L")

    def test_transparent_pages_are_composited_onto_white(self) -> None:
        for mode, clear in (("LA", (0, 0)), ("RGBA", (0, 0, 0, 0))):
            with self.subTest(mode=mode):
                fitted = fit([_png(Image.new(mode, (40, 40), clear))])
                with Image.open(io.BytesIO(fitted.images[0])) as sent:
                    self.assertEqual(sent.mode, "L")
                    self.assertEqual(sent.getpixel((20, 20)), 255)

    def test_png_with_a_transparency_key_is_composited_onto_white(self) -> None:
        for mode, key in (("RGB", (0, 0, 0)), ("L", 0)):
            with self.subTest(mode=mode):
                buf = io.BytesIO()
                Image.new(mode, (40, 40), key).save(buf, "PNG", transparency=key)
                fitted = fit([buf.getvalue()], enhance=False)
                with Image.open(io.BytesIO(fitted.images[0])) as sent:
                    self.assertEqual(sent.getpixel((20, 20)), 255)

    def test_colour_is_not_kept(self) -> None:
        fitted = fit([_page(800, 1100, inks=((30, 40, 140), (200, 20, 20)))])
        with Image.open(io.BytesIO(fitted.images[0])) as sent:
            self.assertEqual(sent.mode, "L")


class BudgetTests(unittest.TestCase):
    def test_estimate_is_area_over_750_rounded_up(self) -> None:
        self.assertEqual(estimate_tokens(750, 1), 1)
        self.assertEqual(estimate_tokens(751, 1), 2)

    def test_steps(self) -> None:
        self.assertEqual(steps_for(1568, 19), (2576, 2200, 2000, 1800, 1568))
        self.assertEqual(steps_for(1568, 21), (2000, 1800, 1568))
        self.assertEqual(steps_for(1900, 19), (2576, 2200, 2000, 1900))

    def test_nineteen_real_size_pages_step_down_to_2200(self) -> None:
        """2576: 19 x 6252 = 118,788 tokens, over 95k. 2200: 19 x 4559 = 86,621, under."""
        with patch.object(image_fit, "_encode", wraps=image_fit._encode) as encode:
            fitted = fit([_page(_REAL_W, _REAL_H, inks=((30, 40, 140),))] * 19)
        self.assertEqual(encode.call_count, 19, "2576 is skipped on tokens alone, never encoded")
        self.assertEqual(fitted.long_edge, 2200)
        self.assertLessEqual(fitted.est_tokens, DEFAULT_TOKEN_BUDGET)
        self.assertFalse(fitted.over_token_budget)
        self.assertEqual(len(fitted.page_tokens), 19)
        self.assertEqual(sum(fitted.page_tokens), fitted.est_tokens)

    def test_forty_five_pages_are_over_the_budget_at_the_floor(self) -> None:
        fitted = fit([_page(_REAL_W, _REAL_H)] * 45)
        self.assertEqual(fitted.long_edge, 1568)
        self.assertTrue(fitted.over_token_budget)
        self.assertFalse(fitted.over_byte_limit)

    def test_byte_limit_at_the_floor_is_reported_not_raised(self) -> None:
        fitted = fit([_page(1000, 1400)] * 3, byte_limit=100)
        self.assertTrue(fitted.over_byte_limit)
        self.assertEqual(fitted.long_edge, 1568)

    def test_a_step_over_the_byte_limit_stops_encoding_its_pages(self) -> None:
        """Once page 1 is over the limit, pages 2..n cannot bring that step back under."""
        with patch.object(image_fit, "_encode", wraps=image_fit._encode) as encode:
            fitted = fit([_page(1000, 1400)] * 4, byte_limit=100)
        # Five steps: the first four stop after one page each, the floor encodes all four.
        self.assertEqual(encode.call_count, 4 * 1 + 4)
        self.assertEqual(len(fitted.images), 4)
        self.assertTrue(fitted.over_byte_limit)

    def test_no_byte_limit_for_file_uploads(self) -> None:
        self.assertFalse(fit([_page(1000, 1400)], byte_limit=None).over_byte_limit)

    def test_order_is_kept(self) -> None:
        a, b = _png(Image.new("L", (10, 10), 0)), _png(Image.new("L", (12, 10), 255))
        self.assertEqual(fit([a, b]).images, (a, b))

    def test_fit_is_deterministic(self) -> None:
        pages = [_page(_REAL_W, _REAL_H, inks=((30, 40, 140),))] * 2
        self.assertEqual(fit(pages).images, fit(pages).images)


class ErrorTests(unittest.TestCase):
    def test_unreadable_page_names_its_number(self) -> None:
        good = _png(Image.new("L", (10, 10), 0))
        with self.assertRaisesRegex(ProviderError, "page 2"):
            fit([good, b"\x89PNG\r\n\x1a\n-truncated"])

    def test_encode_error_is_a_provider_error_naming_the_page(self) -> None:
        big = _page(3000, 3000)
        with (
            patch.object(Image.Image, "save", side_effect=OSError("disk")),
            self.assertRaisesRegex(ProviderError, "page 1 could not be encoded"),
        ):
            fit([big])


class ThumbnailTests(unittest.TestCase):
    def test_thumbnails_are_greyscale_at_768(self) -> None:
        (thumb,) = thumbnails([_page(_REAL_W, _REAL_H, inks=((30, 40, 140), (200, 20, 20)))])
        with Image.open(io.BytesIO(thumb)) as img:
            self.assertEqual(img.mode, "L")
            self.assertEqual(max(img.size), 768)

    def test_thumbnails_are_enhanced_unless_asked_not_to(self) -> None:
        page = _png(_grey_with_lines(400, 500, paper=(220, 220), ink=60, rows=(100, 200)))
        self.assertNotEqual(
            thumbnails([page], long_edge=300), thumbnails([page], long_edge=300, enhance=False)
        )


class RealisticFixtureTests(unittest.TestCase):
    """Spec §7: 19 pages at 2430x3439, noisy RGB, fit under both limits at or above the floor."""

    def test_nineteen_noisy_pages_fit_under_both_limits(self) -> None:
        fitted = fit([_realistic_page()] * 19)
        self.assertGreaterEqual(fitted.long_edge, 1568)
        self.assertLessEqual(fitted.base64_bytes, DEFAULT_BYTE_LIMIT)
        self.assertLessEqual(fitted.est_tokens, DEFAULT_TOKEN_BUDGET)
        self.assertFalse(fitted.over_byte_limit or fitted.over_token_budget)

    def test_the_fixture_is_at_least_as_hard_as_the_real_scan(self) -> None:
        """Its 2576-edge RGB page is no smaller than the real script's (Task 2a step 6)."""
        with Image.open(io.BytesIO(_realistic_page())) as img:
            scale = 2576 / max(img.size)
            size = (round(img.width * scale), round(img.height * scale))
            rgb = _png(img.resize(size, Image.Resampling.LANCZOS))
        self.assertGreaterEqual(image_fit.base64_len(len(rgb)), _REAL_SCAN_B64_PER_PAGE)


#: Median base64 bytes of one real-script page at 2576 px RGB, measured in step 6.
_REAL_SCAN_B64_PER_PAGE = 4_050_000
