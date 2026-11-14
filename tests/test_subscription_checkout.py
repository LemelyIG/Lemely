"""Subscription checkout: who may buy what, priced on the server (spec §5.1, §7).

Money safety (amount and line items come from ``plan_tiers`` only), IDOR (a payer buys only for
themselves or, as a linked parent, for a linked student), the one-live-subscription rule with the
R20b supersession of unpaid checkouts, the key-mode guard (audit I8), the phone guard (UD-11) and
the teacher seat guard (UD-5). Every refusal is proven to commit nothing, counted in a fresh
session, and to leave Paymob uncalled.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError, OperationalError

from lemely.core.subscription_rules import STALE_CHECKOUT_AFTER
from lemely.db.billing_repo import (
    INTENTION_EXPIRATION_SECONDS,
    CheckoutUnavailable,
    PhoneRequired,
    UnknownPayer,
)
from lemely.db.models.billing import (
    Payment,
    PaymentPurpose,
    PaymentStatus,
    PlanAudience,
    PlanTier,
    Subscription,
)
from lemely.db.models.enums import Role, SubscriptionStatus
from lemely.db.models.team import TeacherMemberStatus
from lemely.db.models.users import User
from lemely.db.subscription_repo import (
    _MODE_ALERT_EVERY,
    _MODE_ALERTED,
    AlreadySubscribed,
    InvalidExtraSeats,
    NotLinkedParent,
    PlanModeMismatch,
    PlanNotPurchasable,
    SeatsInsufficient,
    SubscriptionCheckout,
    SubscriptionService,
    _bump,
    _has_other_live,
    _line_items,
)
from lemely.io.paymob.client import PaymobError
from tests.subscription_fixtures import (
    T0,
    FakePaymobClient,
    link_parent,
    paymob_settings,
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

    from sqlalchemy.orm import Session, sessionmaker

    from lemely.runtime.config import PaymobSettings


@pytest.fixture(scope="module")
def _database() -> Iterator[sessionmaker[Session]]:
    with throwaway_database() as factory:
        yield factory


@pytest.fixture(autouse=True)
def _fresh_alert_memo() -> None:
    _MODE_ALERTED.clear()


@pytest.fixture
def pg_sessionmaker(_database: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    """The module's database, emptied after each test so row counts start from zero."""
    yield from emptied_after(_database)


def _service(
    session: Session, client: FakePaymobClient, settings: PaymobSettings | None = None
) -> SubscriptionService:
    return SubscriptionService(session, client, settings or paymob_settings())


def _checkout(
    sm: sessionmaker[Session],
    client: FakePaymobClient | None = None,
    *,
    settings: PaymobSettings | None = None,
    **kwargs: object,
) -> SubscriptionCheckout:
    """No ``sm.begin()``: Phase 02's create_intention_checkout commits inside the call."""
    client = client or FakePaymobClient()
    with sm() as session:
        result = _service(session, client, settings).create_subscription_checkout(
            now=T0,
            **kwargs,  # type: ignore[arg-type]
        )
        session.commit()
        return result


def _counts(sm: sessionmaker[Session]) -> tuple[int, int]:
    """Subscription and payment rows, read through a fresh session."""
    with sm() as session:
        return (
            session.scalar(sa.select(sa.func.count()).select_from(Subscription)) or 0,
            session.scalar(sa.select(sa.func.count()).select_from(Payment)) or 0,
        )


def _subs_of(sm: sessionmaker[Session], user: uuid.UUID) -> list[Subscription]:
    with sm() as session:
        return list(session.scalars(sa.select(Subscription).where(Subscription.user_id == user)))


def _payment_status(sm: sessionmaker[Session], subscription_id: uuid.UUID) -> PaymentStatus:
    with sm() as session:
        return session.scalars(
            sa.select(Payment.status).where(Payment.subscription_id == subscription_id)
        ).one()


def _status(sm: sessionmaker[Session], subscription_id: uuid.UUID) -> SubscriptionStatus:
    with sm() as session:
        sub = session.get(Subscription, subscription_id)
        assert sub is not None
        return sub.status


def _refused(
    sm: sessionmaker[Session],
    error: type[Exception],
    client: FakePaymobClient | None = None,
    *,
    settings: PaymobSettings | None = None,
    **kwargs: object,
) -> Exception:
    """Run a checkout that must be refused; it wrote nothing and never reached Paymob."""
    client = client or FakePaymobClient()
    before = _counts(sm)
    with pytest.raises(error) as excinfo:
        _checkout(sm, client, settings=settings, **kwargs)
    assert _counts(sm) == before, "a refusal must commit nothing"
    assert client.intentions == [], "a refusal must never call Paymob"
    return excinfo.value


# -- money -------------------------------------------------------------------


