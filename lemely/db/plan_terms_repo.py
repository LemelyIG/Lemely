"""The plan terms a subscription is on (UD13-A): one reader for every price and entitlement.

A tier's *terms* are its price, extra-seat price, allowance, included seats and seat allowance.
An admin edit appends the next ``plan_tier_terms`` version and moves ``plan_tiers.terms_version``;
a subscription keeps the version it was sold at (``subscriptions.terms_version``) until its first
renewal after the notice (``pending_terms_version``). Every module that prices or grants for an
EXISTING subscription reads its terms here and never the tier's live columns. New purchases (the
checkout, the public catalogue) read the tier: new customers get the current terms at once.

This module is a leaf of the db package: it imports only the models, so the seat and allowance
modules (which import nothing from the billing charge code) can use it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Final

import sqlalchemy as sa
import structlog
from sqlalchemy.orm import aliased

from lemely.core.billing_defaults import PRICE_CHANGE_NOTICE_DAYS
from lemely.core.subscription_rules import period_end, subscription_amount_minor
from lemely.db.billing_notices import enqueue_plan_terms_change, enqueue_plan_terms_ends
from lemely.db.models.billing import (
    PLAN_LIVE_STATUSES,
    PlanAudience,
    PlanTier,
    PlanTierTerms,
    Subscription,
)
from lemely.db.models.billing_ops import BillingSettings
from lemely.db.models.team import TeacherMember, TeacherMemberKind, TeacherMemberStatus

if TYPE_CHECKING:
    import uuid
    from datetime import datetime

    from sqlalchemy.orm import Session, sessionmaker

log = structlog.get_logger("lemely.db.plan_terms_repo")

#: Rows one sweep tick handles, oldest first; the rest wait for the next tick.
TERMS_NOTICE_BATCH: Final = 200


@dataclass(frozen=True, slots=True)
class TierTerms:
    """One immutable version of a tier's price and entitlements."""

    plan_tier_id: uuid.UUID
    terms_version: int
    price_minor: int
    extra_seat_price_minor: int
    allowance_units: int
    included_seats: int
    seat_allowance_units: int


def _as_terms(row: PlanTierTerms) -> TierTerms:
    return TierTerms(
        plan_tier_id=row.plan_tier_id,
        terms_version=row.terms_version,
        price_minor=int(row.price_minor),
        extra_seat_price_minor=int(row.extra_seat_price_minor),
        allowance_units=int(row.allowance_units),
        included_seats=int(row.included_seats),
        seat_allowance_units=int(row.seat_allowance_units),
    )


def tier_terms(session: Session, tier_id: uuid.UUID, terms_version: int) -> TierTerms | None:
    """The stored terms of ``tier_id`` at ``terms_version``, or ``None`` without such a row."""
    row = session.scalars(
        sa.select(PlanTierTerms).where(
            PlanTierTerms.plan_tier_id == tier_id,
            PlanTierTerms.terms_version == terms_version,
        )
    ).one_or_none()
    return None if row is None else _as_terms(row)


def current_terms_for(session: Session, tier: PlanTier) -> TierTerms:
    """The tier's current terms: what a new purchase of the tier is priced at.

    Raises:
        RuntimeError: the tier has no history row for its own version (the seed trigger and the
            admin write keep one, so this is a broken database).
    """
    terms = tier_terms(session, tier.id, tier.terms_version)
    if terms is None:
        raise RuntimeError(f"plan tier {tier.id} has no terms row for its version")
    return terms


def terms_for(session: Session, subscription: Subscription) -> TierTerms:
    """The terms the subscription is billed and granted on in this period.

    Raises:
        RuntimeError: no history row for the subscription's version (the composite foreign key
            makes this impossible in a consistent database).
    """
    terms = tier_terms(session, subscription.plan_tier_id, subscription.terms_version)
    if terms is None:
        raise RuntimeError(f"subscription {subscription.id} has no terms row for its version")
    return terms


def pending_terms_for(session: Session, subscription: Subscription) -> TierTerms | None:
    """The terms the subscription moves to at its renewal, or ``None`` when no move is pending."""
    if subscription.pending_terms_version is None:
        return None
    return tier_terms(session, subscription.plan_tier_id, subscription.pending_terms_version)


def terms_in_force_for_next_period(session: Session, subscription: Subscription) -> TierTerms:
    """The terms the NEXT period is billed and granted on.

    A pending plan change wins: the target tier's current terms apply (the change clears any
    pending terms when it is applied). Otherwise the pending terms apply when the period ends on
    or after their effective date (``current_period_end >= pending_terms_effective_at``), and the
    current terms apply when not. ``current_period_end`` is fixed within a period, so every
    evaluation in the amount-sync window gives the same answer.

    Raises:
        RuntimeError: a tier or terms row is missing.
    """
    if subscription.pending_plan_tier_id is not None:
        target = tier_for_terms(session, subscription.pending_plan_tier_id)
        return current_terms_for(session, target)
    effective_at = subscription.pending_terms_effective_at
    end = subscription.current_period_end
    if effective_at is not None and end is not None and end >= effective_at:
        pending = pending_terms_for(session, subscription)
        if pending is not None:
            return pending
    return terms_for(session, subscription)


