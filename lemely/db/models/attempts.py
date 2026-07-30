"""ORM models for uploads, attempts, question results, and weakness records."""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lemely.db.base import Base
from lemely.db.models.enums import (
    BoundarySource,
    ConfidenceBand,
    MarkerSource,
    SessionMonth,
    TimestampMixin,
    UploadStatus,
)


class Upload(TimestampMixin, Base):
    """A student's raw scan/upload stored in Supabase Storage."""

    __tablename__ = "uploads"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    storage_path: Mapped[str] = mapped_column(sa.String, nullable=False)
    original_filename: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    content_type: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    byte_size: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    page_count: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    status: Mapped[UploadStatus] = mapped_column(
        sa.Enum(UploadStatus, name="uploadstatus"),
        nullable=False,
        server_default=sa.text("'pending'::uploadstatus"),
    )

    attempts: Mapped[list[Attempt]] = relationship("Attempt", back_populates="upload")


class Attempt(TimestampMixin, Base):
    """A marked attempt at a specific exam paper by a student."""

    __tablename__ = "attempts"
    __table_args__ = (sa.Index("ix_attempts_user_id_recorded_at", "user_id", "recorded_at"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    upload_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("uploads.id"),
        nullable=True,
    )
    paper_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("papers.id"),
        nullable=True,
    )
    subject_code: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    session_month: Mapped[SessionMonth | None] = mapped_column(
        sa.Enum(SessionMonth, name="sessionmonth"),
        nullable=True,
    )
    session_year: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    paper_number: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    paper_variant: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    awarded_marks: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    maximum_marks: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    percentage: Mapped[float] = mapped_column(sa.Float, nullable=False)
    grade: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    predicted_grade: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    boundary_source: Mapped[BoundarySource | None] = mapped_column(
        sa.Enum(BoundarySource, name="boundarysource"),
        nullable=True,
    )
    confidence_band: Mapped[ConfidenceBand | None] = mapped_column(
        sa.Enum(ConfidenceBand, name="confidenceband"),
        nullable=True,
    )
    needs_teacher_review: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.false()
    )
    recorded_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)

    upload: Mapped[Upload | None] = relationship("Upload", back_populates="attempts")
    question_results: Mapped[list[QuestionResult]] = relationship(
        "QuestionResult", back_populates="attempt", cascade="all, delete-orphan"
    )
    weakness_records: Mapped[list[WeaknessRecord]] = relationship(
        "WeaknessRecord", back_populates="attempt"
    )


class QuestionResult(TimestampMixin, Base):
    """Per-question marking outcome within an :class:`Attempt`."""

    __tablename__ = "question_results"
    __table_args__ = (sa.Index("ix_question_results_attempt_id", "attempt_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    attempt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("attempts.id", ondelete="CASCADE"),
        nullable=False,
    )
    question_id: Mapped[str] = mapped_column(sa.String, nullable=False)
    awarded_marks: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    maximum_marks: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    confidence_band: Mapped[ConfidenceBand] = mapped_column(
        sa.Enum(ConfidenceBand, name="confidenceband"),
        nullable=False,
    )
    confidence_score: Mapped[float] = mapped_column(sa.Float, nullable=False)
    needs_teacher_review: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.false()
    )
    marker_source: Mapped[MarkerSource] = mapped_column(
        sa.Enum(MarkerSource, name="markersource"),
        nullable=False,
    )
    topic: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    student_answer: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    expected_answer: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    review_reason: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    feedback: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    matched_point_ids: Mapped[list] = mapped_column(  # type: ignore[type-arg]
        JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
    )

    attempt: Mapped[Attempt] = relationship("Attempt", back_populates="question_results")
    review_queue_items: Mapped[list] = relationship(  # type: ignore[type-arg]
        "ReviewQueueItem", back_populates="question_result"
    )


class WeaknessRecord(TimestampMixin, Base):
    """Aggregated topic-level weakness for a user, optionally tied to an attempt."""

    __tablename__ = "weakness_records"
    __table_args__ = (sa.Index("ix_weakness_records_user_id_topic", "user_id", "topic"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("attempts.id", ondelete="CASCADE"),
        nullable=True,
    )
    topic: Mapped[str] = mapped_column(sa.String, nullable=False)
    lost_marks: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    maximum_marks: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    accuracy: Mapped[float] = mapped_column(sa.Float, nullable=False)
    question_ids: Mapped[list] = mapped_column(  # type: ignore[type-arg]
        JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
    )

    attempt: Mapped[Attempt | None] = relationship("Attempt", back_populates="weakness_records")


__all__ = ["Attempt", "QuestionResult", "Upload", "WeaknessRecord"]
