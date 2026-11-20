"""The per-job LLM cost accumulator (billing spec §5.7 step 4)."""

from __future__ import annotations

import contextvars
import math
import tempfile
import threading
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import structlog
from pydantic import BaseModel, ValidationError
from structlog.testing import capture_logs

from lemely.core.schemas import AIMarkResponse
from lemely.io import gemini
from lemely.io.cost_ledger import CostLedger
from lemely.io.gemini import (
    PREFIX_CACHE_TASK_TAG,
    PREFIX_CACHE_TTL_SECONDS,
    GeminiClient,
    SharedPrefix,
    _reset_process_counters,
    prefix_cache_storage_usd,
    price_call,
    process_call_records,
    record_calls,
)
from lemely.io.llm.cost_meter import CostAccumulator, cost_scope, record_llm_cost, usd_decimal
from lemely.io.llm.errors import CapTruncatedError
from lemely.runtime.config import GeminiSettings, Settings
from lemely.runtime.errors import ExternalServiceError
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
            _settings(tempfile.mkdtemp()),
            _genai_client=object(),
            _anthropic_client=fake,
            ledger=None,
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


_TODAY = date(2026, 10, 19)
_MICRO = Decimal("0.000001")


def _assert_matches_spend(acc: CostAccumulator) -> None:
    """The job total is the process spend, up to one rounded-up micro-dollar per call."""
    spent = Decimal(repr(gemini._process_accumulated_usd))
    assert spent <= acc.total_usd < spent + _MICRO * acc.calls


def _gemini_client(
    responses: list[Any], *, model_pricing: dict[str, list[float]] | None = None, ledger: Any = None
) -> GeminiClient:
    """A Gemini-path client on fakes, with no retry sleeping and an optional price override."""
    genai = fake_genai_client()
    genai.models.generate_content.side_effect = responses
    base = make_settings(tempfile.mkdtemp())
    update: dict[str, Any] = {"backoff_seconds": 0.01}
    if model_pricing is not None:
        update["pricing"] = model_pricing
    settings = base.model_copy(update={"gemini": base.gemini.model_copy(update=update)})
    return GeminiClient(settings, _genai_client=genai, ledger=ledger)


def _generate(client: GeminiClient, model: str = "gemini-3.8-flash") -> _Reply:
    reply = client.generate_structured(
        system_prompt="s",
        user_prompt="u",
        response_schema=_Reply,
        prompt_version="v1",
        model=model,
        task_tag="extraction",
    )
    assert isinstance(reply, _Reply)
    return reply


def test_unpriced_model_fallback_is_recorded_once() -> None:
    """The fallback price (not the NaN the call record carries) is what the job is charged."""
    _reset_process_counters()
    with patch("lemely.io.gemini._today", lambda: _TODAY):
        client = _gemini_client([mock_response('{"value": "a"}', prompt=10_000, candidates=1_000)])
        with cost_scope() as acc:
            _generate(client, model="gemini-unknown-zz")
    assert acc.calls == 1
    assert acc.total_usd > 0
    _assert_matches_spend(acc)


def test_schema_correction_retry_records_both_paid_calls() -> None:
    _reset_process_counters()
    with patch("lemely.io.gemini._today", lambda: _TODAY):
        client = _gemini_client(
            [mock_response("not json"), mock_response('{"value": "a"}')],
        )
        with cost_scope() as acc:
            _generate(client)
    assert acc.calls == 2
    _assert_matches_spend(acc)


def test_claude_cap_truncated_retry_records_both_paid_calls() -> None:
    _reset_process_counters()
    truncated = _message(_VALID_MARK, stop_reason="max_tokens")
    with patch("lemely.io.gemini._today", lambda: _TODAY):
        fake = _FakeAnthropic(truncated, _message(_VALID_MARK, stop_reason="max_tokens"))
        client = GeminiClient(
            _settings(tempfile.mkdtemp()),
            _genai_client=object(),
            _anthropic_client=fake,
            ledger=None,
        )
        with cost_scope() as acc, pytest.raises(CapTruncatedError):
            client.generate_structured(
                system_prompt="s",
                user_prompt="read",
                response_schema=AIMarkResponse,
                prompt_version="v1",
                model="claude-haiku-5-5",
                task_tag="correction",
            )
    assert acc.calls == 2
    _assert_matches_spend(acc)
    assert acc.total_usd > 0


