"""The block, suspension and close sweeps (PLAN T21; SPEC §a.2 ``tutoring_blocks``, §a.3, §a.4b).

SPEC ``docs/tutoring/SPEC.md`` §a.2 (a block's effects), §a.3 (suspension and close, "restores
nothing"), §a.4b (the locks), §c.4 and THREAT-MODEL SC-2 (school-less class enrolments), SC-3
(grants), SC-11 (notes stay readable and reportable), §i.8 (one instant for the block row, the
cancellations and the revokes, read after the tutor row lock; residual (f)).

Each sweep is run the way the routes run it: a block through
``TutoringBlocksRepository.block`` (the tutor row ``FOR UPDATE``, the pair lock, the block row,
then ``TutoringSweeps.sweep_block_in_session``), a suspension or close through
``TutoringSweeps.sanction``. Rows are seeded with the T13/T14 test helpers, relative to the real
clock, because every guard compares with the database ``now()``.

The helpers at the top (classes, callers, ``safety_client``) are imported by the other T21 test
files.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Literal

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from lemely.core.tutor_directory import student_label
from lemely.db.booking_repo import ADMIN_CANCEL_REASON, SYSTEM_CANCEL_REASON, BookingService
from lemely.db.class_repo import ClassService
from lemely.db.models.enums import (
    BookingParty,
    BookingState,
    GrantRevokeReason,
    Role,
    TutorApprovalDecision,
    TutorListingState,
)
from lemely.db.models.orgs import ClassEnrollment, School, SchoolClass
from lemely.db.models.tutoring import TutorApprovalEvent, TutorBookingNote, TutorProfile
from lemely.db.notification_prefs_repo import NotificationPreferencesService
from lemely.db.notification_repo import NotificationService
from lemely.db.parent_repo import ParentLinkService
from lemely.db.tutor_approval_repo import IllegalApprovalTransitionError, TutorApprovalRepository
from lemely.db.tutor_evidence_repo import TutorEvidenceRepository
from lemely.db.tutor_grant_repo import AccessEnded, TutorGrantRepository
from lemely.db.tutor_outcomes_repo import TutorOutcomesRepository
from lemely.db.tutor_profile_repo import TutorProfileRepository
from lemely.db.tutoring_blocks_repo import BlockCaller, BlockOutcome, TutoringBlocksRepository
from lemely.db.tutoring_sweeps import AlreadyClosedError, SweepResult, TutoringSweeps
from lemely.web.deps import (
    get_class_service,
    get_notification_service,
    get_parent_link_service,
    get_push_transport,
    get_user_mirror,
)
from lemely.web.deps_tutoring import get_tutor_profile_repo
from lemely.web.push import RecordingPushTransport
from lemely.web.routers import (
    admin_tutor_sanctions,
    parent_bookings,
    student_bookings,
    student_tutor_access,
    tutor_bookings,
    tutoring_blocks,
    tutoring_booking,
)
from lemely.web.routers.admin_tutors import get_tutor_approval_repo
from lemely.web.routers.student_tutor_access import get_tutor_grant_repo
from lemely.web.routers.tutor_evidence import get_tutor_evidence_repo
from lemely.web.routers.tutoring_outcomes import outcomes_dto
from tests.test_booking_repo import (
    add_booking,
    add_parent,
    add_student,
    another_tutor,
    make_world,
    notes,
    outbox,
    stored,
)
from tests.test_tutor_grant_repo import add_grant, live_grant_count
from tests.test_tutor_outcomes_repo import (
    OTHER_SUBJECT,
    SUBJECT,
    WITH_X_BUCKETS,
    buckets,
    figures,
    five_members,
    outcome_world,
    read,
    x_member,
)
from tests.tutoring_app import app_with_routers
from tests.tutoring_db import (
    DbMirror,
    SeededTutor,
    act_as,
    add_tutor,
    add_user,
    emptied_after,
    tutoring_database,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

Side = Literal["student", "tutor"]
SIDES: tuple[Side, ...] = ("student", "tutor")
Reason = Literal["tutor_suspended", "tutor_closed"]


# ---------------------------------------------------------------------------
# Shared helpers (imported by the other T21 test files)
# ---------------------------------------------------------------------------


def safety_client(
    sm: sessionmaker[Session],
    *,
    notifications: object | None = None,
    transport: RecordingPushTransport | None = None,
) -> TestClient:
    """B1-B3, A5, A12 and the booking and grant reads they change, wired to the test database.

    ``notifications`` replaces the inbox service (the D5.9 proofs pass one that raises).
    """
    app = app_with_routers(
        tutoring_blocks.router,
        admin_tutor_sanctions.router,
        student_bookings.router,
        parent_bookings.router,
        tutor_bookings.router,
        student_tutor_access.router,
    )
    inbox = (
        notifications
        if notifications is not None
        else NotificationService(sm, NotificationPreferencesService(sm))
    )
    push = transport if transport is not None else RecordingPushTransport()
    sweeps = TutoringSweeps(sm)
    app.dependency_overrides.update(
        {
            tutoring_blocks.get_block_repo: lambda: TutoringBlocksRepository(sm, sweeps=sweeps),
            admin_tutor_sanctions.get_tutoring_sweeps: lambda: sweeps,
            tutoring_booking.get_booking_service: lambda: BookingService(sm),
            tutor_bookings.get_booking_service: lambda: BookingService(sm),
            get_tutor_profile_repo: lambda: TutorProfileRepository(sm),
            get_tutor_grant_repo: lambda: TutorGrantRepository(sm),
            get_tutor_approval_repo: lambda: TutorApprovalRepository(sm),
            get_tutor_evidence_repo: lambda: TutorEvidenceRepository(sm),
            get_parent_link_service: lambda: ParentLinkService(sm),
            get_class_service: lambda: ClassService(sm),
            get_user_mirror: lambda: DbMirror(sm),
            get_notification_service: lambda: inbox,
            get_push_transport: lambda: push,
        }
    )
    return TestClient(app)


def student_caller(student: uuid.UUID) -> BlockCaller:
    return BlockCaller(user_id=student, party="student")


def tutor_caller(tutor: SeededTutor) -> BlockCaller:
    return BlockCaller(user_id=tutor.user_id, party="tutor", tutor_profile_id=tutor.profile_id)


def blocks(sm: sessionmaker[Session]) -> TutoringBlocksRepository:
    return TutoringBlocksRepository(sm, sweeps=TutoringSweeps(sm))


def block(
    sm: sessionmaker[Session], tutor: SeededTutor, student: uuid.UUID, *, by: Side
) -> BlockOutcome:
    """B2 as the repository runs it; a tutor's block needs a booking or a grant first (O13)."""
    repo = blocks(sm)
    if by == "student":
        return repo.block(student_caller(student), tutor.profile_id)
    return repo.block(tutor_caller(tutor), student)


