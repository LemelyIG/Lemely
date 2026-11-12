"""Wire shapes for the paper-deletion routes (design 2026-09-22 §8).

``DeletedPaperDTO`` deliberately carries no mark, grade or percentage. The
recently-deleted list is a recovery surface, not a second results screen, and
a deleted paper's marks are exactly what the student asked to stop seeing.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - pydantic needs the real type at runtime

from pydantic import BaseModel, ConfigDict


class DeletedPaperDTO(BaseModel):
    """One restorable deletion, with its countdown."""

    model_config = ConfigDict(extra="forbid")

    attemptId: str
    paperLabel: str
    subjectCode: str | None
    deletedAt: datetime
    restoreDeadline: datetime


class DeletedPapersDTO(BaseModel):
    """The recently-deleted area's whole payload."""

    model_config = ConfigDict(extra="forbid")

    papers: list[DeletedPaperDTO]
    retentionDays: int


__all__ = ["DeletedPaperDTO", "DeletedPapersDTO"]
