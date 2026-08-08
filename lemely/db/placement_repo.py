"""Placement-test service: availability, self-assignment, and results (P4.4 chunk B-4, D4.6).

The placement test is quiz-shaped and reuses the quiz engine wholesale — this
module is the thin composition layer D4.6 §4/§5/§6 describes, not a second
engine. It owns exactly three operations, each thin over machinery that
already exists:

1. :meth:`PlacementService.availability` — load this student's candidate
   bank rows and the subject's transcribed paper timings, hand both to the
   pure :func:`~lemely.core.placement.assemble` (D4.6 §5), and report the
   outcome. No write.
2. :meth:`PlacementService.create` — the same assembly, then a
   :class:`~lemely.db.models.quizzes.Quiz` (``kind=placement``,
   ``student_id=caller``, ``teacher_id=None``, D4.6 §1), a self-
   :class:`~lemely.db.models.quizzes.QuizAssignment`
   (``assigned_by=caller``), and one frozen
   :class:`~lemely.db.models.quizzes.QuizQuestion` per selected candidate via
   :func:`~lemely.db.quiz_repo._snapshot_bank_row` — reused verbatim, not a
   second snapshotter, so ``quiz_questions.topic`` carries
   ``question_bank.topic`` the identical way a teacher-built quiz does (D4.6
   §6's "no new code on the marking side" depends on this).
3. :meth:`PlacementService.result` — the S-05 payload, read straight off the
   quiz-engine tables a marked placement submission already wrote: no
   ``placement_results`` table, no re-derived weakness profile
   (:class:`~lemely.db.models.attempts.WeaknessRecord` rows are read, never
   recomputed — D4.6 §6). No grade, no predicted grade: a placement attempt
   writes neither (``AttemptRepository.persist_quiz_correction`` never
   receives a :class:`~lemely.core.schemas.GradePrediction`, D4.6 §7).

**Take/save-answer/submit are not here.** They are the existing
``/api/student/quizzes/{assignment_id}`` routes, reused verbatim
(:class:`~lemely.db.quiz_taking_repo.QuizTakingService`) — that reuse *is*
the "do not fork the engine" payoff D4.6 §4 describes. This module only
assembles, self-assigns, and reads results.

**Ownership.** :meth:`result` authorises the same way
:meth:`~lemely.db.quiz_taking_repo.QuizTakingService._load_permitted`'s
direct-to-student branch does: an assignment id that exists but is not the
caller's is a 403, never a 404 — the same accepted existence-oracle
trade-off every owner-scoped service in this codebase makes.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import select

from lemely.core.placement import (
    Assembly,
    Candidate,
    PaperTiming,
    Unavailable,
    assemble,
)
from lemely.db.models.academic import Paper
from lemely.db.models.attempts import Attempt, QuestionResult, WeaknessRecord
from lemely.db.models.enums import (
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
from lemely.db.question_bank_repo import _to_row, renderable_bank_filter
from lemely.db.quiz_repo import _snapshot_bank_row
from lemely.db.student_profile_repo import enrolled_paper_numbers
from lemely.io.paper_timing import get_paper_timings
from lemely.io.syllabus_topics import get_taxonomy

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker


class PlacementError(Exception):
    """Base class for placement failures."""


class PlacementNotFoundError(PlacementError):
    """No assignment exists for the supplied id, anywhere (→ 404)."""


class PlacementOwnershipError(PlacementError):
    """The assignment exists but belongs to another student (→ 403)."""


@dataclass(frozen=True, slots=True)
class PlacementAvailability:
    """S-03's payload: whether a placement test can be assembled, and why not."""

    available: bool
    reason: str | None
    """A :class:`~lemely.core.placement.UnavailableReason` value, or ``None``
    when ``available`` is ``True``."""
    question_count: int
    topic_count: int
    """Distinct **syllabus** topics (:attr:`~lemely.core.placement.Assembly.syllabus_topic_count`),
    never ``len(topics)`` — D4.8 §2's overstated-breadth bug."""
    estimated_minutes: float


class PlacementUnavailableError(PlacementError):
    """Assembly failed viability (→ 409); carries the same payload :meth:`availability` returns."""

    def __init__(self, availability: PlacementAvailability) -> None:
        """Wrap the unavailable :class:`PlacementAvailability` payload."""
        self.availability = availability
        super().__init__(f"Placement unavailable for reason={availability.reason!r}")


@dataclass(frozen=True, slots=True)
class PlacementCreated:
    """Outcome of :meth:`PlacementService.create`."""

    assignment_id: uuid.UUID
    quiz_id: uuid.UUID
    question_count: int
    topic_count: int
    estimated_minutes: float


