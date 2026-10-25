"""Directory helpers: availability filter, public names, student labels, zone labels.

Specs: SPEC section b.2 (SP1 time-of-day buckets), section a.2 (``public_first_name``,
SC-25), section 0 "Display names" (F12), section e.1.
"""

from __future__ import annotations

import hashlib
import itertools
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

import pytest

from lemely.core.tutor_directory import (
    TIME_OF_DAY_MINUTES,
    InvalidPublicNameError,
    public_name,
    rule_matches,
    student_label,
    validate_public_name,
    zone_label,
)

_SPEC = Path(__file__).resolve().parents[1] / "docs" / "tutoring" / "SPEC.md"


@dataclass(frozen=True, slots=True)
class _Rule:
    """Structural stand-in for ``core.booking.AvailabilityRule`` (T03 owns that class)."""

    iso_weekday: int
    start_minute: int
    end_minute: int


_BUCKETS = ("morning", "afternoon", "evening")


def _spec_bucket_minutes() -> dict[str, tuple[int, int]]:
    """Read the bucket bounds from the SPEC text, independent of the module under test."""
    spec = _SPEC.read_text(encoding="utf-8")
    line = re.search(r"^TIME_OF_DAY_MINUTES:.*#\s*(?P<pairs>\(.*\))\s*$", spec, re.MULTILINE)
    assert line is not None
    pairs = [(int(a), int(b)) for a, b in re.findall(r"\((\d+),\s*(\d+)\)", line.group("pairs"))]
    assert len(pairs) == 3
    return dict(zip(_BUCKETS, pairs, strict=True))


def test_time_of_day_minutes_equal_spec_text() -> None:
    assert dict(TIME_OF_DAY_MINUTES) == _spec_bucket_minutes()
    assert tuple(TIME_OF_DAY_MINUTES) == _BUCKETS


def _brute_force(
    rule: _Rule, days: frozenset[int], times: frozenset[str], buckets: dict[str, tuple[int, int]]
) -> bool:
    """Minute-by-minute oracle: does any minute of the rule fall in a selected (day, bucket)?"""
    if days and rule.iso_weekday not in days:
        return False
    if not times:
        return True
    return any(
        buckets[t][0] <= minute < buckets[t][1]
        for t in times
        for minute in range(rule.start_minute, rule.end_minute)
    )


_RULE_GRID = [
    _Rule(1, 360, 720),  # exactly the morning bucket
    _Rule(1, 0, 360),  # ends where morning starts
    _Rule(1, 359, 361),  # straddles the morning start by one minute each side
    _Rule(2, 719, 721),  # straddles morning / afternoon
    _Rule(3, 720, 1020),  # exactly afternoon
    _Rule(3, 1019, 1021),  # straddles afternoon / evening
    _Rule(4, 1020, 1080),  # evening, from its first minute
    _Rule(4, 1319, 1440),  # last evening minute through midnight
    _Rule(5, 1320, 1440),  # starts where evening ends
    _Rule(5, 600, 1100),  # spans three buckets
    _Rule(6, 700, 760),  # short, over a boundary
    _Rule(7, 0, 1440),  # all day
]
_DAY_SETS = [
    frozenset[int](),
    frozenset({1}),
    frozenset({3, 4}),
    frozenset({5, 6, 7}),
    frozenset({1, 2, 3, 4, 5, 6, 7}),
]
_TIME_SETS = [
    frozenset[str](),
    frozenset({"morning"}),
    frozenset({"afternoon"}),
    frozenset({"evening"}),
    frozenset({"morning", "evening"}),
    frozenset(_BUCKETS),
]


def test_rule_matches_table() -> None:
    buckets = _spec_bucket_minutes()
    cases = list(itertools.product(_RULE_GRID, _DAY_SETS, _TIME_SETS))
    assert len(cases) == len(_RULE_GRID) * len(_DAY_SETS) * len(_TIME_SETS) == 360
    mismatches = [
        (rule, days, times)
        for rule, days, times in cases
        if rule_matches(rule, days, times) != _brute_force(rule, days, times, buckets)
    ]
    assert mismatches == []


