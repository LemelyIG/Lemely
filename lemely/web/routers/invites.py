"""Redeemable invite codes — ``/api/invites/*`` (D7.3, spec §1.2).

Closes the gap spec §1.2 describes: two working endpoints with no user
interface. ``POST /api/student/classes/join`` was implemented,
ownership-safe and tested, while ``ClassRoster.tsx`` told teachers "They
enter it from the student portal to join" and no such screen existed;
``POST /api/school/seats/invite`` created a student account outright with a
temporary password handed over once, out of band. This router — plus the
mint routes ``school.py`` and ``classes.py`` add — is what makes both
reachable.

``GET /api/invites/{code}`` is deliberately **public**: G-08's flow is
preview-before-account (a visitor sees what they are about to join, then
signs up or signs in to redeem), and :class:`~lemely.db.invite_repo.InviteService.preview`
is written to be paranoid about disclosure precisely because this route
carries no authentication at all. ``POST /api/invites/{code}/redeem`` is
authenticated but role-agnostic (``get_auth_context`` alone, no
``require_role``) — an invite's own ``role`` decides what redeeming it does,
not the caller's platform role, mirroring the ``/api/me/*`` routes' AUTH_ANY
shape.
"""

# FastAPI ``Depends``/``response_model`` and pydantic construction need these type
# imports at runtime (see the per-file-ignore in pyproject.toml).
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from lemely.db.invite_repo import (
    InviteAlreadyRedeemedError,
    InviteNotFoundError,
    InviteService,
)
from lemely.db.models import Invite
from lemely.web.deps import AuthContext, get_auth_context, get_invite_service
from lemely.web.schemas_invites import InviteCodeDTO, InvitePreviewDTO, RedeemInviteResponseDTO

router = APIRouter(prefix="/api/invites")


def _invite_to_dto(invite: Invite) -> InviteCodeDTO:
    """Convert a freshly minted ``Invite`` row into its wire DTO.

    Shared by both mint routes (``school.py``'s seat invite,
    ``classes.py``'s class invite) so the two response shapes cannot drift —
    imported across routers, the same pattern ``school.py`` already follows
    for ``classes.py``'s ``_average_for``.
    """
    return InviteCodeDTO(
        code=invite.code,
        role=invite.role.value,
        schoolId=str(invite.school_id) if invite.school_id is not None else None,
        classId=str(invite.class_id) if invite.class_id is not None else None,
    )


@router.get("/{code}", response_model=InvitePreviewDTO)
def preview_invite(
    code: str,
    service: Annotated[InviteService, Depends(get_invite_service)],
) -> InvitePreviewDTO:
    """G-08: resolve a code to what its holder is about to join. Public.

    Accepts either an ``invites.code`` or a bare ``classes.join_code`` — the
    single "enter a code" box has no way to ask which kind its holder was
    given (see :meth:`~lemely.db.invite_repo.InviteService.preview`). Every
    field on the response is something the holder already learned from
    whoever handed them the code; there is no id, no roster, no count.
    """
    try:
        preview = service.preview(code)
    except InviteNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return InvitePreviewDTO(
        role=preview.role.value,
        schoolName=preview.school_name,
        className=preview.class_name,
        teacherName=preview.teacher_name,
    )


@router.post("/{code}/redeem", response_model=RedeemInviteResponseDTO)
def redeem_invite(
    code: str,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[InviteService, Depends(get_invite_service)],
) -> RedeemInviteResponseDTO:
    """Redeem a code for the authenticated caller. Idempotent.

    Assumes the caller already has an account (unlike :func:`preview_invite`,
    this route requires a bearer token) and attaches it to whatever the code
    provisions. A code shared onward after someone else already redeemed it
    is a **409**, never a second seat consumed or a stranger silently
    attached to a school — see
    :meth:`~lemely.db.invite_repo.InviteService.redeem`.
    """
    try:
        result = service.redeem(auth.user_id, code)
    except InviteNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InviteAlreadyRedeemedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return RedeemInviteResponseDTO(
        role=result.role.value,
        schoolId=str(result.school_id) if result.school_id is not None else None,
        classId=str(result.class_id) if result.class_id is not None else None,
    )


__all__ = ["router"]
