"""Tests for the D3.6 difficulty-targeting module (``lemely.core.difficulty``).

Pure unit tests: no DB, no network, no clock. The property most likely to be
silently wrong under naive rounding — ``allocate_difficulty`` summing to
exactly ``count`` — gets a real sweep across every grade and a wide range of
counts, not a handful of hand-picked examples.
"""

from __future__ import annotations

from typing import get_args

import pytest

from lemely.core.at_risk import GRADE_ORDER
from lemely.core.difficulty import (
    DIFFICULTY_MIX,
    Band,
    allocate_difficulty,
    difficulty_mix,
    infer_difficulty,
)
from lemely.core.generation import GeneratedQuestion

_ALL_TARGETS: list[str | None] = [*GRADE_ORDER, None]
_COUNTS = range(0, 26)


@pytest.mark.parametrize("target_grade", _ALL_TARGETS)
@pytest.mark.parametrize("count", _COUNTS)
def test_allocate_difficulty_sums_to_count(target_grade: str | None, count: int) -> None:
    allocation = allocate_difficulty(target_grade, count)
    assert sum(allocation.values()) == count


@pytest.mark.parametrize("target_grade", _ALL_TARGETS)
@pytest.mark.parametrize("count", _COUNTS)
def test_allocate_difficulty_all_bands_present_and_non_negative(
    target_grade: str | None, count: int
) -> None:
    allocation = allocate_difficulty(target_grade, count)
    assert set(allocation) == {"foundation", "standard", "challenge"}
    assert all(v >= 0 for v in allocation.values())


@pytest.mark.parametrize("target_grade", _ALL_TARGETS)
@pytest.mark.parametrize("count", _COUNTS)
def test_allocate_difficulty_is_deterministic(target_grade: str | None, count: int) -> None:
    first = allocate_difficulty(target_grade, count)
    second = allocate_difficulty(target_grade, count)
    assert first == second
    # Order-independence: rebuilding DIFFICULTY_MIX in a different dict order
    # (simulating set/dict-ordering nondeterminism) must not change the result.
    reordered = dict(reversed(DIFFICULTY_MIX.items()))
    original = DIFFICULTY_MIX.copy()
    DIFFICULTY_MIX.clear()
    DIFFICULTY_MIX.update(reordered)
    try:
        third = allocate_difficulty(target_grade, count)
    finally:
        DIFFICULTY_MIX.clear()
        DIFFICULTY_MIX.update(original)
    assert first == third


def test_allocate_difficulty_negative_count_is_all_zero() -> None:
    allocation = allocate_difficulty("C", -5)
    assert allocation == {"foundation": 0, "standard": 0, "challenge": 0}


@pytest.mark.parametrize("target_grade", GRADE_ORDER)
def test_every_grade_has_a_valid_mix(target_grade: str) -> None:
    foundation, standard, challenge = difficulty_mix(target_grade)
    assert foundation >= 0.0
    assert standard >= 0.0
    assert challenge >= 0.0
    assert foundation + standard + challenge == pytest.approx(1.0, abs=1e-9)


def test_difficulty_mix_covers_exactly_grade_order() -> None:
    assert set(DIFFICULTY_MIX) == set(GRADE_ORDER)


@pytest.mark.parametrize("bad_grade", [None, "", "Z", "a*", "9-1", "F"])
def test_unrecognised_grade_falls_back_to_balanced_mix(bad_grade: str | None) -> None:
    assert difficulty_mix(bad_grade) == (0.20, 0.60, 0.20)


def test_unrecognised_grade_fallback_allocates_sensibly() -> None:
    # The documented fallback keeps at least two bands in play for a
    # reasonably sized quiz, same as every named grade.
    allocation = allocate_difficulty("not-a-real-grade", 10)
    assert sum(allocation.values()) == 10
    assert allocation["foundation"] > 0
    assert allocation["standard"] > 0


# --- infer_difficulty ---------------------------------------------------


@pytest.mark.parametrize(
    ("marks", "question_type", "expected"),
    [
        # MCQ is always foundation, regardless of marks.
        (1, "mcq", "foundation"),
        (10, "mcq", "foundation"),
        # marks <= 1 (the lowest boundary) is foundation for a non-challenge type.
        (1, "short_answer", "foundation"),
        (0, "short_answer", "foundation"),
        (-1, "short_answer", "foundation"),
        (-100, "short_answer", "foundation"),
        # 2..3 marks is standard (both ends of that band).
        (2, "short_answer", "standard"),
        (3, "short_answer", "standard"),
        # 4+ marks (the boundary just above "standard") is challenge.
        (4, "short_answer", "challenge"),
        (20, "short_answer", "challenge"),
        # Structural types are always challenge, even at 1 mark.
        (1, "multi_step", "challenge"),
        (1, "levels_based", "challenge"),
        (1, "indicative_content", "challenge"),
        (0, "multi_step", "challenge"),
        (-5, "levels_based", "challenge"),
    ],
)
def test_infer_difficulty_boundaries(marks: int, question_type: str, expected: Band) -> None:
    assert infer_difficulty(marks, question_type) == expected


# --- vocabulary agreement -------------------------------------------------


def test_band_vocabulary_matches_generated_question_difficulty_literal() -> None:
    """Pin the Band vocabulary against GeneratedQuestion.difficulty's Literal.

    These two must never drift: a fourth difficulty level, or a different
    spelling, invented on one side and not the other would silently break the
    quiz builder's ability to draw generated questions into a difficulty band.
    """
    band_values = set(get_args(Band))
    literal_values = set(get_args(GeneratedQuestion.model_fields["difficulty"].annotation))
    assert band_values == literal_values == {"foundation", "standard", "challenge"}
