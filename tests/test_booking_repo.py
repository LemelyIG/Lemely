"""The booking service: create, compare-and-set transitions, notes, lists, sweeps (PLAN T13).

SPEC ``docs/tutoring/SPEC.md`` §a.3 (state machine, effective states, notes table), §a.4
(constraint-name error mapping), §a.4b (lock order and the guards re-checked inside the
transaction), §b.2 (the codes of SP5, SP6, S1-S5, S14, T9-T17, PA1-PA5), §b.4 (outbox rows in the
change's transaction, notices after commit) and §i.4-§i.6.

Row 18 (a tutor's late cancel needs a reason) is defended three times, each proved on its own
(P24): the core check (``test_tutor_late_cancel_without_reason_refused_by_core_422``), the
compare-and-set ``WHERE`` with the core check bypassed
(``test_tutor_late_cancel_without_reason_refused_by_cas_when_core_bypassed``) and the database
CHECK (``tests/test_db_tutoring_schema.py::test_ck_late_tutor_cancel_requires_reason``, T01).

Every booking here is seeded either through the service (create) or directly as a row (every
other state), relative to the real clock: the service compares with the database ``now()``.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import pytest
import sqlalchemy as sa
import structlog.testing
from sqlalchemy.exc import IntegrityError

from lemely.core.booking import AvailabilityRule, bookable_slots
from lemely.db import booking_repo
from lemely.db.booking_repo import (
    ADMIN_CANCEL_REASON,
    SYSTEM_CANCEL_REASON,
    AcceptDetails,
    Actor,
    BookingNotice,
    BookingRefused,
    BookingRow,
    BookingService,
)
from lemely.db.models import ParentChildLink
from lemely.db.models.enums import BookingParty, BookingState, ModerationState, Role, TutoringMode
from lemely.db.models.tutoring import (
    EmailOutbox,
    StudentTutoringPreferences,
    TutorBooking,
    TutorBookingNote,
    TutoringBlock,
    TutorReview,
)
from lemely.web.booking_view import booking_notices_for
from lemely.web.push import RecordingPushTransport
from lemely.web.tutoring_notify import send_after_commit
from tests.test_notify_email import spec_b4_rows
from tests.tutoring_db import (
    SeededTutor,
    add_block,
    add_subject,
    add_tutor,
    add_user,
    count_statements,
    emptied_after,
    set_block_removed,
    tutoring_database,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

ZONE = "Africa/Cairo"
ALL_WEEK = tuple((day, 0, 1440) for day in range(1, 8))
RULES = tuple(AvailabilityRule(day, start, end) for day, start, end in ALL_WEEK)
LINK = "https://meet.google.com/abc-defg-hij"
PLACE = "The library on Road 9, second floor"
HOUR = timedelta(hours=1)
MODES = ("virtual", "in_person", "other")


# ---------------------------------------------------------------------------
# Fixtures and seeding
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def tutoring_db() -> Iterator[sessionmaker[Session]]:
    with tutoring_database() as factory:
        yield factory


@pytest.fixture
def sm(tutoring_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(tutoring_db)


@pytest.fixture
def service(sm: sessionmaker[Session]) -> BookingService:
    return BookingService(sm)


def add_student(
    sm: sessionmaker[Session],
    *,
    acknowledged: bool = True,
    display_name: str | None = None,
    age: timedelta = timedelta(days=60),
) -> uuid.UUID:
    student = add_user(sm, Role.student, display_name=display_name)
    with sm.begin() as session:
        session.execute(
            sa.text(
                "UPDATE users SET created_at = now() - make_interval(secs => :s) WHERE id = :u"
            ),
            {"s": age.total_seconds(), "u": student},
        )
        if acknowledged:
            session.add(
                StudentTutoringPreferences(
                    user_id=student, safety_notice_acknowledged_at=sa.func.now()
                )
            )
    return student


def add_parent(sm: sessionmaker[Session], *children: uuid.UUID) -> uuid.UUID:
    parent = add_user(sm, Role.parent)
    with sm.begin() as session:
        for child in children:
            session.add(ParentChildLink(parent_id=parent, child_id=child))
    return parent


def unlink(sm: sessionmaker[Session], parent: uuid.UUID, child: uuid.UUID) -> None:
    with sm.begin() as session:
        session.execute(
            sa.delete(ParentChildLink).where(
                ParentChildLink.parent_id == parent, ParentChildLink.child_id == child
            )
        )


def set_listing(sm: sessionmaker[Session], tutor: SeededTutor, state: str) -> None:
    with sm.begin() as session:
        session.execute(
            sa.text(
                "UPDATE tutor_profiles SET listing_state = CAST(:s AS tutorlistingstate), "
                "closed_at = CASE WHEN :s = 'closed' THEN now() END WHERE id = :t"
            ),
            {"s": state, "t": tutor.profile_id},
        )


@dataclass(frozen=True)
class World:
    tutor: SeededTutor
    subject: str
    student: uuid.UUID

    @property
    def tutor_actor(self) -> Actor:
        return Actor(user_id=self.tutor.user_id, party="tutor")

    @property
    def student_actor(self) -> Actor:
        return Actor(user_id=self.student, party="student")


def make_world(
    sm: sessionmaker[Session],
    *,
    modes: tuple[str, ...] = MODES,
    state: str = "listed",
    paused: bool = False,
    acknowledged: bool = True,
    display_name: str | None = None,
) -> World:
    subject = add_subject(sm)
    tutor = add_tutor(
        sm, subjects=(subject,), modes=modes, rules=ALL_WEEK, state=state, paused=paused
    )
    student = add_student(sm, acknowledged=acknowledged, display_name=display_name)
    return World(tutor=tutor, subject=subject, student=student)


def another_tutor(sm: sessionmaker[Session], subject: str) -> SeededTutor:
    return add_tutor(sm, subjects=(subject,), modes=MODES, rules=ALL_WEEK)


@pytest.fixture
def w(sm: sessionmaker[Session]) -> World:
    return make_world(sm)


def slot(after: timedelta = timedelta(hours=30), *, duration: timedelta = HOUR) -> datetime:
    """The first start ``core.booking.bookable_slots`` offers at least ``after`` from now."""
    now = datetime.now(UTC)
    first_day = now.astimezone(ZoneInfo(ZONE)).date()
    offered = bookable_slots(
        RULES, zone=ZONE, start=first_day, days=30, duration=duration, busy=(), now=now
    )
    return next(start for start, _ in offered if start >= now + after)


_DEFAULT = object()


def request(
    service: BookingService,
    w: World,
    *,
    requester: Actor | None = None,
    student_id: object = _DEFAULT,
    tutor: SeededTutor | None = None,
    subject: str | None = None,
    starts_at: datetime | None = None,
    duration: int = 60,
    mode: str = "virtual",
    other_mode_note: str | None = None,
    first_note: str | None = None,
) -> BookingRow:
    actor = requester or w.student_actor
    if student_id is _DEFAULT:
        student_id = None if actor.party == "student" else w.student
    assert student_id is None or isinstance(student_id, uuid.UUID)
    return service.create(
        requester=actor,
        tutor_profile_id=(tutor or w.tutor).profile_id,
        student_id=student_id,
        subject_code=subject or w.subject,
        mode=mode,  # type: ignore[arg-type]
        starts_at=starts_at or slot(),
        duration_minutes=duration,
        other_mode_note=other_mode_note,
        first_note=first_note,
    )


def add_booking(
    sm: sessionmaker[Session],
    w: World,
    *,
    state: str = "requested",
    starts_in: timedelta = timedelta(days=3),
    starts_at: datetime | None = None,
    duration: timedelta = HOUR,
    mode: str = "virtual",
    student: uuid.UUID | None = None,
    tutor: SeededTutor | None = None,
    subject: str | None = None,
    requested_by: uuid.UUID | None = None,
    party: str = "student",
    **columns: object,
) -> uuid.UUID:
    """One booking row in ``state``, coherent with every ``ck_tutor_bookings_*`` CHECK."""
    now = datetime.now(UTC)
    starts_at = starts_at or now + starts_in
    ends_at = starts_at + duration
    booking_state = BookingState(state)
    fields: dict[str, object] = {}
    if booking_state in {BookingState.accepted, BookingState.completed, BookingState.no_show}:
        fields["accepted_at"] = now - timedelta(days=10)
        if mode == "virtual":
            fields["meeting_link"] = LINK
        if mode == "in_person":
            fields["location_detail"] = PLACE
    if booking_state is BookingState.completed:
        fields["completed_at"] = now
        fields["completed_by_party"] = BookingParty.tutor
    if booking_state is BookingState.no_show:
        fields["no_show_marked_at"] = now
    if booking_state is BookingState.cancelled:
        fields["cancelled_at"] = now - timedelta(days=5)
        fields["cancelled_by_party"] = BookingParty.student
    if booking_state is BookingState.declined:
        fields["declined_at"] = now
    if booking_state is BookingState.expired:
        fields["expired_at"] = now
    fields.update(columns)
    student_id = student or w.student
    booking_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            TutorBooking(
                id=booking_id,
                tutor_profile_id=(tutor or w.tutor).profile_id,
                student_id=student_id,
                requested_by_user_id=requested_by or student_id,
                requested_by_party=BookingParty(party),
                subject_code=subject or w.subject,
                mode=TutoringMode(mode),
                starts_at=starts_at,
                ends_at=ends_at,
                state=booking_state,
                **fields,
            )
        )
    return booking_id


def stored(sm: sessionmaker[Session], booking_id: uuid.UUID) -> TutorBooking:
    with sm() as session:
        row = session.get(TutorBooking, booking_id)
        assert row is not None
        session.expunge(row)
        return row


def outbox(sm: sessionmaker[Session]) -> list[tuple[uuid.UUID, str, str]]:
    with sm() as session:
        rows = session.execute(
            sa.select(EmailOutbox.recipient_user_id, EmailOutbox.template, EmailOutbox.dedupe_key)
        ).all()
    return sorted((row[0], row[1], row[2]) for row in rows)


def notes(sm: sessionmaker[Session], booking_id: uuid.UUID) -> list[TutorBookingNote]:
    with sm() as session:
        found = list(
            session.scalars(
                sa.select(TutorBookingNote)
                .where(TutorBookingNote.booking_id == booking_id)
                .order_by(TutorBookingNote.created_at, TutorBookingNote.id)
            )
        )
        for note in found:
            session.expunge(note)
        return found


def refused(excinfo: pytest.ExceptionInfo[BookingRefused]) -> tuple[str, int]:
    return excinfo.value.code, excinfo.value.status


# ---------------------------------------------------------------------------
# Create (SP6)
# ---------------------------------------------------------------------------


def test_create_student_request_records_actor_subject_and_returns_the_row(
    sm: sessionmaker[Session], service: BookingService, w: World
) -> None:
    start = slot()
    row = request(service, w, starts_at=start, first_note="  Can we start with algebra?  ")

    assert row.state == "requested"
    assert (row.student_id, row.requested_by_user_id, row.requested_by_party) == (
        w.student,
        w.student,
        "student",
    )
    assert (row.starts_at, row.ends_at) == (start, start + HOUR)
    assert row.tutor.tutor_id == w.tutor.profile_id
    assert row.tutor_user_id == w.tutor.user_id
    assert row.subject_code == w.subject
    assert row.notice == BookingNotice(
        event="requested", actor_user_id=w.student, linked_parent_ids=()
    )
    db = stored(sm, row.id)
    assert db.state is BookingState.requested
    assert db.requested_by_party is BookingParty.student
    (note,) = notes(sm, row.id)
    assert (note.author_party, note.author_user_id, note.body) == (
        BookingParty.student,
        w.student,
        "Can we start with algebra?",
    )


def test_create_by_parent_records_parent_as_actor_and_child_as_subject(
    sm: sessionmaker[Session], service: BookingService, w: World
) -> None:
    parent = add_parent(sm, w.student)
    row = request(service, w, requester=Actor(user_id=parent, party="parent"))
    assert (row.student_id, row.requested_by_user_id, row.requested_by_party) == (
        w.student,
        parent,
        "parent",
    )
    assert row.notice is not None
    assert row.notice.actor_user_id == parent
    assert row.notice.linked_parent_ids == (parent,)


def test_create_refuses_another_student_id_with_not_self(
    sm: sessionmaker[Session], service: BookingService, w: World
) -> None:
    other = add_student(sm)
    with pytest.raises(BookingRefused) as excinfo:
        request(service, w, student_id=other)
    assert refused(excinfo) == ("not_self", 403)
    request(service, w, student_id=w.student)  # its own id is fine


def test_create_by_parent_needs_a_linked_existing_child(
    sm: sessionmaker[Session], service: BookingService, w: World
) -> None:
    parent = add_parent(sm)
    actor = Actor(user_id=parent, party="parent")
    with pytest.raises(BookingRefused) as excinfo:
        request(service, w, requester=actor)
    assert refused(excinfo) == ("not_linked", 403)
    with pytest.raises(BookingRefused) as excinfo:
        request(service, w, requester=actor, student_id=uuid.uuid4())
    assert refused(excinfo) == ("not_found", 404)
    with pytest.raises(BookingRefused) as excinfo:
        request(service, w, requester=actor, student_id=None)
    assert refused(excinfo) == ("student_required", 422)
    assert outbox(sm) == []


def test_authz_parent_first_note_rejected(
    sm: sessionmaker[Session], service: BookingService, w: World
) -> None:
    parent = add_parent(sm, w.student)
    with pytest.raises(BookingRefused) as excinfo:
        request(service, w, requester=Actor(user_id=parent, party="parent"), first_note="Hello")
    assert refused(excinfo) == ("note_not_allowed_for_parent", 422)
    with sm() as session:
        assert session.scalar(sa.select(sa.func.count()).select_from(TutorBooking)) == 0


def test_safety_notice_required_for_student_requester_only(
    sm: sessionmaker[Session], service: BookingService
) -> None:
    w = make_world(sm, acknowledged=False)
    with pytest.raises(BookingRefused) as excinfo:
        request(service, w)
    assert refused(excinfo) == ("safety_notice_required", 409)
    parent = add_parent(sm, w.student)
    row = request(service, w, requester=Actor(user_id=parent, party="parent"))
    assert row.state == "requested"


def test_authz_booking_horizon_28_days(
    sm: sessionmaker[Session], service: BookingService, w: World
) -> None:
    beyond = (datetime.now(UTC) + timedelta(days=28, hours=2)).replace(
        minute=0, second=0, microsecond=0
    )
    with pytest.raises(BookingRefused) as excinfo:
        request(service, w, starts_at=beyond)
    assert refused(excinfo) == ("beyond_horizon", 409)
    inside = request(service, w, starts_at=slot(timedelta(days=27)))
    assert inside.state == "requested"


@pytest.mark.parametrize(
    ("listing", "paused"),
    [("listed", True), ("pending_review", False), ("suspended", False), ("closed", False)],
)
def test_create_refused_unless_tutor_listed_and_not_paused(
    sm: sessionmaker[Session], service: BookingService, listing: str, paused: bool
) -> None:
    w = make_world(sm, state=listing, paused=paused)
    with pytest.raises(BookingRefused) as excinfo:
        request(service, w)
    assert refused(excinfo) == ("tutor_not_listed", 409)


def test_create_for_unknown_tutor_is_404(service: BookingService, w: World) -> None:
    ghost = SeededTutor(profile_id=uuid.uuid4(), user_id=uuid.uuid4())
    with pytest.raises(BookingRefused) as excinfo:
        request(service, w, tutor=ghost)
    assert refused(excinfo) == ("not_found", 404)


@pytest.mark.parametrize("blocker", ["student", "tutor"])
def test_create_refused_when_blocked_either_direction(
    sm: sessionmaker[Session], service: BookingService, w: World, blocker: str
) -> None:
    pair = (w.student, w.tutor.user_id)
    first, second = pair if blocker == "student" else pair[::-1]
    add_block(sm, first, second)
    with pytest.raises(BookingRefused) as excinfo:
        request(service, w)
    assert refused(excinfo) == ("blocked", 409)
    set_block_removed(sm, first, second)
    assert request(service, w).state == "requested"


def test_create_refused_when_not_bookable(
    sm: sessionmaker[Session], service: BookingService
) -> None:
    w = make_world(sm, modes=("virtual",))
    other_subject = add_subject(sm, name="Physics")
    soon = (datetime.now(UTC) + timedelta(minutes=70)).replace(second=0, microsecond=0)
    soon += timedelta(minutes=(30 - soon.minute % 30) % 30)
    cases = [
        {"subject": other_subject},  # subject not taught
        {"mode": "in_person"},  # mode not offered
        {"starts_at": slot() + timedelta(minutes=15)},  # off the slot grid
        {"starts_at": soon},  # inside MIN_NOTICE
        {"duration": 50},  # not an allowed duration
    ]
    for case in cases:
        with pytest.raises(BookingRefused) as excinfo:
            request(service, w, **case)  # type: ignore[arg-type]
        assert refused(excinfo) == ("not_bookable", 409), case
    assert outbox(sm) == []


def test_quota_booking_create_429_after_10_per_day(
    sm: sessionmaker[Session], service: BookingService, w: World
) -> None:
    for day in range(9):
        add_booking(sm, w, state="cancelled", starts_in=timedelta(days=5 + day))
    for day in range(3):  # created more than 24 hours ago: outside the window
        old = add_booking(sm, w, state="cancelled", starts_in=timedelta(days=20 + day))
        with sm.begin() as session:
            session.execute(
                sa.text(
                    "UPDATE tutor_bookings SET created_at = now() - interval '25 hours' "
                    "WHERE id = :b"
                ),
                {"b": old},
            )
    tenth = request(service, w, starts_at=slot(timedelta(hours=30)))
    assert tenth.state == "requested"
    second_tutor = another_tutor(sm, w.subject)
    with pytest.raises(BookingRefused) as excinfo:
        request(service, w, tutor=second_tutor, starts_at=slot(timedelta(hours=60)))
    assert refused(excinfo) == ("too_many_requests", 429)


def test_lazy_expiry_frees_one_pending_index(
    sm: sessionmaker[Session], service: BookingService, w: World
) -> None:
    stale = add_booking(sm, w, state="requested", starts_in=timedelta(hours=-3))
    row = request(service, w)
    assert row.state == "requested"
    expired = stored(sm, stale)
    assert expired.state is BookingState.expired
    assert expired.expired_at is not None


def test_pending_limit_counts_live_requests_only(
    sm: sessionmaker[Session], service: BookingService, w: World
) -> None:
    for index in range(2):  # stale requests to other tutors hold nothing
        add_booking(
            sm,
            w,
            tutor=another_tutor(sm, w.subject),
            state="requested",
            starts_in=timedelta(hours=-3 - index * 2),
        )
    for index in range(4):
        add_booking(
            sm,
            w,
            tutor=another_tutor(sm, w.subject),
            state="requested",
            starts_in=timedelta(days=2 + index),
        )
    fifth = request(service, w, starts_at=slot(timedelta(days=10)))
    assert fifth.state == "requested"
    with pytest.raises(BookingRefused) as excinfo:
        request(service, w, tutor=another_tutor(sm, w.subject), starts_at=slot(timedelta(days=11)))
    assert refused(excinfo) == ("pending_limit", 409)


@pytest.mark.parametrize(
    ("case", "constraint", "code"),
    [
        ("same_tutor_same_time", "excl_tutor_bookings_tutor_slot", "slot_taken"),
        ("same_student_same_time", "excl_tutor_bookings_student_slot", "student_busy"),
        ("same_pair_second_request", "uq_tutor_bookings_one_pending", "already_pending"),
    ],
)
def test_error_mapping_by_constraint_name(
    sm: sessionmaker[Session],
    service: BookingService,
    w: World,
    case: str,
    constraint: str,
    code: str,
) -> None:
    start = slot()
    request(service, w, starts_at=start)
    if case == "same_tutor_same_time":
        rival = World(tutor=w.tutor, subject=w.subject, student=add_student(sm))
        attempt = {"w": rival, "starts_at": start}
    elif case == "same_student_same_time":
        attempt = {"w": w, "tutor": another_tutor(sm, w.subject), "starts_at": start}
    else:
        attempt = {"w": w, "starts_at": slot(timedelta(hours=60))}
    with pytest.raises(BookingRefused) as excinfo:
        request(service, **attempt)  # type: ignore[arg-type]
    assert refused(excinfo) == (code, 409)
    cause = excinfo.value.__cause__
    assert isinstance(cause, IntegrityError)
    assert cause.orig.diag.constraint_name == constraint  # type: ignore[union-attr]


def test_create_free_text_rejects_contact_details(
    sm: sessionmaker[Session], service: BookingService, w: World
) -> None:
    with pytest.raises(BookingRefused) as excinfo:
        request(service, w, first_note="Call me on 0100 123 4567")
    assert refused(excinfo) == ("contact_details_not_allowed", 422)
    with pytest.raises(BookingRefused) as excinfo:
        request(service, w, mode="other", other_mode_note="Add me @studybuddy")
    assert refused(excinfo) == ("contact_details_not_allowed", 422)
    with pytest.raises(BookingRefused) as excinfo:
        request(service, w, first_note="x" * 2001)
    assert refused(excinfo) == ("text_too_long", 422)
    row = request(service, w, mode="other", other_mode_note="  A study room at school  ")
    assert row.other_mode_note == "A study room at school"
    assert notes(sm, row.id) == []


def test_create_writes_outbox_rows_for_tutor_and_parents_never_the_actor(
    sm: sessionmaker[Session], service: BookingService, w: World
) -> None:
    first_parent = add_parent(sm, w.student)
    second_parent = add_parent(sm, w.student)
    by_student = request(service, w)
    expected = {
        (w.tutor.user_id, "booking_requested"),
        (first_parent, "booking_requested_family"),
        (second_parent, "booking_requested_family"),
    }
    assert {(r, t) for r, t, _ in outbox(sm)} == expected
    assert {key for _, _, key in outbox(sm)} == {
        f"booking:{by_student.id}:requested:{recipient}" for recipient, _ in expected
    }

    with sm.begin() as session:
        session.execute(sa.delete(EmailOutbox))
    by_parent = request(
        service,
        w,
        requester=Actor(user_id=first_parent, party="parent"),
        tutor=another_tutor(sm, w.subject),
        starts_at=slot(timedelta(hours=60)),
    )
    assert {(r, t) for r, t, _ in outbox(sm)} == {
        (by_parent.tutor_user_id, "booking_requested"),
        (second_parent, "booking_requested_family"),
    }


def _outbox_key_patterns() -> list[tuple[str, re.Pattern[str]]]:
    """The booking outbox keys of SPEC §b.4's last column, as patterns."""
    templates = sorted(
        {
            template
            for row in spec_b4_rows()
            for template in re.findall(r"`([^`]+)`", row[4])
            if template.startswith("booking:")
        }
    )
    assert len(templates) >= 2  # non-vacuity: the requested key and the event key

    def pattern(template: str) -> re.Pattern[str]:
        escaped = re.escape(template)
        escaped = re.sub(r"\\\{event\\\}", "(accepted|declined|cancelled)", escaped)
        escaped = re.sub(r"\\\{[a-z_]+_id\\\}", "[0-9a-f-]{36}", escaped)
        return re.compile(f"^{escaped}$")

    return [(template, pattern(template)) for template in templates]


