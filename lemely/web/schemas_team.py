"""Wire DTOs for /api/teacher/team (paymob billing Phase 03, spec §2.2, §2.3).

Field names are camelCase on the wire, like every other ``schemas_*`` module. Names
shown to a teacher are ``users.display_name`` with a neutral fallback, never an email.
``kind`` lets a client tell a seat from an assistant where one route returns either
(``PUT /members/{id}/cap``).
"""

# Pydantic construction needs these type imports at runtime (see the per-file-ignore
# in pyproject.toml).
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from lemely.db.teacher_team_repo import MAX_CAP_UNITS

AssistantRoleLiteral = Literal["co_teacher", "marker", "viewer"]
CapPeriodLiteral = Literal["month", "total"]


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class SeatDTO(ApiModel):
    kind: Literal["student_seat"]
    memberId: str
    studentId: str
    studentName: str
    status: Literal["active", "leaving"]
    leavesAt: datetime | None
    scopeSubjects: list[str]
    scopeActions: list[str]
    capUnits: int | None
    capPeriod: CapPeriodLiteral
    capUsedUnits: int
    """Units this seat drew from the teacher's credits in the current cap window (this
    month for ``month``, ever for ``total``), plus open holds (Phase 01 cap accounting)."""
    meterFraction: float | None
    """Share of this month's seat allowance used, 0..1; ``None`` before the first grant."""
    joinedAt: datetime


class SeatListDTO(ApiModel):
    seats: list[SeatDTO]


class SeatCapacityDTO(ApiModel):
    capacity: int
    used: int
    free: int


class SetSeatScopeRequestDTO(ApiModel):
    subjects: list[str] = Field(max_length=50)
    actions: list[str] = Field(max_length=20)


class SetCapRequestDTO(ApiModel):
    """Both fields are required: an empty body must not silently mean "unlimited".

    ``capUnits`` is ``null`` for no cap, or a whole number from 0 to :data:`MAX_CAP_UNITS`
    (strict: ``true`` and ``"12"`` are refused, not coerced).
    """

    capUnits: Annotated[StrictInt, Field(ge=0, le=MAX_CAP_UNITS)] | None
    capPeriod: CapPeriodLiteral


class AssistantDTO(ApiModel):
    kind: Literal["assistant"]
    memberId: str
    assistantId: str
    assistantName: str
    role: AssistantRoleLiteral
    permissions: dict[str, bool]
    effectivePermissions: list[str]
    capUnits: int | None
    capPeriod: CapPeriodLiteral
    capUsedUnits: int
    """Units this assistant drew from the lead's balance in the current cap window, plus
    open holds (Phase 01 cap accounting)."""


class AssistantListDTO(ApiModel):
    assistants: list[AssistantDTO]


class CreateAssistantInviteRequestDTO(ApiModel):
    role: AssistantRoleLiteral
    expiresInDays: int = Field(default=7, ge=1, le=30)


class AssistantInviteDTO(ApiModel):
    inviteId: str
    code: str
    role: AssistantRoleLiteral
    expiresAt: datetime
    createdAt: datetime


class AssistantInviteListDTO(ApiModel):
    invites: list[AssistantInviteDTO]


class RedeemAssistantInviteRequestDTO(ApiModel):
    code: str = Field(min_length=1, max_length=32)


class UpdateAssistantRequestDTO(ApiModel):
    role: AssistantRoleLiteral | None = None
    permissions: dict[str, bool] | None = Field(default=None, max_length=20)


class MembershipDTO(ApiModel):
    memberId: str
    teacherId: str
    teacherName: str
    role: AssistantRoleLiteral
    effectivePermissions: list[str]


class MembershipListDTO(ApiModel):
    memberships: list[MembershipDTO]