@pytest.mark.parametrize(
    ("rule", "days", "times", "expected"),
    [
        pytest.param(_Rule(1, 360, 720), frozenset({1}), frozenset({"morning"}), True, id="exact"),
        pytest.param(_Rule(1, 360, 720), frozenset({2}), frozenset({"morning"}), False, id="day"),
        pytest.param(_Rule(1, 360, 720), frozenset({1}), frozenset({"evening"}), False, id="slot"),
        pytest.param(_Rule(1, 0, 360), frozenset(), frozenset({"morning"}), False, id="touch"),
        pytest.param(_Rule(1, 1020, 1080), frozenset(), frozenset({"afternoon"}), False, id="edge"),
        pytest.param(_Rule(1, 1019, 1080), frozenset(), frozenset({"afternoon"}), True, id="in1"),
        pytest.param(_Rule(1, 0, 1440), frozenset(), frozenset(), True, id="no_filters"),
        pytest.param(_Rule(2, 600, 700), frozenset({2}), frozenset(), True, id="day_only"),
        pytest.param(_Rule(2, 600, 700), frozenset({3}), frozenset(), False, id="day_only_no"),
    ],
)
def test_rule_matches_named_cases(
    rule: _Rule, days: frozenset[int], times: frozenset[str], expected: bool
) -> None:
    assert rule_matches(rule, days, times) is expected


@pytest.mark.parametrize(
    ("first", "initial", "expected"),
    [
        ("Sara", "M", "Sara M."),
        ("Sara", "m", "Sara M."),
        ("Sara", None, "Sara"),
        ("Sara", "", "Sara"),
        ("Sara", " ", "Sara"),
        ("  Sara ", "M", "Sara M."),
        ("Mary-Jane", "O", "Mary-Jane O."),
        (
            "\U00000633\U00000627\U00000631\U00000629",
            "\U00000645",
            "\U00000633\U00000627\U00000631\U00000629 \U00000645.",
        ),
        ("Stra\U000000dfe", "\U000000df", "Stra\U000000dfe \U000000df."),
    ],
)
def test_public_name_formats_initial(first: str, initial: str | None, expected: str) -> None:
    assert public_name(first, initial) == expected


@pytest.mark.parametrize(
    "first",
    [
        "Sara1",
        "4ra",
        "Sara.",
        "S.ra",
        "sara.com",
        "http://sara",
        "sara/tutor",
        "sara@gmail",
        "@sara",
        "sara:tutor",
        "Sara_M",
        "Sara!",
        "Sara*",
        "Sara+",
        "(Sara)",
        "Sara\n",
        "Sa\tra",
        "\U0000202eSara",  # right-to-left override
        "Sara\U0000202d",
        "Sa\U0000202ara",
        "Sa\U0000202bra",
        "Sa\U0000202cra",
        "Sa\U00002066ra",
        "Sa\U00002067ra",
        "Sa\U00002068ra",
        "Sa\U00002069ra",
        "Sa\U0000200fra",  # right-to-left mark
        "Sa\U0000200dra",  # zero-width joiner
        "Sa\U0000200bra",  # zero-width space
        "\U00000661\U00000662\U00000663",  # Arabic-Indic digits
        "\U0000ff11Sara",  # fullwidth digit
        "Sara\U000000a0Lee",  # non-breaking space is not the allowed space
        "\U00000301Sara",  # a name cannot start with a bare combining accent
        "-Sara",
        "Sara-",
        "'Sara",
        "Sara'",
        " ",
        "",
        "   ",
        "S" * 41,
    ],
)
def test_public_first_name_charset_rejects_digits_urls_bidi(first: str) -> None:
    with pytest.raises(InvalidPublicNameError):
        validate_public_name(first, "M")


