"""Extra seats through a 3DS checkout, the seats quote, seat reduction and capacity (Phase 06 T5).

Money safety, in the order the code enforces it: every refusal happens before a payment row is
written or Paymob is called; the checkout is Phase 02's on the card (Normal 3DS) integration;
an abandoned ``created`` checkout never blocks a new one but a ``pending`` one does; only the
verified callback adds seats; a payment whose effect is void at settle time (the plan ended, the
period rolled, a reduction or grace started, the price or seat ceiling moved) becomes credits; a
seat reduction lowers the usable capacity at once and cannot be walked back after an upgrade that
priced the lower seat count. Every guard has a mutation proof in the task report.

Runs on a throwaway Postgres database (``create_all``); skips without a local Postgres.
"""

from __future__ import annotations

import itertools
import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest
import sqlalchemy as sa
from structlog.testing import capture_logs

from lemely.db.billing_repo import (
    BillingService,
    CheckoutUnavailable,
    PhoneRequired,
    paid_handler_for,
)
from lemely.db.merchant_charge_repo import (
    MAX_SEATS_PER_PURCHASE,
    RENEWAL_SEAT_DEDUPE_PREFIX,
    ChargeQuote,
    MerchantChargeError,
    MerchantChargeService,
    handle_extra_seats_paid,
)
from lemely.db.models.billing import (
    Payment,
    PaymentPurpose,
    PaymentStatus,
    PlanAudience,
    Subscription,
)
from lemely.db.models.billing_ops import CreditConversionRate
from lemely.db.models.enums import Role, SubscriptionStatus
from lemely.db.models.team import TeacherMember, TeacherMemberStatus
from lemely.db.models.tutoring import EmailOutbox
from lemely.db.models.usage import UsageGrant
from lemely.db.teacher_team_repo import NoFreeSeat, TeacherTeamService
from lemely.io.paymob.client import PaymobError
from tests.merchant_charge_fixtures import (
    moto_txn,
    seed_payment_row,
    seed_seat,
    seed_tier,
    seed_user,
    student_with_plan,
    teacher_with_plan,
    throwaway_database,
)
from tests.paymob_fixtures import (
    CARD_INTEGRATION_ID,
    INTENTION_RESPONSE,
    MOTO_INTEGRATION_ID,
    PAYMOB_SETTINGS,
    transaction_obj,
)
from tests.subscription_fixtures import T0, FakePaymobClient, grants_of, paymob_settings
from tests.team_db import add_assistant, add_class, enrol

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

#: Half the period is left: 30 days from ``T0``.
NOW = T0 + timedelta(days=15)
PERIOD_END = T0 + timedelta(days=30)
_order_ids = itertools.count(770_001)
_txn_ids = itertools.count(6_600_001)


class _CheckoutClient(FakePaymobClient):
    """Subscription fixtures' recording fake whose intention accepts ``sensitive`` and mints ids.

    ``names()`` lists only subscription calls, so an empty list after a settle proves the paid
    handler wrote nothing to Paymob (DV-1).
    """

    def __init__(self, settings: Any = PAYMOB_SETTINGS) -> None:
        super().__init__(settings)
        self.sensitive: list[tuple[str, ...]] = []

    def create_intention(  # type: ignore[override]
        self, body: Mapping[str, object], *, sensitive: Sequence[str] = ()
    ) -> dict[str, Any]:
        self.sensitive.append(tuple(sensitive))
        self.intentions.append(dict(body))
        if self.on_intention is not None:
            self.on_intention(dict(body))
        if isinstance(self.intention_response, Exception):
            raise self.intention_response
        response = dict(self.intention_response)
        response["intention_order_id"] = next(_order_ids)
        response["id"] = f"pi_test_seat_{next(_order_ids)}"
        return response


@pytest.fixture(scope="module")
def pg_sessionmaker() -> Iterator[sessionmaker[Session]]:
    with throwaway_database() as factory:
        with factory.begin() as session:
            session.add(CreditConversionRate(currency="EGP", units_per_minor=Decimal("0.01")))
        yield factory


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def _teacher(sm: sessionmaker[Session], **kwargs: Any) -> dict[str, uuid.UUID]:
    """A teacher paying 30 000 with 2 included and 1 extra seat at 2 000, half the period left."""
    options: dict[str, Any] = {"included": 2, "seat_price": 2_000, "price": 30_000, "extra": 1}
    options.update(kwargs)
    return teacher_with_plan(sm, **options)


def _buy(
    sm: sessionmaker[Session],
    client: _CheckoutClient,
    scene: Mapping[str, uuid.UUID],
    seats: int,
    *,
    actor: uuid.UUID | None = None,
    settings: Any = PAYMOB_SETTINGS,
    now: datetime = NOW,
) -> uuid.UUID:
    with sm() as session:
        result = MerchantChargeService(session, client, settings).start_extra_seats_checkout(
            subscription_id=scene["subscription_id"],
            actor_user_id=actor or scene["payer_id"],
            seats=seats,
            now=now,
        )
    return result.payment_id


