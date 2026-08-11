"""Student exam-calendar endpoint (``/api/student/exam-calendar``, P5.5 chunk C).

A thin student-role-only router of its own, mirroring
:mod:`lemely.web.routers.leaderboard`, :mod:`lemely.web.routers.friends` and
:mod:`lemely.web.routers.student_announcements`. It holds no calendar logic —
audience, session matching and the tri-state availability all belong to
:class:`~lemely.db.exam_calendar_repo.ExamCalendarService`.

**There is no ingestion route here, deliberately.** Loading an official
timetable is an operator act performed against a published document, not a
request any authenticated user makes, and exposing it over HTTP would put the
one write path capable of putting a wrong exam date in front of every student
behind a role check. Ingestion stays on the service (D5.8).

Identity is always ``auth.user_id``; no caller-supplied user id exists on this
router, so one student cannot read another's declared papers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends

from lemely.db.exam_calendar_repo import ExamCalendarService
from lemely.db.models.enums import Role
from lemely.web.deps import AuthContext, get_exam_calendar_service, require_role
from lemely.web.schemas_exam_calendar import (
    ExamDateDTO,
    StudentExamCalendarDTO,
    StudentExamEntryDTO,
)

if TYPE_CHECKING:
    from lemely.db.exam_calendar_repo import StudentExamEntry

router = APIRouter(
    prefix="/api/student/exam-calendar",
    dependencies=[Depends(require_role(Role.student))],
)


def _entry_to_dto(entry: StudentExamEntry) -> StudentExamEntryDTO:
    return StudentExamEntryDTO(
        subjectCode=entry.subject_code,
        sessionMonth=entry.session_month.value if entry.session_month is not None else None,
        sessionYear=entry.session_year,
        paperNumber=entry.paper_number,
        availability=entry.availability,
        dates=[
            ExamDateDTO(
                paperVariant=row.paper_variant,
                examDate=row.exam_date,
                startsAtLocal=row.starts_at_local,
                durationMinutes=row.duration_minutes,
                source=row.source,
            )
            for row in entry.dates
        ],
    )


@router.get("", response_model=StudentExamCalendarDTO)
def get_exam_calendar(
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[ExamCalendarService, Depends(get_exam_calendar_service)],
) -> StudentExamCalendarDTO:
    """S-28's calendar: the student's declared papers and their official dates.

    Always a 200. The three empty cases are **states, not errors**: a student
    who has not onboarded, a session we hold no timetable for, and a paper
    with no declared session are all true, expressible answers, and each one
    tells the screen a different sentence to render. A 404 here would say
    "there is no calendar for you", which is false in all three.

    In this build the table is empty in every environment, so the honest
    answer is ``no_timetable`` for any onboarded student — that is the
    intended behaviour and not a defect (D5.8). No date on this response was
    produced by anything other than an ingested official timetable row.
    """
    calendar = service.calendar_for_student(auth.user_id)
    return StudentExamCalendarDTO(
        availability=calendar.availability,
        entries=[_entry_to_dto(entry) for entry in calendar.entries],
    )


__all__ = ["router"]
