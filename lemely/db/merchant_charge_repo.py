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
amount. An extra-seat purchase (T5) is the same shape (:meth:`MerchantChargeService
.start_extra_seats_checkout`, :func:`on_extra_seats_paid`) and reuses the planner's helpers and the
upgrade's repricing idea: the seats are repriced at settle from the terms billed then, so an
upgrade that moved the seat price in between sends the money to credits, never to seats at the old
price. A seat reduction (:meth:`~MerchantChargeService.schedule_seat_reduction`) only records
``pending_extra_seats``; it makes no Paymob call either.

Logs carry payment ids, status codes and flags only: never the card token (plain or encrypted),
the payment key, the intention client secret, billing data or a response body.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Final

import sqlalchemy as sa
import structlog
from sqlalchemy import event as sa_event
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import aliased

from lemely.core.subscription_rules import AMOUNT_SYNC_WINDOW, subscription_amount_minor
from lemely.core.usage_pricing import prorate_minor, prorate_units
from lemely.db.billing_notices import enqueue_extra_seats_charge_failed
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
    PAYMENT_VOID_REASONS,
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
from lemely.db.models.billing_ops import BillingSettings
from lemely.db.models.enums import SubscriptionStatus
from lemely.db.models.team import TeacherMember, TeacherMemberKind, TeacherMemberStatus
from lemely.db.models.usage import GrantKind
from lemely.db.plan_terms_repo import (
    TierTerms,
    current_terms_for,
    terms_for,
    tier_terms,
)
from lemely.db.subscription_repo import (
    AmountPush,
    NoCreditRate,
    SubscriptionService,
    convert_payment_to_credits,
)
from lemely.db.teacher_team_repo import TeacherTeamService
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
#: ``payments.dedupe_key`` prefix of a fallback renewal seat charge (T6): it pays for seats the
#: subscription already holds, so its paid handler never adds any.
RENEWAL_SEAT_DEDUPE_PREFIX: Final = "extra_seat_renewal:"
#: The soonest a failed renewal seat charge is tried again: one attempt a day, never faster.
SEAT_RETRY_INTERVAL: Final = timedelta(days=1)
#: Upper bound on one seat purchase; a typo should not charge for a thousand seats.
MAX_SEATS_PER_PURCHASE: Final = 100

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


