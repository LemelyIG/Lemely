"""student_profiles: leaderboard opt-out flag (P5.3 chunk A, D5.1 §9).

Revision ID: 0014_leaderboard_opt_out
Revises: 0013_xp_subject_dedupe
Create Date: 2026-08-09 00:00:00.000000

One additive column, no existing column touched (D1.2/D1.3):

* ``student_profiles.leaderboard_opt_out`` — ``Boolean``, ``NOT NULL``,
  ``server_default false``. D5.1 §9 puts the flag on ``student_profiles``
  rather than ``users`` because leaderboards are a student-only surface and
  the flag belongs with the student profile it already governs. ``NOT NULL``
  with a server default is safe here (unlike ``xp_events.dedupe_key`` in
  migration ``0013``, which had to stay nullable): every pre-existing
  ``student_profiles`` row unambiguously defaults to "not opted out", which
  is the correct historical value for a flag that did not previously exist —
  there is no meaningless-backfill problem the way there would have been for
  a dedupe identity.

  Enforced in ``lemely.db.leaderboard_repo`` in the query's ``WHERE`` clause,
  never filtered in a DTO or route layer (D5.1 §9) — a row that never leaves
  Postgres cannot leak through a serialization bug or a future endpoint that
  reuses the repo function and forgets the filter.

Reversible: the column is dropped in ``downgrade``, leaving
``student_profiles`` exactly as migration ``0013`` (unaffected by this
column) left it.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0014_leaderboard_opt_out"
down_revision: str | Sequence[str] | None = "0013_xp_subject_dedupe"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "student_profiles",
        sa.Column(
            "leaderboard_opt_out",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    """Reverse 0014: drop the opt-out column."""
    op.drop_column("student_profiles", "leaderboard_opt_out")
