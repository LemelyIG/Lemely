"""Route tests for the placement-test endpoints (``/api/student/placement/*``, P4.4 chunk B-4).

Self-contained (mirrors ``tests/test_web_student_quiz.py``) — a throwaway
Postgres DB per test, skipped cleanly when unreachable. Covers the wire
payload shapes, the 409-carries-the-availability-payload contract (D4.6 §4),
and the cross-tenant 403/no-body-leakage split on the result route (D4.6 §7).
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
from lemely.db.models import User
from lemely.db.models.enums import DifficultySource, QuestionSource, Role
from lemely.db.placement_repo import PlacementService
from lemely.db.question_bank_repo import NewBankQuestion, QuestionBankService
from lemely.runtime.config import DatabaseSettings
from lemely.web import create_app
from lemely.web.deps import AuthContext, get_auth_context, get_placement_service

if TYPE_CHECKING:
    from collections.abc import Iterator

_PHYSICS_TOPICS = [
    "1 Motion, forces and energy",
    "2 Thermal physics",
    "3 Waves",
    "4 Electricity and magnetism",
]


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
def placement_service(pg_sessionmaker: sessionmaker[Session]) -> PlacementService:
    return PlacementService(pg_sessionmaker)


def _use_placement_service(client: TestClient, service: PlacementService) -> None:
    client.app.dependency_overrides[get_placement_service] = lambda: service  # type: ignore[union-attr]


def _auth_as(client: TestClient, user_id: uuid.UUID, role: Role) -> None:
    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(user_id), role=role.value
    )


def _seed_user(sm: sessionmaker[Session], role: Role) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role))
    return uid


def _seed_placement_bank(sm: sessionmaker[Session], *, per_topic: int = 6) -> None:
    service = QuestionBankService(sm)
    rows = []
    ref = 1
    for topic in _PHYSICS_TOPICS:
        for _ in range(per_topic):
            rows.append(
                NewBankQuestion(
                    subject_code="0625",
                    source=QuestionSource.past_paper,
                    difficulty="standard",
                    difficulty_source=DifficultySource.inferred_from_marks,
                    question_type="mcq",
                    prompt=f"Question {ref}",
                    total_marks=2,
                    topic=topic,
                    source_question_id=f"0625_s23_qp_41#{ref}",
                    mcq_options=["A", "B", "C", "D"],
                    mcq_answer="B",
                )
            )
            ref += 1
    service.add_questions(rows)
    service.link_past_paper_rows()


# ---------------------------------------------------------------------------
# Availability.
# ---------------------------------------------------------------------------


def test_availability_route_shape_when_available(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    placement_service: PlacementService,
) -> None:
    _use_placement_service(client, placement_service)
    student = _seed_user(pg_sessionmaker, Role.student)
    _seed_placement_bank(pg_sessionmaker)
    _auth_as(client, student, Role.student)

    resp = client.get("/api/student/placement/0625/availability")

    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is True
    assert body["reason"] is None
    assert body["topicCount"] >= 4
    assert 12.0 <= body["estimatedMinutes"] <= 18.0


def test_availability_route_shape_when_unavailable(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    placement_service: PlacementService,
) -> None:
    _use_placement_service(client, placement_service)
    student = _seed_user(pg_sessionmaker, Role.student)
    _auth_as(client, student, Role.student)

    resp = client.get("/api/student/placement/0580/availability")

    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "available": False,
        "reason": "no_questions",
        "questionCount": 0,
        "topicCount": 0,
        "estimatedMinutes": 0.0,
    }


# ---------------------------------------------------------------------------
# Create — 201, and the 409-equals-availability contract (D4.6 §4).
# ---------------------------------------------------------------------------


def test_create_route_returns_201_with_the_assembled_counts(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    placement_service: PlacementService,
) -> None:
    _use_placement_service(client, placement_service)
    student = _seed_user(pg_sessionmaker, Role.student)
    _seed_placement_bank(pg_sessionmaker)
    _auth_as(client, student, Role.student)

    resp = client.post("/api/student/placement", json={"subjectCode": "0625"})

    assert resp.status_code == 201
    body = resp.json()
    assert uuid.UUID(body["assignmentId"])
    assert uuid.UUID(body["quizId"])
    assert body["questionCount"] >= 6
    assert body["topicCount"] >= 4


def test_create_route_409_payload_equals_the_availability_payload(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    placement_service: PlacementService,
) -> None:
    """D4.6 §4: the 409 on create-when-unavailable carries the identical
    payload ``GET .../availability`` would have returned — not a bare string."""
    _use_placement_service(client, placement_service)
    student = _seed_user(pg_sessionmaker, Role.student)
    _auth_as(client, student, Role.student)

    availability_resp = client.get("/api/student/placement/0580/availability")
    create_resp = client.post("/api/student/placement", json={"subjectCode": "0580"})

    assert availability_resp.status_code == 200
    assert create_resp.status_code == 409
    assert create_resp.json()["detail"] == availability_resp.json()


# ---------------------------------------------------------------------------
# Result — cross-tenant 403, no body leakage (D4.6 §7).
# ---------------------------------------------------------------------------


def test_result_route_cross_tenant_is_403_with_no_body_leakage(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    placement_service: PlacementService,
) -> None:
    owner = _seed_user(pg_sessionmaker, Role.student)
    other = _seed_user(pg_sessionmaker, Role.student)
    _seed_placement_bank(pg_sessionmaker)

    _auth_as(client, owner, Role.student)
    _use_placement_service(client, placement_service)
    created = placement_service.create(owner, "0625")

    _auth_as(client, other, Role.student)
    resp = client.get(f"/api/student/placement/{created.assignment_id}/result")

    assert resp.status_code == 403
    body = resp.json()
    assert set(body) == {"detail"}
    assert isinstance(body["detail"], str)


def test_result_route_unknown_assignment_is_404(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    placement_service: PlacementService,
) -> None:
    _use_placement_service(client, placement_service)
    student = _seed_user(pg_sessionmaker, Role.student)
    _auth_as(client, student, Role.student)

    resp = client.get(f"/api/student/placement/{uuid.uuid4()}/result")

    assert resp.status_code == 404


def test_result_route_before_marking(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    placement_service: PlacementService,
) -> None:
    student = _seed_user(pg_sessionmaker, Role.student)
    _seed_placement_bank(pg_sessionmaker)
    _use_placement_service(client, placement_service)
    created = placement_service.create(student, "0625")

    _auth_as(client, student, Role.student)
    resp = client.get(f"/api/student/placement/{created.assignment_id}/result")

    assert resp.status_code == 200
    body = resp.json()
    assert body["marked"] is False
    assert body["awardedMarks"] is None
    assert body["questions"] == []
    assert body["topicBreakdown"] == []
