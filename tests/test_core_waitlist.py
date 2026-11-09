"""Pure waitlist rules: phone, exam-session window, CSV guard, token hashing, vocabularies."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from lemely.core.waitlist import (
    ALL_SUBJECTS,
    LEVELS,
    TOP_SUBJECTS,
    csv_safe,
    exam_session_options,
    hash_token,
    is_valid_exam_session,
    new_completion_token,
    normalise_email,
    normalise_phone,
    phone_for_export,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("01001234567", "+201001234567"),
        ("0100 123 4567", "+201001234567"),
        ("1001234567", "+201001234567"),
        ("+20 100 123 4567", "+201001234567"),
        ("0020 100 123 4567", "+201001234567"),
        ("(010) 0123-4567", "+201001234567"),
        ("01201234567", "+201201234567"),
        ("+44 7700 900123", "+447700900123"),
        ("+14155552671", "+14155552671"),
    ],
)
def test_phone_numbers_normalise_to_e164(raw: str, expected: str) -> None:
    assert normalise_phone(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", "abc", "0100123", "01301234567", "+20 2 2345 6789", "+0123456789", "+1234", "12 34 x"],
)
def test_bad_phone_numbers_are_refused(raw: str) -> None:
    assert normalise_phone(raw) is None


def test_exam_sessions_are_derived_from_the_date() -> None:
    # In November 2026 the Oct/Nov 2026 sitting is already under way: not offered.
    assert exam_session_options(date(2026, 11, 8)) == [
        ("2027-mj", "May/June 2027"),
        ("2027-on", "Oct/Nov 2027"),
        ("2028-mj", "May/June 2028"),
        ("2028-on", "Oct/Nov 2028"),
    ]
    # Mid-January: the next sitting is this year's May/June.
    assert exam_session_options(date(2027, 1, 15))[0] == ("2027-mj", "May/June 2027")
    # Between the sittings, Oct/Nov is next.
    assert exam_session_options(date(2027, 7, 1))[0] == ("2027-on", "Oct/Nov 2027")


def test_exam_session_window_validation() -> None:
    today = date(2026, 11, 8)
    assert is_valid_exam_session("2027-mj", today)
    assert is_valid_exam_session("2028-on", today)
    assert not is_valid_exam_session("2026-on", today)  # already started
    assert not is_valid_exam_session("2026-mj", today)  # past
    assert not is_valid_exam_session("2029-mj", today)  # beyond the window
    assert not is_valid_exam_session("2027-xx", today)
    assert not is_valid_exam_session("May 2027", today)


@pytest.mark.parametrize("lead", ["=", "+", "-", "@", "\t", "\r"])
def test_csv_cells_that_could_be_formulas_are_neutralised(lead: str) -> None:
    assert csv_safe(f"{lead}HYPERLINK(1)") == f"'{lead}HYPERLINK(1)"


def test_csv_leaves_ordinary_cells_and_stored_phones_alone() -> None:
    assert csv_safe("Cairo Centre") == "Cairo Centre"
    assert csv_safe(None) == ""
    assert csv_safe("+201001234567") == "+201001234567"  # digits only cannot be a formula
    assert csv_safe("+20 100 123 4567") == "+20 100 123 4567"
    assert csv_safe("+1 +1") == "'+1 +1"
    assert csv_safe("+20 1=1") == "'+20 1=1"
    assert csv_safe("+1+1") == "'+1+1"


def test_completion_tokens_are_random_and_only_their_hash_is_derivable() -> None:
    first, first_hash = new_completion_token()
    second, _ = new_completion_token()
    assert first != second
    assert first_hash == hash_token(first)
    assert first not in first_hash
    assert len(first_hash) == 64


def test_email_is_normalised_for_uniqueness() -> None:
    assert normalise_email("  Sara@Example.COM ") == "sara@example.com"


def test_subject_catalogue_is_deduplicated_alphabetical_and_contains_the_top_eight() -> None:
    labels = list(ALL_SUBJECTS.values())
    assert labels == sorted(labels, key=str.lower)
    assert len(set(labels)) == len(labels)
    assert 40 <= len(ALL_SUBJECTS) <= 60
    assert "other" not in ALL_SUBJECTS
    assert [ALL_SUBJECTS[v] for v in TOP_SUBJECTS] == [
        "Mathematics",
        "Physics",
        "Chemistry",
        "Biology",
        "English",
        "Additional Mathematics",
        "Computer Science",
        "Business",
    ]


def test_igcse_is_not_a_level() -> None:
    assert LEVELS == ("o_level", "as_level", "a_level")


@pytest.mark.parametrize(
    ("stored", "shown"),
    [
        ("+201001234567", "+20 100 123 4567"),
        ("+447700900123", "+44 770 090 0123"),
        ("+14155552671", "+1 415 555 2671"),
        (None, None),
    ],
)
def test_phone_export_form_is_spaced_so_spreadsheets_keep_it_as_text(
    stored: str | None, shown: str | None
) -> None:
    assert phone_for_export(stored) == shown
    if shown is not None:
        assert csv_safe(shown) == shown  # and the formula guard leaves it alone


def test_exam_session_validation_has_a_one_day_grace_either_side() -> None:
    # On 1 May 2027 May/June has just stopped being "upcoming", but a browser a day behind
    # (or a form opened yesterday) was shown it: still accepted.
    assert exam_session_options(date(2027, 5, 1))[0][0] == "2027-on"
    assert is_valid_exam_session("2027-mj", date(2027, 5, 1))
    assert not is_valid_exam_session("2027-mj", date(2027, 5, 2))
    # On 30 April a browser a day ahead was shown a window that reaches one sitting further.
    assert "2029-mj" not in {v for v, _ in exam_session_options(date(2027, 4, 30))}
    assert is_valid_exam_session("2029-mj", date(2027, 4, 30))
    assert not is_valid_exam_session("2029-on", date(2027, 4, 30))


_PHONE_CASES = json.loads(
    (Path(__file__).parent / "fixtures" / "waitlist_phone_cases.json").read_text(encoding="utf-8")
)["phone"]


@pytest.mark.parametrize("case", _PHONE_CASES, ids=lambda c: c["raw"] or "<blank>")
def test_phone_fixture_cases(case: dict[str, str | None]) -> None:
    """The shared fixture the TS validator is also tested against (web/tests/unit)."""
    assert normalise_phone(str(case["raw"])) == case["e164"]
