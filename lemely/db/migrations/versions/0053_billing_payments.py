"""billing payments: payments, paymob events, saved cards, credit packs; catalogue columns

Revision ID: 0053_billing_payments
Revises: 0052_usage_ledger
Create Date: 2026-11-05 00:00:00.000000

Billing spec §4.1-§4.3 (Phase 02 of the Paymob plan). Additive except for two
enum labels.

* ``subscriptionstatus`` gains ``pending_first_payment`` and ``past_due``.
* ``plan_tiers`` gains the catalogue columns (audience, allowance, Paymob plan,
  seats); existing rows become active student tiers with zero allowance.
* ``subscriptions`` gains payer, period, grace, seat and Paymob-link columns and
  ``uq_subscriptions_one_live_per_user``: one live paid subscription per beneficiary.
  Its predicate names the two new labels, so the ``ADD VALUE`` statements run in an
  ``autocommit_block`` (a ``status::text`` predicate is not IMMUTABLE and is
  rejected); it ignores payer-less (manual-activation) rows.
* New ``credit_packs``, ``payments``, ``paymob_events`` and ``saved_cards``.
* ``usage_grants.payment_id`` (a plain column since 0052) gets its foreign key.

``downgrade`` drops all of it. Postgres cannot drop enum labels, so rows in the
two new states move to ``expired`` and ``subscriptionstatus`` is renamed and
recreated with its five original labels.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0053_billing_payments"
down_revision: str | Sequence[str] | None = "0052_usage_ledger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_ENUMS: dict[str, tuple[str, ...]] = {
    "planaudience": ("student", "teacher"),
    "paymentpurpose": (
        "subscription_first",
        "subscription_renewal",
        "upgrade_proration",
        "extra_seats",
        "credit_pack",
        "auto_topup",
    ),
    "paymentstatus": (
        "created",
        "pending",
        "paid",
        "failed",
        "failed_mismatch",
        "refunded",
        "partially_refunded",
        "voided",
    ),
    "paymobeventkind": ("transaction", "token", "subscription"),
}

_LIVE_PAID_PREDICATE = (
    "status IN ('pending_first_payment', 'active', 'past_due') AND payer_user_id IS NOT NULL"
)


def _enum(name: str) -> postgresql.ENUM:
    return postgresql.ENUM(*_NEW_ENUMS[name], name=name, create_type=False)


def _timestamps() -> list[sa.Column]:  # type: ignore[type-arg]
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
    ]


def _restore_subscription_status_labels() -> None:
    """Rebuild ``subscriptionstatus`` without the two labels 0053 added.

    Postgres cannot drop an enum label, so the type is renamed, recreated with the
    five pre-0053 labels, and ``subscriptions.status`` is re-pointed at it. The
    default must be dropped first because it is typed as the old enum. Rows in the
    two removed states were already moved to ``expired`` by the caller.
    """
    op.execute("ALTER TYPE subscriptionstatus RENAME TO subscriptionstatus_old")
    op.execute(
        "CREATE TYPE subscriptionstatus AS ENUM "
        "('inactive', 'active', 'cancelled', 'expired', 'rejected')"
    )
    op.execute("ALTER TABLE subscriptions ALTER COLUMN status DROP DEFAULT")
    op.execute(
        "ALTER TABLE subscriptions ALTER COLUMN status TYPE subscriptionstatus "
        "USING status::text::subscriptionstatus"
    )
    op.execute(
        "ALTER TABLE subscriptions ALTER COLUMN status "
        "SET DEFAULT 'inactive'::subscriptionstatus"
    )
    op.execute("DROP TYPE subscriptionstatus_old")


def upgrade() -> None:
    """Upgrade schema."""
    # The new labels must be committed before the partial index below names them
    # ("unsafe use of new value of enum type"), so this runs outside the open
    # transaction. ``autocommit_block`` commits that transaction first, and with it
    # every earlier revision applied in the same run: a base-to-head upgrade that
    # fails anywhere after this point stops at 0052 (plus the two committed labels),
    # not at base. Re-running is safe because both statements are
    # ``ADD VALUE IF NOT EXISTS``.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE subscriptionstatus ADD VALUE IF NOT EXISTS 'pending_first_payment'")
        op.execute("ALTER TYPE subscriptionstatus ADD VALUE IF NOT EXISTS 'past_due'")
    bind = op.get_bind()
    for name, labels in _NEW_ENUMS.items():
        postgresql.ENUM(*labels, name=name).create(bind, checkfirst=False)

    # -- plan_tiers -----------------------------------------------------------
    op.add_column(
        "plan_tiers",
        sa.Column(
            "audience",
            _enum("planaudience"),
            server_default=sa.text("'student'::planaudience"),
            nullable=False,
        ),
    )
    op.add_column(
        "plan_tiers",
        sa.Column("allowance_units", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column("plan_tiers", sa.Column("paymob_plan_id", sa.BigInteger(), nullable=True))
    op.add_column(
        "plan_tiers",
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.add_column(
        "plan_tiers",
        sa.Column("included_seats", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "plan_tiers",
        sa.Column(
            "seat_allowance_units", sa.BigInteger(), server_default=sa.text("0"), nullable=False
        ),
    )
    op.add_column(
        "plan_tiers",
        sa.Column(
            "extra_seat_price_minor", sa.BigInteger(), server_default=sa.text("0"), nullable=False
        ),
    )
    op.create_unique_constraint(
        op.f("uq_plan_tiers_paymob_plan_id"), "plan_tiers", ["paymob_plan_id"]
    )
    op.create_check_constraint(
        op.f("ck_plan_tiers_allowance_nonneg"), "plan_tiers", "allowance_units >= 0"
    )
    op.create_check_constraint(
        op.f("ck_plan_tiers_seats_nonneg"), "plan_tiers", "included_seats >= 0"
    )
    op.create_check_constraint(
        op.f("ck_plan_tiers_seat_allowance_nonneg"), "plan_tiers", "seat_allowance_units >= 0"
    )
    op.create_check_constraint(
        op.f("ck_plan_tiers_extra_seat_price_nonneg"), "plan_tiers", "extra_seat_price_minor >= 0"
    )

    # -- subscriptions --------------------------------------------------------
    op.add_column("subscriptions", sa.Column("payer_user_id", sa.UUID(), nullable=True))
    op.add_column(
        "subscriptions",
        sa.Column("cancel_at_period_end", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column("subscriptions", sa.Column("pending_plan_tier_id", sa.UUID(), nullable=True))
    op.add_column(
        "subscriptions",
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "subscriptions", sa.Column("grace_until", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "subscriptions",
        sa.Column("extra_seats", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column("subscriptions", sa.Column("pending_extra_seats", sa.Integer(), nullable=True))
    op.add_column(
        "subscriptions", sa.Column("paymob_subscription_id", sa.BigInteger(), nullable=True)
    )
    op.add_column(
        "subscriptions",
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
    )
    op.create_foreign_key(
        op.f("fk_subscriptions_payer_user_id_users"),
        "subscriptions",
        "users",
        ["payer_user_id"],
        ["id"],
    )
    op.create_foreign_key(
        op.f("fk_subscriptions_pending_plan_tier_id_plan_tiers"),
        "subscriptions",
        "plan_tiers",
        ["pending_plan_tier_id"],
        ["id"],
    )
    op.create_unique_constraint(
        op.f("uq_subscriptions_paymob_subscription_id"),
        "subscriptions",
        ["paymob_subscription_id"],
    )
    op.create_check_constraint(
        op.f("ck_subscriptions_extra_seats_nonneg"), "subscriptions", "extra_seats >= 0"
    )
    op.create_check_constraint(
        op.f("ck_subscriptions_pending_extra_seats_nonneg"),
        "subscriptions",
        "pending_extra_seats IS NULL OR pending_extra_seats >= 0",
    )
    op.create_index(
        "uq_subscriptions_one_live_per_user",
        "subscriptions",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text(_LIVE_PAID_PREDICATE),
    )

    # -- credit_packs ---------------------------------------------------------
    op.create_table(
        "credit_packs",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("units", sa.BigInteger(), nullable=False),
        sa.Column("price_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), server_default=sa.text("'EGP'"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("units >= 0", name=op.f("ck_credit_packs_units_nonneg")),
        sa.CheckConstraint("price_minor >= 0", name=op.f("ck_credit_packs_price_nonneg")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_credit_packs")),
        sa.UniqueConstraint("code", name=op.f("uq_credit_packs_code")),
    )

    # -- payments -------------------------------------------------------------
    op.create_table(
        "payments",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("payer_user_id", sa.UUID(), nullable=False),
        sa.Column("beneficiary_user_id", sa.UUID(), nullable=False),
        sa.Column("purpose", _enum("paymentpurpose"), nullable=False),
        sa.Column("plan_tier_id", sa.UUID(), nullable=True),
        sa.Column("credit_pack_id", sa.UUID(), nullable=True),
        sa.Column("subscription_id", sa.UUID(), nullable=True),
        sa.Column("seat_quantity", sa.Integer(), nullable=True),
        sa.Column("grant_units", sa.BigInteger(), nullable=True),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), server_default=sa.text("'EGP'"), nullable=False),
        sa.Column(
            "status",
            _enum("paymentstatus"),
            server_default=sa.text("'created'::paymentstatus"),
            nullable=False,
        ),
        sa.Column("special_reference", sa.String(), nullable=False),
        sa.Column("paymob_intention_id", sa.String(), nullable=True),
        sa.Column("paymob_order_id", sa.BigInteger(), nullable=True),
        sa.Column("paymob_txn_id", sa.BigInteger(), nullable=True),
        sa.Column("method", sa.String(), nullable=True),
        sa.Column("last_callback", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reconcile_attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("next_reconcile_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("amount_minor > 0", name=op.f("ck_payments_amount_positive")),
        sa.CheckConstraint(
            "seat_quantity IS NULL OR seat_quantity > 0",
            name=op.f("ck_payments_seat_quantity_positive"),
        ),
        sa.CheckConstraint(
            "grant_units IS NULL OR grant_units > 0", name=op.f("ck_payments_grant_units_positive")
        ),
        sa.CheckConstraint(
            "purpose <> 'credit_pack' OR credit_pack_id IS NOT NULL",
            name=op.f("ck_payments_credit_pack_link"),
        ),
        sa.ForeignKeyConstraint(
            ["payer_user_id"], ["users.id"], name=op.f("fk_payments_payer_user_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["beneficiary_user_id"],
            ["users.id"],
            name=op.f("fk_payments_beneficiary_user_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["plan_tier_id"], ["plan_tiers.id"], name=op.f("fk_payments_plan_tier_id_plan_tiers")
        ),
        sa.ForeignKeyConstraint(
            ["credit_pack_id"],
            ["credit_packs.id"],
            name=op.f("fk_payments_credit_pack_id_credit_packs"),
        ),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["subscriptions.id"],
            name=op.f("fk_payments_subscription_id_subscriptions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payments")),
        sa.UniqueConstraint("special_reference", name=op.f("uq_payments_special_reference")),
        sa.UniqueConstraint("paymob_order_id", name=op.f("uq_payments_paymob_order_id")),
        sa.UniqueConstraint("paymob_txn_id", name=op.f("uq_payments_paymob_txn_id")),
    )
    op.create_index(
        "ix_payments_status_next_reconcile_at", "payments", ["status", "next_reconcile_at"]
    )
    op.create_index("ix_payments_payer_user_id_paid_at", "payments", ["payer_user_id", "paid_at"])

    # -- paymob_events --------------------------------------------------------
    op.create_table(
        "paymob_events",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("kind", _enum("paymobeventkind"), nullable=False),
        sa.Column("dedupe_key", sa.String(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_paymob_events")),
        sa.UniqueConstraint("dedupe_key", name=op.f("uq_paymob_events_dedupe_key")),
    )

    # -- saved_cards ----------------------------------------------------------
    op.create_table(
        "saved_cards",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("token", sa.Text(), nullable=False),
        sa.Column("token_fingerprint", sa.String(64), nullable=False),
        sa.Column("masked_pan", sa.String(), nullable=False),
        sa.Column("brand", sa.String(), nullable=True),
        sa.Column("paymob_token_id", sa.BigInteger(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_saved_cards_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_saved_cards")),
        sa.UniqueConstraint("user_id", "token_fingerprint", name=op.f("uq_saved_cards_user_id")),
    )

    # -- usage_grants.payment_id FK (column created by 0052) -------------------
    op.create_foreign_key(
        op.f("fk_usage_grants_payment_id_payments"),
        "usage_grants",
        "payments",
        ["payment_id"],
        ["id"],
    )


def downgrade() -> None:
    """Downgrade schema: drop everything above and restore the five original labels."""
    op.drop_constraint(
        op.f("fk_usage_grants_payment_id_payments"), "usage_grants", type_="foreignkey"
    )
    op.drop_table("saved_cards")
    op.drop_table("paymob_events")
    op.drop_table("payments")
    op.drop_table("credit_packs")

    op.execute(
        "UPDATE subscriptions SET status = 'expired' "
        "WHERE status::text IN ('pending_first_payment', 'past_due')"
    )
    op.drop_index("uq_subscriptions_one_live_per_user", table_name="subscriptions")
    _restore_subscription_status_labels()
    op.drop_constraint(
        op.f("ck_subscriptions_pending_extra_seats_nonneg"), "subscriptions", type_="check"
    )
    op.drop_constraint(op.f("ck_subscriptions_extra_seats_nonneg"), "subscriptions", type_="check")
    op.drop_constraint(
        op.f("uq_subscriptions_paymob_subscription_id"), "subscriptions", type_="unique"
    )
    op.drop_constraint(
        op.f("fk_subscriptions_pending_plan_tier_id_plan_tiers"),
        "subscriptions",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_subscriptions_payer_user_id_users"), "subscriptions", type_="foreignkey"
    )
    for column in (
        "version",
        "paymob_subscription_id",
        "pending_extra_seats",
        "extra_seats",
        "grace_until",
        "current_period_start",
        "pending_plan_tier_id",
        "cancel_at_period_end",
        "payer_user_id",
    ):
        op.drop_column("subscriptions", column)

    for check in (
        "ck_plan_tiers_extra_seat_price_nonneg",
        "ck_plan_tiers_seat_allowance_nonneg",
        "ck_plan_tiers_seats_nonneg",
        "ck_plan_tiers_allowance_nonneg",
    ):
        op.drop_constraint(op.f(check), "plan_tiers", type_="check")
    op.drop_constraint(op.f("uq_plan_tiers_paymob_plan_id"), "plan_tiers", type_="unique")
    for column in (
        "extra_seat_price_minor",
        "seat_allowance_units",
        "included_seats",
        "is_active",
        "paymob_plan_id",
        "allowance_units",
        "audience",
    ):
        op.drop_column("plan_tiers", column)

    bind = op.get_bind()
    for name in reversed(list(_NEW_ENUMS)):
        postgresql.ENUM(name=name).drop(bind, checkfirst=False)
