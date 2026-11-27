"""DTOs for ``GET /api/student/home`` (redesign lane L1).

camelCase on the wire, like every other student DTO. Every field is data-backed
by an existing service; see :mod:`lemely.web.services.student_home` for which.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import Field

from lemely.web.schemas import ApiModel


class TeacherReplyDTO(ApiModel):
    """A teacher resolved a review item on one of the caller's answers."""

    reviewId: str
    teacherName: str
    questionId: str
    subjectCode: str | None
    subjectName: str | None
    paperNumber: int | None
    marksAdded: int
    paperId: str | None
    resolvedAt: datetime


class MarkingMomentDTO(ApiModel):
    kind: Literal["marking"] = "marking"
    paperId: str
    filename: str | None
    startedAt: datetime | None
    stale: bool
    questionsDone: int | None = None
    questionsTotal: int | None = None


class PaperMomentDTO(ApiModel):
    kind: Literal["result", "tough"]
    paperId: str
    subjectCode: str
    subjectName: str
    paperNumber: int
    awarded: int
    maximum: int
    grade: str
    previousGrade: str | None
    focusQuestion: str | None
    recordedAt: datetime


class TeacherReplyMomentDTO(ApiModel):
    kind: Literal["teacherReply"] = "teacherReply"
    reply: TeacherReplyDTO


class StreakMomentDTO(ApiModel):
    kind: Literal["streakAtRisk", "goalDone"]
    streakDays: int


class BackMomentDTO(ApiModel):
    kind: Literal["backAfterBreak"] = "backAfterBreak"
    daysAway: int


MomentDTO = Annotated[
    MarkingMomentDTO | PaperMomentDTO | TeacherReplyMomentDTO | StreakMomentDTO | BackMomentDTO,
    Field(discriminator="kind"),
]


class TodayDTO(ApiModel):
    practice: bool
    flashcards: bool
    paperThisWeek: bool


class PlanSessionDTO(ApiModel):
    sessionId: str
    subjectCode: str
    topic: str
    minutes: int
    done: bool


class WeekDayDTO(ApiModel):
    day: date
    label: str | None
    done: bool
    isToday: bool


class StreakDTO(ApiModel):
    current: int
    longest: int
    lastActiveOn: date | None
    freezesAvailable: int


class FloorSubjectDTO(ApiModel):
    code: str
    name: str
    grade: str
    previousGrade: str | None
    nextGrade: str | None
    pointsToNext: int | None
    papers: int


class WinBackTopicDTO(ApiModel):
    topic: str
    subjectCode: str
    subjectName: str
    marks: int


class RecentPaperDTO(ApiModel):
    paperId: str
    subjectCode: str
    subjectName: str
    paperNumber: int
    awarded: int
    maximum: int
    grade: str
    recordedAt: datetime


class HomeworkDTO(ApiModel):
    assignmentId: str
    title: str
    subjectCode: str
    teacherName: str
    dueAt: datetime | None
    questionCount: int
    isOverdue: bool


class BestGradeDTO(ApiModel):
    grade: str
    subjectCode: str


class HomeStatsDTO(ApiModel):
    papersMarked: int
    marksWonBack: int
    bestGrade: BestGradeDTO | None


class ActivityDTO(ApiModel):
    kind: Literal["paper", "practice", "teacher"]
    title: str
    sub: str
    at: datetime


class StudentHomeDTO(ApiModel):
    """Payload for ``GET /api/student/home``."""

    studentName: str
    localDate: date
    localHour: int
    moments: list[MomentDTO]
    goals: TodayDTO
    todaySessions: list[PlanSessionDTO]
    week: list[WeekDayDTO]
    streak: StreakDTO
    nextExamOn: date | None
    floor: list[FloorSubjectDTO]
    winBack: list[WinBackTopicDTO]
    recentPapers: list[RecentPaperDTO]
    lastPaperAt: datetime | None
    teacherReplies: list[TeacherReplyDTO]
    homework: list[HomeworkDTO]
    classCount: int
    stats: HomeStatsDTO
    activity: list[ActivityDTO]
