"""Full-report persistence for the student self-mark and quiz marking pipelines.

Where :class:`~lemely.db.history_repo.DbHistoryStore` persists the *totals-only*
:class:`~lemely.core.history.PaperRecord`, this repository persists the complete
marking output — one :class:`~lemely.db.models.attempts.Attempt` plus a
:class:`~lemely.db.models.attempts.QuestionResult` per marked question, a
:class:`~lemely.db.models.attempts.WeaknessRecord` per weak area, and a
:class:`~lemely.db.models.ops.ReviewQueueItem` for every question that needs a
teacher's eyes. Everything lands in a single transaction so a partially-written
attempt is never observable.

**One writer, not two** (``docs/quiz-model.md`` §4.4). :meth:`persist_correction`
(a self-marked past paper, with a :class:`~lemely.core.schemas.GradePrediction`)
and :meth:`persist_quiz_correction` (a marked quiz, P3.5 chunk F1 — no
prediction, a quiz has no grade boundaries) are both thin wrappers around the
private :meth:`_persist`, which is where the row assembly and the review-queue
fan-out (low_confidence / plagiarism_flag / ai_detection_flag) actually live.
Copying that fan-out into a second method — rather than sharing it — is exactly
how one of the three reasons for flagging would quietly stop firing for
quizzes; see ``docs/quiz-model.md`` §4.4.

Core→DB enum mapping is by ``.value`` (the core :class:`StrEnum`s and the DB
:class:`enum.Enum`s share their string members), reusing
:func:`~lemely.db.history_repo.parse_user_id` / ``month_to_enum`` for the two
impedance mismatches (str id → UUID FK, month label → enum).

**P4.4 — filling ``CorrectedQuestion.topic`` on the marking side.** D4.4 §6:
``CorrectedQuestion.topic`` comes from ``topic_hint`` on the parsed mark
scheme, which was measured ``None`` on every one of the 637 questions across
the 33 deterministically-parsed 0625 schemes in ``outputs/schemes/`` — so the
weakness engine grouped every real-paper question under ``"unknown"``.
:func:`fill_correction_topics` closes that gap by running the same
deterministic keyword classifier the bank side uses
(:func:`~lemely.db.question_bank_repo.classify_bank_topics`) against the
marking side's own text. It lives here — in ``lemely.db``, which (unlike
``lemely.core``) has no import-linter layering contract — because it must
compose :mod:`lemely.core.topics` (the pure classifier) with
:mod:`lemely.io.syllabus_topics` (the taxonomy loader), and ``core.correction``
cannot reach the loader without either a signature change through every
marking caller or a layering violation.

Both marking paths — :func:`~lemely.web.services.grading.grade_paper` (past
paper) and :meth:`~lemely.db.quiz_marking_repo.QuizMarkingService.mark_submission`
(quiz) — call :func:`fill_correction_topics` immediately after
``apply_integrity_checks`` and **before** ``summarize_weaknesses``, not inside
:meth:`AttemptRepository._persist`. Both already computed a ``WeaknessReport``
before calling ``persist_correction``/``persist_quiz_correction``, so filling
the topic only at ``_persist`` time would have corrected the topic written
onto each ``QuestionResult`` row without ever changing the topic **grouping**
``summarize_weaknesses`` already committed to — which is the entire point of
this fill (P4.5 practice-targets-weakness needs the grouping, not just the
column).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from lemely.core.schemas import REVIEW_CONFIDENCE_THRESHOLD
from lemely.core.topics import classify, is_writable
from lemely.db.history_repo import month_to_enum, parse_user_id
from lemely.db.models.attempts import Attempt, QuestionResult, WeaknessRecord
from lemely.db.models.enums import AttemptOrigin, BoundarySource, MarkerSource, ReviewReason
from lemely.db.models.enums import ConfidenceBand as DBConfidenceBand
from lemely.db.models.ops import ReviewQueueItem
from lemely.io.syllabus_topics import get_taxonomy

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence

    from sqlalchemy.orm import Session, sessionmaker

    from lemely.core.loose_schemas import MarkScheme, Question
    from lemely.core.schemas import (
        AccuracyReport,
        CorrectedQuestion,
        CorrectionResult,
        GradePrediction,
        WeaknessReport,
    )
    from lemely.core.topics import SyllabusTaxonomy

# The review threshold now has exactly one definition, in
# :mod:`lemely.core.schemas` (D2.2) — the marking layer, this repository and the
# teacher console all read that constant, so the persist-time review gate can no
# longer drift from the flag the marker set or from what the accuracy harness
# measures. Re-exported here because this module's name for it is part of its
# public surface.

#: Explicit weakest-to-strongest ordering for :class:`DBConfidenceBand`, used
#: by :meth:`AttemptRepository._persist` to derive a paper-level confidence
#: band when there is no :class:`~lemely.core.schemas.GradePrediction` to
#: carry one (a quiz, ``docs/quiz-model.md`` §4.4). Written out explicitly
#: rather than relying on enum declaration order, which happens to agree
#: today but is not a contract — the same implicit-coupling trap D3.6 warns
#: against elsewhere in this build.
_CONFIDENCE_BAND_WEAKNESS_ORDER: dict[DBConfidenceBand, int] = {
    DBConfidenceBand.low: 0,
    DBConfidenceBand.medium: 1,
    DBConfidenceBand.high: 2,
}


class AttemptRepository:
    """Persist marking output as relational attempt rows (past paper or quiz)."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        """Bind the repository to a ``sessionmaker`` (one op = one transaction)."""
        self._sm = session_factory

    def persist_correction(
        self,
        *,
        user_id: str,
        report: AccuracyReport,
        upload_id: uuid.UUID | None = None,
        recorded_at: str | None = None,
    ) -> uuid.UUID:
        """Persist a self-marked past paper's :class:`AccuracyReport`.

        Thin wrapper around :meth:`_persist`: carries the report's
        :class:`~lemely.core.schemas.GradePrediction` and tags the attempt
        ``origin=past_paper``. Public signature and behaviour unchanged from
        before the P3.5 chunk F1 refactor.

        Args:
            user_id: Owning user's id — must be a UUID string already present in
                ``users`` (the FK is enforced).
            report: The assembled marking report to persist.
            upload_id: The source upload row, when the attempt came from one.
            recorded_at: ISO timestamp for the attempt; defaults to now (UTC).

        Returns:
            The id of the newly-created :class:`Attempt`.

        Raises:
            ValueError: ``user_id`` is not a valid UUID, or ``session_month`` is
                not a recognised CAIE label.
        """
        return self._persist(
            owner=parse_user_id(user_id),
            correction=report.correction,
            weaknesses=report.weaknesses,
            prediction=report.grade_prediction,
            origin=AttemptOrigin.past_paper,
            upload_id=upload_id,
            recorded_at=recorded_at,
        )

    def persist_quiz_correction(
        self,
        *,
        user_id: str,
        correction: CorrectionResult,
        weaknesses: WeaknessReport,
        recorded_at: str | None = None,
    ) -> uuid.UUID:
        """Persist a marked quiz submission (P3.5 chunk F1, ``docs/quiz-model.md`` §4).

        Thin wrapper around :meth:`_persist`: no
        :class:`~lemely.core.schemas.GradePrediction` (a quiz has no grade
        boundaries) and tags the attempt ``origin=quiz``.

        **The synthetic-metadata trap (§4.3).** ``correction.metadata`` was
        built with a *synthetic* ``paper_number=1``/``paper_variant=1``/
        ``session_month="Specimen"`` purely to satisfy
        :class:`~lemely.core.schemas.ExamMetadata`'s validators for the
        in-memory marking call (see
        :func:`~lemely.db.quiz_marking_repo.quiz_question_to_scheme_question`'s
        caller). ``_persist`` never reads those three fields (nor
        ``session_year``) when ``prediction is None`` — only
        ``subject_code`` is persisted. This is what stops a quiz from
        inventing a bogus "Paper 1/1" row in ``per_paper_comparison``.

        Args:
            user_id: Owning student's id — must be a UUID string already
                present in ``users`` (the FK is enforced).
            correction: The marked result from ``correct_paper``, run against
                the quiz's questions.
            weaknesses: The weakness summary for this submission.
            recorded_at: ISO timestamp for the attempt; defaults to now (UTC).

        Returns:
            The id of the newly-created :class:`Attempt`.

        Raises:
            ValueError: ``user_id`` is not a valid UUID.
        """
        return self._persist(
            owner=parse_user_id(user_id),
            correction=correction,
            weaknesses=weaknesses,
            prediction=None,
            origin=AttemptOrigin.quiz,
            upload_id=None,
            recorded_at=recorded_at,
        )

    def _persist(
        self,
        *,
        owner: uuid.UUID,
        correction: CorrectionResult,
        weaknesses: WeaknessReport,
        prediction: GradePrediction | None,
        origin: AttemptOrigin,
        upload_id: uuid.UUID | None,
        recorded_at: str | None,
    ) -> uuid.UUID:
        """Assemble and write one :class:`Attempt` + its child rows.

        The single writer both :meth:`persist_correction` and
        :meth:`persist_quiz_correction` call (``docs/quiz-model.md`` §4.4) —
        including the review-queue fan-out, so a low-confidence / plagiarism
        / AI-detection flag fires identically for a past paper and a quiz.

        When ``prediction is None`` (a quiz, no grade boundaries exist):

        * ``percentage`` is computed straight from the correction's own
          totals — ``round((awarded / maximum) * 100.0, 2)``, guarded to
          ``0.0`` when ``maximum`` is 0 — using the exact same expression
          :meth:`~lemely.db.review_repo.ReviewService._recompute_attempt_totals`
          uses, so a fresh quiz attempt and one just recomputed after a
          teacher override can never round differently for the same marks.
        * ``grade``, ``predicted_grade``, ``boundary_source``,
          ``session_month``, ``session_year``, ``paper_number``,
          ``paper_variant`` are all NULL — a quiz has no boundaries and no
          real paper/session (see :meth:`persist_quiz_correction`'s
          docstring on the synthetic-metadata trap).
        * ``confidence_band`` is the *weakest* per-question confidence band
          (:func:`_weakest_confidence_band`) — the paper-level confidence for
          an assessment with no grade prediction is only as strong as its
          weakest question.
        """
        meta = correction.metadata
        if prediction is not None:
            percentage = prediction.percentage
            grade: str | None = prediction.grade
            predicted_grade: str | None = prediction.grade
            boundary_source: BoundarySource | None = BoundarySource(prediction.boundary_source)
            confidence_band = DBConfidenceBand(prediction.confidence.value)
            session_month = month_to_enum(meta.session_month)
            session_year = meta.session_year
            paper_number: int | None = meta.paper_number
            paper_variant: int | None = meta.paper_variant
        else:
            maximum = correction.maximum_marks
            percentage = round((correction.awarded_marks / maximum) * 100.0, 2) if maximum else 0.0
            grade = None
            predicted_grade = None
            boundary_source = None
            confidence_band = _weakest_confidence_band(correction.questions)
            # The synthetic-metadata trap (§4.3): never persist the fictional
            # paper/session the in-memory marking call needed.
            session_month = None
            session_year = None
            paper_number = None
            paper_variant = None

        attempt = Attempt(
            user_id=owner,
            upload_id=upload_id,
            subject_code=meta.subject_code,
            session_month=session_month,
            session_year=session_year,
            paper_number=paper_number,
            paper_variant=paper_variant,
            awarded_marks=correction.awarded_marks,
            maximum_marks=correction.maximum_marks,
            percentage=percentage,
            grade=grade,
            predicted_grade=predicted_grade,
            boundary_source=boundary_source,
            confidence_band=confidence_band,
            needs_teacher_review=correction.needs_teacher_review,
            recorded_at=_parse_recorded_at(recorded_at),
            origin=origin,
        )
        attempt.question_results = [_to_question_result(cq) for cq in correction.questions]
        attempt.weakness_records = [
            WeaknessRecord(
                user_id=owner,
                topic=wa.topic,
                lost_marks=wa.lost_marks,
                maximum_marks=wa.maximum_marks,
                accuracy=wa.accuracy,
                question_ids=list(wa.question_ids),
            )
            for wa in weaknesses.weak_areas
        ]

        with self._sm.begin() as session:
            session.add(attempt)
            # Flush so ``attempt.id`` and every ``question_result.id`` are
            # populated before we build the review-queue rows that reference them.
            session.flush()
            attempt_id = attempt.id
            for qr, cq in zip(attempt.question_results, correction.questions, strict=True):
                # ``needs_teacher_review`` is also forced True by an integrity flag
                # (see ``apply_integrity_checks``), which already gets its own,
                # more specific row below — only fall back to the generic
                # low_confidence reason when something on the MARKING side (an
                # actual low confidence score, or the D2.4 structural
                # out-of-range/value-mismatch signal) is why review is needed, so
                # a high-confidence, in-range question that is *purely*
                # plagiarism/AI-detection-flagged doesn't also get a duplicate,
                # mislabeled low_confidence row.
                marking_flagged = qr.needs_teacher_review and not (
                    cq.plagiarism_flagged or cq.ai_detection_flagged
                )
                if marking_flagged or qr.confidence_score < REVIEW_CONFIDENCE_THRESHOLD:
                    session.add(
                        ReviewQueueItem(
                            attempt_id=attempt_id,
                            question_result_id=qr.id,
                            reason=ReviewReason.low_confidence,
                        )
                    )
                if cq.plagiarism_flagged:
                    session.add(
                        ReviewQueueItem(
                            attempt_id=attempt_id,
                            question_result_id=qr.id,
                            reason=ReviewReason.plagiarism_flag,
                        )
                    )
                if cq.ai_detection_flagged:
                    session.add(
                        ReviewQueueItem(
                            attempt_id=attempt_id,
                            question_result_id=qr.id,
                            reason=ReviewReason.ai_detection_flag,
                        )
                    )
        return attempt_id


def _weakest_confidence_band(questions: Sequence[CorrectedQuestion]) -> DBConfidenceBand:
    """The minimum (weakest) confidence band across a set of question results.

    Used by :meth:`AttemptRepository._persist` when there is no
    :class:`~lemely.core.schemas.GradePrediction` to carry a paper-level
    confidence (a quiz, ``docs/quiz-model.md`` §4.4): the attempt's overall
    confidence is only as strong as its weakest question. Ordering is
    :data:`_CONFIDENCE_BAND_WEAKNESS_ORDER`, not enum declaration order.

    Raises:
        ValueError: ``questions`` is empty — an attempt must always carry at
            least one question result, so there is nothing to derive a band
            from otherwise (a real invariant violation, not a defensive
            no-op; ``python -O`` strips ``assert``, so this is a ``raise``).
    """
    if not questions:
        raise ValueError("Cannot derive a confidence band from zero question results")
    return min(
        (DBConfidenceBand(cq.confidence.value) for cq in questions),
        key=lambda band: _CONFIDENCE_BAND_WEAKNESS_ORDER[band],
    )


def _to_question_result(cq: CorrectedQuestion) -> QuestionResult:
    """Map one core :class:`CorrectedQuestion` onto a :class:`QuestionResult` row."""
    return QuestionResult(
        question_id=cq.question_id,
        awarded_marks=cq.awarded_marks,
        maximum_marks=cq.maximum_marks,
        confidence_band=DBConfidenceBand(cq.confidence.value),
        confidence_score=cq.confidence_score,
        needs_teacher_review=cq.needs_teacher_review,
        marker_source=MarkerSource(cq.marker_source),
        topic=cq.topic,
        student_answer=cq.student_answer,
        expected_answer=cq.expected_answer,
        review_reason=cq.review_reason,
        feedback=cq.feedback,
        # The matched mark-scheme point ids ARE the method-mark breakdown.
        matched_point_ids=list(cq.matched_point_ids),
    )


def _parse_recorded_at(value: str | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    return datetime.fromisoformat(value)


def fill_correction_topics(correction: CorrectionResult, mark_scheme: MarkScheme) -> None:
    """Fill missing ``CorrectedQuestion.topic`` labels via the P4.2 classifier (P4.4).

    Must be called **before** ``summarize_weaknesses`` — see the module
    docstring's P4.4 section for why the fill has to happen there rather than
    in :meth:`AttemptRepository._persist`. Mutates ``correction.questions`` in
    place: ``CorrectedQuestion`` is not a frozen model, and every downstream
    reader (``summarize_weaknesses``, ``_persist``) reads these same objects.

    Text signal: a mark scheme carries no question stem or MCQ option text
    (that lives in the question paper, which this function never sees) — see
    :func:`_classification_text` for what it uses instead. Deliberately
    **not** ``CorrectedQuestion.student_answer``/``expected_answer``: those
    are the *answer's* wording, and classifying on it would point a topic
    label at whatever vocabulary the student happened to use rather than at
    the question itself (D4.4's "MCQ options carry the signal" finding is
    about the question's own options, not a candidate's free text).

    Honours the P4.2 write policy (``lemely.core.topics``) exactly:

    * a question that already carries a non-empty ``topic`` (real
      ``topic_hint`` ground truth from the mark scheme) is never overwritten;
    * only a ``high``/``medium``-band match (:func:`~lemely.core.topics.is_writable`)
      is written; a ``low``-band match is discarded, not written — D4.4 §5's
      reasoning applies identically here: there is no per-question topic
      confidence column, so writing a guess would launder it into apparent
      fact;
    * a subject with no bundled taxonomy, a question absent from the mark
      scheme, or a question with no confident match is left with
      ``topic=None`` — never a fallback label.

    Evidence for one question is its **whole subtree**, and a node with no
    confident match of its own inherits from its nearest ancestor that has
    one — see :func:`_resolve_topic_labels` for why both are needed and what
    each is measured to be worth.
    """
    taxonomy = get_taxonomy(correction.metadata.subject_code)
    if taxonomy is None:
        return
    labels = _resolve_topic_labels(mark_scheme, taxonomy)
    for cq in correction.questions:
        if cq.topic:
            continue
        label = labels.get(cq.question_id)
        if label is not None:
            cq.topic = label


def _resolve_topic_labels(mark_scheme: MarkScheme, taxonomy: SyllabusTaxonomy) -> dict[str, str]:
    """Map every mark-scheme question id to a writable topic label, or omit it.

    ``correct_paper`` marks **every node** of the scheme tree
    (``all_questions_flat``), parents and leaves alike, so this resolves the
    same set. Two structural rules, both measured against the 33
    deterministically-parsed 0625 schemes in ``outputs/schemes`` (1329 marked
    nodes) rather than assumed:

    1. **A question is classified from its own subtree**, not from its own
       fields alone. A parent node carries almost no prose of its own — the
       marking content hangs off its ``parts`` — so classifying the node
       in isolation scores 8.1% of nodes and classifying its subtree scores
       14.9%.
    2. **A node with no confident match of its own inherits the nearest
       ancestor's label** (32.2% of all nodes; 52.9% of the non-MCQ ones).
       This is inheritance, not guesswork: ``3(b)(ii)`` whose own mark points
       read "correct substitution" *is structurally part of* question 3, and
       the ancestor's evidence is a superset of the child's. It is still
       gated by :func:`~lemely.core.topics.is_writable`, so a topic no
       ancestor could confidently place stays ``None``.

    **The ceiling is structural and is not a defect here.** 520 of those 1329
    nodes are MCQ, and a CAIE MCQ mark scheme carries exactly one datum — the
    answer letter. There is no text to classify at any depth, so those nodes
    are unclassifiable from a mark scheme by construction; their stems live in
    the question paper (D3.7's wall, the same one P4.1's stem extractor exists
    to climb). The reachable population is the 809 non-MCQ nodes.
    """
    labels: dict[str, str] = {}

    def visit(question: Question, inherited: str | None) -> None:
        match = classify(_subtree_text(question), taxonomy)
        label = match.label if match is not None and is_writable(match) else inherited
        if label is not None:
            # First occurrence wins, mirroring ``get_question_by_id``'s
            # depth-first "first match" semantics on duplicated ids.
            labels.setdefault(question.id, label)
        for part in question.parts or []:
            visit(part, label)

    for question in mark_scheme.questions:
        visit(question, None)
    return labels


def _subtree_text(question: Question) -> str:
    """:func:`_classification_text` for ``question`` and all of its parts."""
    texts = [_classification_text(question)]
    texts.extend(_subtree_text(part) for part in question.parts or [])
    return "\n".join(text for text in texts if text)


def _classification_text(question: Question) -> str:
    """Everything a mark-scheme ``Question`` carries that signals its topic.

    Mirrors :func:`~lemely.db.question_bank_repo.classification_text`'s shape
    for the marking side's own source data. A mark scheme has no question
    stem or MCQ option text — those live in the question paper, which
    :func:`fill_correction_topics` never has access to — so the signal here is
    the mark-scheme's own prose: the command word, marking guidance, examiner
    notes, point-based mark points, indicative-content points, and
    levels-based descriptor text.
    """
    parts: list[str] = []
    if question.question_command:
        parts.append(question.question_command)
    if question.marking_guidance:
        parts.append(question.marking_guidance)
    if question.notes:
        parts.append(question.notes)
    parts.extend(point.point for point in question.answer_points)
    for content_point in question.indicative_content or []:
        parts.append(content_point.point)
    for level in question.level_descriptors or []:
        parts.extend(descriptor.text for descriptor in level.descriptors)
    return "\n".join(p for p in parts if p)


__all__ = ["REVIEW_CONFIDENCE_THRESHOLD", "AttemptRepository", "fill_correction_topics"]
