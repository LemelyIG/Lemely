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

**A third consumer, and why the verdict is split out from the row producer.**
The ``develop`` merge brought :func:`lemely.db.attempt_repo.is_marking_low_confidence`,
which had independently arrived at the same two-disjunct shape for a *different*
job: it is the student self-review **authority gate**
(``self_review_repo``'s ``evidence_required = not is_marking_low_confidence(qr)``),
not a queue predicate. Its argument is a persisted
:class:`~lemely.db.models.attempts.QuestionResult`, not a
:class:`~lemely.core.schemas.CorrectedQuestion`.

A gate and a queue row are not the same question, but they must not disagree
about *this* one: "did the marking side ask for a human look". So
:func:`low_confidence_review_needed` holds that verdict over the five raw
fields both record types carry, and both callers read it —
:func:`review_reasons_for` to decide whether to yield
:attr:`~lemely.db.models.enums.ReviewReason.low_confidence`,
``is_marking_low_confidence`` to decide whether a self-mark carries authority.

That sharing is load-bearing in one direction specifically. Without it, a
US-039 blank (``needs_teacher_review=False``, ``confidence_score=0.0``) is
exempt from the queue on this side and reads as ``low_confidence`` on
develop's, so the gate would set ``evidence_required=False`` on a question no
marker ever read — and ``decide_point`` tests low-confidence *above*
``has_evidence``, so the student's self-mark would be granted outright, with
no evidence and without the lenient judge being consulted. Measured on the
merged tree before this was shared: 0 of 4 marks to 4 of 4. Treating
absence-of-a-marker as marker-doubt happens to favour the student here and
burden them in the queue, which is why it reads as benign on each side alone.
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

    The ``low_confidence`` verdict itself lives in
    :func:`low_confidence_review_needed`, which this delegates to so the
    self-review authority gate can read the identical rule (module docstring).
    The rule it applies is documented here, where the rows are produced:

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
         (``plagiarism_flagged and _is_unflagged_blank(...)`` — see below).
         Currently unreachable in practice — a blank can
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
    disjunct of ``low_confidence`` (via ``low_confidence_review_needed``'s
    ``low_confidence_flagged``) and, per
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

    On a well-formed scheme, the plagiarism check never fires for any
    ``correct_paper`` output: it requires ``expected_answer`` truthy
    (``integrity.py:101``), and every site that sets ``expected_answer``
    non-``None`` also sets ``marker_source="deterministic"``
    (``correction_ai.py:310``, ``:325``, ``:361``, ``core/correction.py:93``,
    ``:111``, ``:129``). On a malformed scheme — one where a non-MCQ
    question's id shadows an MCQ leaf's id, defeating the MCQ exemption's
    first-match DFS lookup (``get_question_by_id``,
    ``lemely/core/loose_schemas.py:1023-1036``; ``integrity.py:92``) — it
    can fire, but only on that same ``deterministic`` row, never on
    ``ai``, ``missing`` or ``dropped``. A real blank
    (``marker_source="missing"``) can therefore never also be
    ``plagiarism_flagged``, on any scheme.

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
    exactly as before); a colliding question that is ALSO
    ``plagiarism_flagged`` is unreachable, since a literal match requires
    ``marker_source == "missing"`` (:func:`_is_unflagged_blank`), which per
    above can never be ``plagiarism_flagged``. The collision guard lives in
    ``lemely.io.correction_ai``'s own pairwise-distinctness test
    (``PairwiseDistinctBlankReasonsTests``, ``tests/test_correction_ai.py``),
    which derives all four blank-shaped literals from the real builders
    rather than hardcoding copies.
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

    The ``low_confidence`` half of :func:`review_reasons_for`, over raw fields
    rather than a record, so the queue producers and
    :func:`lemely.db.attempt_repo.is_marking_low_confidence` — which reads a
    persisted :class:`~lemely.db.models.attempts.QuestionResult`, not a
    :class:`~lemely.core.schemas.CorrectedQuestion` — cannot draw the line
    differently. See this module's docstring for why those two must agree and
    what goes wrong when they do not.

    Fields, not a :class:`typing.Protocol`: the two record types spell
    ``marker_source`` differently (a ``Literal[...]`` string on
    ``CorrectedQuestion``, a :class:`~lemely.db.models.enums.MarkerSource` enum
    member on ``QuestionResult``), so a structural type would need one of them
    to change shape. Keyword-only because five same-typed-ish values in a row
    is exactly the signature a positional call gets silently wrong.

    ``ai_detection_flagged`` is absent by design, not by omission: develop's
    version of this predicate suppressed ``marking_flagged`` on
    ``plagiarism_flagged or ai_detection_flagged``, and F4
    (``0037_remove_ai_detection``) deleted the detector, its column and its
    enum member outright.
    """
    unflagged_blank = _is_unflagged_blank(marker_source=marker_source, review_reason=review_reason)
    marking_flagged = needs_teacher_review and not (
        (plagiarism_flagged and unflagged_blank)
        or _is_solely_plagiarism_flagged(
            plagiarism_flagged=plagiarism_flagged, review_reason=review_reason
        )
    )
    low_confidence_flagged = not unflagged_blank and confidence_score < REVIEW_CONFIDENCE_THRESHOLD
    return marking_flagged or low_confidence_flagged


def _is_unflagged_blank(*, marker_source: str, review_reason: str | None) -> bool:
    """True for a genuine US-039 blank, tolerant of a later stage APPENDING to ``review_reason``.

    ``apply_integrity_checks`` joins new reasons onto the existing ones with
    ``" | "`` and never rewrites what was already there (its own docstring:
    "review_reason appended to (preserving any existing text)"). Splitting on
    the same separator and checking membership, rather than testing the
    whole field for equality, means an integrity flag landing on top of a
    genuine blank does not defeat this check.
    """
    if marker_source != "missing" or not review_reason:
        return False
    return _BLANK_ANSWER_REVIEW_REASON in review_reason.split(" | ")


def _is_solely_plagiarism_flagged(*, plagiarism_flagged: bool, review_reason: str | None) -> bool:
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
    if not plagiarism_flagged or not review_reason:
        return False
    segments = review_reason.split(" | ")
    return len(segments) == 1 and segments[0].startswith("plagiarism (score")


__all__ = ["low_confidence_review_needed", "review_reasons_for"]
