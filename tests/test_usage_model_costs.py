"""Per-model LLM cost accumulator (Phase 07 task 3, part A).

The accumulator sits beside ``cost_meter``: ``GeminiClient._record_spend`` feeds both from
the one price it computes, so the per-model split can never drift from the job total.
"""

from __future__ import annotations

import contextvars
import tempfile
import threading
from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest
from structlog.testing import capture_logs

from lemely.core.schemas import AIMarkResponse
from lemely.io import gemini
from lemely.io.gemini import GeminiClient, _reset_process_counters
from lemely.io.llm.cost_meter import cost_scope, usd_decimal
from lemely.io.llm.model_costs import (
    MODEL_NAME_MAX_LENGTH,
    ModelCostAccumulator,
    model_cost_scope,
    record_model_cost,
)
from tests.gemini_fakes import mock_response
from tests.test_anthropic_adapter import _VALID_MARK, _FakeAnthropic, _message, _settings
from tests.test_cost_meter import _gemini_client, _generate, _Reply

_TODAY = date(2026, 10, 19)
_GEMINI = "gemini-3.8-flash"
_CLAUDE = "claude-haiku-5-5"


def test_two_models_in_one_scope_sum_per_model() -> None:
    with model_cost_scope() as acc:
        record_model_cost(_GEMINI, Decimal("0.002"))
        record_model_cost(_CLAUDE, Decimal("0.001"))
        record_model_cost(_GEMINI, Decimal("0.003"))
    assert acc.totals() == {_GEMINI: Decimal("0.005"), _CLAUDE: Decimal("0.001")}


def test_recording_outside_a_scope_is_a_no_op() -> None:
    record_model_cost(_GEMINI, Decimal("1"))
    with model_cost_scope() as acc:
        pass
    assert acc.totals() == {}


def test_a_model_that_cost_nothing_is_not_listed() -> None:
    with model_cost_scope() as acc:
        record_model_cost(_GEMINI, Decimal(0))
        record_model_cost(_CLAUDE, Decimal("0.001"))
    assert acc.totals() == {_CLAUDE: Decimal("0.001")}


def test_totals_is_a_snapshot() -> None:
    with model_cost_scope() as acc:
        record_model_cost(_GEMINI, Decimal("0.001"))
        snapshot = acc.totals()
        record_model_cost(_GEMINI, Decimal("0.001"))
        snapshot[_CLAUDE] = Decimal(9)
    assert acc.totals() == {_GEMINI: Decimal("0.002")}


def test_a_copy_context_worker_adds_to_the_scope_a_bare_thread_does_not() -> None:
    with model_cost_scope() as acc:
        shared = threading.Thread(
            target=contextvars.copy_context().run,
            args=(record_model_cost, _GEMINI, Decimal("0.004")),
        )
        bare = threading.Thread(target=record_model_cost, args=(_CLAUDE, Decimal("0.009")))
        for worker in (shared, bare):
            worker.start()
            worker.join()
    assert acc.totals() == {_GEMINI: Decimal("0.004")}


def test_concurrent_workers_lose_no_cost() -> None:
    with model_cost_scope() as acc:
        workers = [
            threading.Thread(
                target=contextvars.copy_context().run,
                args=(record_model_cost, _GEMINI, Decimal("0.000001")),
            )
            for _ in range(64)
        ]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
    assert acc.totals() == {_GEMINI: Decimal("0.000064")}


def test_an_inner_scope_shadows_the_outer_one() -> None:
    with model_cost_scope() as outer:
        record_model_cost(_GEMINI, Decimal("0.001"))
        with model_cost_scope() as inner:
            record_model_cost(_CLAUDE, Decimal("0.002"))
        record_model_cost(_GEMINI, Decimal("0.001"))
    assert inner.totals() == {_CLAUDE: Decimal("0.002")}
    assert outer.totals() == {_GEMINI: Decimal("0.002")}


def test_a_scope_that_raised_still_closes() -> None:
    with pytest.raises(RuntimeError), model_cost_scope():
        raise RuntimeError("boom")
    record_model_cost(_GEMINI, Decimal("1"))  # no scope left to receive it
    with model_cost_scope() as acc:
        pass
    assert acc.totals() == {}


