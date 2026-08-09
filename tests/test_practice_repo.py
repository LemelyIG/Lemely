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
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.db.attempt_repo import AttemptRepository
from lemely.db.base import Base
from lemely.db.class_repo import ClassService
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
from lemely.db.quiz_marking_repo import QuizMarkingService
from lemely.db.quiz_taking_repo import QuizTakingService
from lemely.io.gemini import GeminiClient
from lemely.runtime.config import DatabaseSettings, PathsSettings, load_settings

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


@pytest.fixture
def taking_service(pg_sessionmaker: sessionmaker[Session]) -> QuizTakingService:
    return QuizTakingService(pg_sessionmaker, ClassService(pg_sessionmaker))


@pytest.fixture
def attempt_repo(pg_sessionmaker: sessionmaker[Session]) -> AttemptRepository:
    return AttemptRepository(pg_sessionmaker)


def _never_called_gemini_client(tmp_path: Path) -> GeminiClient:
    """Mirrors ``tests/test_placement_repo.py``'s strictest stub for an all-MCQ quiz."""
    mock_genai = MagicMock()
    mock_genai.models.generate_content.side_effect = AssertionError(
        "Gemini must not be called for an all-MCQ practice quiz"
    )
    settings = load_settings(toml_path=None, cwd=tmp_path)
    settings = settings.model_copy(update={"paths": PathsSettings(cache_dir=tmp_path / ".cache")})
    return GeminiClient(settings, _genai_client=mock_genai)


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


def test_figure_dependent_rows_are_never_served_ordinary_rows_still_are(
    pg_sessionmaker: sessionmaker[Session], practice_service: PracticeService
) -> None:
    """P4.8 chunk 0's ``renderable_bank_filter``, pinned by its inverse.

    ``question_bank`` has no image column, so a stem that reads an *existing*
    figure ("The diagram shows...") cannot be fully rendered and must never
    be served. Seeds one figure-dependent row and one ordinary row in the
    same topic, requests more than the ordinary-only pool size, and asserts
    the figure-dependent bank id never appears in what gets persisted — the
    positive half. The inverse (this test's actual name) is the part that
    would fail if the predicate over-excluded: an ordinary stem in the same
    topic, seeded alongside it, must still come back, so a detector that
    accidentally emptied the whole pool cannot pass silently.
    """
    student = _seed_user(pg_sessionmaker)
    service = QuestionBankService(pg_sessionmaker)
    service.add_questions(
        [
            NewBankQuestion(
                subject_code="0625",
                source=QuestionSource.generated,
                difficulty="standard",  # type: ignore[arg-type]
                difficulty_source=DifficultySource.declared_by_generator,
                question_type="mcq",
                prompt=(
                    "The diagram shows a radioactive source, a thick aluminium sheet and a "
                    "radiation detector. Which type of radiation is detected?"
                ),
                total_marks=2,
                topic="1 Motion",
                mcq_options=["A", "B", "C", "D"],
                mcq_answer="B",
            ),
            NewBankQuestion(
                subject_code="0625",
                source=QuestionSource.generated,
                difficulty="standard",  # type: ignore[arg-type]
                difficulty_source=DifficultySource.declared_by_generator,
                question_type="mcq",
                prompt="What is the SI unit of force?",
                total_marks=2,
                topic="1 Motion",
                mcq_options=["A", "B", "C", "D"],
                mcq_answer="B",
            ),
        ]
    )
    with pg_sessionmaker() as session:
        rows = session.execute(
            select(QuestionBank.id, QuestionBank.prompt).where(QuestionBank.subject_code == "0625")
        ).all()
    figure_id = next(rid for rid, prompt in rows if prompt.startswith("The diagram shows"))
    ordinary_id = next(rid for rid, prompt in rows if prompt.startswith("What is the SI unit"))

    created = practice_service.create(
        student, PracticeRequest(subject_code="0625", count=10, topics=("1 Motion",))
    )

    with pg_sessionmaker() as session:
        persisted_bank_ids = set(
            session.scalars(
                select(QuizQuestion.question_bank_id).where(QuizQuestion.quiz_id == created.quiz_id)
            ).all()
        )
    assert figure_id not in persisted_bank_ids
    assert ordinary_id in persisted_bank_ids

    # The row itself must still exist in the bank — exclusion from serving,
    # never deletion (brief's hard constraint 1).
    with pg_sessionmaker() as session:
        still_there = session.get(QuestionBank, figure_id)
    assert still_there is not None
    assert still_there.is_active is True


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


