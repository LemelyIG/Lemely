"""Route tests for the review-queue endpoints (``lemely.web.routers.review``, P3.4).

Self-contained (mirrors ``tests/test_class_repo.py``/the P3.3 section of
``tests/test_web_teacher.py``) — a throwaway Postgres DB per test, skipped
cleanly when unreachable. Covers payload shape for each of the five routes
and the full authz matrix: a teacher must never see, read, resolve, dismiss,
or bulk-approve another teacher's review item.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.core.loose_schemas import (
    AnswerPoint,
    MarkScheme,
    MarkSchemeMetadata,
    PaperType,
    SchemeFormat,
)
from lemely.core.loose_schemas import Question as SchemeQuestion
from lemely.core.loose_schemas import QuestionType as SchemeQuestionType
from lemely.core.loose_schemas import SessionMonth as LooseSessionMonth
from lemely.core.schemas import (
    AccuracyReport,
    ConfidenceBand,
    CorrectedQuestion,
    CorrectionResult,
    ExamMetadata,
    GradePrediction,
    WeaknessReport,
)

# Aliased: `lemely.db.self_review_repo.PointVerdict`, imported below, is the
# STUDENT's self-review verdict (`mark_point_id`/`earned`/`evidence`) -- an
# unrelated class that happens to share this name. This is I6/I7's MARKER
# verdict (`point_id`/`verdict`/`evidence_span`), a `CorrectedQuestion` field.
from lemely.core.schemas import PointVerdict as MarkerPointVerdict
from lemely.db.attempt_repo import AttemptRepository
from lemely.db.base import Base
from lemely.db.class_repo import ClassService
from lemely.db.models import User
from lemely.db.models.attempts import QuestionResult
from lemely.db.models.enums import ReviewReason, Role
from lemely.db.models.ops import ReviewQueueItem
from lemely.db.review_repo import ReviewService
from lemely.db.self_review_repo import PointVerdict, SelfReviewService
from lemely.db.teacher_paper_repo import TeacherPaperRepository
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


def _point_scheme() -> MarkScheme:
    """A one-question, two-point scheme — just enough for a real self-review
    pass (O-1 needs actual ``question_result_points`` rows, not the plain
    ``report``-only fixtures the rest of this file uses)."""
    return MarkScheme(
        metadata=MarkSchemeMetadata(
            subject="Physics",
            subject_code="9999",
            paper_number=1,
            paper_variant=1,
            session_month=LooseSessionMonth.MAY_JUNE,
            session_year=2020,
            paper_type=PaperType.THEORY_CORE,
            maximum_mark=2,
            scheme_format=SchemeFormat.POINT_BASED,
        ),
        questions=[
            SchemeQuestion(
                id="1",
                marks=2,
                type=SchemeQuestionType.RECALL,
                answer_points=[
                    AnswerPoint(id="p1", point="States the law", marks=1),
                    AnswerPoint(id="p2", point="Gives the unit", marks=1),
                ],
            ),
        ],
    )


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
    # No params behaves exactly as before, plus a `nextCursor` that is null
    # once the whole (small) queue fits on one page.
    assert body["nextCursor"] is None


# ── Cursor pagination (B6a) ──────────────────────────────────────────────────


def _seed_teacher_with_n_items(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    count: int,
) -> tuple[uuid.UUID, list[uuid.UUID]]:
    """Seed one teacher/student pair with ``count`` open review items, each a
    minute apart starting five hours ago. Returns (teacher_id, item_ids)
    ordered oldest-first."""
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    student = _seed_user(pg_sessionmaker, Role.student, display_name="Amelia")
    cls = class_service.create_class(teacher, "Physics 10A")
    assert cls.join_code is not None
    class_service.join_by_code(student, cls.join_code)
    base = datetime.now(UTC) - timedelta(hours=5)
    item_ids: list[uuid.UUID] = []
    for i in range(count):
        attempt_id = AttemptRepository(pg_sessionmaker).persist_correction(
            user_id=str(student),
            report=_report([_question(str(i), awarded=0, maximum=2)]),
        )
        with pg_sessionmaker() as session:
            item = session.scalars(
                sa.select(ReviewQueueItem).where(ReviewQueueItem.attempt_id == attempt_id)
            ).first()
            assert item is not None
            item_id = item.id
        with pg_sessionmaker() as session:
            session.execute(
                sa.text("UPDATE review_queue SET created_at = :ts WHERE id = :id"),
                {"ts": base + timedelta(minutes=i), "id": item_id},
            )
            session.commit()
        item_ids.append(item_id)
    return teacher, item_ids


def test_list_review_queue_paginates_with_limit_and_cursor(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
) -> None:
    teacher, item_ids = _seed_teacher_with_n_items(pg_sessionmaker, class_service, 3)
    _use_review_service(client, review_service)
    _auth_as(client, teacher, Role.teacher)

    resp = client.get("/api/teacher/review", params={"limit": 1})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["itemId"] == str(item_ids[0])
    assert body["nextCursor"] is not None

    resp2 = client.get("/api/teacher/review", params={"limit": 1, "cursor": body["nextCursor"]})
    assert resp2.status_code == 200
    body2 = resp2.json()
    assert len(body2["items"]) == 1
    assert body2["items"][0]["itemId"] == str(item_ids[1])


def test_list_review_queue_malformed_cursor_is_422(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
) -> None:
    teacher, _ = _seed_teacher_with_n_items(pg_sessionmaker, class_service, 1)
    _use_review_service(client, review_service)
    _auth_as(client, teacher, Role.teacher)

    resp = client.get("/api/teacher/review", params={"cursor": "not-a-valid-cursor!!"})
    assert resp.status_code == 422


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


def test_get_review_item_carries_the_students_self_review_points(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
) -> None:
    """O-1 (S2 part2+3 final review): ``ReviewItemDetail.points`` has no test
    of its own — forcing ``get_item`` to return ``points=[]`` left every
    other test in this suite green, and ``SelfReviewPoints`` renders ``null``
    on an empty list, so the regression is invisible on the web side and
    restores exactly the state I-2 was raised to fix (a
    ``student_evidence_unjudged`` row the teacher cannot act on).

    Seeds a real self-review pass — an evidenced challenge on a
    high-confidence point, ``judge=None`` — so Phase C opens a
    ``student_evidence_unjudged`` row, then asserts the teacher's GET
    response carries the student's own evidence text and claim, not merely a
    non-empty list (a length check would pass on empty strings)."""
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    student = _seed_user(pg_sessionmaker, Role.student, display_name="Amelia")
    cls = class_service.create_class(teacher, "Physics 10A")
    assert cls.join_code is not None
    class_service.join_by_code(student, cls.join_code)

    question = _question("1", awarded=1, maximum=2, confidence_score=0.95, needs_review=False)
    attempt_id = AttemptRepository(pg_sessionmaker).persist_correction(
        user_id=str(student), report=_report([question]), mark_scheme=_point_scheme()
    )
    with pg_sessionmaker() as session:
        qr_id = session.scalars(
            sa.select(QuestionResult.id).where(
                QuestionResult.attempt_id == attempt_id, QuestionResult.question_id == "1"
            )
        ).one()

    SelfReviewService(pg_sessionmaker, judge=None).submit(
        student,
        attempt_id,
        qr_id,
        [
            PointVerdict(mark_point_id="p1", earned=True),
            PointVerdict(mark_point_id="p2", earned=True, evidence="I gave the unit, m/s."),
        ],
    )

    with pg_sessionmaker() as session:
        item = session.scalars(
            sa.select(ReviewQueueItem).where(
                ReviewQueueItem.question_result_id == qr_id,
                ReviewQueueItem.reason == ReviewReason.student_evidence_unjudged,
            )
        ).one()
        item_id = item.id

    _use_review_service(client, review_service)
    _auth_as(client, teacher, Role.teacher)

    resp = client.get(f"/api/teacher/review/{item_id}")
    assert resp.status_code == 200
    points = resp.json()["points"]
    assert len(points) == 2
    p2 = next(p for p in points if p["markPointId"] == "p2")
    assert p2["pointText"] == "Gives the unit"
    assert p2["awarded"] is False  # the marker withheld it
    assert p2["studentSelfmark"] is True  # the student's own claim
    assert p2["studentEvidence"] == "I gave the unit, m/s."
    assert p2["evidenceVerdict"] is None  # judge=None: never actually judged
    # I6/I7 (US-013, US-046): this attempt was scored by the legacy
    # (non-verdict) path, so the wire shape carries the new fields at their
    # legacy defaults rather than omitting them.
    assert p2["verdict"] is None
    assert p2["evidenceSpan"] == ""
    assert p2["ecfApplied"] is False


def test_get_review_item_carries_marker_verdicts_for_points_the_student_never_touched(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
) -> None:
    """US-046: I6/I7's marker verdict must reach the wire even when the

    student's self-review never ran at all -- unlike the fixture above, no
    ``SelfReviewService.submit`` call happens here. ``withheld`` and
    ``unverifiable`` both read ``awarded: false``; this asserts the wire
    payload still tells them apart.
    """
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    student = _seed_user(pg_sessionmaker, Role.student, display_name="Amelia")
    cls = class_service.create_class(teacher, "Physics 10A")
    assert cls.join_code is not None
    class_service.join_by_code(student, cls.join_code)

    question = CorrectedQuestion(
        question_id="1",
        awarded_marks=0,
        maximum_marks=2,
        confidence=ConfidenceBand.LOW,
        confidence_score=0.3,
        needs_teacher_review=True,
        student_answer="answer-1",
        expected_answer="expected-1",
        topic="Physics",
        marker_source="ai",
        matched_point_ids=[],
        point_verdicts=[
            MarkerPointVerdict(point_id="p1", verdict="unverifiable", evidence_span="tried it"),
            MarkerPointVerdict(
                point_id="p2", verdict="withheld", evidence_span="", ecf_applied=True
            ),
        ],
    )
    attempt_id = AttemptRepository(pg_sessionmaker).persist_correction(
        user_id=str(student), report=_report([question]), mark_scheme=_point_scheme()
    )
    with pg_sessionmaker() as session:
        item = session.scalars(
            sa.select(ReviewQueueItem).where(ReviewQueueItem.attempt_id == attempt_id)
        ).first()
        assert item is not None
        item_id = item.id

    _use_review_service(client, review_service)
    _auth_as(client, teacher, Role.teacher)

    resp = client.get(f"/api/teacher/review/{item_id}")
    assert resp.status_code == 200
    points = resp.json()["points"]
    assert len(points) == 2
    by_id = {p["markPointId"]: p for p in points}

    p1 = by_id["p1"]
    assert p1["verdict"] == "unverifiable"
    assert p1["awarded"] is False
    assert p1["evidenceSpan"] == "tried it"
    assert p1["ecfApplied"] is False
    assert p1["studentSelfmark"] is None  # never self-marked: the defect this task fixes

    p2 = by_id["p2"]
    assert p2["verdict"] == "withheld"
    assert p2["awarded"] is False
    assert p2["ecfApplied"] is True
    assert p2["studentSelfmark"] is None

    # The distinction I6 exists to carry, both collapse to awarded=False.
    assert p1["verdict"] != p2["verdict"]


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


# ---------------------------------------------------------------------------
# Console-sourced items (migration 0034). Regression cover for the split that
# let a grading-console paper show "Review" on its card while the review queue
# stayed empty: the console read ``teacher_papers.report_json`` and the queue
# read ``review_queue``, and only the student path ever wrote the latter.
# ---------------------------------------------------------------------------


def _seed_console_paper(
    pg_sessionmaker: sessionmaker[Session],
    *,
    uploader: uuid.UUID,
    questions: list[CorrectedQuestion] | None = None,
) -> uuid.UUID:
    """Grade a paper through the console repository, as a finished run would."""
    repo = TeacherPaperRepository(pg_sessionmaker, stale_after=timedelta(minutes=10))
    paper_id = uuid.uuid4()
    repo.create(
        paper_id=paper_id,
        uploaded_by=uploader,
        storage_path=f"teacher/{uploader}/{paper_id.hex}/scan.pdf",
        scheme_storage_path=None,
        original_filename="scan.pdf",
        content_type="application/pdf",
        byte_size=15,
    )
    repo.claim_run(paper_id)
    repo.finish(
        paper_id,
        _report(questions if questions is not None else [_question("5b", awarded=1, maximum=4)]),
    )
    return paper_id


def test_console_graded_paper_reaches_the_review_queue(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    review_service: ReviewService,
) -> None:
    """The bug this migration exists for: a flagged console paper must be listed."""
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    paper_id = _seed_console_paper(pg_sessionmaker, uploader=teacher)
    _use_review_service(client, review_service)
    _auth_as(client, teacher, Role.teacher)

    body = client.get("/api/teacher/review").json()
    assert len(body["items"]) == 1
    row = body["items"][0]
    assert row["source"] == "console_paper"
    assert row["paperId"] == str(paper_id)
    # No student, no class — a console upload is attributed to neither (D1.12),
    # and the queue must say so rather than inventing one.
    assert row["attemptId"] is None
    assert row["studentId"] is None
    assert row["classId"] is None
    assert row["className"] is None
    assert row["questionResultId"] is None
    # The paper's own label is its identity, matching its grading-console card.
    assert row["studentDisplayName"] == "Paper 1 V1 May/June 2020 - " + (
        datetime.now(UTC).date().isoformat()
    )
    assert row["questionId"] == "5b"
    assert row["reason"] == "low_confidence"
    assert row["aiAwardedMarks"] == 1
    assert row["maximumMarks"] == 4
    assert row["confidenceScore"] == pytest.approx(0.3)


def test_console_item_detail_carries_the_reports_marking_evidence(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    review_service: ReviewService,
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    _seed_console_paper(pg_sessionmaker, uploader=teacher)
    _use_review_service(client, review_service)
    _auth_as(client, teacher, Role.teacher)

    item_id = client.get("/api/teacher/review").json()["items"][0]["itemId"]
    detail = client.get(f"/api/teacher/review/{item_id}").json()
    assert detail["source"] == "console_paper"
    assert detail["studentAnswer"] == "answer-5b"
    assert detail["expectedAnswer"] == "expected-5b"
    assert detail["topic"] == "Waves"
    assert detail["matchedPointIds"] == ["p1"]
    assert detail["markerSource"] == "ai"
    # Nowhere to persist an override, so every override field stays empty.
    assert detail["isOverridden"] is False
    assert detail["teacherAwardedMarks"] is None


def test_console_item_accepts_as_is_but_refuses_a_mark_override(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    review_service: ReviewService,
) -> None:
    """A console item can be closed, never re-marked — there is no row to write to."""
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    _seed_console_paper(pg_sessionmaker, uploader=teacher)
    _use_review_service(client, review_service)
    _auth_as(client, teacher, Role.teacher)

    item_id = client.get("/api/teacher/review").json()["items"][0]["itemId"]

    # Refused rather than accepted-and-dropped: telling the teacher their
    # re-mark landed when nothing changed is the worse failure.
    refused = client.post(f"/api/teacher/review/{item_id}/resolve", json={"overrideMarks": 3})
    assert refused.status_code == 422
    assert client.get("/api/teacher/review").json()["items"], "still open after a refused override"

    accepted = client.post(f"/api/teacher/review/{item_id}/resolve", json={})
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "resolved"
    assert client.get("/api/teacher/review").json()["items"] == []


def test_console_integrity_flag_can_be_dismissed(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    review_service: ReviewService,
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    _seed_console_paper(
        pg_sessionmaker,
        uploader=teacher,
        questions=[
            _question(
                "2a",
                awarded=0,
                maximum=3,
                confidence_score=1.0,
                needs_review=False,
                plagiarism_flagged=True,
            )
        ],
    )
    _use_review_service(client, review_service)
    _auth_as(client, teacher, Role.teacher)

    rows = client.get("/api/teacher/review").json()["items"]
    assert [r["reason"] for r in rows] == ["plagiarism_flag"]
    resp = client.post(f"/api/teacher/review/{rows[0]['itemId']}/dismiss", json={})
    assert resp.status_code == 200
    assert resp.json()["status"] == "dismissed"


def test_console_items_are_bulk_approvable(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    review_service: ReviewService,
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    _seed_console_paper(
        pg_sessionmaker,
        uploader=teacher,
        questions=[
            _question("1a", awarded=1, maximum=2),
            _question("1b", awarded=0, maximum=2),
        ],
    )
    _use_review_service(client, review_service)
    _auth_as(client, teacher, Role.teacher)

    ids = [r["itemId"] for r in client.get("/api/teacher/review").json()["items"]]
    assert len(ids) == 2
    resp = client.post("/api/teacher/review/bulk-approve", json={"itemIds": ids})
    assert resp.status_code == 200
    assert sorted(resp.json()["approved"]) == sorted(ids)
    assert resp.json()["skipped"] == []
    assert client.get("/api/teacher/review").json()["items"] == []


def test_regrade_replaces_open_console_rows_and_preserves_closed_ones(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    review_service: ReviewService,
) -> None:
    """A second run replaces the open queue without stacking duplicates.

    A question the teacher already signed off is re-queued when the re-mark
    flags it again, and that is correct rather than an undo: the sign-off was
    for the *previous* marking, and a re-run replaced it with a mark nobody has
    reviewed. What must not happen is the resolved row being deleted — it is
    the record that a decision was made, so it survives alongside the new one.
    """
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    paper_id = _seed_console_paper(
        pg_sessionmaker,
        uploader=teacher,
        questions=[
            _question("1a", awarded=1, maximum=2),
            _question("1b", awarded=0, maximum=2),
        ],
    )
    _use_review_service(client, review_service)
    _auth_as(client, teacher, Role.teacher)

    rows = {r["questionId"]: r["itemId"] for r in client.get("/api/teacher/review").json()["items"]}
    assert client.post(f"/api/teacher/review/{rows['1a']}/resolve", json={}).status_code == 200

    # Re-mark the same paper.
    TeacherPaperRepository(pg_sessionmaker, stale_after=timedelta(minutes=10)).finish(
        paper_id,
        _report([_question("1a", awarded=2, maximum=2), _question("1b", awarded=1, maximum=2)]),
    )

    after = client.get("/api/teacher/review").json()["items"]
    # Both questions are flagged by the new run, so both are open again — each
    # exactly once. "1b" is the duplicate-stacking guard: it had an open row
    # before the re-run and must still have exactly one after it.
    assert sorted(r["questionId"] for r in after) == ["1a", "1b"]
    with pg_sessionmaker() as session:
        rows = session.scalars(
            sa.select(ReviewQueueItem).where(ReviewQueueItem.teacher_paper_id == paper_id)
        ).all()
    # Three rows, not four: the resolved "1a" is kept as the record of that
    # decision, the two open rows are the current run's, and nothing is doubled.
    assert sorted(i.status.value for i in rows) == ["open", "open", "resolved"]
    assert sorted(i.question_id for i in rows if i.status.value == "open") == ["1a", "1b"]


def test_console_items_are_scoped_to_the_uploading_teacher(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    review_service: ReviewService,
) -> None:
    """Another teacher's console paper is invisible, and unactionable, not a 404 oracle."""
    owner = _seed_user(pg_sessionmaker, Role.teacher)
    other = _seed_user(pg_sessionmaker, Role.teacher)
    _seed_console_paper(pg_sessionmaker, uploader=owner)
    _use_review_service(client, review_service)

    _auth_as(client, owner, Role.teacher)
    item_id = client.get("/api/teacher/review").json()["items"][0]["itemId"]

    _auth_as(client, other, Role.teacher)
    assert client.get("/api/teacher/review").json()["items"] == []
    assert client.get(f"/api/teacher/review/{item_id}").status_code == 403
    assert client.post(f"/api/teacher/review/{item_id}/resolve", json={}).status_code == 403
    bulk = client.post("/api/teacher/review/bulk-approve", json={"itemIds": [item_id]})
    assert bulk.json()["approved"] == []
    assert [s["reason"] for s in bulk.json()["skipped"]] == ["forbidden"]


