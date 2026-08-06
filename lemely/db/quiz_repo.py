"""Quiz-builder service: CRUD, draft PATCH, status lifecycle, question materialization, pool-count.

P3.5 chunk D, ``docs/quiz-model.md`` §1.4/§1.5/§2/§3. Mirrors
:mod:`lemely.db.class_repo`'s / :mod:`lemely.db.review_repo`'s shape: pure
ownership/mutation logic over a ``sessionmaker``, domain errors mapped to
HTTP status codes by a thin router layer, testable against Postgres with no
GoTrue dependency.

**Ownership is strictly per-teacher.** Unlike :class:`~lemely.db.class_repo.ClassService`
(which also grants ``school_admin`` a read/roster-management view), a quiz
belongs to exactly the teacher who built it — ``docs/quiz-model.md`` names no
school_admin exception, and the brief is explicit: "a teacher may only see
and mutate their own quizzes." So every method here takes a single
``teacher_id`` (no ``role`` parameter) and checks ``Quiz.teacher_id ==
teacher_id`` directly; there is no broader-scope path to bypass.

**Question selection never writes a second ``WHERE`` clause for the bank.**
:meth:`QuizService.generate_questions` and :meth:`QuizService.pool_count`
both call :class:`~lemely.db.question_bank_repo.QuestionBankService`'s
``count_by_band``/``select_questions``/``has_inferred_difficulty`` — the
methods that already share :meth:`~lemely.db.question_bank_repo.QuestionBankService._filters`
— so a count the pool-count endpoint reports and the quiz the builder
actually materializes can never disagree (``docs/quiz-model.md`` §1.3's
"count of 40, quiz of 12" failure mode).

**Materialized questions are copied, never referenced** (§1.5):
:meth:`QuizService.generate_questions` snapshots every field off the selected
:class:`~lemely.db.question_bank_repo.QuestionBankRow` onto the new
:class:`~lemely.db.models.quizzes.QuizQuestion` row; ``question_bank_id`` is
kept as provenance only. ``question_ref`` is assigned once at insert
(``"q1"..."qN"``, tracking the highest existing index so repeated
materialization calls top up rather than collide) and is never renumbered —
:meth:`QuizService.remove_question` marks a row ``removed`` in place rather
than deleting it, so the remaining refs never shift.

**The status lifecycle never runs backwards** (§1.4): ``draft -> assigned ->
closed -> archived``, plus ``draft -> archived``. A quiz that is not a draft
must not have its questions edited — :meth:`QuizService.generate_questions`
and :meth:`QuizService.remove_question` both re-check ``status == draft``
before touching a single ``QuizQuestion`` row, the same guard
:meth:`QuizService.patch_draft` applies to the quiz's own fields. This is
what "editing a live quiz under students mid-attempt" (the failure §1.4
forbids) is prevented by.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from lemely.core.difficulty import allocate_difficulty
from lemely.core.history import GRADE_ORDER
from lemely.db.models.enums import (
    QuestionDifficulty,
    QuestionSource,
    QuizQuestionStatus,
    QuizStatus,
    QuizSubmissionStatus,
)
from lemely.db.models.orgs import SchoolClass
from lemely.db.models.quizzes import Quiz, QuizAssignment, QuizQuestion, QuizSubmission

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from sqlalchemy.orm import Session, sessionmaker

    from lemely.core.difficulty import Band
    from lemely.db.class_repo import ClassService
    from lemely.db.models.enums import Role
    from lemely.db.question_bank_repo import QuestionBankRow, QuestionBankService


class QuizError(Exception):
    """Base class for quiz-model failures."""


class QuizNotFoundError(QuizError):
    """No quiz exists for the supplied id (→ 404)."""


class QuizOwnershipError(QuizError):
    """The caller does not own the target quiz (→ 403)."""


class QuizValidationError(QuizError):
    """The requested mutation is not valid for this quiz (→ 422)."""


#: §1.4's lifecycle: ``draft -> assigned -> closed -> archived``, plus
#: ``draft -> archived`` (an abandoned draft). No transition ever goes
#: backwards; every other pair (including any status to itself) is rejected.
_ALLOWED_TRANSITIONS: dict[QuizStatus, frozenset[QuizStatus]] = {
    QuizStatus.draft: frozenset({QuizStatus.assigned, QuizStatus.archived}),
    QuizStatus.assigned: frozenset({QuizStatus.closed}),
    QuizStatus.closed: frozenset({QuizStatus.archived}),
    QuizStatus.archived: frozenset(),
}


@dataclass(frozen=True, slots=True)
class QuizRow:
    """One quiz, draft or otherwise — the builder's resumable state (§1.4)."""

    quiz_id: uuid.UUID
    teacher_id: uuid.UUID
    school_id: uuid.UUID | None
    subject_code: str
    title: str
    status: QuizStatus
    target_grade: str | None
    included_topics: list[str]
    pool_source: QuestionSource | None
    requested_count: int | None
    time_limit_minutes: int | None
    builder_step: int
    question_count: int
    """Count of ``included`` (not ``removed``) materialized questions."""


