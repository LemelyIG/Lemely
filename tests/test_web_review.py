"""Route tests for the review-queue endpoints (``lemely.web.routers.review``, P3.4).

Self-contained (mirrors ``tests/test_class_repo.py``/the P3.3 section of
``tests/test_web_teacher.py``) — a throwaway Postgres DB per test, skipped
cleanly when unreachable. Covers payload shape for each of the five routes
and the full authz matrix: a teacher must never see, read, resolve, dismiss,
or bulk-approve another teacher's review item.
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
from lemely.db.models.ops import ReviewQueueItem
from lemely.db.review_repo import ReviewService
from lemely.runtime.config import DatabaseSettings
from lemely.web import create_app
from lemely.web.deps import AuthContext, get_auth_context, get_review_service

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


def _question(
    question_id: str,
    *,
    awarded: int,
    maximum: int,
    confidence_score: float = 0.3,
    needs_review: bool = True,
    plagiarism_flagged: bool = False,
) -> CorrectedQuestion:
    return CorrectedQuestion(
        question_id=question_id,
        awarded_marks=awarded,
        maximum_marks=maximum,
        confidence=ConfidenceBand.LOW if needs_review else ConfidenceBand.HIGH,
        confidence_score=confidence_score,
        needs_teacher_review=needs_review,
        student_answer=f"answer-{question_id}",
        expected_answer=f"expected-{question_id}",
        topic="Waves",
        marker_source="ai",
        review_reason="plagiarism (score 0.95)" if plagiarism_flagged else None,
        plagiarism_flagged=plagiarism_flagged,
        matched_point_ids=["p1"] if awarded else [],
    )


def _report(questions: list[CorrectedQuestion]) -> AccuracyReport:
    correction = CorrectionResult(metadata=_metadata(), questions=questions)
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


def _seed_teacher_with_flagged_item(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    *,
    student_name: str = "Amelia",
    plagiarism_flagged: bool = False,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Returns (teacher_id, class_id, review_item_id)."""
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    student = _seed_user(pg_sessionmaker, Role.student, display_name=student_name)
    cls = class_service.create_class(teacher, "Physics 10A")
    assert cls.join_code is not None
    class_service.join_by_code(student, cls.join_code)
    # A HIGH-confidence, plagiarism-flagged question gets exactly one
    # review-queue row (the plagiarism_flag one) — a LOW-confidence question
    # would also earn a separate low_confidence row (see
    # ``AttemptRepository.persist_correction``), which would make ".first()"
    # below ambiguous about which reason it returns.
    attempt_id = AttemptRepository(pg_sessionmaker).persist_correction(
        user_id=str(student),
        report=_report(
            [
                _question(
                    "1",
                    awarded=0,
                    maximum=2,
                    confidence_score=1.0 if plagiarism_flagged else 0.3,
                    needs_review=not plagiarism_flagged,
                    plagiarism_flagged=plagiarism_flagged,
                )
            ]
        ),
    )
    with pg_sessionmaker() as session:
        item = session.scalars(
            sa.select(ReviewQueueItem).where(ReviewQueueItem.attempt_id == attempt_id)
        ).first()
        assert item is not None
        item_id = item.id
    return teacher, cls.class_id, item_id


# ---------------------------------------------------------------------------
# Payload shape (happy path).
# ---------------------------------------------------------------------------


def test_list_review_queue_happy_path_shape(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
) -> None:
    teacher, class_id, _ = _seed_teacher_with_flagged_item(pg_sessionmaker, class_service)
    _use_review_service(client, review_service)
    _auth_as(client, teacher, Role.teacher)

    resp = client.get("/api/teacher/review")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 1
    row = body["items"][0]
    assert row["studentDisplayName"] == "Amelia"
    assert row["classId"] == str(class_id)
    assert row["reason"] == "low_confidence"
    assert row["status"] == "open"
    assert row["aiAwardedMarks"] == 0
    assert row["maximumMarks"] == 2
    assert row["questionId"] == "1"
    assert row["waitingHours"] >= 0


