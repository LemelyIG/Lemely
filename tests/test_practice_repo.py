"""Tests for :mod:`lemely.db.practice_repo` (P4.5).

Postgres-integration, mirroring ``tests/test_placement_repo.py``'s
throwaway-database fixture. Covers:

* Each filter dimension (topic, difficulty band, count, source) verified by
  its inverse — the excluded rows are genuinely absent, not merely that the
  included ones are present.
* Weak-topic targeting: seeded ``WeaknessRecord`` rows actually concentrate
  the generated set on those topics (MISSION §4's acceptance criterion).
* Honesty: a shortfall pool still creates, honestly short, with a reason;
  an empty pool (0580-shaped) refuses outright.
* Enrolment narrowing, mirroring D4.9's four cases.
* The export payload's structural answer-leak exclusion.
* Cross-tenant 403 on export.
"""

from __future__ import annotations

import dataclasses
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.db.base import Base
from lemely.db.models import User
from lemely.db.models.attempts import Attempt, WeaknessRecord
from lemely.db.models.enums import (
    AttemptOrigin,
    DifficultySource,
    QuestionSource,
    QuizKind,
    QuizStatus,
    Role,
)
from lemely.db.models.profiles import StudentEnrolmentPaper, StudentSubjectEnrolment
from lemely.db.models.quizzes import QuestionBank, Quiz, QuizAssignment, QuizQuestion
from lemely.db.practice_repo import (
    PracticeExportQuestion,
    PracticeNotFoundError,
    PracticeOwnershipError,
    PracticeRequest,
    PracticeService,
    PracticeUnavailableError,
)
from lemely.db.question_bank_repo import NewBankQuestion, QuestionBankService
from lemely.runtime.config import DatabaseSettings

if TYPE_CHECKING:
    from collections.abc import Iterator

# ---------------------------------------------------------------------------
# Fixtures — throwaway Postgres database, mirrors the sibling placement suite.
# ---------------------------------------------------------------------------


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


def _seed_user(sm: sessionmaker[Session], role: Role = Role.student) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role))
    return uid


def _seed_rows(
    sm: sessionmaker[Session],
    *,
    subject_code: str = "0625",
    topics: list[str],
    difficulty: str = "standard",
    source: QuestionSource = QuestionSource.past_paper,
    per_topic: int = 2,
    stem: str = "0625_s23_qp_41",
    ref_start: int = 1,
) -> None:
    """Bank rows across ``topics``, linked to a real ``Paper`` when ``source`` is past-paper.

    ``stem`` follows P4.1's CAIE filename convention (``0625_s23_qp_41`` is
    Paper 4); :meth:`~lemely.db.question_bank_repo.QuestionBankService.link_past_paper_rows`
    resolves the paper number from it, the same as
    ``tests/test_placement_repo.py``'s fixture.
    """
    service = QuestionBankService(sm)
    rows = []
    ref = ref_start
    for topic in topics:
        for _ in range(per_topic):
            rows.append(
                NewBankQuestion(
                    subject_code=subject_code,
                    source=source,
                    difficulty=difficulty,  # type: ignore[arg-type]
                    difficulty_source=DifficultySource.inferred_from_marks,
                    question_type="mcq",
                    prompt=f"Question {ref}",
                    total_marks=2,
                    topic=topic,
                    source_question_id=(
                        f"{stem}#{ref}" if source == QuestionSource.past_paper else None
                    ),
                    mcq_options=["A", "B", "C", "D"],
                    mcq_answer="B",
                )
            )
            ref += 1
    service.add_questions(rows)
    if source == QuestionSource.past_paper:
        service.link_past_paper_rows()


def _seed_enrolment(
    sm: sessionmaker[Session],
    student_id: uuid.UUID,
    *,
    subject_code: str = "0625",
    paper_numbers: list[int],
) -> None:
    """Requires the ``subjects`` row, so call after ``_seed_rows`` (which links papers)."""
    with sm.begin() as session:
        enrolment = StudentSubjectEnrolment(user_id=student_id, subject_code=subject_code)
        session.add(enrolment)
        session.flush()
        for number in paper_numbers:
            session.add(StudentEnrolmentPaper(enrolment_id=enrolment.id, paper_number=number))


