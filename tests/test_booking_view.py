"""Viewer-dependent booking and note DTOs (SPEC §b.3 "Viewer-dependent serialisation", PLAN T13).

Pure: every case builds a ``BookingRow`` by hand and serialises it for one viewer. The rules:

* ``meetingLink``/``locationDetail`` only once the booking was accepted, to its student, its tutor
  and linked parents (O16);
* ``review``/``reviewOpensAt`` to the student only (SC-12); ``studentShared`` to the tutor only;
* a system or platform cancellation reason reads "Cancelled" to the tutor, and a block's
  ``system`` cancellation reads as a platform one to the student and parents (SC-11, §i.7);
* a block that alone closes the notes reads as a safety freeze to the tutor (SC-11);
* a tutor never sees the party ``parent`` (SC-9, SPEC §i.4);
* ``post_note`` is added by the builder, for a student or tutor viewer, from ``can_post_note``;
  ``core.booking.allowed_actions`` never returns it (SPEC §i.4);
* a suspended or closed tutor's write actions are stripped (CB-7, SPEC §i.4).
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from lemely.core.booking import BookingFacts, allowed_actions
from lemely.db.booking_repo import (
    Actor,
    BookingNotice,
    BookingRow,
    NoteNotice,
    NoteRow,
    NotesPage,
    ReviewRef,
    SlotsView,
)
from lemely.db.models.enums import NotificationType
from lemely.db.tutor_directory_repo import SubjectRef, TutorCard
from lemely.web.booking_view import (
    booking_notices_for,
    build_booking_dto,
    build_bookings_page_dto,
    build_note_dto,
    build_notes_page_dto,
    build_slots_dto,
    note_notices_for,
)

NOW = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)
TUTOR_PROFILE = uuid.UUID("10000000-0000-4000-8000-000000000001")
TUTOR_USER = uuid.UUID("10000000-0000-4000-8000-000000000002")
STUDENT = uuid.UUID("10000000-0000-4000-8000-000000000003")
PARENT = uuid.UUID("10000000-0000-4000-8000-000000000004")
OTHER_PARENT = uuid.UUID("10000000-0000-4000-8000-000000000005")
BOOKING = uuid.UUID("10000000-0000-4000-8000-000000000006")
LINK = "https://zoom.us/j/123456789"
PLACE = "Community centre, room 2"

AS_STUDENT = Actor(user_id=STUDENT, party="student")
AS_TUTOR = Actor(user_id=TUTOR_USER, party="tutor")
AS_PARENT = Actor(user_id=PARENT, party="parent", child_id=STUDENT)
AS_OTHER_PARENT = Actor(user_id=OTHER_PARENT, party="parent", child_id=STUDENT)
VIEWERS = (AS_STUDENT, AS_TUTOR, AS_PARENT)

CARD = TutorCard(
    tutor_id=TUTOR_PROFILE,
    public_first_name="Sara",
    public_last_initial="M",
    headline="IGCSE Mathematics",
    subjects=(SubjectRef(code="0580", name="Mathematics"),),
    modes=("virtual", "in_person"),
    area_code="cairo",
    rating_sum=0,
    rating_count=0,
)

STATE_FIELDS: dict[str, dict[str, object]] = {
    "requested": {},
    "accepted": {"accepted_at": NOW - timedelta(days=3)},
    "completed": {"accepted_at": NOW - timedelta(days=3), "completed_by_party": "tutor"},
    "no_show": {"accepted_at": NOW - timedelta(days=3)},
    "declined": {"decline_reason": "Fully booked"},
    "cancelled": {
        "cancelled_by_party": "student",
        "cancelled_at": NOW - timedelta(days=1),
        "cancel_reason": "Exam clash",
    },
    "expired": {},
}


def make_row(
    *,
    state: str = "accepted",
    starts_at: datetime = NOW + timedelta(days=2),
    duration: timedelta = timedelta(hours=1),
    mode: str = "virtual",
    **overrides: object,
) -> BookingRow:
    fields: dict[str, object] = {
        "id": BOOKING,
        "tutor": CARD,
        "tutor_user_id": TUTOR_USER,
        "tutor_listing_state": "listed",
        "tutor_zone": "Africa/Cairo",
        "student_id": STUDENT,
        "student_display_name": "Omar",
        "student_created_at": NOW - timedelta(days=90),
        "requested_by_user_id": STUDENT,
        "requested_by_party": "student",
        "subject_code": "0580",
        "subject_name": "Mathematics",
        "mode": mode,
        "starts_at": starts_at,
        "ends_at": starts_at + duration,
        "state": state,
        "meeting_link": LINK if mode == "virtual" else None,
        "location_detail": PLACE if mode == "in_person" else None,
        "other_mode_note": None,
        "decline_reason": None,
        "cancel_reason": None,
        "cancelled_by_party": None,
        "cancelled_at": None,
        "completed_by_party": None,
        "notes_frozen": False,
        "accepted_at": None,
        "created_at": NOW - timedelta(days=5),
        "review": None,
        "has_review": False,
        "blocked": False,
    }
    fields.update(STATE_FIELDS[state])
    fields.update(overrides)
    return BookingRow(**fields)  # type: ignore[arg-type]


def dto_for(row: BookingRow, viewer: Actor, *, shared: bool | None = None) -> dict[str, object]:
    student_shared = (False if shared is None else shared) if viewer.party == "tutor" else None
    return build_booking_dto(
        row, viewer=viewer, now=NOW, student_shared=student_shared
    ).model_dump()


@pytest.mark.parametrize("mode", ["virtual", "in_person"])
def test_meeting_link_only_after_accept_to_participants_and_parents(mode: str) -> None:
    checked = 0
    for state in STATE_FIELDS:
        # Even a row that somehow holds a link before accept never shows it (defence in depth).
        row = make_row(state=state, mode=mode, meeting_link=LINK, location_detail=PLACE)
        visible = state in {"accepted", "completed", "no_show"}
        for viewer in VIEWERS:
            dto = dto_for(row, viewer)
            assert dto["meetingLink"] == (LINK if visible else None), (state, viewer.party)
            assert dto["locationDetail"] == (PLACE if visible else None), (state, viewer.party)
            checked += 1
    assert checked == 7 * 3  # non-vacuity: every stored state for every viewer


def test_meeting_link_never_reaches_a_viewer_outside_the_booking() -> None:
    row = make_row(state="accepted")
    stranger = Actor(user_id=uuid.uuid4(), party="platform_admin")  # type: ignore[arg-type]
    dto = build_booking_dto(row, viewer=stranger, now=NOW, student_shared=None)
    assert (dto.meetingLink, dto.locationDetail) == (None, None)
    assert dto.allowedActions == []


PLATFORM_REASON = "This session was cancelled by Lemely."


@pytest.mark.parametrize(
    ("party", "stored", "tutor_sees", "tutor_party", "family_sees", "family_party"),
    [
        (
            "system",
            "This session was cancelled.",
            "Cancelled",
            "platform_admin",
            PLATFORM_REASON,
            "platform_admin",
        ),
        (
            "platform_admin",
            PLATFORM_REASON,
            "Cancelled",
            "platform_admin",
            PLATFORM_REASON,
            "platform_admin",
        ),
        ("student", "Exam clash", "Exam clash", "student", "Exam clash", "student"),
        ("tutor", "I am unwell", "I am unwell", "tutor", "I am unwell", "tutor"),
    ],
)
def test_system_cancel_reads_as_a_platform_cancellation_to_every_viewer(
    party: str,
    stored: str,
    tutor_sees: str,
    tutor_party: str,
    family_sees: str,
    family_party: str,
) -> None:
    """SC-11, SPEC §i.7: only a block's sweep cancels as ``system``, so whoever reads ``system``
    learns that one side blocked the other. The tutor reads "Cancelled" by ``platform_admin``;
    the student and their parents read a platform cancellation, party and reason exactly as a
    suspension's (``This session was cancelled by Lemely.``). Every other party is unchanged."""
    row = make_row(state="cancelled", cancelled_by_party=party, cancel_reason=stored)
    tutor = dto_for(row, AS_TUTOR)
    assert (tutor["cancelReason"], tutor["cancelledBy"]) == (tutor_sees, tutor_party)
    for viewer in (AS_STUDENT, AS_PARENT):
        family = dto_for(row, viewer)
        assert (family["cancelReason"], family["cancelledBy"]) == (family_sees, family_party)


