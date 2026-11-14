r"""Admin audit log and the tables the admin billing surface owns (Paymob billing phase 07).

Revision ID: 0057_admin_audit_log
Revises: 0056_auto_topup
Create Date: 2026-11-13 00:00:00.000000

Paymob billing spec §4.7, §6, §8 (Phase 07). Additive only, and the only migration of the
phase. Every table and column the phase's tasks need is here:

* ``admin_audit_log`` plus ``admin_audit_log_append_only()`` and its BEFORE UPDATE OR DELETE
  trigger. ``admin_user_id`` is RESTRICT (SET NULL would be an UPDATE the trigger refuses, and
  CASCADE would erase history); ``target_id`` has no foreign key. ``reason_required`` is
  ``reason ~ '\S'``: ``btrim`` strips spaces only, so a tab or newline reason would pass it.
  ``ix_admin_audit_log_idempotency`` is a partial expression index for the idempotency lookup
  (``(action, (after ->> 'idempotency_key')) WHERE after ? 'idempotency_key'``).
* ``job_runs``: one row per sweeper job name (``last_finished_at`` and ``last_outcome`` are NULL
  until the first finish; ``last_error`` is capped at 200 characters).
* ``paymob_webhook_failures``: kind, fixed reason, best-effort remote address, arrival time.
  No body column. The sweeper prunes rows older than 90 days by ``received_at``.
* ``payment_refunds`` (+ enums ``refundkind``, ``refundstatus``): refund and void attempts,
  written before Paymob is called. ``reverse_change`` records the admin's per-refund choice of
  "money only" (the default) or "money and reverse the change" for a Phase 06 charge.
* ``usage_job_model_costs``: LLM cost per (job, model), cascading with the job.
* ``credit_conversion_rates``: the fixed admin-set conversion rate (UD-12), one row per currency:
  ``units_per_minor`` usage units per minor currency unit, CHECK ``> 0``. No row means no
  automatic conversion for that currency.
* ``signup_allowance_off_periods``: when a signup allowance pack was off (``units = 0``). One
  open window per pack (partial unique index on ``off_until IS NULL``). The upgrade opens a
  window, from the upgrade's time, for each ``signup_*`` pack that is already at 0, so an admin
  raising it later has an open window to close and accounts created from now on are skipped by
  the repair job. Windows before the upgrade are unknown and are not invented.
* ``billing_settings`` (UD-13): the single row (``id = 1``, inserted here) of admin-set scalars,
  each with a range CHECK: credit validity months, grace days, extra-seat cap, price-change
  notice days (default 14, 7 to 90), margin EGP per USD, code-execution USD per hour.
* ``llm_price_overrides`` (UD13-D): an admin price per million tokens for one model.
* ``plan_tier_terms`` (UD13-A): the append-only history of a tier's price and entitlements,
  backfilled with version 1 of every valid tier (no negative amount), plus
  ``trg_plan_tiers_seed_terms`` so every later valid tier gets its version 1 the moment it is
  inserted, or later by an UPDATE if it had none (a tier with a negative amount is invalid,
  ``plan_tiers`` has no CHECK for it, and gets no terms row, so the insert of the tier itself
  never fails and nothing can subscribe to it). ``created_by`` is NULL on rows the trigger
  writes (the audit log records who created the tier) and ``RESTRICT`` on the user.
  ``subscriptions`` gains ``terms_version``,
  ``pending_terms_version``, ``pending_terms_effective_at`` and ``terms_notice_sent_at`` with
  composite foreign keys into the history and ``ix_subscriptions_terms_move``;
  ``subscription_periods.terms_version`` records the version a period was billed on. The
  history is created and backfilled before those foreign keys. The shared append-only function
  now names the table it protects.
* ``plan_tiers.version`` / ``terms_version`` / ``paymob_plan_synced_price_minor`` /
  ``paymob_plan_synced_frequency`` / ``paymob_plan_synced_retrial_days``,
  ``credit_packs.version`` / ``signup_validity_days`` (``signup_teacher`` backfilled to 30; only
  a ``signup_*`` pack may set it), ``credit_conversion_rates.version`` and
  ``payments.callback_received_at``.
* Indexes for the admin margin, payments and health queries on ``usage_jobs`` (two),
  ``payments`` (two), ``usage_entries`` and ``paymob_events``. ``ix_admin_usage_jobs_created_at``
  is partial on ``actual_cost_usd IS NOT NULL``: the margin query states that predicate, and a
  plain ``created_at`` index would win the lead's usage-history plan away from
  ``ix_usage_jobs_member_created``.

**Lock behaviour**, as 0037, 0038 and 0056. Both directions lock, in this order: ``plan_tiers``
and ``credit_packs`` (new columns), the new tables' foreign keys on ``users``, ``payments`` and
``usage_jobs``, ``payments`` (new column), ``usage_jobs``, ``usage_entries`` and
``paymob_events`` (index builds), then ``subscriptions`` and ``subscription_periods`` (new
columns, foreign keys), while the old revision may be serving traffic. That is NOT the
callback's order (``payments`` first), so a callback that holds a ``payments`` row lock and
reads ``plan_tiers`` can deadlock with the migration. Postgres then aborts one side after
``deadlock_timeout``, and ``SET lock_timeout`` makes a blocked statement fail fast; either way
the whole migration rolls back and is retried. Nothing is corrupted. Run it in a quiet window.
``env.py`` runs one ``alembic upgrade``/``downgrade`` in ONE transaction, so both directions
``RESET lock_timeout`` before returning, or the timeout would leak into the next migration of
the run.

The index builds are plain ``CREATE INDEX`` (``CONCURRENTLY`` cannot run in a transaction), so
each blocks writes to its table while it runs, and ``lock_timeout`` bounds only the wait for the
lock, not the build. That is acceptable at the current table sizes (``usage_entries`` and
``paymob_events`` are small before launch); check their row counts before a production cutover
that happens later.

``downgrade`` refuses while money or policy history exists, as 0054, 0055 and 0056 do: any
``admin_audit_log`` row (the record of who changed money and why), any ``payment_refunds`` row
(a refund request, possibly sent to Paymob with no recorded outcome), any
``credit_conversion_rates`` row (the rate an admin set; dropping it stops conversions), an edited
``billing_settings`` row (``version > 1``), any ``llm_price_overrides`` row, a ``plan_tier_terms``
row above version 1, a subscription with pending terms, a tier or pack with ``version > 1`` or
a signup pack whose validity differs from the seeded one, or any ``signup_allowance_off_periods``
row (dropping it would let the repair job grant the allowance retroactively). Otherwise it drops
exactly what the upgrade added, in reverse order, the trigger functions included. ``job_runs``,
``paymob_webhook_failures`` and ``usage_job_model_costs`` are operational records that the next
runs and settles rebuild; the downgrade drops them.

The upgrade itself inserts ``signup_allowance_off_periods`` rows (one per ``signup_*`` pack
already at ``units = 0``), so on such a database the downgrade refuses with no admin action at
all. That is intended: the row is what UD-5 needs, and dropping it would let the repair job
grant the allowance retroactively. ``TRUNCATE`` is not blocked by the append-only triggers (test
cleanup relies on it), so the guards protect against an accident, not against an operator
who empties the tables first.
"""