def test_provider_error_before_any_reply_records_nothing() -> None:
    _reset_process_counters()
    with patch("lemely.io.gemini._today", lambda: _TODAY):
        client = _gemini_client([RuntimeError("400 bad request")])
        with cost_scope() as acc, pytest.raises(ExternalServiceError):
            _generate(client)
    assert acc.calls == 0
    assert acc.total_usd == Decimal(0)


def test_prefix_cache_creation_and_storage_are_recorded() -> None:
    _reset_process_counters()
    model = "gemini-3.8-flash"
    tokens = 5_000
    with patch("lemely.io.gemini._today", lambda: _TODAY):
        client = _gemini_client([])
        client._client.caches.create.side_effect = [  # type: ignore[attr-defined]
            SimpleNamespace(
                name="cachedContents/a", usage_metadata=SimpleNamespace(total_token_count=tokens)
            )
        ]
        with cost_scope() as acc:
            handle = client.cached_prefix_handle(
                model,
                SharedPrefix(
                    instructions="a", paper="b", text="a\n\nb", cache="explicit", version="v1"
                ),
                log=structlog.get_logger(),
            )
        creation = price_call(
            model,
            client._settings,
            input_tokens=tokens,
            cached_tokens=0,
            output_tokens=0,
            on=_TODAY,
        )
        storage = prefix_cache_storage_usd(model, tokens, PREFIX_CACHE_TTL_SECONDS, on=_TODAY)
    assert handle == "cachedContents/a"
    assert storage > 0
    assert acc.calls == 1
    assert usd_decimal(creation + storage) == acc.total_usd
    assert gemini._process_cost_by_task[PREFIX_CACHE_TASK_TAG] > 0


@pytest.mark.parametrize("bad", [float("nan"), -0.1], ids=["nan", "negative"])
def test_a_bad_price_never_fails_a_paid_call(bad: float) -> None:
    """A price the accumulator refuses is logged and skipped; the spend is still accounted for."""
    _reset_process_counters()
    ledger = MagicMock(spec=CostLedger)
    ledger.total.return_value = 0.0
    ledger.add.return_value = (1.0, [])
    with patch("lemely.io.gemini._today", lambda: _TODAY):
        client = _gemini_client(
            [mock_response('{"value": "a"}', prompt=10_000, candidates=10)],
            model_pricing={"gemini-3.8-flash": [bad, 0.4]},
            ledger=ledger,
        )
        with cost_scope() as acc, capture_logs() as logs, record_calls():
            reply = _generate(client)
            records = process_call_records()
    assert reply.value == "a"
    assert acc.calls == 0
    [record] = records
    assert (record.task_tag, record.input_tokens) == ("extraction", 10_000)
    assert [e["event"] for e in logs if e["event"] == "usage_cost_unrecordable"] == [
        "usage_cost_unrecordable"
    ]
    assert any(e["event"] == "gemini_call" for e in logs)
    ledger.add.assert_called_once()
    assert gemini._process_input_tokens == 10_000
    assert "extraction" in gemini._process_cost_by_task


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -0.1])
def test_load_refuses_a_non_finite_or_negative_price(bad: float) -> None:
    with pytest.raises(ValidationError, match="finite and non-negative"):
        GeminiSettings(pricing={"gemini-3.8-flash": [bad, 0.4]})
    with pytest.raises(ValidationError, match="finite and non-negative"):
        Settings.model_validate({"gemini": {"pricing": {"m": [0.1, bad]}}})


def test_load_accepts_a_sane_price_override() -> None:
    assert GeminiSettings(pricing={"m": [0.1, 0.0]}).pricing == {"m": [0.1, 0.0]}


def test_accumulator_add_stays_strict() -> None:
    acc = CostAccumulator()
    for bad in (Decimal("NaN"), Decimal("Infinity"), Decimal("-1")):
        with pytest.raises(ValueError, match="finite and non-negative"):
            acc.add(bad)
    assert acc.calls == 0


def test_usd_decimal_refuses_negative_and_infinite() -> None:
    for bad in (-0.01, math.inf):
        with pytest.raises(ValueError, match="not a USD cost"):
            usd_decimal(bad)
