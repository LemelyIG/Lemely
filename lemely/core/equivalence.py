"""SymPy-backed expression equivalence (I8, D12).

The AI marker's only defence against a near-miss numeric or algebraic answer
was, until now, a regex literal-presence check
(:func:`lemely.io.correction_ai._verify_calculated_answers`): it can tell
that a value is *absent*, but it cannot tell that two differently-written
values are the *same* one (``1/2 mv^2`` vs ``0.5mv²``, ``3.0×10^8`` vs
``300000000``, ``g/cm3`` vs ``g cm^-3``). That gap is B8 #5.

This module is the shared solver behind three call sites, each of which
imports it rather than re-implementing symbolic comparison:

1. I6/I7 A-mark verdicts — an A-mark the AI awarded but this module finds
   ``not_equal`` is withheld and routed to human review
   (``equivalence_conflict``); one it withheld but this module finds
   ``equal`` is *also* routed to review, never silently auto-awarded (D12 —
   accuracy-first but unlabelled, so treated as a review candidate until
   labels show the false-positive rate).
2. I2's ``expression_exact`` transcription metric.
3. ``_verify_calculated_answers`` as a fallback when its own literal check
   would otherwise reject an answer this module can prove equivalent.
4. (Designed for, not yet wired: N3's generated-question filter — it needs
   exactly this shape, ``parse -> compare -> Verdict``, with no numerical
   marking policy baked in, so it can call :func:`equivalent` directly.)

Conflicts are never auto-resolved into a mark. ``Verdict`` records *what this
module found*; what a caller does with it is the caller's policy, but one
rule is structural rather than a convention a caller could forget:
:attr:`Verdict.auto_awardable` is only ever true for a ``simplify``-method
``equal`` — a numeric-sample match is evidence of equivalence, not proof of
it (two different expressions can coincide at finitely many points), so it
can support a review decision but must never itself award a mark.

Deferred, not implemented here: the spec's light-LaTeX parsing arm (SymPy's
Lark backend). Every mark scheme and student answer observed so far is
plain text/unicode notation (``×``, superscripts, ``^``), which
:func:`parse_expr_safe` handles directly; nothing in this module or its
tests exercises LaTeX input, and ``pyproject.toml``'s sympy dependency note
does not claim otherwise.
"""

from __future__ import annotations

import hashlib
import math
import queue
import random
import re
import threading
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import TYPE_CHECKING

import sympy

if TYPE_CHECKING:
    from collections.abc import Callable
from sympy.parsing.sympy_parser import (
    convert_xor,
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)

#: Longer inputs are rejected before ever reaching the parser. Mark-scheme
#: and student-answer text is at most a few dozen characters in every
#: observed case; this is a safety margin against pathological input driving
#: pathological parse time, not a realistic ceiling.
_MAX_INPUT_LEN = 500

#: Default budgets. A `simplify` call that has not returned within
#: `_DEFAULT_SIMPLIFY_TIMEOUT` is abandoned in favour of a numeric
#: comparison, which must itself complete within `_DEFAULT_NUMERIC_TIMEOUT`.
#: Parsing gets its own, smaller budget — nothing about parsing plain
#: arithmetic should take a second, and this bounds worst-case latency for
#: an input hygiene misses (see `_run_bounded`, MUST-FIX #9 of the I8
#: review).
_DEFAULT_SIMPLIFY_TIMEOUT = 2.0
_DEFAULT_NUMERIC_TIMEOUT = 0.5
_DEFAULT_PARSE_TIMEOUT = 1.0

#: Random numeric-substitution points used by the fallback comparison.
_NUMERIC_SAMPLE_POINTS = 8

#: Default absolute/relative tolerance when the caller supplies no
#: scheme-derived precision (`sig_figs`, `dp`, `tolerance`). Deliberately
#: tiny — a few orders of magnitude above float round-off noise
#: (`(0.1 + 0.2) - 0.3` is ~5.5e-17) and a few orders below any real
#: physics discrepancy, so it absorbs float noise without ever being
#: mistaken for a marking tolerance. Marking-relevant leniency must come
#: from the scheme (`sig_figs`/`dp`/`tolerance`), never from this default.
_DEFAULT_ABS_TOL = 1e-9
_DEFAULT_REL_TOL = 1e-9

#: An absolute-shaped candidate (`dp`, a bare "± N", or `sig_figs` at the
#: low end where its own window can exceed `ref`) more than this many
#: multiples of `ref` is not "a precision statement about an answer of this
#: magnitude, expressed a bit too loosely" any more — it is a different
#: order of magnitude altogether ("2 dp" applied to `1.6e-19` is
#: thirty-three orders of magnitude off `ref`, not merely imprecise) — so
#: it is DISCARDED outright, contributing no leniency at all. Within this
#: many multiples of `ref`, it is CAPPED to `_ABS_TOLERANCE_SANITY_FRACTION
#: * ref` rather than used verbatim — see
#: `_plausible_or_discard_absolute_candidate` and
#: `_ToleranceSpec.for_magnitude` for why an uncapped "use it as-is within
#: the band" reading (I8 re-review round 5's correction, since reverted —
#: it let a window reach `10 * ref`, wide enough to tolerate a sign flip or
#: a 100-400% error at ordinary magnitude, confirmed as `equal_proven`/
#: `auto_awardable=True`) is unsafe: a window must never exceed the answer
#: it is describing, however "plausible" its raw value looks relative to
#: `ref`. Two regimes, not one: "plausible, cap to a sane fraction of `ref`"
#: or "implausible, discard entirely" — never "plausible, use unbounded".
_ABS_TOLERANCE_DISCARD_MULTIPLE = 10.0

#: The cap applied to a plausible absolute-shaped candidate — see above.
_ABS_TOLERANCE_SANITY_FRACTION = 0.5

#: A caret/`**` tower (`9^9^9`) or a single huge literal exponent
#: (`2**100000000`) has no realistic CAIE reading and can otherwise hang
#: parsing or produce a multi-million-digit integer (I8 review MUST-FIX #9).
_MAX_EXPONENT_VALUE = 1000

_TRANSFORMATIONS = (
    *standard_transformations,
    implicit_multiplication_application,
    convert_xor,
)

#: Unicode superscript digits/signs, unfolded to an explicit `**(...)`
#: exponent *before* any other normalisation runs — NFKC alone silently
#: collapses e.g. "10⁸" to the digit string "108" instead of an exponent,
#: which is a different number. This must run on the raw text.
_SUPERSCRIPT_CHARS = "⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺"
_SUPERSCRIPT_TRANSLATE = str.maketrans(_SUPERSCRIPT_CHARS, "0123456789-+")
_SUPERSCRIPT_RUN_RE = re.compile(f"[{_SUPERSCRIPT_CHARS}]+")

#: Multiplication/division glyphs CAIE mark schemes use instead of `*`/`/`.
_MULT_CHARS = "×·∙"
_UNICODE_MINUS = "−"

#: Base SI/CAIE unit symbols. Ordered longest-first so the unit-digit
#: alternation below cannot match a short prefix of a longer symbol (e.g.
#: "cm" before "c").
_BASE_UNIT_SYMBOLS = (
    "mol",
    "atm",
    "cm",
    "mm",
    "km",
    "kg",
    "Hz",
    "Pa",
    "cd",
    "m",
    "g",
    "s",
    "N",
    "J",
    "W",
    "A",
    "V",
    "C",
    "F",
    "T",
    "H",
    "K",
    "L",
    "l",
    "Ω",
)

#: SI prefixes CAIE mark schemes combine with a base unit ("mg", "kJ",
#: "MHz", ...). Each (prefix, base) pair is protected as its OWN atomic
#: symbol — never as prefix-symbol times base-symbol — because "mg" is a
#: unit of mass, not the product of a unit "m" (metre) and a unit "g"
#: (gram). Without this, "4.5 mg" and "4.5 gm" (gram times metre, a
#: dimensionally different and nonsensical quantity here) parse to the same
#: expression and compare `equal` (I8 review mechanism 5).
#:
#: KNOWN LIMITATION (I8 re-review round 4 SHOULD-FIX 7, deliberately not
#: fixed): "m" is the one SI prefix that is ALSO a base unit symbol
#: (metre), so a compound written with no separator and no exponent on the
#: first factor is genuinely ambiguous — "kg ms^-2" reads as
#: `kg / ms**2` (kilogram per millisecond squared, the atomic-prefix
#: reading this table exists for) rather than `kg * m / s**2` (the newton,
#: what "kg m s^-2" without the missing space meant). Every discriminator
#: tried (neighbouring-token context, exponent position, a
#: prefix-plus-exponent rule) either breaks a case this table is already
#: pinned on (`g/cm3`, `4.5 mg`) or trades this known over-rejection for a
#: new silent WRONG parse on the award path — worse, since a wrong parse
#: can auto-award and an over-rejection can only route to review. The only
#: correct discriminator is a dimensional-plausibility check against a
#: table of named derived units, which is a different, larger piece of
#: work than this module. The affected shape is narrow — a two-letter
#: prefix-ambiguous factor (`mA`, `mC`, `mF`, `mg`, `mH`, `mJ`, `mK`, `mL`,
#: `ml`, `mm`, `mN`, `ms`, `mT`, `mV`, `mW`), no separator, no exponent on
#: that factor specifically — and the direction is always over-rejection
#: (`not_equal`, never a false `equal_proven`): pinned by
#: ``test_kg_ms_known_limitation_is_not_equal_never_equal_proven`` in
#: tests/test_equivalence.py.
_SI_PREFIXES = ("p", "n", "µ", "u", "m", "c", "d", "k", "M", "G")

_UNIT_SYMBOLS: tuple[str, ...] = _BASE_UNIT_SYMBOLS + tuple(
    prefix + base for prefix in _SI_PREFIXES for base in _BASE_UNIT_SYMBOLS
)
_UNIT_DIGIT_RE = re.compile(
    r"\b(" + "|".join(sorted(_UNIT_SYMBOLS, key=len, reverse=True)) + r")(\d+)(?![\d.])"
)

#: Unit spellings that are textually different but dimensionally identical,
#: normalised to a single canonical spelling before parsing so e.g. "g/cm3"
#: and "g cm^-3" are compared as the same symbolic expression rather than
#: relying on `simplify` to discover the identity from scratch.
_UNIT_ALIASES: dict[str, str] = {
    "ohm": "Ω",
    "degC": "°C",
    "degreeC": "°C",
}

#: Names SymPy's default global namespace already binds to something other
#: than a free variable, but which are exactly the symbols CAIE physics
#: questions use most (energy `E`, current/imaginary `I`). Left unprotected,
#: `"E"` parses as `sympy.E` (Euler's number) and `"I"` as the imaginary
#: unit, so e.g. `equivalent("E", "2.718281828459045")` was reported `equal`
#: — a wrong physics answer confirmed by an unrelated mathematical identity
#: (I8 review mechanism 4). Shadowing them as plain symbols here means a
#: literal `E`/`I`/etc. typed in student or mark-scheme text is always
#: treated as the variable it is meant to be, never as the SymPy constant.
_RESERVED_NAME_OVERRIDES = ("E", "I", "O", "S", "Q", "oo", "zoo", "nan")

#: Predefined as ``local_dict`` when parsing, for two reasons:
#: (1) SymPy's `split_symbols` (part of `implicit_multiplication_application`)
#: otherwise splits multi-letter identifiers into single-letter factors —
#: without this, "cm" parses as `c * m` and "mg" as `m * g`.
#: (2) a handful of names collide with SymPy's default global namespace
#: (`_RESERVED_NAME_OVERRIDES` above).
#: Every unit symbol is included regardless of length (I8 review fix #4) —
#: a bare single-letter unit needs no *splitting* protection, but including
#: it here is harmless and keeps this the one place unit identity is
#: defined.
_UNIT_LOCAL_DICT: dict[str, sympy.Symbol] = {
    symbol: sympy.Symbol(symbol) for symbol in (*_UNIT_SYMBOLS, *_RESERVED_NAME_OVERRIDES)
}