def test_student_buys_own_plan_priced_from_the_tier(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = seed_user(pg_sessionmaker, Role.student)
    tier = seed_tier(pg_sessionmaker, price_minor=9_900, paymob_plan_id=5001)
    client = FakePaymobClient()

    result = _checkout(pg_sessionmaker, client, payer_user_id=student, plan_tier_id=tier)

    with pg_sessionmaker() as session:
        sub = session.get(Subscription, result.subscription_id)
        payment = session.get(Payment, result.payment_id)
        assert sub is not None
        assert payment is not None
        assert sub.status is SubscriptionStatus.pending_first_payment
        assert (sub.user_id, sub.payer_user_id, sub.extra_seats) == (student, student, 0)
        assert payment.purpose is PaymentPurpose.subscription_first
        assert payment.amount_minor == 9_900
        assert payment.special_reference == str(payment.id)
        assert payment.subscription_id == sub.id
        assert payment.seat_quantity is None  # the CHECK forbids 0
        assert (payment.payer_user_id, payment.beneficiary_user_id) == (student, student)
    [body] = client.intentions
    assert body["amount"] == 9_900
    assert body["special_reference"] == str(result.payment_id)
    assert body["subscription_plan_id"] == 5001
    assert "subscription_start_date" not in body  # ignored when use_transaction_amount is true
    assert body["items"] == [{"name": "Student plan", "amount": 9_900, "quantity": 1}]
    assert result.checkout_url.startswith("https://")


def test_teacher_extra_seats_are_priced_on_the_server_in_unit_quantity_lines(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    teacher = seed_user(pg_sessionmaker, Role.teacher)
    tier = seed_tier(
        pg_sessionmaker,
        audience=PlanAudience.teacher,
        price_minor=50_000,
        included_seats=10,
        extra_seat_price_minor=2_500,
        paymob_plan_id=6001,
    )
    client = FakePaymobClient()

    result = _checkout(
        pg_sessionmaker, client, payer_user_id=teacher, plan_tier_id=tier, extra_seats=3
    )

    with pg_sessionmaker() as session:
        payment = session.get(Payment, result.payment_id)
        sub = session.get(Subscription, result.subscription_id)
        assert payment is not None
        assert sub is not None
        assert payment.amount_minor == 57_500
        assert payment.seat_quantity == 3
        assert sub.extra_seats == 3
    [body] = client.intentions
    assert body["amount"] == 57_500
    assert body["subscription_plan_id"] == 6001
    assert body["special_reference"] == str(result.payment_id)
    items = body["items"]
    assert isinstance(items, list)
    assert [item["quantity"] for item in items] == [1, 1]  # Phase 02 refuses any other quantity
    assert [item["amount"] for item in items] == [50_000, 7_500]
    assert items[1]["name"] == "Extra student seats x3"
    assert sum(item["amount"] * item["quantity"] for item in items) == body["amount"]


def test_line_items_follow_the_dv6_shape(pg_sessionmaker: sessionmaker[Session]) -> None:
    long_name = seed_tier(
        pg_sessionmaker,
        audience=PlanAudience.teacher,
        price_minor=40_000,
        extra_seat_price_minor=1_000,
    )
    with pg_sessionmaker.begin() as session:
        tier = session.get(PlanTier, long_name)
        assert tier is not None
        tier.name = "N" * 80
        assert _line_items(tier, 0) == [{"name": "N" * 50, "amount": 40_000, "quantity": 1}]
        assert _line_items(tier, 200) == [
            {"name": "N" * 50, "amount": 40_000, "quantity": 1},
            {"name": "Extra student seats x200", "amount": 200_000, "quantity": 1},
        ]


def test_the_amount_never_comes_from_the_caller(pg_sessionmaker: sessionmaker[Session]) -> None:
    """The service has no amount parameter at all: an extra keyword is a ``TypeError``."""
    student = seed_user(pg_sessionmaker, Role.student)
    tier = seed_tier(pg_sessionmaker, price_minor=9_900)
    with pytest.raises(TypeError):
        _checkout(
            pg_sessionmaker,
            payer_user_id=student,
            plan_tier_id=tier,
            amount_minor=1,
        )
    assert _counts(pg_sessionmaker) == (0, 0)


def test_extra_seat_arithmetic_uses_the_tier_not_the_request(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    teacher = seed_user(pg_sessionmaker, Role.teacher)
    tier = seed_tier(
        pg_sessionmaker,
        audience=PlanAudience.teacher,
        price_minor=30_000,
        extra_seat_price_minor=700,
    )
    result = _checkout(pg_sessionmaker, payer_user_id=teacher, plan_tier_id=tier, extra_seats=200)
    with pg_sessionmaker() as session:
        payment = session.get(Payment, result.payment_id)
        assert payment is not None
        assert payment.amount_minor == 30_000 + 200 * 700


def test_checkout_uses_the_callers_clock(pg_sessionmaker: sessionmaker[Session]) -> None:
    """DV-8: the reconcile deadline follows ``now`` (T0), not the wall clock."""
    student = seed_user(pg_sessionmaker, Role.student)
    tier = seed_tier(pg_sessionmaker)
    result = _checkout(pg_sessionmaker, payer_user_id=student, plan_tier_id=tier)
    with pg_sessionmaker() as session:
        payment = session.get(Payment, result.payment_id)
        assert payment is not None
        assert payment.next_reconcile_at is not None
        assert T0 < payment.next_reconcile_at < T0 + timedelta(days=1)


# -- authorization (IDOR) ------------------------------------------------------


def test_parent_buys_for_a_linked_student(pg_sessionmaker: sessionmaker[Session]) -> None:
    parent = seed_user(pg_sessionmaker, Role.parent)
    child = seed_user(pg_sessionmaker, Role.student)
    link_parent(pg_sessionmaker, parent_id=parent, child_id=child)
    tier = seed_tier(pg_sessionmaker)

    result = _checkout(
        pg_sessionmaker, payer_user_id=parent, plan_tier_id=tier, beneficiary_user_id=child
    )

    with pg_sessionmaker() as session:
        sub = session.get(Subscription, result.subscription_id)
        payment = session.get(Payment, result.payment_id)
        assert sub is not None
        assert payment is not None
        assert (sub.user_id, sub.payer_user_id) == (child, parent)
        assert (payment.payer_user_id, payment.beneficiary_user_id) == (parent, child)


def test_parent_cannot_buy_for_an_unlinked_student(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    parent = seed_user(pg_sessionmaker, Role.parent)
    linked = seed_user(pg_sessionmaker, Role.student)
    stranger = seed_user(pg_sessionmaker, Role.student)
    link_parent(pg_sessionmaker, parent_id=parent, child_id=linked)
    tier = seed_tier(pg_sessionmaker)
    _refused(
        pg_sessionmaker,
        NotLinkedParent,
        payer_user_id=parent,
        plan_tier_id=tier,
        beneficiary_user_id=stranger,
    )
    assert _subs_of(pg_sessionmaker, stranger) == []


def test_parent_cannot_buy_for_a_linked_user_who_is_not_a_student(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    parent = seed_user(pg_sessionmaker, Role.parent)
    teacher = seed_user(pg_sessionmaker, Role.teacher)
    other_parent = seed_user(pg_sessionmaker, Role.parent)
    link_parent(pg_sessionmaker, parent_id=parent, child_id=teacher)
    link_parent(pg_sessionmaker, parent_id=parent, child_id=other_parent)
    teacher_tier = seed_tier(pg_sessionmaker, audience=PlanAudience.teacher)
    for target in (teacher, other_parent):
        _refused(
            pg_sessionmaker,
            NotLinkedParent,
            payer_user_id=parent,
            plan_tier_id=teacher_tier,
            beneficiary_user_id=target,
        )


def test_parent_must_name_a_beneficiary(pg_sessionmaker: sessionmaker[Session]) -> None:
    parent = seed_user(pg_sessionmaker, Role.parent)
    child = seed_user(pg_sessionmaker, Role.student)
    link_parent(pg_sessionmaker, parent_id=parent, child_id=child)
    tier = seed_tier(pg_sessionmaker)
    _refused(pg_sessionmaker, NotLinkedParent, payer_user_id=parent, plan_tier_id=tier)
    _refused(
        pg_sessionmaker,
        NotLinkedParent,
        payer_user_id=parent,
        plan_tier_id=tier,
        beneficiary_user_id=parent,
    )


def test_a_student_or_teacher_cannot_buy_for_someone_else(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = seed_user(pg_sessionmaker, Role.student)
    victim = seed_user(pg_sessionmaker, Role.student)
    teacher = seed_user(pg_sessionmaker, Role.teacher)
    tier = seed_tier(pg_sessionmaker)
    teacher_tier = seed_tier(pg_sessionmaker, audience=PlanAudience.teacher)
    _refused(
        pg_sessionmaker,
        NotLinkedParent,
        payer_user_id=student,
        plan_tier_id=tier,
        beneficiary_user_id=victim,
    )
    _refused(
        pg_sessionmaker,
        NotLinkedParent,
        payer_user_id=teacher,
        plan_tier_id=tier,
        beneficiary_user_id=victim,
    )
    _refused(
        pg_sessionmaker,
        NotLinkedParent,
        payer_user_id=teacher,
        plan_tier_id=teacher_tier,
        beneficiary_user_id=student,
    )
    assert _subs_of(pg_sessionmaker, victim) == []


def test_a_user_may_name_themselves(pg_sessionmaker: sessionmaker[Session]) -> None:
    student = seed_user(pg_sessionmaker, Role.student)
    tier = seed_tier(pg_sessionmaker)
    result = _checkout(
        pg_sessionmaker, payer_user_id=student, plan_tier_id=tier, beneficiary_user_id=student
    )
    [sub] = _subs_of(pg_sessionmaker, student)
    assert sub.id == result.subscription_id


def test_an_unknown_payer_is_refused(pg_sessionmaker: sessionmaker[Session]) -> None:
    tier = seed_tier(pg_sessionmaker)
    _refused(pg_sessionmaker, UnknownPayer, payer_user_id=uuid.uuid4(), plan_tier_id=tier)


# -- tier and seats --------------------------------------------------------------


def test_the_tier_must_be_active_synced_dated_and_for_the_beneficiarys_role(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    teacher = seed_user(pg_sessionmaker, Role.teacher)
    student_tier = seed_tier(pg_sessionmaker, audience=PlanAudience.student)
    inactive = seed_tier(pg_sessionmaker, audience=PlanAudience.teacher, is_active=False)
    unsynced = seed_tier(pg_sessionmaker, audience=PlanAudience.teacher, paymob_plan_id=None)
    no_interval = seed_tier(pg_sessionmaker, audience=PlanAudience.teacher, interval=None)
    for tier in (student_tier, inactive, unsynced, no_interval, uuid.uuid4()):
        _refused(pg_sessionmaker, PlanNotPurchasable, payer_user_id=teacher, plan_tier_id=tier)
    admin = seed_user(pg_sessionmaker, Role.school_admin)
    _refused(pg_sessionmaker, PlanNotPurchasable, payer_user_id=admin, plan_tier_id=student_tier)


@pytest.mark.parametrize("extra_seats", [1, 5])
def test_extra_seats_on_a_student_tier_are_refused(
    pg_sessionmaker: sessionmaker[Session], extra_seats: int
) -> None:
    student = seed_user(pg_sessionmaker, Role.student)
    tier = seed_tier(pg_sessionmaker, extra_seat_price_minor=100)
    _refused(
        pg_sessionmaker,
        InvalidExtraSeats,
        payer_user_id=student,
        plan_tier_id=tier,
        extra_seats=extra_seats,
    )


@pytest.mark.parametrize("extra_seats", [-1, 201, 10_000])
def test_extra_seats_out_of_range_are_refused(
    pg_sessionmaker: sessionmaker[Session], extra_seats: int
) -> None:
    teacher = seed_user(pg_sessionmaker, Role.teacher)
    tier = seed_tier(pg_sessionmaker, audience=PlanAudience.teacher, extra_seat_price_minor=100)
    _refused(
        pg_sessionmaker,
        InvalidExtraSeats,
        payer_user_id=teacher,
        plan_tier_id=tier,
        extra_seats=extra_seats,
    )


def test_extra_seats_on_a_tier_with_no_seat_price_are_refused(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    teacher = seed_user(pg_sessionmaker, Role.teacher)
    free_seats = seed_tier(pg_sessionmaker, audience=PlanAudience.teacher, extra_seat_price_minor=0)
    _refused(
        pg_sessionmaker,
        InvalidExtraSeats,
        payer_user_id=teacher,
        plan_tier_id=free_seats,
        extra_seats=1,
    )
    # No extra seats asked for is fine on that tier.
    assert _checkout(pg_sessionmaker, payer_user_id=teacher, plan_tier_id=free_seats)


# -- the one live subscription -----------------------------------------------------


@pytest.mark.parametrize("status", [SubscriptionStatus.active, SubscriptionStatus.past_due])
def test_a_live_paid_subscription_blocks_a_second(
    pg_sessionmaker: sessionmaker[Session], status: SubscriptionStatus
) -> None:
    student = seed_user(pg_sessionmaker, Role.student)
    tier = seed_tier(pg_sessionmaker)
    seed_subscription(
        pg_sessionmaker, user_id=student, tier_id=tier, payer_id=student, status=status
    )
    _refused(pg_sessionmaker, AlreadySubscribed, payer_user_id=student, plan_tier_id=tier)


def test_a_manual_activation_blocks_checkout(pg_sessionmaker: sessionmaker[Session]) -> None:
    """The unique index ignores payer-less rows, so only the application check stops this."""
    student = seed_user(pg_sessionmaker, Role.student)
    tier = seed_tier(pg_sessionmaker)
    seed_subscription(pg_sessionmaker, user_id=student, tier_id=tier, is_manually_activated=True)
    _refused(pg_sessionmaker, AlreadySubscribed, payer_user_id=student, plan_tier_id=tier)


def test_a_parents_checkout_is_blocked_by_the_childs_own_plan(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    parent = seed_user(pg_sessionmaker, Role.parent)
    child = seed_user(pg_sessionmaker, Role.student)
    link_parent(pg_sessionmaker, parent_id=parent, child_id=child)
    tier = seed_tier(pg_sessionmaker)
    seed_subscription(pg_sessionmaker, user_id=child, tier_id=tier, payer_id=child)
    _refused(
        pg_sessionmaker,
        AlreadySubscribed,
        payer_user_id=parent,
        plan_tier_id=tier,
        beneficiary_user_id=child,
    )


def test_a_manual_activation_next_to_a_pending_checkout_still_blocks(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """Both rows are live for the user; retiring the stale pending one must not unblock."""
    student = seed_user(pg_sessionmaker, Role.student)
    tier = seed_tier(pg_sessionmaker)
    seed_subscription(pg_sessionmaker, user_id=student, tier_id=tier, is_manually_activated=True)
    pending = seed_subscription(
        pg_sessionmaker,
        user_id=student,
        tier_id=tier,
        payer_id=student,
        status=SubscriptionStatus.pending_first_payment,
        period_start=None,
        period_end=None,
    )
    seed_first_payment(
        pg_sessionmaker,
        subscription_id=pending,
        status=PaymentStatus.failed,
        paymob_txn_id=None,
    )
    _refused(pg_sessionmaker, AlreadySubscribed, payer_user_id=student, plan_tier_id=tier)
    assert _status(pg_sessionmaker, pending) is SubscriptionStatus.pending_first_payment


def test_an_ended_subscription_does_not_block(pg_sessionmaker: sessionmaker[Session]) -> None:
    student = seed_user(pg_sessionmaker, Role.student)
    tier = seed_tier(pg_sessionmaker)
    for status in (
        SubscriptionStatus.expired,
        SubscriptionStatus.cancelled,
        SubscriptionStatus.rejected,
        SubscriptionStatus.inactive,
    ):
        seed_subscription(
            pg_sessionmaker, user_id=student, tier_id=tier, payer_id=student, status=status
        )
    assert _checkout(pg_sessionmaker, payer_user_id=student, plan_tier_id=tier)


def test_a_fresh_pending_checkout_by_another_payer_blocks(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    parent = seed_user(pg_sessionmaker, Role.parent)
    child = seed_user(pg_sessionmaker, Role.student)
    link_parent(pg_sessionmaker, parent_id=parent, child_id=child)
    tier = seed_tier(pg_sessionmaker)
    pending = seed_subscription(
        pg_sessionmaker,
        user_id=child,
        tier_id=tier,
        payer_id=parent,
        status=SubscriptionStatus.pending_first_payment,
        period_start=None,
        period_end=None,
    )
    seed_first_payment(
        pg_sessionmaker,
        subscription_id=pending,
        status=PaymentStatus.created,
        paymob_txn_id=None,
        created_at=T0 - timedelta(minutes=10),
    )
    _refused(pg_sessionmaker, AlreadySubscribed, payer_user_id=child, plan_tier_id=tier)
    assert _status(pg_sessionmaker, pending) is SubscriptionStatus.pending_first_payment


def test_the_same_payer_supersedes_their_own_open_checkout(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    parent = seed_user(pg_sessionmaker, Role.parent)
    child = seed_user(pg_sessionmaker, Role.student)
    link_parent(pg_sessionmaker, parent_id=parent, child_id=child)
    tier = seed_tier(pg_sessionmaker)
    pending = seed_subscription(
        pg_sessionmaker,
        user_id=child,
        tier_id=tier,
        payer_id=parent,
        status=SubscriptionStatus.pending_first_payment,
        period_start=None,
        period_end=None,
    )
    old_payment = seed_first_payment(
        pg_sessionmaker,
        subscription_id=pending,
        status=PaymentStatus.created,
        paymob_txn_id=None,
        created_at=T0 - timedelta(minutes=10),
    )

    again = _checkout(
        pg_sessionmaker, payer_user_id=parent, plan_tier_id=tier, beneficiary_user_id=child
    )

    assert _status(pg_sessionmaker, pending) is SubscriptionStatus.expired
    assert (
        _status(pg_sessionmaker, again.subscription_id) is SubscriptionStatus.pending_first_payment
    )
    with pg_sessionmaker() as session:
        # The superseded checkout's payment stays open: reconcile may still settle it (T5).
        old = session.get(Payment, old_payment)
        assert old is not None
        assert old.status is PaymentStatus.created


_NO_INTENTION = {"source": "create_intention", "error": "rejected", "outcome_unknown": False}
_DECLINED = {"source": "callback", "success": False, "pending": False, "id": 4242}


def _parent_child_with_pending(
    sm: sessionmaker[Session],
    *,
    payment_status: PaymentStatus,
    last_callback: dict[str, object] | None,
    age: timedelta,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    """A parent's pending checkout for their child: (parent, child, tier, subscription)."""
    parent = seed_user(sm, Role.parent)
    child = seed_user(sm, Role.student)
    link_parent(sm, parent_id=parent, child_id=child)
    tier = seed_tier(sm)
    pending = seed_subscription(
        sm,
        user_id=child,
        tier_id=tier,
        payer_id=parent,
        status=SubscriptionStatus.pending_first_payment,
        period_start=None,
        period_end=None,
    )
    seed_first_payment(
        sm,
        subscription_id=pending,
        status=payment_status,
        paymob_txn_id=None,
        created_at=T0 - age,
        last_callback=last_callback,
    )
    return parent, child, tier, pending


@pytest.mark.parametrize(
    ("status", "last_callback"),
    [
        (PaymentStatus.failed, _NO_INTENTION),  # the intention was rejected: nothing can be paid
        (PaymentStatus.failed_mismatch, _DECLINED),  # closed: Phase 02 ignores later callbacks
        (PaymentStatus.voided, _DECLINED),
    ],
)
def test_an_unpayable_first_payment_is_superseded_by_anyone_at_once(
    pg_sessionmaker: sessionmaker[Session],
    status: PaymentStatus,
    last_callback: dict[str, object],
) -> None:
    _, child, tier, dead = _parent_child_with_pending(
        pg_sessionmaker,
        payment_status=status,
        last_callback=last_callback,
        age=timedelta(minutes=1),
    )
    replacement = _checkout(pg_sessionmaker, payer_user_id=child, plan_tier_id=tier)
    assert _status(pg_sessionmaker, dead) is SubscriptionStatus.expired
    assert replacement.subscription_id != dead


def test_a_declined_card_keeps_the_checkout_payable_for_the_intention_lifetime(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """Phase 02 lets a ``failed`` payment become ``paid`` while the intention is open (R20b).

    A decline leaves the Unified Checkout page open for an hour, where the payer can try another
    card. Replacing the checkout meanwhile would let that payment land on an expired plan.
    """
    parent, child, tier, declined = _parent_child_with_pending(
        pg_sessionmaker,
        payment_status=PaymentStatus.failed,
        last_callback=_DECLINED,
        age=timedelta(minutes=5),
    )
    # Another payer (the student) cannot replace it ...
    _refused(pg_sessionmaker, AlreadySubscribed, payer_user_id=child, plan_tier_id=tier)
    assert _status(pg_sessionmaker, declined) is SubscriptionStatus.pending_first_payment
    # ... the payer who started it may start again (same-payer rule), as for any open checkout.
    again = _checkout(
        pg_sessionmaker, payer_user_id=parent, plan_tier_id=tier, beneficiary_user_id=child
    )
    assert _status(pg_sessionmaker, declined) is SubscriptionStatus.expired
    assert again.subscription_id != declined


def test_a_declined_checkout_is_replaceable_by_anyone_after_the_intention_lifetime(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _, child, tier, declined = _parent_child_with_pending(
        pg_sessionmaker,
        payment_status=PaymentStatus.failed,
        last_callback=_DECLINED,
        age=timedelta(seconds=INTENTION_EXPIRATION_SECONDS - 1),
    )
    _refused(pg_sessionmaker, AlreadySubscribed, payer_user_id=child, plan_tier_id=tier)
    with pg_sessionmaker.begin() as session:
        payment = session.scalars(
            sa.select(Payment).where(Payment.subscription_id == declined)
        ).one()
        payment.created_at = T0 - timedelta(seconds=INTENTION_EXPIRATION_SECONDS)
    taken = _checkout(pg_sessionmaker, payer_user_id=child, plan_tier_id=tier)
    assert _status(pg_sessionmaker, declined) is SubscriptionStatus.expired
    assert taken.subscription_id != declined


def test_a_stale_open_checkout_is_superseded_by_another_payer_but_not_a_fresh_one(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    parent = seed_user(pg_sessionmaker, Role.parent)
    child = seed_user(pg_sessionmaker, Role.student)
    link_parent(pg_sessionmaker, parent_id=parent, child_id=child)
    tier = seed_tier(pg_sessionmaker)
    pending = seed_subscription(
        pg_sessionmaker,
        user_id=child,
        tier_id=tier,
        payer_id=parent,
        status=SubscriptionStatus.pending_first_payment,
        period_start=None,
        period_end=None,
    )
    payment = seed_first_payment(
        pg_sessionmaker,
        subscription_id=pending,
        status=PaymentStatus.created,
        paymob_txn_id=None,
        created_at=T0 - STALE_CHECKOUT_AFTER + timedelta(seconds=1),
    )
    _refused(pg_sessionmaker, AlreadySubscribed, payer_user_id=child, plan_tier_id=tier)

    with pg_sessionmaker.begin() as session:
        row = session.get(Payment, payment)
        assert row is not None
        row.created_at = T0 - STALE_CHECKOUT_AFTER
    taken = _checkout(pg_sessionmaker, payer_user_id=child, plan_tier_id=tier)
    assert _status(pg_sessionmaker, pending) is SubscriptionStatus.expired
    assert taken.subscription_id != pending


def test_a_pending_checkout_with_no_payment_row_is_replaceable(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    parent = seed_user(pg_sessionmaker, Role.parent)
    child = seed_user(pg_sessionmaker, Role.student)
    link_parent(pg_sessionmaker, parent_id=parent, child_id=child)
    tier = seed_tier(pg_sessionmaker)
    orphan = seed_subscription(
        pg_sessionmaker,
        user_id=child,
        tier_id=tier,
        payer_id=parent,
        status=SubscriptionStatus.pending_first_payment,
        period_start=None,
        period_end=None,
    )
    assert _checkout(pg_sessionmaker, payer_user_id=child, plan_tier_id=tier)
    assert _status(pg_sessionmaker, orphan) is SubscriptionStatus.expired


@pytest.mark.parametrize("same_payer", [True, False])
def test_a_paid_but_unactivated_checkout_is_never_superseded(
    pg_sessionmaker: sessionmaker[Session], same_payer: bool
) -> None:
    parent = seed_user(pg_sessionmaker, Role.parent)
    child = seed_user(pg_sessionmaker, Role.student)
    link_parent(pg_sessionmaker, parent_id=parent, child_id=child)
    tier = seed_tier(pg_sessionmaker)
    pending = seed_subscription(
        pg_sessionmaker,
        user_id=child,
        tier_id=tier,
        payer_id=parent,
        status=SubscriptionStatus.pending_first_payment,
        period_start=None,
        period_end=None,
    )
    seed_first_payment(
        pg_sessionmaker,
        subscription_id=pending,
        status=PaymentStatus.paid,
        created_at=T0 - timedelta(days=2),
    )
    _refused(
        pg_sessionmaker,
        AlreadySubscribed,
        payer_user_id=parent if same_payer else child,
        beneficiary_user_id=child if same_payer else None,
        plan_tier_id=tier,
    )
    assert _status(pg_sessionmaker, pending) is SubscriptionStatus.pending_first_payment


# -- Paymob outcomes (R20b) ---------------------------------------------------------


@pytest.mark.parametrize(
    "error",
    [
        PaymobError("Paymob POST v1/intention/ timed out", timeout=True),
        PaymobError("Paymob POST v1/intention/ transport error"),
        PaymobError("Paymob POST v1/intention/ returned 500", status_code=500),
    ],
)
def test_an_unknown_outcome_keeps_the_payment_open_and_the_same_payer_supersedes_it(
    pg_sessionmaker: sessionmaker[Session], error: PaymobError
) -> None:
    parent = seed_user(pg_sessionmaker, Role.parent)
    child = seed_user(pg_sessionmaker, Role.student)
    link_parent(pg_sessionmaker, parent_id=parent, child_id=child)
    tier = seed_tier(pg_sessionmaker)
    client = FakePaymobClient()
    client.intention_response = error

    with pytest.raises(CheckoutUnavailable):
        _checkout(
            pg_sessionmaker,
            client,
            payer_user_id=parent,
            plan_tier_id=tier,
            beneficiary_user_id=child,
        )
    [unknown] = _subs_of(pg_sessionmaker, child)
    assert unknown.status is SubscriptionStatus.pending_first_payment
    assert _payment_status(pg_sessionmaker, unknown.id) is PaymentStatus.created  # R20b

    # The child cannot start their own while the parent's outcome is unknown ...
    _refused(pg_sessionmaker, AlreadySubscribed, payer_user_id=child, plan_tier_id=tier)
    # ... but the same payer's next checkout supersedes it, leaving the payment open.
    retry = _checkout(
        pg_sessionmaker, payer_user_id=parent, plan_tier_id=tier, beneficiary_user_id=child
    )
    assert _status(pg_sessionmaker, unknown.id) is SubscriptionStatus.expired
    assert (
        _status(pg_sessionmaker, retry.subscription_id) is SubscriptionStatus.pending_first_payment
    )
    assert _payment_status(pg_sessionmaker, unknown.id) is PaymentStatus.created


@pytest.mark.parametrize(
    "error",
    [
        PaymobError(
            "Paymob POST v1/intention/ returned 404",
            status_code=404,
            body={"message": "invalid subscription plan id"},
        ),
        PaymobError("Paymob POST v1/intention/ returned 400", status_code=400),
    ],
)
def test_a_definite_rejection_marks_the_payment_failed_and_anyone_supersedes_it(
    pg_sessionmaker: sessionmaker[Session], error: PaymobError
) -> None:
    parent = seed_user(pg_sessionmaker, Role.parent)
    child = seed_user(pg_sessionmaker, Role.student)
    link_parent(pg_sessionmaker, parent_id=parent, child_id=child)
    tier = seed_tier(pg_sessionmaker)
    client = FakePaymobClient()
    client.intention_response = error

    with pytest.raises(CheckoutUnavailable):
        _checkout(
            pg_sessionmaker,
            client,
            payer_user_id=parent,
            plan_tier_id=tier,
            beneficiary_user_id=child,
        )
    [failed] = _subs_of(pg_sessionmaker, child)
    assert _payment_status(pg_sessionmaker, failed.id) is PaymentStatus.failed

    retry = _checkout(pg_sessionmaker, payer_user_id=child, plan_tier_id=tier)  # another payer
    assert _status(pg_sessionmaker, failed.id) is SubscriptionStatus.expired
    assert (
        _status(pg_sessionmaker, retry.subscription_id) is SubscriptionStatus.pending_first_payment
    )


def test_racing_checkouts_meet_the_unique_index_and_one_wins(
    pg_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A competitor commits a live subscription after our live check but before our insert."""
    student = seed_user(pg_sessionmaker, Role.student)
    tier = seed_tier(pg_sessionmaker)
    original = SubscriptionService._retire_stale_checkout
    winner: list[uuid.UUID] = []

    def _retire_then_lose_the_race(
        self: SubscriptionService, *args: object, **kwargs: object
    ) -> None:
        original(self, *args, **kwargs)  # type: ignore[arg-type]
        winner.append(
            seed_subscription(pg_sessionmaker, user_id=student, tier_id=tier, payer_id=student)
        )

    monkeypatch.setattr(SubscriptionService, "_retire_stale_checkout", _retire_then_lose_the_race)
    client = FakePaymobClient()
    with pytest.raises(AlreadySubscribed):
        _checkout(pg_sessionmaker, client, payer_user_id=student, plan_tier_id=tier)

    [only] = _subs_of(pg_sessionmaker, student)
    assert only.id == winner[0]
    assert client.intentions == []
    with pg_sessionmaker() as session:
        assert session.scalar(sa.select(sa.func.count()).select_from(Payment)) == 0


# -- configuration guards ------------------------------------------------------------


def test_unconfigured_paymob_refuses_before_any_write(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = seed_user(pg_sessionmaker, Role.student)
    tier = seed_tier(pg_sessionmaker)
    _refused(
        pg_sessionmaker,
        CheckoutUnavailable,
        settings=paymob_settings(card_integration_id=None),
        payer_user_id=student,
        plan_tier_id=tier,
    )


def test_unconfigured_paymob_is_decided_before_the_other_refusals(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """An invalid request on a dead gateway answers ``CheckoutUnavailable``, not a 4xx reason."""
    student = seed_user(pg_sessionmaker, Role.student)
    inactive = seed_tier(pg_sessionmaker, is_active=False)
    _refused(
        pg_sessionmaker,
        CheckoutUnavailable,
        settings=paymob_settings(secret_key=None),
        payer_user_id=student,
        plan_tier_id=inactive,
    )


@pytest.mark.parametrize(
    ("plan_mode", "keys"),
    [
        ("test", ("egy_sk_live_secret", "egy_pk_live_public")),
        ("live", ("egy_sk_test_secret", "egy_pk_test_public")),
    ],
)
def test_a_plan_made_under_the_other_key_mode_is_refused_with_an_alert(
    pg_sessionmaker: sessionmaker[Session],
    capsys: pytest.CaptureFixture[str],
    plan_mode: str,
    keys: tuple[str, str],
) -> None:
    student = seed_user(pg_sessionmaker, Role.student)
    tier = seed_tier(
        pg_sessionmaker,
        paymob_plan_mode="live" if plan_mode == "live" else "test",
    )
    settings = paymob_settings(secret_key=keys[0], public_key=keys[1])

    error = _refused(
        pg_sessionmaker,
        PlanModeMismatch,
        settings=settings,
        payer_user_id=student,
        plan_tier_id=tier,
    )

    assert isinstance(error, PlanNotPurchasable)  # callers that map it keep working
    assert error.code == "plan_mode_mismatch"
    assert str(error) == "This plan is being set up. Please try again later."
    logged = capsys.readouterr()
    text = logged.out + logged.err
    assert "subscription_plan_mode_mismatch" in text
    assert str(tier) in text
    assert keys[0] not in text
    assert keys[1] not in text


def _mismatch_alerts(output: str) -> int:
    return sum(
        1 for line in output.splitlines() if "plan_mode_mismatch" in line and "alert=True" in line
    )


def test_the_mode_mismatch_alert_fires_once_per_tier_per_window(
    pg_sessionmaker: sessionmaker[Session],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Every click on a mismatched plan is refused, but the operator is paged once (audit I8)."""
    student = seed_user(pg_sessionmaker, Role.student)
    tier = seed_tier(pg_sessionmaker)
    settings = paymob_settings(secret_key="egy_sk_live_secret", public_key="egy_pk_live_public")

    def _attempt(now_offset: timedelta) -> None:
        with pg_sessionmaker() as session, pytest.raises(PlanModeMismatch):
            _service(session, FakePaymobClient(), settings).create_subscription_checkout(
                payer_user_id=student, plan_tier_id=tier, now=T0 + now_offset
            )

    _attempt(timedelta(0))
    _attempt(timedelta(seconds=30))
    _attempt(_MODE_ALERT_EVERY - timedelta(seconds=1))
    logged = capsys.readouterr()
    assert _mismatch_alerts(logged.out + logged.err) == 1
    _attempt(_MODE_ALERT_EVERY)
    logged = capsys.readouterr()
    assert _mismatch_alerts(logged.out + logged.err) == 1  # a new window pages again


def test_a_plan_in_the_configured_mode_is_sold(pg_sessionmaker: sessionmaker[Session]) -> None:
    student = seed_user(pg_sessionmaker, Role.student)
    tier = seed_tier(pg_sessionmaker, paymob_plan_mode="live")
    settings = paymob_settings(secret_key="egy_sk_live_secret", public_key="egy_pk_live_public")
    assert _checkout(pg_sessionmaker, settings=settings, payer_user_id=student, plan_tier_id=tier)


def test_a_payer_with_no_valid_phone_is_refused_before_any_write(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """UD-11: ``billing_data_for`` raises ``PhoneRequired``; nothing is written or sent."""
    no_phone = seed_user(pg_sessionmaker, Role.student, phone=None)
    junk_phone = seed_user(pg_sessionmaker, Role.student, phone="NA")
    tier = seed_tier(pg_sessionmaker)
    for payer in (no_phone, junk_phone):
        _refused(pg_sessionmaker, PhoneRequired, payer_user_id=payer, plan_tier_id=tier)


def test_a_parents_phone_is_the_one_that_matters(pg_sessionmaker: sessionmaker[Session]) -> None:
    parent = seed_user(pg_sessionmaker, Role.parent, phone=None)
    child = seed_user(pg_sessionmaker, Role.student, phone="+201234567890")
    link_parent(pg_sessionmaker, parent_id=parent, child_id=child)
    tier = seed_tier(pg_sessionmaker)
    _refused(
        pg_sessionmaker,
        PhoneRequired,
        payer_user_id=parent,
        plan_tier_id=tier,
        beneficiary_user_id=child,
    )


def test_the_intention_carries_the_payers_real_phone(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = seed_user(pg_sessionmaker, Role.student, phone="01012345678")
    tier = seed_tier(pg_sessionmaker)
    client = FakePaymobClient()
    _checkout(pg_sessionmaker, client, payer_user_id=student, plan_tier_id=tier)
    [body] = client.intentions
    assert body["billing_data"]["phone_number"] == "+201012345678"


def test_a_phone_refusal_leaves_a_replaceable_checkout_untouched_in_the_same_session(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The phone check precedes the supersession flush: nothing is written, even uncommitted.

    The committed-rows tests cannot see this (the caller never commits a refusal); a flushed
    supersession is visible in the refusing session itself.
    """
    parent = seed_user(pg_sessionmaker, Role.parent, phone=None)
    child = seed_user(pg_sessionmaker, Role.student)
    link_parent(pg_sessionmaker, parent_id=parent, child_id=child)
    tier = seed_tier(pg_sessionmaker)
    pending = seed_subscription(
        pg_sessionmaker,
        user_id=child,
        tier_id=tier,
        payer_id=parent,
        status=SubscriptionStatus.pending_first_payment,
        period_start=None,
        period_end=None,
    )
    seed_first_payment(
        pg_sessionmaker,
        subscription_id=pending,
        status=PaymentStatus.created,
        paymob_txn_id=None,
        created_at=T0 - timedelta(minutes=10),
    )
    with pg_sessionmaker() as session:
        service = _service(session, FakePaymobClient())
        with pytest.raises(PhoneRequired):
            service.create_subscription_checkout(
                payer_user_id=parent, plan_tier_id=tier, beneficiary_user_id=child, now=T0
            )
        row = session.get(Subscription, pending)
        assert row is not None
        session.refresh(row)
        assert row.status is SubscriptionStatus.pending_first_payment
        assert session.scalar(sa.select(sa.func.count()).select_from(Subscription)) == 1
        assert session.scalar(sa.select(sa.func.count()).select_from(Payment)) == 1


# -- the row lock, the constraint mapping, the payload ---------------------------------------


def test_the_live_rows_are_locked_in_a_fixed_order_until_the_checkout_ends(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The judgement of the live rows holds a ``FOR UPDATE`` lock (ordered, against deadlocks).

    A live manual plan makes the checkout refuse without writing the row, so a lock held by the
    refusing session can only come from the explicit ``FOR UPDATE``.
    """
    student = seed_user(pg_sessionmaker, Role.student)
    tier = seed_tier(pg_sessionmaker)
    manual = seed_subscription(
        pg_sessionmaker, user_id=student, tier_id=tier, is_manually_activated=True
    )
    statements: list[str] = []

    def _record(conn: object, cursor: object, statement: str, *rest: object) -> None:
        statements.append(statement)

    engine = pg_sessionmaker.kw["bind"]
    event.listen(engine, "before_cursor_execute", _record)
    try:
        with pg_sessionmaker() as holder, pg_sessionmaker() as other:
            service = _service(holder, FakePaymobClient())
            with pytest.raises(AlreadySubscribed):
                service.create_subscription_checkout(
                    payer_user_id=student, plan_tier_id=tier, now=T0
                )
            # The refused session still holds its transaction, and with it the row lock.
            other.execute(sa.text("SET LOCAL lock_timeout = '300ms'"))
            with pytest.raises(OperationalError):
                other.execute(
                    sa.select(Subscription.id)
                    .where(Subscription.id == manual)
                    .with_for_update(nowait=True)
                ).all()
    finally:
        event.remove(engine, "before_cursor_execute", _record)
    locking = [
        s
        for s in statements
        if "FROM subscriptions" in s and "subscriptions.user_id" in s and "FOR UPDATE" in s
    ]
    assert locking, "no locking select on subscriptions was issued"
    assert all("ORDER BY subscriptions.id" in s for s in locking)


def test_only_the_one_live_constraint_means_already_subscribed(
    pg_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Another integrity failure of the subscription insert is not "already subscribed".

    The beneficiary is deleted from a second session after the checkout read it and before it
    inserts the subscription, so the insert itself fails on a foreign key to ``users``
    (``fk_subscriptions_payer_user_id_users``, the first one Postgres checks).
    The failure must come from that insert (asserted by constraint name): a failure from any
    other statement would pass the test without exercising the service's constraint mapping.
    """
    student = seed_user(pg_sessionmaker, Role.student)
    tier = seed_tier(pg_sessionmaker)
    original = SubscriptionService._retire_stale_checkout

    def _retire_then_lose_the_user(
        self: SubscriptionService, *args: object, **kwargs: object
    ) -> None:
        original(self, *args, **kwargs)  # type: ignore[arg-type]
        with pg_sessionmaker.begin() as other:
            other.execute(sa.delete(User).where(User.id == student))

    monkeypatch.setattr(SubscriptionService, "_retire_stale_checkout", _retire_then_lose_the_user)
    client = FakePaymobClient()
    with pytest.raises(IntegrityError) as excinfo:
        _checkout(pg_sessionmaker, client, payer_user_id=student, plan_tier_id=tier)
    assert not isinstance(excinfo.value, AlreadySubscribed)
    diag = getattr(excinfo.value.orig, "diag", None)
    assert getattr(diag, "constraint_name", None) == "fk_subscriptions_payer_user_id_users"
    assert "INSERT INTO subscriptions" in (excinfo.value.statement or "")
    assert client.intentions == []


def test_the_intention_pins_currency_and_the_card_integration(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = seed_user(pg_sessionmaker, Role.student)
    tier = seed_tier(pg_sessionmaker, currency="USD", price_minor=1_500)
    settings = paymob_settings()
    client = FakePaymobClient()
    result = _checkout(
        pg_sessionmaker, client, settings=settings, payer_user_id=student, plan_tier_id=tier
    )
    [body] = client.intentions
    assert body["currency"] == "USD"
    assert body["payment_methods"] == [settings.card_integration_id]  # the card 3DS integration
    assert body["payment_methods"] != [settings.moto_integration_id]
    with pg_sessionmaker() as session:
        payment = session.get(Payment, result.payment_id)
        assert payment is not None
        assert payment.currency == "USD"


# -- UD-5: a teacher cannot buy fewer seats than they hold -----------------------------------


def _teacher_with_seats(sm: sessionmaker[Session], *, active: int, leaving: int = 0) -> uuid.UUID:
    teacher = seed_user(sm, Role.teacher)
    for _ in range(active):
        seed_seat(sm, teacher_id=teacher, student_id=seed_user(sm, Role.student))
    for _ in range(leaving):
        seed_seat(
            sm,
            teacher_id=teacher,
            student_id=seed_user(sm, Role.student),
            status=TeacherMemberStatus.leaving,
        )
    return teacher


def test_a_teacher_with_more_active_seats_than_the_plan_covers_is_refused(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    teacher = _teacher_with_seats(pg_sessionmaker, active=5)
    small = seed_tier(
        pg_sessionmaker,
        audience=PlanAudience.teacher,
        included_seats=3,
        extra_seat_price_minor=100,
    )
    error = _refused(pg_sessionmaker, SeatsInsufficient, payer_user_id=teacher, plan_tier_id=small)
    assert isinstance(error, SeatsInsufficient)
    assert (error.in_use, error.capacity) == (5, 3)
    # Extra seats count toward the capacity: 3 + 1 is still short, 3 + 2 is enough.
    error = _refused(
        pg_sessionmaker,
        SeatsInsufficient,
        payer_user_id=teacher,
        plan_tier_id=small,
        extra_seats=1,
    )
    assert isinstance(error, SeatsInsufficient)
    assert (error.in_use, error.capacity) == (5, 4)
    assert _checkout(pg_sessionmaker, payer_user_id=teacher, plan_tier_id=small, extra_seats=2)


def test_leaving_seats_do_not_count_toward_the_seat_check(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """UD-5: after removing students the teacher can subscribe at once, not at month end."""
    teacher = _teacher_with_seats(pg_sessionmaker, active=3, leaving=4)
    tier = seed_tier(
        pg_sessionmaker,
        audience=PlanAudience.teacher,
        included_seats=3,
        extra_seat_price_minor=100,
    )
    assert _checkout(pg_sessionmaker, payer_user_id=teacher, plan_tier_id=tier)


def test_a_plan_that_covers_the_held_seats_exactly_is_sold(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    teacher = _teacher_with_seats(pg_sessionmaker, active=3)
    tier = seed_tier(pg_sessionmaker, audience=PlanAudience.teacher, included_seats=3)
    assert _checkout(pg_sessionmaker, payer_user_id=teacher, plan_tier_id=tier)


def test_another_teachers_seats_do_not_count(pg_sessionmaker: sessionmaker[Session]) -> None:
    _teacher_with_seats(pg_sessionmaker, active=9)
    teacher = seed_user(pg_sessionmaker, Role.teacher)
    tier = seed_tier(pg_sessionmaker, audience=PlanAudience.teacher, included_seats=1)
    assert _checkout(pg_sessionmaker, payer_user_id=teacher, plan_tier_id=tier)


# -- module helpers other tasks rely on ---------------------------------------------------


def test_bump_advances_the_version(pg_sessionmaker: sessionmaker[Session]) -> None:
    student = seed_user(pg_sessionmaker, Role.student)
    tier = seed_tier(pg_sessionmaker)
    sub_id = seed_subscription(pg_sessionmaker, user_id=student, tier_id=tier, payer_id=student)
    with pg_sessionmaker.begin() as session:
        sub = session.get(Subscription, sub_id)
        assert sub is not None
        before = sub.version
        _bump(sub)
        assert sub.version == before + 1


def test_has_other_live_ignores_the_row_itself_and_ended_rows(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = seed_user(pg_sessionmaker, Role.student)
    tier = seed_tier(pg_sessionmaker)
    mine = seed_subscription(pg_sessionmaker, user_id=student, tier_id=tier, payer_id=student)
    seed_subscription(
        pg_sessionmaker,
        user_id=student,
        tier_id=tier,
        payer_id=student,
        status=SubscriptionStatus.expired,
    )
    with pg_sessionmaker() as session:
        row = session.get(Subscription, mine)
        assert row is not None
        assert _has_other_live(session, row) is False
    seed_subscription(pg_sessionmaker, user_id=student, tier_id=tier, is_manually_activated=True)
    with pg_sessionmaker() as session:
        row = session.get(Subscription, mine)
        assert row is not None
        assert _has_other_live(session, row) is True
