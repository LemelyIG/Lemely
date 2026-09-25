"""Route tests for the review-queue endpoints (``lemely.web.routers.review``, P3.4).

Self-contained (mirrors ``tests/test_class_repo.py``/the P3.3 section of
``tests/test_web_teacher.py``) — a throwaway Postgres DB per test, skipped
cleanly when unreachable. Covers payload shape for each of the five routes
and the full authz matrix: a teacher must never see, read, resolve, dismiss,
or bulk-approve another teacher's review item.
"""

from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
import structlog.testing
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image
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
    SourceBox,
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
from lemely.db.models.attempts import QuestionResult, Upload
from lemely.db.models.enums import ReviewReason, Role
from lemely.db.models.ops import ReviewQueueItem
from lemely.db.review_repo import ReviewService
from lemely.db.self_review_repo import PointVerdict, SelfReviewService
from lemely.db.teacher_paper_repo import TeacherPaperRepository
from lemely.runtime.config import DatabaseSettings
from lemely.web import create_app
from lemely.web.deps import (
    AuthContext,
    get_auth_context,
    get_review_service,
    get_settings,
    get_storage_backend,
)
from tests.storage_fakes import FakeStorageBackend

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


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


def test_get_review_item_exposes_the_markers_rationale_on_the_legacy_path(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
) -> None:
    """``rationale`` reaches the teacher wire from ``point_notes`` alone --

    no ``point_verdicts`` at all -- so this is the one field on this DTO
    that improves the teacher screen before ``equivalence_gate`` is ever on.
    """
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    student = _seed_user(pg_sessionmaker, Role.student, display_name="Amelia")
    cls = class_service.create_class(teacher, "Physics 10A")
    assert cls.join_code is not None
    class_service.join_by_code(student, cls.join_code)

    question = CorrectedQuestion(
        question_id="1",
        awarded_marks=1,
        maximum_marks=2,
        confidence=ConfidenceBand.LOW,
        confidence_score=0.3,
        needs_teacher_review=True,
        student_answer="answer-1",
        expected_answer="expected-1",
        topic="Physics",
        marker_source="ai",
        matched_point_ids=["p1"],
        point_notes={"p1": "method mark: 2x not shown"},
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
    p1 = next(p for p in points if p["markPointId"] == "p1")
    assert p1["rationale"] == "method mark: 2x not shown"
    assert p1["verdict"] is None  # legacy path: no PointVerdict ever written


def test_review_item_detail_reports_whether_a_crop_exists(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
) -> None:
    """`hasSourceBox` must reach the HTTP response, not stop at the dataclass.

    The boxed attempt carries an ``upload_id``: the flag reports "a crop may be
    available", which needs the scan as well as the box. This fixture had the box
    and no scan, so it asserted ``true`` for an item the crop route was certain
    to refuse — see ``test_has_source_box_is_false_when_the_attempt_has_no_upload``.
    """
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    student = _seed_user(pg_sessionmaker, Role.student, display_name="Amelia")
    cls = class_service.create_class(teacher, "Physics 10A")
    assert cls.join_code is not None
    class_service.join_by_code(student, cls.join_code)

    boxed_question = _question("1", awarded=1, maximum=2)
    boxed_question.source_box = SourceBox(page=1, box=[10, 20, 30, 40])
    boxless_question = _question("2", awarded=1, maximum=2)

    upload_id = uuid.uuid4()
    with pg_sessionmaker.begin() as session:
        session.add(
            Upload(
                id=upload_id,
                user_id=student,
                storage_path=f"students/{student}/{upload_id.hex}/scan.pdf",
                original_filename="scan.pdf",
                content_type="application/pdf",
                byte_size=11,
            )
        )
    boxed_attempt_id = AttemptRepository(pg_sessionmaker).persist_correction(
        user_id=str(student), report=_report([boxed_question]), upload_id=upload_id
    )
    boxless_attempt_id = AttemptRepository(pg_sessionmaker).persist_correction(
        user_id=str(student), report=_report([boxless_question])
    )

    def _item_id_for(attempt_id: uuid.UUID) -> uuid.UUID:
        with pg_sessionmaker() as session:
            item = session.scalars(
                sa.select(ReviewQueueItem).where(ReviewQueueItem.attempt_id == attempt_id)
            ).first()
            assert item is not None
            return item.id

    _use_review_service(client, review_service)
    _auth_as(client, teacher, Role.teacher)

    boxed_resp = client.get(f"/api/teacher/review/{_item_id_for(boxed_attempt_id)}")
    assert boxed_resp.status_code == 200
    assert boxed_resp.json()["hasSourceBox"] is True

    boxless_resp = client.get(f"/api/teacher/review/{_item_id_for(boxless_attempt_id)}")
    assert boxless_resp.status_code == 200
    assert boxless_resp.json()["hasSourceBox"] is False


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


# ---------------------------------------------------------------------------
# The crop route (``GET /api/teacher/review/{item_id}/crop``).
#
# Every scan in this section is SYNTHESISED in-process. This repository is
# public and the route serves an image of a real student's handwriting, so no
# fixture here may ever be, or be derived from, a real scan.
# ---------------------------------------------------------------------------

# Geometry for the synthetic scans below, in `SourceBox`'s 0-1000 space.
_MARK_BOX = [100, 100, 300, 400]  # [ymin, xmin, ymax, xmax]
_MARK_RGB = (255, 0, 0)
_OUTSIDE_RGB = (0, 0, 255)
_MARKED_PAGE = 1
_SCAN_PAGES = 3
# A4 in PDF points, the page size a scanned script actually has.
_PAGE_WIDTH_PT = 595.0
_PAGE_HEIGHT_PT = 842.0


def _fill(rgb: tuple[int, int, int]) -> list[float]:
    return [channel / 255 for channel in rgb]


def _synthetic_scan(
    *,
    pages: int = _SCAN_PAGES,
    marked_page: int = _MARKED_PAGE,
    width: float = _PAGE_WIDTH_PT,
    height: float = _PAGE_HEIGHT_PT,
) -> bytes:
    """A synthetic multi-page PDF standing in for a student's scan.

    The page at ``marked_page`` carries a filled red rectangle covering exactly
    ``_MARK_BOX``; every page carries a blue rectangle well outside it. So a
    crop of the box contains red and no blue, while a whole-page render
    contains both, and a failed crop contains neither — which is what lets the
    happy-path test below tell "the boxed region" from "the page it came from"
    and from "a blank image".
    """
    import pymupdf

    doc = pymupdf.open()
    try:
        for index in range(pages):
            page = doc.new_page(width=width, height=height)
            page.draw_rect(
                pymupdf.Rect(0.70 * width, 0.70 * height, 0.95 * width, 0.95 * height),
                color=None,
                fill=_fill(_OUTSIDE_RGB),
            )
            if index == marked_page:
                ymin, xmin, ymax, xmax = _MARK_BOX
                page.draw_rect(
                    pymupdf.Rect(
                        xmin / 1000 * width,
                        ymin / 1000 * height,
                        xmax / 1000 * width,
                        ymax / 1000 * height,
                    ),
                    color=None,
                    fill=_fill(_MARK_RGB),
                )
        data: bytes = doc.tobytes()
    finally:
        doc.close()
    return data


@pytest.fixture
def storage_backend() -> FakeStorageBackend:
    """An in-memory :class:`StorageBackend` double — no network, no local disk."""
    return FakeStorageBackend()


def _queue_rows(client: TestClient, caller: uuid.UUID) -> list[dict[str, object]]:
    """The queue as ``caller`` sees it."""
    _auth_as(client, caller, Role.teacher)
    rows: list[dict[str, object]] = client.get("/api/teacher/review").json()["items"]
    return rows


def _use_storage(client: TestClient, storage: FakeStorageBackend) -> None:
    client.app.dependency_overrides[get_storage_backend] = lambda: storage  # type: ignore[union-attr]


def _seed_boxed_review_item(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    *,
    storage: FakeStorageBackend,
    scan: bytes,
    page: int | None = _MARKED_PAGE,
    with_upload: bool = True,
    store_object: bool = True,
    student_name: str = "Amelia",
    content_type: str = "application/pdf",
    box: list[int] | None = None,
) -> tuple[uuid.UUID, uuid.UUID]:
    """Seed one attempt-backed review item whose scan is in ``storage``.

    Returns ``(teacher_id, item_id)``. ``page=None`` persists no box (the
    common case the DTO's ``hasSourceBox`` already reports); ``with_upload=
    False`` models a quiz or seeded attempt with no scan at all;
    ``store_object=False`` models a storage object that has since expired.
    """
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    student = _seed_user(pg_sessionmaker, Role.student, display_name=student_name)
    cls = class_service.create_class(teacher, "Physics 10A")
    assert cls.join_code is not None
    class_service.join_by_code(student, cls.join_code)

    upload_id: uuid.UUID | None = None
    if with_upload:
        upload_id = uuid.uuid4()
        object_path = f"students/{student}/{upload_id.hex}/scan.pdf"
        with pg_sessionmaker.begin() as session:
            session.add(
                Upload(
                    id=upload_id,
                    user_id=student,
                    storage_path=object_path,
                    original_filename="scan.pdf",
                    content_type=content_type,
                    byte_size=len(scan),
                )
            )
        if store_object:
            storage.upload(get_settings().storage.bucket, object_path, scan, content_type)

    question = _question("1", awarded=1, maximum=2)
    if page is not None:
        question.source_box = SourceBox(page=page, box=list(box or _MARK_BOX))
    attempt_id = AttemptRepository(pg_sessionmaker).persist_correction(
        user_id=str(student), report=_report([question]), upload_id=upload_id
    )
    with pg_sessionmaker() as session:
        item = session.scalars(
            sa.select(ReviewQueueItem).where(ReviewQueueItem.attempt_id == attempt_id)
        ).first()
        assert item is not None
        return teacher, item.id


def test_crop_route_refuses_a_caller_who_cannot_see_the_student(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
    storage_backend: FakeStorageBackend,
) -> None:
    """An image endpoint is where IDOR gets written. This is the first test.

    The route must reuse the review item's own visibility rule, so a teacher
    from another school gets exactly what the detail route gives them and never
    an image, whatever the status code is. Asserted by comparison rather than
    against a hard-coded number: if the two routes ever disagree about the same
    caller and the same item, that divergence is the bug this test exists to
    catch.

    The authorised half is not decoration. A route that returned 404 for every
    caller would satisfy the denial on its own, so the same fixture is served
    to the teacher who owns the class and must produce the image — that is what
    makes the denial above a denial rather than a uniformly broken route.
    """
    intruder = _seed_user(pg_sessionmaker, Role.teacher)
    owner, item_id = _seed_boxed_review_item(
        pg_sessionmaker, class_service, storage=storage_backend, scan=_synthetic_scan()
    )
    _use_review_service(client, review_service)
    _use_storage(client, storage_backend)

    _auth_as(client, intruder, Role.teacher)
    detail = client.get(f"/api/teacher/review/{item_id}")
    denied = client.get(f"/api/teacher/review/{item_id}/crop")
    assert denied.status_code == detail.status_code
    assert denied.headers["content-type"] != "image/png"
    assert not denied.content.startswith(b"\x89PNG\r\n\x1a\n")

    _auth_as(client, owner, Role.teacher)
    allowed = client.get(f"/api/teacher/review/{item_id}/crop")
    assert allowed.status_code == 200
    assert allowed.headers["content-type"] == "image/png"
    assert allowed.content.startswith(b"\x89PNG\r\n\x1a\n")


def _colour_counts(image: Image.Image) -> tuple[int, int, int]:
    """``(reddish, bluish, total)`` pixel counts, tolerant of anti-aliased edges."""
    total = image.width * image.height
    colours = image.getcolors(maxcolors=total) or []
    reddish = sum(n for n, (r, g, b) in colours if r > 200 and g < 80 and b < 80)
    bluish = sum(n for n, (r, g, b) in colours if b > 200 and r < 80 and g < 80)
    return reddish, bluish, total


def _dominant_colour(image: Image.Image) -> tuple[int, int, int]:
    colours = image.getcolors(maxcolors=image.width * image.height) or []
    return max(colours)[1]


def test_crop_route_returns_a_png_of_the_boxed_region(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
    storage_backend: FakeStorageBackend,
) -> None:
    """The happy path, asserting the image is real and correctly sized.

    The scan is built synthetically here -- never a real student scan, the repo
    is PUBLIC -- with a distinctive mark inside the box's region and a second,
    differently-coloured mark well outside it.

    Three independent assertions, because each catches a different wrong
    implementation: pixel equality against the same page rendered at the same
    DPI and cropped with the same helper pins *which page* and *which region*;
    the colour census catches a whole-page render (it would carry the outside
    mark) and a blank crop (it would carry neither mark); and the aspect ratio
    pins the crop to the box's proportion of the page rather than the page's
    own, which a 200 and a content-type check would both let through.
    """
    import pymupdf

    from lemely.io.rasterise import RasterisedPage
    from lemely.io.reread import crop_and_upscale
    from lemely.web.routers.review import _CROP_RENDER_DPI

    scan = _synthetic_scan()
    teacher, item_id = _seed_boxed_review_item(
        pg_sessionmaker, class_service, storage=storage_backend, scan=scan
    )
    _use_review_service(client, review_service)
    _use_storage(client, storage_backend)
    _auth_as(client, teacher, Role.teacher)

    resp = client.get(f"/api/teacher/review/{item_id}/crop")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.headers["cache-control"] == "private, no-store"
    got = Image.open(io.BytesIO(resp.content)).convert("RGB")

    with pymupdf.open(stream=scan, filetype="pdf") as doc:  # type: ignore[no-untyped-call]
        pixmap = doc.load_page(_MARKED_PAGE).get_pixmap(dpi=_CROP_RENDER_DPI)
    expected_png = crop_and_upscale(
        RasterisedPage(
            index=_MARKED_PAGE,
            width=pixmap.width,
            height=pixmap.height,
            png_bytes=pixmap.tobytes("png"),
        ),
        list(_MARK_BOX),
    )
    expected = Image.open(io.BytesIO(expected_png)).convert("RGB")
    assert got.size == expected.size
    assert got.tobytes() == expected.tobytes()

    reddish, bluish, total = _colour_counts(got)
    assert bluish == 0, "the crop reaches outside the box -- this is the page, not the region"
    assert reddish / total > 0.6, "the mark inside the box is missing -- this is a failed crop"

    # Padding scales both axes by the same factor, so the crop's aspect ratio
    # is the box's proportion of the page (~1.06 here), not the page's (~0.71).
    ymin, xmin, ymax, xmax = _MARK_BOX
    expected_aspect = ((xmax - xmin) * _PAGE_WIDTH_PT) / ((ymax - ymin) * _PAGE_HEIGHT_PT)
    assert abs(got.width / got.height - expected_aspect) < 0.03 * expected_aspect


def _synthetic_image_scan() -> bytes:
    """A single-page scan that is a PNG, not a PDF.

    A student scan is not always a PDF: the upload route applies no content-type
    restriction, and ``rasterise_scan_to_pages`` dispatches on content and wraps a
    non-PDF as one ``RasterisedPage(index=0)``. So an ``image/*`` upload really
    does get a ``source_box`` persisted against it, and the crop route really does
    have to serve one. Same marks and same geometry as ``_synthetic_scan`` so the
    colour census below can be the identical assertion.
    """
    from PIL import ImageDraw

    width, height = int(_PAGE_WIDTH_PT), int(_PAGE_HEIGHT_PT)
    image = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0.70 * width, 0.70 * height, 0.95 * width, 0.95 * height), fill=_OUTSIDE_RGB)
    ymin, xmin, ymax, xmax = _MARK_BOX
    draw.rectangle(
        (
            xmin / 1000 * width,
            ymin / 1000 * height,
            xmax / 1000 * width,
            ymax / 1000 * height,
        ),
        fill=_MARK_RGB,
    )
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def test_crop_route_serves_the_boxed_region_of_an_image_scan(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
    storage_backend: FakeStorageBackend,
) -> None:
    """An ``image/*`` scan must crop like a PDF one, and still honour ``box.page``.

    The route deliberately does not refuse a non-PDF: the 500 this route used to
    answer came from page *geometry*, which the area clamp now bounds for images
    and PDFs alike, so refusing images would 422 every legitimate image-scan crop
    while leaving the actual hole open.

    Both halves are needed. The first proves the crop is real and correctly placed
    -- the same colour census the PDF happy path uses, so "it worked" means the
    same thing for both. The second proves ``box.page`` is still enforced: a
    single-page image has only page 0, and a route that skipped the page bound for
    image streams would pass the first half alone.
    """
    scan = _synthetic_image_scan()
    teacher, item_id = _seed_boxed_review_item(
        pg_sessionmaker,
        class_service,
        storage=storage_backend,
        scan=scan,
        page=0,
        content_type="image/png",
    )
    stale_teacher, stale_page = _seed_boxed_review_item(
        pg_sessionmaker,
        class_service,
        storage=storage_backend,
        scan=scan,
        page=1,
        content_type="image/png",
        student_name="Ben",
    )
    _use_review_service(client, review_service)
    _use_storage(client, storage_backend)

    _auth_as(client, teacher, Role.teacher)
    resp = client.get(f"/api/teacher/review/{item_id}/crop")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "image/png"

    got = Image.open(io.BytesIO(resp.content)).convert("RGB")
    reddish, bluish, total = _colour_counts(got)
    assert bluish == 0, "the crop reaches outside the box -- this is the page, not the region"
    assert reddish / total > 0.6, "the mark inside the box is missing -- this is a failed crop"

    # A one-page image has no page 1, and the bound that says so must apply to an
    # image stream exactly as it does to a PDF. Asserted on the logged event, not
    # on the status alone: skipping the bound for image streams also produces a
    # 422, because `load_page(1)` then raises and the generic handler maps it --
    # and its message happens to contain the word "page" too. Only the event name
    # separates "refused by the bound" from "crashed and was caught".
    _auth_as(client, stale_teacher, Role.teacher)
    with structlog.testing.capture_logs() as logs:
        stale = client.get(f"/api/teacher/review/{stale_page}/crop")
    assert stale.status_code == 422, stale.text
    assert [e["event"] for e in logs if e["event"].startswith("review_crop_")] == [
        "review_crop_page_out_of_range"
    ]


