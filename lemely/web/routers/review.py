"""Review queue endpoints (``/api/teacher/review/*``, T-07/T-08, P3.4).

Every route is gated to the teacher/school_admin/platform_admin staff triple
(mirroring ``teacher.py``/``classes.py``); row-level ownership is then
enforced inside :class:`~lemely.db.review_repo.ReviewService`, which scopes
every read/mutation to the caller's own visible students (the same
roster-union rule as ``teacher._visible_students``, D3.1). ``platform_admin``
sees no classes, so it sees no review items either — no super-role bypass.

A new router file rather than extending ``teacher.py`` (already ~1400 LOC):
the review queue is its own coherent surface with its own service, DTOs, and
error mapping, and nothing here needs anything ``teacher.py`` privately
defines.
"""

from __future__ import annotations

import uuid
from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException

from lemely.db.models.enums import Role
from lemely.db.review_repo import (
    ReviewAlreadyClosedError,
    ReviewError,
    ReviewItemDetail,
    ReviewNotFoundError,
    ReviewOwnershipError,
    ReviewQueueRow,
    ReviewService,
    ReviewValidationError,
)
from lemely.web.deps import AuthContext, get_review_service, require_role
from lemely.web.schemas_review import (
    BulkApproveRequestDTO,
    BulkApproveResponseDTO,
    BulkApproveSkipDTO,
    DismissReviewRequestDTO,
    ResolveReviewRequestDTO,
    ReviewBreakdownDTO,
    ReviewItemDetailDTO,
    ReviewQueueItemDTO,
    ReviewQueueListDTO,
)

# Mirrors teacher.py's/classes.py's staff triple.
_STAFF_ROLES = (Role.teacher, Role.school_admin, Role.platform_admin)

router = APIRouter(
    prefix="/api/teacher/review", dependencies=[Depends(require_role(*_STAFF_ROLES))]
)


# ---------------------------------------------------------------------------
# Error mapping.
# ---------------------------------------------------------------------------


