"""SP5 and SP6: slots and booking requests for students and parents (SPEC §b.2, §a.3, §a.4b, §b.4).

Route-level, through :func:`bookings_client` (``app_with_routers``; a lane never edits
``lemely/web/app.py``). This module also holds what the other family booking test files
import: the client, the request body builder and the SPEC parsers.

* SP5 serves ``core.booking.bookable_slots`` for a window of ``from`` (a tutor-zone date from
  today) and ``days`` (1 to 28, default 14, ending no later than today + 28 days), minus the
  tutor's active bookings, behind a verified email.
* SP6 creates a request for the student themselves, or for a parent's linked child; every
  refusal code of SPEC §b.2's SP6 row is produced here, and the expected codes and statuses are
  parsed from that row, not written out by hand.
* O11 (SPEC §i.7): SP5 and SP6 answer SP2's own 404 body for an unknown, unlisted, paused,
  suspended, closed or blocked tutor (both block directions), so nobody learns a tutor blocked
  them.
* D5.9 §1: the inbox notices are written after the commit, and a raising notification service
  leaves the 201 and the committed row (with its outbox rows) in place.
* SPEC §e.3: S1 and PA1 read a page in two statements whatever its size (PA1 adds only the
  per-call link check, O7).
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import pytest
import sqlalchemy as sa
import structlog.testing
from fastapi.testclient import TestClient

from lemely.core.booking import bookable_slots
from lemely.db.booking_repo import BookingService
from lemely.db.class_repo import ClassService
from lemely.db.models import ParentChildLink
from lemely.db.models.enums import BookingState, Role
from lemely.db.models.tutoring import StudentTutoringPreferences, TutorBookingNote
from lemely.db.notification_prefs_repo import NotificationPreferencesService
from lemely.db.notification_repo import NotificationService
from lemely.db.parent_repo import ParentLinkService
from lemely.db.tutor_directory_repo import TutorDirectoryRepository
from lemely.db.tutor_profile_repo import TutorProfileRepository
from lemely.db.tutoring_preferences_repo import TutoringPreferencesRepository
from lemely.web.deps import (
    get_class_service,
    get_notification_service,
    get_parent_link_service,
    get_push_transport,
    get_user_mirror,
)
from lemely.web.deps_tutoring import get_tutor_directory_repo, get_tutor_profile_repo
from lemely.web.push import RecordingPushTransport
from lemely.web.routers import (
    parent_bookings,
    student_bookings,
    tutoring_booking,
    tutoring_directory,
)
from lemely.web.routers.student_bookings import get_tutoring_preferences_repo
from lemely.web.routers.tutoring_booking import get_booking_service
from tests.test_booking_repo import (
    ALL_WEEK,
    HOUR,
    MODES,
    RULES,
    ZONE,
    World,
    add_booking,
    add_parent,
    add_student,
    another_tutor,
    make_world,
    slot,
    stored,
)
from tests.test_tutor_grant_repo import inbox_rows, outbox_rows
from tests.tutoring_app import app_with_routers
from tests.tutoring_db import (
    DbMirror,
    SeededTutor,
    act_as,
    add_block,
    add_subject,
    add_tutor,
    add_user,
    count_statements,
    emptied_after,
    tutoring_database,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    import httpx
    from sqlalchemy.orm import Session, sessionmaker

NO_STORE = "private, no-store"
BOOKINGS = "/api/bookings"
SPEC = Path(__file__).resolve().parents[1] / "docs" / "tutoring" / "SPEC.md"


# ---------------------------------------------------------------------------
# Shared helpers (imported by the other family booking test files)
# ---------------------------------------------------------------------------


class BrokenNotifications:
    """A notification service whose every inbox write raises (D5.9 §1 proofs)."""

    def create(self, *args: object, **kwargs: object) -> object:
        raise RuntimeError("inbox is down")


def bookings_client(
    sm: sessionmaker[Session], *, notifications: object | None = None
) -> TestClient:
    """SP5, SP6, S1-S5, S14, S15, PA1-PA5 and SP2 on a fresh app wired to the test database.

    SP2 is mounted so the hidden-tutor 404s can be compared with the directory's own body (O11).
    ``notifications`` replaces the inbox service (a raising one proves D5.9 §1).
    """
    app = app_with_routers(
        tutoring_booking.router,
        student_bookings.router,
        parent_bookings.router,
        tutoring_directory.router,
    )
    inbox = (
        notifications
        if notifications is not None
        else NotificationService(sm, NotificationPreferencesService(sm))
    )
    push = RecordingPushTransport()
    app.dependency_overrides[get_booking_service] = lambda: BookingService(sm)
    app.dependency_overrides[get_tutoring_preferences_repo] = lambda: TutoringPreferencesRepository(
        sm
    )
    app.dependency_overrides[get_tutor_profile_repo] = lambda: TutorProfileRepository(sm)
    app.dependency_overrides[get_tutor_directory_repo] = lambda: TutorDirectoryRepository(sm)
    app.dependency_overrides[get_user_mirror] = lambda: DbMirror(sm)
    app.dependency_overrides[get_notification_service] = lambda: inbox
    app.dependency_overrides[get_push_transport] = lambda: push
    app.dependency_overrides[get_parent_link_service] = lambda: ParentLinkService(sm)
    app.dependency_overrides[get_class_service] = lambda: ClassService(sm)
    return TestClient(app)


def booking_body(
    w: World,
    *,
    starts_at: datetime | None = None,
    duration: int = 60,
    mode: str = "virtual",
    **fields: object,
) -> dict[str, object]:
    """An SP6 body for ``w``'s tutor and subject; ``fields`` adds or replaces camelCase keys."""
    body: dict[str, object] = {
        "tutorId": str(w.tutor.profile_id),
        "subjectCode": w.subject,
        "mode": mode,
        "startsAt": (starts_at or slot()).isoformat(),
        "durationMinutes": duration,
    }
    body.update(fields)
    return body