def test_outbox_keys_follow_the_spec_b4_column(
    sm: sessionmaker[Session], service: BookingService, w: World
) -> None:
    add_parent(sm, w.student)
    accepted = request(service, w)
    service.transition(
        booking_id=accepted.id,
        actor=w.tutor_actor,
        action="accept",
        accept=AcceptDetails(meeting_link=LINK),
    )
    service.transition(booking_id=accepted.id, actor=w.student_actor, action="cancel")
    declined = request(service, w, starts_at=slot(timedelta(hours=60)))
    service.transition(booking_id=declined.id, actor=w.tutor_actor, action="decline")

    patterns = _outbox_key_patterns()
    keys = [key for _, _, key in outbox(sm)]
    assert len(keys) >= 8  # non-vacuity: requested x2 (tutor, parent) x2, accepted, cancelled...
    for key in keys:
        assert any(compiled.match(key) for _, compiled in patterns), key
    for template, compiled in patterns:
        assert any(compiled.match(key) for key in keys), template


# ---------------------------------------------------------------------------
# Transitions (S3, S14, T11-T15, PA4, PA5)
# ---------------------------------------------------------------------------


def test_tutor_late_cancel_persists_reason_and_party(
    sm: sessionmaker[Session], service: BookingService, w: World
) -> None:
    booking = add_booking(sm, w, state="accepted", starts_in=timedelta(hours=10))
    row = service.transition(
        booking_id=booking, actor=w.tutor_actor, action="cancel", reason="  I am unwell today  "
    )
    assert (row.state, row.cancelled_by_party, row.cancel_reason) == (
        "cancelled",
        "tutor",
        "I am unwell today",
    )
    db = stored(sm, booking)
    assert db.cancelled_by_party is BookingParty.tutor
    assert db.cancelled_by_user_id == w.tutor.user_id
    assert db.cancelled_at is not None
    assert row.notice == BookingNotice(
        event="cancelled",
        actor_user_id=w.tutor.user_id,
        linked_parent_ids=(),
        late_tutor_cancel=True,
    )


