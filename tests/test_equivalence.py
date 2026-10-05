"""Tests for the I8 SymPy equivalence module (``lemely.core.equivalence``).

Pure unit tests: no DB, no network, no clock, no Gemini calls. Sections:

1. The 40-pair table — every row asserts its OWN expected verdict.
2. The first review round's 24-row minimum bar.
3. The second review round's minimum bar: scheme-tolerance shape-awareness
   (percent/sig-fig/dp wording, not a bare-digit guess), tolerance gated to
   the term it actually describes (not a licence for missing/extra
   algebra), the exponent-tower regex restricted to numeric operands (was
   rejecting compound SI units wholesale), the function-call check
   restricted to known SymPy callables (was rejecting implicit
   multiplication by a variable), and the thousands-separator collapse
   narrowed to genuine three-digit groups (was corrupting standard form
   with a dropped multiplication sign). Every kwargs-bearing row here forwards
   `sig_figs`/`dp`/`tolerance` — the first round's harness silently forwarded
   only `sig_figs`, so a `dp`/`tolerance` row would have passed while
   testing nothing.
4. Golden mark-scheme ``calculated_answer`` parsing — reported as a lower
   bound, deferred to I10.
5. Timeout/resource-exhaustion behaviour, using real (not mocked)
   pathological expressions: pool saturation, a genuine double timeout,
   sampler determinism across repeated calls, and interpreter-shutdown
   cost bounded regardless of an abandoned computation.
"""

from __future__ import annotations

import glob
import json
import logging
import math
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest
import sympy

from lemely.core.equivalence import (
    _ABS_TOLERANCE_DISCARD_MULTIPLE,
    _ABS_TOLERANCE_SANITY_FRACTION,
    _DEFAULT_ABS_TOL,
    _DEFAULT_REL_TOL,
    _MAX_PLAUSIBLE_RELATIVE_TOLERANCE,
    EquivalenceMethod,
    Verdict,
    VerdictKind,
    _diff_within_tolerance,
    _numeric_fallback,
    _parse_tolerance,
    _plausible_or_discard_absolute_candidate,
    _round_to_sig_figs,
    _rounds_agree_at_stated_precision,
    _sampler_seed,
    _ToleranceSpec,
    equivalent,
    parse_expr_safe,
)

#: Either kind of `equal` — used where a row's point is the VALUE compared,
#: not which of `simplify`/numeric fallback happened to resolve it.
_EQUAL_KINDS = (VerdictKind.EQUAL_PROVEN, VerdictKind.EQUAL_SAMPLED)

# ---------------------------------------------------------------------------
# 1. The 40-pair equivalence table (criterion 1: >= 38 correct, 0 false equal)
# ---------------------------------------------------------------------------

#: (a, b, expected_kind, note). Covers plain numeric notation variants,
#: units, algebra, near-misses that must never be reported ``equal``, and
#: non-mathematical mark-scheme prose that should not be parseable at all.
#: ``expected_kind`` is ``"equal"`` (either proven or sampled — this table
#: is not testing the method), ``"not_equal"``, or ``"unparseable"``.
_TABLE: list[tuple[str, str, str, str]] = [
    ("31.0", "31", "equal", "trailing decimal zero"),
    ("3/8", "0.375", "equal", "fraction vs decimal"),
    ("0.5", "1/2", "equal", "decimal vs fraction"),
    ("-4", "-4.0", "equal", "negative int vs float"),
    ("2.50", "2.5", "equal", "trailing zero"),
    ("100", "1.0e2", "equal", "plain vs exponential"),
    ("7/2", "3.5", "equal", "improper fraction"),
    ("0", "0.0", "equal", "zero variants"),
    ("1000000", "1×10^6", "equal", "standard form int"),
    ("3.0×10^8", "300000000", "equal", "CAIE standard-form example"),
    ("3.0×10⁸", "3.0*10^8", "equal", "unicode superscript standard form"),
    ("6.4×10⁻³", "0.0064", "equal", "negative exponent standard form"),
    ("g/cm3", "g cm^-3", "equal", "CAIE unit example"),
    ("g/cm³", "g/cm3", "equal", "unicode cubed vs digit"),
    ("2 m/s", "2m/s", "equal", "spacing"),
    ("10 N", "10N", "equal", "spacing, unit colliding with a SymPy builtin"),
    ("1/2 mv^2", "0.5mv²", "equal", "CAIE KE example"),
    ("mv", "vm", "equal", "commutative product"),
    ("a+b", "b+a", "equal", "commutative sum"),
    ("(a+b)^2", "a^2+2ab+b^2", "equal", "binomial expansion"),
    ("2(x+3)", "2x+6", "equal", "distribution"),
    ("x^2 - 1", "(x-1)(x+1)", "equal", "difference of squares"),
    ("sin(x)^2 + cos(x)^2", "1", "equal", "pythagorean identity"),
    ("5", "6", "not_equal", "different integers"),
    ("1/2", "1/3", "not_equal", "different fractions"),
    ("3.0×10^8", "3.0×10^7", "not_equal", "wrong exponent"),
    ("31.0", "31.1", "not_equal", "decimal-place slip"),
    ("mv^2", "mv", "not_equal", "missing exponent"),
    ("g/cm3", "kg/m3", "not_equal", "different unit symbols, not converted"),
    ("sin(x)", "cos(x)", "not_equal", "different functions"),
    ("(a+b)^2", "a^2+b^2", "not_equal", "missing cross term"),
    ("x+1", "x-1", "not_equal", "sign error"),
    ("2x", "3x", "not_equal", "wrong coefficient"),
    ("-4", "4", "not_equal", "sign error on constant"),
    ("1/2 mv^2", "mv^2", "not_equal", "missing factor of a half"),
    ("increases, then decreases", "31.0", "unparseable", "prose vs number"),
    ("any two from: A, B, C", "31.0", "unparseable", "list-style scheme text"),
    ("", "31.0", "unparseable", "empty text"),
    ("accept any value from 30 to 32", "31.0", "unparseable", "range instruction"),
    ("N/A", "3/8", "unparseable", "N/A marker (hygiene-rejected, not a tolerated miss)"),
]

assert len(_TABLE) == 40, "the acceptance criterion is a 40-pair table"

#: The minimum correct count the acceptance criterion requires.
_MIN_CORRECT = 38


def _kind_matches(kind: VerdictKind, expected: str) -> bool:
    if expected == "equal":
        return kind in _EQUAL_KINDS
    return kind.value == expected


@pytest.mark.parametrize("a,b,expected_kind,note", _TABLE, ids=[t[3] for t in _TABLE])
def test_forty_pair_table_row_matches_expected_verdict(
    a: str, b: str, expected_kind: str, note: str
) -> None:
    """Every row asserts ITS OWN expected verdict, `equal` rows included."""
    verdict = equivalent(a, b)
    assert _kind_matches(verdict.kind, expected_kind), (
        f"{a!r} vs {b!r} ({note}): expected {expected_kind}, got "
        f"{verdict.kind.value} (method={verdict.method}, detail={verdict.detail})"
    )


def test_forty_pair_table_aggregate_meets_accuracy_and_has_zero_false_equal() -> None:
    results = [(a, b, expected, equivalent(a, b)) for a, b, expected, _note in _TABLE]

    false_equal = [
        (a, b, v) for a, b, expected, v in results if v.kind in _EQUAL_KINDS and expected != "equal"
    ]
    assert not false_equal, (
        "an A-mark must never be auto-awarded on a wrong answer — false 'equal' "
        f"verdicts: {false_equal}"
    )

    correct = sum(1 for _a, _b, expected, v in results if _kind_matches(v.kind, expected))
    mismatches = [
        (a, b, expected, v.kind.value)
        for a, b, expected, v in results
        if not _kind_matches(v.kind, expected)
    ]
    assert correct >= _MIN_CORRECT, (
        f"only {correct}/{len(_TABLE)} pairs matched their expected verdict "
        f"(need >= {_MIN_CORRECT}); failures: {mismatches}"
    )


# ---------------------------------------------------------------------------
# 2. First review round's 24-row minimum bar
# ---------------------------------------------------------------------------

#: (a, b, expected_kind | None, kwargs, note). ``expected_kind=None`` means
#: either `equal` or `unparseable` is acceptable (the review left the mixed-
#: fraction convention open) — anything else, in particular `not_equal` on
#: a mis-parse, is not. ``kwargs`` is forwarded to :func:`equivalent`
#: directly (``dict[str, object]`` so a ``tolerance`` string fits, not just
#: an int — a narrower annotation is what let round one's harness silently
#: drop `dp`/`tolerance` rows, see section 3 below).
_REVIEW_ROWS: list[tuple[str, str, str | None, dict[str, object], str]] = [
    ("1.6e-19", "1.7e-19", "not_equal", {}, "elementary charge, wrong at 1sf"),
    ("3e-9", "-3e-9", "not_equal", {}, "sign error at small magnitude"),
    ("6.63e-34", "1.0e-34", "not_equal", {}, "Planck constant, 6x out"),
    ("5.0e-7", "6.0e-7", "not_equal", {}, "small-magnitude wavelength slip"),
    ("1e-7", "0", "not_equal", {}, "small value vs zero"),
    ("(0.1+0.2) m", "0.3 m", "equal", {}, "unit-bearing float noise"),
    ("1/3 m", "0.3333333333333333 m", "equal", {}, "unit-bearing float noise"),
    ("500", "1 500", "not_equal", {}, "space is a thousands separator, not a factor"),
    ("1500", "1 500", "equal", {}, "thousands separator round-trips"),
    ("12000", "12 000", "equal", {}, "thousands separator round-trips"),
    ("4.5 mg", "4.5 gm", "not_equal", {}, "milligram vs gram*metre"),
    ("4.5 mg", "4.5 g", "not_equal", {}, "milligram vs gram, for the right reason"),
    ("E", "2.718281828459045", "not_equal", {}, "energy E is not Euler's number"),
    ("2E", "5.43656365691809", "not_equal", {}, "same, scaled"),
    ("I", "sqrt(-1)", "not_equal", {}, "current I is not the imaginary unit"),
    ("N/A", "3/8", "unparseable", {}, "N/A must route to the caller's literal check"),
    ("n/a", "3/8", "unparseable", {}, "case-insensitive"),
    ("30 to 32", "31", "unparseable", {}, "range instruction"),
    ("31 ± 0.5", "31", "unparseable", {}, "tolerance notation"),
    ("~31", "31", "unparseable", {}, "approximation marker"),
    ("3 1/2", "3.5", None, {}, "ambiguous mixed fraction: equal or unparseable, not a wrong parse"),
    ("9^9^9", "1", "unparseable", {}, "exponent tower, bounded"),
    ("0.333", "1/3", "equal", {"sig_figs": 3}, "within the scheme's stated precision"),
    ("0.333", "1/3", "not_equal", {"sig_figs": 6}, "outside a tighter scheme precision"),
]

assert len(_REVIEW_ROWS) == 24


def _call_equivalent(a: str, b: str, kwargs: dict[str, object]) -> Verdict:
    """Forward EVERY field a row's kwargs carries.

    Round one's harness called `equivalent(a, b, sig_figs=kwargs.get(...))`
    — forwarding only `sig_figs` — so a `dp` or `tolerance` key in a row's
    kwargs was silently dropped: the row looked like it tested a scheme
    tolerance while actually testing the untouched default path, and
    passed regardless (I8 re-review B3). Forwarding the dict directly is
    what makes that class of mistake impossible to reintroduce.
    """
    return equivalent(a, b, **kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "a,b,expected_kind,kwargs,note", _REVIEW_ROWS, ids=[r[4] for r in _REVIEW_ROWS]
)
def test_review_minimum_bar_row(
    a: str, b: str, expected_kind: str | None, kwargs: dict[str, object], note: str
) -> None:
    verdict = _call_equivalent(a, b, kwargs)
    if expected_kind is None:
        assert verdict.kind in (*_EQUAL_KINDS, VerdictKind.UNPARSEABLE), (
            f"{a!r} vs {b!r} ({note}): got {verdict.kind.value}, detail={verdict.detail}"
        )
    else:
        assert _kind_matches(verdict.kind, expected_kind), (
            f"{a!r} vs {b!r} ({note}): expected {expected_kind}, got "
            f"{verdict.kind.value} (method={verdict.method}, detail={verdict.detail})"
        )


# ---------------------------------------------------------------------------
# 3. Second review round's minimum bar
# ---------------------------------------------------------------------------

#: (a, b, expected_kind, kwargs, note). Every kwargs-bearing row here is
#: run through `_call_equivalent`, which forwards the whole dict — so a
#: `dp=` or `tolerance=` row genuinely exercises that code path.
_SCHEME_AND_NOTATION_ROWS: list[tuple[str, str, str, dict[str, object], str]] = [
    # B1 — tolerance parsing must be shape-aware, not a bare-digit guess.
    ("31", "40", "not_equal", {"tolerance": "allow 10%"}, "10% of 31 is 3.1, not 9"),
    ("31", "21", "not_equal", {"tolerance": "allow 10%"}, "10% of 31 is 3.1, not 10"),
    ("31", "33", "equal", {"tolerance": "allow 10%"}, "within 10% of 31"),
    ("0.5", "2.4", "not_equal", {"tolerance": "accept to 2 sf"}, "'2 sf' is not literal ±2"),
    ("31.0", "31.004", "equal", {"tolerance": "2 dp"}, "within 2 dp (±0.005)"),
    ("31.0", "31.5", "not_equal", {"tolerance": "2 dp"}, "outside 2 dp"),
    # B2 — scheme tolerance must not license a missing/extra algebraic term.
    ("(a+b)^2", "a^2+b^2", "not_equal", {"tolerance": "± 2"}, "missing 2ab, not a rounding gap"),
    ("(a+b)^2", "a^2+b^2", "not_equal", {"dp": 0}, "pin: must not regress to equal"),
    ("sin(x)^2+cos(x)^2+0.4*y", "1", "not_equal", {"dp": 0}, "stray 0.4*y term, not noise"),
    ("0.4*x + 31", "31", "not_equal", {"dp": 0}, "stray 0.4*x term, not noise"),
    ("1.5*x + 100", "100", "not_equal", {"tolerance": "± 2"}, "stray 1.5*x term, not noise"),
    ("31.4", "31", "equal", {"dp": 0}, "pin: the intended leniency still works"),
    # I8 re-review round 6 SHOULD-FIX 1 originally pinned
    # _ABS_TOLERANCE_DISCARD_MULTIPLE (10x) from both sides via `dp` here,
    # the way the percent path's 19%/20% rows pin
    # _MAX_PLAUSIBLE_RELATIVE_TOLERANCE. Round 10 SUPERSEDED that: `dp`/
    # `sig_figs` no longer route through `_plausible_or_discard_absolute_
    # candidate` (the flat `0.5 * ref` cap it applied was the structural
    # cause of a persistent 50%-relative-error ceiling rounds 7-9 each
    # relocated without closing — see `_precision_candidate_or_discard`).
    # `_ABS_TOLERANCE_DISCARD_MULTIPLE`'s own location is still pinned
    # directly by `test_dp_tolerance_credibility_boundary_is_confined_to_
    # the_discard_threshold` (which calls the function itself, still a
    # real, tested, general-purpose utility — just with no production
    # caller as of this round). The row below is UPDATED, not deleted
    # (I8 re-review round 9's standing rule): it now pins
    # `_precision_candidate_or_discard`'s coherence threshold (0.5x ref)
    # instead, via `dp` end to end — ratio to ref=0.06 is 8.33 (still
    # < old 10x, but now > the new 0.5x coherence threshold), so the
    # candidate is DISCARDED, not capped, and the verdict flips from the
    # round-6 `equal` to `not_equal` (mark-lowering — the safe direction).
    (
        "0.055",
        "0.06",
        "not_equal",
        {"dp": 0},
        "round 10: dp candidate 8.3x ref is past the NEW 0.5x coherence threshold",
    ),
    (
        "0.035",
        "0.04",
        "not_equal",
        {"dp": 0},
        "dp candidate 12.5x ref — past both the old and new thresholds",
    ),
    # The new coherence threshold's own location, pinned via `dp` end to
    # end (I8 re-review round 10): dp=0's candidate is 0.5, exactly the
    # boundary at ref=1.0. `ref=1.02` (candidate 0.5 <= 0.5*1.02=0.51) is
    # coherent — used verbatim, diff 0.42 admitted. `ref=0.98` (candidate
    # 0.5 > 0.5*0.98=0.49) is not — discarded to the strict default.
    ("1.02", "0.6", "equal", {"dp": 0}, "round 10: dp candidate coherent at ref 1.02"),
    ("0.98", "0.6", "not_equal", {"dp": 0}, "round 10: dp candidate incoherent at ref 0.98"),
    # B4 — the exponent-tower check must not reject compound SI units.
    ("kg m²s⁻²", "kg m^2 s^-2", "equal", {}, "the joule, unicode vs caret"),
    ("m²s⁻²", "m^2 s^-2", "equal", {}, "compound unit, no leading coefficient"),
    ("J kg^-1K^-1", "J kg^-1 K^-1", "equal", {}, "specific heat capacity"),
    ("W m^-2K^-4", "W m^-2 K^-4", "equal", {}, "Stefan-Boltzmann"),
    ("N m^2C^-2", "N m^2 C^-2", "equal", {}, "Coulomb constant"),
    ("9^9^9", "1", "unparseable", {}, "still a real tower — must still reject"),
    ("2**3**4", "1", "unparseable", {}, "still a real tower — must still reject"),
    # S1 — the function-call check must not reject implicit multiplication.
    ("a(b+c)", "ab+ac", "equal", {}, "implicit multiplication by a variable"),
    ("x(x+1)", "x^2+x", "equal", {}, "implicit multiplication by a variable"),
    # S2 — the thousands collapse must not corrupt dropped-x standard form.
    ("1.6 10^-19", "1.6e-19", "equal", {}, "dropped × before 10^-19"),
    ("3.0 10^8", "3.0e8", "equal", {}, "dropped × before 10^8"),
    ("2 500", "2500", "equal", {}, "pin: thousands separator must not regress"),
    ("12 000", "12000", "equal", {}, "pin: thousands separator must not regress"),
    ("1 500 000", "1500000", "equal", {}, "pin: chained thousands separators"),
    # I8 re-review round 7 MUST-FIX 1 — the round-7 gate on a STATED
    # absolute tolerance (`_MAX_PLAUSIBLE_RELATIVE_TOLERANCE` applied to
    # `tolerance_abs`) had no dedicated test: reverting it failed only one
    # assertion, in a test about something else. These two rows pin the
    # gate's LOCATION on the absolute path the same way `"19%"`/`"20%"`
    # above already pin it on the percent path — `ref` fixed at 100 (`b`
    # on both rows is smaller, so `max(a, b) == 100` always) so the ratio
    # is exactly the stated tolerance / 100.
    ("100", "81", "equal", {"tolerance": "± 19"}, "± 19 is 19% of ref 100 — believed, verbatim"),
    (
        "100",
        "75",
        "not_equal",
        {"tolerance": "± 25"},
        "± 25 is 25% of ref 100 — past the credibility boundary",
    ),
]


@pytest.mark.parametrize(
    "a,b,expected_kind,kwargs,note",
    _SCHEME_AND_NOTATION_ROWS,
    ids=[r[4] for r in _SCHEME_AND_NOTATION_ROWS],
)
def test_scheme_and_notation_row(
    a: str, b: str, expected_kind: str, kwargs: dict[str, object], note: str
) -> None:
    verdict = _call_equivalent(a, b, kwargs)
    assert _kind_matches(verdict.kind, expected_kind), (
        f"{a!r} vs {b!r} ({note}) kwargs={kwargs}: expected {expected_kind}, got "
        f"{verdict.kind.value} (method={verdict.method}, detail={verdict.detail})"
    )


@pytest.mark.parametrize("tolerance", ["50%", "± 50", "allow 50% (± 50)"])
def test_stated_tolerance_credibility_does_not_depend_on_units(tolerance: str) -> None:
    """The round-7 MUST-FIX, pinned directly (I8 re-review round 7
    MUST-FIX 1 — round 6's own dedicated test for this fix had somehow
    ended up covering only one incidental assertion inside a test about
    something else, and none of these three exact strings appeared
    anywhere but docstring prose).

    `100` vs `115` is a genuine 15% error. A scheme stating `"50%"`,
    `"± 50"`, or `"allow 50% (± 50)"` are the SAME claim in different
    words — a stated tolerance worth half the answer is not a credible
    precision statement in any of the three spellings, and all three must
    be discarded to the strict default, not just the one written as a
    percent. Before the round-7 fix, `"± 50"` and the parenthetical
    `"allow 50% (± 50)"` both survived to `equal_proven`/
    `auto_awardable=True` — five times more lenient than `"50%"` for the
    identical pair, and circumventable by a scheme's own wording.
    """
    verdict = equivalent("100", "115", tolerance=tolerance)
    assert verdict.kind is VerdictKind.NOT_EQUAL, (
        f"tolerance={tolerance!r}: expected NOT_EQUAL, got {verdict.kind.value}"
    )
    assert not verdict.auto_awardable


def test_auto_awardable_is_true_only_for_equal_proven_across_every_table_row() -> None:
    """Structural rule, not a convention — checked against real ``equal``
    rows from all three tables (every one currently resolves via
    ``simplify``, i.e. ``EQUAL_PROVEN``) and separately, in
    ``test_slow_simplify_falls_back_to_numeric_within_budget``, against a
    row that genuinely reaches the numeric path.
    """
    equal_pairs: list[tuple[str, str, dict[str, object]]] = [
        (a, b, {}) for a, b, expected, _note in _TABLE if expected == "equal"
    ]
    equal_pairs += [
        (a, b, kwargs) for a, b, expected, kwargs, _note in _REVIEW_ROWS if expected == "equal"
    ]
    equal_pairs += [
        (a, b, kwargs)
        for a, b, expected, kwargs, _note in _SCHEME_AND_NOTATION_ROWS
        if expected == "equal"
    ]
    assert equal_pairs, "expected at least one equal row to check auto_awardable against"
    for a, b, kwargs in equal_pairs:
        verdict = _call_equivalent(a, b, kwargs)
        if verdict.kind is VerdictKind.EQUAL_PROVEN:
            assert verdict.auto_awardable
        elif verdict.kind is VerdictKind.EQUAL_SAMPLED:
            assert not verdict.auto_awardable


# ---------------------------------------------------------------------------
# 3.5. Third review round: the CROSS PRODUCT round 3 was missing
# ---------------------------------------------------------------------------
#
# Round 1 found the module blind at SI magnitude (0 of 40 table rows within
# 3.8 orders of magnitude of the threshold deciding every verdict). Round 2
# found the tolerance surface added to fix that was itself untested (0 of 64
# rows forwarded `dp`/`tolerance`). Round 3 landed both sets of required rows
# — and they passed as two DISJOINT tables: every round-1 small-magnitude row
# carries `kwargs={}`, and the smallest magnitude in any kwargs-bearing row
# was 0.333. So the absolute-tolerance code path (`dp`, a bare "± N") was
# exercised only in the band 0.333-100, where an absolute window is
# harmless — reproducing round 1's exact criticism on the new surface. This
# section is the INTERACTION: round-1 pairs re-run under scheme kwargs, and
# round-2 B2 pairs re-run with their variables renamed.

#: The full kwarg axis MUST-FIX 1's clamp must hold for — not just the
#: three absolute shapes round 3's finding list happened to name.
#: `sig_figs` and a percent shape are included because round 4 found
#: exactly this omission: "sig_figs against any small-magnitude pair: zero
#: rows" was the one uncovered cell every round-4 MUST-FIX traced back to
#: (I8 re-review round 4 SHOULD-FIX 6 / round 5's completion of it).
_ABSOLUTE_TOLERANCE_SHAPES: list[dict[str, object]] = [
    {"dp": 0},
    {"dp": 2},
    {"tolerance": "± 5"},
    {"sig_figs": 1},
    {"sig_figs": 2},
    {"tolerance": "2.0 sf"},
    {"tolerance": "allow 10%"},
]