def _seed_weakness(
    sm: sessionmaker[Session],
    student_id: uuid.UUID,
    *,
    subject_code: str = "0625",
    topic: str,
    lost_marks: int,
    maximum_marks: int,
) -> None:
    with sm.begin() as session:
        attempt = Attempt(
            user_id=student_id,
            subject_code=subject_code,
            awarded_marks=maximum_marks - lost_marks,
            maximum_marks=maximum_marks,
            percentage=100.0 * (maximum_marks - lost_marks) / maximum_marks,
            recorded_at=datetime.now(UTC),
            origin=AttemptOrigin.quiz,
        )
        session.add(attempt)
        session.flush()
        session.add(
            WeaknessRecord(
                user_id=student_id,
                attempt_id=attempt.id,
                topic=topic,
                lost_marks=lost_marks,
                maximum_marks=maximum_marks,
                accuracy=1.0 - lost_marks / maximum_marks,
            )
        )


def _persisted_topics(sm: sessionmaker[Session], quiz_id: uuid.UUID) -> list[str | None]:
    with sm() as session:
        return list(
            session.scalars(select(QuizQuestion.topic).where(QuizQuestion.quiz_id == quiz_id)).all()
        )


# ---------------------------------------------------------------------------
# Filter dimensions, each verified by its inverse.
# ---------------------------------------------------------------------------


def test_topic_filter_excludes_the_other_topic(
    pg_sessionmaker: sessionmaker[Session], practice_service: PracticeService
) -> None:
    student = _seed_user(pg_sessionmaker)
    _seed_rows(pg_sessionmaker, topics=["1 Motion", "2 Thermal"], per_topic=3)

    created = practice_service.create(
        student, PracticeRequest(subject_code="0625", count=10, topics=("1 Motion",))
    )

    topics = _persisted_topics(pg_sessionmaker, created.quiz_id)
    assert topics, "sanity: something was persisted"
    assert set(topics) == {"1 Motion"}
    assert "2 Thermal" not in topics


def test_difficulty_band_filter_excludes_the_other_band(
    pg_sessionmaker: sessionmaker[Session], practice_service: PracticeService
) -> None:
    student = _seed_user(pg_sessionmaker)
    _seed_rows(
        pg_sessionmaker, topics=["1 Motion"], difficulty="foundation", per_topic=3, ref_start=1
    )
    _seed_rows(
        pg_sessionmaker, topics=["2 Thermal"], difficulty="challenge", per_topic=3, ref_start=100
    )

    created = practice_service.create(
        student,
        PracticeRequest(subject_code="0625", count=10, difficulty_bands=("foundation",)),
    )

    with pg_sessionmaker() as session:
        difficulties = session.scalars(
            select(QuizQuestion.difficulty).where(QuizQuestion.quiz_id == created.quiz_id)
        ).all()
    assert difficulties, "sanity: something was persisted"
    assert all(d.value == "foundation" for d in difficulties)


def test_source_filter_excludes_the_other_source(
    pg_sessionmaker: sessionmaker[Session], practice_service: PracticeService
) -> None:
    student = _seed_user(pg_sessionmaker)
    _seed_rows(
        pg_sessionmaker,
        topics=["1 Motion"],
        source=QuestionSource.past_paper,
        per_topic=3,
        ref_start=1,
    )
    _seed_rows(
        pg_sessionmaker,
        topics=["1 Motion"],
        source=QuestionSource.generated,
        per_topic=3,
        ref_start=100,
    )

    created = practice_service.create(
        student,
        PracticeRequest(
            subject_code="0625", count=20, topics=("1 Motion",), source=QuestionSource.generated
        ),
    )

    # Every persisted question must trace back to a generated-source bank row.
    with pg_sessionmaker() as session:
        bank_ids = session.scalars(
            select(QuizQuestion.question_bank_id).where(QuizQuestion.quiz_id == created.quiz_id)
        ).all()
        assert bank_ids, "sanity: something was persisted"
        bank_sources = session.scalars(
            select(QuestionBank.source).where(QuestionBank.id.in_(bank_ids))
        ).all()
        assert all(s == QuestionSource.generated for s in bank_sources)


