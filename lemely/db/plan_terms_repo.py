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

import enum
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Final

import sqlalchemy as sa
import structlog
from sqlalchemy.orm import aliased

from lemely.core.billing_defaults import PRICE_CHANGE_NOTICE_DAYS
from lemely.core.subscription_rules import (
    AMOUNT_SYNC_WINDOW,
    period_end,
    subscription_amount_minor,
)
from lemely.db.billing_notices import (
    enqueue_plan_terms_cancelled,
    enqueue_plan_terms_change,
    enqueue_plan_terms_ends,
)
from lemely.db.models.billing import (
    PLAN_LIVE_STATUSES,
    PlanAudience,
    PlanTier,
    PlanTierTerms,
    Subscription,
)
from lemely.db.models.billing_ops import BillingSettings
from lemely.db.models.team import TeacherMember, TeacherMemberKind, TeacherMemberStatus
from lemely.db.models.tutoring import EmailOutbox

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


def _as_terms(history: PlanTierTerms) -> TierTerms:
    return TierTerms(
        plan_tier_id=history.plan_tier_id,
        terms_version=history.terms_version,
        price_minor=int(history.price_minor),
        extra_seat_price_minor=int(history.extra_seat_price_minor),
        allowance_units=int(history.allowance_units),
        included_seats=int(history.included_seats),
        seat_allowance_units=int(history.seat_allowance_units),
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


def same_terms(cur_terms: TierTerms, new_terms: TierTerms) -> bool:
    """Identical in every billed term (the only change that may skip the notice)."""
    return (
        cur_terms.price_minor,
        cur_terms.extra_seat_price_minor,
        cur_terms.allowance_units,
        cur_terms.included_seats,
        cur_terms.seat_allowance_units,
    ) == (
        new_terms.price_minor,
        new_terms.extra_seat_price_minor,
        new_terms.allowance_units,
        new_terms.included_seats,
        new_terms.seat_allowance_units,
    )


def price_terms_differ(cur_terms: TierTerms, new_terms: TierTerms) -> bool:
    """The price or the seat price differs (judged on the terms, not on the seats held today)."""
    return (
        cur_terms.price_minor != new_terms.price_minor
        or cur_terms.extra_seat_price_minor != new_terms.extra_seat_price_minor
    )


def move_is_worse(cur_terms: TierTerms, new_terms: TierTerms) -> bool:
    """A move is worse when any term costs more or gives less: it waits the full notice period.

    Judged on the terms alone. A seat price that rises is worse whatever number of extra seats the
    subscriber holds today, because a later seat purchase would be priced at it. A seat price that
    falls to 0 is worse too: the tier then sells no extra seats, and a subscriber holding some
    loses them at the renewal (UD13-A, UD13-G).
    """
    return (
        new_terms.price_minor > cur_terms.price_minor
        or new_terms.extra_seat_price_minor > cur_terms.extra_seat_price_minor
        or (cur_terms.extra_seat_price_minor > 0 and new_terms.extra_seat_price_minor == 0)
        or new_terms.allowance_units < cur_terms.allowance_units
        or new_terms.included_seats < cur_terms.included_seats
        or new_terms.seat_allowance_units < cur_terms.seat_allowance_units
    )


def allowed_terms_for_amount(
    session: Session, subscription: Subscription, amount_minor: int
) -> TierTerms | None:
    """The terms a renewal charged at ``amount_minor`` may be settled on, or ``None``.

    Only two versions are allowed: the subscriber's CURRENT one, and their own pending version once
    it was announced and its effective date has passed for this period (the same rule as
    :func:`terms_in_force_for_next_period`). The amount is priced at the CURRENT seat count, the one
    the period is granted on. A version the subscriber was never told about, or whose notice has
    not run out, can never match; on a tie the current version wins.
    """
    seats = subscription.extra_seats or 0
    current = terms_for(session, subscription)
    if renewal_amount(current, seats) == amount_minor:
        return current
    effective_at = subscription.pending_terms_effective_at
    end = subscription.current_period_end
    if (
        subscription.pending_terms_version is not None
        and subscription.terms_notice_sent_at is not None
        and effective_at is not None
        and end is not None
        and end >= effective_at
    ):
        pending = pending_terms_for(session, subscription)
        if pending is not None and renewal_amount(pending, seats) == amount_minor:
            return pending
    return None


def other_version_priced_at(
    session: Session, subscription: Subscription, amount_minor: int
) -> int | None:
    """A version of the tier other than the subscriber's current one that prices to the amount.

    For the alert that names the cause of an unexplained charge (a push an edit or a revert has
    since overtaken): the highest such version, or ``None``.
    """
    seats = subscription.extra_seats or 0
    versions = session.scalars(
        sa.select(PlanTierTerms)
        .where(
            PlanTierTerms.plan_tier_id == subscription.plan_tier_id,
            PlanTierTerms.terms_version != subscription.terms_version,
        )
        .order_by(PlanTierTerms.terms_version.desc())
    ).all()
    for history in versions:
        if renewal_amount(_as_terms(history), seats) == amount_minor:
            return int(history.terms_version)
    return None


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
    price_change_notice_days`` when the move is worse (judged on the terms, not the seats held
    today), else ``now``. On the fixed-amount path (``amount_updatable`` false) any move of the
    price or the seat price gets the full notice period, up or down: the move ends the plan, so a
    price cut never takes effect at once. The payer gets one notice (UD13-E: no amount) in the same
    transaction; a move identical in every billed term skips it. A move identical to the terms the
    subscriber is on (an admin revert) cancels a pending move and, when that move had been
    announced, says so. On the fixed path a move that changes the renewal amount cannot be
    charged, so the notice says the plan ends and to subscribe again.

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
        reverts = list(
            session.scalars(
                sa.select(S.id)
                .where(*_platform_cancelled_filters(S))
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
    for sub_id in reverts:
        try:
            with sm.begin() as session:
                handled += _revert_platform_cancelled_one(
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
    cur_terms = terms_for(session, sub)
    new_terms = current_terms_for(session, tier)
    seats = sub.pending_extra_seats if sub.pending_extra_seats is not None else sub.extra_seats or 0
    if same_terms(cur_terms, new_terms):
        _take_back(session, sub, new_terms, now=now, amount_updatable=amount_updatable)
        return 1
    worse = move_is_worse(cur_terms, new_terms)
    price_changes = price_terms_differ(cur_terms, new_terms)
    amount_changes = renewal_amount(new_terms, seats) != renewal_amount(cur_terms, seats)
    full_notice = worse or (price_changes and not amount_updatable)
    effective_at = now + timedelta(days=_notice_days(session)) if full_notice else now
    sub.pending_terms_version = new_terms.terms_version
    sub.pending_terms_effective_at = effective_at
    sub.version = (sub.version or 0) + 1
    entitlements_change = (
        new_terms.allowance_units != cur_terms.allowance_units
        or new_terms.included_seats != cur_terms.included_seats
        or new_terms.seat_allowance_units != cur_terms.seat_allowance_units
    )
    seats_over = 0
    if tier.audience is PlanAudience.teacher:
        capacity = new_terms.included_seats + (seats if new_terms.extra_seat_price_minor > 0 else 0)
        seats_over = max(0, _seats_held(session, sub.user_id) - capacity)
    assert tier.interval is not None  # noqa: S101 - a plan that renews has an interval
    applies_at = first_applies_at(sub.current_period_end or now, tier.interval.value, effective_at)
    sub.terms_notice_sent_at = now
    if amount_changes and not amount_updatable:
        enqueue_plan_terms_ends(
            session, subscription=sub, terms_version=new_terms.terms_version, ends_at=applies_at
        )
    else:
        enqueue_plan_terms_change(
            session,
            subscription=sub,
            terms_version=new_terms.terms_version,
            applies_at=applies_at,
            price_changes=price_changes,
            entitlements_change=entitlements_change,
            seats_over=seats_over,
        )
    log.info(
        "subscription_terms_change_noticed",
        subscription_id=str(sub.id),
        terms_version=new_terms.terms_version,
        worse=worse,
        effective_at=effective_at.isoformat(),
    )
    return 1


def _take_back(
    session: Session,
    sub: Subscription,
    new_terms: TierTerms,
    *,
    now: datetime,
    amount_updatable: bool,
    cancelled_by_platform: bool = False,
) -> None:
    """An admin revert: the tier's terms equal the ones the subscriber is on. Cancel the move.

    The subscriber moves to the tier's version at once (identical terms: nothing changes for
    them), the pending move is cleared, and a move that had been announced is taken back by mail.
    When the platform's own fixed-path cancel for that move was scheduled and Paymob has not been
    told, it is withdrawn too. When Paymob's pushed amount is still the reverted one inside the
    amount-sync window, the amount is marked uncertain so the sweep puts the right one back.
    """
    announced = sub.pending_terms_version is not None and (
        sub.terms_notice_sent_at is not None or cancelled_by_platform
    )
    seats = sub.pending_extra_seats if sub.pending_extra_seats is not None else sub.extra_seats or 0
    end = sub.current_period_end
    if (
        amount_updatable
        and sub.paymob_amount_minor is not None
        and end is not None
        and end - now <= AMOUNT_SYNC_WINDOW
        and sub.paymob_amount_minor != renewal_amount(new_terms, seats)
    ):
        sub.amount_sync_uncertain_at = now
    if cancelled_by_platform:
        sub.cancel_at_period_end = False
    sub.terms_version = new_terms.terms_version
    sub.pending_terms_version = None
    sub.pending_terms_effective_at = None
    sub.terms_notice_sent_at = None
    sub.version = (sub.version or 0) + 1
    if announced:
        enqueue_plan_terms_cancelled(
            session, subscription=sub, terms_version=new_terms.terms_version
        )
    log.info(
        "subscription_terms_move_cancelled",
        subscription_id=str(sub.id),
        terms_version=new_terms.terms_version,
        announced=announced,
        cancel_withdrawn=cancelled_by_platform,
    )


def _revert_platform_cancelled_one(
    session: Session, sub_id: uuid.UUID, *, now: datetime, amount_updatable: bool
) -> int:
    """Withdraw the platform's fixed-path cancel when the admin has since reverted the move.

    The marker of a platform cancel is a cancelling row with a pending move and no notice stamp
    (the job clears the stamp when it schedules the cancel; a payer's own cancel keeps it), not yet
    pushed to Paymob. Nothing is withdrawn once Paymob holds the cancel.
    """
    S = Subscription
    row = session.execute(
        sa.select(S, PlanTier)
        .join(PlanTier, PlanTier.id == S.plan_tier_id)
        .where(S.id == sub_id, *_platform_cancelled_filters(S))
        .with_for_update(of=S, skip_locked=True)
    ).first()
    if row is None:
        return 0
    sub, tier = row
    new_terms = current_terms_for(session, tier)
    if not same_terms(terms_for(session, sub), new_terms):
        return 0
    _take_back(
        session,
        sub,
        new_terms,
        now=now,
        amount_updatable=amount_updatable,
        cancelled_by_platform=True,
    )
    return 1


def _platform_cancelled_filters(S: type[Subscription]) -> list[sa.ColumnElement[bool]]:
    return [
        S.status.in_(PLAN_LIVE_STATUSES),
        S.payer_user_id.is_not(None),
        S.is_manually_activated.is_(False),
        S.cancel_at_period_end.is_(True),
        S.paymob_cancelled_at.is_(None),
        S.pending_terms_version.is_not(None),
        S.terms_notice_sent_at.is_(None),
    ]


def is_platform_cancel(sub: Subscription) -> bool:
    """The platform's own fixed-path cancel for a terms move (not the payer's).

    A cancelling row with a pending move and no notice stamp: the fixed-path job clears the stamp
    when it schedules the cancel, and a payer's own cancel keeps the stamp it was noticed with.
    """
    return (
        sub.cancel_at_period_end
        and sub.pending_terms_version is not None
        and sub.terms_notice_sent_at is None
    )


@dataclass(frozen=True, slots=True)
class PendingTermsChange:
    """A noticed move to the tier's newer terms, as the payer's billing screen shows it."""

    effective_at: datetime
    first_renewal_at: datetime | None
    new_terms: TierTerms
    price_changes: bool
    allowance_changes: bool
    included_seats_changes: bool
    seat_allowance_changes: bool
    ends_instead_of_moving: bool


def pending_terms_change(
    session: Session, sub: Subscription, *, interval: str | None, amount_updatable: bool
) -> PendingTermsChange | None:
    """The move pending for ``sub``, or ``None`` when none is (or a plan change decides instead).

    ``ends_instead_of_moving`` is the fixed-amount path: Paymob cannot charge the new amount, so a
    move that changes the renewal amount ends the plan at the period end.
    """
    effective_at = sub.pending_terms_effective_at
    if sub.pending_terms_version is None or effective_at is None or sub.pending_plan_tier_id:
        return None
    new_terms = pending_terms_for(session, sub)
    if new_terms is None:
        return None
    cur_terms = terms_for(session, sub)
    seats = sub.pending_extra_seats if sub.pending_extra_seats is not None else sub.extra_seats or 0
    end = sub.current_period_end
    return PendingTermsChange(
        effective_at=effective_at,
        first_renewal_at=(
            first_applies_at(end, interval, effective_at)
            if end is not None and interval is not None
            else None
        ),
        new_terms=new_terms,
        price_changes=price_terms_differ(cur_terms, new_terms),
        allowance_changes=new_terms.allowance_units != cur_terms.allowance_units,
        included_seats_changes=new_terms.included_seats != cur_terms.included_seats,
        seat_allowance_changes=new_terms.seat_allowance_units != cur_terms.seat_allowance_units,
        ends_instead_of_moving=(
            not amount_updatable
            and renewal_amount(new_terms, seats) != renewal_amount(cur_terms, seats)
        ),
    )


def subscribers_to_move(session: Session, tier_id: uuid.UUID) -> int:
    """Renewing subscribers of the tier not yet on its current terms: those a terms edit moves.

    Complimentary and manual rows do not renew, and a cancelling subscriber is leaving: neither is
    noticed or moved (the same pool as the notice job, before its pending-version filter).
    """
    S = Subscription
    return int(
        session.scalar(
            sa.select(sa.func.count())
            .select_from(S)
            .join(PlanTier, PlanTier.id == S.plan_tier_id)
            .where(
                S.plan_tier_id == tier_id,
                S.status.in_(PLAN_LIVE_STATUSES),
                S.payer_user_id.is_not(None),
                S.is_manually_activated.is_(False),
                S.cancel_at_period_end.is_(False),
                S.terms_version < PlanTier.terms_version,
            )
        )
        or 0
    )


class FixedPathEnd(enum.Enum):
    """What the fixed-path job does after looking at a move's "your plan ends" notice."""

    SENT = "sent"  # the mail was written now: wait out the notice period before cancelling
    TOO_LATE = "too_late"  # the period ends sooner than the notice period: no mail, no cancel
    ANNOUNCED = "announced"  # the subscriber was already told (or has notices off): cancel


def announce_fixed_path_end(session: Session, sub: Subscription, *, now: datetime) -> FixedPathEnd:
    """Make sure the payer has been told the plan ends, at least the notice period ahead.

    The notice sent when the edit was seen may have said "your plan changes" only (a seat price
    edit at no seats held: the amount changed later). The mail naming the end date is written here
    and the notice clock restarts, so the cancel waits until the period end is at least the notice
    period after it. A period that ends sooner is neither mailed nor cancelled: it renews and the
    move waits for the next one.
    """
    version = sub.pending_terms_version
    end = sub.current_period_end
    assert version is not None and end is not None  # noqa: S101 - the selection guarantees both
    seen = session.scalar(
        sa.select(EmailOutbox.id).where(EmailOutbox.dedupe_key == f"terms_ends:{sub.id}:{version}")
    )
    if seen is not None:
        return FixedPathEnd.ANNOUNCED
    if end < now + timedelta(days=_notice_days(session)):
        return FixedPathEnd.TOO_LATE
    written = enqueue_plan_terms_ends(session, subscription=sub, terms_version=version, ends_at=end)
    if not written:
        return FixedPathEnd.ANNOUNCED  # notices are off for this payer: nothing to wait for
    sub.terms_notice_sent_at = now
    sub.version = (sub.version or 0) + 1
    return FixedPathEnd.SENT


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
    ``current_period_end >= pending_terms_effective_at`` AND the period ends no sooner than the
    notice period after the email (``terms_notice_sent_at`` plus ``price_change_notice_days``): a
    move that became amount-changing after the notice (a seat bought since) never cancels a plan
    sooner than the subscriber was promised. A cancelling or plan-changing subscription is not a
    candidate. A move that leaves the amount unchanged is not one: it applies at the renewal.
    ``only`` narrows the answer to one row (the caller's re-check under its lock).
    """
    S = Subscription
    notice_days = sa.func.coalesce(
        sa.select(BillingSettings.price_change_notice_days).scalar_subquery(),
        PRICE_CHANGE_NOTICE_DAYS,
    )
    current = aliased(PlanTierTerms)
    pending = aliased(PlanTierTerms)
    seats = sa.func.coalesce(S.pending_extra_seats, S.extra_seats, 0)

    def amount(alias: type[PlanTierTerms]) -> sa.ColumnElement[int]:
        return alias.price_minor + sa.case(
            (alias.extra_seat_price_minor > 0, seats * alias.extra_seat_price_minor), else_=0
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
            S.terms_notice_sent_at.is_not(None),
            S.current_period_end
            >= S.terms_notice_sent_at + sa.func.make_interval(0, 0, 0, notice_days),
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
    "FixedPathEnd",
    "PendingTermsChange",
    "TierTerms",
    "allowed_terms_for_amount",
    "announce_fixed_path_end",
    "current_terms_for",
    "first_applies_at",
    "fixed_path_move_ids",
    "is_platform_cancel",
    "move_is_worse",
    "other_version_priced_at",
    "pending_terms_change",
    "pending_terms_for",
    "price_terms_differ",
    "queue_terms_change_notices",
    "renewal_amount",
    "same_terms",
    "subscribers_to_move",
    "terms_for",
    "terms_in_force_for_next_period",
    "tier_for_terms",
    "tier_terms",
]
