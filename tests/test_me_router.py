"""HTTP-layer tests for ``/api/me/student-profile/*`` (P4.3 chunk B, D4.5).

Exercises the student-onboarding routes in ``lemely.web.routers.me`` against
a real :class:`StudentProfileService` bound to a throwaway Postgres database
(mirrors ``tests/test_web_classes.py``'s fixture shape). Service-level
behaviour (upsert semantics, range validation, ownership checks) is proven
in ``tests/test_student_profile_repo.py``; this file proves the HTTP layer —
DTO field names, status-code mapping, and — the gate that matters most here
— that there is no student-id path parameter anywhere on this router, so
cross-student access is structurally impossible rather than merely
permission-checked.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.db.base import Base
from lemely.db.models import Subject, User
from lemely.db.models.enums import Role
from lemely.db.student_profile_repo import StudentProfileService
from lemely.runtime.config import DatabaseSettings
from lemely.web import create_app
from lemely.web.deps import AuthContext, get_auth_context, get_student_profile_service

if TYPE_CHECKING:
    from collections.abc import Iterator


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
def service(pg_sessionmaker: sessionmaker[Session]) -> StudentProfileService:
    return StudentProfileService(pg_sessionmaker)


@pytest.fixture
def client(
    pg_sessionmaker: sessionmaker[Session], service: StudentProfileService
) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_student_profile_service] = lambda: service
    _seed_subject(pg_sessionmaker, "0625")
    _seed_subject(pg_sessionmaker, "0580")
    yield TestClient(app)
    app.dependency_overrides.clear()


def _seed_user(sm: sessionmaker[Session], role: Role = Role.student) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role))
    return uid


def _seed_subject(sm: sessionmaker[Session], code: str) -> str:
    with sm.begin() as session:
        session.add(Subject(code=code, name="Physics"))
    return code


def _as(client: TestClient, user_id: uuid.UUID, role: Role) -> TestClient:
    """Point ``get_auth_context`` at ``user_id``/``role`` for subsequent calls.

    Mutates the shared ``app.dependency_overrides`` (mirrors every other
    ``test_web_*.py`` file's pattern of overriding ``get_auth_context``
    per-test); the ``client`` fixture clears overrides on teardown.
    """
    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(user_id), role=role.value
    )
    return client


# ---------------------------------------------------------------------------
# Authz matrix — the gate that matters most (D4.5 §6)
# ---------------------------------------------------------------------------


def test_teacher_role_forbidden_from_every_new_route(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    _as(client, teacher, Role.teacher)

    assert client.get("/api/me/student-profile").status_code == 403
    assert client.patch("/api/me/student-profile", json={}).status_code == 403
    assert (
        client.put("/api/me/student-profile/enrolments", json={"enrolments": []}).status_code == 403
    )
    assert (
        client.put(
            "/api/me/student-profile/enrolments/0625/confidence-ratings",
            json={"ratings": {}},
        ).status_code
        == 403
    )
    assert client.post("/api/me/student-profile/complete-onboarding").status_code == 403


def test_student_b_never_sees_student_as_profile_or_enrolments(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    student_a = _seed_user(pg_sessionmaker)
    student_b = _seed_user(pg_sessionmaker)

    _as(client, student_a, Role.student)
    client.patch("/api/me/student-profile", json={"schoolName": "A's School"})
    client.put(
        "/api/me/student-profile/enrolments",
        json={"enrolments": [{"subjectCode": "0625", "targetGrade": "A"}]},
    )

    _as(client, student_b, Role.student)
    resp = client.get("/api/me/student-profile")
    assert resp.status_code == 200
    body = resp.json()
    # B's own (never-touched) profile: no data leaked from A.
    assert body["profile"]["schoolName"] is None
    assert body["enrolments"] == []


def test_student_b_put_enrolments_does_not_touch_student_a(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    student_a = _seed_user(pg_sessionmaker)
    student_b = _seed_user(pg_sessionmaker)

    _as(client, student_a, Role.student)
    client.put(
        "/api/me/student-profile/enrolments",
        json={"enrolments": [{"subjectCode": "0625", "targetGrade": "A"}]},
    )

    _as(client, student_b, Role.student)
    client.put(
        "/api/me/student-profile/enrolments",
        json={"enrolments": [{"subjectCode": "0625", "targetGrade": "C"}]},
    )

    _as(client, student_a, Role.student)
    resp = client.get("/api/me/student-profile")
    enrolments = resp.json()["enrolments"]
    assert len(enrolments) == 1
    assert enrolments[0]["targetGrade"] == "A"  # untouched by B's call


def test_identity_comes_from_the_token_never_the_payload(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    """A smuggled owner id in the body is rejected, not honoured or quietly dropped.

    P4.10 chunk D (D4.22) retired ``POST /api/student/onboarding`` and with it
    ``test_onboarding_uses_token_identity``, the only test that pinned
    *identity is the token, never the payload* on the onboarding surface. Its
    replacements in ``tests/test_authz_matrix.py`` are role guards (401/403)
    only — those stay green while this guarantee quietly stops being proven,
    which is the same class of gap as chunk D's own trap 1, one layer down.

    The two halves matter separately: "the field was ignored" and "the request
    was rejected" look identical to a test that only reads back the stored
    value. Under ``ApiModel``'s ``extra="forbid"`` this surface does the
    stricter of the two — 422 — and the inverse pair proves nothing was
    written for either party before the rejection.
    """
    victim = _seed_user(pg_sessionmaker)
    attacker = _seed_user(pg_sessionmaker)
    _as(client, victim, Role.student)

    smuggled_patch = client.patch(
        "/api/me/student-profile",
        json={"studentId": str(attacker), "schoolName": "Attacker's School"},
    )
    smuggled_put = client.put(
        "/api/me/student-profile/enrolments",
        json={
            "studentId": str(attacker),
            "enrolments": [{"subjectCode": "0625", "targetGrade": "A"}],
        },
    )

    assert smuggled_patch.status_code == 422
    assert smuggled_put.status_code == 422

    # Inverse 1: rejected outright, so nothing landed on the caller either.
    victim_body = client.get("/api/me/student-profile").json()
    assert victim_body["profile"]["schoolName"] is None
    assert victim_body["enrolments"] == []

    # Inverse 2: and nothing landed on the id that was smuggled.
    _as(client, attacker, Role.student)
    attacker_body = client.get("/api/me/student-profile").json()
    assert attacker_body["profile"]["schoolName"] is None
    assert attacker_body["enrolments"] == []

    # Inverse 3: the same calls without the smuggled id succeed, so the 422 is
    # the extra field and not something else wrong with these payloads.
    _as(client, victim, Role.student)
    assert client.patch("/api/me/student-profile", json={"schoolName": "Real"}).status_code == 200
    assert (
        client.put(
            "/api/me/student-profile/enrolments",
            json={"enrolments": [{"subjectCode": "0625", "targetGrade": "A"}]},
        ).status_code
        == 200
    )


# ---------------------------------------------------------------------------
# GET / PATCH profile
# ---------------------------------------------------------------------------


def test_get_student_profile_new_student_reads_as_all_null(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    student = _seed_user(pg_sessionmaker)
    _as(client, student, Role.student)

    resp = client.get("/api/me/student-profile")

    assert resp.status_code == 200
    body = resp.json()
    assert body["profile"] == {
        "qualificationLevel": None,
        "gradeLevel": None,
        "schoolName": None,
        "hasExternalLessons": None,
        "weeklyStudyHours": None,
        "onboardingCompletedAt": None,
        "leaderboardOptOut": False,
    }
    assert body["enrolments"] == []


def test_patch_student_profile_updates_and_echoes(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    student = _seed_user(pg_sessionmaker)
    _as(client, student, Role.student)

    resp = client.patch(
        "/api/me/student-profile",
        json={"qualificationLevel": "igcse", "weeklyStudyHours": 12},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["qualificationLevel"] == "igcse"
    assert body["weeklyStudyHours"] == 12


def test_patch_student_profile_weekly_hours_out_of_range_is_422(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    student = _seed_user(pg_sessionmaker)
    _as(client, student, Role.student)

    resp = client.patch("/api/me/student-profile", json={"weeklyStudyHours": 81})

    assert resp.status_code == 422


def test_patch_student_profile_unknown_qualification_level_is_422(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    student = _seed_user(pg_sessionmaker)
    _as(client, student, Role.student)

    resp = client.patch("/api/me/student-profile", json={"qualificationLevel": "phd"})

    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# PUT enrolments
# ---------------------------------------------------------------------------


def test_put_enrolments_upserts_each_item(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    student = _seed_user(pg_sessionmaker)
    _as(client, student, Role.student)

    resp = client.put(
        "/api/me/student-profile/enrolments",
        json={
            "enrolments": [
                {
                    "subjectCode": "0625",
                    "targetGrade": "A",
                    "sessionMonth": "may_june",
                    "sessionYear": 2027,
                    "papers": [2, 4],
                }
            ]
        },
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body) == 1
    assert body[0]["subjectCode"] == "0625"
    assert body[0]["targetGrade"] == "A"
    assert body[0]["sessionMonth"] == "may_june"
    assert body[0]["papers"] == [2, 4]


def test_put_enrolments_round_trips_qualification_level(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    """A per-subject qualificationLevel in the PUT body is stored and echoed back."""
    student = _seed_user(pg_sessionmaker)
    _as(client, student, Role.student)

    resp = client.put(
        "/api/me/student-profile/enrolments",
        json={
            "enrolments": [
                {"subjectCode": "0625", "qualificationLevel": "igcse", "papers": []},
            ]
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body[0]["qualificationLevel"] == "igcse"

    # A second PUT with the level omitted-as-None clears it (full-desired-state
    # semantics, same as targetGrade/sessionMonth on this endpoint).
    resp = client.put(
        "/api/me/student-profile/enrolments",
        json={"enrolments": [{"subjectCode": "0625", "qualificationLevel": None, "papers": []}]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body[0]["qualificationLevel"] is None


def test_put_enrolments_unknown_target_grade_is_422(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    student = _seed_user(pg_sessionmaker)
    _as(client, student, Role.student)

    resp = client.put(
        "/api/me/student-profile/enrolments",
        json={"enrolments": [{"subjectCode": "0625", "targetGrade": "Z"}]},
    )

    assert resp.status_code == 422


def test_put_enrolments_unknown_subject_code_is_422(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    student = _seed_user(pg_sessionmaker)
    _as(client, student, Role.student)

    resp = client.put(
        "/api/me/student-profile/enrolments",
        json={"enrolments": [{"subjectCode": "not-a-real-subject"}]},
    )

    assert resp.status_code == 422


def test_put_enrolments_does_not_delete_omitted_subjects(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    student = _seed_user(pg_sessionmaker)
    _as(client, student, Role.student)
    client.put(
        "/api/me/student-profile/enrolments",
        json={"enrolments": [{"subjectCode": "0625", "targetGrade": "A"}]},
    )

    # A second PUT that only mentions a different subject must not delete
    # the first subject's enrolment (upsert-each-item, not full-replace).
    resp = client.put(
        "/api/me/student-profile/enrolments",
        json={"enrolments": [{"subjectCode": "0580", "targetGrade": "B"}]},
    )

    assert resp.status_code == 200
    all_enrolments = client.get("/api/me/student-profile").json()["enrolments"]
    subject_codes = {e["subjectCode"] for e in all_enrolments}
    assert subject_codes == {"0625", "0580"}


# ---------------------------------------------------------------------------
# PUT confidence ratings
# ---------------------------------------------------------------------------


def test_put_confidence_ratings_success(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    student = _seed_user(pg_sessionmaker)
    _as(client, student, Role.student)
    client.put(
        "/api/me/student-profile/enrolments",
        json={"enrolments": [{"subjectCode": "0625"}]},
    )

    resp = client.put(
        "/api/me/student-profile/enrolments/0625/confidence-ratings",
        json={"ratings": {"4.3 Electric circuits": 3, "4.1 Topic": 5}},
    )

    assert resp.status_code == 200, resp.text
    by_topic = {r["topic"]: r["rating"] for r in resp.json()}
    assert by_topic == {"4.3 Electric circuits": 3, "4.1 Topic": 5}


def test_put_confidence_ratings_out_of_range_is_422(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    student = _seed_user(pg_sessionmaker)
    _as(client, student, Role.student)
    client.put(
        "/api/me/student-profile/enrolments",
        json={"enrolments": [{"subjectCode": "0625"}]},
    )

    resp = client.put(
        "/api/me/student-profile/enrolments/0625/confidence-ratings",
        json={"ratings": {"Topic A": 0, "Topic B": 6}},
    )

    assert resp.status_code == 422


def test_put_confidence_ratings_no_enrolment_is_404(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    student = _seed_user(pg_sessionmaker)
    _as(client, student, Role.student)

    resp = client.put(
        "/api/me/student-profile/enrolments/0625/confidence-ratings",
        json={"ratings": {"Topic A": 3}},
    )

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST complete-onboarding
# ---------------------------------------------------------------------------


def test_post_complete_onboarding_sets_timestamp(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    student = _seed_user(pg_sessionmaker)
    _as(client, student, Role.student)

    resp = client.post("/api/me/student-profile/complete-onboarding")

    assert resp.status_code == 200, resp.text
    assert resp.json()["onboardingCompletedAt"] is not None
