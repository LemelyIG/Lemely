"""API DTOs for the review-queue endpoints (``/api/teacher/review/*``, P3.4).

T-07 (queue list) / T-08 (item detail + remark). Field names are camelCase to
match the frontend contract, mirroring the other ``schemas_*.py`` modules.
Converters live in :mod:`lemely.web.routers.review`.
"""

from __future__ import annotations

#: Re-exported from :data:`lemely.core.schemas.PointVerdictWire`, the same
#: ``Literal`` :attr:`~lemely.core.schemas.PointVerdict.verdict` is annotated
#: with; mirrors ``lemely.db.review_repo.PointVerdictWire``, the other
#: re-export of the same alias. The wire boundary is where this ``Literal``
#: is load-bearing — pyright, not mypy, is what catches a plain ``str``
#: reaching it (see ``ReviewItemPointDTO.verdict``'s docstring).
from lemely.core.schemas import PointVerdictWire as PointVerdictWire
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
    """One T-07 queue row: who/what, paper identity, question, reason, age.

    ``source`` says which half of the queue this row came from, so the client
    never has to infer it from which ids are populated:

    * ``"student_attempt"`` — a student submission. ``attemptId`` and the
      ``studentId``/``classId``/``className`` trio are set; ``paperId`` is null.
    * ``"console_paper"`` — a scan the teacher uploaded through the grading
      console. ``paperId`` is set and ``attemptId`` is null. A console upload
      is never attributed to a student (D1.12), so the student/class fields are
      **null rather than filled in with a guess**, and ``studentDisplayName``
      carries the paper's own label — the same one its console card shows.
    """

    itemId: str
    source: str
    attemptId: str | None
    paperId: str | None
    questionResultId: str | None
    studentId: str | None
    studentDisplayName: str
    classId: str | None
    className: str | None
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
    """Response for ``GET /api/teacher/review``.

    ``nextCursor`` is an opaque, urlsafe-base64 keyset token (``created_at``
    + ``itemId``) the client echoes back as the ``cursor`` query param to
    fetch the next page; ``null`` once the caller's whole queue fits on this
    page.

    ``total`` is the count of items matching the request's filters
    (``class_id``/``reason``/``min_age_hours``), ignoring ``limit``/``cursor``
    — the same tenant scope as ``items`` (C3d).
    """

    items: list[ReviewQueueItemDTO]
    nextCursor: str | None = None
    total: int


class ReviewItemPointDTO(ApiModel):
    """One mark point's self-review state.

    For a ``student_evidence_unjudged`` item (S2 part2+3 final review, I-2):
    without this, a teacher opening such an item has no way to see the
    student's own claim or evidence — the sentence the queue row exists to
    have them adjudicate.

    ``verdict``/``evidenceSpan``/``ecfApplied`` are I6/I7 (US-013)'s marker
    verdict, populated regardless of whether the student ever self-marked
    this point. ``verdict`` is typed as the narrowed ``PointVerdictWire``, not
    ``str``, because **the pydantic mypy plugin checks constructor keyword
    arity, not field types** — mypy cannot see a plain ``str`` reaching a
    ``Literal`` field here, only pyright can. ``lemely.db.review_repo``
    already narrowed the DB's loose ``str | None`` before this DTO is built,
    so this field's ``Literal`` is never violated by a well-formed caller;
    pyright is what makes that provable at every call site rather than
    merely true today.

    ``rationale`` is the marker's own per-point reasoning. Unlike ``verdict``,
    it is present on both the verdict and legacy marking paths, so it reaches
    this DTO today, with ``equivalence_gate`` off.
    """

    markPointId: str
    pointText: str
    awarded: bool
    studentSelfmark: bool | None
    studentEvidence: str | None
    evidenceVerdict: str | None
    verdict: PointVerdictWire | None
    evidenceSpan: str
    ecfApplied: bool
    rationale: str | None


class ReviewItemDetailDTO(ApiModel):
    """Response for ``GET /api/teacher/review/{item_id}`` (T-08).

    Extends :class:`ReviewQueueItemDTO`'s fields with the question content,
    AI marking evidence, and any recorded teacher override. There is still no
    persisted mark-scheme extract on
    :class:`~lemely.db.models.attempts.QuestionResult` (see its docstring) —
    that part of the gap is real and stays real, so a future screen must not
    invent scheme-prose precision this backend cannot provide. A scan crop is
    a different matter: one is available whenever ``hasSourceBox`` is
    ``true``, served on demand by ``GET
    /api/teacher/review/{item_id}/crop``. It is QUESTION-level — where the
    answer was read from on the page — never per mark point, so it must not
    be read as showing which pixels justify any one awarded mark.
    Where ``points`` (``ReviewItemPointDTO``) carries a real per-point
    ``verdict`` and quoted evidence span (I6, US-013 — an attempt-backed row
    with a mark scheme, once the marker actually returns verdicts), it is
    strictly richer marking evidence than a bare matched-point identifier.
    That is not every row: on a ``"console_paper"`` row ``points`` is always
    ``[]`` (there is no ``question_result_points`` row for a console item —
    see below) and on a no-scheme question (a quiz) it is also ``[]``; on
    either, ``matchedPointIds`` is the only marking evidence this backend has.
    On a legacy row ``points`` still carries each point's snapshotted scheme
    text and ``awarded`` flag — richer than a bare identifier — but no
    ``verdict``, so the withheld/unverifiable distinction is absent.

    On a ``"console_paper"`` row the marking evidence is read from the paper's
    stored report, but every **override** field (``isOverridden``,
    ``teacherAwardedMarks``, ``teacherNote``, ``teacherBreakdown``,
    ``overriddenBy``, ``overriddenAt``) is always empty: a console paper has no
    ``QuestionResult``, which is the only place a corrected mark is persisted.
    Resolving such an item with ``overrideMarks`` is a 422, not a silent
    no-op — see ``ReviewService.resolve``.
    """

    itemId: str
    source: str
    attemptId: str | None
    paperId: str | None
    questionResultId: str | None
    studentId: str | None
    studentDisplayName: str
    classId: str | None
    className: str | None
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
    points: list[ReviewItemPointDTO]
    """Empty for a ``"console_paper"`` row — see ``ReviewItemDetail.points``."""
    hasSourceBox: bool = False
    """True when a scan crop is available for this question — see
    ``ReviewItemDetail.has_source_box``. Always ``GET
    /api/teacher/review/{item_id}/crop`` returns an image when this is
    ``true``; the client never receives the coordinates themselves."""


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
    "ReviewItemPointDTO",
    "ReviewQueueItemDTO",
    "ReviewQueueListDTO",
]
