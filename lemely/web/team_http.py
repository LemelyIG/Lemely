"""HTTP mapping for teacher-team errors (paymob billing Phase 03).

Bodies use the ``{"code", "message"}`` shape (``lemely.web.tutoring_http``). The
message is fixed copy, never ``str(exc)``, so no member id or teacher id is echoed.
"""

from __future__ import annotations

from typing import Final

from fastapi import HTTPException

from lemely.db.teacher_team_repo import (
    AssistantInviteLimitError,
    AssistantInviteNotFound,
    AssistantInviteRedeemed,
    InvalidCap,
    InvalidInviteExpiry,
    InvalidPermissions,
    InvalidScope,
    NoFreeSeat,
    NotATeacher,
    TeamError,
    TeamMemberNotFound,
)

NO_FREE_SEAT_MESSAGE: Final = (
    "This teacher has no free student seats. Ask your teacher to add more seats, then try again."
)


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def no_free_seat_error() -> HTTPException:
    """Return the 409 a class join gets when the teacher has no free seat (spec §4.4)."""
    return _error(409, "no_free_seat", NO_FREE_SEAT_MESSAGE)


def lead_only_error() -> HTTPException:
    """Return the 403 a team route gives a request that asks to act for another teacher.

    Seats, caps, assistants and invites belong to the caller's own team, so an
    ``X-Lemely-Acting-Teacher`` header naming anyone else is refused, never honoured.
    The body is fixed copy and echoes nothing from the header.
    """
    return _error(
        403,
        "team_lead_only",
        "Seats and assistants are managed by the lead teacher.",
    )


def team_error_to_http(exc: TeamError) -> HTTPException:
    """Map a :class:`TeamError` onto its HTTP status and fixed body.

    :class:`NotATeacher` is checked before its parent :class:`TeamStateError`. An error
    with no dedicated entry (``TeamStateError`` and the base class) is a 409
    ``conflict``: the request is well-formed but the team's current state refuses it.
    """
    if isinstance(exc, NoFreeSeat):
        return no_free_seat_error()
    # Before the fallback below: NotATeacher subclasses TeamStateError, which is a 409.
    if isinstance(exc, NotATeacher):
        return _error(403, "not_a_teacher", "Only a teacher account can do this.")
    if isinstance(exc, InvalidInviteExpiry):
        return _error(422, "invalid_expiry", "Choose an expiry between 1 and 30 days.")
    if isinstance(exc, (TeamMemberNotFound, AssistantInviteNotFound)):
        return _error(404, "not_found", "Not found.")
    if isinstance(exc, InvalidScope):
        return _error(422, "invalid_scope", "Use known subjects and seat actions only.")
    if isinstance(exc, InvalidCap):
        return _error(
            422, "invalid_cap", "Use a whole number of credits, from zero up to the limit."
        )
    if isinstance(exc, InvalidPermissions):
        return _error(422, "invalid_permissions", "Use known team permissions only.")
    if isinstance(exc, AssistantInviteRedeemed):
        return _error(409, "invite_already_redeemed", "This invite has already been used.")
    if isinstance(exc, AssistantInviteLimitError):
        return _error(409, "invite_limit", "You have too many open assistant invites.")
    return _error(409, "conflict", "That change is not possible right now.")


__all__ = ["NO_FREE_SEAT_MESSAGE", "lead_only_error", "no_free_seat_error", "team_error_to_http"]
