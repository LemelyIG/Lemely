"""Tables the admin billing surface owns (Phase 07, migration ``0057_admin_audit_log``).

* ``job_runs``: last run and outcome per sweeper job, one row per job name (health view).
* ``paymob_webhook_failures``: callbacks refused for a bad or missing HMAC (problem queue).
  A row holds the kind, a fixed reason, the best-effort remote address and the arrival time,
  and never a body, an HMAC or an object id. Rows are written by unauthenticated requests;
  they are kept 90 days (the sweeper prunes by ``received_at``).
* ``payment_refunds``: refund and void attempts, inserted *before* Paymob is called
  (spec §6: Paymob has no idempotency keys). ``reverse_change`` is the admin's choice of "money
  only" or "money and reverse the change" for a Phase 06 charge; it is stored on this row so the
  transaction that closes the refund (or an inquiry hours later) still knows it.
* ``usage_job_model_costs``: LLM cost per (job, model) for the margin view.
* ``billing_settings``: the single row of admin-set scalar settings (credit validity, grace days,
  extra-seat cap, price-change notice period, margin FX rate, code-execution price). Every
  column has a range CHECK; ``id = 1`` is enforced, and the row is inserted by the migration and
  by the ``after_create`` listener below on ``create_all`` databases.
* ``llm_price_overrides``: an admin-set price per million tokens for one model, overriding the
  code defaults of the cost accounting (UD13-D).
* ``credit_conversion_rates``: the fixed, admin-set conversion from a payment's currency to usage
  units (UD-12), one row per currency: ``units_per_minor`` units per minor currency unit
  (per piaster for EGP). Unset means no automatic conversion: a payment that needs one stays
  paid and is alerted for manual handling.
* ``signup_allowance_off_periods``: when a free signup allowance (a ``signup_*`` credit pack)
  was switched off (``units = 0``) and back on. The repair job grants the allowance to verified
  accounts that lack it, so without this history an admin raising the pack from 0 would grant
  it retroactively to everyone who signed up while it was off. The repair skips accounts
  created inside an off period: ``off_from <= users.created_at < coalesce(off_until, infinity)``.

The ``sa.Index`` objects at the bottom index Phase 01/02 tables for the admin queries;
declaring them here keeps the ORM and migration ``0057`` in step without editing
those phases' models.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from lemely.db.base import Base
from lemely.db.models.billing import Payment, PaymobEvent
from lemely.db.models.enums import TimestampMixin
from lemely.db.models.usage import UsageEntry, UsageJob


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
    )


def _created_at() -> Mapped[datetime]:
    return mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


class RefundKind(enum.Enum):
    """A partial or full refund, or a same-day void."""

    refund = "refund"
    void = "void"


class RefundStatus(enum.Enum):
    """``unknown`` means Paymob did not answer; inquiry resolves it before any retry."""

    requested = "requested"
    succeeded = "succeeded"
    failed = "failed"
    unknown = "unknown"


class JobRun(Base):
    """The latest run of one sweeper job, upserted by name around every run.

    ``last_finished_at`` and ``last_outcome`` are NULL from the first start until the first
    finish. ``last_error`` is capped at 200 characters by the column: the recorder keeps the
    whole text (exception type and message) inside that.
    """

    __tablename__ = "job_runs"
    __table_args__ = (
        sa.CheckConstraint("last_outcome IN ('ok', 'failed')", name="outcome_known"),
        sa.CheckConstraint("consecutive_failures >= 0", name="failures_non_negative"),
        sa.CheckConstraint("total_runs >= 0 AND total_failures >= 0", name="totals_non_negative"),
    )

    name: Mapped[str] = mapped_column(sa.String(100), primary_key=True)
    last_started_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    last_finished_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    last_outcome: Mapped[str | None] = mapped_column(sa.String(16), nullable=True)
    last_result_count: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    last_error: Mapped[str | None] = mapped_column(sa.String(200), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    consecutive_failures: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.text("0")
    )
    total_runs: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.text("0")
    )
    total_failures: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.text("0")
    )


class PaymobWebhookFailure(Base):
    """One callback refused before processing (bad or missing HMAC). No body is stored."""

    __tablename__ = "paymob_webhook_failures"
    __table_args__ = (
        sa.CheckConstraint("kind IN ('transaction', 'token', 'subscription')", name="kind_known"),
        sa.Index("ix_paymob_webhook_failures_received_at", "received_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    kind: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    reason: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    remote_addr: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    """Best effort: spoofable off the Worker (``client_errors._client_ip``)."""
    received_at: Mapped[datetime] = _created_at()


class PaymentRefund(TimestampMixin, Base):
    """One admin refund or void of a payment, written before Paymob is called."""

    __tablename__ = "payment_refunds"
    __table_args__ = (
        sa.CheckConstraint("amount_minor > 0", name="amount_positive"),
        sa.CheckConstraint("clawed_back_units >= 0", name="clawback_non_negative"),
        sa.Index("ix_payment_refunds_payment_id", "payment_id"),
        sa.Index("ix_payment_refunds_status_created_at", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    payment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("payments.id", ondelete="RESTRICT"), nullable=False
    )
    admin_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    kind: Mapped[RefundKind] = mapped_column(sa.Enum(RefundKind, name="refundkind"), nullable=False)
    status: Mapped[RefundStatus] = mapped_column(
        sa.Enum(RefundStatus, name="refundstatus"),
        nullable=False,
        server_default=sa.text("'requested'::refundstatus"),
    )
    amount_minor: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    reason: Mapped[str] = mapped_column(sa.Text, nullable=False)
    paymob_response: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    clawed_back_units: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.text("0")
    )
    reverse_change: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.false()
    )
    """The admin asked to reverse what the payment bought (a Phase 06 proration or extra seats),
    not only to return the money. ``False`` is money only, the default."""


class UsageJobModelCost(Base):
    """The USD cost one model contributed to one usage job."""

    __tablename__ = "usage_job_model_costs"
    __table_args__ = (
        sa.UniqueConstraint("usage_job_id", "model"),
        sa.CheckConstraint("cost_usd >= 0", name="cost_non_negative"),
        sa.Index("ix_usage_job_model_costs_model", "model"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    usage_job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("usage_jobs.id", ondelete="CASCADE"), nullable=False
    )
    model: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    cost_usd: Mapped[Decimal] = mapped_column(sa.Numeric(12, 6), nullable=False)
    created_at: Mapped[datetime] = _created_at()


class CreditConversionRate(TimestampMixin, Base):
    """Usage units one minor unit of a currency buys, set by an admin (UD-12).

    ``updated_by`` is the admin who last changed the rate (``SET NULL`` if that account is
    ever deleted; ``admin_audit_log`` keeps the history). The rate is exact decimal data,
    never a float.
    """

    __tablename__ = "credit_conversion_rates"
    __table_args__ = (
        sa.CheckConstraint("units_per_minor > 0", name="rate_positive"),
        sa.CheckConstraint(r"currency ~ '^[A-Z]{3}$'", name="currency_code"),
        sa.CheckConstraint("version >= 1", name="version_min"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    currency: Mapped[str] = mapped_column(sa.String(3), nullable=False, unique=True)
    units_per_minor: Mapped[Decimal] = mapped_column(sa.Numeric(18, 6), nullable=False)
    version: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default=sa.text("1"))
    """Optimistic-concurrency counter: an admin edit sends the version it read."""
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class BillingSettings(TimestampMixin, Base):
    """The one row of admin-set billing settings (``id = 1``, enforced).

    ``margin_egp_per_usd`` and ``code_execution_usd_per_hour`` are NULL until an admin sets them
    (no margin rate: the margin view shows USD only; no code-execution price: that cost is not
    estimated). ``version`` is the optimistic-concurrency counter.
    """

    __tablename__ = "billing_settings"
    __table_args__ = (
        sa.CheckConstraint("id = 1", name="singleton"),
        sa.CheckConstraint(
            "credit_validity_months BETWEEN 1 AND 120", name="credit_validity_range"
        ),
        sa.CheckConstraint("grace_days BETWEEN 1 AND 7", name="grace_days_range"),
        sa.CheckConstraint("max_extra_seats BETWEEN 1 AND 10000", name="max_extra_seats_range"),
        sa.CheckConstraint(
            "price_change_notice_days BETWEEN 7 AND 90", name="price_change_notice_range"
        ),
        sa.CheckConstraint(
            "margin_egp_per_usd IS NULL "
            "OR (margin_egp_per_usd > 0 AND margin_egp_per_usd <= 10000)",
            name="margin_rate_range",
        ),
        sa.CheckConstraint(
            "code_execution_usd_per_hour IS NULL OR code_execution_usd_per_hour >= 0",
            name="code_execution_nonneg",
        ),
        sa.CheckConstraint("version >= 1", name="version_min"),
    )

    id: Mapped[int] = mapped_column(
        sa.SmallInteger, primary_key=True, autoincrement=False, server_default=sa.text("1")
    )
    credit_validity_months: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.text("12")
    )
    grace_days: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default=sa.text("3"))
    max_extra_seats: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.text("200")
    )
    price_change_notice_days: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.text("14")
    )
    margin_egp_per_usd: Mapped[Decimal | None] = mapped_column(sa.Numeric(12, 4), nullable=True)
    code_execution_usd_per_hour: Mapped[Decimal | None] = mapped_column(
        sa.Numeric(10, 6), nullable=True
    )
    version: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default=sa.text("1"))
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


SEED_BILLING_SETTINGS_SQL = "INSERT INTO billing_settings (id) VALUES (1) ON CONFLICT DO NOTHING"


def _seed_billing_settings(target: sa.Table, connection: sa.Connection, **_kw: object) -> None:
    """Insert the single row right after ``create_all`` creates the table.

    The migration does the same, so a settings read never finds the table empty.
    """
    if connection.dialect.name == "postgresql":
        connection.execute(sa.text(SEED_BILLING_SETTINGS_SQL))


event.listen(BillingSettings.__table__, "after_create", _seed_billing_settings)


class LlmPriceOverride(TimestampMixin, Base):
    """An admin-set price per million tokens for one model (UD13-D).

    Overrides the code defaults of the cost accounting for that model. The optional cache
    prices apply to cached input and cache writes; ``tier_threshold_tokens`` with the two
    ``tier2_*`` prices describe a higher price for prompts above that many tokens, and are
    all set together or all NULL.
    """

    __tablename__ = "llm_price_overrides"
    __table_args__ = (
        sa.CheckConstraint(
            "input_usd_per_mtok >= 0 AND output_usd_per_mtok >= 0 "
            "AND (cached_input_usd_per_mtok IS NULL OR cached_input_usd_per_mtok >= 0) "
            "AND (cache_write_5m_usd_per_mtok IS NULL OR cache_write_5m_usd_per_mtok >= 0) "
            "AND (cache_write_1h_usd_per_mtok IS NULL OR cache_write_1h_usd_per_mtok >= 0) "
            "AND (tier2_input_usd_per_mtok IS NULL OR tier2_input_usd_per_mtok >= 0) "
            "AND (tier2_output_usd_per_mtok IS NULL OR tier2_output_usd_per_mtok >= 0)",
            name="rates_nonneg",
        ),
        sa.CheckConstraint(
            "(tier_threshold_tokens IS NULL AND tier2_input_usd_per_mtok IS NULL "
            "AND tier2_output_usd_per_mtok IS NULL) "
            "OR (tier_threshold_tokens > 0 AND tier2_input_usd_per_mtok IS NOT NULL "
            "AND tier2_output_usd_per_mtok IS NOT NULL)",
            name="tier_trio",
        ),
        sa.CheckConstraint(r"model ~ '^[A-Za-z0-9._:-]{1,128}$'", name="model_format"),
        sa.CheckConstraint("version >= 1", name="version_min"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    model: Mapped[str] = mapped_column(sa.String(128), nullable=False, unique=True)
    input_usd_per_mtok: Mapped[Decimal] = mapped_column(sa.Numeric(14, 6), nullable=False)
    output_usd_per_mtok: Mapped[Decimal] = mapped_column(sa.Numeric(14, 6), nullable=False)
    cached_input_usd_per_mtok: Mapped[Decimal | None] = mapped_column(
        sa.Numeric(14, 6), nullable=True
    )
    cache_write_5m_usd_per_mtok: Mapped[Decimal | None] = mapped_column(
        sa.Numeric(14, 6), nullable=True
    )
    cache_write_1h_usd_per_mtok: Mapped[Decimal | None] = mapped_column(
        sa.Numeric(14, 6), nullable=True
    )
    tier_threshold_tokens: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    tier2_input_usd_per_mtok: Mapped[Decimal | None] = mapped_column(
        sa.Numeric(14, 6), nullable=True
    )
    tier2_output_usd_per_mtok: Mapped[Decimal | None] = mapped_column(
        sa.Numeric(14, 6), nullable=True
    )
    version: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default=sa.text("1"))
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class SignupAllowanceOffPeriod(Base):
    """A window in which one signup allowance pack was off (``units = 0``).

    ``off_until`` is NULL while the pack is still off, and a pack has at most one such open
    window. The window is half-open: an account created at ``off_from`` was created while the
    allowance was off; one created at ``off_until`` was not.
    """

    __tablename__ = "signup_allowance_off_periods"
    __table_args__ = (
        sa.CheckConstraint("off_until IS NULL OR off_until >= off_from", name="window_ordered"),
        sa.Index(
            "uq_signup_allowance_off_periods_open",
            "credit_pack_id",
            unique=True,
            postgresql_where=sa.text("off_until IS NULL"),
        ),
        sa.Index("ix_signup_allowance_off_periods_pack_from", "credit_pack_id", "off_from"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    credit_pack_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("credit_packs.id", ondelete="RESTRICT"), nullable=False
    )
    off_from: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    off_until: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = _created_at()


# Indexes on tables other phases own, for the admin queries (migration 0057 creates them).
# Partial on ``actual_cost_usd IS NOT NULL`` (the margin query states it): a plain ``created_at``
# index would also serve, and win, the lead's usage-history query (``ix_usage_jobs_member_created``
# is its index; ``tests/test_migration_subscription_periods.py`` pins the plan).
sa.Index(
    "ix_admin_usage_jobs_created_at",
    UsageJob.created_at,
    postgresql_where=sa.text("actual_cost_usd IS NOT NULL"),
)
sa.Index("ix_admin_usage_jobs_action_estimator", UsageJob.action, UsageJob.estimator_version)
sa.Index("ix_admin_payments_paid_at", Payment.paid_at)
sa.Index("ix_admin_payments_status_created_at", Payment.status, Payment.created_at)
sa.Index("ix_admin_usage_entries_kind_event_at", UsageEntry.kind, UsageEntry.event_at)
sa.Index("ix_admin_paymob_events_created_at", PaymobEvent.created_at)

__all__ = [
    "BillingSettings",
    "CreditConversionRate",
    "JobRun",
    "LlmPriceOverride",
    "PaymentRefund",
    "PaymobWebhookFailure",
    "RefundKind",
    "RefundStatus",
    "SignupAllowanceOffPeriod",
    "UsageJobModelCost",
]
