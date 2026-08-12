"""Friends endpoints (``/api/student/friends``, P5.4 chunk B).

A new router file, mirroring ``lemely.web.routers.leaderboard``: thin, its
own DTOs, no growth of ``student.py``. This router adds no friendship logic
of its own — code minting, the crossed-requests auto-accept, opt-out
handling and the "no existence oracle" error collapsing are all
:class:`~lemely.db.friend_repo.FriendService`'s (P5.4 chunk A, D5.6). **No
mark ever crosses this boundary** (D5.1 §0) — the response DTOs in
``lemely.web.schemas_friends`` structurally cannot carry one; see that
module's docstring.

Identity is **always** ``auth.user_id`` — there is no caller-supplied user id
anywhere on this router, so one student can never act as another's friend
list, request, accept or removal. That is structural, not merely
permission-checked: every service call below is keyed on the token's ``sub``,
never on a path or body parameter.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status

from lemely.db.friend_repo import (
    FriendAlreadyExistsError,
    FriendCodeNotFoundError,
    FriendIneligibleUserError,
    FriendNotPendingError,
    FriendRequestNotFoundError,
    FriendSelfRequestError,
    FriendService,
    FriendSummary,
    FriendUserNotFoundError,
)
from lemely.db.leaderboard_repo import ANONYMOUS_DISPLAY_NAME
from lemely.db.models.enums import FriendshipStatus, Role
from lemely.web.deps import AuthContext, get_friend_service, require_role
from lemely.web.schemas_friends import (
    FriendDTO,
    FriendRequestCreateDTO,
    FriendRequestDTO,
    FriendsPageDTO,
)

if TYPE_CHECKING:
    from datetime import datetime

    from lemely.db.friend_repo import FriendRequestSummary
    from lemely.db.models.users import Friendship

router = APIRouter(
    prefix="/api/student/friends", dependencies=[Depends(require_role(Role.student))]
)


def _summary_to_dto(summary: FriendSummary) -> FriendDTO:
    return FriendDTO(
        friendshipId=str(summary.friendship_id),
        userId=str(summary.user_id),
        displayName=summary.display_name,
        xp=summary.xp,
        streak=summary.streak,
        optedOut=summary.opted_out,
        friendsSince=summary.friends_since,
    )


def _pending_to_dto(req: FriendRequestSummary) -> FriendRequestDTO:
    return FriendRequestDTO(
        friendshipId=str(req.friendship_id),
        userId=str(req.user_id),
        displayName=req.display_name,
        requestedAt=req.requested_at,
        status="pending",
    )


def _friendship_to_request_dto(
    friendship_id: uuid.UUID,
    user_id: uuid.UUID,
    display_name: str,
    requested_at: datetime,
    request_status: Literal["pending", "accepted"],
) -> FriendRequestDTO:
    return FriendRequestDTO(
        friendshipId=str(friendship_id),
        userId=str(user_id),
        displayName=display_name,
        requestedAt=requested_at,
        status=request_status,
    )


@router.get("", response_model=FriendsPageDTO)
def get_friends(
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[FriendService, Depends(get_friend_service)],
) -> FriendsPageDTO:
    """S-30: the caller's own friend screen in one call.

    Opening the screen mints the caller's friend code on first read (it is
    otherwise never issued) via :meth:`~lemely.db.friend_repo.FriendService.friend_code_for`
    — no separate "generate my code" action exists because none is needed.

    Raises:
        HTTPException: 404 if the token's ``sub`` has no ``users`` row; 403
            if that row exists but is not a student (D5.1 §10 defence in
            depth — mirrors ``leaderboard.py``'s ``LeaderboardIneligibleViewerError``
            handling).
    """
    try:
        friend_code = service.friend_code_for(auth.user_id)
    except FriendUserNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FriendIneligibleUserError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    friends = service.list_friends(auth.user_id)
    incoming = service.pending_incoming(auth.user_id)
    outgoing = service.pending_outgoing(auth.user_id)
    return FriendsPageDTO(
        friendCode=friend_code,
        friends=[_summary_to_dto(f) for f in friends],
        incoming=[_pending_to_dto(r) for r in incoming],
        outgoing=[_pending_to_dto(r) for r in outgoing],
    )


@router.post("/requests", response_model=FriendRequestDTO, status_code=status.HTTP_201_CREATED)
def create_friend_request(
    body: FriendRequestCreateDTO,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[FriendService, Depends(get_friend_service)],
) -> FriendRequestDTO:
    """Send a friend request to the holder of ``body.friendCode``.

    **The submitted code is normalised with ``.strip().upper()`` before the
    service ever sees it** — deliberate, not incidental. The friend-code
    alphabet is uppercase-only (``lemely.db.friend_repo``), and a student
    typing a friend's code off a screenshot in lowercase, or with a stray
    leading/trailing space from a copy-paste, must not get "no such code".

    **The response is honest about which actually happened.** Because
    ``FriendService.request`` returns the *accepted* row when the target had
    already sent a matching request (the crossed-requests case, D5.6 §2),
    the returned DTO's ``status`` reflects the friendship's real status —
    ``"accepted"`` there, ``"pending"`` otherwise — so the client can say
    "you're now friends" instead of "request sent". This is never inferred
    client-side.

    Raises:
        HTTPException: 404 unknown ``auth.user_id`` or unknown friend code;
            403 caller exists but is not a student; 422 self-request or
            malformed identifiers; 409 already friends or duplicate
            outgoing request.
    """
    code = body.friendCode.strip().upper()
    try:
        friendship = service.request(auth.user_id, code)
    except FriendUserNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FriendIneligibleUserError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FriendCodeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FriendSelfRequestError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except FriendAlreadyExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    other_id, display_name = _other_party(service, auth.user_id, friendship)
    request_status: Literal["pending", "accepted"] = (
        "accepted" if friendship.status == FriendshipStatus.accepted else "pending"
    )
    return _friendship_to_request_dto(
        friendship.id,
        other_id,
        display_name,
        friendship.created_at,
        request_status,
    )


def _other_party(
    service: FriendService, caller_id: str, friendship: Friendship
) -> tuple[uuid.UUID, str]:
    """Resolve the *other* party's id and display name for a returned friendship.

    Mirrors :func:`get_friends` for the name — no separate name-lookup query
    is added to :class:`FriendService` for this one caller.

    ``request()`` can return either a freshly-created ``pending`` row (found
    among the caller's own outgoing requests) or, in the crossed-requests
    case, a row it just flipped to ``accepted`` (found among the caller's own
    friends instead) — mirroring exactly which of
    ``pending_outgoing``/``list_friends`` would already show this row on the
    next ``GET /api/student/friends`` call.

    **The id cannot be read off ``friendship.addressee_id``.** That is only
    the other party for a *freshly created* row. In the crossed-requests case
    (D5.6 §2) the row this returns was created by the **other** student, so
    its ``addressee_id`` is the caller themselves — returning it would ship a
    DTO that ids the caller while carrying the other student's display name,
    and a client rendering "you are now friends with ..." would link to the
    caller's own profile. The party is therefore derived from which end of
    the row the caller is *not* on, which is correct in both directions.
    """
    friendship_id = friendship.id
    caller_uuid = uuid.UUID(caller_id) if isinstance(caller_id, str) else caller_id
    other_id = (
        friendship.requester_id
        if friendship.addressee_id == caller_uuid
        else friendship.addressee_id
    )
    if friendship.status == FriendshipStatus.accepted:
        for friend in service.list_friends(caller_id):
            if friend.friendship_id == friendship_id:
                return other_id, friend.display_name
    else:
        for req in service.pending_outgoing(caller_id):
            if req.friendship_id == friendship_id:
                return other_id, req.display_name
    return other_id, ANONYMOUS_DISPLAY_NAME


@router.post("/{friendship_id}/accept", response_model=FriendDTO)
def accept_friend_request(
    friendship_id: str,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[FriendService, Depends(get_friend_service)],
) -> FriendDTO:
    """Accept a pending friend request addressed to the caller.

    Builds the response by calling :meth:`~lemely.db.friend_repo.FriendService.list_friends`
    after accepting and picking the matching row, rather than teaching
    ``FriendService.accept`` to return an enriched summary itself — simpler,
    and it keeps the service's return type (:class:`~lemely.db.models.users.Friendship`)
    the same shape :meth:`~lemely.db.friend_repo.FriendService.request` already
    returns, with no divergent "accept also does XP/streak enrichment"
    special case for one caller.

    Raises:
        HTTPException: 404 for both "no such friendship" and "the caller is
            not its addressee" — deliberately the same response for both
            (see the module docstring's D5.6 §4 note below); 409 if the
            friendship exists and the caller is its addressee but it is not
            pending; 422 for a malformed ``friendship_id``.
    """
    try:
        accepted = service.accept(auth.user_id, friendship_id)
    except FriendRequestNotFoundError as exc:
        # Collapsing "no such friendship" and "you are not the addressee"
        # into one 404 is the point, not a shortcut (D5.6 §4). Distinguishing
        # them would let a caller probe for the existence of a friendship
        # between two other people by watching which error comes back.
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FriendNotPendingError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Match on the *parsed* id off the row ``accept()`` just returned, never on
    # the raw path string: ``uuid.UUID`` accepts uppercase hex, braces and a
    # ``urn:uuid:`` prefix, all of which normalise to a different string than
    # the client sent. Comparing strings would accept the request successfully
    # and then fall through to the 500 below.
    for friend in service.list_friends(auth.user_id):
        if friend.friendship_id == accepted.id:
            return _summary_to_dto(friend)
    # Unreachable in practice: accept() just succeeded, so list_friends must
    # include this row. Guards against silently returning nothing rather
    # than a 500 if that invariant is ever broken.
    raise HTTPException(status_code=500, detail="Accepted friendship not found in friends list")


@router.delete("/{friendship_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_friend(
    friendship_id: str,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    service: Annotated[FriendService, Depends(get_friend_service)],
) -> None:
    """Decline, cancel, or unfriend — all one act (D5.6 §3).

    ``FriendService.remove`` covers all three: the addressee declining a
    pending request, the requester cancelling their own pending request, and
    either accepted party unfriending. They are the identical database act
    (deleting the row), so there is one endpoint, not three.

    Raises:
        HTTPException: 404 for both "no such friendship" and "the caller is
            not one of its two parties" — deliberately the same response for
            both (D5.6 §4), same reasoning as the accept route above: a
            non-party's call must not be usable to probe whether a
            friendship exists between two other people. The row is left
            untouched in this case. 422 for a malformed ``friendship_id``.
    """
    try:
        service.remove(auth.user_id, friendship_id)
    except FriendRequestNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


__all__ = ["router"]
