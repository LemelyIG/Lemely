"""Postgres-integration tests for the quiz-builder service (P3.5 chunk D).

Mirrors ``test_review_repo.py``/``test_question_bank_repo.py``'s throwaway-
database fixture, skipping cleanly when no local Postgres is reachable.

Covers, per the chunk-D brief:

* Draft lifecycle: create -> PATCH partial fields -> resume; a half-filled
  draft round-trips.
* Status lifecycle: every forbidden transition rejected, including editing
  questions on a non-draft quiz.
* ``question_ref`` stability: remove a middle question, assert the others
  keep their refs and the removed row is retained with ``status='removed'``.
* Snapshot independence: materialize a quiz, then mutate/deactivate the bank
  row, assert the quiz's question text and difficulty are unchanged.
* Count/selection agreement for an identical filter set, including the
  shortfall case.
* Tenancy negatives: another teacher's quiz is not visible, not patchable,
  not status-transitionable, not question-editable.
* The honest-zero path: an empty bank yields ``matching: 0`` with a
  shortfall naming the short bands, not an error and not a fabricated
  number.
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
from lemely.db.class_repo import ClassNotFoundError, ClassOwnershipError, ClassService
from lemely.db.models import User
from lemely.db.models.enums import (
    DifficultySource,
    ExamBoard,
    QuestionDifficulty,
    QuestionSource,
    QuizQuestionStatus,
    QuizStatus,
    QuizSubmissionStatus,
    Role,
)
from lemely.db.models.quizzes import QuestionBank, QuizSubmission
from lemely.db.question_bank_repo import QuestionBankService
from lemely.db.quiz_repo import (
    QuizNotFoundError,
    QuizOwnershipError,
    QuizService,
    QuizValidationError,
)
from lemely.runtime.config import DatabaseSettings

if TYPE_CHECKING:
    from collections.abc import Iterator


# ── Fixture: throwaway Postgres database (mirrors test_question_bank_repo.py) ──


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


# ── Seed helpers ─────────────────────────────────────────────────────────


def _seed_teacher(sm: sessionmaker[Session]) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=Role.teacher))
    return uid


def _seed_bank_row(
    sm: sessionmaker[Session],
    *,
    subject_code: str,
    difficulty: QuestionDifficulty,
    owner_id: uuid.UUID | None = None,
    source: QuestionSource = QuestionSource.generated,
    difficulty_source: DifficultySource = DifficultySource.declared_by_generator,
    prompt: str = "A dummy prompt",
    total_marks: int = 2,
    topic: str | None = None,
    is_active: bool = True,
) -> uuid.UUID:
    row_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            QuestionBank(
                id=row_id,
                board=ExamBoard.caie,
                subject_code=subject_code,
                source=source,
                owner_id=owner_id,
                difficulty=difficulty,
                difficulty_source=difficulty_source,
                question_type="explanation",
                prompt=prompt,
                total_marks=total_marks,
                topic=topic,
                is_active=is_active,
            )
        )
    return row_id


# ---------------------------------------------------------------------------
# Draft lifecycle.
# ---------------------------------------------------------------------------


def test_create_quiz_is_a_half_filled_legal_draft(
    quiz_service: QuizService, pg_sessionmaker: sessionmaker[Session]
) -> None:
    teacher = _seed_teacher(pg_sessionmaker)
    row = quiz_service.create_quiz(teacher, "0625", "Thermal physics recap")

    assert row.status == QuizStatus.draft
    assert row.builder_step == 1
    assert row.target_grade is None
    assert row.included_topics == []
    assert row.pool_source is None
    assert row.requested_count is None
    assert row.time_limit_minutes is None
    assert row.question_count == 0


def test_patch_draft_partial_fields_round_trip(
    quiz_service: QuizService, pg_sessionmaker: sessionmaker[Session]
) -> None:
    teacher = _seed_teacher(pg_sessionmaker)
    created = quiz_service.create_quiz(teacher, "0625", "Thermal physics recap")

    # Step 2/3: topics + target grade only.
    step2 = quiz_service.patch_draft(
        teacher, created.quiz_id, included_topics=["Thermal", "Waves"], target_grade="C"
    )
    assert step2.included_topics == ["Thermal", "Waves"]
    assert step2.target_grade == "C"
    # Untouched fields survive the partial update.
    assert step2.title == "Thermal physics recap"
    assert step2.pool_source is None
    assert step2.builder_step == 1

    # Step 4: pool + count, in a separate call — "resume" a half-filled draft.
    step4 = quiz_service.patch_draft(
        teacher,
        created.quiz_id,
        pool_source=QuestionSource.generated,
        requested_count=10,
        builder_step=4,
    )
    assert step4.pool_source == QuestionSource.generated
    assert step4.requested_count == 10
    assert step4.builder_step == 4
    # Step 2/3 fields from the earlier PATCH are still there.
    assert step4.included_topics == ["Thermal", "Waves"]
    assert step4.target_grade == "C"

    resumed = quiz_service.get_quiz(teacher, created.quiz_id).quiz
    assert resumed.title == "Thermal physics recap"
    assert resumed.included_topics == ["Thermal", "Waves"]
    assert resumed.target_grade == "C"
    assert resumed.pool_source == QuestionSource.generated
    assert resumed.requested_count == 10
    assert resumed.builder_step == 4


def test_patch_draft_rejects_unknown_target_grade(
    quiz_service: QuizService, pg_sessionmaker: sessionmaker[Session]
) -> None:
    teacher = _seed_teacher(pg_sessionmaker)
    created = quiz_service.create_quiz(teacher, "0625", "Quiz")
    with pytest.raises(QuizValidationError):
        quiz_service.patch_draft(teacher, created.quiz_id, target_grade="Z")


def test_patch_draft_rejects_negative_requested_count(
    quiz_service: QuizService, pg_sessionmaker: sessionmaker[Session]
) -> None:
    teacher = _seed_teacher(pg_sessionmaker)
    created = quiz_service.create_quiz(teacher, "0625", "Quiz")
    with pytest.raises(QuizValidationError):
        quiz_service.patch_draft(teacher, created.quiz_id, requested_count=-1)


# ---------------------------------------------------------------------------
# Status lifecycle.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("start", "target"),
    [
        (QuizStatus.assigned, QuizStatus.draft),  # never backwards
        (QuizStatus.closed, QuizStatus.assigned),  # never backwards
        (QuizStatus.archived, QuizStatus.draft),  # terminal
        (QuizStatus.draft, QuizStatus.closed),  # must go through assigned
        (QuizStatus.assigned, QuizStatus.archived),  # not a legal transition
    ],
)
def test_status_transition_forbidden_pairs_rejected(
    quiz_service: QuizService,
    pg_sessionmaker: sessionmaker[Session],
    start: QuizStatus,
    target: QuizStatus,
) -> None:
    teacher = _seed_teacher(pg_sessionmaker)
    created = quiz_service.create_quiz(teacher, "0625", "Quiz")
    _force_status(pg_sessionmaker, created.quiz_id, start)
    with pytest.raises(QuizValidationError):
        quiz_service.set_status(teacher, created.quiz_id, target)


@pytest.mark.parametrize(
    ("start", "target"),
    [
        (QuizStatus.draft, QuizStatus.assigned),
        (QuizStatus.draft, QuizStatus.archived),
        (QuizStatus.assigned, QuizStatus.closed),
        (QuizStatus.closed, QuizStatus.archived),
    ],
)
def test_status_transition_allowed_pairs_succeed(
    quiz_service: QuizService,
    pg_sessionmaker: sessionmaker[Session],
    start: QuizStatus,
    target: QuizStatus,
) -> None:
    teacher = _seed_teacher(pg_sessionmaker)
    created = quiz_service.create_quiz(teacher, "0625", "Quiz")
    _force_status(pg_sessionmaker, created.quiz_id, start)
    row = quiz_service.set_status(teacher, created.quiz_id, target)
    assert row.status == target


def test_editing_questions_on_non_draft_quiz_is_rejected(
    quiz_service: QuizService, pg_sessionmaker: sessionmaker[Session]
) -> None:
    teacher = _seed_teacher(pg_sessionmaker)
    created = quiz_service.create_quiz(teacher, "0625", "Quiz")
    quiz_service.patch_draft(
        teacher, created.quiz_id, pool_source=QuestionSource.generated, requested_count=1
    )
    _seed_bank_row(pg_sessionmaker, subject_code="0625", difficulty=QuestionDifficulty.standard)
    quiz_service.generate_questions(teacher, created.quiz_id)

    quiz_service.set_status(teacher, created.quiz_id, QuizStatus.assigned)

    with pytest.raises(QuizValidationError):
        quiz_service.generate_questions(teacher, created.quiz_id)

    detail = quiz_service.get_quiz(teacher, created.quiz_id)
    ref = detail.questions[0].question_ref
    with pytest.raises(QuizValidationError):
        quiz_service.remove_question(teacher, created.quiz_id, ref)

    with pytest.raises(QuizValidationError):
        quiz_service.patch_draft(teacher, created.quiz_id, title="New title")


def _force_status(sm: sessionmaker[Session], quiz_id: uuid.UUID, status: QuizStatus) -> None:
    """Set a quiz's status directly, bypassing the lifecycle guard (test-only)."""
    from lemely.db.models.quizzes import Quiz

    with sm.begin() as session:
        quiz = session.get(Quiz, quiz_id)
        assert quiz is not None
        quiz.status = status


