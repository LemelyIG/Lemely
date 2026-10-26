"""S1-S5, S14, S15: a student's own sessions, notes and safety notice (SPEC §b.2 "Student").

Route-level, through ``tests.test_web_tutoring_booking.bookings_client``.

* S1 pages the caller's bookings, upcoming (live, ``ends_at`` after the split, earliest first)
  or past (the rest, latest first); the split is fixed by the first page and the cursor is
  tagged with its list *and* its ``when``, so an upcoming cursor never pages the past list.
* S2 is the caller's own booking; anyone else's is the same 404 as an unknown id (O5).
* S3 cancels: a request any time before its start, an accepted session only until 24 hours
  before it (row 18: 409 ``cancel_window_closed`` inside that). A tutor's late cancel reason is
  shown to the student and the linked parents in the booking.
* S4/S5: the thread, oldest first, and a new note by the booking's student (row 16 ii: the
  safety notice first); the tutor is told after the commit, without the note text.
* S14: the 48-hour outcome claim (SC-17); S15 records the safety notice once, idempotently.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import structlog.testing

from lemely.db.booking_repo import Actor, BookingService
from lemely.db.models.enums import BookingState, Role
from lemely.web.schemas_tutoring import BookingDTO, NoteDTO
from tests.test_booking_repo import (
    LINK,
    World,
    add_booking,
    add_parent,
    another_tutor,
    make_world,
    stored,
)
from tests.test_tutor_grant_repo import inbox_rows, outbox_rows
from tests.test_web_tutoring_booking import (
    BOOKINGS,
    NO_STORE,
    BrokenNotifications,
    booking_body,
    bookings_client,
    detail_code,
    note_count,
)
from tests.tutoring_db import act_as, emptied_after, tutoring_database

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session, sessionmaker

LIST = "/api/student/bookings"
SAFETY = "/api/student/tutoring-safety-notice"


def one(booking_id: uuid.UUID | str) -> str:
    return f"{LIST}/{booking_id}"


@pytest.fixture(scope="module")
def tutoring_db() -> Iterator[sessionmaker[Session]]:
    with tutoring_database() as factory:
        yield factory


@pytest.fixture
def sm(tutoring_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(tutoring_db)


@pytest.fixture
def client(sm: sessionmaker[Session]) -> Iterator[TestClient]:
    test_client = bookings_client(sm)
    yield test_client
    test_client.app.dependency_overrides.clear()  # type: ignore[attr-defined]


@pytest.fixture
def w(sm: sessionmaker[Session], client: TestClient) -> World:
    world = make_world(sm, display_name="Amelia")
    act_as(client, world.student, Role.student)
    return world


# ---------------------------------------------------------------------------
# S1, S2
# ---------------------------------------------------------------------------


def test_s1_upcoming_and_past_pages_with_a_when_tagged_cursor(
    sm: sessionmaker[Session], client: TestClient, w: World
) -> None:
    tutors = [another_tutor(sm, w.subject) for _ in range(6)]
    made = {
        "live": add_booking(sm, w, tutor=tutors[0], starts_in=timedelta(days=1)),
        "accepted": add_booking(
            sm, w, tutor=tutors[1], state="accepted", starts_in=timedelta(days=2)
        ),
        "awaiting": add_booking(
            sm, w, tutor=tutors[2], state="accepted", starts_in=-timedelta(hours=3)
        ),
        "completed": add_booking(
            sm, w, tutor=tutors[3], state="completed", starts_in=-timedelta(days=3)
        ),
        "cancelled": add_booking(
            sm, w, tutor=tutors[4], state="cancelled", starts_in=timedelta(days=4)
        ),
        "stale": add_booking(sm, w, tutor=tutors[5], starts_in=-timedelta(hours=5)),
    }
    other = make_world(sm)
    add_booking(sm, other, starts_in=timedelta(days=1))  # someone else's

    first = client.get(LIST, params={"when": "upcoming", "limit": 1})

    assert first.status_code == 200, first.text
    assert first.headers["cache-control"] == NO_STORE
    page = first.json()
    assert [item["bookingId"] for item in page["items"]] == [str(made["live"])]
    assert set(page["items"][0]) == set(BookingDTO.model_fields)
    assert page["items"][0]["studentShared"] is None
    rest = client.get(LIST, params={"when": "upcoming", "limit": 1, "cursor": page["nextCursor"]})
    assert [item["bookingId"] for item in rest.json()["items"]] == [str(made["accepted"])]
    assert rest.json()["nextCursor"] is None

    past = client.get(LIST, params={"when": "past"}).json()
    assert [item["bookingId"] for item in past["items"]] == [
        str(made[name]) for name in ("cancelled", "awaiting", "stale", "completed")
    ]
    assert [item["effectiveState"] for item in past["items"]] == [
        "cancelled",
        "awaiting_outcome",
        "expired",
        "completed",
    ]

    # O21: the cursor is this list's and this ``when``'s only.
    crossed = client.get(LIST, params={"when": "past", "cursor": page["nextCursor"]})
    assert crossed.status_code == 422
    assert detail_code(crossed) == "invalid_cursor"
    assert crossed.headers["cache-control"] == NO_STORE
    for params in (
        {"when": "upcoming", "cursor": "not-a-cursor"},
        {"when": "upcoming", "limit": 0},
        {"when": "upcoming", "limit": 51},
        {"when": "soon"},
        {},
    ):
        refused = client.get(LIST, params=params)
        assert refused.status_code == 422, params
        assert refused.headers["cache-control"] == NO_STORE


def test_s2_own_booking_and_one_404_for_anyone_elses(
    sm: sessionmaker[Session], client: TestClient, w: World
) -> None:
    mine = add_booking(sm, w, state="accepted", starts_in=timedelta(days=2))
    other = make_world(sm)
    theirs = add_booking(sm, other, starts_in=timedelta(days=2))

    response = client.get(one(mine))

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == NO_STORE
    booking = response.json()
    assert booking["bookingId"] == str(mine)
    assert booking["meetingLink"] == LINK  # accepted: the student sees the link (O16)
    assert booking["allowedActions"] == ["cancel", "post_note"]
    assert (booking["review"], booking["reviewOpensAt"], booking["studentShared"]) == (
        None,
        None,
        None,
    )
    refusals = [client.get(one(theirs)), client.get(one(uuid.uuid4()))]
    assert [r.status_code for r in refusals] == [404, 404]
    assert refusals[0].content == refusals[1].content
    assert refusals[0].headers["cache-control"] == NO_STORE
    assert client.get(one("not-a-uuid")).status_code == 422


# ---------------------------------------------------------------------------
# S3
# ---------------------------------------------------------------------------


def test_s3_cancel_tells_the_tutor_and_parents_and_a_repeat_is_200(
    sm: sessionmaker[Session], client: TestClient, w: World
) -> None:
    parent = add_parent(sm, w.student)
    booking = add_booking(sm, w, state="accepted", starts_in=timedelta(days=3))

    response = client.post(f"{one(booking)}/cancel", json={"reason": "  Exams moved  "})

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == NO_STORE
    body = response.json()
    assert (body["effectiveState"], body["cancelledBy"], body["cancelReason"]) == (
        "cancelled",
        "student",
        "Exams moved",
    )
    assert body["cancelledLate"] is False
    assert stored(sm, booking).state is BookingState.cancelled
    notices = inbox_rows(sm)
    assert sorted((user, kind) for user, kind, _, _ in notices) == sorted(
        [(w.tutor.user_id, "booking_update"), (parent, "booking_update")]
    )
    assert all("Exams moved" not in (row[3] or "") for row in notices)  # no reason in a notice
    emails = outbox_rows(sm)
    assert sorted((user, template) for user, template, _ in emails) == sorted(
        [(w.tutor.user_id, "booking_cancelled"), (parent, "booking_cancelled")]
    )

    again = client.post(f"{one(booking)}/cancel")  # no body at all is a cancel without a reason

    assert again.status_code == 200, again.text
    assert again.json()["effectiveState"] == "cancelled"
    assert inbox_rows(sm) == notices  # an idempotent repeat tells nobody
    assert outbox_rows(sm) == emails


def test_s3_late_cancel_409_cancel_window_closed(
    sm: sessionmaker[Session], client: TestClient, w: World
) -> None:
    """Row 18: inside 24 hours of the start only the tutor may cancel an accepted session."""
    late = add_booking(sm, w, state="accepted", starts_in=timedelta(hours=10))

    refused = client.post(f"{one(late)}/cancel", json={"reason": "Something came up"})

    assert refused.status_code == 409, refused.text
    assert detail_code(refused) == "cancel_window_closed"
    assert refused.headers["cache-control"] == NO_STORE
    assert stored(sm, late).state is BookingState.accepted
    assert inbox_rows(sm) == []
    assert outbox_rows(sm) == []
    # Red case: a day further out the same student may cancel.
    early = add_booking(
        sm, w, state="accepted", starts_in=timedelta(hours=30), tutor=another_tutor(sm, w.subject)
    )
    assert client.post(f"{one(early)}/cancel").status_code == 200


def test_s3_refusals(sm: sessionmaker[Session], client: TestClient, w: World) -> None:
    started = add_booking(sm, w, starts_in=-timedelta(minutes=20))  # a request whose time passed
    future = add_booking(sm, w, starts_in=timedelta(days=2), tutor=another_tutor(sm, w.subject))
    cases = [
        (started, {}, 409, "illegal_transition"),
        (future, {"reason": "Call me on 0100 123 4567"}, 422, "contact_details_not_allowed"),
        (future, {"reason": "x" * 301}, 422, "text_too_long"),
    ]
    for booking, body, status, code in cases:
        response = client.post(f"{one(booking)}/cancel", json=body)
        assert response.status_code == status, (code, response.text)
        assert detail_code(response) == code
        assert response.headers["cache-control"] == NO_STORE
    assert stored(sm, future).state is BookingState.requested


def test_t13_late_cancel_with_reason_200_reason_visible_to_student_and_parent(
    sm: sessionmaker[Session], client: TestClient, w: World
) -> None:
    """Row 18, the family half: the tutor's late reason is read in the booking (S2 and PA2)."""
    parent = add_parent(sm, w.student)
    booking = add_booking(sm, w, state="accepted", starts_in=timedelta(hours=10))
    BookingService(sm).transition(  # T13 (the tutor's route is T18's)
        booking_id=booking, actor=w.tutor_actor, action="cancel", reason="I am unwell today"
    )
    other_tutor = another_tutor(sm, w.subject)
    early = add_booking(sm, w, state="accepted", starts_in=timedelta(days=3), tutor=other_tutor)
    BookingService(sm).transition(
        booking_id=early, actor=Actor(user_id=other_tutor.user_id, party="tutor"), action="cancel"
    )

    seen = {"student": client.get(one(booking)).json()}
    act_as(client, parent, Role.parent)
    seen["parent"] = client.get(f"/api/parent/children/{w.student}/bookings/{booking}").json()
    for viewer, body in seen.items():
        assert (body["cancelReason"], body["cancelledBy"], body["cancelledLate"]) == (
            "I am unwell today",
            "tutor",
            True,
        ), viewer
        assert body["effectiveState"] == "cancelled", viewer
    # Red case: a tutor's cancel more than a day ahead is not late.
    act_as(client, w.student, Role.student)
    assert client.get(one(early)).json()["cancelledLate"] is False


