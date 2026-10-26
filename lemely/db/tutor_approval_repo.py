"""Platform-admin approval of tutor profiles (SPEC §a.3 listing transitions, §b.2 A1-A4).

The single writer of ``tutor_approval_events`` (PLAN §1.4 #2) and of the
admin's listing transitions:

* ``pending_review`` to ``listed`` (A3 approve):
  ``first_listed_at = COALESCE(first_listed_at, now())``, ``listed_at = now()``;
* ``suspended`` to ``listed`` (A3 reinstate) when the profile was approved before
  and nothing was submitted after its last approval;
* ``suspended`` to ``pending_review`` (A3 reinstate) otherwise;
* ``pending_review`` to ``rejected`` (A4): a note is required and shown to the tutor.

**Reinstatement (lead ruling, T06 review; T10 review R4).** A profile suspended
while it was ``pending_review`` or ``rejected`` before any approval has
``first_listed_at`` NULL; reinstating it returns it to ``pending_review``, never
straight to ``listed``, because decision row 5a puts an admin approval before
any listing. So does a profile approved before whose moderated edit was waiting
for review when it was suspended (``submitted_at`` after ``listed_at``): listing
it would publish text no admin approved. Any other profile approved at least
once returns to ``listed``. Either way reinstatement restores nothing (SPEC
§a.3, SC-3): grants stay revoked, bookings stay cancelled, enrolments stay
removed. This module touches none of those tables.

**documents_seen_at (F14).** Every A3 call sets it from ``documentsSeen``:
``now()`` when true, NULL when false. An evidence upload or delete clears it
(:mod:`lemely.db.tutor_evidence_repo`). ``documentsSeen=true`` is accepted only
when every current evidence file has an ``evidence_open`` row (A2 issued its
link) written at or after that file's upload; otherwise 409
``documents_not_opened`` (T10 review R3). With no files it is accepted:
evidence is optional. The files are read after the profile lock, which every
upload and delete also takes first, so none can arrive between the check and
the decision.

**One transaction per decision**, which locks the profile row first (SPEC §a.4b),
writes the state, the approval event (with a snapshot of what was decided on,
taken inside :meth:`TutorApprovalRepository.record_event_in_session`) and the
tutor's ``tutor_listing_decision`` email in the outbox (SPEC §b.4: the outbox row
commits or rolls back with the change). The inbox notice is the router's job,
after commit. Both carry ``listed`` (whether the profile is listed after the
decision), so a reinstatement back to review reads "back in review", not
"listed again" (SPEC §b.4).

**Reads.** :meth:`TutorApprovalRepository.queue` pages A1 by
``(COALESCE(submitted_at, created_at), id)``, oldest first, with a cursor bound
to the listing state it was minted for (O21). :meth:`~TutorApprovalRepository.admin_facts`
returns what A2 adds to the tutor's own view: the account email (admin only,
§a.5), the decision history and the open report count.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Final

import sqlalchemy as sa

from lemely.core.keyset import CursorError, decode_cursor, encode_cursor
from lemely.db.email_outbox_repo import enqueue_in_session
from lemely.db.models.enums import TutorApprovalDecision, TutorListingState
from lemely.db.models.tutoring import TutorApprovalEvent, TutorProfile
from lemely.db.tutor_directory_repo import MAX_PAGE_SIZE, SubjectRef, subjects_by_tutor

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

#: ``ck_tutor_approval_events_note_len``.
MAX_NOTE_LENGTH: Final = 2000
#: SPEC §b.4: the tutor's email for a listing decision.
LISTING_TEMPLATE: Final = "tutor_listing_decision"

_QUEUE_CURSOR_TYPES: Final = (datetime, uuid.UUID)
_QUEUED_AT: Final = "COALESCE(tp.submitted_at, tp.created_at)"


# ---------------------------------------------------------------------------
# Errors (each carries the API code the router sends)
# ---------------------------------------------------------------------------


class ApprovalError(Exception):
    """Base class: ``code`` is the stable API code, ``message`` plain English."""

    code: str = "approval_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class TutorNotFoundError(ApprovalError):
    """No tutor profile with that id (404)."""

    code = "not_found"


class IllegalApprovalTransitionError(ApprovalError):
    """The decision does not apply to the profile's listing state (409)."""

    code = "illegal_transition"


class NoteRequiredError(ApprovalError):
    """A rejection needs a note, which the tutor reads (422, SPEC §a.3)."""

    code = "note_required"


