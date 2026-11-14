"""BillingService.apply_*_callback: verify, dedupe, grant once (spec §5.1 step 4, §5.5, §6)."""

from __future__ import annotations

import threading
import time
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from pydantic import SecretStr
from structlog.testing import capture_logs

from lemely.db import billing_repo
from lemely.db.billing_repo import BillingService, MalformedCallback, add_months
from lemely.db.models.billing import Payment, PaymentPurpose, PaymentStatus, PaymobEvent, SavedCard
from lemely.db.models.enums import Role
from lemely.db.models.usage import UsageGrant
from lemely.runtime.config import PaymobSettings
from lemely.runtime.token_cipher import TokenCipher, TokenCipherError
from tests.paymob_fixtures import (
    CARD_INTEGRATION_ID,
    FIXED_NOW,
    PAYMOB_SETTINGS,
    TEST_CARD_TOKEN_KEY,
    FakePaymobClient,
    seed_pack,
    seed_payment,
    seed_user,
    token_obj,
    transaction_obj,
)

if TYPE_CHECKING:
    import uuid
    from datetime import datetime
    from typing import Any

    from sqlalchemy.orm import Session, sessionmaker


def _apply(
    sm: sessionmaker[Session], obj: dict[str, Any], settings: PaymobSettings = PAYMOB_SETTINGS
) -> None:
    with sm.begin() as session:
        BillingService(
            session, FakePaymobClient(), settings, now=lambda: FIXED_NOW
        ).apply_transaction_callback(obj)


def _apply_token(
    sm: sessionmaker[Session], obj: dict[str, Any], settings: PaymobSettings = PAYMOB_SETTINGS
) -> None:
    with sm.begin() as session:
        BillingService(
            session, FakePaymobClient(), settings, now=lambda: FIXED_NOW
        ).apply_token_callback(obj)


def _setup(sm: sessionmaker[Session], **kwargs: Any) -> tuple[uuid.UUID, uuid.UUID]:
    payer = seed_user(sm)
    pack = seed_pack(sm)
    payment = seed_payment(
        sm, payer=payer, beneficiary=payer, pack_id=pack, paymob_order_id=265715202, **kwargs
    )
    return payer, payment


def _payment(sm: sessionmaker[Session], payment_id: uuid.UUID) -> Payment:
    with sm() as session:
        payment = session.get(Payment, payment_id)
        assert payment is not None
        return payment


def _grants(sm: sessionmaker[Session], payment_id: uuid.UUID) -> list[UsageGrant]:
    with sm() as session:
        return list(
            session.scalars(sa.select(UsageGrant).where(UsageGrant.payment_id == payment_id))
        )


def _events(sm: sessionmaker[Session]) -> list[PaymobEvent]:
    with sm() as session:
        return list(session.scalars(sa.select(PaymobEvent).order_by(PaymobEvent.created_at)))


