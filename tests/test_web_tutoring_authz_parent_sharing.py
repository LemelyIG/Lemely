"""Object-level rules for a parent's sharing views: O7 and O22 (SPEC §c.3), decision row 16 i.

* **O7.** ``child_id`` must be linked to the caller, checked on every call through
  ``ParentLinkService.get_child``: a user who exists but is not linked to the caller
  is 403 ``not_linked``; an id no user has is 404 (SPEC §b.2 PA6/PA7 "200, 403,
  404"; the split of ``routers/parent.py``).
* **O22.** PA6/PA7 return exactly the child's own grants and log, never another
  child's, and never write a ``tutor_access_audit`` row.
* The views are read-only: the student alone grants, revokes and sets the
  outcome-figure opt-out (rows 4 and 8; SPEC §a.5).

Each rule has a passing case beside its failing one. Apps come from
``tests.test_web_parent_tutor_access.sharing_client`` (``app_with_routers``).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa

from lemely.db.models.enums import Role
from lemely.db.tutoring_preferences_repo import TutoringPreferencesRepository
from tests.test_tutor_grant_repo import add_grant, add_student, audit_rows, link_parent
from tests.test_web_parent_tutor_access import pa6, pa7, sharing_client, tutor_reads
from tests.tutoring_db import (
    act_as,
    add_tutor,
    add_user,
    anonymous,
    emptied_after,
    tutoring_database,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session, sessionmaker

NO_STORE = "private, no-store"
NOT_LINKED = "not_linked"
NOT_FOUND = "not_found"
ROUTES = (pa6, pa7)


@pytest.fixture(scope="module")
def tutoring_db() -> Iterator[sessionmaker[Session]]:
    with tutoring_database() as factory:
        yield factory


@pytest.fixture
def sm(tutoring_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(tutoring_db)


@pytest.fixture
def client(sm: sessionmaker[Session]) -> Iterator[TestClient]:
    test_client = sharing_client(sm)
    yield test_client
    test_client.app.dependency_overrides.clear()  # type: ignore[attr-defined]


def unlink(sm: sessionmaker[Session], parent: uuid.UUID, child: uuid.UUID) -> None:
    with sm.begin() as session:
        session.execute(
            sa.text("DELETE FROM parent_child_links WHERE parent_id = :p AND child_id = :c"),
            {"p": parent, "c": child},
        )


def relink(sm: sessionmaker[Session], parent: uuid.UUID, child: uuid.UUID) -> None:
    with sm.begin() as session:
        session.execute(
            sa.text("INSERT INTO parent_child_links (parent_id, child_id) VALUES (:p, :c)"),
            {"p": parent, "c": child},
        )


# ---------------------------------------------------------------------------
# O22 (with O7's 403/404 split)
# ---------------------------------------------------------------------------


def test_authz_o22_other_child_403_unknown_404(
    sm: sessionmaker[Session], client: TestClient
) -> None:
    """A child not linked to the caller is 403 and shows nothing; an unknown id is 404."""
    tutor = add_tutor(sm)
    mine = add_student(sm, display_name="Amelia")
    theirs = add_student(sm, display_name="Nour")
    parent = link_parent(sm, mine)
    link_parent(sm, theirs)  # another family's parent
    add_grant(sm, mine, tutor)
    their_grant = add_grant(sm, theirs, tutor)
    tutor_reads(client, tutor, theirs)
    audit_before = audit_rows(sm)
    act_as(client, parent, Role.parent)

    cases = 0
    for route in ROUTES:
        own = client.get(route(mine))
        assert own.status_code == 200, (route, own.text)  # red case: the link opens the door
        other = client.get(route(theirs))
        assert other.status_code == 403, (route, other.text)
        assert other.json()["detail"]["code"] == NOT_LINKED
        assert str(their_grant) not in other.text
        assert "Sara M." not in other.text
        unknown = client.get(route(uuid.uuid4()))
        assert unknown.status_code == 404, route
        assert unknown.json()["detail"]["code"] == NOT_FOUND
        malformed = client.get(route("not-a-uuid"))
        assert malformed.status_code == 422, route
        for response in (own, other, unknown, malformed):
            assert response.headers["cache-control"] == NO_STORE
        cases += 4
    assert cases == 8  # non-vacuity: two routes, four children each
    assert audit_rows(sm) == audit_before


def test_authz_o22_each_child_sees_only_its_own_grants_and_log(
    sm: sessionmaker[Session], client: TestClient
) -> None:
    """Two children of one parent, each with their own tutor: no view mixes them."""
    first = add_student(sm, display_name="Amelia")
    second = add_student(sm, display_name="Karim")
    parent = link_parent(sm, first)
    relink(sm, parent, second)
    sara = add_tutor(sm)
    omar = add_tutor(sm, first_name="Omar", initial="K")
    grants = {first: add_grant(sm, first, sara), second: add_grant(sm, second, omar)}
    tutor_reads(client, sara, first)
    tutor_reads(client, omar, second)
    act_as(client, parent, Role.parent)

    for child, tutor, other_tutor in ((first, sara, omar), (second, omar, sara)):
        shown = client.get(pa6(child)).json()["items"]
        assert [item["grantId"] for item in shown] == [str(grants[child])]
        log = client.get(pa7(child)).json()["items"]
        assert len(log) == 2
        assert {entry["tutorId"] for entry in log} == {str(tutor.profile_id)}
        # The tutor filter cannot reach another child's rows either.
        crossed = client.get(pa7(child), params={"tutorId": str(other_tutor.profile_id)})
        assert crossed.json() == {"items": [], "nextCursor": None}


def test_authz_o7_link_checked_on_every_call(sm: sessionmaker[Session], client: TestClient) -> None:
    """O7: no cached "linked": the call after an unlink is refused, and after a relink served."""
    child = add_student(sm)
    parent = link_parent(sm, child)
    add_grant(sm, child, add_tutor(sm))
    act_as(client, parent, Role.parent)
    assert [client.get(route(child)).status_code for route in ROUTES] == [200, 200]

    unlink(sm, parent, child)
    refused = [client.get(route(child)) for route in ROUTES]
    assert [r.status_code for r in refused] == [403, 403]
    assert all(r.json()["detail"]["code"] == NOT_LINKED for r in refused)
    assert all(r.headers["cache-control"] == NO_STORE for r in refused)

    relink(sm, parent, child)
    assert [client.get(route(child)).status_code for route in ROUTES] == [200, 200]


# ---------------------------------------------------------------------------
# Guard and read-only
# ---------------------------------------------------------------------------


def test_authz_pa6_pa7_refused_for_every_other_role(
    sm: sessionmaker[Session], client: TestClient
) -> None:
    """The child, the tutor and both admins are stopped by the role guard, before the link."""
    tutor = add_tutor(sm)
    child = add_student(sm)
    link_parent(sm, child)
    add_grant(sm, child, tutor)
    callers = (
        (child, Role.student),
        (tutor.user_id, Role.teacher),
        (add_user(sm, Role.school_admin), Role.school_admin),
        (add_user(sm, Role.platform_admin), Role.platform_admin),
    )
    for user, role in callers:
        act_as(client, user, role)
        for route in ROUTES:
            response = client.get(route(child))
            assert response.status_code == 403, (role, route)
            # The guard's plain 403, not the link's ``{"code", "message"}``.
            assert not isinstance(response.json()["detail"], dict)
            assert response.headers["cache-control"] == NO_STORE


def test_authz_pa6_pa7_anonymous_is_401_no_store(
    sm: sessionmaker[Session], client: TestClient
) -> None:
    """No token: 401 ``private, no-store`` before the link check, whether the child exists or not.

    The answer does not depend on the child id, so it tells an anonymous caller nothing about
    who is linked to whom. Mutation: a plain ``APIRoute`` on the router turns this red (the 401
    loses ``no-store``).
    """
    child = add_student(sm)
    parent = link_parent(sm, child)
    tutor = add_tutor(sm)
    add_grant(sm, child, tutor)
    tutor_reads(client, tutor, child)
    audit_before = audit_rows(sm)
    act_as(client, parent, Role.parent)
    assert [client.get(route(child)).status_code for route in ROUTES] == [200, 200]  # red case
    anonymous(client)

    cases = 0
    for route in ROUTES:
        for target in (child, uuid.uuid4()):
            response = client.get(route(target))
            assert response.status_code == 401, (route, target)
            assert response.headers["cache-control"] == NO_STORE
            assert "Sara M." not in response.text
            cases += 1
    assert cases == 4  # non-vacuity: two routes, a linked and an unknown child each
    assert audit_rows(sm) == audit_before


def test_authz_parent_sharing_views_are_read_only(
    sm: sessionmaker[Session], client: TestClient
) -> None:
    """Row 4 and SPEC §a.5: a parent cannot grant, revoke or change the child's opt-out."""
    tutor = add_tutor(sm)
    child = add_student(sm)
    parent = link_parent(sm, child)
    grant = add_grant(sm, child, tutor)
    TutoringPreferencesRepository(sm).set_opt_out(child, value=True)
    act_as(client, parent, Role.parent)

    for route in ROUTES:
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            assert client.request(method, route(child)).status_code == 405, (method, route)
    attempts = (
        ("POST", "/api/student/tutor-grants", {"tutorId": str(tutor.profile_id)}),
        ("POST", f"/api/student/tutor-grants/{grant}/revoke", None),
        ("PUT", "/api/student/tutoring-settings", {"outcomeStatsOptOut": False}),
        ("GET", "/api/student/tutoring-settings", None),
    )
    for method, path, body in attempts:
        response = client.request(method, path, json=body)
        assert response.status_code == 403, (method, path)
        assert response.headers["cache-control"] == NO_STORE

    with sm() as session:
        live = session.execute(
            sa.text("SELECT count(*) FROM tutor_data_grants WHERE revoked_at IS NULL")
        ).scalar_one()
    assert live == 1
    assert TutoringPreferencesRepository(sm).get(child).outcome_stats_opt_out is True
    # Red case: the child can change it, through the same route.
    act_as(client, child, Role.student)
    put = client.put("/api/student/tutoring-settings", json={"outcomeStatsOptOut": False})
    assert put.status_code == 200
    assert TutoringPreferencesRepository(sm).get(child).outcome_stats_opt_out is False
