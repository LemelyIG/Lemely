"""PA6, PA7: a linked parent's read-only view of the child's grants and tutor reads (SPEC §b.2).

Decision row 16 i: a linked parent sees who their child shares progress with and
who looked, read-only; the student alone grants and revokes (row 4). The expected
side of every comparison comes from the child's own routes (S8, S11, T14's), not
from literals written here, so PA6/PA7 are judged against an independent reader.

* PA6 is the child's S8 list with ``alsoTeachesClasses`` always empty (SPEC §b.3:
  that is the student's own information about their classes).
* PA7 is the child's S11 log, newest first, filterable by tutor, keyset-paged with
  its own cursor tag (O21); SPEC §e.3 budget: the link check plus one statement.
* Neither writes a ``tutor_access_audit`` row (that log records tutor reads only).
* The parent's durable record of a grant is PA6, not the notice (SPEC §b.4 point 4):
  every grant PA6 shows has an inbox notice to each linked parent, and a refused
  grant gives neither.
* Every response is ``private, no-store`` (``TutoringRoute``).

The object-level link rules (O7, O22) are in
``tests/test_web_tutoring_authz_parent_sharing.py``, which imports
:func:`sharing_client` from here.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from lemely.db.class_repo import ClassService
from lemely.db.models.enums import GrantRevokeReason, Role, TutorAccessAction
from lemely.db.models.tutoring import TutorAccessAudit
from lemely.db.models.users import ParentChildLink
from lemely.db.parent_repo import ParentLinkService
from lemely.db.tutor_grant_repo import GrantView, TutorGrantRepository
from lemely.db.tutoring_preferences_repo import TutoringPreferencesRepository
from lemely.web.deps import get_parent_link_service
from lemely.web.deps_tutoring import get_tutoring_areas
from lemely.web.routers import (
    parent_tutor_access,
    student_tutor_access,
    student_tutoring_settings,
    tutor_students,
    tutoring_directory,
)
from lemely.web.routers.student_tutor_access import get_tutor_grant_repo, grant_dto
from lemely.web.routers.student_tutoring_settings import get_tutoring_preferences_repo
from lemely.web.tutoring_http import TutoringRoute
from tests.test_tutor_grant_repo import (
    add_grant,
    add_student,
    audit_rows,
    grants_client,
    link_parent,
    outbox_rows,
)
from tests.tutoring_app import app_with_routers, flatten_routes
from tests.tutoring_db import (
    NOW,
    SeededTutor,
    act_as,
    add_tutor,
    count_statements,
    emptied_after,
    tutoring_database,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

NO_STORE = "private, no-store"
S8 = "/api/student/tutor-grants"
S11 = "/api/student/tutor-access-log"


def pa6(child: uuid.UUID | str) -> str:
    return f"/api/parent/children/{child}/tutor-grants"


def pa7(child: uuid.UUID | str) -> str:
    return f"/api/parent/children/{child}/tutor-access-log"


# ---------------------------------------------------------------------------
# Helpers (imported by the authz file)
# ---------------------------------------------------------------------------


def sharing_client(sm: sessionmaker[Session]) -> TestClient:
    """PA6, PA7, S12, S13 beside T14's S8-S11, T19, T20 and SP2, on the test database.

    The overrides are exactly ``grants_client``'s (so T19/T20 write real audit rows
    and S9 sends real notices), plus the parent-link service and the preferences
    repository these routers read.
    """
    base = grants_client(sm)
    app = app_with_routers(
        student_tutor_access.router,
        tutor_students.router,
        tutoring_directory.router,
        parent_tutor_access.router,
        student_tutoring_settings.router,
    )
    app.dependency_overrides.update(base.app.dependency_overrides)  # type: ignore[attr-defined]
    app.dependency_overrides[get_parent_link_service] = lambda: ParentLinkService(sm)
    app.dependency_overrides[get_tutoring_preferences_repo] = lambda: TutoringPreferencesRepository(
        sm
    )
    return TestClient(app)


def tutor_reads(client: TestClient, tutor: SeededTutor, student: uuid.UUID) -> None:
    """One T19 list read and one T20 detail read by ``tutor``: two audit rows."""
    act_as(client, tutor.user_id, Role.teacher)
    assert client.get("/api/tutor/students").status_code == 200
    assert client.get(f"/api/tutor/students/{student}").status_code == 200


def add_audit(
    sm: sessionmaker[Session], student: uuid.UUID, tutor: SeededTutor, *, ago: timedelta
) -> None:
    """An audit row written directly (for the statement count, which needs many rows)."""
    with sm.begin() as session:
        session.add(
            TutorAccessAudit(
                student_id=student,
                tutor_profile_id=tutor.profile_id,
                tutor_public_name="Sara M.",
                action=TutorAccessAction.detail,
                accessed_at=NOW - ago,
            )
        )


def parent_grant_notices(sm: sessionmaker[Session], parent: uuid.UUID) -> list[tuple[str, str]]:
    """``(grantId, studentId)`` of every "sharing started" inbox notice the parent holds."""
    with sm() as session:
        rows = session.execute(
            sa.text(
                "SELECT payload->>'grantId', payload->>'studentId', dedupe_key "
                "FROM notifications WHERE user_id = :p AND type = 'tutor_access' "
                "ORDER BY created_at"
            ),
            {"p": parent},
        ).all()
    assert all(key == f"grant:{grant}:created" for grant, _, key in rows)
    return [(str(grant), str(student)) for grant, student, _ in rows]


def without_classes(item: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in item.items() if key != "alsoTeachesClasses"}


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
    test_client = sharing_client(sm)
    yield test_client
    test_client.app.dependency_overrides.clear()  # type: ignore[attr-defined]


@pytest.fixture
def child(sm: sessionmaker[Session]) -> uuid.UUID:
    return add_student(sm, display_name="Amelia")


@pytest.fixture
def parent(sm: sessionmaker[Session], child: uuid.UUID) -> uuid.UUID:
    return link_parent(sm, child)


# ---------------------------------------------------------------------------
# PA6
# ---------------------------------------------------------------------------


def test_pa6_returns_only_childs_grants_also_teaches_empty(
    sm: sessionmaker[Session], client: TestClient, child: uuid.UUID, parent: uuid.UUID
) -> None:
    listed = add_tutor(sm)
    rejected = add_tutor(sm, state="rejected", first_name="Omar", initial="K")
    ended = add_tutor(sm, first_name="Lina", initial=None)
    add_grant(sm, child, listed, created_ago=timedelta(days=3))
    add_grant(sm, child, rejected, created_ago=timedelta(days=6))
    add_grant(sm, child, ended, created_ago=timedelta(days=2), revoked=GrantRevokeReason.student)
    someone_else = add_grant(sm, add_student(sm), listed)
    classes = ClassService(sm)
    made = classes.create_class(listed.user_id, "Physics 10A")
    assert made.join_code is not None
    classes.join_by_code(child, made.join_code)
    act_as(client, child, Role.student)
    own = client.get(S8).json()["items"]

    act_as(client, parent, Role.parent)
    response = client.get(pa6(child))

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == NO_STORE
    items = response.json()["items"]
    # The same grants, order, statuses and tutor cards as the child's own S8 ...
    assert [without_classes(item) for item in items] == [without_classes(item) for item in own]
    assert [item["status"] for item in items] == ["active", "tutor_unavailable", "revoked"]
    # ... with the class names left out: the child does see one (non-vacuity), the parent none.
    assert [item["alsoTeachesClasses"] for item in own] == [["Physics 10A"], [], []]
    assert [item["alsoTeachesClasses"] for item in items] == [[], [], []]
    assert "Physics 10A" not in response.text
    assert str(someone_else) not in response.text
    assert str(listed.user_id) not in response.text  # SC-19: never a tutor's users.id
    assert audit_rows(sm) == []


def test_pa6_empty_for_a_child_without_grants(
    client: TestClient, child: uuid.UUID, parent: uuid.UUID
) -> None:
    act_as(client, parent, Role.parent)
    response = client.get(pa6(child))
    assert response.status_code == 200
    assert response.json() == {"items": []}
    assert response.headers["cache-control"] == NO_STORE


def test_query_budget_pa6_never_reads_the_childs_classes(
    sm: sessionmaker[Session], client: TestClient, child: uuid.UUID, parent: uuid.UUID
) -> None:
    """SPEC §b.3: PA6 does not run the class lookup (``include_classes=False``).

    The child's own S8 does run it (non-vacuity: the same data, the statement shows up there),
    so the absence on PA6 is the route's choice. Mutation: ``include_classes=True`` in
    ``child_tutor_grants`` turns this red.
    """
    tutor = add_tutor(sm)
    add_grant(sm, child, tutor)
    classes = ClassService(sm)
    made = classes.create_class(tutor.user_id, "Physics 10A")
    assert made.join_code is not None
    classes.join_by_code(child, made.join_code)

    act_as(client, child, Role.student)
    with count_statements(sm) as own_seen:
        assert client.get(S8).status_code == 200
    assert sum("class_enrollments" in statement for statement in own_seen) == 1, own_seen

    act_as(client, parent, Role.parent)
    with count_statements(sm) as seen:
        response = client.get(pa6(child))
    assert response.status_code == 200
    assert len(response.json()["items"]) == 1
    assert not any("class_enrollments" in statement for statement in seen), seen
    assert sum("tutor_data_grants" in statement for statement in seen) == 1


def test_grant_dto_for_a_parent_never_carries_the_childs_classes(
    sm: sessionmaker[Session], child: uuid.UUID
) -> None:
    """SPEC §b.3: even when the view holds class names, a parent's DTO has none.

    Mutation: listing the view's classes for every viewer in ``grant_dto`` turns this red; the
    route alone cannot show it, because PA6 never asks the repository for classes (the route
    side is :func:`test_pa6_shows_no_class_even_if_the_repository_returned_one`).
    """
    tutor = add_tutor(sm)
    add_grant(sm, child, tutor)
    classes = ClassService(sm)
    made = classes.create_class(tutor.user_id, "Physics 10A")
    assert made.join_code is not None
    classes.join_by_code(child, made.join_code)
    [view] = TutorGrantRepository(sm).grants_for_student(child, include_classes=True)
    assert view.also_teaches_classes == ("Physics 10A",)  # non-vacuity: the view holds one
    areas = get_tutoring_areas()

    assert grant_dto(view, areas, viewer="parent").alsoTeachesClasses == []
    assert grant_dto(view, areas, viewer="student").alsoTeachesClasses == ["Physics 10A"]


class _ClassRevealingRepo(TutorGrantRepository):
    """A repository that always loads the child's classes, whatever the caller asks for."""

    def grants_for_student(
        self, student_id: uuid.UUID, *, include_classes: bool = True
    ) -> list[GrantView]:
        return super().grants_for_student(student_id, include_classes=True)


