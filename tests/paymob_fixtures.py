"""Handwritten Paymob payloads and helpers shared by the billing tests.

Shapes follow the research notes (docs/billing/research/01, 02, 04): the
transaction object is the ``obj`` of a Transaction Processed callback, which has
the same shape as a transaction-inquiry response; the token object is the ``obj``
of a ``"type": "TOKEN"`` callback. They are handwritten from the documented field
lists until the live test account supplies recorded ones (spec §9 "Live test
account"). The HMAC secret is a test value: Paymob does not publish the secret
behind its worked example, so callbacks here are signed with it.
"""

from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import httpx

from lemely.db.models import ParentChildLink, User
from lemely.db.models.billing import CreditPack, Payment, PaymentPurpose, PaymentStatus
from lemely.db.models.enums import Role
from lemely.io.paymob.client import PaymobClient
from lemely.io.paymob.hmac import sign, token_hmac_message, transaction_hmac_message
from lemely.runtime.config import PaymobSettings

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session, sessionmaker

TEST_HMAC_SECRET = "test_hmac_secret_0123456789abcdef"
TEST_CARD_TOKEN_KEY = base64.urlsafe_b64encode(b"k" * 32).decode()
CARD_INTEGRATION_ID = 4569876
MOTO_INTEGRATION_ID = 4569877

PAYMOB_SETTINGS = PaymobSettings.model_validate(
    {
        "secret_key": "egy_sk_test_secret",
        "public_key": "egy_pk_test_public",
        "api_key": "api_key_test",
        "hmac_secret": TEST_HMAC_SECRET,
        "card_integration_id": CARD_INTEGRATION_ID,
        "moto_integration_id": MOTO_INTEGRATION_ID,
        "card_token_key": TEST_CARD_TOKEN_KEY,
    }
)


def transaction_obj(
    *,
    txn_id: int = 192036465,
    order_id: int = 265715202,
    merchant_order_id: str = "unknown-reference",
    amount_cents: int = 10000,
    currency: str = "EGP",
    success: bool = True,
    pending: bool = False,
    is_voided: bool = False,
    is_refunded: bool = False,
    refunded_amount_cents: int = 0,
    error_occured: bool = False,
    has_parent_transaction: bool = False,
    is_refund: bool = False,
    is_void: bool = False,
    source_type: str = "card",
) -> dict[str, Any]:
    """A card transaction ``obj`` (research 02 §1.2), success by default."""
    paid = success and not pending
    return {
        "id": txn_id,
        "pending": pending,
        "amount_cents": amount_cents,
        "success": success,
        "is_auth": False,
        "is_capture": False,
        "is_standalone_payment": not has_parent_transaction,
        "is_voided": is_voided,
        "is_refunded": is_refunded,
        "is_3d_secure": True,
        "integration_id": CARD_INTEGRATION_ID,
        "profile_id": 106,
        "has_parent_transaction": has_parent_transaction,
        "order": {
            "id": order_id,
            "created_at": "2026-11-05T10:00:00.000000",
            "delivery_needed": False,
            "amount_cents": amount_cents,
            "currency": currency,
            "merchant_order_id": merchant_order_id,
            "paid_amount_cents": amount_cents if paid else 0,
            "payment_status": "PAID" if paid else "UNPAID",
            "items": [
                {
                    "name": "Credit pack",
                    "description": "100 credits",
                    "amount_cents": amount_cents,
                    "quantity": 1,
                }
            ],
        },
        "created_at": "2026-11-05T10:00:05.123456",
        "currency": currency,
        "source_data": {
            "type": source_type,
            "pan": "2346",
            "sub_type": "MasterCard",
            "tenure": None,
        },
        "api_source": "OTHER",
        "is_void": is_void,
        "is_refund": is_refund,
        "error_occured": error_occured,
        "is_live": False,
        "refunded_amount_cents": refunded_amount_cents,
        "is_captured": False,
        "captured_amount": 0,
        "owner": 302852,
        "parent_transaction": None,
        "data": {
            "message": "Approved" if success else "Do not honour",
            "txn_response_code": "APPROVED" if success else "DECLINED",
            "acq_response_code": "00" if success else "05",
        },
    }