def zone_today() -> date:
    """Today in the tutors' zone, the calendar SP5's ``from`` is read in."""
    return datetime.now(UTC).astimezone(ZoneInfo(ZONE)).date()


def booking_count(sm: sessionmaker[Session]) -> int:
    with sm() as session:
        return int(session.execute(sa.text("SELECT count(*) FROM tutor_bookings")).scalar_one())


def note_count(sm: sessionmaker[Session]) -> int:
    with sm() as session:
        return int(session.scalar(sa.select(sa.func.count()).select_from(TutorBookingNote)) or 0)


def unverified(sm: sessionmaker[Session], role: Role) -> uuid.UUID:
    """A user with no verified email; a student one has read the safety notice."""
    user = add_user(sm, role, verified=False)
    if role is Role.student:
        with sm.begin() as session:
            session.add(
                StudentTutoringPreferences(
                    user_id=user, safety_notice_acknowledged_at=sa.func.now()
                )
            )
    return user


def detail_code(response: httpx.Response) -> str:
    detail = response.json()["detail"]
    assert isinstance(detail, dict), response.text
    return str(detail["code"])


def _spec_b2_row(route_id: str) -> str:
    section = SPEC.read_text(encoding="utf-8").split("### b.2 Routes", 1)[1].split("\n### ", 1)[0]
    [row] = [line for line in section.splitlines() if line.startswith(f"| {route_id} |")]
    return row


def spec_codes(route_id: str) -> dict[str, int]:
    """``{code: status}`` from the Codes cell of SPEC §b.2's ``route_id`` row.

    Each backticked snake_case code takes the nearest three-digit status before it, so
    ``409 `a`, `b`; 422 `c``` gives ``{a: 409, b: 409, c: 422}``; field names such as
    ``studentId`` are not codes.
    """
    cell = _spec_b2_row(route_id).rstrip().rstrip("|").rsplit("|", 1)[1]
    found: dict[str, int] = {}
    status: int | None = None
    for number, code in re.findall(r"\b(\d{3})\b|`([a-z_]+)`", cell):
        if number:
            status = int(number)
        elif status is not None:
            found[code] = status
    return found


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
# SP5
# ---------------------------------------------------------------------------