@pytest.mark.parametrize(
    "initial", ["1", ".", "@", "MM", "\U0000202e", "-", " M", "\U00000661", "\U0000200f"]
)
def test_public_last_initial_must_be_one_letter(initial: str) -> None:
    with pytest.raises(InvalidPublicNameError):
        validate_public_name("Sara", initial)


@pytest.mark.parametrize(
    ("first", "initial"),
    [
        ("Sara", "M"),
        ("Sara", None),
        ("Mary-Jane", "O"),
        ("O'Brien", "B"),
        ("D\U00002019Arcy", None),
        ("Anne Marie", "L"),
        ("\U00000633\U00000627\U00000631\U00000629", "\U00000645"),
        ("\U00000645\U0000062d\U00000645\U0000062f", None),
        # Arabic with diacritics (combining marks) is still a name.
        (
            "\U00000645\U0000064f\U0000062d\U0000064e\U00000645\U00000651\U0000064e\U0000062f",
            "\U00000623",
        ),
        ("Jos\U000000e9", "\U000000c1"),
        ("Zo\U000000eb", None),
        ("S" * 40, "M"),
    ],
)
def test_validate_public_name_accepts_arabic(first: str, initial: str | None) -> None:
    validate_public_name(first, initial)


def test_invalid_public_name_error_is_a_value_error() -> None:
    assert issubclass(InvalidPublicNameError, ValueError)


@pytest.mark.parametrize(
    "display_name",
    [
        "bob@example.com",
        "@bob",
        "a@b",
        " x@y.z ",
        "Bob (bob@example.com)",
        "\U0000ff20bob",  # fullwidth commercial at, folds to "@" under NFKC
    ],
)
def test_student_label_never_contains_at(display_name: str) -> None:
    label = student_label(display_name, uuid.UUID(int=1))
    assert "@" not in label
    assert "\U0000ff20" not in label
    assert label.startswith("Student ")


def test_student_label_uses_trimmed_display_name() -> None:
    assert student_label("  Omar Hassan  ", uuid.UUID(int=7)) == "Omar Hassan"
    assert (
        student_label("\U00000639\U00000645\U00000631", uuid.UUID(int=7))
        == "\U00000639\U00000645\U00000631"
    )


@pytest.mark.parametrize("blank", [None, "", "   ", "\t\n", "\U000000a0"])
def test_student_label_falls_back_to_hashed_suffix(blank: str | None) -> None:
    user_id = uuid.UUID("0b8e2f4a-91c3-4d57-8a6e-3f1d2c4b5a69")
    expected_hex = hashlib.sha256(str(user_id).encode("ascii")).hexdigest()[:4].upper()
    label = student_label(blank, user_id)
    assert label == f"Student {expected_hex}"
    assert re.fullmatch(r"Student [0-9A-F]{4}", label)


def test_student_label_fallback_is_stable_and_differs_between_students() -> None:
    first = uuid.UUID(int=1)
    second = uuid.UUID(int=2)
    assert student_label(None, first) == student_label(None, first)
    assert student_label(None, first) != student_label(None, second)


def test_student_label_fallback_does_not_leak_the_user_id() -> None:
    user_id = uuid.UUID("0b8e2f4a-91c3-4d57-8a6e-3f1d2c4b5a69")
    label = student_label(None, user_id)
    assert user_id.hex not in label


@pytest.mark.parametrize(
    ("zone", "label"),
    [
        ("Africa/Cairo", "Cairo time"),
        ("America/New_York", "New York time"),
        ("Europe/London", "London time"),
        ("America/Argentina/Buenos_Aires", "Buenos Aires time"),
        ("UTC", "UTC time"),
    ],
)
def test_zone_label_cairo(zone: str, label: str) -> None:
    assert zone_label(zone) == label


@pytest.mark.parametrize("zone", ["", "  ", "Africa/"])
def test_zone_label_rejects_empty_zone(zone: str) -> None:
    with pytest.raises(ValueError, match="zone"):
        zone_label(zone)
