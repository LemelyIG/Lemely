"""School-admin portal — seat management endpoints under ``/api/school``.

A ``school_admin`` provisions student accounts against their school's seat quota.
Every route is gated at the router level to the ``school_admin`` role alone
(least privilege, no super-role — mirrors D1.6); row-level ownership is then
enforced inside :class:`~lemely.db.seat_repo.SeatService`, which only ever touches
a school the caller holds a ``school_admin`` membership for. A caller reaching for
another school's seats gets a 403, never data.

The seat/quota/ownership logic lives in the service; this module is the thin HTTP
layer that maps its domain errors to status codes and its dataclasses to wire
DTOs.
"""

# FastAPI ``Depends``/``response_model`` and pydantic construction need these type
# imports at runtime (see the per-file-ignore in pyproject.toml).
from __future__ import annotations

import secrets
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from lemely.core.history import HistoryStoreProtocol
from lemely.db.models.enums import Role
from lemely.db.school_admin_repo import (
    ClassesWouldBeOrphanedError,
    InvalidReassignmentError,
    SchoolAdminService,
    SchoolOwnershipError,
    TeacherNotFoundError,
)
from lemely.db.seat_repo import (
    SeatOwnershipError,
    SeatQuotaExceededError,
    SeatService,
    SeatUsage,
)
from lemely.web.deps import (
    AuthContext,
    get_history_store,
    get_school_admin_service,
    get_seat_service,
    require_role,
)

# The mean of each student's latest grade-bearing paper, imported rather than
# re-derived. `classes.py` owns that rule (D3.9, `docs/quiz-model.md` §5) and
# `tests/test_web_quiz_origin_filtering.py` pins it there; a school average that
# computed its own would be free to disagree with the class average a teacher
# reads for the same students. Cross-router import matches the existing house
# style — `classes.py` itself imports `_mean` from `teacher.py`.
from lemely.web.routers.classes import _average_for
from lemely.web.schemas_school import (
    InviteStudentRequestDTO,
    InviteStudentResponseDTO,
    InviteTeacherRequestDTO,
    InviteTeacherResponseDTO,
    RemoveTeacherRequestDTO,
    RemoveTeacherResponseDTO,
    SchoolOverviewDTO,
    SchoolOverviewListDTO,
    SchoolTeacherDTO,
    SchoolTeacherGroupDTO,
    SchoolTeacherListDTO,
    SeatClassDTO,
    SeatRowDTO,
    SeatUsageDTO,
    SeatUsageListDTO,
)

# Seat management is a school_admin-only surface. Gating at the router level means
# every current and future seat route inherits the 401-then-403 guard by
# construction. A platform_admin manages schools via a dedicated admin surface
# later, not here (D1.10, consistent with D1.6's no-super-role rule).
router = APIRouter(
    prefix="/api",
    dependencies=[Depends(require_role(Role.school_admin))],
)

# Length (in bytes of entropy) of a generated one-time student password. 24 bytes
# → a 32-char URL-safe token; far beyond brute-force reach for a temporary
# credential the student rotates on first login.
_TEMP_PASSWORD_ENTROPY_BYTES = 24


def _seat_usage_to_dto(usage: SeatUsage) -> SeatUsageDTO:
    """Convert a service :class:`SeatUsage` into its wire DTO."""
    return SeatUsageDTO(
        schoolId=str(usage.school_id),
        schoolName=usage.school_name,
        quota=usage.quota,
        used=usage.used,
        available=usage.available,
        seats=[
            SeatRowDTO(
                seatId=str(row.seat_id),
                status=row.status.value,
                assignedUserId=str(row.assigned_user_id) if row.assigned_user_id else None,
                assignedEmail=row.assigned_email,
                assignedDisplayName=row.assigned_display_name,
                assignedAt=row.assigned_at.isoformat() if row.assigned_at else None,
                classes=[
                    SeatClassDTO(
                        classId=str(seat_class.class_id),
                        name=seat_class.name,
                        teacherName=seat_class.teacher_name,
                    )
                    for seat_class in row.classes
                ],
                lastAttemptAt=row.last_attempt_at.isoformat() if row.last_attempt_at else None,
            )
            for row in usage.seats
        ],
    )


