"""Reconciliation of missed callbacks by transaction inquiry (spec §5.10, §6)."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
import structlog
from sqlalchemy import event

from lemely.db import billing_repo
from lemely.db.announcement_repo import AnnouncementService
from lemely.db.billing_repo import RECONCILE_STUCK_AFTER, BillingService
from lemely.db.class_repo import ClassService
from lemely.db.models.billing import Payment, PaymentPurpose, PaymentStatus, PaymobEvent
from lemely.db.models.usage import UsageGrant
from lemely.db.notification_prefs_repo import NotificationPreferencesService
from lemely.db.notification_repo import NotificationService
from lemely.io.paymob.client import PaymobClient, PaymobError, PaymobNotConfigured
from lemely.runtime.config import NotificationsSettings, PaymobSettings
from lemely.web import deps, deps_billing
from lemely.web.billing_jobs import reconcile_pending_payments
from lemely.web.push import RecordingPushTransport
from lemely.web.scheduled_notifications import Sweeper
from tests.paymob_fixtures import (
    FIXED_NOW,
    PAYMOB_SETTINGS,
    FakePaymobClient,
    seed_pack,
    seed_payment,
    seed_user,
    transaction_obj,
)

if TYPE_CHECKING:
    import uuid
    from collections.abc import Callable, Iterator
    from datetime import datetime
    from typing import Any

    from sqlalchemy.engine import Connection, Engine
    from sqlalchemy.orm import Session, sessionmaker


def _due_payment(
    sm: sessionmaker[Session],
    *,
    age: timedelta,
    status: PaymentStatus = PaymentStatus.created,
    paymob_order_id: int | None = None,
) -> uuid.UUID:
    payer = seed_user(sm)
    pack = seed_pack(sm)
    created = FIXED_NOW - age
    return seed_payment(
        sm,
        payer=payer,
        beneficiary=payer,
        pack_id=pack,
        created_at=created,
        status=status,
        paymob_order_id=paymob_order_id,
    )


def _reconcile(
    sm: sessionmaker[Session],
    client: FakePaymobClient,
    now: datetime = FIXED_NOW,
    *,
    lock_timeout: str | None = None,
) -> int:
    with sm() as session:
        try:
            if lock_timeout is not None:
                # A guard for the two-runner tests: if SKIP LOCKED regressed, a select would
                # wait on the other runner's lock forever. A session-level setting (committed
                # at once, since SET is transactional) lasts across the per-payment commits, so
                # that regression is an error on any select of the pass, not a hang.
                session.execute(sa.text(f"SET lock_timeout = '{lock_timeout}'"))
                session.commit()
            return BillingService(
                session, client, PAYMOB_SETTINGS, now=lambda: now
            ).reconcile_pending(now=now)
        finally:
            if lock_timeout is not None:
                session.rollback()
                session.execute(sa.text("RESET lock_timeout"))
                session.commit()


def _payment(sm: sessionmaker[Session], pid: uuid.UUID) -> Payment:
    with sm() as session:
        payment = session.get(Payment, pid)
        assert payment is not None
        return payment


def _grant_count(sm: sessionmaker[Session], pid: uuid.UUID) -> int:
    with sm() as session:
        return len(session.scalars(sa.select(UsageGrant).where(UsageGrant.payment_id == pid)).all())


def _event_count(sm: sessionmaker[Session]) -> int:
    with sm() as session:
        return len(session.scalars(sa.select(PaymobEvent)).all())


def test_a_payment_younger_than_fifteen_minutes_is_left_alone(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    pid = _due_payment(sm, age=timedelta(minutes=10))
    client = FakePaymobClient()
    assert _reconcile(sm, client) == 0
    assert client.inquiries == []
    assert _payment(sm, pid).status is PaymentStatus.created


def test_a_missed_success_callback_is_found_by_inquiry_and_granted(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    pid = _due_payment(sm, age=timedelta(minutes=20))
    client = FakePaymobClient()
    client.inquiry_response = transaction_obj(merchant_order_id=str(pid))
    assert _reconcile(sm, client) == 1
    assert client.inquiries == [str(pid)]
    payment = _payment(sm, pid)
    assert payment.status is PaymentStatus.paid
    assert payment.next_reconcile_at is None
    assert _grant_count(sm, pid) == 1


def test_a_success_found_after_24_hours_is_still_paid(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    pid = _due_payment(sm, age=timedelta(hours=30))
    client = FakePaymobClient()
    client.inquiry_response = transaction_obj(merchant_order_id=str(pid))
    assert _reconcile(sm, client) == 1
    assert _payment(sm, pid).status is PaymentStatus.paid
    assert _grant_count(sm, pid) == 1


def test_the_late_real_callback_after_inquiry_is_a_duplicate(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    pid = _due_payment(sm, age=timedelta(minutes=20))
    obj = transaction_obj(merchant_order_id=str(pid))
    client = FakePaymobClient()
    client.inquiry_response = obj
    _reconcile(sm, client)
    with sm.begin() as session:
        BillingService(session, client, PAYMOB_SETTINGS).apply_transaction_callback(obj)
    assert _grant_count(sm, pid) == 1
    assert _event_count(sm) == 1


def test_no_transaction_yet_backs_off_15m_then_30m(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    pid = _due_payment(sm, age=timedelta(minutes=20))
    client = FakePaymobClient()
    client.inquiry_response = None
    _reconcile(sm, client)
    payment = _payment(sm, pid)
    assert payment.status is PaymentStatus.created
    assert payment.reconcile_attempts == 1
    assert payment.next_reconcile_at == FIXED_NOW + timedelta(minutes=15)
    later = FIXED_NOW + timedelta(minutes=15)
    _reconcile(sm, client, now=later)
    payment = _payment(sm, pid)
    assert payment.reconcile_attempts == 2
    assert payment.next_reconcile_at == later + timedelta(minutes=30)


def test_backoff_is_capped_at_four_hours(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    pid = _due_payment(sm, age=timedelta(hours=1))
    with sm.begin() as session:
        payment = session.get(Payment, pid)
        assert payment is not None
        payment.reconcile_attempts = 9
    client = FakePaymobClient()
    _reconcile(sm, client)
    assert _payment(sm, pid).next_reconcile_at == FIXED_NOW + timedelta(hours=4)


def test_a_huge_attempt_count_cannot_overflow_the_backoff(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    pid = _due_payment(sm, age=timedelta(hours=1))
    with sm.begin() as session:
        payment = session.get(Payment, pid)
        assert payment is not None
        payment.reconcile_attempts = 1_000_000
    _reconcile(sm, FakePaymobClient())
    assert _payment(sm, pid).next_reconcile_at == FIXED_NOW + timedelta(hours=4)


def test_after_24_hours_without_a_transaction_it_is_failed(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    pid = _due_payment(sm, age=timedelta(hours=24, minutes=1))
    client = FakePaymobClient()
    client.inquiry_response = None
    _reconcile(sm, client)
    payment = _payment(sm, pid)
    assert payment.status is PaymentStatus.failed
    assert payment.next_reconcile_at is None


def test_after_24_hours_a_still_pending_transaction_is_failed(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    pid = _due_payment(sm, age=timedelta(hours=25))
    client = FakePaymobClient()
    client.inquiry_response = transaction_obj(
        merchant_order_id=str(pid), success=False, pending=True
    )
    _reconcile(sm, client)
    payment = _payment(sm, pid)
    assert payment.status is PaymentStatus.failed
    assert payment.next_reconcile_at is None


def test_a_still_pending_transaction_keeps_being_checked(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    pid = _due_payment(sm, age=timedelta(minutes=20))
    client = FakePaymobClient()
    client.inquiry_response = transaction_obj(
        merchant_order_id=str(pid), success=False, pending=True
    )
    _reconcile(sm, client)
    payment = _payment(sm, pid)
    assert payment.status is PaymentStatus.pending
    assert payment.next_reconcile_at == FIXED_NOW + timedelta(minutes=15)


def test_a_declined_transaction_found_by_inquiry_is_failed_and_closed(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    pid = _due_payment(sm, age=timedelta(minutes=20))
    client = FakePaymobClient()
    client.inquiry_response = transaction_obj(merchant_order_id=str(pid), success=False)
    _reconcile(sm, client)
    payment = _payment(sm, pid)
    assert payment.status is PaymentStatus.failed
    assert payment.next_reconcile_at is None
    assert _grant_count(sm, pid) == 0


# -- R20b: an unknown outcome is never "failed" -------------------------------------

INQUIRY_ERRORS: list[Callable[[], PaymobError]] = [
    lambda: PaymobError("Paymob GET inquiry timed out", timeout=True),
    lambda: PaymobError("Paymob GET inquiry failed: ConnectError"),
    lambda: PaymobError("Paymob GET inquiry returned 503", status_code=503),
    lambda: PaymobError("Paymob GET inquiry returned 502", status_code=502, outcome_unknown=False),
    lambda: PaymobError("Paymob GET inquiry returned 401", status_code=401),
    lambda: PaymobError("Paymob GET inquiry returned 400", status_code=400),
    lambda: PaymobError("Paymob GET inquiry returned 200 with no JSON", outcome_unknown=True),
    lambda: PaymobNotConfigured("Paymob API key is not configured"),
]


@pytest.mark.parametrize("make_error", INQUIRY_ERRORS)
def test_an_inquiry_failure_reschedules_and_never_fails_the_payment(
    migrated_sessionmaker: sessionmaker[Session], make_error: Callable[[], PaymobError]
) -> None:
    sm = migrated_sessionmaker
    pid = _due_payment(sm, age=timedelta(minutes=20))
    client = FakePaymobClient()
    client.inquiry_response = make_error()
    assert _reconcile(sm, client) == 1
    payment = _payment(sm, pid)
    assert payment.status is PaymentStatus.created
    assert payment.reconcile_attempts == 1
    assert payment.next_reconcile_at == FIXED_NOW + timedelta(minutes=15)


@pytest.mark.parametrize("make_error", INQUIRY_ERRORS)
def test_a_payment_older_than_24_hours_stays_open_while_inquiry_keeps_erroring(
    migrated_sessionmaker: sessionmaker[Session], make_error: Callable[[], PaymobError]
) -> None:
    sm = migrated_sessionmaker
    pid = _due_payment(sm, age=timedelta(hours=30))
    client = FakePaymobClient()
    client.inquiry_response = make_error()
    now = FIXED_NOW
    for expected_minutes in (15, 30, 60, 120, 240, 240, 240):
        assert _reconcile(sm, client, now=now) == 1
        payment = _payment(sm, pid)
        assert payment.status is PaymentStatus.created
        due = now + timedelta(minutes=expected_minutes)
        assert payment.next_reconcile_at == due
        now = due
    assert _payment(sm, pid).reconcile_attempts == 7
    assert _grant_count(sm, pid) == 0


def test_an_inquiry_answer_without_a_transaction_id_is_unreadable_not_absent(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    pid = _due_payment(sm, age=timedelta(hours=30))
    client = FakePaymobClient()
    client.inquiry_response = {"detail": "maintenance"}
    assert _reconcile(sm, client) == 1
    payment = _payment(sm, pid)
    assert payment.status is PaymentStatus.created
    assert payment.next_reconcile_at == FIXED_NOW + timedelta(minutes=15)
    assert _event_count(sm) == 0


def test_an_inquiry_answer_for_another_payment_is_refused(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """A's inquiry returning B's success must neither pay A nor use up B's transaction event."""
    sm = migrated_sessionmaker
    a = _due_payment(sm, age=timedelta(minutes=20))
    # Not due: only A is inquired. B carries the Paymob order its own callback names.
    b = _due_payment(sm, age=timedelta(minutes=5), paymob_order_id=265715202)
    b_success = transaction_obj(merchant_order_id=str(b))
    client = FakePaymobClient()
    client.inquiry_response = b_success
    with structlog.testing.capture_logs() as logs:
        assert _reconcile(sm, client) == 1
    assert client.inquiries == [str(a)]
    payment = _payment(sm, a)
    assert payment.status is PaymentStatus.created
    assert payment.paymob_txn_id is None
    assert payment.reconcile_attempts == 1
    assert payment.next_reconcile_at == FIXED_NOW + timedelta(minutes=15)
    assert _grant_count(sm, a) == 0
    assert _event_count(sm) == 0
    (mismatch,) = [e for e in logs if e["event"] == "paymob_inquiry_reference_mismatch"]
    assert mismatch["log_level"] == "error"
    assert mismatch["payment_id"] == str(a)
    # B's own callback still lands: its event was never consumed.
    with sm.begin() as session:
        BillingService(
            session, client, PAYMOB_SETTINGS, now=lambda: FIXED_NOW
        ).apply_transaction_callback(b_success)
    assert _payment(sm, b).status is PaymentStatus.paid
    assert _grant_count(sm, b) == 1


