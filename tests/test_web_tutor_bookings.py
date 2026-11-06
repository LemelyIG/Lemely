"""T9-T17: a tutor's bookings and their notes, at the route (PLAN T18).

SPEC ``docs/tutoring/SPEC.md`` §b.2 "Tutor" (T9-T17), §a.3 (state machine, effective states,
notes table), row 18 (a tutor's late cancel needs a reason, O30), §b.4 (outbox rows in the
change's transaction, inbox notices after commit, D5.9 §1), §e.3 (query budget) and §i.4-§i.7.

Route-level. The app is built with ``tests.tutoring_app.app_with_routers`` (a lane never edits
``lemely/web/app.py``) and wired to a throwaway ``create_all`` database. Bookings are seeded as
rows with ``tests.test_booking_repo``'s helpers, relative to the real clock: every write guard
compares with the database ``now()``.

The object-level rules (O4, the suspended and closed refusals, the notes state table, the
``no_tutor_profile`` 404 on every route) are in ``tests/test_web_tutoring_authz_bookings_tutor.py``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, get_args

import pytest
import structlog.testing
from fastapi.testclient import TestClient

from lemely.core.booking import effective_state
from lemely.db.booking_repo import Actor, BookingService
from lemely.db.models.enums import BookingParty, BookingState, GrantRevokeReason, Role
from lemely.db.notification_prefs_repo import NotificationPreferencesService
from lemely.db.notification_repo import NotificationService
from lemely.db.tutor_grant_repo import TutorGrantRepository
from lemely.db.tutor_profile_repo import TutorProfileRepository
from lemely.web.booking_view import build_booking_dto
from lemely.web.deps import get_notification_service, get_push_transport
from lemely.web.deps_tutoring import get_tutor_profile_repo
from lemely.web.push import RecordingPushTransport
from lemely.web.routers import tutor_bookings
from lemely.web.routers.student_tutor_access import get_tutor_grant_repo
from lemely.web.routers.tutor_bookings import get_booking_service
from lemely.web.schemas_tutoring import EffectiveStateLit
from tests.test_booking_repo import (
    LINK,
    PLACE,
    World,
    add_booking,
    add_parent,
    add_student,
    make_world,
    notes,
    outbox,
    set_listing,
    stored,
)
from tests.test_tutor_grant_repo import add_grant, audit_rows, inbox_rows
from tests.tutoring_app import app_with_routers
from tests.tutoring_db import (
    act_as,
    count_statements,
    emptied_after,
    tutoring_database,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from httpx import Response
    from sqlalchemy.orm import Session, sessionmaker

NO_STORE = "private, no-store"
CONTACT_PHONE = "Call me on 01001234567"
REASON = "I am unwell today"


# ---------------------------------------------------------------------------
# App and fixtures (imported by the authz file)
# ---------------------------------------------------------------------------


def bookings_client(
    sm: sessionmaker[Session],
    *,
    notifications: object | None = None,
    transport: RecordingPushTransport | None = None,
) -> TestClient:
    """T9-T17 on a fresh app, wired to the test database.

    ``notifications`` replaces the inbox service (the D5.9 proof passes one that raises).
    """
    app = app_with_routers(tutor_bookings.router)
    push = transport if transport is not None else RecordingPushTransport()
    inbox = (
        notifications
        if notifications is not None
        else NotificationService(sm, NotificationPreferencesService(sm))
    )
    app.dependency_overrides[get_tutor_profile_repo] = lambda: TutorProfileRepository(sm)
    app.dependency_overrides[get_booking_service] = lambda: BookingService(sm)
    app.dependency_overrides[get_tutor_grant_repo] = lambda: TutorGrantRepository(sm)
    app.dependency_overrides[get_notification_service] = lambda: inbox
    app.dependency_overrides[get_push_transport] = lambda: push
    return TestClient(app)


def as_tutor(client: TestClient, w: World) -> None:
    act_as(client, w.tutor.user_id, Role.teacher)


def url(booking_id: uuid.UUID, suffix: str = "") -> str:
    return f"/api/tutor/bookings/{booking_id}{suffix}"


def code_of(response: Response) -> str:
    detail = response.json()["detail"]
    assert isinstance(detail, dict), detail
    return str(detail["code"])


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
def w(sm: sessionmaker[Session]) -> World:
    return make_world(sm)


# ---------------------------------------------------------------------------
# T9: the tutor's list
# ---------------------------------------------------------------------------


def test_t9_lists_own_bookings_by_when_with_typed_cursor(
    sm: sessionmaker[Session], client: TestClient, w: World
) -> None:
    upcoming = [
        add_booking(sm, w, state="accepted", starts_in=timedelta(days=day)) for day in (3, 1, 2)
    ]
    past = add_booking(sm, w, state="completed", starts_in=-timedelta(days=3))
    other_world = make_world(sm)
    add_booking(sm, other_world, state="accepted", starts_in=timedelta(days=1))
    as_tutor(client, w)

    first = client.get("/api/tutor/bookings", params={"when": "upcoming", "limit": 2})
    assert first.status_code == 200, first.text
    assert first.headers["cache-control"] == NO_STORE
    cursor = first.json()["nextCursor"]
    assert isinstance(cursor, str)
    second = client.get(
        "/api/tutor/bookings", params={"when": "upcoming", "limit": 2, "cursor": cursor}
    )
    assert second.status_code == 200, second.text
    assert second.json()["nextCursor"] is None
    listed = [item["bookingId"] for item in first.json()["items"] + second.json()["items"]]
    by_start = sorted(upcoming, key=lambda booking: stored(sm, booking).starts_at)
    assert listed == [str(booking) for booking in by_start]  # starts_at ASC; own bookings only

    history = client.get("/api/tutor/bookings", params={"when": "past"})
    assert [item["bookingId"] for item in history.json()["items"]] == [str(past)]

    # O21: a cursor belongs to its own list (the direction differs with ``when``).
    for params in (
        {"when": "past", "cursor": cursor},
        {"when": "upcoming", "state": "accepted", "cursor": cursor},
        {"when": "upcoming", "cursor": "not-a-cursor"},
    ):
        refused = client.get("/api/tutor/bookings", params=params)
        assert refused.status_code == 422, params
        assert code_of(refused) == "invalid_cursor"
        assert refused.headers["cache-control"] == NO_STORE
    for params in (
        {},
        {"when": "later"},
        {"when": "past", "limit": 0},
        {"when": "past", "limit": 51},
    ):
        assert client.get("/api/tutor/bookings", params=params).status_code == 422, params


def test_t9_state_filter_uses_effective_predicates(
    sm: sessionmaker[Session], client: TestClient, w: World
) -> None:
    """``state`` is an effective state (SPEC §a.3), matched exactly as ``core.booking`` derives it.

    The expected side is ``core.booking.effective_state`` over each seeded row, not the route's
    SQL: a stale request must list as ``expired`` (never ``requested``) and a finished accepted
    session as ``awaiting_outcome`` (never ``accepted``).
    """
    seeds = [
        ("requested", timedelta(days=2)),
        ("requested", -timedelta(minutes=30)),  # stale: effectively expired
        ("expired", -timedelta(days=1)),
        ("accepted", timedelta(days=3)),
        ("accepted", -timedelta(hours=3)),  # ended two hours ago: awaiting_outcome
        ("completed", -timedelta(days=2)),
        ("cancelled", timedelta(days=4)),
        ("declined", timedelta(days=5)),
        ("no_show", -timedelta(days=1)),
    ]
    expected: dict[str, set[str]] = {state: set() for state in get_args(EffectiveStateLit)}
    now = datetime.now(UTC)
    for state, starts_in in seeds:
        booking = add_booking(sm, w, state=state, starts_in=starts_in, student=add_student(sm))
        row = stored(sm, booking)
        effective = effective_state(
            row.state.value, starts_at=row.starts_at, ends_at=row.ends_at, now=now
        )
        expected[effective].add(str(booking))
    assert all(expected.values()), expected  # non-vacuity: every effective state has a row
    as_tutor(client, w)

    for state, ids in expected.items():
        found: dict[str, set[str]] = {}
        for when in ("upcoming", "past"):
            response = client.get("/api/tutor/bookings", params={"when": when, "state": state})
            assert response.status_code == 200, response.text
            items = response.json()["items"]
            assert {item["effectiveState"] for item in items} <= {state}
            found[when] = {item["bookingId"] for item in items}
        assert not found["upcoming"] & found["past"]
        assert found["upcoming"] | found["past"] == ids, state
    refused = client.get("/api/tutor/bookings", params={"when": "past", "state": "pending"})
    assert refused.status_code == 422


def test_query_budget_t9_three_repository_statements_plus_guard(
    sm: sessionmaker[Session], client: TestClient, w: World
) -> None:
    """SPEC §e.3: the page costs three repository statements whatever it holds, plus the guard.

    Rows and subjects (the booking list proper) plus one ``studentShared`` statement for the
    whole page (F13: the grant predicate, never the audited gate), and the profile guard before
    them: four statements in all, none of them growing with the row count.
    """
    add_grant(sm, w.student, w.tutor)
    add_booking(sm, w, state="accepted", starts_in=timedelta(days=1))
    as_tutor(client, w)

    def run() -> list[str]:
        with count_statements(sm) as seen:
            response = client.get("/api/tutor/bookings", params={"when": "upcoming"})
        assert response.status_code == 200, response.text
        assert response.json()["items"]  # non-vacuity
        return seen

    one = run()
    for day in range(2, 7):
        add_booking(sm, w, state="accepted", starts_in=timedelta(days=day), student=add_student(sm))
    six = run()

    def kinds(statements: list[str]) -> dict[str, int]:
        found = {"list": 0, "shared": 0, "profile": 0, "other": 0}
        for sql in statements:
            if "FROM tutor_bookings" in sql or "FROM tutor_subjects" in sql:
                found["list"] += 1
            elif "tutor_data_grants" in sql:
                found["shared"] += 1
            elif "FROM tutor_profiles" in sql:
                found["profile"] += 1
            else:
                found["other"] += 1
        return found

    assert kinds(one) == kinds(six) == {"list": 2, "shared": 1, "profile": 1, "other": 0}, six
    assert not any("INSERT" in sql.upper() for sql in six)
    assert len(client.get("/api/tutor/bookings", params={"when": "upcoming"}).json()["items"]) == 6


# ---------------------------------------------------------------------------
# T10 and ``studentShared`` (F13)
# ---------------------------------------------------------------------------


def test_t10_student_shared_writes_no_audit_row(
    sm: sessionmaker[Session], client: TestClient, w: World
) -> None:
    """``studentShared`` is the grant predicate only: T20's ``detail`` audit row is never written.

    Absence test: the mutation that reads it through ``require_valid_grant`` (the audited gate)
    turns this red.
    """
    add_grant(sm, w.student, w.tutor)
    shared_session = add_booking(sm, w, state="accepted", starts_in=timedelta(days=2))
    shared_request = add_booking(sm, w, state="requested", starts_in=timedelta(days=4))
    unshared = add_student(sm)
    unshared_session = add_booking(
        sm, w, state="accepted", starts_in=timedelta(days=3), student=unshared
    )
    ended = add_student(sm)
    add_grant(sm, ended, w.tutor, revoked=GrantRevokeReason.student)
    ended_session = add_booking(sm, w, state="accepted", starts_in=timedelta(days=5), student=ended)
    as_tutor(client, w)

    detail = {
        booking: client.get(url(booking))
        for booking in (shared_session, unshared_session, ended_session)
    }
    assert {booking: r.json()["studentShared"] for booking, r in detail.items()} == {
        shared_session: True,
        unshared_session: False,
        ended_session: False,
    }
    page = client.get("/api/tutor/bookings", params={"when": "upcoming"}).json()["items"]
    assert {item["bookingId"]: item["studentShared"] for item in page} == {
        str(shared_session): True,
        str(shared_request): True,
        str(unshared_session): False,
        str(ended_session): False,
    }
    declined = client.post(url(shared_request, "/decline"), json={})
    assert declined.status_code == 200, declined.text
    assert declined.json()["studentShared"] is True
    assert audit_rows(sm) == []


# ---------------------------------------------------------------------------
# T11: accept
# ---------------------------------------------------------------------------


def test_t11_accept_returns_the_link_and_tells_the_family(
    sm: sessionmaker[Session], client: TestClient, w: World
) -> None:
    parent = add_parent(sm, w.student)
    booking = add_booking(sm, w, state="requested", starts_in=timedelta(days=3))
    as_tutor(client, w)

    response = client.post(url(booking, "/accept"), json={"meetingLink": LINK})

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["effectiveState"], body["meetingLink"], body["locationDetail"]) == (
        "accepted",
        LINK,
        None,
    )
    assert body["allowedActions"] == ["cancel", "post_note"]
    assert body["studentShared"] is False
    assert body["review"] is None
    db = stored(sm, booking)
    assert db.state is BookingState.accepted
    assert db.accepted_at is not None
    assert {(r, t) for r, t, _ in outbox(sm)} == {
        (w.student, "booking_accepted"),
        (parent, "booking_accepted"),
    }
    assert {(user, title) for user, _, title, _ in inbox_rows(sm)} == {
        (w.student, "Session accepted"),
        (parent, "Session accepted"),
    }  # the tutor is not told about their own action
    written = (outbox(sm), inbox_rows(sm))

    again = client.post(url(booking, "/accept"), json={"meetingLink": LINK})
    assert again.status_code == 200, again.text  # an idempotent repeat
    assert (outbox(sm), inbox_rows(sm)) == written


def test_t11_meeting_link_allowlist_and_location_required(
    sm: sessionmaker[Session], client: TestClient, w: World
) -> None:
    """SC-7, SC-4: virtual needs an allowlisted ``https`` link; in person needs a place.

    Only the detail the booking's mode keeps is checked; the other is dropped unread (§i.7).
    """
    online = add_booking(sm, w, state="requested", starts_in=timedelta(days=2))
    in_person = add_booking(
        sm,
        w,
        state="requested",
        starts_in=timedelta(days=3),
        mode="in_person",
        student=add_student(sm),
    )
    as_tutor(client, w)

    for body in (
        None,
        {},
        {"meetingLink": "http://zoom.us/j/123"},
        {"meetingLink": "https://zoom.us.evil.example/j/123"},
        {"meetingLink": "https://zoom.us@evil.example/j/123"},
        {"meetingLink": "https://wa.me/201001234567"},
        {"locationDetail": PLACE},
    ):
        refused = client.post(url(online, "/accept"), json=body)
        assert refused.status_code == 422, (body, refused.text)
        assert code_of(refused) == "meeting_link_not_allowed"
    for body, code in (
        (None, "location_required"),
        ({"locationDetail": "   "}, "location_required"),
        ({"meetingLink": LINK}, "location_required"),
        ({"locationDetail": CONTACT_PHONE}, "contact_details_not_allowed"),
    ):
        refused = client.post(url(in_person, "/accept"), json=body)
        assert refused.status_code == 422, (body, refused.text)
        assert code_of(refused) == code
    assert stored(sm, online).state is BookingState.requested
    assert stored(sm, in_person).state is BookingState.requested
    assert outbox(sm) == []

    accepted = client.post(url(online, "/accept"), json={"meetingLink": LINK})
    assert accepted.status_code == 200, accepted.text
    placed = client.post(
        url(in_person, "/accept"),
        json={"locationDetail": f"  {PLACE}  ", "meetingLink": "http://not-checked.example"},
    )
    assert placed.status_code == 200, placed.text
    assert (placed.json()["locationDetail"], placed.json()["meetingLink"]) == (PLACE, None)
    assert (stored(sm, in_person).location_detail, stored(sm, in_person).meeting_link) == (
        PLACE,
        None,
    )


@pytest.mark.parametrize("listing", ["draft", "rejected"])
def test_t11_accept_on_unlisted_profile_uses_tutor_voice(
    sm: sessionmaker[Session], client: TestClient, w: World, listing: str
) -> None:
    """§i.7: ``tutor_not_listed`` reaches the tutor in the tutor's own words, not SP6's."""
    booking = add_booking(sm, w, state="requested", starts_in=timedelta(days=2))
    set_listing(sm, w.tutor, listing)
    as_tutor(client, w)

    assert "accept" not in client.get(url(booking)).json()["allowedActions"]
    refused = client.post(url(booking, "/accept"), json={"meetingLink": LINK})
    assert refused.status_code == 409, refused.text
    assert code_of(refused) == "tutor_not_listed"
    message = refused.json()["detail"]["message"]
    assert message.startswith("Your tutor profile"), message
    assert "this tutor" not in message.lower()
    assert stored(sm, booking).state is BookingState.requested

    set_listing(sm, w.tutor, "pending_review")  # pending review may still accept (§a.3)
    assert client.post(url(booking, "/accept"), json={"meetingLink": LINK}).status_code == 200


# ---------------------------------------------------------------------------
# T12, T13: decline and cancel
# ---------------------------------------------------------------------------


def test_t12_decline_records_the_reason_and_tells_the_family(
    sm: sessionmaker[Session], client: TestClient, w: World
) -> None:
    booking = add_booking(sm, w, state="requested", starts_in=timedelta(days=2))
    without_reason = add_booking(
        sm, w, state="requested", starts_in=timedelta(days=3), student=add_student(sm)
    )
    as_tutor(client, w)

    response = client.post(url(booking, "/decline"), json={"reason": "Fully booked that week"})
    assert response.status_code == 200, response.text
    assert (response.json()["effectiveState"], response.json()["declineReason"]) == (
        "declined",
        "Fully booked that week",
    )
    assert {(r, t) for r, t, _ in outbox(sm)} == {(w.student, "booking_declined")}
    bare = client.post(url(without_reason, "/decline"))  # the reason is optional, so is the body
    assert bare.status_code == 200, bare.text
    assert bare.json()["declineReason"] is None
    assert client.post(url(booking, "/accept"), json={"meetingLink": LINK}).status_code == 409


def test_t13_late_cancel_without_reason_422(
    sm: sessionmaker[Session], client: TestClient, w: World
) -> None:
    """Row 18, O30: inside 24 h of the start a tutor's cancel needs a non-blank reason."""
    late = add_booking(sm, w, state="accepted", starts_in=timedelta(hours=10))
    as_tutor(client, w)
    assert client.get(url(late)).json()["allowedActions"] == ["cancel_with_reason", "post_note"]

    for body in (None, {}, {"reason": None}, {"reason": ""}, {"reason": "   "}):
        refused = client.post(url(late, "/cancel"), json=body)
        assert refused.status_code == 422, (body, refused.text)
        assert code_of(refused) == "reason_required"
        assert refused.headers["cache-control"] == NO_STORE
    db = stored(sm, late)
    assert (db.state, db.cancelled_at, db.cancel_reason) == (BookingState.accepted, None, None)
    assert outbox(sm) == []
    assert inbox_rows(sm) == []

    # The control: more than 24 h ahead the same body-less cancel is allowed.
    early = add_booking(
        sm, w, state="accepted", starts_in=timedelta(hours=30), student=add_student(sm)
    )
    assert client.post(url(early, "/cancel")).status_code == 200


