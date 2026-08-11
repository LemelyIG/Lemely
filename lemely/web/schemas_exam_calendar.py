"""``/api/student/exam-calendar`` DTOs (P5.5 chunk C, D5.8).

**The availability fields are the load-bearing part of this contract, not
metadata.** This surface ships with an empty table in every environment this
build produces, so the response's job is to let the screen say *why* it has
nothing — "finish onboarding" and "we do not hold the official timetable yet"
are different sentences owed to different students, and an empty ``entries``
list can express neither. The P4.5/D4.10 tri-state pattern, applied to the one
screen where a fabricated value would misinform revision planning rather than
merely disappoint (UI spec 1.4).

Structurally answer-only (D5.1 §0): no field shaped like a mark, grade or
percentage exists here, and the field sets are introspected by a test.
"""

from __future__ import annotations

from datetime import date  # noqa: TC003 - pydantic needs the real type at runtime
from typing import Literal

from lemely.web.schemas import ApiModel


class ExamDateDTO(ApiModel):
    """One dated paper variant, as an official timetable states it."""

    paperVariant: str
    examDate: date
    startsAtLocal: str | None
    """Local start time exactly as the timetable prints it, or ``None`` when
    it does not state one. Never defaulted to midnight — a missing time must
    read as missing."""
    durationMinutes: int | None
    source: str
    """Which published timetable this date came from.

    On the wire, not just in the database: a student or teacher who thinks a
    date is wrong can name the document rather than argue with the app."""


class StudentExamEntryDTO(ApiModel):
    """One paper the student declared, with whatever dates we honestly hold."""

    subjectCode: str
    sessionMonth: str | None
    sessionYear: int | None
    paperNumber: int
    availability: Literal["dated", "no_timetable", "no_session"]
    """Why ``dates`` looks the way it does.

    ``no_session`` means *this student* has not said which session they are
    sitting, which is a gap in their onboarding; ``no_timetable`` means we
    hold no official dates for a session they did name, which is the
    platform's gap. Presenting the first as the second would blame Cambridge
    for a blank the student can fill in themselves."""
    dates: list[ExamDateDTO]
    """A list, not a single date. The timetable's grain is the variant and the
    student declares only a paper number, so "Paper 2" can legitimately map to
    several variants sitting on different days. Picking the earliest would
    invent the one fact the student never gave us."""


class StudentExamCalendarDTO(ApiModel):
    """``GET /api/student/exam-calendar`` response."""

    availability: Literal["available", "no_enrolment", "no_timetable"]
    entries: list[StudentExamEntryDTO]


__all__ = [
    "ExamDateDTO",
    "StudentExamCalendarDTO",
    "StudentExamEntryDTO",
]