class SeatsNotSold(MerchantChargeError):
    """The target plan sells no extra seats while the teacher holds some (UD-5's rule, mirrored)."""

    def __init__(self, *, extra_seats: int) -> None:
        super().__init__(
            "seats_not_sold",
            "The new plan does not sell extra seats, and this plan has some",
            detail={"extra_seats": extra_seats},
        )
        self.extra_seats = extra_seats


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

    def maybe_enqueue_auto_topup(self, owner_user_id: uuid.UUID, now: datetime) -> Payment | None:
        """Queue at most one auto top-up for ``owner_user_id`` in this session's transaction.

        The index contract's name for ``auto_topup_repo.enqueue_auto_topup``, whose result it
        returns. The import is function-local: ``auto_topup_repo`` imports this module (DV-12).
        """
        from lemely.db.auto_topup_repo import enqueue_auto_topup

        return enqueue_auto_topup(self._session, owner_user_id, now=now)

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
        terms_version: int | None = None,
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
            terms_version=terms_version,
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
            terms_version=current_terms_for(self._session, plan.new_tier).terms_version,
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
        old_terms = terms_for(session, sub)
        new_terms = current_terms_for(session, new_tier)
        if not is_upgrade(old_tier, old_terms, new_tier, new_terms):
            raise MerchantChargeError("not_an_upgrade", "That plan is not an upgrade")
        if new_tier.audience is PlanAudience.teacher:
            if _seats_not_sold(sub, new_tier, new_terms):
                raise SeatsNotSold(extra_seats=usable_extra_seats(sub))
            in_use = active_seat_count(session, sub.user_id)
            capacity = new_terms.included_seats + usable_extra_seats(sub)
            if in_use > capacity:
                raise SeatsExceedNewTier(in_use=in_use, capacity=capacity)
        start, end = sub.current_period_start, sub.current_period_end
        if start is None or end is None:
            raise MerchantChargeError("subscription_not_active", "The plan has no current period")
        amount = _upgrade_amount(
            old_terms, new_terms, _priced_extra_seats(sub, new_tier), start, end, now
        )
        if amount <= 0:
            raise MerchantChargeError("period_ending", "The current period is about to end")
        self._refuse_in_amount_window(sub, now)
        allowance = _allowance_gain(old_terms, new_terms, start, end, now)
        return _UpgradePlan(
            subscription=sub,
            new_tier=new_tier,
            amount_minor=amount,
            currency=new_tier.currency,
            allowance_units=allowance,
            period_end=end,
        )

    def _refuse_in_amount_window(self, sub: Subscription, now: datetime) -> None:
        """Refuse a seat or upgrade charge whose new renewal amount Paymob could not learn in time.

        UD-P6. A change paid for now reaches Paymob only through a push of the new renewal amount
        after the settle. Only a manually activated plan is exempt: Paymob never renews it. A
        card plan whose Paymob link has not landed yet (``upgrade_unavailable``, as for an
        upgrade) is refused at any time: nothing can push its amount, and the renewal webhook
        would link it at the old amount and carry the new seats or tier for free. Within
        ``AMOUNT_SYNC_WINDOW`` of the period end there may be no time left to repair a failed or
        unknown push before Paymob renews, so a charge is allowed only while the amount is
        confirmed: Paymob takes amount updates and its stamp equals the renewal amount Lemely
        expects now (``period_ending`` otherwise).
        """
        if sub.is_manually_activated:
            return
        if sub.paymob_subscription_id is None:
            raise MerchantChargeError("upgrade_unavailable", "This plan cannot be changed yet")
        end = sub.current_period_end
        if end is None or now < end - AMOUNT_SYNC_WINDOW:
            return
        confirmed = (
            self._settings.subscription_amount_updatable
            and sub.paymob_amount_minor
            == SubscriptionService(self._session, self._client, self._settings).next_renewal_amount(
                sub
            )
        )
        if not confirmed:
            raise MerchantChargeError(
                "period_ending",
                "The renewal is too close to change the plan or seats; try after it renews",
            )

    # -- payer-present extra seats (3DS checkout, saved cards offered) -----------

    def quote_extra_seats(
        self,
        *,
        subscription_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        seats: int,
        now: datetime,
    ) -> ChargeQuote:
        """What ``seats`` extra seats would charge now; writes nothing, calls nobody.

        The same planner as :meth:`start_extra_seats_checkout`, so the amount and period end
        match what the checkout would bill. A seat purchase adds no allowance
        (``allowance_units is None``).
        """
        plan = self._plan_extra_seats(
            subscription_id=subscription_id,
            actor_user_id=actor_user_id,
            seats=seats,
            now=now,
            lock=False,
        )
        return ChargeQuote(
            amount_minor=plan.amount_minor,
            currency=plan.currency,
            allowance_units=None,
            period_end=plan.period_end,
        )

    def start_extra_seats_checkout(
        self,
        *,
        subscription_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        seats: int,
        now: datetime,
    ) -> CheckoutResult:
        """Record an ``extra_seats`` payment and open its 3DS checkout.

        Refuses before any write (:class:`MerchantChargeError`, or
        :class:`~lemely.db.billing_repo.PhoneRequired`); the caller rolls back. Past the refusals
        the payment is committed ``created`` by Phase 02's checkout before Paymob is called, which
        also releases the subscription lock. No saved card is needed: the payer may type a new
        one in Unified Checkout. :class:`~lemely.db.billing_repo.CheckoutUnavailable` propagates:
        the payer never got a client secret, so nothing was charged. Seats are added only when
        the verified callback arrives (:func:`on_extra_seats_paid`).
        """
        plan = self._plan_extra_seats(
            subscription_id=subscription_id,
            actor_user_id=actor_user_id,
            seats=seats,
            now=now,
            lock=True,
        )
        refuse_if_charge_pending(self._session, plan.subscription.id)
        payer = self._session.get(User, actor_user_id)
        if payer is None:
            raise MerchantChargeError("unknown_payer", "The payer has no account")
        billing_data_for(payer)  # PhoneRequired before any write
        payment = self.new_payment(
            purpose=PaymentPurpose.extra_seats,
            payer_user_id=actor_user_id,
            beneficiary_user_id=plan.subscription.user_id,
            amount_minor=plan.amount_minor,
            currency=plan.currency,
            subscription_id=plan.subscription.id,
            seat_quantity=seats,
            terms_version=plan.subscription.terms_version,
        )
        # The injected clock is the checkout's birth: the void-at-settle rules compare against it.
        payment.created_at = now
        self._session.flush()
        return start_present_checkout(
            self._session,
            self._client,
            self._settings,
            payment=payment,
            item_name=SEATS_ITEM_NAME,
            now=now,
        )

    def _plan_extra_seats(
        self,
        *,
        subscription_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        seats: int,
        now: datetime,
        lock: bool,
    ) -> _SeatPlan:
        """Validate a seat purchase and price it; the one planner the quote and checkout share."""
        session = self._session
        if not 1 <= seats <= MAX_SEATS_PER_PURCHASE:
            raise MerchantChargeError(
                "invalid_seats", f"Buy between 1 and {MAX_SEATS_PER_PURCHASE} seats at a time"
            )
        sub = payable_subscription(session, subscription_id, actor_user_id, lock=lock)
        if sub.cancel_at_period_end:
            raise MerchantChargeError("plan_change_pending", "The plan is set to end")
        tier = session.get(PlanTier, sub.plan_tier_id)
        assert tier is not None  # noqa: S101 - the foreign key
        terms = terms_for(session, sub)
        if tier.audience is not PlanAudience.teacher or terms.extra_seat_price_minor <= 0:
            raise MerchantChargeError("not_a_teacher_plan", "This plan does not sell extra seats")
        if (sub.extra_seats or 0) + seats > seat_ceiling(session):
            raise MerchantChargeError(
                "invalid_seats", "That would pass the most extra seats allowed"
            )
        if sub.pending_extra_seats is not None:
            raise MerchantChargeError(
                "seat_reduction_pending", "A seat reduction is already scheduled"
            )
        if sub.extra_seat_grace_until is not None:
            raise MerchantChargeError("seat_charge_overdue", "The last seat charge was not paid")
        start, end = sub.current_period_start, sub.current_period_end
        if start is None or end is None:
            raise MerchantChargeError("subscription_not_active", "The plan has no current period")
        amount = _seat_amount(seats, terms.extra_seat_price_minor, start, end, now)
        if amount <= 0:
            raise MerchantChargeError("period_ending", "The current period is about to end")
        self._refuse_in_amount_window(sub, now)
        return _SeatPlan(
            subscription=sub,
            seat_price_minor=terms.extra_seat_price_minor,
            amount_minor=amount,
            currency=tier.currency,
            period_end=end,
        )

    def schedule_seat_reduction(
        self,
        *,
        subscription_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        extra_seats: int,
        now: datetime,
    ) -> Subscription:
        """Set ``pending_extra_seats`` to the extra-seat count wanted from the next renewal.

        No Paymob call: the renewal bills the lower count and Phase 05's drift check and
        period-end sweep push the amount. Asking for the current count clears a pending reduction.
        The caller commits. Refusals, all before a write: ``not_a_teacher_plan``,
        ``not_a_reduction`` (outside ``0..extra_seats``), ``seat_reduction_locked`` (see
        :func:`_upgrade_applied_this_period`), ``seats_in_use`` (active plus leaving seats would
        not fit, DV-8) and, on the fixed-amount fallback path, ``seat_reduction_unavailable``.
        """
        session = self._session
        sub = payable_subscription(session, subscription_id, actor_user_id, lock=True)
        tier = session.get(PlanTier, sub.plan_tier_id)
        assert tier is not None  # noqa: S101 - the foreign key
        if tier.audience is not PlanAudience.teacher:
            raise MerchantChargeError("not_a_teacher_plan", "This plan has no student seats")
        held = sub.extra_seats or 0
        if not 0 <= extra_seats <= held:
            raise MerchantChargeError(
                "not_a_reduction", "Buy seats to add them; this only removes seats"
            )
        pending = sub.pending_extra_seats
        if (
            pending is not None
            and extra_seats > pending
            and _upgrade_applied_this_period(session, sub)
        ):
            # Lifting the reduction would bring seats back at a price an upgrade never charged.
            raise MerchantChargeError(
                "seat_reduction_locked",
                "The scheduled reduction cannot be lifted after a plan upgrade this period",
            )
        if extra_seats == held:
            if pending is None:
                return sub
            sub.pending_extra_seats = None
        else:
            terms = terms_for(session, sub)
            if terms.included_seats + extra_seats < TeacherTeamService(session).seats_used(
                sub.user_id
            ):
                raise MerchantChargeError("seats_in_use", "Free the seats before removing them")
            if (
                not self._settings.subscription_amount_updatable
                and sub.paymob_amount_minor is not None
                and subscription_amount_minor(
                    price_minor=terms.price_minor,
                    extra_seats=extra_seats,
                    extra_seat_price_minor=terms.extra_seat_price_minor,
                )
                < sub.paymob_amount_minor
            ):
                # Paymob would keep charging the higher amount it holds.
                raise MerchantChargeError(
                    "seat_reduction_unavailable", "These seats cannot be removed on this plan yet"
                )
            sub.pending_extra_seats = extra_seats
        bump_version(sub)
        session.flush()
        log.info(
            "seat_reduction_scheduled",
            subscription_id=str(sub.id),
            pending=sub.pending_extra_seats,
            at=now.isoformat(),
        )
        return sub

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
# Payer-present charges: shared helpers (the upgrade and the seat purchase use them).
# ---------------------------------------------------------------------------

#: The intention item name of an upgrade (Paymob shows it on the receipt).
UPGRADE_ITEM_NAME: Final = "Plan upgrade (prorated)"
#: The intention item name of a seat purchase.
SEATS_ITEM_NAME: Final = "Extra student seats"


@dataclass(frozen=True, slots=True)
class ChargeQuote:
    """What a payer-present charge would cost now, as the quote route shows it."""

    amount_minor: int
    currency: str
    #: Allowance units an upgrade adds; ``None`` for a seat purchase (it adds no allowance).
    allowance_units: int | None
    period_end: datetime


@dataclass(frozen=True, slots=True)
class _SeatPlan:
    subscription: Subscription
    seat_price_minor: int
    amount_minor: int
    currency: str
    period_end: datetime


@dataclass(frozen=True, slots=True)
class _UpgradePlan:
    subscription: Subscription
    new_tier: PlanTier
    amount_minor: int
    currency: str
    allowance_units: int
    period_end: datetime


class SeatCeilingSettingMissing(MerchantChargeError):
    """``billing_settings`` has no row: the seat ceiling is unknown, so nothing is sold."""

    def __init__(self) -> None:
        super().__init__("payments_unavailable", "The seat ceiling setting is missing")


def seat_ceiling(session: Session) -> int:
    """The most extra seats one subscription may hold: ``billing_settings.max_extra_seats``.

    Fails closed, as the credit-validity read does: ``create_all`` and the migration both insert
    the row, so a missing one is a damaged database. It raises :class:`SeatCeilingSettingMissing`
    and alerts, and no constant stands in for it (a purchase is refused; a paid handler fails,
    the callback rolls back and Paymob retries).
    """
    configured = session.scalar(
        sa.select(BillingSettings.max_extra_seats).where(BillingSettings.id == 1)
    )
    if configured is None:
        alerts.error("seat_ceiling_setting_missing", alert=True)
        raise SeatCeilingSettingMissing
    return int(configured)


