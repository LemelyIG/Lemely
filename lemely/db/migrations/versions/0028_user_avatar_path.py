"""Add ``users.avatar_path`` for student/teacher profile pictures.

Additive: one nullable string column. ``NULL`` means "no avatar set" — the
honest default for every existing row, which predates this feature entirely.
No backfill: there is no prior avatar object for any account to point at.

Revision ID: 0028_user_avatar_path
Revises: 0027_option_parse_incomplete
Create Date: 2026-09-05 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
# Kept to <=32 chars: alembic_version.version_num is varchar(32).
revision: str = "0028_user_avatar_path"
down_revision: str | Sequence[str] | None = "0027_option_parse_incomplete"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "users",
        sa.Column("avatar_path", sa.String(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "avatar_path")
