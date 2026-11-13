"""Throwaway Postgres, a scripted Paymob fake and seed helpers for the Phase 05 subscription tests.

Not a test module: test files import from it. Each test module builds its own pytest fixture
from :func:`throwaway_database` (see ``tests/team_db.py`` for why). Every helper is
keyword-only past its first argument so later tasks can add parameters without touching call
sites, and every helper that writes ``created_at`` takes it as a keyword.

``FakePaymobClient`` subclasses Phase 02's fake: HTTP stays refused, and the subscription calls
are scripted here. Each call is recorded as ``(name, kwargs)`` and ``fail[name]`` raises a
scripted exception after the call is recorded.
"""

from __future__ import annotations

import enum
import itertools
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa

from lemely.db.models import import_all_models
from lemely.db.models.billing import (
    Payment,
    PaymentPurpose,
    PaymentStatus,
    PlanAudience,
    PlanTier,
    Subscription,
)
from lemely.db.models.enums import PlanInterval, SubscriptionStatus
from lemely.db.models.team import (
    CapPeriod,
    TeacherMember,
    TeacherMemberKind,
    TeacherMemberStatus,
)
from lemely.db.models.usage import UsageDebt, UsageGrant
from lemely.io.paymob.hmac import sign, subscription_hmac_message
from lemely.runtime.config import PaymobSettings
from tests.paymob_fixtures import (
    MOTO_INTEGRATION_ID,
    PAYMOB_SETTINGS,
    PLAN_RESPONSE,
    SUBSCRIPTION_RESPONSE,
    TEST_HMAC_SECRET,
    link_parent,
    seed_user,
)
from tests.paymob_fixtures import FakePaymobClient as _Phase02FakePaymobClient
from tests.team_db import team_database

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

    from lemely.io.paymob.client import JsonObject

import_all_models()

HMAC_SECRET = TEST_HMAC_SECRET
T0 = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)


@contextmanager
def throwaway_database() -> Iterator[sessionmaker[Session]]:
    """A fresh ``create_all`` database for one test module; skips without local Postgres.

    Built exactly as ``tests.team_db.team_database`` builds it (it is the same database, so the
    partial unique index on live subscriptions is present because the ORM declares it).
    """
    with team_database() as factory:
        yield factory


def paymob_settings(**overrides: Any) -> PaymobSettings:
    """Phase 02's test settings (MOTO integration set) with ``overrides`` applied."""
    return PaymobSettings.model_validate({**PAYMOB_SETTINGS.model_dump(), **overrides})


#: Paymob plan ids the fake hands out. Module-wide, so two fakes never create the same plan id
#: against one database (``plan_tiers.paymob_plan_id`` is unique).
_created_plan_ids = itertools.count(9001)


