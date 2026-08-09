"""study_plans: persisted adaptive study plan + sessions (P4.7 chunk B).

Revision ID: 0012_study_plans
Revises: 0011_flashcards
Create Date: 2026-08-08 00:00:00.000000

Two additive tables, no existing column touched (D1.2/D1.3):

* ``study_plans`` — one generated week's plan for one ``(user_id,
  subject_code, week_start)``. ``week_start`` is the Monday-aligned ISO week
  a plan was generated for (``lemely.db.study_plan_repo._week_start``) — the
  identity "the current week" resolves against. ``available``/``reason``
  persist chunk A's honesty distinction verbatim: a ``no_signal`` refusal
  (``available=false``) never reads back indistinguishable from the real
  "nothing to schedule this week" state (``available=true``, no sessions).
* ``study_plan_sessions`` — one concrete scheduled session, ``plan_id``
  CASCADE, plus ``completed_at`` (the P5 XP seam this chunk deliberately
  stops at — no XP/points/streak column anywhere here).

**Weekly regeneration supersedes, never mutates.** ``uq_study_plans_active``
(partial unique, ``WHERE superseded_at IS NULL``) makes "at most one active
plan per (student, subject, week)" a database invariant: a later
``generate()`` call for the same week sets the previous row's
``superseded_at`` and inserts a new one, never rewriting the old plan or its
sessions — a student's recorded completion on a superseded plan's session is
never touched.

**Enum type creation** follows ``0009``/``0010``/``0011``'s pattern exactly:
``studyplanactivitytype`` is created explicitly with ``checkfirst=True``
before any column references it, and the column uses
``postgresql.ENUM(..., create_type=False)`` so SQLAlchemy never re-issues
``CREATE TYPE``. It mirrors (does not import) ``lemely.core.study
.ActivityType`` member-for-member — see the docstrings in
``lemely/db/models/study_plan.py`` for why that duplication is intentional
(the same reason ``0011``'s ``reviewgrade`` duplicates the core SM-2 grade
vocabulary).

Downgrade drops tables in reverse dependency order (sessions before plans),
then drops the one enum type.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0012_study_plans"
down_revision: str | Sequence[str] | None = "0011_flashcards"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()

    postgresql.ENUM(
        "practice", "flashcards", "past_paper", "review", name="studyplanactivitytype"
    ).create(bind, checkfirst=True)

    activity_type = postgresql.ENUM(
        "practice",
        "flashcards",
        "past_paper",
        "review",
        name="studyplanactivitytype",
        create_type=False,
    )

    # --- study_plans -----------------------------------------------------
    op.create_table(
        "study_plans",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("subject_code", sa.String(), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("weekly_hours", sa.Float(), nullable=False),
        sa.Column("available", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_study_plans_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_study_plans")),
    )
    op.create_index(
        "ix_study_plans_user_subject_week",
        "study_plans",
        ["user_id", "subject_code", "week_start"],
    )
    op.create_index(
        "uq_study_plans_active",
        "study_plans",
        ["user_id", "subject_code", "week_start"],
        unique=True,
        postgresql_where=sa.text("superseded_at IS NULL"),
    )

    # --- study_plan_sessions ----------------------------------------------
    op.create_table(
        "study_plan_sessions",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("plan_id", sa.UUID(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("topic", sa.String(), nullable=False),
        sa.Column("activity_type", activity_type, nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("focus", sa.Text(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"],
            ["study_plans.id"],
            name=op.f("fk_study_plan_sessions_plan_id_study_plans"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_study_plan_sessions")),
    )
    op.create_index(
        "ix_study_plan_sessions_plan_id_date",
        "study_plan_sessions",
        ["plan_id", "date"],
    )


def downgrade() -> None:
    """Reverse 0012: drop tables in reverse dependency order, then the enum type."""
    op.drop_index("ix_study_plan_sessions_plan_id_date", table_name="study_plan_sessions")
    op.drop_table("study_plan_sessions")

    op.drop_index("uq_study_plans_active", table_name="study_plans")
    op.drop_index("ix_study_plans_user_subject_week", table_name="study_plans")
    op.drop_table("study_plans")

    bind = op.get_bind()
    postgresql.ENUM(name="studyplanactivitytype").drop(bind, checkfirst=True)
