"""Auto top-up enqueue: one queued charge per threshold crossing (spec §5.5 steps 1-2).

The post-settle hook (registered by ``create_app``) calls :func:`enqueue_auto_topup` for every
credits owner a settled job drew on. It only enqueues: it runs inside the settle's transaction
with the chain owners' advisory locks held, so it does no network I/O. A later job (Phase 06
T8) claims the queued row and charges the saved card (MOTO, the payer being away, UD-P1).

Lock order: ledger before setting. Inside a settle the ledger owner advisory locks are already
held, and the ``auto_topup_settings`` row lock (``FOR UPDATE``) is taken after them. Every other
path that locks a setting keeps the same order: the charge handler locks the ledger, then the
setting; the failure sweep and the settings PUT lock the setting alone, never the setting then
the ledger.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import sqlalchemy as sa
import structlog

from lemely.core.subscription_rules import calendar_month_bounds
from lemely.core.usage_types import GrantScope, Payer
from lemely.db.billing_repo import is_linked_parent
from lemely.db.merchant_charge_repo import IN_FLIGHT_STATUSES, insert_queued_payment
from lemely.db.models.billing import (
    AutoTopupSettings,
    CreditPack,
    Payment,
    PaymentPurpose,
    PaymentStatus,
)
from lemely.db.usage_ledger_repo import UsageLedger

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence
    from datetime import datetime

    from sqlalchemy.orm import Session

    from lemely.db.models.usage import UsageJob

log = structlog.get_logger(__name__)

AUTO_TOPUP_DEDUPE_PREFIX: Final = "auto_topup:"

#: ``auto_topup_settings.disabled_reason`` values the built frontend recognises (DV-10).
DISABLED_CHARGE_FAILED: Final = "charge_failed"
DISABLED_PARENT_UNLINKED: Final = "parent_unlinked"


def spent_this_month(session: Session, beneficiary_user_id: uuid.UUID, *, now: datetime) -> int:
    """Minor units of in-flight and paid auto top-ups created in ``now``'s UTC calendar month."""
    start, end = calendar_month_bounds(now)
    total = session.scalar(
        sa.select(sa.func.coalesce(sa.func.sum(Payment.amount_minor), 0)).where(
            Payment.beneficiary_user_id == beneficiary_user_id,
            Payment.purpose == PaymentPurpose.auto_topup,
            Payment.status.in_((*IN_FLIGHT_STATUSES, PaymentStatus.paid)),
            Payment.created_at >= start,
            Payment.created_at < end,
        )
    )
    return int(total or 0)


def enqueue_auto_topup(
    session: Session, owner_user_id: uuid.UUID, *, now: datetime
) -> Payment | None:
    """Queue at most one top-up per threshold crossing; ``None`` when nothing is queued.

    Runs in the caller's transaction and locks the setting row, so two concurrent settles for
    one owner cannot both enqueue.
    """
    setting = session.execute(
        sa.select(AutoTopupSettings)
        .where(AutoTopupSettings.beneficiary_user_id == owner_user_id)
        .with_for_update()
    ).scalar_one_or_none()
    if setting is None or not setting.enabled or setting.saved_card_id is None:
        return None
    if setting.payer_user_id != owner_user_id and not is_linked_parent(
        session, setting.payer_user_id, owner_user_id
    ):
        setting.enabled = False
        setting.disabled_reason = DISABLED_PARENT_UNLINKED
        session.flush()
        log.warning("auto_topup_parent_unlinked", beneficiary=str(owner_user_id))
        return None
    credits = UsageLedger(session).available(
        [Payer(owner_user_id=owner_user_id, scope=GrantScope.CREDITS)], now=now
    )
    if credits >= setting.threshold_units:
        if not setting.armed:
            setting.armed = True
            setting.crossing_seq += 1
            session.flush()
        return None
    if not setting.armed:
        return None
    pack = session.get(CreditPack, setting.credit_pack_id)
    if pack is None or not pack.is_active or pack.price_minor <= 0:
        log.warning("auto_topup_pack_unusable", beneficiary=str(owner_user_id))
        return None
    in_flight = session.scalar(
        sa.select(Payment.id)
        .where(
            Payment.beneficiary_user_id == owner_user_id,
            Payment.purpose == PaymentPurpose.auto_topup,
            Payment.status.in_(IN_FLIGHT_STATUSES),
        )
        .limit(1)
    )
    if in_flight is not None:
        return None
    if (
        spent_this_month(session, owner_user_id, now=now) + pack.price_minor
        > setting.monthly_cap_minor
    ):
        return None
    payment = insert_queued_payment(
        session,
        purpose=PaymentPurpose.auto_topup,
        payer_user_id=setting.payer_user_id,
        beneficiary_user_id=owner_user_id,
        amount_minor=pack.price_minor,
        currency=pack.currency,
        credit_pack_id=pack.id,
        dedupe_key=f"{AUTO_TOPUP_DEDUPE_PREFIX}{owner_user_id}:{setting.crossing_seq}",
    )
    if payment is None:
        return None
    setting.armed = False
    setting.last_payment_id = payment.id
    session.flush()
    return payment


def auto_topup_post_settle_hook(
    session: Session, job: UsageJob, payers: Sequence[Payer], now: datetime
) -> None:
    """Post-settle hook: check auto top-up for each distinct credits owner, in chain order."""
    owners = dict.fromkeys(p.owner_user_id for p in payers if p.scope is GrantScope.CREDITS)
    for owner in owners:
        enqueue_auto_topup(session, owner, now=now)


__all__ = [
    "AUTO_TOPUP_DEDUPE_PREFIX",
    "DISABLED_CHARGE_FAILED",
    "DISABLED_PARENT_UNLINKED",
    "auto_topup_post_settle_hook",
    "enqueue_auto_topup",
    "spent_this_month",
]
