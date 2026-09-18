"""Student self-review endpoints (spec 2026-09-17 self-review, "API").

A new router file, mirroring :mod:`lemely.web.routers.student_announcements`:
thin, its own DTOs, no growth of ``student.py``. Every rule lives in
:class:`~lemely.db.self_review_repo.SelfReviewService`; this module only
maps its errors to status codes and its views to DTOs.

Identity is **always** ``auth.user_id``. Cross-student access is a 404 with
a fixed body, never a 403 — matching every other student route, so the
route is not an existence oracle for another student's attempts.
"""

from __future__ import annotations

from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException

from lemely.db.models.enums import Role
from lemely.db.self_review_repo import (
    PendingSelfReview,
    PointVerdict,
    RevealedSelfReview,
    SelfReviewAlreadySubmittedError,
    SelfReviewError,
    SelfReviewNotFoundError,
    SelfReviewService,
    SelfReviewValidationError,
)
from lemely.web.deps import AuthContext, get_self_review_service, require_role
from lemely.web.schemas_student_self_review import (
    SelfReviewPendingDTO,
    SelfReviewPendingPointDTO,
    SelfReviewRevealedDTO,
    SelfReviewRevealedPointDTO,
    SelfReviewSubmissionDTO,
)

router = APIRouter(prefix="/api/student/attempts")

_SELF_REVIEW_PATH = "/{attempt_id}/questions/{question_result_id}/self-review"


def _raise_for(exc: SelfReviewError) -> NoReturn:
    """Map a :class:`SelfReviewError` to its status. The 404 body is fixed."""
    if isinstance(exc, SelfReviewNotFoundError):
        raise HTTPException(status_code=404, detail="No such question") from exc
    if isinstance(exc, SelfReviewAlreadySubmittedError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, SelfReviewValidationError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise HTTPException(status_code=409, detail=str(exc)) from exc


def _pending_dto(view: PendingSelfReview) -> SelfReviewPendingDTO:
    return SelfReviewPendingDTO(
        state=view.state,
        attemptId=str(view.attempt_id),
        questionResultId=str(view.question_result_id),
        questionId=view.question_id,
        maxMarks=view.maximum_marks,
        evidenceRequired=view.evidence_required,
        points=[
            SelfReviewPendingPointDTO(
                markPointId=p.mark_point_id,
                ordinal=p.ordinal,
                markType=p.mark_type,
                tariff=p.tariff,
                pointText=p.point_text,
                isAlternative=p.is_alternative,
                isOptional=p.is_optional,
                groupKey=p.group_key,
                groupMaxMarks=p.group_max_marks,
            )
            for p in view.points
        ],
    )


def _revealed_dto(view: RevealedSelfReview) -> SelfReviewRevealedDTO:
    return SelfReviewRevealedDTO(
        state=view.state,
        attemptId=str(view.attempt_id),
        questionResultId=str(view.question_result_id),
        questionId=view.question_id,
        maxMarks=view.maximum_marks,
        evidenceRequired=view.evidence_required,
        aiMarks=view.ai_marks,
        effectiveMarks=view.effective_marks,
        studentMarks=view.student_marks,
        teacherSettled=view.teacher_settled,
        pendingTeacher=view.pending_teacher,
        submittedAt=view.submitted_at,
        points=[
            SelfReviewRevealedPointDTO(
                markPointId=p.mark_point_id,
                ordinal=p.ordinal,
                markType=p.mark_type,
                tariff=p.tariff,
                pointText=p.point_text,
                isAlternative=p.is_alternative,
                isOptional=p.is_optional,
                groupKey=p.group_key,
                groupMaxMarks=p.group_max_marks,
                awarded=p.awarded,
                studentSelfmark=p.student_selfmark,
                studentEvidence=p.student_evidence,
                evidenceVerdict=p.evidence_verdict,
                markChanged=p.mark_changed,
                absorbedByGroup=p.absorbed_by_group,
                judgeReason=p.judge_reason,
            )
            for p in view.points
        ],
    )


@router.get(_SELF_REVIEW_PATH, response_model=SelfReviewPendingDTO | SelfReviewRevealedDTO)
def get_self_review(
    attempt_id: str,
    question_result_id: str,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[SelfReviewService, Depends(get_self_review_service)],
) -> SelfReviewPendingDTO | SelfReviewRevealedDTO:
    """The self-review state of one of the caller's questions.

    Before submission the payload is :class:`SelfReviewPendingDTO`, which
    carries no verdict at any depth. After it, :class:`SelfReviewRevealedDTO`.
    """
    try:
        view = service.get(auth.user_id, attempt_id, question_result_id)
    except SelfReviewError as exc:
        _raise_for(exc)
    if isinstance(view, PendingSelfReview):
        return _pending_dto(view)
    return _revealed_dto(view)


@router.post(_SELF_REVIEW_PATH, response_model=SelfReviewRevealedDTO)
def submit_self_review(
    attempt_id: str,
    question_result_id: str,
    payload: SelfReviewSubmissionDTO,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[SelfReviewService, Depends(get_self_review_service)],
) -> SelfReviewRevealedDTO:
    """Record the caller's one self-mark pass and reveal the marker's verdict.

    409 once a pass exists; 422 unless every point carries exactly one verdict.
    """
    try:
        view = service.submit(
            auth.user_id,
            attempt_id,
            question_result_id,
            [
                PointVerdict(mark_point_id=p.markPointId, earned=p.earned, evidence=p.evidence)
                for p in payload.points
            ],
        )
    except SelfReviewError as exc:
        _raise_for(exc)
    return _revealed_dto(view)


__all__ = ["router"]
