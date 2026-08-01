"""Cross-paper performance history schemas."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, Protocol

from pydantic import Field

from lemely.core.schemas import ExamMetadata, StrictModel, WeakArea


def now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string.

    The canonical timestamp format for ``PaperRecord.recorded_at``; lives here
    (not in a storage module) so every history backend and caller shares it.
    """
    return datetime.now(UTC).isoformat()


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


class HistoryStoreProtocol(Protocol):
    """Structural interface for a student-history backend.

    Both the JSON ``HistoryStore`` (CLI/Gradio) and the Postgres
    ``DbHistoryStore`` (web/product) satisfy this, so the web routers and the
    grading service depend on the behaviour, not a concrete storage class
    (decisions D1.8/D1.9).
    """

    def load(self, student_id: str) -> StudentHistory: ...

    def append(self, student_id: str, record: PaperRecord) -> None: ...

    def list_students(self) -> list[str]: ...
