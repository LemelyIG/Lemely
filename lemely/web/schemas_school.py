"""API DTOs for the school-admin seat-management endpoints (``/api/school/*``).

Request/response models for listing seat usage, inviting a student onto a seat,
and revoking a seat. Field names are camelCase to match the frontend contract,
mirroring the other ``schemas_*.py`` modules.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class ApiModel(BaseModel):
    """Base DTO: forbids extra fields and serialises via camelCase aliases."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class SeatRowDTO(ApiModel):
    """One occupied seat and the student it is assigned to."""

    seatId: str
    status: Literal["available", "assigned", "revoked"]
    assignedUserId: str | None = None
    assignedEmail: str | None = None
    assignedAt: str | None = None


class SeatUsageDTO(ApiModel):
    """A school's seat headroom plus its current (non-revoked) seats."""

    schoolId: str
    schoolName: str
    quota: int
    used: int
    available: int
    seats: list[SeatRowDTO]


class SeatUsageListDTO(ApiModel):
    """Seat usage across every school the caller administers."""

    schools: list[SeatUsageDTO]


class InviteStudentRequestDTO(ApiModel):
    """Invite a student onto a seat in ``schoolId``.

    ``password`` is optional: when omitted the backend generates a one-time
    temporary password and returns it once (there is no student email provider in
    v1 — the admin conveys the credential out of band, exactly as the mock SMS
    provider logs the parent OTP).
    """

    schoolId: str
    email: str
    displayName: str | None = None
    password: str | None = None


class InviteStudentResponseDTO(ApiModel):
    """The created student's identity, its seat, and any generated password."""

    userId: str
    seatId: str
    email: str
    temporaryPassword: str | None = None


__all__ = [
    "ApiModel",
    "InviteStudentRequestDTO",
    "InviteStudentResponseDTO",
    "SeatRowDTO",
    "SeatUsageDTO",
    "SeatUsageListDTO",
]
