"""The placement-quiz ownership shape: XOR invariants and fail-closed reads (P4.4, D4.6).

D4.6 §1 makes "exactly one owner, always" a *database* invariant rather than a
convention, and D4.6 §3 states the rule that keeps it safe once student-owned
rows exist:

    A query is scoped by an owner/target predicate, never by ``kind``.

Six of the eight enumerated read sites need no code change to honour that,
because SQL three-valued logic already excludes a NULL owner from an equality
or ``IN``. That is a *property of the existing queries*, and a property nobody
wrote down is a property a refactor deletes by accident — so the fail-closed
half of this module asserts it directly. These are the tests that catch a
future change swapping an owner predicate for a ``kind`` one.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.db.base import Base
from lemely.db.class_repo import ClassService
from lemely.db.models import User
from lemely.db.models.enums import QuizKind, QuizStatus, Role
from lemely.db.models.quizzes import Quiz, QuizAssignment
from lemely.db.question_bank_repo import QuestionBankService
from lemely.db.quiz_repo import QuizOwnershipError, QuizService
from lemely.db.quiz_taking_repo import (
    QuizTakingNotFoundError,
    QuizTakingOwnershipError,
    QuizTakingService,
)
from lemely.runtime.config import DatabaseSettings

if TYPE_CHECKING:
    from collections.abc import Iterator


# ── Fixture: throwaway Postgres database ────────────────────────────────
# Local copy rather than a cross-module import, matching the convention every
# other Postgres-integration module in this suite already follows.


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


def _seed_user(sm: sessionmaker[Session], role: Role) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role))
    return uid


def _placement_quiz(sm: sessionmaker[Session], student_id: uuid.UUID) -> uuid.UUID:
    """A student-owned placement quiz, assigned and self-assigned."""
    quiz_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            Quiz(
                id=quiz_id,
                teacher_id=None,
                student_id=student_id,
                kind=QuizKind.placement,
                subject_code="0625",
                title="Placement test",
                status=QuizStatus.assigned,
            )
        )
        session.add(
            QuizAssignment(
                quiz_id=quiz_id,
                class_id=None,
                student_id=student_id,
                # The student assigned it to themselves — "who assigned this"
                # answered truthfully, not with a sentinel (D4.6 §1).
                assigned_by=student_id,
            )
        )
    return quiz_id


# ── The database invariants (D4.6 §7) ────────────────────────────────────


def test_a_quiz_with_two_owners_is_rejected(pg_sessionmaker: sessionmaker[Session]) -> None:
    teacher_id = _seed_user(pg_sessionmaker, Role.teacher)
    student_id = _seed_user(pg_sessionmaker, Role.student)

    with pytest.raises(IntegrityError, match="ck_quizzes_owner_xor"), pg_sessionmaker.begin() as s:
        s.add(
            Quiz(
                teacher_id=teacher_id,
                student_id=student_id,
                kind=QuizKind.teacher,
                subject_code="0625",
                title="Two owners",
            )
        )


def test_a_quiz_with_no_owner_is_rejected(pg_sessionmaker: sessionmaker[Session]) -> None:
    with pytest.raises(IntegrityError, match="ck_quizzes_owner_xor"), pg_sessionmaker.begin() as s:
        s.add(
            Quiz(
                teacher_id=None,
                student_id=None,
                kind=QuizKind.placement,
                subject_code="0625",
                title="Orphan",
            )
        )


def test_a_placement_quiz_owned_by_a_teacher_is_rejected(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """``kind`` can never disagree with the owner column (``ck_quizzes_kind_owner``)."""
    teacher_id = _seed_user(pg_sessionmaker, Role.teacher)

    with pytest.raises(IntegrityError, match="ck_quizzes_kind_owner"), pg_sessionmaker.begin() as s:
        s.add(
            Quiz(
                teacher_id=teacher_id,
                student_id=None,
                kind=QuizKind.placement,
                subject_code="0625",
                title="Mislabelled",
            )
        )


def test_an_assignment_with_two_targets_is_rejected(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student_id = _seed_user(pg_sessionmaker, Role.student)
    quiz_id = _placement_quiz(pg_sessionmaker, student_id)

    with (
        pytest.raises(IntegrityError, match="ck_quiz_assignments_target_xor"),
        pg_sessionmaker.begin() as s,
    ):
        s.add(
            QuizAssignment(
                quiz_id=quiz_id,
                class_id=uuid.uuid4(),
                student_id=student_id,
                assigned_by=student_id,
            )
        )


def test_an_assignment_with_no_target_is_rejected(pg_sessionmaker: sessionmaker[Session]) -> None:
    student_id = _seed_user(pg_sessionmaker, Role.student)
    quiz_id = _placement_quiz(pg_sessionmaker, student_id)

    with (
        pytest.raises(IntegrityError, match="ck_quiz_assignments_target_xor"),
        pg_sessionmaker.begin() as s,
    ):
        s.add(
            QuizAssignment(quiz_id=quiz_id, class_id=None, student_id=None, assigned_by=student_id)
        )


def test_a_student_cannot_be_self_assigned_the_same_quiz_twice(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The partial unique index, which must not disturb class uniqueness."""
    student_id = _seed_user(pg_sessionmaker, Role.student)
    quiz_id = _placement_quiz(pg_sessionmaker, student_id)

    with (
        pytest.raises(IntegrityError, match="uq_quiz_assignments_student"),
        pg_sessionmaker.begin() as s,
    ):
        s.add(
            QuizAssignment(
                quiz_id=quiz_id, class_id=None, student_id=student_id, assigned_by=student_id
            )
        )


