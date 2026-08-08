"""Practice-set service: honest preview, self-assignment, and print export (P4.5).

Mirrors :mod:`lemely.db.placement_repo`'s shape exactly — a practice set is
``Quiz(kind=QuizKind.practice, student_id=caller, teacher_id=None)`` plus a
self-``QuizAssignment``, assembled through the same
:func:`~lemely.db.quiz_repo._snapshot_bank_row` freezer placement uses, so
``quiz_questions.topic`` carries ``question_bank.topic`` verbatim and no new
marking-side code is needed for the weakness profile a practice attempt
produces (D4.6 §6). No migration: ``quizkind`` already carries ``practice``
(migration 0010).

**What is genuinely different from placement.** Placement assembles a fixed
~15-minute, breadth-first sample against a viability floor
(:mod:`lemely.core.placement`) — the student does not choose anything.
Practice is the opposite shape: the student names the filters (topic,
difficulty, count, source), S-20 shows a live preview of what they will
actually get, and this module's only job is to answer that preview honestly
and then assemble exactly what it promised. There is no budget/duration
concept and no breadth-first spread algorithm to reuse from
:mod:`lemely.core.placement` — a random sample within the requested filters
is what "practice on topic X, difficulty Y, N questions" means, so the
selection lives directly in this module's SQL rather than in a second pure
core algorithm.

**Weak-topic targeting is the phase acceptance criterion** (MISSION §4:
"generated practice demonstrably targets seeded weaknesses"), not a
parameter that merely exists. :meth:`PracticeService.preview`/:meth:`create`
with ``PracticeRequest.weak_topics_only=True`` read the caller's own
``WeaknessRecord`` rows for the subject (P4.2's ``"<code> <name>"`` label
vocabulary, D4.7) and replace the topic filter with them — never a
re-derived weakness engine, and never silently falling back to "no topic
filter" when the student has no weakness data yet (that would defeat the
whole point without saying so; see :data:`PracticeUnavailableReason.no_weaknesses`).

**The honesty path is the common case** (spec §1.4, MISSION's Phase-4
header): the 0625 bank is 273 rows / 211 topic-labelled, and 0580/0606 have
none. :meth:`PracticeService.preview` reports the real matching count,
uncapped, whenever the filtered pool is smaller than requested — never
padded, never silently shortened. :meth:`PracticeService.create` persists
whatever it actually found (capped at the requested count) and says so via
:attr:`PracticeCreated.reason`; it only refuses outright
(:class:`PracticeUnavailableError`) when the pool is genuinely empty for the
filter set, or the caller asked for weak-topic targeting and has no
weaknesses recorded yet.

**Carries D4.9's lesson.** Selection is narrowed to the papers
``student_enrolment_papers`` names when the student has rows, and left
unrestricted when they have none (an unanswered S-02 question is "not
answered", never "sits no papers") — via the shared
:func:`~lemely.db.student_profile_repo.enrolled_paper_numbers` helper
placement now shares with this module rather than each re-deriving it. A
bank row with no linked ``Paper`` (a generated question, or an unlinked
past-paper row) is never excluded by this narrowing — there is nothing to
compare its tier against, so it stays eligible either way.

**Answer-leak discipline (D3.8).** :meth:`PracticeService.export` returns
:class:`PracticeExportQuestion` rows, which structurally carry no
``model_answer``/``mark_scheme_points``/``mcq_answer`` field — the same
subset discipline :class:`~lemely.db.quiz_taking_repo.QuizTakeQuestionRow`
encodes. There is no "reveal answer" payload in this module; S-21's marking
comes from the existing take/submit/mark path, and if a print-time answer
key is ever needed it must be a separate, explicitly-named field or route —
never a widening of this one.

**Take/resume/save-answer/submit are not here.** Same reuse payoff D4.6 §4
already banked for placement: the existing
``/api/student/quizzes/{assignment_id}`` routes serve a practice set
unchanged.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy import func, select

from lemely.db.models.academic import Paper
from lemely.db.models.attempts import Attempt, QuestionResult, WeaknessRecord
from lemely.db.models.enums import (
    QuestionDifficulty,
    QuestionSource,
    QuizKind,
    QuizQuestionStatus,
    QuizStatus,
    QuizSubmissionStatus,
)
from lemely.db.models.quizzes import (
    QuestionBank,
    Quiz,
    QuizAssignment,
    QuizQuestion,
    QuizSubmission,
)
from lemely.db.question_bank_repo import _to_row, renderable_bank_filter, visible_bank_filter
from lemely.db.quiz_repo import _snapshot_bank_row
from lemely.db.student_profile_repo import enrolled_paper_numbers
from lemely.io.syllabus_topics import get_taxonomy

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy import ColumnElement
    from sqlalchemy.orm import Session, sessionmaker

    from lemely.core.difficulty import Band


class PracticeError(Exception):
    """Base class for practice-set failures."""


class PracticeNotFoundError(PracticeError):
    """No assignment exists for the supplied id, anywhere (→ 404).

    Also raised when an assignment id resolves to a quiz the caller owns but
    whose ``kind`` is not ``practice`` (e.g. a placement assignment id
    handed to :meth:`PracticeService.export`) — that resource genuinely does
    not exist as a practice set, and the caller already owns it either way,
    so there is nothing this distinction could leak (D4.6 §3: ``kind`` may
    only narrow a query that is already owner-scoped).
    """


class PracticeOwnershipError(PracticeError):
    """The assignment exists but belongs to another student (→ 403)."""


class PracticeUnavailableReason(StrEnum):
    """Why :meth:`PracticeService.create` refused outright, or why S-20 should say so.

    Distinct from :attr:`PracticeCreated.reason`/:attr:`PracticePreview.reason`'s
    third value, ``insufficient_pool`` — that one is *not* a refusal (see
    module docstring: create still succeeds, honestly short).
    """

    no_questions = "no_questions"
    """The filtered pool was empty. Today this is every request against 0580/0606."""

    no_weaknesses = "no_weaknesses"
    """``weak_topics_only`` was requested but the caller has no ``WeaknessRecord``
    row for this subject yet — falling back to "no topic filter" here would
    silently defeat the entire point of the mode rather than say so."""

    insufficient_pool = "insufficient_pool"
    """The pool matched at least one question but fewer than requested.
    Not a refusal: :meth:`PracticeService.create` still succeeds with the
    real, smaller count."""


@dataclass(frozen=True, slots=True)
class PracticeRequest:
    """S-20's filter set: topic, difficulty, count, source — and the weak-topic mode."""

    subject_code: str
    count: int
    topics: tuple[str, ...] = ()
    """Ignored when ``weak_topics_only`` is ``True`` — see that field."""
    weak_topics_only: bool = False
    """Derive the topic filter from the caller's own ``WeaknessRecord`` rows
    for ``subject_code`` (P4.2's ``"<code> <name>"`` vocabulary, D4.7)
    instead of :attr:`topics`. The acceptance-criterion mode (MISSION §4)."""
    difficulty_bands: tuple[Band, ...] = ()
    """Empty means "any band" — no filter applied."""
    source: QuestionSource | None = None
    """``None`` means "any source" (past-paper or generated)."""


