"""The self-review authority rule (spec 2026-09-17 self-review, "Authority").

Pure table test over every cell: flag state x direction x evidence. The rule
is the feature, so every cell is named — a cell nobody checked is a cell
nobody can defend.
"""

from __future__ import annotations

import pytest

from lemely.core.self_review import PointDecision, decide_point


@pytest.mark.parametrize(
    ("ai_awarded", "student_earned", "low_confidence", "has_evidence", "expected"),
    [
        # Agreement does nothing, whatever else is true.
        (True, True, True, True, PointDecision.AGREE),
        (True, True, False, False, PointDecision.AGREE),
        (False, False, True, False, PointDecision.AGREE),
        (False, False, False, True, PointDecision.AGREE),
        # Low confidence: the student wins outright, evidence optional (D2).
        (False, True, True, False, PointDecision.GRANT),
        (False, True, True, True, PointDecision.GRANT),
        # ...and downward on the same terms (D6).
        (True, False, True, False, PointDecision.GRANT),
        (True, False, True, True, PointDecision.GRANT),
        # High confidence: evidence unlocks the judge (D3); no evidence, no change.
        (False, True, False, True, PointDecision.JUDGE),
        (True, False, False, True, PointDecision.JUDGE),
        (False, True, False, False, PointDecision.NO_CHANGE),
        (True, False, False, False, PointDecision.NO_CHANGE),
    ],
)
def test_decide_point(
    ai_awarded: bool,
    student_earned: bool,
    low_confidence: bool,
    has_evidence: bool,
    expected: PointDecision,
) -> None:
    assert (
        decide_point(
            ai_awarded=ai_awarded,
            student_earned=student_earned,
            low_confidence=low_confidence,
            has_evidence=has_evidence,
        )
        is expected
    )


def test_every_combination_is_decided() -> None:
    """The four booleans give 16 inputs; none may raise or return None."""
    for ai in (True, False):
        for student in (True, False):
            for low in (True, False):
                for evidence in (True, False):
                    decision = decide_point(
                        ai_awarded=ai,
                        student_earned=student,
                        low_confidence=low,
                        has_evidence=evidence,
                    )
                    assert isinstance(decision, PointDecision)
