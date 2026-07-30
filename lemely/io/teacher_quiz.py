"""Teacher quiz builder — selects existing questions, tops up via QuestionGenerator."""

from __future__ import annotations

from typing import TYPE_CHECKING

from lemely.core.generation import GeneratedQuestion, GeneratedQuiz

if TYPE_CHECKING:
    from lemely.core.schemas import WeaknessReport
    from lemely.io.question_generation import QuestionGenerator


class TeacherQuizBuilder:
    """Build a quiz from existing parsed questions, generating new ones for any shortfall.

    Selection-before-generation policy:
      1. Select from existing_questions (filtered by topics if provided).
      2. If count > len(existing_questions), generate the remainder via QuestionGenerator.
      3. Total questions never exceeds count.
    """

    def __init__(
        self,
        generator: QuestionGenerator,
        existing_questions: list[GeneratedQuestion] | None = None,
    ) -> None:
        self._generator = generator
        self._existing = existing_questions or []

    def build(
        self,
        subject_code: str,
        weaknesses: WeaknessReport,
        *,
        count: int,
        topics: list[str] | None = None,
    ) -> GeneratedQuiz:
        """Build a quiz up to count questions.

        Args:
            subject_code: CAIE subject code (e.g. '0625').
            weaknesses: Source of weak topics for generation shortfall.
            count: Target number of questions.
            topics: Optional topic filter for existing question selection.

        Returns:
            GeneratedQuiz with min(count, available) questions.
        """
        # Step 1: Select from existing
        pool = self._existing
        if topics:
            topic_set = {t.lower() for t in topics}
            pool = [q for q in pool if q.topic.lower() in topic_set]
        selected = pool[:count]

        shortfall = count - len(selected)

        # Step 2: Generate remainder if needed
        generated: list[GeneratedQuestion] = []
        if shortfall > 0 and weaknesses.weak_areas:
            quiz = self._generator.generate(weaknesses, subject_code=subject_code, count=shortfall)
            generated = quiz.questions

        return GeneratedQuiz(
            subject_code=subject_code,
            questions=selected + generated,
        )
