"""Spec 2026-10-19 §2 on the Claude path: fit, refusal at the floor, tier warning,
preflight, output cap and the img_fit cache-key version."""

from __future__ import annotations

import io
import tempfile
import unittest
from datetime import date
from typing import Any
from unittest.mock import patch

from PIL import Image, ImageDraw
from structlog.testing import capture_logs

from lemely.core.schemas import AIMarkResponse
from lemely.io.gemini import GeminiClient, _reset_process_counters, record_calls
from lemely.io.llm import image_fit
from lemely.io.providers import ProviderError
from tests.test_anthropic_adapter import (
    _VALID_MARK,
    _FakeAnthropic,
    _message,
    _sent_images,
    _settings,
)

_HAIKU = "claude-haiku-5-5"


def _scan_page(width: int = 2430, height: int = 3439) -> bytes:
    img = Image.new("RGB", (width, height), (255, 255, 255))
    ImageDraw.Draw(img).rectangle([200, 400, 2000, 500], fill=(30, 40, 140))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.enterContext(record_calls())
        _reset_process_counters()
        today = patch("lemely.io.gemini._today", lambda: date(2026, 10, 19))
        today.start()
        self.addCleanup(today.stop)

    def _client(self, *outcomes: object, **gemini: Any) -> tuple[GeminiClient, _FakeAnthropic]:
        settings = _settings(self.tmp)
        if gemini:
            settings = settings.model_copy(
                update={"gemini": settings.gemini.model_copy(update=gemini)}
            )
        fake = _FakeAnthropic(*outcomes)
        return (
            GeminiClient(settings, _genai_client=object(), _anthropic_client=fake, ledger=None),
            fake,
        )

    def _read(
        self, client: GeminiClient, pages: list[bytes], tag: str = "binding_second_read"
    ) -> None:
        client.generate_structured(
            system_prompt="sys",
            user_prompt="read",
            image_parts=pages,
            response_schema=AIMarkResponse,
            prompt_version="v1",
            model=_HAIKU,
            task_tag=tag,
        )


class FitOnTheWireTests(_Base):
    def test_real_size_pages_are_fitted(self) -> None:
        client, fake = self._client(_message(_VALID_MARK))
        self._read(client, [_scan_page()] * 19)
        sent = _sent_images(fake.messages.calls[0])
        self.assertEqual(len(sent), 19)
        for media_type, data in sent:
            self.assertEqual(media_type, "image/png")
            with Image.open(io.BytesIO(data)) as img:
                self.assertEqual(max(img.size), 2200)

    def test_inline_bytes_over_the_limit_at_the_floor_are_refused(self) -> None:
        client, fake = self._client(_message(_VALID_MARK))
        with (
            patch.object(image_fit, "DEFAULT_BYTE_LIMIT", 100),
            self.assertRaisesRegex(ProviderError, r"3 pages .* bytes"),
        ):
            self._read(client, [_scan_page(1000, 1400)] * 3)
        self.assertEqual(fake.messages.calls, [])

    def test_over_budget_at_the_floor_is_sent_and_logged(self) -> None:
        client, fake = self._client(_message(_VALID_MARK), claude_image_token_budget=1_000)
        with capture_logs() as logs:
            self._read(client, [_scan_page(1000, 1400)] * 3)
        self.assertEqual(len(fake.messages.calls), 1)
        (over,) = [e for e in logs if e["event"] == "claude_over_tier"]
        self.assertEqual((over["pages"], over["tag"]), (3, "binding_second_read"))
        self.assertGreater(over["est_tokens"], 1_000)

    def test_preflight_counts_tokens_near_the_budget(self) -> None:
        # One 1000x1400 page is 1,867 estimated tokens: within 10% of a 2,000 budget.
        client, fake = self._client(_message(_VALID_MARK), claude_image_token_budget=2_000)
        with capture_logs() as logs:
            self._read(client, [_scan_page(1000, 1400)])
        self.assertEqual(len(fake.messages.count_calls), 1)
        (pre,) = [e for e in logs if e["event"] == "claude_token_preflight"]
        self.assertEqual((pre["est_tokens"], pre["counted_tokens"]), (1_867, 1_000))

    def test_no_preflight_far_under_the_budget(self) -> None:
        client, fake = self._client(_message(_VALID_MARK))
        self._read(client, [_scan_page(400, 600)])
        self.assertEqual(fake.messages.count_calls, [])


class OutputCapTests(_Base):
    def test_cap_follows_max_output_tokens_for(self) -> None:
        client, fake = self._client(_message(_VALID_MARK), _message(_VALID_MARK))
        self._read(client, [_scan_page(400, 600)], tag="binding_second_read")
        self._read(client, [_scan_page(401, 600)], tag="correction")
        self.assertEqual([c["max_tokens"] for c in fake.messages.calls], [16_384, 16_000])
        self.assertEqual(fake.messages.streamed, [])

    def test_a_cap_above_the_nonstreaming_limit_streams(self) -> None:
        client, fake = self._client(_message(_VALID_MARK))
        self._read(client, [_scan_page(400, 600)], tag="extraction")
        self.assertEqual(len(fake.messages.streamed), 1)
        self.assertEqual(fake.messages.streamed[0]["max_tokens"], 32_768)