import uuid
from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
# Kept to <=32 chars: alembic_version.version_num is varchar(32).
revision: str = "0057_admin_audit_log"
down_revision: str | Sequence[str] | None = "0056_auto_topup"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The ORM declares the same SQL (``lemely.db.models.admin_audit``); the parity test compares
#: the catalogue definitions of the function and the trigger.
_APPEND_ONLY_FUNCTION = """
CREATE OR REPLACE FUNCTION admin_audit_log_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation';
END;
$$
"""

_APPEND_ONLY_TRIGGER = """
CREATE TRIGGER trg_admin_audit_log_append_only
BEFORE UPDATE OR DELETE ON admin_audit_log
FOR EACH ROW EXECUTE FUNCTION admin_audit_log_append_only()
"""

_TERMS_APPEND_ONLY_TRIGGER = """
CREATE TRIGGER trg_plan_tier_terms_append_only
BEFORE UPDATE OR DELETE ON plan_tier_terms
FOR EACH ROW EXECUTE FUNCTION admin_audit_log_append_only()
"""

_SEED_TERMS_FUNCTION = """
CREATE OR REPLACE FUNCTION plan_tiers_seed_terms() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    -- A tier with a negative amount is invalid (``plan_tiers`` has no CHECK for it; the admin
    -- API validates) and the history refuses negatives: such a tier gets no terms row, so
    -- nothing can subscribe to it, instead of the insert of the tier itself failing. When a
    -- tier that has no terms at all becomes valid by an UPDATE, its current version is written
    -- then. A tier that already has terms is never touched here (the admin API inserts the
    -- next version itself, before it moves ``terms_version``).
    IF (TG_OP = 'INSERT'
        OR NOT EXISTS (SELECT 1 FROM plan_tier_terms WHERE plan_tier_id = NEW.id))
       AND NEW.price_minor >= 0 AND NEW.extra_seat_price_minor >= 0
       AND NEW.allowance_units >= 0 AND NEW.included_seats >= 0
       AND NEW.seat_allowance_units >= 0 THEN
        INSERT INTO plan_tier_terms (
            plan_tier_id, terms_version, price_minor, extra_seat_price_minor,
            allowance_units, included_seats, seat_allowance_units
        ) VALUES (
            NEW.id, NEW.terms_version, NEW.price_minor, NEW.extra_seat_price_minor,
            NEW.allowance_units, NEW.included_seats, NEW.seat_allowance_units
        );
    END IF;
    RETURN NEW;
END;
$$
"""