def test_sp5_slots_window_duration_and_bounds(
    sm: sessionmaker[Session], client: TestClient
) -> None:
    w = make_world(sm)
    parent = add_parent(sm, w.student)
    today = zone_today()
    path = f"/api/tutors/{w.tutor.profile_id}/slots"
    act_as(client, w.student, Role.student)

    before = datetime.now(UTC)
    response = client.get(path, params={"from": today.isoformat(), "durationMinutes": 60})
    after = datetime.now(UTC)

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == NO_STORE
    body = response.json()
    assert set(body) == {
        "tutorId",
        "zone",
        "zoneLabel",
        "durationMinutes",
        "windowStart",
        "windowEnd",
        "slots",
    }
    assert (body["tutorId"], body["zone"], body["zoneLabel"], body["durationMinutes"]) == (
        str(w.tutor.profile_id),
        ZONE,
        "Cairo time",
        60,
    )
    cairo = ZoneInfo(ZONE)
    # ``days`` defaults to 14: the window is 14 tutor-zone days from ``from``.
    assert datetime.fromisoformat(body["windowStart"]).astimezone(cairo).date() == today
    assert datetime.fromisoformat(body["windowEnd"]).astimezone(cairo).date() == today + timedelta(
        days=14
    )
    served = {datetime.fromisoformat(item["startsAt"]) for item in body["slots"]}
    assert all(
        datetime.fromisoformat(item["endsAt"]) - datetime.fromisoformat(item["startsAt"]) == HOUR
        for item in body["slots"]
    )

    def offered(now: datetime) -> set[datetime]:
        return {
            start
            for start, _ in bookable_slots(
                RULES, zone=ZONE, start=today, days=14, duration=HOUR, busy=(), now=now
            )
        }

    # The core's grid, independent of the route: what is offered at the end of the call is
    # served, and nothing is served that was not offered at its start.
    assert offered(after) <= served <= offered(before)
    assert len(served) > 500  # non-vacuity: two weeks of half-hour steps

    # A request holds its slot (and the half hours either side, for a one-hour session).
    held = slot(timedelta(days=2))
    assert client.post(BOOKINGS, json=booking_body(w, starts_at=held)).status_code == 201
    again = client.get(path, params={"from": today.isoformat(), "durationMinutes": 60}).json()
    starts = {datetime.fromisoformat(item["startsAt"]) for item in again["slots"]}
    for taken in (held - timedelta(minutes=30), held, held + timedelta(minutes=30)):
        assert taken not in starts
    assert held - HOUR in starts

    def code_of(params: dict[str, object]) -> tuple[int, str | None]:
        refused = client.get(path, params=params)
        assert refused.headers["cache-control"] == NO_STORE
        detail = refused.json().get("detail")
        return refused.status_code, detail.get("code") if isinstance(detail, dict) else None

    window = "invalid_window"
    assert code_of({"from": today.isoformat(), "days": 28, "durationMinutes": 60})[0] == 200
    assert code_of({"from": today.isoformat(), "days": 29, "durationMinutes": 60}) == (422, window)
    assert code_of({"from": today.isoformat(), "days": 0, "durationMinutes": 60}) == (422, window)
    yesterday = (today - timedelta(days=1)).isoformat()
    assert code_of({"from": yesterday, "days": 3, "durationMinutes": 60}) == (422, window)
    later = (today + timedelta(days=20)).isoformat()
    assert code_of({"from": later, "days": 9, "durationMinutes": 120}) == (422, window)
    assert code_of({"from": later, "days": 8, "durationMinutes": 120})[0] == 200
    assert code_of({"from": today.isoformat(), "durationMinutes": 50}) == (
        422,
        "invalid_duration",
    )
    for params in (
        {"durationMinutes": 60},
        {"from": today.isoformat()},
        {"from": "soon", "durationMinutes": 60},
        {"from": today.isoformat(), "durationMinutes": "an hour"},
    ):
        assert code_of(params)[0] == 422, params

    # A parent reads the same slots (row 10: parents browse and book for a linked child).
    act_as(client, parent, Role.parent)
    as_parent = client.get(path, params={"from": today.isoformat(), "durationMinutes": 60})
    assert as_parent.status_code == 200
    assert as_parent.json()["slots"] == again["slots"]


