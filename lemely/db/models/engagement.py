"""ORM models for XP events and streaks (gamification layer)."""

from __future__ import annotations

import uuid
from datetime import date

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from lemely.db.base import Base
from lemely.db.models.enums import TimestampMixin, XpSource


class XpEvent(TimestampMixin, Base):
    """A single XP award earned by a user for completing an activity."""

    __tablename__ = "xp_events"
    __table_args__ = (sa.Index("ix_xp_events_user_id_awarded_on", "user_id", "awarded_on"),)

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
    source: Mapped[XpSource] = mapped_column(
        sa.Enum(XpSource, name="xpsource"),
        nullable=False,
    )
    amount: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    awarded_on: Mapped[date] = mapped_column(sa.Date, nullable=False)
    event_metadata: Mapped[dict] = mapped_column(  # type: ignore[type-arg]
        JSONB, nullable=False, server_default=sa.text("'{}'::jsonb"), name="metadata"
    )


class Streak(TimestampMixin, Base):
    """Running streak record for a user (one row per user)."""

    __tablename__ = "streaks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    current_length: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.literal(0)
    )
    longest_length: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.literal(0)
    )
    last_active_on: Mapped[date | None] = mapped_column(sa.Date, nullable=True)
    freezes_available: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.literal(0)
    )


__all__ = ["Streak", "XpEvent"]