def test_console_items_honour_the_queues_no_super_role_bypass(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    review_service: ReviewService,
) -> None:
    """`platform_admin` sees no console rows either.

    ``teacher_paper_visible`` grants a platform admin every paper — that is the
    grading console's rule (DS11). This queue has no super-role bypass at all
    (D1.6/D1.10), and adding the console source must not quietly hand the one
    deliberately empty-scoped role a view of every teacher's marking.
    """
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    admin = _seed_user(pg_sessionmaker, Role.platform_admin)
    _seed_console_paper(pg_sessionmaker, uploader=teacher)
    _use_review_service(client, review_service)

    _auth_as(client, teacher, Role.teacher)
    item_id = client.get("/api/teacher/review").json()["items"][0]["itemId"]

    _auth_as(client, admin, Role.platform_admin)
    assert client.get("/api/teacher/review").json()["items"] == []
    assert client.get(f"/api/teacher/review/{item_id}").status_code == 403


def test_class_filter_excludes_console_items(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
) -> None:
    """A console paper belongs to no class, so "this class only" excludes it."""
    teacher, class_id, _ = _seed_teacher_with_flagged_item(pg_sessionmaker, class_service)
    _seed_console_paper(pg_sessionmaker, uploader=teacher)
    _use_review_service(client, review_service)
    _auth_as(client, teacher, Role.teacher)

    unfiltered = client.get("/api/teacher/review").json()["items"]
    assert sorted(r["source"] for r in unfiltered) == ["console_paper", "student_attempt"]

    filtered = client.get(f"/api/teacher/review?class_id={class_id}").json()["items"]
    assert [r["source"] for r in filtered] == ["student_attempt"]


def test_both_sources_merge_oldest_first(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
) -> None:
    """Ordering holds across the merged list, not just within each half."""
    teacher, _, attempt_item = _seed_teacher_with_flagged_item(pg_sessionmaker, class_service)
    _seed_console_paper(pg_sessionmaker, uploader=teacher)
    _use_review_service(client, review_service)
    _auth_as(client, teacher, Role.teacher)

    # Age the console row past the attempt-backed one so a naive
    # "attempts first, then papers" concatenation would order them wrongly.
    with pg_sessionmaker.begin() as session:
        session.execute(
            sa.update(ReviewQueueItem)
            .where(ReviewQueueItem.teacher_paper_id.is_not(None))
            .values(created_at=datetime.now(UTC) - timedelta(hours=48))
        )

    rows = client.get("/api/teacher/review").json()["items"]
    assert [r["source"] for r in rows] == ["console_paper", "student_attempt"]
    assert rows[1]["itemId"] == str(attempt_item)

    # `min_age_hours` filters the merged list, not one half of it.
    aged = client.get("/api/teacher/review?min_age_hours=24").json()["items"]
    assert [r["source"] for r in aged] == ["console_paper"]