def pair(tutor: SeededTutor, student: uuid.UUID, *, by: Side) -> tuple[uuid.UUID, uuid.UUID]:
    """``(blocker_user_id, blocked_user_id)`` of a block made by ``by``."""
    return (student, tutor.user_id) if by == "student" else (tutor.user_id, student)


def sanction(
    sm: sessionmaker[Session], tutor: SeededTutor, reason: Reason, *, note: str | None = None
) -> SweepResult:
    admin = add_user(sm, Role.platform_admin)
    return TutoringSweeps(sm).sanction(
        tutor.profile_id, reason=reason, admin_user_id=admin, note=note
    )


def add_school(sm: sessionmaker[Session]) -> uuid.UUID:
    school_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(School(id=school_id, name="Nile Language School"))
    return school_id


def add_class(
    sm: sessionmaker[Session],
    teacher_id: uuid.UUID,
    *,
    school_id: uuid.UUID | None = None,
    name: str = "Saturday group",
) -> uuid.UUID:
    class_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            SchoolClass(
                id=class_id,
                teacher_id=teacher_id,
                school_id=school_id,
                name=name,
                join_code=f"J{class_id.hex[:10]}",
            )
        )
    return class_id


def enrol(sm: sessionmaker[Session], class_id: uuid.UUID, *students: uuid.UUID) -> None:
    with sm.begin() as session:
        for student in students:
            session.add(ClassEnrollment(class_id=class_id, student_id=student))


def classes_of(sm: sessionmaker[Session], student: uuid.UUID) -> set[uuid.UUID]:
    with sm() as session:
        return set(
            session.scalars(
                sa.select(ClassEnrollment.class_id).where(ClassEnrollment.student_id == student)
            )
        )