# ---------------------------------------------------------------------------
# question_ref stability.
# ---------------------------------------------------------------------------


def test_remove_middle_question_keeps_other_refs_stable(
    quiz_service: QuizService, pg_sessionmaker: sessionmaker[Session]
) -> None:
    teacher = _seed_teacher(pg_sessionmaker)
    created = quiz_service.create_quiz(teacher, "0625", "Quiz")
    quiz_service.patch_draft(
        teacher, created.quiz_id, pool_source=QuestionSource.generated, requested_count=3
    )
    # Untargeted mix (0.2, 0.6, 0.2) over count=3 allocates foundation=1,
    # standard=2, challenge=0 (largest-remainder rounding) — seed exactly
    # that supply so all 3 requested questions actually materialize.
    _seed_bank_row(pg_sessionmaker, subject_code="0625", difficulty=QuestionDifficulty.foundation)
    for _ in range(2):
        _seed_bank_row(pg_sessionmaker, subject_code="0625", difficulty=QuestionDifficulty.standard)
    quiz_service.generate_questions(teacher, created.quiz_id)

    before = quiz_service.get_quiz(teacher, created.quiz_id).questions
    assert {q.question_ref for q in before} == {"q1", "q2", "q3"}
    middle_ref = sorted(before, key=lambda q: q.position)[1].question_ref

    quiz_service.remove_question(teacher, created.quiz_id, middle_ref)

    after = quiz_service.get_quiz(teacher, created.quiz_id).questions
    refs_by_status = {q.question_ref: q.status for q in after}
    assert refs_by_status[middle_ref] == QuizQuestionStatus.removed
    remaining_refs = {q.question_ref for q in after} - {middle_ref}
    assert remaining_refs == {"q1", "q2", "q3"} - {middle_ref}
    for ref in remaining_refs:
        assert refs_by_status[ref] == QuizQuestionStatus.included

    # question_count on the summary reflects only 'included' rows.
    summary = quiz_service.get_quiz(teacher, created.quiz_id).quiz
    assert summary.question_count == 2


