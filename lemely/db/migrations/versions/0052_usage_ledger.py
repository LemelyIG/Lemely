"""usage ledger: rates, estimators, grants, balances, jobs, entries, debts

Revision ID: 0052_usage_ledger
Revises: 0051_tutor_evidence_uploads
Create Date: 2026-11-05 00:00:00.000000

Paymob billing spec §4.1 (``usage_rates``, ``usage_estimators``) and §4.5 (the
ledger). Entirely additive: four new enum types, seven new tables, one trigger
function. The ORM declaration is ``lemely/db/models/usage.py``.

* ``usage_grants.payment_id``, ``subscription_period_id`` and
  ``teacher_member_id`` are plain UUID columns; ``0053``, ``0055`` and ``0054``
  add their foreign keys when ``payments``, ``subscription_periods`` and
  ``teacher_members`` exist.
* ``usage_entries`` is append-only: ``trg_usage_entries_append_only`` rejects
  ``UPDATE`` and ``DELETE``. The SQL is copied from the model module on purpose,
  so a later edit there cannot rewrite history here.
* ``usage_jobs.payer_chain`` (JSONB) and ``usage_entries.reason`` are not in the
  spec's column list; see the Phase 01 plan's "Contract deviations".

``downgrade`` drops the tables, the trigger function and the four enum types.
**It destroys the usage ledger**: snapshot the seven tables before any
downgrade past this revision.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
# Kept to <=32 chars: alembic_version.version_num is varchar(32).
revision: str = "0052_usage_ledger"
down_revision: str | Sequence[str] | None = "0051_tutor_evidence_uploads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ENUMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "grantkind",
        (
            "period_allowance",
            "seat_allowance",
            "signup",
            "credit_pack",
            "auto_topup",
            "refund",
            "adjustment",
        ),
    ),
    ("usagejobstatus", ("open", "settled", "released", "expired")),
    (
        "usageentrykind",
        (
            "grant",
            "hold",
            "release",
            "settle",
            "expire",
            "refund",
            "adjust",
            "debt",
            "debt_repay",
        ),
    ),
    ("estimatorinputkind", ("pages", "marks", "questions", "none")),
)

_APPEND_ONLY_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION usage_entries_reject_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'usage_entries is append-only: % rejected', TG_OP;
END;
$$
"""

_APPEND_ONLY_TRIGGER_SQL = """
CREATE TRIGGER trg_usage_entries_append_only
BEFORE UPDATE OR DELETE ON usage_entries
FOR EACH ROW EXECUTE FUNCTION usage_entries_reject_mutation()
"""


def _timestamps() -> list[sa.Column]:
    return [
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
    ]


def _id() -> sa.Column:
    return sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False)


