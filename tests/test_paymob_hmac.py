"""Paymob callback HMACs (research 02 §2; spec §9 "HMAC" unit tests)."""

from __future__ import annotations

import hashlib
import hmac as std_hmac
import re

import pytest

from lemely.io.paymob.hmac import (
    TOKEN_HMAC_FIELDS,
    TRANSACTION_HMAC_FIELDS,
    sign,
    subscription_hmac_message,
    token_hmac_message,
    transaction_hmac_message,
    verify_subscription_hmac,
    verify_token_hmac,
    verify_transaction_hmac,
)
from tests.paymob_fixtures import TEST_HMAC_SECRET, token_obj, transaction_obj

#: The docs' worked example (DOC-HMAC): field values and their concatenation.
DOCS_OBJ = {
    "amount_cents": 100000,
    "created_at": "2024-06-13T11:33:44.592345",
    "currency": "EGP",
    "error_occured": False,
    "has_parent_transaction": False,
    "id": 192036465,
    "integration_id": 4097558,
    "is_3d_secure": True,
    "is_auth": False,
    "is_capture": False,
    "is_refunded": False,
    "is_standalone_payment": True,
    "is_voided": False,
    "order": {"id": 217503754},
    "owner": 302852,
    "pending": False,
    "source_data": {"pan": "2346", "sub_type": "MasterCard", "type": "card"},
    "success": True,
}
DOCS_MESSAGE = (
    "1000002024-06-13T11:33:44.592345EGPfalsefalse1920364654097558truefalsefalsefalse"
    "truefalse217503754302852false2346MasterCardcardtrue"
)
#: The docs' sample digest. Its secret is unpublished, so it only pins the format.
DOCS_DIGEST = (
    "fa8ac0b7f3852e60c50e7fdd4ea5ef0bda96030c19dea1d55df8c76d6c08ab18"
    "77774662cbb04981dc84839ad4da560bcc8cb53b8973548657f7e8f8d2e79930"
)


def test_field_order_is_the_documented_lexicographic_list() -> None:
    assert TRANSACTION_HMAC_FIELDS == (
        "amount_cents",
        "created_at",
        "currency",
        "error_occured",
        "has_parent_transaction",
        "id",
        "integration_id",
        "is_3d_secure",
        "is_auth",
        "is_capture",
        "is_refunded",
        "is_standalone_payment",
        "is_voided",
        "order.id",
        "owner",
        "pending",
        "source_data.pan",
        "source_data.sub_type",
        "source_data.type",
        "success",
    )
    assert TOKEN_HMAC_FIELDS == (
        "card_subtype",
        "created_at",
        "email",
        "id",
        "masked_pan",
        "merchant_id",
        "order_id",
        "token",
    )


def test_the_docs_worked_example_concatenates_exactly() -> None:
    assert transaction_hmac_message(DOCS_OBJ) == DOCS_MESSAGE


def test_sign_is_hmac_sha512_lowercase_hex_like_the_docs_digest() -> None:
    digest = sign(DOCS_MESSAGE, TEST_HMAC_SECRET)
    expected = std_hmac.new(
        TEST_HMAC_SECRET.encode(), DOCS_MESSAGE.encode(), hashlib.sha512
    ).hexdigest()
    assert digest == expected
    assert re.fullmatch(r"[0-9a-f]{128}", digest)
    assert re.fullmatch(r"[0-9a-f]{128}", DOCS_DIGEST)


def test_a_correct_signature_verifies() -> None:
    received = sign(DOCS_MESSAGE, TEST_HMAC_SECRET)
    assert verify_transaction_hmac(DOCS_OBJ, received, TEST_HMAC_SECRET) is True


def test_uppercase_and_padded_hex_still_verifies() -> None:
    received = "  " + sign(DOCS_MESSAGE, TEST_HMAC_SECRET).upper() + "\n"
    assert verify_transaction_hmac(DOCS_OBJ, received, TEST_HMAC_SECRET) is True


@pytest.mark.parametrize(
    ("field", "value"),
    [("amount_cents", 100001), ("success", False), ("pending", True), ("currency", "USD")],
)
def test_any_tampered_field_fails(field: str, value: object) -> None:
    received = sign(DOCS_MESSAGE, TEST_HMAC_SECRET)
    assert verify_transaction_hmac({**DOCS_OBJ, field: value}, received, TEST_HMAC_SECRET) is False


