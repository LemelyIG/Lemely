"""A verified first payment activates the subscription, its period and its allowance (§5.1 step 4).

Real Postgres (a throwaway ``create_all`` database). The handler is driven directly for the
money rules and through Phase 02's callback and reconcile paths for the wiring. A first payment
that lands while another plan is live is turned into credits (UD-3, UD-10) by the one public
helper :func:`convert_payment_to_credits`, which Phase 06 reuses.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from structlog.testing import capture_logs

from lemely.db import billing_repo, subscription_repo
from lemely.db.billing_repo import CREDIT_EXPIRY_MONTHS, BillingService, add_months
from lemely.db.models.billing import (
    CreditPack,
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
from tests.team_db import emptied_after

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

    Credit packs set the conversion rate and ``paymob_events`` dedupe by transaction id, and
    neither hangs off ``users``, so they are cleared here too.
    """
    yield from emptied_after(_database)
    with _database.begin() as session:
        session.execute(sa.text("TRUNCATE credit_packs, paymob_events CASCADE"))


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
    seed_pack(pg_sessionmaker, units=100, price_minor=10_000)  # 1 unit per 100 minor
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
    seed_pack(pg_sessionmaker)
    student, _, pid, _ = _superseded(pg_sessionmaker)
    _handle(pg_sessionmaker, pid)
    [row] = _outbox(pg_sessionmaker, student)
    assert row.template == "subscription_notice"
    assert row.context["notice"] == "credited"
    assert row.context["effective_at"] == "2026-11-10T09:07:00Z"


def test_the_converted_handler_replayed_changes_nothing(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    seed_pack(pg_sessionmaker)
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
    seed_pack(pg_sessionmaker)
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
    seed_pack(pg_sessionmaker)
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
    seed_pack(pg_sessionmaker)
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
    student, sid, pid, _ = _superseded(pg_sessionmaker)  # no credit pack seeded
    with capture_logs() as logs:
        _handle(pg_sessionmaker, pid)
    [entry] = _events_named(logs, "subscription_first_paid_for_superseded_checkout")
    assert entry["alert"] is True
    assert entry["converted"] is False
    assert _payment(pg_sessionmaker, pid).status is PaymentStatus.paid
    assert _payment(pg_sessionmaker, pid).grant_units is None
    assert _subscription(pg_sessionmaker, sid).status is SubscriptionStatus.expired
    assert grants_of(pg_sessionmaker, student) == []
    assert _outbox(pg_sessionmaker, student) == []


def test_the_callback_for_a_superseded_checkout_converts_it_through_phase_02(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    seed_pack(pg_sessionmaker, units=100, price_minor=10_000)
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


def test_a_restarted_checkout_whose_first_one_is_paid_late_answers_200_and_becomes_credits(
    app: FastAPI, pg_sessionmaker: sessionmaker[Session]
) -> None:
    """Review I-2: A is replaced by the same payer's B, then A is paid while B is pending.

    Reactivating A would hit ``uq_subscriptions_one_live_per_user`` and 500 on every retry, so
    the payment becomes credits (UD-3), B is untouched, and B's own payment still activates it.
    """
    seed_pack(pg_sessionmaker, units=100, price_minor=10_000)
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
    assert _subscription(sm, sid_a).status is SubscriptionStatus.expired
    assert _subscription(sm, sid_b).status is SubscriptionStatus.pending_first_payment
    assert _periods(sm, sid_a) == []
    [credit] = grants_of(sm, student)
    assert (credit.kind, credit.units, credit.visible) == (GrantKind.credit_pack, 100, True)
    assert _payment(sm, pid_a).grant_units == 100
    [notice] = _outbox(sm, student)
    assert notice.context["notice"] == "credited"

    assert _post_callback(http, obj_a).status_code == 200  # Paymob retries: nothing changes
    assert len(grants_of(sm, student)) == 1

    assert _post_callback(http, _obj_for(pid_b, order_b, txn_id=802)).status_code == 200
    assert _subscription(sm, sid_b).status is SubscriptionStatus.active
    kinds = sorted(grant.kind.value for grant in grants_of(sm, student))
    assert kinds == [GrantKind.credit_pack.value, GrantKind.period_allowance.value]


def test_the_late_paid_checkout_with_the_replacement_already_live_answers_200(
    app: FastAPI, pg_sessionmaker: sessionmaker[Session]
) -> None:
    seed_pack(pg_sessionmaker)
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
    seed_pack(pg_sessionmaker, units=100, price_minor=10_000)
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
    seed_pack(pg_sessionmaker, units=100, price_minor=10_000)
    student, sid, pid = _pending(pg_sessionmaker)
    first = _convert(pg_sessionmaker, pid, sid)
    with pg_sessionmaker.begin() as session:  # the shop's rate changes before the replay
        session.execute(sa.update(CreditPack).values(units=999))
    second = _convert(pg_sessionmaker, pid, sid)
    assert second.id == first.id
    assert len(grants_of(pg_sessionmaker, student)) == 1
    assert _payment(pg_sessionmaker, pid).grant_units == 100
    assert len(_outbox(pg_sessionmaker, student)) == 1


def test_convert_payment_to_credits_repays_debt_first(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    seed_pack(pg_sessionmaker, units=100, price_minor=10_000)
    student, sid, pid = _pending(pg_sessionmaker)
    seed_debt(pg_sessionmaker, student, 30)
    grant = _convert(pg_sessionmaker, pid, sid)
    assert _remaining(pg_sessionmaker, grant.id) == 70


def test_convert_payment_to_credits_needs_a_paid_payment(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    seed_pack(pg_sessionmaker)
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
    seed_pack(pg_sessionmaker, units=1, price_minor=100)
    _, sid, pid = _pending(pg_sessionmaker, amount_minor=amount_minor)
    with pytest.raises(NoCreditRate):
        _convert(pg_sessionmaker, pid, sid)


def test_credit_rate_follows_what_the_same_money_buys_in_the_shop(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    seed_pack(pg_sessionmaker, units=100, price_minor=10_000)  # 0.010 units per minor
    seed_pack(pg_sessionmaker, units=1_200, price_minor=100_000)  # 0.012 units per minor
    seed_pack(pg_sessionmaker, units=99_999, price_minor=50_000, is_active=False)  # ignored
    with pg_sessionmaker() as session:
        # Below the cheapest pack: that pack's rate. Between the two: the small pack's.
        assert credit_units_for_amount(session, amount_minor=5_000, currency="EGP") == 50
        assert credit_units_for_amount(session, amount_minor=50_000, currency="EGP") == 500
        # Buys the big pack: the big pack's better rate. The result is floored.
        assert credit_units_for_amount(session, amount_minor=100_000, currency="EGP") == 1_200
        assert credit_units_for_amount(session, amount_minor=100_001, currency="EGP") == 1_200
        assert credit_units_for_amount(session, amount_minor=10_001, currency="EGP") == 100


def test_credit_rate_ignores_other_currencies_and_free_or_empty_packs(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    with pg_sessionmaker.begin() as session:
        for code, units, price, currency in (
            ("usd", 500, 10_000, "USD"),
            ("free", 100, 0, "EGP"),
            ("empty", 0, 10_000, "EGP"),
        ):
            session.add(
                CreditPack(code=code, name=code, units=units, price_minor=price, currency=currency)
            )
    with pg_sessionmaker() as session:
        assert credit_units_for_amount(session, amount_minor=10_000, currency="EGP") is None
        assert credit_units_for_amount(session, amount_minor=10_000, currency="USD") == 500


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
    seed_pack(pg_sessionmaker)
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
