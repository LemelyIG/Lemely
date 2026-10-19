"""Spec 2026-10-19 §2: greyscale, token and byte budgets, floor, and a real-size fixture."""

from __future__ import annotations

import functools
import io
import random
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

from lemely.io.llm import image_fit
from lemely.io.llm.image_fit import (
    DEFAULT_BYTE_LIMIT,
    DEFAULT_TOKEN_BUDGET,
    estimate_tokens,
    fit,
    has_colour_ink,
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
    channels = [
        Image.frombytes("L", (_REAL_W, _REAL_H), rng.randbytes(_REAL_W * _REAL_H)).point(
            lambda v: 255 - _NOISE_LEVELS + v % _NOISE_LEVELS
        )
        for _ in range(3)
    ]
    page = Image.merge("RGB", channels)
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


class ColourTests(unittest.TestCase):
    def test_one_ink_is_not_meaningful_colour(self) -> None:
        img = Image.open(io.BytesIO(_page(800, 1100, inks=((30, 40, 140),))))
        self.assertFalse(has_colour_ink(img.convert("RGB")))

    def test_two_inks_are_meaningful_colour(self) -> None:
        img = Image.open(io.BytesIO(_page(800, 1100, inks=((30, 40, 140), (200, 20, 20)))))
        self.assertTrue(has_colour_ink(img.convert("RGB")))

    def test_single_ink_page_is_sent_greyscale(self) -> None:
        fitted = fit([_page(800, 1100, inks=((30, 40, 140),))])
        with Image.open(io.BytesIO(fitted.images[0])) as sent:
            self.assertEqual(sent.mode, "L")
        self.assertEqual(fitted.colour_pages, ())

    def test_two_ink_page_keeps_its_colour(self) -> None:
        fitted = fit([_page(800, 1100), _page(800, 1100, inks=((30, 40, 140), (200, 20, 20)))])
        with Image.open(io.BytesIO(fitted.images[1])) as sent:
            self.assertEqual(sent.mode, "RGB")
        self.assertEqual(fitted.colour_pages, (2,))

    def test_greyscale_png_within_the_edge_is_sent_byte_for_byte(self) -> None:
        grey = _png(Image.new("L", (300, 400), 200))
        self.assertEqual(fit([grey]).images, (grey,))


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
        fitted = fit([_page(_REAL_W, _REAL_H, inks=((30, 40, 140),))] * 19)
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


class RealisticFixtureTests(unittest.TestCase):
    """Spec §7: 19 pages at 2430x3439, noisy RGB, fit under both limits at or above the floor."""

    def test_nineteen_noisy_pages_fit_under_both_limits(self) -> None:
        fitted = fit([_realistic_page()] * 19)
        self.assertGreaterEqual(fitted.long_edge, 1568)
        self.assertLessEqual(fitted.base64_bytes, DEFAULT_BYTE_LIMIT)
        self.assertLessEqual(fitted.est_tokens, DEFAULT_TOKEN_BUDGET)
        self.assertFalse(fitted.over_byte_limit or fitted.over_token_budget)
        self.assertEqual(fitted.colour_pages, ())

    def test_the_fixture_is_at_least_as_hard_as_the_real_scan(self) -> None:
        """Its 2576-edge RGB page is no smaller than the real script's (Task 2a step 6)."""
        with Image.open(io.BytesIO(_realistic_page())) as img:
            scale = 2576 / max(img.size)
            size = (round(img.width * scale), round(img.height * scale))
            rgb = _png(img.resize(size, Image.Resampling.LANCZOS))
        self.assertGreaterEqual(image_fit.base64_len(len(rgb)), _REAL_SCAN_B64_PER_PAGE)


#: Median base64 bytes of one real-script page at 2576 px RGB, measured in step 6.
_REAL_SCAN_B64_PER_PAGE = 4_050_000