@dataclass(frozen=True, slots=True)
class QuizQuestionRow:
    """One materialized quiz question — the frozen snapshot (§1.5)."""

    id: uuid.UUID
    question_bank_id: uuid.UUID | None
    question_ref: str
    position: int
    status: QuizQuestionStatus
    replaced_by_id: uuid.UUID | None
    topic: str | None
    difficulty: Band
    question_type: str
    prompt: str
    model_answer: str | None
    mark_scheme_points: list[str]
    mcq_options: list[str] | None
    mcq_answer: str | None
    total_marks: int


@dataclass(frozen=True, slots=True)
class QuizDetail:
    """A quiz plus every materialized question row.

    Includes both ``included`` and ``removed`` rows — the removed rows are
    the audit trail §1.5 keeps rather than deletes.
    """

    quiz: QuizRow
    questions: list[QuizQuestionRow]


@dataclass(frozen=True, slots=True)
class QuestionGenerationResult:
    """Outcome of materializing a quiz's question set from the bank (§3)."""

    created: list[QuizQuestionRow]
    shortfall: dict[Band, int]
    """Band -> how many fewer than :func:`~lemely.core.difficulty.allocate_difficulty`
    asked for were actually available. Empty when every band was fully met."""


@dataclass(frozen=True, slots=True)
class PoolCountResult:
    """T-09 step 4's live pool-count response (§2)."""

    matching: int
    """Total visible, active rows matching subject/topics/source — every
    band, not just the ones the current allocation needs."""
    requested: int
    by_band: dict[Band, int]
    """The allocation :meth:`QuizService.generate_questions` will use for an
    identical ``(target_grade, requested_count)`` pair — never availability."""
    shortfall: dict[Band, int] | None
    """Band -> how many short of ``by_band`` the visible bank actually has.
    ``None`` (not an empty dict) when nothing is short — a real absence, not
    a degenerate present-but-empty case the wire format has to special-case."""
    difficulty_estimated: bool
    """True when the matching set contains any ``inferred_from_marks`` row
    (§3.2) — the UI must then label the count as an estimate."""


@dataclass(frozen=True, slots=True)
class QuizAssignmentRow:
    """A quiz handed to a class (§1.6) — the teacher-facing assignment view.

    ``roster_size`` and ``submission_counts`` are computed live at read time
    (never a frozen snapshot, per §1.7's completion-rate rule): the former via
    :meth:`~lemely.db.class_repo.ClassService.roster`, the latter by grouping
    this assignment's ``quiz_submissions`` rows by status. ``submission_counts``
    always carries all four :class:`~lemely.db.models.enums.QuizSubmissionStatus`
    keys, zero-filled — never a partial map a caller has to defensively probe.
    """

    assignment_id: uuid.UUID
    quiz_id: uuid.UUID
    class_id: uuid.UUID
    class_name: str
    assigned_by: uuid.UUID
    assigned_at: datetime
    due_at: datetime | None
    closes_at: datetime | None
    roster_size: int
    submission_counts: dict[str, int]


