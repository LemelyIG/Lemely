"""Unit tests for AICorrector and the hybrid correct_paper orchestrator."""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import unittest
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from lemely.core.loose_schemas import MarkScheme
from lemely.core.schemas import (
    ExtractedAnswer,
    ExtractedAnswers,
)
from lemely.io.correction_ai import correct_paper
from lemely.io.gemini import GeminiClient
from lemely.runtime.config import PathsSettings, load_settings
from lemely.runtime.errors import ConfigError
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
    s = s.model_copy(update={"paths": PathsSettings(cache_dir=Path(tmp) / ".cache")})
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
    def _make_question(self):
        from lemely.core.loose_schemas import Question, QuestionType

        return Question.model_construct(
            id="2",
            marks=2,
            type=QuestionType.EXPLANATION,
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

    def test_coherent_match_with_no_answer_points_is_untouched(self):
        """A mark scheme with no discrete answer_points (levels-based, or a
        model_construct fixture like ThresholdTests') has nothing to
        reconcile matched_point_ids against, so the coherence check must not
        fire — preserves ThresholdTests' pre-#40 behaviour."""
        from lemely.io.correction_ai import _build_ai_corrected

        cq = _build_ai_corrected(
            self._make_question(answer_points=[]),
            "answer",
            self._make_mark(1, [], confidence=1.0),
        )
        self.assertFalse(cq.needs_teacher_review)


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
                    "paths": PathsSettings(cache_dir=Path(tmp) / ".cache"),
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
