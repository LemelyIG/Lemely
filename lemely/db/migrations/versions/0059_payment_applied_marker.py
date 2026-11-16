"""The applied marker and the void reason on payments (Paymob billing phase 06, task 9 review I1).

Revision ID: 0059_payment_applied_marker
Revises: 0058_suspend_and_prev_amount
Create Date: 2026-11-16 00:00:00.000000

Additive, on ``payments``, both columns nullable and NULL for every existing row:

* ``applied_at`` (``timestamptz``): set by the paid handler of an upgrade or a seat purchase, in
  the callback transaction that applies it. It is the one marker of "this payment bought what it
  was priced for". Without it, a payment voided with no credit rate (it stays ``paid``, with
  ``grant_units`` NULL) looks exactly like an applied one, and every reader had to guess from the
  subscription as it is now: the return page, the seat-reduction lock and the renewal seat
  shortfall.
* ``void_reason`` (``text``): why the handler voided the payment, CHECK-limited to the known
  reasons (``ck_payments_void_reason_known``). Set whether the payment was then credited or left
  for a manual refund, so the return page can say what happened.

Two more CHECKs keep the markers honest: a payment is never both applied and credited
(``ck_payments_applied_not_credited``: ``applied_at`` and ``grant_units`` are never both set) and
never both applied and voided (``ck_payments_applied_not_voided``).

No backfill: the upgrade and seat payments these columns describe are written by Phase 06 code
that has not shipped, so no production row exists for them. A row written before the column
reads as "not applied", which is the safe side for every reader.

**Lock behaviour**, as 0037/0038/0056/0058: both directions take ACCESS EXCLUSIVE on ``payments``
while the old revision may be serving traffic, so ``SET lock_timeout`` first makes a blocked
statement fail fast and retriably. ``env.py`` runs one ``alembic upgrade``/``downgrade`` in ONE
transaction, so both directions ``RESET lock_timeout`` before returning, or the timeout would
leak into the next migration of the run. The CHECKs are added ``NOT VALID`` and then validated,
so the ACCESS EXCLUSIVE lock is held only for the catalogue change.

``downgrade`` refuses while any payment has ``applied_at`` or ``void_reason`` set: dropping them
would turn an applied purchase into one that looks unapplied (the renewal would then charge for
its seats again) and would forget why a payment was voided. Otherwise it drops what the upgrade
added, in reverse order, and nothing else.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
# Kept to <=32 chars: alembic_version.version_num is varchar(32).
revision: str = "0059_payment_applied_marker"
down_revision: str | Sequence[str] | None = "0058_suspend_and_prev_amount"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Written out, not imported from the model, so the migration is an independent declaration that
#: the parity test compares with the ORM.
VOID_REASONS = (
    "plan_ended",
    "period_rolled",
    "not_an_upgrade_now",
    "seats_not_sold",
    "superseded",
    "seats_changing",
    "seats_over_limit",
    "period_ended",
    "seats_dropped",
)
CHECKS = {
    "ck_payments_applied_not_credited": "applied_at IS NULL OR grant_units IS NULL",
    "ck_payments_applied_not_voided": "applied_at IS NULL OR void_reason IS NULL",
    "ck_payments_void_reason_known": "void_reason IS NULL OR void_reason IN ({})".format(
        ", ".join(f"'{reason}'" for reason in VOID_REASONS)
    ),
}


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("SET lock_timeout = '5s'")
    op.add_column("payments", sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("payments", sa.Column("void_reason", sa.Text(), nullable=True))
    for name, expression in CHECKS.items():
        op.execute(f"ALTER TABLE payments ADD CONSTRAINT {name} CHECK ({expression}) NOT VALID")
        op.execute(f"ALTER TABLE payments VALIDATE CONSTRAINT {name}")
    op.execute("RESET lock_timeout")


def downgrade() -> None:
    """Downgrade schema.

    Refuses while an applied marker or a void reason is recorded (see the module docstring).
    """
    op.execute("SET lock_timeout = '5s'")
    bind = op.get_bind()
    for column, consequence in (
        (
            "applied_at",
            "Dropping the column would turn an applied upgrade or seat purchase into one that "
            "looks unapplied, and the renewal would charge for its seats again.",
        ),
        (
            "void_reason",
            "Dropping the column would forget why a payment was voided to credits.",
        ),
    ):
        if (
            bind.execute(
                sa.text(f"SELECT 1 FROM payments WHERE {column} IS NOT NULL LIMIT 1")  # noqa: S608 - literal
            ).first()
            is not None
        ):
            raise RuntimeError(
                f"Cannot downgrade 0059_payment_applied_marker: payments still has a {column} "
                f"set. {consequence} Downgrading past 0059 is not possible while any is recorded."
            )
    for name in reversed(CHECKS):
        op.drop_constraint(op.f(name), "payments", type_="check")
    op.drop_column("payments", "void_reason")
    op.drop_column("payments", "applied_at")
    op.execute("RESET lock_timeout")