class NoteTooLongError(ApprovalError):
    """A note over :data:`MAX_NOTE_LENGTH` characters (422)."""

    code = "note_too_long"


class DocumentsNotOpenedError(ApprovalError):
    """``documentsSeen`` claimed for a file no admin has opened since its upload (409, R3)."""

    code = "documents_not_opened"


# ---------------------------------------------------------------------------
# Read models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ApprovalOutcome:
    """What one decision did; the router tells the tutor from it after commit."""

    event_id: uuid.UUID
    decision: TutorApprovalDecision
    listing_state: TutorListingState
    tutor_user_id: uuid.UUID

    @property
    def listed(self) -> bool:
        """Whether the profile is listed after the decision (the notices' ``listed`` flag)."""
        return self.listing_state is TutorListingState.listed


@dataclass(frozen=True, slots=True)
class QueueKey:
    """The sort key of the last row of an A1 page: where the next page starts."""

    queued_at: datetime
    tutor_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class QueueItem:
    """One A1 row: the X-04 queue's name, subjects and submission time."""

    tutor_id: uuid.UUID
    public_first_name: str
    public_last_initial: str | None
    subjects: tuple[SubjectRef, ...]
    submitted_at: datetime | None


@dataclass(frozen=True, slots=True)
class QueuePage:
    """One keyset page of the A1 queue."""

    items: tuple[QueueItem, ...]
    next_key: QueueKey | None


@dataclass(frozen=True, slots=True)
class ApprovalHistoryEntry:
    """One decision in A2's history (no event id, no admin id: ID-5)."""

    decision: TutorApprovalDecision
    documents_seen: bool
    note: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class AdminTutorFacts:
    """What A2 shows beyond the tutor's own view of the profile."""

    account_email: str
    history: tuple[ApprovalHistoryEntry, ...]
    open_reports: int


# ---------------------------------------------------------------------------
# Cursor codec (O21)
# ---------------------------------------------------------------------------


def _queue_endpoint(state: TutorListingState) -> str:
    return f"admin_tutors:{state.value}"


def queue_cursor(state: TutorListingState, key: QueueKey) -> str:
    """Encode ``key`` for the A1 list filtered to ``state``."""
    return encode_cursor(_queue_endpoint(state), [key.queued_at, key.tutor_id])


def parse_queue_cursor(token: str, state: TutorListingState) -> QueueKey:
    """Decode a cursor minted by :func:`queue_cursor` for the same ``state``.

    Raises :class:`~lemely.core.keyset.CursorError` for anything else, including a
    cursor minted for another listing state.
    """
    queued_at, tutor_id = decode_cursor(
        token, endpoint=_queue_endpoint(state), types=_QUEUE_CURSOR_TYPES
    )
    if not (
        isinstance(queued_at, datetime) and isinstance(tutor_id, uuid.UUID)
    ):  # pragma: no cover - decode_cursor already returns these types
        raise CursorError("cursor has the wrong shape")
    return QueueKey(queued_at=queued_at, tutor_id=tutor_id)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clean_note(note: str | None) -> str | None:
    if note is None or not note.strip():
        return None
    text = note.strip()
    if len(text) > MAX_NOTE_LENGTH:
        raise NoteTooLongError(f"Keep the note to {MAX_NOTE_LENGTH} characters.")
    return text


def _snapshot(session: Session, tutor_profile_id: uuid.UUID) -> dict[str, object]:
    """The public and logged-in fields the decision was made on, plus the evidence it saw.

    One statement. Evidence is recorded by id, type and size only: never by its
    storage path, and never by its original filename, which is PII (SPEC §a.2)
    and would outlive the file in this append-only log (T10 review R6).
    """
    row = session.execute(
        sa.text(
            "SELECT json_build_object("
            "'public_first_name', tp.public_first_name, "
            "'public_last_initial', tp.public_last_initial, "
            "'headline', tp.headline, 'bio', tp.bio, "
            "'qualification_note', tp.qualification_note, "
            "'offers_virtual', tp.offers_virtual, 'offers_in_person', tp.offers_in_person, "
            "'offers_other', tp.offers_other, 'other_mode_note', tp.other_mode_note, "
            "'area_code', tp.area_code, 'zone', tp.zone, 'indexable', tp.indexable, "
            "'subject_codes', (SELECT coalesce(json_agg(ts.subject_code "
            "ORDER BY ts.subject_code), '[]'::json) FROM tutor_subjects ts "
            "WHERE ts.tutor_profile_id = tp.id), "
            "'availability', (SELECT coalesce(json_agg(json_build_array(r.iso_weekday, "
            "r.start_minute, r.end_minute) ORDER BY r.iso_weekday, r.start_minute), '[]'::json) "
            "FROM tutor_availability_rules r WHERE r.tutor_profile_id = tp.id), "
            "'evidence', (SELECT coalesce(json_agg(json_build_object('evidence_id', e.id, "
            "'content_type', e.content_type, "
            "'size_bytes', e.size_bytes) ORDER BY e.created_at, e.id), '[]'::json) "
            "FROM tutor_evidence_files e WHERE e.tutor_profile_id = tp.id)"
            ") FROM tutor_profiles tp WHERE tp.id = :p"
        ),
        {"p": tutor_profile_id},
    ).scalar_one()
    if not isinstance(row, dict):  # pragma: no cover - json_build_object maps to a dict
        raise TypeError(f"profile snapshot is not an object: {row!r}")
    return row


