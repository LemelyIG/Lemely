"""BillingService checkout, paid-handler registry and the credit-pack grant (spec §5.5, §6)."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from lemely.db.billing_repo import (
    PLACEHOLDER_PHONE,
    BillingService,
    CheckoutUnavailable,
    NotLinkedToBeneficiary,
    UnknownCreditPack,
    UnknownPayer,
    _outcome_unknown,
    add_months,
    billing_data_for,
    grant_credit_pack,
    paid_handler_for,
    register_paid_handler,
)
from lemely.db.models import User
from lemely.db.models.billing import Payment, PaymentPurpose, PaymentStatus
from lemely.db.models.enums import Role
from lemely.db.models.usage import GrantKind, UsageGrant
from lemely.io.paymob.client import PaymobError, PaymobNotConfigured
from lemely.runtime.config import PaymobSettings
from lemely.runtime.token_cipher import TokenCipher, TokenCipherError
from tests.paymob_fixtures import (
    FIXED_NOW,
    INTENTION_RESPONSE,
    PAYMOB_SETTINGS,
    TEST_CARD_TOKEN_KEY,
    FakePaymobClient,
    link_parent,
    seed_pack,
    seed_payment,
    seed_user,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import sessionmaker


def _service(
    session: Session, client: FakePaymobClient, settings: PaymobSettings = PAYMOB_SETTINGS
) -> BillingService:
    return BillingService(session, client, settings, now=lambda: FIXED_NOW)


def test_pack_checkout_inserts_the_payment_and_returns_the_unified_checkout_url(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    payer = seed_user(sm, display_name="Sara Ali")
    pack = seed_pack(sm, name="100 credits", units=100, price_minor=10000)
    client = FakePaymobClient()
    with sm() as session:
        result = _service(session, client).create_pack_checkout(
            payer_user_id=payer, beneficiary_user_id=payer, credit_pack_id=pack
        )
    assert result.checkout_url == (
        "https://eg.checkout.paymob.com/?publicKey=egy_pk_test_public"
        f"&clientSecret={INTENTION_RESPONSE['client_secret']}"
    )
    (body,) = client.intentions
    assert body["amount"] == 10000
    assert body["currency"] == "EGP"
    assert body["payment_methods"] == [4569876]
    assert body["special_reference"] == str(result.payment_id)
    assert body["expiration"] == 3600
    assert body["notification_url"] == "https://lemelyig.com/api/webhooks/paymob/transaction"
    # The SPA route is /billing/return/:paymentId (web/src/routes.tsx). Paymob appends its own
    # ?id=...&hmac=... query to this URL, so ours must carry no query string of its own.
    assert body["redirection_url"] == f"https://lemelyig.com/billing/return/{result.payment_id}"
    assert "?" not in body["redirection_url"]
    assert sum(item["amount"] for item in body["items"]) == body["amount"]
    assert body["billing_data"]["first_name"] == "Sara"
    assert body["billing_data"]["last_name"] == "Ali"
    assert body["billing_data"]["phone_number"] == "+201234567890"
    assert "subscription_plan_id" not in body
    with sm() as session:
        payment = session.get(Payment, result.payment_id)
        assert payment is not None
        assert payment.status is PaymentStatus.created
        assert payment.purpose is PaymentPurpose.credit_pack
        assert payment.payer_user_id == payment.beneficiary_user_id == payer
        assert payment.amount_minor == 10000
        assert payment.grant_units == 100
        assert payment.special_reference == str(payment.id)
        assert payment.paymob_order_id == INTENTION_RESPONSE["intention_order_id"]
        assert payment.paymob_intention_id == INTENTION_RESPONSE["id"]
        assert payment.next_reconcile_at == FIXED_NOW + timedelta(minutes=15)


def test_the_payment_row_is_committed_before_paymob_is_called(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    payer = seed_user(sm)
    pack = seed_pack(sm)
    seen: list[PaymentStatus] = []

    def check(body: dict[str, Any]) -> None:
        with sm() as other:  # a separate connection sees only committed rows
            row = other.get(Payment, uuid.UUID(body["special_reference"]))
            assert row is not None
            seen.append(row.status)

    client = FakePaymobClient()
    client.on_intention = check
    with sm() as session:
        _service(session, client).create_pack_checkout(
            payer_user_id=payer, beneficiary_user_id=payer, credit_pack_id=pack
        )
    assert seen == [PaymentStatus.created]


@pytest.mark.parametrize(
    "error",
    [
        PaymobError("Paymob POST v1/intention/ returned 400", status_code=400),
        PaymobError("Paymob POST v1/intention/ returned 422", status_code=422),
    ],
)
def test_a_definite_paymob_rejection_marks_the_payment_failed_and_never_retries(
    migrated_sessionmaker: sessionmaker[Session], error: PaymobError
) -> None:
    sm = migrated_sessionmaker
    payer = seed_user(sm)
    pack = seed_pack(sm)
    client = FakePaymobClient()
    client.intention_response = error
    with sm() as session, pytest.raises(CheckoutUnavailable):
        _service(session, client).create_pack_checkout(
            payer_user_id=payer, beneficiary_user_id=payer, credit_pack_id=pack
        )
    assert len(client.intentions) == 1
    with sm() as session:
        (payment,) = session.scalars(sa.select(Payment)).all()
        assert payment.status is PaymentStatus.failed
        assert payment.next_reconcile_at is None
        assert payment.last_callback is not None
        assert payment.last_callback["source"] == "create_intention"


@pytest.mark.parametrize(
    "error",
    [
        PaymobError("Paymob POST v1/intention/ timed out", timeout=True),
        PaymobError("Paymob POST v1/intention/ transport error"),
        PaymobError("Paymob POST v1/intention/ returned an unreadable 201", status_code=201),
        PaymobError(
            "Paymob POST v1/intention/ returned 502", status_code=502, outcome_unknown=True
        ),
        PaymobError("Paymob POST v1/intention/ returned 500", status_code=500),
    ],
)
def test_an_unknown_outcome_leaves_the_payment_pending_for_reconciliation(
    migrated_sessionmaker: sessionmaker[Session], error: PaymobError
) -> None:
    """Paymob may have created the order: never read the failure as a decline."""
    sm = migrated_sessionmaker
    payer = seed_user(sm)
    pack = seed_pack(sm)
    client = FakePaymobClient()
    client.intention_response = error
    with sm() as session, pytest.raises(CheckoutUnavailable):
        _service(session, client).create_pack_checkout(
            payer_user_id=payer, beneficiary_user_id=payer, credit_pack_id=pack
        )
    assert len(client.intentions) == 1  # never retried
    with sm() as session:
        (payment,) = session.scalars(sa.select(Payment)).all()
        assert payment.status is PaymentStatus.created
        assert payment.next_reconcile_at == FIXED_NOW + timedelta(minutes=15)
        assert payment.last_callback is not None
        assert payment.last_callback["source"] == "create_intention"
        assert payment.last_callback["outcome_unknown"] is True


def test_a_response_without_a_client_secret_is_a_failure(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    payer = seed_user(sm)
    pack = seed_pack(sm)
    client = FakePaymobClient()
    client.intention_response = {**INTENTION_RESPONSE, "client_secret": None}
    with sm() as session, pytest.raises(CheckoutUnavailable):
        _service(session, client).create_pack_checkout(
            payer_user_id=payer, beneficiary_user_id=payer, credit_pack_id=pack
        )
    with sm() as session:
        assert session.scalars(sa.select(Payment.status)).one() is PaymentStatus.failed


def test_unconfigured_paymob_refuses_before_inserting_anything(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    payer = seed_user(sm)
    pack = seed_pack(sm)
    client = FakePaymobClient()
    with sm() as session, pytest.raises(CheckoutUnavailable):
        _service(session, client, PaymobSettings()).create_pack_checkout(
            payer_user_id=payer, beneficiary_user_id=payer, credit_pack_id=pack
        )
    assert client.intentions == []
    with sm() as session:
        assert session.scalars(sa.select(Payment)).all() == []


def test_unknown_inactive_and_zero_value_packs_are_refused(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    payer = seed_user(sm)
    inactive = seed_pack(sm, is_active=False)
    free = seed_pack(sm, price_minor=0)  # an active zero-price row is still never sold
    empty = seed_pack(sm, units=0)
    client = FakePaymobClient()
    for pack_id in (inactive, free, empty, uuid.uuid4()):
        with sm() as session, pytest.raises(UnknownCreditPack):
            _service(session, client).create_pack_checkout(
                payer_user_id=payer, beneficiary_user_id=payer, credit_pack_id=pack_id
            )
    assert client.intentions == []


def test_the_credit_pack_handler_is_registered_on_import() -> None:
    assert paid_handler_for(PaymentPurpose.credit_pack) is grant_credit_pack


def test_registering_a_second_different_handler_for_a_purpose_is_refused() -> None:
    register_paid_handler(PaymentPurpose.credit_pack, grant_credit_pack)  # same: fine

    def other(session: Session, payment: Payment, obj: Any) -> None:
        raise AssertionError("never called")

    with pytest.raises(ValueError, match="already registered"):
        register_paid_handler(PaymentPurpose.credit_pack, other)
    assert paid_handler_for(PaymentPurpose.credit_pack) is grant_credit_pack


def test_grant_credit_pack_issues_one_visible_grant_expiring_in_twelve_months(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    parent = seed_user(sm, Role.parent)
    child = seed_user(sm)
    pack = seed_pack(sm, units=250)
    paid_at = datetime(2028, 2, 29, 9, 30, tzinfo=UTC)
    payment_id = seed_payment(
        sm,
        payer=parent,
        beneficiary=child,
        pack_id=pack,
        grant_units=250,
        status=PaymentStatus.paid,
        paid_at=paid_at,
    )
    for _ in range(2):  # idempotent on the payment
        with sm.begin() as session:
            payment = session.get(Payment, payment_id)
            assert payment is not None
            grant_credit_pack(session, payment, {})
    with sm() as session:
        (grant,) = session.scalars(
            sa.select(UsageGrant).where(UsageGrant.payment_id == payment_id)
        ).all()
    assert grant.owner_user_id == child
    assert grant.kind is GrantKind.credit_pack
    assert grant.units == 250
    assert grant.visible is True
    assert grant.expires_at == datetime(2029, 2, 28, 9, 30, tzinfo=UTC)


def test_a_duplicate_paid_callback_cannot_double_grant_even_with_a_different_clock(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    payer = seed_user(sm)
    pack = seed_pack(sm, units=40)
    payment_id = seed_payment(
        sm, payer=payer, beneficiary=payer, pack_id=pack, grant_units=40, status=PaymentStatus.paid
    )
    for day in (1, 2, 3):  # a different paid_at (clock) on every call
        with sm.begin() as session:
            payment = session.get(Payment, payment_id)
            assert payment is not None
            payment.paid_at = datetime(2026, 11, day, tzinfo=UTC)
            grant_credit_pack(session, payment, {})
    with sm() as session:
        grants = session.scalars(
            sa.select(UsageGrant).where(UsageGrant.payment_id == payment_id)
        ).all()
    assert len(grants) == 1
    assert grants[0].idempotency_key == f"payment:{payment_id}"


def test_a_grant_credit_pack_without_a_units_snapshot_is_refused(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    payer = seed_user(sm)
    pack = seed_pack(sm)
    payment_id = seed_payment(
        sm, payer=payer, beneficiary=payer, pack_id=pack, status=PaymentStatus.paid
    )
    with sm.begin() as session:
        payment = session.get(Payment, payment_id)
        assert payment is not None
        payment.grant_units = None
        with pytest.raises(RuntimeError, match="grant_units"):
            grant_credit_pack(session, payment, {})


def test_a_linked_parent_may_buy_a_pack_for_their_child(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    parent = seed_user(sm, Role.parent)
    child = seed_user(sm)
    link_parent(sm, parent_id=parent, child_id=child)
    pack = seed_pack(sm)
    with sm() as session:
        result = _service(session, FakePaymobClient()).create_pack_checkout(
            payer_user_id=parent, beneficiary_user_id=child, credit_pack_id=pack
        )
    with sm() as session:
        payment = session.get(Payment, result.payment_id)
        assert payment is not None
        assert (payment.payer_user_id, payment.beneficiary_user_id) == (parent, child)


def test_a_parent_cannot_buy_for_an_unlinked_user(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    parent = seed_user(sm, Role.parent)
    stranger = seed_user(sm)
    other_child = seed_user(sm)
    link_parent(sm, parent_id=parent, child_id=other_child)
    pack = seed_pack(sm)
    client = FakePaymobClient()
    for beneficiary in (stranger, uuid.uuid4()):
        with sm() as session, pytest.raises(NotLinkedToBeneficiary):
            _service(session, client).create_pack_checkout(
                payer_user_id=parent, beneficiary_user_id=beneficiary, credit_pack_id=pack
            )
    assert client.intentions == []
    with sm() as session:
        assert session.scalars(sa.select(Payment)).all() == []


def test_the_link_is_directional_a_child_cannot_buy_for_their_parent(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    parent = seed_user(sm, Role.parent)
    child = seed_user(sm)
    link_parent(sm, parent_id=parent, child_id=child)
    pack = seed_pack(sm)
    with sm() as session, pytest.raises(NotLinkedToBeneficiary):
        _service(session, FakePaymobClient()).create_pack_checkout(
            payer_user_id=child, beneficiary_user_id=parent, credit_pack_id=pack
        )


def test_the_price_comes_from_the_catalogue_not_the_caller(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    payer = seed_user(sm)
    pack = seed_pack(sm, units=75, price_minor=7500)
    client = FakePaymobClient()
    with sm() as session:
        _service(session, client).create_pack_checkout(
            payer_user_id=payer, beneficiary_user_id=payer, credit_pack_id=pack
        )
    with sm() as session:
        payment = session.scalars(sa.select(Payment)).one()
        assert (payment.amount_minor, payment.grant_units) == (7500, 75)
    assert client.intentions[0]["amount"] == 7500


def test_a_malformed_card_token_key_fails_only_when_the_cipher_is_used(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    payer = seed_user(sm)
    pack = seed_pack(sm)
    bad = PaymobSettings.model_validate(
        {
            "secret_key": "egy_sk_test_secret",
            "public_key": "egy_pk_test_public",
            "api_key": "api_key_test",
            "hmac_secret": "test_hmac_secret_0123456789abcdef",
            "card_integration_id": 4569876,
            "card_token_key": "not-a-key",
        }
    )
    client = FakePaymobClient()
    with sm() as session:
        service = _service(session, client, bad)  # construction does not raise
        service.create_pack_checkout(  # checkout never touches the cipher
            payer_user_id=payer, beneficiary_user_id=payer, credit_pack_id=pack
        )
        with pytest.raises(TokenCipherError):
            service.cipher  # noqa: B018


def test_the_cipher_is_built_once_from_the_configured_key_or_injected() -> None:
    with Session() as session:  # unbound: the cipher never touches the database
        service = BillingService(session, FakePaymobClient(), PAYMOB_SETTINGS)
        assert service.cipher is not None
        assert service.cipher is service.cipher
        injected = TokenCipher(TEST_CARD_TOKEN_KEY)
        keyed = BillingService(session, FakePaymobClient(), PAYMOB_SETTINGS, cipher=injected)
        assert keyed.cipher is injected
        assert BillingService(session, FakePaymobClient(), PaymobSettings()).cipher is None


@pytest.mark.parametrize(
    ("moment", "months", "expected"),
    [
        (datetime(2026, 11, 5, tzinfo=UTC), 12, datetime(2027, 11, 5, tzinfo=UTC)),
        (datetime(2028, 2, 29, tzinfo=UTC), 12, datetime(2029, 2, 28, tzinfo=UTC)),
        (datetime(2026, 1, 31, tzinfo=UTC), 1, datetime(2026, 2, 28, tzinfo=UTC)),
        (datetime(2026, 12, 15, tzinfo=UTC), 1, datetime(2027, 1, 15, tzinfo=UTC)),
    ],
)
def test_add_months_clamps_to_the_last_day(
    moment: datetime, months: int, expected: datetime
) -> None:
    assert add_months(moment, months) == expected


def test_billing_data_falls_back_when_the_profile_is_sparse() -> None:
    user = User(
        id=uuid.uuid4(), email="x@example.com", role=Role.teacher, display_name=None, phone=None
    )
    data = billing_data_for(user)
    assert data["first_name"] == "Lemely"
    assert data["last_name"] == "Customer"
    assert data["email"] == "x@example.com"
    assert data["phone_number"] == PLACEHOLDER_PHONE
    assert data["phone_number"] != "NA"
    assert data["country"] == "EGY"


def _user_with_phone(phone: str | None) -> User:
    return User(id=uuid.uuid4(), email="p@example.com", role=Role.student, phone=phone)


def test_the_placeholder_phone_is_a_well_formed_e164_number() -> None:
    assert re.fullmatch(r"\+[1-9]\d{7,14}", PLACEHOLDER_PHONE)


@pytest.mark.parametrize(
    ("stored", "sent"),
    [
        ("+201234567890", "+201234567890"),
        ("+20 123 456 7890", "+201234567890"),
        ("+20-123-456-7890", "+201234567890"),
        ("01012345678", "+201012345678"),
        ("010 1234 5678", "+201012345678"),
        ("00201012345678", "+201012345678"),
        ("201012345678", "+201012345678"),
        ("(+20) 101 234 5678", "+201012345678"),
        ("+447911123456", "+447911123456"),
        # the trunk 0 typed after the country code, a very common Egyptian entry
        ("+2001012345678", "+201012345678"),
        ("002001012345678", "+201012345678"),
        ("+20 (0)101 234 5678", "+201012345678"),
        # the leading 0 of a local mobile dropped
        ("1012345678", "+201012345678"),
        # Arabic-Indic and Persian digits, whole or mixed with ASCII
        ("\u0660\u0661\u0660\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668", "+201012345678"),
        ("+20\u0661\u0660\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668", "+20" + "1012345678"),
        ("\u06f0\u06f1\u06f0\u06f1\u06f2\u06f3\u06f4\u06f5\u06f6\u06f7\u06f8", "+201012345678"),
    ],
)
def test_a_phone_on_file_is_sent_in_e164_form(stored: str, sent: str) -> None:
    assert billing_data_for(_user_with_phone(stored))["phone_number"] == sent


def test_a_sent_phone_is_ascii_only() -> None:
    sent = billing_data_for(
        _user_with_phone("+20\u0661\u0660\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668")
    )
    assert sent["phone_number"].isascii()


@pytest.mark.parametrize(
    "stored",
    [
        None,
        "",
        "   ",
        "NA",
        "call me",
        "12345",
        "+0123456789",
        "0130000000",
        "+2001",
        "+20\u0e51\u0e50",
        # ten Thai digits: \d matches them, but only ASCII digits may be sent
        "+20\u0e51\u0e50\u0e51\u0e52\u0e53\u0e54\u0e55\u0e56\u0e57\u0e58",
    ],
)
def test_a_missing_or_unusable_phone_sends_the_placeholder_never_na(stored: str | None) -> None:
    assert billing_data_for(_user_with_phone(stored))["phone_number"] == PLACEHOLDER_PHONE


def test_billing_data_truncates_long_names_to_paymobs_limit() -> None:
    user = User(
        id=uuid.uuid4(),
        email="y@example.com",
        role=Role.student,
        display_name="A" * 80 + " " + "B" * 80,
    )
    data = billing_data_for(user)
    assert len(data["first_name"]) == 50
    assert len(data["last_name"]) == 50


def test_grant_credit_pack_never_falls_back_to_the_wall_clock(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    payer = seed_user(sm)
    pack = seed_pack(sm)
    payment_id = seed_payment(
        sm, payer=payer, beneficiary=payer, pack_id=pack, status=PaymentStatus.paid
    )  # paid_at unset: the service sets it from its injected clock before the handler runs
    with sm.begin() as session:
        payment = session.get(Payment, payment_id)
        assert payment is not None
        with pytest.raises(RuntimeError, match="paid_at"):
            grant_credit_pack(session, payment, {})
    with sm() as session:
        assert session.scalars(sa.select(UsageGrant)).all() == []


def test_a_paymob_not_configured_error_is_a_known_nothing_happened() -> None:
    assert _outcome_unknown(PaymobNotConfigured("no secret key")) is False
    assert _outcome_unknown(PaymobError("timeout", timeout=True)) is True
    assert _outcome_unknown(PaymobError("transport")) is True
    assert _outcome_unknown(PaymobError("400", status_code=400)) is False
    assert _outcome_unknown(PaymobError("500", status_code=500)) is True
    assert _outcome_unknown(PaymobError("201", status_code=201)) is True
    assert _outcome_unknown(PaymobError("flagged", status_code=400, outcome_unknown=True)) is True


def test_paymob_not_configured_during_checkout_fails_the_payment(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    payer = seed_user(sm)
    pack = seed_pack(sm)
    client = FakePaymobClient()
    client.intention_response = PaymobNotConfigured("no secret key")
    with sm() as session, pytest.raises(CheckoutUnavailable):
        _service(session, client).create_pack_checkout(
            payer_user_id=payer, beneficiary_user_id=payer, credit_pack_id=pack
        )
    with sm() as session:
        (payment,) = session.scalars(sa.select(Payment)).all()
        assert payment.status is PaymentStatus.failed
        assert payment.next_reconcile_at is None


def test_a_missing_client_secret_keeps_paymobs_intention_and_order_ids(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    payer = seed_user(sm)
    pack = seed_pack(sm)
    client = FakePaymobClient()
    client.intention_response = {**INTENTION_RESPONSE, "client_secret": None}
    with sm() as session, pytest.raises(CheckoutUnavailable):
        _service(session, client).create_pack_checkout(
            payer_user_id=payer, beneficiary_user_id=payer, credit_pack_id=pack
        )
    with sm() as session:
        (payment,) = session.scalars(sa.select(Payment)).all()
    assert payment.status is PaymentStatus.failed
    assert payment.paymob_intention_id == str(INTENTION_RESPONSE["id"])
    assert payment.paymob_order_id == INTENTION_RESPONSE["intention_order_id"]


def test_checkout_items_must_add_up_to_the_payment_amount_before_anything_is_committed(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    payer = seed_user(sm)
    pack = seed_pack(sm)
    payment_id = uuid.uuid4()
    client = FakePaymobClient()
    with sm() as session:
        payment = Payment(
            id=payment_id,
            payer_user_id=payer,
            beneficiary_user_id=payer,
            purpose=PaymentPurpose.credit_pack,
            credit_pack_id=pack,
            grant_units=100,
            amount_minor=10000,
            currency="EGP",
            status=PaymentStatus.created,
            special_reference=str(payment_id),
        )
        items = [
            {"name": "a", "amount": 6000, "quantity": 1},
            {"name": "b", "amount": 3999, "quantity": 1},
        ]
        with pytest.raises(ValueError, match="10000"):
            _service(session, client).create_intention_checkout(
                payment=payment,
                items=items,
                billing_data={},
                subscription_plan_id=None,
            )
    assert client.intentions == []
    with sm() as session:
        assert session.scalars(sa.select(Payment)).all() == []


@pytest.mark.parametrize("quantity", [2, 0, "1", True, 1.0])
def test_checkout_items_with_a_quantity_other_than_one_are_refused(
    migrated_sessionmaker: sessionmaker[Session], quantity: object
) -> None:
    sm = migrated_sessionmaker
    payer = seed_user(sm)
    pack = seed_pack(sm)
    payment_id = uuid.uuid4()
    client = FakePaymobClient()
    with sm() as session:
        payment = Payment(
            id=payment_id,
            payer_user_id=payer,
            beneficiary_user_id=payer,
            purpose=PaymentPurpose.credit_pack,
            credit_pack_id=pack,
            grant_units=100,
            amount_minor=10000,
            currency="EGP",
            status=PaymentStatus.created,
            special_reference=str(payment_id),
        )
        with pytest.raises(ValueError, match="quantity"):
            _service(session, client).create_intention_checkout(
                payment=payment,
                items=[{"name": "a", "amount": 10000, "quantity": quantity}],
                billing_data={},
                subscription_plan_id=None,
            )
    assert client.intentions == []
    with sm() as session:
        assert session.scalars(sa.select(Payment)).all() == []


# -- who may buy for whom (review of ee61001c) -----------------------------------------


def test_a_parent_cannot_buy_a_pack_for_themselves(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """The rule lives in the service so every later purchase path inherits it."""
    sm = migrated_sessionmaker
    parent = seed_user(sm, Role.parent)
    link_parent(sm, parent_id=parent, child_id=seed_user(sm))  # even a parent with a child
    pack = seed_pack(sm)
    client = FakePaymobClient()
    with sm() as session, pytest.raises(NotLinkedToBeneficiary):
        _service(session, client).create_pack_checkout(
            payer_user_id=parent, beneficiary_user_id=parent, credit_pack_id=pack
        )
    assert client.intentions == []
    with sm() as session:
        assert session.scalars(sa.select(Payment)).all() == []


@pytest.mark.parametrize("role", [Role.teacher, Role.parent])
def test_a_link_to_a_non_student_does_not_let_a_parent_buy(
    migrated_sessionmaker: sessionmaker[Session], role: Role
) -> None:
    sm = migrated_sessionmaker
    parent = seed_user(sm, Role.parent)
    other = seed_user(sm, role)
    link_parent(sm, parent_id=parent, child_id=other)
    client = FakePaymobClient()
    with sm() as session, pytest.raises(NotLinkedToBeneficiary):
        _service(session, client).create_pack_checkout(
            payer_user_id=parent, beneficiary_user_id=other, credit_pack_id=seed_pack(sm)
        )
    assert client.intentions == []
    with sm() as session:
        assert session.scalars(sa.select(Payment)).all() == []


def test_a_payer_without_a_users_row_is_a_specific_error(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    ghost = uuid.uuid4()
    client = FakePaymobClient()
    with sm() as session, pytest.raises(UnknownPayer):
        _service(session, client).create_pack_checkout(
            payer_user_id=ghost, beneficiary_user_id=ghost, credit_pack_id=seed_pack(sm)
        )
    assert client.intentions == []
