"""Unit tests for AICorrector and the hybrid correct_paper orchestrator."""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import unittest
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from lemely.core.loose_schemas import MarkScheme, Question, QuestionType
from lemely.core.schemas import (
    ConfidenceBand,
    ExtractedAnswer,
    ExtractedAnswers,
    PointVerdict,
)
from lemely.io import correction_ai
from lemely.io.correction_ai import _build_mcq_corrected, _flatten_answers, correct_paper
from lemely.io.gemini import GeminiClient
from lemely.runtime.config import PathsSettings, load_settings
from lemely.runtime.errors import ConfigError, CostCeilingError, ExternalServiceError
from lemely.runtime.events import EventType, bus


def _hybrid_paper_mark_scheme() -> MarkScheme:
    """Two questions: one MCQ + one short theory question."""
    return MarkScheme.model_validate(
        {
            "metadata": {
                "subject": "Physics",
                "subject_code": "0625",
                "paper_number": 4,
                "paper_variant": 2,
                "session_month": "May/June",
                "session_year": 2020,
                "paper_type": "theory_extended",
                "maximum_mark": 3,
                "scheme_format": "mixed",
            },
            "questions": [
                {"id": "1", "marks": 1, "type": "mcq", "mcq_answer": "A"},
                {
                    "id": "2",
                    "marks": 2,
                    "type": "explanation",
                    "question_command": "explain why",
                    "topic_hint": "forces",
                    "answer_points": [
                        {"id": "p1", "point": "gravity acts on it", "marks": 1},
                        {"id": "p2", "point": "no air resistance", "marks": 1},
                    ],
                },
            ],
        }
    )


class _IsolatedEnv:
    def __enter__(self) -> _IsolatedEnv:
        self._snap = dict(os.environ)
        for k in list(os.environ):
            if k.startswith("LEMELY_"):
                del os.environ[k]
        return self

    def __exit__(self, *_: object) -> None:
        os.environ.clear()
        os.environ.update(self._snap)


def _mock_marker_response(awarded: int, matched: list[str], feedback: str = "good") -> MagicMock:
    body = {
        "awarded_marks": awarded,
        "confidence": 0.9,
        "matched_point_ids": matched,
        "feedback": feedback,
    }
    return MagicMock(
        text=json.dumps(body),
        candidates=[MagicMock(finish_reason=MagicMock(__str__=lambda s: "STOP"))],
        usage_metadata=MagicMock(prompt_token_count=10, candidates_token_count=20),
    )


def _client_with_seq(tmp: str, responses: list[MagicMock]) -> GeminiClient:
    mock_genai = MagicMock()
    mock_genai.models.generate_content.side_effect = responses
    mock_genai.files.upload.return_value = MagicMock()
    with _IsolatedEnv():
        s = load_settings(toml_path=None, cwd=Path(tmp))
    s = s.model_copy(
        update={
            "paths": PathsSettings(
                cache_dir=Path(tmp) / ".cache",
                output_dir=Path(tmp) / "outputs",
            )
        }
    )
    return GeminiClient(s, _genai_client=mock_genai)


class HybridCorrectPaperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.ms = _hybrid_paper_mark_scheme()

    def _extracted(self, mcq_answer: str, theory_answer: str) -> ExtractedAnswers:
        return ExtractedAnswers(
            paper_id="test",
            source_scan="scan.png",
            answers=[
                ExtractedAnswer(question_id="1", answer=mcq_answer, confidence=0.99),
                ExtractedAnswer(question_id="2", answer=theory_answer, confidence=0.85),
            ],
        )

    def test_mcq_only_flag_skips_ai_and_marks_theory_missing(self) -> None:
        result = correct_paper(
            mark_scheme=self.ms,
            extracted_answers=self._extracted("A", "because gravity"),
            gemini_client=None,
            mcq_only=True,
        )
        self.assertEqual(len(result.questions), 2)
        q1 = next(q for q in result.questions if q.question_id == "1")
        q2 = next(q for q in result.questions if q.question_id == "2")
        self.assertEqual(q1.marker_source, "deterministic")
        self.assertEqual(q1.awarded_marks, 1)
        self.assertEqual(q2.marker_source, "missing")
        self.assertEqual(q2.awarded_marks, 0)

    def test_hybrid_routes_mcq_deterministic_theory_to_ai(self) -> None:
        client = _client_with_seq(self.tmp, [_mock_marker_response(2, ["p1", "p2"], "full marks")])
        result = correct_paper(
            mark_scheme=self.ms,
            extracted_answers=self._extracted("A", "because gravity and no air resistance"),
            gemini_client=client,
            mcq_only=False,
        )
        q1 = next(q for q in result.questions if q.question_id == "1")
        q2 = next(q for q in result.questions if q.question_id == "2")
        self.assertEqual(q1.marker_source, "deterministic")
        self.assertEqual(q1.awarded_marks, 1)
        self.assertEqual(q2.marker_source, "ai")
        self.assertEqual(q2.awarded_marks, 2)
        self.assertEqual(q2.matched_point_ids, ["p1", "p2"])

    def test_hybrid_without_client_raises_config_error(self) -> None:
        with self.assertRaises(ConfigError):
            correct_paper(
                mark_scheme=self.ms,
                extracted_answers=self._extracted("A", "x"),
                gemini_client=None,
                mcq_only=False,
            )

    def test_awarded_marks_clamped_to_question_max(self) -> None:
        client = _client_with_seq(self.tmp, [_mock_marker_response(5, ["p1", "p2"], "ok")])
        result = correct_paper(
            mark_scheme=self.ms,
            extracted_answers=self._extracted("A", "answer"),
            gemini_client=client,
            mcq_only=False,
        )
        q2 = next(q for q in result.questions if q.question_id == "2")
        self.assertEqual(q2.awarded_marks, 2)  # clamped

    def test_extraction_confidence_propagates_through_mcq_path(self) -> None:
        """CorrectedQuestion.extraction_confidence carries the extractor's confidence (#36/M1.1)."""
        extracted = ExtractedAnswers(
            paper_id="test",
            source_scan="scan.png",
            answers=[
                ExtractedAnswer(question_id="1", answer="A", confidence=0.77),
                ExtractedAnswer(question_id="2", answer="because gravity", confidence=0.42),
            ],
        )
        result = correct_paper(
            mark_scheme=self.ms,
            extracted_answers=extracted,
            gemini_client=None,
            mcq_only=True,
        )
        q1 = next(q for q in result.questions if q.question_id == "1")
        self.assertEqual(q1.extraction_confidence, 0.77)

    def test_extraction_confidence_propagates_through_ai_marked_path(self) -> None:
        """extraction_confidence flows into the AI-marked (non-MCQ) CorrectedQuestion too."""
        client = _client_with_seq(self.tmp, [_mock_marker_response(2, ["p1", "p2"], "ok")])
        extracted = ExtractedAnswers(
            paper_id="test",
            source_scan="scan.png",
            answers=[
                ExtractedAnswer(question_id="1", answer="A", confidence=0.99),
                ExtractedAnswer(question_id="2", answer="because gravity", confidence=0.42),
            ],
        )
        result = correct_paper(
            mark_scheme=self.ms,
            extracted_answers=extracted,
            gemini_client=client,
            mcq_only=False,
        )
        q2 = next(q for q in result.questions if q.question_id == "2")
        self.assertEqual(q2.extraction_confidence, 0.42)

    def test_mcq_confidence_score_tracks_extraction_confidence(self) -> None:
        """MUST-FIX 1 (#36 repair): a correct MCQ's confidence_score must MOVE with
        extraction_confidence, not stay hardcoded at 1.0 (D13). Two different
        extraction confidences on the same correct letter must produce two
        different confidence_score values, each equal to the extraction
        confidence that produced it.
        """
        high = ExtractedAnswers(
            paper_id="test",
            source_scan="scan.png",
            answers=[ExtractedAnswer(question_id="1", answer="A", confidence=0.93)],
        )
        low = ExtractedAnswers(
            paper_id="test",
            source_scan="scan.png",
            answers=[ExtractedAnswer(question_id="1", answer="A", confidence=0.55)],
        )
        result_high = correct_paper(
            mark_scheme=self.ms, extracted_answers=high, gemini_client=None, mcq_only=True
        )
        result_low = correct_paper(
            mark_scheme=self.ms, extracted_answers=low, gemini_client=None, mcq_only=True
        )
        q_high = next(q for q in result_high.questions if q.question_id == "1")
        q_low = next(q for q in result_low.questions if q.question_id == "1")

        self.assertEqual(q_high.awarded_marks, q_high.maximum_marks)  # correct answer
        self.assertEqual(q_low.awarded_marks, q_low.maximum_marks)  # correct answer
        self.assertNotEqual(q_high.confidence_score, q_low.confidence_score)
        self.assertEqual(q_high.confidence_score, 0.93)
        self.assertEqual(q_low.confidence_score, 0.55)

    def test_high_extraction_confidence_correct_mcq_is_not_flagged(self) -> None:
        """Sanity check on option A: a clean single-letter extraction at ~0.93
        (the option-A steady state) must land HIGH and unflagged -- correct
        MCQs must not flood the review queue.
        """
        extracted = ExtractedAnswers(
            paper_id="test",
            source_scan="scan.png",
            answers=[ExtractedAnswer(question_id="1", answer="A", confidence=0.93)],
        )
        result = correct_paper(
            mark_scheme=self.ms, extracted_answers=extracted, gemini_client=None, mcq_only=True
        )
        q1 = next(q for q in result.questions if q.question_id == "1")
        self.assertEqual(q1.confidence, ConfidenceBand.HIGH)
        self.assertFalse(q1.needs_teacher_review)

    def test_low_extraction_confidence_correct_mcq_is_routed_to_review(self) -> None:
        """The point of the fix: a correct MCQ whose LETTER was read with low
        extraction confidence must be flagged for review, not auto-graded at
        1.0/HIGH -- the deterministic comparison being certain does not mean
        the extraction it was applied to was certain.
        """
        extracted = ExtractedAnswers(
            paper_id="test",
            source_scan="scan.png",
            answers=[ExtractedAnswer(question_id="1", answer="A", confidence=0.55)],
        )
        result = correct_paper(
            mark_scheme=self.ms, extracted_answers=extracted, gemini_client=None, mcq_only=True
        )
        q1 = next(q for q in result.questions if q.question_id == "1")
        self.assertEqual(q1.awarded_marks, q1.maximum_marks)  # still correct
        self.assertTrue(q1.needs_teacher_review)
        self.assertNotEqual(q1.confidence, ConfidenceBand.HIGH)


class DroppedAnswerReviewFlagTests(unittest.TestCase):
    """US-031 review MUST-FIX 7, stronger fix: an answer the model RETURNED
    but extraction discarded as malformed must be distinguishable from a
    genuine student blank, unconditionally flagged for review, and must
    never reach the paid AI marker (marking an empty string extraction
    already knew was unusable is waste on top of an already-wrong mark).

    Before this fix, ``ExtractedAnswers.dropped_question_ids`` did not
    exist and ``correct_paper`` had no way to tell "the model answered this
    and it was dropped" from "the model never answered this" -- both looked
    identical (``student_answer=None``). For an MCQ leaf that happened to be
    safe (the existing "missing answer" branch already flags for review);
    for a non-MCQ leaf it was not: ``ai.mark_question`` was called with
    ``student_answer or ""`` and could return a confident judgement that
    tripped none of ``_build_ai_corrected``'s four review gates -- a student
    marked wrong with no human ever told.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.ms = _hybrid_paper_mark_scheme()  # "1" = MCQ, "2" = non-MCQ

    def test_dropped_non_mcq_answer_is_flagged_without_a_paid_call(self) -> None:
        extracted = ExtractedAnswers(
            paper_id="test",
            source_scan="scan.png",
            answers=[ExtractedAnswer(question_id="1", answer="A", confidence=0.99)],
            dropped_question_ids=["2"],
        )
        # Empty side_effect: a call for q2 would raise StopIteration, but
        # that is NOT what proves the skip. `correct_paper`'s own
        # `except Exception` around `ai.mark_question` swallows it and
        # converts the question to `_build_missing_corrected` with review_reason
        # "AI marking failed: ", returning normally -- measured in review
        # Item 4, and the same reason the sibling test below needed real
        # assertions. What proves the paid call is skipped is
        # `generate_content.assert_not_called()` on the last line of this
        # test; the empty sequence only stops the stub fabricating a
        # plausible mark if that assertion is ever removed.
        client = _client_with_seq(self.tmp, [])
        result = correct_paper(
            mark_scheme=self.ms,
            extracted_answers=extracted,
            gemini_client=client,
            mcq_only=False,
        )
        q2 = next(q for q in result.questions if q.question_id == "2")
        self.assertTrue(q2.needs_teacher_review)
        self.assertEqual(q2.marker_source, "dropped")
        self.assertEqual(q2.awarded_marks, 0)
        self.assertIn("dropped", q2.review_reason or "")
        self.assertIn("malformed", q2.review_reason or "")
        self.assertNotIn("AI marking failed", q2.review_reason or "")
        client._client.models.generate_content.assert_not_called()

    def test_dropped_mcq_answer_is_flagged_with_a_distinguishing_reason(self) -> None:
        extracted = ExtractedAnswers(
            paper_id="test",
            source_scan="scan.png",
            answers=[ExtractedAnswer(question_id="2", answer="because gravity", confidence=0.9)],
            dropped_question_ids=["1"],
        )
        result = correct_paper(
            mark_scheme=self.ms,
            extracted_answers=extracted,
            gemini_client=None,
            mcq_only=True,
        )
        q1 = next(q for q in result.questions if q.question_id == "1")
        self.assertTrue(q1.needs_teacher_review)
        self.assertEqual(q1.marker_source, "dropped")
        # Distinct from _build_mcq_corrected's own "missing answer" message
        # (a genuine student blank) -- both flag for review, but only one is
        # actually true here, and the review queue should say which.
        self.assertNotEqual(q1.review_reason, "missing answer")
        self.assertIn("malformed", q1.review_reason or "")

    def test_a_dropped_non_mcq_answer_stays_dropped_under_mcq_only(self) -> None:
        """The short-circuit must sit ahead of the ``ai is None`` branch too,
        for a NON-MCQ leaf specifically.

        CORRECTION (post-54ecedfc independent review): this docstring
        previously claimed "every other test in this class ... pass a client
        with ``mcq_only=False``, so none reaches the configuration where it
        matters." That is false, and 54ecedfc's mutation table inherited the
        same error for mutation C ("short-circuit below `if ai is None`" ...
        "passed everything" pre-commit). The sibling
        ``test_dropped_mcq_answer_is_flagged_with_a_distinguishing_reason``
        (above) already passes ``gemini_client=None, mcq_only=True`` -- the
        exact configuration this docstring said nothing reached -- and,
        verified by mutation, already fails against both a moved
        short-circuit and one gated on ``ai is not None``: for an MCQ leaf,
        skipping the dropped check routes it into the unconditional
        ``if q.type == QuestionType.MCQ`` branch regardless of ``ai``, so
        ``marker_source`` stops being "dropped" there too.

        What this test adds that the MCQ sibling structurally cannot: a
        NON-MCQ leaf never reaches the MCQ branch, so a mutation that
        disables the short-circuit only for non-MCQ leaves (leaving the MCQ
        leaf, and hence the sibling test, untouched) falls through instead to
        ``_build_missing_corrected`` and surfaces as ``marker_source=
        "missing"`` with "non-MCQ question not marked (--mcq-only or no AI
        client)" -- telling the teacher we CHOSE not to mark this question,
        when the model in fact returned an answer for it that extraction
        discarded. That is the exact conflation MF7 exists to remove, and
        this is the only test in the class that can catch it reappearing.
        """
        extracted = ExtractedAnswers(
            paper_id="test",
            source_scan="scan.png",
            answers=[ExtractedAnswer(question_id="1", answer="A", confidence=0.99)],
            dropped_question_ids=["2"],  # "2" is the non-MCQ leaf
        )
        result = correct_paper(
            mark_scheme=self.ms,
            extracted_answers=extracted,
            gemini_client=None,
            mcq_only=True,
        )
        q2 = next(q for q in result.questions if q.question_id == "2")
        self.assertTrue(q2.needs_teacher_review)
        self.assertEqual(q2.marker_source, "dropped")
        self.assertEqual(q2.awarded_marks, 0)
        # Distinct from BOTH blank messages a dropped answer can be mistaken
        # for -- the MCQ path's "missing answer" and this path's own --mcq-only
        # string. Asserting only `needs_teacher_review` would pass either way:
        # both alternatives also flag, which is what makes the conflation quiet.
        self.assertIn("dropped", q2.review_reason or "")
        self.assertIn("malformed", q2.review_reason or "")
        self.assertNotEqual(q2.review_reason, "missing answer")
        self.assertNotIn("--mcq-only", q2.review_reason or "")

    def test_a_genuinely_missing_answer_still_uses_the_original_message(self) -> None:
        """Control: a question with no answer at all, and NOT listed in
        dropped_question_ids, must still read as a genuine blank -- the two
        must not be conflated in either direction."""
        extracted = ExtractedAnswers(
            paper_id="test",
            source_scan="scan.png",
            answers=[ExtractedAnswer(question_id="2", answer="because gravity", confidence=0.9)],
        )
        result = correct_paper(
            mark_scheme=self.ms,
            extracted_answers=extracted,
            gemini_client=None,
            mcq_only=True,
        )
        q1 = next(q for q in result.questions if q.question_id == "1")
        self.assertTrue(q1.needs_teacher_review)
        self.assertEqual(q1.marker_source, "deterministic")
        self.assertEqual(q1.review_reason, "missing answer")

    def test_dropped_answer_does_not_affect_other_questions_on_the_same_paper(self) -> None:
        client = _client_with_seq(self.tmp, [])
        extracted = ExtractedAnswers(
            paper_id="test",
            source_scan="scan.png",
            answers=[ExtractedAnswer(question_id="1", answer="A", confidence=0.99)],
            dropped_question_ids=["2"],
        )
        result = correct_paper(
            mark_scheme=self.ms,
            extracted_answers=extracted,
            gemini_client=client,
            mcq_only=False,
        )
        q1 = next(q for q in result.questions if q.question_id == "1")
        self.assertEqual(q1.marker_source, "deterministic")
        self.assertEqual(q1.awarded_marks, 1)
        self.assertFalse(q1.needs_teacher_review)
        # US-031 review SHOULD-FIX F2: assert on q2 as well, or this test is
        # vacuous for its own stated purpose. With the short-circuit broken, q2
        # falls through to the AI path, `_client_with_seq(self.tmp, [])` raises
        # `StopIteration`, and `correct_paper`'s own `except Exception` turns it
        # into `_build_missing_corrected` -- so every assertion above still
        # passes while the behaviour under test is gone. The empty `side_effect`
        # is NOT a live control; only these assertions are.
        q2 = next(q for q in result.questions if q.question_id == "2")
        self.assertEqual(q2.marker_source, "dropped")
        self.assertTrue(q2.needs_teacher_review)
        self.assertIn("dropped", q2.review_reason or "")
        # The three assertions above are still not enough on their own. Replace
        # the short-circuit's `continue` with `pass` and q2 is appended TWICE --
        # correctly as "dropped" first, then again off the AI path -- so `next()`
        # finds the good one and all three pass while a paid call happened. Only
        # this line catches that.
        client._client.models.generate_content.assert_not_called()
        # Independent-review follow-up (mutJ7 hunt): every assertion above
        # about q2's marks reads the NUMERATOR (`awarded_marks`), and the
        # `bus.publish` frame asserted in MarkingProgressCounterTests reads
        # `max_marks=q.marks` and `confidence=0.0` -- literals taken straight
        # from the `Question`/the publish call, not from the
        # `CorrectedQuestion` `_build_dropped_corrected` actually returns.
        # Neither pins `_build_dropped_corrected`'s own denominator or
        # confidence fields, so zeroing `maximum_marks` there silently
        # shrinks `CorrectionResult.maximum_marks` (a paper's percentage
        # inflates, e.g. 33.3% -> 100.0% here) with every existing assertion
        # still green. Assert the record itself, at both the question and
        # the paper level, plus the confidence pair the same function sets.
        self.assertEqual(q2.maximum_marks, 2)
        self.assertEqual(result.maximum_marks, 3)
        self.assertEqual(q2.confidence, ConfidenceBand.LOW)
        self.assertEqual(q2.confidence_score, 0.0)
        # Was an equivalent mutant (mutJ7 mutation P): `topic_hint` was unset
        # on every leaf in this fixture, so mutating `topic=question.topic_hint`
        # -> `None` produced byte-identical output and no test -- this one
        # included -- could discriminate. Question "2" now carries a
        # `topic_hint` so this assertion is a real regression guard.
        self.assertEqual(q2.topic, "forces")


class BlankAnswerShortCircuitTests(unittest.TestCase):
    """US-039: a non-MCQ leaf the student left BLANK must not pay for a
    marking call, and must not come back as a confident, unflagged-by-accident
    zero.

    Before this fix, ``correct_paper`` reached ``ai.mark_question(q,
    student_answer or "", ...)`` for a blank exactly like it did for real text
    -- a full paid call to mark the empty string, which could return a
    confident judgement (e.g. "blank, 0 marks", HIGH confidence) tripping none
    of ``_build_ai_corrected``'s review gates. Two defects at once: spend
    (one paid call per blank per paper) and honesty (0.97 confidence asserted
    about no student work at all).

    The product owner's ruling (see the brief) is deliberate and not
    re-litigated here: a blank non-MCQ answer becomes an UNFLAGGED zero with
    NO paid call. A flagged zero was rejected -- it would flag every genuine
    blank on every paper and train teachers to bulk-approve without looking.
    ``marker_source`` reuses ``"missing"`` (no engine ran, which is exactly
    what that value already means); the blank-vs-not-marked distinction lives
    in ``review_reason``, following the precedent US-031 set for ``"dropped"``
    before its own enum member existed.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.ms = _hybrid_paper_mark_scheme()  # "1" = MCQ, "2" = non-MCQ

    def test_blank_non_mcq_answer_is_unflagged_zero_without_a_paid_call(self) -> None:
        # No ExtractedAnswer for "2" at all -- the "no entry" shape of blank.
        extracted = ExtractedAnswers(
            paper_id="test",
            source_scan="scan.png",
            answers=[ExtractedAnswer(question_id="1", answer="A", confidence=0.99)],
        )
        client = _client_with_seq(self.tmp, [])
        result = correct_paper(
            mark_scheme=self.ms,
            extracted_answers=extracted,
            gemini_client=client,
            mcq_only=False,
        )
        q2 = next(q for q in result.questions if q.question_id == "2")
        self.assertEqual(q2.marker_source, "missing")
        self.assertEqual(q2.awarded_marks, 0)
        # The ruling: UNFLAGGED, not a flagged zero.
        self.assertFalse(q2.needs_teacher_review)
        # Honest about the fact that no model judged anything -- not the
        # HIGH/0.97 the pre-fix path could assert about an empty string.
        self.assertEqual(q2.confidence, ConfidenceBand.LOW)
        self.assertEqual(q2.confidence_score, 0.0)
        # Distinguishable from every other blank-shaped message this path can
        # produce, per the enum ruling (carry the distinction in
        # review_reason since marker_source is shared with "missing").
        #
        # US-039 MUST-FIX 3 (independent review, blocking 674f309d): asserted
        # POSITIVELY against the module constant rather than via
        # `assertNotEqual`/`assertNotIn` against unrelated literals -- with
        # `review_reason=None` every one of those negative assertions passed
        # vacuously (`assertNotIn(x, "")` is trivially true), so dropping
        # `review_reason` entirely made a genuine blank and a `--mcq-only`
        # skip byte-identical in the database and this test still went green.
        # MUST-FIX C (post-US-039-review): the module-constant comparison
        # above pins nothing about the VALUE -- `_build_blank_corrected`
        # reads `_BLANK_ANSWER_REVIEW_REASON` as a module global and so does
        # this assertion, so both sides move together under ANY mutation of
        # the constant (run-verified: setting it to
        # `_build_missing_corrected`'s own message still passes). What the
        # constant's own docstring says it must guarantee is DISTINCTNESS
        # from the other three blank-shaped messages, which a same-global
        # comparison cannot check at all. Assert the literal string instead
        # -- see PairwiseDistinctBlankReasonsTests below for the
        # distinctness guarantee itself.
        self.assertEqual(
            q2.review_reason,
            "student left this question blank (0 awarded, no AI call made)",
        )
        self.assertEqual(q2.review_reason, correction_ai._BLANK_ANSWER_REVIEW_REASON)
        # Field-mutation survivors from the same review: `topic` and
        # `maximum_marks` (on the question AND the paper total) previously
        # went unpinned by any assertion in this class.
        self.assertEqual(q2.topic, "forces")
        self.assertEqual(q2.maximum_marks, 2)
        self.assertEqual(result.maximum_marks, 3)
        client._client.models.generate_content.assert_not_called()

    def test_empty_string_answer_is_treated_as_blank(self) -> None:
        extracted = ExtractedAnswers(
            paper_id="test",
            source_scan="scan.png",
            answers=[
                ExtractedAnswer(question_id="1", answer="A", confidence=0.99),
                ExtractedAnswer(question_id="2", answer="", confidence=0.9),
            ],
        )
        client = _client_with_seq(self.tmp, [])
        result = correct_paper(
            mark_scheme=self.ms,
            extracted_answers=extracted,
            gemini_client=client,
            mcq_only=False,
        )
        q2 = next(q for q in result.questions if q.question_id == "2")
        self.assertEqual(q2.marker_source, "missing")
        self.assertFalse(q2.needs_teacher_review)
        client._client.models.generate_content.assert_not_called()

    def test_whitespace_only_answer_is_treated_as_blank(self) -> None:
        """Decision: a whitespace-only answer counts as blank, not as text to mark."""
        extracted = ExtractedAnswers(
            paper_id="test",
            source_scan="scan.png",
            answers=[
                ExtractedAnswer(question_id="1", answer="A", confidence=0.99),
                ExtractedAnswer(question_id="2", answer="   \n  ", confidence=0.9),
            ],
        )
        client = _client_with_seq(self.tmp, [])
        result = correct_paper(
            mark_scheme=self.ms,
            extracted_answers=extracted,
            gemini_client=client,
            mcq_only=False,
        )
        q2 = next(q for q in result.questions if q.question_id == "2")
        self.assertEqual(q2.marker_source, "missing")
        self.assertFalse(q2.needs_teacher_review)
        # US-039 MUST-FIX 3 survivor: `extraction_confidence -> None` went
        # undetected in the no-answer-entry test above because the true value
        # is already `None` there (no ExtractedAnswer for "2" at all). This
        # scenario carries a real extracted confidence (0.9, whitespace
        # answer) for a value a hardcoded-`None` mutant would falsify.
        self.assertEqual(q2.extraction_confidence, 0.9)
        client._client.models.generate_content.assert_not_called()

    def test_blank_answer_with_substantial_working_still_calls_the_marker(self) -> None:
        """Decision: a blank answer box is not treated as a true blank when the
        student left substantial working -- awarding an unflagged 0 to a
        question the student visibly attempted is a worse claim than awarding
        it to a truly empty one, so this must still reach the AI marker.
        """
        extracted = ExtractedAnswers(
            paper_id="test",
            source_scan="scan.png",
            answers=[
                ExtractedAnswer(question_id="1", answer="A", confidence=0.99),
                ExtractedAnswer(
                    question_id="2",
                    answer="",
                    working_out="F = ma, so the object accelerates due to gravity",
                    confidence=0.9,
                ),
            ],
        )
        client = _client_with_seq(self.tmp, [_mock_marker_response(1, ["p1"])])
        result = correct_paper(
            mark_scheme=self.ms,
            extracted_answers=extracted,
            gemini_client=client,
            mcq_only=False,
        )
        q2 = next(q for q in result.questions if q.question_id == "2")
        self.assertEqual(q2.marker_source, "ai")
        client._client.models.generate_content.assert_called_once()

    def test_mcq_blank_answer_is_unaffected(self) -> None:
        """MCQ is already correct (``_build_mcq_corrected``'s own blank branch:
        LOW, 0.0, flagged, no call) and must stay on that path untouched."""
        extracted = ExtractedAnswers(
            paper_id="test",
            source_scan="scan.png",
            answers=[ExtractedAnswer(question_id="2", answer="because gravity", confidence=0.9)],
        )
        client = _client_with_seq(self.tmp, [_mock_marker_response(2, ["p1", "p2"])])
        result = correct_paper(
            mark_scheme=self.ms,
            extracted_answers=extracted,
            gemini_client=client,
            mcq_only=False,
        )
        q1 = next(q for q in result.questions if q.question_id == "1")
        self.assertEqual(q1.marker_source, "deterministic")
        self.assertTrue(q1.needs_teacher_review)
        self.assertEqual(q1.review_reason, "missing answer")

    def test_position_mutation_mcq_only_blank_still_reads_as_chose_not_to_mark(self) -> None:
        """Position mutation guard: the blank short-circuit sits AFTER
        ``if ai is None`` in ``correct_paper``, not before it. Under
        ``--mcq-only``, ``marker_source="missing"`` means "we chose not to
        mark this" -- a different statement from "the student left it blank
        and earns 0". Moving the short-circuit above the ``ai is None`` check
        would make a blank read identically to a --mcq-only skip and must
        break this test.
        """
        extracted = ExtractedAnswers(
            paper_id="test",
            source_scan="scan.png",
            answers=[ExtractedAnswer(question_id="1", answer="A", confidence=0.99)],
        )
        result = correct_paper(
            mark_scheme=self.ms,
            extracted_answers=extracted,
            gemini_client=None,
            mcq_only=True,
        )
        q2 = next(q for q in result.questions if q.question_id == "2")
        self.assertEqual(q2.marker_source, "missing")
        # The pre-existing --mcq-only message, not the blank-specific one --
        # and, per the pre-existing --mcq-only contract, still FLAGGED, unlike
        # a real blank under a configured AI marker.
        self.assertEqual(
            q2.review_reason, "non-MCQ question not marked (--mcq-only or no AI client)"
        )
        self.assertTrue(q2.needs_teacher_review)


