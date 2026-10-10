"""AI-driven marking for non-MCQ questions + hybrid orchestrator for full papers."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from typing import Literal, NamedTuple

import structlog

from lemely.core.binding import BindingVerdict
from lemely.core.binding_gate import GateThresholds, check_off_topic, verdict
from lemely.core.correction import _exam_metadata, _load_mark_scheme
from lemely.core.equivalence import Verdict, VerdictKind, equivalent
from lemely.core.loose_schemas import (
    AnswerPoint,
    CalculatedAnswer,
    MarkScheme,
    MathMarkType,
    MCQAnswer,
    Question,
    QuestionType,
)
from lemely.core.point_groups import group_capped_points_total, group_points
from lemely.core.schemas import (
    REVIEW_CONFIDENCE_THRESHOLD,
    AIMarkResponse,
    ConfidenceBand,
    CorrectedQuestion,
    CorrectionResult,
    ExtractedAnswers,
    PointVerdict,
    SourceBox,
    confidence_band_for_score,
    dedupe_point_verdicts,
)
from lemely.io.gemini import GeminiClient, thinking_rank
from lemely.io.prompts.correction_ai import (
    MARKER_SYSTEM_PROMPT,
    VERSION,
    build_marker_user_prompt,
)
from lemely.io.reread import REREAD_REVIEW_AGREEMENT_THRESHOLD
from lemely.io.validation import validate_mark_scheme
from lemely.runtime.config import MarkingOptions
from lemely.runtime.errors import ConfigError, CostCeilingError, LemelyError
from lemely.runtime.events import EventType, bus


def _is_leaf_marked(q: Question) -> bool:
    """Mark only leaf questions with marks > 0. Skip container/zero-mark items."""
    return q.marks > 0 and not q.parts


class _FlatAnswer(NamedTuple):
    """One extracted answer as ``correct_paper`` consumes it, keyed by leaf id."""

    answer: str
    working_out: str | None
    confidence: float
    source_box: SourceBox | None
    answer_reread: str | None
    reread_agreement: float | None


def _flatten_answers(
    extracted: ExtractedAnswers | Mapping[str, str],
) -> dict[str, _FlatAnswer]:
    """Map question_id to its :class:`_FlatAnswer` per extracted answer.

    NIT-B: two ``ExtractedAnswer``s can share one ``question_id`` -- each is
    individually well-formed, so nothing upstream (extraction validation,
    ``_dropped_question_ids``) catches it. A plain dict comprehension keyed
    on ``question_id`` would silently keep only the last one with no trace
    of the discarded answer anywhere. Policy: **last-wins**, matching the
    dict-comprehension behaviour this function had before duplicates were
    detected, and consistent with ``answers`` ordering elsewhere being
    treated as "most recent take wins" (e.g. a later entry plausibly being
    the model correcting itself within one response). The point of this
    change is not to pick a different survivor -- it's to publish the loss
    instead of leaving it an artifact of dict construction. This mirrors the
    same-file ``MARKING_PROGRESS`` precedent of surfacing internal state as a
    bus event rather than the ``ANSWER_DROPPED`` event, which is published
    from ``lemely/io/answer_extraction.py`` and never from this file.

    The published ``duplicate_counts`` payload counts *extra* occurrences
    beyond the first for each question_id, not the total occurrence count --
    e.g. a question_id seen 3 times contributes 2 to its count, not 3.
    """
    if isinstance(extracted, ExtractedAnswers):
        flattened: dict[str, _FlatAnswer] = {}
        duplicate_counts: dict[str, int] = {}
        for a in extracted.answers:
            if a.question_id in flattened:
                duplicate_counts[a.question_id] = duplicate_counts.get(a.question_id, 0) + 1
            flattened[a.question_id] = _FlatAnswer(
                a.answer,
                a.working_out,
                a.confidence,
                a.source_box,
                a.answer_reread,
                a.reread_agreement,
            )
        if duplicate_counts:
            bus.publish(
                EventType.DUPLICATE_QUESTION_ID,
                duplicate_counts=duplicate_counts,
                total_answers=len(extracted.answers),
            )
        return flattened
    # Plain mapping fallback (Mapping[str, str]): no working_out, confidence,
    # box or re-read available, and no duplicate keys to detect.
    return {str(k): _FlatAnswer(str(v), None, 1.0, None, None, None) for k, v in extracted.items()}


#: Fix round 1 (spec 2026-09-26 §4): the letters ``_build_mcq_corrected``
#: accepts, defined once and shared with it rather than hardcoded twice.
#: Fix round 2: derived from :class:`MCQAnswer` instead of a bare literal
#: set. ``typing.get_args`` only resolves a ``Literal``/``Union`` alias, and
#: ``MCQAnswer`` is a plain ``StrEnum``, so this iterates its members
#: instead -- the goal (one definition, not two) is the same either way.
_MCQ_LETTERS = frozenset(letter.value for letter in MCQAnswer)

#: Surrounding characters a re-read may be wrapped in ("(A)", "A.", "[A]")
#: that carry no signal about which letter was read. Straight quotes only
#: (ruff RUF001): curly quotes are not stripped, so a re-read genuinely
#: wrapped in them is left to the embedded-punctuation "nothing usable"
#: path rather than silently treated the same as straight ones.
_MCQ_STRIP_CHARS = "()[]{}<>.,;:!?\"'"


def _normalise_mcq_reread(text: str) -> str | None:
    """Strip surrounding whitespace, punctuation and brackets, upper-case.

    Fix round 1: substitution used to hand ``_build_mcq_corrected`` the raw
    re-read text verbatim, so a re-read of "A." or "(A)" on a correctly-read
    "A" was marked ``0`` ("invalid MCQ answer") instead of left alone or
    correctly substituted. Returns ``None`` unless what remains after
    stripping is a single letter :func:`_build_mcq_corrected` itself
    accepts -- embedded punctuation (e.g. "A/B") is not "surrounding" and is
    deliberately NOT stripped, so it still returns ``None`` for that case.

    Fix round 2 re-review: ``str.strip(chars)`` strips only the given chars
    and stops at the first character outside that set -- so " (A) " (a
    leading SPACE, not in :data:`_MCQ_STRIP_CHARS`) was left completely
    unstripped. A plain ``.strip()`` (whitespace) now runs first.
    """
    stripped = text.strip().strip(_MCQ_STRIP_CHARS).upper()
    return stripped if stripped in _MCQ_LETTERS else None


def _mcq_agrees(first_read: str, reread: str | None) -> bool:
    """Fix round 2: a re-read normalising to the same letter is agreement.

    "A." or "(A)" against a first read of "A" must never be treated as a
    disagreement -- both readings say the same thing once surrounding
    punctuation is stripped, so there is nothing here for the flag or
    substitution to act on.

    Fix round 2 re-review: this must hold ONLY when the first read is
    ALREADY a bare letter :func:`_build_mcq_corrected` accepts as-is --
    ``first_read.upper() in _MCQ_LETTERS``, no stripping. If the first read
    itself needs normalising too ("(A)", "a."), treating it as agreement
    would skip substitution entirely and leave the UN-normalised first read
    to reach ``_build_mcq_corrected``, which does not strip -- scoring 0
    ("invalid MCQ answer") instead of being substituted to the letter both
    readings actually agree on.
    """
    if reread is None or first_read.upper() not in _MCQ_LETTERS:
        return False
    return first_read.upper() == _normalise_mcq_reread(reread)


def _disagreeing_agreement(flat: _FlatAnswer, *, is_mcq: bool = False) -> float | None:
    """The re-read's agreement score when it disagrees, else ``None``.

    Spec 2026-09-26 §4: "disagrees" means ``reread_agreement`` is not
    ``None`` and is below :data:`REREAD_REVIEW_AGREEMENT_THRESHOLD`. Fix
    round 1: gives callers the narrowed ``float`` in one step instead
    of a boolean plus a defensive ``flat.reread_agreement or 0.0`` that was
    both dead (this function's own check already guarantees non-``None``)
    and wrong in spirit (``0.0`` is a legitimate agreement score, not a
    fallback value). Fix round 2: on an MCQ leaf (``is_mcq``), a re-read
    that :func:`_mcq_agrees` with the first read overrides a low raw score
    back to agreement -- ``flat.answer``/``flat.answer_reread`` must be the
    PRE-substitution pair for this to mean anything (callers pass
    ``original[qid]``, never the post-substitution ``answers[qid]``).
    """
    agreement = flat.reread_agreement
    if agreement is None or agreement >= REREAD_REVIEW_AGREEMENT_THRESHOLD:
        return None
    if is_mcq and _mcq_agrees(flat.answer, flat.answer_reread):
        return None
    return agreement


def _substituted_answer(flat: _FlatAnswer, *, is_mcq: bool) -> str | None:
    """The text substitution would mark instead of the first read.

    ``None`` when the re-read is not usable for substitution: it agrees
    with the first read (including, on an MCQ leaf, agreeing once
    normalised -- fix round 2), it is blank, or -- on an MCQ leaf, fix
    round 1 -- it does not normalise to a single option letter. Non-MCQ
    leaves substitute the stripped re-read text verbatim (fix round 1:
    previously unstripped, so a re-read with incidental leading/trailing
    whitespace would have been quoted and marked with it).

    Final review I2: ``None`` too when the FIRST read is blank. The re-read
    of a blank crop is the model's text, never the student's, and marking
    it would pay a call, may award marks, and flag the row -- the US-039
    self-review exploit the flag-off path closes (see
    :func:`_attach_extraction_context`). A blank row stays exactly as
    ``_build_blank_corrected`` leaves it.
    """
    if _is_blank(flat.answer):
        return None
    if _disagreeing_agreement(flat, is_mcq=is_mcq) is None:
        return None
    reread = (flat.answer_reread or "").strip()
    if not reread:
        return None
    return _normalise_mcq_reread(reread) if is_mcq else reread


def _quote(text: str | None) -> str:
    cleaned = (text or "").strip().replace("\n", " ")
    return repr(cleaned if len(cleaned) <= 60 else cleaned[:60] + "…")


def _reread_reason(
    *, first_read: str | None, reread: str | None, agreement: float, substitution: bool
) -> str:
    """The three shapes of the review reason (spec 2026-09-26 §4)."""
    head = (
        "extraction re-read disagreed with the first read "
        f"(agreement {agreement:.2f} < {REREAD_REVIEW_AGREEMENT_THRESHOLD:.2f})"
    )
    if substitution and (reread or "").strip():
        return (
            f"{head}; marked the re-read {_quote(reread)}, the first read was {_quote(first_read)}"
        )
    if substitution:
        return (
            f"{head}; the re-read returned nothing usable, "
            f"marked the first read {_quote(first_read)}"
        )
    return f"{head}; marked the first read {_quote(first_read)}, the re-read gave {_quote(reread)}"


def _join_reason(existing: str | None, added: str) -> str:
    return f"{existing} | {added}" if existing else added


def _dropped_question_ids(extracted: ExtractedAnswers | Mapping[str, str]) -> frozenset[str]:
    """Question ids whose answer was extracted but discarded as malformed.

    US-031 review MUST-FIX 7 (stronger fix): ``ExtractedAnswers`` is the only
    shape that can carry this -- a plain ``Mapping[str, str]`` (the
    correction-only/oracle-answer bypass) never went through extraction at
    all, so there is nothing to have dropped.
    """
    if isinstance(extracted, ExtractedAnswers):
        return frozenset(extracted.dropped_question_ids)
    return frozenset()


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
        principles: list[str] | None = None,
        *,
        equivalence_gate: bool = False,
        prior_values: dict[str, str] | None = None,
    ) -> AIMarkResponse:
        """Mark one question.

        ``principles`` is the paper's own ``metadata.generic_marking_principles``
        (#41 / ruling A13). They are the authority on the M/A dependency; the
        system prompt's strict rule is the fallback for papers that do not print
        them or whose GMP pages could not be parsed.

        ``equivalence_gate`` (US-013, defaults False): forwarded to
        :func:`build_marker_user_prompt`, which appends the I6 point-verdict
        instructions to the USER prompt only when True. ``AIMarkResponse``
        (the ``response_schema`` below) is the SAME class either way --
        ``point_verdicts`` is an additive field the model simply never
        populates when not asked (see that model's docstring) -- and
        ``VERSION`` is not bumped: the flag defaulting off means the prompt
        actually sent for every call today is byte-identical to before this
        story. See ``correction_ai`` module notes / the commit message for
        the ``_params_fingerprint`` schema-hash consequence of the additive
        field regardless of this flag.

        ``prior_values`` (I7, US-013, defaults None): forwarded to
        :func:`build_marker_user_prompt` -- see its docstring and
        :func:`_maybe_apply_ecf_substitution`, the only caller that ever
        passes this non-empty. Not tied to ``equivalence_gate``: this
        parameter exists on every call regardless of that flag's value.
        """
        g = self._client._settings.gemini
        user_prompt = build_marker_user_prompt(
            question,
            student_answer,
            student_working,
            prior_results,
            principles,
            equivalence_gate=equivalence_gate,
            prior_values=prior_values,
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
        # F1 review MUST-FIX 2 (2026-09-17): the gate now reads
        # GeminiClient.resolved_thinking() — the single source of truth also
        # used to build the actual API call — instead of re-deriving the
        # thinking_level_for/thinking_budget_for defaults here. The two used
        # to disagree: a partial TOML override
        # (``thinking_level_for = {"correction": "low"}``, which REPLACES the
        # whole dict rather than merging into it) left this file defaulting
        # the missing "correction_borderline" tag to "high" while gemini.py
        # defaulted it to "low" — the gate fired believing it would retry at
        # HIGH, but the actual call ran at LOW. The gate fires whenever the
        # borderline call would think strictly harder than the original
        # correction call did, on whichever substrate (level or budget) the
        # resolved model actually reads — this also generalises the old 2.5
        # "budget > 0" rule (a correction tag with no configured budget
        # defaults to 0, so "borderline > correction" reduces to the same
        # "budget > 0" check in the common case).
        correction_model = g.model_for("correction")
        correction_thinking = self._client.resolved_thinking("correction", correction_model)
        borderline_thinking = self._client.resolved_thinking(
            "correction_borderline", correction_model
        )
        borderline_gate = thinking_rank(borderline_thinking) > thinking_rank(correction_thinking)
        # Spec 2026-09-26 §3 (#10): the Step-2 guard compares against the
        # call that ACTUALLY RAN LAST, not the original correction call.
        # Step 1 moves the baseline: after a borderline retry the last call
        # ran at (correction_model, borderline_thinking), and under the
        # shipped defaults (low / high / high on one model) the escalation
        # tuple equals that -- Step 2 would bill the identical call again.
        last_call = (correction_model, correction_thinking)
        if result.confidence < g.escalation_confidence_threshold and borderline_gate:
            bus.publish(
                EventType.GEMINI_ESCALATE,
                question_id=question.id,
                confidence=result.confidence,
                escalation_model=f"{correction_model} (thinking)",
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
            last_call = (correction_model, borderline_thinking)

        # Step 2: Pro escalation if confidence still below threshold.
        # F1 fix (4): under F1 defaults correction_model == escalation_model
        # (both "gemini-3.8-flash"), so a bare model-name comparison would make
        # this branch permanently unreachable — the whole point of the
        # escalation step. The guard compares the (model, thinking) tuple the
        # escalation call would run with against the tuple of the call that
        # ran last (``last_call``), which Step 1 updates: same model but a
        # higher thinking_level_for["escalation"] still counts as a genuinely
        # different, worth-trying call. Both tuples are read via
        # ``resolved_thinking`` (F1 review MUST-FIX 2) rather than re-derived,
        # so an unresolved value (e.g. a stray "minimal" on a model that
        # demotes it to "low") can never make this comparison disagree with
        # what the call underneath actually runs at.
        escalation_model = g.escalation_model
        if (
            escalation_model
            and (escalation_model, self._client.resolved_thinking("escalation", escalation_model))
            != last_call
            and result.confidence < g.escalation_confidence_threshold
        ):
            bus.publish(
                EventType.GEMINI_ESCALATE,
                question_id=question.id,
                confidence=result.confidence,
                escalation_model=escalation_model,
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
                task_tag="escalation",
                model=escalation_model,
            )

        # Post-I6-review Item A: ``PointVerdict.ecf_applied`` must be
        # CODE-set only -- I7's whole contract is that it records a re-mark
        # the CODE performed (:func:`_maybe_apply_ecf_substitution`), never
        # something the model claims about its own single-pass answer. But
        # the field is on the wire response schema with no description
        # telling the model that, so nothing stops it setting
        # ``ecf_applied=True`` unprompted -- which would persist onto
        # ``CorrectedQuestion.point_verdicts`` as an ECF claim the code never
        # made, on a call where no substitution happened at all (including
        # every call today, since ``ecf_substitution`` defaults off).
        # Unconditionally forced False here, regardless of
        # ``equivalence_gate``/``ecf_substitution`` or what the model
        # returned, so ``_maybe_apply_ecf_substitution``'s explicit
        # ``ecf_applied=True`` merge is the ONLY place this field can ever
        # become True.
        if result.point_verdicts:
            result = result.model_copy(
                update={
                    "point_verdicts": [
                        pv.model_copy(update={"ecf_applied": False}) for pv in result.point_verdicts
                    ]
                }
            )
        return result


def _build_mcq_corrected(
    question: Question,
    answer: str | None,
    extraction_confidence: float | None = None,
) -> CorrectedQuestion:
    """Deterministic MCQ correction for one question."""
    expected = question.mcq_answer.value if question.mcq_answer else None
    if question.mcq_answer is None:
        # Defensive hardening, not a live fix (D15, spec §2.2(ii)): `Question`'s
        # own validator forbids an MCQ-typed question with `mcq_answer=None`,
        # so this branch is unreachable through any real parsing path today.
        # Without it, a Question that violated that invariant would silently
        # fall through to `is_correct = answer.upper() == None` → False →
        # awarded_marks=0 reported at HIGH/1.0 confidence with no review flag
        # — a wrong mark asserted with full, unflagged confidence.
        return CorrectedQuestion(
            question_id=question.id,
            awarded_marks=0,
            maximum_marks=question.marks,
            confidence=ConfidenceBand.LOW,
            confidence_score=0.0,
            needs_teacher_review=True,
            student_answer=answer,
            expected_answer=None,
            topic=question.topic_hint,
            review_reason="mark scheme has no mcq_answer for this question",
            marker_source="deterministic",
            extraction_confidence=extraction_confidence,
        )
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
            extraction_confidence=extraction_confidence,
        )
    if answer.upper() not in _MCQ_LETTERS:
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
            extraction_confidence=extraction_confidence,
        )
    is_correct = answer.upper() == expected
    # #36 MUST-FIX 1 (repair pass): the deterministic letter comparison itself
    # is certain GIVEN the extraction, so confidence in the awarded mark is
    # confidence that the letter was read correctly. Propagate
    # extraction_confidence into confidence_score instead of hardcoding 1.0
    # (D13) -- the old code threaded extraction_confidence through as inert
    # metadata that nothing read. Fall back to 1.0 only when there is
    # genuinely no extraction signal at all -- there is no basis to invent
    # uncertainty that was never measured. Two call paths reach that same
    # 1.0 by different routes, and the distinction matters if either is ever
    # changed: the oracle path passes `extraction_confidence=None` and is
    # caught by the fallback here, whereas `_flatten_answers`' plain
    # `Mapping[str, str]` branch supplies a literal `1.0` in its tuple
    # (`(str(v), None, 1.0)`) and so never reaches the fallback at all.
    # Band and review-flag are DERIVED from that score via the
    # module's one calibrated cut-offs, not hand-rolled: a clean single
    # letter (option A's ~0.90-0.93 steady state) still lands HIGH and
    # unflagged, so correct MCQs do not flood the review queue; a letter the
    # extractor genuinely read with low confidence now correctly gets
    # flagged even though the mark itself is correct.
    mcq_confidence_score = extraction_confidence if extraction_confidence is not None else 1.0
    mcq_needs_review = mcq_confidence_score < REVIEW_CONFIDENCE_THRESHOLD
    return CorrectedQuestion(
        question_id=question.id,
        awarded_marks=question.marks if is_correct else 0,
        maximum_marks=question.marks,
        confidence=confidence_band_for_score(mcq_confidence_score),
        confidence_score=mcq_confidence_score,
        needs_teacher_review=mcq_needs_review,
        student_answer=answer.upper(),
        expected_answer=expected,
        topic=question.topic_hint,
        review_reason=(
            f"extraction confidence {mcq_confidence_score:.2f} below review threshold "
            f"{REVIEW_CONFIDENCE_THRESHOLD:.2f}"
            if mcq_needs_review
            else None
        ),
        marker_source="deterministic",
        extraction_confidence=extraction_confidence,
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


def _equivalence_fallback_verdict(
    calc: CalculatedAnswer, student_answer: str, student_working: str | None
) -> tuple[Verdict, Literal["answer", "working"]]:
    """Consult ``lemely.core.equivalence`` for a rejected point (I8, US-005b).

    A fallback for a point ``_calculated_value_present`` already rejected —
    see the module docstring's point 3.

    Tries ``student_answer`` first, then ``student_working`` -- mirroring
    ``_verify_calculated_answers``' own literal-candidate handling, since
    extraction commonly splits a question's final requested value into
    ``answer`` while an intermediate checkpoint value lands in ``working``.
    An ``EQUAL_PROVEN`` match on either side is returned immediately, since
    nothing stronger exists; otherwise surfaces a genuine equality finding
    if either side has one, preferring proof over sampling. Verdicts are
    ranked ``EQUAL_SAMPLED`` > ``NOT_EQUAL`` > ``UNPARSEABLE``: a
    ``NOT_EQUAL`` or ``UNPARSEABLE`` verdict on either side is never itself
    reported, since it repeats what the already-triggered literal-match
    rejection already says. ``EQUAL_SAMPLED`` wins between the two sides:
    a wrong final answer with a working expression that samples equal to
    the checkpoint value is exactly the case this mechanism exists to
    surface for a human reviewer, since that is where method marks live.
    ``EQUAL_SAMPLED`` is still never promoted to ``auto_awardable`` -- it
    is evidence, not proof (see ``Verdict.auto_awardable``) -- this only
    decides which finding a reviewer gets to see.

    Returns the verdict alongside which side it came from (NIT H,
    final-branch-review): a reviewer weighing an A-mark needs to know
    whether the *answer* or the *working* sampled equal, not just that
    something did.
    """
    target = str(calc.value)
    answer_verdict = equivalent(
        student_answer, target, sig_figs=calc.sig_figs, dp=calc.dp, tolerance=calc.tolerance
    )
    if answer_verdict.kind is VerdictKind.EQUAL_PROVEN or not student_working:
        return answer_verdict, "answer"
    working_verdict = equivalent(
        student_working, target, sig_figs=calc.sig_figs, dp=calc.dp, tolerance=calc.tolerance
    )
    if working_verdict.kind is VerdictKind.EQUAL_PROVEN:
        return working_verdict, "working"
    rank = {
        VerdictKind.EQUAL_SAMPLED: 2,
        VerdictKind.NOT_EQUAL: 1,
        VerdictKind.UNPARSEABLE: 0,
    }
    if rank[working_verdict.kind] > rank[answer_verdict.kind]:
        return working_verdict, "working"
    return answer_verdict, "answer"


def _verify_calculated_answers(
    question: Question,
    student_answer: str,
    student_working: str | None,
    matched_point_ids: list[str],
    starting_awarded: int,
    *,
    equivalence_gate: bool = False,
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

    ``equivalence_gate`` (US-005b, defaults False): when a point would
    otherwise be rejected here, also consult
    ``lemely.core.equivalence.equivalent`` (:func:`_equivalence_fallback_verdict`)
    as a fallback. An ``equal`` verdict (of either kind — ``EQUAL_PROVEN`` or
    ``EQUAL_SAMPLED``) never changes ``awarded``: even a proven match is only
    "could justify" (D12's ``auto_awardable``), not "does" — this function
    stops short of acting on it and only adds the conflict to the point's
    rejection reason, for a human reviewer to weigh. With the flag off, or
    on a ``NOT_EQUAL``/``UNPARSEABLE`` verdict, behaviour is unchanged.

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
            reason = (
                f"{point_id}: expected value {point.calculated_answer.value!r} not found "
                "in student answer/working"
            )
            if equivalence_gate:
                verdict, side = _equivalence_fallback_verdict(
                    point.calculated_answer, student_answer, student_working
                )
                if verdict.equal_by_any_method:
                    reason += (
                        f"; lemely.core.equivalence found this {verdict.kind.value} on "
                        f"{side} to the scheme value -- routed to review, not auto-awarded"
                    )
            awarded = max(0, awarded - point.marks)
            rejections.append(reason)
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
    question: Question,
    matched_point_ids: list[str],
    awarded_marks: int,
    *,
    point_verdicts: list[PointVerdict] | None = None,
    groups: Sequence[tuple[str | None, int | None]],
) -> str | None:
    """Coherence check (M1.5, #40).

    The marker's claimed ``matched_point_ids`` must exist in the mark scheme
    and must reconcile with ``awarded_marks``.

    Three independent failure modes, any one of which is a coherence
    violation. Every message this returns contains
    :data:`COHERENCE_TRIGGER_MARKER` so downstream (``harness.py``) can
    attribute the trigger without a second, parallel signal:

    0. ``point_verdicts`` (I6's verdict path only -- ``None`` on the legacy
       path, see below) repeats a ``point_id``. Numbered 0, ahead of 1 and 2
       below, rather than renumbering them: it inspects the marker's raw
       ``point_verdicts`` output, upstream of what modes 1 and 2 inspect
       (the already-derived ``matched_point_ids``/``awarded_marks``).
       ``matched_point_ids`` and
       ``awarded_marks`` have both already been through
       :func:`_awarded_from_verdicts`'s ``dedupe_point_verdicts`` call by the
       time they reach here, so a repeat is invisible in THEM; this check
       looks at the marker's own RAW output instead, the same way the other
       two modes below look at the marker's raw claim rather than a
       downstream derivation. Scoped to the verdict path deliberately: the
       legacy path's caller passes ``point_verdicts=None``, so a duplicate in
       ``mark.matched_point_ids`` (whose ``awarded_marks`` comes from the
       model, not a Python sum, and therefore has no inflation bug) cannot
       newly trigger review here.
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
       can imply. ``is_alternative``/``is_optional`` points are non-additive.
       Both paths pass ``groups`` -- the ``(group_key, cap)`` per scheme
       point from :func:`lemely.core.point_groups.group_points` -- and each
       matched group contributes at least ``min(cap, its largest matched tariff)``
       and at most ``min(cap, sum of matched tariffs)`` -- the floor is
       capped too, so a group whose cap binds below its largest matched
       tariff (a pool whose room is smaller than one member's own tariff:
       an unstated pool's room is the whole leftover after the fixed points,
       never shared; a ``select_count`` pool's room is what earlier
       ``select_count`` pools left of it -- only stated-N pools consume a
       shared room) narrows rather than inverts the interval. Both ends are
       then clamped at ``question.marks`` (triage F6), because the awarded
       figure compared against them already is. There is one rule: the
       legacy path passes ``groups`` too (#272), reversing the 2026-09-26
       spec's §1 statement that it keeps the global ``primary +
       non-additive`` rule. That rule flagged an either/or pair matched both
       ways and a det-shaped scheme whose independent tariffs exceed the
       question, and missed an over-award on a stated ``select_count`` pool.

       Only ``awarded_marks`` OUTSIDE ``[implied_min, implied_max]`` is
       flagged; the message names the interval, not a single number.

    Computed on the marker's RAW claim (``mark.matched_point_ids`` and the
    range-clamped ``mark.awarded_marks``), before the separate
    ``_verify_calculated_answers`` backstop — this check is about the
    marker's own self-consistency, orthogonal to whether a later numeric
    backstop revises the awarded marks.

    See BUILD/DECISIONS.md DA10 for the empty/absent ``matched_point_ids``
    rule and the type-scoped exemption. DA10's Decision 3 (the global
    ``primary + non-additive`` range) is superseded by #272 and DA10a: the
    range is the grouped interval described in mode 2 above, on both paths.
    """
    if not question.answer_points and question.type in _COHERENCE_EXEMPT_TYPES:
        # Nothing to reconcile against — this type's mark scheme is not
        # decomposed into discrete points by design (levels-based/
        # indicative-content marking, or the deterministic MCQ marker).
        return None

    if point_verdicts is not None:
        seen_ids: set[str] = set()
        repeated: set[str] = set()
        for pv in point_verdicts:
            if pv.point_id in seen_ids:
                repeated.add(pv.point_id)
            seen_ids.add(pv.point_id)
        if repeated:
            return f"{COHERENCE_TRIGGER_MARKER}: point_verdicts repeats point id(s): " + ", ".join(
                sorted(repeated)
            )

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
    scheme_points, _ = _scheme_groups(question)
    group_of = {
        point.id: (key, cap) for point, (key, cap) in zip(scheme_points, groups, strict=True)
    }
    implied_min = 0
    implied_max = 0
    by_group: dict[str, tuple[int, list[int]]] = {}
    for p in matched_points:
        key, cap = group_of.get(p.id, (None, None))
        if key is None:
            implied_min += p.marks
            implied_max += p.marks
        else:
            by_group.setdefault(key, (cap or 0, []))[1].append(p.marks)
    for cap, tariffs in by_group.values():
        implied_min += min(cap, max(tariffs))
        implied_max += min(cap, sum(tariffs))
    # Triage F6: `awarded_marks` reaches here already clamped at
    # `question.marks` (`_group_capped_total`), so the interval must be
    # too, or a fully-correct answer is routed to review. Three shapes
    # overfill the question: a det-parsed scheme whose independent
    # tariffs exceed it (reconcile.py bypasses validate_mark_point_sum; 4
    # of 479 corpus schemes), a valid scheme whose alternative outweighs
    # its sibling, and unstated pools, each bounded by the full leftover
    # (triage F5) so their caps can sum past the question.
    implied_min = min(implied_min, question.marks)
    implied_max = min(implied_max, question.marks)
    if not (implied_min <= awarded_marks <= implied_max):
        return (
            f"awarded {awarded_marks} mark(s) but {COHERENCE_TRIGGER_MARKER} implies "
            f"between {implied_min} and {implied_max} mark(s)"
        )
    return None


def _normalise_span(text: str) -> str:
    """Whitespace-collapse + casefold, for :func:`_span_found`."""
    return re.sub(r"\s+", " ", text).strip().casefold()


def _span_found(evidence_span: str, *texts: str | None) -> bool:
    """I6 (US-013) span-evidence check -- EXACT/SUBSTRING CONTAINMENT, no fuzzy threshold.

    The plan's ``_check_coherence`` extension calls for
    ``rapidfuzz.fuzz.partial_ratio(...) >= 0.8``. `rapidfuzz` is absent from
    this project: confirmed absent from ``pyproject.toml`` and ``uv.lock``,
    same finding US-010 hit first (filed as ``US-041`` for the dependency
    itself, which is not in this story's file ownership -- ``pyproject.toml``
    is explicitly out of scope here). US-010 substituted
    ``difflib.SequenceMatcher`` under the plan's ``0.8`` threshold verbatim,
    and an independent review of that commit found the substitution
    dangerous even though it was disclosed: Ratcliff/Obershelp gestalt
    pattern matching is NOT normalised Levenshtein distance, so the same
    numeric threshold means a different thing under each metric, and ``0.8``
    was never validated against the substitute.

    Decision for I6 (route (b) from the brief, not route (a) --
    disclosed-but-still-a-substitute -- or (c) -- block the whole gate):
    implement the span check as containment with NO threshold at all. A
    containment check that is too strict fails LOUDLY -- a genuine paraphrase
    or OCR near-miss queues for review instead of matching -- which is the
    safe failure direction for a check that gates whether a mark can be
    auto-trusted. A fuzzy check against an unvalidated threshold fails
    SILENTLY, in the direction of awarding marks nobody can point to
    evidence for -- exactly the defect this story exists to catch. The
    `rapidfuzz.fuzz.partial_ratio(...) >= 0.8` form the plan specifies is
    tracked as US-041 and lands once, deliberately, with the dependency and
    the lock refresh -- not smuggled in here against the wrong metric.
    """
    span = _normalise_span(evidence_span)
    if not span:
        return False
    return any(span in _normalise_span(t) for t in texts if t)


#: I6 (US-013): marker for the point-evidence extension of the coherence
#: gate. Deliberately does NOT contain :data:`COHERENCE_TRIGGER_MARKER`
#: ("matched_point_ids") -- the brief is explicit that a `no_span` finding
#: is queued under the EXISTING `low_confidence` review bucket with a
#: structural reason string, not a new `coherence_mismatch`-shaped trigger
#: and not a new review-reason enum member (this branch already spent a
#: whole story, US-038, on the cost of an inexpressible marker-source enum
#: value; a fifth review-reason value would repeat it).
#: ``lemely.accuracy.harness._review_triggers`` therefore reports a
#: `no_span` finding exactly like any other generic `needs_teacher_review`
#: reason, never as `coherence_mismatch`.
POINT_EVIDENCE_TRIGGER_MARKER = "no_span"


def _check_point_evidence(
    question: Question,
    point_verdicts: list[PointVerdict],
    student_answer: str,
    student_working: str | None,
) -> str | None:
    """I6 coherence-gate extension (#40 continuation, D11, US-013).

    Two independent rules, checked per verdict in list order; the first
    violation found is returned (one reason, like :func:`_check_coherence`,
    not an exhaustive list):

    1. Every ``awarded`` verdict must carry a non-empty ``evidence_span``
       found (:func:`_span_found`) in the student's transcribed answer or
       working -- otherwise a :data:`POINT_EVIDENCE_TRIGGER_MARKER`
       (``no_span``) review trigger.
    2. An awarded M-point (``AnswerPoint.math_mark_type is MathMarkType.M``)
       requires its span to be found specifically INSIDE ``working_out``
       when working was supplied (D11, working-vs-answer): a method mark
       whose only "evidence" is the final answer line is not evidence of
       method, even if that same text also happens to appear verbatim in
       the answer box.

    Only reached from :func:`_build_ai_corrected_from_verdicts`, itself
    only reached when ``equivalence_gate`` is on and the marker returned at
    least one verdict.
    """
    points_by_id = {p.id: p for p in question.answer_points}
    for pv in point_verdicts:
        if pv.verdict != "awarded":
            continue
        point = points_by_id.get(pv.point_id)
        if point is not None and point.math_mark_type is MathMarkType.M and student_working:
            if not _span_found(pv.evidence_span, student_working):
                return (
                    f"{POINT_EVIDENCE_TRIGGER_MARKER}: M-point {pv.point_id} evidence span "
                    "not found in working_out"
                )
            continue
        if not _span_found(pv.evidence_span, student_answer, student_working):
            return (
                f"{POINT_EVIDENCE_TRIGGER_MARKER}: point {pv.point_id} awarded with no "
                "matching evidence span"
            )
    return None


class _VerdictTotals(NamedTuple):
    """What the verdict path derived from a marker's ``point_verdicts``.

    ``capped`` is the mark the student gets: independent points add their
    tariff, each scheme group adds ``min(group cap, awarded tariffs in the
    group)``, and the whole is capped at ``question.marks``. ``additive`` is
    the plain sum the coverage check compares the marker's own claim against
    (spec 2026-09-26 §1: a marker that awarded both halves of an either/or
    and claimed 2 must not be reported as under-described answer_points).
    """

    capped: int
    additive: int
    matched_point_ids: list[str]


def _dedupe_scheme_points(points: list[AnswerPoint]) -> list[AnswerPoint]:
    """First occurrence of a repeated scheme point id wins.

    ``derive_point_rows`` applies the same rule to the same list, so both
    sides read the same group structure.
    """
    kept: list[AnswerPoint] = []
    seen: set[str] = set()
    for point in points:
        if point.id in seen:
            continue
        seen.add(point.id)
        kept.append(point)
    return kept


def _scheme_groups(
    question: Question,
) -> tuple[list[AnswerPoint], list[tuple[str | None, int | None]]]:
    """The deduplicated scheme points and their ``(group_key, cap)`` pairs."""
    points = _dedupe_scheme_points(list(question.answer_points))
    groups = group_points(points, total=question.marks, select_count=question.select_count)
    return points, groups


def _group_capped_total(question: Question, awarded_ids: set[str]) -> tuple[int, int]:
    """``(capped, additive)`` for the scheme points in ``awarded_ids``.

    ``capped``: independent points add their tariff, each scheme group adds
    ``min(group cap, awarded tariffs in the group)``, and the whole is capped
    at ``question.marks`` (:func:`lemely.core.point_groups.group_capped_points_total`).
    ``additive``: the plain sum, likewise capped. One function so that
    :func:`_awarded_from_verdicts` (the marker's claim), the post-backstop
    recomputation in :func:`_build_ai_corrected_from_verdicts` and the
    legacy path's :func:`_awarded_after_backstop` (both triage F4) cannot
    disagree.
    """
    points, groups = _scheme_groups(question)
    awarded = [
        (point.marks, key, cap)
        for point, (key, cap) in zip(points, groups, strict=True)
        if point.id in awarded_ids
    ]
    additive = sum(tariff for tariff, _key, _cap in awarded)
    capped = group_capped_points_total(awarded, total=question.marks)
    return capped, min(additive, question.marks)


def _awarded_after_backstop(
    question: Question, claimed: int, claimed_ids: set[str], surviving_ids: set[str]
) -> int:
    """The legacy path's total after the backstop rejected points (triage F4).

    Called once :func:`_verify_calculated_answers` has rejected something.
    ``lost`` is what the rejected points were worth to the marker's ids under
    the group rule and the ``question.marks`` clamp
    (:func:`_group_capped_total` before minus after), so a rejected either/or
    member that its surviving sibling still covers costs nothing. The result
    is ``min(surviving total, claimed - lost)``, floored at 0:

    * a marker whose claim matches its ids (the well-behaved case) gets the
      surviving ids' capped total, exactly what the verdict path computes;
    * it never exceeds ``claimed``, so the backstop can never raise a mark;
    * a marker that claimed MORE than its ids back keeps only what the
      survivors earn -- a mark no id backs is not kept after the backstop
      has already caught one claim out;
    * a marker that claimed LESS than its ids back still loses ``lost`` off
      its claim, as the old subtraction did: its own withholding is not
      assumed to have been on the rejected point. The safe direction, since
      which point the marker withheld is unknowable and a rejection always
      routes the question to review.

    With independent points only, the clamp not binding and a claim no
    higher than its ids back, this is the old arithmetic: ``claimed`` minus
    each rejected tariff. Runs only when something was rejected; otherwise
    the legacy path keeps the marker's clamped claim as it always has.
    """
    claimed_total, _ = _group_capped_total(question, claimed_ids)
    surviving_total, _ = _group_capped_total(question, surviving_ids)
    lost = claimed_total - surviving_total
    return max(0, min(surviving_total, claimed - lost))


def _awarded_from_verdicts(
    question: Question, point_verdicts: list[PointVerdict]
) -> _VerdictTotals:
    """I6 (US-013): ``awarded_marks`` computed in Python from the verdicts.

    Group-capped (spec 2026-09-26 §1): an either/or pair is worth its best
    member and an "any N from" pool its N largest tariffs, exactly as
    :func:`lemely.core.point_groups.group_points` records them for the
    ledger and as the self-review write path enforces them. The groups come
    from scheme order, so the result cannot depend on the order of the
    verdicts (I6 acceptance 1's metamorphic property still holds).

    Unresolved (dangling) point ids are excluded from the sum here -- the
    same dangling id is separately caught as a structural violation by
    ``_check_coherence`` on the returned ``matched_point_ids``.

    A repeated ``point_id`` is deduplicated first, via
    ``dedupe_point_verdicts`` (:mod:`lemely.core.schemas`) -- the same rule
    ``derive_point_rows`` (:mod:`lemely.db.question_points`) applies to the
    same list.

    Emits ``point_verdict_duplicate_dropped`` for each dropped duplicate.
    ``lemely.db.attempt_repo._warn_if_point_verdicts_were_deduplicated`` emits
    a second, differently-shaped record for the SAME duplicate one layer
    down, under the distinct name
    ``point_verdict_duplicate_dropped_at_persist`` -- when this function ran
    first (the normal path), that is a deliberate second record, not a bug;
    see that function's docstring for why both are kept.
    """
    kept, dropped = dedupe_point_verdicts(point_verdicts)
    if dropped:
        log = structlog.get_logger()
        for pv in dropped:
            log.warning(
                "point_verdict_duplicate_dropped",
                question_id=question.id,
                point_id=pv.point_id,
                verdict=pv.verdict,
            )
    matched_point_ids = [pv.point_id for pv in kept if pv.verdict == "awarded"]
    capped, additive = _group_capped_total(question, set(matched_point_ids))
    return _VerdictTotals(capped=capped, additive=additive, matched_point_ids=matched_point_ids)


#: I6 (US-013, D11): auto-added to feedback when a question earned full
#: marks but no awarded M-point carried a method-evidence span.
_NO_METHOD_SPAN_NOTE = (
    " [No method shown for full marks -- consider asking the student to show working.]"
)


def _maybe_add_no_method_span_note(
    question: Question, feedback: str, awarded: int, point_verdicts: list[PointVerdict]
) -> str:
    """D11: a feedback note is auto-added when a correct answer has no method span.

    Only fires when the question actually decomposes into at least one
    M-point (a question with no M-points has nothing to ask for).
    """
    if awarded != question.marks or not point_verdicts:
        return feedback
    points_by_id = {p.id: p for p in question.answer_points}
    m_points_exist = any(p.math_mark_type is MathMarkType.M for p in question.answer_points)
    if not m_points_exist:
        return feedback
    has_method_evidence = any(
        pv.verdict == "awarded"
        and (point := points_by_id.get(pv.point_id)) is not None
        and point.math_mark_type is MathMarkType.M
        and pv.evidence_span
        for pv in point_verdicts
    )
    if has_method_evidence:
        return feedback
    return feedback + _NO_METHOD_SPAN_NOTE


def _addresses_judgement(mark: AIMarkResponse) -> Literal["yes", "no", "unclear"] | None:
    """The marker's ``addresses_question``, or ``None`` when the reply left it out.

    ``AIMarkResponse`` defaults the field to ``"unclear"`` so a reply without
    it still parses, but an omitted field is not a judgement and must not be
    stored as one. ``model_fields_set`` holds only the fields the reply
    actually carried; it survives the cache (which stores the raw reply text
    and re-validates it) and ``model_copy``.
    """
    return mark.addresses_question if "addresses_question" in mark.model_fields_set else None


def _build_ai_corrected_from_verdicts(
    question: Question,
    student_answer: str,
    mark: AIMarkResponse,
    student_working: str | None,
    extraction_confidence: float | None,
) -> CorrectedQuestion:
    """I6 (US-013): the point-verdict marking path.

    Reached only from :func:`_build_ai_corrected` when ``equivalence_gate``
    is on AND the marker returned at least one ``PointVerdict`` -- see that
    function's docstring. ``awarded_marks`` is always computed from the
    verdicts (:func:`_awarded_from_verdicts`), never from
    ``mark.awarded_marks``.

    Six independent review reasons (the legacy path's four, minus the
    "marker reported an out-of-range number" check -- meaningless once the
    number is Python-computed and pre-capped -- plus the I6 span check and
    the post-``2deea2c5``-review coverage check below), with the SAME
    priority order the legacy path uses (structural reasons before
    confidence):

    1. ``matched_point_ids``/derived-total coherence (:func:`_check_coherence`,
       run against the DERIVED ``matched_point_ids`` and capped total).
    2. COVERAGE mismatch -- ``capped < question.marks`` (the verdicts do not
       account for the question's full marks) yet ``mark.awarded_marks``
       (the marker's OWN claimed total) is HIGHER than ``capped``. Critical
       fix, post-``2deea2c5``-review: that commit's dispatch guard added
       ``question.answer_points`` truthiness to route empty-``answer_points``
       questions (LEVELS_BASED, etc.) to the legacy body, but a question
       whose ``answer_points`` are simply an INCOMPLETE description of its
       marking (e.g. a ``DIAGRAM`` mixing a 2-mark ``AnswerPoint`` with a
       2-mark ``DrawingCriterion`` this path cannot resolve ids against) is
       non-empty and still dispatches here, silently under-capping. The
       narrower I6 prompt wording that commit also shipped (asking only for
       AnswerPoint ids, not the LevelDescriptor/DrawingCriteria ids the
       schema cannot support anyway) removed the ACCIDENTAL safety net: the
       OLD wording's dangling extra id used to trip
       :func:`_check_coherence`'s "unknown mark point id(s)" branch on
       exactly this shape. This check restores an equivalent signal
       deliberately, by comparing the DERIVED total against the marker's
       OWN claim -- the same philosophy the legacy path already uses
       (never trust the model's arithmetic, but DO notice when it disagrees
       with a structural computation) -- rather than re-litigating which
       question types can have incomplete ``answer_points``, so it protects
       any future under-coverage shape, not an enumerated list of types.
       Demonstrated on a constructed ``DIAGRAM`` fixture; the committed
       corpus has zero exposure today (11,024 leaves, all ``recall``/``mcq``,
       none carrying ``drawing_criteria``) -- an input-data limit, not a
       reason this can wait, per Critical A's own precedent: a latent trap
       fires first when money is spent.
    3. The deterministic calculated-answer backstop
       (:func:`_verify_calculated_answers`), unconditionally run with
       ``equivalence_gate=True`` here -- I8's equivalence fallback is
       already gated by the SAME flag this whole branch requires, so there
       is no independent "I8 without I6" state to preserve. Its subtracted
       total is discarded on this path; the mark is recomputed from the
       surviving ids by :func:`_group_capped_total` (triage F4).
    4. `no_span` / M-point-outside-``working_out`` (:func:`_check_point_evidence`),
       queued under the `low_confidence` bucket per that function's
       docstring -- no new enum member, no new trigger.
    5. ``mark.confidence < REVIEW_CONFIDENCE_THRESHOLD``.
    """
    totals = _awarded_from_verdicts(question, mark.point_verdicts)
    capped, matched_point_ids = totals.capped, totals.matched_point_ids
    _, scheme_groups = _scheme_groups(question)

    coherence_reason = _check_coherence(
        question,
        matched_point_ids,
        capped,
        point_verdicts=mark.point_verdicts,
        groups=scheme_groups,
    )
    coherence_mismatch = coherence_reason is not None

    coverage_reason: str | None = None
    if totals.additive < question.marks and mark.awarded_marks > totals.additive:
        coverage_reason = (
            f"verdict-derived total {totals.additive} is below the {question.marks}-mark "
            f"maximum but the marker's own claim ({mark.awarded_marks}) was higher -- "
            "this question's answer_points may not fully describe its marking scheme"
        )
    coverage_mismatch = coverage_reason is not None

    pre_verify_point_ids = set(matched_point_ids)
    _, matched_point_ids, rejections = _verify_calculated_answers(
        question,
        student_answer,
        student_working,
        matched_point_ids,
        capped,
        equivalence_gate=True,
    )
    value_mismatch = bool(rejections)
    # Triage F4: the backstop's own arithmetic subtracts a rejected point's
    # FULL tariff, which is right for the legacy path's additive total and
    # wrong here, where `capped` is already group-capped -- rejecting one
    # member of an either/or pair took the whole pair's mark away (probe:
    # awarded 0 where the surviving alternative alone earns 1). The total is
    # therefore recomputed from the SURVIVING ids with the same group rule
    # the marker's claim was capped with, never adjusted by subtraction. The
    # recomputation keeps the final `question.marks` clamp too: unstated pools
    # are each bounded by the full leftover (triage F5), so their caps can
    # sum past the question and only that clamp bounds the total.
    awarded, _ = _group_capped_total(question, set(matched_point_ids))

    # Post-I6-review: a point ``_verify_calculated_answers`` rejects above is
    # dropped from ``matched_point_ids`` (so it contributes no marks), but its
    # carried ``PointVerdict`` still says ``verdict="awarded"`` -- the
    # marker's raw, now-overruled claim -- which broke the
    # ``awarded == (verdict == "awarded")`` invariant and rendered the
    # review screen's strongest positive chip on a point that earned
    # nothing. Rejected ids are derived as a set difference against the
    # ids captured just above, not by parsing ``rejections`` (prose built
    # for a human, not for coupling this logic to). ``unverifiable`` is the
    # correct verdict -- the backstop could not confirm the value -- not
    # ``withheld``, which means the marker itself judged the point absent.
    # Only ``verdict`` changes: ``point_id``, ``evidence_span``, ``note``,
    # and (I7's CODE-set-only contract, Item A above) ``ecf_applied`` are
    # preserved verbatim via ``model_copy``.
    rejected_point_ids = pre_verify_point_ids - set(matched_point_ids)
    point_verdicts = (
        [
            pv.model_copy(update={"verdict": "unverifiable"})
            if pv.point_id in rejected_point_ids
            else pv
            for pv in mark.point_verdicts
        ]
        if rejected_point_ids
        else mark.point_verdicts
    )

    evidence_reason = _check_point_evidence(
        question, mark.point_verdicts, student_answer, student_working
    )
    no_span = evidence_reason is not None
    low_confidence = mark.confidence < REVIEW_CONFIDENCE_THRESHOLD or no_span

    reasons: list[str] = []
    if coherence_mismatch:
        reasons.append(coherence_reason or "")
    if coverage_mismatch:
        reasons.append(coverage_reason or "")
    if value_mismatch:
        reasons.append("unverified accuracy mark(s): " + "; ".join(rejections))
    if not reasons and low_confidence:
        if no_span:
            reasons.append(evidence_reason or "")
        else:
            reasons.append(
                f"confidence {mark.confidence:.2f} below review threshold "
                f"{REVIEW_CONFIDENCE_THRESHOLD:.2f}"
            )
    review_reason = " | ".join(reasons) if reasons else None

    feedback = _maybe_add_no_method_span_note(question, mark.feedback, awarded, mark.point_verdicts)

    return CorrectedQuestion(
        question_id=question.id,
        awarded_marks=awarded,
        maximum_marks=question.marks,
        confidence=confidence_band_for_score(mark.confidence),
        confidence_score=mark.confidence,
        needs_teacher_review=(
            low_confidence or value_mismatch or coherence_mismatch or coverage_mismatch
        ),
        review_reason=review_reason,
        student_answer=student_answer or None,
        expected_answer=None,
        topic=question.topic_hint,
        marker_source="ai",
        feedback=feedback,
        matched_point_ids=matched_point_ids,
        point_verdicts=point_verdicts,
        extraction_confidence=extraction_confidence,
        addresses_question=_addresses_judgement(mark),
    )


def _build_ai_corrected(
    question: Question,
    student_answer: str,
    mark: AIMarkResponse,
    student_working: str | None = None,
    extraction_confidence: float | None = None,
    *,
    equivalence_gate: bool = False,
) -> CorrectedQuestion:
    """Convert AIMarkResponse + question metadata into a CorrectedQuestion.

    ``equivalence_gate`` (US-005b, defaults False): forwarded to
    ``_verify_calculated_answers`` -- see its docstring. Never changes
    ``awarded_marks`` on its own in this story; a conflict only enriches the
    review reason for reason 3 below.

    I6 (US-013) DISPATCH -- reused ``equivalence_gate`` also decides whether
    this function runs the legacy body below at all: when the flag is on
    AND ``mark.point_verdicts`` is non-empty AND ``question.answer_points``
    is non-empty, this function returns
    :func:`_build_ai_corrected_from_verdicts`'s result instead, which
    computes ``awarded_marks`` from the verdicts rather than trusting
    ``mark.awarded_marks`` (see that function and
    ``AIMarkResponse.point_verdicts``'s docstrings for the full I6 review-
    reason set). With the flag off, with the flag on but an empty
    ``point_verdicts`` -- today's default and every existing point-based
    test's shape, since ``build_marker_user_prompt`` does not yet ask for
    them unless ``equivalence_gate`` is also passed through to it -- or with
    an empty ``question.answer_points``, everything below this dispatch is
    the legacy path, which trusts ``mark.awarded_marks`` and checks coherence
    against the same group-aware interval as the verdict path (#272).

    The ``question.answer_points`` guard (post-I6 review, Critical A) exists
    because :func:`_awarded_from_verdicts` and :func:`_check_point_evidence`
    resolve every verdict's ``point_id`` ONLY against ``question.answer_points``
    -- the wire prompt's I6 block used to (wrongly) ask the model for a
    verdict per ``LevelDescriptor``/``DrawingCriteria`` id too, but
    ``LevelDescriptor`` has no ``id`` field at all (``loose_schemas.py``) and
    ``question.answer_points`` is required to be EMPTY for
    ``QuestionType.LEVELS_BASED`` and typically empty for
    ``INDICATIVE_CONTENT``/diagram/``graph_draw`` questions judged
    holistically. Without this guard, every verdict for such a question
    resolves to nothing, ``_awarded_from_verdicts`` sums to 0, and
    ``LEVELS_BASED``/``INDICATIVE_CONTENT`` are BOTH in
    :data:`_COHERENCE_EXEMPT_TYPES` -- so the dangling-id coherence check
    that would otherwise catch this is switched off for exactly these types,
    and the zero reaches a student unflagged. Demonstrated on a constructed
    6-mark ``LEVELS_BASED`` question (6/6 -> 0/6, no review triggered) and a
    constructed ``INDICATIVE_CONTENT`` question (2/2 -> 0/2, no review
    triggered); the committed 289-scheme corpus contains zero questions of
    either type (it is entirely ``recall``/``mcq``, det-parsed), so no
    corpus regression was ever produced or possible -- this is a latent
    defect in code reachable only once Gemini-parsed schemes populate these
    types, not a measured corpus regression. Falling back to the legacy body
    (which never reads ``point_verdicts`` and is therefore identical whether
    ``equivalence_gate`` is True or False once ``answer_points`` is empty,
    since ``_verify_calculated_answers`` has nothing to iterate either) was
    chosen over resolving ids against ``level_descriptors``/
    ``drawing_criteria`` as well: ``LevelDescriptor`` has no id to resolve
    against, so a partial per-type extension would still leave levels-based
    marking broken while superficially "fixing" diagram/graph_draw -- see
    :func:`build_marker_user_prompt`'s matching fix to the I6 prompt block,
    which no longer asks the model for point_verdicts at all when
    ``question.answer_points`` is empty.

    This guard covers only the EMPTY case. ``INDICATIVE_CONTENT`` is NOT
    required by its own validator to have empty ``answer_points``
    (unlike ``LEVELS_BASED``), so a question that carries SOME
    ``answer_points`` summing to LESS than ``question.marks`` (e.g. a
    ``DIAGRAM`` mixing an ``AnswerPoint`` with a ``DrawingCriterion`` this
    path cannot resolve ids against) still dispatches to the verdicts path
    and would silently under-cap the same way, absent
    :func:`_build_ai_corrected_from_verdicts`'s own coverage-mismatch check
    (its docstring, reason 2) -- that check, not this guard, is what closes
    the adjacent gap.

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
       id, or a range mismatch on the grouped interval, #272) — see
       ``_check_coherence``. Also independent of
       confidence: a marker can be fully confident about an internally
       inconsistent result.
    """
    if equivalence_gate and mark.point_verdicts and question.answer_points:
        return _build_ai_corrected_from_verdicts(
            question, student_answer, mark, student_working, extraction_confidence
        )

    clamped = max(0, min(mark.awarded_marks, question.marks))
    out_of_range = mark.awarded_marks != clamped

    _, groups = _scheme_groups(question)
    coherence_reason = _check_coherence(
        question, list(mark.matched_point_ids), clamped, groups=groups
    )
    coherence_mismatch = coherence_reason is not None

    awarded, matched_point_ids, rejections = _verify_calculated_answers(
        question,
        student_answer,
        student_working,
        list(mark.matched_point_ids),
        clamped,
        equivalence_gate=equivalence_gate,
    )
    value_mismatch = bool(rejections)
    if value_mismatch:
        # Triage F4, legacy path: the backstop subtracted each rejected
        # point's FULL tariff from `clamped`, which a well-behaved marker has
        # already group-capped -- rejecting one member of an either/or pair
        # took the pair's mark (probe: 0 where the surviving member earns 1).
        awarded = _awarded_after_backstop(
            question, clamped, set(mark.matched_point_ids), set(matched_point_ids)
        )
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

    # NIT 7 (post-review, documented not fixed): this legacy return never
    # sets `point_verdicts`, so it defaults empty (`CorrectedQuestion`'s own
    # field default) regardless of whether `mark.point_verdicts` is
    # populated. Benign today -- every call that reaches this branch either
    # never asked for verdicts (`equivalence_gate` False) or asked but the
    # question's `answer_points` cannot support them (Critical A's empty-
    # answer_points fallback) -- but a model that disobeys either
    # instruction and returns verdicts anyway has them silently discarded
    # here, with no flag and no log line. Left as a documented limit rather
    # than plumbed through: this is the legacy body every non-I6 call uses,
    # and keeping verdicts out of it is what keeps the two dispatch branches
    # separable (see `_build_ai_corrected`'s own docstring). Both branches
    # now share the group-aware coherence interval (#272).
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
        extraction_confidence=extraction_confidence,
        addresses_question=_addresses_judgement(mark),
    )


def _build_missing_corrected(
    question: Question,
    student_answer: str | None,
    extraction_confidence: float | None = None,
) -> CorrectedQuestion:
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
        extraction_confidence=extraction_confidence,
    )


def _is_blank(value: str | None) -> bool:
    """True for ``None``, ``""``, and whitespace-only text.

    US-039: a whitespace-only answer (e.g. a stray newline the OCR box
    picked up) is treated as blank, not as text worth a paid marking call --
    there is no student judgement to evaluate in either case.
    """
    return value is None or value.strip() == ""


#: US-039 product-owner ruling: a blank non-MCQ answer becomes an UNFLAGGED
#: zero with NO paid call. Human-readable queue text for a teacher, and
#: deliberately distinct from every other blank-shaped message this module can
#: produce (``_build_mcq_corrected``'s "missing answer",
#: ``_build_missing_corrected``'s "--mcq-only or no AI client", and
#: ``_DROPPED_ANSWER_REVIEW_REASON``) -- but since task #36 nothing DERIVES
#: state from it: ``marker_source == "blank"`` is the signal. The distinctness
#: guard (``PairwiseDistinctBlankReasonsTests``) stays because a queue that
#: shows a teacher the wrong reason is still a defect.
_BLANK_ANSWER_REVIEW_REASON = "student left this question blank (0 awarded, no AI call made)"


def _build_blank_corrected(
    question: Question,
    extraction_confidence: float | None = None,
) -> CorrectedQuestion:
    """Short-circuit for a non-MCQ leaf the student left BLANK.

    US-039: before this function existed, ``correct_paper`` reached
    ``ai.mark_question(q, student_answer or "", ...)`` for a blank exactly as
    it did for real text -- a real, paid API call to mark an empty string,
    which could return a confident judgement (observed: HIGH confidence,
    0.97) tripping none of ``_build_ai_corrected``'s review gates. A student
    was then marked 0 on the strength of a model's opinion about nothing,
    with full confidence and no human ever told.

    The product owner's ruling (recorded on the story, not re-litigated
    here): the replacement is an UNFLAGGED zero with NO paid call. A flagged
    zero was rejected -- it would flag every genuine blank on every paper,
    turning a paper with 8 unattempted parts into 8 queue items a teacher
    dismisses on sight, training them to bulk-approve without looking.

    ``marker_source`` is ``"blank"``, its own fifth literal (task #36,
    migration ``0040_marker_source_blank``). It reused ``"missing"`` until
    then, with the blank-vs-not-marked distinction carried in
    ``review_reason`` prose — the same interim shape US-031 used for
    dropped-vs-missing before ``"dropped"`` had a member, and it failed the
    same way, only more expensively: a blank shares ``confidence_score=0.0``,
    ``ConfidenceBand.LOW`` and ``"missing"`` with a question a marker DID
    look at, so "did a marker score this?" was un-answerable from the columns
    and nine consumers had to be found by hand. Ask it through
    ``lemely.core.schemas.marker_scored`` now.

    ``review_reason`` keeps ``_BLANK_ANSWER_REVIEW_REASON``: it is what a
    teacher reads in the queue. Nothing PARSES it any more — the review-queue
    exemption is ``marker_source == "blank"``.

    Accepted residual risk, not solved here: a FALSE blank -- the student
    wrote something and extraction missed it entirely -- is awarded 0
    silently. That is an extraction defect, not a marking one; the narrower
    model-returned-then-discarded case is already covered by
    ``marker_source="dropped"``.

    Position note (why this is a separate function/branch from
    ``_build_missing_corrected``, not a parameter on it): callers must only
    reach this from ``correct_paper``'s leaf loop AFTER the MCQ branch and
    the ``ai is None`` branch, and BEFORE the AI marking call. Before the MCQ
    branch would change already-correct MCQ behaviour; before ``ai is None``
    would make ``--mcq-only``'s "we chose not to mark this" indistinguishable
    from "the student left it blank", which is the same class of conflation
    US-031's MUST-FIX 7 removed for dropped answers.
    """
    return CorrectedQuestion(
        question_id=question.id,
        awarded_marks=0,
        maximum_marks=question.marks,
        confidence=ConfidenceBand.LOW,
        confidence_score=0.0,
        needs_teacher_review=False,
        student_answer=None,
        expected_answer=None,
        topic=question.topic_hint,
        review_reason=_BLANK_ANSWER_REVIEW_REASON,
        marker_source="blank",
        extraction_confidence=extraction_confidence,
    )


#: US-031 review MUST-FIX 7 (stronger fix): distinct from
#: "AI marking failed: ..." (a live model/transport failure caught in
#: ``correct_paper``'s ``except Exception`` branch) and from "non-MCQ
#: question not marked (--mcq-only or no AI client)"
#: (:func:`_build_missing_corrected`, nothing was ever attempted). A dropped
#: answer means the model DID respond for this question and the response
#: was discarded before marking was ever attempted, because extraction
#: could not make sense of it -- conflating any of the three into one
#: message would make the review queue less informative about what
#: actually happened, which is the same defect class the review flagged in
#: the "AI marking failed" string this must not reuse.
_DROPPED_ANSWER_REVIEW_REASON = (
    "extraction dropped this answer as malformed (see ExtractedAnswers.answer_drops)"
)


#: The reason for a question in ``ExtractedAnswers.unbound_question_ids``: the
#: label binder could bind no answer to it. Distinct from
#: ``_DROPPED_ANSWER_REVIEW_REASON``, which would be false here: nothing was
#: discarded as malformed. It names both ways a scan leaves a leaf unbound: its
#: label was not seen, or the label was seen and the writing by it could not be
#: given to it (it may be a neighbour's, or its page or text could not be read).
#: It is the general sentence; ``UNBOUND_REASON_SENTENCES`` holds the ones for
#: causes it would be false for.
UNBOUND_QUESTION_REVIEW_REASON = (
    "binding unverified: this question's label was not found on the scan, or the writing "
    "by it could not be tied to it, so its answer could not be read"
)


#: A truer sentence for the causes the general one above is false for, keyed by the
#: reason the extraction carries in ``ExtractedAnswers.unbound_question_reasons``.
#: Each starts with ``binding unverified:`` (``lemely.core.binding_review`` keys on
#: that prefix) and none holds ``" | "``, which joins reasons.
UNBOUND_REASON_SENTENCES: dict[str, str] = {
    # The mark scheme's fault, not the scan's.
    "duplicate_id": (
        "binding unverified: the mark scheme lists this question twice, so its answer "
        "could not be matched to it"
    ),
    "undecomposable_id": (
        "binding unverified: the mark scheme names this question in a way no label on a "
        "script can match, so its answer could not be matched to it"
    ),
    # Nothing of the script was bound at all.
    "list_too_long": (
        "binding unverified: the script could not be read against this mark scheme, so "
        "no answer could be matched to this question"
    ),
    "scheme_too_deep": (
        "binding unverified: the script could not be read against this mark scheme, so "
        "no answer could be matched to this question"
    ),
    # Sent to review by comparing two reads, or by the order of the list. The label
    # was found in each of these.
    "answered_in_one_read_only": (
        "binding unverified: writing was found for this question in only one of two "
        "readings of the scan, so its answer was not used"
    ),
    "listing_suspect": (
        "binding unverified: the answers around this question were listed out of order, "
        "so the writing for it could not be told from the next part's"
    ),
    "unaligned_in_other_read": (
        "binding unverified: one reading of the scan found nothing written for this "
        "question and the other could not place its label, so it is not known to be blank"
    ),
}


def _unbound_reason_sentence(why: str | None) -> str:
    """The review reason for an unbound question whose cause is ``why``.

    The general sentence is true for every reason not listed above: those are a label
    that was not found, or one that was found with writing that could not be tied to
    it. It is also what an id with no recorded cause gets.
    """
    return UNBOUND_REASON_SENTENCES.get(why or "", UNBOUND_QUESTION_REVIEW_REASON)


def _unbound_question_ids(extracted: ExtractedAnswers | Mapping[str, str]) -> frozenset[str]:
    """Question ids the label binder could bind no answer to.

    Only an ``ExtractedAnswers`` can carry them: a plain mapping of typed answers
    was never bound from a scan.
    """
    if isinstance(extracted, ExtractedAnswers):
        return frozenset(extracted.unbound_question_ids)
    return frozenset()


def _build_dropped_corrected(
    question: Question, reason: str = _DROPPED_ANSWER_REVIEW_REASON
) -> CorrectedQuestion:
    """Short-circuit for an answer extracted but DROPPED as malformed.

    Also used, with ``reason=UNBOUND_QUESTION_REVIEW_REASON``, for a question the
    label binder could bind no answer to: the same zero, the same flag, no marking
    call, and its own true reason.

    US-031 review MUST-FIX 7, stronger fix. No marking call is made --
    ``correct_paper`` never reaches ``ai.mark_question`` for this question
    at all. Before this function existed, a dropped answer looked to
    ``correct_paper`` identically to "no answer for this question"
    (``student_answer=None``): for an MCQ leaf
    that already flagged for review (``_build_mcq_corrected``'s "missing
    answer" branch, safe by accident); for a non-MCQ leaf, the AI marker was
    asked to mark ``student_answer or ""`` -- a real, paid API call to mark
    an empty string the extractor itself had already discarded -- and could
    return a confident judgement (e.g. "blank, 0 marks", high confidence)
    that tripped none of ``_build_ai_corrected``'s four review gates. A
    student would then be marked wrong because the model's JSON was
    malformed, with no human ever told. For every question that reaches this
    function that path is gone: the mark is 0, it is unconditionally flagged
    for review with a reason distinct from both a genuine student blank and a
    real marking failure, and no spend is wasted marking text extraction
    already knew was unusable.

    COVERAGE LIMIT (review MUST-FIX F1) -- which questions reach it is the
    limit. Only an id in ``ExtractedAnswers.dropped_question_ids`` with no
    surviving entry in ``answers`` does (spec 2026-09-26 §2 (#4): a dropped
    ENTRY is not a verdict on the question when another, well-formed entry
    for the same id survived), and only two of extraction's five drop
    reasons put an id there in the first place: ``missing_answer`` and
    ``malformed_answer``. ``missing_question_id``,
    ``malformed_question_id`` and ``malformed_answer_shape`` (the MF6 case --
    one unusable element in the ``answers`` list) leave no id to attribute the
    flag to, so those three never arrive here and keep the pre-MF7 behaviour
    of their leaf type: on a non-MCQ leaf with an AI marker configured, the
    paid call is still made and ``_build_ai_corrected`` can still return a
    confident, unflagged zero; on an MCQ leaf, or under ``--mcq-only``/no AI
    client, the question is already flagged at 0.0 with no call, but only
    because ``student_answer=None`` is indistinguishable from a blank -- so
    ``review_reason`` carries that path's blank message ("missing answer", or
    "non-MCQ question not marked (--mcq-only or no AI client)") rather than
    what actually happened. See
    ``CorrectedQuestion.marker_source``'s coverage-limit note.
    """
    return CorrectedQuestion(
        question_id=question.id,
        awarded_marks=0,
        maximum_marks=question.marks,
        confidence=ConfidenceBand.LOW,
        confidence_score=0.0,
        needs_teacher_review=True,
        student_answer=None,
        expected_answer=None,
        topic=question.topic_hint,
        review_reason=reason,
        marker_source="dropped",
        extraction_confidence=None,
    )


#: I7 (US-013) GATE. Measured on all 289 committed mark schemes: 26 points
#: (0.25% of 10,314) in 10 schemes carry this marker, as unstructured prose
#: on the point itself or its question's notes/marking_guidance -- e.g.
#: "R = 4.05 / ecf, 3.89, 3.81" and "Strict FT their median reading".
#: Deliberately NOT widened to "any A point with a resolvable M chain" --
#: that would apply ECF where CAIE never marked the point ECF-eligible, and
#: award marks nobody earned. Under-firing (this) is the safe direction;
#: over-firing is a correctness defect.
#:
#: Post-I7-review fix: ``FT`` is matched CASE-SENSITIVELY, unlike ``ecf``/
#: ``dep`` -- the original case-insensitive `\bft\b` also matched
#: `0625_s23_ms_42` q2b/p2's `"Ft = ∆mv OR F = ma OR ..."`, where `Ft` is
#: impulse (force x time), a physics formula with no connection to
#: follow-through. Every genuine follow-through marker in the corpus is
#: written uppercase ("Strict FT", "FT their median reading"), so
#: restricting `FT` to that case drops exactly the one false positive (29
#: -> 28 points, 11 -> 10 schemes) and no genuine hit -- re-measured against
#: the full corpus, not assumed. The over-award scenario this closes is
#: CONDITIONAL, not already live: `0625_s23_ms_42`'s q2 top-level group
#: carries A/C-typed points (`2a`: p1=A, p2=C, p3=C) but no M point
#: anywhere in it today, so `_resolve_ecf_chain` returns `None` for every
#: point in the group and there is nothing to substitute against yet. A
#: single M point ADDED LATER (e.g. by a Gemini re-parse) would give this
#: exact group a resolvable chain, and a point CAIE never marked
#: ECF-eligible would then receive a substituted value and an award --
#: the mis-gate and a chain must BOTH be present, and only the mis-gate
#: was, which this fix closes regardless.
#:
#: Post-whole-branch-review fix: ``dep`` is EXCLUDED from this pattern.
#: In CAIE mark-scheme notation ``dep`` means "Dependent" -- the mark can
#: only be awarded when a stated prerequisite mark is ALSO awarded --
#: while ``FT``/``ecf`` mean "Follow-through after error" / "Error carried
#: forward". I7's re-mark fires only when the prerequisite was NOT
#: awarded, which is exactly the situation in which a dependent mark must
#: be WITHHELD, not carried forward -- the old pattern gated these marks
#: into the one behaviour CAIE says they must never get, an over-award
#: direction. Measured: 2 of the 28 gate hits (both in
#: `0606_s22_ms_23`, leaf 10/p8 and 11a/p3) were dep-only; dropping the
#: token narrows the gate population to 26 points / 10 schemes (see
#: :func:`_maybe_apply_ecf_substitution`'s activation-ceiling docstring
#: and ``_run_ai_marking``'s ``ecf_substitution`` note, both updated to
#: match). Inert on the committed det-parsed corpus today (the gate/chain
#: intersection is still 0 either way), but not inert in general: Gemini
#: -parsed schemes are unconstrained in marker vocabulary and could
#: produce a live dep+chain co-occurrence this excludes.
_ECF_MARKER_RE = re.compile(r"(?i:\becf\b)|\bFT\b")


def _ecf_gated(question: Question, point: AnswerPoint) -> bool:
    """I7 GATE -- may ``point`` ever be re-marked with a substituted prior value?

    True only when an ecf/ft marker appears on the point's own ``point``
    text or ``condition``, or on its (leaf) question's ``notes`` or
    ``marking_guidance`` -- deliberately excluding ``dep`` (Dependent),
    which is the opposite marking behaviour to ECF. See
    :data:`_ECF_MARKER_RE`'s docstring for the measured activation ceiling
    and why this is not widened.
    """
    texts = (point.point, point.condition, question.notes, question.marking_guidance)
    return any(_ECF_MARKER_RE.search(t) for t in texts if t)


def _resolve_ecf_chain(
    question: Question, point: AnswerPoint, top_level_leaves: list[Question]
) -> tuple[str, str] | None:
    """I7 CHAIN resolver -- which prior point's value gets substituted for ``point``.

    Two tiers, in order (measured on the 289-scheme corpus, walking
    ``parts`` recursively -- an earlier probe that walked a non-existent
    ``sub_questions`` key silently visited only top-level questions and
    understated every denominator by 5.8x): ``required_with`` itself is
    non-null in 0 of **10,314** corpus points today, a Gemini-path-only
    field on this det-parsed corpus, so tier 1 is correct-but-dormant and
    tier 2 is the one that actually fires, resolving 820 SAME-LEAF chains
    and 438 CROSS-LEAF ones. Both tiers are reported here as STRUCTURAL
    facts only -- whether a same-leaf result is USABLE for substitution is
    a separate policy decision :func:`_maybe_apply_ecf_substitution` makes,
    not this function's job (see its own docstring's Critical 2 note: a
    same-leaf M-then-A pair is one computation's method and accuracy
    marks, not an error carried FORWARD between two parts, so that
    majority of chains this resolver reports is never actually
    substituted on).

    1. ``point.required_with``, if set, resolved ONLY against ``question``'s
       OWN ``answer_points`` -- point ids are question-scoped by design
       (``loose_schemas.py:202``, "Sequential ID within the question"), so a
       bare id can never name a point in a different question, and this
       tier can therefore only ever return a SAME-LEAF result. A dangling
       ``required_with`` (no such sibling) resolves to no prerequisite,
       never a paper-wide search.
    2. Otherwise, the nearest preceding ``math_mark_type == M`` point within
       the SAME top-level question, walking parts in document order --
       first backwards through ``question``'s own earlier points (SAME-LEAF
       result), then backwards through ``top_level_leaves`` (every leaf
       under the same top-level ancestor, in document order, as this
       story's own ``correct_paper`` grouping presents it -- a CROSS-LEAF
       result). This is the parsing prompt's own rule 9
       (``io/prompts/mark_scheme_parsing.py:338``), computed here rather
       than re-derived from scratch.

    Returns ``(prerequisite_leaf_question_id, prerequisite_point_id)``, or
    ``None`` when neither tier resolves.
    """
    if point.required_with is not None:
        if any(sibling.id == point.required_with for sibling in question.answer_points):
            return question.id, point.required_with
        return None  # dangling required_with -- no paper-wide fallback

    try:
        point_index = next(i for i, p in enumerate(question.answer_points) if p.id == point.id)
    except StopIteration:
        return None

    for sibling in reversed(question.answer_points[:point_index]):
        if sibling.math_mark_type is MathMarkType.M:
            return question.id, sibling.id

    try:
        leaf_index = next(i for i, leaf in enumerate(top_level_leaves) if leaf.id == question.id)
    except StopIteration:
        return None

    for leaf in reversed(top_level_leaves[:leaf_index]):
        for sibling in reversed(leaf.answer_points):
            if sibling.math_mark_type is MathMarkType.M:
                return leaf.id, sibling.id

    return None


def _top_level_ancestor_id(question_id: str, all_by_id: dict[str, Question]) -> str:
    """Walk ``parent_id`` up to the root and return that root's id."""
    q = all_by_id[question_id]
    seen = {q.id}
    while q.parent_id is not None and q.parent_id in all_by_id:
        q = all_by_id[q.parent_id]
        if q.id in seen:  # defensive only -- a well-formed scheme cannot cycle
            break
        seen.add(q.id)
    return q.id


def _group_leaves_by_top_level(
    leaves: list[Question], all_by_id: dict[str, Question]
) -> dict[str, list[Question]]:
    """Group marked leaves by their top-level ancestor id.

    Preserves the document order ``leaves`` already carries --
    :func:`_resolve_ecf_chain` walks each group backwards to find the
    nearest preceding M point.
    """
    groups: dict[str, list[Question]] = {}
    for leaf in leaves:
        tid = _top_level_ancestor_id(leaf.id, all_by_id)
        groups.setdefault(tid, []).append(leaf)
    return groups


def _point_was_awarded(
    leaf_id: str,
    point_id: str,
    corrected_by_id: dict[str, CorrectedQuestion],
) -> bool:
    """Was ``point_id`` (owned by the EARLIER leaf ``leaf_id``) already awarded?

    Post-Critical-2-review NIT fix: this used to also handle
    ``leaf_id == the CURRENT leaf under test`` (``required_with``, or a
    preceding M point earlier in the SAME leaf, before Critical 2 excluded
    the same-leaf case from substitution entirely). That branch was DEAD:
    its only caller (:func:`_maybe_apply_ecf_substitution`) already filters
    out ``prereq_leaf_id == question.id`` before ever calling this
    function, so ``leaf_id`` can never equal the leaf under test here --
    the removed branch asserted a scenario the caller had already ruled
    out. Simplified to what actually happens: ``leaf_id`` is always a leaf
    STRICTLY EARLIER, in document order, than the one being marked, and is
    therefore already present in ``corrected_by_id`` by construction --
    ``correct_paper`` processes leaves in the same document order
    :func:`_resolve_ecf_chain`'s cross-leaf tier walks backwards through.
    """
    prior_cq = corrected_by_id.get(leaf_id)
    return prior_cq is not None and point_id in prior_cq.matched_point_ids


def _maybe_apply_ecf_substitution(
    question: Question,
    cq: CorrectedQuestion,
    mark: AIMarkResponse,
    student_answer: str,
    student_working: str | None,
    extraction_confidence: float | None,
    *,
    ai: AICorrector,
    ecf_substitution: bool,
    equivalence_gate: bool,
    principles: list[str] | None,
    sibling_prior: dict[str, int] | None,
    answers: dict[str, _FlatAnswer],
    top_level_leaves: list[Question],
    corrected_by_id: dict[str, CorrectedQuestion],
    log: structlog.BoundLogger,
) -> CorrectedQuestion:
    """I7 (US-013) ORDER: try without substitution first.

    ``cq``/``mark`` were already marked by the caller with no substitution;
    only re-mark when a part is BELOW MAX *and* GATED *and* has a resolvable
    CROSS-LEAF CHAIN whose prerequisite was itself NOT already correct
    (there is no error to carry forward otherwise -- this is what makes a
    correct prerequisite never trigger a second call).

    Post-I7-review Critical 2 fix (a design error in the original brief, not
    the implementation): a chain that resolves to a point in the SAME leaf
    as ``question`` is EXCLUDED here, deliberately, even though
    :func:`_resolve_ecf_chain` still reports it. A same-leaf M/A pair (or a
    ``required_with`` reference, which by construction can only ever name a
    sibling in the SAME leaf -- point ids are question-scoped) is one
    computation's method and accuracy marks, not two separate parts with an
    error carried FORWARD between them -- there is nothing to substitute.

    Measured on the full corpus: 820 same-leaf chains exist as a
    STRUCTURAL matter, against 438 cross-leaf ones. This is NOT the same
    as saying the unfixed code would have substituted on 820 points --
    substitution additionally requires the GATE, and on this corpus the
    gate (26 points) and ANY chain, same-leaf or cross-leaf, never
    co-occur (measured: gate-and-chain intersection is 0 in both
    buckets). So the unfixed code would have substituted on ZERO corpus
    points, not 820 -- the exclusion is correct on PRINCIPLE (nothing is
    carried forward inside one computation) and is NOT load-bearing on
    this corpus; a reader sizing a revert of this fix should know it would
    change nothing here, while a reader deciding whether the rule is
    necessary should still take it, because Gemini-parsed schemes are
    where a genuine same-leaf/cross-leaf distinction and a co-occurring
    gate can both appear. See ``ECFSubstitutionTests::
    test_same_leaf_chain_never_triggers_substitution`` for the regression
    test (a constructed fixture, since the corpus itself cannot exercise
    this path).

    Honest limit, stated here rather than implied: recomputation is BY THE
    MODEL with the substituted value (plus I8's separate numeric check),
    never a literal (e.g. Numbas-style) recompute -- mark schemes carry no
    machine-readable formula to recompute against.

    No-op (returns ``cq`` unchanged, no second Gemini call) whenever:
    - ``ecf_substitution`` is off (flag-off byte-identical inertness);
    - ``equivalence_gate`` is off -- post-I7-review fix A: ``point_verdicts``
      is NOT in the wire schema's ``required`` list, so a model MAY
      volunteer it even when the I6 prompt block was never appended (i.e.
      ``equivalence_gate`` False). Gating on ``mark.point_verdicts`` alone
      let ``ecf_substitution=True, equivalence_gate=False`` spend a second,
      billed marking call per eligible question -- with its result
      discarded, since ``_build_ai_corrected`` only ever consumes verdicts
      when ``equivalence_gate`` is also True -- a silent cost regression
      against the USD ceiling that contradicted this module's own claim of
      inertness. This explicit check is the fix, not a cosmetic guard;
    - ``cq`` is already at ``maximum_marks``;
    - ``mark.point_verdicts`` is empty;
    - no answer_point is simultaneously below-max, gated, CROSS-LEAF
      chain-resolvable, not already awarded, and backed by a non-blank
      prerequisite answer.

    Measured activation ceiling on the 289-scheme committed corpus, as
    THREE separate numbers rather than one -- publishing a single figure
    (this story's own earlier ``29 points, 11 schemes`` was wrong in
    exactly this way) invites reading a true zero as a regression:
    GATE population 26 points / 10 schemes (:data:`_ECF_MARKER_RE`);
    genuine CROSS-LEAF chain population 438; their INTERSECTION -- the
    actual number of points I7 can activate on -- **0**. The gated
    population and the M/A/B/C-typed population are disjoint on this
    det-parsed corpus: not one of the 26 gated points has a preceding
    typed point in a different leaf. I7 is therefore provably inert on the
    committed corpus BY CONSTRUCTION, not merely rare -- the feature
    targets Gemini-parsed schemes, where ``required_with`` is populated and
    real cross-part chains exist, which this corpus is not. The synthetic
    tests in ``tests/test_correction_ai.py`` are the ONLY evidence this
    path behaves as designed; the corpus provides none.
    """
    if (
        not ecf_substitution
        or not equivalence_gate
        or cq.awarded_marks >= cq.maximum_marks
        or not mark.point_verdicts
    ):
        return cq

    current_matched = set(cq.matched_point_ids)
    eligible: list[tuple[AnswerPoint, str, str]] = []
    for point in question.answer_points:
        if point.id in current_matched:
            continue
        if not _ecf_gated(question, point):
            continue
        prereq = _resolve_ecf_chain(question, point, top_level_leaves)
        if prereq is None:
            continue
        prereq_leaf_id, prereq_point_id = prereq
        if prereq_leaf_id == question.id:
            continue  # same-leaf: nothing to carry FORWARD within one computation
        if _point_was_awarded(prereq_leaf_id, prereq_point_id, corrected_by_id):
            continue  # prerequisite was already correct -- nothing to carry forward
        prereq_answer = answers.get(prereq_leaf_id)
        if not prereq_answer or _is_blank(prereq_answer.answer):
            continue
        eligible.append((point, prereq_leaf_id, prereq_point_id))

    if not eligible:
        return cq

    # Post-I7-review fix D, and the SHOULD-FIX that followed Critical 2's
    # review: include the prerequisite's WORKING alongside its answer (an
    # ECF-relevant intermediate value can live in working_out rather than
    # the final answer line, and the old code dropped it entirely), AND
    # the prerequisite POINT's own scheme text, so the model knows WHICH of
    # the leaf's numbers is being carried forward -- without it, a leaf
    # extracting as e.g. "v = 18, a = 150" gives the model two numbers and
    # no way to tell which one the gated point actually depends on.
    #
    # DECLINED (not merely undocumented): true per-POINT VALUE granularity
    # -- substituting only the specific number the prerequisite point
    # produced, rather than the prerequisite leaf's whole answer -- is not
    # achievable with today's extraction. `answers` is `dict[str, _FlatAnswer]`,
    # keyed by LEAF question id; extraction never resolves a value below one question's
    # answer/working as a whole, so there is no per-point value to look up
    # in the first place, regardless of how this function is written. That
    # is a limit of what extraction records, not a documentation choice.
    def _prior_value_text(leaf_id: str, point_ids: list[str]) -> str:
        # Post-review fix: rendered as separate labelled LINES ("answer:",
        # "working:", "depends on:"), never packed onto one line -- the
        # prompt-building side used to wrap this in `{value!r}`, which
        # turned a real line break into a literal `\n` escape sequence the
        # model could not use as one, and a naive unescaped join would
        # instead put a continuation line at column 0 with nothing marking
        # which entry it belongs to. `build_marker_user_prompt` indents
        # every line of the returned string under its own `qid:` header,
        # so labelled lines here are what keeps a multi-field value
        # unambiguous once indented. `answer` is typed ``str`` in
        # `answers` (never ``None``), so no `or ""` fallback is needed for
        # it.
        flat = answers[leaf_id]
        answer, working = flat.answer, flat.working_out
        lines = [f"answer: {answer}"]
        if working and working.strip():
            lines.append(f"working: {working.strip()}")
        scheme_texts = [
            sibling.point
            for leaf in top_level_leaves
            if leaf.id == leaf_id
            for sibling in leaf.answer_points
            if sibling.id in point_ids
        ]
        if scheme_texts:
            lines.append(f"depends on: {'; '.join(dict.fromkeys(scheme_texts))}")
        return "\n".join(lines)

    prereq_point_ids_by_leaf: dict[str, list[str]] = {}
    for _, prereq_leaf_id, prereq_point_id in eligible:
        prereq_point_ids_by_leaf.setdefault(prereq_leaf_id, []).append(prereq_point_id)
    prior_values = {
        leaf_id: _prior_value_text(leaf_id, point_ids)
        for leaf_id, point_ids in prereq_point_ids_by_leaf.items()
    }
    try:
        mark2 = ai.mark_question(
            question,
            student_answer,
            student_working,
            prior_results=sibling_prior,
            principles=principles,
            equivalence_gate=equivalence_gate,
            prior_values=prior_values,
        )
    except CostCeilingError:
        raise
    except LemelyError as exc:
        # Post-review NIT fix: was `except Exception`, which also caught
        # (and silently masked as "the API call failed") any PROGRAMMING
        # bug in the code above -- e.g. a `StopIteration` from a test's own
        # mock exhausting its `side_effect` list proved nothing under the
        # old bare catch, since it looked identical to a real transport
        # failure. `ai.mark_question`'s genuine failure modes are
        # `LemelyError` subclasses (`ExternalServiceError` for transport,
        # `ParseError` for a malformed response `GeminiClient` could not
        # parse into `AIMarkResponse`) -- `CostCeilingError` is also one,
        # already re-raised above. Anything outside that hierarchy now
        # propagates instead of being swallowed. Deliberately narrower than
        # `correct_paper`'s own pre-existing `except Exception` (a separate,
        # documented decision on a different call site, out of this
        # story's scope).
        log.warning("ecf_substitution_remark_failed", question_id=question.id, error=str(exc))
        return cq

    eligible_ids = {p.id for p, _, _ in eligible}
    mark2_by_id = {pv.point_id: pv for pv in mark2.point_verdicts}
    merged_verdicts: list[PointVerdict] = []
    changed = False
    for pv in mark.point_verdicts:
        replacement = mark2_by_id.get(pv.point_id) if pv.point_id in eligible_ids else None
        if replacement is not None and replacement.verdict == "awarded":
            merged_verdicts.append(replacement.model_copy(update={"ecf_applied": True}))
            changed = True
        else:
            merged_verdicts.append(pv)
    if not changed:
        return cq

    # Post-I7-review Critical 1 fix: the re-mark's OWN confidence/feedback
    # must replace the first pass's, not the other way round.
    # `_build_ai_corrected_from_verdicts` evaluates
    # `mark.confidence < REVIEW_CONFIDENCE_THRESHOLD` -- if `merged_mark`
    # kept the first pass's (often HIGH) confidence, an ECF re-mark the
    # model itself was UNSURE about would ship unflagged, carrying feedback
    # that describes the first pass's rejection rather than the award that
    # actually happened. ECF awards are precisely the marks most in need of
    # a human look; `min()` -- not the re-mark's confidence alone -- so a
    # confident first pass can never mask genuine uncertainty in the
    # re-mark, and a confident re-mark can never override genuine
    # uncertainty already flagged by the first pass.
    # Post-Critical-1-review Critical fix: `feedback=mark2.feedback` above
    # is unconditional, but `point_verdicts` is merged SELECTIVELY (only
    # `eligible_ids` are replaced with pass 2's verdict). Pass 2 is a full
    # re-mark of the WHOLE question, not just the eligible point(s) -- so
    # its feedback can describe crediting a point that was NOT eligible
    # (e.g. an ungated point pass 2 also happened to award), while that
    # point's verdict is correctly discarded from `merged_verdicts`. Without
    # `awarded_marks` also carrying pass 2's claim, `merged_mark.awarded_marks`
    # stayed at pass 1's stale value, which meant
    # `_build_ai_corrected_from_verdicts`'s coverage-mismatch check (this
    # function's docstring, reason 2) could never disagree with it either --
    # not because this fix broke that check (the two landed as a MERGE-ORDER
    # collision: the coverage check did not exist when this bug was
    # introduced, and only arrived with a later commit), but because a
    # stale claim can never disagree with anything by construction.
    # Propagating `mark2.awarded_marks` here makes `merged_mark` internally
    # consistent and lets that check do the catching, rather than adding a
    # second, parallel check.
    merged_mark = mark.model_copy(
        update={
            "point_verdicts": merged_verdicts,
            "confidence": min(mark.confidence, mark2.confidence),
            "feedback": mark2.feedback,
            "awarded_marks": mark2.awarded_marks,
        }
    )
    # G8: the re-mark's feedback and claimed marks are the ones kept above, so
    # its judgement of whether the answer addresses the question is kept with
    # them rather than the first pass's. Set on the built row, not through
    # `merged_mark`: a `model_copy` update would mark the field as set even
    # when the re-mark left it out, turning "no judgement" into "unclear".
    return _build_ai_corrected(
        question,
        student_answer,
        merged_mark,
        student_working,
        extraction_confidence,
        equivalence_gate=equivalence_gate,
    ).model_copy(update={"addresses_question": _addresses_judgement(mark2)})


def _attach_extraction_context(
    cq: CorrectedQuestion,
    answers: dict[str, _FlatAnswer],
    original: dict[str, _FlatAnswer],
    options: MarkingOptions,
    leaf_by_id: dict[str, Question],
) -> CorrectedQuestion:
    """The ONE place the finished row learns what extraction knew about it.

    E (2026-09-24): the extraction bounding box, deep-copied because pydantic
    keeps an already-validated nested model by reference and a shared
    instance would let one holder's mutation corrupt every other holder's
    copy. Spec 2026-09-26 §4 (#9): a crop re-read that disagreed with the
    first read sends an ``ai`` or ``deterministic`` row to teacher review,
    joined onto any reason the builder already gave -- whether or not
    ``reread_substitution`` marked the re-read text, because substitution
    must never hide a disagreement from the teacher. The reason quotes the
    text substitution actually used (fix round 1: :func:`_substituted_answer`
    re-run against ``original``, not the raw ``answer_reread``), so
    ``student_answer`` and the reason always agree. Fix round 2: on an MCQ
    leaf, a re-read that :func:`_mcq_agrees` with the first read once
    normalised is never a disagreement, so "A." vs "A" gives no flag and no
    substitution -- see :func:`_disagreeing_agreement`.

    Fix round 1 ADDED, fix round 2 REVERTED: flagging a ``blank`` row
    whose re-read found non-blank text. Reviewer-reproduced exploit: a
    flagged ``blank`` row makes ``low_confidence_review_needed``
    (``review_queue_rules.py``) return True, which makes
    ``is_marking_low_confidence`` True, and ``self_review.decide_point``
    then GRANTS any challenged point on that row with NO evidence. The
    re-read text comes from the MODEL, not the student -- it is Gemini's
    own second look at the crop, not anything the student supplied -- so
    the risk is not a student writing a fake re-read: it is that ANY
    non-blank re-read on a genuinely blank first read, including one the
    model simply hallucinated over blank pixels, would grant self-mark
    authority on a question the student left blank, with the student never
    having entered anything a human could point to as evidence. Known gap,
    deliberately left open: the proper fix belongs in the self-review
    authority gate itself (deciding what counts as evidence for a GRANT),
    not here in correction, which has no way to tell a genuine recovered
    answer from a hallucinated one. A blank row is left untouched, like
    every dropped/missing row: no answer was read for it.
    """
    if cq.question_id not in answers:
        return cq
    flat = answers[cq.question_id]
    first = original[cq.question_id]
    leaf = leaf_by_id.get(cq.question_id)
    is_mcq = leaf is not None and leaf.type == QuestionType.MCQ
    update: dict[str, object] = {
        "source_box": flat.source_box.model_copy(deep=True) if flat.source_box is not None else None
    }
    agreement = _disagreeing_agreement(first, is_mcq=is_mcq)
    if cq.marker_source in ("ai", "deterministic") and agreement is not None:
        reread_for_reason: str | None
        # Final review I2: a blank first read is never substituted (see
        # :func:`_substituted_answer`), so its reason is the flag-off shape
        # quoting both readings, not "the re-read returned nothing usable".
        substitution = options.reread_substitution and not _is_blank(first.answer)
        if substitution:
            substituted = _substituted_answer(first, is_mcq=is_mcq)
            reread_for_reason = substituted if substituted is not None else ""
        else:
            reread_for_reason = first.answer_reread
        reason = _reread_reason(
            first_read=first.answer,
            reread=reread_for_reason,
            agreement=agreement,
            substitution=substitution,
        )
        update["needs_teacher_review"] = True
        update["review_reason"] = _join_reason(cq.review_reason, reason)
    return cq.model_copy(update=update)


#: Appended to ``review_reason`` on each question a question-scope G8 failure
#: names (see :func:`_with_off_topic_check`).
OFF_TOPIC_REVIEW_REASON = "binding unverified: answer appears to address a different question"

#: Appended to ``review_reason`` on each question whose answer the binding left
#: ``binding_status="unverified"``, with or without a binding report on the
#: extraction (see :func:`_with_off_topic_check`): the binder
#: bound it but doubts what it holds (writing tied by an arrow, carried over from
#: the page before, or beside a label that was not seen), or a question-scope
#: gate check named it.
UNVERIFIED_BINDING_REVIEW_REASON = (
    "binding unverified: this answer may include writing that belongs to another question"
)

_VERDICT_SEVERITY: dict[BindingVerdict, int] = {"pass": 0, "retry": 1, "hold": 2}


def _sent_to_review(
    questions: list[CorrectedQuestion], ids: set[str], reason: str
) -> list[CorrectedQuestion]:
    """``questions`` with those in ``ids`` flagged for a teacher, ``reason`` joined on."""
    return [
        cq.model_copy(
            update={
                "needs_teacher_review": True,
                "review_reason": _join_reason(cq.review_reason, reason),
            }
        )
        if cq.question_id in ids
        else cq
        for cq in questions
    ]


def _with_off_topic_check(
    result: CorrectionResult, extracted_answers: ExtractedAnswers | Mapping[str, str]
) -> CorrectionResult:
    """Run check G8 over the marked paper and attach the binding report.

    G8 (:func:`lemely.core.binding_gate.check_off_topic`) counts the answers
    the MARKER judged not to address their question -- the one binding check
    that can only run after marking, and the main one for prose answers,
    which the checks run at extraction cannot see. ``result.questions`` is in
    mark-scheme order (``correct_paper`` builds it by walking ``leaves``),
    which is the order a run of ``"no"`` verdicts is counted in.

    The extraction's own report is the switch. G8 applies only when
    ``extracted_answers`` is an ``ExtractedAnswers`` that carries one, which
    is what the gated extractor attaches to answers it read off a scan.
    Everything else comes back untouched, ``binding=None``, whatever the
    marker said: a plain mapping (typed answers, CLI JSON), and an
    ``ExtractedAnswers`` with no report (quiz marking, the accuracy harness's
    golden answers, an extraction made with the gate off). Those answers were
    never bound to a question by reading a page, or the gate was not asked,
    so there is no binding to doubt and no report is invented for them.

    With a report, the result's ``binding`` is that report with G8 appended.
    Its verdict is the MORE SEVERE of the one the report arrived with and the
    one recomputed over every check with the report's own ``retried``
    (``hold`` over ``retry`` over ``pass``): adding G8 can raise a verdict
    and can never lower it, whether or not the incoming verdict has a
    failing paper-scope check behind it.

    Scope decides what else changes. A PAPER-scope failure changes no
    question: the verdict stops the whole paper and the report names the
    answers. A QUESTION-scope failure (too few to doubt the paper's binding)
    sends just those questions to teacher review, joined onto any reason the
    builders already gave. ``awarded_marks`` is never touched either way. The
    result is REBUILT, not ``model_copy``-ed, so ``calculate_totals`` derives
    the paper-level ``needs_teacher_review`` from the flagged rows.

    The binding's own doubts do not wait for a report. A question whose answer
    carries ``binding_status="unverified"`` was marked as usual and is then
    sent to teacher review with :data:`UNVERIFIED_BINDING_REVIEW_REASON` joined
    onto its reasons, after G8's when both apply; its marks and the verdict are
    untouched. That is keyed on the answer, as ``unbound_question_ids`` is keyed
    on its field: an answer that may hold another question's writing is never
    published unflagged because no gate ran over it. Quiz marking and the
    harness's golden answers never set a status, so nothing changes for them.
    """
    if not isinstance(extracted_answers, ExtractedAnswers):
        return result
    unverified = {
        a.question_id for a in extracted_answers.answers if a.binding_status == "unverified"
    }
    prior = extracted_answers.binding
    if prior is None:
        if not unverified:
            return result
        return CorrectionResult(
            metadata=result.metadata,
            questions=_sent_to_review(
                result.questions, unverified, UNVERIFIED_BINDING_REVIEW_REASON
            ),
        )
    check = check_off_topic(result, GateThresholds())
    checks = [*prior.checks, check]
    recomputed = verdict(checks, retried=prior.retried)
    report = prior.model_copy(
        update={
            "checks": checks,
            "verdict": max(prior.verdict, recomputed, key=_VERDICT_SEVERITY.__getitem__),
        }
    )
    questions = result.questions
    if not check.passed and check.scope == "question":
        questions = _sent_to_review(questions, set(check.question_ids), OFF_TOPIC_REVIEW_REASON)
    questions = _sent_to_review(questions, unverified, UNVERIFIED_BINDING_REVIEW_REASON)
    return CorrectionResult(metadata=result.metadata, questions=questions, binding=report)


def correct_paper(
    mark_scheme: MarkScheme | str | Mapping[str, object],
    extracted_answers: ExtractedAnswers | Mapping[str, str],
    *,
    gemini_client: GeminiClient | None = None,
    mcq_only: bool = False,
    options: MarkingOptions = MarkingOptions(),  # noqa: B008 -- frozen, immutable dataclass
) -> CorrectionResult:
    """Hybrid paper correction: MCQ deterministic, non-MCQ via AICorrector.

    Args:
        mark_scheme: parsed mark scheme.
        extracted_answers: per-question student responses.
        gemini_client: required when paper contains non-MCQ questions and mcq_only is False.
        mcq_only: if True, skip AI; non-MCQ questions get marker_source="missing".
        options: the marking flags, built by
            ``GradingSettings.marking_options()``. ``options.equivalence_gate``
            (US-005b) selects the verdicts marking path with the SymPy award
            gate. ``options.ecf_substitution`` (I7, US-013) applies
            error-carried-forward by substitution and has no effect unless
            ``equivalence_gate`` is also on: see
            :func:`_maybe_apply_ecf_substitution` for the gate/chain rules and
            the measured activation ceiling (0 on the committed corpus by
            construction). Defaults to both off.

    Returns:
        The marked paper. When ``extracted_answers`` carries a binding
        report, the result's ``binding`` is that report with check G8
        (answers the marker judged off topic) appended; otherwise it is
        ``None`` -- see :func:`_with_off_topic_check`.

    Raises:
        ConfigError: paper has non-MCQ questions, mcq_only=False, and gemini_client is None.
    """
    equivalence_gate = options.equivalence_gate
    ecf_substitution = options.ecf_substitution
    scheme = _load_mark_scheme(mark_scheme)
    leaves = [q for q in scheme.all_questions_flat() if _is_leaf_marked(q)]
    leaf_by_id: dict[str, Question] = {q.id: q for q in leaves}
    # Fix round 1 (spec 2026-09-26 §4): substitution needs to know whether a
    # leaf is MCQ before it can decide the re-read is usable, so `leaf_by_id`
    # is built before the substitution step now, not after it.
    original = _flatten_answers(extracted_answers)

    def _is_mcq_leaf(qid: str) -> bool:
        leaf = leaf_by_id.get(qid)
        return leaf is not None and leaf.type == QuestionType.MCQ

    def _substitute(qid: str, flat: _FlatAnswer) -> _FlatAnswer:
        sub = _substituted_answer(flat, is_mcq=_is_mcq_leaf(qid))
        return flat._replace(answer=sub) if sub is not None else flat

    # Spec 2026-09-26 §4 (#9): under `reread_substitution`, a leaf whose crop
    # re-read disagreed with the first read (and whose re-read text is
    # usable -- see :func:`_substituted_answer`) is marked on the re-read
    # text. Substituted ONCE, here, before the loop, so marking, the blank
    # check, ECF prerequisite text and the dropped-id subtraction all see
    # the text that is actually marked; `original` keeps the first read for
    # the review reason below.
    answers = (
        {qid: _substitute(qid, flat) for qid, flat in original.items()}
        if options.reread_substitution
        else original
    )
    # Spec 2026-09-26 §2 (#4): `dropped_question_ids` records that AN ENTRY
    # for the id was discarded, not that the question has no usable answer.
    # Only an id with no surviving answer short-circuits below; both sides are
    # post-`normalize_extracted_answers`, so canonicalised ids meet here.
    dropped_ids = _dropped_question_ids(extracted_answers).difference(answers)
    # A question the label binder could bind no answer to takes the same path as a
    # dropped answer -- flagged, a zero nobody is asked to believe, no marking call
    # -- under its own reason. The same rule applies: only an id with no surviving
    # answer short-circuits. It does not depend on a binding report: the binder
    # leaves these whether or not a gate ran over it.
    unbound_ids = _unbound_question_ids(extracted_answers).difference(answers)
    unbound_reasons = (
        extracted_answers.unbound_question_reasons
        if isinstance(extracted_answers, ExtractedAnswers)
        else {}
    )
    log = structlog.get_logger().bind(component="correct_paper")

    # Validate mark scheme structure; warn but do not abort.
    for w in validate_mark_scheme(scheme):
        log.warning("mark_scheme_validation", question_id=w.question_id, message=w.message)
        bus.publish(
            EventType.WARNING,
            message=f"Mark scheme validation [{w.question_id}]: {w.message}",
        )

    prior_results_accumulated: dict[str, int] = {}  # question_id -> awarded_marks
    # I7: for _point_was_awarded. Predates the post-loop `source_box`
    # assembly rewrite below -- every `CorrectedQuestion` stored here is the
    # pre-rewrite object, so a future reader of this dict always sees
    # `source_box=None`, never the extractor's box.
    corrected_by_id: dict[str, CorrectedQuestion] = {}
    all_by_id: dict[str, Question] = {qq.id: qq for qq in scheme.all_questions_flat()}
    top_level_groups = _group_leaves_by_top_level(leaves, all_by_id)
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
        flat = answers.get(q.id)
        student_answer = flat.answer if flat else None
        student_working = flat.working_out if flat else None
        extraction_confidence = flat.confidence if flat else None

        # US-031 review MUST-FIX 7 (stronger fix): a dropped answer must be
        # distinguishable from a genuine student blank BEFORE dispatching to
        # either the deterministic MCQ path or the AI marker -- both would
        # otherwise see the exact same `student_answer=None` a real blank
        # produces. Checked first, ahead of MCQ/AI/missing, so it applies
        # uniformly regardless of question type and never reaches
        # ai.mark_question with text extraction already discarded as
        # unusable (a paid call to mark an empty string, on top of a mark
        # that would already be wrong).
        if q.id in unbound_ids or q.id in dropped_ids:
            cq = (
                _build_dropped_corrected(q, _unbound_reason_sentence(unbound_reasons.get(q.id)))
                if q.id in unbound_ids
                else _build_dropped_corrected(q)
            )
            corrected.append(cq)
            prior_results_accumulated[q.id] = 0
            corrected_by_id[q.id] = cq
            bus.publish(
                EventType.MARKING_PROGRESS,
                question_id=q.id,
                marker_source="dropped",
                confidence=0.0,
                awarded=0,
                max_marks=q.marks,
                index=index,  # enumerate position, not an emitted-frame count
                total=total_leaves,
            )
            continue

        if q.type == QuestionType.MCQ:
            cq = _build_mcq_corrected(q, student_answer, extraction_confidence)
            corrected.append(cq)
            prior_results_accumulated[q.id] = cq.awarded_marks
            corrected_by_id[q.id] = cq
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
            cq = _build_missing_corrected(q, student_answer, extraction_confidence)
            corrected.append(cq)
            prior_results_accumulated[q.id] = 0
            corrected_by_id[q.id] = cq
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

        # US-039: a non-MCQ leaf the student left BLANK earns an unflagged 0
        # with no paid call. Checked here -- AFTER the MCQ branch (already
        # correct, left alone) and the `ai is None` branch (whose "missing"
        # means "we chose not to mark this", a different statement from "the
        # student left it blank") and BEFORE the AI marking call, so a blank
        # never reaches `ai.mark_question` at all. `student_working` is
        # checked too: a blank answer box accompanied by substantial working
        # is not treated as a true blank -- the student visibly attempted the
        # question, so awarding an unflagged 0 would be a worse claim than
        # doing so for a truly empty response, and this still reaches the AI
        # marker. See `_build_blank_corrected` for the full ruling.
        if _is_blank(student_answer) and _is_blank(student_working):
            cq = _build_blank_corrected(q, extraction_confidence)
            corrected.append(cq)
            prior_results_accumulated[q.id] = 0
            corrected_by_id[q.id] = cq
            bus.publish(
                EventType.MARKING_PROGRESS,
                question_id=q.id,
                # Read off the record rather than repeating the builder's
                # literal: this frame said "missing" for a blank until task
                # #36 gave the blank its own `marker_source`, which made it a
                # tenth hand-written copy of the same fact and the live
                # progress log's only disagreement with the row that gets
                # persisted (`lemely/app/live_log.py` renders this).
                marker_source=cq.marker_source,
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
                # #41 / A13: the paper's OWN printed principles govern the M/A
                # dependency. `extract_gmp` has always populated this field and
                # it was discarded here.
                principles=scheme.metadata.generic_marking_principles or None,
                equivalence_gate=equivalence_gate,
            )
        except CostCeilingError:
            # US-030: a per-run token/USD ceiling breach is a stop signal for
            # the whole run, not a per-question marking failure. The broad
            # `except Exception` below used to absorb it exactly like a model
            # failure: every remaining leaf was still attempted (re-breaching
            # each time), each landed in the result as `awarded=0` with
            # review_reason "AI marking failed: USD ceiling (...)", and
            # `correct_paper` returned NORMALLY — so a sweep ran to completion
            # and archived an accuracy report of fabricated zeros that no
            # caller could tell from real model failures. Must stay the FIRST
            # clause: `CostCeilingError` is a `LemelyError` and an
            # `ExternalServiceError`, so any broader handler placed above it
            # silently reinstates the bug.
            raise
        except Exception as exc:
            log.warning("ai_marking_failed", question_id=q.id, error=str(exc))
            cq = _build_missing_corrected(q, student_answer, extraction_confidence)
            cq = cq.model_copy(update={"review_reason": f"AI marking failed: {exc!s}"})
            corrected.append(cq)
            corrected_by_id[q.id] = cq
            # Deliberately no index/total here: the per-question counter belongs to
            # MARKING_PROGRESS, and ERROR is not a progress frame. This `index` is
            # simply skipped — the next question still reports its own enumerate
            # position, so the counter stays aligned with the work list.
            bus.publish(
                EventType.ERROR,
                message=f"AI marking failed for q={q.id}: {exc!s}",
            )
            continue
        cq = _build_ai_corrected(
            q,
            student_answer or "",
            mark,
            student_working,
            extraction_confidence,
            equivalence_gate=equivalence_gate,
        )
        cq = _maybe_apply_ecf_substitution(
            q,
            cq,
            mark,
            student_answer or "",
            student_working,
            extraction_confidence,
            ai=ai,
            ecf_substitution=ecf_substitution,
            equivalence_gate=equivalence_gate,
            principles=scheme.metadata.generic_marking_principles or None,
            sibling_prior=sibling_prior or None,
            answers=answers,
            top_level_leaves=top_level_groups[_top_level_ancestor_id(q.id, all_by_id)],
            corrected_by_id=corrected_by_id,
            log=log,
        )
        corrected.append(cq)
        prior_results_accumulated[q.id] = cq.awarded_marks
        corrected_by_id[q.id] = cq
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

    corrected = [
        _attach_extraction_context(cq, answers, original, options, leaf_by_id) for cq in corrected
    ]
    # G8 counts only explicit judgements, so a marker that leaves
    # `addresses_question` out makes the check pass on no evidence. One line
    # per paper says how many kept replies did (an "ai" row with no judgement
    # is exactly that), so a check that never fires can be told from a model
    # that never answers. Logged with or without a binding report.
    marked = [cq for cq in corrected if cq.marker_source == "ai"]
    omitted = sum(1 for cq in marked if cq.addresses_question is None)
    if omitted:
        log.warning("marker_omitted_addresses_question", omitted=omitted, marked=len(marked))
    return _with_off_topic_check(
        CorrectionResult(metadata=_exam_metadata(scheme), questions=corrected), extracted_answers
    )