#: The compare-and-set statement of every booking transition.
UPDATE_BOOKINGS = re.compile(r"\s*UPDATE\s+tutor_bookings\b", re.IGNORECASE)


@pytest.mark.parametrize("reason", [None, "", "   "])
def test_tutor_late_cancel_without_reason_refused_by_core_422(
    sm: sessionmaker[Session], service: BookingService, w: World, reason: str | None
) -> None:
    """The service's own core check refuses before the compare-and-set is even tried.

    The code alone cannot tell the layers apart: without that check the ``UPDATE`` matches no
    row and ``_missed`` re-runs the core, giving the same 422. So the proof is that no
    ``UPDATE tutor_bookings`` statement was sent.
    """
    booking = add_booking(sm, w, state="accepted", starts_in=timedelta(hours=10))
    with count_statements(sm) as seen, pytest.raises(BookingRefused) as excinfo:
        service.transition(booking_id=booking, actor=w.tutor_actor, action="cancel", reason=reason)
    assert refused(excinfo) == ("reason_required", 422)
    assert any("FROM tutor_bookings" in statement for statement in seen)  # non-vacuity
    assert [statement for statement in seen if UPDATE_BOOKINGS.match(statement)] == []
    assert stored(sm, booking).state is BookingState.accepted
    assert outbox(sm) == []


