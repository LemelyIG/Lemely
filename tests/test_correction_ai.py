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
    ConfidenceBand,
    CorrectedQuestion,
    CorrectionResult,
    ExtractedAnswer,
    ExtractedAnswers,
)
from lemely.io.correction_ai import AICorrector, correct_paper
from lemely.io.gemini import GeminiClient
from lemely.runtime.config import PathsSettings, load_settings
from lemely.runtime.errors import ConfigError


def _hybrid_paper_mark_scheme() -> MarkScheme:
    """Two questions: one MCQ + one short theory question."""
    return MarkScheme.model_validate({
        "metadata": {
            "subject": "Physics", "subject_code": "0625",
            "paper_number": 4, "paper_variant": 2,
            "session_month": "May/June", "session_year": 2020,
            "paper_type": "theory_extended", "maximum_mark": 3, "scheme_format": "mixed",
        },
        "questions": [
            {"id": "1", "marks": 1, "type": "mcq", "mcq_answer": "A"},
            {
                "id": "2", "marks": 2, "type": "explanation",
                "question_command": "explain why",
                "answer_points": [
                    {"id": "p1", "point": "gravity acts on it", "marks": 1},
                    {"id": "p2", "point": "no air resistance", "marks": 1},
                ],
            },
        ],
    })


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
            paper_id="test", source_scan="scan.png",
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
