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

import uuid
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy import func, select

from lemely.db.models.attempts import Attempt
from lemely.db.models.enums import QuizKind, QuizQuestionStatus, QuizSubmissionStatus
from lemely.db.models.quizzes import Quiz, QuizAnswer, QuizAssignment, QuizQuestion, QuizSubmission
from lemely.db.practice_repo import PracticeError

if TYPE_CHECKING:
    from datetime import datetime

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


def _run_status(status: QuizSubmissionStatus | None, awarded: int | None) -> str:
    """``not_started`` when no submission exists. ``marked`` only with a real attempt."""
    if status is None:
        return QuizSubmissionStatus.not_started.value
    if status == QuizSubmissionStatus.marked:
        return "marked" if awarded is not None else QuizSubmissionStatus.submitted.value
    return status.name


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


__all__ = ["RUNS_LIMIT_MAX", "PracticeError", "PracticeHubService", "PracticeRun"]
