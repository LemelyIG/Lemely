"""S12, S13: a student's own tutoring settings (SPEC §b.2 "Student", §a.2, SC-13d, row 8).

Route-level, through ``tests.tutoring_app.app_with_routers`` (a lane never edits
``lemely/web/app.py``), on a throwaway database.

* S12 reads the caller's settings. A student who never saved any reads the
  repository's defaults (counted in outcome figures, decision row 8), and the read
  writes nothing.
* S13 changes the outcome-figure opt-out through ``TutoringPreferencesRepository``:
  ``outcomePrefChangedAt`` moves only when the stored value changes, because that
  instant starts the 90-day hold on the tutor's figures (SC-13d) and saving the
  same choice again must not restart it. The safety-notice acknowledgement (S15's)
  is left alone.
* Both routes are ``STUDENT`` only and key on ``auth.user_id``: the body cannot name
  anyone, and a parent cannot read or change the child's choice (SPEC §a.5).
* Every response is ``private, no-store`` (``TutoringRoute``).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from lemely.db.models.enums import Role
from lemely.db.tutoring_preferences_repo import DEFAULT_PREFERENCES, TutoringPreferencesRepository
from lemely.web.deps import get_auth_context
from lemely.web.routers import student_tutoring_settings
from lemely.web.routers.student_tutoring_settings import get_tutoring_preferences_repo
from lemely.web.schemas_tutoring import TutoringSettingsDTO
from lemely.web.tutoring_http import TutoringRoute
from tests.tutoring_app import app_with_routers, flatten_routes
from tests.tutoring_db import act_as, add_user, anonymous, emptied_after, tutoring_database

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

NO_STORE = "private, no-store"
SETTINGS = "/api/student/tutoring-settings"


def settings_client(sm: sessionmaker[Session]) -> TestClient:
    """S12 and S13 on a fresh app, wired to the test database."""
    app = app_with_routers(student_tutoring_settings.router)
    app.dependency_overrides[get_tutoring_preferences_repo] = lambda: TutoringPreferencesRepository(
        sm
    )
    return TestClient(app)


def stored(sm: sessionmaker[Session], student: uuid.UUID) -> tuple[object, ...] | None:
    """The student's row as the database holds it, read without the repository."""
    with sm() as session:
        row = session.execute(
            sa.text(
                "SELECT outcome_stats_opt_out, outcome_pref_changed_at, "
                "safety_notice_acknowledged_at FROM student_tutoring_preferences "
                "WHERE user_id = :u"
            ),
            {"u": student},
        ).first()
    return tuple(row) if row is not None else None


def instant(value: object) -> datetime | None:
    """An API instant parsed back, or ``None``; a naive or offset-less string fails."""
    if value is None:
        return None
    assert isinstance(value, str)
    parsed = datetime.fromisoformat(value)
    assert parsed.tzinfo is not None, value
    return parsed


@pytest.fixture(scope="module")
def tutoring_db() -> Iterator[sessionmaker[Session]]:
    with tutoring_database() as factory:
        yield factory