def tier_for_terms(session: Session, tier_id: uuid.UUID) -> PlanTier:
    """The tier row (for its non-term fields), or a ``RuntimeError`` when it is gone."""
    tier = session.get(PlanTier, tier_id)
    if tier is None:
        raise RuntimeError(f"plan tier {tier_id} does not exist")
    return tier


# -- the notice (UD13-A, Part B) ----------------------------------------------------------


def renewal_amount(terms: TierTerms, extra_seats: int) -> int:
    """What one renewal costs on ``terms`` for a subscriber holding ``extra_seats``.

    Seats are counted only when the terms sell them (a tier with no seat price holds none).
    """
    return subscription_amount_minor(
        price_minor=terms.price_minor,
        extra_seats=extra_seats if terms.extra_seat_price_minor > 0 else 0,
        extra_seat_price_minor=terms.extra_seat_price_minor,
    )


def move_is_worse(current: TierTerms, new: TierTerms, *, extra_seats: int) -> bool:
    """A move is worse for the subscriber when it costs more or gives less (full notice period)."""
    return (
        renewal_amount(new, extra_seats) > renewal_amount(current, extra_seats)
        or new.allowance_units < current.allowance_units
        or new.included_seats < current.included_seats
        or new.seat_allowance_units < current.seat_allowance_units
    )


def first_applies_at(period_end_at: datetime, interval: str, effective_at: datetime) -> datetime:
    """The first period end on or after ``effective_at``: the renewal the new terms first apply to.

    ``period_end_at`` itself when it qualifies, otherwise the following ones.
    """
    end = period_end_at
    for _ in range(400):  # a bound: 90 days of notice over the shortest interval is far below it
        if end >= effective_at:
            return end
        end = period_end(end, interval)
    return end


def _live_paid_filters(S: type[Subscription], T: type[PlanTier]) -> list[sa.ColumnElement[bool]]:
    """Subscriptions that renew by themselves and have not asked to stop (the notice's pool).

    Complimentary rows (no payer) and manual activations do not renew, a cancelling subscriber is
    leaving anyway, and a pending plan change decides the next terms (the target's current ones).
    A move is owed when the tier has terms the subscription is not on, and not yet announced.
    """
    return [
        S.status.in_(PLAN_LIVE_STATUSES),
        S.payer_user_id.is_not(None),
        S.is_manually_activated.is_(False),
        S.cancel_at_period_end.is_(False),
        S.pending_plan_tier_id.is_(None),
        S.terms_version < T.terms_version,
        sa.or_(S.pending_terms_version.is_(None), S.pending_terms_version < T.terms_version),
    ]


def _notice_days(session: Session) -> int:
    days = session.scalar(sa.select(BillingSettings.price_change_notice_days))
    return PRICE_CHANGE_NOTICE_DAYS if days is None else int(days)


def _seats_held(session: Session, teacher_id: uuid.UUID) -> int:
    return int(
        session.scalar(
            sa.select(sa.func.count())
            .select_from(TeacherMember)
            .where(
                TeacherMember.teacher_user_id == teacher_id,
                TeacherMember.kind == TeacherMemberKind.student_seat,
                TeacherMember.status == TeacherMemberStatus.active,
            )
        )
        or 0
    )


def queue_terms_change_notices(
    sm: sessionmaker[Session],
    *,
    now: datetime,
    amount_updatable: bool,
    limit: int = TERMS_NOTICE_BATCH,
) -> int:
    """Announce each subscriber's move to the tier's newer terms; the count of rows handled.

    Job ``billing.terms_change_notices``. At most ``limit`` rows, oldest first, one transaction per
    row with ``FOR UPDATE SKIP LOCKED`` (a row another worker holds waits for the next tick). A
    row's failure is alerted and skipped.

    Per row: ``pending_terms_version`` is the tier's current version and ``terms_notice_sent_at``
    is ``now``. ``pending_terms_effective_at`` is ``now`` plus ``billing_settings.
    price_change_notice_days`` when the move is worse for this subscriber, else ``now``. The payer
    gets one notice (UD13-E: no amount) in the same transaction, unless nothing the subscriber can
    see changes. On the fixed-amount path (``amount_updatable`` false) a move that changes the
    renewal amount cannot be charged, so the notice says the plan ends and to subscribe again.

    Raises:
        ValueError: ``limit`` is below 1.
    """
    if limit < 1:
        raise ValueError("limit must be at least 1")
    S = Subscription
    with sm() as session:
        ids = list(
            session.scalars(
                sa.select(S.id)
                .join(PlanTier, PlanTier.id == S.plan_tier_id)
                .where(*_live_paid_filters(S, PlanTier))
                .order_by(S.created_at, S.id)
                .limit(limit)
            )
        )
    handled = 0
    for sub_id in ids:
        try:
            with sm.begin() as session:
                handled += _announce_one(
                    session, sub_id, now=now, amount_updatable=amount_updatable
                )
        except Exception:
            log.error(
                "terms_change_notice_failed",
                subscription_id=str(sub_id),
                alert=True,
                exc_info=True,
            )
    return handled


