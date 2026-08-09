"""Persisted adaptive study-plan endpoints (``/api/student/study-plan/*``, P4.7 chunk C).

A new router file, mirroring ``lemely.web.routers.placement`` and
``lemely.web.routers.flashcards``: thin, its own DTOs, no growth of
``student.py``. This is the **only** study-plan surface: the legacy
``GET``/``POST /api/student/plan`` routes in ``lemely.web.routers.student``
were stateless and unpersisted, and P4.10 chunk D deleted them once the
frontend had moved here (D4.22).

**Student-only and owner-scoped on every read and write**, via the
router-level ``require_role(Role.student)`` dependency — a study plan is
private study material with no teacher-visibility story in this phase,
mirroring ``flashcards.py``'s identical choice.

**Another student's session id is a 404 here, not a 403** — the service
docstring (``lemely.db.study_plan_repo``) already commits to this, per
D4.11's precedent: a study plan is private study material for exactly one
student, so a 403 would be an existence oracle over it for anyone willing to
enumerate ids. Both :class:`~lemely.db.study_plan_repo.StudyPlanNotFoundError`
and :class:`~lemely.db.study_plan_repo.StudyPlanOwnershipError` are still
raised, still typed, and still tested; only the HTTP rendering is
flattened, exactly as ``flashcards.py``'s ``_raise_for`` already does for its
own deck/card ids.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException

from lemely.db.models.enums import Role
from lemely.db.study_plan_repo import (
    StudyPlanError,
    StudyPlanNotFoundError,
    StudyPlanOwnershipError,
    StudyPlanService,
)
from lemely.web.deps import AuthContext, get_study_plan_service, require_role
from lemely.web.schemas_study_plan import (
    CreateStudyPlanRequestDTO,
    CurrentStudyPlanDTO,
    StudyPlanSessionDTO,
    StudyPlanWeekDTO,
)

if TYPE_CHECKING:
    from lemely.db.study_plan_repo import PlanView, SessionView

router = APIRouter(
    prefix="/api/student/study-plan", dependencies=[Depends(require_role(Role.student))]
)


def _raise_for(exc: StudyPlanError) -> NoReturn:
    """Map a :class:`StudyPlanError` subclass to the matching :class:`HTTPException`.

    Both :class:`StudyPlanNotFoundError` and :class:`StudyPlanOwnershipError`
    become 404 with a byte-identical body — see this module's docstring for
    why the ownership case is not rendered as 403.
    """
    if isinstance(exc, StudyPlanNotFoundError | StudyPlanOwnershipError):
        raise HTTPException(status_code=404, detail="No such study-plan session") from exc
    raise HTTPException(status_code=422, detail=str(exc)) from exc  # pragma: no cover


def _session_to_dto(session: SessionView) -> StudyPlanSessionDTO:
    return StudyPlanSessionDTO(
        id=str(session.id),
        date=session.date,
        topic=session.topic,
        activityType=session.activity_type.value,
        durationMinutes=session.duration_minutes,
        focus=session.focus,
        completedAt=session.completed_at,
    )


def _plan_to_dto(plan: PlanView) -> StudyPlanWeekDTO:
    return StudyPlanWeekDTO(
        id=str(plan.id),
        subjectCode=plan.subject_code,
        weekStart=plan.week_start,
        weeklyHours=plan.weekly_hours,
        available=plan.available,
        reason=plan.reason,
        generatedAt=plan.generated_at,
        sessions=[_session_to_dto(s) for s in plan.sessions],
    )


@router.get("/{subject_code}", response_model=CurrentStudyPlanDTO)
def get_current_study_plan(
    subject_code: str,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[StudyPlanService, Depends(get_study_plan_service)],
) -> CurrentStudyPlanDTO:
    """This week's plan for the caller, or the honest "not generated yet" state.

    See :class:`~lemely.web.schemas_study_plan.CurrentStudyPlanDTO` for the
    three distinguishable wire states this route must never collapse. Never
    a 404 — "no plan yet" is a real, successful response, not an error.
    """
    plan = service.get_current(auth.user_id, subject_code)
    if plan is None:
        return CurrentStudyPlanDTO(generated=False, plan=None)
    return CurrentStudyPlanDTO(generated=True, plan=_plan_to_dto(plan))


@router.post("", response_model=StudyPlanWeekDTO, status_code=201)
def create_study_plan(
    body: CreateStudyPlanRequestDTO,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[StudyPlanService, Depends(get_study_plan_service)],
) -> StudyPlanWeekDTO:
    """S-24's "Rebuild this week's plan" control.

    The caller is always ``auth.user_id`` — never a caller-supplied id, the
    IDOR rule this codebase enforces everywhere. ``StudyPlanService.generate``
    already supersedes rather than mutates any existing plan for the same
    (student, subject, ISO week), so a second call here regenerates cleanly
    with no extra logic needed at this layer.
    """
    plan = service.generate(auth.user_id, body.subjectCode)
    return _plan_to_dto(plan)


@router.post("/sessions/{session_id}/complete", response_model=StudyPlanSessionDTO)
def complete_study_plan_session(
    session_id: str,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[StudyPlanService, Depends(get_study_plan_service)],
) -> StudyPlanSessionDTO:
    """Mark one of the caller's own sessions complete.

    Idempotent — see the service docstring. A malformed (non-UUID)
    ``session_id`` raises ``ValueError`` from the service's ``_as_uuid`` and
    is mapped to 422, not a 500; an unknown or another student's session id
    is a 404 with the identical body (see this module's docstring).
    """
    try:
        session = service.complete_session(auth.user_id, session_id)
    except StudyPlanError as exc:
        _raise_for(exc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _session_to_dto(session)


__all__ = ["router"]
