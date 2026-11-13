"""What a billing screen shows for one beneficiary (index R3; spec §2.1, §2.2, §4.5, §7).

Read-only. Who may see whose summary is the route's job (:func:`is_linked_student` is the
parent half of that rule); this module assumes the caller may see ``beneficiary_user_id``.

Usage, credits and debt come from :func:`~lemely.db.usage_views_repo.meter_view`, so the
summary and ``GET /api/usage/meter`` can never disagree about the same user at the same instant.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import select

from lemely.db.billing_repo import is_linked_parent
from lemely.db.models.billing import (
    PLAN_LIVE_STATUSES,
    Payment,
    PaymentPurpose,
    PaymentStatus,
    PlanTier,
    SavedCard,
    Subscription,
)
from lemely.db.models.enums import Role, SubscriptionStatus
from lemely.db.models.users import User
from lemely.db.teacher_team_repo import TeacherTeamService
from lemely.db.usage_views_repo import meter_view

if TYPE_CHECKING:
    import uuid
    from datetime import datetime

    from sqlalchemy.orm import Session

#: A first checkout is "open" (worth showing as "waiting for payment") only in these states.
_OPEN_FIRST_PAYMENT = (PaymentStatus.created, PaymentStatus.pending)


@dataclass(frozen=True, slots=True)
class CreditLot:
    """Spendable credits that share one expiry (``None``: they never expire)."""

    units: int
    expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class BillingSummary:
    beneficiary: User
    audience: str
    subscription: Subscription | None
    tier: PlanTier | None
    pending_tier: PlanTier | None
    can_manage: bool
    managed_by_name: str | None
    saved_card: SavedCard | None
    meter_fraction: float | None
    meter_resets_at: datetime | None
    credits_balance: int
    credits: list[CreditLot]
    debt_units: int
    seat_capacity: int | None
    seats_used: int | None


def is_linked_student(session: Session, parent_id: uuid.UUID, child_id: uuid.UUID) -> bool:
    """True when ``child_id`` is a student the parent is linked to.

    ``parent_child_links`` ignores roles, so a link that points at a teacher or another parent
    must not open that user's billing: the same rule as checkout's ``_may_buy_for``.
    """
    if not is_linked_parent(session, parent_id, child_id):
        return False
    child = session.get(User, child_id)
    return child is not None and child.role is Role.student


def _live_subscription(session: Session, beneficiary_id: uuid.UUID) -> Subscription | None:
    """The beneficiary's plan in force: the paid row first (R25), then oldest, then id."""
    return session.scalars(
        select(Subscription)
        .where(
            Subscription.user_id == beneficiary_id,
            Subscription.status.in_(PLAN_LIVE_STATUSES),
        )
        .order_by(Subscription.payer_user_id.is_(None), Subscription.created_at, Subscription.id)
        .limit(1)
    ).one_or_none()


def _open_pending_subscription(session: Session, beneficiary_id: uuid.UUID) -> Subscription | None:
    """The newest first checkout still waiting for its payment, or ``None``.

    A pending row whose newest first payment failed (or was never opened) is a stale checkout
    that the next one replaces: showing it would tell a user to wait for a payment that is over.
    """
    pending = session.scalars(
        select(Subscription)
        .where(
            Subscription.user_id == beneficiary_id,
            Subscription.status == SubscriptionStatus.pending_first_payment,
        )
        .order_by(Subscription.created_at.desc(), Subscription.id)
        .limit(1)
    ).one_or_none()
    if pending is None:
        return None
    newest = session.scalars(
        select(Payment.status)
        .where(
            Payment.subscription_id == pending.id,
            Payment.purpose == PaymentPurpose.subscription_first,
        )
        .order_by(Payment.created_at.desc(), Payment.id)
        .limit(1)
    ).one_or_none()
    return pending if newest in _OPEN_FIRST_PAYMENT else None


def _credit_lots(lots: list[tuple[int, datetime | None]]) -> list[CreditLot]:
    """Sum lots per expiry, keeping ``meter_view``'s order (soonest first, no expiry last)."""
    by_expiry: dict[datetime | None, int] = {}
    for remaining, expires_at in lots:
        by_expiry[expires_at] = by_expiry.get(expires_at, 0) + remaining
    return [
        CreditLot(units=units, expires_at=expires_at) for expires_at, units in by_expiry.items()
    ]


def build_billing_summary(
    session: Session, *, caller_user_id: uuid.UUID, beneficiary_user_id: uuid.UUID, now: datetime
) -> BillingSummary:
    """Plan, period, allowance meter, credits by expiry, debt and (teachers) seats."""
    beneficiary = session.get(User, beneficiary_user_id)
    if beneficiary is None:
        raise LookupError(f"unknown user {beneficiary_user_id}")
    is_teacher = beneficiary.role is Role.teacher

    subscription = _live_subscription(session, beneficiary_user_id) or _open_pending_subscription(
        session, beneficiary_user_id
    )
    tier = session.get(PlanTier, subscription.plan_tier_id) if subscription else None
    pending_tier = (
        session.get(PlanTier, subscription.pending_plan_tier_id)
        if subscription is not None and subscription.pending_plan_tier_id is not None
        else None
    )

    payer_id = subscription.payer_user_id if subscription is not None else None
    if subscription is None:
        # Nothing to manage yet: the caller may start a plan if they may buy for the target.
        can_manage = caller_user_id == beneficiary_user_id or is_linked_student(
            session, caller_user_id, beneficiary_user_id
        )
    else:
        # A manual activation (no payer) is changed by a platform admin, never by a user.
        can_manage = payer_id == caller_user_id
    other_payer = (
        session.get(User, payer_id) if payer_id is not None and payer_id != caller_user_id else None
    )

    saved_card = None
    if can_manage:
        # The card is the payer's own; with no plan the caller is the prospective payer.
        saved_card = session.scalars(
            select(SavedCard)
            .where(SavedCard.user_id == caller_user_id, SavedCard.is_active.is_(True))
            .order_by(SavedCard.created_at.desc(), SavedCard.id)
            .limit(1)
        ).one_or_none()

    meter = meter_view(session, user_id=beneficiary_user_id, now=now)
    team = TeacherTeamService(session) if is_teacher else None
    return BillingSummary(
        beneficiary=beneficiary,
        audience="teacher" if is_teacher else "student",
        subscription=subscription,
        tier=tier,
        pending_tier=pending_tier,
        can_manage=can_manage,
        managed_by_name=other_payer.display_name if other_payer is not None else None,
        saved_card=saved_card,
        meter_fraction=meter.allowance_fraction,
        meter_resets_at=meter.allowance_resets_at,
        credits_balance=meter.credits_balance,
        credits=_credit_lots([(lot.remaining, lot.expires_at) for lot in meter.credit_lots]),
        debt_units=meter.debt_units,
        seat_capacity=team.seat_capacity(beneficiary_user_id) if team is not None else None,
        seats_used=team.seats_used(beneficiary_user_id) if team is not None else None,
    )


__all__ = ["BillingSummary", "CreditLot", "build_billing_summary", "is_linked_student"]
