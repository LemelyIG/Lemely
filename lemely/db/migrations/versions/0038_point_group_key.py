"""question_result_points: group_key + group_max_marks (self-review spec, D6)

Revision ID: 0038_point_group_key
Revises: 0037_question_result_pts
Create Date: 2026-09-18 00:00:00.000000

Two additive nullable columns, **no data migration**. ``group_key`` names the
mark-scheme group a point belongs to (``alt:n`` either/or run, ``pool:n``
"any N from" pool, NULL when independent) and ``group_max_marks`` is the most
that group can contribute. Both are derived from the parsed scheme at
correction time (``lemely/db/question_points.py``).

Rows written before this revision keep NULL, and there is nothing honest to
backfill them from — the parsed scheme is not kept. An earlier draft of this
note added that those attempts "have no self-review surface (spec 1 D7)",
which is false: 0037 writes the point rows and is deployed ahead of this
revision, so rows exist with points and without group data, and self-review
is offered on exactly the rows that have points. Left there, an either/or
pair on such a row pays out twice. The read side therefore refuses them —
``lemely.db.self_review_repo.points_are_settleable`` withholds any question
whose grouped points carry no group, rather than capping by guesswork.

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
