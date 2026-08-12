"""The caller's own classes (``GET /api/student/classes``, P5.8 chunk C, D5.14 §1).

A thin router mirroring :mod:`lemely.web.routers.leaderboard` and
:mod:`lemely.web.routers.xp`: its own DTOs, no growth of ``student.py``, and
no logic of its own beyond projecting what
:meth:`~lemely.db.class_repo.ClassService.student_classes` already returns.

**Why it exists.** S-29's ``scope=class`` board requires a ``class_id`` query
parameter, and before this route there was no way for the student SPA to
learn one: ``GET`` routes on ``student.py`` are overview / subject / result /
standings / parent-links, and ``/student/classes/join`` is a ``POST``. The
class scope was not merely awkward to reach — it was unaddressable.

**It reuses the existing service method rather than deriving a second
enrolment query.** ``student_classes``'s own docstring asks callers not to
write one ("do not write a second ``ClassEnrollment`` query anywhere else for
that purpose"), and honouring that is why the parent portal's view of a
child's classes and the student's own view of them cannot drift.

**Identity is structurally ``auth.user_id``.** No caller-supplied student id
exists on this route, so one student cannot enumerate another's classes —
that is a property of the signature, not a check a later edit could drop.
Same shape as P5.3's leaderboard router and P5.8 chunk A's XP router.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from lemely.db.class_repo import ClassService  # noqa: TC001 - FastAPI resolves this at runtime
from lemely.db.models.enums import Role
from lemely.web.deps import AuthContext, get_class_service, require_role
from lemely.web.schemas_student_classes import StudentClassDTO, StudentClassListDTO

router = APIRouter(
    prefix="/api/student/classes", dependencies=[Depends(require_role(Role.student))]
)


@router.get("", response_model=StudentClassListDTO)
def list_my_classes(
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[ClassService, Depends(get_class_service)],
) -> StudentClassListDTO:
    """S-29: the classes this student is enrolled in, for the class-scope selector.

    Returns an empty list — a successful 200 — for a student enrolled in no
    class. That is the normal state for a direct subscriber with no school or
    teacher, so it is an answer, never a 404 and never an error the screen has
    to interpret.
    """
    rows = service.student_classes(auth.user_id)
    return StudentClassListDTO(
        classes=[
            StudentClassDTO(
                classId=str(row.class_id),
                name=row.name,
                subjectCode=row.subject_code,
                schoolName=row.school_name,
            )
            for row in rows
        ]
    )


__all__ = ["router"]
