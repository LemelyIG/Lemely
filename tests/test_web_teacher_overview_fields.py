"""The five additive overview fields behind the teacher home (spec 2026-11-02)."""

# Fixtures are imported from test_web_teacher so pytest resolves them here.
# ruff: noqa: F811
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from lemely.core.history import PaperRecord
from lemely.core.schemas import REVIEW_CONFIDENCE_THRESHOLD
from lemely.db.class_repo import ClassService
from lemely.db.models import Role
from lemely.io.history_store import HistoryStore
from lemely.web.routers.teacher import (
    _confidence_buckets,
    _previous_grade,
    _review_estimate_minutes,
)
from tests.test_web_teacher import (
    _auth_as,
    _forget_last_outcome,  # noqa: F401
    _join_student,
    _metadata,
    _seed_history_record,
    _seed_user,
    _use_class_service,
    ack_service,  # noqa: F401
    bank_service,  # noqa: F401
    class_service,  # noqa: F401
    client,  # noqa: F401
    corpus_repo,  # noqa: F401
    gemini_client,  # noqa: F401
    history_store,  # noqa: F401
    paper_repo,  # noqa: F401
    pg_sessionmaker,  # noqa: F401
    settings,  # noqa: F401
    storage_backend,  # noqa: F401
    teacher_user,  # noqa: F401
)


def test_buckets_are_ten_wide_and_skip_missing_confidence() -> None:
    assert _confidence_buckets([0.05, 0.15, 0.15, 0.99, 1.0, None]) == [
        1,
        2,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        2,
    ]
    assert _confidence_buckets([]) == [0] * 10


def test_buckets_skip_non_finite_confidence() -> None:
    nan, inf = float("nan"), float("inf")
    assert _confidence_buckets([nan, inf, -inf, 0.55]) == [0, 0, 0, 0, 0, 1, 0, 0, 0, 0]


def _record(grade: str, subject_code: str) -> PaperRecord:
    return PaperRecord(
        student_id="s1",
        metadata=_metadata(subject_code=subject_code),
        awarded_marks=40,
        maximum_marks=80,
        percentage=50.0,
        grade=grade,
        weak_areas=[],
        recorded_at="2026-11-01T00:00:00Z",
    )


def test_previous_grade_only_compares_the_latest_papers_subject() -> None:
    # Physics B, then Maths A, then Physics D: the previous *Physics* grade is B,
    # never the Maths A that happens to sit between them.
    records = [_record("B", "0625"), _record("A", "0580"), _record("D", "0625")]
    assert _previous_grade(records) == "B"
    # A different-subject paper alone is not a previous grade.
    assert _previous_grade([_record("A", "0580"), _record("D", "0625")]) is None


def test_previous_grade_is_returned_even_when_unchanged() -> None:
    assert _previous_grade([_record("C", "0625"), _record("C", "0625")]) == "C"


def test_estimate_rounds_up_and_is_zero_when_empty() -> None:
    assert _review_estimate_minutes(0) == 0
    assert _review_estimate_minutes(1) == 1
    assert _review_estimate_minutes(23) == 8  # ceil(23 * 20 / 60)


def test_empty_teacher_gets_zeroed_fields(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], class_service: ClassService
) -> None:
    teacher_id = _seed_user(pg_sessionmaker, Role.teacher)
    _use_class_service(client, class_service)
    _auth_as(client, teacher_id, Role.teacher)
    body = client.get("/api/teacher/overview").json()
    assert body["paperCount"] == 0
    assert body["pendingReviewCount"] == 0
    assert body["reviewConfidenceBuckets"] == [0] * 10
    assert body["reviewEstimateMinutes"] == 0
    assert body["reviewConfidenceThreshold"] == REVIEW_CONFIDENCE_THRESHOLD


def test_paper_count_and_previous_grade(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    history_store: HistoryStore,
) -> None:
    teacher_id = _seed_user(pg_sessionmaker, Role.teacher)
    cls = class_service.create_class(teacher_id, "Physics 10A")
    assert cls.join_code is not None
    ziad = _join_student(pg_sessionmaker, class_service, cls.join_code, "Ziad")
    _seed_history_record(history_store, str(ziad), percentage=72.0, grade="B")
    _seed_history_record(history_store, str(ziad), percentage=65.0, grade="C")
    _seed_history_record(history_store, str(ziad), percentage=58.0, grade="D")
    _use_class_service(client, class_service)
    _auth_as(client, teacher_id, Role.teacher)
    body = client.get("/api/teacher/overview").json()
    assert body["paperCount"] == 3
    (student,) = body["atRisk"]
    assert student["grade"] == "D"
    assert student["previousGrade"] == "C"


def test_previous_grade_is_null_with_one_paper(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    history_store: HistoryStore,
) -> None:
    teacher_id = _seed_user(pg_sessionmaker, Role.teacher)
    cls = class_service.create_class(teacher_id, "Physics 10B")
    assert cls.join_code is not None
    nour = _join_student(pg_sessionmaker, class_service, cls.join_code, "Nour")
    _seed_history_record(history_store, str(nour), percentage=40.0, grade="E")
    assert _previous_grade(history_store.load(str(nour)).records) is None
    assert _previous_grade([]) is None
