"""Difficulty targeting by expected grade (D3.6, ``docs/quiz-model.md`` §3).

Pure, no I/O, no DB, no clock — the only import from the rest of the codebase
is :data:`lemely.core.at_risk.GRADE_ORDER`, so the grade ladder is never
re-literalised here (this codebase has been bitten three times by one rule
implemented twice and drifting — D3.3, D3.4, D3.5).

**The mix has no empirical backing.** There is no dataset in this repo linking
question difficulty to grade outcomes, and none is acquirable within Phase 3.
:data:`DIFFICULTY_MIX` is a product judgement about what *should* discriminate
within a target grade, not a calibrated model — callers (the pool-count
endpoint, the quiz builder) must label it as an estimate and must never
describe it as "calibrated" (spec §1.4: never invent precision). The same
caveat applies to :func:`infer_difficulty`: it is a proxy for effort inferred
from mark allocation, not a measurement of difficulty, and it cannot know
whether a 1-mark question was in fact brutal.

This module, the pool-count endpoint, and the quiz builder's selection query
all call these three functions rather than re-expressing the table — if the
count and the built quiz ever computed the allocation differently, the
teacher would see a count of 40 and a quiz of 12 with no explanation.
"""

from __future__ import annotations

import math
from typing import Literal

from lemely.core.history import GRADE_ORDER

#: The three difficulty bands a question can carry. Deliberately identical to
#: ``GeneratedQuestion.difficulty`` (``lemely/core/generation.py``) and to the
#: ``questiondifficulty`` Postgres enum planned in ``docs/quiz-model.md`` §1.1
#: — one vocabulary, pinned by ``tests/test_difficulty.py``'s vocabulary-
#: agreement test so the two can never drift apart.
Band = Literal["foundation", "standard", "challenge"]

#: Proportions of (foundation, standard, challenge) to draw for a quiz aimed
#: at a given target grade. A **mix**, not a single band: a quiz aimed at a C
#: student made entirely of "standard" questions discriminates nothing — it
#: cannot show who is nearly a B or who is slipping to a D. Every target keeps
#: at least two bands in play.
#:
#: Heuristic. Not calibrated against outcome data — see the module docstring.
#: Keys are exactly :data:`lemely.core.at_risk.GRADE_ORDER`; a mismatch here
#: would silently drop a grade out of the targeting feature, so the two are
#: checked equal below rather than left to drift unnoticed.
DIFFICULTY_MIX: dict[str, tuple[float, float, float]] = {
    # target grade: (foundation, standard, challenge)
    "A*": (0.00, 0.30, 0.70),
    "A": (0.00, 0.50, 0.50),
    "B": (0.20, 0.60, 0.20),
    "C": (0.30, 0.60, 0.10),
    "D": (0.50, 0.50, 0.00),
    "E": (0.70, 0.30, 0.00),
    "U": (1.00, 0.00, 0.00),
}

if set(DIFFICULTY_MIX) != set(GRADE_ORDER):  # pragma: no cover - import-time invariant
    # A real raise, not an ``assert``: ``python -O`` strips asserts, and a drift
    # guard that disappears under an optimised interpreter guards nothing. The
    # failure it catches — a grade silently dropping out of difficulty
    # targeting because the ladder moved and this table did not — is exactly the
    # single-rule-implemented-twice drift D3.3/D3.4/D3.5 each had to fix once.
    raise RuntimeError(
        "DIFFICULTY_MIX must cover exactly the grades in GRADE_ORDER; "
        f"mismatch: {set(DIFFICULTY_MIX) ^ set(GRADE_ORDER)}"
    )

#: Fallback mix for an untargeted quiz (``target_grade is None``) or a grade
#: string not on :data:`lemely.core.at_risk.GRADE_ORDER` (bad data, or a
#: future board with a different ladder). A balanced spread rather than an
#: error: an unknown target is not a reason to crash the pool count or the
#: builder, and a teacher who skipped the target-grade step should still get a
#: quiz that discriminates.
_UNTARGETED_MIX: tuple[float, float, float] = (0.20, 0.60, 0.20)

_BANDS: tuple[Band, Band, Band] = ("foundation", "standard", "challenge")

#: Public name for the band vocabulary, for callers outside this module.
#: `_BANDS` stays as the internal spelling used throughout the arithmetic
#: below; this alias exists so `/api/reference` does not have to reach past
#: the underscore and quietly couple itself to a private symbol.
DIFFICULTY_BANDS: tuple[Band, Band, Band] = _BANDS

