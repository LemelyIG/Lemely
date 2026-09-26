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

import re
from typing import TYPE_CHECKING

import structlog
import sympy

from lemely.core.equivalence import Verdict, VerdictKind, equivalent, parse_expr_safe
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
from lemely.runtime.errors import CostCeilingError, ExternalServiceError, ParseError

if TYPE_CHECKING:
    from lemely.io.gemini import GeminiClient

#: N3 step 4. Total attempts per weak area, including the first generation —
#: not 3 *additional* regenerations on top of it. Bounded so a persistently
#: wrong topic cannot loop forever burning Gemini calls; the item is simply
#: dropped from the quiz once this is exhausted (see
#: lemely.io.question_generation.QuestionGenerator).
MAX_GENERATION_ATTEMPTS = 3

#: Spec 2026-09-26 §10 (#5). The IGCSE/A-level convention: a calculated
#: answer is stated to 3 significant figures. This is a GENERATION-GATE
#: policy -- the generator's own stated answer is compared against its own
#: exact solution -- not a marking tolerance; the marking path keeps
#: deriving its tolerance from the scheme (`lemely.core.equivalence`).
GATE_SIG_FIGS = 3

#: Fix round 2: CAIE physics notation for scientific-notation magnitude,
#: "<mantissa> x 10^<exp>" (also accepting the multiplication-sign glyph in
#: place of the ASCII 'x'/'X'). That glyph stands for "times" here, never
#: SymPy's algebra variable ``x`` -- without this being consumed FIRST,
#: "2.4 x 10^4 J" parses (via implicit multiplication) as
#: ``24000.0*J*x``, a spurious free-symbol product, not the number 24000
#: with a unit.
_SCI_X_NOTATION_RE = re.compile(
    r"^\s*(?P<mantissa>[-+]?(?:\d+\.?\d*|\.\d+))"
    r"\s*[xX\u00d7]\s*10\s*\^\s*(?P<exponent>[-+]?\d+)"
    r"(?P<rest>.*)$"
)

#: Fix round 4 (Important): a whitelist of UNPREFIXED base unit symbols
#: only -- ``kg`` is its own entry (the SI base unit), never a composed
#: ``k`` prefix + ``g`` base. Round 2/3 also allowed an SI prefix
#: (k/M/G/m/...) in front of any base, which stripped a tail like ``"24
#: kJ"`` down to bare ``"24"`` WITHOUT applying the prefix's magnitude --
#: silently discarding a factor of 1000 in either direction (a wrong
#: answer could verify; a correct one could be rejected). The controller
#: decision is to never scale by prefix at all (``m`` as metre vs milli,
#: ``T`` as tesla vs a variable, make that ambiguous) -- so a PREFIXED
#: tail is simply never recognised as a unit and is left completely
#: untouched; ``%`` is likewise never stripped (0.24 vs "24 %" needs a
#: /100 scale this module refuses to guess at, same reasoning). An
#: unrecognised letter (``x``, ``pi``) is still never treated as a unit
#: either, which is what makes "24 pi"/"6x" fall through to a real
#: (numeric or structural) disproof instead of being silently stripped
#: away.
_UNIT_BASE_RE = r"(?:kg|ohm|mol|eV|Pa|Hz|°C|m|s|g|J|N|W|V|A|K|C|L|Ω)"

_UNIT_ATOM_RE = rf"(?:{_UNIT_BASE_RE})(?:\^-?\d+)?"

#: A trailing tail of one or more `_UNIT_ATOM_RE`s joined by '/', '·', '*'
#: or a single space, anchored at the END of the string -- so ``"24 J"``
#: strips to ``"24"``, but ``"6x"``, ``"24 pi"`` and ``"24 J 5"`` (a unit
#: atom followed by a bare, non-unit "5") never match at all. Searched
#: (not matched) from the end, rather than requiring a specific NUMBER
#: shape before it, because Fix round 4's `_expand_sci_x_notation` can
#: leave a compound expression (``"(2.4)*10**(4)"``) in front of the unit,
#: not a plain number. The ``(?<![A-Za-z/·*^])`` guard is what makes a
#: PREFIXED tail like ``"kJ"`` fail entirely rather than partially --
#: without it, the search would still find "J" alone (leaving a dangling,
#: nonsensical "k" glued onto the number) since only "kJ" as a WHOLE is
#: unrecognised, not "J" on its own. Fix round 5 addendum (a): widened to
#: also exclude a preceding SEPARATOR ('/', '·', '*', '^') -- "24 km/s"
#: and "24*s" have the exact same problem one letter over: "s" alone (with
#: "24 km/" or "24*" left dangling) matches on its own once "km" (a
#: letter-prefixed, unrecognised unit) or "*" is skipped past. This guard
#: alone still lets `re.search` hop PAST a blocked separator when a SPACE
#: sits between it and the next candidate start (see `_strip_trailing_unit`
#: for the "24 / s" case that needs a second check).
_UNIT_TAIL_RE = re.compile(
    rf"(?<![A-Za-z/·*^])\s*(?P<unit>{_UNIT_ATOM_RE}(?:(?:[/·*]|\s){_UNIT_ATOM_RE})*)\s*$"
)


