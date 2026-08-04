"""AI-driven marking for non-MCQ questions + hybrid orchestrator for full papers."""

from __future__ import annotations

from collections.abc import Mapping

import structlog

from lemely.core.correction import _exam_metadata, _load_mark_scheme
from lemely.core.loose_schemas import MarkScheme, Question, QuestionType
from lemely.core.schemas import (
    REVIEW_CONFIDENCE_THRESHOLD,
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
from lemely.io.validation import validate_mark_scheme
from lemely.runtime.errors import ConfigError
from lemely.runtime.events import EventType, bus


def _is_leaf_marked(q: Question) -> bool:
    """Mark only leaf questions with marks > 0. Skip container/zero-mark items."""
    return q.marks > 0 and not q.parts


def _flatten_answers(
    extracted: ExtractedAnswers | Mapping[str, str],
) -> dict[str, tuple[str, str | None, float]]:
    """Return {question_id: (answer, working_out, confidence)} for every extracted answer."""
    if isinstance(extracted, ExtractedAnswers):
        return {a.question_id: (a.answer, a.working_out, a.confidence) for a in extracted.answers}
    # Plain mapping fallback (Mapping[str, str]): no working_out or confidence available.
    return {str(k): (str(v), None, 1.0) for k, v in extracted.items()}


class AICorrector:
    """Marks individual non-MCQ questions via the shared GeminiClient."""

    def __init__(self, gemini_client: GeminiClient) -> None:
        self._client = gemini_client

    def mark_question(
        self,
        question: Question,
        student_answer: str,
        student_working: str | None = None,
        prior_results: dict[str, int] | None = None,
    ) -> AIMarkResponse:
        g = self._client._settings.gemini
        user_prompt = build_marker_user_prompt(
            question, student_answer, student_working, prior_results
        )

        result = self._client.generate_structured(
            system_prompt=MARKER_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            response_schema=AIMarkResponse,
            prompt_version=VERSION,
            extra_cache_key=f"q={question.id}",
            task_tag="correction",
        )

        # Step 1: thinking retry for borderline confidence (cheaper than Pro escalation).
        borderline_budget = g.thinking_budget_for.get("correction_borderline", 0)
        if result.confidence < g.escalation_confidence_threshold and borderline_budget > 0:
            bus.publish(
                EventType.GEMINI_ESCALATE,
                question_id=question.id,
                confidence=result.confidence,
                escalation_model=f"{g.model_for('correction')} (thinking)",
            )
            result = self._client.generate_structured(
                system_prompt=MARKER_SYSTEM_PROMPT,
                user_prompt=(
                    user_prompt + "\n\nNOTE: First-pass confidence was low. Re-evaluate carefully."
                ),
                response_schema=AIMarkResponse,
                prompt_version=VERSION,
                extra_cache_key=f"q={question.id}:thinking",
                task_tag="correction_borderline",
            )

        # Step 2: Pro escalation if confidence still below threshold.
        if (
            g.escalation_model
            and g.escalation_model != g.model_for("correction")
            and result.confidence < g.escalation_confidence_threshold
        ):
            bus.publish(
                EventType.GEMINI_ESCALATE,
                question_id=question.id,
                confidence=result.confidence,
                escalation_model=g.escalation_model,
            )
            result = self._client.generate_structured(
                system_prompt=MARKER_SYSTEM_PROMPT,
                user_prompt=(
                    user_prompt + "\n\nNOTE: A previous marking attempt returned low confidence. "
                    "Please re-evaluate carefully before responding."
                ),
                response_schema=AIMarkResponse,
                prompt_version=VERSION,
                extra_cache_key=f"q={question.id}:escalated",
                task_tag="correction",
                model=g.escalation_model,
            )

        return result


def _build_mcq_corrected(question: Question, answer: str | None) -> CorrectedQuestion:
    """Deterministic MCQ correction for one question."""
    expected = question.mcq_answer.value if question.mcq_answer else None
    if answer is None or answer == "":
        return CorrectedQuestion(
            question_id=question.id,
            awarded_marks=0,
            maximum_marks=question.marks,
            confidence=ConfidenceBand.LOW,
            confidence_score=0.0,
            needs_teacher_review=True,
            student_answer=None,
            expected_answer=expected,
            topic=question.topic_hint,
            review_reason="missing answer",
            marker_source="deterministic",
        )
    if answer.upper() not in {"A", "B", "C", "D"}:
        return CorrectedQuestion(
            question_id=question.id,
            awarded_marks=0,
            maximum_marks=question.marks,
            confidence=ConfidenceBand.LOW,
            confidence_score=0.0,
            needs_teacher_review=True,
            student_answer=answer,
            expected_answer=expected,
            topic=question.topic_hint,
            review_reason="invalid MCQ answer",
            marker_source="deterministic",
        )
    is_correct = answer.upper() == expected
    return CorrectedQuestion(
        question_id=question.id,
        awarded_marks=question.marks if is_correct else 0,
        maximum_marks=question.marks,
        confidence=ConfidenceBand.HIGH,
        confidence_score=1.0,
        needs_teacher_review=False,
        student_answer=answer.upper(),
        expected_answer=expected,
        topic=question.topic_hint,
        marker_source="deterministic",
    )


def _build_ai_corrected(
    question: Question,
    student_answer: str,
    mark: AIMarkResponse,
) -> CorrectedQuestion:
    """Convert AIMarkResponse + question metadata into a CorrectedQuestion.

    Two independent reasons flag a question for human review (D2.2):

    1. ``confidence < REVIEW_CONFIDENCE_THRESHOLD`` — the marker itself is unsure.
    2. The marker returned a mark outside ``[0, question.marks]``. The value is
       clamped into range either way, but a marker that asks for 4 marks on a
       3-mark question has misread the mark scheme, so the (silently corrected)
       result must not reach a student unreviewed. This is a structural
       inconsistency signal, independent of the stated confidence, which is where
       the confidence number alone is known to be unreliable.
    """
    awarded = max(0, min(mark.awarded_marks, question.marks))
    out_of_range = mark.awarded_marks != awarded
    low_confidence = mark.confidence < REVIEW_CONFIDENCE_THRESHOLD
    review_reason: str | None = None
    if out_of_range:
        review_reason = (
            f"marker returned {mark.awarded_marks} marks for a "
            f"{question.marks}-mark question (clamped to {awarded})"
        )
    elif low_confidence:
        review_reason = (
            f"confidence {mark.confidence:.2f} below review threshold "
            f"{REVIEW_CONFIDENCE_THRESHOLD:.2f}"
        )
    return CorrectedQuestion(
        question_id=question.id,
        awarded_marks=awarded,
        maximum_marks=question.marks,
        confidence=confidence_band_for_score(mark.confidence),
        confidence_score=mark.confidence,
        needs_teacher_review=low_confidence or out_of_range,
        review_reason=review_reason,
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

    # Validate mark scheme structure; warn but do not abort.
    for w in validate_mark_scheme(scheme):
        log.warning("mark_scheme_validation", question_id=w.question_id, message=w.message)
        bus.publish(
            EventType.WARNING,
            message=f"Mark scheme validation [{w.question_id}]: {w.message}",
        )

    leaves = [q for q in scheme.all_questions_flat() if _is_leaf_marked(q)]
    leaf_by_id: dict[str, Question] = {q.id: q for q in leaves}
    prior_results_accumulated: dict[str, int] = {}  # question_id -> awarded_marks
    has_non_mcq = any(q.type != QuestionType.MCQ for q in leaves)

    if has_non_mcq and not mcq_only and gemini_client is None:
        raise ConfigError(
            "This paper contains non-MCQ questions. Pass a GeminiClient or set mcq_only=True."
        )

    ai = AICorrector(gemini_client) if (gemini_client and not mcq_only) else None

    corrected: list[CorrectedQuestion] = []
    for q in leaves:
        answer_tuple = answers.get(q.id)
        student_answer = answer_tuple[0] if answer_tuple else None
        student_working = answer_tuple[1] if answer_tuple else None

        if q.type == QuestionType.MCQ:
            cq = _build_mcq_corrected(q, student_answer)
            corrected.append(cq)
            prior_results_accumulated[q.id] = cq.awarded_marks
            bus.publish(
                EventType.MARKING_PROGRESS,
                question_id=q.id,
                marker_source="deterministic",
                confidence=1.0,
                awarded=cq.awarded_marks,
                max_marks=q.marks,
            )
            continue
        if ai is None:
            cq = _build_missing_corrected(q, student_answer)
            corrected.append(cq)
            prior_results_accumulated[q.id] = 0
            bus.publish(
                EventType.MARKING_PROGRESS,
                question_id=q.id,
                marker_source="missing",
                confidence=0.0,
                awarded=0,
                max_marks=q.marks,
            )
            continue
        sibling_prior: dict[str, int] = {}
        if q.parent_id is not None:
            sibling_prior = {
                qid: marks
                for qid, marks in prior_results_accumulated.items()
                if leaf_by_id[qid].parent_id == q.parent_id
            }
        try:
            mark = ai.mark_question(
                q,
                student_answer or "",
                student_working,
                prior_results=sibling_prior or None,
            )
        except Exception as exc:
            log.warning("ai_marking_failed", question_id=q.id, error=str(exc))
            cq = _build_missing_corrected(q, student_answer)
            corrected.append(cq.model_copy(update={"review_reason": f"AI marking failed: {exc!s}"}))
            bus.publish(
                EventType.ERROR,
                message=f"AI marking failed for q={q.id}: {exc!s}",
            )
            continue
        cq = _build_ai_corrected(q, student_answer or "", mark)
        corrected.append(cq)
        prior_results_accumulated[q.id] = cq.awarded_marks
        bus.publish(
            EventType.MARKING_PROGRESS,
            question_id=q.id,
            marker_source="ai",
            confidence=mark.confidence,
            awarded=cq.awarded_marks,
            max_marks=q.marks,
        )

    return CorrectionResult(metadata=_exam_metadata(scheme), questions=corrected)
