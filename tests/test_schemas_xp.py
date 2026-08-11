"""D5.1 §0 / D5.13 §3 pins on the S-31 profile DTOs (P5.8 chunk A).

Introspects the Pydantic models' declared field sets rather than eyeballing the
source, on P5.3's precedent: "a comment saying 'don't put a mark here' is not a
control; a failing test is."

Two distinct rules are pinned. **No mark-shaped field** (D5.1 §0) — S-31 is the
student's own screen, so grade privacy is a weaker argument here than on the
leaderboard, but a mark reaching this response would make the *level* and the
streak a function of performance, which is the thing D5.1 §0 outranks
everything else to prevent. And **no activity-count field** (D5.13 §3) — the
count a caller would want cannot be derived from ``xp_events`` correctly,
because D5.1 §3's caps mean a capped award writes no row at all.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from lemely.web.schemas_xp import (
    StreakDTO,
    XpDayDTO,
    XpProfileDTO,
    XpSourceAmountDTO,
    XpWeekDTO,
)

# Substrings signalling a mark/grade leaked onto an effort surface (D5.1 §0 /
# UI spec §1.4). Matched case-insensitively against every field name.
_FORBIDDEN_MARK_SUBSTRINGS = (
    "mark",
    "percent",
    "grade",
    "accuracy",
    "score",
    "confidence",
    "correct",
)

# Substrings signalling an activity tally (D5.13 §3): a count derived from
# `xp_events` is wrong by construction, and a precise-looking wrong number on a
# "record of real work" screen is worse than an absent one.
_FORBIDDEN_COUNT_SUBSTRINGS = ("count", "papers", "questions", "hours", "sessions")

_ALL_DTOS: tuple[type[BaseModel], ...] = (
    XpSourceAmountDTO,
    XpWeekDTO,
    XpDayDTO,
    StreakDTO,
    XpProfileDTO,
)


class TestFieldSetsAreExact:
    """Exact equality, so a new field must be acknowledged deliberately."""

    def test_source_amount_is_exactly_a_source_and_its_xp(self) -> None:
        assert set(XpSourceAmountDTO.model_fields) == {"source", "xp"}

    def test_week_is_exactly_a_window_a_total_and_the_split(self) -> None:
        assert set(XpWeekDTO.model_fields) == {"start", "end", "total", "bySource"}

    def test_day_is_exactly_a_date_and_its_xp(self) -> None:
        assert set(XpDayDTO.model_fields) == {"day", "xp"}

    def test_streak_carries_no_derived_activity_claim(self) -> None:
        assert set(StreakDTO.model_fields) == {
            "current",
            "longest",
            "lastActiveOn",
            "freezesAvailable",
        }

    def test_profile_is_exactly_xp_level_streak_week_and_calendar(self) -> None:
        assert set(XpProfileDTO.model_fields) == {
            "totalXp",
            "level",
            "levelStartXp",
            "nextLevelXp",
            "streak",
            "week",
            "calendar",
            "calendarStart",
            "calendarEnd",
        }


@pytest.mark.parametrize("dto", _ALL_DTOS, ids=lambda d: d.__name__)
class TestNoForbiddenFields:
    def test_no_field_is_shaped_like_a_mark(self, dto: type[BaseModel]) -> None:
        lowered = {name.lower() for name in dto.model_fields}
        for forbidden in _FORBIDDEN_MARK_SUBSTRINGS:
            matches = [name for name in lowered if forbidden in name]
            assert not matches, (
                f"{dto.__name__} has a field matching forbidden mark substring "
                f"{forbidden!r}: {matches} (D5.1 §0)"
            )

    def test_no_field_is_shaped_like_an_activity_tally(self, dto: type[BaseModel]) -> None:
        lowered = {name.lower() for name in dto.model_fields}
        for forbidden in _FORBIDDEN_COUNT_SUBSTRINGS:
            matches = [name for name in lowered if forbidden in name]
            assert not matches, (
                f"{dto.__name__} has a field matching forbidden count substring "
                f"{forbidden!r}: {matches} (D5.13 §3 — a count derived from "
                f"xp_events is wrong by construction)"
            )


class TestNullabilityCarriesMeaning:
    def test_last_active_on_is_optional(self) -> None:
        """A student who has never earned XP has no last-active date.

        It must be null rather than a fabricated "today" (UI spec §1.4).
        """
        annotation = StreakDTO.model_fields["lastActiveOn"].annotation
        assert annotation is not None
        assert "None" in str(annotation) or "Optional" in str(annotation)

    def test_the_totals_are_not_optional(self) -> None:
        """XP and level are always knowable — 0 and 1 for a new student, never null.

        A nullable total would let a screen render "—" where the honest answer
        is "0", which reads as a failure rather than a starting point.
        """
        for field in ("totalXp", "level", "levelStartXp", "nextLevelXp"):
            annotation = str(XpProfileDTO.model_fields[field].annotation)
            assert "None" not in annotation, f"{field} should not be optional, got {annotation}"