@pytest.fixture
def sm(tutoring_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(tutoring_db)


@pytest.fixture
def client(sm: sessionmaker[Session]) -> Iterator[TestClient]:
    test_client = settings_client(sm)
    yield test_client
    test_client.app.dependency_overrides.clear()  # type: ignore[attr-defined]


@pytest.fixture
def student(sm: sessionmaker[Session], client: TestClient) -> uuid.UUID:
    student_id = add_user(sm, Role.student)
    act_as(client, student_id, Role.student)
    return student_id


# ---------------------------------------------------------------------------
# S12
# ---------------------------------------------------------------------------


def test_s12_defaults_when_never_saved_and_a_read_writes_nothing(
    sm: sessionmaker[Session], client: TestClient, student: uuid.UUID
) -> None:
    response = client.get(SETTINGS)

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == NO_STORE
    body = response.json()
    assert set(body) == set(TutoringSettingsDTO.model_fields)
    # The defaults are the repository's (decision row 8: counted unless opted out).
    assert body["outcomeStatsOptOut"] is DEFAULT_PREFERENCES.outcome_stats_opt_out
    assert body["outcomePrefChangedAt"] is DEFAULT_PREFERENCES.outcome_pref_changed_at
    assert body["safetyNoticeAcknowledgedAt"] is DEFAULT_PREFERENCES.safety_notice_acknowledged_at
    assert stored(sm, student) is None


def test_s12_reads_the_stored_row_including_the_safety_acknowledgement(
    sm: sessionmaker[Session], client: TestClient, student: uuid.UUID
) -> None:
    repo = TutoringPreferencesRepository(sm)
    repo.acknowledge_safety_notice(student)
    repo.set_opt_out(student, value=True)
    row = stored(sm, student)
    assert row is not None

    body = client.get(SETTINGS).json()

    assert body["outcomeStatsOptOut"] is True
    assert instant(body["outcomePrefChangedAt"]) == row[1]
    assert instant(body["safetyNoticeAcknowledgedAt"]) == row[2]


# ---------------------------------------------------------------------------
# S13
# ---------------------------------------------------------------------------


def test_opt_out_sets_changed_at_only_on_value_change(
    sm: sessionmaker[Session], client: TestClient, student: uuid.UUID
) -> None:
    """SC-13d: the change instant starts the 90-day hold, so only a real change moves it."""
    # Saving the default (counted) is not a change: the row appears, no hold starts.
    kept = client.put(SETTINGS, json={"outcomeStatsOptOut": False})
    assert kept.status_code == 200, kept.text
    assert kept.headers["cache-control"] == NO_STORE
    assert kept.json()["outcomeStatsOptOut"] is False
    assert kept.json()["outcomePrefChangedAt"] is None
    assert stored(sm, student) == (False, None, None)

    opted_out = client.put(SETTINGS, json={"outcomeStatsOptOut": True}).json()
    first_change = instant(opted_out["outcomePrefChangedAt"])
    assert opted_out["outcomeStatsOptOut"] is True
    assert first_change is not None
    assert stored(sm, student) == (True, first_change, None)

    repeated = client.put(SETTINGS, json={"outcomeStatsOptOut": True}).json()
    assert instant(repeated["outcomePrefChangedAt"]) == first_change
    assert stored(sm, student) == (True, first_change, None)

    opted_in = client.put(SETTINGS, json={"outcomeStatsOptOut": False}).json()
    second_change = instant(opted_in["outcomePrefChangedAt"])
    assert opted_in["outcomeStatsOptOut"] is False
    assert second_change is not None
    assert second_change > first_change
    assert stored(sm, student) == (False, second_change, None)

    read_back = client.get(SETTINGS)
    assert read_back.json() == opted_in
    assert read_back.headers["cache-control"] == NO_STORE


def test_s13_leaves_the_safety_acknowledgement_alone(
    sm: sessionmaker[Session], client: TestClient, student: uuid.UUID
) -> None:
    acknowledged = TutoringPreferencesRepository(sm).acknowledge_safety_notice(student)
    assert acknowledged.safety_notice_acknowledged_at is not None

    for value in (True, False):
        body = client.put(SETTINGS, json={"outcomeStatsOptOut": value}).json()
        assert instant(body["safetyNoticeAcknowledgedAt"]) == (
            acknowledged.safety_notice_acknowledged_at
        )
    row = stored(sm, student)
    assert row is not None
    assert row[2] == acknowledged.safety_notice_acknowledged_at


def test_s13_changes_the_callers_own_row_only(
    sm: sessionmaker[Session], client: TestClient, student: uuid.UUID
) -> None:
    other = add_user(sm, Role.student)

    assert client.put(SETTINGS, json={"outcomeStatsOptOut": True}).status_code == 200
    # The body cannot name another student (``extra="forbid"``).
    named = client.put(SETTINGS, json={"outcomeStatsOptOut": False, "studentId": str(other)})

    assert named.status_code == 422
    assert named.headers["cache-control"] == NO_STORE
    assert stored(sm, other) is None
    row = stored(sm, student)
    assert row is not None
    assert row[0] is True
    act_as(client, other, Role.student)
    assert client.get(SETTINGS).json()["outcomeStatsOptOut"] is False


def test_s13_body_is_validated(
    sm: sessionmaker[Session], client: TestClient, student: uuid.UUID
) -> None:
    bodies: list[object] = [
        {},
        {"outcomeStatsOptOut": None},
        {"outcomeStatsOptOut": "maybe"},
        {"outcomeStatsOptOut": [True]},
        {"outcomeStatsOptOut": True, "extra": 1},
        [True],
    ]
    for body in bodies:
        response = client.put(SETTINGS, json=body)
        assert response.status_code == 422, body
        assert response.headers["cache-control"] == NO_STORE
    missing = client.put(SETTINGS)
    assert missing.status_code == 422
    assert missing.headers["cache-control"] == NO_STORE
    assert stored(sm, student) is None


# ---------------------------------------------------------------------------
# Guard and route class
# ---------------------------------------------------------------------------


def test_s12_s13_refused_for_every_other_role_and_without_a_token(
    sm: sessionmaker[Session], client: TestClient
) -> None:
    child = add_user(sm, Role.student)
    TutoringPreferencesRepository(sm).set_opt_out(child, value=True)
    before = stored(sm, child)
    for role in (Role.parent, Role.teacher, Role.school_admin, Role.platform_admin):
        act_as(client, add_user(sm, role), role)
        read = client.get(SETTINGS)
        write = client.put(SETTINGS, json={"outcomeStatsOptOut": False})
        assert (read.status_code, write.status_code) == (403, 403), role
        assert read.headers["cache-control"] == write.headers["cache-control"] == NO_STORE
    client.app.dependency_overrides.pop(get_auth_context)  # type: ignore[attr-defined]
    anonymous = client.get(SETTINGS)
    assert anonymous.status_code == 401
    assert anonymous.headers["cache-control"] == NO_STORE
    assert stored(sm, child) == before


def test_s12_s13_anonymous_is_401_no_store_and_writes_nothing(
    sm: sessionmaker[Session], client: TestClient
) -> None:
    """No token: both routes answer 401 ``private, no-store``, and the PUT changes nothing.

    Mutation: a plain ``APIRoute`` on the settings router turns this red (the 401 loses
    ``no-store``).
    """
    child = add_user(sm, Role.student)
    TutoringPreferencesRepository(sm).set_opt_out(child, value=True)
    before = stored(sm, child)
    assert before is not None
    act_as(client, child, Role.student)
    assert client.get(SETTINGS).status_code == 200  # red case: with a token S12 answers
    assert client.put(SETTINGS, json={"outcomeStatsOptOut": True}).status_code == 200
    anonymous(client)

    cases = {
        "S12": client.get(SETTINGS),
        "S13": client.put(SETTINGS, json={"outcomeStatsOptOut": False}),
        "S13 no body": client.put(SETTINGS),
    }
    for name, response in cases.items():
        assert response.status_code == 401, name
        assert response.headers["cache-control"] == NO_STORE, name
    assert len(cases) == 3  # non-vacuity: three anonymous calls were made
    assert stored(sm, child) == before


def test_settings_router_has_s12_and_s13_on_the_tutoring_route_class() -> None:
    routes = flatten_routes(student_tutoring_settings.router)
    pairs = {(method, route.path) for route in routes for method in route.methods}
    assert pairs == {("GET", SETTINGS), ("PUT", SETTINGS)}
    assert len(routes) == 2  # non-vacuity: both routes were inspected
    assert all(type(route) is TutoringRoute for route in routes)