class PairwiseDistinctBlankReasonsTests(unittest.TestCase):
    """MUST-FIX C (post-US-039-review): the four blank-shaped
    ``review_reason`` messages must be pairwise DISTINCT strings, which is
    the actual property ``_BLANK_ANSWER_REVIEW_REASON``'s own docstring
    claims (``correction_ai.py``, "distinct from every other blank-shaped
    message this module can produce").

    A same-module-global comparison (``review_reason ==
    correction_ai._BLANK_ANSWER_REVIEW_REASON``) cannot catch a copy-paste
    that sets two of these constants to the identical string, because both
    sides of that comparison would move together. This test would catch it:
    it fails if any two of the four collide.

    Why this matters beyond tidiness: ``attempt_repo.py``'s review-queue
    exemption keys on the literal blank message
    (``_BLANK_ANSWER_REVIEW_REASON``) to skip queuing a genuine blank. If a
    maintainer ever copy-pasted ``_build_missing_corrected``'s message onto
    it, a genuine blank and a ``--mcq-only`` skip would carry an identical
    ``marker_source`` ("missing") AND an identical ``review_reason`` --
    indistinguishable to that exemption, which would then also silently
    skip queuing the ``--mcq-only`` case it was never meant to exempt.
    """

    def test_all_four_blank_shaped_reasons_are_pairwise_distinct(self) -> None:
        """NIT 5 fix (post-review): the previous version of this test read
        two of the four values from the module (catching a constant-side
        mutation) but HARDCODED its own copies of the other two
        ("missing answer" and the ``--mcq-only`` string) -- so a
        literal-side mutation (e.g. `_build_mcq_corrected`'s inline
        ``"missing answer"`` changed to collide with the blank message, a
        plausible DRY edit) went undetected: the test's own copy stayed
        unaffected while the real messages collided. All four are now
        produced by calling the SAME builder functions ``correct_paper``
        itself calls, so a mutation to any of the four literals is
        reflected here automatically."""
        from lemely.core.loose_schemas import MCQAnswer, Question, QuestionType
        from lemely.io.correction_ai import _build_mcq_corrected, _build_missing_corrected

        mcq_question = Question.model_construct(
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
        non_mcq_question = Question.model_construct(
            id="2",
            marks=1,
            type=QuestionType.EXPLANATION,
            parts=[],
            assessment_objectives=[],
            answer_points=[],
            rejected_answers=[],
            ignored_answers=[],
        )
        mcq_missing_answer_reason = _build_mcq_corrected(mcq_question, None).review_reason
        mcq_only_or_no_client_reason = _build_missing_corrected(
            non_mcq_question, None
        ).review_reason

        reasons = {
            "blank": correction_ai._BLANK_ANSWER_REVIEW_REASON,
            "dropped": correction_ai._DROPPED_ANSWER_REVIEW_REASON,
            "mcq_missing_answer": mcq_missing_answer_reason,
            "mcq_only_or_no_client": mcq_only_or_no_client_reason,
        }
        self.assertEqual(len(set(reasons.values())), len(reasons), reasons)


class MCQAbstainHardeningTests(unittest.TestCase):
    """Defensive hardening for a latent, unreachable branch (D15, spec §2.2(ii)).

    ``Question`` itself forbids ``mcq_answer=None`` for an MCQ-typed question
    (see the model validator raising in ``loose_schemas.py``), so this branch
    cannot be reached through any real parsing path today — this is NOT a
    regression test for a live defect, it documents the defensive hardening
    added to ``_build_mcq_corrected`` in case that invariant is ever violated
    (e.g. a future relaxed parser, a hand-built fixture). Before this change,
    a Question with ``mcq_answer=None`` silently fell through to
    ``awarded_marks=0, confidence_score=1.0, HIGH, needs_teacher_review=False``
    — a wrong mark reported with full, unflagged confidence.
    """

    def test_mcq_answer_none_abstains_with_low_confidence_and_review_flag(self) -> None:
        question = Question.model_construct(
            id="1",
            parent_id=None,
            marks=1,
            type=QuestionType.MCQ,
            mcq_answer=None,
            parts=[],
            topic_hint=None,
        )
        result = _build_mcq_corrected(question, "A")
        self.assertEqual(result.confidence_score, 0.0)
        self.assertTrue(result.needs_teacher_review)
        self.assertIsNotNone(result.review_reason)


class ECFContextTests(unittest.TestCase):
    """correct_paper accumulates prior results and injects sibling context."""

    def _multi_part_scheme(self):
        from lemely.core.loose_schemas import MarkScheme

        return MarkScheme.model_validate(
            {
                "metadata": {
                    "subject": "Physics",
                    "subject_code": "0625",
                    "paper_number": 4,
                    "paper_variant": 2,
                    "session_month": "May/June",
                    "session_year": 2020,
                    "paper_type": "theory_extended",
                    "maximum_mark": 4,
                    "scheme_format": "point_based",
                },
                "questions": [
                    {
                        "id": "1",
                        "marks": 0,
                        "type": "explanation",
                        "parts": [
                            {
                                "id": "1(a)",
                                "marks": 2,
                                "type": "explanation",
                                "parent_id": "1",
                                "answer_points": [
                                    {"id": "p1", "point": "method", "marks": 1},
                                    {"id": "p2", "point": "answer", "marks": 1},
                                ],
                            },
                            {
                                "id": "1(b)",
                                "marks": 2,
                                "type": "explanation",
                                "parent_id": "1",
                                "answer_points": [
                                    {"id": "p3", "point": "uses result of (a)", "marks": 2},
                                ],
                            },
                        ],
                    }
                ],
            }
        )

    def test_prior_results_injected_for_second_part(self):
        """build_marker_user_prompt for 1(b) must receive prior_results containing 1(a)."""
        import json
        import tempfile
        from unittest.mock import MagicMock, patch

        from lemely.core.schemas import ExtractedAnswer, ExtractedAnswers
        from lemely.io.correction_ai import correct_paper

        scheme = self._multi_part_scheme()
        extracted = ExtractedAnswers(
            paper_id="test",
            source_scan="s.pdf",
            answers=[
                ExtractedAnswer(question_id="1(a)", answer="v=20 m/s", confidence=0.9),
                ExtractedAnswer(question_id="1(b)", answer="uses 20", confidence=0.9),
            ],
        )
        ai_body = json.dumps(
            {
                "awarded_marks": 1,
                "confidence": 0.9,
                "matched_point_ids": [],
                "feedback": "ok",
            }
        )
        mock_resp = MagicMock(
            text=ai_body,
            candidates=[MagicMock(finish_reason=MagicMock(__str__=lambda s: "STOP"))],
            usage_metadata=MagicMock(prompt_token_count=10, candidates_token_count=20),
        )
        with tempfile.TemporaryDirectory() as tmp:
            client = _client_with_seq(tmp, [mock_resp, mock_resp])

        captured: list[dict] = []

        import lemely.io.correction_ai as _corr_mod
        import lemely.io.prompts.correction_ai as _prompt_mod

        original_fn = _prompt_mod.build_marker_user_prompt

        def _spy(*args, **kwargs):
            captured.append({"args": args, "kwargs": kwargs})
            return original_fn(*args, **kwargs)

        with patch.object(_corr_mod, "build_marker_user_prompt", side_effect=_spy):
            correct_paper(scheme, extracted, gemini_client=client)

        self.assertEqual(len(captured), 2)
        second_kwargs = captured[1]["kwargs"]
        second_args = captured[1]["args"]
        prior = second_kwargs.get("prior_results") or (
            second_args[3] if len(second_args) > 3 else None
        )
        self.assertIsNotNone(
            prior, "prior_results not passed to second build_marker_user_prompt call"
        )
        self.assertIn("1(a)", prior)

    def test_golden_fixture_siblings_carry_prior_results_into_ai_prompt(self):
        """M0.8 (#32) regression: the golden corpus must actually exercise the
        sibling_prior / PRIOR PART RESULTS path, not just a hand-built scheme.

        ``0580_s23_qp_22_theory_correct`` has two leaves, ``12a`` and ``12b``,
        sharing ``parent_id="12"``. Before #32 every golden fixture had
        ``parent_id=None`` on every leaf, so ``correct_paper``'s
        ``if q.parent_id is not None:`` branch (correction_ai.py:464) never
        fired for any leaf loaded via :func:`load_golden_cases`, and this test
        failed with ``prior_results not passed`` for ``12b``. It passes once
        the fixture's ``mark_scheme.json`` carries real ``parent_id`` values.
        """
        import json
        import tempfile
        from pathlib import Path
        from unittest.mock import MagicMock, patch

        from lemely.accuracy.harness import load_golden_cases
        from lemely.core.schemas import ExtractedAnswer, ExtractedAnswers
        from lemely.io.correction_ai import correct_paper

        golden_dir = Path(__file__).resolve().parent / "golden"
        cases = load_golden_cases(golden_dir)
        case = next(c for c in cases if c.paper_id == "0580_s23_qp_22_theory")

        leaf_count = len(case.mark_scheme.all_questions_flat())
        ai_body = json.dumps(
            {
                "awarded_marks": 1,
                "confidence": 0.95,
                "matched_point_ids": [],
                "feedback": "ok",
            }
        )
        mock_resp = MagicMock(
            text=ai_body,
            candidates=[MagicMock(finish_reason=MagicMock(__str__=lambda s: "STOP"))],
            usage_metadata=MagicMock(prompt_token_count=10, candidates_token_count=20),
        )
        extracted = ExtractedAnswers(
            paper_id=case.paper_id,
            source_scan="golden",
            answers=[
                ExtractedAnswer(question_id=qid, answer=gt.student_answer, confidence=1.0)
                for qid, gt in case.ground_truth.items()
            ],
        )

        with tempfile.TemporaryDirectory() as tmp:
            client = _client_with_seq(tmp, [mock_resp] * leaf_count)

        captured: list[dict] = []
        import lemely.io.correction_ai as _corr_mod
        import lemely.io.prompts.correction_ai as _prompt_mod

        original_fn = _prompt_mod.build_marker_user_prompt

        def _spy(*args, **kwargs):
            captured.append({"args": args, "kwargs": kwargs})
            return original_fn(*args, **kwargs)

        with patch.object(_corr_mod, "build_marker_user_prompt", side_effect=_spy):
            correct_paper(case.mark_scheme, extracted, gemini_client=client)

        call_12b = next(c for c in captured if c["args"][0].id == "12b")
        prior = call_12b["kwargs"].get("prior_results") or (
            call_12b["args"][3] if len(call_12b["args"]) > 3 else None
        )
        self.assertIsNotNone(
            prior, "prior_results not passed to build_marker_user_prompt for sibling '12b'"
        )
        self.assertIn("12a", prior)

    def test_nested_fixture_1a_i_prior_results_reach_1a_ii(self):
        """M0.8 (#32) regression: ``0625_w21_qp_32_theory_nested`` exists to
        exercise the PRIOR PART RESULTS (ECF) chain for a *nested* leaf pair,
        but until this fixture is split it has only one leaf under ``1a``
        (``1a_i``) and a second leaf ``1b`` under a different parent (``1``),
        so ``correct_paper``'s exact-``parent_id``-equality sibling grouping
        (correction_ai.py:464-469) never finds a sibling for either leaf and
        ``sibling_prior`` is always empty. Splitting ``1a_i`` into ``1a_i``
        and ``1a_ii`` (both ``parent_id="1a"``) gives the fixture a genuine
        sibling pair, and this test asserts ``1a_ii``'s marking call receives
        ``1a_i``'s awarded marks via ``prior_results``.

        Note: issue #32's literal wording "(a)(i) -> (b)" sibling grouping is
        mathematically impossible under correction_ai.py's exact-parent_id
        grouping (1a_i's parent is "1a", 1b's parent is "1" -- they can never
        be siblings). Only an (a)(i) -> (a)(ii) chain is achievable, so that
        is what this test exercises instead.
        """
        import json
        import tempfile
        from pathlib import Path
        from unittest.mock import MagicMock, patch

        from lemely.accuracy.harness import load_golden_cases
        from lemely.core.schemas import ExtractedAnswer, ExtractedAnswers
        from lemely.io.correction_ai import correct_paper

        golden_dir = Path(__file__).resolve().parent / "golden"
        cases = load_golden_cases(golden_dir)
        case = next(c for c in cases if c.paper_id == "0625_w21_qp_32_theory_nested")

        leaf_count = len(case.mark_scheme.all_questions_flat())
        ai_body = json.dumps(
            {
                "awarded_marks": 1,
                "confidence": 0.95,
                "matched_point_ids": [],
                "feedback": "ok",
            }
        )
        mock_resp = MagicMock(
            text=ai_body,
            candidates=[MagicMock(finish_reason=MagicMock(__str__=lambda s: "STOP"))],
            usage_metadata=MagicMock(prompt_token_count=10, candidates_token_count=20),
        )
        extracted = ExtractedAnswers(
            paper_id=case.paper_id,
            source_scan="golden",
            answers=[
                ExtractedAnswer(question_id=qid, answer=gt.student_answer, confidence=1.0)
                for qid, gt in case.ground_truth.items()
            ],
        )

        with tempfile.TemporaryDirectory() as tmp:
            client = _client_with_seq(tmp, [mock_resp] * leaf_count)

        captured: list[dict] = []
        import lemely.io.correction_ai as _corr_mod
        import lemely.io.prompts.correction_ai as _prompt_mod

        original_fn = _prompt_mod.build_marker_user_prompt

        def _spy(*args, **kwargs):
            captured.append({"args": args, "kwargs": kwargs})
            return original_fn(*args, **kwargs)

        with patch.object(_corr_mod, "build_marker_user_prompt", side_effect=_spy):
            correct_paper(case.mark_scheme, extracted, gemini_client=client)

        call_1a_ii = next(c for c in captured if c["args"][0].id == "1a_ii")
        prior = call_1a_ii["kwargs"].get("prior_results") or (
            call_1a_ii["args"][3] if len(call_1a_ii["args"]) > 3 else None
        )
        self.assertIsNotNone(
            prior, "prior_results not passed to build_marker_user_prompt for sibling '1a_ii'"
        )
        self.assertIn("1a_i", prior)
        self.assertEqual(prior["1a_i"], 1)


class ThresholdTests(unittest.TestCase):
    """Confidence-threshold behaviour, isolated from the M1.5 (#40) coherence
    gate: the fixture uses ``LEVELS_BASED`` (a type exempt from the coherence
    check when ``answer_points`` is empty — see ``_COHERENCE_EXEMPT_TYPES`` in
    ``lemely/io/correction_ai.py``) precisely so these tests exercise only the
    confidence mechanism, not coherence. Any other type here would now also
    trip the coherence gate (empty ``answer_points`` + ``awarded_marks > 0``
    + empty ``matched_point_ids`` is incoherent for non-exempt types since
    #40's MUST-FIX 2), conflating two independent review reasons in tests
    that are meant to isolate one.
    """

    def _make_question(self):
        from lemely.core.loose_schemas import Question, QuestionType

        return Question.model_construct(
            id="2",
            marks=2,
            type=QuestionType.LEVELS_BASED,
            answer_points=[],
            parts=[],
            assessment_objectives=[],
            rejected_answers=[],
            ignored_answers=[],
        )

    def _make_mark(self, confidence: float, awarded_marks: int = 1):
        from lemely.core.schemas import AIMarkResponse

        return AIMarkResponse(
            awarded_marks=awarded_marks,
            confidence=confidence,
            matched_point_ids=[],
            feedback="test",
        )

    # The review threshold is 0.90 as of D2.2 (was a hardcoded 0.80 that only
    # coincidentally matched ``escalation_confidence_threshold``). These tests
    # assert against the single shared constant so they cannot re-fossilise a
    # literal, and they pin the boundary as inclusive-at-threshold.
    def test_review_fires_just_below_threshold(self):
        from lemely.core.schemas import REVIEW_CONFIDENCE_THRESHOLD
        from lemely.io.correction_ai import _build_ai_corrected

        mark = self._make_mark(REVIEW_CONFIDENCE_THRESHOLD - 0.05)
        cq = _build_ai_corrected(self._make_question(), "answer", mark)
        self.assertTrue(cq.needs_teacher_review)
        self.assertIn("below review threshold", cq.review_reason or "")

    def test_review_false_at_threshold(self):
        from lemely.core.schemas import REVIEW_CONFIDENCE_THRESHOLD
        from lemely.io.correction_ai import _build_ai_corrected

        mark = self._make_mark(REVIEW_CONFIDENCE_THRESHOLD)
        cq = _build_ai_corrected(self._make_question(), "answer", mark)
        self.assertFalse(cq.needs_teacher_review)
        self.assertIsNone(cq.review_reason)

    def test_old_0_80_threshold_now_flags(self):
        """Regression guard for D2.2: 0.80 used to auto-grade, now it flags."""
        from lemely.io.correction_ai import _build_ai_corrected

        cq = _build_ai_corrected(self._make_question(), "answer", self._make_mark(0.80))
        self.assertTrue(cq.needs_teacher_review)

    def test_out_of_range_award_flags_despite_full_confidence(self):
        """A marker asking for more marks than exist is clamped AND flagged."""
        from lemely.io.correction_ai import _build_ai_corrected

        # Question is worth 2 marks; the marker asks for 4 at confidence 1.0.
        cq = _build_ai_corrected(
            self._make_question(), "answer", self._make_mark(1.0, awarded_marks=4)
        )
        self.assertEqual(cq.awarded_marks, 2)
        self.assertTrue(cq.needs_teacher_review)
        self.assertIn("clamped", cq.review_reason or "")

    def test_in_range_award_at_full_confidence_is_auto_graded(self):
        from lemely.io.correction_ai import _build_ai_corrected

        cq = _build_ai_corrected(
            self._make_question(), "answer", self._make_mark(1.0, awarded_marks=2)
        )
        self.assertEqual(cq.awarded_marks, 2)
        self.assertFalse(cq.needs_teacher_review)


class CalculatedAnswerVerificationTests(unittest.TestCase):
    """D2.3 marking-quality fix: an accuracy mark gated on a specific numerical
    result must be rejected if that value never appears in the student's
    answer/working, regardless of the marker's stated confidence."""

    def _make_question(self, calc_kwargs: dict | None = None):
        from lemely.core.loose_schemas import AnswerPoint, CalculatedAnswer, Question, QuestionType

        calc = CalculatedAnswer(**(calc_kwargs or {"value": 20.0}))
        return Question.model_construct(
            id="2",
            marks=2,
            type=QuestionType.EXPLANATION,
            answer_points=[
                AnswerPoint(id="p1", point="method", marks=1),
                AnswerPoint(id="p2", point="final answer", marks=1, calculated_answer=calc),
            ],
            parts=[],
            assessment_objectives=[],
            rejected_answers=[],
            ignored_answers=[],
        )

    def _make_mark(self, awarded_marks: int, matched: list[str], confidence: float = 1.0):
        from lemely.core.schemas import AIMarkResponse

        return AIMarkResponse(
            awarded_marks=awarded_marks,
            confidence=confidence,
            matched_point_ids=matched,
            feedback="test",
        )

    def test_missing_calculated_value_rejects_the_point_despite_full_confidence(self):
        from lemely.io.correction_ai import _build_ai_corrected

        cq = _build_ai_corrected(
            self._make_question(),
            "v = u + at, so the answer is 15",
            self._make_mark(2, ["p1", "p2"]),
            student_working="working shows 15",
        )
        self.assertEqual(cq.awarded_marks, 1)  # p2's mark stripped
        self.assertEqual(cq.matched_point_ids, ["p1"])
        self.assertTrue(cq.needs_teacher_review)
        self.assertIn("unverified accuracy mark", cq.review_reason or "")

    def test_present_calculated_value_is_credited(self):
        from lemely.io.correction_ai import _build_ai_corrected

        cq = _build_ai_corrected(
            self._make_question(),
            "v = u + at, so the answer is 20",
            self._make_mark(2, ["p1", "p2"]),
        )
        self.assertEqual(cq.awarded_marks, 2)
        self.assertEqual(cq.matched_point_ids, ["p1", "p2"])
        self.assertFalse(cq.needs_teacher_review)

    def test_value_within_stated_dp_is_credited(self):
        from lemely.io.correction_ai import _build_ai_corrected

        cq = _build_ai_corrected(
            self._make_question({"value": 3.14159, "dp": 2}),
            "the answer is 3.14",
            self._make_mark(2, ["p1", "p2"]),
        )
        self.assertEqual(cq.awarded_marks, 2)
        self.assertFalse(cq.needs_teacher_review)

    def test_value_found_in_working_not_answer_is_credited(self):
        from lemely.io.correction_ai import _build_ai_corrected

        cq = _build_ai_corrected(
            self._make_question(),
            "see working",
            self._make_mark(2, ["p1", "p2"]),
            student_working="v = u + at = 20",
        )
        self.assertEqual(cq.awarded_marks, 2)
        self.assertFalse(cq.needs_teacher_review)

    def test_point_without_calculated_answer_is_untouched(self):
        from lemely.io.correction_ai import _build_ai_corrected

        cq = _build_ai_corrected(
            self._make_question(),
            "no numbers here",
            self._make_mark(1, ["p1"]),  # only claims the non-numeric point
        )
        self.assertEqual(cq.awarded_marks, 1)
        self.assertEqual(cq.matched_point_ids, ["p1"])
        self.assertFalse(cq.needs_teacher_review)

    def test_fraction_form_matches_decimal_calculated_answer(self):
        """D2.3 fix regression guard: a student writing '3/8' must match a
        scheme value of 0.375 (accept_equivalent_forms) instead of being
        wrongly rejected — this exact case regressed a real golden fixture
        (0606 q1) when the deterministic backstop first shipped."""
        from lemely.io.correction_ai import _build_ai_corrected

        cq = _build_ai_corrected(
            self._make_question({"value": 0.375, "accept_equivalent_forms": True}),
            "a = 4, b = 3/8, c = -2",
            self._make_mark(2, ["p1", "p2"]),
        )
        self.assertEqual(cq.awarded_marks, 2)
        self.assertFalse(cq.needs_teacher_review)

    def test_division_shown_as_working_does_not_launder_a_wrong_final_value(self):
        """Regression guard: a fraction regex that evaluates ANY 'a/b' text
        would recompute the student's division itself (148/16.6=8.9...) and
        accidentally validate a wrong stated final answer (89, a decimal-place
        slip) because the *correct* arithmetic happens to appear earlier in
        the same line as working. Only the actually-stated final value must
        be checked, not intermediate working the fix could "correct" for."""
        from lemely.io.correction_ai import _build_ai_corrected

        cq = _build_ai_corrected(
            self._make_question({"value": 8.9}),
            "density = mass / volume = 148 / 16.6 = 89 g/cm3",
            self._make_mark(2, ["p1", "p2"]),
        )
        self.assertEqual(cq.awarded_marks, 1)  # p2 correctly rejected
        self.assertTrue(cq.needs_teacher_review)

    def test_correct_working_does_not_launder_a_wrong_stated_answer(self):
        """Regression guard: extraction splits the student's final numeric
        answer from their working into separate fields. A wrong stated answer
        ('9') sitting next to genuinely-correct working ('36 / 8', which
        evaluates to the target 4.5) must still be rejected — the working
        must never be consulted when the answer field already has a number."""
        from lemely.io.correction_ai import _build_ai_corrected

        cq = _build_ai_corrected(
            self._make_question({"value": 4.5}),
            "9 mg",
            self._make_mark(2, ["p1", "p2"]),
            student_working="idea of three half-lives, so 36 / 8",
        )
        self.assertEqual(cq.awarded_marks, 1)  # p2 correctly rejected
        self.assertTrue(cq.needs_teacher_review)

    def test_unmatched_point_id_is_flagged_for_review(self):
        """M1.5 (#40) strengthening: a dangling point id used to be silently
        accepted (pre-#40 this test was named
        ``test_unmatched_point_id_is_ignored_not_crashed`` and asserted
        exactly the opposite of ``needs_teacher_review`` below). It no longer
        crashes, but it is now a coherence violation that must reach a human,
        not a silent pass-through — see BUILD/DECISIONS.md for the reconcile
        semantics."""
        from lemely.io.correction_ai import _build_ai_corrected

        cq = _build_ai_corrected(
            self._make_question(),
            "answer is 20",
            self._make_mark(1, ["p_unknown"]),
        )
        self.assertEqual(cq.matched_point_ids, ["p_unknown"])
        self.assertEqual(cq.awarded_marks, 1)
        self.assertTrue(cq.needs_teacher_review)
        self.assertIn("matched_point_ids", cq.review_reason or "")
        self.assertIn("p_unknown", cq.review_reason or "")


class EquivalenceGateTests(unittest.TestCase):
    """US-005b: wires ``lemely.core.equivalence`` into
    ``_verify_calculated_answers`` as a fallback for a point the literal
    check already rejected, behind ``equivalence_gate`` (default OFF).

    D12/the module's own contract: an ``equal`` verdict — of *either* kind
    — is a review signal, never an auto-award. ``awarded_marks`` must be
    identical to the flag-off value in every case here; only the review
    reason may gain detail. ``EQUAL_PROVEN`` and ``EQUAL_SAMPLED`` are
    asserted separately so a caller collapsing them back into one boolean
    (the exact defect the module's docstring warns about) would be caught.
    """

    def _make_question(self, calc_kwargs: dict | None = None):
        from lemely.core.loose_schemas import AnswerPoint, CalculatedAnswer, Question, QuestionType

        calc = CalculatedAnswer(**(calc_kwargs or {"value": 300000000.0}))
        return Question.model_construct(
            id="2",
            marks=1,
            type=QuestionType.EXPLANATION,
            answer_points=[
                AnswerPoint(id="p1", point="final answer", marks=1, calculated_answer=calc)
            ],
            parts=[],
            assessment_objectives=[],
            rejected_answers=[],
            ignored_answers=[],
        )

    def _make_mark(self, awarded_marks: int = 1, matched: list[str] | None = None):
        from lemely.core.schemas import AIMarkResponse

        return AIMarkResponse(
            awarded_marks=awarded_marks,
            confidence=1.0,
            matched_point_ids=matched or ["p1"],
            feedback="test",
        )

    def test_flag_defaults_off_in_config(self):
        """Asserted against the config default directly, not a fixture."""
        from lemely.runtime.config import GradingSettings

        self.assertFalse(GradingSettings().equivalence_gate)

    def test_flag_off_is_byte_identical_to_omitting_it(self):
        """The golden marking path never passes ``equivalence_gate`` at
        all. Its outcome (with a student answer the equivalence module
        WOULD find equal, if consulted) must be identical to explicitly
        passing ``equivalence_gate=False`` — proving the gate is inert by
        default rather than merely asserting a branch wasn't entered."""
        from lemely.io.correction_ai import _build_ai_corrected

        question = self._make_question()
        mark = self._make_mark()
        # "3.0 x 10^8" (module docstring's own worked example) is
        # numerically 300000000 but never appears as that literal, so the
        # deterministic backstop rejects it -- a case where flag ON would
        # find EQUAL_PROVEN if consulted, making this a meaningful check
        # that omitting the kwarg really means OFF.
        golden = _build_ai_corrected(question, "3 * 10^8", mark)
        explicit_off = _build_ai_corrected(question, "3 * 10^8", mark, equivalence_gate=False)

        self.assertEqual(golden, explicit_off)
        self.assertEqual(golden.awarded_marks, 0)
        self.assertTrue(golden.needs_teacher_review)
        self.assertIn("unverified accuracy mark", golden.review_reason or "")
        self.assertNotIn("equivalence", golden.review_reason or "")

    def test_flag_on_equal_proven_does_not_auto_award(self):
        from lemely.io.correction_ai import _build_ai_corrected

        question = self._make_question()
        mark = self._make_mark()
        cq = _build_ai_corrected(question, "3 * 10^8", mark, equivalence_gate=True)

        # Not auto-awarded: identical awarded_marks/review gate to flag OFF.
        self.assertEqual(cq.awarded_marks, 0)
        self.assertTrue(cq.needs_teacher_review)
        self.assertIn("equal_proven", cq.review_reason or "")

    def test_flag_on_equal_sampled_routes_to_review_not_award(self):
        """Asserted separately from EQUAL_PROVEN: a test that lumped the two
        together would pass against the collapse-into-one-boolean defect."""
        from unittest.mock import patch

        from lemely.core.equivalence import EquivalenceMethod, Verdict, VerdictKind
        from lemely.io.correction_ai import _build_ai_corrected

        question = self._make_question()
        mark = self._make_mark()
        sampled = Verdict(VerdictKind.EQUAL_SAMPLED, method=EquivalenceMethod.NUMERIC)
        with patch("lemely.io.correction_ai.equivalent", return_value=sampled):
            cq = _build_ai_corrected(question, "some expression", mark, equivalence_gate=True)

        self.assertEqual(cq.awarded_marks, 0)
        self.assertTrue(cq.needs_teacher_review)
        self.assertIn("equal_sampled", cq.review_reason or "")
        self.assertFalse(sampled.auto_awardable)  # the property this story must respect

    def test_flag_on_not_equal_behaves_as_specified(self):
        from unittest.mock import patch

        from lemely.core.equivalence import Verdict, VerdictKind
        from lemely.io.correction_ai import _build_ai_corrected

        question = self._make_question()
        mark = self._make_mark()
        not_equal = Verdict(VerdictKind.NOT_EQUAL)
        with patch("lemely.io.correction_ai.equivalent", return_value=not_equal):
            cq = _build_ai_corrected(
                question, "something else entirely", mark, equivalence_gate=True
            )

        self.assertEqual(cq.awarded_marks, 0)
        self.assertTrue(cq.needs_teacher_review)
        self.assertNotIn("equal", (cq.review_reason or "").replace("equivalence", ""))

    def test_fallback_prefers_equal_sampled_working_over_not_equal_answer(self):
        """SHOULD-FIX from independent review of f1f146fe: the docstring of
        ``_equivalence_fallback_verdict`` claims the more informative of the
        two verdicts is kept because "an indeterminate result on one side
        must not hide a genuine finding on the other" -- but the
        implementation only special-cased ``UNPARSEABLE`` vs. non-
        ``UNPARSEABLE``. A genuine ``EQUAL_SAMPLED`` finding on the working
        side was silently discarded whenever the answer side was
        ``NOT_EQUAL`` (falling through to ``return answer_verdict``),
        exactly the case this docstring says must not happen: a student's
        clearly wrong final answer must not hide a numerically-equivalent
        (by sampling) checkpoint value in their working."""
        from lemely.core.equivalence import EquivalenceMethod, Verdict, VerdictKind
        from lemely.io.correction_ai import _equivalence_fallback_verdict

        calc = self._make_question().answer_points[0].calculated_answer
        not_equal = Verdict(VerdictKind.NOT_EQUAL)
        sampled = Verdict(VerdictKind.EQUAL_SAMPLED, method=EquivalenceMethod.NUMERIC)

        def fake_equivalent(text, target, **kwargs):
            return not_equal if text == "student_answer" else sampled

        with patch("lemely.io.correction_ai.equivalent", side_effect=fake_equivalent):
            verdict = _equivalence_fallback_verdict(calc, "student_answer", "student_working")

        self.assertIs(verdict, sampled)

    def test_flag_on_not_equal_answer_and_equal_sampled_working_routes_to_review(self):
        """End-to-end companion to the fallback-priority test above: the
        surfaced ``equal_sampled`` finding must actually reach the review
        reason via ``_build_ai_corrected``, and must never raise
        ``awarded_marks`` -- this story is marks-safe by construction."""
        from unittest.mock import patch

        from lemely.core.equivalence import EquivalenceMethod, Verdict, VerdictKind
        from lemely.io.correction_ai import _build_ai_corrected

        question = self._make_question()
        mark = self._make_mark()
        not_equal = Verdict(VerdictKind.NOT_EQUAL)
        sampled = Verdict(VerdictKind.EQUAL_SAMPLED, method=EquivalenceMethod.NUMERIC)

        def fake_equivalent(text, target, **kwargs):
            return not_equal if text == "clearly wrong final answer" else sampled

        with patch("lemely.io.correction_ai.equivalent", side_effect=fake_equivalent):
            cq = _build_ai_corrected(
                question,
                "clearly wrong final answer",
                mark,
                student_working="checkpoint expression",
                equivalence_gate=True,
            )

        self.assertEqual(cq.awarded_marks, 0)
        self.assertTrue(cq.needs_teacher_review)
        self.assertIn("equal_sampled", cq.review_reason or "")

    def test_flag_on_unparseable_never_marks_wrong_beyond_the_literal_check(self):
        """A timeout or unreadable expression must not degrade the mark any
        further than the literal check already did -- an indeterminate
        result is "could not read it", never a disproof."""
        from unittest.mock import patch

        from lemely.core.equivalence import Verdict, VerdictKind
        from lemely.io.correction_ai import _build_ai_corrected

        question = self._make_question()
        mark = self._make_mark()
        unparseable = Verdict(VerdictKind.UNPARSEABLE, detail="both methods timed out")
        with patch("lemely.io.correction_ai.equivalent", return_value=unparseable):
            cq = _build_ai_corrected(question, "illegible scrawl", mark, equivalence_gate=True)

        # Same outcome as flag OFF for this same input: the literal check
        # already rejected it, and UNPARSEABLE adds no further information.
        off = _build_ai_corrected(question, "illegible scrawl", mark, equivalence_gate=False)
        self.assertEqual(cq, off)
        self.assertEqual(cq.awarded_marks, 0)
        self.assertTrue(cq.needs_teacher_review)


class PointVerdictPromptTests(unittest.TestCase):
    """I6 (US-013): ``build_marker_user_prompt``'s ``equivalence_gate`` kwarg.

    This is the regression the predecessor's uncommitted work left broken:
    ``AICorrector.mark_question`` calls
    ``build_marker_user_prompt(..., equivalence_gate=equivalence_gate)`` but
    the function did not accept that keyword — every call with the flag on
    (and, before dispatch was wired, every call at all once the kwarg was
    added to the call site) raised ``TypeError: build_marker_user_prompt()
    got an unexpected keyword argument 'equivalence_gate'``.
    """

    def _question(self):
        from lemely.core.loose_schemas import AnswerPoint, Question, QuestionType

        return Question.model_construct(
            id="2",
            marks=2,
            type=QuestionType.EXPLANATION,
            answer_points=[
                AnswerPoint(id="p1", point="gravity acts on it", marks=1),
                AnswerPoint(id="p2", point="no air resistance", marks=1),
            ],
            parts=[],
            assessment_objectives=[],
            rejected_answers=[],
            ignored_answers=[],
        )

    def test_flag_off_prompt_is_byte_identical_to_omitting_it(self):
        from lemely.io.prompts.correction_ai import build_marker_user_prompt

        q = self._question()
        omitted = build_marker_user_prompt(q, "student text")
        explicit_off = build_marker_user_prompt(q, "student text", equivalence_gate=False)
        self.assertEqual(omitted, explicit_off)
        self.assertNotIn("point_verdicts", omitted)
        self.assertNotIn("PER-POINT VERDICTS", omitted)

    def test_flag_on_appends_point_verdict_instructions_in_evidence_verdict_total_order(self):
        from lemely.io.prompts.correction_ai import build_marker_user_prompt

        q = self._question()
        on = build_marker_user_prompt(q, "student text", equivalence_gate=True)
        self.assertIn("point_verdicts", on)
        evidence_pos = on.index("evidence_span")
        verdict_pos = on.index("verdict:")
        total_pos = on.index("compute the total")
        self.assertLess(evidence_pos, verdict_pos)
        self.assertLess(verdict_pos, total_pos)

    def test_version_not_bumped(self):
        """D19: I6/I7/I8 share one VERSION bump at US-018's funded sweep.
        Asserted against the module constant, not retyped, so a later edit
        cannot slip a bump in unnoticed."""
        from lemely.io.prompts.correction_ai import VERSION

        self.assertEqual(VERSION, "5")

    def test_mark_question_forwards_equivalence_gate_without_raising(self):
        """The actual regression: before the fix this call raised TypeError
        from inside ``build_marker_user_prompt``, on the CALL SITE the
        predecessor already wired at ``mark_question``. Uses a real
        ``GeminiClient`` over a mocked genai SDK client (``_client_with_seq``)
        rather than a bare ``MagicMock`` for ``_client``, so the escalation/
        thinking-retry machinery in ``mark_question`` runs against real
        resolved settings instead of comparing ``MagicMock`` objects."""
        from lemely.io.correction_ai import AICorrector

        q = self._question()
        response = _mock_marker_response(1, ["p1"])
        with tempfile.TemporaryDirectory() as tmp:
            client = _client_with_seq(tmp, [response])
            corrector = AICorrector(client)
            corrector.mark_question(q, "student text", equivalence_gate=True)

        sent_call = client._client.models.generate_content.call_args
        sent_contents = sent_call.kwargs["contents"]
        sent_prompt = str(sent_contents)
        self.assertIn("point_verdicts", sent_prompt)


class PriorValuesPromptRenderingTests(unittest.TestCase):
    """Post-review fix: ``build_marker_user_prompt``'s ``prior_values``
    block used to render each value with ``{value!r}``, which escapes a
    real line break in a multi-line value (answer + working) into a
    literal ``\\n`` the model cannot use as one. Dropping ``repr()``
    outright traded that for a different defect: an unindented
    continuation line at column 0 that is ambiguous with a new top-level
    entry. Fixed by indenting every line of the value under its own
    ``qid:`` header instead of rendering it inline.
    """

    def _question(self):
        from lemely.core.loose_schemas import AnswerPoint, Question, QuestionType

        return Question.model_construct(
            id="2",
            marks=1,
            type=QuestionType.EXPLANATION,
            answer_points=[AnswerPoint(id="p1", point="value", marks=1)],
            parts=[],
            assessment_objectives=[],
            rejected_answers=[],
            ignored_answers=[],
        )

    def test_multiline_value_is_indented_not_escaped(self):
        from lemely.io.prompts.correction_ai import build_marker_user_prompt

        q = self._question()
        prompt = build_marker_user_prompt(
            q,
            "student text",
            prior_values={"1a_i": "answer: v = 18\nworking: a = 150"},
        )
        # No literal backslash-n escape sequence from a `repr()` call.
        self.assertNotIn("\\n", prompt)
        # Every line of the value survives as a REAL line break, indented
        # under its own qid -- distinguishable from a new top-level entry.
        self.assertIn("  1a_i:\n    answer: v = 18\n    working: a = 150", prompt)


class EcfAppliedIsCodeSetOnlyTests(unittest.TestCase):
    """Post-I6-review Item A: ``PointVerdict.ecf_applied`` must be CODE-set
    only. I7's whole contract is that it records a re-mark the CODE
    performed (:func:`_maybe_apply_ecf_substitution`), never something the
    model claims about its own single-pass answer -- but the field sits on
    the wire response schema with no description telling the model that, so
    nothing previously stopped the model setting ``ecf_applied=True``
    unprompted, on a call where ``ecf_substitution`` was never even wired
    (every call before this fix, and every call today with the flag off).
    ``AICorrector.mark_question`` now forces every verdict's ``ecf_applied``
    to False unconditionally, regardless of what the model returned or
    whether ``equivalence_gate``/``ecf_substitution`` is on -- the ONLY
    place this field may become True is :func:`_maybe_apply_ecf_substitution`'s
    explicit merge, downstream of this call.
    """

    def _question(self):
        from lemely.core.loose_schemas import AnswerPoint, Question, QuestionType

        return Question.model_construct(
            id="2",
            marks=1,
            type=QuestionType.EXPLANATION,
            answer_points=[AnswerPoint(id="p1", point="gravity acts on it", marks=1)],
            parts=[],
            assessment_objectives=[],
            rejected_answers=[],
            ignored_answers=[],
        )

    def _response_asserting_ecf_applied(self) -> MagicMock:
        body = {
            "awarded_marks": 1,
            "confidence": 0.95,
            "matched_point_ids": ["p1"],
            "feedback": "fb",
            # The model claims ecf_applied=True on its own -- unprompted,
            # since no ecf/prior_values context was ever sent on this call.
            "point_verdicts": [
                {
                    "point_id": "p1",
                    "verdict": "awarded",
                    "evidence_span": "gravity",
                    "ecf_applied": True,
                }
            ],
        }
        return MagicMock(
            text=json.dumps(body),
            candidates=[MagicMock(finish_reason=MagicMock(__str__=lambda s: "STOP"))],
            usage_metadata=MagicMock(prompt_token_count=10, candidates_token_count=20),
        )

    def test_model_asserted_ecf_applied_is_forced_false(self) -> None:
        from lemely.io.correction_ai import AICorrector

        q = self._question()
        response = self._response_asserting_ecf_applied()
        with tempfile.TemporaryDirectory() as tmp:
            client = _client_with_seq(tmp, [response])
            corrector = AICorrector(client)
            # equivalence_gate=True so point_verdicts is even consulted;
            # ecf_substitution never enters mark_question at all -- it is a
            # correct_paper-level concept -- which is the point: this call
            # has no substitution context whatsoever, and the model's own
            # ecf_applied claim must still be rejected.
            mark = corrector.mark_question(q, "gravity acts on it", equivalence_gate=True)

        self.assertEqual(len(mark.point_verdicts), 1)
        self.assertEqual(mark.point_verdicts[0].verdict, "awarded")  # rest of the verdict intact
        self.assertFalse(mark.point_verdicts[0].ecf_applied)


class PointVerdictBuildTests(unittest.TestCase):
    """I6 (US-013): ``_build_ai_corrected`` dispatches to
    ``_build_ai_corrected_from_verdicts`` when ``equivalence_gate`` is on
    AND the marker returned at least one verdict; ``awarded_marks`` is
    always computed in Python from the verdicts, capped at ``q.marks``.
    """

    def _question(self, marks=2):
        from lemely.core.loose_schemas import AnswerPoint, MathMarkType, Question, QuestionType

        return Question.model_construct(
            id="2",
            marks=marks,
            type=QuestionType.EXPLANATION,
            answer_points=[
                AnswerPoint(id="p1", point="method step", marks=1, math_mark_type=MathMarkType.M),
                AnswerPoint(id="p2", point="final value", marks=1, math_mark_type=MathMarkType.A),
            ],
            parts=[],
            assessment_objectives=[],
            rejected_answers=[],
            ignored_answers=[],
        )

    def _verdict(self, point_id, verdict="awarded", span="", note="", ecf=False):
        from lemely.core.schemas import PointVerdict

        return PointVerdict(
            point_id=point_id, verdict=verdict, evidence_span=span, note=note, ecf_applied=ecf
        )

    def _mark(self, point_verdicts, confidence=0.95, feedback="fb"):
        from lemely.core.schemas import AIMarkResponse

        return AIMarkResponse(
            awarded_marks=0,  # deliberately wrong/stale -- must be IGNORED under the verdict path
            confidence=confidence,
            matched_point_ids=[],  # deliberately empty/stale -- must be IGNORED too
            feedback=feedback,
            point_verdicts=point_verdicts,
        )

    def test_flag_off_ignores_point_verdicts_and_uses_legacy_path(self):
        from lemely.io.correction_ai import _build_ai_corrected

        q = self._question()
        mark = self._mark(
            [self._verdict("p1", span="did the method"), self._verdict("p2", span="42")]
        )
        cq = _build_ai_corrected(q, "did the method, answer is 42", mark, equivalence_gate=False)
        # Legacy path trusts mark.awarded_marks (0) / matched_point_ids ([]),
        # not the verdicts -- proving dispatch really is flag-gated.
        self.assertEqual(cq.awarded_marks, 0)
        self.assertEqual(cq.point_verdicts, [])

    def test_flag_on_empty_verdicts_uses_legacy_path(self):
        from lemely.io.correction_ai import _build_ai_corrected

        q = self._question()
        mark = self._mark([])
        cq = _build_ai_corrected(q, "anything", mark, equivalence_gate=True)
        self.assertEqual(cq.awarded_marks, 0)  # legacy mark.awarded_marks, untouched
        self.assertEqual(cq.point_verdicts, [])

    def test_flag_on_with_verdicts_computes_awarded_marks_in_python(self):
        from lemely.io.correction_ai import _build_ai_corrected

        q = self._question()
        mark = self._mark(
            [
                self._verdict("p1", span="did the method"),
                self._verdict("p2", span="42"),
            ]
        )
        cq = _build_ai_corrected(
            q,
            "did the method, answer is 42",
            mark,
            student_working="did the method",
            equivalence_gate=True,
        )
        # sum(awarded verdicts' point marks) == awarded_marks (I6 acceptance 1)
        self.assertEqual(cq.awarded_marks, 2)
        self.assertEqual(set(cq.matched_point_ids), {"p1", "p2"})
        self.assertEqual(cq.point_verdicts, mark.point_verdicts)
        self.assertFalse(cq.needs_teacher_review)

    def test_shuffling_point_order_leaves_marks_unchanged(self):
        """I6 acceptance 1's metamorphic property."""
        from lemely.io.correction_ai import _build_ai_corrected

        q = self._question()
        forward = [
            self._verdict("p1", span="did the method"),
            self._verdict("p2", span="42"),
        ]
        shuffled = list(reversed(forward))
        mark_a = self._mark(forward)
        mark_b = self._mark(shuffled)
        cq_a = _build_ai_corrected(
            q,
            "did the method, answer is 42",
            mark_a,
            student_working="did the method",
            equivalence_gate=True,
        )
        cq_b = _build_ai_corrected(
            q,
            "did the method, answer is 42",
            mark_b,
            student_working="did the method",
            equivalence_gate=True,
        )
        self.assertEqual(cq_a.awarded_marks, cq_b.awarded_marks)
        self.assertEqual(set(cq_a.matched_point_ids), set(cq_b.matched_point_ids))

    def test_awarded_marks_capped_at_question_marks(self):
        from lemely.core.loose_schemas import AnswerPoint, Question, QuestionType
        from lemely.io.correction_ai import _build_ai_corrected

        # 1-mark question whose answer_points sum to more than the cap --
        # a marker-side inconsistency the cap must survive regardless.
        q = Question.model_construct(
            id="2",
            marks=1,
            type=QuestionType.EXPLANATION,
            answer_points=[
                AnswerPoint(id="p1", point="a", marks=1),
                AnswerPoint(id="p2", point="b", marks=1),
            ],
            parts=[],
            assessment_objectives=[],
            rejected_answers=[],
            ignored_answers=[],
        )
        mark = self._mark([self._verdict("p1", span="a text"), self._verdict("p2", span="b text")])
        cq = _build_ai_corrected(q, "a text and b text", mark, equivalence_gate=True)
        self.assertEqual(cq.awarded_marks, 1)  # capped, not 2

    def test_unverifiable_verdict_never_contributes_marks(self):
        from lemely.io.correction_ai import _build_ai_corrected

        q = self._question()
        mark = self._mark(
            [
                self._verdict("p1", verdict="unverifiable"),
                self._verdict("p2", span="42"),
            ]
        )
        cq = _build_ai_corrected(q, "answer is 42", mark, equivalence_gate=True)
        self.assertEqual(cq.awarded_marks, 1)
        self.assertEqual(cq.matched_point_ids, ["p2"])

    def test_awarded_point_with_no_matching_span_triggers_no_span_review(self):
        from lemely.io.correction_ai import POINT_EVIDENCE_TRIGGER_MARKER, _build_ai_corrected

        q = self._question()
        mark = self._mark(
            [
                self._verdict("p1", span="did the method"),
                self._verdict("p2", span="text that never appears anywhere"),
            ]
        )
        cq = _build_ai_corrected(
            q,
            "did the method, answer is 42",
            mark,
            student_working="did the method",
            equivalence_gate=True,
        )
        self.assertTrue(cq.needs_teacher_review)
        self.assertIn(POINT_EVIDENCE_TRIGGER_MARKER, cq.review_reason or "")
        # No new review-reason enum member: queued under the existing
        # generic path, never the coherence-mismatch trigger.
        self.assertNotIn("matched_point_ids", cq.review_reason or "")

    def test_awarded_m_point_span_outside_working_out_is_caught(self):
        """D11 working-vs-answer: an M-point's evidence must be found
        INSIDE working_out when working was supplied, not merely somewhere
        in the answer."""
        from lemely.io.correction_ai import POINT_EVIDENCE_TRIGGER_MARKER, _build_ai_corrected

        q = self._question()
        mark = self._mark(
            [
                # "42" only appears in the final answer line, never in the
                # working -- not evidence of METHOD even though it is
                # genuinely present verbatim in the transcript.
                self._verdict("p1", span="42"),
                self._verdict("p2", span="42"),
            ]
        )
        cq = _build_ai_corrected(
            q,
            "the answer is 42",
            mark,
            student_working="some unrelated working with no matching value in it",
            equivalence_gate=True,
        )
        self.assertTrue(cq.needs_teacher_review)
        self.assertIn(POINT_EVIDENCE_TRIGGER_MARKER, cq.review_reason or "")
        self.assertIn("working_out", cq.review_reason or "")

    def test_full_marks_with_no_method_span_gets_feedback_note(self):
        from lemely.io.correction_ai import _NO_METHOD_SPAN_NOTE, _build_ai_corrected

        mark = self._mark(
            [
                # p1 is the M-point but its verdict is withheld -- no
                # awarded M-point evidence at all, even though p2 (A) is
                # awarded and the total happens to hit full marks via some
                # other accounting path in a hypothetical scheme. Use a
                # 1-mark question so p2 alone reaches "full marks".
                self._verdict("p1", verdict="withheld"),
                self._verdict("p2", span="42"),
            ],
            feedback="A1 awarded for the correct value.",
        )
        q1 = self._question(marks=1)
        cq = _build_ai_corrected(q1, "answer is 42", mark, equivalence_gate=True)
        self.assertEqual(cq.awarded_marks, 1)
        self.assertEqual(cq.maximum_marks, 1)
        self.assertIn(_NO_METHOD_SPAN_NOTE, cq.feedback or "")

    def test_full_marks_with_method_span_present_has_no_note(self):
        from lemely.io.correction_ai import _NO_METHOD_SPAN_NOTE, _build_ai_corrected

        q = self._question(marks=2)
        mark = self._mark(
            [
                self._verdict("p1", span="did the method"),
                self._verdict("p2", span="42"),
            ],
            feedback="Full marks.",
        )
        cq = _build_ai_corrected(
            q,
            "did the method, answer is 42",
            mark,
            student_working="did the method",
            equivalence_gate=True,
        )
        self.assertEqual(cq.awarded_marks, 2)
        self.assertNotIn(_NO_METHOD_SPAN_NOTE, cq.feedback or "")

    def test_field_mutation_matrix_on_verdict_path_return(self):
        """Lesson from rev-us039: a field can be set correctly in the
        builder and still be completely unpinned by tests. Assert
        POSITIVELY on every field this path sets, not just awarded_marks."""
        from lemely.io.correction_ai import _build_ai_corrected

        q = self._question(marks=2)
        mark = self._mark(
            [
                self._verdict("p1", span="did the method", note="method shown"),
                self._verdict("p2", span="42"),
            ],
            feedback="Full marks awarded.",
            confidence=0.95,
        )
        cq = _build_ai_corrected(
            q,
            "did the method, answer is 42",
            mark,
            student_working="did the method",
            extraction_confidence=0.77,
            equivalence_gate=True,
        )
        self.assertEqual(cq.question_id, "2")
        self.assertEqual(cq.maximum_marks, 2)
        self.assertEqual(cq.awarded_marks, 2)
        self.assertEqual(cq.confidence_score, 0.95)
        self.assertEqual(cq.marker_source, "ai")
        self.assertEqual(cq.feedback, "Full marks awarded.")
        self.assertEqual(set(cq.matched_point_ids), {"p1", "p2"})
        self.assertEqual(cq.point_verdicts, mark.point_verdicts)
        self.assertEqual(cq.extraction_confidence, 0.77)
        self.assertFalse(cq.needs_teacher_review)
        self.assertIsNone(cq.review_reason)


class VerdictPathLevelsBasedFallbackTests(unittest.TestCase):
    """Post-I6-review Critical A: the verdict path resolves every
    ``PointVerdict.point_id`` ONLY against ``question.answer_points``
    (:func:`_awarded_from_verdicts`, :func:`_check_point_evidence`).
    ``LEVELS_BASED`` questions are REQUIRED to have an empty
    ``answer_points`` list, and ``INDICATIVE_CONTENT``/diagram/``graph_draw``
    questions marked holistically typically do too. With the old dispatch
    (``equivalence_gate and mark.point_verdicts``, no ``answer_points``
    guard), every ``point_verdicts`` entry for such a question was dangling
    by construction, :func:`_awarded_from_verdicts` summed to 0, and
    ``LEVELS_BASED``/``INDICATIVE_CONTENT`` are BOTH in
    :data:`_COHERENCE_EXEMPT_TYPES` -- so the dangling-id coherence check
    that would otherwise catch a zeroed score was switched off for exactly
    these two types, and the zero reached a student unflagged.

    Demonstrated here on CONSTRUCTED fixtures. The committed 289-scheme
    corpus contains zero questions of either type (11,024 leaf questions are
    entirely ``recall``/``mcq``, all det-parsed) -- this is a latent defect
    in code reachable once Gemini-parsed schemes populate these types, never
    a measured corpus regression, and the assertions below say so by
    checking flag-ON equals flag-OFF rather than claiming a corpus number
    moved.
    """

    def _levels_question(self, marks: int = 6) -> object:
        from lemely.core.loose_schemas import (
            DescriptorText,
            LevelDescriptor,
            Question,
            QuestionType,
        )

        return Question.model_construct(
            id="1",
            marks=marks,
            type=QuestionType.LEVELS_BASED,
            answer_points=[],
            parts=[],
            assessment_objectives=[],
            rejected_answers=[],
            ignored_answers=[],
            level_descriptors=[
                LevelDescriptor(
                    level=3,
                    mark_range=[5, 6],
                    descriptors=[DescriptorText(label="general", text="excellent, well-argued")],
                )
            ],
        )

    def _indicative_question(self, content_marks: int = 1, writing_marks: int = 1) -> object:
        from lemely.core.loose_schemas import IndicativeContentPoint, Question, QuestionType

        return Question.model_construct(
            id="2",
            marks=content_marks + writing_marks,
            type=QuestionType.INDICATIVE_CONTENT,
            answer_points=[],
            parts=[],
            assessment_objectives=[],
            rejected_answers=[],
            ignored_answers=[],
            indicative_content=[
                IndicativeContentPoint(id="ic1", point="uses evidence from the text")
            ],
            content_marks=content_marks,
            writing_marks=writing_marks,
        )

    def _graph_draw_question(self, marks: int = 2) -> object:
        """NIT 6 (post-review): the class docstring names ``graph_draw`` as
        one of the affected types, but until now only
        ``levels_based``/``indicative_content`` were exercised -- exactly
        the coverage gap the reviewer noted would have surfaced MUST-FIX 1
        (a NON-empty, partial-coverage case) had it been present at
        authoring time. This fixture has EMPTY ``answer_points`` (marked
        holistically via ``plot_requirements`` instead), so it belongs with
        the other EMPTY-``answer_points`` cases here; MUST-FIX 1's own
        ``VerdictPathPartialCoverageTests`` covers the NON-empty,
        partial-coverage ``diagram`` shape separately."""
        from lemely.core.loose_schemas import PlotRequirement, Question, QuestionType

        return Question.model_construct(
            id="3",
            marks=marks,
            type=QuestionType.GRAPH_DRAW,
            answer_points=[],
            parts=[],
            assessment_objectives=[],
            rejected_answers=[],
            ignored_answers=[],
            plot_requirements=[PlotRequirement(x_value=1.0, y_value=2.0)],
        )

    def _mark(self, awarded: int, matched: list[str], point_verdicts: list) -> object:
        from lemely.core.schemas import AIMarkResponse

        return AIMarkResponse(
            awarded_marks=awarded,
            confidence=0.95,
            matched_point_ids=matched,
            feedback="fb",
            point_verdicts=point_verdicts,
        )

    def test_graph_draw_flag_on_equals_flag_off(self) -> None:
        """Unlike LEVELS_BASED/INDICATIVE_CONTENT, GRAPH_DRAW is NOT in
        ``_COHERENCE_EXEMPT_TYPES`` -- so a claimed ``matched_point_ids``
        entry that cannot resolve against its (empty) ``answer_points`` is
        legitimately DANGLING and ``_check_coherence`` correctly flags it,
        on BOTH the flag-off legacy path and the flag-on path (which also
        falls back to legacy here, since ``question.answer_points`` is
        empty). The point of this test is that BOTH paths flag it
        IDENTICALLY -- not that neither does."""
        from lemely.core.schemas import PointVerdict
        from lemely.io.correction_ai import _build_ai_corrected

        q = self._graph_draw_question()
        student_answer = "plots (1, 2) correctly with a smooth curve"
        mark = self._mark(
            2,
            ["pt1"],
            point_verdicts=[
                PointVerdict(point_id="pt1", verdict="awarded", evidence_span=student_answer)
            ],
        )

        cq_off = _build_ai_corrected(q, student_answer, mark, equivalence_gate=False)
        cq_on = _build_ai_corrected(q, student_answer, mark, equivalence_gate=True)

        self.assertEqual(cq_on.awarded_marks, cq_off.awarded_marks)
        self.assertEqual(cq_on.needs_teacher_review, cq_off.needs_teacher_review)
        self.assertTrue(cq_on.needs_teacher_review)  # "pt1" is a genuinely dangling id here
        self.assertEqual(cq_on.review_reason, cq_off.review_reason)

    def test_levels_based_flag_on_equals_flag_off(self) -> None:
        from lemely.core.schemas import PointVerdict
        from lemely.io.correction_ai import _build_ai_corrected

        q = self._levels_question()
        student_answer = "a genuinely excellent, well-argued extended response"
        mark = self._mark(
            6,
            ["lvl1"],
            point_verdicts=[
                PointVerdict(point_id="lvl1", verdict="awarded", evidence_span=student_answer)
            ],
        )

        cq_off = _build_ai_corrected(q, student_answer, mark, equivalence_gate=False)
        cq_on = _build_ai_corrected(q, student_answer, mark, equivalence_gate=True)

        self.assertEqual(cq_on.awarded_marks, cq_off.awarded_marks)
        self.assertEqual(cq_on.awarded_marks, 6)  # not silently zeroed by the verdict path
        self.assertEqual(cq_on.matched_point_ids, cq_off.matched_point_ids)
        self.assertEqual(cq_on.needs_teacher_review, cq_off.needs_teacher_review)
        self.assertFalse(cq_on.needs_teacher_review)  # confirms it was never flagged either
        self.assertEqual(cq_on.review_reason, cq_off.review_reason)

    def test_indicative_content_flag_on_equals_flag_off(self) -> None:
        from lemely.core.schemas import PointVerdict
        from lemely.io.correction_ai import _build_ai_corrected

        q = self._indicative_question()
        student_answer = "the response uses evidence from the text effectively"
        mark = self._mark(
            2,
            ["ic1"],
            point_verdicts=[
                PointVerdict(point_id="ic1", verdict="awarded", evidence_span=student_answer)
            ],
        )

        cq_off = _build_ai_corrected(q, student_answer, mark, equivalence_gate=False)
        cq_on = _build_ai_corrected(q, student_answer, mark, equivalence_gate=True)

        self.assertEqual(cq_on.awarded_marks, cq_off.awarded_marks)
        self.assertEqual(cq_on.awarded_marks, 2)
        self.assertEqual(cq_on.needs_teacher_review, cq_off.needs_teacher_review)
        self.assertFalse(cq_on.needs_teacher_review)
        self.assertEqual(cq_on.review_reason, cq_off.review_reason)


class VerdictPathPartialCoverageTests(unittest.TestCase):
    """Post-``2deea2c5``-review Critical fix: the verdict-path dispatch
    guard added by that commit only handles EMPTY ``answer_points``
    (``question.answer_points`` falsy). It does not handle the ADJACENT
    case -- ``answer_points`` present but summing to LESS than
    ``question.marks`` (e.g. a ``DIAGRAM`` mixing an ``AnswerPoint`` with a
    ``DrawingCriterion`` this path cannot resolve ids against) -- which
    still dispatches to the verdicts path and silently under-caps.

    Worse: that same commit's narrower (and CORRECT, per its own Critical A
    fix) I6 prompt wording -- "one entry per AnswerPoint id" instead of the
    old, wrong "AnswerPoint / LevelDescriptor / DrawingCriteria id" -- also
    removed an ACCIDENTAL safety net for exactly this shape: under the OLD
    wording the model would volunteer a verdict for the DrawingCriterion id
    too, which ``_check_coherence`` would then flag as an unknown
    ``matched_point_ids`` entry. The new, correct wording no longer elicits
    that dangling id, so the flag-off path (unaffected, structural) still
    catches the under-coverage via its own coherence check, but the
    flag-on (verdict) path silently lost the only signal it had --
    ``_build_ai_corrected_from_verdicts``'s new coverage-mismatch check
    (reason 2 in its docstring) restores it, deliberately, by comparing the
    DERIVED total against the marker's OWN claim rather than re-deriving
    which question types can have incomplete ``answer_points``.

    Demonstrated on a constructed ``DIAGRAM`` fixture. The committed
    289-scheme corpus has ZERO exposure today (11,024 leaves, all
    ``recall``/``mcq``, none carrying ``drawing_criteria``) -- an
    input-data limit, not a reason this can wait, per Critical A's own
    precedent that a latent trap fires first when money is spent.
    """

    def _question(self) -> object:
        from lemely.core.loose_schemas import AnswerPoint, Question, QuestionType

        return Question.model_construct(
            id="1",
            marks=4,
            type=QuestionType.DIAGRAM,
            answer_points=[AnswerPoint(id="p1", point="clearly labelled axis", marks=2)],
            parts=[],
            assessment_objectives=[],
            rejected_answers=[],
            ignored_answers=[],
        )

    def test_partial_coverage_is_flagged_on_both_paths(self) -> None:
        """Before the fix: flag OFF flags it (coherence: the model's own
        claimed 4 marks is outside the [2, 2] range its 2-mark AnswerPoint
        implies); flag ON silently drops to 2/4 with no flag at all. After
        the fix, both paths flag the question for review -- the derived
        mark itself is NOT required to match between the two paths (the
        verdict path deliberately computes from the DERIVED total, never
        the marker's claim, which is I6's whole point), but the review
        SIGNAL that a human must look at this question is restored on both.
        """
        from lemely.core.schemas import PointVerdict
        from lemely.io.correction_ai import _build_ai_corrected

        q = self._question()
        student_answer = "diagram with a clearly labelled axis and a correctly drawn line"
        mark = self._mark(
            4,  # the marker's OWN claim: full marks
            ["p1"],
            point_verdicts=[
                PointVerdict(point_id="p1", verdict="awarded", evidence_span=student_answer)
            ],
        )

        cq_off = _build_ai_corrected(q, student_answer, mark, equivalence_gate=False)
        cq_on = _build_ai_corrected(q, student_answer, mark, equivalence_gate=True)

        self.assertTrue(cq_off.needs_teacher_review)
        self.assertTrue(cq_on.needs_teacher_review)  # the fix: this used to be False
        self.assertIsNotNone(cq_on.review_reason)
        self.assertIn("2", cq_on.review_reason or "")  # names the derived total
        self.assertIn("4", cq_on.review_reason or "")  # names the question maximum

    def _mark(self, awarded: int, matched: list[str], point_verdicts: list) -> object:
        from lemely.core.schemas import AIMarkResponse

        return AIMarkResponse(
            awarded_marks=awarded,
            confidence=0.95,
            matched_point_ids=matched,
            feedback="fb",
            point_verdicts=point_verdicts,
        )


class CoherenceGateTests(unittest.TestCase):
    """M1.5 (#40): awarded_marks must reconcile with matched_point_ids,
    and every matched_point_id must resolve in the mark scheme — a fourth
    independent review reason, computed before (and never gated by) the
    confidence check. See BUILD/DECISIONS.md for the empty/absent
    matched_point_ids and is_alternative/is_optional reconciliation rules.
    """

    def _make_question(self, answer_points=None):
        from lemely.core.loose_schemas import Question, QuestionType

        return Question.model_construct(
            id="2",
            marks=2,
            type=QuestionType.EXPLANATION,
            answer_points=answer_points if answer_points is not None else [],
            parts=[],
            assessment_objectives=[],
            rejected_answers=[],
            ignored_answers=[],
        )

    def _points(self):
        from lemely.core.loose_schemas import AnswerPoint

        return [
            AnswerPoint(id="p1", point="method", marks=1),
            AnswerPoint(id="p2", point="final answer", marks=1),
        ]

    def _make_mark(self, awarded_marks: int, matched: list[str], confidence: float = 1.0):
        from lemely.core.schemas import AIMarkResponse

        return AIMarkResponse(
            awarded_marks=awarded_marks,
            confidence=confidence,
            matched_point_ids=matched,
            feedback="test",
        )

    def test_reconciliation_mismatch_flags_despite_full_confidence(self):
        from lemely.io.correction_ai import _build_ai_corrected

        # matched_point_ids implies 1 mark (p1 only); awarded_marks claims 2.
        cq = _build_ai_corrected(
            self._make_question(self._points()),
            "answer",
            self._make_mark(2, ["p1"], confidence=1.0),
        )
        self.assertTrue(cq.needs_teacher_review)
        self.assertIn("matched_point_ids", cq.review_reason or "")

    def test_dangling_point_id_flags_review(self):
        from lemely.io.correction_ai import _build_ai_corrected

        cq = _build_ai_corrected(
            self._make_question(self._points()),
            "answer",
            self._make_mark(1, ["p_nonexistent"], confidence=1.0),
        )
        self.assertTrue(cq.needs_teacher_review)
        self.assertIn("p_nonexistent", cq.review_reason or "")

    def test_empty_matched_point_ids_reconciliation(self):
        """Documents the chosen semantics (BUILD/DECISIONS.md): marks awarded
        with no matched_point_ids to justify them is incoherent; zero marks
        with an empty list is coherent (nothing was matched, nothing was
        awarded)."""
        from lemely.io.correction_ai import _build_ai_corrected

        incoherent = _build_ai_corrected(
            self._make_question(self._points()),
            "answer",
            self._make_mark(1, [], confidence=1.0),
        )
        self.assertTrue(incoherent.needs_teacher_review)
        self.assertIn("matched_point_ids", incoherent.review_reason or "")

        coherent = _build_ai_corrected(
            self._make_question(self._points()),
            "no attempt",
            self._make_mark(0, [], confidence=1.0),
        )
        self.assertFalse(coherent.needs_teacher_review)

    def test_high_confidence_incoherent_still_fires(self):
        """Binding constraint 5: the trigger fires independently of stated
        confidence, at or above REVIEW_CONFIDENCE_THRESHOLD."""
        from lemely.core.schemas import REVIEW_CONFIDENCE_THRESHOLD
        from lemely.io.correction_ai import _build_ai_corrected

        cq = _build_ai_corrected(
            self._make_question(self._points()),
            "answer",
            self._make_mark(2, ["p1"], confidence=REVIEW_CONFIDENCE_THRESHOLD),
        )
        self.assertTrue(cq.needs_teacher_review)

    def test_exempt_type_with_no_answer_points_is_untouched(self):
        """A LEVELS_BASED/INDICATIVE_CONTENT/MCQ question with no discrete
        answer_points has nothing to reconcile matched_point_ids against by
        design, so the coherence check must not fire regardless of
        awarded_marks. Scoped to the exempt TYPES, not to empty-ness of
        answer_points in general — see MUST-FIX 2 (#40 repair pass)."""
        from lemely.core.loose_schemas import Question, QuestionType
        from lemely.io.correction_ai import _build_ai_corrected

        exempt_question = Question.model_construct(
            id="2",
            marks=2,
            type=QuestionType.LEVELS_BASED,
            answer_points=[],
            parts=[],
            assessment_objectives=[],
            rejected_answers=[],
            ignored_answers=[],
        )
        cq = _build_ai_corrected(
            exempt_question,
            "answer",
            self._make_mark(1, [], confidence=1.0),
        )
        self.assertFalse(cq.needs_teacher_review)

    def test_non_exempt_type_with_empty_answer_points_and_award_flags(self):
        """A non-exempt type (e.g. EXPLANATION) with empty answer_points is a
        data gap, not an intentional shape — an award with nothing to justify
        it is still incoherent, same rule as the non-empty-points case
        (MUST-FIX 2, #40 repair pass). Previously this returned None before
        ever reaching the dangling/award checks, silently accepting a
        fabricated award."""
        from lemely.io.correction_ai import _build_ai_corrected

        cq = _build_ai_corrected(
            self._make_question(answer_points=[]),
            "answer",
            self._make_mark(1, [], confidence=1.0),
        )
        self.assertTrue(cq.needs_teacher_review)
        self.assertIn("matched_point_ids", cq.review_reason or "")

    def test_empty_answer_points_with_nonempty_matched_point_ids_flags(self):
        """Empty answer_points + non-empty matched_point_ids: every claimed id
        is dangling by definition (there is nothing to resolve it against).
        This was the acceptance-bullet-2 gap the review found: the old
        ``if not question.answer_points: return None`` short-circuit ran
        BEFORE the dangling-id check, so a wholly fabricated
        matched_point_ids list on an empty-answer_points question was
        silently accepted (MUST-FIX 2, #40 repair pass)."""
        from lemely.io.correction_ai import _build_ai_corrected

        cq = _build_ai_corrected(
            self._make_question(answer_points=[]),
            "answer",
            self._make_mark(1, ["p_fabricated"], confidence=1.0),
        )
        self.assertTrue(cq.needs_teacher_review)
        self.assertIn("matched_point_ids", cq.review_reason or "")
        self.assertIn("p_fabricated", cq.review_reason or "")

    def test_any_3_from_5_optional_award_is_coherent(self):
        """MUST-FIX 1: a legitimate 'any 3 from 5' award over an is_optional
        pool must NOT be capped by a single global max(). The awarded marks
        must fall within [implied_min, implied_max] = [1, 5] for 3 matched
        1-mark optional points out of a 5-point pool; 3 is within range."""
        from lemely.core.loose_schemas import AnswerPoint, Question, QuestionType
        from lemely.io.correction_ai import _build_ai_corrected

        pool = [
            AnswerPoint(id=f"p{i}", point=f"item {i}", marks=1, is_optional=True)
            for i in range(1, 6)
        ]
        question = Question.model_construct(
            id="2",
            marks=5,
            type=QuestionType.LIST,
            answer_points=pool,
            parts=[],
            assessment_objectives=[],
            rejected_answers=[],
            ignored_answers=[],
        )
        cq = _build_ai_corrected(
            question,
            "answer",
            self._make_mark(3, ["p1", "p2", "p3"], confidence=1.0),
        )
        self.assertFalse(cq.needs_teacher_review)
        self.assertEqual(cq.awarded_marks, 3)

    def test_award_outside_the_implied_range_still_flags(self):
        """MUST-FIX 1: the range replaces the point estimate, it does not
        remove the gate — an award outside [implied_min, implied_max] is
        still incoherent. 3 optional 1-mark points matched, implied range is
        [1, 3]; awarding 5 is outside it."""
        from lemely.core.loose_schemas import AnswerPoint, Question, QuestionType
        from lemely.io.correction_ai import _build_ai_corrected

        pool = [
            AnswerPoint(id=f"p{i}", point=f"item {i}", marks=1, is_optional=True)
            for i in range(1, 4)
        ]
        question = Question.model_construct(
            id="2",
            marks=5,
            type=QuestionType.LIST,
            answer_points=pool,
            parts=[],
            assessment_objectives=[],
            rejected_answers=[],
            ignored_answers=[],
        )
        cq = _build_ai_corrected(
            question,
            "answer",
            self._make_mark(5, ["p1", "p2", "p3"], confidence=1.0),
        )
        self.assertTrue(cq.needs_teacher_review)
        self.assertIn("matched_point_ids", cq.review_reason or "")


class ThinkingRetryTests(unittest.TestCase):
    """Thinking retry fires before Pro escalation for borderline confidence."""

    def test_thinking_retry_before_pro_escalation(self):
        """When Flash confidence < threshold and correction_borderline budget > 0,
        a second Flash call (with thinking) must precede any Pro escalation."""
        import json
        import tempfile
        from pathlib import Path
        from unittest.mock import MagicMock

        from lemely.core.loose_schemas import MarkScheme
        from lemely.core.schemas import ExtractedAnswer, ExtractedAnswers
        from lemely.io.correction_ai import correct_paper
        from lemely.runtime.config import PathsSettings, load_settings

        scheme = MarkScheme.model_validate(
            {
                "metadata": {
                    "subject": "Physics",
                    "subject_code": "0625",
                    "paper_number": 4,
                    "paper_variant": 2,
                    "session_month": "May/June",
                    "session_year": 2020,
                    "paper_type": "theory_extended",
                    "maximum_mark": 2,
                    "scheme_format": "point_based",
                },
                "questions": [
                    {
                        "id": "1",
                        "marks": 2,
                        "type": "explanation",
                        "answer_points": [
                            {"id": "p1", "point": "gravity", "marks": 1},
                            {"id": "p2", "point": "speed", "marks": 1},
                        ],
                    }
                ],
            }
        )
        extracted = ExtractedAnswers(
            paper_id="test",
            source_scan="s.pdf",
            answers=[ExtractedAnswer(question_id="1", answer="gravity", confidence=0.9)],
        )

        low_body = json.dumps(
            {
                "awarded_marks": 1,
                "confidence": 0.70,
                "matched_point_ids": [],
                "feedback": "borderline",
            }
        )
        high_body = json.dumps(
            {"awarded_marks": 1, "confidence": 0.88, "matched_point_ids": [], "feedback": "clear"}
        )

        def _resp(body: str) -> MagicMock:
            return MagicMock(
                text=body,
                candidates=[MagicMock(finish_reason=MagicMock(__str__=lambda s: "STOP"))],
                usage_metadata=MagicMock(prompt_token_count=10, candidates_token_count=20),
            )

        with tempfile.TemporaryDirectory() as tmp:
            with _IsolatedEnv():
                s = load_settings(toml_path=None, cwd=Path(tmp))
            s = s.model_copy(
                update={
                    "paths": PathsSettings(
                        cache_dir=Path(tmp) / ".cache",
                        output_dir=Path(tmp) / "outputs",
                    ),
                    "gemini": s.gemini.model_copy(
                        update={
                            "escalation_model": "gemini-2.5-pro",
                            "escalation_confidence_threshold": 0.80,
                            "thinking_budget_for": {"correction_borderline": 2000},
                        }
                    ),
                }
            )
            mock_genai = MagicMock()
            # Flash low-conf, then Flash+thinking high-conf (no Pro needed)
            mock_genai.models.generate_content.side_effect = [_resp(low_body), _resp(high_body)]
            mock_genai.files.upload.return_value = MagicMock()
            from lemely.io.gemini import GeminiClient

            client = GeminiClient(s, _genai_client=mock_genai)

        correct_paper(scheme, extracted, gemini_client=client)

        calls = mock_genai.models.generate_content.call_args_list
        # Must have exactly 2 calls: Flash normal + Flash thinking (Pro NOT needed)
        self.assertEqual(
            len(calls), 2, f"Expected 2 API calls (Flash + thinking), got {len(calls)}"
        )
        # Second call must carry a ThinkingConfig (i.e. the thinking budget was applied).
        second_call_repr = str(calls[1])
        self.assertIn("ThinkingConfig", second_call_repr)


def _level(v: object) -> str | None:
    """Normalise a ``types.ThinkingLevel`` (or a plain string) to lowercase.

    Duplicated from ``tests/test_gemini_client.py`` (small and pure — the SDK
    coerces the ``thinking_level`` kwarg into a ``types.ThinkingLevel`` enum
    member, so a bare string comparison against the lowercase config value
    always fails even though the level round-tripped correctly).
    """
    if v is None:
        return None
    value = getattr(v, "value", v)
    return str(value).lower()


class F1EscalationReachabilityTests(unittest.TestCase):
    """F1 acceptance (4b): the Step-2 escalation gate must stay reachable when
    correction_model == escalation_model (the shipped F1 default, both
    "gemini-3.8-flash"), where a bare model-name comparison would make it
    permanently dead.
    """

    def test_borderline_mark_produces_three_calls_all_on_3x_correction_model(self):
        from lemely.io.correction_ai import correct_paper

        scheme = MarkScheme.model_validate(
            {
                "metadata": {
                    "subject": "Physics",
                    "subject_code": "0625",
                    "paper_number": 4,
                    "paper_variant": 2,
                    "session_month": "May/June",
                    "session_year": 2020,
                    "paper_type": "theory_extended",
                    "maximum_mark": 2,
                    "scheme_format": "point_based",
                },
                "questions": [
                    {
                        "id": "1",
                        "marks": 2,
                        "type": "explanation",
                        "answer_points": [
                            {"id": "p1", "point": "gravity", "marks": 1},
                            {"id": "p2", "point": "speed", "marks": 1},
                        ],
                    }
                ],
            }
        )
        extracted = ExtractedAnswers(
            paper_id="test",
            source_scan="s.pdf",
            answers=[ExtractedAnswer(question_id="1", answer="gravity", confidence=0.9)],
        )

        def _resp(confidence: float, feedback: str) -> MagicMock:
            body = json.dumps(
                {
                    "awarded_marks": 1,
                    "confidence": confidence,
                    "matched_point_ids": [],
                    "feedback": feedback,
                }
            )
            return MagicMock(
                text=body,
                candidates=[MagicMock(finish_reason=MagicMock(__str__=lambda s: "STOP"))],
                usage_metadata=MagicMock(prompt_token_count=10, candidates_token_count=20),
            )

        with tempfile.TemporaryDirectory() as tmp:
            with _IsolatedEnv():
                # F1 defaults, untouched: correction_model == escalation_model
                # == "gemini-3.8-flash"; thinking_level_for as shipped.
                s = load_settings(toml_path=None, cwd=Path(tmp))
            s = s.model_copy(
                update={
                    "paths": PathsSettings(
                        cache_dir=Path(tmp) / ".cache",
                        output_dir=Path(tmp) / "outputs",
                    )
                }
            )
            self.assertEqual(s.gemini.model_for("correction"), "gemini-3.8-flash")
            self.assertEqual(s.gemini.model_for("escalation"), "gemini-3.8-flash")

            mock_genai = MagicMock()
            # Call 1 (correction, low): confidence 0.5, below the 0.80 threshold.
            # Call 2 (correction_borderline, high): still 0.6, below threshold.
            # Call 3 (escalation, high): 0.95, resolves.
            mock_genai.models.generate_content.side_effect = [
                _resp(0.5, "low"),
                _resp(0.6, "high"),
                _resp(0.95, "high-escalation"),
            ]
            mock_genai.files.upload.return_value = MagicMock()
            client = GeminiClient(s, _genai_client=mock_genai)

            with _capturing(EventType.GEMINI_CALL_START) as captured:
                correct_paper(scheme, extracted, gemini_client=client)

            calls = mock_genai.models.generate_content.call_args_list
            self.assertEqual(len(calls), 3, f"expected 3 calls, got {len(calls)}")

            starts = captured[EventType.GEMINI_CALL_START]
            self.assertEqual(len(starts), 3)
            self.assertEqual(
                [e["task"] for e in starts], ["correction", "correction_borderline", "escalation"]
            )
            self.assertTrue(all(e["model"] == "gemini-3.8-flash" for e in starts))
            self.assertNotIn("gemini-2.5-flash", [e["model"] for e in starts])

            # F1 review FIX 4: assert the actual thinking_level sent on each
            # call, not just tags/models — an implementation that ignored
            # thinking_level_for entirely and always sent "low" would still
            # pass every assertion above.
            levels = [_level(c.kwargs["config"].thinking_config.thinking_level) for c in calls]
            self.assertEqual(levels, ["low", "high", "high"])

    def test_no_escalation_when_all_three_tags_resolve_to_the_same_thinking(self):
        """F1 review FIX 4 (negative case): with correction ==
        correction_borderline == escalation == "high" on the same 3.x model,
        neither gate has anything to gain by firing — exactly ONE call is
        made, confirming the gates compare actual resolved thinking rather
        than just "is a retry configured at all"."""
        from lemely.io.correction_ai import correct_paper

        scheme = MarkScheme.model_validate(
            {
                "metadata": {
                    "subject": "Physics",
                    "subject_code": "0625",
                    "paper_number": 4,
                    "paper_variant": 2,
                    "session_month": "May/June",
                    "session_year": 2020,
                    "paper_type": "theory_extended",
                    "maximum_mark": 2,
                    "scheme_format": "point_based",
                },
                "questions": [
                    {
                        "id": "1",
                        "marks": 2,
                        "type": "explanation",
                        "answer_points": [
                            {"id": "p1", "point": "gravity", "marks": 1},
                            {"id": "p2", "point": "speed", "marks": 1},
                        ],
                    }
                ],
            }
        )
        extracted = ExtractedAnswers(
            paper_id="test",
            source_scan="s.pdf",
            answers=[ExtractedAnswer(question_id="1", answer="gravity", confidence=0.9)],
        )

        def _resp(confidence: float) -> MagicMock:
            body = json.dumps(
                {
                    "awarded_marks": 1,
                    "confidence": confidence,
                    "matched_point_ids": [],
                    "feedback": "low",
                }
            )
            return MagicMock(
                text=body,
                candidates=[MagicMock(finish_reason=MagicMock(__str__=lambda s: "STOP"))],
                usage_metadata=MagicMock(prompt_token_count=10, candidates_token_count=20),
            )

        with tempfile.TemporaryDirectory() as tmp:
            with _IsolatedEnv():
                s = load_settings(toml_path=None, cwd=Path(tmp))
            s = s.model_copy(
                update={
                    "paths": PathsSettings(
                        cache_dir=Path(tmp) / ".cache",
                        output_dir=Path(tmp) / "outputs",
                    ),
                    "gemini": s.gemini.model_copy(
                        update={
                            "thinking_level_for": {
                                "correction": "high",
                                "correction_borderline": "high",
                                "escalation": "high",
                            }
                        }
                    ),
                }
            )
            self.assertEqual(s.gemini.model_for("correction"), "gemini-3.8-flash")
            self.assertEqual(s.gemini.model_for("escalation"), "gemini-3.8-flash")

            mock_genai = MagicMock()
            # Confidence stays low forever -- if either gate fired anyway,
            # there would be more than one call.
            mock_genai.models.generate_content.side_effect = [_resp(0.1)] * 3
            mock_genai.files.upload.return_value = MagicMock()
            client = GeminiClient(s, _genai_client=mock_genai)

            correct_paper(scheme, extracted, gemini_client=client)

            self.assertEqual(mock_genai.models.generate_content.call_count, 1)


@contextlib.contextmanager
def _capturing(*event_types: EventType) -> Iterator[dict[EventType, list[dict[str, Any]]]]:
    """Record every payload published on ``event_types`` for the duration of the block.

    Unsubscribes in ``finally``: ``bus`` is a process-wide singleton, so a spy
    left attached keeps firing — and accumulating another test's events — for
    the rest of the session.
    """
    captured: dict[EventType, list[dict[str, Any]]] = {t: [] for t in event_types}

    def _spy_for(event_type: EventType):
        def _spy(**payload: Any) -> None:
            captured[event_type].append(payload)

        return _spy

    spies = [(t, _spy_for(t)) for t in event_types]
    for event_type, spy in spies:
        bus.subscribe(event_type, spy)
    try:
        yield captured
    finally:
        for event_type, spy in spies:
            bus.unsubscribe(event_type, spy)


def _five_leaf_mark_scheme() -> MarkScheme:
    """One MCQ, a two-part container, and two standalone theory questions.

    Six nodes but only *five* leaves: the zero-mark container "2" is structure,
    not work, so ``correct_paper`` never marks it and it must not appear in the
    counter's denominator. The parts also give the run a question whose position
    in the work list ("2(b)", third) differs from its position among top-level
    questions, which is exactly the kind of drift the index is meant to survive.
    """
    return MarkScheme.model_validate(
        {
            "metadata": {
                "subject": "Physics",
                "subject_code": "0625",
                "paper_number": 4,
                "paper_variant": 2,
                "session_month": "May/June",
                "session_year": 2020,
                "paper_type": "theory_extended",
                "maximum_mark": 9,
                "scheme_format": "mixed",
            },
            "questions": [
                {"id": "1", "marks": 1, "type": "mcq", "mcq_answer": "A"},
                {
                    "id": "2",
                    "marks": 0,
                    "type": "explanation",
                    "parts": [
                        {
                            "id": "2(a)",
                            "marks": 2,
                            "type": "explanation",
                            "parent_id": "2",
                            "answer_points": [
                                {"id": "p1", "point": "states the rule", "marks": 1},
                                {"id": "p2", "point": "applies the rule", "marks": 1},
                            ],
                        },
                        {
                            "id": "2(b)",
                            "marks": 2,
                            "type": "explanation",
                            "parent_id": "2",
                            "answer_points": [
                                {"id": "p1", "point": "uses the result of (a)", "marks": 2},
                            ],
                        },
                    ],
                },
                {
                    "id": "3",
                    "marks": 2,
                    "type": "explanation",
                    "question_command": "explain why",
                    "answer_points": [
                        {"id": "p1", "point": "gravity acts on it", "marks": 1},
                        {"id": "p2", "point": "no air resistance", "marks": 1},
                    ],
                },
                {
                    "id": "4",
                    "marks": 2,
                    "type": "explanation",
                    "question_command": "explain why",
                    "answer_points": [
                        {"id": "p1", "point": "energy is conserved", "marks": 2},
                    ],
                },
            ],
        }
    )


class MarkingProgressCounterTests(unittest.TestCase):
    """MARKING_PROGRESS carries a per-question counter the UI can render honestly.

    ``index`` is the 1-based position of the question inside the work list
    (``leaves``) and ``total`` is that list's length, so "Question 4 of 5" names
    the question actually being marked. The contrast that matters is with a
    counter of *frames emitted* — see the failure test below for why the two
    are not the same number.
    """

    # Marking order: leaves, depth-first, as ``all_questions_flat`` yields them.
    LEAF_IDS = ("1", "2(a)", "2(b)", "3", "4")

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.ms = _five_leaf_mark_scheme()

    def _extracted(self) -> ExtractedAnswers:
        return ExtractedAnswers(
            paper_id="test",
            source_scan="scan.png",
            answers=[
                ExtractedAnswer(question_id="1", answer="A", confidence=0.99),
                ExtractedAnswer(question_id="2(a)", answer="states and applies it", confidence=0.9),
                ExtractedAnswer(question_id="2(b)", answer="uses the 20 from (a)", confidence=0.9),
                ExtractedAnswer(question_id="3", answer="because gravity", confidence=0.9),
                ExtractedAnswer(question_id="4", answer="energy is conserved", confidence=0.9),
            ],
        )

    def test_indices_run_1_to_n_against_a_constant_total(self) -> None:
        # Four responses: the MCQ leaf is marked deterministically and never
        # reaches Gemini, so only the four non-MCQ leaves consume one each.
        client = _client_with_seq(self.tmp, [_mock_marker_response(2, ["p1"]) for _ in range(4)])

        with _capturing(EventType.MARKING_PROGRESS) as captured:
            correct_paper(self.ms, self._extracted(), gemini_client=client)

        frames = captured[EventType.MARKING_PROGRESS]
        self.assertEqual([f["question_id"] for f in frames], list(self.LEAF_IDS))
        self.assertEqual([f["index"] for f in frames], [1, 2, 3, 4, 5])
        # One denominator for the whole run, and it counts leaves: the zero-mark
        # container "2" is never marked, so a total of 6 would promise the UI a
        # question that is never coming.
        self.assertEqual({f["total"] for f in frames}, {5})

    def test_a_failed_question_does_not_shift_the_indices_after_it(self) -> None:
        """The regression this counter exists to prevent.

        Question "3" is the *fourth* leaf and its AI call raises, so it publishes
        ERROR and no MARKING_PROGRESS at all. Question "4" — the fifth leaf, and
        the next frame the UI receives — must still report index 5. A counter
        incremented once per emitted frame would report 4 here: the UI would
        label question 4's result with question 3's number, and a paper where
        every question was handled would finish reading "4 of 5".
        """
        # Non-MCQ call order is 2(a), 2(b), 3, 4 — so the third response is
        # question "3". The message deliberately avoids the substrings
        # ``GeminiClient._call_once`` classifies as transient ("503", "rate
        # limit", "connection", ...); a transient-looking error would be retried
        # and would eat the response queued for question "4".
        client = _client_with_seq(
            self.tmp,
            [
                _mock_marker_response(2, ["p1"]),
                _mock_marker_response(2, ["p1"]),
                RuntimeError("marker stub refuses this question"),
                _mock_marker_response(2, ["p1"]),
            ],
        )

        with _capturing(EventType.MARKING_PROGRESS, EventType.ERROR) as captured:
            result = correct_paper(self.ms, self._extracted(), gemini_client=client)

        frames = captured[EventType.MARKING_PROGRESS]
        self.assertEqual([f["question_id"] for f in frames], ["1", "2(a)", "2(b)", "4"])
        # Position 4 is simply absent — the gap is the honest signal that a
        # question was skipped. It is not closed up by renumbering "4" to 4.
        self.assertEqual([f["index"] for f in frames], [1, 2, 3, 5])
        # The denominator does not shrink either: five questions were attempted,
        # and hiding the failed one would overstate how much of the paper the
        # marker actually got through.
        self.assertEqual({f["total"] for f in frames}, {5})

        # The failure is reported, and reported as an error rather than dressed
        # up as progress. ERROR deliberately carries no index/total (see the
        # comment on the except branch in correction_ai.correct_paper).
        errors = captured[EventType.ERROR]
        self.assertEqual(len(errors), 1)
        self.assertIn("q=3", str(errors[0]["message"]))
        self.assertNotIn("index", errors[0])
        self.assertNotIn("total", errors[0])

        # The result still covers every leaf; the failed one is marked missing
        # rather than silently dropped (which is what makes total=5 truthful).
        self.assertEqual(len(result.questions), 5)
        q3 = next(q for q in result.questions if q.question_id == "3")
        self.assertEqual(q3.marker_source, "missing")
        self.assertIn("AI marking failed", q3.review_reason or "")

    def test_the_no_ai_path_numbers_every_leaf_too(self) -> None:
        """``mcq_only`` marks the theory questions "missing" but still counts them.

        Both AI-free publish sites (deterministic MCQ, missing non-MCQ) take the
        same enumerate position, so an --mcq-only run drives the counter to its
        total instead of stalling at "1 of 5" with four questions unaccounted for.
        """
        with _capturing(EventType.MARKING_PROGRESS) as captured:
            correct_paper(self.ms, self._extracted(), gemini_client=None, mcq_only=True)

        frames = captured[EventType.MARKING_PROGRESS]
        self.assertEqual([f["index"] for f in frames], [1, 2, 3, 4, 5])
        self.assertEqual({f["total"] for f in frames}, {5})
        self.assertEqual(
            [f["marker_source"] for f in frames],
            ["deterministic", "missing", "missing", "missing", "missing"],
        )

    def test_a_dropped_answer_publishes_a_frame_and_reaches_its_sibling(self) -> None:
        """US-031 review F-item follow-up: the dropped short-circuit does three
        things and only one of them was pinned anywhere.

        ``DroppedAnswerReviewFlagTests`` asserts the ``CorrectedQuestion`` the
        short-circuit builds. It cannot assert the other two:
        ``_hybrid_paper_mark_scheme`` is two flat leaves with no ``parent_id``,
        so ``sibling_prior`` is always ``{}`` there, and that class captures no
        events. So both of these were unprotected:

        1. ``prior_results_accumulated[q.id] = 0`` -- a dropped question must
           still appear in its siblings' ECF context carrying 0, not vanish
           from it. ``sibling_prior or None`` means an omitted entry reaches
           the marker as ``None``, silently changing what it is told about the
           student's earlier working. Observable only through a sibling pair,
           which this scheme has.
        2. The dropped branch publishes MARKING_PROGRESS at all, labelled
           ``"dropped"``, against the same ``total`` every other frame carries.
           Without the frame the denominator lies in exactly the way this class
           exists to prevent: ``total=5`` with four frames arriving means
           "Question 4 of 5" never completes on a paper with a dropped answer.

        Neither line is broken today. Both were simply unasserted, and the
        branch this class never visited is the one they live in.
        """
        import lemely.io.correction_ai as _corr_mod

        # Realistic shape: a dropped answer never reaches `answers` at all, it
        # survives only as an id. 2(a) is the FIRST of the sibling pair, so
        # 2(b) is marked after it and can see it in prior_results.
        extracted = ExtractedAnswers(
            paper_id="test",
            source_scan="scan.png",
            answers=[a for a in self._extracted().answers if a.question_id != "2(a)"],
            dropped_question_ids=["2(a)"],
        )
        # Three responses, not four: the MCQ leaf is deterministic and 2(a) is
        # short-circuited before any marker is reached, so only 2(b), 3 and 4
        # consume one each. A fourth would go unused; a second consumed by 2(a)
        # would itself be the bug.
        client = _client_with_seq(self.tmp, [_mock_marker_response(2, ["p1"]) for _ in range(3)])

        prompt_calls: list[dict[str, Any]] = []
        original_fn = _corr_mod.build_marker_user_prompt

        def _spy(*args: Any, **kwargs: Any) -> Any:
            prompt_calls.append({"args": args, "kwargs": kwargs})
            return original_fn(*args, **kwargs)

        with (
            _capturing(EventType.MARKING_PROGRESS) as captured,
            patch.object(_corr_mod, "build_marker_user_prompt", side_effect=_spy),
        ):
            result = correct_paper(self.ms, extracted, gemini_client=client)

        # (2) The frame is emitted, labelled "dropped" rather than borrowing
        # "missing", and leaves the denominator reachable.
        frames = captured[EventType.MARKING_PROGRESS]
        self.assertEqual([f["question_id"] for f in frames], list(self.LEAF_IDS))
        self.assertEqual([f["index"] for f in frames], [1, 2, 3, 4, 5])
        self.assertEqual({f["total"] for f in frames}, {5})
        self.assertEqual(
            [f["marker_source"] for f in frames],
            ["deterministic", "dropped", "ai", "ai", "ai"],
        )
        dropped_frame = frames[1]
        self.assertEqual(dropped_frame["awarded"], 0)
        self.assertEqual(dropped_frame["confidence"], 0.0)
        self.assertEqual(dropped_frame["max_marks"], 2)

        # (1) 2(b) is the only leaf marked after 2(a) under the same parent, so
        # its ECF context is where the 0 has to show up. The MCQ leaf "1" is
        # correctly absent: `sibling_prior` filters on parent_id.
        by_qid = {c["args"][0].id: c for c in prompt_calls}
        self.assertIn("2(b)", by_qid, "build_marker_user_prompt was never called for 2(b)")
        call_2b = by_qid["2(b)"]
        prior = call_2b["kwargs"].get("prior_results") or (
            call_2b["args"][3] if len(call_2b["args"]) > 3 else None
        )
        self.assertIsNotNone(prior, "prior_results not passed for sibling 2(b)")
        self.assertEqual(prior, {"2(a)": 0})

        # Every leaf is still in the result, which is what makes total=5 true.
        self.assertEqual(len(result.questions), 5)
        q2a = next(q for q in result.questions if q.question_id == "2(a)")
        self.assertEqual(q2a.marker_source, "dropped")

    def test_a_blank_answer_publishes_a_frame_and_reaches_its_sibling(self) -> None:
        """US-039: the blank short-circuit needs the same two guarantees the
        dropped short-circuit needed above -- ``_hybrid_paper_mark_scheme``
        (used by ``BlankAnswerShortCircuitTests``) is two flat leaves with no
        ``parent_id``, so ``sibling_prior`` is always ``{}`` there and this
        property is unobservable in that class. This scheme's "2(a)"/"2(b)"
        sibling pair is what makes it observable.

        1. A ``MARKING_PROGRESS`` frame is still published for the blank leaf,
           labelled with its ``marker_source`` ("missing") against the same
           ``total`` every other frame carries -- omitting it would leave
           ``total=5`` promising a question that never arrives.
        2. ``prior_results_accumulated[q.id] = 0`` still runs for the blank
           leaf, so its sibling sees it in ``prior_results`` rather than the
           entry being silently omitted (``sibling_prior or None`` turns an
           omitted entry into ``None``, not ``{}}``, so asserting
           ``assertIsNotNone`` first is required -- otherwise this would pass
           vacuously against a missing key).
        """
        import lemely.io.correction_ai as _corr_mod

        # 2(a) has no extracted answer at all -- the "no entry" shape of blank.
        # 2(b) is the sibling marked afterward under the same parent_id.
        extracted = ExtractedAnswers(
            paper_id="test",
            source_scan="scan.png",
            answers=[a for a in self._extracted().answers if a.question_id != "2(a)"],
        )
        # Three responses: the MCQ leaf is deterministic and 2(a) is
        # short-circuited as blank before any marker is reached, so only
        # 2(b), 3 and 4 consume one each.
        client = _client_with_seq(self.tmp, [_mock_marker_response(2, ["p1"]) for _ in range(3)])

        prompt_calls: list[dict[str, Any]] = []
        original_fn = _corr_mod.build_marker_user_prompt

        def _spy(*args: Any, **kwargs: Any) -> Any:
            prompt_calls.append({"args": args, "kwargs": kwargs})
            return original_fn(*args, **kwargs)

        with (
            _capturing(EventType.MARKING_PROGRESS) as captured,
            patch.object(_corr_mod, "build_marker_user_prompt", side_effect=_spy),
        ):
            result = correct_paper(self.ms, extracted, gemini_client=client)

        # (1) The frame is emitted, labelled "missing", and leaves the
        # denominator reachable -- no gap for "2(a)".
        frames = captured[EventType.MARKING_PROGRESS]
        self.assertEqual([f["question_id"] for f in frames], list(self.LEAF_IDS))
        self.assertEqual([f["index"] for f in frames], [1, 2, 3, 4, 5])
        self.assertEqual({f["total"] for f in frames}, {5})
        self.assertEqual(
            [f["marker_source"] for f in frames],
            ["deterministic", "missing", "ai", "ai", "ai"],
        )
        blank_frame = frames[1]
        self.assertEqual(blank_frame["awarded"], 0)
        self.assertEqual(blank_frame["confidence"], 0.0)
        self.assertEqual(blank_frame["max_marks"], 2)

        # (2) 2(b) is the only leaf marked after 2(a) under the same parent, so
        # its ECF context is where the 0 has to show up.
        by_qid = {c["args"][0].id: c for c in prompt_calls}
        self.assertIn("2(b)", by_qid, "build_marker_user_prompt was never called for 2(b)")
        call_2b = by_qid["2(b)"]
        prior = call_2b["kwargs"].get("prior_results") or (
            call_2b["args"][3] if len(call_2b["args"]) > 3 else None
        )
        self.assertIsNotNone(prior, "prior_results not passed for sibling 2(b)")
        self.assertEqual(prior, {"2(a)": 0})

        # Every leaf is still in the result, and the blank one is unflagged
        # (the ruling), unlike the dropped equivalent above.
        self.assertEqual(len(result.questions), 5)
        q2a = next(q for q in result.questions if q.question_id == "2(a)")
        self.assertEqual(q2a.marker_source, "missing")
        self.assertFalse(q2a.needs_teacher_review)


class CostCeilingAbortTests(unittest.TestCase):
    """US-030: a per-run spend ceiling breach stops the run mid-paper.

    ``_check_cost_ceiling`` raises :class:`CostCeilingError` — a stop signal
    for the whole run, not a per-question failure. Before this fix the broad
    ``except Exception`` around ``ai.mark_question`` absorbed it exactly like
    a model failure: every remaining leaf was still attempted (each one
    breaching again), each got ``awarded=0`` with ``review_reason="AI marking
    failed: USD ceiling (...)"``, and ``correct_paper`` returned NORMALLY. A
    caller could not tell those fabricated zeros from real model failures,
    and the spend guard was advisory rather than binding.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.ms = _five_leaf_mark_scheme()

    def _extracted(self) -> ExtractedAnswers:
        return ExtractedAnswers(
            paper_id="test",
            source_scan="scan.png",
            answers=[
                ExtractedAnswer(question_id="1", answer="A", confidence=0.99),
                ExtractedAnswer(question_id="2(a)", answer="states and applies it", confidence=0.9),
                ExtractedAnswer(question_id="2(b)", answer="uses the 20 from (a)", confidence=0.9),
                ExtractedAnswer(question_id="3", answer="because gravity", confidence=0.9),
                ExtractedAnswer(question_id="4", answer="energy is conserved", confidence=0.9),
            ],
        )

    def test_a_ceiling_breach_stops_the_paper_instead_of_awarding_zeros(self) -> None:
        """The regression. Leaf "2(a)" marks cleanly, then the ceiling binds.

        What must NOT happen: leaves "2(b)", "3" and "4" each get attempted,
        each re-breach, and each land in the result as ``awarded=0`` with an
        "AI marking failed" reason — a plausible-looking paper of fabricated
        zeros. The breach must leave ``correct_paper`` by raising.
        """
        client = _client_with_seq(self.tmp, [_mock_marker_response(2, ["p1"]) for _ in range(4)])

        real_check = GeminiClient._check_cost_ceiling
        attempts: list[int] = []

        def _ceiling_binds_on_the_second_call(client_self: GeminiClient) -> None:
            attempts.append(1)
            if len(attempts) >= 2:
                raise CostCeilingError(
                    "USD ceiling ($14.0000) exceeded; persistent cumulative spend "
                    "is $14.0100 (across all runs)."
                )
            real_check(client_self)

        with (
            patch.object(GeminiClient, "_check_cost_ceiling", _ceiling_binds_on_the_second_call),
            _capturing(EventType.MARKING_PROGRESS, EventType.ERROR) as captured,
            self.assertRaises(CostCeilingError) as ctx,
        ):
            correct_paper(self.ms, self._extracted(), gemini_client=client)

        self.assertIn("USD ceiling", str(ctx.exception))

        # Exactly two paid attempts: "2(a)" succeeded, "2(b)" breached, and
        # then the run stopped. Three or four means the breach was absorbed
        # and the marker kept spending into a ceiling it had already hit.
        self.assertEqual(len(attempts), 2)

        # Only the MCQ leaf and "2(a)" ever reported progress. A frame for
        # "2(b)"/"3"/"4" would mean a zero was recorded for them.
        frames = captured[EventType.MARKING_PROGRESS]
        self.assertEqual([f["question_id"] for f in frames], ["1", "2(a)"])

        # And the breach is not dressed up as a per-question marking error.
        self.assertEqual(
            [e for e in captured[EventType.ERROR] if "AI marking failed" in str(e["message"])],
            [],
        )

    def test_an_ordinary_model_failure_still_degrades_to_a_flagged_zero(self) -> None:
        """The blast-radius guard: only the ceiling breach changes behaviour.

        A plain ``RuntimeError`` from the marker must still produce a
        ``marker_source="missing"`` question with an "AI marking failed"
        reason, and the rest of the paper must still be marked.
        """
        client = _client_with_seq(
            self.tmp,
            [
                _mock_marker_response(2, ["p1"]),
                RuntimeError("marker stub refuses this question"),
                _mock_marker_response(2, ["p1"]),
                _mock_marker_response(2, ["p1"]),
            ],
        )

        result = correct_paper(self.ms, self._extracted(), gemini_client=client)

        self.assertEqual(len(result.questions), 5)
        failed = next(q for q in result.questions if q.question_id == "2(b)")
        self.assertEqual(failed.marker_source, "missing")
        self.assertEqual(failed.awarded_marks, 0)
        self.assertIn("AI marking failed", failed.review_reason or "")

    def test_a_transport_external_service_error_still_degrades(self) -> None:
        """A plain ``ExternalServiceError`` — the ceiling error's own parent
        class — must keep degrading. Narrowing on the parent instead of on
        ``CostCeilingError`` would take this ordinary transport failure down
        with the whole run.
        """
        client = _client_with_seq(
            self.tmp,
            [
                _mock_marker_response(2, ["p1"]),
                _mock_marker_response(2, ["p1"]),
                _mock_marker_response(2, ["p1"]),
                _mock_marker_response(2, ["p1"]),
            ],
        )

        real_check = GeminiClient._check_cost_ceiling
        attempts: list[int] = []

        def _transport_fails_on_the_second_call(client_self: GeminiClient) -> None:
            attempts.append(1)
            if len(attempts) == 2:
                raise ExternalServiceError("upstream refused the request")
            real_check(client_self)

        with patch.object(GeminiClient, "_check_cost_ceiling", _transport_fails_on_the_second_call):
            result = correct_paper(self.ms, self._extracted(), gemini_client=client)

        self.assertEqual(len(result.questions), 5)
        degraded = next(q for q in result.questions if q.question_id == "2(b)")
        self.assertEqual(degraded.marker_source, "missing")
        self.assertIn("AI marking failed", degraded.review_reason or "")
        # The paper was finished: leaves "3" and "4" were still attempted.
        self.assertEqual(len(attempts), 4)


class DuplicateQuestionIdFlattenTests(unittest.TestCase):
    """NIT-B: two ``ExtractedAnswer``s sharing one ``question_id`` must not
    vanish into a dict comprehension unnoticed -- the loss has to be
    observable, mirroring the same-file ``MARKING_PROGRESS`` precedent of
    surfacing internal state as a bus event (``ANSWER_DROPPED`` is a
    different event, published only from ``answer_extraction.py``, not from
    this file; see US-031 review MUST-FIX 7 for the dropped-answers case).
    """

    def test_duplicate_question_id_publishes_event_and_last_one_wins(self) -> None:
        frames: list[dict] = []

        def _spy(**payload: object) -> None:
            frames.append(payload)

        extracted = ExtractedAnswers(
            paper_id="test",
            source_scan="scan.png",
            answers=[
                ExtractedAnswer(question_id="1", answer="first", confidence=0.5),
                ExtractedAnswer(question_id="2", answer="only", confidence=0.9),
                ExtractedAnswer(question_id="1", answer="second", confidence=0.8),
            ],
        )

        bus.subscribe(EventType.DUPLICATE_QUESTION_ID, _spy)
        try:
            flattened = _flatten_answers(extracted)
        finally:
            bus.unsubscribe(EventType.DUPLICATE_QUESTION_ID, _spy)

        # Policy: last-wins. Pinned here, not incidental to dict construction.
        self.assertEqual(flattened["1"], ("second", None, 0.8))
        self.assertEqual(flattened["2"], ("only", None, 0.9))

        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0]["duplicate_counts"], {"1": 1})
        self.assertEqual(frames[0]["total_answers"], 3)

    def test_no_duplicate_event_when_all_ids_distinct(self) -> None:
        frames: list[dict] = []

        def _spy(**payload: object) -> None:
            frames.append(payload)

        extracted = ExtractedAnswers(
            paper_id="test",
            source_scan="scan.png",
            answers=[
                ExtractedAnswer(question_id="1", answer="A", confidence=0.5),
                ExtractedAnswer(question_id="2", answer="B", confidence=0.9),
            ],
        )

        bus.subscribe(EventType.DUPLICATE_QUESTION_ID, _spy)
        try:
            flattened = _flatten_answers(extracted)
        finally:
            bus.unsubscribe(EventType.DUPLICATE_QUESTION_ID, _spy)

        self.assertEqual(frames, [])
        self.assertEqual(flattened["1"], ("A", None, 0.5))
        self.assertEqual(flattened["2"], ("B", None, 0.9))

    def test_duplicate_count_is_extra_occurrences_not_total(self) -> None:
        """Pin the payload semantics at 3+ occurrences, where "extra
        occurrences beyond the first" and "total occurrences" diverge (at
        exactly 2 occurrences both readings give 1, so that case alone
        cannot distinguish them).
        """
        frames: list[dict] = []

        def _spy(**payload: object) -> None:
            frames.append(payload)

        extracted = ExtractedAnswers(
            paper_id="test",
            source_scan="scan.png",
            answers=[
                ExtractedAnswer(question_id="1", answer="first", confidence=0.5),
                ExtractedAnswer(question_id="1", answer="second", confidence=0.6),
                ExtractedAnswer(question_id="1", answer="third", confidence=0.7),
            ],
        )

        bus.subscribe(EventType.DUPLICATE_QUESTION_ID, _spy)
        try:
            flattened = _flatten_answers(extracted)
        finally:
            bus.unsubscribe(EventType.DUPLICATE_QUESTION_ID, _spy)

        # 3 occurrences -> 2 *extra* beyond the first, not 3 total.
        self.assertEqual(flattened["1"], ("third", None, 0.7))
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0]["duplicate_counts"], {"1": 2})
        self.assertEqual(frames[0]["total_answers"], 3)

    def test_mapping_fallback_branch_never_publishes(self) -> None:
        """A plain ``Mapping[str, str]`` cannot contain duplicate keys -- it
        never went through extraction, so there is nothing to detect."""
        frames: list[dict] = []

        def _spy(**payload: object) -> None:
            frames.append(payload)

        bus.subscribe(EventType.DUPLICATE_QUESTION_ID, _spy)
        try:
            flattened = _flatten_answers({"1": "A", "2": "B"})
        finally:
            bus.unsubscribe(EventType.DUPLICATE_QUESTION_ID, _spy)

        self.assertEqual(frames, [])
        self.assertEqual(flattened["1"], ("A", None, 1.0))
        self.assertEqual(flattened["2"], ("B", None, 1.0))


class EcfChainResolverTests(unittest.TestCase):
    """I7 (US-013) CHAIN resolver + GATE, as pure functions -- independent of
    ``correct_paper`` orchestration and any marking call. Measured on the
    full 289-scheme corpus (10,314 answer points): 820 same-leaf chains,
    438 cross-leaf chains, 28 gated points across 10 schemes -- and their
    intersection (the true I7 activation ceiling) is 0. See
    ``_resolve_ecf_chain``/``_maybe_apply_ecf_substitution``'s own
    docstrings for why same-leaf and cross-leaf chains are structurally
    identical here but only cross-leaf ones are ever substituted on.
    """

    def _leaf(
        self,
        id_: str,
        marks: int,
        points: list,
        parent_id: str | None = None,
        notes: str | None = None,
        marking_guidance: str | None = None,
    ):
        from lemely.core.loose_schemas import Question, QuestionType

        return Question.model_construct(
            id=id_,
            parent_id=parent_id,
            marks=marks,
            type=QuestionType.CALCULATION,
            answer_points=points,
            parts=[],
            assessment_objectives=[],
            rejected_answers=[],
            ignored_answers=[],
            notes=notes,
            marking_guidance=marking_guidance,
        )

    def test_top_level_scoping_resolves_cross_leaf_chain(self) -> None:
        """The golden fixture's own shape (1a_i M -> 1a_ii A): an
        immediate-parent-only resolver -- one that looks only inside
        ``question``'s own ``answer_points`` or its container parent's,
        never a SIBLING LEAF's -- finds nothing here and must fail this
        test."""
        from lemely.core.loose_schemas import AnswerPoint, MathMarkType
        from lemely.io.correction_ai import _resolve_ecf_chain

        m_point = AnswerPoint(id="p1", point="(a=) (v-u)/t", marks=1, math_mark_type=MathMarkType.M)
        a_point = AnswerPoint(id="p1", point="final value", marks=1, math_mark_type=MathMarkType.A)
        leaf_i = self._leaf("1a_i", 1, [m_point])
        leaf_ii = self._leaf("1a_ii", 1, [a_point])

        result = _resolve_ecf_chain(leaf_ii, a_point, [leaf_i, leaf_ii])

        self.assertEqual(result, ("1a_i", "p1"))

    def test_no_preceding_m_point_anywhere_is_unresolvable(self) -> None:
        """A point with no preceding M anywhere in its top-level question
        must never resolve to a substitutable prerequisite."""
        from lemely.core.loose_schemas import AnswerPoint, MathMarkType
        from lemely.io.correction_ai import _resolve_ecf_chain

        a_point = AnswerPoint(id="p1", point="value", marks=1, math_mark_type=MathMarkType.A)
        leaf = self._leaf("1a", 1, [a_point])

        self.assertIsNone(_resolve_ecf_chain(leaf, a_point, [leaf]))

    def test_required_with_resolves_within_same_question_only(self) -> None:
        """A non-null ``required_with`` of "p1" must resolve to THIS
        question's own "p1", never another question's -- even when another
        question in the same top-level group happens to reuse the id (point
        ids are question-scoped by design, ``loose_schemas.py:202``)."""
        from lemely.core.loose_schemas import AnswerPoint, MathMarkType
        from lemely.io.correction_ai import _resolve_ecf_chain

        other_p1 = AnswerPoint(id="p1", point="x's own p1", marks=5, math_mark_type=MathMarkType.M)
        other_leaf = self._leaf("9", 5, [other_p1])

        own_p1 = AnswerPoint(id="p1", point="y's own p1", marks=1, math_mark_type=MathMarkType.M)
        dependent = AnswerPoint(
            id="p2",
            point="y's dependent",
            marks=1,
            math_mark_type=MathMarkType.A,
            required_with="p1",
            condition="ft",
        )
        y_leaf = self._leaf("10", 2, [own_p1, dependent])

        result = _resolve_ecf_chain(y_leaf, dependent, [other_leaf, y_leaf])

        self.assertEqual(result, ("10", "p1"))  # Y's own p1, never X's

    def test_required_with_dangling_never_falls_back_to_a_paper_wide_lookup(self) -> None:
        """A paper-wide lookup would wrongly find X's "p1" for Y's dangling
        reference; the correct answer is "no prerequisite", not X's point."""
        from lemely.core.loose_schemas import AnswerPoint, MathMarkType
        from lemely.io.correction_ai import _resolve_ecf_chain

        other_p1 = AnswerPoint(id="p1", point="x's p1", marks=1, math_mark_type=MathMarkType.M)
        other_leaf = self._leaf("9", 1, [other_p1])
        dependent = AnswerPoint(
            id="p2",
            point="y's dependent",
            marks=1,
            math_mark_type=MathMarkType.A,
            required_with="p1",  # Y has NO "p1" of its own
            condition="ft",
        )
        y_leaf = self._leaf("10", 1, [dependent])

        self.assertIsNone(_resolve_ecf_chain(y_leaf, dependent, [other_leaf, y_leaf]))

    def test_gate_fires_on_point_condition_marker(self) -> None:
        from lemely.core.loose_schemas import AnswerPoint, MathMarkType
        from lemely.io.correction_ai import _ecf_gated

        point = AnswerPoint(
            id="p1", point="value", marks=1, math_mark_type=MathMarkType.A, condition="Strict FT"
        )
        leaf = self._leaf("1", 1, [point])

        self.assertTrue(_ecf_gated(leaf, point))

    def test_gate_fires_on_question_notes_marker(self) -> None:
        """Measured example from the corpus: `"R = 4.05 / ecf, 3.89, 3.81"`."""
        from lemely.core.loose_schemas import AnswerPoint, MathMarkType
        from lemely.io.correction_ai import _ecf_gated

        point = AnswerPoint(id="p1", point="value", marks=1, math_mark_type=MathMarkType.A)
        leaf = self._leaf("1", 1, [point], notes="R = 4.05 / ecf, 3.89, 3.81")

        self.assertTrue(_ecf_gated(leaf, point))

    def test_gate_is_case_sensitive_for_ft_to_exclude_impulse_formulae(self) -> None:
        """Post-I7-review fix B: the corpus hit
        `0625_s23_ms_42` q2b/p2 -- `"Ft = ∆mv OR F = ma OR ..."` -- is the
        impulse formula (force x time), not follow-through, and the
        original case-INSENSITIVE `\\bft\\b` gated it regardless. Every
        genuine follow-through marker in the corpus is written uppercase
        ("Strict FT", "FT their median reading"), confirmed by
        re-measuring the whole corpus with the fix (29 -> 28 points,
        11 -> 10 schemes, dropping exactly this one hit and no genuine
        one) -- so `FT` alone is matched case-sensitively; `ecf`/`dep` stay
        case-insensitive."""
        from lemely.core.loose_schemas import AnswerPoint, MathMarkType
        from lemely.io.correction_ai import _ecf_gated

        impulse_point = AnswerPoint(
            id="p2",
            # Corpus-verbatim glyphs, not ASCII substitutes -- this is the
            # exact text of the corpus hit the fix removes.
            point="Ft = ∆mv OR F = ma OR (F =) (0.16 × 18) / 0.12 C1",  # noqa: RUF001
            marks=1,
            math_mark_type=MathMarkType.C,
        )
        leaf = self._leaf("2b", 1, [impulse_point])

        self.assertFalse(_ecf_gated(leaf, impulse_point))

    def test_gate_does_not_fire_without_a_marker(self) -> None:
        """The measured 0.27% activation rate (28 of 10,314 points): absent
        a marker, GATE must stay closed even though the point is otherwise
        perfectly ordinary."""
        from lemely.core.loose_schemas import AnswerPoint, MathMarkType
        from lemely.io.correction_ai import _ecf_gated

        point = AnswerPoint(id="p1", point="value", marks=1, math_mark_type=MathMarkType.A)
        leaf = self._leaf("1", 1, [point])

        self.assertFalse(_ecf_gated(leaf, point))