class QuizService:
    """Quiz CRUD, draft PATCH, status transitions, question materialization, pool-count.

    Constructed with a ``sessionmaker`` plus the two collaborators this
    service composes rather than re-deriving: :class:`~lemely.db.class_repo.ClassService`
    (for :meth:`~lemely.db.class_repo.ClassService.member_school_ids`, the
    school tier of bank visibility) and :class:`~lemely.db.question_bank_repo.QuestionBankService`
    (every bank read/count/select).
    """

    def __init__(
        self,
        sessionmaker: sessionmaker[Session],
        class_service: ClassService,
        question_bank_service: QuestionBankService,
    ) -> None:
        """Wire the service to its collaborators."""
        self._sessionmaker = sessionmaker
        self._class_service = class_service
        self._bank = question_bank_service

    # -- CRUD -----------------------------------------------------------------

    def create_quiz(self, teacher_id: uuid.UUID | str, subject_code: str, title: str) -> QuizRow:
        """Create a draft quiz (``status=draft``, ``builder_step=1``).

        Every step-2/3/4 field is nullable and left unset (§1.4) — a
        half-filled draft is a legal row from the moment it exists.
        """
        teacher_uuid = _as_uuid(teacher_id)
        with self._sessionmaker() as session, session.begin():
            quiz = Quiz(teacher_id=teacher_uuid, subject_code=subject_code, title=title)
            session.add(quiz)
            session.flush()
            return self._to_quiz_row(session, quiz)

    def list_quizzes(self, teacher_id: uuid.UUID | str) -> list[QuizRow]:
        """Return every quiz the caller owns, most recently created first."""
        teacher_uuid = _as_uuid(teacher_id)
        with self._sessionmaker() as session:
            rows = session.scalars(
                select(Quiz).where(Quiz.teacher_id == teacher_uuid).order_by(Quiz.created_at.desc())
            ).all()
            return [self._to_quiz_row(session, quiz) for quiz in rows]

    def get_quiz(self, teacher_id: uuid.UUID | str, quiz_id: uuid.UUID | str) -> QuizDetail:
        """Return one owned quiz plus every materialized question row.

        Raises:
            QuizNotFoundError: No quiz exists with ``quiz_id`` (404).
            QuizOwnershipError: The quiz exists but is not the caller's (403).
        """
        teacher_uuid = _as_uuid(teacher_id)
        quiz_uuid = _as_uuid(quiz_id)
        with self._sessionmaker() as session:
            quiz = self._load_owned(session, teacher_uuid, quiz_uuid)
            questions = session.scalars(
                select(QuizQuestion)
                .where(QuizQuestion.quiz_id == quiz_uuid)
                .order_by(QuizQuestion.position)
            ).all()
            return QuizDetail(
                quiz=self._to_quiz_row(session, quiz),
                questions=[_to_question_row(q) for q in questions],
            )

    def patch_draft(
        self,
        teacher_id: uuid.UUID | str,
        quiz_id: uuid.UUID | str,
        *,
        title: str | None = None,
        target_grade: str | None = None,
        included_topics: list[str] | None = None,
        pool_source: QuestionSource | None = None,
        requested_count: int | None = None,
        time_limit_minutes: int | None = None,
        builder_step: int | None = None,
    ) -> QuizRow:
        """Partial-update a draft quiz's step-2/3/4 fields.

        §1.4's "PATCH on an existing row" — how a half-filled draft
        round-trips. Every keyword argument omitted (``None``) leaves the stored value
        untouched — mirrors ``ClassService.update_class``'s convention.
        ``includedTopics`` can still be cleared by passing ``[]`` explicitly
        (distinguishable from omission, unlike the scalar fields).

        Raises:
            QuizNotFoundError: No quiz exists with ``quiz_id`` (404).
            QuizOwnershipError: The quiz is not the caller's (403).
            QuizValidationError: The quiz is not a draft (422), or
                ``target_grade``/``requested_count``/``time_limit_minutes``
                is out of range (422).
        """
        teacher_uuid = _as_uuid(teacher_id)
        quiz_uuid = _as_uuid(quiz_id)
        if target_grade is not None and target_grade not in GRADE_ORDER:
            raise QuizValidationError(f"Unknown target grade: {target_grade!r}")
        if requested_count is not None and requested_count < 0:
            raise QuizValidationError("requested_count must be >= 0")
        if time_limit_minutes is not None and time_limit_minutes <= 0:
            raise QuizValidationError("time_limit_minutes must be > 0")
        with self._sessionmaker() as session, session.begin():
            quiz = self._load_owned(session, teacher_uuid, quiz_uuid, for_update=True)
            if quiz.status != QuizStatus.draft:
                raise QuizValidationError(
                    f"Quiz {quiz_uuid} is not a draft (status={quiz.status.value}); "
                    "duplicate it into a new draft to change its fields"
                )
            if title is not None:
                quiz.title = title
            if target_grade is not None:
                quiz.target_grade = target_grade
            if included_topics is not None:
                quiz.included_topics = list(included_topics)
            if pool_source is not None:
                quiz.pool_source = pool_source
            if requested_count is not None:
                quiz.requested_count = requested_count
            if time_limit_minutes is not None:
                quiz.time_limit_minutes = time_limit_minutes
            if builder_step is not None:
                quiz.builder_step = builder_step
            session.flush()
            return self._to_quiz_row(session, quiz)

    def set_status(
        self, teacher_id: uuid.UUID | str, quiz_id: uuid.UUID | str, new_status: QuizStatus
    ) -> QuizRow:
        """Transition a quiz's status, enforcing §1.4's one-way lifecycle.

        Raises:
            QuizNotFoundError: No quiz exists with ``quiz_id`` (404).
            QuizOwnershipError: The quiz is not the caller's (403).
            QuizValidationError: ``new_status`` is not reachable from the
                quiz's current status (422) — never backwards, never a
                same-status no-op.
        """
        teacher_uuid = _as_uuid(teacher_id)
        quiz_uuid = _as_uuid(quiz_id)
        with self._sessionmaker() as session, session.begin():
            quiz = self._load_owned(session, teacher_uuid, quiz_uuid, for_update=True)
            allowed = _ALLOWED_TRANSITIONS.get(quiz.status, frozenset())
            if new_status not in allowed:
                raise QuizValidationError(
                    f"Cannot transition quiz {quiz_uuid} from {quiz.status.value} "
                    f"to {new_status.value}"
                )
            quiz.status = new_status
            session.flush()
            return self._to_quiz_row(session, quiz)

    # -- Question materialization (§1.5, §3) -----------------------------------

    def generate_questions(
        self, teacher_id: uuid.UUID | str, quiz_id: uuid.UUID | str
    ) -> QuestionGenerationResult:
        """Materialize the quiz's question set from the bank into ``quiz_questions``.

        Allocates ``quiz.requested_count`` across bands with
        :func:`~lemely.core.difficulty.allocate_difficulty` (the identical
        call :meth:`pool_count` makes for the same ``(target_grade,
        requested_count)`` pair), then fills each band with
        :meth:`~lemely.db.question_bank_repo.QuestionBankService.select_questions`
        — never a second, hand-written selection query (§1.3). Every field on
        the resulting :class:`~lemely.db.models.quizzes.QuizQuestion` is
        copied off the selected bank row (§1.5's snapshot rule);
        ``question_bank_id`` is kept as provenance only.

        **Additive, not idempotent-replace**: calling this again after
        raising ``requestedCount`` tops the set up (new ``question_ref``s
        continue from the highest already assigned) rather than clearing and
        rebuilding it — a teacher increasing the count mid-draft must not
        lose curation already done on the questions already materialized.

        A band the bank cannot fully supply is *not* padded from another
        band (§3: "a shortfall per band rather than silently substituting")
        — :attr:`QuestionGenerationResult.shortfall` names exactly which
        bands and by how much.

        Raises:
            QuizNotFoundError: No quiz exists with ``quiz_id`` (404).
            QuizOwnershipError: The quiz is not the caller's (403).
            QuizValidationError: The quiz is not a draft (422, "a quiz that
                is not a draft must not have its questions edited"), or has
                no ``pool_source`` selected yet (422).
        """
        teacher_uuid = _as_uuid(teacher_id)
        quiz_uuid = _as_uuid(quiz_id)
        school_ids = self._class_service.member_school_ids(teacher_uuid)
        with self._sessionmaker() as session, session.begin():
            quiz = self._load_owned(session, teacher_uuid, quiz_uuid, for_update=True)
            if quiz.status != QuizStatus.draft:
                raise QuizValidationError(
                    f"Quiz {quiz_uuid} is not a draft (status={quiz.status.value}); "
                    "its questions cannot be edited"
                )
            if quiz.pool_source is None:
                raise QuizValidationError(f"Quiz {quiz_uuid} has no pool source selected yet")

            existing_refs = session.scalars(
                select(QuizQuestion.question_ref).where(QuizQuestion.quiz_id == quiz_uuid)
            ).all()
            next_index = _next_ref_index(existing_refs)
            next_position = _next_position(session, quiz_uuid)

            allocation = allocate_difficulty(quiz.target_grade, quiz.requested_count or 0)
            created: list[QuizQuestion] = []
            shortfall: dict[Band, int] = {}
            for band, needed in allocation.items():
                if needed <= 0:
                    continue
                rows = self._bank.select_questions(
                    teacher_uuid,
                    school_ids,
                    subject_code=quiz.subject_code,
                    band=band,
                    count=needed,
                    topics=list(quiz.included_topics) or None,
                    source=quiz.pool_source,
                )
                if len(rows) < needed:
                    shortfall[band] = needed - len(rows)
                for bank_row in rows:
                    qq = _snapshot_bank_row(
                        bank_row,
                        quiz_id=quiz_uuid,
                        question_ref=f"q{next_index}",
                        position=next_position,
                    )
                    session.add(qq)
                    created.append(qq)
                    next_index += 1
                    next_position += 1
            session.flush()
            return QuestionGenerationResult(
                created=[_to_question_row(q) for q in created], shortfall=shortfall
            )

    def remove_question(
        self, teacher_id: uuid.UUID | str, quiz_id: uuid.UUID | str, question_ref: str
    ) -> QuizQuestionRow:
        """Curate a question out of a draft. Kept, not deleted (§1.5).

        ``status`` becomes ``removed``; ``position``/``question_ref`` on
        every other question are untouched, so a mark recorded against
        another ``question_ref`` can never be silently re-pointed.

        Raises:
            QuizNotFoundError: No quiz exists with ``quiz_id`` (404).
            QuizOwnershipError: The quiz is not the caller's (403).
            QuizValidationError: The quiz is not a draft (422), no question
                carries ``question_ref`` (422), or it is already removed
                (422).
        """
        teacher_uuid = _as_uuid(teacher_id)
        quiz_uuid = _as_uuid(quiz_id)
        with self._sessionmaker() as session, session.begin():
            quiz = self._load_owned(session, teacher_uuid, quiz_uuid, for_update=True)
            if quiz.status != QuizStatus.draft:
                raise QuizValidationError(
                    f"Quiz {quiz_uuid} is not a draft (status={quiz.status.value}); "
                    "its questions cannot be edited"
                )
            qq = session.scalars(
                select(QuizQuestion).where(
                    QuizQuestion.quiz_id == quiz_uuid, QuizQuestion.question_ref == question_ref
                )
            ).first()
            if qq is None:
                raise QuizValidationError(f"No question {question_ref!r} on quiz {quiz_uuid}")
            if qq.status == QuizQuestionStatus.removed:
                raise QuizValidationError(f"Question {question_ref!r} is already removed")
            qq.status = QuizQuestionStatus.removed
            session.flush()
            return _to_question_row(qq)

    # -- Pool-count (§2/§3) -----------------------------------------------------

    def pool_count(
        self,
        teacher_id: uuid.UUID | str,
        *,
        subject_code: str,
        target_grade: str | None,
        requested_count: int,
        topics: Sequence[str] | None = None,
        source: QuestionSource | None = None,
    ) -> PoolCountResult:
        """T-09 step 4's live pool-count, per ``docs/quiz-model.md`` §2.

        ``byBand`` is exactly :func:`~lemely.core.difficulty.allocate_difficulty`'s
        output for ``(target_grade, requested_count)`` — the identical call
        :meth:`generate_questions` makes, so this can never quote an
        allocation the builder itself would not produce. ``shortfall`` is
        computed by comparing that allocation against
        :meth:`~lemely.db.question_bank_repo.QuestionBankService.count_by_band`'s
        real availability, band by band; ``None`` when nothing is short.

        ``source=past_paper`` against a subject with no indexed past-paper
        rows is not an error and not a fabricated number — ``matching`` is a
        real, honest ``0`` (D3.7/§2); the router is responsible for
        rendering the exact §2 wording, not this method.
        """
        teacher_uuid = _as_uuid(teacher_id)
        school_ids = self._class_service.member_school_ids(teacher_uuid)
        counts = self._bank.count_by_band(
            teacher_uuid, school_ids, subject_code=subject_code, topics=topics, source=source
        )
        matching = sum(counts.values())
        by_band = allocate_difficulty(target_grade, requested_count)
        shortfall: dict[Band, int] = {}
        for band, needed in by_band.items():
            available = counts.get(band, 0)
            if available < needed:
                shortfall[band] = needed - available
        difficulty_estimated = self._bank.has_inferred_difficulty(
            teacher_uuid, school_ids, subject_code=subject_code, topics=topics, source=source
        )
        return PoolCountResult(
            matching=matching,
            requested=requested_count,
            by_band=by_band,
            shortfall=shortfall or None,
            difficulty_estimated=difficulty_estimated,
        )

    # -- Assignments (§1.6, P3.5 chunk E) ----------------------------------------

    def create_assignment(
        self,
        teacher_id: uuid.UUID | str,
        caller_role: Role | str,
        quiz_id: uuid.UUID | str,
        class_id: uuid.UUID | str,
        *,
        due_at: datetime | None = None,
        closes_at: datetime | None = None,
    ) -> QuizAssignmentRow:
        """Assign an owned quiz to a class. A ``draft`` quiz becomes ``assigned``.

        ``caller_role`` is threaded through to :meth:`~lemely.db.class_repo.ClassService.get_class`
        so class scope is never re-derived here — the class check reuses the
        identical rule every other teacher-portal route already enforces
        (D3.1). Quiz ownership itself stays strictly ``teacher_id``-scoped
        (see module docstring), independent of ``caller_role``.

        An already-``assigned`` quiz may be assigned to a *further* class
        (§1.6: "the same quiz assigned to two classes is an obvious teacher
        need"); ``closed``/``archived`` quizzes may not be assigned to any
        class — the lifecycle never runs backwards.

        Raises:
            QuizNotFoundError: No quiz exists with ``quiz_id`` (404).
            QuizOwnershipError: The quiz is not the caller's (403).
            ClassNotFoundError: No class exists with ``class_id`` (404) —
                propagated from :class:`~lemely.db.class_repo.ClassService`
                unchanged, per this method's "never re-derive" rule.
            ClassOwnershipError: The class is outside the caller's scope (403)
                — propagated unchanged, same rule.
            QuizValidationError: ``closes_at`` is earlier than ``due_at``
                (422); the quiz is ``closed``/``archived`` (422); the quiz has
                no ``included`` question (422, "assigning an empty quiz" —
                the defect this guard exists for); or the quiz is already
                assigned to this class (422; the unique index is the
                backstop, not the primary path).
        """
        teacher_uuid = _as_uuid(teacher_id)
        quiz_uuid = _as_uuid(quiz_id)
        class_uuid = _as_uuid(class_id)
        if due_at is not None and closes_at is not None and closes_at < due_at:
            raise QuizValidationError("closesAt cannot be earlier than dueAt")

        with self._sessionmaker() as session, session.begin():
            quiz = self._load_owned(session, teacher_uuid, quiz_uuid, for_update=True)
            if quiz.status not in (QuizStatus.draft, QuizStatus.assigned):
                raise QuizValidationError(
                    f"Quiz {quiz_uuid} is {quiz.status.value}; it can no longer be assigned"
                )
            included_count = (
                session.scalar(
                    select(func.count())
                    .select_from(QuizQuestion)
                    .where(
                        QuizQuestion.quiz_id == quiz_uuid,
                        QuizQuestion.status == QuizQuestionStatus.included,
                    )
                )
                or 0
            )
            if included_count == 0:
                raise QuizValidationError(
                    f"Quiz {quiz_uuid} has no included questions; add at least one before assigning"
                )
            # Class scope: reused, never re-derived (see docstring). Checked
            # inside the quiz's transaction so an out-of-scope class never
            # gets as far as an assignment insert attempt.
            self._class_service.get_class(teacher_uuid, caller_role, class_uuid)
            duplicate = session.scalars(
                select(QuizAssignment.id).where(
                    QuizAssignment.quiz_id == quiz_uuid, QuizAssignment.class_id == class_uuid
                )
            ).first()
            if duplicate is not None:
                raise QuizValidationError(
                    f"Quiz {quiz_uuid} is already assigned to class {class_uuid}"
                )
            assignment = QuizAssignment(
                quiz_id=quiz_uuid,
                class_id=class_uuid,
                assigned_by=teacher_uuid,
                due_at=due_at,
                closes_at=closes_at,
            )
            session.add(assignment)
            if quiz.status == QuizStatus.draft:
                quiz.status = QuizStatus.assigned
            try:
                session.flush()
            except IntegrityError as exc:
                # Backstop only (uq_quiz_assignments): the pre-check above is
                # the primary path (module brief).
                raise QuizValidationError(
                    f"Quiz {quiz_uuid} is already assigned to class {class_uuid}"
                ) from exc
            school_class = session.get(SchoolClass, class_uuid)
            if school_class is None:  # pragma: no cover - get_class already loaded this row
                raise QuizError(f"Unknown class: {class_uuid}")
            roster_size = len(self._class_service.roster(teacher_uuid, caller_role, class_uuid))
            return QuizAssignmentRow(
                assignment_id=assignment.id,
                quiz_id=quiz_uuid,
                class_id=class_uuid,
                class_name=school_class.name,
                assigned_by=teacher_uuid,
                assigned_at=assignment.assigned_at,
                due_at=assignment.due_at,
                closes_at=assignment.closes_at,
                roster_size=roster_size,
                submission_counts=_zero_submission_counts(),
            )

    def list_assignments(
        self,
        teacher_id: uuid.UUID | str,
        caller_role: Role | str,
        quiz_id: uuid.UUID | str,
    ) -> list[QuizAssignmentRow]:
        """Every assignment of an owned quiz, oldest first.

        ``rosterSize`` is read live via :meth:`~lemely.db.class_repo.ClassService.roster`
        on every call (§1.7: "never a frozen snapshot") — a student who joins
        the class after assignment shows up here immediately.
        ``submissionCounts`` is counts only (§1.6/chunk-E brief): no marks, no
        averages, no per-student results — that aggregation is chunk F's T-10.

        Raises:
            QuizNotFoundError: No quiz exists with ``quiz_id`` (404).
            QuizOwnershipError: The quiz is not the caller's (403).
        """
        teacher_uuid = _as_uuid(teacher_id)
        quiz_uuid = _as_uuid(quiz_id)
        with self._sessionmaker() as session:
            self._load_owned(session, teacher_uuid, quiz_uuid)
            assignments = session.scalars(
                select(QuizAssignment)
                .where(QuizAssignment.quiz_id == quiz_uuid)
                .order_by(QuizAssignment.assigned_at)
            ).all()
            rows: list[QuizAssignmentRow] = []
            for assignment in assignments:
                school_class = session.get(SchoolClass, assignment.class_id)
                if school_class is None:  # pragma: no cover - FK guarantees the row exists
                    raise QuizError(f"Unknown class: {assignment.class_id}")
                roster_size = len(
                    self._class_service.roster(teacher_uuid, caller_role, assignment.class_id)
                )
                counts = _zero_submission_counts()
                for status, count in session.execute(
                    select(QuizSubmission.status, func.count())
                    .where(QuizSubmission.assignment_id == assignment.id)
                    .group_by(QuizSubmission.status)
                ).all():
                    counts[status.value] = int(count)
                rows.append(
                    QuizAssignmentRow(
                        assignment_id=assignment.id,
                        quiz_id=quiz_uuid,
                        class_id=assignment.class_id,
                        class_name=school_class.name,
                        assigned_by=assignment.assigned_by,
                        assigned_at=assignment.assigned_at,
                        due_at=assignment.due_at,
                        closes_at=assignment.closes_at,
                        roster_size=roster_size,
                        submission_counts=counts,
                    )
                )
            return rows

    def delete_assignment(
        self,
        teacher_id: uuid.UUID | str,
        quiz_id: uuid.UUID | str,
        assignment_id: uuid.UUID | str,
    ) -> None:
        """Unassign a quiz from a class. Refused once any student has started.

        ``quiz_submissions`` cascades from ``quiz_assignments`` (§1.7), so
        deleting an assignment with any submission whose status is not
        ``not_started`` would silently destroy that student's answers. This
        method refuses (422) rather than allow that; there is no override.

        Raises:
            QuizNotFoundError: No quiz exists with ``quiz_id``, or no
                assignment exists with ``assignment_id`` on this quiz (404).
            QuizOwnershipError: The quiz is not the caller's (403).
            QuizValidationError: A submission for this assignment has a
                status other than ``not_started`` (422).
        """
        teacher_uuid = _as_uuid(teacher_id)
        quiz_uuid = _as_uuid(quiz_id)
        assignment_uuid = _as_uuid(assignment_id)
        with self._sessionmaker() as session, session.begin():
            self._load_owned(session, teacher_uuid, quiz_uuid)
            assignment = session.get(QuizAssignment, assignment_uuid, with_for_update=True)
            if assignment is None or assignment.quiz_id != quiz_uuid:
                raise QuizNotFoundError(f"Unknown assignment: {assignment_uuid}")
            started = session.scalars(
                select(QuizSubmission.id).where(
                    QuizSubmission.assignment_id == assignment_uuid,
                    QuizSubmission.status != QuizSubmissionStatus.not_started,
                )
            ).first()
            if started is not None:
                raise QuizValidationError(
                    f"Assignment {assignment_uuid} has a student submission already in "
                    "progress; unassigning would destroy that student's work"
                )
            session.delete(assignment)

    # -- Internals --------------------------------------------------------------

    def _load_owned(
        self,
        session: Session,
        teacher_uuid: uuid.UUID,
        quiz_uuid: uuid.UUID,
        *,
        for_update: bool = False,
    ) -> Quiz:
        quiz = session.get(Quiz, quiz_uuid, with_for_update=for_update)
        if quiz is None:
            raise QuizNotFoundError(f"Unknown quiz: {quiz_uuid}")
        if quiz.teacher_id != teacher_uuid:
            raise QuizOwnershipError(f"Caller does not own quiz {quiz_uuid}")
        return quiz

    def _to_quiz_row(self, session: Session, quiz: Quiz) -> QuizRow:
        count = (
            session.scalar(
                select(func.count())
                .select_from(QuizQuestion)
                .where(
                    QuizQuestion.quiz_id == quiz.id,
                    QuizQuestion.status == QuizQuestionStatus.included,
                )
            )
            or 0
        )
        return QuizRow(
            quiz_id=quiz.id,
            teacher_id=quiz.teacher_id,
            school_id=quiz.school_id,
            subject_code=quiz.subject_code,
            title=quiz.title,
            status=quiz.status,
            target_grade=quiz.target_grade,
            included_topics=list(quiz.included_topics),
            pool_source=quiz.pool_source,
            requested_count=quiz.requested_count,
            time_limit_minutes=quiz.time_limit_minutes,
            builder_step=quiz.builder_step,
            question_count=int(count),
        )


