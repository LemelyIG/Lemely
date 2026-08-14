"""API DTOs for the school-admin seat-management endpoints (``/api/school/*``).

Request/response models for listing seat usage, inviting a student onto a seat,
and revoking a seat. Field names are camelCase to match the frontend contract,
mirroring the other ``schemas_*.py`` modules.
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict


class ApiModel(BaseModel):
    """Base DTO: forbids extra fields and serialises via camelCase aliases."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class SeatClassDTO(ApiModel):
    """One class, inside this school, that a seated student is enrolled in."""

    classId: str
    name: str
    teacherName: str | None = None


class SeatRowDTO(ApiModel):
    """One occupied seat and the student it is assigned to.

    ``classes`` is a list because a student's enrolment within a school is not
    exclusive; see :class:`~lemely.db.seat_repo.SeatRow` for why K-02's single
    "class" column is not collapsed here.

    ``lastAttemptAt`` is **not** "last active". No table records a session or a
    login, so the most recent attempt is the only activity signal that exists,
    and the field is named for what it measures.
    """

    seatId: str
    status: Literal["available", "assigned", "revoked"]
    assignedUserId: str | None = None
    assignedEmail: str | None = None
    assignedDisplayName: str | None = None
    assignedAt: str | None = None
    classes: list[SeatClassDTO] = []
    lastAttemptAt: str | None = None


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

    schoolId: uuid.UUID
    email: str
    displayName: str | None = None
    password: str | None = None


class InviteStudentResponseDTO(ApiModel):
    """The created student's identity, its seat, and any generated password."""

    userId: str
    seatId: str
    email: str
    temporaryPassword: str | None = None


class SchoolOverviewDTO(ApiModel):
    """K-01's headline figures for one school the caller administers.

    ``averageLatestPercentage`` is the mean of each student's **latest
    grade-bearing** paper (``docs/quiz-model.md`` §5) — the identical rule the
    class screens use, computed by the identical function, so a school mean and a
    class mean can never mean two different things.

    ``studentsWithAPaper`` is its denominator, carried explicitly rather than
    implied. A mean over 3 of 40 students is a different claim from a mean over
    40, and K-01 is the one screen where a reader would otherwise assume the
    larger number. When it is 0 the average is ``None``, never 0.0.

    There is no subscription field. ``subscriptions`` is a **per-user** table
    (``lemely/db/models/billing.py``); no school-level subscription, plan or
    billing state exists anywhere in the schema, so K-01's "subscription status"
    line has nothing honest to read and is omitted rather than invented.
    """

    schoolId: str
    schoolName: str
    quota: int
    seatsUsed: int
    seatsAvailable: int
    teacherCount: int
    classCount: int
    enrolledStudentCount: int
    studentsWithAPaper: int
    averageLatestPercentage: float | None = None


class SchoolOverviewListDTO(ApiModel):
    """K-01 across every school the caller administers (usually one)."""

    schools: list[SchoolOverviewDTO]


class SchoolTeacherDTO(ApiModel):
    """One teacher on a school's staff (K-03).

    ``studentCount`` is distinct students across that teacher's classes in this
    school, so a student they teach twice counts once.
    """

    userId: str
    email: str
    displayName: str | None = None
    classCount: int
    studentCount: int


class SchoolTeacherGroupDTO(ApiModel):
    """One school's staff roster."""

    schoolId: str
    schoolName: str
    teachers: list[SchoolTeacherDTO]


class SchoolTeacherListDTO(ApiModel):
    """Staff rosters across every school the caller administers."""

    schools: list[SchoolTeacherGroupDTO]


class InviteTeacherRequestDTO(ApiModel):
    """Invite a teacher onto a school's staff.

    Same credential handling as :class:`InviteStudentRequestDTO`: no email
    provider exists in v1, so an omitted password is generated once and returned
    once for the admin to convey out of band.
    """

    schoolId: uuid.UUID
    email: str
    displayName: str | None = None
    password: str | None = None


class InviteTeacherResponseDTO(ApiModel):
    """The created teacher's identity and any generated password."""

    userId: str
    email: str
    temporaryPassword: str | None = None


class RemoveTeacherRequestDTO(ApiModel):
    """Remove a teacher from a school's staff, reassigning their classes.

    ``reassignToTeacherId`` is required whenever the teacher still owns classes
    here; omitting it yields a 409 naming the count, rather than orphaning them
    (UI spec K-03). It is ignored when they own none.
    """

    schoolId: uuid.UUID
    reassignToTeacherId: uuid.UUID | None = None


class RemoveTeacherResponseDTO(ApiModel):
    """How much staffing actually moved, so the screen can say so."""

    classesReassigned: int


__all__ = [
    "ApiModel",
    "InviteStudentRequestDTO",
    "InviteStudentResponseDTO",
    "InviteTeacherRequestDTO",
    "InviteTeacherResponseDTO",
    "RemoveTeacherRequestDTO",
    "RemoveTeacherResponseDTO",
    "SchoolOverviewDTO",
    "SchoolOverviewListDTO",
    "SchoolTeacherDTO",
    "SchoolTeacherGroupDTO",
    "SchoolTeacherListDTO",
    "SeatClassDTO",
    "SeatRowDTO",
    "SeatUsageDTO",
    "SeatUsageListDTO",
]
