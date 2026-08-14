"""ORM models for plan tiers and subscriptions."""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lemely.db.base import Base
from lemely.db.models.enums import PlanInterval, SubscriptionStatus, TimestampMixin


class PlanTier(TimestampMixin, Base):
    """A purchasable subscription plan (e.g. ``free``, ``student_monthly``)."""

    __tablename__ = "plan_tiers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    code: Mapped[str] = mapped_column(sa.String, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(sa.String, nullable=False)
    price_minor: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.literal(0)
    )
    currency: Mapped[str] = mapped_column(
        sa.String, nullable=False, server_default=sa.literal("EGP")
    )
    interval: Mapped[PlanInterval | None] = mapped_column(
        sa.Enum(PlanInterval, name="planinterval"),
        nullable=True,
    )
    max_devices: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.literal(3)
    )
    features: Mapped[dict] = mapped_column(  # type: ignore[type-arg]
        JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
    )

    subscriptions: Mapped[list[Subscription]] = relationship(
        "Subscription", back_populates="plan_tier"
    )


class Subscription(TimestampMixin, Base):
    """A user's subscription to a :class:`PlanTier`.

    A user may hold a personal subscription *and* a school seat simultaneously;
    no exclusivity constraint is enforced at the schema level.
    """

    __tablename__ = "subscriptions"
    __table_args__ = (sa.Index("ix_subscriptions_user_id_status", "user_id", "status"),)

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
    plan_tier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("plan_tiers.id"),
        nullable=False,
    )
    status: Mapped[SubscriptionStatus] = mapped_column(
        sa.Enum(SubscriptionStatus, name="subscriptionstatus"),
        nullable=False,
        server_default=sa.text("'inactive'::subscriptionstatus"),
    )
    is_manually_activated: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.false()
    )
    activated_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    activation_note: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    """Why a platform admin activated or rejected this subscription (X-02).

    Nullable because a note is a human sentence with no honest default; see
    migration ``0019`` for why it is not ``NOT NULL DEFAULT ''``."""
    current_period_end: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    plan_tier: Mapped[PlanTier] = relationship("PlanTier", back_populates="subscriptions")


__all__ = ["PlanTier", "Subscription"]
