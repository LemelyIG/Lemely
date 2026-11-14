"""Billing service: payments, Paymob callbacks and paid handlers (billing spec §3-§6).

The only module that joins Paymob to the usage ledger. ``PaymobClient`` knows
nothing about credits and ``UsageLedger`` knows nothing about Paymob; a payment
verified here is handed to the handler registered for its purpose, which
issues the grant.

**Transactions.** Read methods and the callback appliers never commit: the
webhook route owns one ``sessionmaker.begin()`` transaction and answers 200 only
after it commits (spec §6). Two methods commit on purpose:
``create_intention_checkout`` commits the payment row *before* calling Paymob
(Paymob has no idempotency keys; our row must exist first) and again after;
``reconcile_pending`` commits after each payment it settles.

**Paid handlers.** Each purpose registers exactly one handler at import time
(``register_paid_handler``). Phase 02 registers ``credit_pack``; Phases 05 and 06
register the subscription and merchant-charge purposes from their own modules.
A paid payment whose purpose has no handler raises, which rolls the webhook
transaction back so Paymob retries and reconciliation tries again.
"""

from __future__ import annotations

import calendar
import re
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import urlencode

import psycopg
import structlog
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import OperationalError

from lemely.core.phone import InvalidPhone, validate_phone
from lemely.db.models import ParentChildLink, User
from lemely.db.models.billing import (
    CreditPack,
    Payment,
    PaymentPurpose,
    PaymentStatus,
    PaymobEvent,
    PaymobEventKind,
    PlanAudience,
    PlanTier,
    SavedCard,
)
from lemely.db.models.billing_ops import BillingSettings
from lemely.db.models.enums import Role
from lemely.db.models.usage import GrantKind
from lemely.db.usage_ledger_repo import UsageLedger
from lemely.io.paymob.client import PaymobError
from lemely.runtime.token_cipher import TokenCipher

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from lemely.io.paymob.client import PaymobClient
    from lemely.runtime.config import PaymobSettings

log = structlog.get_logger(__name__)

INTENTION_EXPIRATION_SECONDS: Final = 3600
#: Saved cards one intention may offer (live ``pay-with-saved-cards/cit.md``).
MAX_CARD_TOKENS: Final = 3
RECONCILE_AFTER: Final = timedelta(minutes=15)
RECONCILE_GIVE_UP_AFTER: Final = timedelta(hours=24)
RECONCILE_MAX_BACKOFF: Final = timedelta(hours=4)
#: A payment still open this long after it was created, whose inquiries keep erroring or
#: coming back unreadable, stops being polled (its status stays open: R20b).
RECONCILE_STUCK_AFTER: Final = timedelta(days=7)
RECONCILE_BATCH: Final = 20
# Past 2**10 the doubling is far beyond the cap; clamping the exponent keeps ``timedelta``
# multiplication from overflowing on a payment that has been rescheduled for years.
_MAX_BACKOFF_EXPONENT: Final = 10
WEBHOOK_PATH: Final = "/api/webhooks/paymob/transaction"
#: The SPA route is ``/billing/return/:paymentId`` (``web/src/routes.tsx``). The id rides in the
#: path, not a query: Paymob appends its own ``?id=...&hmac=...`` to ``redirection_url`` and the
#: docs do not say how it joins a URL that already has a ``?`` (skill audit C1, DV-28).
RETURN_PATH: Final = "/billing/return"

_OPEN: Final = (PaymentStatus.created, PaymentStatus.pending)
_SETTLED: Final = (PaymentStatus.paid, PaymentStatus.partially_refunded, PaymentStatus.refunded)
_REDACTED: Final = "[redacted]"
# Refund progress only moves forward: an out-of-order callback never downgrades it.
_REFUND_RANK: Final = {
    PaymentStatus.paid: 0,
    PaymentStatus.partially_refunded: 1,
    PaymentStatus.refunded: 2,
}

#: A decoded Paymob JSON object (callback ``obj``, intention item or billing data).
JsonMap = Mapping[str, Any]  # type: ignore[explicit-any]

_PURPOSE_LABELS: Final[Mapping[PaymentPurpose, str]] = {
    PaymentPurpose.subscription_first: "Subscription",
    PaymentPurpose.subscription_renewal: "Subscription renewal",
    PaymentPurpose.upgrade_proration: "Plan upgrade",
    PaymentPurpose.extra_seats: "Extra student seats",
    PaymentPurpose.credit_pack: "Credit pack",
    PaymentPurpose.auto_topup: "Credit auto top-up",
}


# ---------------------------------------------------------------------------
# Errors and results.
# ---------------------------------------------------------------------------


class BillingError(Exception):
    """Base class for billing failures a route maps to an HTTP status."""


class CheckoutUnavailable(BillingError):
    """Paymob is not configured or did not create the intention (503)."""


class UnknownCreditPack(BillingError):
    """No active credit pack with that id (404)."""


class NotLinkedToBeneficiary(BillingError):
    """The payer may not buy for this beneficiary (403).

    A parent buys only for a student they are linked to through ``parent_child_links``,
    never for themselves; nobody else buys for another user.
    """


class PhoneRequired(BillingError):
    """The payer has no valid phone on file, and Paymob requires one (422 ``phone_required``)."""


class UnknownPayer(BillingError):
    """The payer has no ``users`` row, e.g. a valid token for a deleted account (403)."""


class MalformedCallback(BillingError):
    """A verified callback lacks a field we need (400)."""


class PaymentNotFoundError(BillingError):
    """No payment has that id."""


class PaymentBusyError(BillingError):
    """Another transaction holds the payment's row lock (a sweeper pass, a callback, a click).

    The admin route maps it to 409. The caller's transaction is aborted and must roll back.
    """


class CreditValiditySettingMissing(BillingError):
    """``billing_settings`` has no ``id = 1`` row, so a credit pack's validity is unknown."""


@dataclass(frozen=True, slots=True)
class CheckoutResult:
    payment_id: uuid.UUID
    checkout_url: str


# ---------------------------------------------------------------------------
# Paid-handler registry.
# ---------------------------------------------------------------------------

PaidHandler = Callable[["Session", Payment, JsonMap], None]
_PAID_HANDLERS: dict[PaymentPurpose, PaidHandler] = {}


def register_paid_handler(purpose: PaymentPurpose, handler: PaidHandler) -> None:
    """Register the one handler a verified payment of ``purpose`` is passed to."""
    existing = _PAID_HANDLERS.get(purpose)
    if existing is not None and existing is not handler:
        raise ValueError(f"a paid handler is already registered for {purpose.value}")
    _PAID_HANDLERS[purpose] = handler


def paid_handler_for(purpose: PaymentPurpose) -> PaidHandler | None:
    return _PAID_HANDLERS.get(purpose)


# ---------------------------------------------------------------------------
# Pure helpers.
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(UTC)


def add_months(moment: datetime, months: int) -> datetime:
    """``moment`` plus ``months`` calendar months, clamped to the month's last day."""
    index = moment.month - 1 + months
    year = moment.year + index // 12
    month = index % 12 + 1
    day = min(moment.day, calendar.monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)


