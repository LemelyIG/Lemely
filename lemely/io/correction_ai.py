"""AI-driven marking for non-MCQ questions + hybrid orchestrator for full papers."""

from __future__ import annotations

from collections.abc import Mapping

import structlog

from lemely.core.correction import _exam_metadata, _load_mark_scheme
from lemely.core.loose_schemas import MarkScheme, Question, QuestionType
from lemely.core.schemas import (
    AIMarkResponse,
    ConfidenceBand,
    CorrectedQuestion,
    CorrectionResult,
    ExtractedAnswers,
    confidence_band_for_score,
)
from lemely.io.gemini import GeminiClient
from lemely.io.prompts.correction_ai import (
    MARKER_SYSTEM_PROMPT,
    VERSION,
    build_marker_user_prompt,
)
from lemely.runtime.errors import ConfigError


def _is_leaf_marked(q: Question) -> bool:
    """Mark only leaf questions with marks > 0. Skip container/zero-mark items."""
    return q.marks > 0 and not q.parts


def _flatten_answers(extracted: ExtractedAnswers | Mapping[str, str]) -> dict[str, str]:
    if isinstance(extracted, ExtractedAnswers):
        return {a.question_id: a.answer for a in extracted.answers}
    return {str(k): str(v) for k, v in extracted.items()}


class AICorrector:
    """Marks individual non-MCQ questions via the shared GeminiClient."""

    def __init__(self, gemini_client: GeminiClient) -> None:
        self._client = gemini_client

    def mark_question(self, question: Question, student_answer: str) -> AIMarkResponse:
        return self._client.generate_structured(
            system_prompt=MARKER_SYSTEM_PROMPT,
            user_prompt=build_marker_user_prompt(question, student_answer),
            response_schema=AIMarkResponse,
            prompt_version=VERSION,
            extra_cache_key=f"q={question.id}",
        )


def _build_mcq_corrected(question: Question, answer: str | None) -> CorrectedQuestion:
    """Deterministic MCQ correction for one question."""
    expected = question.mcq_answer.value if question.mcq_answer else None
    if answer is None or answer == "":
        return CorrectedQuestion(
            question_id=question.id, awarded_marks=0, maximum_marks=question.marks,
            confidence=ConfidenceBand.LOW, confidence_score=0.0, needs_teacher_review=True,
            student_answer=None, expected_answer=expected,
            topic=question.topic_hint, review_reason="missing answer",
            marker_source="deterministic",
        )
    if answer.upper() not in {"A", "B", "C", "D"}:
        return CorrectedQuestion(
            question_id=question.id, awarded_marks=0, maximum_marks=question.marks,
            confidence=ConfidenceBand.LOW, confidence_score=0.0, needs_teacher_review=True,
            student_answer=answer, expected_answer=expected,
            topic=question.topic_hint, review_reason="invalid MCQ answer",
            marker_source="deterministic",
        )
    is_correct = answer.upper() == expected
    return CorrectedQuestion(
        question_id=question.id,
        awarded_marks=question.marks if is_correct else 0,
        maximum_marks=question.marks,
        confidence=ConfidenceBand.HIGH, confidence_score=1.0, needs_teacher_review=False,
        student_answer=answer.upper(), expected_answer=expected,
        topic=question.topic_hint,
        marker_source="deterministic",
    )


def _build_ai_corrected(
    question: Question, student_answer: str, mark: AIMarkResponse,
) -> CorrectedQuestion:
    """Convert AIMarkResponse + question metadata into a CorrectedQuestion."""
    awarded = max(0, min(mark.awarded_marks, question.marks))
    return CorrectedQuestion(
        question_id=question.id,
        awarded_marks=awarded,
        maximum_marks=question.marks,
        confidence=confidence_band_for_score(mark.confidence),
        confidence_score=mark.confidence,
        needs_teacher_review=mark.confidence < 0.7,
        student_answer=student_answer or None,
        expected_answer=None,
        topic=question.topic_hint,
        marker_source="ai",
        feedback=mark.feedback,
        matched_point_ids=list(mark.matched_point_ids),
    )


def _build_missing_corrected(question: Question, student_answer: str | None) -> CorrectedQuestion:
    return CorrectedQuestion(
        question_id=question.id,
        awarded_marks=0,
        maximum_marks=question.marks,
        confidence=ConfidenceBand.LOW,
        confidence_score=0.0,
        needs_teacher_review=True,
        student_answer=student_answer or None,
        expected_answer=None,
        topic=question.topic_hint,
        review_reason="non-MCQ question not marked (--mcq-only or no AI client)",
        marker_source="missing",
    )


def correct_paper(
    mark_scheme: MarkScheme | str | Mapping[str, object],
    extracted_answers: ExtractedAnswers | Mapping[str, str],
    *,
    gemini_client: GeminiClient | None = None,
    mcq_only: bool = False,
) -> CorrectionResult:
    """Hybrid paper correction: MCQ deterministic, non-MCQ via AICorrector.

    Args:
        mark_scheme: parsed mark scheme.
        extracted_answers: per-question student responses.
        gemini_client: required when paper contains non-MCQ questions and mcq_only is False.
        mcq_only: if True, skip AI; non-MCQ questions get marker_source="missing".

    Raises:
        ConfigError: paper has non-MCQ questions, mcq_only=False, and gemini_client is None.
    """
    scheme = _load_mark_scheme(mark_scheme)
    answers = _flatten_answers(extracted_answers)
    log = structlog.get_logger().bind(component="correct_paper")

    leaves = [q for q in scheme.all_questions_flat() if _is_leaf_marked(q)]
    has_non_mcq = any(q.type != QuestionType.MCQ for q in leaves)

    if has_non_mcq and not mcq_only and gemini_client is None:
        raise ConfigError(
            "This paper contains non-MCQ questions. Pass a GeminiClient or set mcq_only=True."
        )

    ai = AICorrector(gemini_client) if (gemini_client and not mcq_only) else None

    corrected: list[CorrectedQuestion] = []
    for q in leaves:
        student_answer = answers.get(q.id)
        if q.type == QuestionType.MCQ:
            corrected.append(_build_mcq_corrected(q, student_answer))
            continue
        if ai is None:
            corrected.append(_build_missing_corrected(q, student_answer))
            continue
        try:
            mark = ai.mark_question(q, student_answer or "")
        except Exception as exc:
            log.warning("ai_marking_failed", question_id=q.id, error=str(exc))
            cq = _build_missing_corrected(q, student_answer)
            corrected.append(cq.model_copy(update={"review_reason": f"AI marking failed: {exc!s}"}))
            continue
        corrected.append(_build_ai_corrected(q, student_answer or "", mark))

    return CorrectionResult(metadata=_exam_metadata(scheme), questions=corrected)