def block_row(
    sm: sessionmaker[Session], blocker: uuid.UUID, blocked: uuid.UUID
) -> tuple[datetime, datetime, datetime | None, str] | None:
    """``(created_at, updated_at, removed_at, xmin)``; ``xmin`` moves on every write of the row."""
    with sm() as session:
        row = session.execute(
            sa.text(
                "SELECT created_at, updated_at, removed_at, xmin::text FROM tutoring_blocks "
                "WHERE blocker_user_id = :a AND blocked_user_id = :b"
            ),
            {"a": blocker, "b": blocked},
        ).first()
    return None if row is None else (row[0], row[1], row[2], row[3])


def block_count(sm: sessionmaker[Session]) -> int:
    with sm() as session:
        return int(session.execute(sa.text("SELECT count(*) FROM tutoring_blocks")).scalar_one())


def grant_state(
    sm: sessionmaker[Session], grant_id: uuid.UUID
) -> tuple[datetime | None, str | None]:
    with sm() as session:
        row = session.execute(
            sa.text("SELECT revoked_at, revoke_reason::text FROM tutor_data_grants WHERE id = :g"),
            {"g": grant_id},
        ).one()
    return row[0], row[1]


def add_note(
    sm: sessionmaker[Session], booking_id: uuid.UUID, author: uuid.UUID, party: str, body: str
) -> uuid.UUID:
    note_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            TutorBookingNote(
                id=note_id,
                booking_id=booking_id,
                author_user_id=author,
                author_party=BookingParty(party),
                body=body,
            )
        )
    return note_id


@pytest.fixture(scope="module")
def tutoring_db() -> Iterator[sessionmaker[Session]]:
    with tutoring_database() as factory:
        yield factory


