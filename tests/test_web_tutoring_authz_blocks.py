"""Object-level authorisation of B1-B3 (PLAN T21; SPEC §a.4b, §b.2 "Safety", §c.2, THREAT-MODEL §7).

* ``test_authz_suspended_tutor_write_routes_409``, the B2 case: a suspended or closed tutor's
  block is refused with 409 ``tutor_suspended`` / ``tutor_closed`` and nothing is written, no
  block row, no cancellation, no revoke (CB-7). A student may still block that tutor.
* The guard ``STUDENT_OR_TEACHER``: parents and both admin roles get 403, an anonymous caller 401,
  on all three routes, before any handler runs. ``tests/test_authz_matrix_complete.py`` proves
  the same once the lead adds the rows (hot file); this file proves it for the lane.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

from lemely.db.models.enums import BookingState, Role
from tests.test_booking_repo import add_booking, make_world, set_listing, stored
from tests.test_tutor_grant_repo import add_grant
from tests.test_tutoring_sweeps import block_count, block_row, grant_state, safety_client
from tests.tutoring_db import act_as, add_user, anonymous, emptied_after, tutoring_database

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session, sessionmaker

B = "/api/tutoring/blocks"
NO_STORE = "private, no-store"


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


@pytest.mark.parametrize(
    ("state", "code"), [("suspended", "tutor_suspended"), ("closed", "tutor_closed")]
)
def test_authz_suspended_tutor_write_routes_409(
    sm: sessionmaker[Session], client: TestClient, state: str, code: str
) -> None:
    """The B2 case of THREAT-MODEL §7's parametrised test (T3-T7, T11-T15, T17, T18, B2)."""
    w = make_world(sm)
    upcoming = add_booking(sm, w, state="requested", starts_in=timedelta(days=2))
    grant = add_grant(sm, w.student, w.tutor)
    set_listing(sm, w.tutor, state)
    act_as(client, w.tutor.user_id, Role.teacher)

    response = client.post(B, json={"studentId": str(w.student)})

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == code
    assert response.headers["Cache-Control"] == NO_STORE
    assert block_count(sm) == 0
    assert stored(sm, upcoming).state is BookingState.requested
    assert grant_state(sm, grant) == (None, None)

    # The student, on the other side, may still block that tutor (a safety path).
    act_as(client, w.student, Role.student)
    assert client.post(B, json={"tutorId": str(w.tutor.profile_id)}).status_code == 201
    assert block_row(sm, w.student, w.tutor.user_id) is not None


ROUTES = (("GET", B), ("POST", B), ("DELETE", f"{B}/00000000-0000-4000-8000-000000000000"))


@pytest.mark.parametrize(("method", "path"), ROUTES)
@pytest.mark.parametrize("role", [Role.parent, Role.school_admin, Role.platform_admin])
def test_block_routes_refuse_roles_outside_student_or_teacher(
    sm: sessionmaker[Session], client: TestClient, method: str, path: str, role: Role
) -> None:
    act_as(client, add_user(sm, role), role)
    response = client.request(method, path, json={"tutorId": None} if method == "POST" else None)
    assert response.status_code == 403, (method, path, role, response.text)
    assert response.headers["Cache-Control"] == NO_STORE


@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_block_routes_refuse_an_anonymous_caller(
    client: TestClient, method: str, path: str
) -> None:
    anonymous(client)
    response = client.request(method, path, json={} if method == "POST" else None)
    assert response.status_code == 401, (method, path)
    assert response.headers["Cache-Control"] == NO_STORE
