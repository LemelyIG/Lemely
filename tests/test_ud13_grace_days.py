"""UD13-C (a): one admin grace-days setting drives grace, Paymob retries and drift (T18).

Real Postgres. The setting (``billing_settings.grace_days``, 1 to 7) is read in the transaction
that uses it:

* a renewal failure sets ``grace_until = failure instant + grace_days``, and a row already in
  grace keeps the deadline it was given;
* a plan sync sends ``retrial_days = grace_days`` and stamps it, and a tier whose stamp differs
  from the setting (or is missing) reads ``drifted`` (or ``unverified``) until the admin syncs;
* without the row nothing is guessed (fail closed, alerted).

The seat-charge attempts (P06 T6) and the email copy are pinned in
``test_merchant_charge_renewal_seats.py`` and ``test_billing_email_templates.py``.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import pytest
import sqlalchemy as sa
from structlog.testing import capture_logs

from lemely.db.admin_billing_repo import paymob_drift
from lemely.db.models.billing import PlanTier, Subscription
from lemely.db.models.billing_ops import BillingSettings
from lemely.db.models.enums import PlanInterval, Role, SubscriptionStatus
from lemely.db.subscription_repo import (
    TRIGGER_FAILED,
    GraceSettingMissing,
    SubscriptionService,
    sync_paymob_plan,
)
from tests.subscription_fixtures import (
    T0,
    FakePaymobClient,
    charge,
    ensure_billing_settings,
    paymob_settings,
    remote_subscription,
    seed_subscription,
    seed_tier,
    seed_user,
    subscription_webhook,
    throwaway_database,
)
from tests.team_db import emptied_after

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

PID = 5150
END = T0 + timedelta(days=30)


@pytest.fixture(scope="module")
def _database() -> Iterator[sessionmaker[Session]]:
    with throwaway_database() as factory:
        yield factory


@pytest.fixture
def pg_sessionmaker(_database: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(_database)
    with _database.begin() as session:
        session.execute(sa.text("TRUNCATE paymob_events CASCADE"))


@pytest.fixture
def sm(pg_sessionmaker: sessionmaker[Session]) -> sessionmaker[Session]:
    ensure_billing_settings(pg_sessionmaker)
    return pg_sessionmaker


def _set_grace_days(factory: sessionmaker[Session], days: int) -> None:
    with factory.begin() as session:
        session.execute(sa.update(BillingSettings).values(grace_days=days))


def _linked(factory: sessionmaker[Session], **kwargs: Any) -> uuid.UUID:
    student = seed_user(factory, Role.student)
    tier_id = seed_tier(factory, allowance_units=1_000)
    return seed_subscription(
        factory,
        user_id=student,
        tier_id=tier_id,
        payer_id=student,
        paymob_subscription_id=PID,
        paymob_amount_minor=10_000,
        activated_at=T0,
        **kwargs,
    )


def _client(updated_at: str = "t1") -> FakePaymobClient:
    client = FakePaymobClient()
    client.subscriptions[PID] = remote_subscription(PID, updated_at=updated_at)
    client.last_transactions[PID] = charge(777, 10_000, created_at=T0)
    return client


def _fail(factory: sessionmaker[Session], now: Any, updated_at: str = "t1") -> None:
    with factory.begin() as session:
        SubscriptionService(session, _client(updated_at), paymob_settings()).apply_renewal_webhook(
            subscription_webhook(TRIGGER_FAILED, PID), now=now
        )


def _subscription(factory: sessionmaker[Session], sid: uuid.UUID) -> Subscription:
    with factory() as session:
        row = session.get(Subscription, sid)
        assert row is not None
        return row


# -- grace_until ------------------------------------------------------------------------


@pytest.mark.parametrize("days", [1, 5, 7])
def test_a_renewal_failure_sets_grace_from_the_setting(
    sm: sessionmaker[Session], days: int
) -> None:
    _set_grace_days(sm, days)
    sid = _linked(sm)
    failed_at = END + timedelta(hours=1)
    _fail(sm, failed_at)
    row = _subscription(sm, sid)
    assert (row.status, row.grace_until) == (
        SubscriptionStatus.past_due,
        failed_at + timedelta(days=days),
    )


def test_a_row_already_in_grace_keeps_its_old_deadline_when_the_setting_changes(
    sm: sessionmaker[Session],
) -> None:
    _set_grace_days(sm, 5)
    sid = _linked(sm)
    first = END + timedelta(hours=1)
    _fail(sm, first)
    _set_grace_days(sm, 7)
    # Paymob's retry fails a day later (a new remote stamp): the stored deadline is not recomputed.
    _fail(sm, first + timedelta(days=1), updated_at="t2")
    assert _subscription(sm, sid).grace_until == first + timedelta(days=5)


def test_mark_past_due_reads_the_setting_in_the_calling_transaction(
    sm: sessionmaker[Session],
) -> None:
    """The value is read in the caller's own transaction: an uncommitted change is seen."""
    sid = _linked(sm)
    with sm.begin() as session:
        session.execute(sa.update(BillingSettings).values(grace_days=2))  # not committed yet
        SubscriptionService(session, _client(), paymob_settings()).mark_past_due(sid, now=END)
    assert _subscription(sm, sid).grace_until == END + timedelta(days=2)