def _enum(name: str) -> postgresql.ENUM:
    return postgresql.ENUM(name=name, create_type=False)


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    for name, values in _ENUMS:
        postgresql.ENUM(*values, name=name).create(bind, checkfirst=False)

    op.create_table(
        "usage_rates",
        _id(),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("units_per_usd", sa.BigInteger(), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("units_per_usd > 0", name=op.f("ck_usage_rates_units_per_usd_positive")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_usage_rates")),
        sa.UniqueConstraint("version", "action", name="uq_usage_rates_version_action"),
    )

    op.create_table(
        "usage_estimators",
        _id(),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("input_kind", _enum("estimatorinputkind"), nullable=False),
        sa.Column("base_low", sa.BigInteger(), nullable=False),
        sa.Column("base_high", sa.BigInteger(), nullable=False),
        sa.Column("per_input_low", sa.BigInteger(), nullable=False),
        sa.Column("per_input_high", sa.BigInteger(), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "0 <= base_low AND base_low <= base_high", name=op.f("ck_usage_estimators_base_range")
        ),
        sa.CheckConstraint(
            "0 <= per_input_low AND per_input_low <= per_input_high",
            name=op.f("ck_usage_estimators_per_input_range"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_usage_estimators")),
        sa.UniqueConstraint("version", "action", name="uq_usage_estimators_version_action"),
    )

    op.create_table(
        "usage_grants",
        _id(),
        sa.Column("owner_user_id", sa.UUID(), nullable=False),
        sa.Column("kind", _enum("grantkind"), nullable=False),
        sa.Column("visible", sa.Boolean(), nullable=False),
        sa.Column("teacher_member_id", sa.UUID(), nullable=True),
        sa.Column("priority", sa.SmallInteger(), nullable=False),
        sa.Column("units", sa.BigInteger(), nullable=False),
        sa.Column(
            "effective_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payment_id", sa.UUID(), nullable=True),
        sa.Column("subscription_period_id", sa.UUID(), nullable=True),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("units > 0", name=op.f("ck_usage_grants_units_positive")),
        sa.CheckConstraint(
            "expires_at IS NULL OR expires_at > effective_at",
            name=op.f("ck_usage_grants_expires_after_effective"),
        ),
        sa.CheckConstraint(
            "(kind = 'seat_allowance') = (teacher_member_id IS NOT NULL)",
            name=op.f("ck_usage_grants_seat_link"),
        ),
        sa.CheckConstraint(
            "NOT (visible AND kind IN ('period_allowance', 'seat_allowance'))",
            name=op.f("ck_usage_grants_allowance_hidden"),
        ),
        sa.CheckConstraint(
            "kind NOT IN ('credit_pack', 'auto_topup') OR visible",
            name=op.f("ck_usage_grants_credit_visible"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("fk_usage_grants_owner_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_usage_grants")),
        sa.UniqueConstraint(
            "owner_user_id", "idempotency_key", name="uq_usage_grants_owner_idempotency"
        ),
    )
    op.create_index(
        "ix_usage_grants_owner_spend",
        "usage_grants",
        [
            "owner_user_id",
            "priority",
            sa.text("expires_at ASC NULLS LAST"),
            "effective_at",
            "id",
        ],
    )
    op.create_index(
        "ix_usage_grants_expiring",
        "usage_grants",
        ["expires_at"],
        postgresql_where=sa.text("expires_at IS NOT NULL"),
    )
    op.create_index(
        "ix_usage_grants_seat",
        "usage_grants",
        ["teacher_member_id"],
        postgresql_where=sa.text("teacher_member_id IS NOT NULL"),
    )

    op.create_table(
        "usage_grant_balances",
        sa.Column("grant_id", sa.UUID(), nullable=False),
        sa.Column("remaining", sa.BigInteger(), nullable=False),
        sa.Column("held", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "0 <= held AND held <= remaining",
            name=op.f("ck_usage_grant_balances_held_within_remaining"),
        ),
        sa.ForeignKeyConstraint(
            ["grant_id"],
            ["usage_grants.id"],
            name=op.f("fk_usage_grant_balances_grant_id_usage_grants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("grant_id", name=op.f("pk_usage_grant_balances")),
    )

    op.create_table(
        "usage_jobs",
        _id(),
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("actor_user_id", sa.UUID(), nullable=False),
        sa.Column("teacher_member_id", sa.UUID(), nullable=True),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("estimate_low", sa.BigInteger(), nullable=False),
        sa.Column("estimate_high", sa.BigInteger(), nullable=False),
        sa.Column("estimator_version", sa.Integer(), nullable=False),
        sa.Column("reserved", sa.BigInteger(), nullable=False),
        sa.Column("charged", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("debt_created", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("actual_cost_usd", sa.Numeric(12, 6), nullable=True),
        sa.Column("rate_version", sa.Integer(), nullable=False),
        sa.Column("payer_chain", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "status",
            _enum("usagejobstatus"),
            server_default=sa.text("'open'::usagejobstatus"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "0 <= estimate_low AND estimate_low <= estimate_high",
            name=op.f("ck_usage_jobs_estimate_range"),
        ),
        sa.CheckConstraint("reserved >= 0", name=op.f("ck_usage_jobs_reserved_nonnegative")),
        sa.CheckConstraint("charged >= 0", name=op.f("ck_usage_jobs_charged_nonnegative")),
        sa.CheckConstraint(
            "debt_created >= 0 AND debt_created <= charged",
            name=op.f("ck_usage_jobs_debt_within_charged"),
        ),
        sa.CheckConstraint(
            "(status = 'settled') = (settled_at IS NOT NULL)",
            name=op.f("ck_usage_jobs_settled_at_matches"),
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_usage_jobs_actor_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_usage_jobs")),
        sa.UniqueConstraint("job_id", name=op.f("uq_usage_jobs_job_id")),
    )
    op.create_index("ix_usage_jobs_actor_created", "usage_jobs", ["actor_user_id", "created_at"])
    op.create_index(
        "ix_usage_jobs_open_expires",
        "usage_jobs",
        ["expires_at"],
        postgresql_where=sa.text("status = 'open'"),
    )

    op.create_table(
        "usage_debts",
        _id(),
        sa.Column("owner_user_id", sa.UUID(), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=True),
        sa.Column("units", sa.BigInteger(), nullable=False),
        sa.Column("outstanding", sa.BigInteger(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("units > 0", name=op.f("ck_usage_debts_units_positive")),
        sa.CheckConstraint(
            "0 <= outstanding AND outstanding <= units",
            name=op.f("ck_usage_debts_outstanding_within_units"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("fk_usage_debts_owner_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["usage_jobs.job_id"],
            name=op.f("fk_usage_debts_job_id_usage_jobs"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_usage_debts")),
    )
    op.create_index("ix_usage_debts_job", "usage_debts", ["job_id"])
    op.create_index(
        "ix_usage_debts_owner_outstanding",
        "usage_debts",
        ["owner_user_id", "created_at"],
        postgresql_where=sa.text("outstanding > 0"),
    )

    op.create_table(
        "usage_entries",
        _id(),
        sa.Column("grant_id", sa.UUID(), nullable=True),
        sa.Column("job_id", sa.UUID(), nullable=True),
        sa.Column("debt_id", sa.UUID(), nullable=True),
        sa.Column("teacher_member_id", sa.UUID(), nullable=True),
        sa.Column("kind", _enum("usageentrykind"), nullable=False),
        sa.Column("units", sa.BigInteger(), nullable=False),
        sa.Column("rate_version", sa.Integer(), nullable=True),
        sa.Column("event_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("units <> 0", name=op.f("ck_usage_entries_units_nonzero")),
        sa.CheckConstraint(
            "grant_id IS NOT NULL OR debt_id IS NOT NULL", name=op.f("ck_usage_entries_has_target")
        ),
        sa.CheckConstraint(
            "kind NOT IN ('debt', 'debt_repay') OR debt_id IS NOT NULL",
            name=op.f("ck_usage_entries_debt_kinds_link"),
        ),
        sa.ForeignKeyConstraint(
            ["grant_id"],
            ["usage_grants.id"],
            name=op.f("fk_usage_entries_grant_id_usage_grants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["usage_jobs.job_id"],
            name=op.f("fk_usage_entries_job_id_usage_jobs"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["debt_id"],
            ["usage_debts.id"],
            name=op.f("fk_usage_entries_debt_id_usage_debts"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_usage_entries")),
        sa.UniqueConstraint(
            "grant_id", "idempotency_key", "kind", name="uq_usage_entries_grant_key_kind"
        ),
    )
    op.create_index(
        "uq_usage_entries_debt_key_kind",
        "usage_entries",
        ["debt_id", "idempotency_key", "kind"],
        unique=True,
        postgresql_where=sa.text("grant_id IS NULL"),
    )
    op.create_index("ix_usage_entries_grant", "usage_entries", ["grant_id"])
    op.create_index("ix_usage_entries_job", "usage_entries", ["job_id"])
    op.create_index("ix_usage_entries_debt", "usage_entries", ["debt_id"])
    op.create_index(
        "ix_usage_entries_cap",
        "usage_entries",
        ["teacher_member_id", "event_at"],
        postgresql_where=sa.text("teacher_member_id IS NOT NULL"),
    )
    op.execute(_APPEND_ONLY_FUNCTION_SQL)
    op.execute(_APPEND_ONLY_TRIGGER_SQL)


def downgrade() -> None:
    """Downgrade schema: drop the ledger, its trigger function and its enum types."""
    op.drop_table("usage_entries")  # drops trg_usage_entries_append_only with it
    op.execute("DROP FUNCTION usage_entries_reject_mutation()")
    op.drop_table("usage_debts")
    op.drop_table("usage_jobs")
    op.drop_table("usage_grant_balances")
    op.drop_table("usage_grants")
    op.drop_table("usage_estimators")
    op.drop_table("usage_rates")
    bind = op.get_bind()
    for name, _values in reversed(_ENUMS):
        postgresql.ENUM(name=name).drop(bind, checkfirst=False)