def token_obj(
    *,
    token_id: int = 15978654,
    order_id: str = "265715202",
    token: str = "3f22ce8a4e5b6c7d8e9f",
    masked_pan: str = "xxxx-xxxx-xxxx-2346",
    card_subtype: str = "MasterCard",
    email: str = "kiyedi3052@claspira.com",
) -> dict[str, Any]:
    """A card-token callback ``obj`` (research 02 §2.2, create-card-token sample)."""
    return {
        "id": token_id,
        "token": token,
        "masked_pan": masked_pan,
        "merchant_id": 1053928,
        "card_subtype": card_subtype,
        "created_at": "2026-08-24T13:28:31.015314",
        "email": email,
        "order_id": order_id,
        "user_added": False,
        "next_payment_intention": "pi_test_0001",
        "cardholder_name": "TEST ACCOUNT",
        "expiry_month": "01",
        "expiry_year": "39",
    }


def transaction_callback(obj: dict[str, Any]) -> dict[str, Any]:
    return {"type": "TRANSACTION", "obj": obj}


def token_callback(obj: dict[str, Any]) -> dict[str, Any]:
    return {"type": "TOKEN", "obj": obj}


def sign_transaction(obj: dict[str, Any], secret: str = TEST_HMAC_SECRET) -> str:
    return sign(transaction_hmac_message(obj), secret)


def sign_token(obj: dict[str, Any], secret: str = TEST_HMAC_SECRET) -> str:
    return sign(token_hmac_message(obj), secret)


#: ``POST v1/intention/`` 201 body (research 01 §2.1 sample, with our test ids).
INTENTION_RESPONSE: dict[str, Any] = {
    "payment_keys": [
        {
            "integration": CARD_INTEGRATION_ID,
            "key": "ZXlKaGJHY2lPaUpJVXpVeE1pSjkuZXlKMWMyVnlYMmxrSWpveE1EVXpPVEk0ZlE.payment-key",
            "gateway_type": "MIGS",
            "iframe_id": None,
            "order_id": 265715202,
        }
    ],
    "intention_order_id": 265715202,
    "id": "pi_test_bd49bb7fb4da48cfac4ec71ab4d8c433",
    "intention_detail": {
        "amount": 10000,
        "items": [
            {"name": "Credit pack", "amount": 10000, "description": "100 credits", "quantity": 1}
        ],
        "currency": "EGP",
        "billing_data": {
            "apartment": "NA",
            "floor": "NA",
            "first_name": "Sara",
            "last_name": "Ali",
            "street": "NA",
            "building": "NA",
            "phone_number": "+201234567890",
            "shipping_method": None,
            "city": "NA",
            "country": "EGY",
            "state": "NA",
            "email": "payer@example.com",
            "postal_code": None,
        },
    },
    "client_secret": "egy_csk_test_94042f793419c5a0f14a4cadfda9d626",
    "payment_methods": [
        {
            "integration_id": CARD_INTEGRATION_ID,
            "alias": None,
            "name": "Card",
            "method_type": "online",
            "currency": "EGP",
            "live": False,
            "use_cvc_with_moto": False,
        }
    ],
    "special_reference": "set-per-test",
    "extras": {"creation_extras": {}, "confirmation_extras": None},
    "confirmed": False,
    "status": "intended",
    "created": "2026-11-05T10:00:00.000000",
    "card_detail": None,
    "card_tokens": [],
    "object": "paymentintention",
}

#: ``POST api/auth/tokens`` body, trimmed (the real one carries the merchant profile).
AUTH_TOKEN_RESPONSE: dict[str, Any] = {"token": "auth_token_test_1", "profile": {"id": 302852}}

#: ``GET api/acceptance/subscriptions/{id}`` (research 02 §2.3/§6 field list).
SUBSCRIPTION_RESPONSE: dict[str, Any] = {
    "id": 1264,
    "client_info": {
        "email": "payer@example.com",
        "full_name": "Sara Ali",
        "phone_number": "+201234567890",
    },
    "frequency": 30,
    "created_at": "2026-11-05T10:00:00",
    "updated_at": "2026-11-05T10:00:00",
    "name": "Student monthly",
    "reminder_days": None,
    "retrial_days": 3,
    "plan_id": 1186,
    "state": "active",
    "amount_cents": 9900,
    "starts_at": "2026-11-05",
    "next_billing": "2026-12-05",
    "reminder_date": None,
    "ends_at": None,
    "resumed_at": None,
    "suspended_at": None,
    "webhook_url": "https://lemelyig.com/api/webhooks/paymob/subscription",
    "integration": MOTO_INTEGRATION_ID,
    "initial_transaction": 241322967,
}

