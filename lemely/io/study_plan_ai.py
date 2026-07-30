"""AI narrative layer for study plans — wraps the pure scheduler output."""

from __future__ import annotations

from typing import TYPE_CHECKING

from lemely.core.study import StudyPlan
from lemely.io.prompts.study_plan import (
    VERSION,
    build_study_plan_system_prompt,
    build_study_plan_user_prompt,
)

if TYPE_CHECKING:
    from lemely.io.gemini import GeminiClient


class _NarratedStudyPlan(StudyPlan):
    """Internal model to receive the AI-narrated plan with narrative filled in."""


class StudyPlanNarrator:
    """Enrich a deterministic StudyPlan with human-friendly AI guidance."""

    def __init__(self, gemini_client: GeminiClient) -> None:
        self._client = gemini_client

    def narrate(self, plan: StudyPlan) -> StudyPlan:
        """Add an AI-generated narrative to the study plan.

        Args:
            plan: A StudyPlan produced by build_study_plan (narrative=None).

        Returns:
            A new StudyPlan with narrative field populated.
        """
        top_topics = [s.topic for s in plan.sessions[:5]]
        extra_cache_key = f"{plan.student_id}:{','.join(top_topics)}"

        narrated = self._client.generate_structured(
            system_prompt=build_study_plan_system_prompt(),
            user_prompt=build_study_plan_user_prompt(plan),
            response_schema=StudyPlan,
            prompt_version=VERSION,
            task_tag="study_plan",
            extra_cache_key=extra_cache_key,
        )
        return narrated