class ECFSubstitutionTests(unittest.TestCase):
    """I7 (US-013): error-carried-forward by substitution, behind
    ``ecf_substitution`` (default OFF), orchestrated end-to-end through
    ``correct_paper``. Fixture: top-level Q1 -> 1a -> {1a_i (M point p1),
    1a_ii (A point p1)} -- the same cross-leaf, same-top-level-question
    shape the nested golden fixture
    (``tests/golden/0625_w21_qp_32_theory_nested``) exercises; built here in
    Python so this test file owns the fixture outright (FILE OWNERSHIP) and
    the committed corpus/golden JSON is never touched.

    ``AICorrector.mark_question`` is patched directly (never a live Gemini
    call, and never a cache/thinking-retry side channel to control) so each
    test asserts on the EXACT sequence of marking calls and their kwargs.
    """

    def _scheme(self, *, gate_marker: str | None = "ecf") -> MarkScheme:
        point_ii: dict[str, object] = {
            "id": "p1",
            "point": "final numeric value",
            "marks": 1,
            "math_mark_type": "A",
        }
        if gate_marker is not None:
            point_ii["condition"] = gate_marker
        return MarkScheme.model_validate(
            {
                "metadata": {
                    "subject": "Physics",
                    "subject_code": "0625",
                    "paper_number": 3,
                    "paper_variant": 2,
                    "session_month": "Oct/Nov",
                    "session_year": 2021,
                    "paper_type": "theory_extended",
                    "maximum_mark": 2,
                    "scheme_format": "point_based",
                },
                "questions": [
                    {
                        "id": "1",
                        "marks": 0,
                        "type": "calculation",
                        "parts": [
                            {
                                "id": "1a",
                                "marks": 0,
                                "type": "calculation",
                                "parent_id": "1",
                                "parts": [
                                    {
                                        "id": "1a_i",
                                        "marks": 1,
                                        "type": "calculation",
                                        "parent_id": "1a",
                                        "answer_points": [
                                            {
                                                "id": "p1",
                                                "point": "(a=) (v-u)/t in any form",
                                                "marks": 1,
                                                "math_mark_type": "M",
                                            }
                                        ],
                                    },
                                    {
                                        "id": "1a_ii",
                                        "marks": 1,
                                        "type": "calculation",
                                        "parent_id": "1a",
                                        "answer_points": [point_ii],
                                    },
                                ],
                            },
                        ],
                    }
                ],
            }
        )

    def _unresolvable_scheme(self) -> MarkScheme:
        """A single leaf, gated A-point, no M anywhere in the paper."""
        return MarkScheme.model_validate(
            {
                "metadata": {
                    "subject": "Physics",
                    "subject_code": "0625",
                    "paper_number": 3,
                    "paper_variant": 2,
                    "session_month": "Oct/Nov",
                    "session_year": 2021,
                    "paper_type": "theory_extended",
                    "maximum_mark": 1,
                    "scheme_format": "point_based",
                },
                "questions": [
                    {
                        "id": "1",
                        "marks": 1,
                        "type": "calculation",
                        "answer_points": [
                            {
                                "id": "p1",
                                "point": "final value",
                                "marks": 1,
                                "math_mark_type": "A",
                                "condition": "ecf",
                            }
                        ],
                    },
                ],
            }
        )

    def _extracted(self, a_answer: str, aii_answer: str) -> ExtractedAnswers:
        return ExtractedAnswers(
            paper_id="test",
            source_scan="scan.png",
            answers=[
                ExtractedAnswer(question_id="1a_i", answer=a_answer, confidence=0.9),
                ExtractedAnswer(question_id="1a_ii", answer=aii_answer, confidence=0.9),
            ],
        )

    def _pv(self, point_id: str, verdict: str, ecf: bool = False, span: str = "x"):
        from lemely.core.schemas import PointVerdict

        return PointVerdict(point_id=point_id, verdict=verdict, evidence_span=span, ecf_applied=ecf)

    def _mark(self, point_verdicts, confidence: float = 0.95, feedback: str = "fb"):
        from lemely.core.schemas import AIMarkResponse

        return AIMarkResponse(
            awarded_marks=0,  # deliberately stale -- the verdict path ignores it
            confidence=confidence,
            matched_point_ids=[],  # deliberately stale, same reason
            feedback=feedback,
            point_verdicts=point_verdicts,
        )

    def test_wrong_prerequisite_triggers_substitution_to_full_marks(self) -> None:
        """Direction 1 of the false-positive axis: a wrong (a) with a
        correct, consistent method in (b) earns full marks via ECF, with
        ``ecf_applied=True`` recorded on the awarded verdict."""
        scheme = self._scheme()
        extracted = self._extracted("wrong value", "consistent working from wrong value")
        mark_1a_i = self._mark([self._pv("p1", "withheld")])  # (a) got the M wrong
        # not satisfied vs the scheme's correct value:
        mark_1a_ii_pass1 = self._mark([self._pv("p1", "withheld")])
        mark_1a_ii_pass2 = self._mark([self._pv("p1", "awarded", span="consistent")])  # ECF re-mark

        with patch.object(
            correction_ai.AICorrector,
            "mark_question",
            side_effect=[mark_1a_i, mark_1a_ii_pass1, mark_1a_ii_pass2],
        ) as mock_mark:
            result = correct_paper(
                mark_scheme=scheme,
                extracted_answers=extracted,
                gemini_client=MagicMock(),
                equivalence_gate=True,
                ecf_substitution=True,
            )

        self.assertEqual(mock_mark.call_count, 3)  # (a), (b) pass 1, (b) ECF re-mark
        cq_ii = next(q for q in result.questions if q.question_id == "1a_ii")
        self.assertEqual(cq_ii.awarded_marks, 1)
        self.assertEqual(cq_ii.point_verdicts[0].verdict, "awarded")
        self.assertTrue(cq_ii.point_verdicts[0].ecf_applied)
        # The third call is the substitution itself: the student's OWN
        # extracted VALUE for the prerequisite, never marks or the scheme's
        # correct value -- tagged with the prerequisite POINT's own scheme
        # text (the SHOULD-FIX that followed Critical 2's review), so the
        # model knows WHICH of the leaf's numbers is being carried forward.
        _, third_call_kwargs = mock_mark.call_args_list[2]
        self.assertEqual(
            third_call_kwargs["prior_values"],
            {"1a_i": "answer: wrong value\ndepends on: (a=) (v-u)/t in any form"},
        )

    def test_correct_prerequisite_never_triggers_substitution(self) -> None:
        """Direction 2 of the false-positive axis -- the dangerous one: a
        CORRECT (a) must never cause a second marking call for (b), even
        though (b) is gated, chain-resolvable, and below max. Asserted by
        VALUE (the marker was never called a third time, and ecf_applied
        stays False), never by a log line."""
        scheme = self._scheme()
        extracted = self._extracted("correct value", "some working")
        mark_1a_i = self._mark([self._pv("p1", "awarded", span="correct")])  # (a) correct
        mark_1a_ii = self._mark([self._pv("p1", "withheld")])  # below max, gated, resolvable

        with patch.object(
            correction_ai.AICorrector, "mark_question", side_effect=[mark_1a_i, mark_1a_ii]
        ) as mock_mark:
            result = correct_paper(
                mark_scheme=scheme,
                extracted_answers=extracted,
                gemini_client=MagicMock(),
                equivalence_gate=True,
                ecf_substitution=True,
            )

        self.assertEqual(mock_mark.call_count, 2)  # no third (ECF) call
        cq_ii = next(q for q in result.questions if q.question_id == "1a_ii")
        self.assertEqual(cq_ii.awarded_marks, 0)
        self.assertFalse(cq_ii.point_verdicts[0].ecf_applied)

    def test_unresolvable_chain_is_inert(self) -> None:
        """An A-point with no preceding M anywhere in its top-level question
        is never substituted even when gated.

        Tightened per review: ``answers.get(prereq_leaf_id)`` returning
        ``None`` would ALSO skip substitution for an unrelated reason (a
        resolver bug returning an unknown leaf id) -- not vacuous (it does
        go red under such a bug), but the resolver's own answer is asserted
        directly too, so this test fails specifically on "the chain
        resolves to something", not merely on "nothing got substituted"."""
        from lemely.io.correction_ai import _resolve_ecf_chain

        scheme = self._unresolvable_scheme()
        leaf = scheme.questions[0]
        self.assertIsNone(_resolve_ecf_chain(leaf, leaf.answer_points[0], [leaf]))

        extracted = ExtractedAnswers(
            paper_id="test",
            source_scan="scan.png",
            answers=[ExtractedAnswer(question_id="1", answer="something", confidence=0.9)],
        )
        mark_1 = self._mark([self._pv("p1", "withheld")])

        with patch.object(
            correction_ai.AICorrector, "mark_question", side_effect=[mark_1]
        ) as mock_mark:
            result = correct_paper(
                mark_scheme=scheme,
                extracted_answers=extracted,
                gemini_client=MagicMock(),
                equivalence_gate=True,
                ecf_substitution=True,
            )

        self.assertEqual(mock_mark.call_count, 1)  # no second call -- no prerequisite exists
        cq = result.questions[0]
        self.assertEqual(cq.awarded_marks, 0)
        self.assertFalse(cq.point_verdicts[0].ecf_applied)

    def test_ungated_point_is_inert(self) -> None:
        """A point with a resolvable chain but no ecf/ft/dep marker is never
        substituted, even though the prerequisite is wrong."""
        scheme = self._scheme(gate_marker=None)
        extracted = self._extracted("wrong value", "some working")
        # (a) wrong -- would be eligible for a re-mark if the point were gated:
        mark_1a_i = self._mark([self._pv("p1", "withheld")])
        mark_1a_ii = self._mark([self._pv("p1", "withheld")])

        with patch.object(
            correction_ai.AICorrector, "mark_question", side_effect=[mark_1a_i, mark_1a_ii]
        ) as mock_mark:
            result = correct_paper(
                mark_scheme=scheme,
                extracted_answers=extracted,
                gemini_client=MagicMock(),
                equivalence_gate=True,
                ecf_substitution=True,
            )

        self.assertEqual(mock_mark.call_count, 2)  # no ECF call -- gate closed
        cq_ii = next(q for q in result.questions if q.question_id == "1a_ii")
        self.assertEqual(cq_ii.awarded_marks, 0)
        self.assertFalse(cq_ii.point_verdicts[0].ecf_applied)

    def test_below_max_precondition(self) -> None:
        """A part already at full marks is never re-marked even when gated
        with a resolvable (and wrong) prerequisite."""
        scheme = self._scheme()
        extracted = self._extracted("wrong value", "some working")
        mark_1a_i = self._mark([self._pv("p1", "withheld")])  # (a) wrong
        # already full marks before the ECF check ever runs:
        mark_1a_ii = self._mark([self._pv("p1", "awarded", span="some working")])

        with patch.object(
            correction_ai.AICorrector, "mark_question", side_effect=[mark_1a_i, mark_1a_ii]
        ) as mock_mark:
            result = correct_paper(
                mark_scheme=scheme,
                extracted_answers=extracted,
                gemini_client=MagicMock(),
                equivalence_gate=True,
                ecf_substitution=True,
            )

        self.assertEqual(mock_mark.call_count, 2)  # already at max -- never re-marked
        cq_ii = next(q for q in result.questions if q.question_id == "1a_ii")
        self.assertEqual(cq_ii.awarded_marks, 1)
        self.assertFalse(cq_ii.point_verdicts[0].ecf_applied)

    def test_flag_off_is_inert(self) -> None:
        """With ``ecf_substitution`` off, behaviour is byte-identical to the
        same fixture/mocks with the flag simply absent -- every
        ``ecf_applied`` stays False and the marker is never called a third
        time, asserted at the outcome level (not by checking a branch)."""
        scheme = self._scheme()
        extracted = self._extracted("wrong value", "consistent working from wrong value")
        mark_1a_i = self._mark([self._pv("p1", "withheld")])
        mark_1a_ii = self._mark([self._pv("p1", "withheld")])

        with patch.object(
            correction_ai.AICorrector, "mark_question", side_effect=[mark_1a_i, mark_1a_ii]
        ) as mock_mark:
            result = correct_paper(
                mark_scheme=scheme,
                extracted_answers=extracted,
                gemini_client=MagicMock(),
                equivalence_gate=True,
                ecf_substitution=False,
            )

        self.assertEqual(mock_mark.call_count, 2)  # never a third (ECF) call
        cq_ii = next(q for q in result.questions if q.question_id == "1a_ii")
        self.assertEqual(cq_ii.awarded_marks, 0)
        self.assertFalse(cq_ii.point_verdicts[0].ecf_applied)

    def test_equivalence_gate_off_never_pays_for_a_second_call(self) -> None:
        """Post-I7-review fix A: ``point_verdicts`` is NOT in the wire
        schema's ``required`` list, so a model COULD volunteer it even when
        ``equivalence_gate`` is off (the I6 prompt block never appended).
        Before this fix, ``_maybe_apply_ecf_substitution`` gated only on
        ``mark.point_verdicts`` being non-empty -- so
        ``ecf_substitution=True, equivalence_gate=False`` could spend an
        extra BILLED marking call per eligible question, with its result
        discarded (``_build_ai_corrected`` only consumes verdicts when
        ``equivalence_gate`` is also True). Same wrong-(a)/gated/resolvable
        shape as the positive test above, but with ``equivalence_gate=False``
        and the mocked responses volunteering ``point_verdicts`` anyway (to
        prove the guard, not the prompt, is what stops the call) -- assert
        on the CALL COUNT, since that is what costs money."""
        scheme = self._scheme()
        extracted = self._extracted("wrong value", "consistent working from wrong value")
        mark_1a_i = self._mark([self._pv("p1", "withheld")])
        mark_1a_ii = self._mark([self._pv("p1", "withheld")])

        with patch.object(
            correction_ai.AICorrector, "mark_question", side_effect=[mark_1a_i, mark_1a_ii]
        ) as mock_mark:
            result = correct_paper(
                mark_scheme=scheme,
                extracted_answers=extracted,
                gemini_client=MagicMock(),
                equivalence_gate=False,
                ecf_substitution=True,
            )

        self.assertEqual(mock_mark.call_count, 2)  # no billed ECF re-mark call
        cq_ii = next(q for q in result.questions if q.question_id == "1a_ii")
        # Legacy path: trusts mark.awarded_marks/matched_point_ids, not the
        # volunteered point_verdicts -- and point_verdicts is empty on the
        # persisted CorrectedQuestion either way (CorrectedQuestion.point_verdicts
        # defaults empty, only ever populated by the verdicts path).
        self.assertEqual(cq_ii.point_verdicts, [])

    def test_same_leaf_chain_never_triggers_substitution(self) -> None:
        """Post-I7-review Critical 2 (a design error in the original brief,
        not the implementation): a same-leaf M-then-A pair is one
        computation's method and accuracy marks, not error carried FORWARD
        between two parts -- there is nothing to substitute. Measured on the
        full corpus, same-leaf chains (820) structurally outnumber cross-leaf
        ones (438) -- but the gate (28 points) never co-occurs with EITHER
        chain shape on this corpus (measured: gate-and-chain intersection is
        0 for both), so the unfixed code would have substituted on ZERO
        corpus points, not 820. The exclusion is correct on PRINCIPLE, not
        load-bearing on this corpus -- this test pins the principle directly,
        since neither `_scheme()` nor `_unresolvable_scheme()` exercises the
        same-leaf shape at all, and no corpus row can exercise it either."""
        # One leaf, two points: p1=M (wrong), p2=A (gated, resolvable to p1
        # -- but SAME leaf, so must be excluded regardless of the M being wrong).
        scheme = MarkScheme.model_validate(
            {
                "metadata": {
                    "subject": "Physics",
                    "subject_code": "0625",
                    "paper_number": 3,
                    "paper_variant": 2,
                    "session_month": "Oct/Nov",
                    "session_year": 2021,
                    "paper_type": "theory_extended",
                    "maximum_mark": 2,
                    "scheme_format": "point_based",
                },
                "questions": [
                    {
                        "id": "1",
                        "marks": 2,
                        "type": "calculation",
                        "answer_points": [
                            {
                                "id": "p1",
                                "point": "(a=) (v-u)/t in any form",
                                "marks": 1,
                                "math_mark_type": "M",
                            },
                            {
                                "id": "p2",
                                "point": "final numeric value",
                                "marks": 1,
                                "math_mark_type": "A",
                                "condition": "ecf",
                            },
                        ],
                    }
                ],
            }
        )
        extracted = ExtractedAnswers(
            paper_id="test",
            source_scan="scan.png",
            answers=[
                ExtractedAnswer(
                    question_id="1", answer="wrong method, consistent value", confidence=0.9
                )
            ],
        )
        # ONE leaf -> ONE mark_question call carries BOTH points' verdicts.
        mark_1 = self._mark(
            [self._pv("p1", "withheld"), self._pv("p2", "withheld")],
        )

        with patch.object(
            correction_ai.AICorrector, "mark_question", side_effect=[mark_1]
        ) as mock_mark:
            result = correct_paper(
                mark_scheme=scheme,
                extracted_answers=extracted,
                gemini_client=MagicMock(),
                equivalence_gate=True,
                ecf_substitution=True,
            )

        self.assertEqual(mock_mark.call_count, 1)  # no ECF re-mark call at all
        cq = result.questions[0]
        self.assertEqual(cq.awarded_marks, 0)
        self.assertFalse(cq.point_verdicts[0].ecf_applied)
        self.assertFalse(cq.point_verdicts[1].ecf_applied)

    def test_ecf_remark_confidence_and_feedback_replace_first_pass(self) -> None:
        """Post-I7-review Critical 1: before this fix,
        ``merged_mark = mark.model_copy(update={"point_verdicts": ...})``
        replaced ONLY the verdicts -- ``mark.confidence``/``mark.feedback``
        stayed at the FIRST pass's values, so
        ``_build_ai_corrected_from_verdicts`` evaluated the review-confidence
        gate against a number the re-mark never reported. A re-mark the
        model was only 40% confident about shipped as whatever confidence
        band the FIRST (rejecting) pass happened to report, carrying
        feedback that describes the rejection rather than the award that
        actually happened. ECF awards are precisely the marks most in need
        of a human look. Fixed via
        ``confidence=min(mark.confidence, mark2.confidence)`` and taking
        ``mark2.feedback`` whenever the merge actually changed the outcome."""
        scheme = self._scheme()
        extracted = self._extracted("wrong value", "consistent working from wrong value")
        mark_1a_i = self._mark([self._pv("p1", "withheld")], confidence=0.95)
        mark_1a_ii_pass1 = self._mark(
            [self._pv("p1", "withheld")],
            confidence=0.95,
            feedback="FIRST PASS: no mark -- your value does not match the scheme",
        )
        mark_1a_ii_pass2 = self._mark(
            [self._pv("p1", "awarded", span="consistent")],
            confidence=0.40,  # the re-mark itself is UNSURE
            feedback="ECF RE-MARK: method consistent with your (incorrect) part (a) value",
        )

        with patch.object(
            correction_ai.AICorrector,
            "mark_question",
            side_effect=[mark_1a_i, mark_1a_ii_pass1, mark_1a_ii_pass2],
        ):
            result = correct_paper(
                mark_scheme=scheme,
                extracted_answers=extracted,
                gemini_client=MagicMock(),
                equivalence_gate=True,
                ecf_substitution=True,
            )

        cq_ii = next(q for q in result.questions if q.question_id == "1a_ii")
        self.assertEqual(cq_ii.awarded_marks, 1)
        self.assertTrue(cq_ii.point_verdicts[0].ecf_applied)
        # The re-mark's own (low) confidence governs -- never the first
        # pass's higher one -- so a genuinely uncertain ECF award is queued.
        self.assertEqual(cq_ii.confidence_score, 0.40)
        self.assertTrue(cq_ii.needs_teacher_review)
        # Feedback describes the award that actually happened, not the
        # first pass's rejection.
        self.assertEqual(
            cq_ii.feedback,
            "ECF RE-MARK: method consistent with your (incorrect) part (a) value",
        )

    def test_partial_merge_with_pass2_overclaim_is_still_queued(self) -> None:
        """Post-Critical-1-review Critical fix: ``feedback=mark2.feedback``
        is unconditional, but ``point_verdicts`` is merged SELECTIVELY --
        only points in ``eligible_ids`` take pass 2's verdict. Pass 2 is a
        full re-mark of the WHOLE question, so it can claim credit for an
        INELIGIBLE point too (here, an ungated ``p2``) while that point's
        verdict is correctly discarded from the merge. Chimera case: a leaf
        with one eligible point (``p1``, gated, resolvable) and one
        ineligible point (``p2``, ungated) where pass 2 claims BOTH are
        correct (2/2) but only ``p1``'s verdict survives the merge (1/2) --
        before the fix, the student would see pass 2's "2 marks awarded"
        feedback while receiving 1, unqueued, because
        ``merged_mark.awarded_marks`` stayed at pass 1's stale claim (0)
        and could never disagree with the derived total. Propagating
        ``mark2.awarded_marks`` into the merge lets the EXISTING
        coverage-mismatch check (``242c524f``) catch this without a second,
        parallel mechanism."""
        scheme = MarkScheme.model_validate(
            {
                "metadata": {
                    "subject": "Physics",
                    "subject_code": "0625",
                    "paper_number": 3,
                    "paper_variant": 2,
                    "session_month": "Oct/Nov",
                    "session_year": 2021,
                    "paper_type": "theory_extended",
                    "maximum_mark": 3,
                    "scheme_format": "point_based",
                },
                "questions": [
                    {
                        "id": "1",
                        "marks": 0,
                        "type": "calculation",
                        "parts": [
                            {
                                "id": "1a",
                                "marks": 0,
                                "type": "calculation",
                                "parent_id": "1",
                                "parts": [
                                    {
                                        "id": "1a_i",
                                        "marks": 1,
                                        "type": "calculation",
                                        "parent_id": "1a",
                                        "answer_points": [
                                            {
                                                "id": "p1",
                                                "point": "(a=) (v-u)/t in any form",
                                                "marks": 1,
                                                "math_mark_type": "M",
                                            }
                                        ],
                                    },
                                    {
                                        "id": "1a_ii",
                                        "marks": 2,
                                        "type": "calculation",
                                        "parent_id": "1a",
                                        "answer_points": [
                                            {
                                                "id": "p1",
                                                "point": "follow-through value",
                                                "marks": 1,
                                                "math_mark_type": "A",
                                                "condition": "ecf",
                                            },
                                            {
                                                "id": "p2",
                                                "point": "correct unit",
                                                "marks": 1,
                                                "math_mark_type": "A",
                                            },
                                        ],
                                    },
                                ],
                            },
                        ],
                    }
                ],
            }
        )
        extracted = self._extracted("wrong value", "some working covering both p1 and p2")
        mark_1a_i = self._mark([self._pv("p1", "withheld")])
        mark_1a_ii_pass1 = self._mark([self._pv("p1", "withheld"), self._pv("p2", "withheld")])
        from lemely.core.schemas import AIMarkResponse

        mark_1a_ii_pass2 = AIMarkResponse(
            awarded_marks=2,  # pass 2's OWN claim: both points now earn a mark
            confidence=0.90,
            matched_point_ids=["p1", "p2"],
            feedback=(
                "PASS 2: both the follow-through value AND the unit earn a mark - 2 marks awarded."
            ),
            point_verdicts=[
                self._pv("p1", "awarded", span="some working covering both p1 and p2"),
                self._pv("p2", "awarded", span="some working covering both p1 and p2"),
            ],
        )

        with patch.object(
            correction_ai.AICorrector,
            "mark_question",
            side_effect=[mark_1a_i, mark_1a_ii_pass1, mark_1a_ii_pass2],
        ):
            result = correct_paper(
                mark_scheme=scheme,
                extracted_answers=extracted,
                gemini_client=MagicMock(),
                equivalence_gate=True,
                ecf_substitution=True,
            )

        cq_ii = next(q for q in result.questions if q.question_id == "1a_ii")
        # p2 was never eligible (ungated) -- its verdict must stay "withheld"
        # from pass 1, NOT pass 2's "awarded", regardless of the fix.
        verdicts_by_id = {pv.point_id: pv for pv in cq_ii.point_verdicts}
        self.assertEqual(verdicts_by_id["p2"].verdict, "withheld")
        self.assertEqual(cq_ii.awarded_marks, 1)  # derived total: only p1 credited
        # The fix: pass 2's overclaim (2) now disagrees with the derived
        # total (1) and the EXISTING coverage check catches it.
        self.assertTrue(cq_ii.needs_teacher_review)
        self.assertIsNotNone(cq_ii.review_reason)

    def test_remark_transport_failure_is_swallowed_gracefully(self) -> None:
        """The ECF re-mark's exception handler must still absorb a genuine
        transport/API failure (an ``ExternalServiceError`` -- the class
        ``ai.mark_question`` actually raises for those) and fall back to
        the un-substituted result, exactly as before the NIT fix below."""
        from lemely.runtime.errors import ExternalServiceError

        scheme = self._scheme()
        extracted = self._extracted("wrong value", "consistent working from wrong value")
        mark_1a_i = self._mark([self._pv("p1", "withheld")])
        mark_1a_ii_pass1 = self._mark([self._pv("p1", "withheld")])

        with patch.object(
            correction_ai.AICorrector,
            "mark_question",
            side_effect=[mark_1a_i, mark_1a_ii_pass1, ExternalServiceError("Gemini unreachable")],
        ):
            result = correct_paper(
                mark_scheme=scheme,
                extracted_answers=extracted,
                gemini_client=MagicMock(),
                equivalence_gate=True,
                ecf_substitution=True,
            )

        cq_ii = next(q for q in result.questions if q.question_id == "1a_ii")
        self.assertEqual(cq_ii.awarded_marks, 0)  # un-substituted result, no crash
        self.assertFalse(cq_ii.point_verdicts[0].ecf_applied)

    def test_remark_programming_bug_is_not_swallowed(self) -> None:
        """Post-review NIT fix: the ECF re-mark's exception handler used to
        be a bare ``except Exception``, which also caught a PROGRAMMING bug
        in the surrounding code (or, as in the review that found this, a
        test's own ``StopIteration`` from an exhausted mock ``side_effect``
        list) and silently returned the un-substituted result -- identical
        to a genuine transport failure, proving nothing about which one
        actually happened. Narrowed to ``LemelyError`` (``ai.mark_question``'s
        actual failure-mode hierarchy); a plain ``RuntimeError`` -- standing
        in for any bug outside that hierarchy -- must now PROPAGATE instead
        of being absorbed."""
        scheme = self._scheme()
        extracted = self._extracted("wrong value", "consistent working from wrong value")
        mark_1a_i = self._mark([self._pv("p1", "withheld")])
        mark_1a_ii_pass1 = self._mark([self._pv("p1", "withheld")])

        with (
            patch.object(
                correction_ai.AICorrector,
                "mark_question",
                side_effect=[mark_1a_i, mark_1a_ii_pass1, RuntimeError("not a LemelyError")],
            ),
            self.assertRaises(RuntimeError),
        ):
            correct_paper(
                mark_scheme=scheme,
                extracted_answers=extracted,
                gemini_client=MagicMock(),
                equivalence_gate=True,
                ecf_substitution=True,
            )

    def test_no_version_bump(self) -> None:
        """D19: I6/I7/I8 share one VERSION bump, taken later at US-018's
        funded sweep -- this story bumps nothing."""
        from lemely.io.prompts.correction_ai import VERSION

        self.assertEqual(VERSION, "5")

    def test_schema_hash_unchanged(self) -> None:
        """I7 adds no schema field (``PointVerdict.ecf_applied`` and
        ``AnswerPoint.math_mark_type``/``required_with`` all already
        existed) -- the marking response schema's hash, measured on the
        UNSTRIPPED schema exactly as ``GeminiClient._params_fingerprint``
        computes it, must be unchanged from ``6ad23e79``.

        Pinned value updated to ``886c4232e7a7`` by the post-I6-review
        Critical B commit (which landed after I7): removing
        ``PointVerdict``'s class docstring (moved to a module comment) took
        its text out of ``model_json_schema()`` entirely, which moved this
        hash once, deliberately, for a documented reason -- see that
        commit's message and ``MarkingSchemaHashStableAcrossPythonOptimizeTests``
        below for why the OLD value silently differed by interpreter mode.
        I7 itself still adds no field and moves nothing on its own.
        """
        import hashlib
        import json as json_module

        from lemely.core.schemas import AIMarkResponse

        schema_json = json_module.dumps(AIMarkResponse.model_json_schema(), sort_keys=True)
        actual = hashlib.sha256(schema_json.encode()).hexdigest()[:12]
        self.assertEqual(actual, "886c4232e7a7")


