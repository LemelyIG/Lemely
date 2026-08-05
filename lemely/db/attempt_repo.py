"""Full-report persistence for the student self-mark pipeline (P2.1).

Where :class:`~lemely.db.history_repo.DbHistoryStore` persists the *totals-only*
:class:`~lemely.core.history.PaperRecord`, this repository persists the complete
:class:`~lemely.core.schemas.AccuracyReport` produced by the marking pipeline:
one :class:`~lemely.db.models.attempts.Attempt` plus a
:class:`~lemely.db.models.attempts.QuestionResult` per marked question, a
:class:`~lemely.db.models.attempts.WeaknessRecord` per weak area, and a
:class:`~lemely.db.models.ops.ReviewQueueItem` for every question that needs a
teacher's eyes. Everything lands in a single transaction so a partially-written
attempt is never observable.

Core→DB enum mapping is by ``.value`` (the core :class:`StrEnum`s and the DB
:class:`enum.Enum`s share their string members), reusing
:func:`~lemely.db.history_repo.parse_user_id` / ``month_to_enum`` for the two
impedance mismatches (str id → UUID FK, month label → enum).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from lemely.core.schemas import REVIEW_CONFIDENCE_THRESHOLD
from lemely.db.history_repo import month_to_enum, parse_user_id
from lemely.db.models.attempts import Attempt, QuestionResult, WeaknessRecord
from lemely.db.models.enums import BoundarySource, MarkerSource, ReviewReason
from lemely.db.models.enums import ConfidenceBand as DBConfidenceBand
from lemely.db.models.ops import ReviewQueueItem

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.orm import Session, sessionmaker

    from lemely.core.schemas import AccuracyReport, CorrectedQuestion

# The review threshold now has exactly one definition, in
# :mod:`lemely.core.schemas` (D2.2) — the marking layer, this repository and the
# teacher console all read that constant, so the persist-time review gate can no
# longer drift from the flag the marker set or from what the accuracy harness
# measures. Re-exported here because this module's name for it is part of its
# public surface.


class AttemptRepository:
    """Persist a full :class:`AccuracyReport` as relational attempt rows."""

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
        """Persist an :class:`AccuracyReport` and return the new attempt id.

        Writes one :class:`Attempt` (+ its :class:`QuestionResult`s and
        :class:`WeaknessRecord`s) and a :class:`ReviewQueueItem` for every
        question flagged for review, all inside a single transaction.

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
        owner = parse_user_id(user_id)
        correction = report.correction
        meta = correction.metadata
        prediction = report.grade_prediction

        attempt = Attempt(
            user_id=owner,
            upload_id=upload_id,
            subject_code=meta.subject_code,
            session_month=month_to_enum(meta.session_month),
            session_year=meta.session_year,
            paper_number=meta.paper_number,
            paper_variant=meta.paper_variant,
            awarded_marks=correction.awarded_marks,
            maximum_marks=correction.maximum_marks,
            percentage=prediction.percentage,
            grade=prediction.grade,
            predicted_grade=prediction.grade,
            boundary_source=BoundarySource(prediction.boundary_source),
            confidence_band=DBConfidenceBand(prediction.confidence.value),
            needs_teacher_review=correction.needs_teacher_review,
            recorded_at=_parse_recorded_at(recorded_at),
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
            for wa in report.weaknesses.weak_areas
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


__all__ = ["REVIEW_CONFIDENCE_THRESHOLD", "AttemptRepository"]
