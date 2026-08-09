"""Friend requests, friendships, and friend-code minting (P5.4 chunk A, D5.1).

Shape mirrors :mod:`lemely.db.xp_repo`/:mod:`lemely.db.leaderboard_repo`: a
plain ``sessionmaker`` constructor argument and an injectable clock (``now``,
defaulting to aware UTC now). This module owns the ``friendships`` table and
``users.friend_code`` (migration ``0015``); the friends *leaderboard* scope
itself lives in :mod:`lemely.db.leaderboard_repo` (it reads ``friendships``
directly rather than calling into this service, mirroring how that module
already reads ``ClassEnrollment``/``Seat`` directly instead of going through
a class/seat service).

**Structural uniqueness, not caller discipline (D5.1 §8 applied a second
time).** ``friendships`` stores a friendship in one direction of record
(``requester_id``/``addressee_id``) plus a derived, order-independent pair
(``pair_low``/``pair_high``), with a unique index on the pair and three
``CHECK`` constraints pinning the pair to the parties — see migration
``0015`` and :class:`~lemely.db.models.users.Friendship` for the full
reasoning (Postgres cannot index ``LEAST()``/``GREATEST()``, so the pair is
materialized instead of derived). This module never relies on "we only ever
insert in one order" as a guarantee; the reciprocal insert a race could
produce is a rejected ``IntegrityError`` at the database, and
:meth:`FriendService.request` handles the *legitimate* crossed-requests case
(both parties pressed "add" before either saw the other's request) by
accepting the existing reverse-pending row rather than attempting — and
failing — a second insert.

**Existence oracle avoidance (mirrors ``LeaderboardClassAccessError``).**
:meth:`FriendService.accept` and :meth:`FriendService.remove` both raise the
same :class:`FriendRequestNotFoundError` whether the ``friendship_id`` does
not exist at all, or exists but the caller is not a party to it. A caller who
is not the addressee of a pending request must not be able to distinguish
"no such friendship" from "a friendship exists between two other people" by
watching which error comes back.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import case, func, or_, select
from sqlalchemy.exc import IntegrityError

from lemely.db.leaderboard_repo import ANONYMOUS_DISPLAY_NAME
from lemely.db.models.engagement import Streak, XpEvent
from lemely.db.models.enums import FriendshipStatus, Role
from lemely.db.models.profiles import StudentProfile
from lemely.db.models.users import Friendship, User

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from sqlalchemy.engine import Row
    from sqlalchemy.orm import Session, sessionmaker

#: Friend-code alphabet: uppercase A-Z + digits 2-9, minus the visually
#: ambiguous set (0/O, 1/I/L) — a code is meant to be read aloud or typed
#: from a screenshot, and those pairs are exactly where transcription fails.
_FRIEND_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_FRIEND_CODE_LENGTH = 8

#: Bounded retry on a unique-constraint collision when minting a code
#: (:meth:`FriendService.friend_code_for`). 8 characters from a 32-symbol
#: alphabet is ~2^40 of space; a collision is already vanishingly unlikely,
#: this bound exists only so a pathological run fails loudly instead of
#: looping.
_MAX_CODE_ATTEMPTS = 5

#: The Postgres constraint name migration ``0015`` creates on
#: ``users.friend_code``. Only an ``IntegrityError`` naming exactly this
#: constraint is treated as a collision worth retrying.
_FRIEND_CODE_CONSTRAINT_NAME = "uq_users_friend_code"


def _utcnow() -> datetime:
    """Default clock: aware UTC now. Production wiring only — tests inject their own."""
    return datetime.now(UTC)


def _generate_friend_code() -> str:
    """Draw one candidate 8-character code from :data:`_FRIEND_CODE_ALPHABET`.

    Uses :func:`secrets.choice`, never the :mod:`random` module — a friend
    code is a lookup key handed to strangers, and :mod:`random` is not
    cryptographically unpredictable.
    """
    return "".join(secrets.choice(_FRIEND_CODE_ALPHABET) for _ in range(_FRIEND_CODE_LENGTH))


def _is_friend_code_violation(exc: IntegrityError) -> bool:
    """``True`` only for a violation of ``uq_users_friend_code``.

    Any other integrity error must keep propagating — mirrors
    ``lemely.db.xp_repo._is_dedupe_violation``'s reasoning exactly.
    """
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    constraint_name = getattr(diag, "constraint_name", None)
    return constraint_name == _FRIEND_CODE_CONSTRAINT_NAME


class FriendError(Exception):
    """Base class for friend-service failures."""


class FriendUserNotFoundError(FriendError):
    """No user exists for the supplied id (→ 404)."""


class FriendIneligibleUserError(FriendError):
    """The user exists but is not a student (→ 403-shaped; D5.1 §10)."""


class FriendCodeNotFoundError(FriendError):
    """No user holds the supplied friend code."""


class FriendSelfRequestError(FriendError):
    """A user supplied their own friend code."""


class FriendAlreadyExistsError(FriendError):
    """An accepted friendship, or the caller's own outgoing pending request, already exists."""


