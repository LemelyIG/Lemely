"""Route tests for the persisted study-plan endpoints (``/api/student/study-plan/*``, P4.7 chunk C).

Self-contained (mirrors ``tests/test_web_placement.py``) — a throwaway
Postgres DB per test, skipped cleanly when unreachable. Every assertion here
is verified by its inverse, this build's standing rule: a test that only
checks the happy value proves nothing about the guard.

Covers the three GET states (D4.12 §5's open gap, closed by this chunk), the
regenerate-supersedes contract, the flattened-404 completion boundary
(byte-identical bodies for "unknown" and "someone else's"), completion
idempotency, the malformed-uuid-is-422 guard, and the student-only role gate
on all three routes.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.db.base import Base
from lemely.db.models.academic import Subject
from lemely.db.models.attempts import Attempt, WeaknessRecord
from lemely.db.models.enums import AttemptOrigin, Role
from lemely.db.models.profiles import StudentSubjectEnrolment
from lemely.db.models.users import User
from lemely.db.student_profile_repo import StudentProfileService
from lemely.db.study_plan_repo import StudyPlanService
from lemely.runtime.config import DatabaseSettings
from lemely.web import create_app
from lemely.web.deps import (
    AuthContext,
    get_auth_context,
    get_student_profile_service,
    get_study_plan_service,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

# A fixed Wednesday, so "the current ISO week" is unambiguous across tests.
_THIS_WEEK = datetime(2026, 8, 5, 9, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Fixtures.
# ---------------------------------------------------------------------------


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app()
    yield TestClient(app)
    app.dependency_overrides.clear()


def _server_reachable(url: str) -> bool:
    server_url = make_url(url).set(database="postgres")
    engine = create_engine(server_url)
    try:
        with engine.connect():
            return True
    except OperationalError:
        return False
    finally:
        engine.dispose()


@pytest.fixture
def pg_sessionmaker() -> Iterator[sessionmaker[Session]]:
    base_url = DatabaseSettings().url
    if not _server_reachable(base_url):
        pytest.skip("local Postgres not reachable")

    server_url = make_url(base_url).set(database="postgres")
    admin = create_engine(server_url, isolation_level="AUTOCOMMIT")
    dbname = f"lemely_test_{uuid.uuid4().hex[:12]}"
    with admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{dbname}"'))

    engine = create_engine(make_url(base_url).set(database=dbname))
    Base.metadata.create_all(engine)
    try:
        yield sessionmaker(bind=engine, expire_on_commit=False, future=True)
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
def study_plan_service(pg_sessionmaker: sessionmaker[Session]) -> StudyPlanService:
    return StudyPlanService(pg_sessionmaker, now=lambda: _THIS_WEEK)


def _use_study_plan_service(client: TestClient, service: StudyPlanService) -> None:
    client.app.dependency_overrides[get_study_plan_service] = lambda: service  # type: ignore[union-attr]


def _auth_as(client: TestClient, user_id: uuid.UUID, role: Role) -> None:
    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(user_id), role=role.value
    )


def _seed_user(sm: sessionmaker[Session], role: Role = Role.student) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role))
    return uid


def _seed_weakness(
    sm: sessionmaker[Session],
    student_id: uuid.UUID,
    *,
    subject_code: str = "0625",
    topic: str,
    lost_marks: int,
    maximum_marks: int = 10,
) -> None:
    with sm.begin() as session:
        attempt = Attempt(
            user_id=student_id,
            subject_code=subject_code,
            awarded_marks=maximum_marks - lost_marks,
            maximum_marks=maximum_marks,
            percentage=100.0 * (maximum_marks - lost_marks) / maximum_marks,
            recorded_at=datetime.now(UTC),
            origin=AttemptOrigin.quiz,
        )
        session.add(attempt)
        session.flush()
        session.add(
            WeaknessRecord(
                user_id=student_id,
                attempt_id=attempt.id,
                topic=topic,
                lost_marks=lost_marks,
                maximum_marks=maximum_marks,
                accuracy=1.0 - lost_marks / maximum_marks,
            )
        )


# ---------------------------------------------------------------------------
# GET — the three distinguishable states.
# ---------------------------------------------------------------------------


def test_get_returns_not_generated_before_any_post(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    study_plan_service: StudyPlanService,
) -> None:
    _use_study_plan_service(client, study_plan_service)
    student = _seed_user(pg_sessionmaker)
    _auth_as(client, student, Role.student)

    resp = client.get("/api/student/study-plan/0625")

    assert resp.status_code == 200
    assert resp.json() == {"generated": False, "plan": None}


def test_get_returns_a_no_signal_refusal_distinct_from_not_generated(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    study_plan_service: StudyPlanService,
) -> None:
    """No weakness/placement/confidence rows at all -> generated=True, available=False."""
    _use_study_plan_service(client, study_plan_service)
    student = _seed_user(pg_sessionmaker)
    _auth_as(client, student, Role.student)

    not_generated = client.get("/api/student/study-plan/0625").json()
    study_plan_service.generate(student, "0625")
    refused = client.get("/api/student/study-plan/0625").json()

    # Inverse-of-inverse: the two states must not collapse into each other.
    assert not_generated != refused
    assert refused["generated"] is True
    assert refused["plan"]["available"] is False
    assert refused["plan"]["reason"] == "no_signal"
    assert refused["plan"]["sessions"] == []


def test_get_returns_a_real_available_plan_distinct_from_a_refusal(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    study_plan_service: StudyPlanService,
) -> None:
    _use_study_plan_service(client, study_plan_service)
    student = _seed_user(pg_sessionmaker)
    _seed_weakness(pg_sessionmaker, student, topic="1 Motion", lost_marks=5)
    _auth_as(client, student, Role.student)

    study_plan_service.generate(student, "0625")
    resp = client.get("/api/student/study-plan/0625")

    assert resp.status_code == 200
    body = resp.json()
    assert body["generated"] is True
    assert body["plan"]["available"] is True
    assert body["plan"]["reason"] is None
    assert len(body["plan"]["sessions"]) > 0
    session = body["plan"]["sessions"][0]
    expected_fields = {
        "id",
        "date",
        "topic",
        "activityType",
        "durationMinutes",
        "focus",
        "completedAt",
    }
    assert expected_fields <= set(session)
    assert session["completedAt"] is None

    # Inverse: this body is distinct from both other states seen above.
    assert body != {"generated": False, "plan": None}
    assert body["plan"]["available"] is not False


def test_another_students_plan_is_invisible(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    study_plan_service: StudyPlanService,
) -> None:
    """A plan is private study material: GET is scoped to the caller alone.

    Structurally guaranteed today — the route passes ``auth.user_id`` and never
    a caller-supplied id — so this pins that property against a future refactor
    that adds a student selector "for teachers" and leaks it here.
    """
    _use_study_plan_service(client, study_plan_service)
    owner = _seed_user(pg_sessionmaker)
    other = _seed_user(pg_sessionmaker)
    _seed_weakness(pg_sessionmaker, owner, topic="1 Motion", lost_marks=5)
    study_plan_service.generate(owner, "0625")

    _auth_as(client, other, Role.student)
    assert client.get("/api/student/study-plan/0625").json() == {"generated": False, "plan": None}

    # Inverse: the owner sees the very plan the other student could not.
    _auth_as(client, owner, Role.student)
    assert client.get("/api/student/study-plan/0625").json()["generated"] is True


def test_a_plan_for_one_subject_is_not_returned_for_another(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    study_plan_service: StudyPlanService,
) -> None:
    """The path's ``subject_code`` selects the plan; it is not decoration.

    A student enrolled in several subjects holds one plan per subject per week,
    and serving the physics plan under ``/0580`` would schedule maths study
    against physics weaknesses.
    """
    _use_study_plan_service(client, study_plan_service)
    student = _seed_user(pg_sessionmaker)
    _seed_weakness(pg_sessionmaker, student, subject_code="0625", topic="1 Motion", lost_marks=5)
    _auth_as(client, student, Role.student)
    study_plan_service.generate(student, "0625")

    assert client.get("/api/student/study-plan/0580").json() == {"generated": False, "plan": None}

    # Inverse: the subject it was generated for does return it.
    physics = client.get("/api/student/study-plan/0625").json()
    assert physics["generated"] is True
    assert physics["plan"]["subjectCode"] == "0625"


# ---------------------------------------------------------------------------
# POST — creates, and a second call supersedes rather than duplicating.
# ---------------------------------------------------------------------------


def test_post_creates_a_plan(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    study_plan_service: StudyPlanService,
) -> None:
    _use_study_plan_service(client, study_plan_service)
    student = _seed_user(pg_sessionmaker)
    _seed_weakness(pg_sessionmaker, student, topic="1 Motion", lost_marks=5)
    _auth_as(client, student, Role.student)

    resp = client.post("/api/student/study-plan", json={"subjectCode": "0625"})

    assert resp.status_code == 201
    body = resp.json()
    assert uuid.UUID(body["id"])
    assert body["subjectCode"] == "0625"
    assert body["available"] is True


def test_second_post_supersedes_rather_than_duplicating(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    study_plan_service: StudyPlanService,
) -> None:
    _use_study_plan_service(client, study_plan_service)
    student = _seed_user(pg_sessionmaker)
    _seed_weakness(pg_sessionmaker, student, topic="1 Motion", lost_marks=5)
    _auth_as(client, student, Role.student)

    first = client.post("/api/student/study-plan", json={"subjectCode": "0625"}).json()
    second = client.post("/api/student/study-plan", json={"subjectCode": "0625"}).json()

    # Inverse: they are not the same row.
    assert first["id"] != second["id"]

    current = client.get("/api/student/study-plan/0625").json()
    assert current["generated"] is True
    assert current["plan"]["id"] == second["id"]
    assert current["plan"]["id"] != first["id"]


def test_post_with_no_signal_returns_the_real_honest_refusal(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    study_plan_service: StudyPlanService,
) -> None:
    """An unknown/signal-less subject is not invented an error path: the
    service's real behaviour is a persisted 201 refusal, and this route must
    not paper over or reshape it."""
    _use_study_plan_service(client, study_plan_service)
    student = _seed_user(pg_sessionmaker)
    _auth_as(client, student, Role.student)

    resp = client.post("/api/student/study-plan", json={"subjectCode": "9999"})

    assert resp.status_code == 201
    body = resp.json()
    assert body["available"] is False
    assert body["reason"] == "no_signal"
    assert body["sessions"] == []

    # Inverse: a subject with a real signal is available.
    _seed_weakness(pg_sessionmaker, student, subject_code="0625", topic="1 Motion", lost_marks=5)
    ok_resp = client.post("/api/student/study-plan", json={"subjectCode": "0625"})
    assert ok_resp.json()["available"] is True


def test_post_takes_identity_from_the_token_never_the_payload(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    study_plan_service: StudyPlanService,
) -> None:
    """A smuggled ``studentId`` is rejected, not honoured (the retired IDOR pin).

    P4.10 chunk D (D4.22) deleted ``POST /api/student/plan`` and with it
    ``test_plan_post_ignores_any_caller_supplied_id`` — the only test that
    pinned *identity is the token, never the payload* on the study-plan
    surface. Its replacements in ``tests/test_authz_matrix.py`` are role
    guards (401/403) only, so this guarantee had no owner until now: the
    matrix stays green while a real property stops being proven.

    ``test_another_students_plan_is_invisible`` covers the *read* direction.
    What is unique here is the *write*: whose plan a POST creates.
    """
    _use_study_plan_service(client, study_plan_service)
    victim = _seed_user(pg_sessionmaker)
    attacker = _seed_user(pg_sessionmaker)
    _seed_weakness(pg_sessionmaker, victim, topic="1 Motion", lost_marks=5)
    _seed_weakness(pg_sessionmaker, attacker, topic="1 Motion", lost_marks=5)
    _auth_as(client, victim, Role.student)

    # extra="forbid": smuggling another student's id is a 422, not honoured.
    smuggled = client.post(
        "/api/student/study-plan",
        json={"subjectCode": "0625", "studentId": str(attacker)},
    )
    assert smuggled.status_code == 422

    # Inverse 1: rejected outright — no plan was written under either identity.
    assert client.get("/api/student/study-plan/0625").json()["generated"] is False
    _auth_as(client, attacker, Role.student)
    assert client.get("/api/student/study-plan/0625").json()["generated"] is False

    # Inverse 2: the same call without the smuggled id succeeds and the plan
    # lands on the token's owner, not on the id that was offered.
    _auth_as(client, victim, Role.student)
    created = client.post("/api/student/study-plan", json={"subjectCode": "0625"})
    assert created.status_code == 201
    assert client.get("/api/student/study-plan/0625").json()["plan"]["id"] == created.json()["id"]
    _auth_as(client, attacker, Role.student)
    assert client.get("/api/student/study-plan/0625").json()["generated"] is False


# ---------------------------------------------------------------------------
# Completion — flattened 404, idempotency, malformed id.
# ---------------------------------------------------------------------------


def test_complete_owner_gets_200_with_a_real_completed_at(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    study_plan_service: StudyPlanService,
) -> None:
    _use_study_plan_service(client, study_plan_service)
    student = _seed_user(pg_sessionmaker)
    _seed_weakness(pg_sessionmaker, student, topic="1 Motion", lost_marks=5)
    _auth_as(client, student, Role.student)
    plan = study_plan_service.generate(student, "0625")
    session_id = plan.sessions[0].id

    resp = client.post(f"/api/student/study-plan/sessions/{session_id}/complete")

    assert resp.status_code == 200
    body = resp.json()
    assert body["completedAt"] is not None

    # Inverse: before completion it was None (asserted via the plan view).
    assert plan.sessions[0].completed_at is None


def test_unknown_and_other_students_session_ids_are_byte_identical_404s(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    study_plan_service: StudyPlanService,
) -> None:
    _use_study_plan_service(client, study_plan_service)
    owner = _seed_user(pg_sessionmaker)
    other = _seed_user(pg_sessionmaker)
    _seed_weakness(pg_sessionmaker, owner, topic="1 Motion", lost_marks=5)
    plan = study_plan_service.generate(owner, "0625")
    session_id = plan.sessions[0].id

    _auth_as(client, other, Role.student)
    other_resp = client.post(f"/api/student/study-plan/sessions/{session_id}/complete")

    unknown_id = uuid.uuid4()
    unknown_resp = client.post(f"/api/student/study-plan/sessions/{unknown_id}/complete")

    assert other_resp.status_code == 404
    assert unknown_resp.status_code == 404
    assert other_resp.json() == unknown_resp.json()

    # Inverse: the real owner, on the exact same session id, gets a 200.
    _auth_as(client, owner, Role.student)
    owner_resp = client.post(f"/api/student/study-plan/sessions/{session_id}/complete")
    assert owner_resp.status_code == 200


def test_completion_is_idempotent(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    study_plan_service: StudyPlanService,
) -> None:
    _use_study_plan_service(client, study_plan_service)
    student = _seed_user(pg_sessionmaker)
    _seed_weakness(pg_sessionmaker, student, topic="1 Motion", lost_marks=5)
    _auth_as(client, student, Role.student)
    plan = study_plan_service.generate(student, "0625")
    session_id = plan.sessions[0].id

    first = client.post(f"/api/student/study-plan/sessions/{session_id}/complete").json()
    second = client.post(f"/api/student/study-plan/sessions/{session_id}/complete").json()

    assert first["completedAt"] == second["completedAt"]
    # Inverse: this is not just two identical Nones — it is a real timestamp.
    assert first["completedAt"] is not None


def test_malformed_session_id_is_422_not_500(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    study_plan_service: StudyPlanService,
) -> None:
    _use_study_plan_service(client, study_plan_service)
    student = _seed_user(pg_sessionmaker)
    _auth_as(client, student, Role.student)

    resp = client.post("/api/student/study-plan/sessions/not-a-uuid/complete")

    assert resp.status_code == 422
    # Inverse: a syntactically valid (but unknown) UUID is a 404, not a 422.
    valid_unknown_resp = client.post(f"/api/student/study-plan/sessions/{uuid.uuid4()}/complete")
    assert valid_unknown_resp.status_code == 404


# ---------------------------------------------------------------------------
# Role guard — every route, teacher and parent both rejected.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("role", [Role.teacher, Role.parent])
def test_get_route_rejects_non_students(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    study_plan_service: StudyPlanService,
    role: Role,
) -> None:
    _use_study_plan_service(client, study_plan_service)
    non_student = _seed_user(pg_sessionmaker, role)
    _auth_as(client, non_student, role)

    resp = client.get("/api/student/study-plan/0625")

    assert resp.status_code == 403
    # Inverse: the identical route, as a student, succeeds.
    student = _seed_user(pg_sessionmaker, Role.student)
    _auth_as(client, student, Role.student)
    assert client.get("/api/student/study-plan/0625").status_code == 200


@pytest.mark.parametrize("role", [Role.teacher, Role.parent])
def test_post_route_rejects_non_students(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    study_plan_service: StudyPlanService,
    role: Role,
) -> None:
    _use_study_plan_service(client, study_plan_service)
    non_student = _seed_user(pg_sessionmaker, role)
    _auth_as(client, non_student, role)

    resp = client.post("/api/student/study-plan", json={"subjectCode": "0625"})

    assert resp.status_code == 403
    # Inverse: the identical route, as a student, succeeds.
    student = _seed_user(pg_sessionmaker, Role.student)
    _auth_as(client, student, Role.student)
    assert client.post("/api/student/study-plan", json={"subjectCode": "0625"}).status_code == 201


@pytest.mark.parametrize("role", [Role.teacher, Role.parent])
def test_complete_route_rejects_non_students(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    study_plan_service: StudyPlanService,
    role: Role,
) -> None:
    _use_study_plan_service(client, study_plan_service)
    student = _seed_user(pg_sessionmaker, Role.student)
    _seed_weakness(pg_sessionmaker, student, topic="1 Motion", lost_marks=5)
    plan = study_plan_service.generate(student, "0625")
    session_id = plan.sessions[0].id

    non_student = _seed_user(pg_sessionmaker, role)
    _auth_as(client, non_student, role)
    resp = client.post(f"/api/student/study-plan/sessions/{session_id}/complete")

    assert resp.status_code == 403
    # Inverse: the identical route, as the owning student, succeeds.
    _auth_as(client, student, Role.student)
    ok = client.post(f"/api/student/study-plan/sessions/{session_id}/complete")
    assert ok.status_code == 200


# ---------------------------------------------------------------------------
# L9 · the week across subjects, moving a session, planning next week.
# ---------------------------------------------------------------------------


def _enrol(sm: sessionmaker[Session], student_id: uuid.UUID, code: str) -> None:
    with sm.begin() as session:
        if session.scalar(sa.select(Subject.id).where(Subject.code == code)) is None:
            session.add(Subject(code=code, name=f"Subject {code}"))
            session.flush()
        session.add(StudentSubjectEnrolment(user_id=student_id, subject_code=code))


def _use_profile_service(client: TestClient, sm: sessionmaker[Session]) -> None:
    client.app.dependency_overrides[get_student_profile_service] = (  # type: ignore[union-attr]
        lambda: StudentProfileService(sm)
    )


def test_week_lists_every_enrolled_subject_in_one_call(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    study_plan_service: StudyPlanService,
) -> None:
    _use_study_plan_service(client, study_plan_service)
    _use_profile_service(client, pg_sessionmaker)
    student = _seed_user(pg_sessionmaker)
    _enrol(pg_sessionmaker, student, "0625")
    _enrol(pg_sessionmaker, student, "0580")
    _seed_weakness(pg_sessionmaker, student, topic="1 Motion", lost_marks=5)
    study_plan_service.generate(student, "0625")
    study_plan_service.generate(student, "9709")  # a plan for a subject they are not enrolled in
    _auth_as(client, student, Role.student)

    resp = client.get("/api/student/study-plan")

    assert resp.status_code == 200
    body = resp.json()
    assert body["today"] == "2026-08-05"
    assert body["weekStart"] == "2026-08-03"
    assert body["weekEnd"] == "2026-08-09"
    assert [s["subjectCode"] for s in body["subjects"]] == ["0580", "0625"]
    maths, physics = body["subjects"]
    assert maths == {
        "subjectCode": "0580",
        "generated": False,
        "plan": None,
        "paperCount": 0,
        "weakTopics": [],
    }
    assert physics["generated"] is True
    assert physics["weakTopics"] == [{"topic": "1 Motion", "accuracyPct": 50}]
    session = physics["plan"]["sessions"][0]
    assert session["anyDay"] is False
    assert session["reason"] == {"kind": "marks_lost", "count": 5}
    # Inverse: the un-enrolled subject's plan is not in the week.
    assert "9709" not in [s["subjectCode"] for s in body["subjects"]]


def test_week_is_owner_scoped(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    study_plan_service: StudyPlanService,
) -> None:
    _use_study_plan_service(client, study_plan_service)
    _use_profile_service(client, pg_sessionmaker)
    owner = _seed_user(pg_sessionmaker)
    other = _seed_user(pg_sessionmaker)
    for uid in (owner, other):
        _enrol(pg_sessionmaker, uid, "0625")
    _seed_weakness(pg_sessionmaker, owner, topic="1 Motion", lost_marks=5)
    study_plan_service.generate(owner, "0625")

    _auth_as(client, other, Role.student)
    assert client.get("/api/student/study-plan").json()["subjects"][0]["plan"] is None
    # Inverse: the owner sees it.
    _auth_as(client, owner, Role.student)
    assert client.get("/api/student/study-plan").json()["subjects"][0]["plan"] is not None


@pytest.mark.parametrize("role", [Role.teacher, Role.parent])
def test_week_route_rejects_non_students(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    study_plan_service: StudyPlanService,
    role: Role,
) -> None:
    _use_study_plan_service(client, study_plan_service)
    _use_profile_service(client, pg_sessionmaker)
    _auth_as(client, _seed_user(pg_sessionmaker, role), role)

    assert client.get("/api/student/study-plan").status_code == 403
    # Inverse.
    _auth_as(client, _seed_user(pg_sessionmaker), Role.student)
    assert client.get("/api/student/study-plan").status_code == 200


def _student_with_plan(
    client: TestClient, sm: sessionmaker[Session], service: StudyPlanService
) -> tuple[uuid.UUID, str]:
    _use_study_plan_service(client, service)
    student = _seed_user(sm)
    _seed_weakness(sm, student, topic="1 Motion", lost_marks=5)
    plan = service.generate(student, "0625")
    _auth_as(client, student, Role.student)
    return student, str(plan.sessions[0].id)


def test_move_owner_gets_the_new_date(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    study_plan_service: StudyPlanService,
) -> None:
    _, session_id = _student_with_plan(client, pg_sessionmaker, study_plan_service)

    resp = client.post(
        f"/api/student/study-plan/sessions/{session_id}/move", json={"date": "2026-08-09"}
    )

    assert resp.status_code == 200
    assert resp.json()["date"] == "2026-08-09"
    assert resp.json()["reason"] is None
    sessions = client.get("/api/student/study-plan/0625").json()["plan"]["sessions"]
    assert next(s for s in sessions if s["id"] == session_id)["date"] == "2026-08-09"


def test_move_unknown_and_other_students_sessions_are_byte_identical_404s(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    study_plan_service: StudyPlanService,
) -> None:
    _, session_id = _student_with_plan(client, pg_sessionmaker, study_plan_service)
    unknown = client.post(
        f"/api/student/study-plan/sessions/{uuid.uuid4()}/move", json={"date": "2026-08-09"}
    )
    _auth_as(client, _seed_user(pg_sessionmaker), Role.student)
    foreign = client.post(
        f"/api/student/study-plan/sessions/{session_id}/move", json={"date": "2026-08-09"}
    )

    assert unknown.status_code == foreign.status_code == 404
    assert unknown.content == foreign.content


def test_move_refusals_carry_a_machine_readable_code(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    study_plan_service: StudyPlanService,
) -> None:
    _, session_id = _student_with_plan(client, pg_sessionmaker, study_plan_service)
    url = f"/api/student/study-plan/sessions/{session_id}/move"

    past = client.post(url, json={"date": "2026-08-04"})
    assert past.status_code == 422
    assert past.json()["detail"]["code"] == "past_day"

    far = client.post(url, json={"date": "2026-09-30"})
    assert far.status_code == 422
    assert far.json()["detail"]["code"] == "outside_week"

    client.post(f"/api/student/study-plan/sessions/{session_id}/complete")
    done = client.post(url, json={"date": "2026-08-09"})
    assert done.status_code == 409
    assert done.json()["detail"]["code"] == "completed"


def test_move_with_a_malformed_id_or_date_is_422(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    study_plan_service: StudyPlanService,
) -> None:
    _, session_id = _student_with_plan(client, pg_sessionmaker, study_plan_service)

    bad_id = client.post(
        "/api/student/study-plan/sessions/not-a-uuid/move", json={"date": "2026-08-09"}
    )
    bad_date = client.post(
        f"/api/student/study-plan/sessions/{session_id}/move", json={"date": "Friday"}
    )

    assert bad_id.status_code == 422
    assert bad_date.status_code == 422


@pytest.mark.parametrize("role", [Role.teacher, Role.parent])
def test_move_route_rejects_non_students(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    study_plan_service: StudyPlanService,
    role: Role,
) -> None:
    _, session_id = _student_with_plan(client, pg_sessionmaker, study_plan_service)
    url = f"/api/student/study-plan/sessions/{session_id}/move"
    _auth_as(client, _seed_user(pg_sessionmaker, role), role)

    assert client.post(url, json={"date": "2026-08-09"}).status_code == 403


def test_post_week_next_plans_next_week_without_touching_this_one(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    study_plan_service: StudyPlanService,
) -> None:
    _use_study_plan_service(client, study_plan_service)
    student = _seed_user(pg_sessionmaker)
    _seed_weakness(pg_sessionmaker, student, topic="1 Motion", lost_marks=5)
    _auth_as(client, student, Role.student)

    nxt = client.post("/api/student/study-plan", json={"subjectCode": "0625", "week": "next"})

    assert nxt.status_code == 201
    assert nxt.json()["weekStart"] == "2026-08-10"
    assert client.get("/api/student/study-plan/0625").json()["generated"] is False
    # Inverse: the default is this week.
    cur = client.post("/api/student/study-plan", json={"subjectCode": "0625"})
    assert cur.json()["weekStart"] == "2026-08-03"
    # And an unknown value is refused.
    bad = client.post("/api/student/study-plan", json={"subjectCode": "0625", "week": "later"})
    assert bad.status_code == 422


def test_complete_still_returns_the_session_with_the_new_keys(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    study_plan_service: StudyPlanService,
) -> None:
    _, session_id = _student_with_plan(client, pg_sessionmaker, study_plan_service)

    resp = client.post(f"/api/student/study-plan/sessions/{session_id}/complete")

    assert resp.status_code == 200
    assert resp.json()["completedAt"] is not None
    assert resp.json()["anyDay"] is False
    assert resp.json()["reason"] is None