def test_tutor_late_cancel_without_reason_refused_by_cas_when_core_bypassed(
    sm: sessionmaker[Session],
    service: BookingService,
    w: World,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The core check is switched off: the compare-and-set ``WHERE`` alone still refuses.

    Zero rows update, so the service refuses with a 409 and nothing reaches the
    database CHECK (which would raise an ``IntegrityError`` instead).
    """
    monkeypatch.setattr(booking_repo, "check_transition", lambda *args, **kwargs: None)
    booking = add_booking(sm, w, state="accepted", starts_in=timedelta(hours=10))
    with pytest.raises(BookingRefused) as excinfo:
        service.transition(booking_id=booking, actor=w.tutor_actor, action="cancel", reason=None)
    assert excinfo.value.status == 409
    db = stored(sm, booking)
    assert (db.state, db.cancel_reason, db.cancelled_at) == (BookingState.accepted, None, None)
    assert outbox(sm) == []


def test_tutor_cancel_more_than_24h_ahead_needs_no_reason(
    sm: sessionmaker[Session], service: BookingService, w: World
) -> None:
    booking = add_booking(sm, w, state="accepted", starts_in=timedelta(hours=30))
    row = service.transition(booking_id=booking, actor=w.tutor_actor, action="cancel")
    assert (row.state, row.cancel_reason) == ("cancelled", None)
    assert row.notice is not None
    assert row.notice.late_tutor_cancel is False


def test_tutor_cancel_after_start_refused_already_started(
    sm: sessionmaker[Session], service: BookingService, w: World
) -> None:
    booking = add_booking(sm, w, state="accepted", starts_in=timedelta(minutes=-10))
    with pytest.raises(BookingRefused) as excinfo:
        service.transition(booking_id=booking, actor=w.tutor_actor, action="cancel", reason="ill")
    assert refused(excinfo) == ("already_started", 409)


def test_student_cancel_inside_24h_refused_cancel_window_closed(
    sm: sessionmaker[Session], service: BookingService, w: World
) -> None:
    late = add_booking(sm, w, state="accepted", starts_in=timedelta(hours=10))
    with pytest.raises(BookingRefused) as excinfo:
        service.transition(booking_id=late, actor=w.student_actor, action="cancel")
    assert refused(excinfo) == ("cancel_window_closed", 409)
    early = add_booking(sm, w, state="accepted", starts_in=timedelta(hours=30))
    row = service.transition(
        booking_id=early, actor=w.student_actor, action="cancel", reason="Exam"
    )
    assert (row.state, row.cancelled_by_party, row.cancel_reason) == (
        "cancelled",
        "student",
        "Exam",
    )
    pending = add_booking(
        sm, w, state="requested", starts_in=timedelta(hours=5), tutor=another_tutor(sm, w.subject)
    )
    assert service.transition(booking_id=pending, actor=w.student_actor, action="cancel").state == (
        "cancelled"
    )


def test_authz_parent_cancel_requires_requester(
    sm: sessionmaker[Session], service: BookingService, w: World
) -> None:
    requester = add_parent(sm, w.student)
    other = add_parent(sm, w.student)
    booking = add_booking(
        sm,
        w,
        state="requested",
        requested_by=requester,
        party="parent",
        starts_in=timedelta(days=4),
    )
    with pytest.raises(BookingRefused) as excinfo:
        service.transition(
            booking_id=booking,
            actor=Actor(user_id=other, party="parent", child_id=w.student),
            action="cancel",
        )
    assert refused(excinfo) == ("not_requester", 403)
    by_student = add_booking(
        sm, w, state="requested", tutor=another_tutor(sm, w.subject), starts_in=timedelta(days=5)
    )
    with pytest.raises(BookingRefused) as excinfo:
        service.transition(
            booking_id=by_student,
            actor=Actor(user_id=requester, party="parent", child_id=w.student),
            action="cancel",
        )
    assert refused(excinfo) == ("not_requester", 403)
    row = service.transition(
        booking_id=booking,
        actor=Actor(user_id=requester, party="parent", child_id=w.student),
        action="cancel",
    )
    assert (row.state, row.cancelled_by_party) == ("cancelled", "parent")
    assert stored(sm, booking).cancelled_by_user_id == requester


def test_authz_parent_actions_refused_after_unlink(
    sm: sessionmaker[Session], service: BookingService, w: World
) -> None:
    parent = add_parent(sm, w.student)
    booking = add_booking(
        sm, w, state="requested", requested_by=parent, party="parent", starts_in=timedelta(days=4)
    )
    unlink(sm, parent, w.student)
    with pytest.raises(BookingRefused) as excinfo:
        service.transition(
            booking_id=booking,
            actor=Actor(user_id=parent, party="parent", child_id=w.student),
            action="cancel",
        )
    assert refused(excinfo) == ("not_linked", 403)
    assert stored(sm, booking).state is BookingState.requested


def test_failed_transition_writes_no_outbox_row(
    sm: sessionmaker[Session],
    service: BookingService,
    w: World,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A refusal writes nothing, and neither does a change that fails after queueing its emails.

    The refusals all raise before any email is queued, so on their own they cannot show where the
    outbox rows are written. The second half fails the transition *after* both emails were queued
    (``is_late_cancel`` runs in ``_announce`` after ``_enqueue_emails``): nothing may remain,
    because the rows belong to the change's own transaction (SPEC §b.4, D5.9 §1).
    """
    add_parent(sm, w.student)
    booking = add_booking(sm, w, state="accepted", starts_in=timedelta(hours=10))
    refusals = [
        (w.student_actor, "cancel", None),  # cancel_window_closed
        (w.tutor_actor, "cancel", None),  # reason_required
        (w.tutor_actor, "complete", None),  # not_ended
        (w.tutor_actor, "decline", None),  # illegal_transition
    ]
    for actor, action, reason in refusals:
        with pytest.raises(BookingRefused):
            service.transition(booking_id=booking, actor=actor, action=action, reason=reason)  # type: ignore[arg-type]
    assert outbox(sm) == []
    assert stored(sm, booking).state is BookingState.accepted

    early = add_booking(sm, w, state="accepted", starts_in=timedelta(hours=30))
    queued: list[object] = []
    real_enqueue = booking_repo.enqueue_in_session

    def counting_enqueue(*args: object, **kwargs: object) -> bool:
        queued.append(kwargs["template"])
        return real_enqueue(*args, **kwargs)  # type: ignore[arg-type]

    def failing_late_check(**_: object) -> bool:
        raise RuntimeError("failed after the emails were queued")

    monkeypatch.setattr(booking_repo, "enqueue_in_session", counting_enqueue)
    monkeypatch.setattr(booking_repo, "is_late_cancel", failing_late_check)
    with pytest.raises(RuntimeError, match="after the emails were queued"):
        service.transition(booking_id=early, actor=w.student_actor, action="cancel")
    assert queued == ["booking_cancelled", "booking_cancelled"]  # the tutor and the parent
    assert outbox(sm) == []
    db = stored(sm, early)
    assert (db.state, db.cancelled_at, db.cancelled_by_user_id) == (
        BookingState.accepted,
        None,
        None,
    )


def test_cancel_quota_429_after_10_per_day(
    sm: sessionmaker[Session], service: BookingService, w: World
) -> None:
    for day in range(10):
        add_booking(
            sm,
            w,
            state="cancelled",
            starts_in=timedelta(days=5 + day),
            cancelled_at=datetime.now(UTC) - timedelta(hours=2),
            cancelled_by_user_id=w.student,
        )
    booking = add_booking(sm, w, state="requested", starts_in=timedelta(days=2))
    with pytest.raises(BookingRefused) as excinfo:
        service.transition(booking_id=booking, actor=w.student_actor, action="cancel")
    assert refused(excinfo) == ("too_many_requests", 429)
    assert stored(sm, booking).state is BookingState.requested


def test_accept_virtual_needs_an_allowlisted_link(
    sm: sessionmaker[Session], service: BookingService, w: World
) -> None:
    parent = add_parent(sm, w.student)
    booking = add_booking(sm, w, state="requested", starts_in=timedelta(days=2))
    for details in (None, AcceptDetails(), AcceptDetails(meeting_link="http://zoom.us/j/1")):
        with pytest.raises(BookingRefused) as excinfo:
            service.transition(
                booking_id=booking, actor=w.tutor_actor, action="accept", accept=details
            )
        assert refused(excinfo) == ("meeting_link_not_allowed", 422)
    row = service.transition(
        booking_id=booking,
        actor=w.tutor_actor,
        action="accept",
        accept=AcceptDetails(meeting_link=LINK, location_detail="ignored for virtual"),
    )
    assert (row.state, row.meeting_link, row.location_detail) == ("accepted", LINK, None)
    assert row.accepted_at is not None
    assert {(r, t) for r, t, _ in outbox(sm)} == {
        (w.student, "booking_accepted"),
        (parent, "booking_accepted"),
    }


def test_accept_in_person_needs_a_contact_free_location(
    sm: sessionmaker[Session], service: BookingService, w: World
) -> None:
    booking = add_booking(sm, w, state="requested", mode="in_person", starts_in=timedelta(days=2))
    with pytest.raises(BookingRefused) as excinfo:
        service.transition(booking_id=booking, actor=w.tutor_actor, action="accept")
    assert refused(excinfo) == ("location_required", 422)
    with pytest.raises(BookingRefused) as excinfo:
        service.transition(
            booking_id=booking,
            actor=w.tutor_actor,
            action="accept",
            accept=AcceptDetails(location_detail="Ring me at 01001234567 at the gate"),
        )
    assert refused(excinfo) == ("contact_details_not_allowed", 422)
    row = service.transition(
        booking_id=booking,
        actor=w.tutor_actor,
        action="accept",
        accept=AcceptDetails(location_detail=f"  {PLACE}  ", meeting_link=LINK),
    )
    assert (row.state, row.location_detail, row.meeting_link) == ("accepted", PLACE, None)


DISALLOWED_LINK = "http://zoom.us/j/1"
CONTACT_PLACE = "Ring me at 01001234567 at the gate"


@pytest.mark.parametrize(
    ("mode", "details", "kept"),
    [
        ("virtual", AcceptDetails(meeting_link=LINK, location_detail=CONTACT_PLACE), (LINK, None)),
        ("virtual", AcceptDetails(meeting_link=LINK, location_detail="x" * 400), (LINK, None)),
        (
            "in_person",
            AcceptDetails(location_detail=PLACE, meeting_link=DISALLOWED_LINK),
            (None, PLACE),
        ),
        (
            "other",
            AcceptDetails(meeting_link=DISALLOWED_LINK, location_detail=CONTACT_PLACE),
            (None, None),
        ),
    ],
    ids=["virtual-contact-place", "virtual-long-place", "in-person-bad-link", "other-both-bad"],
)
def test_accept_checks_only_the_detail_its_mode_keeps(
    sm: sessionmaker[Session],
    service: BookingService,
    w: World,
    mode: str,
    details: AcceptDetails,
    kept: tuple[str | None, str | None],
) -> None:
    """A detail the session's mode does not use is dropped unread (SPEC §a.3, SC-7).

    It is never stored (the ``meeting_link_mode``/``location_detail_mode`` CHECKs), so it can
    carry no contact detail anywhere, and it must not refuse the accept either.
    """
    booking = add_booking(sm, w, state="requested", mode=mode, starts_in=timedelta(days=2))
    row = service.transition(
        booking_id=booking, actor=w.tutor_actor, action="accept", accept=details
    )
    assert (row.state, row.meeting_link, row.location_detail) == ("accepted", *kept)
    db = stored(sm, booking)
    assert (db.meeting_link, db.location_detail) == kept


@pytest.mark.parametrize("blocker", ["student", "tutor"])
def test_authz_accept_refused_when_blocked(
    sm: sessionmaker[Session], service: BookingService, w: World, blocker: str
) -> None:
    booking = add_booking(sm, w, state="requested", starts_in=timedelta(days=2))
    pair = (w.student, w.tutor.user_id)
    add_block(sm, *(pair if blocker == "student" else pair[::-1]))
    with pytest.raises(BookingRefused) as excinfo:
        service.transition(
            booking_id=booking,
            actor=w.tutor_actor,
            action="accept",
            accept=AcceptDetails(meeting_link=LINK),
        )
    assert refused(excinfo) == ("access_ended", 409)
    declined = service.transition(booking_id=booking, actor=w.tutor_actor, action="decline")
    assert declined.state == "declined"  # a block withholds accept only


@pytest.mark.parametrize(
    ("listing", "code"), [("suspended", "tutor_suspended"), ("closed", "tutor_closed")]
)
@pytest.mark.parametrize("action", ["accept", "decline", "cancel", "complete", "no_show"])
def test_authz_tutor_writes_refused_when_suspended_or_closed(
    sm: sessionmaker[Session],
    service: BookingService,
    w: World,
    listing: str,
    code: str,
    action: str,
) -> None:
    state, starts_in = {
        "accept": ("requested", timedelta(days=2)),
        "decline": ("requested", timedelta(days=2)),
        "cancel": ("accepted", timedelta(days=2)),
        "complete": ("accepted", timedelta(hours=-3)),
        "no_show": ("accepted", timedelta(hours=-3)),
    }[action]
    booking = add_booking(sm, w, state=state, starts_in=starts_in)
    set_listing(sm, w.tutor, listing)
    with pytest.raises(BookingRefused) as excinfo:
        service.transition(
            booking_id=booking,
            actor=w.tutor_actor,
            action=action,  # type: ignore[arg-type]
            accept=AcceptDetails(meeting_link=LINK),
            reason="Reason",
        )
    assert refused(excinfo) == (code, 409)
    assert stored(sm, booking).state is BookingState(state)


@pytest.mark.parametrize("listing", ["draft", "rejected"])
def test_accept_refused_for_a_rejected_listing(
    sm: sessionmaker[Session], service: BookingService, w: World, listing: str
) -> None:
    booking = add_booking(sm, w, state="requested", starts_in=timedelta(days=2))
    set_listing(sm, w.tutor, listing)
    with pytest.raises(BookingRefused) as excinfo:
        service.transition(
            booking_id=booking,
            actor=w.tutor_actor,
            action="accept",
            accept=AcceptDetails(meeting_link=LINK),
        )
    assert refused(excinfo) == ("tutor_not_listed", 409)
    # The tutor is told about their own profile, not "this tutor" as a family is (SP6).
    message = excinfo.value.message.lower()
    assert "your" in message, message
    assert "this tutor" not in message, message
    set_listing(sm, w.tutor, "pending_review")  # pending review may still accept (§a.3)
    row = service.transition(
        booking_id=booking,
        actor=w.tutor_actor,
        action="accept",
        accept=AcceptDetails(meeting_link=LINK),
    )
    assert row.state == "accepted"


def test_accept_after_start_refused_already_started(
    sm: sessionmaker[Session], service: BookingService, w: World
) -> None:
    booking = add_booking(sm, w, state="requested", starts_in=timedelta(minutes=-5))
    with pytest.raises(BookingRefused) as excinfo:
        service.transition(
            booking_id=booking,
            actor=w.tutor_actor,
            action="accept",
            accept=AcceptDetails(meeting_link=LINK),
        )
    assert refused(excinfo) == ("already_started", 409)


def test_decline_records_reason_and_tells_the_family(
    sm: sessionmaker[Session], service: BookingService, w: World
) -> None:
    booking = add_booking(sm, w, state="requested", starts_in=timedelta(days=2))
    row = service.transition(
        booking_id=booking, actor=w.tutor_actor, action="decline", reason="Fully booked that week"
    )
    assert (row.state, row.decline_reason) == ("declined", "Fully booked that week")
    assert stored(sm, booking).declined_at is not None
    assert {(r, t) for r, t, _ in outbox(sm)} == {(w.student, "booking_declined")}


def test_authz_complete_requires_ends_at(
    sm: sessionmaker[Session], service: BookingService, w: World
) -> None:
    running = add_booking(sm, w, state="accepted", starts_in=timedelta(minutes=-30))
    for action in ("complete", "no_show"):
        with pytest.raises(BookingRefused) as excinfo:
            service.transition(booking_id=running, actor=w.tutor_actor, action=action)  # type: ignore[arg-type]
        assert refused(excinfo) == ("not_ended", 409)
    ended = add_booking(
        sm, w, state="accepted", starts_in=timedelta(hours=-2), tutor=another_tutor(sm, w.subject)
    )
    row = service.transition(
        booking_id=ended, actor=Actor(row_tutor(sm, ended), "tutor"), action="complete"
    )
    assert (row.state, row.completed_by_party) == ("completed", "tutor")
    assert row.notice is not None
    assert row.notice.event == "completed"
    assert outbox(sm) == []  # completed and no-show send no email (§b.4)


def row_tutor(sm: sessionmaker[Session], booking_id: uuid.UUID) -> uuid.UUID:
    with sm() as session:
        return session.execute(
            sa.text(
                "SELECT tp.user_id FROM tutor_bookings b "
                "JOIN tutor_profiles tp ON tp.id = b.tutor_profile_id WHERE b.id = :b"
            ),
            {"b": booking_id},
        ).scalar_one()


def test_tutor_no_show_after_end(
    sm: sessionmaker[Session], service: BookingService, w: World
) -> None:
    booking = add_booking(sm, w, state="accepted", starts_in=timedelta(hours=-2))
    row = service.transition(booking_id=booking, actor=w.tutor_actor, action="no_show")
    assert row.state == "no_show"
    assert stored(sm, booking).no_show_marked_at is not None


def test_authz_student_may_complete_after_48h_awaiting_outcome(
    sm: sessionmaker[Session], service: BookingService, w: World
) -> None:
    early = add_booking(sm, w, state="accepted", starts_in=-timedelta(hours=48))  # ended 47 h ago
    with pytest.raises(BookingRefused) as excinfo:
        service.transition(booking_id=early, actor=w.student_actor, action="complete")
    assert refused(excinfo) == ("outcome_claim_not_open", 409)
    late = add_booking(
        sm, w, state="accepted", starts_in=-timedelta(hours=50), tutor=another_tutor(sm, w.subject)
    )
    row = service.transition(booking_id=late, actor=w.student_actor, action="complete")
    assert (row.state, row.completed_by_party) == ("completed", "student")


def test_parent_claim_complete_requires_requester(
    sm: sessionmaker[Session], service: BookingService, w: World
) -> None:
    requester = add_parent(sm, w.student)
    other = add_parent(sm, w.student)
    booking = add_booking(
        sm,
        w,
        state="accepted",
        starts_in=-timedelta(hours=60),
        requested_by=requester,
        party="parent",
    )
    with pytest.raises(BookingRefused) as excinfo:
        service.transition(
            booking_id=booking,
            actor=Actor(user_id=other, party="parent", child_id=w.student),
            action="claim_complete",
        )
    assert refused(excinfo) == ("not_requester", 403)
    row = service.transition(
        booking_id=booking,
        actor=Actor(user_id=requester, party="parent", child_id=w.student),
        action="claim_complete",
    )
    assert (row.state, row.completed_by_party) == ("completed", "parent")


def test_idempotent_repeat_returns_the_row_without_a_notice(
    sm: sessionmaker[Session], service: BookingService, w: World
) -> None:
    booking = add_booking(sm, w, state="requested", starts_in=timedelta(days=2))
    first = service.transition(
        booking_id=booking,
        actor=w.tutor_actor,
        action="accept",
        accept=AcceptDetails(meeting_link=LINK),
    )
    written = outbox(sm)
    again = service.transition(
        booking_id=booking,
        actor=w.tutor_actor,
        action="accept",
        accept=AcceptDetails(meeting_link=LINK),
    )
    assert first.notice is not None
    assert again.notice is None
    assert again.state == "accepted"
    assert outbox(sm) == written


def test_transitions_are_scoped_to_the_actor(
    sm: sessionmaker[Session], service: BookingService, w: World
) -> None:
    booking = add_booking(sm, w, state="requested", starts_in=timedelta(days=2))
    stranger_tutor = another_tutor(sm, w.subject)
    stranger_student = add_student(sm)
    other_child = add_student(sm)
    parent = add_parent(sm, w.student, other_child)
    actors = [
        Actor(user_id=stranger_tutor.user_id, party="tutor"),
        Actor(user_id=stranger_student, party="student"),
        Actor(user_id=parent, party="parent", child_id=other_child),
    ]
    for actor in actors:
        action = "decline" if actor.party == "tutor" else "cancel"
        with pytest.raises(BookingRefused) as excinfo:
            service.transition(booking_id=booking, actor=actor, action=action)  # type: ignore[arg-type]
        assert refused(excinfo) == ("not_found", 404), actor
    with pytest.raises(BookingRefused) as excinfo:
        service.transition(booking_id=uuid.uuid4(), actor=w.student_actor, action="cancel")
    assert refused(excinfo) == ("not_found", 404)
    with pytest.raises(BookingRefused) as excinfo:
        service.transition(booking_id=booking, actor=w.student_actor, action="accept")
    assert refused(excinfo) == ("illegal_transition", 409)


def test_transition_survives_a_raising_notification_service(
    sm: sessionmaker[Session], service: BookingService, w: World
) -> None:
    """D5.9 §1: the change and its outbox row are committed before any inbox write is tried."""
    add_parent(sm, w.student)
    booking = add_booking(sm, w, state="requested", starts_in=timedelta(days=2))
    row = service.transition(
        booking_id=booking,
        actor=w.tutor_actor,
        action="accept",
        accept=AcceptDetails(meeting_link=LINK),
    )

    class _BrokenService:
        def create(self, *args: object, **kwargs: object) -> object:
            raise RuntimeError("inbox is down")

    notices = booking_notices_for(row)
    assert len(notices) == 2  # the student and the parent
    with structlog.testing.capture_logs() as logs:
        send_after_commit(
            notices,
            service=_BrokenService(),  # type: ignore[arg-type]
            transport=RecordingPushTransport(),
        )
    assert stored(sm, booking).state is BookingState.accepted
    assert len(outbox(sm)) == 2
    assert len([log for log in logs if log["event"] == "notification_create_failed"]) == 2


# ---------------------------------------------------------------------------
# Notes (S4, S5, T16, T17, PA3)
# ---------------------------------------------------------------------------

NOTE_CASES = [
    # (state, starts_in, extra, can_post)
    ("requested", timedelta(days=2), {}, True),
    ("accepted", timedelta(days=2), {}, True),
    ("accepted", -timedelta(days=2), {}, True),  # awaiting_outcome, inside the grace
    ("completed", -timedelta(days=6), {}, True),
    ("completed", -timedelta(days=8), {}, False),  # past ends_at + 7 days
    ("requested", -timedelta(minutes=30), {}, False),  # effectively expired
    ("declined", timedelta(days=2), {}, False),
    ("cancelled", timedelta(days=2), {}, False),
    ("no_show", -timedelta(days=1), {}, False),
    ("expired", -timedelta(days=1), {}, False),
    ("accepted", timedelta(days=2), {"notes_frozen_at": datetime.now(UTC)}, False),
]


@pytest.mark.parametrize(("state", "starts_in", "extra", "can_post"), NOTE_CASES)
def test_can_post_note_enforced(
    sm: sessionmaker[Session],
    service: BookingService,
    w: World,
    state: str,
    starts_in: timedelta,
    extra: dict[str, object],
    can_post: bool,
) -> None:
    booking = add_booking(sm, w, state=state, starts_in=starts_in, **extra)
    for actor in (w.student_actor, w.tutor_actor):
        page = service.list_notes(booking_id=booking, viewer=actor, after=None, limit=20)
        assert page is not None
        assert page.can_post is can_post
        if can_post:
            note = service.post_note(booking_id=booking, actor=actor, body="See you then.")
            assert note.author_party == actor.party
        else:
            with pytest.raises(BookingRefused) as excinfo:
                service.post_note(booking_id=booking, actor=actor, body="See you then.")
            assert refused(excinfo) == ("notes_closed", 409)
    assert len(notes(sm, booking)) == (2 if can_post else 0)


def test_notes_closed_by_a_block_or_a_suspended_tutor(
    sm: sessionmaker[Session], service: BookingService, w: World
) -> None:
    booking = add_booking(sm, w, state="accepted", starts_in=timedelta(days=2))
    add_block(sm, w.student, w.tutor.user_id)
    with pytest.raises(BookingRefused) as excinfo:
        service.post_note(booking_id=booking, actor=w.student_actor, body="Hello")
    assert refused(excinfo) == ("notes_closed", 409)
    set_block_removed(sm, w.student, w.tutor.user_id)
    set_listing(sm, w.tutor, "suspended")
    with pytest.raises(BookingRefused) as excinfo:
        service.post_note(booking_id=booking, actor=w.student_actor, body="Hello")
    assert refused(excinfo) == ("notes_closed", 409)
    with pytest.raises(BookingRefused) as excinfo:
        service.post_note(booking_id=booking, actor=w.tutor_actor, body="Hello")
    assert refused(excinfo) == ("tutor_suspended", 409)


def test_student_note_needs_the_safety_notice(
    sm: sessionmaker[Session], service: BookingService
) -> None:
    w = make_world(sm, acknowledged=False)
    booking = add_booking(sm, w, state="accepted", starts_in=timedelta(days=2))
    with pytest.raises(BookingRefused) as excinfo:
        service.post_note(booking_id=booking, actor=w.student_actor, body="Hello")
    assert refused(excinfo) == ("safety_notice_required", 409)
    assert service.post_note(booking_id=booking, actor=w.tutor_actor, body="Hello").body == "Hello"


def test_note_body_is_trimmed_bounded_and_contact_free(
    sm: sessionmaker[Session], service: BookingService, w: World
) -> None:
    booking = add_booking(sm, w, state="accepted", starts_in=timedelta(days=2))
    for body, code in (("   ", "note_empty"), ("x" * 2001, "text_too_long")):
        with pytest.raises(BookingRefused) as excinfo:
            service.post_note(booking_id=booking, actor=w.student_actor, body=body)
        assert refused(excinfo) == (code, 422)
    with pytest.raises(BookingRefused) as excinfo:
        service.post_note(booking_id=booking, actor=w.student_actor, body="mail me: a@b.co")
    assert refused(excinfo) == ("contact_details_not_allowed", 422)
    note = service.post_note(booking_id=booking, actor=w.student_actor, body="  Bring paper 2  ")
    assert note.body == "Bring paper 2"


def test_post_note_returns_the_notice_facts(
    sm: sessionmaker[Session], service: BookingService
) -> None:
    w = make_world(sm, display_name="Omar")
    parent = add_parent(sm, w.student)
    booking = add_booking(sm, w, state="accepted", starts_in=timedelta(days=2))
    note = service.post_note(booking_id=booking, actor=w.tutor_actor, body="Chapter 4 please.")
    assert note.notice is not None
    assert (note.notice.tutor_user_id, note.notice.student_id) == (w.tutor.user_id, w.student)
    assert note.notice.linked_parent_ids == (parent,)
    assert (note.notice.tutor_name, note.notice.student_label) == ("Sara M.", "Omar")
    assert note.author_name == "Sara M."


def test_parents_read_notes_but_never_post(
    sm: sessionmaker[Session], service: BookingService
) -> None:
    w = make_world(sm, display_name="Omar")
    parent = add_parent(sm, w.student)
    booking = add_booking(sm, w, state="accepted", starts_in=timedelta(days=2))
    service.post_note(booking_id=booking, actor=w.student_actor, body="First")
    service.post_note(booking_id=booking, actor=w.tutor_actor, body="Second")
    page = service.list_notes(
        booking_id=booking,
        viewer=Actor(user_id=parent, party="parent", child_id=w.student),
        after=None,
        limit=20,
    )
    assert page is not None
    assert page.can_post is False
    assert [(n.author_party, n.author_name, n.body) for n in page.items] == [
        ("student", "Omar", "First"),
        ("tutor", "Sara M.", "Second"),
    ]


def test_list_notes_pages_oldest_first_and_hides_hidden_bodies(
    sm: sessionmaker[Session], service: BookingService, w: World
) -> None:
    booking = add_booking(sm, w, state="accepted", starts_in=timedelta(days=2))
    posted = [
        service.post_note(booking_id=booking, actor=w.student_actor, body=f"Note {index}")
        for index in range(3)
    ]
    admin = add_user(sm, Role.platform_admin)
    with sm.begin() as session:
        assert BookingService.hide_note_in_session(session, posted[1].id, admin) is True
        assert BookingService.hide_note_in_session(session, posted[1].id, admin) is False
    seen = []
    after = None
    while True:
        page = service.list_notes(booking_id=booking, viewer=w.tutor_actor, after=after, limit=2)
        assert page is not None
        seen.extend(page.items)
        if page.next_key is None:
            break
        after = page.next_key
    assert [n.id for n in seen] == [n.id for n in posted]
    assert [(n.hidden, n.body) for n in seen] == [
        (False, "Note 0"),
        (True, None),
        (False, "Note 2"),
    ]
    assert notes(sm, booking)[1].hidden_by_user_id == admin


def test_list_notes_scoped_to_the_viewer(
    sm: sessionmaker[Session], service: BookingService, w: World
) -> None:
    booking = add_booking(sm, w, state="accepted", starts_in=timedelta(days=2))
    strangers = [
        Actor(user_id=another_tutor(sm, w.subject).user_id, party="tutor"),
        Actor(user_id=add_student(sm), party="student"),
        Actor(user_id=add_parent(sm), party="parent", child_id=add_student(sm)),
    ]
    for viewer in strangers:
        assert service.list_notes(booking_id=booking, viewer=viewer, after=None, limit=20) is None
    for actor in strangers[:2]:
        with pytest.raises(BookingRefused) as excinfo:
            service.post_note(booking_id=booking, actor=actor, body="Hi")
        assert refused(excinfo) == ("not_found", 404)
    assert notes(sm, booking) == []


def test_freeze_and_unfreeze_notes_in_session(
    sm: sessionmaker[Session], service: BookingService, w: World
) -> None:
    booking = add_booking(sm, w, state="accepted", starts_in=timedelta(days=2))
    with sm.begin() as session:
        assert BookingService.freeze_notes_in_session(session, booking) is True
        assert BookingService.freeze_notes_in_session(session, booking) is False
    with pytest.raises(BookingRefused) as excinfo:
        service.post_note(booking_id=booking, actor=w.student_actor, body="Hello")
    assert refused(excinfo) == ("notes_closed", 409)
    assert service.get_for_viewer(booking, w.student_actor).notes_frozen is True  # type: ignore[union-attr]
    with sm.begin() as session:
        assert BookingService.unfreeze_notes_in_session(session, booking) is True
        assert BookingService.unfreeze_notes_in_session(session, booking) is False
    assert (
        service.post_note(booking_id=booking, actor=w.student_actor, body="Hello").body == "Hello"
    )


# ---------------------------------------------------------------------------
# Reads (S1, S2, T9, T10, PA1, PA2)
# ---------------------------------------------------------------------------


def _all_pages(fetch: object, **kwargs: object) -> list[BookingRow]:
    rows: list[BookingRow] = []
    after = None
    splits = set()
    while True:
        page = fetch(after=after, limit=2, **kwargs)  # type: ignore[operator]
        rows.extend(page.items)
        if page.next_key is None:
            break
        splits.add(page.next_key.split)
        after = page.next_key
    assert len(splits) <= 1  # the split is fixed in the cursor (F25)
    return rows


def test_list_for_student_upcoming_and_past_by_effective_state(
    sm: sessionmaker[Session], service: BookingService, w: World
) -> None:
    tutors = [another_tutor(sm, w.subject) for _ in range(7)]
    made = {
        "live_request": add_booking(sm, w, tutor=tutors[0], starts_in=timedelta(days=1)),
        "accepted": add_booking(
            sm, w, tutor=tutors[1], state="accepted", starts_in=timedelta(days=2)
        ),
        "in_progress": add_booking(
            sm, w, tutor=tutors[2], state="accepted", starts_in=timedelta(minutes=-20)
        ),
        "awaiting": add_booking(
            sm, w, tutor=tutors[3], state="accepted", starts_in=-timedelta(hours=3)
        ),
        "completed": add_booking(
            sm, w, tutor=tutors[4], state="completed", starts_in=-timedelta(days=3)
        ),
        "cancelled": add_booking(
            sm, w, tutor=tutors[5], state="cancelled", starts_in=timedelta(days=4)
        ),
        "stale": add_booking(sm, w, tutor=tutors[6], starts_in=-timedelta(hours=5)),
    }
    upcoming = _all_pages(service.list_for_student, student_id=w.student, when="upcoming")
    assert [row.id for row in upcoming] == [
        made["in_progress"],
        made["live_request"],
        made["accepted"],
    ]
    past = _all_pages(service.list_for_student, student_id=w.student, when="past")
    assert [row.id for row in past] == [
        made["cancelled"],
        made["awaiting"],
        made["stale"],
        made["completed"],
    ]
    other = add_student(sm)
    add_booking(sm, w, student=other, tutor=tutors[0], starts_in=timedelta(days=6))
    assert len(_all_pages(service.list_for_student, student_id=w.student, when="upcoming")) == 3


def test_list_for_tutor_state_filter_uses_effective_predicates(
    sm: sessionmaker[Session], service: BookingService, w: World
) -> None:
    students = [add_student(sm) for _ in range(5)]
    live = add_booking(sm, w, student=students[0], starts_in=timedelta(days=1))
    stale = add_booking(sm, w, student=students[1], starts_in=-timedelta(hours=4))
    expired = add_booking(sm, w, student=students[2], state="expired", starts_in=-timedelta(days=2))
    awaiting = add_booking(
        sm, w, student=students[3], state="accepted", starts_in=-timedelta(hours=6)
    )
    accepted = add_booking(
        sm, w, student=students[4], state="accepted", starts_in=timedelta(days=3)
    )
    other_tutor = another_tutor(sm, w.subject)
    add_booking(sm, w, student=students[0], tutor=other_tutor, starts_in=timedelta(days=2))

    def ids(when: str, state: str) -> set[uuid.UUID]:
        page = service.list_for_tutor(
            w.tutor.profile_id,
            when=when,
            state=state,
            after=None,
            limit=50,  # type: ignore[arg-type]
        )
        return {row.id for row in page.items}

    assert ids("upcoming", "requested") == {live}
    assert ids("past", "expired") == {stale, expired}
    assert ids("upcoming", "expired") == set()
    assert ids("past", "awaiting_outcome") == {awaiting}
    assert ids("upcoming", "accepted") == {accepted}


def test_list_for_child_returns_only_that_childs_bookings(
    sm: sessionmaker[Session], service: BookingService, w: World
) -> None:
    sibling = add_student(sm)
    mine = add_booking(sm, w, starts_in=timedelta(days=1))
    add_booking(sm, w, student=sibling, starts_in=timedelta(days=2))
    page = service.list_for_child(w.student, when="upcoming", after=None, limit=20)
    assert [row.id for row in page.items] == [mine]


def test_booking_lists_take_two_statements(
    sm: sessionmaker[Session], service: BookingService, w: World
) -> None:
    second = another_tutor(sm, w.subject)
    other = add_student(sm)
    for index in range(4):
        add_booking(
            sm,
            w,
            tutor=w.tutor if index % 2 else second,
            student=w.student if index < 3 else other,
            state="accepted",
            starts_in=timedelta(days=1 + index),
        )
    calls = [
        lambda: service.list_for_student(w.student, when="upcoming", after=None, limit=20),
        lambda: service.list_for_child(w.student, when="upcoming", after=None, limit=20),
        lambda: service.list_for_tutor(w.tutor.profile_id, when="upcoming", after=None, limit=20),
    ]
    for call in calls:
        with count_statements(sm) as seen:
            page = call()
        assert page.items  # non-vacuity: the page has rows
        assert len(seen) == 2, seen


def test_get_for_viewer_is_scoped_and_carries_review_and_block(
    sm: sessionmaker[Session], service: BookingService, w: World
) -> None:
    booking = add_booking(sm, w, state="completed", starts_in=-timedelta(days=9))
    with sm.begin() as session:
        session.add(
            TutorReview(
                booking_id=booking,
                tutor_profile_id=w.tutor.profile_id,
                student_id=w.student,
                stars=4,
                body=None,
                text_state=ModerationState.none,
            )
        )
    add_block(sm, w.tutor.user_id, w.student)
    parent = add_parent(sm, w.student)
    for viewer in (
        w.student_actor,
        w.tutor_actor,
        Actor(user_id=parent, party="parent", child_id=w.student),
    ):
        row = service.get_for_viewer(booking, viewer)
        assert row is not None
        assert row.blocked is True
        assert row.has_review is True
        assert row.review is not None
        assert row.review.stars == 4
    strangers = [
        Actor(user_id=another_tutor(sm, w.subject).user_id, party="tutor"),
        Actor(user_id=add_student(sm), party="student"),
        Actor(user_id=parent, party="parent", child_id=add_student(sm)),
    ]
    for viewer in strangers:
        assert service.get_for_viewer(booking, viewer) is None


def _block_row_at(
    sm: sessionmaker[Session], blocker: uuid.UUID, blocked: uuid.UUID, *, at: datetime
) -> None:
    with sm.begin() as session:
        session.add(
            TutoringBlock(
                blocker_user_id=blocker, blocked_user_id=blocked, created_at=at, updated_at=at
            )
        )


def test_rows_carry_when_the_active_block_began_and_the_outcome_instants(
    sm: sessionmaker[Session], service: BookingService, w: World
) -> None:
    """SPEC §i.8 (F5-A2): every read row carries ``blocked_since``, the earliest ``updated_at``
    of an active block between the pair in either direction (``None`` without one, and then
    ``blocked`` is false), and the stored ``completed_at`` and ``no_show_marked_at``."""
    completed = add_booking(sm, w, state="completed", starts_in=-timedelta(days=9))
    no_show = add_booking(sm, w, state="no_show", starts_in=-timedelta(days=3))

    def read(booking: uuid.UUID) -> BookingRow:
        row = service.get_for_viewer(booking, w.tutor_actor)
        assert row is not None
        return row

    def listed() -> dict[uuid.UUID, BookingRow]:
        page = service.list_for_tutor(w.tutor.profile_id, when="past", after=None, limit=20)
        return {row.id: row for row in page.items}

    for booking, column in ((completed, "completed_at"), (no_show, "no_show_marked_at")):
        row = read(booking)
        assert (row.blocked_since, row.blocked) == (None, False)
        assert getattr(row, column) == getattr(stored(sm, booking), column)
        assert getattr(row, column) is not None
    assert read(completed).no_show_marked_at is None
    assert read(no_show).completed_at is None

    first = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)
    _block_row_at(sm, w.tutor.user_id, w.student, at=first)
    _block_row_at(sm, w.student, w.tutor.user_id, at=first + timedelta(days=2))
    other_pair = make_world(sm)
    _block_row_at(sm, other_pair.student, w.tutor.user_id, at=first - timedelta(days=5))
    for row in (read(completed), read(no_show), *listed().values()):
        assert (row.blocked_since, row.blocked) == (first, True)  # the earlier of the two
    set_block_removed(sm, w.tutor.user_id, w.student)  # the tutor lifts theirs
    assert read(completed).blocked_since == first + timedelta(days=2)
    set_block_removed(sm, w.student, w.tutor.user_id)
    assert (read(completed).blocked_since, read(completed).blocked) == (None, False)
    # A renewal through the ORM clears removed_at and stamps updated_at: the block starts again.
    with sm.begin() as session:
        block = session.get(TutoringBlock, (w.student, w.tutor.user_id))
        assert block is not None
        block.removed_at = None
    with sm() as session:
        renewed = session.execute(
            sa.select(TutoringBlock.updated_at, TutoringBlock.created_at).where(
                TutoringBlock.blocker_user_id == w.student,
                TutoringBlock.blocked_user_id == w.tutor.user_id,
            )
        ).one()
    assert renewed.created_at == first + timedelta(days=2)
    assert renewed.updated_at > renewed.created_at
    assert read(completed).blocked_since == renewed.updated_at


