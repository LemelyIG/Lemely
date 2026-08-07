"""T-10 class results for one quiz *assignment* (P3.5 chunk F2, ``docs/quiz-model.md`` §4.6).

**Per assignment, never per quiz** (§1.6). A quiz assigned to two classes has
two sets of results; aggregating across them would average two cohorts into a
number that describes neither.

The five panels and their sources are fixed by §4.6 and implemented here as
five projections over *one* load of the assignment's submissions and their
attempts — there is no sixth aggregation path, and every panel is derived
from the same in-memory rows so two panels cannot disagree:

===========================  ==========================================================
panel                        source
===========================  ==========================================================
Completion rate              ``quiz_submissions.status`` vs the **live** roster
Score distribution           ``attempts.percentage`` of the submissions' attempts
Per-question analysis        ``question_results`` grouped by ``question_id``
                             (= ``question_ref``), joined to the ``quiz_questions``
                             snapshot for prompt/topic/difficulty
Per-student results          ``attempts`` + ``question_results.effective_marks``
Class-wide weaknesses        :func:`~lemely.core.class_analytics.rank_topic_weaknesses`
                             over the same ``WeaknessRecord`` rows T-04 reads
===========================  ==========================================================

Three rules a naive implementation gets wrong, each enforced here:

1. **``effective_marks``, never ``awarded_marks``** (§4.6, P3.4's
   single-accessor rule). Every per-question and per-student number below
   reads :attr:`~lemely.db.models.attempts.QuestionResult.effective_marks`, so
   a teacher's own override cannot show on the student's screen and be missing
   from the class view. This also forces Python-side aggregation rather than a
   SQL ``avg()`` — ``effective_marks`` is a property over two columns, and a
   ``avg(awarded_marks)`` would silently ignore every correction.
2. **Percentages, not grades.** The score distribution buckets
   ``attempts.percentage`` in ten-point bands. Quizzes have no grade
   boundaries to bucket by and chunk F1 deliberately leaves
   ``attempts.grade`` NULL for them (D3.9); a grade distribution here would be
   invented precision.
3. **The roster is read live, and it is the denominator.** Submissions are
   created lazily (§1.7), so a snapshotted or pre-seeded denominator drifts
   the moment a student joins or leaves. Everything is therefore scoped to the
   *current* roster; a submission from a student who has since left the class
   is counted nowhere but reported as
   :attr:`CompletionStats.off_roster_submission_count`, so the teacher sees
   that it exists rather than having it silently disappear (D3.10).

Ownership is not re-derived: :meth:`QuizResultsService.assignment_results`
calls :meth:`~lemely.db.quiz_repo.QuizService.get_quiz` for the 404/403
decision and the materialized question snapshot, and
:meth:`~lemely.db.class_repo.ClassService.roster` for the class scope — the
same two seams every other teacher-portal surface uses. There is still no
``school_admin`` view into a quiz (see :mod:`lemely.db.quiz_repo`'s module
docstring); ``caller_role`` reaches ``ClassService`` only.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from lemely.core.class_analytics import rank_topic_weaknesses
from lemely.core.history import StudentHistory
from lemely.db.history_repo import attempt_to_record
from lemely.db.models.attempts import Attempt
from lemely.db.models.enums import QuizQuestionStatus, QuizSubmissionStatus
from lemely.db.models.orgs import SchoolClass
from lemely.db.models.quizzes import QuizAssignment, QuizSubmission
from lemely.db.quiz_repo import QuizAssignmentRow, QuizError, QuizNotFoundError

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.orm import Session, sessionmaker

    from lemely.core.class_analytics import TopicWeakness
    from lemely.core.difficulty import Band
    from lemely.core.history import PaperRecord
    from lemely.db.class_repo import ClassService, RosterEntry
    from lemely.db.models.attempts import QuestionResult
    from lemely.db.models.enums import ConfidenceBand, Role
    from lemely.db.quiz_repo import QuizQuestionRow, QuizService

#: A submission counts toward "completed" once the student has handed it in.
#: ``marked`` is included because marking is asynchronous (chunk F1 runs it on
#: a background thread): a completion rate that only counted ``submitted``
#: would fall as marking succeeded, which is backwards.
_COMPLETED_STATUSES = frozenset({QuizSubmissionStatus.submitted, QuizSubmissionStatus.marked})

#: Ten-point percentage bands, the top one inclusive of 100.
_BUCKET_BOUNDS: tuple[tuple[int, int], ...] = (
    (0, 9),
    (10, 19),
    (20, 29),
    (30, 39),
    (40, 49),
    (50, 59),
    (60, 69),
    (70, 79),
    (80, 89),
    (90, 100),
)


@dataclass(frozen=True, slots=True)
class CompletionStats:
    """Completion against the **live** roster (§4.6 rule (c))."""

    roster_size: int
    completed_count: int
    """Roster students whose submission is ``submitted`` or ``marked``."""
    completion_rate: float | None
    """``completed_count / roster_size``, 0.0-1.0. ``None`` for an empty
    roster — 0/0 is not 0%, and reporting it as 0% would read as "nobody has
    done it" when the truth is "there is nobody to do it"."""
    status_counts: dict[str, int]
    """Every :class:`~lemely.db.models.enums.QuizSubmissionStatus` value →
    count over roster students, zero-filled and summing to ``roster_size``: a
    roster student with no submission row yet is ``not_started`` (rows are
    created lazily, §1.7)."""
    off_roster_submission_count: int
    """Submissions from students no longer on the roster. Excluded from every
    panel — the denominator is the live roster — but surfaced so a teacher
    sees the work exists rather than watching it vanish (D3.10)."""


