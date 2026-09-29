"""The two additive marker-reasoning fields on :class:`CorrectedQuestion`.

Both default to ``None`` so no marker prompt change is required to ship the
per-question detail work (spec 2026-09-17 D1). When the marker starts emitting
them, they stop being null and nothing else has to change.
"""

from __future__ import annotations

from lemely.core.schemas import ConfidenceBand, CorrectedQuestion


def _question(**overrides: object) -> CorrectedQuestion:
    base: dict[str, object] = {
        "question_id": "1a",
        "awarded_marks": 2,
        "maximum_marks": 3,
        "confidence": ConfidenceBand.HIGH,
        "confidence_score": 0.95,
        "needs_teacher_review": False,
    }
    base.update(overrides)
    return CorrectedQuestion(**base)  # type: ignore[arg-type]


def test_rationale_and_point_notes_default_to_none() -> None:
    question = _question()
    assert question.rationale is None
    assert question.point_notes is None


def test_rationale_and_point_notes_round_trip_when_supplied() -> None:
    question = _question(
        rationale="Method correct, final value not given to 3sf.",
        point_notes={"p1": "method shown", "p2": "rounding wrong"},
    )
    assert question.rationale == "Method correct, final value not given to 3sf."
    assert question.point_notes == {"p1": "method shown", "p2": "rounding wrong"}


#: A ``teacher_papers.report_json`` exactly as develop wrote it before ``1094cfde``
#: removed ``CorrectedQuestion.ai_detection_flagged`` (triage probe
#: ``probe1_make.py``, 2026-09-29): ``model_dump(mode="json")`` emits defaults,
#: so EVERY stored report carries the key.
_LEGACY_REPORT = {
    "correction": {
        "metadata": {
            "subject_code": "9999",
            "paper_number": 1,
            "paper_variant": 1,
            "session_month": "May/June",
            "session_year": 2020,
            "source_document": None,
        },
        "questions": [
            {
                "question_id": "1a",
                "awarded_marks": 1,
                "maximum_marks": 2,
                "confidence": "high",
                "confidence_score": 0.9,
                "needs_teacher_review": False,
                "student_answer": None,
                "expected_answer": None,
                "topic": None,
                "review_reason": None,
                "marker_source": "ai",
                "feedback": None,
                "matched_point_ids": [],
                "plagiarism_flagged": False,
                "ai_detection_flagged": False,
                "extraction_confidence": None,
                "rationale": None,
                "point_notes": None,
            }
        ],
        "awarded_marks": 1,
        "maximum_marks": 2,
        "needs_teacher_review": False,
    },
    "weaknesses": {"weak_areas": [], "needs_teacher_review": False},
    "grade_prediction": {
        "awarded_marks": 1,
        "maximum_marks": 2,
        "percentage": 50.0,
        "grade": "U",
        "confidence": "high",
        "needs_teacher_review": False,
        "boundary_source": "global_default",
    },
}


def test_a_report_stored_before_the_ai_detection_removal_still_loads() -> None:
    """Triage F1: ``StrictModel`` is ``extra="forbid"`` and ``1094cfde`` deleted
    the field, so ``AccuracyReport.model_validate`` on any pre-PR
    ``report_json`` raised ``extra_forbidden`` -- a 500 on the teacher paper
    list (``teacher_paper_repo._snapshot``) and a silently dropped report on
    console review items (``review_repo._console_report``)."""
    import copy

    from lemely.core.schemas import AccuracyReport

    report = AccuracyReport.model_validate(copy.deepcopy(_LEGACY_REPORT))

    question = report.correction.questions[0]
    assert question.awarded_marks == 1
    assert "ai_detection_flagged" not in question.model_dump()


def test_the_legacy_key_is_the_only_unknown_key_tolerated() -> None:
    """Both keys present: the validator must drop ``ai_detection_flagged`` and
    ``ai_detection_flagged`` alone -- a second, unrelated unknown key must
    still be rejected by ``extra="forbid"``. Passing only ``ai_detection_score``
    (with no legacy key) would never exercise the validator's drop branch at
    all, so this must send both."""
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as exc_info:
        _question(ai_detection_flagged=False, ai_detection_score=0.9)

    errors = exc_info.value.errors()
    assert [e["loc"] for e in errors] == [("ai_detection_score",)]
    assert errors[0]["type"] == "extra_forbidden"


def test_the_before_validator_does_not_mutate_the_caller_dict() -> None:
    """A loader that re-reads the same dict (``review_repo`` parses a paper's
    report once and threads it through) must not see it change under it."""
    stored = {
        "question_id": "1a",
        "awarded_marks": 2,
        "maximum_marks": 3,
        "confidence": ConfidenceBand.HIGH,
        "confidence_score": 0.95,
        "needs_teacher_review": False,
        "ai_detection_flagged": True,
    }
    CorrectedQuestion.model_validate(stored)
    assert stored["ai_detection_flagged"] is True