# ---------------------------------------------------------------------------
# Slots (SP5)
# ---------------------------------------------------------------------------


def test_slots_offer_the_rule_grid_minus_active_bookings(
    sm: sessionmaker[Session], service: BookingService, w: World
) -> None:
    now = datetime.now(UTC)
    offered = {
        start
        for start, _ in bookable_slots(
            RULES,
            zone=ZONE,
            start=now.astimezone(ZoneInfo(ZONE)).date(),
            days=6,
            duration=HOUR,
            busy=(),
            now=now,
        )
    }
    # A start whose neighbours an hour either side are offered too (never next to a DST hour).
    held_at = min(
        s for s in offered if s >= now + timedelta(days=2) and {s - HOUR, s + HOUR} <= offered
    )
    freed_at = min(s for s in offered if s >= held_at + 3 * HOUR)
    add_booking(sm, w, state="accepted", starts_at=held_at)
    add_booking(sm, w, state="cancelled", starts_at=freed_at, student=add_student(sm))
    today = datetime.now(UTC).astimezone(ZoneInfo(ZONE)).date()
    view = service.slots(w.tutor.profile_id, start=today, days=5, duration_minutes=60)
    starts = {start for start, _ in view.slots}
    assert len(view.slots) > 100  # non-vacuity: four days of half-hour steps
    assert (view.zone, view.duration_minutes) == (ZONE, 60)
    assert view.window_start <= view.slots[0][0]
    assert view.slots[-1][0] < view.window_end
    assert all(end - start == HOUR for start, end in view.slots)
    # The accepted booking holds its hour: neither it nor the half-hours either side are offered.
    for blocked in (held_at - timedelta(minutes=30), held_at, held_at + timedelta(minutes=30)):
        assert blocked not in starts
    assert held_at - HOUR in starts
    assert held_at + HOUR in starts
    assert freed_at in starts  # a cancelled booking frees its slot
    assert all(start >= now + timedelta(hours=1, minutes=59) for start in starts)