@dataclass(frozen=True, slots=True)
class ScoreBucket:
    """One ten-point band of the percentage distribution."""

    lower: int
    upper: int
    student_count: int


@dataclass(frozen=True, slots=True)
class QuestionAnalysisRow:
    """One question's class-wide performance, in the quiz's display order.

    Every mark here is an ``effective_marks`` sum (§4.6 rule (a)).
    ``accuracy`` divides by the marks actually *marked*
    (``question_results.maximum_marks``) rather than the snapshot's
    ``total_marks``, so the ratio is self-consistent even if the two ever
    diverge; ``total_marks`` is still reported for display.
    """

    question_ref: str
    position: int
    prompt: str
    topic: str | None
    difficulty: Band
    total_marks: int
    answered_count: int
    """Marked answers for this question across the roster."""
    average_marks: float | None
    """``None`` when nobody has been marked on it yet — not 0.0."""
    accuracy: float | None
    full_marks_count: int
    zero_marks_count: int
    needs_review_count: int
    overridden_count: int
    """Answers a teacher has already corrected — the T-07/T-08 audit trail
    made visible in the class view."""


@dataclass(frozen=True, slots=True)
class StudentResultRow:
    """One roster student's result, whether or not they have submitted."""

    student_id: uuid.UUID
    display_name: str
    status: QuizSubmissionStatus
    submitted_at: datetime | None
    marked_at: datetime | None
    awarded_marks: int | None
    maximum_marks: int | None
    percentage: float | None
    confidence_band: ConfidenceBand | None
    needs_teacher_review: bool
    marks_by_question: dict[str, int]
    """``question_ref`` → ``effective_marks``. Empty until marking lands."""
    marking_error: str | None
    """Set when marking failed for this submission (F1 leaves the row
    ``submitted``-but-unmarked rather than silently dropping it)."""


@dataclass(frozen=True, slots=True)
class QuizAssignmentResults:
    """T-10's whole payload for one assignment: the five §4.6 panels plus a header."""

    assignment: QuizAssignmentRow
    quiz_title: str
    subject_code: str
    question_count: int
    total_marks: int
    completion: CompletionStats
    average_percentage: float | None
    median_percentage: float | None
    score_distribution: list[ScoreBucket]
    question_analysis: list[QuestionAnalysisRow]
    students: list[StudentResultRow]
    topic_weaknesses: list[TopicWeakness]


