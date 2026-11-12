"""Schemas for integrity checks (plagiarism).

F4 removed the AI-generated-answer detector (``ai_generated`` used to be the
other ``IntegrityFinding.kind`` value); ``plagiarism`` is the only kind left.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from lemely.core.schemas import StrictModel


class IntegrityFinding(StrictModel):
    question_id: str
    kind: Literal["plagiarism"]
    flagged: bool
    score: float = Field(..., ge=0.0, le=1.0)  # difflib ratio
    rationale: str


class IntegrityReport(StrictModel):
    findings: list[IntegrityFinding]
    needs_teacher_review: bool = False