#: Wrong-answer pairs spanning both ends of the magnitude axis the review
#: found untested: SI-scale (below 1e-3, where round 4's MUST-FIX 1 lived)
#: and the large-magnitude end (>= 1e6, hand-probed by the reviewer and
#: found correct but untested — recorded here so a later round does not
#: have to re-derive that it is sound). Each pair is wrong by a large
#: enough margin (not merely a units-in-the-last-place slip) that it stays
#: `not_equal` under every shape in `_ABSOLUTE_TOLERANCE_SHAPES` above,
#: including the loosest ones (`sig_figs=1`, `allow 10%`) — verified by
#: direct call before being pinned as a parametrized table, not assumed.
_WRONG_ANSWER_MAGNITUDE_PAIRS: list[tuple[str, str]] = [
    ("1.6e-19", "3.2e-19"),
    ("3e-9", "-3e-9"),
    ("6.63e-34", "2.0e-34"),
    ("5.0e-7", "1.3e-6"),
    ("1e-7", "0"),
    ("1500000", "2500000"),
    ("3e8", "4e8"),
]

#: (a, b, kwargs, note). Every row's expected kind is `not_equal` — each
#: pair is a previously-required wrong-answer case; the point is that NO
#: scheme kwarg, however generous, may turn it into `equal_proven`.
_MUST_FIX_1_AND_2_ROWS: list[tuple[str, str, dict[str, object], str]] = [
    # MUST-FIX 1 — every magnitude-class pair x every tolerance shape
    # (7 x 7 = 49 rows). An unclamped absolute window, or an unclamped
    # `sig_figs` (round 4's specific gap), makes some of these
    # `equal_proven`.
    *(
        (a, b, kwargs, f"{a} vs {b} at {kwargs}")
        for a, b in _WRONG_ANSWER_MAGNITUDE_PAIRS
        for kwargs in _ABSOLUTE_TOLERANCE_SHAPES
    ),
    # MUST-FIX 2 — every round-2 B2 pair, renamed to unit-family letters.
    # The round-3 bug (`_is_unit_or_scalar_key`) granted these full scheme
    # leniency purely because `m`/`s`/`T` are unit-family symbol names —
    # the ORIGINAL `x`/`y` versions of these exact pairs are pinned in
    # `_SCHEME_AND_NOTATION_ROWS` above and must give the same answer.
    ("(m+s)^2", "m^2+s^2", {"tolerance": "± 2"}, "renamed missing-cross-term"),
    ("(m+T)^2", "m^2+T^2", {"dp": 0}, "renamed missing-cross-term, dp shape"),
    ("sin(x)^2+cos(x)^2+0.4*m", "1", {"dp": 0}, "renamed stray term"),
    ("0.4*m + 31", "31", {"dp": 0}, "renamed stray term"),
    ("1.5*T + 100", "100", {"tolerance": "± 2"}, "renamed stray term"),
    # Round-1 mechanism 5 (unit confusion) reopened by ANY scheme tolerance
    # under the old name-based eligibility check.
    ("0.19 cm", "0.19 mm", {"dp": 0}, "10x unit error, cm vs mm"),
    ("0.19 cm", "0.19 km", {"tolerance": "± 2"}, "1e5 unit error, cm vs km"),
    ("0.3 m", "0.3 s", {"dp": 0}, "metres are not seconds"),
    # Round 6 MUST-FIX 1 — a one-sided CONSTANT term. `_key_present_on_
    # both_sides` exempted `key == 1` (the pure-number term) unconditionally,
    # which was safe only while every absolute candidate was bounded below
    # `ref` — a guarantee round 5's as-is design broke. A whole missing
    # constant term through the single most common tolerance shape a mark
    # scheme writes.
    ("x + 5", "x", {"tolerance": "± 5"}, "one-sided constant term"),
    ("x + 4", "x", {"tolerance": "± 5"}, "one-sided constant term"),
    ("m*s + 5", "m*s", {"tolerance": "± 5"}, "one-sided constant term, unit-shaped factor"),
    ("x + 0.45", "x", {"dp": 0}, "one-sided constant term, dp shape"),
    # Round 6 MUST-FIX 2 — the 0.5 -> 10.0-used-as-is widening (since
    # reverted) admitted sign flips and 100-400% errors at ordinary
    # magnitude, all through tolerance shapes that survive the 10x band.
    ("2.5", "-2.5", {"tolerance": "± 5"}, "sign flip, 200% error"),
    ("0.3", "-0.2", {"tolerance": "± 0.5"}, "sign flip, 250% error"),
    ("0.19", "-0.3", {"tolerance": "± 0.5"}, "sign flip, 163% error"),
    ("-4", "4", {"tolerance": "± 8"}, "sign flip, 200% error"),
    ("8", "3", {"tolerance": "± 5"}, "167% error"),
    ("0.05", "0.01", {"dp": 0}, "400% error"),
    ("0.19", "0.6", {"tolerance": "± 0.5"}, "68% error"),
]


@pytest.mark.parametrize(
    "a,b,kwargs,note", _MUST_FIX_1_AND_2_ROWS, ids=[r[3] for r in _MUST_FIX_1_AND_2_ROWS]
)
def test_must_fix_1_and_2_regression_row(
    a: str, b: str, kwargs: dict[str, object], note: str
) -> None:
    verdict = _call_equivalent(a, b, kwargs)
    assert verdict.kind is VerdictKind.NOT_EQUAL, (
        f"{a!r} vs {b!r} ({note}) kwargs={kwargs}: expected not_equal, got "
        f"{verdict.kind.value} (auto_awardable={verdict.auto_awardable}, detail={verdict.detail})"
    )


def test_one_sided_constant_term_stays_eligible_when_present_on_both_sides() -> None:
    """Pins the correct, non-regressive side of MUST-FIX 1's fix: a constant
    term present on BOTH sides with different coefficients is a genuine
    precision comparison, not a missing term, and must stay eligible for
    scheme leniency — `_key_present_on_both_sides` must not have swung from
    "always eligible" to "never eligible" for `key == 1`.
    """
    verdict = equivalent("31 + 5", "31", tolerance="± 5")
    assert verdict.kind is VerdictKind.EQUAL_PROVEN
    assert verdict.auto_awardable


def test_unit_shaped_and_algebra_shaped_terms_agree_under_a_discarded_tolerance() -> None:
    """`1.4*m*s` and `1.4*x*y` are the SAME shape (a coefficient times a
    two-symbol product, present on both sides with the same discrepancy)
    — the only difference is whether the symbols happen to spell unit
    names. Whatever verdict the tolerance produces, it must treat them
    identically — checked here at a DISCARDED tolerance (this test does
    NOT cover name-based eligibility — see the note and the paired test
    below for that).

    The verdict itself is `not_equal` (flipped from `equal_proven` in I8
    re-review round 7): a stated `± 0.5` against `ref` 1.4 is 36% of the
    answer, and the module's own percent path discards a STATED tolerance
    at or above 20% as not a credible precision statement about this
    answer (`_MAX_PLAUSIBLE_RELATIVE_TOLERANCE`). Round 7 closed the gap
    where a scheme writing "50%" and one writing "± 50" (the same claim,
    different units) got different answers — the fix applies that same
    0.2 ceiling to a stated absolute tolerance, not only a stated percent.
    36% stated in figures is not a precision statement any more than 36%
    stated in words would be: we do not honour in figures what we refuse
    in words, so this pair is discarded to the strict default and is
    `not_equal`, same as `1.4*x*y` vs `1.0*x*y` at `tolerance="50%"` would
    be.

    IMPORTANT — what this test does NOT prove (I8 re-review round 7
    MUST-FIX 2): with the tolerance discarded, `spec` and
    `spec.restricted_to_default()` collapse to the SAME candidate list, so
    eligibility (:func:`_key_present_on_both_sides`) makes zero difference
    to this row's verdict — reinstating round 3's name-based eligibility
    bug still passes this test unchanged. This row is a units-
    independence pin, not an eligibility pin; eligibility on a ONE-SIDED
    term is covered by `test_invariant_one_sided_terms_are_never_tolerable`
    instead, and eligibility on a TWO-SIDED, SURVIVING-tolerance term (the
    thing this test's old docstring claimed to cover, incorrectly — a
    two-sided term is eligible under both the name-based and the
    presence-based rule, so no row on a two-sided term could ever have
    distinguished them) is covered by the paired test immediately below,
    which uses a tolerance that actually survives.
    """
    unit_verdict = equivalent("1.4*m*s", "1.0*m*s", tolerance="± 0.5")
    algebra_verdict = equivalent("1.4*x*y", "1.0*x*y", tolerance="± 0.5")
    assert unit_verdict.kind == algebra_verdict.kind, (
        f"verdict depended on symbol names: m*s -> {unit_verdict.kind.value}, "
        f"x*y -> {algebra_verdict.kind.value}"
    )
    assert unit_verdict.kind is VerdictKind.NOT_EQUAL, (
        "± 0.5 at ref 1.4 is 36% of the answer — not credible as a stated absolute "
        "tolerance any more than '36%' would be credible as a stated percent, so it is "
        "discarded to the strict default and both sides are not_equal"
    )


def test_unit_shaped_and_algebra_shaped_terms_agree_under_a_surviving_tolerance() -> None:
    """The consistency check that restores what MUST-FIX 2 (I8 re-review
    round 7) found the test above had lost: with the round-7 gate now
    discarding `± 0.5` at `ref` 1.4, eligibility makes no observable
    difference there any more (both `spec` and its restricted form
    collapse to the same window). Using `± 0.2` instead (14% of `ref` —
    inside `_MAX_PLAUSIBLE_RELATIVE_TOLERANCE`, so it SURVIVES and is
    actually applied) makes eligibility observable again: `1.4*m*s` vs
    `1.3*m*s` differs by 0.1, inside the surviving `± 0.2` window, so this
    only proves `equal_proven` if the scheme's tolerance was genuinely
    APPLIED to this two-sided, unit-shaped term — exactly what round 3's
    bug (unit-family names bypassing the eligibility check for a term
    present on only ONE side) would have gotten right for the wrong
    reason on a term like this one, but which a correctly-implemented
    eligibility check must also get right, symmetrically, for `x*y`.

    Verified this discriminates: forcing `_key_present_on_both_sides` to
    always return `False` makes both sides `not_equal` here, failing this
    test — confirming it is not vacuous the way the discarded-tolerance
    version above now is.
    """
    unit_verdict = equivalent("1.4*m*s", "1.3*m*s", tolerance="± 0.2")
    algebra_verdict = equivalent("1.4*x*y", "1.3*x*y", tolerance="± 0.2")
    assert unit_verdict.kind == algebra_verdict.kind, (
        f"verdict depended on symbol names: m*s -> {unit_verdict.kind.value}, "
        f"x*y -> {algebra_verdict.kind.value}"
    )
    assert unit_verdict.kind is VerdictKind.EQUAL_PROVEN, (
        "± 0.2 at ref 1.4 is 14% of the answer — a surviving, applied tolerance — so "
        "0.1 <= 0.2 should be equal on both sides"
    )
    assert unit_verdict.auto_awardable


def test_kg_ms_known_limitation_is_not_equal_never_equal_proven() -> None:
    """Pins the SI-prefix ambiguity documented beside `_SI_PREFIXES`
    (I8 re-review round 4 SHOULD-FIX 7) as a KNOWN, TESTED limitation.

    `"kg ms^-2"` reads its `ms` factor as the atomic unit "millisecond"
    (the same reading that correctly makes "4.5 mg" atomic milligram), not
    as `m * s` — so it does not equal `"N"` (kg*m/s**2), even though a
    student who wrote "kg ms^-2" meaning "kg m s^-2" (a dropped space) gets
    marked `not_equal` rather than `equal`. The direction matters: without
    this pin, a future round that "fixes" prefix handling could silently
    flip this into a false `equal_proven` and nothing would object — the
    over-rejection is the deliberately accepted cost, not something to
    "improve" without noticing what it trades away.
    """
    verdict = equivalent("N", "kg ms^-2")
    assert verdict.kind is VerdictKind.NOT_EQUAL
    assert not verdict.auto_awardable


# ---------------------------------------------------------------------------
# Structural invariants (I8 re-review round 3, "STRUCTURAL RULING")
# ---------------------------------------------------------------------------
#
# Hand-listed rows have failed to catch this module's tolerance-surface bugs
# three rounds running, because each round's rows test the surface that
# round happened to be thinking about. These three properties are meant to
# hold for ANY input, not just the ones enumerated above — a future change
# that violates one of them fails here regardless of which specific pair or
# kwarg combination triggers it.


def test_invariant_rename_does_not_change_the_verdict() -> None:
    """Consistently renaming every free symbol must not change the verdict.

    The parser gives a unit symbol and an ordinary algebra variable the
    SAME kind of `Symbol` — nothing in a `sympy.Expr` distinguishes "this
    is Newtons" from "this is an arbitrary variable called N". A
    discriminator that depends on the symbol's NAME (the round-3 bug) is
    therefore wrong by construction: swap the names consistently and nothing
    about the comparison's mathematical content has changed, so the verdict
    must not change either.
    """
    _CaseBuilder = Callable[[sympy.Symbol, sympy.Symbol], tuple[sympy.Expr, sympy.Expr]]
    cases: list[tuple[_CaseBuilder, dict[str, object]]] = [
        (lambda p, q: (p + 1, p - 1), {}),
        (lambda p, q: ((p + q) ** 2, p**2 + q**2), {"tolerance": "± 2"}),
        (lambda p, q: (sympy.Rational(2, 5) * p + 31, sympy.Integer(31)), {"dp": 0}),
        (lambda p, q: (sympy.Rational(3, 2) * p + 100, sympy.Integer(100)), {"tolerance": "± 2"}),
        (
            lambda p, q: (
                sympy.sin(p) ** 2 + sympy.cos(p) ** 2 + sympy.Rational(2, 5) * q,
                sympy.Integer(1),
            ),
            {"dp": 0},
        ),
        (
            lambda p, q: (sympy.Rational(14, 10) * p * q, sympy.Rational(10, 10) * p * q),
            {"tolerance": "± 0.5"},
        ),
    ]
    name_pairs = [("x", "y"), ("m", "s"), ("T", "g")]
    for builder, kwargs in cases:
        verdicts = {}
        for xname, yname in name_pairs:
            xs, ys = sympy.symbols(f"{xname} {yname}")
            a_expr, b_expr = builder(xs, ys)
            verdicts[(xname, yname)] = equivalent(a_expr, b_expr, **kwargs).kind  # type: ignore[arg-type]
        assert len(set(verdicts.values())) == 1, (
            f"verdict depended on symbol names for kwargs={kwargs}: {verdicts}"
        )


@dataclass(frozen=True, slots=True)
class _AlwaysGenerousSpec:
    """A `_ToleranceSpec`-shaped test double whose window always covers the
    full coefficient, no matter how large.

    A real `_ToleranceSpec.for_magnitude` caps/discards every absolute-shaped
    candidate (round 5 SHOULD-FIX 2/MUST-FIX 1) and rejects `sig_figs < 1`
    outright, so no kwarg combination reachable through `equivalent()` can
    any longer construct a spec generous enough to tolerate a one-sided
    term's own full magnitude (I8 re-review round 5's "ordering trap":
    fixing the clamp closes off the very kwarg, `sig_figs=0`, this
    invariant used to rely on to reach the branch it was testing). This
    double bypasses that entirely, asserting the property against
    `_diff_within_tolerance`'s OWN gating logic rather than against
    whichever specific tolerance shape happens to be capable of triggering
    it in the current implementation — see I8 re-review round 4 MUST-FIX 3
    and round 5's confirmation that the real-kwarg version was vacuous.
    """

    def for_magnitude(self, ref: float) -> float:
        return abs(ref) * 2 + 1.0

    def restricted_to_default(self) -> _NeverGenerousSpec:
        # Strict: this is what `_diff_within_tolerance` must fall back to
        # for an INELIGIBLE key. If this returned something generous too,
        # the test could not tell "the key was correctly gated to the
        # restricted spec" apart from "everything is generous regardless" —
        # it needs a real contrast between the two branches to mean anything.
        return _NeverGenerousSpec()


@dataclass(frozen=True, slots=True)
class _NeverGenerousSpec:
    """The restricted side of `_AlwaysGenerousSpec` — tolerates nothing."""

    def for_magnitude(self, ref: float) -> float:
        return 0.0

    def restricted_to_default(self) -> _NeverGenerousSpec:
        return self


def test_invariant_one_sided_terms_are_never_tolerable() -> None:
    """No spec may make a pair ``EQUAL_PROVEN`` when some diff key is
    present on only one side, however generous its tolerance window.

    A term entirely missing from one operand (or entirely absent from the
    other) is a missing/extra term — a different, larger kind of "not the
    same answer" than a rounding difference on a value both operands
    share, and no numeric precision statement can license it. Tested
    directly against `_diff_within_tolerance` with an always-generous
    fake spec (see `_AlwaysGenerousSpec`) rather than through `equivalent()`
    with a real kwarg, because every real kwarg shape is now itself capped
    to never exceed a one-sided term's own magnitude (`_ABS_TOLERANCE_
    SANITY_FRACTION` bounds every absolute candidate below `ref`, and
    `sig_figs < 1` is rejected outright) — so this property no longer has
    a live real-world trigger to hang a regression test on, only the
    internal invariant that should hold regardless.
    """
    a_sym, b_sym = sympy.symbols("a b")
    one_sided_pairs: list[tuple[sympy.Expr, sympy.Expr]] = [
        ((a_sym + b_sym) ** 2, a_sym**2 + b_sym**2),
        (sympy.Symbol("x") + 100, sympy.Integer(100)),
        (5 * sympy.Symbol("m") * sympy.Symbol("s") + 5, sympy.Integer(5)),
        (sympy.Symbol("F") + sympy.Rational(3, 10) * sympy.Symbol("N"), sympy.Symbol("F")),
    ]
    spec = _AlwaysGenerousSpec()
    for a_expr, b_expr in one_sided_pairs:
        diff = sympy.simplify(a_expr - b_expr)
        is_within = _diff_within_tolerance(diff, a_expr, b_expr, spec)  # type: ignore[arg-type]
        assert not is_within, (
            f"{a_expr} vs {b_expr}: a one-sided term was tolerated by an "
            "always-generous spec — _key_present_on_both_sides did not gate it"
        )


def test_sig_figs_zero_is_rejected_not_merely_capped() -> None:
    """`sig_figs=0` as a DIRECT keyword (bypassing the free-text
    `tolerance` route entirely) must contribute no leniency at all, not a
    wide-but-capped window.

    `CalculatedAnswer.sig_figs` has `ge=1` (`loose_schemas.py`), so this
    kwarg shape is not reachable from real scheme data — but `equivalent()`
    itself does not enforce that, and I8 re-review round 4 MUST-FIX 1(b)
    found a genuine hole here (`sig_figs=0`'s window is `5 * ref` by
    construction). Pinned directly, in addition to the free-text regex fix
    (MUST-FIX 1(a)) and the internal gating test above.
    """
    verdict = equivalent("31", "60", sig_figs=0)
    assert verdict.kind is VerdictKind.NOT_EQUAL
    assert not verdict.auto_awardable


def test_invariant_scheme_tolerance_never_exceeds_scaled_window() -> None:
    """No kwargs may turn a strict-default ``not_equal`` into
    ``EQUAL_PROVEN`` unless the difference is within the scheme's stated
    precision measured AGAINST THE REFERENCE MAGNITUDE — never a flat
    window that happens to be wide in absolute terms but tiny, or even
    vastly larger than the answer itself, at that magnitude.
    """
    # Wrong by enough that even the loosest shape below (sig_figs=1,
    # allow-10%-equivalent) cannot legitimately admit them — "1.6e-19" vs
    # "1.7e-19" (a 6% difference) rounds to the SAME value at 1 significant
    # figure and is a genuine, correct `equal` there, not a bug; reusing
    # `_WRONG_ANSWER_MAGNITUDE_PAIRS` avoids re-deriving that distinction.
    genuinely_wrong_small_magnitude_pairs = _WRONG_ANSWER_MAGNITUDE_PAIRS[:4]
    absolute_shaped_kwargs: list[dict[str, object]] = [
        {"dp": 0},
        {"dp": 2},
        {"dp": 6},
        {"dp": 10},
        {"tolerance": "± 2"},
        {"tolerance": "± 5"},
        {"sig_figs": 1},
        {"tolerance": "2.0 sf"},
    ]
    for a, b in genuinely_wrong_small_magnitude_pairs:
        for kwargs in absolute_shaped_kwargs:
            verdict = _call_equivalent(a, b, kwargs)
            assert verdict.kind is VerdictKind.NOT_EQUAL, (
                f"{a!r} vs {b!r} at {kwargs}: an absolute tolerance exceeded its "
                f"scaled window -> {verdict.kind.value}"
            )


def test_for_magnitude_never_exceeds_ref() -> None:
    """The axis rounds 1-4 each closed one magnitude cell of at a time,
    and round 5 opened as a ratio band instead (I8 re-review round 5 §6):
    for ANY pair and ANY kwargs, `for_magnitude(ref)` must never exceed
    `ref` itself. A window wider than the answer cannot be a precision
    statement about it, whatever the scheme says — `|a - b| <= 2 * ref`
    always holds for two values of the same magnitude, so a window at or
    above `ref` tolerates any difference between them, sign flip included.

    Asserted directly on `_ToleranceSpec`, the same way the one-sided
    invariant is asserted directly on `_diff_within_tolerance` — this is
    the property `_plausible_or_discard_absolute_candidate`'s cap exists
    to guarantee, checked independently of whichever specific pair or
    kwarg combination a round's row tables happened to exercise it with.
    """
    specs = [
        _ToleranceSpec(None, None, None, None, _DEFAULT_ABS_TOL, _DEFAULT_REL_TOL),
        _ToleranceSpec(1, None, None, None, _DEFAULT_ABS_TOL, _DEFAULT_REL_TOL),
        _ToleranceSpec(6, None, None, None, _DEFAULT_ABS_TOL, _DEFAULT_REL_TOL),
        _ToleranceSpec(None, 0, None, None, _DEFAULT_ABS_TOL, _DEFAULT_REL_TOL),
        _ToleranceSpec(None, 2, None, None, _DEFAULT_ABS_TOL, _DEFAULT_REL_TOL),
        _ToleranceSpec(None, 10, None, None, _DEFAULT_ABS_TOL, _DEFAULT_REL_TOL),
        _ToleranceSpec(None, None, 2.0, None, _DEFAULT_ABS_TOL, _DEFAULT_REL_TOL),
        _ToleranceSpec(None, None, 5.0, None, _DEFAULT_ABS_TOL, _DEFAULT_REL_TOL),
        _ToleranceSpec(None, None, 100.0, None, _DEFAULT_ABS_TOL, _DEFAULT_REL_TOL),
        _ToleranceSpec(None, None, None, 0.05, _DEFAULT_ABS_TOL, _DEFAULT_REL_TOL),
        _ToleranceSpec(None, None, None, 0.19, _DEFAULT_ABS_TOL, _DEFAULT_REL_TOL),
        # A scheme can carry more than one shape at once.
        _ToleranceSpec(6, 2, 5.0, 0.19, _DEFAULT_ABS_TOL, _DEFAULT_REL_TOL),
    ]
    refs = [
        1e-34,
        1e-19,
        1e-9,
        1e-7,
        1e-3,
        0.005,
        0.045,
        0.09,
        0.12,
        0.5,
        1.0,
        8,
        9,
        31,
        100,
        1500000,
        3e8,
    ]
    for spec in specs:
        for ref in refs:
            window = spec.for_magnitude(ref)
            assert window <= abs(ref), (
                f"for_magnitude({ref}) = {window} exceeds ref for spec={spec}"
            )


