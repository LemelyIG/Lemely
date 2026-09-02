"""account lifecycle timestamps on users (issue #10, D7.4 + D7.11)

Revision ID: 0021_account_lifecycle
Revises: 0020_enrolment_qual_level
Create Date: 2026-08-25 00:00:00.000000

Additive: two nullable timestamps on ``users``. No backfill and no default —
an existing account has neither verified an email through a flow that did not
exist nor accepted a consent it was never shown, and stamping "now" on either
would manufacture a fact. NULL is the honest value and both readers treat it
as such: ``email_verified_at IS NULL`` gates one route (D7.5), and
``terms_accepted_at`` is recorded for audit rather than enforced retroactively.

Reversible: ``downgrade`` drops both columns. No enum type is created here, so
there is none to drop (contrast ``0022``/``0023``).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
# Kept to <=32 chars: alembic_version.version_num is varchar(32).
revision: str = "0021_account_lifecycle"
down_revision: str | Sequence[str] | None = "0020_enrolment_qual_level"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "users",
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("terms_accepted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "terms_accepted_at")
    op.drop_column("users", "email_verified_at")