def payer_phone(user: User) -> str:
    """The payer's phone in E.164, or :class:`PhoneRequired` when none usable is on file.

    UD-11: every user gives a phone at sign-up or onboarding, and ``billing_data.phone_number``
    is required by Paymob (a missing one is a 400). A user who has none, or whose stored value
    does not validate (an older free-text entry), is asked for one; **no placeholder is ever
    sent**. The check is :func:`lemely.core.phone.validate_phone`, the same one sign-up uses.
    """
    try:
        return validate_phone(user.phone)
    except InvalidPhone as exc:
        raise PhoneRequired(str(user.id)) from exc


def billing_data_for(user: User) -> dict[str, str]:
    """Paymob ``billing_data`` from the payer's profile (research 01 §2.1).

    First name, last name, email and phone are required by Paymob; address
    fields are not collected by Lemely and are sent as ``"NA"``, as Paymob's own
    samples send placeholders. The phone is the payer's own, in E.164 (see
    :func:`payer_phone`); a payer without one raises :class:`PhoneRequired`.
    """
    first, _, last = (user.display_name or "").strip().partition(" ")
    return {
        "first_name": (first or "Lemely")[:50],
        "last_name": (last.strip() or "Customer")[:50],
        "email": user.email,
        "phone_number": payer_phone(user),
        "apartment": "NA",
        "floor": "NA",
        "street": "NA",
        "building": "NA",
        "city": "NA",
        "state": "NA",
        "country": "EGY",
    }


def _outcome_unknown(exc: PaymobError) -> bool:
    """True when Paymob may have applied the call: never read this as a decline.

    The client's own ``outcome_unknown`` flag is authoritative: it is set when no
    usable answer came back, and cleared for ``PaymobNotConfigured`` (raised
    before anything was sent, so nothing happened). Beyond that, only a received
    4xx is a definite rejection: a 5xx (a gateway error does not say whether the
    order was created) or a 2xx we could not use is unknown even where the client
    did not flag it.
    """
    if exc.outcome_unknown:
        return True
    return exc.status_code is not None and not 400 <= exc.status_code < 500


def _reconcile_clock(payment: Payment) -> datetime:
    """When reconcile's give-up and stuck windows start counting for ``payment``.

    A checkout starts them at ``created_at`` (its intention goes out in the same breath). A queued
    charge can wait before it is sent, so it starts them when it was sent (``sent_at``): counted
    from ``created_at``, a row queued over a day ago would be failed on the first reconcile pass
    after a real charge, which a seat or top-up sweep reads as "not charged" (a double charge).
    """
    return payment.sent_at or payment.created_at


def _as_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _is_true(value: object) -> bool:
    return value is True or value == "true"


def _flag(value: object) -> str:
    return "1" if _is_true(value) else "0"


def transaction_dedupe_key(obj: JsonMap) -> str:
    """Transaction id plus the state flags (spec §4.2): a new state is a new event.

    Built from HMAC-signed fields only (``id``, ``success``, ``pending``, ``is_voided``,
    ``is_refunded``). A key that held an unsigned field (``refunded_amount_cents``)
    would let a replayed signature mint fresh keys at will. The refunded total is
    state, not identity: see ``_apply_transaction``.
    """
    return (
        f"txn:{obj.get('id')}:s{_flag(obj.get('success'))}p{_flag(obj.get('pending'))}"
        f"v{_flag(obj.get('is_voided'))}r{_flag(obj.get('is_refunded'))}"
    )


# Shapes of a genuine TOKEN callback's fields (research 02 §2.2). The HMAC cannot vouch for
# them: ``type`` is unsigned and Paymob joins the signed values with no separator, so a
# transaction callback's signature can be re-split into a TOKEN body whose every slot
# holds attacker-chosen text. A transaction's signed string begins with ``amount_cents``
# (digits), so a real brand name (letters first) and an ISO ``created_at`` cannot both
# appear in the slots they would have to occupy.
_CARD_TOKEN_RE: Final = re.compile(r"[A-Za-z0-9_.:+/=~-]{8,512}")
_MASKED_PAN_RE: Final = re.compile(r"[\dXx* -]{8,23}")
_CARD_SUBTYPE_RE: Final = re.compile(r"[A-Za-z][A-Za-z ]{1,19}")


def _validate_token_callback(obj: JsonMap) -> tuple[int, str]:
    """The ``(token id, token)`` of a well-formed TOKEN ``obj``, else ``MalformedCallback``.

    The messages name the field, never the value: they reach logs and the 400 body.
    """
    token_id = _as_int(obj.get("id"))
    if token_id is None:
        raise MalformedCallback("token callback has no integer id")
    if _as_int(obj.get("order_id")) is None:
        raise MalformedCallback("token callback has no integer order_id")
    token = obj.get("token")
    if not isinstance(token, str) or _CARD_TOKEN_RE.fullmatch(token) is None:
        raise MalformedCallback("token callback has a malformed token")
    masked_pan = obj.get("masked_pan")
    if not isinstance(masked_pan, str) or _MASKED_PAN_RE.fullmatch(masked_pan) is None:
        raise MalformedCallback("token callback has a malformed masked_pan")
    subtype = obj.get("card_subtype")
    if not isinstance(subtype, str) or _CARD_SUBTYPE_RE.fullmatch(subtype) is None:
        raise MalformedCallback("token callback has a malformed card_subtype")
    created_at = obj.get("created_at")
    try:
        if not isinstance(created_at, str) or not created_at:
            raise ValueError("created_at is not a string")
        datetime.fromisoformat(created_at)
    except ValueError as exc:
        raise MalformedCallback("token callback has a malformed created_at") from exc
    return token_id, token


def _is_token_key(key: object) -> bool:
    """Any key that may carry a card token: ``token``, ``card_token``, ``card_tokens``, ..."""
    return isinstance(key, str) and "token" in key.lower()


def _redact_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            key: _REDACTED if _is_token_key(key) and item is not None else _redact_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact_value(item) for item in value]
    return value


def _redact_tokens(obj: JsonMap) -> dict[str, object]:
    """A deep copy of ``obj`` with every raw card token replaced (spec §7).

    Stored payloads (``paymob_events.payload``, ``payments.last_callback``) are
    readable by support and admin tools; the token is a credential that can charge
    the card, so it never reaches them, whichever callback it arrives in.
    """
    return {
        key: _REDACTED if _is_token_key(key) and item is not None else _redact_value(item)
        for key, item in obj.items()
    }


# ---------------------------------------------------------------------------
# Paid handler: credit packs (spec §5.5).
# ---------------------------------------------------------------------------


def _credit_validity_months(session: Session, payment_id: uuid.UUID) -> int:
    """The admin-set credit validity: ``billing_settings.credit_validity_months`` (``id = 1``).

    Read in the caller's transaction, no lock. Fails closed: a missing row (the migration and
    ``create_all`` both insert it, so its absence is a damaged database) raises
    :class:`CreditValiditySettingMissing`, and no constant stands in for it. The paid handler
    then fails, the callback rolls back and answers 5xx, and Paymob retries.
    """
    months = session.scalar(
        select(BillingSettings.credit_validity_months).where(BillingSettings.id == 1)
    )
    if months is None:
        # A paid customer is left without credits and every retry fails the same way, so a
        # person must restore the row: an alert, with the payment to re-run.
        log.error("credit_validity_setting_missing", alert=True, payment_id=str(payment_id))
        raise CreditValiditySettingMissing("no billing settings row: credit validity is not set")
    return months


