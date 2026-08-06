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


# The single source of truth for the grade ladder, best to worst. It lives in
# this schema module rather than in ``lemely.core.at_risk`` (which owned it
# until P3.5 chunk G) so that :func:`is_grade_bearing` can reach it without a
# schema module having to import a rules engine. ``lemely.core.at_risk``
# re-exports it, so ``from lemely.core.at_risk import GRADE_ORDER`` — the
# import every existing caller uses — keeps working unchanged.
GRADE_ORDER = ["A*", "A", "B", "C", "D", "E", "U"]

PaperOrigin = Literal["past_paper", "quiz", "custom_paper"]
"""The origin vocabulary, named once so the DB layer can convert an
``AttemptOrigin`` member into it without re-literalising the three strings.
Deliberately identical to ``lemely.db.models.enums.AttemptOrigin``'s values and
pinned equal to them by ``tests/test_db_schema.py``, the same anti-drift
discipline applied to the difficulty bands.
"""


class PaperRecord(StrictModel):
    student_id: str
    metadata: ExamMetadata
    awarded_marks: int = Field(..., ge=0)
    maximum_marks: int = Field(..., ge=0)
    percentage: float = Field(..., ge=0.0, le=100.0)
    grade: str
    weak_areas: list[WeakArea]  # full objects for cross-paper aggregation
    recorded_at: str  # ISO-8601 UTC
    origin: PaperOrigin = "past_paper"
    """What kind of assessment produced this record (P3.5, ``docs/quiz-model.md``
    §5). Mirrors ``attempts.origin``; defaulted so every pre-existing record and
    every persisted history file loads unchanged. Read it through
    :func:`is_grade_bearing` rather than comparing to a literal at call sites.
    """


def is_grade_bearing(record: PaperRecord) -> bool:
    """Whether this record may back a grade, boundary, or paper-comparison claim.

    True only for full past-paper attempts that carry a real grade. A quiz has
    no grade boundaries, so its percentage is not comparable to a paper's and
    its grade does not exist — a ten-question topic quiz scoring 50% is not the
    same claim as a full paper scoring 50%, and averaging the two invents a
    precision neither has (spec §1.4, "never invent precision").

    Topic-level aggregation deliberately ignores this predicate: a weakness is
    a weakness whatever revealed it, and a quiz *is* activity. The split of
    which consumer applies it is tabulated in ``docs/quiz-model.md`` §5.
    """
    return record.origin == "past_paper" and record.grade in GRADE_ORDER


# Bump when the persisted StudentHistory shape changes in a non-additive way.
# HistoryStore.load() refuses files whose schema_version exceeds this.
# 1 -> 2 (P3.5 chunk G): added PaperRecord.origin. Additive — it has a default,
# so a version-1 file on disk still loads and reads back as all-past_paper.
HISTORY_SCHEMA_VERSION = 2


class StudentHistory(StrictModel):
    # Persisted so a future migration can detect and upgrade older files instead
    # of silently misreading them. This default is what a *newly constructed*
    # history carries (always the current version); a history read off disk gets
    # the version the file actually declared, with absent meaning 1 — see
    # ``HistoryStore.load``, which resolves that before validating.
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