# ---------------------------------------------------------------------------
# SHOULD-FIX 1-3: tolerance-string parsing edge cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tolerance,a,b,expected_kind",
    [
        ("500%", "31", "900", "not_equal"),
        ("100%", "31", "60", "not_equal"),
        ("3 sf (accept 100% of marks)", "31", "60", "not_equal"),
        ("allow +/- 0.5", "31.0", "31.3", "equal"),
        ("± 0.5 cm", "31.0 cm", "31.3 cm", "equal"),
        ("± 0.2 to 2 dp", "31.0", "31.15", "equal"),
        ("± 0.2 to 2 dp", "31.0", "31.25", "not_equal"),
        # Round 5 MUST-FIX 2: "± N%" must read as N% relative, not N absolute
        # — unanchoring the bare pattern (round 4) let it also match the
        # number INSIDE a percent sign, and `max()` then preferred the
        # (much wider) absolute reading of the same substring.
        ("± 2%", "31", "32.5", "not_equal"),
        ("± 5%", "31", "35", "not_equal"),
        ("+/- 2%", "31", "32.5", "not_equal"),
        ("± 2 %", "31", "32.5", "not_equal"),
        # Round 5 SHOULD-FIX 3: 0.2 is pinned from both sides, not just from
        # above (round 4 only pinned "< 1.0" via 500%/100%). The threshold
        # is a CREDIBILITY boundary, not a precision statement about this
        # answer — a stated percent at or above 20% is DISCARDED entirely,
        # contributing no leniency at all, so "20%" itself is rejected too.
        # Round 6 briefly replaced this rejection with a `min(value, 0.2)`
        # cap, reasoning it would remove the "19%"-admits/"20%"-rejects
        # cliff (found via "100" vs "115") — that traded a monotonicity
        # nit for an award-affecting defect: capping a NON-CREDIBLE percent
        # (e.g. `tolerance="50%"`, which nothing states legitimately) still
        # grants the FULL 20% window on its strength, converting an
        # obviously-untrustworthy field value into real leniency ("100" vs
        # "115", a genuine 15% error, became `equal_proven` under
        # `tolerance="50%"`). Reverted: an over-threshold percent must be
        # discarded like an over-threshold absolute candidate is (see
        # `_plausible_or_discard_absolute_candidate`) — the boundary's
        # cliff is deliberate and pinned by
        # `test_percent_tolerance_credibility_boundary_is_confined_to_the_discard_threshold`,
        # not engineered away.
        ("19%", "100", "119", "equal"),
        ("20%", "100", "120", "not_equal"),
        ("21%", "100", "121", "not_equal"),
        # Round 5 SHOULD-FIX 4: a graph-reading allowance is a window of one
        # GRID SPACING, not that many whole units of the answer — must not
        # be read as a numeric tolerance regardless of whether a legitimate
        # unit token sits between the number and the disqualifying word.
        ("accept ± 1 square", "31", "31.8", "not_equal"),
        ("± 1 small square", "31", "31.8", "not_equal"),
        ("answer ± 1 division", "31", "31.8", "not_equal"),
        ("± 2 cm on the graph", "31", "31.8", "not_equal"),
        # Round 6 MUST-FIX 3: `_BARE_TOLERANCE_RE`'s trailing lookaheads
        # (round 5) BACKTRACKED around a decimal percent — `\d+(?:\.\d+)?`
        # matched "2.5", failed `(?!\s*%)` against "%", backtracked to "2",
        # and the lookahead then passed against ".5%". Every round-5 pinned
        # row above uses an INTEGER percent, the one shape with nothing to
        # backtrack into, so the defect shipped invisibly. `31` vs `40` at
        # `"± 10.5%"` is round 2's B1 numbers verbatim.
        ("± 2.5%", "31", "32.5", "not_equal"),
        ("+/- 2.5%", "31", "32.5", "not_equal"),
        ("± 10.5%", "31", "40", "not_equal"),
        ("± 12.5 %", "31", "40", "not_equal"),
        # The counting-noun lookaheads had the identical backtracking bug.
        ("± 1.5 squares", "31", "32.6", "not_equal"),
        ("± 2.5 divisions", "31", "34", "not_equal"),
    ],
    ids=[
        "SHOULD-FIX-1-implausible-percent-rejected",
        "SHOULD-FIX-1-100-percent-rejected",
        "SHOULD-FIX-1-percent-does-not-override-explicit-sf",
        "SHOULD-FIX-3-unanchored-plus-minus",
        "SHOULD-FIX-3-unanchored-plus-minus-with-unit",
        "SHOULD-FIX-2-widest-shape-wins-within",
        "SHOULD-FIX-2-widest-shape-wins-outside",
        "round5-MUST-FIX-2-plus-minus-percent",
        "round5-MUST-FIX-2-plus-minus-percent-wider",
        "round5-MUST-FIX-2-plus-minus-percent-slash-form",
        "round5-MUST-FIX-2-plus-minus-percent-spaced",
        "round5-SHOULD-FIX-3-boundary-admitted",
        "round6-SHOULD-FIX-3-boundary-exact",
        "round5-SHOULD-FIX-3-boundary-rejected",
        "round5-SHOULD-FIX-4-graph-square",
        "round5-SHOULD-FIX-4-graph-small-square",
        "round5-SHOULD-FIX-4-graph-division",
        "round5-SHOULD-FIX-4-graph-unit-then-noun",
        "round6-MUST-FIX-3-decimal-percent",
        "round6-MUST-FIX-3-decimal-percent-slash-form",
        "round6-MUST-FIX-3-decimal-percent-wider",
        "round6-MUST-FIX-3-decimal-percent-spaced",
        "round6-MUST-FIX-3-decimal-counting-noun-square",
        "round6-MUST-FIX-3-decimal-counting-noun-division",
    ],
)
def test_tolerance_string_parsing_edge_case(
    tolerance: str, a: str, b: str, expected_kind: str
) -> None:
    verdict = equivalent(a, b, tolerance=tolerance)
    assert _kind_matches(verdict.kind, expected_kind), (
        f"{a!r} vs {b!r} at tolerance={tolerance!r}: expected {expected_kind}, got "
        f"{verdict.kind.value} (detail={verdict.detail})"
    )


@pytest.mark.parametrize(
    "tolerance,field,expected",
    [
        ("2.0 sf", "sig_figs", 2),
        ("3.0 s.f.", "sig_figs", 3),
        ("correct to 3.0 significant figures", "sig_figs", 3),
        ("accept to 2.0 sf", "sig_figs", 2),
        ("1.0 sig figs", "sig_figs", 1),
        ("2.0 dp", "dp", 2),
        ("3.0 decimal places", "dp", 3),
        ("1.0 d.p.", "dp", 1),
    ],
)
def test_sig_figs_and_dp_word_regex_does_not_read_past_a_decimal_point(
    tolerance: str, field: str, expected: int
) -> None:
    """Round 5 MUST-FIX 1(a) / SHOULD-FIX 5, corrected round 6 MUST-FIX 4:
    without a left boundary, `.search` matched the digits AFTER the
    decimal point in a string like "2.0 sf", parsing `sig_figs=0` from a
    scheme that plainly meant 2. The round-5 fix stopped the wrong digit
    (`0`) from being captured, but did not make the RIGHT one (`2`) match
    either — `"2.0 sf"` parsed to no `sig_figs` at ALL, silently discarding
    the scheme's stated precision rather than reading it. This test
    previously asserted `value is None or value >= 1`, which a `None`
    satisfies vacuously — it was pinning "not 0", not "= 2", and 14
    cross-product/invariant rows built on `{"tolerance": "2.0 sf"}` were
    contributing no tolerance at all while looking like they exercised one.
    Asserting the exact expected integer per row closes that.
    """
    parsed = _parse_tolerance(tolerance)
    value = getattr(parsed, field)
    assert value == expected, f"{tolerance!r} parsed {field}={value}, expected {expected}"


def test_dp_tolerance_is_monotonic_except_for_the_one_documented_coherence_jump() -> None:
    """A LOOSER stated precision (`dp=n`, fewer decimal places) must never
    make the comparison STRICTER than a FINER one (`dp=n+1`) — round 5
    SHOULD-FIX 2's original non-monotonicity finding: discarding an
    over-wide absolute candidate outright (rather than capping it) made
    `0.09` vs `0.12` `equal` at the finer `dp=1` but `not_equal` at the
    coarser `dp=0`, backwards from what "0 dp is a wider allowance than 1
    dp" should mean. Round 6 closed it with a flat `0.5 * ref` cap across
    the whole "plausible" band.

    Round 10 replaced that cap with
    :func:`_precision_candidate_or_discard`'s coherent-verbatim-or-
    discard rule, because the flat cap was itself the structural cause of
    a persistent 50%-relative-error auto-award ceiling (rounds 7, 8 and 9
    each relocated which pair exhibited it without closing it — see
    `test_the_dp_ceiling_is_bounded_by_the_coherence_threshold_not_50_
    percent_everywhere`). That trade brings back exactly ONE non-monotonic
    JUMP — never more — at the coherence boundary itself, the same shape
    the sibling test
    `test_dp_tolerance_credibility_boundary_is_confined_to_the_discard_
    threshold` already pins for the analogous boundary on the raw
    candidate/ref sweep: `0.09` vs `0.12` is `not_equal` at `dp=0`
    (candidate `0.5` is incoherent at `ref=0.12` — discarded to the tiny
    default), `equal_proven` at `dp=1` (candidate `0.05` is coherent —
    used verbatim, `0.03 <= 0.05`), then `not_equal` again at `dp=2..4`
    (the coherent candidate has shrunk below the `0.03` difference). This
    is round 5's original pattern in miniature, deliberately reintroduced
    at a DIFFERENT (lower) threshold — the price of closing the ceiling —
    so this test now pins "at most one RISE", not "zero rises", mirroring
    how the sibling test pins "at most one DROP" for its own boundary.

    That permitted rise is a DELIBERATE POLICY CHOICE, not a tolerated bug:
    it follows from the product owner's ruling that A STATED PRECISION
    DEFINES THE TOLERANCE WINDOW (see `_precision_candidate_or_discard`'s
    docstring, which records the ruling and its other accepted
    consequence). So if the rise ever DISAPPEARS, that is itself worth
    noticing rather than quietly welcoming: this test would still pass, but
    something would have changed what a stated precision means. As of I8
    re-review round 11 the rise is present and unmoved — `"0.09"` vs
    `"0.12"` is `not_equal` at `dp=0` and `equal_proven` at `dp=1`, with
    `_precision_count_is_decisive` in place exactly as without it (that fix
    changes decisiveness, never the window, and this boundary is a window
    property).
    """
    pairs_and_max_dp = [("0.09", "0.12", 4), ("8", "9", 2), ("31.0", "31.5", 4)]
    for a, b, max_dp in pairs_and_max_dp:
        results = [equivalent(a, b, dp=dp).kind in _EQUAL_KINDS for dp in range(max_dp + 1)]
        # `dp` counts UP as precision gets FINER. At most one RISE (a
        # `False` immediately followed by a `True`) is permitted, at the
        # coherence-boundary crossing; beyond that single jump, results
        # must return to non-increasing (no second rise).
        rises = [i for i in range(len(results) - 1) if results[i + 1] and not results[i]]
        assert len(rises) <= 1, (
            f"{a!r} vs {b!r}: dp results {results} have more than one rise, "
            "not just the one permitted coherence-boundary jump"
        )
        after_the_jump = results[rises[0] + 1 :] if rises else results
        first_rejected = next(
            (i for i, admitted in enumerate(after_the_jump) if not admitted), None
        )
        if first_rejected is not None:
            results = after_the_jump
            assert not any(results[first_rejected:]), (
                f"{a!r} vs {b!r}: dp results {results} are not monotonic — "
                "a finer (larger) dp admitted the pair after a coarser one rejected it"
            )


def test_dp_tolerance_credibility_boundary_is_confined_to_the_discard_threshold() -> None:
    """DERIVE the boundary, don't hand-pick pairs that happen to miss it.

    Round 6: `0.02` vs `0.04` is `not_equal` at `dp=0`, `equal_proven` at
    `dp=1`, `not_equal` again at `dp=2` onward, except the three hand-picked
    pairs in the test above all happen to land entirely on one side of the
    boundary (I8 review, three rounds running: SHOULD-FIX 2 was "fixed" by
    picking new pairs each time rather than by locating the boundary
    itself). This is not a monotonicity defect to eliminate —
    `_plausible_or_discard_absolute_candidate`'s own docstring explains why
    it is a deliberate CREDIBILITY boundary: a `dp`/bare-`± N` candidate
    more than `_ABS_TOLERANCE_DISCARD_MULTIPLE`x `ref` is not a believable
    precision statement about this answer, and is discarded to no
    leniency rather than capped. What this test pins is exactly where that
    boundary is allowed to occur: at most once, and only at the candidate
    that crosses `_ABS_TOLERANCE_DISCARD_MULTIPLE * ref` — never inside the
    plausible (believed) band, where `min(candidate, cap)` alone is
    provably non-decreasing, and never inside the discard band, which is
    constant 0.
    """
    for ref in (0.04, 1.0, 1234.5, 1.6e-19, 7.5e12):
        # Candidates a raw `dp=n` (or bare `± N`) tolerance can actually
        # produce, spanning several orders on both sides of the discard
        # threshold — not a hand-picked pair.
        candidates = [ref * (2.0**exp) for exp in range(-20, 20)]
        windows = [_plausible_or_discard_absolute_candidate(c, ref) or 0.0 for c in candidates]

        # Epsilon scaled to `ref` itself, not `max(ref, 1.0)`: at
        # ref=1.6e-19 the discard-boundary drop is from `_ABS_TOLERANCE_
        # SANITY_FRACTION * ref` (~8e-20) to `0.0`, and `max(ref, 1.0)`
        # floors the epsilon at 1.0 — `1e-15 * 1.0` is *larger* than the
        # entire drop it is meant to detect, silently masking the
        # boundary at this magnitude (found while tightening SHOULD-FIX 2
        # below to `== 1`: this ref produced 0 drops until fixed). Windows
        # at a given `ref` are always `O(ref)`, so scaling the epsilon to
        # `abs(ref)` catches the real jump while still being far above
        # float noise (~1e-16 relative).
        drops = [
            i for i in range(len(windows) - 1) if windows[i + 1] < windows[i] - 1e-9 * abs(ref)
        ]
        # Exactly one, not merely "at most one" (I8 re-review round 6
        # SHOULD-FIX 2): the sweep spans `ref * 2**exp` for `exp` in
        # [-20, 20), ratios ~9.5e-7 to ~5.2e5, which always straddles the
        # 10x discard threshold — so this test would go VACUOUS if the
        # discard tier were ever deleted (`drops == []` then trivially
        # satisfies "at most one", and everything below only runs `if
        # drops:`). `== 1` requires the boundary to actually exist.
        assert len(drops) == 1, (
            f"ref={ref}: expected exactly one non-monotonic drop (the discard "
            f"boundary), found {len(drops)} at candidates "
            f"{[candidates[i] for i in drops]}"
        )
        if drops:
            (i,) = drops
            discard_multiple = candidates[i] / abs(ref)
            assert discard_multiple == pytest.approx(_ABS_TOLERANCE_DISCARD_MULTIPLE, rel=1.0), (
                f"ref={ref}: the one permitted drop must straddle "
                f"_ABS_TOLERANCE_DISCARD_MULTIPLE (={_ABS_TOLERANCE_DISCARD_MULTIPLE}), "
                f"found it at candidate/ref={discard_multiple}"
            )
            # And it must be a drop TO zero (full discard), not a partial one.
            assert windows[i + 1] == 0.0

        # Below the boundary, capping alone (`min(candidate, cap)`) is
        # provably non-decreasing — pin that the plausible band itself
        # never contributes a drop.
        discard_threshold = _ABS_TOLERANCE_DISCARD_MULTIPLE * abs(ref)
        plausible = [w for c, w in zip(candidates, windows, strict=True) if c <= discard_threshold]
        assert plausible == sorted(plausible), (
            f"ref={ref}: the plausible (capped, non-discarded) band alone is not "
            f"monotonic: {plausible}"
        )
        cap = _ABS_TOLERANCE_SANITY_FRACTION * abs(ref)
        # Scaled to `abs(ref)` (I8 re-review round 7 SHOULD-FIX 1), not
        # `max(ref, 1.0)`: at ref=1.6e-19 the old floor admitted a window
        # ~1.25e10 times the cap without objecting — inert at the one
        # magnitude the cap/discard design exists to protect.
        assert all(w <= cap + 1e-9 * abs(ref) for w in plausible)


def test_sig_figs_tolerance_is_monotonic_in_precision() -> None:
    """`sig_figs` has no analogue of the `dp`/bare-`± N` cliff — pin it.

    A `sig_figs=n` candidate is `0.5 * 10 ** (exponent - n + 1)` where
    `exponent = floor(log10(abs(ref)))`. Its ratio to `ref` is therefore
    always `0.5 * 10 ** (1 - n) / m` for `m` in `[1, 10)` (`ref`'s own
    mantissa) — at most `0.5` (at `n=1`, `m` near 1) and shrinking by a
    further factor of 10 for every additional significant figure. That
    ratio never reaches `_ABS_TOLERANCE_DISCARD_MULTIPLE` (10.0), so a
    `sig_figs` candidate never enters the discard tier at any `ref != 0`
    and any `sig_figs >= 1` (the only values `_ToleranceSpec.for_magnitude`
    ever builds a candidate for — `sig_figs=0` is rejected upstream, I8
    re-review round 4 MUST-FIX 1(b)). It also never exceeds the cap
    (`_ABS_TOLERANCE_SANITY_FRACTION`, 0.5), so `window == candidate`
    throughout: a plain, monotonically shrinking function of `sig_figs`.
    Confirmed structurally here (never touching the discard tier, for a
    spread of magnitudes and mantissas) and behaviourally via `equivalent`.
    """
    for ref in (0.04, 1.0, 9.999, 1234.5, 1.6e-19, 7.5e12):
        for sig_figs in range(1, 12):
            exponent = math.floor(math.log10(abs(ref)))
            candidate = 0.5 * 10 ** (exponent - sig_figs + 1)
            assert candidate <= _ABS_TOLERANCE_DISCARD_MULTIPLE * abs(ref), (
                f"ref={ref}, sig_figs={sig_figs}: candidate {candidate} unexpectedly "
                "reached the discard tier"
            )
            # Scaled to `abs(ref)` (I8 re-review round 7 SHOULD-FIX 1),
            # not `max(ref, 1.0)` — the same fix as the boundary test
            # above, for the same reason: at ref=1.6e-19 the old floor
            # admitted a bound ~1.25e7x the cap.
            assert candidate <= _ABS_TOLERANCE_SANITY_FRACTION * abs(ref) + 1e-12 * abs(ref)

    pairs_and_max_sig_figs = [("31.4", "31.6", 3), ("0.0012", "0.0013", 3), ("8", "9", 2)]
    for a, b, max_sig_figs in pairs_and_max_sig_figs:
        results = [
            equivalent(a, b, sig_figs=sig_figs).kind in _EQUAL_KINDS
            for sig_figs in range(1, max_sig_figs + 1)
        ]
        first_rejected = next((i for i, admitted in enumerate(results) if not admitted), None)
        if first_rejected is not None:
            assert not any(results[first_rejected:]), (
                f"{a!r} vs {b!r}: sig_figs results {results} are not monotonic"
            )


#: `sig_figs=1`/`dp=0` are AWARD DEFECTS, not documentable limitations —
#: overturned from round 6's pin (I8 re-review round 7 item 7). Round 6
#: pinned `sig_figs=1` auto-awarding `9` vs `13.95` as a known, accepted
#: limitation, on the precedent of
#: `test_kg_ms_known_limitation_is_not_equal_never_equal_proven`. Round 7
#: rejected that precedent: `kg_ms` pins a `NOT_EQUAL` — over-strictness,
#: which costs review rate but always puts a human in the loop via
#: `equivalence_conflict`. Pinning `EQUAL_PROVEN`/`auto_awardable=True`
#: here was the opposite direction: an award defect blessed as a feature,
#: with no human anywhere in the path.
#:
#: `_rounds_agree_at_stated_precision`/`_ToleranceSpec.stated_precision_
#: bound`: whichever of `sig_figs`/`dp` is the DECISIVE (widest) source of
#: the comparison window must also have both values agree once rounded to
#: that many figures/places — the window alone is a necessary but not
#: sufficient reading of "N significant figures" or "N decimal places".
#:
#: Rounded HALF-UP (I8 re-review round 9 SHOULD-FIX 2b): half-to-even left
#: a residual auto-award at exactly the SAME worst-case error round 7
#: measured (`dp=0`'s 50%) — the fix moved which pair exhibited it
#: (`"1.0"`/`"1.5"` to `"0.25"`/`"0.5"`) rather than closing it. Each row
#: gets its own parametrize id (round 8's NIT: a single loop test detects
#: but does not diagnose which precision broke).
_ROUNDING_AGREEMENT_REJECTED_ROWS: list[tuple[str, str, dict[str, object], str]] = [
    ("9", "13.95", {"sig_figs": 1}, "sig_figs=1, 9 vs 10 at 1sf"),
    ("100", "150", {"sig_figs": 1}, "sig_figs=1, 100 vs 200 at 1sf"),
    ("1.0", "1.5", {"sig_figs": 1}, "sig_figs=1, 1 vs 2 at 1sf"),
    ("1.0", "1.5", {"dp": 0}, "dp=0, 1 vs 2 at 0dp"),
    ("0.25", "0.5", {"dp": 0}, "dp=0, half-up: 0 vs 1 — was equal under half-even"),
    ("25", "20", {"sig_figs": 1}, "half-up midpoint: 30 vs 20 at 1sf"),
    ("2.5", "2.0", {"sig_figs": 1}, "half-up midpoint: 3 vs 2 at 1sf"),
    ("0.25", "0.2", {"sig_figs": 1}, "half-up midpoint: 0.3 vs 0.2 at 1sf"),
    ("2.5", "2", {"dp": 0}, "half-up midpoint: 3 vs 2 at 0dp"),
]


@pytest.mark.parametrize(
    "a,b,kwargs,note",
    _ROUNDING_AGREEMENT_REJECTED_ROWS,
    ids=[r[3] for r in _ROUNDING_AGREEMENT_REJECTED_ROWS],
)
def test_rounding_agreement_rejects_a_window_admitted_pair(
    a: str, b: str, kwargs: dict[str, object], note: str
) -> None:
    verdict = equivalent(a, b, **kwargs)
    assert verdict.kind is VerdictKind.NOT_EQUAL, (
        f"{a!r} vs {b!r} at {kwargs} ({note}): expected NOT_EQUAL, got {verdict.kind.value}"
    )
    assert not verdict.auto_awardable


def test_rounding_agreement_does_not_reject_what_half_up_says_is_the_same() -> None:
    """The mirror of the rejected rows above: a pair that DOES agree once
    rounded half-up must not be caught in the net (I8 re-review round 9
    SHOULD-FIX 2b) — `2.5`/`3.0` and `0.25`/`0.3` at `sig_figs=1`, and
    `10.5`/`11.0` at `dp=0`, were all `not_equal` under half-to-even and
    are `equal_proven` under half-up, because both sides of each pair
    round to the SAME figure once ties break away from zero rather than
    to even. (`10.5`/`11.0`, not round 9's original `0.5`/`0.55`: round
    10's coherence threshold on `dp` — see `_precision_candidate_or_
    discard` — discards `dp=0`'s candidate entirely at `ref=0.55`, so
    that pair no longer reaches the rounding-agreement check at all; this
    row is chosen at a `ref` large enough to stay coherent.)

    Also: `sig_figs >= 2` / `dp >= 1` are unaffected — round 6 confirmed
    the misjudgement there is one unit in the last place and immaterial,
    and this fix must not turn those into false rejections. And a wider
    EXPLICIT tolerance stated alongside dp/sig_figs must still win — "±
    0.2 to 2 dp" means 2 dp is a display precision and ± 0.2 is the real,
    deliberately wider window (I8 re-review round 6 SHOULD-FIX 2, "widest
    shape wins" — this fix must not silently re-narrow it back to the
    losing candidate's precision).
    """
    still_equal = [
        ("2.5", "3.0", {"sig_figs": 1}, "half-up: both round to 3"),
        ("0.25", "0.3", {"sig_figs": 1}, "half-up: both round to 0.3"),
        ("10.5", "11.0", {"dp": 0}, "half-up: both round to 11 (coherent at this ref)"),
        ("31.4", "31", {"dp": 0}, "coarser dp, genuinely the same at 0 dp"),
        ("31.0", "31.004", {"tolerance": "2 dp"}, "same at 2 dp"),
        ("15.02", "15.04", {"sig_figs": 3}, "same to 3 sf (both round to 15.0)"),
    ]
    for a, b, kwargs, note in still_equal:
        verdict = equivalent(a, b, **kwargs)
        assert verdict.kind is VerdictKind.EQUAL_PROVEN, f"{a!r} vs {b!r} ({note}): {verdict.kind}"
        assert verdict.auto_awardable

    survives_wider_tolerance = equivalent("31.0", "31.15", tolerance="± 0.2 to 2 dp")
    assert survives_wider_tolerance.kind is VerdictKind.EQUAL_PROVEN
    assert survives_wider_tolerance.auto_awardable