# ---------------------------------------------------------------------------
# Result (S-21 poll target, P4.9 chunk 0).
# ---------------------------------------------------------------------------


def test_result_not_started_says_so_honestly(
    pg_sessionmaker: sessionmaker[Session], practice_service: PracticeService
) -> None:
    """No ``QuizSubmission`` row exists yet — never a fabricated zero score."""
    student = _seed_user(pg_sessionmaker)
    _seed_rows(pg_sessionmaker, topics=["1 Motion"], per_topic=3)
    created = practice_service.create(
        student, PracticeRequest(subject_code="0625", count=3, topics=("1 Motion",))
    )

    result = practice_service.result(student, created.assignment_id)

    assert result.marked is False
    assert result.submission_status == "not_started"
    assert result.awarded_marks is None
    assert result.maximum_marks is None
    assert result.questions == []


def test_result_submitted_but_not_yet_marked_is_distinct_from_not_started(
    pg_sessionmaker: sessionmaker[Session],
    practice_service: PracticeService,
    taking_service: QuizTakingService,
) -> None:
    """S-21 must tell "not submitted" apart from "submitted, being marked"."""
    student = _seed_user(pg_sessionmaker)
    _seed_rows(pg_sessionmaker, topics=["1 Motion"], per_topic=3)
    created = practice_service.create(
        student, PracticeRequest(subject_code="0625", count=3, topics=("1 Motion",))
    )
    detail = taking_service.get_take(student, created.assignment_id)
    for question in detail.questions:
        taking_service.save_answer(
            student, created.assignment_id, question.question_ref, answer_text="B"
        )
    taking_service.submit(student, created.assignment_id)

    result = practice_service.result(student, created.assignment_id)

    assert result.marked is False
    assert result.submission_status == "submitted"
    assert result.awarded_marks is None
    assert result.maximum_marks is None
    assert result.questions == []


def test_result_unknown_assignment_is_404_not_403(
    pg_sessionmaker: sessionmaker[Session], practice_service: PracticeService
) -> None:
    student = _seed_user(pg_sessionmaker)

    with pytest.raises(PracticeNotFoundError):
        practice_service.result(student, uuid.uuid4())


def test_result_cross_tenant_is_403_not_404(
    pg_sessionmaker: sessionmaker[Session], practice_service: PracticeService
) -> None:
    owner = _seed_user(pg_sessionmaker)
    other = _seed_user(pg_sessionmaker)
    _seed_rows(pg_sessionmaker, topics=["1 Motion"], per_topic=3)
    created = practice_service.create(
        owner, PracticeRequest(subject_code="0625", count=3, topics=("1 Motion",))
    )

    with pytest.raises(PracticeOwnershipError):
        practice_service.result(other, created.assignment_id)


def test_result_for_a_placement_assignment_is_404_not_data(
    pg_sessionmaker: sessionmaker[Session], practice_service: PracticeService
) -> None:
    """A caller-owned assignment of the wrong ``kind`` is 404, not data (mirrors export)."""
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
        practice_service.result(student, assignment_id)


def test_result_for_a_teacher_assigned_quiz_is_404_not_data(
    pg_sessionmaker: sessionmaker[Session], practice_service: PracticeService
) -> None:
    """A teacher-assigned (``kind=teacher``) quiz owned by this student is not a practice set."""
    student = _seed_user(pg_sessionmaker)
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    quiz_id = uuid.uuid4()
    assignment_id = uuid.uuid4()
    with pg_sessionmaker.begin() as session:
        session.add(
            Quiz(
                id=quiz_id,
                teacher_id=teacher,
                student_id=None,
                kind=QuizKind.teacher,
                subject_code="0625",
                title="Teacher quiz",
                status=QuizStatus.assigned,
            )
        )
        session.add(
            QuizAssignment(
                id=assignment_id,
                quiz_id=quiz_id,
                class_id=None,
                student_id=student,
                assigned_by=teacher,
            )
        )

    with pytest.raises(PracticeNotFoundError):
        practice_service.result(student, assignment_id)


