"""Object-level rules for granted data: O2, O3, O5, O14 (both directions), O18 (SPEC §c.3).

The grant is the only door from a tutor to a student's analytics (ADR-T03): it is
checked on every read against the caller's own profile, never against another
profile id (O18, ID-1), and it never unions with the class roster in either
direction (O14). Each rule has a passing case and a failing one. Apps come from
``tests.test_tutor_grant_repo.grants_client`` (``app_with_routers``).
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

from lemely.db.class_repo import ClassService
from lemely.db.models.enums import GrantRevokeReason, Role
from tests.test_tutor_grant_repo import (
    add_grant,
    add_student,
    audit_rows,
    grants_client,
    seed_history,
)
from tests.test_tutor_review_repo import add_booking
from tests.tutoring_db import (
    act_as,
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
NOT_FOUND = {"detail": {"code": "not_found", "message": "Student not found."}}


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


def enrol(sm: sessionmaker[Session], teacher: uuid.UUID, student: uuid.UUID) -> None:
    classes = ClassService(sm)
    made = classes.create_class(teacher, "Physics 10A")
    assert made.join_code is not None
    classes.join_by_code(student, made.join_code)


# ---------------------------------------------------------------------------
# O2, O3
# ---------------------------------------------------------------------------


def test_authz_t20_requires_a_currently_valid_grant(
    sm: sessionmaker[Session], client: TestClient
) -> None:
    """O2: checked per request; the same tutor is refused once the grant ends."""
    tutor = add_tutor(sm)
    student = add_student(sm)
    grant = add_grant(sm, student, tutor)
    act_as(client, tutor.user_id, Role.teacher)
    assert client.get(f"/api/tutor/students/{student}").status_code == 200

    act_as(client, student, Role.student)
    assert client.post(f"/api/student/tutor-grants/{grant}/revoke").status_code == 200
    act_as(client, tutor.user_id, Role.teacher)
    refused = client.get(f"/api/tutor/students/{student}")

    assert refused.status_code == 403
    assert refused.json()["detail"]["code"] == "access_ended"


def test_o3_every_t20_200_writes_exactly_one_detail_row(
    sm: sessionmaker[Session], client: TestClient
) -> None:
    tutor = add_tutor(sm)
    student = add_student(sm)
    grant = add_grant(sm, student, tutor)
    act_as(client, tutor.user_id, Role.teacher)
    for expected in range(1, 4):
        assert client.get(f"/api/tutor/students/{student}").status_code == 200
        assert (
            audit_rows(sm) == [(grant, student, tutor.profile_id, "Sara M.", "detail")] * expected
        )


# ---------------------------------------------------------------------------
# O18: the caller's own profile, never another's (ID-1)
# ---------------------------------------------------------------------------


def test_idor_t20_other_tutors_grant_does_not_authorize(
    sm: sessionmaker[Session], client: TestClient
) -> None:
    """Tutor B knows the student from a booking; the student granted tutor A only."""
    subject = add_subject(sm)
    tutor_a = add_tutor(sm, subjects=[subject])
    tutor_b = add_tutor(sm, subjects=[subject], first_name="Omar", initial="K")
    student = add_student(sm)
    add_grant(sm, student, tutor_a)
    add_booking(
        sm,
        student=student,
        tutor=tutor_b,
        subject=subject,
        state="accepted",
        ended_ago=-timedelta(days=2),
    )
    # An ended grant of A's must not turn B's answer into a 403 either.
    add_grant(
        sm, student, tutor_a, revoked=GrantRevokeReason.student, created_ago=timedelta(days=30)
    )

    act_as(client, tutor_b.user_id, Role.teacher)
    refused = client.get(f"/api/tutor/students/{student}")
    listing = client.get("/api/tutor/students")
    act_as(client, tutor_a.user_id, Role.teacher)
    allowed = client.get(f"/api/tutor/students/{student}")

    assert refused.status_code == 404
    assert refused.json() == NOT_FOUND
    assert listing.json() == {"items": [], "nextCursor": None}
    assert allowed.status_code == 200
    assert {row[2] for row in audit_rows(sm)} == {tutor_a.profile_id}


def test_idor_t20_unknown_and_never_granted_are_identical_404(
    sm: sessionmaker[Session], client: TestClient
) -> None:
    tutor = add_tutor(sm)
    act_as(client, tutor.user_id, Role.teacher)
    never_granted = add_student(sm)
    a_teacher = add_user(sm, Role.teacher)

    responses = [
        client.get(f"/api/tutor/students/{student_id}")
        for student_id in (uuid.uuid4(), never_granted, a_teacher, tutor.user_id)
    ]

    assert [r.status_code for r in responses] == [404] * 4
    assert all(r.json() == NOT_FOUND for r in responses)
    assert all(r.headers["cache-control"] == NO_STORE for r in responses)
    assert len({r.content for r in responses}) == 1
    assert audit_rows(sm) == []


# ---------------------------------------------------------------------------
# O14: the roster and the grant never authorise each other
# ---------------------------------------------------------------------------


def test_authz_cross_gate_class_teacher_without_grant_t20_404(
    sm: sessionmaker[Session], client: TestClient
) -> None:
    """The class teacher also tutors, but the student never granted them."""
    add_subject(sm, code="0625", name="Physics")
    teacher_tutor = add_tutor(sm)
    student = add_student(sm)
    enrol(sm, teacher_tutor.user_id, student)
    seed_history(sm, student)
    act_as(client, teacher_tutor.user_id, Role.teacher)

    # Red case: the roster gate does let this teacher see the student...
    assert client.get(f"/api/teacher/students/{student}").status_code == 200
    # ...and that is no door into the tutor routes.
    refused = client.get(f"/api/tutor/students/{student}")
    assert refused.status_code == 404
    assert refused.json() == NOT_FOUND
    assert client.get("/api/tutor/students").json()["items"] == []

    # With an ended grant it is the generic 403, never a 200 through the roster.
    add_grant(sm, student, teacher_tutor, revoked=GrantRevokeReason.student)
    ended = client.get(f"/api/tutor/students/{student}")
    assert ended.status_code == 403
    assert ended.json()["detail"]["code"] == "access_ended"
    assert audit_rows(sm) == []


def test_authz_cross_gate_granted_tutor_not_on_roster_teacher_route_403(
    sm: sessionmaker[Session], client: TestClient
) -> None:
    """A valid grant is no way into the teacher routes (teacher.py teacher_student_detail)."""
    add_subject(sm, code="0625", name="Physics")
    tutor = add_tutor(sm)
    student = add_student(sm, display_name="Amelia")
    seed_history(sm, student)
    add_grant(sm, student, tutor)
    act_as(client, tutor.user_id, Role.teacher)

    # Red case: the grant does open the tutor route...
    assert client.get(f"/api/tutor/students/{student}").status_code == 200
    # ...and not the roster route.
    refused = client.get(f"/api/teacher/students/{student}")
    assert refused.status_code == 403
    assert "Amelia" not in refused.text
    assert "attempts" not in refused.text


# ---------------------------------------------------------------------------
# No admin or other-role path to granted data (SPEC §c.1 comment, ADR-T03)
# ---------------------------------------------------------------------------


def test_only_teachers_reach_t19_and_t20(sm: sessionmaker[Session], client: TestClient) -> None:
    tutor = add_tutor(sm)
    student = add_student(sm)
    add_grant(sm, student, tutor)
    for role in (Role.student, Role.parent, Role.school_admin, Role.platform_admin):
        caller = student if role is Role.student else add_user(sm, role)
        act_as(client, caller, role)
        for path in ("/api/tutor/students", f"/api/tutor/students/{student}"):
            response = client.get(path)
            assert response.status_code == 403, (role, path)
            assert response.headers["cache-control"] == NO_STORE
    assert audit_rows(sm) == []
