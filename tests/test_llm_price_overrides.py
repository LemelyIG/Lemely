"""Admin AI token price overrides: the runtime registry and its refresh (UD13-D, Phase 07 T19).

Pinned here: the resolution order (exact override over config over code), the NULL cache fallbacks,
the flat price with no tier 2, the exact per-million to per-1k conversion, the bounds that keep a
recorded cost from going negative, ``NaN`` or silently zero, the atomic swap that threads see, the
refresh (a failure keeps the last snapshot, a bad row is skipped, a slow older load never wins), and
that a metered job settles at the override and at the code price again once it is cleared.
"""

from __future__ import annotations

import contextlib
import math
import tempfile
import threading
import time
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
import sqlalchemy as sa
from structlog.testing import capture_logs

from lemely.core.metered_actions import MeteredAction
from lemely.db.billing_settings_repo import BillingSettingsService
from lemely.db.llm_price_repo import LlmPriceService, LlmPriceView, list_overrides
from lemely.db.models.billing_ops import BillingSettings, LlmPriceOverride
from lemely.db.models.enums import Role
from lemely.io import gemini
from lemely.io.gemini import (
    UnpricedModelError,
    _reset_process_counters,
    _resolve_pricing,
    price_call,
    price_row,
)
from lemely.io.llm import price_overrides
from lemely.io.llm.price_overrides import InvalidPriceError, Override, Snapshot
from lemely.io.llm.pricing import CLAUDE_PRICING, PriceRow, claude_row, row_cost
from lemely.web import llm_price_refresh
from lemely.web.usage import UsageMeter, UsageRequest
from tests.admin_billing_db import NOW, add_user, billing_database, emptied_after
from tests.gemini_fakes import make_settings, mock_response
from tests.test_cost_meter import _gemini_client, _generate
from tests.usage_helpers import NOW as USAGE_NOW
from tests.usage_helpers import give, jobs_for, seed_catalogue, seed_user

if TYPE_CHECKING:
    import uuid
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

_HAIKU = "claude-haiku-5-5"
_SONNET = "claude-sonnet-5-5"
_GEMINI = "gemini-3.8-flash"
_TODAY = date(2026, 10, 19)
_D = Decimal


@pytest.fixture(autouse=True)
def _clean_registry() -> Iterator[None]:
    price_overrides.install(None)
    llm_price_refresh.reset_failures()
    yield
    price_overrides.install(None)
    llm_price_refresh.reset_failures()


def _snapshot(*overrides: Override, hour: Decimal | None = None) -> Snapshot:
    return Snapshot(
        overrides={o.model: o for o in overrides}, code_execution_usd_per_hour=hour, loaded_at=NOW
    )


def _override(model: str = _SONNET, /, **rates: object) -> Override:
    values: dict[str, object] = {
        "input_usd_per_mtok": _D("3"),
        "output_usd_per_mtok": _D("15"),
    }
    values.update(rates)
    return Override(model=model, **values)  # type: ignore[arg-type]


# --- resolution ---------------------------------------------------------------------------


def test_with_nothing_installed_the_code_row_applies() -> None:
    assert claude_row(_SONNET) == CLAUDE_PRICING[_SONNET]


def test_an_exact_override_beats_config_which_beats_code() -> None:
    config = PriceRow(0.5, 0.5, 0.6)
    code = PriceRow(0.1, 0.1, 0.2)
    assert price_overrides.resolve("m", code, config_row=config) == config
    assert price_overrides.resolve("m", code) == code
    price_overrides.install(_snapshot(_override("m")))
    row = price_overrides.resolve("m", code, config_row=config)
    assert row is not None
    assert (row.input, row.output) == (0.003, 0.015)


def test_the_override_matches_the_model_id_exactly_not_by_substring() -> None:
    price_overrides.install(_snapshot(_override("claude-sonnet-5")))
    assert claude_row(_SONNET) == CLAUDE_PRICING[_SONNET]
    price_overrides.install(_snapshot(_override(_SONNET)))
    assert claude_row("claude-sonnet-5-5-20260101") == CLAUDE_PRICING[_SONNET]