_EXIF_ORIENTATION_TAG = 0x0112
_CORNER_RGB = (0, 255, 0)
# A landscape sensor frame, so a crop taken in the wrong orientation lands on a
# different part of the photo rather than on a symmetric copy of the right one.
_PHOTO_RAW_SIZE = (600, 300)


def _synthetic_phone_photo(orientation: int) -> bytes:
    """A JPEG whose pixels are stored sideways, with an EXIF flag saying so.

    Phones store a portrait photo as a landscape sensor frame plus EXIF
    orientation (6 is the usual one). The red mark covers ``_MARK_BOX`` in the
    RAW pixel grid, which is the grid extraction boxes against. A green corner
    inside the mark, at its raw top-left, shows which way up a crop was turned.
    """
    from PIL import ImageDraw

    width, height = _PHOTO_RAW_SIZE
    image = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0.70 * width, 0.70 * height, 0.95 * width, 0.95 * height), fill=_OUTSIDE_RGB)
    ymin, xmin, ymax, xmax = _MARK_BOX
    left, upper = xmin / 1000 * width, ymin / 1000 * height
    right, lower = xmax / 1000 * width, ymax / 1000 * height
    draw.rectangle((left, upper, right - 1, lower - 1), fill=_MARK_RGB)
    draw.rectangle(
        (left, upper, left + 0.25 * (right - left) - 1, upper + 0.4 * (lower - upper) - 1),
        fill=_CORNER_RGB,
    )
    exif = Image.Exif()
    exif[_EXIF_ORIENTATION_TAG] = orientation
    buf = io.BytesIO()
    image.save(buf, format="JPEG", exif=exif.tobytes(), quality=95)
    return buf.getvalue()


