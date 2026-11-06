"""Object-level rules on the family booking routes (SPEC §c.3 O5-O9, O23, O26, O30; P30).

Route-level, through ``tests.test_web_tutoring_booking.bookings_client``. Each rule has a
passing case and a case that shows the check refusing (SPEC §c.3: "the check must be shown to
go red"):

* O5: a student's booking routes act only on the caller's own bookings (one 404 otherwise);
* O6: SP6's subject is the student themselves or a parent's linked child;
* O7: a parent route checks the link, then that the booking is that child's;
* O8: a parent completes (and cancels, ``test_web_parent_bookings``) only what they requested;
* O9: notes are posted only by the booking's student here; parents read only;
* O23: the outcome claim opens 48 hours after the end, with no tutor outcome recorded;
* O26: the safety notice gates a student's own request and note, never a parent's request;
* O30: inside 24 hours of an accepted session's start the family may not cancel it;
* S5 against the SPEC §a.3 notes table (parsed from the SPEC, every effective state);
* every route of the three family routers answers ``private, no-store`` on its success path,
  and each is a ``TutoringRoute``.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from lemely.db.models.enums import BookingState, Role
from lemely.web.routers import parent_bookings, student_bookings, tutoring_booking
from lemely.web.tutoring_http import TutoringRoute
from tests.test_booking_repo import (
    HOUR,
    add_booking,
    add_parent,
    add_student,
    another_tutor,
    make_world,
    set_listing,
    slot,
    stored,
)
from tests.test_tutor_grant_repo import inbox_rows
from tests.test_web_tutoring_booking import (
    BOOKINGS,
    NO_STORE,
    SPEC,
    booking_body,
    booking_count,
    bookings_client,
    detail_code,
    note_count,
    zone_today,
)
from tests.tutoring_app import flatten_routes
from tests.tutoring_db import act_as, add_block, emptied_after, tutoring_database

if TYPE_CHECKING:
    from collections.abc import Iterator

    import httpx
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session, sessionmaker

STUDENT = "/api/student/bookings"
FAMILY_ROUTERS = (tutoring_booking.router, student_bookings.router, parent_bookings.router)


def parent_path(child: uuid.UUID | str, booking: uuid.UUID | str = "") -> str:
    base = f"/api/parent/children/{child}/bookings"
    return f"{base}/{booking}" if booking else base


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


# ---------------------------------------------------------------------------
# O5
# ---------------------------------------------------------------------------


def test_o5_student_routes_act_only_on_the_callers_bookings(
    sm: sessionmaker[Session], client: TestClient
) -> None:
    caller = make_world(sm)
    owner = make_world(sm)
    upcoming = add_booking(sm, owner, state="accepted", starts_in=timedelta(days=3))
    ended = add_booking(
        sm,
        owner,
        state="accepted",
        starts_in=-timedelta(hours=60),
        tutor=another_tutor(sm, owner.subject),
    )
    act_as(client, caller.student, Role.student)
    calls: list[tuple[str, str, uuid.UUID, dict[str, object] | None]] = [
        ("GET", "", upcoming, None),
        ("POST", "/cancel", upcoming, {}),
        ("GET", "/notes", upcoming, None),
        ("POST", "/notes", upcoming, {"body": "Hello"}),
        ("POST", "/complete", ended, None),
    ]
    for method, suffix, booking, body in calls:
        theirs = client.request(method, f"{STUDENT}/{booking}{suffix}", json=body)
        unknown = client.request(method, f"{STUDENT}/{uuid.uuid4()}{suffix}", json=body)
        assert theirs.status_code == unknown.status_code == 404, (method, suffix, theirs.text)
        assert theirs.content == unknown.content, (method, suffix)
        assert theirs.headers["cache-control"] == NO_STORE
    assert stored(sm, upcoming).state is BookingState.accepted
    assert stored(sm, ended).state is BookingState.accepted
    assert note_count(sm) == 0
    assert inbox_rows(sm) == []
    # Red case: the owner reaches the same bookings.
    act_as(client, owner.student, Role.student)
    assert client.get(f"{STUDENT}/{upcoming}").status_code == 200
    assert client.post(f"{STUDENT}/{ended}/complete").status_code == 200


# ---------------------------------------------------------------------------
# O6
# ---------------------------------------------------------------------------


def test_o6_sp6_subject_is_the_student_or_a_linked_child(
    sm: sessionmaker[Session], client: TestClient
) -> None:
    w = make_world(sm)
    act_as(client, w.student, Role.student)
    for other in (str(add_student(sm)), "not-a-uuid"):
        refused = client.post(BOOKINGS, json=booking_body(w, studentId=other))
        assert refused.status_code == 403, refused.text
        assert detail_code(refused) == "not_self"

    stranger = add_parent(sm)
    act_as(client, stranger, Role.parent)
    # An unknown child is the route's own link check (the parent routes' "Child not found."),
    # answered before the service, whose own lookup would say "Student not found.".
    cases: list[tuple[dict[str, object], int, str, str | None]] = [
        ({"studentId": str(w.student)}, 403, "not_linked", None),
        ({"studentId": str(uuid.uuid4())}, 404, "not_found", "Child not found."),
        ({"studentId": "not-a-uuid"}, 404, "not_found", "Child not found."),
        ({}, 422, "student_required", None),
    ]
    for fields, status, code, message in cases:
        refused = client.post(BOOKINGS, json=booking_body(w, **fields))
        assert refused.status_code == status, (fields, refused.text)
        assert detail_code(refused) == code
        if message is not None:
            assert refused.json()["detail"]["message"] == message, fields
        assert refused.headers["cache-control"] == NO_STORE
    assert booking_count(sm) == 0

    # Red cases: the student's own id, and a linked parent naming the child.
    act_as(client, w.student, Role.student)
    own = client.post(BOOKINGS, json=booking_body(w, studentId=str(w.student)))
    assert own.status_code == 201, own.text
    parent = add_parent(sm, w.student)
    act_as(client, parent, Role.parent)
    linked = client.post(
        BOOKINGS,
        json=booking_body(
            w,
            starts_at=slot(timedelta(hours=60)),
            studentId=str(w.student),
            tutorId=str(another_tutor(sm, w.subject).profile_id),
        ),
    )
    assert linked.status_code == 201, linked.text
    assert linked.json()["student"]["studentId"] == str(w.student)


# ---------------------------------------------------------------------------
# O7, O8
# ---------------------------------------------------------------------------


def test_o7_parent_routes_check_the_link_then_the_childs_booking(
    sm: sessionmaker[Session], client: TestClient
) -> None:
    w = make_world(sm)
    sibling = add_student(sm)
    parent = add_parent(sm, w.student)  # linked to w.student only
    childs = add_booking(sm, w, starts_in=timedelta(days=2))
    siblings = add_booking(
        sm, w, student=sibling, starts_in=timedelta(days=3), tutor=another_tutor(sm, w.subject)
    )
    act_as(client, parent, Role.parent)

    assert client.get(parent_path(w.student, childs)).status_code == 200  # red case
    via_child = client.get(parent_path(w.student, siblings))
    unknown_booking = client.get(parent_path(w.student, uuid.uuid4()))
    assert via_child.status_code == unknown_booking.status_code == 404
    assert via_child.content == unknown_booking.content
    via_sibling = client.get(parent_path(sibling, siblings))
    assert via_sibling.status_code == 403
    assert detail_code(via_sibling) == "not_linked"
    assert client.get(parent_path(uuid.uuid4(), childs)).status_code == 404
    listed = client.get(parent_path(w.student), params={"when": "upcoming"}).json()
    assert [item["bookingId"] for item in listed["items"]] == [str(childs)]


def test_o8_parent_completes_only_what_they_requested(
    sm: sessionmaker[Session], client: TestClient
) -> None:
    w = make_world(sm)
    requester = add_parent(sm, w.student)
    other = add_parent(sm, w.student)
    by_parent = add_booking(
        sm,
        w,
        state="accepted",
        starts_in=-timedelta(hours=60),
        requested_by=requester,
        party="parent",
    )
    by_student = add_booking(
        sm,
        w,
        state="accepted",
        starts_in=-timedelta(hours=70),
        tutor=another_tutor(sm, w.subject),
    )
    act_as(client, other, Role.parent)
    as_other = client.post(f"{parent_path(w.student, by_parent)}/complete")
    act_as(client, requester, Role.parent)
    not_theirs = client.post(f"{parent_path(w.student, by_student)}/complete")
    for response in (as_other, not_theirs):
        assert response.status_code == 403, response.text
        assert detail_code(response) == "not_requester"
    assert stored(sm, by_parent).state is BookingState.accepted
    assert stored(sm, by_student).state is BookingState.accepted
    # Red case: the requester may.
    assert client.post(f"{parent_path(w.student, by_parent)}/complete").status_code == 200


# ---------------------------------------------------------------------------
# O9
# ---------------------------------------------------------------------------


def test_o9_notes_are_posted_by_the_bookings_student_and_parents_only_read(
    sm: sessionmaker[Session], client: TestClient
) -> None:
    w = make_world(sm)
    parent = add_parent(sm, w.student)
    booking = add_booking(sm, w, state="accepted", starts_in=timedelta(days=2))

    stranger = make_world(sm)
    act_as(client, stranger.student, Role.student)
    assert client.post(f"{STUDENT}/{booking}/notes", json={"body": "Hi"}).status_code == 404
    act_as(client, parent, Role.parent)
    assert (
        client.post(f"{parent_path(w.student, booking)}/notes", json={"body": "Hi"}).status_code
        == 405
    )
    assert client.get(f"{parent_path(w.student, booking)}/notes").json()["canPost"] is False
    assert note_count(sm) == 0
    # Red case: the booking's own student posts.
    act_as(client, w.student, Role.student)
    assert client.post(f"{STUDENT}/{booking}/notes", json={"body": "Hi"}).status_code == 201
    assert client.get(f"{STUDENT}/{booking}/notes").json()["canPost"] is True


# ---------------------------------------------------------------------------
# O23
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("claimant", ["student", "parent"])
def test_o23_claim_only_48h_after_the_end_with_no_tutor_outcome(
    sm: sessionmaker[Session], client: TestClient, claimant: str
) -> None:
    w = make_world(sm)
    parent = add_parent(sm, w.student)
    requested_by = parent if claimant == "parent" else None
    cases = [
        ("requested", timedelta(days=2)),
        ("accepted", timedelta(days=3)),
        ("accepted", -timedelta(hours=48)),  # ended 47 hours ago
        ("no_show", -timedelta(hours=60)),  # the tutor recorded an outcome
    ]
    refused_ids = [
        add_booking(
            sm,
            w,
            state=state,
            starts_in=starts_in,
            tutor=another_tutor(sm, w.subject),
            requested_by=requested_by,
            party=claimant,
        )
        for state, starts_in in cases
    ]
    open_claim = add_booking(
        sm,
        w,
        state="accepted",
        starts_in=-timedelta(hours=50),
        requested_by=requested_by,
        party=claimant,
    )
    act_as(client, parent if claimant == "parent" else w.student, Role(claimant))

    def path(booking: uuid.UUID) -> str:
        if claimant == "parent":
            return f"{parent_path(w.student, booking)}/complete"
        return f"{STUDENT}/{booking}/complete"

    for booking, case in zip(refused_ids, cases, strict=True):
        response = client.post(path(booking))
        assert response.status_code == 409, (case, response.text)
        assert detail_code(response) == "outcome_claim_not_open", case
        assert stored(sm, booking).completed_at is None
    claimed = client.post(path(open_claim))
    assert claimed.status_code == 200, claimed.text
    assert claimed.json()["completedBy"] == claimant


# ---------------------------------------------------------------------------
# O26
# ---------------------------------------------------------------------------


def test_o26_safety_notice_gates_the_students_request_and_note_not_a_parents_request(
    sm: sessionmaker[Session], client: TestClient
) -> None:
    w = make_world(sm, acknowledged=False)
    parent = add_parent(sm, w.student)

    act_as(client, w.student, Role.student)
    own = client.post(BOOKINGS, json=booking_body(w))
    assert own.status_code == 409
    assert detail_code(own) == "safety_notice_required"

    act_as(client, parent, Role.parent)
    by_parent = client.post(BOOKINGS, json=booking_body(w, studentId=str(w.student)))
    assert by_parent.status_code == 201, by_parent.text

    act_as(client, w.student, Role.student)
    note_path = f"{STUDENT}/{by_parent.json()['bookingId']}/notes"
    refused = client.post(note_path, json={"body": "Hello"})
    assert refused.status_code == 409
    assert detail_code(refused) == "safety_notice_required"
    assert note_count(sm) == 0
    # Red case: once the student has read the notice (S15), the note goes through.
    assert client.post("/api/student/tutoring-safety-notice").status_code == 200
    assert client.post(note_path, json={"body": "Hello"}).status_code == 201


# ---------------------------------------------------------------------------
# O30 (family side)
# ---------------------------------------------------------------------------


def test_o30_family_cannot_cancel_an_accepted_session_inside_24h(
    sm: sessionmaker[Session], client: TestClient
) -> None:
    w = make_world(sm)
    parent = add_parent(sm, w.student)

    def booked(starts_in: timedelta, *, by_parent: bool) -> uuid.UUID:
        return add_booking(
            sm,
            w,
            state="accepted",
            starts_in=starts_in,
            tutor=another_tutor(sm, w.subject),
            requested_by=parent if by_parent else None,
            party="parent" if by_parent else "student",
        )

    # One child, so no two of these one-hour sessions may overlap.
    student_late = booked(timedelta(hours=20), by_parent=False)
    parent_late = booked(timedelta(hours=22, minutes=30), by_parent=True)
    student_early = booked(timedelta(hours=25, minutes=30), by_parent=False)
    parent_early = booked(timedelta(hours=28), by_parent=True)

    act_as(client, w.student, Role.student)
    late = client.post(f"{STUDENT}/{student_late}/cancel")
    early = client.post(f"{STUDENT}/{student_early}/cancel")
    act_as(client, parent, Role.parent)
    parent_refused = client.post(f"{parent_path(w.student, parent_late)}/cancel")
    parent_allowed = client.post(f"{parent_path(w.student, parent_early)}/cancel")

    for response in (late, parent_refused):
        assert response.status_code == 409, response.text
        assert detail_code(response) == "cancel_window_closed"
    for response in (early, parent_allowed):  # red cases: more than 24 hours ahead
        assert response.status_code == 200, response.text
    assert stored(sm, student_late).state is BookingState.accepted
    assert stored(sm, parent_late).state is BookingState.accepted


# ---------------------------------------------------------------------------
# S5 against the SPEC §a.3 notes table
# ---------------------------------------------------------------------------

_EFFECTIVE_STATES = frozenset(
    {
        "requested",
        "accepted",
        "awaiting_outcome",
        "completed",
        "no_show",
        "declined",
        "cancelled",
        "expired",
    }
)


def spec_notes_table() -> tuple[dict[str, str], str]:
    """``({effective state: "yes" | "grace" | "no"}, override rule)`` from SPEC §a.3 "Notes"."""
    text = SPEC.read_text(encoding="utf-8")
    table = text.split("**Notes**", 1)[1].split("\n\n", 2)[1]
    rules: dict[str, str] = {}
    override = ""
    for line in table.splitlines()[2:]:
        state_cell, rule_cell = (cell.strip() for cell in line.strip().strip("|").split("|"))
        rule = "grace" if rule_cell.startswith("until") else rule_cell
        if state_cell.startswith("any state"):
            override = rule
            continue
        # The states are the backticked names before any parenthesis ("`accepted` (before
        # `ends_at`)" names one state).
        for state in re.findall(r"`([a-z_]+)`", state_cell.split("(", 1)[0]):
            rules[state] = rule
    return rules, override


NOTE_CASES: list[tuple[str, str, timedelta, str]] = [
    # (case, stored state, start relative to now, effective state)
    ("live_request", "requested", timedelta(days=2), "requested"),
    ("accepted_upcoming", "accepted", timedelta(days=2), "accepted"),
    ("awaiting_in_grace", "accepted", -timedelta(days=2), "awaiting_outcome"),
    ("awaiting_after_grace", "accepted", -timedelta(days=8), "awaiting_outcome"),
    ("completed_in_grace", "completed", -timedelta(days=6), "completed"),
    ("completed_after_grace", "completed", -timedelta(days=8), "completed"),
    ("no_show", "no_show", -timedelta(days=1), "no_show"),
    ("declined", "declined", timedelta(days=2), "declined"),
    ("cancelled", "cancelled", timedelta(days=2), "cancelled"),
    ("expired", "expired", -timedelta(days=1), "expired"),
    ("stale_request", "requested", -timedelta(minutes=30), "expired"),
]
OVERRIDE_CASES = ("blocked_by_student", "blocked_by_tutor", "tutor_suspended", "frozen")


def _note_attempt(client: TestClient, booking: uuid.UUID) -> tuple[httpx.Response, bool]:
    response = client.post(f"{STUDENT}/{booking}/notes", json={"body": "Checking in"})
    can_post = client.get(f"{STUDENT}/{booking}/notes").json()["canPost"]
    return response, bool(can_post)


def test_authz_can_post_note_state_table_s5(sm: sessionmaker[Session], client: TestClient) -> None:
    rules, override = spec_notes_table()
    assert set(rules) == _EFFECTIVE_STATES  # non-vacuity: the table names all eight states
    assert {effective for *_, effective in NOTE_CASES} == _EFFECTIVE_STATES
    assert override == "no"
    outcomes: dict[str, bool] = {}
    for case, state, starts_in, effective in NOTE_CASES:
        w = make_world(sm)
        booking = add_booking(sm, w, state=state, starts_in=starts_in)
        rule = rules[effective]
        ends_at = datetime.now(UTC) + starts_in + HOUR
        expected = rule == "yes" or (
            rule == "grace" and datetime.now(UTC) < ends_at + timedelta(days=7)
        )
        act_as(client, w.student, Role.student)
        response, can_post = _note_attempt(client, booking)
        assert response.status_code == (201 if expected else 409), (case, response.text)
        if not expected:
            assert detail_code(response) == "notes_closed", case
        assert can_post is expected, case
        outcomes[case] = expected
    for case in OVERRIDE_CASES:
        w = make_world(sm)
        booking = add_booking(
            sm,
            w,
            state="accepted",
            starts_in=timedelta(days=2),
            notes_frozen_at=datetime.now(UTC) if case == "frozen" else None,
        )
        if case == "blocked_by_student":
            add_block(sm, w.student, w.tutor.user_id)
        elif case == "blocked_by_tutor":
            add_block(sm, w.tutor.user_id, w.student)
        elif case == "tutor_suspended":
            set_listing(sm, w.tutor, "suspended")
        act_as(client, w.student, Role.student)
        response, can_post = _note_attempt(client, booking)
        assert response.status_code == 409, (case, response.text)
        assert detail_code(response) == "notes_closed", case
        assert can_post is False, case
    # Non-vacuity both ways: the table allows some states and refuses others.
    assert set(outcomes.values()) == {True, False}


# ---------------------------------------------------------------------------
# P30: no-store on every family route's success path
# ---------------------------------------------------------------------------


def test_tutoring_private_routes_send_no_store(
    sm: sessionmaker[Session], client: TestClient
) -> None:
    routes = [route for router in FAMILY_ROUTERS for route in flatten_routes(router)]
    declared = {(method, route.path) for route in routes for method in route.methods}
    assert len(declared) == 14  # SP5, SP6, S1-S5, S14, S15, PA1-PA5
    assert all(isinstance(route, TutoringRoute) for route in routes)

    w = make_world(sm)
    parent = add_parent(sm, w.student)
    ended = add_booking(sm, w, state="accepted", starts_in=-timedelta(hours=50))
    by_parent = add_booking(
        sm,
        w,
        starts_in=timedelta(days=3),
        requested_by=parent,
        party="parent",
        tutor=another_tutor(sm, w.subject),
    )
    parent_ended = add_booking(
        sm,
        w,
        state="accepted",
        starts_in=-timedelta(hours=70),
        requested_by=parent,
        party="parent",
        tutor=another_tutor(sm, w.subject),
    )
    seen: dict[tuple[str, str], httpx.Response] = {}

    act_as(client, w.student, Role.student)
    seen[("GET", "/api/tutors/{tutor_id}/slots")] = client.get(
        f"/api/tutors/{w.tutor.profile_id}/slots",
        params={"from": zone_today().isoformat(), "durationMinutes": 60},
    )
    created = client.post(BOOKINGS, json=booking_body(w))
    seen[("POST", "/api/bookings")] = created
    booking = created.json()["bookingId"]
    seen[("GET", "/api/student/bookings")] = client.get(STUDENT, params={"when": "upcoming"})
    seen[("GET", "/api/student/bookings/{booking_id}")] = client.get(f"{STUDENT}/{booking}")
    seen[("POST", "/api/student/bookings/{booking_id}/notes")] = client.post(
        f"{STUDENT}/{booking}/notes", json={"body": "Hello"}
    )
    seen[("GET", "/api/student/bookings/{booking_id}/notes")] = client.get(
        f"{STUDENT}/{booking}/notes"
    )
    seen[("POST", "/api/student/bookings/{booking_id}/cancel")] = client.post(
        f"{STUDENT}/{booking}/cancel"
    )
    seen[("POST", "/api/student/bookings/{booking_id}/complete")] = client.post(
        f"{STUDENT}/{ended}/complete"
    )
    seen[("POST", "/api/student/tutoring-safety-notice")] = client.post(
        "/api/student/tutoring-safety-notice"
    )
    act_as(client, parent, Role.parent)
    template = "/api/parent/children/{child_id}/bookings"
    seen[("GET", template)] = client.get(parent_path(w.student), params={"when": "upcoming"})
    seen[("GET", f"{template}/{{booking_id}}")] = client.get(parent_path(w.student, by_parent))
    seen[("GET", f"{template}/{{booking_id}}/notes")] = client.get(
        f"{parent_path(w.student, by_parent)}/notes"
    )
    seen[("POST", f"{template}/{{booking_id}}/cancel")] = client.post(
        f"{parent_path(w.student, by_parent)}/cancel"
    )
    seen[("POST", f"{template}/{{booking_id}}/complete")] = client.post(
        f"{parent_path(w.student, parent_ended)}/complete"
    )

    assert set(seen) == declared  # every family route exercised, nothing else
    for route, response in seen.items():
        assert 200 <= response.status_code < 300, (route, response.text)
        assert response.headers["cache-control"] == NO_STORE, route
