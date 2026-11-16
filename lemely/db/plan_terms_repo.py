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
from typing import TYPE_CHECKING

import sqlalchemy as sa

from lemely.db.models.billing import PlanTier, PlanTierTerms, Subscription

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.orm import Session


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


__all__ = [
    "TierTerms",
    "current_terms_for",
    "pending_terms_for",
    "terms_for",
    "terms_in_force_for_next_period",
    "tier_for_terms",
    "tier_terms",
]