def test_remove_unknown_ref_is_rejected(
    quiz_service: QuizService, pg_sessionmaker: sessionmaker[Session]
) -> None:
    teacher = _seed_teacher(pg_sessionmaker)
    created = quiz_service.create_quiz(teacher, "0625", "Quiz")
    with pytest.raises(QuizValidationError):
        quiz_service.remove_question(teacher, created.quiz_id, "q99")


def test_remove_already_removed_ref_is_rejected(
    quiz_service: QuizService, pg_sessionmaker: sessionmaker[Session]
) -> None:
    teacher = _seed_teacher(pg_sessionmaker)
    created = quiz_service.create_quiz(teacher, "0625", "Quiz")
    quiz_service.patch_draft(
        teacher, created.quiz_id, pool_source=QuestionSource.generated, requested_count=1
    )
    _seed_bank_row(pg_sessionmaker, subject_code="0625", difficulty=QuestionDifficulty.standard)
    quiz_service.generate_questions(teacher, created.quiz_id)
    ref = quiz_service.get_quiz(teacher, created.quiz_id).questions[0].question_ref

    quiz_service.remove_question(teacher, created.quiz_id, ref)
    with pytest.raises(QuizValidationError):
        quiz_service.remove_question(teacher, created.quiz_id, ref)


# ---------------------------------------------------------------------------
# Snapshot independence (§1.5).
# ---------------------------------------------------------------------------


def test_materialized_question_is_a_snapshot_not_a_live_reference(
    quiz_service: QuizService, pg_sessionmaker: sessionmaker[Session]
) -> None:
    teacher = _seed_teacher(pg_sessionmaker)
    bank_id = _seed_bank_row(
        pg_sessionmaker,
        subject_code="0625",
        difficulty=QuestionDifficulty.standard,
        prompt="Original prompt text",
    )
    created = quiz_service.create_quiz(teacher, "0625", "Quiz")
    quiz_service.patch_draft(
        teacher, created.quiz_id, pool_source=QuestionSource.generated, requested_count=1
    )
    quiz_service.generate_questions(teacher, created.quiz_id)
    question = quiz_service.get_quiz(teacher, created.quiz_id).questions[0]
    assert question.prompt == "Original prompt text"
    assert question.difficulty == "standard"

    # Mutate and deactivate the bank row after materialization.
    with pg_sessionmaker.begin() as session:
        row = session.get(QuestionBank, bank_id)
        assert row is not None
        row.prompt = "Mutated prompt text"
        row.difficulty = QuestionDifficulty.challenge
        row.is_active = False

    unchanged = quiz_service.get_quiz(teacher, created.quiz_id).questions[0]
    assert unchanged.prompt == "Original prompt text"
    assert unchanged.difficulty == "standard"
    assert unchanged.question_bank_id == bank_id  # provenance only, still points at it


# ---------------------------------------------------------------------------
# Count/selection agreement, including the shortfall case.
# ---------------------------------------------------------------------------