@pytest.fixture
def sm(tutoring_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(tutoring_db)


@pytest.fixture
def client(sm: sessionmaker[Session]) -> Iterator[TestClient]:
    test_client = safety_client(sm)
    yield test_client
    test_client.app.dependency_overrides.clear()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# School-less class enrolments (SC-2 a and b)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("by", SIDES)
def test_block_removes_school_less_enrolment_keeps_school_enrolment(
    sm: sessionmaker[Session], by: Side
) -> None:
    """SC-2a: the student leaves the tutor's school-less classes; school classes and other
    teachers' classes keep them, and a classmate keeps the tutor's class."""
    w = make_world(sm)
    add_booking(sm, w, state="completed", starts_in=-timedelta(days=20))  # O13 for a tutor
    classmate = add_student(sm)
    other_teacher = add_user(sm, Role.teacher)
    school = add_school(sm)
    tutors_own = add_class(sm, w.tutor.user_id, name="Saturday group")
    tutors_school = add_class(sm, w.tutor.user_id, school_id=school, name="School physics")
    someone_elses = add_class(sm, other_teacher, name="Another group")
    enrol(sm, tutors_own, w.student, classmate)
    enrol(sm, tutors_school, w.student)
    enrol(sm, someone_elses, w.student)

    outcome = block(sm, w.tutor, w.student, by=by)

    assert outcome.created
    assert outcome.sweep is not None
    assert outcome.sweep.enrolments_removed == 1
    assert classes_of(sm, w.student) == {tutors_school, someone_elses}
    assert classes_of(sm, classmate) == {tutors_own}


def test_suspension_removes_school_less_enrolments_of_tutoring_students_only(
    sm: sessionmaker[Session],
) -> None:
    """SC-2b: every student with any booking or any grant with the tutor, in any state, leaves
    the tutor's school-less classes; a classmate with neither stays, as do school classes."""
    w = make_world(sm)
    booked = w.student
    add_booking(sm, w, state="cancelled", starts_in=-timedelta(days=30))
    granted = add_student(sm)
    add_grant(sm, granted, w.tutor, revoked=GrantRevokeReason.student)
    child = add_student(sm)
    parent = add_parent(sm, child)
    add_booking(sm, w, state="declined", student=child, requested_by=parent, party="parent")
    unrelated = add_student(sm)
    other_tutor = another_tutor(sm, w.subject)
    with_other_tutor = add_student(sm)
    add_booking(
        sm,
        w,
        state="completed",
        starts_in=-timedelta(days=3),
        tutor=other_tutor,
        student=with_other_tutor,
    )
    school = add_school(sm)
    own = add_class(sm, w.tutor.user_id)
    at_school = add_class(sm, w.tutor.user_id, school_id=school, name="School physics")
    other_tutors_class = add_class(sm, other_tutor.user_id, name="Other tutor's group")
    everyone = (booked, granted, child, unrelated, with_other_tutor)
    enrol(sm, own, *everyone)
    enrol(sm, at_school, *everyone)
    enrol(sm, other_tutors_class, booked)

    result = sanction(sm, w.tutor, "tutor_suspended")

    assert result.enrolments_removed == 3
    for student in (granted, child):
        assert classes_of(sm, student) == {at_school}
    assert classes_of(sm, booked) == {at_school, other_tutors_class}
    assert classes_of(sm, unrelated) == {own, at_school}
    assert classes_of(sm, with_other_tutor) == {own, at_school}


def test_close_removes_school_less_enrolments(sm: sessionmaker[Session]) -> None:
    """A close removes every enrolment in the tutor's school-less classes (SPEC §i.6); school
    classes keep theirs."""
    w = make_world(sm)
    add_booking(sm, w, state="completed", starts_in=-timedelta(days=3))
    unrelated = add_student(sm)
    school = add_school(sm)
    own = add_class(sm, w.tutor.user_id)
    second = add_class(sm, w.tutor.user_id, name="Evening group")
    at_school = add_class(sm, w.tutor.user_id, school_id=school, name="School physics")
    enrol(sm, own, w.student, unrelated)
    enrol(sm, second, unrelated)
    enrol(sm, at_school, w.student, unrelated)

    result = sanction(sm, w.tutor, "tutor_closed")

    assert result.enrolments_removed == 3
    assert classes_of(sm, w.student) == {at_school}
    assert classes_of(sm, unrelated) == {at_school}


# ---------------------------------------------------------------------------
# Grants (SC-3) and "restores nothing"
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("reason", "stored_reason"),
    [
        ("tutor_suspended", GrantRevokeReason.tutor_suspended),
        ("tutor_closed", GrantRevokeReason.tutor_closed),
    ],
)
def test_authz_suspension_revokes_grants_with_reason(
    sm: sessionmaker[Session], reason: Reason, stored_reason: GrantRevokeReason
) -> None:
    tutor = add_tutor(sm)
    first, second, earlier = add_student(sm), add_student(sm), add_student(sm)
    live = sorted([add_grant(sm, first, tutor), add_grant(sm, second, tutor)])
    ended = add_grant(sm, earlier, tutor, revoked=GrantRevokeReason.student)
    other_tutor = add_tutor(sm, first_name="Omar")
    untouched = add_grant(sm, first, other_tutor)
    grants = TutorGrantRepository(sm)
    assert grants.require_valid_grant(tutor.profile_id, first) is not None  # valid before

    result = sanction(sm, tutor, reason)

    assert sorted(item.grant_id for item in result.revoked) == live
    assert result.revoke_reason is stored_reason
    for grant in live:
        revoked_at, why = grant_state(sm, grant)
        assert revoked_at is not None
        assert why == stored_reason.value
    assert grant_state(sm, ended)[1] == "student"
    assert grant_state(sm, untouched) == (None, None)
    with pytest.raises(AccessEnded):
        grants.require_valid_grant(tutor.profile_id, first)


def test_authz_reinstatement_does_not_restore_grants(sm: sessionmaker[Session]) -> None:
    """SPEC §a.3, SC-3: reinstating a suspended tutor (A3) restores no grant, no booking and
    no enrolment."""
    w = make_world(sm)
    grant = add_grant(sm, w.student, w.tutor)
    upcoming = add_booking(sm, w, state="accepted", starts_in=timedelta(days=3))
    own = add_class(sm, w.tutor.user_id)
    enrol(sm, own, w.student)
    with sm.begin() as session:  # approved after its last submission: reinstates to listed
        session.execute(
            sa.text("UPDATE tutor_profiles SET listed_at = first_listed_at WHERE id = :t"),
            {"t": w.tutor.profile_id},
        )
    sanction(sm, w.tutor, "tutor_suspended")
    admin = add_user(sm, Role.platform_admin)

    outcome = TutorApprovalRepository(sm).approve(
        w.tutor.profile_id, admin_user_id=admin, documents_seen=False, note=None
    )

    assert outcome.decision is TutorApprovalDecision.reinstated
    assert outcome.listed  # listed again, yet nothing comes back
    assert grant_state(sm, grant)[1] == "tutor_suspended"
    assert live_grant_count(sm, w.student, w.tutor.profile_id) == 0
    booking = stored(sm, upcoming)
    assert booking.state is BookingState.cancelled
    assert booking.cancelled_by_party is BookingParty.platform_admin
    assert classes_of(sm, w.student) == set()
    with pytest.raises(AccessEnded):
        TutorGrantRepository(sm).require_valid_grant(w.tutor.profile_id, w.student)


