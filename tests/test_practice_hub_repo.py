"""Service tests for :mod:`lemely.db.practice_hub_repo` (L4 Practice tab).

Throwaway Postgres per test (mirrors ``tests/test_web_practice.py``), skipped
when no local server is reachable.
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
from lemely.db.models import User
from lemely.db.models.academic import MarkScheme, Paper, Subject
from lemely.db.models.attempts import Attempt
from lemely.db.models.catalogue import SyllabusPaper
from lemely.db.models.enums import (
    AttemptOrigin,
    DifficultySource,
    ExamBoard,
    QuestionDifficulty,
    QuestionSource,
    QuizKind,
    QuizQuestionStatus,
    QuizStatus,
    QuizSubmissionStatus,
    Role,
    SessionMonth,
)
from lemely.db.models.quizzes import Quiz, QuizAnswer, QuizAssignment, QuizQuestion, QuizSubmission
from lemely.db.practice_hub_repo import (
    RUNS_LIMIT_MAX,
    PastPaperUnavailableError,
    PracticeHubService,
)
from lemely.db.practice_repo import PracticeNotFoundError
from lemely.db.question_bank_repo import NewBankQuestion, QuestionBankService
from lemely.runtime.config import DatabaseSettings

if TYPE_CHECKING:
    from collections.abc import Iterator

T0 = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)


def _server_reachable(url: str) -> bool:
    engine = create_engine(make_url(url).set(database="postgres"))
    try:
        with engine.connect():
            return True
    except OperationalError:
        return False
    finally:
        engine.dispose()


@pytest.fixture
def sm() -> Iterator[sessionmaker[Session]]:
    base_url = DatabaseSettings().url
    if not _server_reachable(base_url):
        pytest.skip("local Postgres not reachable")
    admin = create_engine(make_url(base_url).set(database="postgres"), isolation_level="AUTOCOMMIT")
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
def service(sm: sessionmaker[Session]) -> PracticeHubService:
    return PracticeHubService(sm)


def _user(sm: sessionmaker[Session], role: Role = Role.student) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role))
    return uid


def _set(
    sm: sessionmaker[Session],
    student: uuid.UUID,
    *,
    topics: list[str | None],
    assigned_at: datetime = T0,
    kind: QuizKind = QuizKind.practice,
    subject_code: str = "0625",
    status: QuizSubmissionStatus | None = None,
    answers: list[str] | None = None,
    answered_at: datetime | None = None,
    marks: tuple[int, int] | None = None,
) -> uuid.UUID:
    """One self-assigned set; returns the assignment id."""
    with sm.begin() as session:
        quiz = Quiz(
            teacher_id=None,
            student_id=student,
            kind=kind,
            subject_code=subject_code,
            title="Physics Practice Set",
            status=QuizStatus.assigned,
        )
        session.add(quiz)
        session.flush()
        assignment = QuizAssignment(
            quiz_id=quiz.id,
            class_id=None,
            student_id=student,
            assigned_by=student,
            assigned_at=assigned_at,
        )
        session.add(assignment)
        questions = []
        for position, topic in enumerate(topics, start=1):
            qq = QuizQuestion(
                quiz_id=quiz.id,
                question_ref=f"q{position}",
                position=position,
                status=QuizQuestionStatus.included,
                topic=topic,
                difficulty=QuestionDifficulty.standard,
                question_type="short",
                prompt=f"Question {position}",
                mark_scheme_points=[],
                total_marks=2,
            )
            session.add(qq)
            questions.append(qq)
        session.flush()
        if status is not None:
            attempt_id = None
            if marks is not None:
                attempt = Attempt(
                    user_id=student,
                    subject_code=subject_code,
                    awarded_marks=marks[0],
                    maximum_marks=marks[1],
                    percentage=100.0 * marks[0] / marks[1],
                    recorded_at=assigned_at,
                    origin=AttemptOrigin.quiz,
                )
                session.add(attempt)
                session.flush()
                attempt_id = attempt.id
            submission = QuizSubmission(
                assignment_id=assignment.id,
                student_id=student,
                status=status,
                started_at=assigned_at,
                submitted_at=assigned_at
                if status in (QuizSubmissionStatus.submitted, QuizSubmissionStatus.marked)
                else None,
                marked_at=assigned_at if status == QuizSubmissionStatus.marked else None,
                attempt_id=attempt_id,
            )
            session.add(submission)
            session.flush()
            for qq, text in zip(questions, answers or [], strict=False):
                session.add(
                    QuizAnswer(
                        submission_id=submission.id,
                        quiz_question_id=qq.id,
                        answer_text=text,
                        answered_at=answered_at or assigned_at,
                    )
                )
        return assignment.id


def test_no_runs_is_an_empty_list(service: PracticeHubService, sm: sessionmaker[Session]) -> None:
    assert service.runs(_user(sm)) == []


def test_a_fresh_set_is_not_started_with_topics_by_frequency(
    service: PracticeHubService, sm: sessionmaker[Session]
) -> None:
    student = _user(sm)
    aid = _set(sm, student, topics=["2 Waves", "1 Motion", "1 Motion", None])
    [run] = service.runs(student)
    assert run.assignment_id == aid
    assert run.status == "not_started"
    assert run.question_count == 4
    assert run.answered_count == 0
    assert run.topics == ["1 Motion", "2 Waves"]
    assert run.awarded_marks is None
    assert run.maximum_marks is None
    assert run.title == "Physics Practice Set"
    assert run.subject_code == "0625"


def test_in_progress_counts_only_non_blank_answers(
    service: PracticeHubService, sm: sessionmaker[Session]
) -> None:
    student = _user(sm)
    _set(
        sm,
        student,
        topics=["1 Motion"] * 4,
        status=QuizSubmissionStatus.in_progress,
        answers=["12 m/s", "   ", "B"],
    )
    [run] = service.runs(student)
    assert run.status == "in_progress"
    assert run.answered_count == 2


def test_marked_run_carries_the_attempt_marks(
    service: PracticeHubService, sm: sessionmaker[Session]
) -> None:
    student = _user(sm)
    _set(
        sm,
        student,
        topics=["1 Motion"] * 3,
        status=QuizSubmissionStatus.marked,
        answers=["a", "b", "c"],
        marks=(7, 9),
    )
    [run] = service.runs(student)
    assert run.status == "marked"
    assert (run.awarded_marks, run.maximum_marks) == (7, 9)


def test_submitted_but_unmarked_never_shows_a_score(
    service: PracticeHubService, sm: sessionmaker[Session]
) -> None:
    student = _user(sm)
    _set(sm, student, topics=["1 Motion"], status=QuizSubmissionStatus.submitted, answers=["a"])
    [run] = service.runs(student)
    assert run.status == "submitted"
    assert run.awarded_marks is None
    assert run.maximum_marks is None


def test_marked_without_an_attempt_reads_as_submitted(
    service: PracticeHubService, sm: sessionmaker[Session]
) -> None:
    student = _user(sm)
    _set(
        sm,
        student,
        topics=["1 Motion"],
        status=QuizSubmissionStatus.marked,
        answers=["a"],
        marks=None,
    )
    [run] = service.runs(student)
    assert run.status == "submitted"
    assert run.awarded_marks is None


def test_orders_by_last_activity_not_creation(
    service: PracticeHubService, sm: sessionmaker[Session]
) -> None:
    student = _user(sm)
    older = _set(
        sm,
        student,
        topics=["1 Motion"],
        assigned_at=T0,
        status=QuizSubmissionStatus.in_progress,
        answers=["a"],
        answered_at=T0 + timedelta(days=3),
    )
    newer = _set(sm, student, topics=["2 Waves"], assigned_at=T0 + timedelta(days=1))
    assert [r.assignment_id for r in service.runs(student)] == [older, newer]
    assert service.runs(student)[0].last_activity_at == T0 + timedelta(days=3)


def test_only_the_callers_own_practice_sets(
    service: PracticeHubService, sm: sessionmaker[Session]
) -> None:
    student = _user(sm)
    other = _user(sm)
    mine = _set(sm, student, topics=["1 Motion"])
    _set(sm, other, topics=["1 Motion"])
    _set(sm, student, topics=["1 Motion"], kind=QuizKind.placement)
    assert [r.assignment_id for r in service.runs(student)] == [mine]


def test_limit_is_honoured_and_bounded(
    service: PracticeHubService, sm: sessionmaker[Session]
) -> None:
    student = _user(sm)
    for day in range(3):
        _set(sm, student, topics=["1 Motion"], assigned_at=T0 + timedelta(days=day))
    assert len(service.runs(student, limit=2)) == 2
    with pytest.raises(ValueError, match="limit"):
        service.runs(student, limit=0)
    with pytest.raises(ValueError, match="limit"):
        service.runs(student, limit=RUNS_LIMIT_MAX + 1)


def _paper(
    sm: sessionmaker[Session],
    *,
    number: int,
    variant: int,
    month: SessionMonth,
    year: int,
    scheme_max: int | None = None,
) -> uuid.UUID:
    with sm.begin() as session:
        if session.scalars(sa.select(Subject).where(Subject.code == "0625")).first() is None:
            session.add(Subject(code="0625", name="Physics", board=ExamBoard.caie))
            session.flush()
        paper = Paper(
            board=ExamBoard.caie,
            subject_code="0625",
            session_month=month,
            session_year=year,
            paper_number=number,
            paper_variant=variant,
        )
        session.add(paper)
        session.flush()
        if scheme_max is not None:
            session.add(MarkScheme(paper_id=paper.id, maximum_mark=scheme_max, parsed_payload={}))
        return paper.id


def _bank(
    sm: sessionmaker[Session],
    paper_id: uuid.UUID,
    refs: list[int],
    *,
    prefix: str = "0625_s23_qp_41",
) -> None:
    QuestionBankService(sm).add_questions(
        [
            NewBankQuestion(
                subject_code="0625",
                source=QuestionSource.past_paper,
                difficulty="standard",
                difficulty_source=DifficultySource.inferred_from_marks,
                question_type="short",
                prompt=f"Calculate the speed in part {ref}.",
                total_marks=3,
                topic="1 Motion",
                source_question_id=f"{prefix}#{ref}",
                paper_id=paper_id,
            )
            for ref in refs
        ]
    )


def _timing(sm: sessionmaker[Session], *, number: int, minutes: int, total: int) -> None:
    with sm.begin() as session:
        session.add(
            SyllabusPaper(
                board=ExamBoard.caie,
                subject_code="0625",
                paper_number=number,
                name=f"Paper {number}",
                duration_minutes=minutes,
                total_marks=total,
                practical=False,
                source_document="0625 syllabus",
                source_url="https://example.org/0625.pdf",
                syllabus_version="2023-2025",
            )
        )


def _paper_attempt(
    sm: sessionmaker[Session], student: uuid.UUID, paper_id: uuid.UUID, awarded: int, maximum: int
) -> None:
    with sm.begin() as session:
        session.add(
            Attempt(
                user_id=student,
                paper_id=paper_id,
                subject_code="0625",
                awarded_marks=awarded,
                maximum_marks=maximum,
                percentage=100.0 * awarded / maximum,
                recorded_at=T0,
                origin=AttemptOrigin.past_paper,
            )
        )


def test_past_papers_lists_servable_or_attempted_papers_in_order(
    service: PracticeHubService, sm: sessionmaker[Session]
) -> None:
    student = _user(sm)
    p41 = _paper(sm, number=4, variant=1, month=SessionMonth.may_june, year=2023, scheme_max=80)
    p42 = _paper(sm, number=4, variant=2, month=SessionMonth.oct_nov, year=2023)
    p21 = _paper(sm, number=2, variant=1, month=SessionMonth.may_june, year=2023)
    _paper(
        sm, number=3, variant=1, month=SessionMonth.may_june, year=2023
    )  # no rows, no attempt: hidden
    _bank(sm, p41, [1, 2, 3])
    _bank(sm, p42, [1], prefix="0625_w23_qp_42")
    _paper_attempt(sm, student, p21, 41, 70)
    _timing(sm, number=4, minutes=75, total=80)

    rows = service.past_papers(student, "0625")

    assert [r.paper_id for r in rows] == [p42, p41, p21]
    first, second, third = rows
    assert (first.code, first.session_label) == ("0625/42", "Oct/Nov 2023")
    assert first.duration_minutes == 75
    assert first.total_marks == 80  # from the syllabus when there is no mark scheme
    assert second.question_count == 3
    assert second.total_marks == 80
    assert (third.code, third.question_count, third.duration_minutes) == ("0625/21", 0, None)
    assert (third.awarded_marks, third.maximum_marks) == (41, 70)
    assert first.awarded_marks is None


def test_past_papers_ignore_another_students_attempt(
    service: PracticeHubService, sm: sessionmaker[Session]
) -> None:
    student = _user(sm)
    other = _user(sm)
    p21 = _paper(sm, number=2, variant=1, month=SessionMonth.may_june, year=2023)
    _paper_attempt(sm, other, p21, 41, 70)
    assert service.past_papers(student, "0625") == []


def test_inactive_bank_rows_do_not_make_a_paper_printable(
    service: PracticeHubService, sm: sessionmaker[Session]
) -> None:
    student = _user(sm)
    p41 = _paper(sm, number=4, variant=1, month=SessionMonth.may_june, year=2023)
    _bank(sm, p41, [1])
    with sm.begin() as session:
        session.execute(sa.text("UPDATE question_bank SET is_active = false"))
    assert service.past_papers(student, "0625") == []


def test_create_from_paper_keeps_question_order_and_titles_the_set(
    service: PracticeHubService, sm: sessionmaker[Session]
) -> None:
    student = _user(sm)
    p41 = _paper(sm, number=4, variant=1, month=SessionMonth.may_june, year=2023)
    _bank(sm, p41, [10, 2, 1])
    _timing(sm, number=4, minutes=75, total=80)

    created = service.create_from_paper(student, p41, timed=True)

    assert created.question_count == 3
    assert created.requested_count == 3
    assert created.reason is None
    with sm() as session:
        quiz = session.get(Quiz, created.quiz_id)
        assert quiz is not None
        assert quiz.kind == QuizKind.practice
        assert quiz.student_id == student
        assert quiz.title == "0625/41 · May/June 2023"
        assert quiz.time_limit_minutes == 75
        prompts = session.scalars(
            sa.select(QuizQuestion.prompt)
            .where(QuizQuestion.quiz_id == quiz.id)
            .order_by(QuizQuestion.position)
        ).all()
    assert prompts == [
        "Calculate the speed in part 1.",
        "Calculate the speed in part 2.",
        "Calculate the speed in part 10.",
    ]
    # The new set shows up in Recent straight away.
    assert service.runs(student)[0].assignment_id == created.assignment_id


def test_create_from_paper_untimed_has_no_limit(
    service: PracticeHubService, sm: sessionmaker[Session]
) -> None:
    student = _user(sm)
    p41 = _paper(sm, number=4, variant=1, month=SessionMonth.may_june, year=2023)
    _bank(sm, p41, [1])
    _timing(sm, number=4, minutes=75, total=80)
    created = service.create_from_paper(student, p41, timed=False)
    with sm() as session:
        quiz = session.get(Quiz, created.quiz_id)
        assert quiz is not None
        assert quiz.time_limit_minutes is None


def test_create_from_unknown_paper_is_not_found(
    service: PracticeHubService, sm: sessionmaker[Session]
) -> None:
    with pytest.raises(PracticeNotFoundError):
        service.create_from_paper(_user(sm), uuid.uuid4(), timed=False)


def test_create_from_paper_with_nothing_servable_is_refused(
    service: PracticeHubService, sm: sessionmaker[Session]
) -> None:
    p21 = _paper(sm, number=2, variant=1, month=SessionMonth.may_june, year=2023)
    with pytest.raises(PastPaperUnavailableError):
        service.create_from_paper(_user(sm), p21, timed=False)
