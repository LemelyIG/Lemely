"""tutoring safety: tutoring_reports, tutoring_blocks

Revision ID: 0050_tutoring_safety
Revises: 0049_tutor_grants_audit
Create Date: 2026-10-25 00:00:00.000000

Two new tables (SPEC ``docs/tutoring/SPEC.md`` §a.2, §f). Entirely additive.

* ``tutoring_reports``: a report names exactly one target, the one its
  ``target_type`` says (``ck_tutoring_reports_one_target``); targets are never
  hard-deleted, so every target FK is ``RESTRICT``. The queue index sorts
  ``safety_concern`` first (SC-10); one open report per reporter and target
  (``uq_tutoring_reports_open_per_reporter``).
* ``tutoring_blocks``: keyed on ``users.id`` both ways. Rows are never deleted
  (an unblock sets ``removed_at``), so "this student ever blocked this tutor"
  stays answerable for the outcome exclusion (ADR-T04).

``downgrade`` drops both tables in reverse.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
# Kept to <=32 chars: alembic_version.version_num is varchar(32).
revision: str = "0050_tutoring_safety"
down_revision: str | Sequence[str] | None = "0049_tutor_grants_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: (column, referred table) for each of the five report targets.
_TARGETS: tuple[tuple[str, str], ...] = (
    ("tutor_profile_id", "tutor_profiles"),
    ("review_id", "tutor_reviews"),
    ("reply_id", "tutor_review_replies"),
    ("booking_id", "tutor_bookings"),
    ("note_id", "tutor_booking_notes"),
)


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
    ]


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "tutoring_reports",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("reporter_user_id", sa.UUID(), nullable=True),
        sa.Column(
            "reporter_party",
            postgresql.ENUM(name="bookingparty", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "target_type",
            postgresql.ENUM(name="reporttargettype", create_type=False),
            nullable=False,
        ),
        *(sa.Column(column, sa.UUID(), nullable=True) for column, _table in _TARGETS),
        sa.Column("target_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("reason", postgresql.ENUM(name="reportreason", create_type=False), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column(
            "state",
            postgresql.ENUM(name="reportstate", create_type=False),
            server_default=sa.text("'open'::reportstate"),
            nullable=False,
        ),
        sa.Column(
            "resolution",
            postgresql.ENUM(name="reportresolution", create_type=False),
            nullable=True,
        ),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("resolved_by", sa.UUID(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "reporter_party IN ('student', 'parent', 'tutor')",
            name=op.f("ck_tutoring_reports_reporter_party_allowed"),
        ),
        sa.CheckConstraint(
            "num_nonnulls(tutor_profile_id, review_id, reply_id, booking_id, note_id) = 1 "
            "AND (target_type <> 'tutor_profile' OR tutor_profile_id IS NOT NULL) "
            "AND (target_type <> 'review' OR review_id IS NOT NULL) "
            "AND (target_type <> 'review_reply' OR reply_id IS NOT NULL) "
            "AND (target_type <> 'booking' OR booking_id IS NOT NULL) "
            "AND (target_type <> 'booking_note' OR note_id IS NOT NULL)",
            name=op.f("ck_tutoring_reports_one_target"),
        ),
        sa.CheckConstraint(
            "char_length(details) <= 1000", name=op.f("ck_tutoring_reports_details_len")
        ),
        sa.CheckConstraint(
            "(state = 'open') = (resolution IS NULL)",
            name=op.f("ck_tutoring_reports_resolution_matches_state"),
        ),
        sa.CheckConstraint(
            "char_length(resolution_note) <= 1000",
            name=op.f("ck_tutoring_reports_resolution_note_len"),
        ),
        sa.ForeignKeyConstraint(
            ["reporter_user_id"],
            ["users.id"],
            name=op.f("fk_tutoring_reports_reporter_user_id_users"),
            ondelete="SET NULL",
        ),
        *(
            sa.ForeignKeyConstraint(
                [column],
                [f"{table}.id"],
                name=op.f(f"fk_tutoring_reports_{column}_{table}"),
                ondelete="RESTRICT",
            )
            for column, table in _TARGETS
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by"],
            ["users.id"],
            name=op.f("fk_tutoring_reports_resolved_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tutoring_reports")),
    )
    op.create_index(
        "ix_tutoring_reports_queue",
        "tutoring_reports",
        ["state", sa.text("(reason = 'safety_concern') DESC"), "created_at", "id"],
    )
    op.create_index(
        "uq_tutoring_reports_open_per_reporter",
        "tutoring_reports",
        [
            "reporter_user_id",
            "target_type",
            sa.text("COALESCE(tutor_profile_id, review_id, reply_id, booking_id, note_id)"),
        ],
        unique=True,
        postgresql_where=sa.text("state = 'open'"),
    )
    op.create_index(
        "ix_tutoring_reports_reporter_day",
        "tutoring_reports",
        ["reporter_user_id", "created_at"],
    )
    for column, _table in _TARGETS:
        op.create_index(
            f"ix_tutoring_reports_{column}",
            "tutoring_reports",
            [column],
            postgresql_where=sa.text(f"{column} IS NOT NULL"),
        )
    op.create_index(
        "ix_tutoring_reports_resolved_by",
        "tutoring_reports",
        ["resolved_by"],
        postgresql_where=sa.text("resolved_by IS NOT NULL"),
    )

    op.create_table(
        "tutoring_blocks",
        sa.Column("blocker_user_id", sa.UUID(), nullable=False),
        sa.Column("blocked_user_id", sa.UUID(), nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "blocker_user_id <> blocked_user_id", name=op.f("ck_tutoring_blocks_not_self")
        ),
        sa.ForeignKeyConstraint(
            ["blocker_user_id"],
            ["users.id"],
            name=op.f("fk_tutoring_blocks_blocker_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["blocked_user_id"],
            ["users.id"],
            name=op.f("fk_tutoring_blocks_blocked_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "blocker_user_id", "blocked_user_id", name=op.f("pk_tutoring_blocks")
        ),
    )
    op.create_index(
        "ix_tutoring_blocks_blocked",
        "tutoring_blocks",
        ["blocked_user_id", "blocker_user_id"],
    )


def downgrade() -> None:
    """Downgrade schema: drop both tables in reverse (indexes go with them)."""
    op.drop_table("tutoring_blocks")
    op.drop_table("tutoring_reports")
