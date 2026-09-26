"""Unit tests for lemely.io.reread (I1 crop-and-re-read step)."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from PIL import Image

from lemely.core.schemas import ExtractedAnswer, SourceBox
from lemely.io.gemini import GeminiClient
from lemely.io.rasterise import RasterisedPage
from lemely.io.reread import (
    REREAD_MEDIA_RESOLUTION,
    Rereader,
    crop_and_upscale,
    padded_crop_rect,
    should_reread,
)
from lemely.runtime.config import PathsSettings, load_settings


def _page(width: int = 1000, height: int = 1000) -> RasterisedPage:
    image = Image.new("RGB", (width, height), color="white")
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return RasterisedPage(index=0, width=width, height=height, png_bytes=buf.getvalue())


class ShouldRereadTests(unittest.TestCase):
    def test_no_box_never_triggers(self) -> None:
        answer = ExtractedAnswer(question_id="1", answer="x", confidence=0.1, source_box=None)
        self.assertFalse(should_reread(answer))

    def test_low_confidence_with_box_triggers(self) -> None:
        answer = ExtractedAnswer(
            question_id="1",
            answer="x",
            confidence=0.1,
            source_box=SourceBox(page=0, box=[0, 0, 100, 100]),
        )
        self.assertTrue(should_reread(answer))

    def test_high_confidence_with_box_does_not_trigger(self) -> None:
        answer = ExtractedAnswer(
            question_id="1",
            answer="x",
            confidence=0.95,
            source_box=SourceBox(page=0, box=[0, 0, 100, 100]),
        )
        self.assertFalse(should_reread(answer))

    def test_custom_threshold_is_respected(self) -> None:
        answer = ExtractedAnswer(
            question_id="1",
            answer="x",
            confidence=0.7,
            source_box=SourceBox(page=0, box=[0, 0, 100, 100]),
        )
        self.assertFalse(should_reread(answer, confidence_threshold=0.6))
        self.assertTrue(should_reread(answer, confidence_threshold=0.8))


class CropAndUpscaleTests(unittest.TestCase):
    def test_output_is_upscaled_by_the_configured_factor(self) -> None:
        page = _page(1000, 1000)
        box = [100, 100, 300, 400]  # 0-1000 scale on a 1000x1000 page == exact px box
        png = crop_and_upscale(page, box, padding_frac=0.0, upscale=2)
        image = Image.open(io.BytesIO(png))
        # 300-100=200 tall, 400-100=300 wide, x2 upscale.
        self.assertEqual(image.height, 400)
        self.assertEqual(image.width, 600)

    def test_padding_expands_the_crop(self) -> None:
        page = _page(1000, 1000)
        box = [100, 100, 300, 400]
        no_pad = Image.open(io.BytesIO(crop_and_upscale(page, box, padding_frac=0.0, upscale=1)))
        padded = Image.open(io.BytesIO(crop_and_upscale(page, box, padding_frac=0.08, upscale=1)))
        self.assertGreater(padded.width, no_pad.width)
        self.assertGreater(padded.height, no_pad.height)

    def test_crop_near_the_edge_is_clamped_not_out_of_bounds(self) -> None:
        page = _page(1000, 1000)
        box = [0, 0, 50, 50]  # top-left corner, padding would go negative without clamping
        png = crop_and_upscale(page, box, padding_frac=0.5, upscale=1)
        image = Image.open(io.BytesIO(png))
        self.assertGreater(image.width, 0)
        self.assertGreater(image.height, 0)

    def test_tiny_box_produces_a_non_degenerate_crop(self) -> None:
        page = _page(1000, 1000)
        box = [500, 500, 501, 501]  # smallest legal SourceBox area
        png = crop_and_upscale(page, box, padding_frac=0.0, upscale=1)
        image = Image.open(io.BytesIO(png))
        self.assertGreaterEqual(image.width, 1)
        self.assertGreaterEqual(image.height, 1)

    def test_default_arguments_use_the_shipped_upscale_and_padding(self) -> None:
        """I1 review should-fix 6: the tests above all pass ``upscale``/
        ``padding_frac`` explicitly, so they verify the parameter plumbing
        but never the shipped ``REREAD_UPSCALE``/``REREAD_PADDING_FRAC``
        defaults the production call path actually uses -- a mutation to
        either constant broke zero tests. Exercise the default path with no
        keyword overrides and pin the exact resulting dimensions."""
        page = _page(1000, 1000)
        box = [100, 100, 300, 400]  # 200 tall x 300 wide on a 1000x1000 page
        png = crop_and_upscale(page, box)
        image = Image.open(io.BytesIO(png))
        # 8% padding: +16 (200*0.08) tall, +24 (300*0.08) wide -> 232x348;
        # then 2x upscale -> 464x696.
        self.assertEqual(image.width, 696)
        self.assertEqual(image.height, 464)


class PaddedCropRectTests(unittest.TestCase):
    """The rectangle arithmetic, shared with the review crop route."""

    def test_pins_the_padded_rectangle(self) -> None:
        # 8% of 200 tall is 16, 8% of 300 wide is 24; floored low, rounded high.
        self.assertEqual(padded_crop_rect(1000, 1000, [100, 100, 300, 400]), (76, 84, 424, 316))

    def test_is_the_rectangle_crop_and_upscale_crops(self) -> None:
        """The route crops with this helper instead of calling ``crop_and_upscale``
        on the whole page, so the two must choose the same pixels."""
        for width, height, box in (
            (1000, 1000, [100, 100, 300, 400]),
            (1241, 1754, [0, 0, 1000, 1000]),
            (600, 300, [37, 911, 38, 912]),
            (333, 777, [480, 10, 990, 620]),
        ):
            page = _page(width, height)
            image = Image.open(io.BytesIO(crop_and_upscale(page, box, upscale=1)))
            left, upper, right, lower = padded_crop_rect(width, height, box)
            self.assertEqual((image.width, image.height), (right - left, lower - upper), box)
            self.assertGreaterEqual(left, 0)
            self.assertGreaterEqual(upper, 0)
            self.assertLessEqual(right, width)
            self.assertLessEqual(lower, height)


def _client_returning(tmp: str, answer_text: str) -> tuple[GeminiClient, MagicMock]:
    mock_genai = MagicMock()
    resp = MagicMock(
        text=json.dumps({"answer": answer_text}),
        candidates=[MagicMock(finish_reason=MagicMock(__str__=lambda s: "STOP"))],
        usage_metadata=MagicMock(prompt_token_count=5, candidates_token_count=10),
    )
    mock_genai.models.generate_content.return_value = resp
    import os

    snap = dict(os.environ)
    for k in list(os.environ):
        if k.startswith("LEMELY_"):
            del os.environ[k]
    try:
        settings = load_settings(toml_path=None, cwd=Path(tmp))
    finally:
        os.environ.clear()
        os.environ.update(snap)
    settings = settings.model_copy(
        update={
            "paths": PathsSettings(
                cache_dir=Path(tmp) / ".cache",
                output_dir=Path(tmp) / "outputs",
            )
        }
    )
    return GeminiClient(settings, _genai_client=mock_genai), mock_genai


class RereaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()

    def test_reread_populates_answer_reread_and_agreement(self) -> None:
        client, _ = _client_returning(self.tmp, "42 m/s")
        rereader = Rereader(client)
        page = _page()
        answer = ExtractedAnswer(
            question_id="3(b)",
            answer="42 m/s",
            confidence=0.3,
            source_box=SourceBox(page=0, box=[100, 100, 300, 400]),
        )

        result = rereader.reread(answer, [page], extra_cache_key="manifest-abc")

        self.assertEqual(result.answer_reread, "42 m/s")
        self.assertIsNotNone(result.reread_agreement)
        assert result.reread_agreement is not None
        self.assertAlmostEqual(result.reread_agreement, 1.0)

    def test_reread_sends_high_media_resolution_on_the_crop_part(self) -> None:
        client, mock_genai = _client_returning(self.tmp, "20 m/s")
        rereader = Rereader(client)
        page = _page()
        answer = ExtractedAnswer(
            question_id="1(b)",
            answer="19.6 N",
            confidence=0.2,
            source_box=SourceBox(page=0, box=[100, 100, 300, 400]),
        )

        rereader.reread(answer, [page], extra_cache_key="manifest-xyz")

        contents = mock_genai.models.generate_content.call_args.kwargs["contents"]
        image_parts = [p for p in contents if hasattr(p, "media_resolution")]
        self.assertEqual(len(image_parts), 1)
        self.assertIsNotNone(image_parts[0].media_resolution)
        # I1 review round 2, should-fix 6: asserting against
        # REREAD_MEDIA_RESOLUTION itself is self-referential -- it passes for
        # any value the constant happens to hold (mutating "high" to "low"
        # broke zero tests). "high" is an explicit plan requirement for the
        # re-read crop (medium is used for the primary whole-page call);
        # hardcode the expected value.
        self.assertEqual(REREAD_MEDIA_RESOLUTION, "high")
        self.assertEqual(
            str(image_parts[0].media_resolution.level).upper().rsplit(".", 1)[-1],
            "MEDIA_RESOLUTION_HIGH",
        )

    def test_reread_without_a_box_raises(self) -> None:
        client, _ = _client_returning(self.tmp, "x")
        rereader = Rereader(client)
        answer = ExtractedAnswer(question_id="1", answer="x", confidence=0.1, source_box=None)
        with self.assertRaises(ValueError):
            rereader.reread(answer, [_page()], extra_cache_key="k")


if __name__ == "__main__":
    unittest.main()
