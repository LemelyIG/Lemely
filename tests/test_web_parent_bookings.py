"""PA1-PA5: a parent's view of a linked child's sessions (SPEC §b.2 "Parent", §c.3 O7, O8).

Route-level, through ``tests.test_web_tutoring_booking.bookings_client``.

* Every route checks, on every call, that ``child_id`` is linked to the caller
  (``ParentLinkService.get_child``; O7): 403 ``not_linked`` for a child who exists but is not
  linked (the existing parent routes' split), 404 for no such user. Only then is the booking
  read, and only if it is that child's.
* PA1-PA3 are read-only: no review fields (SC-12), ``canPost`` always false (O9).
* PA4 and PA5 only for the parent who requested the booking (O8: 403 ``not_requester``); PA4
  never inside 24 hours of an accepted session's start (row 18). Once cancelled, the meeting
  place is ``null`` (O16), and a failing inbox leaves the cancel committed (D5.9 §1).
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
import structlog.testing

from lemely.db.models.enums import BookingState, ModerationState, Role
from lemely.db.models.tutoring import TutorReview
from tests.test_booking_repo import (
    LINK,
    PLACE,
    World,
    add_booking,
    add_parent,
    add_student,
    another_tutor,
    make_world,
    stored,
    unlink,
)
from tests.test_tutor_grant_repo import inbox_rows, outbox_rows
from tests.test_web_tutoring_booking import (
    NO_STORE,
    BrokenNotifications,
    bookings_client,
    detail_code,
)
from tests.tutoring_db import act_as, emptied_after, tutoring_database

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session, sessionmaker


def children(child: uuid.UUID | str) -> str:
    return f"/api/parent/children/{child}/bookings"


def one(child: uuid.UUID | str, booking: uuid.UUID | str) -> str:
    return f"{children(child)}/{booking}"


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
    return make_world(sm, display_name="Amelia")


def parent_booking(
    sm: sessionmaker[Session],
    w: World,
    parent: uuid.UUID,
    *,
    state: str = "requested",
    starts_in: timedelta = timedelta(days=3),
    fresh_tutor: bool = True,
    mode: str = "virtual",
) -> uuid.UUID:
    """A booking ``parent`` requested for ``w.student`` (with its own tutor by default)."""
    return add_booking(
        sm,
        w,
        state=state,
        starts_in=starts_in,
        mode=mode,
        requested_by=parent,
        party="parent",
        tutor=another_tutor(sm, w.subject) if fresh_tutor else None,
    )


# ---------------------------------------------------------------------------
# PA1, PA2, PA3
# ---------------------------------------------------------------------------


def test_pa1_lists_only_that_childs_bookings_with_its_own_cursor(
    sm: sessionmaker[Session], client: TestClient, w: World
) -> None:
    sibling = add_student(sm)
    parent = add_parent(sm, w.student, sibling)
    mine = [
        add_booking(sm, w, starts_in=timedelta(days=day), tutor=another_tutor(sm, w.subject))
        for day in (1, 2, 3)
    ]
    theirs = add_booking(sm, w, student=sibling, starts_in=timedelta(days=4))
    act_as(client, parent, Role.parent)

    first = client.get(children(w.student), params={"when": "upcoming", "limit": 2})

    assert first.status_code == 200, first.text
    assert first.headers["cache-control"] == NO_STORE
    page = first.json()
    assert [item["bookingId"] for item in page["items"]] == [str(b) for b in mine[:2]]
    assert all(item["review"] is None for item in page["items"])
    assert all(item["studentShared"] is None for item in page["items"])
    rest = client.get(
        children(w.student), params={"when": "upcoming", "limit": 2, "cursor": page["nextCursor"]}
    ).json()
    assert [item["bookingId"] for item in rest["items"]] == [str(mine[2])]
    assert rest["nextCursor"] is None
    sibling_page = client.get(children(sibling), params={"when": "upcoming"}).json()
    assert [item["bookingId"] for item in sibling_page["items"]] == [str(theirs)]
    assert client.get(children(w.student), params={"when": "past"}).json()["items"] == []

    # O21: neither the other ``when`` nor the student's own list accepts this cursor, and back.
    crossed = client.get(children(w.student), params={"when": "past", "cursor": page["nextCursor"]})
    assert crossed.status_code == 422
    assert detail_code(crossed) == "invalid_cursor"
    act_as(client, w.student, Role.student)
    student_cursor = client.get(
        "/api/student/bookings", params={"when": "upcoming", "limit": 1}
    ).json()["nextCursor"]
    assert (
        client.get(
            "/api/student/bookings", params={"when": "upcoming", "cursor": page["nextCursor"]}
        ).status_code
        == 422
    )
    act_as(client, parent, Role.parent)
    refused = client.get(children(w.student), params={"when": "upcoming", "cursor": student_cursor})
    assert refused.status_code == 422
    assert refused.headers["cache-control"] == NO_STORE


def test_pa_routes_403_not_linked_and_404_unknown_child(
    sm: sessionmaker[Session], client: TestClient, w: World
) -> None:
    booking = add_booking(sm, w, state="accepted", starts_in=timedelta(days=3))
    stranger = add_parent(sm)  # linked to nobody
    act_as(client, stranger, Role.parent)
    routes = [
        ("GET", lambda child: children(child), {"when": "upcoming"}),
        ("GET", lambda child: one(child, booking), None),
        ("GET", lambda child: f"{one(child, booking)}/notes", None),
        ("POST", lambda child: f"{one(child, booking)}/cancel", None),
        ("POST", lambda child: f"{one(child, booking)}/complete", None),
    ]
    for method, path, params in routes:
        not_linked = client.request(method, path(w.student), params=params)
        unknown = client.request(method, path(uuid.uuid4()), params=params)
        assert not_linked.status_code == 403, (method, path(w.student), not_linked.text)
        assert detail_code(not_linked) == "not_linked"
        assert unknown.status_code == 404, (method, path(w.student), unknown.text)
        assert detail_code(unknown) == "not_found"
        for response in (not_linked, unknown):
            assert response.headers["cache-control"] == NO_STORE
        assert client.request(method, path("not-a-uuid"), params=params).status_code == 422
    assert stored(sm, booking).state is BookingState.accepted
    assert len(routes) == 5  # non-vacuity: PA1-PA5


def test_pa2_reads_the_childs_booking_and_404s_a_siblings(
    sm: sessionmaker[Session], client: TestClient, w: World
) -> None:
    sibling = add_student(sm)
    parent = add_parent(sm, w.student, sibling)
    booking = add_booking(sm, w, state="accepted", starts_in=timedelta(days=2))
    act_as(client, parent, Role.parent)

    response = client.get(one(w.student, booking))

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == NO_STORE
    body = response.json()
    assert body["meetingLink"] == LINK  # after accept, linked parents see it (O16)
    assert body["allowedActions"] == []  # read-only: the student requested it
    via_sibling = client.get(one(sibling, booking))
    unknown = client.get(one(w.student, uuid.uuid4()))
    assert via_sibling.status_code == unknown.status_code == 404
    assert via_sibling.content == unknown.content


def test_idor_pa2_booking_review_null_for_parent_viewer(
    sm: sessionmaker[Session], client: TestClient, w: World
) -> None:
    """SC-12: the student's review of a booking reaches the student only."""
    parent = add_parent(sm, w.student)
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
    act_as(client, w.student, Role.student)
    as_student = client.get(f"/api/student/bookings/{booking}").json()
    act_as(client, parent, Role.parent)
    as_parent = client.get(one(w.student, booking)).json()

    # Red case: the same booking does carry a review, which the student's view shows.
    assert as_student["review"] is not None
    assert as_student["review"]["stars"] == 4
    assert as_student["reviewOpensAt"] is not None
    assert as_parent["review"] is None
    assert as_parent["reviewOpensAt"] is None
    assert as_parent["meetingLink"] == LINK
    assert "review" not in as_parent["allowedActions"]


