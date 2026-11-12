"""Spec 2026-10-19 §3: tiered Claude prices, cache writes, container time, fail-closed."""

from __future__ import annotations

import random
import tempfile
import unittest
from datetime import date
from unittest.mock import patch

from structlog.testing import capture_logs

from lemely.core.schemas import AIMarkResponse
from lemely.io.gemini import (
    GeminiClient,
    UnpricedModelError,
    _reset_process_counters,
    price_row,
    process_call_records,
    record_calls,
)
from lemely.io.llm.pricing import (
    CLAUDE_PRICE_SOURCES,
    CLAUDE_PRICING,
    PriceRow,
    claude_row,
    row_cost,
)
from tests.gemini_fakes import make_settings, mock_response
from tests.test_anthropic_adapter import _VALID_MARK, _FakeAnthropic, _message, _settings

_TODAY = date(2026, 10, 19)


def _old_row_cost(
    row: PriceRow, *, input_tokens: int, cached_tokens: int, output_tokens: int
) -> float:
    """Today's gemini._row_cost, copied verbatim, as the oracle for Gemini rows."""
    cached = min(max(cached_tokens, 0), max(input_tokens, 0))
    uncached = max(input_tokens, 0) - cached
    return (
        uncached / 1000 * row.input
        + cached / 1000 * row.cached_input
        + output_tokens / 1000 * row.output
    )


class RowTests(unittest.TestCase):
    def test_rows_per_mtok(self) -> None:
        expected = {
            "claude-haiku-5-5": (0.10, 0.01, 0.50, 0.125, 0.20),
            "claude-sonnet-5-5": (2.0, 0.10, 10.0, 2.50, 4.0),
            "claude-opus-5-5": (4.0, 0.20, 20.0, 5.0, 8.0),
            "claude-fable-5-1": (10.0, 0.25, 50.0, 12.50, 20.0),
        }
        for model, per_mtok in expected.items():
            row = CLAUDE_PRICING[model]
            got = (row.input, row.cached_input, row.output, row.cache_write_5m, row.cache_write_1h)
            for g, e in zip(got, per_mtok, strict=True):
                with self.subTest(model=model):
                    self.assertAlmostEqual(g * 1000, e, places=9)  # type: ignore[operator]

    def test_haiku_tier_two(self) -> None:
        row = CLAUDE_PRICING["claude-haiku-5-5"]
        self.assertEqual(row.tier_threshold_tokens, 100_000)
        assert row.tier2 is not None
        self.assertAlmostEqual(row.tier2.input * 1000, 0.50, places=9)
        self.assertAlmostEqual(row.tier2.output * 1000, 2.50, places=9)
        self.assertAlmostEqual(row.tier2.cache_write_5m * 1000, 0.625, places=9)  # type: ignore[operator]
        self.assertAlmostEqual(row.tier2.cached_input * 1000, 0.05, places=9)

    def test_every_row_records_its_source(self) -> None:
        for model in CLAUDE_PRICING:
            url, read_on = CLAUDE_PRICE_SOURCES[model]
            self.assertTrue(url.startswith("https://platform.claude.com/"))
            self.assertIsInstance(read_on, date)

    def test_longest_key_wins(self) -> None:
        self.assertIs(claude_row("claude-haiku-5-5"), CLAUDE_PRICING["claude-haiku-5-5"])
        self.assertIsNone(claude_row("claude-nonexistent-9"))


