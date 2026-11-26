"""``GET /api/student/home``: the student Home hub and Me stats (redesign lane L1).

Gathers inputs from the services that already own them (history, XP and streak,
study plans, exam calendar, assigned quizzes, the active upload, classes, and
one new student-scoped read for teacher replies) and hands them to the pure
builders in :mod:`lemely.web.services.student_home`. Nothing here decides what
the student sees; the client's view model picks the stage moment.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends

from lemely.auth.mirror import UserMirror
from lemely.core.history import HistoryStoreProtocol, is_grade_bearing
from lemely.core.schemas import ExamMetadata
from lemely.db.class_repo import ClassService
from lemely.db.exam_calendar_repo import ExamCalendarService
from lemely.db.models.enums import Role, XpSource
from lemely.db.quiz_taking_repo import QuizTakingService
from lemely.db.session import get_sessionmaker
from lemely.db.student_home_repo import StudentHomeReads
from lemely.db.student_profile_repo import StudentProfileService
from lemely.db.study_plan_repo import SessionView, StudyPlanService
from lemely.db.upload_repo import StudentUploadRepository
from lemely.db.xp_repo import StreakState, UserZoneReader, XpBreakdown, XpService, week_bounds
from lemely.io.grade_boundaries import GradeBoundaryStore
from lemely.web.deps import (
    AuthContext,
    get_class_service,
    get_exam_calendar_service,
    get_history_store,
    get_quiz_taking_service,
    get_settings,
    get_student_profile_service,
    get_student_upload_repo,
    get_study_plan_service,
    get_user_mirror,
    get_user_zone_reader,
    get_xp_service,
    require_role,
)
from lemely.web.routers.student import _run_dto
from lemely.web.schemas_student_home import StudentHomeDTO
from lemely.web.services.student_home import REPLY_WINDOW, HomeInputs, build_home

router = APIRouter(prefix="/api/student", tags=["student-home"])

_EMPTY_STREAK = StreakState(
    current_length=0, longest_length=0, last_active_on=None, freezes_available=0
)


def _now() -> datetime:
    return datetime.now(UTC)


def _empty_breakdown() -> XpBreakdown:
    return XpBreakdown(total=0, by_source=dict.fromkeys(XpSource, 0))


def _student_uuid(user_id: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(user_id)
    except ValueError:
        return None


@lru_cache(maxsize=1)
def get_student_home_reads() -> StudentHomeReads:
    """Process-wide :class:`StudentHomeReads`; tests override it."""
    return StudentHomeReads(get_sessionmaker(get_settings()))


@router.get("/home", response_model=StudentHomeDTO)
def student_home(
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    history_store: Annotated[HistoryStoreProtocol, Depends(get_history_store)],
    mirror: Annotated[UserMirror, Depends(get_user_mirror)],
    profile_service: Annotated[StudentProfileService, Depends(get_student_profile_service)],
    xp_service: Annotated[XpService, Depends(get_xp_service)],
    zones: Annotated[UserZoneReader, Depends(get_user_zone_reader)],
    study_plans: Annotated[StudyPlanService, Depends(get_study_plan_service)],
    exam_calendar: Annotated[ExamCalendarService, Depends(get_exam_calendar_service)],
    quizzes: Annotated[QuizTakingService, Depends(get_quiz_taking_service)],
    uploads: Annotated[StudentUploadRepository, Depends(get_student_upload_repo)],
    classes: Annotated[ClassService, Depends(get_class_service)],
    reads: Annotated[StudentHomeReads, Depends(get_student_home_reads)],
) -> StudentHomeDTO:
    """Return everything the Home hub and the Me screen's stats need, in one read."""
    now = _now()
    records = history_store.load(auth.user_id).records

    store: list[GradeBoundaryStore] = []

    def boundaries_for(metadata: ExamMetadata) -> dict[str, float]:
        if not store:
            store.append(GradeBoundaryStore())
        return store[0].resolve(metadata)[0]

    student = _student_uuid(auth.user_id)
    if student is None:
        week_start, _ = week_bounds(now.date())
        inputs = HomeInputs(
            student_name="",
            records=records,
            now=now,
            local_date=now.date(),
            local_hour=now.hour,
            week_start=week_start,
            streak=_EMPTY_STREAK,
            today_xp=_empty_breakdown(),
            week_xp=_empty_breakdown(),
            week_xp_by_day={},
            sessions=[],
            calendar=None,
            assigned=[],
            active_run=None,
            teacher_replies=[],
            class_count=0,
        )
        return build_home(inputs, boundaries_for)

    local = now.astimezone(zones.zone_for(student))
    local_date = local.date()
    week_start, week_end = week_bounds(local_date)

    try:
        enrolled_codes = {e.subject_code for e in profile_service.list_enrolments(auth.user_id)}
    except ValueError:
        enrolled_codes = set()
    paper_codes = {r.metadata.subject_code for r in records if is_grade_bearing(r)}
    sessions: list[SessionView] = []
    for code in sorted(enrolled_codes | paper_codes):
        plan = study_plans.get_current(student, code, now=now)
        if plan is not None:
            sessions.extend(plan.sessions)

    user = mirror.get_by_id(student)
    run = uploads.get_active_run(user_id=auth.user_id)

    inputs = HomeInputs(
        student_name=(user.display_name or user.email) if user is not None else "",
        records=records,
        now=now,
        local_date=local_date,
        local_hour=local.hour,
        week_start=week_start,
        streak=xp_service.streak(student, now=now),
        today_xp=xp_service.xp_breakdown(student, start=local_date, end=local_date),
        week_xp=xp_service.xp_breakdown(student, start=week_start, end=week_end),
        week_xp_by_day=xp_service.xp_by_day(student, start=week_start, end=week_end),
        sessions=sessions,
        calendar=exam_calendar.calendar_for_student(student),
        assigned=quizzes.list_assigned(student),
        active_run=_run_dto(run, now=now) if run is not None else None,
        teacher_replies=reads.recent_teacher_replies(student, since=now - REPLY_WINDOW),
        class_count=len(classes.enrolled_class_ids(student)),
    )
    return build_home(inputs, boundaries_for)