def test_generate_questions_never_exceeds_pool_count_matching(
    quiz_service: QuizService, pg_sessionmaker: sessionmaker[Session]
) -> None:
    teacher = _seed_teacher(pg_sessionmaker)
    # Only 2 standard-band rows exist; request 5.
    for _ in range(2):
        _seed_bank_row(pg_sessionmaker, subject_code="0625", difficulty=QuestionDifficulty.standard)

    created = quiz_service.create_quiz(teacher, "0625", "Quiz")
    quiz_service.patch_draft(
        teacher,
        created.quiz_id,
        pool_source=QuestionSource.generated,
        requested_count=5,
        target_grade="C",
    )

    count = quiz_service.pool_count(
        teacher,
        subject_code="0625",
        target_grade="C",
        requested_count=5,
        source=QuestionSource.generated,
    )
    result = quiz_service.generate_questions(teacher, created.quiz_id)

    assert count.shortfall is not None
    assert sum(count.shortfall.values()) > 0
    # The builder created exactly as many as the bank could actually supply.
    assert len(result.created) == count.matching
    assert result.shortfall == count.shortfall


def test_pool_count_and_selection_agree_when_pool_fully_covers_request(
    quiz_service: QuizService, pg_sessionmaker: sessionmaker[Session]
) -> None:
    teacher = _seed_teacher(pg_sessionmaker)
    # Untargeted mix is (0.2, 0.6, 0.2) -> for count=5: foundation=1, standard=3, challenge=1.
    for _ in range(2):
        _seed_bank_row(
            pg_sessionmaker, subject_code="0625", difficulty=QuestionDifficulty.foundation
        )
    for _ in range(4):
        _seed_bank_row(pg_sessionmaker, subject_code="0625", difficulty=QuestionDifficulty.standard)
    for _ in range(2):
        _seed_bank_row(
            pg_sessionmaker, subject_code="0625", difficulty=QuestionDifficulty.challenge
        )

    created = quiz_service.create_quiz(teacher, "0625", "Quiz")
    quiz_service.patch_draft(
        teacher, created.quiz_id, pool_source=QuestionSource.generated, requested_count=5
    )

    count = quiz_service.pool_count(
        teacher,
        subject_code="0625",
        target_grade=None,
        requested_count=5,
        source=QuestionSource.generated,
    )
    assert count.shortfall is None

    result = quiz_service.generate_questions(teacher, created.quiz_id)
    assert result.shortfall == {}
    assert len(result.created) == 5


def test_pool_count_honest_zero_on_empty_bank_names_short_bands(quiz_service: QuizService) -> None:
    teacher = uuid.uuid4()
    result = quiz_service.pool_count(
        teacher,
        subject_code="0625-empty",
        target_grade="C",
        requested_count=10,
        source=QuestionSource.past_paper,
    )
    assert result.matching == 0
    assert result.shortfall is not None
    assert sum(result.shortfall.values()) == 10
    assert result.difficulty_estimated is False


def test_pool_count_difficulty_estimated_true_with_inferred_row(
    quiz_service: QuizService, pg_sessionmaker: sessionmaker[Session]
) -> None:
    teacher = uuid.uuid4()
    _seed_bank_row(
        pg_sessionmaker,
        subject_code="0625-est",
        difficulty=QuestionDifficulty.standard,
        source=QuestionSource.past_paper,
        difficulty_source=DifficultySource.inferred_from_marks,
    )
    result = quiz_service.pool_count(
        teacher,
        subject_code="0625-est",
        target_grade=None,
        requested_count=1,
        source=QuestionSource.past_paper,
    )
    assert result.difficulty_estimated is True


# ---------------------------------------------------------------------------
# Tenancy negatives.
# ---------------------------------------------------------------------------


def test_get_quiz_out_of_scope_is_ownership_error(
    quiz_service: QuizService, pg_sessionmaker: sessionmaker[Session]
) -> None:
    owner = _seed_teacher(pg_sessionmaker)
    other = uuid.uuid4()
    created = quiz_service.create_quiz(owner, "0625", "Quiz")
    with pytest.raises(QuizOwnershipError):
        quiz_service.get_quiz(other, created.quiz_id)


def test_patch_draft_out_of_scope_is_ownership_error(
    quiz_service: QuizService, pg_sessionmaker: sessionmaker[Session]
) -> None:
    owner = _seed_teacher(pg_sessionmaker)
    other = uuid.uuid4()
    created = quiz_service.create_quiz(owner, "0625", "Quiz")
    with pytest.raises(QuizOwnershipError):
        quiz_service.patch_draft(other, created.quiz_id, title="Hijacked")


