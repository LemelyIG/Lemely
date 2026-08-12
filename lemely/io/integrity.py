"""AI-based content detection — Gemini classifier for AI-generated answers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from lemely.core.integrity_schemas import IntegrityFinding
from lemely.core.loose_schemas import QuestionType
from lemely.core.plagiarism import PlagiarismChecker
from lemely.core.schemas import CorrectedQuestion, CorrectionResult
from lemely.io.prompts.integrity import (
    AI_DETECTION_SYSTEM_PROMPT,
    VERSION,
    build_ai_detection_user_prompt,
)

if TYPE_CHECKING:
    from lemely.core.loose_schemas import MarkScheme
    from lemely.io.gemini import GeminiClient
    from lemely.runtime.config import IntegritySettings


class AIContentDetector:
    """Classify whether a student answer is AI-generated using Gemini.

    Uses task_tag='integrity'. Threshold is checked by the caller (IntegritySettings).
    """

    def __init__(self, gemini_client: GeminiClient) -> None:
        self._client = gemini_client

    def detect(
        self,
        question_id: str,
        question_text: str,
        student_answer: str,
        mark_scheme_points: list[str],
    ) -> IntegrityFinding:
        """Classify one answer for AI-generation.

        Args:
            question_id: Identifier used in the returned finding.
            question_text: The exam question text.
            student_answer: The student's answer to assess.
            mark_scheme_points: Mark scheme bullet points for context.

        Returns:
            IntegrityFinding with kind='ai_generated'.
        """
        extra_cache_key = f"{question_id}:{hash(student_answer)}"
        return self._client.generate_structured(
            system_prompt=AI_DETECTION_SYSTEM_PROMPT,
            user_prompt=build_ai_detection_user_prompt(
                question_id, question_text, student_answer, mark_scheme_points
            ),
            response_schema=IntegrityFinding,
            prompt_version=VERSION,
            task_tag="integrity",
            extra_cache_key=extra_cache_key,
        )


def apply_integrity_checks(
    correction: CorrectionResult,
    mark_scheme: MarkScheme,
    *,
    gemini_client: GeminiClient | None,
    settings: IntegritySettings,
) -> CorrectionResult:
    """Run advisory plagiarism / AI-detection checks over a marked paper.

    Both checks are advisory teacher-review signals only: a flagged question
    gets ``plagiarism_flagged``/``ai_detection_flagged`` set, ``review_reason``
    appended to (preserving any existing text), and ``needs_teacher_review``
    forced True. ``awarded_marks``/``maximum_marks`` are never touched.

    Plagiarism runs when ``settings.plagiarism_enabled`` and the question has
    both a student answer and an expected (mark-scheme) answer. AI-detection
    runs when ``settings.ai_detection_enabled`` and a ``gemini_client`` is
    available and the question has a student answer — it costs one Gemini
    call per question, so it is opt-in and skipped entirely (no client call)
    when disabled.

    **Both checks are skipped for MCQ questions** (B3). Neither similarity nor
    AI-authorship is a meaningful measure of a single multiple-choice letter:
    a *correct* MCQ answer is character-identical to the expected one, so
    ``SequenceMatcher`` scores it 1.0 and every right answer became a
    plagiarism flag while every wrong one stayed clean — the signal inverted.
    The guard is on the mark-scheme question's ``type``, deliberately not on
    answer length: a one-character *free-text* answer is a different case and
    is still checked. A question absent from the scheme cannot be classified,
    so it is treated as free-text and still checked.

    Returns a freshly-constructed :class:`CorrectionResult` (not a
    ``model_copy``) so ``CorrectionResult.calculate_totals`` reruns and
    ``needs_teacher_review`` reflects any newly-flagged questions.
    """
    plagiarism_checker = (
        PlagiarismChecker(threshold=settings.plagiarism_threshold)
        if settings.plagiarism_enabled
        else None
    )
    ai_detector = (
        AIContentDetector(gemini_client)
        if settings.ai_detection_enabled and gemini_client is not None
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

        if ai_detector is not None and not is_mcq and cq.student_answer:
            # Best-effort proxy: the mark-scheme model has no verbatim question-stem
            # field, so fall back through command word / topic hint / id.
            question_text = (
                (question.question_command or question.topic_hint or question.id)
                if question is not None
                else cq.question_id
            )
            mark_scheme_points = (
                [p.point for p in question.answer_points] if question is not None else []
            )
            finding = ai_detector.detect(
                cq.question_id, question_text, cq.student_answer, mark_scheme_points
            )
            if finding.flagged:
                updates["ai_detection_flagged"] = True
                reasons.append(f"ai_detection (score {finding.score:.2f})")

        if updates:
            updates["needs_teacher_review"] = True
            updates["review_reason"] = " | ".join(reasons)
            cq = cq.model_copy(update=updates)
        updated_questions.append(cq)

    return CorrectionResult(metadata=correction.metadata, questions=updated_questions)