#: Function calls this module will evaluate. Anything else that IS a known
#: SymPy callable — `factorial(100000)`, `Integral(...)` — is rejected
#: outright rather than handed to SymPy: both can be made arbitrarily
#: expensive, and `Integral` in particular reaches SymPy machinery with no
#: relevance to mark-scheme text (I8 review, "silent WRONG parses" table).
#: This is an allowlist among SymPy's own names, not a blocklist on
#: identifiers generally — an identifier that is NOT a SymPy attribute
#: (`a`, `x`, `v`, `T`, ...) is never treated as a "call" here regardless
#: of what follows it: implicit multiplication turns `a(b+c)`/`x(x+1)`/
#: `v(t)` into ordinary products, which is what a student meant. Checking
#: `hasattr(sympy, name)` is what makes that distinction — the earlier
#: version rejected identifier-before-`(` unconditionally and took out
#: every such row (I8 review S1).
_ALLOWED_FUNCTIONS = frozenset(
    {
        "sin",
        "cos",
        "tan",
        "asin",
        "acos",
        "atan",
        "sinh",
        "cosh",
        "tanh",
        "sqrt",
        "log",
        "ln",
        "exp",
        "Abs",
    }
)
_FUNCTION_CALL_RE = re.compile(r"([A-Za-zΩ°][A-Za-z0-9]*)\s*\(")


def _is_disallowed_sympy_call(name: str) -> bool:
    return name not in _ALLOWED_FUNCTIONS and hasattr(sympy, name)


#: Mark-scheme prose this module must never silently coerce into an
#: expression: "N/A", a range ("30 to 32"), a tolerance/approximation
#: marker ("±", "~", "+/-"). Each parses as *something* under implicit
#: multiplication (I8 review's "silent WRONG parses" table) — a confident
#: wrong verdict, which is strictly worse than `unparseable` routing the
#: caller back to its own literal check.
_NOT_AN_ANSWER_RE = re.compile(r"(?i)\bn\s*/\s*a\b|\bto\b|[±~]|\+\s*/\s*-")

#: A whole-number-space-fraction like "3 1/2" is a mixed number in common
#: usage but, unhyphenated, is genuinely ambiguous with two separate
#: implicitly-multiplied tokens ("3" times "1/2") once the thousands-
#: separator collapse below has run. Reject rather than guess.
_MIXED_FRACTION_RE = re.compile(r"\b\d+\s+\d+\s*/\s*\d+\b")

#: A digit run split by whitespace ("1 500", "12 000") is a thousands
#: separator in CAIE mark-scheme convention, not two implicitly-multiplied
#: numbers — collapsing it is what makes "1500" and "1 500" compare equal.
#: Must run after the mixed-fraction check above, which needs the spacing
#: intact to detect "3 1/2".
#:
#: Narrowed to require the RIGHT group be exactly three digits (a genuine
#: thousands group) and the LEFT group be a fresh integer run with no
#: decimal point anywhere in it (`(?<![\d.])` — not preceded by a digit or
#: a "."). An unqualified "collapse any digit-space-digit" also ate
#: dropped-`×` standard form: "1.6 10^-19" (meant `1.6 × 10^-19`) collapsed
#: to "1.610^-19" (a different, wrong number), and "3.0 10^8" to "3.010^8"
#: (I8 review S2). Excluding a left group with "10" (two digits, not
#: three) or with a decimal point leaves both to implicit multiplication
#: instead, which parses them correctly.
_SPACED_DIGIT_GROUP_RE = re.compile(r"(?<![\d.])(\d+)\s+(\d{3})(?!\d)")

#: A genuine exponent TOWER — `9^9^9`, right-associative chained
#: exponentiation — is two exponent operators with nothing but a NUMERIC
#: operand between them. This must NOT fire on two separate exponentiations
#: in the same expression (`a^2 + b^2` has two `^` but is ordinary algebra,
#: not a tower) — the distinguishing feature of a tower is that no
#: `+`/`-`/`*`/`/` ever separates the two operators, so requiring only an
#: operand between them is what tells the two apart. The operand must be
#: numeric (`[0-9]+`, not `\w+`): a `\w+` version also matches a letter
#: immediately following an exponent with no separator — e.g. `m**2s` in
#: the unfolded form of `m²s⁻²` (a compound SI unit, `m²·s⁻²`) — and
#: rejects legitimate compound-unit notation wholesale (I8 review B4).
_EXPONENT_TOWER_RE = re.compile(r"(?:\*\*|\^)\s*\(?-?[0-9]+\)?\s*(?:\*\*|\^)")

#: A single oversized literal exponent (`2**100000000`) is not a tower but
#: is just as capable of hanging parsing or producing a multi-million-digit
#: integer — see `_MAX_EXPONENT_VALUE`.
_EXPONENT_VALUE_RE = re.compile(r"(?:\*\*|\^)\s*\(?(-?\d+)\)?")


class EquivalenceMethod(StrEnum):
    """How a :class:`Verdict` was reached."""

    SIMPLIFY = "simplify"
    NUMERIC = "numeric"


class VerdictKind(StrEnum):
    """The four possible outcomes of :func:`equivalent`.

    ``EQUAL_PROVEN`` and ``EQUAL_SAMPLED`` are deliberately distinct
    members, not one ``EQUAL`` plus a method field a caller could ignore.
    A round of review found ``Verdict.equal`` collapsing them back into one
    boolean sitting right next to :attr:`Verdict.auto_awardable`, which
    answers the same question differently — a caller writing
    ``if verdict.equal: award()`` silently got the pre-D12 behaviour, with
    no error and nothing to catch it in a type check. Splitting the kind
    is what survives serialisation into review records and harness
    artifacts too, where a computed property does not: a persisted
    ``"equal_sampled"`` says what happened; a persisted ``"equal"`` plus a
    separately-persisted method field can drift apart or get dropped.
    """

    EQUAL_PROVEN = "equal_proven"
    EQUAL_SAMPLED = "equal_sampled"
    NOT_EQUAL = "not_equal"
    UNPARSEABLE = "unparseable"


@dataclass(frozen=True, slots=True)
class Verdict:
    """Result of comparing two expressions.

    ``method`` is ``None`` when ``kind`` is ``UNPARSEABLE`` — no comparison
    was ever attempted, whether because the text could not be read as an
    expression or because *both* comparison methods exhausted their time
    budget (an indeterminate result, which this module treats the same as
    "could not read it" rather than as a disproof — see :func:`equivalent`).
    ``detail`` carries a short, human-readable reason (which side failed to
    parse, the simplified difference, which sample point diverged) for
    logging and for the review-trigger message; it is never required for
    control flow.
    """

    kind: VerdictKind
    method: EquivalenceMethod | None = None
    detail: str | None = None

    @property
    def equal_by_any_method(self) -> bool:
        """Either kind of equal — ``EQUAL_PROVEN`` or ``EQUAL_SAMPLED``.

        Deliberately NOT named ``equal``: that name previously invited
        ``if verdict.equal: award()``, silently including a finite-sample
        match. Use this only where "equal at all, method aside" is
        genuinely the question (e.g. I2's ``expression_exact`` metric,
        which reports agreement, not marks) — an award decision must use
        :attr:`auto_awardable` instead.
        """
        return self.kind in (VerdictKind.EQUAL_PROVEN, VerdictKind.EQUAL_SAMPLED)

    @property
    def auto_awardable(self) -> bool:
        """Whether this verdict alone could justify auto-awarding a mark.

        Only ``EQUAL_PROVEN`` qualifies. ``EQUAL_SAMPLED`` is a
        finite-sample match — evidence of equivalence, not proof (two
        distinct expressions can coincide at finitely many points) — so it
        is a review candidate like any ``not_equal``, never an auto-award,
        per D12. This is a structural rule rather than a convention
        callers must remember to apply.
        """
        return self.kind is VerdictKind.EQUAL_PROVEN