def test_t13_late_cancel_with_reason_200_reason_visible_to_student_and_parent(
    sm: sessionmaker[Session], client: TestClient, w: World
) -> None:
    """Tutor half: T13 stores the reason; the student's and the parent's ``BookingDTO`` carry it.

    The family half (S2, PA2 at the route) is T17's. Here the family's view is built by the same
    service read and DTO builder those routes use. The reason never travels in a notice or an
    email (SPEC §b.4 copy rules).
    """
    parent = add_parent(sm, w.student)
    booking = add_booking(sm, w, state="accepted", starts_in=timedelta(hours=10))
    as_tutor(client, w)

    response = client.post(url(booking, "/cancel"), json={"reason": f"  {REASON}  "})

    assert response.status_code == 200, response.text
    body = response.json()
    assert (
        body["effectiveState"],
        body["cancelReason"],
        body["cancelledBy"],
        body["cancelledLate"],
        body["allowedActions"],
    ) == ("cancelled", REASON, "tutor", True, [])
    db = stored(sm, booking)
    assert (db.cancelled_by_party, db.cancelled_by_user_id) == (BookingParty.tutor, w.tutor.user_id)

    service = BookingService(sm)
    now = datetime.now(UTC)
    for viewer in (
        Actor(user_id=w.student, party="student"),
        Actor(user_id=parent, party="parent", child_id=w.student),
    ):
        row = service.get_for_viewer(booking, viewer)
        assert row is not None
        family = build_booking_dto(row, viewer=viewer, now=now, student_shared=None)
        assert (family.cancelReason, family.cancelledBy, family.cancelledLate) == (
            REASON,
            "tutor",
            True,
        )

    notices = inbox_rows(sm)
    assert {user for user, *_ in notices} == {w.student, parent}
    assert all(
        body_text == "Sara M. cancelled your session. Open it to see why."
        for *_, body_text in notices
    )
    assert {(r, t) for r, t, _ in outbox(sm)} == {
        (w.student, "booking_cancelled"),
        (parent, "booking_cancelled"),
    }
    assert REASON not in repr(notices)