# ---------------------------------------------------------------------------
# SP6
# ---------------------------------------------------------------------------


def test_sp6_student_request_201_tells_tutor_and_parents_never_the_actor(
    sm: sessionmaker[Session], client: TestClient
) -> None:
    w = make_world(sm, display_name="Amelia")
    parent = add_parent(sm, w.student)
    act_as(client, w.student, Role.student)
    start = slot()

    response = client.post(
        BOOKINGS, json=booking_body(w, starts_at=start, firstNote="  Can we start with algebra?  ")
    )

    assert response.status_code == 201, response.text
    assert response.headers["cache-control"] == NO_STORE
    booking = response.json()
    assert booking["tutor"]["tutorId"] == str(w.tutor.profile_id)
    assert booking["student"] == {"studentId": str(w.student), "displayName": "Amelia"}
    assert (booking["requestedBy"], booking["effectiveState"], booking["mode"]) == (
        "student",
        "requested",
        "virtual",
    )
    assert datetime.fromisoformat(booking["startsAt"]) == start
    assert datetime.fromisoformat(booking["endsAt"]) == start + HOUR
    assert booking["allowedActions"] == ["cancel", "post_note"]
    assert (booking["meetingLink"], booking["review"], booking["studentShared"]) == (
        None,
        None,
        None,
    )
    assert str(w.tutor.user_id) not in response.text  # SC-19: never a tutor's users.id
    booking_id = uuid.UUID(booking["bookingId"])
    assert stored(sm, booking_id).state is BookingState.requested
    assert note_count(sm) == 1  # the first note, in the request's own transaction

    inbox = inbox_rows(sm)
    assert sorted((user, kind) for user, kind, _, _ in inbox) == sorted(
        [(w.tutor.user_id, "booking_request"), (parent, "booking_update")]
    )
    tutor_notice = next(row for row in inbox if row[0] == w.tutor.user_id)
    assert tutor_notice[2:] == ("New session request", "Amelia asked to book a session.")
    assert sorted((user, template) for user, template, _ in outbox_rows(sm)) == sorted(
        [(w.tutor.user_id, "booking_requested"), (parent, "booking_requested_family")]
    )


def test_sp6_parent_request_201_for_a_linked_child(
    sm: sessionmaker[Session], client: TestClient
) -> None:
    w = make_world(sm, acknowledged=False)  # a parent's request needs no safety notice (O26)
    parent = add_parent(sm, w.student)
    act_as(client, parent, Role.parent)

    response = client.post(BOOKINGS, json=booking_body(w, studentId=str(w.student)))

    assert response.status_code == 201, response.text
    booking = response.json()
    assert booking["requestedBy"] == "parent"
    assert booking["student"]["studentId"] == str(w.student)
    assert booking["allowedActions"] == ["cancel"]  # a parent never posts notes (O9)
    db = stored(sm, uuid.UUID(booking["bookingId"]))
    assert (db.student_id, db.requested_by_user_id) == (w.student, parent)
    assert sorted((user, kind) for user, kind, _, _ in inbox_rows(sm)) == sorted(
        [(w.tutor.user_id, "booking_request"), (w.student, "booking_update")]
    )


