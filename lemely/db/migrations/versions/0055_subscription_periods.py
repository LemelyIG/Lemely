"""subscription periods: one row per paid period, Paymob amount and cancel stamps, billing notices

Revision ID: 0055_subscription_periods
Revises: 0054_teacher_team
Create Date: 2026-11-13 00:00:00.000000

Paymob billing spec §4.3, §5.1-§5.3 (Phase 05). Additive:

* ``subscription_periods``: one row per paid period. Unique ``(subscription_id, period_start)``
  so a period's allowance grant is issued once; ``payment_id`` unique, so one payment pays for at
  most one period. ``CASCADE`` with the subscription; ``RESTRICT`` against the payment.
* ``usage_grants.subscription_period_id`` gains its foreign key (the column exists since 0052),
  ``ON DELETE RESTRICT``: a period that backs a grant is never deleted.
* ``ix_usage_grants_subscription_period`` (partial, ``subscription_period_id IS NOT NULL``): Postgres
  does not index a foreign key's referencing column, and period grants are looked up by period
  (the UD-1 expiry extension, the refund clawback) while a period delete scans for them.
* ``ix_usage_jobs_member_created`` on ``usage_jobs (teacher_member_id, created_at DESC, id DESC)``
  (partial, ``teacher_member_id IS NOT NULL``): the Phase 04 follow-up for a lead's usage history,
  whose funder branch reads the jobs run under their seats and assistants.
* Four partial indexes on ``subscriptions`` for the Phase 05 sweeps (grace expiry, pending Paymob
  cancel, period end and amount candidates, daily drift). Phase 05 adds no other migration, so
  they are created here; ``tests/test_migration_subscription_periods.py`` pins the predicate each
  one serves.
* ``plan_tiers.paymob_plan_mode`` (``test`` or ``live``, nullable text): the Paymob key mode the
  tier's ``paymob_plan_id`` was created under (audit I8: a plan id exists in one mode only).
  Two CHECKs: the value is ``test`` or ``live``, and it is set exactly when the id is. Existing
  linked tiers are backfilled to ``test`` first (before launch only test-mode plans exist; nothing
  on ``main`` or ``develop`` writes ``paymob_plan_id``). ``sync_paymob_plan`` sets it; refusing a
  mismatched tier at checkout is a later task.
* ``subscriptions.paymob_amount_minor`` (the renewal amount Lemely last set at Paymob) and
  ``subscriptions.paymob_cancelled_at`` (when the Paymob subscription was cancelled).
* The one-live-subscription index is ``uq_subscriptions_one_live_per_user`` from 0053; this
  revision does not touch it.
* ``notificationtype`` gains ``billing``; ``notification_preferences`` gains ``billing`` (``NOT NULL
  DEFAULT true``) so ``test_notification_type_enum_matches_preference_columns`` keeps holding.
  The column has no user toggle: payment notices are transactional.

``ALTER TYPE ... ADD VALUE`` runs inside the migration transaction (no ``autocommit_block``, which
would commit every earlier revision of the same run), so nothing in ``upgrade`` may *use* the new
label. Any later revision in the same base-to-head run must likewise compare ``type::text`` and
never name ``'billing'`` as a ``notificationtype`` literal.

``downgrade`` refuses while any ``usage_grants`` row has a ``subscription_period_id``: such a grant
can be neither deleted (ledger entries ``RESTRICT``) nor detached without rewriting ledger history,
so dropping ``subscription_periods`` would orphan it (0054 precedent). It also refuses while any
period exists: a period with no grant (a zero-allowance plan) still records which payment paid for
it, and dropping the table would lose that silently. Otherwise it deletes
``billing`` notifications first (older code cannot load them, precedent 0044), then drops the
preference column, the indexes, the plan mode column with its checks, the two subscription columns, the foreign key and the table. The ``billing``
enum label stays: Postgres has no ``DROP VALUE``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
# Kept to <=32 chars: alembic_version.version_num is varchar(32).
revision: str = "0055_subscription_periods"
down_revision: str | Sequence[str] | None = "0054_teacher_team"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GRANT_FK = "fk_usage_grants_subscription_period_id_subscription_periods"

_LIVE = "('pending_first_payment', 'active', 'past_due')"
#: (name, columns, predicate) of the four ``subscriptions`` sweep indexes; the ORM declares the same.
_SWEEP_INDEXES: tuple[tuple[str, list[str], str], ...] = (
    (
        "ix_subscriptions_grace_expiry",
        ["grace_until", "id"],
        "status = 'past_due' AND paymob_subscription_id IS NOT NULL",
    ),
    (
        "ix_subscriptions_paymob_cancel_pending",
        ["current_period_end", "id"],
        "paymob_subscription_id IS NOT NULL AND paymob_cancelled_at IS NULL",
    ),
    (
        "ix_subscriptions_paymob_live_period_end",
        ["current_period_end", "id"],
        f"paymob_subscription_id IS NOT NULL AND status IN {_LIVE}",
    ),
    (
        "ix_subscriptions_paymob_drift",
        ["updated_at", "id"],
        f"paymob_subscription_id IS NOT NULL AND (paymob_cancelled_at IS NULL OR status IN {_LIVE})",
    ),
)


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "subscription_periods",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("subscription_id", sa.UUID(), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payment_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "period_end > period_start", name=op.f("ck_subscription_periods_period_order")
        ),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["subscriptions.id"],
            name=op.f("fk_subscription_periods_subscription_id_subscriptions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["payment_id"],
            ["payments.id"],
            name=op.f("fk_subscription_periods_payment_id_payments"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_subscription_periods")),
        sa.UniqueConstraint(
            "subscription_id",
            "period_start",
            name=op.f("uq_subscription_periods_subscription_id_period_start"),
        ),
        sa.UniqueConstraint("payment_id", name=op.f("uq_subscription_periods_payment_id")),
    )
    op.create_foreign_key(
        op.f(GRANT_FK),
        "usage_grants",
        "subscription_periods",
        ["subscription_period_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_usage_grants_subscription_period",
        "usage_grants",
        ["subscription_period_id"],
        postgresql_where=sa.text("subscription_period_id IS NOT NULL"),
    )
    op.create_index(
        "ix_usage_jobs_member_created",
        "usage_jobs",
        ["teacher_member_id", sa.text("created_at DESC"), sa.text("id DESC")],
        postgresql_where=sa.text("teacher_member_id IS NOT NULL"),
    )
    op.add_column("plan_tiers", sa.Column("paymob_plan_mode", sa.String(), nullable=True))
    op.execute("UPDATE plan_tiers SET paymob_plan_mode = 'test' WHERE paymob_plan_id IS NOT NULL")
    op.create_check_constraint(
        op.f("ck_plan_tiers_paymob_plan_mode_values"),
        "plan_tiers",
        "paymob_plan_mode IN ('test', 'live')",
    )
    op.create_check_constraint(
        op.f("ck_plan_tiers_paymob_plan_mode_linked"),
        "plan_tiers",
        "(paymob_plan_id IS NULL) = (paymob_plan_mode IS NULL)",
    )
    op.add_column("subscriptions", sa.Column("paymob_amount_minor", sa.BigInteger(), nullable=True))
    op.add_column(
        "subscriptions",
        sa.Column("paymob_cancelled_at", sa.DateTime(timezone=True), nullable=True),
    )
    # After the columns they index. The status labels are 0053's, committed long before.
    for name, columns, predicate in _SWEEP_INDEXES:
        op.create_index(name, "subscriptions", columns, postgresql_where=sa.text(predicate))
    op.execute("ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'billing'")
    op.add_column(
        "notification_preferences",
        sa.Column("billing", sa.Boolean(), server_default=sa.true(), nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema. The ``billing`` notificationtype label stays.

    Refuses while a period grant or any period exists (see the module docstring).
    """
    period_grant = op.get_bind().execute(
        sa.text("SELECT 1 FROM usage_grants WHERE subscription_period_id IS NOT NULL LIMIT 1")
    )
    if period_grant.first() is not None:
        raise RuntimeError(
            "Cannot downgrade 0055_subscription_periods: usage_grants still has period grants "
            "(subscription_period_id IS NOT NULL). A period grant can be neither deleted nor "
            "detached, so dropping subscription_periods would orphan it and the next upgrade "
            "would fail. Downgrading past 0055 is not possible once period grants exist."
        )
    period = op.get_bind().execute(sa.text("SELECT 1 FROM subscription_periods LIMIT 1"))
    if period.first() is not None:
        raise RuntimeError(
            "Cannot downgrade 0055_subscription_periods: subscription_periods still has rows. "
            "A period records which payment paid for it (including a period with no grant), and "
            "dropping the table would lose that history silently. Downgrading past 0055 is not "
            "possible once any period exists."
        )
    # ``type::text``: the label was added by 0055's own upgrade, so inside one base-to-head or
    # head-to-base run it cannot be named as an enum literal before commit (Phase 03 precedent).
    op.execute("DELETE FROM notifications WHERE type::text = 'billing'")
    op.drop_column("notification_preferences", "billing")
    for name, _columns, _predicate in reversed(_SWEEP_INDEXES):
        op.drop_index(name, table_name="subscriptions")
    op.drop_constraint(op.f("ck_plan_tiers_paymob_plan_mode_linked"), "plan_tiers", type_="check")
    op.drop_constraint(op.f("ck_plan_tiers_paymob_plan_mode_values"), "plan_tiers", type_="check")
    op.drop_column("plan_tiers", "paymob_plan_mode")
    op.drop_column("subscriptions", "paymob_cancelled_at")
    op.drop_column("subscriptions", "paymob_amount_minor")
    op.drop_index("ix_usage_jobs_member_created", table_name="usage_jobs")
    op.drop_index("ix_usage_grants_subscription_period", table_name="usage_grants")
    op.drop_constraint(op.f(GRANT_FK), "usage_grants", type_="foreignkey")
    op.drop_table("subscription_periods")
