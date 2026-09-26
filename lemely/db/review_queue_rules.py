"""The one "did the marking side ask for a human look at this question" rule.

Three consumers, one statement, because they must not disagree:

* :meth:`lemely.db.attempt_repo.AttemptRepository.persist_correction` (through
  its ``_persist``) — opens ``review_queue`` rows for a student attempt.
* ``_review_items_for`` (:mod:`lemely.db.teacher_paper_repo`) — the same, for a
  console-graded paper. Migration ``0034`` documented both as applying "the same
  three-reason rule"; that was true only while two hand-written copies stayed in
  sync, and ``674f309d`` broke it (the US-039 blank exemption reached the attempt
  producer alone, so a paper with 8 unattempted parts still became 8 console
  queue items the product owner had rejected).
* :func:`lemely.db.attempt_repo.is_marking_low_confidence` — the student
  self-review AUTHORITY gate (``self_review_repo``'s
  ``evidence_required = not is_marking_low_confidence(qr)``). A gate is not a
  queue row, but both rest on this one question, and when they disagreed a
  student could self-award every mark on a blank with no evidence and no judge
  (measured on the merged tree: 0 of 4 marks to 4 of 4). Absence of a marker is
  not marker-doubt.

:func:`low_confidence_review_needed` holds the verdict over raw fields rather
than a record because the two record types spell ``marker_source`` differently
(a ``Literal`` on :class:`~lemely.core.schemas.CorrectedQuestion`, a
:class:`~lemely.db.models.enums.MarkerSource` member on
:class:`~lemely.db.models.attempts.QuestionResult`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from lemely.core.schemas import REVIEW_CONFIDENCE_THRESHOLD, CorrectedQuestion
from lemely.db.models.enums import ReviewReason

if TYPE_CHECKING:
    from collections.abc import Iterator


def review_reasons_for(question: CorrectedQuestion) -> Iterator[ReviewReason]:
    """Yield the :class:`ReviewReason` values one graded question earns.

    * ``low_confidence`` per :func:`low_confidence_review_needed`.
    * ``plagiarism_flag`` per integrity flag actually raised. This is also the
      only place the flag is ever persisted — there is no
      ``question_results.plagiarism_flagged`` column (see
      :attr:`QuestionResult.review_queue_items
      <lemely.db.models.attempts.QuestionResult.review_queue_items>`).
    """
    if low_confidence_review_needed(
        marker_source=question.marker_source,
        review_reason=question.review_reason,
        needs_teacher_review=question.needs_teacher_review,
        confidence_score=question.confidence_score,
        plagiarism_flagged=question.plagiarism_flagged,
    ):
        yield ReviewReason.low_confidence
    if question.plagiarism_flagged:
        yield ReviewReason.plagiarism_flag


def low_confidence_review_needed(
    *,
    marker_source: str,
    review_reason: str | None,
    needs_teacher_review: bool,
    confidence_score: float,
    plagiarism_flagged: bool,
) -> bool:
    """Did the MARKING side ask for a human look at this question?

    True on either disjunct:

    * ``needs_teacher_review``, which a marker sets for a low score or for one
      of four structural reasons independent of confidence — ``out_of_range``,
      ``value_mismatch``, ``coherence_mismatch``, ``no_span``
      (``correction_ai.py``'s ``_build_ai_corrected``);
    * ``confidence_score`` below :data:`REVIEW_CONFIDENCE_THRESHOLD`.

    Two exemptions, both narrow, both because a later stage overwrites what the
    marking side said:

    ``unscored_blank`` — a genuine US-039 blank (``marker_source == "blank"``).
    An unflagged zero must not become a queue item (the product owner rejected
    turning 8 unattempted parts into 8 rows a teacher bulk-dismisses), and must
    not grant self-mark authority either.

    It suppresses the score disjunct UNCONDITIONALLY: a blank's
    ``confidence_score`` is a placeholder, not a signal, and that is the US-039
    ruling itself.

    It suppresses the ``needs_teacher_review`` disjunct only ``and
    plagiarism_flagged``, and that conjunct is load-bearing in the direction
    that matters. ``_build_blank_corrected`` sets ``needs_teacher_review=False``,
    and today the only stage that can flip it True on a blank is
    :func:`lemely.io.integrity.apply_integrity_checks` — which sets it inside the
    same ``if updates:`` that just set ``plagiarism_flagged`` (checked, not
    assumed: ``updates`` has no other writer), and which therefore already opens
    its own ``plagiarism_flag`` row. So on every row producible today the
    conjunct changes nothing. It is here for the row that is not producible yet:
    a later stage that flags a blank WITHOUT opening a row of its own (a
    false-blank detector, US-042's accepted residual) must not have its signal
    swallowed. Dropping the conjunct is the silent direction — no queue row at
    all — so it stays, and
    ``test_a_blank_flagged_by_something_that_opens_no_row_still_queues`` fails if
    it goes.

    This is NOT the reason the conjunct originally existed. That was a guard
    against ``review_reason`` colliding with the blank literal, which task #36
    made impossible by moving the check onto the column.

    ``_is_solely_plagiarism_flagged`` — ``apply_integrity_checks`` forces
    ``needs_teacher_review`` True on ANY flagged question regardless of what the
    marking side said, so when its appended segment is the ONLY thing on
    ``review_reason`` the marking side had no complaint of its own and
    ``marking_flagged`` would mint a duplicate, mislabelled row beside the
    ``plagiarism_flag`` one. When it is one of several segments a builder wrote a
    real reason first, and that reason survives — a fully-confident but
    out-of-range mark is exactly this case, and losing its ``low_confidence``
    row hides the sole signal that the marker misread the mark scheme.

    ``ai_detection_flagged`` is absent by design, not by omission: develop's
    version of this predicate suppressed ``marking_flagged`` on
    ``plagiarism_flagged or ai_detection_flagged``, and F4
    (``0037_remove_ai_detection``) deleted the detector, its column and its enum
    member outright.
    """
    unscored_blank = marker_source == "blank"
    marking_flagged = needs_teacher_review and not (
        # `plagiarism_flagged and` is UNREACHABLE TODAY AND RETAINED DELIBERATELY,
        # because a future producer could reach it. Do not simplify it away: on
        # every row producible today it changes nothing, but a later stage that
        # flags a blank without opening a queue row of its own would then get its
        # signal swallowed entirely. See this function's docstring, and
        # `test_a_blank_flagged_by_something_that_opens_no_row_still_queues`,
        # which is mutation-checked and fails the moment this is dropped.
        (plagiarism_flagged and unscored_blank)
        or _is_solely_plagiarism_flagged(
            plagiarism_flagged=plagiarism_flagged, review_reason=review_reason
        )
    )
    low_confidence_flagged = not unscored_blank and confidence_score < REVIEW_CONFIDENCE_THRESHOLD
    return marking_flagged or low_confidence_flagged


def _is_solely_plagiarism_flagged(*, plagiarism_flagged: bool, review_reason: str | None) -> bool:
    """True when the integrity-appended plagiarism segment is the only reason on record.

    ``apply_integrity_checks`` appends ``f"plagiarism (score {score:.2f})"``
    onto whatever ``review_reason`` a builder already produced, joined by
    ``" | "``, so a lone segment means ``review_reason`` was empty before
    integrity ran.

    This is the one string test left in this module and it is not the one task
    #36 removed. That one recovered a marker_source-shaped FACT from prose (is
    this a blank?), which ``marker_source == "blank"`` now answers from a
    column. This one asks whether the marking side wrote anything at all, and
    there is no other persisted record of that: ``needs_teacher_review`` has
    already been clobbered by the time anyone reads it, and the four structural
    flags are recorded nowhere else.
    """
    if not plagiarism_flagged or not review_reason:
        return False
    segments = review_reason.split(" | ")
    return len(segments) == 1 and segments[0].startswith("plagiarism (score")


__all__ = ["low_confidence_review_needed", "review_reasons_for"]