def _expand_sci_x_notation(stated: str) -> str:
    """``"2.4 x 10^4 J"`` -> ``"(2.4)*10**(4) J"``; anything else unchanged.

    Fix round 4 (Minor): rewritten as a SymPy-parseable EXPRESSION rather
    than computed in Python floats (``mantissa * 10.0**exponent``) -- the
    float computation raised an uncaught ``OverflowError`` for an exponent
    like 400 (nothing catches it around ``verify_question``, so it aborted
    the whole generation request) and silently underflowed a very negative
    exponent (``"2 x 10^-400"``) to exactly ``0.0``. SymPy's own arbitrary-
    precision arithmetic parses ``10**(400)``/``10**(-400)`` exactly, with
    neither failure mode.
    """
    match = _SCI_X_NOTATION_RE.match(stated)
    if match is None:
        return stated
    return f"({match.group('mantissa')})*10**({match.group('exponent')}){match.group('rest')}"


def _strip_trailing_unit(stated: str) -> str:
    """Normalise CAIE-style magnitude/unit notation, or return unchanged.

    Two independent, sequential transforms: :func:`_expand_sci_x_notation`
    resolves an "x 10^n" magnitude first (a unit tail after it is still
    found by :data:`_UNIT_TAIL_RE`, which searches from the end rather
    than anchoring at a specific value shape), then a trailing tail is
    dropped ONLY when it fully matches :data:`_UNIT_TAIL_RE` -- one or
    more whitelisted, UNPREFIXED unit atoms and nothing else, so ``"24
    J"`` strips to ``"24"`` but ``"6x"``, ``"24 pi"``, ``"24 J 5"`` and a
    PREFIXED tail like ``"24 kJ"`` are all left alone.

    Fix round 5 addendum (a): :data:`_UNIT_TAIL_RE`'s lookbehind still lets
    `re.search` hop PAST a blocked separator when a space follows it --
    ``"24 / s"`` finds "s" alone starting right after that space (the
    lookbehind only inspects the char immediately before ITS OWN match,
    which is the space, not the "/" one character further back), leaving
    a dangling ``"24 / "`` as the "value". A genuine ``"<value> <unit>"``
    tail never ends in an operator once trailing whitespace is dropped, so
    that shape is rejected here explicitly rather than returned as a
    stripped (but nonsensical, unparseable) value.
    """
    stated = _expand_sci_x_notation(stated)
    match = _UNIT_TAIL_RE.search(stated)
    if match is None:
        return stated
    value = stated[: match.start()].rstrip()
    if not value or value[-1] in "/·*^":
        return stated
    return value


def _safe_equivalent(a: str | sympy.Expr, b: str | sympy.Expr, *, sig_figs: int) -> Verdict:
    """:func:`~lemely.core.equivalence.equivalent`, guarded against too extreme a magnitude.

    Fix round 5 addendum (b): ``_ToleranceSpec._sig_figs_candidate``
    (``lemely/core/equivalence.py``) computes ``math.floor(math.log10(abs(
    ref)))`` -- for ``ref`` around ``10**308`` or beyond, converting it to
    a Python ``float`` overflows to ``inf``, and ``math.floor(inf)`` raises
    ``OverflowError``. ``GATE_SIG_FIGS`` always sets ``sig_figs``, so this
    branch runs on every comparison this module makes -- a magnitude this
    extreme is reachable in practice through ``_expand_sci_x_notation``
    (``"2 x 10^400"``), not merely synthetic. Treated the same way
    :func:`equivalent` itself treats a resource/timeout failure (I8 review
    MUST-FIX #4): the comparison could not be completed, which is not a
    disproof, so ``UNPARSEABLE`` rather than letting the exception escape
    and abort the whole generation request.
    """
    try:
        return equivalent(a, b, sig_figs=sig_figs)
    except (OverflowError, ValueError) as exc:
        return Verdict(VerdictKind.UNPARSEABLE, detail=f"magnitude too extreme to compare: {exc}")


