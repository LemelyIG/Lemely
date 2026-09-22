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

    * ``low_confidence`` when the marking side asked for review — a real
      low confidence score, or ``needs_teacher_review`` set for a structural
      reason (``out_of_range``, ``value_mismatch``, ``coherence_mismatch``,
      ``no_span`` — all four independent of confidence,
      ``correction_ai.py:1043-1055``) — OR the confidence score itself falls
      below ``REVIEW_CONFIDENCE_THRESHOLD``.

      Two narrow exemptions from the ``needs_teacher_review`` disjunct
      (``marking_flagged``), both because ``apply_integrity_checks`` forces
      ``needs_teacher_review`` True on ANY flagged question regardless of
      what the marking side actually said:

      1. A question whose *only* ``review_reason`` segment is the
         integrity-appended plagiarism text (:func:`_is_solely_plagiarism_flagged`)
         — the marking side had nothing to say, so ``marking_flagged`` would
         mint a duplicate, mislabelled row alongside the ``plagiarism_flag``
         row below.
      2. A genuine US-039 blank that also picked up an integrity flag
         (``question.plagiarism_flagged and _is_unflagged_blank(question)``
         — see below). Currently unreachable in practice — a blank can
         never actually be ``plagiarism_flagged`` (see below) — but gated
         on ``plagiarism_flagged`` rather than dropped, since
         ``_is_unflagged_blank`` alone would also silence a real
         marking-side reason on a hypothetical literal collision with
         another builder's unflagged ``review_reason`` (see **Known
         limits** below).

      Neither exemption suppresses a real marking-side reason: a question
      that is *also* structurally flagged or genuinely low-confidence keeps
      that segment in ``review_reason``, so it fails both checks and
      ``marking_flagged`` still fires alongside ``plagiarism_flag``.

    * ``plagiarism_flag`` per integrity flag actually raised.

    **US-039 unflagged-blank exemption.** ``_build_blank_corrected`` marks a
    genuine blank ``marker_source="missing"``, ``confidence_score=0.0``, and
    ``needs_teacher_review=False`` — the product owner's ruling: an
    unflagged zero should not become a queue item, so a paper with several
    unattempted parts does not become that many items a teacher
    bulk-dismisses. The exemption suppresses both the confidence-score
    disjunct of ``low_confidence`` (via ``low_confidence_flagged``) and, per
    exemption 2 above, the ``needs_teacher_review`` disjunct once integrity
    forces it True — and only when ``marker_source == "missing"`` AND the
    blank's own reason is one of the ``" | "``-split segments of
    ``review_reason`` (:func:`_is_unflagged_blank`), never off
    ``confidence_score`` or ``marker_source`` alone. That keeps it from
    leaking onto ``_build_missing_corrected``'s or ``_build_dropped_corrected``'s
    output (also ``confidence_score == 0.0``, but ``needs_teacher_review=True``
    from the builder itself, not just from integrity, so they still queue).
    Membership rather than whole-field equality matters because
    ``apply_integrity_checks`` (:mod:`lemely.io.integrity`) APPENDS to
    ``review_reason`` rather than replacing it, so a flagged blank still
    carries the blank's own reason as one of possibly several segments.

    In today's pipeline a real blank can never also be ``plagiarism_flagged``:
    ``_build_blank_corrected`` sets both ``student_answer`` and
    ``expected_answer`` to ``None``, and ``apply_integrity_checks``'s
    plagiarism check requires both truthy before it runs. This does not rest
    on the MCQ exemption — that exemption is an id lookup against the mark
    scheme (``integrity.py:92``), not a builder property, so a scheme whose
    MCQ leaf id is shadowed in DFS order by an earlier same-id non-MCQ
    question defeats it and the check runs anyway. It rests on
    ``expected_answer`` instead: every site that sets it to a non-``None``
    value also sets ``marker_source="deterministic"``
    (``correction_ai.py:310``, ``:325``, ``:361``, ``core/correction.py:93``,
    ``:111``, ``:129``), so a genuine blank's ``expected_answer`` is
    ``None`` regardless of how the scheme is shaped.

    **Known limits.** ``_is_unflagged_blank`` is a string signal, not a
    dedicated boolean on :class:`~lemely.core.schemas.CorrectedQuestion` —
    robust to ``apply_integrity_checks`` *appending* onto ``review_reason``,
    but would be defeated by a stage that rewrites the field outright
    (``correct_paper``'s AI-failure branch, ``correction_ai.py:1922``, does
    exactly that — harmless here only because a blank ``continue``s before
    reaching it), or by ``_BLANK_ANSWER_REVIEW_REASON`` ever colliding with
    another builder's literal. That collision is harmless whenever
    ``plagiarism_flagged`` is False (exemption 2 above is gated on it, so an
    unflagged colliding question still queues via ``marking_flagged``
    exactly as before); only if the same question is ALSO
    ``plagiarism_flagged`` does the collision cost a real ``low_confidence``
    row, and a colliding question is also unreachable today: a literal
    match requires ``marker_source == "missing"`` (see
    :func:`_is_unflagged_blank`), which implies ``expected_answer is None``
    (see above) and so ``plagiarism_flagged=False``. The collision guard
    lives in ``lemely.io.correction_ai``'s own
    pairwise-distinctness test (``PairwiseDistinctBlankReasonsTests``,
    ``tests/test_correction_ai.py``), which derives all four blank-shaped
    literals from the real builders rather than hardcoding copies.
    """
    unflagged_blank = _is_unflagged_blank(question)
    marking_flagged = question.needs_teacher_review and not (
        (question.plagiarism_flagged and unflagged_blank) or _is_solely_plagiarism_flagged(question)
    )
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


def _is_solely_plagiarism_flagged(question: CorrectedQuestion) -> bool:
    """True when the integrity-appended plagiarism segment is the only reason on record.

    ``apply_integrity_checks`` appends
    ``f"plagiarism (score {finding.score:.2f})"`` (``integrity.py:102``) onto
    whatever ``review_reason`` a builder already produced, joined by
    ``" | "``. When that segment is the *only* one, the marking side had no
    complaint of its own — ``review_reason`` was empty before integrity ran.
    When it is one of several segments, a builder wrote a structural or
    low-confidence reason of its own, and that reason must not be dropped
    just because the question also got plagiarism-flagged (Finding A: a
    fully-confident but out-of-range mark is exactly this case, and losing
    its ``low_confidence`` row hides the sole signal that the marker
    misread the mark scheme).
    """
    if not question.plagiarism_flagged or not question.review_reason:
        return False
    segments = question.review_reason.split(" | ")
    return len(segments) == 1 and segments[0].startswith("plagiarism (score")


__all__ = ["review_reasons_for"]