def test_s3_commits_when_inbox_write_raises(sm: sessionmaker[Session]) -> None:
    """D5.9 §1 at the router: the cancel and its emails commit; the inbox failure is logged."""
    client = bookings_client(sm, notifications=BrokenNotifications())
    w = make_world(sm)
    parent = add_parent(sm, w.student)
    booking = add_booking(sm, w, state="accepted", starts_in=timedelta(days=3))
    act_as(client, w.student, Role.student)

    with structlog.testing.capture_logs() as logs:
        response = client.post(f"{one(booking)}/cancel")

    assert response.status_code == 200, response.text
    assert stored(sm, booking).state is BookingState.cancelled
    assert len(outbox_rows(sm)) == 2  # tutor and parent, queued in the cancel's transaction
    failures = [entry for entry in logs if entry["event"] == "notification_create_failed"]
    assert sorted(entry["user_id"] for entry in failures) == sorted(
        [str(w.tutor.user_id), str(parent)]
    )


# ---------------------------------------------------------------------------
# S4, S5
# ---------------------------------------------------------------------------


def test_s5_posts_a_note_and_s4_pages_the_thread_oldest_first(
    sm: sessionmaker[Session], client: TestClient, w: World
) -> None:
    parent = add_parent(sm, w.student)
    booking = add_booking(sm, w, state="accepted", starts_in=timedelta(days=2))

    posted = client.post(f"{one(booking)}/notes", json={"body": "  Can we start with algebra?  "})

    assert posted.status_code == 201, posted.text
    assert posted.headers["cache-control"] == NO_STORE
    note = posted.json()
    assert set(note) == set(NoteDTO.model_fields)
    assert (note["authorParty"], note["authorName"], note["body"], note["hidden"]) == (
        "student",
        "Amelia",
        "Can we start with algebra?",
        False,
    )
    notices = inbox_rows(sm)
    assert [(user, kind, title) for user, kind, title, _ in notices] == [
        (w.tutor.user_id, "booking_note", "New note")
    ]
    assert "algebra" not in (notices[0][3] or "")  # the note text never travels
    assert parent not in {user for user, *_ in notices}  # parents hear of tutor notes only

    for text in ("Second note", "Third note"):
        assert client.post(f"{one(booking)}/notes", json={"body": text}).status_code == 201
    first = client.get(f"{one(booking)}/notes", params={"limit": 2})
    assert first.status_code == 200, first.text
    assert first.headers["cache-control"] == NO_STORE
    page = first.json()
    assert [item["body"] for item in page["items"]] == ["Can we start with algebra?", "Second note"]
    assert page["canPost"] is True
    rest = client.get(f"{one(booking)}/notes", params={"limit": 2, "cursor": page["nextCursor"]})
    assert [item["body"] for item in rest.json()["items"]] == ["Third note"]
    assert rest.json()["nextCursor"] is None
    # O21: a booking-list cursor is not a notes cursor.
    add_booking(sm, w, starts_in=timedelta(days=5), tutor=another_tutor(sm, w.subject))
    list_cursor = client.get(LIST, params={"when": "upcoming", "limit": 1}).json()["nextCursor"]
    assert list_cursor is not None
    crossed = client.get(f"{one(booking)}/notes", params={"cursor": list_cursor})
    assert crossed.status_code == 422
    assert detail_code(crossed) == "invalid_cursor"


