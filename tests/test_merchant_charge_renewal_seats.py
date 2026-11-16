"""The fallback renewal seat charge: grace, daily retries and the seat drop (Phase 06 T6).

When Paymob cannot take an amount change (``subscription_amount_updatable`` false) a renewal
charges the old amount and the seats the teacher added are unpaid. This job charges the gap to the
saved card (MOTO, nobody present), retries once a day while the grace lasts and, when it ends,
drops the extra seats. Money safety, in the order the code enforces it: nothing is queued on the
updatable path (the push, or the user's own purchase, covers it); the amount comes from the
period's own renewal payment and the terms that period was billed on, never from the live tier or
``paymob_amount_minor`` (DV-3); a seat purchase checkout that may still be paid defers the first
attempt (DV-27); an attempt whose outcome is unknown blocks every retry; only the verified
callback marks an attempt paid; a drop keeps the grace marker so one failed period never starts a
second grace. Every guard has a mutation proof in the task report.

Runs on a throwaway Postgres database (``create_all``); skips without a local Postgres.
"""

from __future__ import annotations

import itertools
import threading
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
import sqlalchemy as sa
from structlog.testing import capture_logs

import lemely.db.merchant_charge_repo as repo
import lemely.db.subscription_repo as subscription_repo
from lemely.db.billing_repo import INTENTION_EXPIRATION_SECONDS, RECONCILE_AFTER, BillingService
from lemely.db.merchant_charge_repo import (
    MERCHANT_SWEEP_BATCH,
    RENEWAL_SEAT_DEDUPE_PREFIX,
    SEAT_RETRY_INTERVAL,
    current_period,
    queue_renewal_seat_charge,
    renewal_seat_shortfall,
    run_extra_seat_renewal_job,
)
from lemely.db.models.billing import (
    Payment,
    PaymentPurpose,
    PaymentStatus,
    PlanAudience,
    Subscription,
    SubscriptionPeriod,
)
from lemely.db.models.billing_ops import BillingSettings, CreditConversionRate
from lemely.db.models.enums import Role, SubscriptionStatus
from lemely.db.models.team import TeacherMember, TeacherMemberStatus
from lemely.db.models.tutoring import EmailOutbox
from lemely.io.notify_email import ExtraSeatsChargeFailed
from tests.merchant_charge_fixtures import (
    FakeMotoClient,
    moto_txn,
    seed_payment_row,
    seed_seat,
    seed_tier,
    seed_user,
    teacher_with_plan,
    throwaway_database,
)
from tests.paymob_fixtures import PAYMOB_SETTINGS
from tests.subscription_fixtures import T0, grants_of, paymob_settings

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from sqlalchemy.orm import Session, sessionmaker

NOW = T0 + timedelta(days=1)
FALLBACK = paymob_settings(subscription_amount_updatable=False)
UPDATABLE = paymob_settings(subscription_amount_updatable=True)
DECLINE: dict[str, Any] = {"id": 1, "success": False, "pending": False}
_txn_ids = itertools.count(8_800_001)
_order_ids = itertools.count(990_001)


@pytest.fixture(scope="module")
def pg_sessionmaker() -> Iterator[sessionmaker[Session]]:
    with throwaway_database() as factory:
        with factory.begin() as session:
            session.add(CreditConversionRate(currency="EGP", units_per_minor=Decimal("0.01")))
        yield factory


@pytest.fixture(autouse=True)
def _quiet_database(pg_sessionmaker: sessionmaker[Session]) -> None:
    """Earlier tests' subscriptions and queued attempts take no part in this test's run.

    The job scans every subscription in the database, so rows another test left behind would be
    charged or counted here. They are switched off (no seats, no grace) and their unsent
    attempts failed, the same state a finished subscription is in.
    """
    with pg_sessionmaker.begin() as session:
        session.execute(sa.update(Subscription).values(extra_seats=0, extra_seat_grace_until=None))
        session.execute(
            sa.update(Payment)
            .where(
                Payment.dedupe_key.like(f"{RENEWAL_SEAT_DEDUPE_PREFIX}%"),
                Payment.status == PaymentStatus.created,
            )
            .values(status=PaymentStatus.failed)
        )


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def _scene(
    sm: sessionmaker[Session],
    *,
    renewal: int = 30_000,
    extra: int = 2,
    seats: int = 0,
    **kwargs: Any,
) -> dict[str, uuid.UUID]:
    """A teacher paying 30 000 with 2 included seats and ``extra`` more at 2 000.

    The current period is paid by a ``subscription_renewal`` payment of ``renewal`` (the amount
    Paymob charged, which on the fallback path has no seat rise in it) and ``seats`` active
    student seats are held. ``paymob_amount_minor`` holds what Paymob charges.
    """
    scene = teacher_with_plan(
        sm, included=2, seat_price=2_000, price=30_000, extra=extra, paymob_amount=renewal, **kwargs
    )
    renewal_id = seed_payment_row(
        sm,
        payer_id=scene["payer_id"],
        beneficiary_id=scene["user_id"],
        purpose=PaymentPurpose.subscription_renewal,
        amount_minor=renewal,
        status=PaymentStatus.paid,
        subscription_id=scene["subscription_id"],
        plan_tier_id=scene["tier_id"],
        paid_at=T0,
    )
    scene["renewal_id"] = renewal_id
    with sm.begin() as session:
        session.execute(
            sa.update(SubscriptionPeriod)
            .where(SubscriptionPeriod.id == scene["period_id"])
            .values(payment_id=renewal_id)
        )
    for _ in range(seats):
        seed_seat(
            sm,
            teacher_id=scene["teacher_id"],
            student_id=seed_user(sm, Role.student),
            created_at=T0 + timedelta(minutes=len(_seat_ids(sm, scene))),
        )
    return scene


def _seat_ids(sm: sessionmaker[Session], scene: Mapping[str, uuid.UUID]) -> list[uuid.UUID]:
    with sm() as session:
        return list(
            session.scalars(
                sa.select(TeacherMember.id).where(
                    TeacherMember.teacher_user_id == scene["teacher_id"]
                )
            )
        )


def _run(
    sm: sessionmaker[Session],
    client: FakeMotoClient,
    *,
    settings: Any = FALLBACK,
    now: datetime = NOW,
    limit: int = MERCHANT_SWEEP_BATCH,
) -> int:
    return run_extra_seat_renewal_job(sm, client, settings, now=now, limit=limit)


def _attempts(sm: sessionmaker[Session], scene: Mapping[str, uuid.UUID]) -> list[Payment]:
    with sm() as session:
        rows = session.scalars(
            sa.select(Payment).where(
                Payment.subscription_id == scene["subscription_id"],
                Payment.purpose == PaymentPurpose.extra_seats,
                Payment.dedupe_key.like(f"{RENEWAL_SEAT_DEDUPE_PREFIX}%"),
            )
        ).all()
    return sorted(rows, key=lambda row: row.dedupe_key or "")


def _sub(sm: sessionmaker[Session], scene: Mapping[str, uuid.UUID]) -> Subscription:
    with sm() as session:
        row = session.get(Subscription, scene["subscription_id"])
        assert row is not None
        return row


def _update_sub(sm: sessionmaker[Session], scene: Mapping[str, uuid.UUID], **values: Any) -> None:
    with sm.begin() as session:
        session.execute(
            sa.update(Subscription)
            .where(Subscription.id == scene["subscription_id"])
            .values(**values)
        )


def _key(scene: Mapping[str, uuid.UUID], attempt: int) -> str:
    return f"{RENEWAL_SEAT_DEDUPE_PREFIX}{scene['period_id']}:{attempt}"