def test_get_review_item_happy_path_shape(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
) -> None:
    teacher, _, item_id = _seed_teacher_with_flagged_item(pg_sessionmaker, class_service)
    _use_review_service(client, review_service)
    _auth_as(client, teacher, Role.teacher)

    resp = client.get(f"/api/teacher/review/{item_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["studentAnswer"] == "answer-1"
    assert body["expectedAnswer"] == "expected-1"
    assert body["isOverridden"] is False
    assert body["teacherAwardedMarks"] is None
    assert body["matchedPointIds"] == []


def test_resolve_accept_as_is_shape(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
) -> None:
    teacher, _, item_id = _seed_teacher_with_flagged_item(pg_sessionmaker, class_service)
    _use_review_service(client, review_service)
    _auth_as(client, teacher, Role.teacher)

    resp = client.post(f"/api/teacher/review/{item_id}/resolve", json={"note": "fine as-is"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "resolved"


def test_resolve_override_updates_detail_but_keeps_ai_mark(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
) -> None:
    teacher, _, item_id = _seed_teacher_with_flagged_item(pg_sessionmaker, class_service)
    _use_review_service(client, review_service)
    _auth_as(client, teacher, Role.teacher)

    resp = client.post(
        f"/api/teacher/review/{item_id}/resolve",
        json={
            "overrideMarks": 2,
            "breakdown": {"methodMarks": 1, "accuracyMarks": 1},
            "note": "Full credit — working shown.",
        },
    )
    assert resp.status_code == 200

    detail = client.get(f"/api/teacher/review/{item_id}").json()
    assert detail["isOverridden"] is True
    assert detail["teacherAwardedMarks"] == 2
    assert detail["teacherNote"] == "Full credit — working shown."
    assert detail["teacherBreakdown"] == {
        "methodMarks": 1,
        "accuracyMarks": 1,
        "otherMarks": None,
        "notes": None,
    }
    # The AI's original mark is still retrievable, unchanged, alongside the override.
    assert detail["aiAwardedMarks"] == 0


def test_dismiss_shape(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
) -> None:
    teacher, _, item_id = _seed_teacher_with_flagged_item(
        pg_sessionmaker, class_service, plagiarism_flagged=True
    )
    _use_review_service(client, review_service)
    _auth_as(client, teacher, Role.teacher)

    resp = client.post(f"/api/teacher/review/{item_id}/dismiss", json={"note": "checked, fine"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "dismissed"


def test_bulk_approve_shape(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
) -> None:
    teacher, _, item_id = _seed_teacher_with_flagged_item(pg_sessionmaker, class_service)
    _use_review_service(client, review_service)
    _auth_as(client, teacher, Role.teacher)

    resp = client.post("/api/teacher/review/bulk-approve", json={"itemIds": [str(item_id)]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["approved"] == [str(item_id)]
    assert body["skipped"] == []


def test_bulk_approve_malformed_id_is_422(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    _use_review_service(client, review_service)
    _auth_as(client, teacher, Role.teacher)

    resp = client.post("/api/teacher/review/bulk-approve", json={"itemIds": ["not-a-uuid"]})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Authz matrix: teacher A must never see/read/resolve/dismiss/bulk-approve
# teacher B's items.
# ---------------------------------------------------------------------------


def test_authz_list_never_shows_another_teachers_item(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
) -> None:
    teacher_a = _seed_user(pg_sessionmaker, Role.teacher)
    _seed_teacher_with_flagged_item(pg_sessionmaker, class_service, student_name="B's student")
    _use_review_service(client, review_service)
    _auth_as(client, teacher_a, Role.teacher)

    body = client.get("/api/teacher/review").json()
    assert body["items"] == []


def test_authz_get_item_out_of_scope_is_403(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
) -> None:
    teacher_a = _seed_user(pg_sessionmaker, Role.teacher)
    _, _, item_id = _seed_teacher_with_flagged_item(pg_sessionmaker, class_service)
    _use_review_service(client, review_service)
    _auth_as(client, teacher_a, Role.teacher)

    resp = client.get(f"/api/teacher/review/{item_id}")
    assert resp.status_code == 403


def test_authz_get_item_unknown_id_is_404(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    _use_review_service(client, review_service)
    _auth_as(client, teacher, Role.teacher)

    resp = client.get(f"/api/teacher/review/{uuid.uuid4()}")
    assert resp.status_code == 404


def test_authz_get_item_malformed_id_is_422(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    _use_review_service(client, review_service)
    _auth_as(client, teacher, Role.teacher)

    resp = client.get("/api/teacher/review/not-a-uuid")
    assert resp.status_code == 422


def test_authz_resolve_out_of_scope_is_403(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
) -> None:
    teacher_a = _seed_user(pg_sessionmaker, Role.teacher)
    _, _, item_id = _seed_teacher_with_flagged_item(pg_sessionmaker, class_service)
    _use_review_service(client, review_service)
    _auth_as(client, teacher_a, Role.teacher)

    resp = client.post(f"/api/teacher/review/{item_id}/resolve", json={})
    assert resp.status_code == 403


def test_authz_dismiss_out_of_scope_is_403(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
) -> None:
    teacher_a = _seed_user(pg_sessionmaker, Role.teacher)
    _, _, item_id = _seed_teacher_with_flagged_item(
        pg_sessionmaker, class_service, plagiarism_flagged=True
    )
    _use_review_service(client, review_service)
    _auth_as(client, teacher_a, Role.teacher)

    resp = client.post(f"/api/teacher/review/{item_id}/dismiss", json={})
    assert resp.status_code == 403


def test_authz_bulk_approve_out_of_scope_is_skipped_not_approved(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
) -> None:
    """Bulk-approve is skip-and-report (see ``ReviewService.bulk_approve``'s
    docstring), so the authz guarantee here is: teacher A's call can never
    approve teacher B's item — it comes back ``skipped`` with reason
    ``"forbidden"``, never in ``approved``, and B's item is untouched."""
    teacher_a = _seed_user(pg_sessionmaker, Role.teacher)
    _, _, item_id = _seed_teacher_with_flagged_item(pg_sessionmaker, class_service)
    _use_review_service(client, review_service)
    _auth_as(client, teacher_a, Role.teacher)

    resp = client.post("/api/teacher/review/bulk-approve", json={"itemIds": [str(item_id)]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["approved"] == []
    assert body["skipped"] == [{"itemId": str(item_id), "reason": "forbidden"}]

    with pg_sessionmaker() as session:
        item = session.get(ReviewQueueItem, item_id)
        assert item is not None
        assert item.status.value == "open"


def test_authz_platform_admin_sees_none_no_super_role_bypass(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
) -> None:
    admin = _seed_user(pg_sessionmaker, Role.platform_admin)
    _, _, item_id = _seed_teacher_with_flagged_item(pg_sessionmaker, class_service)
    _use_review_service(client, review_service)
    _auth_as(client, admin, Role.platform_admin)

    assert client.get("/api/teacher/review").json()["items"] == []
    assert client.get(f"/api/teacher/review/{item_id}").status_code == 403


# ---------------------------------------------------------------------------
# Overview "Need your eyes" — now review-queue-scoped (fixes the inherited
# cross-tenant leak: previously counted the entire in-process papers_store
# with no owner filter).
# ---------------------------------------------------------------------------


def test_overview_need_your_eyes_scoped_to_callers_review_queue(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
) -> None:
    from lemely.core.history import PaperRecord
    from lemely.db.history_repo import DbHistoryStore
    from lemely.web.deps import get_class_service, get_history_store

    teacher_a, _, _ = _seed_teacher_with_flagged_item(
        pg_sessionmaker, class_service, student_name="A's student"
    )
    teacher_b = _seed_user(pg_sessionmaker, Role.teacher)
    student_b = _seed_user(pg_sessionmaker, Role.student, display_name="B's student")
    class_b = class_service.create_class(teacher_b, "B's class")
    assert class_b.join_code is not None
    class_service.join_by_code(student_b, class_b.join_code)
    # Give B's student a paper (so overview isn't entirely empty for B) but no
    # flagged review item — B's "Need your eyes" must read 0, never A's count.
    DbHistoryStore(pg_sessionmaker).append(
        str(student_b),
        PaperRecord(
            student_id=str(student_b),
            metadata=_metadata(),
            awarded_marks=2,
            maximum_marks=2,
            percentage=100.0,
            grade="A",
            weak_areas=[],
            recorded_at="2026-01-01T00:00:00+00:00",
        ),
    )

    app = create_app()
    app.dependency_overrides[get_class_service] = lambda: class_service
    app.dependency_overrides[get_review_service] = lambda: review_service
    app.dependency_overrides[get_history_store] = lambda: DbHistoryStore(pg_sessionmaker)
    local = TestClient(app)

    local.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(teacher_a), role=Role.teacher.value
    )
    stats_a = {s["key"]: s["value"] for s in local.get("/api/teacher/overview").json()["stats"]}
    assert stats_a["Need your eyes"] == "1"

    local.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(teacher_b), role=Role.teacher.value
    )
    stats_b = {s["key"]: s["value"] for s in local.get("/api/teacher/overview").json()["stats"]}
    assert stats_b["Need your eyes"] == "0"

    app.dependency_overrides.clear()