def _corner_position(image: Image.Image) -> tuple[float, float]:
    """Where the green corner sits inside the red-and-green mark, as 0-1 fractions."""
    mark_xs: list[int] = []
    mark_ys: list[int] = []
    corner_xs: list[int] = []
    corner_ys: list[int] = []
    pixels = image.load()
    assert pixels is not None
    for y in range(image.height):
        for x in range(image.width):
            r, g, b = pixels[x, y]  # type: ignore[misc]
            is_red = r > 200 and g < 80 and b < 80
            is_green = g > 200 and r < 80 and b < 80
            if is_red or is_green:
                mark_xs.append(x)
                mark_ys.append(y)
            if is_green:
                corner_xs.append(x)
                corner_ys.append(y)
    assert corner_xs, "no green corner at all -- this crop missed the mark"
    span_x = max(mark_xs) - min(mark_xs) or 1
    span_y = max(mark_ys) - min(mark_ys) or 1
    return (
        (sum(corner_xs) / len(corner_xs) - min(mark_xs)) / span_x,
        (sum(corner_ys) / len(corner_ys) - min(mark_ys)) / span_y,
    )


@pytest.mark.parametrize("orientation", [2, 3, 4, 5, 6, 7, 8])
def test_crop_route_crops_an_exif_rotated_photo_where_extraction_boxed_it(
    orientation: int,
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
    storage_backend: FakeStorageBackend,
    tmp_path: Path,
) -> None:
    """The box is in the raw pixel grid, so the crop must be taken there too.

    Extraction decodes an image upload with PIL, which does not apply EXIF
    orientation, so the model boxed the raw sensor frame. A renderer that
    applies the flag first (MuPDF does) crops the same numbers out of a turned
    image, which is a different part of the photo. The colour census shows the
    region is right. The green corner's position, measured against PIL's own
    ``exif_transpose`` of the whole photo, shows the crop is upright.
    """
    from PIL import ImageOps

    from lemely.io.rasterise import rasterise_scan_to_pages

    scan = _synthetic_phone_photo(orientation)

    # The premise, pinned: extraction sees the raw frame. If extraction ever
    # starts applying EXIF orientation, this fails, and the crop route has to
    # change with it.
    photo_path = tmp_path / "photo.jpg"
    photo_path.write_bytes(scan)
    (extracted,) = rasterise_scan_to_pages(photo_path)
    assert (extracted.width, extracted.height) == _PHOTO_RAW_SIZE

    teacher, item_id = _seed_boxed_review_item(
        pg_sessionmaker,
        class_service,
        storage=storage_backend,
        scan=scan,
        page=0,
        content_type="image/jpeg",
    )
    _use_review_service(client, review_service)
    _use_storage(client, storage_backend)
    _auth_as(client, teacher, Role.teacher)

    resp = client.get(f"/api/teacher/review/{item_id}/crop")
    assert resp.status_code == 200, resp.text
    got = Image.open(io.BytesIO(resp.content)).convert("RGB")

    reddish, bluish, total = _colour_counts(got)
    assert bluish == 0, "the crop reaches outside the box -- this is the page, not the region"
    assert reddish / total > 0.5, "the mark inside the box is missing -- wrong region"

    # Upright: the mark is wide in the raw frame, so it is tall once turned by
    # a quarter (5-8) and still wide after a half turn or a mirror (2-4).
    assert (got.height > got.width) == (orientation in (5, 6, 7, 8)), got.size
    upright = ImageOps.exif_transpose(Image.open(io.BytesIO(scan))).convert("RGB")
    want_x, want_y = _corner_position(upright)
    got_x, got_y = _corner_position(got)
    assert abs(got_x - want_x) < 0.15, (orientation, (got_x, got_y), (want_x, want_y))
    assert abs(got_y - want_y) < 0.15, (orientation, (got_x, got_y), (want_x, want_y))


