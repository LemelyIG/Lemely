"""AI-driven marking for non-MCQ questions + hybrid orchestrator for full papers."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping

import structlog

from lemely.core.correction import _exam_metadata, _load_mark_scheme
from lemely.core.loose_schemas import CalculatedAnswer, MarkScheme, Question, QuestionType
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


def _extract_decimals(text: str) -> list[float]:
    """Pull every plain-decimal numeric literal out of free-form text.

    Pure string matching — never evaluates an expression — so it is safe to
    apply to scratch working: a target value that appears verbatim (e.g. an
    intermediate B-mark checkpoint like "AC = 28.89") is found without risk of
    "correcting" the student's arithmetic.
    """
    out: list[float] = []
    for raw in re.findall(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", text):
        try:
            out.append(float(raw))
        except ValueError:
            continue
    return out


def _extract_fraction_values(text: str) -> list[float]:
    """Evaluate simple integer ``a/b`` fractions found in the text.

    Mark schemes routinely mark fractions "oe" with a decimal
    ``calculated_answer.value`` — e.g. a student writing "3/8" must match a
    scheme value of 0.375.

    Deliberately NOT applied to scratch working (see ``_verify_calculated_answers``):
    working text routinely contains a division whose *correct* result differs
    from the student's actual stated answer (e.g. "148 / 16.6 = 89", a
    decimal-place slip) — evaluating it ourselves would silently redo the
    student's arithmetic instead of checking what they wrote.
    """
    out: list[float] = []
    # Integer/integer only (neither operand may be adjacent to a decimal
    # point) and not immediately followed by "= <number>" (that shape is a
    # division-with-shown-result, not a fraction presented as the answer).
    fraction_re = r"(?<![\d.])([-+]?\d+)(?![\d.])\s*/\s*(?<![\d.])(\d+)(?![\d.])(?!\s*=\s*[-+]?\d)"
    for num, denom in re.findall(fraction_re, text):
        try:
            d = float(denom)
            if d != 0:
                out.append(float(num) / d)
        except ValueError:
            continue
    return out


def _sig_round(value: float, sig_figs: int) -> float:
    if value == 0:
        return 0.0
    return round(value, -math.floor(math.log10(abs(value))) + (sig_figs - 1))


def _calculated_value_present(calc: CalculatedAnswer, candidates: list[float]) -> bool:
    """True if any candidate number matches ``calc.value``.

    Matches within the mark scheme's stated precision (dp/sig_figs), or else a
    default 1% relative tolerance.
    """
    if calc.value is None or not candidates:
        return False
    for c in candidates:
        if calc.dp is not None and round(c, calc.dp) == round(calc.value, calc.dp):
            return True
        if calc.sig_figs is not None and _sig_round(c, calc.sig_figs) == _sig_round(
            calc.value, calc.sig_figs
        ):
            return True
        if abs(c - calc.value) <= max(abs(calc.value) * 0.01, 1e-6):
            return True
    return False


def _verify_calculated_answers(
    question: Question,
    student_answer: str,
    student_working: str | None,
    matched_point_ids: list[str],
    starting_awarded: int,
) -> tuple[int, list[str], list[str]]:
    """Deterministic backstop for the AI marker (D2.3).

    The marker was found to award accuracy-type marks on partial-credit theory
    questions without verifying the final numeric value actually appears in the
    student's answer (confirmed at n=68 across 3 papers/2 subjects — same
    failure mode every time: method steps correct, final value wrong, marker
    credits it anyway).

    For every point the AI claims was matched, if the mark scheme attaches a
    ``calculated_answer.value`` to that point (i.e. it is gated on a specific
    numerical result, regardless of M/A/B/C code), reject the point — and its
    marks — unless that value is actually present somewhere in the student's
    answer or working text. Points without a ``calculated_answer`` (method
    steps, prose, levels-based criteria) are untouched.

    Literal decimals are matched across both ``student_answer`` and
    ``student_working`` — extraction commonly splits a question's final
    requested value into ``answer`` while an intermediate value that still
    carries its own mark-scheme point (e.g. a B-mark checkpoint like
    "AC = 28.89") lands in ``working``; both must be checked. Fractions
    ("3/8") are only evaluated from ``student_answer`` — see
    ``_extract_fraction_values`` for why working is excluded from that part.

    Returns (adjusted_awarded_marks, adjusted_matched_point_ids, rejection_reasons).
    """
    points_by_id = {p.id: p for p in question.answer_points}
    candidates = _extract_fraction_values(student_answer)
    candidates += _extract_decimals(student_answer)
    if student_working:
        candidates += _extract_decimals(student_working)

    awarded = starting_awarded
    matched: list[str] = []
    rejections: list[str] = []
    for point_id in matched_point_ids:
        point = points_by_id.get(point_id)
        if (
            point is not None
            and point.calculated_answer is not None
            and point.calculated_answer.value is not None
            and not _calculated_value_present(point.calculated_answer, candidates)
        ):
            awarded = max(0, awarded - point.marks)
            rejections.append(
                f"{point_id}: expected value {point.calculated_answer.value!r} not found "
                "in student answer/working"
            )
            continue
        matched.append(point_id)
    return awarded, matched, rejections


#: Literal substring every message :func:`_check_coherence` returns contains.
#: ``lemely.accuracy.harness._review_triggers`` imports this constant (rather
#: than hard-coding the string) to detect the coherence trigger and append the
#: distinct ``"coherence_mismatch"`` trigger alongside the generic
#: ``"needs_teacher_review"`` one. Keeping this a shared constant means a
#: reworded message cannot silently desync the two sides and make
#: ``coherence_trigger_rate`` read 0.0 with tests still green — see
#: ``tests/test_accuracy_harness.py::CoherenceTriggerWiringTests``.
COHERENCE_TRIGGER_MARKER = "matched_point_ids"

#: Question types whose marking is not decomposed into discrete
#: ``AnswerPoint``s (levels-based, indicative-content, MCQ handled by the
#: deterministic marker). For these, an empty ``question.answer_points`` is
#: expected shape, not a data gap, so the coherence check is skipped
#: entirely. Every other type with empty ``answer_points`` is NOT exempt —
#: see ``_check_coherence`` and BUILD/DECISIONS.md DA10.
_COHERENCE_EXEMPT_TYPES = frozenset(
    {QuestionType.LEVELS_BASED, QuestionType.INDICATIVE_CONTENT, QuestionType.MCQ}
)


def _check_coherence(
    question: Question, matched_point_ids: list[str], awarded_marks: int
) -> str | None:
    """Coherence check (M1.5, #40).

    The marker's claimed ``matched_point_ids`` must exist in the mark scheme
    and must reconcile with ``awarded_marks``.

    Two independent failure modes, either one is a coherence violation. Every
    message this returns contains :data:`COHERENCE_TRIGGER_MARKER` so
    downstream (``harness.py``) can attribute the trigger without a second,
    parallel signal:

    1. A dangling point id: ``matched_point_ids`` references an id that does
       not exist in ``question.answer_points``. Previously silently accepted
       (``_verify_calculated_answers`` still tolerates it for its own,
       narrower purpose — rejecting unverifiable calculated-answer values —
       but does not itself flag the dangling reference); here it is a
       structural inconsistency in its own right and must not reach a student
       unreviewed. When ``question.answer_points`` is empty and the question
       type is not in :data:`_COHERENCE_EXEMPT_TYPES`, EVERY id in
       ``matched_point_ids`` is dangling by definition (there is nothing to
       resolve against), so this falls out of the same code path rather than
       needing a separate branch.
    2. ``awarded_marks`` falls outside the RANGE of marks the matched points
       can imply. ``is_alternative``/``is_optional`` points are non-additive:
       a matched OR-group contributes at least its single highest-value
       member and at most the sum of all matched members of that group.
       ``AnswerPoint`` carries no group identifier, so the number of distinct
       OR-groups among the matched non-additive points is unknowable from the
       data alone — a global point estimate (e.g. "the max of all of them")
       would wrongly cap a legitimate "any 3 from 5" award or two independent
       OR-groups down to one point's marks. Instead:

       ``implied_min = sum(primary marks) + max(non-additive marks, default 0)``
       ``implied_max = sum(primary marks) + sum(non-additive marks)``

       Only ``awarded_marks`` OUTSIDE ``[implied_min, implied_max]`` is
       flagged; the message names the interval, not a single number.

    Computed on the marker's RAW claim (``mark.matched_point_ids`` and the
    range-clamped ``mark.awarded_marks``), before the separate
    ``_verify_calculated_answers`` backstop — this check is about the
    marker's own self-consistency, orthogonal to whether a later numeric
    backstop revises the awarded marks.

    See BUILD/DECISIONS.md DA10 for the empty/absent ``matched_point_ids``
    rule, the type-scoped exemption, and the ``is_alternative``/
    ``is_optional`` range-reconciliation rule.
    """
    if not question.answer_points and question.type in _COHERENCE_EXEMPT_TYPES:
        # Nothing to reconcile against — this type's mark scheme is not
        # decomposed into discrete points by design (levels-based/
        # indicative-content marking, or the deterministic MCQ marker).
        return None

    points_by_id = {p.id: p for p in question.answer_points}
    dangling = [pid for pid in matched_point_ids if pid not in points_by_id]
    if dangling:
        return f"{COHERENCE_TRIGGER_MARKER} references unknown mark point id(s): " + ", ".join(
            dangling
        )

    if not matched_point_ids:
        if awarded_marks > 0:
            return f"{awarded_marks} mark(s) awarded but {COHERENCE_TRIGGER_MARKER} is empty"
        return None

    matched_points = [points_by_id[pid] for pid in matched_point_ids]
    primary = [p for p in matched_points if not p.is_alternative and not p.is_optional]
    non_additive = [p for p in matched_points if p.is_alternative or p.is_optional]
    primary_sum = sum(p.marks for p in primary)
    implied_min = primary_sum + max((p.marks for p in non_additive), default=0)
    implied_max = primary_sum + sum(p.marks for p in non_additive)
    if not (implied_min <= awarded_marks <= implied_max):
        return (
            f"awarded {awarded_marks} mark(s) but {COHERENCE_TRIGGER_MARKER} implies "
            f"between {implied_min} and {implied_max} mark(s)"
        )
    return None


def _build_ai_corrected(
    question: Question,
    student_answer: str,
    mark: AIMarkResponse,
    student_working: str | None = None,
) -> CorrectedQuestion:
    """Convert AIMarkResponse + question metadata into a CorrectedQuestion.

    Four independent reasons flag a question for human review (D2.2, D2.3 for #3, M1.5 for #40):

    1. ``confidence < REVIEW_CONFIDENCE_THRESHOLD`` — the marker itself is unsure.
    2. The marker returned a mark outside ``[0, question.marks]``. The value is
       clamped into range either way, but a marker that asks for 4 marks on a
       3-mark question has misread the mark scheme, so the (silently corrected)
       result must not reach a student unreviewed. This is a structural
       inconsistency signal, independent of the stated confidence, which is where
       the confidence number alone is known to be unreliable.
    3. The marker credited a mark point with a specific ``calculated_answer``
       whose value cannot be found in the student's answer/working — see
       ``_verify_calculated_answers``. This directly targets the D2.3 finding
       that stated confidence does not separate correct from wrong on this
       failure mode, so it must not depend on confidence at all.
    4. ``matched_point_ids`` is incoherent with ``awarded_marks`` (a dangling
       id, or a sum mismatch) — see ``_check_coherence``. Also independent of
       confidence: a marker can be fully confident about an internally
       inconsistent result.
    """
    clamped = max(0, min(mark.awarded_marks, question.marks))
    out_of_range = mark.awarded_marks != clamped

    coherence_reason = _check_coherence(question, list(mark.matched_point_ids), clamped)
    coherence_mismatch = coherence_reason is not None

    awarded, matched_point_ids, rejections = _verify_calculated_answers(
        question, student_answer, student_working, list(mark.matched_point_ids), clamped
    )
    value_mismatch = bool(rejections)
    low_confidence = mark.confidence < REVIEW_CONFIDENCE_THRESHOLD

    reasons: list[str] = []
    if out_of_range:
        reasons.append(
            f"marker returned {mark.awarded_marks} marks for a "
            f"{question.marks}-mark question (clamped to {clamped})"
        )
    if coherence_mismatch:
        reasons.append(coherence_reason or "")
    if value_mismatch:
        reasons.append("unverified accuracy mark(s): " + "; ".join(rejections))
    if not reasons and low_confidence:
        reasons.append(
            f"confidence {mark.confidence:.2f} below review threshold "
            f"{REVIEW_CONFIDENCE_THRESHOLD:.2f}"
        )
    review_reason = " | ".join(reasons) if reasons else None

    return CorrectedQuestion(
        question_id=question.id,
        awarded_marks=awarded,
        maximum_marks=question.marks,
        confidence=confidence_band_for_score(mark.confidence),
        confidence_score=mark.confidence,
        needs_teacher_review=low_confidence or out_of_range or value_mismatch or coherence_mismatch,
        review_reason=review_reason,
        student_answer=student_answer or None,
        expected_answer=None,
        topic=question.topic_hint,
        marker_source="ai",
        feedback=mark.feedback,
        matched_point_ids=matched_point_ids,
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
    # `index` comes from enumerate over `leaves` — the true position in the work
    # list — and never from a counter of MARKING_PROGRESS frames emitted. A
    # question whose AI call raises publishes ERROR instead of MARKING_PROGRESS
    # (see the except branch below), so a frame counter would silently drift and
    # the UI would show a question number that no longer matches reality.
    total_leaves = len(leaves)
    for index, q in enumerate(leaves, start=1):
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
                index=index,  # enumerate position, not an emitted-frame count
                total=total_leaves,
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
                index=index,  # enumerate position, not an emitted-frame count
                total=total_leaves,
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
            # Deliberately no index/total here: the per-question counter belongs to
            # MARKING_PROGRESS, and ERROR is not a progress frame. This `index` is
            # simply skipped — the next question still reports its own enumerate
            # position, so the counter stays aligned with the work list.
            bus.publish(
                EventType.ERROR,
                message=f"AI marking failed for q={q.id}: {exc!s}",
            )
            continue
        cq = _build_ai_corrected(q, student_answer or "", mark, student_working)
        corrected.append(cq)
        prior_results_accumulated[q.id] = cq.awarded_marks
        bus.publish(
            EventType.MARKING_PROGRESS,
            question_id=q.id,
            marker_source="ai",
            confidence=mark.confidence,
            awarded=cq.awarded_marks,
            max_marks=q.marks,
            index=index,  # enumerate position, not an emitted-frame count
            total=total_leaves,
        )

    return CorrectionResult(metadata=_exam_metadata(scheme), questions=corrected)
