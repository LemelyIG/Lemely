"""Tests for `total` on ``GET /api/teacher/review`` (C3d, Task 9).

Self-contained (mirrors ``tests/test_web_review.py``) — a throwaway Postgres
DB per test, skipped cleanly when unreachable. Proves `total` counts every
item matching the request's filters (ignoring `limit`/`cursor`), respects the
SAME filters as the paginated `items` list, and — the security-relevant
part — never leaks across tenants: a different teacher gets `total == 0`
even though items exist, because `ReviewService.list_queue` scopes by the
caller's own visible students exactly like the paginated query does.
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

from lemely.core.schemas import (
    AccuracyReport,
    ConfidenceBand,
    CorrectedQuestion,
    CorrectionResult,
    ExamMetadata,
    GradePrediction,
    WeaknessReport,
)
from lemely.db.attempt_repo import AttemptRepository
from lemely.db.base import Base
from lemely.db.class_repo import ClassService
from lemely.db.models import User
from lemely.db.models.enums import Role
from lemely.db.review_repo import ReviewService
from lemely.runtime.config import DatabaseSettings
from lemely.web import create_app
from lemely.web.deps import AuthContext, get_auth_context, get_review_service

if TYPE_CHECKING:
    from collections.abc import Iterator


# ---------------------------------------------------------------------------
# Fixtures (mirrors tests/test_web_review.py).
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
def class_service(pg_sessionmaker: sessionmaker[Session]) -> ClassService:
    return ClassService(pg_sessionmaker)


@pytest.fixture
def review_service(
    pg_sessionmaker: sessionmaker[Session], class_service: ClassService
) -> ReviewService:
    return ReviewService(pg_sessionmaker, class_service)


def _use_review_service(client: TestClient, review_service: ReviewService) -> None:
    client.app.dependency_overrides[get_review_service] = lambda: review_service  # type: ignore[union-attr]


def _auth_as(client: TestClient, user_id: uuid.UUID, role: Role) -> None:
    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(user_id), role=role.value
    )


def _seed_user(
    sm: sessionmaker[Session], role: Role = Role.teacher, display_name: str | None = None
) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role, display_name=display_name))
    return uid


def _metadata() -> ExamMetadata:
    return ExamMetadata(
        subject_code="9999",
        paper_number=1,
        paper_variant=1,
        session_month="May/June",
        session_year=2020,
    )


def _report(question_id: str) -> AccuracyReport:
    question = CorrectedQuestion(
        question_id=question_id,
        awarded_marks=0,
        maximum_marks=2,
        confidence=ConfidenceBand.LOW,
        confidence_score=0.3,
        needs_teacher_review=True,
        student_answer=f"answer-{question_id}",
        expected_answer=f"expected-{question_id}",
        topic="Waves",
        marker_source="ai",
        matched_point_ids=[],
    )
    correction = CorrectionResult(metadata=_metadata(), questions=[question])
    awarded, maximum = correction.awarded_marks, correction.maximum_marks
    pct = round((awarded / maximum) * 100.0, 2) if maximum else 0.0
    prediction = GradePrediction(
        awarded_marks=awarded,
        maximum_marks=maximum,
        percentage=pct,
        grade="U",
        confidence=ConfidenceBand.LOW,
        needs_teacher_review=correction.needs_teacher_review,
        boundary_source="global_default",
    )
    return AccuracyReport(
        correction=correction, weaknesses=WeaknessReport(weak_areas=[]), grade_prediction=prediction
    )


def _flag_item(
    pg_sessionmaker: sessionmaker[Session], student_id: uuid.UUID, question_id: str
) -> None:
    AttemptRepository(pg_sessionmaker).persist_correction(
        user_id=str(student_id), report=_report(question_id)
    )


# ---------------------------------------------------------------------------
# `total` behaviour.
# ---------------------------------------------------------------------------


def test_total_counts_every_open_item_across_two_classes(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
) -> None:
    """3 open items, unfiltered → total == 3, and items/total agree."""
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    class_a = class_service.create_class(teacher, "Physics 10A")
    class_b = class_service.create_class(teacher, "Physics 10B")
    assert class_a.join_code is not None
    assert class_b.join_code is not None

    alice = _seed_user(pg_sessionmaker, Role.student, display_name="Alice")
    bob = _seed_user(pg_sessionmaker, Role.student, display_name="Bob")
    cara = _seed_user(pg_sessionmaker, Role.student, display_name="Cara")
    class_service.join_by_code(alice, class_a.join_code)
    class_service.join_by_code(bob, class_a.join_code)
    class_service.join_by_code(cara, class_b.join_code)

    _flag_item(pg_sessionmaker, alice, "1")
    _flag_item(pg_sessionmaker, bob, "1")
    _flag_item(pg_sessionmaker, cara, "1")

    _use_review_service(client, review_service)
    _auth_as(client, teacher, Role.teacher)

    resp = client.get("/api/teacher/review")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 3
    assert len(body["items"]) == 3


def test_total_respects_the_same_filters_as_the_page(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
) -> None:
    """A `class_id` filter that narrows the page also narrows `total`."""
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    class_a = class_service.create_class(teacher, "Physics 10A")
    class_b = class_service.create_class(teacher, "Physics 10B")
    assert class_a.join_code is not None
    assert class_b.join_code is not None

    alice = _seed_user(pg_sessionmaker, Role.student, display_name="Alice")
    bob = _seed_user(pg_sessionmaker, Role.student, display_name="Bob")
    cara = _seed_user(pg_sessionmaker, Role.student, display_name="Cara")
    class_service.join_by_code(alice, class_a.join_code)
    class_service.join_by_code(bob, class_a.join_code)
    class_service.join_by_code(cara, class_b.join_code)

    _flag_item(pg_sessionmaker, alice, "1")
    _flag_item(pg_sessionmaker, bob, "1")
    _flag_item(pg_sessionmaker, cara, "1")

    _use_review_service(client, review_service)
    _auth_as(client, teacher, Role.teacher)

    resp = client.get("/api/teacher/review", params={"class_id": str(class_b.class_id)})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["studentDisplayName"] == "Cara"


def test_total_is_tenant_scoped_like_the_list(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
) -> None:
    """A different teacher, with no visibility into these students, gets
    `total == 0` — never a leak of another tenant's queue depth (the
    security-relevant case: `total` must use the exact same `teacher_id`
    scoping as the existing `items` query, not a broader/unscoped count)."""
    owner = _seed_user(pg_sessionmaker, Role.teacher)
    other_teacher = _seed_user(pg_sessionmaker, Role.teacher)
    owner_class = class_service.create_class(owner, "Physics 10A")
    assert owner_class.join_code is not None
    student = _seed_user(pg_sessionmaker, Role.student, display_name="Alice")
    class_service.join_by_code(student, owner_class.join_code)
    _flag_item(pg_sessionmaker, student, "1")

    _use_review_service(client, review_service)
    _auth_as(client, other_teacher, Role.teacher)

    resp = client.get("/api/teacher/review")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0
    assert body["items"] == []
