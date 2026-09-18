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