def test_set_status_out_of_scope_is_ownership_error(
    quiz_service: QuizService, pg_sessionmaker: sessionmaker[Session]
) -> None:
    owner = _seed_teacher(pg_sessionmaker)
    other = uuid.uuid4()
    created = quiz_service.create_quiz(owner, "0625", "Quiz")
    with pytest.raises(QuizOwnershipError):
        quiz_service.set_status(other, created.quiz_id, QuizStatus.assigned)


def test_generate_questions_out_of_scope_is_ownership_error(
    quiz_service: QuizService, pg_sessionmaker: sessionmaker[Session]
) -> None:
    owner = _seed_teacher(pg_sessionmaker)
    other = uuid.uuid4()
    created = quiz_service.create_quiz(owner, "0625", "Quiz")
    quiz_service.patch_draft(
        owner, created.quiz_id, pool_source=QuestionSource.generated, requested_count=1
    )
    with pytest.raises(QuizOwnershipError):
        quiz_service.generate_questions(other, created.quiz_id)


def test_remove_question_out_of_scope_is_ownership_error(
    quiz_service: QuizService, pg_sessionmaker: sessionmaker[Session]
) -> None:
    owner = _seed_teacher(pg_sessionmaker)
    other = uuid.uuid4()
    created = quiz_service.create_quiz(owner, "0625", "Quiz")
    with pytest.raises(QuizOwnershipError):
        quiz_service.remove_question(other, created.quiz_id, "q1")


def test_list_quizzes_never_shows_another_teachers_quiz(
    quiz_service: QuizService, pg_sessionmaker: sessionmaker[Session]
) -> None:
    owner = _seed_teacher(pg_sessionmaker)
    other = _seed_teacher(pg_sessionmaker)
    quiz_service.create_quiz(owner, "0625", "Owner's quiz")
    quiz_service.create_quiz(other, "0625", "Other's quiz")

    owner_titles = {row.title for row in quiz_service.list_quizzes(owner)}
    other_titles = {row.title for row in quiz_service.list_quizzes(other)}
    assert owner_titles == {"Owner's quiz"}
    assert other_titles == {"Other's quiz"}


def test_unknown_quiz_id_is_not_found_not_ownership(quiz_service: QuizService) -> None:
    caller = uuid.uuid4()
    with pytest.raises(QuizNotFoundError):
        quiz_service.get_quiz(caller, uuid.uuid4())


def test_pool_count_never_sees_another_teachers_owned_rows(
    quiz_service: QuizService, pg_sessionmaker: sessionmaker[Session]
) -> None:
    teacher_a = _seed_teacher(pg_sessionmaker)
    teacher_b = _seed_teacher(pg_sessionmaker)
    _seed_bank_row(
        pg_sessionmaker,
        subject_code="0625-tenancy",
        difficulty=QuestionDifficulty.standard,
        owner_id=teacher_b,
        source=QuestionSource.teacher_upload,
    )

    result = quiz_service.pool_count(
        teacher_a,
        subject_code="0625-tenancy",
        target_grade=None,
        requested_count=1,
        source=QuestionSource.teacher_upload,
    )
    assert result.matching == 0


def test_generate_questions_never_selects_another_teachers_owned_rows(
    quiz_service: QuizService, pg_sessionmaker: sessionmaker[Session]
) -> None:
    teacher_a = _seed_teacher(pg_sessionmaker)
    teacher_b = _seed_teacher(pg_sessionmaker)
    _seed_bank_row(
        pg_sessionmaker,
        subject_code="0625-tenancy2",
        difficulty=QuestionDifficulty.standard,
        owner_id=teacher_b,
        source=QuestionSource.teacher_upload,
    )

    created = quiz_service.create_quiz(teacher_a, "0625-tenancy2", "Quiz")
    quiz_service.patch_draft(
        teacher_a, created.quiz_id, pool_source=QuestionSource.teacher_upload, requested_count=5
    )
    result = quiz_service.generate_questions(teacher_a, created.quiz_id)

    # teacher_b's row is the only one that exists for this subject; teacher_a
    # must see none of it, so nothing gets materialized (never a substitute
    # from a visible band either — an honest empty result, not a leak).
    assert result.created == []
    assert result.shortfall == {"foundation": 1, "standard": 3, "challenge": 1}


# ---------------------------------------------------------------------------
# get_quiz retains removed rows (audit trail).
# ---------------------------------------------------------------------------


def test_get_quiz_returns_removed_rows_too(
    quiz_service: QuizService, pg_sessionmaker: sessionmaker[Session]
) -> None:
    teacher = _seed_teacher(pg_sessionmaker)
    _seed_bank_row(pg_sessionmaker, subject_code="0625", difficulty=QuestionDifficulty.standard)
    created = quiz_service.create_quiz(teacher, "0625", "Quiz")
    quiz_service.patch_draft(
        teacher, created.quiz_id, pool_source=QuestionSource.generated, requested_count=1
    )
    quiz_service.generate_questions(teacher, created.quiz_id)
    ref = quiz_service.get_quiz(teacher, created.quiz_id).questions[0].question_ref
    quiz_service.remove_question(teacher, created.quiz_id, ref)

    detail = quiz_service.get_quiz(teacher, created.quiz_id)
    assert len(detail.questions) == 1
    assert detail.questions[0].status == QuizQuestionStatus.removed
    assert detail.quiz.question_count == 0