class FriendRequestNotFoundError(FriendError):
    """No such friendship, or the caller is not a party to it.

    Deliberately the single error for both cases — see the module
    docstring's "existence oracle avoidance" note.
    """


class FriendNotPendingError(FriendError):
    """The friendship exists and the caller is a party, but it is not ``pending``."""


@dataclass(frozen=True, slots=True)
class FriendSummary:
    """One accepted friend, as returned by :meth:`FriendService.list_friends`."""

    friendship_id: uuid.UUID
    user_id: uuid.UUID
    display_name: str
    xp: int | None
    """Lifetime total XP (all ``xp_events``, no window — S-30 asks for "XP
    and streak" with no window, unlike S-29's weekly board). ``None`` iff
    ``opted_out`` — see the class docstring's opt-out note on
    :meth:`FriendService.list_friends`."""
    streak: int | None
    """``streaks.current_length``. ``None`` iff ``opted_out``."""
    opted_out: bool
    friends_since: datetime | None
    """When the friendship was accepted (``friendships.responded_at``)."""


@dataclass(frozen=True, slots=True)
class FriendRequestSummary:
    """One pending request, as returned by ``pending_incoming``/``pending_outgoing``.

    No XP/streak fields: the two are not friends yet, so the requester's or
    addressee's numbers are not this caller's to see.
    """

    friendship_id: uuid.UUID
    user_id: uuid.UUID
    """The *other* party — the requester for an incoming request, the
    addressee for an outgoing one."""
    display_name: str
    requested_at: datetime