def test_crop_route_404s_for_an_item_whose_attempt_has_no_upload(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
    storage_backend: FakeStorageBackend,
) -> None:
    """A quiz or seeded attempt has no scan, so there is nothing to crop.

    Paired with an otherwise identical item that *does* have one: a 404 is also
    what an unregistered route returns, so without the positive control this
    test would pass before the route existed and prove nothing.
    """
    teacher, item_id = _seed_boxed_review_item(
        pg_sessionmaker,
        class_service,
        storage=storage_backend,
        scan=_synthetic_scan(),
        with_upload=False,
    )
    scan_teacher, with_scan = _seed_boxed_review_item(
        pg_sessionmaker,
        class_service,
        storage=storage_backend,
        scan=_synthetic_scan(),
        student_name="Ben",
    )
    _use_review_service(client, review_service)
    _use_storage(client, storage_backend)

    _auth_as(client, teacher, Role.teacher)
    with structlog.testing.capture_logs() as logs:
        resp = client.get(f"/api/teacher/review/{item_id}/crop")
    assert resp.status_code == 404
    assert resp.headers["content-type"] != "image/png"
    # The bodies are deliberately collapsed, so the logged reason is the only
    # thing that can tell this 404 apart from the no-box one. Without this, a
    # lookup that checked the box columns before the upload would answer both
    # cases identically and no test here would notice.
    assert [e["reason"] for e in logs if e["event"] == "review_crop_absent"] == ["no_upload"]

    _auth_as(client, scan_teacher, Role.teacher)
    assert client.get(f"/api/teacher/review/{with_scan}/crop").status_code == 200


def test_crop_route_404s_for_an_item_with_no_persisted_box(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
    storage_backend: FakeStorageBackend,
) -> None:
    """The common case: the DTO's ``hasSourceBox`` already told the client not to ask.

    Both halves of ``hasSourceBox`` are exercised against the same route, so
    the 404 below is the route's answer for a boxless item rather than its
    answer for everything.
    """
    teacher, item_id = _seed_boxed_review_item(
        pg_sessionmaker,
        class_service,
        storage=storage_backend,
        scan=_synthetic_scan(),
        page=None,
    )
    boxed_teacher, boxed = _seed_boxed_review_item(
        pg_sessionmaker,
        class_service,
        storage=storage_backend,
        scan=_synthetic_scan(),
        student_name="Ben",
    )
    _use_review_service(client, review_service)
    _use_storage(client, storage_backend)

    _auth_as(client, teacher, Role.teacher)
    assert client.get(f"/api/teacher/review/{item_id}").json()["hasSourceBox"] is False
    with structlog.testing.capture_logs() as logs:
        resp = client.get(f"/api/teacher/review/{item_id}/crop")
    assert resp.status_code == 404
    assert resp.headers["content-type"] != "image/png"
    # As above: the reason is the discriminator, because the body cannot be.
    assert [e["reason"] for e in logs if e["event"] == "review_crop_absent"] == ["no_box"]

    _auth_as(client, boxed_teacher, Role.teacher)
    assert client.get(f"/api/teacher/review/{boxed}").json()["hasSourceBox"] is True
    assert client.get(f"/api/teacher/review/{boxed}/crop").status_code == 200


def test_crop_route_404s_identically_for_a_missing_item_and_a_missing_box(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
    storage_backend: FakeStorageBackend,
) -> None:
    """Every absence collapses to one indistinguishable 404, deliberately.

    A 404 whose body varied by reason would let a caller walk item ids and
    learn which of their own students have scans on file, and -- worse -- learn
    that an id it guessed names a real item at all. Same status, same body,
    with only the id the caller itself supplied differing.

    All six reasons are in here rather than the three that a body-equality
    assertion first covered: the console item and the missing ``uploads`` row
    were reasons nothing asserted, and the expired object is answered on a
    different code path (the route's, not the lookup's) so it is the one most
    likely to drift. "This student had a scan and it has since been deleted" is
    exactly the kind of thing a differing body would leak.
    """
    teacher, boxless = _seed_boxed_review_item(
        pg_sessionmaker,
        class_service,
        storage=storage_backend,
        scan=_synthetic_scan(),
        page=None,
    )
    gone_teacher, gone = _seed_boxed_review_item(
        pg_sessionmaker,
        class_service,
        storage=storage_backend,
        scan=_synthetic_scan(),
        store_object=False,
        student_name="Cara",
    )
    no_upload_teacher, no_upload = _seed_boxed_review_item(
        pg_sessionmaker,
        class_service,
        storage=storage_backend,
        scan=_synthetic_scan(),
        with_upload=False,
        student_name="Dev",
    )
    orphan_teacher, orphan = _seed_boxed_review_item(
        pg_sessionmaker,
        class_service,
        storage=storage_backend,
        scan=_synthetic_scan(),
        student_name="Esme",
    )
    console_teacher = _seed_user(pg_sessionmaker, Role.teacher)
    console_paper = _seed_console_paper(pg_sessionmaker, uploader=console_teacher)
    unknown = uuid.uuid4()
    boxed_teacher, boxed = _seed_boxed_review_item(
        pg_sessionmaker,
        class_service,
        storage=storage_backend,
        scan=_synthetic_scan(),
        student_name="Ben",
    )
    _use_review_service(client, review_service)
    _use_storage(client, storage_backend)

    # `upload_row_missing` cannot arise while the FK holds -- which is the point
    # of the branch, and the reason the row has to be manufactured here. Dropped
    # in this test's own throwaway database only.
    with pg_sessionmaker.begin() as session:
        fk = session.execute(
            sa.text(
                "SELECT conname FROM pg_constraint WHERE conrelid = 'attempts'::regclass "
                "AND contype = 'f' AND pg_get_constraintdef(oid) LIKE '%uploads%'"
            )
        ).scalar_one()
        session.execute(sa.text(f'ALTER TABLE attempts DROP CONSTRAINT "{fk}"'))
        orphaned = session.execute(
            sa.text(
                "SELECT upload_id FROM attempts WHERE id = "
                "(SELECT attempt_id FROM review_queue WHERE id = :item)"
            ),
            {"item": orphan},
        ).scalar_one()
        session.execute(sa.text("DELETE FROM uploads WHERE id = :uid"), {"uid": orphaned})

    console_item = next(
        row
        for row in _queue_rows(client, console_teacher)
        if row["source"] == "console_paper" and row["paperId"] == str(console_paper)
    )["itemId"]

    # The route exists and serves images -- otherwise the 404s below would match
    # each other trivially, for the wrong reason.
    _auth_as(client, boxed_teacher, Role.teacher)
    assert client.get(f"/api/teacher/review/{boxed}/crop").status_code == 200

    bodies = set()
    reasons = set()
    absences = (
        (teacher, boxless),
        (gone_teacher, gone),
        (no_upload_teacher, no_upload),
        (orphan_teacher, orphan),
        (console_teacher, console_item),
        (teacher, unknown),
    )
    for caller, item_id in absences:
        _auth_as(client, caller, Role.teacher)
        with structlog.testing.capture_logs() as logs:
            resp = client.get(f"/api/teacher/review/{item_id}/crop")
        assert resp.status_code == 404, (item_id, resp.status_code)
        bodies.add(resp.json()["detail"].replace(str(item_id), "<id>"))
        for entry in logs:
            if entry["event"] == "review_crop_absent":
                reasons.add(entry["reason"])
            elif entry["event"] == "review_crop_object_missing":
                reasons.add("object_missing")

    assert len(bodies) == 1, bodies
    # And each 404 came from the branch it was seeded to reach. Without this the
    # six requests above could all be answered by one branch -- a fixture that
    # failed to produce its condition would still return a matching body, and the
    # equality assertion would pass while covering nothing.
    assert reasons == {
        "no_box",
        "object_missing",
        "no_upload",
        "upload_row_missing",
        "console_item",
        "no_such_item",
    }, reasons