# ---------------------------------------------------------------------------
# Assignments (§1.6, P3.5 chunk E).
# ---------------------------------------------------------------------------


def _assignable_quiz(
    quiz_service: QuizService, sm: sessionmaker[Session], teacher: uuid.UUID, subject_code: str
) -> uuid.UUID:
    """Create a draft quiz with exactly one ``included`` question, ready to assign."""
    _seed_bank_row(sm, subject_code=subject_code, difficulty=QuestionDifficulty.standard)
    created = quiz_service.create_quiz(teacher, subject_code, "Assignable quiz")
    quiz_service.patch_draft(
        teacher, created.quiz_id, pool_source=QuestionSource.generated, requested_count=1
    )
    quiz_service.generate_questions(teacher, created.quiz_id)
    return created.quiz_id


def test_create_assignment_transitions_draft_to_assigned(
    quiz_service: QuizService, class_service: ClassService, pg_sessionmaker: sessionmaker[Session]
) -> None:
    teacher = _seed_teacher(pg_sessionmaker)
    quiz_id = _assignable_quiz(quiz_service, pg_sessionmaker, teacher, "0625")
    cls = class_service.create_class(teacher, "Physics 10A")

    row = quiz_service.create_assignment(teacher, Role.teacher, quiz_id, cls.class_id)

    assert row.class_id == cls.class_id
    assert row.class_name == "Physics 10A"
    assert row.roster_size == 0
    assert row.submission_counts == {s.value: 0 for s in QuizSubmissionStatus}
    assert quiz_service.get_quiz(teacher, quiz_id).quiz.status == QuizStatus.assigned


def test_create_assignment_on_assigned_quiz_allows_further_class(
    quiz_service: QuizService, class_service: ClassService, pg_sessionmaker: sessionmaker[Session]
) -> None:
    teacher = _seed_teacher(pg_sessionmaker)
    quiz_id = _assignable_quiz(quiz_service, pg_sessionmaker, teacher, "0625")
    cls_a = class_service.create_class(teacher, "Class A")
    cls_b = class_service.create_class(teacher, "Class B")

    quiz_service.create_assignment(teacher, Role.teacher, quiz_id, cls_a.class_id)
    row = quiz_service.create_assignment(teacher, Role.teacher, quiz_id, cls_b.class_id)

    assert row.class_id == cls_b.class_id
    assert quiz_service.get_quiz(teacher, quiz_id).quiz.status == QuizStatus.assigned


def test_create_assignment_empty_quiz_is_rejected(
    quiz_service: QuizService, class_service: ClassService, pg_sessionmaker: sessionmaker[Session]
) -> None:
    teacher = _seed_teacher(pg_sessionmaker)
    created = quiz_service.create_quiz(teacher, "0625", "Empty quiz")
    cls = class_service.create_class(teacher, "Class")

    with pytest.raises(QuizValidationError):
        quiz_service.create_assignment(teacher, Role.teacher, created.quiz_id, cls.class_id)


def test_create_assignment_closed_quiz_is_rejected(
    quiz_service: QuizService, class_service: ClassService, pg_sessionmaker: sessionmaker[Session]
) -> None:
    teacher = _seed_teacher(pg_sessionmaker)
    quiz_id = _assignable_quiz(quiz_service, pg_sessionmaker, teacher, "0625")
    cls = class_service.create_class(teacher, "Class")
    _force_status(pg_sessionmaker, quiz_id, QuizStatus.closed)

    with pytest.raises(QuizValidationError):
        quiz_service.create_assignment(teacher, Role.teacher, quiz_id, cls.class_id)


def test_create_assignment_archived_quiz_is_rejected(
    quiz_service: QuizService, class_service: ClassService, pg_sessionmaker: sessionmaker[Session]
) -> None:
    teacher = _seed_teacher(pg_sessionmaker)
    quiz_id = _assignable_quiz(quiz_service, pg_sessionmaker, teacher, "0625")
    cls = class_service.create_class(teacher, "Class")
    _force_status(pg_sessionmaker, quiz_id, QuizStatus.archived)

    with pytest.raises(QuizValidationError):
        quiz_service.create_assignment(teacher, Role.teacher, quiz_id, cls.class_id)


