"""Unit tests for the pure builders behind ``GET /api/student/home``."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from lemely.core.history import PaperRecord
from lemely.core.schemas import ExamMetadata, WeakArea
from lemely.io.det.profiles import get_profile
from lemely.web.schemas_student_home import TeacherReplyDTO
from lemely.web.services.student_home import (
    build_activity,
    build_floor,
    build_recent_papers,
    build_stats,
    build_win_back,
    focus_question,
    next_boundary,
    paper_moment,
    question_label,
)

NOW = datetime(2026, 11, 12, 15, 0, tzinfo=UTC)
BOUNDARIES = {"A*": 90.0, "A": 80.0, "B": 70.0, "C": 60.0, "D": 50.0, "E": 40.0}


def _boundaries(_metadata: ExamMetadata) -> dict[str, float]:
    return dict(BOUNDARIES)


def _weak(topic: str, lost: int, maximum: int, qid: str) -> WeakArea:
    return WeakArea(
        topic=topic,
        lost_marks=lost,
        maximum_marks=maximum,
        accuracy=round(1.0 - lost / maximum, 4),
        question_ids=[qid],
    )


def _paper(
    *,
    code: str = "0580",
    paper: int = 4,
    awarded: int = 61,
    maximum: int = 80,
    grade: str = "B",
    at: datetime = NOW - timedelta(hours=2),
    weak: list[WeakArea] | None = None,
    origin: str = "past_paper",
    attempt_id: str | None = None,
) -> PaperRecord:
    return PaperRecord(
        student_id="s",
        metadata=ExamMetadata(
            subject_code=code,
            paper_number=paper,
            paper_variant=2,
            session_month="May/June",
            session_year=2024,
        ),
        awarded_marks=awarded,
        maximum_marks=maximum,
        percentage=round(awarded / maximum * 100, 2),
        grade=grade,
        weak_areas=weak or [],
        recorded_at=at.isoformat(),
        origin=origin,  # type: ignore[arg-type]
        attempt_id=attempt_id,
    )


def test_next_boundary_returns_the_next_grade_and_rounded_up_points() -> None:
    assert next_boundary(76, BOUNDARIES) == ("A", 4)
    assert next_boundary(79.2, BOUNDARIES) == ("A", 1)
    assert next_boundary(95, BOUNDARIES) == (None, None)


def test_floor_grades_each_subject_from_its_weighted_mean() -> None:
    records = [
        _paper(code="0580", awarded=48, maximum=80, grade="C", at=NOW - timedelta(days=20)),
        _paper(code="0580", awarded=61, maximum=80, grade="B", at=NOW - timedelta(days=2)),
        _paper(code="0625", awarded=27, maximum=40, grade="C", at=NOW - timedelta(days=9)),
    ]
    floor = build_floor(records, _boundaries)
    assert [f.code for f in floor] == ["0580", "0625"]
    maths = floor[0]
    # (48 + 61) / 160 = 68% -> C, next B at 70 -> 2 points.
    assert (maths.grade, maths.nextGrade, maths.pointsToNext, maths.papers) == ("C", "B", 2, 2)
    # The grade before the latest paper: 48/80 = 60% -> C.
    assert maths.previousGrade == "C"
    assert maths.name == (get_profile("0580").name or "0580")
    physics = floor[1]
    assert physics.previousGrade is None


def test_floor_ignores_quiz_records() -> None:
    records = [_paper(origin="quiz", awarded=10, maximum=10, grade="A*")]
    assert build_floor(records, _boundaries) == []


def test_win_back_ranks_topics_from_each_subjects_latest_paper() -> None:
    records = [
        _paper(code="0580", at=NOW - timedelta(days=30), weak=[_weak("Old topic", 20, 30, "1")]),
        _paper(
            code="0580",
            at=NOW - timedelta(days=2),
            weak=[_weak("Vectors", 9, 12, "8"), _weak("Algebra", 0, 10, "2")],
        ),
        _paper(code="0625", at=NOW - timedelta(days=5), weak=[_weak("Waves", 7, 10, "3")]),
        _paper(code="0606", at=NOW - timedelta(days=6), weak=[_weak("Inequalities", 6, 9, "5")]),
        _paper(
            code="0606", at=NOW - timedelta(days=6), origin="quiz", weak=[_weak("Q", 50, 60, "9")]
        ),
    ]
    rows = build_win_back(records)
    assert [(r.topic, r.subjectCode, r.marks) for r in rows] == [
        ("Vectors", "0580", 9),
        ("Waves", "0625", 7),
        ("Inequalities", "0606", 6),
    ]


def test_recent_papers_are_newest_first_with_history_indices_as_ids() -> None:
    records = [
        _paper(code="0580", at=NOW - timedelta(days=9)),
        _paper(origin="quiz", at=NOW - timedelta(days=8)),
        _paper(code="0625", at=NOW - timedelta(days=1)),
    ]
    rows = build_recent_papers(records)
    assert [(r.paperId, r.subjectCode) for r in rows] == [("2", "0625"), ("0", "0580")]


def test_focus_question_picks_most_lost_or_easiest_win() -> None:
    record = _paper(weak=[_weak("Vectors", 9, 12, "8"), _weak("Units", 1, 10, "3")])
    assert focus_question(record, easiest=False) == "8"
    assert focus_question(record, easiest=True) == "3"
    assert focus_question(_paper(weak=[]), easiest=False) is None


def test_paper_moment_is_a_result_when_recent_and_not_a_drop() -> None:
    records = [
        _paper(grade="C", at=NOW - timedelta(days=20)),
        _paper(grade="B", awarded=61, weak=[_weak("Vectors", 9, 12, "8")]),
    ]
    moment = paper_moment(records, NOW)
    assert moment is not None
    assert (moment.kind, moment.grade, moment.previousGrade, moment.focusQuestion) == (
        "result",
        "B",
        "C",
        "8",
    )
    assert moment.paperId == "1"


def test_paper_moment_is_tough_for_a_low_grade_or_a_drop() -> None:
    low = paper_moment([_paper(grade="D", awarded=42)], NOW)
    assert low is not None
    assert low.kind == "tough"
    dropped = paper_moment([_paper(grade="A", at=NOW - timedelta(days=9)), _paper(grade="B")], NOW)
    assert dropped is not None
    assert dropped.kind == "tough"


def test_paper_moment_expires_after_48_hours() -> None:
    assert paper_moment([_paper(at=NOW - timedelta(hours=49))], NOW) is None
    assert paper_moment([], NOW) is None


def test_stats_count_papers_and_practice_marks() -> None:
    records = [
        _paper(grade="B"),
        _paper(code="0606", grade="A"),
        _paper(origin="quiz", awarded=7, maximum=9),
        _paper(origin="quiz", awarded=5, maximum=10),
    ]
    stats = build_stats(records)
    assert stats.papersMarked == 2
    assert stats.marksWonBack == 12
    assert stats.bestGrade is not None
    assert (stats.bestGrade.grade, stats.bestGrade.subjectCode) == ("A", "0606")
    assert build_stats([]).bestGrade is None


def test_activity_merges_papers_practice_and_teacher_replies_newest_first() -> None:
    reply = TeacherReplyDTO(
        reviewId="r1",
        teacherName="Ms. Hanna",
        questionId="7",
        subjectCode="0580",
        subjectName="Mathematics",
        paperNumber=4,
        marksAdded=1,
        paperId="0",
        resolvedAt=NOW - timedelta(hours=1),
    )
    records = [
        _paper(at=NOW - timedelta(days=2)),
        _paper(origin="quiz", awarded=8, maximum=10, at=NOW - timedelta(hours=3)),
    ]
    rows = build_activity(records, [reply])
    assert [r.kind for r in rows] == ["teacher", "practice", "paper"]
    assert rows[0].title == "Ms. Hanna checked Q7"
    assert rows[0].sub == "Mathematics · +1 mark"
    assert rows[1].sub.endswith("8 of 10")


def test_question_label_adds_q_once() -> None:
    assert question_label("7") == "Q7"
    assert question_label("Q4b") == "Q4b"
