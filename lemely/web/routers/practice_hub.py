"""Practice tab endpoints (L4): recent runs and past papers.

Same ``/api/student/practice`` prefix and role gate as
:mod:`lemely.web.routers.practice`, in a separate file so the Practice-tab
lane and the practice-run lane (L3) never edit one router. The builder's
availability check is the generator's existing ``GET .../{code}/preview``,
which is reused unchanged.
"""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Query

from lemely.db.models.enums import Role
from lemely.db.practice_hub_repo import (
    RUNS_LIMIT_MAX,
    PastPaperRow,
    PastPaperUnavailableError,
    PracticeHubService,
    PracticeRun,
)
from lemely.db.practice_repo import PracticeCreated, PracticeNotFoundError
from lemely.db.session import get_sessionmaker
from lemely.web.deps import AuthContext, get_settings, require_role
from lemely.web.schemas_practice import CreatePracticeResponseDTO
from lemely.web.schemas_practice_hub import (
    CreateFromPaperRequestDTO,
    PastPaperDTO,
    PastPapersDTO,
    PracticeRunDTO,
    PracticeRunsDTO,
    PracticeRunStatus,
)

router = APIRouter(
    prefix="/api/student/practice", dependencies=[Depends(require_role(Role.student))]
)


def get_practice_hub_service() -> PracticeHubService:
    """The Practice tab service, on the process-wide session factory. Tests override this."""
    return PracticeHubService(get_sessionmaker(get_settings()))


def _run_to_dto(run: PracticeRun) -> PracticeRunDTO:
    return PracticeRunDTO(
        assignmentId=str(run.assignment_id),
        subjectCode=run.subject_code,
        title=run.title,
        topics=run.topics,
        status=cast("PracticeRunStatus", run.status),
        questionCount=run.question_count,
        answeredCount=run.answered_count,
        awardedMarks=run.awarded_marks,
        maximumMarks=run.maximum_marks,
        timeLimitMinutes=run.time_limit_minutes,
        lastActivityAt=run.last_activity_at.isoformat(),
    )


def _paper_to_dto(row: PastPaperRow) -> PastPaperDTO:
    return PastPaperDTO(
        paperId=str(row.paper_id),
        code=row.code,
        subjectCode=row.subject_code,
        paperNumber=row.paper_number,
        paperVariant=row.paper_variant,
        sessionLabel=row.session_label,
        durationMinutes=row.duration_minutes,
        totalMarks=row.total_marks,
        questionCount=row.question_count,
        awardedMarks=row.awarded_marks,
        maximumMarks=row.maximum_marks,
    )


def _created_to_dto(row: PracticeCreated) -> CreatePracticeResponseDTO:
    return CreatePracticeResponseDTO(
        assignmentId=str(row.assignment_id),
        quizId=str(row.quiz_id),
        questionCount=row.question_count,
        requestedCount=row.requested_count,
        topics=row.topics,
        reason=row.reason,
    )


@router.get("/runs", response_model=PracticeRunsDTO)
def practice_runs(
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[PracticeHubService, Depends(get_practice_hub_service)],
    limit: Annotated[int, Query(ge=1, le=RUNS_LIMIT_MAX)] = 10,
) -> PracticeRunsDTO:
    """The caller's practice sets, most recent activity first (Practice tab "Recent")."""
    try:
        runs = service.runs(auth.user_id, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return PracticeRunsDTO(runs=[_run_to_dto(run) for run in runs])


@router.get("/papers/{subject_code}", response_model=PastPapersDTO)
def past_papers(
    subject_code: str,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[PracticeHubService, Depends(get_practice_hub_service)],
) -> PastPapersDTO:
    """Past papers the caller can print for ``subject_code``, or has already done."""
    try:
        rows = service.past_papers(auth.user_id, subject_code)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return PastPapersDTO(subjectCode=subject_code, papers=[_paper_to_dto(row) for row in rows])


@router.post("/papers/{paper_id}", response_model=CreatePracticeResponseDTO, status_code=201)
def create_from_paper(
    paper_id: str,
    body: CreateFromPaperRequestDTO,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[PracticeHubService, Depends(get_practice_hub_service)],
) -> CreatePracticeResponseDTO:
    """Self-assign a set made of one past paper's servable questions (past paper sheet)."""
    try:
        created = service.create_from_paper(auth.user_id, paper_id, timed=body.timed)
    except PracticeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PastPaperUnavailableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _created_to_dto(created)


__all__ = ["get_practice_hub_service", "router"]