class QuizResultsService:
    """T-10 aggregation for one quiz assignment.

    Composes :class:`~lemely.db.quiz_repo.QuizService` (ownership + the
    materialized question snapshot) and
    :class:`~lemely.db.class_repo.ClassService` (the live roster) rather than
    re-deriving either — see the module docstring.
    """

    def __init__(
        self,
        sessionmaker: sessionmaker[Session],
        quiz_service: QuizService,
        class_service: ClassService,
    ) -> None:
        """Wire the service to its collaborators."""
        self._sessionmaker = sessionmaker
        self._quiz_service = quiz_service
        self._class_service = class_service

    def assignment_results(
        self,
        teacher_id: uuid.UUID | str,
        caller_role: Role | str,
        quiz_id: uuid.UUID | str,
        assignment_id: uuid.UUID | str,
    ) -> QuizAssignmentResults:
        """Aggregate one assignment's results across the five §4.6 panels.

        Raises:
            QuizNotFoundError: No quiz exists with ``quiz_id``, or no
                assignment exists with ``assignment_id`` *on this quiz* (404).
            QuizOwnershipError: The quiz is not the caller's (403) —
                propagated unchanged from
                :meth:`~lemely.db.quiz_repo.QuizService.get_quiz`.
            ClassNotFoundError: The assignment's class no longer exists (404)
                — propagated unchanged from
                :class:`~lemely.db.class_repo.ClassService`.
            ClassOwnershipError: The class is outside the caller's scope (403)
                — propagated unchanged, same rule.
        """
        quiz_uuid = _as_uuid(quiz_id)
        assignment_uuid = _as_uuid(assignment_id)
        # Ownership first: a caller who does not own the quiz must not be able
        # to probe which assignment ids exist.
        detail = self._quiz_service.get_quiz(teacher_id, quiz_uuid)
        questions = sorted(
            (q for q in detail.questions if q.status == QuizQuestionStatus.included),
            key=lambda q: q.position,
        )

        with self._sessionmaker() as session:
            assignment = session.get(QuizAssignment, assignment_uuid)
            if assignment is None or assignment.quiz_id != quiz_uuid:
                raise QuizNotFoundError(f"Unknown assignment: {assignment_uuid}")
            school_class = session.get(SchoolClass, assignment.class_id)
            if school_class is None:  # pragma: no cover - FK guarantees the row exists
                raise QuizError(f"Unknown class: {assignment.class_id}")
            class_name = school_class.name
            class_id = assignment.class_id
            due_at = assignment.due_at
            closes_at = assignment.closes_at
            assigned_at = assignment.assigned_at
            assigned_by = assignment.assigned_by
            submissions = list(
                session.scalars(
                    select(QuizSubmission).where(QuizSubmission.assignment_id == assignment_uuid)
                ).all()
            )
            attempts_by_id = _load_attempts(
                session, [s.attempt_id for s in submissions if s.attempt_id is not None]
            )

        # Live roster, never a snapshot (§1.7 / §4.6 rule (c)). Read after the
        # session closes: ClassService opens its own.
        roster = self._class_service.roster(teacher_id, caller_role, class_id)
        roster_ids = {entry.student_id for entry in roster}
        submission_by_student = {s.student_id: s for s in submissions}

        completion = _completion_stats(roster, submissions, roster_ids)
        students = _student_rows(roster, submission_by_student, attempts_by_id)
        # Iterated in roster order (not over the id set) so every downstream
        # projection is deterministic.
        roster_attempts = [
            attempts_by_id[sub.attempt_id]
            for entry in roster
            if (sub := submission_by_student.get(entry.student_id)) is not None
            and sub.attempt_id is not None
            and sub.attempt_id in attempts_by_id
        ]
        percentages = sorted(attempt.percentage for attempt in roster_attempts)

        return QuizAssignmentResults(
            assignment=QuizAssignmentRow(
                assignment_id=assignment_uuid,
                quiz_id=quiz_uuid,
                class_id=class_id,
                class_name=class_name,
                assigned_by=assigned_by,
                assigned_at=assigned_at,
                due_at=due_at,
                closes_at=closes_at,
                roster_size=len(roster),
                submission_counts=completion.status_counts,
            ),
            quiz_title=detail.quiz.title,
            subject_code=detail.quiz.subject_code,
            question_count=len(questions),
            total_marks=sum(q.total_marks for q in questions),
            completion=completion,
            average_percentage=(
                round(sum(percentages) / len(percentages), 2) if percentages else None
            ),
            median_percentage=_median(percentages),
            score_distribution=_score_distribution(percentages),
            question_analysis=_question_analysis(questions, roster_attempts),
            students=students,
            topic_weaknesses=_topic_weaknesses(roster_attempts),
        )


