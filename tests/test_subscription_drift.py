"""The daily drift check repairs what missed webhooks left behind (spec §5.2 Daily job).

Real Postgres (a throwaway ``create_all`` database). Everything Paymob says is read before the
row lock and applied under it, one transaction per row. A renewal is accepted by the one rule of
``_apply_successful_charge`` (DV-12); a Paymob-side cancel or suspension is mirrored as a cancel at
period end (UD-4 (b)); an amount drift goes back through the one PUT helper (DV-18); an ended plan
whose Paymob subscription is still open is cancelled (DV-27). Also here: the full-refund hook
(UD-6 (a)) and the first-checkout seat ceiling read from ``billing_settings`` (UD-13).
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
import sqlalchemy as sa
from structlog.testing import capture_logs

from lemely.core.subscription_rules import PAYMOB_ACCOUNT_TZ
from lemely.db.billing_repo import CheckoutUnavailable
from lemely.db.merchant_charge_repo import current_period
from lemely.db.models.billing import (
    Payment,
    PaymentPurpose,
    PaymobEvent,
    PaymobEventKind,
    PlanAudience,
    Subscription,
    SubscriptionPeriod,
)
from lemely.db.models.billing_ops import BillingSettings
from lemely.db.models.enums import Role, SubscriptionStatus
from lemely.db.models.tutoring import EmailOutbox
from lemely.db.models.usage import UsageEntry, UsageEntryKind, UsageGrantBalance
from lemely.db.subscription_repo import (
    TRIGGER_FAILED,
    TRIGGER_SUCCESS,
    InvalidExtraSeats,
    SubscriptionService,
)
from lemely.db.usage_ledger_repo import UsageLedger
from lemely.io.paymob.client import PaymobError
from tests.subscription_fixtures import (
    T0,
    FakePaymobClient,
    charge,
    ensure_billing_settings,
    grants_of,
    paymob_settings,
    remote_subscription,
    seed_first_payment,
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

PID = 4321
FIRST_TXN = 700 + PID
END = T0 + timedelta(days=30)
DAY = END + timedelta(hours=6)
TOMORROW = DAY + timedelta(days=1)


@pytest.fixture(scope="module")
def _database() -> Iterator[sessionmaker[Session]]:
    with throwaway_database() as factory:
        yield factory


@pytest.fixture
def pg_sessionmaker(_database: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    ensure_billing_settings(_database)  # ``emptied_after`` truncates it (it references users)
    yield from emptied_after(_database)
    with _database.begin() as session:
        session.execute(sa.text("TRUNCATE paymob_events CASCADE"))


# -- seeding and reading ----------------------------------------------------------------


def _linked(
    sm: sessionmaker[Session],
    pid: int = PID,
    *,
    tier_id: uuid.UUID | None = None,
    **kwargs: Any,
) -> uuid.UUID:
    """An active plan linked to Paymob, charging 100.00 a period, its first payment recorded."""
    student = seed_user(sm, Role.student)
    options: dict[str, Any] = {
        "payer_id": student,
        "paymob_subscription_id": pid,
        "paymob_amount_minor": 10_000,
        "activated_at": T0,
    } | kwargs
    sid = seed_subscription(sm, user_id=student, tier_id=tier_id or seed_tier(sm), **options)
    seed_first_payment(sm, subscription_id=sid, paymob_txn_id=700 + pid)
    return sid


def _client(
    pid: int = PID,
    *,
    state: str = "active",
    amount: int = 10_000,
    last: dict[str, Any] | None = None,
) -> FakePaymobClient:
    """Paymob as it stands: ``last`` is the last charge, by default the first payment."""
    client = FakePaymobClient()
    client.subscriptions[pid] = remote_subscription(
        pid,
        state=state,
        amount_cents=amount,
        initial_transaction=700 + pid,
        next_billing=END.astimezone(PAYMOB_ACCOUNT_TZ).date().isoformat(),
    )
    client.last_transactions[pid] = last or charge(700 + pid, 10_000)
    return client


def _drift(
    sm: sessionmaker[Session],
    client: FakePaymobClient,
    *,
    limit: int | None = None,
    settings_overrides: dict[str, Any] | None = None,
    now: datetime = DAY,
) -> int:
    """One drift pass at ``now``; a row is checked once a UTC day, so a second pass on the
    same day passes the next day's ``now`` (``TOMORROW``)."""
    with sm() as session:
        service = SubscriptionService(
            session, client, paymob_settings(**(settings_overrides or {}))
        )
        if limit is None:
            return service.check_drift(now=now)
        return service.check_drift(now=now, limit=limit)


def _sub(sm: sessionmaker[Session], sid: uuid.UUID) -> Subscription:
    with sm() as session:
        row = session.get(Subscription, sid)
        assert row is not None
        return row


def _renewals(sm: sessionmaker[Session], sid: uuid.UUID) -> list[Payment]:
    with sm() as session:
        return list(
            session.scalars(
                sa.select(Payment).where(
                    Payment.subscription_id == sid,
                    Payment.purpose == PaymentPurpose.subscription_renewal,
                )
            )
        )


def _periods(sm: sessionmaker[Session], sid: uuid.UUID) -> int:
    with sm() as session:
        return (
            session.scalar(
                sa.select(sa.func.count())
                .select_from(SubscriptionPeriod)
                .where(SubscriptionPeriod.subscription_id == sid)
            )
            or 0
        )


def _deliver(sm: sessionmaker[Session], client: FakePaymobClient, body: dict[str, Any]) -> None:
    with sm.begin() as session:
        SubscriptionService(session, client, paymob_settings()).apply_renewal_webhook(body, now=DAY)


# -- in sync, missed renewals ------------------------------------------------------------


def test_in_sync_subscription_needs_no_repair(pg_sessionmaker: sessionmaker[Session]) -> None:
    _linked(pg_sessionmaker)
    client = _client()
    assert _drift(pg_sessionmaker, client) == 0
    assert "update_subscription" not in client.names()
    assert "cancel_subscription" not in client.names()