def test_price_row_applies_config_over_code_and_override_over_both() -> None:
    settings = make_settings(tempfile.mkdtemp())
    pricing = {_GEMINI: [0.5, 0.6]}
    settings = settings.model_copy(
        update={"gemini": settings.gemini.model_copy(update={"pricing": pricing})}
    )
    assert price_row(_GEMINI, settings, on=_TODAY).input == 0.5
    price_overrides.install(_snapshot(_override(_GEMINI)))
    row = price_row(_GEMINI, settings, on=_TODAY)
    assert (row.input, row.output) == (0.003, 0.015)


def test_an_override_prices_a_model_the_code_does_not_know() -> None:
    settings = make_settings(tempfile.mkdtemp())
    with pytest.raises(UnpricedModelError):
        price_row("claude-new-9", settings, on=_TODAY)
    price_overrides.install(_snapshot(_override("claude-new-9")))
    assert price_row("claude-new-9", settings, on=_TODAY).input == 0.003
    assert claude_row("claude-new-9") is not None


def test_the_unrecognised_model_fallback_also_honours_an_override() -> None:
    settings = make_settings(tempfile.mkdtemp())
    price_overrides.install(_snapshot(_override("odd-model")))
    assert _resolve_pricing("odd-model", settings) == (0.003, 0.015)


def test_a_null_cache_rate_falls_back_to_the_code_row_then_to_input() -> None:
    price_overrides.install(_snapshot(_override(_SONNET)))
    row = claude_row(_SONNET)
    code = CLAUDE_PRICING[_SONNET]
    assert row is not None
    assert (row.cached_input, row.cache_write_5m, row.cache_write_1h) == (
        code.cached_input,
        code.cache_write_5m,
        code.cache_write_1h,
    )
    # No code row for the model: cached bills at the override's input, writes stay None (= input).
    bare = _override("claude-new-9").to_row(None)
    assert bare.cached_input == bare.input
    assert bare.cache_write_5m is None
    assert bare.cache_write_1h is None


def test_a_given_cache_rate_wins_over_the_code_row() -> None:
    row = _override(
        cached_input_usd_per_mtok=_D("0.3"),
        cache_write_5m_usd_per_mtok=_D("3.75"),
        cache_write_1h_usd_per_mtok=_D("6"),
    ).to_row(CLAUDE_PRICING[_SONNET])
    assert (row.cached_input, row.cache_write_5m, row.cache_write_1h) == (0.0003, 0.00375, 0.006)


def test_with_no_tier_two_the_override_is_flat_even_over_a_tiered_code_row() -> None:
    price_overrides.install(_snapshot(_override(_HAIKU)))
    assert CLAUDE_PRICING[_HAIKU].tier2 is not None
    row = claude_row(_HAIKU)
    assert row is not None
    assert row.tier2 is None
    assert row.tier_threshold_tokens is None
    small = row_cost(row, input_tokens=1_000, cached_tokens=0, output_tokens=0)
    big = row_cost(row, input_tokens=1_000_000, cached_tokens=0, output_tokens=0)
    assert big == pytest.approx(small * 1000)


def test_a_tier_two_override_changes_the_rate_above_the_threshold() -> None:
    row = _override(
        tier_threshold_tokens=100_000,
        tier2_input_usd_per_mtok=_D("6"),
        tier2_output_usd_per_mtok=_D("30"),
        cached_input_usd_per_mtok=_D("0.3"),
    ).to_row(None)
    assert row.tier_threshold_tokens == 100_000
    assert row.tier2 is not None
    assert (row.tier2.input, row.tier2.output) == (0.006, 0.03)
    assert row.tier2.cached_input == pytest.approx(0.0006)  # scaled by tier2 / tier1 input
    assert row_cost(row, input_tokens=200_000, cached_tokens=0, output_tokens=0) == pytest.approx(
        1.2
    )


