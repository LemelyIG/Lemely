"""Cross-paper performance history schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from lemely.core.schemas import ExamMetadata, StrictModel, WeakArea


class PaperRecord(StrictModel):
    student_id: str
    metadata: ExamMetadata
    awarded_marks: int = Field(..., ge=0)
    maximum_marks: int = Field(..., ge=0)
    percentage: float = Field(..., ge=0.0, le=100.0)
    grade: str
    weak_areas: list[WeakArea]  # full objects for cross-paper aggregation
    recorded_at: str  # ISO-8601 UTC


# Bump when the persisted StudentHistory shape changes in a non-additive way.
# HistoryStore.load() refuses files whose schema_version exceeds this.
HISTORY_SCHEMA_VERSION = 1


class StudentHistory(StrictModel):
    # Persisted so a future migration can detect and upgrade older files instead
    # of silently misreading them. Absent in pre-versioning files → defaults to 1.
    schema_version: int = HISTORY_SCHEMA_VERSION
    student_id: str
    records: list[PaperRecord] = []  # noqa: RUF012


class TopicTrend(StrictModel):
    topic: str
    direction: Literal["improving", "declining", "stable"]
    delta_accuracy: float


class PerformanceComparison(StrictModel):
    student_id: str
    latest: PaperRecord
    prior_count: int
    percentage_delta: float | None
    topic_trends: list[TopicTrend]
