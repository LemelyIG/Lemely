"""A5 suspend and A12 close at the route (PLAN T21; SPEC §b.2 "Platform admin", §a.3, §b.4).

Route-level, through ``tests.test_tutoring_sweeps.safety_client``. The sweeps themselves are
proved in ``tests/test_tutoring_sweeps.py``; this file proves what the routes add: the codes
(200, 404, 409 ``illegal_transition`` / ``already_closed``, 422), the A2-shaped answer, the
after-commit notices (the tutor's listing notice and grant endings, the students' "can no longer
see your progress", the family's cancellations, never the note), D5.9 §1 and ``no-store``.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
import structlog.testing

from lemely.db.models.enums import BookingParty, BookingState, Role
from lemely.db.tutor_profile_repo import TutorProfileRepository
from tests.test_booking_repo import add_booking, add_parent, add_student, make_world, stored
from tests.test_tutor_grant_repo import add_grant
from tests.test_tutoring_sweeps import (
    add_class,
    classes_of,
    enrol,
    grant_state,
    safety_client,
)
from tests.test_web_tutoring_blocks import _RaisingInbox, inbox
from tests.tutoring_db import act_as, add_tutor, add_user, emptied_after, tutoring_database

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session, sessionmaker

NO_STORE = "private, no-store"
STATES = ("draft", "pending_review", "listed", "rejected", "suspended", "closed")


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


@pytest.fixture
def admin(sm: sessionmaker[Session], client: TestClient) -> uuid.UUID:
    admin_id = add_user(sm, Role.platform_admin)
    act_as(client, admin_id, Role.platform_admin)
    return admin_id


def sanction_url(tutor_id: uuid.UUID, action: str) -> str:
    return f"/api/admin/tutors/{tutor_id}/{action}"


# ---------------------------------------------------------------------------
# A5
# ---------------------------------------------------------------------------


def test_a5_suspends_and_sweeps_in_one_answer(
    sm: sessionmaker[Session], client: TestClient, admin: uuid.UUID
) -> None:
    w = make_world(sm)
    grant = add_grant(sm, w.student, w.tutor)
    upcoming = add_booking(sm, w, state="accepted", starts_in=timedelta(days=2))
    own = add_class(sm, w.tutor.user_id)
    enrol(sm, own, w.student)

    response = client.post(
        sanction_url(w.tutor.profile_id, "suspend"), json={"note": "Reported by two families."}
    )

    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == NO_STORE
    body = response.json()
    assert body["listingState"] == "suspended"
    assert body["tutorId"] == str(w.tutor.profile_id)
    assert [entry["decision"] for entry in body["history"]] == ["suspended"]
    assert body["history"][0]["note"] == "Reported by two families."
    assert all(item["signedUrl"] is None for item in body["evidence"])
    row = stored(sm, upcoming)
    assert row.state is BookingState.cancelled
    assert row.cancelled_by_party is BookingParty.platform_admin
    assert grant_state(sm, grant)[1] == "tutor_suspended"
    assert classes_of(sm, w.student) == set()
    view = TutorProfileRepository(sm).own_profile(w.tutor.profile_id)
    assert view is not None
    assert view.review_note == "Reported by two families."  # the tutor reads a suspension note


def test_a5_notices_after_commit(
    sm: sessionmaker[Session], client: TestClient, admin: uuid.UUID
) -> None:
    """SPEC §b.4: the tutor's listing notice and a generic end per grant; each student "can no
    longer see your progress"; each student and parent the cancellation. The tutor gets no
    notice per cancelled session (they are told the listing decision), and no copy carries the
    admin's note."""
    w = make_world(sm)
    parent = add_parent(sm, w.student)
    grant = add_grant(sm, w.student, w.tutor)
    upcoming = add_booking(sm, w, state="accepted", starts_in=timedelta(days=2))
    note = "Do not book this tutor again."

    response = client.post(sanction_url(w.tutor.profile_id, "suspend"), json={"note": note})
    assert response.status_code == 200, response.text

    tutor_inbox = inbox(sm, w.tutor.user_id)
    assert sorted(row[:3] for row in tutor_inbox) == sorted(
        [
            (
                "tutor_listing",
                "Your tutor profile is suspended",
                "Open your profile to see the note from Lemely.",
            ),
            (
                "tutor_access",
                "Progress sharing ended",
                "Access to progress you could see has ended.",
            ),
        ]
    )
    assert sorted(row[:3] for row in inbox(sm, w.student)) == sorted(
        [
            ("tutor_access", "Progress sharing ended", "Sara M. can no longer see your progress."),
            ("booking_update", "Session cancelled", "Your session with Sara M. was cancelled."),
        ]
    )
    assert inbox(sm, parent) == [
        (
            "booking_update",
            "Session cancelled",
            "Your session with Sara M. was cancelled.",
            f"booking:{upcoming}:cancelled",
        )
    ]
    keys = {row[3] for row in tutor_inbox}
    assert f"grant:{grant}:ended" in keys
    for user in (w.tutor.user_id, w.student, parent):
        assert all(note not in (row[2] or "") for row in inbox(sm, user))