# --- exact conversion ---------------------------------------------------------------------


@pytest.mark.parametrize("per_mtok", ["0.009", "0.015", "0.571429", "2.142857", "3", "15"])
def test_per_mtok_converts_to_per_1k_exactly(per_mtok: str) -> None:
    row = _override(input_usd_per_mtok=_D(per_mtok)).to_row(None)
    assert row.input == float(_D(per_mtok) / 1000)


def test_the_conversion_is_not_done_in_float() -> None:
    # float(0.009) / 1000 differs from the exact decimal answer in the last bit.
    assert float(_D("0.009")) / 1000 != float(_D("0.009") / 1000)
    assert _override(input_usd_per_mtok=_D("0.009")).to_row(None).input == float(_D("0.000009"))


# --- bounds: never negative, NaN or silently zero ----------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        _D(0),
        _D("-0.000001"),
        _D("NaN"),
        _D("Infinity"),
        _D("-Infinity"),
        _D("1000.000001"),
        _D("0.0000001"),
        _D("1E+4"),
        1.5,
        "3",
        True,
    ],
    ids=["zero", "neg", "nan", "inf", "-inf", "over", "7places", "1e4", "float", "str", "bool"],
)
def test_an_input_price_outside_the_bounds_is_refused(bad: object) -> None:
    with pytest.raises(InvalidPriceError, match="inputUsdPerMtok"):
        _override(input_usd_per_mtok=bad)


@pytest.mark.parametrize(
    "name",
    [
        "output_usd_per_mtok",
        "cached_input_usd_per_mtok",
        "cache_write_5m_usd_per_mtok",
        "cache_write_1h_usd_per_mtok",
    ],
)
def test_every_other_rate_is_bounded_the_same_way(name: str) -> None:
    for bad in (_D(0), _D("-1"), _D("NaN"), _D("1001")):
        with pytest.raises(InvalidPriceError):
            _override(**{name: bad})
    assert _override(**{name: _D("1000")})  # the edge is legal


def test_the_tier_trio_is_all_or_none_with_a_bounded_threshold() -> None:
    with pytest.raises(InvalidPriceError, match="tierThresholdTokens"):
        _override(tier_threshold_tokens=1000)
    with pytest.raises(InvalidPriceError, match="tierThresholdTokens"):
        _override(tier2_input_usd_per_mtok=_D("1"), tier2_output_usd_per_mtok=_D("2"))
    for bad in (0, -1, 10_000_001, True):
        with pytest.raises(InvalidPriceError, match="tierThresholdTokens"):
            _override(
                tier_threshold_tokens=bad,
                tier2_input_usd_per_mtok=_D("1"),
                tier2_output_usd_per_mtok=_D("2"),
            )
    with pytest.raises(InvalidPriceError, match="tier2OutputUsdPerMtok"):
        _override(
            tier_threshold_tokens=10,
            tier2_input_usd_per_mtok=_D("1"),
            tier2_output_usd_per_mtok=_D(0),
        )


def test_every_legal_extreme_gives_a_finite_positive_cost() -> None:
    for rate in (_D("0.000001"), _D("1000")):
        row = _override(input_usd_per_mtok=rate, output_usd_per_mtok=rate).to_row(None)
        cost = row_cost(row, input_tokens=1_000_000, cached_tokens=0, output_tokens=1_000_000)
        assert math.isfinite(cost)
        assert cost > 0