def test_s5_refusals(sm: sessionmaker[Session], client: TestClient, w: World) -> None:
    open_booking = add_booking(sm, w, state="accepted", starts_in=timedelta(days=2))
    cancelled = add_booking(
        sm, w, state="cancelled", starts_in=timedelta(days=3), tutor=another_tutor(sm, w.subject)
    )
    cases = [
        (open_booking, "Call me on 0100 123 4567", 422, "contact_details_not_allowed"),
        (open_booking, "   ", 422, "note_empty"),
        (open_booking, "x" * 2001, 422, "text_too_long"),
        (cancelled, "Hello", 409, "notes_closed"),
    ]
    for booking, text, status, code in cases:
        response = client.post(f"{one(booking)}/notes", json={"body": text})
        assert response.status_code == status, (code, response.text)
        assert detail_code(response) == code
        assert response.headers["cache-control"] == NO_STORE
    unacknowledged = make_world(sm, acknowledged=False)
    theirs = add_booking(sm, unacknowledged, state="accepted", starts_in=timedelta(days=2))
    act_as(client, unacknowledged.student, Role.student)
    refused = client.post(f"{one(theirs)}/notes", json={"body": "Hello"})
    assert refused.status_code == 409
    assert detail_code(refused) == "safety_notice_required"
    assert note_count(sm) == 0
    assert inbox_rows(sm) == []