def test_count_caps_the_persisted_set(
    pg_sessionmaker: sessionmaker[Session], practice_service: PracticeService
) -> None:
    student = _seed_user(pg_sessionmaker)
    _seed_rows(pg_sessionmaker, topics=["1 Motion"], per_topic=10)

    created = practice_service.create(
        student, PracticeRequest(subject_code="0625", count=3, topics=("1 Motion",))
    )

    assert created.question_count == 3
    assert created.reason is None


# ---------------------------------------------------------------------------
# Weak-topic targeting (MISSION §4's acceptance criterion).
# ---------------------------------------------------------------------------


def test_weak_topic_targeting_concentrates_on_the_seeded_weakness(
    pg_sessionmaker: sessionmaker[Session], practice_service: PracticeService
) -> None:
    student = _seed_user(pg_sessionmaker)
    _seed_rows(pg_sessionmaker, topics=["1 Motion", "2 Thermal", "3 Waves"], per_topic=4)
    _seed_weakness(pg_sessionmaker, student, topic="2 Thermal", lost_marks=4, maximum_marks=10)

    preview = practice_service.preview(
        student, PracticeRequest(subject_code="0625", count=10, weak_topics_only=True)
    )
    assert preview.topics == ["2 Thermal"]

    created = practice_service.create(
        student, PracticeRequest(subject_code="0625", count=10, weak_topics_only=True)
    )

    topics = _persisted_topics(pg_sessionmaker, created.quiz_id)
    assert topics, "sanity: something was persisted"
    assert set(topics) == {"2 Thermal"}
    assert "1 Motion" not in topics
    assert "3 Waves" not in topics


def test_weak_topic_targeting_excludes_a_topic_with_zero_net_lost_marks(
    pg_sessionmaker: sessionmaker[Session], practice_service: PracticeService
) -> None:
    """A topic the student answered perfectly is not a weakness (mirrors group_weak_areas)."""
    student = _seed_user(pg_sessionmaker)
    _seed_rows(pg_sessionmaker, topics=["1 Motion", "2 Thermal"], per_topic=4)
    _seed_weakness(pg_sessionmaker, student, topic="1 Motion", lost_marks=0, maximum_marks=10)
    _seed_weakness(pg_sessionmaker, student, topic="2 Thermal", lost_marks=5, maximum_marks=10)

    preview = practice_service.preview(
        student, PracticeRequest(subject_code="0625", count=10, weak_topics_only=True)
    )

    assert preview.topics == ["2 Thermal"]


def test_weak_topic_targeting_with_no_weaknesses_refuses_honestly(
    pg_sessionmaker: sessionmaker[Session], practice_service: PracticeService
) -> None:
    student = _seed_user(pg_sessionmaker)
    _seed_rows(pg_sessionmaker, topics=["1 Motion"], per_topic=4)

    preview = practice_service.preview(
        student, PracticeRequest(subject_code="0625", count=10, weak_topics_only=True)
    )

    assert preview.available is False
    assert preview.reason == "no_weaknesses"
    with pytest.raises(PracticeUnavailableError):
        practice_service.create(
            student, PracticeRequest(subject_code="0625", count=10, weak_topics_only=True)
        )


# ---------------------------------------------------------------------------
# Honesty: shortfall still creates; an empty pool refuses (spec §1.4).
# ---------------------------------------------------------------------------


