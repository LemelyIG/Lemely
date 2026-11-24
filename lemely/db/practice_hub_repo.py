"""Practice tab reads (L4): recent practice runs, past papers, and a set built from one past paper.

Kept apart from :mod:`lemely.db.practice_repo` so the Practice-tab lane never
edits the generator module L3 also changes. The same ownership rule holds:
every run query is scoped by ``QuizAssignment.student_id == caller`` **and**
``Quiz.student_id == caller`` **and** ``Quiz.kind == practice``, so another
student's set, a teacher quiz or a placement test can never appear.

Scores are only reported for a ``marked`` submission with a real ``Attempt``
row. Anything else carries ``None`` and never a fabricated zero, the same rule
:meth:`~lemely.db.practice_repo.PracticeService.result` follows.
"""

from __future__ import annotations

import re
import uuid
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy import func, select

from lemely.db.models.academic import MarkScheme, Paper
from lemely.db.models.attempts import Attempt
from lemely.db.models.catalogue import SyllabusPaper
from lemely.db.models.enums import (
    SESSION_MONTH_LABELS,
    AttemptOrigin,
    QuestionSource,
    QuizKind,
    QuizQuestionStatus,
    QuizStatus,
    QuizSubmissionStatus,
    SessionMonth,
)
from lemely.db.models.quizzes import (
    QuestionBank,
    Quiz,
    QuizAnswer,
    QuizAssignment,
    QuizQuestion,
    QuizSubmission,
)
from lemely.db.practice_repo import PracticeCreated, PracticeError, PracticeNotFoundError
from lemely.db.question_bank_repo import _to_row, renderable_bank_filter, visible_bank_filter
from lemely.db.quiz_repo import _snapshot_bank_row
from lemely.db.student_profile_repo import enrolled_paper_numbers

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy import ColumnElement
    from sqlalchemy.orm import Session, sessionmaker

RUNS_LIMIT_MAX = 50


@dataclass(frozen=True, slots=True)
class PracticeRun:
    """One practice set, as the Practice tab's "Recent" list shows it."""

    assignment_id: uuid.UUID
    subject_code: str
    title: str
    topics: list[str]
    status: str
    question_count: int
    answered_count: int
    awarded_marks: int | None
    maximum_marks: int | None
    time_limit_minutes: int | None
    last_activity_at: datetime


_MONTH_RANK: dict[SessionMonth, int] = {
    SessionMonth.oct_nov: 3,
    SessionMonth.may_june: 2,
    SessionMonth.feb_mar: 1,
    SessionMonth.specimen: 0,
}
_QUESTION_NUMBER = re.compile(r"#(\d+)\s*$")


class PastPaperUnavailableError(PracticeError):
    """The paper exists but has no question the bank can serve yet (→ 409)."""


@dataclass(frozen=True, slots=True)
class PastPaperRow:
    """One past paper on the Practice tab's past papers screen."""

    paper_id: uuid.UUID
    subject_code: str
    code: str
    paper_number: int
    paper_variant: int
    session_label: str
    duration_minutes: int | None
    total_marks: int | None
    question_count: int
    awarded_marks: int | None
    maximum_marks: int | None


