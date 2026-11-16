"""Subscription notices through the transactional email outbox (Paymob billing spec §3 Jobs).

The payer hears about renewals, failed renewals, expiry and cancellation. The beneficiary (a
child, when a parent pays) sees the plan in the app instead. The row is written in the caller's
transaction, so the notice commits or rolls back with the state change it describes.

Billing notices are exempt from the outbox's daily cap (UD-9): the delivery job neither skips
them for it nor counts them toward it. They only leave the building where an email provider is
configured (the mock records them as ``skipped``).
"""

from __future__ import annotations

from datetime import UTC
from typing import TYPE_CHECKING, Literal

from lemely.db.email_outbox_repo import enqueue_in_session

if TYPE_CHECKING:
    import uuid
    from datetime import datetime

    from sqlalchemy.orm import Session

    from lemely.db.models.billing import Subscription

SubscriptionNoticeKind = Literal["renewed", "payment_failed", "expired", "cancelled", "credited"]


def enqueue_subscription_notice(
    session: Session,
    *,
    subscription: Subscription,
    notice: SubscriptionNoticeKind,
    effective_at: datetime,
) -> bool:
    """Queue one notice to the payer. ``True`` when a row was written.

    ``False`` when the subscription has no payer (a manual activation), the payer switched
    billing notices off, or this notice for this instant is already queued. The dedupe key
    names the instant in UTC, so the same instant written in two offsets is one notice.

    Raises:
        ValueError: ``effective_at`` is naive (it would be read as local time).
    """
    if effective_at.tzinfo is None or effective_at.utcoffset() is None:
        raise ValueError("effective_at must be timezone-aware")
    if subscription.payer_user_id is None:
        return False
    instant = effective_at.astimezone(UTC)
    return enqueue_in_session(
        session,
        recipient_user_id=subscription.payer_user_id,
        template="subscription_notice",
        context={
            "subscription_id": subscription.id,
            "notice": notice,
            "effective_at": instant,
        },
        dedupe_key=f"subscription:{subscription.id}:{notice}:{instant.isoformat()}",
    )


def enqueue_auto_topup_failed(
    session: Session, *, payer_user_id: uuid.UUID, payment_id: uuid.UUID
) -> bool:
    """Queue the "auto top-up could not charge your card" notice to the payer.

    ``True`` when a row was written; ``False`` when the payer switched billing notices off or
    this payment's notice is already queued. One notice per failed payment: a later failure is
    a new payment and a new notice.
    """
    return enqueue_in_session(
        session,
        recipient_user_id=payer_user_id,
        template="auto_topup_failed",
        context={"payment_id": payment_id},
        dedupe_key=f"auto_topup_failed:{payment_id}",
    )


def enqueue_auto_topup_card_missing(
    session: Session, *, payer_user_id: uuid.UUID, setting_id: uuid.UUID, crossing_seq: int
) -> bool:
    """Queue the "auto top-up is off, your saved card was removed" notice to the payer.

    No payment exists for this case (no charge was attempted), so the key is the setting and its
    crossing: one notice per disable, and a later disable after a re-enable (which bumps
    ``crossing_seq``) is a new notice. ``True`` when a row was written; ``False`` when the payer
    switched billing notices off or this disable is already noticed.
    """
    return enqueue_in_session(
        session,
        recipient_user_id=payer_user_id,
        template="auto_topup_card_missing",
        context={"setting_id": setting_id},
        dedupe_key=f"auto_topup_card_missing:{setting_id}:{crossing_seq}",
    )


def enqueue_auto_topup_phone_required(
    session: Session, *, payer_user_id: uuid.UUID, setting_id: uuid.UUID, crossing_seq: int
) -> bool:
    """Queue the "auto top-up is off, add a mobile number" notice to the payer.

    No charge was attempted (the processor needs a phone for every background charge), so the key
    is the setting and its crossing, as for :func:`enqueue_auto_topup_card_missing`. ``True`` when
    a row was written; ``False`` when billing notices are off or this disable is already noticed.
    """
    return enqueue_in_session(
        session,
        recipient_user_id=payer_user_id,
        template="auto_topup_phone_required",
        context={"setting_id": setting_id},
        dedupe_key=f"auto_topup_phone_required:{setting_id}:{crossing_seq}",
    )


def enqueue_extra_seats_charge_failed(
    session: Session,
    *,
    payer_user_id: uuid.UUID,
    subscription_id: uuid.UUID,
    first_attempt_id: uuid.UUID,
    grace_days: int,
) -> bool:
    """Queue the "your extra seats payment failed" notice to the payer.

    ``grace_days`` is the grace this run started with (``billing_settings.grace_days`` then), so
    the copy names the days the payer really has.

    ``first_attempt_id`` is the first failed payment of the run of daily retries, so the payer
    hears once per run and not once per daily attempt. ``True`` when a row was written;
    ``False`` when billing notices are off or this run's notice is already queued.
    """
    return enqueue_in_session(
        session,
        recipient_user_id=payer_user_id,
        template="extra_seats_charge_failed",
        context={"subscription_id": subscription_id, "grace_days": grace_days},
        dedupe_key=f"extra_seats_failed:{first_attempt_id}",
    )


