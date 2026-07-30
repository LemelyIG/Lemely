"""Tests for Phase 4: QuestionGenerator and generate-quiz --use-ai CLI flag."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from lemely.app.cli import cli
from lemely.core.generation import GeneratedQuestion, GeneratedQuiz
from lemely.core.schemas import WeakArea, WeaknessReport
from lemely.io.question_generation import QuestionGenerator


def _weakness(topics: list[str]) -> WeaknessReport:
    return WeaknessReport(
        weak_areas=[
            WeakArea(topic=t, lost_marks=3, maximum_marks=10, accuracy=0.7, question_ids=[f"q{i}"])
            for i, t in enumerate(topics)
        ]
    )


def _generated_question(topic: str) -> GeneratedQuestion:
    return GeneratedQuestion(
        topic=topic,
        difficulty="standard",
        prompt=f"Explain {topic}.",
        model_answer=f"Model answer for {topic}.",
        mark_scheme_points=[f"Point 1 for {topic}", f"Point 2 for {topic}"],
        total_marks=2,
    )


class TestQuestionGeneratorUnit:
    def test_calls_generate_structured_with_generation_tag(self) -> None:
        mock_client = MagicMock()
        quiz = GeneratedQuiz(
            subject_code="0625",
            questions=[_generated_question("Waves")],
        )
        mock_client.generate_structured.return_value = quiz

        generator = QuestionGenerator(mock_client)
        result = generator.generate(_weakness(["Waves"]), subject_code="0625", count=1)

        assert isinstance(result, GeneratedQuiz)
        mock_client.generate_structured.assert_called_once()
        call_kwargs = mock_client.generate_structured.call_args.kwargs
        assert call_kwargs["task_tag"] == "generation"

    def test_caps_at_min_count_len_weak_areas(self) -> None:
        mock_client = MagicMock()
        mock_client.generate_structured.return_value = GeneratedQuiz(
            subject_code="0625",
            questions=[_generated_question("Waves"), _generated_question("Optics")],
        )
        generator = QuestionGenerator(mock_client)
        # count=5 but only 2 weak areas
        generator.generate(_weakness(["Waves", "Optics"]), subject_code="0625", count=5)
        call_kwargs = mock_client.generate_structured.call_args.kwargs
        # user_prompt should mention 2 questions not 5
        assert "2" in call_kwargs["user_prompt"]

    def test_questions_have_model_answer_and_points(self) -> None:
        mock_client = MagicMock()
        questions = [_generated_question("Waves"), _generated_question("Forces")]
        mock_client.generate_structured.return_value = GeneratedQuiz(
            subject_code="0625", questions=questions
        )
        generator = QuestionGenerator(mock_client)
        result = generator.generate(_weakness(["Waves", "Forces"]), subject_code="0625")
        for q in result.questions:
            assert q.model_answer
            assert q.mark_scheme_points


class TestGenerateQuizCLI:
    def test_default_path_no_gemini_client(self, tmp_path) -> None:
        import json

        weakness_file = tmp_path / "weakness.json"
        weakness_file.write_text(
            json.dumps(
                {
                    "weak_areas": [
                        {
                            "topic": "Waves",
                            "lost_marks": 3,
                            "maximum_marks": 10,
                            "accuracy": 0.7,
                            "question_ids": ["q1"],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        with patch("lemely.io.gemini.GeminiClient") as mock_gc:
            runner = CliRunner()
            result = runner.invoke(cli, ["generate-quiz", str(weakness_file)])
            mock_gc.assert_not_called()
        assert result.exit_code == 0

    def test_use_ai_without_subject_code_fails(self, tmp_path) -> None:
        import json

        weakness_file = tmp_path / "weakness.json"
        weakness_file.write_text(json.dumps({"weak_areas": []}), encoding="utf-8")
        runner = CliRunner()
        result = runner.invoke(cli, ["generate-quiz", str(weakness_file), "--use-ai"])
        assert result.exit_code == 2
        assert "subject-code" in result.output.lower() or "subject_code" in result.output.lower()
