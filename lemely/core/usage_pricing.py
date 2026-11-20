"""Pure usage pricing: units from USD, estimate ranges, proration (spec §3, §4.1, §4.5).

No database and no I/O. Every number here is an integer except the USD cost,
which is a :class:`~decimal.Decimal`. Rounding always favours Lemely's books
staying whole: a charge rounds up (``usd_to_units``) and a prorated price rounds
up (``prorate_minor``); a prorated allowance also rounds up (``prorate_units``),
so a user is never short-changed by a fraction of a unit.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import ROUND_CEILING, Decimal
from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    from lemely.core.usage_types import EstimatorParams

#: Spend-order priority per ``GrantKind`` value (spec §4.5). Lower spends first.
GRANT_PRIORITY: Mapping[str, int] = MappingProxyType(
    {
        "period_allowance": 10,
        "seat_allowance": 10,
        "signup": 20,
        "refund": 30,
        "adjustment": 40,
        "credit_pack": 50,
        "auto_topup": 50,
    }
)

_MICROSECOND = timedelta(microseconds=1)


def usd_to_units(cost_usd: Decimal, units_per_usd: int) -> int:
    """``ceil(cost_usd * units_per_usd)``; a zero cost is zero units."""
    if units_per_usd <= 0:
        raise ValueError("units_per_usd must be > 0")
    if cost_usd < 0:
        raise ValueError("cost_usd must be >= 0")
    return int((cost_usd * units_per_usd).to_integral_value(rounding=ROUND_CEILING))


def estimate_range(params: EstimatorParams, input_count: int) -> tuple[int, int]:
    """``(low, high)`` units for ``input_count`` inputs; ``none`` ignores the count."""
    if input_count < 0:
        raise ValueError("input_count must be >= 0")
    count = 0 if params.input_kind == "none" else input_count
    return (
        params.base_low + params.per_input_low * count,
        params.base_high + params.per_input_high * count,
    )


def _prorate_ceil(amount: int, period_start: datetime, period_end: datetime, now: datetime) -> int:
    if amount < 0:
        raise ValueError("amount must be >= 0")
    if period_end <= period_start:
        raise ValueError("period_end must be after period_start")
    if now <= period_start:
        return amount
    if now >= period_end:
        return 0
    total = (period_end - period_start) // _MICROSECOND
    left = (period_end - now) // _MICROSECOND
    return -(-amount * left // total)


def prorate_minor(
    amount_minor: int, period_start: datetime, period_end: datetime, now: datetime
) -> int:
    """The share of ``amount_minor`` for the rest of the period, rounded up, in 0..amount."""
    return _prorate_ceil(amount_minor, period_start, period_end, now)


def prorate_units(units: int, period_start: datetime, period_end: datetime, now: datetime) -> int:
    """The share of ``units`` for the rest of the period, rounded up, in 0..units."""
    return _prorate_ceil(units, period_start, period_end, now)


__all__ = ["GRANT_PRIORITY", "estimate_range", "prorate_minor", "prorate_units", "usd_to_units"]