@dataclass(frozen=True, slots=True)
class PlacementQuestionResult:
    """One marked question's outcome, for S-05's per-question view."""

    question_ref: str
    topic: str | None
    awarded_marks: int
    """The single accessor's value
    (:attr:`~lemely.db.models.attempts.QuestionResult.effective_marks`) — a
    teacher override, if one exists, else the AI's own mark."""
    maximum_marks: int


@dataclass(frozen=True, slots=True)
class PlacementTopicBreakdown:
    """One topic's weakness, read verbatim off a ``WeaknessRecord`` row."""

    topic: str
    lost_marks: int
    maximum_marks: int
    accuracy: float


@dataclass(frozen=True, slots=True)
class PlacementResultRow:
    """S-05's payload: per-question marks, topic breakdown, and the level-estimate flag.

    ``marked=False`` covers both "not yet submitted" and "submitted but not
    yet marked" — S-05 must say so honestly rather than render a half
    result; every count/list field is a zero/empty placeholder in that case,
    not a partial computation.
    """

    assignment_id: uuid.UUID
    quiz_id: uuid.UUID
    subject_code: str
    marked: bool
    awarded_marks: int | None
    maximum_marks: int | None
    questions: list[PlacementQuestionResult]
    topic_breakdown: list[PlacementTopicBreakdown]
    spans_multiple_bands: bool
    """Whether S-05 may show a working-level estimate
    (:attr:`~lemely.core.placement.Assembly.spans_multiple_bands`, D4.6 §5).
    Read off the frozen ``quiz_questions.difficulty`` snapshot — the same
    property assembly computed, never a second definition — since
    ``Assembly`` itself is not persisted."""


