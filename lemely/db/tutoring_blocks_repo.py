"""Blocks between a student and a tutor: B1, B2, B3 (SPEC §a.2 ``tutoring_blocks``, §b.2, §i.8).

The single writer of ``tutoring_blocks`` (``tests/test_tutoring_predicates_single_source.py``
allows this module and :mod:`lemely.db.tutoring_sweeps`; every read elsewhere goes through
:mod:`lemely.db.tutoring_predicates`). Blocks are keyed on ``users.id`` both ways; the caller
names the counterpart by the id their role knows (SC-19, O28): a student by the tutor's profile
id, a tutor by the student's id.

**Rows are never deleted.** A lift (B3) sets ``removed_at``; a renewal (B2 on a lifted row)
clears it and keeps ``created_at``, the first block, which the outcome exclusion and its hold
read (ADR-T04). ``updated_at`` is the instant the row last became active (SPEC §i.8,
``tutoring_predicates.active_block_since_sql``): the INSERT takes the server default ``now()``,
in the same transaction as the sweep; a lift and a renewal set ``updated_at = now()`` themselves
(raw SQL skips the ORM ``onupdate``). **A block request on a row that is already active writes
nothing** (the upsert's ``DO UPDATE ... WHERE tutoring_blocks.removed_at IS NOT NULL`` matches no
row): a repeated press after the note window closed must not move ``blocked_since`` and switch
the tutor's ``notesFrozen`` off while the block stands. A lift of a lifted row writes nothing
either.

**Who may block whom (O13).** A student may block a tutor profile that is listed and not paused
(the directory's own predicate), or one the student has a booking or a grant with in any state,
or one the student has blocked before. A tutor may block only a student who has a booking (by
the student or a parent) or a grant with them, in any state. Neither rule reads the other side's
block, so no answer tells the caller that they were blocked (SC-11). Anything else is 404 with
the body the caller would get for an unknown id; for a student that is SP2's (PP-6).

**B2, one transaction (SPEC §a.4b "Block (B2)").** The tutor row ``FOR UPDATE``
(``tutoring_sweeps.lock_tutor_for_sweep``); for a tutor caller the 409 ``tutor_suspended`` /
``tutor_closed`` (CB-7, read under that lock); the O13 check; both ``users`` rows
``FOR KEY SHARE`` in id order (the block row references them; SPEC §i.7); the pair lock; the
upsert; and, when the row became active, ``TutoringSweeps.sweep_block_in_session``. B3 takes the
tutor row and the pair lock the same way, so a lift and a block of one pair never interleave.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Final, Literal

import sqlalchemy as sa

from lemely.core.tutor_directory import public_name, student_label
from lemely.db.booking_repo import lock_pair_in_session
from lemely.db.models.enums import TutorListingState
from lemely.db.tutoring_predicates import listed_and_not_paused_sql
from lemely.db.tutoring_sweeps import (
    LockedTutor,
    SweepResult,
    TutoringSweeps,
    lock_tutor_for_sweep,
    lock_users_for_insert,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

BlockerParty = Literal["student", "tutor"]

#: The upsert of SPEC §i.8: a new row, or a lifted row made active again; never a write to a row
#: that is already active.
_UPSERT_SQL: Final = (
    "INSERT INTO tutoring_blocks (blocker_user_id, blocked_user_id) VALUES (:blocker, :blocked) "
    "ON CONFLICT (blocker_user_id, blocked_user_id) DO UPDATE "
    "SET removed_at = NULL, updated_at = now() WHERE tutoring_blocks.removed_at IS NOT NULL "
    "RETURNING updated_at"
)

#: O13 for a student caller, over ``tutor_profiles tp`` (``:student_id`` is the caller).
_STUDENT_MAY_BLOCK_SQL: Final = (
    f"({listed_and_not_paused_sql('tp')} "  # noqa: S608 - a constant fragment, no caller text
    "OR EXISTS (SELECT 1 FROM tutor_bookings b WHERE b.tutor_profile_id = tp.id "
    "AND b.student_id = :student_id) "
    "OR EXISTS (SELECT 1 FROM tutor_data_grants g WHERE g.tutor_profile_id = tp.id "
    "AND g.student_id = :student_id) "
    "OR EXISTS (SELECT 1 FROM tutoring_blocks k WHERE k.blocker_user_id = :student_id "
    "AND k.blocked_user_id = tp.user_id))"
)

#: O13 for a tutor caller: a student who booked (or was booked for) or granted this tutor.
_TUTOR_MAY_BLOCK_SQL: Final = (
    "SELECT u.display_name FROM users u WHERE u.id = :student_id AND u.role = 'student' "
    "AND (EXISTS (SELECT 1 FROM tutor_bookings b WHERE b.tutor_profile_id = :tutor_profile_id "
    "AND b.student_id = u.id) "
    "OR EXISTS (SELECT 1 FROM tutor_data_grants g WHERE g.tutor_profile_id = :tutor_profile_id "
    "AND g.student_id = u.id))"
)

_INACTIVE: Final = {
    TutorListingState.suspended: ("tutor_suspended", "Your tutor profile is suspended."),
    TutorListingState.closed: ("tutor_closed", "Your tutor profile is closed."),
}


class BlockError(Exception):
    """A refusal the route sends as ``tutoring_error(status, code, message)``."""

    code: str = "block_error"
    status: int = 409

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotBlockable(BlockError):
    """The counterpart is not one the caller may block (O13), or does not exist (404)."""

    code = "not_found"
    status = 404


class NoBlockRow(BlockError):
    """B3: the caller has no block row for this counterpart (O28, 404)."""

    code = "not_found"
    status = 404


class TutorInactive(BlockError):
    """B2 by a suspended or closed tutor (409 ``tutor_suspended`` / ``tutor_closed``, CB-7)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class BlockCaller:
    """Who calls B1-B3: a student, or a tutor with their own profile id.

    The route resolves ``tutor_profile_id`` from ``auth.user_id`` (O1); no caller sends it.
    """

    user_id: uuid.UUID
    party: BlockerParty
    tutor_profile_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class BlockView:
    """One of the caller's active blocks, named for the caller (``BlockDTO``).

    ``counterpart_id`` is the tutor's profile id for a student, the student's id for a tutor;
    ``display_name`` the tutor's public name or ``student_label``; ``active_since`` the row's
    ``updated_at``, the instant this block last became active.
    """

    counterpart_id: uuid.UUID
    display_name: str
    active_since: datetime


