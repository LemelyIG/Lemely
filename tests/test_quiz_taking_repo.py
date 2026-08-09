"""Postgres-integration tests for the student quiz-taking service (P3.5 chunk E).

Mirrors ``test_quiz_repo.py``'s throwaway-database fixture, skipping cleanly
when no local Postgres is reachable. Covers, per the chunk-E brief:

* Tenancy: a student not enrolled in the assigned class cannot open, save to,
  or submit the assignment (403); an assignment id that exists nowhere is a
  404.
* The answer-leak guard: the take payload's dataclasses carry no
  ``model_answer``/``mark_scheme_points``/``mcq_answer`` field at all.
* Lazy submission creation: no ``quiz_submissions`` row exists until first
  open; a second open does not create a second row or reset ``started_at``.
* Open/overdue semantics driven entirely through the injected clock.
* Auto-save upsert (one row per ref) and its rejection once submitted/closed.
* Submit sets status/timestamp, leaves ``attempt_id`` NULL, and rejects a
  second submit.
"""

from __future__ import annotations

import dataclasses
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.db.base import Base
from lemely.db.class_repo import ClassService
from lemely.db.models import User
from lemely.db.models.enums import (
    QuestionDifficulty,
    QuestionSource,
    QuizKind,
    QuizStatus,
    QuizSubmissionStatus,
    Role,
)
from lemely.db.models.quizzes import QuestionBank, Quiz, QuizAssignment, QuizSubmission
from lemely.db.question_bank_repo import QuestionBankService
from lemely.db.quiz_repo import QuizService
from lemely.db.quiz_taking_repo import (
    QuizTakeQuestionRow,
    QuizTakingNotFoundError,
    QuizTakingOwnershipError,
    QuizTakingService,
    QuizTakingValidationError,
)
from lemely.runtime.config import DatabaseSettings

if TYPE_CHECKING:
    from collections.abc import Iterator


# ── Fixture: throwaway Postgres database ────────────────────────────────


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
def bank_service(pg_sessionmaker: sessionmaker[Session]) -> QuestionBankService:
    return QuestionBankService(pg_sessionmaker)


@pytest.fixture
def quiz_service(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    bank_service: QuestionBankService,
) -> QuizService:
    return QuizService(pg_sessionmaker, class_service, bank_service)


class _Clock:
    """A settable clock: ``now()`` returns whatever ``.value`` currently holds."""

    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


@pytest.fixture
def clock() -> _Clock:
    return _Clock(datetime(2026, 1, 1, tzinfo=UTC))


@pytest.fixture
def taking_service(
    pg_sessionmaker: sessionmaker[Session], class_service: ClassService, clock: _Clock
) -> QuizTakingService:
    return QuizTakingService(pg_sessionmaker, class_service, now=clock)


# ── Seed helpers ─────────────────────────────────────────────────────────


def _seed_user(
    sm: sessionmaker[Session], role: Role, *, display_name: str | None = None
) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role, display_name=display_name))
    return uid


def _seed_bank_row(sm: sessionmaker[Session], *, subject_code: str) -> uuid.UUID:
    from lemely.db.models.enums import DifficultySource, ExamBoard

    row_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            QuestionBank(
                id=row_id,
                board=ExamBoard.caie,
                subject_code=subject_code,
                source=QuestionSource.generated,
                difficulty=QuestionDifficulty.standard,
                difficulty_source=DifficultySource.declared_by_generator,
                question_type="explanation",
                prompt="Explain osmosis.",
                total_marks=3,
            )
        )
    return row_id


