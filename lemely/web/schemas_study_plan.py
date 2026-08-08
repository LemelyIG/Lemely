"""API DTOs for the persisted adaptive study-plan endpoints (P4.7 chunk C).

Field names are camelCase to match the frontend contract, mirroring
``schemas_placement.py``. Converters live in
``lemely.web.routers.study_plan``.

These DTOs are new and distinct from the legacy ``StudyPlanDTO`` in
``lemely.web.routers.student`` (the ``GET``/``POST /api/student/plan``
routes) — that surface stays untouched until P4.10 migrates the frontend.
``activityType`` and ``date`` are exposed per session here for the first
time (D4.12 §5's stated gap); the legacy DTO never surfaced them.
"""

from __future__ import annotations

from datetime import date, datetime  # noqa: TC003 - pydantic needs the real type at runtime

from lemely.web.schemas import ApiModel


class StudyPlanSessionDTO(ApiModel):
    """One scheduled session, as persisted.

    ``id`` is a ``str`` (a UUID on the wire), matching every other DTO in
    this codebase (``schemas_placement.py``, ``schemas_flashcards.py``).
    """

    id: str
    date: date
    topic: str
    activityType: str
    durationMinutes: int
    focus: str
    completedAt: datetime | None


class StudyPlanWeekDTO(ApiModel):
    """One persisted weekly plan and its sessions.

    ``available``/``reason`` mirror :class:`lemely.core.study.StudyPlan`'s
    honesty fields verbatim (P4.7 chunk B's persistence, D4.12): a plan may
    legitimately have ``available=True`` and an empty ``sessions`` list
    ("nothing to schedule this week"), which is a different state from
    ``available=False`` ("nothing to evaluate at all" — a ``no_signal``
    refusal). Neither state is a 404; see
    :class:`CurrentStudyPlanDTO` for the third state, "no plan generated
    yet this week", which lives one level up.
    """

    id: str
    subjectCode: str
    weekStart: date
    weeklyHours: float
    available: bool
    reason: str | None
    generatedAt: datetime
    sessions: list[StudyPlanSessionDTO]


class CurrentStudyPlanDTO(ApiModel):
    """``GET /api/student/study-plan/{subject_code}``'s payload.

    Three distinguishable wire states (D4.12 §5's open gap, closed here):

    * ``{"generated": false, "plan": null}`` — no plan has been generated
      for this ISO week at all.
    * ``{"generated": true, "plan": {"available": false, "reason":
      "no_signal", "sessions": [], ...}}`` — a plan was generated and it
      was an honest refusal.
    * ``{"generated": true, "plan": {"available": true, "sessions": [...],
      ...}}`` — a real plan, which may itself have an empty ``sessions``
      list ("there was something to evaluate and nothing to schedule").

    None of these three collapse into another, and none of them is a 404.
    """

    generated: bool
    plan: StudyPlanWeekDTO | None


class CreateStudyPlanRequestDTO(ApiModel):
    subjectCode: str
