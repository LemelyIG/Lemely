"""MerchantChargeService.charge_saved_card and the queued-charge helpers (Phase 06 T3).

Money safety, in the order the service enforces it: the payment row is committed ``pending``
before Paymob is called and no row lock is held across a call; an unknown outcome stays
``pending`` for reconcile and is never inquired, retried or failed in line; a received 4xx is
definite and fails the row; a refusal before the claim leaves nothing behind; and only a verified
callback or reconcile inquiry pays. Every guard here has a mutation proof in the task report.

Runs on a throwaway Postgres database (``create_all``); skips without a local Postgres.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
import sqlalchemy as sa
from structlog.testing import capture_logs

from lemely.db import billing_repo, merchant_charge_repo
from lemely.db.billing_repo import (
    RECONCILE_AFTER,
    BillingService,
    PhoneRequired,
    saved_cards_for,
)
from lemely.db.merchant_charge_repo import (
    FAILED_STATUSES,
    IN_FLIGHT_STATUSES,
    ChargeAlreadyAttempted,
    ChargesUnavailable,
    MerchantChargeError,
    MerchantChargeService,
    charge_queued_payments,
    charges_configured,
    fail_unsent,
    insert_queued_payment,
)
from lemely.db.models.billing import (
    Payment,
    PaymentPurpose,
    PaymentStatus,
    PaymobEvent,
    SavedCard,
)
from lemely.db.models.enums import Role
from lemely.io.paymob.client import PaymobError, PaymobNotConfigured
from tests.merchant_charge_fixtures import (
    FakeMotoClient,
    moto_txn,
    paymob_settings,
    seed_payment_row,
    seed_saved_card,
    seed_user,
    throwaway_database,
)
from tests.paymob_fixtures import (
    CARD_INTEGRATION_ID,
    MOTO_INTEGRATION_ID,
    PAYMOB_SETTINGS,
    TEST_CARD_TOKEN_KEY,
    FakePaymobClient,
    transaction_obj,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

    from lemely.runtime.config import PaymobSettings

NOW = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
TOKEN = "tok_card_1"


@pytest.fixture(scope="module")
def pg_sessionmaker() -> Iterator[sessionmaker[Session]]:
    with throwaway_database() as factory:
        yield factory


@pytest.fixture
def clean_queue(pg_sessionmaker: sessionmaker[Session]) -> None:
    """Drop queued rows other tests left ``created``: the sweep takes every row of its prefix."""
    with pg_sessionmaker.begin() as session:
        session.execute(
            sa.delete(Payment).where(
                Payment.status == PaymentStatus.created, Payment.dedupe_key.is_not(None)
            )
        )


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def _payer(sm: sessionmaker[Session], **user: Any) -> tuple[uuid.UUID, uuid.UUID]:
    """A payer and one active saved card (token ``TOKEN``)."""
    payer = seed_user(sm, Role.student, **user)
    return payer, seed_saved_card(sm, payer, token=TOKEN)


def _dedupe_key(purpose: PaymentPurpose) -> str:
    prefix = {
        PaymentPurpose.auto_topup: "auto_topup",
        PaymentPurpose.extra_seats: "extra_seat_renewal",
    }[purpose]
    return f"{prefix}:{uuid.uuid4()}:1"


def _charge(
    sm: sessionmaker[Session],
    client: FakeMotoClient,
    *,
    payer: uuid.UUID,
    card_id: uuid.UUID,
    settings: PaymobSettings = PAYMOB_SETTINGS,
    purpose: PaymentPurpose = PaymentPurpose.auto_topup,
    amount: int = 10_000,
    keyed: bool = True,
    now: datetime = NOW,
) -> uuid.UUID:
    """Create a payment and charge it the way a sweeper job does; a refusal rolls it back.

    The dedupe key carries the prefix 0056's CHECK pairs with ``purpose``. ``keyed=False`` makes
    a checkout-style payment (no key), which the service must refuse to charge.
    """
    with sm() as session:
        service = MerchantChargeService(session, client, settings)
        payment = service.new_payment(
            purpose=purpose,
            payer_user_id=payer,
            beneficiary_user_id=payer,
            amount_minor=amount,
            currency="EGP",
            dedupe_key=_dedupe_key(purpose) if keyed else None,
        )
        payment_id = payment.id
        card = session.get(SavedCard, card_id)
        assert card is not None
        try:
            service.charge_saved_card(payment, card, now=now)
        except Exception:
            session.rollback()
            raise
    return payment_id


def _row(sm: sessionmaker[Session], payment_id: uuid.UUID) -> Payment:
    with sm() as session:
        payment = session.get(Payment, payment_id)
        assert payment is not None
        session.expunge(payment)
        return payment


def _count(sm: sessionmaker[Session], payer: uuid.UUID) -> int:
    with sm() as session:
        return (
            session.scalar(
                sa.select(sa.func.count())
                .select_from(Payment)
                .where(Payment.payer_user_id == payer)
            )
            or 0
        )


def _ciphertext(sm: sessionmaker[Session], card_id: uuid.UUID) -> str:
    with sm() as session:
        card = session.get(SavedCard, card_id)
        assert card is not None
        return card.token


def _no_inquiry(client: FakeMotoClient) -> None:
    assert client.inquiries == []
    assert client.calls_to("inquire_by_order_ref") == []


# ---------------------------------------------------------------------------
# Record first, no lock across a call (money safety 1 and 2).
# ---------------------------------------------------------------------------


def test_record_first_the_row_is_pending_and_unlocked_while_paymob_is_called(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    client = FakeMotoClient(sessionmaker=pg_sessionmaker)
    payer, card = _payer(pg_sessionmaker)
    _charge(pg_sessionmaker, client, payer=payer, card_id=card)
    # Seen from another session at the moment of each Paymob call: committed as ``pending``
    # (the claim) and not locked (``FOR UPDATE NOWAIT`` succeeded).
    assert client.at_intention == [{"status": PaymentStatus.pending, "lock_free": True}]
    assert client.at_pay == [{"status": PaymentStatus.pending, "lock_free": True}]


# ---------------------------------------------------------------------------
# The request Paymob sees.
# ---------------------------------------------------------------------------


def test_intention_body_is_moto_only_and_pay_gets_the_decrypted_token(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    client = FakeMotoClient()
    payer, card = _payer(pg_sessionmaker)
    payment_id = _charge(pg_sessionmaker, client, payer=payer, card_id=card, amount=12_345)
    (body,) = client.calls_to("create_intention")
    assert body["payment_methods"] == [MOTO_INTEGRATION_ID]
    assert body["amount"] == 12_345
    assert body["currency"] == "EGP"
    assert body["special_reference"] == str(payment_id)
    assert body["notification_url"] == (
        f"{PAYMOB_SETTINGS.notification_base_url}/api/webhooks/paymob/transaction"
    )
    assert body["expiration"] == 3600
    assert body["extras"] == {"payment_id": str(payment_id), "purpose": "auto_topup"}
    assert "redirection_url" not in body
    assert body["billing_data"]["phone_number"] == "+201234567890"
    assert {"first_name", "last_name", "email", "phone_number", "country"} <= set(
        body["billing_data"]
    )
    (item,) = body["items"]
    assert item["quantity"] == 1
    assert item["amount"] == 12_345
    assert 0 < len(item["name"]) <= 50
    assert "payment_keys" not in body

    (pay,) = client.calls_to("pay_with_token")
    assert pay["card_token"] == TOKEN
    assert pay["card_token"] != _ciphertext(pg_sessionmaker, card)
    assert pay["payment_token"] == client.intention_response["payment_keys"][0]["key"]


def test_accepted_charge_stays_pending_with_the_paymob_ids_stored(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    client = FakeMotoClient()
    payer, card = _payer(pg_sessionmaker)
    payment_id = _charge(pg_sessionmaker, client, payer=payer, card_id=card)
    row = _row(pg_sessionmaker, payment_id)
    assert row.status is PaymentStatus.pending
    assert row.method == "card_moto"
    assert row.paymob_order_id is not None
    assert row.paymob_intention_id is not None
    assert row.paymob_intention_id.startswith("pi_test_moto_")
    assert row.next_reconcile_at == NOW + RECONCILE_AFTER
    assert row.paid_at is None


def test_pending_answer_is_accepted_and_waits_for_the_callback(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    client = FakeMotoClient()
    client.pay_response = {"id": 5, "success": False, "pending": True}
    payer, card = _payer(pg_sessionmaker)
    payment_id = _charge(pg_sessionmaker, client, payer=payer, card_id=card)
    assert _row(pg_sessionmaker, payment_id).status is PaymentStatus.pending


# ---------------------------------------------------------------------------
# Declines.
# ---------------------------------------------------------------------------


def test_decline_fails_the_payment(pg_sessionmaker: sessionmaker[Session]) -> None:
    client = FakeMotoClient()
    client.pay_response = {"id": 9, "success": False, "pending": False}
    payer, card = _payer(pg_sessionmaker)
    payment_id = _charge(pg_sessionmaker, client, payer=payer, card_id=card)
    row = _row(pg_sessionmaker, payment_id)
    assert row.status is PaymentStatus.failed
    assert row.next_reconcile_at is None


def test_late_decline_never_overwrites_a_paid_callback(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    client = FakeMotoClient()
    client.pay_response = {"id": 9, "success": False, "pending": False}

    def callback_wins(_call: dict[str, Any]) -> None:
        reference = client.calls_to("create_intention")[0]["special_reference"]
        with pg_sessionmaker.begin() as session:
            session.execute(
                sa.update(Payment)
                .where(Payment.special_reference == reference)
                .values(status=PaymentStatus.paid, paid_at=NOW)
            )

    client.on_pay = callback_wins
    payer, card = _payer(pg_sessionmaker)
    payment_id = _charge(pg_sessionmaker, client, payer=payer, card_id=card)
    assert _row(pg_sessionmaker, payment_id).status is PaymentStatus.paid


# ---------------------------------------------------------------------------
# Unknown outcomes stay pending for reconcile: zero inquiries, one write at most.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "scripted",
    [
        PaymobError("pay timed out", timeout=True),
        PaymobError("pay gateway error", status_code=503, outcome_unknown=True),
        PaymobError("pay gateway error without the flag", status_code=502),
        {},
        {"id": 1},
        {"id": 1, "success": False},
        {"id": 1, "success": "false", "pending": "false"},
        {"id": 1, "success": None, "pending": None},
    ],
    ids=["timeout", "503", "502-unflagged", "empty", "no-flags", "no-pending", "strings", "nulls"],
)
def test_unknown_pay_outcome_stays_pending_for_reconcile(
    pg_sessionmaker: sessionmaker[Session], scripted: Any
) -> None:
    client = FakeMotoClient()
    client.pay_response = scripted
    payer, card = _payer(pg_sessionmaker)
    payment_id = _charge(pg_sessionmaker, client, payer=payer, card_id=card)
    row = _row(pg_sessionmaker, payment_id)
    assert row.status is PaymentStatus.pending
    assert row.next_reconcile_at is not None
    assert row.next_reconcile_at <= NOW
    assert len(client.calls_to("pay_with_token")) == 1
    _no_inquiry(client)


@pytest.mark.parametrize(
    "scripted",
    [
        PaymobError("intention timed out", timeout=True),
        PaymobError("intention gateway error", status_code=503, outcome_unknown=True),
        PaymobError("intention gateway error without the flag", status_code=500),
    ],
    ids=["timeout", "503", "500-unflagged"],
)
def test_unknown_intention_outcome_stays_pending_and_never_pays(
    pg_sessionmaker: sessionmaker[Session], scripted: Exception
) -> None:
    client = FakeMotoClient()
    client.intention_response = scripted
    payer, card = _payer(pg_sessionmaker)
    payment_id = _charge(pg_sessionmaker, client, payer=payer, card_id=card)
    row = _row(pg_sessionmaker, payment_id)
    assert row.status is PaymentStatus.pending
    assert row.next_reconcile_at is not None
    assert row.next_reconcile_at <= NOW
    assert row.last_callback is not None
    assert row.last_callback["outcome_unknown"] is True
    assert client.calls_to("pay_with_token") == []
    assert len(client.calls_to("create_intention")) == 1
    _no_inquiry(client)


# ---------------------------------------------------------------------------
# Definite outcomes fail the row.
# ---------------------------------------------------------------------------


def test_pay_4xx_is_definite_and_fails_the_payment(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    client = FakeMotoClient()
    client.pay_response = PaymobError("bad request", status_code=400)
    payer, card = _payer(pg_sessionmaker)
    payment_id = _charge(pg_sessionmaker, client, payer=payer, card_id=card)
    row = _row(pg_sessionmaker, payment_id)
    assert row.status is PaymentStatus.failed
    assert row.next_reconcile_at is None
    assert len(client.calls_to("pay_with_token")) == 1
    _no_inquiry(client)


def test_intention_4xx_is_definite_and_never_pays(pg_sessionmaker: sessionmaker[Session]) -> None:
    client = FakeMotoClient()
    client.intention_response = PaymobError("bad request", status_code=400)
    payer, card = _payer(pg_sessionmaker)
    payment_id = _charge(pg_sessionmaker, client, payer=payer, card_id=card)
    row = _row(pg_sessionmaker, payment_id)
    assert row.status is PaymentStatus.failed
    assert row.next_reconcile_at is None
    assert client.calls_to("pay_with_token") == []
    _no_inquiry(client)


def test_a_client_refusal_after_the_claim_fails_the_row_and_never_pays(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    # The client's own key-mode / credential refusal: raised before anything was sent, so the
    # outcome is known and the row is failed, not left for reconcile.
    client = FakeMotoClient()
    client.intention_response = PaymobNotConfigured("keys in different modes")
    payer, card = _payer(pg_sessionmaker)
    payment_id = _charge(pg_sessionmaker, client, payer=payer, card_id=card)
    assert _row(pg_sessionmaker, payment_id).status is PaymentStatus.failed
    assert client.calls_to("pay_with_token") == []


@pytest.mark.parametrize(
    "response",
    [
        {"id": "pi_x", "intention_order_id": 4_000_001, "payment_keys": []},
        {"id": "pi_x", "intention_order_id": 4_000_002},
        {"id": "pi_x", "intention_order_id": 4_000_003, "payment_keys": [{"key": ""}]},
        {"id": "pi_x", "intention_order_id": 4_000_004, "payment_keys": [{"key": 7}]},
    ],
    ids=["empty-keys", "no-keys", "blank-key", "non-string-key"],
)
def test_intention_without_a_payment_key_fails_and_never_pays(
    pg_sessionmaker: sessionmaker[Session], response: dict[str, Any]
) -> None:
    client = FakeMotoClient()
    client.fresh_ids = False
    client.intention_response = response
    payer, card = _payer(pg_sessionmaker)
    payment_id = _charge(pg_sessionmaker, client, payer=payer, card_id=card)
    row = _row(pg_sessionmaker, payment_id)
    assert row.status is PaymentStatus.failed
    assert row.paymob_order_id == response["intention_order_id"]  # kept for support
    assert client.calls_to("pay_with_token") == []


# ---------------------------------------------------------------------------
# Refusals before the claim: nothing committed, nothing sent.
# ---------------------------------------------------------------------------


def _assert_refused_cleanly(
    sm: sessionmaker[Session], client: FakeMotoClient, payer: uuid.UUID
) -> None:
    assert _count(sm, payer) == 0
    assert client.calls == []


def test_another_users_card_is_refused(pg_sessionmaker: sessionmaker[Session]) -> None:
    client = FakeMotoClient()
    payer, _own = _payer(pg_sessionmaker)
    other, other_card = _payer(pg_sessionmaker)
    with pytest.raises(MerchantChargeError) as raised:
        _charge(pg_sessionmaker, client, payer=payer, card_id=other_card)
    assert raised.value.code == "no_saved_card"
    _assert_refused_cleanly(pg_sessionmaker, client, payer)
    assert _count(pg_sessionmaker, other) == 0


def test_an_inactive_card_is_refused(pg_sessionmaker: sessionmaker[Session]) -> None:
    client = FakeMotoClient()
    payer = seed_user(pg_sessionmaker, Role.student)
    card = seed_saved_card(pg_sessionmaker, payer, is_active=False)
    with pytest.raises(MerchantChargeError) as raised:
        _charge(pg_sessionmaker, client, payer=payer, card_id=card)
    assert raised.value.code == "no_saved_card"
    _assert_refused_cleanly(pg_sessionmaker, client, payer)


def test_a_ciphertext_copied_from_another_users_row_is_refused(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    # R22: the token opens only for the row's own user, so a ciphertext moved onto another
    # user's card row decrypts to an error, never to the first user's card.
    client = FakeMotoClient()
    _victim, victim_card = _payer(pg_sessionmaker)
    payer, card = _payer(pg_sessionmaker)
    stolen = _ciphertext(pg_sessionmaker, victim_card)
    with pg_sessionmaker.begin() as session:
        session.execute(sa.update(SavedCard).where(SavedCard.id == card).values(token=stolen))
    with pytest.raises(MerchantChargeError) as raised:
        _charge(pg_sessionmaker, client, payer=payer, card_id=card)
    assert raised.value.code == "no_saved_card"
    _assert_refused_cleanly(pg_sessionmaker, client, payer)


@pytest.mark.parametrize(
    "settings",
    [
        paymob_settings(moto_integration_id=None),
        paymob_settings(card_token_key=None),
        # Public and secret keys in different modes: checkout is not configured.
        paymob_settings(secret_key="egy_sk_test_one", public_key="egy_pk_live_two"),
    ],
    ids=["no-moto-id", "no-token-key", "key-mode-mismatch"],
)
def test_an_unconfigured_or_mismatched_account_is_refused(
    pg_sessionmaker: sessionmaker[Session], settings: PaymobSettings
) -> None:
    assert not charges_configured(settings)
    client = FakeMotoClient(settings)
    payer, card = _payer(pg_sessionmaker)
    with pytest.raises(ChargesUnavailable) as raised:
        _charge(pg_sessionmaker, client, payer=payer, card_id=card, settings=settings)
    assert raised.value.code == "payments_unavailable"
    _assert_refused_cleanly(pg_sessionmaker, client, payer)


def test_a_payer_without_a_phone_is_refused(pg_sessionmaker: sessionmaker[Session]) -> None:
    client = FakeMotoClient()
    payer, card = _payer(pg_sessionmaker, phone=None)
    with pytest.raises(PhoneRequired):
        _charge(pg_sessionmaker, client, payer=payer, card_id=card)
    _assert_refused_cleanly(pg_sessionmaker, client, payer)


def test_the_configured_account_passes_charges_configured() -> None:
    assert charges_configured(PAYMOB_SETTINGS)


# ---------------------------------------------------------------------------
# One charge per payment.
# ---------------------------------------------------------------------------


def test_a_second_charge_of_the_same_payment_calls_nothing(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    client = FakeMotoClient()
    payer, card = _payer(pg_sessionmaker)
    payment_id = _charge(pg_sessionmaker, client, payer=payer, card_id=card)
    with pg_sessionmaker() as session:
        payment = session.get(Payment, payment_id)
        card_row = session.get(SavedCard, card)
        assert payment is not None
        assert card_row is not None
        with pytest.raises(ChargeAlreadyAttempted):
            MerchantChargeService(session, client, PAYMOB_SETTINGS).charge_saved_card(
                payment, card_row, now=NOW
            )
    assert len(client.calls_to("create_intention")) == 1
    assert len(client.calls_to("pay_with_token")) == 1


def test_a_stale_created_row_loses_the_claim_to_another_worker(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    # Worker B loaded the payment while it was still ``created``; worker A then claimed and
    # charged it. B's in-memory row still says ``created``: only the conditional UPDATE refuses it.
    client_a, client_b = FakeMotoClient(), FakeMotoClient()
    payer, card = _payer(pg_sessionmaker)
    with pg_sessionmaker() as session_b:
        with pg_sessionmaker.begin() as setup:
            payment = MerchantChargeService(setup, client_a, PAYMOB_SETTINGS).new_payment(
                purpose=PaymentPurpose.auto_topup,
                payer_user_id=payer,
                beneficiary_user_id=payer,
                amount_minor=10_000,
                currency="EGP",
                dedupe_key=f"auto_topup:{uuid.uuid4()}:1",
            )
            payment_id = payment.id
        stale = session_b.get(Payment, payment_id)
        card_b = session_b.get(SavedCard, card)
        assert stale is not None
        assert card_b is not None
        assert stale.status is PaymentStatus.created
        with pg_sessionmaker() as session_a:
            row_a = session_a.get(Payment, payment_id)
            card_a = session_a.get(SavedCard, card)
            assert row_a is not None
            assert card_a is not None
            MerchantChargeService(session_a, client_a, PAYMOB_SETTINGS).charge_saved_card(
                row_a, card_a, now=NOW
            )
        with pytest.raises(ChargeAlreadyAttempted):
            MerchantChargeService(session_b, client_b, PAYMOB_SETTINGS).charge_saved_card(
                stale, card_b, now=NOW
            )
    assert len(client_a.calls_to("pay_with_token")) == 1
    assert client_b.calls == []


# ---------------------------------------------------------------------------
# Only a verified callback or reconcile inquiry pays, exactly once.
# ---------------------------------------------------------------------------


@pytest.fixture
def paid_calls(monkeypatch: pytest.MonkeyPatch) -> list[uuid.UUID]:
    """Stand in for auto top-up's paid handler (T8 registers the real one at import time).

    ``monkeypatch.setitem`` on the registry rather than ``register_paid_handler``: it is undone
    after the test, so it can neither outlive it nor collide with T8's import-time registration
    (``register_paid_handler`` refuses a second, different handler). Each call is one effect.
    """
    calls: list[uuid.UUID] = []

    def handler(_session: Session, payment: Payment, _obj: Any) -> None:
        assert payment.paid_at == NOW  # set from the service clock before the handler runs
        calls.append(payment.id)

    monkeypatch.setitem(billing_repo._PAID_HANDLERS, PaymentPurpose.auto_topup, handler)
    return calls


def _charged_topup(sm: sessionmaker[Session], client: FakeMotoClient) -> tuple[uuid.UUID, Payment]:
    payer = seed_user(sm, Role.student)
    card = seed_saved_card(sm, payer, token=TOKEN)
    payment_id = _charge(sm, client, payer=payer, card_id=card)
    return payment_id, _row(sm, payment_id)


def _deliver(sm: sessionmaker[Session], obj: dict[str, Any]) -> None:
    with sm.begin() as session:
        BillingService(
            session, FakePaymobClient(), PAYMOB_SETTINGS, now=lambda: NOW
        ).apply_transaction_callback(obj)


def _reconcile(sm: sessionmaker[Session], obj: dict[str, Any] | None) -> int:
    inquirer = FakePaymobClient()
    inquirer.inquiry_response = obj
    with sm() as session:
        return BillingService(
            session, inquirer, PAYMOB_SETTINGS, now=lambda: NOW
        ).reconcile_pending(now=NOW + timedelta(minutes=20))


def _paid_once(
    sm: sessionmaker[Session], paid: list[uuid.UUID], payment_id: uuid.UUID, txn: int
) -> None:
    row = _row(sm, payment_id)
    assert row.status is PaymentStatus.paid
    assert row.paid_at == NOW
    assert row.paymob_txn_id == txn
    assert paid == [payment_id]  # the paid handler ran once
    with sm() as session:
        events = session.scalar(
            sa.select(sa.func.count())
            .select_from(PaymobEvent)
            .where(PaymobEvent.dedupe_key.like(f"txn:{txn}:%"))
        )
    assert events == 1


def test_callback_twice_then_reconcile_pays_and_runs_the_handler_once(
    pg_sessionmaker: sessionmaker[Session], paid_calls: list[uuid.UUID]
) -> None:
    client = FakeMotoClient()
    payment_id, row = _charged_topup(pg_sessionmaker, client)
    assert row.status is PaymentStatus.pending
    assert row.paymob_order_id is not None
    obj = moto_txn(
        order_id=row.paymob_order_id,
        merchant_order_id=row.special_reference,
        amount_cents=row.amount_minor,
        txn_id=777_001,
    )
    _deliver(pg_sessionmaker, obj)
    _deliver(pg_sessionmaker, obj)
    _reconcile(pg_sessionmaker, obj)
    _paid_once(pg_sessionmaker, paid_calls, payment_id, 777_001)


def test_reconcile_then_callback_twice_pays_and_runs_the_handler_once(
    pg_sessionmaker: sessionmaker[Session], paid_calls: list[uuid.UUID]
) -> None:
    client = FakeMotoClient()
    payment_id, row = _charged_topup(pg_sessionmaker, client)
    assert row.paymob_order_id is not None
    obj = moto_txn(
        order_id=row.paymob_order_id,
        merchant_order_id=row.special_reference,
        amount_cents=row.amount_minor,
        txn_id=777_002,
    )
    assert _reconcile(pg_sessionmaker, obj) == 1
    _deliver(pg_sessionmaker, obj)
    _deliver(pg_sessionmaker, obj)
    _paid_once(pg_sessionmaker, paid_calls, payment_id, 777_002)


@pytest.mark.parametrize(
    ("label", "integration_id"),
    [("card", CARD_INTEGRATION_ID), ("foreign", 9_999_999)],
)
def test_a_callback_from_another_integration_is_held_back_and_pays_nothing(
    pg_sessionmaker: sessionmaker[Session],
    paid_calls: list[uuid.UUID],
    label: str,
    integration_id: int,
) -> None:
    # A MOTO-charged payment accepts only the MOTO integration (Phase 02's per-payment guard):
    # a transaction on the card (3DS) integration, or on one that is not ours, settles nothing
    # even with a real order id. The MOTO callback that follows still pays.
    client = FakeMotoClient()
    payment_id, row = _charged_topup(pg_sessionmaker, client)
    assert row.paymob_order_id is not None
    other = transaction_obj(
        txn_id=777_003 if label == "card" else 777_013,
        order_id=row.paymob_order_id,
        merchant_order_id=row.special_reference,
        amount_cents=row.amount_minor,
    )
    other["integration_id"] = integration_id
    _deliver(pg_sessionmaker, other)
    assert _row(pg_sessionmaker, payment_id).status is PaymentStatus.pending
    assert paid_calls == []
    ours = moto_txn(
        order_id=row.paymob_order_id,
        merchant_order_id=row.special_reference,
        amount_cents=row.amount_minor,
        txn_id=777_004 if label == "card" else 777_014,
    )
    _deliver(pg_sessionmaker, ours)
    assert _row(pg_sessionmaker, payment_id).status is PaymentStatus.paid
    assert paid_calls == [payment_id]


# ---------------------------------------------------------------------------
# Queue helpers.
# ---------------------------------------------------------------------------


def _queue(
    sm: sessionmaker[Session], payer: uuid.UUID, *, key: str | None = None, amount: int = 5_000
) -> uuid.UUID:
    with sm.begin() as session:
        payment = insert_queued_payment(
            session,
            purpose=PaymentPurpose.auto_topup,
            payer_user_id=payer,
            beneficiary_user_id=payer,
            amount_minor=amount,
            currency="EGP",
            dedupe_key=key or f"auto_topup:{uuid.uuid4()}:1",
        )
        assert payment is not None
        return payment.id


def _active_card(session: Session, payment: Payment) -> SavedCard | None:
    return next(iter(saved_cards_for(session, payment.payer_user_id)), None)


def _run_queue(
    sm: sessionmaker[Session],
    client: FakeMotoClient,
    *,
    card_for: Any = _active_card,
    settings: PaymobSettings = PAYMOB_SETTINGS,
) -> int:
    return charge_queued_payments(
        sm,
        client,
        settings,
        purpose=PaymentPurpose.auto_topup,
        dedupe_prefix="auto_topup:",
        card_for=card_for,
        now=NOW,
    )


def test_insert_queued_payment_is_idempotent_on_its_key(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    payer = seed_user(pg_sessionmaker, Role.student)
    key = f"auto_topup:{uuid.uuid4()}:1"
    first = _queue(pg_sessionmaker, payer, key=key)
    with pg_sessionmaker.begin() as session:
        again = insert_queued_payment(
            session,
            purpose=PaymentPurpose.auto_topup,
            payer_user_id=payer,
            beneficiary_user_id=payer,
            amount_minor=5_000,
            currency="EGP",
            dedupe_key=key,
        )
    assert again is None
    row = _row(pg_sessionmaker, first)
    assert row.status is PaymentStatus.created
    assert row.special_reference == str(first)
    assert row.dedupe_key == key
    assert row.next_reconcile_at is None
    assert _count(pg_sessionmaker, payer) == 1


def test_a_dedupe_key_must_carry_its_purposes_prefix(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    # Migration 0056's CHECK: ``auto_topup:`` goes with the auto_topup purpose, and
    # ``extra_seat_renewal:`` with extra_seats. A wrong pairing raises instead of inserting.
    payer = seed_user(pg_sessionmaker, Role.student)
    with pytest.raises(sa.exc.IntegrityError), pg_sessionmaker.begin() as session:
        insert_queued_payment(
            session,
            purpose=PaymentPurpose.auto_topup,
            payer_user_id=payer,
            beneficiary_user_id=payer,
            amount_minor=5_000,
            currency="EGP",
            dedupe_key=f"extra_seat_renewal:{uuid.uuid4()}:1",
        )
    assert _count(pg_sessionmaker, payer) == 0


def test_fail_unsent_is_conditional_on_created(pg_sessionmaker: sessionmaker[Session]) -> None:
    payer = seed_user(pg_sessionmaker, Role.student)
    fresh = _queue(pg_sessionmaker, payer)
    claimed = _queue(pg_sessionmaker, payer)
    with pg_sessionmaker.begin() as session:
        session.execute(
            sa.update(Payment).where(Payment.id == claimed).values(status=PaymentStatus.pending)
        )
    with pg_sessionmaker.begin() as session:
        assert fail_unsent(session, fresh, reason="card_unusable") is True
        assert fail_unsent(session, claimed, reason="card_unusable") is False
    row = _row(pg_sessionmaker, fresh)
    assert row.status is PaymentStatus.failed
    assert row.last_callback == {"source": "pre_send", "reason": "card_unusable"}
    assert row.next_reconcile_at is None
    assert _row(pg_sessionmaker, claimed).status is PaymentStatus.pending


def test_the_status_groups_are_the_documented_ones() -> None:
    assert set(IN_FLIGHT_STATUSES) == {PaymentStatus.created, PaymentStatus.pending}
    assert set(FAILED_STATUSES) == {
        PaymentStatus.failed,
        PaymentStatus.failed_mismatch,
        PaymentStatus.voided,
    }


@pytest.mark.usefixtures("clean_queue")
def test_queued_payments_are_charged_once_across_runs(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    payer = seed_user(pg_sessionmaker, Role.student)
    seed_saved_card(pg_sessionmaker, payer, token=TOKEN)
    ids = [_queue(pg_sessionmaker, payer) for _ in range(3)]
    client = FakeMotoClient()
    assert _run_queue(pg_sessionmaker, client) == 3
    assert _run_queue(pg_sessionmaker, client) == 0
    assert len(client.calls_to("pay_with_token")) == 3
    assert {_row(pg_sessionmaker, i).status for i in ids} == {PaymentStatus.pending}


@pytest.mark.usefixtures("clean_queue")
def test_two_replicas_interleaved_charge_each_queued_payment_once(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    payer = seed_user(pg_sessionmaker, Role.student)
    seed_saved_card(pg_sessionmaker, payer, token=TOKEN)
    ids = [_queue(pg_sessionmaker, payer) for _ in range(2)]
    client = FakeMotoClient()
    inner: list[int] = []

    def other_replica(_call: dict[str, Any]) -> None:
        client.on_pay = None  # the second replica's own charge must not recurse
        inner.append(_run_queue(pg_sessionmaker, client))

    client.on_pay = other_replica
    outer = _run_queue(pg_sessionmaker, client)
    # Replica A claimed the first row and was mid-call when replica B ran: B saw that row as
    # ``pending`` and charged only the other; A then found the second already claimed.
    assert inner == [1]
    assert outer == 1
    assert len(client.calls_to("pay_with_token")) == 2
    assert {_row(pg_sessionmaker, i).status for i in ids} == {PaymentStatus.pending}


@pytest.mark.usefixtures("clean_queue")
def test_a_queued_payment_with_an_unusable_card_fails_unsent(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    client = FakeMotoClient()
    # No card at all.
    nobody = seed_user(pg_sessionmaker, Role.student)
    no_card = _queue(pg_sessionmaker, nobody)
    # An inactive card.
    inactive_payer = seed_user(pg_sessionmaker, Role.student)
    seed_saved_card(pg_sessionmaker, inactive_payer, is_active=False)
    inactive = _queue(pg_sessionmaker, inactive_payer)
    # A card whose ciphertext was copied from another user's row.
    _victim, victim_card = _payer(pg_sessionmaker)
    swapped_payer, swapped_card = _payer(pg_sessionmaker)
    with pg_sessionmaker.begin() as session:
        session.execute(
            sa.update(SavedCard)
            .where(SavedCard.id == swapped_card)
            .values(token=_ciphertext(pg_sessionmaker, victim_card))
        )
    swapped = _queue(pg_sessionmaker, swapped_payer)

    def any_card(session: Session, payment: Payment) -> SavedCard | None:
        # Hand back even an inactive card, so the service's own refusal is what fails the row.
        return session.scalars(
            sa.select(SavedCard).where(SavedCard.user_id == payment.payer_user_id)
        ).first()

    assert _run_queue(pg_sessionmaker, client, card_for=any_card) == 3
    for payment_id in (no_card, inactive, swapped):
        row = _row(pg_sessionmaker, payment_id)
        assert row.status is PaymentStatus.failed
        assert row.last_callback == {"source": "pre_send", "reason": "card_unusable"}
    assert client.calls == []


@pytest.mark.usefixtures("clean_queue")
def test_a_queued_payment_for_a_payer_without_a_phone_fails_unsent(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    client = FakeMotoClient()
    payer, _card = _payer(pg_sessionmaker, phone=None)
    payment_id = _queue(pg_sessionmaker, payer)
    assert _run_queue(pg_sessionmaker, client) == 1
    row = _row(pg_sessionmaker, payment_id)
    assert row.status is PaymentStatus.failed
    assert row.last_callback == {"source": "pre_send", "reason": "phone_required"}
    assert client.calls == []


@pytest.mark.usefixtures("clean_queue")
def test_one_row_raising_does_not_stop_the_rest_and_raises_an_alert(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    payer = seed_user(pg_sessionmaker, Role.student)
    seed_saved_card(pg_sessionmaker, payer, token=TOKEN)
    bad = _queue(pg_sessionmaker, payer)
    good = _queue(pg_sessionmaker, payer)
    client = FakeMotoClient()

    def card_for(session: Session, payment: Payment) -> SavedCard | None:
        if payment.id == bad:
            raise RuntimeError(f"boom {TOKEN}")
        return _active_card(session, payment)

    with capture_logs() as logs:
        handled = _run_queue(pg_sessionmaker, client, card_for=card_for)
    assert handled == 1
    assert _row(pg_sessionmaker, bad).status is PaymentStatus.created  # untouched, retried next run
    assert _row(pg_sessionmaker, good).status is PaymentStatus.pending
    (alert,) = [e for e in logs if e["event"] == "merchant_charge_sweep_failed"]
    assert alert["alert"] is True
    assert alert["payment_id"] == str(bad)
    assert alert["error_type"] == "RuntimeError"
    assert TOKEN not in str(logs)


@pytest.mark.usefixtures("clean_queue")
def test_the_queue_does_nothing_while_charges_are_not_configured(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    payer = seed_user(pg_sessionmaker, Role.student)
    seed_saved_card(pg_sessionmaker, payer, token=TOKEN)
    queued = _queue(pg_sessionmaker, payer)
    mismatched = paymob_settings(secret_key="egy_sk_test_one", public_key="egy_pk_live_two")
    client = FakeMotoClient(mismatched)
    assert _run_queue(pg_sessionmaker, client, settings=mismatched) == 0
    assert client.calls == []
    # Left ``created``: fixing the keys lets the next run send it.
    assert _row(pg_sessionmaker, queued).status is PaymentStatus.created
    assert _run_queue(pg_sessionmaker, FakeMotoClient()) == 1


@pytest.mark.usefixtures("clean_queue")
def test_the_queue_only_takes_its_own_prefix_and_purpose(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    payer = seed_user(pg_sessionmaker, Role.student)
    seed_saved_card(pg_sessionmaker, payer, token=TOKEN)
    mine = _queue(pg_sessionmaker, payer)
    with pg_sessionmaker.begin() as session:
        other = insert_queued_payment(
            session,
            purpose=PaymentPurpose.extra_seats,
            payer_user_id=payer,
            beneficiary_user_id=payer,
            amount_minor=5_000,
            currency="EGP",
            dedupe_key=f"extra_seat_renewal:{uuid.uuid4()}:1",
            seat_quantity=2,
        )
        assert other is not None
        other_id = other.id
    client = FakeMotoClient()
    assert _run_queue(pg_sessionmaker, client) == 1
    assert _row(pg_sessionmaker, mine).status is PaymentStatus.pending
    assert _row(pg_sessionmaker, other_id).status is PaymentStatus.created


# ---------------------------------------------------------------------------
# R27: an unexpected error after the claim never becomes "nothing was charged".
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("stage", ["intention", "pay"])
def test_an_unexpected_error_after_the_claim_leaves_the_row_pending_and_raises_an_alert(
    pg_sessionmaker: sessionmaker[Session], stage: str
) -> None:
    client = FakeMotoClient()

    def boom(_call: dict[str, Any]) -> None:
        raise RuntimeError(f"unexpected {TOKEN}")

    if stage == "intention":
        client.on_intention = boom
    else:
        client.on_pay = boom
    payer, card = _payer(pg_sessionmaker)
    with capture_logs() as logs:
        payment_id = _charge(pg_sessionmaker, client, payer=payer, card_id=card)  # no raise
    row = _row(pg_sessionmaker, payment_id)
    assert row.status is PaymentStatus.pending
    assert row.next_reconcile_at is not None
    assert row.next_reconcile_at <= NOW
    (alert,) = [e for e in logs if e["event"] == "merchant_charge_post_claim_error"]
    assert alert["alert"] is True
    assert alert["payment_id"] == str(payment_id)
    assert alert["error_type"] == "RuntimeError"
    assert TOKEN not in str(logs)
    if stage == "intention":
        assert client.calls_to("pay_with_token") == []


# ---------------------------------------------------------------------------
# Logs never carry the token, the payment key or the ciphertext.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "scripted",
    [
        PaymobError("declined", status_code=400, body={"echo": TOKEN}),
        PaymobError("timed out", timeout=True),
        {"id": 1, "success": True, "pending": False},
        {"id": 1, "success": False, "pending": False},
        {},
    ],
    ids=["4xx", "timeout", "accepted", "declined", "unreadable"],
)
def test_logs_never_carry_the_token_the_payment_key_or_the_ciphertext(
    pg_sessionmaker: sessionmaker[Session], scripted: Any
) -> None:
    client = FakeMotoClient()
    client.pay_response = scripted
    payer, card = _payer(pg_sessionmaker)
    with capture_logs() as logs:
        _charge(pg_sessionmaker, client, payer=payer, card_id=card)
    rendered = str(logs)
    payment_key = client.intention_response["payment_keys"][0]["key"]
    client_secret = client.intention_response["client_secret"]
    assert logs  # something was logged, so the assertions below mean something
    assert TOKEN not in rendered
    assert payment_key not in rendered
    assert client_secret not in rendered
    assert _ciphertext(pg_sessionmaker, card) not in rendered
    assert TEST_CARD_TOKEN_KEY not in rendered


# ---------------------------------------------------------------------------
# Card choice (DV-6) and the shared payment builder.
# ---------------------------------------------------------------------------


def test_active_card_is_the_first_card_the_summary_shows(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    payer = seed_user(pg_sessionmaker, Role.student)
    tie = NOW - timedelta(days=1)
    first = seed_saved_card(pg_sessionmaker, payer, token="tok_a", created_at=tie)
    second = seed_saved_card(pg_sessionmaker, payer, token="tok_b", created_at=tie)
    older = seed_saved_card(
        pg_sessionmaker, payer, token="tok_c", created_at=tie - timedelta(days=9)
    )
    with pg_sessionmaker() as session:
        shown = [card.id for card in saved_cards_for(session, payer)]
        chosen = MerchantChargeService(session, FakeMotoClient(), PAYMOB_SETTINGS).active_card(
            payer
        )
    # Same ``created_at``: the summary's tie-break is ``id`` ascending, and the charge follows it.
    assert shown == [*sorted([first, second]), older]
    assert chosen is not None
    assert chosen.id == shown[0]


def test_active_card_is_none_without_an_active_card(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    payer = seed_user(pg_sessionmaker, Role.student)
    seed_saved_card(pg_sessionmaker, payer, is_active=False)
    with pg_sessionmaker() as session:
        service = MerchantChargeService(session, FakeMotoClient(), PAYMOB_SETTINGS)
        assert service.active_card(payer) is None


def test_new_payment_flushes_a_created_row_with_its_reference(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    payer = seed_user(pg_sessionmaker, Role.student)
    with pg_sessionmaker() as session:
        payment = MerchantChargeService(session, FakeMotoClient(), PAYMOB_SETTINGS).new_payment(
            purpose=PaymentPurpose.extra_seats,
            payer_user_id=payer,
            beneficiary_user_id=payer,
            amount_minor=4_000,
            currency="EGP",
            seat_quantity=2,
            dedupe_key=f"extra_seat_renewal:{uuid.uuid4()}:1",
        )
        assert payment.special_reference == str(payment.id)
        assert payment.status is PaymentStatus.created
        # Flushed, not committed: visible in this transaction, gone after a rollback.
        assert (
            session.scalar(
                sa.select(sa.func.count()).select_from(Payment).where(Payment.id == payment.id)
            )
            == 1
        )
        session.rollback()
    assert _count(pg_sessionmaker, payer) == 0


# ---------------------------------------------------------------------------
# Review fixes: a saved card is charged only for a queued payment of its own.
# ---------------------------------------------------------------------------


def _committed_payment(
    sm: sessionmaker[Session],
    payer: uuid.UUID,
    *,
    purpose: PaymentPurpose = PaymentPurpose.auto_topup,
    dedupe_key: str | None = None,
    paymob_order_id: int | None = None,
) -> uuid.UUID:
    return seed_payment_row(
        sm,
        payer_id=payer,
        purpose=purpose,
        amount_minor=6_000,
        dedupe_key=dedupe_key if dedupe_key is not None else _dedupe_key(purpose),
        paymob_order_id=paymob_order_id,
    )


def _charge_loaded(
    sm: sessionmaker[Session], client: FakeMotoClient, payment_id: uuid.UUID, card_id: uuid.UUID
) -> None:
    with sm() as session:
        payment = session.get(Payment, payment_id)
        card = session.get(SavedCard, card_id)
        assert payment is not None
        assert card is not None
        MerchantChargeService(session, client, PAYMOB_SETTINGS).charge_saved_card(
            payment, card, now=NOW
        )


def test_a_payment_without_a_dedupe_key_is_never_charged_by_saved_card(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    # UD-P1 as an invariant: only a queued charge (the key 0056 ties to its purpose) is
    # MOTO-charged. An ``extra_seats`` purchase (no key) is a 3DS checkout; never taken here.
    client = FakeMotoClient()
    payer, card = _payer(pg_sessionmaker)
    with pytest.raises(MerchantChargeError) as raised:
        _charge(
            pg_sessionmaker,
            client,
            payer=payer,
            card_id=card,
            purpose=PaymentPurpose.extra_seats,
            keyed=False,
        )
    assert raised.value.code == "not_a_queued_charge"
    _assert_refused_cleanly(pg_sessionmaker, client, payer)


@pytest.mark.parametrize("started", ["order", "intention"])
def test_a_payment_with_a_paymob_checkout_is_never_charged_by_saved_card(
    pg_sessionmaker: sessionmaker[Session], started: str
) -> None:
    client = FakeMotoClient()
    payer, card = _payer(pg_sessionmaker)
    payment_id = _committed_payment(
        pg_sessionmaker, payer, paymob_order_id=4_200_001 if started == "order" else None
    )
    if started == "intention":
        with pg_sessionmaker.begin() as session:
            session.execute(
                sa.update(Payment)
                .where(Payment.id == payment_id)
                .values(paymob_intention_id="pi_x")
            )
    with pytest.raises(MerchantChargeError) as raised:
        _charge_loaded(pg_sessionmaker, client, payment_id, card)
    assert raised.value.code == "not_a_queued_charge"
    assert client.calls == []
    assert _row(pg_sessionmaker, payment_id).status is PaymentStatus.created


def test_a_checkout_started_after_the_row_was_loaded_still_loses_the_claim(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    # The in-memory row looked queued; before the claim a checkout intention was attached to it.
    # The claim's own WHERE refuses, so nothing is sent for a payment the payer can also pay.
    client = FakeMotoClient()
    payer, card = _payer(pg_sessionmaker)
    payment_id = _committed_payment(pg_sessionmaker, payer)
    with pg_sessionmaker() as session:
        payment = session.get(Payment, payment_id)
        card_row = session.get(SavedCard, card)
        assert payment is not None
        assert card_row is not None
        with pg_sessionmaker.begin() as other:
            other.execute(
                sa.update(Payment).where(Payment.id == payment_id).values(paymob_order_id=4_200_002)
            )
        with pytest.raises(ChargeAlreadyAttempted):
            MerchantChargeService(session, client, PAYMOB_SETTINGS).charge_saved_card(
                payment, card_row, now=NOW
            )
    assert client.calls == []
    assert _row(pg_sessionmaker, payment_id).status is PaymentStatus.created


def test_only_queued_purposes_have_a_moto_item_name() -> None:
    # Upgrades and credit packs are 3DS checkouts (UD-P1) and are never charged to a saved card.
    assert set(merchant_charge_repo._ITEM_NAMES) == {
        PaymentPurpose.auto_topup,
        PaymentPurpose.extra_seats,
    }


# ---------------------------------------------------------------------------
# Review fixes: the card is checked atomically with the claim.
# ---------------------------------------------------------------------------


def test_a_card_deactivated_after_it_was_loaded_is_not_charged(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    client = FakeMotoClient()
    payer, card = _payer(pg_sessionmaker)
    payment_id = _committed_payment(pg_sessionmaker, payer)
    with pg_sessionmaker() as session:
        payment = session.get(Payment, payment_id)
        card_row = session.get(SavedCard, card)
        assert payment is not None
        assert card_row is not None
        assert card_row.is_active  # what the service sees: a stale, still-active card
        with pg_sessionmaker.begin() as other:
            other.execute(sa.update(SavedCard).where(SavedCard.id == card).values(is_active=False))
        with pytest.raises(MerchantChargeError) as raised:
            MerchantChargeService(session, client, PAYMOB_SETTINGS).charge_saved_card(
                payment, card_row, now=NOW
            )
    assert raised.value.code == "no_saved_card"
    assert client.calls == []
    assert _row(pg_sessionmaker, payment_id).status is PaymentStatus.created


@pytest.mark.usefixtures("clean_queue")
def test_a_queued_payment_whose_card_is_removed_mid_sweep_fails_unsent(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    payer, card = _payer(pg_sessionmaker)
    queued = _queue(pg_sessionmaker, payer)
    client = FakeMotoClient()

    def removed_after_loading(session: Session, payment: Payment) -> SavedCard | None:
        loaded = _active_card(session, payment)
        with pg_sessionmaker.begin() as other:
            other.execute(sa.update(SavedCard).where(SavedCard.id == card).values(is_active=False))
        return loaded

    assert _run_queue(pg_sessionmaker, client, card_for=removed_after_loading) == 1
    row = _row(pg_sessionmaker, queued)
    assert row.status is PaymentStatus.failed
    assert row.last_callback == {"source": "pre_send", "reason": "card_unusable"}
    assert client.calls == []


@pytest.mark.usefixtures("clean_queue")
def test_a_queued_payment_is_never_charged_to_another_payers_genuine_card(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    # The owner check is the only thing between a queued charge and someone else's card: a
    # foreign card decrypts fine under its own owner's id, so only the payer comparison refuses it.
    payer = seed_user(pg_sessionmaker, Role.student)
    _other, others_card = _payer(pg_sessionmaker)
    queued = _queue(pg_sessionmaker, payer)
    client = FakeMotoClient()

    def others(session: Session, _payment: Payment) -> SavedCard | None:
        return session.get(SavedCard, others_card)

    assert _run_queue(pg_sessionmaker, client, card_for=others) == 1
    row = _row(pg_sessionmaker, queued)
    assert row.status is PaymentStatus.failed
    assert row.last_callback == {"source": "pre_send", "reason": "card_unusable"}
    assert client.calls == []


# ---------------------------------------------------------------------------
# Review fixes: a row that raises on every sweep cannot block the queue for good.
# ---------------------------------------------------------------------------


def _error_note(sm: sessionmaker[Session], payment_id: uuid.UUID) -> dict[str, Any] | None:
    return _row(sm, payment_id).last_callback


@pytest.mark.usefixtures("clean_queue")
def test_a_poison_row_is_failed_unsent_after_repeated_sweep_errors(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    payer = seed_user(pg_sessionmaker, Role.student)
    seed_saved_card(pg_sessionmaker, payer, token=TOKEN)
    poison = _queue(pg_sessionmaker, payer)
    client = FakeMotoClient()

    def card_for(session: Session, payment: Payment) -> SavedCard | None:
        if payment.id == poison:
            raise RuntimeError("unknown_payer-like failure")
        return _active_card(session, payment)

    assert merchant_charge_repo.MAX_SWEEP_ERRORS == 3  # pinned: the loops below count to it
    for attempt in range(1, 3):
        with capture_logs() as logs:
            assert _run_queue(pg_sessionmaker, client, card_for=card_for) == 0
        row = _row(pg_sessionmaker, poison)
        assert row.status is PaymentStatus.created  # tried again next run
        assert row.last_callback == {
            "source": "sweep_error",
            "attempts": attempt,
            "error_type": "RuntimeError",
        }
        assert [e for e in logs if e["event"] == "merchant_charge_sweep_failed"]

    with capture_logs() as logs:
        assert _run_queue(pg_sessionmaker, client, card_for=card_for) == 1
    row = _row(pg_sessionmaker, poison)
    assert row.status is PaymentStatus.failed
    assert row.last_callback == {"source": "pre_send", "reason": "sweep_error"}
    assert row.next_reconcile_at is None
    (gave_up,) = [e for e in logs if e["event"] == "merchant_charge_sweep_gave_up"]
    assert gave_up["alert"] is True
    assert gave_up["payment_id"] == str(poison)
    assert client.calls == []  # nothing was ever sent for it
    # Gone from the queue: a further run has nothing to do.
    assert _run_queue(pg_sessionmaker, client, card_for=card_for) == 0


@pytest.mark.usefixtures("clean_queue")
def test_poison_rows_do_not_starve_newer_rows_beyond_the_attempt_bound(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    # A batch of one: the oldest (poison) row holds the only slot until it is failed, then the
    # row behind it is charged. Without the bound it would hold the slot for good.
    payer = seed_user(pg_sessionmaker, Role.student)
    seed_saved_card(pg_sessionmaker, payer, token=TOKEN)
    poison = _queue(pg_sessionmaker, payer)
    good = _queue(pg_sessionmaker, payer)
    client = FakeMotoClient()

    def card_for(session: Session, payment: Payment) -> SavedCard | None:
        if payment.id == poison:
            raise RuntimeError("poison")
        return _active_card(session, payment)

    for _ in range(4):
        charge_queued_payments(
            pg_sessionmaker,
            client,
            PAYMOB_SETTINGS,
            purpose=PaymentPurpose.auto_topup,
            dedupe_prefix="auto_topup:",
            card_for=card_for,
            now=NOW,
            limit=1,
        )
    assert _row(pg_sessionmaker, poison).status is PaymentStatus.failed
    assert _row(pg_sessionmaker, good).status is PaymentStatus.pending
    assert len(client.calls_to("pay_with_token")) == 1


# ---------------------------------------------------------------------------
# Review I1: reconcile's windows run from the send, not from the queueing.
# ---------------------------------------------------------------------------


def _backdate(sm: sessionmaker[Session], payment_id: uuid.UUID, **ago: float) -> None:
    """Move ``created_at`` back, as if the row had waited in the queue (rows can wait)."""
    with sm.begin() as session:
        session.execute(
            sa.update(Payment)
            .where(Payment.id == payment_id)
            .values(created_at=NOW - timedelta(**ago))
        )


def _due_first(sm: sessionmaker[Session], payment_id: uuid.UUID) -> None:
    """Make the payment the oldest due row, so a reconcile pass reaches it before any other."""
    with sm.begin() as session:
        session.execute(
            sa.update(Payment)
            .where(Payment.id == payment_id)
            .values(next_reconcile_at=NOW - timedelta(days=3650))
        )


def _queued_and_charged(
    sm: sessionmaker[Session], client: FakeMotoClient, **waited: float
) -> tuple[uuid.UUID, Payment]:
    """Queue a row, let it wait ``waited`` in the queue, then charge it through the sweep."""
    payer = seed_user(sm, Role.student)
    seed_saved_card(sm, payer, token=TOKEN)
    queued = _queue(sm, payer)
    _backdate(sm, queued, **waited)
    assert _run_queue(sm, client) == 1
    _due_first(sm, queued)
    return queued, _row(sm, queued)


def _reconcile_with(
    sm: sessionmaker[Session], answer: dict[str, Any] | None | Exception, *, at: datetime
) -> int:
    inquirer = FakePaymobClient()
    inquirer.inquiry_response = answer
    with sm() as session:
        return BillingService(session, inquirer, PAYMOB_SETTINGS, now=lambda: at).reconcile_pending(
            now=at
        )


WAITED = [
    pytest.param({"hours": 1}, id="1h"),
    pytest.param({"hours": 25}, id="25h"),
    pytest.param({"days": 8}, id="8d"),
]


@pytest.mark.usefixtures("clean_queue")
@pytest.mark.parametrize("waited", WAITED)
def test_a_late_charged_row_is_not_failed_by_the_first_reconcile_while_paymob_is_still_pending(
    pg_sessionmaker: sessionmaker[Session], waited: dict[str, float]
) -> None:
    # Phase 02 gives a payment up (``failed``) 24 h after its clock starts, and that is what the
    # seat and top-up sweeps read as "definitely not charged". The clock for a queued charge starts
    # when it is sent, not when it was queued: a row that waited a day and was then charged is
    # still pending 20 minutes later when Paymob has not finished with it.
    queued, row = _queued_and_charged(pg_sessionmaker, FakeMotoClient(), **waited)
    assert row.status is PaymentStatus.pending
    assert row.paymob_order_id is not None
    still_pending = moto_txn(
        order_id=row.paymob_order_id,
        merchant_order_id=row.special_reference,
        amount_cents=row.amount_minor,
        success=False,
        pending=True,
        txn_id=778_001,
    )
    _reconcile_with(pg_sessionmaker, still_pending, at=NOW + timedelta(minutes=20))
    after = _row(pg_sessionmaker, queued)
    assert after.status is PaymentStatus.pending
    assert after.next_reconcile_at is not None


@pytest.mark.usefixtures("clean_queue")
@pytest.mark.parametrize("waited", WAITED)
def test_a_late_charged_row_with_an_unknown_pay_outcome_keeps_polling_for_a_full_window(
    pg_sessionmaker: sessionmaker[Session], waited: dict[str, float]
) -> None:
    # The pay call timed out: Paymob may or may not have charged. The first inquiry finds no
    # transaction yet, and then one that fails. Neither may end the payment while the send is
    # young (24 h to give up, 7 days to stop polling), however long the row waited in the queue.
    client = FakeMotoClient()
    client.pay_response = PaymobError("pay timed out", timeout=True)
    queued, _row_before = _queued_and_charged(pg_sessionmaker, client, **waited)
    at = NOW + timedelta(minutes=20)
    _reconcile_with(pg_sessionmaker, None, at=at)  # no transaction yet
    mid = _row(pg_sessionmaker, queued)
    assert mid.status is PaymentStatus.pending
    assert mid.next_reconcile_at is not None
    _due_first(pg_sessionmaker, queued)
    _reconcile_with(pg_sessionmaker, PaymobError("down", timeout=True), at=at)
    after = _row(pg_sessionmaker, queued)
    assert after.status is PaymentStatus.pending
    assert after.next_reconcile_at is not None  # not "stuck": the row is minutes old


@pytest.mark.usefixtures("clean_queue")
def test_the_claim_stamps_sent_at_and_the_windows_still_close_a_really_old_send(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    payer = seed_user(pg_sessionmaker, Role.student)
    seed_saved_card(pg_sessionmaker, payer, token=TOKEN)
    queued = _queue(pg_sessionmaker, payer)
    assert _row(pg_sessionmaker, queued).sent_at is None  # queued, nothing sent
    client = FakeMotoClient()
    assert _run_queue(pg_sessionmaker, client) == 1
    row = _row(pg_sessionmaker, queued)
    assert row.sent_at == NOW
    # A send that really is more than a day old and has no transaction is still given up on.
    _due_first(pg_sessionmaker, queued)
    _reconcile_with(pg_sessionmaker, None, at=NOW + timedelta(hours=25))
    assert _row(pg_sessionmaker, queued).status is PaymentStatus.failed


def test_a_checkout_payment_has_no_sent_at_and_keeps_the_created_at_clock(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    payer = seed_user(pg_sessionmaker, Role.student)
    payment_id = seed_payment_row(
        pg_sessionmaker,
        payer_id=payer,
        purpose=PaymentPurpose.extra_seats,
        amount_minor=5_000,
        status=PaymentStatus.created,
        created_at=NOW - timedelta(hours=25),
    )
    with pg_sessionmaker.begin() as session:
        session.execute(
            sa.update(Payment)
            .where(Payment.id == payment_id)
            .values(next_reconcile_at=NOW - timedelta(days=3650))
        )
    assert _row(pg_sessionmaker, payment_id).sent_at is None
    _reconcile_with(pg_sessionmaker, None, at=NOW)
    assert _row(pg_sessionmaker, payment_id).status is PaymentStatus.failed