def test_no_viewer_can_tell_a_block_from_a_platform_cancellation() -> None:
    """Everything any viewer's DTO says about a block's cancellation equals a suspension's."""
    swept = make_row(
        state="cancelled", cancelled_by_party="system", cancel_reason="This session was cancelled."
    )
    by_platform = replace(swept, cancelled_by_party="platform_admin", cancel_reason=PLATFORM_REASON)
    by_student = replace(swept, cancelled_by_party="student", cancel_reason="Exam clash")
    for viewer in VIEWERS:
        assert dto_for(swept, viewer) == dto_for(by_platform, viewer), viewer.party
        assert dto_for(swept, viewer) != dto_for(by_student, viewer), viewer.party  # non-vacuity


def test_review_fields_student_viewer_only() -> None:
    review = ReviewRef(
        review_id=uuid.uuid4(), stars=5, text_state="pending", created_at=NOW - timedelta(days=1)
    )
    row = make_row(
        state="completed",
        starts_at=NOW - timedelta(days=9),
        review=review,
        has_review=True,
    )
    student = dto_for(row, AS_STUDENT)
    assert student["review"] == {
        "reviewId": str(review.review_id),
        "stars": 5,
        "textState": "pending",
        "editableUntil": (review.created_at + timedelta(days=14)).isoformat(),
    }
    assert student["reviewOpensAt"] == (row.ends_at + timedelta(days=7)).isoformat()
    for viewer in (AS_TUTOR, AS_PARENT):
        dto = dto_for(row, viewer)
        assert (dto["review"], dto["reviewOpensAt"]) == (None, None)
    not_completed = dto_for(make_row(state="accepted", review=None), AS_STUDENT)
    assert (not_completed["review"], not_completed["reviewOpensAt"]) == (None, None)


