"""Route tests for the practice-generator endpoints (``/api/student/practice/*``, P4.5).

Self-contained (mirrors ``tests/test_web_placement.py``) — a throwaway
Postgres DB per test, skipped cleanly when unreachable. Covers wire payload
shapes, the honesty path (shortfall still 201, empty pool 409 carrying the
preview payload), the answer-leak-free export payload, and cross-tenant
403/no-body-leakage on every new route.
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
from lemely.db.practice_repo import PracticeRequest, PracticeService
from lemely.db.question_bank_repo import NewBankQuestion, QuestionBankService
from lemely.runtime.config import DatabaseSettings
from lemely.web import create_app
from lemely.web.deps import AuthContext, get_auth_context, get_practice_service

if TYPE_CHECKING:
    from collections.abc import Iterator


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
def practice_service(pg_sessionmaker: sessionmaker[Session]) -> PracticeService:
    return PracticeService(pg_sessionmaker)


def _use_practice_service(client: TestClient, service: PracticeService) -> None:
    client.app.dependency_overrides[get_practice_service] = lambda: service  # type: ignore[union-attr]


def _auth_as(client: TestClient, user_id: uuid.UUID, role: Role) -> None:
    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(user_id), role=role.value
    )


def _seed_user(sm: sessionmaker[Session], role: Role = Role.student) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role))
    return uid


def _seed_bank(sm: sessionmaker[Session], *, topic: str = "1 Motion", per_topic: int = 6) -> None:
    service = QuestionBankService(sm)
    rows = [
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
        for ref in range(1, per_topic + 1)
    ]
    service.add_questions(rows)
    service.link_past_paper_rows()


# ---------------------------------------------------------------------------
# Preview.
# ---------------------------------------------------------------------------


def test_preview_route_shape_when_fully_available(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], practice_service: PracticeService
) -> None:
    _use_practice_service(client, practice_service)
    student = _seed_user(pg_sessionmaker)
    _seed_bank(pg_sessionmaker, per_topic=6)
    _auth_as(client, student, Role.student)

    resp = client.get(
        "/api/student/practice/0625/preview", params={"count": 4, "topics": ["1 Motion"]}
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is True
    assert body["reason"] is None
    assert body["availableCount"] == 6
    assert body["requestedCount"] == 4
    assert body["topics"] == ["1 Motion"]


def test_preview_route_shape_when_empty(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], practice_service: PracticeService
) -> None:
    _use_practice_service(client, practice_service)
    student = _seed_user(pg_sessionmaker)
    _auth_as(client, student, Role.student)

    resp = client.get("/api/student/practice/0580/preview", params={"count": 10})

    assert resp.status_code == 200
    assert resp.json() == {
        "available": False,
        "reason": "no_questions",
        "requestedCount": 10,
        "availableCount": 0,
        "topics": [],
    }


def test_preview_route_rejects_an_unknown_difficulty_band(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], practice_service: PracticeService
) -> None:
    _use_practice_service(client, practice_service)
    student = _seed_user(pg_sessionmaker)
    _auth_as(client, student, Role.student)

    resp = client.get(
        "/api/student/practice/0625/preview",
        params={"count": 10, "difficulty_bands": ["impossible"]},
    )

    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Create — 201 honesty path, and the 409-equals-preview contract.
# ---------------------------------------------------------------------------


def test_create_route_returns_201_with_a_shortfall_reason(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], practice_service: PracticeService
) -> None:
    _use_practice_service(client, practice_service)
    student = _seed_user(pg_sessionmaker)
    _seed_bank(pg_sessionmaker, per_topic=3)
    _auth_as(client, student, Role.student)

    resp = client.post(
        "/api/student/practice",
        json={"subjectCode": "0625", "count": 20, "topics": ["1 Motion"]},
    )

    assert resp.status_code == 201
    body = resp.json()
    assert uuid.UUID(body["assignmentId"])
    assert uuid.UUID(body["quizId"])
    assert body["questionCount"] == 3
    assert body["requestedCount"] == 20
    assert body["reason"] == "insufficient_pool"


def test_create_route_409_payload_equals_the_preview_payload(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], practice_service: PracticeService
) -> None:
    _use_practice_service(client, practice_service)
    student = _seed_user(pg_sessionmaker)
    _auth_as(client, student, Role.student)

    preview_resp = client.get("/api/student/practice/0580/preview", params={"count": 10})
    create_resp = client.post("/api/student/practice", json={"subjectCode": "0580", "count": 10})

    assert preview_resp.status_code == 200
    assert create_resp.status_code == 409
    assert create_resp.json()["detail"] == preview_resp.json()


# ---------------------------------------------------------------------------
# Export — answer-free payload, cross-tenant 403/no-body-leakage.
# ---------------------------------------------------------------------------


def test_export_route_never_returns_marking_material(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], practice_service: PracticeService
) -> None:
    student = _seed_user(pg_sessionmaker)
    _seed_bank(pg_sessionmaker, per_topic=3)
    created = practice_service.create(
        student, PracticeRequest(subject_code="0625", count=3, topics=("1 Motion",))
    )

    _auth_as(client, student, Role.student)
    _use_practice_service(client, practice_service)
    resp = client.get(f"/api/student/practice/{created.assignment_id}/export")

    assert resp.status_code == 200
    body = resp.json()
    assert body["questions"]
    for q in body["questions"]:
        assert "modelAnswer" not in q
        assert "markSchemePoints" not in q
        assert "mcqAnswer" not in q


def test_export_route_cross_tenant_is_403_with_no_body_leakage(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], practice_service: PracticeService
) -> None:
    owner = _seed_user(pg_sessionmaker)
    other = _seed_user(pg_sessionmaker)
    _seed_bank(pg_sessionmaker, per_topic=3)

    _auth_as(client, owner, Role.student)
    _use_practice_service(client, practice_service)
    created = practice_service.create(
        owner, PracticeRequest(subject_code="0625", count=3, topics=("1 Motion",))
    )

    _auth_as(client, other, Role.student)
    resp = client.get(f"/api/student/practice/{created.assignment_id}/export")

    assert resp.status_code == 403
    body = resp.json()
    assert set(body) == {"detail"}
    assert isinstance(body["detail"], str)


def test_export_route_unknown_assignment_is_404(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], practice_service: PracticeService
) -> None:
    _use_practice_service(client, practice_service)
    student = _seed_user(pg_sessionmaker)
    _auth_as(client, student, Role.student)

    resp = client.get(f"/api/student/practice/{uuid.uuid4()}/export")

    assert resp.status_code == 404