class FakePaymobClient(_Phase02FakePaymobClient):
    """Phase 02's fake plus scripted subscription calls that record and can fail.

    ``plans`` and ``subscriptions`` hold what Paymob "knows"; ``last_transactions`` maps a
    Paymob subscription id to the body ``last_transaction`` returns. A call with nothing
    scripted for it falls back to a copy of the shared ``*_RESPONSE`` payloads, except
    ``last_transaction``, which asserts so a test cannot read an unscripted charge by accident.
    """

    def __init__(self, settings: PaymobSettings = PAYMOB_SETTINGS) -> None:
        super().__init__(settings)
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.fail: dict[str, Exception] = {}
        self.subscriptions: dict[int, JsonObject] = {}
        self.last_transactions: dict[int, JsonObject] = {}

    def names(self) -> list[str]:
        """The recorded call names, in order."""
        return [name for name, _ in self.calls]

    def calls_to(self, name: str) -> list[dict[str, Any]]:
        """The recorded keyword arguments of every call to ``name``."""
        return [kwargs for called, kwargs in self.calls if called == name]

    def _record(self, call: str, /, **kwargs: Any) -> None:
        self.calls.append((call, kwargs))
        if call in self.fail:
            raise self.fail[call]

    def create_plan(  # type: ignore[override]
        self,
        *,
        name: str,
        frequency_days: int,
        amount_cents: int,
        integration_id: int,
        webhook_url: str,
        retrial_days: int | None = None,
        reminder_days: int | None = None,
        use_transaction_amount: bool = False,
    ) -> JsonObject:
        self._record(
            "create_plan",
            name=name,
            frequency_days=frequency_days,
            amount_cents=amount_cents,
            integration_id=integration_id,
            webhook_url=webhook_url,
            retrial_days=retrial_days,
            reminder_days=reminder_days,
            use_transaction_amount=use_transaction_amount,
        )
        return {
            **PLAN_RESPONSE,
            "id": next(_created_plan_ids),
            "name": name,
            "frequency": frequency_days,
            "amount_cents": amount_cents,
        }

    def get_subscription(self, subscription_id: int) -> JsonObject:
        self._record("get_subscription", subscription_id=subscription_id)
        stored = self.subscriptions.get(subscription_id)
        return dict(stored if stored is not None else SUBSCRIPTION_RESPONSE) | {
            "id": subscription_id
        }

    def update_subscription(
        self,
        subscription_id: int,
        *,
        amount_cents: int | None = None,
        ends_at: str | None = None,
        next_billing: str | None = None,
    ) -> JsonObject:
        self._record(
            "update_subscription",
            subscription_id=subscription_id,
            amount_cents=amount_cents,
            ends_at=ends_at,
            next_billing=next_billing,
        )
        row = self.subscriptions.setdefault(
            subscription_id, {**SUBSCRIPTION_RESPONSE, "id": subscription_id}
        )
        for key, value in (
            ("amount_cents", amount_cents),
            ("ends_at", ends_at),
            ("next_billing", next_billing),
        ):
            if value is not None:
                row[key] = value
        return dict(row)

    def cancel_subscription(self, subscription_id: int) -> JsonObject:
        self._record("cancel_subscription", subscription_id=subscription_id)
        row = self.subscriptions.setdefault(
            subscription_id, {**SUBSCRIPTION_RESPONSE, "id": subscription_id}
        )
        row["state"] = "canceled"
        return dict(row)

    def last_transaction(self, subscription_id: int) -> JsonObject:
        self._record("last_transaction", subscription_id=subscription_id)
        if subscription_id not in self.last_transactions:
            raise AssertionError(f"no last transaction scripted for subscription {subscription_id}")
        return dict(self.last_transactions[subscription_id])


class _AutoPlanId(enum.Enum):
    """Marks ``seed_tier``'s default: link the tier to a fresh, unique Paymob plan id."""

    AUTO = enum.auto()


_plan_ids = itertools.count(5001)


def seed_tier(
    sm: sessionmaker[Session],
    *,
    audience: PlanAudience = PlanAudience.student,
    price_minor: int = 10_000,
    interval: PlanInterval | None = PlanInterval.monthly,
    allowance_units: int = 1_000,
    included_seats: int = 0,
    seat_allowance_units: int = 0,
    extra_seat_price_minor: int = 0,
    paymob_plan_id: int | None | _AutoPlanId = _AutoPlanId.AUTO,
    is_active: bool = True,
    currency: str = "EGP",
) -> uuid.UUID:
    """Insert a plan tier; ``paymob_plan_id=None`` leaves it unlinked, the default links it."""
    tier_id = uuid.uuid4()
    plan_id = next(_plan_ids) if isinstance(paymob_plan_id, _AutoPlanId) else paymob_plan_id
    with sm.begin() as session:
        session.add(
            PlanTier(
                id=tier_id,
                code=f"{audience.value}-{tier_id.hex[:8]}",
                name=f"{audience.value.title()} plan",
                price_minor=price_minor,
                currency=currency,
                interval=interval,
                audience=audience,
                allowance_units=allowance_units,
                included_seats=included_seats,
                seat_allowance_units=seat_allowance_units,
                extra_seat_price_minor=extra_seat_price_minor,
                paymob_plan_id=plan_id,
                is_active=is_active,
            )
        )
    return tier_id


