"""announcement_reads table (P5.5 chunk A)

Revision ID: 0016_announcement_reads
Revises: 0015_friendships
Create Date: 2026-08-10 00:00:00.000000

One additive table, no existing column touched (D1.2/D1.3).

**A read receipt is the existence of a row, not a boolean on a row.** The
obvious alternative — a ``read`` flag somewhere — has nowhere to live:
``announcements`` is one row per *audience*, not per recipient (a class-wide
post is a single row that hundreds of students see, D3.14 3), so a flag on
it would be a single global bit shared by every reader. A join table is the
only shape that can say "this user read this announcement" at all.

``read_at`` is therefore never nullable and never ``false``: the row exists
if and only if the announcement was read, and it records when. There is no
"unread row" state, which means unread is computed as an absence
(``NOT EXISTS`` / outer join ``IS NULL``) and a student who has never opened
the app has no rows here rather than one per announcement in scope. That
matters at the scale this table is written at: read receipts are the highest
write-volume thing in the engagement layer, and pre-seeding a row per
(student, announcement) pair would multiply the table by the class size for
announcements nobody ever opens.

**``uq_announcement_reads_pair`` is what makes marking-as-read idempotent.**
The student surface will fire "mark read" on every open of the same
announcement, and re-opening one must not append a second row and must not
move the original ``read_at`` (first-read time is the useful number; a
"last opened" timestamp is a different feature nobody asked for). Making the
pair unique in the database rather than checking-then-inserting in Python is
the same choice migrations ``0013`` (``xp_events.dedupe_key``) and ``0015``
(``uq_friendships_pair``) already made, for the same reason: two concurrent
requests from two tabs cannot both pass a Python existence check, but they
cannot both win a unique index. D5.1 8, "idempotency is enforced by the
database, not by care", applied to a third table.

Both FKs are ``ON DELETE CASCADE``. Deleting an announcement (the teacher
route already supports this) must not strand receipts pointing at a row that
no longer exists, and neither must deleting a user.

The ``(user_id, announcement_id)`` index exists for the read direction the
student surface actually uses — "which of the announcements in my scope have
I read" is always keyed by user first. The unique constraint's own index is
ordered ``(announcement_id, user_id)`` and cannot serve that query.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0016_announcement_reads"
down_revision: str | Sequence[str] | None = "0015_friendships"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "announcement_reads",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "announcement_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=False),
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
            ["announcement_id"],
            ["announcements.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "announcement_id",
            "user_id",
            name="uq_announcement_reads_pair",
        ),
    )
    op.create_index(
        "ix_announcement_reads_user_id_announcement_id",
        "announcement_reads",
        ["user_id", "announcement_id"],
    )


def downgrade() -> None:
    """Reverse 0016: drop the read-receipt table and its index."""
    op.drop_index(
        "ix_announcement_reads_user_id_announcement_id",
        table_name="announcement_reads",
    )
    op.drop_table("announcement_reads")