def test_pa6_shows_no_class_even_if_the_repository_returned_one(
    sm: sessionmaker[Session], client: TestClient, child: uuid.UUID, parent: uuid.UUID
) -> None:
    """Defence in depth for SPEC §b.3: the DTO builder, not only the query, drops the classes.

    Mutation: ``viewer="student"`` in ``child_tutor_grants`` turns this red (with the repository
    asked for no classes the route alone can never show it).
    """
    tutor = add_tutor(sm)
    add_grant(sm, child, tutor)
    classes = ClassService(sm)
    made = classes.create_class(tutor.user_id, "Physics 10A")
    assert made.join_code is not None
    classes.join_by_code(child, made.join_code)
    client.app.dependency_overrides[get_tutor_grant_repo] = lambda: _ClassRevealingRepo(sm)  # type: ignore[attr-defined]
    act_as(client, child, Role.student)
    assert client.get(S8).json()["items"][0]["alsoTeachesClasses"] == ["Physics 10A"]  # non-vacuity

    act_as(client, parent, Role.parent)
    response = client.get(pa6(child))

    assert response.status_code == 200
    assert [item["alsoTeachesClasses"] for item in response.json()["items"]] == [[]]
    assert "Physics 10A" not in response.text


def test_notify_grant_commit_implies_parent_inbox_rows(
    sm: sessionmaker[Session], client: TestClient, child: uuid.UUID, parent: uuid.UUID
) -> None:
    """SPEC §b.4: every grant a parent can see in PA6 came with a notice to that parent.

    And the converse: a refused grant shows nothing in PA6 and sends nothing.
    PA6 is the durable record (§b.4 point 4); the notice only points to it.
    """
    second_parent = link_parent(sm, child)
    tutor = add_tutor(sm)
    hidden = add_tutor(sm, paused=True)
    act_as(client, child, Role.student)
    refused = client.post(S8, json={"tutorId": str(hidden.profile_id)})
    assert refused.status_code == 404
    first = client.post(S8, json={"tutorId": str(tutor.profile_id)}).json()["grantId"]
    assert client.post(f"{S8}/{first}/revoke").status_code == 200
    second = client.post(S8, json={"tutorId": str(tutor.profile_id)})
    assert second.status_code == 201, second.text

    for each in (parent, second_parent):
        act_as(client, each, Role.parent)
        shown = client.get(pa6(child)).json()["items"]
        shown_ids = [item["grantId"] for item in shown]
        assert sorted(shown_ids) == sorted([first, second.json()["grantId"]])
        assert sorted(parent_grant_notices(sm, each)) == sorted(
            (grant_id, str(child)) for grant_id in shown_ids
        )
        assert sorted(key for user, _, key in outbox_rows(sm) if user == each) == sorted(
            f"grant:{grant_id}:created:{each}" for grant_id in shown_ids
        )
    assert str(hidden.profile_id) not in client.get(pa6(child)).text