def grant_credit_pack(session: Session, payment: Payment, obj: JsonMap) -> None:
    """Issue the beneficiary's visible credit grant, expiring after the admin-set validity.

    The validity is read now, so an edited setting changes packs paid from then on and
    never a grant already issued.
    """
    if payment.grant_units is None:
        raise RuntimeError(f"credit pack payment {payment.id} has no grant_units snapshot")
    # ``paid_at`` is set from the service's injected clock before any handler runs;
    # a wall-clock fallback here would make the expiry and a replay disagree.
    paid_at = payment.paid_at
    if paid_at is None:
        raise RuntimeError(f"credit pack payment {payment.id} has no paid_at")
    UsageLedger(session).issue_grant(
        owner_user_id=payment.beneficiary_user_id,
        kind=GrantKind.credit_pack,
        units=payment.grant_units,
        idempotency_key=f"payment:{payment.id}",
        expires_at=add_months(paid_at, _credit_validity_months(session, payment.id)),
        visible=True,
        effective_at=paid_at,
        payment_id=payment.id,
    )


register_paid_handler(PaymentPurpose.credit_pack, grant_credit_pack)


# ---------------------------------------------------------------------------
# Read queries used by the billing router.
# ---------------------------------------------------------------------------


def is_linked_parent(session: Session, parent_id: uuid.UUID, child_id: uuid.UUID) -> bool:
    """True when ``parent_child_links`` links the two (spec §2.1, §7)."""
    return (
        session.scalar(
            select(ParentChildLink.id).where(
                ParentChildLink.parent_id == parent_id, ParentChildLink.child_id == child_id
            )
        )
        is not None
    )


def active_catalogue(
    session: Session, *, audience: PlanAudience, sellable_tiers_only: bool = False
) -> tuple[list[PlanTier], list[CreditPack]]:
    """Active tiers of ``audience`` and every sellable pack.

    ``sellable_tiers_only`` also drops tiers with no billing interval (rows nobody can
    subscribe to); the public pricing page sets it.
    """
    tier_query = select(PlanTier).where(PlanTier.is_active.is_(True), PlanTier.audience == audience)
    if sellable_tiers_only:
        tier_query = tier_query.where(PlanTier.interval.is_not(None))
    tiers = session.scalars(tier_query.order_by(PlanTier.price_minor, PlanTier.code)).all()
    packs = session.scalars(
        select(CreditPack)
        .where(
            CreditPack.is_active.is_(True),
            CreditPack.price_minor > 0,
            CreditPack.units > 0,
        )
        .order_by(CreditPack.price_minor, CreditPack.code)
    ).all()
    return list(tiers), list(packs)


def payment_for_viewer(
    session: Session, *, payment_id: uuid.UUID, user_id: uuid.UUID
) -> Payment | None:
    """The payment if ``user_id`` is its payer or beneficiary, else ``None`` (no oracle)."""
    payment = session.get(Payment, payment_id)
    if payment is None or user_id not in (payment.payer_user_id, payment.beneficiary_user_id):
        return None
    return payment


def receipts_for(session: Session, payer_user_id: uuid.UUID) -> list[Payment]:
    """Every payment this user paid for, newest first: the receipts (spec §2.5)."""
    return list(
        session.scalars(
            select(Payment)
            .where(Payment.payer_user_id == payer_user_id, Payment.paid_at.is_not(None))
            .order_by(Payment.paid_at.desc(), Payment.id)
        ).all()
    )


def saved_cards_for(session: Session, user_id: uuid.UUID) -> list[SavedCard]:
    """The user's own active saved cards, newest first (index R3; masked fields only leave)."""
    return list(
        session.scalars(
            select(SavedCard)
            .where(SavedCard.user_id == user_id, SavedCard.is_active.is_(True))
            .order_by(SavedCard.created_at.desc(), SavedCard.id)
        ).all()
    )


def describe_payment(session: Session, payment: Payment) -> str:
    if payment.purpose is PaymentPurpose.credit_pack and payment.credit_pack_id is not None:
        pack = session.get(CreditPack, payment.credit_pack_id)
        if pack is not None:
            return pack.name
    return _PURPOSE_LABELS[payment.purpose]


# ---------------------------------------------------------------------------
# The service.
# ---------------------------------------------------------------------------


