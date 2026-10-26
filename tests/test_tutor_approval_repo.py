"""Admin approval of tutor profiles (SPEC §a.3 listing transitions, §a.2 ``tutor_approval_events``).

DB-backed against a ``create_all`` database (helpers from ``tests/tutoring_db.py``).
Covers A3 (approve, and reinstate a suspended tutor) and A4 (reject), the
``documents_seen_at`` rules (F14), the A1 queue and the A2 facts. The lead's
reinstatement ruling (T06 review): a suspended profile that was never approved
(``first_listed_at IS NULL``) returns to ``pending_review``, never straight to
``listed`` (decision row 5a); one with ``first_listed_at`` set returns to
``listed``. Either way reinstatement restores nothing (SC-3).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa

from lemely.core.keyset import CursorError
from lemely.db.models.enums import Role, TutorApprovalDecision, TutorListingState
from lemely.db.models.tutoring import EmailOutbox, TutorApprovalEvent, TutorProfile
from lemely.db.tutor_approval_repo import (
    MAX_NOTE_LENGTH,
    IllegalApprovalTransitionError,
    NoteRequiredError,
    NoteTooLongError,
    TutorApprovalRepository,
    TutorNotFoundError,
    parse_queue_cursor,
    queue_cursor,
)
from lemely.db.tutor_evidence_repo import TutorEvidenceRepository
from lemely.db.tutor_profile_repo import ProfileChanges, TutorProfileRepository
from tests.tutoring_db import (
    NOW,
    add_subject,
    add_tutor,
    add_user,
    emptied_after,
    tutoring_database,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture(scope="module")
def tutoring_db() -> Iterator[sessionmaker[Session]]:
    with tutoring_database() as factory:
        yield factory


@pytest.fixture
def sm(tutoring_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(tutoring_db)


@pytest.fixture
def repo(sm: sessionmaker[Session]) -> TutorApprovalRepository:
    return TutorApprovalRepository(sm)


def _profile(sm: sessionmaker[Session], profile_id: uuid.UUID) -> TutorProfile:
    with sm() as session:
        profile = session.get(TutorProfile, profile_id)
        assert profile is not None
        return profile


def _events(sm: sessionmaker[Session], profile_id: uuid.UUID) -> list[TutorApprovalEvent]:
    with sm() as session:
        return list(
            session.scalars(
                sa.select(TutorApprovalEvent)
                .where(TutorApprovalEvent.tutor_profile_id == profile_id)
                .order_by(TutorApprovalEvent.created_at, TutorApprovalEvent.id)
            )
        )


def _outbox(sm: sessionmaker[Session]) -> list[EmailOutbox]:
    with sm() as session:
        return list(session.scalars(sa.select(EmailOutbox).order_by(EmailOutbox.created_at)))


def _set(sm: sessionmaker[Session], profile_id: uuid.UUID, **columns: object) -> None:
    with sm.begin() as session:
        session.execute(
            sa.update(TutorProfile).where(TutorProfile.id == profile_id).values(**columns)
        )


def _admin(sm: sessionmaker[Session]) -> uuid.UUID:
    return add_user(sm, Role.platform_admin)


# ---------------------------------------------------------------------------
# A3 approve (pending_review -> listed)
# ---------------------------------------------------------------------------


def test_approve_sets_first_listed_once(
    sm: sessionmaker[Session], repo: TutorApprovalRepository
) -> None:
    subject = add_subject(sm)
    tutor = add_tutor(sm, state="pending_review", subjects=[subject])
    admin = _admin(sm)
    assert _profile(sm, tutor.profile_id).first_listed_at is None

    first = repo.approve(tutor.profile_id, admin_user_id=admin, documents_seen=False, note=None)

    after_first = _profile(sm, tutor.profile_id)
    assert first.decision is TutorApprovalDecision.approved
    assert first.listing_state is TutorListingState.listed
    assert after_first.listing_state is TutorListingState.listed
    assert after_first.first_listed_at is not None
    assert after_first.listed_at == after_first.first_listed_at

    # A moderated edit sends the listed profile back to review (SPEC §a.3) ...
    _, re_review = TutorProfileRepository(sm).update(
        tutor.profile_id, ProfileChanges(headline="IGCSE Mathematics and Further Pure")
    )
    assert re_review is True
    assert _profile(sm, tutor.profile_id).listing_state is TutorListingState.pending_review

    # ... and the second approval keeps the first approval's instant.
    repo.approve(tutor.profile_id, admin_user_id=admin, documents_seen=True, note=None)

    after_second = _profile(sm, tutor.profile_id)
    assert after_second.listing_state is TutorListingState.listed
    assert after_second.first_listed_at == after_first.first_listed_at
    assert after_second.listed_at is not None
    assert after_second.listed_at > after_first.listed_at
    assert [e.decision for e in _events(sm, tutor.profile_id)] == [
        TutorApprovalDecision.approved,
        TutorApprovalDecision.approved,
    ]


def test_approve_records_event_snapshot_and_listing_email(
    sm: sessionmaker[Session], repo: TutorApprovalRepository
) -> None:
    subject = add_subject(sm, name="Physics")
    tutor = add_tutor(
        sm,
        state="pending_review",
        subjects=[subject],
        bio="Ten years of teaching.",
        qualification_note="BSc Physics",
        rules=((2, 600, 720),),
    )
    TutorEvidenceRepository(sm).add(
        tutor.profile_id,
        evidence_id=uuid.uuid4(),
        storage_path=f"tutor-evidence/{tutor.profile_id}/{uuid.uuid4()}.pdf",
        filename="degree.pdf",
        content_type="application/pdf",
        size_bytes=1234,
        description="BSc certificate",
    )
    admin = _admin(sm)

    outcome = repo.approve(
        tutor.profile_id, admin_user_id=admin, documents_seen=True, note="Checked the degree."
    )

    [event] = _events(sm, tutor.profile_id)
    assert event.id == outcome.event_id
    assert event.admin_user_id == admin
    assert event.decision is TutorApprovalDecision.approved
    assert event.documents_seen is True
    assert event.note == "Checked the degree."
    snapshot = event.profile_snapshot
    assert snapshot["public_first_name"] == "Sara"
    assert snapshot["headline"] == "IGCSE Mathematics, patient and exam focused"
    assert snapshot["bio"] == "Ten years of teaching."
    assert snapshot["qualification_note"] == "BSc Physics"
    assert snapshot["subject_codes"] == [subject]
    assert snapshot["availability"] == [[2, 600, 720]]
    assert [item["filename"] for item in snapshot["evidence"]] == ["degree.pdf"]
    assert "storage_path" not in json.dumps(snapshot)

    assert outcome.notify_tutor is True
    assert outcome.tutor_user_id == tutor.user_id
    [mail] = _outbox(sm)
    assert mail.recipient_user_id == tutor.user_id
    assert mail.template == "tutor_listing_decision"
    assert mail.dedupe_key == f"listing:{event.id}"
    assert mail.context == {"approval_event_id": str(event.id), "decision": "approved"}


@pytest.mark.parametrize("state", ["draft", "listed", "rejected", "closed"])
def test_approve_refused_outside_pending_review_and_suspended_409(
    sm: sessionmaker[Session], repo: TutorApprovalRepository, state: str
) -> None:
    tutor = add_tutor(sm, state=state)
    before = _profile(sm, tutor.profile_id)

    with pytest.raises(IllegalApprovalTransitionError) as excinfo:
        repo.approve(tutor.profile_id, admin_user_id=_admin(sm), documents_seen=True, note=None)

    assert excinfo.value.code == "illegal_transition"
    after = _profile(sm, tutor.profile_id)
    assert after.listing_state is before.listing_state
    assert after.documents_seen_at == before.documents_seen_at
    assert _events(sm, tutor.profile_id) == []
    assert _outbox(sm) == []


def test_unknown_tutor_404(sm: sessionmaker[Session], repo: TutorApprovalRepository) -> None:
    admin = _admin(sm)
    with pytest.raises(TutorNotFoundError) as excinfo:
        repo.approve(uuid.uuid4(), admin_user_id=admin, documents_seen=False, note=None)
    assert excinfo.value.code == "not_found"
    with pytest.raises(TutorNotFoundError):
        repo.reject(uuid.uuid4(), admin_user_id=admin, note="No.")
    assert repo.admin_facts(uuid.uuid4()) is None


# ---------------------------------------------------------------------------
# documents_seen_at (SPEC §a.2, F14)
# ---------------------------------------------------------------------------


def test_documents_seen_cleared_by_upload_delete_and_false_approval(
    sm: sessionmaker[Session], repo: TutorApprovalRepository
) -> None:
    tutor = add_tutor(sm, state="pending_review")
    admin = _admin(sm)
    evidence = TutorEvidenceRepository(sm)

    def seen() -> bool:
        return _profile(sm, tutor.profile_id).documents_seen_at is not None

    def back_to_review() -> None:
        _set(sm, tutor.profile_id, listing_state=TutorListingState.pending_review)

    repo.approve(tutor.profile_id, admin_user_id=admin, documents_seen=True, note=None)
    assert seen()

    # An upload clears it, whatever the listing state.
    added = evidence.add(
        tutor.profile_id,
        evidence_id=uuid.uuid4(),
        storage_path=f"tutor-evidence/{tutor.profile_id}/{uuid.uuid4()}.png",
        filename="cert.png",
        content_type="image/png",
        size_bytes=10,
        description=None,
    )
    assert not seen()

    back_to_review()
    repo.approve(tutor.profile_id, admin_user_id=admin, documents_seen=True, note=None)
    assert seen()

    # A delete clears it.
    evidence.delete(tutor.profile_id, added.id)
    assert not seen()

    back_to_review()
    repo.approve(tutor.profile_id, admin_user_id=admin, documents_seen=True, note=None)
    assert seen()

    # An approval with documentsSeen=false clears it.
    back_to_review()
    repo.approve(tutor.profile_id, admin_user_id=admin, documents_seen=False, note=None)
    assert not seen()
    assert [e.documents_seen for e in _events(sm, tutor.profile_id)] == [True, True, True, False]


# ---------------------------------------------------------------------------
# A3 reinstate (suspended -> listed | pending_review), restores nothing
# ---------------------------------------------------------------------------


def _digest(sm: sessionmaker[Session], table: str) -> str:
    with sm() as session:
        rows = session.execute(
            sa.text(f"SELECT row_to_json(t)::text FROM {table} t ORDER BY 1")  # noqa: S608
        ).scalars()
        return hashlib.sha256("\n".join(rows).encode()).hexdigest()


def _cancelled_booking_and_revoked_grant(
    sm: sessionmaker[Session], profile_id: uuid.UUID, subject: str
) -> uuid.UUID:
    student = add_user(sm, Role.student)
    start = NOW + timedelta(days=3)
    with sm.begin() as session:
        session.execute(
            sa.text(
                "INSERT INTO tutor_bookings (id, tutor_profile_id, student_id, "
                "requested_by_user_id, requested_by_party, subject_code, mode, starts_at, "
                "ends_at, state, cancelled_at, cancelled_by_party) VALUES (:id, :p, :s, :s, "
                "'student', :subj, 'virtual', :start, :end, 'cancelled', :now, 'platform_admin')"
            ),
            {
                "id": uuid.uuid4(),
                "p": profile_id,
                "s": student,
                "subj": subject,
                "start": start,
                "end": start + timedelta(hours=1),
                "now": NOW,
            },
        )
        session.execute(
            sa.text(
                "INSERT INTO tutor_data_grants (id, student_id, tutor_profile_id, created_at, "
                "revoked_at, revoke_reason) VALUES (:id, :s, :p, :then, :now, 'tutor_suspended')"
            ),
            {
                "id": uuid.uuid4(),
                "s": student,
                "p": profile_id,
                "then": NOW - timedelta(days=5),
                "now": NOW,
            },
        )
    return student


def test_reinstate_restores_nothing(
    sm: sessionmaker[Session], repo: TutorApprovalRepository
) -> None:
    """SC-3: grants stay revoked, bookings stay cancelled, enrolments stay removed."""
    subject = add_subject(sm)
    tutor = add_tutor(sm, state="suspended", subjects=[subject], first_listed_at=NOW)
    _cancelled_booking_and_revoked_grant(sm, tutor.profile_id, subject)
    tables = ("tutor_bookings", "tutor_data_grants", "class_enrollments", "tutoring_blocks")
    before = {table: _digest(sm, table) for table in tables}

    outcome = repo.approve(
        tutor.profile_id, admin_user_id=_admin(sm), documents_seen=False, note=None
    )

    assert outcome.decision is TutorApprovalDecision.reinstated
    assert {table: _digest(sm, table) for table in tables} == before
    with sm() as session:
        assert (
            session.execute(sa.text("SELECT state::text FROM tutor_bookings")).scalar_one()
            == "cancelled"
        )
        assert session.execute(
            sa.text("SELECT revoked_at IS NOT NULL FROM tutor_data_grants")
        ).scalar_one()


def test_reinstate_never_approved_returns_to_pending_review(
    sm: sessionmaker[Session], repo: TutorApprovalRepository
) -> None:
    """Lead ruling: row 5a, admin approval before listing; a never-approved profile is queued."""
    tutor = add_tutor(sm, state="suspended", first_listed_at=None)

    outcome = repo.approve(
        tutor.profile_id, admin_user_id=_admin(sm), documents_seen=True, note=None
    )

    profile = _profile(sm, tutor.profile_id)
    assert outcome.decision is TutorApprovalDecision.reinstated
    assert outcome.listing_state is TutorListingState.pending_review
    assert profile.listing_state is TutorListingState.pending_review
    assert profile.first_listed_at is None
    assert profile.listed_at is None
    assert [e.decision for e in _events(sm, tutor.profile_id)] == [TutorApprovalDecision.reinstated]
    # The fixed "listed again" copy would be false here, so the tutor is not told.
    assert outcome.notify_tutor is False
    assert _outbox(sm) == []


def test_reinstate_previously_listed_returns_to_listed(
    sm: sessionmaker[Session], repo: TutorApprovalRepository
) -> None:
    first_listed = NOW - timedelta(days=90)
    tutor = add_tutor(sm, state="suspended", first_listed_at=first_listed)

    outcome = repo.approve(
        tutor.profile_id, admin_user_id=_admin(sm), documents_seen=False, note=None
    )

    profile = _profile(sm, tutor.profile_id)
    assert outcome.decision is TutorApprovalDecision.reinstated
    assert outcome.listing_state is TutorListingState.listed
    assert profile.listing_state is TutorListingState.listed
    assert profile.first_listed_at == first_listed
    assert profile.listed_at is not None
    assert profile.listed_at > first_listed
    assert outcome.notify_tutor is True
    [mail] = _outbox(sm)
    assert mail.context == {"approval_event_id": str(outcome.event_id), "decision": "reinstated"}


# ---------------------------------------------------------------------------
# A4 reject (pending_review -> rejected), note required and shown to the tutor
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("note", [None, "", "   \n"])
def test_reject_requires_note(
    sm: sessionmaker[Session], repo: TutorApprovalRepository, note: str | None
) -> None:
    tutor = add_tutor(sm, state="pending_review")

    with pytest.raises(NoteRequiredError) as excinfo:
        repo.reject(tutor.profile_id, admin_user_id=_admin(sm), note=note)

    assert excinfo.value.code == "note_required"
    assert _profile(sm, tutor.profile_id).listing_state is TutorListingState.pending_review
    assert _events(sm, tutor.profile_id) == []
    assert _outbox(sm) == []


def test_reject_with_note_is_shown_to_the_tutor(
    sm: sessionmaker[Session], repo: TutorApprovalRepository
) -> None:
    tutor = add_tutor(sm, state="pending_review")
    note = "  Please upload a clearer copy of your degree certificate.  "

    outcome = repo.reject(tutor.profile_id, admin_user_id=_admin(sm), note=note)

    assert outcome.decision is TutorApprovalDecision.rejected
    assert outcome.listing_state is TutorListingState.rejected
    assert outcome.notify_tutor is True
    assert _profile(sm, tutor.profile_id).listing_state is TutorListingState.rejected
    [event] = _events(sm, tutor.profile_id)
    assert event.note == note.strip()
    own = TutorProfileRepository(sm).own_profile(tutor.profile_id)
    assert own is not None
    assert own.review_note == note.strip()
    [mail] = _outbox(sm)
    assert mail.context == {"approval_event_id": str(event.id), "decision": "rejected"}
    assert "degree" not in json.dumps(mail.context)  # the note never travels by email


def test_note_longer_than_column_refused(
    sm: sessionmaker[Session], repo: TutorApprovalRepository
) -> None:
    tutor = add_tutor(sm, state="pending_review")
    with pytest.raises(NoteTooLongError) as excinfo:
        repo.reject(tutor.profile_id, admin_user_id=_admin(sm), note="x" * (MAX_NOTE_LENGTH + 1))
    assert excinfo.value.code == "note_too_long"
    with pytest.raises(NoteTooLongError):
        repo.approve(
            tutor.profile_id,
            admin_user_id=_admin(sm),
            documents_seen=False,
            note="x" * (MAX_NOTE_LENGTH + 1),
        )
    assert MAX_NOTE_LENGTH == 2000


@pytest.mark.parametrize("state", ["draft", "listed", "rejected", "suspended", "closed"])
def test_reject_only_from_pending_review(
    sm: sessionmaker[Session], repo: TutorApprovalRepository, state: str
) -> None:
    tutor = add_tutor(sm, state=state)
    with pytest.raises(IllegalApprovalTransitionError):
        repo.reject(tutor.profile_id, admin_user_id=_admin(sm), note="No.")
    assert _profile(sm, tutor.profile_id).listing_state is TutorListingState(state)
    assert _events(sm, tutor.profile_id) == []


# ---------------------------------------------------------------------------
# record_event_in_session (shared with the suspension and close sweeps)
# ---------------------------------------------------------------------------


def test_record_event_in_session_writes_in_the_callers_transaction(
    sm: sessionmaker[Session], repo: TutorApprovalRepository
) -> None:
    subject = add_subject(sm)
    tutor = add_tutor(sm, state="listed", subjects=[subject])
    admin = _admin(sm)

    with sm() as session:
        repo.record_event_in_session(
            session,
            tutor_profile_id=tutor.profile_id,
            admin_user_id=admin,
            decision=TutorApprovalDecision.suspended,
            documents_seen=False,
            note="Safeguarding review.",
        )
        session.rollback()
    assert _events(sm, tutor.profile_id) == []

    with sm.begin() as session:
        event_id = repo.record_event_in_session(
            session,
            tutor_profile_id=tutor.profile_id,
            admin_user_id=admin,
            decision=TutorApprovalDecision.suspended,
            documents_seen=False,
            note="Safeguarding review.",
        )
    [event] = _events(sm, tutor.profile_id)
    assert event.id == event_id
    assert event.decision is TutorApprovalDecision.suspended
    assert event.profile_snapshot["subject_codes"] == [subject]


# ---------------------------------------------------------------------------
# A1 queue and A2 facts
# ---------------------------------------------------------------------------


def test_queue_orders_oldest_submission_first_and_pages_by_keyset(
    sm: sessionmaker[Session], repo: TutorApprovalRepository
) -> None:
    subject = add_subject(sm, name="Chemistry")
    tutors = [add_tutor(sm, state="pending_review", subjects=[subject]) for _ in range(3)]
    for days, tutor in zip((3, 1, 2), tutors, strict=True):
        _set(sm, tutor.profile_id, submitted_at=NOW - timedelta(days=days))
    add_tutor(sm, state="listed")
    add_tutor(sm, state="draft")

    first = repo.queue(TutorListingState.pending_review, after=None, limit=2)
    assert [item.tutor_id for item in first.items] == [tutors[0].profile_id, tutors[2].profile_id]
    assert first.items[0].subjects[0].name == "Chemistry"
    assert first.items[0].public_first_name == "Sara"
    assert first.next_key is not None

    second = repo.queue(TutorListingState.pending_review, after=first.next_key, limit=2)
    assert [item.tutor_id for item in second.items] == [tutors[1].profile_id]
    assert second.next_key is None

    drafts = repo.queue(TutorListingState.draft, after=None, limit=20)
    assert len(drafts.items) == 1
    assert drafts.items[0].submitted_at is None


def test_queue_cursor_is_bound_to_its_state(repo: TutorApprovalRepository) -> None:
    from lemely.db.tutor_approval_repo import QueueKey

    key = QueueKey(queued_at=NOW, tutor_id=uuid.uuid4())
    token = queue_cursor(TutorListingState.pending_review, key)
    assert parse_queue_cursor(token, TutorListingState.pending_review) == key
    with pytest.raises(CursorError):
        parse_queue_cursor(token, TutorListingState.listed)
    with pytest.raises(CursorError):
        parse_queue_cursor("not-a-cursor", TutorListingState.pending_review)


def test_queue_limit_bounds(repo: TutorApprovalRepository) -> None:
    for limit in (0, 51):
        with pytest.raises(ValueError, match="limit"):
            repo.queue(TutorListingState.pending_review, after=None, limit=limit)


def _report(sm: sessionmaker[Session], *, state: str = "open", **target: uuid.UUID) -> None:
    [(column, value)] = target.items()
    target_type = {
        "tutor_profile_id": "tutor_profile",
        "booking_id": "booking",
        "review_id": "review",
    }[column]
    with sm.begin() as session:
        session.execute(
            sa.text(
                "INSERT INTO tutoring_reports (id, reporter_user_id, reporter_party, target_type, "  # noqa: S608 - test-owned column names
                f"{column}, target_snapshot, reason, state, resolution) VALUES (:id, NULL, "
                "'student', CAST(:t AS reporttargettype), :v, '{}', 'spam', "
                "CAST(:state AS reportstate), CAST(:res AS reportresolution))"
            ),
            {
                "id": uuid.uuid4(),
                "t": target_type,
                "v": value,
                "state": state,
                "res": None if state == "open" else "dismissed",
            },
        )


def test_admin_facts_email_history_and_open_reports(
    sm: sessionmaker[Session], repo: TutorApprovalRepository
) -> None:
    subject = add_subject(sm)
    tutor = add_tutor(sm, state="pending_review", subjects=[subject])
    other = add_tutor(sm, state="listed", subjects=[subject])
    admin = _admin(sm)
    repo.reject(tutor.profile_id, admin_user_id=admin, note="Upload your certificate.")
    _set(sm, tutor.profile_id, listing_state=TutorListingState.pending_review)
    repo.approve(tutor.profile_id, admin_user_id=admin, documents_seen=True, note=None)

    _cancelled_booking_and_revoked_grant(sm, tutor.profile_id, subject)
    with sm() as session:
        booking = session.execute(sa.text("SELECT id FROM tutor_bookings")).scalar_one()
    _report(sm, tutor_profile_id=tutor.profile_id)
    _report(sm, booking_id=booking)
    _report(sm, tutor_profile_id=tutor.profile_id, state="dismissed")
    _report(sm, tutor_profile_id=other.profile_id)

    facts = repo.admin_facts(tutor.profile_id)

    assert facts is not None
    assert facts.account_email == f"{tutor.user_id}@example.com"
    assert facts.open_reports == 2
    assert [(h.decision, h.documents_seen, h.note) for h in facts.history] == [
        (TutorApprovalDecision.approved, True, None),
        (TutorApprovalDecision.rejected, False, "Upload your certificate."),
    ]