def _raise_for(exc: ReviewError) -> NoReturn:
    """Map a :class:`ReviewError` subclass to the matching :class:`HTTPException`."""
    if isinstance(exc, ReviewNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, ReviewOwnershipError):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if isinstance(exc, ReviewAlreadyClosedError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, ReviewValidationError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise HTTPException(status_code=409, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# DTO conversion.
# ---------------------------------------------------------------------------


def _row_to_dto(row: ReviewQueueRow) -> ReviewQueueItemDTO:
    return ReviewQueueItemDTO(
        itemId=str(row.item_id),
        attemptId=str(row.attempt_id),
        questionResultId=str(row.question_result_id) if row.question_result_id else None,
        studentId=str(row.student_id),
        studentDisplayName=row.student_display_name,
        classId=str(row.class_id),
        className=row.class_name,
        subjectCode=row.subject_code,
        paperNumber=row.paper_number,
        paperVariant=row.paper_variant,
        sessionMonth=row.session_month,
        sessionYear=row.session_year,
        questionId=row.question_id,
        reason=row.reason.value,
        status=row.status.value,
        createdAt=row.created_at.isoformat(),
        waitingHours=round(row.waiting_hours, 2),
        aiAwardedMarks=row.ai_awarded_marks,
        maximumMarks=row.maximum_marks,
        confidenceScore=row.confidence_score,
    )


def _breakdown_to_dto(breakdown: dict[str, object] | None) -> ReviewBreakdownDTO | None:
    if breakdown is None:
        return None
    return ReviewBreakdownDTO.model_validate(breakdown)


def _detail_to_dto(detail: ReviewItemDetail) -> ReviewItemDetailDTO:
    row = detail.row
    return ReviewItemDetailDTO(
        itemId=str(row.item_id),
        attemptId=str(row.attempt_id),
        questionResultId=str(row.question_result_id) if row.question_result_id else None,
        studentId=str(row.student_id),
        studentDisplayName=row.student_display_name,
        classId=str(row.class_id),
        className=row.class_name,
        subjectCode=row.subject_code,
        paperNumber=row.paper_number,
        paperVariant=row.paper_variant,
        sessionMonth=row.session_month,
        sessionYear=row.session_year,
        questionId=row.question_id,
        reason=row.reason.value,
        status=row.status.value,
        createdAt=row.created_at.isoformat(),
        waitingHours=round(row.waiting_hours, 2),
        aiAwardedMarks=row.ai_awarded_marks,
        maximumMarks=row.maximum_marks,
        confidenceScore=row.confidence_score,
        studentAnswer=detail.student_answer,
        expectedAnswer=detail.expected_answer,
        topic=detail.topic,
        matchedPointIds=detail.matched_point_ids,
        feedback=detail.feedback,
        markerSource=detail.marker_source,
        reviewReason=detail.review_reason,
        isOverridden=detail.is_overridden,
        teacherAwardedMarks=detail.teacher_awarded_marks,
        teacherNote=detail.teacher_note,
        teacherBreakdown=_breakdown_to_dto(detail.teacher_breakdown),
        overriddenBy=str(detail.overridden_by) if detail.overridden_by else None,
        overriddenAt=detail.overridden_at.isoformat() if detail.overridden_at else None,
        resolutionNote=detail.resolution_note,
        resolvedBy=str(detail.resolved_by) if detail.resolved_by else None,
        resolvedAt=detail.resolved_at.isoformat() if detail.resolved_at else None,
    )


# ---------------------------------------------------------------------------
# Routes.
# ---------------------------------------------------------------------------


@router.get("", response_model=ReviewQueueListDTO)
def list_review_queue(
    auth: Annotated[AuthContext, Depends(require_role(*_STAFF_ROLES))],
    service: Annotated[ReviewService, Depends(get_review_service)],
    class_id: str | None = None,
    reason: str | None = None,
    min_age_hours: float | None = None,
) -> ReviewQueueListDTO:
    """T-07: every open review item across the caller's own students.

    Filters by class, reason, and minimum waiting age. A malformed
    (non-UUID) ``class_id`` is a clean 422, never a 500.
    """
    try:
        rows = service.list_queue(
            auth.user_id,
            auth.role,
            class_id=class_id,
            reason=reason,
            min_age_hours=min_age_hours,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ReviewQueueListDTO(items=[_row_to_dto(row) for row in rows])


@router.get("/{item_id}", response_model=ReviewItemDetailDTO)
def get_review_item(
    item_id: str,
    auth: Annotated[AuthContext, Depends(require_role(*_STAFF_ROLES))],
    service: Annotated[ReviewService, Depends(get_review_service)],
) -> ReviewItemDetailDTO:
    """T-08: full detail for one review item.

    An item outside the caller's scope is a 403; an id that maps to no item
    anywhere is a 404; a malformed (non-UUID) id is a clean 422 — the same
    split ``teacher_student_detail`` documents at length.
    """
    try:
        detail = service.get_item(auth.user_id, auth.role, item_id)
    except (ReviewNotFoundError, ReviewOwnershipError) as exc:
        _raise_for(exc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _detail_to_dto(detail)


@router.post("/bulk-approve", response_model=BulkApproveResponseDTO)
def bulk_approve_review_items(
    body: BulkApproveRequestDTO,
    auth: Annotated[AuthContext, Depends(require_role(*_STAFF_ROLES))],
    service: Annotated[ReviewService, Depends(get_review_service)],
) -> BulkApproveResponseDTO:
    """T-07 bulk-approve: accept-as-is every id in scope; skip-and-report the rest.

    A malformed (non-UUID) id anywhere in ``itemIds`` is a clean 422, never a
    500 — checked up front, before any item is touched. See
    ``ReviewService.bulk_approve``'s docstring for why the *scope* check
    (not_found/forbidden/already_closed) is skip-and-report rather than
    all-or-nothing; malformed input is a different failure mode and is
    rejected wholesale.
    """
    try:
        item_ids = [uuid.UUID(raw) for raw in body.itemIds]
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result = service.bulk_approve(auth.user_id, auth.role, item_ids)
    return BulkApproveResponseDTO(
        approved=[str(item_id) for item_id in result.approved],
        skipped=[
            BulkApproveSkipDTO(itemId=str(skip.item_id), reason=skip.reason)
            for skip in result.skipped
        ],
    )


@router.post("/{item_id}/resolve", response_model=ReviewQueueItemDTO)
def resolve_review_item(
    item_id: str,
    body: ResolveReviewRequestDTO,
    auth: Annotated[AuthContext, Depends(require_role(*_STAFF_ROLES))],
    service: Annotated[ReviewService, Depends(get_review_service)],
) -> ReviewQueueItemDTO:
    """T-08: accept the AI mark as-is, or override it with a note to the student.

    Authz mirrors ``get_review_item``. An already-resolved/dismissed item is a
    409; an out-of-range ``overrideMarks`` (or one supplied for an item with no
    underlying question result) is a 422.
    """
    breakdown = body.breakdown.model_dump(exclude_none=True) if body.breakdown is not None else None
    try:
        row = service.resolve(
            auth.user_id,
            auth.role,
            item_id,
            override_marks=body.overrideMarks,
            breakdown=breakdown,
            note=body.note,
        )
    except (
        ReviewNotFoundError,
        ReviewOwnershipError,
        ReviewAlreadyClosedError,
        ReviewValidationError,
    ) as exc:
        _raise_for(exc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _row_to_dto(row)


@router.post("/{item_id}/dismiss", response_model=ReviewQueueItemDTO)
def dismiss_review_item(
    item_id: str,
    body: DismissReviewRequestDTO,
    auth: Annotated[AuthContext, Depends(require_role(*_STAFF_ROLES))],
    service: Annotated[ReviewService, Depends(get_review_service)],
) -> ReviewQueueItemDTO:
    """T-08: dismiss an integrity flag. No student-visible record survives this.

    Authz mirrors ``get_review_item``. An already-resolved/dismissed item is a
    409; dismissing a non-integrity item (``low_confidence``/``manual``) is a
    422 — see ``ReviewService.dismiss``.
    """
    try:
        row = service.dismiss(auth.user_id, auth.role, item_id, note=body.note)
    except (
        ReviewNotFoundError,
        ReviewOwnershipError,
        ReviewAlreadyClosedError,
        ReviewValidationError,
    ) as exc:
        _raise_for(exc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _row_to_dto(row)


__all__ = ["router"]