@dataclass(frozen=True, slots=True)
class BlockOutcome:
    """B2's result: ``created`` is false when the block was already active (nothing written)."""

    created: bool
    block: BlockView
    sweep: SweepResult | None


@dataclass(frozen=True, slots=True)
class _Pair:
    """The pair a B2 or B3 call names, resolved and locked."""

    tutor: LockedTutor
    student_id: uuid.UUID
    blocker_user_id: uuid.UUID
    blocked_user_id: uuid.UUID
    counterpart_id: uuid.UUID
    display_name: str


def _as_uuid(value: object) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _instant(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"expected a datetime, got {value!r}")
    return value


class TutoringBlocksRepository:
    """The caller's blocks over one ``sessionmaker``."""

    def __init__(
        self, sessionmaker: sessionmaker[Session], *, sweeps: TutoringSweeps | None = None
    ) -> None:
        """Wire the repository to a session factory and the sweeps a new block runs."""
        self._sessionmaker = sessionmaker
        self._sweeps = sweeps if sweeps is not None else TutoringSweeps(sessionmaker)

    # -- B1 -------------------------------------------------------------------

    def active_blocks(self, caller: BlockCaller) -> list[BlockView]:
        """B1: the caller's active blocks, the most recently made first (one statement)."""
        if caller.party == "student":
            statement = (
                "SELECT tp.id AS counterpart_id, tp.public_first_name, tp.public_last_initial, "
                "NULL AS display_name, k.updated_at FROM tutoring_blocks k "
                "JOIN tutor_profiles tp ON tp.user_id = k.blocked_user_id "
                "WHERE k.blocker_user_id = :caller AND k.removed_at IS NULL "
                "ORDER BY k.updated_at DESC, tp.id"
            )
        else:
            statement = (
                "SELECT u.id AS counterpart_id, NULL AS public_first_name, "
                "NULL AS public_last_initial, u.display_name, k.updated_at "
                "FROM tutoring_blocks k JOIN users u ON u.id = k.blocked_user_id "
                "WHERE k.blocker_user_id = :caller AND k.removed_at IS NULL "
                "ORDER BY k.updated_at DESC, u.id"
            )
        with self._sessionmaker() as session:
            rows = session.execute(sa.text(statement), {"caller": caller.user_id}).all()
        views: list[BlockView] = []
        for row in rows:
            counterpart = _as_uuid(row.counterpart_id)
            if caller.party == "student":
                name = public_name(str(row.public_first_name), row.public_last_initial)
            else:
                name = student_label(row.display_name, counterpart)
            views.append(
                BlockView(
                    counterpart_id=counterpart,
                    display_name=name,
                    active_since=_instant(row.updated_at),
                )
            )
        return views

    # -- B2 -------------------------------------------------------------------

    def block(self, caller: BlockCaller, counterpart_id: uuid.UUID) -> BlockOutcome:
        """B2 in one transaction: see :meth:`block_in_session`."""
        with self._sessionmaker.begin() as session:
            return self.block_in_session(session, caller, counterpart_id)

    def block_in_session(
        self, session: Session, caller: BlockCaller, counterpart_id: uuid.UUID
    ) -> BlockOutcome:
        """B2's body in the caller's transaction (module docstring for the order of steps).

        Raises :class:`NotBlockable` (O13) or :class:`TutorInactive`; a refusal writes nothing.
        On an already active row, returns it with ``created=False`` and ``sweep=None``, having
        written nothing.
        """
        resolved = self._resolve(session, caller, counterpart_id, for_block=True)
        lock_users_for_insert(session, [resolved.blocker_user_id, resolved.blocked_user_id])
        lock_pair_in_session(
            session, student_id=resolved.student_id, tutor_profile_id=resolved.tutor.profile_id
        )
        written = session.execute(
            sa.text(_UPSERT_SQL),
            {"blocker": resolved.blocker_user_id, "blocked": resolved.blocked_user_id},
        ).first()
        if written is None:
            existing = session.execute(
                sa.text(
                    "SELECT updated_at FROM tutoring_blocks "
                    "WHERE blocker_user_id = :blocker AND blocked_user_id = :blocked"
                ),
                {"blocker": resolved.blocker_user_id, "blocked": resolved.blocked_user_id},
            ).scalar_one()
            return BlockOutcome(created=False, block=self._view(resolved, existing), sweep=None)
        sweep = self._sweeps.sweep_block_in_session(
            session,
            student_id=resolved.student_id,
            tutor_profile_id=resolved.tutor.profile_id,
            actor_user_id=caller.user_id,
        )
        return BlockOutcome(created=True, block=self._view(resolved, written[0]), sweep=sweep)

    # -- B3 -------------------------------------------------------------------

    def unblock(self, caller: BlockCaller, counterpart_id: uuid.UUID) -> bool:
        """B3: lift the caller's block of the counterpart; restores nothing (SPEC §b.2).

        ``True`` when this call lifted an active block, ``False`` when the caller's row was
        already lifted (nothing written). Raises :class:`NoBlockRow` when the caller has no row
        for that counterpart, whoever else may have one (O28).
        """
        with self._sessionmaker.begin() as session:
            try:
                resolved = self._resolve(session, caller, counterpart_id, for_block=False)
            except NotBlockable as exc:
                raise NoBlockRow("Block not found.") from exc
            lock_pair_in_session(
                session,
                student_id=resolved.student_id,
                tutor_profile_id=resolved.tutor.profile_id,
            )
            found = session.execute(
                sa.text(
                    "SELECT removed_at FROM tutoring_blocks WHERE blocker_user_id = :blocker "
                    "AND blocked_user_id = :blocked FOR UPDATE"
                ),
                {"blocker": resolved.blocker_user_id, "blocked": resolved.blocked_user_id},
            ).first()
            if found is None:
                raise NoBlockRow("Block not found.")
            if found[0] is not None:
                return False
            session.execute(
                sa.text(
                    "UPDATE tutoring_blocks SET removed_at = now(), updated_at = now() "
                    "WHERE blocker_user_id = :blocker AND blocked_user_id = :blocked "
                    "AND removed_at IS NULL"
                ),
                {"blocker": resolved.blocker_user_id, "blocked": resolved.blocked_user_id},
            )
            return True

    # -- Resolution (O13, O28) ----------------------------------------------

    def _resolve(
        self, session: Session, caller: BlockCaller, counterpart_id: uuid.UUID, *, for_block: bool
    ) -> _Pair:
        """Lock the tutor row and name the pair; for B2 also apply CB-7 and O13."""
        if caller.party == "student":
            tutor = lock_tutor_for_sweep(session, counterpart_id)
            if tutor is None:
                raise NotBlockable("Tutor not found.")
            if for_block:
                allowed = session.execute(
                    sa.text(
                        f"SELECT {_STUDENT_MAY_BLOCK_SQL} FROM tutor_profiles tp "  # noqa: S608 - constant
                        "WHERE tp.id = :tutor_profile_id"
                    ),
                    {"tutor_profile_id": tutor.profile_id, "student_id": caller.user_id},
                ).scalar_one()
                if not allowed:
                    raise NotBlockable("Tutor not found.")
            return _Pair(
                tutor=tutor,
                student_id=caller.user_id,
                blocker_user_id=caller.user_id,
                blocked_user_id=tutor.user_id,
                counterpart_id=tutor.profile_id,
                display_name=tutor.public_name,
            )
        if caller.tutor_profile_id is None:
            raise ValueError("a tutor caller needs their own tutor profile id")
        tutor = lock_tutor_for_sweep(session, caller.tutor_profile_id)
        if tutor is None or tutor.user_id != caller.user_id:
            raise ValueError("the tutor caller's profile does not belong to them")
        if for_block and tutor.listing_state in _INACTIVE:
            code, message = _INACTIVE[tutor.listing_state]
            raise TutorInactive(code, message)
        found = session.execute(
            sa.text(_TUTOR_MAY_BLOCK_SQL),
            {"student_id": counterpart_id, "tutor_profile_id": tutor.profile_id},
        ).first()
        if found is None:
            raise NotBlockable("Student not found.")
        return _Pair(
            tutor=tutor,
            student_id=counterpart_id,
            blocker_user_id=tutor.user_id,
            blocked_user_id=counterpart_id,
            counterpart_id=counterpart_id,
            display_name=student_label(found[0], counterpart_id),
        )

    @staticmethod
    def _view(resolved: _Pair, active_since: object) -> BlockView:
        return BlockView(
            counterpart_id=resolved.counterpart_id,
            display_name=resolved.display_name,
            active_since=_instant(active_since),
        )


__all__ = [
    "BlockCaller",
    "BlockError",
    "BlockOutcome",
    "BlockView",
    "BlockerParty",
    "NoBlockRow",
    "NotBlockable",
    "TutorInactive",
    "TutoringBlocksRepository",
]