def _seed_attempt(
    sm: sessionmaker[Session],
    scene: Mapping[str, uuid.UUID],
    attempt: int,
    status: PaymentStatus,
    *,
    amount: int = 4_000,
    created_at: datetime | None = None,
    sent_at: datetime | None = None,
    with_order: bool = False,
) -> uuid.UUID:
    payment_id = seed_payment_row(
        sm,
        payer_id=scene["payer_id"],
        beneficiary_id=scene["user_id"],
        purpose=PaymentPurpose.extra_seats,
        amount_minor=amount,
        status=status,
        subscription_id=scene["subscription_id"],
        seat_quantity=amount // 2_000,
        dedupe_key=_key(scene, attempt),
        paid_at=NOW if status is PaymentStatus.paid else None,
        created_at=created_at,
        paymob_order_id=next(_order_ids) if with_order else None,
    )
    if sent_at is not None:
        with sm.begin() as session:
            session.execute(
                sa.update(Payment).where(Payment.id == payment_id).values(sent_at=sent_at)
            )
    return payment_id


def _seed_purchase(
    sm: sessionmaker[Session],
    scene: Mapping[str, uuid.UUID],
    status: PaymentStatus,
    *,
    seats: int = 1,
    created_at: datetime,
    applied: bool = True,
) -> uuid.UUID:
    """A seat purchase checkout (no ``dedupe_key``): prorated, so cheaper than the full price.

    A paid one is stamped ``applied_at`` (its handler added the seats) unless ``applied`` is false:
    a purchase voided to credits, or left unconverted, added none.
    """
    payment_id = seed_payment_row(
        sm,
        payer_id=scene["payer_id"],
        beneficiary_id=scene["user_id"],
        purpose=PaymentPurpose.extra_seats,
        amount_minor=seats * 1_000,
        status=status,
        subscription_id=scene["subscription_id"],
        seat_quantity=seats,
        paid_at=created_at + timedelta(minutes=5) if status is PaymentStatus.paid else None,
        created_at=created_at,
    )
    if applied and status is PaymentStatus.paid:
        with sm.begin() as session:
            session.execute(
                sa.update(Payment)
                .where(Payment.id == payment_id)
                .values(applied_at=created_at + timedelta(minutes=5))
            )
    return payment_id


def _notices(sm: sessionmaker[Session], recipient: uuid.UUID) -> list[EmailOutbox]:
    with sm() as session:
        return list(
            session.scalars(
                sa.select(EmailOutbox).where(
                    EmailOutbox.recipient_user_id == recipient,
                    EmailOutbox.template == "extra_seats_charge_failed",
                )
            )
        )


def _deliver(sm: sessionmaker[Session], payment: Payment, *, at: datetime) -> None:
    assert payment.paymob_order_id is not None
    obj = moto_txn(
        order_id=payment.paymob_order_id,
        merchant_order_id=str(payment.id),
        amount_cents=payment.amount_minor,
        txn_id=next(_txn_ids),
    )
    with sm.begin() as session:
        BillingService(
            session, FakeMotoClient(), PAYMOB_SETTINGS, now=lambda: at
        ).apply_transaction_callback(obj)


def _declining() -> FakeMotoClient:
    client = FakeMotoClient()
    client.pay_response = dict(DECLINE)
    return client


def _alerts(logs: list[Any]) -> list[str]:
    return [log["event"] for log in logs if log.get("alert")]


def _upgraded_scene(
    sm: sessionmaker[Session],
    *,
    renewal: int,
    new_price: int = 40_000,
    stamped: bool = True,
    **kwargs: Any,
) -> dict[str, uuid.UUID]:
    """A scene whose subscription moved to a dearer tier after the renewal paid (an upgrade).

    ``stamped``: the renewal recorded the terms version it billed (``period.terms_version``);
    without it the period's terms are unknowable once the tier has changed.
    """
    scene = _scene(sm, renewal=renewal, **kwargs)
    if stamped:
        with sm.begin() as session:
            session.execute(
                sa.update(SubscriptionPeriod)
                .where(SubscriptionPeriod.id == scene["period_id"])
                .values(terms_version=1)
            )
    target = seed_tier(
        sm,
        audience=PlanAudience.teacher,
        price_minor=new_price,
        included_seats=2,
        extra_seat_price_minor=2_000,
    )
    _update_sub(sm, scene, plan_tier_id=target, terms_version=1)
    seed_payment_row(
        sm,
        payer_id=scene["payer_id"],
        beneficiary_id=scene["user_id"],
        purpose=PaymentPurpose.upgrade_proration,
        amount_minor=5_000,
        status=PaymentStatus.paid,
        subscription_id=scene["subscription_id"],
        plan_tier_id=target,
        paid_at=T0 + timedelta(hours=3),
        created_at=T0 + timedelta(hours=3),
    )
    return scene


def _raise_base_price(sm: sessionmaker[Session], tier_id: uuid.UUID, price: int) -> None:
    """An admin publishes terms v2 at ``price`` and moves the tier to it."""
    with sm.begin() as session:
        session.execute(
            sa.text(
                "INSERT INTO plan_tier_terms (plan_tier_id, terms_version, price_minor, "
                "extra_seat_price_minor, allowance_units, included_seats, seat_allowance_units) "
                "SELECT plan_tier_id, 2, :price, extra_seat_price_minor, allowance_units, "
                "included_seats, seat_allowance_units FROM plan_tier_terms "
                "WHERE plan_tier_id = :tier AND terms_version = 1"
            ),
            {"tier": tier_id, "price": price},
        )
        session.execute(
            sa.text("UPDATE plan_tiers SET price_minor = :price, terms_version = 2 WHERE id = :t"),
            {"t": tier_id, "price": price},
        )


# ---------------------------------------------------------------------------
# 1. The first run.
# ---------------------------------------------------------------------------


