"""ORM models for uploads, attempts, question results, and weakness records."""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lemely.db.base import Base
from lemely.db.models.enums import (
    AttemptOrigin,
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
    __table_args__ = (
        sa.Index("ix_attempts_user_id_recorded_at", "user_id", "recorded_at"),
        sa.Index("ix_attempts_user_id_origin", "user_id", "origin"),
    )

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
    origin: Mapped[AttemptOrigin] = mapped_column(
        sa.Enum(AttemptOrigin, name="attemptorigin"),
        nullable=False,
        server_default=sa.text("'past_paper'::attemptorigin"),
    )
    """What kind of assessment produced this attempt (P3.5, migration
    ``0007_quiz_model``). Every pre-existing row is a past-paper attempt, so
    the default needs no backfill. For ``origin = quiz``, ``grade``,
    ``predicted_grade``, ``boundary_source``, ``paper_id``, ``paper_number``,
    ``paper_variant``, ``session_month`` and ``session_year`` are all NULL —
    a ten-question quiz has no grade boundaries, and giving it one would
    invent precision and silently corrupt every grade-bearing consumer of
    student history (``docs/quiz-model.md`` §1.2). This column is schema
    only in chunk A; nothing here yet reads it (chunk G wires it up).
    """

    upload: Mapped[Upload | None] = relationship("Upload", back_populates="attempts")
    question_results: Mapped[list[QuestionResult]] = relationship(
        "QuestionResult", back_populates="attempt", cascade="all, delete-orphan"
    )
    weakness_records: Mapped[list[WeaknessRecord]] = relationship(
        "WeaknessRecord", back_populates="attempt"
    )


class QuestionResult(TimestampMixin, Base):
    """Per-question marking outcome within an :class:`Attempt`.

    ``teacher_awarded_marks``/``teacher_note``/``teacher_breakdown``/
    ``overridden_by``/``overridden_at`` are P3.4's teacher-override columns
    (migration ``0005_review_overrides``). They are additive and all
    nullable: ``awarded_marks`` (the AI's mark) is never mutated or erased by
    an override — "the teacher has final authority" (UI-spec §1.4) means the
    teacher's mark wins on every read, not that the machine's mark is
    destroyed. It stays queryable for accuracy measurement (MISSION §4:
    "overrides feed back as recorded corrections") and so a teacher can always
    see what Lemely originally produced. See :attr:`effective_marks`.
    """

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
    teacher_awarded_marks: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    teacher_note: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    teacher_breakdown: Mapped[dict | None] = mapped_column(  # type: ignore[type-arg]
        JSONB, nullable=True
    )
    """Teacher-supplied method/accuracy breakdown for an override, verbatim.

    Deliberately NOT computed: a mark scheme's M/A/B point types
    (``lemely.core.loose_schemas.MathMarkType``) live in the parsed mark
    scheme, not on this row — only ``matched_point_ids`` (bare point ids) is
    persisted here, with no join back to per-point mark types. There is
    nothing here honest to derive a breakdown from (UI-spec §1.4: never invent
    precision), so this column stores exactly what the teacher typed — free-form
    keys the API layer validates loosely (e.g. ``methodMarks``/``accuracyMarks``),
    nothing more.
    """
    overridden_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id"),
        nullable=True,
    )
    overridden_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    attempt: Mapped[Attempt] = relationship("Attempt", back_populates="question_results")
    review_queue_items: Mapped[list] = relationship(  # type: ignore[type-arg]
        "ReviewQueueItem", back_populates="question_result"
    )

    @property
    def effective_marks(self) -> int:
        """The mark that must reach every student-facing surface.

        The teacher's override when one has been recorded, else the AI's
        ``awarded_marks`` unchanged. **The single accessor** — anything
        (a route, a DTO converter, a future report) that needs "this
        question's mark" reads this, never ``awarded_marks`` directly, so a
        teacher correction can never be shown on one screen and silently
        missing on another (P3.4; the same anti-drift discipline D3.3 applied
        to "at risk").
        """
        if self.teacher_awarded_marks is not None:
            return self.teacher_awarded_marks
        return self.awarded_marks

    @property
    def is_overridden(self) -> bool:
        """Whether a teacher has recorded a correction for this question."""
        return self.teacher_awarded_marks is not None


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
