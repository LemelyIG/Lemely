"""API DTOs for the Practice tab endpoints (L4). camelCase, mirroring ``schemas_practice.py``."""

from __future__ import annotations

from typing import Literal

from lemely.web.schemas import ApiModel

PracticeRunStatus = Literal["not_started", "in_progress", "submitted", "marked"]


class PracticeRunDTO(ApiModel):
    """One practice set in "Recent". ``awardedMarks``/``maximumMarks`` are set only when marked."""

    assignmentId: str
    subjectCode: str
    title: str
    topics: list[str]
    status: PracticeRunStatus
    questionCount: int
    answeredCount: int
    awardedMarks: int | None
    maximumMarks: int | None
    timeLimitMinutes: int | None
    lastActivityAt: str


class PracticeRunsDTO(ApiModel):
    """Response for ``GET /api/student/practice/runs``."""

    runs: list[PracticeRunDTO]


class PastPaperDTO(ApiModel):
    """One printable or already-done past paper."""

    paperId: str
    code: str
    subjectCode: str
    paperNumber: int
    paperVariant: int
    sessionLabel: str
    durationMinutes: int | None
    totalMarks: int | None
    questionCount: int
    awardedMarks: int | None
    maximumMarks: int | None


class PastPapersDTO(ApiModel):
    """Response for ``GET /api/student/practice/papers/{subject_code}``."""

    subjectCode: str
    papers: list[PastPaperDTO]


class CreateFromPaperRequestDTO(ApiModel):
    """Body for ``POST /api/student/practice/papers/{paper_id}``."""

    timed: bool = False
