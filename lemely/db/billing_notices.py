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


__all__ = [
    "SubscriptionNoticeKind",
    "enqueue_auto_topup_card_missing",
    "enqueue_auto_topup_failed",
    "enqueue_auto_topup_phone_required",
    "enqueue_extra_seats_charge_failed",
    "enqueue_subscription_notice",
]