# ---------------------------------------------------------------------------
# PA7
# ---------------------------------------------------------------------------


def test_pa7_access_log_equals_the_childs_s11_log_with_filter_and_cursor(
    sm: sessionmaker[Session], client: TestClient, child: uuid.UUID, parent: uuid.UUID
) -> None:
    sara = add_tutor(sm)
    omar = add_tutor(sm, first_name="Omar", initial="K")
    other = add_student(sm, display_name="Nour")
    for tutor in (sara, omar):
        add_grant(sm, child, tutor)
    add_grant(sm, other, sara)
    tutor_reads(client, sara, child)
    tutor_reads(client, omar, child)
    act_as(client, sara.user_id, Role.teacher)
    assert client.get(f"/api/tutor/students/{other}").status_code == 200
    act_as(client, child, Role.student)
    own_log = client.get(S11, params={"limit": 50}).json()["items"]
    own_sara = client.get(S11, params={"tutorId": str(sara.profile_id)}).json()["items"]
    assert len(own_log) == 4  # non-vacuity: two list and two detail reads of this child
    assert len(own_sara) == 2

    act_as(client, parent, Role.parent)
    first = client.get(pa7(child), params={"limit": 3})
    assert first.status_code == 200, first.text
    assert first.headers["cache-control"] == NO_STORE
    page = first.json()
    assert page["nextCursor"] is not None
    rest = client.get(pa7(child), params={"limit": 3, "cursor": page["nextCursor"]})
    assert rest.headers["cache-control"] == NO_STORE
    assert rest.json()["nextCursor"] is None
    assert page["items"] + rest.json()["items"] == own_log
    assert set(page["items"][0]) == {"tutorId", "tutorName", "action", "accessedAt"}  # no id
    only_sara = client.get(pa7(child), params={"tutorId": str(sara.profile_id)}).json()
    assert only_sara == {"items": own_sara, "nextCursor": None}