@dataclass(frozen=True, slots=True)
class PracticePreview:
    """S-20's live preview: how many questions this filter set actually matches.

    ``available`` is ``True`` whenever :meth:`PracticeService.create` would
    succeed at all — including the honest-shortfall case
    (``reason="insufficient_pool"``); it is ``False`` only for the two
    refusal reasons in :class:`PracticeUnavailableReason`.
    """

    available: bool
    reason: str | None
    """A :class:`PracticeUnavailableReason` value, or ``None`` when the pool
    fully covers the requested count."""
    requested_count: int
    available_count: int
    """The real, uncapped number of matching rows — never rounded up, never
    capped to ``requested_count`` (spec §1.4: no invented precision)."""
    topics: list[str]
    """The resolved topic filter actually applied — the caller's own
    ``topics`` in the ordinary case, or the derived weak-topic set when
    ``weak_topics_only`` was requested. Sorted, so S-20 can render it
    deterministically."""


class PracticeUnavailableError(PracticeError):
    """Assembly refused outright (→ 409); carries the same payload :meth:`preview` returns."""

    def __init__(self, preview: PracticePreview) -> None:
        """Wrap the unavailable :class:`PracticePreview` payload."""
        self.preview = preview
        super().__init__(f"Practice set unavailable for reason={preview.reason!r}")


@dataclass(frozen=True, slots=True)
class PracticeCreated:
    """Outcome of :meth:`PracticeService.create`."""

    assignment_id: uuid.UUID
    quiz_id: uuid.UUID
    question_count: int
    """The real, persisted count — may be less than ``requested_count``; see ``reason``."""
    requested_count: int
    topics: list[str]
    reason: str | None
    """``"insufficient_pool"`` when ``question_count < requested_count``, else ``None``."""


