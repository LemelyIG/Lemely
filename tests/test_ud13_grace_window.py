"""T18 review I1: the early-charge window outlasts the longest Paymob retry the setting allows.

An admin may set ``grace_days`` up to ``MAX_GRACE_DAYS`` and a Sync sends it as ``retrial_days``.
A renewal paid on the plan's last retry day restarts our period at that charge, while Paymob keeps
its own anchor, so its next charge or failure can land ``MAX_GRACE_DAYS`` days (plus the Cairo
calendar offset) before our period end. A failure that early is a genuine one and must not be
dropped as ``period_already_paid``.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from structlog.testing import capture_logs

from lemely.core.subscription_rules import MAX_GRACE_DAYS
from lemely.db.admin_billing_repo import AdminInvalidError
from lemely.db.billing_settings_repo import validate_settings
from lemely.db.models.enums import SubscriptionStatus
from lemely.db.subscription_repo import (
    EARLY_CHARGE_WINDOW,
    NEXT_BILLING_EARLIER_TOLERANCE,
    TRIGGER_FAILED,
    TRIGGER_SUCCESS,
)
from tests.subscription_fixtures import charge, ensure_billing_settings, throwaway_database
from tests.team_db import emptied_after
from tests.test_subscription_lifecycle import END, PID, _client, _deliver, _linked, _sub

if TYPE_CHECKING:
    import uuid
    from collections.abc import Iterator
    from datetime import datetime

    from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture(scope="module")
def _database() -> Iterator[sessionmaker[Session]]:
    with throwaway_database() as factory:
        yield factory


@pytest.fixture
def pg_sessionmaker(_database: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    ensure_billing_settings(_database)
    yield from emptied_after(_database)
    with _database.begin() as session:
        session.execute(sa.text("TRUNCATE paymob_events CASCADE"))


def _set_grace(sm: sessionmaker[Session], days: int) -> None:
    with sm.begin() as session:
        session.execute(sa.text("UPDATE billing_settings SET grace_days = :d"), {"d": days})


def _late_paid_then_next_cycle(
    sm: sessionmaker[Session], grace: int
) -> tuple[uuid.UUID, datetime, datetime]:
    """Fail at the end, pay on the plan's last retry day, and return Paymob's next billing.

    Returns ``(subscription, our new period end, Paymob's own next_billing)``: Paymob keeps its
    anchor (one cycle after the original end) while our period restarts at the late charge.
    """
    _set_grace(sm, grace)
    _, sid = _linked(sm)
    _deliver(sm, _client(updated_at="f1"), TRIGGER_FAILED, END - timedelta(hours=2))
    assert _sub(sm, sid).status is SubscriptionStatus.past_due
    paid_at = END + timedelta(days=grace - 1, hours=20)
    client = _client(updated_at="s1")
    client.last_transactions[PID] = charge(888, 10_000, created_at=paid_at)
    _deliver(sm, client, TRIGGER_SUCCESS, paid_at + timedelta(minutes=5))
    sub = _sub(sm, sid)
    assert sub.status is SubscriptionStatus.active
    assert sub.current_period_end == paid_at + timedelta(days=30)
    return sid, sub.current_period_end, END + timedelta(days=30) - timedelta(hours=1)


def test_a_three_day_plans_next_cycle_failure_is_honoured(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sid, _, paymob_next = _late_paid_then_next_cycle(pg_sessionmaker, 3)
    _deliver(pg_sessionmaker, _client(updated_at="f2"), TRIGGER_FAILED, paymob_next)
    assert _sub(pg_sessionmaker, sid).status is SubscriptionStatus.past_due


def test_a_seven_day_plans_next_cycle_failure_is_honoured_not_dropped_as_paid(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sid, end, paymob_next = _late_paid_then_next_cycle(pg_sessionmaker, MAX_GRACE_DAYS)
    assert end - paymob_next > timedelta(days=3, hours=6)  # beyond the old window
    assert end - paymob_next <= EARLY_CHARGE_WINDOW
    with capture_logs() as logs:
        _deliver(pg_sessionmaker, _client(updated_at="f2"), TRIGGER_FAILED, paymob_next)
    reasons = [e.get("reason") for e in logs if e["event"] == "subscription_stale_failure_ignored"]
    assert reasons == []
    assert _sub(pg_sessionmaker, sid).status is SubscriptionStatus.past_due


def test_the_window_and_the_drift_tolerance_follow_the_settings_ceiling() -> None:
    assert timedelta(days=MAX_GRACE_DAYS, hours=6) == EARLY_CHARGE_WINDOW
    assert NEXT_BILLING_EARLIER_TOLERANCE == EARLY_CHARGE_WINDOW


def test_the_ceiling_is_the_upper_bound_of_the_grace_days_check(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """``MAX_GRACE_DAYS`` is the table's CHECK bound and the admin write's bound: one number."""
    _set_grace(pg_sessionmaker, MAX_GRACE_DAYS)  # the ceiling is accepted
    _set_grace(pg_sessionmaker, 1)
    for refused in (MAX_GRACE_DAYS + 1, 0):
        with pytest.raises(IntegrityError), pg_sessionmaker.begin() as session:
            session.execute(sa.text("UPDATE billing_settings SET grace_days = :d"), {"d": refused})
    assert validate_settings({"grace_days": MAX_GRACE_DAYS}) == {"grace_days": MAX_GRACE_DAYS}
    with pytest.raises(AdminInvalidError):
        validate_settings({"grace_days": MAX_GRACE_DAYS + 1})
