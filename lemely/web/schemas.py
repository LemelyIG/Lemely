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
    questionResultId: str | None = None
    """``question_results.id`` once the attempt is persisted; the address the
    self-review routes take. ``None`` on a frame built before persistence
    (a teacher-console grade, which has no ``question_results`` row)."""
    pendingTeacher: bool | None = None
    """Whether a teacher still has an open review queued for this question,
    right now — not ``reviewReason``'s frozen record of why it was once
    flagged. ``None`` on every call site except the student self-review list
    (``routers/student_self_review.py``), which is the only one with a queue
    to ask; a client must not read absence as "settled"."""


class WeakAreaDTO(ApiModel):
    """Weak-area summary — mirrors ``WeakArea`` in types.ts."""

    topic: str
    marksLost: int
    marksAvailable: int


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


#: Prefixes of the ``review_reason`` segments ``lemely/io/integrity.py`` writes
#: for a plagiarism or AI-content finding, e.g. ``"plagiarism (score 0.94)"``.
#: The reason is a ``" | "``-joined list, so an integrity finding travels in the
#: same free-text field as ordinary marking reasons.
_INTEGRITY_REASON_PREFIXES = ("plagiarism", "ai_detection")


def student_safe_review_reason(reason: str | None) -> str | None:
    """Drop integrity findings from a ``review_reason`` bound for a student.

    QUALITY-BAR.md: "No screen accuses a student of cheating; integrity flags
    are teacher-only." The two booleans are easy to remember and were already
    forced off on student surfaces — but ``review_reason`` is free text that
    ``lemely/io/integrity.py`` appends ``"plagiarism (score 0.94)"`` to, and
    ``PaperResult`` renders it verbatim as "Needs review: ...". Suppressing the
    flags while forwarding the sentence tells the student anyway, with a score
    attached.

    Other marking reasons survive: a student is told *that* a question needs a
    look, just never that the reason was an integrity finding. A reason made up
    only of integrity segments becomes ``None``, not an empty string.
    """
    if not reason:
        return None
    kept = [
        segment
        for segment in (part.strip() for part in reason.split(" | "))
        if segment and not segment.startswith(_INTEGRITY_REASON_PREFIXES)
    ]
    return " | ".join(kept) or None


def question_to_dto(
    question: CorrectedQuestion,
    *,
    question_result_id: str | None = None,
    for_student: bool = False,
) -> QuestionResultDTO:
    """Convert a core :class:`CorrectedQuestion` into a :class:`QuestionResultDTO`.

    ``for_student`` suppresses everything integrity-related — both flags and any
    integrity segment of ``review_reason`` — and the marker's per-point verdict,
    ``matched_point_ids``. It defaults to ``False`` because the teacher console
    (``routers/teacher.py``) reads this same DTO and all three are exactly what a
    teacher is there to see, so the sanitising is per call site, never global.

    ``matched_point_ids`` is withheld because it *is* the per-point verdict:
    ``lemely/db/question_points.py`` sets each point row's ``awarded`` to
    ``point.id in matched_point_ids``, so naming the matched ids names the
    awarded points. This DTO also carries ``question_result_id``, the id the
    self-review panel renders on — shipping both would put the answer beside the
    question a student is asked to commit against, before the reveal (self-review
    spec: "If the verdict were in the payload and merely hidden in the UI, the
    entire exercise is defeated by opening devtools"). The question's *aggregate*
    ``awarded_marks`` stays: the panel sits on a screen that shows the mark, and
    the promise was only ever to withhold ``awarded`` per point.
    """
    return QuestionResultDTO(
        questionId=question.question_id,
        awardedMarks=question.awarded_marks,
        maxMarks=question.maximum_marks,
        markerSource=question.marker_source,
        confidence=question.confidence_score,
        feedback=question.feedback,
        matchedPointIds=None if for_student else (list(question.matched_point_ids) or None),
        reviewReason=(
            student_safe_review_reason(question.review_reason)
            if for_student
            else question.review_reason
        ),
        plagiarismFlagged=False if for_student else question.plagiarism_flagged,
        aiDetectionFlagged=False if for_student else question.ai_detection_flagged,
        topic=question.topic,
        questionResultId=question_result_id,
    )


def weak_area_to_dto(weak_area: CoreWeakArea) -> WeakAreaDTO:
    """Convert a core :class:`WeakArea` into a :class:`WeakAreaDTO`."""
    return WeakAreaDTO(
        topic=weak_area.topic,
        marksLost=weak_area.lost_marks,
        marksAvailable=weak_area.maximum_marks,
    )