# ---------------------------------------------------------------------------
# Bookings
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("by", SIDES)
def test_block_cancels_inside_24h(sm: sessionmaker[Session], by: Side) -> None:
    """A block cancels every active session of the pair not yet started, inside the 24-hour
    window too (row 15a): party ``system``, the fixed reason, no canceller."""
    w = make_world(sm)
    soon = add_booking(sm, w, state="accepted", starts_in=timedelta(hours=10))
    pending = add_booking(sm, w, state="requested", starts_in=timedelta(days=3, hours=2))
    later = add_booking(sm, w, state="accepted", starts_in=timedelta(days=5))
    started = add_booking(sm, w, state="accepted", starts_in=-timedelta(minutes=10))
    done = add_booking(sm, w, state="completed", starts_in=-timedelta(days=2))
    other = add_student(sm)
    theirs = add_booking(sm, w, state="accepted", starts_in=timedelta(hours=13), student=other)

    outcome = block(sm, w.tutor, w.student, by=by)

    assert outcome.sweep is not None
    assert [item.booking_id for item in outcome.sweep.cancelled] == [soon, pending, later]
    for booking_id in (soon, pending, later):
        row = stored(sm, booking_id)
        assert row.state is BookingState.cancelled
        assert row.cancelled_by_party is BookingParty.system
        assert row.cancel_reason == SYSTEM_CANCEL_REASON
        assert row.cancelled_by_user_id is None
    assert stored(sm, started).state is BookingState.accepted
    assert stored(sm, done).state is BookingState.completed
    assert stored(sm, theirs).state is BookingState.accepted


@pytest.mark.parametrize("reason", ["tutor_suspended", "tutor_closed"])
def test_sanction_cancels_future_sessions_as_the_platform_and_emails_the_family(
    sm: sessionmaker[Session], reason: Reason
) -> None:
    """SPEC §a.3: every active session not yet started, of every student, party
    ``platform_admin``; the emails go to the students and their parents, not to the tutor, who
    is told about the listing decision instead."""
    w = make_world(sm)
    parent = add_parent(sm, w.student)
    soon = add_booking(sm, w, state="accepted", starts_in=timedelta(hours=5))
    pending = add_booking(sm, w, state="requested", starts_in=timedelta(days=2))
    started = add_booking(sm, w, state="accepted", starts_in=-timedelta(minutes=10))
    done = add_booking(sm, w, state="completed", starts_in=-timedelta(days=3))
    other = add_student(sm, display_name="Karim Adel")
    theirs = add_booking(sm, w, state="accepted", starts_in=timedelta(days=4), student=other)

    result = sanction(sm, w.tutor, reason)

    assert [item.booking_id for item in result.cancelled] == [soon, pending, theirs]
    for booking_id in (soon, pending, theirs):
        row = stored(sm, booking_id)
        assert row.state is BookingState.cancelled
        assert row.cancelled_by_party is BookingParty.platform_admin
        assert row.cancel_reason == ADMIN_CANCEL_REASON
    assert stored(sm, started).state is BookingState.accepted
    assert stored(sm, done).state is BookingState.completed
    by_booking = {item.booking_id: item for item in result.cancelled}
    assert by_booking[soon].linked_parent_ids == (parent,)
    assert by_booking[theirs].linked_parent_ids == ()
    assert by_booking[theirs].student_label == student_label("Karim Adel", other)
    cancel_mails = {
        (recipient, key)
        for recipient, template, key in outbox(sm)
        if template == "booking_cancelled"
    }
    assert cancel_mails == {
        (w.student, f"booking:{soon}:cancelled:{w.student}"),
        (parent, f"booking:{soon}:cancelled:{parent}"),
        (w.student, f"booking:{pending}:cancelled:{w.student}"),
        (parent, f"booking:{pending}:cancelled:{parent}"),
        (other, f"booking:{theirs}:cancelled:{other}"),
    }


