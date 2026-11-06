"""Pure verification of Paymob callback HMACs (billing spec §3; research 02 §2).

All three are HMAC-SHA512 under the account HMAC secret, hex digest, compared in
constant time:

* **Transaction** callbacks: the values of 20 fixed keys of ``obj``, concatenated
  with no separator in the documented (lexicographic) order; ``hmac`` arrives in
  the query string.
* **Card-token** callbacks: 8 fixed keys of ``obj``, same rules.
* **Subscription** callbacks: the string ``"{trigger_type}for{subscription id}"``;
  ``hmac`` arrives in the body. It covers neither amount nor state, so callers
  re-fetch from Paymob before acting (spec §5.2).

Stringification follows every reference implementation (research 02 §2.1):
``None`` -> ``""``, booleans -> ``"true"``/``"false"``, everything else ``str()``
with no reformatting (``created_at`` is used verbatim). A missing nested object
(wallet callbacks can omit ``source_data`` fields) contributes empty strings.
"""

from __future__ import annotations

import hashlib
import hmac as std_hmac
from collections.abc import Mapping
from typing import Final

TRANSACTION_HMAC_FIELDS: Final[tuple[str, ...]] = (
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

TOKEN_HMAC_FIELDS: Final[tuple[str, ...]] = (
    "card_subtype",
    "created_at",
    "email",
    "id",
    "masked_pan",
    "merchant_id",
    "order_id",
    "token",
)


def _stringify(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _lookup(obj: Mapping[str, object], dotted: str) -> object:
    current: object = obj
    for part in dotted.split("."):
        if not isinstance(current, Mapping):
            return None
        current = current.get(part)
    return current


def _message(obj: Mapping[str, object], fields: tuple[str, ...]) -> str:
    return "".join(_stringify(_lookup(obj, field)) for field in fields)


def transaction_hmac_message(obj: Mapping[str, object]) -> str:
    """The string Paymob signs for a transaction callback ``obj``."""
    return _message(obj, TRANSACTION_HMAC_FIELDS)


def token_hmac_message(obj: Mapping[str, object]) -> str:
    """The string Paymob signs for a card-token callback ``obj``."""
    return _message(obj, TOKEN_HMAC_FIELDS)


def subscription_hmac_message(trigger_type: str, sub_id: int) -> str:
    """The string Paymob signs for a subscription callback."""
    return f"{trigger_type}for{sub_id}"


def sign(message: str, secret: str) -> str:
    """HMAC-SHA512 of ``message`` under ``secret``, lowercase hex."""
    return std_hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha512).hexdigest()


def _matches(message: str, received: str, secret: str) -> bool:
    if not secret or not received:
        return False
    expected = sign(message, secret).encode("ascii")
    return std_hmac.compare_digest(expected, received.strip().lower().encode("utf-8"))


def verify_transaction_hmac(obj: Mapping[str, object], received: str, secret: str) -> bool:
    """True when ``received`` is Paymob's signature of transaction ``obj``."""
    return _matches(transaction_hmac_message(obj), received, secret)


def verify_token_hmac(obj: Mapping[str, object], received: str, secret: str) -> bool:
    """True when ``received`` is Paymob's signature of card-token ``obj``."""
    return _matches(token_hmac_message(obj), received, secret)


def verify_subscription_hmac(trigger_type: str, sub_id: int, received: str, secret: str) -> bool:
    """True when ``received`` is Paymob's signature of a subscription callback."""
    return _matches(subscription_hmac_message(trigger_type, sub_id), received, secret)


__all__ = [
    "TOKEN_HMAC_FIELDS",
    "TRANSACTION_HMAC_FIELDS",
    "sign",
    "subscription_hmac_message",
    "token_hmac_message",
    "transaction_hmac_message",
    "verify_subscription_hmac",
    "verify_token_hmac",
    "verify_transaction_hmac",
]
