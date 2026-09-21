"""``QuestionResult.effective_marks`` precedence: teacher > student > AI.

Pure ORM-object tests — no database. The property is the single accessor
every read surface uses (P3.4), so the precedence is pinned here in both
directions, including a student self-marking *downward* (spec D6).
"""

from __future__ import annotations

from datetime import UTC, datetime

from lemely.db.models.attempts import QuestionResult
from lemely.db.models.enums import ConfidenceBand, MarkerSource


def _qr(**overrides: object) -> QuestionResult:
    base: dict[str, object] = {
        "question_id": "1a",
        "awarded_marks": 1,
        "maximum_marks": 3,
        "confidence_band": ConfidenceBand.high,
        "confidence_score": 0.95,
        "needs_teacher_review": False,
        "marker_source": MarkerSource.ai,
    }
    base.update(overrides)
    return QuestionResult(**base)  # type: ignore[arg-type]


def test_ai_mark_when_nothing_else_is_recorded() -> None:
    assert _qr().effective_marks == 1


def test_student_selfmark_beats_ai() -> None:
    assert _qr(student_selfmark_marks=3).effective_marks == 3


def test_student_selfmark_downward_beats_ai() -> None:
    assert _qr(awarded_marks=2, student_selfmark_marks=0).effective_marks == 0


def test_teacher_beats_student_and_ai() -> None:
    assert _qr(student_selfmark_marks=3, teacher_awarded_marks=2).effective_marks == 2


def test_teacher_zero_still_beats_student() -> None:
    assert _qr(student_selfmark_marks=3, teacher_awarded_marks=0).effective_marks == 0


def test_student_zero_still_beats_ai() -> None:
    assert _qr(awarded_marks=2, student_selfmark_marks=0).effective_marks == 0


def test_awarded_marks_is_never_touched_by_the_accessor() -> None:
    qr = _qr(student_selfmark_marks=3, teacher_awarded_marks=2)
    assert qr.effective_marks == 2
    assert qr.awarded_marks == 1


def test_is_self_marked_reads_the_timestamp_not_the_marks() -> None:
    assert _qr().is_self_marked is False
    # A pass that changed nothing still counts as a pass (one pass per question).
    assert _qr(student_selfmarked_at=datetime.now(UTC)).is_self_marked is True
    assert _qr(student_selfmark_marks=3).is_self_marked is False
