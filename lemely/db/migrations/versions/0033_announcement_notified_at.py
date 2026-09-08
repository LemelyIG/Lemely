"""Add ``announcements.notified_at`` and the sweeper's partial index (push-delivery spec §1).

``notified_at`` means *fan-out for this row completed*; ``NULL`` means it has
not. Deliberately a timestamp and not a boolean: it answers "when did this go
out", the question an operator investigating a missed notification asks.

The partial index over ``(publish_at) WHERE notified_at IS NULL`` is the only
shape the sweeper's claim query needs and stays tiny, because the vast majority
of rows are stamped.

No backfill. Every existing row was notified at create time by the router
(``_notify_audience``, P5.6 chunk C2b) or, for a future-dated one, never — and
the sweeper will now notify those at their ``publish_at`` if it is still ahead,
which is the correct-but-late outcome the spec accepts. Stamping them all as
notified would silently drop a scheduled post's audience.

Revision ID: 0033_announcement_notified_at
Revises: 0032_user_timezone
Create Date: 2026-09-05 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
# Kept to <=32 chars: alembic_version.version_num is varchar(32).
revision: str = "0033_announcement_notified_at"
down_revision: str | Sequence[str] | None = "0032_user_timezone"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "announcements",
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_announcements_due_unnotified",
        "announcements",
        ["publish_at"],
        postgresql_where=sa.text("notified_at IS NULL"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_announcements_due_unnotified", table_name="announcements")
    op.drop_column("announcements", "notified_at")