def test_sig_figs_decisiveness_gate_is_load_bearing_when_a_wider_tolerance_wins() -> None:
    """The `sig_figs` half of `stated_precision_bound`'s decisiveness gate
    (I8 re-review round 9 MUST-FIX 2 — round 8 found this untested:
    deleting only the `sig_figs` decisiveness test left all 239 tests
    passing, while deleting the `dp` half — already pinned by
    `test_rounding_agreement_does_not_reject_what_half_up_says_is_the_same`'s
    `"± 0.2 to 2 dp"` row — fails 2).

    `"2.0"` vs `"2.4"` differ by `0.4`. The explicit `± 0.4` is wider than
    `sig_figs=2`'s own candidate (`± 0.05` at this magnitude), so `± 0.4`
    governs and the `sig_figs=2` wording is display precision only — it
    must NOT be imposed as a rounding-agreement requirement (`2.0` and
    `2.4` do not round to the same value at 2 sf, which would wrongly
    reject this pair if `sig_figs` were treated as decisive here).
    """
    survives = equivalent("2.0", "2.4", sig_figs=2, tolerance="± 0.4")
    assert survives.kind is VerdictKind.EQUAL_PROVEN
    assert survives.auto_awardable


def test_decisiveness_tie_break_favours_the_explicit_tolerance_at_an_exact_tie() -> None:
    """`stated_precision_bound`'s `> explicit` clauses (I8 re-review round
    9's answer to round 8 item 1c), pinned directly — round 9 shipped
    them with ZERO test coverage: round 10's reviewer found reverting
    both clauses to `== window` (the pre-round-9 rule) left all 250 tests
    passing, and each clause dropped individually was also uncaught.

    `dp`'s clause: `"31.0049"` vs `"31.0099"` at `± 0.005 to 2 dp` — the
    `dp=2` candidate (`0.005`) exactly TIES the explicit `± 0.005`. The
    tie must go to the EXPLICIT statement (`equal_proven`, no rounding
    claim imposed), not to `dp` (which would reject: `31.00` vs `31.01`
    disagree at 2 dp). Its neighbour `± 0.0049 to 2 dp` has `dp` genuinely
    wider than the explicit `0.0049` — `dp` IS decisive there, and the
    same pair is correctly `not_equal`.

    `sig_figs`'s clause: `"30.93"` vs `"30.97"` at `sig_figs=3`,
    `tolerance="± 0.05"` — the `sig_figs=3` candidate at this
    magnitude is also exactly `0.05`, tying the explicit `± 0.05`. Must
    stay `equal_proven` (diff `0.04 <= 0.05`) even though the pair
    disagrees at 3 sf (`30.9` vs `31.0`) — the tie goes to the explicit
    statement, so no rounding claim is imposed.
    """
    tie = equivalent("31.0049", "31.0099", tolerance="± 0.005 to 2 dp")
    assert tie.kind is VerdictKind.EQUAL_PROVEN, "an exact tie must favour the explicit tolerance"
    assert tie.auto_awardable

    just_wider = equivalent("31.0049", "31.0099", tolerance="± 0.0049 to 2 dp")
    assert just_wider.kind is VerdictKind.NOT_EQUAL, "dp genuinely wider than explicit must decide"
    assert not just_wider.auto_awardable

    sig_figs_tie = equivalent("30.93", "30.97", sig_figs=3, tolerance="± 0.05")
    assert sig_figs_tie.kind is VerdictKind.EQUAL_PROVEN, (
        "an exact sig_figs/explicit tie must favour the explicit tolerance"
    )
    assert sig_figs_tie.auto_awardable


def test_decisiveness_max_selection_is_not_just_beats_explicit() -> None:
    """The decisiveness gate requires a field's candidate to both beat
    `explicit` AND tie the true `window` — not merely beat `explicit` in
    isolation (I8 re-review round 10, closing the two clause-level gaps
    round 9's own new test could not distinguish: dropping `== window`
    from `sig_figs`'s clause, or from `dp`'s, left every existing test
    passing).

    `"10"` vs `"10.3"` with both `dp=0` and `sig_figs=3` set, no explicit
    tolerance: `dp=0`'s candidate (`0.5`) is the true decisive maximum;
    `sig_figs=3`'s candidate (`0.05`) exceeds the float-noise `explicit`
    baseline but is NOT the window's actual maximum. `sig_figs` must NOT
    be treated as decisive here — if it were, its rounding claim (`10.0`
    vs `10.3` disagree at 3 sf) would wrongly reject a pair `dp=0`
    correctly admits (`10` and `10.3` agree at 0 dp).
    """
    verdict = equivalent("10", "10.3", dp=0, sig_figs=3)
    assert verdict.kind is VerdictKind.EQUAL_PROVEN, (
        "sig_figs merely beating the float-noise baseline must not make it decisive "
        "over dp, which is the field that actually set the window"
    )
    assert verdict.auto_awardable


def test_the_dp_ceiling_is_bounded_by_the_coherence_threshold_not_50_percent_everywhere() -> None:
    """The `dp` auto-award ceiling: STILL exactly 50% at an isolated
    boundary point, but no longer achieved across an entire decade of
    magnitudes the way the flat `0.5 * ref` cap produced it (I8 re-review
    round 10 ruling, restoring the row round 9 found deleted without
    record — MUST-FIX 1 — in its CURRENT, honest form).

    `"0.5"` vs `"1.0"` at `dp=0` is `equal_proven`/`auto_awardable=True`
    at EXACTLY 50% relative error — `ref=1.0` is precisely
    `2 * dp=0's quantum (0.5)`, the coherence boundary itself, where the
    quantum is used verbatim and happens to equal half the answer. This
    is not a bug this round introduces or hides: it is the measured,
    honest consequence of round 10's structural fix, reported rather than
    swept into a passing assertion. Round 7 measured 50% at `1.0`/`1.5`;
    round 8 at `0.25`/`0.5`; round 9 at `0.025`/`0.05` (`sig_figs=1`/`dp`
    generally); this round measures 50% at `0.5`/`1.0` — and, by
    exhaustive grid search (200 points per `ref`, 27 `ref` values from
    0.001 to 1000), confirms the RAW ceiling number is UNCHANGED at
    exactly 50% for `dp` at any precision (0, 1, 2 all measured at 50%,
    each at its own `ref = 2 * quantum` singular point). What changed is
    where it is reachable: previously ANY `ref` in a whole decade
    (`quantum` to `10 * quantum`) hit the flat `0.5 * ref` cap; now only
    the single point `ref = 2 * quantum` does, everywhere else the
    quantum is either used verbatim (below the point, ratio shrinks
    toward 0 as `ref` grows) or discarded outright (below the coherence
    threshold, ratio effectively 0). `sig_figs` ceilings are UNCHANGED by
    this round for a structural reason: a `sig_figs` candidate's ratio to
    `ref` is bounded by construction at `0.5` (at `sig_figs=1`, worst
    mantissa) and never needed capping in the first place, so it never
    routed through the discarded cap and is unaffected — measured
    ceilings: `sig_figs=1` ~34% (`"0.145"`/`"0.0957"`-shaped pairs),
    `sig_figs=2` ~4.5%, `sig_figs=3` ~0.5% (immaterial, per round 6).

    The 50% award at that single point is an ACCEPTED POLICY TRADE-OFF, not
    an open defect: the product owner ruled, after rounds 7, 8 and 9 each
    failed to move the ceiling, that A STATED PRECISION DEFINES THE
    TOLERANCE WINDOW, and this point is what that ruling implies at
    `ref == 2 * quantum`. See `_precision_candidate_or_discard`'s docstring
    for the ruling and its second accepted consequence. Do not narrow this
    assertion to make the number smaller — the number is the policy.

    Directionality of round 10's change was measured here and the
    measurement was WRONG, twice (I8 re-review round 11 MUST-FIX 2). This
    docstring claimed "87 awards were REMOVED and ZERO were newly GRANTED
    ... on this grid", over a 5-precision-setting x 31-ref x 39-offset grid;
    a reviewer's wider 11,520-pair grid agreed. Neither could REACH the
    pairs round 10 newly granted, which need `ref` inside
    `[0.5 * 10**-dp, 10**-dp)` and the pair straddling `0.5 * 10**-dp` —
    and there were 1,122 of them, every one `auto_awardable=True`, up to 20%
    relative error. Both sweeps chose `ref` values independently of the `dp`
    under test, so they never landed in that half-decade; see
    `_discarded_dp_band_grid` for why that, specifically, is what blinded
    them, and for the two things it is NOT (a fixed `ref`, or offsets scaled
    to `ref` — both reach the band fine). The claim has been moved to a grid
    that can reach it and now lives, with its own instrument control, in
    `test_no_new_auto_award_on_a_grid_that_reaches_the_discarded_dp_band`.
    Nothing in this test asserts a directionality property; do not restate
    one here from a sweep whose `ref` values are not pinned to its `dp`.
    """
    ceiling_pair = equivalent("0.5", "1.0", dp=0)
    assert ceiling_pair.kind is VerdictKind.EQUAL_PROVEN, (
        "0.5 vs 1.0 at dp=0 sits exactly at the coherence boundary (ref=1.0=2*0.5) — "
        "the module's own honest 50%-error ceiling, not something to hide"
    )
    assert ceiling_pair.auto_awardable

    # Move `ref` just below the boundary — the SAME 0.5 quantum is now
    # incoherent (0.5 > 0.5 * 0.99) and discarded entirely, giving a much
    # smaller (not larger) admitted error — confirming the ceiling is a
    # single point, not a plateau either side of it.
    just_below = equivalent("0.5", "0.99", dp=0)
    assert just_below.kind is VerdictKind.NOT_EQUAL
    assert not just_below.auto_awardable


def _spec_for(
    sig_figs: int | None = None, dp: int | None = None, tolerance: str | None = None
) -> _ToleranceSpec:
    """The `_ToleranceSpec` `equivalent()` itself builds for these kwargs."""
    parsed = _parse_tolerance(tolerance)
    return _ToleranceSpec(
        sig_figs=sig_figs if sig_figs is not None else parsed.sig_figs,
        dp=dp if dp is not None else parsed.dp,
        tolerance_abs=parsed.absolute,
        tolerance_rel=parsed.relative,
        abs_tol=_DEFAULT_ABS_TOL,
        rel_tol=_DEFAULT_REL_TOL,
    )


def _pre_round_10_auto_awards(spec: _ToleranceSpec, a: float, b: float) -> bool:
    """Would the PRE-round-10 module have auto-awarded this bare numeric pair?

    A reference model of the four-line revert round 10 consists of: the flat
    `_plausible_or_discard_absolute_candidate` cap where the current module
    uses `_precision_candidate_or_discard`, and otherwise the module's own
    live code — `_ToleranceSpec._explicit_window`, its two raw candidates,
    the `== window and > explicit` decisiveness rule, and
    `_rounds_agree_at_stated_precision`. For a pair of numeric literals
    `_diff_within_tolerance` reduces to exactly this: one `key == 1` term,
    `ref = max(|a|, |b|)`, window test then rounding test.

    A model of a build that no longer exists can quietly become fiction, so
    the grid test below validates it in two ways before using it: against a
    DOCUMENTED round-10 removal the live module must disagree with it on,
    and by requiring the grid to contain removals at all.
    """
    ref = max(abs(a), abs(b))
    explicit = spec._explicit_window(ref)
    sig_figs_candidate = None
    if spec.sig_figs is not None and spec.sig_figs >= 1:
        sig_figs_candidate = _plausible_or_discard_absolute_candidate(
            spec._sig_figs_candidate(ref), ref
        )
    dp_candidate = None
    if spec.dp is not None:
        dp_candidate = _plausible_or_discard_absolute_candidate(spec._dp_candidate(ref), ref)
    window = max(c for c in (explicit, sig_figs_candidate, dp_candidate) if c is not None)
    if abs(a - b) > window:
        return False
    decisive_sig_figs = (
        spec.sig_figs
        if sig_figs_candidate is not None
        and sig_figs_candidate == window
        and sig_figs_candidate > explicit
        else None
    )
    decisive_dp = (
        spec.dp
        if dp_candidate is not None and dp_candidate == window and dp_candidate > explicit
        else None
    )
    return _rounds_agree_at_stated_precision(a, b, decisive_sig_figs, decisive_dp)


def _discarded_dp_band_grid() -> list[tuple[str, str, dict[str, int | str]]]:
    """Pairs that CAN reach the band where `dp`'s WINDOW is discarded.

    Write `q = 10**-dp`, so `dp`'s raw window candidate is `0.5 * q`. Two
    conditions put a pair inside the reachable band:

    1. `ref` inside `[0.5 * q, q)`. Below `q` the candidate exceeds
       `_ABS_TOLERANCE_SANITY_FRACTION * ref` and is discarded; and since
       both values are then below `q`, the only `dp` midpoint they can
       straddle is `0.5 * q`, which forces `ref >= 0.5 * q`.
    2. the pair actually STRADDLING `0.5 * q`, so the `dp` rounding claim
       DISAGREES — one value rounds to 0, the other to one whole `q`.

    Some window source other than `dp` must then admit the difference, but
    that is NOT a third condition to arrange: the `rel_tol` float-noise
    default (`1e-9 * ref`) already is one. So a pair with `dp` alone and no
    `sig_figs`/`tolerance` at all reaches the band, at offsets below that
    scale — `"0.4999999999"` vs `"0.5"` at `dp=0` is exactly that pair, and
    round 10 auto-awarded it. Hence the `{"dp": dp}` shape and the
    `1e-10`-scale offset below, which an earlier version of this grid
    omitted and could therefore not have caught a regression confined to
    that shape (I8 re-review round 12 SHOULD-FIX 1).

    What blinded the two earlier sweeps was neither condition. It was
    sweeping `ref` over human-chosen magnitudes (`0.001`, `0.1`, `1.0`,
    `31`, `1000`) INDEPENDENTLY of `dp`: such a sweep lands in the top half
    of the decade belonging to the `dp` under test essentially never,
    however large it grows. The rule for a grid here is therefore PIN `ref`
    TO THE `dp`, which is what `ref_multiple` does below — a multiple of
    `q / 2`, never an absolute magnitude.

    Two corollaries, both measured, that an earlier draft of this docstring
    got wrong by stating universals instead — the same over-general-negative
    shape as the claim round 11 MUST-FIX 2 removed, which is why it is worth
    stating carefully rather than loosely:

    - a FIXED `ref` with only the offset varying DOES reach the band, as
      long as that `ref` lies inside it: 11 newly-granted round-10 pairs at
      `ref = 0.5` alone. The earlier sweeps' fixed `ref` values lay outside
      `[0.5 * q, q)`; that, not the fixing, is why they reached nothing.
    - offsets scaled to `ref` rather than to `q` are FINE. With
      `ref = mult * q / 2`, a ref-relative offset `frac` straddles whenever
      `frac > 1 - 1 / mult`, so at `mult = 1.0` any positive offset does.
    """
    rows: list[tuple[str, str, dict[str, int | str]]] = []
    # As fractions of `q`. `0.0000000001` is the `dp`-alone case: it must stay
    # under the `rel_tol` window (`1e-9 * ref`, i.e. `5e-10 * q` at the band's
    # lower edge) for that window to admit it with no second source stated.
    offsets = (
        "0.0000000001",
        "0.005",
        "0.01",
        "0.02",
        "0.03",
        "0.04",
        "0.049",
        "0.08",
        "0.1",
        "0.19",
    )
    for dp in (0, 1, 2):
        quantum = Decimal(10) ** -dp
        for ref_multiple in ("1", "1.1", "1.25", "1.5", "1.8", "1.98"):
            ref = quantum / 2 * Decimal(ref_multiple)
            for offset in offsets:
                other = ref - quantum * Decimal(offset)
                if other <= 0:
                    continue
                for kwargs in (
                    {"dp": dp},
                    {"dp": dp, "sig_figs": 1},
                    {"dp": dp, "sig_figs": 2},
                    {"dp": dp, "tolerance": f"± {quantum * Decimal('0.1')}"},
                    {"dp": dp, "sig_figs": 1, "tolerance": f"± {quantum * Decimal('0.19')}"},
                ):
                    rows.append((str(other), str(ref), kwargs))
    return rows


#: (a, b, kwargs, why) — four pairs a DISCARDED `dp` window must still refuse.
#:
#: Each sits in `_discarded_dp_band_grid`'s band and rounds DIFFERENTLY at the
#: stated `dp`, by a whole unit in that `dp`'s last place. Round 10 made all
#: four `equal_proven`/`auto_awardable=True` (I8 re-review round 11 MUST-FIX
#: 1). The third is derived from the band characterisation rather than taken
#: from the review — the first two are at `dp=0`, and a `dp=0`-only pin would
#: not notice a fix that happened to work only at the coarsest precision.
#:
#: The fourth states NO second tolerance source: `dp` alone, with the `rel_tol`
#: float-noise default carrying the window by itself. The first three all set
#: `sig_figs` or `tolerance`, so without it these pins could not distinguish a
#: fix that only worked when a second source was stated (I8 re-review round 12
#: SHOULD-FIX 1). It is also the pair that falsifies the "needs a second
#: tolerance source" reading of the band — see `_discarded_dp_band_grid`.
_DISCARDED_DP_WINDOW_ROWS: list[tuple[str, str, dict[str, int | str], str]] = [
    (
        "0.45",
        "0.5",
        {"sig_figs": 1, "dp": 0},
        "10% error; dp=0's discarded claim was REPLACED by sig_figs=1's, which passes",
    ),
    (
        "0.4",
        "0.5",
        {"dp": 0, "tolerance": "± 0.1"},
        "20% error, the widest reachable; the stated ± 0.1 carries the window alone",
    ),
    (
        "0.048",
        "0.052",
        {"sig_figs": 1, "dp": 1},
        "7.7% error at dp=1, derived from the band characterisation, not reported",
    ),
    (
        "0.4999999999",
        "0.5",
        {"dp": 0},
        "dp ALONE: the rel_tol default window (5e-10) admits a 1e-10 diff that "
        "rounds 0 vs 1 at the stated 0 dp — no second tolerance source needed",
    ),
]


def test_a_discarded_dp_window_loses_its_leniency_not_its_rounding_claim() -> None:
    """A discarded precision candidate loses its WINDOW, never its CLAIM.

    `_precision_candidate_or_discard` answers exactly one question: is the
    derived window `0.5 * 10**-dp` coherent at this magnitude? Round 10 used
    its answer for a SECOND question too — decisiveness, i.e. whether "N
    decimal places" is enforced as a rounding claim by
    `_rounds_agree_at_stated_precision`. The two come apart in the band
    `ref` in `[0.5 * q, q)` for `q = 10**-dp`: there the window genuinely
    exceeds half the answer's own scale and must be discarded, while the
    rounding claim is not merely still well-defined but the STRICTEST
    available reading of the scheme's own words — both values are
    sub-quantum, so "to 0 dp" means "both round to the same whole number".

    Dropping the claim with the window did not merely relax `dp`; it let a
    DIFFERENT, WIDER rule win in its place. For `"0.45"` vs `"0.5"` at
    `sig_figs=1, dp=0` the decisive bound went from `(None, 0)` — `dp=0`
    enforced, `0` vs `1`, a whole unit apart, refused — to `(1, None)`:
    `sig_figs=1`'s claim SUBSTITUTED for `dp`'s, and it passes (both round
    to `0.5` at 1 s.f.). A 10%-relative-error pair the pre-round-10 code
    refused became `equal_proven`/`auto_awardable=True` — a mark awarded to
    a wrong answer with no human in the loop, which is the one thing this
    module's `auto_awardable` contract exists to prevent (I8 re-review round
    11 MUST-FIX 1).

    `_precision_count_is_decisive` splits the two questions: a discard costs
    the candidate its window, and decisiveness then falls back to the raw
    candidate's own comparison against `explicit` — the same "is the
    scheme's precision wording stricter than anything explicit it stated"
    test the coherent branch applies. The WINDOW is untouched, so this does
    not reopen the wide-band 50% ceiling round 10 exists to close.
    """
    for a, b, kwargs, why in _DISCARDED_DP_WINDOW_ROWS:
        verdict = equivalent(a, b, **kwargs)  # type: ignore[arg-type]
        assert verdict.kind is VerdictKind.NOT_EQUAL, f"{a} vs {b} {kwargs}: {why}"
        assert not verdict.auto_awardable, f"{a} vs {b} {kwargs}: {why}"

    # The mechanism, at the level it actually broke: at `ref=0.5` with
    # `sig_figs=1, dp=0`, `sig_figs` sets the window and `dp`'s candidate is
    # discarded — yet BOTH must be reported decisive, because `dp`'s raw
    # candidate still beats the explicit window and its rounding claim is
    # the stricter of the two.
    spec = _spec_for(sig_figs=1, dp=0)
    assert spec.for_magnitude(0.5) == pytest.approx(0.05), "sig_figs=1 sets the window here"
    assert spec._dp_candidate(0.5) > _ABS_TOLERANCE_SANITY_FRACTION * 0.5, (
        "this pair must sit in the band where dp's own window is DISCARDED"
    )
    assert spec.stated_precision_bound(0.5) == (1, 0), (
        "a dp whose window was discarded must keep its rounding claim — dropping it "
        "substitutes sig_figs=1's more permissive claim for dp=0's"
    )


def test_no_new_auto_award_on_a_grid_that_reaches_the_discarded_dp_band() -> None:
    """Round 10 must not newly GRANT an auto-award anywhere in the band.

    This replaces a directionality claim two earlier grids certified and
    both got wrong (I8 re-review round 11 MUST-FIX 2). Round 10's own test
    reported "87 awards were REMOVED and ZERO were newly GRANTED ... on this
    grid"; the qualifier was honest but the property is what the module's
    narrative rests on, and as a general statement it was false — 1,122
    newly-granted, `auto_awardable=True` pairs on the reviewer's wider grid.
    Neither sweep could reach the band, because neither pinned `ref` to the
    `dp` under test (see `_discarded_dp_band_grid`), and a test that cannot
    reach a defect is not a guard against it.

    Measured here, over 900 band-reaching pairs (900 of 900 have `dp`'s
    window discarded), comparing the live module against
    `_pre_round_10_auto_awards`: round 10 as written newly granted 79
    auto-awards (worst 20% relative error) while removing 404; with
    `_precision_count_is_decisive` the same 404 removals stand and NOTHING
    is newly granted. The change is mark-lowering only — now on a grid that
    could have shown otherwise.

    3 of those 79 are the `{"dp": dp}` shape with no second tolerance source
    stated, which an earlier version of this grid could not express at all
    (I8 re-review round 12 SHOULD-FIX 1). Keep that shape: a fix that only
    worked when `sig_figs`/`tolerance` accompanied `dp` would otherwise pass
    here, and the `rel_tol` default alone is enough to carry the window.
    """
    # Instrument control: a DOCUMENTED round-10 removal (`"0.5"` vs `"0.7"`
    # at `dp=0` — candidate `0.5` capped to `0.35`, diff `0.2` admitted,
    # both values rounding to `1`). The model must award it and the live
    # module must refuse it. If they AGREE, the model is not modelling
    # pre-round-10 and every count below is meaningless.
    assert _pre_round_10_auto_awards(_spec_for(dp=0), 0.5, 0.7), (
        "the reference model no longer reproduces a known pre-round-10 award"
    )
    assert equivalent("0.5", "0.7", dp=0).kind is VerdictKind.NOT_EQUAL, (
        "the live module no longer reproduces a known round-10 removal"
    )

    newly_granted: list[str] = []
    removed = 0
    discarded_dp_window = 0
    for a_text, b_text, kwargs in _discarded_dp_band_grid():
        a, b = float(a_text), float(b_text)
        spec = _spec_for(**kwargs)  # type: ignore[arg-type]
        ref = max(abs(a), abs(b))
        if spec._dp_candidate(ref) > _ABS_TOLERANCE_SANITY_FRACTION * ref:
            discarded_dp_window += 1
        before = _pre_round_10_auto_awards(spec, a, b)
        verdict = equivalent(a_text, b_text, **kwargs)  # type: ignore[arg-type]
        after = verdict.kind is VerdictKind.EQUAL_PROVEN and verdict.auto_awardable
        if before and not after:
            removed += 1
        if after and not before:
            newly_granted.append(
                f"{a_text} vs {b_text} {kwargs}: {abs(a - b) / ref:.1%} relative error"
            )

    assert discarded_dp_window, (
        "no grid pair reaches the band where dp's window is discarded — this guard "
        "cannot see the defect it exists for"
    )
    assert removed, (
        "no grid pair straddles round 10's change at all — the reference model and the "
        "live module agree everywhere, so a regression would not show up here either"
    )
    assert not newly_granted, (
        f"{len(newly_granted)} auto-award(s) the pre-round-10 code REFUSED are now "
        f"granted, with no human in the loop: {newly_granted[:5]}"
    )


