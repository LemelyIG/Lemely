"""The XP-to-level curve (D5.13 §1, the mapping D5.1 §10 deferred to P5.8).

**The single implementation of the curve.** S-31 renders a level and a progress
bar; the route returns ``level``, ``levelStartXp`` and ``nextLevelXp`` so the
screen never re-derives any of it in TypeScript. A second copy on the client is
the kind of duplicate that stays right for a year and then disagrees after one
tweak to the constant.

The curve is **level N begins at 100·(N-1)² XP** — 0, 100, 400, 900, 1600,
2500 — and it is a pure function of total XP, which is the constraint D5.1 §10
placed on whatever P5.8 chose. Quadratic rather than linear so the first levels
arrive quickly and later ones represent real accumulated work (UI spec S-31
wants the screen to read as a training log); against D5.1 §2's award amounts, a
student correcting one paper a day reaches level 2 on day 2, level 3 on day 8,
level 4 on day 18 and level 5 on day 32.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

#: XP required for level 2. Level N's floor is ``LEVEL_STEP * (N - 1) ** 2``.
LEVEL_STEP = 100


@dataclass(frozen=True, slots=True)
class LevelProgress:
    """Where a total sits on the curve: the level, and the band containing it.

    ``level_start_xp <= total_xp < next_level_xp`` always holds, so a caller
    can draw a progress bar as ``(total - start) / (next - start)`` without
    guarding against a zero-width or negative band.
    """

    level: int
    total_xp: int
    level_start_xp: int
    next_level_xp: int


def level_floor(level: int) -> int:
    """The XP at which ``level`` begins. ``level_floor(1)`` is 0.

    Raises:
        ValueError: ``level`` is below 1 — there is no level 0.
    """
    if level < 1:
        raise ValueError(f"level must be >= 1, got {level}")
    return LEVEL_STEP * (level - 1) ** 2


def level_for_xp(total_xp: int) -> int:
    """The level containing ``total_xp``.

    **Integer arithmetic** (D5.13 §1). ``isqrt(x // 100) >= N`` iff
    ``x >= 100·N²``, because N² is an integer — so this *is* the curve in the
    module docstring, not an approximation that happens to agree with it, and
    the equivalence is provable by hand rather than by sampling.

    The float form ``floor(sqrt(total / 100))`` was measured and is **not**
    wrong here (P5.8 chunk A inverted this and every boundary test still
    passed): at a boundary ``100·N²`` the division and the square root are both
    exact in IEEE 754 for any total this product can reach. It is avoided
    anyway because its correctness *depends* on that argument holding — for
    every input, forever — while the integer form's does not depend on
    anything. Do not restore the claim that it fails at a boundary; it does
    not, and a decision record justified by a fabricated failure mode is worse
    than no justification.

    A negative total is not reachable — ``xp_events.amount`` is always positive
    and D5.1 §3 forbids persisting a 0-amount row — but it clamps to level 1
    rather than raising, because this runs on a read path where a
    ``ValueError`` would 500 a profile screen over an impossible number.
    """
    if total_xp < LEVEL_STEP:
        return 1
    return math.isqrt(total_xp // LEVEL_STEP) + 1


def progress_for_xp(total_xp: int) -> LevelProgress:
    """Resolve ``total_xp`` into its level and the XP band around it."""
    level = level_for_xp(total_xp)
    return LevelProgress(
        level=level,
        total_xp=total_xp,
        level_start_xp=level_floor(level),
        next_level_xp=level_floor(level + 1),
    )


__all__ = ["LEVEL_STEP", "LevelProgress", "level_floor", "level_for_xp", "progress_for_xp"]
