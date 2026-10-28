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

**Leaving a school-less class** (``DELETE /api/student/classes/{class_id}``,
tutoring S17, SC-2c) sits here because this router's prefix is the path. It
removes only the caller's own enrolment, only in a class with no school; a
school class, a class the caller is not in and an unknown id are one 404.
"""

from __future__ import annotations

import uuid  # noqa: TC003 - FastAPI resolves the path parameter's type at runtime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response

from lemely.db.class_repo import ClassService  # noqa: TC001 - FastAPI resolves this at runtime
from lemely.db.models.enums import Role
from lemely.web.deps import AuthContext, get_class_service, require_role
from lemely.web.schemas_student_classes import StudentClassDTO, StudentClassListDTO
from lemely.web.tutoring_http import NO_STORE

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


@router.delete("/{class_id}", status_code=204)
def leave_school_less_class(
    class_id: uuid.UUID,
    response: Response,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[ClassService, Depends(get_class_service)],
) -> None:
    """S17: leave a school-less class (SC-2c, O24). 204, or 404 with no reason given.

    ``Cache-Control: private, no-store`` on the 204 and on the 404 (SPEC §b.5;
    this router keeps its own route class, so the header is set here). The
    teacher stops seeing the caller's progress through this class at once.
    """
    if not service.leave_school_less_class(auth.user_id, class_id):
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": "Class not found."},
            headers={"Cache-Control": NO_STORE},
        )
    response.headers["Cache-Control"] = NO_STORE


__all__ = ["router"]