def test_sp6_every_code_in_spec_b2(sm: sessionmaker[Session], client: TestClient) -> None:
    """Each refusal of SPEC §b.2's SP6 row, produced through the route, with its status."""
    expected = spec_codes("SP6")
    assert len(expected) == 12  # non-vacuity: the codes the SP6 row names
    produced: dict[str, httpx.Response] = {}

    w = make_world(sm)
    act_as(client, w.student, Role.student)
    produced["not_self"] = client.post(
        BOOKINGS, json=booking_body(w, studentId=str(add_student(sm)))
    )
    produced["not_bookable"] = client.post(
        BOOKINGS, json=booking_body(w, subjectCode=add_subject(sm, name="Physics"))
    )
    beyond = (datetime.now(UTC) + timedelta(days=28, hours=2)).replace(
        minute=0, second=0, microsecond=0
    )
    produced["beyond_horizon"] = client.post(BOOKINGS, json=booking_body(w, starts_at=beyond))
    first = slot()
    assert client.post(BOOKINGS, json=booking_body(w, starts_at=first)).status_code == 201
    produced["already_pending"] = client.post(
        BOOKINGS, json=booking_body(w, starts_at=slot(timedelta(hours=60)))
    )
    produced["student_busy"] = client.post(
        BOOKINGS,
        json=booking_body(w, starts_at=first, tutorId=str(another_tutor(sm, w.subject).profile_id)),
    )
    rival = add_student(sm)
    act_as(client, rival, Role.student)
    produced["slot_taken"] = client.post(BOOKINGS, json=booking_body(w, starts_at=first))
    for index in range(5):
        add_booking(
            sm,
            w,
            student=rival,
            tutor=another_tutor(sm, w.subject),
            starts_in=timedelta(days=3 + index),
        )
    produced["pending_limit"] = client.post(
        BOOKINGS,
        json=booking_body(
            w,
            starts_at=slot(timedelta(days=12)),
            tutorId=str(another_tutor(sm, w.subject).profile_id),
        ),
    )

    stranger = add_parent(sm)
    act_as(client, stranger, Role.parent)
    produced["not_linked"] = client.post(BOOKINGS, json=booking_body(w, studentId=str(w.student)))
    parent = add_parent(sm, w.student)
    act_as(client, parent, Role.parent)
    produced["note_not_allowed_for_parent"] = client.post(
        BOOKINGS, json=booking_body(w, studentId=str(w.student), firstNote="Hello")
    )

    unacknowledged = make_world(sm, acknowledged=False)
    act_as(client, unacknowledged.student, Role.student)
    produced["safety_notice_required"] = client.post(BOOKINGS, json=booking_body(unacknowledged))

    fresh = make_world(sm)
    act_as(client, fresh.student, Role.student)
    produced["contact_details_not_allowed"] = client.post(
        BOOKINGS, json=booking_body(fresh, firstNote="Call me on 0100 123 4567")
    )

    busy = make_world(sm)
    for day in range(10):
        add_booking(sm, busy, state="cancelled", starts_in=timedelta(days=5 + day))
    act_as(client, busy.student, Role.student)
    produced["too_many_requests"] = client.post(BOOKINGS, json=booking_body(busy))

    assert set(produced) == set(expected)
    for code, response in produced.items():
        assert response.status_code == expected[code], (code, response.text)
        assert detail_code(response) == code
        assert response.headers["cache-control"] == NO_STORE
    # Nothing was written by any refusal: one request plus the 15 seeded rows.
    assert booking_count(sm) == 1 + 5 + 10

    # The 422 codes SPEC §i.7 adds to SP6.
    act_as(client, parent, Role.parent)
    extra = {
        "student_required": client.post(BOOKINGS, json=booking_body(w)),
        "invalid_starts_at": client.post(
            BOOKINGS, json=booking_body(w, studentId=str(w.student), startsAt="next Tuesday")
        ),
    }
    act_as(client, fresh.student, Role.student)
    naive = slot().replace(tzinfo=None).isoformat()
    extra["invalid_starts_at_naive"] = client.post(
        BOOKINGS, json=booking_body(fresh, startsAt=naive)
    )
    extra["text_too_long"] = client.post(BOOKINGS, json=booking_body(fresh, firstNote="x" * 2001))
    for name, response in extra.items():
        assert response.status_code == 422, (name, response.text)
        assert detail_code(response) == name.removesuffix("_naive")
        assert response.headers["cache-control"] == NO_STORE
    assert booking_count(sm) == 16