def _lock(session: Session, tutor_profile_id: uuid.UUID) -> TutorProfile:
    profile = session.get(TutorProfile, tutor_profile_id, with_for_update=True)
    if profile is None:
        raise TutorNotFoundError("Tutor not found.")
    return profile


def _illegal(action: str, state: TutorListingState) -> IllegalApprovalTransitionError:
    return IllegalApprovalTransitionError(f"A {state.value} profile cannot be {action}.")


def _reinstated_state(profile: TutorProfile) -> TutorListingState:
    """Where A3 puts a suspended profile: ``listed`` only if nothing awaits an approval.

    ``pending_review`` for a profile never approved (``first_listed_at`` NULL) and
    for one with a submission after its last approval (a moderated edit sends a
    listed profile back to review with ``submitted_at = now()``). A submission
    with no ``listed_at`` to compare with counts as waiting.
    """
    if profile.first_listed_at is None:
        return TutorListingState.pending_review
    submitted, approved = profile.submitted_at, profile.listed_at
    if submitted is not None and (approved is None or submitted > approved):
        return TutorListingState.pending_review
    return TutorListingState.listed


#: The evidence files of a profile that no admin has opened since they were
#: uploaded: no ``evidence_open`` row for the file (A2 writes one per link it
#: issues) created at or after the file's row. ``tutor_profile_id`` on the access
#: row lets ``ix_tutoring_admin_access_tutor`` serve the probe.
_UNOPENED_EVIDENCE_SQL: Final = (
    "SELECT count(*) FROM tutor_evidence_files e WHERE e.tutor_profile_id = :p "
    "AND NOT EXISTS (SELECT 1 FROM tutoring_admin_access a "
    "WHERE a.tutor_profile_id = e.tutor_profile_id AND a.evidence_id = e.id "
    "AND a.action = 'evidence_open' AND a.created_at >= e.created_at)"
)


def _check_documents_opened(session: Session, tutor_profile_id: uuid.UUID) -> None:
    """Refuse ``documentsSeen=true`` while any current file is unopened (T10 review R3).

    Run under the profile lock, which uploads and deletes also take first.
    """
    unopened = session.execute(
        sa.text(_UNOPENED_EVIDENCE_SQL), {"p": tutor_profile_id}
    ).scalar_one()
    if unopened:
        raise DocumentsNotOpenedError(
            "Open every document before you confirm that you looked at them."
        )


_OPEN_REPORTS_SQL: Final = (
    "SELECT count(*) FROM tutoring_reports r WHERE r.state = 'open' AND ("
    "r.tutor_profile_id = :p "
    "OR r.review_id IN (SELECT id FROM tutor_reviews WHERE tutor_profile_id = :p) "
    "OR r.reply_id IN (SELECT id FROM tutor_review_replies WHERE tutor_profile_id = :p) "
    "OR r.booking_id IN (SELECT id FROM tutor_bookings WHERE tutor_profile_id = :p) "
    "OR r.note_id IN (SELECT n.id FROM tutor_booking_notes n "
    "JOIN tutor_bookings b ON b.id = n.booking_id WHERE b.tutor_profile_id = :p))"
)


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------


