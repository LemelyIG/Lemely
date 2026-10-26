"""Object-level rules on the tutor's booking routes T9-T17 (SPEC §c.3, §a.4b, PLAN T18).

* **O1 / (f):** a teacher without a tutor profile gets 404 ``no_tutor_profile`` on every route.
* **O4:** a tutor reads and acts only on bookings of their own profile; another tutor's booking
  is the same 404 as an unknown id (no existence oracle).
* **O9 (tutor side):** a tutor posts a note only while ``can_post_note`` holds, checked here
  over every effective state of SPEC §a.3's notes table, parsed from the SPEC text.
* **CB-7:** every write route (T11-T15, T17) refuses a suspended or closed profile with 409
  ``tutor_suspended`` / ``tutor_closed`` before any booking is read.
* **SC-9, SC-11, SC-12:** a tutor never reads the party ``parent`` or ``system`` and never sees
  the student's review.
* **SC-26:** every route answers ``Cache-Control: private, no-store``.

O30's tutor side (row 18) is ``tests/test_web_tutor_bookings.py::
test_t13_late_cancel_without_reason_422``. Apps come from that file's ``bookings_client``.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, get_args

import pytest

from lemely.db.booking_repo import SYSTEM_CANCEL_REASON, Actor, BookingService
from lemely.db.models.enums import BookingParty, BookingState, ModerationState, Role
from lemely.db.models.tutoring import TutorReview
from lemely.web.booking_view import build_booking_dto
from lemely.web.routers import tutor_bookings
from lemely.web.schemas_tutoring import EffectiveStateLit
from tests.test_booking_repo import (
    LINK,
    World,
    add_booking,
    add_parent,
    add_student,
    another_tutor,
    make_world,
    notes,
    outbox,
    set_listing,
    stored,
)
from tests.test_web_tutor_bookings import as_tutor, bookings_client, code_of, url
from tests.tutoring_app import flatten_routes
from tests.tutoring_db import act_as, add_block, add_user, emptied_after, tutoring_database

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi.testclient import TestClient
    from httpx import Response
    from sqlalchemy.orm import Session, sessionmaker

NO_STORE = "private, no-store"
SPEC = Path(__file__).resolve().parents[1] / "docs" / "tutoring" / "SPEC.md"
NOT_FOUND = {"detail": {"code": "not_found", "message": "Booking not found."}}


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
# The route set, read from SPEC §b.2 (non-vacuity for every sweep below)
# ---------------------------------------------------------------------------


def spec_routes() -> dict[str, tuple[str, str]]:
    """``{"T9": ("GET", "/api/tutor/bookings"), ...}``: SPEC §b.2 rows T9-T17."""
    found = re.findall(
        r"^\| (T(?:9|1[0-7])) \| `(GET|POST) (/api/tutor/bookings[^`\s]*)`",
        SPEC.read_text(encoding="utf-8"),
        flags=re.MULTILINE,
    )
    return {row: (method, path) for row, method, path in found}


def router_routes() -> set[tuple[str, str]]:
    return {
        (method, route.path)
        for route in flatten_routes(tutor_bookings.router)
        for method in route.methods
    }


def test_router_serves_exactly_spec_rows_t9_t17() -> None:
    rows = spec_routes()
    assert sorted(rows) == sorted(f"T{n}" for n in range(9, 18))  # nine rows parsed
    assert router_routes() == set(rows.values())


def _request(client: TestClient, method: str, path: str, booking: uuid.UUID) -> Response:
    """One call of ``(method, path)`` for ``booking``, with a body each route accepts."""
    target = path.replace("{booking_id}", str(booking))
    if method == "GET":
        params = {"when": "upcoming"} if path == "/api/tutor/bookings" else None
        return client.get(target, params=params)
    bodies: dict[str, object] = {
        "accept": {"meetingLink": LINK},
        "decline": {},
        "cancel": {"reason": "Unwell"},
        "notes": {"body": "See you then."},
    }
    return client.post(target, json=bodies.get(path.rsplit("/", 1)[-1]))


# ---------------------------------------------------------------------------
# O1 / (f) and SC-26
# ---------------------------------------------------------------------------


def test_t9_t17_404_no_tutor_profile(sm: sessionmaker[Session], client: TestClient) -> None:
    """ADR-T01 action 3: a teacher without a profile reads one 404 on all nine routes."""
    teacher = add_user(sm, Role.teacher)
    act_as(client, teacher, Role.teacher)
    checked = set()
    for method, path in spec_routes().values():
        response = _request(client, method, path, uuid.uuid4())
        assert response.status_code == 404, (method, path, response.text)
        assert code_of(response) == "no_tutor_profile", (method, path)
        assert response.headers["cache-control"] == NO_STORE
        checked.add((method, path))
    assert len(checked) == 9


def test_t9_t17_success_paths_send_no_store(
    sm: sessionmaker[Session], client: TestClient, w: World
) -> None:
    """SC-26 (a): each route's success response is ``private, no-store``."""

    def fresh(state: str, starts_in: timedelta) -> uuid.UUID:
        return add_booking(sm, w, state=state, starts_in=starts_in, student=add_student(sm))

    booking_for = {
        "T9": fresh("accepted", timedelta(days=2)),
        "T10": fresh("accepted", timedelta(days=3)),
        "T11": fresh("requested", timedelta(days=4)),
        "T12": fresh("requested", timedelta(days=5)),
        "T13": fresh("accepted", timedelta(days=6)),
        "T14": fresh("accepted", -timedelta(hours=3)),
        "T15": fresh("accepted", -timedelta(hours=5)),
        "T16": fresh("accepted", timedelta(days=7)),
        "T17": fresh("accepted", timedelta(days=8)),
    }
    as_tutor(client, w)
    rows = spec_routes()
    assert set(booking_for) == set(rows)
    for row, (method, path) in rows.items():
        response = _request(client, method, path, booking_for[row])
        assert response.status_code in (200, 201), (row, response.text)
        assert response.headers["cache-control"] == NO_STORE, row