def _answer_with_order(pid: uuid.UUID, order: object, *, txn_id: int = 192036465) -> dict[str, Any]:
    """A success answer whose ``order`` is replaced by ``order`` (a map, a bare id, or absent)."""
    obj = transaction_obj(merchant_order_id=str(pid), txn_id=txn_id)
    if order is None:
        del obj["order"]
    else:
        obj["order"] = order
    return obj


@pytest.mark.parametrize(
    "order",
    [{"id": 222}, 222, {"id": "222"}],
    ids=["reference-less map", "bare int", "numeric string id"],
)
def test_an_inquiry_answer_naming_a_different_order_id_is_refused(
    migrated_sessionmaker: sessionmaker[Session], order: object
) -> None:
    sm = migrated_sessionmaker
    pid = _due_payment(sm, age=timedelta(minutes=20), paymob_order_id=111)
    client = FakePaymobClient()
    client.inquiry_response = _answer_with_order(pid, order)
    with structlog.testing.capture_logs() as logs:
        assert _reconcile(sm, client) == 1
    payment = _payment(sm, pid)
    assert payment.status is PaymentStatus.created
    assert payment.paymob_txn_id is None
    assert payment.next_reconcile_at == FIXED_NOW + timedelta(minutes=15)
    assert _grant_count(sm, pid) == 0
    assert _event_count(sm) == 0
    assert [e["event"] for e in logs if e["log_level"] == "error"] == [
        "paymob_inquiry_reference_mismatch"
    ]


