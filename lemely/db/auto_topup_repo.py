"""Auto top-up enqueue: one queued charge per threshold crossing (spec §5.5 steps 1-2).

The post-settle hook (registered by ``create_app``) calls :func:`enqueue_auto_topup` for every
credits owner a settled job drew on. It only enqueues: it runs inside the settle's transaction
with the chain owners' advisory locks held, so it does no network I/O. :func:`run_auto_topup_job`
claims the queued row and charges the saved card (MOTO, the payer being away, UD-P1); the paid
handler grants the credits and re-arms the setting; a failure sweep switches a setting off after a
failed charge. The settings service (:func:`get_auto_topup`, :func:`put_auto_topup`) is what the
routes call. Every "month" here is the UTC calendar month (DV-19).

Lock order: payment, event, ledger, then setting. Inside a settle the ledger owner advisory locks
are already held, and the ``auto_topup_settings`` row lock (``FOR UPDATE``) is taken after them.
Every other path that locks a setting keeps the same order: the paid handler locks the ledger (the
grant), then the setting; the failure sweep and the settings PUT lock the setting alone, never the
setting then the ledger.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import sqlalchemy as sa
import structlog

from lemely.core.subscription_rules import calendar_month_bounds
from lemely.core.usage_types import GrantScope, Payer
from lemely.db.billing_notices import (
    enqueue_auto_topup_card_missing,
    enqueue_auto_topup_failed,
)
from lemely.db.billing_repo import (
    add_months,
    credit_validity_months,
    is_linked_parent,
    payer_phone,
    register_paid_handler,
)
from lemely.db.merchant_charge_repo import (
    FAILED_STATUSES,
    IN_FLIGHT_STATUSES,
    MERCHANT_SWEEP_BATCH,
    MerchantChargeError,
    charge_queued_payments,
    insert_queued_payment,
)
from lemely.db.models import User
from lemely.db.models.billing import (
    AutoTopupSettings,
    CreditPack,
    Payment,
    PaymentPurpose,
    PaymentStatus,
    SavedCard,
)
from lemely.db.models.usage import GrantKind
from lemely.db.usage_ledger_repo import UsageLedger

if TYPE_CHECKING:
    import uuid
    from collections.abc import Mapping, Sequence
    from datetime import datetime

    from sqlalchemy.orm import Session, sessionmaker

    from lemely.db.models.usage import UsageJob
    from lemely.io.paymob.client import PaymobClient
    from lemely.runtime.config import PaymobSettings

log = structlog.get_logger(__name__)
#: Events the operator alerts on (``alert=True`` survives only in structlog).
alerts = structlog.get_logger("lemely.db.auto_topup_repo.alerts")

AUTO_TOPUP_DEDUPE_PREFIX: Final = "auto_topup:"

#: ``auto_topup_settings.disabled_reason`` values the built frontend recognises (DV-10).
DISABLED_CHARGE_FAILED: Final = "charge_failed"
DISABLED_PARENT_UNLINKED: Final = "parent_unlinked"

#: Billing currency for a balance with no settings row yet (Lemely charges EGP only, spec §1).
DEFAULT_CURRENCY: Final = "EGP"
#: Largest threshold or monthly cap accepted: far below BIGINT, far above any real value.
MAX_SETTING_VALUE: Final = 10**12


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
    if setting is None or not setting.enabled:
        return None
    if setting.saved_card_id is None:
        # Only after a hard card delete (``ON DELETE SET NULL``). Switch it off so the setting
        # stops claiming auto top-up is on, and tell the payer in this same transaction: the row
        # cannot tell this disable from a failed charge afterwards, so a later sweep could not
        # find it.
        setting.enabled = False
        setting.disabled_reason = DISABLED_CHARGE_FAILED
        enqueue_auto_topup_card_missing(
            session,
            payer_user_id=setting.payer_user_id,
            setting_id=setting.id,
            crossing_seq=setting.crossing_seq,
        )
        session.flush()
        log.error("auto_topup_card_missing", alert=True, beneficiary=str(owner_user_id))
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
    if setting.consented_at is None:
        # Last gate, reached only when a top-up would otherwise queue: it must not alert on
        # every settle at a healthy balance, nor hide the unlink disable. An unattended MOTO
        # charge without consent evidence is undefendable in a dispute. Stay armed: a later
        # consent stamp lets the next settle queue.
        log.error("auto_topup_no_consent", alert=True, beneficiary=str(owner_user_id))
        return None
    payment = insert_queued_payment(
        session,
        purpose=PaymentPurpose.auto_topup,
        payer_user_id=setting.payer_user_id,
        beneficiary_user_id=owner_user_id,
        amount_minor=pack.price_minor,
        currency=pack.currency,
        credit_pack_id=pack.id,
        dedupe_key=f"{AUTO_TOPUP_DEDUPE_PREFIX}{setting.id}:{setting.crossing_seq}",
    )
    if payment is None:
        # Impossible under the row lock with a per-setting key: a bug signal, never silent.
        log.warning(
            "auto_topup_dedupe_conflict", beneficiary=str(owner_user_id), setting=str(setting.id)
        )
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
        try:
            with session.begin_nested():
                enqueue_auto_topup(session, owner, now=now)
        except Exception:
            # One owner's fault must not skip the other owners in the chain.
            log.error(
                "auto_topup_enqueue_failed", alert=True, beneficiary=str(owner), exc_info=True
            )


# ---------------------------------------------------------------------------
# The paid handler: grant the credits, re-arm the setting.
# ---------------------------------------------------------------------------


def on_auto_topup_paid(session: Session, payment: Payment) -> None:
    """Apply a paid ``auto_topup`` payment: the beneficiary's credits, then re-arm the setting.

    Runs once per payment inside Phase 02's callback or reconcile transaction, after the payment
    lock and the event insert (lock order: payment, event, ledger, setting). It makes no Paymob
    call. The grant is made even when the setting was switched off meanwhile: the money is taken,
    so the credits are delivered. ``issue_grant`` repays the beneficiary's debt first and is
    idempotent on ``auto_topup:{payment.id}``.

    The setting is re-armed (and ``crossing_seq`` bumped) only when this payment is its latest
    top-up and the setting is disarmed. A late payment of an older top-up changes nothing, and a
    top-up that leaves the balance below the threshold fires again on the next crossing.

    Raises:
        ValueError: ``paid_at`` or ``credit_pack_id`` is missing (the clock is never guessed, and a
            purpose that does not match its pack is a bug).
    """
    paid_at = payment.paid_at
    if paid_at is None:
        raise ValueError(f"auto top-up payment {payment.id} has no paid_at")
    if payment.credit_pack_id is None:
        raise ValueError(f"auto top-up payment {payment.id} has no credit_pack_id")
    pack = session.get_one(CreditPack, payment.credit_pack_id)
    UsageLedger(session).issue_grant(
        owner_user_id=payment.beneficiary_user_id,
        kind=GrantKind.auto_topup,
        units=pack.units,
        idempotency_key=f"{AUTO_TOPUP_DEDUPE_PREFIX}{payment.id}",
        expires_at=add_months(paid_at, credit_validity_months(session, payment_id=payment.id)),
        visible=True,
        effective_at=paid_at,
        payment_id=payment.id,
    )
    setting = session.execute(
        sa.select(AutoTopupSettings)
        .where(AutoTopupSettings.beneficiary_user_id == payment.beneficiary_user_id)
        .with_for_update()
    ).scalar_one_or_none()
    if setting is not None and setting.last_payment_id == payment.id and not setting.armed:
        setting.armed = True
        setting.crossing_seq += 1
    session.flush()


def handle_auto_topup_paid(session: Session, payment: Payment, obj: Mapping[str, object]) -> None:
    """Phase 02 ``PaidHandler`` for ``auto_topup`` (the verified callback body is not needed)."""
    del obj
    on_auto_topup_paid(session, payment)


register_paid_handler(PaymentPurpose.auto_topup, handle_auto_topup_paid)


# ---------------------------------------------------------------------------
# The charge job: queued charges, then the failure sweep.
# ---------------------------------------------------------------------------


def _auto_topup_card(session: Session, payment: Payment) -> SavedCard | None:
    """The card a queued top-up is charged to, re-checked now; ``None`` fails it unsent (DV-24).

    The queued row pins no card and no consent, so everything is read again at charge time: the
    setting still exists, is enabled, carries the consent stamp, belongs to this payment's payer
    and still has this payment as its latest top-up; a parent payer is still linked to the child
    (DV-9); the card is the payer's own and active.
    """
    setting = session.scalars(
        sa.select(AutoTopupSettings).where(
            AutoTopupSettings.beneficiary_user_id == payment.beneficiary_user_id
        )
    ).first()
    if (
        setting is None
        or not setting.enabled
        or setting.saved_card_id is None
        or setting.consented_at is None
        or setting.payer_user_id != payment.payer_user_id
        or setting.last_payment_id != payment.id
    ):
        return None
    if payment.payer_user_id != payment.beneficiary_user_id and not is_linked_parent(
        session, payment.payer_user_id, payment.beneficiary_user_id
    ):
        return None
    card = session.get(SavedCard, setting.saved_card_id)
    if card is None or not card.is_active or card.user_id != payment.payer_user_id:
        return None
    return card


def _disable_failed_auto_topups(sessionmaker: sessionmaker[Session]) -> int:
    """Switch off each enabled setting whose latest top-up failed, and tell the payer (DV-23).

    At most ``MERCHANT_SWEEP_BATCH`` settings per run, one transaction each, so a bad row cannot
    block or undo the others. A failure of an older top-up (not ``last_payment_id``) is ignored.
    """
    with sessionmaker() as session:
        setting_ids = list(
            session.scalars(
                sa.select(AutoTopupSettings.id)
                .join(Payment, Payment.id == AutoTopupSettings.last_payment_id)
                .where(AutoTopupSettings.enabled.is_(True), Payment.status.in_(FAILED_STATUSES))
                .order_by(AutoTopupSettings.updated_at, AutoTopupSettings.id)
                .limit(MERCHANT_SWEEP_BATCH)
            )
        )
    return sum(_disable_one(sessionmaker, setting_id) for setting_id in setting_ids)


def _disable_one(sessionmaker: sessionmaker[Session], setting_id: uuid.UUID) -> bool:
    with sessionmaker() as session:
        try:
            row = session.execute(
                sa.select(AutoTopupSettings, Payment.id)
                .join(Payment, Payment.id == AutoTopupSettings.last_payment_id)
                .where(
                    AutoTopupSettings.id == setting_id,
                    AutoTopupSettings.enabled.is_(True),
                    Payment.status.in_(FAILED_STATUSES),
                )
                .with_for_update(of=AutoTopupSettings, skip_locked=True)
            ).first()
            if row is None:
                return False
            setting, payment_id = row
            setting.enabled = False
            setting.disabled_reason = DISABLED_CHARGE_FAILED
            setting.armed = True
            setting.crossing_seq += 1
            enqueue_auto_topup_failed(
                session, payer_user_id=setting.payer_user_id, payment_id=payment_id
            )
            session.commit()
        except Exception as exc:
            session.rollback()
            alerts.error(
                "auto_topup_sweep_failed",
                alert=True,
                setting_id=str(setting_id),
                error_type=type(exc).__name__,
            )
            return False
    log.warning("auto_topup_disabled", setting_id=str(setting_id), payment_id=str(payment_id))
    return True


def run_auto_topup_job(
    sessionmaker: sessionmaker[Session],
    client: PaymobClient,
    settings: PaymobSettings,
    *,
    now: datetime,
) -> int:
    """Job ``billing.auto_topup``: charge the queued top-ups, then switch off the failed ones.

    Returns how many queued charges were handled plus how many settings were switched off. Runs
    only where charges are configured (the provider decides, T10); without it the queued rows wait.
    """
    handled = charge_queued_payments(
        sessionmaker,
        client,
        settings,
        purpose=PaymentPurpose.auto_topup,
        dedupe_prefix=AUTO_TOPUP_DEDUPE_PREFIX,
        card_for=_auto_topup_card,
        now=now,
    )
    return handled + _disable_failed_auto_topups(sessionmaker)


# ---------------------------------------------------------------------------
# The settings service (spec §4.6; T9's routes call these).
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AutoTopupView:
    """One balance's auto top-up.

    With no settings row yet ("not set up"): ``enabled`` is False and ``threshold_units``,
    ``credit_pack_id``, ``saved_card_id`` and ``monthly_cap_minor`` are None.
    ``spent_this_month_minor`` counts the UTC calendar month.
    """

    beneficiary_user_id: uuid.UUID
    enabled: bool
    threshold_units: int | None
    credit_pack_id: uuid.UUID | None
    saved_card_id: uuid.UUID | None
    monthly_cap_minor: int | None
    spent_this_month_minor: int
    currency: str
    disabled_reason: str | None


def _view(session: Session, setting: AutoTopupSettings, *, now: datetime) -> AutoTopupView:
    pack = session.get(CreditPack, setting.credit_pack_id)
    return AutoTopupView(
        beneficiary_user_id=setting.beneficiary_user_id,
        enabled=setting.enabled,
        threshold_units=setting.threshold_units,
        credit_pack_id=setting.credit_pack_id,
        saved_card_id=setting.saved_card_id,
        monthly_cap_minor=setting.monthly_cap_minor,
        spent_this_month_minor=spent_this_month(session, setting.beneficiary_user_id, now=now),
        currency=pack.currency if pack is not None else DEFAULT_CURRENCY,
        disabled_reason=setting.disabled_reason,
    )


def get_auto_topup(
    session: Session, *, payer_user_id: uuid.UUID, beneficiary_user_id: uuid.UUID, now: datetime
) -> AutoTopupView:
    """The setting for this balance; a "not set up" view when no row exists yet.

    The caller has already authorized the payer for this beneficiary (self, or a linked parent).

    Raises:
        MerchantChargeError: ``not_found`` when another payer owns the setting (the beneficiary
            sees the balance, not the billing; the route answers 404).
    """
    setting = session.scalars(
        sa.select(AutoTopupSettings).where(
            AutoTopupSettings.beneficiary_user_id == beneficiary_user_id
        )
    ).first()
    if setting is None:
        return AutoTopupView(
            beneficiary_user_id=beneficiary_user_id,
            enabled=False,
            threshold_units=None,
            credit_pack_id=None,
            saved_card_id=None,
            monthly_cap_minor=None,
            spent_this_month_minor=spent_this_month(session, beneficiary_user_id, now=now),
            currency=DEFAULT_CURRENCY,
            disabled_reason=None,
        )
    if setting.payer_user_id != payer_user_id:
        raise MerchantChargeError("not_found", "No auto top-up for this account.")
    return _view(session, setting, now=now)


def put_auto_topup(
    session: Session,
    *,
    payer_user_id: uuid.UUID,
    beneficiary_user_id: uuid.UUID,
    enabled: bool,
    threshold_units: int,
    credit_pack_id: uuid.UUID,
    saved_card_id: uuid.UUID | None,
    monthly_cap_minor: int,
    now: datetime,
) -> AutoTopupView:
    """Create or update the setting; the caller (already authorized) commits.

    The order of the refusals is pinned: the owner is checked before the pack and the card, so a
    payer who does not own the row learns nothing about them whatever ids are sent. Switching on
    stamps ``consented_at = now`` (the chargeback evidence for an unattended MOTO charge), re-arms
    and clears ``disabled_reason``; an edit of a setting that stays on keeps the stamp. Nothing
    else sets it, and without it no top-up is ever queued or charged.

    Raises:
        MerchantChargeError: ``invalid_settings``, ``managed_by_another_payer``,
            ``pack_not_found``, ``card_not_found``, ``no_saved_card``, ``cap_below_pack_price``,
            ``unknown_payer``.
        PhoneRequired: switching on while the payer has no valid phone (every background charge
            would be refused, DV-5).
    """
    if (
        not 0 < threshold_units <= MAX_SETTING_VALUE
        or not 0 <= monthly_cap_minor <= MAX_SETTING_VALUE
    ):
        raise MerchantChargeError(
            "invalid_settings", "The threshold must be positive and the cap not negative."
        )
    setting = session.execute(
        sa.select(AutoTopupSettings)
        .where(AutoTopupSettings.beneficiary_user_id == beneficiary_user_id)
        .with_for_update()
    ).scalar_one_or_none()
    if setting is not None and setting.payer_user_id != payer_user_id:
        raise MerchantChargeError(
            "managed_by_another_payer", "Someone else manages auto top-up for this account."
        )
    pack = session.get(CreditPack, credit_pack_id)
    if pack is None or not pack.is_active or pack.price_minor <= 0:
        raise MerchantChargeError("pack_not_found", "Credit pack not found.")
    if saved_card_id is not None:
        card = session.get(SavedCard, saved_card_id)
        if card is None or card.user_id != payer_user_id or not card.is_active:
            raise MerchantChargeError("card_not_found", "Card not found.")
    if enabled and saved_card_id is None:
        raise MerchantChargeError("no_saved_card", "Choose a saved card for auto top-up.")
    if enabled and monthly_cap_minor < pack.price_minor:
        raise MerchantChargeError(
            "cap_below_pack_price", "The monthly cap is below the pack price."
        )
    if enabled:
        payer = session.get(User, payer_user_id)
        if payer is None:
            raise MerchantChargeError("unknown_payer", "The payer has no account.")
        payer_phone(payer)  # PhoneRequired propagates
    if setting is None:
        setting = AutoTopupSettings(
            beneficiary_user_id=beneficiary_user_id,
            payer_user_id=payer_user_id,
            enabled=False,
            threshold_units=threshold_units,
            credit_pack_id=credit_pack_id,
            monthly_cap_minor=monthly_cap_minor,
            armed=True,
            crossing_seq=0,
        )
        session.add(setting)
    if enabled and not setting.enabled:
        setting.armed = True
        setting.crossing_seq += 1
        setting.disabled_reason = None
        setting.consented_at = now
        if setting.last_payment_id is not None:
            last_status = session.scalar(
                sa.select(Payment.status).where(Payment.id == setting.last_payment_id)
            )
            if last_status in FAILED_STATUSES:
                # The failure that switched it off is handled: without this the sweep would
                # switch the setting off again at once.
                setting.last_payment_id = None
    setting.enabled = enabled
    setting.threshold_units = threshold_units
    setting.credit_pack_id = credit_pack_id
    setting.saved_card_id = saved_card_id
    setting.monthly_cap_minor = monthly_cap_minor
    session.flush()
    return _view(session, setting, now=now)


__all__ = [
    "AUTO_TOPUP_DEDUPE_PREFIX",
    "DEFAULT_CURRENCY",
    "DISABLED_CHARGE_FAILED",
    "DISABLED_PARENT_UNLINKED",
    "MAX_SETTING_VALUE",
    "AutoTopupView",
    "auto_topup_post_settle_hook",
    "enqueue_auto_topup",
    "get_auto_topup",
    "handle_auto_topup_paid",
    "on_auto_topup_paid",
    "put_auto_topup",
    "run_auto_topup_job",
    "spent_this_month",
]
