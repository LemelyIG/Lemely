"""flashcard decks: generation status (redesign L10).

Revision ID: 0055_flashcard_generation
Revises: 0054_waitlist_email_confirmation
Create Date: 2026-11-15 00:00:00.000000

Four columns and one check constraint on ``flashcard_decks``. Additive.

* ``generation_status``: ``writing`` / ``ready`` / ``failed``, NOT NULL, default ``ready`` so
  every existing deck reads as ready without a backfill.
* ``requested_count``: the card count the student asked the model for.
* ``generation_started_at``: start of the current writing attempt (stale detection).
* ``generation_error``: a short machine code when writing failed.

``downgrade`` drops the constraint and the four columns.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
# Kept to <=32 chars: alembic_version.version_num is varchar(32).
revision: str = "0055_flashcard_generation"
down_revision: str | Sequence[str] | None = "0054_waitlist_email_confirmation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "flashcard_decks"
CHECK = "ck_flashcard_decks_generation_status"


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        TABLE,
        sa.Column(
            "generation_status",
            sa.String(length=16),
            server_default=sa.text("'ready'"),
            nullable=False,
        ),
    )
    op.add_column(TABLE, sa.Column("requested_count", sa.Integer(), nullable=True))
    op.add_column(
        TABLE, sa.Column("generation_started_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(TABLE, sa.Column("generation_error", sa.String(length=64), nullable=True))
    op.create_check_constraint(
        op.f(CHECK), TABLE, "generation_status IN ('writing', 'ready', 'failed')"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(op.f(CHECK), TABLE, type_="check")
    op.drop_column(TABLE, "generation_error")
    op.drop_column(TABLE, "generation_started_at")
    op.drop_column(TABLE, "requested_count")
    op.drop_column(TABLE, "generation_status")
