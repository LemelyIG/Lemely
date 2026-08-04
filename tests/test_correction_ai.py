"""Unit tests for AICorrector and the hybrid correct_paper orchestrator."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
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
