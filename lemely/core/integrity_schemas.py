"""Schemas for integrity checks (plagiarism and AI-generated detection)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from lemely.core.schemas import StrictModel


class IntegrityFinding(StrictModel):
    question_id: str
    kind: Literal["plagiarism", "ai_generated"]
    flagged: bool
    score: float = Field(..., ge=0.0, le=1.0)  # difflib ratio or classifier confidence
    rationale: str


class IntegrityReport(StrictModel):
    findings: list[IntegrityFinding]
    needs_teacher_review: bool = False
