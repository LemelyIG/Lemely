from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConfidenceBand(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


def confidence_band_for_score(score: float) -> ConfidenceBand:
    if score >= 0.90:
        return ConfidenceBand.HIGH
    if score >= 0.70:
        return ConfidenceBand.MEDIUM
    return ConfidenceBand.LOW


class ExamMetadata(StrictModel):
    subject_code: str = Field(..., pattern=r"^\d{4}$")
    paper_number: int = Field(..., ge=1, le=9)
    paper_variant: int = Field(..., ge=1, le=9)
    session_month: Literal["May/June", "Oct/Nov", "Feb/Mar", "Specimen"]
    session_year: int | None = Field(None, ge=2000, le=2100)
    source_document: str | None = None


class SourceLibraryEntry(StrictModel):
    source_path: Path
    metadata: ExamMetadata


class BatchParseItem(StrictModel):
    source_path: str
    output_path: str | None = None
    status: Literal["skipped_existing", "parsed", "needs_parser", "invalid_existing", "failed"]
    message: str | None = None


class BatchParseResult(StrictModel):
    items: list[BatchParseItem]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total(self) -> int:
        return len(self.items)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def parsed(self) -> int:
        return sum(1 for item in self.items if item.status == "parsed")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def skipped(self) -> int:
        return sum(1 for item in self.items if item.status == "skipped_existing")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def failed(self) -> int:
        return sum(1 for item in self.items if item.status in {"failed", "invalid_existing"})


class CostEstimate(StrictModel):
    source_root: str
    mark_scheme_pdfs: int = Field(..., ge=0)
    cached_json: int = Field(..., ge=0)
    needs_parsing: int = Field(..., ge=0)
    estimated_pdf_pages: int | None = Field(None, ge=0)
    token_policy: str


class CorrectedQuestion(StrictModel):
    question_id: str
    awarded_marks: int = Field(..., ge=0)
    maximum_marks: int = Field(..., ge=0)
    confidence: ConfidenceBand
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    needs_teacher_review: bool
    student_answer: str | None = None
    expected_answer: str | None = None
    topic: str | None = None
    review_reason: str | None = None

    @model_validator(mode="after")
    def validate_awarded_marks(self) -> CorrectedQuestion:
        if self.awarded_marks > self.maximum_marks:
            raise ValueError("awarded_marks cannot exceed maximum_marks")
        return self


class CorrectionResult(StrictModel):
    metadata: ExamMetadata
    questions: list[CorrectedQuestion]
    awarded_marks: int = 0
    maximum_marks: int = 0
    needs_teacher_review: bool = False

    @model_validator(mode="after")
    def calculate_totals(self) -> CorrectionResult:
        object.__setattr__(self, "awarded_marks", sum(q.awarded_marks for q in self.questions))
        object.__setattr__(self, "maximum_marks", sum(q.maximum_marks for q in self.questions))
        object.__setattr__(
            self,
            "needs_teacher_review",
            any(q.needs_teacher_review for q in self.questions),
        )
        return self


class WeakArea(StrictModel):
    topic: str
    lost_marks: int = Field(..., ge=0)
    maximum_marks: int = Field(..., ge=0)
    accuracy: float = Field(..., ge=0.0, le=1.0)
    question_ids: list[str]


class WeaknessReport(StrictModel):
    weak_areas: list[WeakArea]
    needs_teacher_review: bool = False


class GradePrediction(StrictModel):
    awarded_marks: int = Field(..., ge=0)
    maximum_marks: int = Field(..., ge=0)
    percentage: float = Field(..., ge=0.0, le=100.0)
    grade: str
    confidence: ConfidenceBand
    needs_teacher_review: bool = False


class QuizQuestion(StrictModel):
    topic: str
    prompt: str
    source_question_ids: list[str]


class QuizPayload(StrictModel):
    questions: list[QuizQuestion]


class AccuracyReport(StrictModel):
    correction: CorrectionResult
    weaknesses: WeaknessReport
    grade_prediction: GradePrediction
