"""component and option grade thresholds

Revision ID: 0025_thresholds
Revises: 0024_reference_catalogue
Create Date: 2026-09-02 00:00:00.000000

Two additive tables. Cambridge publishes two threshold tables in one
document and they mean different things:

* ``component_thresholds`` — minimum raw marks per grade for **one paper**.
  This is what Lemely grades a single marked paper against. The official
  documents state, in these words, that "Grade A* does not exist at the
  level of an individual component" — so the highest grade a component row
  can carry is A. ``verified`` records whether every grade in the row was
  confirmed against the official PDF; ``False`` means the row came from
  ciegt alone. Nothing downstream may cite Cambridge as the source of an
  unverified row.
* ``option_thresholds`` — thresholds for a weighted **combination** of
  components (e.g. option ``BX`` = components 21, 41, 51). This is the only
  place A* appears, and exists so Lemely can derive which grades a student
  may realistically target. ``max_mark_after_weighting`` is nullable: the
  pre-2020 CAIE layout prints ``Option A* A B C D E F G`` with no maximum
  mark column at all, and a NOT NULL column here would make every such
  session unstorable.

Both tables store raw marks (``thresholds`` JSONB, alongside ``max_mark`` /
``max_mark_after_weighting``) rather than pre-computed percentages, so every
stored number is one a human can check directly against the source document.
``source_url`` is NOT NULL on both: a threshold row that cannot name where it
came from is indistinguishable from an invented one, and these numbers decide
real students' grades.

Reuses the existing ``examboard`` and ``sessionmonth`` enum types
(``create_type=False``) — this migration creates no new enum type, so
``downgrade`` drops none.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0025_thresholds"
down_revision: str | Sequence[str] | None = "0024_reference_catalogue"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "component_thresholds",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "board",
            postgresql.ENUM("caie", "edexcel", "oxford_aqa", name="examboard", create_type=False),
            nullable=False,
            server_default=sa.text("'caie'::examboard"),
        ),
        sa.Column("subject_code", sa.String(), nullable=False),
        sa.Column(
            "session_month",
            postgresql.ENUM(
                "may_june", "oct_nov", "feb_mar", "specimen", name="sessionmonth", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("session_year", sa.Integer(), nullable=False),
        sa.Column("paper_number", sa.Integer(), nullable=False),
        sa.Column("paper_variant", sa.Integer(), nullable=False),
        sa.Column("max_mark", sa.Integer(), nullable=False),
        sa.Column("thresholds", postgresql.JSONB(), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False),
        sa.Column("source_url", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "board", "subject_code", "session_month", "session_year", "paper_number", "paper_variant",
            name="uq_component_thresholds_identity",
        ),
    )
    op.create_index(
        "ix_component_thresholds_lookup", "component_thresholds", ["board", "subject_code", "session_year"]
    )

    op.create_table(
        "option_thresholds",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "board",
            postgresql.ENUM("caie", "edexcel", "oxford_aqa", name="examboard", create_type=False),
            nullable=False,
            server_default=sa.text("'caie'::examboard"),
        ),
        sa.Column("subject_code", sa.String(), nullable=False),
        sa.Column(
            "session_month",
            postgresql.ENUM(
                "may_june", "oct_nov", "feb_mar", "specimen", name="sessionmonth", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("session_year", sa.Integer(), nullable=False),
        sa.Column("option_code", sa.String(), nullable=False),
        sa.Column("component_numbers", postgresql.JSONB(), nullable=False),
        sa.Column("max_mark_after_weighting", sa.Integer(), nullable=True),
        sa.Column("thresholds", postgresql.JSONB(), nullable=False),
        sa.Column("source_url", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "board", "subject_code", "session_month", "session_year", "option_code",
            name="uq_option_thresholds_identity",
        ),
    )


def downgrade() -> None:
    """Reverse 0025: drop both threshold tables and their index.

    Neither ``examboard`` nor ``sessionmonth`` is dropped — both predate this
    migration and are reused read-only (``create_type=False`` above is the
    matching half of that), so this migration creates no enum type and drops
    none.
    """
    op.drop_table("option_thresholds")
    op.drop_index("ix_component_thresholds_lookup", table_name="component_thresholds")
    op.drop_table("component_thresholds")