def test_create_assignment_duplicate_is_rejected(
    quiz_service: QuizService, class_service: ClassService, pg_sessionmaker: sessionmaker[Session]
) -> None:
    teacher = _seed_teacher(pg_sessionmaker)
    quiz_id = _assignable_quiz(quiz_service, pg_sessionmaker, teacher, "0625")
    cls = class_service.create_class(teacher, "Class")
    quiz_service.create_assignment(teacher, Role.teacher, quiz_id, cls.class_id)

    with pytest.raises(QuizValidationError):
        quiz_service.create_assignment(teacher, Role.teacher, quiz_id, cls.class_id)


def test_create_assignment_closes_before_due_is_rejected(
    quiz_service: QuizService, class_service: ClassService, pg_sessionmaker: sessionmaker[Session]
) -> None:
    teacher = _seed_teacher(pg_sessionmaker)
    quiz_id = _assignable_quiz(quiz_service, pg_sessionmaker, teacher, "0625")
    cls = class_service.create_class(teacher, "Class")
    now = datetime.now(UTC)

    with pytest.raises(QuizValidationError):
        quiz_service.create_assignment(
            teacher,
            Role.teacher,
            quiz_id,
            cls.class_id,
            due_at=now + timedelta(days=2),
            closes_at=now + timedelta(days=1),
        )


def test_create_assignment_another_teachers_quiz_is_ownership_error(
    quiz_service: QuizService, class_service: ClassService, pg_sessionmaker: sessionmaker[Session]
) -> None:
    owner = _seed_teacher(pg_sessionmaker)
    intruder = _seed_teacher(pg_sessionmaker)
    quiz_id = _assignable_quiz(quiz_service, pg_sessionmaker, owner, "0625")
    cls = class_service.create_class(intruder, "Intruder's class")

    with pytest.raises(QuizOwnershipError):
        quiz_service.create_assignment(intruder, Role.teacher, quiz_id, cls.class_id)


def test_create_assignment_out_of_scope_class_is_class_ownership_error(
    quiz_service: QuizService, class_service: ClassService, pg_sessionmaker: sessionmaker[Session]
) -> None:
    teacher = _seed_teacher(pg_sessionmaker)
    other_teacher = _seed_teacher(pg_sessionmaker)
    quiz_id = _assignable_quiz(quiz_service, pg_sessionmaker, teacher, "0625")
    other_cls = class_service.create_class(other_teacher, "Not my class")

    with pytest.raises(ClassOwnershipError):
        quiz_service.create_assignment(teacher, Role.teacher, quiz_id, other_cls.class_id)


def test_create_assignment_unknown_class_is_class_not_found_error(
    quiz_service: QuizService, pg_sessionmaker: sessionmaker[Session]
) -> None:
    teacher = _seed_teacher(pg_sessionmaker)
    quiz_id = _assignable_quiz(quiz_service, pg_sessionmaker, teacher, "0625")

    with pytest.raises(ClassNotFoundError):
        quiz_service.create_assignment(teacher, Role.teacher, quiz_id, uuid.uuid4())


def test_list_assignments_roster_size_reflects_late_joiners(
    quiz_service: QuizService, class_service: ClassService, pg_sessionmaker: sessionmaker[Session]
) -> None:
    """Roster-drift: a student who joins *after* assignment appears in ``rosterSize``."""
    teacher = _seed_teacher(pg_sessionmaker)
    quiz_id = _assignable_quiz(quiz_service, pg_sessionmaker, teacher, "0625")
    cls = class_service.create_class(teacher, "Class")
    quiz_service.create_assignment(teacher, Role.teacher, quiz_id, cls.class_id)

    before = quiz_service.list_assignments(teacher, Role.teacher, quiz_id)
    assert before[0].roster_size == 0

    student = _seed_user(pg_sessionmaker, Role.student)
    assert cls.join_code is not None
    class_service.join_by_code(student, cls.join_code)

    after = quiz_service.list_assignments(teacher, Role.teacher, quiz_id)
    assert after[0].roster_size == 1


def test_list_assignments_submission_counts_grouped_by_status(
    quiz_service: QuizService, class_service: ClassService, pg_sessionmaker: sessionmaker[Session]
) -> None:
    teacher = _seed_teacher(pg_sessionmaker)
    quiz_id = _assignable_quiz(quiz_service, pg_sessionmaker, teacher, "0625")
    cls = class_service.create_class(teacher, "Class")
    assignment = quiz_service.create_assignment(teacher, Role.teacher, quiz_id, cls.class_id)
    student_a = _seed_user(pg_sessionmaker, Role.student)
    student_b = _seed_user(pg_sessionmaker, Role.student)
    with pg_sessionmaker.begin() as session:
        session.add(
            QuizSubmission(
                assignment_id=assignment.assignment_id,
                student_id=student_a,
                status=QuizSubmissionStatus.in_progress,
            )
        )
        session.add(
            QuizSubmission(
                assignment_id=assignment.assignment_id,
                student_id=student_b,
                status=QuizSubmissionStatus.submitted,
            )
        )

    rows = quiz_service.list_assignments(teacher, Role.teacher, quiz_id)
    counts = rows[0].submission_counts
    assert counts["in_progress"] == 1
    assert counts["submitted"] == 1
    assert counts["not_started"] == 0
    assert counts["marked"] == 0


