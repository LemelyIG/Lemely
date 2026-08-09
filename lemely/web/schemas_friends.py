"""``/api/student/friends`` DTOs (P5.4 chunk B, D5.1/D5.6).

**Structurally answer-only (D5.1 §0).** A friend's list, like the
leaderboard, is a display-identity-plus-XP surface — MISSION §3 fixes
"leaderboards show XP (effort), never grades", and D5.6 §5 extends that
reasoning to the friends list even though it carries no ranks. So
:class:`FriendDTO` carries display identity, lifetime XP and streak — and
nothing shaped like a mark, percentage, accuracy, grade or predicted-grade.
Not "left unset": those fields do not exist on these models, so a
well-meaning future addition three years from now fails
``tests/test_schemas_friends.py``'s field-set introspection instead of
silently reaching the wire.

Mirrors :mod:`lemely.web.schemas_leaderboard`'s style exactly: an explicit
``ApiModel`` subclass per DTO, camelCase names declared directly (no alias
generator).
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - pydantic needs the real type at runtime
from typing import Literal

from lemely.web.schemas import ApiModel


class FriendDTO(ApiModel):
    """One accepted friend.

    Returned by ``GET /api/student/friends`` and
    ``POST /api/student/friends/{friendship_id}/accept``.

    ``xp``/``streak`` are ``int | None`` — this is not laziness (D5.6 §5). An
    opted-out friend stays visible in the list (removing them would make them
    unremovable) but their numbers come back ``None`` with ``optedOut=True``
    so the UI states the fact ("this friend has opted out of leaderboards")
    rather than rendering a fabricated ``0``, which UI spec §1.4 forbids.
    Never "tidy" this into ``int = 0``.
    """

    friendshipId: str
    userId: str
    displayName: str
    xp: int | None
    """Lifetime total XP (no window — S-30 asks for "XP and streak" with no
    window, unlike the weekly leaderboard). ``None`` iff ``optedOut``."""
    streak: int | None
    """Current streak length. ``None`` iff ``optedOut``."""
    optedOut: bool
    friendsSince: datetime | None
    """When the friendship was accepted. Always present for an accepted
    friendship; typed nullable only because it mirrors the underlying
    ``friendships.responded_at`` column's nullability."""


class FriendRequestDTO(ApiModel):
    """One pending — or, for a crossed request, now-accepted — friendship.

    Returned in ``incoming``/``outgoing`` on ``GET /api/student/friends`` and
    by ``POST /api/student/friends/requests``.

    No XP/streak fields: the two are not confirmed friends yet, so the
    requester's or addressee's numbers are not this caller's to see.
    """

    friendshipId: str
    userId: str
    """The *other* party — the requester for an incoming request, the
    addressee for an outgoing one."""
    displayName: str
    requestedAt: datetime
    status: Literal["pending", "accepted"]
    """The friendship's actual status after the call that produced this DTO.

    Load-bearing on ``POST /api/student/friends/requests``: because
    ``FriendService.request`` returns the *accepted* row in the
    crossed-requests case (both parties had already asked), the response
    must say so plainly rather than the client inferring "request sent" from
    a 201 alone — the caller is now friends, not merely waiting."""


class FriendsPageDTO(ApiModel):
    """``GET /api/student/friends`` response.

    Everything S-30's screen needs in one call: the caller's own friend code
    (minted on first read), their accepted friends, and both directions of
    pending request.
    """

    friendCode: str
    friends: list[FriendDTO]
    incoming: list[FriendRequestDTO]
    outgoing: list[FriendRequestDTO]


class FriendRequestCreateDTO(ApiModel):
    """``POST /api/student/friends/requests`` body."""

    friendCode: str


__all__ = [
    "FriendDTO",
    "FriendRequestCreateDTO",
    "FriendRequestDTO",
    "FriendsPageDTO",
]