class FriendService:
    """Manage friend codes, friend requests, and accepted friendships (D5.1).

    Constructed with a ``sessionmaker`` and an injectable clock, mirroring
    :class:`~lemely.db.xp_repo.XpService` and
    :class:`~lemely.db.leaderboard_repo.LeaderboardService`.
    """

    def __init__(
        self,
        sessionmaker: sessionmaker[Session],
        *,
        now: Callable[[], datetime] = _utcnow,
    ) -> None:
        """Wire the service to a session factory and a clock."""
        self._sessionmaker = sessionmaker
        self._now = now

    # -- Friend codes ---------------------------------------------------------

    def friend_code_for(self, user_id: uuid.UUID | str) -> str:
        """Return ``user_id``'s friend code, minting one on first call.

        Idempotent: a second call for the same user returns the same code
        (the column is only ever written once — see the retry loop below,
        which returns immediately once a candidate is persisted without
        collision).

        Args:
            user_id: The student the code identifies. Must resolve to a
                ``users`` row with ``role=Role.student`` — a friend code is a
                student-only surface (D5.1 §10), same as everything else in
                this module.

        Raises:
            FriendUserNotFoundError: no user exists for ``user_id``.
            FriendIneligibleUserError: the user exists but is not a student.
            FriendError: no unique code could be minted after
                :data:`_MAX_CODE_ATTEMPTS` collisions — vanishingly unlikely
                given the alphabet size, but reported rather than looped
                forever.
        """
        student_uuid = _as_uuid(user_id)
        with self._sessionmaker() as session, session.begin():
            user = session.get(User, student_uuid)
            if user is None:
                raise FriendUserNotFoundError(f"Unknown user: {student_uuid}")
            if user.role != Role.student:
                raise FriendIneligibleUserError(
                    f"User {student_uuid} has role={user.role!r}; "
                    "friend codes are student-only (D5.1 §10)"
                )
            if user.friend_code:
                return user.friend_code

            last_exc: IntegrityError | None = None
            for _ in range(_MAX_CODE_ATTEMPTS):
                candidate = _generate_friend_code()
                try:
                    with session.begin_nested():
                        user.friend_code = candidate
                        session.flush()
                    return candidate
                except IntegrityError as exc:
                    if not _is_friend_code_violation(exc):
                        raise
                    last_exc = exc
                    continue

            raise FriendError(
                f"Could not mint a unique friend code for {student_uuid} "
                f"after {_MAX_CODE_ATTEMPTS} attempts"
            ) from last_exc

    # -- Requesting / accepting -------------------------------------------------

    def request(self, requester_id: uuid.UUID | str, friend_code: str) -> Friendship:
        """Send a friend request from ``requester_id`` to the holder of ``friend_code``.

        **Crossed requests resolve to one accepted friendship, never two rows
        or an error.** If the target already has an outstanding pending
        request addressed to the caller (both people pressed "add" before
        seeing the other's request), this call accepts that existing row
        instead of attempting a second insert — which
        ``uq_friendships_pair`` would reject anyway. Two people who both ask
        to be friends must end up friends, not deadlocked on whoever calls
        the API second.

        Args:
            requester_id: The student sending the request. Must be a student
                (D5.1 §10).
            friend_code: The target's code (see :meth:`friend_code_for`).
                Only ever resolves to a student, since only students are ever
                issued a code.

        Raises:
            FriendUserNotFoundError: no user exists for ``requester_id``.
            FriendIneligibleUserError: ``requester_id`` exists but is not a
                student.
            FriendCodeNotFoundError: no user holds ``friend_code``.
            FriendSelfRequestError: ``friend_code`` is the caller's own code.
            FriendAlreadyExistsError: the pair is already friends, or the
                caller already has an outgoing pending request to this
                target.
        """
        requester_uuid = _as_uuid(requester_id)
        with self._sessionmaker() as session, session.begin():
            requester = session.get(User, requester_uuid)
            if requester is None:
                raise FriendUserNotFoundError(f"Unknown user: {requester_uuid}")
            if requester.role != Role.student:
                raise FriendIneligibleUserError(
                    f"User {requester_uuid} has role={requester.role!r}; "
                    "friend requests are student-only (D5.1 §10)"
                )

            target = session.scalar(select(User).where(User.friend_code == friend_code))
            if target is None:
                raise FriendCodeNotFoundError(f"No user holds friend code {friend_code!r}")
            if target.id == requester_uuid:
                raise FriendSelfRequestError("A user cannot friend themselves")

            pair_low, pair_high = _ordered_pair(requester_uuid, target.id)
            existing = session.scalar(
                select(Friendship).where(
                    Friendship.pair_low == pair_low, Friendship.pair_high == pair_high
                )
            )
            if existing is not None:
                if existing.status == FriendshipStatus.accepted:
                    raise FriendAlreadyExistsError(
                        f"{requester_uuid} and {target.id} are already friends"
                    )
                # Pending. If the caller is the existing row's requester,
                # this is a duplicate of their own outstanding ask.
                if existing.requester_id == requester_uuid:
                    raise FriendAlreadyExistsError(
                        f"{requester_uuid} already has a pending request to {target.id}"
                    )
                # Reverse pending: the target already asked the caller.
                # Accept it rather than erroring or inserting a second row.
                existing.status = FriendshipStatus.accepted
                existing.responded_at = self._now()
                session.flush()
                return existing

            friendship = Friendship(
                requester_id=requester_uuid,
                addressee_id=target.id,
                status=FriendshipStatus.pending,
                pair_low=pair_low,
                pair_high=pair_high,
            )
            session.add(friendship)
            session.flush()
            return friendship

    def accept(self, user_id: uuid.UUID | str, friendship_id: uuid.UUID | str) -> Friendship:
        """Accept a pending friend request. Only the addressee may call this.

        The requester attempting to accept their own request raises
        :class:`FriendRequestNotFoundError` — the same error a total
        stranger gets — rather than a distinct "you can't accept your own
        request" error, so the response never confirms that a row the caller
        is not the addressee of exists (see the module docstring).

        Raises:
            FriendRequestNotFoundError: no such friendship, or ``user_id`` is
                not its addressee.
            FriendNotPendingError: the friendship exists and ``user_id`` is
                its addressee, but it is already accepted.
        """
        user_uuid = _as_uuid(user_id)
        friendship_uuid = _as_uuid(friendship_id)
        with self._sessionmaker() as session, session.begin():
            friendship = session.get(Friendship, friendship_uuid)
            if friendship is None or friendship.addressee_id != user_uuid:
                raise FriendRequestNotFoundError(
                    f"No pending friend request {friendship_uuid} addressed to {user_uuid}"
                )
            if friendship.status != FriendshipStatus.pending:
                raise FriendNotPendingError(f"Friendship {friendship_uuid} is not pending")
            friendship.status = FriendshipStatus.accepted
            friendship.responded_at = self._now()
            session.flush()
            return friendship

    def remove(self, user_id: uuid.UUID | str, friendship_id: uuid.UUID | str) -> None:
        """Delete a friendship row, whatever state it is in.

        **One method covers decline (addressee, pending), cancel (requester,
        pending) and unfriend (either party, accepted)** because all three
        are the same database act — deleting the row — and separate
        endpoints would only ever differ in which word the error message
        used. Any party to the friendship may call this in any status.

        A removed friendship leaves no tombstone: the row is gone, not
        soft-deleted, so the pair is free to send a fresh request later (the
        unique pair index has nothing left to collide with).

        Raises:
            FriendRequestNotFoundError: no such friendship, or ``user_id`` is
                not one of its two parties. The row is left untouched in
                this case — a non-party's call has no effect beyond the
                error, never a side effect a caller could use to probe
                whether a friendship exists between two other people.
        """
        user_uuid = _as_uuid(user_id)
        friendship_uuid = _as_uuid(friendship_id)
        with self._sessionmaker() as session, session.begin():
            friendship = session.get(Friendship, friendship_uuid)
            if friendship is None or user_uuid not in (
                friendship.requester_id,
                friendship.addressee_id,
            ):
                raise FriendRequestNotFoundError(
                    f"No friendship {friendship_uuid} involving {user_uuid}"
                )
            session.delete(friendship)

    # -- Reading ----------------------------------------------------------------

    def list_friends(self, user_id: uuid.UUID | str) -> list[FriendSummary]:
        """All of ``user_id``'s accepted friends, with lifetime XP and streak.

        **Opt-out handling.** D5.1 §9 says an opted-out student is absent
        from every *board*, including boards their friends see — but a
        friends list is not a board. It carries no ranks, and the
        relationship is mutual and consented to by both parties (unlike a
        leaderboard, which shows a student to classmates who never opted
        into being compared with them). Removing an opted-out friend from
        this list would also make them unremovable — a friendship the caller
        cannot see is a friendship they cannot end via
        :meth:`remove`. So an opted-out friend **stays in the list**, but
        their ``xp``/``streak`` come back as ``None`` with ``opted_out=True``
        rather than a real number, so the UI can state the fact ("this
        friend has opted out of leaderboards") instead of rendering a
        fabricated ``0`` — UI spec §1.4 forbids inventing precision. They
        remain excluded from the *friends leaderboard* by
        ``lemely.db.leaderboard_repo``'s existing opt-out ``WHERE`` clause,
        unaffected by this method.

        Never selects ``users.email`` — a friend with no ``display_name``
        set renders as
        :data:`~lemely.db.leaderboard_repo.ANONYMOUS_DISPLAY_NAME`, exactly
        as an unnamed student does on a leaderboard (D5.5). A friends list is
        if anything a wider audience than one class, so the same leak this
        product already closed on the leaderboard must stay closed here.
        """
        user_uuid = _as_uuid(user_id)
        other_id = case(
            (Friendship.requester_id == user_uuid, Friendship.addressee_id),
            else_=Friendship.requester_id,
        )
        with self._sessionmaker() as session:
            rows = session.execute(
                select(
                    Friendship.id.label("friendship_id"),
                    other_id.label("other_id"),
                    Friendship.responded_at,
                )
                .where(
                    Friendship.status == FriendshipStatus.accepted,
                    or_(Friendship.requester_id == user_uuid, Friendship.addressee_id == user_uuid),
                )
                .order_by(Friendship.responded_at)
            ).all()
            if not rows:
                return []

            other_ids = [row.other_id for row in rows]
            users_by_id = {
                u.id: u for u in session.scalars(select(User).where(User.id.in_(other_ids)))
            }
            opted_out_by_id: dict[uuid.UUID, bool] = {
                r.user_id: bool(r.leaderboard_opt_out)
                for r in session.execute(
                    select(StudentProfile.user_id, StudentProfile.leaderboard_opt_out).where(
                        StudentProfile.user_id.in_(other_ids)
                    )
                )
            }
            xp_by_id: dict[uuid.UUID, int] = {
                r.user_id: int(r[1] or 0)
                for r in session.execute(
                    select(XpEvent.user_id, func.sum(XpEvent.amount))
                    .where(XpEvent.user_id.in_(other_ids))
                    .group_by(XpEvent.user_id)
                )
            }
            streak_by_id: dict[uuid.UUID, int] = {
                r.user_id: int(r.current_length)
                for r in session.execute(
                    select(Streak.user_id, Streak.current_length).where(
                        Streak.user_id.in_(other_ids)
                    )
                )
            }

        summaries: list[FriendSummary] = []
        for row in rows:
            other_user = users_by_id.get(row.other_id)
            display_name = (other_user.display_name if other_user else None) or (
                ANONYMOUS_DISPLAY_NAME
            )
            opted_out = bool(opted_out_by_id.get(row.other_id, False))
            if opted_out:
                xp: int | None = None
                streak: int | None = None
            else:
                xp = int(xp_by_id.get(row.other_id) or 0)
                streak = int(streak_by_id.get(row.other_id, 0))
            summaries.append(
                FriendSummary(
                    friendship_id=row.friendship_id,
                    user_id=row.other_id,
                    display_name=display_name,
                    xp=xp,
                    streak=streak,
                    opted_out=opted_out,
                    friends_since=row.responded_at,
                )
            )
        return summaries

    def pending_incoming(self, user_id: uuid.UUID | str) -> list[FriendRequestSummary]:
        """Pending requests addressed to ``user_id`` (awaiting their decision).

        No XP/streak — the two are not friends yet.
        """
        user_uuid = _as_uuid(user_id)
        with self._sessionmaker() as session:
            rows = session.execute(
                select(Friendship.id, Friendship.requester_id, Friendship.created_at)
                .where(
                    Friendship.addressee_id == user_uuid,
                    Friendship.status == FriendshipStatus.pending,
                )
                .order_by(Friendship.created_at)
            ).all()
            return self._to_request_summaries(session, rows)

    def pending_outgoing(self, user_id: uuid.UUID | str) -> list[FriendRequestSummary]:
        """Pending requests ``user_id`` sent, awaiting the other side's decision.

        No XP/streak — the two are not friends yet.
        """
        user_uuid = _as_uuid(user_id)
        with self._sessionmaker() as session:
            rows = session.execute(
                select(Friendship.id, Friendship.addressee_id, Friendship.created_at)
                .where(
                    Friendship.requester_id == user_uuid,
                    Friendship.status == FriendshipStatus.pending,
                )
                .order_by(Friendship.created_at)
            ).all()
            return self._to_request_summaries(session, rows)

    @staticmethod
    def _to_request_summaries(
        session: Session, rows: Sequence[Row[tuple[uuid.UUID, uuid.UUID, datetime]]]
    ) -> list[FriendRequestSummary]:
        """Resolve display names for a batch of (friendship_id, other_id, requested_at) rows."""
        if not rows:
            return []
        other_ids = [row[1] for row in rows]
        name_stmt = select(User.id, User.display_name).where(User.id.in_(other_ids))
        names_by_id: dict[uuid.UUID, str | None] = {
            r.id: r.display_name for r in session.execute(name_stmt)
        }
        return [
            FriendRequestSummary(
                friendship_id=row[0],
                user_id=row[1],
                display_name=names_by_id.get(row[1]) or ANONYMOUS_DISPLAY_NAME,
                requested_at=row[2],
            )
            for row in rows
        ]

    def friend_ids(self, user_id: uuid.UUID | str) -> list[uuid.UUID]:
        """Accepted counterparty ids for ``user_id`` — feeds the leaderboard's ``friends`` scope.

        Deliberately unfiltered by opt-out: D5.1 §9's opt-out guarantee is
        enforced in ``lemely.db.leaderboard_repo``'s ranking query WHERE
        clause, not here — this method only answers "who is this user
        friends with", the same question :meth:`list_friends` answers, just
        without the display/XP/streak enrichment.
        """
        user_uuid = _as_uuid(user_id)
        other_id = case(
            (Friendship.requester_id == user_uuid, Friendship.addressee_id),
            else_=Friendship.requester_id,
        )
        with self._sessionmaker() as session:
            ids = session.scalars(
                select(other_id).where(
                    Friendship.status == FriendshipStatus.accepted,
                    or_(
                        Friendship.requester_id == user_uuid,
                        Friendship.addressee_id == user_uuid,
                    ),
                )
            ).all()
        return list(ids)


def _ordered_pair(a: uuid.UUID, b: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    """Sort ``(a, b)`` so the first element is the smaller (``pair_low``/``pair_high``)."""
    return (a, b) if a < b else (b, a)


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    """Coerce a str/UUID to :class:`uuid.UUID`, raising ``ValueError`` if invalid."""
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Identifier must be a UUID, got {value!r}") from exc


__all__ = [
    "FriendAlreadyExistsError",
    "FriendCodeNotFoundError",
    "FriendError",
    "FriendIneligibleUserError",
    "FriendNotPendingError",
    "FriendRequestNotFoundError",
    "FriendRequestSummary",
    "FriendSelfRequestError",
    "FriendService",
    "FriendSummary",
    "FriendUserNotFoundError",
]
