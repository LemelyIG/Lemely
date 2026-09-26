"""AI-powered practice question generator using weak areas as input."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from lemely.core.generation import GeneratedQuestion, GeneratedQuiz
from lemely.io.prompts.question_generation import (
    VERSION,
    build_question_gen_system_prompt,
    build_question_gen_user_prompt,
)
from lemely.io.question_gates import MAX_GENERATION_ATTEMPTS, verify_question

if TYPE_CHECKING:
    from lemely.core.schemas import WeakArea, WeaknessReport
    from lemely.io.gemini import GeminiClient


class QuestionGenerator:
    """Generate targeted practice questions from a WeaknessReport via Gemini.

    One question is generated per weak area, capped at min(count, len(weak_areas)).
    Each candidate question is run through the N3 verification gate
    (:mod:`lemely.io.question_gates`) before it is returned; a candidate the
    gate rejects is regenerated, with the rejection reason fed back into the
    prompt, up to :data:`~lemely.io.question_gates.MAX_GENERATION_ATTEMPTS`
    times. An area that never produces a verified question in that budget is
    dropped from the quiz rather than returned unverified — this is the gate
    that stops a wrong item reaching a student's quiz (B6 [gen 6]: 6%
    factual error, 14% wrong difficulty, 38% clearing the discrimination bar
    on unverified AI items).
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
        """Generate verified practice questions for the top weak areas.

        Args:
            weaknesses: WeaknessReport with weak_areas to target.
            subject_code: CAIE subject code (e.g. '0625').
            count: Maximum number of questions to generate.

        Returns:
            GeneratedQuiz with at most min(count, len(weak_areas)) questions,
            each carrying a non-None ``verified_by``. An area whose every
            generation attempt was rejected contributes no question at all.
        """
        areas = weaknesses.weak_areas[:count]
        questions: list[GeneratedQuestion] = []
        for area in areas:
            verified = self._generate_verified_one(area, subject_code=subject_code)
            if verified is not None:
                questions.append(verified)
        # N3 review MUST-FIX 3: a per-generate() summary count, independent
        # of question_gates' per-rejection log line. This is the backstop
        # that stays visible even when individual rejection records scroll
        # off — a teacher requesting 5 questions and receiving 2 must be
        # detectable in production without reconstructing it from rejection
        # counts by hand.
        structlog.get_logger().info(
            "question_generation_summary",
            subject_code=subject_code,
            requested=len(areas),
            generated=len(questions),
            dropped=len(areas) - len(questions),
        )
        return GeneratedQuiz(subject_code=subject_code, questions=questions)

    def _generate_one(
        self, area: WeakArea, *, subject_code: str, failure_reason: str | None
    ) -> GeneratedQuestion:
        """One Gemini call for a single weak area.

        Cache-keyed on that area and on ``failure_reason`` (via the user
        prompt it changes) so a regeneration attempt is a genuinely new
        call, not a cache hit that would return the exact rejected question
        again.
        """
        quiz = self._client.generate_structured(
            system_prompt=build_question_gen_system_prompt(subject_code),
            user_prompt=build_question_gen_user_prompt(
                [area], count=1, failure_reason=failure_reason
            ),
            response_schema=GeneratedQuiz,
            prompt_version=VERSION,
            task_tag="generation",
            extra_cache_key=f"{subject_code}:{area.topic}:{failure_reason or ''}",
        )
        question = quiz.questions[0]
        # verified_by/rejection_reason are set only by verify_question
        # (lemely.io.question_gates) — never trust whatever Gemini's own
        # JSON output happened to put there, since that would let a wrong
        # item self-certify.
        return question.model_copy(update={"verified_by": None, "rejection_reason": None})

    def _generate_verified_one(
        self, area: WeakArea, *, subject_code: str
    ) -> GeneratedQuestion | None:
        failure_reason: str | None = None
        for attempt in range(MAX_GENERATION_ATTEMPTS):
            candidate = self._generate_one(
                area, subject_code=subject_code, failure_reason=failure_reason
            )
            verified = verify_question(
                self._client, candidate, subject_code=subject_code, attempt=attempt
            )
            if verified.verified_by is not None:
                return verified
            failure_reason = verified.rejection_reason
        return None
