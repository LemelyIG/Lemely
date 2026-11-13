"""Pure subscription arithmetic (Phase 05). No database."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from lemely.core.subscription_rules import (
    AMOUNT_SYNC_WINDOW,
    GRACE_PERIOD,
    MAX_EXTRA_SEATS_AT_CHECKOUT,
    PAYMOB_RETRIAL_DAYS,
    PERIOD_DAYS,
    STALE_CHECKOUT_AFTER,
    calendar_month_bounds,
    is_successful_charge,
    parse_paymob_time,
    paymob_frequency,
    period_end,
    renewal_period_start,
    seat_capacity_for,
    start_of_day,
    subscription_amount_minor,
)
from lemely.db.teacher_team_repo import month_end, month_start
from lemely.io.paymob.client import SUBSCRIPTION_FREQUENCIES

GOOD_CHARGE = {
    "success": True,
    "pending": False,
    "is_voided": False,
    "is_refunded": False,
    "error_occured": False,
}


def test_constants() -> None:
    assert dict(PERIOD_DAYS) == {"monthly": 30, "yearly": 360}
    assert set(PERIOD_DAYS.values()) <= SUBSCRIPTION_FREQUENCIES
    assert timedelta(days=3) == GRACE_PERIOD
    assert timedelta(hours=2) == STALE_CHECKOUT_AFTER
    assert MAX_EXTRA_SEATS_AT_CHECKOUT == 200
    assert timedelta(days=2) == AMOUNT_SYNC_WINDOW


def test_the_paymob_retry_window_is_left_to_paymob() -> None:
    """UD-7 (2026-11-13): Lemely does not set ``retrial_days``."""
    assert PAYMOB_RETRIAL_DAYS is None


def test_period_end_adds_the_paymob_cycle() -> None:
    start = datetime(2026, 1, 31, 12, tzinfo=UTC)
    assert period_end(start, "monthly") == datetime(2026, 3, 2, 12, tzinfo=UTC)
    assert period_end(start, "yearly") == start + timedelta(days=360)


def test_an_unknown_interval_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown plan interval"):
        paymob_frequency("weekly")


def test_amount_is_plan_plus_extra_seats() -> None:
    assert (
        subscription_amount_minor(price_minor=10_000, extra_seats=0, extra_seat_price_minor=0)
        == 10_000
    )
    assert (
        subscription_amount_minor(price_minor=10_000, extra_seats=3, extra_seat_price_minor=2_500)
        == 17_500
    )
    # A tier that sells no extra seats still prices as the plan when none are asked for.
    assert (
        subscription_amount_minor(price_minor=10_000, extra_seats=0, extra_seat_price_minor=2_500)
        == 10_000
    )


def test_extra_seats_on_a_zero_seat_price_are_refused() -> None:
    with pytest.raises(ValueError, match="sells no extra seats"):
        subscription_amount_minor(price_minor=10_000, extra_seats=1, extra_seat_price_minor=0)


@pytest.mark.parametrize(
    ("price", "seats", "seat_price"),
    [(-1, 0, 0), (10_000, -1, 100), (10_000, 1, -100)],
)
def test_negative_amount_inputs_are_refused(price: int, seats: int, seat_price: int) -> None:
    with pytest.raises(ValueError):
        subscription_amount_minor(
            price_minor=price, extra_seats=seats, extra_seat_price_minor=seat_price
        )


def test_seat_capacity() -> None:
    assert seat_capacity_for(included_seats=0, extra_seats=0) == 0
    assert seat_capacity_for(included_seats=10, extra_seats=2) == 12
    with pytest.raises(ValueError):
        seat_capacity_for(included_seats=10, extra_seats=-1)
    with pytest.raises(ValueError):
        seat_capacity_for(included_seats=-1, extra_seats=0)


def test_calendar_month_bounds_are_utc_and_wrap_the_year() -> None:
    assert calendar_month_bounds(datetime(2026, 11, 21, 15, tzinfo=UTC)) == (
        datetime(2026, 11, 1, tzinfo=UTC),
        datetime(2026, 12, 1, tzinfo=UTC),
    )
    assert calendar_month_bounds(datetime(2026, 12, 31, 23, 59, tzinfo=UTC))[1] == datetime(
        2027, 1, 1, tzinfo=UTC
    )
    cairo_midnight = datetime(2026, 12, 1, 0, 30, tzinfo=timezone(timedelta(hours=2)))
    assert calendar_month_bounds(cairo_midnight)[0] == datetime(2026, 11, 1, tzinfo=UTC)


@pytest.mark.parametrize(
    "now", [datetime(2026, 11, 21, 15, tzinfo=UTC), datetime(2026, 12, 31, 23, 59, tzinfo=UTC)]
)
def test_month_bounds_match_the_teacher_team_month(now: datetime) -> None:
    """DV-20: the seat allowance repo cannot import ``teacher_team_repo``, so the pure copy
    of its month arithmetic is pinned here."""
    assert calendar_month_bounds(now) == (month_start(now), month_end(now))


def test_start_of_day() -> None:
    assert start_of_day(datetime(2026, 11, 21, 15, 7, tzinfo=UTC)) == datetime(
        2026, 11, 21, tzinfo=UTC
    )


def test_naive_datetimes_are_refused() -> None:
    naive = datetime(2026, 11, 21, 15)
    with pytest.raises(ValueError, match="timezone-aware"):
        calendar_month_bounds(naive)
    with pytest.raises(ValueError, match="timezone-aware"):
        start_of_day(naive)


def test_a_clean_charge_is_successful() -> None:
    assert is_successful_charge(GOOD_CHARGE)
    assert is_successful_charge({"success": True})  # absent flags read as false


@pytest.mark.parametrize("flag", ["pending", "is_voided", "is_refunded", "error_occured"])
@pytest.mark.parametrize("value", [True, "true"])
def test_a_set_failure_flag_fails_the_charge(flag: str, value: object) -> None:
    assert not is_successful_charge({**GOOD_CHARGE, flag: value})


def test_a_false_flag_does_not_fail_the_charge() -> None:
    assert is_successful_charge({**GOOD_CHARGE, "error_occured": False, "pending": "false"})


@pytest.mark.parametrize("success", [False, "true", 1, None])
def test_only_a_json_true_success_counts(success: object) -> None:
    assert not is_successful_charge({**GOOD_CHARGE, "success": success})
    assert not is_successful_charge({})


def test_parse_paymob_time() -> None:
    assert parse_paymob_time("2026-11-18T13:42:08.456634") == datetime(
        2026, 11, 18, 13, 42, 8, 456634, tzinfo=UTC
    )
    assert parse_paymob_time("2026-11-18T13:42:08+02:00") == datetime(
        2026, 11, 18, 11, 42, 8, tzinfo=UTC
    )
    assert parse_paymob_time("not a time") is None
    assert parse_paymob_time("") is None
    assert parse_paymob_time(None) is None
    assert parse_paymob_time(20261118) is None


def test_renewal_period_start_continues_on_time_and_restarts_late() -> None:
    end = datetime(2026, 12, 10, 9, tzinfo=UTC)
    early = end - timedelta(hours=8)  # Paymob bills on the next_billing date
    late = end + timedelta(days=2)  # after retries
    assert renewal_period_start(current_period_end=end, charged_at=early) == end
    assert renewal_period_start(current_period_end=end, charged_at=late) == late
    assert renewal_period_start(current_period_end=None, charged_at=late) == late