# ---------------------------------------------------------------------------
# Panel projections. Pure functions over already-loaded rows — no I/O, so each
# panel is unit-testable on its own and none of them can issue a stray query.
# ---------------------------------------------------------------------------


def _load_attempts(session: Session, attempt_ids: list[uuid.UUID]) -> dict[uuid.UUID, Attempt]:
    """Load the submissions' attempts with their result and weakness rows eagerly.

    ``selectinload`` is not an optimisation here but a correctness
    requirement: every projection below runs *after* the session closes, and
    lazy-loading ``question_results``/``weakness_records`` at that point would
    raise ``DetachedInstanceError``.
    """
    if not attempt_ids:
        return {}
    attempts = session.scalars(
        select(Attempt)
        .where(Attempt.id.in_(attempt_ids))
        .options(
            selectinload(Attempt.question_results),
            selectinload(Attempt.weakness_records),
        )
    ).all()
    return {attempt.id: attempt for attempt in attempts}


def _completion_stats(
    roster: list[RosterEntry],
    submissions: list[QuizSubmission],
    roster_ids: set[uuid.UUID],
) -> CompletionStats:
    """Completion against the live roster, with off-roster work reported not dropped."""
    status_counts = {status.value: 0 for status in QuizSubmissionStatus}
    by_student = {s.student_id: s for s in submissions}
    completed = 0
    for entry in roster:
        submission = by_student.get(entry.student_id)
        status = submission.status if submission is not None else QuizSubmissionStatus.not_started
        status_counts[status.value] += 1
        if status in _COMPLETED_STATUSES:
            completed += 1
    off_roster = sum(1 for s in submissions if s.student_id not in roster_ids)
    return CompletionStats(
        roster_size=len(roster),
        completed_count=completed,
        completion_rate=round(completed / len(roster), 4) if roster else None,
        status_counts=status_counts,
        off_roster_submission_count=off_roster,
    )


def _student_rows(
    roster: list[RosterEntry],
    submission_by_student: dict[uuid.UUID, QuizSubmission],
    attempts_by_id: dict[uuid.UUID, Attempt],
) -> list[StudentResultRow]:
    """One row per roster student, in roster order, submitted or not."""
    rows: list[StudentResultRow] = []
    for entry in roster:
        submission = submission_by_student.get(entry.student_id)
        attempt = (
            attempts_by_id.get(submission.attempt_id)
            if submission is not None and submission.attempt_id is not None
            else None
        )
        marks_by_question = (
            {result.question_id: result.effective_marks for result in attempt.question_results}
            if attempt is not None
            else {}
        )
        rows.append(
            StudentResultRow(
                student_id=entry.student_id,
                display_name=entry.display_name,
                status=(
                    submission.status
                    if submission is not None
                    else QuizSubmissionStatus.not_started
                ),
                submitted_at=submission.submitted_at if submission is not None else None,
                marked_at=submission.marked_at if submission is not None else None,
                awarded_marks=attempt.awarded_marks if attempt is not None else None,
                maximum_marks=attempt.maximum_marks if attempt is not None else None,
                percentage=attempt.percentage if attempt is not None else None,
                confidence_band=attempt.confidence_band if attempt is not None else None,
                needs_teacher_review=attempt.needs_teacher_review if attempt is not None else False,
                marks_by_question=marks_by_question,
                marking_error=submission.marking_error if submission is not None else None,
            )
        )
    return rows