def test_review_action_offered_to_the_student_once_reviews_open() -> None:
    ended_long_ago = make_row(state="completed", starts_at=NOW - timedelta(days=9))
    assert "review" in dto_for(ended_long_ago, AS_STUDENT)["allowedActions"]
    assert "review" not in dto_for(ended_long_ago, AS_PARENT)["allowedActions"]
    recent = make_row(state="completed", starts_at=NOW - timedelta(days=2))
    assert "review" not in dto_for(recent, AS_STUDENT)["allowedActions"]
    young = replace(ended_long_ago, student_created_at=NOW - timedelta(days=3))
    assert "review" not in dto_for(young, AS_STUDENT)["allowedActions"]
    reviewed = replace(ended_long_ago, has_review=True)
    assert "review" not in dto_for(reviewed, AS_STUDENT)["allowedActions"]


@pytest.mark.parametrize(
    ("party", "before_start", "late"),
    [
        ("tutor", timedelta(hours=10), True),
        ("tutor", timedelta(hours=24), False),  # exactly 24 h before is not late
        ("tutor", timedelta(hours=30), False),
        ("student", timedelta(hours=30), False),
        ("system", timedelta(hours=2), False),
    ],
)
def test_cancelled_late_flag(party: str, before_start: timedelta, late: bool) -> None:
    starts_at = NOW + timedelta(days=1)
    row = make_row(
        state="cancelled",
        starts_at=starts_at,
        cancelled_by_party=party,
        cancelled_at=starts_at - before_start,
        cancel_reason="Reason",
    )
    for viewer in VIEWERS:
        assert dto_for(row, viewer)["cancelledLate"] is late
    assert dto_for(make_row(state="accepted"), AS_STUDENT)["cancelledLate"] is False


