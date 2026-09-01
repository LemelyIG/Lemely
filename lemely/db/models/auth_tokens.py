"""ORM model for single-use email-verification and password-reset tokens."""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from lemely.db.base import Base
from lemely.db.models.enums import AuthTokenPurpose, TimestampMixin


class AuthToken(TimestampMixin, Base):
    """A single-use credential emitted into an email link (D7.7).

    **The row never holds the credential.** ``token_hash`` is the SHA-256 of
    the token that went into the link; the plaintext exists in the email and
    in the requester's browser and nowhere else. A database read — a backup, a
    log, a support query, a leak — therefore yields nothing redeemable. This is
    the one property that makes storing these in Postgres safer than the
    in-memory ``OtpStore`` they otherwise resemble, rather than merely more
    durable.

    **Durability is the reason they are not in memory.** ``OtpStore`` is a
    plain dict: challenges die on restart and do not exist across workers.
    That is tolerable for a code a parent types within sixty seconds and not
    for a reset link someone opens from their inbox an hour and one deploy
    later.

    Single-use is ``used_at``, not deletion: a redeemed row is evidence, and a
    second presentation of the same token should be distinguishable from a
    token that was never minted. Expiry is absolute (``expires_at``), so a
    clock comparison is the whole validity check and there is no sliding
    window to reason about.
    """

    __tablename__ = "auth_tokens"
    __table_args__ = (
        sa.Index("ix_auth_tokens_token_hash", "token_hash", unique=True),
        sa.Index("ix_auth_tokens_user_id_purpose", "user_id", "purpose"),
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
    purpose: Mapped[AuthTokenPurpose] = mapped_column(
        sa.Enum(AuthTokenPurpose, name="authtokenpurpose"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    """SHA-256 hex digest of the emitted token. Unique so a redemption lookup
    is a single indexed read and a hash collision is a rejected insert."""
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)


__all__ = ["AuthToken"]
