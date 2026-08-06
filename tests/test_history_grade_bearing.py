"""Tests for the grade-bearing predicate (P3.5 chunk G, docs/quiz-model.md §5).

Pure unit tests: the predicate is the single place the whole codebase decides
whether a record may back a grade, boundary, or paper-comparison claim, so it
is pinned directly here as well as through its consumers in
``tests/test_class_analytics.py`` and ``tests/test_at_risk.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from lemely.core.history import (
    GRADE_ORDER,
    PaperOrigin,
    PaperRecord,
    is_grade_bearing,
)
from lemely.core.schemas import ExamMetadata


def _record(*, grade: str = "B", origin: PaperOrigin = "past_paper") -> PaperRecord:
    return PaperRecord(
        student_id="alice",
        metadata=ExamMetadata(
            subject_code="0625",
            paper_number=1,
            paper_variant=2,
            session_month="May/June",
            session_year=2020,
        ),
        awarded_marks=65,
        maximum_marks=80,
        percentage=81.25,
        grade=grade,
        weak_areas=[],
        recorded_at=datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
    ).model_copy(update={"origin": origin})


def test_origin_defaults_to_past_paper() -> None:
    """The field is additive: a record constructed without it is a past paper,
    so every call site that predates chunk G keeps its meaning."""
    record = PaperRecord(
        student_id="alice",
        metadata=ExamMetadata(
            subject_code="0625",
            paper_number=1,
            paper_variant=2,
            session_month="May/June",
            session_year=2020,
        ),
        awarded_marks=65,
        maximum_marks=80,
        percentage=81.25,
        grade="B",
        weak_areas=[],
        recorded_at=datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
    )
    assert record.origin == "past_paper"
    assert is_grade_bearing(record)


@pytest.mark.parametrize("grade", GRADE_ORDER)
def test_every_grade_on_the_ladder_is_grade_bearing(grade: str) -> None:
    assert is_grade_bearing(_record(grade=grade))


def test_quiz_is_never_grade_bearing_even_with_a_grade_string() -> None:
    """Origin is checked independently of the grade field.

    A quiz should never carry a grade, but if some future code path wrote one
    anyway, the predicate must still refuse it — otherwise the guarantee
    degrades to "trust whatever wrote the row".
    """
    assert not is_grade_bearing(_record(grade="A*", origin="quiz"))


def test_custom_paper_is_not_grade_bearing() -> None:
    """T-11 custom papers have no official boundaries, so they cannot back a
    predicted grade or sit in a paper comparison against real CAIE papers."""
    assert not is_grade_bearing(_record(origin="custom_paper"))


@pytest.mark.parametrize("grade", ["", "Z", "b", "A+", "pass", "9"])
def test_grade_off_the_ladder_is_not_grade_bearing(grade: str) -> None:
    """An unrecognised grade string cannot back a grade claim. Case matters:
    "b" is not "B", and silently upper-casing would invent a grade the marking
    path never asserted."""
    assert not is_grade_bearing(_record(grade=grade))
