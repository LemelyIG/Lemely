"""otp_challenges: Postgres-backed, channel-aware OTP challenges (spec 2026-09-03 §4.4, D7.7)

Revision ID: 0025_otp_challenges
Revises: 0024_teacher_papers
Create Date: 2026-09-03 00:00:00.000000

One additive table, ``otp_challenges``, backed by a new ``otpchannel`` enum
(``phone`` / ``email``). It is the foundation for a Postgres-backed
``OtpChallengeStore`` (a later task, ``DbOtpStore``) that lets a second Cloud
Run instance verify a code the first one issued — today's in-memory
``OtpStore`` is a plain dict, invisible across workers and lost on restart.

The primary key is composite — ``(channel, address_hash)`` — not a synthetic
``id``. A phone challenge and an email challenge for the same underlying
string are two independent rows with independent codes and independent TTLs;
a synthetic id plus a unique index on the pair would let the same fact be
expressed two ways instead of making one of them impossible. ``address_hash``
and ``code_hash`` are the SHA-256 hex digests of the normalised address and
the code respectively (D7.7, the same rule ``auth_tokens.token_hash``
follows): a row never holds a redeemable credential or a raw contact, so a
database read yields nothing that verifies a code or identifies who it was
sent to.

No ``created_at``/``updated_at``. Every other table in this schema carries
them because a row is a durable record worth knowing the history of; a
challenge is not — it lives seconds to minutes, is replaced wholesale on
reissue, and is deleted outright on success, expiry or lockout. ``issued_at``
already answers "when was this created" for the one case (the resend
cooldown) that needs it.

Reversible: ``downgrade`` drops the table, then drops the ``otpchannel``
Postgres type explicitly. A table drop does not drop the type backing an enum
column — the same trap ``0006_at_risk_acknowledgements`` documents for
``atriskreason``, ``0022_auth_tokens`` follows for ``authtokenpurpose``, and
``0023_invites`` follows for ``inviterole``. This migration lets
``op.create_table``'s enum column create the type implicitly and drops it
explicitly in ``downgrade`` rather than issuing a separate, redundant
``CREATE TYPE``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
# Kept to <=32 chars: alembic_version.version_num is varchar(32).
revision: str = "0025_otp_challenges"
down_revision: str | Sequence[str] | None = "0024_teacher_papers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "otp_challenges",
        sa.Column("channel", sa.Enum("phone", "email", name="otpchannel"), nullable=False),
        sa.Column("address_hash", sa.String(), nullable=False),
        sa.Column("code_hash", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.PrimaryKeyConstraint("channel", "address_hash", name=op.f("pk_otp_challenges")),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("otp_challenges")
    op.execute("DROP TYPE otpchannel")