# ---------------------------------------------------------------------------
# S14
# ---------------------------------------------------------------------------


def test_authz_student_may_complete_after_48h_awaiting_outcome(
    sm: sessionmaker[Session], client: TestClient, w: World
) -> None:
    parent = add_parent(sm, w.student)
    early = add_booking(sm, w, state="accepted", starts_in=-timedelta(hours=48))  # ended 47 h ago

    refused = client.post(f"{one(early)}/complete")

    assert refused.status_code == 409, refused.text
    assert detail_code(refused) == "outcome_claim_not_open"
    assert refused.headers["cache-control"] == NO_STORE
    assert stored(sm, early).state is BookingState.accepted

    other_tutor = another_tutor(sm, w.subject)
    late = add_booking(sm, w, state="accepted", starts_in=-timedelta(hours=50), tutor=other_tutor)
    claimed = client.post(f"{one(late)}/complete")

    assert claimed.status_code == 200, claimed.text
    assert claimed.headers["cache-control"] == NO_STORE
    assert (claimed.json()["effectiveState"], claimed.json()["completedBy"]) == (
        "completed",
        "student",
    )
    assert sorted((user, title) for user, _, title, _ in inbox_rows(sm)) == sorted(
        [(other_tutor.user_id, "Session completed"), (parent, "Session completed")]
    )
    notices = inbox_rows(sm)
    assert client.post(f"{one(late)}/complete").status_code == 200  # idempotent
    assert inbox_rows(sm) == notices


