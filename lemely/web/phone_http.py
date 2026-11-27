"""HTTP face of the phone rule (UD-11): one validator, one 422 shape.

Sign-up, the profile edit and checkout all answer a missing or malformed phone with
**422** and ``detail={"code": <stable code>, "message": <plain text>}``. The codes are
``phone_required`` and ``phone_invalid`` (:mod:`lemely.core.phone`); the frontend matches on
the code, never on the message. Checkout adds nothing of its own: a payer with no valid phone
is ``phone_required`` there too.
"""

from __future__ import annotations

from fastapi import HTTPException

from lemely.core.phone import PHONE_REQUIRED, InvalidPhone, validate_phone

#: Shown when checkout is refused because the payer has no valid phone on file.
CHECKOUT_PHONE_MESSAGE = "Add a phone number to your profile before paying."


def phone_error(code: str, message: str) -> HTTPException:
    """The 422 for phone ``code`` with a plain ``message``."""
    return HTTPException(status_code=422, detail={"code": code, "message": message})


def require_valid_phone(raw: str | None) -> str:
    """``raw`` as E.164, or the 422 ``phone_required`` / ``phone_invalid``."""
    try:
        return validate_phone(raw)
    except InvalidPhone as exc:
        raise phone_error(exc.code, exc.message) from exc


def checkout_phone_required() -> HTTPException:
    """The 422 ``phone_required`` a checkout answers when the payer has no valid phone."""
    return phone_error(PHONE_REQUIRED, CHECKOUT_PHONE_MESSAGE)


__all__ = [
    "CHECKOUT_PHONE_MESSAGE",
    "checkout_phone_required",
    "phone_error",
    "require_valid_phone",
]
