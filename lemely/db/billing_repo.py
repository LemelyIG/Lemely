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
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import urlencode

import structlog
from sqlalchemy import select

from lemely.db.models import ParentChildLink, User
from lemely.db.models.billing import (
    CreditPack,
    Payment,
    PaymentPurpose,
    PaymentStatus,
    PlanAudience,
    PlanTier,
)
from lemely.db.models.usage import GrantKind
from lemely.db.usage_ledger_repo import UsageLedger
from lemely.io.paymob.client import PaymobError
from lemely.runtime.token_cipher import TokenCipher

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from lemely.io.paymob.client import PaymobClient
    from lemely.runtime.config import PaymobSettings

log = structlog.get_logger(__name__)

CREDIT_EXPIRY_MONTHS: Final = 12
INTENTION_EXPIRATION_SECONDS: Final = 3600
RECONCILE_AFTER: Final = timedelta(minutes=15)
WEBHOOK_PATH: Final = "/api/webhooks/paymob/transaction"
RETURN_PATH: Final = "/billing/return"

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
    """The payer is not the beneficiary and has no ``parent_child_links`` row to them (403)."""


class MalformedCallback(BillingError):
    """A verified callback lacks a field we need (400)."""


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


def billing_data_for(user: User) -> dict[str, str]:
    """Paymob ``billing_data`` from the payer's profile (research 01 §2.1).

    First name, last name, email and phone are required by Paymob; address
    fields are not collected by Lemely and are sent as ``"NA"``, as Paymob's own
    samples send placeholders. Whether Paymob validates the ``"NA"`` phone
    fallback is an open question for the live test account (research 01 §8 q5).
    """
    first, _, last = (user.display_name or "").strip().partition(" ")
    return {
        "first_name": (first or "Lemely")[:50],
        "last_name": (last.strip() or "Customer")[:50],
        "email": user.email,
        "phone_number": user.phone or "NA",
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

    No usable answer (``status_code is None``) or an explicit ``outcome_unknown``
    is unknown by the client's contract. Only a received 4xx is a definite
    rejection: a 5xx (a gateway error does not say whether the order was created)
    or a 2xx we could not use is unknown even where the client did not flag it.
    """
    return exc.outcome_unknown or exc.status_code is None or not 400 <= exc.status_code < 500


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
    """Transaction id plus the state flags (spec §4.2): a new state is a new event."""
    return (
        f"txn:{obj.get('id')}:s{_flag(obj.get('success'))}p{_flag(obj.get('pending'))}"
        f"v{_flag(obj.get('is_voided'))}r{_flag(obj.get('is_refunded'))}"
        f":{_as_int(obj.get('refunded_amount_cents')) or 0}"
    )


# ---------------------------------------------------------------------------
# Paid handler: credit packs (spec §5.5).
# ---------------------------------------------------------------------------


def grant_credit_pack(session: Session, payment: Payment, obj: JsonMap) -> None:
    """Issue the beneficiary's visible credit grant, expiring 12 months after payment."""
    if payment.grant_units is None:
        raise RuntimeError(f"credit pack payment {payment.id} has no grant_units snapshot")
    paid_at = payment.paid_at or _utcnow()
    UsageLedger(session).issue_grant(
        owner_user_id=payment.beneficiary_user_id,
        kind=GrantKind.credit_pack,
        units=payment.grant_units,
        idempotency_key=f"payment:{payment.id}",
        expires_at=add_months(paid_at, CREDIT_EXPIRY_MONTHS),
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
    session: Session, *, audience: PlanAudience
) -> tuple[list[PlanTier], list[CreditPack]]:
    tiers = session.scalars(
        select(PlanTier)
        .where(PlanTier.is_active.is_(True), PlanTier.audience == audience)
        .order_by(PlanTier.price_minor, PlanTier.code)
    ).all()
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
        return f"{self._settings.redirection_base_url}{RETURN_PATH}?payment={payment_id}"

    def create_pack_checkout(
        self,
        *,
        payer_user_id: uuid.UUID,
        beneficiary_user_id: uuid.UUID,
        credit_pack_id: uuid.UUID,
    ) -> CheckoutResult:
        """Price a pack on the server, insert the payment, create the intention (§5.5).

        The price and unit count come from the ``credit_packs`` row, never from
        the caller. ``payer_user_id`` may differ from ``beneficiary_user_id`` only
        through a ``parent_child_links`` row (parent pays, child receives).
        """
        if not self._settings.checkout_configured:
            raise CheckoutUnavailable("Paymob checkout is not configured")
        pack = self._session.get(CreditPack, credit_pack_id)
        if pack is None or not pack.is_active or pack.price_minor <= 0 or pack.units <= 0:
            # Inactive signup-allowance rows (Phase 04) and zero-value packs are never sold.
            raise UnknownCreditPack(str(credit_pack_id))
        payer = self._session.get(User, payer_user_id)
        if payer is None:
            raise BillingError(f"unknown payer {payer_user_id}")
        if payer_user_id != beneficiary_user_id and not is_linked_parent(
            self._session, payer_user_id, beneficiary_user_id
        ):
            # A parent buys only for a linked child; nobody buys credits for a stranger.
            raise NotLinkedToBeneficiary(str(beneficiary_user_id))
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
            billing_data=billing_data_for(payer),
            subscription_plan_id=None,
        )

    def create_intention_checkout(
        self,
        *,
        payment: Payment,
        items: Sequence[JsonMap],
        billing_data: JsonMap,
        subscription_plan_id: int | None,
    ) -> CheckoutResult:
        """Commit ``payment``, create its Paymob intention, return the checkout URL.

        Shared with Phase 05 (subscriptions pass ``subscription_plan_id``). The call
        is never retried. ``CheckoutUnavailable`` is raised on every failure, but
        the payment's fate depends on what Paymob may have done:

        * A definite rejection (a received non-5xx error status), or a 2xx with no
          client secret: nothing can be paid, so the payment is marked ``failed``.
        * An unknown outcome (no usable answer, ``outcome_unknown``, or a 5xx):
          Paymob may have created the order and the customer may even pay it, so
          the payment stays ``created`` with its ``next_reconcile_at`` and the
          reconcile job settles it by inquiry. It is never marked ``failed`` here.
        """
        if not self._settings.checkout_configured:
            raise CheckoutUnavailable("Paymob checkout is not configured")
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
        client_secret = response.get("client_secret")
        if not isinstance(client_secret, str) or not client_secret:
            self._fail_checkout(payment, "intention response had no client_secret", None)
            log.warning("paymob_intention_without_secret", payment_id=str(payment.id))
            raise CheckoutUnavailable("Paymob returned no client secret")
        intention_id = response.get("id")
        payment.paymob_intention_id = str(intention_id) if intention_id else None
        payment.paymob_order_id = _as_int(response.get("intention_order_id"))
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


__all__ = [
    "CREDIT_EXPIRY_MONTHS",
    "INTENTION_EXPIRATION_SECONDS",
    "RECONCILE_AFTER",
    "RETURN_PATH",
    "WEBHOOK_PATH",
    "BillingError",
    "BillingService",
    "CheckoutResult",
    "CheckoutUnavailable",
    "JsonMap",
    "MalformedCallback",
    "NotLinkedToBeneficiary",
    "PaidHandler",
    "UnknownCreditPack",
    "active_catalogue",
    "add_months",
    "billing_data_for",
    "describe_payment",
    "grant_credit_pack",
    "is_linked_parent",
    "paid_handler_for",
    "payment_for_viewer",
    "receipts_for",
    "register_paid_handler",
    "transaction_dedupe_key",
]