def _announce_one(
    session: Session, sub_id: uuid.UUID, *, now: datetime, amount_updatable: bool
) -> int:
    S = Subscription
    row = session.execute(
        sa.select(S, PlanTier)
        .join(PlanTier, PlanTier.id == S.plan_tier_id)
        .where(S.id == sub_id, *_live_paid_filters(S, PlanTier))
        .with_for_update(of=S, skip_locked=True)
    ).first()
    if row is None:
        return 0  # changed or locked since the read: the next tick decides
    sub, tier = row
    current = terms_for(session, sub)
    new = current_terms_for(session, tier)
    seats = sub.pending_extra_seats if sub.pending_extra_seats is not None else sub.extra_seats or 0
    worse = move_is_worse(current, new, extra_seats=seats)
    effective_at = now + timedelta(days=_notice_days(session)) if worse else now
    sub.pending_terms_version = new.terms_version
    sub.pending_terms_effective_at = effective_at
    sub.version = (sub.version or 0) + 1
    price_changes = renewal_amount(new, seats) != renewal_amount(current, seats)
    entitlements_change = (
        new.allowance_units != current.allowance_units
        or new.included_seats != current.included_seats
        or new.seat_allowance_units != current.seat_allowance_units
    )
    seats_over = 0
    if tier.audience is PlanAudience.teacher:
        capacity = new.included_seats + (seats if new.extra_seat_price_minor > 0 else 0)
        seats_over = max(0, _seats_held(session, sub.user_id) - capacity)
    if not (price_changes or entitlements_change or seats_over):
        return 1  # a change the subscriber cannot see (an unused seat price): moves without a mail
    assert tier.interval is not None  # noqa: S101 - a plan that renews has an interval
    applies_at = first_applies_at(sub.current_period_end or now, tier.interval.value, effective_at)
    sub.terms_notice_sent_at = now
    if price_changes and not amount_updatable:
        enqueue_plan_terms_ends(
            session, subscription=sub, terms_version=new.terms_version, ends_at=applies_at
        )
    else:
        enqueue_plan_terms_change(
            session,
            subscription=sub,
            terms_version=new.terms_version,
            applies_at=applies_at,
            price_changes=price_changes,
            entitlements_change=entitlements_change,
            seats_over=seats_over,
        )
    log.info(
        "subscription_terms_change_noticed",
        subscription_id=str(sub.id),
        terms_version=new.terms_version,
        worse=worse,
        effective_at=effective_at.isoformat(),
    )
    return 1


def fixed_path_move_ids(
    session: Session,
    *,
    now: datetime,
    limit: int = TERMS_NOTICE_BATCH,
    only: uuid.UUID | None = None,
) -> list[uuid.UUID]:
    """Subscriptions whose pending move changes the renewal amount and is due, oldest first.

    For the fixed-amount path (Paymob cannot change the amount): such a move is never applied by a
    renewal, so the plan is cancelled at its period end instead. Due means
    ``current_period_end >= pending_terms_effective_at``; a cancelling or plan-changing
    subscription is not a candidate. A move that leaves the amount unchanged is not one: it applies
    at the renewal. ``only`` narrows the answer to one row (the caller's re-check under its lock).
    """
    S = Subscription
    current = aliased(PlanTierTerms)
    pending = aliased(PlanTierTerms)
    seats = sa.func.coalesce(S.pending_extra_seats, S.extra_seats, 0)

    def amount(t: type[PlanTierTerms]) -> sa.ColumnElement[int]:
        return t.price_minor + sa.case(
            (t.extra_seat_price_minor > 0, seats * t.extra_seat_price_minor), else_=0
        )

    stmt = (
        sa.select(S.id)
        .join(
            current,
            sa.and_(
                current.plan_tier_id == S.plan_tier_id, current.terms_version == S.terms_version
            ),
        )
        .join(
            pending,
            sa.and_(
                pending.plan_tier_id == S.plan_tier_id,
                pending.terms_version == S.pending_terms_version,
            ),
        )
        .where(
            S.status.in_(PLAN_LIVE_STATUSES),
            S.payer_user_id.is_not(None),
            S.is_manually_activated.is_(False),
            S.cancel_at_period_end.is_(False),
            S.pending_plan_tier_id.is_(None),
            S.pending_terms_version.is_not(None),
            S.current_period_end >= S.pending_terms_effective_at,
            S.current_period_end > now,
            amount(current) != amount(pending),
        )
        .order_by(S.current_period_end, S.id)
        .limit(limit)
    )
    if only is not None:
        stmt = stmt.where(S.id == only)
    return list(session.scalars(stmt))


__all__ = [
    "TERMS_NOTICE_BATCH",
    "TierTerms",
    "current_terms_for",
    "first_applies_at",
    "fixed_path_move_ids",
    "move_is_worse",
    "pending_terms_for",
    "queue_terms_change_notices",
    "renewal_amount",
    "terms_for",
    "terms_in_force_for_next_period",
    "tier_for_terms",
    "tier_terms",
]
