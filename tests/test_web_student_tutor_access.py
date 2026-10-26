"""S8-S11: a student's data grants and the log of tutor reads (SPEC §b.2 "Student", §b.4, ADR-T02).

Route-level, through ``tests.test_tutor_grant_repo.grants_client`` (``app_with_routers``).

* S8 lists live grants first, then ended ones, newest first, each with its status
  and, for the student only, the classes the tutor also teaches them (SC-2e).
* S9 needs a verified email; it creates (201) or returns the live grant (200), and
  is refused for a tutor who is not listed-and-unpaused or is in a block with the
  student (O11). A new grant tells the tutor and every linked parent; the parents'
  email is queued in the grant's transaction (SPEC §b.4).
* S10 is idempotent and only for the student's own grant (O5); the tutor is told,
  in generic words, that access ended (SC-11).
* S11 is the student's own log, newest first, filterable by tutor, keyset-paged.
* Every route answers ``private, no-store`` on every status (``TutoringRoute``).
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa

from lemely.db.class_repo import ClassService
from lemely.db.models.enums import GrantRevokeReason, Role
from tests.test_tutor_grant_repo import (
    add_grant,
    add_student,
    audit_rows,
    grants_client,
    inbox_rows,
    link_parent,
    live_grant_count,
    outbox_rows,
)
from tests.tutoring_db import (
    act_as,
    add_block,
    add_subject,
    add_tutor,
    add_user,
    emptied_after,
    tutoring_database,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session, sessionmaker

NO_STORE = "private, no-store"
GRANTS = "/api/student/tutor-grants"
LOG = "/api/student/tutor-access-log"


@pytest.fixture(scope="module")
def tutoring_db() -> Iterator[sessionmaker[Session]]:
    with tutoring_database() as factory:
        yield factory


@pytest.fixture
def sm(tutoring_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(tutoring_db)


@pytest.fixture
def client(sm: sessionmaker[Session]) -> Iterator[TestClient]:
    test_client = grants_client(sm)
    yield test_client
    test_client.app.dependency_overrides.clear()  # type: ignore[attr-defined]


@pytest.fixture
def student(sm: sessionmaker[Session], client: TestClient) -> uuid.UUID:
    student_id = add_student(sm, display_name="Amelia")
    act_as(client, student_id, Role.student)
    return student_id


# ---------------------------------------------------------------------------
# S8
# ---------------------------------------------------------------------------


def test_s8_lists_live_first_then_ended_with_status_and_also_teaches_classes(
    sm: sessionmaker[Session], client: TestClient, student: uuid.UUID
) -> None:
    subject = add_subject(sm, name="Physics")
    listed = add_tutor(sm, subjects=[subject])
    rejected = add_tutor(sm, state="rejected", first_name="Omar", initial="K")
    ended = add_tutor(sm, first_name="Lina", initial=None)
    live = add_grant(sm, student, listed, created_ago=timedelta(days=3))
    live_unavailable = add_grant(sm, student, rejected, created_ago=timedelta(days=6))
    revoked = add_grant(
        sm, student, ended, created_ago=timedelta(days=2), revoked=GrantRevokeReason.student
    )
    add_grant(sm, add_student(sm), listed)  # someone else's grant
    classes = ClassService(sm)
    made = classes.create_class(listed.user_id, "Physics 10A")
    assert made.join_code is not None
    classes.join_by_code(student, made.join_code)

    response = client.get(GRANTS)

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == NO_STORE
    items = response.json()["items"]
    assert [i["grantId"] for i in items] == [str(live), str(live_unavailable), str(revoked)]
    assert [i["status"] for i in items] == ["active", "tutor_unavailable", "revoked"]
    assert [i["alsoTeachesClasses"] for i in items] == [["Physics 10A"], [], []]
    first = items[0]
    assert set(first) == {
        "grantId",
        "tutor",
        "createdAt",
        "revokedAt",
        "status",
        "scope",
        "alsoTeachesClasses",
    }
    assert first["scope"] == "all_subjects_derived"
    assert first["revokedAt"] is None
    assert items[2]["revokedAt"] is not None
    assert first["tutor"]["tutorId"] == str(listed.profile_id)
    assert first["tutor"]["publicName"] == "Sara M."
    assert first["tutor"]["subjects"] == [{"code": subject, "name": "Physics"}]
    assert str(listed.user_id) not in response.text  # SC-19: never a tutor's users.id
    assert audit_rows(sm) == []


def test_s8_empty(client: TestClient, student: uuid.UUID) -> None:
    response = client.get(GRANTS)
    assert response.json() == {"items": []}


# ---------------------------------------------------------------------------
# S9
# ---------------------------------------------------------------------------


def test_s9_creates_201_then_returns_the_live_grant_200(
    sm: sessionmaker[Session], client: TestClient, student: uuid.UUID
) -> None:
    tutor = add_tutor(sm)
    parent = link_parent(sm, student)

    created = client.post(GRANTS, json={"tutorId": str(tutor.profile_id)})
    repeated = client.post(GRANTS, json={"tutorId": str(tutor.profile_id)})

    assert created.status_code == 201, created.text
    assert repeated.status_code == 200, repeated.text
    assert created.headers["cache-control"] == repeated.headers["cache-control"] == NO_STORE
    grant_id = created.json()["grantId"]
    assert repeated.json()["grantId"] == grant_id
    assert created.json()["status"] == "active"
    assert live_grant_count(sm, student, tutor.profile_id) == 1
    # One inbox notice each to the tutor and the parent, none to the student who acted.
    inbox = inbox_rows(sm)
    assert sorted((user, kind) for user, kind, _, _ in inbox) == sorted(
        [(tutor.user_id, "tutor_access"), (parent, "tutor_access")]
    )
    tutor_body = next(body for user, _, _, body in inbox if user == tutor.user_id)
    assert tutor_body == "Amelia shared their progress with you."
    assert outbox_rows(sm) == [
        (parent, "tutor_access_granted", f"grant:{grant_id}:created:{parent}")
    ]


def test_s9_requires_verified_email(sm: sessionmaker[Session], client: TestClient) -> None:
    unverified = add_student(sm, verified=False)
    act_as(client, unverified, Role.student)
    tutor = add_tutor(sm)

    response = client.post(GRANTS, json={"tutorId": str(tutor.profile_id)})

    assert response.status_code == 403
    assert response.json()["detail"] == {"code": "email_unverified"}
    assert response.headers["cache-control"] == NO_STORE
    assert live_grant_count(sm, unverified, tutor.profile_id) == 0


def test_s9_refused_for_unlisted_paused_or_blocked_tutor(
    sm: sessionmaker[Session], client: TestClient, student: uuid.UUID
) -> None:
    not_found = [str(uuid.uuid4()), "not-a-uuid"]
    for tutor_id in not_found:
        response = client.post(GRANTS, json={"tutorId": tutor_id})
        assert response.status_code == 404, tutor_id
        assert response.json()["detail"]["code"] == "not_found"
        assert response.headers["cache-control"] == NO_STORE
    hidden = [
        add_tutor(sm, state=s)
        for s in ("draft", "pending_review", "rejected", "suspended", "closed")
    ]
    hidden.append(add_tutor(sm, paused=True))
    for tutor in hidden:
        response = client.post(GRANTS, json={"tutorId": str(tutor.profile_id)})
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "tutor_not_listed"
    blocked_by_student = add_tutor(sm)
    add_block(sm, student, blocked_by_student.user_id)
    blocked_by_tutor = add_tutor(sm)
    add_block(sm, blocked_by_tutor.user_id, student)
    for tutor in (blocked_by_student, blocked_by_tutor):
        response = client.post(GRANTS, json={"tutorId": str(tutor.profile_id)})
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "blocked"
    with sm() as session:
        assert session.execute(sa.text("SELECT count(*) FROM tutor_data_grants")).scalar_one() == 0
    assert inbox_rows(sm) == []
    assert outbox_rows(sm) == []


def test_s9_body_is_validated(client: TestClient, student: uuid.UUID) -> None:
    for body in ({}, {"tutorId": 5}, {"tutorId": "x", "extra": 1}):
        response = client.post(GRANTS, json=body)
        assert response.status_code == 422
        assert response.headers["cache-control"] == NO_STORE


# ---------------------------------------------------------------------------
# S10
# ---------------------------------------------------------------------------


def test_s10_revoke_idempotent_and_tells_the_tutor_generically(
    sm: sessionmaker[Session], client: TestClient, student: uuid.UUID
) -> None:
    tutor = add_tutor(sm)
    parent = link_parent(sm, student)
    grant_id = client.post(GRANTS, json={"tutorId": str(tutor.profile_id)}).json()["grantId"]
    before = len(inbox_rows(sm))

    first = client.post(f"{GRANTS}/{grant_id}/revoke")
    second = client.post(f"{GRANTS}/{grant_id}/revoke")

    assert first.status_code == second.status_code == 200
    assert first.headers["cache-control"] == NO_STORE
    assert first.json()["status"] == "revoked"
    assert first.json()["revokedAt"] is not None
    assert second.json() == first.json()
    new_notices = inbox_rows(sm)[before:]
    assert [(user, title, body) for user, _, title, body in new_notices] == [
        (tutor.user_id, "Progress sharing ended", "Access to progress you could see has ended.")
    ]
    assert parent not in {user for user, *_ in new_notices}
    assert live_grant_count(sm, student, tutor.profile_id) == 0


def test_s10_other_students_grant_and_unknown_id_are_the_same_404(
    sm: sessionmaker[Session], client: TestClient, student: uuid.UUID
) -> None:
    tutor = add_tutor(sm)
    someone_else = add_student(sm)
    theirs = add_grant(sm, someone_else, tutor)

    responses = [client.post(f"{GRANTS}/{gid}/revoke") for gid in (theirs, uuid.uuid4())]

    assert [r.status_code for r in responses] == [404, 404]
    assert responses[0].json() == responses[1].json()
    assert responses[0].headers["cache-control"] == NO_STORE
    assert live_grant_count(sm, someone_else, tutor.profile_id) == 1
    assert client.post(f"{GRANTS}/not-a-uuid/revoke").status_code == 422


def test_revoke_then_regrant_notifies_parents_twice(
    sm: sessionmaker[Session], client: TestClient, student: uuid.UUID
) -> None:
    """F17: each grant is its own event, so its notices carry their own keys."""
    tutor = add_tutor(sm)
    parent = link_parent(sm, student)

    first = client.post(GRANTS, json={"tutorId": str(tutor.profile_id)}).json()["grantId"]
    assert client.post(f"{GRANTS}/{first}/revoke").status_code == 200
    second = client.post(GRANTS, json={"tutorId": str(tutor.profile_id)})

    assert second.status_code == 201
    assert second.json()["grantId"] != first
    parent_inbox = [row for row in inbox_rows(sm) if row[0] == parent]
    assert len(parent_inbox) == 2
    assert all(kind == "tutor_access" for _, kind, _, _ in parent_inbox)
    assert [key for user, _, key in outbox_rows(sm) if user == parent] == [
        f"grant:{first}:created:{parent}",
        f"grant:{second.json()['grantId']}:created:{parent}",
    ]


# ---------------------------------------------------------------------------
# S11
# ---------------------------------------------------------------------------


def test_s11_access_log_newest_first_filter_and_cursor(
    sm: sessionmaker[Session], client: TestClient, student: uuid.UUID
) -> None:
    sara = add_tutor(sm)
    omar = add_tutor(sm, first_name="Omar", initial="K")
    add_grant(sm, student, sara)
    add_grant(sm, student, omar)
    for tutor, path in (
        (sara, "/api/tutor/students"),
        (sara, f"/api/tutor/students/{student}"),
        (omar, f"/api/tutor/students/{student}"),
    ):
        act_as(client, tutor.user_id, Role.teacher)
        assert client.get(path).status_code == 200
    act_as(client, student, Role.student)

    first = client.get(LOG, params={"limit": 2})

    assert first.status_code == 200, first.text
    assert first.headers["cache-control"] == NO_STORE
    page = first.json()
    assert [(i["tutorName"], i["action"]) for i in page["items"]] == [
        ("Omar K.", "detail"),
        ("Sara M.", "detail"),
    ]
    assert set(page["items"][0]) == {"tutorId", "tutorName", "action", "accessedAt"}  # no id
    assert page["items"][0]["tutorId"] == str(omar.profile_id)
    rest = client.get(LOG, params={"limit": 2, "cursor": page["nextCursor"]}).json()
    assert [(i["tutorName"], i["action"]) for i in rest["items"]] == [("Sara M.", "list")]
    assert rest["nextCursor"] is None

    only_sara = client.get(LOG, params={"tutorId": str(sara.profile_id)}).json()
    assert [i["action"] for i in only_sara["items"]] == ["detail", "list"]
    # O21: a cursor from another list is refused.
    act_as(client, sara.user_id, Role.teacher)
    add_grant(sm, add_student(sm), sara)
    t19_cursor = client.get("/api/tutor/students", params={"limit": 1}).json()["nextCursor"]
    assert t19_cursor is not None
    act_as(client, student, Role.student)
    refused = client.get(LOG, params={"cursor": t19_cursor})
    assert refused.status_code == 422
    assert refused.json()["detail"]["code"] == "invalid_cursor"
    assert refused.headers["cache-control"] == NO_STORE
    assert client.get(LOG, params={"tutorId": "nope"}).status_code == 422


def test_s11_is_the_callers_own_log_only(
    sm: sessionmaker[Session], client: TestClient, student: uuid.UUID
) -> None:
    tutor = add_tutor(sm)
    other = add_student(sm)
    add_grant(sm, other, tutor)
    act_as(client, tutor.user_id, Role.teacher)
    assert client.get(f"/api/tutor/students/{other}").status_code == 200
    act_as(client, student, Role.student)
    assert client.get(LOG).json() == {"items": [], "nextCursor": None}


# ---------------------------------------------------------------------------
# Consent rules seen from the tutor's side
# ---------------------------------------------------------------------------


def test_authz_grant_invalid_when_listing_rejected(
    sm: sessionmaker[Session], client: TestClient, student: uuid.UUID
) -> None:
    """CB-4: a re-review that is rejected ends the tutor's access; the student sees why."""
    tutor = add_tutor(sm)
    assert client.post(GRANTS, json={"tutorId": str(tutor.profile_id)}).status_code == 201
    act_as(client, tutor.user_id, Role.teacher)
    assert client.get(f"/api/tutor/students/{student}").status_code == 200
    with sm.begin() as session:
        session.execute(
            sa.text("UPDATE tutor_profiles SET listing_state = 'rejected' WHERE id = :t"),
            {"t": tutor.profile_id},
        )

    refused = client.get(f"/api/tutor/students/{student}")

    assert refused.status_code == 403
    assert refused.json()["detail"]["code"] == "access_ended"
    assert len(audit_rows(sm)) == 1  # only the read before the rejection
    act_as(client, student, Role.student)
    [item] = client.get(GRANTS).json()["items"]
    assert item["status"] == "tutor_unavailable"
    assert item["revokedAt"] is None


def test_parent_and_teacher_are_refused_by_the_guard(
    sm: sessionmaker[Session], client: TestClient
) -> None:
    tutor = add_tutor(sm)
    for role in (Role.parent, Role.teacher, Role.school_admin, Role.platform_admin):
        act_as(client, add_user(sm, role), role)
        for method, path in (("GET", GRANTS), ("POST", GRANTS), ("GET", LOG)):
            response = client.request(method, path, json={"tutorId": str(tutor.profile_id)})
            assert response.status_code == 403, (role, method, path)
            assert response.headers["cache-control"] == NO_STORE
