"""Tests for T-10 class results (P3.5 chunk F2, ``docs/quiz-model.md`` §4.6).

Service layer (:class:`~lemely.db.quiz_results_repo.QuizResultsService`) and
the single route that exposes it live in one file because they share ~120
lines of throwaway-Postgres fixture boilerplate and the route is a pure
projection of the service — splitting them would duplicate the scaffolding
without testing anything extra. Mirrors ``tests/test_web_quiz.py``'s fixtures.

The three §4.6 rules a naive implementation gets wrong each have a test that
fails against the naive version:

* ``test_per_question_analysis_uses_effective_marks_not_awarded`` fails if the
  aggregation reads ``awarded_marks``;
* ``test_completion_rate_tracks_the_live_roster`` fails if the denominator is
  snapshotted at assignment time;
* ``test_score_distribution_is_percentages_not_grades`` pins that the buckets
  are percentage bands and that quizzes carry no grade to bucket by.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.core.schemas import (
    ConfidenceBand,
    CorrectedQuestion,
    CorrectionResult,
    ExamMetadata,
    WeakArea,
    WeaknessReport,
)
from lemely.db.attempt_repo import AttemptRepository
from lemely.db.base import Base
from lemely.db.class_repo import ClassService
from lemely.db.models import ClassEnrollment, User
from lemely.db.models.attempts import QuestionResult
from lemely.db.models.enums import (
    DifficultySource,
    ExamBoard,
    QuestionDifficulty,
    QuestionSource,
    QuizSubmissionStatus,
    Role,
)
from lemely.db.models.quizzes import QuestionBank, QuizSubmission
from lemely.db.question_bank_repo import QuestionBankService
from lemely.db.quiz_repo import QuizNotFoundError, QuizOwnershipError, QuizService
from lemely.db.quiz_results_repo import QuizResultsService
from lemely.db.quiz_taking_repo import QuizTakingService
from lemely.runtime.config import DatabaseSettings
from lemely.web import create_app
from lemely.web.deps import AuthContext, get_auth_context, get_quiz_results_service

if TYPE_CHECKING:
    from collections.abc import Iterator


# ---------------------------------------------------------------------------
# Fixtures.
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
def class_service(pg_sessionmaker: sessionmaker[Session]) -> ClassService:
    return ClassService(pg_sessionmaker)


@pytest.fixture
def quiz_service(
    pg_sessionmaker: sessionmaker[Session], class_service: ClassService
) -> QuizService:
    return QuizService(pg_sessionmaker, class_service, QuestionBankService(pg_sessionmaker))


@pytest.fixture
def taking_service(
    pg_sessionmaker: sessionmaker[Session], class_service: ClassService
) -> QuizTakingService:
    return QuizTakingService(pg_sessionmaker, class_service)


@pytest.fixture
def attempt_repo(pg_sessionmaker: sessionmaker[Session]) -> AttemptRepository:
    return AttemptRepository(pg_sessionmaker)


@pytest.fixture
def results_service(
    pg_sessionmaker: sessionmaker[Session],
    quiz_service: QuizService,
    class_service: ClassService,
) -> QuizResultsService:
    return QuizResultsService(pg_sessionmaker, quiz_service, class_service)


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app()
    yield TestClient(app)
    app.dependency_overrides.clear()


def _auth_as(client: TestClient, user_id: uuid.UUID, role: Role) -> None:
    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(user_id), role=role.value
    )


# ---------------------------------------------------------------------------
# Seed helpers.
# ---------------------------------------------------------------------------


def _seed_user(
    sm: sessionmaker[Session], role: Role, *, display_name: str | None = None
) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role, display_name=display_name))
    return uid


def _seed_bank(sm: sessionmaker[Session], subject_code: str) -> None:
    """Three rows per band so ``allocate_difficulty`` can always fill a 3-question quiz."""
    with sm.begin() as session:
        for band in QuestionDifficulty:
            for index in range(3):
                session.add(
                    QuestionBank(
                        board=ExamBoard.caie,
                        subject_code=subject_code,
                        source=QuestionSource.generated,
                        difficulty=band,
                        difficulty_source=DifficultySource.declared_by_generator,
                        question_type="explanation",
                        topic="Waves" if index % 2 == 0 else "Forces",
                        prompt=f"{band.value} question {index}",
                        model_answer="model",
                        mark_scheme_points=["p"],
                        total_marks=3,
                    )
                )


def _quiz_metadata(subject_code: str = "0625") -> ExamMetadata:
    """The synthetic shape the quiz marking path builds (§4.3) — never persisted."""
    return ExamMetadata(
        subject_code=subject_code,
        paper_number=1,
        paper_variant=1,
        session_month="Specimen",
        session_year=None,
    )


def _enroll(sm: sessionmaker[Session], class_id: uuid.UUID, student_id: uuid.UUID) -> None:
    with sm.begin() as session:
        session.add(ClassEnrollment(class_id=class_id, student_id=student_id))


def _unenroll(sm: sessionmaker[Session], class_id: uuid.UUID, student_id: uuid.UUID) -> None:
    with sm.begin() as session:
        session.execute(
            sa.delete(ClassEnrollment).where(
                ClassEnrollment.class_id == class_id,
                ClassEnrollment.student_id == student_id,
            )
        )


class _Scenario:
    """A teacher with one 3-question quiz assigned to a class of three students."""

    def __init__(
        self,
        teacher: uuid.UUID,
        class_id: uuid.UUID,
        quiz_id: uuid.UUID,
        assignment_id: uuid.UUID,
        refs: list[str],
        students: dict[str, uuid.UUID],
    ) -> None:
        self.teacher = teacher
        self.class_id = class_id
        self.quiz_id = quiz_id
        self.assignment_id = assignment_id
        self.refs = refs
        self.students = students


def _scenario(
    sm: sessionmaker[Session],
    quiz_service: QuizService,
    class_service: ClassService,
    *,
    subject_code: str = "0625",
) -> _Scenario:
    teacher = _seed_user(sm, Role.teacher, display_name="Ms Nour")
    _seed_bank(sm, subject_code)
    quiz = quiz_service.create_quiz(teacher, subject_code, "Waves recap")
    quiz_service.patch_draft(
        teacher, quiz.quiz_id, pool_source=QuestionSource.generated, requested_count=3
    )
    quiz_service.generate_questions(teacher, quiz.quiz_id)
    detail = quiz_service.get_quiz(teacher, quiz.quiz_id)
    refs = [q.question_ref for q in sorted(detail.questions, key=lambda q: q.position)]
    assert len(refs) == 3, "fixture must produce exactly three questions"

    cls = class_service.create_class(teacher, "9A")
    students = {
        name: _seed_user(sm, Role.student, display_name=name)
        for name in ("Amira", "Bilal", "Carla")
    }
    for student_id in students.values():
        _enroll(sm, cls.class_id, student_id)

    assignment = quiz_service.create_assignment(teacher, Role.teacher, quiz.quiz_id, cls.class_id)
    return _Scenario(
        teacher=teacher,
        class_id=cls.class_id,
        quiz_id=quiz.quiz_id,
        assignment_id=assignment.assignment_id,
        refs=refs,
        students=students,
    )


def _submit(
    taking_service: QuizTakingService, student: uuid.UUID, assignment_id: uuid.UUID
) -> uuid.UUID:
    take = taking_service.get_take(student, assignment_id)
    for question in take.questions:
        taking_service.save_answer(
            student, assignment_id, question.question_ref, answer_text="an answer"
        )
    return taking_service.submit(student, assignment_id).submission_id


def _mark(
    sm: sessionmaker[Session],
    attempt_repo: AttemptRepository,
    student: uuid.UUID,
    submission_id: uuid.UUID,
    marks: list[tuple[str, int, int]],
    *,
    weak_areas: list[WeakArea] | None = None,
    needs_review_refs: frozenset[str] = frozenset(),
) -> uuid.UUID:
    """Persist a marked attempt through the real quiz writer and link the submission.

    Uses :meth:`~lemely.db.attempt_repo.AttemptRepository.persist_quiz_correction`
    — the same writer chunk F1's :class:`QuizMarkingService` persists through —
    rather than driving the marker itself, so these tests exercise the T-10
    aggregation without a Gemini round trip.
    """
    correction = CorrectionResult(
        metadata=_quiz_metadata(),
        questions=[
            CorrectedQuestion(
                question_id=ref,
                awarded_marks=awarded,
                maximum_marks=maximum,
                confidence=ConfidenceBand.HIGH,
                confidence_score=0.9,
                needs_teacher_review=ref in needs_review_refs,
                marker_source="ai",
            )
            for ref, awarded, maximum in marks
        ],
    )
    attempt_id = attempt_repo.persist_quiz_correction(
        user_id=str(student),
        correction=correction,
        weaknesses=WeaknessReport(weak_areas=weak_areas or []),
    )
    with sm.begin() as session:
        submission = session.get(QuizSubmission, submission_id)
        assert submission is not None
        submission.attempt_id = attempt_id
        submission.status = QuizSubmissionStatus.marked
        submission.marked_at = datetime.now(UTC)
    return attempt_id


def _override(
    sm: sessionmaker[Session],
    attempt_id: uuid.UUID,
    question_ref: str,
    teacher_marks: int,
    teacher_id: uuid.UUID,
) -> None:
    """Record a teacher override on one question, exactly as P3.4's flow writes it.

    Written directly rather than through ``ReviewService`` so the test isolates
    the *read* side: the point is that T-10's aggregation reads
    ``effective_marks``, not that the override flow works (P3.4 pins that).
    """
    with sm.begin() as session:
        result = session.scalars(
            select(QuestionResult).where(
                QuestionResult.attempt_id == attempt_id,
                QuestionResult.question_id == question_ref,
            )
        ).one()
        result.teacher_awarded_marks = teacher_marks
        result.overridden_by = teacher_id
        result.overridden_at = datetime.now(UTC)


# ---------------------------------------------------------------------------
# 1. Completion rate — against the live roster (§4.6 rule (c)).
# ---------------------------------------------------------------------------


def test_completion_rate_tracks_the_live_roster(
    pg_sessionmaker: sessionmaker[Session],
    quiz_service: QuizService,
    class_service: ClassService,
    taking_service: QuizTakingService,
    attempt_repo: AttemptRepository,
    results_service: QuizResultsService,
) -> None:
    """A student joining after assignment moves the denominator immediately."""
    scenario = _scenario(pg_sessionmaker, quiz_service, class_service)
    submission = _submit(taking_service, scenario.students["Amira"], scenario.assignment_id)
    _mark(
        pg_sessionmaker,
        attempt_repo,
        scenario.students["Amira"],
        submission,
        [(ref, 3, 3) for ref in scenario.refs],
    )

    results = results_service.assignment_results(
        scenario.teacher, Role.teacher, scenario.quiz_id, scenario.assignment_id
    )
    assert results.completion.roster_size == 3
    assert results.completion.completed_count == 1
    assert results.completion.completion_rate == pytest.approx(1 / 3, abs=1e-4)

    latecomer = _seed_user(pg_sessionmaker, Role.student, display_name="Dina")
    _enroll(pg_sessionmaker, scenario.class_id, latecomer)

    after = results_service.assignment_results(
        scenario.teacher, Role.teacher, scenario.quiz_id, scenario.assignment_id
    )
    assert after.completion.roster_size == 4
    assert after.completion.completion_rate == pytest.approx(0.25)
    # Zero-filled and summing to the roster: three students never opened it.
    assert after.completion.status_counts["not_started"] == 3
    assert sum(after.completion.status_counts.values()) == 4


def test_in_progress_does_not_count_as_completed(
    pg_sessionmaker: sessionmaker[Session],
    quiz_service: QuizService,
    class_service: ClassService,
    taking_service: QuizTakingService,
    results_service: QuizResultsService,
) -> None:
    """Opening a quiz creates an ``in_progress`` row; that is not completion."""
    scenario = _scenario(pg_sessionmaker, quiz_service, class_service)
    taking_service.get_take(scenario.students["Amira"], scenario.assignment_id)

    results = results_service.assignment_results(
        scenario.teacher, Role.teacher, scenario.quiz_id, scenario.assignment_id
    )
    assert results.completion.completed_count == 0
    assert results.completion.status_counts["in_progress"] == 1
    assert results.completion.status_counts["not_started"] == 2


def test_submitted_but_unmarked_counts_as_completed(
    pg_sessionmaker: sessionmaker[Session],
    quiz_service: QuizService,
    class_service: ClassService,
    taking_service: QuizTakingService,
    results_service: QuizResultsService,
) -> None:
    """Marking is asynchronous — completion must not dip while it runs (F1)."""
    scenario = _scenario(pg_sessionmaker, quiz_service, class_service)
    _submit(taking_service, scenario.students["Amira"], scenario.assignment_id)

    results = results_service.assignment_results(
        scenario.teacher, Role.teacher, scenario.quiz_id, scenario.assignment_id
    )
    assert results.completion.completed_count == 1
    assert results.completion.status_counts["submitted"] == 1
    # No attempt yet, so no score to report — null, never a zero.
    amira = next(s for s in results.students if s.display_name == "Amira")
    assert amira.percentage is None
    assert amira.marks_by_question == {}


def test_empty_roster_reports_a_null_completion_rate(
    pg_sessionmaker: sessionmaker[Session],
    quiz_service: QuizService,
    class_service: ClassService,
    results_service: QuizResultsService,
) -> None:
    """0/0 is not 0% — an empty class reports ``None``, not "nobody has done it"."""
    scenario = _scenario(pg_sessionmaker, quiz_service, class_service)
    for student_id in scenario.students.values():
        _unenroll(pg_sessionmaker, scenario.class_id, student_id)

    results = results_service.assignment_results(
        scenario.teacher, Role.teacher, scenario.quiz_id, scenario.assignment_id
    )
    assert results.completion.roster_size == 0
    assert results.completion.completion_rate is None
    assert results.students == []
    assert results.average_percentage is None
    assert results.median_percentage is None


def test_off_roster_submission_is_excluded_but_reported(
    pg_sessionmaker: sessionmaker[Session],
    quiz_service: QuizService,
    class_service: ClassService,
    taking_service: QuizTakingService,
    attempt_repo: AttemptRepository,
    results_service: QuizResultsService,
) -> None:
    """A student who left the class is counted nowhere, but their work is not hidden."""
    scenario = _scenario(pg_sessionmaker, quiz_service, class_service)
    leaver = scenario.students["Bilal"]
    submission = _submit(taking_service, leaver, scenario.assignment_id)
    _mark(
        pg_sessionmaker,
        attempt_repo,
        leaver,
        submission,
        [(ref, 3, 3) for ref in scenario.refs],
    )
    _unenroll(pg_sessionmaker, scenario.class_id, leaver)

    results = results_service.assignment_results(
        scenario.teacher, Role.teacher, scenario.quiz_id, scenario.assignment_id
    )
    assert results.completion.roster_size == 2
    assert results.completion.completed_count == 0
    assert results.completion.off_roster_submission_count == 1
    assert [s.display_name for s in results.students] == ["Amira", "Carla"]
    # Their marks are out of every aggregation, so the rate can never exceed 1.
    assert results.average_percentage is None
    assert all(bucket.student_count == 0 for bucket in results.score_distribution)


# ---------------------------------------------------------------------------
# 2. Score distribution — percentages, never grades (§4.6 rule (b)).
# ---------------------------------------------------------------------------


def test_score_distribution_is_percentages_not_grades(
    pg_sessionmaker: sessionmaker[Session],
    quiz_service: QuizService,
    class_service: ClassService,
    taking_service: QuizTakingService,
    attempt_repo: AttemptRepository,
    results_service: QuizResultsService,
) -> None:
    """Ten-point bands, top band inclusive of 100, and no grade anywhere to bucket by."""
    scenario = _scenario(pg_sessionmaker, quiz_service, class_service)
    # 9/9 = 100%, 5/9 = 55.6%, 0/9 = 0% -> the 90-100, 50-59 and 0-9 bands.
    plans = {
        "Amira": [(scenario.refs[0], 3, 3), (scenario.refs[1], 3, 3), (scenario.refs[2], 3, 3)],
        "Bilal": [(scenario.refs[0], 3, 3), (scenario.refs[1], 2, 3), (scenario.refs[2], 0, 3)],
        "Carla": [(scenario.refs[0], 0, 3), (scenario.refs[1], 0, 3), (scenario.refs[2], 0, 3)],
    }
    for name, marks in plans.items():
        submission = _submit(taking_service, scenario.students[name], scenario.assignment_id)
        _mark(pg_sessionmaker, attempt_repo, scenario.students[name], submission, marks)

    results = results_service.assignment_results(
        scenario.teacher, Role.teacher, scenario.quiz_id, scenario.assignment_id
    )
    populated = {
        (b.lower, b.upper): b.student_count for b in results.score_distribution if b.student_count
    }
    assert populated == {(90, 100): 1, (50, 59): 1, (0, 9): 1}
    assert len(results.score_distribution) == 10
    assert results.average_percentage == pytest.approx(51.85, abs=0.01)
    assert results.median_percentage == pytest.approx(55.56, abs=0.01)


# ---------------------------------------------------------------------------
# 3. Per-question analysis — effective_marks, never awarded_marks (rule (a)).
# ---------------------------------------------------------------------------


def test_per_question_analysis_uses_effective_marks_not_awarded(
    pg_sessionmaker: sessionmaker[Session],
    quiz_service: QuizService,
    class_service: ClassService,
    taking_service: QuizTakingService,
    attempt_repo: AttemptRepository,
    results_service: QuizResultsService,
) -> None:
    """A teacher's own override must move the class view, not just the student's.

    Both students are marked 0 on ``q1`` by the AI; the teacher restores 3
    marks for one of them. Reading ``awarded_marks`` would report an average
    of 0.0 and an accuracy of 0.0 here — the exact "correction visible on one
    screen, missing on another" failure §4.6 rule (a) forbids.
    """
    scenario = _scenario(pg_sessionmaker, quiz_service, class_service)
    q1 = scenario.refs[0]
    attempts: dict[str, uuid.UUID] = {}
    for name in ("Amira", "Bilal"):
        submission = _submit(taking_service, scenario.students[name], scenario.assignment_id)
        attempts[name] = _mark(
            pg_sessionmaker,
            attempt_repo,
            scenario.students[name],
            submission,
            [(ref, 0, 3) for ref in scenario.refs],
            needs_review_refs=frozenset({q1}),
        )
    _override(pg_sessionmaker, attempts["Amira"], q1, 3, scenario.teacher)

    results = results_service.assignment_results(
        scenario.teacher, Role.teacher, scenario.quiz_id, scenario.assignment_id
    )
    row = next(q for q in results.question_analysis if q.question_ref == q1)
    assert row.answered_count == 2
    assert row.average_marks == pytest.approx(1.5)
    # 3 effective marks earned out of the 6 that were marked (2 students x 3).
    assert row.accuracy == pytest.approx(0.5)
    assert row.full_marks_count == 1
    assert row.zero_marks_count == 1
    assert row.overridden_count == 1
    assert row.needs_review_count == 2

    # ...and the per-student panel reads the same accessor.
    amira = next(s for s in results.students if s.display_name == "Amira")
    assert amira.marks_by_question[q1] == 3
    bilal = next(s for s in results.students if s.display_name == "Bilal")
    assert bilal.marks_by_question[q1] == 0


def test_question_analysis_covers_every_question_in_display_order(
    pg_sessionmaker: sessionmaker[Session],
    quiz_service: QuizService,
    class_service: ClassService,
    results_service: QuizResultsService,
) -> None:
    """Unanswered questions appear with null averages — never a silently missing row."""
    scenario = _scenario(pg_sessionmaker, quiz_service, class_service)

    results = results_service.assignment_results(
        scenario.teacher, Role.teacher, scenario.quiz_id, scenario.assignment_id
    )
    assert [q.question_ref for q in results.question_analysis] == scenario.refs
    assert [q.position for q in results.question_analysis] == sorted(
        q.position for q in results.question_analysis
    )
    assert all(q.answered_count == 0 for q in results.question_analysis)
    assert all(q.average_marks is None for q in results.question_analysis)
    assert all(q.accuracy is None for q in results.question_analysis)
    assert results.question_count == 3
    assert results.total_marks == 9


# ---------------------------------------------------------------------------
# 4. Per-student results and 5. class-wide weaknesses.
# ---------------------------------------------------------------------------


def test_student_rows_cover_the_whole_roster_including_non_starters(
    pg_sessionmaker: sessionmaker[Session],
    quiz_service: QuizService,
    class_service: ClassService,
    taking_service: QuizTakingService,
    attempt_repo: AttemptRepository,
    results_service: QuizResultsService,
) -> None:
    """Every roster student has a row; those who never started are visibly empty."""
    scenario = _scenario(pg_sessionmaker, quiz_service, class_service)
    submission = _submit(taking_service, scenario.students["Amira"], scenario.assignment_id)
    _mark(
        pg_sessionmaker,
        attempt_repo,
        scenario.students["Amira"],
        submission,
        [(scenario.refs[0], 3, 3), (scenario.refs[1], 1, 3), (scenario.refs[2], 0, 3)],
    )

    results = results_service.assignment_results(
        scenario.teacher, Role.teacher, scenario.quiz_id, scenario.assignment_id
    )
    assert len(results.students) == 3
    amira = next(s for s in results.students if s.display_name == "Amira")
    assert amira.status is QuizSubmissionStatus.marked
    assert amira.awarded_marks == 4
    assert amira.maximum_marks == 9
    assert amira.percentage == pytest.approx(44.44, abs=0.01)
    assert amira.marks_by_question == {
        scenario.refs[0]: 3,
        scenario.refs[1]: 1,
        scenario.refs[2]: 0,
    }
    assert amira.marking_error is None

    carla = next(s for s in results.students if s.display_name == "Carla")
    assert carla.status is QuizSubmissionStatus.not_started
    assert carla.awarded_marks is None
    assert carla.percentage is None
    assert carla.marks_by_question == {}


def test_topic_weaknesses_are_scoped_to_this_assignment(
    pg_sessionmaker: sessionmaker[Session],
    quiz_service: QuizService,
    class_service: ClassService,
    taking_service: QuizTakingService,
    attempt_repo: AttemptRepository,
    results_service: QuizResultsService,
) -> None:
    """Ranked over this assignment's attempts only — not the students' whole history.

    A prior past-paper attempt with a different weak topic exists for the same
    student; T-10 must not surface it, or "what did my class find hard *in
    this quiz*" silently becomes "what has this class ever found hard".
    """
    scenario = _scenario(pg_sessionmaker, quiz_service, class_service)
    amira = scenario.students["Amira"]
    # Prior, unrelated attempt for the same student.
    attempt_repo.persist_quiz_correction(
        user_id=str(amira),
        correction=CorrectionResult(
            metadata=_quiz_metadata(),
            questions=[
                CorrectedQuestion(
                    question_id="old1",
                    awarded_marks=0,
                    maximum_marks=4,
                    confidence=ConfidenceBand.HIGH,
                    confidence_score=0.9,
                    needs_teacher_review=False,
                    marker_source="ai",
                )
            ],
        ),
        weaknesses=WeaknessReport(
            weak_areas=[
                WeakArea(
                    topic="Radioactivity",
                    lost_marks=4,
                    maximum_marks=4,
                    accuracy=0.0,
                    question_ids=["old1"],
                )
            ]
        ),
    )

    submission = _submit(taking_service, amira, scenario.assignment_id)
    _mark(
        pg_sessionmaker,
        attempt_repo,
        amira,
        submission,
        [(ref, 1, 3) for ref in scenario.refs],
        weak_areas=[
            WeakArea(
                topic="Waves",
                lost_marks=4,
                maximum_marks=6,
                accuracy=0.3333,
                question_ids=[scenario.refs[0], scenario.refs[1]],
            ),
            WeakArea(
                topic="Forces",
                lost_marks=2,
                maximum_marks=3,
                accuracy=0.3333,
                question_ids=[scenario.refs[2]],
            ),
        ],
    )

    results = results_service.assignment_results(
        scenario.teacher, Role.teacher, scenario.quiz_id, scenario.assignment_id
    )
    assert [w.topic for w in results.topic_weaknesses] == ["Waves", "Forces"]
    assert results.topic_weaknesses[0].lost_marks == 4
    assert results.topic_weaknesses[0].student_ids == [str(amira)]


# ---------------------------------------------------------------------------
# 6. Authorization — ownership is reused, never re-derived.
# ---------------------------------------------------------------------------


def test_another_teachers_quiz_is_forbidden(
    pg_sessionmaker: sessionmaker[Session],
    quiz_service: QuizService,
    class_service: ClassService,
    results_service: QuizResultsService,
) -> None:
    scenario = _scenario(pg_sessionmaker, quiz_service, class_service)
    intruder = _seed_user(pg_sessionmaker, Role.teacher)

    with pytest.raises(QuizOwnershipError):
        results_service.assignment_results(
            intruder, Role.teacher, scenario.quiz_id, scenario.assignment_id
        )


def test_school_admin_has_no_view_into_a_quizs_results(
    pg_sessionmaker: sessionmaker[Session],
    quiz_service: QuizService,
    class_service: ClassService,
    results_service: QuizResultsService,
) -> None:
    """Quiz ownership stays strictly ``teacher_id``-scoped — ``caller_role`` reaches
    ``ClassService`` only, and never widens the quiz check (chunk D/E rule)."""
    scenario = _scenario(pg_sessionmaker, quiz_service, class_service)
    admin = _seed_user(pg_sessionmaker, Role.school_admin)

    with pytest.raises(QuizOwnershipError):
        results_service.assignment_results(
            admin, Role.school_admin, scenario.quiz_id, scenario.assignment_id
        )


def test_assignment_from_another_quiz_is_not_found(
    pg_sessionmaker: sessionmaker[Session],
    quiz_service: QuizService,
    class_service: ClassService,
    results_service: QuizResultsService,
) -> None:
    """An assignment id must belong to the quiz in the path, not merely exist."""
    first = _scenario(pg_sessionmaker, quiz_service, class_service)
    other = quiz_service.create_quiz(first.teacher, "0625", "Second quiz")

    with pytest.raises(QuizNotFoundError):
        results_service.assignment_results(
            first.teacher, Role.teacher, other.quiz_id, first.assignment_id
        )


def test_unknown_assignment_is_not_found(
    pg_sessionmaker: sessionmaker[Session],
    quiz_service: QuizService,
    class_service: ClassService,
    results_service: QuizResultsService,
) -> None:
    scenario = _scenario(pg_sessionmaker, quiz_service, class_service)

    with pytest.raises(QuizNotFoundError):
        results_service.assignment_results(
            scenario.teacher, Role.teacher, scenario.quiz_id, uuid.uuid4()
        )


# ---------------------------------------------------------------------------
# 7. The route.
# ---------------------------------------------------------------------------


def test_results_route_returns_all_five_panels(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    quiz_service: QuizService,
    class_service: ClassService,
    taking_service: QuizTakingService,
    attempt_repo: AttemptRepository,
    results_service: QuizResultsService,
) -> None:
    scenario = _scenario(pg_sessionmaker, quiz_service, class_service)
    submission = _submit(taking_service, scenario.students["Amira"], scenario.assignment_id)
    _mark(
        pg_sessionmaker,
        attempt_repo,
        scenario.students["Amira"],
        submission,
        [(ref, 3, 3) for ref in scenario.refs],
        weak_areas=[
            WeakArea(
                topic="Waves", lost_marks=1, maximum_marks=3, accuracy=0.667, question_ids=["q1"]
            )
        ],
    )
    client.app.dependency_overrides[get_quiz_results_service] = lambda: results_service  # type: ignore[union-attr]
    _auth_as(client, scenario.teacher, Role.teacher)

    response = client.get(
        f"/api/teacher/quizzes/{scenario.quiz_id}/assignments/{scenario.assignment_id}/results"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["quizTitle"] == "Waves recap"
    assert body["subjectCode"] == "0625"
    assert body["assignment"]["className"] == "9A"
    assert body["completion"]["rosterSize"] == 3
    assert body["completion"]["completedCount"] == 1
    assert body["completion"]["completionRate"] == pytest.approx(1 / 3, abs=1e-4)
    assert len(body["scoreDistribution"]) == 10
    assert len(body["questionAnalysis"]) == 3
    assert [s["displayName"] for s in body["students"]] == ["Amira", "Bilal", "Carla"]
    assert body["topicWeaknesses"][0]["topic"] == "Waves"
    assert body["averagePercentage"] == pytest.approx(100.0)


def test_results_route_never_leaks_a_model_answer(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    quiz_service: QuizService,
    class_service: ClassService,
    results_service: QuizResultsService,
) -> None:
    """A teacher surface may legitimately show model answers — but this DTO has no
    field for one, so a future edit cannot accidentally widen it into a student
    payload (D3.8's structural guard, kept intact)."""
    scenario = _scenario(pg_sessionmaker, quiz_service, class_service)
    client.app.dependency_overrides[get_quiz_results_service] = lambda: results_service  # type: ignore[union-attr]
    _auth_as(client, scenario.teacher, Role.teacher)

    response = client.get(
        f"/api/teacher/quizzes/{scenario.quiz_id}/assignments/{scenario.assignment_id}/results"
    )

    assert response.status_code == 200
    assert "model" not in response.text.lower().replace("modelanswer", "")
    for question in response.json()["questionAnalysis"]:
        assert "modelAnswer" not in question
        assert "markSchemePoints" not in question


def test_results_route_rejects_a_student(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    quiz_service: QuizService,
    class_service: ClassService,
    results_service: QuizResultsService,
) -> None:
    scenario = _scenario(pg_sessionmaker, quiz_service, class_service)
    client.app.dependency_overrides[get_quiz_results_service] = lambda: results_service  # type: ignore[union-attr]
    _auth_as(client, scenario.students["Amira"], Role.student)

    response = client.get(
        f"/api/teacher/quizzes/{scenario.quiz_id}/assignments/{scenario.assignment_id}/results"
    )

    assert response.status_code == 403


def test_results_route_maps_ownership_to_403_and_unknown_to_404(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    quiz_service: QuizService,
    class_service: ClassService,
    results_service: QuizResultsService,
) -> None:
    scenario = _scenario(pg_sessionmaker, quiz_service, class_service)
    intruder = _seed_user(pg_sessionmaker, Role.teacher)
    client.app.dependency_overrides[get_quiz_results_service] = lambda: results_service  # type: ignore[union-attr]

    _auth_as(client, intruder, Role.teacher)
    forbidden = client.get(
        f"/api/teacher/quizzes/{scenario.quiz_id}/assignments/{scenario.assignment_id}/results"
    )
    assert forbidden.status_code == 403

    _auth_as(client, scenario.teacher, Role.teacher)
    missing = client.get(
        f"/api/teacher/quizzes/{scenario.quiz_id}/assignments/{uuid.uuid4()}/results"
    )
    assert missing.status_code == 404

    malformed = client.get(
        f"/api/teacher/quizzes/{scenario.quiz_id}/assignments/not-a-uuid/results"
    )
    assert malformed.status_code == 422
