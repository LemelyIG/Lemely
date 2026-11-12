"""auth_cooldowns: Postgres-backed resend-cooldown stamps (spec 2026-09-03 §4.4, D7.7)

Revision ID: 0026_auth_cooldowns
Revises: 0025_otp_challenges
Create Date: 2026-09-03 00:00:00.000000

One additive table, ``auth_cooldowns``, the last of the three D7.12/§4.4 auth
stores to move off process memory. It is the foundation for a Postgres-backed
``CooldownStoreProtocol`` implementation (a later task, ``DbCooldownStore``)
so a resend a second Cloud Run instance receives is throttled by the stamp
the first one made — today's in-memory ``CooldownStore`` is a plain
per-worker dict, invisible across instances and lost on restart.

The primary key is composite — ``(purpose, key_hash)`` — not a synthetic
``id``, mirroring ``otp_challenges`` (migration ``0025``): a signup cooldown
and a resend-verification cooldown for the same underlying email are two
independent rows with independent stamps, never one row two purposes
contend over. ``purpose`` is a plain string, not an enum — the whole point
of this table is that a new D7.12 caller can start stamping a new purpose
with no migration, unlike ``otp_challenges.channel``'s closed two-value
vocabulary. ``key_hash`` is the SHA-256 hex digest of the cooldown key
(D7.7, the same rule ``auth_tokens.token_hash`` and
``otp_challenges.address_hash`` follow): a row never holds a raw contact, so
a database read yields nothing that identifies who a cooldown was stamped
for. It is ``String(64)`` — a SHA-256 hex digest is always exactly 64
characters — the same explicit length those two columns use.

No ``created_at``/``updated_at``. A cooldown row is overwritten wholesale on
every successful stamp and carries no history worth keeping —
``stamped_at`` already answers "when was this last touched", the same
reasoning ``0025_otp_challenges`` gives for its own identical omission.

No enum, so nothing for ``downgrade`` to drop beyond the table itself —
unlike ``0025_otp_challenges``, which must also drop the ``otpchannel``
Postgres type it implicitly creates.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
# Kept to <=32 chars: alembic_version.version_num is varchar(32).
revision: str = "0031_auth_cooldowns"
down_revision: str | Sequence[str] | None = "0030_otp_challenges"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "auth_cooldowns",
        sa.Column("purpose", sa.String(), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("stamped_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("purpose", "key_hash", name=op.f("pk_auth_cooldowns")),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("auth_cooldowns")
