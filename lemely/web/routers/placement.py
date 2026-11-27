"""Placement-test endpoints (``/api/student/placement/*``, P4.4 chunk B-4, D4.6).

A new router file, not an extension of ``lemely.web.routers.quiz`` — the
placement surface is thin (three routes) but the wiring it needs
(:class:`~lemely.db.placement_repo.PlacementService`, its own DTOs) is
distinct enough to earn its own coherent file, mirroring the precedent
``lemely.web.routers.quiz`` itself set by not growing ``student.py``/
``teacher.py`` further.

**Take/save-answer/submit are not here.** They are the existing
``/api/student/quizzes/{assignment_id}`` routes
(``lemely.web.routers.quiz.student_router``), reused verbatim — D4.6 §4's
entire point. This router only offers availability, self-assigns a test, and
reads its result.
"""

from __future__ import annotations

from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException

from lemely.db.models.enums import Role
from lemely.db.placement_repo import (
    PlacementAvailability,
    PlacementCreated,
    PlacementError,
    PlacementNotFoundError,
    PlacementOwnershipError,
    PlacementResultRow,
    PlacementService,
    PlacementUnavailableError,
)
from lemely.web.deps import AuthContext, get_placement_service, require_role
from lemely.web.schemas_placement import (
    CreatePlacementRequestDTO,
    CreatePlacementResponseDTO,
    PlacementAvailabilityDTO,
    PlacementQuestionResultDTO,
    PlacementResultDTO,
    PlacementTopicBreakdownDTO,
)

router = APIRouter(
    prefix="/api/student/placement", dependencies=[Depends(require_role(Role.student))]
)


def _raise_for(exc: PlacementError) -> NoReturn:
    """Map a :class:`PlacementError` subclass to the matching :class:`HTTPException`."""
    if isinstance(exc, PlacementNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, PlacementOwnershipError):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    raise HTTPException(status_code=409, detail=str(exc)) from exc  # pragma: no cover


def _availability_to_dto(row: PlacementAvailability) -> PlacementAvailabilityDTO:
    return PlacementAvailabilityDTO(
        available=row.available,
        reason=row.reason,
        questionCount=row.question_count,
        topicCount=row.topic_count,
        estimatedMinutes=row.estimated_minutes,
    )


def _created_to_dto(row: PlacementCreated) -> CreatePlacementResponseDTO:
    return CreatePlacementResponseDTO(
        assignmentId=str(row.assignment_id),
        quizId=str(row.quiz_id),
        questionCount=row.question_count,
        topicCount=row.topic_count,
        estimatedMinutes=row.estimated_minutes,
    )


def _result_to_dto(row: PlacementResultRow) -> PlacementResultDTO:
    return PlacementResultDTO(
        assignmentId=str(row.assignment_id),
        quizId=str(row.quiz_id),
        subjectCode=row.subject_code,
        marked=row.marked,
        awardedMarks=row.awarded_marks,
        maximumMarks=row.maximum_marks,
        questions=[
            PlacementQuestionResultDTO(
                questionRef=q.question_ref,
                topic=q.topic,
                awardedMarks=q.awarded_marks,
                maximumMarks=q.maximum_marks,
            )
            for q in row.questions
        ],
        topicBreakdown=[
            PlacementTopicBreakdownDTO(
                topic=t.topic,
                lostMarks=t.lost_marks,
                maximumMarks=t.maximum_marks,
                accuracy=t.accuracy,
            )
            for t in row.topic_breakdown
        ],
        spansMultipleBands=row.spans_multiple_bands,
    )


@router.get("/{subject_code}/availability", response_model=PlacementAvailabilityDTO)
def placement_availability(
    subject_code: str,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[PlacementService, Depends(get_placement_service)],
) -> PlacementAvailabilityDTO:
    """S-03: whether a ~15-minute placement test can be assembled for this subject."""
    try:
        result = service.availability(auth.user_id, subject_code)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _availability_to_dto(result)


@router.post("", response_model=CreatePlacementResponseDTO, status_code=201)
def create_placement(
    body: CreatePlacementRequestDTO,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[PlacementService, Depends(get_placement_service)],
) -> CreatePlacementResponseDTO:
    """Assemble and self-assign a placement test (S-03 → S-04).

    409, carrying the identical payload ``GET .../availability`` would have
    returned, when assembly does not clear the viability floor.
    """
    try:
        result = service.create(auth.user_id, body.subjectCode)
    except PlacementUnavailableError as exc:
        raise HTTPException(
            status_code=409, detail=_availability_to_dto(exc.availability).model_dump()
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _created_to_dto(result)


@router.get("/{assignment_id}/result", response_model=PlacementResultDTO)
def placement_result(
    assignment_id: str,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[PlacementService, Depends(get_placement_service)],
) -> PlacementResultDTO:
    """S-05: not a grade — a starting picture.

    404 when the assignment does not exist anywhere; 403 when it exists but
    is not the caller's — never data (D4.6 §4's existence-oracle trade-off).
    """
    try:
        result = service.result(auth.user_id, assignment_id)
    except (PlacementNotFoundError, PlacementOwnershipError) as exc:
        _raise_for(exc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _result_to_dto(result)


__all__ = ["router"]
