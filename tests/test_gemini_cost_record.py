"""Cost-ladder rung 0: the per-call cost record, cached-token pricing, 2027 prices."""

from __future__ import annotations

import inspect
import math
import tempfile
import threading
import unittest
from datetime import date
from unittest.mock import MagicMock, patch

from pydantic import BaseModel

from lemely.io import gemini as gemini_module
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
    record_calls,
    set_call_context,
)
from lemely.io.llm.pricing import CLAUDE_PRICING
from lemely.runtime.errors import ParseError
from tests.gemini_fakes import make_settings, mock_response

_TODAY = date(2026, 10, 19)
_MODEL = "gemini-3.8-flash"


class _Schema(BaseModel):
    value: str


def _response(
    text: str, *, prompt: int, cached: int, candidates: int, thoughts: int = 0
) -> MagicMock:
    return mock_response(
        text, prompt=prompt, candidates=candidates, thoughts=thoughts, cached=cached
    )


class CostRecordTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.settings = make_settings(self.tmp)
        # Call records are kept only while a recorder is open.
        self.enterContext(record_calls())
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
        row = price_row("claude-haiku-5-5", self.settings, on=_TODAY)
        self.assertEqual(row, CLAUDE_PRICING["claude-haiku-5-5"])

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
        resp = _response('{"value": "a"}', prompt=100, cached=0, candidates=10)
        resp.usage_metadata = MagicMock(
            spec=["prompt_token_count", "candidates_token_count", "thoughts_token_count"],
            prompt_token_count=100,
            candidates_token_count=10,
            thoughts_token_count=0,
        )
        client = self._client(resp)
        self._call(client)
        (rec,) = process_call_records()
        self.assertEqual(rec.cached_tokens, 0)

    def test_unpriced_model_record_is_nan_ledger_still_advances(self) -> None:
        client = self._client(_response('{"value": "a"}', prompt=1_000, cached=0, candidates=100))
        before = gemini_module._process_accumulated_usd
        client.generate_structured(
            system_prompt="sys",
            user_prompt="user",
            response_schema=_Schema,
            prompt_version="1",
            model="gemini-9-ultra",
        )
        (rec,) = process_call_records()
        self.assertTrue(math.isnan(rec.usd_now))
        self.assertTrue(math.isnan(rec.usd_2027))
        self.assertGreater(gemini_module._process_accumulated_usd, before)

    def test_case_key_is_context_local_across_threads(self) -> None:
        client = self._client(
            _response('{"value": "a"}', prompt=100, cached=0, candidates=10),
            _response('{"value": "b"}', prompt=100, cached=0, candidates=10),
        )
        barrier = threading.Barrier(2)

        def worker(key: str, extra: str) -> None:
            set_call_context(case_key=key)
            barrier.wait(timeout=5)
            self._call(client, extra_cache_key=extra)

        threads = [
            threading.Thread(target=worker, args=("case-A", "a")),
            threading.Thread(target=worker, args=("case-B", "b")),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        self.assertEqual(
            sorted(r.case_key or "" for r in process_call_records()), ["case-A", "case-B"]
        )

    def test_stale_unparsed_mark_after_reset_does_not_flip_other_record(self) -> None:
        client = self._client()
        spend = {
            "model": _MODEL,
            "task_tag": None,
            "latency_ms": 0,
            "log": MagicMock(),
            "params_fingerprint": "f",
        }
        client._record_spend(response=_response("x", prompt=1, cached=0, candidates=1), **spend)
        stale = gemini_module._thread_state.last_record
        _reset_process_counters()
        client._record_spend(response=_response("y", prompt=2, cached=0, candidates=1), **spend)
        # This thread's pointer now names the second record; point it back at the
        # reset-away first one, as a failure arriving after the reset would.
        gemini_module._thread_state.last_record = stale
        gemini_module._mark_last_record_unparsed()
        self.assertEqual([r.parse_ok for r in process_call_records()], [True])

    def test_code_execution_record_has_no_thinking(self) -> None:
        resp = _response("x", prompt=100, cached=0, candidates=10)
        part = MagicMock()
        part.code_execution_result.output = "42"
        resp.candidates[0].content.parts = [part]
        client = self._client(resp)
        client._call_code_execution_once(
            _MODEL, "p", MagicMock(), "marking", params_fingerprint="f"
        )
        (rec,) = process_call_records()
        self.assertIsNone(rec.thinking)


class RecorderSwitchTests(unittest.TestCase):
    """Records are appended only while a `record_calls` block is open."""

    def setUp(self) -> None:
        self.settings = make_settings(tempfile.mkdtemp())
        _reset_process_counters()
        patcher = patch("lemely.io.gemini._today", lambda: _TODAY)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _call(self, extra: str) -> None:
        genai = MagicMock()
        genai.models.generate_content.return_value = _response(
            '{"value": "a"}', prompt=100, cached=0, candidates=10
        )
        GeminiClient(self.settings, _genai_client=genai).generate_structured(
            system_prompt="sys",
            user_prompt="user",
            response_schema=_Schema,
            prompt_version="1",
            model=_MODEL,
            extra_cache_key=extra,
        )

    def test_default_path_appends_nothing(self) -> None:
        before = gemini_module._process_accumulated_usd
        self._call("a")
        self.assertEqual(process_call_records(), [])
        self.assertEqual(gemini_module._process_call_records, [])
        # Spend is still counted; only the per-call record is skipped.
        self.assertGreater(gemini_module._process_accumulated_usd, before)

    def test_recorder_on_appends(self) -> None:
        with record_calls():
            self._call("a")
            self.assertEqual(len(process_call_records()), 1)

    def test_nested_blocks_keep_records_until_outermost_exit(self) -> None:
        with record_calls():
            with record_calls():
                self._call("a")
            self._call("b")
            self.assertEqual(len(process_call_records()), 2)
        self.assertEqual(process_call_records(), [])
        self._call("c")
        self.assertEqual(process_call_records(), [])


if __name__ == "__main__":
    unittest.main()
