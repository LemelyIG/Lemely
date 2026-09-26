"""Unit tests for lemely.io.second_read (I3, US-010 label-free half).

Covers ONLY the label-free acceptance criteria: both variants produce
`extraction_agreement` in [0, 1] (I3 acceptance 1), and the second read
never returns the primary's cached reply (SD21 / I3 acceptance 4). AUROC
per variant and the adopt-if->=0.70 selection rule are OUT of scope -- they
need Phase-A transcription labels (US-008) that do not exist yet.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from lemely.core.schemas import ExtractedAnswer
from lemely.io.gemini import GeminiClient
from lemely.io.second_read import (
    REREAD_AGREEMENT_THRESHOLD,
    CrossModelSecondReader,
    StructuralSecondReader,
    build_second_reader,
    compute_agreement,
    text_agreement,
)
from lemely.runtime.config import GeminiSettings, PathsSettings, load_settings


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


def _resp(body: dict) -> MagicMock:
    return MagicMock(
        text=json.dumps(body),
        candidates=[MagicMock(finish_reason=MagicMock(__str__=lambda s: "STOP"))],
        usage_metadata=MagicMock(prompt_token_count=5, candidates_token_count=30),
    )


def _client(tmp: str, mock_genai: MagicMock) -> GeminiClient:
    mock_genai.files.upload.return_value = MagicMock()
    with _IsolatedEnv():
        settings = load_settings(toml_path=None, cwd=Path(tmp))
    settings = settings.model_copy(
        update={
            "paths": PathsSettings(
                cache_dir=Path(tmp) / ".cache",
                output_dir=Path(tmp) / "outputs",
            )
        }
    )
    return GeminiClient(settings, _genai_client=mock_genai)


def _mark_scheme():
    from lemely.core.loose_schemas import MarkScheme

    return MarkScheme.model_validate(
        {
            "metadata": {
                "subject": "Physics",
                "subject_code": "0625",
                "paper_number": 1,
                "paper_variant": 2,
                "session_month": "May/June",
                "session_year": 2020,
                "paper_type": "mcq",
                "maximum_mark": 1,
                "scheme_format": "mcq",
            },
            "questions": [{"id": "1", "marks": 1, "type": "mcq", "mcq_answer": "A"}],
        }
    )


class TextAgreementTests(unittest.TestCase):
    def test_identical_strings_score_one(self) -> None:
        self.assertEqual(text_agreement("42 m/s", "42 m/s"), 1.0)

    def test_identical_after_whitespace_casing_differences(self) -> None:
        self.assertEqual(text_agreement("  42 M/S ", "42 m/s"), 1.0)

    def test_completely_different_strings_score_low(self) -> None:
        self.assertLess(text_agreement("42 m/s", "banana"), 0.3)

    def test_result_is_bounded_zero_one(self) -> None:
        self.assertGreaterEqual(text_agreement("", "anything"), 0.0)
        self.assertLessEqual(text_agreement("foo", "foobar"), 1.0)


class BuildSecondReaderTests(unittest.TestCase):
    def test_none_variant_returns_none(self) -> None:
        client = MagicMock()
        settings = GeminiSettings(second_reader="none")
        self.assertIsNone(build_second_reader(client, settings))

    def test_cross_model_variant_uses_second_read_model(self) -> None:
        client = MagicMock()
        settings = GeminiSettings(second_reader="cross_model", second_read_model="gemini-3.8-flash")
        reader = build_second_reader(client, settings)
        self.assertIsInstance(reader, CrossModelSecondReader)

    def test_structural_variant_uses_extraction_model(self) -> None:
        client = MagicMock()
        settings = GeminiSettings(second_reader="structural")
        reader = build_second_reader(client, settings)
        self.assertIsInstance(reader, StructuralSecondReader)


class ComputeAgreementTests(unittest.TestCase):
    def test_matches_by_question_id_and_bounds_hold(self) -> None:
        primary = [
            ExtractedAnswer(question_id="1", answer="A", confidence=0.9),
            ExtractedAnswer(question_id="2", answer="19.6 N", confidence=0.9),
        ]
        second_read = {"1": "A", "2": "totally different text"}
        agreements = compute_agreement(primary, second_read)
        self.assertEqual(agreements["1"], 1.0)
        self.assertGreaterEqual(agreements["2"], 0.0)
        self.assertLess(agreements["2"], REREAD_AGREEMENT_THRESHOLD)

    def test_question_id_absent_from_second_read_is_left_out(self) -> None:
        primary = [ExtractedAnswer(question_id="1", answer="A", confidence=0.9)]
        agreements = compute_agreement(primary, second_read={})
        self.assertEqual(agreements, {})


class SecondReadCacheTests(unittest.TestCase):
    """SD21 (I3 acceptance 4): the second read never returns the primary's
    cached reply -- extra_cache_key differs, so a cache hit on the primary
    does not satisfy the second read."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()

    def test_cross_model_extra_cache_key_differs_from_primary(self) -> None:
        mock_genai = MagicMock()
        primary_body = {"answers": [{"question_id": "1", "answer": "A"}]}
        second_body = {"answers": [{"question_id": "1", "answer": "Z"}]}
        mock_genai.models.generate_content.side_effect = [_resp(primary_body), _resp(second_body)]
        client = _client(self.tmp, mock_genai)
        mark_scheme = _mark_scheme()
        image_parts = [b"page0"]

        # Warm a cache entry keyed like the PRIMARY extraction call would be:
        # same extra_cache_key base, no model override (falls back to the
        # client's global default), a plain prompt distinct from either
        # second-read prompt.
        from lemely.io.prompts.answer_extraction import VERSION

        class _PrimaryOutput(__import__("pydantic").BaseModel):
            answers: list[dict]

        client.generate_structured(
            system_prompt="primary prompt",
            user_prompt="primary user prompt",
            image_parts=image_parts,
            response_schema=_PrimaryOutput,
            prompt_version=VERSION,
            extra_cache_key="manifest123",
            task_tag="extraction",
        )
        self.assertEqual(mock_genai.models.generate_content.call_count, 1)

        reader = CrossModelSecondReader(client, model="gemini-3.8-flash")
        result = reader.read(mark_scheme, image_parts, extra_cache_key="manifest123")

        # A fresh live call was made -- the primary's cache entry did NOT
        # satisfy the second read.
        self.assertEqual(mock_genai.models.generate_content.call_count, 2)
        self.assertEqual(result, {"1": "Z"})

        # Re-issuing the EXACT primary call again is a cache hit (no third
        # live call) -- the primary's own cache entry is intact and
        # untouched by the second read.
        client.generate_structured(
            system_prompt="primary prompt",
            user_prompt="primary user prompt",
            image_parts=image_parts,
            response_schema=_PrimaryOutput,
            prompt_version=VERSION,
            extra_cache_key="manifest123",
            task_tag="extraction",
        )
        self.assertEqual(mock_genai.models.generate_content.call_count, 2)

    def test_structural_extra_cache_key_differs_from_primary(self) -> None:
        mock_genai = MagicMock()
        primary_body = {"answers": [{"question_id": "1", "answer": "A"}]}
        second_body = {"answers": [{"question_id": "1", "answer": "Q"}]}
        mock_genai.models.generate_content.side_effect = [_resp(primary_body), _resp(second_body)]
        client = _client(self.tmp, mock_genai)
        mark_scheme = _mark_scheme()
        image_parts = [b"page0"]

        from lemely.io.prompts.answer_extraction import VERSION

        class _PrimaryOutput(__import__("pydantic").BaseModel):
            answers: list[dict]

        client.generate_structured(
            system_prompt="primary prompt",
            user_prompt="primary user prompt",
            image_parts=image_parts,
            response_schema=_PrimaryOutput,
            prompt_version=VERSION,
            extra_cache_key="manifest123",
            task_tag="extraction",
        )
        self.assertEqual(mock_genai.models.generate_content.call_count, 1)

        gemini_settings = client._settings.gemini
        reader = StructuralSecondReader(
            client, model=gemini_settings.extraction_model or gemini_settings.model
        )
        result = reader.read(mark_scheme, image_parts, extra_cache_key="manifest123")

        self.assertEqual(mock_genai.models.generate_content.call_count, 2)
        self.assertEqual(result, {"1": "Q"})


class RereadThresholdTests(unittest.TestCase):
    def test_threshold_matches_plan_value(self) -> None:
        """Plan: 'Re-read (I1) fires on agreement < 0.8.'"""
        self.assertEqual(REREAD_AGREEMENT_THRESHOLD, 0.8)


if __name__ == "__main__":
    unittest.main()