# ---------------------------------------------------------------------------
# O4
# ---------------------------------------------------------------------------


def test_idor_tutor_routes_scoped_to_own_bookings(
    sm: sessionmaker[Session], client: TestClient, w: World
) -> None:
    """O4: another tutor's booking is the same 404 as an unknown id, on every route."""
    booking = add_booking(sm, w, state="requested", starts_in=timedelta(days=2))
    stranger = another_tutor(sm, w.subject)
    act_as(client, stranger.user_id, Role.teacher)

    for method, path in spec_routes().values():
        if path == "/api/tutor/bookings":
            listed = client.get(path, params={"when": "upcoming"})
            assert listed.status_code == 200
            assert listed.json()["items"] == []
            continue
        theirs = _request(client, method, path, booking)
        unknown = _request(client, method, path, uuid.uuid4())
        assert theirs.status_code == unknown.status_code == 404, (method, path)
        assert theirs.json() == unknown.json() == NOT_FOUND, (method, path)
    assert stored(sm, booking).state is BookingState.requested
    assert notes(sm, booking) == []

    as_tutor(client, w)  # the owner still sees and acts on it
    assert client.get(url(booking)).status_code == 200


# ---------------------------------------------------------------------------
# SC-9, SC-11, SC-12: what a tutor never reads
# ---------------------------------------------------------------------------


def test_idor_t10_booking_review_null_for_tutor_viewer(
    sm: sessionmaker[Session], client: TestClient, w: World
) -> None:
    """SC-12: the student's review of the booking is never in the tutor's ``BookingDTO``."""
    booking = add_booking(sm, w, state="completed", starts_in=-timedelta(days=9))
    with sm.begin() as session:
        session.add(
            TutorReview(
                booking_id=booking,
                tutor_profile_id=w.tutor.profile_id,
                student_id=w.student,
                stars=2,
                body=None,
                text_state=ModerationState.none,
            )
        )
    student = Actor(user_id=w.student, party="student")
    row = BookingService(sm).get_for_viewer(booking, student)
    assert row is not None
    seen_by_student = build_booking_dto(
        row, viewer=student, now=datetime.now(UTC), student_shared=None
    )
    assert seen_by_student.review is not None  # the red case: the review exists
    as_tutor(client, w)

    detail = client.get(url(booking)).json()
    listed = client.get("/api/tutor/bookings", params={"when": "past"}).json()["items"]
    for dto in (detail, *listed):
        assert (dto["review"], dto["reviewOpensAt"]) == (None, None)
        assert "review" not in dto["allowedActions"]
    assert str(seen_by_student.review.reviewId) not in str(detail)


