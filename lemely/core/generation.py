"""Schemas for AI-generated practice questions."""

from __future__ import annotations

from typing import Literal

from lemely.core.schemas import StrictModel


class GeneratedQuestion(StrictModel):
    topic: str
    difficulty: Literal["foundation", "standard", "challenge"]
    prompt: str
    model_answer: str
    mark_scheme_points: list[str]
    total_marks: int
    source_question_ids: list[str] = []  # noqa: RUF012


class GeneratedQuiz(StrictModel):
    subject_code: str
    questions: list[GeneratedQuestion]