@dataclass(frozen=True, slots=True)
class PracticeExportQuestion:
    """One question in the print/export payload (S-21).

    A strict subset of :class:`~lemely.db.quiz_repo.QuizQuestionRow` — no
    ``model_answer``, ``mark_scheme_points``, or ``mcq_answer`` field exists
    here at all (see module docstring), mirroring
    :class:`~lemely.db.quiz_taking_repo.QuizTakeQuestionRow`'s discipline.
    """

    question_ref: str
    position: int
    topic: str | None
    difficulty: Band
    question_type: str
    prompt: str
    total_marks: int
    mcq_options: list[str] | None


@dataclass(frozen=True, slots=True)
class PracticeExportSet:
    """Full response for the print/export route."""

    assignment_id: uuid.UUID
    quiz_id: uuid.UUID
    subject_code: str
    title: str
    questions: list[PracticeExportQuestion] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class PracticeResultQuestion:
    """One marked question's outcome, for S-21's result view.

    Unlike :class:`~lemely.db.placement_repo.PlacementQuestionResult`, this
    carries ``position`` (S-21 renders a set the student built themselves,
    ordered) and the marking engine's own confidence for the mark — every
    displayed mark must carry its confidence (QUALITY-BAR.md's product
    section). No ``model_answer``/``mark_scheme_points``/``mcq_answer`` here
    either — this is feedback on the student's own answer, not the scheme
    material (D3.8's discipline, mirrored from :class:`PracticeExportQuestion`).
    """

    question_ref: str
    position: int
    topic: str | None
    total_marks: int
    awarded_marks: int
    """:attr:`~lemely.db.models.attempts.QuestionResult.effective_marks` — the
    teacher's override when one exists, else the AI's own mark (mirrors
    :attr:`~lemely.db.placement_repo.PlacementQuestionResult.awarded_marks`)."""
    confidence_band: str
    confidence_score: float


@dataclass(frozen=True, slots=True)
class PracticeResultRow:
    """S-21's result payload: has this practice set been marked, and how did it go.

    ``marked=False`` covers both "not yet submitted" and "submitted but not
    yet marked" — :attr:`submission_status` is what tells those two apart
    (S-21 polls this the way S-05 polls placement's result route); every
    score field is ``None``, never ``0``, while unmarked (spec §1.4: a zero
    score for an unmarked set is invented precision).
    """

    assignment_id: uuid.UUID
    quiz_id: uuid.UUID
    subject_code: str
    marked: bool
    submission_status: str
    """A :class:`~lemely.db.models.enums.QuizSubmissionStatus` value —
    ``"not_started"`` when no ``QuizSubmission`` row exists yet (a row is
    created lazily on first open, never pre-seeded)."""
    awarded_marks: int | None
    maximum_marks: int | None
    questions: list[PracticeResultQuestion]


@dataclass(frozen=True, slots=True)
class PracticeTopicCount:
    """One servable topic and its real, unpadded available count."""

    topic: str
    available_count: int


@dataclass(frozen=True, slots=True)
class PracticeTopicsResult:
    """S-20's topic-selection payload: real, servable topics plus the caller's own weak topics.

    ``untopiced_count`` is reported separately, never folded into
    :attr:`topics` under an invented label — an untopiced row is legitimate
    practice *material* (P4.5), just not a *topic* (module docstring / P4.9
    scoping).
    """

    subject_code: str
    topics: list[PracticeTopicCount]
    weak_topics: list[str]
    untopiced_count: int