def test_t13_tutor_cancel_refusals(sm: sessionmaker[Session], client: TestClient, w: World) -> None:
    """A tutor declines a request, never cancels it; a started session is past cancelling."""
    request = add_booking(sm, w, state="requested", starts_in=timedelta(days=2))
    started = add_booking(sm, w, state="accepted", starts_in=-timedelta(minutes=10))
    as_tutor(client, w)
    for booking, code in ((request, "illegal_transition"), (started, "already_started")):
        refused = client.post(url(booking, "/cancel"), json={"reason": REASON})
        assert refused.status_code == 409, refused.text
        assert code_of(refused) == code
    assert stored(sm, request).state is BookingState.requested
    assert stored(sm, started).state is BookingState.accepted


# ---------------------------------------------------------------------------
# T14, T15: the tutor's outcome
# ---------------------------------------------------------------------------


def test_t14_t15_record_the_outcome_after_the_session(
    sm: sessionmaker[Session], client: TestClient, w: World
) -> None:
    held = add_booking(sm, w, state="accepted", starts_in=-timedelta(hours=3))
    missed = add_booking(
        sm, w, state="accepted", starts_in=-timedelta(hours=5), student=add_student(sm)
    )
    as_tutor(client, w)

    completed = client.post(url(held, "/complete"))
    assert completed.status_code == 200, completed.text
    assert (completed.json()["effectiveState"], completed.json()["completedBy"]) == (
        "completed",
        "tutor",
    )
    no_show = client.post(url(missed, "/no-show"))
    assert no_show.status_code == 200, no_show.text
    assert no_show.json()["effectiveState"] == "no_show"
    assert stored(sm, missed).no_show_marked_at is not None
    assert {(user, title) for user, _, title, _ in inbox_rows(sm)} == {
        (w.student, "Session completed"),
        (stored(sm, missed).student_id, "No-show recorded"),
    }
    assert outbox(sm) == []  # completed and no-show send no email (§b.4)
    refused = client.post(url(held, "/no-show"))
    assert (refused.status_code, code_of(refused)) == (409, "illegal_transition")


