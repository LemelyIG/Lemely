"""Tests for Phase 6: PlagiarismChecker and AIContentDetector."""

from __future__ import annotations

from unittest.mock import MagicMock

from lemely.core.integrity_schemas import IntegrityFinding
from lemely.core.plagiarism import PlagiarismChecker
from lemely.io.integrity import AIContentDetector


class TestPlagiarismChecker:
    def test_verbatim_copy_is_flagged(self) -> None:
        checker = PlagiarismChecker(threshold=0.85)
        expected = "The velocity of a wave is equal to its frequency multiplied by its wavelength."
        result = checker.check("q1", expected, expected)
        assert result.flagged is True
        assert result.score >= 0.85

    def test_paraphrase_not_flagged(self) -> None:
        checker = PlagiarismChecker(threshold=0.85)
        expected = "Velocity equals frequency times wavelength."
        student = "The speed at which a wave travels is determined by how often it oscillates per second times the distance between each cycle."
        result = checker.check("q1", student, expected)
        assert result.flagged is False
        assert result.score < 0.85

    def test_returns_plagiarism_kind(self) -> None:
        checker = PlagiarismChecker()
        result = checker.check("q1", "same text", "same text")
        assert result.kind == "plagiarism"

    def test_question_id_in_finding(self) -> None:
        checker = PlagiarismChecker()
        result = checker.check("q42", "answer", "expected")
        assert result.question_id == "q42"

    def test_no_gemini_client_used(self) -> None:
        mock_client = MagicMock()
        checker = PlagiarismChecker()
        checker.check("q1", "text", "text")
        mock_client.generate_structured.assert_not_called()

    def test_score_is_float_between_0_and_1(self) -> None:
        checker = PlagiarismChecker()
        result = checker.check("q1", "some answer here", "some answer here")
        assert 0.0 <= result.score <= 1.0

    def test_rationale_is_non_empty(self) -> None:
        checker = PlagiarismChecker()
        result = checker.check("q1", "text", "text")
        assert result.rationale


class TestAIContentDetector:
    def test_returns_integrity_finding(self) -> None:
        finding = IntegrityFinding(
            question_id="q1",
            kind="ai_generated",
            flagged=True,
            score=0.92,
            rationale="Unnaturally fluent prose.",
        )
        mock_client = MagicMock()
        mock_client.generate_structured.return_value = finding

        detector = AIContentDetector(mock_client)
        result = detector.detect(
            "q1",
            "What is refraction?",
            "Refraction is the bending of light.",
            ["Award 1 mark for bending of light"],
        )

        assert result.kind == "ai_generated"
        assert isinstance(result.score, float)
        assert result.rationale

    def test_uses_integrity_task_tag(self) -> None:
        mock_client = MagicMock()
        mock_client.generate_structured.return_value = IntegrityFinding(
            question_id="q1",
            kind="ai_generated",
            flagged=False,
            score=0.3,
            rationale="OK",
        )
        AIContentDetector(mock_client).detect("q1", "Q", "A", [])
        call_kwargs = mock_client.generate_structured.call_args.kwargs
        assert call_kwargs["task_tag"] == "integrity"