class MarkingSchemaHashStableAcrossPythonOptimizeTests(unittest.TestCase):
    """Post-I6-review Critical B: ``PointVerdict`` used to carry a class
    DOCSTRING, and it is nested inside ``AIMarkResponse`` -- the
    ``response_schema`` for every marking call. Pydantic derives a model's
    JSON-Schema ``description`` from ``__doc__`` when nothing overrides it,
    and CPython's ``-O``/``-OO`` strips docstrings, so
    ``GeminiClient._params_fingerprint`` (which hashes the UNSTRIPPED
    ``model_json_schema()`` for the on-disk cache key) computed a DIFFERENT
    hash depending on the ambient ``PYTHONOPTIMIZE`` setting -- US-036's
    exact defect, reintroduced on the marking path.

    A test computed live in THIS process cannot catch that class of
    regression by itself (both sides would lose the docstring together
    under ``-OO``), so this runs the ACTUAL hash computation in two
    subprocesses -- one plain, one under the ``-OO`` flag.

    Post-review SHOULD-FIX 2 fix: an earlier version of this test claimed
    the flag argv (rather than the ``PYTHONOPTIMIZE`` env var) is what
    prevents the ambient environment from masking a regression. That claim
    was FALSE about the mechanism -- ``subprocess.run`` inherits
    ``os.environ`` by default, so under a poisoned ambient
    ``PYTHONOPTIMIZE=2`` the "plain" subprocess is ALSO optimized, and
    since ``886c4232e7a7`` (the post-fix value) happens to equal the
    STRIPPED (pre-fix, ``-OO``) hash, both assertions would pass on the
    PRE-fix code too -- the test was fully inert in that environment, not
    merely weakened. What actually protects local runs is
    ``tests/conftest.py``'s ``UsageError`` refusal under ``PYTHONOPTIMIZE``
    (``5669d5f8``) -- but that guards the PYTEST process only; these bare
    interpreter subprocesses are invisible to it. Fixed two ways: each
    subprocess now also reports ``sys.flags.optimize``, asserted directly
    in THIS (pytest) process, where an assertion cannot be stripped --
    proving what the subprocess actually ran under, not merely inferring
    it from which flag was passed; and the subprocess environment strips
    ``PYTHONOPTIMIZE`` explicitly as defence in depth. Matches US-036's own
    ``WireSchemaSurvivesPythonOptimizeTests``, whose in-script
    ``assert sys.flags.optimize == 2`` survives stripping precisely because
    a bare assert is only live at ``optimize == 0`` -- it fires exactly
    when the flag failed to apply; this test asserts the same fact from
    the outside instead, since its script's own bare assert would have the
    identical survive-only-when-it-should-fail problem.
    """

    _SCRIPT = (
        "import hashlib, json, sys\n"
        "from lemely.core.schemas import AIMarkResponse\n"
        "schema_json = json.dumps(AIMarkResponse.model_json_schema(), sort_keys=True)\n"
        "print(json.dumps({\n"
        "    'optimize': sys.flags.optimize,\n"
        "    'hash': hashlib.sha256(schema_json.encode()).hexdigest()[:12],\n"
        "}))\n"
    )

    def _run_under(self, *interpreter_flags: str) -> dict[str, object]:
        import json as json_module
        import os
        import subprocess
        import sys

        # Strip PYTHONOPTIMIZE from the child's environment as defence in
        # depth -- the REAL guard is the `optimize` assertion below, which
        # proves what the subprocess did rather than what the environment
        # did not do.
        env = dict(os.environ)
        env.pop("PYTHONOPTIMIZE", None)
        # This module's own hard-coded _SCRIPT, no shell, no untrusted input
        # -- same pattern as US-036's WireSchemaSurvivesPythonOptimizeTests.
        result = subprocess.run(  # noqa: S603
            [sys.executable, *interpreter_flags, "-c", self._SCRIPT],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
        return json_module.loads(result.stdout)  # type: ignore[no-any-return]

    def test_schema_hash_identical_under_dash_oo(self) -> None:
        normal = self._run_under()
        optimized = self._run_under("-OO")

        # Proves the subprocesses actually ran at the intended optimize
        # levels -- this is the guard, not the flag/env-var choice alone.
        self.assertEqual(normal["optimize"], 0)
        self.assertEqual(optimized["optimize"], 2)

        self.assertEqual(normal["hash"], optimized["hash"])
        self.assertEqual(normal["hash"], "886c4232e7a7")


_GOLDEN_DIR = Path(__file__).parent / "golden"


class PointVerdictGoldenFixtureTests(unittest.TestCase):
    """I6 (US-013) Important 7 -- acceptance 1 and acceptance 2, actually
    exercised against the three golden ``_theory_partial`` fixtures rather
    than only against ``Question.model_construct`` synthetics.

    Every prior I6 test (``PointVerdictBuildTests`` above) builds BOTH the
    question and the evidence spans itself, so ``_normalise_span`` had never
    run against a real transcribed answer. Here the ``Question`` comes from
    ``MarkScheme.model_validate_json`` parsing an actual fixture's
    ``mark_scheme.json`` (full pydantic validation, not ``model_construct``),
    and each ``PointVerdict.evidence_span`` is a real substring of the
    fixture's ``answers.json`` student answer -- deliberately re-cased and/or
    re-spaced from how it appears verbatim, so a passing assertion actually
    proves ``_normalise_span``'s whitespace-collapse and casefold survive
    real transcription noise, not just synthetic round-trips.

    Which points are "awarded" per leaf is read from each fixture's
    ``answers.json`` ``notes`` field (the only place the golden data records
    partial-credit attribution) and hard-coded per leaf below -- there is no
    machine-readable point-level ground truth format for this repo to load
    instead.
    """

    def _leaf(self, fixture: str, question_id: str) -> Question:
        mark_scheme = MarkScheme.model_validate_json(
            (_GOLDEN_DIR / fixture / "mark_scheme.json").read_text(encoding="utf-8")
        )
        question = mark_scheme.get_question_by_id(question_id)
        assert question is not None, f"{fixture}: no leaf {question_id!r}"
        return question

    def _ground_truth_awarded(self, fixture: str, question_id: str) -> int:
        answers = json.loads((_GOLDEN_DIR / fixture / "answers.json").read_text(encoding="utf-8"))
        return int(answers[question_id]["awarded_marks"])

    def _student_answer(self, fixture: str, question_id: str) -> str:
        answers = json.loads((_GOLDEN_DIR / fixture / "answers.json").read_text(encoding="utf-8"))
        return str(answers[question_id]["student_answer"])

    def _assert_row(
        self,
        fixture: str,
        question_id: str,
        verdicts_factory: Callable[[], list[PointVerdict]],
    ) -> None:
        """Load one golden row, mark it via the verdict path, and assert
        I6 acceptance 1 (sum of awarded points == awarded_marks, matching
        the fixture's own ground truth) plus acceptance 1's metamorphic
        shuffle property.
        """
        from lemely.core.schemas import AIMarkResponse
        from lemely.io.correction_ai import _build_ai_corrected

        question = self._leaf(fixture, question_id)
        student_answer = self._student_answer(fixture, question_id)
        expected_awarded = self._ground_truth_awarded(fixture, question_id)
        point_verdicts = verdicts_factory()

        mark = AIMarkResponse(
            awarded_marks=0,  # must be ignored -- the verdict path computes its own
            confidence=0.95,
            matched_point_ids=[],
            feedback="",
            point_verdicts=point_verdicts,
        )
        cq = _build_ai_corrected(question, student_answer, mark, equivalence_gate=True)

        # Acceptance 1, on a REAL golden row: sum(awarded verdicts' point
        # marks) == awarded_marks, and it matches the fixture's own
        # human-labelled ground truth.
        points_by_id = {p.id: p for p in question.answer_points}
        awarded_ids = [pv.point_id for pv in point_verdicts if pv.verdict == "awarded"]
        self.assertEqual(sum(points_by_id[pid].marks for pid in awarded_ids), cq.awarded_marks)
        self.assertEqual(cq.awarded_marks, expected_awarded)

        # Acceptance 1's metamorphic property: shuffling point_verdicts
        # order leaves marks unchanged.
        shuffled_mark = AIMarkResponse(
            awarded_marks=0,
            confidence=0.95,
            matched_point_ids=[],
            feedback="",
            point_verdicts=list(reversed(point_verdicts)),
        )
        shuffled_cq = _build_ai_corrected(
            question, student_answer, shuffled_mark, equivalence_gate=True
        )
        self.assertEqual(cq.awarded_marks, shuffled_cq.awarded_marks)
        self.assertEqual(set(cq.matched_point_ids), set(shuffled_cq.matched_point_ids))

        # Acceptance 2: every awarded point's evidence span is found in the
        # fixture's real answer text -- proven by the absence of a `no_span`
        # review trigger, since `_check_point_evidence` runs unconditionally
        # inside `_build_ai_corrected_from_verdicts`.
        from lemely.io.correction_ai import POINT_EVIDENCE_TRIGGER_MARKER

        self.assertNotIn(POINT_EVIDENCE_TRIGGER_MARKER, cq.review_reason or "")

    def test_0606_leaf_1_three_b_points_two_awarded(self) -> None:
        """0606_s23_qp_12_theory_partial, leaf "1": a=4 (hit), b=3/8 (hit),
        c=-2 (missed -- student wrote the sign-flipped "c = 2"). Real
        multi-point B-mark leaf; ground truth awarded_marks is 2."""

        def verdicts() -> list[PointVerdict]:
            return [
                PointVerdict(point_id="p1", verdict="awarded", evidence_span="A = 4"),
                PointVerdict(point_id="p2", verdict="awarded", evidence_span="b =   3/8"),
                PointVerdict(point_id="p3", verdict="withheld", evidence_span=""),
            ]

        self._assert_row("0606_s23_qp_12_theory_partial", "1", verdicts)

    def test_0625_leaf_1b_density_two_m_points_awarded_a_missed(self) -> None:
        """0625_s20_qp_31_theory_partial, leaf "1b": both M points hit
        (formula stated, correct substitution); the final A point missed
        (89 g/cm3 instead of 8.9 -- a decimal-place slip). Ground truth
        awarded_marks is 2. Evidence spans are deliberately re-cased and
        re-spaced from the verbatim answer text to exercise
        ``_normalise_span``'s casefold + whitespace-collapse against real
        transcription noise, not a synthetic round-trip."""

        def verdicts() -> list[PointVerdict]:
            return [
                PointVerdict(
                    point_id="p1", verdict="awarded", evidence_span="Density  =  Mass / Volume"
                ),
                PointVerdict(point_id="p2", verdict="awarded", evidence_span="148 / 16.6"),
                PointVerdict(point_id="p3", verdict="withheld", evidence_span=""),
            ]

        self._assert_row("0625_s20_qp_31_theory_partial", "1b", verdicts)

    def test_0580_leaf_1_single_point_full_marks(self) -> None:
        """0580_s23_qp_22_theory_partial, leaf "1": a single-point 1-mark
        leaf hit in full ("-5 - 8 = -13"). This excerpt fixture's
        mark_scheme.json only carries one full-mark point per leaf (its
        ``answers.json`` notes describe a real scheme's partial-credit
        structure that this excerpt does not reproduce) -- exercised here
        with a leading/trailing-whitespace evidence span to prove
        ``_normalise_span``'s ``.strip()`` against real fixture text."""

        def verdicts() -> list[PointVerdict]:
            return [PointVerdict(point_id="p1", verdict="awarded", evidence_span="  -13  ")]

        self._assert_row("0580_s23_qp_22_theory_partial", "1", verdicts)

    def test_0580_leaf_12b_single_point_full_marks_uppercase_span(self) -> None:
        """Same fixture, leaf "12b" -- 1 mark, hit in full. Evidence span
        deliberately uppercased against the real lowercase answer text to
        prove ``_normalise_span``'s ``.casefold()``."""

        def verdicts() -> list[PointVerdict]:
            return [
                PointVerdict(
                    point_id="p1",
                    verdict="awarded",
                    evidence_span="THE OTHER SOLUTION IS X = -8",
                )
            ]

        self._assert_row("0580_s23_qp_22_theory_partial", "12b", verdicts)
