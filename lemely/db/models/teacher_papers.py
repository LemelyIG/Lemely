"""ORM model for a teacher-console paper (spec 2026-09-03 §4.2, DS2/DS11/DS13)."""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from lemely.db.base import Base
from lemely.db.models.enums import TimestampMixin, UploadStatus


class TeacherPaper(TimestampMixin, Base):
    """One scan uploaded through the grading console, and its run state.

    Replaces the in-process ``_PaperStore``. Every field the grading worker
    used to mutate on an in-memory entry is a column, so any instance can
    answer the polled routes from the row and a restart loses nothing.
    ``graded`` versus ``review`` is *derived* from ``report_json`` at read time
    — ``status`` records only the run's lifecycle.
    """

    __tablename__ = "teacher_papers"
    __table_args__ = (
        sa.Index("ix_teacher_papers_uploaded_by_created_at", "uploaded_by", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
    )
    uploaded_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    student_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    storage_path: Mapped[str] = mapped_column(sa.String, nullable=False)
    scheme_storage_path: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    original_filename: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    content_type: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    byte_size: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    status: Mapped[UploadStatus] = mapped_column(
        # Same Postgres type ``uploads.status`` already uses; SQLAlchemy dedups
        # enum types by name at ``create_all``, and the migration below passes
        # ``create_type=False`` so Alembic never tries to re-create it.
        sa.Enum(UploadStatus, name="uploadstatus"),
        nullable=False,
        server_default=sa.text("'pending'::uploadstatus"),
    )
    stage: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    progress_index: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    progress_total: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # type: ignore[type-arg]
    mark_scheme_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # type: ignore[type-arg]
    report_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # type: ignore[type-arg]
    error: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    run_started_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )


__all__ = ["TeacherPaper"]