# ---------------------------------------------------------------------------
# T16, T17: notes
# ---------------------------------------------------------------------------


def test_t16_t17_notes_thread_oldest_first_with_cursor(
    sm: sessionmaker[Session], client: TestClient, w: World
) -> None:
    parent = add_parent(sm, w.student)
    booking = add_booking(sm, w, state="accepted", starts_in=timedelta(days=2))
    BookingService(sm).post_note(
        booking_id=booking, actor=Actor(user_id=w.student, party="student"), body="Hello"
    )
    as_tutor(client, w)

    posted = []
    for text in ("Bring the 2023 paper.", "  Chapter 4 first.  ", "See you then."):
        response = client.post(url(booking, "/notes"), json={"body": text})
        assert response.status_code == 201, response.text
        assert response.headers["cache-control"] == NO_STORE
        posted.append(response.json())
    assert [note["body"] for note in posted] == [
        "Bring the 2023 paper.",
        "Chapter 4 first.",
        "See you then.",
    ]
    assert {(n["authorParty"], n["authorName"], n["hidden"]) for n in posted} == {
        ("tutor", "Sara M.", False)
    }

    first = client.get(url(booking, "/notes"), params={"limit": 3})
    assert first.status_code == 200, first.text
    assert first.json()["canPost"] is True
    cursor = first.json()["nextCursor"]
    assert isinstance(cursor, str)
    rest = client.get(url(booking, "/notes"), params={"limit": 3, "cursor": cursor}).json()
    assert rest["nextCursor"] is None
    thread = first.json()["items"] + rest["items"]
    assert [note["body"] for note in thread] == [
        "Hello",
        "Bring the 2023 paper.",
        "Chapter 4 first.",
        "See you then.",
    ]
    assert thread[0]["authorParty"] == "student"
    bad = client.get(url(booking, "/notes"), params={"cursor": "not-a-cursor"})
    assert (bad.status_code, code_of(bad)) == (422, "invalid_cursor")

    # The student hears of each note; a linked parent once per tutor-zone day (SC-9). No text.
    notices = [(user, title, body) for user, _, title, body in inbox_rows(sm)]
    assert sum(user == w.student for user, *_ in notices) == 3
    assert sum(user == parent for user, *_ in notices) == 1
    assert not any("paper" in str(body) or "Chapter" in str(body) for *_, body in notices)
    assert w.tutor.user_id not in {user for user, *_ in notices}  # never told of their own notes


