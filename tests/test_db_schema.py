"""Schema-level tests for the SQLAlchemy ORM models and the core migration.

Two layers:

* **Metadata assertions** run everywhere with no database. They guard against
  regressions such as an unresolved ``Mapped[...]`` annotation (which silently
  breaks every model at mapper-configuration time) and confirm the naming
  convention that the additive-migration guarantee depends on.
* **Integration tests** create a throwaway Postgres database, run
  ``create_all``, and exercise enums, server defaults, and foreign keys against
  a real server. They skip cleanly when no local Postgres is reachable (CI
  without a DB service, or the local Supabase stack being down).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, get_args

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from lemely.core.difficulty import Band
from lemely.core.generation import GeneratedQuestion
from lemely.db.base import Base
from lemely.db.models import import_all_models
from lemely.db.models.enums import NotificationType, QuestionDifficulty
from lemely.runtime.config import DatabaseSettings

if TYPE_CHECKING:
    from collections.abc import Iterator

# Populate Base.metadata with every model before any assertion runs.
import_all_models()

EXPECTED_TABLES = {
    "users",
    "parent_child_links",
    "devices",
    "schools",
    "school_memberships",
    "seats",
    "classes",
    "class_enrollments",
    "subjects",
    "papers",
    "mark_schemes",
    "plan_tiers",
    "subscriptions",
    "uploads",
    "attempts",
    "question_results",
    "weakness_records",
    "review_queue",
    "announcements",
    "notifications",
    "at_risk_acknowledgements",
    "notification_preferences",
    "xp_events",
    "streaks",
    "question_bank",
    "quizzes",
    "quiz_questions",
    "quiz_assignments",
    "quiz_submissions",
    "quiz_answers",
    "student_profiles",
    "student_subject_enrolments",
    "student_enrolment_papers",
    "student_confidence_ratings",
    "flashcard_decks",
    "flashcards",
    "flashcard_reviews",
    "study_plans",
    "study_plan_sessions",
    "friendships",
    "announcement_reads",
    "exam_dates",
}


# ---------------------------------------------------------------------------
# Metadata layer — no database required
# ---------------------------------------------------------------------------


def test_all_expected_tables_registered() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_registry_configures() -> None:
    # Fails loudly if any Mapped[...] annotation cannot be resolved at runtime
    # (e.g. a type imported only under TYPE_CHECKING).
    Base.registry.configure()


def test_naming_convention_applied() -> None:
    users = Base.metadata.tables["users"]
    assert users.primary_key.name == "pk_users"
    fk_names = [
        fk.name for table in Base.metadata.tables.values() for fk in table.foreign_key_constraints
    ]
    assert fk_names, "expected foreign keys across the schema"
    assert all(str(name).startswith("fk_") for name in fk_names)


def test_every_model_has_timestamps() -> None:
    for name, table in Base.metadata.tables.items():
        assert "created_at" in table.c, f"{name} missing created_at"
        assert "updated_at" in table.c, f"{name} missing updated_at"


def test_question_difficulty_enum_matches_band_vocabulary() -> None:
    """Pin the ``questiondifficulty`` Postgres enum against ``Band`` and
    ``GeneratedQuestion.difficulty``'s ``Literal`` (P3.5, ``docs/quiz-model.md``
    §1.1).

    Three independent representations of the same three-value vocabulary
    exist in this codebase: ``lemely.core.difficulty.Band`` (a ``Literal``),
    ``GeneratedQuestion.difficulty`` (a Pydantic field using that same
    ``Literal``), and ``lemely.db.models.enums.QuestionDifficulty`` (a native
    Postgres enum). A fourth difficulty level, or a different spelling,
    invented on any one side and not the others would silently break the
    quiz builder's ability to draw generated questions into a difficulty
    band. This mirrors ``tests/test_difficulty.py``'s
    ``test_band_vocabulary_matches_generated_question_difficulty_literal``.
    """
    band_values = set(get_args(Band))
    literal_values = set(get_args(GeneratedQuestion.model_fields["difficulty"].annotation))
    enum_values = {member.value for member in QuestionDifficulty}
    assert band_values == literal_values == enum_values == {"foundation", "standard", "challenge"}


def test_attempt_origin_enum_matches_paper_origin_vocabulary() -> None:
    """Pin the ``attemptorigin`` Postgres enum against ``PaperOrigin`` (§5).

    ``DbHistoryStore`` converts between the two by value in both directions
    (``AttemptOrigin(record.origin)`` on write, ``attempt.origin.value`` on
    read), and the read side is a ``cast`` — so mypy cannot catch a drift here.
    A member added to one side only would raise ``ValueError`` on write, or
    silently produce a ``PaperRecord`` whose ``origin`` is outside its own
    ``Literal`` on read. This test is what makes that cast safe.
    """
    from lemely.core.history import PaperOrigin
    from lemely.db.models.enums import AttemptOrigin

    assert {member.value for member in AttemptOrigin} == set(get_args(PaperOrigin))


def test_notification_type_enum_matches_preference_columns() -> None:
    """Pin ``NotificationType`` against ``notification_preferences``' boolean columns.

    P3.6 chunk B (G-12): one explicit ``NOT NULL BOOLEAN`` column per
    :class:`NotificationType` member, deliberately not a JSONB blob or a
    row-per-type table — this is what makes that guarantee real rather than
    aspirational. Mirrors P3.5 chunk A's
    ``test_question_difficulty_enum_matches_band_vocabulary`` three-way
    pattern (here two-way: enum vs. columns). A member added to one side
    only would either 500 on write (column missing) or leave a column no
    enum value ever populates — this test is what makes that impossible to
    ship unnoticed.
    """
    table = Base.metadata.tables["notification_preferences"]
    non_toggle_columns = {
        "user_id",
        "quiet_hours_start",
        "quiet_hours_end",
        "created_at",
        "updated_at",
    }
    toggle_columns = {c.name for c in table.columns} - non_toggle_columns
    assert toggle_columns == {member.value for member in NotificationType}


def test_every_enum_column_binds_its_value_not_its_member_name() -> None:
    """Every ``sa.Enum`` column must send ``.value`` to Postgres, not ``.name``.

    This is the invariant behind D3.13, and it is worth a standing test
    because the bug it prevents is invisible to every other gate we run.

    SQLAlchemy's default enum binding converts a Python enum member to its DB
    string using ``.name``, **not** ``.value``. Every enum mirrored in
    ``lemely/db/models/enums.py`` is declared with lowercase member names
    equal to their values (``low_confidence = "low_confidence"``), so the
    default binding happens to be correct — a load-bearing convention nobody
    had written down. ``AtRiskReason`` (``lemely/core/at_risk.py``) is reused
    straight from ``lemely.core`` instead of being mirrored under that
    convention and uses ordinary ``SCREAMING_SNAKE_CASE`` members, so
    ``at_risk_acknowledgements.reason`` bound ``"DECLINING_TREND"`` while
    migration 0006's real Postgres type only accepts ``"declining_trend"``.
    Result: every acknowledge/unacknowledge call 500'd on a migrated stack
    while all twelve gates stayed green.

    Neither ``pytest`` nor ``alembic check`` could see it. ``alembic check``'s
    comparator does not diff enum labels, and a ``create_all()``-based test
    fixture derives the type's DDL from the same buggy declaration — so the
    test database accepted the wrong string and the suite was
    self-consistently wrong. Only a real E2E write against the migrated
    schema surfaced it.

    So the rule is checked structurally instead: a column is safe if its enum
    already satisfies ``name == value``, or if it explicitly passes
    ``values_callable``. Anything else is the D3.13 bug waiting to happen.
    """
    import_all_models()
    unsafe = [
        f"{table.name}.{column.name} ({column.type.enum_class.__name__})"
        for table in Base.metadata.tables.values()
        for column in table.columns
        if isinstance(column.type, sa.Enum)
        and column.type.enum_class is not None
        and column.type.values_callable is None
        and not all(member.name == member.value for member in column.type.enum_class)
    ]
    assert unsafe == [], (
        "These enum columns bind the member NAME to Postgres but their enum's "
        "name differs from its value, so every write fails against the "
        "migrated schema (D3.13). Give each one "
        "values_callable=lambda enum_cls: [e.value for e in enum_cls]: " + ", ".join(unsafe)
    )


# ---------------------------------------------------------------------------
# Integration layer — real Postgres, skipped when unreachable
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


@pytest.fixture(scope="module")
def pg_engine() -> Iterator[sa.Engine]:
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
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)'))
        admin.dispose()


def test_server_defaults_and_enums(pg_engine: sa.Engine) -> None:
    from lemely.db.models import PlanTier, Subscription, User
    from lemely.db.models.enums import Role, SubscriptionStatus

    uid = uuid.uuid4()
    with Session(pg_engine) as session:
        session.add(User(id=uid, email="student@example.com", role=Role.student))
        tier = PlanTier(code="free", name="Free")
        session.add(tier)
        session.flush()  # populate server-default id via RETURNING
        sub = Subscription(user_id=uid, plan_tier_id=tier.id)
        session.add(sub)
        session.commit()

        session.refresh(sub)
        user = session.get(User, uid)
        assert user is not None
        assert user.is_active is False  # server_default false
        assert user.locale == "en"  # server_default 'en'
        assert user.created_at is not None
        assert sub.status is SubscriptionStatus.inactive  # enum server_default
        assert tier.currency == "EGP"
        assert tier.max_devices == 3
        assert tier.features == {}


def test_unique_email_enforced(pg_engine: sa.Engine) -> None:
    from lemely.db.models import User
    from lemely.db.models.enums import Role

    with Session(pg_engine) as session:
        session.add(User(id=uuid.uuid4(), email="dup@example.com", role=Role.parent))
        session.commit()

    with Session(pg_engine) as session, pytest.raises(IntegrityError):
        session.add(User(id=uuid.uuid4(), email="dup@example.com", role=Role.teacher))
        session.commit()


def test_foreign_key_enforced(pg_engine: sa.Engine) -> None:
    from lemely.db.models import Subscription

    with Session(pg_engine) as session, pytest.raises(IntegrityError):
        session.add(Subscription(user_id=uuid.uuid4(), plan_tier_id=uuid.uuid4()))
        session.commit()


# ---------------------------------------------------------------------------
# P3.5 chunk A — quiz model (docs/quiz-model.md §1)
# ---------------------------------------------------------------------------


def test_attempt_origin_defaults_to_past_paper(pg_engine: sa.Engine) -> None:
    """Every existing/unspecified attempt is a past-paper attempt (§1.2).

    Chunk A adds ``attempts.origin`` additively with a server default so no
    backfill is needed; this proves the default actually reaches a row
    inserted without the column, not just that the column exists.
    """
    from datetime import UTC, datetime

    from lemely.db.models import Attempt, User
    from lemely.db.models.enums import AttemptOrigin, Role

    with Session(pg_engine) as session:
        user = User(id=uuid.uuid4(), email="origin-default@example.com", role=Role.student)
        session.add(user)
        session.flush()

        attempt = Attempt(
            user_id=user.id,
            awarded_marks=1,
            maximum_marks=1,
            percentage=100.0,
            recorded_at=datetime.now(UTC),
        )
        session.add(attempt)
        session.commit()

        session.refresh(attempt)
        assert attempt.origin is AttemptOrigin.past_paper


def test_quiz_model_round_trip(pg_engine: sa.Engine) -> None:
    """Insert one row per new P3.5 table and read every one back (§1.3-§1.8).

    ``alembic check`` clean proves the ORM models and the migration agree on
    column-level shape; it does not prove a row actually survives every FK,
    enum, and JSONB default end to end. This walks the full chain —
    question_bank -> quiz -> quiz_question -> quiz_assignment ->
    quiz_submission -> quiz_answer, with the submission's attempt_id pointing
    at a real quiz-origin Attempt — against the same schema the migration
    produced in the live-Postgres upgrade/downgrade/upgrade check.
    """
    from datetime import UTC, datetime

    from lemely.db.models import (
        Attempt,
        QuestionBank,
        Quiz,
        QuizAnswer,
        QuizAssignment,
        QuizQuestion,
        QuizSubmission,
        School,
        SchoolClass,
        User,
    )
    from lemely.db.models.enums import (
        AttemptOrigin,
        DifficultySource,
        QuestionDifficulty,
        QuestionSource,
        QuizQuestionStatus,
        QuizStatus,
        QuizSubmissionStatus,
        Role,
    )

    with Session(pg_engine) as session:
        teacher = User(id=uuid.uuid4(), email="teacher-qm@example.com", role=Role.teacher)
        student = User(id=uuid.uuid4(), email="student-qm@example.com", role=Role.student)
        session.add_all([teacher, student])
        session.flush()

        school = School(name="Quiz Model School")
        session.add(school)
        session.flush()

        school_class = SchoolClass(school_id=school.id, teacher_id=teacher.id, name="10A")
        session.add(school_class)
        session.flush()

        bank_question = QuestionBank(
            subject_code="0580",
            source=QuestionSource.past_paper,
            difficulty=QuestionDifficulty.standard,
            difficulty_source=DifficultySource.inferred_from_marks,
            question_type="short_answer",
            prompt="Solve for x: 2x + 3 = 7",
            total_marks=2,
        )
        session.add(bank_question)
        session.flush()
        session.refresh(bank_question)
        assert bank_question.is_active is True  # server_default true
        assert bank_question.mark_scheme_points == []  # server_default '[]'::jsonb
        assert bank_question.source_question_ids == []  # server_default '[]'::jsonb

        quiz = Quiz(teacher_id=teacher.id, subject_code="0580", title="Algebra recap")
        session.add(quiz)
        session.flush()

        quiz_question = QuizQuestion(
            quiz_id=quiz.id,
            question_bank_id=bank_question.id,
            question_ref="q1",
            position=1,
            difficulty=QuestionDifficulty.standard,
            question_type="short_answer",
            prompt="Solve for x: 2x + 3 = 7",
            total_marks=2,
        )
        session.add(quiz_question)
        session.flush()

        assignment = QuizAssignment(
            quiz_id=quiz.id, class_id=school_class.id, assigned_by=teacher.id
        )
        session.add(assignment)
        session.flush()

        attempt = Attempt(
            user_id=student.id,
            awarded_marks=2,
            maximum_marks=2,
            percentage=100.0,
            recorded_at=datetime.now(UTC),
            origin=AttemptOrigin.quiz,
        )
        session.add(attempt)
        session.flush()

        submission = QuizSubmission(
            assignment_id=assignment.id,
            student_id=student.id,
            status=QuizSubmissionStatus.marked,
            attempt_id=attempt.id,
        )
        session.add(submission)
        session.flush()

        answer = QuizAnswer(
            submission_id=submission.id,
            quiz_question_id=quiz_question.id,
            answer_text="x = 2",
            working_text="2x = 4",
        )
        session.add(answer)
        session.commit()

        session.refresh(quiz)
        session.refresh(quiz_question)
        session.refresh(assignment)
        session.refresh(submission)
        session.refresh(answer)

        assert quiz.status is QuizStatus.draft  # server_default
        assert quiz.builder_step == 1  # server_default
        assert quiz.included_topics == []  # server_default
        assert quiz_question.status is QuizQuestionStatus.included  # server_default
        assert quiz_question.question_bank_id == bank_question.id
        assert submission.attempt_id == attempt.id
        assert submission.status is QuizSubmissionStatus.marked
        assert answer.answer_text == "x = 2"
        assert answer.working_text == "2x = 4"


def test_question_bank_paper_question_unique_only_when_paper_set(pg_engine: sa.Engine) -> None:
    """``uq_question_bank_paper_question`` is a *partial* unique index (§1.3).

    Two rows sharing ``(paper_id, source_question_id)`` collide (the ingest
    idempotency this index exists for); two rows that both have
    ``paper_id IS NULL`` (generated/teacher-upload questions) must not,
    since the index's ``WHERE paper_id IS NOT NULL`` excludes them.
    """
    from lemely.db.models import Paper, QuestionBank, Subject
    from lemely.db.models.enums import (
        DifficultySource,
        QuestionDifficulty,
        QuestionSource,
        SessionMonth,
    )

    def _bank_row(paper_id: uuid.UUID | None, source_question_id: str | None) -> QuestionBank:
        return QuestionBank(
            subject_code="0580-uq",
            source=QuestionSource.past_paper,
            paper_id=paper_id,
            source_question_id=source_question_id,
            difficulty=QuestionDifficulty.standard,
            difficulty_source=DifficultySource.inferred_from_marks,
            question_type="short_answer",
            prompt="q",
            total_marks=1,
        )

    with Session(pg_engine) as session:
        subject = Subject(code="0580-uq", name="Mathematics")
        session.add(subject)
        session.flush()

        paper = Paper(
            subject_code=subject.code,
            session_month=SessionMonth.may_june,
            session_year=2024,
            paper_number=1,
            paper_variant=1,
        )
        session.add(paper)
        session.flush()
        paper_id = paper.id

        session.add(_bank_row(paper_id, "1a"))
        session.commit()

    with Session(pg_engine) as session, pytest.raises(IntegrityError):
        session.add(_bank_row(paper_id, "1a"))
        session.commit()

    # Two rows with paper_id NULL (generated/teacher-upload questions): the
    # partial index only fires when paper_id IS NOT NULL, so this must not
    # collide even with an identical source_question_id.
    with Session(pg_engine) as session:
        session.add(_bank_row(None, "1a"))
        session.add(_bank_row(None, "1a"))
        session.commit()


# ---------------------------------------------------------------------------
# P4.3 chunk A — student profiles / onboarding (D4.5)
# ---------------------------------------------------------------------------


def test_student_profile_round_trip(pg_engine: sa.Engine) -> None:
    """Insert one row per new P4.3 table and read every one back (D4.5).

    profile -> enrolment -> paper + confidence rating, proving the ORM
    models and the migration agree end to end (the same chain
    ``test_quiz_model_round_trip`` walks for P3.5 chunk A).
    """
    from lemely.db.models import (
        StudentConfidenceRating,
        StudentEnrolmentPaper,
        StudentProfile,
        StudentSubjectEnrolment,
        Subject,
        User,
    )
    from lemely.db.models.enums import QualificationLevel, Role, SessionMonth

    with Session(pg_engine) as session:
        student = User(id=uuid.uuid4(), email="onboarding@example.com", role=Role.student)
        session.add(student)
        subject = Subject(code="0625-sp", name="Physics")
        session.add(subject)
        session.flush()

        profile = StudentProfile(
            user_id=student.id,
            qualification_level=QualificationLevel.igcse,
            grade_level="Year 11",
            weekly_study_hours=10,
        )
        session.add(profile)
        session.flush()

        enrolment = StudentSubjectEnrolment(
            user_id=student.id,
            subject_code=subject.code,
            target_grade="A",
            session_month=SessionMonth.may_june,
            session_year=2027,
        )
        session.add(enrolment)
        session.flush()

        paper = StudentEnrolmentPaper(enrolment_id=enrolment.id, paper_number=2)
        rating = StudentConfidenceRating(
            enrolment_id=enrolment.id, topic="4.3 Electric circuits", rating=3
        )
        session.add_all([paper, rating])
        session.commit()

        session.refresh(profile)
        session.refresh(enrolment)
        session.refresh(paper)
        session.refresh(rating)
        assert profile.qualification_level is QualificationLevel.igcse
        assert profile.onboarding_completed_at is None
        assert enrolment.target_grade == "A"
        assert paper.paper_number == 2
        assert rating.rating == 3


def test_student_profile_weekly_study_hours_check_rejects_out_of_range(
    pg_engine: sa.Engine,
) -> None:
    from lemely.db.models import StudentProfile, User
    from lemely.db.models.enums import Role

    with Session(pg_engine) as session:
        student = User(id=uuid.uuid4(), email="hours-check@example.com", role=Role.student)
        session.add(student)
        session.flush()

        session.add(StudentProfile(user_id=student.id, weekly_study_hours=81))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        session.add(StudentProfile(user_id=student.id, weekly_study_hours=-1))
        with pytest.raises(IntegrityError):
            session.commit()


def test_student_confidence_rating_check_rejects_out_of_range(pg_engine: sa.Engine) -> None:
    from lemely.db.models import StudentSubjectEnrolment, Subject, User
    from lemely.db.models.enums import Role

    with Session(pg_engine) as session:
        student = User(id=uuid.uuid4(), email="rating-check@example.com", role=Role.student)
        session.add(student)
        subject = Subject(code="0625-rc", name="Physics")
        session.add(subject)
        session.flush()
        enrolment = StudentSubjectEnrolment(user_id=student.id, subject_code=subject.code)
        session.add(enrolment)
        session.commit()

        enrolment_id = enrolment.id

    from lemely.db.models import StudentConfidenceRating

    with Session(pg_engine) as session, pytest.raises(IntegrityError):
        session.add(StudentConfidenceRating(enrolment_id=enrolment_id, topic="4.1 Topic", rating=6))
        session.commit()

    with Session(pg_engine) as session, pytest.raises(IntegrityError):
        session.add(StudentConfidenceRating(enrolment_id=enrolment_id, topic="4.1 Topic", rating=0))
        session.commit()


def test_student_subject_enrolment_unique_per_user_and_subject(pg_engine: sa.Engine) -> None:
    from lemely.db.models import StudentSubjectEnrolment, Subject, User
    from lemely.db.models.enums import Role

    with Session(pg_engine) as session:
        student = User(id=uuid.uuid4(), email="uq-enrolment@example.com", role=Role.student)
        session.add(student)
        subject = Subject(code="0625-uqe", name="Physics")
        session.add(subject)
        session.flush()
        session.add(StudentSubjectEnrolment(user_id=student.id, subject_code=subject.code))
        session.commit()
        student_id, subject_code = student.id, subject.code

    with Session(pg_engine) as session, pytest.raises(IntegrityError):
        session.add(StudentSubjectEnrolment(user_id=student_id, subject_code=subject_code))
        session.commit()


def test_student_enrolment_paper_unique_per_enrolment_and_paper_number(
    pg_engine: sa.Engine,
) -> None:
    from lemely.db.models import StudentEnrolmentPaper, StudentSubjectEnrolment, Subject, User
    from lemely.db.models.enums import Role

    with Session(pg_engine) as session:
        student = User(id=uuid.uuid4(), email="uq-paper@example.com", role=Role.student)
        session.add(student)
        subject = Subject(code="0625-uqp", name="Physics")
        session.add(subject)
        session.flush()
        enrolment = StudentSubjectEnrolment(user_id=student.id, subject_code=subject.code)
        session.add(enrolment)
        session.commit()
        enrolment_id = enrolment.id
        session.add(StudentEnrolmentPaper(enrolment_id=enrolment_id, paper_number=2))
        session.commit()

    with Session(pg_engine) as session, pytest.raises(IntegrityError):
        session.add(StudentEnrolmentPaper(enrolment_id=enrolment_id, paper_number=2))
        session.commit()


def test_student_confidence_rating_unique_per_enrolment_and_topic(pg_engine: sa.Engine) -> None:
    from lemely.db.models import StudentConfidenceRating, StudentSubjectEnrolment, Subject, User
    from lemely.db.models.enums import Role

    with Session(pg_engine) as session:
        student = User(id=uuid.uuid4(), email="uq-rating@example.com", role=Role.student)
        session.add(student)
        subject = Subject(code="0625-uqr", name="Physics")
        session.add(subject)
        session.flush()
        enrolment = StudentSubjectEnrolment(user_id=student.id, subject_code=subject.code)
        session.add(enrolment)
        session.commit()
        enrolment_id = enrolment.id
        session.add(
            StudentConfidenceRating(
                enrolment_id=enrolment_id, topic="4.3 Electric circuits", rating=3
            )
        )
        session.commit()

    with Session(pg_engine) as session, pytest.raises(IntegrityError):
        session.add(
            StudentConfidenceRating(
                enrolment_id=enrolment_id, topic="4.3 Electric circuits", rating=4
            )
        )
        session.commit()