def test_the_container_hour_price_is_bounded_and_applied() -> None:
    base = row_cost(
        CLAUDE_PRICING[_SONNET],
        input_tokens=0,
        cached_tokens=0,
        output_tokens=0,
        container_seconds=3600,
    )
    assert base == pytest.approx(0.05)
    price_overrides.install(_snapshot(hour=_D("0.25")))
    assert row_cost(
        CLAUDE_PRICING[_SONNET],
        input_tokens=0,
        cached_tokens=0,
        output_tokens=0,
        container_seconds=3600,
    ) == pytest.approx(0.25)
    for bad in (_D(0), _D("-1"), _D("NaN"), _D("100.000001")):
        with pytest.raises(InvalidPriceError):
            _snapshot(hour=bad)


# --- the snapshot swap --------------------------------------------------------------------


def test_a_snapshot_is_immutable_and_copies_what_it_is_given() -> None:
    mine = {_SONNET: _override()}
    snap = Snapshot(overrides=mine, code_execution_usd_per_hour=None, loaded_at=NOW)
    mine["other"] = _override("other")
    assert set(snap.overrides) == {_SONNET}
    with pytest.raises(TypeError):
        snap.overrides["x"] = _override("x")  # type: ignore[index]
    with pytest.raises(AttributeError):
        snap.loaded_at = NOW  # type: ignore[misc]


def test_install_swaps_the_whole_snapshot_and_a_held_one_never_changes() -> None:
    first = _snapshot(_override(input_usd_per_mtok=_D("3")))
    second = _snapshot(_override(input_usd_per_mtok=_D("9")))
    price_overrides.install(first)
    held = price_overrides.current()
    price_overrides.install(second)
    assert held is first
    assert first.overrides[_SONNET].input_usd_per_mtok == _D("3")
    assert price_overrides.current() is second


def test_threads_see_whole_snapshots_while_one_is_swapped_continuously() -> None:
    """Every read is one of the two installed rows, never an empty gap or a mix of both."""
    pairs = [(_D("3"), _D("18")), (_D("7"), _D("49"))]
    snaps = [_snapshot(_override(input_usd_per_mtok=i, output_usd_per_mtok=o)) for i, o in pairs]
    allowed = {
        (row.input, row.output) for row in (snap.overrides[_SONNET].to_row(None) for snap in snaps)
    }
    stop = threading.Event()
    torn: list[tuple[float, float]] = []

    def reader() -> None:
        while not stop.is_set():
            row = claude_row(_SONNET)
            assert row is not None
            if (row.input, row.output) not in allowed:
                torn.append((row.input, row.output))

    price_overrides.install(snaps[0])
    readers = [threading.Thread(target=reader) for _ in range(4)]
    for t in readers:
        t.start()
    deadline = time.monotonic() + 0.4
    index = 0
    while time.monotonic() < deadline:
        price_overrides.install(snaps[index % 2])
        index += 1
    stop.set()
    for t in readers:
        t.join()
    assert torn == []
    assert index > 10


def test_a_published_snapshot_is_what_a_worker_thread_reads() -> None:
    price_overrides.install(_snapshot(_override(input_usd_per_mtok=_D("8"))))
    seen: list[float] = []

    def worker() -> None:
        row = claude_row(_SONNET)
        assert row is not None
        seen.append(row.input)

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()
    assert seen == [0.008]


# --- refresh, with a database -------------------------------------------------------------


@pytest.fixture(scope="module")
def billing_db() -> Iterator[sessionmaker[Session]]:
    with billing_database() as factory:
        yield factory