@pytest.mark.parametrize(
    "bad", [Decimal("NaN"), Decimal("Infinity"), Decimal("-0.000001")], ids=["nan", "inf", "neg"]
)
def test_add_refuses_a_non_finite_or_negative_cost(bad: Decimal) -> None:
    acc = ModelCostAccumulator()
    with pytest.raises(ValueError, match="finite and non-negative"):
        acc.add(_GEMINI, bad)
    assert acc.totals() == {}
    with model_cost_scope() as scoped, pytest.raises(ValueError, match="finite and non-negative"):
        record_model_cost(_GEMINI, bad)
    assert scoped.totals() == {}


def test_a_long_model_name_is_truncated_and_still_sums_under_one_key() -> None:
    long_name = "m" * (MODEL_NAME_MAX_LENGTH + 40)
    with model_cost_scope() as acc:
        record_model_cost(long_name, Decimal("0.001"))
        record_model_cost(long_name, Decimal("0.002"))
    assert acc.totals() == {"m" * MODEL_NAME_MAX_LENGTH: Decimal("0.003")}


def test_a_name_at_the_limit_is_kept_whole() -> None:
    name = "m" * MODEL_NAME_MAX_LENGTH
    with model_cost_scope() as acc:
        record_model_cost(name, Decimal("0.001"))
    assert list(acc.totals()) == [name]


def test_record_spend_feeds_the_model_the_call_ran_on() -> None:
    _reset_process_counters()
    with patch("lemely.io.gemini._today", lambda: _TODAY):
        client = _gemini_client([mock_response('{"value": "a"}', prompt=10_000, candidates=1_000)])
        with model_cost_scope() as acc:
            _generate(client)
    totals = acc.totals()
    assert list(totals) == [_GEMINI]
    assert totals[_GEMINI] > 0


def test_per_model_totals_equal_the_job_total_across_both_providers() -> None:
    """One source: the Gemini and the Claude call each feed both scopes the same figure."""
    _reset_process_counters()
    with patch("lemely.io.gemini._today", lambda: _TODAY):
        gemini_client = _gemini_client(
            [
                mock_response('{"value": "a"}', prompt=10_000, candidates=1_000),
                mock_response('{"value": "b"}', prompt=2_000, candidates=300),
            ]
        )
        claude_client = GeminiClient(
            _settings(tempfile.mkdtemp()),
            _genai_client=object(),
            _anthropic_client=_FakeAnthropic(
                _message(_VALID_MARK, input_tokens=1_000, output_tokens=200)
            ),
            ledger=None,
        )
        with cost_scope() as job, model_cost_scope() as per_model:
            for prompt in ("first", "second"):  # distinct prompts: the second is not a cache hit
                gemini_client.generate_structured(
                    system_prompt="s",
                    user_prompt=prompt,
                    response_schema=_Reply,
                    prompt_version="v1",
                    model=_GEMINI,
                    task_tag="extraction",
                )
            claude_client.generate_structured(
                system_prompt="s",
                user_prompt="read",
                response_schema=AIMarkResponse,
                prompt_version="v1",
                model=_CLAUDE,
                task_tag="correction",
            )
    totals = per_model.totals()
    assert set(totals) == {_GEMINI, _CLAUDE}
    assert totals[_CLAUDE] == Decimal("0.000200")
    assert sum(totals.values(), Decimal(0)) == job.total_usd
    assert job.calls == 3


@pytest.mark.parametrize("bad", [float("nan"), -0.1], ids=["nan", "negative"])
def test_a_refused_price_skips_both_feeds_without_failing_the_call(bad: float) -> None:
    _reset_process_counters()
    with patch("lemely.io.gemini._today", lambda: _TODAY):
        client = _gemini_client(
            [mock_response('{"value": "a"}', prompt=10_000, candidates=10)],
            model_pricing={_GEMINI: [bad, 0.4]},
        )
        with cost_scope() as job, model_cost_scope() as per_model, capture_logs() as logs:
            reply = _generate(client)
    assert reply.value == "a"
    assert job.calls == 0
    assert per_model.totals() == {}
    assert [e["event"] for e in logs if e["event"] == "usage_cost_unrecordable"] == [
        "usage_cost_unrecordable"
    ]
    assert gemini._process_input_tokens == 10_000


def test_the_model_feed_uses_the_same_rounded_figure_as_the_job_feed() -> None:
    _reset_process_counters()
    with patch("lemely.io.gemini._today", lambda: _TODAY):
        client = _gemini_client([mock_response('{"value": "a"}', prompt=10_007, candidates=13)])
        with cost_scope() as job, model_cost_scope() as per_model:
            _generate(client)
    assert per_model.totals() == {_GEMINI: job.total_usd}
    assert job.total_usd == usd_decimal(gemini._process_accumulated_usd)
