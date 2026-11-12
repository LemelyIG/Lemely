"""waitlist applicants: email confirmation (double opt-in).

Revision ID: 0054_waitlist_email_confirmation
Revises: 0053_waitlist_applicant_name
Create Date: 2026-11-10 00:00:00.000000

Six columns on ``waitlist_applicants`` and one partial unique index. Additive.

* ``email_confirmed_at``: when the emailed link was used. ``email_confirmed`` (0052) is the flag.
* ``confirm_token_hash`` / ``confirm_token_expires_at``: SHA-256 of the newest emailed token
  (never the token) and the expiry shared by the links of the current window. The partial
  unique index serves the lookup.
* ``confirm_prev_hashes``: digests of the earlier links of the window, so a re-send does not
  invalidate a link already in the owner's inbox.
* ``confirm_sent_at`` / ``confirm_send_count``: when a mail was last issued (the per-address
  resend throttle) and how many went out in the current window (the cap).

``downgrade`` drops the index and the six columns.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
# Kept to <=32 chars: alembic_version.version_num is varchar(32).
revision: str = "0054_waitlist_email_confirmation"
down_revision: str | Sequence[str] | None = "0053_waitlist_applicant_name"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "waitlist_applicants"
INDEX = "uq_waitlist_applicants_confirm_token_hash"


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(TABLE, sa.Column("email_confirmed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(TABLE, sa.Column("confirm_token_hash", sa.String(length=64), nullable=True))
    op.add_column(
        TABLE, sa.Column("confirm_token_expires_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(TABLE, sa.Column("confirm_sent_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        TABLE,
        sa.Column(
            "confirm_prev_hashes",
            postgresql.ARRAY(sa.String(length=64)),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
    )
    op.add_column(
        TABLE,
        sa.Column("confirm_send_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.create_index(
        INDEX,
        TABLE,
        ["confirm_token_hash"],
        unique=True,
        postgresql_where=sa.text("confirm_token_hash IS NOT NULL"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(INDEX, table_name=TABLE, postgresql_where=sa.text("confirm_token_hash IS NOT NULL"))
    op.drop_column(TABLE, "confirm_send_count")
    op.drop_column(TABLE, "confirm_prev_hashes")
    op.drop_column(TABLE, "confirm_sent_at")
    op.drop_column(TABLE, "confirm_token_expires_at")
    op.drop_column(TABLE, "confirm_token_hash")
    op.drop_column(TABLE, "email_confirmed_at")