# ── The fail-closed reads (D4.6 §3) ──────────────────────────────────────


def test_a_placement_quiz_is_invisible_to_every_teacher(
    pg_sessionmaker: sessionmaker[Session],
    quiz_service: QuizService,
) -> None:
    """``list_quizzes`` scopes on ``teacher_id == :caller``; NULL never equals a uuid.

    Asserted rather than assumed: this is the property that would silently
    disappear if the predicate were ever rewritten as a ``kind`` filter.
    """
    teacher_id = _seed_user(pg_sessionmaker, Role.teacher)
    student_id = _seed_user(pg_sessionmaker, Role.student)
    quiz_id = _placement_quiz(pg_sessionmaker, student_id)

    assert [row.quiz_id for row in quiz_service.list_quizzes(teacher_id)] == []

    with pytest.raises(QuizOwnershipError):
        quiz_service.get_quiz(teacher_id, quiz_id)


def test_a_placement_quiz_is_not_an_assigned_quiz(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
) -> None:
    """``list_assigned`` scopes on ``class_id IN (:enrolled)``; ``NULL IN (…)`` is NULL.

    Deliberate, not a gap (D4.6 §3): a placement test is not "an assigned
    quiz" in the student's assigned-work list. P4.5/P4.7 add a second,
    explicitly ``kind``-allowlisted branch for practice and study-plan sets.
    """
    student_id = _seed_user(pg_sessionmaker, Role.student)
    _placement_quiz(pg_sessionmaker, student_id)

    taking = QuizTakingService(pg_sessionmaker, class_service)

    assert taking.list_assigned(student_id) == []


# ── The one predicate that genuinely changed (D4.6 §4) ───────────────────


def _assignment_id(sm: sessionmaker[Session], quiz_id: uuid.UUID) -> uuid.UUID:
    with sm() as session:
        return session.scalars(
            sa.select(QuizAssignment.id).where(QuizAssignment.quiz_id == quiz_id)
        ).one()


def test_the_owning_student_can_open_their_own_placement_test(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
) -> None:
    """``_load_permitted``'s direct-to-student branch.

    The student is enrolled in **no class at all** — which is the point. Under
    the old ``_load_enrolled`` predicate a class-less assignment was
    un-takeable by anyone, so this is the behaviour D4.6 §4 had to add rather
    than a behaviour it preserved.
    """
    student_id = _seed_user(pg_sessionmaker, Role.student)
    quiz_id = _placement_quiz(pg_sessionmaker, student_id)
    assignment_id = _assignment_id(pg_sessionmaker, quiz_id)

    taking = QuizTakingService(pg_sessionmaker, class_service)
    detail = taking.get_take(student_id, assignment_id)

    # The absence is carried through as absence, not as a blank name: a
    # placement test has no teacher and no class, and S-04 must render that
    # rather than an empty string (D4.6 §3).
    assert detail.header.class_name is None
    assert detail.header.teacher_name is None
    assert detail.header.quiz_title == "Placement test"


def test_another_student_cannot_open_someone_elses_placement_test(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
) -> None:
    """403, not data — the inequality branch, which is what makes ``_load_permitted``
    fail closed rather than merely fail differently."""
    owner_id = _seed_user(pg_sessionmaker, Role.student)
    other_id = _seed_user(pg_sessionmaker, Role.student)
    quiz_id = _placement_quiz(pg_sessionmaker, owner_id)
    assignment_id = _assignment_id(pg_sessionmaker, quiz_id)

    taking = QuizTakingService(pg_sessionmaker, class_service)

    with pytest.raises(QuizTakingOwnershipError):
        taking.get_take(other_id, assignment_id)
    with pytest.raises(QuizTakingOwnershipError):
        taking.submit(other_id, assignment_id)


def test_an_unknown_assignment_is_still_a_404_not_a_403(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
) -> None:
    """The D3.4 403-vs-404 split survives the rewrite unchanged."""
    student_id = _seed_user(pg_sessionmaker, Role.student)
    taking = QuizTakingService(pg_sessionmaker, class_service)

    with pytest.raises(QuizTakingNotFoundError):
        taking.get_take(student_id, uuid.uuid4())