def test_rounding_agreement_does_not_apply_pointwise_during_algebraic_sampling() -> None:
    """MUST-FIX 1 (I8 re-review round 9, a design ruling, not a test gap):
    the rounding-agreement check must act only where a concrete ANSWER
    value exists (a genuine constant-vs-constant comparison), never
    pointwise at arbitrary sample points probing an algebraic identity.

    Round 8 found the check applied inside `_values_within_tolerance`
    itself, which `_numeric_fallback` also calls once per RANDOM sample
    point when comparing expressions with free symbols — turning "the
    answer's own precision" into a claim about eight arbitrary values an
    expression happens to take. The measured consequence: the same
    marking question (`"is a 0.2 offset the same answer at 0 dp"`),
    expressed through ten expressions differing only by an arbitrary scale
    coefficient, went from uniformly `equal` to 7 of 10 `not_equal`,
    decided by where the seeded sample points landed — and the result was
    `NOT_EQUAL`, never a review flag, since `EQUAL_SAMPLED` is never
    `auto_awardable`.

    The fix moved the rounding-agreement check out of
    `_values_within_tolerance` (now window-only, used identically for
    both the direct comparison and the per-sample-point algebra check)
    and into `_numeric_fallback`'s own no-free-symbols branch, the one
    place on this path where a concrete final-answer value exists. This
    test proves both halves directly against the production
    `_numeric_fallback`, not just through `equivalent()`.
    """
    x = sympy.Symbol("x")
    spec = _ToleranceSpec(None, 0, None, None, _DEFAULT_ABS_TOL, _DEFAULT_REL_TOL)

    # The ten-scale-coefficient case must be uniform again.
    for coefficient in (1000, 2000, 3000, 5000, 7000, 11000, 13000, 17000, 19000, 23000):
        a = coefficient * x
        b = coefficient * x + sympy.Float("0.3")
        result = _numeric_fallback(a, b, 5.0, spec)
        assert result is not None
        equal, detail = result
        assert equal, f"coefficient={coefficient}: expected equal (sampling path), got {detail}"

    # And the no-free-symbols branch — a genuine answer comparison — must
    # still enforce the rounding-agreement check: `1.0` vs `1.5` at
    # `dp=0` reaches `_numeric_fallback` directly here (bypassing
    # `equivalent()`'s simplify path, which resolves it first for plain
    # numbers) and must still be rejected.
    one = sympy.Float("1.0")
    one_and_a_half = sympy.Float("1.5")
    result = _numeric_fallback(one, one_and_a_half, 5.0, spec)
    assert result is not None
    equal, _detail = result
    assert not equal, "a genuine answer comparison must still enforce rounding agreement"


def _round_to_sig_figs_reference(value: float, sig_figs: int) -> float:
    """A from-scratch reference for :func:`_round_to_sig_figs`, used to
    verify it independently rather than by re-deriving the same formula.

    Deliberately a DIFFERENT code path from the function under test: uses
    `Decimal.adjusted()` (the position of the decimal's own most
    significant digit) rather than `math.floor(math.log10(...))` for the
    exponent, and `Decimal.quantize(..., ROUND_HALF_UP)` rather than
    `_round_half_up`'s `scaleb`/`quantize` pairing, though both end up
    calling the same `ROUND_HALF_UP` primitive — round-half-up is a single
    well-defined operation, so there is no independent *algorithm* to
    round-half-up other than the primitive itself (I8 re-review round 9:
    the previous version of this reference used `%g` string formatting,
    which follows Python's own half-to-even convention on the double's
    exact binary value — it agreed with the OLD half-to-even
    `_round_to_sig_figs`, but necessarily disagrees with the new half-up
    one at exact decimal midpoints like `13.95`, which is why this
    reference had to change alongside the fix rather than catching it).
    """
    if value == 0:
        return 0.0
    decimal_value = Decimal(repr(value))
    exponent = decimal_value.adjusted()
    quantum = Decimal(1).scaleb(exponent - sig_figs + 1)
    return float(decimal_value.quantize(quantum, rounding=ROUND_HALF_UP))


def test_round_to_sig_figs_matches_an_independent_decimal_reference() -> None:
    """`_round_to_sig_figs` is the load-bearing half of the rounding-
    agreement check — verified against an independently-derived
    `Decimal`-based reference rather than only trusted by construction.

    Exact `==`, not `pytest.approx` (I8 re-review round 9 item 2c NIT):
    the value this guards is consumed by an exact `==` in
    `_rounds_agree_at_stated_precision`, so the property that matters is
    bit-equality, and `pytest.approx`'s default 1e-6 relative tolerance
    would admit a deviation that property cannot survive.
    """
    for value in (9, 13.95, 100.0, 150.0, 1.0, 1.5, 0.5, 0.25, 31.4, 0.0012, 1234.5, -13.95, -9.0):
        for sig_figs in (1, 2, 3, 4):
            got = _round_to_sig_figs(float(value), sig_figs)
            want = _round_to_sig_figs_reference(float(value), sig_figs)
            assert got == want, f"_round_to_sig_figs({value}, {sig_figs}) = {got}, expected {want}"


def test_percent_tolerance_credibility_boundary_is_confined_to_the_discard_threshold() -> None:
    """The percent path has the same CREDIBILITY boundary as the absolute
    path (`_plausible_or_discard_absolute_candidate`), not a monotonicity
    defect to engineer away — derive it, don't hand-pick two points.

    Round 6 briefly capped an over-threshold percent to
    `_MAX_PLAUSIBLE_RELATIVE_TOLERANCE` instead of discarding it, reasoning
    from "100" vs "115" being `equal_proven` at 19% and `not_equal` at 20%
    that a wider stated percent must never be stricter. That is true only
    within the CREDIBLE range: capping made `tolerance="50%"` — a value
    nothing legitimately states — grant the full 20% window on its
    strength, converting an untrustworthy field into real leniency ("100"
    vs "115", a genuine 15% error, became `equal_proven`). Reverted to
    discarding: a stated percent at or above the threshold is not believed
    at all, matching the absolute path. This pins that the resulting
    cliff is confined to exactly the credibility threshold, drops all the
    way to zero leniency, and does not reappear anywhere else.
    """
    parsed_relative = [(pct, _parse_tolerance(f"{pct}%").relative) for pct in range(1, 41)]
    drops = [
        i
        for i in range(len(parsed_relative) - 1)
        if (parsed_relative[i + 1][1] or 0.0) < (parsed_relative[i][1] or 0.0)
    ]
    # Exactly one, not merely "at most one" (I8 re-review round 6
    # SHOULD-FIX 2's mirror on the percent path): the sweep is 1-40%,
    # which always straddles the 20% threshold, so the boundary must
    # actually exist — `== 1` closes the same vacuous-if-deleted hole as
    # the dp boundary test above.
    assert len(drops) == 1, f"expected exactly one drop, found {drops}: {parsed_relative}"
    if drops:
        (i,) = drops
        pct_before = parsed_relative[i][0]
        pct_after = parsed_relative[i + 1][0]
        assert pct_after == pytest.approx(_MAX_PLAUSIBLE_RELATIVE_TOLERANCE * 100, abs=1), (
            f"the one permitted drop must sit at the discard threshold, found it at {pct_after}%"
        )
        relative_before = parsed_relative[i][1]
        assert relative_before is not None and relative_before < 1.0
        assert parsed_relative[i + 1][1] is None, (
            f"credibility boundary must drop to NO leniency (discard), not a partial cap "
            f"— got {parsed_relative[i + 1][1]} at {pct_after}%"
        )
        assert pct_before < pct_after

    # Below the threshold, the parsed relative tolerance must itself be
    # monotonic in the stated percent (this half is a plain `value/100`,
    # no cap/discard tier — verified directly, not assumed).
    below = [rel for pct, rel in parsed_relative if rel is not None]
    assert below == sorted(below)

    # And confirm the behavioural end-to-end boundary lands at the same
    # place: exactly one not_equal->equal transition below the threshold,
    # then not_equal (no leniency) at and above it, never re-admitted.
    results = [
        (pct, equivalent("100", "115", tolerance=f"{pct}%").kind in _EQUAL_KINDS)
        for pct in range(1, 41)
    ]
    admitted = [pct for pct, ok in results if ok]
    if admitted:
        assert max(admitted) < _MAX_PLAUSIBLE_RELATIVE_TOLERANCE * 100, (
            f"a percent at/above the discard threshold must never be admitted: {results}"
        )


# ---------------------------------------------------------------------------
# 4. Golden mark-scheme calculated_answer parsing (criterion 2 — deferred)
# ---------------------------------------------------------------------------


def _golden_calculated_answers() -> list[tuple[str, float, str]]:
    """Every (fixture path, value, unit) with a non-null calculated_answer."""
    found: list[tuple[str, float, str]] = []
    root = Path(__file__).parent / "golden"
    for path in sorted(glob.glob(str(root / "*" / "mark_scheme.json"))):
        scheme = json.loads(Path(path).read_text())
        for question in scheme.get("questions", []):
            for point in question.get("answer_points") or []:
                calc = point.get("calculated_answer")
                if calc and calc.get("value") is not None:
                    raw_unit = calc.get("unit")
                    unit = raw_unit.strip() if isinstance(raw_unit, str) else ""
                    found.append((path, float(calc["value"]), unit))
    return found


#: Expected SymPy expression for each DISTINCT (value, unit) pair across
#: the golden fixtures, keyed the same way the fixtures store it. Checked
#: for structural equality, not `is not None`.
#:
#: The `(8.9, "g/cm^3")` entry previously read `(8.9, "g/cm")`, and the note
#: here described why: all three
#: `tests/golden/0625_s20_qp_31_theory_*/mark_scheme.json` fixtures stored
#: `"unit": "g/cm\n"` — a truncated `g/cm³` plus a trailing newline — and
#: this table deliberately expected the text the fixture actually contained
#: rather than the unit it should have had, so as not to paper over a real
#: fixture defect from a test. That defect has since been FIXED in all three
#: fixtures (they now store `"g/cm^3"`), which is what the shape guard in
#: `test_golden_calculated_answer_parse_correctness_deferred_to_i10` exists
#: to catch: it failed with "fixtures have [(8.9, 'g/cm^3')] ... expectation
#: table has [(8.9, 'g/cm')]". The guard worked; the table is what needed
#: updating. Nothing about the parse is in question here — `8.9 g/cm^3` and
#: the corrupted `8.9 g/cm` both parsed correctly all along.
_m, _g, _s, _cm, _mg = sympy.symbols("m g s cm mg")
_EXPECTED_GOLDEN_PARSES: dict[tuple[float, str], sympy.Expr] = {
    (0.19, "cm"): 0.19 * _cm,
    (8.9, "g/cm^3"): 8.9 * _g / _cm**3,
    (31.0, "m/s"): 31.0 * _m / _s,
    (3.0, "N"): 3.0 * sympy.Symbol("N"),
    (16.0, "V"): 16.0 * sympy.Symbol("V"),
    (81.0, ""): sympy.Float(81.0),
    (4.5, "mg"): 4.5 * _mg,
    (0.375, ""): sympy.Float(0.375),
    (9.6, ""): sympy.Float(9.6),
    (1.25, ""): sympy.Float(1.25),
    (28.89, ""): sympy.Float(28.89),
    (81.1, ""): sympy.Float(81.1),
    (30.45, ""): sympy.Float(30.45),
}


def test_golden_calculated_answer_parse_correctness_deferred_to_i10() -> None:
    """Report, do not claim criterion 2 is met.

    I10 (Gemini-primary mark-scheme parsing) has not landed —
    `corpus/mark-schemes/*.json` has zero populated `calculated_answer`
    objects, checked directly. This measures parse CORRECTNESS against the
    best available proxy: the hand-authored golden fixtures using the same
    schema. That proxy is much smaller than its raw count suggests — see
    the reported paper/distinct-pair counts below — so this is a lower
    bound with caveats attached, not the criterion.
    """
    entries = _golden_calculated_answers()
    assert entries, "expected at least one calculated_answer fixture to measure against"

    papers = {Path(path).parent.name.rsplit("_theory_", 1)[0] for path, _v, _u in entries}
    distinct_pairs = sorted({(value, unit) for _path, value, unit in entries})

    assert set(distinct_pairs) == set(_EXPECTED_GOLDEN_PARSES), (
        "the golden fixtures changed shape — update _EXPECTED_GOLDEN_PARSES "
        f"to match: fixtures have {sorted(set(distinct_pairs) - set(_EXPECTED_GOLDEN_PARSES))} "
        f"not in the expectation table, expectation table has "
        f"{sorted(set(_EXPECTED_GOLDEN_PARSES) - set(distinct_pairs))} not in the fixtures"
    )

    correct = 0
    failures: list[str] = []
    for value, unit in distinct_pairs:
        text = f"{value} {unit}".strip()
        parsed = parse_expr_safe(text)
        expected = _EXPECTED_GOLDEN_PARSES[(value, unit)]
        if parsed is not None and sympy.simplify(parsed - expected) == 0:
            correct += 1
        else:
            failures.append(f"{text!r}: parsed {parsed!r}, expected {expected!r}")

    rate = correct / len(distinct_pairs)
    print(
        f"\nI8 criterion 2 (DEFERRED to I10, not met by this measurement): "
        f"{len(entries)} raw calculated_answer entries across {len(papers)} paper(s) "
        f"collapse to {len(distinct_pairs)} distinct (value, unit) pairs; "
        f"{correct}/{len(distinct_pairs)} ({rate:.1%}) parsed to the structurally "
        "correct SymPy expression. This is a lower bound against a hand-authored "
        "proxy corpus, not the Gemini-parsed golden corpus the acceptance "
        "criterion names — re-measure once I10 lands."
    )
    assert not failures, f"parse correctness failures: {failures}"


# ---------------------------------------------------------------------------
# 5. Timeout, determinism, and resource-exhaustion behaviour (criterion 3)
# ---------------------------------------------------------------------------


def _slow_cosine_sum_identity(n: int) -> tuple[sympy.Expr, sympy.Expr]:
    """A real trigonometric identity SymPy's `simplify` struggles to prove.

    sum_{k=1}^{n} cos(kx) = sin(nx/2) * cos((n+1)x/2) / sin(x/2)

    `simplify` does not special-case this Dirichlet-kernel-style sum, so it
    spends real, non-trivial wall-clock time attempting (and, at this size,
    failing) to reduce the difference to zero — a genuine pathological
    input rather than a mocked delay.
    """
    x = sympy.Symbol("x")
    lhs = sum(sympy.cos(k * x) for k in range(1, n + 1))
    rhs = (
        sympy.sin(sympy.Rational(n, 2) * x)
        * sympy.cos(sympy.Rational(n + 1, 2) * x)
        / sympy.sin(x / 2)
    )
    return lhs, rhs


def test_slow_simplify_falls_back_to_numeric_within_budget() -> None:
    """Isolated in a subprocess so the production defaults are exercised
    end-to-end through a real process boundary, not just in-process
    (I8 re-review round 5 SHOULD-FIX 1).

    Asserted on the outcome, not the clock (#257): this used to also bound
    `subprocess.run`'s own `timeout=4`, on the theory that a fresh
    interpreter has no abandoned CPU-bound threads to contend with, so a
    legitimate run (~2.48s: production `simplify_timeout` 2.0s +
    `numeric_timeout` 0.5s + interpreter/import overhead) sits with real
    margin below a broken one (~5.04-5.39s, `simplify` running unbounded --
    I8 re-review round 6). That margin assumed the only contention was
    in-process GIL contention; under 2x CPU oversubscription on the host
    machine, the whole subprocess gets less wall-clock time regardless of
    whether the in-process timeout logic is honoured, and a legitimate run
    measured past 4s there. The `method`/`kind`/`auto_awardable` asserts
    below are what prove correctness: the production defaults must still
    route to the numeric fallback through a real subprocess. The bound that
    a tight budget actually caps `simplify`'s worst-case wall time is
    already proven, with a generous margin, by
    `test_simplify_timeout_is_configurable_and_bounds_worst_case`; this test
    does not need to re-prove that property under a tight one too, so
    `timeout=30` below is only a hang guard.
    """
    script = (
        "import sys; sys.path.insert(0, '.'); import sympy\n"
        "from lemely.core.equivalence import equivalent\n"
        "x = sympy.Symbol('x')\n"
        "n = 25\n"
        "lhs = sum(sympy.cos(k * x) for k in range(1, n + 1))\n"
        "rhs = (sympy.sin(sympy.Rational(n, 2) * x) * sympy.cos(sympy.Rational(n + 1, 2) * x)"
        " / sympy.sin(x / 2))\n"
        "v = equivalent(lhs, rhs)\n"
        "print(f'{v.method.value if v.method else None}|{v.kind.value}|{v.auto_awardable}')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], check=True, timeout=30, capture_output=True, text=True
    )
    method, kind, auto_awardable = result.stdout.strip().split("|")
    assert method == EquivalenceMethod.NUMERIC.value
    assert kind == VerdictKind.EQUAL_SAMPLED.value
    assert auto_awardable == "False"


@pytest.fixture
def declined_simplify(monkeypatch: pytest.MonkeyPatch):
    """Force `equivalent` onto the numeric path by construction (#257).

    `_run_bounded` returns ``None`` for the simplify step -- exactly what a
    timeout returns -- without starting a thread, and gives every other
    bounded step a 30 s budget. The tests that use this are about the
    SAMPLER, not the budgets; racing a real `simplify` against 0.05 s turned
    runner load into a red build (CI run 36155845596, 3.13 only).
    """
    from lemely.core import equivalence as eq

    real = eq._run_bounded

    def bounded(func, timeout):
        if func.__name__ == "_simplify_diff":
            return None
        return real(func, 30.0)

    monkeypatch.setattr(eq, "_run_bounded", bounded)


def test_simplify_timeout_is_configurable_and_bounds_worst_case() -> None:
    """Same mechanism, driven down to a small budget so the test is fast.

    Proves the timeout parameter — not just its 2.0s production default —
    actually bounds `simplify`'s runtime, using the same real slow
    expression rather than a mocked sleep.

    The numeric budget is generous (#257): this test is about the SIMPLIFY
    budget bounding wall time, and a 0.5 s numeric budget could also expire
    on a loaded runner and turn a passing simplify bound into UNPARSEABLE.
    The `elapsed < 5.0` bound still proves `simplify_timeout` was honoured:
    the numeric comparison on this pair takes milliseconds.
    """
    lhs, rhs = _slow_cosine_sum_identity(25)

    started = time.monotonic()
    verdict = equivalent(lhs, rhs, simplify_timeout=0.05, numeric_timeout=30.0)
    elapsed = time.monotonic() - started

    # Generous (see the note on this pattern in
    # test_real_double_timeout_is_unparseable_never_not_equal): this suite
    # abandons many CPU-bound daemon threads elsewhere, whose GIL
    # contention can delay this thread past a tight budget when the whole
    # file runs together.
    assert elapsed < 5.0
    assert verdict.method is EquivalenceMethod.NUMERIC
    assert verdict.kind is VerdictKind.EQUAL_SAMPLED


def test_sampler_seed_is_deterministic_for_the_same_pair() -> None:
    """The seed itself must be reproducible — checked directly, with no
    sample size needed at all.

    A previous version of this determinism claim raced a 0.001s
    `simplify_timeout` against `simplify(sqrt(x**2) - x)`, which itself
    resolves in under a millisecond ~98-100% of the time on this machine
    (measured 0-3 numeric-path calls out of 200 across 5 runs) — so the
    200-repetition loop was almost entirely re-testing the SIMPLIFY path,
    not the sampler, and would have passed unchanged on the fully unseeded
    pre-fix code (measured 6/6 passes with `_sampler_seed` monkeypatched to
    `random.randrange`). Testing `_sampler_seed` directly removes the
    race entirely (I8 re-review round 3 MUST-FIX 3).
    """
    x = sympy.Symbol("x")
    a, b = sympy.sqrt(x**2), x
    assert _sampler_seed(a, b) == _sampler_seed(a, b)


def test_numeric_fallback_is_deterministic_across_repeated_calls(declined_simplify: None) -> None:
    """The sampler must not flip its verdict run to run on the SAME pair,
    proven by forcing every call through the ACTUAL numeric path (#257: the
    `declined_simplify` fixture, not a 0.05 s race that a loaded runner can
    lose on BOTH budgets and report UNPARSEABLE). `method` is asserted on
    every iteration, so this cannot silently degrade into re-testing
    `simplify`; and `simplify_timeout=100.0` proves the path is forced by
    the fixture, not by the clock -- with the real `_run_bounded`, a 100 s
    budget would let `simplify` finish and the first assertion would fail.
    """
    lhs, rhs = _slow_cosine_sum_identity(25)

    kinds = set()
    for _ in range(10):
        verdict = equivalent(lhs, rhs, simplify_timeout=100.0, numeric_timeout=3.0)
        assert verdict.method is EquivalenceMethod.NUMERIC, (
            "did not reach the numeric path — this run tests nothing about the sampler"
        )
        kinds.add(verdict.kind)
    assert kinds == {VerdictKind.EQUAL_SAMPLED}, f"verdict flipped across repeated calls: {kinds}"