def _quote(
    sm: sessionmaker[Session],
    client: _CheckoutClient,
    scene: Mapping[str, uuid.UUID],
    seats: int,
    *,
    actor: uuid.UUID | None = None,
    now: datetime = NOW,
) -> ChargeQuote:
    with sm() as session:
        return MerchantChargeService(session, client, PAYMOB_SETTINGS).quote_extra_seats(
            subscription_id=scene["subscription_id"],
            actor_user_id=actor or scene["payer_id"],
            seats=seats,
            now=now,
        )


def _reduce(
    sm: sessionmaker[Session],
    scene: Mapping[str, uuid.UUID],
    extra_seats: int,
    *,
    actor: uuid.UUID | None = None,
    settings: Any = PAYMOB_SETTINGS,
    client: _CheckoutClient | None = None,
) -> None:
    with sm.begin() as session:
        MerchantChargeService(
            session, client or _CheckoutClient(), settings
        ).schedule_seat_reduction(
            subscription_id=scene["subscription_id"],
            actor_user_id=actor or scene["payer_id"],
            extra_seats=extra_seats,
            now=NOW,
        )


def _payment(sm: sessionmaker[Session], payment_id: uuid.UUID) -> Payment:
    with sm() as session:
        row = session.get(Payment, payment_id)
        assert row is not None
        return row


def _sub(sm: sessionmaker[Session], scene: Mapping[str, uuid.UUID]) -> Subscription:
    with sm() as session:
        row = session.get(Subscription, scene["subscription_id"])
        assert row is not None
        return row


def _seat_payments(sm: sessionmaker[Session], scene: Mapping[str, uuid.UUID]) -> int:
    with sm() as session:
        return int(
            session.scalar(
                sa.select(sa.func.count())
                .select_from(Payment)
                .where(
                    Payment.subscription_id == scene["subscription_id"],
                    Payment.purpose == PaymentPurpose.extra_seats,
                )
            )
            or 0
        )


def _update_sub(sm: sessionmaker[Session], scene: Mapping[str, uuid.UUID], **values: Any) -> None:
    with sm.begin() as session:
        session.execute(
            sa.update(Subscription)
            .where(Subscription.id == scene["subscription_id"])
            .values(**values)
        )


def _txn(payment: Payment) -> dict[str, Any]:
    assert payment.paymob_order_id is not None
    return transaction_obj(
        txn_id=next(_txn_ids),
        order_id=payment.paymob_order_id,
        merchant_order_id=str(payment.id),
        amount_cents=payment.amount_minor,
    )


def _deliver(sm: sessionmaker[Session], obj: dict[str, Any], *, at: datetime = NOW) -> None:
    with sm.begin() as session:
        BillingService(
            session, _CheckoutClient(), PAYMOB_SETTINGS, now=lambda: at
        ).apply_transaction_callback(obj)


def _pay(sm: sessionmaker[Session], payment_id: uuid.UUID, *, at: datetime = NOW) -> None:
    _deliver(sm, _txn(_payment(sm, payment_id)), at=at)


def _grant(sm: sessionmaker[Session], owner: uuid.UUID, key: str) -> UsageGrant | None:
    return next((g for g in grants_of(sm, owner) if g.idempotency_key == key), None)


def _credited_notices(sm: sessionmaker[Session], recipient: uuid.UUID) -> int:
    with sm() as session:
        rows = session.scalars(
            sa.select(EmailOutbox).where(EmailOutbox.recipient_user_id == recipient)
        ).all()
    return sum(1 for row in rows if row.context.get("notice") == "credited")


def _credited_reasons(logs: list[Any]) -> list[str]:
    return [log["reason"] for log in logs if log["event"] == "merchant_charge_credited"]


def _refused(
    sm: sessionmaker[Session],
    client: _CheckoutClient,
    scene: Mapping[str, uuid.UUID],
    seats: int,
    code: str,
    **kwargs: Any,
) -> MerchantChargeError:
    """The checkout is refused with ``code``, leaving no payment row and no Paymob call."""
    before = _seat_payments(sm, scene)
    with pytest.raises(MerchantChargeError) as caught:
        _buy(sm, client, scene, seats, **kwargs)
    assert caught.value.code == code
    assert _seat_payments(sm, scene) == before
    assert client.intentions == []
    return caught.value


def _seat_tier(sm: sessionmaker[Session], *, price: int, seat_price: int) -> uuid.UUID:
    return seed_tier(
        sm,
        audience=PlanAudience.teacher,
        price_minor=price,
        allowance_units=2_000,
        included_seats=2,
        extra_seat_price_minor=seat_price,
    )


