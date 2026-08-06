"""Student quiz-taking service: assignment discovery, take, answer, submit.

P3.5 chunk E, ``docs/quiz-model.md`` §1.6/§1.7/§1.8, UI-spec §S-26. A separate
service from :class:`~lemely.db.quiz_repo.QuizService` on purpose: quiz
*building* is scoped by ``teacher_id`` ownership; quiz *taking* is scoped by
class **enrolment** — a different tenancy axis entirely, with its own
:class:`ClassEnrollment` seam (:meth:`~lemely.db.class_repo.ClassService.enrolled_class_ids`)
and its own writes (``quiz_submissions``/``quiz_answers``). Mixing the two
into one service would mean every method carries a "which axis am I scoped
on" flag; two services with two narrow contracts is the one-rule-one-place
discipline this codebase has already paid for three times (D3.3/D3.4/D3.5).

**Open / overdue semantics — there is no ``opens_at`` column.**

* ``closed``: the quiz's own status is ``closed``/``archived``, **or**
  ``closes_at`` has passed. A closed assignment cannot be started, saved to,
  or submitted — every mutating method below checks this first.
* ``overdue``: ``due_at`` has passed and the assignment is not closed.
  Overdue is a *flag*, not a block (UI-spec §1.4: "flags are signals, not
  verdicts") — a late-but-not-yet-closed submission is still accepted and
  simply carries the flag.
* S-26's "not yet open" state has no backing column: an assignment does not
  exist until the teacher creates it, so there is nothing to be "not yet
  open" *of*. Do not invent a column for this; the UI state is reachable
  purely from "no assignment found" (404).

**Lazy submission creation (§1.7).** ``quiz_submissions`` rows are never
pre-seeded at assignment time; :meth:`QuizTakingService.get_take` creates one
on first *open* — and only when the quiz is not closed — setting
``status=in_progress``/``started_at``. A second open of the same assignment
must not create a second row or reset ``started_at``; the unique index
``uq_quiz_submissions`` is the backstop, the check-then-create in
:meth:`get_take`/:meth:`save_answer` is the primary path.

**Clock injection.** Both ``now`` comparisons (open/overdue) and the
timestamps this service writes go through an injected zero-arg ``now``
callable (mirrors :class:`~lemely.auth.otp.OtpStore`'s ``clock`` parameter),
so open/overdue/lazy-creation behaviour is testable without sleeping or
mutating the wall clock.

**Never serialises marking material.** ``model_answer``, ``mark_scheme_points``,
and ``mcq_answer`` are never read into any row this service returns — see
:class:`QuizTakeQuestionRow`'s field list, which is a strict subset of
:class:`~lemely.db.quiz_repo.QuizQuestionRow`'s. This is the one way this
chunk can leak answers to a student; keep the field list a subset by
construction, not by remembering to omit three fields at the DTO layer.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from lemely.db.models.enums import QuizQuestionStatus, QuizStatus, QuizSubmissionStatus
from lemely.db.models.orgs import SchoolClass
from lemely.db.models.quizzes import Quiz, QuizAnswer, QuizAssignment, QuizQuestion, QuizSubmission
from lemely.db.models.users import User

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session, sessionmaker

    from lemely.core.difficulty import Band
    from lemely.db.class_repo import ClassService


class QuizTakingError(Exception):
    """Base class for student quiz-taking failures."""


class QuizTakingNotFoundError(QuizTakingError):
    """No assignment exists for the supplied id, anywhere (→ 404)."""


class QuizTakingOwnershipError(QuizTakingError):
    """The assignment exists but the caller is not enrolled in its class (→ 403)."""


class QuizTakingValidationError(QuizTakingError):
    """The requested action is not valid for this assignment/submission (→ 422)."""


def _utcnow() -> datetime:
    """Default clock: aware UTC now. Production wiring only — tests inject their own."""
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class AssignedQuizRow:
    """One row of ``GET /api/student/quizzes`` — an assignment the student can see."""

    assignment_id: uuid.UUID
    quiz_title: str
    subject_code: str
    class_name: str
    teacher_name: str
    assigned_at: datetime
    due_at: datetime | None
    closes_at: datetime | None
    question_count: int
    """``included`` questions only."""
    time_limit_minutes: int | None
    submission_status: QuizSubmissionStatus
    is_open: bool
    is_overdue: bool


@dataclass(frozen=True, slots=True)
class QuizTakeQuestionRow:
    """One question in the take payload (S-26).

    A strict subset of :class:`~lemely.db.quiz_repo.QuizQuestionRow` — no
    ``model_answer``, ``mark_scheme_points``, or ``mcq_answer`` field exists
    here at all, so there is nothing to accidentally serialise (see module
    docstring).
    """

    id: uuid.UUID
    question_ref: str
    position: int
    topic: str | None
    difficulty: Band
    question_type: str
    prompt: str
    total_marks: int
    mcq_options: list[str] | None
    answer_text: str | None
    working_text: str | None
    answered_at: datetime | None


@dataclass(frozen=True, slots=True)
class QuizTakeHeader:
    """The take payload's header block (S-26: teacher, class, due date, ...)."""

    quiz_title: str
    subject_code: str
    class_name: str
    teacher_name: str
    due_at: datetime | None
    closes_at: datetime | None
    time_limit_minutes: int | None
    submission_status: QuizSubmissionStatus
    is_open: bool
    is_overdue: bool
    unanswered_count: int


