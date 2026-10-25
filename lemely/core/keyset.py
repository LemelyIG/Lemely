"""Opaque keyset cursors for the tutoring list endpoints (SPEC section 0 "Paging", O21).

A list endpoint pages by the sort key of its last row, not by an offset, so the
cursor is just that key. It is the one value a client can edit between requests,
so the codec is deliberately strict about everything it accepts back:

* The wire form is ``base64url(JSON {"e": <endpoint tag>, "k": [<sort-key values>]})``
  without padding, and nothing else: no extra fields, no extra whitespace
  tolerance beyond what ``json`` gives, a bounded length.
* The endpoint tag travels with the key, so a cursor minted by one list cannot
  be replayed against another (a directory cursor is not a bookings cursor).
* Decoding is typed per endpoint. Each slot declares the Python type it expects
  and the decoder refuses any other: a UUID slot only takes a canonical UUID
  string, a ``Decimal`` slot only plain decimal text (no exponent, no NaN), a
  ``datetime`` slot only a timezone-aware ISO instant. Values reach SQL only as
  bound parameters, but a tampered value should still die here as a 422 rather
  than reach the driver as a 500.

Pure: no I/O, no framework. Routers turn :class:`CursorError` into a 422.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

# A directory cursor is a decimal, an instant and a UUID: about 150 characters
# once encoded. 512 leaves ample room and bounds the work a hostile token costs.
_MAX_TOKEN_LENGTH: Final = 512

# base64url alphabet only: ``b64decode(altchars=...)`` would also let ``+`` and ``/`` through.
_TOKEN_CHARS: Final = re.compile(r"[A-Za-z0-9_-]+")

# Plain decimal text only. Exponent forms ("1e999999") and NaN/Infinity are
# valid ``Decimal`` input but never something this codec writes.
_DECIMAL_TEXT: Final = re.compile(r"-?\d{1,30}(?:\.\d{1,30})?")


class CursorError(ValueError):
    """A cursor token is malformed, for another endpoint, or of the wrong shape."""


def encode_cursor(endpoint: str, values: Sequence[object]) -> str:
    """Encode ``values`` (the sort key of the last row) for ``endpoint``.

    Raises ``TypeError`` for a value type the codec cannot round-trip and
    ``ValueError`` for a naive datetime or a non-finite decimal: those are bugs
    in the calling endpoint, not bad client input.
    """
    payload = {"e": endpoint, "k": [_encode_value(v) for v in values]}
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(token: str, *, endpoint: str, types: Sequence[type]) -> tuple[object, ...]:
    """Decode ``token`` for ``endpoint``, one value per entry of ``types``.

    Raises :class:`CursorError` for anything a client could have produced by
    editing a cursor: bad base64, bad JSON, another endpoint's tag, the wrong
    number of values, or a value that does not parse as its declared type.
    Raises ``TypeError`` if ``types`` names a type the codec does not support
    (a programming error, checked before the token is looked at).
    """
    for kind in types:
        if kind not in _DECODERS:
            raise TypeError(f"unsupported cursor value type: {kind!r}")
    tag, keys = _parse_payload(token)
    if tag != endpoint:
        raise CursorError("cursor belongs to a different list")
    if len(keys) != len(types):
        raise CursorError("cursor has the wrong number of values")
    return tuple(_DECODERS[kind](raw) for kind, raw in zip(types, keys, strict=True))


def _encode_value(value: object) -> object:
    # ``bool`` is an ``int`` subclass, so it must be tested before ``int``; and
    # ``datetime`` is a ``date`` subclass, so likewise before ``date``.
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("cursor decimals must be finite")
        return format(value, "f")
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("cursor datetimes need a timezone")
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"unsupported cursor value type: {type(value).__name__}")


def _parse_payload(token: str) -> tuple[str, list[object]]:
    if not isinstance(token, str) or len(token) > _MAX_TOKEN_LENGTH:
        raise CursorError("cursor is empty or too long")
    if _TOKEN_CHARS.fullmatch(token) is None:
        raise CursorError("cursor is not valid")
    try:
        padded = token + "=" * (-len(token) % 4)
        raw = base64.b64decode(padded.encode("ascii"), altchars=b"-_", validate=True)
        parsed = json.loads(raw.decode("utf-8"))
    except (binascii.Error, UnicodeError, ValueError) as exc:
        raise CursorError("cursor is not valid") from exc
    if not isinstance(parsed, dict) or set(parsed) != {"e", "k"}:
        raise CursorError("cursor has the wrong shape")
    tag, keys = parsed["e"], parsed["k"]
    if not isinstance(tag, str) or not isinstance(keys, list):
        raise CursorError("cursor has the wrong shape")
    return tag, keys


def _decode_str(raw: object) -> str:
    if not isinstance(raw, str):
        raise CursorError("cursor value is not text")
    return raw


def _decode_int(raw: object) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise CursorError("cursor value is not an integer")
    return raw


def _decode_bool(raw: object) -> bool:
    if not isinstance(raw, bool):
        raise CursorError("cursor value is not a boolean")
    return raw


def _decode_uuid(raw: object) -> uuid.UUID:
    if not isinstance(raw, str):
        raise CursorError("cursor value is not a UUID")
    try:
        parsed = uuid.UUID(raw)
    except ValueError as exc:
        raise CursorError("cursor value is not a UUID") from exc
    if str(parsed) != raw:
        # ``uuid.UUID`` also accepts braces, urn: prefixes and bare hex; the
        # codec only ever writes the canonical form, so only that comes back.
        raise CursorError("cursor value is not a canonical UUID")
    return parsed


def _decode_decimal(raw: object) -> Decimal:
    if not isinstance(raw, str) or _DECIMAL_TEXT.fullmatch(raw) is None:
        raise CursorError("cursor value is not a decimal")
    try:
        return Decimal(raw)
    except InvalidOperation as exc:  # pragma: no cover - the pattern already guarantees a parse
        raise CursorError("cursor value is not a decimal") from exc


def _decode_datetime(raw: object) -> datetime:
    if not isinstance(raw, str):
        raise CursorError("cursor value is not an instant")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise CursorError("cursor value is not an instant") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CursorError("cursor instant has no timezone")
    return parsed


def _decode_date(raw: object) -> date:
    if not isinstance(raw, str):
        raise CursorError("cursor value is not a date")
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise CursorError("cursor value is not a date") from exc


_DECODERS: Final[dict[type, Callable[[object], object]]] = {
    str: _decode_str,
    int: _decode_int,
    bool: _decode_bool,
    uuid.UUID: _decode_uuid,
    Decimal: _decode_decimal,
    datetime: _decode_datetime,
    date: _decode_date,
}