def enqueue_plan_terms_change(
    session: Session,
    *,
    subscription: Subscription,
    terms_version: int,
    applies_at: datetime,
    price_changes: bool,
    entitlements_change: bool,
    seats_over: int,
) -> bool:
    """Queue the "your plan's terms change on DATE" notice to the payer (UD13-A, UD13-E).

    ``applies_at`` is the first renewal the new terms apply to. No amount is stated. One notice per
    subscription and terms version: a newer edit is a new version and a new notice. ``False`` when
    the subscription has no payer, the payer switched billing notices off, or it is already queued.

    Raises:
        ValueError: ``applies_at`` is naive.
    """
    if applies_at.tzinfo is None or applies_at.utcoffset() is None:
        raise ValueError("applies_at must be timezone-aware")
    if subscription.payer_user_id is None:
        return False
    return enqueue_in_session(
        session,
        recipient_user_id=subscription.payer_user_id,
        template="plan_terms_change",
        context={
            "subscription_id": subscription.id,
            "applies_at": applies_at.astimezone(UTC),
            "price_changes": price_changes,
            "entitlements_change": entitlements_change,
            "seats_over": seats_over,
        },
        dedupe_key=f"terms_change:{subscription.id}:{terms_version}",
    )


def enqueue_plan_terms_ends(
    session: Session, *, subscription: Subscription, terms_version: int, ends_at: datetime
) -> bool:
    """Queue the "your plan ends on DATE, subscribe again" notice (the fixed-amount path).

    Its own dedupe key (``terms_ends:``): the move may first have been announced as a plain change
    (a seat price edit with no seats held) and the "your plan ends" mail still has to go out when
    the change turns out to alter the amount. ``False`` as for :func:`enqueue_plan_terms_change`.

    Raises:
        ValueError: ``ends_at`` is naive.
    """
    if ends_at.tzinfo is None or ends_at.utcoffset() is None:
        raise ValueError("ends_at must be timezone-aware")
    if subscription.payer_user_id is None:
        return False
    return enqueue_in_session(
        session,
        recipient_user_id=subscription.payer_user_id,
        template="plan_terms_ends",
        context={"subscription_id": subscription.id, "ends_at": ends_at.astimezone(UTC)},
        dedupe_key=f"terms_ends:{subscription.id}:{terms_version}",
    )


def enqueue_charge_after_plan_end(
    session: Session, *, payer_user_id: uuid.UUID, payment_id: uuid.UUID
) -> bool:
    """Queue the "we received a payment after your plan was set to end; we will refund it" notice.

    For a renewal charge kept without a period because the platform had cancelled the plan for a
    price change. No amount is stated. One per payment. ``True`` when a row was written; ``False``
    when billing notices are off or this payment's notice is already queued.
    """
    return enqueue_in_session(
        session,
        recipient_user_id=payer_user_id,
        template="charge_after_plan_end",
        context={"payment_id": payment_id},
        dedupe_key=f"charge_after_plan_end:{payment_id}",
    )


def enqueue_plan_terms_cancelled(
    session: Session,
    *,
    subscription: Subscription,
    terms_version: int,
    plan_continues: bool = False,
) -> bool:
    """Queue the "the change to your plan will not happen" notice (an admin reverted the edit).

    Sent only for a move that had been announced. ``plan_continues`` is the variant for a plan
    that had been told it ends: the cancel is withdrawn, the plan renews and charges the card. No
    amount is stated. One per subscription and
    terms version. ``False`` when the subscription has no payer, the payer switched billing notices
    off, or it is already queued.
    """
    if subscription.payer_user_id is None:
        return False
    return enqueue_in_session(
        session,
        recipient_user_id=subscription.payer_user_id,
        template="plan_terms_cancelled",
        context={"subscription_id": subscription.id, "plan_continues": plan_continues},
        dedupe_key=f"terms_change_cancelled:{subscription.id}:{terms_version}",
    )


__all__ = [
    "SubscriptionNoticeKind",
    "enqueue_auto_topup_card_missing",
    "enqueue_auto_topup_failed",
    "enqueue_auto_topup_phone_required",
    "enqueue_charge_after_plan_end",
    "enqueue_extra_seats_charge_failed",
    "enqueue_plan_terms_cancelled",
    "enqueue_plan_terms_change",
    "enqueue_plan_terms_ends",
    "enqueue_subscription_notice",
]