def test_crop_route_404s_when_the_stored_object_has_gone(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
    storage_backend: FakeStorageBackend,
) -> None:
    """A stored scan is not forever (GCS lifecycle, a cleared dev filesystem).

    404 to the caller -- there is no image -- but the reason is distinguishable
    server-side, because "the object expired" and "this item never had a box"
    need different operational responses.
    """
    teacher, item_id = _seed_boxed_review_item(
        pg_sessionmaker,
        class_service,
        storage=storage_backend,
        scan=_synthetic_scan(),
        store_object=False,
    )
    _use_review_service(client, review_service)
    _use_storage(client, storage_backend)
    _auth_as(client, teacher, Role.teacher)

    # Requested with an upper-cased id on purpose: the lookup logs the canonical
    # form, so a route logging the caller's raw path string would make one request
    # emit two spellings of one id, for no reason but that nobody normalised it.
    with structlog.testing.capture_logs() as logs:
        resp = client.get(f"/api/teacher/review/{str(item_id).upper()}/crop")
    assert resp.status_code == 404
    assert resp.headers["content-type"] != "image/png"
    missing = [entry for entry in logs if entry["event"] == "review_crop_object_missing"]
    assert missing, [entry["event"] for entry in logs]
    assert missing[0]["item_id"] == str(item_id)