def _seat_amount(
    seats: int, seat_price_minor: int, start: datetime, end: datetime, at: datetime
) -> int:
    """What ``seats`` extra seats cost at ``at``: the seat price for the rest of the period.

    The quote, the checkout and the settle-time reprice all use this one function, so a seat
    price that moved in between is a mismatch and voids the payment to credits.
    """
    return prorate_minor(seats * seat_price_minor, start, end, at)


def _upgrade_applied_this_period(session: Session, sub: Subscription) -> bool:
    """True when a paid upgrade that changed the plan landed in the current period (I3).

    An upgrade prices the seats the subscription will bill (``usable_extra_seats``): the seats a
    pending reduction drops are charged nothing at the new seat price. Lifting that reduction
    afterwards would bring them back at a price nobody paid, so :meth:`schedule_seat_reduction`
    refuses to lift one while such an upgrade exists. Only a payment the paid handler applied
    (``applied_at`` set) counts: one voided to credits, or left unconverted for want of a credit
    rate, changed nothing. The rule is conservative in that it cannot tell a reduction scheduled
    before the upgrade from one scheduled after it, because the reduction carries no timestamp;
    deeper reductions stay allowed and the lock ends at the renewal.
    """
    start = sub.current_period_start
    if start is None:
        return True
    return (
        session.scalar(
            sa.select(Payment.id)
            .where(
                Payment.subscription_id == sub.id,
                Payment.purpose == PaymentPurpose.upgrade_proration,
                Payment.status == PaymentStatus.paid,
                Payment.applied_at.is_not(None),
                Payment.paid_at >= start,
            )
            .limit(1)
        )
        is not None
    )


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


#: The tier's current terms (P06-T4's name, kept for the admin payments module): the one reader is
#: :func:`lemely.db.plan_terms_repo.current_terms_for`.
current_terms = current_terms_for


def is_upgrade(
    old_tier: PlanTier, old_terms: TierTerms, new_tier: PlanTier, new_terms: TierTerms
) -> bool:
    """Same audience, interval and currency, and a higher price than the one being paid."""
    return (
        new_tier.id != old_tier.id
        and new_tier.audience is old_tier.audience
        and new_tier.interval is old_tier.interval
        and new_tier.currency == old_tier.currency
        and new_terms.price_minor > old_terms.price_minor
    )


def _seats_not_sold(sub: Subscription, new_tier: PlanTier, new_terms: TierTerms) -> bool:
    """True when a teacher holds extra seats and the target tier sells none (seat price 0).

    Such a plan holds no extra seats whatever the row says (the renewal bills none), so an upgrade
    would either drop seats the teacher paid for or keep them for free. It is refused, as a
    downgrade below the held seats is (UD-5).
    """
    return (
        new_tier.audience is PlanAudience.teacher
        and new_terms.extra_seat_price_minor <= 0
        and usable_extra_seats(sub) > 0
    )


def _priced_extra_seats(sub: Subscription, new_tier: PlanTier) -> int:
    """Extra seats whose price changes with an upgrade: a teacher plan's usable extra seats.

    A scheduled reduction lowers them at once (the seats it drops are not billed again), the same
    figure the capacity check uses. A student plan sells no seats.
    """
    return usable_extra_seats(sub) if new_tier.audience is PlanAudience.teacher else 0


def _upgrade_amount(
    old_terms: TierTerms,
    new_terms: TierTerms,
    extra_seats: int,
    start: datetime,
    end: datetime,
    at: datetime,
) -> int:
    """What an upgrade charges at ``at``: the base price difference plus the seat price difference.

    The seat part is ``(new seat price - billed seat price) x extra_seats``, added to the base
    difference and prorated once for the rest of the period (so both parts round together). A
    cheaper seat price makes it negative and nets against the base; the charge is never below one
    piaster (Paymob needs a positive amount). ``0`` only when the period is over, which the quote
    and the checkout refuse as ``period_ending``. The quote, the checkout and the settle-time
    reprice all use this one function, so a seat change that moves the price in between is a
    mismatch and voids the payment to credits. A change that leaves the price equal (the same seat
    price on both plans, or the 1-piaster floor) applies the upgrade: nothing was under-collected.
    """
    base_diff = new_terms.price_minor - old_terms.price_minor
    if prorate_minor(max(base_diff, 0), start, end, at) <= 0:
        return 0
    seat_diff = (new_terms.extra_seat_price_minor - old_terms.extra_seat_price_minor) * extra_seats
    return max(prorate_minor(max(base_diff + seat_diff, 0), start, end, at), 1)