def _zero_submission_counts() -> dict[str, int]:
    """A ``QuizSubmissionStatus`` value -> 0 map with every status present.

    A freshly created assignment has no submissions at all, and a listing
    must still report all four keys — never a partial map a caller has to
    defensively probe (see :class:`QuizAssignmentRow`'s docstring).
    """
    return {status.value: 0 for status in QuizSubmissionStatus}


def _snapshot_bank_row(
    row: QuestionBankRow, *, quiz_id: uuid.UUID, question_ref: str, position: int
) -> QuizQuestion:
    """Copy a selected bank row's content onto a new ``QuizQuestion`` (§1.5).

    Every content field is duplicated, never referenced through the FK — a
    bank row edited or deactivated after this call must not retroactively
    change what this quiz asked (see module docstring / §1.5).
    """
    return QuizQuestion(
        quiz_id=quiz_id,
        question_bank_id=row.id,
        question_ref=question_ref,
        position=position,
        topic=row.topic,
        difficulty=QuestionDifficulty(row.difficulty),
        question_type=row.question_type,
        prompt=row.prompt,
        model_answer=row.model_answer,
        mark_scheme_points=list(row.mark_scheme_points),
        mcq_options=list(row.mcq_options) if row.mcq_options is not None else None,
        mcq_answer=row.mcq_answer,
        total_marks=row.total_marks,
    )


