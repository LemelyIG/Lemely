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
authenticated but role-agnostic at the **guard** level (``get_auth_context``
alone, no ``require_role``) — an invite's own ``role`` decides what redeeming
it does, not the caller's platform role, mirroring the ``/api/me/*`` routes'
AUTH_ANY shape. The caller's role is still passed through to
:meth:`~lemely.db.invite_repo.InviteService.redeem` as ``caller_role`` (spec
§4): a parent invite redeemed by anyone else, or a student/teacher invite
redeemed by a parent, is a **403**
(:class:`~lemely.db.invite_repo.InviteRoleMismatchError`) — a business rule
enforced in the service, not a route-level guard.
"""

# FastAPI ``Depends``/``response_model`` and pydantic construction need these type
# imports at runtime (see the per-file-ignore in pyproject.toml).
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from lemely.db.invite_repo import (
    InviteAlreadyRedeemedError,
    InviteNotFoundError,
    InviteRoleMismatchError,
    InviteService,
)
from lemely.db.models import Invite
from lemely.db.models.enums import Role
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
        childName=preview.child_name,
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

    ``caller_role`` (spec §4) is passed through so the service can enforce a
    parent invite against a non-parent caller, and a student/teacher invite
    against a parent caller — either mismatch is a **403**
    (:class:`~lemely.db.invite_repo.InviteRoleMismatchError`).

    **The 403 body is a fixed, non-revealing string — never ``str(exc)``.**
    ``InviteRoleMismatchError``'s own message names the code and states which
    kind of invite it is (e.g. "Invite 'ABC123' is a parent invite; caller
    role is Role.student") — exactly the log-line-not-a-response shape
    ``_cooldown_detail`` in ``routers/auth.py`` already documents the
    reasoning for. Echoing it here would be an enumeration oracle even though
    the caller is authenticated: a signed-in student could otherwise probe
    arbitrary codes and learn "this one exists and is a parent invite" from
    the 403 alone, distinct from the 404 an unknown code gets. This is a
    stronger case than ``_cooldown_detail``'s: not just impolite wording, an
    actual information leak. Naming neither the code nor the invite kind is
    what fixes it; a caller who already possesses the code they submitted
    learns nothing new from a body that only repeats it back to them.

    **Fixing the body does not close the channel entirely, and that is a
    recorded decision, not an oversight.** The status split itself —
    403 (exists, wrong role), 404 (does not exist), 409 (already redeemed by
    someone else) — still lets an authenticated caller learn "this code
    exists" from the status code alone, independent of the body. Accepted
    here because the caller already has an account and a bearer token: the
    anonymous-caller disclosure discipline binding rule 4 requires
    (:meth:`~lemely.db.invite_repo.InviteService.preview`, and the identical
    404-only collapse :func:`~lemely.web.routers.auth._require_live_parent_invite`
    applies for the three pre-account ``/auth/parent/*`` routes) does not
    extend to a signed-in caller probing a code they could, at best, learn
    is real but still cannot redeem.
    """
    try:
        result = service.redeem(auth.user_id, code, caller_role=Role(auth.role))
    except InviteNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InviteAlreadyRedeemedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except InviteRoleMismatchError as exc:
        raise HTTPException(
            status_code=403, detail="This invite is not for your account type."
        ) from exc
    return RedeemInviteResponseDTO(
        role=result.role.value,
        schoolId=str(result.school_id) if result.school_id is not None else None,
        classId=str(result.class_id) if result.class_id is not None else None,
        childId=str(result.child_id) if result.child_id is not None else None,
    )


__all__ = ["router"]
