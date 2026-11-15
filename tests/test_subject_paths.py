"""Pure helpers behind the Subject screen's steps path (redesign L2)."""

from __future__ import annotations

from lemely.core.history import PaperRecord
from lemely.core.schemas import ExamMetadata, WeakArea
from lemely.web.subject_paths import (
    GOAL_GRADE,
    attempt_dto,
    goal_line,
    marks_to_win,
    paper_code_label,
    session_label,
)


def _meta(
    *, paper: int = 4, variant: int = 2, month: str = "May/June", year: int | None = 2024
) -> ExamMetadata:
    return ExamMetadata(
        subject_code="0580",
        paper_number=paper,
        paper_variant=variant,
        session_month=month,  # type: ignore[arg-type]
        session_year=year,
    )


def _weak(topic: str, lost: int, maximum: int) -> WeakArea:
    return WeakArea(
        topic=topic,
        lost_marks=lost,
        maximum_marks=maximum,
        accuracy=round(1.0 - lost / maximum, 4),
        question_ids=["q1"],
    )


def _record(
    *,
    awarded: int = 61,
    maximum: int = 80,
    grade: str = "A",
    weak: list[WeakArea] | None = None,
    origin: str = "past_paper",
    recorded_at: str = "2024-04-15T10:00:00+00:00",
) -> PaperRecord:
    return PaperRecord(
        student_id="maya",
        metadata=_meta(),
        awarded_marks=awarded,
        maximum_marks=maximum,
        percentage=round(awarded / maximum * 100.0, 2),
        grade=grade,
        weak_areas=weak or [],
        recorded_at=recorded_at,
        origin=origin,  # type: ignore[arg-type]
    )


def test_session_label_shortens_the_month_and_keeps_the_year() -> None:
    assert session_label(_meta(month="May/June", year=2024)) == "May/Jun 2024"
    assert session_label(_meta(month="Oct/Nov", year=2023)) == "Oct/Nov 2023"
    assert session_label(_meta(month="Feb/Mar", year=2024)) == "Feb/Mar 2024"


def test_session_label_without_a_year_is_the_month_alone() -> None:
    assert session_label(_meta(month="Specimen", year=None)) == "Specimen"


def test_paper_code_label_is_code_paper_variant_then_session() -> None:
    assert paper_code_label(_meta(paper=4, variant=2)) == "0580/42 · May/Jun 2024"


def test_goal_line_is_the_a_star_line_in_raw_marks_for_an_exact_boundary() -> None:
    goal = goal_line({"A*": 85.0, "A": 72.0, "B": 60.0}, "exact", _meta(), 80)

    assert goal is not None
    assert goal.grade == GOAL_GRADE == "A*"
    assert goal.marks == 68  # 85% of 80
    assert goal.outOf == 80
    assert goal.source == "exact"
    assert goal.sourceLabel == "May/Jun 2024 boundary"


def test_goal_line_rounds_half_up_not_to_even() -> None:
    # 72.5% of 80 = 58.0; 85.625% of 80 = 68.5 -> 69 (Python's round() would give 68).
    goal = goal_line({"A*": 85.625}, "exact", _meta(), 80)
    assert goal is not None
    assert goal.marks == 69


def test_goal_line_falls_back_to_the_top_grade_when_the_paper_has_no_a_star() -> None:
    # A Core paper carries no A* (or A, or B) boundary; its top grade is C.
    goal = goal_line({"C": 60.0, "D": 45.0, "E": 30.0}, "subject_default", _meta(paper=1), 40)

    assert goal is not None
    assert goal.grade == "C"
    assert goal.marks == 24
    assert goal.sourceLabel == "Average of past boundaries"


def test_goal_line_labels_a_global_estimate_honestly() -> None:
    goal = goal_line({"A*": 80.0}, "global_default", _meta(), 80)
    assert goal is not None
    assert goal.sourceLabel == "Estimated boundary"


def test_goal_line_is_none_without_boundaries_or_marks() -> None:
    assert goal_line({}, "exact", _meta(), 80) is None
    assert goal_line({"A*": 85.0}, "exact", _meta(), 0) is None


def test_attempt_dto_carries_the_full_history_index_and_marks() -> None:
    dto = attempt_dto(6, _record(awarded=61, maximum=80, grade="A"))

    assert dto.id == "6"
    assert dto.awarded == 61
    assert dto.maximum == 80
    assert dto.grade == "A"
    assert dto.recordedAt == "2024-04-15T10:00:00+00:00"
    assert dto.label == "0580/42 · May/Jun 2024"


def test_marks_to_win_is_the_mean_marks_lost_per_paper_that_tested_the_topic() -> None:
    records = [
        _record(weak=[_weak("C2 Algebra", 6, 12), _weak("C7 Vectors", 9, 14)]),
        _record(weak=[_weak("C2 Algebra", 8, 12)]),
    ]

    assert marks_to_win(records) == {"C2 Algebra": 7, "C7 Vectors": 9}


def test_marks_to_win_ignores_quizzes_because_they_are_not_paper_marks() -> None:
    records = [
        _record(weak=[_weak("C2 Algebra", 4, 12)]),
        _record(weak=[_weak("C2 Algebra", 10, 10)], origin="quiz", grade=""),
    ]

    assert marks_to_win(records) == {"C2 Algebra": 4}


def test_marks_to_win_rounds_half_up() -> None:
    records = [
        _record(weak=[_weak("C5 Mensuration", 3, 10)]),
        _record(weak=[_weak("C5 Mensuration", 4, 10)]),
    ]

    assert marks_to_win(records) == {"C5 Mensuration": 4}  # mean 3.5 -> 4