@pytest.mark.parametrize(
    "order",
    [{"id": 111}, 111, {}, None],
    ids=["same order id map", "same bare int", "empty order map", "no order at all"],
)
def test_an_inquiry_answer_that_agrees_or_names_nothing_is_applied(
    migrated_sessionmaker: sessionmaker[Session], order: object
) -> None:
    """Pins the choice: an answer with neither reference nor order id was keyed on our
    reference, so it is trusted. Refusing missing references must turn this red."""
    sm = migrated_sessionmaker
    pid = _due_payment(sm, age=timedelta(minutes=20), paymob_order_id=111)
    client = FakePaymobClient()
    client.inquiry_response = _answer_with_order(pid, order)
    assert _reconcile(sm, client) == 1
    assert _payment(sm, pid).status is PaymentStatus.paid
    assert _grant_count(sm, pid) == 1


def test_an_inquiry_answer_naming_this_payment_is_applied(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    pid = _due_payment(sm, age=timedelta(minutes=20))
    client = FakePaymobClient()
    client.inquiry_response = transaction_obj(merchant_order_id=str(pid))
    assert _reconcile(sm, client) == 1
    assert _payment(sm, pid).status is PaymentStatus.paid


STUCK_ANSWERS: list[Callable[[], PaymobError | dict[str, Any]]] = [
    lambda: PaymobError("Paymob GET inquiry timed out", timeout=True),
    lambda: PaymobError("Paymob GET inquiry returned 503", status_code=503),
    lambda: {"detail": "maintenance"},
]


@pytest.mark.parametrize("make_answer", STUCK_ANSWERS)
def test_a_payment_that_stays_unreadable_for_a_week_stops_being_polled_but_stays_open(
    migrated_sessionmaker: sessionmaker[Session],
    make_answer: Callable[[], PaymobError | dict[str, Any]],
) -> None:
    sm = migrated_sessionmaker
    young = _due_payment(sm, age=RECONCILE_STUCK_AFTER - timedelta(hours=1))
    old = _due_payment(sm, age=RECONCILE_STUCK_AFTER)
    client = FakePaymobClient()
    client.inquiry_response = make_answer()
    with structlog.testing.capture_logs() as logs:
        assert _reconcile(sm, client) == 2
    assert _payment(sm, young).next_reconcile_at == FIXED_NOW + timedelta(minutes=15)
    stuck = _payment(sm, old)
    assert stuck.status is PaymentStatus.created  # R20b: never failed on an unknown outcome
    assert stuck.next_reconcile_at is None
    (entry,) = [e for e in logs if e["event"] == "paymob_reconcile_stuck"]
    assert entry["log_level"] == "error"
    assert entry["payment_id"] == str(old)
    # No longer selected, so no further inquiries.
    client.inquiries.clear()
    assert _reconcile(sm, client, now=FIXED_NOW + timedelta(days=1)) == 1  # only `young`
    assert client.inquiries == [str(young)]


def test_the_stuck_threshold_is_seven_days() -> None:
    assert timedelta(days=7) == RECONCILE_STUCK_AFTER


def test_a_poisoned_payment_older_than_a_week_stops_being_polled_but_stays_open(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    poison = _due_payment(sm, age=RECONCILE_STUCK_AFTER + timedelta(hours=1))
    client = _PoisonedClient(poison)
    with structlog.testing.capture_logs() as logs:
        assert _reconcile(sm, client) == 0
    payment = _payment(sm, poison)
    assert payment.status is PaymentStatus.created
    assert payment.next_reconcile_at is None
    stuck = [e for e in logs if e["event"] == "paymob_reconcile_stuck"]
    assert [e["payment_id"] for e in stuck] == [str(poison)]
    client.inquiries.clear()
    assert _reconcile(sm, client, now=FIXED_NOW + timedelta(days=1)) == 0
    assert client.inquiries == []


def test_a_stuck_payment_is_still_paid_by_a_late_callback(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    pid = _due_payment(sm, age=RECONCILE_STUCK_AFTER, paymob_order_id=265715202)
    client = FakePaymobClient()
    client.inquiry_response = PaymobError("down", status_code=503)
    _reconcile(sm, client)
    assert _payment(sm, pid).next_reconcile_at is None
    with sm.begin() as session:
        BillingService(
            session, client, PAYMOB_SETTINGS, now=lambda: FIXED_NOW
        ).apply_transaction_callback(transaction_obj(merchant_order_id=str(pid)))
    assert _payment(sm, pid).status is PaymentStatus.paid
    assert _grant_count(sm, pid) == 1


def test_closed_payments_are_never_inquired(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    _due_payment(sm, age=timedelta(hours=1), status=PaymentStatus.paid)
    _due_payment(sm, age=timedelta(hours=1), status=PaymentStatus.failed)
    client = FakePaymobClient()
    assert _reconcile(sm, client) == 0
    assert client.inquiries == []


def test_the_batch_limit_bounds_one_pass(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    for _ in range(3):
        _due_payment(sm, age=timedelta(minutes=20))
    client = FakePaymobClient()
    with sm() as session:
        handled = BillingService(
            session, client, PAYMOB_SETTINGS, now=lambda: FIXED_NOW
        ).reconcile_pending(now=FIXED_NOW, limit=2)
    assert handled == 2
    assert len(client.inquiries) == 2


# -- amendment A: lock order is payment row, then event insert ----------------------


def test_reconcile_locks_the_payment_before_recording_its_event(
    migrated_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    sm = migrated_sessionmaker
    pid = _due_payment(sm, age=timedelta(minutes=20))
    client = FakePaymobClient()
    client.inquiry_response = transaction_obj(merchant_order_id=str(pid))
    statements: list[str] = []

    def record(
        conn: Connection,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        many: bool,
    ) -> None:
        statements.append(statement)

    # ``_payment_for_callback`` would lock the row a second time; reconcile already holds it.
    def forbidden(self: BillingService, obj: object, order_map: object) -> Payment | None:
        raise AssertionError("reconcile must not look the payment up by order again")

    monkeypatch.setattr(BillingService, "_payment_for_callback", forbidden)
    with sm() as session:
        bind = session.get_bind()
        assert isinstance(bind, sa.engine.Engine)
        engine: Engine = bind
        event.listen(engine, "before_cursor_execute", record)
        try:
            handled = BillingService(
                session, client, PAYMOB_SETTINGS, now=lambda: FIXED_NOW
            ).reconcile_pending(now=FIXED_NOW)
        finally:
            event.remove(engine, "before_cursor_execute", record)
    assert handled == 1
    lock = next(i for i, s in enumerate(statements) if "FOR UPDATE SKIP LOCKED" in s)
    insert = next(i for i, s in enumerate(statements) if "INSERT INTO paymob_events" in s)
    assert lock < insert
    assert not any(
        "FOR UPDATE" in s and "SKIP LOCKED" not in s for s in statements[: insert + 1]
    ), "the payment row is locked once, by the reconcile select"


# -- amendment C: one poison row must not block the rest ----------------------------


class _PoisonedClient(FakePaymobClient):
    """Raises an unexpected (non-Paymob) error for one reference only."""

    def __init__(self, poison: uuid.UUID) -> None:
        super().__init__()
        self.poison = str(poison)

    def inquire_by_order_ref(self, merchant_order_id: str) -> dict[str, Any] | None:
        if merchant_order_id == self.poison:
            self.inquiries.append(merchant_order_id)
            raise RuntimeError("unexpected inquiry bug")
        return super().inquire_by_order_ref(merchant_order_id)


def test_a_poison_payment_is_backed_off_and_the_batch_continues(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    poison = _due_payment(sm, age=timedelta(hours=3))  # earliest next_reconcile_at: picked first
    healthy = _due_payment(sm, age=timedelta(hours=1))
    client = _PoisonedClient(poison)
    client.inquiry_response = transaction_obj(merchant_order_id=str(healthy))
    with structlog.testing.capture_logs() as logs:
        assert _reconcile(sm, client) == 1
    bad = _payment(sm, poison)
    assert bad.status is PaymentStatus.created
    assert bad.reconcile_attempts == 1
    assert bad.next_reconcile_at == FIXED_NOW + timedelta(minutes=15)
    assert _payment(sm, healthy).status is PaymentStatus.paid
    assert _grant_count(sm, healthy) == 1
    errors = [entry for entry in logs if entry["event"] == "paymob_reconcile_error"]
    assert [entry["payment_id"] for entry in errors] == [str(poison)]
    assert errors[0]["log_level"] == "error"


def test_a_poison_payment_stops_blocking_the_queue_on_the_next_pass(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    poison = _due_payment(sm, age=timedelta(hours=3))
    client = _PoisonedClient(poison)
    assert _reconcile(sm, client) == 0
    assert client.inquiries == [str(poison)]
    # Not due again until its backoff has passed.
    assert _reconcile(sm, client, now=FIXED_NOW + timedelta(minutes=14)) == 0
    assert client.inquiries == [str(poison)]
    assert _reconcile(sm, client, now=FIXED_NOW + timedelta(minutes=15)) == 0
    assert client.inquiries == [str(poison), str(poison)]
    bad = _payment(sm, poison)
    assert bad.reconcile_attempts == 2
    assert bad.next_reconcile_at == FIXED_NOW + timedelta(minutes=45)


def test_a_failure_after_the_event_insert_rolls_the_whole_payment_back(
    migrated_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The paid handler raises after the event and status were written: none of it sticks."""
    sm = migrated_sessionmaker
    pid = _due_payment(sm, age=timedelta(minutes=20))

    def boom(session: Session, payment: Payment, obj: billing_repo.JsonMap) -> None:
        raise RuntimeError("handler bug")

    monkeypatch.setitem(billing_repo._PAID_HANDLERS, PaymentPurpose.credit_pack, boom)
    client = FakePaymobClient()
    client.inquiry_response = transaction_obj(merchant_order_id=str(pid))
    assert _reconcile(sm, client) == 0
    payment = _payment(sm, pid)
    assert payment.status is PaymentStatus.created
    assert payment.paid_at is None
    assert payment.paymob_txn_id is None
    assert payment.reconcile_attempts == 1
    assert payment.next_reconcile_at == FIXED_NOW + timedelta(minutes=15)
    assert _event_count(sm) == 0
    assert _grant_count(sm, pid) == 0


# -- amendment F: two runners ---------------------------------------------------------


def test_a_payment_locked_by_another_runner_is_skipped_not_inquired(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    pid = _due_payment(sm, age=timedelta(minutes=20))
    client = FakePaymobClient()
    client.inquiry_response = transaction_obj(merchant_order_id=str(pid))
    with sm() as holder:  # connection 1: another replica is mid-way through this payment
        holder.scalars(sa.select(Payment).where(Payment.id == pid).with_for_update()).one()
        assert (
            _reconcile(sm, client, lock_timeout="3s") == 0
        )  # connection 2: SKIP LOCKED passes it by
        assert client.inquiries == []
        assert _payment_unlocked_fields(holder, pid) == (PaymentStatus.created, 0)
    # The holder released its lock without finishing: the next pass takes the payment.
    assert _reconcile(sm, client) == 1
    assert client.inquiries == [str(pid)]
    assert _payment(sm, pid).status is PaymentStatus.paid
    assert _grant_count(sm, pid) == 1


def _payment_unlocked_fields(session: Session, pid: uuid.UUID) -> tuple[PaymentStatus, int]:
    payment = session.get(Payment, pid)
    assert payment is not None
    return payment.status, payment.reconcile_attempts


def test_a_runner_skips_the_locked_payment_and_settles_the_free_one(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    locked = _due_payment(sm, age=timedelta(hours=3))  # first in queue order
    free = _due_payment(sm, age=timedelta(hours=1))
    client = FakePaymobClient()
    client.inquiry_response = transaction_obj(merchant_order_id=str(free))
    with sm() as holder:
        holder.scalars(sa.select(Payment).where(Payment.id == locked).with_for_update()).one()
        assert _reconcile(sm, client, lock_timeout="3s") == 1
    assert client.inquiries == [str(free)]
    assert _payment(sm, free).status is PaymentStatus.paid
    assert _payment(sm, locked).status is PaymentStatus.created
    assert _payment(sm, locked).reconcile_attempts == 0


def test_a_locked_payment_behind_a_free_one_is_skipped_on_the_next_select(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """The second select of the pass (after the first commit) must skip too."""
    sm = migrated_sessionmaker
    free = _due_payment(sm, age=timedelta(hours=3))  # first in queue order
    locked = _due_payment(sm, age=timedelta(hours=1))
    client = FakePaymobClient()
    client.inquiry_response = transaction_obj(merchant_order_id=str(free))
    with sm() as holder:
        holder.scalars(sa.select(Payment).where(Payment.id == locked).with_for_update()).one()
        assert _reconcile(sm, client, lock_timeout="3s") == 1
    assert client.inquiries == [str(free)]
    assert _payment(sm, free).status is PaymentStatus.paid
    assert _payment(sm, locked).reconcile_attempts == 0


# -- the job function -----------------------------------------------------------------


def test_the_job_function_opens_its_own_session(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    pid = _due_payment(sm, age=timedelta(minutes=20))
    client = FakePaymobClient()
    client.inquiry_response = transaction_obj(merchant_order_id=str(pid))
    assert reconcile_pending_payments(sm, client, PAYMOB_SETTINGS, now=FIXED_NOW) == 1
    assert _payment(sm, pid).status is PaymentStatus.paid


# -- the sweeper ----------------------------------------------------------------------


def _sweeper(
    sm: sessionmaker[Session], billing_reconcile: Callable[[datetime], int] | None = None
) -> Sweeper:
    return Sweeper(
        sessionmaker=sm,
        announcements=AnnouncementService(sm, ClassService(sm)),
        notifications=NotificationService(sm, NotificationPreferencesService(sm)),
        transport=RecordingPushTransport(),
        settings=NotificationsSettings(),
        now=lambda: FIXED_NOW,
        billing_reconcile=billing_reconcile,
    )


def test_the_sweeper_runs_billing_reconcile_pending_when_wired(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    seen: list[datetime] = []

    def job(now: datetime) -> int:
        seen.append(now)
        return 3

    results = _sweeper(migrated_sessionmaker, job).sweep_once()
    assert results["billing.reconcile_pending"] == 3
    assert seen == [FIXED_NOW]


def test_the_sweeper_leaves_billing_out_when_paymob_is_unconfigured(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    assert "billing.reconcile_pending" not in _sweeper(migrated_sessionmaker).sweep_once()


def test_a_failing_billing_job_does_not_stop_the_other_sweeper_jobs(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    def job(now: datetime) -> int:
        raise RuntimeError("billing down")

    results = _sweeper(migrated_sessionmaker, job).sweep_once()
    assert results["billing.reconcile_pending"] is None
    assert results["publish_due_announcements"] is not None


# -- deps_billing ---------------------------------------------------------------------


class _SpyClient(FakePaymobClient):
    def __init__(self, settings: PaymobSettings) -> None:
        super().__init__(settings)
        self.closed = 0

    def close(self) -> None:
        self.closed += 1
        super().close()


@pytest.fixture
def billing_deps(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[_SpyClient]]:
    """``deps_billing`` over configured Paymob settings, recording every client it builds."""
    built: list[_SpyClient] = []

    def factory(settings: PaymobSettings) -> PaymobClient:
        client = _SpyClient(settings)
        built.append(client)
        return client

    settings = deps.get_settings().model_copy(update={"paymob": PAYMOB_SETTINGS})
    monkeypatch.setattr(deps_billing, "get_settings", lambda: settings)
    monkeypatch.setattr(deps_billing, "PaymobClient", factory)
    deps_billing.get_paymob_client.cache_clear()
    yield built
    deps_billing.get_paymob_client.cache_clear()


def test_reset_closes_the_cached_client_before_clearing_it(billing_deps: list[_SpyClient]) -> None:
    first = deps_billing.get_paymob_client()
    assert deps_billing.get_paymob_client() is first
    deps_billing.reset_billing_singletons()
    assert isinstance(first, _SpyClient)
    assert first.closed == 1
    second = deps_billing.get_paymob_client()
    assert second is not first
    assert len(billing_deps) == 2


def test_reset_with_no_cached_client_builds_nothing(billing_deps: list[_SpyClient]) -> None:
    deps_billing.reset_billing_singletons()
    deps_billing.reset_billing_singletons()
    assert billing_deps == []


def test_reset_still_clears_the_cache_when_close_fails(billing_deps: list[_SpyClient]) -> None:
    first = deps_billing.get_paymob_client()
    assert isinstance(first, _SpyClient)

    def broken_close() -> None:
        raise OSError("pool already torn down")

    first.close = broken_close  # type: ignore[method-assign]
    with pytest.raises(OSError, match="pool already torn down"):
        deps_billing.reset_billing_singletons()
    assert deps_billing.get_paymob_client() is not first


def test_deps_reset_singletons_resets_the_billing_singletons(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(deps_billing, "reset_billing_singletons", lambda: calls.append("reset"))
    deps.reset_singletons()
    assert calls == ["reset"]


def test_the_reconcile_job_is_none_when_checkout_is_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = deps.get_settings().model_copy(update={"paymob": PaymobSettings()})
    monkeypatch.setattr(deps_billing, "get_settings", lambda: settings)
    assert deps_billing.get_billing_reconcile_job() is None


def test_the_reconcile_job_runs_the_pass_with_the_process_collaborators(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = deps.get_settings().model_copy(update={"paymob": PAYMOB_SETTINGS})
    client = FakePaymobClient()
    sentinel = SimpleNamespace(name="sessionmaker")
    seen: list[tuple[object, object, object, datetime]] = []

    def fake_pass(
        sessionmaker_: object, client_: object, settings_: object, *, now: datetime
    ) -> int:
        seen.append((sessionmaker_, client_, settings_, now))
        return 7

    monkeypatch.setattr(deps_billing, "get_settings", lambda: settings)
    monkeypatch.setattr(deps_billing, "get_paymob_client", lambda: client)
    monkeypatch.setattr(deps_billing, "get_billing_sessionmaker", lambda: sentinel)
    monkeypatch.setattr(deps_billing, "reconcile_pending_payments", fake_pass)
    job = deps_billing.get_billing_reconcile_job()
    assert job is not None
    assert job(FIXED_NOW) == 7
    assert seen == [(sentinel, client, PAYMOB_SETTINGS, FIXED_NOW)]


def test_get_sweeper_wires_the_billing_job_only_when_one_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def job(now: datetime) -> int:
        return 1

    try:
        deps.get_sweeper.cache_clear()
        monkeypatch.setattr(deps_billing, "get_billing_reconcile_job", lambda: job)
        assert deps.get_sweeper().billing_reconcile is job
        deps.get_sweeper.cache_clear()
        monkeypatch.setattr(deps_billing, "get_billing_reconcile_job", lambda: None)
        assert deps.get_sweeper().billing_reconcile is None
    finally:
        deps.get_sweeper.cache_clear()
