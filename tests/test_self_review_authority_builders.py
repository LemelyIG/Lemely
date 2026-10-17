"""Self-review authority, enumerated over every real ``CorrectedQuestion`` producer.

WHY THIS FILE EXISTS, AND WHY IT IS NOT IN EITHER EXISTING SUITE
---------------------------------------------------------------

The ``develop`` merge produced a Critical that existed in **neither branch
alone**: a student could self-award every mark on a question they left blank —
no evidence, no judge, measured 0 of 4 to 4 of 4 — because
``is_marking_low_confidence`` (develop's self-review *authority gate*) returned
``True`` for a US-039 blank, and ``decide_point`` tests ``low_confidence``
**above** ``has_evidence``.

Neither side's test suite could have caught it, and that is a measured fact
about the *shape* of those suites, not an oversight in them:

* develop's authority unit tests build their rows through a fixture that
  hardcodes ``marker_source=MarkerSource.ai`` and never varies
  ``review_reason``. A blank is ``marker_source="missing"`` with the blank
  literal. Not reachable from there.
* develop's self-review suite routes every fixture through one ``_question()``
  helper that hardcodes ``marker_source="ai"`` with no parameter to override
  it. There is no path in that file to a ``"missing"`` question.
* this branch had no ``self_review_repo.py`` at all, so it contributed zero
  tests for the gate.

The root cause is general: **two suites each hand-enumerating their own side's
field values cannot in principle catch a combination only the intersection
produces.** A fixture that names its field values freezes them; the next story
adds a producer the fixture has never heard of, and the gate silently stops
being tested for it.

So this file does not name field values. It enumerates the **producers** —
every ``_build_*_corrected`` in :mod:`lemely.io.correction_ai` that
``correct_paper`` can emit — and asserts the authority outcome for whatever
each one actually emits today. Add a sixth builder and this file fails until
its row is stated, which is the property the hardcoded fixtures could not have.

Every predicate here is imported from the tree, never transcribed: a copied
predicate cannot fail when the original changes, and failing when the original
changes is the entire job.
"""

from __future__ import annotations

import unittest

from lemely.core.loose_schemas import MCQAnswer, Question, QuestionType
from lemely.core.schemas import AIMarkResponse, CorrectedQuestion
from lemely.core.self_review import PointDecision, decide_point
from lemely.db.attempt_repo import _to_question_result, is_marking_low_confidence
from lemely.db.models.enums import ReviewReason
from lemely.db.review_queue_rules import review_reasons_for
from lemely.io.correction_ai import (
    _build_ai_corrected,
    _build_blank_corrected,
    _build_dropped_corrected,
    _build_mcq_corrected,
    _build_missing_corrected,
)

_MARKS = 4


def _mcq_question() -> Question:
    return Question.model_construct(
        id="1",
        marks=1,
        type=QuestionType.MCQ,
        mcq_answer=MCQAnswer.A,
        parts=[],
        assessment_objectives=[],
        answer_points=[],
        rejected_answers=[],
        ignored_answers=[],
    )


def _open_question() -> Question:
    return Question.model_construct(
        id="3b",
        marks=_MARKS,
        type=QuestionType.CALCULATION,
        parts=[],
        assessment_objectives=[],
        answer_points=[],
        rejected_answers=[],
        ignored_answers=[],
    )


def _every_producer() -> dict[str, CorrectedQuestion]:
    """One :class:`CorrectedQuestion` per real producer ``correct_paper`` emits.

    Built by calling the builders themselves rather than by writing out their
    field values, so a change to any builder's ``marker_source``,
    ``confidence_score``, ``needs_teacher_review`` or ``review_reason`` lands
    here automatically — the failure mode this file exists to close.

    ``_build_ai_corrected_from_verdicts`` is not a separate row: it is reached
    only *through* ``_build_ai_corrected``'s I6 dispatch (``equivalence_gate``
    on plus non-empty ``point_verdicts``), and it produces an ``"ai"`` row like
    the one below. The five here are the five distinct ``marker_source`` /
    review-shape outcomes the pipeline can persist.
    """
    return {
        # A correct MCQ: deterministic, fully confident, nothing to review.
        "mcq_correct": _build_mcq_corrected(_mcq_question(), "A"),
        # An MCQ with no extracted answer: "missing", and flagged by the
        # builder itself.
        "mcq_no_answer": _build_mcq_corrected(_mcq_question(), None),
        # A real AI mark, low confidence — the case authority was designed for.
        "ai_low_confidence": _build_ai_corrected(
            _open_question(),
            "some working",
            AIMarkResponse(
                awarded_marks=1,
                confidence=0.55,
                matched_point_ids=[],
                feedback="Partially correct.",
            ),
        ),
        # A genuine US-039 blank: the student wrote nothing, no AI call made.
        "blank": _build_blank_corrected(_open_question()),
        # US-038: the model returned an answer, extraction discarded it.
        "dropped": _build_dropped_corrected(_open_question()),
        # --mcq-only / no client: a non-MCQ question nothing marked.
        "missing": _build_missing_corrected(_open_question(), None),
    }


