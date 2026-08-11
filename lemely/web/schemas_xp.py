"""``GET /api/student/xp`` DTOs (P5.8 chunk A, D5.13).

**Structurally effort-only, on the same terms as the leaderboard's DTOs
(D5.1 §0).** S-31 is the student's own screen rather than a public one, so the
grade-privacy argument is weaker here — but XP is defined as "did you do the
work, never how well", and a mark reaching this response would make the *level*
and the streak a function of performance. So no field on these models is shaped
like a mark, percentage, accuracy, grade or predicted grade, and
``tests/test_schemas_xp.py`` introspects the field sets so a later addition
fails a test rather than silently reaching the wire.

**``bySource`` is XP per source, never an activity count** (D5.13 §3). It is
tempting to read ``paper_corrected: 150`` as "three papers"; D5.1 §3's daily
caps mean a capped award writes no row and §8's dedupe means a re-corrected
paper writes one row for two markings, so any count derived from this is wrong
by construction. UI spec §1.4 forbids presenting it as one, which is why the
field is named for XP and no ``count`` sits beside it.

Mirrors :mod:`lemely.web.schemas_leaderboard`'s style: an explicit ``ApiModel``
subclass per DTO, camelCase names declared directly (no alias generator).
"""

from __future__ import annotations

from datetime import date  # noqa: TC003 - pydantic needs the real type at runtime

from lemely.web.schemas import ApiModel


class XpSourceAmountDTO(ApiModel):
    """XP earned from one of D5.1 §1's four sources over a window."""

    source: str
    """One of ``paper_corrected``, ``quiz_completed``, ``flashcard_reviewed``,
    ``study_session_completed`` — the ``xpsource`` enum's four values, which
    D5.1 §1 fixes as the whole scope of Phase 5."""
    xp: int
    """XP, not a tally of actions. See the module docstring."""


class XpWeekDTO(ApiModel):
    """This week's XP, split by source (S-31's "XP earned this week").

    The window is D5.1 §6's — Monday 00:00 to Sunday 23:59:59 Cairo — resolved
    through the same :func:`lemely.db.xp_repo.week_bounds` the leaderboard
    uses, so S-29 and S-31 cannot report two different weeks for one fact
    (D5.13 §2).
    """

    start: date
    end: date
    total: int
    bySource: list[XpSourceAmountDTO]
    """All four sources, always, 0 for any that earned nothing this week — a
    bar chart never has to special-case a missing key. Ordered by the
    ``XpSource`` enum's declaration order, which is stable."""


class XpDayDTO(ApiModel):
    """One day of the streak calendar: the date, and the XP it earned."""

    day: date
    xp: int


class StreakDTO(ApiModel):
    """The student's streak as of this request (D5.1 §4/§5).

    Resolved lazily on read — there is no scheduler in this build — so a
    returning student's stale streak never appears healthier than it is just
    because nobody has read it in weeks.
    """

    current: int
    longest: int
    lastActiveOn: date | None
    """``None`` for a student who has never earned XP. Never a fabricated
    "today" (UI spec §1.4)."""
    freezesAvailable: int


class XpProfileDTO(ApiModel):
    """``GET /api/student/xp`` response — S-31's whole data dependency.

    Deliberately absent: **lifetime activity stats and achievements**
    (D5.13 §3). UI spec S-31 lists "papers marked, questions answered, hours
    studied"; the first two can only be derived from ``xp_events`` in a way the
    caps and dedupe rules make wrong, and the third has no source in this
    schema at all. An absent stat is honest; a precise-looking wrong one is
    not.
    """

    totalXp: int
    level: int
    levelStartXp: int
    """XP at which the current level began. ``totalXp - levelStartXp`` is
    progress into it."""
    nextLevelXp: int
    """XP at which the next level begins. Always strictly greater than
    ``levelStartXp``, so a progress bar's denominator is never zero."""
    streak: StreakDTO
    week: XpWeekDTO
    calendar: list[XpDayDTO]
    """The last 28 days that earned XP, oldest first. **Days with no XP are
    absent, not zero-valued** (D5.13 §4) — the client fills the grid from
    ``calendarStart``/``calendarEnd``, so "no XP" and "outside the window"
    cannot be rendered as two different things by accident."""
    calendarStart: date
    calendarEnd: date
    """The inclusive window ``calendar`` was drawn from, so the client knows
    exactly how many cells to render without assuming 28."""


__all__ = [
    "StreakDTO",
    "XpDayDTO",
    "XpProfileDTO",
    "XpSourceAmountDTO",
    "XpWeekDTO",
]
