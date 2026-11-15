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
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import pytest
import sqlalchemy as sa
from structlog.testing import capture_logs

from lemely.db.billing_repo import CheckoutUnavailable
from lemely.db.models.billing import (
    Payment,
    PaymentPurpose,
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
        pid, state=state, amount_cents=amount, initial_transaction=700 + pid
    )
    client.last_transactions[pid] = last or charge(700 + pid, 10_000)
    return client


def _drift(
    sm: sessionmaker[Session],
    client: FakePaymobClient,
    *,
    limit: int | None = None,
    settings_overrides: dict[str, Any] | None = None,
) -> int:
    with sm() as session:
        service = SubscriptionService(
            session, client, paymob_settings(**(settings_overrides or {}))
        )
        if limit is None:
            return service.check_drift(now=DAY)
        return service.check_drift(now=DAY, limit=limit)


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
    sid = _linked(pg_sessionmaker, period_end=DAY + timedelta(days=1))
    client = _client(amount=12_345)
    client.fail["update_subscription"] = PaymobError("timeout", timeout=True)
    assert _drift(pg_sessionmaker, client) == 0  # not repaired yet
    row = _sub(pg_sessionmaker, sid)
    assert row.paymob_amount_minor != 10_000  # no stamp claims a PUT that may not have landed
    assert row.amount_sync_uncertain_at is not None  # durable: tomorrow sends it again
    assert len(client.calls_to("update_subscription")) == 1

    del client.fail["update_subscription"]
    assert _drift(pg_sessionmaker, client) == 1
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
    assert client.names() == ["get_subscription", "cancel_subscription"]
    assert _sub(pg_sessionmaker, sid).paymob_cancelled_at == DAY
    assert _drift(pg_sessionmaker, client) == 0  # no longer a candidate


def test_an_ended_row_whose_paymob_subscription_is_already_cancelled_is_stamped(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sid = _linked(pg_sessionmaker, status=SubscriptionStatus.cancelled)
    client = _client(state="canceled")
    assert _drift(pg_sessionmaker, client) == 1
    assert client.names() == ["get_subscription"]  # no cancel call
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
    assert client.names() == ["get_subscription", "cancel_subscription"]
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


def test_a_limit_below_one_is_refused(pg_sessionmaker: sessionmaker[Session]) -> None:
    with pytest.raises(ValueError, match="limit"):
        _drift(pg_sessionmaker, FakePaymobClient(), limit=0)


def test_rows_are_taken_least_recently_updated_first(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    newer = _linked(pg_sessionmaker, pid=1)
    older = _linked(pg_sessionmaker, pid=2)
    with pg_sessionmaker.begin() as session:
        session.execute(
            sa.update(Subscription)
            .where(Subscription.id == older)
            .values(updated_at=T0 - timedelta(days=9))
        )
    client = _client(pid=1, state="canceled")
    client.subscriptions[2] = remote_subscription(2, state="canceled", initial_transaction=702)
    client.last_transactions[2] = charge(702, 10_000)
    assert _drift(pg_sessionmaker, client, limit=1) == 1
    assert _sub(pg_sessionmaker, older).cancel_at_period_end is True
    assert _sub(pg_sessionmaker, newer).cancel_at_period_end is False


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


def test_a_full_refund_of_the_first_payment_ends_the_plan(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    sid = _linked(sm)
    with sm() as session:
        first = session.scalars(sa.select(Payment.id).where(Payment.subscription_id == sid)).one()
    _refund(sm, first, full=True)
    assert _sub(sm, sid).status is SubscriptionStatus.cancelled


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
