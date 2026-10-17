"""The per-class paper exclusion behind a teacher's unshare (design §5).

The product's first per-paper sharing concept: teacher visibility of a
student's papers has until now derived purely from class enrollment, with
nothing to unshare. Grain is ``(class, attempt)`` — a class has owners and
administrators, so "their view" is the class's view, and D9 is per paper, so a
student in two classes unshared in one still counts in the other.

Read by exactly one thing,
:class:`~lemely.db.class_history.ClassScopedHistoryStore`, which is constructed
only in :mod:`lemely.web.routers.classes`. That containment is what makes the
student genuinely unaffected rather than carefully unaffected.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from lemely.db.base import Base
from lemely.db.models.enums import TimestampMixin


class ClassPaperExclusion(TimestampMixin, Base):
    """One attempt hidden from one class's view and analytics."""

    __tablename__ = "class_paper_exclusions"

    class_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("classes.id", ondelete="CASCADE"),
        primary_key=True,
    )
    attempt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("attempts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    excluded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )


__all__ = ["ClassPaperExclusion"]
