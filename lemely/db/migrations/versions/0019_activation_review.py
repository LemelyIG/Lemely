"""subscriptions.activation_note + a `rejected` subscription status (P4.7, X-02)

Revision ID: 0019_activation_review
Revises: 0018_push_subscriptions
Create Date: 2026-08-14 08:00:00.000000

Two additive changes, both required by UI spec X-02 ("activate / reject **with a
note**") and neither expressible against the existing schema. Nothing is
altered, dropped, or backfilled (D1.2/D1.3).

**Why a `rejected` status rather than reusing `cancelled`.** X-02 is the queue a
platform admin works through by hand, because payments are deferred and
activation is a manual toggle (see :class:`SubscriptionStatus`'s own docstring).
The queue is "subscriptions still `inactive`", so a decision has to move the row
*out* of `inactive` or it comes back tomorrow. `cancelled` was the only existing
exit, and it is the wrong word: it already means "the subscriber ended this",
which is a different event with a different party responsible. Reusing it would
make "we declined this request" and "they quit" indistinguishable in the one
table an audit would read. The value is added rather than the enum rewritten, so
every existing row keeps its meaning.

`ALTER TYPE ... ADD VALUE` is transaction-safe from PostgreSQL 12 onward
provided the new value is not *used* in the same transaction, which it is not —
this migration only declares it, and the first row to carry it is written at
runtime. `IF NOT EXISTS` keeps the migration re-runnable against a database
where it was applied by hand.

**Why the note is nullable.** Most decisions will carry one and the UI asks for
one, but a note is a human sentence and there is no honest default to write when
none was given. `NOT NULL DEFAULT ''` would put an empty string on every row
ever activated before this migration and make "no note was recorded" and "the
note was blank" the same value.

**Why there is no `reviewed_by` / `reviewed_at` pair.** `activated_at` already
records when an activation happened, and adding a reviewer column would need a
foreign key to `users` that this migration cannot backfill for the rows already
activated. The note is the whole of what X-02 asks for; a full audit trail is a
larger design than one screen justifies, and inventing half of it here would
leave a column that is null for exactly the rows anyone would want it for.

**Downgrade is asymmetric on purpose.** The column drops cleanly. The enum value
does not: PostgreSQL has no `ALTER TYPE ... DROP VALUE`, and rebuilding the type
would have to decide what to do with any row already holding `rejected` —
silently rewriting a recorded decision to `cancelled` is exactly the conflation
this migration exists to prevent. The value is therefore left in place on
downgrade and the reason is stated there too, rather than the downgrade
pretending to be complete.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# Alembic's ``alembic_version.version_num`` is ``varchar(32)``, so this id is
# abbreviated from the file's subject rather than spelling it out.
revision = "0019_activation_review"
down_revision = "0018_push_subscriptions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the `rejected` status value and the nullable activation note."""
    op.execute("ALTER TYPE subscriptionstatus ADD VALUE IF NOT EXISTS 'rejected'")
    op.add_column(
        "subscriptions",
        sa.Column("activation_note", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    """Drop the note column. The enum value stays — see the module docstring."""
    op.drop_column("subscriptions", "activation_note")