_SEED_TERMS_TRIGGER = """
CREATE TRIGGER trg_plan_tiers_seed_terms
AFTER INSERT OR UPDATE OF price_minor, extra_seat_price_minor, allowance_units,
    included_seats, seat_allowance_units ON plan_tiers
FOR EACH ROW EXECUTE FUNCTION plan_tiers_seed_terms()
"""

IDEMPOTENCY_INDEX = "ix_admin_audit_log_idempotency"
IDEMPOTENCY_KEY_EXPRESSION = "(after ->> 'idempotency_key')"
HAS_IDEMPOTENCY_KEY = "after ? 'idempotency_key'"

#: ``(index name, table, columns, partial predicate)`` of the indexes this revision adds to
#: other phases' tables.
_FOREIGN_INDEXES: tuple[tuple[str, str, list[str], str | None], ...] = (
    (
        "ix_admin_usage_jobs_created_at",
        "usage_jobs",
        ["created_at"],
        "actual_cost_usd IS NOT NULL",
    ),
    ("ix_admin_usage_jobs_action_estimator", "usage_jobs", ["action", "estimator_version"], None),
    ("ix_admin_payments_paid_at", "payments", ["paid_at"], None),
    ("ix_admin_payments_status_created_at", "payments", ["status", "created_at"], None),
    ("ix_admin_usage_entries_kind_event_at", "usage_entries", ["kind", "event_at"], None),
    ("ix_admin_paymob_events_created_at", "paymob_events", ["created_at"], None),
)


def _uuid_pk() -> sa.Column[uuid.UUID]:
    return sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False)