def test_free_text_fields_refuse_contact_details(
    sm: sessionmaker[Session], client: TestClient, w: World
) -> None:
    """SC-7 for every free-text field T11-T17 accept: place, decline and cancel reasons, notes."""
    request = add_booking(sm, w, state="requested", starts_in=timedelta(days=2))
    session = add_booking(sm, w, state="accepted", starts_in=timedelta(days=3))
    in_person = add_booking(
        sm,
        w,
        state="requested",
        starts_in=timedelta(days=4),
        mode="in_person",
        student=add_student(sm),
    )
    as_tutor(client, w)
    for path, body in (
        (url(request, "/decline"), {"reason": CONTACT_PHONE}),
        (url(session, "/cancel"), {"reason": "Email me at sara@example.com"}),
        (url(in_person, "/accept"), {"locationDetail": CONTACT_PHONE}),
        (url(session, "/notes"), {"body": "Join at https://example.com/room"}),
    ):
        refused = client.post(path, json=body)
        assert refused.status_code == 422, (path, refused.text)
        assert code_of(refused) == "contact_details_not_allowed"
    assert stored(sm, request).state is BookingState.requested
    assert stored(sm, session).state is BookingState.accepted
    assert stored(sm, in_person).state is BookingState.requested
    assert notes(sm, session) == []
    assert outbox(sm) == []