def test_tutor_never_reads_the_parent_or_system_party(
    sm: sessionmaker[Session], client: TestClient, w: World
) -> None:
    """SC-9: no tutor DTO reveals a parent link; SC-11: a block's cancellation reads as Lemely's."""
    parent = add_parent(sm, w.student)
    by_parent = add_booking(
        sm, w, state="requested", starts_in=timedelta(days=2), requested_by=parent, party="parent"
    )
    swept = add_booking(
        sm,
        w,
        state="cancelled",
        starts_in=timedelta(days=3),
        cancelled_by_party=BookingParty.system,
        cancel_reason=SYSTEM_CANCEL_REASON,
    )
    as_tutor(client, w)

    request = client.get(url(by_parent)).json()
    assert request["requestedBy"] == "student"
    cancelled = client.get(url(swept)).json()
    assert (cancelled["cancelledBy"], cancelled["cancelReason"]) == ("platform_admin", "Cancelled")
    page = client.get("/api/tutor/bookings", params={"when": "past"}).text
    page += client.get("/api/tutor/bookings", params={"when": "upcoming"}).text
    for text in (str(request), str(cancelled), page):
        assert str(parent) not in text
        assert "parent" not in text
        assert "system" not in text
        assert SYSTEM_CANCEL_REASON not in text


# ---------------------------------------------------------------------------
# Accept guards (SPEC §a.3, §a.4b)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("blocker", ["student", "tutor"])
def test_authz_accept_refused_when_blocked(
    sm: sessionmaker[Session], client: TestClient, w: World, blocker: str
) -> None:
    booking = add_booking(sm, w, state="requested", starts_in=timedelta(days=2))
    pair = (w.student, w.tutor.user_id)
    add_block(sm, *(pair if blocker == "student" else pair[::-1]))
    as_tutor(client, w)

    assert "accept" not in client.get(url(booking)).json()["allowedActions"]
    refused = client.post(url(booking, "/accept"), json={"meetingLink": LINK})
    assert refused.status_code == 409, refused.text
    assert code_of(refused) == "access_ended"
    assert stored(sm, booking).state is BookingState.requested
    declined = client.post(url(booking, "/decline"), json={})
    assert declined.status_code == 200, declined.text  # a block withholds accept only


def test_authz_accept_refused_when_suspended(
    sm: sessionmaker[Session], client: TestClient, w: World
) -> None:
    booking = add_booking(sm, w, state="requested", starts_in=timedelta(days=2))
    set_listing(sm, w.tutor, "suspended")
    as_tutor(client, w)

    refused = client.post(url(booking, "/accept"), json={"meetingLink": LINK})
    assert refused.status_code == 409, refused.text
    assert code_of(refused) == "tutor_suspended"
    assert client.get(url(booking)).json()["allowedActions"] == []
    assert stored(sm, booking).state is BookingState.requested
    set_listing(sm, w.tutor, "listed")  # the red case: the same accept, once reinstated
    assert client.post(url(booking, "/accept"), json={"meetingLink": LINK}).status_code == 200


# ---------------------------------------------------------------------------
# CB-7: every write route refuses a suspended or closed profile
# ---------------------------------------------------------------------------

#: Per write route: a booking the action succeeds on while listed, and a body it accepts.
WRITE_CASES: dict[str, tuple[str, timedelta, object]] = {
    "accept": ("requested", timedelta(days=2), {"meetingLink": LINK}),
    "decline": ("requested", timedelta(days=2), {}),
    "cancel": ("accepted", timedelta(days=2), {"reason": "Unwell"}),
    "complete": ("accepted", -timedelta(hours=3), None),
    "no-show": ("accepted", -timedelta(hours=3), None),
    "notes": ("accepted", timedelta(days=2), {"body": "See you then."}),
}


def test_write_cases_cover_every_write_route() -> None:
    writes = {path.rsplit("/", 1)[-1] for method, path in router_routes() if method == "POST"}
    assert writes == set(WRITE_CASES)  # T11-T15 and T17: six routes


