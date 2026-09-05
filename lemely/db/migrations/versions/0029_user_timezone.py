"""Add ``users.timezone`` and ``users.timezone_is_explicit`` (per-user civil time, spec §3).

Additive. ``timezone`` is ``NULL`` for every existing row and ``NULL`` resolves
to the launch zone (``lemely.db.xp_repo.DEFAULT_ZONE``), so this migration
changes nobody's behaviour on deploy. ``timezone_is_explicit`` records that the
*user* chose the zone, which is what stops the client's auto-detect overwriting
a deliberate choice. No backfill: nothing knows where an existing user is.

Revision ID: 0029_user_timezone
Revises: 0028_user_avatar_path
Create Date: 2026-09-05 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
# Kept to <=32 chars: alembic_version.version_num is varchar(32).
revision: str = "0029_user_timezone"
down_revision: str | Sequence[str] | None = "0028_user_avatar_path"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("users", sa.Column("timezone", sa.String(length=64), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "timezone_is_explicit",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "timezone_is_explicit")
    op.drop_column("users", "timezone")