def seed_subscription(
    sm: sessionmaker[Session],
    *,
    user_id: uuid.UUID,
    tier_id: uuid.UUID,
    payer_id: uuid.UUID | None = None,
    status: SubscriptionStatus = SubscriptionStatus.active,
    period_start: datetime | None = T0,
    period_end: datetime | None = T0 + timedelta(days=30),
    paymob_subscription_id: int | None = None,
    paymob_amount_minor: int | None = None,
    extra_seats: int = 0,
    pending_extra_seats: int | None = None,
    cancel_at_period_end: bool = False,
    pending_plan_tier_id: uuid.UUID | None = None,
    grace_until: datetime | None = None,
    is_manually_activated: bool = False,
    paymob_cancelled_at: datetime | None = None,
    created_at: datetime | None = None,
) -> uuid.UUID:
    """Insert a subscription row exactly as given (no ledger effect, no period row)."""
    sub_id = uuid.uuid4()
    with sm.begin() as session:
        sub = Subscription(
            id=sub_id,
            user_id=user_id,
            payer_user_id=payer_id,
            plan_tier_id=tier_id,
            status=status,
            current_period_start=period_start,
            current_period_end=period_end,
            paymob_subscription_id=paymob_subscription_id,
            paymob_amount_minor=paymob_amount_minor,
            extra_seats=extra_seats,
            pending_extra_seats=pending_extra_seats,
            cancel_at_period_end=cancel_at_period_end,
            pending_plan_tier_id=pending_plan_tier_id,
            grace_until=grace_until,
            is_manually_activated=is_manually_activated,
            paymob_cancelled_at=paymob_cancelled_at,
        )
        if created_at is not None:
            sub.created_at = created_at
        session.add(sub)
    return sub_id


def seed_first_payment(
    sm: sessionmaker[Session],
    *,
    subscription_id: uuid.UUID,
    amount_minor: int = 10_000,
    status: PaymentStatus = PaymentStatus.paid,
    paymob_txn_id: int | None = None,
    paymob_order_id: int | None = None,
    paid_at: datetime | None = T0,
    created_at: datetime | None = None,
    seat_quantity: int | None = None,
) -> uuid.UUID:
    """Insert the ``subscription_first`` payment of ``subscription_id``.

    The payer is the subscription's payer, so a manual activation (no payer) cannot have one.
    """
    payment_id = uuid.uuid4()
    with sm.begin() as session:
        sub = session.get(Subscription, subscription_id)
        assert sub is not None, "seed the subscription first"
        assert sub.payer_user_id is not None, "a manual activation has no payer to pay"
        payment = Payment(
            id=payment_id,
            special_reference=str(payment_id),
            payer_user_id=sub.payer_user_id,
            beneficiary_user_id=sub.user_id,
            purpose=PaymentPurpose.subscription_first,
            plan_tier_id=sub.plan_tier_id,
            subscription_id=sub.id,
            seat_quantity=seat_quantity,
            amount_minor=amount_minor,
            currency="EGP",
            status=status,
            paymob_txn_id=paymob_txn_id,
            paymob_order_id=paymob_order_id,
            paid_at=paid_at if status is PaymentStatus.paid else None,
        )
        if created_at is not None:
            payment.created_at = created_at
        session.add(payment)
    return payment_id


def seed_seat(
    sm: sessionmaker[Session],
    *,
    teacher_id: uuid.UUID,
    student_id: uuid.UUID,
    status: TeacherMemberStatus = TeacherMemberStatus.active,
    created_at: datetime | None = None,
    leaves_at: datetime | None = None,
) -> uuid.UUID:
    """Insert a student seat; a ``leaving`` seat without ``leaves_at`` leaves 30 days after T0."""
    member_id = uuid.uuid4()
    if status is TeacherMemberStatus.leaving and leaves_at is None:
        leaves_at = T0 + timedelta(days=30)
    with sm.begin() as session:
        member = TeacherMember(
            id=member_id,
            teacher_user_id=teacher_id,
            member_user_id=student_id,
            kind=TeacherMemberKind.student_seat,
            scope_subjects=[],
            scope_actions=[],
            cap_units=None,
            cap_period=CapPeriod.month,
            status=status,
            leaves_at=leaves_at,
        )
        if created_at is not None:
            member.created_at = created_at
        session.add(member)
    return member_id