@dataclass(frozen=True, slots=True)
class QuizTakeDetail:
    """Full response for ``GET /api/student/quizzes/{assignment_id}``."""

    header: QuizTakeHeader
    questions: list[QuizTakeQuestionRow]


@dataclass(frozen=True, slots=True)
class QuizAnswerRow:
    """Response for a single answer auto-save."""

    question_ref: str
    answer_text: str | None
    working_text: str | None
    answered_at: datetime | None


@dataclass(frozen=True, slots=True)
class SubmitResultRow:
    """Response for ``POST /api/student/quizzes/{assignment_id}/submit``.

    ``attempt_id`` stays NULL on the underlying row and the status stops at
    ``submitted`` — chunk F's ``QuizMarkingService`` is what advances it to
    ``marked``. Nothing here stubs, fakes, or pre-empts that.
    """

    submission_status: QuizSubmissionStatus
    answered_count: int
    unanswered_count: int


class QuizTakingService:
    """Student-side quiz discovery/take/save/submit. Scoped by enrolment, not ownership.

    Constructed with a ``sessionmaker``, the same :class:`~lemely.db.class_repo.ClassService`
    singleton every other portal service composes (for
    :meth:`~lemely.db.class_repo.ClassService.enrolled_class_ids` — the single
    seam every method here uses to answer "is this student in this
    assignment's class"), and an injectable clock.
    """

    def __init__(
        self,
        sessionmaker: sessionmaker[Session],
        class_service: ClassService,
        now: Callable[[], datetime] = _utcnow,
    ) -> None:
        """Wire the service to its collaborators and clock."""
        self._sessionmaker = sessionmaker
        self._class_service = class_service
        self._now = now

    # -- Discovery ----------------------------------------------------------

    def list_assigned(self, student_id: uuid.UUID | str) -> list[AssignedQuizRow]:
        """Assignments for classes the student is enrolled in.

        Only quizzes whose status is ``assigned`` or ``closed`` are included
        — a ``draft``/``archived`` quiz was never (or is no longer) a live
        assignment. Newest assigned first.
        """
        student_uuid = _as_uuid(student_id)
        class_ids = self._class_service.enrolled_class_ids(student_uuid)
        if not class_ids:
            return []
        now = self._now()
        with self._sessionmaker() as session:
            stmt = (
                select(QuizAssignment, Quiz, SchoolClass, User)
                .join(Quiz, Quiz.id == QuizAssignment.quiz_id)
                .join(SchoolClass, SchoolClass.id == QuizAssignment.class_id)
                .join(User, User.id == Quiz.teacher_id)
                .where(
                    QuizAssignment.class_id.in_(class_ids),
                    Quiz.status.in_((QuizStatus.assigned, QuizStatus.closed)),
                )
                .order_by(QuizAssignment.assigned_at.desc())
            )
            rows: list[AssignedQuizRow] = []
            for assignment, quiz, school_class, teacher in session.execute(stmt).all():
                question_count = self._included_question_count(session, quiz.id)
                submission = self._find_submission(session, assignment.id, student_uuid)
                closed = _is_closed(quiz.status, assignment.closes_at, now)
                rows.append(
                    AssignedQuizRow(
                        assignment_id=assignment.id,
                        quiz_title=quiz.title,
                        subject_code=quiz.subject_code,
                        class_name=school_class.name,
                        teacher_name=_display_name(teacher),
                        assigned_at=assignment.assigned_at,
                        due_at=assignment.due_at,
                        closes_at=assignment.closes_at,
                        question_count=question_count,
                        time_limit_minutes=quiz.time_limit_minutes,
                        submission_status=(
                            submission.status if submission else QuizSubmissionStatus.not_started
                        ),
                        is_open=not closed,
                        is_overdue=_is_overdue(assignment.due_at, closed, now),
                    )
                )
            return rows

    # -- Take (S-26) ----------------------------------------------------------

    def get_take(
        self, student_id: uuid.UUID | str, assignment_id: uuid.UUID | str
    ) -> QuizTakeDetail:
        """The take payload: header + every ``included`` question, in order.

        Lazily creates the ``quiz_submissions`` row on first open
        (``status=in_progress``, ``started_at=now``) — only when the quiz is
        not closed. A second open of the same assignment reuses the existing
        row untouched (no reset of ``started_at``). A closed quiz is returned
        read-only: no row is created or advanced.

        Raises:
            QuizTakingNotFoundError: No assignment exists with
                ``assignment_id``, anywhere (404).
            QuizTakingOwnershipError: The student is not enrolled in the
                assignment's class (403).
        """
        student_uuid = _as_uuid(student_id)
        assignment_uuid = _as_uuid(assignment_id)
        now = self._now()
        with self._sessionmaker() as session, session.begin():
            assignment = self._load_enrolled(session, student_uuid, assignment_uuid)
            quiz = self._require_quiz(session, assignment.quiz_id)
            school_class = session.get(SchoolClass, assignment.class_id)
            if school_class is None:  # pragma: no cover - FK guarantees the row exists
                raise QuizTakingError(f"Unknown class: {assignment.class_id}")
            teacher = session.get(User, quiz.teacher_id)

            closed = _is_closed(quiz.status, assignment.closes_at, now)
            submission = self._find_submission(
                session, assignment_uuid, student_uuid, for_update=True
            )
            if submission is None and not closed:
                submission = self._create_submission(session, assignment_uuid, student_uuid, now)

            questions = session.scalars(
                select(QuizQuestion)
                .where(
                    QuizQuestion.quiz_id == quiz.id,
                    QuizQuestion.status == QuizQuestionStatus.included,
                )
                .order_by(QuizQuestion.position)
            ).all()
            answers_by_question: dict[uuid.UUID, QuizAnswer] = {}
            if submission is not None:
                answers_by_question = {
                    a.quiz_question_id: a
                    for a in session.scalars(
                        select(QuizAnswer).where(QuizAnswer.submission_id == submission.id)
                    ).all()
                }

            question_rows: list[QuizTakeQuestionRow] = []
            unanswered = 0
            for q in questions:
                answer = answers_by_question.get(q.id)
                answer_text = answer.answer_text if answer is not None else None
                if not answer_text:
                    unanswered += 1
                question_rows.append(
                    QuizTakeQuestionRow(
                        id=q.id,
                        question_ref=q.question_ref,
                        position=q.position,
                        topic=q.topic,
                        difficulty=q.difficulty.value,
                        question_type=q.question_type,
                        prompt=q.prompt,
                        total_marks=q.total_marks,
                        mcq_options=list(q.mcq_options) if q.mcq_options is not None else None,
                        answer_text=answer_text,
                        working_text=answer.working_text if answer is not None else None,
                        answered_at=answer.answered_at if answer is not None else None,
                    )
                )

            submission_status = (
                submission.status if submission is not None else QuizSubmissionStatus.not_started
            )
            header = QuizTakeHeader(
                quiz_title=quiz.title,
                subject_code=quiz.subject_code,
                class_name=school_class.name,
                teacher_name=_display_name(teacher),
                due_at=assignment.due_at,
                closes_at=assignment.closes_at,
                time_limit_minutes=quiz.time_limit_minutes,
                submission_status=submission_status,
                is_open=not closed,
                is_overdue=_is_overdue(assignment.due_at, closed, now),
                unanswered_count=unanswered,
            )
            return QuizTakeDetail(header=header, questions=question_rows)

    # -- Answer autosave --------------------------------------------------------

    def save_answer(
        self,
        student_id: uuid.UUID | str,
        assignment_id: uuid.UUID | str,
        question_ref: str,
        *,
        answer_text: str | None = None,
        working_text: str | None = None,
    ) -> QuizAnswerRow:
        """Upsert one answer, keyed by the stable ``question_ref``.

        ``answer_text``/``working_text`` left as ``None`` (omitted from the
        request) leave the stored value untouched — the same "omission vs
        explicit clear" convention :meth:`~lemely.db.quiz_repo.QuizService.patch_draft`
        uses; pass ``""`` to explicitly clear a field. Creates the submission
        row if the student saves without a prior :meth:`get_take` call.

        Raises:
            QuizTakingNotFoundError: No assignment exists with
                ``assignment_id`` (404).
            QuizTakingOwnershipError: The student is not enrolled in the
                assignment's class (403).
            QuizTakingValidationError: The quiz is closed (422); the
                submission is already ``submitted``/``marked`` (422); or
                ``question_ref`` is not an ``included`` question of this
                quiz (422).
        """
        student_uuid = _as_uuid(student_id)
        assignment_uuid = _as_uuid(assignment_id)
        now = self._now()
        with self._sessionmaker() as session, session.begin():
            assignment = self._load_enrolled(session, student_uuid, assignment_uuid)
            quiz = self._require_quiz(session, assignment.quiz_id)
            if _is_closed(quiz.status, assignment.closes_at, now):
                raise QuizTakingValidationError(
                    f"Assignment {assignment_uuid} is closed; answers can no longer be saved"
                )
            qq = session.scalars(
                select(QuizQuestion).where(
                    QuizQuestion.quiz_id == quiz.id,
                    QuizQuestion.question_ref == question_ref,
                    QuizQuestion.status == QuizQuestionStatus.included,
                )
            ).first()
            if qq is None:
                raise QuizTakingValidationError(
                    f"No included question {question_ref!r} on this quiz"
                )
            submission = self._find_submission(
                session, assignment_uuid, student_uuid, for_update=True
            )
            if submission is None:
                submission = self._create_submission(session, assignment_uuid, student_uuid, now)
            elif submission.status in (QuizSubmissionStatus.submitted, QuizSubmissionStatus.marked):
                raise QuizTakingValidationError(
                    f"Submission is {submission.status.value}; answers can no longer be saved"
                )

            answer = session.scalars(
                select(QuizAnswer)
                .where(
                    QuizAnswer.submission_id == submission.id,
                    QuizAnswer.quiz_question_id == qq.id,
                )
                .with_for_update()
            ).first()
            if answer is None:
                answer = QuizAnswer(submission_id=submission.id, quiz_question_id=qq.id)
                session.add(answer)
            if answer_text is not None:
                answer.answer_text = answer_text
            if working_text is not None:
                answer.working_text = working_text
            answer.answered_at = now
            try:
                session.flush()
            except IntegrityError as exc:
                # Backstop only (uq_quiz_answers): the select-then-insert
                # above is the primary path.
                raise QuizTakingValidationError(
                    f"Answer for {question_ref!r} already exists; retry the save"
                ) from exc
            return QuizAnswerRow(
                question_ref=question_ref,
                answer_text=answer.answer_text,
                working_text=answer.working_text,
                answered_at=answer.answered_at,
            )

    # -- Submit -----------------------------------------------------------------

    def submit(
        self, student_id: uuid.UUID | str, assignment_id: uuid.UUID | str
    ) -> SubmitResultRow:
        """Submit: ``status=submitted``, ``submitted_at`` set. No marking here.

        ``attempt_id`` stays NULL and the status stops at ``submitted`` —
        chunk F's ``QuizMarkingService`` is what advances it to ``marked``.
        A late-but-not-yet-closed submission is accepted (overdue is a flag,
        not a block, per module docstring); a closed assignment or a second
        submit is rejected.

        Raises:
            QuizTakingNotFoundError: No assignment exists with
                ``assignment_id`` (404).
            QuizTakingOwnershipError: The student is not enrolled in the
                assignment's class (403).
            QuizTakingValidationError: No submission exists yet to submit,
                it is already ``submitted``/``marked``, or the quiz is
                closed (422).
        """
        student_uuid = _as_uuid(student_id)
        assignment_uuid = _as_uuid(assignment_id)
        now = self._now()
        with self._sessionmaker() as session, session.begin():
            assignment = self._load_enrolled(session, student_uuid, assignment_uuid)
            quiz = self._require_quiz(session, assignment.quiz_id)
            submission = self._find_submission(
                session, assignment_uuid, student_uuid, for_update=True
            )
            if submission is None:
                raise QuizTakingValidationError(
                    f"No submission exists for assignment {assignment_uuid}; open the quiz first"
                )
            if submission.status in (QuizSubmissionStatus.submitted, QuizSubmissionStatus.marked):
                raise QuizTakingValidationError(f"Submission is already {submission.status.value}")
            if _is_closed(quiz.status, assignment.closes_at, now):
                raise QuizTakingValidationError(
                    f"Assignment {assignment_uuid} is closed; it can no longer be submitted"
                )
            submission.status = QuizSubmissionStatus.submitted
            submission.submitted_at = now
            session.flush()

            total = self._included_question_count(session, quiz.id)
            answered = (
                session.scalar(
                    select(func.count())
                    .select_from(QuizAnswer)
                    .join(QuizQuestion, QuizQuestion.id == QuizAnswer.quiz_question_id)
                    .where(
                        QuizAnswer.submission_id == submission.id,
                        QuizQuestion.status == QuizQuestionStatus.included,
                        QuizAnswer.answer_text.is_not(None),
                        QuizAnswer.answer_text != "",
                    )
                )
                or 0
            )
            return SubmitResultRow(
                submission_status=submission.status,
                answered_count=int(answered),
                unanswered_count=total - int(answered),
            )

    # -- Internals ----------------------------------------------------------

    def _load_enrolled(
        self, session: Session, student_uuid: uuid.UUID, assignment_uuid: uuid.UUID
    ) -> QuizAssignment:
        """Load an assignment, enforcing the 403-vs-404 split every owner-scoped route uses.

        An assignment id that maps to nothing anywhere is a 404; one that
        exists but whose class the student is not enrolled in is a 403 —
        never data, mirroring :class:`~lemely.db.class_repo.ClassService`'s
        accepted existence-oracle trade-off.
        """
        assignment = session.get(QuizAssignment, assignment_uuid)
        if assignment is None:
            raise QuizTakingNotFoundError(f"Unknown assignment: {assignment_uuid}")
        enrolled_ids = self._class_service.enrolled_class_ids(student_uuid)
        if assignment.class_id not in enrolled_ids:
            raise QuizTakingOwnershipError(
                f"Student {student_uuid} is not enrolled in class {assignment.class_id}"
            )
        return assignment

    def _require_quiz(self, session: Session, quiz_id: uuid.UUID) -> Quiz:
        """Load a quiz by id, defensively.

        A ``QuizAssignment.quiz_id`` FK guarantees the row exists, but the
        checked accessor keeps this module ``assert``-free (production code,
        not a test) rather than trusting that invariant silently.
        """
        quiz = session.get(Quiz, quiz_id)
        if quiz is None:  # pragma: no cover - FK guarantees the row exists
            raise QuizTakingError(f"Unknown quiz: {quiz_id}")
        return quiz

    def _find_submission(
        self,
        session: Session,
        assignment_uuid: uuid.UUID,
        student_uuid: uuid.UUID,
        *,
        for_update: bool = False,
    ) -> QuizSubmission | None:
        stmt = select(QuizSubmission).where(
            QuizSubmission.assignment_id == assignment_uuid,
            QuizSubmission.student_id == student_uuid,
        )
        if for_update:
            stmt = stmt.with_for_update()
        return session.scalars(stmt).first()

    def _create_submission(
        self,
        session: Session,
        assignment_uuid: uuid.UUID,
        student_uuid: uuid.UUID,
        now: datetime,
    ) -> QuizSubmission:
        """Insert the lazily-created submission row (§1.7).

        The caller already ran :meth:`_find_submission` with
        ``for_update=True`` inside the same transaction immediately before
        this is called, so under normal (single-writer-per-row) operation
        this insert cannot race — ``uq_quiz_submissions`` remains the schema
        backstop, but recovering from its violation here would require
        rolling back and re-entering the caller's transaction, which is not
        worth the complexity for a case this design already serializes
        against.
        """
        submission = QuizSubmission(
            assignment_id=assignment_uuid,
            student_id=student_uuid,
            status=QuizSubmissionStatus.in_progress,
            started_at=now,
        )
        session.add(submission)
        session.flush()
        return submission

    def _included_question_count(self, session: Session, quiz_id: uuid.UUID) -> int:
        return (
            session.scalar(
                select(func.count())
                .select_from(QuizQuestion)
                .where(
                    QuizQuestion.quiz_id == quiz_id,
                    QuizQuestion.status == QuizQuestionStatus.included,
                )
            )
            or 0
        )