@pytest.mark.parametrize("state", STATES)
def test_a5_transition_codes(
    sm: sessionmaker[Session], client: TestClient, admin: uuid.UUID, state: str
) -> None:
    tutor = add_tutor(sm, state=state)
    response = client.post(sanction_url(tutor.profile_id, "suspend"), json={})
    if state in {"listed", "pending_review", "rejected"}:
        assert response.status_code == 200, response.text
        assert response.json()["listingState"] == "suspended"
    else:
        assert response.status_code == 409, response.text
        assert response.json()["detail"]["code"] == "illegal_transition"
        assert inbox(sm, tutor.user_id) == []
    assert response.headers["Cache-Control"] == NO_STORE


# ---------------------------------------------------------------------------
# A12
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("state", STATES[:-1])
def test_a12_closes_from_every_open_state(
    sm: sessionmaker[Session], client: TestClient, admin: uuid.UUID, state: str
) -> None:
    tutor = add_tutor(sm, state=state)
    response = client.post(
        sanction_url(tutor.profile_id, "close"), json={"note": "Asked to leave."}
    )
    assert response.status_code == 200, response.text
    assert response.json()["listingState"] == "closed"
    assert response.headers["Cache-Control"] == NO_STORE
    assert [row[:3] for row in inbox(sm, tutor.user_id)] == [
        (
            "tutor_listing",
            "Your tutor profile is closed",
            "Your profile is no longer visible to students.",
        )
    ]
    view = TutorProfileRepository(sm).own_profile(tutor.profile_id)
    assert view is not None
    assert view.review_note != "Asked to leave."  # a close note is admin-internal (SPEC §a.2)


def test_a12_already_closed_409(
    sm: sessionmaker[Session], client: TestClient, admin: uuid.UUID
) -> None:
    tutor = add_tutor(sm)
    assert client.post(sanction_url(tutor.profile_id, "close"), json={}).status_code == 200
    again = client.post(sanction_url(tutor.profile_id, "close"), json={})
    assert again.status_code == 409, again.text
    assert again.json()["detail"]["code"] == "already_closed"
    assert again.headers["Cache-Control"] == NO_STORE
    assert len(inbox(sm, tutor.user_id)) == 1  # the refusal told nobody


def test_a12_close_sweeps_like_a_suspension(
    sm: sessionmaker[Session], client: TestClient, admin: uuid.UUID
) -> None:
    w = make_world(sm)
    grant = add_grant(sm, w.student, w.tutor)
    upcoming = add_booking(sm, w, state="requested", starts_in=timedelta(days=2))
    response = client.post(sanction_url(w.tutor.profile_id, "close"), json={})
    assert response.status_code == 200, response.text
    assert stored(sm, upcoming).cancelled_by_party is BookingParty.platform_admin
    assert grant_state(sm, grant)[1] == "tutor_closed"
    assert (
        "tutor_access",
        "Progress sharing ended",
        "Sara M. can no longer see your progress.",
    ) in [row[:3] for row in inbox(sm, w.student)]


# ---------------------------------------------------------------------------
# Both routes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("action", ["suspend", "close"])
def test_a5_a12_unknown_tutor_404(
    sm: sessionmaker[Session], client: TestClient, admin: uuid.UUID, action: str
) -> None:
    response = client.post(sanction_url(uuid.uuid4(), action), json={})
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "not_found"
    assert response.headers["Cache-Control"] == NO_STORE


@pytest.mark.parametrize("action", ["suspend", "close"])
def test_a5_a12_note_too_long_422_writes_nothing(
    sm: sessionmaker[Session], client: TestClient, admin: uuid.UUID, action: str
) -> None:
    w = make_world(sm)
    upcoming = add_booking(sm, w, state="accepted", starts_in=timedelta(days=2))
    response = client.post(sanction_url(w.tutor.profile_id, action), json={"note": "x" * 2001})
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "note_too_long"
    assert stored(sm, upcoming).state is BookingState.accepted
    assert inbox(sm, w.tutor.user_id) == []


@pytest.mark.parametrize("action", ["suspend", "close"])
@pytest.mark.parametrize("role", [Role.school_admin, Role.teacher, Role.student, Role.parent])
def test_a5_a12_are_platform_admin_only(
    sm: sessionmaker[Session], client: TestClient, action: str, role: Role
) -> None:
    tutor = add_tutor(sm)
    act_as(client, add_user(sm, role), role)
    response = client.post(sanction_url(tutor.profile_id, action), json={})
    assert response.status_code == 403
    assert response.headers["Cache-Control"] == NO_STORE
    assert inbox(sm, tutor.user_id) == []


@pytest.mark.parametrize("action", ["suspend", "close"])
def test_a5_a12_commit_when_the_inbox_write_raises(sm: sessionmaker[Session], action: str) -> None:
    """D5.9 §1: the sanction answers 200 with the sweep committed when every inbox write fails."""
    w = make_world(sm)
    other = add_student(sm, display_name="Karim Adel")
    grant = add_grant(sm, other, w.tutor)
    upcoming = add_booking(sm, w, state="accepted", starts_in=timedelta(days=2))
    client = safety_client(sm, notifications=_RaisingInbox())
    admin_id = add_user(sm, Role.platform_admin)
    act_as(client, admin_id, Role.platform_admin)

    with structlog.testing.capture_logs() as logs:
        response = client.post(sanction_url(w.tutor.profile_id, action), json={})

    assert response.status_code == 200, response.text
    assert stored(sm, upcoming).state is BookingState.cancelled
    assert grant_state(sm, grant)[0] is not None
    failures = [entry for entry in logs if entry["event"] == "notification_create_failed"]
    # listing (tutor), grant end (tutor, student), cancellation (student)
    assert len(failures) == 4