class PracticeHubService:
    """Reads behind the Practice tab. Constructed with a ``sessionmaker`` alone."""

    def __init__(self, sessionmaker: sessionmaker[Session]) -> None:
        """Wire the service to a session factory."""
        self._sessionmaker = sessionmaker

    def runs(self, student_id: uuid.UUID | str, *, limit: int = 10) -> list[PracticeRun]:
        """The caller's practice sets, most recent activity first.

        Last activity is the latest of: assigned, last non-blank answer,
        submitted, marked. Postgres ``GREATEST`` ignores NULL arguments, so a
        set nobody opened falls back to its assignment time.
        """
        if limit < 1 or limit > RUNS_LIMIT_MAX:
            raise ValueError(f"limit must be between 1 and {RUNS_LIMIT_MAX}, got {limit}")
        student_uuid = _as_uuid(student_id)
        with self._sessionmaker() as session:
            answered = (
                select(
                    QuizAnswer.submission_id.label("submission_id"),
                    func.count(QuizAnswer.id).label("answered"),
                    func.max(QuizAnswer.answered_at).label("last_answer_at"),
                )
                .where(func.coalesce(func.trim(QuizAnswer.answer_text), "") != "")
                .group_by(QuizAnswer.submission_id)
                .subquery()
            )
            counts = (
                select(
                    QuizQuestion.quiz_id.label("quiz_id"), func.count(QuizQuestion.id).label("n")
                )
                .where(QuizQuestion.status == QuizQuestionStatus.included)
                .group_by(QuizQuestion.quiz_id)
                .subquery()
            )
            last_activity = func.greatest(
                QuizAssignment.assigned_at,
                answered.c.last_answer_at,
                QuizSubmission.submitted_at,
                QuizSubmission.marked_at,
            ).label("last_activity_at")
            stmt = (
                select(
                    QuizAssignment.id,
                    Quiz.id,
                    Quiz.subject_code,
                    Quiz.title,
                    Quiz.time_limit_minutes,
                    QuizSubmission.status,
                    Attempt.awarded_marks,
                    Attempt.maximum_marks,
                    func.coalesce(counts.c.n, 0),
                    func.coalesce(answered.c.answered, 0),
                    last_activity,
                )
                .join(Quiz, Quiz.id == QuizAssignment.quiz_id)
                .outerjoin(
                    QuizSubmission,
                    sa.and_(
                        QuizSubmission.assignment_id == QuizAssignment.id,
                        QuizSubmission.student_id == student_uuid,
                    ),
                )
                .outerjoin(answered, answered.c.submission_id == QuizSubmission.id)
                .outerjoin(Attempt, Attempt.id == QuizSubmission.attempt_id)
                .outerjoin(counts, counts.c.quiz_id == Quiz.id)
                .where(
                    QuizAssignment.student_id == student_uuid,
                    Quiz.student_id == student_uuid,
                    Quiz.kind == QuizKind.practice,
                )
                .order_by(sa.desc(last_activity), QuizAssignment.id)
                .limit(limit)
            )
            rows = session.execute(stmt).all()
            topics = _topics_by_quiz(session, [row[1] for row in rows])
            runs: list[PracticeRun] = []
            for (
                assignment_id,
                quiz_id,
                subject_code,
                title,
                time_limit,
                sub_status,
                awarded,
                maximum,
                question_count,
                answered_count,
                activity,
            ) in rows:
                status = _run_status(sub_status, awarded)
                runs.append(
                    PracticeRun(
                        assignment_id=assignment_id,
                        subject_code=subject_code,
                        title=title,
                        topics=topics.get(quiz_id, []),
                        status=status,
                        question_count=int(question_count),
                        answered_count=int(answered_count),
                        awarded_marks=awarded if status == "marked" else None,
                        maximum_marks=maximum if status == "marked" else None,
                        time_limit_minutes=time_limit,
                        last_activity_at=activity,
                    )
                )
            return runs

    def past_papers(self, student_id: uuid.UUID | str, subject_code: str) -> list[PastPaperRow]:
        """Papers for ``subject_code`` the caller can print, or has already done."""
        student_uuid = _as_uuid(student_id)
        with self._sessionmaker() as session:
            servable = (
                select(
                    QuestionBank.paper_id.label("paper_id"), func.count(QuestionBank.id).label("n")
                )
                .where(*_servable_clauses(student_uuid))
                .group_by(QuestionBank.paper_id)
                .subquery()
            )
            stmt = (
                select(Paper, MarkScheme.maximum_mark, func.coalesce(servable.c.n, 0))
                .outerjoin(MarkScheme, MarkScheme.paper_id == Paper.id)
                .outerjoin(servable, servable.c.paper_id == Paper.id)
                .where(Paper.subject_code == subject_code)
            )
            enrolled = enrolled_paper_numbers(session, student_uuid, subject_code)
            if enrolled:
                stmt = stmt.where(Paper.paper_number.in_(enrolled))
            found = session.execute(stmt).all()
            latest = _latest_paper_attempts(
                session, student_uuid, [paper.id for paper, _, _ in found]
            )
            timings = {
                number: (minutes, total)
                for number, minutes, total in session.execute(
                    select(
                        SyllabusPaper.paper_number,
                        SyllabusPaper.duration_minutes,
                        SyllabusPaper.total_marks,
                    ).where(SyllabusPaper.subject_code == subject_code)
                ).all()
            }
            keyed: list[tuple[tuple[int, int, int, int], PastPaperRow]] = []
            for paper, scheme_max, count in found:
                attempt = latest.get(paper.id)
                if int(count) == 0 and attempt is None:
                    continue
                timing = timings.get(paper.paper_number)
                row = PastPaperRow(
                    paper_id=paper.id,
                    subject_code=paper.subject_code,
                    code=_paper_code(paper),
                    paper_number=paper.paper_number,
                    paper_variant=paper.paper_variant,
                    session_label=_session_label(paper.session_month, paper.session_year),
                    duration_minutes=timing[0] if timing else None,
                    total_marks=scheme_max
                    if scheme_max is not None
                    else (timing[1] if timing else None),
                    question_count=int(count),
                    awarded_marks=attempt[0] if attempt else None,
                    maximum_marks=attempt[1] if attempt else None,
                )
                sort_key = (
                    -paper.paper_number,
                    -(paper.session_year or 0),
                    -_MONTH_RANK.get(paper.session_month, 0),
                    paper.paper_variant,
                )
                keyed.append((sort_key, row))
            return [row for _, row in sorted(keyed, key=lambda pair: pair[0])]

    def create_from_paper(
        self, student_id: uuid.UUID | str, paper_id: uuid.UUID | str, *, timed: bool
    ) -> PracticeCreated:
        """Self-assign a practice set made of one past paper's servable questions.

        Raises:
            PracticeNotFoundError: No paper with ``paper_id`` (→ 404).
            PastPaperUnavailableError: The paper has no servable question (→ 409).
        """
        student_uuid = _as_uuid(student_id)
        paper_uuid = _as_uuid(paper_id)
        with self._sessionmaker() as session, session.begin():
            paper = session.get(Paper, paper_uuid)
            if paper is None:
                raise PracticeNotFoundError(f"Unknown paper: {paper_uuid}")
            # The list narrows to the papers the student sits; a made-up id must not get past it.
            # An empty enrolment means "not narrowed" (D4.9), never "sits nothing".
            enrolled = enrolled_paper_numbers(session, student_uuid, paper.subject_code)
            if enrolled and paper.paper_number not in enrolled:
                raise PracticeNotFoundError(f"Unknown paper: {paper_uuid}")
            rows = list(
                session.scalars(
                    select(QuestionBank).where(
                        *_servable_clauses(student_uuid), QuestionBank.paper_id == paper_uuid
                    )
                ).all()
            )
            if not rows:
                raise PastPaperUnavailableError(
                    f"Paper {paper_uuid} has no question we can serve yet"
                )
            rows.sort(key=_question_order)
            duration = (
                session.scalar(
                    select(SyllabusPaper.duration_minutes).where(
                        SyllabusPaper.subject_code == paper.subject_code,
                        SyllabusPaper.paper_number == paper.paper_number,
                    )
                )
                if timed
                else None
            )
            session_label = _session_label(paper.session_month, paper.session_year)
            quiz = Quiz(
                teacher_id=None,
                student_id=student_uuid,
                kind=QuizKind.practice,
                subject_code=paper.subject_code,
                title=f"{_paper_code(paper)} · {session_label}",
                status=QuizStatus.assigned,
                time_limit_minutes=duration,
            )
            session.add(quiz)
            session.flush()
            assignment = QuizAssignment(
                quiz_id=quiz.id, class_id=None, student_id=student_uuid, assigned_by=student_uuid
            )
            session.add(assignment)
            for position, bank_row in enumerate(rows, start=1):
                session.add(
                    _snapshot_bank_row(
                        _to_row(bank_row),
                        quiz_id=quiz.id,
                        question_ref=f"q{position}",
                        position=position,
                    )
                )
            session.flush()
            return PracticeCreated(
                assignment_id=assignment.id,
                quiz_id=quiz.id,
                question_count=len(rows),
                requested_count=len(rows),
                topics=sorted({row.topic for row in rows if row.topic}),
                reason=None,
            )