def test_a_shortfall_pool_still_creates_and_says_so(
    pg_sessionmaker: sessionmaker[Session], practice_service: PracticeService
) -> None:
    student = _seed_user(pg_sessionmaker)
    _seed_rows(pg_sessionmaker, topics=["1 Motion"], per_topic=3)

    preview = practice_service.preview(
        student, PracticeRequest(subject_code="0625", count=20, topics=("1 Motion",))
    )
    assert preview.available is True
    assert preview.reason == "insufficient_pool"
    assert preview.available_count == 3
    assert preview.requested_count == 20

    created = practice_service.create(
        student, PracticeRequest(subject_code="0625", count=20, topics=("1 Motion",))
    )
    assert created.question_count == 3
    assert created.requested_count == 20
    assert created.reason == "insufficient_pool"


def test_an_empty_pool_refuses_with_no_questions(
    pg_sessionmaker: sessionmaker[Session], practice_service: PracticeService
) -> None:
    student = _seed_user(pg_sessionmaker)

    preview = practice_service.preview(student, PracticeRequest(subject_code="0580", count=10))

    assert preview.available is False
    assert preview.reason == "no_questions"
    assert preview.available_count == 0

    with pytest.raises(PracticeUnavailableError) as excinfo:
        practice_service.create(student, PracticeRequest(subject_code="0580", count=10))
    assert excinfo.value.preview == preview


# ---------------------------------------------------------------------------
# Enrolment narrowing, mirroring D4.9's four cases.
# ---------------------------------------------------------------------------


def test_a_paper_the_student_will_not_sit_is_not_drawn_from(
    pg_sessionmaker: sessionmaker[Session], practice_service: PracticeService
) -> None:
    student = _seed_user(pg_sessionmaker)
    _seed_rows(pg_sessionmaker, topics=["1 Motion"], per_topic=4, stem="0625_s23_qp_41")  # Paper 4
    _seed_enrolment(pg_sessionmaker, student, paper_numbers=[1, 3])

    preview = practice_service.preview(student, PracticeRequest(subject_code="0625", count=10))

    assert preview.available is False
    assert preview.reason == "no_questions"


def test_an_enrolled_paper_is_drawn_from(
    pg_sessionmaker: sessionmaker[Session], practice_service: PracticeService
) -> None:
    student = _seed_user(pg_sessionmaker)
    _seed_rows(pg_sessionmaker, topics=["1 Motion"], per_topic=4, stem="0625_s23_qp_41")
    _seed_enrolment(pg_sessionmaker, student, paper_numbers=[4])

    preview = practice_service.preview(student, PracticeRequest(subject_code="0625", count=10))

    assert preview.available is True
    assert preview.available_count == 4


def test_a_student_who_skipped_the_paper_question_is_not_narrowed(
    pg_sessionmaker: sessionmaker[Session], practice_service: PracticeService
) -> None:
    student = _seed_user(pg_sessionmaker)
    _seed_rows(pg_sessionmaker, topics=["1 Motion"], per_topic=4, stem="0625_s23_qp_41")
    _seed_enrolment(pg_sessionmaker, student, paper_numbers=[])

    preview = practice_service.preview(student, PracticeRequest(subject_code="0625", count=10))

    assert preview.available is True


def test_another_students_enrolment_does_not_narrow_this_one(
    pg_sessionmaker: sessionmaker[Session], practice_service: PracticeService
) -> None:
    student_a = _seed_user(pg_sessionmaker)
    student_b = _seed_user(pg_sessionmaker)
    _seed_rows(pg_sessionmaker, topics=["1 Motion"], per_topic=4, stem="0625_s23_qp_41")
    _seed_enrolment(pg_sessionmaker, student_b, paper_numbers=[1, 3])

    preview_a = practice_service.preview(student_a, PracticeRequest(subject_code="0625", count=10))
    preview_b = practice_service.preview(student_b, PracticeRequest(subject_code="0625", count=10))

    assert preview_a.available is True
    assert preview_b.available is False


# ---------------------------------------------------------------------------
# create() persistence shape.
# ---------------------------------------------------------------------------


