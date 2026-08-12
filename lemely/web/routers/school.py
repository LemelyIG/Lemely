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

from lemely.db.models.enums import Role
from lemely.db.seat_repo import (
    SeatOwnershipError,
    SeatQuotaExceededError,
    SeatService,
    SeatUsage,
)
from lemely.web.deps import AuthContext, get_seat_service, require_role
from lemely.web.schemas_school import (
    InviteStudentRequestDTO,
    InviteStudentResponseDTO,
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
                assignedAt=row.assigned_at.isoformat() if row.assigned_at else None,
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
