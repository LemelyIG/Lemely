"""Per-mark-point derivation (spec 2026-09-17, "Write path").

Pure-function tests: no database, no session. The behaviour that matters most
is the inversion — a row is written per point in the MARK SCHEME, not per id in
``matched_point_ids`` — because missed points are exactly what a breakdown is
for.
"""

from __future__ import annotations

from lemely.core.loose_schemas import (
    AnswerPoint,
    MarkScheme,
    MarkSchemeMetadata,
    MathMarkType,
    PaperType,
    SchemeFormat,
)
from lemely.core.loose_schemas import Question as SchemeQuestion
from lemely.core.loose_schemas import QuestionType as SchemeQuestionType
from lemely.core.loose_schemas import SessionMonth as LooseSessionMonth
from lemely.core.schemas import ConfidenceBand, CorrectedQuestion
from lemely.db.question_points import derive_point_rows


def _scheme() -> MarkScheme:
    """A one-question scheme with three points: p1 (M, 1), p2 (A, 1), p3 (B, 1).

    Field names here are verified against the real schema, not guessed:
    ``Question`` takes ``type=`` (not ``question_type=``), every enum member is
    UPPERCASE, and ``MarkSchemeMetadata`` requires ``subject`` and
    ``maximum_mark`` as well as the obvious fields.
    """
    question = SchemeQuestion(
        id="1a",
        marks=3,
        type=SchemeQuestionType.CALCULATION,
        answer_points=[
            AnswerPoint(id="p1", point="Correct method", marks=1, math_mark_type=MathMarkType.M),
            AnswerPoint(id="p2", point="Answer to 3sf", marks=1, math_mark_type=MathMarkType.A),
            AnswerPoint(id="p3", point="Units stated", marks=1, math_mark_type=MathMarkType.B),
        ],
    )
    return MarkScheme(
        metadata=MarkSchemeMetadata(
            subject="Mathematics",
            subject_code="0580",
            paper_number=2,
            paper_variant=1,
            session_month=LooseSessionMonth.MAY_JUNE,
            session_year=2024,
            paper_type=PaperType.THEORY_EXTENDED,
            maximum_mark=3,
            scheme_format=SchemeFormat.POINT_BASED,
        ),
        questions=[question],
    )


def _corrected(**overrides: object) -> CorrectedQuestion:
    base: dict[str, object] = {
        "question_id": "1a",
        "awarded_marks": 1,
        "maximum_marks": 3,
        "confidence": ConfidenceBand.HIGH,
        "confidence_score": 0.95,
        "needs_teacher_review": False,
        "matched_point_ids": ["p1"],
    }
    base.update(overrides)
    return CorrectedQuestion(**base)  # type: ignore[arg-type]


def test_writes_a_row_per_scheme_point_not_per_matched_id() -> None:
    """The inversion. Two missed points must still become rows."""
    rows = derive_point_rows(_corrected(), _scheme())

    assert [row["mark_point_id"] for row in rows] == ["p1", "p2", "p3"]
    assert [row["awarded"] for row in rows] == [True, False, False]


def test_carries_tariff_mark_type_and_text_from_the_scheme() -> None:
    rows = derive_point_rows(_corrected(), _scheme())

    assert rows[1] == {
        "mark_point_id": "p2",
        "ordinal": 1,
        "mark_type": "A",
        "tariff": 1,
        "point_text": "Answer to 3sf",
        "awarded": False,
        "rationale": None,
    }


def test_rationale_comes_from_point_notes_when_the_marker_supplied_it() -> None:
    rows = derive_point_rows(
        _corrected(point_notes={"p2": "wrote 12.47, needed 12.5"}),
        _scheme(),
    )

    assert rows[1]["rationale"] == "wrote 12.47, needed 12.5"
    assert rows[0]["rationale"] is None


def test_point_notes_for_unknown_points_are_ignored() -> None:
    """A note keyed to a point the scheme lacks must not mint a row."""
    rows = derive_point_rows(
        _corrected(point_notes={"p99": "note for a point that does not exist"}),
        _scheme(),
    )

    assert [row["mark_point_id"] for row in rows] == ["p1", "p2", "p3"]


def test_dangling_matched_ids_do_not_become_rows() -> None:
    """An id the marker claimed but the scheme lacks is dropped, not invented."""
    rows = derive_point_rows(_corrected(matched_point_ids=["p1", "p_ghost"]), _scheme())

    assert [row["mark_point_id"] for row in rows] == ["p1", "p2", "p3"]
    assert [row["awarded"] for row in rows] == [True, False, False]


def test_no_scheme_yields_no_rows() -> None:
    """The quiz case: persist_quiz_correction has no scheme to pass."""
    assert derive_point_rows(_corrected(), None) == []


def test_question_absent_from_the_scheme_yields_no_rows() -> None:
    assert derive_point_rows(_corrected(question_id="99z"), _scheme()) == []


def test_question_with_no_answer_points_yields_no_rows() -> None:
    """Levels-based questions carry descriptors, not points."""
    scheme = _scheme()
    scheme.questions[0].answer_points = []

    assert derive_point_rows(_corrected(), scheme) == []


def test_duplicate_point_ids_collapse_to_one_row_first_occurrence_wins() -> None:
    """A malformed scheme with two points sharing an id must not emit two rows:
    that would violate the DB's uniqueness constraint on
    ``(question_result_id, mark_point_id)`` and lose the whole attempt at
    commit (spec 2026-09-17, "Error handling"). The first occurrence wins and
    ``ordinal`` stays contiguous over the emitted rows, not the raw index.
    """
    scheme = _scheme()
    scheme.questions[0].answer_points = [
        AnswerPoint(id="p1", point="Correct method", marks=1, math_mark_type=MathMarkType.M),
        AnswerPoint(
            id="p1", point="Duplicate, should be dropped", marks=5, math_mark_type=MathMarkType.B
        ),
        AnswerPoint(id="p2", point="Answer to 3sf", marks=1, math_mark_type=MathMarkType.A),
    ]

    rows = derive_point_rows(_corrected(matched_point_ids=["p1"]), scheme)

    assert [row["mark_point_id"] for row in rows] == ["p1", "p2"]
    assert [row["ordinal"] for row in rows] == [0, 1]
    assert rows[0]["point_text"] == "Correct method"
    assert rows[0]["tariff"] == 1


def test_mark_type_is_none_for_a_non_maths_point() -> None:
    scheme = _scheme()
    scheme.questions[0].answer_points[0].math_mark_type = None

    rows = derive_point_rows(_corrected(), scheme)

    assert rows[0]["mark_type"] is None