@pytest.mark.parametrize(
    ("listing", "code"), [("suspended", "tutor_suspended"), ("closed", "tutor_closed")]
)
@pytest.mark.parametrize("action", sorted(WRITE_CASES))
def test_authz_suspended_tutor_write_routes_409(
    sm: sessionmaker[Session],
    client: TestClient,
    w: World,
    action: str,
    listing: str,
    code: str,
) -> None:
    """CB-7: refused for the profile, before any booking is read (an unknown id answers 409 too)."""
    state, starts_in, body = WRITE_CASES[action]
    booking = add_booking(sm, w, state=state, starts_in=starts_in)
    set_listing(sm, w.tutor, listing)
    as_tutor(client, w)

    for target in (booking, uuid.uuid4()):
        refused = client.post(url(target, f"/{action}"), json=body)
        assert refused.status_code == 409, (target, refused.text)
        assert code_of(refused) == code
        assert refused.headers["cache-control"] == NO_STORE
    assert stored(sm, booking).state is BookingState(state)
    assert notes(sm, booking) == []
    assert outbox(sm) == []

    set_listing(sm, w.tutor, "listed")  # the red case: the same request succeeds when listed
    allowed = client.post(url(booking, f"/{action}"), json=body)
    assert allowed.status_code in (200, 201), allowed.text


def test_authz_suspended_tutor_cannot_post_note_on_completed_booking(
    sm: sessionmaker[Session], client: TestClient, w: World
) -> None:
    """A completed session's notes stay open seven days, but not to a suspended tutor (§a.3)."""
    booking = add_booking(sm, w, state="completed", starts_in=-timedelta(days=2))
    as_tutor(client, w)
    first = client.post(url(booking, "/notes"), json={"body": "Well done today."})
    assert first.status_code == 201, first.text  # the red case: allowed while listed

    set_listing(sm, w.tutor, "suspended")
    refused = client.post(url(booking, "/notes"), json={"body": "One more thing."})
    assert refused.status_code == 409, refused.text
    assert code_of(refused) == "tutor_suspended"
    assert client.get(url(booking, "/notes")).json()["canPost"] is False
    assert "post_note" not in client.get(url(booking)).json()["allowedActions"]
    assert [note.body for note in notes(sm, booking)] == ["Well done today."]


def test_authz_complete_requires_ends_at(
    sm: sessionmaker[Session], client: TestClient, w: World
) -> None:
    """T14/T15 before ``ends_at`` are 409 ``not_ended`` (SC-17, BK-8)."""
    running = add_booking(sm, w, state="accepted", starts_in=-timedelta(minutes=30))
    upcoming = add_booking(sm, w, state="accepted", starts_in=timedelta(days=2))
    ended = add_booking(sm, w, state="accepted", starts_in=-timedelta(hours=3))
    as_tutor(client, w)

    for booking in (running, upcoming):
        assert not {"complete", "no_show"} & set(client.get(url(booking)).json()["allowedActions"])
        for action in ("complete", "no-show"):
            refused = client.post(url(booking, f"/{action}"))
            assert refused.status_code == 409, (action, refused.text)
            assert code_of(refused) == "not_ended"
        assert stored(sm, booking).state is BookingState.accepted
    assert {"complete", "no_show"} <= set(client.get(url(ended)).json()["allowedActions"])
    done = client.post(url(ended, "/complete"))
    assert done.status_code == 200, done.text
    assert done.json()["effectiveState"] == "completed"


# ---------------------------------------------------------------------------
# O9 tutor side: the notes table of SPEC §a.3, over every effective state
# ---------------------------------------------------------------------------


def notes_table() -> dict[str, str]:
    """``{effective state: "yes" | "grace" | "no"}``, parsed from SPEC §a.3's notes table."""
    text = SPEC.read_text(encoding="utf-8")
    lines = text[text.index("**Notes** — `core.booking.can_post_note`") :].splitlines()[1:]
    table: dict[str, str] = {}
    for line in lines:
        if not line.startswith("|"):
            if table:
                break
            continue
        first, second = (cell.strip() for cell in line.strip().strip("|").split("|")[:2])
        if first in {"Effective state", "---"} or first.startswith("any state"):
            continue
        rule = {"yes": "yes", "no": "no"}.get(second)
        if second.startswith("until `ends_at + NOTE_POST_GRACE`"):
            rule = "grace"
        assert rule is not None, line
        # The states are the backticked names before any parenthesis: "`accepted` (before
        # `ends_at`)" names one state, not two.
        for state in re.findall(r"`([a-z_]+)`", first.split("(", 1)[0]):
            table[state] = rule
    return table