def test_pa3_parent_reads_the_notes_and_never_posts(
    sm: sessionmaker[Session], client: TestClient, w: World
) -> None:
    parent = add_parent(sm, w.student)
    booking = add_booking(sm, w, state="accepted", starts_in=timedelta(days=2))
    act_as(client, w.student, Role.student)
    assert (
        client.post(
            f"/api/student/bookings/{booking}/notes", json={"body": "See you on Thursday"}
        ).status_code
        == 201
    )
    act_as(client, parent, Role.parent)

    response = client.get(f"{one(w.student, booking)}/notes")

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == NO_STORE
    page = response.json()
    assert [(item["authorParty"], item["body"]) for item in page["items"]] == [
        ("student", "See you on Thursday")
    ]
    assert page["canPost"] is False
    assert (
        client.post(f"{one(w.student, booking)}/notes", json={"body": "Hello"}).status_code == 405
    )


# ---------------------------------------------------------------------------
# PA4, PA5
# ---------------------------------------------------------------------------


def test_pa4_requester_cancels_and_everyone_else_is_told(
    sm: sessionmaker[Session], client: TestClient, w: World
) -> None:
    parent = add_parent(sm, w.student)
    other_parent = add_parent(sm, w.student)
    booking = parent_booking(sm, w, parent, fresh_tutor=False)
    act_as(client, parent, Role.parent)

    response = client.post(f"{one(w.student, booking)}/cancel", json={"reason": "Clash"})

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == NO_STORE
    body = response.json()
    assert (body["effectiveState"], body["cancelledBy"], body["cancelReason"]) == (
        "cancelled",
        "parent",
        "Clash",
    )
    assert sorted((user, kind) for user, kind, _, _ in inbox_rows(sm)) == sorted(
        [
            (w.tutor.user_id, "booking_update"),
            (w.student, "booking_update"),
            (other_parent, "booking_update"),
        ]
    )
    assert parent not in {user for user, _, _ in outbox_rows(sm)}