def test_block_sweeps_only_the_pair_and_emails_everyone_but_the_blocker(
    sm: sessionmaker[Session],
) -> None:
    w = make_world(sm)
    parent = add_parent(sm, w.student)
    mine = add_booking(sm, w, state="accepted", starts_in=timedelta(days=2))
    grant = add_grant(sm, w.student, w.tutor)
    other = add_student(sm)
    theirs = add_booking(sm, w, state="accepted", starts_in=timedelta(days=3), student=other)
    their_grant = add_grant(sm, other, w.tutor)
    elsewhere_tutor = another_tutor(sm, w.subject)
    elsewhere = add_booking(
        sm, w, state="accepted", starts_in=timedelta(days=4), tutor=elsewhere_tutor
    )
    elsewhere_grant = add_grant(sm, w.student, elsewhere_tutor)

    outcome = block(sm, w.tutor, w.student, by="student")

    sweep = outcome.sweep
    assert sweep is not None
    assert [item.booking_id for item in sweep.cancelled] == [mine]
    assert [item.grant_id for item in sweep.revoked] == [grant]
    assert sweep.revoke_reason is GrantRevokeReason.block
    assert (sweep.tutor_profile_id, sweep.tutor_user_id) == (w.tutor.profile_id, w.tutor.user_id)
    assert sweep.tutor_name == "Sara M."
    assert sweep.cancelled[0].linked_parent_ids == (parent,)
    assert sweep.cancelled[0].student_label == student_label(None, w.student)
    assert sweep.revoked[0].student_id == w.student
    assert sweep.approval_event_id is None
    assert stored(sm, theirs).state is BookingState.accepted
    assert stored(sm, elsewhere).state is BookingState.accepted
    assert grant_state(sm, their_grant) == (None, None)
    assert grant_state(sm, elsewhere_grant) == (None, None)
    assert grant_state(sm, grant)[1] == "block"
    mailed = {recipient for recipient, template, _ in outbox(sm) if template == "booking_cancelled"}
    assert mailed == {w.tutor.user_id, parent}


@pytest.mark.parametrize("by", SIDES)
def test_block_insert_cancel_and_revoke_share_one_now(sm: sessionmaker[Session], by: Side) -> None:
    """SPEC §i.8, §a.4b: the block row, the revokes and the cancellations carry one instant, the
    clock read once the tutor row is held ``FOR UPDATE``, so ``blocked_since`` equals the revoke
    and cancel instants."""
    w = make_world(sm)
    grant = add_grant(sm, w.student, w.tutor)
    upcoming = add_booking(sm, w, state="accepted", starts_in=timedelta(days=2))

    block(sm, w.tutor, w.student, by=by)

    row = block_row(sm, *pair(w.tutor, w.student, by=by))
    assert row is not None
    created_at, updated_at, removed_at, _ = row
    revoked_at, _ = grant_state(sm, grant)
    cancelled = stored(sm, upcoming)
    assert removed_at is None
    assert created_at == updated_at == revoked_at == cancelled.cancelled_at == cancelled.updated_at


@pytest.mark.parametrize("reason", ["tutor_suspended", "tutor_closed"])
def test_sanction_stamps_every_row_with_one_instant(
    sm: sessionmaker[Session], reason: Reason
) -> None:
    """SPEC §a.4b: a suspension or close stamps its cancellations, revokes, listing change and
    approval event with one instant, the clock read once the tutor row is held."""
    w = make_world(sm)
    grant = add_grant(sm, w.student, w.tutor)
    upcoming = add_booking(sm, w, state="accepted", starts_in=timedelta(days=2))

    result = sanction(sm, w.tutor, reason)

    with sm() as session:
        profile = session.get(TutorProfile, w.tutor.profile_id)
        event = session.get(TutorApprovalEvent, result.approval_event_id)
        grant_updated_at = session.execute(
            sa.text("SELECT updated_at FROM tutor_data_grants WHERE id = :g"), {"g": grant}
        ).scalar_one()
    assert profile is not None
    assert event is not None
    revoked_at, _ = grant_state(sm, grant)
    cancelled = stored(sm, upcoming)
    instants = {
        revoked_at,
        grant_updated_at,
        cancelled.cancelled_at,
        cancelled.updated_at,
        profile.updated_at,
        event.created_at,
    }
    if reason == "tutor_closed":
        instants.add(profile.closed_at)
    assert len(instants) == 1
    assert None not in instants