def test_real_double_timeout_is_unparseable_never_not_equal() -> None:
    """A genuine double timeout through the real code path — no
    monkeypatching either method — must resolve to ``UNPARSEABLE``, never
    ``NOT_EQUAL``.

    A resource failure means this module knows nothing about the answer;
    ``NOT_EQUAL`` is a positive claim that the student is wrong, which
    under the I6 policy withholds an awarded A-mark and opens a review.

    `Si`/`Ci` (sine/cosine integral) have no elementary closed form, so
    `simplify` spends real time on the difference without resolving it, and
    `evalf` performs real numeric quadrature per substitution rather than a
    cheap closed-form evaluation — a genuine double timeout, not a mocked
    delay on either method.

    Isolated in a subprocess (I8 re-review round 5 SHOULD-FIX 1,
    corrected — same reasoning as
    ``test_slow_simplify_falls_back_to_numeric_within_budget``): a margin
    generous enough for this suite's GIL contention (observed up to ~1.5s
    here) no longer discriminates against the regression this test exists
    to catch, but removing the timing assertion entirely throws away a
    real gate rather than isolating it. A legitimate run measures ~0.48s
    here; the regression (either timeout silently not honoured) measures
    ~1.14s.

    The timing assertion is on the CALL's OWN elapsed time, measured
    INSIDE the subprocess with ``time.monotonic()``, not on
    ``subprocess.run``'s outer wall-clock ``timeout=`` (I8 re-review round
    7 SHOULD-FIX 2 — the previous version used `timeout=1` as the
    correctness gate itself, with ~0.49s of slack over the ~0.51s
    legitimate case; under real CPU contention this measured a genuine
    flake, 2 failures in 7 runs on an otherwise idle machine and 2 of 5
    under deliberate load, because interpreter startup and import time —
    not the comparison itself — is also inside that outer window and
    varies with contention). Measuring only the `equivalent()` call's own
    elapsed time removes that source of variance entirely, and
    `subprocess.run`'s own `timeout=` is now a generous safety net against
    a genuine hang, not the discriminator — it plays no role in whether
    this test passes or fails on a normal run.
    """
    script = (
        "import sys; sys.path.insert(0, '.'); import sympy, time\n"
        "from lemely.core.equivalence import equivalent\n"
        "t, x = sympy.symbols('t x')\n"
        "lhs = sympy.Integral(sympy.sin(t) / t, (t, 0, x))\n"
        "rhs = sympy.Integral(sympy.cos(t) / t, (t, 0, x))\n"
        "started = time.monotonic()\n"
        "v = equivalent(lhs, rhs, simplify_timeout=0.05, numeric_timeout=0.01)\n"
        "elapsed = time.monotonic() - started\n"
        "print(f'{v.method}|{v.kind.value}|{v.detail}|{elapsed}')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], check=True, timeout=30, capture_output=True, text=True
    )
    method, kind, detail, elapsed_str = result.stdout.strip().split("|", 3)
    assert method == "None"
    assert kind == VerdictKind.UNPARSEABLE.value
    elapsed = float(elapsed_str)
    # A legitimate double timeout is ~0.06s (the two budgets) plus
    # scheduling slack; the regression this test exists to catch (~1.14s,
    # a real double timeout not honoured) sits an order of magnitude above
    # it — measured on the CALL alone, isolated from interpreter
    # startup/import jitter and this suite's own contention.
    assert elapsed < 1.0, f"double timeout was not honoured within budget: {elapsed:.3f}s"
    assert "timeout" in detail


def test_pool_saturation_does_not_degrade_a_later_unrelated_call() -> None:
    """A shared, never-reclaimed thread pool means an abandoned
    pathological worker keeps consuming a slot forever, so a later,
    completely unrelated call degrades too. Each call now gets its own
    thread (see ``_run_bounded``), so five consecutive slow calls must not
    affect a sixth, trivial one.
    """
    lhs, rhs = _slow_cosine_sum_identity(22)
    for _ in range(5):
        equivalent(lhs, rhs)  # each abandons a ~2.5s background thread

    started = time.monotonic()
    verdict = equivalent("2+2", "4")
    elapsed = time.monotonic() - started

    # Generous for the same reason noted on the other timing assertions in
    # this section: many OTHER tests in this file also abandon multi-second
    # CPU-bound daemon threads, and their accumulated GIL contention can
    # push even a trivial comparison's wall-clock time up when the whole
    # file runs together. The distinction this test exists to prove — a
    # bounded few seconds vs. the old shared-pool's unbounded contagion
    # (measured 89.6s) — holds regardless.
    assert elapsed < 8.0, f"took {elapsed:.2f}s — a later call should not be degraded"
    assert verdict.kind is VerdictKind.EQUAL_PROVEN
    assert verdict.auto_awardable


def test_interpreter_shutdown_is_not_blocked_by_an_abandoned_computation() -> None:
    """A `ThreadPoolExecutor`'s workers are not daemon threads, and
    `concurrent.futures.thread` registers an `atexit` hook that joins every
    worker any pool ever started — so abandoning one pathological
    `simplify` call left the WHOLE PROCESS blocked at exit for as long as
    that computation kept running in the background (measured 105.44s of
    total wall time for a call that itself returned in 2.05s). Run as a
    subprocess so "the process exits promptly" is actually observable —
    the parent test process would not itself hang or un-hang based on
    whether ITS OWN interpreter shutdown is blocked.
    """
    script = (
        "import sys; sys.path.insert(0, '.'); import sympy\n"
        "from lemely.core.equivalence import equivalent\n"
        "x = sympy.Symbol('x')\n"
        "n = 25\n"
        "lhs = sum(sympy.cos(k * x) for k in range(1, n + 1))\n"
        "rhs = (sympy.sin(sympy.Rational(n, 2) * x) * sympy.cos(sympy.Rational(n + 1, 2) * x)"
        " / sympy.sin(x / 2))\n"
        "equivalent(lhs, rhs)\n"
    )
    started = time.monotonic()
    subprocess.run([sys.executable, "-c", script], check=True, timeout=15)
    elapsed = time.monotonic() - started
    # Generous: the comparison itself takes ~2.05s (simplify_timeout +
    # near-instant numeric fallback), plus interpreter start/import
    # overhead. Under the old ThreadPoolExecutor-based `_run_bounded`, this
    # was 105s.
    assert elapsed < 10.0, f"process took {elapsed:.2f}s to exit — shutdown was blocked"


# ---------------------------------------------------------------------------
# parse_expr_safe edge cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", [None, "", "   ", "x" * 501])
def test_parse_expr_safe_rejects_degenerate_input(text: str | None) -> None:
    assert parse_expr_safe(text) is None


def test_parse_expr_safe_accepts_already_valid_arithmetic() -> None:
    expr = parse_expr_safe("2 + 2")
    assert expr == sympy.Integer(4)


@pytest.mark.parametrize(
    "text",
    [
        "factorial(100000)",
        "Integral(exp(-x**2),(x,-oo,oo))",
        "2**100000000",
        "9^9^9",
        "2**3**4",
        "2^(999*999*999)",
        "2^(10*10*10*10*10*10*10*10*10)",
        "(2+x-x)^(999*999*999)",
        "(10^300*10^300*10^300*10^300)^999",
        "(10^300*10^300*10^300*10^300+1)^999",
        "2^(999!)",
        "(999!)!",
        "9999999!",
        "9 999 999!",
        "2^(999*999*999*(x-1))",
        "2^(999*999*999*(x-y))",
        "(10^300+1)^1000*(10^300+3)^1000",
        "(10^300+1)^14*(10^300+3)^14",
        "(" + "*".join(["(10^300+1)^1000"] * 10) + "*1)^2",
        "2^((999x-999)(999y-999)(999z-999))",
        "exp(999*999*999*ln(2)*(x-1))",
    ],
    ids=[
        "disallowed-function",
        "disallowed-function-nested",
        "huge-exponent",
        "exponent-tower-caret",
        "exponent-tower-double-star",
        "computed-exponent",
        "computed-exponent-products",
        "computed-exponent-symbolic-base",
        "result-too-many-bits",
        # The row above is already caught by `_EXPONENT_TOWER_RE` (`^300)^999`
        # matches through its optional `\)?`); this one has no tower shape, so
        # only the structural result-bits bound in `_pow_would_explode` stops it.
        "result-too-many-bits-no-tower",
        "factorial-exponent",
        "factorial-of-parenthesised",
        "factorial-too-large",
        "factorial-too-large-thousands-spaced",
        # Review round 1: 0 at the all-ones point, so the walk passes them; the
        # evaluated `2**(997002999*x - 997002999)` then froze `equivalent`.
        "computed-exponent-times-difference",
        "computed-exponent-times-two-symbol-difference",
        # Review round 1: each power within bounds, their product (a 1,993,157-bit
        # Integer) is not; `str()` of it raised in the caller. The second row is
        # small enough per power for the walk and caught by the result-size bound.
        "product-result-too-large",
        "product-result-too-large-within-pow-bound",
        "product-of-bounded-powers",
        "product-of-differences-in-exponent",
        "exp-of-log",
    ],
)
def test_parse_expr_safe_rejects_dangerous_constructs(text: str) -> None:
    assert parse_expr_safe(text) is None


@pytest.mark.parametrize(
    "text",
    ["2^(999*999*999)", "2^(10*10*10*10*10*10*10*10*10)", "(2+x-x)^(999*999*999)"],
    ids=["computed-exponent", "computed-exponent-products", "computed-exponent-symbolic-base"],
)
def test_computed_exponents_are_refused_before_any_big_int_work(text: str) -> None:
    """Triage F2 (2026-09-29): ``2^(999*999*999)`` used to pass both regexes
    and return a 997,003,000-bit Integer after 3.79 s, during which a
    heartbeat thread stalled 3.83 s -- the GIL was held, so ``_run_bounded``'s
    timeout could not have helped. The refusal must come from the structural
    walk on the UNEVALUATED parse -- before the evaluated parse, the only
    step that does big-int work, ever runs -- and not from the worker's
    timeout (which would kill the worker, so its pid must survive).

    Asserted on the step, not the clock (review round 2): this test used to
    bound the elapsed time (< 0.5 s) and failed once under load from other
    test runs while passing alone. ``last_outcome`` says which stage ended
    the parse; the generous timeout only keeps a loaded machine from turning
    a millisecond walk into a kill. Remove the walk's guard and the outcome
    becomes ``refused-evaluated`` -- after the big-int work -- and this goes
    red."""
    from lemely.core import equivalence as eq

    assert parse_expr_safe("2+2") == sympy.Integer(4)  # a live worker whose pid must survive
    worker_pid = eq._PARSE_WORKER.pid()
    assert parse_expr_safe(text, timeout=30.0) is None
    assert eq._PARSE_WORKER.last_outcome == "refused-unevaluated"
    assert eq._PARSE_WORKER.pid() == worker_pid, "refused by a kill, not by the walk"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2^(1/2)", sympy.sqrt(2)),
        ("10^(-3)", sympy.Rational(1, 1000)),
        ("2^(3*4)", sympy.Integer(4096)),
        ("5!", sympy.Integer(120)),
        ("2^999", sympy.Integer(2) ** 999),
        ("1000!", sympy.factorial(1000)),
    ],
    ids=[
        "fractional-exponent",
        "negative-exponent",
        "small-computed-exponent",
        "small-factorial",
        "largest-literal",
        "largest-factorial-2568-digits",
    ],
)
def test_bounded_exponents_still_parse(text: str, expected: sympy.Expr) -> None:
    assert parse_expr_safe(text) == expected


def test_symbolic_exponents_still_parse() -> None:
    x, n = sympy.symbols("x n")
    assert parse_expr_safe("x^(n+1)") == x ** (n + 1)


@pytest.mark.parametrize(
    "text",
    [
        "(1/(1-v^2/c^2))^(1/2)",
        "(x/(x-1))^2",
        "(m/(M-m))^2",
        "2^(1/(n-1))",
        "((a+b)/(a-b))^2",
    ],
    ids=[
        "lorentz-factor",
        "ratio-squared",
        "mass-ratio-squared",
        "singular-exponent",
        "sum-over-difference",
    ],
)
def test_answers_singular_when_every_symbol_is_one_still_parse(text: str) -> None:
    """The structural bound substitutes 1 for EVERY symbol, so any difference
    of symbols (``M - m``, ``1 - v²/c²``) is 0 there and the power's base or
    exponent is ``zoo``/``nan`` -- a property of the substitution point, not
    of the answer. Refusing those turned the Lorentz factor and every
    ``(a/(a-b))^2`` into UNPARSEABLE; they must parse exactly as before."""
    from lemely.core import equivalence as eq

    expected = eq._parse_normalized(eq._normalize_text(text), evaluate=True)
    assert parse_expr_safe(text) == expected


def _alive(pid: int | None) -> bool:
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


#: Prelude for the parse-worker timing tests below, each run in a FRESH
#: interpreter for the same reason as
#: `test_slow_simplify_falls_back_to_numeric_within_budget`: this file
#: abandons CPU-bound daemon threads elsewhere, and their GIL contention
#: inflates in-process wall-clock and heartbeat measurements (observed: a
#: correct 1.0 s kill measured 2.06 s in-process, after the pool-saturation
#: test). `timed` runs a call while a 50 ms heartbeat thread ticks and
#: reports the call's wall time and the heartbeat's longest gap -- a gap far
#: above 50 ms means something held the GIL in THIS process.
_WORKER_TIMING_PRELUDE = """
import itertools, json, multiprocessing, os, sys, threading, time
sys.path.insert(0, '.')
from lemely.core import equivalence as eq
from lemely.core.equivalence import parse_expr_safe

def timed(call):
    beats, stop = [], threading.Event()
    def beat():
        while not stop.is_set():
            beats.append(time.monotonic())
            time.sleep(0.05)
    thread = threading.Thread(target=beat, daemon=True)
    thread.start()
    started = time.monotonic()
    result = call()
    elapsed = time.monotonic() - started
    stop.set()
    thread.join()
    return result, elapsed, max((b - a for a, b in itertools.pairwise(beats)), default=0.0)

def alive(pid):
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True

warm = parse_expr_safe("2+2")  # start the worker: time the call below, not a start
pid_before = eq._PARSE_WORKER.pid()
"""


def _run_worker_timing_script(body: str, *, timeout: float = 60) -> dict[str, object]:
    script = _WORKER_TIMING_PRELUDE + body
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        timeout=timeout,
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_the_parse_worker_kills_a_runaway_parse_and_keeps_the_parent_responsive() -> None:
    """Triage F2, user decision 3: the guards can be bypassed by something
    nobody has thought of yet, so the parse runs in a child that can be
    KILLED. In-process, ``2**(999*999*999)`` held the GIL for 3.8 s and a
    50 ms heartbeat stalled 3.83 s; through the worker the parent gets
    ``None`` at the timeout and its heartbeat never misses a beat. ``vet=False``
    skips the structural bound, which would refuse this text first."""
    out = _run_worker_timing_script(
        """
result, elapsed, gap = timed(lambda: eq._PARSE_WORKER.parse("2**(999*999*999)", 1.0, vet=False))
print(json.dumps({
    "warm": str(warm),
    "pid_before": pid_before,
    "result": repr(result),
    "elapsed": elapsed,
    "gap": gap,
    "killed": not alive(pid_before),
    "pid_after_kill": eq._PARSE_WORKER.pid(),
    "still_a_child": pid_before in [c.pid for c in multiprocessing.active_children()],
    "respawned": str(parse_expr_safe("2+2")),
    "pid_after_respawn": eq._PARSE_WORKER.pid(),
}))
"""
    )
    assert out["warm"] == "4" and out["pid_before"] is not None
    assert out["result"] == "None"
    assert 0.9 < out["elapsed"] < 1.6, f"the timeout was not honoured: {out['elapsed']:.2f}s"  # type: ignore[operator]
    assert out["gap"] < 0.25, f"the parent stalled for {out['gap']:.2f}s -- the GIL was held"  # type: ignore[operator]
    # Killed AND joined: no zombie, not tracked as a child any more.
    assert out["killed"] is True
    assert out["pid_after_kill"] is None
    assert out["still_a_child"] is False
    # The next call respawns the worker transparently.
    assert out["respawned"] == "4"
    assert out["pid_after_respawn"] not in (None, out["pid_before"])


@pytest.mark.parametrize(
    "text",
    ["2^(999*999*999 + 0/(n-1))"],
    ids=["exponent-singular-at-ones"],
)
def test_what_the_walk_cannot_bound_never_stalls_the_caller(text: str) -> None:
    """Every guard ON, through ``parse_expr_safe``: ``0/(n-1)`` is ``nan``
    when n is 1, so the walk cannot bound this exponent and leaves it to the
    evaluated parse -- which folds ``0/(n-1)`` to 0 and would build
    ``2**997002999``. It must come back ``None`` at the timeout without the
    caller's heartbeat noticing: the walk and the parse run in the killable
    worker. (A walk that simply refused it would pass the first and last
    asserts, which is why the kill is asserted too: this test is about the
    backstop.) The product-of-powers input that used to share this test --
    each ``(10^300+1)^1000`` within the old 1M-bit bound, 33.5 s and a 2.5 s
    heartbeat gap for 25 terms when the walk ran in the caller -- is now
    refused per power by the lowered bound (see
    ``test_parse_expr_safe_rejects_dangerous_constructs``)."""
    out = _run_worker_timing_script(
        f"""
result, elapsed, gap = timed(lambda: parse_expr_safe({text!r}, timeout=1.0))
print(json.dumps({{
    "result": repr(result), "elapsed": elapsed, "gap": gap, "killed": not alive(pid_before),
}}))
"""
    )
    assert out["result"] == "None"
    assert out["killed"] is True, "never reached the worker's timeout"
    assert 0.9 < out["elapsed"] < 1.6, f"the timeout was not honoured: {out['elapsed']:.2f}s"  # type: ignore[operator]
    assert out["gap"] < 0.25, f"the caller stalled for {out['gap']:.2f}s -- the GIL was held"  # type: ignore[operator]


def test_parse_expr_safe_never_raises_on_a_base_whose_magnitude_overflows_a_float() -> None:
    """``float(exp(exp(exp(exp(10)))))`` is ``inf`` -- not an OverflowError --
    and ``int(math.log2(inf))`` raised OverflowError straight out of
    ``parse_expr_safe``, which promises never to raise. A base too large for
    a float is too large to raise to a power: refused."""
    assert parse_expr_safe("exp(exp(exp(exp(10))))^2") is None


def test_the_parse_worker_survives_a_memory_error() -> None:
    """A parse that breaches the child's address-space limit comes back as
    ``None`` -- not a crash, not a respawn: the child catches MemoryError.
    ``vet=False`` skips the structural bound, which would refuse this text
    first; without the limit the child would return a 125 MB Integer.

    Asserted on the outcome, not the clock (review round 2): the MemoryError
    arrives after ~2.6 s of big-int work normally, but after more than 10 s
    with the CPUs 2x oversubscribed, where the old 10 s timeout killed the
    worker first and failed this test for a reason unrelated to memory. The
    timeout is generous so only a hang could reach it."""
    from lemely.core import equivalence as eq

    assert parse_expr_safe("2+2") == sympy.Integer(4)
    pid_before = eq._PARSE_WORKER.pid()
    assert eq._PARSE_WORKER.parse("2**999999999", 120.0, vet=False) is None
    assert eq._PARSE_WORKER.last_outcome == "memory"
    assert eq._PARSE_WORKER.pid() == pid_before


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("2^(999*999*999*(x-1))", "2^x"),
        ("2^(999*999*999*(x-1))", "0"),
        ("2^(999*999*999*(x-y))", "1"),
        # Every atom is 999; the expanded exponent holds -997002999.
        ("2^((999x-999)(999y-999)(999z-999))", "1"),
        # `exp` is not a Pow; simplify turns exp(N*log(2)*(x-1)) into 2**-N.
        ("exp(999*999*999*ln(2)*(x-1))", "1"),
    ],
    ids=[
        "difference-vs-power",
        "difference-vs-zero",
        "two-symbol-difference-vs-one",
        "product-of-differences-vs-one",
        "exp-of-log-vs-one",
    ],
)
def test_a_computed_exponent_never_freezes_the_caller_through_equivalent(a: str, b: str) -> None:
    """Review round 1 (Important 1). ``999*999*999*(x-1)`` is 0 at the
    all-ones point, so the unevaluated walk passes it, and the worker used to
    return ``2**(997002999*x - 997002999)`` in 0.02 s -- after which
    ``equivalent`` froze the caller for 4.2-4.7 s (``simplify`` splitting off
    ``2**-997002999`` with the GIL held, in its ``_run_bounded`` thread) or
    never returned (``sympy.expand`` of the difference, unbounded, on the
    caller's own thread). The bound must hold for the form ``simplify`` and
    ``expand`` actually see -- the EVALUATED tree -- so the answer comes back
    unparseable in milliseconds, through ``equivalent``, not only through
    ``parse_expr_safe``. Fresh interpreter, for the heartbeat."""
    out = _run_worker_timing_script(
        f"""
verdict, elapsed, gap = timed(lambda: eq.equivalent({a!r}, {b!r}))
print(json.dumps({{"kind": verdict.kind.value, "elapsed": elapsed, "gap": gap}}))
""",
        timeout=30,
    )
    assert out["kind"] == VerdictKind.UNPARSEABLE.value
    assert out["elapsed"] < 1.0, f"equivalent took {out['elapsed']:.2f}s"  # type: ignore[operator]
    assert out["gap"] < 0.25, f"the caller stalled for {out['gap']:.2f}s -- the GIL was held"  # type: ignore[operator]


@pytest.mark.parametrize(
    "text",
    [
        "e^(-t/(R*C))",
        "2^(t/5730)",
        "N0*(1/2)^(t/5730)",
        "A*e^(-0.693*t/5730)",
        "(1+r/100)^n",
        "e^(-x/(1000+y))",
        "(x+1)^1000",
        "10^(3/2)",
        "3.0×10^8",
        "x^(n+1)",
        # Review round 2: exp(...) without a log is never n**k in disguise.
        "exp(-5000/T)",
        "A*exp(-2000*t)",
        "N0*exp(-1500*t)",
        "exp(-(x-5000)^2/2)",
        "exp(-(E-2000)/(k*T))",
        "exp(2000/T)",
    ],
    ids=[
        "rc-decay",
        "half-life-power",
        "half-life-fraction",
        "decay-float-coefficient",
        "compound-interest",
        "large-number-in-denominator",
        "largest-literal-exponent",
        "fractional-numeric-power",
        "standard-form",
        "symbolic-exponent",
        "exp-boltzmann-large-constant",
        "exp-decay-large-rate",
        "exp-decay-subscripted-amplitude",
        "exp-gaussian-large-offset",
        "exp-activation-energy-offset",
        "exp-growth-large-constant",
    ],
)
def test_ordinary_exponents_pass_the_evaluated_bound(text: str) -> None:
    """The review-round-1 bound on the EVALUATED tree must not refuse the
    exponent shapes real answers use: decay and half-life forms, Float
    coefficients (inexact: never an exact big integer), a large number in a
    denominator (a negative power is an atom), and the largest literal
    exponent the regex allows."""
    from lemely.core import equivalence as eq

    expected = eq._parse_normalized(eq._normalize_text(text), evaluate=True)
    assert not eq._evaluated_would_explode(expected)
    assert parse_expr_safe(text) == expected


@pytest.mark.parametrize(
    "text",
    ["(10^300+1)^1000*(10^300+3)^1000", "(10^300+1)^14*(10^300+3)^14"],
    ids=["reviewer-input", "each-power-within-the-pow-bound"],
)
def test_an_oversized_result_is_never_returned_so_equivalent_never_raises(text: str) -> None:
    """Review round 1 (Important 2). Each power passed the walk and the
    product did not have to: the worker returned a 1,993,157-bit Integer,
    and ``equivalent(parsed, "1")`` then raised ``ValueError('Exceeds the
    limit (4300 digits) for integer string conversion')`` from ``str``/
    ``srepr`` -- which ``correction_ai`` does not catch. The worker now
    refuses any result holding a number too long to print, so the caller
    sees ``None``/UNPARSEABLE and never an exception."""
    assert parse_expr_safe(text) is None
    assert equivalent(text, "1").kind is VerdictKind.UNPARSEABLE


