"""question_result_points: group_key + group_max_marks (self-review spec, D6)

Revision ID: 0038_point_group_key
Revises: 0037_question_result_pts
Create Date: 2026-09-18 00:00:00.000000

Two additive nullable columns, **no data migration**. ``group_key`` names the
mark-scheme group a point belongs to (``alt:n`` either/or run, ``pool:n``
"any N from" pool, NULL when independent) and ``group_max_marks`` is the most
that group can contribute. Both are derived from the parsed scheme at
correction time (``lemely/db/question_points.py``); rows written before this
revision keep NULL — the attempts behind them have no self-review surface
(spec 1 D7), so there is nothing to protect and nothing honest to backfill
from.

Reversible: ``downgrade`` drops the two columns.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
# Kept to <=32 chars: alembic_version.version_num is varchar(32).
revision: str = "0038_point_group_key"
down_revision: str | Sequence[str] | None = "0037_question_result_pts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("question_result_points", sa.Column("group_key", sa.Text(), nullable=True))
    op.add_column(
        "question_result_points", sa.Column("group_max_marks", sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("question_result_points", "group_max_marks")
    op.drop_column("question_result_points", "group_key")