def _score_distribution(percentages: list[float]) -> list[ScoreBucket]:
    """Bucket percentages into ten-point bands — never grades (§4.6 rule (b))."""
    counts = [0] * len(_BUCKET_BOUNDS)
    for percentage in percentages:
        # Clamped both ways: min() keeps 100.0 (and any float overshoot) in
        # the top band rather than off the end of the list.
        index = min(int(percentage // 10), len(_BUCKET_BOUNDS) - 1)
        counts[max(index, 0)] += 1
    return [
        ScoreBucket(lower=lower, upper=upper, student_count=count)
        for (lower, upper), count in zip(_BUCKET_BOUNDS, counts, strict=True)
    ]


def _question_analysis(
    questions: list[QuizQuestionRow], attempts: list[Attempt]
) -> list[QuestionAnalysisRow]:
    """Per-question class performance, aggregating ``effective_marks`` (§4.6 rule (a))."""
    results_by_ref: dict[str, list[QuestionResult]] = {}
    for attempt in attempts:
        for result in attempt.question_results:
            results_by_ref.setdefault(result.question_id, []).append(result)

    rows: list[QuestionAnalysisRow] = []
    for question in questions:
        results = results_by_ref.get(question.question_ref, [])
        answered = len(results)
        earned = sum(result.effective_marks for result in results)
        available = sum(result.maximum_marks for result in results)
        rows.append(
            QuestionAnalysisRow(
                question_ref=question.question_ref,
                position=question.position,
                prompt=question.prompt,
                topic=question.topic,
                difficulty=question.difficulty,
                total_marks=question.total_marks,
                answered_count=answered,
                average_marks=round(earned / answered, 2) if answered else None,
                accuracy=round(earned / available, 4) if available else None,
                full_marks_count=sum(
                    1
                    for result in results
                    if result.maximum_marks > 0 and result.effective_marks >= result.maximum_marks
                ),
                zero_marks_count=sum(1 for result in results if result.effective_marks == 0),
                needs_review_count=sum(1 for result in results if result.needs_teacher_review),
                overridden_count=sum(1 for result in results if result.is_overridden),
            )
        )
    return rows


def _topic_weaknesses(attempts: list[Attempt]) -> list[TopicWeakness]:
    """Rank this assignment's topics by marks lost, reusing T-04's ranking function.

    The attempts are projected through
    :func:`~lemely.db.history_repo.attempt_to_record` — the same projection
    the history store uses — and grouped into one
    :class:`~lemely.core.history.StudentHistory` per student, so
    :func:`~lemely.core.class_analytics.rank_topic_weaknesses` sees exactly
    the shape it sees on the T-04 path. The only difference is scope: these
    are just this assignment's attempts, not the students' whole history.
    """
    records_by_student: dict[str, list[PaperRecord]] = {}
    for attempt in attempts:
        student_id = str(attempt.user_id)
        records_by_student.setdefault(student_id, []).append(attempt_to_record(student_id, attempt))
    histories = [
        StudentHistory(student_id=student_id, records=records)
        for student_id, records in sorted(records_by_student.items())
    ]
    return rank_topic_weaknesses(histories)


def _median(values: list[float]) -> float | None:
    """Median of an already-sorted list, or ``None`` when it is empty."""
    if not values:
        return None
    midpoint = len(values) // 2
    if len(values) % 2:
        return round(values[midpoint], 2)
    return round((values[midpoint - 1] + values[midpoint]) / 2, 2)


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    """Coerce a path parameter to ``UUID``; a malformed id is a 422, not a 500."""
    return value if isinstance(value, uuid.UUID) else uuid.UUID(value)


__all__ = [
    "CompletionStats",
    "QuestionAnalysisRow",
    "QuizAssignmentResults",
    "QuizResultsService",
    "ScoreBucket",
    "StudentResultRow",
]