def test_an_interrupted_parse_never_hands_its_reply_to_the_next_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review round 1 (Minor 1). A ``KeyboardInterrupt`` while waiting for the
    reply used to escape ``except Exception`` and leave that reply pending in
    the pipe, so the NEXT caller received the previous text's expression. The
    interrupted worker must be discarded before the interrupt propagates."""
    from lemely.core import equivalence as eq

    assert parse_expr_safe("2+2") == sympy.Integer(4)
    conn = eq._PARSE_WORKER._conn
    assert conn is not None
    real_poll = conn.poll
    interrupts = [KeyboardInterrupt()]

    def poll_once_interrupted(timeout: float = 0.0) -> bool:
        if interrupts:
            raise interrupts.pop()
        return real_poll(timeout)

    monkeypatch.setattr(conn, "poll", poll_once_interrupted)
    with pytest.raises(KeyboardInterrupt):
        eq._PARSE_WORKER.parse("2+3", 1.0)
    assert parse_expr_safe("4*4") == sympy.Integer(16)


def test_a_worker_that_cannot_start_returns_none_and_backs_off(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Review round 1 (Minor 2). Where no child can be started (e.g. from a
    daemonic process), every call returns ``None`` -- never raises -- and a
    failed start is not retried for ``_PARSE_WORKER_START_COOLDOWN`` seconds,
    with one warning per failed start rather than one per call."""
    from lemely.core import equivalence as eq

    attempts: list[int] = []
    real_context = eq.multiprocessing.get_context("spawn")

    class _Unstartable:
        def __init__(self, **_kwargs: object) -> None:
            self.pid: int | None = None  # never spawned

        def start(self) -> None:
            attempts.append(1)
            raise AssertionError("daemonic processes are not allowed to have children")

    class _Context:
        Process = _Unstartable

        @staticmethod
        def Pipe() -> object:  # mirrors multiprocessing's API
            return real_context.Pipe()

    monkeypatch.setattr(eq.multiprocessing, "get_context", lambda _method: _Context())
    worker = eq._ParseWorker()
    monkeypatch.setattr(eq, "_PARSE_WORKER", worker)
    with caplog.at_level(logging.WARNING, logger=eq.__name__):
        assert parse_expr_safe("2+2") is None
        assert parse_expr_safe("3+3") is None
    assert len(attempts) == 1, "a failed start was retried inside the cool-down"
    assert len([r for r in caplog.records if "parse worker" in r.getMessage()]) == 1
    # Once the cool-down has passed, it tries again (and still returns None).
    assert worker._start_failed_at is not None
    worker._start_failed_at -= eq._PARSE_WORKER_START_COOLDOWN + 1
    assert parse_expr_safe("4+4") is None
    assert len(attempts) == 2


def test_a_caller_queued_behind_a_timeout_gets_its_own_result() -> None:
    """Review round 1 (Minor 3). Calls are serialised on one worker: a caller
    that queues behind a runaway parse must get ITS OWN expression after the
    runaway is killed and the worker respawned -- not ``None``, and not the
    runaway's late reply.

    Holds only because the queued caller's budget is 5.0 s: since #271 the
    wait for the lock counts against the caller's own ``timeout``, so at the
    1.0 s default a caller queued behind a 1.0 s runaway gets ``None`` with
    the outcome ``"busy"`` instead (see
    ``test_a_caller_that_cannot_take_the_worker_lock_returns_busy_within_its_timeout``)."""
    from lemely.core import equivalence as eq

    assert parse_expr_safe("2+2") == sympy.Integer(4)
    results: dict[str, object] = {}
    finished: dict[str, float] = {}

    def runaway() -> None:
        results["runaway"] = eq._PARSE_WORKER.parse("2**(999*999*999)", 1.0, vet=False)
        finished["runaway"] = time.monotonic()

    def ordinary() -> None:
        results["ordinary"] = parse_expr_safe("3*7", timeout=5.0)
        finished["ordinary"] = time.monotonic()

    first = threading.Thread(target=runaway)
    first.start()
    deadline = time.monotonic() + 5.0
    while not eq._PARSE_WORKER._lock.locked() and time.monotonic() < deadline:
        time.sleep(0.005)
    assert eq._PARSE_WORKER._lock.locked(), "the runaway never took the worker"
    second = threading.Thread(target=ordinary)
    second.start()
    first.join(30)
    second.join(30)
    assert results == {"runaway": None, "ordinary": sympy.Integer(21)}
    assert finished["ordinary"] >= finished["runaway"], "the second caller did not queue"


def test_a_caller_that_cannot_take_the_worker_lock_returns_busy_within_its_timeout() -> None:
    """#271. The lock wait is bounded by the caller's own ``timeout``: a
    caller that cannot take the worker within it gets ``None`` with
    ``last_outcome == "busy"`` -- it does not queue unboundedly behind a
    holder, and it never touches the child."""
    from lemely.core import equivalence as eq

    worker = eq._ParseWorker()  # private instance, never the singleton
    outcome: dict[str, object] = {}

    def call() -> None:
        started = time.monotonic()
        outcome["result"] = worker.parse("1+1", timeout=0.2)
        outcome["elapsed"] = time.monotonic() - started

    worker._lock.acquire()
    thread = threading.Thread(target=call)
    try:
        thread.start()
        thread.join(1.0)
        finished_in_time = not thread.is_alive()
    finally:
        worker._lock.release()
        thread.join(30)
        pid_before_shutdown = worker.pid()
        worker.shutdown()
    assert pid_before_shutdown is None, "a caller that never took the lock started a child"
    assert finished_in_time is True, "the caller waited past its timeout for the lock"
    assert outcome["result"] is None
    elapsed = outcome["elapsed"]
    assert isinstance(elapsed, float) and elapsed < 0.5
    assert worker.last_outcome == "busy"


def test_parse_expr_outcome_reports_each_calls_own_outcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Task 2 review, Important 1 (#271). ``parse_expr_safe`` collapses
    "busy" into ``None``, and ``last_outcome`` is one attribute every thread
    overwrites, so a caller cannot tell "not an expression" from "could not
    decide". ``parse_expr_outcome`` returns the outcome of THIS call."""
    from lemely.core import equivalence as eq

    assert eq.parse_expr_outcome("2+2") == (sympy.Integer(4), "ok")
    assert eq.parse_expr_outcome("accept 30 to 32") == (None, "refused")  # before the worker
    assert eq.parse_expr_outcome("not an answer at all, really") == (None, "error")  # in it
    assert eq.parse_expr_outcome(None) == (None, "refused")
    assert not {"refused", "error"} & eq.PARSE_UNDECIDED_OUTCOMES

    class NeverFreeLock:
        def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
            return False

        def release(self) -> None:
            raise AssertionError("released a lock that was never acquired")

    worker = eq._ParseWorker()
    worker._lock = NeverFreeLock()  # type: ignore[assignment]
    monkeypatch.setattr(eq, "_PARSE_WORKER", worker)
    worker.last_outcome = "ok"  # another thread's outcome: never this call's
    assert eq.parse_expr_outcome("24") == (None, "busy")
    assert "busy" in eq.PARSE_UNDECIDED_OUTCOMES
    assert parse_expr_safe("24") is None
    assert worker.pid() is None


class _UndecidedWorker:
    """Every parse ends with ``outcome``; the SHARED ``last_outcome`` says "ok".

    Task 6 review, Important 2: a parse that reads ``last_outcome`` after the
    call -- one attribute every thread overwrites -- instead of the call's own
    outcome gets "ok" from this worker and is caught; the real worker writes
    both, so it hides the difference.
    """

    def __init__(self, outcome: str) -> None:
        self.outcome = outcome
        self.last_outcome = "ok"

    def parse_with_outcome(
        self, text: str, timeout: float, *, vet: bool = True
    ) -> tuple[sympy.Expr | None, str]:
        return None, self.outcome

    def parse(self, text: str, timeout: float, *, vet: bool = True) -> sympy.Expr | None:
        return None

    def pid(self) -> int | None:
        return None

    def shutdown(self) -> None:
        return None


@pytest.mark.parametrize("outcome", ["busy", "timeout", "unavailable", "crash"])
def test_parse_expr_outcome_is_the_calls_own_not_the_shared_attribute(
    outcome: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lemely.core import equivalence as eq

    monkeypatch.setattr(eq, "_PARSE_WORKER", _UndecidedWorker(outcome))
    assert eq.parse_expr_outcome("24") == (None, outcome)
    assert outcome in eq.PARSE_UNDECIDED_OUTCOMES


def test_parse_undecided_outcomes_are_exactly_the_ones_that_say_nothing_about_the_text() -> None:
    """Task 6 review, Minor 3/4: pinned as a set, so dropping a member is red."""
    from lemely.core import equivalence as eq

    assert (
        frozenset({"busy", "timeout", "unavailable", "crash", "refused-ambiguous"})
        == eq.PARSE_UNDECIDED_OUTCOMES
    )


@pytest.mark.parametrize("text", ["(2)3", "(1.5)2", "(x+1)2", "sqrt2x"])
def test_refusals_without_a_settled_reading_have_their_own_outcome(text: str) -> None:
    """Task 6 review, Minor 4: a digit after a bracket and a bracketless
    argument with no settled reading are refused because the text has two
    readings, not because it is not an expression -- a distinct outcome, so a
    caller can treat it as "could not decide"."""
    from lemely.core import equivalence as eq

    assert eq.parse_expr_outcome(text) == (None, "refused-ambiguous")
    assert parse_expr_safe(text) is None


def test_the_worker_parses_normally_once_the_lock_is_free() -> None:
    """#271 guard: with the lock free, a fresh worker starts (outside the
    caller's budget) and parses as before."""
    from lemely.core import equivalence as eq

    worker = eq._ParseWorker()
    try:
        assert worker.parse("1+1", timeout=5.0) == sympy.Integer(2)
        assert worker.last_outcome == "ok"
    finally:
        worker.shutdown()


def test_a_lock_wait_that_leaves_no_budget_returns_busy_without_killing_the_worker() -> None:
    """#271 floor. A caller that takes the lock with (almost) none of its
    budget left must not poll ``~0`` and then kill a healthy worker for the
    "timeout": it returns ``None`` with ``last_outcome == "busy"`` and the
    child lives on (same pid). Deterministic: the lock is a wrapper whose
    ``acquire`` consumes all but ~20 ms of the caller's timeout and then
    succeeds, which is a contended acquire that won at the last moment."""
    from lemely.core import equivalence as eq

    class LateLock:
        """Takes the real lock only after consuming nearly all of ``timeout``."""

        def __init__(self, real: threading.Lock) -> None:
            self.real = real

        def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
            time.sleep(max(0.0, timeout - 0.02))
            return self.real.acquire(blocking, timeout)

        def release(self) -> None:
            self.real.release()

    worker = eq._ParseWorker()
    real_lock = worker._lock
    try:
        assert worker.parse("1+1", timeout=5.0) == sympy.Integer(2)  # warm: a live child
        pid_before = worker.pid()
        assert pid_before is not None
        worker._lock = LateLock(real_lock)  # type: ignore[assignment]
        result = worker.parse("2+2", timeout=0.2)
        worker._lock = real_lock
        assert result is None
        assert worker.last_outcome == "busy"
        assert worker.pid() == pid_before, "a healthy worker was killed for a lock wait"
        assert worker.parse("3+3", timeout=5.0) == sympy.Integer(6)  # and it still serves
    finally:
        worker._lock = real_lock
        worker.shutdown()


def test_equivalent_never_raises_when_its_difference_is_too_long_to_print() -> None:
    """Review round 2 (item 2). Each operand fits the result bound, but
    ``a - b`` does not: ``1/(10^4298+1) - 997`` has a 4,301-digit numerator,
    and formatting it into ``Verdict.detail`` raised ``ValueError('Exceeds
    the limit (4300 digits) for integer string conversion')`` out of
    ``equivalent`` -- which ``correction_ai`` does not catch. The verdict
    must stand and the detail must say why it cannot show the number."""
    verdict = equivalent("1/(10^999*10^999*10^999*10^999*10^302+1)", "997")
    assert verdict.kind is VerdictKind.NOT_EQUAL
    assert verdict.detail is not None and "too long to print" in verdict.detail


def test_the_sampler_seed_never_raises_on_a_number_too_long_to_print() -> None:
    """Review round 2 (item 2): ``srepr`` in the sampler seed prints every
    number too, and ``equivalent`` also accepts already-parsed expressions,
    which no parse bound limits. The seed must still come back, stay
    deterministic, and still tell two different long numbers apart."""
    from lemely.core import equivalence as eq

    x = sympy.Symbol("x")
    long_a = sympy.Integer(10) ** 5000 + 1
    long_b = sympy.Integer(10) ** 5000 + 3
    seed = eq._sampler_seed(long_a * x, x)
    assert seed == eq._sampler_seed(long_a * x, x)
    assert seed != eq._sampler_seed(long_b * x, x)


@pytest.mark.parametrize(
    "kwargs",
    [{"sig_figs": 3}, {"dp": 2}, {"sig_figs": 1}],
    ids=["sig-figs-3", "dp-2", "sig-figs-1"],
)
def test_an_answer_beyond_float_range_with_stated_precision_never_raises(
    kwargs: dict[str, int],
) -> None:
    """Review round 2 (item 3). ``2 * 10^400`` has no float magnitude, and the
    sig-figs window took ``math.floor(math.log10(inf))`` -- an OverflowError
    straight out of ``equivalent``, which ``correction_ai`` does not catch.
    It must come back as a verdict, and never an equal one: a number beyond
    float range has no window to be "close enough" inside."""
    verdict = equivalent("2×10^400", "5", **kwargs)
    assert verdict.kind is VerdictKind.NOT_EQUAL


@pytest.mark.parametrize(
    ("a", "b", "kwargs"),
    [
        ("2×10^400", "5", {}),
        ("2×10^400", "5.0", {}),
        ("2×10^400", "9.81", {"tolerance": "2%"}),
        ("2×10^400*x", "5*x", {}),
        ("2×10^300", "5", {}),
        ("1/0", "1/0", {}),
        ("0/0", "0/0", {}),
    ],
    ids=[
        "beyond-float-vs-integer",
        "beyond-float-vs-float",
        "beyond-float-vs-float-at-2-percent",
        "beyond-float-coefficient",
        "within-float-range-stays-not-equal",
        "infinity-vs-itself",
        "undefined-vs-itself",
    ],
)
def test_a_non_finite_magnitude_is_never_equal(a: str, b: str, kwargs: dict[str, str]) -> None:
    """Review round 2 (item 5), serious before the gate is enabled.
    ``_magnitude`` gave ``inf`` for ``2 * 10^400``, ``for_magnitude(inf)`` was
    ``inf``, and ``inf > inf`` is False -- so any answer beyond float range
    was certified EQUAL_PROVEN against anything. A ``nan`` coefficient
    (``zoo - zoo``) passed the same way, since ``nan > window`` is False
    too. Every comparison that can see ``inf``/``nan`` must fail closed:
    not equal (or unparseable), never equal."""
    verdict = equivalent(a, b, **kwargs)  # type: ignore[arg-type]
    assert verdict.kind not in (VerdictKind.EQUAL_PROVEN, VerdictKind.EQUAL_SAMPLED)


def test_an_exact_identity_beyond_float_range_is_still_equal() -> None:
    """The fail-closed rule is about magnitudes and windows, not exact
    arithmetic: two identical exact numbers beyond float range still differ
    by exactly 0, which needs no window at all."""
    assert equivalent("2×10^400", "2×10^400").kind is VerdictKind.EQUAL_PROVEN


def test_the_tolerance_helpers_fail_closed_on_non_finite_values() -> None:
    """Review round 2 (item 5), at the helpers themselves, so a caller that
    reaches them some other way gets the same answer: nothing non-finite is
    ever within a window, and rounding agreement between a non-finite value
    and anything is False rather than an OverflowError."""
    from lemely.core import equivalence as eq

    spec = eq._ToleranceSpec(
        sig_figs=3, dp=None, tolerance_abs=None, tolerance_rel=None, abs_tol=1e-9, rel_tol=1e-9
    )
    inf, nan = math.inf, math.nan
    assert not eq._values_within_tolerance(complex(inf), complex(5), spec)
    assert not eq._values_within_tolerance(complex(inf), complex(inf), spec)
    assert not eq._values_within_tolerance(complex(nan), complex(nan), spec)
    assert not eq._rounds_agree_at_stated_precision(inf, 5.0, 3, None)
    assert not eq._rounds_agree_at_stated_precision(5.0, nan, None, 2)
    assert eq._values_within_tolerance(complex(5), complex(5), spec)


def test_a_subscripted_amplitude_is_never_read_as_a_zeroth_power() -> None:
    """Review round 2 (item 6), serious before the gate is enabled. ``N`` and
    ``A`` are units (newton, ampere), and the unit-digit rewrite turned
    ``N0`` into ``N**0`` = 1: ``parse_expr_safe("N0*x")`` was ``x`` and
    ``equivalent("N0*x", "x")`` was EQUAL_PROVEN -- a coefficient silently
    deleted. A letter followed by 0 or 1 is always a subscript."""
    assert equivalent("N0*x", "x").kind is VerdictKind.NOT_EQUAL
    parsed = parse_expr_safe("N0*exp(-k*t)")
    n0, k, t = sympy.symbols("N_0 k t")
    assert parsed == n0 * sympy.exp(-k * t)
    assert parse_expr_safe("A0") == sympy.Symbol("A_0")


@pytest.mark.parametrize(
    ("a", "b", "kind"),
    [
        ("v1+v2", "v2+v1", VerdictKind.EQUAL_PROVEN),
        ("m1+m2", "m2+m1", VerdictKind.EQUAL_PROVEN),
        ("v1+v2", "3v", VerdictKind.NOT_EQUAL),
        ("m1*m2", "m^3", VerdictKind.NOT_EQUAL),
        ("R1+R2", "3R", VerdictKind.NOT_EQUAL),
        ("x2-2x-15", "-15", VerdictKind.NOT_EQUAL),
        ("F1-F2", "-F", VerdictKind.NOT_EQUAL),
        ("x0", "0", VerdictKind.NOT_EQUAL),
        # Review round 3: Greek letters take subscripts too (ε₀ transcribed as ε0).
        ("θ1+θ2", "3θ", VerdictKind.NOT_EQUAL),
        ("θ1+θ2", "θ2+θ1", VerdictKind.EQUAL_PROVEN),
        ("ω1+ω2", "3ω", VerdictKind.NOT_EQUAL),
        ("ε0*E", "0", VerdictKind.NOT_EQUAL),
        ("μ0*I", "0", VerdictKind.NOT_EQUAL),
        ("ϵ0*E", "0", VerdictKind.NOT_EQUAL),
        ("φ1-φ2", "-φ", VerdictKind.NOT_EQUAL),
        ("q/(4πε0r^2)", "q/(4πε0r^2)", VerdictKind.EQUAL_PROVEN),
        # π2 is ambiguous (π², π/2 -- the corpus's "π 3" is a broken stacked
        # fraction -- or 2π): one symbol, so it can only match itself.
        ("π2", "2π", VerdictKind.NOT_EQUAL),
        ("2π", "π*2", VerdictKind.EQUAL_PROVEN),
    ],
    ids=[
        "two-velocities-commute",
        "two-masses-commute",
        "velocities-are-not-3v",
        "masses-are-not-m-cubed",
        "resistors-are-not-3R",
        "caretless-square-is-not-a-coefficient",
        "forces-with-a-unit-letter",
        "initial-position-is-not-zero",
        "greek-angles-are-not-3-theta",
        "greek-angles-commute",
        "greek-angular-velocities-are-not-3-omega",
        "permittivity-is-not-zero",
        "greek-mu-permeability-is-not-zero",
        "lunate-epsilon-is-not-zero",
        "greek-phases-are-not-minus-phi",
        "coulomb-constant-denominator-equals-itself",
        "pi2-is-not-2pi",
        "2pi-unchanged",
    ],
)
def test_a_letter_followed_by_digits_is_one_symbol(a: str, b: str, kind: VerdictKind) -> None:
    """Review round 2 (item 6). Outside the unit powers mark schemes write
    without a caret, a letter followed by digits is a subscripted symbol,
    never a coefficient or a power: ``v1+v2`` used to parse as ``3*v``,
    ``m1*m2`` as ``m**3``, ``R1+R2`` as ``3*R``, ``x0`` as ``0``, and the
    mark-scheme maths ``x2-2x-15`` (a lost superscript) as ``-15`` -- each a
    false EQUAL_PROVEN waiting for the matching wrong answer. A subscript
    symbol can only ever equal itself, so the unreadable ``x2`` now routes
    to review instead of matching ``-15``."""
    assert equivalent(a, b).kind is kind


@pytest.mark.parametrize(
    ("caretless", "caret"),
    [
        ("g/cm3", "g/cm^3"),
        ("kg/m3", "kg/m^3"),
        ("5.7 m/s2", "5.7 m/s^2"),
        ("9200 N/m2", "9200 N/m^2"),
        ("30 cm3", "30 cm^3"),
        ("m2", "m^2"),
        ("0.75 N/cm2", "0.75 N/cm^2"),
        ("T2", "T^2"),
    ],
    ids=[
        "density-g-cm3",
        "density-kg-m3",
        "acceleration-m-s2",
        "pressure-N-m2",
        "volume-cm3",
        "area-m2",
        "pressure-N-cm2",
        # A lone single-letter unit with exponent >= 2 stays a power: the
        # corpus's pendulum answers write T² as T2.
        "pendulum-period-squared",
    ],
)
def test_caretless_unit_powers_from_mark_schemes_still_parse_as_powers(
    caretless: str, caret: str
) -> None:
    """Every form here is copied from the mark-scheme corpus (``g / cm3``,
    ``kg / m3``, ``5.7 m / s2``, ``9200 (N / m2)``, ``30 cm3``, ``m2``,
    ``0.75 (N / cm2)``): a unit written with its power's superscript lost.
    The subscript rule must not break them."""
    assert parse_expr_safe(caretless) == parse_expr_safe(caret)


def test_greek_subscripts_are_one_symbol_each() -> None:
    """Review round 3: the letter class held µ (the micro sign) but no Greek
    letter, so SymPy split ``λ1*λ2`` into ``2*λ**2`` and ``ε0`` into 0."""
    l1, l2 = sympy.symbols("λ_1 λ_2")
    assert parse_expr_safe("λ1*λ2") == l1 * l2
    q, pi, e0, r = sympy.symbols("q π ε_0 r")
    assert parse_expr_safe("q/(4πε0r^2)") == q / (4 * pi * e0 * r**2)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("sinx2", sympy.sin(sympy.Symbol("x_2"))),
        ("lnx2", sympy.log(sympy.Symbol("x_2"))),
        ("expx2", sympy.exp(sympy.Symbol("x_2"))),
        ("sqrtx2", sympy.sqrt(sympy.Symbol("x_2"))),
        ("logx2", sympy.log(sympy.Symbol("x_2"))),
        ("cosθ1", sympy.cos(sympy.Symbol("θ_1"))),
        ("sinθ1", sympy.sin(sympy.Symbol("θ_1"))),
        ("tanα2", sympy.tan(sympy.Symbol("α_2"))),
    ],
    ids=[
        "sin-ascii-head",
        "ln-ascii-head",
        "exp-ascii-head",
        "sqrt-ascii-head",
        "log-ascii-head",
        "cos-greek-head",
        "sin-greek-head",
        "tan-greek-head",
    ],
)
def test_a_function_name_head_still_calls_its_subscripted_argument(
    text: str, expected: sympy.Expr
) -> None:
    """Task 4 review's carried-over Minor: ``_rewrite_digit_suffixes`` joined
    a function-name head to its subscripted last letter with an explicit
    ``*`` -- ``sinx2`` became ``sin*(x_2)``, a bare symbol ``sin`` multiplied
    by ``(x_2)``, not a call to SymPy's ``sin``. At ec1ba45f this still read
    as ``sin(x_2)`` (the head/last split existed but the join used ``*``
    unconditionally); it now gives ``None`` -- ``sin`` as a plain symbol
    conflicts with SymPy's own recognition of ``sin`` elsewhere in this
    module and the parse is refused. ``lnx2``, ``expx2``, ``sqrtx2`` and
    ``logx2`` have the same shape (all :data:`_ALLOWED_FUNCTIONS` heads).
    When ``head`` is itself a known function name it must stay a call --
    ``head(last_digits)`` -- not a product.

    Review round 1: the ``head in _ALLOWED_FUNCTIONS`` check is not ASCII-only
    -- ``cos``/``sin``/``tan`` are the head regardless of what script the
    *subscript* letter is in, so ``cosθ1``/``sinθ1``/the tan-alpha-2 row get
    the same call treatment as ``sinx2``, going from UNPARSEABLE (Task 4 round 4) to
    ``cos(θ_1)`` etc. here. Ruled correct on review: a function call is a
    better reading than UNPARSEABLE, and the dispatch wording that asked to
    "keep the Greek rows as they are" meant "don't break the existing
    single-Greek-letter subscript rows" (``θ1+θ2``, ``ε0*E``, ...), not "no
    Greek row may ever change" -- none of those rows has a function-name
    head, so they are genuinely untouched (see
    ``test_a_greek_head_call_is_not_read_as_one_flat_symbol_family`` and
    ``test_a_function_call_head_never_reports_a_false_equal`` below for the
    two properties this reach must not break)."""
    assert parse_expr_safe(text) == expected