def test_pa7_cursor_has_its_own_tag(
    sm: sessionmaker[Session], client: TestClient, child: uuid.UUID, parent: uuid.UUID
) -> None:
    """O21: a cursor from S11 or T19 is refused by PA7, and PA7's by S11."""
    tutor = add_tutor(sm)
    add_grant(sm, child, tutor)
    add_grant(sm, add_student(sm), tutor)
    tutor_reads(client, tutor, child)
    t19_cursor = client.get("/api/tutor/students", params={"limit": 1}).json()["nextCursor"]
    act_as(client, child, Role.student)
    s11_cursor = client.get(S11, params={"limit": 1}).json()["nextCursor"]
    act_as(client, parent, Role.parent)
    pa7_cursor = client.get(pa7(child), params={"limit": 1}).json()["nextCursor"]
    assert None not in (t19_cursor, s11_cursor, pa7_cursor)

    for foreign in (s11_cursor, t19_cursor, "not-a-cursor"):
        refused = client.get(pa7(child), params={"cursor": foreign})
        assert refused.status_code == 422, foreign
        assert refused.json()["detail"]["code"] == "invalid_cursor"
        assert refused.headers["cache-control"] == NO_STORE
    # Red case: PA7's own cursor is accepted by PA7.
    assert client.get(pa7(child), params={"cursor": pa7_cursor}).status_code == 200
    act_as(client, child, Role.student)
    back = client.get(S11, params={"cursor": pa7_cursor})
    assert back.status_code == 422
    assert back.json()["detail"]["code"] == "invalid_cursor"