def test_sp6_body_is_validated(sm: sessionmaker[Session], client: TestClient) -> None:
    w = make_world(sm)
    act_as(client, w.student, Role.student)
    for body in (
        {},
        {**booking_body(w), "mode": "by_carrier_pigeon"},
        {**booking_body(w), "durationMinutes": "an hour"},
        {**booking_body(w), "price": 300},
    ):
        response = client.post(BOOKINGS, json=body)
        assert response.status_code == 422, body
        assert response.headers["cache-control"] == NO_STORE
    assert booking_count(sm) == 0


def test_sp5_sp6_refused_for_unlisted_paused_or_blocked_tutor(
    sm: sessionmaker[Session], client: TestClient
) -> None:
    """O11 (SPEC §i.7): every tutor the caller may not see is SP2's own 404, byte for byte.

    Each hidden tutor teaches the subject and is free all week, so only its visibility can
    refuse it. The expected body is whatever SP2 answers for the same id; a distinct answer
    would tell a student that a tutor exists but is hidden, or that the tutor blocked them.
    """
    subject = add_subject(sm)
    student = add_student(sm)
    parent = add_parent(sm, student)

    def tutor(state: str = "listed", *, paused: bool = False) -> World:
        made = add_tutor(
            sm, subjects=(subject,), modes=MODES, rules=ALL_WEEK, state=state, paused=paused
        )
        return World(tutor=made, subject=subject, student=student)

    hidden = {
        state: tutor(state)
        for state in ("draft", "pending_review", "rejected", "suspended", "closed")
    }
    hidden["paused"] = tutor(paused=True)
    hidden["blocked_by_student"] = tutor()
    add_block(sm, student, hidden["blocked_by_student"].tutor.user_id)
    hidden["blocked_by_tutor"] = tutor()
    add_block(sm, hidden["blocked_by_tutor"].tutor.user_id, student)
    unknown = World(
        tutor=SeededTutor(profile_id=uuid.uuid4(), user_id=uuid.uuid4()),
        subject=subject,
        student=student,
    )
    hidden["unknown"] = unknown
    today = zone_today().isoformat()

    act_as(client, student, Role.student)
    sp2 = {name: client.get(f"/api/tutors/{w.tutor.profile_id}") for name, w in hidden.items()}
    assert {name: r.status_code for name, r in sp2.items()} == dict.fromkeys(hidden, 404)
    assert len({r.content for r in sp2.values()}) == 1  # SP2 itself answers one body
    for name, w in hidden.items():
        slots = client.get(
            f"/api/tutors/{w.tutor.profile_id}/slots",
            params={"from": today, "durationMinutes": 60},
        )
        booked = client.post(BOOKINGS, json=booking_body(w))
        for response in (slots, booked):
            assert response.status_code == 404, (name, response.text)
            assert response.content == sp2[name].content, name
            assert response.headers["cache-control"] == NO_STORE
    malformed = client.post(BOOKINGS, json=booking_body(unknown, tutorId="not-a-uuid"))
    assert malformed.status_code == 404
    assert malformed.content == sp2["unknown"].content
    assert len(hidden) == 9  # non-vacuity: every hidden kind compared

    # A parent booking for a child in a block with the tutor, either direction: the same 404.
    act_as(client, parent, Role.parent)
    for name in ("blocked_by_student", "blocked_by_tutor"):
        refused = client.post(BOOKINGS, json=booking_body(hidden[name], studentId=str(student)))
        assert refused.status_code == 404, refused.text
        assert refused.content == sp2["unknown"].content
    assert booking_count(sm) == 0
    assert inbox_rows(sm) == []
    assert outbox_rows(sm) == []

    # Red case: a listed, unpaused, unblocked tutor is served and bookable.
    act_as(client, student, Role.student)
    visible = tutor()
    assert (
        client.get(
            f"/api/tutors/{visible.tutor.profile_id}/slots",
            params={"from": today, "durationMinutes": 60},
        ).status_code
        == 200
    )
    assert client.post(BOOKINGS, json=booking_body(visible)).status_code == 201