#: Stored rows that are in each effective state; ``starts_in`` with the default one-hour length.
_POSITIONS: dict[str, list[tuple[str, str, timedelta, bool | None]]] = {
    # (case id, stored state, starts_in, can post) - None: take the SPEC rule's yes/no.
    "requested": [("live", "requested", timedelta(days=2), None)],
    "accepted": [
        ("upcoming", "accepted", timedelta(days=2), None),
        ("in-progress", "accepted", -timedelta(minutes=30), None),
    ],
    "awaiting_outcome": [
        ("in-grace", "accepted", -timedelta(days=1, hours=1), True),
        ("past-grace", "accepted", -timedelta(days=8, hours=1), False),
    ],
    "completed": [
        ("in-grace", "completed", -timedelta(days=1, hours=1), True),
        ("past-grace", "completed", -timedelta(days=8, hours=1), False),
    ],
    "no_show": [("ended", "no_show", -timedelta(days=1, hours=1), None)],
    "declined": [("upcoming", "declined", timedelta(days=2), None)],
    "cancelled": [("upcoming", "cancelled", timedelta(days=2), None)],
    "expired": [
        ("stored", "expired", -timedelta(days=1), None),
        ("stale-request", "requested", -timedelta(minutes=30), None),
    ],
}


def _note_cases() -> list[tuple[str, str, timedelta, bool, str | None]]:
    """``(effective state, stored state, starts_in, can post, modifier)`` per case."""
    cases = []
    for state, rule in notes_table().items():
        for _, stored_state, starts_in, explicit in _POSITIONS[state]:
            if rule == "grace":
                assert explicit is not None
                can_post = explicit
            else:
                can_post = rule == "yes"
            cases.append((state, stored_state, starts_in, can_post, None))
    # The table's last row: any state is closed by a block either way or a safety freeze.
    for modifier in ("student-blocks", "tutor-blocks", "frozen"):
        cases.append(("accepted", "accepted", timedelta(days=2), False, modifier))
    return cases


def _case_id(case: tuple[str, str, timedelta, bool, str | None]) -> str:
    state, stored_state, starts_in, can_post, modifier = case
    return f"{state}-{stored_state}-{starts_in}-{can_post}-{modifier}"


def test_note_state_table_covers_every_effective_state() -> None:
    table = notes_table()
    assert set(table) == set(get_args(EffectiveStateLit))  # all eight effective states
    assert set(table.values()) == {"yes", "grace", "no"}
    cases = _note_cases()
    assert {case[3] for case in cases} == {True, False}
    assert len(cases) == 15  # 12 positions over the eight states, plus block x2 and freeze


@pytest.mark.parametrize("case", _note_cases(), ids=_case_id)
def test_authz_can_post_note_state_table(
    sm: sessionmaker[Session],
    client: TestClient,
    w: World,
    case: tuple[str, str, timedelta, bool, str | None],
) -> None:
    """T17 over every effective state: 201, or 409 ``notes_closed``; T10 and T16 agree."""
    state, stored_state, starts_in, can_post, modifier = case
    extra: dict[str, object] = {}
    if modifier == "frozen":
        extra["notes_frozen_at"] = datetime.now(UTC)
    booking = add_booking(sm, w, state=stored_state, starts_in=starts_in, **extra)
    if modifier == "student-blocks":
        add_block(sm, w.student, w.tutor.user_id)
    if modifier == "tutor-blocks":
        add_block(sm, w.tutor.user_id, w.student)
    as_tutor(client, w)

    detail = client.get(url(booking)).json()
    assert detail["effectiveState"] == state
    assert ("post_note" in detail["allowedActions"]) is can_post
    assert client.get(url(booking, "/notes")).json()["canPost"] is can_post
    response = client.post(url(booking, "/notes"), json={"body": "See you then."})
    if can_post:
        assert response.status_code == 201, response.text
    else:
        assert response.status_code == 409, response.text
        assert code_of(response) == "notes_closed"
    assert len(notes(sm, booking)) == (1 if can_post else 0)
    assert stored(sm, booking).state is BookingState(stored_state)