def test_tutor_viewer_never_learns_a_parent_party() -> None:
    by_parent = make_row(
        state="cancelled",
        requested_by_party="parent",
        requested_by_user_id=PARENT,
        cancelled_by_party="parent",
        cancelled_at=NOW - timedelta(days=3),
    )
    completed = make_row(
        state="completed",
        starts_at=NOW - timedelta(days=4),
        requested_by_party="parent",
        requested_by_user_id=PARENT,
        completed_by_party="parent",
    )
    tutor = dto_for(by_parent, AS_TUTOR)
    assert (tutor["requestedBy"], tutor["cancelledBy"]) == ("student", "student")
    assert dto_for(completed, AS_TUTOR)["completedBy"] == "student"
    for viewer in (AS_STUDENT, AS_PARENT):
        assert (
            dto_for(by_parent, viewer)["requestedBy"],
            dto_for(by_parent, viewer)["cancelledBy"],
        ) == (
            "parent",
            "parent",
        )
        assert dto_for(completed, viewer)["completedBy"] == "parent"


def test_post_note_is_added_by_the_builder_for_student_and_tutor_only() -> None:
    row = make_row(state="accepted")
    facts = BookingFacts(
        state="accepted",
        starts_at=row.starts_at,
        ends_at=row.ends_at,
        viewer="student",
        viewer_is_requester=False,
        tutor_outcome_recorded=False,
    )
    core = allowed_actions(facts, now=NOW, has_review=False, blocked=False, review_account_ok=True)
    assert "post_note" not in core  # SPEC §i.4: the core never returns it
    assert "post_note" in dto_for(row, AS_STUDENT)["allowedActions"]
    assert "post_note" in dto_for(row, AS_TUTOR)["allowedActions"]
    assert "post_note" not in dto_for(row, AS_PARENT)["allowedActions"]
    for closed in (
        replace(row, notes_frozen=True),
        replace(row, blocked=True),
        make_row(state="declined"),
        make_row(state="completed", starts_at=NOW - timedelta(days=8)),
    ):
        for viewer in VIEWERS:
            assert "post_note" not in dto_for(closed, viewer)["allowedActions"]


def test_tutor_reads_a_block_that_alone_closes_notes_as_a_freeze() -> None:
    """SC-11: a tutor must not learn that the student blocked them from closed notes.

    A block closes notes the window would keep open; a tutor reading closed notes with
    ``notesFrozen: false`` on a listed profile could only be looking at a block. The tutor reads
    that closure as a safety freeze. Where notes are closed anyway, a block changes nothing.
    """
    open_notes = (
        make_row(state="completed", starts_at=NOW - timedelta(days=2)),  # inside the 7 days
        make_row(state="accepted", starts_at=NOW - timedelta(hours=3)),  # awaiting outcome
    )
    for row in open_notes:
        assert "post_note" in dto_for(row, AS_TUTOR)["allowedActions"]  # red case: open
        blocked = dto_for(replace(row, blocked=True), AS_TUTOR)
        frozen = dto_for(replace(row, notes_frozen=True), AS_TUTOR)
        assert blocked == frozen, row.state
        frozen_actions = frozen["allowedActions"]
        assert isinstance(frozen_actions, list)
        assert (frozen["notesFrozen"], "post_note" in frozen_actions) == (True, False)
        for viewer in (AS_STUDENT, AS_PARENT):  # the family keeps the stored flag
            assert dto_for(replace(row, blocked=True), viewer)["notesFrozen"] is False
    closed_anyway = (
        make_row(state="completed", starts_at=NOW - timedelta(days=9)),  # window over
        make_row(state="declined"),
        make_row(state="cancelled"),
        make_row(
            state="completed", starts_at=NOW - timedelta(days=2), tutor_listing_state="closed"
        ),
    )
    for row in closed_anyway:
        assert dto_for(replace(row, blocked=True), AS_TUTOR) == dto_for(row, AS_TUTOR), row.state
        assert dto_for(replace(row, blocked=True), AS_TUTOR)["notesFrozen"] is False


@pytest.mark.parametrize("listing", ["suspended", "closed"])
def test_tutor_write_actions_stripped_when_suspended_or_closed(listing: str) -> None:
    pending = make_row(state="requested")
    assert set(dto_for(pending, AS_TUTOR)["allowedActions"]) == {"accept", "decline", "post_note"}
    inactive = replace(pending, tutor_listing_state=listing)
    assert dto_for(inactive, AS_TUTOR)["allowedActions"] == []
    ended = make_row(
        state="accepted", starts_at=NOW - timedelta(hours=3), tutor_listing_state=listing
    )
    assert dto_for(ended, AS_TUTOR)["allowedActions"] == []
    assert "cancel" in dto_for(inactive, AS_STUDENT)["allowedActions"]  # the family keeps theirs


