"""ORM model for redeemable school/class invite codes."""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from lemely.db.base import Base
from lemely.db.models.enums import InviteRole, TimestampMixin


class Invite(TimestampMixin, Base):
    """A redeemable code that provisions a school seat, a class enrolment, or parent access (D7.3).

    An invite to nothing is not an invite. All three target columns are
    nullable because an invite is to a school, a class, **or** a child, never
    necessarily more than one of them — and ``ck_invites_target`` is what
    stops "one of these" degrading into "none of these". This is the
    ``friendships`` rule again: idempotency and validity are enforced by the
    database, not by care.

    ``reusable`` distinguishes the two parent-invite kinds that share this
    table (spec "two invite kinds, one table" §3): a single-use link that
    expires and gets marked redeemed, or a rotatable short code that never
    is. ``redeemed_by``/``redeemed_at`` mark consumption rather than deleting
    the row, for the same reason ``AuthToken.used_at`` does: a school admin
    asking "did that code ever get used, and by whom" is a question the
    schema should be able to answer.
    """

    __tablename__ = "invites"
    __table_args__ = (
        sa.CheckConstraint(
            "school_id IS NOT NULL OR class_id IS NOT NULL OR child_id IS NOT NULL",
            name="ck_invites_target",
        ),
        sa.Index("ix_invites_code", "code", unique=True),
        sa.Index("ix_invites_child_id", "child_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    code: Mapped[str] = mapped_column(sa.String, nullable=False)
    role: Mapped[InviteRole] = mapped_column(
        sa.Enum(InviteRole, name="inviterole"),
        nullable=False,
    )
    school_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("schools.id", ondelete="CASCADE"),
        nullable=True,
    )
    class_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("classes.id", ondelete="CASCADE"),
        nullable=True,
    )
    child_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
    )
    seat_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("seats.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id"),
        nullable=False,
    )
    expires_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    reusable: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.false())
    redeemed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    redeemed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)


__all__ = ["Invite"]
