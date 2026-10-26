"""The safeguarding sweeps: a block, a suspension and a close (SPEC §a.2, §a.3, §a.4b).

Each sweep runs inside its caller's transaction and writes nothing a rollback would not undo
(D5.9 §1). The router sends the inbox notices after the commit, built from the
:class:`SweepResult` returned here; the only email rows are queued inside the transaction (the
cancellations through ``BookingService``, the tutor's listing decision here), so they commit or
roll back with the change (SPEC §b.4 point 1).

**A block** (SPEC §a.2 ``tutoring_blocks``, row 15a). After the block row is written (by
:mod:`lemely.db.tutoring_blocks_repo`, in the same transaction and so with the same ``now()``,
SPEC §i.8), :meth:`TutoringSweeps.sweep_block_in_session`:

1. cancels the pair's active sessions not yet started, inside the 24-hour window too
   (``BookingService.cancel_future_for_pair_in_session``: party ``system``, the fixed reason,
   every party and linked parent emailed except the blocker);
2. revokes the pair's live grant (``tutor_grant_repo.revoke_live_in_session``, reason
   ``block``; the reason does not say which side blocked, SPEC §i.8 residual (d));
3. removes the student from every school-less class the tutor's user teaches (SC-2a,
   ``ClassService.remove_school_less_enrolments_in_session``); school classes keep them.

**A suspension or a close** (SPEC §a.3, A5, A12, and T25's A11 ``tutor_suspended``).
:meth:`TutoringSweeps.sweep_sanction_in_session` checks the transition (suspend from ``listed``,
``pending_review`` or ``rejected``; close from anything but ``closed``), then cancels every
active session not yet started (party ``platform_admin``; the students and their parents are
emailed, the tutor is told the listing decision instead), revokes every live grant (reason
``tutor_suspended`` or ``tutor_closed``, SC-3), removes school-less enrolments (a suspension:
every student with any booking or any grant with the tutor, in any state, SC-2b; a close: every
enrolment in those classes, SPEC §i.6), and only then moves the listing, records the approval
event (with the validated note) and queues the tutor's ``tutor_listing_decision`` email.
Reinstatement (A3) restores none of it (SC-3); this module has no inverse.

**Locks (SPEC §a.4b, §i.7).** Every sweep holds the tutor row ``FOR UPDATE`` before anything
else (:func:`lock_tutor_for_sweep`). A booking, note or grant write takes that row
``FOR SHARE`` first, so it either finishes before the sweep starts (and the sweep then sees and
cancels or revokes what it wrote) or starts after the sweep commits (and then re-reads the
block or the listing and refuses). The listing moves last on purpose: until then nothing but
``FOR UPDATE`` keeps a create that already holds the share lock from inserting around the
cancellation. A block also takes the student's ``users`` row ``FOR KEY SHARE`` and the pair
lock (``booking_repo.lock_pair_in_session``); both are taken again here, which costs nothing
inside one transaction and keeps this method safe for a caller that forgot them. The
cancellation helpers take the affected students' rows ``FOR KEY SHARE`` themselves, in id
order, before their ``UPDATE``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Literal

import sqlalchemy as sa

from lemely.core.tutor_directory import public_name, student_label
from lemely.db.booking_repo import BookingService, lock_pair_in_session
from lemely.db.class_repo import ClassService
from lemely.db.email_outbox_repo import enqueue_in_session
from lemely.db.models.enums import GrantRevokeReason, TutorApprovalDecision, TutorListingState
from lemely.db.parent_repo import ParentLinkService
from lemely.db.tutor_approval_repo import (
    LISTING_TEMPLATE,
    MAX_NOTE_LENGTH,
    ApprovalError,
    IllegalApprovalTransitionError,
    NoteTooLongError,
    TutorApprovalRepository,
    TutorNotFoundError,
)
from lemely.db.tutor_grant_repo import revoke_live_in_session

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sqlalchemy.orm import Session, sessionmaker

SanctionReason = Literal["tutor_suspended", "tutor_closed"]


class AlreadyClosedError(ApprovalError):
    """A12 on a profile that is already closed (409, SC-21: a close is irreversible in v1)."""

    code = "already_closed"


@dataclass(frozen=True, slots=True)
class _Sanction:
    """What one sanction does: the listing it ends in and the records it writes."""

    target: TutorListingState
    decision: TutorApprovalDecision
    revoke_reason: GrantRevokeReason
    allowed_from: frozenset[TutorListingState]


_SANCTIONS: Final[Mapping[str, _Sanction]] = MappingProxyType(
    {
        "tutor_suspended": _Sanction(
            target=TutorListingState.suspended,
            decision=TutorApprovalDecision.suspended,
            revoke_reason=GrantRevokeReason.tutor_suspended,
            allowed_from=frozenset(
                {
                    TutorListingState.listed,
                    TutorListingState.pending_review,
                    TutorListingState.rejected,
                }
            ),
        ),
        "tutor_closed": _Sanction(
            target=TutorListingState.closed,
            decision=TutorApprovalDecision.closed,
            revoke_reason=GrantRevokeReason.tutor_closed,
            allowed_from=frozenset(set(TutorListingState) - {TutorListingState.closed}),
        ),
    }
)


@dataclass(frozen=True, slots=True)
class LockedTutor:
    """The tutor row a sweep holds ``FOR UPDATE``: who the tutor is and their listing now."""

    profile_id: uuid.UUID
    user_id: uuid.UUID
    listing_state: TutorListingState
    public_name: str


@dataclass(frozen=True, slots=True)
class CancelledBooking:
    """One session a sweep cancelled, and who is told after the commit (SPEC §b.4)."""

    booking_id: uuid.UUID
    student_id: uuid.UUID
    student_label: str
    linked_parent_ids: tuple[uuid.UUID, ...]


@dataclass(frozen=True, slots=True)
class RevokedGrant:
    """One live grant a sweep ended."""

    grant_id: uuid.UUID
    student_id: uuid.UUID
    student_label: str


@dataclass(frozen=True, slots=True)
class SweepResult:
    """What one sweep changed: the facts its after-commit notices are built from.

    Names only, never text a person wrote: ``tutor_name`` is the public name and every student
    is their ``student_label`` (SPEC §0 "Display names", SC-9). ``approval_event_id`` and
    ``decision`` are set for a sanction only. ``cancelled`` is in start order, ``revoked`` in id
    order.
    """

    tutor_profile_id: uuid.UUID
    tutor_user_id: uuid.UUID
    tutor_name: str
    revoke_reason: GrantRevokeReason
    cancelled: tuple[CancelledBooking, ...]
    revoked: tuple[RevokedGrant, ...]
    enrolments_removed: int
    approval_event_id: uuid.UUID | None = None
    decision: TutorApprovalDecision | None = None


def lock_tutor_for_sweep(session: Session, tutor_profile_id: uuid.UUID) -> LockedTutor | None:
    """§a.4b step 1 for a block, a suspension or a close: the tutor row ``FOR UPDATE``.

    ``None`` when there is no such profile. Taking it again later in the same transaction is a
    no-op.
    """
    row = session.execute(
        sa.text(
            "SELECT id, user_id, listing_state::text AS listing_state, public_first_name, "
            "public_last_initial FROM tutor_profiles WHERE id = :t FOR UPDATE"
        ),
        {"t": tutor_profile_id},
    ).first()
    if row is None:
        return None
    return LockedTutor(
        profile_id=_as_uuid(row.id),
        user_id=_as_uuid(row.user_id),
        listing_state=TutorListingState(str(row.listing_state)),
        public_name=public_name(str(row.public_first_name), row.public_last_initial),
    )


def lock_users_for_insert(session: Session, user_ids: Sequence[uuid.UUID]) -> None:
    """Take ``users`` rows ``FOR KEY SHARE`` in id order, before the pair lock (SPEC §i.7).

    An insert that references a user (a block row, an outbox row) takes this lock in its
    foreign-key check anyway; taken there, late, it would wait on a booking create that holds
    the student row ``FOR UPDATE`` while that create waits on this transaction's pair lock.
    """
    session.execute(
        sa.text(
            "SELECT 1 FROM users WHERE id = ANY(CAST(:ids AS uuid[])) ORDER BY id FOR KEY SHARE"
        ),
        {"ids": sorted(set(user_ids))},
    )


def _as_uuid(value: object) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _clean_note(note: str | None) -> str | None:
    """An admin note as ``tutor_approval_events`` stores it: trimmed, blank as ``None``."""
    if note is None or not note.strip():
        return None
    text = note.strip()
    if len(text) > MAX_NOTE_LENGTH:
        raise NoteTooLongError(f"Keep the note to {MAX_NOTE_LENGTH} characters.")
    return text


class TutoringSweeps:
    """The three sweeps over one ``sessionmaker`` (the helpers they compose are instance methods).

    The ``*_in_session`` methods run in the caller's transaction; :meth:`sanction` opens one.
    """

    def __init__(
        self,
        sessionmaker: sessionmaker[Session],
        *,
        bookings: BookingService | None = None,
        classes: ClassService | None = None,
        parents: ParentLinkService | None = None,
        approvals: TutorApprovalRepository | None = None,
    ) -> None:
        """Wire the sweeps to a session factory and the services they compose."""
        self._sessionmaker = sessionmaker
        self._parents = parents if parents is not None else ParentLinkService(sessionmaker)
        self._bookings = (
            bookings
            if bookings is not None
            else BookingService(sessionmaker, parents=self._parents)
        )
        self._classes = classes if classes is not None else ClassService(sessionmaker)
        self._approvals = (
            approvals if approvals is not None else TutorApprovalRepository(sessionmaker)
        )

    # -- A block (SPEC §a.2) -------------------------------------------------

    def sweep_block_in_session(
        self,
        session: Session,
        *,
        student_id: uuid.UUID,
        tutor_profile_id: uuid.UUID,
        actor_user_id: uuid.UUID,
    ) -> SweepResult:
        """The effects of a new or renewed block between the pair, in the caller's transaction.

        Call it right after writing the block row, in that transaction (SPEC §i.8: one
        ``now()`` for the row, the cancellations and the revoke). ``actor_user_id`` is the
        blocker, who gets no email for their own action. Raises ``LookupError`` for an unknown
        profile (the caller resolved it under the same lock, so this means a programming
        error).
        """
        tutor = lock_tutor_for_sweep(session, tutor_profile_id)
        if tutor is None:
            raise LookupError(f"no tutor profile {tutor_profile_id}")
        lock_users_for_insert(session, [student_id, tutor.user_id])
        lock_pair_in_session(session, student_id=student_id, tutor_profile_id=tutor_profile_id)
        cancelled = self._bookings.cancel_future_for_pair_in_session(
            session,
            tutor_profile_id=tutor_profile_id,
            student_id=student_id,
            actor_user_id=actor_user_id,
        )
        revoked = revoke_live_in_session(
            session,
            tutor_profile_id=tutor_profile_id,
            student_id=student_id,
            reason=GrantRevokeReason.block,
        )
        removed = self._classes.remove_school_less_enrolments_in_session(
            session, teacher_user_id=tutor.user_id, student_ids=[student_id]
        )
        return self._result(
            session,
            tutor,
            reason=GrantRevokeReason.block,
            cancelled=cancelled,
            revoked=revoked,
            removed=removed,
        )

    # -- A suspension or a close (SPEC §a.3) ---------------------------------

    def sweep_sanction_in_session(
        self,
        session: Session,
        *,
        tutor_profile_id: uuid.UUID,
        reason: SanctionReason,
        admin_user_id: uuid.UUID,
        note: str | None,
    ) -> SweepResult:
        """A5 (``tutor_suspended``) or A12 (``tutor_closed``), in the caller's transaction.

        Raises :class:`~lemely.db.tutor_approval_repo.NoteTooLongError` (before any lock),
        :class:`~lemely.db.tutor_approval_repo.TutorNotFoundError`,
        :class:`~lemely.db.tutor_approval_repo.IllegalApprovalTransitionError` (a suspension
        from ``draft``, ``suspended`` or ``closed``) or :class:`AlreadyClosedError`; a refusal
        writes nothing. The note is stored on the approval event; the tutor reads it for a
        suspension only (SPEC §a.2), and no notice or email ever carries it.
        """
        rule = _SANCTIONS[reason]
        cleaned = _clean_note(note)
        tutor = lock_tutor_for_sweep(session, tutor_profile_id)
        if tutor is None:
            raise TutorNotFoundError("Tutor not found.")
        if tutor.listing_state not in rule.allowed_from:
            if tutor.listing_state is TutorListingState.closed and reason == "tutor_closed":
                raise AlreadyClosedError("This tutor profile is already closed.")
            raise IllegalApprovalTransitionError(
                f"A {tutor.listing_state.value} profile cannot be {rule.target.value}."
            )
        lock_users_for_insert(session, [tutor.user_id])  # the listing email references it
        cancelled = self._bookings.cancel_future_for_tutor_in_session(
            session, tutor_profile_id=tutor_profile_id
        )
        revoked = revoke_live_in_session(
            session, tutor_profile_id=tutor_profile_id, student_id=None, reason=rule.revoke_reason
        )
        if reason == "tutor_closed":
            removed = self._classes.remove_all_school_less_enrolments_in_session(
                session, teacher_user_id=tutor.user_id
            )
        else:
            removed = self._classes.remove_school_less_enrolments_in_session(
                session,
                teacher_user_id=tutor.user_id,
                student_ids=_tutoring_students(session, tutor_profile_id),
            )
        session.execute(
            sa.text(
                "UPDATE tutor_profiles SET listing_state = CAST(:state AS tutorlistingstate), "
                "closed_at = CASE WHEN :state = 'closed' THEN now() ELSE closed_at END, "
                "updated_at = now() WHERE id = :t"
            ),
            {"state": rule.target.value, "t": tutor_profile_id},
        )
        event_id = self._approvals.record_event_in_session(
            session,
            tutor_profile_id=tutor_profile_id,
            admin_user_id=admin_user_id,
            decision=rule.decision,
            documents_seen=False,
            note=cleaned,
        )
        enqueue_in_session(
            session,
            recipient_user_id=tutor.user_id,
            template=LISTING_TEMPLATE,
            context={
                "approval_event_id": event_id,
                "decision": rule.decision.value,
                "listed": False,
            },
            dedupe_key=f"listing:{event_id}",
        )
        swept = self._result(
            session,
            tutor,
            reason=rule.revoke_reason,
            cancelled=cancelled,
            revoked=revoked,
            removed=removed,
        )
        return replace(swept, approval_event_id=event_id, decision=rule.decision)

    def sanction(
        self,
        tutor_profile_id: uuid.UUID,
        *,
        reason: SanctionReason,
        admin_user_id: uuid.UUID,
        note: str | None,
    ) -> SweepResult:
        """:meth:`sweep_sanction_in_session` in a transaction of its own (A5, A12)."""
        with self._sessionmaker.begin() as session:
            return self.sweep_sanction_in_session(
                session,
                tutor_profile_id=tutor_profile_id,
                reason=reason,
                admin_user_id=admin_user_id,
                note=note,
            )

    # -- Notice facts ----------------------------------------------------------

    def _result(
        self,
        session: Session,
        tutor: LockedTutor,
        *,
        reason: GrantRevokeReason,
        cancelled: Sequence[uuid.UUID],
        revoked: Sequence[uuid.UUID],
        removed: int,
    ) -> SweepResult:
        """Read, in the sweep's transaction, the names and parents the notices need."""
        bookings: list[CancelledBooking] = []
        parents_of: dict[uuid.UUID, tuple[uuid.UUID, ...]] = {}
        if cancelled:
            rows = session.execute(
                sa.text(
                    "SELECT b.id, b.student_id, u.display_name FROM tutor_bookings b "
                    "JOIN users u ON u.id = b.student_id WHERE b.id = ANY(CAST(:ids AS uuid[])) "
                    "ORDER BY b.starts_at, b.id"
                ),
                {"ids": list(cancelled)},
            ).all()
            for row in rows:
                student = _as_uuid(row.student_id)
                if student not in parents_of:
                    parents_of[student] = tuple(
                        self._parents.linked_parent_ids_in_session(session, student)
                    )
                bookings.append(
                    CancelledBooking(
                        booking_id=_as_uuid(row.id),
                        student_id=student,
                        student_label=student_label(row.display_name, student),
                        linked_parent_ids=parents_of[student],
                    )
                )
        grants: list[RevokedGrant] = []
        if revoked:
            rows = session.execute(
                sa.text(
                    "SELECT g.id, g.student_id, u.display_name FROM tutor_data_grants g "
                    "JOIN users u ON u.id = g.student_id WHERE g.id = ANY(CAST(:ids AS uuid[])) "
                    "ORDER BY g.id"
                ),
                {"ids": list(revoked)},
            ).all()
            grants = [
                RevokedGrant(
                    grant_id=_as_uuid(row.id),
                    student_id=_as_uuid(row.student_id),
                    student_label=student_label(row.display_name, _as_uuid(row.student_id)),
                )
                for row in rows
            ]
        return SweepResult(
            tutor_profile_id=tutor.profile_id,
            tutor_user_id=tutor.user_id,
            tutor_name=tutor.public_name,
            revoke_reason=reason,
            cancelled=tuple(bookings),
            revoked=tuple(grants),
            enrolments_removed=removed,
        )


def _tutoring_students(session: Session, tutor_profile_id: uuid.UUID) -> list[uuid.UUID]:
    """SC-2b: every student with any booking or any grant with the tutor, in any state."""
    rows = session.execute(
        sa.text(
            "SELECT student_id FROM tutor_bookings WHERE tutor_profile_id = :t "
            "UNION SELECT student_id FROM tutor_data_grants WHERE tutor_profile_id = :t "
            "ORDER BY student_id"
        ),
        {"t": tutor_profile_id},
    ).scalars()
    return [_as_uuid(value) for value in rows]


__all__ = [
    "AlreadyClosedError",
    "CancelledBooking",
    "LockedTutor",
    "RevokedGrant",
    "SanctionReason",
    "SweepResult",
    "TutoringSweeps",
    "lock_tutor_for_sweep",
    "lock_users_for_insert",
]
