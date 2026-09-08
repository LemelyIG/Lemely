"""Parent invites: `inviterole.parent`, `invites.child_id`, `invites.reusable` (spec §3).

Two invite kinds, one table (spec §3): a student mints a single-use link (a
row with an `expires_at` and `reusable=false`, marked redeemed on use) or a
rotatable short code (`reusable=true`, no expiry, never marked redeemed —
each parent who claims it just gets a new `parent_child_links` row). Both
resolve at the existing `/join/:code` screen, so both belong on `invites`
rather than a second table that would duplicate its lifecycle.

`ALTER TYPE ... ADD VALUE` follows the additive-enum pattern of migration
`0019`: transaction-safe from PostgreSQL 12 onward as long as the new value
is only declared here and not used in the same transaction, and `IF NOT
EXISTS` keeps this re-runnable. As with `0019`, the value cannot be dropped
on downgrade — PostgreSQL has no `ALTER TYPE ... DROP VALUE`, and rebuilding
the type would have to decide what to do with any row already holding
`parent`. The downgrade therefore only reverses the columns/index/constraint
and leaves the enum value in place, same as `0019`'s downgrade does for
`rejected`.

`child_id` is nullable and FK's `users.id` `ON DELETE CASCADE`: a parent
invite is meaningless once the child account it grants access to is gone,
the same reasoning `school_id`/`class_id` already use for their targets.
`ck_invites_target` is recreated to admit `child_id` as a third valid target
so a parent invite is not rejected as "pointing at neither a school nor a
class" the way migration `0023` originally worded the constraint.

`reusable` defaults to `false` so every pre-existing row — all of them
single-use school/class invites — keeps its current, correct meaning without
a backfill.

Revision ID: 0034_parent_invites
Revises: 0033_announcement_notified_at
Create Date: 2026-09-08 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
# Kept to <=32 chars: alembic_version.version_num is varchar(32).
revision: str = "0034_parent_invites"
down_revision: str | Sequence[str] | None = "0033_announcement_notified_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the `parent` invite role, `child_id`, and `reusable`."""
    op.execute("ALTER TYPE inviterole ADD VALUE IF NOT EXISTS 'parent'")
    op.add_column(
        "invites",
        sa.Column(
            "child_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.add_column(
        "invites",
        sa.Column("reusable", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_invites_child_id", "invites", ["child_id"])
    op.drop_constraint(op.f("ck_invites_target"), "invites", type_="check")
    op.create_check_constraint(
        op.f("ck_invites_target"),
        "invites",
        "school_id IS NOT NULL OR class_id IS NOT NULL OR child_id IS NOT NULL",
    )


def downgrade() -> None:
    """Drop the columns/index/constraint. The enum value stays — see the module docstring."""
    op.drop_constraint(op.f("ck_invites_target"), "invites", type_="check")
    op.create_check_constraint(
        op.f("ck_invites_target"),
        "invites",
        "school_id IS NOT NULL OR class_id IS NOT NULL",
    )
    op.drop_index("ix_invites_child_id", table_name="invites")
    op.drop_column("invites", "reusable")
    op.drop_column("invites", "child_id")
