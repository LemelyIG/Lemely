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

**Tutoring additions to redeem (SPEC §c.4, decision row 14), no guard change.**
A parent invite whose child already has four linked parents answers **409**
``parent_limit``; a new parent link and a new enrolment in a tutor's
school-less class are announced after commit (D5.9 §1) through
:func:`~lemely.web.tutoring_notify.send_after_commit`. The two mappers below
turn the service's change records into those notices; ``student.py`` and
``auth.py`` reuse them for the same events.
"""

# FastAPI ``Depends``/``response_model`` and pydantic construction need these type
# imports at runtime (see the per-file-ignore in pyproject.toml).
from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Final, Literal

from fastapi import APIRouter, Depends, HTTPException

from lemely.db.invite_repo import (
    InviteAlreadyRedeemedError,
    InviteNotFoundError,
    InviteParentLimitError,
    InviteRoleMismatchError,
    InviteService,
)
from lemely.db.models import Invite
from lemely.db.models.enums import InviteRole, ParentLinkEvent, Role
from lemely.db.notification_repo import NotificationService
from lemely.db.parent_repo import MAX_LINKED_PARENTS
from lemely.web.deps import (
    AuthContext,
    get_auth_context,
    get_invite_service,
    get_notification_service,
    get_push_transport,
)
from lemely.web.push import NotificationTransport
from lemely.web.schemas_invites import InviteCodeDTO, InvitePreviewDTO, RedeemInviteResponseDTO
from lemely.web.tutoring_http import tutoring_error
from lemely.web.tutoring_notify import class_join_notices, parent_link_notices, send_after_commit

if TYPE_CHECKING:
    from lemely.db.class_repo import TutorClassJoin
    from lemely.db.invite_repo import RedeemResult
    from lemely.db.parent_repo import ParentLinkChange
    from lemely.web.tutoring_notify import InboxNotice

router = APIRouter(prefix="/api/invites")

PARENT_LIMIT_MESSAGE: Final = (
    f"This child already has {MAX_LINKED_PARENTS} linked parents, the most allowed."
)
"""The ``parent_limit`` 409 message, shared with ``POST /api/auth/parent/signup``."""


def parent_link_change_notices(change: ParentLinkChange | None) -> list[InboxNotice]:
    """The after-commit ``parent_link`` notices for a link change (SPEC §b.4); none without one."""
    if change is None:
        return []
    return parent_link_notices(
        event="linked" if change.event is ParentLinkEvent.linked else "unlinked",
        event_id=change.event_id,
        recipient_parent_ids=change.notify_parent_ids,
    )


def tutor_class_join_notices(join: TutorClassJoin | None) -> list[InboxNotice]:
    """The after-commit ``tutor_access`` notices for a tutor class join (SC-2d); none otherwise."""
    if join is None:
        return []
    return class_join_notices(
        enrollment_id=join.enrollment_id,
        student_user_id=join.student_id,
        tutor_name=join.tutor_name,
        linked_parent_ids=join.linked_parent_ids,
    )


def redeem_notices(result: RedeemResult) -> list[InboxNotice]:
    """Every after-commit notice one redemption owes."""
    return [
        *parent_link_change_notices(result.link_change),
        *tutor_class_join_notices(result.class_join),
    ]


def _mintable_invite_role(role: InviteRole) -> Literal["student", "teacher"]:
    """Narrow :class:`InviteRole` onto :attr:`InviteCodeDTO.role`'s wire literal.

    ``InviteRole`` (``lemely.db.models.enums``) has three members --
    ``student``/``teacher``/``parent`` -- deliberately narrower than the
    five-member ``Role``. ``InviteCodeDTO.role`` is narrower still:
    ``Literal["student", "teacher"]``, because the only two mint routes that
    build an :class:`InviteCodeDTO` (``school.py``'s
    ``mint_seat_invite_code`` and ``classes.py``'s ``mint_class_invite_code``)
    both mint with ``role=InviteRole.student`` today -- neither ever mints a
    ``teacher`` or ``parent`` invite through this path. Parent invites are
    minted by :meth:`~lemely.db.invite_repo.InviteService.mint_parent_invite`
    and :meth:`~lemely.db.invite_repo.InviteService.rotate_parent_code`, but
    those return :class:`ParentInviteLinkDTO`/:class:`ParentCodeDTO`
    (``student.py``), never this DTO.

    So the ``parent`` branch below is unreachable **today**, checked, not
    assumed -- both ``_invite_to_dto`` call sites pass a freshly-minted
    ``Invite`` whose ``role`` was set from a hardcoded ``InviteRole.student``
    a few lines up the same call stack. It is real risk for tomorrow: if a
    third mint route or a future ``mint_class_invite``/``mint_seat_invite``
    parameter ever lets a caller choose ``InviteRole.parent`` and routes the
    result through ``_invite_to_dto``, pydantic's own field validation would
    raise inside the constructor before this ever reaches the wire -- this
    function's explicit raise just makes that failure a clear ``ValueError``
    at the narrowing site (mypy-checked) instead of an opaque
    ``ValidationError`` from ``InviteCodeDTO(...)``, and a ``cast``/
    ``# type: ignore`` here would suppress that message entirely.
    """
    if role is InviteRole.student:
        return "student"
    if role is InviteRole.teacher:
        return "teacher"
    raise ValueError(f"Invite role {role!r} has no mintable wire representation")


def _invite_to_dto(invite: Invite) -> InviteCodeDTO:
    """Convert a freshly minted ``Invite`` row into its wire DTO.

    Shared by both mint routes (``school.py``'s seat invite,
    ``classes.py``'s class invite) so the two response shapes cannot drift —
    imported across routers, the same pattern ``school.py`` already follows
    for ``classes.py``'s ``_average_for``.
    """
    return InviteCodeDTO(
        code=invite.code,
        role=_mintable_invite_role(invite.role),
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
    notifications: Annotated[NotificationService, Depends(get_notification_service)],
    transport: Annotated[NotificationTransport, Depends(get_push_transport)],
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

    **409 ``parent_limit``** (tutoring SPEC §c.4): a parent invite whose child
    already has four linked parents, for a parent not already among them. The
    body is the tutoring ``{"code", "message"}`` shape and names no one. After
    a successful redemption the parents already linked (new parent link), or
    the caller's linked parents (new enrolment in a tutor's school-less class),
    get their inbox notices; the change has committed by then, and a failed
    notice never fails the redemption.
    """
    try:
        result = service.redeem(auth.user_id, code, caller_role=Role(auth.role))
    except InviteNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InviteParentLimitError as exc:
        raise tutoring_error(409, "parent_limit", PARENT_LIMIT_MESSAGE) from exc
    except InviteAlreadyRedeemedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except InviteRoleMismatchError as exc:
        raise HTTPException(
            status_code=403, detail="This invite is not for your account type."
        ) from exc
    send_after_commit(redeem_notices(result), service=notifications, transport=transport)
    return RedeemInviteResponseDTO(
        role=result.role.value,
        schoolId=str(result.school_id) if result.school_id is not None else None,
        classId=str(result.class_id) if result.class_id is not None else None,
        childId=str(result.child_id) if result.child_id is not None else None,
    )


__all__ = [
    "PARENT_LIMIT_MESSAGE",
    "parent_link_change_notices",
    "redeem_notices",
    "router",
    "tutor_class_join_notices",
]