def grants_of(sm: sessionmaker[Session], owner_id: uuid.UUID) -> list[UsageGrant]:
    """Every grant owned by ``owner_id``, oldest effective first."""
    with sm() as session:
        return list(
            session.scalars(
                sa.select(UsageGrant)
                .where(UsageGrant.owner_user_id == owner_id)
                .order_by(UsageGrant.effective_at, UsageGrant.id)
            )
        )


def seed_debt(sm: sessionmaker[Session], owner_id: uuid.UUID, units: int) -> None:
    """Outstanding debt with no job (``usage_debts.job_id`` is nullable).

    ``UsageLedger.adjust`` with negative units never creates debt (Phase 01), so tests seed the
    row directly.
    """
    with sm.begin() as session:
        session.add(UsageDebt(owner_user_id=owner_id, units=units, outstanding=units))


def subscription_webhook(
    trigger_type: str, paymob_id: int, *, secret: str = HMAC_SECRET, **extra: Any
) -> JsonObject:
    """A subscription callback body signed over ``"{trigger}for{id}"`` (research 02 §2.3).

    ``hmac`` is in the body. ``extra`` keys (for example ``paymob_request_id``) are added
    unsigned, as Paymob's are.
    """
    body: JsonObject = {
        "subscription_data": {"id": paymob_id, "state": "active", "amount_cents": 1},
        "trigger_type": trigger_type,
        "hmac": sign(subscription_hmac_message(trigger_type, paymob_id), secret),
    }
    body.update(extra)
    return body


def charge(
    txn_id: int,
    amount_cents: int,
    *,
    created_at: datetime = T0,
    success: bool = True,
    currency: str = "EGP",
    order_id: int | None = None,
    **flags: Any,
) -> JsonObject:
    """A ``GET subscriptions/{id}/last-transaction`` body (a transaction object).

    ``order`` carries an integer id (DV-14); ``flags`` override ``pending``, ``is_voided``,
    ``is_refunded`` or ``error_occured``. ``created_at`` is written naive, as Paymob does.
    """
    return {
        "id": txn_id,
        "amount_cents": amount_cents,
        "currency": currency,
        "success": success,
        "pending": False,
        "is_voided": False,
        "is_refunded": False,
        "error_occured": False,
        "order": {"id": order_id if order_id is not None else txn_id + 1_000_000},
        "created_at": created_at.astimezone(UTC).replace(tzinfo=None).isoformat(),
    } | flags


def remote_subscription(
    paymob_id: int,
    *,
    state: str = "active",
    amount_cents: int = 10_000,
    initial_transaction: int = 777,
    updated_at: str = "2026-11-10T09:00:00",
    **extra: Any,
) -> JsonObject:
    """A ``GET subscriptions/{id}`` body (research 02 §6 field list)."""
    return {
        **SUBSCRIPTION_RESPONSE,
        "id": paymob_id,
        "state": state,
        "amount_cents": amount_cents,
        "initial_transaction": initial_transaction,
        "updated_at": updated_at,
        "integration": MOTO_INTEGRATION_ID,
    } | extra


__all__ = [
    "HMAC_SECRET",
    "T0",
    "FakePaymobClient",
    "charge",
    "grants_of",
    "link_parent",
    "paymob_settings",
    "remote_subscription",
    "seed_debt",
    "seed_first_payment",
    "seed_seat",
    "seed_subscription",
    "seed_tier",
    "seed_user",
    "subscription_webhook",
    "throwaway_database",
]