def test_a_missed_renewal_is_applied_once_even_if_the_webhook_comes_later(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sid = _linked(pg_sessionmaker)
    client = _client(last=charge(888, 10_000, created_at=END - timedelta(hours=1)))
    assert _drift(pg_sessionmaker, client) == 1
    assert _sub(pg_sessionmaker, sid).current_period_end == END + timedelta(days=30)
    assert len(_renewals(pg_sessionmaker, sid)) == 1
    assert _drift(pg_sessionmaker, client) == 0  # the second day repeats nothing
    _deliver(pg_sessionmaker, client, subscription_webhook(TRIGGER_SUCCESS, PID))
    assert len(_renewals(pg_sessionmaker, sid)) == 1  # one payment ...
    assert _periods(pg_sessionmaker, sid) == 1  # ... one period
    assert _sub(pg_sessionmaker, sid).current_period_end == END + timedelta(days=30)


def test_a_lost_success_webhook_is_recovered_after_a_failure_was_ignored(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """N-1: active past its period end, the success lost and a later failure judged stale."""
    sid = _linked(pg_sessionmaker)
    paid = END + timedelta(hours=1)
    client = _client(last=charge(888, 10_000, created_at=paid))
    _deliver(pg_sessionmaker, client, subscription_webhook(TRIGGER_FAILED, PID))
    after_failure = _sub(pg_sessionmaker, sid)
    assert after_failure.status is SubscriptionStatus.active  # the failure was ignored
    assert after_failure.current_period_end == END  # and nothing renewed the period
    assert _drift(pg_sessionmaker, client) == 1
    row = _sub(pg_sessionmaker, sid)
    assert (row.status, row.current_period_start) == (SubscriptionStatus.active, paid)
    assert row.current_period_end == paid + timedelta(days=30)
    [renewal] = _renewals(pg_sessionmaker, sid)
    assert renewal.paymob_txn_id == 888
    assert _drift(pg_sessionmaker, client) == 0


def test_the_first_payment_is_not_taken_for_a_renewal(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """Drift passes Paymob's ``initial_transaction``, so a first charge never grants twice."""
    sid = _linked(pg_sessionmaker)
    with pg_sessionmaker.begin() as session:
        session.execute(sa.delete(Payment).where(Payment.subscription_id == sid))
    assert _drift(pg_sessionmaker, _client()) == 0
    assert _renewals(pg_sessionmaker, sid) == []


def test_a_charge_that_cannot_be_read_is_alerted_and_not_applied(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sid = _linked(pg_sessionmaker)
    client = _client(last={"id": "not-a-number", "amount_cents": 10_000})
    with capture_logs() as logs:
        assert _drift(pg_sessionmaker, client) == 0
    assert any(log["event"] == "subscription_last_transaction_unreadable" for log in logs)
    assert _renewals(pg_sessionmaker, sid) == []


# -- Paymob-side cancel and suspension (UD-4) --------------------------------------------


def test_an_external_cancel_is_mirrored_as_a_cancel_at_period_end(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sid = _linked(pg_sessionmaker)
    assert _drift(pg_sessionmaker, _client(state="canceled")) == 1
    row = _sub(pg_sessionmaker, sid)
    assert row.status is SubscriptionStatus.active  # the paid period is kept (UD-4 (b))
    assert row.cancel_at_period_end is True
    assert row.paymob_cancelled_at == DAY
    assert _drift(pg_sessionmaker, _client(state="canceled")) == 0  # mirrored once


def test_our_own_paymob_cancel_is_not_drift(pg_sessionmaker: sessionmaker[Session]) -> None:
    sid = _linked(
        pg_sessionmaker, cancel_at_period_end=True, paymob_cancelled_at=T0 + timedelta(days=2)
    )
    assert _drift(pg_sessionmaker, _client(state="canceled")) == 0
    assert _sub(pg_sessionmaker, sid).paymob_cancelled_at == T0 + timedelta(days=2)


def test_a_suspension_is_mirrored(pg_sessionmaker: sessionmaker[Session]) -> None:
    sid = _linked(pg_sessionmaker, period_end=DAY + timedelta(days=5))
    assert _drift(pg_sessionmaker, _client(state="suspended")) == 1
    row = _sub(pg_sessionmaker, sid)
    assert (row.status, row.cancel_at_period_end, row.suspended_at) == (
        SubscriptionStatus.active,
        True,
        DAY,
    )
    assert _drift(pg_sessionmaker, _client(state="suspended")) == 0


# -- amount drift (DV-18) ----------------------------------------------------------------


@pytest.mark.parametrize("stamp", [10_000, 9_000])
def test_amount_drift_is_put_back_through_the_one_helper(
    pg_sessionmaker: sessionmaker[Session], stamp: int
) -> None:
    sid = _linked(pg_sessionmaker, paymob_amount_minor=stamp, period_end=DAY + timedelta(days=1))
    client = _client(amount=12_345)
    assert _drift(pg_sessionmaker, client) == 1
    assert client.calls_to("update_subscription") == [
        {"subscription_id": PID, "amount_cents": 10_000, "ends_at": None, "next_billing": None}
    ]
    row = _sub(pg_sessionmaker, sid)
    assert row.paymob_amount_minor == 10_000  # the stamp is what next_renewal_amount says
    # The helper kept what it replaced, for a charge Paymob made before the PUT landed.
    assert (row.previous_amount_minor, row.amount_replaced_at is not None) == (12_345, True)
    assert row.amount_sync_uncertain_at is None
    assert _drift(pg_sessionmaker, client) == 0  # Paymob now holds the right amount
    assert len(client.calls_to("update_subscription")) == 1


def test_an_unknown_outcome_put_is_left_for_tomorrow(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sid = _linked(pg_sessionmaker, period_end=DAY + timedelta(days=2))  # still running tomorrow
    client = _client(amount=12_345)
    client.fail["update_subscription"] = PaymobError("timeout", timeout=True)
    assert _drift(pg_sessionmaker, client) == 0  # not repaired yet
    row = _sub(pg_sessionmaker, sid)
    assert row.paymob_amount_minor != 10_000  # no stamp claims a PUT that may not have landed
    assert row.amount_sync_uncertain_at is not None  # durable: tomorrow sends it again
    assert len(client.calls_to("update_subscription")) == 1

    del client.fail["update_subscription"]
    assert _drift(pg_sessionmaker, client, now=TOMORROW) == 1
    row = _sub(pg_sessionmaker, sid)
    assert (row.paymob_amount_minor, row.amount_sync_uncertain_at) == (10_000, None)
    assert len(client.calls_to("update_subscription")) == 2


def test_a_cancelling_plan_has_no_amount_drift(pg_sessionmaker: sessionmaker[Session]) -> None:
    _linked(
        pg_sessionmaker,
        period_end=DAY + timedelta(days=1),
        cancel_at_period_end=True,
        paymob_cancelled_at=T0,
    )
    client = _client(amount=12_345)
    assert _drift(pg_sessionmaker, client) == 0
    assert client.calls_to("update_subscription") == []


def test_the_fixed_amount_path_is_not_pushed(pg_sessionmaker: sessionmaker[Session]) -> None:
    sid = _linked(pg_sessionmaker, period_end=DAY + timedelta(days=1))
    client = _client(amount=12_345)
    assert (
        _drift(pg_sessionmaker, client, settings_overrides={"subscription_amount_updatable": False})
        == 0
    )
    assert client.calls_to("update_subscription") == []
    assert _sub(pg_sessionmaker, sid).paymob_amount_minor == 10_000  # the stamp is untouched


# -- ended rows (DV-15, DV-27) -----------------------------------------------------------


def test_a_failed_cancel_of_an_expired_subscription_is_retried(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sid = _linked(pg_sessionmaker, status=SubscriptionStatus.expired)
    client = _client()
    assert _drift(pg_sessionmaker, client) == 1
    assert client.names() == ["get_subscription", "last_transaction", "cancel_subscription"]
    assert _sub(pg_sessionmaker, sid).paymob_cancelled_at == DAY
    assert _drift(pg_sessionmaker, client) == 0  # no longer a candidate


def test_an_ended_row_whose_paymob_subscription_is_already_cancelled_is_stamped(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sid = _linked(pg_sessionmaker, status=SubscriptionStatus.cancelled)
    client = _client(state="canceled")
    assert _drift(pg_sessionmaker, client) == 1
    assert client.names() == ["get_subscription", "last_transaction"]  # no cancel call
    assert _sub(pg_sessionmaker, sid).paymob_cancelled_at == DAY


def test_a_superseded_checkout_linked_to_paymob_is_cancelled(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = seed_user(pg_sessionmaker, Role.student)
    sid = seed_subscription(
        pg_sessionmaker,
        user_id=student,
        tier_id=seed_tier(pg_sessionmaker),
        payer_id=student,
        status=SubscriptionStatus.expired,
        period_start=None,
        period_end=None,
        paymob_subscription_id=PID,
    )
    client = _client()
    assert _drift(pg_sessionmaker, client) == 1
    assert client.names() == ["get_subscription", "last_transaction", "cancel_subscription"]
    assert _sub(pg_sessionmaker, sid).paymob_cancelled_at == DAY


def test_a_cancel_the_ended_row_already_has_is_not_repeated(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _linked(pg_sessionmaker, status=SubscriptionStatus.expired, paymob_cancelled_at=T0)
    client = _client()
    assert _drift(pg_sessionmaker, client) == 0
    assert client.calls == []  # not even a read: it is not a candidate


def test_a_refused_cancel_of_an_ended_row_is_not_stamped(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sid = _linked(pg_sessionmaker, status=SubscriptionStatus.expired)
    client = _client()
    client.fail["cancel_subscription"] = PaymobError("down", status_code=503)
    assert _drift(pg_sessionmaker, client) == 0
    assert _sub(pg_sessionmaker, sid).paymob_cancelled_at is None  # tomorrow tries again


# -- a paid charge the webhook lost, on an ended row (I-1) --------------------------------


def test_a_lost_late_charge_reactivates_a_lapsed_plan_and_is_not_cancelled(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    sid = _linked(sm, status=SubscriptionStatus.expired)
    client = _client(last=charge(888, 10_000, created_at=END + timedelta(hours=1)))
    assert _drift(sm, client) == 1
    row = _sub(sm, sid)
    assert (row.status, row.paymob_cancelled_at) == (SubscriptionStatus.active, None)
    assert len(_renewals(sm, sid)) == 1
    assert "cancel_subscription" not in client.names()  # the plan is paid for again


def test_a_lost_late_charge_on_a_cancelled_plan_is_kept_for_a_refund_before_the_cancel(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    sid = _linked(sm, status=SubscriptionStatus.cancelled)
    client = _client(last=charge(888, 10_000, created_at=END + timedelta(hours=1)))
    with capture_logs() as logs:
        assert _drift(sm, client) == 1
    [alert] = [log for log in logs if log["event"] == "subscription_charge_on_ended_subscription"]
    assert alert.get("alert") is True
    [payment] = _renewals(sm, sid)
    assert payment.paid_at is not None  # the money is on record
    row = _sub(sm, sid)
    assert (row.status, row.paymob_cancelled_at) == (SubscriptionStatus.cancelled, None)
    assert "cancel_subscription" not in client.names()  # not in the pass that found the money
    assert _drift(sm, client, now=TOMORROW) == 1  # the next day's pass cancels it
    assert _sub(sm, sid).paymob_cancelled_at == TOMORROW
    assert len(_renewals(sm, sid)) == 1


def test_a_lost_late_charge_is_recorded_even_when_paymob_already_reports_canceled(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    sid = _linked(sm, status=SubscriptionStatus.cancelled)
    client = _client(
        state="canceled", last=charge(888, 10_000, created_at=END + timedelta(hours=1))
    )
    assert _drift(sm, client) == 1
    assert len(_renewals(sm, sid)) == 1
    assert _sub(sm, sid).paymob_cancelled_at is None  # stamped by the next pass, after the record


# -- robustness --------------------------------------------------------------------------


def test_one_paymob_failure_does_not_stop_the_rest(pg_sessionmaker: sessionmaker[Session]) -> None:
    broken = _linked(pg_sessionmaker, pid=1)
    good = _linked(pg_sessionmaker, pid=2)
    client = _client(pid=1)
    client.subscriptions[2] = remote_subscription(2, state="canceled", initial_transaction=702)
    client.last_transactions[2] = charge(702, 10_000)
    client.fail_for[("get_subscription", 1)] = PaymobError("down", status_code=503)
    assert _drift(pg_sessionmaker, client) == 1
    assert _sub(pg_sessionmaker, good).cancel_at_period_end is True
    assert _sub(pg_sessionmaker, broken).cancel_at_period_end is False


def test_a_failed_last_transaction_read_skips_only_that_row(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _linked(pg_sessionmaker, pid=1)
    good = _linked(pg_sessionmaker, pid=2)
    client = _client(pid=1)
    client.subscriptions[2] = remote_subscription(2, state="canceled", initial_transaction=702)
    client.last_transactions[2] = charge(702, 10_000)
    client.fail_for[("last_transaction", 1)] = PaymobError("down", status_code=503)
    assert _drift(pg_sessionmaker, client) == 1
    assert _sub(pg_sessionmaker, good).cancel_at_period_end is True


def test_a_remote_that_names_another_subscription_is_skipped(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sid = _linked(pg_sessionmaker)
    client = _client(state="canceled")
    real = client.get_subscription

    def get(subscription_id: int) -> Any:
        return real(subscription_id) | {"id": 999}

    client.get_subscription = get  # type: ignore[method-assign]
    assert _drift(pg_sessionmaker, client) == 0
    assert _sub(pg_sessionmaker, sid).cancel_at_period_end is False


def test_a_failing_row_rolls_back_alone_and_is_alerted(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _linked(pg_sessionmaker, pid=1, status=SubscriptionStatus.expired)
    good = _linked(pg_sessionmaker, pid=2, status=SubscriptionStatus.expired)
    client = _client(pid=1)
    client.subscriptions[2] = remote_subscription(2, state="canceled", initial_transaction=702)
    client.last_transactions[2] = charge(702, 10_000)
    client.fail_for[("cancel_subscription", 1)] = RuntimeError("secret account data")
    with capture_logs() as logs:
        assert _drift(pg_sessionmaker, client) == 1
    assert _sub(pg_sessionmaker, good).paymob_cancelled_at == DAY
    [alert] = [log for log in logs if log["event"] == "subscription_sweep_failed"]
    assert alert["error"] == "RuntimeError"
    assert "secret" not in str(alert)


def test_the_limit_bounds_one_pass(pg_sessionmaker: sessionmaker[Session]) -> None:
    first = _linked(pg_sessionmaker, pid=1)
    second = _linked(pg_sessionmaker, pid=2)
    client = _client(pid=1, state="canceled")
    client.subscriptions[2] = remote_subscription(2, state="canceled", initial_transaction=702)
    client.last_transactions[2] = charge(702, 10_000)
    assert _drift(pg_sessionmaker, client, limit=1) == 1
    repaired = [_sub(pg_sessionmaker, sid).cancel_at_period_end for sid in (first, second)]
    assert sorted(repaired) == [False, True]  # exactly one row
    assert _drift(pg_sessionmaker, client, limit=1) == 1  # the other one tomorrow
    assert all(_sub(pg_sessionmaker, sid).cancel_at_period_end for sid in (first, second))


def test_a_spent_budget_stops_the_drift_check_between_rows_and_the_rest_wait(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    first = _linked(pg_sessionmaker, pid=1)
    second = _linked(pg_sessionmaker, pid=2)
    client = _client(pid=1, state="canceled")
    client.subscriptions[2] = remote_subscription(2, state="canceled", initial_transaction=702)
    client.last_transactions[2] = charge(702, 10_000)
    asked: list[int] = []

    def should_stop() -> bool:
        asked.append(len(client.calls))  # Paymob calls made before each check
        return len(asked) > 1

    with pg_sessionmaker() as session:
        service = SubscriptionService(session, client, paymob_settings())
        assert service.check_drift(now=DAY, should_stop=should_stop) == 1
    # The first row's reads and repair all ran before the second check; nothing after it.
    assert asked[0] == 0
    assert asked[1] == len(client.calls) > 0
    repaired = [_sub(pg_sessionmaker, sid).cancel_at_period_end for sid in (first, second)]
    assert sorted(repaired) == [False, True]
    assert _drift(pg_sessionmaker, client) == 1  # the next pass, same day, takes the other row
    assert all(_sub(pg_sessionmaker, sid).cancel_at_period_end for sid in (first, second))


def test_a_limit_below_one_is_refused(pg_sessionmaker: sessionmaker[Session]) -> None:
    with pytest.raises(ValueError, match="limit"):
        _drift(pg_sessionmaker, FakePaymobClient(), limit=0)


def _checked(sm: sessionmaker[Session], sid: uuid.UUID) -> Any:
    return _sub(sm, sid).drift_checked_at


def test_rows_never_checked_come_first_then_the_least_recently_checked(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    stale = _linked(sm, pid=1)
    fresh = _linked(sm, pid=2)
    _linked(sm, pid=3)  # never checked
    with sm.begin() as session:
        for sid, days in ((stale, 9), (fresh, 1)):
            session.execute(
                sa.update(Subscription)
                .where(Subscription.id == sid)
                .values(drift_checked_at=DAY - timedelta(days=days))
            )
    client = _client(pid=1)
    for pid in (2, 3):
        client.subscriptions[pid] = remote_subscription(pid, initial_transaction=700 + pid)
        client.last_transactions[pid] = charge(700 + pid, 10_000)
    seen: list[int] = []
    for _ in range(3):
        _drift(sm, client, limit=1)
        seen = [c["subscription_id"] for c in client.calls_to("get_subscription")]
    assert seen == [3, 1, 2]  # never checked, then the stale one, then the fresh one


def test_rows_in_sync_cannot_starve_the_rest_of_a_bounded_pass(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """With ``limit=1`` every row is reached, though the first two need nothing."""
    sm = pg_sessionmaker
    ids = [_linked(sm, pid=pid) for pid in (1, 2, 3)]
    client = _client(pid=1)
    for pid in (2, 3):
        client.subscriptions[pid] = remote_subscription(pid, initial_transaction=700 + pid)
        client.last_transactions[pid] = charge(700 + pid, 10_000)
    client.subscriptions[3]["state"] = "canceled"
    results = [_drift(sm, client, limit=1) for _ in range(3)]
    assert sorted(results) == [0, 0, 1]
    assert all(_checked(sm, sid) == DAY for sid in ids)
    assert _sub(sm, ids[2]).cancel_at_period_end is True  # the last row was reached and repaired


def test_a_row_whose_read_failed_goes_to_the_back_of_the_queue(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    broken = _linked(sm, pid=1)
    client = _client(pid=1)
    client.fail_for[("get_subscription", 1)] = PaymobError("down", status_code=503)
    assert _drift(sm, client) == 0
    assert _checked(sm, broken) == DAY


def test_every_check_stamps_the_row_even_when_nothing_is_repaired(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sid = _linked(pg_sessionmaker)
    assert _checked(pg_sessionmaker, sid) is None
    assert _drift(pg_sessionmaker, _client()) == 0
    assert _checked(pg_sessionmaker, sid) == DAY


def test_a_held_row_is_skipped(pg_sessionmaker: sessionmaker[Session]) -> None:
    sid = _linked(pg_sessionmaker)
    client = _client(state="canceled")
    holding = threading.Event()
    release = threading.Event()

    def hold() -> None:
        with pg_sessionmaker() as session:
            session.execute(
                sa.select(Subscription.id).where(Subscription.id == sid).with_for_update()
            ).all()
            holding.set()
            release.wait(timeout=30)
            session.rollback()

    thread = threading.Thread(target=hold)
    thread.start()
    try:
        assert holding.wait(timeout=30)
        assert _drift(pg_sessionmaker, client) == 0  # skipped, not waited for
    finally:
        release.set()
        thread.join(timeout=30)
    assert _sub(pg_sessionmaker, sid).cancel_at_period_end is False
    assert _drift(pg_sessionmaker, client) == 1  # free again: repaired


def test_a_row_that_changed_since_the_read_is_judged_on_its_new_state(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The reads come first; the repair re-checks under the lock (a webhook may have won)."""
    sid = _linked(pg_sessionmaker)
    client = _client()
    real = client.last_transaction

    def last(subscription_id: int) -> Any:
        with pg_sessionmaker.begin() as session:  # the webhook gets there first
            row = session.get(Subscription, sid)
            assert row is not None
            row.status = SubscriptionStatus.expired
        return real(subscription_id)

    client.last_transaction = last  # type: ignore[method-assign]
    assert _drift(pg_sessionmaker, client) == 1
    row = _sub(pg_sessionmaker, sid)
    assert row.status is SubscriptionStatus.expired
    assert client.names().count("cancel_subscription") == 1  # cancelled as an ended row
    assert row.paymob_cancelled_at == DAY
    assert row.cancel_at_period_end is False


def test_a_manual_activation_is_untouched_by_every_sweep(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = seed_user(pg_sessionmaker, Role.student)
    sid = seed_subscription(
        pg_sessionmaker,
        user_id=student,
        tier_id=seed_tier(pg_sessionmaker),
        is_manually_activated=True,
        period_start=None,
        period_end=None,
    )
    client = FakePaymobClient()
    with pg_sessionmaker() as session:
        service = SubscriptionService(session, client, paymob_settings())
        assert service.expire_overdue(now=DAY) == 0
        assert service.apply_period_end_changes(now=DAY) == 0
        assert service.check_drift(now=DAY) == 0
    assert client.calls == []
    assert _sub(pg_sessionmaker, sid).status is SubscriptionStatus.active


def test_a_manual_activation_that_ended_is_never_selected(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = seed_user(pg_sessionmaker, Role.student)
    seed_subscription(
        pg_sessionmaker,
        user_id=student,
        tier_id=seed_tier(pg_sessionmaker),
        status=SubscriptionStatus.cancelled,
        is_manually_activated=True,
        period_start=None,
        period_end=None,
    )
    client = FakePaymobClient()
    assert _drift(pg_sessionmaker, client) == 0
    assert client.calls == []


# -- the period-end sweep also records a lost charge before it cancels (N-1) ---------------


def _sweep(sm: sessionmaker[Session], client: FakePaymobClient, *, now: Any = DAY) -> int:
    with sm() as session:
        return SubscriptionService(session, client, paymob_settings()).apply_period_end_changes(
            now=now
        )


def test_the_sweep_records_a_lost_late_charge_instead_of_cancelling_first(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    sid = _linked(sm, status=SubscriptionStatus.expired)
    client = _client(last=charge(888, 10_000, created_at=END + timedelta(hours=1)))
    assert _sweep(sm, client) == 1
    assert "last_transaction" in client.names()
    assert "cancel_subscription" not in client.names()
    row = _sub(sm, sid)
    assert (row.status, row.paymob_cancelled_at) == (SubscriptionStatus.active, None)
    assert len(_renewals(sm, sid)) == 1


def test_the_sweep_keeps_a_late_charge_on_a_cancelled_plan_and_cancels_next_time(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    sid = _linked(sm, status=SubscriptionStatus.cancelled)
    client = _client(last=charge(888, 10_000, created_at=END + timedelta(hours=1)))
    assert _sweep(sm, client) == 1
    assert len(_renewals(sm, sid)) == 1
    assert _sub(sm, sid).paymob_cancelled_at is None
    assert "cancel_subscription" not in client.names()
    assert _sweep(sm, client, now=DAY + timedelta(hours=1)) == 1
    assert _sub(sm, sid).paymob_cancelled_at == DAY + timedelta(hours=1)
    assert len(_renewals(sm, sid)) == 1


def test_the_sweep_leaves_an_ended_row_alone_when_paymob_cannot_be_read(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    sid = _linked(sm, status=SubscriptionStatus.expired)
    client = _client()
    client.fail["last_transaction"] = PaymobError("down", status_code=503)
    assert _sweep(sm, client) == 0
    assert "cancel_subscription" not in client.names()
    assert _sub(sm, sid).paymob_cancelled_at is None


# -- a kept charge is not also underpaid (N-3), a pending PUT is marked (N-4) ---------------


def test_a_charge_kept_on_a_cancelled_plan_alerts_only_as_kept(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    _linked(sm, status=SubscriptionStatus.cancelled, paymob_amount_minor=5_000)
    client = _client(last=charge(888, 5_000, created_at=END + timedelta(hours=1)))
    with capture_logs() as logs:
        _drift(sm, client)
    names = [log["event"] for log in logs if log.get("alert")]
    assert names.count("subscription_charge_on_ended_subscription") == 1
    assert "subscription_renewal_underpaid" not in names


def test_a_pending_put_is_marked_in_the_first_transaction(
    pg_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """N-4: a crash between the two transactions leaves the amount sweep to send the PUT."""
    sm = pg_sessionmaker
    sid = _linked(sm)
    client = _client(amount=12_345, last=charge(888, 10_000, created_at=END - timedelta(hours=1)))

    def die(*_args: object, **_kwargs: object) -> bool:
        raise KeyboardInterrupt  # the process dies after the first commit

    monkeypatch.setattr(SubscriptionService, "_repair_amount", die)
    with pytest.raises(KeyboardInterrupt):
        _drift(sm, client)
    monkeypatch.undo()
    row = _sub(sm, sid)
    assert len(_renewals(sm, sid)) == 1  # the renewal is committed
    assert row.amount_sync_uncertain_at == DAY  # and the owed PUT is on record
    assert client.calls_to("update_subscription") == []
    assert _sweep(sm, client, now=DAY + timedelta(hours=1)) == 1  # the amount sweep sends it
    [put] = client.calls_to("update_subscription")
    assert put["amount_cents"] == 10_000
    assert _sub(sm, sid).amount_sync_uncertain_at is None  # cleared when the PUT confirmed


def test_an_amount_in_sync_is_not_marked(pg_sessionmaker: sessionmaker[Session]) -> None:
    sm = pg_sessionmaker
    sid = _linked(sm, period_end=DAY + timedelta(days=1))
    assert _drift(sm, _client()) == 0
    assert _sub(sm, sid).amount_sync_uncertain_at is None


# -- underpaid renewals and refused PUTs (I-4, I-5) --------------------------------------


def _success_webhook(sm: sessionmaker[Session], client: FakePaymobClient, *, at: Any) -> None:
    with sm.begin() as session:
        SubscriptionService(session, client, paymob_settings()).apply_renewal_webhook(
            subscription_webhook(TRIGGER_SUCCESS, PID), now=at
        )


def test_a_renewal_below_the_expected_amount_after_an_unknown_put_is_alerted(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """I-4: Paymob holds half, drift's PUT is unknown, Paymob charges half: never silent."""
    sm = pg_sessionmaker
    sid = _linked(sm, period_end=DAY + timedelta(days=1))
    client = _client(amount=5_000)
    client.fail["update_subscription"] = PaymobError("timeout", timeout=True)
    assert _drift(sm, client) == 0
    assert _sub(sm, sid).amount_sync_uncertain_at is not None  # tomorrow sends it again
    client.last_transactions[PID] = charge(889, 5_000, created_at=DAY + timedelta(hours=2))
    with capture_logs() as logs:
        _success_webhook(sm, client, at=DAY + timedelta(hours=3))
    [alert] = [log for log in logs if log["event"] == "subscription_renewal_underpaid"]
    assert (alert["charged_minor"], alert["expected_minor"], alert.get("alert")) == (
        5_000,
        10_000,
        True,
    )
    [renewal] = _renewals(sm, sid)
    assert renewal.paid_at is not None  # the payer did pay what Paymob held: the period is theirs


def test_a_renewal_at_the_expected_amount_is_not_underpaid(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    _linked(sm, period_end=DAY + timedelta(days=1))
    client = _client(last=charge(889, 10_000, created_at=DAY + timedelta(hours=2)))
    with capture_logs() as logs:
        _success_webhook(sm, client, at=DAY + timedelta(hours=3))
    assert not any(log["event"] == "subscription_renewal_underpaid" for log in logs)


def test_a_refused_amount_put_keeps_the_recovered_renewal_and_the_stamp(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """I-5: the amount goes back in a transaction of its own; its refusal costs only the PUT."""
    sm = pg_sessionmaker
    sid = _linked(sm)
    client = _client(amount=12_345, last=charge(888, 10_000, created_at=END - timedelta(hours=1)))
    client.fail["update_subscription"] = PaymobError("refused", status_code=400)
    with capture_logs() as logs:
        assert _drift(sm, client) == 1
    assert len(_renewals(sm, sid)) == 1  # recovered
    assert _checked(sm, sid) == DAY  # and stamped
    [failed] = [log for log in logs if log["event"] == "subscription_sweep_failed"]
    assert failed.get("alert") is True
    assert _sub(sm, sid).previous_amount_minor is None  # the refused PUT left nothing behind


def test_rows_whose_put_is_refused_do_not_sort_first_for_ever(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    refused = _linked(sm, pid=1, period_end=DAY + timedelta(days=1))
    other = _linked(sm, pid=2)
    client = _client(pid=1, amount=12_345)
    client.fail_for[("update_subscription", 1)] = PaymobError("refused", status_code=400)
    client.subscriptions[2] = remote_subscription(2, state="canceled", initial_transaction=702)
    client.last_transactions[2] = charge(702, 10_000)
    for _ in range(2):
        _drift(sm, client, limit=1)
    assert _checked(sm, refused) == DAY
    assert _sub(sm, other).cancel_at_period_end is True  # reached though `limit` is 1


def test_a_row_whose_repair_raises_is_stamped_and_goes_to_the_back(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    broken = _linked(sm, pid=1, status=SubscriptionStatus.expired)
    other = _linked(sm, pid=2, status=SubscriptionStatus.expired)
    client = _client(pid=1)
    client.subscriptions[2] = remote_subscription(2, state="canceled", initial_transaction=702)
    client.last_transactions[2] = charge(702, 10_000)
    client.fail_for[("cancel_subscription", 1)] = RuntimeError("boom")
    for _ in range(2):
        _drift(sm, client, limit=1)
    assert _checked(sm, broken) == DAY  # rolled back, then stamped on its own
    assert _sub(sm, other).paymob_cancelled_at == DAY


# -- linking a Paymob-created plan from its stored event (T5-I2) --------------------------


def _unlinked(sm: sessionmaker[Session], *, txn: int = FIRST_TXN, **kwargs: Any) -> uuid.UUID:
    """An active plan that was paid but never linked to its Paymob subscription."""
    student = seed_user(sm, Role.student)
    sid = seed_subscription(
        sm,
        user_id=student,
        tier_id=seed_tier(sm),
        payer_id=student,
        paymob_amount_minor=None,
        activated_at=T0,
        **kwargs,
    )
    seed_first_payment(sm, subscription_id=sid, paymob_txn_id=txn)
    return sid


def _store_created_event(
    sm: sessionmaker[Session], *, paymob_id: int = PID, initial: int | None = FIRST_TXN
) -> uuid.UUID:
    remote = remote_subscription(paymob_id, initial_transaction=initial or 0)
    if initial is None:
        del remote["initial_transaction"]
    with sm.begin() as session:
        event = PaymobEvent(
            kind=PaymobEventKind.subscription,
            dedupe_key=f"sub:{paymob_id}:Subscription Created:{uuid.uuid4()}",
            payload={"body": {"trigger_type": "Subscription Created"}, "remote": remote},
        )
        session.add(event)
        session.flush()
        return event.id


def _event_processed(sm: sessionmaker[Session], event_id: uuid.UUID) -> bool:
    with sm() as session:
        event = session.get(PaymobEvent, event_id)
        assert event is not None
        return event.processed_at is not None


def test_a_stored_created_event_links_the_plan_and_the_same_pass_checks_it(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    sid = _unlinked(sm)
    event = _store_created_event(sm)
    client = _client()
    assert _drift(sm, client) == 1  # the link; the plan itself is in sync
    row = _sub(sm, sid)
    assert row.paymob_subscription_id == PID
    assert _event_processed(sm, event)
    assert "get_subscription" in client.names()  # linked rows are checked in the same pass
    assert _drift(sm, client) == 0  # and it is linked once


def test_a_stored_event_for_another_transaction_links_nothing(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    sid = _unlinked(sm)
    event = _store_created_event(sm, initial=FIRST_TXN + 1)
    assert _drift(sm, _client()) == 0
    assert _sub(sm, sid).paymob_subscription_id is None
    assert not _event_processed(sm, event)


def test_an_already_processed_event_is_not_linked_again(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    sid = _unlinked(sm)
    event = _store_created_event(sm)
    with sm.begin() as session:
        stored = session.get(PaymobEvent, event)
        assert stored is not None
        stored.processed_at = T0
    assert _drift(sm, _client()) == 0
    assert _sub(sm, sid).paymob_subscription_id is None


def test_an_event_without_an_initial_transaction_links_nothing(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    sid = _unlinked(sm)
    _store_created_event(sm, initial=None)
    assert _drift(sm, _client()) == 0
    assert _sub(sm, sid).paymob_subscription_id is None


def test_a_paymob_id_another_plan_holds_is_not_linked_and_is_alerted(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    holder = _linked(sm)  # holds PID already
    sid = _unlinked(sm, txn=FIRST_TXN + 50)
    event = _store_created_event(sm, initial=FIRST_TXN + 50)
    with capture_logs() as logs:
        _drift(sm, _client())
    assert any(log["event"] == "subscription_created_event_link_conflict" for log in logs)
    assert _sub(sm, sid).paymob_subscription_id is None
    assert _sub(sm, holder).paymob_subscription_id == PID
    assert not _event_processed(sm, event)


def test_a_complimentary_row_is_never_linked(pg_sessionmaker: sessionmaker[Session]) -> None:
    sm = pg_sessionmaker
    student = seed_user(sm, Role.student)
    sid = seed_subscription(
        sm,
        user_id=student,
        tier_id=seed_tier(sm),
        is_manually_activated=True,
        period_start=None,
        period_end=None,
    )
    _store_created_event(sm)
    client = FakePaymobClient()
    assert _drift(sm, client) == 0
    assert client.calls == []
    assert _sub(sm, sid).paymob_subscription_id is None


def test_the_link_pass_is_bounded_by_the_limit(pg_sessionmaker: sessionmaker[Session]) -> None:
    sm = pg_sessionmaker
    first = _unlinked(sm, txn=FIRST_TXN)
    second = _unlinked(sm, txn=FIRST_TXN + 7)
    _store_created_event(sm, paymob_id=PID, initial=FIRST_TXN)
    _store_created_event(sm, paymob_id=PID + 7, initial=FIRST_TXN + 7)
    client = _client()
    client.subscriptions[PID + 7] = remote_subscription(PID + 7, initial_transaction=FIRST_TXN + 7)
    client.last_transactions[PID + 7] = charge(FIRST_TXN + 7, 10_000)
    _drift(sm, client, limit=1)
    linked = [_sub(sm, sid).paymob_subscription_id is not None for sid in (first, second)]
    assert sorted(linked) == [False, True]


def test_a_link_conflict_is_alerted_once_and_does_not_hold_the_link_slot(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    _linked(sm)  # holds PID
    stuck = _unlinked(sm, txn=FIRST_TXN + 50)
    _store_created_event(sm, initial=FIRST_TXN + 50)
    free = _unlinked(sm, txn=FIRST_TXN + 60)
    _store_created_event(sm, paymob_id=PID + 60, initial=FIRST_TXN + 60)
    client = _client()
    client.subscriptions[PID + 60] = remote_subscription(
        PID + 60, initial_transaction=FIRST_TXN + 60
    )
    client.last_transactions[PID + 60] = charge(FIRST_TXN + 60, 10_000)
    with capture_logs() as logs:
        for _ in range(3):
            _drift(sm, client, limit=1)
    conflicts = [log for log in logs if log["event"] == "subscription_created_event_link_conflict"]
    assert len(conflicts) == 1  # once per conflict, not once a day
    assert _sub(sm, stuck).paymob_subscription_id is None
    assert _sub(sm, free).paymob_subscription_id == PID + 60  # the conflict did not block it


def test_a_link_and_a_repair_of_the_same_row_are_one_repair(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    sid = _unlinked(sm)
    _store_created_event(sm)
    client = _client(state="canceled")
    assert _drift(sm, client) == 1
    row = _sub(sm, sid)
    assert (row.paymob_subscription_id, row.cancel_at_period_end) == (PID, True)


# -- Paymob's next_billing against our period end (M8) -----------------------------------


def _with_next_billing(client: FakePaymobClient, when: Any) -> FakePaymobClient:
    client.subscriptions[PID]["next_billing"] = (
        when.astimezone(PAYMOB_ACCOUNT_TZ).date().isoformat()
    )
    return client


def _disagreements(logs: list[Any]) -> list[Any]:
    return [log for log in logs if log["event"] == "subscription_next_billing_disagrees"]


def test_a_next_billing_far_after_our_end_is_alerted_and_never_moves_the_end(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    sid = _linked(sm, period_end=DAY + timedelta(days=2))
    client = _with_next_billing(_client(), DAY + timedelta(days=400))  # I-3: no bound to abuse
    with capture_logs() as logs:
        assert _drift(sm, client) == 0  # nothing was repaired
    [alert] = _disagreements(logs)
    assert (alert["direction"], alert.get("alert")) == ("later", True)
    assert _sub(sm, sid).current_period_end == DAY + timedelta(days=2)


def test_a_next_billing_far_before_our_end_is_alerted_and_never_shortens_the_period(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    sid = _linked(sm, period_end=DAY + timedelta(days=20))
    client = _with_next_billing(_client(), DAY + timedelta(days=5))
    with capture_logs() as logs:
        assert _drift(sm, client) == 0
    [alert] = _disagreements(logs)
    assert alert["direction"] == "earlier"
    assert _sub(sm, sid).current_period_end == DAY + timedelta(days=20)  # untouched


def test_a_disagreement_is_alerted_once_per_period(pg_sessionmaker: sessionmaker[Session]) -> None:
    sm = pg_sessionmaker
    _linked(sm, period_end=DAY + timedelta(days=2))
    client = _with_next_billing(_client(), DAY + timedelta(days=30))
    with capture_logs() as logs:
        for _ in range(3):
            _drift(sm, client)
    assert len(_disagreements(logs)) == 1


def test_a_disagreement_is_alerted_again_for_the_next_period(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    sid = _linked(sm, period_end=DAY + timedelta(days=2))
    client = _with_next_billing(_client(), DAY + timedelta(days=30))
    with capture_logs() as logs:
        _drift(sm, client)
        with sm.begin() as session:
            row = session.get(Subscription, sid)
            assert row is not None
            row.current_period_end = DAY + timedelta(days=3)  # a renewal moved the period
        _drift(sm, client, now=TOMORROW)
    assert len(_disagreements(logs)) == 2


def test_the_period_lookups_still_find_the_period_after_a_disagreement(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """I-2: the end stays equal to the period row's, so P06 lookups and the grace work."""
    sm = pg_sessionmaker
    sid = _linked(sm)
    client = _client(last=charge(888, 10_000, created_at=END - timedelta(hours=1)))
    assert _drift(sm, client) == 1  # the renewal: a new period row and its grant
    new_end = END + timedelta(days=30)
    _with_next_billing(client, new_end + timedelta(days=10))
    with sm() as session:
        assert (
            SubscriptionService(session, client, paymob_settings()).check_drift(
                now=DAY + timedelta(days=1)
            )
            == 0
        )
    with sm() as session:
        sub = session.get(Subscription, sid)
        assert sub is not None
        period = current_period(session, sub)
        assert period is not None and period.period_end == sub.current_period_end == new_end


def test_a_far_next_billing_does_not_hide_a_real_failure(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """I-3: with the end untouched, a failure at the real billing date starts the grace."""
    sm = pg_sessionmaker
    sid = _linked(sm, period_end=DAY + timedelta(days=2))
    client = _with_next_billing(_client(), DAY + timedelta(days=400))
    _drift(sm, client)
    fail_at = DAY + timedelta(days=2, hours=1)
    client.last_transactions[PID] = charge(999, 10_000, created_at=fail_at, success=False)
    with sm.begin() as session:
        SubscriptionService(session, client, paymob_settings()).apply_renewal_webhook(
            subscription_webhook(TRIGGER_FAILED, PID), now=fail_at
        )
    row = _sub(sm, sid)
    assert row.status is SubscriptionStatus.past_due
    assert row.grace_until is not None


@pytest.mark.parametrize("days", [-2, 0, 1, 2])
def test_a_next_billing_inside_the_tolerance_is_not_a_disagreement(
    pg_sessionmaker: sessionmaker[Session], days: int
) -> None:
    sm = pg_sessionmaker
    sid = _linked(sm, period_end=DAY + timedelta(days=10))
    client = _with_next_billing(_client(), DAY + timedelta(days=10 + days))
    with capture_logs() as logs:
        assert _drift(sm, client) == 0
    assert not any(log["event"] == "subscription_next_billing_disagrees" for log in logs)
    assert _sub(sm, sid).current_period_end == DAY + timedelta(days=10)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"cancel_at_period_end": True, "paymob_cancelled_at": T0},
        {"status": SubscriptionStatus.past_due, "grace_until": DAY + timedelta(days=2)},
    ],
)
def test_next_billing_is_not_compared_for_a_cancelling_or_past_due_plan(
    pg_sessionmaker: sessionmaker[Session], kwargs: dict[str, Any]
) -> None:
    sm = pg_sessionmaker
    sid = _linked(sm, period_end=DAY + timedelta(days=2), **kwargs)
    client = _with_next_billing(_client(), DAY + timedelta(days=12))
    assert _drift(sm, client) == 0
    assert _sub(sm, sid).current_period_end == DAY + timedelta(days=2)


def test_next_billing_is_not_compared_once_the_period_is_over(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    sid = _linked(sm)  # ends at END, before DAY: a renewal is due, not an anchor
    client = _with_next_billing(_client(), DAY + timedelta(days=12))
    assert _drift(sm, client) == 0
    assert _sub(sm, sid).current_period_end == END


def test_an_unreadable_next_billing_is_ignored(pg_sessionmaker: sessionmaker[Session]) -> None:
    sm = pg_sessionmaker
    _linked(sm, period_end=DAY + timedelta(days=2))
    client = _client()
    client.subscriptions[PID]["next_billing"] = "someday"
    assert _drift(sm, client) == 0


# -- full refund of a subscription payment (UD-6 (a)) ------------------------------------


def _renewed_with_spend(
    sm: sessionmaker[Session], *, spent: int
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, FakePaymobClient]:
    """``(student, subscription, renewal payment, client)``: a 100 unit period, ``spent`` used."""
    student = seed_user(sm, Role.student)
    sid = seed_subscription(
        sm,
        user_id=student,
        tier_id=seed_tier(sm, allowance_units=100),
        payer_id=student,
        paymob_subscription_id=PID,
        paymob_amount_minor=10_000,
        activated_at=T0,
    )
    seed_first_payment(sm, subscription_id=sid, paymob_txn_id=FIRST_TXN)
    client = _client(last=charge(888, 10_000, created_at=END - timedelta(hours=1)))
    assert _drift(sm, client) == 1  # the renewal is granted through the drift check
    [payment] = _renewals(sm, sid)
    if spent:
        with sm.begin() as session:
            UsageLedger(session).adjust(
                owner_user_id=student,
                units=-spent,
                reason="test spend",
                idempotency_key="spend",
                now=DAY,
            )
    return student, sid, payment.id, client


def _remaining(sm: sessionmaker[Session], student: uuid.UUID) -> int:
    with sm() as session:
        return (
            session.scalar(
                sa.select(sa.func.coalesce(sa.func.sum(UsageGrantBalance.remaining), 0)).where(
                    UsageGrantBalance.grant_id.in_([g.id for g in grants_of(sm, student)])
                )
            )
            or 0
        )


def _outbox(sm: sessionmaker[Session]) -> int:
    with sm() as session:
        return session.scalar(sa.select(sa.func.count()).select_from(EmailOutbox)) or 0


def _refund(sm: sessionmaker[Session], payment_id: uuid.UUID, *, full: bool) -> None:
    with sm.begin() as session:
        SubscriptionService(session, FakePaymobClient(), paymob_settings()).on_payment_refunded(
            payment_id, full=full, now=DAY + timedelta(hours=1)
        )


def test_a_full_refund_claws_back_only_the_unspent_units_and_ends_the_plan(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    student, sid, payment_id, client = _renewed_with_spend(sm, spent=30)
    assert _remaining(sm, student) == 70
    mails_before = _outbox(sm)
    _refund(sm, payment_id, full=True)
    assert _remaining(sm, student) == 0
    with sm() as session:
        [entry] = session.scalars(
            sa.select(UsageEntry).where(UsageEntry.kind == UsageEntryKind.refund)
        ).all()
    assert entry.units == -70  # the 30 spent units stay spent
    row = _sub(sm, sid)
    assert row.status is SubscriptionStatus.cancelled
    assert row.paymob_cancelled_at is None  # Paymob's cancel is the sweep's, not the hook's
    assert "cancel_subscription" not in client.names()
    assert _outbox(sm) == mails_before  # no notice
    # The cancel sweep then ends the Paymob subscription.
    with sm() as session:
        service = SubscriptionService(session, client, paymob_settings())
        assert service.apply_period_end_changes(now=DAY + timedelta(hours=2)) == 1
    assert client.names().count("cancel_subscription") == 1
    assert _sub(sm, sid).paymob_cancelled_at is not None


def test_a_full_refund_is_idempotent(pg_sessionmaker: sessionmaker[Session]) -> None:
    sm = pg_sessionmaker
    student, sid, payment_id, _ = _renewed_with_spend(sm, spent=30)
    _refund(sm, payment_id, full=True)
    _refund(sm, payment_id, full=True)
    assert _remaining(sm, student) == 0
    with sm() as session:
        assert (
            session.scalar(
                sa.select(sa.func.count())
                .select_from(UsageEntry)
                .where(UsageEntry.kind == UsageEntryKind.refund)
            )
            == 1
        )
    assert _sub(sm, sid).status is SubscriptionStatus.cancelled


def test_a_partial_refund_changes_nothing(pg_sessionmaker: sessionmaker[Session]) -> None:
    sm = pg_sessionmaker
    student, sid, payment_id, _ = _renewed_with_spend(sm, spent=30)
    _refund(sm, payment_id, full=False)
    assert _remaining(sm, student) == 70
    row = _sub(sm, sid)
    assert (row.status, row.cancel_at_period_end) == (SubscriptionStatus.active, False)


def test_a_refund_of_a_payment_that_is_not_a_subscription_charge_changes_nothing(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    _, sid, payment_id, _ = _renewed_with_spend(sm, spent=0)
    with sm.begin() as session:
        session.execute(
            sa.update(Payment)
            .where(Payment.id == payment_id)
            .values(purpose=PaymentPurpose.upgrade_proration)
        )
    _refund(sm, payment_id, full=True)
    assert _sub(sm, sid).status is SubscriptionStatus.active
    _refund(sm, uuid.uuid4(), full=True)  # an unknown payment is not an error either


def _first_payment_of(sm: sessionmaker[Session], sid: uuid.UUID) -> uuid.UUID:
    with sm() as session:
        return session.scalars(
            sa.select(Payment.id).where(
                Payment.subscription_id == sid,
                Payment.purpose == PaymentPurpose.subscription_first,
            )
        ).one()


def _give_period(
    sm: sessionmaker[Session], sid: uuid.UUID, payment_id: uuid.UUID, *, start: Any, end: Any
) -> None:
    with sm.begin() as session:
        session.add(
            SubscriptionPeriod(
                subscription_id=sid, period_start=start, period_end=end, payment_id=payment_id
            )
        )


def test_a_full_refund_of_the_current_periods_first_payment_ends_the_plan(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    sid = _linked(sm)
    first = _first_payment_of(sm, sid)
    _give_period(sm, sid, first, start=T0, end=END)  # the only, so the current, period
    _refund(sm, first, full=True)
    assert _sub(sm, sid).status is SubscriptionStatus.cancelled


def test_a_full_refund_of_an_older_periods_payment_changes_nothing_and_alerts(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    student, sid, renewal, _ = _renewed_with_spend(sm, spent=0)
    first = _first_payment_of(sm, sid)
    _give_period(sm, sid, first, start=T0, end=END)  # the renewal's period came after it
    before = _remaining(sm, student)
    with capture_logs() as logs:
        _refund(sm, first, full=True)
    [alert] = [log for log in logs if log["event"] == "subscription_old_period_refunded"]
    assert alert.get("alert") is True
    assert str(sid) == alert["subscription_id"]
    row = _sub(sm, sid)
    assert (row.status, row.cancel_at_period_end) == (SubscriptionStatus.active, False)
    assert _remaining(sm, student) == before  # nothing clawed back
    # The current period's payment still ends the plan.
    _refund(sm, renewal, full=True)
    assert _sub(sm, sid).status is SubscriptionStatus.cancelled


def _early_renewal(sm: sessionmaker[Session]) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, Any]:
    """``(student, subscription, early renewal payment, now)``: N in force, N+1 paid early."""
    student = seed_user(sm, Role.student)
    sid = seed_subscription(
        sm,
        user_id=student,
        tier_id=seed_tier(sm, allowance_units=100),
        payer_id=student,
        paymob_subscription_id=PID,
        paymob_amount_minor=10_000,
        activated_at=T0,
    )
    seed_first_payment(sm, subscription_id=sid, paymob_txn_id=FIRST_TXN)
    _give_period(sm, sid, _first_payment_of(sm, sid), start=T0, end=END)
    now = END - timedelta(hours=2)
    client = _client(last=charge(888, 10_000, created_at=END - timedelta(hours=3)))
    with sm() as session:
        assert SubscriptionService(session, client, paymob_settings()).check_drift(now=now) == 1
    [renewal] = _renewals(sm, sid)
    return student, sid, renewal.id, now


def _refund_at(sm: sessionmaker[Session], payment_id: uuid.UUID, now: Any) -> None:
    with sm.begin() as session:
        SubscriptionService(session, FakePaymobClient(), paymob_settings()).on_payment_refunded(
            payment_id, full=True, now=now
        )


def test_refunding_a_period_that_has_not_started_does_not_end_the_plan_now(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    student, sid, renewal, now = _early_renewal(sm)
    assert _remaining(sm, student) == 100
    with capture_logs() as logs:
        _refund_at(sm, renewal, now)
    row = _sub(sm, sid)
    assert (row.status, row.cancel_at_period_end) == (SubscriptionStatus.active, False)
    assert _remaining(sm, student) == 0  # what the future period would have granted is taken back
    [alert] = [log for log in logs if log["event"] == "subscription_future_period_refunded"]
    assert alert.get("alert") is True


def test_refunding_the_period_in_force_while_a_later_one_is_paid_ends_nothing(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """N-2: ending the plan would strand the paid next period; it is left to a person."""
    sm = pg_sessionmaker
    student, sid, renewal, now = _early_renewal(sm)
    first = _first_payment_of(sm, sid)
    with capture_logs() as logs:
        _refund_at(sm, first, now)
    row = _sub(sm, sid)
    assert (row.status, row.cancel_at_period_end) == (SubscriptionStatus.active, False)
    assert _remaining(sm, student) == 100  # nothing taken back
    [alert] = [log for log in logs if log["event"] == "subscription_refund_with_later_paid_period"]
    assert alert.get("alert") is True
    assert not any(log["event"] == "subscription_old_period_refunded" for log in logs)
    with sm() as session:
        kept = session.get(Payment, renewal)
        assert kept is not None and kept.paid_at is not None


def test_refunding_the_newest_period_in_force_still_ends_the_plan(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    _, sid, renewal, _ = _early_renewal(sm)
    _refund_at(sm, renewal, END + timedelta(hours=1))  # N+1 has started: it is the one in force
    assert _sub(sm, sid).status is SubscriptionStatus.cancelled


def test_a_refund_of_a_charge_that_bought_no_period_changes_nothing(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    sid = _linked(sm)  # no period row for its first payment
    with capture_logs() as logs:
        _refund(sm, _first_payment_of(sm, sid), full=True)
    assert _sub(sm, sid).status is SubscriptionStatus.active
    assert not any(log["event"] == "subscription_old_period_refunded" for log in logs)


def test_a_refund_never_writes_to_paymob(pg_sessionmaker: sessionmaker[Session]) -> None:
    sm = pg_sessionmaker
    _, _, payment_id, _ = _renewed_with_spend(sm, spent=0)
    quiet = FakePaymobClient()
    with sm.begin() as session:
        SubscriptionService(session, quiet, paymob_settings()).on_payment_refunded(
            payment_id, full=True, now=DAY
        )
    assert quiet.calls == []


# -- the first-checkout seat ceiling (UD-13) ---------------------------------------------


def _teacher_checkout(sm: sessionmaker[Session], extra_seats: int) -> None:
    teacher = seed_user(sm, Role.teacher)
    tier = seed_tier(sm, audience=PlanAudience.teacher, extra_seat_price_minor=100)
    with sm() as session:
        SubscriptionService(
            session, FakePaymobClient(), paymob_settings()
        ).create_subscription_checkout(
            payer_user_id=teacher, plan_tier_id=tier, extra_seats=extra_seats, now=T0
        )
        session.commit()


def _set_ceiling(sm: sessionmaker[Session], seats: int) -> None:
    with sm.begin() as session:
        row = session.get(BillingSettings, 1)
        assert row is not None
        row.max_extra_seats = seats


@pytest.mark.parametrize(
    ("ceiling", "seats", "allowed"),
    [(10, 11, False), (10, 10, True), (300, 250, True), (300, 301, False)],
)
def test_the_first_checkout_ceiling_is_the_admin_set_one(
    pg_sessionmaker: sessionmaker[Session], ceiling: int, seats: int, allowed: bool
) -> None:
    sm = pg_sessionmaker
    _set_ceiling(sm, ceiling)
    if allowed:
        _teacher_checkout(sm, seats)  # 250 is above the old constant of 200
        return
    with pytest.raises(InvalidExtraSeats):
        _teacher_checkout(sm, seats)
    with sm() as session:  # nothing was written
        assert session.scalar(sa.select(sa.func.count()).select_from(Subscription)) == 0


def test_the_first_checkout_fails_closed_without_the_settings_row(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    with sm.begin() as session:
        session.execute(sa.delete(BillingSettings))
    with capture_logs() as logs, pytest.raises(CheckoutUnavailable):
        _teacher_checkout(sm, 5)
    assert any(log["event"] == "seat_ceiling_setting_missing" and log.get("alert") for log in logs)
    with sm() as session:  # nothing was written
        assert session.scalar(sa.select(sa.func.count()).select_from(Subscription)) == 0


def test_a_checkout_of_no_extra_seats_does_not_need_the_ceiling_setting(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    with sm.begin() as session:
        session.execute(sa.delete(BillingSettings))
    _teacher_checkout(sm, 0)  # no seats asked for, so nothing to bound
    with sm() as session:
        assert session.scalar(sa.select(sa.func.count()).select_from(Subscription)) == 1
