"""Student self-review: the authority rule and the judge seam, both pure.

The rule (spec 2026-09-17 self-review, "Authority"), per mark point where the
student and the marker disagree:

* the question is **low-confidence** (the marker said it was unsure) — the
  student's verdict is applied outright, evidence optional (D2), in either
  direction (D6);
* otherwise the student must have **written evidence**, and a lenient judge
  decides (D3); a bare disagreement with no evidence is recorded as a
  misconception signal and changes nothing.

"Low-confidence" is decided by the caller with
:func:`lemely.db.attempt_repo.is_marking_low_confidence` — the same function
that opens the ``low_confidence`` review-queue row — so an integrity-only flag
(plagiarism / AI detection) never reaches here as ``low_confidence=True``.
Integrity flags grant no authority.

This module has no I/O and imports nothing outside the standard library, so
the rule is table-tested without a database
(``tests/test_core_self_review.py``). The judge itself lives in
:mod:`lemely.io.evidence_judge`; this module only defines what a judge is
asked and what it answers, so the service can be tested with a scripted one.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class PointDecision(StrEnum):
    """What to do with one mark point after the student's verdict arrives."""

    AGREE = "agree"
    """Student and marker concur. Nothing to apply; the agreement is confirmed."""
    GRANT = "grant"
    """Low-confidence question: the student's verdict is applied as-is."""
    JUDGE = "judge"
    """High-confidence question with evidence: ask the lenient judge."""
    NO_CHANGE = "no_change"
    """High-confidence question, no evidence: recorded, not applied."""


def decide_point(
    *,
    ai_awarded: bool,
    student_earned: bool,
    low_confidence: bool,
    has_evidence: bool,
) -> PointDecision:
    """The authority rule for one point. Pure; see the module docstring."""
    if ai_awarded == student_earned:
        return PointDecision.AGREE
    if low_confidence:
        return PointDecision.GRANT
    if has_evidence:
        return PointDecision.JUDGE
    return PointDecision.NO_CHANGE


@dataclass(frozen=True, slots=True)
class JudgeRequest:
    """Everything the lenient judge is given for one challenged point.

    ``student_answer`` is the transcribed answer the marker saw;
    ``marker_rationale`` is the marker's own reason for the verdict (the
    per-point ``rationale`` when a marker emitted one, else the question's
    ``rationale``, else its student-facing ``feedback``). ``student_claims_earned``
    says which direction the challenge runs — a student may also argue they
    did *not* earn a point the marker awarded (D6).
    """

    subject_code: str
    question_id: str
    point_text: str
    mark_type: str | None
    tariff: int
    student_answer: str | None
    marker_rationale: str | None
    student_claims_earned: bool
    student_evidence: str


@dataclass(frozen=True, slots=True)
class JudgeVerdict:
    """Accept or reject, plus the short reason the student is shown."""

    accepted: bool
    reason: str


class EvidenceJudge(Protocol):
    """The seam :class:`lemely.db.self_review_repo.SelfReviewService` calls.

    Any exception raised by :meth:`judge` is a judge *failure*, which the
    service turns into a ``student_evidence_unjudged`` review-queue row —
    never a silent accept or reject.
    """

    def judge(self, request: JudgeRequest) -> JudgeVerdict:
        """Decide one challenged point."""
        ...


__all__ = [
    "EvidenceJudge",
    "JudgeRequest",
    "JudgeVerdict",
    "PointDecision",
    "decide_point",
]