def _run_status(status: QuizSubmissionStatus | None, awarded: int | None) -> str:
    """``not_started`` when no submission exists. ``marked`` only with a real attempt."""
    if status is None:
        return QuizSubmissionStatus.not_started.value
    if status == QuizSubmissionStatus.marked:
        return "marked" if awarded is not None else QuizSubmissionStatus.submitted.value
    return str(status.value)


def _topics_by_quiz(session: Session, quiz_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[str]]:
    """Each quiz's distinct topics, most frequent first, ties broken by first position."""
    if not quiz_ids:
        return {}
    rows = session.execute(
        select(QuizQuestion.quiz_id, QuizQuestion.topic)
        .where(
            QuizQuestion.quiz_id.in_(quiz_ids),
            QuizQuestion.status == QuizQuestionStatus.included,
            QuizQuestion.topic.is_not(None),
        )
        .order_by(QuizQuestion.quiz_id, QuizQuestion.position)
    ).all()
    ordered: dict[uuid.UUID, list[str]] = {}
    for quiz_id, topic in rows:
        ordered.setdefault(quiz_id, []).append(topic)
    return {quiz_id: _by_frequency(found) for quiz_id, found in ordered.items()}


def _by_frequency(topics: list[str]) -> list[str]:
    counts = Counter(topics)
    first: dict[str, int] = {}
    for index, topic in enumerate(topics):
        first.setdefault(topic, index)
    return sorted(counts, key=lambda topic: (-counts[topic], first[topic]))


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    """Coerce a str/UUID to :class:`uuid.UUID`, raising ``ValueError`` if invalid."""
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Identifier must be a UUID, got {value!r}") from exc


