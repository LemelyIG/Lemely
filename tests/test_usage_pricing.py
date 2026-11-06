"""Pure usage pricing and value types (Paymob billing spec §4.5, §5.6, §9 "Unit")."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from lemely.core.usage_pricing import (
    GRANT_PRIORITY,
    estimate_range,
    prorate_minor,
    prorate_units,
    usd_to_units,
)
from lemely.core.usage_types import (
    ESTIMATOR_INPUT_KINDS,
    EstimatorParams,
    GrantScope,
    Payer,
    payer_from_json,
    payer_to_json,
)

START = datetime(2026, 11, 1, tzinfo=UTC)
END = datetime(2026, 12, 1, tzinfo=UTC)  # 30 days


# ---------------------------------------------------------------------------
# usd_to_units
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cost", "rate", "units"),
    [
        (Decimal("0"), 1000, 0),
        (Decimal("0.004"), 1000, 4),
        (Decimal("0.0042"), 1000, 5),  # rounds up
        (Decimal("0.000001"), 1000, 1),  # any cost is at least one unit
        (Decimal("1.5"), 200, 300),
    ],
)
def test_usd_to_units_rounds_up(cost: Decimal, rate: int, units: int) -> None:
    assert usd_to_units(cost, rate) == units


def test_usd_to_units_refuses_negative_cost_and_nonpositive_rate() -> None:
    with pytest.raises(ValueError, match="cost_usd"):
        usd_to_units(Decimal("-0.01"), 1000)
    with pytest.raises(ValueError, match="units_per_usd"):
        usd_to_units(Decimal("1"), 0)


# ---------------------------------------------------------------------------
# estimate_range
# ---------------------------------------------------------------------------


def _params(kind: str = "pages") -> EstimatorParams:
    return EstimatorParams(
        version=3, input_kind=kind, base_low=2, base_high=4, per_input_low=1, per_input_high=3
    )


@pytest.mark.parametrize("kind", ["pages", "marks", "questions"])
def test_estimate_range_scales_with_the_input_count(kind: str) -> None:
    assert estimate_range(_params(kind), 0) == (2, 4)
    assert estimate_range(_params(kind), 5) == (7, 19)


def test_estimate_range_ignores_the_count_for_input_kind_none() -> None:
    assert estimate_range(_params("none"), 50) == (2, 4)


def test_estimate_range_refuses_a_negative_count() -> None:
    with pytest.raises(ValueError, match="input_count"):
        estimate_range(_params(), -1)


def test_estimator_params_refuse_inverted_or_unknown_settings() -> None:
    with pytest.raises(ValueError, match="input_kind"):
        EstimatorParams(1, "words", 0, 1, 0, 1)
    with pytest.raises(ValueError, match="base_low"):
        EstimatorParams(1, "pages", 5, 4, 0, 1)
    with pytest.raises(ValueError, match="per_input_low"):
        EstimatorParams(1, "pages", 0, 1, 2, 1)
    assert {"pages", "marks", "questions", "none"} == ESTIMATOR_INPUT_KINDS


# ---------------------------------------------------------------------------
# Proration
# ---------------------------------------------------------------------------


def test_prorate_minor_charges_the_remaining_fraction_rounded_up() -> None:
    assert prorate_minor(30000, START, END, START + timedelta(days=10)) == 20000
    # 1/3 of 100 = 33.33 -> 34
    assert prorate_minor(100, START, END, START + timedelta(days=20)) == 34


def test_prorate_minor_clamps_to_the_period() -> None:
    assert prorate_minor(500, START, END, START - timedelta(days=1)) == 500
    assert prorate_minor(500, START, END, START) == 500
    assert prorate_minor(500, START, END, END) == 0
    assert prorate_minor(500, START, END, END + timedelta(days=3)) == 0


def test_prorate_units_matches_minor_rounding() -> None:
    assert prorate_units(1000, START, END, START + timedelta(days=15)) == 500
    assert prorate_units(10, START, END, START + timedelta(days=29, hours=23)) == 1


def test_proration_refuses_an_empty_period_and_a_negative_amount() -> None:
    with pytest.raises(ValueError, match="period_end"):
        prorate_minor(100, END, START, START)
    with pytest.raises(ValueError, match="amount"):
        prorate_units(-1, START, END, START)


# ---------------------------------------------------------------------------
# GRANT_PRIORITY and Payer
# ---------------------------------------------------------------------------


def test_grant_priority_matches_the_spec_table() -> None:
    assert dict(GRANT_PRIORITY) == {
        "period_allowance": 10,
        "seat_allowance": 10,
        "signup": 20,
        "refund": 30,
        "adjustment": 40,
        "credit_pack": 50,
        "auto_topup": 50,
    }
    with pytest.raises(TypeError):
        GRANT_PRIORITY["signup"] = 1  # type: ignore[index]


def test_payer_rules() -> None:
    owner, member = uuid.uuid4(), uuid.uuid4()
    with pytest.raises(ValueError, match="SEAT payer needs"):
        Payer(owner_user_id=owner, scope=GrantScope.SEAT)
    with pytest.raises(ValueError, match="debt_exempt"):
        Payer(owner_user_id=owner, scope=GrantScope.CREDITS, debt_exempt=True)
    with pytest.raises(ValueError, match="cap_units must be"):
        Payer(owner_user_id=owner, scope=GrantScope.CREDITS, teacher_member_id=member, cap_units=-1)
    with pytest.raises(ValueError, match="capped payer"):
        Payer(owner_user_id=owner, scope=GrantScope.CREDITS, cap_units=10)
    with pytest.raises(ValueError, match="cap_window_start"):
        Payer(owner_user_id=owner, scope=GrantScope.CREDITS, cap_window_start=START)
    seat = Payer(
        owner_user_id=owner, scope=GrantScope.SEAT, teacher_member_id=member, debt_exempt=True
    )
    assert seat.debt_exempt


def test_payer_json_round_trip() -> None:
    payers = [
        Payer(owner_user_id=uuid.uuid4(), scope=GrantScope.ALLOWANCE),
        Payer(
            owner_user_id=uuid.uuid4(),
            scope=GrantScope.SEAT,
            teacher_member_id=uuid.uuid4(),
            debt_exempt=True,
        ),
        Payer(
            owner_user_id=uuid.uuid4(),
            scope=GrantScope.CREDITS,
            teacher_member_id=uuid.uuid4(),
            cap_units=250,
            cap_window_start=START,
        ),
    ]
    for payer in payers:
        assert payer_from_json(payer_to_json(payer)) == payer
