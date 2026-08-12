"""The XP-to-level curve (P5.8 chunk A, D5.13 §1).

Pure arithmetic, no database — the curve is a display concern with no schema
implication, which is exactly why D5.1 §10 was able to defer it to P5.8.

The tests that carry weight here are the **boundary** ones: every boundary in
range asserted from both sides, cross-checked against the stated rule ``level N
begins at 100·(N-1)²``, plus monotonicity over a wide sweep (a non-monotonic
curve would let a student *lose* a level by earning XP, which no amount of
boundary testing catches on its own).

**These tests do not distinguish the integer implementation from the float
one** — that was measured, not assumed: swapping ``isqrt(x // 100)`` for
``floor(sqrt(x / 100))`` leaves all of them green, because at a boundary
``100·N²`` both operations are exact in IEEE 754. D5.13 §1 originally claimed
the float form fails there; it does not, and the decision record was corrected
rather than left standing on a failure mode nobody had reproduced. The integer
form is still the one shipped, for the reason in
:func:`~lemely.web.xp_levels.level_for_xp`'s docstring.
"""

from __future__ import annotations

import pytest

from lemely.web.xp_levels import (
    LEVEL_STEP,
    level_floor,
    level_for_xp,
    progress_for_xp,
)


def test_a_student_with_no_xp_is_level_one() -> None:
    """Level 0 does not exist — a new student opens S-31 already on the board."""
    assert level_for_xp(0) == 1
    assert level_floor(1) == 0


@pytest.mark.parametrize("level", range(1, 25))
def test_each_level_begins_exactly_where_the_spec_says(level: int) -> None:
    """``level_floor(N) == 100·(N-1)²`` — the rule as written in D5.13 §1."""
    assert level_floor(level) == LEVEL_STEP * (level - 1) ** 2


@pytest.mark.parametrize("level", range(2, 25))
def test_the_boundary_is_exact_from_both_sides(level: int) -> None:
    """One XP short is the old level; the boundary itself is the new one.

    An off-by-one here is the defect a student actually notices — earning the
    XP for a level and not being given it. See this module's docstring for what
    this test does *not* prove.
    """
    boundary = level_floor(level)
    assert level_for_xp(boundary - 1) == level - 1
    assert level_for_xp(boundary) == level
    assert level_for_xp(boundary + 1) == level


def test_the_curve_never_goes_backwards() -> None:
    """Monotonic over a sweep spanning the first two dozen levels.

    A non-monotonic curve would let a student *lose* a level by earning XP,
    which no amount of boundary testing would catch on its own.
    """
    levels = [level_for_xp(total) for total in range(0, 60_000, 7)]
    assert levels == sorted(levels)


def test_a_negative_total_clamps_rather_than_raising() -> None:
    """Unreachable in practice, but this is a read path (D5.13's `level_for_xp` note).

    ``xp_events.amount`` is always positive and D5.1 §3 forbids persisting a
    0-amount row, so a negative total cannot occur — but 500-ing a student's
    profile screen over an impossible number is the wrong failure mode.
    """
    assert level_for_xp(-1) == 1


def test_level_zero_and_below_is_rejected_by_level_floor() -> None:
    """``level_floor`` is the inverse direction and *does* raise — it is not a read path."""
    with pytest.raises(ValueError, match="level must be >= 1"):
        level_floor(0)


@pytest.mark.parametrize("total", [0, 1, 99, 100, 399, 400, 1599, 1600, 2500, 12_345])
def test_progress_brackets_the_total_with_a_non_empty_band(total: int) -> None:
    """``start <= total < next`` always, so a progress bar's denominator is never zero."""
    progress = progress_for_xp(total)
    assert progress.level_start_xp <= total < progress.next_level_xp
    assert progress.next_level_xp > progress.level_start_xp
    assert progress.total_xp == total
    assert progress.level == level_for_xp(total)


def test_the_early_levels_arrive_quickly_and_later_ones_do_not() -> None:
    """The property that made the curve quadratic (D5.13 §1), pinned as a fact.

    One corrected paper is 50 XP (D5.1 §2), so a student is halfway to level 2
    on their first day — while the *gap* between consecutive levels keeps
    widening, which is what makes a high level a record of real work rather
    than a slow restatement of total XP.
    """
    assert level_floor(2) == 100
    gaps = [level_floor(n + 1) - level_floor(n) for n in range(1, 10)]
    assert gaps == sorted(gaps)
    assert len(set(gaps)) == len(gaps)
