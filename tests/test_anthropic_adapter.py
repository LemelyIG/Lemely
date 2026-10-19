"""Cost-ladder lever A1: the Anthropic adapter behind ``claude-`` model-prefix dispatch.

Every test drives a fake SDK client: no network call, no Anthropic spend.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import anthropic
import httpx2
from pydantic import BaseModel, SecretStr

from lemely.core.schemas import AIMarkResponse
from lemely.io.gemini import (
    GeminiClient,
    _reset_process_counters,
    price_call,
    price_row,
    process_call_records,
    set_call_context,
)
from lemely.io.providers import ProviderTransientError, is_anthropic_model
from lemely.io.providers.anthropic_adapter import (
    MAX_OUTPUT_TOKENS,
    AnthropicAdapter,
    Usage,
    effort_for,
)
from lemely.runtime.config import Settings
from lemely.runtime.errors import ExternalServiceError, ParseError
from tests.gemini_fakes import make_settings, mock_response

_TODAY = date(2026, 10, 19)
_HAIKU = "claude-haiku-5-5"

_VALID_MARK = {
    "awarded_marks": 2,
    "confidence": 0.9,
    "matched_point_ids": ["M1", "A1"],
    "feedback": "Correct method and answer.",
    "point_verdicts": [],
    "addresses_question": "yes",
}


def _message(
    payload: dict[str, object] | str,
    *,
    input_tokens: int = 1_000,
    cache_read: int = 0,
    cache_write: int = 0,
    output_tokens: int = 200,
    thinking_tokens: int = 0,
    stop_reason: str = "end_turn",
) -> SimpleNamespace:
    """A stand-in for ``anthropic.types.Message`` with real ints in every usage field."""
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return SimpleNamespace(
        content=[
            SimpleNamespace(type="thinking", thinking=""),
            SimpleNamespace(type="text", text=text),
        ],
        stop_reason=stop_reason,
        usage=SimpleNamespace(
            input_tokens=input_tokens,
            cache_read_input_tokens=cache_read,
            cache_creation_input_tokens=cache_write,
            output_tokens=output_tokens,
            output_tokens_details=SimpleNamespace(thinking_tokens=thinking_tokens),
        ),
    )


class _FakeMessages:
    def __init__(self, outcomes: list[object]) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> object:
        self.calls.append(kwargs)
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class _FakeAnthropic:
    """Stands in for ``anthropic.Anthropic``: only ``messages.create`` is touched."""

    def __init__(self, *outcomes: object) -> None:
        self.messages = _FakeMessages(list(outcomes))


def _status_error(status: int) -> anthropic.APIStatusError:
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx2.Response(status, request=request)
    classes: dict[int, type[anthropic.APIStatusError]] = {
        400: anthropic.BadRequestError,
        401: anthropic.AuthenticationError,
        429: anthropic.RateLimitError,
        500: anthropic.InternalServerError,
        529: anthropic.OverloadedError,
    }
    cls = classes.get(status, anthropic.APIStatusError)
    return cls(f"status {status}", response=response, body=None)


def _settings(tmp: str, **gemini_updates: object) -> Settings:
    s = make_settings(tmp)
    return s.model_copy(
        update={
            "gemini": s.gemini.model_copy(update={"backoff_seconds": 0.01, **gemini_updates}),
            "anthropic_api_key": SecretStr("test-key"),
        }
    )


class _ClientTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        _reset_process_counters()
        set_call_context(case_key=None)
        today = patch("lemely.io.gemini._today", lambda: _TODAY)
        today.start()
        self.addCleanup(today.stop)
        no_sleep = patch("lemely.io.gemini.time.sleep")
        no_sleep.start()
        self.addCleanup(no_sleep.stop)

    def _client(
        self, *outcomes: object, settings: Settings | None = None
    ) -> tuple[GeminiClient, _FakeAnthropic, MagicMock]:
        fake = _FakeAnthropic(*outcomes)
        genai = MagicMock()
        client = GeminiClient(
            settings or _settings(self.tmp),
            _genai_client=genai,
            _anthropic_client=fake,
            ledger=None,
        )
        return client, fake, genai

    def _mark(self, client: GeminiClient, **kwargs: Any) -> AIMarkResponse:
        params: dict[str, Any] = {
            "system_prompt": "You are a CAIE examiner.",
            "user_prompt": "Mark this answer.",
            "response_schema": AIMarkResponse,
            "prompt_version": "v1",
            "model": _HAIKU,
            "task_tag": "correction",
        }
        params.update(kwargs)
        return client.generate_structured(**params)


class AdapterTests(unittest.TestCase):
    def test_schema_roundtrip_ai_mark_response(self) -> None:
        fake = _FakeAnthropic(
            _message(
                _VALID_MARK, input_tokens=900, cache_read=100, output_tokens=250, thinking_tokens=50
            )
        )
        parsed, usage = AnthropicAdapter(fake).generate(
            model=_HAIKU,
            system_prompt="sys",
            user_prompt="user",
            response_schema=AIMarkResponse,
            thinking="low",
            cache_prefix=None,
        )
        self.assertIsInstance(parsed, AIMarkResponse)
        self.assertEqual(parsed, AIMarkResponse.model_validate(_VALID_MARK))
        self.assertEqual(
            usage,
            Usage(input_tokens=1_000, cached_tokens=100, output_tokens=250, thinking_tokens=50),
        )
        (call,) = fake.messages.calls
        self.assertEqual(call["model"], _HAIKU)
        self.assertEqual(call["max_tokens"], MAX_OUTPUT_TOKENS)
        fmt = call["output_config"]["format"]
        self.assertEqual(fmt["type"], "json_schema")
        self.assertEqual(fmt["schema"], anthropic.transform_schema(AIMarkResponse))
        # The provider schema cannot carry numeric bounds: they must not be sent.
        sent = json.dumps(fmt["schema"])
        for keyword in ('"minimum"', '"maximum"', '"exclusiveMinimum"'):
            self.assertNotIn(keyword, sent)
        # ``addresses_question`` stays required on the wire (AIMarkResponse's override).
        self.assertIn("addresses_question", fmt["schema"]["required"])

    def test_out_of_bounds_marks_rejected(self) -> None:
        cases: list[tuple[dict[str, object], int | None]] = [
            ({**_VALID_MARK, "awarded_marks": -1}, None),
            ({**_VALID_MARK, "confidence": 1.5}, None),
            ({**_VALID_MARK, "awarded_marks": 4}, 3),
        ]
        for payload, max_marks in cases:
            with self.subTest(payload=payload, max_marks=max_marks):
                adapter = AnthropicAdapter(_FakeAnthropic(_message(payload)))
                with self.assertRaises(ParseError):
                    adapter.generate(
                        model=_HAIKU,
                        system_prompt="sys",
                        user_prompt="user",
                        response_schema=AIMarkResponse,
                        thinking=None,
                        cache_prefix=None,
                        max_awarded_marks=max_marks,
                    )
        # The bound is inclusive.
        adapter = AnthropicAdapter(_FakeAnthropic(_message({**_VALID_MARK, "awarded_marks": 3})))
        parsed, _usage = adapter.generate(
            model=_HAIKU,
            system_prompt="sys",
            user_prompt="user",
            response_schema=AIMarkResponse,
            thinking=None,
            cache_prefix=None,
            max_awarded_marks=3,
        )
        self.assertEqual(parsed.awarded_marks, 3)

    def test_effort_mapping(self) -> None:
        self.assertEqual(effort_for("minimal"), "low")
        self.assertEqual(effort_for("low"), "low")
        self.assertEqual(effort_for("medium"), "medium")
        self.assertEqual(effort_for("high"), "high")
        with self.assertRaises(ValueError):
            effort_for("xhigh-ish")
        for level, expected in [("minimal", "low"), ("medium", "medium"), ("high", "high")]:
            with self.subTest(level=level):
                fake = _FakeAnthropic(_message(_VALID_MARK))
                AnthropicAdapter(fake).generate(
                    model=_HAIKU,
                    system_prompt="sys",
                    user_prompt="user",
                    response_schema=AIMarkResponse,
                    thinking=level,
                    cache_prefix=None,
                )
                self.assertEqual(fake.messages.calls[0]["output_config"]["effort"], expected)
                self.assertEqual(fake.messages.calls[0]["thinking"], {"type": "adaptive"})
        fake = _FakeAnthropic(_message(_VALID_MARK))
        AnthropicAdapter(fake).generate(
            model=_HAIKU,
            system_prompt="sys",
            user_prompt="user",
            response_schema=AIMarkResponse,
            thinking=None,
            cache_prefix=None,
        )
        self.assertNotIn("effort", fake.messages.calls[0]["output_config"])

    def test_prompt_caching_marks_system_and_prefix(self) -> None:
        fake = _FakeAnthropic(_message(_VALID_MARK), _message(_VALID_MARK))
        adapter = AnthropicAdapter(fake)
        adapter.generate(
            model=_HAIKU,
            system_prompt="sys",
            user_prompt="user",
            response_schema=AIMarkResponse,
            thinking=None,
            cache_prefix="mark scheme",
        )
        first = fake.messages.calls[0]
        self.assertEqual(
            first["system"],
            [{"type": "text", "text": "sys", "cache_control": {"type": "ephemeral"}}],
        )
        self.assertEqual(
            first["messages"],
            [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "mark scheme",
                            "cache_control": {"type": "ephemeral"},
                        },
                        {"type": "text", "text": "user"},
                    ],
                }
            ],
        )
        adapter.generate(
            model=_HAIKU,
            system_prompt="sys",
            user_prompt="user",
            response_schema=AIMarkResponse,
            thinking=None,
            cache_prefix=None,
        )
        self.assertEqual(fake.messages.calls[1]["messages"], [{"role": "user", "content": "user"}])

    def test_sdk_errors_split_into_transient_and_permanent(self) -> None:
        for status in (429, 500, 503, 529):
            with self.subTest(status=status):
                adapter = AnthropicAdapter(_FakeAnthropic(_status_error(status)))
                with self.assertRaises(ProviderTransientError):
                    adapter.complete(
                        model=_HAIKU,
                        system_prompt="s",
                        user_prompt="u",
                        response_schema=AIMarkResponse,
                        thinking=None,
                        cache_prefix=None,
                    )
        request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
        adapter = AnthropicAdapter(_FakeAnthropic(anthropic.APIConnectionError(request=request)))
        with self.assertRaises(ProviderTransientError):
            adapter.complete(
                model=_HAIKU,
                system_prompt="s",
                user_prompt="u",
                response_schema=AIMarkResponse,
                thinking=None,
                cache_prefix=None,
            )
        for status in (400, 401):
            with self.subTest(status=status):
                adapter = AnthropicAdapter(_FakeAnthropic(_status_error(status)))
                with self.assertRaises(ExternalServiceError) as ctx:
                    adapter.complete(
                        model=_HAIKU,
                        system_prompt="s",
                        user_prompt="u",
                        response_schema=AIMarkResponse,
                        thinking=None,
                        cache_prefix=None,
                    )
                self.assertNotIsInstance(ctx.exception, ProviderTransientError)

    def test_model_prefix(self) -> None:
        self.assertTrue(is_anthropic_model("claude-haiku-5-5"))
        self.assertFalse(is_anthropic_model("gemini-3.8-flash"))
        self.assertFalse(is_anthropic_model("anthropic.claude-haiku-5-5"))

    def test_haiku_price_row_pinned(self) -> None:
        settings = make_settings(tempfile.mkdtemp())
        row = price_row(_HAIKU, settings, on=_TODAY)
        self.assertEqual((row.input, row.cached_input, row.output), (0.0001, 0.00001, 0.0005))


class ClientDispatchTests(_ClientTestCase):
    def test_dispatch_by_model_prefix(self) -> None:
        client, fake, genai = self._client(_message(_VALID_MARK))
        result = self._mark(client)
        self.assertEqual(result.awarded_marks, 2)
        self.assertEqual(len(fake.messages.calls), 1)
        genai.models.generate_content.assert_not_called()

        # The reply is cached by the client: a second identical call is free.
        self.assertEqual(self._mark(client), result)
        self.assertEqual(len(fake.messages.calls), 1)

        # A Gemini model on the same client never touches the Anthropic SDK.
        genai.models.generate_content.return_value = mock_response(json.dumps(_VALID_MARK))
        self._mark(client, model="gemini-3.8-flash")
        genai.models.generate_content.assert_called_once()
        self.assertEqual(len(fake.messages.calls), 1)

        # A claude- model reached through task_tag routing dispatches too.
        settings = _settings(self.tmp, correction_model=_HAIKU)
        client2, fake2, genai2 = self._client(_message(_VALID_MARK), settings=settings)
        self._mark(client2, model=None, cache_mode="bypass")
        self.assertEqual(len(fake2.messages.calls), 1)
        genai2.models.generate_content.assert_not_called()

    def test_usage_fills_call_record_with_provider_anthropic(self) -> None:
        client, _fake, _genai = self._client(
            _message(
                _VALID_MARK,
                input_tokens=600,
                cache_read=3_000,
                cache_write=400,
                output_tokens=700,
                thinking_tokens=300,
            )
        )
        self._mark(client, attempt="first", question_id="Q1")
        (rec,) = process_call_records()
        self.assertEqual(rec.provider, "anthropic")
        self.assertEqual(rec.model, _HAIKU)
        self.assertEqual(rec.input_tokens, 4_100)  # 600 + 3000 + 1.25 * 400
        self.assertEqual(rec.cached_tokens, 3_000)
        self.assertEqual(rec.output_tokens, 700)
        self.assertEqual(rec.thinking_tokens, 300)
        self.assertEqual(rec.attempt, "first")
        self.assertEqual(rec.question_id, "Q1")
        self.assertTrue(rec.parse_ok)
        settings = make_settings(self.tmp)
        expected = price_call(
            _HAIKU, settings, input_tokens=4_100, cached_tokens=3_000, output_tokens=700, on=_TODAY
        )
        self.assertAlmostEqual(rec.usd_now, expected, places=12)
        self.assertEqual(rec.usd_2027, rec.usd_now)
        self.assertAlmostEqual(expected, (1_100 * 0.0001 + 3_000 * 0.00001 + 700 * 0.0005) / 1000)

    def test_cache_write_premium_priced(self) -> None:
        client, _fake, _genai = self._client(
            _message(_VALID_MARK, input_tokens=1_000, cache_write=2_000, output_tokens=0)
        )
        self._mark(client)
        (rec,) = process_call_records()
        # uncached 1000 + cache write 2000 at 1.25x the input rate.
        self.assertAlmostEqual(rec.usd_now, (1_000 + 1.25 * 2_000) * 0.0001 / 1000, places=12)
        self.assertEqual(rec.usd_2027, rec.usd_now)

    def test_unexpected_adapter_exception_becomes_external_service_error(self) -> None:
        client, fake, _genai = self._client(RuntimeError("boom"))
        with self.assertRaises(ExternalServiceError):
            self._mark(client)
        self.assertEqual(len(fake.messages.calls), 1)

    def test_code_execution_rejects_claude_model(self) -> None:
        client, fake, genai = self._client()
        with self.assertRaises(ValueError):
            client.generate_with_code_execution(prompt="p", prompt_version="v1", model=_HAIKU)
        self.assertEqual(fake.messages.calls, [])
        genai.models.generate_content.assert_not_called()

    def test_record_thinking_is_the_effort_sent(self) -> None:
        settings = _settings(self.tmp, thinking_level_for={"correction": "high"})
        client, fake, _genai = self._client(_message(_VALID_MARK), settings=settings)
        self._mark(client)
        self.assertEqual(fake.messages.calls[0]["output_config"]["effort"], "high")
        (rec,) = process_call_records()
        self.assertEqual(rec.thinking, "high")
        self.assertEqual(client.resolved_thinking("correction", _HAIKU), "high")

    def test_transient_error_retried_permanent_not(self) -> None:
        client, fake, _genai = self._client(
            _status_error(429),
            _status_error(529),
            _status_error(500),
            _message(_VALID_MARK),
            settings=_settings(self.tmp, max_retries=3),
        )
        self.assertEqual(self._mark(client).awarded_marks, 2)
        self.assertEqual(len(fake.messages.calls), 4)

        client, fake, _genai = self._client(
            _status_error(400),
            _message(_VALID_MARK),
            settings=_settings(self.tmp, max_retries=3),
        )
        with self.assertRaises(ExternalServiceError):
            self._mark(client, cache_mode="bypass")
        self.assertEqual(len(fake.messages.calls), 1)

        # Exhausted transient retries surface as ExternalServiceError.
        client, fake, _genai = self._client(
            _status_error(529),
            _status_error(529),
            settings=_settings(self.tmp, max_retries=1),
        )
        with self.assertRaises(ExternalServiceError):
            self._mark(client, cache_mode="bypass")
        self.assertEqual(len(fake.messages.calls), 2)

    def test_max_tokens_stop_is_retried_and_still_billed(self) -> None:
        client, fake, _genai = self._client(
            _message('{"awarded_marks": 2', stop_reason="max_tokens"),
            _message(_VALID_MARK),
        )
        self._mark(client)
        self.assertEqual(len(fake.messages.calls), 2)
        self.assertEqual(len(process_call_records()), 2)

    def test_out_of_bounds_reply_goes_through_schema_correction_retry(self) -> None:
        client, fake, _genai = self._client(
            _message({**_VALID_MARK, "awarded_marks": -2}),
            _message({**_VALID_MARK, "confidence": 7}),
        )
        with self.assertRaises(ParseError):
            self._mark(client)
        self.assertEqual(len(fake.messages.calls), 2)
        self.assertIn("failed validation", fake.messages.calls[1]["messages"][0]["content"])
        self.assertEqual([r.parse_ok for r in process_call_records()], [False, False])

    def test_images_rejected(self) -> None:
        client, fake, genai = self._client(_message(_VALID_MARK))
        with self.assertRaises(ValueError):
            self._mark(client, image_parts=[b"\x89PNG"])
        with self.assertRaises(ValueError):
            self._mark(client, file_paths=[Path(self.tmp) / "scheme.pdf"])
        self.assertEqual(fake.messages.calls, [])
        genai.files.upload.assert_not_called()

    def test_missing_api_key_is_a_permanent_error(self) -> None:
        settings = _settings(self.tmp).model_copy(update={"anthropic_api_key": None})
        client = GeminiClient(settings, _genai_client=MagicMock(), ledger=None)
        with self.assertRaises(ExternalServiceError):
            self._mark(client)

    def test_claude_cache_key_carries_a_provider_component(self) -> None:
        client, _fake, _genai = self._client()
        args: dict[str, Any] = {
            "system_prompt": "sys",
            "user_prompt": "user",
            "response_schema": AIMarkResponse,
            "prompt_version": "v1",
            "task_tag": "correction",
        }
        fp_claude = client._params_fingerprint(_HAIKU, "correction", AIMarkResponse)
        with patch("lemely.io.gemini.is_anthropic_model", return_value=False):
            fp_without_provider = client._params_fingerprint(_HAIKU, "correction", AIMarkResponse)
        self.assertNotEqual(fp_claude, fp_without_provider)
        self.assertNotEqual(
            client.structured_cache_key(model=_HAIKU, **args),
            client.structured_cache_key(model="claude-haiku-5-6", **args),
        )


class _PinnedSchema(BaseModel):
    value: str


class GeminiCacheKeyStabilityTests(unittest.TestCase):
    def test_gemini_cache_keys_unchanged(self) -> None:
        """Values captured on 983c977e, before this task touched gemini.py.

        Every Gemini entry already on disk is addressed by these keys; the
        Anthropic provider component must not move a single one of them. They
        depend on the default ``thinking_level_for``, so a deliberate change to
        those defaults is the one legitimate reason to re-capture them. The two
        ``extraction``-tag keys were re-captured when ``max_output_tokens_for``
        began capping that tag at 16384 (cost-ladder B12); the ``correction`` and
        untagged keys did not move, which is the proof the cap is tag-scoped.
        """
        client = GeminiClient(
            make_settings(tempfile.mkdtemp()), _genai_client=object(), ledger=None
        )
        pinned = [
            ("gemini-3.8-flash", "correction", "62e1535661dcbc4c"),
            ("gemini-2.5-flash", None, "95b0df425f53e2b3"),
            ("gemini-3.5-flash-lite", "extraction", "6b1b203108fd62ed"),
        ]
        for model, tag, expected in pinned:
            with self.subTest(model=model, tag=tag):
                self.assertEqual(
                    client.structured_cache_key(
                        system_prompt="sys",
                        user_prompt="user",
                        response_schema=_PinnedSchema,
                        prompt_version="v1",
                        model=model,
                        task_tag=tag,
                    ),
                    expected,
                )
        self.assertEqual(
            client.structured_cache_key(
                system_prompt="sys",
                user_prompt="user",
                image_parts=[b"png"],
                media_resolution="medium",
                response_schema=_PinnedSchema,
                prompt_version="v1",
                model="gemini-3.8-flash",
                task_tag="extraction",
            ),
            "2536c5f9b31d8fe9",
        )


if __name__ == "__main__":
    unittest.main()
