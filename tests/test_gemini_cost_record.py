"""Cost-ladder rung 0: the per-call cost record, cached-token pricing, 2027 prices."""

from __future__ import annotations

import inspect
import tempfile
import unittest
from datetime import date
from unittest.mock import MagicMock, patch

from pydantic import BaseModel

from lemely.io.gemini import (
    PRICE_DATE_2027,
    CallRecord,
    GeminiClient,
    PriceRow,
    UnpricedModelError,
    _reset_process_counters,
    price_call,
    price_row,
    process_call_records,
    set_call_context,
)
from lemely.runtime.errors import ParseError
from tests.test_gemini_client import _make_settings, _mock_response

_TODAY = date(2026, 10, 19)
_MODEL = "gemini-3.8-flash"


class _Schema(BaseModel):
    value: str


def _response(text: str, *, prompt: int, cached: int, candidates: int, thoughts: int = 0):
    resp = _mock_response(text, in_tok=prompt, out_tok=candidates, thoughts_tok=thoughts)
    resp.usage_metadata.cached_content_token_count = cached
    return resp


class CostRecordTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.settings = _make_settings(self.tmp)
        _reset_process_counters()
        set_call_context(case_key=None)
        patcher = patch("lemely.io.gemini._today", lambda: _TODAY)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _client(self, *responses: MagicMock) -> GeminiClient:
        genai = MagicMock()
        genai.models.generate_content.side_effect = list(responses)
        return GeminiClient(self.settings, _genai_client=genai)

    def _call(self, client: GeminiClient, **kwargs: object) -> _Schema:
        return client.generate_structured(
            system_prompt="sys",
            user_prompt="user",
            response_schema=_Schema,
            prompt_version="1",
            model=_MODEL,
            **kwargs,  # type: ignore[arg-type]
        )

    def test_cached_tokens_priced_at_cached_rate(self) -> None:
        client = self._client(
            _response('{"value": "a"}', prompt=10_000, cached=8_000, candidates=1_000)
        )
        self._call(client)
        (rec,) = process_call_records()
        expected = (2000 * 0.00075 + 8000 * 0.000075 + 1000 * 0.00375) / 1000
        self.assertAlmostEqual(rec.usd_now, expected, places=9)
        self.assertEqual(rec.cached_tokens, 8_000)

    def test_2027_price_used_on_and_after_boundary(self) -> None:
        kwargs = {"input_tokens": 10_000, "cached_tokens": 8_000, "output_tokens": 1_000}
        before = price_call(_MODEL, self.settings, on=date(2026, 12, 31), **kwargs)
        after = price_call(_MODEL, self.settings, on=date(2027, 1, 1), **kwargs)
        self.assertAlmostEqual(before, (2000 * 0.00075 + 8000 * 0.000075 + 1000 * 0.00375) / 1000)
        self.assertAlmostEqual(after, (2000 * 0.0015 + 8000 * 0.00015 + 1000 * 0.0075) / 1000)
        self.assertEqual(
            price_row(_MODEL, self.settings, on=date(2026, 12, 31)),
            PriceRow(0.00075, 0.000075, 0.00375),
        )
        self.assertEqual(
            price_row(_MODEL, self.settings, on=date(2027, 1, 1)),
            PriceRow(0.0015, 0.00015, 0.0075),
        )
        self.assertEqual(PRICE_DATE_2027, date(2027, 1, 1))

    def test_record_carries_both_prices(self) -> None:
        client = self._client(_response('{"value": "a"}', prompt=1_000, cached=0, candidates=100))
        self._call(client)
        (rec,) = process_call_records()
        self.assertAlmostEqual(rec.usd_2027, rec.usd_now * 2, places=9)

    def test_thinking_tokens_billed_as_output(self) -> None:
        client = self._client(
            _response('{"value": "a"}', prompt=0, cached=0, candidates=1_000, thoughts=500)
        )
        self._call(client)
        (rec,) = process_call_records()
        self.assertEqual(rec.thinking_tokens, 500)
        self.assertEqual(rec.output_tokens, 1_500)
        self.assertAlmostEqual(rec.usd_now, 1500 * 0.00375 / 1000, places=9)

    def test_unknown_model_raises_unpriced(self) -> None:
        with self.assertRaises(UnpricedModelError):
            price_row("gemini-9-ultra", self.settings, on=_TODAY)

    def test_3_1_flash_lite_row_exists(self) -> None:
        self.assertEqual(
            price_row("gemini-3.1-flash-lite", self.settings, on=_TODAY),
            PriceRow(0.00025, 0.000025, 0.0015),
        )

    def test_haiku_row_exists(self) -> None:
        self.assertEqual(
            price_row("claude-haiku-5-5", self.settings, on=_TODAY),
            PriceRow(0.0001, 0.00001, 0.0005),
        )

    def test_deprecated_3_7_flash_is_no_longer_priced(self) -> None:
        with self.assertRaises(UnpricedModelError):
            price_row("gemini-3.7-flash", self.settings, on=_TODAY)

    def test_call_record_appended_with_attempt_and_question(self) -> None:
        client = self._client(_response('{"value": "a"}', prompt=100, cached=0, candidates=10))
        self._call(client, attempt="borderline", question_id="3b", task_tag="marking")
        (rec,) = process_call_records()
        self.assertIsInstance(rec, CallRecord)
        self.assertEqual((rec.attempt, rec.question_id), ("borderline", "3b"))
        self.assertEqual((rec.model, rec.provider, rec.task_tag), (_MODEL, "gemini", "marking"))
        self.assertTrue(rec.parse_ok)

    def test_records_default_to_no_attempt_or_question(self) -> None:
        client = self._client(_response('{"value": "a"}', prompt=100, cached=0, candidates=10))
        self._call(client)
        (rec,) = process_call_records()
        self.assertIsNone(rec.attempt)
        self.assertIsNone(rec.question_id)

    def test_attempt_and_question_id_not_in_cache_key(self) -> None:
        for fn in (
            GeminiClient._cache_key,
            GeminiClient._params_fingerprint,
            GeminiClient._structured_cache_key,
            GeminiClient.structured_cache_key,
        ):
            params = inspect.signature(fn).parameters
            self.assertNotIn("attempt", params)
            self.assertNotIn("question_id", params)
        # Behavioural: a second call differing only in attempt is a cache hit.
        client = self._client(_response('{"value": "a"}', prompt=100, cached=0, candidates=10))
        self._call(client, attempt="first", question_id="1a")
        self._call(client, attempt="escalation", question_id="1a")
        self.assertEqual(client._client.models.generate_content.call_count, 1)
        self.assertEqual(len(process_call_records()), 1)

    def test_reset_clears_call_records(self) -> None:
        client = self._client(_response('{"value": "a"}', prompt=100, cached=0, candidates=10))
        self._call(client)
        self.assertEqual(len(process_call_records()), 1)
        _reset_process_counters()
        self.assertEqual(process_call_records(), [])

    def test_process_call_records_returns_a_copy(self) -> None:
        client = self._client(_response('{"value": "a"}', prompt=100, cached=0, candidates=10))
        self._call(client)
        process_call_records().clear()
        self.assertEqual(len(process_call_records()), 1)

    def test_case_key_from_context(self) -> None:
        client = self._client(
            _response('{"value": "a"}', prompt=100, cached=0, candidates=10),
            _response('{"value": "b"}', prompt=100, cached=0, candidates=10),
        )
        set_call_context(case_key="paper-1")
        self._call(client, extra_cache_key="x")
        set_call_context(case_key="paper-2")
        self._call(client, extra_cache_key="y")
        self.assertEqual([r.case_key for r in process_call_records()], ["paper-1", "paper-2"])

    def test_parse_failure_recorded_with_parse_ok_false(self) -> None:
        client = self._client(
            _response("not json", prompt=100, cached=0, candidates=10),
            _response("still not json", prompt=100, cached=0, candidates=10),
        )
        with self.assertRaises(ParseError):
            self._call(client)
        records = process_call_records()
        self.assertEqual(len(records), 2)
        self.assertTrue(all(not r.parse_ok for r in records))

    def test_parse_failure_then_success_marks_only_the_failed_call(self) -> None:
        client = self._client(
            _response("not json", prompt=100, cached=0, candidates=10),
            _response('{"value": "ok"}', prompt=100, cached=0, candidates=10),
        )
        self._call(client)
        self.assertEqual([r.parse_ok for r in process_call_records()], [False, True])

    def test_mock_usage_without_cached_attr_counts_zero_cached(self) -> None:
        # A bare MagicMock attribute must not be read as 1 cached token.
        client = self._client(_mock_response('{"value": "a"}', in_tok=100, out_tok=10))
        self._call(client)
        (rec,) = process_call_records()
        self.assertEqual(rec.cached_tokens, 0)


if __name__ == "__main__":
    unittest.main()
