"""ORM models for user identity, parent-child links, and device sessions."""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lemely.db.base import Base
from lemely.db.models.enums import Role, TimestampMixin


class User(TimestampMixin, Base):
    """Platform user whose ``id`` mirrors ``auth.users.id`` in Supabase.

    The ``id`` is supplied by the application at signup (not server-generated)
    so it can be kept in sync with the Supabase auth system without a
    cross-schema foreign key.
    """

    __tablename__ = "users"
    __table_args__ = (
        sa.Index("ix_users_email", "email"),
        sa.Index("ix_users_role", "role"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        # No server_default: caller supplies the auth.users id.
    )
    email: Mapped[str] = mapped_column(sa.String, nullable=False, unique=True)
    role: Mapped[Role] = mapped_column(
        sa.Enum(Role, name="role"),
        nullable=False,
    )
    display_name: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    phone: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.false())
    locale: Mapped[str] = mapped_column(sa.String, nullable=False, server_default=sa.literal("en"))

    # Relationships (back-references populated by child models)
    devices: Mapped[list[Device]] = relationship(
        "Device", back_populates="user", cascade="all, delete-orphan"
    )
    parent_links: Mapped[list[ParentChildLink]] = relationship(
        "ParentChildLink",
        foreign_keys="ParentChildLink.parent_id",
        back_populates="parent",
        cascade="all, delete-orphan",
    )
    child_links: Mapped[list[ParentChildLink]] = relationship(
        "ParentChildLink",
        foreign_keys="ParentChildLink.child_id",
        back_populates="child",
        cascade="all, delete-orphan",
    )


class ParentChildLink(TimestampMixin, Base):
    """Associates a parent user with a child (student) user."""

    __tablename__ = "parent_child_links"
    __table_args__ = (
        sa.UniqueConstraint(
            "parent_id",
            "child_id",
            name="uq_parent_child_links_parent_id_child_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    parent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    child_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    parent: Mapped[User] = relationship(
        "User", foreign_keys=[parent_id], back_populates="parent_links"
    )
    child: Mapped[User] = relationship(
        "User", foreign_keys=[child_id], back_populates="child_links"
    )


class Device(TimestampMixin, Base):
    """Session/device registry entry for a user.

    The application enforces a max-3-concurrent-device policy by revoking the
    oldest entry; this table only stores the records.
    """

    __tablename__ = "devices"
    __table_args__ = (
        sa.Index("ix_devices_user_id_revoked_at", "user_id", "revoked_at"),
        sa.Index("ix_devices_user_id_client_device_id", "user_id", "client_device_id"),
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
    # Stable opaque identifier the client (SPA) mints once and stores locally, so a
    # re-login on the same device reuses its row instead of consuming a new slot
    # (D1.11). Nullable: a client that supplies none gets a fresh device per login.
    client_device_id: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    device_label: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    refresh_token_id: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    last_seen_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship("User", back_populates="devices")


__all__ = ["Device", "ParentChildLink", "User"]