def test_result_end_to_end_marked_carries_per_question_marks_and_confidence(
    pg_sessionmaker: sessionmaker[Session],
    practice_service: PracticeService,
    taking_service: QuizTakingService,
    attempt_repo: AttemptRepository,
    tmp_path: Path,
) -> None:
    student = _seed_user(pg_sessionmaker)
    _seed_rows(pg_sessionmaker, topics=["1 Motion"], per_topic=3)
    created = practice_service.create(
        student, PracticeRequest(subject_code="0625", count=3, topics=("1 Motion",))
    )
    detail = taking_service.get_take(student, created.assignment_id)
    for position, question in enumerate(detail.questions):
        wrong_first = "A" if position == 0 else "B"
        taking_service.save_answer(
            student, created.assignment_id, question.question_ref, answer_text=wrong_first
        )
    submit_result = taking_service.submit(student, created.assignment_id)

    marking = QuizMarkingService(
        pg_sessionmaker, attempt_repo, _never_called_gemini_client(tmp_path)
    )
    mark_outcome = marking.mark_submission(submit_result.submission_id)
    assert mark_outcome.attempt_id is not None

    result = practice_service.result(student, created.assignment_id)

    assert result.marked is True
    assert result.submission_status == "marked"
    assert result.awarded_marks is not None
    assert result.maximum_marks is not None
    assert result.awarded_marks < result.maximum_marks  # the first answer was wrong
    assert len(result.questions) == created.question_count
    positions = [q.position for q in result.questions]
    assert positions == sorted(positions), "S-21 renders the set in position order"
    assert positions == list(range(1, created.question_count + 1))
    for q in result.questions:
        assert q.topic == "1 Motion"
        assert q.total_marks == 2
        assert q.awarded_marks in (0, 2)
        assert q.confidence_band in ("high", "medium", "low")
        assert 0.0 <= q.confidence_score <= 1.0

    # No marking-scheme material leaks through the result dataclass either.
    field_names = {f.name for f in dataclasses.fields(result.questions[0])}
    assert "model_answer" not in field_names
    assert "mark_scheme_points" not in field_names
    assert "mcq_answer" not in field_names


# ---------------------------------------------------------------------------
# Topics (S-20's topic-selection control, P4.9 chunk 0).
# ---------------------------------------------------------------------------


def test_topics_carries_the_group_so_a_parent_and_its_subtopics_are_not_peers(
    pg_sessionmaker: sessionmaker[Session], practice_service: PracticeService
) -> None:
    """A parent label and its subtopics are disjoint row sets, not a hierarchy.

    Measured live against the 0625 bank: ``"1 Motion, forces and energy"``
    (152 rows) comes back alongside ``"1.2 Motion"`` (6) and
    ``"1.3 Mass and weight"`` (5), because D4.2's classifier writes whichever
    level it matched and each row carries exactly one label. Rendered flat,
    S-20 would offer the parent as though it covered the children — it does
    not, and a student picking it silently loses them. ``syllabus_group`` is
    what lets the screen nest them; without it the topic list is misleading
    rather than merely terse.
    """
    student = _seed_user(pg_sessionmaker)
    _seed_rows(
        pg_sessionmaker,
        topics=["1 Motion, forces and energy", "1.2 Motion", "10.1 Late", "2.1 Thermal"],
        per_topic=2,
    )

    result = practice_service.topics(student, "0625")

    groups = {t.topic: t.syllabus_group for t in result.topics}
    assert groups["1 Motion, forces and energy"] == "1"
    assert groups["1.2 Motion"] == "1"
    assert groups["2.1 Thermal"] == "2"
    assert groups["10.1 Late"] == "10"

    # The parent does not absorb the child's rows — they are genuinely disjoint,
    # which is the whole reason the group key has to reach the screen.
    by_topic = {t.topic: t.available_count for t in result.topics}
    assert by_topic["1 Motion, forces and energy"] == 2
    assert by_topic["1.2 Motion"] == 2

    # Syllabus-code order, not string order: "10.1" sorts after "2.1", not before it.
    assert [t.topic for t in result.topics] == [
        "1 Motion, forces and energy",
        "1.2 Motion",
        "2.1 Thermal",
        "10.1 Late",
    ]