class PlacementService:
    """Assemble, self-assign, and read back a student's placement test.

    Constructed with a ``sessionmaker`` alone: unlike
    :class:`~lemely.db.quiz_taking_repo.QuizTakingService`, placement
    ownership needs no ``ClassService`` seam — a placement assignment is
    always direct-to-student (D4.6 §1), never class-targeted.
    """

    def __init__(self, sessionmaker: sessionmaker[Session]) -> None:
        """Wire the service to a session factory."""
        self._sessionmaker = sessionmaker

    # -- Availability (S-03) -----------------------------------------------

    def availability(self, student_id: uuid.UUID | str, subject_code: str) -> PlacementAvailability:
        """Whether a placement test can be assembled for ``subject_code`` right now.

        No write. Excludes this student's prior placement questions for the
        same subject from the eligible pool (D4.6 §4) — a student who has
        exhausted the pool is told so, not silently offered a repeat.
        """
        student_uuid = _as_uuid(student_id)
        result = self._assemble(student_uuid, subject_code)
        return _to_availability(result)

    # -- Create (S-03 → S-04) ------------------------------------------------

    def create(self, student_id: uuid.UUID | str, subject_code: str) -> PlacementCreated:
        """Assemble and self-assign a placement test.

        One transaction: the ``Quiz``, its self-``QuizAssignment``, and every
        frozen ``QuizQuestion`` snapshot, or nothing at all.

        Raises:
            PlacementUnavailableError: Assembly did not clear the viability
                floor (→ 409); carries the identical payload
                :meth:`availability` would have returned.
        """
        student_uuid = _as_uuid(student_id)
        title = _placement_title(subject_code)
        with self._sessionmaker() as session, session.begin():
            candidates = self._load_candidates(session, subject_code)
            exclude_bank_ids = self._load_excluded_bank_ids(session, student_uuid, subject_code)
            timings = self._timings_for(session, student_uuid, subject_code)
            result = assemble(candidates, timings, exclude_bank_ids=exclude_bank_ids)
            if isinstance(result, Unavailable):
                raise PlacementUnavailableError(_to_availability(result))

            selected_ids = [s.candidate.question_bank_id for s in result.selected]
            bank_rows = {
                row.id: row
                for row in session.scalars(
                    select(QuestionBank).where(QuestionBank.id.in_(selected_ids))
                ).all()
            }

            quiz = Quiz(
                teacher_id=None,
                student_id=student_uuid,
                kind=QuizKind.placement,
                subject_code=subject_code,
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

            for position, selected in enumerate(result.selected, start=1):
                bank_obj = bank_rows[selected.candidate.question_bank_id]
                qq = _snapshot_bank_row(
                    _to_row(bank_obj),
                    quiz_id=quiz.id,
                    question_ref=f"q{position}",
                    position=position,
                )
                session.add(qq)
            session.flush()

            return PlacementCreated(
                assignment_id=assignment.id,
                quiz_id=quiz.id,
                question_count=result.question_count,
                topic_count=result.syllabus_topic_count,
                estimated_minutes=result.estimated_minutes,
            )

    # -- Result (S-05) --------------------------------------------------------

    def result(
        self, student_id: uuid.UUID | str, assignment_id: uuid.UUID | str
    ) -> PlacementResultRow:
        """The S-05 payload: marks, topic breakdown, and the level-estimate flag.

        Reads ``WeaknessRecord`` rows verbatim (D4.6 §6) — no recomputation,
        no second weakness engine. ``marked=False`` (with every list/count
        field empty) when the submission has not been marked yet, rather
        than a half-true result.

        Raises:
            PlacementNotFoundError: No assignment exists with
                ``assignment_id``, anywhere (404).
            PlacementOwnershipError: The assignment exists but is not the
                caller's (403) — an id that exists anywhere is a 403, not a
                404, mirroring ``QuizTakingService``'s accepted trade-off.
        """
        student_uuid = _as_uuid(student_id)
        assignment_uuid = _as_uuid(assignment_id)
        with self._sessionmaker() as session:
            assignment = session.get(QuizAssignment, assignment_uuid)
            if assignment is None:
                raise PlacementNotFoundError(f"Unknown assignment: {assignment_uuid}")
            if assignment.student_id != student_uuid:
                raise PlacementOwnershipError(
                    f"Assignment {assignment_uuid} is not assigned to student {student_uuid}"
                )
            quiz = session.get(Quiz, assignment.quiz_id)
            if quiz is None:  # pragma: no cover - FK guarantees the row exists
                raise PlacementError(f"Unknown quiz: {assignment.quiz_id}")

            submission = session.scalars(
                select(QuizSubmission).where(
                    QuizSubmission.assignment_id == assignment_uuid,
                    QuizSubmission.student_id == student_uuid,
                )
            ).first()
            if (
                submission is None
                or submission.status != QuizSubmissionStatus.marked
                or submission.attempt_id is None
            ):
                return PlacementResultRow(
                    assignment_id=assignment_uuid,
                    quiz_id=quiz.id,
                    subject_code=quiz.subject_code,
                    marked=False,
                    awarded_marks=None,
                    maximum_marks=None,
                    questions=[],
                    topic_breakdown=[],
                    spans_multiple_bands=False,
                )

            attempt = session.get(Attempt, submission.attempt_id)
            if attempt is None:  # pragma: no cover - FK guarantees the row exists
                raise PlacementError(f"Unknown attempt: {submission.attempt_id}")
            question_results = session.scalars(
                select(QuestionResult).where(QuestionResult.attempt_id == attempt.id)
            ).all()
            weaknesses = session.scalars(
                select(WeaknessRecord).where(WeaknessRecord.attempt_id == attempt.id)
            ).all()
            bands = session.scalars(
                select(QuizQuestion.difficulty).where(
                    QuizQuestion.quiz_id == quiz.id,
                    QuizQuestion.status == QuizQuestionStatus.included,
                )
            ).all()

            return PlacementResultRow(
                assignment_id=assignment_uuid,
                quiz_id=quiz.id,
                subject_code=quiz.subject_code,
                marked=True,
                awarded_marks=attempt.awarded_marks,
                maximum_marks=attempt.maximum_marks,
                questions=[
                    PlacementQuestionResult(
                        question_ref=qr.question_id,
                        topic=qr.topic,
                        awarded_marks=qr.effective_marks,
                        maximum_marks=qr.maximum_marks,
                    )
                    for qr in question_results
                ],
                topic_breakdown=[
                    PlacementTopicBreakdown(
                        topic=w.topic,
                        lost_marks=w.lost_marks,
                        maximum_marks=w.maximum_marks,
                        accuracy=w.accuracy,
                    )
                    for w in weaknesses
                ],
                spans_multiple_bands=len(set(bands)) >= 2,
            )

    # -- Internals --------------------------------------------------------------

    def _assemble(self, student_uuid: uuid.UUID, subject_code: str) -> Assembly | Unavailable:
        with self._sessionmaker() as session:
            candidates = self._load_candidates(session, subject_code)
            exclude_bank_ids = self._load_excluded_bank_ids(session, student_uuid, subject_code)
            timings = self._timings_for(session, student_uuid, subject_code)
        return assemble(candidates, timings, exclude_bank_ids=exclude_bank_ids)

    def _timings_for(
        self, session: Session, student_uuid: uuid.UUID, subject_code: str
    ) -> dict[int, PaperTiming]:
        """The subject's paper timings, narrowed to the papers this student will sit.

        D4.6 §5 says selection runs "across the topics of the papers the
        student's ``student_enrolment_papers`` rows say they will sit". That
        clause is load-bearing for a tiered subject: 0625 Core is papers 1/3
        and Extended is 2/4, so measuring a Core student on Extended questions
        would overstate their weakness in every topic it touched, and P4.7
        builds a study plan out of exactly those weakness rows.

        The narrowing is applied to ``timings`` rather than to the candidate
        list so that :func:`~lemely.core.placement.assemble` remains the one
        place that decides "ineligible" — a paper the student will not sit has
        no rate, and a candidate with no rate is already excluded there.

        **A student with no enrolment-paper rows is not narrowed at all.**
        Every S-02 field is skippable (D4.5), so an absent row means "not
        answered", never "sits no papers"; treating silence as an empty
        allowlist would make placement unavailable for every student who
        skipped that question, which is a defaulted answer wearing a filter's
        clothes (spec §1.4).
        """
        timings = get_paper_timings(subject_code)
        enrolled = enrolled_paper_numbers(session, student_uuid, subject_code)
        if not enrolled:
            return dict(timings)
        return {number: timing for number, timing in timings.items() if number in enrolled}

    def _load_candidates(self, session: Session, subject_code: str) -> list[Candidate]:
        """Every ``source=past_paper`` bank row for this subject, paper-joined.

        D4.6 §5 names only ``source='past_paper'`` as relevant today — no
        further filter is invented. A row whose ``paper_id`` is unset
        (unlinked, D4.8 §1) still comes back, with ``paper_number=None``;
        :func:`~lemely.core.placement.assemble` is what excludes it, so
        there is exactly one place that decides "ineligible".

        P4.8 chunk 0 adds :func:`~lemely.db.question_bank_repo.
        renderable_bank_filter`: this loader builds its own subject/source/
        ``is_active`` filter rather than calling
        :func:`~lemely.db.question_bank_repo.visible_bank_filter` (placement
        is always direct-to-student, never owner/school scoped — see the
        class docstring), so the figure-dependency exclusion has to be
        applied here explicitly too, not inherited from a shared visibility
        seam it never used.
        """
        stmt = (
            select(
                QuestionBank.id,
                QuestionBank.topic,
                QuestionBank.total_marks,
                QuestionBank.difficulty,
                Paper.paper_number,
            )
            .outerjoin(Paper, Paper.id == QuestionBank.paper_id)
            .where(
                QuestionBank.subject_code == subject_code,
                QuestionBank.source == QuestionSource.past_paper,
                QuestionBank.is_active.is_(True),
                renderable_bank_filter(),
            )
        )
        return [
            Candidate(
                question_bank_id=row.id,
                topic=row.topic,
                paper_number=row.paper_number,
                total_marks=row.total_marks,
                difficulty=row.difficulty.value,
            )
            for row in session.execute(stmt).all()
        ]

    def _load_excluded_bank_ids(
        self, session: Session, student_uuid: uuid.UUID, subject_code: str
    ) -> frozenset[uuid.UUID]:
        """``question_bank_id``s frozen onto this student's prior placement quizzes.

        Scoped to the same subject as the new attempt (D4.6 §4).

        Scoped by ``Quiz.student_id == caller`` — an owner predicate, never a
        ``kind``-only filter (D4.6 §3) — narrowed by ``kind == placement`` and
        ``subject_code`` on top of that owner scope.
        """
        ids = session.scalars(
            select(QuizQuestion.question_bank_id)
            .join(Quiz, Quiz.id == QuizQuestion.quiz_id)
            .where(
                Quiz.student_id == student_uuid,
                Quiz.kind == QuizKind.placement,
                Quiz.subject_code == subject_code,
                QuizQuestion.question_bank_id.is_not(None),
            )
        ).all()
        return frozenset(i for i in ids if i is not None)


def _to_availability(result: Assembly | Unavailable) -> PlacementAvailability:
    if isinstance(result, Assembly):
        return PlacementAvailability(
            available=True,
            reason=None,
            question_count=result.question_count,
            topic_count=result.syllabus_topic_count,
            estimated_minutes=result.estimated_minutes,
        )
    return PlacementAvailability(
        available=False,
        reason=result.reason.value,
        question_count=result.eligible_questions,
        topic_count=result.eligible_topics,
        estimated_minutes=result.estimated_minutes,
    )


def _placement_title(subject_code: str) -> str:
    """``"<Subject name> Placement Test"``, the transcribed name — never invented.

    Falls back to the bare code only when no bundled taxonomy names the
    subject; in practice :meth:`PlacementService.create` never reaches this
    branch for a subject the assembler just found ≥4 topiced syllabus topics
    in, since topic classification itself requires that same taxonomy.
    """
    taxonomy = get_taxonomy(subject_code)
    subject_name = taxonomy.subject_name if taxonomy is not None else subject_code
    return f"{subject_name} Placement Test"


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    """Coerce a str/UUID to :class:`uuid.UUID`, raising ``ValueError`` if invalid."""
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Identifier must be a UUID, got {value!r}") from exc


__all__ = [
    "PlacementAvailability",
    "PlacementCreated",
    "PlacementError",
    "PlacementNotFoundError",
    "PlacementOwnershipError",
    "PlacementQuestionResult",
    "PlacementResultRow",
    "PlacementService",
    "PlacementTopicBreakdown",
    "PlacementUnavailableError",
]
