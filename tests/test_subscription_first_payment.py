"""A verified first payment activates the subscription, its period and its allowance (§5.1 step 4).

Real Postgres (a throwaway ``create_all`` database). The handler is driven directly for the
money rules and through Phase 02's callback and reconcile paths for the wiring. A first payment
that lands while another plan is live is turned into credits (UD-3, UD-10) by the one public
helper :func:`convert_payment_to_credits`, which Phase 06 reuses.
"""

from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from structlog.testing import capture_logs

from lemely.db import billing_repo, subscription_repo
from lemely.db.billing_repo import CREDIT_EXPIRY_MONTHS, BillingService, add_months
from lemely.db.models.billing import (
    Payment,
    PaymentPurpose,
    PaymentStatus,
    PaymobEvent,
    PaymobEventKind,
    PlanAudience,
    PlanTier,
    Subscription,
    SubscriptionPeriod,
)
from lemely.db.models.billing_ops import BillingSettings, CreditConversionRate
from lemely.db.models.enums import PlanInterval, Role, SubscriptionStatus
from lemely.db.models.team import TeacherMember, TeacherMemberStatus
from lemely.db.models.tutoring import EmailOutbox
from lemely.db.models.usage import GrantKind, UsageGrant, UsageGrantBalance
from lemely.db.subscription_repo import (
    NoCreditRate,
    SubscriptionService,
    convert_payment_to_credits,
    credit_units_for_amount,
    handle_subscription_first,
)
from lemely.db.teacher_team_repo import month_end
from lemely.db.usage_ledger_repo import UsageLedger
from lemely.runtime.config import Settings
from lemely.web import create_app
from lemely.web.deps import get_settings
from lemely.web.deps_billing import get_billing_sessionmaker, get_paymob_client
from tests.paymob_fixtures import (
    INTENTION_RESPONSE,
    PAYMOB_SETTINGS,
    seed_pack,
    seed_payment,
    sign_transaction,
    transaction_callback,
    transaction_obj,
)
from tests.subscription_fixtures import (
    T0,
    FakePaymobClient,
    grants_of,
    paymob_settings,
    seed_debt,
    seed_first_payment,
    seed_seat,
    seed_subscription,
    seed_tier,
    seed_user,
    throwaway_database,
)
from tests.team_db import add_assistant, emptied_after

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi import FastAPI
    from sqlalchemy.orm import Session, sessionmaker

PAID_AT = T0 + timedelta(minutes=7)  # never equal to T0, so a clock mix-up shows


@pytest.fixture(scope="module")
def _database() -> Iterator[sessionmaker[Session]]:
    with throwaway_database() as factory:
        yield factory


