"""Quiz marking service: adapt, mark, and persist a submitted quiz (P3.5 chunk F1).

``docs/quiz-model.md`` §4.2 — "one marking road, not two". A quiz question is
adapted into a core :class:`~lemely.core.loose_schemas.Question`
(:func:`quiz_question_to_scheme_question`), assembled into an in-memory
:class:`~lemely.core.loose_schemas.MarkScheme`, and run through the
**existing** :func:`~lemely.io.correction_ai.correct_paper` — the identical
hybrid deterministic-MCQ / ``AICorrector`` engine a past paper uses, with the
same confidence escalation and :data:`~lemely.core.schemas.REVIEW_CONFIDENCE_THRESHOLD`
gate. No new marking engine, no new prompt. The result is persisted through
:meth:`~lemely.db.attempt_repo.AttemptRepository.persist_quiz_correction` —
the same writer a past paper uses (``docs/quiz-model.md`` §4.4) — so a
low-confidence quiz answer lands in the exact same review queue P3.4 built.

Mirrors :mod:`lemely.db.quiz_taking_repo`'s shape: an injected ``sessionmaker``,
an injected zero-arg clock, module-level error classes, frozen dataclass row
DTOs. Unlike that module, this one legitimately talks to Gemini (via
``correct_paper``/``apply_integrity_checks``) — that I/O is deliberately kept
out of :mod:`lemely.db.quiz_taking_repo` (the module docstring there is
explicit: quiz *taking* is I/O-free of Gemini) and out of any DB transaction:
every DB read needed to build the marking call happens in one short session,
which is closed *before* ``correct_paper`` runs, and the persist/status-update
writes happen in fresh, short transactions afterwards. Holding a transaction
open across a multi-question Gemini round trip would hold row locks for the
duration of that round trip, which is exactly the cost ``docs/quiz-model.md``
§4.2 says background marking exists to avoid at the HTTP layer — the same
discipline applies one layer down, inside this service.

**Integrity checks — applied, deliberately** (the brief calls this out as a
decision to make explicitly). ``apply_integrity_checks`` (plagiarism +
AI-detection) runs here exactly as it does for a past paper in
``lemely.web.services.grading.grade_paper``. Reasoning: a quiz answer is a
*typed* text-box response — if anything, more trivially copy-pasteable than a
scanned/OCR'd handwritten past-paper answer, so AI-detection is at least as
relevant here, not less. Plagiarism checking compares against
``expected_answer``, which (as for past papers) only :func:`_build_mcq_corrected`
ever sets, so in practice it is a no-op for the open-ended questions a quiz
mostly carries — the same pre-existing shape as the past-paper path, not a
quiz-specific gap this chunk introduces. Applying the checks is also free by
default: plagiarism is pure ``difflib`` (no Gemini call) and AI-detection is
opt-in, off by default (``IntegritySettings.ai_detection_enabled=False``), so
enabling it costs nothing unless a deployment has already chosen to spend on
it for past papers too. This decision only changes which flags *can* arrive
set on a question result — the review-queue fan-out itself
(:meth:`~lemely.db.attempt_repo.AttemptRepository._persist`) is unchanged
either way (``docs/quiz-model.md`` §4.5).

**Idempotent.** Marking an already-``marked`` submission is a no-op (returns
the existing result without re-marking or re-persisting). Marking a
submission that is not ``submitted`` is a validation error — see
:meth:`QuizMarkingService.mark_submission`.

**On marking failure**, ``quiz_submissions.marking_error`` is set and
``status`` is left at ``submitted`` (the column exists for exactly this,
``lemely.db.models.quizzes.QuizSubmission``'s docstring). This applies only to
failures in the "do the actual marking" phase (building the in-memory mark
scheme, ``correct_paper``, ``apply_integrity_checks``, persisting) — a bad
``submission_id`` or a submission in the wrong state is a genuine caller
error and still raises, exactly like every other repository in this codebase.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import select

from lemely.core.analytics import summarize_weaknesses
from lemely.core.loose_schemas import (
    AnswerPoint,
    MarkScheme,
    MarkSchemeMetadata,
    MCQAnswer,
    PaperType,
    Question,
    QuestionType,
    SchemeFormat,
)
from lemely.core.loose_schemas import SessionMonth as LooseSessionMonth
from lemely.core.schemas import ExtractedAnswer, ExtractedAnswers
from lemely.db.attempt_repo import fill_correction_topics
from lemely.db.models.enums import QuizQuestionStatus, QuizSubmissionStatus
from lemely.db.models.quizzes import Quiz, QuizAnswer, QuizAssignment, QuizQuestion, QuizSubmission
from lemely.io.correction_ai import correct_paper
from lemely.io.integrity import apply_integrity_checks
from lemely.runtime.config import IntegritySettings

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session, sessionmaker

    from lemely.db.attempt_repo import AttemptRepository
    from lemely.io.gemini import GeminiClient

log = structlog.get_logger(__name__)


def _utcnow() -> datetime:
    """Default clock: aware UTC now. Production wiring only — tests inject their own."""
    return datetime.now(UTC)


class QuizMarkingError(Exception):
    """Base class for quiz marking failures."""


class QuizMarkingNotFoundError(QuizMarkingError):
    """No submission exists for the supplied id (→ 404)."""


class QuizMarkingValidationError(QuizMarkingError):
    """The submission is not in a markable state (→ 422)."""


@dataclass(frozen=True, slots=True)
class MarkSubmissionResult:
    """Outcome of one :meth:`QuizMarkingService.mark_submission` call.

    Deliberately carries nothing from the mark scheme or the student's
    answers — no ``modelAnswer``/``markSchemePoints``/``mcqAnswer``, no
    per-question breakdown — the same structural exclusion
    ``lemely.db.quiz_taking_repo.QuizTakeQuestionRow`` uses (D3.8): F1 adds
    no student-facing read of the marking result at all, so there is nothing
    here for such a field to leak into.
    """

    submission_id: uuid.UUID
    status: QuizSubmissionStatus
    attempt_id: uuid.UUID | None
    marking_error: str | None


class QuizMarkingService:
    """Mark a submitted quiz and persist it as an ordinary quiz-origin ``Attempt``.

    Constructed with a ``sessionmaker``, the :class:`~lemely.db.attempt_repo.AttemptRepository`
    singleton every other marking path persists through (so a quiz mark and a
    past-paper mark share the exact same writer), a
    :class:`~lemely.io.gemini.GeminiClient`, and an injectable clock. Never
    called directly by the router that triggers it — see
    ``lemely.web.routers.quiz``'s background-thread wiring, which keeps a
    multi-question Gemini round trip out of the request/response cycle
    (``docs/quiz-model.md`` §4.2).
    """

    def __init__(
        self,
        sessionmaker: sessionmaker[Session],
        attempt_repo: AttemptRepository,
        gemini_client: GeminiClient,
        *,
        integrity_settings: IntegritySettings | None = None,
        now: Callable[[], datetime] = _utcnow,
    ) -> None:
        """Wire the service to its collaborators and clock.

        ``integrity_settings`` defaults to a fresh
        :class:`~lemely.runtime.config.IntegritySettings` (plagiarism on,
        AI-detection off) when omitted.
        """
        self._sessionmaker = sessionmaker
        self._attempt_repo = attempt_repo
        self._gemini_client = gemini_client
        self._integrity_settings = integrity_settings
        self._now = now

    def mark_submission(self, submission_id: uuid.UUID | str) -> MarkSubmissionResult:
        """Mark one submitted quiz submission, persist it, and advance its status.

        Sequence (``docs/quiz-model.md`` §4.2): load the frozen ``included``
        ``quiz_questions`` and this submission's ``quiz_answers``; adapt each
        question with :func:`quiz_question_to_scheme_question`; run the
        assembled :class:`~lemely.core.loose_schemas.MarkScheme` through
        ``correct_paper`` + ``apply_integrity_checks`` (module docstring); no
        grade prediction; persist via
        :meth:`~lemely.db.attempt_repo.AttemptRepository.persist_quiz_correction`;
        set ``attempt_id``/``status=marked``/``marked_at``.

        Idempotent: a submission already ``marked`` is returned unchanged, no
        re-marking or re-persisting.

        Raises:
            QuizMarkingNotFoundError: No submission exists with
                ``submission_id`` (404).
            QuizMarkingValidationError: The submission's status is neither
                ``submitted`` nor ``marked`` — i.e. ``not_started`` or
                ``in_progress``, which cannot yet be marked (422).
        """
        submission_uuid = _as_uuid(submission_id)

        with self._sessionmaker() as session:
            submission = session.get(QuizSubmission, submission_uuid)
            if submission is None:
                raise QuizMarkingNotFoundError(f"Unknown submission: {submission_uuid}")
            if submission.status == QuizSubmissionStatus.marked:
                return MarkSubmissionResult(
                    submission_id=submission_uuid,
                    status=submission.status,
                    attempt_id=submission.attempt_id,
                    marking_error=submission.marking_error,
                )
            if submission.status != QuizSubmissionStatus.submitted:
                raise QuizMarkingValidationError(
                    f"Submission {submission_uuid} is {submission.status.value}; only a "
                    "'submitted' submission can be marked"
                )

            assignment = session.get(QuizAssignment, submission.assignment_id)
            if assignment is None:  # pragma: no cover - FK guarantees the row exists
                raise QuizMarkingError(f"Unknown assignment: {submission.assignment_id}")
            quiz = session.get(Quiz, assignment.quiz_id)
            if quiz is None:  # pragma: no cover - FK guarantees the row exists
                raise QuizMarkingError(f"Unknown quiz: {assignment.quiz_id}")

            questions = session.scalars(
                select(QuizQuestion)
                .where(
                    QuizQuestion.quiz_id == quiz.id,
                    QuizQuestion.status == QuizQuestionStatus.included,
                )
                .order_by(QuizQuestion.position)
            ).all()
            answers_by_question = {
                a.quiz_question_id: a
                for a in session.scalars(
                    select(QuizAnswer).where(QuizAnswer.submission_id == submission.id)
                ).all()
            }

            # Everything needed to build the marking call, snapshotted before
            # leaving the session — the Gemini round trip below must not run
            # inside an open DB session/transaction (module docstring).
            subject_code = quiz.subject_code
            student_id = submission.student_id
            scheme_questions = [quiz_question_to_scheme_question(q) for q in questions]
            extracted = ExtractedAnswers(
                paper_id=str(assignment.id),
                source_scan="quiz",
                answers=[
                    ExtractedAnswer(
                        question_id=q.question_ref,
                        answer=(
                            answers_by_question[q.id].answer_text or ""
                            if q.id in answers_by_question
                            else ""
                        ),
                        confidence=1.0,
                        working_out=(
                            answers_by_question[q.id].working_text
                            if q.id in answers_by_question
                            else None
                        ),
                    )
                    for q in questions
                ],
            )

        try:
            mark_scheme = _build_mark_scheme(subject_code, scheme_questions)
            correction = correct_paper(
                mark_scheme=mark_scheme,
                extracted_answers=extracted,
                gemini_client=self._gemini_client,
            )
            correction = apply_integrity_checks(
                correction,
                mark_scheme,
                gemini_client=self._gemini_client,
                settings=self._integrity_settings or IntegritySettings(),
            )
            # P4.4: fill CorrectedQuestion.topic before summarize_weaknesses
            # groups on it — see lemely.db.attempt_repo's module docstring for
            # why this must happen here rather than at persist time.
            fill_correction_topics(correction, mark_scheme)
            weaknesses = summarize_weaknesses(correction)
            attempt_id = self._attempt_repo.persist_quiz_correction(
                user_id=str(student_id),
                correction=correction,
                weaknesses=weaknesses,
                recorded_at=self._now().isoformat(),
            )
        except Exception as exc:
            error_text = str(exc)
            log.warning("quiz_marking_failed", submission_id=str(submission_uuid), error=error_text)
            with self._sessionmaker() as session, session.begin():
                row = session.get(QuizSubmission, submission_uuid, with_for_update=True)
                if row is not None:
                    row.marking_error = error_text
            return MarkSubmissionResult(
                submission_id=submission_uuid,
                status=QuizSubmissionStatus.submitted,
                attempt_id=None,
                marking_error=error_text,
            )

        marked_at = self._now()
        with self._sessionmaker() as session, session.begin():
            row = session.get(QuizSubmission, submission_uuid, with_for_update=True)
            if row is None:  # pragma: no cover - defensive; row existed moments ago
                raise QuizMarkingError(f"Unknown submission: {submission_uuid}")
            row.attempt_id = attempt_id
            row.status = QuizSubmissionStatus.marked
            row.marked_at = marked_at
            row.marking_error = None
        return MarkSubmissionResult(
            submission_id=submission_uuid,
            status=QuizSubmissionStatus.marked,
            attempt_id=attempt_id,
            marking_error=None,
        )


def _split_marks_evenly(total_marks: int, point_count: int) -> list[int]:
    """Distribute a question's total marks across its mark-scheme points.

    ``question_bank``/``quiz_questions`` store each point as bare text
    (``mark_scheme_points: list[str]``) with no per-point mark breakdown —
    ``docs/quiz-model.md`` §4.2 step 3 leaves this as ``marks=…``. Splits
    ``total_marks`` by floor division, adding the remainder one point at a
    time starting from the first, so the sum always equals ``total_marks``
    exactly (never exceeds it, which
    :meth:`~lemely.core.loose_schemas.Question.validate_mark_point_sum` would
    reject) without fabricating any finer-grained information than "credit is
    spread evenly" — which does not change what a student can actually score:
    ``AICorrector.mark_question``'s ``awarded_marks`` comes from the model's
    own independent judgement of the whole answer, not a sum of point marks,
    so this split only shapes the mark-scheme text a marker reads, never a
    student's mark.

    Returns ``[]`` when ``point_count`` is 0 (a question with no
    mark-scheme-point text, e.g. many MCQ rows).
    """
    if point_count <= 0:
        return []
    base, remainder = divmod(total_marks, point_count)
    return [base + (1 if i < remainder else 0) for i in range(point_count)]


def quiz_question_to_scheme_question(qq: QuizQuestion) -> Question:
    """Adapt one materialized quiz question into a core marking :class:`Question`.

    The pure adapter named in ``docs/quiz-model.md`` §4.2 step 3 — a
    module-level function over the ORM row (not a method, not a DB session),
    so it is unit-testable in isolation:

    * ``id=qq.question_ref`` — becomes ``Question.id`` and therefore
      ``question_results.question_id``, one identifier end to end.
    * ``marks=qq.total_marks``, ``type=QuestionType(qq.question_type)``,
      ``topic_hint=qq.topic``.
    * ``answer_points`` — one :class:`~lemely.core.loose_schemas.AnswerPoint`
      per ``qq.mark_scheme_points`` entry, ``id=f"p{i+1}"``, ``point=<text>``,
      ``marks=`` :func:`_split_marks_evenly`'s per-point share.
    * ``mcq_answer`` — set (as :class:`~lemely.core.loose_schemas.MCQAnswer`)
      only when ``type == QuestionType.MCQ``; the
      :class:`~lemely.core.loose_schemas.Question` validator rejects an
      ``mcq_answer`` on any other type, so this must not be set
      unconditionally.

    Raises:
        pydantic.ValidationError: ``qq``'s snapshot does not describe a valid
            :class:`Question` for its type (e.g. an MCQ row with no
            ``mcq_answer``, or a ``levels_based`` row with no descriptors —
            neither of which any current writer produces, but this adapter
            does not special-case around a malformed row; the caller treats
            this as a marking failure, see the module docstring).
    """
    question_type = QuestionType(qq.question_type)
    marks_per_point = _split_marks_evenly(qq.total_marks, len(qq.mark_scheme_points))
    answer_points = [
        AnswerPoint(id=f"p{i + 1}", point=text, marks=marks_per_point[i])
        for i, text in enumerate(qq.mark_scheme_points)
    ]
    mcq_answer = (
        MCQAnswer(qq.mcq_answer)
        if question_type == QuestionType.MCQ and qq.mcq_answer is not None
        else None
    )
    return Question(
        id=qq.question_ref,
        marks=qq.total_marks,
        type=question_type,
        topic_hint=qq.topic,
        answer_points=answer_points,
        mcq_answer=mcq_answer,
    )


def _build_mark_scheme(subject_code: str, questions: list[Question]) -> MarkScheme:
    """Synthesize the in-memory :class:`MarkScheme` the marking call needs.

    ``docs/quiz-model.md`` §4.3, the synthetic-metadata trap:
    :class:`~lemely.core.schemas.ExamMetadata` (which ``correct_paper``
    derives from this scheme's metadata) requires a 4-digit subject code and
    ``paper_number``/``paper_variant`` in 1..9 — a quiz has a subject code and
    nothing else. ``paper_number=1``, ``paper_variant=1``,
    ``session_month="Specimen"`` are pure fictions that exist **only** to
    satisfy this in-memory call; the caller
    (:meth:`QuizMarkingService.mark_submission`) hands the resulting
    :class:`~lemely.core.schemas.CorrectionResult` to
    ``AttemptRepository.persist_quiz_correction``, which never reads them
    (see that method's docstring). ``paper_type``/``scheme_format`` are
    generic placeholders with no marking-relevant effect: ``paper_type`` is
    deliberately not ``PaperType.MCQ`` (which would trigger
    :meth:`MarkScheme.validate_maximum_mark`'s MCQ-only "every mark must sum
    to the paper total" check against a quiz that may mix MCQ and non-MCQ
    questions).
    """
    # `or 1`: MarkSchemeMetadata.maximum_mark requires >=1; a real quiz always
    # has at least one positive-mark question, but this guards the
    # defensive edge case of an all-zero-mark set without ever persisting
    # the fallback value (see module docstring).
    maximum_mark = sum(q.marks for q in questions) or 1
    metadata = MarkSchemeMetadata(
        subject=subject_code,
        subject_code=subject_code,
        paper_number=1,
        paper_variant=1,
        session_month=LooseSessionMonth.SPECIMEN,
        session_year=None,
        paper_type=PaperType.THEORY_CORE,
        maximum_mark=maximum_mark,
        scheme_format=SchemeFormat.MIXED,
    )
    return MarkScheme(metadata=metadata, questions=questions)


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    """Coerce a str/UUID to :class:`uuid.UUID`, raising ``ValueError`` if invalid."""
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Identifier must be a UUID, got {value!r}") from exc


__all__ = [
    "MarkSubmissionResult",
    "QuizMarkingError",
    "QuizMarkingNotFoundError",
    "QuizMarkingService",
    "QuizMarkingValidationError",
    "quiz_question_to_scheme_question",
]