def _servable_clauses(student_uuid: uuid.UUID) -> list[ColumnElement[bool]]:
    """Past-paper bank rows linked to a paper that practice may serve to this caller.

    The same visibility and renderability predicates the generator uses
    (``PracticeService._matching_clauses``), so "printable" never means
    something different here.
    """
    return [
        QuestionBank.is_active.is_(True),
        visible_bank_filter(student_uuid, ()),
        renderable_bank_filter(),
        QuestionBank.source == QuestionSource.past_paper,
        QuestionBank.paper_id.is_not(None),
    ]


def _latest_paper_attempts(
    session: Session, student_uuid: uuid.UUID, paper_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[int, int]]:
    if not paper_ids:
        return {}
    rows = session.execute(
        select(Attempt.paper_id, Attempt.awarded_marks, Attempt.maximum_marks)
        .where(
            Attempt.user_id == student_uuid,
            Attempt.paper_id.in_(paper_ids),
            Attempt.origin == AttemptOrigin.past_paper,
        )
        .order_by(Attempt.recorded_at.desc())
    ).all()
    latest: dict[uuid.UUID, tuple[int, int]] = {}
    for paper_id, awarded, maximum in rows:
        latest.setdefault(paper_id, (awarded, maximum))
    return latest


def _paper_code(paper: Paper) -> str:
    return f"{paper.subject_code}/{paper.paper_number}{paper.paper_variant}"


def _session_label(month: SessionMonth, year: int | None) -> str:
    label = SESSION_MONTH_LABELS[month]
    return f"{label} {year}" if year else label


def _question_order(row: QuestionBank) -> tuple[int, str, str]:
    ref = row.source_question_id or ""
    match = _QUESTION_NUMBER.search(ref)
    return (int(match.group(1)) if match else 10**6, ref, str(row.id))


__all__ = [
    "RUNS_LIMIT_MAX",
    "PastPaperRow",
    "PastPaperUnavailableError",
    "PracticeError",
    "PracticeHubService",
    "PracticeRun",
]