@pytest.fixture
def pg_sessionmaker(_database: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    """The module's database, emptied after each test.

    Credit packs, conversion rates and ``paymob_events`` (deduped by transaction id) do not hang
    off ``users``, so they are cleared here too.
    """
    yield from emptied_after(_database)
    with _database.begin() as session:
        session.execute(
            sa.text("TRUNCATE credit_packs, credit_conversion_rates, paymob_events CASCADE")
        )


# -- seeding ----------------------------------------------------------------------------


def _pending(
    sm: sessionmaker[Session],
    *,
    interval: PlanInterval = PlanInterval.monthly,
    allowance: int = 1_000,
    status: SubscriptionStatus = SubscriptionStatus.pending_first_payment,
    amount_minor: int = 10_000,
    txn_id: int | None = 777,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """``(student, subscription, payment)`` for a paid, not yet activated first payment."""
    student = seed_user(sm, Role.student)
    tier = seed_tier(sm, interval=interval, allowance_units=allowance)
    sid = seed_subscription(
        sm,
        user_id=student,
        tier_id=tier,
        payer_id=student,
        status=status,
        period_start=None,
        period_end=None,
    )
    pid = seed_first_payment(
        sm, subscription_id=sid, amount_minor=amount_minor, paymob_txn_id=txn_id, paid_at=PAID_AT
    )
    return student, sid, pid


def _set_validity(sm: sessionmaker[Session], months: int = 12) -> None:
    """The admin-set credit validity: the singleton ``billing_settings`` row (``id = 1``).

    The row is upserted because ``emptied_after`` truncates it (it references ``users``).
    """
    with sm.begin() as session:
        row = session.get(BillingSettings, 1)
        if row is None:
            session.add(BillingSettings(id=1, credit_validity_months=months))
        else:
            row.credit_validity_months = months
            row.version += 1


def _delete_settings(sm: sessionmaker[Session]) -> None:
    with sm.begin() as session:
        session.execute(sa.delete(BillingSettings))


def _set_rate(
    sm: sessionmaker[Session], currency: str = "EGP", units_per_minor: str = "0.01"
) -> None:
    """The admin-set rate for ``currency`` (UD-12); a second call is an edit (version 2).

    A conversion needs the validity setting too, so the default row (12 months) is made first
    when it is missing.
    """
    with sm() as session:
        missing = session.get(BillingSettings, 1) is None
    if missing:
        _set_validity(sm)
    with sm.begin() as session:
        row = session.scalars(
            sa.select(CreditConversionRate).where(CreditConversionRate.currency == currency)
        ).one_or_none()
        if row is None:
            session.add(
                CreditConversionRate(currency=currency, units_per_minor=Decimal(units_per_minor))
            )
        else:
            row.units_per_minor = Decimal(units_per_minor)
            row.version += 1


def _handle(sm: sessionmaker[Session], pid: uuid.UUID) -> None:
    with sm.begin() as session:
        payment = session.get(Payment, pid)
        assert payment is not None
        handle_subscription_first(session, payment, {})


def _periods(sm: sessionmaker[Session], sid: uuid.UUID) -> list[SubscriptionPeriod]:
    with sm() as session:
        return list(
            session.scalars(
                sa.select(SubscriptionPeriod)
                .where(SubscriptionPeriod.subscription_id == sid)
                .order_by(SubscriptionPeriod.period_start)
            )
        )


def _subscription(sm: sessionmaker[Session], sid: uuid.UUID) -> Subscription:
    with sm() as session:
        row = session.get(Subscription, sid)
        assert row is not None
        return row


def _payment(sm: sessionmaker[Session], pid: uuid.UUID) -> Payment:
    with sm() as session:
        row = session.get(Payment, pid)
        assert row is not None
        return row


def _remaining(sm: sessionmaker[Session], grant_id: uuid.UUID) -> int:
    with sm() as session:
        return session.scalars(
            sa.select(UsageGrantBalance.remaining).where(UsageGrantBalance.grant_id == grant_id)
        ).one()


def _outbox(sm: sessionmaker[Session], recipient: uuid.UUID) -> list[EmailOutbox]:
    with sm() as session:
        return list(
            session.scalars(
                sa.select(EmailOutbox)
                .where(EmailOutbox.recipient_user_id == recipient)
                .order_by(EmailOutbox.created_at, EmailOutbox.id)
            )
        )


def _stored_created_event(
    sm: sessionmaker[Session],
    *,
    remote: dict[str, Any],
    processed_at: datetime | None = None,
) -> uuid.UUID:
    event_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            PaymobEvent(
                id=event_id,
                kind=PaymobEventKind.subscription,
                dedupe_key=f"sub:{remote.get('id')}:Subscription Created:{event_id}",
                payload={"body": {"trigger_type": "Subscription Created"}, "remote": remote},
                processed_at=processed_at,
            )
        )
    return event_id


def _event(sm: sessionmaker[Session], event_id: uuid.UUID) -> PaymobEvent:
    with sm() as session:
        row = session.get(PaymobEvent, event_id)
        assert row is not None
        return row


def _events_named(logs: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    return [entry for entry in logs if entry["event"] == name]


def _superseded(
    sm: sessionmaker[Session],
    *,
    other: SubscriptionStatus = SubscriptionStatus.active,
    other_payer_is_student: bool = True,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    """A paid first payment of an ``expired`` (superseded) checkout while ``other`` is live.

    Returns ``(student, superseded subscription, its payment, the live subscription)``.
    """
    student, sid, pid = _pending(sm, status=SubscriptionStatus.expired)
    live = seed_subscription(
        sm,
        user_id=student,
        tier_id=seed_tier(sm),
        payer_id=student if other_payer_is_student else None,
        status=other,
        is_manually_activated=not other_payer_is_student,
    )
    return student, sid, pid, live


# -- the money: one period, one grant -----------------------------------------------------


def test_first_payment_activates_with_one_period_and_one_allowance(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student, sid, pid = _pending(pg_sessionmaker)
    _handle(pg_sessionmaker, pid)

    sub = _subscription(pg_sessionmaker, sid)
    assert sub.status is SubscriptionStatus.active
    assert (sub.current_period_start, sub.current_period_end) == (
        PAID_AT,
        PAID_AT + timedelta(days=30),
    )
    assert sub.activated_at == PAID_AT
    assert sub.grace_until is None
    assert sub.paymob_amount_minor == 10_000
    assert sub.version == 2  # seeded at 1, bumped once
    [period] = _periods(pg_sessionmaker, sid)
    assert (period.period_start, period.period_end, period.payment_id) == (
        PAID_AT,
        PAID_AT + timedelta(days=30),
        pid,
    )
    [grant] = grants_of(pg_sessionmaker, student)
    assert grant.kind is GrantKind.period_allowance
    assert (grant.units, grant.visible, grant.teacher_member_id) == (1_000, False, None)
    assert grant.owner_user_id == student
    assert grant.effective_at == PAID_AT
    assert grant.expires_at == PAID_AT + timedelta(days=30)
    assert (grant.subscription_period_id, grant.payment_id) == (period.id, pid)


def test_the_beneficiary_not_the_payer_owns_the_allowance(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    parent = seed_user(pg_sessionmaker, Role.parent)
    child = seed_user(pg_sessionmaker, Role.student)
    sid = seed_subscription(
        pg_sessionmaker,
        user_id=child,
        tier_id=seed_tier(pg_sessionmaker),
        payer_id=parent,
        status=SubscriptionStatus.pending_first_payment,
        period_start=None,
        period_end=None,
    )
    pid = seed_first_payment(pg_sessionmaker, subscription_id=sid, paid_at=PAID_AT)
    _handle(pg_sessionmaker, pid)
    assert len(grants_of(pg_sessionmaker, child)) == 1
    assert grants_of(pg_sessionmaker, parent) == []


def test_yearly_period_is_360_days(pg_sessionmaker: sessionmaker[Session]) -> None:
    _, sid, pid = _pending(pg_sessionmaker, interval=PlanInterval.yearly)
    _handle(pg_sessionmaker, pid)
    [period] = _periods(pg_sessionmaker, sid)
    assert period.period_end - period.period_start == timedelta(days=360)


def test_handler_is_idempotent(pg_sessionmaker: sessionmaker[Session]) -> None:
    student, sid, pid = _pending(pg_sessionmaker)
    _handle(pg_sessionmaker, pid)
    with capture_logs() as logs:
        _handle(pg_sessionmaker, pid)  # no IntegrityError on the period's unique payment
    assert [entry for entry in logs if entry.get("alert")] == []  # a replay is not an incident
    assert len(_periods(pg_sessionmaker, sid)) == 1
    assert len(grants_of(pg_sessionmaker, student)) == 1
    assert _subscription(pg_sessionmaker, sid).version == 2


def test_allowance_repays_debt_first(pg_sessionmaker: sessionmaker[Session]) -> None:
    student, _, pid = _pending(pg_sessionmaker, allowance=100)
    seed_debt(pg_sessionmaker, student, 30)  # adjust(-n) never creates debt (Phase 01)
    with pg_sessionmaker() as session:
        assert UsageLedger(session).has_debt(student)  # non-vacuity
    _handle(pg_sessionmaker, pid)
    with pg_sessionmaker() as session:
        assert not UsageLedger(session).has_debt(student)
    [grant] = grants_of(pg_sessionmaker, student)
    assert _remaining(pg_sessionmaker, grant.id) == 70


def test_zero_allowance_tier_makes_a_period_but_no_grant(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student, sid, pid = _pending(pg_sessionmaker, allowance=0)
    _handle(pg_sessionmaker, pid)
    assert len(_periods(pg_sessionmaker, sid)) == 1
    assert grants_of(pg_sessionmaker, student) == []
    assert _subscription(pg_sessionmaker, sid).status is SubscriptionStatus.active


def test_a_payment_without_paid_at_is_refused_not_given_the_wall_clock(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student, sid, pid = _pending(pg_sessionmaker)
    with pg_sessionmaker.begin() as session:
        payment = session.get(Payment, pid)
        assert payment is not None
        payment.paid_at = None
    with pytest.raises(RuntimeError, match="paid_at"):
        _handle(pg_sessionmaker, pid)
    assert _subscription(pg_sessionmaker, sid).status is SubscriptionStatus.pending_first_payment
    assert grants_of(pg_sessionmaker, student) == []


def test_a_superseded_checkout_with_nothing_else_live_is_activated(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student, sid, pid = _pending(pg_sessionmaker, status=SubscriptionStatus.expired)
    _handle(pg_sessionmaker, pid)
    assert _subscription(pg_sessionmaker, sid).status is SubscriptionStatus.active
    assert len(grants_of(pg_sessionmaker, student)) == 1


@pytest.mark.parametrize(
    "state",
    [
        SubscriptionStatus.active,
        SubscriptionStatus.past_due,
        SubscriptionStatus.cancelled,
        SubscriptionStatus.inactive,
    ],
)
def test_a_state_that_cannot_take_a_first_payment_changes_nothing_and_alerts(
    pg_sessionmaker: sessionmaker[Session], state: SubscriptionStatus
) -> None:
    student, sid, pid = _pending(pg_sessionmaker, status=state)
    with capture_logs() as logs:
        _handle(pg_sessionmaker, pid)
    [entry] = _events_named(logs, "subscription_first_paid_in_unexpected_state")
    assert entry["alert"] is True
    assert _subscription(pg_sessionmaker, sid).status is state
    assert _periods(pg_sessionmaker, sid) == []
    assert grants_of(pg_sessionmaker, student) == []
    assert _payment(pg_sessionmaker, pid).grant_units is None


def test_a_tier_that_lost_its_interval_is_not_activated_and_alerts(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student, sid, pid = _pending(pg_sessionmaker)
    with pg_sessionmaker.begin() as session:
        tier = session.scalars(sa.select(PlanTier)).one()
        tier.interval = None
    with capture_logs() as logs:
        _handle(pg_sessionmaker, pid)
    [entry] = _events_named(logs, "subscription_first_paid_for_unusable_tier")
    assert entry["alert"] is True
    assert _subscription(pg_sessionmaker, sid).status is SubscriptionStatus.pending_first_payment
    assert grants_of(pg_sessionmaker, student) == []


# -- through Phase 02 ---------------------------------------------------------------------


def _checkout(
    sm: sessionmaker[Session],
    client: FakePaymobClient,
    *,
    student: uuid.UUID | None = None,
    tier: uuid.UUID | None = None,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, int]:
    """A real checkout; returns ``(student, subscription id, payment id, paymob order id)``."""
    student = student or seed_user(sm, Role.student)
    tier = tier or seed_tier(sm, price_minor=10_000)
    with sm() as session:  # create_intention_checkout commits itself
        result = SubscriptionService(
            session, client, paymob_settings()
        ).create_subscription_checkout(payer_user_id=student, plan_tier_id=tier, now=T0)
        session.commit()
    order_id = _payment(sm, result.payment_id).paymob_order_id
    assert order_id is not None
    return student, result.subscription_id, result.payment_id, order_id


def _callback(
    sm: sessionmaker[Session],
    client: FakePaymobClient,
    obj: dict[str, Any],
    *,
    now: datetime = PAID_AT,
) -> None:
    with sm.begin() as session:
        BillingService(
            session, client, paymob_settings(), now=lambda: now
        ).apply_transaction_callback(obj)


def _obj_for(pid: uuid.UUID, order_id: int, **overrides: Any) -> dict[str, Any]:
    return transaction_obj(
        txn_id=overrides.pop("txn_id", 777),
        order_id=order_id,
        merchant_order_id=str(pid),
        **overrides,
    )


def test_a_verified_callback_activates_the_subscription(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    client = FakePaymobClient()
    student, sid, pid, order = _checkout(pg_sessionmaker, client)
    _callback(pg_sessionmaker, client, _obj_for(pid, order))

    assert _payment(pg_sessionmaker, pid).status is PaymentStatus.paid
    sub = _subscription(pg_sessionmaker, sid)
    assert sub.status is SubscriptionStatus.active
    assert sub.activated_at == PAID_AT
    assert sub.paymob_amount_minor == 10_000
    [grant] = grants_of(pg_sessionmaker, student)
    assert grant.effective_at == PAID_AT


def test_the_same_callback_twice_grants_once(pg_sessionmaker: sessionmaker[Session]) -> None:
    client = FakePaymobClient()
    student, sid, pid, order = _checkout(pg_sessionmaker, client)
    obj = _obj_for(pid, order)
    _callback(pg_sessionmaker, client, obj)
    _callback(pg_sessionmaker, client, obj)
    assert len(_periods(pg_sessionmaker, sid)) == 1
    assert len(grants_of(pg_sessionmaker, student)) == 1


def test_a_callback_for_another_amount_activates_nothing(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    client = FakePaymobClient()
    student, sid, pid, order = _checkout(pg_sessionmaker, client)
    _callback(pg_sessionmaker, client, _obj_for(pid, order, amount_cents=9_999))
    assert _payment(pg_sessionmaker, pid).status is PaymentStatus.failed_mismatch
    assert _subscription(pg_sessionmaker, sid).status is SubscriptionStatus.pending_first_payment
    assert _periods(pg_sessionmaker, sid) == []
    assert grants_of(pg_sessionmaker, student) == []


def test_reconcile_reaches_the_handler_without_any_router_import(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    client = FakePaymobClient()
    student, sid, pid, order = _checkout(pg_sessionmaker, client)
    client.inquiry_response = _obj_for(pid, order)
    when = T0 + timedelta(hours=1)
    with pg_sessionmaker() as session:
        handled = BillingService(
            session, client, paymob_settings(), now=lambda: when
        ).reconcile_pending(now=when)
    assert handled == 1
    sub = _subscription(pg_sessionmaker, sid)
    assert (sub.status, sub.activated_at) == (SubscriptionStatus.active, when)
    assert len(grants_of(pg_sessionmaker, student)) == 1


def test_the_handler_is_registered_for_subscription_first() -> None:
    assert (
        billing_repo.paid_handler_for(PaymentPurpose.subscription_first)
        is subscription_repo.handle_subscription_first
    )


# -- linking the Paymob subscription ------------------------------------------------------


def test_links_a_subscription_created_event_that_arrived_first(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _, sid, pid = _pending(pg_sessionmaker)
    event = _stored_created_event(pg_sessionmaker, remote={"id": 4321, "initial_transaction": 777})
    _handle(pg_sessionmaker, pid)
    assert _subscription(pg_sessionmaker, sid).paymob_subscription_id == 4321
    assert _event(pg_sessionmaker, event).processed_at == PAID_AT


def test_an_event_for_another_transaction_is_left_alone(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _, sid, pid = _pending(pg_sessionmaker)
    event = _stored_created_event(pg_sessionmaker, remote={"id": 4321, "initial_transaction": 778})
    _handle(pg_sessionmaker, pid)
    assert _subscription(pg_sessionmaker, sid).paymob_subscription_id is None
    assert _event(pg_sessionmaker, event).processed_at is None


@pytest.mark.parametrize(
    "remote",
    [
        {"id": 4321, "initial_transaction": "777"},  # compared as integers, never as text
        {"id": 4321, "initial_transaction": 777.0},  # jsonb equates 777.0 with 777; we do not
        {"id": "4321", "initial_transaction": 777},  # the Paymob id must be an integer
        {"id": True, "initial_transaction": 777},  # a bool is not an id
        {"initial_transaction": 777},
    ],
    ids=["txn-as-text", "txn-as-float", "id-as-text", "id-as-bool", "no-id"],
)
def test_an_event_whose_remote_facts_are_not_integers_is_not_linked(
    pg_sessionmaker: sessionmaker[Session], remote: dict[str, Any]
) -> None:
    _, sid, pid = _pending(pg_sessionmaker)
    event = _stored_created_event(pg_sessionmaker, remote=remote)
    _handle(pg_sessionmaker, pid)
    assert _subscription(pg_sessionmaker, sid).paymob_subscription_id is None
    assert _event(pg_sessionmaker, event).processed_at is None


def test_an_event_naming_the_transaction_only_in_the_unsigned_body_links_nothing(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The body is unsigned (R26): an event naming the txn only there links nothing."""
    _, sid, pid = _pending(pg_sessionmaker)
    event_id = uuid.uuid4()
    with pg_sessionmaker.begin() as session:
        session.add(
            PaymobEvent(
                id=event_id,
                kind=PaymobEventKind.subscription,
                dedupe_key=f"sub:forged:{event_id}",
                payload={
                    "body": {"subscription_data": {"id": 4321, "initial_transaction": 777}},
                    "remote": {"id": 4321},
                },
            )
        )
    _handle(pg_sessionmaker, pid)
    assert _subscription(pg_sessionmaker, sid).paymob_subscription_id is None


def test_a_paymob_id_another_subscription_holds_is_not_linked_and_alerts(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _, sid, pid = _pending(pg_sessionmaker)
    other = seed_user(pg_sessionmaker, Role.student)
    seed_subscription(
        pg_sessionmaker,
        user_id=other,
        tier_id=seed_tier(pg_sessionmaker),
        payer_id=other,
        paymob_subscription_id=4321,
    )
    event = _stored_created_event(pg_sessionmaker, remote={"id": 4321, "initial_transaction": 777})
    with capture_logs() as logs:
        _handle(pg_sessionmaker, pid)  # no IntegrityError, the activation still happens
    [entry] = _events_named(logs, "subscription_created_event_link_conflict")
    assert entry["alert"] is True
    sub = _subscription(pg_sessionmaker, sid)
    assert (sub.status, sub.paymob_subscription_id) == (SubscriptionStatus.active, None)
    assert _event(pg_sessionmaker, event).processed_at is None


def test_a_processed_event_is_not_linked_again(pg_sessionmaker: sessionmaker[Session]) -> None:
    _, sid, pid = _pending(pg_sessionmaker)
    earlier = T0 - timedelta(days=1)
    event = _stored_created_event(
        pg_sessionmaker, remote={"id": 4321, "initial_transaction": 777}, processed_at=earlier
    )
    _handle(pg_sessionmaker, pid)
    assert _subscription(pg_sessionmaker, sid).paymob_subscription_id is None
    assert _event(pg_sessionmaker, event).processed_at == earlier


def test_a_subscription_that_is_already_linked_keeps_its_id(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student, sid, pid = _pending(pg_sessionmaker)
    with pg_sessionmaker.begin() as session:
        sub = session.get(Subscription, sid)
        assert sub is not None
        sub.paymob_subscription_id = 1111
    event = _stored_created_event(pg_sessionmaker, remote={"id": 4321, "initial_transaction": 777})
    _handle(pg_sessionmaker, pid)
    assert _subscription(pg_sessionmaker, sid).paymob_subscription_id == 1111
    assert _event(pg_sessionmaker, event).processed_at is None


# -- UD-3: a paid checkout that lost to another plan becomes credits ---------------------


def test_a_superseded_checkout_paid_while_another_is_live_becomes_credits(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _set_rate(pg_sessionmaker)
    student, sid, pid, live = _superseded(pg_sessionmaker)
    with capture_logs() as logs:
        _handle(pg_sessionmaker, pid)

    assert _events_named(logs, "subscription_first_paid_for_superseded_checkout")
    sub = _subscription(pg_sessionmaker, sid)
    assert sub.status is SubscriptionStatus.expired  # never a second live row
    assert _subscription(pg_sessionmaker, live).status is SubscriptionStatus.active
    assert _periods(pg_sessionmaker, sid) == []
    [grant] = grants_of(pg_sessionmaker, student)
    assert grant.kind is GrantKind.credit_pack
    assert (grant.units, grant.visible, grant.payment_id) == (100, True, pid)
    assert grant.owner_user_id == student
    assert grant.effective_at == PAID_AT
    assert grant.expires_at == add_months(PAID_AT, CREDIT_EXPIRY_MONTHS)
    assert _payment(pg_sessionmaker, pid).grant_units == 100
    assert _payment(pg_sessionmaker, pid).status is PaymentStatus.paid


def test_the_payer_is_told_the_payment_became_credits(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _set_rate(pg_sessionmaker)
    student, _, pid, _ = _superseded(pg_sessionmaker)
    _handle(pg_sessionmaker, pid)
    [row] = _outbox(pg_sessionmaker, student)
    assert row.template == "subscription_notice"
    assert row.context["notice"] == "credited"
    assert row.context["effective_at"] == "2026-11-10T09:07:00Z"


def test_the_converted_handler_replayed_changes_nothing(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _set_rate(pg_sessionmaker)
    student, sid, pid, live = _superseded(pg_sessionmaker)
    _handle(pg_sessionmaker, pid)
    with pg_sessionmaker.begin() as session:  # the other plan lapses, then the handler replays
        other = session.get(Subscription, live)
        assert other is not None
        other.status = SubscriptionStatus.expired
    _handle(pg_sessionmaker, pid)
    assert _subscription(pg_sessionmaker, sid).status is SubscriptionStatus.expired
    assert len(grants_of(pg_sessionmaker, student)) == 1
    assert len(_outbox(pg_sessionmaker, student)) == 1


def test_a_pending_checkout_paid_while_a_manual_plan_is_live_is_expired_not_stranded(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """A paid pending row can never be replaced by a checkout, so it must leave the live set."""
    _set_rate(pg_sessionmaker)
    student, sid, pid = _pending(pg_sessionmaker)
    seed_subscription(
        pg_sessionmaker,
        user_id=student,
        tier_id=seed_tier(pg_sessionmaker),
        payer_id=None,
        is_manually_activated=True,
    )
    _handle(pg_sessionmaker, pid)
    assert _subscription(pg_sessionmaker, sid).status is SubscriptionStatus.expired
    assert _periods(pg_sessionmaker, sid) == []
    [grant] = grants_of(pg_sessionmaker, student)
    assert grant.kind is GrantKind.credit_pack


def test_the_extra_paymob_subscription_is_left_for_the_sweeps_to_cancel(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """DV-27: linked, ended, not yet cancelled at Paymob. The webhook path never calls Paymob."""
    _set_rate(pg_sessionmaker)
    _, sid, pid, _ = _superseded(pg_sessionmaker)
    event = _stored_created_event(pg_sessionmaker, remote={"id": 4321, "initial_transaction": 777})
    _handle(pg_sessionmaker, pid)
    sub = _subscription(pg_sessionmaker, sid)
    assert sub.status is SubscriptionStatus.expired
    assert sub.paymob_subscription_id == 4321
    assert sub.paymob_cancelled_at is None
    assert _event(pg_sessionmaker, event).processed_at == PAID_AT


def test_the_unique_live_index_is_never_hit_by_a_superseded_payment(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _set_rate(pg_sessionmaker)
    student, sid, pid, live = _superseded(pg_sessionmaker)
    _handle(pg_sessionmaker, pid)  # activating would violate uq_subscriptions_one_live_per_user
    with pg_sessionmaker() as session:
        live_rows = session.scalars(
            sa.select(Subscription.id).where(
                Subscription.user_id == student,
                Subscription.status.in_(subscription_repo.LIVE_SUBSCRIPTION_STATUSES),
            )
        ).all()
    assert live_rows == [live]


def test_a_superseded_payment_with_no_credit_rate_keeps_the_money_visible_and_alerts(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student, sid, pid, _ = _superseded(pg_sessionmaker)  # no rate row set
    with capture_logs() as logs:
        _handle(pg_sessionmaker, pid)
    [entry] = _events_named(logs, "subscription_first_paid_for_superseded_checkout")
    assert entry["alert"] is True
    assert entry["converted"] is False
    assert entry["reason"] == "no_rate"
    assert _payment(pg_sessionmaker, pid).status is PaymentStatus.paid
    assert _payment(pg_sessionmaker, pid).grant_units is None
    assert _subscription(pg_sessionmaker, sid).status is SubscriptionStatus.expired
    assert grants_of(pg_sessionmaker, student) == []
    assert _outbox(pg_sessionmaker, student) == []


def test_the_callback_for_a_superseded_checkout_converts_it_through_phase_02(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _set_rate(pg_sessionmaker)
    client = FakePaymobClient()
    student, sid, pid, order = _checkout(pg_sessionmaker, client)
    with pg_sessionmaker.begin() as session:  # a second checkout replaced it and went live
        sub = session.get(Subscription, sid)
        assert sub is not None
        sub.status = SubscriptionStatus.expired
    seed_subscription(
        pg_sessionmaker, user_id=student, tier_id=seed_tier(pg_sessionmaker), payer_id=student
    )
    _callback(pg_sessionmaker, client, _obj_for(pid, order))
    assert _payment(pg_sessionmaker, pid).status is PaymentStatus.paid
    assert _subscription(pg_sessionmaker, sid).status is SubscriptionStatus.expired
    [grant] = grants_of(pg_sessionmaker, student)
    assert (grant.kind, grant.units) == (GrantKind.credit_pack, 100)


# -- T5-I1: only an unpaid pending replacement is expired, never a plan in force -----------


def _pending_replacement(
    sm: sessionmaker[Session],
    student: uuid.UUID,
    *,
    first_payment: PaymentStatus | None = PaymentStatus.created,
) -> uuid.UUID:
    """A same-payer pending checkout, with a first payment in ``first_payment`` (or none)."""
    sid = seed_subscription(
        sm,
        user_id=student,
        tier_id=seed_tier(sm),
        payer_id=student,
        status=SubscriptionStatus.pending_first_payment,
        period_start=None,
        period_end=None,
    )
    if first_payment is not None:
        seed_first_payment(
            sm,
            subscription_id=sid,
            status=first_payment,
            paymob_txn_id=None,
            paid_at=PAID_AT if first_payment is PaymentStatus.paid else None,
        )
    return sid


@pytest.mark.parametrize(
    "replacement_payment",
    [None, PaymentStatus.created, PaymentStatus.pending, PaymentStatus.failed],
    ids=["no-payment", "created", "pending", "declined"],
)
def test_an_old_checkout_paid_beside_an_unpaid_replacement_activates_and_expires_it(
    pg_sessionmaker: sessionmaker[Session], replacement_payment: PaymentStatus | None
) -> None:
    student, sid, pid = _pending(pg_sessionmaker, status=SubscriptionStatus.expired)
    replacement = _pending_replacement(pg_sessionmaker, student, first_payment=replacement_payment)
    _handle(pg_sessionmaker, pid)

    assert _subscription(pg_sessionmaker, sid).status is SubscriptionStatus.active
    assert _subscription(pg_sessionmaker, replacement).status is SubscriptionStatus.expired
    assert _subscription(pg_sessionmaker, replacement).version == 2
    [grant] = grants_of(pg_sessionmaker, student)
    assert grant.kind is GrantKind.period_allowance
    assert _outbox(pg_sessionmaker, student) == []


def test_a_replacement_with_money_behind_it_is_a_plan_so_the_old_payment_becomes_credits(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _set_rate(pg_sessionmaker)
    student, sid, pid = _pending(pg_sessionmaker, status=SubscriptionStatus.expired)
    replacement = _pending_replacement(pg_sessionmaker, student, first_payment=PaymentStatus.paid)
    _handle(pg_sessionmaker, pid)
    assert _subscription(pg_sessionmaker, sid).status is SubscriptionStatus.expired
    assert _subscription(pg_sessionmaker, replacement).status is (
        SubscriptionStatus.pending_first_payment
    )
    [grant] = grants_of(pg_sessionmaker, student)
    assert grant.kind is GrantKind.credit_pack


def test_a_plan_in_force_is_never_expired_to_make_room(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _set_rate(pg_sessionmaker)
    # A manual plan (no payer) is outside the unique index: a pending checkout can sit beside it.
    student, sid, pid, live = _superseded(pg_sessionmaker, other_payer_is_student=False)
    replacement = _pending_replacement(
        pg_sessionmaker, student, first_payment=PaymentStatus.created
    )
    _handle(pg_sessionmaker, pid)
    assert _subscription(pg_sessionmaker, live).status is SubscriptionStatus.active
    assert _subscription(pg_sessionmaker, sid).status is SubscriptionStatus.expired
    assert _subscription(pg_sessionmaker, replacement).status is (
        SubscriptionStatus.pending_first_payment
    )
    assert [g.kind for g in grants_of(pg_sessionmaker, student)] == [GrantKind.credit_pack]


def test_two_late_payments_of_one_account_settle_to_one_plan_without_a_deadlock(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """A and B are both paid at once: one activates, the other becomes credits, nobody hangs."""
    _set_rate(pg_sessionmaker)
    for round_number in range(3):
        student = seed_user(pg_sessionmaker, Role.student)
        tier = seed_tier(pg_sessionmaker)
        sids: list[uuid.UUID] = []
        pids: list[uuid.UUID] = []
        for index, status in enumerate(
            (SubscriptionStatus.expired, SubscriptionStatus.pending_first_payment)
        ):
            sid = seed_subscription(
                pg_sessionmaker,
                user_id=student,
                tier_id=tier,
                payer_id=student,
                status=status,
                period_start=None,
                period_end=None,
            )
            sids.append(sid)
            pids.append(
                seed_first_payment(
                    pg_sessionmaker,
                    subscription_id=sid,
                    paymob_txn_id=2_000 + round_number * 10 + index,
                    paid_at=PAID_AT,
                )
            )
        barrier = threading.Barrier(2)
        errors: list[BaseException] = []

        def run(
            pid: uuid.UUID,
            barrier: threading.Barrier = barrier,
            errors: list[BaseException] = errors,
        ) -> None:
            try:
                barrier.wait(timeout=10)
                _handle(pg_sessionmaker, pid)
            except BaseException as exc:  # reported through the assertion below
                errors.append(exc)

        threads = [threading.Thread(target=run, args=(pid,)) for pid in pids]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
        assert not any(thread.is_alive() for thread in threads), "a handler hung (deadlock)"
        assert errors == []
        statuses = sorted(_subscription(pg_sessionmaker, sid).status.value for sid in sids)
        assert statuses == ["active", "expired"]
        kinds = sorted(g.kind.value for g in grants_of(pg_sessionmaker, student))
        assert kinds == [GrantKind.credit_pack.value, GrantKind.period_allowance.value]


def test_the_account_rows_are_locked_lowest_id_first_whichever_one_is_paid(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The deadlock guard, deterministically: the paid row has the HIGHER id.

    A holder keeps the lower-id row locked, so the handler blocks on it. If the handler had locked
    its own (higher) row first, as a naive ``get(..., with_for_update=True)`` does, that row would
    already be locked and the probe below could not take it.
    """
    student = seed_user(pg_sessionmaker, Role.student)
    tier = seed_tier(pg_sessionmaker)
    low, high = sorted(
        seed_subscription(
            pg_sessionmaker,
            user_id=student,
            tier_id=tier,
            payer_id=student,
            status=SubscriptionStatus.expired,
            period_start=None,
            period_end=None,
        )
        for _ in range(2)
    )
    with pg_sessionmaker.begin() as session:  # the lower id is the live, unpaid replacement
        session.execute(
            sa.update(Subscription)
            .where(Subscription.id == low)
            .values(status=SubscriptionStatus.pending_first_payment)
        )
    pid = seed_first_payment(
        pg_sessionmaker, subscription_id=high, paid_at=PAID_AT, paymob_txn_id=6_001
    )
    holder = pg_sessionmaker()
    holder.execute(sa.select(Subscription.id).where(Subscription.id == low).with_for_update())
    done = threading.Event()

    def run() -> None:
        _handle(pg_sessionmaker, pid)
        done.set()

    thread = threading.Thread(target=run)
    thread.start()
    try:
        assert not done.wait(timeout=1.5)  # blocked on the lower row
        probe = pg_sessionmaker()
        try:
            probe.execute(
                sa.select(Subscription.id)
                .where(Subscription.id == high)
                .with_for_update(nowait=True)
            )
        finally:
            probe.rollback()
            probe.close()
    finally:
        holder.rollback()
        holder.close()
        thread.join(timeout=30)
    assert done.is_set()
    assert _subscription(pg_sessionmaker, high).status is SubscriptionStatus.active


def test_a_unique_index_race_on_activation_falls_back_to_credits(
    pg_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """M-1: the live check read stale, a live row exists; the savepoint turns it into credits."""
    _set_rate(pg_sessionmaker)
    student, sid, pid, live = _superseded(pg_sessionmaker)
    monkeypatch.setattr(subscription_repo, "_live_others", lambda session, subscription: [])
    _handle(pg_sessionmaker, pid)  # no IntegrityError, so the webhook would answer 200
    assert _subscription(pg_sessionmaker, sid).status is SubscriptionStatus.expired
    assert _subscription(pg_sessionmaker, live).status is SubscriptionStatus.active
    assert _periods(pg_sessionmaker, sid) == []
    [grant] = grants_of(pg_sessionmaker, student)
    assert grant.kind is GrantKind.credit_pack


# -- the per-transaction advisory lock (T5-I2) -----------------------------------------------


def test_the_handler_waits_for_the_advisory_lock_on_the_paymob_transaction_id(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student, sid, pid = _pending(pg_sessionmaker, txn_id=4_242)
    holder = pg_sessionmaker()
    holder.execute(
        sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": "paymob_txn:4242"},
    )
    done = threading.Event()

    def run() -> None:
        _handle(pg_sessionmaker, pid)
        done.set()

    thread = threading.Thread(target=run)
    thread.start()
    try:
        assert not done.wait(timeout=1.5), "the handler ran without taking the transaction lock"
    finally:
        holder.rollback()
        holder.close()
    thread.join(timeout=30)
    assert done.is_set()
    assert _subscription(pg_sessionmaker, sid).status is SubscriptionStatus.active


# -- the webhook answers 200 for a paid, superseded checkout -------------------------------

WEBHOOK_URL = "/api/webhooks/paymob/transaction"


@pytest.fixture
def app(pg_sessionmaker: sessionmaker[Session]) -> Iterator[FastAPI]:
    settings = Settings().model_copy(update={"paymob": PAYMOB_SETTINGS})
    application = create_app()
    application.dependency_overrides[get_settings] = lambda: settings
    application.dependency_overrides[get_billing_sessionmaker] = lambda: pg_sessionmaker
    application.dependency_overrides[get_paymob_client] = lambda: FakePaymobClient()
    yield application
    application.dependency_overrides.clear()


def _post_callback(http: TestClient, obj: dict[str, Any]) -> Any:
    return http.post(
        WEBHOOK_URL, params={"hmac": sign_transaction(obj)}, json=transaction_callback(obj)
    )


def test_a_restarted_checkout_whose_first_one_is_paid_late_activates_and_expires_the_unpaid_one(
    app: FastAPI, pg_sessionmaker: sessionmaker[Session]
) -> None:
    """T5-I1: A is replaced by the same payer's B, then A is paid while B is still unpaid.

    No plan is in force, so the payer gets the plan they paid for: A activates and the unpaid B
    expires in the same transaction (no credits, and the unique live index is never hit). B paid
    later meets a plan in force (A), so UD-3 turns it into credits.
    """
    _set_rate(pg_sessionmaker)
    sm = pg_sessionmaker
    client = FakePaymobClient()
    student, sid_a, pid_a, order_a = _checkout(sm, client)
    tier = _subscription(sm, sid_a).plan_tier_id
    client.intention_response = {**INTENTION_RESPONSE, "intention_order_id": order_a + 1}
    _, sid_b, pid_b, order_b = _checkout(sm, client, student=student, tier=tier)
    assert _subscription(sm, sid_a).status is SubscriptionStatus.expired  # replaced by B
    assert _subscription(sm, sid_b).status is SubscriptionStatus.pending_first_payment
    http = TestClient(app, raise_server_exceptions=True)

    obj_a = _obj_for(pid_a, order_a, txn_id=801)
    response = _post_callback(http, obj_a)

    assert (response.status_code, response.json()) == (200, {"status": "ok"})
    assert _payment(sm, pid_a).status is PaymentStatus.paid
    assert _subscription(sm, sid_a).status is SubscriptionStatus.active
    assert _subscription(sm, sid_b).status is SubscriptionStatus.expired
    assert len(_periods(sm, sid_a)) == 1
    [allowance] = grants_of(sm, student)
    assert allowance.kind is GrantKind.period_allowance
    assert _payment(sm, pid_a).grant_units is None
    assert _outbox(sm, student) == []

    assert _post_callback(http, obj_a).status_code == 200  # Paymob retries: nothing changes
    assert len(grants_of(sm, student)) == 1

    assert _post_callback(http, _obj_for(pid_b, order_b, txn_id=802)).status_code == 200
    assert _subscription(sm, sid_a).status is SubscriptionStatus.active
    assert _subscription(sm, sid_b).status is SubscriptionStatus.expired
    kinds = sorted(grant.kind.value for grant in grants_of(sm, student))
    assert kinds == [GrantKind.credit_pack.value, GrantKind.period_allowance.value]
    [notice] = _outbox(sm, student)
    assert notice.context["notice"] == "credited"


def test_the_late_paid_checkout_with_the_replacement_already_live_answers_200(
    app: FastAPI, pg_sessionmaker: sessionmaker[Session]
) -> None:
    _set_rate(pg_sessionmaker)
    sm = pg_sessionmaker
    client = FakePaymobClient()
    student, sid_a, pid_a, order_a = _checkout(sm, client)
    tier = _subscription(sm, sid_a).plan_tier_id
    client.intention_response = {**INTENTION_RESPONSE, "intention_order_id": order_a + 1}
    _, sid_b, pid_b, order_b = _checkout(sm, client, student=student, tier=tier)
    http = TestClient(app, raise_server_exceptions=True)
    assert _post_callback(http, _obj_for(pid_b, order_b, txn_id=802)).status_code == 200
    assert _subscription(sm, sid_b).status is SubscriptionStatus.active

    assert _post_callback(http, _obj_for(pid_a, order_a, txn_id=801)).status_code == 200

    assert _subscription(sm, sid_a).status is SubscriptionStatus.expired
    assert _subscription(sm, sid_b).status is SubscriptionStatus.active
    assert sorted(grant.kind.value for grant in grants_of(sm, student)) == [
        GrantKind.credit_pack.value,
        GrantKind.period_allowance.value,
    ]


# -- the public helper Phase 06 reuses ----------------------------------------------------


def _convert(
    sm: sessionmaker[Session], pid: uuid.UUID, sid: uuid.UUID, *, now: datetime = PAID_AT
) -> UsageGrant:
    with sm.begin() as session:
        payment = session.get(Payment, pid)
        sub = session.get(Subscription, sid)
        assert payment is not None
        assert sub is not None
        grant = convert_payment_to_credits(session, payment, subscription=sub, now=now)
        session.expunge(grant)
        return grant


def test_convert_payment_to_credits_issues_visible_twelve_month_credits(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _set_rate(pg_sessionmaker)
    student, sid, pid = _pending(pg_sessionmaker, amount_minor=25_000)
    grant = _convert(pg_sessionmaker, pid, sid)
    assert grant.units == 250
    assert (grant.kind, grant.visible, grant.owner_user_id) == (
        GrantKind.credit_pack,
        True,
        student,
    )
    assert grant.expires_at == add_months(PAID_AT, CREDIT_EXPIRY_MONTHS)
    assert _payment(pg_sessionmaker, pid).grant_units == 250


def test_convert_payment_to_credits_is_idempotent_and_keeps_the_first_rate(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _set_rate(pg_sessionmaker, "EGP", "0.01")
    student, sid, pid = _pending(pg_sessionmaker)
    first = _convert(pg_sessionmaker, pid, sid)
    with pg_sessionmaker.begin() as session:  # the admin's rate changes before the replay
        session.execute(sa.update(CreditConversionRate).values(units_per_minor=Decimal("9.99")))
    second = _convert(pg_sessionmaker, pid, sid)
    assert second.id == first.id
    assert len(grants_of(pg_sessionmaker, student)) == 1
    assert _payment(pg_sessionmaker, pid).grant_units == 100
    assert len(_outbox(pg_sessionmaker, student)) == 1


def test_convert_payment_to_credits_repays_debt_first(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _set_rate(pg_sessionmaker)
    student, sid, pid = _pending(pg_sessionmaker)
    seed_debt(pg_sessionmaker, student, 30)
    grant = _convert(pg_sessionmaker, pid, sid)
    assert _remaining(pg_sessionmaker, grant.id) == 70


def test_convert_payment_to_credits_needs_a_paid_payment(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _set_rate(pg_sessionmaker)
    _, sid, pid = _pending(pg_sessionmaker)
    with pg_sessionmaker.begin() as session:
        payment = session.get(Payment, pid)
        assert payment is not None
        payment.status = PaymentStatus.pending
        payment.paid_at = None
    with pytest.raises(ValueError, match="paid"):
        _convert(pg_sessionmaker, pid, sid)
    assert grants_of(pg_sessionmaker, _subscription(pg_sessionmaker, sid).user_id) == []


@pytest.mark.parametrize("amount_minor", [1, 99])
def test_an_amount_too_small_for_one_unit_is_refused_not_granted_as_zero(
    pg_sessionmaker: sessionmaker[Session], amount_minor: int
) -> None:
    _set_rate(pg_sessionmaker, "EGP", "0.01")
    _, sid, pid = _pending(pg_sessionmaker, amount_minor=amount_minor)
    with pytest.raises(NoCreditRate) as refused:
        _convert(pg_sessionmaker, pid, sid)
    assert refused.value.reason == "below_one_unit"


def test_credit_units_follow_the_admin_set_rate_for_the_currency(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """UD-12: units = floor(amount x the rate row), per currency, exact decimal arithmetic."""
    _set_rate(pg_sessionmaker, "EGP", "0.01")
    _set_rate(pg_sessionmaker, "USD", "5")
    with pg_sessionmaker() as session:
        assert credit_units_for_amount(session, amount_minor=10_000, currency="EGP") == 100
        assert credit_units_for_amount(session, amount_minor=10_099, currency="EGP") == 100
        assert credit_units_for_amount(session, amount_minor=10_000, currency="USD") == 50_000


def test_a_changed_rate_changes_the_credits_granted(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _set_rate(pg_sessionmaker, "EGP", "0.01")
    student, sid, pid = _pending(pg_sessionmaker, amount_minor=10_000)
    first = _convert(pg_sessionmaker, pid, sid)
    assert first.units == 100

    _set_rate(pg_sessionmaker, "EGP", "0.025")  # the admin raises it (version 2)
    other, other_sid, other_pid = _pending(pg_sessionmaker, amount_minor=10_000, txn_id=778)
    second = _convert(pg_sessionmaker, other_pid, other_sid)
    assert second.units == 250
    assert _payment(pg_sessionmaker, other_pid).grant_units == 250
    assert _payment(pg_sessionmaker, pid).grant_units == 100  # the first stays as converted


def test_a_missing_rate_refuses_and_a_pack_price_is_not_a_rate(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """No row for the currency: nothing is converted, whatever the credit packs would say."""
    seed_pack(pg_sessionmaker, units=100, price_minor=10_000)
    _set_rate(pg_sessionmaker, "USD", "5")  # another currency's rate is not this one's
    student, sid, pid = _pending(pg_sessionmaker)
    with pg_sessionmaker() as session:
        assert credit_units_for_amount(session, amount_minor=10_000, currency="EGP") is None
    with pytest.raises(NoCreditRate) as refused:
        _convert(pg_sessionmaker, pid, sid)
    assert refused.value.reason == "no_rate"
    assert grants_of(pg_sessionmaker, student) == []
    assert _payment(pg_sessionmaker, pid).grant_units is None


def test_the_rate_is_read_inside_the_callers_transaction(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """An uncommitted rate change in the caller's own transaction is the rate used."""
    _set_rate(pg_sessionmaker, "EGP", "0.01")
    with pg_sessionmaker.begin() as session:
        session.execute(
            sa.update(CreditConversionRate)
            .where(CreditConversionRate.currency == "EGP")
            .values(units_per_minor=Decimal("0.5"))
        )
        assert credit_units_for_amount(session, amount_minor=10_000, currency="EGP") == 5_000


# -- credit validity: the admin-set billing_settings.credit_validity_months ------------------


def test_an_edited_validity_changes_the_expiry_of_new_grants_only(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _set_rate(pg_sessionmaker)
    _set_validity(pg_sessionmaker, 12)
    _, sid, pid = _pending(pg_sessionmaker)
    first = _convert(pg_sessionmaker, pid, sid)
    assert first.expires_at == add_months(PAID_AT, 12)

    _set_validity(pg_sessionmaker, 6)  # the admin shortens it (version 2)
    _, other_sid, other_pid = _pending(pg_sessionmaker, txn_id=778)
    second = _convert(pg_sessionmaker, other_pid, other_sid)
    assert second.expires_at == add_months(PAID_AT, 6)
    [stored_first] = [
        g for g in grants_of(pg_sessionmaker, first.owner_user_id) if g.id == first.id
    ]
    assert stored_first.expires_at == add_months(PAID_AT, 12)  # untouched


def test_a_replay_keeps_the_expiry_already_stamped_on_the_grant(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _set_rate(pg_sessionmaker)
    _, sid, pid = _pending(pg_sessionmaker)
    first = _convert(pg_sessionmaker, pid, sid)
    _set_validity(pg_sessionmaker, 3)
    second = _convert(pg_sessionmaker, pid, sid)
    assert second.id == first.id
    assert second.expires_at == first.expires_at == add_months(PAID_AT, 12)
    _delete_settings(pg_sessionmaker)  # a replay needs no setting at all
    assert _convert(pg_sessionmaker, pid, sid).id == first.id


def test_a_missing_settings_row_refuses_and_grants_nothing(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _set_rate(pg_sessionmaker)
    _delete_settings(pg_sessionmaker)
    student, sid, pid = _pending(pg_sessionmaker)
    with pytest.raises(NoCreditRate, match="validity") as refused:
        _convert(pg_sessionmaker, pid, sid)
    assert refused.value.reason == "no_validity_setting"
    assert grants_of(pg_sessionmaker, student) == []
    assert _payment(pg_sessionmaker, pid).grant_units is None
    assert _outbox(pg_sessionmaker, student) == []


def test_a_superseded_payment_with_no_settings_row_alerts_for_manual_handling(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _set_rate(pg_sessionmaker)
    _delete_settings(pg_sessionmaker)
    student, sid, pid, _ = _superseded(pg_sessionmaker)
    with capture_logs() as logs:
        _handle(pg_sessionmaker, pid)
    [entry] = _events_named(logs, "subscription_first_paid_for_superseded_checkout")
    assert (entry["alert"], entry["converted"]) == (True, False)
    assert entry["reason"] == "no_validity_setting"
    assert _payment(pg_sessionmaker, pid).status is PaymentStatus.paid
    assert grants_of(pg_sessionmaker, student) == []


# -- UD-12 review minors ------------------------------------------------------------------


def test_the_credit_arithmetic_is_exact_decimal_not_float(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """M-2: ``int(100 * float("0.29"))`` is 28; the exact floor is 29."""
    _set_rate(pg_sessionmaker, "EGP", "0.29")
    with pg_sessionmaker() as session:
        assert credit_units_for_amount(session, amount_minor=100, currency="EGP") == 29
        assert credit_units_for_amount(session, amount_minor=1_000, currency="EGP") == 290


def test_units_beyond_bigint_are_no_rate_not_a_database_error(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """M-1: the largest rate the column holds on 10,000,000 minor units overflows BIGINT."""
    _set_rate(pg_sessionmaker, "EGP", "999999999999.999999")
    student, sid, pid = _pending(pg_sessionmaker, amount_minor=10_000_000)
    with pg_sessionmaker() as session:
        assert credit_units_for_amount(session, amount_minor=10_000_000, currency="EGP") is None
    with pytest.raises(NoCreditRate) as refused:  # not a sqlalchemy DataError
        _convert(pg_sessionmaker, pid, sid)
    assert refused.value.reason == "overflow"
    assert grants_of(pg_sessionmaker, student) == []
    assert _payment(pg_sessionmaker, pid).grant_units is None


def test_an_overflowing_conversion_alerts_with_its_reason_and_keeps_the_payment_paid(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _set_rate(pg_sessionmaker, "EGP", "999999999999.999999")
    student, sid, pid, _ = _superseded(pg_sessionmaker)
    with pg_sessionmaker.begin() as session:
        payment = session.get(Payment, pid)
        assert payment is not None
        payment.amount_minor = 10_000_000
    with capture_logs() as logs:
        _handle(pg_sessionmaker, pid)  # no DataError: the callback transaction survives
    [entry] = _events_named(logs, "subscription_first_paid_for_superseded_checkout")
    assert (entry["alert"], entry["converted"], entry["reason"]) == (True, False, "overflow")
    assert _payment(pg_sessionmaker, pid).status is PaymentStatus.paid
    assert grants_of(pg_sessionmaker, student) == []


def test_a_replay_uses_the_stored_grants_units_even_when_the_payment_lost_its_stamp(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """M-3: a grant exists, ``grant_units`` is empty and the rate moved: the grant's units win."""
    _set_rate(pg_sessionmaker, "EGP", "0.01")
    student, sid, pid = _pending(pg_sessionmaker)
    first = _convert(pg_sessionmaker, pid, sid)
    with pg_sessionmaker.begin() as session:
        payment = session.get(Payment, pid)
        assert payment is not None
        payment.grant_units = None
    _set_rate(pg_sessionmaker, "EGP", "0.05")
    replay = _convert(pg_sessionmaker, pid, sid)
    assert replay.id == first.id
    assert _payment(pg_sessionmaker, pid).grant_units == 100
    with pg_sessionmaker.begin() as session:  # and with the rate row gone, the replay still works
        payment = session.get(Payment, pid)
        assert payment is not None
        payment.grant_units = None
        session.execute(sa.delete(CreditConversionRate))
    assert _convert(pg_sessionmaker, pid, sid).id == first.id
    assert _payment(pg_sessionmaker, pid).grant_units == 100
    assert len(grants_of(pg_sessionmaker, student)) == 1


# -- UD-5: seats over capacity move to leaving, before the grant ---------------------------


def _teacher_plan(
    sm: sessionmaker[Session],
    *,
    included_seats: int = 2,
    extra_seats: int = 0,
    seats: int = 3,
    seat_status: TeacherMemberStatus = TeacherMemberStatus.active,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, list[uuid.UUID]]:
    """A teacher with ``seats`` held seats (oldest first) and a paid, unactivated first payment."""
    teacher = seed_user(sm, Role.teacher)
    tier = seed_tier(
        sm,
        audience=PlanAudience.teacher,
        included_seats=included_seats,
        allowance_units=500,
        extra_seat_price_minor=500 if extra_seats else 0,
    )
    sid = seed_subscription(
        sm,
        user_id=teacher,
        tier_id=tier,
        payer_id=teacher,
        status=SubscriptionStatus.pending_first_payment,
        period_start=None,
        period_end=None,
        extra_seats=extra_seats,
    )
    pid = seed_first_payment(sm, subscription_id=sid, paid_at=PAID_AT, paymob_txn_id=900)
    members = [
        seed_seat(
            sm,
            teacher_id=teacher,
            student_id=seed_user(sm, Role.student),
            status=seat_status,
            created_at=T0 - timedelta(days=10 - index),
        )
        for index in range(seats)
    ]
    return teacher, sid, pid, members


def _seat_status(sm: sessionmaker[Session], member_id: uuid.UUID) -> TeacherMember:
    with sm() as session:
        row = session.get(TeacherMember, member_id)
        assert row is not None
        return row


def test_a_teacher_over_capacity_at_activation_loses_the_newest_seat_to_leaving(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    teacher, sid, pid, members = _teacher_plan(pg_sessionmaker, included_seats=2, seats=3)
    _handle(pg_sessionmaker, pid)

    oldest, middle, newest = (_seat_status(pg_sessionmaker, m) for m in members)
    assert (oldest.status, middle.status) == (TeacherMemberStatus.active,) * 2
    assert newest.status is TeacherMemberStatus.leaving
    assert newest.leaves_at == month_end(PAID_AT)
    assert _subscription(pg_sessionmaker, sid).status is SubscriptionStatus.active
    [grant] = grants_of(pg_sessionmaker, teacher)  # the plan's own allowance
    assert grant.kind is GrantKind.period_allowance


def test_extra_seats_raise_the_capacity_that_shedding_keeps(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _, _, pid, members = _teacher_plan(pg_sessionmaker, included_seats=1, extra_seats=2, seats=3)
    _handle(pg_sessionmaker, pid)
    assert {_seat_status(pg_sessionmaker, m).status for m in members} == {
        TeacherMemberStatus.active
    }


def test_seats_already_leaving_are_not_counted_or_touched(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _, _, pid, members = _teacher_plan(
        pg_sessionmaker, included_seats=2, seats=3, seat_status=TeacherMemberStatus.leaving
    )
    _handle(pg_sessionmaker, pid)
    rows = [_seat_status(pg_sessionmaker, m) for m in members]
    assert {row.status for row in rows} == {TeacherMemberStatus.leaving}
    assert {row.leaves_at for row in rows} == {T0 + timedelta(days=30)}  # the seeded date


def test_a_leaving_seat_does_not_push_an_active_seat_out(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """Two active seats fit a two-seat plan however many seats are already on their way out."""
    teacher, _, pid, members = _teacher_plan(pg_sessionmaker, included_seats=2, seats=2)
    leaving = seed_seat(
        pg_sessionmaker,
        teacher_id=teacher,
        student_id=seed_user(pg_sessionmaker, Role.student),
        status=TeacherMemberStatus.leaving,
    )
    _handle(pg_sessionmaker, pid)
    assert {_seat_status(pg_sessionmaker, m).status for m in members} == {
        TeacherMemberStatus.active
    }
    assert _seat_status(pg_sessionmaker, leaving).status is TeacherMemberStatus.leaving


def test_a_superseded_teacher_checkout_sheds_nothing(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _set_rate(pg_sessionmaker)
    teacher, sid, pid, members = _teacher_plan(pg_sessionmaker, included_seats=2, seats=3)
    with pg_sessionmaker.begin() as session:
        sub = session.get(Subscription, sid)
        assert sub is not None
        sub.status = SubscriptionStatus.expired
    seed_subscription(
        pg_sessionmaker,
        user_id=teacher,
        tier_id=seed_tier(pg_sessionmaker, audience=PlanAudience.teacher, included_seats=5),
        payer_id=teacher,
    )
    _handle(pg_sessionmaker, pid)
    assert {_seat_status(pg_sessionmaker, m).status for m in members} == {
        TeacherMemberStatus.active
    }


def test_the_activation_time_is_the_payment_time_not_the_wall_clock(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student, sid, pid = _pending(pg_sessionmaker)
    paid = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    with pg_sessionmaker.begin() as session:
        payment = session.get(Payment, pid)
        assert payment is not None
        payment.paid_at = paid
    _handle(pg_sessionmaker, pid)
    [grant] = grants_of(pg_sessionmaker, student)
    assert grant.effective_at == paid
    assert _subscription(pg_sessionmaker, sid).current_period_start == paid


# -- review minors -----------------------------------------------------------------------


def test_credits_go_to_the_beneficiary_and_the_notice_to_the_payer_who_is_a_parent(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """M-2: a parent paid for a child; the child owns the credits, the parent hears of it."""
    _set_rate(pg_sessionmaker)
    parent = seed_user(pg_sessionmaker, Role.parent)
    child = seed_user(pg_sessionmaker, Role.student)
    sid = seed_subscription(
        pg_sessionmaker,
        user_id=child,
        tier_id=seed_tier(pg_sessionmaker),
        payer_id=parent,
        status=SubscriptionStatus.expired,
        period_start=None,
        period_end=None,
    )
    seed_subscription(
        pg_sessionmaker, user_id=child, tier_id=seed_tier(pg_sessionmaker), payer_id=child
    )
    pid = seed_first_payment(pg_sessionmaker, subscription_id=sid, paid_at=PAID_AT, paymob_txn_id=5)
    _handle(pg_sessionmaker, pid)
    [grant] = grants_of(pg_sessionmaker, child)
    assert grant.kind is GrantKind.credit_pack
    assert grants_of(pg_sessionmaker, parent) == []
    assert len(_outbox(pg_sessionmaker, parent)) == 1
    assert _outbox(pg_sessionmaker, child) == []


def test_an_assistant_is_never_a_seat(pg_sessionmaker: sessionmaker[Session]) -> None:
    """M-3: assistants do not count toward capacity, so none is shed for being over it."""
    teacher, _, pid, members = _teacher_plan(pg_sessionmaker, included_seats=2, seats=2)
    assistant = add_assistant(
        pg_sessionmaker, teacher_id=teacher, assistant_id=seed_user(pg_sessionmaker, Role.student)
    )
    _handle(pg_sessionmaker, pid)
    assert {_seat_status(pg_sessionmaker, m).status for m in members} == {
        TeacherMemberStatus.active
    }
    assert _seat_status(pg_sessionmaker, assistant).status is TeacherMemberStatus.active


def test_shedding_a_seat_raises_an_alert(pg_sessionmaker: sessionmaker[Session]) -> None:
    """M-7: the backstop removes a student the teacher did not choose to remove: page someone."""
    _, _, pid, _ = _teacher_plan(pg_sessionmaker, included_seats=2, seats=3)
    with capture_logs() as logs:
        _handle(pg_sessionmaker, pid)
    [entry] = _events_named(logs, "seats_shed_after_plan_change")
    assert entry["alert"] is True
    assert entry["count"] == 1


def test_convert_refuses_a_credit_pack_payment(pg_sessionmaker: sessionmaker[Session]) -> None:
    """M-4: a pack's ``grant_units`` is its checkout snapshot; converting it would pay twice."""
    _set_rate(pg_sessionmaker)
    payer = seed_user(pg_sessionmaker, Role.student)
    pack = seed_pack(pg_sessionmaker)
    pid = seed_payment(
        pg_sessionmaker,
        payer=payer,
        beneficiary=payer,
        pack_id=pack,
        status=PaymentStatus.paid,
        paid_at=PAID_AT,
    )
    sid = seed_subscription(
        pg_sessionmaker, user_id=payer, tier_id=seed_tier(pg_sessionmaker), payer_id=payer
    )
    with pytest.raises(ValueError, match="credit pack"):
        _convert(pg_sessionmaker, pid, sid)
    assert grants_of(pg_sessionmaker, payer) == []


def test_convert_refuses_a_payment_that_already_paid_for_a_period(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _set_rate(pg_sessionmaker)
    student, sid, pid = _pending(pg_sessionmaker)
    _handle(pg_sessionmaker, pid)  # activated: the payment bought a period
    with pytest.raises(ValueError, match="period"):
        _convert(pg_sessionmaker, pid, sid)
    assert [g.kind for g in grants_of(pg_sessionmaker, student)] == [GrantKind.period_allowance]


def test_convert_refuses_grant_units_that_no_conversion_issued(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _set_rate(pg_sessionmaker)
    student, sid, pid = _pending(pg_sessionmaker)
    with pg_sessionmaker.begin() as session:
        payment = session.get(Payment, pid)
        assert payment is not None
        payment.grant_units = 500  # a snapshot, but no credited grant exists
    with pytest.raises(ValueError, match="grant units"):
        _convert(pg_sessionmaker, pid, sid)
    assert grants_of(pg_sessionmaker, student) == []
