"""paper soft delete: deleted_at, withdrawn review items, class exclusions

Revision ID: 0039_paper_soft_delete
Revises: 0038_point_group_key
Create Date: 2026-09-22 00:00:00.000000

The product's first soft delete (design 2026-09-22 §3). Entirely additive: three
nullable timestamps, one nullable timestamp on the review queue, two enum
values, one boolean preference column, and one table. No backfill — a NULL
``deleted_at`` is exactly "not deleted", which is true of every existing row.

The partial index carries ``WHERE deleted_at IS NOT NULL`` because its only
readers are the purge candidate query and the recently-deleted list, both of
which look at the small deleted minority. A full index would be mostly NULLs.

``notification_preferences.review_withdrawn`` is added here (review amendment
2026-09-24, R10) because ``NotificationType.review_withdrawn`` would otherwise
break the enum/preference-column vocabulary pin
(``test_notification_type_enum_matches_preference_columns``) the moment it
lands. ``teacher_papers.deleted_at`` is also added here (R I4) so a later task
never has to edit an already-applied migration.

``downgrade`` reverses the schema — drops the columns, the index and the table
— but that is **not** the same as reversing behaviour, and it is not a safe
incident-response rollback on its own. Two things it cannot undo: the added
enum values (Postgres has no ``DROP VALUE``, and recreating
``reviewstatus``/``notificationtype`` would mean rewriting every dependent
column for no benefit — this matches how 0037 handled ``reviewreason``), and
the fact that dropping ``deleted_at`` makes every already-deleted paper
visible again, which is true regardless of which application code is running.
``downgrade`` clears the ``review_withdrawn`` notifications and
``withdrawn`` review-queue rows first so pre-0039 code does not 500 reading
them, but the visibility change is unavoidable and is documented, with the
incident-response alternative, in ``docs/deployment.md`` §5.7.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
# Kept to <=32 chars: alembic_version.version_num is varchar(32).
revision: str = "0039_paper_soft_delete"
down_revision: str | Sequence[str] | None = "0038_point_group_key"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TYPE reviewstatus ADD VALUE IF NOT EXISTS 'withdrawn'")
    op.execute("ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'review_withdrawn'")

    op.add_column("attempts", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("uploads", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "teacher_papers", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "review_queue", sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "notification_preferences",
        sa.Column(
            "review_withdrawn", sa.Boolean(), server_default=sa.true(), nullable=False
        ),
    )

    op.create_index(
        "ix_attempts_deleted_at",
        "attempts",
        ["deleted_at"],
        postgresql_where=sa.text("deleted_at IS NOT NULL"),
    )

    op.create_table(
        "class_paper_exclusions",
        sa.Column("class_id", sa.UUID(), nullable=False),
        sa.Column("attempt_id", sa.UUID(), nullable=False),
        sa.Column("excluded_by", sa.UUID(), nullable=True),
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
            ["class_id"],
            ["classes.id"],
            name="fk_class_paper_exclusions_class_id_classes",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["attempts.id"],
            name="fk_class_paper_exclusions_attempt_id_attempts",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["excluded_by"],
            ["users.id"],
            name="fk_class_paper_exclusions_excluded_by_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("class_id", "attempt_id", name="pk_class_paper_exclusions"),
    )


def downgrade() -> None:
    """Downgrade schema. The two enum values stay; Postgres cannot drop them.

    Clears the rows pre-0039 code cannot load through the old enums before
    dropping the columns — see the module docstring and ``docs/deployment.md``
    §5.7 for what this does and does not restore.
    """
    op.execute("DELETE FROM notifications WHERE type = 'review_withdrawn'")
    op.execute("UPDATE review_queue SET status = 'dismissed' WHERE status = 'withdrawn'")
    op.drop_table("class_paper_exclusions")
    op.drop_index("ix_attempts_deleted_at", table_name="attempts")
    op.drop_column("notification_preferences", "review_withdrawn")
    op.drop_column("review_queue", "withdrawn_at")
    op.drop_column("teacher_papers", "deleted_at")
    op.drop_column("uploads", "deleted_at")
    op.drop_column("attempts", "deleted_at")
