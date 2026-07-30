"""Tests for Phase 6: TeacherQuizBuilder selection-before-generation logic."""

from __future__ import annotations

from unittest.mock import MagicMock

from lemely.core.generation import GeneratedQuestion, GeneratedQuiz
from lemely.core.schemas import WeakArea, WeaknessReport
from lemely.io.question_generation import QuestionGenerator
from lemely.io.teacher_quiz import TeacherQuizBuilder


def _question(topic: str) -> GeneratedQuestion:
    return GeneratedQuestion(
        topic=topic,
        difficulty="standard",
        prompt=f"Q: {topic}",
        model_answer=f"A: {topic}",
        mark_scheme_points=["p1"],
        total_marks=1,
    )


def _weakness(topics: list[str]) -> WeaknessReport:
    return WeaknessReport(
        weak_areas=[
            WeakArea(topic=t, lost_marks=2, maximum_marks=5, accuracy=0.6, question_ids=[])
            for t in topics
        ]
    )


class TestTeacherQuizBuilder:
    def test_selects_existing_before_generating(self) -> None:
        existing = [_question("Waves"), _question("Forces"), _question("Optics")]
        mock_gen = MagicMock(spec=QuestionGenerator)

        builder = TeacherQuizBuilder(mock_gen, existing_questions=existing)
        result = builder.build("0625", _weakness(["Energy"]), count=3)

        assert len(result.questions) == 3
        mock_gen.generate.assert_not_called()

    def test_generates_shortfall(self) -> None:
        existing = [_question("Waves"), _question("Forces"), _question("Optics")]
        generated = [_question("Energy"), _question("Circuits")]

        mock_gen = MagicMock(spec=QuestionGenerator)
        mock_gen.generate.return_value = GeneratedQuiz(subject_code="0625", questions=generated)

        builder = TeacherQuizBuilder(mock_gen, existing_questions=existing)
        result = builder.build("0625", _weakness(["Energy", "Circuits"]), count=5)

        assert len(result.questions) == 5
        mock_gen.generate.assert_called_once()
        # Generator called with shortfall=2
        call_kwargs = mock_gen.generate.call_args.kwargs
        assert call_kwargs["count"] == 2

    def test_topic_filter_applied(self) -> None:
        existing = [_question("Waves"), _question("Forces"), _question("Optics")]
        mock_gen = MagicMock(spec=QuestionGenerator)
        mock_gen.generate.return_value = GeneratedQuiz(subject_code="0625", questions=[])

        builder = TeacherQuizBuilder(mock_gen, existing_questions=existing)
        result = builder.build("0625", _weakness(["Waves"]), count=2, topics=["Waves"])
        topics = [q.topic for q in result.questions]
        assert all(t == "Waves" for t in topics)

    def test_total_never_exceeds_count(self) -> None:
        existing = [_question(f"T{i}") for i in range(10)]
        mock_gen = MagicMock(spec=QuestionGenerator)

        builder = TeacherQuizBuilder(mock_gen, existing_questions=existing)
        result = builder.build("0625", _weakness([]), count=3)

        assert len(result.questions) == 3
        mock_gen.generate.assert_not_called()
