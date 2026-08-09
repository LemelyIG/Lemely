"""Tests for :mod:`lemely.db.study_plan_repo` (P4.7 chunk B).

Postgres-integration, mirroring ``tests/test_flashcard_repo.py``'s
throwaway-database fixture. No Gemini anywhere in this module or its tests.

Covers:

* Sourcing the three live signals: weakness (``WeaknessRecord``, summed per
  topic, zero-net-lost excluded), placement (most recently *marked*
  placement attempt's breakdown, owner-scoped), confidence (S-02 ratings; no
  enrolment/no ratings is an empty signal, never an error) — each verified
  by its inverse.
* Availability earned from the live bank/deck, not defaulted.
* The persisted honesty split: a ``no_signal`` refusal is distinguishable on
  read from the real "nothing to schedule this week" state.
* Weekly regeneration: same-week supersedes, a different week leaves last
  week's plan untouched and still readable.
* Per-session completion: idempotent, owner-scoped (404-shaped for both an
  unknown id and another student's id, but as distinct exception types).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.db.base import Base
from lemely.db.models.academic import Subject
from lemely.db.models.attempts import Attempt, WeaknessRecord
from lemely.db.models.enums import (
    AttemptOrigin,
    DifficultySource,
    QuestionDifficulty,
    QuestionSource,
    QuizKind,
    QuizSubmissionStatus,
    Role,
)
from lemely.db.models.flashcards import DeckOrigin, FlashcardDeck
from lemely.db.models.profiles import (
    StudentConfidenceRating,
    StudentProfile,
    StudentSubjectEnrolment,
)
from lemely.db.models.quizzes import QuestionBank, Quiz, QuizAssignment, QuizSubmission
from lemely.db.models.study_plan import StudyPlanActivityType
from lemely.db.models.users import User
from lemely.db.study_plan_repo import (
    StudyPlanNotFoundError,
    StudyPlanOwnershipError,
    StudyPlanService,
)
from lemely.runtime.config import DatabaseSettings

if TYPE_CHECKING:
    from collections.abc import Iterator

# ---------------------------------------------------------------------------
# Fixtures — throwaway Postgres database, mirrors the sibling flashcard suite.
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


# A fixed Wednesday, so week arithmetic in tests is unambiguous.
_THIS_WEEK = datetime(2026, 8, 5, 9, 0, 0, tzinfo=UTC)
_LAST_WEEK = _THIS_WEEK - timedelta(days=7)


@pytest.fixture
def study_plan_service(pg_sessionmaker: sessionmaker[Session]) -> StudyPlanService:
    return StudyPlanService(pg_sessionmaker, now=lambda: _THIS_WEEK)


def _seed_user(sm: sessionmaker[Session], role: Role = Role.student) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role))
    return uid


def _seed_subject(sm: sessionmaker[Session], code: str = "0625") -> None:
    with sm.begin() as session:
        existing = session.scalars(sa.select(Subject).where(Subject.code == code)).first()
        if existing is None:
            session.add(Subject(code=code, name="Physics"))


def _seed_weakness(
    sm: sessionmaker[Session],
    student_id: uuid.UUID,
    *,
    subject_code: str = "0625",
    topic: str,
    lost_marks: int,
    maximum_marks: int = 10,
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


def _seed_placement_result(
    sm: sessionmaker[Session],
    student_id: uuid.UUID,
    *,
    subject_code: str = "0625",
    topic: str,
    lost_marks: int,
    maximum_marks: int = 10,
    marked_at: datetime,
    status: QuizSubmissionStatus = QuizSubmissionStatus.marked,
) -> None:
    with sm.begin() as session:
        quiz = Quiz(
            teacher_id=None,
            student_id=student_id,
            kind=QuizKind.placement,
            subject_code=subject_code,
            title="Placement",
        )
        session.add(quiz)
        session.flush()

        assignment = QuizAssignment(quiz_id=quiz.id, student_id=student_id, assigned_by=student_id)
        session.add(assignment)
        session.flush()

        attempt_id = None
        if status == QuizSubmissionStatus.marked:
            # An Attempt/WeaknessRecord only exists once marking has actually
            # run (marking is what creates them) — an unmarked submission has
            # neither, mirroring the real system rather than a test-only
            # shortcut, so it also contributes nothing to the separate
            # rolling-weakness signal.
            attempt = Attempt(
                user_id=student_id,
                subject_code=subject_code,
                awarded_marks=maximum_marks - lost_marks,
                maximum_marks=maximum_marks,
                percentage=100.0 * (maximum_marks - lost_marks) / maximum_marks,
                recorded_at=marked_at,
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
            attempt_id = attempt.id

        submission = QuizSubmission(
            assignment_id=assignment.id,
            student_id=student_id,
            status=status,
            attempt_id=attempt_id,
            marked_at=marked_at if status == QuizSubmissionStatus.marked else None,
        )
        session.add(submission)


def _seed_confidence(
    sm: sessionmaker[Session],
    student_id: uuid.UUID,
    *,
    subject_code: str = "0625",
    topic: str,
    rating: int,
) -> None:
    _seed_subject(sm, subject_code)
    with sm.begin() as session:
        enrolment = session.scalars(
            sa.select(StudentSubjectEnrolment).where(
                StudentSubjectEnrolment.user_id == student_id,
                StudentSubjectEnrolment.subject_code == subject_code,
            )
        ).first()
        if enrolment is None:
            enrolment = StudentSubjectEnrolment(user_id=student_id, subject_code=subject_code)
            session.add(enrolment)
            session.flush()
        session.add(StudentConfidenceRating(enrolment_id=enrolment.id, topic=topic, rating=rating))


def _seed_bank_question(
    sm: sessionmaker[Session],
    *,
    subject_code: str = "0625",
    topic: str,
    source: QuestionSource = QuestionSource.past_paper,
    prompt: str = "Question",
) -> None:
    with sm.begin() as session:
        session.add(
            QuestionBank(
                subject_code=subject_code,
                source=source,
                topic=topic,
                difficulty=QuestionDifficulty.standard,
                difficulty_source=DifficultySource.inferred_from_marks,
                question_type="mcq",
                prompt=prompt,
                total_marks=2,
                mcq_options=["A", "B"],
                mcq_answer="A",
            )
        )


def _seed_flashcard_deck(
    sm: sessionmaker[Session],
    student_id: uuid.UUID,
    *,
    subject_code: str = "0625",
    topic: str,
) -> None:
    with sm.begin() as session:
        session.add(
            FlashcardDeck(
                user_id=student_id,
                subject_code=subject_code,
                topic=topic,
                title=f"{topic} deck",
                origin=DeckOrigin.topic,
            )
        )


def _seed_profile(
    sm: sessionmaker[Session], student_id: uuid.UUID, *, weekly_study_hours: int
) -> None:
    with sm.begin() as session:
        session.add(StudentProfile(user_id=student_id, weekly_study_hours=weekly_study_hours))


# ---------------------------------------------------------------------------
# Honesty: no_signal refusal vs. the real empty-week state.
# ---------------------------------------------------------------------------


def test_no_signal_is_persisted_as_a_refusal(
    pg_sessionmaker: sessionmaker[Session], study_plan_service: StudyPlanService
) -> None:
    student = _seed_user(pg_sessionmaker)
    plan = study_plan_service.generate(student, "0625")
    assert plan.available is False
    assert plan.reason == "no_signal"
    assert plan.sessions == []

    # Inverse: a real weakness row makes it available.
    _seed_weakness(pg_sessionmaker, student, topic="1 Motion", lost_marks=5)
    plan2 = study_plan_service.generate(student, "0625")
    assert plan2.available is True
    assert plan2.reason is None
    assert len(plan2.sessions) > 0


def test_a_zero_scoring_topic_is_a_real_empty_week_not_a_refusal(
    pg_sessionmaker: sessionmaker[Session], study_plan_service: StudyPlanService
) -> None:
    """Full confidence everywhere -> ``available=True``, empty sessions.

    Distinct from ``no_signal``: there *was* a signal (a confidence rating),
    it just scored every topic at zero priority.
    """
    student = _seed_user(pg_sessionmaker)
    _seed_confidence(pg_sessionmaker, student, topic="1 Motion", rating=5)

    plan = study_plan_service.generate(student, "0625")

    assert plan.available is True
    assert plan.reason is None
    assert plan.sessions == []


# ---------------------------------------------------------------------------
# Sourcing: weakness.
# ---------------------------------------------------------------------------


def test_weakness_topics_with_zero_net_lost_marks_are_excluded(
    pg_sessionmaker: sessionmaker[Session], study_plan_service: StudyPlanService
) -> None:
    student = _seed_user(pg_sessionmaker)
    _seed_weakness(pg_sessionmaker, student, topic="1 Motion", lost_marks=0, maximum_marks=10)

    plan = study_plan_service.generate(student, "0625")
    assert plan.available is False
    assert plan.reason == "no_signal"

    # Inverse: nonzero lost marks on the same topic produces a real plan.
    _seed_weakness(pg_sessionmaker, student, topic="1 Motion", lost_marks=4, maximum_marks=10)
    plan2 = study_plan_service.generate(student, "0625")
    assert plan2.available is True
    assert any(s.topic == "1 Motion" for s in plan2.sessions)


# ---------------------------------------------------------------------------
# Sourcing: placement.
# ---------------------------------------------------------------------------


def test_placement_signal_uses_the_most_recently_marked_attempt(
    pg_sessionmaker: sessionmaker[Session], study_plan_service: StudyPlanService
) -> None:
    """Only the latest marked placement attempt's breakdown is the signal.

    Exercises :meth:`StudyPlanService._placement_results` directly (private,
    but ``tests/**`` is exempted from ``SLF001`` for exactly this reason) —
    seeding two *marked* placement attempts also seeds two
    ``WeaknessRecord`` rows, which is real and correct (a placement attempt
    is graded evidence like any other), but it means a full ``generate()``
    call cannot isolate the placement-only signal from the always-on
    rolling-weakness one. Reading the private method's return value is the
    precise way to pin "most recent, not all of them" without that
    confound.
    """
    student = _seed_user(pg_sessionmaker)
    _seed_placement_result(
        pg_sessionmaker,
        student,
        topic="1 Motion",
        lost_marks=6,
        marked_at=_THIS_WEEK - timedelta(days=10),
    )
    _seed_placement_result(
        pg_sessionmaker,
        student,
        topic="3 Waves",
        lost_marks=6,
        marked_at=_THIS_WEEK - timedelta(days=1),
    )

    with pg_sessionmaker() as session:
        results = study_plan_service._placement_results(session, student, "0625")

    topics = {r.topic for r in results}
    assert topics == {"3 Waves"}


def test_an_unmarked_placement_submission_contributes_no_signal(
    pg_sessionmaker: sessionmaker[Session], study_plan_service: StudyPlanService
) -> None:
    student = _seed_user(pg_sessionmaker)
    _seed_placement_result(
        pg_sessionmaker,
        student,
        topic="1 Motion",
        lost_marks=6,
        marked_at=_THIS_WEEK,
        status=QuizSubmissionStatus.submitted,
    )

    plan = study_plan_service.generate(student, "0625")
    assert plan.available is False
    assert plan.reason == "no_signal"

    # Inverse: marking it makes it a real signal.
    _seed_placement_result(
        pg_sessionmaker, student, topic="1 Motion", lost_marks=6, marked_at=_THIS_WEEK
    )
    plan2 = study_plan_service.generate(student, "0625")
    assert plan2.available is True


def test_placement_signal_is_owner_scoped(
    pg_sessionmaker: sessionmaker[Session], study_plan_service: StudyPlanService
) -> None:
    """Another student's marked placement attempt must never leak in."""
    owner = _seed_user(pg_sessionmaker)
    other = _seed_user(pg_sessionmaker)
    _seed_placement_result(
        pg_sessionmaker, other, topic="1 Motion", lost_marks=6, marked_at=_THIS_WEEK
    )

    plan = study_plan_service.generate(owner, "0625")
    assert plan.available is False
    assert plan.reason == "no_signal"


# ---------------------------------------------------------------------------
# Sourcing: confidence (S-02).
# ---------------------------------------------------------------------------


def test_no_enrolment_reads_as_an_empty_confidence_signal_not_an_error(
    pg_sessionmaker: sessionmaker[Session], study_plan_service: StudyPlanService
) -> None:
    student = _seed_user(pg_sessionmaker)
    plan = study_plan_service.generate(student, "0625")  # must not raise
    assert plan.available is False

    # Inverse: a real confidence gap (low rating) produces a scheduled topic.
    _seed_confidence(pg_sessionmaker, student, topic="1 Motion", rating=1)
    plan2 = study_plan_service.generate(student, "0625")
    assert plan2.available is True
    assert any(s.topic == "1 Motion" for s in plan2.sessions)


# ---------------------------------------------------------------------------
# Availability: earned, from the live bank/deck.
# ---------------------------------------------------------------------------


def test_activity_type_is_earned_from_the_live_bank_and_deck(
    pg_sessionmaker: sessionmaker[Session], study_plan_service: StudyPlanService
) -> None:
    student = _seed_user(pg_sessionmaker)
    _seed_weakness(pg_sessionmaker, student, topic="1 Motion", lost_marks=8, maximum_marks=10)

    # No bank rows, no deck: falls back to review, the honest floor.
    plan = study_plan_service.generate(student, "0625")
    assert all(s.activity_type == StudyPlanActivityType.review for s in plan.sessions)

    # Inverse: a real past-paper bank row earns past_paper (highest precedence).
    _seed_bank_question(pg_sessionmaker, topic="1 Motion", source=QuestionSource.past_paper)
    plan2 = study_plan_service.generate(student, "0625")
    assert all(s.activity_type == StudyPlanActivityType.past_paper for s in plan2.sessions)


def test_practice_is_earned_without_past_paper_rows(
    pg_sessionmaker: sessionmaker[Session], study_plan_service: StudyPlanService
) -> None:
    student = _seed_user(pg_sessionmaker)
    _seed_weakness(pg_sessionmaker, student, topic="1 Motion", lost_marks=8, maximum_marks=10)
    _seed_bank_question(pg_sessionmaker, topic="1 Motion", source=QuestionSource.generated)

    plan = study_plan_service.generate(student, "0625")
    assert all(s.activity_type == StudyPlanActivityType.practice for s in plan.sessions)


def test_flashcards_is_earned_from_a_deck_when_no_bank_rows_exist(
    pg_sessionmaker: sessionmaker[Session], study_plan_service: StudyPlanService
) -> None:
    student = _seed_user(pg_sessionmaker)
    _seed_weakness(pg_sessionmaker, student, topic="1 Motion", lost_marks=8, maximum_marks=10)
    _seed_flashcard_deck(pg_sessionmaker, student, topic="1 Motion")

    plan = study_plan_service.generate(student, "0625")
    assert all(s.activity_type == StudyPlanActivityType.flashcards for s in plan.sessions)


def test_bank_availability_is_owner_scoped_to_the_visibility_predicate(
    pg_sessionmaker: sessionmaker[Session], study_plan_service: StudyPlanService
) -> None:
    """A deck belonging to another student must not earn flashcards for this one."""
    student = _seed_user(pg_sessionmaker)
    other = _seed_user(pg_sessionmaker)
    _seed_weakness(pg_sessionmaker, student, topic="1 Motion", lost_marks=8, maximum_marks=10)
    _seed_flashcard_deck(pg_sessionmaker, other, topic="1 Motion")

    plan = study_plan_service.generate(student, "0625")
    assert all(s.activity_type == StudyPlanActivityType.review for s in plan.sessions)


def test_a_figure_dependent_bank_row_does_not_earn_practice_ordinary_rows_still_do(
    pg_sessionmaker: sessionmaker[Session], study_plan_service: StudyPlanService
) -> None:
    """P4.8 chunk 0: ``_availability`` must count the same pool practice would serve.

    A bank row whose prompt reads an existing figure ("The diagram shows...")
    is excluded by ``renderable_bank_filter``; on its own it must not earn
    ``past_paper`` (the false-positive this whole chunk exists to prevent —
    a study plan session pointing at a question the student cannot fully
    see). The inverse: adding one ordinary row in the same topic must earn
    ``practice`` (its `source` is ``generated``, not ``past_paper``), proving
    the predicate did not also swallow the ordinary row.
    """
    student = _seed_user(pg_sessionmaker)
    _seed_weakness(pg_sessionmaker, student, topic="1 Motion", lost_marks=8, maximum_marks=10)
    _seed_bank_question(
        pg_sessionmaker,
        topic="1 Motion",
        source=QuestionSource.past_paper,
        prompt=(
            "The diagram shows a radio signal from the Earth being reflected by Pluto "
            "and returning to the Earth. What is the time taken?"
        ),
    )

    plan = study_plan_service.generate(student, "0625")
    assert all(s.activity_type == StudyPlanActivityType.review for s in plan.sessions)

    # Inverse: an ordinary generated-source row in the same topic is not
    # figure-dependent and must still be counted, earning practice.
    _seed_bank_question(pg_sessionmaker, topic="1 Motion", source=QuestionSource.generated)
    plan2 = study_plan_service.generate(student, "0625")
    assert all(s.activity_type == StudyPlanActivityType.practice for s in plan2.sessions)


# ---------------------------------------------------------------------------
# Weekly hours default.
# ---------------------------------------------------------------------------


def test_weekly_hours_defaults_from_the_student_profile(
    pg_sessionmaker: sessionmaker[Session], study_plan_service: StudyPlanService
) -> None:
    student = _seed_user(pg_sessionmaker)
    _seed_weakness(pg_sessionmaker, student, topic="1 Motion", lost_marks=5)
    _seed_profile(pg_sessionmaker, student, weekly_study_hours=6)

    plan = study_plan_service.generate(student, "0625")
    assert plan.weekly_hours == 6.0

    # Inverse: an explicit override wins over the profile default.
    plan2 = study_plan_service.generate(student, "0625", weekly_hours=3.0)
    assert plan2.weekly_hours == 3.0


# ---------------------------------------------------------------------------
# Weekly regeneration: supersedes, never mutates.
# ---------------------------------------------------------------------------


def test_regenerating_within_the_same_week_supersedes_the_previous_plan(
    pg_sessionmaker: sessionmaker[Session], study_plan_service: StudyPlanService
) -> None:
    student = _seed_user(pg_sessionmaker)
    _seed_weakness(pg_sessionmaker, student, topic="1 Motion", lost_marks=5)

    first = study_plan_service.generate(student, "0625")
    second = study_plan_service.generate(student, "0625")

    assert first.id != second.id
    current = study_plan_service.get_current(student, "0625")
    assert current is not None
    assert current.id == second.id


def test_regenerating_a_different_week_does_not_touch_last_weeks_plan(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _seed_user(pg_sessionmaker)
    _seed_weakness(pg_sessionmaker, student, topic="1 Motion", lost_marks=5)

    last_week_service = StudyPlanService(pg_sessionmaker, now=lambda: _LAST_WEEK)
    this_week_service = StudyPlanService(pg_sessionmaker, now=lambda: _THIS_WEEK)

    last_week_plan = last_week_service.generate(student, "0625")
    this_week_plan = this_week_service.generate(student, "0625")

    assert last_week_plan.id != this_week_plan.id

    # Last week's plan is still readable, unsuperseded, exactly as generated.
    still_last_week = last_week_service.get_current(student, "0625")
    assert still_last_week is not None
    assert still_last_week.id == last_week_plan.id

    still_this_week = this_week_service.get_current(student, "0625")
    assert still_this_week is not None
    assert still_this_week.id == this_week_plan.id


def test_get_current_is_none_before_any_generation(
    pg_sessionmaker: sessionmaker[Session], study_plan_service: StudyPlanService
) -> None:
    student = _seed_user(pg_sessionmaker)
    assert study_plan_service.get_current(student, "0625") is None


# ---------------------------------------------------------------------------
# Per-session completion.
# ---------------------------------------------------------------------------


def test_complete_session_is_idempotent(
    pg_sessionmaker: sessionmaker[Session], study_plan_service: StudyPlanService
) -> None:
    student = _seed_user(pg_sessionmaker)
    _seed_weakness(pg_sessionmaker, student, topic="1 Motion", lost_marks=5)
    plan = study_plan_service.generate(student, "0625")
    session_id = plan.sessions[0].id
    assert plan.sessions[0].completed_at is None

    first = study_plan_service.complete_session(student, session_id, now=_THIS_WEEK)
    assert first.completed_at == _THIS_WEEK

    later = _THIS_WEEK + timedelta(hours=1)
    second = study_plan_service.complete_session(student, session_id, now=later)
    assert second.completed_at == _THIS_WEEK  # unchanged, not moved forward


def test_complete_session_unknown_id_is_not_found(
    pg_sessionmaker: sessionmaker[Session], study_plan_service: StudyPlanService
) -> None:
    student = _seed_user(pg_sessionmaker)
    with pytest.raises(StudyPlanNotFoundError):
        study_plan_service.complete_session(student, uuid.uuid4())


def test_complete_session_is_owner_scoped(
    pg_sessionmaker: sessionmaker[Session], study_plan_service: StudyPlanService
) -> None:
    owner = _seed_user(pg_sessionmaker)
    other = _seed_user(pg_sessionmaker)
    _seed_weakness(pg_sessionmaker, owner, topic="1 Motion", lost_marks=5)
    plan = study_plan_service.generate(owner, "0625")
    session_id = plan.sessions[0].id

    with pytest.raises(StudyPlanOwnershipError):
        study_plan_service.complete_session(other, session_id)

    # Inverse: the actual owner succeeds.
    result = study_plan_service.complete_session(owner, session_id)
    assert result.completed_at is not None