class AuthorityOverEveryProducerTests(unittest.TestCase):
    """What ``is_marking_low_confidence`` grants, per producer."""

    def test_only_a_flagged_or_low_scored_mark_grants_evidence_free_authority(self) -> None:
        """The authority table, stated per producer rather than per field value.

        ``True`` means "the marker doubted itself, so the student's word is
        enough": ``self_review_repo._to_view`` sets
        ``evidence_required = not is_marking_low_confidence(qr)``, and
        ``decide_point`` grants outright on ``low_confidence`` without ever
        reading ``has_evidence``.

        The blank is ``False`` and that is the whole point of the row. A blank
        has ``confidence_score == 0.0``, which satisfies the bare
        ``< REVIEW_CONFIDENCE_THRESHOLD`` disjunct develop's version of this
        gate applied — so before the US-039 exemption reached the gate, a blank
        granted evidence-free authority. Absence of a marker is not
        marker-doubt.
        """
        expected = {
            "mcq_correct": False,
            "mcq_no_answer": True,
            "ai_low_confidence": True,
            "blank": False,
            "dropped": True,
            "missing": True,
        }
        actual = {
            name: is_marking_low_confidence(_to_question_result(cq))
            for name, cq in _every_producer().items()
        }
        self.assertEqual(actual, expected)

    def test_the_gate_and_the_queue_predicate_never_disagree(self) -> None:
        """One rule, two consumers — checked over the real producer product.

        ``review_reasons_for`` decides whether a ``low_confidence`` queue row
        opens; ``is_marking_low_confidence`` decides whether a self-mark
        carries authority. They are different questions, but both rest on "did
        the marking side ask for a human look", and they must answer *that*
        identically or the two diverge exactly where nothing tests the seam —
        which is how the Critical arose. Both read
        ``review_queue_rules.low_confidence_review_needed``; this asserts the
        sharing is real rather than documented.
        """
        for name, cq in _every_producer().items():
            with self.subTest(producer=name):
                queue_says = ReviewReason.low_confidence in set(review_reasons_for(cq))
                gate_says = is_marking_low_confidence(_to_question_result(cq))
                self.assertEqual(queue_says, gate_says)

    def test_a_blank_is_the_only_unflagged_zero(self) -> None:
        """Guards the exemption's width from both sides.

        The exemption must catch the genuine blank and nothing else. Every
        other zero-mark producer here is ``needs_teacher_review=True`` from the
        builder itself, so it still queues and still grants authority; only the
        blank is the product owner's deliberate "unflagged zero". If a later
        edit keys the exemption off ``confidence_score == 0.0`` or
        ``marker_source == "missing"`` alone, ``mcq_no_answer`` and ``missing``
        flip and this fails.
        """
        producers = _every_producer()
        zero_scored = {name: cq for name, cq in producers.items() if cq.confidence_score == 0.0}
        self.assertEqual(
            sorted(zero_scored),
            ["blank", "dropped", "mcq_no_answer", "missing"],
            "a producer's confidence_score moved; re-check which rows the "
            "exemption has to distinguish",
        )
        unflagged = [name for name, cq in zero_scored.items() if not cq.needs_teacher_review]
        self.assertEqual(unflagged, ["blank"])


class BlankFacesTheJudgeTests(unittest.TestCase):
    """The end-to-end outcome, through the real ``decide_point``.

    This is ``probes/authority_exploit_probe.py``'s five steps as an
    assertion. The probe reproduced the exploit before the merge and is the
    standing manual gate; this is the automated one, and it fails if the
    exemption is ever removed from the gate — including by the "obvious"
    repair of deleting the ``ai_detection_flagged`` term, which silences the
    merge's loud ``AttributeError`` and kills the exemption with it.
    """

    def _blank_row(self):
        return _to_question_result(_build_blank_corrected(_open_question()))

    def test_a_blank_self_marked_with_no_evidence_moves_no_marks(self) -> None:
        low_confidence = is_marking_low_confidence(self._blank_row())
        self.assertFalse(low_confidence, "the US-039 exemption is not reaching the gate")

        decisions = [
            decide_point(
                ai_awarded=False,
                student_earned=True,
                low_confidence=low_confidence,
                has_evidence=False,
            )
            for _ in range(_MARKS)
        ]
        self.assertEqual(decisions, [PointDecision.NO_CHANGE] * _MARKS)
        self.assertNotIn(PointDecision.GRANT, decisions)

    def test_a_blank_self_marked_WITH_evidence_reaches_the_judge(self) -> None:
        """US-042's false blank is the case with a legitimate claim.

        The panel stays available on a blank deliberately: the student may have
        written something extraction missed. What the exemption changes is the
        route — they supply evidence and a lenient judge rules, instead of the
        mark moving on their word alone.
        """
        low_confidence = is_marking_low_confidence(self._blank_row())
        decisions = [
            decide_point(
                ai_awarded=False,
                student_earned=True,
                low_confidence=low_confidence,
                has_evidence=True,
            )
            for _ in range(_MARKS)
        ]
        self.assertEqual(decisions, [PointDecision.JUDGE] * _MARKS)

    def test_a_genuinely_low_confidence_mark_still_grants_outright(self) -> None:
        """The exemption must not cost develop's feature.

        A real low-confidence AI mark is the case authority exists for: the
        marker doubted itself, so the student wins without having to argue.
        """
        low_confidence = is_marking_low_confidence(
            _to_question_result(
                _build_ai_corrected(
                    _open_question(),
                    "some working",
                    AIMarkResponse(
                        awarded_marks=1,
                        confidence=0.55,
                        matched_point_ids=[],
                        feedback="Partially correct.",
                    ),
                )
            )
        )
        self.assertTrue(low_confidence)
        self.assertIs(
            decide_point(
                ai_awarded=False,
                student_earned=True,
                low_confidence=low_confidence,
                has_evidence=False,
            ),
            PointDecision.GRANT,
        )


if __name__ == "__main__":
    unittest.main()