def _unfold_superscripts(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        exponent = match.group(0).translate(_SUPERSCRIPT_TRANSLATE)
        return f"**({exponent})" if exponent[0] in "-+" else f"**{exponent}"

    return _SUPERSCRIPT_RUN_RE.sub(repl, text)


def _looks_like_prose_or_unsafe(text: str) -> bool:
    """Reject mark-scheme prose and unsafe constructs before parsing.

    Applied to the raw, pre-normalisation text (spacing and case matter for
    these patterns) as well as, separately, to the fully normalised text in
    :func:`parse_expr_safe` for the exponent-tower check, which needs
    unicode superscripts already unfolded to `**`.
    """
    if _NOT_AN_ANSWER_RE.search(text):
        return True
    if _MIXED_FRACTION_RE.search(text):
        return True
    calls = _FUNCTION_CALL_RE.findall(text)
    return any(_is_disallowed_sympy_call(name) for name in calls)


def _has_unsafe_exponent(text: str) -> bool:
    if _EXPONENT_TOWER_RE.search(text):
        return True
    for match in _EXPONENT_VALUE_RE.finditer(text):
        try:
            if abs(int(match.group(1))) > _MAX_EXPONENT_VALUE:
                return True
        except ValueError:
            continue
    return False


def _collapse_thousands_separators(text: str) -> str:
    """Collapse "1 500 000" to "1500000", one triple at a time.

    A single substitution pass only removes one space; a value with more
    than one grouped triple ("1 500 000") needs the pass repeated until it
    stops matching, since collapsing the rightmost group changes what
    qualifies as a fresh left-hand run for the next group.
    """
    while True:
        collapsed = _SPACED_DIGIT_GROUP_RE.sub(r"\1\2", text)
        if collapsed == text:
            return collapsed
        text = collapsed


def _normalize_text(text: str) -> str:
    """Rewrite CAIE-style notation into something SymPy's parser accepts.

    Order matters: superscripts must be unfolded before NFKC normalisation
    (see :data:`_SUPERSCRIPT_RUN_RE`'s docstring note above); unit-digit
    splitting must run after multiplication-glyph replacement so a unit
    right after a `×` isn't mistaken for part of the preceding number; the
    thousands-separator collapse runs last of the rewrites, once mixed
    fractions have already been rejected on the original spacing.
    """
    normalized = _unfold_superscripts(text)
    normalized = normalized.replace(_UNICODE_MINUS, "-")
    for ch in _MULT_CHARS:
        normalized = normalized.replace(ch, "*")
    normalized = normalized.replace("÷", "/")
    for alias, canonical in _UNIT_ALIASES.items():
        normalized = normalized.replace(alias, canonical)
    normalized = _UNIT_DIGIT_RE.sub(r"\1**\2", normalized)
    normalized = _collapse_thousands_separators(normalized)
    return normalized.strip()


def _run_bounded[T](func: Callable[[], T], timeout: float) -> T | None:
    """Run ``func`` off-thread, abandoning it past ``timeout``.

    A signal-based timeout (``signal.alarm``) only works on the main thread
    and on POSIX, and this module is called from request-handling code that
    may run on neither. A background thread works everywhere; the abandoned
    worker is not killed (Python cannot forcibly kill a thread) but is left
    to finish on its own, its result discarded.

    Each call gets its OWN thread rather than sharing one module-global
    pool — a shared pool's abandoned workers accumulate and never give
    their slot back, so one pathological input starves every later call
    for as long as that computation keeps running (I8 review MUST-FIX #3:
    measured 89.6s of contagion from a single call at n=60, during which
    even ``equivalent("2+2", "4")`` returned ``not_equal``).

    The thread is started with ``daemon=True`` rather than through a
    ``concurrent.futures.ThreadPoolExecutor``. A pool's workers are NOT
    daemon threads, and ``concurrent.futures.thread`` registers an
    ``atexit`` hook that joins every worker any pool ever started —
    ``executor.shutdown(wait=False)`` returns immediately, but the
    interpreter still blocks on that join at process exit (I8 review B5:
    measured 105.44s of total wall time for a single abandoned call that
    itself returned in 2.05s, with no bound on how many threads accumulate
    across calls). A daemon thread is never joined at exit — it is simply
    not there to wait for — so interpreter shutdown is bounded regardless
    of what this module has abandoned.
    """
    result_queue: queue.Queue[tuple[bool, object]] = queue.Queue(maxsize=1)

    def _worker() -> None:
        try:
            result_queue.put((True, func()))
        except Exception as exc:  # re-raised on the caller's thread below
            result_queue.put((False, exc))

    threading.Thread(target=_worker, daemon=True).start()
    try:
        ok, value = result_queue.get(timeout=timeout)
    except queue.Empty:
        return None
    if not ok:
        raise value  # type: ignore[misc]
    return value  # type: ignore[return-value]


def parse_expr_safe(
    text: str | None, *, timeout: float = _DEFAULT_PARSE_TIMEOUT
) -> sympy.Expr | None:
    """Parse CAIE-style answer text into a SymPy expression, or ``None``.

    Handles plain arithmetic, unicode superscripts/multiplication signs,
    standard-form notation (``3.0×10^8``), simple unit expressions
    (``g/cm3``, ``g cm^-3``), SI-prefixed units (``4.5 mg``), and implicit
    multiplication (``mv^2``, ``0.5mv²``). Never raises — any parse failure
    (empty/prose text, unbalanced notation, an expression too long to be a
    real answer) returns ``None`` rather than propagating a SymPy
    exception, since callers use this on untrusted, free-text student and
    mark-scheme content.

    Also returns ``None`` — deliberately, not a bug — for text this module
    can technically make SymPy accept but must not, because the result
    would be a confident verdict on a meaning nobody wrote: mark-scheme
    prose ("N/A", a range, "±"/"~" tolerance notation), disallowed function
    calls, and exponent towers/oversized literal exponents that have no
    realistic CAIE reading and would otherwise defeat the timeout budget
    below by hanging *parsing* itself. Bounded by ``timeout`` for the same
    reason (I8 review MUST-FIX #9): a handful of characters (``9^9^9``) can
    otherwise run unbounded, or return a valid but multi-million-digit
    integer (``2**100000000``) — both caught by the exponent check above in
    the common case, this is the backstop for whatever it misses.
    """
    if text is None:
        return None
    stripped = text.strip()
    if not stripped or len(stripped) > _MAX_INPUT_LEN:
        return None
    if _looks_like_prose_or_unsafe(stripped):
        return None
    normalized = _normalize_text(stripped)
    if not normalized or _has_unsafe_exponent(normalized):
        return None

    def _parse() -> sympy.Expr:
        return parse_expr(
            normalized,
            transformations=_TRANSFORMATIONS,
            local_dict=dict(_UNIT_LOCAL_DICT),
            evaluate=True,
        )

    try:
        expr = _run_bounded(_parse, timeout)
    except (
        SyntaxError,
        TypeError,
        ValueError,
        AttributeError,
        RecursionError,
        sympy.SympifyError,
    ):
        return None
    if not isinstance(expr, sympy.Basic):
        return None
    return expr


#: Recognised free-text shapes for `CalculatedAnswer.tolerance`
#: (`loose_schemas.py:175`). Checked in this order — percent, then sig-fig
#: wording, then dp wording, then a bare "± N" — because a bare digit-run
#: regex on the raw string cannot tell "allow 10%" from "± 10": both
#: contain the digits "10", but the first is a RELATIVE 10%, and reading it
#: as an absolute window of 10 was a false-equal path (I8 review B1: `31`
#: vs `40` at "allow 10%" was `equal`, 29% out; `0.5` vs `2.4` at "accept
#: to 2 sf" was also `equal`, treating "2 sf" as ±2 absolute).
_PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")

#: ``(?<![\d.])`` on both — without it, `.search` over free text matches the
#: digits AFTER a decimal point: `"2.0 sf"` captured `"0"` as `sig_figs=0`,
#: and `"3.0 dp"` likewise gave `dp=0` (I8 re-review round 4 MUST-FIX 1(a) /
#: SHOULD-FIX 5). The guard requires the captured digit run to start a fresh
#: number, not continue one.
#:
#: The optional ``(?:\.\d+)?`` after the capture group (added I8 re-review
#: round 6 MUST-FIX 4) consumes a trailing decimal part WITHOUT capturing
#: it, rather than leaving it unmatched — the lookbehind alone stopped the
#: WRONG digit (`"0"`) from being captured, but did nothing to make the
#: RIGHT one (`"2"`) match either, so `"2.0 sf"` parsed to no `sig_figs` at
#: all (silently discarding the scheme's stated precision) instead of the
#: `2` it plainly states. `sig_figs`/`dp` are integer counts — "2.0
#: significant figures" and "2 significant figures" mean the same count —
#: so truncating rather than rounding the decimal part is correct, not
#: merely convenient.
_SIG_FIGS_WORD_RE = re.compile(
    r"(?<![\d.])(\d+)(?:\.\d+)?\s*(?:sig(?:nificant)?\s*fig(?:ure)?s?|s\.?\s*f\.?)",
    re.IGNORECASE,
)
_DP_WORD_RE = re.compile(
    r"(?<![\d.])(\d+)(?:\.\d+)?\s*(?:d\.?\s*p\.?|decimal\s*places?)", re.IGNORECASE
)

#: Unanchored (I8 re-review round 3 SHOULD-FIX 3) — the previous ``^...$``
#: anchoring meant any surrounding prose or unit ("allow +/- 0.5", "± 0.5
#: cm") dropped the tolerance to strict, since nothing but "+/- N" ever
#: matched the whole string. Each alternative still requires the ±/+/-
#: MARKER immediately before the number, so a plain percentage or sig-fig/dp
#: digit run is never mistaken for a bare absolute window.
#:
#: Deliberately just the marker-plus-number, with NO trailing lookahead
#: baked into this pattern — see `_DISQUALIFYING_SUFFIX_RE` and its use in
#: `_parse_tolerance` for why. An earlier version embedded
#: `(?!\s*%)(?!\s*squares?\b)...` directly after the number group: with
#: `\d+(?:\.\d+)?` and no anchor forcing the longest match, the engine
#: BACKTRACKS around a failing lookahead by shrinking the number instead of
#: rejecting the match — "± 2.5%" matched "2.5", failed the `(?!\s*%)`
#: lookahead against "%", backtracked `\d+` down to "2", and the lookahead
#: then passed against ".5%" (I8 re-review round 6 MUST-FIX 3: `± 2.5%`
#: read as `absolute=2.0`, a false-equal on ordinary decimal percentages —
#: every round-4 pinned row used an INTEGER percent, the one shape with
#: nothing to backtrack into). Matching the number alone, with disqualification
#: checked as a separate, later regex operation against the fixed end
#: position of an already-complete match, cannot backtrack into the number
#: at all.
_BARE_TOLERANCE_RE = re.compile(r"±\s*(\d+(?:\.\d+)?)|\+\s*/\s*-\s*(\d+(?:\.\d+)?)")

#: Checked against the text starting exactly where a `_BARE_TOLERANCE_RE`
#: match ends — a percent sign or a countable-unit noun right after the
#: number means the number is not an absolute window on the answer (it is
#: a percentage, or a count of grid squares/divisions on a graph). See
#: `_BARE_TOLERANCE_RE`'s docstring for why this is a separate check rather
#: than a lookahead inside that pattern.
#:
#: No leading ``^`` — used with ``.match(text, pos)``, which already
#: anchors the attempt to start exactly at ``pos``; an explicit ``^``
#: asserts "start of the whole string" instead (Python's ``re`` does not
#: reinterpret ``^`` relative to ``pos`` without `re.MULTILINE`), which
#: silently never matches for any ``pos > 0`` and made this check a no-op.
_DISQUALIFYING_SUFFIX_RE = re.compile(
    r"\s*(?:%|(?:small\s+)?squares?\b|(?:division|box|unit|grid)s?\b)"
)

#: A graph/grid-reading allowance ("± 2 cm on the graph", "within one grid
#: square") states a window on the GRAPH, not on the answer, however far
#: the counting noun sits from the number — "± 2 cm on the graph" has a
#: perfectly unit-shaped token (`cm`) immediately after the number, so the
#: positional guard above (which only looks at what's RIGHT after the
#: digits) does not catch it. Checked separately, over the whole string,
#: rather than folded into the positional lookahead.
_GRAPH_OR_GRID_READING_RE = re.compile(r"(?i)\bgraph\b|\bgrid\b")

#: A stated percentage at or above this fraction is a CREDIBILITY boundary,
#: not a precision statement about this answer, and is DISCARDED entirely
#: — never applied, not even capped. Lowered from the round-4 value of 0.5
#: (I8 re-review round 5 SHOULD-FIX 3 — 0.5 was pinned only from above, by
#: "500%"/"100%"; nothing pinned it from below). The judgement behind 0.2,
#: stated so it can be checked rather than merely asserted: no CAIE mark
#: scheme has been observed to state a tolerance anywhere near 20%, so
#: this is roughly 2x headroom on that judgement — it is NOT backed by
#: fixture data, because every "tolerance" key in every golden mark scheme
#: and every `corpus/mark-schemes/*.json` file is `null` (verified: 212
#: keys, 212 nulls, zero non-null — US-028 review). This describes the
#: CORPUS, not reachability: `lemely/io/prompts/mark_scheme_parsing.py`
#: already extracts `sig_figs`, `dp` and `tolerance` in production (its
#: prompt gives literal examples like `"± 0.2"` and `"± 1 mm"`), so a
#: non-null `tolerance` string is live today — the fixture corpus simply
#: happens not to carry one yet, because CAIE rarely states per-answer-
#: point precision in the papers this corpus was built from. "500%"
#: parsing to `relative=5.0` verbatim made a 100%-wrong answer
#: `equal_proven`; at this tighter threshold, `tolerance="allow 49%"`
#: (45% off) is also rejected as a MARKING TOLERANCE rather than merely
#: the pathological cases — the answer's own 45% error is checked against
#: the strict default, not against the 49% the string stated. This same
#: 0.2 ceiling is also applied to a STATED ABSOLUTE tolerance (a bare
#: "± N") before it ever reaches `_plausible_or_discard_absolute_candidate`
#: — see the credibility test in `_ToleranceSpec.for_magnitude` — because
#: "± 50" on a ref of 100 and "50%" on the same ref are the same claim in
#: different units and must be judged identically (I8 re-review round 7).
#:
#: DISCARDED, not capped, above the threshold (I8 re-review round 6 —
#: reversed twice this round). A round-6 attempt capped an over-threshold
#: percent to this ceiling instead of discarding it, reasoning that
#: `min(value, cap)` alone is provably monotonic (unlike the absolute/`dp`
#: path, a relative candidate is already SCALED to `ref`, so it has no
#: analogue of the SI-scale mismatch that forces a hard discard tier
#: there) — that IS true, but it misses that capping is itself the wrong
#: reading of an over-threshold value: `"500%"`/`"100%"`/`"50%"` are not
#: credible precision statements about any real answer, and capping them
#: still grants the FULL 20% window on the strength of a field value
#: nobody should believe (`100` vs `115`, a genuine 15% error, became
#: `equal_proven` under `tolerance="50%"`) — award-affecting leniency
#: manufactured from noise. This is the exact class of defect rounds 2-5
#: closed, and it is the mirror image of what the absolute/`dp` path gets
#: right: `_plausible_or_discard_absolute_candidate` treats "not credible"
#: as "no information" and discards to the strict default; the percent
#: path now matches it, for the same reason. The two-sided cliff this
#: reintroduces (`"19%"` grants leniency, `"20%"` grants none) is the same
#: CREDIBILITY boundary as the absolute path's — not a defect to engineer
#: away, but the correct discontinuity at the edge of what a scheme string
#: can be trusted to mean — and is derived and pinned by
#: `test_percent_tolerance_credibility_boundary_is_confined_to_the_discard_threshold`
#: in `tests/test_equivalence.py`, the same way as the absolute path's.
_MAX_PLAUSIBLE_RELATIVE_TOLERANCE = 0.2


@dataclass(frozen=True, slots=True)
class _ParsedTolerance:
    """The shape-aware reading of a scheme's free-text ``tolerance``.

    Every field is ``None`` for unrecognised free text (e.g. "± half a
    small square") — deliberately: an unrecognised tolerance must fall
    back to the strict default, never to a wide absolute one guessed from
    whatever digits happen to appear in the string (I8 review B1).
    """

    absolute: float | None = None
    relative: float | None = None
    sig_figs: int | None = None
    dp: int | None = None


def _parse_tolerance(tolerance: str | None) -> _ParsedTolerance:
    """Read every recognised shape in ``tolerance``, not just the first.

    A string can legitimately carry more than one shape ("± 0.2 to 2 dp",
    "within 2% or 2 dp, whichever is larger") — the previous version
    returned on the first shape it matched, silently discarding whichever
    the mark scheme actually meant to be the wider (more lenient) one (I8
    re-review SHOULD-FIX 2). Populating every field independently and
    letting :meth:`_ToleranceSpec.for_magnitude`'s ``max(candidates)`` pick
    the widest is what "whichever is larger" in the scheme's own wording
    means; a single-shape string is unaffected, since only one field ends
    up set.
    """
    if not tolerance:
        return _ParsedTolerance()
    text = tolerance.strip()

    relative = None
    for percent_match in _PERCENT_RE.finditer(text):
        value = float(percent_match.group(1)) / 100
        if value >= _MAX_PLAUSIBLE_RELATIVE_TOLERANCE:
            continue
        if relative is None or value > relative:
            relative = value

    sig_figs_match = _SIG_FIGS_WORD_RE.search(text)
    sig_figs = int(sig_figs_match.group(1)) if sig_figs_match else None

    dp_match = _DP_WORD_RE.search(text)
    dp = int(dp_match.group(1)) if dp_match else None

    absolute = None
    if not _GRAPH_OR_GRID_READING_RE.search(text):
        for bare_match in _BARE_TOLERANCE_RE.finditer(text):
            if _DISQUALIFYING_SUFFIX_RE.match(text, bare_match.end()):
                continue
            raw = bare_match.group(1) or bare_match.group(2)
            value = float(raw)
            if absolute is None or value > absolute:
                absolute = value

    return _ParsedTolerance(absolute=absolute, relative=relative, sig_figs=sig_figs, dp=dp)


def _plausible_or_discard_absolute_candidate(candidate: float, ref: float) -> float | None:
    """Two-regime treatment for an absolute-shaped tolerance candidate.

    - Within `_ABS_TOLERANCE_DISCARD_MULTIPLE`x of `ref`: PLAUSIBLE — a
      believable, if generous, precision statement about an answer of this
      magnitude ("± 5" on an answer near 9 is a coarse-scale reading, not a
      nonsense one). CAPPED to `_ABS_TOLERANCE_SANITY_FRACTION * ref` — a
      window must never exceed the answer it describes, however plausible
      its raw value looked relative to `ref` (I8 re-review round 6: using
      the raw candidate here unscaled let a window reach `10 * ref`, wide
      enough to tolerate a sign flip or a 100-400% error at ordinary
      magnitude — `2.5` vs `-2.5` at `tolerance="± 5"`, `0.05` vs `0.01` at
      `dp=0`, both confirmed `equal_proven`/`auto_awardable=True`).
    - Beyond that: discarded (returns ``None``) — this is no longer a
      precision statement about `ref` at all, it is a different order of
      magnitude ("2 dp" against `1.6e-19` is not a coarse reading of that
      answer, it is thirty-three orders of magnitude away from it), and
      letting any fraction of it through would still swallow an answer
      that is simply *wrong at this scale* as "noise".

    Capping inside the band rather than using the candidate verbatim does
    NOT reopen the SI-scale guarantee: an implausible candidate (`dp=2`
    against `1.6e-19`, ratio ~3e16) is discarded *before* the cap is ever
    reached, so it never gets even the capped fraction — only a candidate
    already judged plausible is capped, and capping a plausible one to
    `0.5 * ref` still leaves it strictly below `ref`.

    This is a CREDIBILITY boundary, not a continuous "stated tolerance ->
    window" function, and is not held to monotonicity across its whole
    domain (I8 re-review round 6). Within the believed (plausible) regime
    it IS monotonic: `window == min(candidate, cap)`, which is provably
    non-decreasing in `candidate` — the round-6 complaint this function
    was built to fix (`0.09` vs `0.12` was `equal` at the finer `dp=1` but
    `not_equal` at the coarser `dp=0`, backwards) was a cliff INSIDE this
    band, and that is genuinely eliminated: capping instead of using the
    raw candidate makes `min(candidate, cap)` well-behaved throughout.
    What remains is the transition INTO the discard regime: a candidate
    one unit inside the plausible band still gets the full cap, `0.5 *
    ref`, while a candidate one unit past `_ABS_TOLERANCE_DISCARD_MULTIPLE
    * ref` drops straight to `None` (no leniency at all). That is not a
    monotonicity defect to eliminate — a stated tolerance more than 10x
    the answer's own magnitude is not a precision statement about THIS
    answer any more (most plausibly a parse artefact or a misread field),
    and declining to grant leniency from a value that is not credible is
    the correct response, not a bug: "a looser stated tolerance yields
    less leniency" is true and desired once "looser" has crossed into
    "not believable". No choice of the two constants removes this
    transition, and it should not be removed: shrinking
    `_ABS_TOLERANCE_DISCARD_MULTIPLE` only moves the boundary nearer
    `ref`, and replacing the hard discard with a continuous taper down to
    0 turns the single transition into a wider non-monotonic hump instead
    (rises, flattens, then must still fall to 0 somewhere) — worse, not
    better, since it grants partial credit to values already judged not
    credible. Removing the discard tier entirely would reopen the
    original SI-scale MUST-FIX this function exists to satisfy (`1.6e-19`
    vs `1.7e-19` must be `not_equal`; a bare cap-without-discard makes it
    `equal_proven`, checked directly) — not revisited here.

    Reaching this boundary requires a scheme to state a tolerance more
    than `_ABS_TOLERANCE_DISCARD_MULTIPLE`x (10x) the answer's own
    magnitude. Current evidence: no CAIE mark scheme fixture states one at
    all — every "tolerance" key in every golden mark scheme and every
    `corpus/mark-schemes/*.json` file is `null` (verified: 212 keys, 212
    nulls, zero non-null — US-028 review). That is a fact about the
    CORPUS, not about reachability: `lemely/io/prompts/mark_scheme_parsing.py`
    already extracts `sig_figs`, `dp` and `tolerance` in production today
    (its prompt gives `"± 0.2"` and `"± 1 mm"` as literal examples), so a
    non-null value here is live in production — the fixture corpus simply
    has not happened to carry one, because CAIE rarely states per-answer-
    point precision in the papers it was built from. If a real fixture is
    ever observed to produce a value past this boundary, that is the
    trigger to revisit this design, not evidence that it is wrong today.
    `test_dp_tolerance_credibility_boundary_is_confined_to_the_discard_threshold`
    in `tests/test_equivalence.py` derives the boundary programmatically
    (40 orders of magnitude, 5 `ref` scales) and pins that the transition
    occurs at most once, only at the `_ABS_TOLERANCE_DISCARD_MULTIPLE`x
    crossing, and only as a drop to exactly zero — so it cannot silently
    move or widen. The percent path (`_MAX_PLAUSIBLE_RELATIVE_TOLERANCE`)
    has the identical credibility boundary, pinned the same way.

    A STATED absolute tolerance (`tolerance_abs`, a bare "± N") is judged
    by a THIRD regime before it ever reaches this function at all —
    `_ToleranceSpec.for_magnitude` first tests it against
    `_MAX_PLAUSIBLE_RELATIVE_TOLERANCE` (0.2, as a fraction of `ref`), the
    same credibility ceiling the percent path applies to a stated percent
    (I8 re-review round 7), and only a value that PASSES that test is used
    at all — used verbatim, not passed through this function, since a
    value that small relative to `ref` is already inside the plausible-
    and-capped band below with room to spare (`0.2 * ref` is well under
    both the `0.5 * ref` cap and the `_ABS_TOLERANCE_DISCARD_MULTIPLE`x
    threshold). `dp` and `sig_figs` candidates do NOT get that outer test
    and come straight to the two regimes documented above, because they
    are DERIVED rounding windows with an honest meaning at any magnitude,
    not a field value restating a claim about `ref` the way a bare "± N"
    does. So a stated absolute tolerance is judged by three regimes end to
    end: (1) not credible as a fraction of `ref` at all (`> 0.2 * ref`) —
    discarded, without even reaching this function; (2) credible relative
    to `ref`'s own magnitude — used verbatim; there is no separate "capped"
    sub-case reachable from this path, since regime (1) already excludes
    anything the cap would otherwise reduce.

    `dp`/`sig_figs` no longer route through this function at all (I8
    re-review round 10 — see :func:`_precision_candidate_or_discard`):
    a DERIVED quantum is a different kind of value from a STATED tolerance
    whose magnitude cannot otherwise be trusted, and capping it produced a
    uniform, structural 50%-relative-error ceiling across an entire
    decade of magnitudes rather than bounding a pathological outlier.
    This function is retained for its own general two-regime cap/discard
    treatment of a value whose CREDIBILITY (not merely its coherence at
    this scale) is in question, and remains directly unit-tested, but has
    no production caller as of this round.
    """
    if candidate > _ABS_TOLERANCE_DISCARD_MULTIPLE * abs(ref):
        return None
    return min(candidate, _ABS_TOLERANCE_SANITY_FRACTION * abs(ref))


def _precision_candidate_or_discard(candidate: float, ref: float) -> float | None:
    """A `dp`/`sig_figs` quantum, used VERBATIM if coherent, discarded otherwise.

    NOT :func:`_plausible_or_discard_absolute_candidate`'s two-regime
    cap/discard treatment (I8 re-review round 10 ruling, the third
    attempt at this structural question across rounds 7, 8 and 9). That
    function exists to bound a STATED tolerance whose magnitude the
    module cannot otherwise trust, by capping an over-wide-but-not-yet-
    absurd value down to a sane fraction of `ref`. A `dp`/`sig_figs`
    quantum is different in kind: it is a DERIVED window with an exact,
    unambiguous meaning — "correct to N decimal places" IS the claim
    "agrees to within half a unit in the last place", nothing more and
    nothing less — so there is nothing to cap it TO. Capping it anyway
    manufactured a uniform `0.5 * ref` window across the ENTIRE decade of
    magnitudes where the raw quantum merely exceeded `ref` (`ref` to
    `10 * ref`), which is the structural cause of the 50% relative-error
    ceiling rounds 7, 8 and 9 each measured and relocated (by changing
    which specific pair exhibited it) without ever closing it.

    Either the quantum already fits coherently within half the answer's
    own scale (`candidate <= 0.5 * ref`) — used AS-IS, unmodified, since
    below this threshold capping would have been a no-op anyway — or it
    does not, in which case "N decimal places"/"N significant figures" is
    not a coherent precision statement about an answer of THIS magnitude
    at all (the same shape of argument
    `_plausible_or_discard_absolute_candidate` makes one tier further out,
    at 10x, for a value whose CREDIBILITY is in question — here the value
    is fully credible, being a directly-derived quantum, and the only
    question is whether it is coherent at this scale), and it is
    discarded to the strict default rather than capped down to a fraction
    that bears no relationship to what "N places" actually means.

    Reuses `_ABS_TOLERANCE_SANITY_FRACTION` (0.5) as the COHERENCE
    threshold here, not as a cap — the same numeric value, a different
    role: there, values above it get clamped down to it; here, values
    above it get discarded to no leniency at all.

    Two consequences of this rule are ACCEPTED POLICY TRADE-OFFS, ruled on
    by the product owner after three engineering rounds (7, 8 and 9) each
    failed to move the `dp=0` auto-award ceiling off exactly 50%. The
    ruling: A STATED PRECISION DEFINES THE TOLERANCE WINDOW — "correct to N
    decimal places" IS "agrees to within half a unit in the last place",
    and that is the window, not an input to be scaled towards some
    independently-chosen error target. What follows from it is accepted,
    not outstanding:

    - a 50%-relative-error pair IS auto-awardable at the single point
      `ref == 2 * quantum` (`"0.5"` vs `"1.0"` at `dp=0`), where the
      quantum is coherent by a hair and happens to equal half the answer.
      Bounded to that one point per `dp` value, with the measurement, by
      `test_the_dp_ceiling_is_bounded_by_the_coherence_threshold_not_50_
      percent_everywhere`.
    - the verdict RISES once as the stated `dp` gets FINER, across the
      coherence boundary (`"0.09"` vs `"0.12"`: `not_equal` at `dp=0`,
      `equal_proven` at `dp=1`), because a coarser precision's wider
      quantum can be discarded at a magnitude where a finer one's survives.
      Pinned by `test_dp_tolerance_is_monotonic_except_for_the_one_
      documented_coherence_jump`.

    Neither is a defect awaiting a fix, and a later round should not taper
    either away: doing so abandons the ruling above, and the three rounds
    that tried each produced a WIDER 50% band rather than a narrower one.

    DECISIVENESS is a separate question from the window and is not decided
    here — see :func:`_precision_count_is_decisive`. A discarded candidate
    loses its window; it must never thereby lose its count's ROUNDING
    claim, which is what round 10 did (I8 re-review round 11 MUST-FIX 1).
    """
    if candidate > _ABS_TOLERANCE_SANITY_FRACTION * abs(ref):
        return None
    return candidate


def _precision_count_is_decisive(
    raw_candidate: float, ref: float, window: float, explicit: float
) -> bool:
    """Does this `dp`/`sig_figs` count's "N places" wording carry a ROUNDING claim?

    A single precision statement makes two separable claims, and
    :func:`_precision_candidate_or_discard` judges only the first:

    1. a derived WINDOW (`0.5 * 10**-dp`), which is genuinely incoherent
       once it exceeds half the answer's own scale — correctly discarded
       there, since "correct to 2 dp" cannot mean "within ± 0.005" about an
       answer of `1.6e-19`;
    2. a ROUNDING claim (`_round_half_up(a, dp) == _round_half_up(b, dp)`,
       via :func:`_rounds_agree_at_stated_precision`), which is well-defined
       at EVERY magnitude — and in exactly the band where the window is
       discarded (`ref` in `[0.5 * 10**-dp, 10**-dp)`) it is the STRICTEST
       available reading of the scheme's own words, both values being
       sub-quantum: "to 0 dp" there means "both round to the same whole
       number".

    So a discard costs a count its WINDOW and must never also cost it its
    CLAIM. Round 10 gated decisiveness on the window test alone
    (`coherent is not None and coherent == window and coherent > explicit`),
    which dropped (2) along with (1) — and a DIFFERENT, WIDER rule then won
    in its place rather than nothing winning: `"0.45"` vs `"0.5"` at
    `sig_figs=1, dp=0` had `dp=0`'s claim discarded and `sig_figs=1`'s
    substituted for it, and that one passes (both round to `0.5` at 1 s.f.),
    auto-awarding a 10%-relative-error pair — `0` vs `1` at the stated 0 dp,
    a whole unit apart — that the pre-round-10 code refused (I8 re-review
    round 11 MUST-FIX 1: 1,122 such newly-granted, `auto_awardable=True`
    pairs on an 11,520-pair grid, worst case 20%).

    When the window survives, decisiveness is unchanged from round 10: the
    candidate must BE the window and beat `explicit` (see
    :meth:`_ToleranceSpec.stated_precision_bound` for both halves of that
    rule). When it is discarded, the raw candidate is compared against
    `explicit` directly — the same "is the scheme's precision wording
    stricter than anything explicit it stated" question, asked of the value
    the scheme's words actually name. This function decides ONLY
    decisiveness; the window itself is :meth:`_ToleranceSpec.for_magnitude`'s
    and is left exactly as round 10 made it, so restoring the claim does not
    reopen the wide-band 50% ceiling round 10 exists to close.
    """
    coherent = _precision_candidate_or_discard(raw_candidate, ref)
    if coherent is None:
        return raw_candidate > explicit
    return coherent == window and coherent > explicit


@dataclass(frozen=True, slots=True)
class _ToleranceSpec:
    """Every source of scheme-derived leniency, bundled for one comparison.

    ``sig_figs``/``dp`` here are already the EFFECTIVE values — whichever
    of the direct keyword argument or the parsed ``tolerance`` string's
    wording (2.1) won ("explicit argument overrides a parsed string" rather
    than combining both) — computed once in :func:`equivalent`, not
    per-key.
    """

    sig_figs: int | None
    dp: int | None
    tolerance_abs: float | None
    tolerance_rel: float | None
    abs_tol: float
    rel_tol: float

    def for_magnitude(self, ref: float) -> float:
        """The largest difference still considered "the same value" at ``ref``.

        Combines every source of precision this spec carries — the wider
        (more lenient) tolerance wins, since ``sig_figs``, ``dp`` and
        ``tolerance`` are alternative ways a mark scheme expresses the same
        "close enough" allowance, not independent constraints to
        intersect. Falls back to ``rel_tol`` scaled to ``ref`` when the
        scheme specifies nothing — deliberately NOT a flat ``abs_tol``
        floor applied regardless of scale: a fixed 1e-9 floor is
        float-noise-scale at ref ~ 0.3 but is nine orders of magnitude
        *larger* than SI quantities like the elementary charge (~1.6e-19),
        so it would silently swallow a wrong answer at that scale as
        "noise" (I8 review's required row: `1.6e-19` vs `1.7e-19` must be
        `not_equal`). ``abs_tol`` only applies at ``ref == 0``, where a
        relative tolerance is meaningless.

        ``dp``, ``tolerance_abs``, and ``sig_figs`` at its low end (0-1
        significant figures) are ABSOLUTE — a flat window with little or no
        built-in relation to ``ref``, unlike ``tolerance_rel`` and
        ``sig_figs`` at higher precision, which are computed FROM ``ref``
        and so shrink automatically as ``ref`` shrinks. An absolute window
        that is not small relative to the answer's own magnitude cannot be
        a precision statement about that answer: "2 dp" (±0.005) is a
        mantissa-level statement on a normal-sized answer, but applied
        literally to `1.6e-19` it makes ±0.005 — thirty-three orders of
        magnitude larger than the answer — pass as "the same value" (I8
        re-review round 3 MUST-FIX 1). The same is true of `sig_figs=0`:
        its window is `5 * ref` by construction (I8 re-review round 4
        MUST-FIX 1(b)) — five times the answer itself, at ANY magnitude.

        Each absolute-shaped candidate is therefore run through
        :func:`_plausible_or_discard_absolute_candidate`: CAPPED to
        `_ABS_TOLERANCE_SANITY_FRACTION * ref` when it is within
        `_ABS_TOLERANCE_DISCARD_MULTIPLE`x of `ref` (a scheme tolerance
        that is "wide but not absurd" at this magnitude — coarse, not
        incoherent), discarded entirely when it is wildly disproportionate.
        A round-5 version of this rule used a plausible candidate AS-IS
        (unscaled) instead of capping it, reasoning that capping an
        IMPLAUSIBLE candidate (`dp=2` against `1.6e-19`, capped to `8e-20`)
        still passes its `1e-20` diff as `equal` — true, but the fix for
        that is the discard tier above it, not removing the cap from the
        plausible tier too. Using a plausible candidate as-is meant a
        window could reach `10 * ref`; since `|a - b| <= 2 * ref` always
        for two values of that magnitude, a window that size tolerates
        ANY difference between them, sign flip included (I8 re-review
        round 6, MUST-FIX 2: `2.5` vs `-2.5` at `tolerance="± 5"` was
        `equal_proven`/`auto_awardable=True`). Capping keeps the window
        strictly below `ref` in both tiers — plausible-and-capped, or
        discarded outright — which is what the SI-scale guarantee actually
        requires: not merely "never apply an ASTRONOMICALLY oversized
        candidate", but "never let the window exceed the answer itself".

        This still has a discontinuity at the `_ABS_TOLERANCE_DISCARD_
        MULTIPLE`x boundary — this is the CREDIBILITY boundary
        `_plausible_or_discard_absolute_candidate` documents, not a defect
        to taper away; moving from "not credible, discarded" (window ~ the
        tiny default) to "credible, capped" (window up to `0.5 * ref`) as
        a candidate's ratio to `ref` crosses that boundary is necessarily a
        jump. For a `dp` sweep at a FIXED `ref`, this is usually
        unobservable (dp's raw candidate shrinks monotonically as `dp`
        increases, so once `dp=k` lands inside the plausible band every
        finer `dp` does too, each capped to the SAME `0.5 * ref` ceiling —
        no reordering among them). It can still produce a step exactly
        where a `ref` places two ADJACENT `dp` values on opposite sides of
        the boundary (I8 re-review round 5 SHOULD-FIX 1, round 6) —
        confirmed to require a stated tolerance over 10x the answer's own
        magnitude, which no observed CAIE fixture states (see
        `_plausible_or_discard_absolute_candidate`'s docstring for the
        evidence and the derived, pinned test).

        A STATED absolute tolerance (`tolerance_abs`) additionally passes
        through one more, EARLIER gate that `dp` and `sig_figs` never see:
        it must first be no more than `_MAX_PLAUSIBLE_RELATIVE_TOLERANCE`
        (0.2) of `ref`, the identical credibility ceiling the percent path
        applies to a stated percent, before it is used at all (I8
        re-review round 7). Without this, "± 50" and "50%" on the same
        ref-100 pair disagreed — the percent was discarded by that
        ceiling while the identical-in-substance absolute value survived
        to the cap/discard pair above and was capped to `0.5 * ref`,
        five times more lenient than the percent path allowed for the
        same claim. `dp`/`sig_figs` are exempt because they are DERIVED
        rounding windows, not a restatement of a fraction of `ref` the
        way a bare "± N" is — see
        :func:`_plausible_or_discard_absolute_candidate`'s docstring for
        the full three-regime breakdown this produces for `tolerance_abs`.

        `sig_figs` at 0 is additionally rejected outright, before this
        function ever sees a candidate for it — see the explicit `>= 1`
        guard below (I8 re-review round 4 MUST-FIX 1(b) — matches the
        `ge=1` `CalculatedAnswer.sig_figs` already enforces upstream, so a
        caller going through the schema cannot even construct a "0
        significant figures" request the way it can construct an oversized
        `dp`/`tolerance` string).
        """
        if ref == 0:
            return self.abs_tol
        candidates = [self._explicit_window(ref)]
        if self.sig_figs is not None and self.sig_figs >= 1:
            coherent = _precision_candidate_or_discard(self._sig_figs_candidate(ref), ref)
            if coherent is not None:
                candidates.append(coherent)
        if self.dp is not None:
            coherent = _precision_candidate_or_discard(self._dp_candidate(ref), ref)
            if coherent is not None:
                candidates.append(coherent)
        return max(candidates)

    def _sig_figs_candidate(self, ref: float) -> float:
        """The raw (uncapped, undiscarded) `sig_figs` window candidate at `ref`.

        Callers only ever call this when `self.sig_figs` is set.
        """
        sig_figs = self.sig_figs
        if sig_figs is None:
            raise ValueError("_sig_figs_candidate requires sig_figs to be set")
        exponent = math.floor(math.log10(abs(ref)))
        return float(0.5 * 10 ** (exponent - sig_figs + 1))

    def _dp_candidate(self, ref: float) -> float:
        """The raw (uncapped, undiscarded) `dp` window candidate — independent of `ref`.

        Callers only ever call this when `self.dp` is set.
        """
        dp = self.dp
        if dp is None:
            raise ValueError("_dp_candidate requires dp to be set")
        return float(0.5 * 10**-dp)

    def _explicit_window(self, ref: float) -> float:
        """The tolerance window with `sig_figs`/`dp` entirely excluded.

        The float-noise-scale `rel_tol` default, plus any credible
        explicit `tolerance_abs`/`tolerance_rel`.

        The single source of truth :meth:`for_magnitude` and
        :meth:`stated_precision_bound` both build on: `for_magnitude`
        widens it with `sig_figs`/`dp`; `stated_precision_bound` compares
        against it to decide whether either of those is actually the
        window's decisive source, or merely a claim this explicit,
        EXPLICITLY-stated window already subsumes.

        A STATED absolute tolerance ("± N") is a direct restatement of
        the same claim a stated PERCENT makes, just in different units,
        and must be believed to the same degree
        (`_MAX_PLAUSIBLE_RELATIVE_TOLERANCE`, 0.2) — I8 re-review round 7
        MUST-FIX: without this test, "± 50" on a ref of 100 (50% of the
        answer) survived to the existing 10x-discard tier and was CAPPED
        to `0.5 * ref`, while "50%" on the same pair was DISCARDED
        outright by `_MAX_PLAUSIBLE_RELATIVE_TOLERANCE` itself — the same
        claim, judged two different ways depending only on which units
        the scheme happened to use ("allow 50% (± 50)" bypassed the
        percent discard entirely via its parenthetical absolute
        restatement). Once a stated value passes this gate it is by
        construction already inside `_plausible_or_discard_absolute_
        candidate`'s plausible-and-capped band (0.2 * ref < 0.5 * ref ==
        the cap, and 0.2 * ref is nowhere near the 10x discard multiple),
        so it is used verbatim rather than passed through that function
        again. `dp` and `sig_figs` do NOT get this test: they are DERIVED
        rounding windows with an honest meaning at any magnitude ("2 dp"
        is a claim about counting decimal places, not a restatement of a
        fraction of `ref`), not a field value whose credibility as a
        fraction of the answer is in question the way a bare stated
        tolerance's is — they are excluded from this method entirely and
        keep going through the existing cap/discard machinery in
        :meth:`for_magnitude`, untouched.
        """
        candidates = [self.rel_tol * abs(ref)]
        if (
            self.tolerance_abs is not None
            and self.tolerance_abs <= _MAX_PLAUSIBLE_RELATIVE_TOLERANCE * abs(ref)
        ):
            candidates.append(self.tolerance_abs)
        if self.tolerance_rel is not None:
            candidates.append(self.tolerance_rel * abs(ref))
        return max(candidates)

    def stated_precision_bound(self, ref: float) -> tuple[int | None, int | None]:
        """Which of ``sig_figs``/``dp``, if either, decided the window.

        Whichever field's own candidate is STRICTLY WIDER than
        :meth:`_explicit_window` (the ``rel_tol`` default, or a credible
        explicit ``tolerance_abs``/``tolerance_rel``) — not merely tied
        with it. A scheme stating `"± 0.2 to 2 dp"` means the 2 dp is a
        DISPLAY precision and ± 0.2 is the real, wider, deliberately
        generous window — `for_magnitude` already picks ± 0.2 as the
        winner (I8 re-review round 6 SHOULD-FIX 2, "widest shape wins"),
        and the rounding-agreement claim must not override that explicit
        generosity by re-imposing the narrower 2 dp reading underneath
        it. Only when a precision COUNT (`sig_figs`/`dp`) is ITSELF wider
        than every explicit statement does its "N figures" wording get
        taken literally as a rounding claim rather than only a window
        width (I8 re-review round 7 item 7).

        STRICT, not `>=` (I8 re-review round 9 SHOULD-FIX 1c): an EXACT
        tie between a precision candidate and the explicit window used to
        make BOTH count as decisive, which is a float-equality cliff — two
        schemes stating materially the same allowance (`"± 0.005 to 2
        dp"` vs `"± 0.0051 to 2 dp"`, ref 31) got opposite verdicts
        depending on which side of an exact tie the parsed float landed.
        Resolving every tie in favour of the EXPLICIT statement (`>`,
        never `>=`) moves the boundary one step, and gives it a
        DIRECTION worth having (favouring the scheme's own explicit
        wording over an incidental tie) — it does NOT make the rule
        continuous (I8 re-review round 9 MUST-FIX 2 correction: an
        earlier version of this docstring claimed it did). The verdict
        still flips as the stated tolerance crosses the precision
        candidate; the step merely sits at a different, now award-
        SAFER, exact float value (`"± 0.0049 to 2 dp"` vs `"± 0.005 to 2
        dp"`, one epsilon lower than before) — two schemes stating
        materially the same allowance can still land on opposite sides of
        it. Pinned directly by
        `test_decisiveness_tie_break_favours_the_explicit_tolerance_at_
        an_exact_tie`.

        If both `sig_figs` and `dp` are stated and BOTH tie the actual
        window (equal to each other and to `window`, both strictly wider
        than `explicit`), `_rounds_agree_at_stated_precision` requires
        agreement on both — genuinely rare (a scheme stating both, with
        neither reducible to the other, and their raw candidates
        happening to coincide), but a real double claim when it happens.
        The ordinary case is that only ONE of them achieves `window` at
        all — the other, NARROWER field is pure display precision with NO
        rounding claim enforced, however wide its own candidate is
        relative to `explicit` — `_rounds_agree_at_stated_precision`'s own
        docstring states this plainly rather than claiming both fields
        always apply together. "Narrower" is load-bearing: a field whose
        candidate is WIDER than the window only because its window was
        discarded as incoherent is not display precision, and does keep its
        claim (see the note further down).

        NOTE — the explicit window itself can be produced by NOTHING the
        scheme stated at all: at large `|ref|` (`|ref| > 5e8 * 10**-dp`),
        `rel_tol * |ref|` alone already exceeds `dp`'s candidate, so it
        wins by default and `dp` is silently non-decisive there too —
        immaterial in practice (the surviving window is float-noise-scale
        relative to `ref`), but real, and this is where it is checked.
        This is a `dp`-ONLY regime, NOT "similarly for `sig_figs`" (I8
        re-review round 9 SHOULD-FIX 5, a correction to an earlier draft
        of this note): `dp`'s candidate is a FIXED absolute value
        (`0.5 * 10**-dp`, independent of `ref`), so a large enough `ref`
        eventually swamps it; a `sig_figs` candidate is *proportional* to
        `ref` (`0.5 * 10**(1-sf)/m * ref`), so there is no large-`ref`
        regime for it at all — measured across exponents -300..+308 and
        every mantissa, `sig_figs` in `1..8` is decisive at every
        magnitude, `sig_figs=9` is mantissa-dependent, and `sig_figs>=10`
        is decisive at no magnitude — a `sig_figs`-VALUE cutoff, not a
        magnitude-dependent one.

        A field whose derived WINDOW was discarded as incoherent at this
        magnitude (:func:`_precision_candidate_or_discard`) is still
        decisive: the discard costs it its window, never its "N places"
        ROUNDING claim, which is well-defined at every magnitude and is the
        strictest available reading of the scheme's words precisely in that
        band. :func:`_precision_count_is_decisive` holds both halves of
        that rule, and its docstring carries the measured consequence of
        conflating them (I8 re-review round 11 MUST-FIX 1). This is also
        why BOTH fields can come back set here without their candidates
        coinciding: `sig_figs` can hold the window while a discarded `dp`
        holds a stricter claim over it.
        """
        if ref == 0:
            return (None, None)
        # `window` (the true max, matching `for_magnitude`) picks out which
        # field actually SET the window when sig_figs and dp are both
        # stated and unequal — only the one achieving the max is decisive,
        # never both merely for both exceeding `explicit`. `> explicit`
        # (not `>=`) is the round-9 tie-break: a field tying `explicit`
        # achieved the window too, but must not count as decisive over it.
        # Both clauses live in `_precision_count_is_decisive`, alongside the
        # discarded-window case they do not apply to.
        window = self.for_magnitude(ref)
        explicit = self._explicit_window(ref)
        sig_figs_bound = None
        if (
            self.sig_figs is not None
            and self.sig_figs >= 1
            and _precision_count_is_decisive(self._sig_figs_candidate(ref), ref, window, explicit)
        ):
            sig_figs_bound = self.sig_figs
        dp_bound = None
        if self.dp is not None and _precision_count_is_decisive(
            self._dp_candidate(ref), ref, window, explicit
        ):
            dp_bound = self.dp
        return (sig_figs_bound, dp_bound)

    def restricted_to_default(self) -> _ToleranceSpec:
        """Strip every scheme-derived allowance, keeping only the float-noise-scale defaults.

        Used for a diff term the scheme's tolerance does not apply to —
        see :func:`_key_present_on_both_sides`.
        """
        return _ToleranceSpec(None, None, None, None, self.abs_tol, self.rel_tol)


def _key_present_on_both_sides(
    key: sympy.Expr, a_terms: dict[sympy.Expr, sympy.Expr], b_terms: dict[sympy.Expr, sympy.Expr]
) -> bool:
    """Is this term's non-numeric factor eligible for scheme leniency?

    A mark scheme's ``sig_figs``/``dp``/``tolerance`` is a statement about
    the PRECISION of a numeric or unit-bearing answer — "0.333 vs 1/3 is
    fine at 3sf", "(0.1+0.2) m vs 0.3 m is float noise on the same unit".
    It is not a licence to ignore an extra algebraic term nothing in the
    mark scheme accounts for: ``(a+b)**2`` vs ``a**2+b**2`` is missing a
    ``2*a*b`` term, and ``sin(x)**2+cos(x)**2+0.4*y`` vs ``1`` has a stray
    ``0.4*y`` term neither operand's other form shares — nothing about
    "correct to 2 dp" makes either of those the same answer (I8 review
    B2).

    An earlier version of this check restricted leniency to the pure-number
    term (``key == 1``) and to keys whose free symbols were all recognised
    units. That makes eligibility depend on variable NAMES — but the parser
    gives a unit symbol (``m``, ``s``, ``T``) and an ordinary algebra
    variable the SAME kind of ``Symbol``, with no tag distinguishing them.
    275 unit-family names (every SI prefix × base combination, including
    every common CAIE physics variable letter — ``A C F H J K L N T V W g
    l m s Ω``) therefore bypassed the whole check: ``1.5*m + 100`` vs
    ``100`` at ``tolerance="± 2"`` was `equal_proven`/`auto_awardable=True`
    while the structurally identical ``1.5*x + 100`` correctly was not (I8
    re-review MUST-FIX 2). It also reopened round 1's unit-confusion
    mechanism whenever any scheme tolerance was present: ``0.19 cm`` vs
    ``0.19 mm`` (a 10x unit error) at ``dp=0`` was `equal_proven`.

    The discriminator that does not depend on what a symbol is CALLED is
    whether the term is present, with a nonzero coefficient, on BOTH sides
    — a term missing from one side entirely is a missing/extra term, not a
    rounding difference on a shared quantity, regardless of whether that
    term happens to be unit-shaped.

    This applies to the pure-number term (``key == 1``) exactly the same
    as to any other key — an earlier version exempted it unconditionally,
    which was safe only as long as every absolute-shaped tolerance
    candidate was bounded below ``ref`` (round 4's presence-check design).
    Once a plausible candidate could reach `ref` itself, the exemption
    stopped being safe: ``"x + 5"`` vs ``"x"`` at ``tolerance="± 5"`` has a
    one-sided constant term (present in `a`, absent from `b`) that the
    unconditional exemption still called eligible, making a WHOLE MISSING
    TERM `equal_proven`/`auto_awardable=True` (I8 re-review round 6
    MUST-FIX 1) — the exact defect this function exists to prevent for
    every other kind of term. ``"31 + 5"`` vs ``"31"`` at the same
    tolerance correctly stays eligible under the general rule: there the
    constant is present on both sides (36 and 31), so it is a genuine
    precision comparison, not a missing term.
    """
    return bool(a_terms.get(key)) and bool(b_terms.get(key))


def _magnitude(value: sympy.Expr) -> float | None:
    try:
        return abs(complex(value.evalf()))
    except TypeError:
        return None


def _real_value(value: sympy.Expr) -> float | None:
    """The actual signed value of ``value``, for rounding.

    Not its magnitude — :func:`_magnitude` deliberately discards sign,
    since it only ever feeds a scale factor. ``None`` when it cannot be
    evaluated to a number at all, so the caller can defer to the window
    check alone rather than manufacture a spurious rejection.
    """
    try:
        return complex(value.evalf()).real
    except TypeError:
        return None


def _round_half_up(value: float, ndigits: int) -> float:
    """Round ``value`` to ``ndigits`` decimal places, HALF-UP.

    Ties away from zero — not Python's builtin ``round()``, which is
    half-to-even. A CAIE mark scheme's "N decimal places" or "N
    significant figures" means the everyday half-up convention, not
    banker's rounding — the two diverge only at an exact midpoint, and
    switching the convention closes exactly those midpoint cases (I8
    re-review round 9 SHOULD-FIX 2b). It does NOT, by itself, touch the
    module's separate 50%-relative-error `dp` ceiling: that ceiling comes
    from the WINDOW (how far apart two values may be at all), not from
    which rounding convention is applied to values already inside that
    window, and round 9's half-up switch left it exactly where round 7
    measured it (`"0.25"` vs `"0.5"` at `dp=0`, still 50% under
    half-to-even AND half-up alike — round 9 only moved which pair
    exhibited it, from `"1.0"`/`"1.5"` to `"0.25"`/`"0.5"`). Closing the
    WINDOW-side 50% ceiling needed a separate, structural change — see
    `_precision_candidate_or_discard` (I8 re-review round 10) — and even
    that change does not remove the ceiling NUMBER, only the WIDE BAND of
    magnitudes across which it was reachable; see
    `test_the_dp_ceiling_is_bounded_by_the_coherence_threshold_not_50_
    percent_everywhere` for the measured, current picture.

    Goes through ``Decimal(repr(value))`` rather than ``Decimal(value)``:
    ``repr`` gives the shortest decimal string that round-trips to this
    float, i.e. the decimal a person actually typed or a scheme actually
    states; ``Decimal(value)`` would instead expose the float's exact
    (and often non-terminating-looking) binary value, which can put a
    value that is not actually at a midpoint onto the wrong side of one.
    """
    quantum = Decimal(1).scaleb(-ndigits)
    return float(Decimal(repr(value)).quantize(quantum, rounding=ROUND_HALF_UP))


def _round_to_sig_figs(value: float, sig_figs: int) -> float:
    """Round ``value`` to ``sig_figs`` significant figures.

    Uses the identical magnitude convention `_ToleranceSpec.for_magnitude`'s
    `sig_figs` candidate already uses (`exponent = floor(log10(abs(ref)))`),
    so "does this round to the same N sig figs" and "is this within N sig
    figs' worth of window" agree on what N sig figs means for this value.
    Rounds HALF-UP via :func:`_round_half_up` — see its docstring.
    """
    if value == 0:
        return 0.0
    exponent = math.floor(math.log10(abs(value)))
    return _round_half_up(value, sig_figs - 1 - exponent)


def _rounds_agree_at_stated_precision(
    a_val: float | None, b_val: float | None, sig_figs: int | None, dp: int | None
) -> bool:
    """Do ``a_val`` and ``b_val`` round to the same figure at the stated precision?

    The actual values, not their difference — at the precision the
    scheme's own words state. ``sig_figs``/``dp`` here are the DECISIVE bound from
    :meth:`_ToleranceSpec.stated_precision_bound`, not the spec's raw
    fields — a field the scheme stated but that lost to a wider explicit
    tolerance carries no rounding claim (see that method's docstring).

    `_ToleranceSpec.for_magnitude`'s tolerance WINDOW answers "how far
    apart may two values be and still count as the same" — a necessary
    but not SUFFICIENT reading of "N significant figures" or "N decimal
    places". Two values can sit inside that window and still round to
    DIFFERENT figures if they straddle a rounding midpoint: `9` and
    `13.95` are both within `sig_figs=1`'s window of each other (a window
    is a symmetric distance, not a rounding rule), but round to `9` and
    `10` — not "the same value to 1 significant figure" by any reading of
    the phrase. At `sig_figs >= 2` or `dp >= 1` the resulting
    misjudgement is one unit in the last place and immaterial; at
    `sig_figs = 1` or `dp = 0` it is a whole significant figure or whole
    unit — measured up to 86% relative error auto-awarded before this
    check existed (I8 re-review round 7 item 7: `sig_figs=1` alone
    auto-awarded 176 differently-rounding pairs across a grid; `dp=0` had
    the identical defect, e.g. `"1.0"` vs `"1.5"`, a 50% error).

    This is therefore an ADDITIONAL, STRICTER, necessary condition
    alongside the window — never a replacement for it, and never more
    lenient than it: it can turn a window-admitted `equal` into
    `not_equal`, never the reverse. Checked only for the fields the scheme
    states as a precision COUNT (`sig_figs`/`dp` — not
    `tolerance_abs`/`tolerance_rel`, which already state a window directly
    and have no "N figures" reading to hold values to).

    An earlier version of this paragraph went on to conclude that this
    check therefore "cannot manufacture leniency, only remove a false
    one". That is true of this FUNCTION and false of the SYSTEM, and the
    difference is not academic (I8 re-review round 11 MUST-FIX 1): the
    check's strictness is only ever applied to the arguments it is GIVEN,
    so a change upstream that makes a stated field arrive here as `None`
    where it previously arrived set removes a rejection — real, measured
    leniency, arriving through this function's caller rather than through
    this function. That is exactly how round 10 newly auto-awarded pairs
    the code had refused. Any claim about the direction of a change must
    therefore be measured on
    :meth:`_ToleranceSpec.stated_precision_bound`'s OUTPUT, never argued
    from this function's body — see
    `test_no_new_auto_award_on_a_grid_that_reaches_the_discarded_dp_band`.

    ``sig_figs`` and ``dp`` are NOT independently "both must agree" here
    in the way an earlier version of this docstring claimed — that claim
    was false as implemented (I8 re-review round 9 item 1d): the caller
    (:meth:`_ToleranceSpec.stated_precision_bound`) already resolves which
    field, if either, is decisive, and passes `None` for the other.
    Ordinarily at most one arrives set. Both arrive set in two cases, and
    only then does agreement on both apply: when both tie the same decisive
    window, and when one field holds the window while the OTHER's window
    was discarded as incoherent at this magnitude but keeps its rounding
    claim (I8 re-review round 11 MUST-FIX 1 — see
    :func:`_precision_count_is_decisive`).

    Rounds HALF-UP (away from zero at an exact midpoint), not Python's
    default half-to-even: a CAIE mark scheme's "N significant figures" or
    "N decimal places" means half-up (I8 re-review round 9 SHOULD-FIX
    2b). This closes the midpoint-rounding cases specifically, but does
    NOT by itself touch the separate, WINDOW-side 50%-relative-error `dp`
    ceiling — that is a property of `_ToleranceSpec.for_magnitude`'s
    window, not of which convention rounds a value already inside it; see
    :func:`_round_half_up` and `_precision_candidate_or_discard` (I8
    re-review round 10) for what does and does not move that ceiling.

    Returns ``True`` (no additional constraint) when neither field is
    set, or when either value could not be evaluated to a real number —
    rounding is then undefined, so this defers to the window check alone
    rather than manufacturing a spurious rejection.
    """
    if sig_figs is None and dp is None:
        return True
    if a_val is None or b_val is None:
        return True
    if dp is not None and _round_half_up(a_val, dp) != _round_half_up(b_val, dp):
        return False
    if sig_figs is not None:
        return _round_to_sig_figs(a_val, sig_figs) == _round_to_sig_figs(b_val, sig_figs)
    return True


def _split_terms(expr: sympy.Expr) -> dict[sympy.Expr, sympy.Expr]:
    """Group an expanded expression's terms by their non-numeric factor.

    ``3*x + 2*x`` and ``0.1*m + 0.2*m`` both collapse to one entry keyed by
    the symbolic part (``x``, ``m``) with the numeric coefficients summed —
    this is what lets tolerance be applied per physical quantity rather
    than to an expression as an indivisible whole.
    """
    terms: dict[sympy.Expr, sympy.Expr] = {}
    for term in sympy.Add.make_args(sympy.expand(expr)):
        coeff, rest = term.as_coeff_Mul()
        terms[rest] = terms.get(rest, sympy.Integer(0)) + coeff
    return terms


def _diff_within_tolerance(
    diff: sympy.Expr,
    expr_a: sympy.Expr,
    expr_b: sympy.Expr,
    spec: _ToleranceSpec,
) -> bool:
    """Is ``diff`` (= ``expr_a - expr_b``, already simplified) close to zero?

    An exact zero (after expansion) is always ``True`` — that covers every
    purely algebraic identity (``(a+b)**2`` vs its expansion, trig
    identities `simplify` resolves outright) with no tolerance involved.
    Otherwise each term of ``diff`` is compared against a tolerance scaled
    to *that term's own* magnitude in ``expr_a``/``expr_b`` — so
    ``(0.1 + 0.2) m`` vs ``0.3 m`` (float noise on a unit-bearing
    expression) passes. The scheme's ``spec`` only applies to a term whose
    key is eligible (:func:`_key_present_on_both_sides` — present, with a
    nonzero coefficient, in both operands) — an ineligible key (e.g. the
    ``a*b`` cross-term missing from ``a**2+b**2``, or a stray algebraic
    ``y`` term) is checked against ``spec.restricted_to_default()`` instead,
    regardless of how wide the scheme's own tolerance is (I8 review B2 — a
    numeric precision field must not license a whole missing or extraneous
    algebraic term; that is a different, larger kind of "not the same
    answer" than a rounding difference).

    A term whose key is eligible ALSO has to agree with the other side
    once rounded to whatever precision the scheme states
    (:func:`_rounds_agree_at_stated_precision`) — the window above answers
    "close enough", not "the same to N figures", and those diverge exactly
    at `sig_figs=1`/`dp=0` (I8 re-review round 7 item 7).
    """
    expanded = sympy.expand(diff)
    if expanded == 0:
        return True
    a_terms = _split_terms(expr_a)
    b_terms = _split_terms(expr_b)
    for key, coeff in _split_terms(expanded).items():
        magnitude = _magnitude(coeff)
        if magnitude is None:
            return False
        a_term = a_terms.get(key, sympy.Integer(0))
        b_term = b_terms.get(key, sympy.Integer(0))
        ref = max(_magnitude(a_term) or 0.0, _magnitude(b_term) or 0.0)
        eligible = _key_present_on_both_sides(key, a_terms, b_terms)
        effective_spec = spec if eligible else spec.restricted_to_default()
        if magnitude > effective_spec.for_magnitude(ref):
            return False
        sig_figs_bound, dp_bound = effective_spec.stated_precision_bound(ref)
        if not _rounds_agree_at_stated_precision(
            _real_value(a_term), _real_value(b_term), sig_figs_bound, dp_bound
        ):
            return False
    return True


def _values_within_tolerance(av: complex, bv: complex, spec: _ToleranceSpec) -> bool:
    """Is ``|av - bv|`` within the scheme's tolerance WINDOW at this magnitude?

    Deliberately window-only — no rounding-agreement check
    (:func:`_rounds_agree_at_stated_precision`) here (I8 re-review round 9
    MUST-FIX 1, a design ruling, not a test gap). This function is called
    both for the ACTUAL final answer (no free symbols — see
    :func:`_numeric_fallback`'s first branch, which applies the rounding
    check itself, once, there) and for arbitrary SAMPLE POINTS probing an
    algebraic identity's equivalence, which are not the answer at all. A
    scheme stating "2 sf"/"0 dp" is a claim about the answer's own
    precision, not about eight arbitrary values an expression happens to
    take — applying the rounding check here made it run once per sample
    point with "any single disagreement loses", which is both a stronger
    claim than the window ever made and one whose outcome depends on
    where the (seeded, but otherwise arbitrary) sample points happened to
    land: the same marking question, scaled by an arbitrary coefficient
    (`1000*x` vs `1000*x + 0.3`, `dp=0`), went from uniformly `equal` to
    `not_equal` at 7 of 10 tested coefficients — and the result was
    `NOT_EQUAL`, not a review flag, since `EQUAL_SAMPLED` is never
    `auto_awardable` — mark-lowering with no human in the loop, driven by
    sampling position rather than anything about the answer.
    """
    ref = max(abs(av), abs(bv))
    return abs(av - bv) <= spec.for_magnitude(ref)


def _sample_point(rng: random.Random) -> float:
    """A point spanning several decades of magnitude and either sign.

    Fixed points in ``[0.5, 5.0]`` (the module's first cut) miss anything
    that only diverges at zero, at a negative argument, or at a different
    scale — confirmed false ``equal`` for ``sqrt(x**2)`` vs ``x`` (they
    agree for every positive `x`) and for an expression hand-constructed to
    vanish exactly on that range (I8 review mechanism 3).
    """
    magnitude = 10 ** rng.uniform(-3, 3)
    return magnitude if rng.random() < 0.5 else -magnitude


def _sampler_seed(a: sympy.Expr, b: sympy.Expr) -> int:
    """A seed derived from the two expressions being compared, not fixed.

    A single fixed seed (this module's first cut) makes the "random"
    sample points fully predictable for every comparison — a crafted
    expression can be built to agree with the reference at exactly those
    points and disagree everywhere else, and it generalises to every other
    comparison forever, since the points never change (I8 review mechanism
    3). An UNSEEDED sampler (the module's second cut) closes that hole but
    trades it for run-to-run nondeterminism: measured 6 flips in 2000
    repetitions of the IDENTICAL input (`sqrt(x**2)` vs `x`). Review
    routing keys on `kind`, so a flipped verdict changes whether a mark is
    withheld and pollutes the A/A churn floor the next story measures —
    indistinguishable from model drift (I8 re-review 2.1).

    Seeding from a hash of both expressions' `srepr` gives exact
    determinism (the same pair always samples the same points, so the same
    pair always gets the same verdict) while still defeating the
    fixed-point-set attack, since the points now differ per PAIR rather
    than being the same set for every comparison this module ever makes.

    The two `srepr`s are sorted before hashing so the seed — and therefore
    the verdict — is the same regardless of which operand is passed as `a`
    and which as `b` (equivalence is symmetric; the seed should be too).
    """
    payload = "|".join(sorted((sympy.srepr(a), sympy.srepr(b)))).encode()
    return int.from_bytes(hashlib.blake2b(payload, digest_size=8).digest(), "big")


def _numeric_fallback(
    a: sympy.Expr, b: sympy.Expr, timeout: float, spec: _ToleranceSpec
) -> tuple[bool, str] | None:
    """Compare ``a`` and ``b`` at random points instead of simplifying.

    Returns ``(equal, detail)``, or ``None`` if the fallback itself could
    not complete within ``timeout`` (in which case the caller must not
    claim any verdict from it — see :func:`equivalent`).
    """

    def _compare() -> tuple[bool, str]:
        symbols = sorted(a.free_symbols | b.free_symbols, key=lambda s: s.name)
        if not symbols:
            try:
                av = complex(a.evalf())
                bv = complex(b.evalf())
            except TypeError:
                return False, "non-numeric constant expressions"
            equal = _values_within_tolerance(av, bv, spec)
            if equal:
                # A concrete final-answer comparison (no free symbols) —
                # the one place on this path where "the answer's own
                # precision" actually means something, so the
                # rounding-agreement check applies HERE, once, rather than
                # per sample point (see `_values_within_tolerance`'s
                # docstring for why not there; I8 re-review round 9
                # MUST-FIX 1).
                ref = max(abs(av), abs(bv))
                sig_figs_bound, dp_bound = spec.stated_precision_bound(ref)
                equal = _rounds_agree_at_stated_precision(
                    av.real, bv.real, sig_figs_bound, dp_bound
                )
            return equal, f"|{av} - {bv}| {'<=' if equal else '>'} tolerance"

        rng = random.Random(_sampler_seed(a, b))
        for _ in range(_NUMERIC_SAMPLE_POINTS):
            point = {s: _sample_point(rng) for s in symbols}
            try:
                av = complex(a.evalf(subs=point))
                bv = complex(b.evalf(subs=point))
            except TypeError:
                return False, "could not evaluate at sample point"
            if not _values_within_tolerance(av, bv, spec):
                return False, f"diverged at {point}"
        return True, f"matched at {_NUMERIC_SAMPLE_POINTS} sample points"

    return _run_bounded(_compare, timeout)


def equivalent(
    a: str | sympy.Expr | None,
    b: str | sympy.Expr | None,
    *,
    sig_figs: int | None = None,
    dp: int | None = None,
    tolerance: str | None = None,
    simplify_timeout: float = _DEFAULT_SIMPLIFY_TIMEOUT,
    numeric_timeout: float = _DEFAULT_NUMERIC_TIMEOUT,
    parse_timeout: float = _DEFAULT_PARSE_TIMEOUT,
    abs_tol: float = _DEFAULT_ABS_TOL,
    rel_tol: float = _DEFAULT_REL_TOL,
) -> Verdict:
    """Compare two answers for mathematical equivalence.

    ``a`` and ``b`` may be raw text (parsed with :func:`parse_expr_safe`) or
    already-parsed SymPy expressions. If either side is text and fails to
    parse, the result is ``UNPARSEABLE`` — callers (I6/``_verify_calculated_
    answers``) fall back to their own literal check in that case, since this
    module has nothing to say about text it cannot read as an expression.

    ``sig_figs``, ``dp`` and ``tolerance`` are the mark scheme's own
    precision fields (``CalculatedAnswer.sig_figs``/``.dp``/``.tolerance``)
    — the plan requires the comparison tolerance to be *derived from the
    scheme*, not a hardcoded constant baked into this module. ``tolerance``
    is free text and is read shape-aware (:func:`_parse_tolerance`) —
    percent, sig-fig/dp wording, or a bare "± N" — never as a bare number
    regardless of what precedes it (I8 review B1). When ``sig_figs`` or
    ``dp`` is given directly as well as present in ``tolerance``'s wording,
    the direct keyword wins. When none of these resolve to anything, only
    ``abs_tol``/``rel_tol`` apply, at their float-noise-scale defaults (see
    :data:`_DEFAULT_ABS_TOL`) — deliberately too tight to substitute for a
    real marking tolerance, so an un-configured caller gets a strict
    comparison rather than a silently lenient one. That leniency is also
    restricted to the part of the answer it is a statement about, and to a
    magnitude sane for that answer — see :func:`_key_present_on_both_sides`
    and :meth:`_ToleranceSpec.for_magnitude` (I8 review B2, I8 re-review
    MUST-FIX 1/2).

    ``sympy.simplify(a - b)`` decides it first: an exact zero (after
    expansion), or a difference within the derived tolerance of each
    eligible term's own magnitude, means ``EQUAL_PROVEN`` (see
    :func:`_diff_within_tolerance`). If `simplify` has not returned within
    ``simplify_timeout`` seconds, a numeric comparison at sample points
    seeded from the two expressions themselves is used instead
    (:func:`_sampler_seed`) — a probabilistic check, so it is reported as
    ``EQUAL_SAMPLED``, for which :attr:`Verdict.auto_awardable` is always
    ``False``. If the numeric fallback also cannot complete within
    ``numeric_timeout``, the result is ``UNPARSEABLE``: at that point this
    module knows nothing, and ``NOT_EQUAL`` is a positive claim that the
    student is wrong — a resource failure must never be read as a disproof
    (I8 review MUST-FIX #4).
    """
    expr_a = a if isinstance(a, sympy.Basic) else parse_expr_safe(a, timeout=parse_timeout)
    expr_b = b if isinstance(b, sympy.Basic) else parse_expr_safe(b, timeout=parse_timeout)
    if expr_a is None or expr_b is None:
        side = "a" if expr_a is None else "b"
        return Verdict(VerdictKind.UNPARSEABLE, detail=f"could not parse operand {side!r}")

    parsed_tolerance = _parse_tolerance(tolerance)
    spec = _ToleranceSpec(
        sig_figs=sig_figs if sig_figs is not None else parsed_tolerance.sig_figs,
        dp=dp if dp is not None else parsed_tolerance.dp,
        tolerance_abs=parsed_tolerance.absolute,
        tolerance_rel=parsed_tolerance.relative,
        abs_tol=abs_tol,
        rel_tol=rel_tol,
    )

    def _simplify_diff() -> sympy.Expr:
        return sympy.simplify(expr_a - expr_b)

    diff = _run_bounded(_simplify_diff, simplify_timeout)
    if diff is not None:
        is_equal = _diff_within_tolerance(diff, expr_a, expr_b, spec)
        kind = VerdictKind.EQUAL_PROVEN if is_equal else VerdictKind.NOT_EQUAL
        return Verdict(kind, method=EquivalenceMethod.SIMPLIFY, detail=f"simplify(a - b) = {diff}")

    fallback = _numeric_fallback(expr_a, expr_b, numeric_timeout, spec)
    if fallback is None:
        return Verdict(
            VerdictKind.UNPARSEABLE,
            detail="both simplify and the numeric fallback exceeded their timeout budgets",
        )
    is_equal, detail = fallback
    kind = VerdictKind.EQUAL_SAMPLED if is_equal else VerdictKind.NOT_EQUAL
    return Verdict(kind, method=EquivalenceMethod.NUMERIC, detail=detail)
