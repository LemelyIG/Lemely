"""Postgres-integration tests for :class:`AttemptRepository` (P2.1).

Throwaway-DB tests that skip cleanly when no local Postgres is reachable
(mirrors ``test_history_repo_parity.py``). They assert the full-report mapping:
one attempt, per-question results, weakness records, and a review-queue row for
every question flagged for review — and that the totals-only ``DbHistoryStore``
still coexists on the same tables.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.core.history import PaperRecord
from lemely.core.schemas import (
    AccuracyReport,
    ConfidenceBand,
    CorrectedQuestion,
    CorrectionResult,
    ExamMetadata,
    GradePrediction,
    WeakArea,
    WeaknessReport,
)
from lemely.db.attempt_repo import AttemptRepository
from lemely.db.base import Base
from lemely.db.history_repo import DbHistoryStore
from lemely.db.models import User
from lemely.db.models.attempts import Attempt, QuestionResult, WeaknessRecord
from lemely.db.models.enums import BoundarySource, MarkerSource, ReviewReason, Role
from lemely.db.models.enums import ConfidenceBand as DBConfidenceBand
from lemely.db.models.ops import ReviewQueueItem
from lemely.runtime.config import DatabaseSettings

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


def _seed_user(sm: sessionmaker[Session], role: Role = Role.student) -> str:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role))
    return str(uid)


def _report() -> AccuracyReport:
    """A mixed report: one HIGH-confidence pass, one LOW-confidence flag."""
    metadata = ExamMetadata(
        subject_code="0625",
        paper_number=1,
        paper_variant=2,
        session_month="May/June",
        session_year=2020,
    )
    high = CorrectedQuestion(
        question_id="1",
        awarded_marks=1,
        maximum_marks=1,
        confidence=ConfidenceBand.HIGH,
        confidence_score=1.0,
        needs_teacher_review=False,
        student_answer="A",
        expected_answer="A",
        topic="Waves",
        marker_source="deterministic",
        matched_point_ids=["p1"],
    )
    low = CorrectedQuestion(
        question_id="2",
        awarded_marks=0,
        maximum_marks=2,
        confidence=ConfidenceBand.LOW,
        confidence_score=0.3,
        needs_teacher_review=True,
        student_answer="",
        expected_answer=None,
        topic="Forces",
        review_reason="missing answer",
        marker_source="ai",
        feedback="No working shown.",
        matched_point_ids=[],
    )
    correction = CorrectionResult(metadata=metadata, questions=[high, low])
    weaknesses = WeaknessReport(
        weak_areas=[
            WeakArea(
                topic="Forces",
                lost_marks=2,
                maximum_marks=2,
                accuracy=0.0,
                question_ids=["2"],
            ),
            WeakArea(
                topic="Waves",
                lost_marks=0,
                maximum_marks=1,
                accuracy=1.0,
                question_ids=["1"],
            ),
        ]
    )
    prediction = GradePrediction(
        awarded_marks=1,
        maximum_marks=3,
        percentage=33.33,
        grade="U",
        confidence=ConfidenceBand.LOW,
        needs_teacher_review=True,
        boundary_source="subject_default",
    )
    return AccuracyReport(correction=correction, weaknesses=weaknesses, grade_prediction=prediction)


def test_persist_correction_writes_one_attempt(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    user_id = _seed_user(pg_sessionmaker)
    repo = AttemptRepository(pg_sessionmaker)

    attempt_id = repo.persist_correction(user_id=user_id, report=_report())
    assert isinstance(attempt_id, uuid.UUID)

    with pg_sessionmaker() as session:
        attempts = session.scalars(select(Attempt)).all()
        assert len(attempts) == 1
        attempt = attempts[0]
        assert attempt.id == attempt_id
        assert attempt.subject_code == "0625"
        assert attempt.grade == "U"
        assert attempt.predicted_grade == "U"
        assert attempt.boundary_source == BoundarySource.subject_default
        assert attempt.confidence_band == DBConfidenceBand.low
        # needs_teacher_review is True because at least one question was flagged.
        assert attempt.needs_teacher_review is True


def test_persist_correction_maps_question_results(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    user_id = _seed_user(pg_sessionmaker)
    AttemptRepository(pg_sessionmaker).persist_correction(user_id=user_id, report=_report())

    with pg_sessionmaker() as session:
        results = session.scalars(select(QuestionResult).order_by(QuestionResult.question_id)).all()
        assert len(results) == 2
        first, second = results
        assert first.question_id == "1"
        assert first.confidence_band == DBConfidenceBand.high
        assert first.marker_source == MarkerSource.deterministic
        assert first.matched_point_ids == ["p1"]
        assert second.question_id == "2"
        assert second.confidence_band == DBConfidenceBand.low
        assert second.marker_source == MarkerSource.ai
        assert second.matched_point_ids == []


def test_persist_correction_writes_weakness_records(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    user_id = _seed_user(pg_sessionmaker)
    attempt_id = AttemptRepository(pg_sessionmaker).persist_correction(
        user_id=user_id, report=_report()
    )

    with pg_sessionmaker() as session:
        records = session.scalars(select(WeaknessRecord)).all()
        assert len(records) == 2
        assert all(r.attempt_id == attempt_id for r in records)
        assert {r.topic for r in records} == {"Forces", "Waves"}


def test_review_queue_only_for_flagged_questions(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    user_id = _seed_user(pg_sessionmaker)
    attempt_id = AttemptRepository(pg_sessionmaker).persist_correction(
        user_id=user_id, report=_report()
    )

    with pg_sessionmaker() as session:
        items = session.scalars(select(ReviewQueueItem)).all()
        # Only the LOW-confidence, review-flagged question (id "2") queues.
        assert len(items) == 1
        item = items[0]
        assert item.attempt_id == attempt_id
        assert item.reason.value == "low_confidence"
        flagged = session.get(QuestionResult, item.question_result_id)
        assert flagged is not None
        assert flagged.question_id == "2"


def _report_with_integrity_flags() -> AccuracyReport:
    """One HIGH-confidence question flagged for BOTH plagiarism and AI-detection.

    ``needs_teacher_review`` is True purely because ``apply_integrity_checks``
    set it (confidence_score is 1.0, well above the review threshold, and
    there is no marking-side out-of-range/value-mismatch signal either) — so
    ``persist_correction`` must NOT also queue a ``low_confidence`` row for
    this question; that would misleadingly label a fully-confident mark as
    low-confidence. Only the two integrity-specific rows should appear.
    """
    metadata = ExamMetadata(
        subject_code="0625",
        paper_number=1,
        paper_variant=2,
        session_month="May/June",
        session_year=2020,
    )
    flagged = CorrectedQuestion(
        question_id="1",
        awarded_marks=1,
        maximum_marks=1,
        confidence=ConfidenceBand.HIGH,
        confidence_score=1.0,
        needs_teacher_review=True,
        student_answer="A",
        expected_answer="A",
        topic="Waves",
        review_reason="plagiarism (score 0.95) | ai_detection (score 0.90)",
        marker_source="deterministic",
        matched_point_ids=["p1"],
        plagiarism_flagged=True,
        ai_detection_flagged=True,
    )
    correction = CorrectionResult(metadata=metadata, questions=[flagged])
    prediction = GradePrediction(
        awarded_marks=1,
        maximum_marks=1,
        percentage=100.0,
        grade="A",
        confidence=ConfidenceBand.HIGH,
        needs_teacher_review=True,
        boundary_source="subject_default",
    )
    return AccuracyReport(
        correction=correction,
        weaknesses=WeaknessReport(weak_areas=[]),
        grade_prediction=prediction,
    )


def test_review_queue_includes_integrity_flag_rows(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    user_id = _seed_user(pg_sessionmaker)
    attempt_id = AttemptRepository(pg_sessionmaker).persist_correction(
        user_id=user_id, report=_report_with_integrity_flags()
    )

    with pg_sessionmaker() as session:
        items = session.scalars(select(ReviewQueueItem)).all()
        reasons = {item.reason for item in items}
        # NOT low_confidence: confidence_score is 1.0 and there is no marking-side
        # out-of-range/value-mismatch signal, so needs_teacher_review is True purely
        # from the two integrity flags, which already have their own rows below.
        assert reasons == {
            ReviewReason.plagiarism_flag,
            ReviewReason.ai_detection_flag,
        }
        assert all(item.attempt_id == attempt_id for item in items)
        question_result_ids = {item.question_result_id for item in items}
        assert len(question_result_ids) == 1


def test_review_queue_low_confidence_row_survives_alongside_integrity_flags(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """A genuinely low-confidence question that is ALSO integrity-flagged still
    gets its own low_confidence row — the fix that stops a high-confidence,
    purely-integrity-flagged question from getting a spurious low_confidence
    row must not suppress a real low-confidence signal when the two coincide.
    """
    metadata = ExamMetadata(
        subject_code="0625",
        paper_number=1,
        paper_variant=2,
        session_month="May/June",
        session_year=2020,
    )
    flagged = CorrectedQuestion(
        question_id="1",
        awarded_marks=0,
        maximum_marks=1,
        confidence=ConfidenceBand.LOW,
        confidence_score=0.5,
        needs_teacher_review=True,
        student_answer="A",
        expected_answer="A",
        topic="Waves",
        review_reason="confidence 0.50 below review threshold 0.90 | plagiarism (score 0.95)",
        marker_source="deterministic",
        matched_point_ids=["p1"],
        plagiarism_flagged=True,
    )
    correction = CorrectionResult(metadata=metadata, questions=[flagged])
    prediction = GradePrediction(
        awarded_marks=0,
        maximum_marks=1,
        percentage=0.0,
        grade="U",
        confidence=ConfidenceBand.LOW,
        needs_teacher_review=True,
        boundary_source="subject_default",
    )
    report = AccuracyReport(
        correction=correction,
        weaknesses=WeaknessReport(weak_areas=[]),
        grade_prediction=prediction,
    )

    user_id = _seed_user(pg_sessionmaker)
    attempt_id = AttemptRepository(pg_sessionmaker).persist_correction(
        user_id=user_id, report=report
    )

    with pg_sessionmaker() as session:
        items = session.scalars(select(ReviewQueueItem)).all()
        reasons = {item.reason for item in items}
        assert reasons == {ReviewReason.low_confidence, ReviewReason.plagiarism_flag}
        assert all(item.attempt_id == attempt_id for item in items)


def test_coexists_with_db_history_store(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    user_id = _seed_user(pg_sessionmaker)
    # A separate PaperRecord written via the totals-only history store.
    history = DbHistoryStore(pg_sessionmaker)
    history.append(
        user_id,
        PaperRecord(
            student_id=user_id,
            metadata=ExamMetadata(
                subject_code="0625",
                paper_number=2,
                paper_variant=1,
                session_month="Oct/Nov",
                session_year=2021,
            ),
            awarded_marks=40,
            maximum_marks=50,
            percentage=80.0,
            grade="A",
            weak_areas=[],
            recorded_at="2026-01-01T00:00:00+00:00",
        ),
    )
    AttemptRepository(pg_sessionmaker).persist_correction(user_id=user_id, report=_report())

    # The history store sees BOTH attempts (its own record + the repo's).
    assert len(history.load(user_id).records) == 2