def test_pa4_commits_when_inbox_write_raises(sm: sessionmaker[Session]) -> None:
    """D5.9 §1 at the router: the cancel and its emails commit; the inbox failures are logged.

    SPEC §b.4 "Cancelled": every other party and the linked parents, never the parent who acted.
    """
    client = bookings_client(sm, notifications=BrokenNotifications())
    w = make_world(sm)
    parent = add_parent(sm, w.student)
    other_parent = add_parent(sm, w.student)
    booking = parent_booking(sm, w, parent, state="accepted", fresh_tutor=False)
    act_as(client, parent, Role.parent)

    with structlog.testing.capture_logs() as logs:
        response = client.post(f"{one(w.student, booking)}/cancel")

    assert response.status_code == 200, response.text
    assert stored(sm, booking).state is BookingState.cancelled
    told = sorted([w.tutor.user_id, w.student, other_parent])
    assert sorted(user for user, _, _ in outbox_rows(sm)) == told
    assert {template for _, template, _ in outbox_rows(sm)} == {"booking_cancelled"}
    failures = [entry for entry in logs if entry["event"] == "notification_create_failed"]
    assert sorted(entry["user_id"] for entry in failures) == sorted(str(user) for user in told)
    assert inbox_rows(sm) == []


def test_pa4_late_cancel_409_cancel_window_closed(
    sm: sessionmaker[Session], client: TestClient, w: World
) -> None:
    """Row 18: the requesting parent may not cancel an accepted session inside 24 hours."""
    parent = add_parent(sm, w.student)
    late = parent_booking(sm, w, parent, state="accepted", starts_in=timedelta(hours=10))
    act_as(client, parent, Role.parent)

    refused = client.post(f"{one(w.student, late)}/cancel", json={"reason": "Clash"})

    assert refused.status_code == 409, refused.text
    assert detail_code(refused) == "cancel_window_closed"
    assert refused.headers["cache-control"] == NO_STORE
    assert stored(sm, late).state is BookingState.accepted
    assert inbox_rows(sm) == []
    # Red case: a day further out the same parent may cancel.
    early = parent_booking(
        sm, w, parent, state="accepted", starts_in=timedelta(hours=30), mode="in_person"
    )
    assert client.get(one(w.student, early)).json()["locationDetail"] == PLACE  # accepted shows it
    allowed = client.post(f"{one(w.student, early)}/cancel")
    assert allowed.status_code == 200, allowed.text
    # O16: a cancelled session's place is null in the cancel's answer and in a later read,
    # though the row keeps it (only the DTO withholds it).
    for shown in (allowed.json(), client.get(one(w.student, early)).json()):
        assert (shown["meetingLink"], shown["locationDetail"]) == (None, None)
    assert stored(sm, early).location_detail == PLACE


