"""Suspension marker and the replaced renewal amount (Paymob billing phase 05, task 8).

Revision ID: 0058_suspend_and_prev_amount
Revises: 0057_admin_audit_log
Create Date: 2026-11-14 00:00:00.000000

Additive, all on ``subscriptions`` and all nullable:

* ``suspended_at`` (``timestamptz``). A Paymob ``suspended`` callback turns the subscription into
  a cancel at period end, and a ``resumed`` callback must undo exactly that cancel and no other:
  one the payer asked for stays. The column is the cause marker. It is set when a suspension
  schedules the cancel, and cleared by a resume, by the payer's own cancel, by a Paymob
  ``canceled`` callback and when the plan ends.
* ``previous_amount_minor`` (``bigint``) and ``amount_replaced_at`` (``timestamptz``), paired by
  ``ck_subscriptions_previous_amount_paired``. Paymob can charge up to three days early, so a PUT
  that replaces the renewal amount can land after Paymob has already charged the old one. The
  columns keep the amount a PUT replaced and when, so a renewal charged at that amount before the
  replacement is still paid (and nothing else is). They are cleared once a renewal grants a period
  and when the plan ends.
* ``amount_sync_uncertain_at`` (``timestamptz``): set when the last amount PUT had an unknown
  outcome (Paymob may hold an amount the stamp does not show), so the next sweep repeats it on any
  replica after any restart. Cleared by a PUT that succeeds and when the plan ends.

NULL for every existing row. **Lock behaviour**, as 0037/0038/0056: both directions take ACCESS
EXCLUSIVE on ``subscriptions`` while the old revision may be serving traffic, so ``SET
lock_timeout`` first makes a blocked statement fail fast and retriably. ``env.py`` runs one
``alembic upgrade``/``downgrade`` in ONE transaction, so both directions ``RESET lock_timeout``
before returning, or the timeout would leak into the next migration of the run.

The CHECK is added ``NOT VALID`` and then validated, so the ACCESS EXCLUSIVE lock is held only for
the catalogue change and the scan runs under the lighter ``SHARE UPDATE EXCLUSIVE`` lock.

``downgrade`` refuses while any row has ``suspended_at``, ``previous_amount_minor`` or
``amount_sync_uncertain_at`` set (the 0054/0055/0056 precedent): dropping the first would make a
suspended plan end at period end even if Paymob resumes it, the second would turn a paid early
renewal into a mismatch, and the third would forget that Paymob's amount is unconfirmed.
Otherwise it drops what the upgrade added, in reverse order, and nothing else.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
# Kept to <=32 chars: alembic_version.version_num is varchar(32).
revision: str = "0058_suspend_and_prev_amount"
down_revision: str | Sequence[str] | None = "0057_admin_audit_log"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PAIRED_CHECK = "ck_subscriptions_previous_amount_paired"


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("SET lock_timeout = '5s'")
    op.add_column(
        "subscriptions", sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "subscriptions", sa.Column("previous_amount_minor", sa.BigInteger(), nullable=True)
    )
    op.add_column(
        "subscriptions", sa.Column("amount_replaced_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "subscriptions",
        sa.Column("amount_sync_uncertain_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        f"ALTER TABLE subscriptions ADD CONSTRAINT {PAIRED_CHECK} "
        "CHECK ((previous_amount_minor IS NULL) = (amount_replaced_at IS NULL)) NOT VALID"
    )
    op.execute(f"ALTER TABLE subscriptions VALIDATE CONSTRAINT {PAIRED_CHECK}")
    op.execute("RESET lock_timeout")


def downgrade() -> None:
    """Downgrade schema.

    Refuses while a suspension, a replaced amount or an uncertain PUT is recorded (see the module
    docstring).
    """
    op.execute("SET lock_timeout = '5s'")
    bind = op.get_bind()
    if (
        bind.execute(
            sa.text("SELECT 1 FROM subscriptions WHERE suspended_at IS NOT NULL LIMIT 1")
        ).first()
        is not None
    ):
        raise RuntimeError(
            "Cannot downgrade 0058_suspend_and_prev_amount: subscriptions still has a "
            "suspended_at set. Dropping the column would make a suspended plan end at period "
            "end even if Paymob resumes it. Downgrading past 0058 is not possible while any "
            "suspension is recorded."
        )
    if (
        bind.execute(
            sa.text("SELECT 1 FROM subscriptions WHERE previous_amount_minor IS NOT NULL LIMIT 1")
        ).first()
        is not None
    ):
        raise RuntimeError(
            "Cannot downgrade 0058_suspend_and_prev_amount: subscriptions still has a "
            "previous_amount_minor set. Dropping the columns would turn a renewal Paymob charged "
            "at the replaced amount into a mismatch. Downgrading past 0058 is not possible while "
            "any replaced amount is recorded."
        )
    if (
        bind.execute(
            sa.text(
                "SELECT 1 FROM subscriptions WHERE amount_sync_uncertain_at IS NOT NULL LIMIT 1"
            )
        ).first()
        is not None
    ):
        raise RuntimeError(
            "Cannot downgrade 0058_suspend_and_prev_amount: subscriptions still has an "
            "amount_sync_uncertain_at set. Dropping the column would forget that Paymob's amount "
            "is unconfirmed. Downgrading past 0058 is not possible while any is recorded."
        )
    op.drop_constraint(op.f(PAIRED_CHECK), "subscriptions", type_="check")
    op.drop_column("subscriptions", "amount_sync_uncertain_at")
    op.drop_column("subscriptions", "amount_replaced_at")
    op.drop_column("subscriptions", "previous_amount_minor")
    op.drop_column("subscriptions", "suspended_at")
    op.execute("RESET lock_timeout")