def test_one_run_queues_and_charges_the_uncovered_seats_once(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _scene(sm)
    client = FakeMotoClient()

    _run(sm, client)

    (attempt,) = _attempts(sm, scene)
    assert attempt.amount_minor == 4_000  # 34 000 for the plan and 2 seats, 30 000 charged
    assert attempt.seat_quantity == 2
    assert attempt.dedupe_key == _key(scene, 1)
    assert attempt.purpose is PaymentPurpose.extra_seats
    assert attempt.payer_user_id == scene["payer_id"]
    assert attempt.beneficiary_user_id == scene["user_id"]
    assert attempt.status is PaymentStatus.pending
    assert len(client.calls_to("pay_with_token")) == 1

    _run(sm, client, now=NOW + timedelta(minutes=5))

    assert len(_attempts(sm, scene)) == 1
    assert len(client.calls_to("pay_with_token")) == 1  # nothing was queued or charged again


@pytest.mark.parametrize(
    ("renewal", "amount", "quantity"),
    [
        (30_000, 4_000, 2),
        (32_000, 2_000, 1),
        (31_000, 3_000, None),  # not a whole number of seats
        (20_000, 4_000, 2),  # the gap is wider than the seats are worth: never more than the seats
    ],
)
def test_the_amount_is_the_seat_gap_capped_at_the_seats(
    pg_sessionmaker: sessionmaker[Session], renewal: int, amount: int, quantity: int | None
) -> None:
    sm = pg_sessionmaker
    scene = _scene(sm, renewal=renewal)

    _run(sm, FakeMotoClient())

    (attempt,) = _attempts(sm, scene)
    assert (attempt.amount_minor, attempt.seat_quantity) == (amount, quantity)


@pytest.mark.parametrize("renewal", [34_000, 40_000])
def test_seats_the_renewal_already_covers_are_not_charged(
    pg_sessionmaker: sessionmaker[Session], renewal: int
) -> None:
    sm = pg_sessionmaker
    scene = _scene(sm, renewal=renewal)
    client = FakeMotoClient()

    _run(sm, client)

    assert _attempts(sm, scene) == []
    assert client.calls_to("pay_with_token") == []


# ---------------------------------------------------------------------------
# 2. DV-3: the double-charge guards.
# ---------------------------------------------------------------------------


def test_nothing_is_queued_on_the_updatable_path_even_with_a_gap_in_the_stamp(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _scene(sm)  # the stamp (30 000) is 4 000 below what the plan now bills
    client = FakeMotoClient()

    _run(sm, client, settings=UPDATABLE)

    assert _attempts(sm, scene) == []
    assert client.calls_to("pay_with_token") == []


def test_the_first_period_is_never_charged_for_seats(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _scene(sm)
    with sm.begin() as session:  # the period is paid by the checkout, which carried the seats
        session.execute(
            sa.update(SubscriptionPeriod)
            .where(SubscriptionPeriod.id == scene["period_id"])
            .values(payment_id=scene["payment_id"])
        )
        session.execute(
            sa.update(Payment).where(Payment.id == scene["payment_id"]).values(amount_minor=30_000)
        )
    client = FakeMotoClient()

    _run(sm, client)

    assert _attempts(sm, scene) == []
    assert client.calls_to("pay_with_token") == []


def test_a_paid_prorated_purchase_in_this_period_is_taken_off_the_amount(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _scene(sm)
    _seed_purchase(sm, scene, PaymentStatus.paid, created_at=T0 + timedelta(hours=2))

    _run(sm, FakeMotoClient())

    (attempt,) = _attempts(sm, scene)
    assert attempt.amount_minor == 2_000  # one of the two seats was paid for when it was bought


def test_a_purchase_from_an_earlier_period_is_not_taken_off_the_amount(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _scene(sm)
    _seed_purchase(sm, scene, PaymentStatus.paid, created_at=T0 - timedelta(days=3))

    _run(sm, FakeMotoClient())

    (attempt,) = _attempts(sm, scene)
    assert attempt.amount_minor == 4_000


@pytest.mark.parametrize(("renewal", "amount"), [(30_000, 4_000), (32_000, 2_000), (34_000, None)])
def test_an_upgrade_paid_this_period_does_not_change_the_seat_amount(
    pg_sessionmaker: sessionmaker[Session], renewal: int, amount: int | None
) -> None:
    # The upgrade moved the subscription to a 40 000 plan; the renewal was charged on the old one.
    # The seat gap is the renewal's own (period terms: 30 000 plus the seats), not the price gap
    # to the new plan and not what Paymob holds.
    sm = pg_sessionmaker
    scene = _upgraded_scene(sm, renewal=renewal)

    _run(sm, FakeMotoClient())

    attempts = _attempts(sm, scene)
    assert [a.amount_minor for a in attempts] == ([] if amount is None else [amount])


def test_an_admin_raising_the_base_price_leaves_the_seat_charge_unchanged(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    # The subscriber is billed on terms v1 until their renewal moves them; the tier now says 40 000.
    sm = pg_sessionmaker
    scene = _scene(sm, renewal=32_000)
    _raise_base_price(sm, scene["tier_id"], 40_000)

    _run(sm, FakeMotoClient())

    (attempt,) = _attempts(sm, scene)
    assert (
        attempt.amount_minor == 2_000
    )  # 34 000 under v1, 32 000 charged; the live tier says 8 000


def test_the_period_terms_win_over_the_terms_the_subscription_moved_to(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    # The period was billed on v1; the subscription has since moved to v2 (36 000).
    sm = pg_sessionmaker
    scene = _scene(sm, renewal=32_000)
    _raise_base_price(sm, scene["tier_id"], 36_000)
    _update_sub(sm, scene, terms_version=2)
    with sm.begin() as session:
        session.execute(
            sa.update(SubscriptionPeriod)
            .where(SubscriptionPeriod.id == scene["period_id"])
            .values(terms_version=1)
        )

    _run(sm, FakeMotoClient())

    (attempt,) = _attempts(sm, scene)
    assert attempt.amount_minor == 2_000  # v1: 34 000 - 32 000; v2 would say 8 000, capped to 4 000


@pytest.mark.parametrize(
    "change",
    [
        {"status": SubscriptionStatus.past_due},
        {"status": SubscriptionStatus.cancelled},
        {"paymob_subscription_id": None},
        {"extra_seats": 0},
    ],
)
def test_only_an_active_linked_plan_with_extra_seats_qualifies(
    pg_sessionmaker: sessionmaker[Session], change: dict[str, Any]
) -> None:
    sm = pg_sessionmaker
    scene = _scene(sm)
    _update_sub(sm, scene, **change)
    client = FakeMotoClient()

    _run(sm, client)

    assert _attempts(sm, scene) == []
    assert client.calls_to("pay_with_token") == []


def test_a_student_plan_never_qualifies(pg_sessionmaker: sessionmaker[Session]) -> None:
    sm = pg_sessionmaker
    scene = _scene(sm)
    student_tier = seed_tier(sm, audience=PlanAudience.student, price_minor=30_000)
    _update_sub(sm, scene, plan_tier_id=student_tier, terms_version=1)

    _run(sm, FakeMotoClient())

    assert _attempts(sm, scene) == []


# ---------------------------------------------------------------------------
# 2b. A1 / DV-27: a seat purchase checkout that may still be paid.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", [PaymentStatus.created, PaymentStatus.pending])
def test_an_open_seat_checkout_defers_the_first_attempt(
    pg_sessionmaker: sessionmaker[Session], status: PaymentStatus
) -> None:
    sm = pg_sessionmaker
    scene = _scene(sm)
    _seed_purchase(sm, scene, status, created_at=NOW - timedelta(minutes=10))
    client = FakeMotoClient()

    _run(sm, client)

    assert _attempts(sm, scene) == []
    assert client.calls_to("pay_with_token") == []


def test_the_deferral_ends_once_the_checkout_can_no_longer_be_paid(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    window = timedelta(seconds=INTENTION_EXPIRATION_SECONDS) + RECONCILE_AFTER
    young = _scene(sm)
    _seed_purchase(sm, young, PaymentStatus.created, created_at=NOW - window + timedelta(minutes=1))
    old = _scene(sm)
    _seed_purchase(sm, old, PaymentStatus.created, created_at=NOW - window)
    gone = _scene(sm)
    _seed_purchase(sm, gone, PaymentStatus.failed, created_at=NOW - timedelta(minutes=10))

    _run(sm, FakeMotoClient())

    assert _attempts(sm, young) == []
    # An abandoned checkout never reduces the amount: only a paid one does.
    assert [a.amount_minor for a in _attempts(sm, old)] == [4_000]
    assert [a.amount_minor for a in _attempts(sm, gone)] == [4_000]


def test_a_deferred_attempt_is_queued_by_a_later_run(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _scene(sm)
    window = timedelta(seconds=INTENTION_EXPIRATION_SECONDS) + RECONCILE_AFTER
    _seed_purchase(sm, scene, PaymentStatus.created, created_at=NOW - timedelta(minutes=10))
    client = FakeMotoClient()

    _run(sm, client)
    assert _attempts(sm, scene) == []
    _run(sm, client, now=NOW + window)

    assert [a.amount_minor for a in _attempts(sm, scene)] == [4_000]


# ---------------------------------------------------------------------------
# 3. A decline: grace, one email, daily retries.
# ---------------------------------------------------------------------------


def test_a_decline_starts_the_grace_and_one_email_then_retries_daily_up_to_three_attempts(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _scene(sm)
    client = _declining()

    _run(sm, client)  # attempt 1, declined, sent at NOW
    (first,) = _attempts(sm, scene)
    assert first.status is PaymentStatus.failed
    assert _sub(sm, scene).extra_seat_grace_until is None  # the grace starts on the next look

    _run(sm, client, now=NOW + timedelta(hours=1))
    after = _sub(sm, scene)
    # The grace runs from when the failure is seen, for ``grace_days`` (3 by default).
    assert after.extra_seat_grace_until == NOW + timedelta(hours=1, days=3)
    assert after.extra_seat_grace_payment_id == first.id
    (notice,) = _notices(sm, scene["payer_id"])
    assert notice.dedupe_key == f"extra_seats_failed:{first.id}"
    assert notice.context["grace_days"] == 3
    assert len(_attempts(sm, scene)) == 1

    # Many runs inside the first day: no retry.
    for hours in (2, 6, 12, 23):
        _run(sm, client, now=NOW + timedelta(hours=hours))
    assert len(_attempts(sm, scene)) == 1

    # Day 1: attempt 2. Several runs the same day add nothing.
    for minutes in (0, 5, 30):
        _run(sm, client, now=NOW + SEAT_RETRY_INTERVAL + timedelta(minutes=minutes))
    assert [a.dedupe_key for a in _attempts(sm, scene)] == [_key(scene, 1), _key(scene, 2)]

    # Day 2: attempt 3, the last.
    for minutes in (0, 5):
        _run(sm, client, now=NOW + 2 * SEAT_RETRY_INTERVAL + timedelta(minutes=minutes))
    assert [a.dedupe_key for a in _attempts(sm, scene)] == [_key(scene, n) for n in (1, 2, 3)]
    assert len(client.calls_to("pay_with_token")) == 3
    sent = [a.sent_at for a in _attempts(sm, scene)]
    assert all(b - a >= SEAT_RETRY_INTERVAL for a, b in itertools.pairwise(sent))  # type: ignore[operator]

    # No fourth attempt; the grace ends and the seats drop; the email went out once in total.
    _run(sm, client, now=NOW + timedelta(days=2, hours=23))
    assert len(_attempts(sm, scene)) == 3
    _run(sm, client, now=NOW + timedelta(days=3, hours=1))
    assert len(_attempts(sm, scene)) == 3
    assert len(client.calls_to("pay_with_token")) == 3
    assert _sub(sm, scene).extra_seats == 0
    assert len(_notices(sm, scene["payer_id"])) == 1


def _set_grace_days(sm: sessionmaker[Session], days: int) -> None:
    with sm.begin() as session:
        session.execute(sa.update(BillingSettings).values(grace_days=days))


def test_the_grace_and_the_attempts_follow_the_billing_setting(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    _set_grace_days(sm, 2)
    try:
        scene = _scene(sm)
        client = _declining()
        _run(sm, client)
        _run(sm, client, now=NOW + timedelta(hours=1))
        assert _sub(sm, scene).extra_seat_grace_until == NOW + timedelta(hours=1, days=2)
        (notice,) = _notices(sm, scene["payer_id"])
        assert notice.context["grace_days"] == 2
        _run(sm, client, now=NOW + SEAT_RETRY_INTERVAL)
        _run(sm, client, now=NOW + SEAT_RETRY_INTERVAL + timedelta(hours=2))
        assert len(_attempts(sm, scene)) == 2  # two days, two attempts
        _run(sm, client, now=NOW + timedelta(days=2, hours=1))
        assert _sub(sm, scene).extra_seats == 0
    finally:
        _set_grace_days(sm, 3)


@pytest.mark.parametrize("new_days", [7, 1])
def test_an_admin_changing_grace_days_mid_grace_changes_nothing_for_a_running_grace(
    pg_sessionmaker: sessionmaker[Session], new_days: int
) -> None:
    sm = pg_sessionmaker
    scene = _scene(sm)
    client = _declining()
    _run(sm, client)
    _run(sm, client, now=NOW + timedelta(hours=1))  # a 3 day grace starts
    _set_grace_days(sm, new_days)
    try:
        for minutes in (5, 10, 15, 20):  # minutes later: no burst, whatever the new setting
            _run(sm, client, now=NOW + timedelta(hours=1, minutes=minutes))
        assert len(client.calls_to("pay_with_token")) == 1
        for offset in (SEAT_RETRY_INTERVAL, 2 * SEAT_RETRY_INTERVAL, timedelta(days=2, hours=22)):
            _run(sm, client, now=NOW + offset)
        # The cap of this grace is the 3 it started with: not 7, and not 1.
        assert len(_attempts(sm, scene)) == 3
        assert len(client.calls_to("pay_with_token")) == 3
        assert _sub(sm, scene).extra_seat_grace_until == NOW + timedelta(hours=1, days=3)
    finally:
        _set_grace_days(sm, 3)


def test_a_missed_day_makes_a_late_retry_not_a_burst(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _scene(sm)
    client = _declining()
    _run(sm, client)
    _run(sm, client, now=NOW + timedelta(hours=1))
    late = NOW + timedelta(days=2, hours=1)  # the job was down for a day

    _run(sm, client, now=late)
    _run(sm, client, now=late + timedelta(minutes=5))

    attempts = _attempts(sm, scene)
    assert len(attempts) == 2
    assert len(client.calls_to("pay_with_token")) == 2
    assert attempts[1].sent_at == late
    _run(sm, client, now=NOW + timedelta(days=3, hours=1))  # the grace is over: drop, not attempt 3
    assert len(_attempts(sm, scene)) == 2
    assert _sub(sm, scene).extra_seats == 0


def test_the_row_logic_itself_refuses_a_retry_inside_the_interval(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    # The candidate query keeps a row away until its retry is due; the row logic must hold too,
    # for any other way a row gets visited (a queued sibling, a direct call).
    sm = pg_sessionmaker
    scene = _scene(sm)
    client = _declining()
    _run(sm, client)
    _run(sm, client, now=NOW + timedelta(hours=1))

    with sm.begin() as session:
        changed = repo._process_seat_row(
            session, scene["subscription_id"], fallback=True, now=NOW + timedelta(hours=2)
        )

    assert changed is False
    assert len(_attempts(sm, scene)) == 1


def test_a_missing_grace_setting_fails_closed_with_one_alert_for_the_run(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scenes = [_scene(sm) for _ in range(3)]
    client = FakeMotoClient()
    with sm.begin() as session:
        session.execute(
            sa.text("CREATE TABLE billing_settings_bak AS SELECT * FROM billing_settings")
        )
        session.execute(sa.delete(BillingSettings))
    try:
        with capture_logs() as logs:
            _run(sm, client)
    finally:
        with sm.begin() as session:
            session.execute(
                sa.text("INSERT INTO billing_settings SELECT * FROM billing_settings_bak")
            )
            session.execute(sa.text("DROP TABLE billing_settings_bak"))

    assert all(_attempts(sm, scene) == [] for scene in scenes)
    assert client.calls_to("pay_with_token") == []
    assert _alerts(logs) == ["seat_grace_setting_missing"]  # once, not once per row


@pytest.mark.parametrize("days", [1, 2, 3, 7])
def test_the_email_copy_follows_the_grace_the_failure_started(days: int) -> None:
    lead = ExtraSeatsChargeFailed(subscription_id=uuid.uuid4(), grace_days=days).lead()
    assert f"within {days} day" in lead
    assert ("each day" in lead) == (days > 1)  # one day of grace leaves no time to retry
    assert "extra seats are removed" in lead
    assert timedelta(days=1) == SEAT_RETRY_INTERVAL


def test_a_retry_is_not_queued_on_the_updatable_path_but_the_drop_still_runs(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _scene(sm, seats=4)
    first = _seed_attempt(
        sm,
        scene,
        1,
        PaymentStatus.failed,
        created_at=NOW - timedelta(days=1),
        sent_at=NOW - timedelta(days=1),
    )
    _update_sub(
        sm,
        scene,
        extra_seat_grace_until=NOW + timedelta(days=2),
        extra_seat_grace_payment_id=first,
    )

    _run(sm, FakeMotoClient(), settings=UPDATABLE, now=NOW + timedelta(days=1, hours=1))
    assert len(_attempts(sm, scene)) == 1  # a retry was due, none was queued

    _run(sm, FakeMotoClient(), settings=UPDATABLE, now=NOW + timedelta(days=2))
    assert _sub(sm, scene).extra_seats == 0  # but the grace still ends in a drop


# ---------------------------------------------------------------------------
# 4. An unknown outcome blocks the retry, and the drop.
# ---------------------------------------------------------------------------


def _accepted_retry(
    sm: sessionmaker[Session], scene: Mapping[str, uuid.UUID]
) -> tuple[FakeMotoClient, Payment]:
    """Attempt 1 declined, a 3 day grace started, attempt 2 sent a day later and left pending."""
    declined = _declining()
    _run(sm, declined)
    _run(sm, declined, now=NOW + timedelta(hours=1))
    unknown = FakeMotoClient()  # accepted by Paymob, answer not final: the attempt stays pending
    _run(sm, unknown, now=NOW + SEAT_RETRY_INTERVAL)
    second = _attempts(sm, scene)[1]
    assert second.status is PaymentStatus.pending
    return unknown, second


def test_a_retry_whose_outcome_is_unknown_blocks_the_next_retry(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _scene(sm)
    unknown, _ = _accepted_retry(sm, scene)

    for days in (2, 2.5):
        _run(sm, unknown, now=NOW + timedelta(days=days))
    attempts = _attempts(sm, scene)
    assert len(attempts) == 2  # attempt 3 was due and was not queued
    assert len(unknown.calls_to("pay_with_token")) == 1


def test_the_drop_waits_while_a_retry_is_pending_then_a_paid_retry_keeps_the_seats(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _scene(sm, seats=4)
    unknown, second = _accepted_retry(sm, scene)

    with capture_logs() as logs:
        _run(sm, unknown, now=NOW + timedelta(days=3, hours=2))  # the grace is over

    assert _sub(sm, scene).extra_seats == 2  # not dropped: the retry may have charged the card
    assert "extra_seats_dropped" not in _alerts(logs)
    _deliver(sm, second, at=NOW + timedelta(days=3, hours=2, minutes=5))

    after = _sub(sm, scene)
    assert (after.extra_seats, after.extra_seat_grace_until) == (2, None)
    assert _attempts(sm, scene)[1].grant_units is None  # it bought what it paid for: no credits


def test_the_drop_runs_once_the_pending_retry_has_failed(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _scene(sm, seats=4)
    unknown, second = _accepted_retry(sm, scene)
    _run(sm, unknown, now=NOW + timedelta(days=3, hours=2))
    assert _sub(sm, scene).extra_seats == 2
    with sm.begin() as session:  # reconcile gave up on it
        session.execute(
            sa.update(Payment).where(Payment.id == second.id).values(status=PaymentStatus.failed)
        )

    _run(sm, unknown, now=NOW + timedelta(days=3, hours=3))

    assert _sub(sm, scene).extra_seats == 0


# ---------------------------------------------------------------------------
# 5. A paid retry, through the real callback path.
# ---------------------------------------------------------------------------


def test_a_paid_retry_clears_the_grace_and_keeps_the_seats(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _scene(sm, seats=4)
    accepting, second = _accepted_retry(sm, scene)
    assert _sub(sm, scene).extra_seat_grace_until is not None
    retry_at = NOW + SEAT_RETRY_INTERVAL
    before = _sub(sm, scene)

    _deliver(sm, second, at=retry_at + timedelta(minutes=2))

    after = _sub(sm, scene)
    assert after.extra_seat_grace_until is None
    assert after.extra_seats == 2
    assert after.version == before.version + 1
    assert _attempts(sm, scene)[1].status is PaymentStatus.paid
    assert _attempts(sm, scene)[1].applied_at is not None  # R-M1: the grace branch stamps it

    _run(sm, accepting, now=NOW + timedelta(days=5))

    assert _sub(sm, scene).extra_seats == 2
    assert len(_attempts(sm, scene)) == 2
    assert len(accepting.calls_to("pay_with_token")) == 1
    with sm() as session:
        active = session.scalar(
            sa.select(sa.func.count())
            .select_from(TeacherMember)
            .where(
                TeacherMember.teacher_user_id == scene["teacher_id"],
                TeacherMember.status == TeacherMemberStatus.active,
            )
        )
    assert active == 4


def test_a_paid_attempt_with_no_grace_running_still_marks_the_seats_applied(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """R-M2: the fall-through (no grace, current period, seats held) is paid-and-applied.

    The money stands for seats the plan holds, so it is neither voided nor credited, and the
    ``applied_at`` marker says so (a reader that drops the ``dedupe_key`` filter sees it applied).
    """
    sm = pg_sessionmaker
    scene = _scene(sm, seats=4)
    attempt_id = _seed_attempt(sm, scene, 1, PaymentStatus.pending, with_order=True)
    attempt = _attempts(sm, scene)[0]
    assert attempt.id == attempt_id
    assert _sub(sm, scene).extra_seat_grace_until is None

    _deliver(sm, attempt, at=NOW + timedelta(minutes=2))

    paid = _attempts(sm, scene)[0]
    assert paid.status is PaymentStatus.paid
    assert paid.applied_at is not None
    assert paid.void_reason is None
    assert paid.grant_units is None
    assert _sub(sm, scene).extra_seats == 2


def test_an_unknown_void_reason_alerts_and_never_raises_inside_the_callback(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """R-N1: a raise would roll back a callback that already moved money, so it alerts instead."""
    sm = pg_sessionmaker
    scene = _scene(sm, seats=4)
    attempt_id = _seed_attempt(sm, scene, 1, PaymentStatus.paid)
    with sm.begin() as session:
        payment = session.get(Payment, attempt_id)
        sub = session.get(Subscription, scene["subscription_id"])
        assert payment is not None
        assert sub is not None
        with capture_logs() as logs:
            repo.credit_void_payment(session, payment, sub, reason="not_a_reason", paid_at=NOW)
        assert "merchant_charge_void_reason_unknown" in _alerts(logs)
        assert payment.void_reason is None
        assert payment.grant_units is None


# ---------------------------------------------------------------------------
# 6. The grace ends: the seats drop.
# ---------------------------------------------------------------------------


def _grace_expired_scene(sm: sessionmaker[Session]) -> tuple[dict[str, uuid.UUID], uuid.UUID]:
    scene = _scene(sm, seats=4)
    first = _seed_attempt(
        sm,
        scene,
        1,
        PaymentStatus.failed,
        created_at=NOW - timedelta(days=4),
        sent_at=NOW - timedelta(days=4),
    )
    _update_sub(
        sm,
        scene,
        extra_seat_grace_until=NOW - timedelta(hours=1),
        extra_seat_grace_payment_id=first,
        pending_extra_seats=1,
    )
    return scene, first


def test_an_elapsed_grace_drops_the_extra_seats_and_removes_the_newest_students(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene, first = _grace_expired_scene(sm)
    members = _seat_ids(sm, scene)
    with sm() as session:  # oldest first, by the ``created_at`` the scene gave each seat
        ordered = list(
            session.scalars(
                sa.select(TeacherMember.id)
                .where(TeacherMember.teacher_user_id == scene["teacher_id"])
                .order_by(TeacherMember.created_at, TeacherMember.id)
            )
        )
    assert sorted(ordered) == sorted(members)
    before = _sub(sm, scene)
    client = FakeMotoClient()

    with capture_logs() as logs:
        _run(sm, client)

    after = _sub(sm, scene)
    assert after.extra_seats == 0
    assert after.pending_extra_seats is None
    assert after.extra_seat_grace_until is None
    assert after.extra_seat_grace_payment_id == first  # the same failed period never starts another
    assert after.version == before.version + 1
    with sm() as session:
        status = {
            row.id: row.status
            for row in session.scalars(
                sa.select(TeacherMember).where(TeacherMember.teacher_user_id == scene["teacher_id"])
            )
        }
    assert [status[m] for m in ordered[:2]] == [TeacherMemberStatus.active] * 2
    assert [status[m] for m in ordered[2:]] == [TeacherMemberStatus.leaving] * 2
    assert "extra_seats_dropped" in _alerts(logs)
    dropped = next(log for log in logs if log["event"] == "extra_seats_dropped")
    assert dropped["subscription_id"] == str(scene["subscription_id"])
    assert dropped["extra_seats"] == 2
    assert dropped["members_removed"] == 2
    assert client.calls_to("pay_with_token") == []


def test_the_same_failed_period_never_starts_a_second_grace(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene, first = _grace_expired_scene(sm)
    client = FakeMotoClient()
    _run(sm, client)
    assert _sub(sm, scene).extra_seats == 0

    _run(sm, client, now=NOW + timedelta(days=1))  # the next day: nothing to do
    assert _sub(sm, scene).extra_seat_grace_until is None

    # The teacher buys the seats again in the same period, and the failed attempt is still the
    # period's only one: it must not open a second grace nor mail the payer again.
    _update_sub(sm, scene, extra_seats=2)
    _run(sm, client, now=NOW + timedelta(days=2))
    after = _sub(sm, scene)
    assert after.extra_seat_grace_until is None
    assert after.extra_seat_grace_payment_id == first
    assert _notices(sm, scene["payer_id"]) == []
    assert client.calls_to("pay_with_token") == []


def test_a_grace_that_has_not_elapsed_drops_nothing(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene, _ = _grace_expired_scene(sm)
    _update_sub(sm, scene, extra_seat_grace_until=NOW + timedelta(minutes=1))

    _run(sm, FakeMotoClient())

    assert _sub(sm, scene).extra_seats == 2


# ---------------------------------------------------------------------------
# 7. Two attempts paid (a late success, R20b).
# ---------------------------------------------------------------------------


def test_two_paid_attempts_alert_and_a_queued_third_is_failed_unsent(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _scene(sm)
    _seed_attempt(sm, scene, 1, PaymentStatus.paid)
    _seed_attempt(sm, scene, 2, PaymentStatus.paid)
    third = _seed_attempt(sm, scene, 3, PaymentStatus.created)
    client = FakeMotoClient()

    with capture_logs() as logs:
        _run(sm, client)

    assert "extra_seat_charge_duplicate" in _alerts(logs)
    rows = {row.id: row for row in _attempts(sm, scene)}
    assert rows[third].status is PaymentStatus.failed
    assert rows[third].last_callback == {"source": "pre_send", "reason": "superseded"}
    assert client.calls_to("pay_with_token") == []


def test_one_paid_attempt_supersedes_a_queued_one_without_an_alert(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _scene(sm)
    _seed_attempt(sm, scene, 1, PaymentStatus.paid)
    second = _seed_attempt(sm, scene, 2, PaymentStatus.created)
    client = FakeMotoClient()

    with capture_logs() as logs:
        _run(sm, client)

    assert _alerts(logs) == []
    assert {row.id: row.status for row in _attempts(sm, scene)}[second] is PaymentStatus.failed
    assert client.calls_to("pay_with_token") == []


# ---------------------------------------------------------------------------
# 8. Robustness.
# ---------------------------------------------------------------------------


def test_one_row_raising_does_not_stop_the_next(
    pg_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    sm = pg_sessionmaker
    bad = _scene(sm, start=T0 - timedelta(days=1), end=T0 + timedelta(days=29))
    good = _scene(sm)
    real = repo.renewal_seat_shortfall

    def flaky(session: Session, sub: Subscription, period: SubscriptionPeriod) -> int:
        if sub.id == bad["subscription_id"]:
            raise RuntimeError("boom")
        return real(session, sub, period)

    monkeypatch.setattr(repo, "renewal_seat_shortfall", flaky)

    with capture_logs() as logs:
        _run(sm, FakeMotoClient())

    assert _attempts(sm, bad) == []
    assert [a.amount_minor for a in _attempts(sm, good)] == [4_000]
    failed = [log for log in logs if log["event"] == "merchant_charge_sweep_failed"]
    assert [log["subscription_id"] for log in failed] == [str(bad["subscription_id"])]
    assert failed[0]["alert"] is True
    assert failed[0]["error_type"] == "RuntimeError"


def test_the_limit_bounds_the_batch(pg_sessionmaker: sessionmaker[Session]) -> None:
    sm = pg_sessionmaker
    scenes = [
        _scene(sm, start=T0 - timedelta(days=n), end=T0 + timedelta(days=30 - n)) for n in range(3)
    ]
    client = FakeMotoClient()

    _run(sm, client, limit=2)

    queued = [bool(_attempts(sm, scene)) for scene in scenes]
    assert queued == [False, True, True]  # oldest period first; the rest wait for the next run
    assert len(client.calls_to("pay_with_token")) == 2

    _run(sm, client, limit=2, now=NOW + timedelta(minutes=5))

    assert all(_attempts(sm, scene) for scene in scenes)


def test_a_row_locked_by_another_session_is_skipped(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    held = _scene(sm, start=T0 - timedelta(days=1), end=T0 + timedelta(days=29))
    free = _scene(sm)
    client = FakeMotoClient()
    locked = threading.Event()
    release = threading.Event()

    def hold() -> None:
        with sm.begin() as session:
            session.execute(
                sa.select(Subscription.id)
                .where(Subscription.id == held["subscription_id"])
                .with_for_update()
            )
            locked.set()
            release.wait(timeout=30)

    holder = threading.Thread(target=hold)
    holder.start()
    try:
        assert locked.wait(timeout=30)
        _run(sm, client)
    finally:
        release.set()
        holder.join(timeout=30)

    assert _attempts(sm, held) == []  # skipped, not waited for
    assert [a.amount_minor for a in _attempts(sm, free)] == [4_000]

    _run(sm, client, now=NOW + timedelta(minutes=5))

    assert [a.amount_minor for a in _attempts(sm, held)] == [4_000]


def test_rows_with_nothing_left_to_do_do_not_hold_a_place_in_the_batch(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    # A period whose seat charge was paid (or whose renewal covers the seats) stays "active with
    # extra seats" until it rolls; oldest first, such rows must not starve the ones that need work.
    sm = pg_sessionmaker
    for n in range(2):
        done = _scene(sm, start=T0 - timedelta(days=10 + n), end=T0 + timedelta(days=20 - n))
        if n == 0:  # a failed attempt, then a paid retry
            _seed_attempt(sm, done, 1, PaymentStatus.failed)
        _seed_attempt(sm, done, 2 - n, PaymentStatus.paid)
    covered = _scene(sm, renewal=34_000, start=T0 - timedelta(days=12), end=T0 + timedelta(days=18))
    needs = _scene(sm)

    _run(sm, FakeMotoClient(), limit=1)

    assert _attempts(sm, covered) == []
    assert [a.amount_minor for a in _attempts(sm, needs)] == [4_000]


# ---------------------------------------------------------------------------
# The drop: unsent retries, late successes and the callback race (review I1, I2).
# ---------------------------------------------------------------------------


def test_the_drop_fails_a_queued_retry_unsent_instead_of_charging_it(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene, _ = _grace_expired_scene(sm)
    queued = _seed_attempt(sm, scene, 2, PaymentStatus.created, created_at=NOW - timedelta(days=1))
    client = FakeMotoClient()

    _run(sm, client)

    assert _sub(sm, scene).extra_seats == 0
    row = {a.id: a for a in _attempts(sm, scene)}[queued]
    assert row.status is PaymentStatus.failed
    assert row.last_callback == {"source": "pre_send", "reason": "grace_ended"}
    assert client.calls_to("pay_with_token") == []  # the card is never charged for removed seats


def test_a_late_success_after_the_drop_becomes_credits_with_an_alert(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene, _ = _grace_expired_scene(sm)
    retry = _seed_attempt(sm, scene, 2, PaymentStatus.failed, with_order=True)
    _run(sm, FakeMotoClient())
    assert _sub(sm, scene).extra_seats == 0

    with capture_logs() as logs:
        _deliver(sm, {a.id: a for a in _attempts(sm, scene)}[retry], at=NOW + timedelta(hours=2))

    paid = {a.id: a for a in _attempts(sm, scene)}[retry]
    assert paid.status is PaymentStatus.paid
    assert paid.grant_units is not None  # the money is the teacher's credits, not Lemely's
    assert _sub(sm, scene).extra_seats == 0
    assert "renewal_seat_payment_credited" in _alerts(logs)
    credited = [
        g for g in grants_of(sm, scene["user_id"]) if g.idempotency_key == f"credited:{retry}"
    ]
    assert len(credited) == 1


def test_a_callback_racing_the_drop_waits_for_it_and_is_credited(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    # The job holds the subscription lock while it drops; a callback locks payment, then waits for
    # the subscription, so it can only read the seats after the drop committed.
    sm = pg_sessionmaker
    scene, _ = _grace_expired_scene(sm)
    retry = _seed_attempt(sm, scene, 2, PaymentStatus.failed, with_order=True)
    payment = {a.id: a for a in _attempts(sm, scene)}[retry]
    dropped = threading.Event()
    release = threading.Event()

    def drop() -> None:
        with sm() as session:
            repo._process_seat_row(session, scene["subscription_id"], fallback=True, now=NOW)
            dropped.set()
            release.wait(timeout=30)
            session.commit()

    callback = threading.Thread(target=lambda: _deliver(sm, payment, at=NOW + timedelta(hours=2)))
    dropper = threading.Thread(target=drop)
    with capture_logs() as logs:
        dropper.start()
        try:
            assert dropped.wait(timeout=30)
            callback.start()
            callback.join(timeout=1.5)
            assert callback.is_alive()  # it is waiting on the subscription lock
        finally:
            release.set()
            dropper.join(timeout=30)
            callback.join(timeout=30)

    assert _sub(sm, scene).extra_seats == 0
    assert {a.id: a for a in _attempts(sm, scene)}[retry].grant_units is not None
    assert "renewal_seat_payment_credited" in _alerts(logs)


def test_a_renewal_seat_payment_for_an_earlier_period_becomes_credits_with_an_alert(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _scene(sm)
    old = seed_payment_row(
        sm,
        payer_id=scene["payer_id"],
        beneficiary_id=scene["user_id"],
        purpose=PaymentPurpose.extra_seats,
        amount_minor=4_000,
        status=PaymentStatus.pending,
        subscription_id=scene["subscription_id"],
        seat_quantity=2,
        dedupe_key=f"{RENEWAL_SEAT_DEDUPE_PREFIX}{uuid.uuid4()}:1",
        paymob_order_id=next(_order_ids),
    )
    with sm() as session:
        payment = session.get(Payment, old)
        assert payment is not None

    with capture_logs() as logs:
        _deliver(sm, payment, at=NOW)

    assert "renewal_seat_payment_credited" in _alerts(logs)
    with sm() as session:
        assert session.get(Payment, old).grant_units is not None  # type: ignore[union-attr]
    assert _sub(sm, scene).extra_seats == 2


# ---------------------------------------------------------------------------
# One period's grace is never touched by another period (review M5).
# ---------------------------------------------------------------------------


def _old_period_grace(sm: sessionmaker[Session], scene: Mapping[str, uuid.UUID]) -> uuid.UUID:
    """A grace running since an earlier period's failed attempt; returns that payment's id."""
    old = seed_payment_row(
        sm,
        payer_id=scene["payer_id"],
        beneficiary_id=scene["user_id"],
        purpose=PaymentPurpose.extra_seats,
        amount_minor=4_000,
        status=PaymentStatus.failed,
        subscription_id=scene["subscription_id"],
        seat_quantity=2,
        dedupe_key=f"{RENEWAL_SEAT_DEDUPE_PREFIX}{uuid.uuid4()}:1",
    )
    _update_sub(
        sm,
        scene,
        extra_seat_grace_until=NOW + timedelta(days=2),
        extra_seat_grace_payment_id=old,
    )
    return old


def test_a_new_periods_failure_does_not_restart_the_old_periods_grace(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _scene(sm)
    old = _old_period_grace(sm, scene)
    _seed_attempt(sm, scene, 1, PaymentStatus.failed, sent_at=NOW)

    _run(sm, FakeMotoClient(), now=NOW + timedelta(days=1, hours=1))

    after = _sub(sm, scene)
    assert after.extra_seat_grace_until == NOW + timedelta(days=2)
    assert after.extra_seat_grace_payment_id == old
    assert _notices(sm, scene["payer_id"]) == []


def test_a_new_periods_paid_attempt_does_not_clear_the_old_periods_grace(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _scene(sm)
    old = _old_period_grace(sm, scene)
    current = _seed_attempt(sm, scene, 1, PaymentStatus.pending, with_order=True)
    payment = {a.id: a for a in _attempts(sm, scene)}[current]

    _deliver(sm, payment, at=NOW)

    after = _sub(sm, scene)
    assert after.extra_seat_grace_until == NOW + timedelta(days=2)
    assert after.extra_seat_grace_payment_id == old
    assert after.extra_seats == 2
    assert {a.id: a for a in _attempts(sm, scene)}[current].grant_units is None


# ---------------------------------------------------------------------------
# Review I3, M1, M2: who is visited, unknown terms, converted purchases.
# ---------------------------------------------------------------------------


def test_rows_that_owe_nothing_after_a_paid_purchase_do_not_starve_a_due_drop(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    covered = _scene(sm, start=T0 - timedelta(days=5), end=T0 + timedelta(days=25))
    _seed_purchase(sm, covered, PaymentStatus.paid, seats=2, created_at=T0 - timedelta(days=4))
    due, _ = _grace_expired_scene(sm)

    for n in range(3):
        _run(sm, FakeMotoClient(), limit=1, now=NOW + timedelta(hours=n))

    assert _attempts(sm, covered) == []
    assert _sub(sm, due).extra_seats == 0  # the drop ran: the covered row held no place


def test_a_period_whose_terms_cannot_be_known_owes_nothing_and_alerts(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _upgraded_scene(sm, renewal=30_000, stamped=False)
    client = FakeMotoClient()

    with capture_logs() as logs:
        _run(sm, client)

    assert _attempts(sm, scene) == []
    assert client.calls_to("pay_with_token") == []
    assert "extra_seat_terms_unknown" in _alerts(logs)


def test_a_purchase_converted_to_credits_does_not_reduce_the_seat_charge(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _scene(sm)
    purchase = _seed_purchase(
        sm, scene, PaymentStatus.paid, seats=1, created_at=T0 + timedelta(hours=1), applied=False
    )
    with sm.begin() as session:  # it added no seats: its money became credits
        session.execute(sa.update(Payment).where(Payment.id == purchase).values(grant_units=1_000))

    _run(sm, FakeMotoClient())

    (attempt,) = _attempts(sm, scene)
    assert attempt.amount_minor == 4_000


def test_a_purchase_voided_without_a_credit_rate_does_not_reduce_the_seat_charge(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """Paid, never applied, never converted (no rate): it added no seats, so the renewal still
    charges for them, and the sweep still visits the row. Counting it as bought under-collects by
    its quantity times the seat price: here the whole 4 000 (review I1, point 5)."""
    sm = pg_sessionmaker
    scene = _scene(sm)
    _seed_purchase(
        sm, scene, PaymentStatus.paid, seats=2, created_at=T0 + timedelta(hours=1), applied=False
    )

    _run(sm, FakeMotoClient())

    (attempt,) = _attempts(sm, scene)
    assert attempt.amount_minor == 4_000


# ---------------------------------------------------------------------------
# Re-review N-I1, N-M1..M5.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("days", "outage"),
    [(3, timedelta(days=3, hours=1)), (1, timedelta(days=1, hours=1))],
)
def test_a_grace_never_starts_with_its_deadline_already_passed(
    pg_sessionmaker: sessionmaker[Session], days: int, outage: timedelta
) -> None:
    # The job was down for the grace length after attempt 1 was declined. The grace starts when the
    # failure is seen, so the customer still gets a whole grace, and a retry, before the drop.
    sm = pg_sessionmaker
    _set_grace_days(sm, days)
    try:
        scene = _scene(sm)
        client = _declining()
        _run(sm, client)
        back = NOW + outage

        _run(sm, client, now=back)
        assert _sub(sm, scene).extra_seat_grace_until == back + timedelta(days=days)
        assert len(_notices(sm, scene["payer_id"])) == 1

        _run(sm, client, now=back + timedelta(minutes=5))  # the very next run
        assert _sub(sm, scene).extra_seats == 2  # not dropped
        assert len(_attempts(sm, scene)) == 2  # and the retry the email promised was made
        assert len(client.calls_to("pay_with_token")) == 2

        _run(sm, client, now=back + timedelta(days=days))
        assert _sub(sm, scene).extra_seats == 0
    finally:
        _set_grace_days(sm, 3)


def test_a_late_success_after_a_drop_and_a_re_purchase_is_still_credited(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene, _ = _grace_expired_scene(sm)
    retry = _seed_attempt(sm, scene, 2, PaymentStatus.failed, with_order=True)
    _run(sm, FakeMotoClient())
    assert _sub(sm, scene).extra_seats == 0
    _update_sub(sm, scene, extra_seats=1)  # the teacher bought a seat back after the drop

    with capture_logs() as logs:
        _deliver(sm, {a.id: a for a in _attempts(sm, scene)}[retry], at=NOW + timedelta(hours=2))

    assert {a.id: a for a in _attempts(sm, scene)}[retry].grant_units is not None
    assert _sub(sm, scene).extra_seats == 1
    assert "renewal_seat_payment_credited" in _alerts(logs)


def test_unknown_terms_alert_once_per_period_and_hold_no_place_in_the_batch(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    unknown = _upgraded_scene(
        sm, renewal=30_000, stamped=False, start=T0 - timedelta(days=5), end=T0 + timedelta(days=25)
    )
    due, _ = _grace_expired_scene(sm)

    with capture_logs() as logs:
        for minutes in (0, 5, 10, 15):
            _run(sm, FakeMotoClient(), limit=1, now=NOW + timedelta(minutes=minutes))

    assert _alerts(logs).count("extra_seat_terms_unknown") == 1  # once, not once per run
    assert _attempts(sm, unknown) == []
    assert _sub(sm, due).extra_seats == 0  # the drop was not starved by the unknown row


def test_an_earlier_periods_retry_paid_after_the_roll_ends_that_periods_grace(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _scene(sm)
    old_period = uuid.uuid4()
    first = seed_payment_row(
        sm,
        payer_id=scene["payer_id"],
        beneficiary_id=scene["user_id"],
        purpose=PaymentPurpose.extra_seats,
        amount_minor=4_000,
        status=PaymentStatus.failed,
        subscription_id=scene["subscription_id"],
        seat_quantity=2,
        dedupe_key=f"{RENEWAL_SEAT_DEDUPE_PREFIX}{old_period}:1",
    )
    retry = seed_payment_row(
        sm,
        payer_id=scene["payer_id"],
        beneficiary_id=scene["user_id"],
        purpose=PaymentPurpose.extra_seats,
        amount_minor=4_000,
        status=PaymentStatus.pending,
        subscription_id=scene["subscription_id"],
        seat_quantity=2,
        dedupe_key=f"{RENEWAL_SEAT_DEDUPE_PREFIX}{old_period}:2",
        paymob_order_id=next(_order_ids),
    )
    _update_sub(
        sm,
        scene,
        extra_seat_grace_until=NOW + timedelta(days=1),
        extra_seat_grace_payment_id=first,
    )
    with sm() as session:
        payment = session.get(Payment, retry)
        assert payment is not None

    _deliver(sm, payment, at=NOW)  # the old period's retry succeeds after the roll

    after = _sub(sm, scene)
    assert after.extra_seat_grace_until is None  # that period's debt is paid
    with sm() as session:
        paid = session.get(Payment, retry)
        assert paid is not None
        assert paid.status is PaymentStatus.paid
        assert paid.grant_units is None  # the seats were held for that period: the money stands
    _run(sm, FakeMotoClient(), now=NOW + timedelta(days=1, minutes=1))
    assert _sub(sm, scene).extra_seats == 2  # and the seats are not dropped


def test_a_retry_that_failed_unsent_also_spaces_the_next_attempt(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _scene(sm)
    first = _seed_attempt(sm, scene, 1, PaymentStatus.failed, created_at=NOW, sent_at=NOW)
    _update_sub(
        sm,
        scene,
        extra_seat_grace_until=NOW + timedelta(days=3),
        extra_seat_grace_payment_id=first,
    )
    # Attempt 2 was queued on day 1 and failed before it was sent (no card at that moment).
    _seed_attempt(sm, scene, 2, PaymentStatus.failed, created_at=NOW + timedelta(days=1))

    with sm.begin() as session:
        changed = repo._process_seat_row(
            session, scene["subscription_id"], fallback=True, now=NOW + timedelta(days=1, minutes=5)
        )

    assert changed is False
    assert len(_attempts(sm, scene)) == 2  # the last retry is not burnt minutes later


def test_a_drop_deferred_on_an_unresolved_attempt_alerts_once_after_a_day(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene, _ = _grace_expired_scene(sm)  # the grace ended at NOW - 1h
    _seed_attempt(sm, scene, 2, PaymentStatus.pending, sent_at=NOW - timedelta(days=2))
    client = FakeMotoClient()

    with capture_logs() as early:
        _run(sm, client, now=NOW + timedelta(hours=20))  # 21h past the deadline
    with capture_logs() as late:
        _run(sm, client, now=NOW + timedelta(days=1))  # 25h past it
        _run(sm, client, now=NOW + timedelta(days=2))

    assert "extra_seats_drop_stuck" not in _alerts(early)
    assert _alerts(late) == ["extra_seats_drop_stuck"]  # once
    assert _sub(sm, scene).extra_seats == 2  # still waiting for the outcome


# ---------------------------------------------------------------------------
# The public helpers.
# ---------------------------------------------------------------------------


def test_the_shortfall_and_the_queue_helper_agree_with_the_job(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _scene(sm)
    with sm.begin() as session:
        sub = session.get(Subscription, scene["subscription_id"])
        assert sub is not None
        period = current_period(session, sub)
        assert period is not None
        assert renewal_seat_shortfall(session, sub, period) == 4_000
        payment = queue_renewal_seat_charge(session, sub, period, now=NOW)
        assert payment is not None
        assert (payment.amount_minor, payment.dedupe_key) == (4_000, _key(scene, 1))
        assert queue_renewal_seat_charge(session, sub, period, now=NOW) is None  # one per key


def test_phase05_is_untouched_outside_next_renewal_amount() -> None:
    source = Path(subscription_repo.__file__).read_text(encoding="utf-8")
    assert "queue_renewal_seat_charge" not in source
