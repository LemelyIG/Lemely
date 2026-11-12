"""waitlist applicants: the applicant's name.

Revision ID: 0053_waitlist_applicant_name
Revises: 0052_waitlist_applicants
Create Date: 2026-11-09 00:00:00.000000

Adds ``waitlist_applicants.name`` (``varchar(100)``, nullable): step 1 of the form now asks
for it. Nullable because rows created before this migration have none. Purely additive.

``downgrade`` drops the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
# Kept to <=32 chars: alembic_version.version_num is varchar(32).
revision: str = "0053_waitlist_applicant_name"
down_revision: str | Sequence[str] | None = "0052_waitlist_applicants"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("waitlist_applicants", sa.Column("name", sa.String(length=100), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("waitlist_applicants", "name")