def test_slots_hidden_tutor_is_404(sm: sessionmaker[Session], service: BookingService) -> None:
    today = datetime.now(UTC).astimezone(ZoneInfo(ZONE)).date()
    paused = make_world(sm, paused=True)
    with pytest.raises(BookingRefused) as excinfo:
        service.slots(paused.tutor.profile_id, start=today, days=3, duration_minutes=60)
    assert refused(excinfo) == ("not_found", 404)
    w = make_world(sm)
    add_block(sm, w.tutor.user_id, w.student)
    with pytest.raises(BookingRefused) as excinfo:
        service.slots(
            w.tutor.profile_id, start=today, days=3, duration_minutes=60, student_id=w.student
        )
    assert refused(excinfo) == ("not_found", 404)
    assert service.slots(w.tutor.profile_id, start=today, days=3, duration_minutes=60).slots


def test_slots_window_and_duration_validation(service: BookingService, w: World) -> None:
    today = datetime.now(UTC).astimezone(ZoneInfo(ZONE)).date()
    for start, days in (
        (today - timedelta(days=1), 3),
        (today, 0),
        (today, 29),
        (today + timedelta(days=20), 9),
    ):
        with pytest.raises(BookingRefused) as excinfo:
            service.slots(w.tutor.profile_id, start=start, days=days, duration_minutes=60)
        assert refused(excinfo) == ("invalid_window", 422), (start, days)
    with pytest.raises(BookingRefused) as excinfo:
        service.slots(w.tutor.profile_id, start=today, days=3, duration_minutes=50)
    assert refused(excinfo) == ("invalid_duration", 422)
    assert service.slots(
        w.tutor.profile_id, start=today + timedelta(days=20), days=8, duration_minutes=120
    ).slots


