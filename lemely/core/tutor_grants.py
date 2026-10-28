"""Tutor data-grant validity (SPEC §a.2 ``tutor_data_grants``, §a.3, §e.1; ADR-T02; SC-3).

A grant is a student's consent for one tutor to read their derived analytics.
Validity is never stored: it is worked out on every read from the grant row,
the tutor's listing state and whether the pair has an active block, so a revoke,
a block or a delisting takes effect on the very next read (decision row 3b).
The repositories use the SQL mirror of :func:`grant_is_valid`, pinned to it by a
parity test.

Pure by construction: no ``lemely.db``, ``web``, ``io`` or ``app`` import, no
SQLAlchemy, no FastAPI and no clock of its own (import-linter ``forbidden``
contract, SPEC §e.1). Every instant must be timezone-aware; a naive one raises
:class:`ValueError`.

**Precedence** (:func:`grant_status`, SPEC §e.1). The first rule that applies
wins:

1. ``revoke_reason``: ``student`` -> ``revoked``, ``block`` -> ``blocked``,
   ``tutor_suspended`` -> ``tutor_suspended``, ``tutor_closed`` ->
   ``tutor_closed``. A revoked grant stays revoked whatever happens afterwards:
   reinstating a suspended tutor, or removing the block, restores nothing (CB-5);
   the student must grant again.
2. ``expired``: ``expires_at`` is set and ``now >= expires_at`` (always NULL in
   v1; the grant is valid while ``now < expires_at``).
3. ``blocked``: an active block between the two users.
4. ``tutor_unavailable``: the tutor's listing state is neither ``listed`` nor
   ``pending_review`` (CB-4). A paused tutor is still ``listed``: ``paused_at``
   is orthogonal to the listing state and is not an input here (SC-3).
5. ``active``.

**What the student and their parents read** (:func:`grant_status_for_student`,
S8, S9, S10, PA6; SPEC §i.7, §i.8, SC-11). The same status, except where it would
tell them that the tutor blocked them:

* ``blocked`` stays only when the student's own block explains it: their first
  block of this tutor fell inside the grant's life, from ``created_at`` to its
  revoke (a block's sweep revokes the live grant in the block's own transaction,
  so the two instants are equal), or to ``now`` for a live grant. Any other block
  is the tutor's, and it reads ``tutor_unavailable``, the status of a grant whose
  tutor is not listed.
* ``tutor_suspended`` and ``tutor_closed`` read ``tutor_unavailable`` too. A
  revoked grant reading ``tutor_unavailable`` could otherwise only be a tutor's
  block; with every tutor-side end of a grant (the tutor's block, a suspension, a
  close) read the same, the status and ``revokedAt`` together say only that the
  tutor ended it. The student's own revoke (``revoked``) and their own block
  (``blocked``) keep their names.

Validity is unchanged: none of these statuses is ``active``.

**Literals are written out here on purpose.** ``core`` may not import
``lemely.db``, so the revoke reasons and listing states below are pinned to
``GrantRevokeReason`` and ``TutorListingState`` in
``tests/test_tutoring_cross_pins.py`` (PLAN §1.4 #11), which also pins
:data:`GrantStatus` to the API's ``GrantStatusLit``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Literal

if TYPE_CHECKING:
    from collections.abc import Mapping

GrantStatus = Literal[
    "active",
    "revoked",
    "expired",
    "blocked",
    "tutor_suspended",
    "tutor_closed",
    "tutor_unavailable",
]
#: The statuses :func:`grant_status_for_student` can return: never a tutor-side end's name.
StudentGrantStatus = Literal["active", "revoked", "expired", "blocked", "tutor_unavailable"]


@dataclass(frozen=True, slots=True)
class GrantFacts:
    """One ``tutor_data_grants`` row plus the two facts about the tutor its validity reads.

    ``tutor_listing_state`` is ``tutor_profiles.listing_state``; ``blocked`` is
    whether an active block exists between the student and the tutor's user, in
    either direction.
    """

    created_at: datetime
    revoked_at: datetime | None
    revoke_reason: str | None
    expires_at: datetime | None
    tutor_listing_state: str
    blocked: bool


#: ``grantrevokereason`` value -> the status a grant revoked for it reads as.
_REVOKED_STATUS: Final[Mapping[str, GrantStatus]] = MappingProxyType(
    {
        "student": "revoked",
        "block": "blocked",
        "tutor_suspended": "tutor_suspended",
        "tutor_closed": "tutor_closed",
    }
)
#: Every status but ``blocked`` -> what the student and their parents read (SPEC §i.8).
_SHOWN_TO_STUDENT: Final[Mapping[GrantStatus, StudentGrantStatus]] = MappingProxyType(
    {
        "active": "active",
        "revoked": "revoked",
        "expired": "expired",
        "tutor_suspended": "tutor_unavailable",
        "tutor_closed": "tutor_unavailable",
        "tutor_unavailable": "tutor_unavailable",
    }
)
#: ``tutorlistingstate``; any other value can only come from a bug.
_LISTING_STATES: Final = frozenset(
    {"draft", "pending_review", "listed", "rejected", "suspended", "closed"}
)
#: Listing states that keep a grant valid (SC-3: re-review keeps it, paused or not).
_VALID_LISTING_STATES: Final = frozenset({"listed", "pending_review"})


def _require_aware(**instants: datetime | None) -> None:
    for name, value in instants.items():
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError(f"{name} must be a timezone-aware datetime, got naive {value!r}")


def _utc(value: datetime) -> datetime:
    """Compare instants in UTC: two datetimes sharing a zone compare by wall time, ignoring fold."""
    return value.astimezone(UTC)


def _check_facts(facts: GrantFacts, now: datetime) -> None:
    """Refuse facts the ``tutor_data_grants`` CHECKs would refuse: they can only come from a bug."""
    _require_aware(
        now=now,
        created_at=facts.created_at,
        revoked_at=facts.revoked_at,
        expires_at=facts.expires_at,
    )
    if (facts.revoked_at is None) != (facts.revoke_reason is None):
        raise ValueError(
            "revoked_at and revoke_reason must be both set or both NULL, got "
            f"{facts.revoked_at!r} and {facts.revoke_reason!r}"
        )
    if facts.revoke_reason is not None and facts.revoke_reason not in _REVOKED_STATUS:
        raise ValueError(f"unknown revoke_reason {facts.revoke_reason!r}")
    if facts.tutor_listing_state not in _LISTING_STATES:
        raise ValueError(f"unknown tutor_listing_state {facts.tutor_listing_state!r}")
    created = _utc(facts.created_at)
    if facts.expires_at is not None and _utc(facts.expires_at) <= created:
        raise ValueError("expires_at must be later than created_at")
    if facts.revoked_at is not None and _utc(facts.revoked_at) < created:
        raise ValueError("revoked_at must not be earlier than created_at")


def grant_status(facts: GrantFacts, *, now: datetime) -> GrantStatus:
    """The grant's status at ``now``, by the precedence in the module docstring.

    Raises :class:`ValueError` for a naive instant or for facts the table's
    CHECKs and enums would refuse.
    """
    _check_facts(facts, now)
    if facts.revoke_reason is not None:
        return _REVOKED_STATUS[facts.revoke_reason]
    if facts.expires_at is not None and _utc(now) >= _utc(facts.expires_at):
        return "expired"
    if facts.blocked:
        return "blocked"
    if facts.tutor_listing_state not in _VALID_LISTING_STATES:
        return "tutor_unavailable"
    return "active"


def grant_status_for_student(
    facts: GrantFacts, *, now: datetime, student_blocked_at: datetime | None
) -> StudentGrantStatus:
    """The status the student and their linked parents read (module docstring, SPEC §i.8).

    ``student_blocked_at`` is when the student first blocked the tutor's user (a lifted
    block counts; ``None`` if they never did). Every tutor-side end reads
    ``tutor_unavailable``: a ``blocked`` status the student's own block does not explain,
    ``tutor_suspended`` and ``tutor_closed``. Every other status is :func:`grant_status`.

    Raises :class:`ValueError` for a naive instant, as :func:`grant_status` does.
    """
    _require_aware(student_blocked_at=student_blocked_at)
    status = grant_status(facts, now=now)
    if status != "blocked":
        return _SHOWN_TO_STUDENT[status]
    end = facts.revoked_at if facts.revoked_at is not None else now
    if student_blocked_at is not None and (
        _utc(facts.created_at) <= _utc(student_blocked_at) <= _utc(end)
    ):
        return "blocked"
    return "tutor_unavailable"


def grant_is_valid(facts: GrantFacts, *, now: datetime) -> bool:
    """Whether the tutor may read the student's data now: the status is ``active``.

    The SQL mirror used by T19/T20/S8/PA6 is
    ``revoked_at IS NULL AND (expires_at IS NULL OR expires_at > now())``, no
    active block between the pair, and ``listing_state IN ('listed',
    'pending_review')``.
    """
    return grant_status(facts, now=now) == "active"