class BillingService:
    """Payments and Paymob callbacks over one SQLAlchemy session."""

    def __init__(
        self,
        session: Session,
        client: PaymobClient,
        settings: PaymobSettings,
        *,
        cipher: TokenCipher | None = None,
        now: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._session = session
        self._client = client
        self._settings = settings
        self._cipher = cipher
        self._now = now

    @property
    def cipher(self) -> TokenCipher | None:
        """The saved-card token cipher, or ``None`` when no ``card_token_key`` is set.

        Built on first use, not at construction: a malformed ``card_token_key``
        must fail loudly where the cipher is needed (saving a card), not break
        every checkout and webhook that never touches it. Raises
        ``TokenCipherError`` on a malformed key.
        """
        if self._cipher is None and self._settings.card_token_key is not None:
            self._cipher = TokenCipher(self._settings.card_token_key.get_secret_value())
        return self._cipher

    # -- checkout -------------------------------------------------------------

    @property
    def notification_url(self) -> str:
        return f"{self._settings.notification_base_url}{WEBHOOK_PATH}"

    def redirection_url(self, payment_id: uuid.UUID) -> str:
        return f"{self._settings.redirection_base_url}{RETURN_PATH}/{payment_id}"

    def create_pack_checkout(
        self,
        *,
        payer_user_id: uuid.UUID,
        beneficiary_user_id: uuid.UUID,
        credit_pack_id: uuid.UUID,
    ) -> CheckoutResult:
        """Price a pack on the server, insert the payment, create the intention (§5.5).

        The price and unit count come from the ``credit_packs`` row, never from
        the caller. A parent buys only for a linked student, never for themselves
        (``NotLinkedToBeneficiary``); no one else buys for another user. A payer with no valid
        phone is refused (``PhoneRequired``) before anything is written.
        """
        if not self._settings.checkout_configured:
            raise CheckoutUnavailable("Paymob checkout is not configured")
        pack = self._session.get(CreditPack, credit_pack_id)
        if pack is None or not pack.is_active or pack.price_minor <= 0 or pack.units <= 0:
            # Inactive signup-allowance rows (Phase 04) and zero-value packs are never sold.
            raise UnknownCreditPack(str(credit_pack_id))
        payer = self._session.get(User, payer_user_id)
        if payer is None:
            raise UnknownPayer(str(payer_user_id))
        if (
            payer.role is Role.parent or payer_user_id != beneficiary_user_id
        ) and not self._may_buy_for(payer_user_id, beneficiary_user_id):
            raise NotLinkedToBeneficiary(str(beneficiary_user_id))
        billing_data = billing_data_for(payer)  # PhoneRequired before any row is written
        payment_id = uuid.uuid4()
        payment = Payment(
            id=payment_id,
            payer_user_id=payer_user_id,
            beneficiary_user_id=beneficiary_user_id,
            purpose=PaymentPurpose.credit_pack,
            credit_pack_id=pack.id,
            grant_units=pack.units,
            amount_minor=pack.price_minor,
            currency=pack.currency,
            status=PaymentStatus.created,
            special_reference=str(payment_id),
        )
        items = [
            {
                "name": pack.name[:50],
                "amount": pack.price_minor,
                "description": f"{pack.units} Lemely credits"[:255],
                "quantity": 1,
            }
        ]
        return self.create_intention_checkout(
            payment=payment,
            items=items,
            billing_data=billing_data,
            subscription_plan_id=None,
        )

    def _may_buy_for(self, payer_user_id: uuid.UUID, beneficiary_user_id: uuid.UUID) -> bool:
        """True when ``payer`` is linked to ``beneficiary`` and the beneficiary is a student.

        Applies to every parent (even naming their own id, which is never linked) and to
        any payer naming someone else. ``is_linked_parent`` ignores roles, so a link row
        that points at a teacher or another parent is refused here.
        """
        if not is_linked_parent(self._session, payer_user_id, beneficiary_user_id):
            return False
        beneficiary = self._session.get(User, beneficiary_user_id)
        return beneficiary is not None and beneficiary.role is Role.student

    def create_intention_checkout(
        self,
        *,
        payment: Payment,
        items: Sequence[JsonMap],
        billing_data: JsonMap,
        subscription_plan_id: int | None,
        card_tokens: Sequence[str] = (),
    ) -> CheckoutResult:
        """Commit ``payment``, create its Paymob intention, return the checkout URL.

        Shared with Phase 05 (subscriptions pass ``subscription_plan_id``) and Phase 06
        (upgrades and seat purchases pass the payer's decrypted saved-card ``card_tokens``,
        at most :data:`MAX_CARD_TOKENS`: Unified Checkout then offers those cards, and 3DS
        still runs on the unchanged card integration). The tokens are secrets: they go only
        into the intention body and the client's ``sensitive`` scrub list, never a log, the
        payment row or an exception. The call is never retried. ``CheckoutUnavailable`` is
        raised on every failure, but the payment's fate depends on what Paymob may have done:

        * A definite rejection (a received non-5xx error status), or a 2xx with no
          client secret: nothing can be paid, so the payment is marked ``failed``.
        * An unknown outcome (no usable answer, ``outcome_unknown``, or a 5xx):
          Paymob may have created the order and the customer may even pay it, so
          the payment stays ``created`` with its ``next_reconcile_at`` and the
          reconcile job settles it by inquiry. It is never marked ``failed`` here.
        """
        if len(card_tokens) > MAX_CARD_TOKENS:
            raise ValueError(f"at most {MAX_CARD_TOKENS} saved cards can be offered at checkout")
        if not self._settings.checkout_configured:
            raise CheckoutUnavailable("Paymob checkout is not configured")
        for item in items:
            if "quantity" in item and not (type(item["quantity"]) is int and item["quantity"] == 1):
                # Whether Paymob's item ``amount`` is per unit or a line total is unconfirmed;
                # fail closed rather than send a total it may reject or misprice.
                raise ValueError("checkout items must have quantity 1")
        item_total = sum(_as_int(item.get("amount")) or 0 for item in items)
        if item_total != payment.amount_minor:
            # Paymob rejects a mismatch, and a mismatched row would sit open until reconciled.
            raise ValueError(
                f"checkout items add up to {item_total}, "
                f"not the payment amount {payment.amount_minor}"
            )
        if payment.next_reconcile_at is None:
            payment.next_reconcile_at = self._now() + RECONCILE_AFTER
        self._session.add(payment)
        self._session.commit()

        assert self._settings.card_integration_id is not None  # checkout_configured  # noqa: S101
        body: dict[str, object] = {
            "amount": payment.amount_minor,
            "currency": payment.currency,
            "payment_methods": [self._settings.card_integration_id],
            "items": [dict(item) for item in items],
            "billing_data": dict(billing_data),
            "special_reference": payment.special_reference,
            "expiration": INTENTION_EXPIRATION_SECONDS,
            "notification_url": self.notification_url,
            "redirection_url": self.redirection_url(payment.id),
            "extras": {"payment_id": str(payment.id), "purpose": payment.purpose.value},
        }
        if subscription_plan_id is not None:
            body["subscription_plan_id"] = subscription_plan_id
        try:
            if card_tokens:
                body["card_tokens"] = list(card_tokens)
                response = self._client.create_intention(body, sensitive=tuple(card_tokens))
            else:
                response = self._client.create_intention(body)
        except PaymobError as exc:
            unknown = _outcome_unknown(exc)
            if unknown:
                self._note_unknown_checkout(payment, str(exc), exc.status_code)
            else:
                self._fail_checkout(payment, str(exc), exc.status_code)
            log.warning(
                "paymob_intention_failed",
                payment_id=str(payment.id),
                status_code=exc.status_code,
                timeout=exc.timeout,
                outcome_unknown=unknown,
            )
            raise CheckoutUnavailable("Paymob is unavailable") from exc
        # Paymob created an order even when the response is unusable: keep its ids
        # on the row so support and reconciliation can find it.
        intention_id = response.get("id")
        payment.paymob_intention_id = str(intention_id) if intention_id else None
        payment.paymob_order_id = _as_int(response.get("intention_order_id"))
        client_secret = response.get("client_secret")
        if not isinstance(client_secret, str) or not client_secret:
            self._fail_checkout(payment, "intention response had no client_secret", None)
            log.warning("paymob_intention_without_secret", payment_id=str(payment.id))
            raise CheckoutUnavailable("Paymob returned no client secret")
        self._session.commit()
        query = urlencode(
            {"publicKey": self._settings.public_key or "", "clientSecret": client_secret}
        )
        log.info(
            "paymob_checkout_created", payment_id=str(payment.id), purpose=payment.purpose.value
        )
        return CheckoutResult(
            payment_id=payment.id, checkout_url=f"{self._settings.checkout_base}/?{query}"
        )

    def _fail_checkout(self, payment: Payment, error: str, status_code: int | None) -> None:
        payment.status = PaymentStatus.failed
        payment.next_reconcile_at = None
        payment.last_callback = {
            "source": "create_intention",
            "error": error,
            "status_code": status_code,
            "outcome_unknown": False,
        }
        self._session.commit()

    def _note_unknown_checkout(self, payment: Payment, error: str, status_code: int | None) -> None:
        """Record an unknown intention outcome and leave the payment pending."""
        payment.last_callback = {
            "source": "create_intention",
            "error": error,
            "status_code": status_code,
            "outcome_unknown": True,
        }
        self._session.commit()

    # -- callbacks ------------------------------------------------------------

    def apply_transaction_callback(self, obj: JsonMap) -> None:
        """Apply a HMAC-verified transaction callback ``obj`` (spec §5.1 step 4, §6).

        Never commits: the webhook route's ``sessionmaker.begin()`` owns the
        transaction and answers 200 only after it commits.

        Stamps ``Payment.callback_received_at`` on the payment the *signed* ``order.id``
        resolves to (see ``_apply_transaction``), so the admin "missing callback" queue
        can tell a payment whose callback never came from one reconcile found first.
        """
        self._apply_transaction(obj, source="callback")

    def _record_event(self, kind: PaymobEventKind, dedupe_key: str, payload: JsonMap) -> bool:
        """Insert the event once; False when ``dedupe_key`` was already recorded.

        ``payload`` is stored as given: callers pass it already redacted.
        """
        inserted = self._session.execute(
            pg_insert(PaymobEvent)
            .values(
                kind=kind, dedupe_key=dedupe_key, payload=dict(payload), processed_at=self._now()
            )
            .on_conflict_do_nothing(index_elements=[PaymobEvent.dedupe_key])
            .returning(PaymobEvent.id)
        ).scalar_one_or_none()
        return inserted is not None

    def _has_recorded_final_state(self, txn_id: int) -> bool:
        """True when any non-pending state (failure, success, void...) is stored for ``txn_id``.

        Paymob transaction ids are globally unique, so the stored events' dedupe keys
        (``txn:<id>:s<success>p<pending>...``, see ``transaction_dedupe_key``) answer this
        without a new column. ``s_p0`` matches every key whose pending flag is clear:
        ``_`` is the one-character LIKE wildcard for the success flag, so a failure
        (``s0p0``), a success carrying an error or a void (``s1p0``) all count. A
        pending callback for such a transaction is stale. The prefix LIKE is served by
        ``ix_paymob_events_dedupe_key_prefix`` (``text_pattern_ops``).
        """
        return (
            self._session.scalar(
                select(
                    select(PaymobEvent.id)
                    .where(
                        PaymobEvent.kind == PaymobEventKind.transaction,
                        PaymobEvent.dedupe_key.like(f"txn:{txn_id}:s_p0%"),
                    )
                    .exists()
                )
            )
            is True
        )

    def _payment_for_callback(self, obj: JsonMap, order_map: JsonMap) -> Payment | None:
        """The payment a callback is for, found by the *signed* ``order.id``, or ``None``.

        ``order.merchant_order_id`` is not under the HMAC, so it cannot select the row:
        anyone holding a genuine signature could edit it to point at another payment.
        The signed Paymob order id (stored as ``paymob_order_id`` at checkout) selects the
        row, and a reference that is present must then agree with it. A callback that
        matches nothing is logged at error level and settles nothing; the reconcile
        inquiry reaches the payment from our side, which needs no ``order.id``. When the
        reference names an open payment that has no order yet, reconcile is re-armed
        (``_rearm_reconcile_for_reference``).
        """
        order_id = _as_int(order_map.get("id"))
        payment = (
            self._session.scalars(
                select(Payment).where(Payment.paymob_order_id == order_id).with_for_update()
            ).one_or_none()
            if order_id is not None
            else None
        )
        if payment is not None and self._answers_for(payment, obj):
            return payment
        if payment is None:
            self._rearm_reconcile_for_reference(order_map.get("merchant_order_id"))
            if obj.get("api_source") == "SUBSCRIPTION" and self._is_moto_integration(obj):
                # Paymob charges a renewal on the plan's MOTO integration with no intention of
                # ours, so no payment of ours can match it yet. ``api_source`` is not signed, so
                # the signed MOTO ``integration_id`` must agree before the log level drops:
                # nothing is settled from it, and every other unmatched callback stays an
                # error. Renewals are recorded by the subscription webhook and the drift check
                # (Phase 05), not here (skill audit I5).
                log.info(
                    "paymob_renewal_txn_callback_unmatched",
                    order_id=str(order_map.get("id"))[:32],
                    txn_id=_as_int(obj.get("id")),
                    integration_id=str(obj.get("integration_id"))[:20],
                )
                return None
        log.error(
            "paymob_callback_unmatched",
            reason="reference_mismatch" if payment is not None else "no_payment_for_order",
            order_id=str(order_map.get("id"))[:32],
            merchant_order_id=str(order_map.get("merchant_order_id"))[:64],
            txn_id=_as_int(obj.get("id")),
        )
        return None

    def _rearm_reconcile_for_reference(self, reference: object) -> None:
        """Make an open payment with no recorded Paymob order due for an inquiry now.

        A payment whose checkout outcome was unknown has no ``paymob_order_id``, so a
        genuine callback cannot be matched by its signed order id. The callback names the
        payment only through the unsigned reference, so it is not believed: nothing is
        settled from it. It is a hint that Paymob has the transaction, and the inquiry
        (keyed on our own reference, answered by Paymob) is the trusted path. Setting
        ``next_reconcile_at`` re-arms reconcile and lifts a stuck payment's cleared
        schedule. Only an open payment with no order is touched, and only to bring its
        schedule forward, so a forged hint costs at most one inquiry per pass.
        """
        if not isinstance(reference, str) or not reference:
            return
        payment = self._session.scalars(
            select(Payment).where(Payment.special_reference == reference).with_for_update()
        ).one_or_none()
        if payment is None or payment.paymob_order_id is not None or payment.status not in _OPEN:
            return
        now = self._now()
        if payment.next_reconcile_at is None or payment.next_reconcile_at > now:
            payment.next_reconcile_at = now
            log.warning("paymob_callback_rearmed_reconcile", payment_id=str(payment.id))

    def _is_moto_integration(self, obj: JsonMap) -> bool:
        """True when the signed ``integration_id`` is the configured MOTO integration."""
        moto = self._settings.moto_integration_id
        return moto is not None and _as_int(obj.get("integration_id")) == moto

    def _is_our_integration(self, obj: JsonMap) -> bool:
        """True when the signed ``integration_id`` is one configured for this account and mode.

        The configured ids are the card, Apple Pay and MOTO integrations: mode is set by the
        keys, and an id from the other mode (or another integration) is not in the set. A
        renewal arrives on the MOTO id. A missing or unreadable id is not ours.
        """
        ours = {
            value
            for value in (
                self._settings.card_integration_id,
                self._settings.apple_pay_integration_id,
                self._settings.moto_integration_id,
            )
            if value is not None
        }
        return _as_int(obj.get("integration_id")) in ours

    def _integration_allowed_for(self, payment: Payment, obj: JsonMap) -> bool:
        """True when ``payment`` may be settled by a transaction on the signed ``integration_id``.

        Which integration may take a payment follows how it was started, so a purchase that
        needs a 3DS challenge can never settle through the no-3DS MOTO integration (Lemely, not
        the issuer, carries that chargeback liability, UD-P1):

        * a **renewal** keeps Phase 05's rule: any integration configured for this account
          and mode (Paymob charges it on the plan's MOTO integration);
        * a payment with a ``dedupe_key`` was **charged by us on a saved card** (auto top-up,
          the fallback seat charge): the MOTO integration only. The 0056 CHECK ties the key to
          those purposes, so it is the reliable discriminator: ``purpose`` is ambiguous
          (``extra_seats`` is both) and ``method`` is overwritten by the first callback;
        * every other payment is a **checkout** the payer completes in Unified Checkout: the
          card and Apple Pay integrations only.
        """
        if payment.purpose is PaymentPurpose.subscription_renewal:
            return self._is_our_integration(obj)
        integration = _as_int(obj.get("integration_id"))
        if payment.dedupe_key is not None:
            moto = self._settings.moto_integration_id
            return moto is not None and integration == moto
        checkout = {
            value
            for value in (
                self._settings.card_integration_id,
                self._settings.apple_pay_integration_id,
            )
            if value is not None
        }
        return integration in checkout

    @staticmethod
    def _is_child_transaction(obj: JsonMap) -> bool:
        """True for a refund/void child. Any of the three markers is enough.

        Only ``has_parent_transaction`` is under the HMAC; ``is_refund`` and ``is_void``
        are not. They are not dropped (Paymob's refund shape is not pinned down), so the
        caller keys a child's event apart from the transaction key, and a disagreement
        between the signed and unsigned markers is logged.
        """
        return (
            _is_true(obj.get("is_refund"))
            or _is_true(obj.get("is_void"))
            or _is_true(obj.get("has_parent_transaction"))
        )

    def _apply_transaction(
        self, obj: JsonMap, *, source: str, payment: Payment | None = None
    ) -> bool:
        """Verify, dedupe and apply one transaction ``obj`` (callback or inquiry).

        ``payment`` is passed by reconciliation, which already holds its row lock. Returns
        ``False`` only when the signed ``integration_id`` is not ours and the transaction was
        held back for manual review; every other outcome (applied, duplicate, no payment, a
        refund child) is ``True``.
        """
        txn_id = _as_int(obj.get("id"))
        if txn_id is None:
            raise MalformedCallback("transaction callback has no integer id")
        safe = _redact_tokens(obj)
        order = obj.get("order")
        order_map: JsonMap = order if isinstance(order, Mapping) else {}
        # Lock order: the payment row first (FOR UPDATE), then the ``paymob_events`` insert.
        # ``reconcile_pending`` (Task 8) locks the payment before it calls this method, so
        # taking the event's unique-key row first here would deadlock against it. Every
        # path that touches both must follow payment-then-event.
        if payment is None:
            payment = self._payment_for_callback(obj, order_map)
            if payment is None:
                # An audit row under its own key: the key ``txn:<id>:...`` is the one the
                # genuine callback for this transaction needs, and must stay free.
                self._record_event(PaymobEventKind.transaction, f"unmatched:{txn_id}", safe)
                return True
        child = self._is_child_transaction(obj)
        if source == "callback" and not child:
            # Arrival stamp (P07 DV-4): on the payment the signed ``order.id`` resolved, in
            # this callback's transaction (payment row already locked, event insert still
            # to come), and before the dedupe check below, so a duplicate, or a callback
            # that reconcile has already overtaken, still counts as a callback. A refund or
            # void child is not the parent's payment result. An inquiry never stamps.
            payment.callback_received_at = self._now()
        if not child and not self._integration_allowed_for(payment, obj):
            # Another integration on the same account (a payment link, a dashboard test) signs
            # with the same HMAC secret, so a genuine signature and a real ``order.id`` are not
            # enough: ``integration_id`` is signed and says which integration took the payment.
            # It is judged on the callback and on a reconcile inquiry alike: an inquiry proves
            # the answer came from Paymob, not which integration took the money, and the next
            # pass would otherwise settle what the callback refused. Nothing is settled
            # automatically; the payment stays open for a person to review (reconcile stops
            # polling it, see ``_reconcile_one``), with an error-level alert naming the path.
            # The audit row has its own key so the genuine callback's ``txn:`` key stays free.
            # A refund/void child is not judged: it settles nothing, and the parent's own
            # callback carries the state (skill audit I1, review I1). Which integrations a payment
            # accepts depends on how it was started (``_integration_allowed_for``).
            log.error(
                "paymob_unexpected_integration",
                alert=True,
                path=source,
                payment_id=str(payment.id),
                txn_id=txn_id,
                integration_id=str(obj.get("integration_id"))[:20],
            )
            self._record_event(PaymobEventKind.transaction, f"rejected_integration:{txn_id}", safe)
            return False
        if child and (
            (_is_true(obj.get("is_refund")) or _is_true(obj.get("is_void")))
            != _is_true(obj.get("has_parent_transaction"))
        ):
            log.warning(
                "paymob_child_marker_mismatch",
                txn_id=txn_id,
                payment_id=str(payment.id),
                is_refund=_is_true(obj.get("is_refund")),
                is_void=_is_true(obj.get("is_void")),
                has_parent_transaction=_is_true(obj.get("has_parent_transaction")),
            )
        # A child is keyed apart: ``is_refund``/``is_void`` are unsigned, so a payer who
        # resends their own signed success with one set must not use up the ``txn:`` key
        # the genuine callback and the reconcile inquiry need.
        event_key = transaction_dedupe_key(obj)
        if child:
            event_key = f"child:{event_key}"
        if not self._record_event(PaymobEventKind.transaction, event_key, safe):
            log.info("paymob_duplicate_transaction", txn_id=txn_id, source=source)
            if not child and _is_true(obj.get("is_refunded")) and payment.status in _SETTLED:
                # The refunded total is not signed, so it is not part of the key: a second,
                # larger total arrives under the same one. Re-running the refund step is
                # idempotent and monotonic (the largest total and the furthest status win),
                # and it runs only for a callback that already passed the signed checks.
                self._apply_post_payment_flags(payment, obj, safe, txn_id=txn_id)
            return True
        if child:
            # A refund/void child; the parent's own callback carries the state.
            log.info("paymob_child_transaction", payment_id=str(payment.id), txn_id=txn_id)
            return True
        if payment.status in _SETTLED:
            self._apply_post_payment_flags(payment, obj, safe, txn_id=txn_id)
            return True
        if payment.status in (PaymentStatus.failed_mismatch, PaymentStatus.voided):
            log.warning(
                "paymob_callback_for_closed_payment",
                payment_id=str(payment.id),
                status=payment.status.value,
                txn_id=txn_id,
            )
            return True

        if (
            payment.status is PaymentStatus.failed
            and obj.get("pending") is True
            and (txn_id == payment.paymob_txn_id or self._has_recorded_final_state(txn_id))
        ):
            # A pending callback for a transaction whose final state is already recorded is
            # stale (delivered out of order). Reopening would strand the payment in
            # ``pending``: the reconcile inquiry's final state dedupes against the event
            # already recorded and never lands. Only a genuinely new attempt (no recorded
            # final state for its id) reopens it.
            log.info(
                "paymob_stale_pending_after_failure", payment_id=str(payment.id), txn_id=txn_id
            )
            return True

        # Open (created/pending) or failed: a failed payment can still become paid on a
        # later verified success (R20b), and the grant's idempotency key keeps that to one.
        payment.last_callback = safe
        payment.paymob_txn_id = txn_id
        if payment.paymob_order_id is None:
            payment.paymob_order_id = _as_int(order_map.get("id"))
        source_data = obj.get("source_data")
        if isinstance(source_data, Mapping) and isinstance(source_data.get("type"), str):
            payment.method = source_data["type"]

        amount = _as_int(obj.get("amount_cents"))
        currency = obj.get("currency")
        if amount != payment.amount_minor or currency != payment.currency:
            payment.status = PaymentStatus.failed_mismatch
            payment.next_reconcile_at = None
            log.error(
                "paymob_amount_mismatch",
                payment_id=str(payment.id),
                txn_id=txn_id,
                expected_amount=payment.amount_minor,
                received_amount=amount,
                expected_currency=payment.currency,
                received_currency=str(currency)[:8],
                source=source,
            )
            return True

        succeeded = (
            obj.get("success") is True
            and obj.get("pending") is False
            and not _is_true(obj.get("is_voided"))
            and not _is_true(obj.get("is_refunded"))
            and not _is_true(obj.get("error_occured"))
        )
        if succeeded:
            handler = _PAID_HANDLERS.get(payment.purpose)
            if handler is None:
                raise RuntimeError(f"no paid handler registered for {payment.purpose.value}")
            payment.status = PaymentStatus.paid
            payment.paid_at = self._now()
            payment.next_reconcile_at = None
            handler(self._session, payment, obj)
            log.info(
                "paymob_payment_paid",
                payment_id=str(payment.id),
                purpose=payment.purpose.value,
                txn_id=txn_id,
                source=source,
            )
        elif obj.get("pending") is True:
            if payment.status is PaymentStatus.failed:
                # A new attempt (another transaction) is in flight after a decline: its success
                # callback may be lost, so put the payment back on the reconcile schedule.
                payment.reconcile_attempts = 0  # the new attempt starts at the 15 minute backoff
                payment.next_reconcile_at = self._now() + RECONCILE_AFTER
                log.info("paymob_pending_after_failure", payment_id=str(payment.id), txn_id=txn_id)
            payment.status = PaymentStatus.pending
        else:
            payment.status = PaymentStatus.failed
            payment.next_reconcile_at = None
            log.info(
                "paymob_payment_failed", payment_id=str(payment.id), txn_id=txn_id, source=source
            )
        return True

    def _apply_post_payment_flags(
        self, payment: Payment, obj: JsonMap, safe: JsonMap, *, txn_id: int
    ) -> None:
        """Mirror a refund or void on an already-paid payment (no grant changes here)."""
        if txn_id != payment.paymob_txn_id:
            log.warning(
                "paymob_second_transaction_on_paid_payment",
                payment_id=str(payment.id),
                txn_id=txn_id,
            )
            return
        if _is_true(obj.get("is_voided")):
            payment.last_callback = dict(safe)
            payment.status = PaymentStatus.voided
        elif _is_true(obj.get("is_refunded")):
            refunded = _as_int(obj.get("refunded_amount_cents")) or 0
            seen = _as_int((payment.last_callback or {}).get("refunded_amount_cents")) or 0
            reached = (
                PaymentStatus.refunded
                if refunded >= payment.amount_minor
                else PaymentStatus.partially_refunded
            )
            if refunded >= seen:
                payment.last_callback = dict(safe)  # keeps the largest total seen
            if _REFUND_RANK[reached] > _REFUND_RANK[payment.status]:
                payment.status = reached
        else:
            return
        log.warning(
            "paymob_payment_reversed",
            payment_id=str(payment.id),
            status=payment.status.value,
            txn_id=txn_id,
        )

    def apply_token_callback(self, obj: JsonMap) -> None:
        """Store or refresh the payer's saved card from a verified TOKEN callback (§5.5).

        Never commits. The token is sealed for, and fingerprinted under, the payer's
        user id (R22), and the stored event never holds the raw token.
        """
        token_id, token = _validate_token_callback(obj)
        payload = _redact_tokens({**dict(obj), "token": _REDACTED})
        dedupe_key = f"token:{token_id}:{obj.get('order_id')}"
        if not self._record_event(PaymobEventKind.token, dedupe_key, payload):
            log.info("paymob_duplicate_token", token_id=token_id)
            return
        order_id = _as_int(obj.get("order_id"))
        payment = (
            self._session.scalars(
                select(Payment).where(Payment.paymob_order_id == order_id)
            ).one_or_none()
            if order_id is not None
            else None
        )
        if payment is None:
            log.warning("paymob_token_unknown_order", order_id=str(obj.get("order_id"))[:32])
            return
        cipher = self.cipher
        if cipher is None:
            log.warning("paymob_token_not_stored_no_key", payment_id=str(payment.id))
            return
        owner = payment.payer_user_id
        fingerprint = cipher.fingerprint(token, owner)
        masked_pan = str(obj.get("masked_pan") or "")
        subtype = obj.get("card_subtype")
        brand = subtype if isinstance(subtype, str) else None
        # One atomic upsert on (user_id, token_fingerprint): two callbacks for the same
        # card racing on its first save cannot both insert, and neither 500s.
        stmt = pg_insert(SavedCard).values(
            user_id=owner,
            token=cipher.encrypt(token, owner),
            token_fingerprint=fingerprint,
            masked_pan=masked_pan,
            brand=brand,
            paymob_token_id=token_id,
            is_active=True,
        )
        self._session.execute(
            stmt.on_conflict_do_update(
                index_elements=[SavedCard.user_id, SavedCard.token_fingerprint],
                set_={
                    "masked_pan": stmt.excluded.masked_pan,
                    "brand": stmt.excluded.brand,
                    "paymob_token_id": stmt.excluded.paymob_token_id,
                    "is_active": True,
                    "updated_at": func.now(),
                },
            )
        )
        log.info("paymob_card_saved", payment_id=str(payment.id), user_id=str(owner))

    def card_token(self, card: SavedCard) -> str:
        """The decrypted token for a merchant-initiated charge (Phase 06).

        Opens only for the row's own ``user_id``; a ciphertext moved to another
        user's row raises ``TokenCipherError``.
        """
        cipher = self.cipher
        if cipher is None:
            raise BillingError("card token key is not configured")
        return cipher.decrypt(card.token, card.user_id)

    # -- reconciliation (spec §5.10) -------------------------------------------

    def reconcile_pending(self, *, now: datetime, limit: int = RECONCILE_BATCH) -> int:
        """Inquire every open payment that is due; commit after each. Returns how many.

        ``FOR UPDATE SKIP LOCKED`` lets two replicas run this at once without
        inquiring the same payment twice. A payment still open after the inquiry
        is pushed back on a doubling schedule (15m, 30m, 1h, 2h, 4h, 4h...) until it
        is 24 hours old, then marked ``failed``. That give-up needs a *successful*
        inquiry that shows the payment still open (or no transaction at all): any
        ``PaymobError`` (timeout, transport, 5xx, an unreadable 2xx, a 4xx), and any
        answer we cannot read, only reschedules, because a Paymob outage must never
        fail a payment the customer may have paid (index R20b).

        Lock order is payment row, then ``paymob_events`` insert (index R14): the
        select below locks the payment and ``_apply_transaction`` receives it, so it
        neither looks it up nor locks it again.

        One payment that raises an unexpected error cannot block the rest. The
        select orders by ``next_reconcile_at``, so a row that failed and kept its old
        schedule would be picked first on every pass and starve everything behind it.
        It is rolled back, logged as ``paymob_reconcile_error``, pushed back on the
        same backoff in a fresh transaction, and the batch carries on. It is not
        counted in the return value, which is the number of payments inquired and
        committed.
        """
        handled = 0
        for _ in range(limit):
            payment = self._session.scalars(
                select(Payment)
                .where(Payment.status.in_(_OPEN), Payment.next_reconcile_at <= now)
                .order_by(Payment.next_reconcile_at, Payment.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            ).first()
            if payment is None:
                break
            payment_id = payment.id
            try:
                self._reconcile_one(payment, now=now)
                self._session.commit()
            except Exception:
                self._session.rollback()
                log.exception("paymob_reconcile_error", payment_id=str(payment_id))
                if not self._back_off_poisoned(payment_id, now=now):
                    break
                continue
            handled += 1
        return handled

    def _back_off_poisoned(self, payment_id: uuid.UUID, *, now: datetime) -> bool:
        """Push a payment whose reconcile raised back on the schedule, in a fresh transaction.

        False when even that failed (the database itself is unwell): the caller stops
        the pass rather than pick the same row again.
        """
        try:
            payment = self._session.scalars(
                select(Payment)
                .where(Payment.id == payment_id, Payment.status.in_(_OPEN))
                .with_for_update(skip_locked=True)
            ).first()
            if payment is not None:
                self._reschedule_unknown(payment, now=now)
            self._session.commit()
        except Exception:
            self._session.rollback()
            log.exception("paymob_reconcile_backoff_error", payment_id=str(payment_id))
            return False
        return True

    def _reconcile_one(self, payment: Payment, *, now: datetime) -> None:
        try:
            obj = self._client.inquire_by_order_ref(payment.special_reference)
        except PaymobError as exc:
            # The outcome is unknown whatever the flavour: reschedule, never fail.
            log.warning(
                "paymob_inquiry_failed",
                payment_id=str(payment.id),
                status_code=exc.status_code,
                timeout=exc.timeout,
                outcome_unknown=_outcome_unknown(exc),
            )
            self._reschedule_unknown(payment, now=now)
            return
        if obj is not None:
            if _as_int(obj.get("id")) is None:
                # A 2xx object with no transaction id is an unreadable answer, not "no
                # transaction yet": it must not start the 24-hour countdown.
                log.warning("paymob_inquiry_unreadable", payment_id=str(payment.id))
                self._reschedule_unknown(payment, now=now)
                return
            if not self._answers_for(payment, obj):
                # The answer belongs to another payment. Applying it would pay and grant
                # this one on that payment's transaction and consume the event key its own
                # callback needs, leaving it open for good. Record nothing.
                order = obj.get("order")
                answered = order.get("merchant_order_id") if isinstance(order, Mapping) else None
                answered_order = order.get("id") if isinstance(order, Mapping) else order
                log.error(
                    "paymob_inquiry_reference_mismatch",
                    payment_id=str(payment.id),
                    answered_reference=str(answered)[:64],
                    answered_order_id=str(answered_order)[:32],
                    txn_id=_as_int(obj.get("id")),
                )
                self._reschedule_unknown(payment, now=now)
                return
            if not self._apply_transaction(obj, source="inquiry", payment=payment):
                # Paymob answered with a transaction on an integration that is not ours (the
                # alert is already logged). Never settle it automatically, and never abandon
                # it after 24 hours either: money may have moved, so it stays open with no
                # schedule, as a stuck payment does, until a person decides.
                payment.next_reconcile_at = None
                return
        if payment.status not in _OPEN:
            payment.next_reconcile_at = None
            return
        if now - _reconcile_clock(payment) >= RECONCILE_GIVE_UP_AFTER:
            payment.status = PaymentStatus.failed
            payment.next_reconcile_at = None
            log.info("paymob_payment_abandoned", payment_id=str(payment.id))
            return
        self._schedule_next(payment, now=now)

    def reconcile_payment_now(self, payment_id: uuid.UUID, *, now: datetime) -> PaymentStatus:
        """Reconcile one payment now, ignoring its backoff schedule (admin trigger, spec §8).

        Locks the payment ``FOR UPDATE`` (payment row first, then the ``paymob_events``
        insert inside ``_reconcile_one``, the same lock order as ``reconcile_pending``) and
        runs the per-payment routine, so every rule of the sweeper applies unchanged:

        * a transaction on an integration that is not ours is never settled: the payment
          stays open with no schedule until a person decides;
        * a payment 24 hours old (counted from ``coalesce(sent_at, created_at)``) whose
          inquiry shows no transaction, or one still pending, becomes ``failed``;
        * an inquiry that errors only reschedules.

        A payment that is no longer ``created`` or ``pending`` is returned untouched, so a
        double click cannot inquire a settled payment again. The row is read fresh under the
        lock, so a caller may load the payment first. The lock is ``NOWAIT``: a payment another
        transaction holds (the sweeper mid-inquiry, a callback) raises :class:`PaymentBusyError`
        at once instead of stalling the request, and the caller must roll back. Never commits:
        the caller's transaction does. Raises :class:`PaymentNotFoundError` for an unknown id.
        """
        try:
            # ``populate_existing``: the lock alone does not refresh an object this session
            # already loaded (an admin route reads the payment first). A stale ``pending``
            # here would let the 24-hour give-up overwrite a payment a callback just paid.
            payment = self._session.get(
                Payment, payment_id, with_for_update={"nowait": True}, populate_existing=True
            )
        except OperationalError as exc:
            if isinstance(exc.orig, psycopg.errors.LockNotAvailable):
                raise PaymentBusyError(str(payment_id)) from None
            raise
        if payment is None:
            raise PaymentNotFoundError(str(payment_id))
        if payment.status in _OPEN:
            self._reconcile_one(payment, now=now)
        return payment.status

    @staticmethod
    def _answers_for(payment: Payment, obj: JsonMap) -> bool:
        """False when ``obj`` names a different payment than the one inquired.

        Two identifiers are cross-checked: ``order.merchant_order_id`` against our
        ``special_reference``, and ``order.id`` (or a bare-int ``order``) against the
        payment's ``paymob_order_id`` once that is known. A disagreement on either is a
        refusal. An answer that carries neither is taken to be for the inquired payment:
        the inquiry was keyed on its reference.
        """
        order = obj.get("order")
        reference: object = None
        order_id: int | None
        if isinstance(order, Mapping):
            reference = order.get("merchant_order_id")
            order_id = _as_int(order.get("id"))
        else:
            order_id = _as_int(order)
        if reference is not None and str(reference) != payment.special_reference:
            return False
        return (
            payment.paymob_order_id is None
            or order_id is None
            or order_id == payment.paymob_order_id
        )

    def _reschedule_unknown(self, payment: Payment, *, now: datetime) -> None:
        """Reschedule after an inquiry that told us nothing, or stop polling a stuck payment.

        After ``RECONCILE_STUCK_AFTER`` the schedule is cleared so the row stops costing
        an inquiry per pass, and ``paymob_reconcile_stuck`` is logged at error level for
        a human. The status stays open: an unknown outcome is never "failed" (R20b), and a
        late callback can still settle it.
        """
        if now - _reconcile_clock(payment) >= RECONCILE_STUCK_AFTER:
            payment.reconcile_attempts += 1
            payment.next_reconcile_at = None
            log.error(
                "paymob_reconcile_stuck",
                payment_id=str(payment.id),
                status=payment.status.value,
                attempts=payment.reconcile_attempts,
            )
            return
        self._schedule_next(payment, now=now)

    def _schedule_next(self, payment: Payment, *, now: datetime) -> None:
        payment.reconcile_attempts += 1
        exponent = min(payment.reconcile_attempts - 1, _MAX_BACKOFF_EXPONENT)
        payment.next_reconcile_at = now + min(
            RECONCILE_AFTER * (2**exponent), RECONCILE_MAX_BACKOFF
        )


__all__ = [
    "INTENTION_EXPIRATION_SECONDS",
    "MAX_CARD_TOKENS",
    "RECONCILE_AFTER",
    "RECONCILE_BATCH",
    "RECONCILE_GIVE_UP_AFTER",
    "RECONCILE_MAX_BACKOFF",
    "RECONCILE_STUCK_AFTER",
    "RETURN_PATH",
    "WEBHOOK_PATH",
    "BillingError",
    "BillingService",
    "CheckoutResult",
    "CheckoutUnavailable",
    "CreditValiditySettingMissing",
    "JsonMap",
    "MalformedCallback",
    "NotLinkedToBeneficiary",
    "PaidHandler",
    "PaymentBusyError",
    "PaymentNotFoundError",
    "PhoneRequired",
    "UnknownCreditPack",
    "UnknownPayer",
    "active_catalogue",
    "add_months",
    "billing_data_for",
    "describe_payment",
    "grant_credit_pack",
    "is_linked_parent",
    "paid_handler_for",
    "payer_phone",
    "payment_for_viewer",
    "receipts_for",
    "register_paid_handler",
    "saved_cards_for",
    "transaction_dedupe_key",
]
