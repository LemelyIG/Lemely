"""SM-2 spaced-repetition scheduler for flashcard reviews (P4.6 chunk A).

Pure by construction: no DB import, no ``io`` import, no clock of its own.
Every function that cares about "now" takes it as an injected ``now``
parameter, matching :mod:`lemely.core.at_risk` and
:mod:`lemely.core.class_analytics`'s style — a scheduler that reads the wall
clock internally cannot be tested by inversion (same input, same output), and
the import-linter layering contract (``lemely/pyproject.toml``
``[tool.importlinter]``) forbids ``core`` from importing ``db``/``io`` in the
first place.

**Two mirrored ``ReviewGrade`` enums exist on purpose, do not deduplicate
them.** This module defines its own :class:`ReviewGrade` because ``core``
must not import ``lemely.db`` (the layering contract again).
``lemely.db.models.flashcards.ReviewGrade`` is the Postgres-enum mirror with
the same four members in the same order; a migration change to one without
the other is exactly the drift ``tests/test_flashcard_schema.py`` is written
to catch. If a future refactor is tempted to import one from the other across
the ``core``/``db`` boundary, that import is the layering violation this
docstring is warning about — see the matching comment in
``lemely/db/models/flashcards.py``.

**SM-2, and the five gaps the canonical algorithm leaves open:**

1. **Quality mapping.** SM-2 grades a review 0-5. The four-button UI
   (again/hard/good/easy) is standard spaced-repetition UX (Anki, SuperMemo's
   own later versions) collapsed onto SM-2's five-point scale:
   ``again=0`` (complete blackout), ``hard=3`` (correct, but only after
   real hesitation — the lowest *passing* grade), ``good=4`` (correct,
   some hesitation), ``easy=5`` (correct, no hesitation). There is no
   quality 1 or 2 exposed: SM-2 treats anything below 3 as a failure and
   this scheduler has no button that means "wrong but not a blackout" —
   inventing one would be precision this module cannot justify from a
   four-button grade.

2. **The ease-factor update runs on every grade, including ``again`` —
   and this is a departure from canonical SM-2, not a faithful reading of
   it.** SM-2's published step 5 says that on ``q < 3`` you restart the
   repetitions "*without changing the E-Factor*"; only step 6's formula
   (``EF' = EF + (0.1 - (5-q)*(0.08 + (5-q)*0.02))``) is applied on a pass.
   This module applies that formula on every grade instead, so a blackout
   costs ease (``q=0`` drops EF by ~0.8 in one review). The reason is that
   a lapse is the strongest evidence available that the card's interval was
   too long, and leaving EF untouched means a repeatedly-failed card keeps
   being rescheduled on the same optimistic multiplier; Anki and the later
   SuperMemo algorithms both penalise ease on a lapse for this reason.
   The floor in point 3 is what bounds the penalty. Pinned by
   ``test_again_shortens_the_interval_and_increments_lapses`` — if this
   choice is ever revisited, that is the test to change, deliberately.

3. **The ease floor (1.3) is the thing that stops a repeatedly-failed card
   from being scheduled into nonsense.** Without it, a card graded
   ``again`` over and over would have its ease factor driven arbitrarily
   negative, and the interval formula (``round(prev_interval *
   ease_factor)``) would then either shrink through zero or flip the sign
   of every future interval. 1.3 is SM-2's own published floor, not a
   value invented for this module.

4. **The ``again`` interval is a deliberate departure from canonical SM-2.**
   Canonical SM-2 sets ``interval = 1 day`` even on a failure — it was
   designed for daily paper decks with no concept of same-session
   relearning. This module instead reschedules an ``again`` card for
   :data:`AGAIN_REVIEW_DELAY` (10 minutes) later and reports
   ``interval_days = 0``, matching the "relearning step" behaviour every
   modern SRS implementation (Anki included) actually ships, so a card a
   student just got wrong resurfaces in the same study session instead of
   vanishing for a day. ``repetitions`` resets to 0 and ``lapses``
   increments, exactly as canonical SM-2 does on failure.

5. **Rounding.** ``round(prev_interval_days * ease_factor)`` uses Python's
   banker's rounding (round-half-to-even) — the built-in ``round()``, no
   custom rounding rule. SM-2 does not specify a tie-breaking rule and none
   is inferable from the algorithm; banker's rounding is what ``round()``
   gives for free and this module does not invent a more "precise" rule it
   cannot justify.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

#: A new card's starting ease factor (SM-2's published default).
INITIAL_EASE_FACTOR = 2.5

#: SM-2's published floor — see docstring point 3.
EASE_FACTOR_FLOOR = 1.3

#: How long an ``again``-graded card is set aside before resurfacing in the
#: same session — see docstring point 4.
AGAIN_REVIEW_DELAY = timedelta(minutes=10)


class ReviewGrade(enum.Enum):
    """The four-button self-grade a student gives a flashcard review.

    Mirrored (not imported) by ``lemely.db.models.flashcards.ReviewGrade`` —
    see the module docstring for why the mirror exists instead of a shared
    import.
    """

    again = "again"
    hard = "hard"
    good = "good"
    easy = "easy"


#: SM-2 quality (0-5) for each grade — see module docstring point 1.
_QUALITY: dict[ReviewGrade, int] = {
    ReviewGrade.again: 0,
    ReviewGrade.hard: 3,
    ReviewGrade.good: 4,
    ReviewGrade.easy: 5,
}

#: The lowest quality SM-2 counts as a *pass* (repetitions continue to build).
_PASS_QUALITY_THRESHOLD = 3


@dataclass(frozen=True, slots=True)
class CardSchedule:
    """A flashcard's SM-2 scheduling state at a point in time.

    Mirrors ``lemely/db/models/flashcards.py``'s ``flashcards`` SM-2 columns
    exactly (``repetitions``/``ease_factor``/``interval_days``/``lapses``/
    ``due_at``/``last_reviewed_at``) so a row can round-trip through this
    dataclass with no translation layer.
    """

    repetitions: int
    ease_factor: float
    interval_days: int
    lapses: int
    due_at: datetime
    last_reviewed_at: datetime | None


def initial_schedule(now: datetime) -> CardSchedule:
    """The schedule state for a brand-new card: due immediately.

    A card that has never been reviewed has nothing to wait for — S-22
    ("nothing due today") should not be defeated by a freshly created card
    that will not appear until tomorrow.
    """
    return CardSchedule(
        repetitions=0,
        ease_factor=INITIAL_EASE_FACTOR,
        interval_days=0,
        lapses=0,
        due_at=now,
        last_reviewed_at=None,
    )


def review(schedule: CardSchedule, grade: ReviewGrade, *, now: datetime) -> CardSchedule:
    """Apply one SM-2 review to ``schedule`` and return the next state.

    Pure: the same ``(schedule, grade, now)`` always produces the same
    result, and no wall clock is read — only the injected ``now``. See the
    module docstring for the four places this diverges from, or fills a gap
    in, canonical SM-2.
    """
    quality = _QUALITY[grade]

    ease_factor = schedule.ease_factor + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    ease_factor = max(ease_factor, EASE_FACTOR_FLOOR)

    if quality < _PASS_QUALITY_THRESHOLD:
        # A blackout: same-session relearning step, not a day-scale
        # interval. See module docstring point 4.
        return replace(
            schedule,
            repetitions=0,
            ease_factor=ease_factor,
            interval_days=0,
            lapses=schedule.lapses + 1,
            due_at=now + AGAIN_REVIEW_DELAY,
            last_reviewed_at=now,
        )

    repetitions = schedule.repetitions + 1
    if repetitions == 1:
        interval_days = 1
    elif repetitions == 2:
        interval_days = 6
    else:
        # Canonical SM-2 ordering: the interval multiplies the *pre-update*
        # ease factor (computed above but not yet applied), then the ease
        # factor itself is updated for the *next* review below.
        interval_days = round(schedule.interval_days * schedule.ease_factor)

    return replace(
        schedule,
        repetitions=repetitions,
        ease_factor=ease_factor,
        interval_days=interval_days,
        due_at=now + timedelta(days=interval_days),
        last_reviewed_at=now,
    )


__all__ = [
    "AGAIN_REVIEW_DELAY",
    "EASE_FACTOR_FLOOR",
    "INITIAL_EASE_FACTOR",
    "CardSchedule",
    "ReviewGrade",
    "initial_schedule",
    "review",
]
