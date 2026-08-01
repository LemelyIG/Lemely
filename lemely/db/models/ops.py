"""ORM models for review queue, announcements, and notifications."""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lemely.db.base import Base
from lemely.db.models.enums import (
    NotificationType,
    ReviewReason,
    ReviewStatus,
    TimestampMixin,
)


class ReviewQueueItem(TimestampMixin, Base):
    """A question result that requires teacher review."""

    __tablename__ = "review_queue"
    __table_args__ = (sa.Index("ix_review_queue_status", "status"),)

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
    question_result_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("question_results.id"),
        nullable=True,
    )
    reason: Mapped[ReviewReason] = mapped_column(
        sa.Enum(ReviewReason, name="reviewreason"),
        nullable=False,
    )
    status: Mapped[ReviewStatus] = mapped_column(
        sa.Enum(ReviewStatus, name="reviewstatus"),
        nullable=False,
        server_default=sa.text("'open'::reviewstatus"),
    )
    assigned_teacher_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id"),
        nullable=True,
    )
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id"),
        nullable=True,
    )
    resolution_note: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)

    question_result: Mapped[object] = relationship(
        "QuestionResult", back_populates="review_queue_items"
    )


class Announcement(TimestampMixin, Base):
    """An announcement published by a teacher or school admin."""

    __tablename__ = "announcements"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id"),
        nullable=False,
    )
    school_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("schools.id"),
        nullable=True,
    )
    class_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("classes.id"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(sa.String, nullable=False)
    body: Mapped[str] = mapped_column(sa.Text, nullable=False)
    publish_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)


class Notification(TimestampMixin, Base):
    """An in-app notification delivered to a specific user."""

    __tablename__ = "notifications"
    __table_args__ = (sa.Index("ix_notifications_user_id_read_at", "user_id", "read_at"),)

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
    type: Mapped[NotificationType] = mapped_column(
        sa.Enum(NotificationType, name="notificationtype"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(sa.String, nullable=False)
    body: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    payload: Mapped[dict] = mapped_column(  # type: ignore[type-arg]
        JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
    )
    read_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)


__all__ = ["Announcement", "Notification", "ReviewQueueItem"]