def _now(name: str) -> sa.Column[datetime]:
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("SET lock_timeout = '5s'")

    op.create_table(
        "admin_audit_log",
        _uuid_pk(),
        sa.Column("admin_user_id", sa.UUID(), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_kind", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.UUID(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("before", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        _now("created_at"),
        sa.CheckConstraint(r"reason ~ '\S'", name=op.f("ck_admin_audit_log_reason_required")),
        sa.ForeignKeyConstraint(
            ["admin_user_id"],
            ["users.id"],
            name=op.f("fk_admin_audit_log_admin_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admin_audit_log")),
    )
    op.create_index(
        "ix_admin_audit_log_target", "admin_audit_log", ["target_kind", "target_id", "created_at"]
    )
    op.create_index("ix_admin_audit_log_created_at", "admin_audit_log", ["created_at"])
    op.create_index(
        IDEMPOTENCY_INDEX,
        "admin_audit_log",
        ["action", sa.text(IDEMPOTENCY_KEY_EXPRESSION)],
        unique=True,
        postgresql_where=sa.text(HAS_IDEMPOTENCY_KEY),
    )
    op.execute(_APPEND_ONLY_FUNCTION)
    op.execute(_APPEND_ONLY_TRIGGER)

    op.create_table(
        "job_runs",
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("last_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_outcome", sa.String(length=16), nullable=True),
        sa.Column("last_result_count", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.String(length=200), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "consecutive_failures", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("total_runs", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("total_failures", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.CheckConstraint(
            "last_outcome IN ('ok', 'failed')", name=op.f("ck_job_runs_outcome_known")
        ),
        sa.CheckConstraint(
            "consecutive_failures >= 0", name=op.f("ck_job_runs_failures_non_negative")
        ),
        sa.CheckConstraint(
            "total_runs >= 0 AND total_failures >= 0", name=op.f("ck_job_runs_totals_non_negative")
        ),
        sa.PrimaryKeyConstraint("name", name=op.f("pk_job_runs")),
    )

    op.create_table(
        "paymob_webhook_failures",
        _uuid_pk(),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=False),
        sa.Column("remote_addr", sa.String(length=64), nullable=True),
        _now("received_at"),
        sa.CheckConstraint(
            "kind IN ('transaction', 'token', 'subscription')",
            name=op.f("ck_paymob_webhook_failures_kind_known"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_paymob_webhook_failures")),
    )
    op.create_index(
        "ix_paymob_webhook_failures_received_at", "paymob_webhook_failures", ["received_at"]
    )

    op.create_table(
        "payment_refunds",
        _uuid_pk(),
        sa.Column("payment_id", sa.UUID(), nullable=False),
        sa.Column("admin_user_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.Enum("refund", "void", name="refundkind"), nullable=False),
        sa.Column(
            "status",
            sa.Enum("requested", "succeeded", "failed", "unknown", name="refundstatus"),
            server_default=sa.text("'requested'::refundstatus"),
            nullable=False,
        ),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("paymob_response", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "clawed_back_units", sa.BigInteger(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("reverse_change", sa.Boolean(), server_default=sa.false(), nullable=False),
        _now("created_at"),
        _now("updated_at"),
        sa.CheckConstraint("amount_minor > 0", name=op.f("ck_payment_refunds_amount_positive")),
        sa.CheckConstraint(
            "clawed_back_units >= 0", name=op.f("ck_payment_refunds_clawback_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["payment_id"],
            ["payments.id"],
            name=op.f("fk_payment_refunds_payment_id_payments"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["admin_user_id"],
            ["users.id"],
            name=op.f("fk_payment_refunds_admin_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payment_refunds")),
    )
    op.create_index("ix_payment_refunds_payment_id", "payment_refunds", ["payment_id"])
    op.create_index(
        "ix_payment_refunds_status_created_at", "payment_refunds", ["status", "created_at"]
    )

    op.create_table(
        "usage_job_model_costs",
        _uuid_pk(),
        sa.Column("usage_job_id", sa.UUID(), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("cost_usd", sa.Numeric(precision=12, scale=6), nullable=False),
        _now("created_at"),
        sa.CheckConstraint(
            "cost_usd >= 0", name=op.f("ck_usage_job_model_costs_cost_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["usage_job_id"],
            ["usage_jobs.id"],
            name=op.f("fk_usage_job_model_costs_usage_job_id_usage_jobs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_usage_job_model_costs")),
        sa.UniqueConstraint(
            "usage_job_id", "model", name=op.f("uq_usage_job_model_costs_usage_job_id")
        ),
    )
    op.create_index("ix_usage_job_model_costs_model", "usage_job_model_costs", ["model"])

    op.create_table(
        "credit_conversion_rates",
        _uuid_pk(),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("units_per_minor", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        _now("created_at"),
        _now("updated_at"),
        sa.CheckConstraint(
            "units_per_minor > 0", name=op.f("ck_credit_conversion_rates_rate_positive")
        ),
        sa.CheckConstraint(
            r"currency ~ '^[A-Z]{3}$'", name=op.f("ck_credit_conversion_rates_currency_code")
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_credit_conversion_rates_version_min")),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name=op.f("fk_credit_conversion_rates_updated_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_credit_conversion_rates")),
        sa.UniqueConstraint("currency", name=op.f("uq_credit_conversion_rates_currency")),
    )

    op.create_table(
        "signup_allowance_off_periods",
        _uuid_pk(),
        sa.Column("credit_pack_id", sa.UUID(), nullable=False),
        sa.Column("off_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("off_until", sa.DateTime(timezone=True), nullable=True),
        _now("created_at"),
        sa.CheckConstraint(
            "off_until IS NULL OR off_until >= off_from",
            name=op.f("ck_signup_allowance_off_periods_window_ordered"),
        ),
        sa.ForeignKeyConstraint(
            ["credit_pack_id"],
            ["credit_packs.id"],
            name=op.f("fk_signup_allowance_off_periods_credit_pack_id_credit_packs"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_signup_allowance_off_periods")),
    )
    op.create_index(
        "uq_signup_allowance_off_periods_open",
        "signup_allowance_off_periods",
        ["credit_pack_id"],
        unique=True,
        postgresql_where=sa.text("off_until IS NULL"),
    )
    op.create_index(
        "ix_signup_allowance_off_periods_pack_from",
        "signup_allowance_off_periods",
        ["credit_pack_id", "off_from"],
    )
    op.execute(
        "INSERT INTO signup_allowance_off_periods (credit_pack_id, off_from) "
        "SELECT id, now() FROM credit_packs WHERE starts_with(code, 'signup_') AND units = 0"
    )

    op.add_column(
        "plan_tiers", sa.Column("paymob_plan_synced_price_minor", sa.BigInteger(), nullable=True)
    )
    op.add_column(
        "plan_tiers", sa.Column("paymob_plan_synced_frequency", sa.Integer(), nullable=True)
    )
    op.add_column(
        "plan_tiers", sa.Column("paymob_plan_synced_retrial_days", sa.Integer(), nullable=True)
    )
    op.add_column(
        "plan_tiers",
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
    )
    op.add_column(
        "plan_tiers",
        sa.Column("terms_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
    )
    op.create_check_constraint(op.f("ck_plan_tiers_version_min"), "plan_tiers", "version >= 1")
    op.create_check_constraint(
        op.f("ck_plan_tiers_terms_version_min"), "plan_tiers", "terms_version >= 1"
    )
    op.add_column(
        "credit_packs",
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
    )
    op.add_column("credit_packs", sa.Column("signup_validity_days", sa.Integer(), nullable=True))
    # Teacher signup credits last 30 days today (``TEACHER_SIGNUP_VALIDITY``); the student
    # allowance never expires (NULL). The CHECK goes on after the backfill.
    op.execute("UPDATE credit_packs SET signup_validity_days = 30 WHERE code = 'signup_teacher'")
    op.create_check_constraint(op.f("ck_credit_packs_version_min"), "credit_packs", "version >= 1")
    op.create_check_constraint(
        op.f("ck_credit_packs_signup_validity"),
        "credit_packs",
        "signup_validity_days IS NULL "
        "OR (starts_with(code, 'signup_') AND signup_validity_days BETWEEN 1 AND 3650)",
    )
    op.add_column(
        "payments", sa.Column("callback_received_at", sa.DateTime(timezone=True), nullable=True)
    )

    for name, table, columns, predicate in _FOREIGN_INDEXES:
        op.create_index(
            name,
            table,
            columns,
            postgresql_where=None if predicate is None else sa.text(predicate),
        )

    # Plan terms history. The table is created and backfilled (version 1 of every tier, from the
    # tier's own columns) BEFORE the subscription columns and foreign keys that point at it:
    # adding a composite foreign key first would fail on the existing subscriptions.
    op.create_table(
        "plan_tier_terms",
        _uuid_pk(),
        sa.Column("plan_tier_id", sa.UUID(), nullable=False),
        sa.Column("terms_version", sa.Integer(), nullable=False),
        sa.Column("price_minor", sa.BigInteger(), nullable=False),
        sa.Column("extra_seat_price_minor", sa.BigInteger(), nullable=False),
        sa.Column("allowance_units", sa.BigInteger(), nullable=False),
        sa.Column("included_seats", sa.Integer(), nullable=False),
        sa.Column("seat_allowance_units", sa.BigInteger(), nullable=False),
        _now("created_at"),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.CheckConstraint("terms_version >= 1", name=op.f("ck_plan_tier_terms_terms_version_min")),
        sa.CheckConstraint(
            "price_minor >= 0 AND extra_seat_price_minor >= 0 AND allowance_units >= 0 "
            "AND included_seats >= 0 AND seat_allowance_units >= 0",
            name=op.f("ck_plan_tier_terms_amounts_nonneg"),
        ),
        sa.ForeignKeyConstraint(
            ["plan_tier_id"],
            ["plan_tiers.id"],
            name=op.f("fk_plan_tier_terms_plan_tier_id_plan_tiers"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_plan_tier_terms_created_by_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plan_tier_terms")),
        sa.UniqueConstraint(
            "plan_tier_id", "terms_version", name=op.f("uq_plan_tier_terms_plan_tier_id")
        ),
    )
    op.execute(
        "INSERT INTO plan_tier_terms (plan_tier_id, terms_version, price_minor, "
        "extra_seat_price_minor, allowance_units, included_seats, seat_allowance_units) "
        "SELECT id, 1, price_minor, extra_seat_price_minor, allowance_units, included_seats, "
        "seat_allowance_units FROM plan_tiers WHERE price_minor >= 0 "
        "AND extra_seat_price_minor >= 0 AND allowance_units >= 0 AND included_seats >= 0 "
        "AND seat_allowance_units >= 0"
    )
    op.execute(_TERMS_APPEND_ONLY_TRIGGER)
    op.execute(_SEED_TERMS_FUNCTION)
    op.execute(_SEED_TERMS_TRIGGER)

    op.add_column(
        "subscriptions",
        sa.Column("terms_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
    )
    op.add_column("subscriptions", sa.Column("pending_terms_version", sa.Integer(), nullable=True))
    op.add_column(
        "subscriptions",
        sa.Column("pending_terms_effective_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "subscriptions",
        sa.Column("terms_notice_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_subscriptions_terms_version_min"), "subscriptions", "terms_version >= 1"
    )
    op.create_check_constraint(
        op.f("ck_subscriptions_pending_terms_paired"),
        "subscriptions",
        "(pending_terms_version IS NULL) = (pending_terms_effective_at IS NULL)",
    )
    op.create_foreign_key(
        op.f("fk_subscriptions_terms"),
        "subscriptions",
        "plan_tier_terms",
        ["plan_tier_id", "terms_version"],
        ["plan_tier_id", "terms_version"],
    )
    op.create_foreign_key(
        op.f("fk_subscriptions_pending_terms"),
        "subscriptions",
        "plan_tier_terms",
        ["plan_tier_id", "pending_terms_version"],
        ["plan_tier_id", "terms_version"],
    )
    op.create_index(
        "ix_subscriptions_terms_move",
        "subscriptions",
        ["plan_tier_id", "terms_version"],
        postgresql_where=sa.text("status IN ('active', 'past_due')"),
    )
    op.add_column("subscription_periods", sa.Column("terms_version", sa.Integer(), nullable=True))

    op.create_table(
        "billing_settings",
        sa.Column("id", sa.SmallInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "credit_validity_months", sa.Integer(), server_default=sa.text("12"), nullable=False
        ),
        sa.Column("grace_days", sa.Integer(), server_default=sa.text("3"), nullable=False),
        sa.Column("max_extra_seats", sa.Integer(), server_default=sa.text("200"), nullable=False),
        sa.Column(
            "price_change_notice_days", sa.Integer(), server_default=sa.text("14"), nullable=False
        ),
        sa.Column("margin_egp_per_usd", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("code_execution_usd_per_hour", sa.Numeric(precision=10, scale=6), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        _now("created_at"),
        _now("updated_at"),
        sa.CheckConstraint("id = 1", name=op.f("ck_billing_settings_singleton")),
        sa.CheckConstraint(
            "credit_validity_months BETWEEN 1 AND 120",
            name=op.f("ck_billing_settings_credit_validity_range"),
        ),
        sa.CheckConstraint(
            "grace_days BETWEEN 1 AND 7", name=op.f("ck_billing_settings_grace_days_range")
        ),
        sa.CheckConstraint(
            "max_extra_seats BETWEEN 1 AND 10000",
            name=op.f("ck_billing_settings_max_extra_seats_range"),
        ),
        sa.CheckConstraint(
            "price_change_notice_days BETWEEN 7 AND 90",
            name=op.f("ck_billing_settings_price_change_notice_range"),
        ),
        sa.CheckConstraint(
            "margin_egp_per_usd IS NULL "
            "OR (margin_egp_per_usd > 0 AND margin_egp_per_usd <= 10000)",
            name=op.f("ck_billing_settings_margin_rate_range"),
        ),
        sa.CheckConstraint(
            "code_execution_usd_per_hour IS NULL OR code_execution_usd_per_hour >= 0",
            name=op.f("ck_billing_settings_code_execution_nonneg"),
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_billing_settings_version_min")),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name=op.f("fk_billing_settings_updated_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_billing_settings")),
    )
    op.execute("INSERT INTO billing_settings (id) VALUES (1)")

    op.create_table(
        "llm_price_overrides",
        _uuid_pk(),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("input_usd_per_mtok", sa.Numeric(precision=14, scale=6), nullable=False),
        sa.Column("output_usd_per_mtok", sa.Numeric(precision=14, scale=6), nullable=False),
        sa.Column("cached_input_usd_per_mtok", sa.Numeric(precision=14, scale=6), nullable=True),
        sa.Column("cache_write_5m_usd_per_mtok", sa.Numeric(precision=14, scale=6), nullable=True),
        sa.Column("cache_write_1h_usd_per_mtok", sa.Numeric(precision=14, scale=6), nullable=True),
        sa.Column("tier_threshold_tokens", sa.Integer(), nullable=True),
        sa.Column("tier2_input_usd_per_mtok", sa.Numeric(precision=14, scale=6), nullable=True),
        sa.Column("tier2_output_usd_per_mtok", sa.Numeric(precision=14, scale=6), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        _now("created_at"),
        _now("updated_at"),
        sa.CheckConstraint(
            "input_usd_per_mtok >= 0 AND output_usd_per_mtok >= 0 "
            "AND (cached_input_usd_per_mtok IS NULL OR cached_input_usd_per_mtok >= 0) "
            "AND (cache_write_5m_usd_per_mtok IS NULL OR cache_write_5m_usd_per_mtok >= 0) "
            "AND (cache_write_1h_usd_per_mtok IS NULL OR cache_write_1h_usd_per_mtok >= 0) "
            "AND (tier2_input_usd_per_mtok IS NULL OR tier2_input_usd_per_mtok >= 0) "
            "AND (tier2_output_usd_per_mtok IS NULL OR tier2_output_usd_per_mtok >= 0)",
            name=op.f("ck_llm_price_overrides_rates_nonneg"),
        ),
        sa.CheckConstraint(
            "(tier_threshold_tokens IS NULL AND tier2_input_usd_per_mtok IS NULL "
            "AND tier2_output_usd_per_mtok IS NULL) "
            "OR (tier_threshold_tokens > 0 AND tier2_input_usd_per_mtok IS NOT NULL "
            "AND tier2_output_usd_per_mtok IS NOT NULL)",
            name=op.f("ck_llm_price_overrides_tier_trio"),
        ),
        sa.CheckConstraint(
            r"model ~ '^[A-Za-z0-9._:-]{1,128}$'", name=op.f("ck_llm_price_overrides_model_format")
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_llm_price_overrides_version_min")),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name=op.f("fk_llm_price_overrides_updated_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_llm_price_overrides")),
        sa.UniqueConstraint("model", name=op.f("uq_llm_price_overrides_model")),
    )
    op.execute("RESET lock_timeout")


def _refuse_if_any(probe: str, message: str) -> None:
    """Raise ``RuntimeError(message)`` when the ``SELECT 1 ... LIMIT 1`` probe finds a row."""
    if op.get_bind().execute(sa.text(probe)).first() is not None:
        raise RuntimeError(message)


def downgrade() -> None:
    """Downgrade schema.

    Refuses while an audit row, a refund or a signup-allowance off period exists (see the
    module docstring).
    """
    op.execute("SET lock_timeout = '5s'")
    _refuse_if_any(
        "SELECT 1 FROM admin_audit_log LIMIT 1",
        "Cannot downgrade 0057_admin_audit_log: admin_audit_log still has rows. The log is the "
        "record of who changed money and why, and dropping it would lose that silently. "
        "Downgrading past 0057 is not possible once any admin action is recorded.",
    )
    _refuse_if_any(
        "SELECT 1 FROM payment_refunds LIMIT 1",
        "Cannot downgrade 0057_admin_audit_log: payment_refunds still has rows. A row is a "
        "refund or void request that may have reached Paymob, and dropping the table would "
        "lose its outcome silently. Downgrading past 0057 is not possible once any exists.",
    )
    _refuse_if_any(
        "SELECT 1 FROM credit_conversion_rates LIMIT 1",
        "Cannot downgrade 0057_admin_audit_log: credit_conversion_rates still has rows. They are "
        "the admin-set rates that turn a payment into usage units, and dropping the table would "
        "stop those conversions silently. Downgrading past 0057 is not possible once any exists.",
    )
    _refuse_if_any(
        "SELECT 1 FROM billing_settings WHERE version > 1 LIMIT 1",
        "Cannot downgrade 0057_admin_audit_log: billing_settings has been edited (version > 1). "
        "The admin-set credit validity, grace days, seat cap, notice period and rates would be "
        "lost silently. Downgrading past 0057 is not possible once they were changed.",
    )
    _refuse_if_any(
        "SELECT 1 FROM llm_price_overrides LIMIT 1",
        "Cannot downgrade 0057_admin_audit_log: llm_price_overrides still has rows. They are "
        "admin-set AI prices that change what every job costs, and dropping the table would "
        "revert the cost accounting silently. Downgrading past 0057 is not possible once any "
        "exists.",
    )
    _refuse_if_any(
        "SELECT 1 FROM plan_tier_terms WHERE terms_version > 1 LIMIT 1",
        "Cannot downgrade 0057_admin_audit_log: plan_tier_terms holds a terms version above 1. "
        "Subscribers may be billed on it, and dropping the history would lose what each one "
        "agreed to. Downgrading past 0057 is not possible once a plan's terms changed.",
    )
    _refuse_if_any(
        "SELECT 1 FROM plan_tiers WHERE version > 1 LIMIT 1",
        "Cannot downgrade 0057_admin_audit_log: a plan tier has been edited (version > 1). The "
        "edit counter is dropped with the column, and an admin's change would be lost "
        "silently. Downgrading past 0057 is not possible once a tier was changed.",
    )
    _refuse_if_any(
        "SELECT 1 FROM credit_packs WHERE version > 1 "
        "OR (signup_validity_days IS NOT NULL "
        "AND NOT (code = 'signup_teacher' AND signup_validity_days = 30)) LIMIT 1",
        "Cannot downgrade 0057_admin_audit_log: a credit pack has been edited (version > 1) or a "
        "signup pack's validity differs from the one this migration seeded (30 days for "
        "signup_teacher, none for the others). Dropping the columns would revert an admin's "
        "change silently. Downgrading past 0057 is not possible once they were changed.",
    )
    _refuse_if_any(
        "SELECT 1 FROM subscriptions WHERE pending_terms_version IS NOT NULL LIMIT 1",
        "Cannot downgrade 0057_admin_audit_log: a subscription has pending terms. A notice may "
        "already have been sent for the move, and dropping the column would lose it silently. "
        "Downgrading past 0057 is not possible while any move is pending.",
    )
    _refuse_if_any(
        "SELECT 1 FROM signup_allowance_off_periods LIMIT 1",
        "Cannot downgrade 0057_admin_audit_log: signup_allowance_off_periods still has rows. "
        "They are what stops the repair job granting the free signup allowance retroactively "
        "to accounts created while it was off. Downgrading past 0057 is not possible once any "
        "exists.",
    )
    op.drop_table("llm_price_overrides")
    op.drop_table("billing_settings")
    op.drop_column("subscription_periods", "terms_version")
    op.drop_index("ix_subscriptions_terms_move", table_name="subscriptions")
    op.drop_constraint(op.f("fk_subscriptions_pending_terms"), "subscriptions", type_="foreignkey")
    op.drop_constraint(op.f("fk_subscriptions_terms"), "subscriptions", type_="foreignkey")
    op.drop_constraint(
        op.f("ck_subscriptions_pending_terms_paired"), "subscriptions", type_="check"
    )
    op.drop_constraint(op.f("ck_subscriptions_terms_version_min"), "subscriptions", type_="check")
    op.drop_column("subscriptions", "terms_notice_sent_at")
    op.drop_column("subscriptions", "pending_terms_effective_at")
    op.drop_column("subscriptions", "pending_terms_version")
    op.drop_column("subscriptions", "terms_version")
    op.execute("DROP TRIGGER trg_plan_tiers_seed_terms ON plan_tiers")
    op.execute("DROP FUNCTION plan_tiers_seed_terms()")
    op.execute("DROP TRIGGER trg_plan_tier_terms_append_only ON plan_tier_terms")
    op.drop_table("plan_tier_terms")
    for name, table, _columns, _predicate in reversed(_FOREIGN_INDEXES):
        op.drop_index(name, table_name=table)
    op.drop_column("payments", "callback_received_at")
    op.drop_constraint(op.f("ck_credit_packs_signup_validity"), "credit_packs", type_="check")
    op.drop_constraint(op.f("ck_credit_packs_version_min"), "credit_packs", type_="check")
    op.drop_column("credit_packs", "signup_validity_days")
    op.drop_column("credit_packs", "version")
    op.drop_constraint(op.f("ck_plan_tiers_terms_version_min"), "plan_tiers", type_="check")
    op.drop_constraint(op.f("ck_plan_tiers_version_min"), "plan_tiers", type_="check")
    op.drop_column("plan_tiers", "terms_version")
    op.drop_column("plan_tiers", "version")
    op.drop_column("plan_tiers", "paymob_plan_synced_retrial_days")
    op.drop_column("plan_tiers", "paymob_plan_synced_frequency")
    op.drop_column("plan_tiers", "paymob_plan_synced_price_minor")
    op.drop_index(
        "ix_signup_allowance_off_periods_pack_from", table_name="signup_allowance_off_periods"
    )
    op.drop_index("uq_signup_allowance_off_periods_open", table_name="signup_allowance_off_periods")
    op.drop_table("signup_allowance_off_periods")
    op.drop_table("credit_conversion_rates")
    op.drop_index("ix_usage_job_model_costs_model", table_name="usage_job_model_costs")
    op.drop_table("usage_job_model_costs")
    op.drop_index("ix_payment_refunds_status_created_at", table_name="payment_refunds")
    op.drop_index("ix_payment_refunds_payment_id", table_name="payment_refunds")
    op.drop_table("payment_refunds")
    sa.Enum(name="refundstatus").drop(op.get_bind(), checkfirst=False)
    sa.Enum(name="refundkind").drop(op.get_bind(), checkfirst=False)
    op.drop_index("ix_paymob_webhook_failures_received_at", table_name="paymob_webhook_failures")
    op.drop_table("paymob_webhook_failures")
    op.drop_table("job_runs")
    op.execute("DROP TRIGGER trg_admin_audit_log_append_only ON admin_audit_log")
    op.drop_index(IDEMPOTENCY_INDEX, table_name="admin_audit_log")
    op.drop_index("ix_admin_audit_log_created_at", table_name="admin_audit_log")
    op.drop_index("ix_admin_audit_log_target", table_name="admin_audit_log")
    op.drop_table("admin_audit_log")
    op.execute("DROP FUNCTION admin_audit_log_append_only()")
    op.execute("RESET lock_timeout")
