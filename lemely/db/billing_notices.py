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


def enqueue_extra_seats_charge_failed(
    session: Session,
    *,
    payer_user_id: uuid.UUID,
    subscription_id: uuid.UUID,
    first_attempt_id: uuid.UUID,
) -> bool:
    """Queue the "your extra seats payment failed" notice to the payer.

    ``first_attempt_id`` is the first failed payment of the run of daily retries, so the payer
    hears once per run and not once per daily attempt. ``True`` when a row was written;
    ``False`` when billing notices are off or this run's notice is already queued.
    """
    return enqueue_in_session(
        session,
        recipient_user_id=payer_user_id,
        template="extra_seats_charge_failed",
        context={"subscription_id": subscription_id},
        dedupe_key=f"extra_seats_failed:{first_attempt_id}",
    )


__all__ = [
    "SubscriptionNoticeKind",
    "enqueue_auto_topup_failed",
    "enqueue_extra_seats_charge_failed",
    "enqueue_subscription_notice",
]