def test_a_successful_callback_marks_paid_and_grants_once(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    payer, pid = _setup(sm)
    _apply(sm, transaction_obj(merchant_order_id=str(pid)))
    payment = _payment(sm, pid)
    assert payment.status is PaymentStatus.paid
    assert payment.paid_at == FIXED_NOW
    assert payment.paymob_txn_id == 192036465
    assert payment.method == "card"
    assert payment.next_reconcile_at is None
    assert payment.last_callback is not None and payment.last_callback["id"] == 192036465
    (grant,) = _grants(sm, pid)
    assert grant.owner_user_id == payer
    assert grant.units == 100
    (event,) = _events(sm)
    assert event.dedupe_key == "txn:192036465:s1p0v0r0"
    assert event.processed_at == FIXED_NOW


def test_a_duplicate_callback_is_a_no_op(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    _, pid = _setup(sm)
    obj = transaction_obj(merchant_order_id=str(pid))
    _apply(sm, obj)
    _apply(sm, obj)
    assert len(_grants(sm, pid)) == 1
    assert len(_events(sm)) == 1


def test_pending_then_success(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    _, pid = _setup(sm)
    _apply(sm, transaction_obj(merchant_order_id=str(pid), success=False, pending=True))
    assert _payment(sm, pid).status is PaymentStatus.pending
    assert _grants(sm, pid) == []
    _apply(sm, transaction_obj(merchant_order_id=str(pid)))
    assert _payment(sm, pid).status is PaymentStatus.paid
    assert len(_grants(sm, pid)) == 1
    assert len(_events(sm)) == 2


def test_a_declined_callback_fails_without_a_grant(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    _, pid = _setup(sm)
    _apply(sm, transaction_obj(merchant_order_id=str(pid), success=False))
    payment = _payment(sm, pid)
    assert payment.status is PaymentStatus.failed
    assert payment.next_reconcile_at is None
    assert _grants(sm, pid) == []


def test_a_late_success_after_failure_is_honoured(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    _, pid = _setup(sm, status=PaymentStatus.failed)
    _apply(sm, transaction_obj(merchant_order_id=str(pid)))
    assert _payment(sm, pid).status is PaymentStatus.paid
    assert len(_grants(sm, pid)) == 1


@pytest.mark.parametrize(
    "overrides",
    [
        {"error_occured": True},
        {"is_voided": True},
        {"is_refunded": True, "refunded_amount_cents": 10000},
    ],
)
def test_success_with_a_bad_flag_is_not_paid(
    migrated_sessionmaker: sessionmaker[Session], overrides: dict[str, Any]
) -> None:
    sm = migrated_sessionmaker
    _, pid = _setup(sm)
    _apply(sm, transaction_obj(merchant_order_id=str(pid), **overrides))
    assert _payment(sm, pid).status is PaymentStatus.failed
    assert _grants(sm, pid) == []


@pytest.mark.parametrize("overrides", [{"amount_cents": 9999}, {"currency": "USD"}])
def test_amount_or_currency_mismatch_is_failed_mismatch_with_no_grant(
    migrated_sessionmaker: sessionmaker[Session], overrides: dict[str, Any]
) -> None:
    sm = migrated_sessionmaker
    _, pid = _setup(sm)
    _apply(sm, transaction_obj(merchant_order_id=str(pid), **overrides))
    payment = _payment(sm, pid)
    assert payment.status is PaymentStatus.failed_mismatch
    assert payment.next_reconcile_at is None
    assert _grants(sm, pid) == []
    # A later correct callback cannot revive a mismatched payment.
    _apply(sm, transaction_obj(merchant_order_id=str(pid), txn_id=999))
    assert _payment(sm, pid).status is PaymentStatus.failed_mismatch
    assert _grants(sm, pid) == []


@pytest.mark.parametrize("reference", ["not-a-uuid", "6f1c5d1e-0000-4000-8000-000000000000"])
def test_an_unknown_reference_is_recorded_and_ignored(
    migrated_sessionmaker: sessionmaker[Session], reference: str
) -> None:
    sm = migrated_sessionmaker
    _, pid = _setup(sm)
    _apply(sm, transaction_obj(merchant_order_id=reference))
    assert _payment(sm, pid).status is PaymentStatus.created
    assert len(_events(sm)) == 1


def test_the_dedupe_key_holds_signed_fields_only() -> None:
    """refunded_amount_cents and the merchant reference sit outside the HMAC."""
    base = transaction_obj(merchant_order_id="a")
    edited = transaction_obj(merchant_order_id="b", refunded_amount_cents=777)
    assert billing_repo.transaction_dedupe_key(base) == billing_repo.transaction_dedupe_key(edited)


def test_a_reference_that_disagrees_with_the_signed_order_pays_nothing(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """The signed order.id names X1; the unsigned reference names X2: neither moves."""
    sm = migrated_sessionmaker
    payer = seed_user(sm)
    pack = seed_pack(sm)
    x1 = seed_payment(sm, payer=payer, beneficiary=payer, pack_id=pack, paymob_order_id=265715202)
    x2 = seed_payment(sm, payer=payer, beneficiary=payer, pack_id=pack, paymob_order_id=111)
    _apply(sm, transaction_obj(merchant_order_id=str(x2), order_id=265715202))
    assert _payment(sm, x1).status is PaymentStatus.created
    assert _payment(sm, x2).status is PaymentStatus.created
    assert _grants(sm, x1) == [] and _grants(sm, x2) == []
    # The audit row does not use up the key X1's genuine callback needs.
    (event,) = _events(sm)
    assert event.dedupe_key == "unmatched:192036465"
    _apply(sm, transaction_obj(merchant_order_id=str(x1), order_id=265715202))
    assert _payment(sm, x1).status is PaymentStatus.paid
    assert _payment(sm, x2).status is PaymentStatus.created
    assert len(_grants(sm, x1)) == 1 and _grants(sm, x2) == []


def test_a_callback_is_matched_by_the_signed_order_not_the_reference(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    _, pid = _setup(sm)
    _apply(sm, transaction_obj(merchant_order_id=str(pid), order_id=999))
    assert _payment(sm, pid).status is PaymentStatus.created
    assert _grants(sm, pid) == []


def test_a_payment_without_a_paymob_order_ignores_a_callback(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    payer = seed_user(sm)
    pid = seed_payment(sm, payer=payer, beneficiary=payer, pack_id=seed_pack(sm))
    _apply(sm, transaction_obj(merchant_order_id=str(pid)))
    assert _payment(sm, pid).status is PaymentStatus.created
    assert _grants(sm, pid) == []


def test_a_forged_child_marker_does_not_consume_the_transaction_key(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """is_refund/is_void are unsigned: resending a signed success with one set is a child.

    It is still treated as a child, but must not use up the ``txn:`` key the genuine
    callback (and the reconcile inquiry) need, or the payment is stuck paid-but-ungranted.
    """
    sm = migrated_sessionmaker
    _, pid = _setup(sm)
    genuine = transaction_obj(merchant_order_id=str(pid))
    for marker in ("is_refund", "is_void"):
        with capture_logs() as logs:
            _apply(sm, {**genuine, marker: True})
        assert any(e["event"] == "paymob_child_marker_mismatch" for e in logs), marker
        assert _payment(sm, pid).status is PaymentStatus.created
        assert _grants(sm, pid) == []
    keys = sorted(e.dedupe_key for e in _events(sm))
    assert keys and all(k.startswith("child:") for k in keys)
    _apply(sm, genuine)
    assert _payment(sm, pid).status is PaymentStatus.paid
    assert len(_grants(sm, pid)) == 1
    _apply(sm, genuine)  # and a replay of the genuine callback still dedupes
    assert len(_grants(sm, pid)) == 1


def test_a_genuine_child_agrees_with_its_signed_marker_and_is_not_warned(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    _, pid = _setup(sm)
    with capture_logs() as logs:
        _apply(
            sm,
            transaction_obj(
                merchant_order_id=str(pid),
                txn_id=192036466,
                is_refund=True,
                has_parent_transaction=True,
            ),
        )
    assert not any(e["event"] == "paymob_child_marker_mismatch" for e in logs)


def test_a_refund_total_that_grows_is_applied_through_the_same_dedupe_key(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """The refunded amount is state, not identity: the second, larger total still lands."""
    sm = migrated_sessionmaker
    _, pid = _setup(sm)
    _apply(sm, transaction_obj(merchant_order_id=str(pid)))
    for amount in (4000, 4000, 10000, 4000):
        _apply(
            sm,
            transaction_obj(
                merchant_order_id=str(pid), is_refunded=True, refunded_amount_cents=amount
            ),
        )
    payment = _payment(sm, pid)
    assert payment.status is PaymentStatus.refunded
    assert (payment.last_callback or {})["refunded_amount_cents"] == 10000
    assert len(_events(sm)) == 2  # the payment and its refund state, however often resent


def test_refund_and_void_flags_on_a_paid_payment(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    _, pid = _setup(sm)
    _apply(sm, transaction_obj(merchant_order_id=str(pid)))
    _apply(
        sm,
        transaction_obj(merchant_order_id=str(pid), is_refunded=True, refunded_amount_cents=4000),
    )
    assert _payment(sm, pid).status is PaymentStatus.partially_refunded
    _apply(
        sm,
        transaction_obj(merchant_order_id=str(pid), is_refunded=True, refunded_amount_cents=10000),
    )
    assert _payment(sm, pid).status is PaymentStatus.refunded
    assert len(_grants(sm, pid)) == 1  # clawback of unspent units is an admin action (Phase 07)


def test_void_on_a_paid_payment(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    _, pid = _setup(sm)
    _apply(sm, transaction_obj(merchant_order_id=str(pid)))
    _apply(sm, transaction_obj(merchant_order_id=str(pid), is_voided=True))
    assert _payment(sm, pid).status is PaymentStatus.voided


def test_a_child_refund_transaction_changes_nothing(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    _, pid = _setup(sm)
    _apply(sm, transaction_obj(merchant_order_id=str(pid)))
    _apply(
        sm,
        transaction_obj(
            merchant_order_id=str(pid),
            txn_id=192036466,
            is_refund=True,
            has_parent_transaction=True,
            amount_cents=4000,
        ),
    )
    payment = _payment(sm, pid)
    assert payment.status is PaymentStatus.paid
    assert payment.paymob_txn_id == 192036465
    assert len(_events(sm)) == 2


def test_a_missing_handler_rolls_the_whole_callback_back(
    migrated_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    sm = migrated_sessionmaker
    _, pid = _setup(sm)
    monkeypatch.delitem(billing_repo._PAID_HANDLERS, PaymentPurpose.credit_pack)
    with pytest.raises(RuntimeError, match="no paid handler"):
        _apply(sm, transaction_obj(merchant_order_id=str(pid)))
    assert _payment(sm, pid).status is PaymentStatus.created
    assert _events(sm) == []


def test_a_callback_without_an_id_is_malformed(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    obj = transaction_obj()
    del obj["id"]
    with pytest.raises(MalformedCallback):
        _apply(migrated_sessionmaker, obj)


# -- card-token callbacks ------------------------------------------------------


def _cards(sm: sessionmaker[Session]) -> list[SavedCard]:
    with sm() as session:
        return list(session.scalars(sa.select(SavedCard)))


def test_a_token_callback_stores_the_card_encrypted_for_the_payer(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    parent = seed_user(sm, Role.parent)
    child = seed_user(sm)
    pack = seed_pack(sm)
    seed_payment(sm, payer=parent, beneficiary=child, pack_id=pack, paymob_order_id=265715202)
    _apply_token(sm, token_obj(token="tok-secret-123"))
    (card,) = _cards(sm)
    assert card.user_id == parent
    assert card.masked_pan == "xxxx-xxxx-xxxx-2346"
    assert card.brand == "MasterCard"
    assert card.paymob_token_id == 15978654
    assert "tok-secret-123" not in card.token
    assert TokenCipher(TEST_CARD_TOKEN_KEY).decrypt(card.token, parent) == "tok-secret-123"
    with sm() as session:
        service = BillingService(session, FakePaymobClient(), PAYMOB_SETTINGS)
        assert service.card_token(card) == "tok-secret-123"
    (event,) = _events(sm)
    assert event.payload["token"] == "[redacted]"
    assert "tok-secret-123" not in str(event.payload)


@pytest.mark.parametrize(
    "overrides",
    [
        {"token": "short"},
        {"token": "has space in it 12345"},
        {"token": "x" * 513},
        {"masked_pan": "4569876truefalse"},
        {"masked_pan": "12345"},
        {"masked_pan": "x" * 24},
        {"card_subtype": "10000"},
        {"card_subtype": ""},
        {"card_subtype": "MasterCard2"},
        {"card_subtype": "A" * 21},
        {"created_at": ""},
        {"created_at": "not-a-date"},
        {"created_at": "10000"},
        {"created_at": None},
        {"token_id": "abc"},
        {"order_id": "abc"},
    ],
)
def test_a_token_callback_of_the_wrong_shape_is_malformed(
    migrated_sessionmaker: sessionmaker[Session], overrides: dict[str, Any]
) -> None:
    sm = migrated_sessionmaker
    seed_payment(
        sm,
        payer=seed_user(sm),
        beneficiary=seed_user(sm),
        pack_id=seed_pack(sm),
        paymob_order_id=265715202,
    )
    obj = token_obj()
    mapping = {"token_id": "id"}
    for key, value in overrides.items():
        obj[mapping.get(key, key)] = value
    with pytest.raises(MalformedCallback):
        _apply_token(sm, obj)
    assert _cards(sm) == []
    assert _events(sm) == []


@pytest.mark.parametrize(
    "subtype", ["MasterCard", "Visa", "Meeza", "Amex", "American Express", "Discover"]
)
def test_real_card_brands_are_accepted(
    migrated_sessionmaker: sessionmaker[Session], subtype: str
) -> None:
    sm = migrated_sessionmaker
    seed_payment(
        sm,
        payer=seed_user(sm),
        beneficiary=seed_user(sm),
        pack_id=seed_pack(sm),
        paymob_order_id=265715202,
    )
    _apply_token(sm, token_obj(card_subtype=subtype))
    (card,) = _cards(sm)
    assert card.brand == subtype


def test_the_same_card_twice_refreshes_one_row(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    _setup(sm)
    _apply_token(sm, token_obj(token_id=1, token="tok-card-a", masked_pan="xxxx-xxxx-xxxx-1111"))
    _apply_token(sm, token_obj(token_id=2, token="tok-card-a", masked_pan="xxxx-xxxx-xxxx-2222"))
    (card,) = _cards(sm)
    assert card.masked_pan == "xxxx-xxxx-xxxx-2222"
    assert card.paymob_token_id == 2


def test_a_duplicate_token_callback_is_a_no_op(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    _setup(sm)
    _apply_token(sm, token_obj())
    _apply_token(sm, token_obj())
    assert len(_cards(sm)) == 1
    assert len(_events(sm)) == 1


def test_a_token_for_an_unknown_order_is_ignored(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    _setup(sm)
    _apply_token(sm, token_obj(order_id="1"))
    assert _cards(sm) == []


def test_without_a_card_key_the_token_is_not_stored(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    _setup(sm)
    no_key = PAYMOB_SETTINGS.model_copy(update={"card_token_key": None})
    _apply_token(sm, token_obj(), settings=no_key)
    assert _cards(sm) == []
    with sm() as session:
        service = BillingService(session, FakePaymobClient(), no_key)
        with pytest.raises(billing_repo.BillingError):
            service.card_token(SavedCard(token="v1:x", token_fingerprint="f", masked_pan="m"))


def test_a_token_callback_without_a_token_is_malformed(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    obj = token_obj()
    del obj["token"]
    with pytest.raises(MalformedCallback):
        _apply_token(migrated_sessionmaker, obj)


# -- R20b / refunds / grants ---------------------------------------------------


def test_a_decline_then_a_verified_success_is_paid_and_granted_once(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    _, pid = _setup(sm)
    _apply(sm, transaction_obj(merchant_order_id=str(pid), txn_id=1, success=False))
    assert _payment(sm, pid).status is PaymentStatus.failed
    success = transaction_obj(merchant_order_id=str(pid), txn_id=2)
    _apply(sm, success)
    _apply(sm, success)
    assert _payment(sm, pid).status is PaymentStatus.paid
    assert _payment(sm, pid).paymob_txn_id == 2
    assert len(_grants(sm, pid)) == 1


def test_the_grant_uses_the_injected_clock(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    _, pid = _setup(sm)
    _apply(sm, transaction_obj(merchant_order_id=str(pid)))
    (grant,) = _grants(sm, pid)
    assert grant.expires_at == add_months(FIXED_NOW, 12)
    assert grant.effective_at == FIXED_NOW


def test_a_duplicate_with_a_different_clock_cannot_grant_twice(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    _, pid = _setup(sm)
    obj = transaction_obj(merchant_order_id=str(pid))
    _apply(sm, obj)
    with sm.begin() as session:
        later = lambda: FIXED_NOW.replace(year=2030)  # noqa: E731
        BillingService(
            session, FakePaymobClient(), PAYMOB_SETTINGS, now=later
        ).apply_transaction_callback(obj)
    assert len(_grants(sm, pid)) == 1


def test_a_second_transaction_on_a_paid_payment_changes_nothing(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    _, pid = _setup(sm)
    _apply(sm, transaction_obj(merchant_order_id=str(pid)))
    _apply(sm, transaction_obj(merchant_order_id=str(pid), txn_id=777, is_voided=True))
    payment = _payment(sm, pid)
    assert payment.status is PaymentStatus.paid
    assert payment.paymob_txn_id == 192036465
    assert len(_grants(sm, pid)) == 1


def test_a_voided_payment_ignores_a_late_success(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    _, pid = _setup(sm, status=PaymentStatus.voided)
    _apply(sm, transaction_obj(merchant_order_id=str(pid)))
    assert _payment(sm, pid).status is PaymentStatus.voided
    assert _grants(sm, pid) == []


def test_the_callback_never_commits_the_route_owns_the_transaction(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    _, pid = _setup(sm)
    with sm() as session:
        BillingService(
            session, FakePaymobClient(), PAYMOB_SETTINGS, now=lambda: FIXED_NOW
        ).apply_transaction_callback(transaction_obj(merchant_order_id=str(pid)))
        session.rollback()
    assert _payment(sm, pid).status is PaymentStatus.created
    assert _events(sm) == []
    assert _grants(sm, pid) == []


def test_a_stored_transaction_event_never_holds_a_raw_card_token(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    _, pid = _setup(sm)
    obj = transaction_obj(merchant_order_id=str(pid))
    obj["source_data"]["token"] = "tok-in-transaction"
    obj["order"]["items"].append({"name": "x", "card_token": "tok-nested"})
    _apply(sm, obj)
    (event,) = _events(sm)
    payment = _payment(sm, pid)
    assert "tok-in-transaction" not in str(event.payload)
    assert "tok-nested" not in str(event.payload)
    assert payment.last_callback is not None
    assert "tok-in-transaction" not in str(payment.last_callback)
    assert "tok-nested" not in str(payment.last_callback)


def test_the_unknown_reference_event_is_redacted_too(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    obj = transaction_obj(merchant_order_id="nobody")
    obj["source_data"]["token"] = "tok-orphan"
    _apply(sm, obj)
    (event,) = _events(sm)
    assert "tok-orphan" not in str(event.payload)


# -- R22: card tokens bound to their owner -------------------------------------


def test_the_stored_token_opens_only_for_its_owner(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    payer, _ = _setup(sm)
    other = seed_user(sm)
    _apply_token(sm, token_obj(token="tok-owned"))
    (card,) = _cards(sm)
    cipher = TokenCipher(TEST_CARD_TOKEN_KEY)
    assert cipher.decrypt(card.token, payer) == "tok-owned"
    with pytest.raises(TokenCipherError):
        cipher.decrypt(card.token, other)
    assert card.token_fingerprint == cipher.fingerprint("tok-owned", payer)


def test_a_ciphertext_moved_to_another_users_row_is_refused(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    _setup(sm)
    other = seed_user(sm)
    _apply_token(sm, token_obj(token="tok-moved"))
    (card,) = _cards(sm)
    with sm() as session:
        service = BillingService(session, FakePaymobClient(), PAYMOB_SETTINGS)
        assert service.card_token(card) == "tok-moved"
        card.user_id = other  # a database writer swaps the row's owner
        with pytest.raises(TokenCipherError):
            service.card_token(card)
        session.rollback()


def test_the_same_physical_card_for_two_users_is_two_rows_with_different_fingerprints(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    pack = seed_pack(sm)
    a, b = seed_user(sm), seed_user(sm)
    seed_payment(sm, payer=a, beneficiary=a, pack_id=pack, paymob_order_id=11)
    seed_payment(sm, payer=b, beneficiary=b, pack_id=pack, paymob_order_id=22)
    _apply_token(sm, token_obj(token_id=1, order_id="11", token="tok-shared"))
    _apply_token(sm, token_obj(token_id=2, order_id="22", token="tok-shared"))
    cards = {card.user_id: card for card in _cards(sm)}
    assert set(cards) == {a, b}
    assert cards[a].token_fingerprint != cards[b].token_fingerprint
    service_cipher = TokenCipher(TEST_CARD_TOKEN_KEY)
    assert service_cipher.decrypt(cards[a].token, a) == "tok-shared"
    assert service_cipher.decrypt(cards[b].token, b) == "tok-shared"


def test_the_same_card_for_the_same_user_keeps_a_stable_fingerprint(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    _setup(sm)
    _apply_token(sm, token_obj(token_id=1, token="tok-card-a"))
    first = _cards(sm)[0].token_fingerprint
    _apply_token(sm, token_obj(token_id=2, token="tok-card-a"))
    (card,) = _cards(sm)
    assert card.token_fingerprint == first


def test_a_malformed_card_key_fails_the_token_callback_loudly(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    _setup(sm)
    bad = PAYMOB_SETTINGS.model_copy(update={"card_token_key": SecretStr("not-a-key")})
    with pytest.raises(TokenCipherError):
        _apply_token(sm, token_obj(), settings=bad)
    assert _cards(sm) == []


# -- review fixes: single-layer exactly-once, lifecycle, ordering, races -----------


def _apply_at(sm: sessionmaker[Session], obj: dict[str, Any], now: datetime) -> None:
    with sm.begin() as session:
        BillingService(
            session, FakePaymobClient(), PAYMOB_SETTINGS, now=lambda: now
        ).apply_transaction_callback(obj)


def test_a_replayed_success_is_stopped_by_the_paid_status_even_if_dedupe_fails(
    migrated_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    sm = migrated_sessionmaker
    _, pid = _setup(sm)
    obj = transaction_obj(merchant_order_id=str(pid))
    _apply(sm, obj)
    monkeypatch.setattr(BillingService, "_record_event", lambda self, kind, key, payload: True)
    _apply_at(sm, obj, FIXED_NOW + timedelta(days=1))
    assert _payment(sm, pid).paid_at == FIXED_NOW
    assert len(_grants(sm, pid)) == 1


def test_a_second_successful_transaction_on_a_paid_payment_changes_nothing(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    _, pid = _setup(sm)
    _apply(sm, transaction_obj(merchant_order_id=str(pid)))
    _apply_at(
        sm, transaction_obj(merchant_order_id=str(pid), txn_id=777), FIXED_NOW + timedelta(days=1)
    )
    payment = _payment(sm, pid)
    assert payment.paymob_txn_id == 192036465
    assert payment.paid_at == FIXED_NOW
    assert payment.status is PaymentStatus.paid
    assert len(_grants(sm, pid)) == 1


def test_a_pending_retry_after_a_decline_returns_to_pending_and_is_reconciled(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    _, pid = _setup(sm)
    _apply(sm, transaction_obj(merchant_order_id=str(pid), txn_id=1, success=False))
    assert _payment(sm, pid).status is PaymentStatus.failed
    assert _payment(sm, pid).next_reconcile_at is None
    _apply(sm, transaction_obj(merchant_order_id=str(pid), txn_id=2, success=False, pending=True))
    payment = _payment(sm, pid)
    assert payment.status is PaymentStatus.pending
    assert payment.next_reconcile_at == FIXED_NOW + timedelta(minutes=15)
    assert _grants(sm, pid) == []
    _apply(sm, transaction_obj(merchant_order_id=str(pid), txn_id=2))
    payment = _payment(sm, pid)
    assert payment.status is PaymentStatus.paid
    assert payment.next_reconcile_at is None
    assert len(_grants(sm, pid)) == 1


def test_stale_pending_for_the_failed_transaction_does_not_reopen_it(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    _, pid = _setup(sm)
    failed = transaction_obj(merchant_order_id=str(pid), txn_id=1, success=False)
    _apply(sm, failed)
    # The same transaction's pending callback arrives out of order, after its final failure.
    _apply(sm, transaction_obj(merchant_order_id=str(pid), txn_id=1, success=False, pending=True))
    payment = _payment(sm, pid)
    assert payment.status is PaymentStatus.failed
    assert payment.next_reconcile_at is None
    assert payment.paymob_txn_id == 1
    assert payment.last_callback is not None
    assert payment.last_callback["pending"] is False
    # The reconcile inquiry returns the same failure again: it dedupes and stays failed.
    _apply(sm, failed)
    payment = _payment(sm, pid)
    assert payment.status is PaymentStatus.failed
    assert payment.next_reconcile_at is None
    assert _grants(sm, pid) == []


def test_stale_pending_for_an_older_failed_transaction_does_not_reopen_it(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    _, pid = _setup(sm)
    _apply(sm, transaction_obj(merchant_order_id=str(pid), txn_id=1, success=False))
    failed_b = transaction_obj(merchant_order_id=str(pid), txn_id=2, success=False)
    _apply(sm, failed_b)
    # Transaction 1 already failed; its pending callback arrives after transaction 2 failed.
    _apply(sm, transaction_obj(merchant_order_id=str(pid), txn_id=1, success=False, pending=True))
    payment = _payment(sm, pid)
    assert payment.status is PaymentStatus.failed
    assert payment.next_reconcile_at is None
    assert payment.paymob_txn_id == 2
    assert payment.last_callback is not None
    assert payment.last_callback["pending"] is False
    # The reconcile inquiry re-reports transaction 2's failure: it dedupes and stays failed.
    _apply(sm, failed_b)
    assert _payment(sm, pid).status is PaymentStatus.failed
    assert _grants(sm, pid) == []


def test_a_pending_callback_that_reopens_a_failed_payment_restarts_the_backoff(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    _, pid = _setup(sm)
    with sm.begin() as session:
        payment = session.get(Payment, pid)
        assert payment is not None
        payment.reconcile_attempts = 7
    _apply(sm, transaction_obj(merchant_order_id=str(pid), txn_id=1, success=False))
    _apply(sm, transaction_obj(merchant_order_id=str(pid), txn_id=2, success=False, pending=True))
    payment = _payment(sm, pid)
    assert payment.status is PaymentStatus.pending
    assert payment.reconcile_attempts == 0
    assert payment.next_reconcile_at == FIXED_NOW + timedelta(minutes=15)


def test_stale_pending_for_the_current_transaction_after_a_success_with_error_stays_failed(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """The same-transaction clause: the failure's key is ``s1p0``, not ``s0p0``."""
    sm = migrated_sessionmaker
    _, pid = _setup(sm)
    _apply(
        sm,
        transaction_obj(merchant_order_id=str(pid), txn_id=1, success=True, error_occured=True),
    )
    assert _payment(sm, pid).status is PaymentStatus.failed
    _apply(sm, transaction_obj(merchant_order_id=str(pid), txn_id=1, success=False, pending=True))
    payment = _payment(sm, pid)
    assert payment.status is PaymentStatus.failed
    assert payment.paymob_txn_id == 1
    assert payment.next_reconcile_at is None
    assert _grants(sm, pid) == []


def test_stale_pending_for_an_older_transaction_that_failed_as_success_with_error(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """Any recorded non-pending state makes a later pending stale, not only ``s0p0``."""
    sm = migrated_sessionmaker
    _, pid = _setup(sm)
    _apply(
        sm,
        transaction_obj(merchant_order_id=str(pid), txn_id=1, success=True, error_occured=True),
    )
    _apply(sm, transaction_obj(merchant_order_id=str(pid), txn_id=2, success=False))
    _apply(sm, transaction_obj(merchant_order_id=str(pid), txn_id=1, success=False, pending=True))
    payment = _payment(sm, pid)
    assert payment.status is PaymentStatus.failed
    assert payment.paymob_txn_id == 2
    assert payment.next_reconcile_at is None
    assert _grants(sm, pid) == []


def test_stale_pending_for_a_transaction_that_was_voided_stays_failed(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    _, pid = _setup(sm)
    _apply(
        sm,
        transaction_obj(merchant_order_id=str(pid), txn_id=1, success=True, is_voided=True),
    )
    assert _payment(sm, pid).status is PaymentStatus.failed
    _apply(sm, transaction_obj(merchant_order_id=str(pid), txn_id=2, success=False))
    _apply(sm, transaction_obj(merchant_order_id=str(pid), txn_id=1, success=False, pending=True))
    payment = _payment(sm, pid)
    assert payment.status is PaymentStatus.failed
    assert payment.paymob_txn_id == 2
    assert payment.next_reconcile_at is None


def test_pending_for_a_never_seen_transaction_reopens_after_two_failures(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    _, pid = _setup(sm)
    _apply(sm, transaction_obj(merchant_order_id=str(pid), txn_id=1, success=False))
    _apply(sm, transaction_obj(merchant_order_id=str(pid), txn_id=2, success=False))
    _apply(sm, transaction_obj(merchant_order_id=str(pid), txn_id=3, success=False, pending=True))
    payment = _payment(sm, pid)
    assert payment.status is PaymentStatus.pending
    assert payment.paymob_txn_id == 3
    assert payment.next_reconcile_at == FIXED_NOW + timedelta(minutes=15)


def _refund(pid: uuid.UUID, cents: int) -> dict[str, Any]:
    return transaction_obj(
        merchant_order_id=str(pid), is_refunded=True, refunded_amount_cents=cents
    )


def test_a_late_smaller_refund_total_never_downgrades_a_full_refund(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    _, pid = _setup(sm)
    _apply(sm, transaction_obj(merchant_order_id=str(pid)))
    _apply(sm, _refund(pid, 10000))
    _apply(sm, _refund(pid, 4000))  # arrives late
    payment = _payment(sm, pid)
    assert payment.status is PaymentStatus.refunded
    assert payment.last_callback is not None
    assert payment.last_callback["refunded_amount_cents"] == 10000


def test_refund_progress_keeps_the_largest_total_seen(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    _, pid = _setup(sm)
    _apply(sm, transaction_obj(merchant_order_id=str(pid)))
    _apply(sm, _refund(pid, 6000))
    _apply(sm, _refund(pid, 4000))
    payment = _payment(sm, pid)
    assert payment.status is PaymentStatus.partially_refunded
    assert payment.last_callback is not None
    assert payment.last_callback["refunded_amount_cents"] == 6000
    _apply(sm, _refund(pid, 10000))
    assert _payment(sm, pid).status is PaymentStatus.refunded


def test_every_token_looking_key_is_redacted_including_nested_lists(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    _setup(sm)
    obj = token_obj(token="tok-main")
    obj["card_tokens"] = [{"token": "tok-in-list", "id": 9}]
    obj["Saved_Token_Value"] = "tok-odd-key"
    obj["extra"] = {"nested": {"cardToken": "tok-deep"}}
    _apply_token(sm, obj)
    (event,) = _events(sm)
    text = str(event.payload)
    for leaked in ("tok-main", "tok-in-list", "tok-odd-key", "tok-deep"):
        assert leaked not in text
    assert event.payload["card_tokens"] == "[redacted]"
    assert event.payload["id"] == 15978654  # non-token fields survive


def test_the_token_callback_never_commits_the_route_owns_the_transaction(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    _setup(sm)
    with sm() as session:
        BillingService(session, FakePaymobClient(), PAYMOB_SETTINGS).apply_token_callback(
            token_obj()
        )
        session.rollback()
    assert _cards(sm) == []
    assert _events(sm) == []


def test_the_callback_locks_the_payment_before_inserting_its_event(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """Lock order payment-then-event: a reconcile-style holder cannot deadlock a callback."""
    sm = migrated_sessionmaker
    _, pid = _setup(sm)
    obj = transaction_obj(merchant_order_id=str(pid))
    errors: list[BaseException] = []

    def callback() -> None:
        try:
            _apply(sm, obj)
        except BaseException as exc:
            errors.append(exc)

    with sm() as holder:  # plays reconcile_pending: it holds the payment row lock first
        holder.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
        locked = holder.scalars(sa.select(Payment).where(Payment.id == pid).with_for_update()).one()
        worker = threading.Thread(target=callback)
        worker.start()
        time.sleep(1.0)  # the callback is now waiting on the payment lock
        BillingService(
            holder, FakePaymobClient(), PAYMOB_SETTINGS, now=lambda: FIXED_NOW
        )._apply_transaction(obj, source="inquiry", payment=locked)
        holder.commit()
    worker.join(30)
    assert not worker.is_alive()
    assert errors == []
    assert _payment(sm, pid).status is PaymentStatus.paid
    assert len(_grants(sm, pid)) == 1
    assert len(_events(sm)) == 1


def test_two_concurrent_first_saves_of_the_same_card_do_not_fail(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    _setup(sm)
    errors: list[BaseException] = []

    def second() -> None:
        try:
            _apply_token(
                sm, token_obj(token_id=2, token="tok-race", masked_pan="xxxx-xxxx-xxxx-2222")
            )
        except BaseException as exc:
            errors.append(exc)

    with sm.begin() as first:
        BillingService(first, FakePaymobClient(), PAYMOB_SETTINGS).apply_token_callback(
            token_obj(token_id=1, token="tok-race", masked_pan="xxxx-xxxx-xxxx-1111")
        )
        worker = threading.Thread(target=second)
        worker.start()
        time.sleep(1.0)  # the second callback is now waiting on the first's uncommitted card row
    worker.join(30)
    assert not worker.is_alive()
    assert errors == []
    (card,) = _cards(sm)
    assert card.masked_pan == "xxxx-xxxx-xxxx-2222"
    assert card.paymob_token_id == 2


# -- the signed integration_id must be one of ours (skill audit I1) --------------------------

MOTO_ID = PAYMOB_SETTINGS.moto_integration_id
APPLE_PAY_ID = 4569878
FOREIGN_ID = 999999


def _levels(logs: list[dict[str, Any]], event: str) -> list[str]:
    return [str(e["log_level"]) for e in logs if e["event"] == event]


@pytest.mark.parametrize("foreign", [FOREIGN_ID, 0, None, "999999", True, "abc"])
def test_a_callback_from_a_foreign_integration_settles_nothing(
    migrated_sessionmaker: sessionmaker[Session], foreign: object
) -> None:
    """A dashboard test or payment link shares the account HMAC secret, so it can carry a
    genuine signature and a real ``order.id``; only the signed ``integration_id`` tells."""
    sm = migrated_sessionmaker
    _, pid = _setup(sm)
    obj = {**transaction_obj(merchant_order_id=str(pid)), "integration_id": foreign}
    with capture_logs() as logs:
        _apply(sm, obj)
    assert _levels(logs, "paymob_unexpected_integration") == ["error"]
    (entry,) = [e for e in logs if e["event"] == "paymob_unexpected_integration"]
    assert entry["path"] == "callback"
    assert entry["alert"] is True
    assert _payment(sm, pid).status is PaymentStatus.created
    assert _grants(sm, pid) == []
    # The audit row does not use up the key the genuine callback needs.
    (event,) = _events(sm)
    assert event.dedupe_key == "rejected_integration:192036465"
    _apply(sm, transaction_obj(merchant_order_id=str(pid)))
    assert _payment(sm, pid).status is PaymentStatus.paid
    assert len(_grants(sm, pid)) == 1


def test_a_callback_with_no_integration_id_settles_nothing(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    _, pid = _setup(sm)
    obj = transaction_obj(merchant_order_id=str(pid))
    del obj["integration_id"]
    _apply(sm, obj)
    assert _payment(sm, pid).status is PaymentStatus.created


@pytest.mark.parametrize(
    ("integration_id", "settles"),
    [(CARD_INTEGRATION_ID, True), (APPLE_PAY_ID, True), (MOTO_ID, False)],
    ids=["card", "apple_pay", "moto"],
)
def test_a_checkout_payment_is_settled_only_by_the_card_and_apple_pay_integrations(
    migrated_sessionmaker: sessionmaker[Session], integration_id: int, settles: bool
) -> None:
    """A credit pack is a 3DS checkout: the MOTO integration (no 3DS, Lemely carries the
    chargeback liability) never settles it, though the MOTO id is configured for this account.
    The full matrix is in ``tests/test_billing_integration_guard.py``."""
    sm = migrated_sessionmaker
    _, pid = _setup(sm)
    settings = PAYMOB_SETTINGS.model_copy(update={"apple_pay_integration_id": APPLE_PAY_ID})
    obj = {**transaction_obj(merchant_order_id=str(pid)), "integration_id": integration_id}
    _apply(sm, obj, settings)
    expected = PaymentStatus.paid if settles else PaymentStatus.created
    assert _payment(sm, pid).status is expected


def test_an_integration_that_is_not_configured_is_not_accepted(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """Apple Pay is unset in PAYMOB_SETTINGS, so its id is not ours here."""
    sm = migrated_sessionmaker
    _, pid = _setup(sm)
    obj = {**transaction_obj(merchant_order_id=str(pid)), "integration_id": APPLE_PAY_ID}
    _apply(sm, obj)
    assert _payment(sm, pid).status is PaymentStatus.created


def test_a_foreign_integration_cannot_flip_a_paid_payment_to_voided(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    _, pid = _setup(sm)
    _apply(sm, transaction_obj(merchant_order_id=str(pid)))
    voided = {
        **transaction_obj(merchant_order_id=str(pid), is_voided=True),
        "integration_id": FOREIGN_ID,
    }
    _apply(sm, voided)
    assert _payment(sm, pid).status is PaymentStatus.paid


def test_the_foreign_integration_is_ignored_even_when_the_callback_is_otherwise_a_duplicate(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    _, pid = _setup(sm)
    _apply(sm, transaction_obj(merchant_order_id=str(pid)))
    _apply(sm, {**transaction_obj(merchant_order_id=str(pid)), "integration_id": FOREIGN_ID})
    assert len(_grants(sm, pid)) == 1


# -- renewal charges have no intention of ours (skill audit I5) ---------------------------


def _renewal_obj(**kwargs: Any) -> dict[str, Any]:
    """A renewal charge: billed on the plan's MOTO integration, with no intention of ours."""
    return {
        **transaction_obj(txn_id=777001, order_id=555001, **kwargs),
        "api_source": "SUBSCRIPTION",
        "integration_id": MOTO_ID,
    }


def test_an_unmatched_renewal_callback_is_info_not_an_error(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    _setup(sm)
    with capture_logs() as logs:
        _apply(sm, _renewal_obj())
    assert _levels(logs, "paymob_renewal_txn_callback_unmatched") == ["info"]
    assert not any(e["log_level"] == "error" for e in logs)
    assert not any(e["event"] == "paymob_callback_unmatched" for e in logs)
    (event,) = _events(sm)  # still audited, under the unmatched key
    assert event.dedupe_key == "unmatched:777001"


@pytest.mark.parametrize("api_source", ["OTHER", "IFRAME", None, "subscription", ""])
def test_any_other_unmatched_callback_stays_an_error(
    migrated_sessionmaker: sessionmaker[Session], api_source: str | None
) -> None:
    sm = migrated_sessionmaker
    _setup(sm)
    obj = {**transaction_obj(txn_id=777002, order_id=555002), "api_source": api_source}
    with capture_logs() as logs:
        _apply(sm, obj)
    assert _levels(logs, "paymob_callback_unmatched") == ["error"]
    assert not any(e["event"] == "paymob_renewal_txn_callback_unmatched" for e in logs)


@pytest.mark.parametrize("integration_id", [CARD_INTEGRATION_ID, FOREIGN_ID, None, "abc"])
def test_the_renewal_marker_needs_the_signed_moto_integration_to_downgrade_the_log(
    migrated_sessionmaker: sessionmaker[Session], integration_id: object
) -> None:
    """``api_source`` is unsigned; the log level rests on the signed MOTO ``integration_id``."""
    sm = migrated_sessionmaker
    _setup(sm)
    obj = {**_renewal_obj(), "integration_id": integration_id}
    with capture_logs() as logs:
        _apply(sm, obj)
    assert _levels(logs, "paymob_callback_unmatched") == ["error"]
    assert not any(e["event"] == "paymob_renewal_txn_callback_unmatched" for e in logs)


def test_no_moto_integration_configured_means_no_renewal_downgrade(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    _setup(sm)
    settings = PAYMOB_SETTINGS.model_copy(update={"moto_integration_id": None})
    obj = {**_renewal_obj(), "integration_id": None}
    with capture_logs() as logs:
        _apply(sm, obj, settings)
    assert _levels(logs, "paymob_callback_unmatched") == ["error"]


def test_a_renewal_marker_does_not_excuse_a_reference_mismatch(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """The order matches one of our payments but the reference names another: still an error."""
    sm = migrated_sessionmaker
    payer = seed_user(sm)
    pack = seed_pack(sm)
    seed_payment(sm, payer=payer, beneficiary=payer, pack_id=pack, paymob_order_id=265715202)
    x2 = seed_payment(sm, payer=payer, beneficiary=payer, pack_id=pack, paymob_order_id=111)
    obj = {
        **transaction_obj(merchant_order_id=str(x2), order_id=265715202),
        "api_source": "SUBSCRIPTION",
    }
    with capture_logs() as logs:
        _apply(sm, obj)
    assert _levels(logs, "paymob_callback_unmatched") == ["error"]


def test_a_renewal_that_does_match_one_of_our_payments_is_applied_normally(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    _, pid = _setup(sm)
    obj = {**transaction_obj(merchant_order_id=str(pid)), "api_source": "SUBSCRIPTION"}
    with capture_logs() as logs:
        _apply(sm, obj)
    assert _payment(sm, pid).status is PaymentStatus.paid
    assert not any(e["event"] == "paymob_renewal_txn_callback_unmatched" for e in logs)


def test_a_refund_or_void_child_is_not_judged_on_its_integration(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """A child settles nothing (the parent's callback carries the state), so a foreign
    ``integration_id`` on one is neither alerted nor allowed to move the payment."""
    sm = migrated_sessionmaker
    _, pid = _setup(sm)
    _apply(sm, transaction_obj(merchant_order_id=str(pid)))
    child = {
        **transaction_obj(
            merchant_order_id=str(pid),
            txn_id=192036466,
            is_refund=True,
            has_parent_transaction=True,
        ),
        "integration_id": FOREIGN_ID,
    }
    with capture_logs() as logs:
        _apply(sm, child)
    assert not any(e["event"] == "paymob_unexpected_integration" for e in logs)
    assert any(e["event"] == "paymob_child_transaction" for e in logs)
    assert _payment(sm, pid).status is PaymentStatus.paid
    keys = {e.dedupe_key for e in _events(sm)}
    assert not any(k.startswith("rejected_integration:") for k in keys)
    assert any(k.startswith("child:txn:192036466") for k in keys)


# -- callback arrival stamp (P07 T2, DV-4) ---------------------------------------


def test_a_verified_callback_stamps_its_arrival_on_the_signed_payment(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    _, pid = _setup(sm)
    assert _payment(sm, pid).callback_received_at is None
    _apply(sm, transaction_obj(merchant_order_id=str(pid), success=False, pending=True))
    assert _payment(sm, pid).callback_received_at == FIXED_NOW


def test_a_duplicate_callback_still_stamps_its_arrival(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    _, pid = _setup(sm)
    obj = transaction_obj(merchant_order_id=str(pid))
    _apply(sm, obj)
    with sm.begin() as session:
        session.execute(
            sa.update(Payment).where(Payment.id == pid).values(callback_received_at=None)
        )
    _apply(sm, obj)  # a dedupe no-op for the payment, but a callback all the same
    assert len(_grants(sm, pid)) == 1
    assert _payment(sm, pid).callback_received_at == FIXED_NOW


def test_a_callback_after_an_inquiry_already_paid_the_payment_still_stamps_it(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """Reconcile learned the result first; the late real callback is a dedupe no-op that
    must still say "a callback arrived", or the problem queue lists a payment that has one."""
    sm = migrated_sessionmaker
    _, pid = _setup(sm, created_at=FIXED_NOW - timedelta(hours=1))
    obj = transaction_obj(merchant_order_id=str(pid))
    client = FakePaymobClient()
    client.inquiry_response = obj
    with sm.begin() as session:
        BillingService(
            session, client, PAYMOB_SETTINGS, now=lambda: FIXED_NOW
        ).reconcile_payment_now(pid, now=FIXED_NOW)
    paid = _payment(sm, pid)
    assert paid.status is PaymentStatus.paid
    assert paid.callback_received_at is None  # an inquiry is not a callback
    _apply(sm, obj)
    assert _payment(sm, pid).callback_received_at == FIXED_NOW
    assert len(_grants(sm, pid)) == 1


def test_a_signed_callback_naming_another_payment_stamps_nothing_on_it(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """``merchant_order_id`` is unsigned: a genuine signature must not stamp the payment
    that field names. Phase 02 refuses the disagreement, so neither payment is stamped."""
    sm = migrated_sessionmaker
    payer = seed_user(sm)
    pack = seed_pack(sm)
    a = seed_payment(sm, payer=payer, beneficiary=payer, pack_id=pack, paymob_order_id=265715202)
    b = seed_payment(sm, payer=payer, beneficiary=payer, pack_id=pack, paymob_order_id=111)
    _apply(sm, transaction_obj(merchant_order_id=str(b), order_id=265715202))
    assert _payment(sm, a).callback_received_at is None
    assert _payment(sm, b).callback_received_at is None


def test_a_callback_stamps_only_the_payment_its_signed_order_resolves_to(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    payer = seed_user(sm)
    pack = seed_pack(sm)
    a = seed_payment(sm, payer=payer, beneficiary=payer, pack_id=pack, paymob_order_id=265715202)
    b = seed_payment(sm, payer=payer, beneficiary=payer, pack_id=pack, paymob_order_id=111)
    obj = transaction_obj(merchant_order_id=str(a), order_id=265715202)
    _apply(sm, obj)
    assert _payment(sm, a).callback_received_at == FIXED_NOW
    assert _payment(sm, b).callback_received_at is None


def test_an_unmatched_callback_stamps_nothing(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    _, pid = _setup(sm)
    _apply(sm, transaction_obj(merchant_order_id=str(pid), order_id=999))
    assert _payment(sm, pid).callback_received_at is None


def test_a_refund_or_void_child_callback_stamps_nothing(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """A child is not the parent's payment result, so it is not the parent's callback."""
    sm = migrated_sessionmaker
    _, pid = _setup(sm)
    _apply(
        sm,
        transaction_obj(
            merchant_order_id=str(pid),
            txn_id=192036466,
            is_refund=True,
            has_parent_transaction=True,
        ),
    )
    assert _payment(sm, pid).callback_received_at is None