#: Tie-break order for :func:`allocate_difficulty`'s largest-remainder step,
#: lowest value wins ties. ``standard`` sorts first per the documented rule
#: ("ties broken toward standard" — ``docs/quiz-model.md`` §3.1): the middle
#: band is the safest place to put an odd remainder unit since it never turns
#: a targeted quiz into an all-foundation or all-challenge one.
_TIE_PRIORITY: dict[Band, int] = {"standard": 0, "foundation": 1, "challenge": 2}


def difficulty_mix(target_grade: str | None) -> tuple[float, float, float]:
    """Look up the (foundation, standard, challenge) proportions for a target.

    Args:
        target_grade: a :data:`lemely.core.at_risk.GRADE_ORDER` member, or
            ``None`` for an untargeted quiz (a teacher who skipped the
            target-grade step of the builder).

    Returns:
        The proportions from :data:`DIFFICULTY_MIX`, or the balanced
        ``(0.2, 0.6, 0.2)`` fallback when ``target_grade`` is ``None`` or not
        a recognised grade. Unrecognised data does not raise here — mirroring
        ``at_risk._check_below_target``'s judgement that a malformed grade
        string should not crash the dashboard — because this function backs a
        live pool-count response, not a validated form submission.
    """
    if target_grade is None:
        return _UNTARGETED_MIX
    return DIFFICULTY_MIX.get(target_grade, _UNTARGETED_MIX)


def allocate_difficulty(target_grade: str | None, count: int) -> dict[Band, int]:
    """Turn a difficulty mix into whole-question counts summing to ``count``.

    Largest-remainder rounding: each band gets ``floor(proportion * count)``
    questions, then the remaining units (at most two, since there are three
    bands) go to the bands with the largest fractional remainder, ties broken
    toward ``standard`` (see :data:`_TIE_PRIORITY`).

    Deterministic by construction: the ordering used to break ties is a fixed
    tuple comparison, never a set or dict iteration order, so the same
    ``(target_grade, count)`` pair always yields the same allocation. That is
    what lets the pool-count endpoint and the quiz builder call this function
    independently and never disagree (``docs/quiz-model.md`` §3.1).

    Args:
        target_grade: passed through to :func:`difficulty_mix`.
        count: how many questions the quiz needs. ``count <= 0`` returns an
            all-zero allocation rather than raising — a draft quiz with no
            requested count yet is a legitimate state (§1.4 of the schema
            design), not an error.

    Returns:
        A mapping with all three :data:`Band` keys present, whose values are
        non-negative integers summing to exactly ``max(count, 0)``.
    """
    if count <= 0:
        return {band: 0 for band in _BANDS}

    proportions = difficulty_mix(target_grade)
    exact = [p * count for p in proportions]
    floors = [math.floor(x) for x in exact]
    remainder = count - sum(floors)

    remainders = [(exact[i] - floors[i], _TIE_PRIORITY[_BANDS[i]], i) for i in range(3)]
    remainders.sort(key=lambda item: (-item[0], item[1]))

    result: dict[Band, int] = {band: floors[i] for i, band in enumerate(_BANDS)}
    for _frac, _priority, index in remainders[:remainder]:
        result[_BANDS[index]] += 1
    return result


def infer_difficulty(marks: int, question_type: str) -> Band:
    """Estimate a difficulty band from mark allocation and question shape.

    Past-paper questions carry no difficulty label anywhere in the corpus
    (``docs/quiz-model.md`` §3.2). Asking Gemini to label each at ingest was
    rejected on cost — a per-question model call across the whole corpus for a
    field that only orders a pool. This heuristic is the chosen alternative:
    derived entirely from data already parsed, at zero marginal cost.

    It is a **proxy for effort, not for difficulty**: a 1-mark question can be
    brutal, and this function has no way to know that. Callers must record
    ``difficulty_source = inferred_from_marks`` so an estimated band is never
    confused with one a generator declared or a teacher set, and the UI must
    label it "estimated from mark allocation".

    Args:
        marks: the question's total mark allocation. Not validated as
            positive — a zero, negative, or otherwise absurd value (bad
            parser output) falls through the same ``marks <= 1`` branch as a
            genuine 1-mark question rather than raising, because this
            function backs an ingest pipeline that must not crash on
            malformed upstream data.
        question_type: a ``QuestionType`` member value (plain string, not the
            enum itself — see ``docs/quiz-model.md`` §1.3 on why
            ``question_type`` stays a string rather than a native PG enum).

    Returns:
        ``"challenge"`` for multi-step/levels-based/indicative-content
        questions regardless of marks; otherwise ``"foundation"`` for MCQ or
        marks <= 1, ``"standard"`` for marks <= 3, and ``"challenge"`` above
        that.
    """
    if question_type in {"multi_step", "levels_based", "indicative_content"}:
        return "challenge"
    if question_type == "mcq" or marks <= 1:
        return "foundation"
    if marks <= 3:
        return "standard"
    return "challenge"