def test_a_greek_head_call_is_not_read_as_one_flat_symbol_family() -> None:
    """Review round 1: pin the two properties this fix's Greek reach must
    not break, now that ``cosθ1``/``sinθ1``/the tan-alpha-2 row are calls too.

    ``4πε0`` has no function-name head (``head`` is the plain symbol ``π``),
    so it is unaffected and still reads as a bare product. ``θ1+θ2`` vs
    ``3θ`` has no head at all (a single Greek letter plus digits), so it is
    also unaffected -- already pinned in
    ``test_a_letter_followed_by_digits_is_one_symbol``, reasserted here
    directly so this fix's own test does not depend on trusting that one."""
    pi, e0 = sympy.symbols("π ε_0")
    assert parse_expr_safe("4πε0") == 4 * e0 * pi
    assert equivalent("θ1+θ2", "3θ").kind is VerdictKind.NOT_EQUAL


def test_a_function_call_head_never_reports_a_false_equal() -> None:
    """False-EQUAL guard (review round 1): ``cosθ1`` must never be reported
    ``equal_proven`` against ``cosθ`` (no digit suffix); a wrong match would
    be worse than the UNPARSEABLE this fix's call reading replaces. ``cosθ``
    was the letter-split product ``c*o*s*θ`` when this was written; since
    #270 it is ``cos(θ)``, and ``cos(θ_1)`` is still a different call."""
    assert equivalent("cosθ1", "cosθ").kind is not VerdictKind.EQUAL_PROVEN


def test_a_family_letter_and_a_unit_power_in_the_same_text() -> None:
    """Review round 3 (pin the context rule): the family decision is per
    letter. ``m1`` makes ``m`` a family -- a subscript -- while ``s2`` in the
    same text, whose letter carries no other suffix, stays a unit power."""
    m1, m, s = sympy.symbols("m_1 m s")
    assert parse_expr_safe("m1*9.81 m/s2") == m1 * sympy.Float("9.81") * m / s**2


@pytest.mark.parametrize("text", ["3e8", "3E8", "3.0e8"])
def test_scientific_notation_is_not_a_subscript(text: str) -> None:
    """``e``/``E`` after a digit is an exponent marker, not a letter with a
    digit suffix: the subscript rule must leave it to Python's float
    literal, exactly as before."""
    assert parse_expr_safe(text) == sympy.Float("3e8")


# ---------------------------------------------------------------------------
# #270: function names, a digit after a bracket, `x` as times, one micro sign
# ---------------------------------------------------------------------------

#: (a, b, expected_kind, note). Each `equal` row is a reading SymPy's letter
#: splitting got wrong (``ln6`` was ``6*l*n``, so ``ln6`` and ``3ln2`` were
#: both letter products and EQUAL_PROVEN to each other); each `not_equal` row
#: is the false match that reading produced. ``sin2x`` is ``sin(2x)``, the
#: CAIE convention (owner decision D1), pinned both ways. The two micro rows
#: spell U+00B5 (the micro sign) and U+03BC (Greek mu) as escapes so the
#: difference survives an editor.
_ISSUE_270_TABLE: list[tuple[str, str, str, str]] = [
    ("ln6", "3ln2", "not_equal", "ln6-is-not-3ln2"),
    ("ln6", "ln(6)", "equal", "ln6-is-ln-of-6"),
    ("3ln2", "ln(8)", "equal", "3ln2-is-ln-of-8"),
    ("sin2x", "2sinx", "not_equal", "sin2x-is-not-2sinx"),
    ("sin2x", "sin(2x)", "equal", "sin2x-is-sin-of-2x"),
    ("2sinx", "2*sin(x)", "equal", "2sinx-is-2-sin-x"),
    ("log10(100)", "2", "equal", "log10-call-is-base-10"),
    ("Asin(ωt1)", "A*sin(ω*t_1)", "equal", "coefficient-before-a-call"),
    ("(x+1)2", "x^2+2x+1", "unparseable", "digit-after-bracket-is-refused"),
    ("(x+1)^2", "x^2+2x+1", "equal", "caret-after-bracket-unchanged"),
    ("3.0x10^8", "3.0×10^8", "equal", "ascii-x-times-ten-vs-times-sign"),
    ("3.0x10^8", "3.0*10**8", "equal", "ascii-x-times-ten-vs-star"),
    ("2x", "2*x", "equal", "2x-is-still-2-times-x"),
    ("4.5 µg", "4.5 μg", "equal", "micro-sign-is-greek-mu"),
    ("4.5 µg", "4.5 mg", "not_equal", "micrograms-are-not-milligrams"),
]


@pytest.mark.parametrize(
    "a,b,expected_kind,note", _ISSUE_270_TABLE, ids=[t[3] for t in _ISSUE_270_TABLE]
)
def test_issue_270_row_matches_expected_verdict(
    a: str, b: str, expected_kind: str, note: str
) -> None:
    """#270: each row asserts its own verdict, the guards included."""
    verdict = equivalent(a, b)
    assert _kind_matches(verdict.kind, expected_kind), (
        f"{a!r} vs {b!r} ({note}): expected {expected_kind}, got "
        f"{verdict.kind.value} (method={verdict.method}, detail={verdict.detail})"
    )


def test_both_micro_spellings_parse_to_one_unit_symbol() -> None:
    """#270: ``µg`` (U+00B5) was protected as a unit symbol, but Python's
    tokenizer NFKC-folds an identifier's U+00B5 to U+03BC, so the name SymPy
    looked up was not the one in ``local_dict`` -- a NameError, and
    ``parse_expr_safe("4.5 µg")`` was ``None``. The U+03BC spelling was
    never protected, so ``4.5 μg`` split into ``4.5*g*μ``. Both must
    be the one microgram symbol, spelled with U+03BC."""
    micrograms = 4.5 * sympy.Symbol("μg")
    assert parse_expr_safe("4.5 µg") == micrograms
    assert parse_expr_safe("4.5 μg") == micrograms


def test_issue_270_digit_after_bracket_is_refused() -> None:
    """#270: ``(x+1)2`` is either a lost superscript (``(x+1)²``) or a
    coefficient written after the bracket; implicit multiplication read it as
    ``2x+2``. Refused rather than guessed."""
    assert parse_expr_safe("(x+1)2") is None


@pytest.mark.parametrize(
    ("a", "b"),
    [("(x+1)x", "x^2+x"), ("(x+1)(x-1)", "x^2-1")],
    ids=["bracket-then-letter", "bracket-then-bracket"],
)
def test_issue_270_unaffected_bracket_shapes_still_multiply(a: str, b: str) -> None:
    """Guard: only a DIGIT after ``)`` is refused."""
    assert _kind_matches(equivalent(a, b).kind, "equal")


@pytest.mark.parametrize(
    ("a", "b", "expected_kind"),
    [("5x3", "5*x_3", "equal"), ("x10", "x*10", "not_equal"), ("2x10", "20", "not_equal")],
    ids=["5x3-is-a-subscript", "x10-is-a-subscript", "2x10-has-no-exponent-marker"],
)
def test_issue_270_narrow_times_rule_leaves_x_without_ten_power_alone(
    a: str, b: str, expected_kind: str
) -> None:
    """Guard: ``x`` is read as times only between a number and ``10^``/``10**``;
    anywhere else it stays the variable."""
    assert _kind_matches(equivalent(a, b).kind, expected_kind)


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("2x10^x", "2*10^x"),
        ("2*10^x", "2x10^x"),
        ("3x+2x10^2", "3x+200"),
        ("3x+200", "3x+2x10^2"),
        ("2x10^n", "2*10^n"),
        ("2*10^n", "2x10^n"),
    ],
    ids=[
        "symbolic-exponent",
        "symbolic-exponent-reversed",
        "x-is-a-variable-elsewhere",
        "x-is-a-variable-elsewhere-reversed",
        "symbolic-exponent-no-other-x",
        "symbolic-exponent-no-other-x-reversed",
    ],
)
def test_issue_270_times_x_is_never_read_where_x_may_be_the_variable(a: str, b: str) -> None:
    """Task 6 review, Important 1: ``x`` is read as times only before ``10^``
    with a whole-number exponent, and only when no other ``x`` in the text
    is the variable. ``2x10^x`` (exponent ``x``) and ``3x+2x10^2`` (``3x``
    uses ``x`` as the variable) were false EQUAL_PROVEN after 65ba2bd6.
    ``2x10^n`` pins the exponent check on its own (re-review): no other
    ``x`` is left once it is read as times, so only the whole-number
    exponent stops it becoming ``2*10^n``."""
    assert equivalent(a, b).kind not in _EQUAL_KINDS


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("2.4 x 10^(-3)", "0.0024"),
        ("6.4x10⁻³", "0.0064"),
        ("2 x 10^+3", "2000"),
        ("3.0 x 10 ** 8", "300000000"),
        ("2.4 x 10^4 J", "24000 J"),
    ],
    ids=["bracketed-negative", "superscript", "plus-sign", "spaced-star-star", "unit-after"],
)
def test_issue_270_times_x_still_reads_standard_form(a: str, b: str) -> None:
    """Guard: the narrowed rule still reads every standard-form shape."""
    assert _kind_matches(equivalent(a, b).kind, "equal")


def test_issue_270_function_name_pass_does_not_recurse_per_link() -> None:
    """Task 6 review, Minor 5. A chain of applications recursed once per link,
    so ``"lnx" * 166`` (498 characters, under the input cap) needed about 527
    frames: a caller already deep in its stack got a RecursionError, which
    breaks ``parse_expr_safe``'s never-raises promise. Run here with only 80
    frames to spare."""
    from lemely.core import equivalence as eq

    frame = sys._getframe()
    depth = 0
    while frame is not None:
        depth += 1
        frame = frame.f_back  # type: ignore[assignment]
    text = "lnx" * 166
    old_limit = sys.getrecursionlimit()
    sys.setrecursionlimit(depth + 80)
    try:
        result = eq._apply_function_names(text)
    finally:
        sys.setrecursionlimit(old_limit)
    assert result == "*".join(["ln(x)"] * 166)


#: (a, b, expected_kind, note). The function-application reading (#270,
#: controller decision extending D1): a function name followed directly by
#: one letter, a number, or a number then one letter is that function
#: applied to it. Every row here was a letter product before #270
#: (``cost`` was ``c*o*s*t``, ``sqrt2`` was ``2*q*r*s*t``).
_FUNCTION_APPLICATION_TABLE: list[tuple[str, str, str, str]] = [
    ("cost", "cos(t)", "equal", "cost-is-cos-of-t"),
    ("sinx", "sin(x)", "equal", "sinx-is-sin-of-x"),
    ("sinxcosx", "sin(x)*cos(x)", "equal", "concatenated-applications-split"),
    ("sqrt2", "sqrt(2)", "equal", "sqrt2-is-root-2"),
    ("ln2x", "ln(2*x)", "equal", "ln2x-is-ln-of-2x"),
    # Owner decision 2026-10-05 supersedes the D1 extension for `log`: a
    # single digit after `log` is a lost subscript base, so `log3x` is
    # log base 3 of x, not `log(3*x)`.
    ("log3x", "log(x, 3)", "equal", "log3x-is-log-base-3-of-x"),
    ("log25x", "log(25*x)", "equal", "log25x-multi-digit-is-a-coefficient"),
    ("tan2x", "tan(2*x)", "equal", "tan2x-is-tan-of-2x"),
]


@pytest.mark.parametrize(
    "a,b,expected_kind,note",
    _FUNCTION_APPLICATION_TABLE,
    ids=[t[3] for t in _FUNCTION_APPLICATION_TABLE],
)
def test_issue_270_function_application_row(a: str, b: str, expected_kind: str, note: str) -> None:
    verdict = equivalent(a, b)
    assert _kind_matches(verdict.kind, expected_kind), (
        f"{a!r} vs {b!r} ({note}): expected {expected_kind}, got "
        f"{verdict.kind.value} (method={verdict.method}, detail={verdict.detail})"
    )


def test_issue_270_function_name_pass_is_linear_on_a_failing_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The function-name pass runs in the caller, not in the killable parse
    worker, so its work must stay bounded. ``sin2asin2a...`` offers two
    readings at every level (``2a`` then ``sin``, or ``2`` then ``asin``);
    when the chain fails at its tail (``sin2xy``), a pass that retries every
    level without remembering what already failed does 2**n work: before
    the fix, 16 repeats (86 characters) took 786,427 calls and about 0.8 s,
    and a 500-character answer would never return."""
    from lemely.core import equivalence as eq

    calls = 0
    real = eq._application_at

    def counting(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return real(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(eq, "_application_at", counting)
    text = "sin2a" * 16 + "sin2xy"
    assert eq._apply_function_names(text) == text
    assert calls <= 4 * len(text), calls


def test_issue_270_log10_without_brackets_is_log_base_ten() -> None:
    """Owner decision (#270): "log10(x) is often expressed as log10x.
    depending on context the student intent is to be inferred." A lost
    subscript (log₁₀) is the common case, so ``log10x``, ``log10 x`` and
    ``log10 100`` are the base-10 log of their argument, like ``log10(``,
    and never ``log(10x)`` or ``log(10)*x``."""
    x = sympy.Symbol("x")
    assert parse_expr_safe("log10x") == sympy.log(x, 10)
    assert parse_expr_safe("log10 x") == sympy.log(x, 10)
    assert parse_expr_safe("log10 100") == sympy.Integer(2)
    assert equivalent("log10 100", "2").kind is VerdictKind.EQUAL_PROVEN
    assert equivalent("log10(1000)", "3").kind is VerdictKind.EQUAL_PROVEN
    assert not _kind_matches(equivalent("log10x", "log(10*x)").kind, "equal")


@pytest.mark.parametrize(
    ("text", "readings"),
    [
        ("log10x^2", ("log(x,10)^2", "log(x^2,10)")),
        ("log10xy", ("log(x,10)*y", "log(x*y,10)")),
    ],
    ids=["log10-exponent-after-argument", "log10-two-letters-after-name"],
)
def test_issue_270_log10_does_not_guess_an_ambiguous_argument(
    text: str, readings: tuple[str, str]
) -> None:
    """Guard: the base-10 reading takes the same arguments as every other
    function name, so the shapes the pass refuses elsewhere stay refused."""
    for reading in readings:
        assert not _kind_matches(equivalent(text, reading).kind, "equal"), reading


def test_issue_270_log_with_a_single_digit_base_is_that_base() -> None:
    """Owner decision (2026-10-05): the lost-subscript reading of ``log10``
    extends to single-digit bases 2 to 9. ``log2x`` is ``log(x, 2)``, never
    ``log(2x)``; ``log2 8`` is 3; ``log2(8)`` is ``log(8, 2)`` as ``log10(``
    is base 10."""
    x = sympy.Symbol("x")
    assert parse_expr_safe("log2x") == sympy.log(x, 2)
    assert parse_expr_safe("log3x") == sympy.log(x, 3)
    assert parse_expr_safe("log2 8") == sympy.Integer(3)
    assert parse_expr_safe("log3 9") == sympy.Integer(2)
    assert equivalent("log2(8)", "3").kind is VerdictKind.EQUAL_PROVEN
    assert not _kind_matches(equivalent("log2x", "log(2*x)").kind, "equal")


@pytest.mark.parametrize(
    ("text", "same_as"),
    [
        ("log100", "log(100)"),
        ("log25", "log(25)"),
        ("log2.5", "log(2.5)"),
        ("log10.5", "log(10.5)"),
        ("log2", "log(2)"),
        ("log2 + 1", "log(2) + 1"),
        ("ln2x", "ln(2*x)"),
    ],
    ids=["multi-digit", "multi-digit-not-10", "decimal", "decimal-10", "bare", "operator", "ln"],
)
def test_issue_270_log_base_reading_leaves_other_digits_alone(text: str, same_as: str) -> None:
    """Guard (owner decision 2026-10-05): a multi-digit number other than 10,
    a decimal, a bare ``log2`` and ``log2 + 1`` keep their readings, and
    ``ln`` has no base."""
    assert parse_expr_safe(text) == parse_expr_safe(same_as)


@pytest.mark.parametrize("text", ["log2x^2", "log2xy", "log10x^2", "log10xy", "log3x!"])
def test_issue_270_a_lost_base_log_with_an_ambiguous_argument_is_refused(text: str) -> None:
    """A ``log`` with a lost subscript base whose argument the pass will not
    read (``log2x^2`` is log₂(x²) or (log₂x)²) used to fall to the letter
    product ``2*g*l*o*x**2`` -- a confident NOT_EQUAL on a reading nobody
    wrote. It is refused as ambiguous, the same outcome as ``sqrt2x``, so the
    generation gate admits the solver and fails closed."""
    from lemely.core import equivalence as eq

    assert eq.parse_expr_outcome(text) == (None, "refused-ambiguous")


def test_issue_270_sqrt_of_a_number_then_a_letter_is_refused() -> None:
    """``sqrt2x`` is ``sqrt(2x)`` or ``sqrt(2)*x``; unlike the trig, ``ln`` and
    ``log`` forms, no convention settles it, so it is refused."""
    assert parse_expr_safe("sqrt2x") is None
    assert parse_expr_safe("sqrt2") == sympy.sqrt(2)


@pytest.mark.parametrize(
    ("text", "readings"),
    [
        ("sinx^2", ("sin(x)^2", "sin(x^2)")),
        ("sinxy", ("sin(x)*y", "sin(x*y)")),
        ("ln2(x+1)", ("ln(2)*(x+1)", "ln(2*(x+1))")),
    ],
    ids=["exponent-after-argument", "two-letters-after-name", "bracket-after-number"],
)
def test_issue_270_function_names_do_not_guess_an_ambiguous_argument(
    text: str, readings: tuple[str, str]
) -> None:
    """Guard: the function-name pass brackets only an argument that ends at an
    operator, a space or the end of the text. ``sinx^2`` (``sin²x`` or
    ``sin(x²)``), ``sinxy`` and ``ln2(x+1)`` match neither reading."""
    for reading in readings:
        assert not _kind_matches(equivalent(text, reading).kind, "equal"), reading


def test_an_interrupted_start_kills_the_child_and_leaves_the_worker_clean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review round 2 (item 4). ``_spawn`` caught only ``Exception`` around
    ``process.start()``: a KeyboardInterrupt there left both pipe ends open
    and a child that had already been spawned running, unjoined. It must be
    killed and joined, the pipes closed, and the interrupt re-raised; the
    next call must start cleanly."""
    from lemely.core import equivalence as eq

    events: list[str] = []
    real_context = eq.multiprocessing.get_context("spawn")
    pipes: list[object] = []

    class _InterruptedAfterSpawn:
        def __init__(self, **_kwargs: object) -> None:
            self.pid: int | None = None

        def start(self) -> None:
            self.pid = 424242  # the child exists; the interrupt lands after
            raise KeyboardInterrupt

        def kill(self) -> None:
            events.append("kill")

        def join(self, timeout: float | None = None) -> None:
            events.append("join")

    class _Context:
        Process = _InterruptedAfterSpawn

        @staticmethod
        def Pipe() -> object:  # mirrors multiprocessing's API
            ends = real_context.Pipe()
            pipes.extend(ends)
            return ends

    worker = eq._ParseWorker()
    monkeypatch.setattr(eq, "_PARSE_WORKER", worker)
    monkeypatch.setattr(eq.multiprocessing, "get_context", lambda _method: _Context())
    with pytest.raises(KeyboardInterrupt):
        worker.parse("2+2", 1.0)
    assert events == ["kill", "join"]
    assert pipes and all(end.closed for end in pipes)  # type: ignore[attr-defined]
    assert worker.pid() is None
    monkeypatch.setattr(eq.multiprocessing, "get_context", lambda method: real_context)
    assert parse_expr_safe("2+2") == sympy.Integer(4)
    worker.shutdown()


def test_the_parse_worker_leaves_no_child_behind() -> None:
    import multiprocessing

    from lemely.core import equivalence as eq

    assert parse_expr_safe("3*10^8") == sympy.Integer(300000000)
    pid = eq._PARSE_WORKER.pid()
    assert pid is not None and _alive(pid)
    eq._PARSE_WORKER.shutdown()
    assert not _alive(pid)
    assert eq._PARSE_WORKER.pid() is None
    assert not [c for c in multiprocessing.active_children() if c.name == "lemely-parse-worker"]


@pytest.mark.parametrize(
    "text", ["0.5mv²", "3.0×10^8", "(x+1)^2 - x^2", "g cm^-3", "sqrt(2)/2", "5!"]
)
def test_ordinary_inputs_are_unchanged_through_the_parse_worker(text: str) -> None:
    """The worker's result is the same expression the in-process parse of
    the same normalised text gives -- the process boundary (a pickle round
    trip) changes nothing a caller can compare."""
    from lemely.core import equivalence as eq

    in_process = eq._parse_normalized(eq._normalize_text(text), evaluate=True)
    through_worker = parse_expr_safe(text)
    assert through_worker == in_process
    assert sympy.srepr(through_worker) == sympy.srepr(in_process)


def test_prose_is_still_refused_through_the_parse_worker() -> None:
    assert parse_expr_safe("not an answer at all, really") is None


@pytest.mark.parametrize(
    "text,expected",
    [
        ("a(b+c)", "a*(b + c)"),
        ("v(t)", "t*v"),
        ("T(2)", "2*T"),
    ],
    ids=["variable-call", "variable-call-single-letter", "variable-call-reserved-lookalike"],
)
def test_parse_expr_safe_treats_unknown_identifier_call_as_multiplication(
    text: str, expected: str
) -> None:
    """S1: an identifier before "(" is only a rejected "function call" when
    it is a KNOWN SymPy callable outside the allowlist. `a`, `v`, `T` are
    not SymPy attributes, so `a(b+c)` etc. must survive as implicit
    multiplication, not be rejected outright.
    """
    parsed = parse_expr_safe(text)
    assert parsed is not None
    assert sympy.simplify(parsed - sympy.sympify(expected)) == 0


def test_equivalent_accepts_already_parsed_expressions() -> None:
    x = sympy.Symbol("x")
    verdict = equivalent(x + 1, 1 + x)
    assert verdict.kind is VerdictKind.EQUAL_PROVEN
    assert verdict.method is EquivalenceMethod.SIMPLIFY
    assert verdict.auto_awardable


def test_verdict_equal_by_any_method_covers_both_equal_kinds() -> None:
    assert Verdict(VerdictKind.EQUAL_PROVEN).equal_by_any_method is True
    assert Verdict(VerdictKind.EQUAL_SAMPLED).equal_by_any_method is True
    assert Verdict(VerdictKind.NOT_EQUAL).equal_by_any_method is False
    assert Verdict(VerdictKind.UNPARSEABLE).equal_by_any_method is False


def test_verdict_has_no_equal_property() -> None:
    """The pre-fix `.equal` property collapsed EQUAL_PROVEN and
    EQUAL_SAMPLED into one boolean sitting next to `auto_awardable`, which
    answers the same question differently — `if verdict.equal: award()`
    silently got the pre-D12 behaviour. It must not exist; callers must say
    which question they mean (`auto_awardable` or `equal_by_any_method`).
    """
    assert not hasattr(Verdict(VerdictKind.EQUAL_PROVEN), "equal")


def test_verdict_auto_awardable_requires_equal_proven() -> None:
    assert Verdict(VerdictKind.EQUAL_PROVEN, method=EquivalenceMethod.SIMPLIFY).auto_awardable
    assert not Verdict(VerdictKind.EQUAL_SAMPLED, method=EquivalenceMethod.NUMERIC).auto_awardable
    assert not Verdict(VerdictKind.NOT_EQUAL, method=EquivalenceMethod.SIMPLIFY).auto_awardable
    assert not Verdict(VerdictKind.UNPARSEABLE).auto_awardable
