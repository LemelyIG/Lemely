"""Keyset cursor codec (SPEC section 0 "Paging", section e.1, O21).

The cursor is the only thing a client can tamper with on every tutoring list, so
these tests pin the wire shape (base64url JSON ``{"e": tag, "k": [...]}``) and
every way a decode must refuse: wrong endpoint, wrong arity, wrong type,
malformed text.
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from lemely.core.keyset import CursorError, decode_cursor, encode_cursor

_UUID = uuid.UUID("0b8e2f4a-91c3-4d57-8a6e-3f1d2c4b5a69")
_INSTANT = datetime(2026, 10, 25, 9, 30, 15, 123456, tzinfo=UTC)


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64_json(payload: object) -> str:
    return _b64(json.dumps(payload).encode("utf-8"))


def test_cursor_round_trip_typed() -> None:
    values: list[object] = [Decimal("4.166667"), _INSTANT, _UUID]
    token = encode_cursor("public_directory", values)
    decoded = decode_cursor(
        token, endpoint="public_directory", types=[Decimal, datetime, uuid.UUID]
    )
    assert decoded == (Decimal("4.166667"), _INSTANT, _UUID)
    assert [type(v) for v in decoded] == [Decimal, datetime, uuid.UUID]


def test_cursor_round_trip_preserves_decimal_scale_and_offset_instant() -> None:
    cairo = timezone(timedelta(hours=3))
    instant = datetime(2026, 10, 25, 12, 0, tzinfo=cairo)
    token = encode_cursor("e", [Decimal("4.000000"), instant])
    decoded = decode_cursor(token, endpoint="e", types=[Decimal, datetime])
    assert str(decoded[0]) == "4.000000"
    # Same instant; the offset survives the trip.
    assert decoded[1] == instant
    assert isinstance(decoded[1], datetime)
    assert decoded[1].utcoffset() == timedelta(hours=3)


def test_cursor_round_trip_plain_scalars() -> None:
    values: list[object] = ["abc", 7, True, date(2026, 10, 25), -3]
    token = encode_cursor("scalars", values)
    decoded = decode_cursor(token, endpoint="scalars", types=[str, int, bool, date, int])
    assert decoded == tuple(values)
    assert decoded[2] is True


def test_cursor_wire_shape_is_unpadded_base64url_json_with_tag_and_keys() -> None:
    token = encode_cursor("student_bookings", [_UUID, 5])
    assert "=" not in token
    assert "+" not in token
    assert "/" not in token
    payload = json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
    assert payload == {"e": "student_bookings", "k": [str(_UUID), 5]}


def test_cursor_encoding_is_deterministic() -> None:
    first = encode_cursor("x", [Decimal("4.5"), _UUID])
    second = encode_cursor("x", [Decimal("4.5"), _UUID])
    assert first == second


def test_cursor_from_other_endpoint_raises() -> None:
    token = encode_cursor("public_directory", [_UUID])
    with pytest.raises(CursorError):
        decode_cursor(token, endpoint="student_bookings", types=[uuid.UUID])


@pytest.mark.parametrize(
    ("values", "types"),
    [
        pytest.param([_UUID], [uuid.UUID, uuid.UUID], id="too_few_values"),
        pytest.param([_UUID, _UUID], [uuid.UUID], id="too_many_values"),
        pytest.param([_UUID], [datetime], id="uuid_decoded_as_datetime"),
        pytest.param([_INSTANT], [uuid.UUID], id="datetime_decoded_as_uuid"),
        pytest.param([Decimal("4.5")], [int], id="decimal_text_decoded_as_int"),
        pytest.param([7], [str], id="int_decoded_as_str"),
        pytest.param(["7"], [int], id="str_decoded_as_int"),
        pytest.param([True], [int], id="bool_decoded_as_int"),
        pytest.param([1], [bool], id="int_decoded_as_bool"),
        pytest.param([7], [Decimal], id="json_number_decoded_as_decimal"),
        pytest.param([7], [uuid.UUID], id="json_number_decoded_as_uuid"),
        pytest.param([date(2026, 1, 2)], [datetime], id="date_decoded_as_datetime"),
    ],
)
def test_cursor_wrong_arity_or_type_raises(values: list[object], types: list[type]) -> None:
    token = encode_cursor("e", values)
    with pytest.raises(CursorError):
        decode_cursor(token, endpoint="e", types=types)


@pytest.mark.parametrize(
    ("raw", "kind"),
    [
        pytest.param("not-a-uuid", uuid.UUID, id="bad_uuid"),
        pytest.param("{0b8e2f4a-91c3-4d57-8a6e-3f1d2c4b5a69}", uuid.UUID, id="braced_uuid"),
        pytest.param("0B8E2F4A91C34D578A6E3F1D2C4B5A69", uuid.UUID, id="non_canonical_uuid"),
        pytest.param("NaN", Decimal, id="decimal_nan"),
        pytest.param("Infinity", Decimal, id="decimal_infinity"),
        pytest.param("1e999999", Decimal, id="decimal_exponent_form"),
        pytest.param("4,5", Decimal, id="decimal_comma"),
        pytest.param("", Decimal, id="decimal_empty"),
        pytest.param("\U00000664.\U00000665", Decimal, id="decimal_arabic_indic_digits"),
        pytest.param("\U0000ff14.\U0000ff15", Decimal, id="decimal_fullwidth_digits"),
        pytest.param("a\x00b", str, id="string_with_nul"),
        pytest.param("x" * 257, str, id="string_over_256_characters"),
        pytest.param("9999-12-31T23:59:59-23:59", datetime, id="instant_overflowing_utc"),
        pytest.param("0001-01-01T00:00:00+23:59", datetime, id="instant_underflowing_utc"),
        pytest.param("2026-10-25T09:30:15", datetime, id="naive_datetime"),
        pytest.param("yesterday", datetime, id="datetime_garbage"),
        pytest.param("2026-13-45", date, id="date_garbage"),
    ],
)
def test_cursor_bad_text_for_a_typed_slot_raises(raw: str, kind: type) -> None:
    token = _b64_json({"e": "e", "k": [raw]})
    with pytest.raises(CursorError):
        decode_cursor(token, endpoint="e", types=[kind])


@pytest.mark.parametrize(
    "token",
    [
        pytest.param("", id="empty"),
        pytest.param("!!!!", id="not_base64_alphabet"),
        pytest.param("ab cd", id="space_inside"),
        pytest.param("a", id="impossible_length"),
        pytest.param(_b64(b"\xff\xfe\xfd"), id="not_utf8"),
        pytest.param(_b64(b"not json"), id="not_json"),
        pytest.param(_b64_json([1, 2]), id="json_array_not_object"),
        pytest.param(_b64_json("text"), id="json_string"),
        pytest.param(_b64_json({"e": "e"}), id="missing_keys_field"),
        pytest.param(_b64_json({"k": []}), id="missing_endpoint_field"),
        pytest.param(_b64_json({"e": "e", "k": [], "x": 1}), id="extra_field"),
        pytest.param(_b64_json({"e": 5, "k": []}), id="endpoint_not_str"),
        pytest.param(_b64_json({"e": "e", "k": "abc"}), id="keys_not_list"),
        pytest.param("A" * 5000, id="oversize"),
    ],
)
def test_cursor_malformed_base64_raises(token: str) -> None:
    with pytest.raises(CursorError):
        decode_cursor(token, endpoint="e", types=[])


def test_cursor_int_is_bounded_to_int64() -> None:
    low, high = -(2**63), 2**63 - 1
    for ok in (low, 0, high):
        token = encode_cursor("e", [ok])
        assert decode_cursor(token, endpoint="e", types=[int]) == (ok,)
    for bad in (low - 1, high + 1, 10**300, -(10**300)):
        token = encode_cursor("e", [bad])
        with pytest.raises(CursorError):
            decode_cursor(token, endpoint="e", types=[int])


def test_cursor_string_up_to_256_characters_round_trips() -> None:
    token = encode_cursor("e", ["x" * 256])
    assert decode_cursor(token, endpoint="e", types=[str]) == ("x" * 256,)


def test_cursor_error_is_a_value_error_so_routers_can_map_it_to_422() -> None:
    assert issubclass(CursorError, ValueError)


def test_empty_key_list_round_trips() -> None:
    token = encode_cursor("e", [])
    assert decode_cursor(token, endpoint="e", types=[]) == ()


def test_encode_refuses_naive_datetime_and_unsupported_types() -> None:
    with pytest.raises(ValueError, match="timezone"):
        encode_cursor("e", [datetime(2026, 10, 25, 9, 0)])
    with pytest.raises(TypeError):
        encode_cursor("e", [None])
    with pytest.raises(TypeError):
        encode_cursor("e", [1.5])
    with pytest.raises(ValueError, match="finite"):
        encode_cursor("e", [Decimal("NaN")])


def test_decode_refuses_unsupported_slot_type() -> None:
    token = encode_cursor("e", [1])
    with pytest.raises(TypeError):
        decode_cursor(token, endpoint="e", types=[float])
