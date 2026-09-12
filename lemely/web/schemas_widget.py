"""``GET /api/student/widget`` DTOs (packet A5).

Backs the Windows/Android widget surface declared in `vite/manifest.ts`'s
`widgets` member and rendered by `public/widgets/streak.json`'s Adaptive
Card template. Two fields only — the streak count and the next scheduled
study session, if any — because that is everything the Adaptive Card
template binds, via `${streak}` / `${nextSession.title}` /
`${nextSession.startsAt}`.

Mirrors `lemely.web.schemas_xp`'s style: an explicit `ApiModel` subclass per
DTO, camelCase names declared directly (no alias generator).
"""

from __future__ import annotations

from lemely.web.schemas import ApiModel


class WidgetNextSessionDTO(ApiModel):
    """The caller's earliest not-yet-completed study-plan session, this week."""

    title: str
    """The session's topic (`StudyPlanSessionDTO.topic`'s own field)."""

    startsAt: str
    """ISO 8601, UTC, noon. `SessionView.date` (the underlying record)
    carries no time of day — this is noon UTC of that date, not midnight
    (A5 review fix): the Adaptive Card template converts to the viewer's
    local timezone before rendering just the date, and midnight UTC shifts
    back a calendar day for anyone west of UTC. Noon is the time of day
    every realistic timezone offset still renders as the same date, so it
    represents the real day-granularity schedule without either fabricating
    an hour or being wrong for half the world."""


class StudentWidgetDTO(ApiModel):
    """The whole widget payload — matches `public/widgets/streak-data.json`'s shape."""

    streak: int
    """`XpService.profile(...).streak.current_length` — the same number
    `GET /api/student/xp` reports, never recomputed here."""

    nextSession: WidgetNextSessionDTO | None
    """`None` when nothing is next: no plan generated for any enrolled
    subject, a generated-but-refused plan (`available: false`), or every
    session in the current plan already completed. Never a 404 — a
    well-formed empty state, the same rule every other student-facing route
    in this phase follows."""
