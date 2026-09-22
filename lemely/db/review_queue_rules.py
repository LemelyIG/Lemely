"""The one "does this graded question need a review-queue row" predicate.

Migration ``0034`` gave ``review_queue`` two producers —
:meth:`~lemely.db.attempt_repo.AttemptRepository.persist_correction` for a
student attempt, ``_review_items_for`` (:mod:`lemely.db.teacher_paper_repo`)
for a console-graded paper — and both were documented as applying "the same
three-reason rule", so the two sources could never disagree about what "needs
review" means. That was only ever true by two hand-written copies staying in
sync: ``674f309d`` added the US-039 unflagged-blank exemption to the attempt
producer alone, and the console producer went on queuing every blank via its
own ``low_confidence`` arm regardless — the exact "8 unattempted parts, 8
queue items a teacher bulk-dismisses" scenario the product owner rejected,
just reached through ``lemely.web.services.grading.grade_paper`` instead of a
student submission.

:func:`review_reasons_for` is the fix: both producers now call the same
function on the same :class:`~lemely.core.schemas.CorrectedQuestion`, so the
"same rule" claim is a fact about the code, not a comment that can drift out
from under it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from lemely.core.schemas import REVIEW_CONFIDENCE_THRESHOLD, CorrectedQuestion
from lemely.db.models.enums import ReviewReason
from lemely.io.correction_ai import _BLANK_ANSWER_REVIEW_REASON

if TYPE_CHECKING:
    from collections.abc import Iterator


def review_reasons_for(question: CorrectedQuestion) -> Iterator[ReviewReason]:
    """Yield the :class:`ReviewReason` values one graded question earns.

    * ``low_confidence`` when the **marking** side asked for review — a real
      low confidence score, or ``needs_teacher_review`` set for a structural
      reason — OR the confidence score itself falls below
      ``REVIEW_CONFIDENCE_THRESHOLD``. A question that is *purely*
      integrity-flagged does not count as ``marking_flagged``:
      ``apply_integrity_checks`` forces ``needs_teacher_review`` True and that
      would mint a duplicate, mislabelled row alongside the specific
      ``plagiarism_flag`` row below.
    * ``plagiarism_flag`` per integrity flag actually raised.

    **US-039 unflagged-blank exemption.** ``_build_blank_corrected`` marks a
    genuine blank ``marker_source="missing"``, ``confidence_score=0.0``, and
    ``needs_teacher_review=False`` — the product owner's explicit ruling: an
    unflagged zero, no queue item, so a paper with several unattempted parts
    does not become that many items a teacher learns to bulk-dismiss. The
    exemption only ever suppresses the confidence-score disjunct of
    ``low_confidence``, and only when BOTH ``marker_source == "missing"`` AND
    ``review_reason`` is the blank's own reason — not off ``confidence_score``
    or ``marker_source`` alone — so it cannot leak onto
    ``_build_missing_corrected``'s or ``_build_dropped_corrected``'s output
    (also ``confidence_score`` 0.0, but ``needs_teacher_review=True`` there,
    so they already queue via ``marking_flagged`` regardless).
    """
    marking_flagged = question.needs_teacher_review and not question.plagiarism_flagged
    unflagged_blank = (
        question.marker_source == "missing"
        and question.review_reason == _BLANK_ANSWER_REVIEW_REASON
    )
    low_confidence_flagged = (
        not unflagged_blank and question.confidence_score < REVIEW_CONFIDENCE_THRESHOLD
    )
    if marking_flagged or low_confidence_flagged:
        yield ReviewReason.low_confidence
    if question.plagiarism_flagged:
        yield ReviewReason.plagiarism_flag


__all__ = ["review_reasons_for"]
