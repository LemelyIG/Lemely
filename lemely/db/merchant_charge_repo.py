"""Unattended merchant charges: a saved card charged over Paymob MOTO (billing Phase 06).

Auto top-up and the fallback renewal seat charge run with nobody at the screen, so they cannot
do 3DS: they charge a saved card directly (a MOTO intention, then ``payments/pay`` with the
card token). Lemely, not the card issuer, carries the chargeback liability for these charges
(UD-P1). Upgrades and seat purchases happen with the payer present and go through Phase 02's 3DS
checkout instead; they share the building blocks here (:meth:`MerchantChargeService.new_payment`,
:class:`MerchantChargeError`) but never call :meth:`~MerchantChargeService.charge_saved_card`.

**Money safety** (index R20b, R27; constraints section 5). The order inside
:meth:`MerchantChargeService.charge_saved_card` is the whole design:

1. Refuse before any write: unconfigured account or key-mode mismatch, a card that is not the
   payer's active card, a token that will not decrypt, a payer with no phone. Nothing is committed
   and nothing is sent.
2. **Record first.** Claim ``created -> pending`` with a conditional ``UPDATE`` and **commit**
   before any Paymob call. A second worker, or a retry of the same payment, finds the row no longer
   ``created`` and calls nothing (:class:`ChargeAlreadyAttempted`). That claim is also the only
   place a row lock is taken, and the commit releases it: **no Paymob call is made while a row
   lock is held**, and none from a callback handler.
3. Paymob answers are classified once, for the intention and the pay call alike. A received 4xx
   (``not _outcome_unknown``) is definite and fails the payment. Anything that does not say whether
   Paymob applied the call (a timeout, a transport error, a 5xx, a 2xx we cannot read) leaves the
   payment ``pending`` with ``next_reconcile_at = now``: Phase 02's reconcile inquiry settles it
   with all its guards. There is **no in-line inquiry and no retry**.
4. Only a verified callback or a reconcile inquiry marks a payment ``paid``. This module never does.
5. Every ``-> failed`` is a conditional ``UPDATE ... WHERE status = 'pending'``, so a callback that
   already paid the row is never overwritten by a late decline.
6. Once Paymob may have been called, an unexpected error never becomes "nothing was charged":
   :meth:`~MerchantChargeService.charge_saved_card` catches it, leaves the row ``pending`` for
   reconcile, raises an alert and returns the payment.

**Transactions.** ``charge_saved_card`` commits (the claim, then each stored fact). The caller
creates the payment with :meth:`~MerchantChargeService.new_payment` (flush only) or
:func:`insert_queued_payment` and lets ``charge_saved_card`` commit it. A refusal in step 1
propagates; the caller rolls back, and nothing was ever committed.

**Payer-present charges** (Phase 06 T4, DV-25, DV-26). A plan upgrade is a Phase 02 checkout on the
card (Normal 3DS) integration that offers the payer's saved cards through ``card_tokens``; the
issuer keeps the liability and the payer may pay with any card. The quote and the checkout share one
planner (:meth:`MerchantChargeService._plan_upgrade`), a checkout is recorded before Paymob is
called (:meth:`~lemely.db.billing_repo.BillingService.create_intention_checkout`), and only the
verified callback or a reconcile inquiry settles it. An abandoned checkout can still be paid up to
an hour later, so :func:`on_upgrade_paid` re-checks under the subscription lock whether the payment
still buys what it was priced for; when it does not, the money becomes credits (UD-P2) instead of
a tier change. The handler makes no Paymob call (DV-1): Phase 05's drift check pushes the new
amount.

Logs carry payment ids, status codes and flags only: never the card token (plain or encrypted),
the payment key, the intention client secret, billing data or a response body.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import sqlalchemy as sa
import structlog
from sqlalchemy.dialects.postgresql import insert as pg_insert

from lemely.core.usage_pricing import prorate_minor, prorate_units
from lemely.db.billing_repo import (
    INTENTION_EXPIRATION_SECONDS,
    MAX_CARD_TOKENS,
    RECONCILE_AFTER,
    WEBHOOK_PATH,
    BillingError,
    BillingService,
    CheckoutResult,
    CheckoutUnavailable,
    PhoneRequired,
    _as_int,
    _outcome_unknown,
    billing_data_for,
    is_linked_parent,
    register_paid_handler,
    saved_cards_for,
)
from lemely.db.models import User
from lemely.db.models.billing import (
    PLAN_LIVE_STATUSES,
    Payment,
    PaymentPurpose,
    PaymentStatus,
    PlanAudience,
    PlanTier,
    PlanTierTerms,
    SavedCard,
    Subscription,
    SubscriptionPeriod,
)
from lemely.db.models.enums import SubscriptionStatus
from lemely.db.models.team import TeacherMember, TeacherMemberKind, TeacherMemberStatus
from lemely.db.models.usage import GrantKind
from lemely.db.subscription_repo import NoCreditRate, convert_payment_to_credits
from lemely.db.usage_ledger_repo import UsageLedger
from lemely.io.paymob.client import PaymobError
from lemely.runtime.token_cipher import TokenCipherError

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from datetime import datetime
    from typing import NoReturn

    from sqlalchemy.orm import Session, sessionmaker

    from lemely.io.paymob.client import PaymobClient
    from lemely.runtime.config import PaymobSettings

log = structlog.get_logger(__name__)
#: Events the operator alerts on (``alert=True`` survives only in structlog).
alerts = structlog.get_logger("lemely.db.merchant_charge_repo.alerts")

#: Payments Paymob has not finished with: the "in flight" group of every charge check.
IN_FLIGHT_STATUSES: Final = (PaymentStatus.created, PaymentStatus.pending)
#: Payments that definitely did not charge the customer (a later success can still pay one, R20b).
FAILED_STATUSES: Final = (
    PaymentStatus.failed,
    PaymentStatus.failed_mismatch,
    PaymentStatus.voided,
)
#: Queued rows one sweep run charges, oldest first; the rest wait for the next run.
MERCHANT_SWEEP_BATCH: Final = 200
#: Unexpected sweep errors one queued row may raise before it is failed unsent: a row that errors on
#: every run (a deleted payer, a bug in ``card_for``) would otherwise hold its place at the head of
#: the oldest-first batch forever.
MAX_SWEEP_ERRORS: Final = 3
#: ``payments.method`` of a saved-card MOTO charge.
CARD_MOTO_METHOD: Final = "card_moto"

#: The intention item name (Paymob shows it on the receipt; at most 50 characters). Only the two
#: queued purposes are here: upgrades, credit packs and seat purchases are 3DS checkouts (UD-P1) and
#: are never charged to a saved card, so :meth:`charge_saved_card` refuses everything else.
_ITEM_NAMES: Final[dict[PaymentPurpose, str]] = {
    PaymentPurpose.auto_topup: "Credit auto top-up",
    PaymentPurpose.extra_seats: "Extra student seats",
}


# ---------------------------------------------------------------------------
# Errors.
# ---------------------------------------------------------------------------


class MerchantChargeError(Exception):
    """A merchant charge was refused before any write; ``code`` is the machine-readable reason.

    ``detail`` carries extra machine-readable facts for the HTTP body (never secrets).
    """

    def __init__(
        self, code: str, message: str | None = None, *, detail: Mapping[str, object] | None = None
    ) -> None:
        super().__init__(message or code)
        self.code = code
        self.detail: dict[str, object] = dict(detail or {})


class SeatsExceedNewTier(MerchantChargeError):
    """More active seats are held than the target plan (plus the usable extra seats) can seat."""

    def __init__(self, *, in_use: int, capacity: int) -> None:
        super().__init__(
            "seats_exceed_new_tier",
            "More students hold a seat than the new plan seats",
            detail={"in_use": in_use, "capacity": capacity},
        )
        self.in_use = in_use
        self.capacity = capacity


class ChargeAlreadyAttempted(Exception):
    """The payment is no longer ``created``: another worker claimed it. Nothing was called."""


class ChargesUnavailable(MerchantChargeError):
    """Merchant charges are not configured or the keys are in different modes; nothing was sent."""

    def __init__(self) -> None:
        super().__init__("payments_unavailable", "Merchant charges are not available")


def charges_configured(settings: PaymobSettings) -> bool:
    """True when a saved card can be charged: checkout works, MOTO is set, tokens can be opened.

    ``checkout_configured`` already refuses a public/secret key-mode mismatch, so a charge is
    refused (not sent to 404) while the keys disagree.
    """
    return (
        settings.checkout_configured
        and settings.moto_integration_id is not None
        and settings.card_token_key is not None
    )


# ---------------------------------------------------------------------------
# Queue helpers (shared by auto top-up and the fallback renewal seat charge).
# ---------------------------------------------------------------------------


def insert_queued_payment(
    session: Session,
    *,
    purpose: PaymentPurpose,
    payer_user_id: uuid.UUID,
    beneficiary_user_id: uuid.UUID,
    amount_minor: int,
    currency: str,
    dedupe_key: str,
    subscription_id: uuid.UUID | None = None,
    credit_pack_id: uuid.UUID | None = None,
    seat_quantity: int | None = None,
) -> Payment | None:
    """Queue a ``created`` payment under ``dedupe_key``; ``None`` when the key already exists.

    ``INSERT ... ON CONFLICT (dedupe_key) DO NOTHING``: two replicas that decide to queue the
    same charge insert it once. The key's prefix must match ``purpose`` (migration 0056's CHECK
    raises otherwise). Runs in the caller's transaction; the row has no reconcile schedule until a
    charge claims it, so reconcile never inquires about a payment nothing was ever sent for.
    """
    payment_id = uuid.uuid4()
    inserted = session.execute(
        pg_insert(Payment)
        .values(
            id=payment_id,
            special_reference=str(payment_id),
            payer_user_id=payer_user_id,
            beneficiary_user_id=beneficiary_user_id,
            purpose=purpose,
            subscription_id=subscription_id,
            credit_pack_id=credit_pack_id,
            seat_quantity=seat_quantity,
            amount_minor=amount_minor,
            currency=currency,
            status=PaymentStatus.created,
            dedupe_key=dedupe_key,
        )
        .on_conflict_do_nothing(index_elements=[Payment.dedupe_key])
        .returning(Payment.id)
    ).first()
    if inserted is None:
        return None
    return session.get(Payment, payment_id)


def fail_unsent(session: Session, payment_id: uuid.UUID, *, reason: str) -> bool:
    """Fail a payment nothing was sent for: conditional ``created -> failed``.

    Returns whether this call did it (``False``: the row is no longer ``created``). Flushes into
    the caller's transaction; the caller commits.
    """
    failed = session.execute(
        sa.update(Payment)
        .where(Payment.id == payment_id, Payment.status == PaymentStatus.created)
        .values(
            status=PaymentStatus.failed,
            last_callback={"source": "pre_send", "reason": reason},
            next_reconcile_at=None,
        )
        .returning(Payment.id)
    ).first()
    return failed is not None


def charge_queued_payments(
    sessionmaker: sessionmaker[Session],
    client: PaymobClient,
    settings: PaymobSettings,
    *,
    purpose: PaymentPurpose,
    dedupe_prefix: str,
    card_for: Callable[[Session, Payment], SavedCard | None],
    now: datetime,
    limit: int = MERCHANT_SWEEP_BATCH,
) -> int:
    """Charge up to ``limit`` queued ``created`` payments, oldest first; returns how many handled.

    One transaction per payment, so a row that fails cannot block or undo the others. Safe to run
    on several replicas at once: each payment is claimed by a conditional update, and a replica that
    loses the claim skips it. A payment whose card is unusable (missing, inactive, another user's,
    or its token will not decrypt) or whose payer has no phone is failed unsent, without a Paymob
    call. Any other error rolls back that payment, raises ``merchant_charge_sweep_failed`` and
    carries on; the row stays ``created`` and is tried again next run. When charges are not
    configured (including a key-mode mismatch) nothing is touched and the rows wait.
    """
    if not charges_configured(settings):
        log.warning("merchant_charges_not_configured", purpose=purpose.value)
        return 0
    with sessionmaker() as session:
        payment_ids = list(
            session.scalars(
                sa.select(Payment.id)
                .where(
                    Payment.status == PaymentStatus.created,
                    Payment.purpose == purpose,
                    Payment.dedupe_key.startswith(dedupe_prefix, autoescape=True),
                )
                .order_by(Payment.created_at, Payment.id)
                .limit(limit)
            )
        )
    handled = 0
    for payment_id in payment_ids:
        if _charge_queued_one(
            sessionmaker, client, settings, payment_id, card_for=card_for, now=now
        ):
            handled += 1
    return handled


def _charge_queued_one(
    sessionmaker: sessionmaker[Session],
    client: PaymobClient,
    settings: PaymobSettings,
    payment_id: uuid.UUID,
    *,
    card_for: Callable[[Session, Payment], SavedCard | None],
    now: datetime,
) -> bool:
    """Charge one queued payment in its own session; whether it was handled (not skipped)."""
    with sessionmaker() as session:
        try:
            payment = session.get(Payment, payment_id)
            if payment is None or payment.status is not PaymentStatus.created:
                return False
            card = card_for(session, payment)
            if card is None:
                return _fail_queued(session, payment_id, "card_unusable")
            service = MerchantChargeService(session, client, settings)
            try:
                service.charge_saved_card(payment, card, now=now)
            except ChargeAlreadyAttempted:
                return False
            except PhoneRequired:
                return _fail_queued(session, payment_id, "phone_required")
            except MerchantChargeError as exc:
                if exc.code != "no_saved_card":
                    raise
                return _fail_queued(session, payment_id, "card_unusable")
        except Exception as exc:
            session.rollback()
            alerts.error(
                "merchant_charge_sweep_failed",
                alert=True,
                payment_id=str(payment_id),
                error_type=type(exc).__name__,
            )
            return _note_sweep_error(session, payment_id, type(exc).__name__)
        return True


def _note_sweep_error(session: Session, payment_id: uuid.UUID, error_type: str) -> bool:
    """Count an unexpected sweep error on the row; fail it unsent once it keeps happening.

    Returns whether the row was failed (handled). Nothing was sent for it (a post-claim error never
    reaches here, and the writes below are conditional on ``created``), so ``fail_unsent`` is the
    truth. The count lives in ``last_callback`` so no column is needed.
    """
    try:
        row = session.execute(
            sa.select(Payment.status, Payment.last_callback).where(Payment.id == payment_id)
        ).one_or_none()
        if row is None or row.status is not PaymentStatus.created:
            session.rollback()
            return False
        note = row.last_callback or {}
        previous = note.get("attempts") if note.get("source") == "sweep_error" else 0
        attempts = (previous if isinstance(previous, int) else 0) + 1
        if attempts >= MAX_SWEEP_ERRORS:
            gave_up = fail_unsent(session, payment_id, reason="sweep_error")
            session.commit()
            if gave_up:
                alerts.error(
                    "merchant_charge_sweep_gave_up",
                    alert=True,
                    payment_id=str(payment_id),
                    error_type=error_type,
                    attempts=attempts,
                )
            return gave_up
        session.execute(
            sa.update(Payment)
            .where(Payment.id == payment_id, Payment.status == PaymentStatus.created)
            .values(
                last_callback={
                    "source": "sweep_error",
                    "attempts": attempts,
                    "error_type": error_type,
                }
            )
        )
        session.commit()
    except Exception as exc:
        session.rollback()
        alerts.error(
            "merchant_charge_sweep_error_note_failed",
            alert=True,
            payment_id=str(payment_id),
            error_type=type(exc).__name__,
        )
    return False


def _fail_queued(session: Session, payment_id: uuid.UUID, reason: str) -> bool:
    session.rollback()
    if fail_unsent(session, payment_id, reason=reason):
        session.commit()
        log.warning("merchant_charge_failed_unsent", payment_id=str(payment_id), reason=reason)
        return True
    session.rollback()
    return False


# ---------------------------------------------------------------------------
# The service.
# ---------------------------------------------------------------------------


class MerchantChargeService:
    """Saved-card MOTO charges over one SQLAlchemy session (billing Phase 06)."""

    def __init__(self, session: Session, client: PaymobClient, settings: PaymobSettings) -> None:
        self._session = session
        self._client = client
        self._settings = settings
        self._billing = BillingService(session, client, settings)

    def active_card(self, payer_user_id: uuid.UUID) -> SavedCard | None:
        """The card the billing summary shows first: the one a "charged to {card}" line names."""
        return next(iter(saved_cards_for(self._session, payer_user_id)), None)

    def new_payment(
        self,
        *,
        purpose: PaymentPurpose,
        payer_user_id: uuid.UUID,
        beneficiary_user_id: uuid.UUID,
        amount_minor: int,
        currency: str,
        subscription_id: uuid.UUID | None = None,
        plan_tier_id: uuid.UUID | None = None,
        credit_pack_id: uuid.UUID | None = None,
        seat_quantity: int | None = None,
        dedupe_key: str | None = None,
    ) -> Payment:
        """Add a ``created`` payment (``special_reference`` is its id) and flush; never commits."""
        payment_id = uuid.uuid4()
        payment = Payment(
            id=payment_id,
            special_reference=str(payment_id),
            payer_user_id=payer_user_id,
            beneficiary_user_id=beneficiary_user_id,
            purpose=purpose,
            subscription_id=subscription_id,
            plan_tier_id=plan_tier_id,
            credit_pack_id=credit_pack_id,
            seat_quantity=seat_quantity,
            amount_minor=amount_minor,
            currency=currency,
            status=PaymentStatus.created,
            dedupe_key=dedupe_key,
        )
        self._session.add(payment)
        self._session.flush()
        return payment

    # -- payer-present upgrade (3DS checkout, saved cards offered) ---------------

    def quote_upgrade(
        self,
        *,
        subscription_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        plan_tier_id: uuid.UUID,
        now: datetime,
    ) -> ChargeQuote:
        """What an upgrade to ``plan_tier_id`` would charge now; writes nothing, calls nobody.

        Needs no phone, card or pending check: it is the same planner as the checkout, so the
        amount, allowance and period end match what :meth:`start_upgrade_checkout` would bill.
        """
        plan = self._plan_upgrade(
            subscription_id=subscription_id,
            actor_user_id=actor_user_id,
            plan_tier_id=plan_tier_id,
            now=now,
            lock=False,
        )
        return ChargeQuote(
            amount_minor=plan.amount_minor,
            currency=plan.currency,
            allowance_units=plan.allowance_units,
            period_end=plan.period_end,
        )

    def start_upgrade_checkout(
        self,
        *,
        subscription_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        plan_tier_id: uuid.UUID,
        now: datetime,
    ) -> CheckoutResult:
        """Record an ``upgrade_proration`` payment and open its 3DS checkout.

        Refuses before any write (:class:`MerchantChargeError`, or
        :class:`~lemely.db.billing_repo.PhoneRequired`); the caller rolls back. Past the refusals
        the payment is committed ``created`` by Phase 02's checkout before Paymob is called, which
        also releases the subscription lock.
        :class:`~lemely.db.billing_repo.CheckoutUnavailable` (unconfigured, refused, or an unknown
        outcome) propagates: the payer never got a client secret, so nothing was charged. The tier
        changes only when the verified callback arrives (:func:`on_upgrade_paid`).
        """
        plan = self._plan_upgrade(
            subscription_id=subscription_id,
            actor_user_id=actor_user_id,
            plan_tier_id=plan_tier_id,
            now=now,
            lock=True,
        )
        refuse_if_charge_pending(self._session, plan.subscription.id)
        payer = self._session.get(User, actor_user_id)
        if payer is None:
            raise MerchantChargeError("unknown_payer", "The payer has no account")
        billing_data_for(payer)  # PhoneRequired before any write
        payment = self.new_payment(
            purpose=PaymentPurpose.upgrade_proration,
            payer_user_id=actor_user_id,
            beneficiary_user_id=plan.subscription.user_id,
            amount_minor=plan.amount_minor,
            currency=plan.currency,
            subscription_id=plan.subscription.id,
            plan_tier_id=plan.new_tier.id,
        )
        # The injected clock is the checkout's birth: the void-at-settle rules compare against it.
        payment.created_at = now
        self._session.flush()
        return start_present_checkout(
            self._session,
            self._client,
            self._settings,
            payment=payment,
            item_name=UPGRADE_ITEM_NAME,
            now=now,
        )

    def _plan_upgrade(
        self,
        *,
        subscription_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        plan_tier_id: uuid.UUID,
        now: datetime,
        lock: bool,
    ) -> _UpgradePlan:
        """Validate an upgrade and price it; the one planner the quote and the checkout share."""
        session = self._session
        if not self._settings.subscription_amount_updatable:
            raise MerchantChargeError(
                "upgrade_unavailable",
                "Plan upgrades are not available right now",
                detail={"next": "cancel_and_resubscribe"},
            )
        sub = payable_subscription(session, subscription_id, actor_user_id, lock=lock)
        if sub.paymob_subscription_id is None:
            raise MerchantChargeError("upgrade_unavailable", "This plan cannot be upgraded")
        if sub.cancel_at_period_end or sub.pending_plan_tier_id is not None:
            raise MerchantChargeError("plan_change_pending", "A plan change is already scheduled")
        new_tier = session.get(PlanTier, plan_tier_id)
        if new_tier is None or not new_tier.is_active:
            raise MerchantChargeError("tier_not_found", "That plan is not available")
        old_tier = session.get(PlanTier, sub.plan_tier_id)
        assert old_tier is not None  # noqa: S101 - the foreign key
        old_terms = billed_terms(session, sub)
        new_terms = current_terms(session, new_tier)
        if not is_upgrade(old_tier, old_terms, new_tier, new_terms):
            raise MerchantChargeError("not_an_upgrade", "That plan is not an upgrade")
        if new_tier.audience is PlanAudience.teacher:
            in_use = active_seat_count(session, sub.user_id)
            capacity = new_terms.included_seats + usable_extra_seats(sub)
            if in_use > capacity:
                raise SeatsExceedNewTier(in_use=in_use, capacity=capacity)
        start, end = sub.current_period_start, sub.current_period_end
        if start is None or end is None:
            raise MerchantChargeError("subscription_not_active", "The plan has no current period")
        amount = prorate_minor(new_terms.price_minor - old_terms.price_minor, start, end, now)
        if amount <= 0:
            raise MerchantChargeError("period_ending", "The current period is about to end")
        allowance = _allowance_gain(old_terms, new_terms, start, end, now)
        return _UpgradePlan(
            subscription=sub,
            new_tier=new_tier,
            amount_minor=amount,
            currency=new_tier.currency,
            allowance_units=allowance,
            period_end=end,
        )

    # -- the charge -------------------------------------------------------------

    def charge_saved_card(self, payment: Payment, card: SavedCard, *, now: datetime) -> Payment:
        """Charge ``payment`` to ``card`` over MOTO and return the refreshed payment.

        Raises before any write, and leaves nothing committed, when the charge is refused:
        :class:`ChargesUnavailable`, :class:`MerchantChargeError` (``no_saved_card``,
        ``unknown_payer``), :class:`~lemely.db.billing_repo.PhoneRequired`, ``ValueError`` (a
        purpose a card is never charged for). The caller rolls its session back on any of them.
        :class:`ChargeAlreadyAttempted` (after a rollback) means another worker owns the payment.

        Once the claim is committed nothing propagates: every Paymob outcome and every unexpected
        error is recorded on the row (see the module docstring), and the payment comes back
        ``pending`` (accepted or unknown) or ``failed`` (a definite rejection). The result is
        never read as "nothing was charged" unless the row says ``failed``.
        """
        if not charges_configured(self._settings):
            raise ChargesUnavailable
        if payment.status is not PaymentStatus.created:
            raise ChargeAlreadyAttempted
        if not _is_queued_charge(payment):
            raise MerchantChargeError(
                "not_a_queued_charge", "Only a queued charge is charged to a saved card"
            )
        if not card.is_active or card.user_id != payment.payer_user_id:
            raise MerchantChargeError("no_saved_card", "The card is not the payer's active card")
        token = self._decrypt(card)
        payer = self._session.get(User, payment.payer_user_id)
        if payer is None:
            raise MerchantChargeError("unknown_payer", "The payer has no account")
        item_name = _ITEM_NAMES.get(payment.purpose)
        if item_name is None:
            raise ValueError(f"a saved card is never charged for {payment.purpose.value}")
        payment_id = payment.id
        card_id = card.id
        amount = payment.amount_minor
        items: list[dict[str, object]] = [{"name": item_name[:50], "amount": amount, "quantity": 1}]
        if sum(_as_int(item["amount"]) or 0 for item in items) != amount:
            # Paymob rejects a mismatch; refuse before the claim rather than fail a claimed row.
            raise ValueError("charge items do not add up to the payment amount")
        assert self._settings.moto_integration_id is not None  # charges_configured  # noqa: S101
        body: dict[str, object] = {
            "amount": amount,
            "currency": payment.currency,
            "payment_methods": [self._settings.moto_integration_id],
            "items": items,
            "billing_data": billing_data_for(payer),  # PhoneRequired propagates
            "special_reference": payment.special_reference,
            "expiration": INTENTION_EXPIRATION_SECONDS,
            "notification_url": f"{self._settings.notification_base_url}{WEBHOOK_PATH}",
            "extras": {"payment_id": str(payment_id), "purpose": payment.purpose.value},
        }

        # Record first: claim created -> pending and commit before Paymob is called. The claim's
        # WHERE re-checks, atomically with the claim, everything checked above on a copy that may
        # be stale: the payment is still ``created`` and still a queued charge (no checkout
        # attached to it since it was loaded), and the card is still the payer's active card.
        claimed = self._session.execute(
            sa.update(Payment)
            .where(
                Payment.id == payment_id,
                Payment.status == PaymentStatus.created,
                Payment.dedupe_key.is_not(None),
                Payment.paymob_order_id.is_(None),
                Payment.paymob_intention_id.is_(None),
                sa.exists().where(
                    SavedCard.id == card_id,
                    SavedCard.user_id == Payment.payer_user_id,
                    SavedCard.is_active.is_(True),
                ),
            )
            .values(
                status=PaymentStatus.pending,
                method=CARD_MOTO_METHOD,
                sent_at=now,
                next_reconcile_at=now + RECONCILE_AFTER,
            )
            .returning(Payment.id)
            .execution_options(synchronize_session=False)
        ).first()
        if claimed is None:
            self._refuse_claim(payment_id)
        self._session.commit()

        try:
            self._send(payment_id, body, token, now=now)
        except Exception as exc:
            self._after_unexpected_error(payment_id, exc, now=now)
        return self._reload(payment)

    def _refuse_claim(self, payment_id: uuid.UUID) -> NoReturn:
        """The claim matched nothing: say why, roll back and raise. Nothing was sent.

        Read inside the same transaction (it still holds the caller's flushed payment, if any):
        a payment that is no longer ``created``, or that a checkout has since claimed, belongs to
        someone else (:class:`ChargeAlreadyAttempted`); otherwise it was the card that went away
        between the caller loading it and now (``no_saved_card``).
        """
        row = self._session.execute(
            sa.select(
                Payment.status,
                Payment.dedupe_key,
                Payment.paymob_order_id,
                Payment.paymob_intention_id,
            ).where(Payment.id == payment_id)
        ).one_or_none()
        self._session.rollback()
        if (
            row is None
            or row.status is not PaymentStatus.created
            or row.dedupe_key is None
            or row.paymob_order_id is not None
            or row.paymob_intention_id is not None
        ):
            raise ChargeAlreadyAttempted
        raise MerchantChargeError("no_saved_card", "The card is no longer the payer's active card")

    def _decrypt(self, card: SavedCard) -> str:
        try:
            cipher = self._billing.cipher
        except TokenCipherError as exc:  # a malformed card_token_key: a config fault, not the card
            raise ChargesUnavailable from exc
        if cipher is None:
            raise ChargesUnavailable
        try:
            return self._billing.card_token(card)
        except (TokenCipherError, BillingError) as exc:
            raise MerchantChargeError("no_saved_card", "The saved card cannot be used") from exc

    # -- Paymob calls (after the claim; nothing here holds a row lock) ----------------

    def _send(
        self, payment_id: uuid.UUID, body: dict[str, object], token: str, *, now: datetime
    ) -> None:
        try:
            response = self._client.create_intention(body)
        except PaymobError as exc:
            self._record_error("create_intention", payment_id, exc, now=now)
            return
        # Paymob created an order even when the answer is unusable: keep its ids on the row, and
        # commit them before paying (the callback matches on the signed ``order.id``).
        intention_id = response.get("id")
        self._session.execute(
            sa.update(Payment)
            .where(Payment.id == payment_id, Payment.status == PaymentStatus.pending)
            .values(
                paymob_intention_id=str(intention_id) if intention_id else None,
                paymob_order_id=_as_int(response.get("intention_order_id")),
            )
        )
        self._session.commit()
        payment_key = _payment_key(response)
        if payment_key is None:
            self._finish("failed", payment_id, source="create_intention", now=now)
            log.warning("moto_intention_without_payment_key", payment_id=str(payment_id))
            return
        try:
            answer = self._client.pay_with_token(card_token=token, payment_token=payment_key)
        except PaymobError as exc:
            self._record_error("pay_with_token", payment_id, exc, now=now)
            return
        success, pending = answer.get("success"), answer.get("pending")
        if success is False and pending is False:
            self._finish("failed", payment_id, source="pay_with_token", now=now)
            log.info("moto_charge_declined", payment_id=str(payment_id))
        elif success is True or pending is True:
            # Accepted: only the callback or the reconcile inquiry marks it paid.
            log.info("moto_charge_accepted", payment_id=str(payment_id), pending=pending is True)
        else:
            self._finish("unknown", payment_id, source="pay_with_token", now=now)
            log.warning("moto_pay_answer_unreadable", payment_id=str(payment_id))

    def _record_error(
        self, source: str, payment_id: uuid.UUID, exc: PaymobError, *, now: datetime
    ) -> None:
        """A Paymob call raised: a received 4xx fails the row, anything else stays for reconcile."""
        unknown = _outcome_unknown(exc)
        self._finish(
            "unknown" if unknown else "failed",
            payment_id,
            source=source,
            now=now,
            status_code=exc.status_code,
        )
        log.warning(
            "moto_outcome_unknown" if unknown else "moto_call_refused",
            payment_id=str(payment_id),
            source=source,
            status_code=exc.status_code,
            timeout=exc.timeout,
        )

    def _finish(
        self,
        outcome: str,
        payment_id: uuid.UUID,
        *,
        source: str,
        now: datetime,
        status_code: int | None = None,
    ) -> None:
        """Conditionally close the claim: ``failed`` (definite) or due for reconcile (unknown).

        Both are ``WHERE status = 'pending'``, so a callback that already paid or failed the row
        is never overwritten by what this call learned late.
        """
        note: dict[str, object] = {
            "source": source,
            "outcome_unknown": outcome == "unknown",
            "status_code": status_code,
        }
        values: dict[str, object]
        if outcome == "failed":
            values = {
                "status": PaymentStatus.failed,
                "next_reconcile_at": None,
                "last_callback": note,
            }
        else:
            values = {"next_reconcile_at": now, "last_callback": note}
        self._session.execute(
            sa.update(Payment)
            .where(Payment.id == payment_id, Payment.status == PaymentStatus.pending)
            .values(**values)
        )
        self._session.commit()

    def _after_unexpected_error(
        self, payment_id: uuid.UUID, exc: Exception, *, now: datetime
    ) -> None:
        """An error after the claim: Paymob may have been called, so leave the row for reconcile."""
        self._session.rollback()
        rescheduled = False
        try:
            self._session.execute(
                sa.update(Payment)
                .where(Payment.id == payment_id, Payment.status == PaymentStatus.pending)
                .values(next_reconcile_at=now)
            )
            self._session.commit()
            rescheduled = True
        except Exception:
            self._session.rollback()
        alerts.error(
            "merchant_charge_post_claim_error",
            alert=True,
            payment_id=str(payment_id),
            error_type=type(exc).__name__,
            rescheduled=rescheduled,
        )

    def _reload(self, payment: Payment) -> Payment:
        """The payment as the database now has it; the stale object when even that fails."""
        try:
            self._session.refresh(payment)
        except Exception:
            self._session.rollback()
        return payment


def _is_queued_charge(payment: Payment) -> bool:
    """True for a payment this service may charge: queued (a ``dedupe_key``), no checkout attached.

    UD-P1 as an invariant. The 0056 CHECK ties a ``dedupe_key`` to the purposes charged on a saved
    card (auto top-up, the renewal seat charge), so a payment with one cannot be a 3DS purchase; a
    payment with a Paymob order or intention id already has a checkout the payer can complete.
    """
    return (
        payment.dedupe_key is not None
        and payment.paymob_order_id is None
        and payment.paymob_intention_id is None
    )


def _payment_key(response: Mapping[str, object]) -> str | None:
    """``payment_keys[0].key`` of an intention answer, or ``None`` when there is no usable one."""
    keys = response.get("payment_keys")
    if not isinstance(keys, list) or not keys:
        return None
    first = keys[0]
    key = first.get("key") if isinstance(first, dict) else None
    return key if isinstance(key, str) and key else None


# ---------------------------------------------------------------------------
# Payer-present charges: shared helpers (T5 reuses them).
# ---------------------------------------------------------------------------

#: The intention item name of an upgrade (Paymob shows it on the receipt).
UPGRADE_ITEM_NAME: Final = "Plan upgrade (prorated)"


@dataclass(frozen=True, slots=True)
class ChargeQuote:
    """What a payer-present charge would cost now, as the quote route shows it."""

    amount_minor: int
    currency: str
    allowance_units: int
    period_end: datetime


@dataclass(frozen=True, slots=True)
class _UpgradePlan:
    subscription: Subscription
    new_tier: PlanTier
    amount_minor: int
    currency: str
    allowance_units: int
    period_end: datetime


def usable_extra_seats(sub: Subscription) -> int:
    """Extra seats the subscription can still seat: a scheduled reduction lowers them at once."""
    extra = sub.extra_seats or 0
    pending = sub.pending_extra_seats
    return extra if pending is None else min(extra, pending)


def active_seat_count(session: Session, teacher_user_id: uuid.UUID) -> int:
    """Seats held by an active, non-leaving student (a ``leaving`` seat frees up, UD-5, DV-8)."""
    return int(
        session.scalar(
            sa.select(sa.func.count())
            .select_from(TeacherMember)
            .where(
                TeacherMember.teacher_user_id == teacher_user_id,
                TeacherMember.kind == TeacherMemberKind.student_seat,
                TeacherMember.status == TeacherMemberStatus.active,
            )
        )
        or 0
    )


def lock_subscription(session: Session, subscription_id: uuid.UUID) -> Subscription | None:
    """The subscription row under ``FOR UPDATE``, reloaded so the lock sees current values."""
    return session.get(Subscription, subscription_id, with_for_update=True, populate_existing=True)


def current_period(session: Session, sub: Subscription) -> SubscriptionPeriod | None:
    """The period row that ends where the subscription's current period ends, if there is one."""
    if sub.current_period_end is None:
        return None
    return session.scalars(
        sa.select(SubscriptionPeriod)
        .where(
            SubscriptionPeriod.subscription_id == sub.id,
            SubscriptionPeriod.period_end == sub.current_period_end,
        )
        .order_by(SubscriptionPeriod.period_start.desc())
        .limit(1)
    ).first()


def payable_subscription(
    session: Session, subscription_id: uuid.UUID, actor_user_id: uuid.UUID, *, lock: bool
) -> Subscription:
    """The subscription ``actor_user_id`` may pay for, or a refusal that leaks nothing.

    ``not_found`` (one code, one message) unless the actor is the payer, and, when the payer is
    not the subscriber, still linked to them (DV-9): a stranger, a beneficiary and an unlinked
    parent cannot be told apart from an unknown id. Then ``subscription_not_active`` unless the
    plan is ``active``. Locks the row when ``lock``.
    """
    sub = (
        lock_subscription(session, subscription_id)
        if lock
        else session.get(Subscription, subscription_id)
    )
    payer = None if sub is None else sub.payer_user_id
    if (
        sub is None
        or payer is None
        or payer != actor_user_id
        or (payer != sub.user_id and not is_linked_parent(session, payer, sub.user_id))
    ):
        raise MerchantChargeError("not_found", "Subscription not found")
    if sub.status is not SubscriptionStatus.active:
        raise MerchantChargeError("subscription_not_active", "The plan is not active")
    return sub


def refuse_if_charge_pending(session: Session, subscription_id: uuid.UUID) -> None:
    """Refuse (``charge_in_flight``) while an upgrade or seat purchase is under way (DV-26).

    Only a ``pending`` checkout payment counts (a transaction is being confirmed, e.g. 3DS).
    An abandoned ``created`` one never blocks: it may still be paid, and the settle-time rules
    keep that safe.
    """
    in_flight = session.scalar(
        sa.select(Payment.id)
        .where(
            Payment.subscription_id == subscription_id,
            Payment.purpose.in_((PaymentPurpose.upgrade_proration, PaymentPurpose.extra_seats)),
            Payment.dedupe_key.is_(None),
            Payment.status == PaymentStatus.pending,
        )
        .limit(1)
    )
    if in_flight is not None:
        raise MerchantChargeError("charge_in_flight", "A payment for this plan is being confirmed")


def bump_version(sub: Subscription) -> None:
    """Advance ``subscriptions.version`` (a plain counter: the mapper does not do it)."""
    sub.version = (sub.version or 0) + 1


def billed_terms(session: Session, sub: Subscription) -> PlanTierTerms:
    """The terms version the subscriber is billed on (UD13-A): what they pay, not the tier's."""
    terms = session.scalars(
        sa.select(PlanTierTerms).where(
            PlanTierTerms.plan_tier_id == sub.plan_tier_id,
            PlanTierTerms.terms_version == sub.terms_version,
        )
    ).one_or_none()
    if terms is None:
        raise RuntimeError(f"subscription {sub.id} has no terms row for its version")
    return terms


def current_terms(session: Session, tier: PlanTier) -> PlanTierTerms:
    """The tier's current terms version: what a new purchase of the tier is priced at."""
    terms = session.scalars(
        sa.select(PlanTierTerms).where(
            PlanTierTerms.plan_tier_id == tier.id,
            PlanTierTerms.terms_version == tier.terms_version,
        )
    ).one_or_none()
    if terms is None:
        raise RuntimeError(f"plan tier {tier.id} has no terms row for its version")
    return terms


def is_upgrade(
    old_tier: PlanTier, old_terms: PlanTierTerms, new_tier: PlanTier, new_terms: PlanTierTerms
) -> bool:
    """Same audience, interval and currency, and a higher price than the one being paid."""
    return (
        new_tier.id != old_tier.id
        and new_tier.audience is old_tier.audience
        and new_tier.interval is old_tier.interval
        and new_tier.currency == old_tier.currency
        and new_terms.price_minor > old_terms.price_minor
    )


def _allowance_gain(
    old_terms: PlanTierTerms,
    new_terms: PlanTierTerms,
    start: datetime,
    end: datetime,
    at: datetime,
) -> int:
    """Allowance units the upgrade adds for the rest of the period (never negative)."""
    difference = new_terms.allowance_units - old_terms.allowance_units
    if difference <= 0:
        return 0
    return max(0, prorate_units(difference, start, end, at))


def offered_card_tokens(
    service: BillingService, session: Session, payer_id: uuid.UUID
) -> list[str]:
    """The payer's newest saved cards (at most three), decrypted, for Unified Checkout to offer.

    A card whose token will not open (a ciphertext moved to another user's row, a rotated key) is
    skipped and logged by card id: an offer is a convenience, never a reason to refuse a payment.
    Tokens are secrets: callers hand them to the intention and nothing else.
    """
    try:
        if service.cipher is None:
            return []
    except TokenCipherError:
        log.warning("card_token_key_unusable_for_offer")
        return []
    tokens: list[str] = []
    for card in saved_cards_for(session, payer_id)[:MAX_CARD_TOKENS]:
        try:
            tokens.append(service.card_token(card))
        except (TokenCipherError, BillingError):
            log.warning("saved_card_not_offered", card_id=str(card.id))
    return tokens


def start_present_checkout(
    session: Session,
    client: PaymobClient,
    settings: PaymobSettings,
    *,
    payment: Payment,
    item_name: str,
    now: datetime,
) -> CheckoutResult:
    """Open the 3DS checkout of a payer-present ``payment`` that the caller added and flushed.

    One item that equals the payment amount, the payer's offered saved cards, and Phase 02's
    ``create_intention_checkout`` for everything else (commit before the Paymob call, definite
    4xx to ``failed``, unknown to ``created`` for reconcile). When checkout is not configured the
    flushed payment is rolled back first, so nothing is left behind.
    """
    payer = session.get(User, payment.payer_user_id)
    if payer is None:
        raise MerchantChargeError("unknown_payer", "The payer has no account")
    billing = BillingService(session, client, settings, now=lambda: now)
    billing_data = billing_data_for(payer)
    if not settings.checkout_configured:
        session.rollback()
        raise CheckoutUnavailable("Paymob checkout is not configured")
    items: list[dict[str, object]] = [
        {"name": item_name[:50], "amount": payment.amount_minor, "quantity": 1}
    ]
    return billing.create_intention_checkout(
        payment=payment,
        items=items,
        billing_data=billing_data,
        subscription_plan_id=None,
        card_tokens=offered_card_tokens(billing, session, payer.id),
    )


# ---------------------------------------------------------------------------
# The upgrade's paid handler.
# ---------------------------------------------------------------------------


def upgrade_void_reason(session: Session, sub: Subscription, payment: Payment) -> str | None:
    """Why a paid upgrade no longer buys what it was priced for, or ``None`` when it does (DV-26).

    Checked under the subscription lock, in this order: the plan ended; the period rolled since
    the checkout was priced; the target is no longer an upgrade over the tier now billed (another
    payment already switched it); the price recomputed from the terms billed now, at the instant
    the checkout was priced, differs from the amount charged (an upgrade landed after the quote,
    or the target's price changed).

    A downgrade, cancel or seat-capacity change scheduled after the checkout is not re-checked
    here: the payer bought the upgrade for the rest of the period, and the scheduled change takes
    effect at the renewal as it would have anyway, so no money is lost either way.
    """
    if (
        sub.status not in PLAN_LIVE_STATUSES
        or sub.current_period_start is None
        or sub.current_period_end is None
    ):
        return "plan_ended"
    if sub.current_period_start > payment.created_at:
        return "period_rolled"
    target = None if payment.plan_tier_id is None else session.get(PlanTier, payment.plan_tier_id)
    current = session.get(PlanTier, sub.plan_tier_id)
    if (
        target is None
        or current is None
        or not is_upgrade(
            current, billed_terms(session, sub), target, current_terms(session, target)
        )
    ):
        return "not_an_upgrade_now"
    # Reprice: what this checkout would cost if it were started at the instant it was priced, from
    # the terms billed NOW. Another upgrade that changed the tier (X landed, this was priced
    # old -> Y), or an admin price change on the target, makes the price differ; a payment that
    # was only converted to credits never moved the tier, so it can never trigger this.
    repriced = prorate_minor(
        current_terms(session, target).price_minor - billed_terms(session, sub).price_minor,
        sub.current_period_start,
        sub.current_period_end,
        payment.created_at,
    )
    return "superseded" if repriced != payment.amount_minor else None


def credit_void_payment(
    session: Session, payment: Payment, sub: Subscription, *, reason: str, paid_at: datetime
) -> None:
    """Turn a paid charge whose effect is void into the beneficiary's credits (UD-P2, DV-17).

    Without an admin-set rate the conversion fails closed: nothing is granted, the payment stays
    ``paid`` and ``merchant_charge_unconvertible`` asks an operator for a manual refund. It never
    raises, because the handler runs in the callback transaction and a raise would reject a
    callback that already moved money.
    """
    try:
        convert_payment_to_credits(session, payment, subscription=sub, now=paid_at)
    except NoCreditRate as exc:
        alerts.error(
            "merchant_charge_unconvertible",
            alert=True,
            payment_id=str(payment.id),
            subscription_id=str(sub.id),
            purpose=payment.purpose.value,
            void_reason=reason,
            reason=exc.reason,
        )
        return
    log.info(
        "merchant_charge_credited",
        payment_id=str(payment.id),
        subscription_id=str(sub.id),
        purpose=payment.purpose.value,
        reason=reason,
    )


def on_upgrade_paid(session: Session, payment: Payment) -> None:
    """Apply a paid ``upgrade_proration`` payment: switch the tier and grant the allowance gain.

    Runs once per payment inside Phase 02's callback or reconcile transaction, after the payment
    lock, the event insert, the integration guard and the amount check (lock order: payment, event,
    subscription, ledger). It makes no Paymob call (DV-1). A payment whose effect is void at settle
    time becomes credits instead (:func:`upgrade_void_reason`).

    Raises:
        RuntimeError: ``payment.paid_at`` is missing (the clock is never guessed).
    """
    paid_at = payment.paid_at
    if paid_at is None:
        raise RuntimeError(f"upgrade payment {payment.id} has no paid_at")
    sub = (
        None
        if payment.subscription_id is None
        else lock_subscription(session, payment.subscription_id)
    )
    if sub is None or payment.plan_tier_id is None:
        alerts.error(
            "merchant_charge_paid_without_subscription", alert=True, payment_id=str(payment.id)
        )
        return
    reason = upgrade_void_reason(session, sub, payment)
    if reason is not None:
        credit_void_payment(session, payment, sub, reason=reason, paid_at=paid_at)
        return
    target = session.get(PlanTier, payment.plan_tier_id)
    assert target is not None  # noqa: S101 - the foreign key, and upgrade_void_reason read it
    old_terms = billed_terms(session, sub)
    new_terms = current_terms(session, target)
    period = current_period(session, sub)
    start, end = sub.current_period_start, sub.current_period_end
    assert start is not None and end is not None  # noqa: S101 - upgrade_void_reason checked
    sub.plan_tier_id = target.id
    sub.terms_version = new_terms.terms_version
    # The pending terms move was for the tier just left: the target's current terms replace it.
    sub.pending_terms_version = None
    sub.pending_terms_effective_at = None
    sub.terms_notice_sent_at = None
    bump_version(sub)
    session.flush()
    units = _allowance_gain(old_terms, new_terms, start, end, paid_at)
    if units > 0 and paid_at < end:
        UsageLedger(session).issue_grant(
            owner_user_id=sub.user_id,
            kind=GrantKind.period_allowance,
            units=units,
            idempotency_key=f"upgrade:{payment.id}",
            expires_at=end,
            visible=False,
            effective_at=paid_at,
            payment_id=payment.id,
            subscription_period_id=None if period is None else period.id,
        )
    log.info(
        "merchant_charge_upgrade_applied",
        payment_id=str(payment.id),
        subscription_id=str(sub.id),
        plan_tier_id=str(target.id),
        granted_units=units if paid_at < end else 0,
    )


def handle_upgrade_paid(session: Session, payment: Payment, obj: Mapping[str, object]) -> None:
    """Paid handler for ``upgrade_proration`` (the callback body is verified and not needed)."""
    del obj
    on_upgrade_paid(session, payment)


register_paid_handler(PaymentPurpose.upgrade_proration, handle_upgrade_paid)


__all__ = [
    "CARD_MOTO_METHOD",
    "FAILED_STATUSES",
    "IN_FLIGHT_STATUSES",
    "MAX_SWEEP_ERRORS",
    "MERCHANT_SWEEP_BATCH",
    "UPGRADE_ITEM_NAME",
    "ChargeAlreadyAttempted",
    "ChargeQuote",
    "ChargesUnavailable",
    "MerchantChargeError",
    "MerchantChargeService",
    "SeatsExceedNewTier",
    "active_seat_count",
    "billed_terms",
    "bump_version",
    "charge_queued_payments",
    "charges_configured",
    "credit_void_payment",
    "current_period",
    "current_terms",
    "fail_unsent",
    "handle_upgrade_paid",
    "insert_queued_payment",
    "is_upgrade",
    "lock_subscription",
    "offered_card_tokens",
    "on_upgrade_paid",
    "payable_subscription",
    "refuse_if_charge_pending",
    "start_present_checkout",
    "upgrade_void_reason",
    "usable_extra_seats",
]