def _is_closed(quiz_status: QuizStatus, closes_at: datetime | None, now: datetime) -> bool:
    """§'s open/overdue semantics: closed = quiz.status terminal OR ``closes_at`` passed."""
    if quiz_status in (QuizStatus.closed, QuizStatus.archived):
        return True
    return closes_at is not None and closes_at < now


def _is_overdue(due_at: datetime | None, closed: bool, now: datetime) -> bool:
    """A flag, not a block: ``due_at`` passed and the assignment is not closed."""
    if closed or due_at is None:
        return False
    return due_at < now


def _display_name(user: User | None) -> str:
    if user is None:  # pragma: no cover - defensive, FK guarantees a row
        return ""
    return user.display_name or user.email


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    """Coerce a str/UUID to :class:`uuid.UUID`, raising ``ValueError`` if invalid."""
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Identifier must be a UUID, got {value!r}") from exc


__all__ = [
    "AssignedQuizRow",
    "QuizAnswerRow",
    "QuizTakeDetail",
    "QuizTakeHeader",
    "QuizTakeQuestionRow",
    "QuizTakingError",
    "QuizTakingNotFoundError",
    "QuizTakingOwnershipError",
    "QuizTakingService",
    "QuizTakingValidationError",
    "SubmitResultRow",
]
