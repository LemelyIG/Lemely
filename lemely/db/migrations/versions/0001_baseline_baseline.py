"""baseline (empty): establish Alembic version tracking.

The application schema is introduced by the following migration. This baseline
carries no schema changes; it exists so the local Supabase Postgres (which
starts with only the ``auth``/``storage`` schemas) has a known Alembic head.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-07-30 11:22:19.307621
"""

from __future__ import annotations

# revision identifiers, used by Alembic.
revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No-op baseline."""


def downgrade() -> None:
    """No-op baseline."""