class EnhanceToggleTests(_Base):
    def test_the_setting_changes_the_bytes_sent(self) -> None:
        page = _scan_page(800, 1100)
        sent: dict[bool, bytes] = {}
        for enhance in (True, False):
            client, fake = self._client(_message(_VALID_MARK), claude_image_enhance=enhance)
            self._read(client, [page])
            ((_, sent[enhance]),) = _sent_images(fake.messages.calls[0])
        self.assertNotEqual(sent[True], sent[False])

    def test_off_sends_what_an_unenhanced_fit_makes(self) -> None:
        page = _scan_page(800, 1100)
        client, fake = self._client(_message(_VALID_MARK), claude_image_enhance=False)
        self._read(client, [page])
        ((_, data),) = _sent_images(fake.messages.calls[0])
        plain = image_fit.fit(
            [page],
            byte_limit=image_fit.DEFAULT_BYTE_LIMIT,
            token_budget=95_000,
            floor_px=1568,
            enhance=False,
        )
        self.assertEqual(data, plain.images[0])


class CacheKeyTests(_Base):
    def test_claude_key_carries_the_cap_and_the_fit_version(self) -> None:
        client, _fake = self._client()
        second = client._params_fingerprint(_HAIKU, "binding_second_read", AIMarkResponse)
        correction = client._params_fingerprint(_HAIKU, "correction", AIMarkResponse)
        self.assertNotEqual(second, correction)
        with patch("lemely.io.llm.image_fit.IMG_FIT_VERSION", "v-test"):
            moved = client._params_fingerprint(_HAIKU, "binding_second_read", AIMarkResponse)
        self.assertNotEqual(second, moved)

    def test_claude_key_moves_with_the_image_budget_and_floor(self) -> None:
        base, _ = self._client()
        key = base._params_fingerprint(_HAIKU, "binding_second_read", AIMarkResponse)
        for setting, value in (
            ("claude_image_token_budget", 80_000),
            ("claude_image_floor_px", 1200),
        ):
            with self.subTest(setting=setting):
                other, _ = self._client(**{setting: value})
                self.assertNotEqual(
                    key, other._params_fingerprint(_HAIKU, "binding_second_read", AIMarkResponse)
                )

    def test_claude_key_moves_with_image_enhancement(self) -> None:
        on, _ = self._client()
        off, _ = self._client(claude_image_enhance=False)
        key_on = on._params_fingerprint(_HAIKU, "binding_second_read", AIMarkResponse)
        key_off = off._params_fingerprint(_HAIKU, "binding_second_read", AIMarkResponse)
        self.assertNotEqual(key_on, key_off)
        self.assertEqual(
            key_off,
            self._client(claude_image_enhance=False)[0]._params_fingerprint(
                _HAIKU, "binding_second_read", AIMarkResponse
            ),
        )

    def test_claude_key_moves_with_page_labels_only_for_several_images(self) -> None:
        client, _fake = self._client()
        args = (_HAIKU, "binding_second_read", AIMarkResponse)
        none = client._params_fingerprint(*args)
        one = client._params_fingerprint(*args, n_images=1)
        two = client._params_fingerprint(*args, n_images=2)
        self.assertEqual(none, one)
        self.assertNotEqual(one, two)
        self.assertEqual(two, client._params_fingerprint(*args, n_images=19))

    def test_the_structured_key_changes_between_one_and_two_pages(self) -> None:
        client, _fake = self._client()
        common = {
            "system_prompt": "s",
            "user_prompt": "u",
            "response_schema": AIMarkResponse,
            "prompt_version": "v1",
            "task_tag": "binding_second_read",
        }
        gem = "gemini-2.5-flash"
        for model, moves in ((_HAIKU, True), (gem, False)):
            one = client.structured_cache_key(model=model, image_parts=[b"a"], **common)
            two = client.structured_cache_key(model=model, image_parts=[b"a", b"b"], **common)
            self.assertNotEqual(one, two)  # different bytes always differ; compare segments:
            seg = client._params_fingerprint
            self.assertEqual(
                seg(model, "binding_second_read", AIMarkResponse, n_images=2)
                != seg(model, "binding_second_read", AIMarkResponse, n_images=1),
                moves,
            )

    def test_gemini_key_ignores_the_claude_image_settings(self) -> None:
        base, _ = self._client()
        other, _ = self._client(
            claude_image_token_budget=80_000, claude_image_floor_px=1200, claude_image_enhance=False
        )
        model = "gemini-2.5-flash"
        self.assertEqual(
            base._params_fingerprint(model, "extraction", AIMarkResponse),
            other._params_fingerprint(model, "extraction", AIMarkResponse),
        )