#: ``POST api/acceptance/subscription-plans`` body.
PLAN_RESPONSE: dict[str, Any] = {
    "id": 1186,
    "frequency": 30,
    "name": "Student monthly",
    "reminder_days": None,
    "retrial_days": 3,
    "plan_type": "rent",
    "number_of_deductions": None,
    "amount_cents": 9900,
    "use_transaction_amount": False,
    "is_active": True,
    "webhook_url": "https://lemelyig.com/api/webhooks/paymob/subscription",
    "integration": MOTO_INTEGRATION_ID,
    "fee": None,
}
# ---------------------------------------------------------------------------
# Fake client and DB seeders (Task 6 onward).
# ---------------------------------------------------------------------------

FIXED_NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)


def _refuse(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"unexpected Paymob HTTP call: {request.method} {request.url}")


class FakePaymobClient(PaymobClient):
    """A PaymobClient whose HTTP layer is never reached; each call is scripted."""

    def __init__(self, settings: PaymobSettings = PAYMOB_SETTINGS) -> None:
        super().__init__(settings, http=httpx.Client(transport=httpx.MockTransport(_refuse)))
        self.intentions: list[dict[str, Any]] = []
        self.intention_response: dict[str, Any] | Exception = dict(INTENTION_RESPONSE)
        self.on_intention: Callable[[dict[str, Any]], None] | None = None
        self.inquiries: list[str] = []
        self.inquiry_response: dict[str, Any] | None | Exception = None

    def create_intention(self, body: Any) -> dict[str, Any]:
        self.intentions.append(dict(body))
        if self.on_intention is not None:
            self.on_intention(dict(body))
        if isinstance(self.intention_response, Exception):
            raise self.intention_response
        return dict(self.intention_response)

    def inquire_by_order_ref(self, merchant_order_id: str) -> dict[str, Any] | None:
        self.inquiries.append(merchant_order_id)
        if isinstance(self.inquiry_response, Exception):
            raise self.inquiry_response
        return self.inquiry_response


def seed_user(
    sm: sessionmaker[Session],
    role: Role = Role.student,
    *,
    display_name: str | None = "Sara Ali",
    phone: str | None = "+201234567890",
) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            User(
                id=uid,
                email=f"{uid}@example.com",
                role=role,
                display_name=display_name,
                phone=phone,
            )
        )
    return uid


def seed_pack(
    sm: sessionmaker[Session],
    *,
    code: str | None = None,
    name: str = "100 credits",
    units: int = 100,
    price_minor: int = 10000,
    is_active: bool = True,
) -> uuid.UUID:
    pack_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            CreditPack(
                id=pack_id,
                code=code or f"pack_{pack_id.hex[:8]}",
                name=name,
                units=units,
                price_minor=price_minor,
                currency="EGP",
                is_active=is_active,
            )
        )
    return pack_id


def link_parent(sm: sessionmaker[Session], *, parent_id: uuid.UUID, child_id: uuid.UUID) -> None:
    with sm.begin() as session:
        session.add(ParentChildLink(parent_id=parent_id, child_id=child_id))


def seed_payment(
    sm: sessionmaker[Session],
    *,
    payer: uuid.UUID,
    beneficiary: uuid.UUID,
    pack_id: uuid.UUID,
    amount_minor: int = 10000,
    grant_units: int = 100,
    status: PaymentStatus = PaymentStatus.created,
    created_at: datetime | None = None,
    next_reconcile_at: datetime | None = None,
    paymob_order_id: int | None = None,
    paid_at: datetime | None = None,
) -> uuid.UUID:
    payment_id = uuid.uuid4()
    created = created_at or FIXED_NOW
    with sm.begin() as session:
        payment = Payment(
            id=payment_id,
            payer_user_id=payer,
            beneficiary_user_id=beneficiary,
            purpose=PaymentPurpose.credit_pack,
            credit_pack_id=pack_id,
            grant_units=grant_units,
            amount_minor=amount_minor,
            currency="EGP",
            status=status,
            special_reference=str(payment_id),
            paymob_order_id=paymob_order_id,
            paid_at=paid_at,
            next_reconcile_at=next_reconcile_at or created + timedelta(minutes=15),
        )
        payment.created_at = created
        session.add(payment)
    return payment_id