def _upgrade_checkout(
    sm: sessionmaker[Session],
    client: _CheckoutClient,
    scene: Mapping[str, uuid.UUID],
    target: uuid.UUID,
    *,
    now: datetime = NOW,
) -> uuid.UUID:
    with sm() as session:
        result = MerchantChargeService(session, client, PAYMOB_SETTINGS).start_upgrade_checkout(
            subscription_id=scene["subscription_id"],
            actor_user_id=scene["payer_id"],
            plan_tier_id=target,
            now=now,
        )
    return result.payment_id


# ---------------------------------------------------------------------------
# The checkout.
# ---------------------------------------------------------------------------


def test_the_checkout_records_the_payment_and_opens_a_card_integration_intention(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _teacher(sm)
    client = _CheckoutClient()

    payment_id = _buy(sm, client, scene, 2)

    payment = _payment(sm, payment_id)
    assert payment.purpose is PaymentPurpose.extra_seats
    assert payment.status is PaymentStatus.created
    assert payment.amount_minor == 2_000  # 2 seats x 2 000, half the period left
    assert payment.seat_quantity == 2
    assert payment.currency == "EGP"
    assert payment.subscription_id == scene["subscription_id"]
    assert payment.payer_user_id == scene["payer_id"]
    assert payment.beneficiary_user_id == scene["user_id"]
    assert payment.dedupe_key is None
    assert payment.created_at == NOW  # the injected clock, which the void-at-settle rules compare
    (body,) = client.intentions
    assert body["payment_methods"] == [CARD_INTEGRATION_ID]
    assert MOTO_INTEGRATION_ID not in body["payment_methods"]
    assert body["items"] == [{"name": "Extra student seats", "amount": 2_000, "quantity": 1}]
    assert body["amount"] == 2_000
    assert body["redirection_url"] == f"https://lemelyig.com/billing/return/{payment_id}"
    assert body["card_tokens"]  # the payer's saved card is offered
    assert len(client.sensitive[0]) == len(body["card_tokens"])
    assert _sub(sm, scene).extra_seats == 1  # nothing added before the callback


def test_a_teacher_with_no_saved_card_can_still_buy_seats(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _teacher(sm, card=False)
    client = _CheckoutClient()

    payment_id = _buy(sm, client, scene, 1)

    assert _payment(sm, payment_id).amount_minor == 1_000
    assert "card_tokens" not in client.intentions[0]


@pytest.mark.parametrize("seats", [0, -1, MAX_SEATS_PER_PURCHASE + 1])
def test_a_seat_count_outside_the_per_purchase_bound_is_refused_before_any_write(
    pg_sessionmaker: sessionmaker[Session], seats: int
) -> None:
    sm = pg_sessionmaker
    scene = _teacher(sm)
    _refused(sm, _CheckoutClient(), scene, seats, "invalid_seats")
    with pytest.raises(MerchantChargeError) as quoted:
        _quote(sm, _CheckoutClient(), scene, seats)
    assert quoted.value.code == "invalid_seats"


def test_a_purchase_past_the_total_seat_ceiling_is_refused(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _teacher(sm, extra=150)
    _refused(sm, _CheckoutClient(), scene, 51, "invalid_seats")  # 150 + 51 > 200
    assert _payment(sm, _buy(sm, _CheckoutClient(), scene, 50)).seat_quantity == 50


def test_a_student_plan_cannot_buy_seats(pg_sessionmaker: sessionmaker[Session]) -> None:
    sm = pg_sessionmaker
    scene = student_with_plan(sm)
    _refused(sm, _CheckoutClient(), scene, 1, "not_a_teacher_plan")
    with pytest.raises(MerchantChargeError) as quoted:
        _quote(sm, _CheckoutClient(), scene, 1)
    assert quoted.value.code == "not_a_teacher_plan"


def test_a_teacher_plan_that_sells_no_seats_cannot_buy_them(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _teacher(sm, seat_price=0, extra=0)
    _refused(sm, _CheckoutClient(), scene, 1, "not_a_teacher_plan")


def test_a_pending_reduction_blocks_a_purchase(pg_sessionmaker: sessionmaker[Session]) -> None:
    sm = pg_sessionmaker
    scene = _teacher(sm, extra=3, pending=1)
    _refused(sm, _CheckoutClient(), scene, 1, "seat_reduction_pending")


def test_an_overdue_seat_charge_blocks_a_purchase(pg_sessionmaker: sessionmaker[Session]) -> None:
    sm = pg_sessionmaker
    scene = _teacher(sm)
    _update_sub(sm, scene, extra_seat_grace_until=NOW + timedelta(days=3))
    _refused(sm, _CheckoutClient(), scene, 1, "seat_charge_overdue")


def test_a_past_due_plan_cannot_buy_seats(pg_sessionmaker: sessionmaker[Session]) -> None:
    sm = pg_sessionmaker
    scene = _teacher(sm)
    _update_sub(sm, scene, status=SubscriptionStatus.past_due)
    _refused(sm, _CheckoutClient(), scene, 1, "subscription_not_active")


def test_a_payer_without_a_phone_is_refused_before_any_write(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _teacher(sm)
    with sm.begin() as session:
        session.execute(
            sa.text("UPDATE users SET phone = NULL WHERE id = :u"), {"u": scene["payer_id"]}
        )
    client = _CheckoutClient()
    with pytest.raises(PhoneRequired):
        _buy(sm, client, scene, 1)
    assert _seat_payments(sm, scene) == 0
    assert client.intentions == []


@pytest.mark.parametrize("purpose", [PaymentPurpose.extra_seats, PaymentPurpose.upgrade_proration])
def test_a_pending_seat_or_upgrade_payment_blocks_a_purchase(
    pg_sessionmaker: sessionmaker[Session], purpose: PaymentPurpose
) -> None:
    sm = pg_sessionmaker
    scene = _teacher(sm)
    seed_payment_row(
        sm,
        payer_id=scene["payer_id"],
        beneficiary_id=scene["user_id"],
        purpose=purpose,
        amount_minor=1_000,
        status=PaymentStatus.pending,
        subscription_id=scene["subscription_id"],
        seat_quantity=1 if purpose is PaymentPurpose.extra_seats else None,
        plan_tier_id=scene["tier_id"] if purpose is PaymentPurpose.upgrade_proration else None,
    )
    seed_before = _seat_payments(sm, scene)
    client = _CheckoutClient()
    with pytest.raises(MerchantChargeError) as caught:
        _buy(sm, client, scene, 1)
    assert caught.value.code == "charge_in_flight"
    assert _seat_payments(sm, scene) == seed_before
    assert client.intentions == []


def test_an_abandoned_created_checkout_does_not_block_a_new_one(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _teacher(sm)
    first = _buy(sm, _CheckoutClient(), scene, 1)
    second = _buy(sm, _CheckoutClient(), scene, 1, now=NOW + timedelta(minutes=1))
    assert first != second
    assert _payment(sm, first).status is PaymentStatus.created
    assert _seat_payments(sm, scene) == 2


def test_the_period_ending_refuses_a_purchase(pg_sessionmaker: sessionmaker[Session]) -> None:
    sm = pg_sessionmaker
    scene = _teacher(sm)
    _refused(sm, _CheckoutClient(), scene, 1, "period_ending", now=PERIOD_END)


# ---------------------------------------------------------------------------
# IDOR: nobody but the payer.
# ---------------------------------------------------------------------------


def test_nobody_but_the_payer_can_buy_quote_or_reduce_seats(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _teacher(sm, extra=2)
    stranger = seed_user(sm, Role.teacher)
    assistant = seed_user(sm, Role.teacher)
    add_assistant(sm, teacher_id=scene["user_id"], assistant_id=assistant)

    outcomes: list[set[tuple[str, str]]] = []
    for actor in (stranger, assistant, uuid.uuid4()):
        seen: set[tuple[str, str]] = set()
        for call in (
            lambda a=actor: _buy(sm, _CheckoutClient(), scene, 1, actor=a),
            lambda a=actor: _quote(sm, _CheckoutClient(), scene, 1, actor=a),
            lambda a=actor: _reduce(sm, scene, 0, actor=a),
        ):
            with pytest.raises(MerchantChargeError) as caught:
                call()
            seen.add((caught.value.code, str(caught.value)))
        outcomes.append(seen)

    assert outcomes[0] == outcomes[1] == outcomes[2] == {("not_found", "Subscription not found")}
    unknown = uuid.uuid4()
    with sm() as session, pytest.raises(MerchantChargeError) as caught:
        MerchantChargeService(session, _CheckoutClient(), PAYMOB_SETTINGS).quote_extra_seats(
            subscription_id=unknown, actor_user_id=scene["payer_id"], seats=1, now=NOW
        )
    assert (caught.value.code, str(caught.value)) == ("not_found", "Subscription not found")
    assert _seat_payments(sm, scene) == 0
    assert _sub(sm, scene).pending_extra_seats is None


# ---------------------------------------------------------------------------
# Paymob outcomes at creation.
# ---------------------------------------------------------------------------


def test_an_unknown_outcome_at_creation_leaves_the_payment_created(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _teacher(sm)
    client = _CheckoutClient()
    client.intention_response = PaymobError("timed out", timeout=True)

    with pytest.raises(CheckoutUnavailable):
        _buy(sm, client, scene, 1)

    with sm() as session:
        [row] = session.scalars(
            sa.select(Payment).where(
                Payment.subscription_id == scene["subscription_id"],
                Payment.purpose == PaymentPurpose.extra_seats,
            )
        ).all()
    assert row.status is PaymentStatus.created  # reconcile settles it, never failed here
    assert row.next_reconcile_at is not None
    client.intention_response = dict(INTENTION_RESPONSE)
    assert _buy(sm, client, scene, 1, now=NOW + timedelta(minutes=1))  # a new one may start


def test_a_definite_refusal_fails_the_payment(pg_sessionmaker: sessionmaker[Session]) -> None:
    sm = pg_sessionmaker
    scene = _teacher(sm)
    client = _CheckoutClient()
    client.intention_response = PaymobError("bad request", status_code=400)

    with pytest.raises(CheckoutUnavailable):
        _buy(sm, client, scene, 1)

    with sm() as session:
        [row] = session.scalars(
            sa.select(Payment).where(
                Payment.subscription_id == scene["subscription_id"],
                Payment.purpose == PaymentPurpose.extra_seats,
            )
        ).all()
    assert row.status is PaymentStatus.failed


# ---------------------------------------------------------------------------
# The quote.
# ---------------------------------------------------------------------------


def test_the_quote_writes_nothing_calls_nobody_and_has_no_allowance(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _teacher(sm)
    client = _CheckoutClient()
    before = _sub(sm, scene)

    quote = _quote(sm, client, scene, 2)

    assert quote == ChargeQuote(
        amount_minor=2_000, currency="EGP", allowance_units=None, period_end=PERIOD_END
    )
    assert client.intentions == []
    assert client.names() == []
    assert _seat_payments(sm, scene) == 0
    after = _sub(sm, scene)
    assert (after.extra_seats, after.version) == (before.extra_seats, before.version)
    # The quote is the bill: the same planner prices the checkout.
    assert _payment(sm, _buy(sm, client, scene, 2)).amount_minor == quote.amount_minor


# ---------------------------------------------------------------------------
# The paid handler.
# ---------------------------------------------------------------------------


def test_the_handler_is_registered_for_extra_seats() -> None:
    assert paid_handler_for(PaymentPurpose.extra_seats) is handle_extra_seats_paid


def test_a_paid_purchase_adds_the_seats_once_through_the_real_callback_path(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _teacher(sm)
    client = _CheckoutClient()
    payment_id = _buy(sm, client, scene, 2)
    before = _sub(sm, scene)
    obj = _txn(_payment(sm, payment_id))

    _deliver(sm, obj)
    # Paymob retries a callback. There is deliberately no reconcile leg: ``reconcile_pending``
    # never selects a ``paid`` payment, so it would pass whatever the handler does. Exactly-once
    # rests on the once-per-payment dispatch and ``extra_seats`` and ``version`` moving once.
    _deliver(sm, obj)

    after = _sub(sm, scene)
    assert before.extra_seats == 1
    assert after.extra_seats == 3
    assert after.version == before.version + 1
    assert after.paymob_amount_minor == before.paymob_amount_minor  # the stamp is unchanged (DV-1)
    assert client.names() == []  # no Paymob subscription call from the callback
    payment = _payment(sm, payment_id)
    assert payment.status is PaymentStatus.paid
    assert payment.grant_units is None
    assert _credited_notices(sm, scene["payer_id"]) == 0


def test_two_different_seat_checkouts_both_paid_are_both_applied(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _teacher(sm)
    first = _buy(sm, _CheckoutClient(), scene, 2)
    second = _buy(sm, _CheckoutClient(), scene, 2, now=NOW + timedelta(minutes=1))

    _pay(sm, first, at=NOW + timedelta(minutes=2))
    _pay(sm, second, at=NOW + timedelta(minutes=3))

    assert _sub(sm, scene).extra_seats == 1 + 2 + 2


def test_a_purchase_paid_after_the_plan_ended_becomes_credits(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _teacher(sm)
    payment_id = _buy(sm, _CheckoutClient(), scene, 2)
    _update_sub(sm, scene, status=SubscriptionStatus.expired)

    with capture_logs() as logs:
        _pay(sm, payment_id, at=NOW + timedelta(minutes=5))

    assert _sub(sm, scene).extra_seats == 1
    credited = _grant(sm, scene["user_id"], f"credited:{payment_id}")
    assert credited is not None
    assert credited.visible is True
    assert _payment(sm, payment_id).grant_units == credited.units
    assert _credited_notices(sm, scene["payer_id"]) == 1
    assert _credited_reasons(logs) == ["plan_ended"]
    assert [log["event"] for log in logs if log.get("alert")] == []


def test_a_purchase_paid_after_the_period_rolled_becomes_credits(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _teacher(sm)
    payment_id = _buy(sm, _CheckoutClient(), scene, 2)
    renewed = NOW + timedelta(days=1)
    _update_sub(
        sm, scene, current_period_start=renewed, current_period_end=renewed + timedelta(days=30)
    )

    with capture_logs() as logs:
        _pay(sm, payment_id, at=renewed + timedelta(minutes=5))

    assert _sub(sm, scene).extra_seats == 1
    assert _grant(sm, scene["user_id"], f"credited:{payment_id}") is not None
    assert _credited_reasons(logs) == ["period_rolled"]


def test_a_purchase_paid_after_a_reduction_was_scheduled_becomes_credits(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _teacher(sm)
    payment_id = _buy(sm, _CheckoutClient(), scene, 2)
    _reduce(sm, scene, 0)  # the payer schedules a reduction while the checkout is open

    with capture_logs() as logs:
        _pay(sm, payment_id, at=NOW + timedelta(minutes=5))

    after = _sub(sm, scene)
    assert (after.extra_seats, after.pending_extra_seats) == (1, 0)
    assert _grant(sm, scene["user_id"], f"credited:{payment_id}") is not None
    assert _credited_reasons(logs) == ["seats_changing"]
    assert _credited_notices(sm, scene["payer_id"]) == 1


def test_a_purchase_paid_after_a_seat_grace_started_becomes_credits(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _teacher(sm)
    payment_id = _buy(sm, _CheckoutClient(), scene, 2)
    _update_sub(sm, scene, extra_seat_grace_until=NOW + timedelta(days=3))

    with capture_logs() as logs:
        _pay(sm, payment_id, at=NOW + timedelta(minutes=5))

    assert _sub(sm, scene).extra_seats == 1
    assert _credited_reasons(logs) == ["seats_changing"]


def test_a_purchase_that_would_pass_the_seat_ceiling_becomes_credits(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _teacher(sm, extra=150)
    payment_id = _buy(sm, _CheckoutClient(), scene, 50)
    _update_sub(sm, scene, extra_seats=151)  # another purchase landed first

    with capture_logs() as logs:
        _pay(sm, payment_id, at=NOW + timedelta(minutes=5))

    assert _sub(sm, scene).extra_seats == 151
    assert _credited_reasons(logs) == ["seats_over_limit"]


def test_a_seat_checkout_priced_before_an_upgrade_landed_is_credited_not_applied(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """I4: the seats were priced at the old seat price; the upgrade moved it, so they void."""
    sm = pg_sessionmaker
    scene = _teacher(sm)
    target = _seat_tier(sm, price=40_000, seat_price=5_000)
    client = _CheckoutClient()
    seats = _buy(sm, client, scene, 2)  # 2 x 2 000 / 2 = 2 000
    upgrade = _upgrade_checkout(sm, client, scene, target, now=NOW + timedelta(minutes=1))
    _pay(sm, upgrade, at=NOW + timedelta(minutes=2))
    assert _sub(sm, scene).plan_tier_id == target

    with capture_logs() as logs:
        _pay(sm, seats, at=NOW + timedelta(minutes=3))

    assert _sub(sm, scene).extra_seats == 1  # never added at the old price
    assert _grant(sm, scene["user_id"], f"credited:{seats}") is not None
    assert _credited_reasons(logs) == ["superseded"]


def test_a_seat_checkout_priced_after_an_upgrade_is_applied(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _teacher(sm)
    target = _seat_tier(sm, price=40_000, seat_price=5_000)
    client = _CheckoutClient()
    _pay(sm, _upgrade_checkout(sm, client, scene, target))
    seats = _buy(sm, client, scene, 2, now=NOW + timedelta(minutes=1))

    assert _payment(sm, seats).amount_minor == 5_000  # 2 x 5 000 / 2: the new seat price
    with capture_logs() as logs:
        _pay(sm, seats, at=NOW + timedelta(minutes=2))

    assert _sub(sm, scene).extra_seats == 3
    assert _credited_reasons(logs) == []


def test_a_seat_checkout_paid_after_the_plan_moved_to_a_plan_that_sells_none_is_credited(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _teacher(sm, extra=0)
    target = _seat_tier(sm, price=40_000, seat_price=0)
    client = _CheckoutClient()
    seats = _buy(sm, client, scene, 2)
    _pay(
        sm,
        _upgrade_checkout(sm, client, scene, target, now=NOW + timedelta(minutes=1)),
        at=NOW + timedelta(minutes=2),
    )

    with capture_logs() as logs:
        _pay(sm, seats, at=NOW + timedelta(minutes=3))

    assert _sub(sm, scene).extra_seats == 0
    assert _credited_reasons(logs) == ["seats_not_sold"]


def test_a_renewal_seat_payment_only_clears_the_grace(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _teacher(sm)
    _update_sub(sm, scene, extra_seat_grace_until=NOW + timedelta(days=3))
    payment_id = seed_payment_row(
        sm,
        payer_id=scene["payer_id"],
        beneficiary_id=scene["user_id"],
        purpose=PaymentPurpose.extra_seats,
        amount_minor=1_000,
        status=PaymentStatus.pending,
        subscription_id=scene["subscription_id"],
        seat_quantity=1,
        dedupe_key=f"{RENEWAL_SEAT_DEDUPE_PREFIX}{scene['period_id']}:1",
        paymob_order_id=next(_order_ids),
    )
    payment = _payment(sm, payment_id)
    assert payment.paymob_order_id is not None
    obj = moto_txn(
        order_id=payment.paymob_order_id,
        merchant_order_id=str(payment_id),
        amount_cents=1_000,
        txn_id=next(_txn_ids),
    )
    before = _sub(sm, scene)

    _deliver(sm, obj)

    after = _sub(sm, scene)
    assert after.extra_seats == before.extra_seats  # it pays for seats that already exist
    assert after.extra_seat_grace_until is None
    assert _payment(sm, payment_id).status is PaymentStatus.paid


def test_a_renewal_seat_payment_for_an_ended_plan_is_logged_not_credited(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _teacher(sm)
    _update_sub(sm, scene, status=SubscriptionStatus.expired)
    payment_id = seed_payment_row(
        sm,
        payer_id=scene["payer_id"],
        beneficiary_id=scene["user_id"],
        purpose=PaymentPurpose.extra_seats,
        amount_minor=1_000,
        status=PaymentStatus.pending,
        subscription_id=scene["subscription_id"],
        seat_quantity=1,
        dedupe_key=f"{RENEWAL_SEAT_DEDUPE_PREFIX}{scene['period_id']}:1",
        paymob_order_id=next(_order_ids),
    )
    payment = _payment(sm, payment_id)
    assert payment.paymob_order_id is not None
    obj = moto_txn(
        order_id=payment.paymob_order_id,
        merchant_order_id=str(payment_id),
        amount_cents=1_000,
        txn_id=next(_txn_ids),
    )

    with capture_logs() as logs:
        _deliver(sm, obj)

    assert _sub(sm, scene).extra_seats == 1
    assert [log["event"] for log in logs if log["log_level"] == "warning"] == [
        "renewal_seat_paid_for_ended_plan"
    ]


def test_the_handler_refuses_a_payment_with_no_paid_at(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _teacher(sm)
    payment_id = _buy(sm, _CheckoutClient(), scene, 1)
    with sm.begin() as session:
        payment = session.get(Payment, payment_id)
        assert payment is not None
        with pytest.raises(RuntimeError, match="paid_at"):
            handle_extra_seats_paid(session, payment, {})


def test_a_purchase_with_no_seat_quantity_is_an_error(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _teacher(sm)
    payment_id = seed_payment_row(
        sm,
        payer_id=scene["payer_id"],
        beneficiary_id=scene["user_id"],
        purpose=PaymentPurpose.extra_seats,
        amount_minor=1_000,
        status=PaymentStatus.paid,
        subscription_id=scene["subscription_id"],
        paid_at=NOW,
        created_at=NOW,
    )
    with sm.begin() as session:
        payment = session.get(Payment, payment_id)
        assert payment is not None
        with pytest.raises(ValueError, match="seat_quantity"):
            handle_extra_seats_paid(session, payment, {})


# ---------------------------------------------------------------------------
# Seat reduction and capacity.
# ---------------------------------------------------------------------------


def _seated(
    sm: sessionmaker[Session], scene: Mapping[str, uuid.UUID], statuses: list[Any]
) -> list[uuid.UUID]:
    seats: list[uuid.UUID] = []
    for status in statuses:
        seats.append(
            seed_seat(
                sm,
                teacher_id=scene["user_id"],
                student_id=seed_user(sm),
                status=status,
            )
        )
    return seats


def test_a_reduction_is_refused_counting_a_leaving_seat_and_succeeds_once_it_is_removed(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _teacher(sm)  # 2 included + 1 extra
    seats = _seated(
        sm,
        scene,
        [TeacherMemberStatus.active, TeacherMemberStatus.active, TeacherMemberStatus.leaving],
    )
    client = _CheckoutClient()

    with pytest.raises(MerchantChargeError) as caught:
        _reduce(sm, scene, 0, client=client)
    assert caught.value.code == "seats_in_use"
    assert _sub(sm, scene).pending_extra_seats is None

    with sm.begin() as session:
        member = session.get(TeacherMember, seats[2])
        assert member is not None
        member.status = TeacherMemberStatus.removed
    before = _sub(sm, scene)
    _reduce(sm, scene, 0, client=client)

    after = _sub(sm, scene)
    assert after.pending_extra_seats == 0
    assert after.extra_seats == 1  # Phase 05 applies it at the renewal
    assert after.version == before.version + 1
    assert client.names() == [] and client.intentions == []  # no Paymob call
    with sm() as session:
        assert TeacherTeamService(session).seat_capacity(scene["user_id"]) == 2


def test_a_scheduled_reduction_stops_new_class_joins_past_the_lower_capacity(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _teacher(sm)
    _seated(sm, scene, [TeacherMemberStatus.active, TeacherMemberStatus.active])
    _reduce(sm, scene, 0)
    newcomer = seed_user(sm)
    class_id, _ = add_class(sm, teacher_id=scene["user_id"])
    enrol(sm, class_id, newcomer)

    with pytest.raises(NoFreeSeat), sm.begin() as session:
        TeacherTeamService(session).claim_seat_for_class_join(
            student_user_id=newcomer, class_id=class_id, now=NOW
        )

    # Without the reduction the same join would have found the extra seat.
    _update_sub(sm, scene, pending_extra_seats=None)
    with sm.begin() as session:
        seat = TeacherTeamService(session).claim_seat_for_class_join(
            student_user_id=newcomer, class_id=class_id, now=NOW
        )
        assert seat is not None


def test_the_capacity_is_capped_by_a_pending_reduction_but_never_raised_by_it(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _teacher(sm, extra=3, pending=1)
    with sm() as session:
        assert TeacherTeamService(session).seat_capacity(scene["user_id"]) == 2 + 1
    _update_sub(sm, scene, pending_extra_seats=7)  # a stale value above the held seats
    with sm() as session:
        assert TeacherTeamService(session).seat_capacity(scene["user_id"]) == 2 + 3


def test_a_reduction_to_the_current_count_clears_a_pending_one(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _teacher(sm, extra=2, pending=0)
    before = _sub(sm, scene)
    _reduce(sm, scene, 2)
    after = _sub(sm, scene)
    assert after.pending_extra_seats is None
    assert after.version == before.version + 1


def test_a_reduction_above_the_current_count_or_below_zero_is_not_a_reduction(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _teacher(sm)
    for value in (5, -1):
        with pytest.raises(MerchantChargeError) as caught:
            _reduce(sm, scene, value)
        assert caught.value.code == "not_a_reduction"


def test_a_student_plan_cannot_schedule_a_reduction(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = student_with_plan(sm)
    with pytest.raises(MerchantChargeError) as caught:
        _reduce(sm, scene, 0)
    assert caught.value.code == "not_a_teacher_plan"


def test_a_fallback_reduction_below_the_amount_paymob_holds_is_refused(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _teacher(sm)  # Paymob holds 32 000 (price + 1 extra seat)
    settings = paymob_settings(subscription_amount_updatable=False)
    with pytest.raises(MerchantChargeError) as caught:
        _reduce(sm, scene, 0, settings=settings)
    assert caught.value.code == "seat_reduction_unavailable"
    assert _sub(sm, scene).pending_extra_seats is None
    _reduce(sm, scene, 0)  # on the updatable path the same reduction is fine
    assert _sub(sm, scene).pending_extra_seats == 0


def test_cancelling_a_reduction_after_an_upgrade_priced_the_lower_seat_count_is_refused(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """I3: reduce, upgrade (seats priced at the reduced count), cancel: no seats return unpaid."""
    sm = pg_sessionmaker
    scene = _teacher(sm, extra=3)
    _reduce(sm, scene, 1)
    target = _seat_tier(sm, price=40_000, seat_price=5_000)
    upgrade = _upgrade_checkout(sm, _CheckoutClient(), scene, target)
    _pay(sm, upgrade)
    assert _sub(sm, scene).plan_tier_id == target
    capacity_before = _capacity_of(sm, scene)

    for restored in (3, 2):  # clearing it, or lifting it partway
        with pytest.raises(MerchantChargeError) as caught:
            _reduce(sm, scene, restored)
        assert caught.value.code == "seat_reduction_locked"

    after = _sub(sm, scene)
    assert after.pending_extra_seats == 1
    assert _capacity_of(sm, scene) == capacity_before == 2 + 1
    _reduce(sm, scene, 0)  # a deeper reduction is still fine
    assert _sub(sm, scene).pending_extra_seats == 0


def test_cancelling_a_reduction_is_fine_when_no_upgrade_landed(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    sm = pg_sessionmaker
    scene = _teacher(sm, extra=3)
    _reduce(sm, scene, 1)
    _reduce(sm, scene, 3)
    assert _sub(sm, scene).pending_extra_seats is None


def _capacity_of(sm: sessionmaker[Session], scene: Mapping[str, uuid.UUID]) -> int:
    with sm() as session:
        return TeacherTeamService(session).seat_capacity(scene["user_id"])