# ---------------------------------------------------------------------------
# D5.9 §1: the inbox comes after the commit and can never undo it
# ---------------------------------------------------------------------------


class _RaisingInbox:
    """A ``NotificationService`` whose inbox write always fails."""

    def create(self, *args: object, **kwargs: object) -> object:
        raise RuntimeError("inbox is down")


def test_writes_survive_a_raising_notification_service(sm: sessionmaker[Session], w: World) -> None:
    """T11 and T17 answer 2xx with a committed row when every inbox write raises."""
    parent = add_parent(sm, w.student)
    booking = add_booking(sm, w, state="requested", starts_in=timedelta(days=2))
    client = bookings_client(sm, notifications=_RaisingInbox())
    as_tutor(client, w)

    with structlog.testing.capture_logs() as logs:
        accepted = client.post(url(booking, "/accept"), json={"meetingLink": LINK})
        noted = client.post(url(booking, "/notes"), json={"body": "See you then."})

    assert accepted.status_code == 200, accepted.text
    assert noted.status_code == 201, noted.text
    assert stored(sm, booking).state is BookingState.accepted
    assert [note.body for note in notes(sm, booking)] == ["See you then."]
    assert {(r, t) for r, t, _ in outbox(sm)} == {
        (w.student, "booking_accepted"),
        (parent, "booking_accepted"),
    }
    failures = [entry for entry in logs if entry["event"] == "notification_create_failed"]
    assert len(failures) == 4  # accept: student + parent; note: student + parent (first today)
    assert inbox_rows(sm) == []
