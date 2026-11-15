"""Read-only queries the student Home needs and no other repo answers (lane L1).

One question today: which of my answers did a teacher check recently? The
teacher review queue (:mod:`lemely.db.review_repo`) is teacher-scoped by
design, so this is a separate, student-scoped read rather than a widening of
that service's tenancy rules.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import select

from lemely.db.models import User
from lemely.db.models.attempts import Attempt, QuestionResult
from lemely.db.models.enums import ReviewStatus
from lemely.db.models.ops import ReviewQueueItem

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.orm import Session, sessionmaker

_FALLBACK_TEACHER = "Your teacher"


@dataclass(frozen=True, slots=True)
class TeacherReplyRow:
    """One resolved review item on the student's own answer."""

    review_id: uuid.UUID
    attempt_id: uuid.UUID
    teacher_name: str
    question_id: str
    subject_code: str | None
    paper_number: int | None
    marks_added: int
    resolved_at: datetime


class StudentHomeReads:
    """Student-scoped reads for ``GET /api/student/home``."""

    def __init__(self, sessionmaker: sessionmaker[Session]) -> None:
        self._sessionmaker = sessionmaker

    def recent_teacher_replies(
        self, student_id: uuid.UUID | str, *, since: datetime, limit: int = 3
    ) -> list[TeacherReplyRow]:
        """Resolved review items on the student's live attempts since ``since``, newest first.

        ``marks_added`` is the teacher's override minus the original mark,
        floored at zero; an accepted mark adds nothing.
        """
        student = student_id if isinstance(student_id, uuid.UUID) else uuid.UUID(student_id)
        query = (
            select(
                ReviewQueueItem.id,
                ReviewQueueItem.attempt_id,
                ReviewQueueItem.resolved_at,
                User.display_name,
                QuestionResult.question_id,
                QuestionResult.awarded_marks,
                QuestionResult.teacher_awarded_marks,
                Attempt.subject_code,
                Attempt.paper_number,
            )
            .join(Attempt, Attempt.id == ReviewQueueItem.attempt_id)
            .join(QuestionResult, QuestionResult.id == ReviewQueueItem.question_result_id)
            .join(User, User.id == ReviewQueueItem.resolved_by)
            .where(
                Attempt.user_id == student,
                Attempt.deleted_at.is_(None),
                ReviewQueueItem.status == ReviewStatus.resolved,
                ReviewQueueItem.resolved_at.is_not(None),
                ReviewQueueItem.resolved_at >= since,
            )
            .order_by(ReviewQueueItem.resolved_at.desc())
            .limit(limit)
        )
        with self._sessionmaker() as session:
            rows = session.execute(query).all()
        replies: list[TeacherReplyRow] = []
        for row in rows:
            override = row.teacher_awarded_marks
            added = max(0, override - row.awarded_marks) if override is not None else 0
            replies.append(
                TeacherReplyRow(
                    review_id=row.id,
                    attempt_id=row.attempt_id,
                    teacher_name=row.display_name or _FALLBACK_TEACHER,
                    question_id=row.question_id,
                    subject_code=row.subject_code,
                    paper_number=row.paper_number,
                    marks_added=added,
                    resolved_at=row.resolved_at,
                )
            )
        return replies
