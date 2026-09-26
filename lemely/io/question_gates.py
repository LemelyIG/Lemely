"""N3: verification gates for AI-generated practice questions.

``QuestionGenerator.generate`` used to return Gemini's output verbatim, and
``TeacherQuizBuilder`` topped up shortfall the same way. Measured rates for
unverified AI items: 6% factual error, 14% wrong difficulty, 38% clearing the
discrimination bar (B6 [gen 6]). Nothing checked that a generated question's
stated answer was actually the answer to the question — this module is that
check.

The five steps (docs/plans/ai-improvements-plan.md:610-618):

1. A validity pass (:func:`check_validity`) — one structured call asking
   whether the question is well-posed, missing data, contradictory, or has a
   single answer.
2. For CALCULATION / EQUATION / numeric RECALL items: solve
   ``question.solution_expr`` and compare it to ``question.answer`` locally
   with :func:`lemely.core.equivalence.equivalent`.
3. If SymPy could not PROVE the answer (an ``EQUAL_SAMPLED`` finite-sample
   match, or ``UNPARSEABLE``), fall back to Gemini's own ``code_execution``
   tool (:meth:`~lemely.io.gemini.GeminiClient.generate_with_code_execution`)
   — NOT a locally-built sandbox — and compare that independently-computed
   answer to the stated one instead.
4. Reject -> regenerate, up to :data:`MAX_GENERATION_ATTEMPTS`, feeding the
   rejection reason back into the next attempt's prompt
   (:mod:`lemely.io.question_generation`).
5. Tag the result with ``verified_by`` and ``rejection_reason``
   (:class:`lemely.core.generation.GeneratedQuestion`).

Deliberately not done here: difficulty stays ``declared_by_generator``;
distractor mining from examiner reports (the reports are not in this
checkout).

Which :class:`~lemely.core.equivalence.VerdictKind` counts as "verified", and
why: only ``EQUAL_PROVEN`` does, at every step. ``EQUAL_SAMPLED`` is a
finite-sample numeric match — evidence of equivalence, not proof of it (two
distinct expressions can coincide at finitely many points,
:attr:`~lemely.core.equivalence.Verdict.auto_awardable`) — so it is treated
exactly like ``UNPARSEABLE`` here: not a pass, but also not the positive
claim ``NOT_EQUAL`` is, so it falls through to the code-execution fallback
rather than being rejected outright. ``UNPARSEABLE`` (which covers both
"could not read the text" and a solver timeout) is never recorded as
verified, at either the SymPy or the code-execution step — this module's
``verified_by`` never claims more than the verdict backing it actually
supports.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from lemely.core.equivalence import VerdictKind, equivalent, parse_expr_safe
from lemely.core.generation import (
    SOLVABLE_QUESTION_TYPES,
    GeneratedQuestion,
    QuestionValidityCheck,
)
from lemely.core.loose_schemas import QuestionType
from lemely.io.prompts.question_generation import (
    CODE_EXECUTION_VERSION,
    VALIDITY_VERSION,
    build_code_execution_prompt,
    build_validity_check_system_prompt,
    build_validity_check_user_prompt,
)
from lemely.runtime.errors import ExternalServiceError, ParseError

if TYPE_CHECKING:
    from lemely.io.gemini import GeminiClient

#: N3 step 4. Total attempts per weak area, including the first generation —
#: not 3 *additional* regenerations on top of it. Bounded so a persistently
#: wrong topic cannot loop forever burning Gemini calls; the item is simply
#: dropped from the quiz once this is exhausted (see
#: lemely.io.question_generation.QuestionGenerator).
MAX_GENERATION_ATTEMPTS = 3


def check_validity(
    client: GeminiClient, question: GeneratedQuestion, *, subject_code: str
) -> QuestionValidityCheck:
    """N3 step 1: ask whether ``question`` can be answered at all."""
    return client.generate_structured(
        system_prompt=build_validity_check_system_prompt(subject_code),
        user_prompt=build_validity_check_user_prompt(question),
        response_schema=QuestionValidityCheck,
        prompt_version=VALIDITY_VERSION,
        task_tag="question_validity",
        extra_cache_key=f"{subject_code}:{question.topic}:{question.prompt}",
    )


def _validity_rejection_reason(validity: QuestionValidityCheck) -> str:
    reasons = []
    if not validity.well_posed:
        reasons.append("not well-posed")
    if validity.missing_data:
        reasons.append("missing data")
    if validity.contradictory:
        reasons.append("contradictory")
    if not validity.single_answer:
        reasons.append("does not have a single answer")
    return f"validity: {', '.join(reasons)}"


def _admits_solver(question: GeneratedQuestion) -> bool:
    """N3 step 2's scope, MUST-FIX 2.

    CALCULATION/EQUATION always admit a
    solver; RECALL admits one only when its stated answer is present and
    SymPy-parseable — i.e. *numeric* RECALL (plan:611), not the far more
    common prose RECALL ("name the process...") which has no stated
    answer for a solver to check at all. Every other question_type never
    admits a solver.
    """
    if question.question_type in SOLVABLE_QUESTION_TYPES:
        return True
    if question.question_type is QuestionType.RECALL:
        return question.answer is not None and parse_expr_safe(question.answer) is not None
    return False


def _reject(
    question: GeneratedQuestion, reason: str, *, subject_code: str, attempt: int
) -> GeneratedQuestion:
    """Return the rejected copy of ``question`` and log it.

    N3 review MUST-FIX 3: an item that fails every gate step vanishes from
    `QuestionGenerator.generate` with nothing else recording that it
    happened — a teacher requesting 5 questions silently receiving 2, with
    no log line, counter, or field anywhere saying 3 were rejected or why.
    Every rejection is logged here, structured on the fields a production
    diagnosis actually needs (subject_code, topic, rejection_reason, and
    which attempt this was) rather than as free text.
    """
    structlog.get_logger().warning(
        "question_rejected",
        subject_code=subject_code,
        topic=question.topic,
        verified_by=None,
        rejection_reason=reason,
        attempt=attempt,
    )
    return question.model_copy(update={"verified_by": None, "rejection_reason": reason})


def _run_code_execution(client: GeminiClient, question: GeneratedQuestion) -> str | None:
    """N3 step 3.

    Returns the sandbox's answer text, or ``None`` if the call itself
    failed (network, no key) or returned nothing usable — either way,
    "could not verify", never treated as a disproof.
    """
    try:
        raw = client.generate_with_code_execution(
            prompt=build_code_execution_prompt(question),
            prompt_version=CODE_EXECUTION_VERSION,
            task_tag="question_validity",
            extra_cache_key=f"{question.topic}:{question.prompt}",
        )
    except (ParseError, ExternalServiceError):
        return None
    raw = raw.strip()
    return raw or None


def verify_question(
    client: GeminiClient,
    question: GeneratedQuestion,
    *,
    subject_code: str,
    attempt: int = 0,
) -> GeneratedQuestion:
    """Run the full N3 gate pipeline on one generated question.

    Returns a copy of ``question`` with ``verified_by``/``rejection_reason``
    set. Any ``verified_by``/``rejection_reason`` already present on
    ``question`` (e.g. leftover fields a prior Gemini JSON response happened
    to fill in) is discarded and replaced — this function's own findings are
    the only source of truth for those two fields.

    ``attempt`` is the 0-based regeneration attempt this call is running as
    (see :mod:`lemely.io.question_generation`); it is carried through only
    to the rejection log record (MUST-FIX 3), never into the pass/fail
    decision itself.
    """
    validity = check_validity(client, question, subject_code=subject_code)
    if not validity.passes:
        return _reject(
            question,
            _validity_rejection_reason(validity),
            subject_code=subject_code,
            attempt=attempt,
        )

    if not _admits_solver(question):
        # No solver applies to this question_type/answer shape (plan:610-618
        # step 2 is scoped to CALCULATION/EQUATION/numeric RECALL only); the
        # validity pass is the only check this gate can run.
        return question.model_copy(
            update={"verified_by": "validity_only", "rejection_reason": None}
        )

    verdict = None
    if question.solution_expr and question.answer:
        verdict = equivalent(question.solution_expr, question.answer)
        if verdict.kind is VerdictKind.EQUAL_PROVEN:
            return question.model_copy(update={"verified_by": "sympy", "rejection_reason": None})
        if verdict.kind is VerdictKind.NOT_EQUAL:
            return _reject(
                question,
                f"sympy: stated answer does not equal the solved value ({verdict.detail})",
                subject_code=subject_code,
                attempt=attempt,
            )
        # EQUAL_SAMPLED or UNPARSEABLE: SymPy did not PROVE the answer, so
        # fall through to the code-execution fallback (step 3) rather than
        # either rejecting on unproven evidence or accepting it.

    if not question.answer:
        # MUST-FIX 2's backstop: an item with no stated answer at all can
        # never be verified by any step below, so reject it here rather
        # than spending a paid code_execution call whose comparison
        # against None would always fail anyway.
        return _reject(
            question,
            "no stated answer to verify",
            subject_code=subject_code,
            attempt=attempt,
        )

    sandbox_answer = _run_code_execution(client, question)
    if sandbox_answer is None:
        detail = verdict.detail if verdict is not None else "no solution_expr to solve"
        return _reject(
            question,
            f"sandbox: code execution produced no usable result ({detail})",
            subject_code=subject_code,
            attempt=attempt,
        )

    sandbox_verdict = equivalent(sandbox_answer, question.answer)
    if sandbox_verdict.kind is VerdictKind.EQUAL_PROVEN:
        return question.model_copy(update={"verified_by": "sandbox", "rejection_reason": None})

    detail = sandbox_verdict.detail or sandbox_verdict.kind.value
    return _reject(
        question,
        f"sandbox: code execution result does not match the stated answer ({detail})",
        subject_code=subject_code,
        attempt=attempt,
    )
