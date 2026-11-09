"""The per-job LLM cost accumulator (billing spec §5.7 step 4)."""

from __future__ import annotations

import contextvars
import tempfile
import threading
from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest
from pydantic import BaseModel

from lemely.core.schemas import AIMarkResponse
from lemely.io import gemini
from lemely.io.gemini import GeminiClient, _reset_process_counters
from lemely.io.llm.cost_meter import cost_scope, record_llm_cost, usd_decimal
from tests.gemini_fakes import fake_genai_client, make_settings, mock_response
from tests.test_anthropic_adapter import _VALID_MARK, _FakeAnthropic, _message, _settings


class _Reply(BaseModel):
    value: str


def test_scope_sums_every_recorded_cost() -> None:
    with cost_scope() as acc:
        record_llm_cost(Decimal("0.010000"))
        record_llm_cost(Decimal("0.002500"))
    assert acc.total_usd == Decimal("0.012500")
    assert acc.calls == 2


def test_no_scope_records_nothing_and_does_not_raise() -> None:
    record_llm_cost(Decimal("1"))
    with cost_scope() as acc:
        pass
    assert acc.total_usd == Decimal(0)


def test_inner_scope_shadows_the_outer() -> None:
    with cost_scope() as outer:
        record_llm_cost(Decimal("0.1"))
        with cost_scope() as inner:
            record_llm_cost(Decimal("0.2"))
    assert outer.total_usd == Decimal("0.1")
    assert inner.total_usd == Decimal("0.2")


def test_copied_context_threads_feed_the_same_scope() -> None:
    with cost_scope() as acc:
        ctx = contextvars.copy_context()
        worker = threading.Thread(target=ctx.run, args=(record_llm_cost, Decimal("0.3")))
        worker.start()
        worker.join()
    assert acc.total_usd == Decimal("0.3")


def test_a_bare_thread_does_not_see_the_scope() -> None:
    with cost_scope() as acc:
        worker = threading.Thread(target=record_llm_cost, args=(Decimal("0.3"),))
        worker.start()
        worker.join()
    assert acc.total_usd == Decimal(0)


def test_negative_cost_is_refused() -> None:
    with cost_scope(), pytest.raises(ValueError, match="negative"):
        record_llm_cost(Decimal("-0.01"))


def test_usd_decimal_rounds_up_to_micro_dollars() -> None:
    assert usd_decimal(0.0002) == Decimal("0.000200")
    assert usd_decimal(0.0000001) == Decimal("0.000001")
    assert usd_decimal(0.0) == Decimal("0.000000")
    with pytest.raises(ValueError, match="not a USD cost"):
        usd_decimal(float("nan"))


def test_gemini_calls_feed_the_scope() -> None:
    _reset_process_counters()
    with patch("lemely.io.gemini._today", lambda: date(2026, 10, 19)):
        genai = fake_genai_client()
        genai.models.generate_content.side_effect = [
            mock_response('{"value": "a"}', prompt=10_000, candidates=1_000)
        ]
        client = GeminiClient(make_settings(tempfile.mkdtemp()), _genai_client=genai, ledger=None)
        with cost_scope() as acc:
            client.generate_structured(
                system_prompt="s",
                user_prompt="u",
                response_schema=_Reply,
                prompt_version="v1",
                model="gemini-3.8-flash",
                task_tag="extraction",
            )
    assert acc.calls == 1
    assert acc.total_usd == usd_decimal(gemini._process_accumulated_usd)
    assert acc.total_usd > 0


def test_claude_calls_feed_the_scope() -> None:
    _reset_process_counters()
    with patch("lemely.io.gemini._today", lambda: date(2026, 10, 19)):
        fake = _FakeAnthropic(_message(_VALID_MARK, input_tokens=1_000, output_tokens=200))
        client = GeminiClient(
            _settings(tempfile.mkdtemp()), _genai_client=object(), _anthropic_client=fake, ledger=None
        )
        with cost_scope() as acc:
            client.generate_structured(
                system_prompt="s",
                user_prompt="read",
                response_schema=AIMarkResponse,
                prompt_version="v1",
                model="claude-haiku-5-5",
                task_tag="correction",
            )
    # 1,000 in x 0.0001/1k + 200 out x 0.0005/1k (lemely/io/llm/pricing.py).
    assert acc.total_usd == Decimal("0.000200")
    assert acc.calls == 1
