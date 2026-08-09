"""``GET /api/student/leaderboard`` DTOs (P5.3 chunk B, D5.1).

**Structurally answer-only (D5.1 §0).** A leaderboard is the one public
surface in this product — MISSION §3 fixes "leaderboards show XP (effort),
never grades", and UI spec §1.4 makes grades private to the student, their
parents and their teachers. So :class:`LeaderboardRowDTO` and
:class:`LeaderboardViewerDTO` carry display identity, weekly XP and rank —
and nothing shaped like a mark, percentage, accuracy, grade or
predicted-grade. Not "left unset": those fields do not exist on these
models, so a well-meaning future addition three years from now fails
``tests/test_schemas_leaderboard.py``'s field-set introspection instead of
silently reaching the wire.

Mirrors :mod:`lemely.web.schemas_student_profile`'s style: an explicit
``ApiModel`` subclass per DTO, camelCase names declared directly (no alias
generator).
"""

from __future__ import annotations

from datetime import date  # noqa: TC003 - pydantic needs the real type at runtime
from typing import Literal

from lemely.web.schemas import ApiModel


class LeaderboardRowDTO(ApiModel):
    """One ranked entry on a board. Only display identity, XP and rank (D5.1 §0)."""

    userId: str
    displayName: str
    xp: int
    rank: int
    """Standard competition ranking (equal XP -> equal rank; ties skip the next rank)."""


class LeaderboardViewerDTO(ApiModel):
    """The viewer's own pinned row — always present when ``status="ok"``.

    Present even when the viewer falls outside the returned ``rows`` (D5.1
    §9: "they keep earning XP... and still see their own totals"), so a
    screen can always show "you" even off the visible page.
    """

    userId: str
    displayName: str
    xp: int
    rank: int | None
    """``None`` when the viewer has no XP this week, or is opted out —
    never a fabricated last place (UI spec §1.4: never invent precision)."""


class LeaderboardDTO(ApiModel):
    """``GET /api/student/leaderboard`` response.

    ``status="unavailable"`` (school scope, viewer holds no non-revoked seat
    at any school) is a **successful** response, never a 404 and never an
    empty board — an empty board would falsely assert "nobody scored this
    week" (D5.1 §9), which is a different and untrue claim from "this scope
    has nothing to rank the viewer against".
    """

    status: Literal["ok", "unavailable"]
    unavailableReason: Literal["no_school"] | None = None
    weekStart: date
    weekEnd: date
    rows: list[LeaderboardRowDTO]
    """The top-N ranked rows. Empty when ``status="unavailable"``. Never
    includes an opted-out student — enforced in the query's own WHERE clause
    (``lemely.db.leaderboard_repo``), not filtered here."""
    viewer: LeaderboardViewerDTO | None
    """``None`` iff ``status="unavailable"``."""
    viewerOptedOut: bool
    """The explicit "you have opted out" fact (D5.1 §9) — present regardless
    of ``status``, so a screen can plainly say so and offer the undo, distinct
    from the viewer simply having no XP this week."""


__all__ = ["LeaderboardDTO", "LeaderboardRowDTO", "LeaderboardViewerDTO"]
