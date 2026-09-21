"""Advisory integrity checks over a marked paper — plagiarism only.

F4 removed the AI-generated-answer detector (``AIContentDetector``, formerly
here) outright. It was a zero-shot Gemini classifier with no measured
false-positive rate; published AI-text detectors run ~61% false-positive
rates on authentic L2 student writing, and JCQ guidance (Ofqual, 14 Jan 2026
principles; Ofqual, 16 Jul 2026 approach) is that such a detector must never
be sole evidence of anything. This module now carries only the one integrity
signal with an actual, checkable basis: near-verbatim copying from the mark
scheme's own model answer, via stdlib ``difflib`` (no Gemini call, no
false-authorship claim). It is advisory only — it flags a question for a
teacher's judgement and never touches a mark — not a claim that a teacher
marks alongside Lemely on every paper, which nothing in this codebase
guarantees.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from lemely.core.loose_schemas import QuestionType
from lemely.core.plagiarism import PlagiarismChecker
from lemely.core.schemas import CorrectedQuestion, CorrectionResult

if TYPE_CHECKING:
    from lemely.core.loose_schemas import MarkScheme
    from lemely.io.gemini import GeminiClient
    from lemely.runtime.config import IntegritySettings


def apply_integrity_checks(
    correction: CorrectionResult,
    mark_scheme: MarkScheme,
    *,
    gemini_client: GeminiClient | None = None,
    settings: IntegritySettings,
) -> CorrectionResult:
    """Run the advisory plagiarism check over a marked paper.

    Advisory only: a flagged question gets ``plagiarism_flagged`` set,
    ``review_reason`` appended to (preserving any existing text), and
    ``needs_teacher_review`` forced True. ``awarded_marks``/``maximum_marks``
    are never touched. A flag is a signal for the teacher's judgement, not a
    verdict about the student.

    Runs when ``settings.plagiarism_enabled`` and the question has both a
    student answer and an expected (mark-scheme) answer.

    **Skipped for MCQ questions** (B3). Similarity is not a meaningful
    measure of a single multiple-choice letter: a *correct* MCQ answer is
    character-identical to the expected one, so ``SequenceMatcher`` scores it
    1.0 and every right answer became a plagiarism flag while every wrong one
    stayed clean — the signal inverted. The guard is on the mark-scheme
    question's ``type``, deliberately not on answer length: a one-character
    *free-text* answer is a different case and is still checked. A question
    absent from the scheme cannot be classified, so it is treated as
    free-text and still checked.

    Args:
        correction: the marking output to check, question by question.
        mark_scheme: the paper's mark scheme, consulted to exempt MCQ
            questions and to look up each question's type.
        gemini_client: unused — kept as a keyword-compatible no-op for
            callers written before F4 removed the only Gemini-backed check
            this function ran. Accepting and ignoring it here is cheaper than
            hunting down every call site the same day the detector is
            deleted; a later cleanup pass may drop the parameter outright.
        settings: ``IntegritySettings`` — ``plagiarism_enabled`` and
            ``plagiarism_threshold`` are the only fields this function reads.

    Returns a freshly-constructed :class:`CorrectionResult` (not a
    ``model_copy``) so ``CorrectionResult.calculate_totals`` reruns and
    ``needs_teacher_review`` reflects any newly-flagged questions.
    """
    plagiarism_checker = (
        PlagiarismChecker(threshold=settings.plagiarism_threshold)
        if settings.plagiarism_enabled
        else None
    )

    updated_questions: list[CorrectedQuestion] = []
    for cq in correction.questions:
        reasons = cq.review_reason.split(" | ") if cq.review_reason else []
        updates: dict[str, bool | str] = {}

        question = mark_scheme.get_question_by_id(cq.question_id)
        # An unknown question cannot be classified — treat it as free-text and
        # keep checking it, rather than silently exempting it.
        is_mcq = question is not None and question.type == QuestionType.MCQ

        if (
            plagiarism_checker is not None
            and not is_mcq
            and cq.student_answer
            and cq.expected_answer
        ):
            finding = plagiarism_checker.check(
                cq.question_id, cq.student_answer, cq.expected_answer
            )
            if finding.flagged:
                updates["plagiarism_flagged"] = True
                reasons.append(f"plagiarism (score {finding.score:.2f})")

        if updates:
            updates["needs_teacher_review"] = True
            updates["review_reason"] = " | ".join(reasons)
            cq = cq.model_copy(update=updates)
        updated_questions.append(cq)

    return CorrectionResult(metadata=correction.metadata, questions=updated_questions)