def _assigned_quiz(
    quiz_service: QuizService,
    class_service: ClassService,
    sm: sessionmaker[Session],
    *,
    subject_code: str = "0625",
    due_at: datetime | None = None,
    closes_at: datetime | None = None,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Build a teacher, an assigned quiz with one question, and an empty class.

    Returns ``(teacher_id, class_id, assignment_id)``.
    """
    teacher = _seed_user(sm, Role.teacher, display_name="Ms Rivera")
    _seed_bank_row(sm, subject_code=subject_code)
    created = quiz_service.create_quiz(teacher, subject_code, "Recap quiz")
    quiz_service.patch_draft(
        teacher, created.quiz_id, pool_source=QuestionSource.generated, requested_count=1
    )
    quiz_service.generate_questions(teacher, created.quiz_id)
    cls = class_service.create_class(teacher, "9A")
    assignment = quiz_service.create_assignment(
        teacher, Role.teacher, created.quiz_id, cls.class_id, due_at=due_at, closes_at=closes_at
    )
    return teacher, cls.class_id, assignment.assignment_id


def _enroll(
    class_service: ClassService, sm: sessionmaker[Session], class_id: uuid.UUID
) -> uuid.UUID:
    student = _seed_user(sm, Role.student, display_name="Amira")
    with sm.begin() as session:
        from lemely.db.models import ClassEnrollment

        session.add(ClassEnrollment(class_id=class_id, student_id=student))
    return student


def _student_owned_quiz(
    sm: sessionmaker[Session], student_id: uuid.UUID, kind: QuizKind, *, subject_code: str = "0625"
) -> tuple[uuid.UUID, uuid.UUID]:
    """A student-owned, self-assigned quiz of any :class:`QuizKind` (P4.5).

    Built by hand rather than through :class:`~lemely.db.practice_repo.PracticeService`
    / :class:`~lemely.db.placement_repo.PlacementService` so this module can
    exercise every ``kind`` — including ``placement``, which those services'
    own tests already cover elsewhere — without importing either service.
    Returns ``(quiz_id, assignment_id)``.
    """
    quiz_id = uuid.uuid4()
    assignment_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            Quiz(
                id=quiz_id,
                teacher_id=None,
                student_id=student_id,
                kind=kind,
                subject_code=subject_code,
                title=f"{kind.value} set",
                status=QuizStatus.assigned,
            )
        )
        session.add(
            QuizAssignment(
                id=assignment_id,
                quiz_id=quiz_id,
                class_id=None,
                student_id=student_id,
                assigned_by=student_id,
            )
        )
    return quiz_id, assignment_id


# ---------------------------------------------------------------------------
# Answer-leak guard.
# ---------------------------------------------------------------------------


def test_take_question_row_has_no_marking_fields() -> None:
    """The dataclass itself cannot carry the three forbidden fields, by construction."""
    field_names = {f.name for f in dataclasses.fields(QuizTakeQuestionRow)}
    assert "model_answer" not in field_names
    assert "mark_scheme_points" not in field_names
    assert "mcq_answer" not in field_names


def test_get_take_never_returns_marking_material(
    quiz_service: QuizService,
    class_service: ClassService,
    taking_service: QuizTakingService,
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    teacher, class_id, assignment_id = _assigned_quiz(quiz_service, class_service, pg_sessionmaker)
    student = _enroll(class_service, pg_sessionmaker, class_id)

    detail = taking_service.get_take(student, assignment_id)
    assert len(detail.questions) == 1
    q = detail.questions[0]
    assert not hasattr(q, "model_answer")
    assert not hasattr(q, "mark_scheme_points")
    assert not hasattr(q, "mcq_answer")


# ---------------------------------------------------------------------------
# Lazy submission creation.
# ---------------------------------------------------------------------------


def test_get_take_lazily_creates_submission_on_first_open(
    quiz_service: QuizService,
    class_service: ClassService,
    taking_service: QuizTakingService,
    pg_sessionmaker: sessionmaker[Session],
    clock: _Clock,
) -> None:
    teacher, class_id, assignment_id = _assigned_quiz(quiz_service, class_service, pg_sessionmaker)
    student = _enroll(class_service, pg_sessionmaker, class_id)

    with pg_sessionmaker() as session:
        rows = session.scalars(
            select(QuizSubmission).where(QuizSubmission.assignment_id == assignment_id)
        ).all()
        assert rows == []

    detail = taking_service.get_take(student, assignment_id)
    assert detail.header.submission_status == QuizSubmissionStatus.in_progress

    with pg_sessionmaker() as session:
        rows = session.scalars(
            select(QuizSubmission).where(QuizSubmission.assignment_id == assignment_id)
        ).all()
        assert len(rows) == 1
        assert rows[0].started_at == clock.value


def test_get_take_second_open_does_not_duplicate_or_reset_started_at(
    quiz_service: QuizService,
    class_service: ClassService,
    taking_service: QuizTakingService,
    pg_sessionmaker: sessionmaker[Session],
    clock: _Clock,
) -> None:
    teacher, class_id, assignment_id = _assigned_quiz(quiz_service, class_service, pg_sessionmaker)
    student = _enroll(class_service, pg_sessionmaker, class_id)

    taking_service.get_take(student, assignment_id)
    clock.value = clock.value + timedelta(hours=1)
    taking_service.get_take(student, assignment_id)

    with pg_sessionmaker() as session:
        rows = session.scalars(
            select(QuizSubmission).where(QuizSubmission.assignment_id == assignment_id)
        ).all()
        assert len(rows) == 1
        assert rows[0].started_at == clock.value - timedelta(hours=1)


def test_get_take_closed_quiz_does_not_create_submission(
    quiz_service: QuizService,
    class_service: ClassService,
    pg_sessionmaker: sessionmaker[Session],
    clock: _Clock,
) -> None:
    teacher, class_id, assignment_id = _assigned_quiz(
        quiz_service, class_service, pg_sessionmaker, closes_at=clock.value - timedelta(hours=1)
    )
    student = _enroll(class_service, pg_sessionmaker, class_id)
    service = QuizTakingService(pg_sessionmaker, class_service, now=clock)

    detail = service.get_take(student, assignment_id)
    assert detail.header.is_open is False
    assert detail.header.submission_status == QuizSubmissionStatus.not_started

    with pg_sessionmaker() as session:
        rows = session.scalars(
            select(QuizSubmission).where(QuizSubmission.assignment_id == assignment_id)
        ).all()
        assert rows == []


# ---------------------------------------------------------------------------
# Open/overdue matrix.
# ---------------------------------------------------------------------------


def test_open_and_not_overdue_when_no_dates_set(
    quiz_service: QuizService,
    class_service: ClassService,
    taking_service: QuizTakingService,
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    teacher, class_id, assignment_id = _assigned_quiz(quiz_service, class_service, pg_sessionmaker)
    student = _enroll(class_service, pg_sessionmaker, class_id)
    detail = taking_service.get_take(student, assignment_id)
    assert detail.header.is_open is True
    assert detail.header.is_overdue is False


def test_overdue_but_still_open_past_due_before_close(
    quiz_service: QuizService,
    class_service: ClassService,
    pg_sessionmaker: sessionmaker[Session],
    clock: _Clock,
) -> None:
    teacher, class_id, assignment_id = _assigned_quiz(
        quiz_service,
        class_service,
        pg_sessionmaker,
        due_at=clock.value - timedelta(hours=1),
        closes_at=clock.value + timedelta(days=1),
    )
    student = _enroll(class_service, pg_sessionmaker, class_id)
    service = QuizTakingService(pg_sessionmaker, class_service, now=clock)

    detail = service.get_take(student, assignment_id)
    assert detail.header.is_open is True
    assert detail.header.is_overdue is True


def test_closed_after_closes_at_and_never_overdue(
    quiz_service: QuizService,
    class_service: ClassService,
    pg_sessionmaker: sessionmaker[Session],
    clock: _Clock,
) -> None:
    teacher, class_id, assignment_id = _assigned_quiz(
        quiz_service,
        class_service,
        pg_sessionmaker,
        due_at=clock.value - timedelta(days=2),
        closes_at=clock.value - timedelta(hours=1),
    )
    student = _enroll(class_service, pg_sessionmaker, class_id)
    service = QuizTakingService(pg_sessionmaker, class_service, now=clock)

    detail = service.get_take(student, assignment_id)
    assert detail.header.is_open is False
    # Overdue is meaningless once closed — the flag must not also fire.
    assert detail.header.is_overdue is False


def test_closed_when_quiz_status_is_closed_even_with_no_closes_at(
    quiz_service: QuizService,
    class_service: ClassService,
    pg_sessionmaker: sessionmaker[Session],
    clock: _Clock,
) -> None:
    teacher, class_id, assignment_id = _assigned_quiz(quiz_service, class_service, pg_sessionmaker)
    quiz = quiz_service.list_quizzes(teacher)[0]
    quiz_service.set_status(teacher, quiz.quiz_id, QuizStatus.closed)
    student = _enroll(class_service, pg_sessionmaker, class_id)
    service = QuizTakingService(pg_sessionmaker, class_service, now=clock)

    detail = service.get_take(student, assignment_id)
    assert detail.header.is_open is False


# ---------------------------------------------------------------------------
# Discovery listing.
# ---------------------------------------------------------------------------


def test_list_assigned_excludes_draft_and_archived_quizzes(
    quiz_service: QuizService,
    class_service: ClassService,
    taking_service: QuizTakingService,
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    teacher, class_id, assignment_id = _assigned_quiz(quiz_service, class_service, pg_sessionmaker)
    student = _enroll(class_service, pg_sessionmaker, class_id)

    rows = taking_service.list_assigned(student)
    assert len(rows) == 1
    assert rows[0].assignment_id == assignment_id
    assert rows[0].teacher_name == "Ms Rivera"
    assert rows[0].question_count == 1


def test_list_assigned_only_for_enrolled_classes(
    quiz_service: QuizService,
    class_service: ClassService,
    taking_service: QuizTakingService,
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _assigned_quiz(quiz_service, class_service, pg_sessionmaker)
    outsider = _seed_user(pg_sessionmaker, Role.student)

    rows = taking_service.list_assigned(outsider)
    assert rows == []


# ---------------------------------------------------------------------------
# Discovery listing: the student-owned branch P4.5 adds (D4.6 §3's deferred site).
# ---------------------------------------------------------------------------


def test_list_assigned_includes_the_owners_own_practice_set(
    taking_service: QuizTakingService, pg_sessionmaker: sessionmaker[Session]
) -> None:
    student = _seed_user(pg_sessionmaker, Role.student)
    _quiz_id, assignment_id = _student_owned_quiz(pg_sessionmaker, student, QuizKind.practice)

    rows = taking_service.list_assigned(student)

    assert len(rows) == 1
    assert rows[0].assignment_id == assignment_id
    assert rows[0].class_name is None
    assert rows[0].teacher_name is None


def test_list_assigned_excludes_another_students_practice_set(
    taking_service: QuizTakingService, pg_sessionmaker: sessionmaker[Session]
) -> None:
    owner = _seed_user(pg_sessionmaker, Role.student)
    other = _seed_user(pg_sessionmaker, Role.student)
    _student_owned_quiz(pg_sessionmaker, owner, QuizKind.practice)

    assert taking_service.list_assigned(other) == []


def test_list_assigned_includes_a_study_plan_set(
    taking_service: QuizTakingService, pg_sessionmaker: sessionmaker[Session]
) -> None:
    student = _seed_user(pg_sessionmaker, Role.student)
    _quiz_id, assignment_id = _student_owned_quiz(pg_sessionmaker, student, QuizKind.study_plan)

    rows = taking_service.list_assigned(student)

    assert [r.assignment_id for r in rows] == [assignment_id]


def test_list_assigned_still_excludes_a_placement_set_alongside_a_practice_set(
    taking_service: QuizTakingService, pg_sessionmaker: sessionmaker[Session]
) -> None:
    """The allowlist is positive (D4.6 §3), pinned so it would fail under ``kind != 'teacher'``.

    A student who owns both a placement quiz and a practice quiz must see
    only the practice one. Under a negative-polarity implementation
    (``kind != QuizKind.teacher``) the placement row would also satisfy the
    predicate and leak into this list — this test fails exactly that way if
    someone "simplifies" the allowlist later.
    """
    student = _seed_user(pg_sessionmaker, Role.student)
    _student_owned_quiz(pg_sessionmaker, student, QuizKind.placement)
    _practice_quiz_id, practice_assignment_id = _student_owned_quiz(
        pg_sessionmaker, student, QuizKind.practice
    )

    rows = taking_service.list_assigned(student)

    assert [r.assignment_id for r in rows] == [practice_assignment_id]


def test_list_assigned_merges_class_and_student_owned_rows(
    quiz_service: QuizService,
    class_service: ClassService,
    taking_service: QuizTakingService,
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    teacher, class_id, class_assignment_id = _assigned_quiz(
        quiz_service, class_service, pg_sessionmaker
    )
    student = _enroll(class_service, pg_sessionmaker, class_id)
    _quiz_id, practice_assignment_id = _student_owned_quiz(
        pg_sessionmaker, student, QuizKind.practice
    )

    rows = taking_service.list_assigned(student)

    assert {r.assignment_id for r in rows} == {class_assignment_id, practice_assignment_id}


# ---------------------------------------------------------------------------
# Tenancy: not enrolled / unknown assignment.
# ---------------------------------------------------------------------------


def test_get_take_not_enrolled_is_ownership_error(
    quiz_service: QuizService,
    class_service: ClassService,
    taking_service: QuizTakingService,
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    teacher, class_id, assignment_id = _assigned_quiz(quiz_service, class_service, pg_sessionmaker)
    outsider = _seed_user(pg_sessionmaker, Role.student)

    with pytest.raises(QuizTakingOwnershipError):
        taking_service.get_take(outsider, assignment_id)


def test_get_take_unknown_assignment_is_not_found(
    taking_service: QuizTakingService, pg_sessionmaker: sessionmaker[Session]
) -> None:
    student = _seed_user(pg_sessionmaker, Role.student)
    with pytest.raises(QuizTakingNotFoundError):
        taking_service.get_take(student, uuid.uuid4())


def test_save_answer_not_enrolled_is_ownership_error(
    quiz_service: QuizService,
    class_service: ClassService,
    taking_service: QuizTakingService,
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    teacher, class_id, assignment_id = _assigned_quiz(quiz_service, class_service, pg_sessionmaker)
    outsider = _seed_user(pg_sessionmaker, Role.student)

    with pytest.raises(QuizTakingOwnershipError):
        taking_service.save_answer(outsider, assignment_id, "q1", answer_text="x")


def test_submit_not_enrolled_is_ownership_error(
    quiz_service: QuizService,
    class_service: ClassService,
    taking_service: QuizTakingService,
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    teacher, class_id, assignment_id = _assigned_quiz(quiz_service, class_service, pg_sessionmaker)
    outsider = _seed_user(pg_sessionmaker, Role.student)

    with pytest.raises(QuizTakingOwnershipError):
        taking_service.submit(outsider, assignment_id)


# ---------------------------------------------------------------------------
# Auto-save upsert.
# ---------------------------------------------------------------------------


def test_save_answer_upserts_a_single_row(
    quiz_service: QuizService,
    class_service: ClassService,
    taking_service: QuizTakingService,
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    teacher, class_id, assignment_id = _assigned_quiz(quiz_service, class_service, pg_sessionmaker)
    student = _enroll(class_service, pg_sessionmaker, class_id)
    ref = taking_service.get_take(student, assignment_id).questions[0].question_ref

    first = taking_service.save_answer(student, assignment_id, ref, answer_text="Draft one")
    assert first.answer_text == "Draft one"
    second = taking_service.save_answer(student, assignment_id, ref, answer_text="Final answer")
    assert second.answer_text == "Final answer"

    detail = taking_service.get_take(student, assignment_id)
    assert detail.questions[0].answer_text == "Final answer"


def test_save_answer_creates_submission_without_prior_get(
    quiz_service: QuizService,
    class_service: ClassService,
    taking_service: QuizTakingService,
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    teacher, class_id, assignment_id = _assigned_quiz(quiz_service, class_service, pg_sessionmaker)
    student = _enroll(class_service, pg_sessionmaker, class_id)

    with pg_sessionmaker() as session:
        assert (
            session.scalars(
                select(QuizSubmission).where(QuizSubmission.assignment_id == assignment_id)
            ).first()
            is None
        )

    taking_service.save_answer(student, assignment_id, "q1", answer_text="No GET first")

    with pg_sessionmaker() as session:
        assert (
            session.scalars(
                select(QuizSubmission).where(QuizSubmission.assignment_id == assignment_id)
            ).first()
            is not None
        )


def test_save_answer_rejects_unknown_ref(
    quiz_service: QuizService,
    class_service: ClassService,
    taking_service: QuizTakingService,
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    teacher, class_id, assignment_id = _assigned_quiz(quiz_service, class_service, pg_sessionmaker)
    student = _enroll(class_service, pg_sessionmaker, class_id)

    with pytest.raises(QuizTakingValidationError):
        taking_service.save_answer(student, assignment_id, "q99", answer_text="nope")


def test_save_answer_rejects_when_closed(
    quiz_service: QuizService,
    class_service: ClassService,
    pg_sessionmaker: sessionmaker[Session],
    clock: _Clock,
) -> None:
    teacher, class_id, assignment_id = _assigned_quiz(
        quiz_service, class_service, pg_sessionmaker, closes_at=clock.value - timedelta(hours=1)
    )
    student = _enroll(class_service, pg_sessionmaker, class_id)
    service = QuizTakingService(pg_sessionmaker, class_service, now=clock)

    with pytest.raises(QuizTakingValidationError):
        service.save_answer(student, assignment_id, "q1", answer_text="too late")


def test_save_answer_rejects_when_already_submitted(
    quiz_service: QuizService,
    class_service: ClassService,
    taking_service: QuizTakingService,
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    teacher, class_id, assignment_id = _assigned_quiz(quiz_service, class_service, pg_sessionmaker)
    student = _enroll(class_service, pg_sessionmaker, class_id)
    ref = taking_service.get_take(student, assignment_id).questions[0].question_ref
    taking_service.save_answer(student, assignment_id, ref, answer_text="answer")
    taking_service.submit(student, assignment_id)

    with pytest.raises(QuizTakingValidationError):
        taking_service.save_answer(student, assignment_id, ref, answer_text="edit after submit")


# ---------------------------------------------------------------------------
# Submit.
# ---------------------------------------------------------------------------


def test_submit_sets_status_and_timestamp_leaves_attempt_id_null(
    quiz_service: QuizService,
    class_service: ClassService,
    taking_service: QuizTakingService,
    pg_sessionmaker: sessionmaker[Session],
    clock: _Clock,
) -> None:
    teacher, class_id, assignment_id = _assigned_quiz(quiz_service, class_service, pg_sessionmaker)
    student = _enroll(class_service, pg_sessionmaker, class_id)
    ref = taking_service.get_take(student, assignment_id).questions[0].question_ref
    taking_service.save_answer(student, assignment_id, ref, answer_text="Complete")

    result = taking_service.submit(student, assignment_id)
    assert result.submission_status == QuizSubmissionStatus.submitted
    assert result.answered_count == 1
    assert result.unanswered_count == 0

    with pg_sessionmaker() as session:
        row = session.scalars(
            select(QuizSubmission).where(QuizSubmission.assignment_id == assignment_id)
        ).first()
        assert row is not None
        assert row.status == QuizSubmissionStatus.submitted
        assert row.submitted_at == clock.value
        assert row.attempt_id is None


def test_submit_rejects_second_submit(
    quiz_service: QuizService,
    class_service: ClassService,
    taking_service: QuizTakingService,
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    teacher, class_id, assignment_id = _assigned_quiz(quiz_service, class_service, pg_sessionmaker)
    student = _enroll(class_service, pg_sessionmaker, class_id)
    taking_service.get_take(student, assignment_id)
    taking_service.submit(student, assignment_id)

    with pytest.raises(QuizTakingValidationError):
        taking_service.submit(student, assignment_id)


def test_submit_without_prior_submission_is_rejected(
    quiz_service: QuizService,
    class_service: ClassService,
    taking_service: QuizTakingService,
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    teacher, class_id, assignment_id = _assigned_quiz(quiz_service, class_service, pg_sessionmaker)
    student = _enroll(class_service, pg_sessionmaker, class_id)

    with pytest.raises(QuizTakingValidationError):
        taking_service.submit(student, assignment_id)


def test_submit_overdue_but_not_closed_is_still_accepted(
    quiz_service: QuizService,
    class_service: ClassService,
    pg_sessionmaker: sessionmaker[Session],
    clock: _Clock,
) -> None:
    teacher, class_id, assignment_id = _assigned_quiz(
        quiz_service,
        class_service,
        pg_sessionmaker,
        due_at=clock.value - timedelta(hours=1),
        closes_at=clock.value + timedelta(days=1),
    )
    student = _enroll(class_service, pg_sessionmaker, class_id)
    service = QuizTakingService(pg_sessionmaker, class_service, now=clock)
    service.get_take(student, assignment_id)

    result = service.submit(student, assignment_id)
    assert result.submission_status == QuizSubmissionStatus.submitted


def test_submit_rejected_once_closed(
    quiz_service: QuizService,
    class_service: ClassService,
    pg_sessionmaker: sessionmaker[Session],
    clock: _Clock,
) -> None:
    teacher, class_id, assignment_id = _assigned_quiz(
        quiz_service, class_service, pg_sessionmaker, closes_at=clock.value + timedelta(hours=1)
    )
    student = _enroll(class_service, pg_sessionmaker, class_id)
    service = QuizTakingService(pg_sessionmaker, class_service, now=clock)
    service.get_take(student, assignment_id)

    # Time passes; the assignment closes before the student submits.
    clock.value = clock.value + timedelta(hours=2)
    with pytest.raises(QuizTakingValidationError):
        service.submit(student, assignment_id)