def test_without_a_settings_row_no_grace_is_guessed(sm: sessionmaker[Session]) -> None:
    sid = _linked(sm)
    with sm.begin() as session:
        session.execute(sa.delete(BillingSettings))
    with (
        capture_logs() as logs,
        pytest.raises(GraceSettingMissing),
        sm.begin() as session,
    ):
        SubscriptionService(session, _client(), paymob_settings()).mark_past_due(sid, now=END)
    assert _subscription(sm, sid).status is SubscriptionStatus.active
    assert [e["event"] for e in logs if e.get("alert") is True] == ["grace_setting_missing"]


# -- the plan sync ----------------------------------------------------------------------


def test_a_plan_sync_sends_and_stamps_the_setting_as_retrial_days(
    sm: sessionmaker[Session],
) -> None:
    _set_grace_days(sm, 5)
    tier_id = seed_tier(sm, paymob_plan_id=None)
    client = FakePaymobClient()
    with sm.begin() as session:
        sync_paymob_plan(session, client, paymob_settings(), tier_id)
    assert client.calls_to("create_plan")[0]["retrial_days"] == 5
    with sm() as session:
        tier = session.get(PlanTier, tier_id)
        assert tier is not None
        assert tier.paymob_plan_synced_retrial_days == 5
        assert paymob_drift(tier, "test", 5) == "in_sync"
        # The admin lowers the setting: the plan Paymob holds still retries for 5 days.
        assert paymob_drift(tier, "test", 4) == "drifted"


def test_a_failed_sync_stamps_nothing(sm: sessionmaker[Session]) -> None:
    _set_grace_days(sm, 6)
    tier_id = seed_tier(sm, paymob_plan_id=None)
    client = FakePaymobClient()
    client.fail["create_plan"] = RuntimeError("boom")
    with pytest.raises(RuntimeError), sm.begin() as session:
        sync_paymob_plan(session, client, paymob_settings(), tier_id)
    with sm() as session:
        tier = session.get(PlanTier, tier_id)
        assert tier is not None
        assert tier.paymob_plan_synced_retrial_days is None


def test_a_sync_without_a_settings_row_calls_paymob_never(sm: sessionmaker[Session]) -> None:
    tier_id = seed_tier(sm, paymob_plan_id=None)
    with sm.begin() as session:
        session.execute(sa.delete(BillingSettings))
    client = FakePaymobClient()
    with pytest.raises(GraceSettingMissing), sm.begin() as session:
        sync_paymob_plan(session, client, paymob_settings(), tier_id)
    assert client.names() == []


# -- drift ------------------------------------------------------------------------------


def _tier(**fields: Any) -> PlanTier:
    base: dict[str, Any] = {
        "price_minor": 20_000,
        "interval": PlanInterval.monthly,
        "paymob_plan_id": 1,
        "paymob_plan_mode": "test",
        "paymob_plan_synced_price_minor": 20_000,
        "paymob_plan_synced_frequency": 30,
        "paymob_plan_synced_retrial_days": 3,
    }
    return PlanTier(**(base | fields))


def test_drift_compares_the_retrial_stamp_with_the_setting() -> None:
    assert paymob_drift(_tier(), "test", 3) == "in_sync"
    assert paymob_drift(_tier(), "test", 4) == "drifted"
    assert paymob_drift(_tier(paymob_plan_synced_retrial_days=7), "test", 3) == "drifted"


def test_a_missing_retrial_stamp_is_unverified_never_in_sync() -> None:
    assert paymob_drift(_tier(paymob_plan_synced_retrial_days=None), "test", 3) == "unverified"


def test_the_other_drift_reasons_still_win() -> None:
    assert paymob_drift(_tier(paymob_plan_id=None, paymob_plan_mode=None), "test", 3) == (
        "not_synced"
    )
    assert paymob_drift(_tier(), "live", 3) == "drifted"
    assert paymob_drift(_tier(price_minor=30_000), "test", 3) == "drifted"
    assert paymob_drift(_tier(paymob_plan_synced_price_minor=None), "test", 3) == "unverified"
    # A price mismatch is reported even when the retrial stamp is also absent.
    assert (
        paymob_drift(_tier(price_minor=30_000, paymob_plan_synced_retrial_days=None), "test", 3)
        == "drifted"
    )
