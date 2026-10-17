"""API DTOs for redeemable invite codes (``/api/invites/*``, D7.3).

Request/response models for the public preview, the authenticated redeem,
and the two mint routes (``school.py``'s seat invite,
``classes.py``'s class invite share the mint response shape). Field names
are camelCase to match the frontend contract, mirroring the other
``schemas_*.py`` modules.
"""

# FastAPI ``Depends``/``response_model`` and pydantic construction need these type
# imports at runtime (see the per-file-ignore in pyproject.toml).
from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict


class ApiModel(BaseModel):
    """Base DTO: forbids extra fields and serialises via camelCase aliases."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class MintSeatInviteRequestDTO(ApiModel):
    """Mint a redeemable seat invite in ``schoolId``, reserving its seat.

    ``schoolId`` is a body field rather than a path segment, mirroring
    ``InviteStudentRequestDTO`` (``schemas_school.py``): an admin may
    administer more than one school, so the target must be named explicitly
    rather than assumed. Lives here rather than in ``schemas_school.py``
    because every other DTO this route touches (the response) is defined in
    this module too — the request and response for one route stay together.
    """

    schoolId: uuid.UUID


class InviteCodeDTO(ApiModel):
    """A freshly minted, redeemable invite code (D7.3).

    Returned by both mint routes — ``POST /api/school/seats/invite-code``
    (``schoolId`` set, ``classId`` ``None``) and
    ``POST /api/school/classes/{id}/invite-code`` (``classId`` set,
    ``schoolId`` ``None``) — so the two response shapes cannot drift apart.
    Carries no ``expiresAt``: neither mint path sets one today, and this
    codebase omits a field rather than always answering it with the same
    absent value (mirrors ``SchoolOverviewDTO``'s "no subscription field"
    rule).
    """

    code: str
    role: Literal["student", "teacher"]
    schoolId: str | None = None
    classId: str | None = None


class InvitePreviewDTO(ApiModel):
    """G-08's pre-account preview: what the code's holder is about to join.

    Backs the **public**, unauthenticated ``GET /api/invites/{code}``. Every
    field here is something the code's holder already learned from whoever
    handed it to them — a school's name, a class's name, a teacher's name, or
    (spec §4) a child's name for a parent invite. Deliberately carries no id,
    no roster, no seat/enrolment count; see
    :meth:`~lemely.db.invite_repo.InviteService.preview`.

    ``childName`` is set only for a ``role="parent"`` preview — the child's
    display name, or ``"your child"`` when blank (never their email or id,
    the identical disclosure discipline the other three fields already carry).
    """

    role: Literal["student", "teacher", "parent"]
    schoolName: str | None = None
    className: str | None = None
    teacherName: str | None = None
    childName: str | None = None


class RedeemInviteResponseDTO(ApiModel):
    """What redeeming a code produced, for the caller's next screen to read.

    ``childId`` (spec §4) is set only for a ``role="parent"`` redemption —
    mirrors :attr:`~lemely.db.invite_repo.RedeemResult.child_id`, letting the
    UI route straight to that child's overview.
    """

    role: Literal["student", "teacher", "parent"]
    schoolId: str | None = None
    classId: str | None = None
    childId: str | None = None


__all__ = [
    "ApiModel",
    "InviteCodeDTO",
    "InvitePreviewDTO",
    "MintSeatInviteRequestDTO",
    "RedeemInviteResponseDTO",
]