def test_accept_withheld_when_blocked_or_listing_cannot_accept() -> None:
    pending = make_row(state="requested")
    assert "accept" not in dto_for(replace(pending, blocked=True), AS_TUTOR)["allowedActions"]
    for listing in ("draft", "rejected"):
        actions = dto_for(replace(pending, tutor_listing_state=listing), AS_TUTOR)["allowedActions"]
        assert "accept" not in actions
        assert "decline" in actions
    assert (
        "accept"
        in dto_for(replace(pending, tutor_listing_state="pending_review"), AS_TUTOR)[
            "allowedActions"
        ]
    )


def test_inside_24h_the_tutor_gets_cancel_with_reason_and_the_family_nothing() -> None:
    soon = make_row(state="accepted", starts_at=NOW + timedelta(hours=10))
    tutor = dto_for(soon, AS_TUTOR)["allowedActions"]
    assert "cancel_with_reason" in tutor
    assert "cancel" not in tutor
    assert "cancel" not in dto_for(soon, AS_STUDENT)["allowedActions"]
    by_parent = replace(soon, requested_by_party="parent", requested_by_user_id=PARENT)
    assert "cancel" not in dto_for(by_parent, AS_PARENT)["allowedActions"]
    later = replace(
        by_parent, starts_at=NOW + timedelta(days=3), ends_at=NOW + timedelta(days=3, hours=1)
    )
    assert "cancel" in dto_for(later, AS_PARENT)["allowedActions"]
    assert "cancel" not in dto_for(later, AS_OTHER_PARENT)["allowedActions"]  # O8: requester only


def test_allowed_actions_keep_the_literal_order() -> None:
    order = [
        "accept",
        "decline",
        "cancel",
        "cancel_with_reason",
        "complete",
        "no_show",
        "review",
        "post_note",
    ]
    pending = dto_for(make_row(state="requested"), AS_TUTOR)["allowedActions"]
    assert pending == [action for action in order if action in pending]


def test_student_shared_tutor_viewer_only() -> None:
    row = make_row()
    assert dto_for(row, AS_TUTOR, shared=True)["studentShared"] is True
    assert dto_for(row, AS_TUTOR, shared=False)["studentShared"] is False
    for viewer in (AS_STUDENT, AS_PARENT):
        dto = build_booking_dto(row, viewer=viewer, now=NOW, student_shared=True)
        assert dto.studentShared is None


def test_student_name_is_always_the_student_label() -> None:
    row = make_row(student_display_name="omar.k@example.com")
    for viewer in VIEWERS:
        name = dto_for(row, viewer)["student"]["displayName"]  # type: ignore[index]
        assert name.startswith("Student ")
        assert "@" not in name


def test_card_subject_area_and_effective_state() -> None:
    dto = dto_for(make_row(state="accepted", starts_at=NOW - timedelta(hours=3)), AS_STUDENT)
    assert dto["effectiveState"] == "awaiting_outcome"
    assert dto["tutor"]["tutorId"] == str(TUTOR_PROFILE)  # type: ignore[index]
    assert dto["tutor"]["publicName"] == "Sara M."  # type: ignore[index]
    assert dto["subject"] == {"code": "0580", "name": "Mathematics"}
    assert dto["area"]["code"] == "cairo"  # type: ignore[index]
    assert dto["bookingId"] == str(BOOKING)
    assert dto["student"]["studentId"] == str(STUDENT)  # type: ignore[index]


def test_bookings_page_marks_shared_students_for_the_tutor_only() -> None:
    other_student = uuid.uuid4()
    rows = [make_row(), replace(make_row(), id=uuid.uuid4(), student_id=other_student)]
    page = build_bookings_page_dto(
        rows, viewer=AS_TUTOR, now=NOW, next_cursor="abc", shared_student_ids={STUDENT}
    )
    assert [item.studentShared for item in page.items] == [True, False]
    assert page.nextCursor == "abc"
    family = build_bookings_page_dto(rows, viewer=AS_STUDENT, now=NOW, next_cursor=None)
    assert [item.studentShared for item in family.items] == [None, None]