def test_create_persists_a_self_owned_assigned_practice_quiz(
    pg_sessionmaker: sessionmaker[Session], practice_service: PracticeService
) -> None:
    student = _seed_user(pg_sessionmaker)
    _seed_rows(pg_sessionmaker, topics=["1 Motion"], per_topic=4)

    created = practice_service.create(
        student, PracticeRequest(subject_code="0625", count=3, topics=("1 Motion",))
    )

    with pg_sessionmaker() as session:
        quiz = session.get(Quiz, created.quiz_id)
        assert quiz is not None
        assert quiz.teacher_id is None
        assert quiz.student_id == student
        assert quiz.kind.value == "practice"
        assert quiz.time_limit_minutes is None
        assert quiz.status.value == "assigned"

        assignment = session.scalars(
            select(QuizAssignment).where(QuizAssignment.quiz_id == created.quiz_id)
        ).one()
        assert assignment.student_id == student
        assert assignment.class_id is None
        assert assignment.assigned_by == student


# ---------------------------------------------------------------------------
# Export: structural answer-leak exclusion, and cross-tenant 403.
# ---------------------------------------------------------------------------


def test_export_dataclass_has_no_marking_fields() -> None:
    """The dataclass itself cannot carry the three forbidden fields, by construction."""
    field_names = {f.name for f in dataclasses.fields(PracticeExportQuestion)}
    assert "model_answer" not in field_names
    assert "mark_scheme_points" not in field_names
    assert "mcq_answer" not in field_names


def test_export_never_returns_marking_material(
    pg_sessionmaker: sessionmaker[Session], practice_service: PracticeService
) -> None:
    student = _seed_user(pg_sessionmaker)
    _seed_rows(pg_sessionmaker, topics=["1 Motion"], per_topic=3)
    created = practice_service.create(
        student, PracticeRequest(subject_code="0625", count=3, topics=("1 Motion",))
    )

    export = practice_service.export(student, created.assignment_id)

    assert export.questions
    for q in export.questions:
        assert not hasattr(q, "model_answer")
        assert not hasattr(q, "mark_scheme_points")
        assert not hasattr(q, "mcq_answer")


def test_export_cross_tenant_is_403_not_404(
    pg_sessionmaker: sessionmaker[Session], practice_service: PracticeService
) -> None:
    owner = _seed_user(pg_sessionmaker)
    other = _seed_user(pg_sessionmaker)
    _seed_rows(pg_sessionmaker, topics=["1 Motion"], per_topic=3)
    created = practice_service.create(
        owner, PracticeRequest(subject_code="0625", count=3, topics=("1 Motion",))
    )

    with pytest.raises(PracticeOwnershipError):
        practice_service.export(other, created.assignment_id)


def test_export_unknown_assignment_is_404_not_403(
    pg_sessionmaker: sessionmaker[Session], practice_service: PracticeService
) -> None:
    student = _seed_user(pg_sessionmaker)

    with pytest.raises(PracticeNotFoundError):
        practice_service.export(student, uuid.uuid4())


def test_export_a_placement_assignment_is_not_a_practice_set(
    pg_sessionmaker: sessionmaker[Session], practice_service: PracticeService
) -> None:
    """A caller-owned assignment of the wrong ``kind`` is 404, not data (see module docstring)."""
    student = _seed_user(pg_sessionmaker)
    quiz_id = uuid.uuid4()
    assignment_id = uuid.uuid4()
    with pg_sessionmaker.begin() as session:
        session.add(
            Quiz(
                id=quiz_id,
                teacher_id=None,
                student_id=student,
                kind=QuizKind.placement,
                subject_code="0625",
                title="Placement test",
                status=QuizStatus.assigned,
            )
        )
        session.add(
            QuizAssignment(
                id=assignment_id,
                quiz_id=quiz_id,
                class_id=None,
                student_id=student,
                assigned_by=student,
            )
        )

    with pytest.raises(PracticeNotFoundError):
        practice_service.export(student, assignment_id)