# ---------------------------------------------------------------------------
# Sanction bookkeeping: listing, approval event, the tutor's email
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("reason", "decision", "state"),
    [
        ("tutor_suspended", TutorApprovalDecision.suspended, TutorListingState.suspended),
        ("tutor_closed", TutorApprovalDecision.closed, TutorListingState.closed),
    ],
)
def test_sanction_moves_the_listing_records_the_event_and_queues_the_tutor_email(
    sm: sessionmaker[Session],
    reason: Reason,
    decision: TutorApprovalDecision,
    state: TutorListingState,
) -> None:
    tutor = add_tutor(sm)
    admin = add_user(sm, Role.platform_admin)

    result = TutoringSweeps(sm).sanction(
        tutor.profile_id, reason=reason, admin_user_id=admin, note="  Reported twice.  "
    )

    assert result.decision is decision
    assert result.approval_event_id is not None
    with sm() as session:
        profile = session.get(TutorProfile, tutor.profile_id)
        event = session.get(TutorApprovalEvent, result.approval_event_id)
        assert profile is not None
        assert event is not None
        assert profile.listing_state is state
        assert (profile.closed_at is not None) is (state is TutorListingState.closed)
        assert event.decision is decision
        assert event.admin_user_id == admin
        assert event.note == "Reported twice."
        assert event.documents_seen is False
        assert event.profile_snapshot["public_first_name"] == "Sara"
    assert outbox(sm) == [
        (tutor.user_id, "tutor_listing_decision", f"listing:{result.approval_event_id}")
    ]


_STATES = ("draft", "pending_review", "listed", "rejected", "suspended", "closed")


@pytest.mark.parametrize("state", _STATES)
@pytest.mark.parametrize("reason", ["tutor_suspended", "tutor_closed"])
def test_sanction_transition_table(sm: sessionmaker[Session], reason: Reason, state: str) -> None:
    """SPEC §a.3: suspend from listed, pending_review or rejected; close from anything but
    closed (409 ``already_closed``). A refusal writes nothing."""
    tutor = add_tutor(sm, state=state)
    allowed = (
        state in {"listed", "pending_review", "rejected"}
        if reason == "tutor_suspended"
        else state != "closed"
    )
    if allowed:
        result = sanction(sm, tutor, reason)
        assert result.approval_event_id is not None
        return
    expected = AlreadyClosedError if reason == "tutor_closed" else IllegalApprovalTransitionError
    with pytest.raises(expected) as refused:
        sanction(sm, tutor, reason)
    assert refused.value.code == (
        "already_closed" if reason == "tutor_closed" else "illegal_transition"
    )
    with sm() as session:
        profile = session.get(TutorProfile, tutor.profile_id)
        assert profile is not None
        assert profile.listing_state.value == state
        assert session.scalar(sa.select(sa.func.count()).select_from(TutorApprovalEvent)) == 0
    assert outbox(sm) == []


# ---------------------------------------------------------------------------
# Outcomes (ADR-T04 F1), notes (SC-11), residual (f)
# ---------------------------------------------------------------------------


def _outcome_bytes(
    repo: TutorOutcomesRepository, tutor: SeededTutor, viewer: uuid.UUID
) -> tuple[bytes, bytes]:
    """SP4's and T8's ``OutcomesDTO`` as SP4 serialises it."""
    seen = repo.outcomes_for_viewer(tutor.profile_id, viewer, Role.student)
    preview = repo.preview(tutor.profile_id)
    assert seen is not None
    assert preview is not None
    assert preview.outcomes is not None
    return (
        outcomes_dto(seen).model_dump_json().encode(),
        outcomes_dto(preview.outcomes).model_dump_json().encode(),
    )