def test_topics_returns_real_counts_and_a_separate_untopiced_count(
    pg_sessionmaker: sessionmaker[Session], practice_service: PracticeService
) -> None:
    student = _seed_user(pg_sessionmaker)
    _seed_rows(pg_sessionmaker, topics=["1 Motion", "2 Thermal"], per_topic=3)
    service = QuestionBankService(pg_sessionmaker)
    service.add_questions(
        [
            NewBankQuestion(
                subject_code="0625",
                source=QuestionSource.generated,
                difficulty="standard",
                difficulty_source=DifficultySource.declared_by_generator,
                question_type="mcq",
                prompt="An untopiced generated question.",
                total_marks=2,
                topic=None,
                mcq_options=["A", "B", "C", "D"],
                mcq_answer="B",
            )
        ]
    )

    result = practice_service.topics(student, "0625")

    by_topic = {t.topic: t.available_count for t in result.topics}
    assert by_topic == {"1 Motion": 3, "2 Thermal": 3}
    assert result.untopiced_count == 1
    assert None not in by_topic


def test_topics_excludes_a_figure_dependent_row_ordinary_rows_still_counted(
    pg_sessionmaker: sessionmaker[Session], practice_service: PracticeService
) -> None:
    """Pins that ``topics`` shares ``_matching_clauses``, not a second, drifting copy."""
    student = _seed_user(pg_sessionmaker)
    service = QuestionBankService(pg_sessionmaker)
    service.add_questions(
        [
            NewBankQuestion(
                subject_code="0625",
                source=QuestionSource.generated,
                difficulty="standard",
                difficulty_source=DifficultySource.declared_by_generator,
                question_type="mcq",
                prompt=(
                    "The diagram shows a radioactive source, a thick aluminium sheet and a "
                    "radiation detector. Which type of radiation is detected?"
                ),
                total_marks=2,
                topic="1 Motion",
                mcq_options=["A", "B", "C", "D"],
                mcq_answer="B",
            ),
            NewBankQuestion(
                subject_code="0625",
                source=QuestionSource.generated,
                difficulty="standard",
                difficulty_source=DifficultySource.declared_by_generator,
                question_type="mcq",
                prompt="What is the SI unit of force?",
                total_marks=2,
                topic="1 Motion",
                mcq_options=["A", "B", "C", "D"],
                mcq_answer="B",
            ),
        ]
    )

    result = practice_service.topics(student, "0625")

    by_topic = {t.topic: t.available_count for t in result.topics}
    assert by_topic == {"1 Motion": 1}


def test_topics_includes_the_callers_weak_topics_excluding_zero_net_loss(
    pg_sessionmaker: sessionmaker[Session], practice_service: PracticeService
) -> None:
    student = _seed_user(pg_sessionmaker)
    _seed_rows(pg_sessionmaker, topics=["1 Motion", "2 Thermal"], per_topic=3)
    _seed_weakness(pg_sessionmaker, student, topic="2 Thermal", lost_marks=4, maximum_marks=10)
    _seed_weakness(pg_sessionmaker, student, topic="1 Motion", lost_marks=0, maximum_marks=10)

    result = practice_service.topics(student, "0625")

    assert result.weak_topics == ["2 Thermal"]


def test_topics_narrows_to_the_papers_the_student_will_sit(
    pg_sessionmaker: sessionmaker[Session], practice_service: PracticeService
) -> None:
    student = _seed_user(pg_sessionmaker)
    _seed_rows(pg_sessionmaker, topics=["1 Motion"], per_topic=4, stem="0625_s23_qp_41")  # Paper 4
    _seed_enrolment(pg_sessionmaker, student, paper_numbers=[1, 3])

    result = practice_service.topics(student, "0625")

    assert result.topics == []


def test_topics_another_students_enrolment_does_not_narrow_this_one(
    pg_sessionmaker: sessionmaker[Session], practice_service: PracticeService
) -> None:
    student_a = _seed_user(pg_sessionmaker)
    student_b = _seed_user(pg_sessionmaker)
    _seed_rows(pg_sessionmaker, topics=["1 Motion"], per_topic=4, stem="0625_s23_qp_41")
    _seed_enrolment(pg_sessionmaker, student_b, paper_numbers=[1, 3])

    result_a = practice_service.topics(student_a, "0625")
    result_b = practice_service.topics(student_b, "0625")

    assert result_a.topics != []
    assert result_b.topics == []