@router.get("/school/seats", response_model=SeatUsageListDTO)
def list_seats(
    auth: Annotated[AuthContext, Depends(require_role(Role.school_admin))],
    service: Annotated[SeatService, Depends(get_seat_service)],
) -> SeatUsageListDTO:
    """Return seat usage for every school the authenticated admin administers.

    Ownership is inherent: the service returns only schools the caller holds a
    ``school_admin`` membership for, so there is no cross-tenant leakage even
    though no school id is supplied.
    """
    usages = service.list_admin_schools(auth.user_id)
    return SeatUsageListDTO(schools=[_seat_usage_to_dto(u) for u in usages])


@router.post("/school/seats/invite", response_model=InviteStudentResponseDTO)
def invite_student(
    body: InviteStudentRequestDTO,
    auth: Annotated[AuthContext, Depends(require_role(Role.school_admin))],
    service: Annotated[SeatService, Depends(get_seat_service)],
) -> InviteStudentResponseDTO:
    """Create a student account and assign it a seat in ``schoolId``.

    Identity is the authenticated admin (``auth.user_id``); the target school must
    be one they administer (else 403). A missing password is generated once and
    returned in ``temporaryPassword`` (no student email provider in v1). A school
    at its seat quota yields a 409.
    """
    generated = body.password is None
    password = body.password or secrets.token_urlsafe(_TEMP_PASSWORD_ENTROPY_BYTES)
    try:
        result = service.invite_student(
            auth.user_id,
            body.schoolId,
            body.email,
            password,
            display_name=body.displayName,
        )
    except SeatOwnershipError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except SeatQuotaExceededError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return InviteStudentResponseDTO(
        userId=str(result.user_id),
        seatId=str(result.seat_id),
        email=result.email,
        temporaryPassword=password if generated else None,
    )


@router.get("/school/overview", response_model=SchoolOverviewListDTO)
def school_overview(
    auth: Annotated[AuthContext, Depends(require_role(Role.school_admin))],
    seats: Annotated[SeatService, Depends(get_seat_service)],
    admin: Annotated[SchoolAdminService, Depends(get_school_admin_service)],
    history_store: Annotated[HistoryStoreProtocol, Depends(get_history_store)],
) -> SchoolOverviewListDTO:
    """Return K-01's headline figures for every school the caller administers.

    Ownership is inherent for the same reason :func:`list_seats` needs no school
    id: both services return only schools the caller holds a ``school_admin``
    membership for. An admin who administers nothing gets ``{"schools": []}``.

    The seat half comes from :class:`SeatService` rather than being recounted
    here, so "used" has exactly one definition across K-01 and K-02.
    """
    usage_by_school = {
        str(usage.school_id): usage for usage in seats.list_admin_schools(auth.user_id)
    }
    schools: list[SchoolOverviewDTO] = []
    for counts in admin.overview(auth.user_id):
        usage = usage_by_school.get(str(counts.school_id))
        histories = [history_store.load(str(student_id)) for student_id in counts.student_ids]
        average = _average_for(histories)
        # The denominator of that average, counted the same way `_average_for`
        # filters: students whose latest *grade-bearing* record exists. A student
        # with only quiz activity is not in it, which is why this cannot simply
        # be "students with any history".
        with_a_paper = sum(1 for history in histories if _average_for([history]) is not None)
        schools.append(
            SchoolOverviewDTO(
                schoolId=str(counts.school_id),
                schoolName=counts.school_name,
                quota=usage.quota if usage else 0,
                seatsUsed=usage.used if usage else 0,
                seatsAvailable=usage.available if usage else 0,
                teacherCount=counts.teacher_count,
                classCount=counts.class_count,
                enrolledStudentCount=counts.enrolled_student_count,
                studentsWithAPaper=with_a_paper,
                averageLatestPercentage=average,
            )
        )
    return SchoolOverviewListDTO(schools=schools)