class PracticeService:
    """Preview, self-assign, and export a student's practice set.

    Constructed with a ``sessionmaker`` alone, mirroring
    :class:`~lemely.db.placement_repo.PlacementService` — a practice
    assignment is always direct-to-student, never class-targeted, so no
    ``ClassService`` seam is needed.
    """

    def __init__(self, sessionmaker: sessionmaker[Session]) -> None:
        """Wire the service to a session factory."""
        self._sessionmaker = sessionmaker

    # -- Preview (S-20) -------------------------------------------------------

    def preview(self, student_id: uuid.UUID | str, request: PracticeRequest) -> PracticePreview:
        """How many questions this filter set actually matches, right now. No write."""
        student_uuid = _as_uuid(student_id)
        with self._sessionmaker() as session:
            return self._preview(session, student_uuid, request)

    # -- Create (S-20 -> S-21) -------------------------------------------------

    def create(self, student_id: uuid.UUID | str, request: PracticeRequest) -> PracticeCreated:
        """Assemble and self-assign a practice set.

        One transaction: the ``Quiz``, its self-``QuizAssignment``, and every
        frozen ``QuizQuestion`` snapshot, or nothing at all.

        Raises:
            PracticeUnavailableError: The pool is empty for this filter set,
                or ``weak_topics_only`` was requested and the caller has no
                weaknesses recorded for this subject (→ 409); carries the
                identical payload :meth:`preview` would have returned.
        """
        student_uuid = _as_uuid(student_id)
        title = _practice_title(request.subject_code)
        with self._sessionmaker() as session, session.begin():
            preview = self._preview(session, student_uuid, request)
            if not preview.available:
                raise PracticeUnavailableError(preview)

            rows = self._select_rows(session, student_uuid, request, topics=preview.topics)

            quiz = Quiz(
                teacher_id=None,
                student_id=student_uuid,
                kind=QuizKind.practice,
                subject_code=request.subject_code,
                title=title,
                status=QuizStatus.assigned,
                time_limit_minutes=None,
            )
            session.add(quiz)
            session.flush()

            assignment = QuizAssignment(
                quiz_id=quiz.id,
                class_id=None,
                student_id=student_uuid,
                assigned_by=student_uuid,
            )
            session.add(assignment)

            for position, bank_row in enumerate(rows, start=1):
                qq = _snapshot_bank_row(
                    _to_row(bank_row),
                    quiz_id=quiz.id,
                    question_ref=f"q{position}",
                    position=position,
                )
                session.add(qq)
            session.flush()

            return PracticeCreated(
                assignment_id=assignment.id,
                quiz_id=quiz.id,
                question_count=len(rows),
                requested_count=request.count,
                topics=preview.topics,
                reason=(
                    PracticeUnavailableReason.insufficient_pool.value
                    if len(rows) < request.count
                    else None
                ),
            )

    # -- Export / print (S-21) -------------------------------------------------

    def export(
        self, student_id: uuid.UUID | str, assignment_id: uuid.UUID | str
    ) -> PracticeExportSet:
        """The print/export payload: every ``included`` question, answer-free.

        Raises:
            PracticeNotFoundError: No assignment exists with
                ``assignment_id`` anywhere (404); or it exists and belongs
                to the caller but is not a ``practice``-kind quiz (404 —
                see the class docstring).
            PracticeOwnershipError: The assignment exists but is not the
                caller's (403) — an id that exists anywhere is a 403, not a
                404, mirroring every other owner-scoped service here.
        """
        student_uuid = _as_uuid(student_id)
        assignment_uuid = _as_uuid(assignment_id)
        with self._sessionmaker() as session:
            assignment = session.get(QuizAssignment, assignment_uuid)
            if assignment is None:
                raise PracticeNotFoundError(f"Unknown assignment: {assignment_uuid}")
            if assignment.student_id != student_uuid:
                raise PracticeOwnershipError(
                    f"Assignment {assignment_uuid} is not assigned to student {student_uuid}"
                )
            quiz = session.get(Quiz, assignment.quiz_id)
            if quiz is None:  # pragma: no cover - FK guarantees the row exists
                raise PracticeError(f"Unknown quiz: {assignment.quiz_id}")
            if quiz.kind != QuizKind.practice:
                raise PracticeNotFoundError(f"Assignment {assignment_uuid} is not a practice set")

            questions = session.scalars(
                select(QuizQuestion)
                .where(
                    QuizQuestion.quiz_id == quiz.id,
                    QuizQuestion.status == QuizQuestionStatus.included,
                )
                .order_by(QuizQuestion.position)
            ).all()
            return PracticeExportSet(
                assignment_id=assignment_uuid,
                quiz_id=quiz.id,
                subject_code=quiz.subject_code,
                title=quiz.title,
                questions=[
                    PracticeExportQuestion(
                        question_ref=q.question_ref,
                        position=q.position,
                        topic=q.topic,
                        difficulty=q.difficulty.value,
                        question_type=q.question_type,
                        prompt=q.prompt,
                        total_marks=q.total_marks,
                        mcq_options=list(q.mcq_options) if q.mcq_options is not None else None,
                    )
                    for q in questions
                ],
            )

    # -- Result (S-21 poll target) ----------------------------------------------

    def result(
        self, student_id: uuid.UUID | str, assignment_id: uuid.UUID | str
    ) -> PracticeResultRow:
        """S-21's result payload: has this practice set been marked, and how did it go.

        Submitting any quiz (placement, practice, or teacher-assigned) triggers
        ``QuizMarkingService.mark_submission`` on a background thread — this
        method only reads what that already wrote, exactly the way
        :meth:`~lemely.db.placement_repo.PlacementService.result` does.
        ``marked=False`` (every score field ``None``, ``questions=[]``) when
        the submission has not been marked yet, rather than a half-true
        result; :attr:`PracticeResultRow.submission_status` still tells
        "not submitted yet" apart from "submitted, being marked".

        Raises:
            PracticeNotFoundError: No assignment exists with
                ``assignment_id`` anywhere (404); or it exists and belongs
                to the caller but is not a ``practice``-kind quiz (404 —
                see the class docstring, same ordering as :meth:`export`).
            PracticeOwnershipError: The assignment exists but is not the
                caller's (403).
        """
        student_uuid = _as_uuid(student_id)
        assignment_uuid = _as_uuid(assignment_id)
        with self._sessionmaker() as session:
            assignment = session.get(QuizAssignment, assignment_uuid)
            if assignment is None:
                raise PracticeNotFoundError(f"Unknown assignment: {assignment_uuid}")
            if assignment.student_id != student_uuid:
                raise PracticeOwnershipError(
                    f"Assignment {assignment_uuid} is not assigned to student {student_uuid}"
                )
            quiz = session.get(Quiz, assignment.quiz_id)
            if quiz is None:  # pragma: no cover - FK guarantees the row exists
                raise PracticeError(f"Unknown quiz: {assignment.quiz_id}")
            if quiz.kind != QuizKind.practice:
                raise PracticeNotFoundError(f"Assignment {assignment_uuid} is not a practice set")

            submission = session.scalars(
                select(QuizSubmission).where(
                    QuizSubmission.assignment_id == assignment_uuid,
                    QuizSubmission.student_id == student_uuid,
                )
            ).first()
            if submission is None:
                return PracticeResultRow(
                    assignment_id=assignment_uuid,
                    quiz_id=quiz.id,
                    subject_code=quiz.subject_code,
                    marked=False,
                    submission_status=QuizSubmissionStatus.not_started.value,
                    awarded_marks=None,
                    maximum_marks=None,
                    questions=[],
                )
            if submission.status != QuizSubmissionStatus.marked or submission.attempt_id is None:
                return PracticeResultRow(
                    assignment_id=assignment_uuid,
                    quiz_id=quiz.id,
                    subject_code=quiz.subject_code,
                    marked=False,
                    submission_status=submission.status.value,
                    awarded_marks=None,
                    maximum_marks=None,
                    questions=[],
                )

            attempt = session.get(Attempt, submission.attempt_id)
            if attempt is None:  # pragma: no cover - FK guarantees the row exists
                raise PracticeError(f"Unknown attempt: {submission.attempt_id}")
            question_results = session.scalars(
                select(QuestionResult).where(QuestionResult.attempt_id == attempt.id)
            ).all()
            positions = {
                qq.question_ref: qq.position
                for qq in session.scalars(
                    select(QuizQuestion).where(
                        QuizQuestion.quiz_id == quiz.id,
                        QuizQuestion.status == QuizQuestionStatus.included,
                    )
                ).all()
            }

            questions = sorted(
                (
                    PracticeResultQuestion(
                        question_ref=qr.question_id,
                        position=positions[qr.question_id],
                        topic=qr.topic,
                        total_marks=qr.maximum_marks,
                        awarded_marks=qr.effective_marks,
                        confidence_band=qr.confidence_band.value,
                        confidence_score=qr.confidence_score,
                    )
                    for qr in question_results
                    if qr.question_id in positions
                ),
                key=lambda q: q.position,
            )

            return PracticeResultRow(
                assignment_id=assignment_uuid,
                quiz_id=quiz.id,
                subject_code=quiz.subject_code,
                marked=True,
                submission_status=QuizSubmissionStatus.marked.value,
                awarded_marks=attempt.awarded_marks,
                maximum_marks=attempt.maximum_marks,
                questions=questions,
            )

    # -- Topics (S-20) ------------------------------------------------------

    def topics(self, student_id: uuid.UUID | str, subject_code: str) -> PracticeTopicsResult:
        """The distinct **servable** topics for this student and subject, with real counts.

        Filtered through exactly the clauses :meth:`_preview` uses
        (:func:`~lemely.db.student_profile_repo.enrolled_paper_numbers`,
        :func:`~lemely.db.question_bank_repo.visible_bank_filter`,
        :func:`~lemely.db.question_bank_repo.renderable_bank_filter`, subject) via
        :meth:`_matching_clauses` — the same shared predicate, not a second,
        drifting copy, so an offered topic can never be one the pool cannot
        actually serve.

        Untopiced rows (``topic IS NULL``) are not a topic: their count is
        reported separately (:attr:`PracticeTopicsResult.untopiced_count`),
        never folded into :attr:`PracticeTopicsResult.topics` under an
        invented label. Also returns the caller's own weak topics for this
        subject (:meth:`_weak_topics_for` — the same ``WeaknessRecord``
        resolution :meth:`_preview` uses for ``weak_topics_only``), so S-20
        can pre-fill its chips from the server's own vocabulary rather than
        re-deriving from a different one.
        """
        student_uuid = _as_uuid(student_id)
        with self._sessionmaker() as session:
            enrolled = enrolled_paper_numbers(session, student_uuid, subject_code)
            base_clauses = self._matching_clauses(
                enrolled, student_uuid, subject_code, (), (), None
            )

            topic_rows = session.execute(
                select(QuestionBank.topic, func.count())
                .select_from(QuestionBank)
                .outerjoin(Paper, Paper.id == QuestionBank.paper_id)
                .where(*base_clauses, QuestionBank.topic.is_not(None))
                .group_by(QuestionBank.topic)
            ).all()
            untopiced_count = (
                session.scalar(
                    select(func.count())
                    .select_from(QuestionBank)
                    .outerjoin(Paper, Paper.id == QuestionBank.paper_id)
                    .where(*base_clauses, QuestionBank.topic.is_(None))
                )
                or 0
            )
            weak_topics = self._weak_topics_for(session, student_uuid, subject_code)

            return PracticeTopicsResult(
                subject_code=subject_code,
                topics=sorted(
                    (
                        PracticeTopicCount(topic=topic, available_count=count)
                        for topic, count in topic_rows
                    ),
                    key=lambda t: t.topic,
                ),
                weak_topics=weak_topics,
                untopiced_count=untopiced_count,
            )

    # -- Internals --------------------------------------------------------------

    def _preview(
        self, session: Session, student_uuid: uuid.UUID, request: PracticeRequest
    ) -> PracticePreview:
        if request.weak_topics_only:
            topics = self._weak_topics_for(session, student_uuid, request.subject_code)
            if not topics:
                return PracticePreview(
                    available=False,
                    reason=PracticeUnavailableReason.no_weaknesses.value,
                    requested_count=request.count,
                    available_count=0,
                    topics=[],
                )
        else:
            topics = sorted(set(request.topics))

        enrolled = enrolled_paper_numbers(session, student_uuid, request.subject_code)
        clauses = self._matching_clauses(
            enrolled,
            student_uuid,
            request.subject_code,
            topics,
            request.difficulty_bands,
            request.source,
        )
        count_stmt = (
            select(func.count())
            .select_from(QuestionBank)
            .outerjoin(Paper, Paper.id == QuestionBank.paper_id)
            .where(*clauses)
        )
        available_count = session.scalar(count_stmt) or 0

        if available_count == 0:
            return PracticePreview(
                available=False,
                reason=PracticeUnavailableReason.no_questions.value,
                requested_count=request.count,
                available_count=0,
                topics=topics,
            )
        if available_count < request.count:
            return PracticePreview(
                available=True,
                reason=PracticeUnavailableReason.insufficient_pool.value,
                requested_count=request.count,
                available_count=available_count,
                topics=topics,
            )
        return PracticePreview(
            available=True,
            reason=None,
            requested_count=request.count,
            available_count=available_count,
            topics=topics,
        )

    def _select_rows(
        self,
        session: Session,
        student_uuid: uuid.UUID,
        request: PracticeRequest,
        *,
        topics: Sequence[str],
    ) -> list[QuestionBank]:
        """The actual sample: up to ``request.count`` rows, chosen at random.

        ``topics`` is the *resolved* filter :meth:`_preview` already computed
        (the caller's own topics, or the derived weak-topic set) — passed in
        rather than re-derived, so a weak-topic set can never read differently
        between the preview that authorised the create and the create itself.
        """
        if request.count <= 0:
            return []
        enrolled = enrolled_paper_numbers(session, student_uuid, request.subject_code)
        clauses = self._matching_clauses(
            enrolled,
            student_uuid,
            request.subject_code,
            topics,
            request.difficulty_bands,
            request.source,
        )
        stmt = (
            select(QuestionBank)
            .outerjoin(Paper, Paper.id == QuestionBank.paper_id)
            .where(*clauses)
            .order_by(func.random())
            .limit(request.count)
        )
        return list(session.scalars(stmt).all())

    def _matching_clauses(
        self,
        enrolled: frozenset[int],
        student_uuid: uuid.UUID,
        subject_code: str,
        topics: Sequence[str],
        bands: Sequence[Band],
        source: QuestionSource | None,
    ) -> list[ColumnElement[bool]]:
        """The filter set both the preview count and the selection share.

        Built on :func:`~lemely.db.question_bank_repo.visible_bank_filter` —
        the single §1.3 visibility predicate — so "matching" can never mean
        something different between the honest count and the actual
        selection (the exact divergence that module's docstring warns
        against).
        """
        clauses: list[ColumnElement[bool]] = [
            QuestionBank.is_active.is_(True),
            visible_bank_filter(student_uuid, ()),
            renderable_bank_filter(),
            QuestionBank.subject_code == subject_code,
        ]
        if source is not None:
            clauses.append(QuestionBank.source == source)
        if topics:
            clauses.append(QuestionBank.topic.in_(topics))
        if bands:
            clauses.append(QuestionBank.difficulty.in_([QuestionDifficulty(b) for b in bands]))
        if enrolled:
            # D4.9's lesson: narrow only when the student has enrolment-paper
            # rows, and never exclude a row with no linked Paper at all —
            # there is nothing to compare its tier against.
            clauses.append(sa.or_(Paper.paper_number.is_(None), Paper.paper_number.in_(enrolled)))
        return clauses

    def _weak_topics_for(
        self, session: Session, student_uuid: uuid.UUID, subject_code: str
    ) -> list[str]:
        """Distinct topics with net lost marks, aggregated across every attempt.

        Reads ``WeaknessRecord`` rows verbatim, joined to ``Attempt`` for
        ``subject_code`` (``WeaknessRecord`` itself carries no subject) — no
        re-derivation of the weakness engine. The "zero net lost marks is not
        a weakness" exclusion mirrors
        :func:`~lemely.core.analytics.group_weak_areas`'s identical rule,
        applied here as an aggregate across every attempt rather than one.
        Sorted, for a deterministic S-20 preview.
        """
        rows = session.execute(
            select(WeaknessRecord.topic, WeaknessRecord.lost_marks, WeaknessRecord.maximum_marks)
            .join(Attempt, Attempt.id == WeaknessRecord.attempt_id)
            .where(WeaknessRecord.user_id == student_uuid, Attempt.subject_code == subject_code)
        ).all()
        totals: dict[str, list[int]] = {}
        for topic, lost, maximum in rows:
            bucket = totals.setdefault(topic, [0, 0])
            bucket[0] += lost
            bucket[1] += maximum
        return sorted(topic for topic, (lost, _maximum) in totals.items() if lost > 0)


def _practice_title(subject_code: str) -> str:
    """``"<Subject name> Practice Set"``, the transcribed name — never invented.

    Mirrors :func:`~lemely.db.placement_repo._placement_title`.
    """
    taxonomy = get_taxonomy(subject_code)
    subject_name = taxonomy.subject_name if taxonomy is not None else subject_code
    return f"{subject_name} Practice Set"


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    """Coerce a str/UUID to :class:`uuid.UUID`, raising ``ValueError`` if invalid."""
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Identifier must be a UUID, got {value!r}") from exc


__all__ = [
    "PracticeCreated",
    "PracticeError",
    "PracticeExportQuestion",
    "PracticeExportSet",
    "PracticeNotFoundError",
    "PracticeOwnershipError",
    "PracticePreview",
    "PracticeRequest",
    "PracticeResultQuestion",
    "PracticeResultRow",
    "PracticeService",
    "PracticeTopicCount",
    "PracticeTopicsResult",
    "PracticeUnavailableError",
    "PracticeUnavailableReason",
]
