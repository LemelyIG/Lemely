"""Schemas for student profiles and study plans."""

from __future__ import annotations

import datetime
from enum import StrEnum

from pydantic import Field

from lemely.core.schemas import StrictModel


class StudentProfile(StrictModel):
    student_id: str
    grade_level: str
    subjects: list[str]
    school: str | None = None
    weekly_study_hours: float = Field(..., gt=0)
    confidence_by_subject: dict[str, float] = {}  # noqa: RUF012


class ActivityType(StrEnum):
    """What a scheduled session actually asks the student to do.

    Each member must be *earned* by an availability signal before
    :mod:`lemely.core.study_plan` may schedule it — see that module's
    docstring. ``review`` is the one member that needs no resource (re-read
    notes / redo worked examples) and is therefore the honest fallback when
    nothing else is earned, never a value invented to fill a gap.
    """

    practice = "practice"
    flashcards = "flashcards"
    past_paper = "past_paper"
    review = "review"


class StudySession(StrictModel):
    date: datetime.date
    """A real calendar date derived from the scheduler's injected clock, not
    a placeholder like the old literal ``week=1`` — see
    :mod:`lemely.core.study_plan`."""
    topic: str
    subject_code: str
    activity_type: ActivityType
    duration_minutes: int = Field(..., gt=0)
    focus: str


class StudyPlanUnavailableReason(StrEnum):
    """Why a study plan could not be built.

    Mirrors :class:`lemely.core.placement.UnavailableReason`'s
    machine-readable shape.
    """

    no_signal = "no_signal"
    """No weakness rows, no placement result, and no questionnaire ratings —
    there is nothing to schedule from, and inventing a plausible-looking week
    anyway would be exactly the laundering S-24/D4.6 refuse elsewhere."""


class StudyPlan(StrictModel):
    student_id: str
    weekly_hours: float
    sessions: list[StudySession]
    narrative: str | None = None
    available: bool = True
    """``False`` only for the honest refusal
    (:class:`StudyPlanUnavailableReason`); an *empty* ``sessions`` list with
    ``available=True`` is a different, equally real state — every topic
    scored zero, so there is nothing to schedule this week, not that nothing
    could be evaluated."""
    reason: str | None = None
    """A :class:`StudyPlanUnavailableReason` value, or ``None`` when
    ``available`` is ``True``."""
