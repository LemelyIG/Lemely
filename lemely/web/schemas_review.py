"""API DTOs for the review-queue endpoints (``/api/teacher/review/*``, P3.4).

T-07 (queue list) / T-08 (item detail + remark). Field names are camelCase to
match the frontend contract, mirroring the other ``schemas_*.py`` modules.
Converters live in :mod:`lemely.web.routers.review`.
"""

from __future__ import annotations

from lemely.web.schemas import ApiModel


class ReviewBreakdownDTO(ApiModel):
    """A teacher-supplied method/accuracy breakdown, recorded verbatim.

    Deliberately not derived from the mark scheme's M/A/B point types — those
    live in the parsed mark scheme, not on the persisted
    :class:`~lemely.db.models.attempts.QuestionResult` row, so there is
    nothing to compute this from (UI-spec §1.4: never invent precision). Every
    field is what the teacher typed, nothing more.
    """

    methodMarks: int | None = None
    accuracyMarks: int | None = None
    otherMarks: int | None = None
    notes: str | None = None


class ReviewQueueItemDTO(ApiModel):
    """One T-07 queue row: student, paper identity, question, reason, age."""

    itemId: str
    attemptId: str
    questionResultId: str | None
    studentId: str
    studentDisplayName: str
    classId: str
    className: str
    subjectCode: str | None
    paperNumber: int | None
    paperVariant: int | None
    sessionMonth: str | None
    sessionYear: int | None
    questionId: str | None
    reason: str
    status: str
    createdAt: str
    waitingHours: float
    aiAwardedMarks: int | None
    maximumMarks: int | None
    confidenceScore: float | None


class ReviewQueueListDTO(ApiModel):
    """Response for ``GET /api/teacher/review``."""

    items: list[ReviewQueueItemDTO]


class ReviewItemDetailDTO(ApiModel):
    """Response for ``GET /api/teacher/review/{item_id}`` (T-08).

    Extends :class:`ReviewQueueItemDTO`'s fields with the question content,
    AI marking evidence, and any recorded teacher override. There is no
    persisted mark-scheme extract or scan-crop image on
    :class:`~lemely.db.models.attempts.QuestionResult` (see its docstring) —
    ``matchedPointIds`` and ``studentAnswer`` are the honest substitutes this
    backend can actually provide.
    """

    itemId: str
    attemptId: str
    questionResultId: str | None
    studentId: str
    studentDisplayName: str
    classId: str
    className: str
    subjectCode: str | None
    paperNumber: int | None
    paperVariant: int | None
    sessionMonth: str | None
    sessionYear: int | None
    questionId: str | None
    reason: str
    status: str
    createdAt: str
    waitingHours: float
    aiAwardedMarks: int | None
    maximumMarks: int | None
    confidenceScore: float | None
    studentAnswer: str | None
    expectedAnswer: str | None
    topic: str | None
    matchedPointIds: list[str]
    feedback: str | None
    markerSource: str | None
    reviewReason: str | None
    isOverridden: bool
    teacherAwardedMarks: int | None
    teacherNote: str | None
    teacherBreakdown: ReviewBreakdownDTO | None
    overriddenBy: str | None
    overriddenAt: str | None
    resolutionNote: str | None
    resolvedBy: str | None
    resolvedAt: str | None


class ResolveReviewRequestDTO(ApiModel):
    """Resolve one review item: accept as-is, or override the mark.

    ``overrideMarks`` omitted (or ``None``) accepts the AI mark unchanged.
    Supplying it records a teacher correction — see
    ``ReviewService.resolve``'s docstring for the full contract.
    """

    overrideMarks: int | None = None
    breakdown: ReviewBreakdownDTO | None = None
    note: str | None = None


class DismissReviewRequestDTO(ApiModel):
    """Dismiss an integrity flag. ``note`` is an internal record only."""

    note: str | None = None


class BulkApproveRequestDTO(ApiModel):
    """Accept-as-is every id in ``itemIds`` that the caller may access.

    ``itemIds`` are plain strings (mirroring every other id field in this
    codebase's DTOs, e.g. ``EnrollStudentRequestDTO.studentId``) — the router
    parses each into a UUID, 422-ing on the first malformed one.
    """

    itemIds: list[str]


class BulkApproveSkipDTO(ApiModel):
    """One id the bulk-approve call declined to touch, and why."""

    itemId: str
    reason: str


class BulkApproveResponseDTO(ApiModel):
    """Skip-and-report outcome of ``POST /api/teacher/review/bulk-approve``."""

    approved: list[str]
    skipped: list[BulkApproveSkipDTO]


__all__ = [
    "BulkApproveRequestDTO",
    "BulkApproveResponseDTO",
    "BulkApproveSkipDTO",
    "DismissReviewRequestDTO",
    "ResolveReviewRequestDTO",
    "ReviewBreakdownDTO",
    "ReviewItemDetailDTO",
    "ReviewQueueItemDTO",
    "ReviewQueueListDTO",
]
