"""Pure subscription arithmetic: periods, amounts, seat capacity, month bounds, charge checks.

Paymob billing spec §2.6, §5.2-§5.4, §5.9. No database and no I/O. Intervals are the string
values of ``lemely.db.models.enums.PlanInterval`` (``monthly`` / ``yearly``): ``lemely.core``
never imports ``lemely.db``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Mapping

#: Access continues this long after a failed renewal while Paymob retries (spec §2.6).
GRACE_PERIOD: Final = timedelta(days=3)

#: A first-payment checkout older than this can be replaced by a new one. Paymob intentions
#: expire after 3600 s (spec §5.1 step 2); the second hour absorbs a late callback.
STALE_CHECKOUT_AFTER: Final = timedelta(hours=2)

#: Upper bound on extra seats bought with the first checkout.
MAX_EXTRA_SEATS_AT_CHECKOUT: Final = 200

#: Days per period. Paymob plans accept only 7/15/30/60/90/180/360-day frequencies
#: (research 02 §6), so a month is 30 days and a year 360, and Lemely's period matches the
#: Paymob billing cycle exactly.
PERIOD_DAYS: Final[Mapping[str, int]] = MappingProxyType({"monthly": 30, "yearly": 360})

#: How long a failed renewal keeps being retried at Paymob. ``None`` leaves Paymob's own default
#: in force (decision UD-7 of 2026-11-13: the retry window is not set by Lemely). The plan sync
#: passes this to ``create_plan(retrial_days=...)``, where ``None`` is sent as a null.
PAYMOB_RETRIAL_DAYS: Final[int | None] = None

#: A renewal is checked against its Paymob amount when it is due within this window (DV-16).
AMOUNT_SYNC_WINDOW: Final = timedelta(days=2)

_FAILURE_FLAGS: Final = ("pending", "is_voided", "is_refunded", "error_occured")


def paymob_frequency(interval: str) -> int:
    """The Paymob plan ``frequency`` (days) for a plan interval."""
    try:
        return PERIOD_DAYS[interval]
    except KeyError as exc:
        raise ValueError(f"unknown plan interval {interval!r}") from exc


def period_end(start: datetime, interval: str) -> datetime:
    """End of the period that starts at ``start``."""
    return start + timedelta(days=paymob_frequency(interval))


def subscription_amount_minor(
    *, price_minor: int, extra_seats: int, extra_seat_price_minor: int
) -> int:
    """Plan price plus extra seats, in minor units (spec §5.1 step 1).

    ``extra_seat_price_minor`` is ``0`` on a tier that sells no extra seats.

    Raises:
        ValueError: a negative input, or extra seats on a tier with no seat price.
    """
    if price_minor < 0 or extra_seat_price_minor < 0:
        raise ValueError("prices must be >= 0")
    if extra_seats < 0:
        raise ValueError("extra_seats must be >= 0")
    if extra_seats and extra_seat_price_minor == 0:
        raise ValueError("this tier sells no extra seats")
    return price_minor + extra_seats * extra_seat_price_minor


def seat_capacity_for(*, included_seats: int, extra_seats: int) -> int:
    """Seats a teacher subscription holds: included plus extra (spec §4.4)."""
    if included_seats < 0 or extra_seats < 0:
        raise ValueError("seat counts must be >= 0")
    return included_seats + extra_seats


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")


def calendar_month_bounds(now: datetime) -> tuple[datetime, datetime]:
    """``[start, end)`` of the UTC calendar month containing ``now`` (seat allowances, §5.9)."""
    _require_aware(now, "now")
    start = now.astimezone(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


def start_of_day(now: datetime) -> datetime:
    """Midnight UTC of ``now``'s day; prorating from it counts today as a day left."""
    _require_aware(now, "now")
    return now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


def _is_true(value: object) -> bool:
    return value is True or value == "true"


def is_successful_charge(txn: Mapping[str, object]) -> bool:
    """Paid iff ``success`` is JSON true and no failure flag is set (research 02 §3).

    A flag counts as set when it is JSON true or the string ``"true"``; an absent flag is not set.
    """
    return txn.get("success") is True and not any(_is_true(txn.get(f)) for f in _FAILURE_FLAGS)


def parse_paymob_time(value: object) -> datetime | None:
    """Parse a Paymob timestamp to an aware UTC datetime; ``None`` when unparseable.

    A timestamp without an offset is read as UTC. That is an assumption: no recorded sandbox run
    confirms the timezone of ``created_at`` on ``GET subscriptions/{id}/last-transaction``
    (billing constraints UD-8), so the go-live sandbox checklist verifies it.
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def renewal_period_start(*, current_period_end: datetime | None, charged_at: datetime) -> datetime:
    """Start of the period a successful renewal pays for.

    Paymob bills on the ``next_billing`` date, so an on-time charge can land hours before the
    period ends; it continues the current period with no gap and no overlap. A late charge
    (after retries) starts the new period at the charge.
    """
    if current_period_end is None:
        return charged_at
    return max(current_period_end, charged_at)


__all__ = [
    "AMOUNT_SYNC_WINDOW",
    "GRACE_PERIOD",
    "MAX_EXTRA_SEATS_AT_CHECKOUT",
    "PAYMOB_RETRIAL_DAYS",
    "PERIOD_DAYS",
    "STALE_CHECKOUT_AFTER",
    "calendar_month_bounds",
    "is_successful_charge",
    "parse_paymob_time",
    "paymob_frequency",
    "period_end",
    "renewal_period_start",
    "seat_capacity_for",
    "start_of_day",
    "subscription_amount_minor",
]
