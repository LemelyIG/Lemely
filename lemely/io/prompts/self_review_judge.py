"""Versioned prompt for the lenient self-review evidence judge.

"Lenient" is operational (spec 2026-09-17 self-review, "The lenient judge"):
**accept unless the student's evidence is contradicted by their own recorded
answer.** The burden sits on rejection. Plausible-but-unproven clears the
bar; only a direct contradiction with what they actually wrote does not.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lemely.core.self_review import JudgeRequest

VERSION = "1"

JUDGE_SYSTEM_PROMPT = (
    "You are a lenient examiner reviewing a student's challenge to one mark point "
    "on their marked exam answer. You are given the mark point, the marker's reason "
    "for its verdict, the student's transcribed answer exactly as it was marked, and "
    "the student's written case. "
    "Rule: ACCEPT UNLESS the student's case is directly contradicted by their own "
    "recorded answer. A claim that is plausible but not proven by the transcription "
    "is accepted. Reject only when the transcribed answer itself shows the claim to be "
    "false. Never reject for tone, brevity, or because the marker disagreed. "
    "Return ONLY valid JSON matching the JudgeOutcome schema: `accepted` (boolean) and "
    "`reason` (one or two plain sentences addressed to the student, no exclamation "
    "marks)."
)


def build_judge_user_prompt(request: JudgeRequest) -> str:
    """Lay out one challenged point for the judge. Nothing absent is invented."""
    direction = (
        "The student claims they DID earn this point although the marker withheld it."
        if request.student_claims_earned
        else "The student claims they did NOT earn this point although the marker awarded it."
    )
    mark_type = f" (mark type {request.mark_type})" if request.mark_type else ""
    answer = request.student_answer or "(no answer was transcribed)"
    rationale = request.marker_rationale or "(the marker gave no reason)"
    return (
        f"Subject: {request.subject_code}\n"
        f"Question: {request.question_id}\n"
        f"Mark point{mark_type}, worth {request.tariff}: {request.point_text}\n\n"
        f"{direction}\n\n"
        f"Student's transcribed answer:\n{answer}\n\n"
        f"Marker's reason:\n{rationale}\n\n"
        f"Student's case:\n{request.student_evidence}\n\n"
        "Decide: is the student's case contradicted by their own transcribed answer? "
        "If not, accept."
    )


__all__ = ["JUDGE_SYSTEM_PROMPT", "VERSION", "build_judge_user_prompt"]
