"""The one phone validator (UD-11 / UD-11a): format only, E.164 out, no placeholder ever."""

from __future__ import annotations

import pytest

from lemely.core.phone import (
    PHONE_INVALID,
    PHONE_REQUIRED,
    InvalidPhone,
    normalise_phone,
    validate_phone,
)

ARABIC_INDIC = "٠١٠١٢٣٤٥٦٧٨"  # 01012345678
PERSIAN = "۰۱۰۱۲۳۴۵۶۷۸"  # 01012345678


@pytest.mark.parametrize(
    ("typed", "stored"),
    [
        # every Egyptian mobile prefix (010, 011, 012, 015), local and international
        ("01012345678", "+201012345678"),
        ("01112345678", "+201112345678"),
        ("01212345678", "+201212345678"),
        ("01512345678", "+201512345678"),
        ("+201512345678", "+201512345678"),
        # international mobiles: UK, Saudi Arabia, UAE; and the US, where libphonenumber cannot
        # tell a mobile from a landline (FIXED_LINE_OR_MOBILE) and the number must still pass
        ("+447911123456", "+447911123456"),
        ("+966512345678", "+966512345678"),
        ("+971501234567", "+971501234567"),
        ("+12025550123", "+12025550123"),
    ],
)
def test_mobile_numbers_are_accepted(typed: str, stored: str) -> None:
    assert validate_phone(typed) == stored


@pytest.mark.parametrize(
    ("typed", "stored"),
    [
        ("+201234567890", "+201234567890"),
        ("+20 123 456 7890", "+201234567890"),
        ("+20-123-456-7890", "+201234567890"),
        ("01012345678", "+201012345678"),
        ("010 1234 5678", "+201012345678"),
        ("00201012345678", "+201012345678"),
        ("201012345678", "+201012345678"),
        ("(+20) 101 234 5678", "+201012345678"),
        # the trunk 0 typed after the country code, a very common Egyptian entry
        ("+2001012345678", "+201012345678"),
        ("002001012345678", "+201012345678"),
        ("+20 (0)101 234 5678", "+201012345678"),
        # the leading 0 of a local mobile dropped
        ("1012345678", "+201012345678"),
        # Arabic-Indic and Persian digits, whole or mixed with ASCII
        (ARABIC_INDIC, "+201012345678"),
        ("+20" + ARABIC_INDIC[1:], "+201012345678"),
        (PERSIAN, "+201012345678"),
        # international numbers are accepted: the spec is not Egypt-only
        ("+447911123456", "+447911123456"),
        ("+1 650 253 0000", "+16502530000"),
        ("0044 7911 123456", "+447911123456"),
        ("  +201012345678  ", "+201012345678"),
    ],
)
def test_a_valid_number_is_stored_in_e164(typed: str, stored: str) -> None:
    assert validate_phone(typed) == stored
    assert normalise_phone(typed) == stored
    assert stored.isascii()


@pytest.mark.parametrize(
    "typed",
    [
        # M1: a landline is a well-formed number, but not one a payer is reached on
        "0223456789",  # Cairo
        "+20223456789",
        "0233456789",
        "035123456",  # Alexandria
        "+442071234567",  # London
        "NA",
        "call me",
        "12345",
        "+0123456789",
        "0130000000",
        "+2001",
        # the former placeholder is well formed but is nobody's number
        "+200000000000",
        "0000000000",
        # an extension is not part of a phone number we store
        "+201012345678 ext 5",
        "+201012345678;ext=5",
        # vanity letters would be silently turned into digits by libphonenumber
        "0101-LEMELY",
        "+1 800 FLOWERS",
        "+20\u0e51\u0e50",
        "+20\u0e51\u0e50\u0e51\u0e52\u0e53\u0e54\u0e55\u0e56\u0e57\u0e58",
        "+" + "1" * 40,
        "9" * 200,
    ],
)
def test_a_malformed_number_is_refused(typed: str) -> None:
    with pytest.raises(InvalidPhone) as caught:
        validate_phone(typed)
    assert caught.value.code == PHONE_INVALID
    assert normalise_phone(typed) is None


@pytest.mark.parametrize("typed", [None, "", "   ", "\t\n"])
def test_a_missing_number_is_required_not_invalid(typed: str | None) -> None:
    with pytest.raises(InvalidPhone) as caught:
        validate_phone(typed)
    assert caught.value.code == PHONE_REQUIRED
    assert normalise_phone(typed) is None


def test_the_error_carries_a_plain_message_and_never_echoes_the_input() -> None:
    with pytest.raises(InvalidPhone) as caught:
        validate_phone("secret-not-a-number")
    assert "secret" not in caught.value.message
    assert caught.value.message
    assert str(caught.value) == caught.value.message


def test_the_stable_codes() -> None:
    assert PHONE_REQUIRED == "phone_required"
    assert PHONE_INVALID == "phone_invalid"