class CostTests(unittest.TestCase):
    def test_tier_switches_above_100k_total_input(self) -> None:
        row = CLAUDE_PRICING["claude-haiku-5-5"]
        at = row_cost(row, input_tokens=100_000, cached_tokens=0, output_tokens=0)
        over = row_cost(row, input_tokens=100_001, cached_tokens=0, output_tokens=0)
        self.assertAlmostEqual(at, 100_000 * 0.10 / 1e6, places=12)
        self.assertAlmostEqual(over, 100_001 * 0.50 / 1e6, places=12)

    def test_reads_and_writes_count_toward_the_tier(self) -> None:
        row = CLAUDE_PRICING["claude-haiku-5-5"]
        usd = row_cost(
            row,
            input_tokens=120_000,
            cached_tokens=60_000,
            output_tokens=0,
            cache_write_5m_tokens=50_000,
        )
        self.assertAlmostEqual(
            usd, (10_000 * 0.50 + 60_000 * 0.05 + 50_000 * 0.625) / 1e6, places=12
        )

    def test_cache_writes_at_their_rates(self) -> None:
        row = CLAUDE_PRICING["claude-haiku-5-5"]
        usd = row_cost(
            row,
            input_tokens=10_000,
            cached_tokens=3_000,
            output_tokens=1_000,
            cache_write_5m_tokens=2_000,
            cache_write_1h_tokens=1_000,
        )
        expected = (4_000 * 0.10 + 3_000 * 0.01 + 2_000 * 0.125 + 1_000 * 0.20 + 1_000 * 0.50) / 1e6
        self.assertAlmostEqual(usd, expected, places=12)

    def test_container_seconds_at_five_cents_an_hour(self) -> None:
        row = CLAUDE_PRICING["claude-haiku-5-5"]
        usd = row_cost(row, input_tokens=0, cached_tokens=0, output_tokens=0, container_seconds=300)
        self.assertAlmostEqual(usd, 300 / 3600 * 0.05, places=12)

    def test_gemini_rows_cost_exactly_what_they_did(self) -> None:
        rng = random.Random(7)
        row = PriceRow(0.000750, 0.000075, 0.003750)
        for _ in range(500):
            i, c, o = rng.randint(0, 200_000), rng.randint(0, 200_000), rng.randint(0, 40_000)
            self.assertEqual(
                row_cost(row, input_tokens=i, cached_tokens=c, output_tokens=o),
                _old_row_cost(row, input_tokens=i, cached_tokens=c, output_tokens=o),
            )


class ClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.enterContext(record_calls())
        _reset_process_counters()
        today = patch("lemely.io.gemini._today", lambda: _TODAY)
        today.start()
        self.addCleanup(today.stop)

    def _mark(self, client: GeminiClient, model: str = "claude-haiku-5-5") -> None:
        client.generate_structured(
            system_prompt="s",
            user_prompt="u",
            response_schema=AIMarkResponse,
            prompt_version="v1",
            model=model,
            task_tag="correction",
        )

    def test_unpriced_claude_model_fails_before_any_request(self) -> None:
        fake = _FakeAnthropic(_message(_VALID_MARK))
        client = GeminiClient(
            _settings(self.tmp), _genai_client=object(), _anthropic_client=fake, ledger=None
        )
        with self.assertRaises(UnpricedModelError):
            self._mark(client, model="claude-nonexistent-9")
        self.assertEqual(fake.messages.calls, [])
        with self.assertRaises(UnpricedModelError):
            price_row("claude-nonexistent-9", make_settings(self.tmp), on=_TODAY)

    def test_record_carries_cache_writes(self) -> None:
        fake = _FakeAnthropic(
            _message(_VALID_MARK, input_tokens=1_000, cache_write=2_000, cache_read=500)
        )
        client = GeminiClient(
            _settings(self.tmp), _genai_client=object(), _anthropic_client=fake, ledger=None
        )
        self._mark(client)
        (rec,) = process_call_records()
        self.assertEqual(
            (rec.input_tokens, rec.cached_tokens, rec.cache_write_5m_tokens), (3_500, 500, 2_000)
        )
        expected = (1_000 * 0.10 + 500 * 0.01 + 2_000 * 0.125 + 200 * 0.50) / 1e6
        self.assertAlmostEqual(rec.usd_now, expected, places=12)

    def test_inference_geo_is_never_sent(self) -> None:
        fake = _FakeAnthropic(_message(_VALID_MARK))
        client = GeminiClient(
            _settings(self.tmp), _genai_client=object(), _anthropic_client=fake, ledger=None
        )
        self._mark(client)
        self.assertNotIn("inference_geo", fake.messages.calls[0])

    def test_gemini_record_and_log_line_unchanged(self) -> None:
        from tests.gemini_fakes import fake_genai_client

        genai = fake_genai_client()
        genai.models.generate_content.return_value = mock_response(
            '{"awarded_marks": 1, "confidence": 0.9, "feedback": "f", "addresses_question": "yes"}'
        )
        client = GeminiClient(make_settings(self.tmp), _genai_client=genai, ledger=None)
        with capture_logs() as logs:
            self._mark(client, model="gemini-3.8-flash")
        (rec,) = process_call_records()
        self.assertEqual(
            (rec.cache_write_5m_tokens, rec.cache_write_1h_tokens, rec.container_seconds),
            (0, 0, 0.0),
        )
        (line,) = [e for e in logs if e["event"] == "gemini_call"]
        self.assertFalse(
            {"cache_write_5m_tokens", "cache_write_1h_tokens", "container_seconds"} & set(line)
        )