class TutorApprovalRepository:
    """Admin approval decisions and the admin's reads of tutor profiles."""

    def __init__(self, sessionmaker: sessionmaker[Session]) -> None:
        """Wire the repository to a session factory."""
        self._sessionmaker = sessionmaker

    # -- shared with every admin decision (A3, A4 here; A5, A11, A12 elsewhere) --

    def record_event_in_session(
        self,
        session: Session,
        *,
        tutor_profile_id: uuid.UUID,
        admin_user_id: uuid.UUID | None,
        decision: TutorApprovalDecision,
        documents_seen: bool,
        note: str | None,
    ) -> uuid.UUID:
        """Append one ``tutor_approval_events`` row in the caller's transaction; returns its id.

        The snapshot of the profile is taken here, inside the same transaction as
        the decision, so it is exactly what the decision applied to. ``note`` is
        stored as given (callers validate it); the column CHECK caps it at 2000.
        """
        snapshot = _snapshot(session, tutor_profile_id)
        event_id = session.execute(
            sa.insert(TutorApprovalEvent)
            .values(
                tutor_profile_id=tutor_profile_id,
                admin_user_id=admin_user_id,
                decision=decision,
                documents_seen=documents_seen,
                note=note,
                profile_snapshot=snapshot,
            )
            .returning(TutorApprovalEvent.id)
        ).scalar_one()
        if not isinstance(event_id, uuid.UUID):  # pragma: no cover - the column is a uuid
            raise TypeError(f"approval event id is not a UUID: {event_id!r}")
        return event_id

    # -- A3, A4 -------------------------------------------------------------

    def approve(
        self,
        tutor_profile_id: uuid.UUID,
        *,
        admin_user_id: uuid.UUID,
        documents_seen: bool,
        note: str | None,
    ) -> ApprovalOutcome:
        """A3: approve a ``pending_review`` profile, or reinstate a ``suspended`` one.

        Raises :class:`TutorNotFoundError`, :class:`IllegalApprovalTransitionError`
        (any other state), :class:`DocumentsNotOpenedError` (``documents_seen``
        with a file no admin has opened since its upload) or
        :class:`NoteTooLongError`.
        """
        cleaned = _clean_note(note)
        with self._sessionmaker.begin() as session:
            profile = _lock(session, tutor_profile_id)
            state = profile.listing_state
            if state is TutorListingState.pending_review:
                decision, target = TutorApprovalDecision.approved, TutorListingState.listed
            elif state is TutorListingState.suspended:
                decision, target = TutorApprovalDecision.reinstated, _reinstated_state(profile)
            else:
                raise _illegal("approved", state)
            if documents_seen:
                _check_documents_opened(session, profile.id)
            profile.listing_state = target
            profile.documents_seen_at = sa.func.now() if documents_seen else None
            if target is TutorListingState.listed:
                profile.listed_at = sa.func.now()
                profile.first_listed_at = sa.func.coalesce(
                    TutorProfile.first_listed_at, sa.func.now()
                )
            session.flush()
            return self._decided(
                session,
                profile,
                decision=decision,
                admin_user_id=admin_user_id,
                documents_seen=documents_seen,
                note=cleaned,
            )

    def reject(
        self, tutor_profile_id: uuid.UUID, *, admin_user_id: uuid.UUID, note: str | None
    ) -> ApprovalOutcome:
        """A4: reject a ``pending_review`` profile with a note the tutor reads.

        Raises :class:`NoteRequiredError`, :class:`NoteTooLongError`,
        :class:`TutorNotFoundError` or :class:`IllegalApprovalTransitionError`.
        """
        cleaned = _clean_note(note)
        if cleaned is None:
            raise NoteRequiredError("Write a note for the tutor: they read it on their profile.")
        with self._sessionmaker.begin() as session:
            profile = _lock(session, tutor_profile_id)
            if profile.listing_state is not TutorListingState.pending_review:
                raise _illegal("rejected", profile.listing_state)
            profile.listing_state = TutorListingState.rejected
            session.flush()
            return self._decided(
                session,
                profile,
                decision=TutorApprovalDecision.rejected,
                admin_user_id=admin_user_id,
                documents_seen=False,
                note=cleaned,
            )

    def _decided(
        self,
        session: Session,
        profile: TutorProfile,
        *,
        decision: TutorApprovalDecision,
        admin_user_id: uuid.UUID,
        documents_seen: bool,
        note: str | None,
    ) -> ApprovalOutcome:
        """Record the event and queue the tutor's email: every A3 and A4 decision is told."""
        event_id = self.record_event_in_session(
            session,
            tutor_profile_id=profile.id,
            admin_user_id=admin_user_id,
            decision=decision,
            documents_seen=documents_seen,
            note=note,
        )
        outcome = ApprovalOutcome(
            event_id=event_id,
            decision=decision,
            listing_state=profile.listing_state,
            tutor_user_id=profile.user_id,
        )
        enqueue_in_session(
            session,
            recipient_user_id=profile.user_id,
            template=LISTING_TEMPLATE,
            context={
                "approval_event_id": event_id,
                "decision": decision.value,
                "listed": outcome.listed,
            },
            dedupe_key=f"listing:{event_id}",
        )
        return outcome

    # -- A1, A2 reads -------------------------------------------------------

    def queue(self, state: TutorListingState, *, after: QueueKey | None, limit: int) -> QueuePage:
        """A1: one page of profiles in ``state``, oldest submission first (two statements).

        Raises ``ValueError`` for a ``limit`` outside 1..50.
        """
        if not 1 <= limit <= MAX_PAGE_SIZE:
            raise ValueError(f"limit must be 1 to {MAX_PAGE_SIZE}, got {limit}")
        where = ["tp.listing_state = CAST(:state AS tutorlistingstate)"]
        params: dict[str, object] = {"state": state.value, "limit": limit + 1}
        if after is not None:
            where.append(f"({_QUEUED_AT}, tp.id) > (:after_at, :after_id)")
            params.update(after_at=after.queued_at, after_id=after.tutor_id)
        statement = sa.text(
            "SELECT tp.id, tp.public_first_name, tp.public_last_initial, tp.submitted_at, "  # noqa: S608 - constants
            f"{_QUEUED_AT} AS queued_at FROM tutor_profiles tp WHERE {' AND '.join(where)} "
            f"ORDER BY {_QUEUED_AT}, tp.id LIMIT :limit"
        )
        with self._sessionmaker() as session:
            rows = session.execute(statement, params).all()
            page = rows[:limit]
            subjects = subjects_by_tutor(session, [row.id for row in page])
        items = tuple(
            QueueItem(
                tutor_id=row.id,
                public_first_name=row.public_first_name,
                public_last_initial=row.public_last_initial,
                subjects=subjects.get(row.id, ()),
                submitted_at=row.submitted_at,
            )
            for row in page
        )
        next_key = None
        if len(rows) > limit:
            last = page[-1]
            next_key = QueueKey(queued_at=last.queued_at, tutor_id=last.id)
        return QueuePage(items=items, next_key=next_key)

    def admin_facts(self, tutor_profile_id: uuid.UUID) -> AdminTutorFacts | None:
        """A2: account email, decision history (newest first) and open reports, or ``None``."""
        with self._sessionmaker() as session:
            head = session.execute(
                sa.text(
                    f"SELECT u.email, ({_OPEN_REPORTS_SQL}) AS open_reports "  # noqa: S608 - constants
                    "FROM tutor_profiles tp JOIN users u ON u.id = tp.user_id WHERE tp.id = :p"
                ),
                {"p": tutor_profile_id},
            ).first()
            if head is None:
                return None
            history = session.execute(
                sa.select(
                    TutorApprovalEvent.decision,
                    TutorApprovalEvent.documents_seen,
                    TutorApprovalEvent.note,
                    TutorApprovalEvent.created_at,
                )
                .where(TutorApprovalEvent.tutor_profile_id == tutor_profile_id)
                .order_by(TutorApprovalEvent.created_at.desc(), TutorApprovalEvent.id.desc())
            ).all()
        return AdminTutorFacts(
            account_email=str(head.email),
            history=tuple(
                ApprovalHistoryEntry(
                    decision=row.decision,
                    documents_seen=row.documents_seen,
                    note=row.note,
                    created_at=row.created_at,
                )
                for row in history
            ),
            open_reports=int(head.open_reports),
        )


__all__ = [
    "LISTING_TEMPLATE",
    "MAX_NOTE_LENGTH",
    "AdminTutorFacts",
    "ApprovalError",
    "ApprovalHistoryEntry",
    "ApprovalOutcome",
    "DocumentsNotOpenedError",
    "IllegalApprovalTransitionError",
    "NoteRequiredError",
    "NoteTooLongError",
    "QueueItem",
    "QueueKey",
    "QueuePage",
    "TutorApprovalRepository",
    "TutorNotFoundError",
    "parse_queue_cursor",
    "queue_cursor",
]