def test_pa7_cursor_is_bound_to_the_child_it_was_minted_for(
    sm: sessionmaker[Session], client: TestClient, child: uuid.UUID, parent: uuid.UUID
) -> None:
    """A parent of two children cannot carry a page position from one child's log to the other's.

    Mutation: tagging the cursor with ``ACCESS_LOG_ENDPOINT`` alone (not the child) turns this
    red, because child B's PA7 then accepts child A's cursor.
    """
    sibling = add_student(sm, display_name="Karim")
    with sm.begin() as session:
        session.add(ParentChildLink(parent_id=parent, child_id=sibling))
    tutor = add_tutor(sm)
    for each in (child, sibling):
        add_grant(sm, each, tutor)
        for minutes in (1, 2, 3):
            add_audit(sm, each, tutor, ago=timedelta(minutes=minutes))
    act_as(client, parent, Role.parent)
    cursors = {
        each: client.get(pa7(each), params={"limit": 1}).json()["nextCursor"]
        for each in (child, sibling)
    }
    assert None not in cursors.values()
    assert cursors[child] != cursors[sibling]

    for owner, other in ((child, sibling), (sibling, child)):
        refused = client.get(pa7(other), params={"cursor": cursors[owner]})
        assert refused.status_code == 422, (owner, other)
        assert refused.json()["detail"]["code"] == "invalid_cursor"
        assert refused.headers["cache-control"] == NO_STORE
        # Red case: the cursor continues the log of the child it was minted for.
        accepted = client.get(pa7(owner), params={"cursor": cursors[owner], "limit": 1})
        assert accepted.status_code == 200, accepted.text
        assert len(accepted.json()["items"]) == 1


def test_pa7_query_parameters_are_validated(
    client: TestClient, child: uuid.UUID, parent: uuid.UUID
) -> None:
    act_as(client, parent, Role.parent)
    for params in ({"tutorId": "nope"}, {"limit": 0}, {"limit": 51}, {"limit": "x"}):
        response = client.get(pa7(child), params=params)
        assert response.status_code == 422, params
        assert response.headers["cache-control"] == NO_STORE
    assert client.get(pa7(child), params={"limit": 50}).status_code == 200


def test_pa7_writes_no_tutor_access_audit_row(
    sm: sessionmaker[Session], client: TestClient, child: uuid.UUID, parent: uuid.UUID
) -> None:
    """SPEC §b.2, O22: the log records tutor reads only; a parent's reads add nothing."""
    tutor = add_tutor(sm)
    add_grant(sm, child, tutor)
    tutor_reads(client, tutor, child)
    before = audit_rows(sm)
    assert len(before) == 2

    act_as(client, parent, Role.parent)
    for _ in range(3):
        response = client.get(pa7(child))
        assert response.status_code == 200
        # The route did read the log (non-vacuity): both tutor reads are listed.
        assert len(response.json()["items"]) == 2
        assert client.get(pa7(child), params={"tutorId": str(tutor.profile_id)}).status_code == 200

    assert audit_rows(sm) == before


def test_pa6_writes_no_tutor_access_audit_row(
    sm: sessionmaker[Session], client: TestClient, child: uuid.UUID, parent: uuid.UUID
) -> None:
    tutor = add_tutor(sm)
    add_grant(sm, child, tutor)
    tutor_reads(client, tutor, child)
    before = audit_rows(sm)
    assert len(before) == 2

    act_as(client, parent, Role.parent)
    for _ in range(3):
        assert len(client.get(pa6(child)).json()["items"]) == 1

    assert audit_rows(sm) == before


def test_query_budget_pa7_link_check_plus_one_statement(
    sm: sessionmaker[Session], client: TestClient, child: uuid.UUID, parent: uuid.UUID
) -> None:
    """SPEC §e.3: "S11, PA7 audit log | 1 (PA7: + the link check)", whatever the page size."""
    tutor = add_tutor(sm)
    for minutes in range(12):
        add_audit(sm, child, tutor, ago=timedelta(minutes=minutes + 1))
    act_as(client, parent, Role.parent)

    for limit in (1, 5, 12):
        with count_statements(sm) as seen:
            response = client.get(pa7(child), params={"limit": limit})
        assert response.status_code == 200
        assert len(response.json()["items"]) == limit
        assert len(seen) == 2, seen
        assert sum("parent_child_links" in statement for statement in seen) == 1
        assert sum("tutor_access_audit" in statement for statement in seen) == 1


# ---------------------------------------------------------------------------
# Route class
# ---------------------------------------------------------------------------


def test_parent_sharing_router_is_two_get_routes_on_the_tutoring_route_class() -> None:
    routes = flatten_routes(parent_tutor_access.router)
    pairs = {(method, route.path) for route in routes for method in route.methods}
    assert pairs == {
        ("GET", "/api/parent/children/{child_id}/tutor-grants"),
        ("GET", "/api/parent/children/{child_id}/tutor-access-log"),
    }
    assert len(routes) == 2  # non-vacuity: both routes were inspected; neither writes
    assert all(type(route) is TutoringRoute for route in routes)
