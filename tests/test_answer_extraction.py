"""Unit tests for GeminiAnswerExtractor (GeminiClient mocked)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from lemely.core.loose_schemas import MarkScheme
from lemely.core.schemas import ExtractedAnswers
from lemely.io.answer_extraction import GeminiAnswerExtractor
from lemely.io.gemini import GeminiClient
from lemely.runtime.config import PathsSettings, load_settings


def _minimal_mcq_mark_scheme() -> MarkScheme:
    return MarkScheme.model_validate({
        "metadata": {
            "subject": "Physics", "subject_code": "0625",
            "paper_number": 1, "paper_variant": 2,
            "session_month": "May/June", "session_year": 2020,
            "paper_type": "mcq", "maximum_mark": 3, "scheme_format": "mcq",
        },
        "questions": [
            {"id": "1", "marks": 1, "type": "mcq", "mcq_answer": "A"},
            {"id": "2", "marks": 1, "type": "mcq", "mcq_answer": "B"},
            {"id": "3", "marks": 1, "type": "mcq", "mcq_answer": "C"},
        ],
    })


def _theory_mark_scheme() -> MarkScheme:
    return MarkScheme.model_validate({
        "metadata": {
            "subject": "Physics", "subject_code": "0625",
            "paper_number": 4, "paper_variant": 2,
            "session_month": "May/June", "session_year": 2020,
            "paper_type": "theory_extended", "maximum_mark": 5, "scheme_format": "point_based",
        },
        "questions": [
            {
                "id": "1(a)", "marks": 2, "type": "explanation",
                "question_command": "explain why",
                "answer_points": [
                    {"id": "p1", "point": "due to gravity", "marks": 1},
                    {"id": "p2", "point": "acting downward", "marks": 1},
                ],
            },
            {
                "id": "1(b)", "marks": 3, "type": "calculation",
                "question_command": "calculate the speed",
                "answer_points": [
                    {"id": "p1", "point": "v = d/t", "marks": 1, "math_mark_type": "M"},
                    {"id": "p2", "point": "v = 100/5", "marks": 1, "math_mark_type": "M"},
                    {"id": "p3", "point": "20 m/s", "marks": 1, "math_mark_type": "A"},
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


def _client_with_response(tmp: str, body: dict) -> GeminiClient:
    mock_genai = MagicMock()
    resp = MagicMock(
        text=json.dumps(body),
        candidates=[MagicMock(finish_reason=MagicMock(__str__=lambda s: "STOP"))],
        usage_metadata=MagicMock(prompt_token_count=5, candidates_token_count=30),
    )
    mock_genai.models.generate_content.return_value = resp
    mock_genai.files.upload.return_value = MagicMock()
    with _IsolatedEnv():
        settings = load_settings(toml_path=None, cwd=Path(tmp))
    settings = settings.model_copy(
        update={"paths": PathsSettings(cache_dir=Path(tmp) / ".cache")}
    )
    return GeminiClient(settings, _genai_client=mock_genai)


class AnswerExtractorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.scan = Path(self.tmp) / "scan.png"
        self.scan.write_bytes(b"\x89PNG\r\n\x1a\n")

    def test_mcq_extraction(self) -> None:
        body = {"answers": [
            {"question_id": "1", "answer": "A", "confidence": 0.99, "source_region": None},
            {"question_id": "2", "answer": "B", "confidence": 0.95, "source_region": None},
            {"question_id": "3", "answer": "C", "confidence": 0.85, "source_region": None},
        ]}
        extractor = GeminiAnswerExtractor(_client_with_response(self.tmp, body))
        result = extractor(scan_path=self.scan, mark_scheme=_minimal_mcq_mark_scheme())
        self.assertIsInstance(result, ExtractedAnswers)
        self.assertEqual(len(result.answers), 3)
        self.assertEqual(result.answers[0].answer, "A")
        self.assertIn("0625", result.paper_id)

    def test_theory_extraction_handles_freetext(self) -> None:
        body = {"answers": [
            {"question_id": "1(a)", "answer": "because gravity pulls it down", "confidence": 0.8, "source_region": None},
            {"question_id": "1(b)", "answer": "20 m/s using v=d/t", "confidence": 0.9, "source_region": None},
        ]}
        extractor = GeminiAnswerExtractor(_client_with_response(self.tmp, body))
        result = extractor(scan_path=self.scan, mark_scheme=_theory_mark_scheme())
        self.assertEqual(len(result.answers), 2)
        self.assertIn("gravity", result.answers[0].answer)
        self.assertIn("20 m/s", result.answers[1].answer)

    def test_working_out_round_trips_through_extractor(self) -> None:
        body = {"answers": [
            {
                "question_id": "1(b)",
                "answer": "20 m/s",
                "confidence": 0.9,
                "source_region": "page 1, q1b",
                "working_out": "v = d/t\nv = 100/5\nv = 20 m/s",
            },
        ]}
        extractor = GeminiAnswerExtractor(_client_with_response(self.tmp, body))
        result = extractor(scan_path=self.scan, mark_scheme=_theory_mark_scheme())
        self.assertEqual(len(result.answers), 1)
        self.assertEqual(result.answers[0].working_out, "v = d/t\nv = 100/5\nv = 20 m/s")

    def test_mcq_working_out_is_none(self) -> None:
        body = {"answers": [
            {"question_id": "1", "answer": "A", "confidence": 0.99, "source_region": None, "working_out": None},
        ]}
        extractor = GeminiAnswerExtractor(_client_with_response(self.tmp, body))
        result = extractor(scan_path=self.scan, mark_scheme=_minimal_mcq_mark_scheme())
        self.assertIsNone(result.answers[0].working_out)


class IDNormalizationTests(unittest.TestCase):

    def test_canonical_id_strips_spaces_and_brackets(self):
        from lemely.io.answer_extraction import _canonical_id
        self.assertEqual(_canonical_id("1 a i"), _canonical_id("1(a)(i)"))

    def test_canonical_id_strips_brackets_only(self):
        from lemely.io.answer_extraction import _canonical_id
        self.assertEqual(_canonical_id("1(a)"), _canonical_id("1a"))

    def test_canonical_id_case_insensitive(self):
        from lemely.io.answer_extraction import _canonical_id
        self.assertEqual(_canonical_id("1(A)"), _canonical_id("1(a)"))

    def test_normalize_matches_exact_id(self):
        from lemely.io.answer_extraction import normalize_extracted_answers
        from lemely.core.schemas import ExtractedAnswer, ExtractedAnswers
        manifest_ids = ["1", "1(a)", "1(b)"]
        extracted = ExtractedAnswers(
            paper_id="test", source_scan="scan.pdf",
            answers=[
                ExtractedAnswer(question_id="1",    answer="A", confidence=0.9),
                ExtractedAnswer(question_id="1(a)", answer="B", confidence=0.9),
                ExtractedAnswer(question_id="1(b)", answer="C", confidence=0.9),
            ],
        )
        normalized = normalize_extracted_answers(extracted, manifest_ids)
        ids = {a.question_id for a in normalized.answers}
        self.assertEqual(ids, {"1", "1(a)", "1(b)"})

    def test_normalize_corrects_space_drift(self):
        from lemely.io.answer_extraction import normalize_extracted_answers
        from lemely.core.schemas import ExtractedAnswer, ExtractedAnswers
        manifest_ids = ["1(a)(i)"]
        extracted = ExtractedAnswers(
            paper_id="test", source_scan="scan.pdf",
            answers=[ExtractedAnswer(question_id="1 a i", answer="X", confidence=0.7)],
        )
        normalized = normalize_extracted_answers(extracted, manifest_ids)
        self.assertEqual(normalized.answers[0].question_id, "1(a)(i)")

    def test_normalize_positional_fallback(self):
        from lemely.io.answer_extraction import normalize_extracted_answers
        from lemely.core.schemas import ExtractedAnswer, ExtractedAnswers
        manifest_ids = ["1(a)(i)"]
        extracted = ExtractedAnswers(
            paper_id="test", source_scan="scan.pdf",
            answers=[
                ExtractedAnswer(question_id="completely_unrecognised", answer="Y", confidence=0.6),
            ],
        )
        normalized = normalize_extracted_answers(extracted, manifest_ids)
        # Positional fallback: first extracted answer → first manifest ID
        self.assertEqual(normalized.answers[0].question_id, "1(a)(i)")