def test_authz_parent_cancel_requires_requester(
    sm: sessionmaker[Session], client: TestClient, w: World
) -> None:
    """O8: a linked parent who did not request the booking only reads it."""
    requester = add_parent(sm, w.student)
    other = add_parent(sm, w.student)
    by_parent = parent_booking(sm, w, requester, state="accepted")
    by_student = add_booking(sm, w, starts_in=timedelta(days=4))

    act_as(client, other, Role.parent)
    as_other = client.post(f"{one(w.student, by_parent)}/cancel")
    act_as(client, requester, Role.parent)
    not_theirs = client.post(f"{one(w.student, by_student)}/cancel")

    for response in (as_other, not_theirs):
        assert response.status_code == 403, response.text
        assert detail_code(response) == "not_requester"
        assert response.headers["cache-control"] == NO_STORE
    assert stored(sm, by_parent).state is BookingState.accepted
    assert stored(sm, by_student).state is BookingState.requested
    assert inbox_rows(sm) == []
    # Red case: the requester may.
    assert client.post(f"{one(w.student, by_parent)}/cancel").status_code == 200


def test_authz_parent_actions_refused_after_unlink(
    sm: sessionmaker[Session], client: TestClient, w: World
) -> None:
    """O7: the link is checked on every call, so an unlinked parent loses every PA route."""
    parent = add_parent(sm, w.student)
    upcoming = parent_booking(sm, w, parent)
    ended = parent_booking(sm, w, parent, state="accepted", starts_in=-timedelta(hours=60))
    act_as(client, parent, Role.parent)
    calls = [
        ("GET", children(w.student), {"when": "upcoming"}),
        ("GET", one(w.student, upcoming), None),
        ("GET", f"{one(w.student, upcoming)}/notes", None),
        ("POST", f"{one(w.student, upcoming)}/cancel", None),
        ("POST", f"{one(w.student, ended)}/complete", None),
    ]
    # Red case: while linked, every read answers.
    for method, path, params in calls[:3]:
        assert client.request(method, path, params=params).status_code == 200, path

    unlink(sm, parent, w.student)

    for method, path, params in calls:
        response = client.request(method, path, params=params)
        assert response.status_code == 403, (method, path, response.text)
        assert detail_code(response) == "not_linked"
        assert response.headers["cache-control"] == NO_STORE
    assert stored(sm, upcoming).state is BookingState.requested
    assert stored(sm, ended).state is BookingState.accepted
    assert inbox_rows(sm) == []


def test_pa5_requesting_parent_completes_after_48h(
    sm: sessionmaker[Session], client: TestClient, w: World
) -> None:
    parent = add_parent(sm, w.student)
    early = parent_booking(sm, w, parent, state="accepted", starts_in=-timedelta(hours=48))
    late = add_booking(
        sm,
        w,
        state="accepted",
        starts_in=-timedelta(hours=50),
        requested_by=parent,
        party="parent",
        tutor=w.tutor,
    )
    act_as(client, parent, Role.parent)

    refused = client.post(f"{one(w.student, early)}/complete")
    claimed = client.post(f"{one(w.student, late)}/complete")

    assert refused.status_code == 409, refused.text
    assert detail_code(refused) == "outcome_claim_not_open"
    assert claimed.status_code == 200, claimed.text
    assert claimed.headers["cache-control"] == NO_STORE
    assert (claimed.json()["effectiveState"], claimed.json()["completedBy"]) == (
        "completed",
        "parent",
    )
    assert stored(sm, early).state is BookingState.accepted
    # The tutor and the student are told; the parent who acted is not.
    assert sorted((user, title) for user, _, title, _ in inbox_rows(sm)) == sorted(
        [(w.tutor.user_id, "Session completed"), (w.student, "Session completed")]
    )