def _allowance_gain(
    old_terms: TierTerms,
    new_terms: TierTerms,
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


def _terms_moved(payment: Payment, terms_version_now: int) -> bool:
    """True when the terms the payment was priced on are no longer the ones in force.

    An edit that keeps the price but changes the allowance or the seats would pass the amount
    comparison and sell the payer something other than the quote (P06-T4 m2). A payment without a
    recorded version (written before the column) is not checked.
    """
    return payment.terms_version is not None and payment.terms_version != terms_version_now


def upgrade_void_reason(session: Session, sub: Subscription, payment: Payment) -> str | None:
    """Why a paid upgrade no longer buys what it was priced for, or ``None`` when it does (DV-26).

    Checked under the subscription lock, in this order: the plan ended; the period rolled since
    the checkout was priced; the target is no longer an upgrade over the tier now billed (another
    payment already switched it); the target sells no extra seats while the teacher holds some
    (``seats_not_sold``); the price recomputed from the terms billed now, at the instant the
    checkout was priced, differs from the amount charged (an upgrade landed after the quote, the
    target's price changed, or a seat change moved the price).

    A downgrade or cancel scheduled after the checkout is not re-checked here, and neither is a
    seat change that leaves the price and the seat-sold test as they were: the payer bought the
    upgrade for the rest of the period, and the scheduled change takes effect at the renewal as it
    would have anyway, so no money is lost either way.
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
            current, terms_for(session, sub), target, current_terms_for(session, target)
        )
    ):
        return "not_an_upgrade_now"
    # Reprice: what this checkout would cost if it were started at the instant it was priced, from
    # the terms billed NOW. Another upgrade that changed the tier (X landed, this was priced
    # old -> Y), or an admin price change on the target, makes the price differ; a payment that
    # was only converted to credits never moved the tier, so it can never trigger this.
    if _seats_not_sold(sub, target, current_terms_for(session, target)):
        return "seats_not_sold"
    if _terms_moved(payment, current_terms_for(session, target).terms_version):
        return "superseded"
    repriced = _upgrade_amount(
        terms_for(session, sub),
        current_terms_for(session, target),
        _priced_extra_seats(sub, target),
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

    The reason is stamped on the payment either way (``void_reason``), so the return page can say
    what happened. An unknown reason is a programming error the CHECK would refuse at flush, so it
    is not stamped and not converted: ``merchant_charge_void_reason_unknown`` alerts an operator
    and the payment stays ``paid`` (not applied, not credited) for a manual refund.
    """
    if reason not in PAYMENT_VOID_REASONS:
        alerts.error(
            "merchant_charge_void_reason_unknown",
            alert=True,
            payment_id=str(payment.id),
            subscription_id=str(sub.id),
            purpose=payment.purpose.value,
            void_reason=reason,
        )
        return
    payment.void_reason = reason
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
    old_terms = terms_for(session, sub)
    new_terms = current_terms_for(session, target)
    period = current_period(session, sub)
    start, end = sub.current_period_start, sub.current_period_end
    assert start is not None and end is not None  # noqa: S101 - upgrade_void_reason checked
    sub.plan_tier_id = target.id
    sub.terms_version = new_terms.terms_version
    # The pending terms move was for the tier just left: the target's current terms replace it.
    sub.pending_terms_version = None
    sub.pending_terms_effective_at = None
    sub.terms_notice_sent_at = None
    payment.applied_at = paid_at  # the one marker that this payment bought what it priced
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
    queue_amount_push(session, sub.id)
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


# ---------------------------------------------------------------------------
# Pushing the new renewal amount after a settle (UD-P6).
# ---------------------------------------------------------------------------

#: ``session.info`` key holding the subscription ids whose amount to push when the session commits.
_PUSH_KEY: Final = "merchant_charge_amount_pushes"
_amount_pusher: Callable[[uuid.UUID], None] | None = None


def register_amount_pusher(pusher: Callable[[uuid.UUID], None] | None) -> None:
    """Set the function that pushes one subscription's renewal amount (wiring, T10).

    A paid handler holds no Paymob client (DV-1), so the process that serves callbacks registers
    one, typically ``functools.partial(push_renewal_amount, factory, client, settings)``. ``None``
    unregisters it. Without one a settle logs ``subscription_amount_push_not_configured`` and the
    window refusal plus Phase 05's period-end sweep still protect the renewal.
    """
    global _amount_pusher
    _amount_pusher = pusher


def push_renewal_amount(
    factory: sessionmaker[Session],
    client: PaymobClient,
    settings: PaymobSettings,
    subscription_id: uuid.UUID,
) -> None:
    """Push the subscription's renewal amount with Phase 05's ``sync_renewal_amount``.

    Its own transaction, so it never runs inside the callback's. A definite refusal, and an
    unknown outcome (which leaves the stamp behind the expected amount), are not pushed: both log
    ``subscription_amount_push_failed`` with ``alert=True``, and the window refusal then holds
    until the amount is confirmed.
    """
    with factory.begin() as session:
        sub = lock_subscription(session, subscription_id)
        if sub is None:
            return
        if (
            sub.status is not SubscriptionStatus.active
            or sub.cancel_at_period_end
            or sub.paymob_subscription_id is None
            or sub.paymob_cancelled_at is not None
        ):
            # The sweep's own guards: a plan that is ending or gone has no amount worth changing.
            log.info("subscription_amount_push_skipped", subscription_id=str(subscription_id))
            return
        service = SubscriptionService(session, client, settings)
        try:
            pushed = service.sync_renewal_amount(sub)
        except PaymobError as exc:
            alerts.error(
                "subscription_amount_push_failed",
                alert=True,
                subscription_id=str(subscription_id),
                reason="refused",
                status_code=exc.status_code,
            )
            return
        if (
            sub.paymob_subscription_id is not None
            and settings.subscription_amount_updatable
            and sub.paymob_amount_minor != service.next_renewal_amount(sub)
        ):
            alerts.error(
                "subscription_amount_push_failed",
                alert=True,
                subscription_id=str(subscription_id),
                reason="period_over" if pushed is AmountPush.PERIOD_OVER else "unknown_outcome",
            )


def _run_amount_push(subscription_id: uuid.UUID) -> None:
    pusher = _amount_pusher
    if pusher is None:
        log.warning("subscription_amount_push_not_configured", subscription_id=str(subscription_id))
        return
    try:
        pusher(subscription_id)
    except Exception as exc:
        # After the commit: nothing may undo the settle, and the sweep repairs the stamp.
        alerts.error(
            "subscription_amount_push_failed",
            alert=True,
            subscription_id=str(subscription_id),
            reason="error",
            error_type=type(exc).__name__,
        )


def _pushes_after_commit(session: Session) -> None:
    # A savepoint release also dispatches this; only the outermost commit pushes.
    if session.in_nested_transaction():
        return
    for subscription_id in dict.fromkeys(session.info.pop(_PUSH_KEY, [])):
        _run_amount_push(subscription_id)


def _pushes_after_transaction_end(session: Session, ended: object) -> None:
    if getattr(ended, "parent", None) is None:
        session.info.pop(_PUSH_KEY, None)  # a rollback pushes nothing


def queue_amount_push(session: Session, subscription_id: uuid.UUID) -> None:
    """Push ``subscription_id``'s renewal amount once the outermost transaction commits.

    Never inside the callback transaction: Paymob is called after the settle is durable, so a slow
    or failing Paymob cannot reject a callback that already moved money. The push is idempotent
    (it sends only when the stamp differs from the expected amount), so a duplicate is harmless.
    """
    session.info.setdefault(_PUSH_KEY, []).append(subscription_id)
    for name, listener in (
        ("after_commit", _pushes_after_commit),
        ("after_transaction_end", _pushes_after_transaction_end),
    ):
        if not sa_event.contains(session, name, listener):
            sa_event.listen(session, name, listener)


# ---------------------------------------------------------------------------
# The seat purchase's paid handler.
# ---------------------------------------------------------------------------


def seats_void_reason(session: Session, sub: Subscription, payment: Payment) -> str | None:
    """Why a paid seat purchase no longer buys what it was priced for, or ``None`` (DV-26).

    Checked under the subscription lock, in this order: the plan ended; the period rolled since
    the checkout was priced; a reduction was scheduled or a seat grace started since (the
    start-time refusals would now apply); the plan now sells no seats (an upgrade landed);
    the seats would pass the ceiling (another purchase landed); the price recomputed from the
    terms billed now, at the instant the checkout was priced, differs from the amount charged
    (an upgrade moved the seat price after the quote, I4). Two purchases paid close together are
    both applied: each paid for its own seats.
    """
    if (
        sub.status not in PLAN_LIVE_STATUSES
        or sub.current_period_start is None
        or sub.current_period_end is None
    ):
        return "plan_ended"
    if sub.current_period_start > payment.created_at:
        return "period_rolled"
    if sub.pending_extra_seats is not None or sub.extra_seat_grace_until is not None:
        return "seats_changing"
    if _terms_moved(payment, sub.terms_version):
        return "superseded"
    price = terms_for(session, sub).extra_seat_price_minor
    if price <= 0:
        return "seats_not_sold"
    quantity = payment.seat_quantity or 0
    if (sub.extra_seats or 0) + quantity > seat_ceiling(session):
        return "seats_over_limit"
    repriced = _seat_amount(
        quantity, price, sub.current_period_start, sub.current_period_end, payment.created_at
    )
    return "superseded" if repriced != payment.amount_minor else None


def _settle_renewal_seat_payment(
    session: Session, sub: Subscription, payment: Payment, *, paid_at: datetime
) -> None:
    """A fallback renewal seat charge was paid: end its grace, or convert it to credits (UD-P2).

    It pays for seats the subscription already holds, so it adds none. A payment for the period
    whose grace is running ends that grace, even when the period has rolled since: those seats
    were held for it, so the money stands. Otherwise it buys nothing when the plan ended, when it
    belongs to an earlier period, or when its period's grace already ended (the marker says so: a
    drop, or an earlier paid attempt; a late success, R20b, or a callback that waited on the
    drop's subscription lock): that money becomes credits and ``renewal_seat_payment_credited``
    alerts, never silently kept. A grace belonging to another period is left alone.
    """
    assert payment.dedupe_key is not None  # noqa: S101 - the caller matched the prefix
    key_period = payment.dedupe_key.removeprefix(RENEWAL_SEAT_DEDUPE_PREFIX).partition(":")[0]
    period = current_period(session, sub)
    grace_period = _grace_period_id(session, sub)
    reason: str | None = None
    if sub.status not in PLAN_LIVE_STATUSES:
        reason = "plan_ended"
    elif sub.extra_seat_grace_until is not None and grace_period == key_period:
        # This period's grace is paid up, whether or not the period has rolled since: the seats
        # were held for it, so the money stands and the grace ends.
        sub.extra_seat_grace_until = None
        payment.applied_at = paid_at
        bump_version(sub)
        session.flush()
        return
    elif period is None or key_period != str(period.id):
        reason = "period_ended"
    elif grace_period == key_period or (sub.extra_seats or 0) <= 0:
        # The marker says this period's grace already ended (a drop, or an earlier paid attempt):
        # whatever seats are held now were not bought by this payment.
        reason = "seats_dropped"
    if reason is None:
        # No grace is running, this period's marker is not the grace's, and seats are held: the
        # money stands for seats the plan already has, so nothing is voided or credited. Mark it
        # applied, like the grace branch above, so a reader that ignores the key prefix agrees.
        payment.applied_at = paid_at
        session.flush()
        return
    alerts.error(
        "renewal_seat_payment_credited",
        alert=True,
        payment_id=str(payment.id),
        subscription_id=str(sub.id),
        reason=reason,
    )
    credit_void_payment(session, payment, sub, reason=reason, paid_at=paid_at)


def on_extra_seats_paid(session: Session, payment: Payment) -> None:
    """Apply a paid ``extra_seats`` payment: raise ``extra_seats`` by the quantity bought.

    Runs once per payment inside Phase 02's callback or reconcile transaction, after the payment
    lock, the event insert, the integration guard and the amount check (lock order: payment,
    event, subscription, ledger). It makes no Paymob call and leaves ``paymob_amount_minor``
    alone (DV-1): Phase 05's drift check pushes the new amount. A fallback renewal seat payment
    (key prefix :data:`RENEWAL_SEAT_DEDUPE_PREFIX`) pays for seats that already exist and only
    ends the grace. A purchase whose effect is void at settle time becomes credits instead
    (:func:`seats_void_reason`).

    Raises:
        RuntimeError: ``payment.paid_at`` is missing (the clock is never guessed).
        ValueError: a purchase has no ``seat_quantity``.
    """
    paid_at = payment.paid_at
    if paid_at is None:
        raise RuntimeError(f"seat payment {payment.id} has no paid_at")
    sub = (
        None
        if payment.subscription_id is None
        else lock_subscription(session, payment.subscription_id)
    )
    if sub is None:
        alerts.error(
            "merchant_charge_paid_without_subscription", alert=True, payment_id=str(payment.id)
        )
        return
    if payment.dedupe_key is not None and payment.dedupe_key.startswith(RENEWAL_SEAT_DEDUPE_PREFIX):
        _settle_renewal_seat_payment(session, sub, payment, paid_at=paid_at)
        return
    quantity = payment.seat_quantity
    if quantity is None:
        raise ValueError(f"seat purchase {payment.id} has no seat_quantity")
    reason = seats_void_reason(session, sub, payment)
    if reason is not None:
        credit_void_payment(session, payment, sub, reason=reason, paid_at=paid_at)
        return
    sub.extra_seats = (sub.extra_seats or 0) + quantity
    payment.applied_at = paid_at  # the one marker that this payment bought what it priced
    bump_version(sub)
    session.flush()
    queue_amount_push(session, sub.id)
    log.info(
        "merchant_charge_seats_applied",
        payment_id=str(payment.id),
        subscription_id=str(sub.id),
        seats=quantity,
    )


def handle_extra_seats_paid(session: Session, payment: Payment, obj: Mapping[str, object]) -> None:
    """Paid handler for ``extra_seats`` (the callback body is verified and not needed)."""
    del obj
    on_extra_seats_paid(session, payment)


register_paid_handler(PaymentPurpose.extra_seats, handle_extra_seats_paid)


# ---------------------------------------------------------------------------
# The fallback renewal seat charge: grace, daily retries and the seat drop (T6).
# ---------------------------------------------------------------------------


class SeatGraceSettingMissing(MerchantChargeError):
    """``billing_settings`` has no row: the grace length is unknown, so no seat charge is made."""

    def __init__(self) -> None:
        super().__init__("payments_unavailable", "The grace period setting is missing")


@dataclass(frozen=True, slots=True)
class _ShortfallPlan:
    """What an attempt charges: the amount, its currency and the seats it pays for (if whole)."""

    amount_minor: int
    currency: str
    seat_quantity: int | None


def seat_grace_days(session: Session) -> int:
    """The days a failed seat charge may be put right: ``billing_settings.grace_days`` (1 to 7).

    It is also the most attempts one period gets (one a day). Read inside the row's transaction
    and fails closed, like :func:`seat_ceiling`: no row, no constant stands in for it.
    """
    configured = session.scalar(
        sa.select(BillingSettings.grace_days).where(BillingSettings.id == 1)
    )
    if configured is None:
        alerts.error("seat_grace_setting_missing", alert=True)
        raise SeatGraceSettingMissing
    return int(configured)


#: Alerts already raised by this process, by ``(event, key)``: a condition that stays true (a
#: period whose terms are unknown, a drop that cannot proceed) must alert once, not every run.
_ALERTED: Final[set[tuple[str, str]]] = set()
_ALERTED_MAX: Final = 10_000
#: How long past its deadline a grace may wait on an unresolved attempt before it is alerted.
DROP_STUCK_ALERT_AFTER: Final = timedelta(hours=24)


def _alert_once(event: str, key: str, **fields: object) -> None:
    """Raise ``event`` (``alert=True``) the first time this process sees ``key``.

    A restart, or another replica, may alert once more; the set is cleared when it grows large.
    """
    ident = (event, key)
    if ident in _ALERTED:
        return
    if len(_ALERTED) >= _ALERTED_MAX:
        _ALERTED.clear()
    _ALERTED.add(ident)
    alerts.error(event, alert=True, **fields)


def _attempt_prefix(period_id: uuid.UUID) -> str:
    return f"{RENEWAL_SEAT_DEDUPE_PREFIX}{period_id}:"


def _renewal_payment(session: Session, period: SubscriptionPeriod) -> Payment | None:
    """The paid ``subscription_renewal`` payment that bought ``period``, else ``None``.

    The first period is paid by the ``subscription_first`` checkout, whose amount already carried
    the seats (P05 DV-6): it never qualifies (DV-3).
    """
    if period.payment_id is None:
        return None
    payment = session.get(Payment, period.payment_id)
    if (
        payment is None
        or payment.purpose is not PaymentPurpose.subscription_renewal
        or payment.status is not PaymentStatus.paid
    ):
        return None
    return payment


def _period_terms(
    session: Session, sub: Subscription, period: SubscriptionPeriod, renewal: Payment
) -> TierTerms | None:
    """The terms the period was billed on, never the tier's live ones (UD13-A, DV-3), or ``None``.

    ``period.terms_version`` when the renewal stamped it, on the renewal payment's own tier.
    Otherwise the terms the subscriber is billed on (:func:`terms_for`), but only while the
    subscription is still on the renewal's tier. After a tier change (an upgrade) with no stamped
    version the billed terms of the period cannot be known exactly, and a guess would turn the
    upgrade's price gap into a "seat" charge: ``None``, and the caller charges nothing.
    """
    tier_id = renewal.plan_tier_id or sub.plan_tier_id
    if period.terms_version is None:
        return terms_for(session, sub) if tier_id == sub.plan_tier_id else None
    terms = tier_terms(session, tier_id, period.terms_version)
    if terms is None:
        raise RuntimeError(f"subscription {sub.id} has no terms row for its period")
    return terms


def _holds_seats_to_charge(session: Session, sub: Subscription) -> bool:
    """An active, Paymob-linked teacher plan with extra seats (item 2 of the brief)."""
    if (
        sub.status is not SubscriptionStatus.active
        or sub.paymob_subscription_id is None
        or (sub.extra_seats or 0) <= 0
    ):
        return False
    tier = session.get(PlanTier, sub.plan_tier_id)
    return tier is not None and tier.audience is PlanAudience.teacher


def renewal_seat_shortfall(session: Session, sub: Subscription, period: SubscriptionPeriod) -> int:
    """Minor units of extra seats the period's renewal charge did not cover, or ``0`` (DV-3).

    ``expected`` is the period's own terms (price plus the extra seats at their seat price);
    ``charged`` is the renewal payment's amount. Seats bought and paid during this period are
    taken off (they paid the prorated share when bought; abandoned checkouts and purchases turned
    into credits do not count, DV-27). A period whose terms cannot be known exactly (the tier
    changed and the renewal stamped no version) owes nothing and alerts
    ``extra_seat_terms_unknown``.
    The result is clamped to the value of the extra seats, so a renewal that was cheap for any
    other reason never turns into a bigger charge. It never reads ``paymob_amount_minor`` or the
    tier's live price: after an upgrade or a price rise those would charge something that is not
    a seat. ``0`` for anything that does not qualify (not active, not linked, no extra seats, a
    first period, a period no paid renewal bought).
    """
    if not _holds_seats_to_charge(session, sub):
        return 0
    renewal = _renewal_payment(session, period)
    if renewal is None:
        return 0
    terms = _period_terms(session, sub, period, renewal)
    if terms is None:
        _alert_once(
            "extra_seat_terms_unknown",
            str(period.id),
            subscription_id=str(sub.id),
            period_id=str(period.id),
        )
        return 0
    seat_price = terms.extra_seat_price_minor
    extra = sub.extra_seats or 0
    if seat_price <= 0:
        return 0
    expected = subscription_amount_minor(
        price_minor=terms.price_minor, extra_seats=extra, extra_seat_price_minor=seat_price
    )
    bought = session.scalar(
        sa.select(sa.func.coalesce(sa.func.sum(Payment.seat_quantity), 0)).where(
            Payment.subscription_id == sub.id,
            Payment.purpose == PaymentPurpose.extra_seats,
            Payment.dedupe_key.is_(None),
            Payment.status == PaymentStatus.paid,
            Payment.applied_at.is_not(None),  # a voided or credited purchase added no seats
            Payment.created_at >= period.period_start,
        )
    )
    gap = expected - renewal.amount_minor - int(bought or 0) * seat_price
    return max(0, min(extra * seat_price, gap))


def _seat_checkout_open(session: Session, sub: Subscription, now: datetime) -> bool:
    """A seat purchase checkout that may still be paid (DV-27): ``created`` or ``pending``.

    It can be paid until its intention expires and reconcile has looked, so a charge queued now
    could pay for the same seats a second time.
    """
    window = timedelta(seconds=INTENTION_EXPIRATION_SECONDS) + RECONCILE_AFTER
    return (
        session.scalar(
            sa.select(Payment.id)
            .where(
                Payment.subscription_id == sub.id,
                Payment.purpose == PaymentPurpose.extra_seats,
                Payment.dedupe_key.is_(None),
                Payment.status.in_(IN_FLIGHT_STATUSES),
                Payment.created_at > now - window,
            )
            .limit(1)
        )
        is not None
    )


def _queue_attempt(
    session: Session,
    sub: Subscription,
    period: SubscriptionPeriod,
    attempt: int,
    plan: _ShortfallPlan,
) -> Payment | None:
    """Queue attempt ``attempt`` of the period; ``None`` when that key already exists."""
    return insert_queued_payment(
        session,
        purpose=PaymentPurpose.extra_seats,
        payer_user_id=sub.payer_user_id or sub.user_id,
        beneficiary_user_id=sub.user_id,
        amount_minor=plan.amount_minor,
        currency=plan.currency,
        dedupe_key=f"{_attempt_prefix(period.id)}{attempt}",
        subscription_id=sub.id,
        seat_quantity=plan.seat_quantity,
    )


def queue_renewal_seat_charge(
    session: Session, sub: Subscription, period: SubscriptionPeriod, *, now: datetime
) -> Payment | None:
    """Queue attempt 1 of the period's uncovered seats; ``None`` when there is nothing to queue.

    ``None`` too when a seat purchase checkout may still be paid (:func:`_seat_checkout_open`:
    the next run looks again) or the attempt already exists. The caller commits. It does not look
    at ``subscription_amount_updatable``: only the fallback path may queue, and the job
    (:func:`run_extra_seat_renewal_job`) is the one place that knows the setting.
    """
    shortfall = renewal_seat_shortfall(session, sub, period)
    if shortfall <= 0:
        return None
    renewal = _renewal_payment(session, period)
    if renewal is None:
        return None
    if _seat_checkout_open(session, sub, now):
        log.info("renewal_seat_charge_deferred", subscription_id=str(sub.id))
        return None
    terms = _period_terms(session, sub, period, renewal)
    if terms is None:
        return None
    seat_price = terms.extra_seat_price_minor
    whole = shortfall % seat_price == 0
    plan = _ShortfallPlan(shortfall, renewal.currency, shortfall // seat_price if whole else None)
    return _queue_attempt(session, sub, period, 1, plan)


def _period_attempts(
    session: Session, sub: Subscription, period: SubscriptionPeriod
) -> list[Payment]:
    """This period's seat charge attempts in attempt order, anchored on the subscription."""
    prefix = _attempt_prefix(period.id)
    rows = session.scalars(
        sa.select(Payment).where(
            Payment.subscription_id == sub.id,
            Payment.purpose == PaymentPurpose.extra_seats,
            Payment.dedupe_key.startswith(prefix, autoescape=True),
        )
    ).all()
    return sorted(rows, key=lambda row: int((row.dedupe_key or prefix).removeprefix(prefix) or 0))


def _grace_period_id(session: Session, sub: Subscription) -> str | None:
    """The period the running grace belongs to: the one its first failed attempt was keyed to."""
    if sub.extra_seat_grace_payment_id is None:
        return None
    key = session.scalar(
        sa.select(Payment.dedupe_key).where(Payment.id == sub.extra_seat_grace_payment_id)
    )
    if key is None or not key.startswith(RENEWAL_SEAT_DEDUPE_PREFIX):
        return None
    return key.removeprefix(RENEWAL_SEAT_DEDUPE_PREFIX).partition(":")[0]


def _drop_extra_seats(session: Session, sub: Subscription, *, now: datetime) -> None:
    """End the grace by removing the extra seats and the newest students beyond the plan's own.

    ``extra_seat_grace_payment_id`` stays: the same failed period never starts a second grace.
    Every extra seat goes, including ones bought and paid earlier in the period: they were paid
    for the period that has ended and the new period's amount is unpaid, so no credit is owed.
    Takes member row locks only (subscription, then members) and no ledger lock.
    """
    included = terms_for(session, sub).included_seats
    dropped = sub.extra_seats or 0
    sub.extra_seats = 0
    sub.pending_extra_seats = None
    sub.extra_seat_grace_until = None
    bump_version(sub)
    session.flush()
    held = list(
        session.scalars(
            sa.select(TeacherMember.id)
            .where(
                TeacherMember.teacher_user_id == sub.user_id,
                TeacherMember.kind == TeacherMemberKind.student_seat,
                TeacherMember.status == TeacherMemberStatus.active,
            )
            .order_by(TeacherMember.created_at.desc(), TeacherMember.id.desc())
            .with_for_update(of=TeacherMember)
        )
    )
    removed = held[: max(0, len(held) - included)]
    team = TeacherTeamService(session)
    for member_id in removed:
        team.request_removal(member_id, now=now)
    alerts.error(
        "extra_seats_dropped",
        alert=True,
        subscription_id=str(sub.id),
        extra_seats=dropped,
        members_removed=len(removed),
    )


def _end_grace(session: Session, sub: Subscription, *, now: datetime) -> bool:
    """The grace has elapsed: fail every unsent retry, then drop the seats unless one is unknown.

    A queued (``created``) retry was never sent, so it is failed unsent (no MOTO call) in this
    transaction, before the drop: otherwise the charge pass would bill the card for seats that
    were just removed. A ``pending`` retry may already have charged the card, so the drop waits
    for its outcome (callback or reconcile): a late success would otherwise buy nothing. Returns
    whether anything changed.
    """
    changed = False
    queued = session.scalars(
        sa.select(Payment.id).where(
            Payment.subscription_id == sub.id,
            Payment.purpose == PaymentPurpose.extra_seats,
            Payment.dedupe_key.startswith(RENEWAL_SEAT_DEDUPE_PREFIX, autoescape=True),
            Payment.status == PaymentStatus.created,
        )
    ).all()
    for payment_id in queued:
        changed = fail_unsent(session, payment_id, reason="grace_ended") or changed
    unknown = session.scalar(
        sa.select(Payment.id)
        .where(
            Payment.subscription_id == sub.id,
            Payment.purpose == PaymentPurpose.extra_seats,
            Payment.dedupe_key.startswith(RENEWAL_SEAT_DEDUPE_PREFIX, autoescape=True),
            Payment.status.in_(IN_FLIGHT_STATUSES),
        )
        .limit(1)
    )
    if unknown is not None:
        log.info("extra_seats_drop_deferred", subscription_id=str(sub.id))
        until = sub.extra_seat_grace_until
        if until is not None and now >= until + DROP_STUCK_ALERT_AFTER:
            _alert_once(
                "extra_seats_drop_stuck",
                f"{sub.id}:{until.isoformat()}",
                subscription_id=str(sub.id),
                payment_id=str(unknown),
            )
        return changed
    _drop_extra_seats(session, sub, now=now)
    return True


def _supersede_after_paid(session: Session, sub: Subscription, attempts: list[Payment]) -> bool:
    """One attempt is paid: fail the queued ones unsent; alert when a second was paid too (R20b)."""
    paid = [a for a in attempts if a.status is PaymentStatus.paid]
    changed = False
    for attempt in attempts:
        if attempt.status is PaymentStatus.created:
            changed = fail_unsent(session, attempt.id, reason="superseded") or changed
    if len(paid) > 1:
        alerts.error(
            "extra_seat_charge_duplicate",
            alert=True,
            subscription_id=str(sub.id),
            payment_ids=[str(a.id) for a in paid],
        )
    return changed


def _grace_cap(session: Session, first: Payment, until: datetime) -> int:
    """Attempts one grace allows, frozen when it started.

    A grace ends at ``seen + grace_days`` and one attempt is allowed per day from the first send,
    so the cap is the days from that send to the deadline: ``grace_days`` when the failure was
    seen at once, more when the job was late to see it (the customer still gets the full grace
    to put it right). An admin changing ``grace_days`` mid-grace changes nothing for a grace
    already running. A first attempt that was never sent has no send time; the setting then
    applies as it is now (nothing was charged, so there is no burst to fear).
    """
    if first.sent_at is None:
        return seat_grace_days(session)
    return max(1, (until - first.sent_at) // timedelta(days=1))


def _after_failed_attempt(
    session: Session,
    sub: Subscription,
    period: SubscriptionPeriod,
    attempts: list[Payment],
    *,
    fallback: bool,
    now: datetime,
) -> bool:
    """The period has attempts and none is paid: start the grace, or retry once a day.

    An attempt whose outcome is unknown (``created``, ``pending``) blocks everything: only a
    definite failure starts a grace or allows another charge (spec section 6). A retry waits a
    full interval after the previous one was *sent* (so a missed day never causes a burst) and
    stops at the cap frozen when the grace started.
    """
    latest = attempts[-1]
    if latest.status not in FAILED_STATUSES:
        return False
    first = attempts[0]
    until = sub.extra_seat_grace_until
    if sub.extra_seat_grace_payment_id != first.id:
        if until is not None:
            return False  # another period's grace still holds the marker: it ends on its own
        days = seat_grace_days(session)
        sub.extra_seat_grace_until = now + timedelta(days=days)  # from when the failure is seen
        sub.extra_seat_grace_payment_id = first.id
        bump_version(sub)
        enqueue_extra_seats_charge_failed(
            session,
            payer_user_id=sub.payer_user_id or sub.user_id,
            subscription_id=sub.id,
            first_attempt_id=first.id,
            grace_days=days,
        )
        return True
    if (
        not fallback
        or sub.status is not SubscriptionStatus.active
        or until is None
        or until <= now
        or len(attempts) >= _grace_cap(session, first, until)
        or now < (latest.sent_at or latest.created_at) + SEAT_RETRY_INTERVAL
    ):
        return False
    plan = _ShortfallPlan(first.amount_minor, first.currency, first.seat_quantity)
    return _queue_attempt(session, sub, period, len(attempts) + 1, plan) is not None


def _process_seat_row(
    session: Session, subscription_id: uuid.UUID, *, fallback: bool, now: datetime
) -> bool:
    """One subscription, under ``FOR UPDATE SKIP LOCKED``: act, return whether anything changed."""
    sub = session.scalars(
        sa.select(Subscription)
        .where(Subscription.id == subscription_id)
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    ).one_or_none()
    if sub is None:
        return False
    if sub.extra_seat_grace_until is not None and sub.extra_seat_grace_until <= now:
        return _end_grace(session, sub, now=now)
    period = current_period(session, sub)
    if period is None:
        return False
    attempts = _period_attempts(session, sub, period)
    if any(a.status is PaymentStatus.paid for a in attempts):
        return _supersede_after_paid(session, sub, attempts)
    if not attempts:
        return fallback and queue_renewal_seat_charge(session, sub, period, now=now) is not None
    return _after_failed_attempt(session, sub, period, attempts, fallback=fallback, now=now)


def _seat_candidate_ids(
    session: Session, *, fallback: bool, now: datetime, limit: int
) -> list[uuid.UUID]:
    """Up to ``limit`` subscriptions the job has work on right now, the longest-due first (DV-23).

    A subscription in a grace is due at the earlier of its deadline and one interval after its
    latest send (a retry): until then it is not visited and takes no place in the batch. A
    subscription with a queued attempt is always visited. On the fallback path a qualifying
    subscription is visited when the exact shortfall (billed terms, paid in-period purchases
    taken off) is above zero and it has no paid attempt and not only in-flight ones. A period
    whose terms are unknown owes nothing and is never a candidate (it alerts through
    :func:`_alert_unknown_terms`). Rows with nothing to do are left out, and the order is
    by due time, so they can neither fill the batch nor starve a drop or a retry.
    """
    renewal = aliased(Payment)
    terms = aliased(PlanTierTerms)
    attempt_key = sa.func.concat(RENEWAL_SEAT_DEDUPE_PREFIX, SubscriptionPeriod.id, ":%")

    def attempts_where() -> list[sa.ColumnElement[bool]]:
        return [
            Payment.subscription_id == Subscription.id,
            Payment.purpose == PaymentPurpose.extra_seats,
            Payment.dedupe_key.like(attempt_key),
        ]

    def has_attempt(*statuses: PaymentStatus) -> sa.ColumnElement[bool]:
        stmt = sa.exists().where(*attempts_where())
        if statuses:
            stmt = stmt.where(Payment.status.in_(statuses))
        return stmt

    last_sent = (
        sa.select(sa.func.max(sa.func.coalesce(Payment.sent_at, Payment.created_at)))
        .where(*attempts_where())
        .scalar_subquery()
    )
    bought = (
        sa.select(sa.func.coalesce(sa.func.sum(Payment.seat_quantity), 0))
        .where(
            Payment.subscription_id == Subscription.id,
            Payment.purpose == PaymentPurpose.extra_seats,
            Payment.dedupe_key.is_(None),
            Payment.status == PaymentStatus.paid,
            Payment.applied_at.is_not(None),
            Payment.created_at >= SubscriptionPeriod.period_start,
        )
        .scalar_subquery()
    )
    retry_due = last_sent + sa.literal(SEAT_RETRY_INTERVAL, sa.Interval())
    grace_due = sa.func.least(
        Subscription.extra_seat_grace_until,
        sa.func.coalesce(retry_due, Subscription.extra_seat_grace_until),
    )
    in_grace = Subscription.extra_seat_grace_until.is_not(None)
    queued = has_attempt(PaymentStatus.created)
    wanted = [queued]
    if fallback:
        terms_unknown = sa.and_(
            SubscriptionPeriod.terms_version.is_(None),
            renewal.plan_tier_id != Subscription.plan_tier_id,
        )
        seat = terms.extra_seat_price_minor
        gap = (
            terms.price_minor
            + Subscription.extra_seats * seat
            - renewal.amount_minor
            - bought * seat
        )
        wanted.append(
            sa.and_(
                Subscription.status == SubscriptionStatus.active,
                Subscription.paymob_subscription_id.is_not(None),
                Subscription.extra_seats > 0,
                PlanTier.audience == PlanAudience.teacher,
                renewal.purpose == PaymentPurpose.subscription_renewal,
                renewal.status == PaymentStatus.paid,
                ~terms_unknown,
                seat > 0,
                sa.func.least(Subscription.extra_seats * seat, gap) > 0,
                sa.or_(~has_attempt(PaymentStatus.paid), queued),
                sa.or_(~has_attempt(), has_attempt(*FAILED_STATUSES), queued),
            )
        )
    due = sa.case((in_grace, grace_due), else_=Subscription.current_period_start)
    return list(
        session.scalars(
            sa.select(Subscription.id)
            .join(PlanTier, PlanTier.id == Subscription.plan_tier_id)
            .outerjoin(
                SubscriptionPeriod,
                sa.and_(
                    SubscriptionPeriod.subscription_id == Subscription.id,
                    SubscriptionPeriod.period_end == Subscription.current_period_end,
                ),
            )
            .outerjoin(renewal, renewal.id == SubscriptionPeriod.payment_id)
            .outerjoin(
                terms,
                sa.and_(
                    terms.plan_tier_id
                    == sa.func.coalesce(renewal.plan_tier_id, Subscription.plan_tier_id),
                    terms.terms_version
                    == sa.func.coalesce(
                        SubscriptionPeriod.terms_version, Subscription.terms_version
                    ),
                ),
            )
            .where(sa.or_(sa.and_(in_grace, grace_due <= now), sa.and_(~in_grace, sa.or_(*wanted))))
            .order_by(due, Subscription.id)
            .limit(limit)
        )
    )


def _alert_unknown_terms(session: Session, *, limit: int) -> None:
    """Alert, once per period, for qualifying periods whose billed terms cannot be known.

    Such a period owes nothing (:func:`renewal_seat_shortfall`), so it is not a candidate and
    holds no place in the batch; this read-only pass is the only place that looks at it.
    """
    renewal = aliased(Payment)
    rows = session.execute(
        sa.select(Subscription.id, SubscriptionPeriod.id)
        .join(PlanTier, PlanTier.id == Subscription.plan_tier_id)
        .join(
            SubscriptionPeriod,
            sa.and_(
                SubscriptionPeriod.subscription_id == Subscription.id,
                SubscriptionPeriod.period_end == Subscription.current_period_end,
            ),
        )
        .join(renewal, renewal.id == SubscriptionPeriod.payment_id)
        .where(
            Subscription.status == SubscriptionStatus.active,
            Subscription.paymob_subscription_id.is_not(None),
            Subscription.extra_seats > 0,
            PlanTier.audience == PlanAudience.teacher,
            renewal.purpose == PaymentPurpose.subscription_renewal,
            renewal.status == PaymentStatus.paid,
            SubscriptionPeriod.terms_version.is_(None),
            renewal.plan_tier_id != Subscription.plan_tier_id,
        )
        .order_by(SubscriptionPeriod.period_start, Subscription.id)
        .limit(limit)
    ).all()
    for subscription_id, period_id in rows:
        _alert_once(
            "extra_seat_terms_unknown",
            str(period_id),
            subscription_id=str(subscription_id),
            period_id=str(period_id),
        )


def _seat_row_one(
    sessionmaker: sessionmaker[Session],
    subscription_id: uuid.UUID,
    *,
    fallback: bool,
    now: datetime,
) -> bool:
    """Run one row in its own transaction; a failure rolls back that row alone and is alerted."""
    with sessionmaker() as session:
        try:
            changed = _process_seat_row(session, subscription_id, fallback=fallback, now=now)
            session.commit()
        except Exception as exc:
            session.rollback()
            alerts.error(
                "merchant_charge_sweep_failed",
                alert=True,
                subscription_id=str(subscription_id),
                error_type=type(exc).__name__,
            )
            return False
        return changed


def run_extra_seat_renewal_job(
    sessionmaker: sessionmaker[Session],
    client: PaymobClient,
    settings: PaymobSettings,
    *,
    now: datetime,
    limit: int = MERCHANT_SWEEP_BATCH,
) -> int:
    """Charge the seats a fixed-amount renewal left unpaid, with a grace and a drop; the count.

    Only when Paymob cannot take an amount change (``subscription_amount_updatable`` false) does
    the job queue anything: otherwise the user's own charge or the amount push covers the seats
    (DV-3). With the flag true it still finishes what exists (a grace that ends drops its seats,
    a paid attempt supersedes a queued one). A missing ``billing_settings`` row fails the whole
    run with one alert. Up to ``limit`` subscriptions that are due are visited, each in its own
    transaction under ``FOR UPDATE SKIP LOCKED`` (a row another worker holds is left to it, a
    failing row is rolled back and alerted alone), and then the queued attempts are charged to
    the payer's active card over MOTO. Returns the rows changed plus the attempts handled.
    """
    fallback = not settings.subscription_amount_updatable
    with sessionmaker() as session:
        try:
            seat_grace_days(session)
        except SeatGraceSettingMissing:
            return 0
        candidates = _seat_candidate_ids(session, fallback=fallback, now=now, limit=limit)
        if fallback:
            _alert_unknown_terms(session, limit=limit)
    handled = sum(
        _seat_row_one(sessionmaker, subscription_id, fallback=fallback, now=now)
        for subscription_id in candidates
    )

    def active_card(session: Session, payment: Payment) -> SavedCard | None:
        return MerchantChargeService(session, client, settings).active_card(payment.payer_user_id)

    return handled + charge_queued_payments(
        sessionmaker,
        client,
        settings,
        purpose=PaymentPurpose.extra_seats,
        dedupe_prefix=RENEWAL_SEAT_DEDUPE_PREFIX,
        card_for=active_card,
        now=now,
        limit=limit,
    )


__all__ = [
    "CARD_MOTO_METHOD",
    "FAILED_STATUSES",
    "IN_FLIGHT_STATUSES",
    "MAX_SEATS_PER_PURCHASE",
    "MAX_SWEEP_ERRORS",
    "MERCHANT_SWEEP_BATCH",
    "RENEWAL_SEAT_DEDUPE_PREFIX",
    "SEATS_ITEM_NAME",
    "SEAT_RETRY_INTERVAL",
    "UPGRADE_ITEM_NAME",
    "ChargeAlreadyAttempted",
    "ChargeQuote",
    "ChargesUnavailable",
    "MerchantChargeError",
    "MerchantChargeService",
    "SeatCeilingSettingMissing",
    "SeatGraceSettingMissing",
    "SeatsExceedNewTier",
    "SeatsNotSold",
    "active_seat_count",
    "bump_version",
    "charge_queued_payments",
    "charges_configured",
    "credit_void_payment",
    "current_period",
    "current_terms",
    "fail_unsent",
    "handle_extra_seats_paid",
    "handle_upgrade_paid",
    "insert_queued_payment",
    "is_upgrade",
    "lock_subscription",
    "offered_card_tokens",
    "on_extra_seats_paid",
    "on_upgrade_paid",
    "payable_subscription",
    "push_renewal_amount",
    "queue_amount_push",
    "queue_renewal_seat_charge",
    "refuse_if_charge_pending",
    "register_amount_pusher",
    "renewal_seat_shortfall",
    "run_extra_seat_renewal_job",
    "seat_ceiling",
    "seat_grace_days",
    "seats_void_reason",
    "start_present_checkout",
    "upgrade_void_reason",
    "usable_extra_seats",
]
