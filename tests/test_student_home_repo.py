"""``StudentHomeReads.recent_teacher_replies`` against a throwaway Postgres."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.core.analytics import summarize_weaknesses
from lemely.core.schemas import (
    AccuracyReport,
    ConfidenceBand,
    CorrectedQuestion,
    CorrectionResult,
    ExamMetadata,
    GradePrediction,
)
from lemely.db.attempt_repo import AttemptRepository
from lemely.db.base import Base
from lemely.db.class_repo import ClassService
from lemely.db.models import User
from lemely.db.models.attempts import Attempt
from lemely.db.models.enums import Role
from lemely.db.models.ops import ReviewQueueItem
from lemely.db.review_repo import ReviewService
from lemely.db.student_home_repo import StudentHomeReads
from lemely.runtime.config import DatabaseSettings

if TYPE_CHECKING:
    from collections.abc import Iterator


def _reachable(url: str) -> bool:
    engine = create_engine(make_url(url).set(database="postgres"))
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
    if not _reachable(base_url):
        pytest.skip("local Postgres not reachable")
    admin = create_engine(make_url(base_url).set(database="postgres"), isolation_level="AUTOCOMMIT")
    name = f"lemely_test_{uuid.uuid4().hex[:12]}"
    with admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{name}"'))
    engine = create_engine(make_url(base_url).set(database=name))
    Base.metadata.create_all(engine)
    try:
        yield sessionmaker(bind=engine, expire_on_commit=False, future=True)
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def _user(sm: sessionmaker[Session], role: Role, name: str | None) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role, display_name=name))
    return uid


def _report() -> AccuracyReport:
    metadata = ExamMetadata(
        subject_code="9999",
        paper_number=4,
        paper_variant=1,
        session_month="May/June",
        session_year=2024,
    )
    question = CorrectedQuestion(
        question_id="7",
        awarded_marks=1,
        maximum_marks=3,
        confidence=ConfidenceBand.LOW,
        confidence_score=0.4,
        needs_teacher_review=True,
        student_answer="a",
        expected_answer="b",
        topic="Vectors",
        marker_source="ai",
        review_reason="low_confidence",
        plagiarism_flagged=False,
        matched_point_ids=["p1"],
    )
    correction = CorrectionResult(metadata=metadata, questions=[question])
    return AccuracyReport(
        correction=correction,
        weaknesses=summarize_weaknesses(correction),
        grade_prediction=GradePrediction(
            awarded_marks=1,
            maximum_marks=3,
            percentage=33.33,
            grade="U",
            confidence=ConfidenceBand.LOW,
            needs_teacher_review=True,
            boundary_source="global_default",
        ),
    )


def _setup(sm: sessionmaker[Session]) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    classes = ClassService(sm)
    teacher = _user(sm, Role.teacher, "Ms. Hanna")
    student = _user(sm, Role.student, "Mariam")
    cls = classes.create_class(teacher, "10B Mathematics")
    assert cls.join_code is not None
    classes.join_by_code(student, cls.join_code)
    attempt = AttemptRepository(sm).persist_correction(user_id=str(student), report=_report())
    with sm() as session:
        item = session.scalars(
            select(ReviewQueueItem).where(ReviewQueueItem.attempt_id == attempt)
        ).one()
    return teacher, student, attempt, item.id


def _resolve(sm: sessionmaker[Session], teacher: uuid.UUID, item: uuid.UUID, **kwargs: int) -> None:
    ReviewService(sm, ClassService(sm)).resolve(teacher, Role.teacher, item, **kwargs)


def test_a_resolved_override_is_a_reply_with_marks_added(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    teacher, student, attempt, item = _setup(pg_sessionmaker)
    _resolve(pg_sessionmaker, teacher, item, override_marks=2)
    rows = StudentHomeReads(pg_sessionmaker).recent_teacher_replies(
        student, since=datetime.now(UTC) - timedelta(days=7)
    )
    assert len(rows) == 1
    row = rows[0]
    assert (row.teacher_name, row.question_id, row.marks_added) == ("Ms. Hanna", "7", 1)
    assert (row.attempt_id, row.subject_code, row.paper_number) == (attempt, "9999", 4)


def test_open_items_other_students_and_deleted_papers_are_not_replies(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    teacher, student, attempt, item = _setup(pg_sessionmaker)
    reads = StudentHomeReads(pg_sessionmaker)
    since = datetime.now(UTC) - timedelta(days=7)
    assert reads.recent_teacher_replies(student, since=since) == []

    ReviewService(pg_sessionmaker, ClassService(pg_sessionmaker)).resolve(
        teacher, Role.teacher, item
    )
    stranger = _user(pg_sessionmaker, Role.student, "Other")
    assert reads.recent_teacher_replies(stranger, since=since) == []
    accepted = reads.recent_teacher_replies(student, since=since)
    assert [r.marks_added for r in accepted] == [0]

    with pg_sessionmaker.begin() as session:
        session.get_one(Attempt, attempt).deleted_at = datetime.now(UTC)
    assert reads.recent_teacher_replies(student, since=since) == []


def test_replies_older_than_since_are_left_out(pg_sessionmaker: sessionmaker[Session]) -> None:
    teacher, student, _attempt, item = _setup(pg_sessionmaker)
    ReviewService(pg_sessionmaker, ClassService(pg_sessionmaker)).resolve(
        teacher, Role.teacher, item
    )
    rows = StudentHomeReads(pg_sessionmaker).recent_teacher_replies(
        student, since=datetime.now(UTC) + timedelta(minutes=1)
    )
    assert rows == []


def test_a_teacher_without_a_display_name_is_your_teacher(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    teacher, student, _attempt, item = _setup(pg_sessionmaker)
    with pg_sessionmaker.begin() as session:
        session.get_one(User, teacher).display_name = None
    ReviewService(pg_sessionmaker, ClassService(pg_sessionmaker)).resolve(
        teacher, Role.teacher, item
    )
    rows = StudentHomeReads(pg_sessionmaker).recent_teacher_replies(
        student, since=datetime.now(UTC) - timedelta(days=1)
    )
    assert rows[0].teacher_name == "Your teacher"