@router.get("/school/teachers", response_model=SchoolTeacherListDTO)
def list_school_teachers(
    auth: Annotated[AuthContext, Depends(require_role(Role.school_admin))],
    admin: Annotated[SchoolAdminService, Depends(get_school_admin_service)],
) -> SchoolTeacherListDTO:
    """Return the staff roster of every school the caller administers (K-03)."""
    return SchoolTeacherListDTO(
        schools=[
            SchoolTeacherGroupDTO(
                schoolId=str(group.school_id),
                schoolName=group.school_name,
                teachers=[
                    SchoolTeacherDTO(
                        userId=str(teacher.user_id),
                        email=teacher.email,
                        displayName=teacher.display_name,
                        classCount=teacher.class_count,
                        studentCount=teacher.student_count,
                    )
                    for teacher in group.teachers
                ],
            )
            for group in admin.list_teachers(auth.user_id)
        ]
    )


@router.post("/school/teachers/invite", response_model=InviteTeacherResponseDTO)
def invite_teacher(
    body: InviteTeacherRequestDTO,
    auth: Annotated[AuthContext, Depends(require_role(Role.school_admin))],
    admin: Annotated[SchoolAdminService, Depends(get_school_admin_service)],
) -> InviteTeacherResponseDTO:
    """Create a teacher account and add it to ``schoolId``'s staff (K-03).

    This is the admin-created path ``routers/auth.py`` reserves: self-service
    signup may only ever mint a ``student`` (D1.7), and an elevated role is
    created here, by an authenticated ``school_admin``, for a school they
    administer. No quota is consumed — seats are a student allocation.
    """
    generated = body.password is None
    password = body.password or secrets.token_urlsafe(_TEMP_PASSWORD_ENTROPY_BYTES)
    try:
        result = admin.invite_teacher(
            auth.user_id,
            body.schoolId,
            body.email,
            password,
            display_name=body.displayName,
        )
    except SchoolOwnershipError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return InviteTeacherResponseDTO(
        userId=str(result.user_id),
        email=result.email,
        temporaryPassword=password if generated else None,
    )


@router.post("/school/teachers/{teacher_id}/remove", response_model=RemoveTeacherResponseDTO)
def remove_teacher(
    teacher_id: uuid.UUID,
    body: RemoveTeacherRequestDTO,
    auth: Annotated[AuthContext, Depends(require_role(Role.school_admin))],
    admin: Annotated[SchoolAdminService, Depends(get_school_admin_service)],
) -> RemoveTeacherResponseDTO:
    """Remove a teacher from a school's staff, reassigning their classes (K-03).

    A teacher who still owns classes and no ``reassignToTeacherId`` is a **409**,
    not a silent orphaning: the spec requires the reassignment be made
    explicitly, and the message names how many classes are in the way so the
    screen can say so.

    The teacher's account survives; only the membership is deleted. That is why
    this is a POST to ``/remove`` rather than a ``DELETE`` of the teacher — the
    latter would describe a destruction that does not happen.
    """
    try:
        reassigned = admin.remove_teacher(
            auth.user_id,
            body.schoolId,
            teacher_id,
            reassign_to=body.reassignToTeacherId,
        )
    except SchoolOwnershipError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except TeacherNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ClassesWouldBeOrphanedError, InvalidReassignmentError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return RemoveTeacherResponseDTO(classesReassigned=reassigned)


@router.post("/school/seats/{seat_id}/revoke", status_code=204)
def revoke_seat(
    seat_id: uuid.UUID,
    auth: Annotated[AuthContext, Depends(require_role(Role.school_admin))],
    service: Annotated[SeatService, Depends(get_seat_service)],
) -> None:
    """Revoke a seat, freeing its slot against the school's quota.

    The student's account is left intact. A seat the caller does not administer is
    a 403; an unknown seat is a 404 (raised by the service).
    """
    from lemely.db.seat_repo import SeatNotFoundError

    try:
        service.revoke_seat(auth.user_id, seat_id)
    except SeatNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SeatOwnershipError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
