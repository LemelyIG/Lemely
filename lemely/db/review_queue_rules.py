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
    ``low_confidence``, and only when ``marker_source == "missing"`` AND
    ``review_reason`` CARRIES the blank's own reason (see
    :func:`_is_unflagged_blank` below) — not off ``confidence_score`` or
    ``marker_source`` alone — so it cannot leak onto
    ``_build_missing_corrected``'s or ``_build_dropped_corrected``'s output
    (also ``confidence_score`` 0.0, but ``needs_teacher_review=True`` there,
    so they already queue via ``marking_flagged`` regardless).

    **Second independent review (proven, fixed).** The exemption originally
    tested ``review_reason == _BLANK_ANSWER_REVIEW_REASON`` by full equality.
    ``apply_integrity_checks`` (:mod:`lemely.io.integrity`) APPENDS to
    ``review_reason`` (``" | ".join([*existing.split(" | "), new_reason])``,
    preserving the original text) whenever it flags a question — so a blank
    that also picked up an integrity flag would carry
    ``"<blank reason> | copied from another candidate"``, which is not equal
    to ``_BLANK_ANSWER_REVIEW_REASON``. Under the old check that made
    ``unflagged_blank`` False, so ``low_confidence_flagged`` fired
    (``0.0 < threshold``) and the row came back labelled ``low_confidence``
    alongside its ``plagiarism_flag`` row — the exact "duplicate, mislabelled
    row" this docstring's ``marking_flagged`` disjunct claims to avoid, minted
    by the OTHER disjunct instead. :func:`_is_unflagged_blank` now checks
    MEMBERSHIP of the blank's exact reason in the ``" | "``-split segments,
    which matches regardless of what gets appended after it. Verified: a
    genuine blank with ``plagiarism_flagged=True`` and
    ``review_reason="<blank reason> | copied from another candidate"`` now
    yields only ``plagiarism_flag`` — queued because it was flagged, not
    because a marker that never ran was "unsure".

    In today's pipeline this exact combination cannot actually occur:
    ``_build_blank_corrected`` sets both ``student_answer`` and
    ``expected_answer`` to ``None``, and ``apply_integrity_checks``'s
    plagiarism check requires both to be truthy before it ever runs — so a
    real blank can never reach the flagged branch. The fix stands anyway:
    this function's contract is "given a ``CorrectedQuestion`` shaped like
    X, decide Y", not "given only what today's two callers happen to
    produce", and relying on a coincidental gate in an unrelated module to
    keep this predicate sound is exactly the fragile coupling worth removing
    now rather than after some future builder changes that gate.

    **Remaining known limit.** ``_is_unflagged_blank`` is still a string
    signal, not a dedicated boolean on
    :class:`~lemely.core.schemas.CorrectedQuestion` — that schema is owned by
    another lane and adding a field there is out of this module's reach. It
    is now robust to *appending* (the one real mutation
    ``apply_integrity_checks`` performs today), but would still be defeated
    by a future stage that rewrites ``review_reason`` outright rather than
    appending to it, or by ``_BLANK_ANSWER_REVIEW_REASON`` ever colliding
    with another builder's literal as one of its own ``" | "``-split
    segments. The guard against the latter is
    ``lemely.io.correction_ai``'s own pairwise-distinctness test (see
    ``tests/test_correction_ai.py``), not anything in this module.
    """
    marking_flagged = question.needs_teacher_review and not question.plagiarism_flagged
    unflagged_blank = _is_unflagged_blank(question)
    low_confidence_flagged = (
        not unflagged_blank and question.confidence_score < REVIEW_CONFIDENCE_THRESHOLD
    )
    if marking_flagged or low_confidence_flagged:
        yield ReviewReason.low_confidence
    if question.plagiarism_flagged:
        yield ReviewReason.plagiarism_flag


def _is_unflagged_blank(question: CorrectedQuestion) -> bool:
    """True for a genuine US-039 blank, tolerant of a later stage APPENDING to ``review_reason``.

    ``apply_integrity_checks`` joins new reasons onto the existing ones with
    ``" | "`` and never rewrites what was already there (its own docstring:
    "review_reason appended to (preserving any existing text)"). Splitting on
    the same separator and checking membership, rather than testing the
    whole field for equality, means an integrity flag landing on top of a
    genuine blank does not defeat this check.
    """
    if question.marker_source != "missing" or not question.review_reason:
        return False
    return _BLANK_ANSWER_REVIEW_REASON in question.review_reason.split(" | ")


__all__ = ["review_reasons_for"]