def test_booking_notices_follow_the_notice_facts() -> None:
    assert booking_notices_for(make_row()) == []  # no notice: an idempotent repeat
    requested = make_row(
        state="requested",
        notice=BookingNotice(
            event="requested", actor_user_id=STUDENT, linked_parent_ids=(PARENT, OTHER_PARENT)
        ),
    )
    by_user = {notice.user_id: notice for notice in booking_notices_for(requested)}
    assert set(by_user) == {TUTOR_USER, PARENT, OTHER_PARENT}
    assert by_user[TUTOR_USER].type is NotificationType.booking_request
    assert by_user[TUTOR_USER].body == "Omar asked to book a session."
    assert by_user[PARENT].type is NotificationType.booking_update
    assert by_user[PARENT].dedupe_key == f"booking:{BOOKING}:requested"
    late = make_row(
        state="cancelled",
        cancelled_by_party="tutor",
        cancelled_at=NOW,
        cancel_reason="I am unwell",
        notice=BookingNotice(
            event="cancelled",
            actor_user_id=TUTOR_USER,
            linked_parent_ids=(),
            late_tutor_cancel=True,
        ),
    )
    (notice,) = booking_notices_for(late)
    assert notice.user_id == STUDENT
    assert notice.body == "Sara M. cancelled your session. Open it to see why."
    assert "unwell" not in f"{notice.title} {notice.body}"


def test_note_notices_follow_the_notice_facts() -> None:
    note = NoteRow(
        id=uuid.uuid4(),
        booking_id=BOOKING,
        author_party="tutor",
        author_name="Sara M.",
        body="Chapter 4 next time",
        hidden=False,
        created_at=NOW,
        notice=NoteNotice(
            tutor_user_id=TUTOR_USER,
            tutor_name="Sara M.",
            student_id=STUDENT,
            student_label="Omar",
            linked_parent_ids=(PARENT,),
            tutor_zone="Africa/Cairo",
        ),
    )
    notices = note_notices_for(note)
    assert {notice.user_id for notice in notices} == {STUDENT, PARENT}
    assert all("Chapter" not in f"{n.title} {n.body}" for n in notices)
    assert note_notices_for(replace(note, notice=None)) == []


def test_note_dto_never_carries_a_hidden_body() -> None:
    visible = NoteRow(
        id=uuid.uuid4(),
        booking_id=BOOKING,
        author_party="student",
        author_name="Omar",
        body="See you Monday",
        hidden=False,
        created_at=NOW,
    )
    assert build_note_dto(visible).model_dump() == {
        "noteId": str(visible.id),
        "authorParty": "student",
        "authorName": "Omar",
        "body": "See you Monday",
        "hidden": False,
        "createdAt": NOW.isoformat(),
    }
    hidden = replace(visible, hidden=True)
    assert build_note_dto(hidden).body is None
    page = build_notes_page_dto(
        NotesPage(items=(visible, hidden), next_key=None, can_post=False), next_cursor=None
    )
    assert [item.body for item in page.items] == ["See you Monday", None]
    assert page.canPost is False


def test_slots_dto_is_iso_instants_in_the_tutor_zone() -> None:
    start = datetime(2026, 11, 12, 13, 0, tzinfo=UTC)
    view = SlotsView(
        tutor_id=TUTOR_PROFILE,
        zone="Africa/Cairo",
        duration_minutes=60,
        window_start=datetime(2026, 11, 11, 22, 0, tzinfo=UTC),
        window_end=datetime(2026, 11, 14, 22, 0, tzinfo=UTC),
        slots=((start, start + timedelta(hours=1)),),
    )
    dto = build_slots_dto(view)
    assert dto.model_dump() == {
        "tutorId": str(TUTOR_PROFILE),
        "zone": "Africa/Cairo",
        "zoneLabel": "Cairo time",
        "durationMinutes": 60,
        "windowStart": "2026-11-11T22:00:00+00:00",
        "windowEnd": "2026-11-14T22:00:00+00:00",
        "slots": [{"startsAt": "2026-11-12T13:00:00+00:00", "endsAt": "2026-11-12T14:00:00+00:00"}],
    }
