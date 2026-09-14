"""``uploads.idempotency_key``: dedupe a student's ``POST /student/uploads`` retries.

Until now a double-tap on the upload button, or the offline upload queue
(Task 10) replaying a request that in fact already reached the server,
created two ``uploads`` rows and two object-storage uploads for the same
scan — ``POST /student/correct`` then marks whichever ``paperId`` the client
happened to keep, silently discarding the other. The client now sends an
``Idempotency-Key`` header it generates per upload attempt; the router looks
up a matching key for the same user before doing any work, and reuses the
row it finds instead of creating a new one.

``ux_uploads_user_idempotency`` is what actually closes the race a lookup
alone cannot: two requests racing with the same key can both miss the
lookup and both reach the insert, but only one insert can win a unique
index — the loser's ``IntegrityError`` is caught by
``StudentUploadRepository.create_upload``, which re-reads and returns the
winner's row. This is single-instance FastAPI (``anyio.to_thread`` for
blocking work); there is no distributed lock anywhere in ``lemely/`` and
none is needed here — the database is the single point of truth the race
resolves against.

The index has no time bound of its own — Postgres partial indexes cannot
express "created within the last 24h" — so the 24h dedupe window is a
business rule the repository enforces above the index: a key last used
more than 24h ago no longer counts as a match, and reusing it clears the
stale row's key before inserting the new one, freeing it back up.

Revision ID: 0036_upload_idempotency_key
Revises: 0035_merge_heads
Create Date: 2026-09-13 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
# Kept to <=32 chars: alembic_version.version_num is varchar(32).
revision: str = "0036_upload_idempotency_key"
down_revision: str | Sequence[str] | None = "0035_merge_heads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("uploads", sa.Column("idempotency_key", sa.String(length=128), nullable=True))
    op.create_index(
        "ux_uploads_user_idempotency",
        "uploads",
        ["user_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ux_uploads_user_idempotency", table_name="uploads")
    op.drop_column("uploads", "idempotency_key")