# ---------------------------------------------------------------------------
# Session-level helpers for sweeps and reports (T21, T25)
# ---------------------------------------------------------------------------


def test_cancel_future_for_pair_in_session_overrides_the_24h_window(
    sm: sessionmaker[Session], service: BookingService, w: World
) -> None:
    parent = add_parent(sm, w.student)
    requested = add_booking(sm, w, starts_in=timedelta(days=3))
    inside_24h = add_booking(sm, w, state="accepted", starts_in=timedelta(hours=5))
    ended = add_booking(sm, w, state="accepted", starts_in=-timedelta(hours=3))
    other_pair = add_booking(sm, w, student=add_student(sm), starts_in=timedelta(days=4))
    with sm.begin() as session:
        cancelled = service.cancel_future_for_pair_in_session(
            session,
            tutor_profile_id=w.tutor.profile_id,
            student_id=w.student,
            actor_user_id=w.student,
        )
    assert cancelled == [inside_24h, requested]
    for booking in cancelled:
        db = stored(sm, booking)
        assert (db.state, db.cancelled_by_party, db.cancel_reason, db.cancelled_by_user_id) == (
            BookingState.cancelled,
            BookingParty.system,
            SYSTEM_CANCEL_REASON,
            None,
        )
    assert stored(sm, ended).state is BookingState.accepted
    assert stored(sm, other_pair).state is BookingState.requested
    assert {(r, t) for r, t, _ in outbox(sm)} == {
        (w.tutor.user_id, "booking_cancelled"),
        (parent, "booking_cancelled"),
    }  # the student blocked: the actor is not told