def test_list_assignments_another_teachers_quiz_is_ownership_error(
    quiz_service: QuizService, pg_sessionmaker: sessionmaker[Session]
) -> None:
    owner = _seed_teacher(pg_sessionmaker)
    intruder = _seed_teacher(pg_sessionmaker)
    quiz_id = _assignable_quiz(quiz_service, pg_sessionmaker, owner, "0625")

    with pytest.raises(QuizOwnershipError):
        quiz_service.list_assignments(intruder, Role.teacher, quiz_id)


def test_delete_assignment_happy_path(
    quiz_service: QuizService, class_service: ClassService, pg_sessionmaker: sessionmaker[Session]
) -> None:
    teacher = _seed_teacher(pg_sessionmaker)
    quiz_id = _assignable_quiz(quiz_service, pg_sessionmaker, teacher, "0625")
    cls = class_service.create_class(teacher, "Class")
    assignment = quiz_service.create_assignment(teacher, Role.teacher, quiz_id, cls.class_id)

    quiz_service.delete_assignment(teacher, quiz_id, assignment.assignment_id)

    assert quiz_service.list_assignments(teacher, Role.teacher, quiz_id) == []


def test_delete_assignment_refused_once_student_started(
    quiz_service: QuizService, class_service: ClassService, pg_sessionmaker: sessionmaker[Session]
) -> None:
    teacher = _seed_teacher(pg_sessionmaker)
    quiz_id = _assignable_quiz(quiz_service, pg_sessionmaker, teacher, "0625")
    cls = class_service.create_class(teacher, "Class")
    assignment = quiz_service.create_assignment(teacher, Role.teacher, quiz_id, cls.class_id)
    student = _seed_user(pg_sessionmaker, Role.student)
    with pg_sessionmaker.begin() as session:
        session.add(
            QuizSubmission(
                assignment_id=assignment.assignment_id,
                student_id=student,
                status=QuizSubmissionStatus.in_progress,
            )
        )

    with pytest.raises(QuizValidationError):
        quiz_service.delete_assignment(teacher, quiz_id, assignment.assignment_id)

    # The assignment (and its submission) must still exist afterwards.
    remaining = quiz_service.list_assignments(teacher, Role.teacher, quiz_id)
    assert len(remaining) == 1


def test_delete_assignment_allowed_when_only_not_started_submissions_exist(
    quiz_service: QuizService, class_service: ClassService, pg_sessionmaker: sessionmaker[Session]
) -> None:
    teacher = _seed_teacher(pg_sessionmaker)
    quiz_id = _assignable_quiz(quiz_service, pg_sessionmaker, teacher, "0625")
    cls = class_service.create_class(teacher, "Class")
    assignment = quiz_service.create_assignment(teacher, Role.teacher, quiz_id, cls.class_id)
    student = _seed_user(pg_sessionmaker, Role.student)
    with pg_sessionmaker.begin() as session:
        session.add(
            QuizSubmission(
                assignment_id=assignment.assignment_id,
                student_id=student,
                status=QuizSubmissionStatus.not_started,
            )
        )

    quiz_service.delete_assignment(teacher, quiz_id, assignment.assignment_id)
    assert quiz_service.list_assignments(teacher, Role.teacher, quiz_id) == []


def test_delete_assignment_unknown_assignment_is_not_found(
    quiz_service: QuizService, pg_sessionmaker: sessionmaker[Session]
) -> None:
    teacher = _seed_teacher(pg_sessionmaker)
    quiz_id = _assignable_quiz(quiz_service, pg_sessionmaker, teacher, "0625")

    with pytest.raises(QuizNotFoundError):
        quiz_service.delete_assignment(teacher, quiz_id, uuid.uuid4())


def test_delete_assignment_another_teachers_quiz_is_ownership_error(
    quiz_service: QuizService, class_service: ClassService, pg_sessionmaker: sessionmaker[Session]
) -> None:
    owner = _seed_teacher(pg_sessionmaker)
    intruder = _seed_teacher(pg_sessionmaker)
    quiz_id = _assignable_quiz(quiz_service, pg_sessionmaker, owner, "0625")
    cls = class_service.create_class(owner, "Class")
    assignment = quiz_service.create_assignment(owner, Role.teacher, quiz_id, cls.class_id)

    with pytest.raises(QuizOwnershipError):
        quiz_service.delete_assignment(intruder, quiz_id, assignment.assignment_id)


def _seed_user(
    sm: sessionmaker[Session], role: Role, *, display_name: str | None = None
) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role, display_name=display_name))
    return uid
