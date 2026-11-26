"""The one phone validator-and-normaliser (UD-11 / UD-11a). Pure; format only.

Every place Lemely accepts or sends a phone number goes through :func:`validate_phone`:
sign-up, the profile edit and the Paymob ``billing_data``. It parses with libphonenumber
(the ``phonenumbers`` package), requires ``is_valid_number`` and returns E.164 text such as
``+201012345678``. Only a number libphonenumber types as a mobile line is accepted (``MOBILE``, or
``FIXED_LINE_OR_MOBILE`` for regions that cannot tell the two apart); a pure landline such as
Egyptian ``0223456789`` is refused as ``phone_invalid``, because the number is also where a payer
is reached (M1 decision). That is a *format* check only: it does not prove the number exists or
belongs to the person who typed it (there is no OTP, UD-11a).

The default region is Egypt, so a local ``01012345678`` or a bare ``1012345678`` reads as an
Egyptian mobile. A number with a ``+`` or ``00`` prefix is parsed in its own region, so
international numbers are accepted too: nothing in the Paymob spec limits a payer to Egypt.
libphonenumber also covers the entry habits Egyptian users have: Arabic-Indic and Persian
digits, spaces and brackets, a bare ``20...`` and the trunk ``0`` typed after the country code
(``+2001012345678``).

Nothing here substitutes a number. A missing or malformed value is an :class:`InvalidPhone`
(or ``None`` from :func:`normalise_phone`); no placeholder is ever produced.
"""

from __future__ import annotations

from typing import Final

import phonenumbers
from phonenumbers import NumberParseException, PhoneNumberFormat, PhoneNumberType

#: Stable error codes the HTTP layer sends as ``detail.code``.
PHONE_REQUIRED: Final = "phone_required"
PHONE_INVALID: Final = "phone_invalid"

#: Region a number without a ``+`` / ``00`` prefix is read in.
DEFAULT_REGION: Final = "EG"

#: Plain messages for the user. They never echo the input.
_MESSAGES: Final = {
    PHONE_REQUIRED: "Enter a mobile number.",
    PHONE_INVALID: "Enter a valid mobile number, for example 01012345678 or +201012345678.",
}

#: The number types accepted. ``FIXED_LINE_OR_MOBILE`` is libphonenumber's answer for regions (the
#: US, for one) where a mobile and a landline share a numbering range; refusing it would refuse
#: every such mobile.
_ACCEPTED_TYPES: Final = frozenset({PhoneNumberType.MOBILE, PhoneNumberType.FIXED_LINE_OR_MOBILE})

#: Anything longer is not a phone number; stops a huge string reaching the parser.
_MAX_INPUT_LENGTH: Final = 40

#: Arabic-Indic (U+0660..) and Persian (U+06F0..) digits to ASCII, as Egyptian users type them.
#: Digits of any other script are refused rather than read: libphonenumber would accept them,
#: but only the scripts a user of this product plausibly types are worth the ambiguity.
_ASCII_DIGITS: Final = {
    **{0x0660 + n: ord("0") + n for n in range(10)},
    **{0x06F0 + n: ord("0") + n for n in range(10)},
}


class InvalidPhone(ValueError):
    """The value is not a usable phone number; ``code`` is one of the stable codes above."""

    def __init__(self, code: str) -> None:
        self.code = code
        self.message = _MESSAGES[code]
        super().__init__(self.message)


def validate_phone(raw: str | None) -> str:
    """Return ``raw`` as an E.164 string, or raise :class:`InvalidPhone`.

    ``PHONE_REQUIRED`` for ``None`` or blank input, ``PHONE_INVALID`` for anything libphonenumber
    does not accept as a valid mobile number (a pure landline included). Arabic-Indic and Persian
    digits are read as ASCII; digits of any other script are refused. Letters are refused
    outright: libphonenumber would turn vanity letters into digits and read ``ext`` as an
    extension, and neither belongs in a stored number. An extension is refused for the same reason.
    """
    text = (raw or "").strip().translate(_ASCII_DIGITS)
    if not text:
        raise InvalidPhone(PHONE_REQUIRED)
    if (
        len(text) > _MAX_INPUT_LENGTH
        or ";" in text
        or any(ch.isalpha() or (ch.isdigit() and not ch.isascii()) for ch in text)
    ):
        raise InvalidPhone(PHONE_INVALID)
    try:
        parsed = phonenumbers.parse(text, DEFAULT_REGION)
    except NumberParseException as exc:
        raise InvalidPhone(PHONE_INVALID) from exc
    if (
        parsed.extension
        or not phonenumbers.is_valid_number(parsed)
        or phonenumbers.number_type(parsed) not in _ACCEPTED_TYPES
    ):
        raise InvalidPhone(PHONE_INVALID)
    return phonenumbers.format_number(parsed, PhoneNumberFormat.E164)


def normalise_phone(raw: str | None) -> str | None:
    """:func:`validate_phone`, but ``None`` instead of raising for a missing or invalid value."""
    try:
        return validate_phone(raw)
    except InvalidPhone:
        return None


__all__ = [
    "DEFAULT_REGION",
    "PHONE_INVALID",
    "PHONE_REQUIRED",
    "InvalidPhone",
    "normalise_phone",
    "validate_phone",
]