def test_a_tampered_order_id_fails() -> None:
    received = sign(DOCS_MESSAGE, TEST_HMAC_SECRET)
    tampered = {**DOCS_OBJ, "order": {"id": 1}}
    assert verify_transaction_hmac(tampered, received, TEST_HMAC_SECRET) is False


@pytest.mark.parametrize("received", ["", "abc", "0" * 128, "z" * 128, "é" * 128])
def test_missing_short_wrong_or_non_hex_signatures_fail(received: str) -> None:
    assert verify_transaction_hmac(DOCS_OBJ, received, TEST_HMAC_SECRET) is False


def test_the_wrong_secret_fails() -> None:
    received = sign(DOCS_MESSAGE, "another-secret")
    assert verify_transaction_hmac(DOCS_OBJ, received, TEST_HMAC_SECRET) is False


def test_an_empty_secret_never_verifies() -> None:
    assert verify_transaction_hmac(DOCS_OBJ, sign(DOCS_MESSAGE, ""), "") is False


def test_none_becomes_empty_string_and_wallet_shaped_source_data_works() -> None:
    wallet = {
        **DOCS_OBJ,
        "source_data": {"type": "wallet", "pan": "01010101010", "sub_type": None},
    }
    message = transaction_hmac_message(wallet)
    assert message.endswith("false01010101010wallettrue")
    assert "None" not in message
    assert verify_transaction_hmac(wallet, sign(message, TEST_HMAC_SECRET), TEST_HMAC_SECRET)


def test_absent_nested_objects_contribute_empty_strings() -> None:
    bare = {k: v for k, v in DOCS_OBJ.items() if k not in {"source_data", "order"}}
    message = transaction_hmac_message(bare)
    # is_standalone(true) is_voided(false) order.id("") owner pending(false) 3x"" success
    assert message.endswith("truefalse302852falsetrue")


def test_the_shared_fixture_round_trips() -> None:
    obj = transaction_obj(merchant_order_id="ref-1")
    assert verify_transaction_hmac(obj, sign(transaction_hmac_message(obj), "s"), "s")


def test_token_message_matches_the_docs_sample_prefix() -> None:
    obj = token_obj(token="3f22ce8a4e", order_id="593881581")
    assert token_hmac_message(obj) == (
        "MasterCard2026-08-24T13:28:31.015314kiyedi3052@claspira.com15978654"
        "xxxx-xxxx-xxxx-234610539285938815813f22ce8a4e"
    )


def test_token_signature_verifies_and_detects_a_swapped_token() -> None:
    obj = token_obj()
    received = sign(token_hmac_message(obj), TEST_HMAC_SECRET)
    assert verify_token_hmac(obj, received, TEST_HMAC_SECRET) is True
    assert verify_token_hmac({**obj, "token": "other"}, received, TEST_HMAC_SECRET) is False


def test_subscription_message_is_trigger_for_id() -> None:
    assert subscription_hmac_message("suspended", 1264) == "suspendedfor1264"
    assert subscription_hmac_message("Successful Transaction", 1264) == (
        "Successful Transactionfor1264"
    )


def test_subscription_signature_verifies_and_binds_the_trigger() -> None:
    received = sign("suspendedfor1264", TEST_HMAC_SECRET)
    assert verify_subscription_hmac("suspended", 1264, received, TEST_HMAC_SECRET) is True
    assert verify_subscription_hmac("resumed", 1264, received, TEST_HMAC_SECRET) is False
    assert verify_subscription_hmac("suspended", 1265, received, TEST_HMAC_SECRET) is False


def test_one_character_tamper_of_the_received_digest_fails() -> None:
    received = sign(DOCS_MESSAGE, TEST_HMAC_SECRET)
    flipped = ("0" if received[-1] != "0" else "1").join([received[:-1], ""])
    assert flipped != received
    assert verify_transaction_hmac(DOCS_OBJ, flipped, TEST_HMAC_SECRET) is False


def test_swapping_two_fields_in_the_order_would_fail() -> None:
    """Prove the order matters: amount_cents and created_at swapped is rejected."""
    swapped = (
        "2024-06-13T11:33:44.592345100000" + DOCS_MESSAGE[len("1000002024-06-13T11:33:44.592345") :]
    )
    assert swapped != DOCS_MESSAGE
    received = sign(swapped, TEST_HMAC_SECRET)
    assert verify_transaction_hmac(DOCS_OBJ, received, TEST_HMAC_SECRET) is False