def test_cancel_future_for_tutor_in_session_cancels_every_future_active_booking(
    sm: sessionmaker[Session], service: BookingService, w: World
) -> None:
    other = add_student(sm)
    first = add_booking(sm, w, starts_in=timedelta(days=3))
    second = add_booking(sm, w, student=other, state="accepted", starts_in=timedelta(hours=2))
    done = add_booking(sm, w, state="completed", starts_in=-timedelta(days=2))
    with sm.begin() as session:
        cancelled = service.cancel_future_for_tutor_in_session(
            session, tutor_profile_id=w.tutor.profile_id
        )
    assert cancelled == [second, first]
    assert {stored(sm, b).cancelled_by_party for b in cancelled} == {BookingParty.platform_admin}
    assert {stored(sm, b).cancel_reason for b in cancelled} == {ADMIN_CANCEL_REASON}
    assert stored(sm, done).state is BookingState.completed
    assert {(r, t) for r, t, _ in outbox(sm)} == {
        (w.student, "booking_cancelled"),
        (other, "booking_cancelled"),
    }


def test_admin_cancel_in_session_only_before_the_start(
    sm: sessionmaker[Session], service: BookingService, w: World
) -> None:
    admin = add_user(sm, Role.platform_admin)
    booking = add_booking(sm, w, state="accepted", starts_in=timedelta(hours=3))
    with sm.begin() as session:
        row = service.admin_cancel_in_session(session, booking_id=booking, admin_user_id=admin)
    assert (row.state, row.cancelled_by_party, row.cancel_reason) == (
        "cancelled",
        "platform_admin",
        ADMIN_CANCEL_REASON,
    )
    assert row.notice is not None
    assert row.notice.actor_user_id == admin
    assert stored(sm, booking).cancelled_by_user_id == admin
    with sm.begin() as session:
        again = service.admin_cancel_in_session(session, booking_id=booking, admin_user_id=admin)
    assert again.notice is None
    started = add_booking(
        sm, w, state="accepted", starts_in=-timedelta(minutes=10), student=add_student(sm)
    )
    with pytest.raises(BookingRefused) as excinfo, sm.begin() as session:
        service.admin_cancel_in_session(session, booking_id=started, admin_user_id=admin)
    assert refused(excinfo) == ("already_started", 409)
    with pytest.raises(BookingRefused) as excinfo, sm.begin() as session:
        service.admin_cancel_in_session(session, booking_id=uuid.uuid4(), admin_user_id=admin)
    assert refused(excinfo) == ("not_found", 404)


def test_admin_complete_in_session_awaiting_outcome_or_no_show(
    sm: sessionmaker[Session], service: BookingService, w: World
) -> None:
    admin = add_user(sm, Role.platform_admin)
    awaiting = add_booking(sm, w, state="accepted", starts_in=-timedelta(hours=3))
    no_show = add_booking(sm, w, state="no_show", starts_in=-timedelta(days=2))
    running = add_booking(sm, w, state="accepted", starts_in=timedelta(days=2))
    for booking in (awaiting, no_show):
        with sm.begin() as session:
            row = service.admin_complete_in_session(
                session, booking_id=booking, admin_user_id=admin
            )
        assert (row.state, row.completed_by_party) == ("completed", "platform_admin")
    with pytest.raises(BookingRefused) as excinfo, sm.begin() as session:
        service.admin_complete_in_session(session, booking_id=running, admin_user_id=admin)
    assert refused(excinfo) == ("not_ended", 409)
