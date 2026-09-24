"""Add I6's per-point verdict columns to `question_result_points`.

US-045 (task #45, `PLAN-point-verdicts.md`). `CorrectedQuestion.point_verdicts`
is produced by I6's verdict path (`_build_ai_corrected_from_verdicts`) and, until
this migration, reaches no table: `grep -rn "point_verdicts" lemely/db/
lemely/web/` returns zero hits, so a teacher reviewing a question sees `withheld`
and `unverifiable` both collapsed into `awarded=False` — the exact distinction I6
exists to carry.

**Three columns, not four.** `PointVerdict.note` is deliberately NOT a new
column: `derive_point_rows` already writes `CorrectedQuestion.point_notes` onto
the existing `rationale` column, and `PointVerdict.note` is the same concept
from the verdict path. A second column would be the ninth formulation of "did a
marker score this and why" — the disease `0040_marker_source_blank` spent a
migration curing for `marker_source`, where eight formulations cost nine
hand-found consumers. `PointVerdict.evidence_box` went nowhere either: it was
typed `None` and rejected every non-`None` value, and was deleted in
`ccf230ee` for exactly that reason -- it never had a fourth column to give.

* `verdict` — text, nullable. `NULL` for a point scored by the legacy
  (non-verdict) path.
* `evidence_span` — text, not-null, default `''`, matching `PointVerdict`'s own
  default so an absent verdict and an empty quote read the same.
* `ecf_applied` — bool, not-null, default `false`.

Follows `0040_marker_source_blank`. `downgrade()` drops all three, restoring
the pre-migration shape exactly (no backfill either direction: a row's verdict
data does not survive a downgrade/upgrade round trip, same posture as every
other lossy migration on this table).

Revision ID: 0041_point_verdict_columns
Revises: 0040_marker_source_blank
Create Date: 2026-09-23 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0041_point_verdict_columns"
down_revision: str | Sequence[str] | None = "0040_marker_source_blank"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "question_result_points",
        sa.Column("verdict", sa.Text(), nullable=True),
    )
    op.add_column(
        "question_result_points",
        sa.Column(
            "evidence_span", sa.Text(), nullable=False, server_default=sa.text("''")
        ),
    )
    op.add_column(
        "question_result_points",
        sa.Column(
            "ecf_applied", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("question_result_points", "ecf_applied")
    op.drop_column("question_result_points", "evidence_span")
    op.drop_column("question_result_points", "verdict")
