"""A binding doubt keeps the teacher's queue row but grants no self-mark authority.

The queue rule (``low_confidence_review_needed``) is deliberately untouched: a
question whose answer may belong to another question, or was never read, must
reach a teacher. The authority rule (``grants_self_mark_authority``) differs on
purpose: "the marker was unsure of its own mark" lets the student's word stand,
but "the transcription itself is in doubt" does not.
"""

from __future__ import annotations

import pytest

from lemely.core.binding_review import BINDING_REVIEW_PREFIX, has_binding_doubt
from lemely.core.loose_schemas import Question, QuestionType
from lemely.core.schemas import AIMarkResponse, CorrectedQuestion
from lemely.core.self_review import PointDecision, decide_point
from lemely.db.attempt_repo import (
    _to_question_result,
    grants_self_mark_authority,
    is_marking_low_confidence,
)
from lemely.db.models.enums import ReviewReason
from lemely.db.review_queue_rules import review_reasons_for
from lemely.io.correction_ai import (
    OFF_TOPIC_REVIEW_REASON,
    UNBOUND_QUESTION_REVIEW_REASON,
    UNVERIFIED_BINDING_REVIEW_REASON,
    _build_ai_corrected,
    _build_blank_corrected,
    _build_dropped_corrected,
    _build_missing_corrected,
    _sent_to_review,
)

_BINDING_REASONS = [
    UNBOUND_QUESTION_REVIEW_REASON,
    OFF_TOPIC_REVIEW_REASON,
    UNVERIFIED_BINDING_REVIEW_REASON,
]


def _open_question() -> Question:
    return Question.model_construct(
        id="3b",
        marks=4,
        type=QuestionType.CALCULATION,
        parts=[],
        assessment_objectives=[],
        answer_points=[],
        rejected_answers=[],
        ignored_answers=[],
    )


def _ai(confidence: float) -> CorrectedQuestion:
    return _build_ai_corrected(
        _open_question(),
        "some working",
        AIMarkResponse(
            awarded_marks=1, confidence=confidence, matched_point_ids=[], feedback="Partly."
        ),
    )


def _queues(cq: CorrectedQuestion) -> bool:
    return ReviewReason.low_confidence in set(review_reasons_for(cq))


def _authority(cq: CorrectedQuestion) -> bool:
    return grants_self_mark_authority(_to_question_result(cq))


def test_has_binding_doubt_table() -> None:
    assert has_binding_doubt(None) is False
    assert has_binding_doubt("") is False
    assert has_binding_doubt("value_mismatch") is False
    for reason in _BINDING_REASONS:
        assert has_binding_doubt(reason) is True
    assert has_binding_doubt(f"value_mismatch | {OFF_TOPIC_REVIEW_REASON}") is True
    assert (
        has_binding_doubt(f"{UNVERIFIED_BINDING_REVIEW_REASON} | plagiarism (score 0.94)") is True
    )
    # The words appearing mid-sentence, or in a segment that does not start with
    # the prefix, are not a binding doubt.
    assert has_binding_doubt("the marker said binding unverified: in passing") is False
    assert has_binding_doubt("note | the binding unverified: text is quoted") is False


@pytest.mark.parametrize("reason", _BINDING_REASONS)
def test_every_binding_reason_the_writer_emits_starts_with_the_prefix(reason: str) -> None:
    """The writer (correction_ai) and the rule (binding_review) cannot drift apart."""
    assert reason.startswith(BINDING_REVIEW_PREFIX)


def test_unbound_question_keeps_its_queue_row_and_grants_no_authority() -> None:
    cq = _build_dropped_corrected(_open_question(), UNBOUND_QUESTION_REVIEW_REASON)

    assert _queues(cq) is True
    assert is_marking_low_confidence(_to_question_result(cq)) is True  # queue meaning unchanged
    assert _authority(cq) is False


def test_unverified_answer_keeps_its_queue_row_and_grants_no_authority() -> None:
    for reason in (UNVERIFIED_BINDING_REVIEW_REASON, OFF_TOPIC_REVIEW_REASON):
        cq = _sent_to_review([_ai(0.95)], {"3b"}, reason)[0]  # confident mark, then flagged

        assert _queues(cq) is True
        assert _authority(cq) is False


def test_marker_low_confidence_still_grants_authority() -> None:
    assert _authority(_ai(0.2)) is True
    assert _authority(_build_missing_corrected(_open_question(), None)) is True
    assert _authority(_build_dropped_corrected(_open_question())) is True


def test_binding_doubt_with_low_marker_confidence_grants_no_authority() -> None:
    cq = _sent_to_review([_ai(0.2)], {"3b"}, UNVERIFIED_BINDING_REVIEW_REASON)[0]

    assert is_marking_low_confidence(_to_question_result(cq)) is True
    assert _authority(cq) is False


def test_a_blank_is_still_neither_queued_nor_granted_authority() -> None:
    cq = _build_blank_corrected(_open_question())

    assert _queues(cq) is False
    assert _authority(cq) is False


def test_student_self_mark_on_a_binding_doubt_question_goes_to_evidence_and_judge_or_no_change() -> (  # noqa: E501
    None
):
    for cq in (
        _build_dropped_corrected(_open_question(), UNBOUND_QUESTION_REVIEW_REASON),
        _sent_to_review([_ai(0.95)], {"3b"}, UNVERIFIED_BINDING_REVIEW_REASON)[0],
    ):
        granted = _authority(cq)
        # The student claims a point the marker did not award.
        no_evidence = decide_point(
            ai_awarded=False, student_earned=True, low_confidence=granted, has_evidence=False
        )
        with_evidence = decide_point(
            ai_awarded=False, student_earned=True, low_confidence=granted, has_evidence=True
        )

        assert no_evidence is PointDecision.NO_CHANGE
        assert with_evidence is PointDecision.JUDGE