def test_authz_verified_email_required_for_booking_review_grant_submit(
    sm: sessionmaker[Session], client: TestClient
) -> None:
    """The booking half (SP5, SP6): a student or parent without a verified email gets 403."""
    w = make_world(sm)
    student = unverified(sm, Role.student)
    parent = unverified(sm, Role.parent)
    with sm.begin() as session:
        session.add(ParentChildLink(parent_id=parent, child_id=w.student))
    slots_path = f"/api/tutors/{w.tutor.profile_id}/slots"
    params = {"from": zone_today().isoformat(), "durationMinutes": 60}
    for caller, role, body in (
        (student, Role.student, booking_body(w)),
        (parent, Role.parent, booking_body(w, studentId=str(w.student))),
    ):
        act_as(client, caller, role)
        for response in (client.get(slots_path, params=params), client.post(BOOKINGS, json=body)):
            assert response.status_code == 403, (role, response.text)
            assert response.json()["detail"] == {"code": "email_unverified"}
            assert response.headers["cache-control"] == NO_STORE
    assert booking_count(sm) == 0
    # Red case: the verified student passes both.
    act_as(client, w.student, Role.student)
    assert client.get(slots_path, params=params).status_code == 200
    assert client.post(BOOKINGS, json=booking_body(w)).status_code == 201


def test_sp6_commits_when_inbox_write_raises(sm: sessionmaker[Session]) -> None:
    """D5.9 §1 at the router: notices are sent after the commit, and their failure is logged."""
    client = bookings_client(sm, notifications=BrokenNotifications())
    w = make_world(sm)
    parent = add_parent(sm, w.student)
    act_as(client, w.student, Role.student)

    with structlog.testing.capture_logs() as logs:
        response = client.post(BOOKINGS, json=booking_body(w))

    assert response.status_code == 201, response.text
    assert stored(sm, uuid.UUID(response.json()["bookingId"])).state is BookingState.requested
    assert sorted(template for _, template, _ in outbox_rows(sm)) == [
        "booking_requested",
        "booking_requested_family",
    ]
    failures = [entry for entry in logs if entry["event"] == "notification_create_failed"]
    assert sorted(entry["user_id"] for entry in failures) == sorted(
        [str(w.tutor.user_id), str(parent)]
    )
    assert inbox_rows(sm) == []


# ---------------------------------------------------------------------------
# Query budget (SPEC §e.3)
# ---------------------------------------------------------------------------


def test_query_budget_s1_pa1_two_statements(sm: sessionmaker[Session], client: TestClient) -> None:
    w = make_world(sm)
    parent = add_parent(sm, w.student)
    tutors = [w.tutor, *(another_tutor(sm, w.subject) for _ in range(2))]
    made = 0
    for size in (1, 6):
        while made < size:
            add_booking(
                sm,
                w,
                tutor=tutors[made % len(tutors)],
                state="accepted" if made % 2 else "requested",
                starts_in=timedelta(days=1 + made),
            )
            made += 1
        act_as(client, w.student, Role.student)
        with count_statements(sm) as seen:
            response = client.get("/api/student/bookings", params={"when": "upcoming"})
        assert response.status_code == 200, response.text
        assert len(response.json()["items"]) == size  # non-vacuity: the page has the rows
        assert len(seen) == 2, seen

        act_as(client, parent, Role.parent)
        with count_statements(sm) as seen:
            response = client.get(
                f"/api/parent/children/{w.student}/bookings", params={"when": "upcoming"}
            )
        assert response.status_code == 200, response.text
        assert len(response.json()["items"]) == size
        link_checks = [statement for statement in seen if "parent_child_links" in statement]
        assert len(link_checks) == 1, seen  # O7: the link, checked on this call
        assert len(seen) - len(link_checks) == 2, seen
