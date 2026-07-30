"""AI-powered practice question generator using weak areas as input."""

from __future__ import annotations

from typing import TYPE_CHECKING

from lemely.core.generation import GeneratedQuiz
from lemely.io.prompts.question_generation import (
    VERSION,
    build_question_gen_system_prompt,
    build_question_gen_user_prompt,
)

if TYPE_CHECKING:
    from lemely.core.schemas import WeaknessReport
    from lemely.io.gemini import GeminiClient


class QuestionGenerator:
    """Generate targeted practice questions from a WeaknessReport via Gemini.

    One question is generated per weak area, capped at min(count, len(weak_areas)).
    extra_cache_key includes subject_code + top topic names for effective caching.
    """

    def __init__(self, gemini_client: GeminiClient) -> None:
        self._client = gemini_client

    def generate(
        self,
        weaknesses: WeaknessReport,
        *,
        subject_code: str,
        count: int = 5,
    ) -> GeneratedQuiz:
        """Generate practice questions for the top weak areas.

        Args:
            weaknesses: WeaknessReport with weak_areas to target.
            subject_code: CAIE subject code (e.g. '0625').
            count: Maximum number of questions to generate.

        Returns:
            GeneratedQuiz with min(count, len(weak_areas)) questions.
        """
        areas = weaknesses.weak_areas[:count]
        top_topics = ",".join(a.topic for a in areas[:5])
        extra_cache_key = f"{subject_code}:{top_topics}"

        return self._client.generate_structured(
            system_prompt=build_question_gen_system_prompt(subject_code),
            user_prompt=build_question_gen_user_prompt(areas, count=len(areas)),
            response_schema=GeneratedQuiz,
            prompt_version=VERSION,
            task_tag="generation",
            extra_cache_key=extra_cache_key,
        )
