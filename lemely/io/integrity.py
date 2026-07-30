"""AI-based content detection — Gemini classifier for AI-generated answers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from lemely.core.integrity_schemas import IntegrityFinding
from lemely.io.prompts.integrity import (
    AI_DETECTION_SYSTEM_PROMPT,
    VERSION,
    build_ai_detection_user_prompt,
)

if TYPE_CHECKING:
    from lemely.io.gemini import GeminiClient


class AIContentDetector:
    """Classify whether a student answer is AI-generated using Gemini.

    Uses task_tag='integrity'. Threshold is checked by the caller (IntegritySettings).
    """

    def __init__(self, gemini_client: GeminiClient) -> None:
        self._client = gemini_client

    def detect(
        self,
        question_id: str,
        question_text: str,
        student_answer: str,
        mark_scheme_points: list[str],
    ) -> IntegrityFinding:
        """Classify one answer for AI-generation.

        Args:
            question_id: Identifier used in the returned finding.
            question_text: The exam question text.
            student_answer: The student's answer to assess.
            mark_scheme_points: Mark scheme bullet points for context.

        Returns:
            IntegrityFinding with kind='ai_generated'.
        """
        extra_cache_key = f"{question_id}:{hash(student_answer)}"
        return self._client.generate_structured(
            system_prompt=AI_DETECTION_SYSTEM_PROMPT,
            user_prompt=build_ai_detection_user_prompt(
                question_id, question_text, student_answer, mark_scheme_points
            ),
            response_schema=IntegrityFinding,
            prompt_version=VERSION,
            task_tag="integrity",
            extra_cache_key=extra_cache_key,
        )
