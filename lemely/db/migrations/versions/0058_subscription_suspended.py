"""Record when Paymob suspended a subscription (Paymob billing phase 05, task 8).

Revision ID: 0058_subscription_suspended
Revises: 0057_admin_audit_log
Create Date: 2026-11-14 00:00:00.000000

Additive: ``subscriptions.suspended_at`` (nullable ``timestamptz``). A Paymob ``suspended``
callback turns the subscription into a cancel at period end, and a ``resumed`` callback must
undo exactly that cancel and no other: one the payer asked for stays. The column is the cause
marker. It is set when a suspension schedules the cancel, and cleared by a resume, by the payer's
own cancel and by a Paymob ``canceled`` callback. NULL for every existing row: none was suspended
through this code.

**Lock behaviour**, as 0037/0038/0056: both directions take ACCESS EXCLUSIVE on ``subscriptions``
while the old revision may be serving traffic, so ``SET lock_timeout`` first makes a blocked
statement fail fast and retriably. ``env.py`` runs one ``alembic upgrade``/``downgrade`` in ONE
transaction, so both directions ``RESET lock_timeout`` before returning, or the timeout would
leak into the next migration of the run.

``downgrade`` refuses while any row has ``suspended_at`` set: dropping the column would turn a
suspended plan that a ``resumed`` callback should restore into one that ends at period end,
silently (the 0054/0055/0056 precedent). Otherwise it drops the column and nothing else.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
# Kept to <=32 chars: alembic_version.version_num is varchar(32).
revision: str = "0058_subscription_suspended"
down_revision: str | Sequence[str] | None = "0057_admin_audit_log"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("SET lock_timeout = '5s'")
    op.add_column(
        "subscriptions", sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.execute("RESET lock_timeout")


def downgrade() -> None:
    """Downgrade schema.

    Refuses while a suspension is recorded (see the module docstring).
    """
    op.execute("SET lock_timeout = '5s'")
    if (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM subscriptions WHERE suspended_at IS NOT NULL LIMIT 1"))
        .first()
        is not None
    ):
        raise RuntimeError(
            "Cannot downgrade 0058_subscription_suspended: subscriptions still has a "
            "suspended_at set. Dropping the column would make a suspended plan end at period "
            "end even if Paymob resumes it. Downgrading past 0058 is not possible while any "
            "suspension is recorded."
        )
    op.drop_column("subscriptions", "suspended_at")
    op.execute("RESET lock_timeout")