def _compare_stated(exact: str, stated: str) -> Verdict:
    """Compare a stated answer against an exact one at :data:`GATE_SIG_FIGS`.

    Fix round 2: three attempts, in order, each returned as soon as it
    proves equality.

    1. :func:`~lemely.core.equivalence.equivalent` on ``exact``/``stated``
       UNMODIFIED. This alone handles a stated answer already within
       tolerance when both sides are plain numbers (``"22/7"`` vs
       ``"3.14"``), and an exact match written in a different but
       algebraically identical symbolic form (``"1/sqrt(2)"`` vs
       ``"sqrt(2)/2"``, or the SAME irrational constant on both sides,
       ``"sqrt(2)"`` vs ``"sqrt(2)"``, or ``"2*pi"`` vs ``"2 pi"`` --
       ``pi`` is a numeric constant to SymPy, not a free symbol, so this
       parses and simplifies exactly like any other pure-number pair).
    2. When step 1 fails to prove equality AND both sides parse to a
       constant (no free symbols), numerically evaluate BOTH sides
       (``sympy.N``) and retry. This is for an exact IRRATIONAL constant
       against a decimal approximation (``"sqrt(2)"`` vs ``"1.41"``):
       ``equivalent``'s tolerance window is keyed per algebraic term, and
       ``sqrt(2)`` and ``1.41`` are different keys, so step 1 gets no
       tolerance leniency there at all. N()-ing only ONE side (the
       pre-fix-round-2 approach) broke the identical-form case above --
       ``"sqrt(2)"`` vs ``"sqrt(2)"`` would then compare a decimal against
       a still-symbolic ``sqrt(2)``, a term-key mismatch of exactly the
       same shape -- which is why step 1 must run FIRST and unmodified;
       this step is only a fallback for what it could not prove.
    3. When that also fails, strip a trailing unit or an "x 10^n" magnitude
       from ``stated`` (:func:`_strip_trailing_unit`) and retry the whole
       comparison recursively -- ``"24 J"`` -> ``"24"``, ``"2.4 x 10^4 J"``
       -> ``"24000.0"``. A ``stated`` that is genuinely wrong (``"24
       pi"``, ``"6x"``, ``"24 J 5"``) either fails step 2 on its own merits
       (a real numeric or structural mismatch) or is never touched by the
       stripper at all (no whitelisted unit tail to strip), so it falls
       through to whichever verdict step 1 or step 2 already computed --
       never silently stripped into a false match.
    """
    verdict = _safe_equivalent(exact, stated, sig_figs=GATE_SIG_FIGS)
    if verdict.kind is VerdictKind.EQUAL_PROVEN:
        return verdict
    exact_expr = parse_expr_safe(exact)
    stated_expr = parse_expr_safe(stated)
    if (
        exact_expr is not None
        and stated_expr is not None
        and not exact_expr.free_symbols
        and not stated_expr.free_symbols
    ):
        numeric_verdict = _safe_equivalent(
            sympy.N(exact_expr), sympy.N(stated_expr), sig_figs=GATE_SIG_FIGS
        )
        if numeric_verdict.kind is VerdictKind.EQUAL_PROVEN:
            return numeric_verdict
        verdict = numeric_verdict
    stripped = _strip_trailing_unit(stated)
    if stripped != stated:
        recursive_verdict = _compare_stated(exact, stripped)
        if recursive_verdict.kind is VerdictKind.UNPARSEABLE:
            # Fix round 5 addendum (a): a strip that leaves something this
            # module cannot itself compare must not SILENTLY DOWNGRADE a
            # real verdict step 1/2 already computed (a hard NOT_EQUAL, or
            # another EQUAL_PROVEN/EQUAL_SAMPLED found before stripping)
            # into "could not verify" -- which would buy a needless paid
            # sandbox call for a case this function already had an answer
            # for.
            return verdict
        return recursive_verdict
    return verdict


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
    except CostCeilingError:
        # `CostCeilingError` subclasses `ExternalServiceError`, so the
        # handler below used to file a per-run budget breach as "the sandbox
        # produced no usable result" and let the regenerate loop keep going.
        # A ceiling breach is a stop signal for the whole run and is never
        # retryable, so it propagates. Must stay the FIRST clause: placing
        # the broader `ExternalServiceError` above it silently reinstates
        # the bug (same ruling as lemely/io/mark_schemes.py).
        raise
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
        verdict = _compare_stated(question.solution_expr, question.answer)
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

    sandbox_verdict = _compare_stated(sandbox_answer, question.answer)
    if sandbox_verdict.kind is VerdictKind.EQUAL_PROVEN:
        return question.model_copy(update={"verified_by": "sandbox", "rejection_reason": None})

    detail = sandbox_verdict.detail or sandbox_verdict.kind.value
    return _reject(
        question,
        f"sandbox: code execution result does not match the stated answer ({detail})",
        subject_code=subject_code,
        attempt=attempt,
    )
