"""Record whether an option row's grade cells were all readable.

An unreadable grade cell is dropped from ``thresholds``, which leaves it
indistinguishable from a genuine "not applicable at this tier" absence.
Components signal the same doubt with ``verified=False``; options had no
equivalent, so a garbled cell left only a transient log line -- and option
thresholds are what ``ThresholdService.target_vocabularies`` turns into the
grade choices a student is shown.

Existing rows default to ``false``. That is not a claim they were all read
cleanly: they were ingested before the flag existed and were never checked.
Re-run ``scripts/ingest_thresholds.py`` to populate it truthfully (the same
re-ingest ``docs/deployment.md`` §3.5 already asks for).

Revision ID: 0027_option_parse_incomplete
Revises: 0026_component_max_mark_positive
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0027_option_parse_incomplete"
down_revision = "0026_component_max_mark_positive"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "option_thresholds",
        sa.Column(
            "parse_incomplete",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("option_thresholds", "parse_incomplete")
