"""push_subscriptions table + notifications.dedupe_key (P5.6 chunk A)

Revision ID: 0018_push_subscriptions
Revises: 0017_exam_dates
Create Date: 2026-08-10 12:00:00.000000

One additive table and one additive nullable column. No existing column is
altered and nothing is backfilled (D1.2/D1.3).

**Why ``notifications`` needs a column at all.** P5.6's brief said the inbox
needed no migration, because the ``notifications`` table has existed since
Phase 1. That was right about the table and wrong about the task: D5.9 6
requires ``grade_ready`` to be idempotent per *upload*, and there is nowhere
on the existing row to say which upload a notification is about in a way the
database can enforce. ``payload`` could hold it, but a JSONB value cannot be
made unique without an expression index that is strictly harder to read than
a column. So this mirrors migration ``0013``'s ``xp_events.dedupe_key``
exactly — same nullable ``String``, same **partial** unique index restricted
to ``WHERE dedupe_key IS NOT NULL``.

The partiality is the whole point, and it is worth restating rather than
cross-referencing: a plain unique index over ``(user_id, type, dedupe_key)``
would treat SQL ``NULL``s as distinct in Postgres and so would not actually
constrain anything, while a ``NOT NULL`` column would force every notification
that has no natural idempotency key to invent one. Some genuinely have none —
two ``study_plan_reminder`` notifications a week apart are two real
notifications, not a duplicate — and those rows carry ``NULL`` and are exempt
from the index. This is the same split D5.3 landed on for XP: the paper seam
dedupes, the flashcard seam deliberately does not.

**Why the dedupe key is scoped by ``type`` as well as ``user_id``.** The keys
are minted per notification type from whatever id that type is about (an
upload, an announcement). Two different types could legitimately derive the
same key from the same underlying row, and they are not duplicates of each
other. Including ``type`` keeps each type's idempotency independent, exactly
as ``0013`` includes ``source``.

**Why ``push_subscriptions.endpoint`` is globally unique rather than unique
per user.** The endpoint URL identifies a browser install, not a person. If
two users sign into one browser, the second subscription arrives with the same
endpoint; a per-user unique constraint would happily keep both rows, and the
first user's notifications would then be pushed to a browser someone else is
now using. Global uniqueness makes that shape unrepresentable and forces the
re-subscribe to move the row to the new owner. Enforcing it in the database
rather than in Python is D5.1 8's rule ("idempotency is enforced by the
database, not by care") applied to a fourth table — two tabs subscribing at
once cannot both win a unique index, but they can both pass an existence
check.

``user_id`` is ``ON DELETE CASCADE``: a deleted user must not leave live push
endpoints behind that would keep receiving their notifications.

The ``ix_push_subscriptions_user_id`` index serves the only read the send path
performs — "every endpoint for this user" — which the unique index on
``endpoint`` alone cannot answer.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0018_push_subscriptions"
down_revision: str | Sequence[str] | None = "0017_exam_dates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "notifications",
        sa.Column("dedupe_key", sa.String(), nullable=True),
    )
    op.create_index(
        "uq_notifications_user_type_dedupe",
        "notifications",
        ["user_id", "type", "dedupe_key"],
        unique=True,
        postgresql_where=sa.text("dedupe_key IS NOT NULL"),
    )
    op.create_table(
        "push_subscriptions",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("p256dh", sa.String(), nullable=False),
        sa.Column("auth", sa.String(), nullable=False),
        sa.Column("user_agent", sa.String(), nullable=True),
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
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("endpoint", name="uq_push_subscriptions_endpoint"),
    )
    op.create_index(
        "ix_push_subscriptions_user_id",
        "push_subscriptions",
        ["user_id"],
    )


def downgrade() -> None:
    """Reverse 0018: drop the push table, then the notifications dedupe column."""
    op.drop_index("ix_push_subscriptions_user_id", table_name="push_subscriptions")
    op.drop_table("push_subscriptions")
    op.drop_index("uq_notifications_user_type_dedupe", table_name="notifications")
    op.drop_column("notifications", "dedupe_key")
