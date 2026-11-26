"""Seed helpers and a MOTO callback builder for the Phase 06 merchant-charge tests.

Not a test module: test files import from it. It reuses Phase 02's and Phase 05's seeders
(``tests/paymob_fixtures.py``, ``tests/subscription_fixtures.py``, both read-only here) and adds
only what Phase 06 is missing: a saved card with a real ciphertext, a period row, a payment with
a queue ``dedupe_key``, an auto top-up row, a MOTO-signed transaction body, and one-call
"teacher with a plan" and "student with a plan" scenes.

Task 1 creates it, Task 3 may extend it, and it is read-only afterwards: a helper a later task
needs goes in that task's own test file. Every helper is keyword-only past its first argument.
"""

from __future__ import annotations

import itertools
import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from sqlalchemy.exc import OperationalError

from lemely.core.subscription_rules import subscription_amount_minor
from lemely.db.models.billing import (
    AutoTopupSettings,
    Payment,
    PaymentPurpose,
    PaymentStatus,
    PlanAudience,
    SavedCard,
    SubscriptionPeriod,
)
from lemely.db.models.enums import Role
from lemely.runtime.token_cipher import TokenCipher
from tests.paymob_fixtures import (
    INTENTION_RESPONSE,
    MOTO_INTEGRATION_ID,
    PAYMOB_SETTINGS,
    TEST_CARD_TOKEN_KEY,
    FakePaymobClient,
    link_parent,
    seed_pack,
    seed_user,
    transaction_obj,
)
from tests.subscription_fixtures import (
    T0,
    paymob_settings,
    seed_first_payment,
    seed_seat,
    seed_subscription,
    seed_tier,
    throwaway_database,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session, sessionmaker

    from lemely.runtime.config import PaymobSettings

#: Paymob subscription ids the scenes hand out (``subscriptions.paymob_subscription_id`` is
#: unique), module-wide so two scenes in one database never collide.
_paymob_subscription_ids = itertools.count(7001)
#: Order, intention and transaction ids the fake hands out, module-wide so two charges in one
#: database never share a ``payments.paymob_order_id`` (unique).
_moto_ids = itertools.count(880_001)


def seed_saved_card(
    sm: sessionmaker[Session],
    user_id: uuid.UUID,
    *,
    token: str = "tok_card_1",
    is_active: bool = True,
    created_at: datetime | None = None,
) -> uuid.UUID:
    """Insert a saved card for ``user_id``, its token encrypted under that user's id (R22)."""
    cipher = TokenCipher(TEST_CARD_TOKEN_KEY)
    card_id = uuid.uuid4()
    with sm.begin() as session:
        card = SavedCard(
            id=card_id,
            user_id=user_id,
            token=cipher.encrypt(token, user_id),
            token_fingerprint=cipher.fingerprint(token, user_id),
            masked_pan="xxxx-2346",
            brand="mastercard",
            is_active=is_active,
        )
        if created_at is not None:
            card.created_at = created_at
        session.add(card)
    return card_id


def seed_period(
    sm: sessionmaker[Session],
    *,
    subscription_id: uuid.UUID,
    period_start: datetime,
    period_end: datetime,
    payment_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Insert a ``subscription_periods`` row (no grant: the caller issues what it needs)."""
    period_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            SubscriptionPeriod(
                id=period_id,
                subscription_id=subscription_id,
                period_start=period_start,
                period_end=period_end,
                payment_id=payment_id,
            )
        )
    return period_id


def seed_payment_row(
    sm: sessionmaker[Session],
    *,
    payer_id: uuid.UUID,
    beneficiary_id: uuid.UUID | None = None,
    purpose: PaymentPurpose,
    amount_minor: int,
    status: PaymentStatus = PaymentStatus.created,
    subscription_id: uuid.UUID | None = None,
    plan_tier_id: uuid.UUID | None = None,
    credit_pack_id: uuid.UUID | None = None,
    seat_quantity: int | None = None,
    dedupe_key: str | None = None,
    paid_at: datetime | None = None,
    created_at: datetime | None = None,
    paymob_order_id: int | None = None,
) -> uuid.UUID:
    """Insert a payment exactly as given; ``special_reference`` is ``str(id)`` as in production.

    The beneficiary defaults to the payer. No ledger or subscription effect.
    """
    payment_id = uuid.uuid4()
    with sm.begin() as session:
        payment = Payment(
            id=payment_id,
            special_reference=str(payment_id),
            payer_user_id=payer_id,
            beneficiary_user_id=beneficiary_id or payer_id,
            purpose=purpose,
            plan_tier_id=plan_tier_id,
            credit_pack_id=credit_pack_id,
            subscription_id=subscription_id,
            seat_quantity=seat_quantity,
            amount_minor=amount_minor,
            currency="EGP",
            status=status,
            dedupe_key=dedupe_key,
            paid_at=paid_at,
            paymob_order_id=paymob_order_id,
        )
        if created_at is not None:
            payment.created_at = created_at
        session.add(payment)
    return payment_id


def seed_auto_topup(
    sm: sessionmaker[Session],
    *,
    beneficiary_id: uuid.UUID,
    payer_id: uuid.UUID,
    pack_id: uuid.UUID,
    card_id: uuid.UUID | None,
    enabled: bool = True,
    threshold: int = 500,
    cap: int = 50_000,
    consented_at: datetime | None = None,
) -> uuid.UUID:
    """Insert an ``auto_topup_settings`` row (armed, ``crossing_seq`` 0, no consent stamp)."""
    setting_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            AutoTopupSettings(
                id=setting_id,
                beneficiary_user_id=beneficiary_id,
                payer_user_id=payer_id,
                enabled=enabled,
                threshold_units=threshold,
                credit_pack_id=pack_id,
                saved_card_id=card_id,
                monthly_cap_minor=cap,
                consented_at=consented_at,
            )
        )
    return setting_id


def moto_txn(
    *,
    order_id: int,
    merchant_order_id: str,
    amount_cents: int,
    success: bool = True,
    pending: bool = False,
    txn_id: int,
) -> dict[str, Any]:
    """A transaction ``obj`` processed on the MOTO integration (``transaction_obj``: the card id).

    Sign it with ``tests.paymob_fixtures.sign_transaction`` after this call, never before: the
    body is mutated here, so a signature taken from ``transaction_obj`` would no longer match.
    """
    obj = transaction_obj(
        txn_id=txn_id,
        order_id=order_id,
        merchant_order_id=merchant_order_id,
        amount_cents=amount_cents,
        success=success,
        pending=pending,
    )
    obj["integration_id"] = MOTO_INTEGRATION_ID
    return obj


#: ``INTENTION_RESPONSE`` with the MOTO integration named in its payment key, the answer a MOTO
#: intention gets.
MOTO_INTENTION_RESPONSE: dict[str, Any] = {
    **INTENTION_RESPONSE,
    "payment_keys": [{**INTENTION_RESPONSE["payment_keys"][0], "integration": MOTO_INTEGRATION_ID}],
}


class FakeMotoClient(FakePaymobClient):
    """Phase 02's fake (HTTP refused) plus a scripted, recording MOTO ``pay_with_token``.

    ``intention_response`` is Phase 02's attribute; the default one (the MOTO answer) is given a
    fresh ``intention_order_id`` and ``id`` per call (set ``fresh_ids = False`` to script exact
    ids). ``pay_response`` is the body
    ``pay_with_token`` returns, or the exception it raises. ``on_pay`` runs inside the pay call,
    before the answer, so a test can race a callback against it or raise from it.

    ``calls`` records ``(name, kwargs)`` for ``create_intention``, ``pay_with_token`` and
    ``inquire_by_order_ref`` (``calls_to`` filters them). When ``sessionmaker`` is given, every
    ``create_intention`` and ``pay_with_token`` probe the database from a **separate** session and
    appends what it saw to ``at_intention`` / ``at_pay``: the payment's status by
    ``special_reference`` and whether its row could be locked (``FOR UPDATE NOWAIT``). A status of
    ``pending`` and ``lock_free`` true prove the claim was committed before Paymob was called and
    that no row lock was held across either call.
    """

    def __init__(
        self,
        settings: PaymobSettings = PAYMOB_SETTINGS,
        *,
        sessionmaker: sessionmaker[Session] | None = None,
    ) -> None:
        super().__init__(settings)
        self.sessionmaker = sessionmaker
        self.intention_response = dict(MOTO_INTENTION_RESPONSE)
        self.fresh_ids = True
        self.pay_response: dict[str, Any] | Exception = {
            "id": next(_moto_ids),
            "success": True,
            "pending": False,
        }
        self.on_pay: Callable[[dict[str, Any]], None] | None = None
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.at_intention: list[dict[str, Any]] = []
        self.at_pay: list[dict[str, Any]] = []
        self._reference: str | None = None

    def calls_to(self, name: str) -> list[dict[str, Any]]:
        """The recorded keyword arguments of every call to ``name``."""
        return [kwargs for called, kwargs in self.calls if called == name]

    def _probe(self, special_reference: str) -> dict[str, Any]:
        assert self.sessionmaker is not None
        with self.sessionmaker() as session:
            status = session.scalar(
                sa.select(Payment.status).where(Payment.special_reference == special_reference)
            )
            try:
                session.execute(
                    sa.text(
                        "SELECT id FROM payments WHERE special_reference = :ref FOR UPDATE NOWAIT"
                    ),
                    {"ref": special_reference},
                )
                lock_free = True
            except OperationalError:
                lock_free = False
            finally:
                session.rollback()
        return {"status": status, "lock_free": lock_free}

    def create_intention(self, body: Any) -> dict[str, Any]:
        self.calls.append(("create_intention", dict(body)))
        self._reference = str(body["special_reference"])
        if self.sessionmaker is not None:
            self.at_intention.append(self._probe(self._reference))
        if self.on_intention is not None:
            self.on_intention(dict(body))
        if isinstance(self.intention_response, Exception):
            raise self.intention_response
        response = dict(self.intention_response)
        if self.fresh_ids:
            if "intention_order_id" in response:
                response["intention_order_id"] = next(_moto_ids)
            if "id" in response:
                response["id"] = f"pi_test_moto_{next(_moto_ids)}"
        self.intentions.append(dict(body))
        return response

    def pay_with_token(self, *, card_token: str, payment_token: str) -> dict[str, Any]:
        call = {"card_token": card_token, "payment_token": payment_token}
        self.calls.append(("pay_with_token", call))
        if self.sessionmaker is not None and self._reference is not None:
            self.at_pay.append(self._probe(self._reference))
        if self.on_pay is not None:
            self.on_pay(call)
        if isinstance(self.pay_response, Exception):
            raise self.pay_response
        return dict(self.pay_response)

    def inquire_by_order_ref(self, merchant_order_id: str) -> dict[str, Any] | None:
        self.calls.append(("inquire_by_order_ref", {"merchant_order_id": merchant_order_id}))
        return super().inquire_by_order_ref(merchant_order_id)


def _scene(
    sm: sessionmaker[Session],
    *,
    role: Role,
    audience: PlanAudience,
    payer_id: uuid.UUID | None,
    price: int,
    allowance_units: int,
    included_seats: int,
    seat_price: int,
    extra: int,
    pending: int | None,
    paymob_amount: int | None,
    start: datetime,
    end: datetime,
    card: bool,
) -> dict[str, uuid.UUID]:
    user_id = seed_user(sm, role)
    payer = payer_id or user_id
    tier_id = seed_tier(
        sm,
        audience=audience,
        price_minor=price,
        allowance_units=allowance_units,
        included_seats=included_seats,
        extra_seat_price_minor=seat_price,
    )
    in_step = subscription_amount_minor(
        price_minor=price, extra_seats=extra, extra_seat_price_minor=seat_price
    )
    stamp = in_step if paymob_amount is None else paymob_amount
    subscription_id = seed_subscription(
        sm,
        user_id=user_id,
        tier_id=tier_id,
        payer_id=payer,
        period_start=start,
        period_end=end,
        paymob_subscription_id=next(_paymob_subscription_ids),
        paymob_amount_minor=stamp,
        extra_seats=extra,
        pending_extra_seats=pending,
    )
    payment_id = seed_first_payment(
        sm, subscription_id=subscription_id, amount_minor=stamp, paid_at=start
    )
    period_id = seed_period(
        sm,
        subscription_id=subscription_id,
        period_start=start,
        period_end=end,
        payment_id=payment_id,
    )
    scene: dict[str, uuid.UUID] = {
        "user_id": user_id,
        "payer_id": payer,
        "tier_id": tier_id,
        "subscription_id": subscription_id,
        "payment_id": payment_id,
        "period_id": period_id,
    }
    if card:
        scene["card_id"] = seed_saved_card(sm, payer)
    return scene


def teacher_with_plan(
    sm: sessionmaker[Session],
    *,
    included: int = 2,
    seat_price: int = 2_000,
    price: int = 30_000,
    extra: int = 0,
    pending: int | None = None,
    paymob_amount: int | None = None,
    start: datetime = T0,
    end: datetime = T0 + timedelta(days=30),
    card: bool = True,
) -> dict[str, uuid.UUID]:
    """A teacher with an active paid teacher plan, its first payment, its period and a card.

    ``paymob_amount`` defaults to "in step" (``subscription_amount_minor`` of the price and the
    extra seats), which is also the first payment's amount. Keys: ``user_id`` (also
    ``teacher_id``), ``payer_id`` (the teacher), ``tier_id``, ``subscription_id``,
    ``payment_id``, ``period_id`` and, when ``card`` is true, ``card_id``.
    """
    scene = _scene(
        sm,
        role=Role.teacher,
        audience=PlanAudience.teacher,
        payer_id=None,
        price=price,
        allowance_units=1_000,
        included_seats=included,
        seat_price=seat_price,
        extra=extra,
        pending=pending,
        paymob_amount=paymob_amount,
        start=start,
        end=end,
        card=card,
    )
    scene["teacher_id"] = scene["user_id"]
    return scene


def student_with_plan(
    sm: sessionmaker[Session],
    *,
    price: int = 10_000,
    allowance_units: int = 1_000,
    payer_id: uuid.UUID | None = None,
    paymob_amount: int | None = None,
    start: datetime = T0,
    end: datetime = T0 + timedelta(days=30),
    card: bool = True,
) -> dict[str, uuid.UUID]:
    """A student with an active paid student plan, its first payment, its period and a card.

    ``payer_id`` is a parent paying for the student (the card then belongs to the parent); the
    caller links them with ``link_parent``. Keys as ``teacher_with_plan``, with ``student_id``
    in place of ``teacher_id``.
    """
    scene = _scene(
        sm,
        role=Role.student,
        audience=PlanAudience.student,
        payer_id=payer_id,
        price=price,
        allowance_units=allowance_units,
        included_seats=0,
        seat_price=0,
        extra=0,
        pending=None,
        paymob_amount=paymob_amount,
        start=start,
        end=end,
        card=card,
    )
    scene["student_id"] = scene["user_id"]
    return scene


__all__ = [
    "MOTO_INTEGRATION_ID",
    "MOTO_INTENTION_RESPONSE",
    "T0",
    "FakeMotoClient",
    "link_parent",
    "moto_txn",
    "paymob_settings",
    "seed_auto_topup",
    "seed_pack",
    "seed_payment_row",
    "seed_period",
    "seed_saved_card",
    "seed_seat",
    "seed_subscription",
    "seed_tier",
    "seed_user",
    "student_with_plan",
    "teacher_with_plan",
    "throwaway_database",
]