@pytest.fixture
def sm(billing_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(billing_db)


@pytest.fixture
def admin(sm: sessionmaker[Session]) -> uuid.UUID:
    return add_user(sm, Role.platform_admin)


def _set(
    sm: sessionmaker[Session], admin: uuid.UUID, model: str = _SONNET, **extra: object
) -> None:
    rates: dict[str, object] = {
        "input_usd_per_mtok": _D("3"),
        "output_usd_per_mtok": _D("15"),
        **extra,
    }
    with sm.begin() as session:
        LlmPriceService(session, now=lambda: NOW).set_price(
            admin, model=model, rates=rates, expected_version=None, reason="test price"
        )


def test_refresh_installs_the_table_and_the_container_hour(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    _set(sm, admin)
    with sm.begin() as session:
        BillingSettingsService(session, now=lambda: NOW).update(
            admin,
            fields={"code_execution_usd_per_hour": _D("0.2")},
            expected_version=1,
            reason="container hour",
        )
    assert llm_price_refresh.refresh_prices(sm) == 1
    snap = price_overrides.current()
    assert snap is not None
    assert snap.overrides[_SONNET].input_usd_per_mtok == _D("3")
    assert snap.code_execution_usd_per_hour == _D("0.2")


def test_clearing_and_refreshing_returns_the_code_value(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    _set(sm, admin)
    llm_price_refresh.refresh_prices(sm)
    assert claude_row(_SONNET) != CLAUDE_PRICING[_SONNET]
    with sm.begin() as session:
        LlmPriceService(session, now=lambda: NOW).clear_price(
            admin, model=_SONNET, expected_version=1, reason="back to code"
        )
    llm_price_refresh.refresh_prices(sm)
    assert claude_row(_SONNET) == CLAUDE_PRICING[_SONNET]


def test_a_failed_refresh_keeps_the_last_snapshot_and_logs(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    _set(sm, admin)
    llm_price_refresh.refresh_prices(sm)
    kept = price_overrides.current()
    with (
        patch.object(llm_price_refresh, "list_overrides", side_effect=RuntimeError("db down")),
        capture_logs() as logs,
        pytest.raises(RuntimeError),
    ):
        llm_price_refresh.refresh_prices(sm)
    assert price_overrides.current() is kept
    failed = [e for e in logs if e["event"] == "llm_price_refresh_failed"]
    assert len(failed) == 1
    assert failed[0]["alert"] is False


def test_the_fifth_failure_in_a_row_alerts_and_a_success_resets_the_count(
    sm: sessionmaker[Session],
) -> None:
    with (
        patch.object(llm_price_refresh, "list_overrides", side_effect=RuntimeError("db down")),
        capture_logs() as logs,
    ):
        for _ in range(5):
            llm_price_refresh.refresh_after_commit(sm)  # never raises
    assert [e["alert"] for e in logs if e["event"] == "llm_price_refresh_failed"] == [
        False,
        False,
        False,
        False,
        True,
    ]
    llm_price_refresh.refresh_prices(sm)
    with (
        patch.object(llm_price_refresh, "list_overrides", side_effect=RuntimeError("db down")),
        capture_logs() as logs,
        contextlib.suppress(RuntimeError),
    ):
        llm_price_refresh.refresh_prices(sm)
    assert [e["alert"] for e in logs if e["event"] == "llm_price_refresh_failed"] == [False]


def test_a_row_the_database_holds_but_the_bounds_refuse_is_skipped_loudly(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    """A direct edit can store a zero price (the CHECK allows it); it must never be installed."""
    _set(sm, admin, _SONNET)
    _set(sm, admin, "claude-opus-5-5")
    with sm.begin() as session:
        session.execute(
            sa.update(LlmPriceOverride)
            .where(LlmPriceOverride.model == _SONNET)
            .values(input_usd_per_mtok=0)
        )
        session.execute(sa.update(BillingSettings).values(code_execution_usd_per_hour=0))
    with capture_logs() as logs:
        assert llm_price_refresh.refresh_prices(sm) == 1
    snap = price_overrides.current()
    assert snap is not None
    assert set(snap.overrides) == {"claude-opus-5-5"}
    assert snap.code_execution_usd_per_hour is None
    assert claude_row(_SONNET) == CLAUDE_PRICING[_SONNET]
    events = {e["event"]: e for e in logs}
    assert events["llm_price_override_ignored"]["alert"] is True
    assert events["llm_price_code_execution_ignored"]["alert"] is True


def test_a_slow_older_load_cannot_install_after_a_newer_one(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    """Load and install share one lock, so loads install in the order they read the table."""
    _set(sm, admin)
    entered = threading.Event()
    release = threading.Event()
    calls: list[int] = []

    def slow_first(session: Session) -> list[LlmPriceView]:
        rows = list_overrides(session)  # the first load reads the old price, then stalls
        calls.append(1)
        if len(calls) == 1:
            entered.set()
            release.wait(5)
        return rows

    with patch.object(llm_price_refresh, "list_overrides", slow_first):
        older = threading.Thread(target=llm_price_refresh.refresh_prices, args=(sm,))
        older.start()
        assert entered.wait(5)
        with sm.begin() as session:
            row = session.scalar(sa.select(LlmPriceOverride))
            assert row is not None
            row.input_usd_per_mtok = _D("9")
            row.version += 1
        newer = threading.Thread(target=llm_price_refresh.refresh_prices, args=(sm,))
        newer.start()
        newer.join(1)  # with the lock it waits for the older load; without, it installs now
        release.set()
        older.join(5)
        newer.join(5)
    snap = price_overrides.current()
    assert snap is not None
    assert snap.overrides[_SONNET].input_usd_per_mtok == _D("9")


# --- a metered job -----------------------------------------------------------------------


def _student(sm: sessionmaker[Session]) -> uuid.UUID:
    seed_catalogue(sm)
    student = seed_user(sm)
    give(sm, student, units=100_000)
    return student


def _run_job(sm: sessionmaker[Session], student: uuid.UUID) -> tuple[Decimal, int]:
    _reset_process_counters()
    meter = UsageMeter(sm, enforce=True, now=lambda: USAGE_NOW)
    request = UsageRequest(
        actor_user_id=student, actor_role=Role.student, action=MeteredAction.MARK_PAPER
    )
    with patch.object(gemini, "_today", lambda: _TODAY):
        client = _gemini_client([mock_response('{"value": "a"}', prompt=10_000, candidates=1_000)])
        with meter.reserve(meter.authorize(request)).run():
            _generate(client)
    job = jobs_for(sm, student)[-1]
    assert job.actual_cost_usd is not None
    return job.actual_cost_usd, job.charged


def test_a_metered_job_settles_at_the_override_and_at_the_code_price_once_cleared(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    student = _student(sm)
    admin = add_user(sm, Role.platform_admin)
    code_cost, code_units = _run_job(sm, student)
    assert code_cost == _D("0.011250")  # 10k in at 0.00075/1k + 1k out at 0.00375/1k

    _set(sm, admin, _GEMINI)  # $3 in / $15 out per MTok: 10k in = 0.03, 1k out = 0.015
    llm_price_refresh.refresh_prices(sm)
    override_cost, override_units = _run_job(sm, student)
    assert override_cost == _D("0.045000")
    assert override_units > code_units

    with sm.begin() as session:
        LlmPriceService(session, now=lambda: NOW).clear_price(
            admin, model=_GEMINI, expected_version=1, reason="back to code"
        )
    llm_price_refresh.refresh_prices(sm)
    assert _run_job(sm, student) == (code_cost, code_units)


def test_price_call_uses_the_override_for_the_2027_projection_too() -> None:
    settings = make_settings(tempfile.mkdtemp())
    price_overrides.install(_snapshot(_override(_GEMINI)))
    now = price_call(
        _GEMINI, settings, input_tokens=1000, cached_tokens=0, output_tokens=0, on=_TODAY
    )
    later = price_call(
        _GEMINI,
        settings,
        input_tokens=1000,
        cached_tokens=0,
        output_tokens=0,
        on=gemini.PRICE_DATE_2027,
    )
    assert now == later == pytest.approx(0.003)


def test_the_registry_imports_neither_the_database_nor_the_web_layer() -> None:
    """``lemely.io`` may not reach ``lemely.db``; the registry is fed from outside."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(price_overrides))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    assert not {m for m in imported if m.startswith(("lemely.db", "lemely.web", "sqlalchemy"))}