def _to_question_row(qq: QuizQuestion) -> QuizQuestionRow:
    return QuizQuestionRow(
        id=qq.id,
        question_bank_id=qq.question_bank_id,
        question_ref=qq.question_ref,
        position=qq.position,
        status=qq.status,
        replaced_by_id=qq.replaced_by_id,
        topic=qq.topic,
        difficulty=qq.difficulty.value,
        question_type=qq.question_type,
        prompt=qq.prompt,
        model_answer=qq.model_answer,
        mark_scheme_points=list(qq.mark_scheme_points),
        mcq_options=list(qq.mcq_options) if qq.mcq_options is not None else None,
        mcq_answer=qq.mcq_answer,
        total_marks=qq.total_marks,
    )


def _next_ref_index(existing_refs: Sequence[str]) -> int:
    """Return the next ``"qN"`` index after the highest already assigned.

    ``1`` when no refs exist yet. Refs are always of this codebase's own
    making (``f"q{n}"``, see :meth:`QuizService.generate_questions`), so a
    ref that does not parse this way is defensively ignored rather than
    raising — a corrupt/foreign row must not block topping up the rest.
    """
    highest = 0
    for ref in existing_refs:
        if not ref.startswith("q"):
            continue
        try:
            highest = max(highest, int(ref[1:]))
        except ValueError:
            continue
    return highest + 1


def _next_position(session: Session, quiz_uuid: uuid.UUID) -> int:
    """Return one past the highest ``position`` already used on this quiz."""
    highest = session.scalar(
        select(func.max(QuizQuestion.position)).where(QuizQuestion.quiz_id == quiz_uuid)
    )
    return int(highest or 0) + 1


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    """Coerce a str/UUID to :class:`uuid.UUID`, raising ``ValueError`` if invalid."""
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Identifier must be a UUID, got {value!r}") from exc


__all__ = [
    "PoolCountResult",
    "QuestionGenerationResult",
    "QuizAssignmentRow",
    "QuizDetail",
    "QuizError",
    "QuizNotFoundError",
    "QuizOwnershipError",
    "QuizQuestionRow",
    "QuizRow",
    "QuizService",
    "QuizValidationError",
]