def test_tutor_block_leaves_outcomes_unchanged(sm: sessionmaker[Session]) -> None:
    """SPEC §a.3, ADR-T04 (F1): a tutor-initiated block changes no figure, even of a member in
    the published five. Control: the member's own block of an identical tutor does change them,
    so the byte comparison can fail."""
    repo = TutorOutcomesRepository(sm)
    viewer = uuid.uuid4()
    tutor = outcome_world(sm)
    five_members(sm, tutor)
    x = x_member(sm, tutor)
    before = _outcome_bytes(repo, tutor, viewer)
    assert dict(buckets(figures(read(repo, tutor)))) == WITH_X_BUCKETS  # X is in the figure

    assert block(sm, tutor, x.student, by="tutor").created
    assert _outcome_bytes(repo, tutor, viewer) == before

    control = add_tutor(sm, subjects=(SUBJECT, OTHER_SUBJECT))
    five_members(sm, control)
    control_x = x_member(sm, control)
    control_before = _outcome_bytes(repo, control, viewer)
    assert block(sm, control, control_x.student, by="student").created
    assert _outcome_bytes(repo, control, viewer) != control_before


@pytest.mark.parametrize("by", SIDES)
def test_authz_block_keeps_notes_readable_and_reportable(
    sm: sessionmaker[Session], client: TestClient, by: Side
) -> None:
    """SC-11: after a block both sides and the linked parents still read the thread (S4, T16,
    PA3) under a booking they can still open (S2, T10, PA2); the notes are closed, not gone, and
    stay unhidden, which is what makes them reportable (O12; the report route R1 is T25's)."""
    w = make_world(sm)
    parent = add_parent(sm, w.student)
    recent = add_booking(sm, w, state="completed", starts_in=-timedelta(days=2))
    add_note(sm, recent, w.student, "student", "Thank you for the session")
    add_note(sm, recent, w.tutor.user_id, "tutor", "Practise question 4 again")

    block(sm, w.tutor, w.student, by=by)

    reads = {
        "S4": (w.student, Role.student, f"/api/student/bookings/{recent}"),
        "T16": (w.tutor.user_id, Role.teacher, f"/api/tutor/bookings/{recent}"),
        "PA3": (parent, Role.parent, f"/api/parent/children/{w.student}/bookings/{recent}"),
    }
    for name, (user, role, booking_path) in reads.items():
        act_as(client, user, role)
        opened = client.get(booking_path)
        assert opened.status_code == 200, (name, opened.text)
        page = client.get(f"{booking_path}/notes")
        assert page.status_code == 200, (name, page.text)
        body = page.json()
        assert [item["body"] for item in body["items"]] == [
            "Thank you for the session",
            "Practise question 4 again",
        ], name
        assert [item["hidden"] for item in body["items"]] == [False, False], name
        assert body["canPost"] is False, name
    assert [note.hidden_at for note in notes(sm, recent)] == [None, None]


def test_also_teaches_classes_reads_the_same_after_a_tutor_block_suspension_or_close(
    sm: sessionmaker[Session],
) -> None:
    """Residual (f), SPEC §i.8: after a tutor's block, a suspension and a close the student's
    grant reads the same, ``alsoTeachesClasses`` included: every sweep removes this student from
    the tutor's school-less classes (SC-2a, SC-2b, the close), so only the school class is left
    in all three. The student's own block is the control (``blocked``)."""
    seen: dict[str, tuple[str, tuple[str, ...]]] = {}
    for kind in ("tutor_block", "suspension", "close", "student_block"):
        w = make_world(sm)
        add_grant(sm, w.student, w.tutor)
        school = add_school(sm)
        enrol(sm, add_class(sm, w.tutor.user_id, name="Saturday group"), w.student)
        enrol(
            sm, add_class(sm, w.tutor.user_id, school_id=school, name="School physics"), w.student
        )
        [before] = TutorGrantRepository(sm).grants_for_student(w.student)
        assert sorted(before.also_teaches_classes) == ["Saturday group", "School physics"]
        if kind == "tutor_block":
            block(sm, w.tutor, w.student, by="tutor")
        elif kind == "student_block":
            block(sm, w.tutor, w.student, by="student")
        else:
            sanction(sm, w.tutor, "tutor_suspended" if kind == "suspension" else "tutor_closed")
        [after] = TutorGrantRepository(sm).grants_for_student(w.student)
        seen[kind] = (after.status, after.also_teaches_classes)

    assert seen["tutor_block"] == ("tutor_unavailable", ("School physics",))
    assert seen["suspension"] == seen["tutor_block"]
    assert seen["close"] == seen["tutor_block"]
    assert seen["student_block"] == ("blocked", ("School physics",))
