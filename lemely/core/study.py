"""Schemas for student profiles and study plans."""

from __future__ import annotations

from pydantic import Field

from lemely.core.schemas import StrictModel, WeaknessReport


class PlacementResult(StrictModel):
    subject_code: str
    weaknesses: WeaknessReport


class StudentProfile(StrictModel):
    student_id: str
    grade_level: str
    subjects: list[str]
    school: str | None = None
    weekly_study_hours: float = Field(..., gt=0)
    confidence_by_subject: dict[str, float] = {}  # noqa: RUF012


class StudySession(StrictModel):
    week: int
    topic: str
    subject_code: str
    hours: float
    focus: str


class StudyPlan(StrictModel):
    student_id: str
    weekly_hours: float
    sessions: list[StudySession]
    narrative: str | None = None