def test_crop_route_422s_for_a_page_out_of_range_without_rendering(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
    storage_backend: FakeStorageBackend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A box captured against a different render must cost a bounds check, not a render.

    ``load_page`` is booby-trapped for the duration of the request: if the
    route rendered before checking ``doc.page_count``, the explosion's text
    would surface in the generic "could not render" 422 instead of the
    out-of-range one. That is what makes "without rendering" observable rather
    than asserted from the outside -- both failures are 422s, so the status
    code alone could not tell them apart.
    """
    import pymupdf

    teacher, item_id = _seed_boxed_review_item(
        pg_sessionmaker,
        class_service,
        storage=storage_backend,
        scan=_synthetic_scan(pages=_SCAN_PAGES),
        page=_SCAN_PAGES + 6,
    )
    _use_review_service(client, review_service)
    _use_storage(client, storage_backend)
    _auth_as(client, teacher, Role.teacher)

    def _explode(self: object, *args: object, **kwargs: object) -> object:
        raise AssertionError("load_page called before the page-count check")

    monkeypatch.setattr(pymupdf.Document, "load_page", _explode)

    resp = client.get(f"/api/teacher/review/{item_id}/crop")
    assert resp.status_code == 422
    assert "load_page called" not in resp.json()["detail"]
    assert "page" in resp.json()["detail"].lower()


def test_crop_route_refuses_a_console_item(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
    storage_backend: FakeStorageBackend,
) -> None:
    """Console papers are out of scope for this route (issue #245), so: 404.

    Not because no scan exists -- a console paper's scan is a ``TeacherPaper``
    upload and its box is often in ``report_json``. Serving it would need a
    second lookup against ``teacher_paper_visible``, which grants
    ``platform_admin`` every paper, and this queue deliberately refuses that
    super-role grant. Widening the crop route to console items would inherit
    the grant, so the route must not reach one at all.
    """
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    _seed_console_paper(pg_sessionmaker, uploader=teacher)
    attempt_teacher, attempt_item = _seed_boxed_review_item(
        pg_sessionmaker,
        class_service,
        storage=storage_backend,
        scan=_synthetic_scan(),
        student_name="Ben",
    )
    _use_review_service(client, review_service)
    _use_storage(client, storage_backend)

    _auth_as(client, teacher, Role.teacher)
    rows = client.get("/api/teacher/review").json()["items"]
    console = next(row for row in rows if row["source"] == "console_paper")
    resp = client.get(f"/api/teacher/review/{console['itemId']}/crop")
    assert resp.status_code == 404
    assert resp.headers["content-type"] != "image/png"

    # The attempt-backed half of the same queue does serve an image, so the
    # 404 above is about the item's source and not about the route.
    _auth_as(client, attempt_teacher, Role.teacher)
    assert client.get(f"/api/teacher/review/{attempt_item}/crop").status_code == 200


def test_crop_route_honours_the_queues_no_super_role_bypass(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
    storage_backend: FakeStorageBackend,
) -> None:
    """``platform_admin`` sees no classes, so it sees no student's scan either."""
    admin = _seed_user(pg_sessionmaker, Role.platform_admin)
    _, item_id = _seed_boxed_review_item(
        pg_sessionmaker, class_service, storage=storage_backend, scan=_synthetic_scan()
    )
    _use_review_service(client, review_service)
    _use_storage(client, storage_backend)
    _auth_as(client, admin, Role.platform_admin)

    detail = client.get(f"/api/teacher/review/{item_id}")
    crop = client.get(f"/api/teacher/review/{item_id}/crop")
    assert crop.status_code == detail.status_code
    assert crop.headers["content-type"] != "image/png"


def test_crop_route_does_not_mutate_the_box_it_was_handed(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
    storage_backend: FakeStorageBackend,
) -> None:
    """Two requests for the same item must return the same image, byte for byte.

    Rescaling the 0-1000 coordinates to pixels in place is the natural way to
    write this route and is exactly the trap: the second request would then
    scale already-scaled coordinates and return a different (wrong) crop.
    """
    teacher, item_id = _seed_boxed_review_item(
        pg_sessionmaker, class_service, storage=storage_backend, scan=_synthetic_scan()
    )
    _use_review_service(client, review_service)
    _use_storage(client, storage_backend)
    _auth_as(client, teacher, Role.teacher)

    first = client.get(f"/api/teacher/review/{item_id}/crop")
    second = client.get(f"/api/teacher/review/{item_id}/crop")
    assert first.status_code == second.status_code == 200
    assert first.content == second.content


def test_crop_route_refuses_a_box_that_survived_without_revalidation() -> None:
    """``model_copy``/``model_construct`` skip the validator; this guard does not.

    ``SourceBox``'s validator runs at construction only, so a box that reached
    the route through a copy -- or out of columns written before
    ``ck_question_results_source_box_positive_area`` existed -- is not
    guaranteed sane. ``PIL.Image.crop`` does not raise on an inverted or
    zero-area rectangle: it returns an empty or garbage image, which would
    render as a blank crop beside a real student's answer. So the bounds and
    the area are checked before any pixel arithmetic, and the route fails
    closed rather than rendering.
    """
    from lemely.web.routers.review import _require_renderable_box

    unusable = [
        [300, 100, 100, 400],  # inverted vertically
        [100, 400, 300, 100],  # inverted horizontally
        [100, 100, 100, 400],  # zero height
        [100, 100, 300, 100],  # zero width
        [-1, 100, 300, 400],  # below the scale
        [100, 100, 300, 1001],  # above the scale
    ]
    for coords in unusable:
        with pytest.raises(HTTPException) as caught:
            _require_renderable_box(SourceBox.model_construct(page=0, box=coords), item_id="item")
        assert caught.value.status_code == 422

    # A negative page is the worst of these, and the only one that would not
    # have looked like a failure: `SourceBox.page`'s `ge=0` is validator-only,
    # the route's `box.page >= doc.page_count` bound does not exclude it, and
    # `doc.load_page(-1)` does not raise -- it returns the LAST page. So an
    # unvalidated `page=-1` served a different student's-page region with a 200
    # and every appearance of success.
    with pytest.raises(HTTPException) as caught:
        _require_renderable_box(
            SourceBox.model_construct(page=-1, box=list(_MARK_BOX)), item_id="item"
        )
    assert caught.value.status_code == 422

    # The same predicate must let a real box through, or it would prove nothing.
    assert _require_renderable_box(SourceBox(page=0, box=list(_MARK_BOX)), item_id="item") is None


def test_page_indices_agree_between_the_extractor_and_the_crop_renderer(
    tmp_path: Path,
) -> None:
    """``source_box.page`` is an index into the extractor's render; the crop route
    renders with a different library. Both are 0-based document order, so the
    indices coincide -- but that is an assumption two dependencies could break
    independently, and nothing else in the codebase would notice.
    """
    import pymupdf

    from lemely.io.rasterise import rasterise_pdf_to_pages
    from lemely.web.routers.review import _CROP_RENDER_DPI

    # One distinctive mark per page: a renderer that reordered pages, or
    # counted from one, would show a different colour at the same index.
    marks = [(255, 0, 0), (0, 255, 0), (0, 0, 255)]
    doc = pymupdf.open()
    try:
        for rgb in marks:
            page = doc.new_page(width=_PAGE_WIDTH_PT, height=_PAGE_HEIGHT_PT)
            page.draw_rect(
                pymupdf.Rect(0, 0, _PAGE_WIDTH_PT, _PAGE_HEIGHT_PT),
                color=None,
                fill=_fill(rgb),
            )
        pdf_path = tmp_path / "three-pages.pdf"
        pdf_path.write_bytes(doc.tobytes())
    finally:
        doc.close()

    extractor_pages = rasterise_pdf_to_pages(pdf_path)
    assert [page.index for page in extractor_pages] == [0, 1, 2]

    # The instrument first. This test cannot go red while the two renderers agree
    # on page order -- that is what a characterisation test is -- so the only
    # failure available to it is its own apparatus breaking: three pages that
    # rendered identically, or a `_dominant_colour` that stopped discriminating,
    # would satisfy every "page N shows mark N" assertion below while proving
    # nothing at all.
    rendered = {
        _dominant_colour(Image.open(io.BytesIO(page.png_bytes)).convert("RGB"))
        for page in extractor_pages
    }
    assert len(rendered) == 3, rendered

    with pymupdf.open(pdf_path) as renderer:  # type: ignore[no-untyped-call]
        for index, expected_rgb in enumerate(marks):
            via_extractor = Image.open(io.BytesIO(extractor_pages[index].png_bytes)).convert("RGB")
            via_renderer = Image.open(
                io.BytesIO(
                    renderer.load_page(index).get_pixmap(dpi=_CROP_RENDER_DPI).tobytes("png")
                )
            ).convert("RGB")
            assert _dominant_colour(via_extractor) == expected_rgb
            assert _dominant_colour(via_renderer) == expected_rgb
            # Named negatively too: "page N is not page N+1's colour" is what
            # an off-by-one in either renderer would actually break, and it
            # fails even if `expected_rgb` and the fixture drifted together.
            assert _dominant_colour(via_renderer) != marks[(index + 1) % len(marks)]


# ---------------------------------------------------------------------------
# Review fixes on 1a0dabc2 (I-1, I-2, M-2, M-3, M-4).
# ---------------------------------------------------------------------------


@pytest.fixture
def lenient_client() -> Iterator[TestClient]:
    """A client that returns 500 rather than re-raising the handler's exception.

    ``TestClient``'s default re-raises, which makes "this must never be a 500"
    unassertable: the test errors out before it sees a status code. This one
    lets the response through so the assertion can be written as the claim.
    """
    app = create_app()
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


def test_crop_route_never_500s_on_a_page_too_large_to_rasterise(
    lenient_client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
    storage_backend: FakeStorageBackend,
) -> None:
    """A tiny PDF declaring enormous pages is a decompression bomb, not a big upload.

    Under 1.4KB, three pages, each declaring an 8000x8000pt page: at 150 dpi that
    is a ~278 megapixel render, past twice ``PIL``'s ``MAX_IMAGE_PIXELS``, so
    ``DecompressionBombError`` is raised from ``Image.open`` inside
    ``crop_and_upscale`` -- which sat outside the route's
    ``except Exception -> 422`` block, so it escaped as a 500. A page landing
    just under that ceiling did not raise at all and simply rendered, at
    gigabytes of peak RSS for one request.

    It is reachable: the student upload route validates neither content type nor
    page geometry, and extraction does not pre-empt it either, because
    ``rasterise_pdf_to_pages`` renders the same page fine (pypdfium2 has no bomb
    ceiling). So a ``source_box`` is persisted for exactly the upload this route
    then chokes on.

    Whatever the outcome, it is this route's documented vocabulary -- an image,
    or the 422 every other unrenderable scan gets. Never a 500.
    """
    _use_review_service(lenient_client, review_service)
    _use_storage(lenient_client, storage_backend)

    # 8000pt trips PIL's ceiling at the preferred DPI; 500,000pt is over the
    # render ceiling even at 1 dpi, so it is refused before anything is
    # rasterised. Both are the same class of input and both must stay inside this
    # route's vocabulary.
    for index, size in enumerate((8000.0, 500_000.0)):
        scan = _synthetic_scan(width=size, height=size)
        # The bomb's whole character: a trivially small file, so no upload-size
        # limit anywhere upstream would ever have stopped it.
        assert len(scan) < 2_000, (size, len(scan))

        teacher, item_id = _seed_boxed_review_item(
            pg_sessionmaker,
            class_service,
            storage=storage_backend,
            scan=scan,
            student_name=f"Bomb {index}",
        )
        _auth_as(lenient_client, teacher, Role.teacher)

        resp = lenient_client.get(f"/api/teacher/review/{item_id}/crop")
        assert resp.status_code != 500, (size, resp.text)
        assert resp.status_code in (200, 422), (size, resp.status_code)


def test_has_source_box_is_false_when_the_attempt_has_no_upload(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
    storage_backend: FakeStorageBackend,
) -> None:
    """The flag must not be true for an item the crop route is certain to refuse.

    Five ``source_box_*`` columns and no ``attempts.upload_id`` is a real
    combination -- a quiz or an imported attempt can carry a box with no scan
    behind it -- and the flag said ``true`` for it while the crop route returned
    404. The check costs nothing: ``get_item`` already holds the ``attempt``.

    Storage expiry is deliberately NOT part of this: it is a timing condition,
    so nothing checked when the detail is read can promise anything about the
    object at crop time. That is why the flag's contract says a crop "may be"
    available and a 404 is absence, not an error.
    """
    teacher, no_upload = _seed_boxed_review_item(
        pg_sessionmaker,
        class_service,
        storage=storage_backend,
        scan=_synthetic_scan(),
        with_upload=False,
    )
    with_upload_teacher, with_upload = _seed_boxed_review_item(
        pg_sessionmaker,
        class_service,
        storage=storage_backend,
        scan=_synthetic_scan(),
        student_name="Ben",
    )
    _use_review_service(client, review_service)
    _use_storage(client, storage_backend)

    _auth_as(client, teacher, Role.teacher)
    assert client.get(f"/api/teacher/review/{no_upload}").json()["hasSourceBox"] is False
    assert client.get(f"/api/teacher/review/{no_upload}/crop").status_code == 404

    # The box alone is not what the flag reports, but it is still necessary: the
    # item that has both must still say true, or the flag would just be off.
    _auth_as(client, with_upload_teacher, Role.teacher)
    assert client.get(f"/api/teacher/review/{with_upload}").json()["hasSourceBox"] is True
    assert client.get(f"/api/teacher/review/{with_upload}/crop").status_code == 200


def test_a_pil_failure_inside_the_crop_is_a_422_not_a_500(
    lenient_client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
    storage_backend: FakeStorageBackend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The area ceiling and the error handler are two defences, and this is the second.

    With ``_MAX_CROP_PX`` in place an ordinary scan never reaches PIL's own
    ceiling, which would leave the handler's coverage of ``crop_and_upscale``
    asserted by nothing. So PIL's ceiling is lowered instead of the page being
    enlarged: ``Image.MAX_IMAGE_PIXELS`` is dropped far below an A4 render, which
    makes ``Image.open`` inside ``crop_and_upscale`` raise
    ``DecompressionBombError`` on a perfectly ordinary page.

    That is the exact shape of the escape: ``crop_and_upscale`` used to sit after
    the ``except Exception -> 422`` block, so anything PIL raised left the route
    as a 500. Independent of page geometry, and of this module's own constant.
    """
    from PIL import Image as PILImage

    monkeypatch.setattr(PILImage, "MAX_IMAGE_PIXELS", 16)

    teacher, item_id = _seed_boxed_review_item(
        pg_sessionmaker, class_service, storage=storage_backend, scan=_synthetic_scan()
    )
    _use_review_service(lenient_client, review_service)
    _use_storage(lenient_client, storage_backend)
    _auth_as(lenient_client, teacher, Role.teacher)

    resp = lenient_client.get(f"/api/teacher/review/{item_id}/crop")
    assert resp.status_code == 422, (resp.status_code, resp.text)
    assert "Could not render this scan" in resp.json()["detail"]


def test_the_crop_is_never_kept_in_the_browser_cache(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
    storage_backend: FakeStorageBackend,
) -> None:
    """A student's handwriting must not outlive the check that let a teacher see it.

    The browser cache is keyed by URL, not by the bearer token. A cached crop
    could be reopened on a shared school computer after the teacher signs out,
    or after the student leaves the class, with no request reaching the server.
    """
    teacher, item_id = _seed_boxed_review_item(
        pg_sessionmaker, class_service, storage=storage_backend, scan=_synthetic_scan()
    )
    _use_review_service(client, review_service)
    _use_storage(client, storage_backend)
    _auth_as(client, teacher, Role.teacher)

    resp = client.get(f"/api/teacher/review/{item_id}/crop")
    assert resp.status_code == 200
    directives = {d.strip() for d in resp.headers["cache-control"].split(",")}
    assert "no-store" in directives, directives
    assert not any(d.startswith("max-age") for d in directives), directives


def test_an_unrenderable_scan_does_not_echo_the_renderer_error(
    lenient_client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
    storage_backend: FakeStorageBackend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The client gets a fixed message; the renderer's own text goes to the log.

    Requested with the id upper-cased, so the log line is shown to carry the
    canonical id and not whatever spelling the caller sent.
    """
    from PIL import Image as PILImage

    monkeypatch.setattr(PILImage, "MAX_IMAGE_PIXELS", 16)
    teacher, item_id = _seed_boxed_review_item(
        pg_sessionmaker, class_service, storage=storage_backend, scan=_synthetic_scan()
    )
    _use_review_service(lenient_client, review_service)
    _use_storage(lenient_client, storage_backend)
    _auth_as(lenient_client, teacher, Role.teacher)

    with structlog.testing.capture_logs() as logs:
        resp = lenient_client.get(f"/api/teacher/review/{str(item_id).upper()}/crop")
    assert resp.status_code == 422, (resp.status_code, resp.text)
    assert resp.json()["detail"] == "Could not render this scan"

    (failed,) = [e for e in logs if e["event"] == "review_crop_render_failed"]
    assert failed["item_id"] == str(item_id)
    assert "decompression bomb" in failed["error"]


def test_the_route_and_the_extractor_sniff_a_pdf_the_same_way(tmp_path: Path) -> None:
    """One check, two spellings, and they already disagreed on four bytes.

    The crop route tested ``startswith(b"%PDF")``; ``rasterise`` tested
    ``== b"%PDF-"``. A stream of exactly ``b"%PDF"`` was a PDF to one and not to
    the other, which means the route could hand MuPDF a ``filetype`` the
    extractor's own dispatch would have rejected. Asserted over the same bytes
    through both entry points, so the two cannot drift apart again.
    """
    from lemely.io.rasterise import _looks_like_pdf, looks_like_pdf

    headers = [
        b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n",
        b"%PDF-",
        b"%PDF",  # the case the two spellings disagreed on
        b"%PDFX",
        b"\x89PNG\r\n\x1a\n",
        b"%",
        b"",
    ]
    for header in headers:
        path = tmp_path / "scan"
        path.write_bytes(header)
        assert looks_like_pdf(header) == _looks_like_pdf(path), header


# ---------------------------------------------------------------------------
# The crop's pixel ceiling. The render was bounded, but the response was not:
# padding and the 2x upscale took a 40 Mpx render to a 160 Mpx PNG, ~1.4 GB of
# peak memory for one request on a 1 GiB instance.
# ---------------------------------------------------------------------------

# The review's page: at 150 dpi it lands on the old 40 Mpx render ceiling.
_OVERSIZED_PAGE_PT = 3035.0
_WHOLE_PAGE_BOX = [0, 0, 1000, 1000]


@pytest.mark.parametrize("box", [_MARK_BOX, _WHOLE_PAGE_BOX], ids=["mark", "whole-page"])
def test_crop_of_an_oversized_pdf_page_stays_under_the_pixel_ceiling(
    box: list[int],
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
    storage_backend: FakeStorageBackend,
) -> None:
    """A 520-byte PDF can declare a page this big, so its size bounds nothing.

    The census on the mark case shows the smaller output is still the right
    region; the ceiling is paid for in resolution, never in place.
    """
    from lemely.web.routers.review import _MAX_CROP_PX

    scan = _synthetic_scan(width=_OVERSIZED_PAGE_PT, height=_OVERSIZED_PAGE_PT)
    teacher, item_id = _seed_boxed_review_item(
        pg_sessionmaker, class_service, storage=storage_backend, scan=scan, box=box
    )
    _use_review_service(client, review_service)
    _use_storage(client, storage_backend)
    _auth_as(client, teacher, Role.teacher)

    resp = client.get(f"/api/teacher/review/{item_id}/crop")
    assert resp.status_code == 200, resp.text
    got = Image.open(io.BytesIO(resp.content)).convert("RGB")
    assert got.width * got.height <= _MAX_CROP_PX, got.size

    if box == _MARK_BOX:
        reddish, bluish, total = _colour_counts(got)
        assert bluish == 0, "the crop reaches outside the box -- this is the page, not the region"
        assert reddish / total > 0.6, "the mark inside the box is missing -- this is a failed crop"


def test_pdf_crop_plan_keeps_every_output_under_the_ceiling() -> None:
    """The plan picks the DPI and the upscale from the padded box, not the page.

    An ordinary answer on an A4 page must come out exactly as it did before the
    ceiling existed (full DPI, full upscale), or the ceiling would cost every
    teacher sharpness to guard against a crafted file.
    """
    import pymupdf

    from lemely.io.reread import REREAD_UPSCALE
    from lemely.web.routers.review import _CROP_RENDER_DPI, _MAX_CROP_PX, _pdf_crop_plan

    a4 = _pdf_crop_plan(pymupdf.Rect(0, 0, _PAGE_WIDTH_PT, _PAGE_HEIGHT_PT), list(_MARK_BOX))
    assert a4 is not None
    assert (a4.dpi, a4.upscale) == (_CROP_RENDER_DPI, REREAD_UPSCALE)

    sizes = ((_PAGE_WIDTH_PT, _PAGE_HEIGHT_PT), (_OVERSIZED_PAGE_PT, _OVERSIZED_PAGE_PT))
    sizes += ((8000.0, 8000.0), (20_000.0, 3_000.0), (14_400.0, 14_400.0))
    boxes = (_WHOLE_PAGE_BOX, list(_MARK_BOX), [0, 0, 1, 1000], [499, 0, 501, 1000])
    for width, height in sizes:
        for box in boxes:
            plan = _pdf_crop_plan(pymupdf.Rect(0, 0, width, height), box)
            assert plan is not None, (width, height, box)
            region_w, region_h = plan.size
            assert region_w * region_h * plan.upscale**2 <= _MAX_CROP_PX, (width, height, box)
            assert 1 <= plan.dpi <= _CROP_RENDER_DPI

    # Clamped, not merely capped: a whole 8000pt page cannot fit at 150 dpi, so
    # a plan that kept the preferred DPI would only pass the bound above by
    # accident of the arithmetic.
    big = _pdf_crop_plan(pymupdf.Rect(0, 0, 8000, 8000), _WHOLE_PAGE_BOX)
    assert big is not None
    assert big.dpi < _CROP_RENDER_DPI

    # A page no DPI can fit is refused; the route answers 422.
    assert _pdf_crop_plan(pymupdf.Rect(0, 0, 500_000, 500_000), _WHOLE_PAGE_BOX) is None


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("cropbox", [False, True], ids=["mediabox", "cropbox"])
def test_a_clipped_render_is_the_same_pixels_as_cropping_the_whole_page(
    rotation: int, cropbox: bool
) -> None:
    """The route renders only the padded box. That is only safe if it is the
    same image as rendering the page and cropping, on turned and cropped pages
    too, where MuPDF's page space and the rendered page differ.
    """
    import pymupdf

    from lemely.io.reread import padded_crop_rect
    from lemely.web.routers.review import _pdf_crop_plan

    doc = pymupdf.open()
    try:
        page = doc.new_page(width=_PAGE_WIDTH_PT, height=_PAGE_HEIGHT_PT)
        page.draw_rect(pymupdf.Rect(60, 100, 200, 250), color=None, fill=_fill(_MARK_RGB))
        page.draw_rect(pymupdf.Rect(300, 500, 420, 700), color=None, fill=_fill(_OUTSIDE_RGB))
        page.insert_text((100, 400), "x = 3.2 m/s", fontsize=20)
        if cropbox:
            page.set_cropbox(pymupdf.Rect(40, 60, 500, 700))
        page.set_rotation(rotation)

        for box in (list(_MARK_BOX), _WHOLE_PAGE_BOX, [37, 911, 38, 912]):
            plan = _pdf_crop_plan(page.rect, box)
            assert plan is not None
            clipped = page.get_pixmap(matrix=pymupdf.Matrix(plan.zoom, plan.zoom), clip=plan.clip)
            assert (clipped.width, clipped.height) == plan.size, box

            whole = page.get_pixmap(matrix=pymupdf.Matrix(plan.zoom, plan.zoom))
            rect = padded_crop_rect(whole.width, whole.height, box)
            expected = Image.open(io.BytesIO(whole.tobytes("png"))).convert("RGB").crop(rect)
            got = Image.open(io.BytesIO(clipped.tobytes("png"))).convert("RGB")
            assert got.tobytes() == expected.tobytes(), box
    finally:
        doc.close()


def _streamed_png(width: int, height: int) -> bytes:
    """A grey PNG built row by row, so the test never holds the decoded image."""
    import struct
    import zlib

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = struct.pack(">I", zlib.crc32(tag + data))
        return struct.pack(">I", len(data)) + tag + data + crc

    compressor = zlib.compressobj(9)
    row = b"\x00" + b"\x80" * width
    idat = bytearray()
    for _ in range(height):
        idat += compressor.compress(row)
    idat += compressor.flush()
    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    signature = b"\x89PNG\r\n\x1a\n"
    return signature + chunk(b"IHDR", header) + chunk(b"IDAT", bytes(idat)) + chunk(b"IEND", b"")


def test_an_image_scan_too_large_to_decode_is_refused_before_decoding(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
    storage_backend: FakeStorageBackend,
) -> None:
    """An image has no DPI to turn down, so its decode is bounded by refusing it.

    A few hundred kilobytes of PNG can declare tens of megapixels. PIL lets it
    through (its own bomb ceiling is higher), so extraction can box it. The
    route reads the size from the header and refuses first.
    """
    from lemely.web.routers.review import _MAX_DECODE_PX

    side = int(_MAX_DECODE_PX**0.5) + 100
    scan = _streamed_png(side, side)
    assert len(scan) < 200_000
    teacher, item_id = _seed_boxed_review_item(
        pg_sessionmaker,
        class_service,
        storage=storage_backend,
        scan=scan,
        page=0,
        content_type="image/png",
    )
    _use_review_service(client, review_service)
    _use_storage(client, storage_backend)
    _auth_as(client, teacher, Role.teacher)

    with structlog.testing.capture_logs() as logs:
        resp = client.get(f"/api/teacher/review/{item_id}/crop")
    assert resp.status_code == 422, (resp.status_code, len(resp.content))
    assert [e["event"] for e in logs if e["event"].startswith("review_crop_")] == [
        "review_crop_page_too_large"
    ]


def test_a_high_resolution_photo_is_decoded_smaller_and_still_cropped_right(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
    storage_backend: FakeStorageBackend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 43 Mpx JPEG is a real phone photo (high-resolution mode), not an attack.

    It is over the decode ceiling, so it is decoded at a reduced scale, which
    JPEG supports natively, rather than refused. The box is normalised, so the
    smaller decode lands on the same region.
    """
    from PIL import ImageDraw

    from lemely.web.routers.review import _MAX_CROP_PX, _MAX_DECODE_PX

    width, height = 8000, 5400
    assert width * height > _MAX_DECODE_PX
    image = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0.70 * width, 0.70 * height, 0.95 * width, 0.95 * height), fill=_OUTSIDE_RGB)
    ymin, xmin, ymax, xmax = _MARK_BOX
    draw.rectangle(
        (xmin / 1000 * width, ymin / 1000 * height, xmax / 1000 * width, ymax / 1000 * height),
        fill=_MARK_RGB,
    )
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=90)
    del image, draw

    teacher, item_id = _seed_boxed_review_item(
        pg_sessionmaker,
        class_service,
        storage=storage_backend,
        scan=buf.getvalue(),
        page=0,
        content_type="image/jpeg",
    )
    _use_review_service(client, review_service)
    _use_storage(client, storage_backend)
    _auth_as(client, teacher, Role.teacher)

    resp = client.get(f"/api/teacher/review/{item_id}/crop")
    assert resp.status_code == 200, resp.text
    # Lifted only after the route has answered, so an oversized response is
    # reported as its size below rather than as PIL's own bomb error.
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", None)
    got = Image.open(io.BytesIO(resp.content)).convert("RGB")
    assert got.width * got.height <= _MAX_CROP_PX, got.size

    reddish, bluish, total = _colour_counts(got)
    assert bluish == 0, "the crop reaches outside the box -- this is the page, not the region"
    assert reddish / total > 0.6, "the mark inside the box is missing -- this is a failed crop"


@pytest.mark.parametrize("mode", ["RGB", "L", "P"])
def test_an_image_region_over_the_ceiling_is_scaled_down_not_refused(
    mode: str,
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    review_service: ReviewService,
    storage_backend: FakeStorageBackend,
) -> None:
    """A whole-page answer on a large scan is a real region, just a big one.

    It is scaled to fit rather than refused, in every mode a scanner writes:
    colour, greyscale and palette. The page is one-pixel black and white
    stripes, the finest detail handwriting has. Filtered, they come out grey;
    point-sampled, which is what PIL does to a palette image it resizes as
    is, they come out as aliased black and white.
    """
    from PIL import ImageDraw

    from lemely.web.routers.review import _MAX_CROP_PX

    width, height = 3000, 2000
    image = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    for x in range(0, width, 2):
        draw.line((x, 0, x, height), fill=(0, 0, 0))
    image = image.convert(mode)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    teacher, item_id = _seed_boxed_review_item(
        pg_sessionmaker,
        class_service,
        storage=storage_backend,
        scan=buf.getvalue(),
        page=0,
        content_type="image/png",
        box=_WHOLE_PAGE_BOX,
    )
    _use_review_service(client, review_service)
    _use_storage(client, storage_backend)
    _auth_as(client, teacher, Role.teacher)

    resp = client.get(f"/api/teacher/review/{item_id}/crop")
    assert resp.status_code == 200, resp.text
    got = Image.open(io.BytesIO(resp.content)).convert("RGB")
    assert width * height > _MAX_CROP_PX
    assert got.width * got.height <= _MAX_CROP_PX, got.size
    assert abs(got.width / got.height - width / height) < 0.01
    grey = got.convert("L")
    histogram = grey.histogram()
    mid_tones = sum(histogram[32:224]) / (grey.width * grey.height)
    assert mid_tones > 0.5, f"{mid_tones:.2f} mid-tone: the stripes were point-sampled"
