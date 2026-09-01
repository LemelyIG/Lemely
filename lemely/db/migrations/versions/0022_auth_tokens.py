"""auth_tokens: single-use email-verification and password-reset tokens (D7.7)

Revision ID: 0022_auth_tokens
Revises: 0021_account_lifecycle
Create Date: 2026-08-25 00:00:00.000000

One additive table, ``auth_tokens``, backed by a new ``authtokenpurpose``
enum (``email_verification`` / ``password_reset``). One table with a purpose
column rather than two near-identical tables: mint, single-use, expire and
revoke-all-on-password-change are the same lifecycle for both flows, so a
second table would duplicate a repository rather than express a real
distinction (D7.7).

``token_hash`` is the SHA-256 hex digest of the token that went into the
emitted link — the plaintext exists in the email and the requester's browser
and nowhere else, so a database read (a backup, a log, a support query, a
leak) yields nothing redeemable. ``ix_auth_tokens_token_hash`` is a unique
index: it is the redemption lookup, and a hash collision is a rejected
insert rather than an ambiguous match. ``ix_auth_tokens_user_id_purpose``
serves the other access pattern this table needs, revoking every outstanding
token of one purpose for one user on a password change.

``used_at`` marks single-use rather than deleting the row (a redeemed token
is evidence); ``expires_at`` is absolute, so validity is one clock
comparison with no sliding window to reason about.

This table exists in Postgres, not in the in-memory ``OtpStore`` shape it
otherwise resembles, because a reset link is opened from an inbox an hour and
one deploy after it was minted — ``OtpStore`` dies on restart and does not
exist across workers, which a 60-second OTP can tolerate and this cannot.

Reversible: ``downgrade`` drops the table, then drops the ``authtokenpurpose``
Postgres type explicitly. A table drop does not drop the type backing an enum
column — the same trap ``0006_at_risk_acknowledgements`` documents for
``atriskreason``, and ``0015_friendships`` follows for ``friendshipstatus``.
This migration lets ``op.create_table``'s enum column create the type
implicitly and drops it explicitly in ``downgrade`` rather than issuing a
separate, redundant ``CREATE TYPE``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
# Kept to <=32 chars: alembic_version.version_num is varchar(32).
revision: str = "0022_auth_tokens"
down_revision: str | Sequence[str] | None = "0021_account_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "auth_tokens",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "purpose",
            sa.Enum("email_verification", "password_reset", name="authtokenpurpose"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_auth_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_tokens")),
    )
    op.create_index(
        "ix_auth_tokens_token_hash", "auth_tokens", ["token_hash"], unique=True
    )
    op.create_index(
        "ix_auth_tokens_user_id_purpose", "auth_tokens", ["user_id", "purpose"]
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("auth_tokens")
    sa.Enum(name="authtokenpurpose").drop(op.get_bind(), checkfirst=False)
