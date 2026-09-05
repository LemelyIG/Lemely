"""API DTOs and core→DTO converters for the FastAPI backend.

These models mirror the frontend contract in ``web/src/lib/types.ts`` (camelCase
field names). Keeping them separate from ``lemely.core.schemas`` lets the wire
format evolve independently of the domain model. Converters translate the
snake_case core objects into these camelCase DTOs.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from lemely.core.schemas import (
    CorrectedQuestion,
    CorrectionResult,
)
from lemely.core.schemas import (
    WeakArea as CoreWeakArea,
)

MarkerSource = Literal["deterministic", "ai", "missing"]


class ApiModel(BaseModel):
    """Base DTO: forbids extra fields and serialises via camelCase aliases."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class QuestionResultDTO(ApiModel):
    """Per-question grading result — mirrors ``QuestionResult`` in types.ts."""

    questionId: str
    awardedMarks: int
    maxMarks: int
    markerSource: MarkerSource
    confidence: float | None = None
    feedback: str | None = None
    matchedPointIds: list[str] | None = None
    reviewReason: str | None = None
    plagiarismFlagged: bool = False
    aiDetectionFlagged: bool = False
    topic: str | None = None


class WeakAreaDTO(ApiModel):
    """Weak-area summary — mirrors ``WeakArea`` in types.ts."""

    topic: str
    marksLost: int
    marksAvailable: int


class GradeResultDTO(ApiModel):
    """Full grading payload returned once a grade job completes."""

    awardedMarks: int
    maxMarks: int
    needsTeacherReview: bool
    questions: list[QuestionResultDTO]


class StorageHealthDTO(ApiModel):
    """Which object-storage backend this process is configured for (DS12)."""

    backend: str
    bucket: str


class HealthDTO(ApiModel):
    """Health-check payload for ``GET /api/health``."""

    status: Literal["ok"] = "ok"
    apiKeyConfigured: bool
    storage: StorageHealthDTO

    #: False when grade boundaries cannot be read, for either of two reasons:
    #: a fresh/unseeded database with no verified grade-boundary rows (where
    #: ``GradeBoundaryStore`` refuses to grade against invented numbers -- see
    #: ``lemely.io.grade_boundaries``), or a database that could not be reached
    #: or queried at all. ``/api/health`` stays 200 in both cases so the check
    #: itself never crashes; the backend log discriminates them, since only the
    #: second writes ``health: could not read grade boundaries from the
    #: database``. A deploy can poll this to catch "migrations ran, ingest
    #: never did" before a student sees a wrong grade.
    #:
    #: Scope: the store is cached, so this reflects the state at first load.
    #: A database that fails *after* boundaries loaded leaves this ``true``.
    gradeBoundariesLoaded: bool


def question_to_dto(question: CorrectedQuestion) -> QuestionResultDTO:
    """Convert a core :class:`CorrectedQuestion` into a :class:`QuestionResultDTO`."""
    return QuestionResultDTO(
        questionId=question.question_id,
        awardedMarks=question.awarded_marks,
        maxMarks=question.maximum_marks,
        markerSource=question.marker_source,
        confidence=question.confidence_score,
        feedback=question.feedback,
        matchedPointIds=list(question.matched_point_ids) or None,
        reviewReason=question.review_reason,
        plagiarismFlagged=question.plagiarism_flagged,
        aiDetectionFlagged=question.ai_detection_flagged,
        topic=question.topic,
    )


def correction_to_dto(correction: CorrectionResult) -> GradeResultDTO:
    """Convert a core :class:`CorrectionResult` into a :class:`GradeResultDTO`."""
    return GradeResultDTO(
        awardedMarks=correction.awarded_marks,
        maxMarks=correction.maximum_marks,
        needsTeacherReview=correction.needs_teacher_review,
        questions=[question_to_dto(q) for q in correction.questions],
    )


def weak_area_to_dto(weak_area: CoreWeakArea) -> WeakAreaDTO:
    """Convert a core :class:`WeakArea` into a :class:`WeakAreaDTO`."""
    return WeakAreaDTO(
        topic=weak_area.topic,
        marksLost=weak_area.lost_marks,
        marksAvailable=weak_area.maximum_marks,
    )
