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

Logs carry payment ids, status codes and flags only: never the card token (plain or encrypted),
the payment key, the intention client secret, billing data or a response body.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Final

import sqlalchemy as sa
import structlog
from sqlalchemy.dialects.postgresql import insert as pg_insert

from lemely.db.billing_repo import (
    INTENTION_EXPIRATION_SECONDS,
    RECONCILE_AFTER,
    WEBHOOK_PATH,
    BillingError,
    BillingService,
    PhoneRequired,
    _as_int,
    _outcome_unknown,
    billing_data_for,
    saved_cards_for,
)
from lemely.db.models import User
from lemely.db.models.billing import Payment, PaymentPurpose, PaymentStatus, SavedCard
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
    """A merchant charge was refused before any write; ``code`` is the machine-readable reason."""

    def __init__(self, code: str, message: str | None = None) -> None:
        super().__init__(message or code)
        self.code = code


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


__all__ = [
    "CARD_MOTO_METHOD",
    "FAILED_STATUSES",
    "IN_FLIGHT_STATUSES",
    "MAX_SWEEP_ERRORS",
    "MERCHANT_SWEEP_BATCH",
    "ChargeAlreadyAttempted",
    "ChargesUnavailable",
    "MerchantChargeError",
    "MerchantChargeService",
    "charge_queued_payments",
    "charges_configured",
    "fail_unsent",
    "insert_queued_payment",
]