def test_s14_refused_after_a_tutor_outcome(
    sm: sessionmaker[Session], client: TestClient, w: World
) -> None:
    no_show = add_booking(sm, w, state="no_show", starts_in=-timedelta(hours=60))
    refused = client.post(f"{one(no_show)}/complete")
    assert refused.status_code == 409
    assert detail_code(refused) == "outcome_claim_not_open"
    assert stored(sm, no_show).state is BookingState.no_show


# ---------------------------------------------------------------------------
# S15
# ---------------------------------------------------------------------------


def test_s15_safety_notice_is_idempotent_and_opens_booking(
    sm: sessionmaker[Session], client: TestClient
) -> None:
    w = make_world(sm, acknowledged=False)
    act_as(client, w.student, Role.student)
    blocked = client.post(BOOKINGS, json=booking_body(w))
    assert blocked.status_code == 409
    assert detail_code(blocked) == "safety_notice_required"

    first = client.post(SAFETY)
    second = client.post(SAFETY)

    assert first.status_code == second.status_code == 200, first.text
    assert first.headers["cache-control"] == NO_STORE
    settings = first.json()
    assert set(settings) == {
        "outcomeStatsOptOut",
        "outcomePrefChangedAt",
        "safetyNoticeAcknowledgedAt",
    }
    assert (settings["outcomeStatsOptOut"], settings["outcomePrefChangedAt"]) == (False, None)
    acknowledged_at = datetime.fromisoformat(settings["safetyNoticeAcknowledgedAt"])
    assert abs(acknowledged_at - datetime.now(UTC)) < timedelta(minutes=5)
    assert second.json() == settings  # the first instant is kept
    assert client.post(BOOKINGS, json=booking_body(w)).status_code == 201
