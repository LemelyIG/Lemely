"""ORM models for the usage ledger (Paymob billing spec §4.1, §4.5; migration ``0052``).

Seven tables:

* :class:`UsageRate` and :class:`UsageEstimator`: versioned, admin-edited
  catalogue rows. A job records the ``rate_version`` and ``estimator_version``
  it used.
* :class:`UsageGrant`: one block of units owned by one account, with a priority
  and an optional expiry. ``payment_id`` is a foreign key to ``payments``
  (declared here, created by migration ``0053``); ``teacher_member_id`` is a foreign
  key to ``teacher_members`` (migration ``0054``); ``subscription_period_id`` is a
  plain UUID column here, and migration ``0055`` adds its foreign key when the target
  table exists.
* :class:`UsageGrantBalance`: the cached ``remaining`` and ``held`` of a grant.
  ``reconcile_balances`` rebuilds it from the entries.
* :class:`UsageJob`: one metered action, which is also the usage history row.
  ``payer_chain`` keeps the chain the job reserved against, so ``settle`` can
  keep drawing down it.
* :class:`UsageEntry`: the append-only ledger. A trigger rejects ``UPDATE`` and
  ``DELETE``; :func:`_install_append_only_trigger` installs it on ``create_all``
  databases and migration ``0052`` installs the same SQL on migrated ones.
* :class:`UsageDebt`: negative balance, owed by the payer of last resort.

Sign convention for ``usage_entries.units``: a grant's ``remaining`` is the sum
of its ``grant``, ``settle``, ``expire``, ``refund``, ``adjust`` and
``debt_repay`` entries; its ``held`` is the sum of its ``hold`` (positive) and
``release`` (negative) entries. A ``debt`` entry has no grant and carries the
debt as a negative number; a forgiveness ``adjust`` entry with no grant carries
the forgiven units as a positive number.

The enums mirror (do not import) ``lemely.core``: no module under
``lemely.db.models`` imports ``lemely.core``. ``tests/test_usage_models.py``
pins ``GrantKind`` against ``GRANT_PRIORITY`` and ``EstimatorInputKind`` against
``ESTIMATOR_INPUT_KINDS``.

Foreign keys to ``users`` are ``RESTRICT``: ledger rows are a money record and
the app never hard-deletes a user.
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
from lemely.db.models.enums import TimestampMixin


class GrantKind(enum.Enum):
    period_allowance = "period_allowance"
    seat_allowance = "seat_allowance"
    signup = "signup"
    credit_pack = "credit_pack"
    auto_topup = "auto_topup"
    refund = "refund"
    adjustment = "adjustment"


class UsageJobStatus(enum.Enum):
    open = "open"
    settled = "settled"
    released = "released"
    expired = "expired"


class UsageEntryKind(enum.Enum):
    grant = "grant"
    hold = "hold"
    release = "release"
    settle = "settle"
    expire = "expire"
    refund = "refund"
    adjust = "adjust"
    debt = "debt"
    debt_repay = "debt_repay"


class EstimatorInputKind(enum.Enum):
    pages = "pages"
    marks = "marks"
    questions = "questions"
    none = "none"


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
    )


class UsageRate(TimestampMixin, Base):
    """Units charged per USD of LLM cost, per action, per version."""

    __tablename__ = "usage_rates"
    __table_args__ = (
        sa.UniqueConstraint("version", "action", name="uq_usage_rates_version_action"),
        sa.CheckConstraint("units_per_usd > 0", name="units_per_usd_positive"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    action: Mapped[str] = mapped_column(sa.String, nullable=False)
    units_per_usd: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    effective_from: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)


class UsageEstimator(TimestampMixin, Base):
    """Estimate-range settings per action, per version."""

    __tablename__ = "usage_estimators"
    __table_args__ = (
        sa.UniqueConstraint("version", "action", name="uq_usage_estimators_version_action"),
        sa.CheckConstraint("0 <= base_low AND base_low <= base_high", name="base_range"),
        sa.CheckConstraint(
            "0 <= per_input_low AND per_input_low <= per_input_high", name="per_input_range"
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    action: Mapped[str] = mapped_column(sa.String, nullable=False)
    input_kind: Mapped[EstimatorInputKind] = mapped_column(
        sa.Enum(EstimatorInputKind, name="estimatorinputkind"), nullable=False
    )
    base_low: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    base_high: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    per_input_low: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    per_input_high: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    effective_from: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)


class UsageGrant(TimestampMixin, Base):
    """A block of units owned by one account."""

    __tablename__ = "usage_grants"
    __table_args__ = (
        sa.UniqueConstraint(
            "owner_user_id", "idempotency_key", name="uq_usage_grants_owner_idempotency"
        ),
        sa.CheckConstraint("units > 0", name="units_positive"),
        sa.CheckConstraint(
            "expires_at IS NULL OR expires_at > effective_at", name="expires_after_effective"
        ),
        sa.CheckConstraint(
            "(kind = 'seat_allowance') = (teacher_member_id IS NOT NULL)", name="seat_link"
        ),
        sa.CheckConstraint(
            "NOT (visible AND kind IN ('period_allowance', 'seat_allowance'))",
            name="allowance_hidden",
        ),
        sa.CheckConstraint(
            "kind NOT IN ('credit_pack', 'auto_topup') OR visible", name="credit_visible"
        ),
        # The spend order of spec §5.6: priority, soonest expiry first with no-expiry last,
        # then oldest, then id as the tie-break.
        sa.Index(
            "ix_usage_grants_owner_spend",
            "owner_user_id",
            "priority",
            sa.text("expires_at ASC NULLS LAST"),
            "effective_at",
            "id",
        ),
        sa.Index(
            "ix_usage_grants_expiring",
            "expires_at",
            postgresql_where=sa.text("expires_at IS NOT NULL"),
        ),
        sa.Index(
            "ix_usage_grants_seat",
            "teacher_member_id",
            postgresql_where=sa.text("teacher_member_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    kind: Mapped[GrantKind] = mapped_column(sa.Enum(GrantKind, name="grantkind"), nullable=False)
    visible: Mapped[bool] = mapped_column(sa.Boolean, nullable=False)
    teacher_member_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("teacher_members.id", ondelete="RESTRICT"),
        nullable=True,
    )
    """The seat a ``seat_allowance`` grant belongs to (FK added by 0054_teacher_team).

    ``RESTRICT``, stated: ``teacher_members`` rows are never deleted (status ``removed``
    instead), and a seat grant must never lose its seat link, which would turn it into
    a plain allowance.
    """
    priority: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False)
    units: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    effective_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    expires_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    payment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("payments.id"), nullable=True
    )
    subscription_period_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    idempotency_key: Mapped[str] = mapped_column(sa.String, nullable=False)


class UsageGrantBalance(TimestampMixin, Base):
    """Cached ``remaining`` and ``held`` for one grant; rebuilt from the entries."""

    __tablename__ = "usage_grant_balances"
    __table_args__ = (
        sa.CheckConstraint("0 <= held AND held <= remaining", name="held_within_remaining"),
    )

    grant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("usage_grants.id", ondelete="CASCADE"),
        primary_key=True,
    )
    remaining: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    held: Mapped[int] = mapped_column(sa.BigInteger, nullable=False, server_default=sa.literal(0))


class UsageJob(TimestampMixin, Base):
    """One metered action: reservation, charge and the usage-history row.

    ``charged`` is the actual cost in units (``ceil`` of ``actual_cost_usd`` at the
    job's rate); ``debt_created`` is the part of it that no grant could cover, so
    the amount actually drawn from grants is ``charged - debt_created``.
    """

    __tablename__ = "usage_jobs"
    __table_args__ = (
        sa.CheckConstraint(
            "0 <= estimate_low AND estimate_low <= estimate_high", name="estimate_range"
        ),
        sa.CheckConstraint("reserved >= 0", name="reserved_nonnegative"),
        sa.CheckConstraint("charged >= 0", name="charged_nonnegative"),
        sa.CheckConstraint(
            "debt_created >= 0 AND debt_created <= charged", name="debt_within_charged"
        ),
        sa.CheckConstraint(
            "(status = 'settled') = (settled_at IS NOT NULL)", name="settled_at_matches"
        ),
        sa.Index("ix_usage_jobs_actor_created", "actor_user_id", "created_at"),
        sa.Index(
            "ix_usage_jobs_open_expires",
            "expires_at",
            postgresql_where=sa.text("status = 'open'"),
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, unique=True)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    teacher_member_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    action: Mapped[str] = mapped_column(sa.String, nullable=False)
    estimate_low: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    estimate_high: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    estimator_version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    reserved: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    charged: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.literal(0)
    )
    debt_created: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.literal(0)
    )
    actual_cost_usd: Mapped[Decimal | None] = mapped_column(sa.Numeric(12, 6), nullable=True)
    rate_version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    payer_chain: Mapped[list[dict[str, str | int | bool | None]]] = mapped_column(
        JSONB, nullable=False
    )
    status: Mapped[UsageJobStatus] = mapped_column(
        sa.Enum(UsageJobStatus, name="usagejobstatus"),
        nullable=False,
        server_default=sa.text("'open'::usagejobstatus"),
    )
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    settled_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)


class UsageDebt(TimestampMixin, Base):
    """Units an account owes after a job overran its chain."""

    __tablename__ = "usage_debts"
    __table_args__ = (
        sa.CheckConstraint("units > 0", name="units_positive"),
        sa.CheckConstraint(
            "0 <= outstanding AND outstanding <= units", name="outstanding_within_units"
        ),
        sa.Index("ix_usage_debts_job", "job_id"),
        sa.Index(
            "ix_usage_debts_owner_outstanding",
            "owner_user_id",
            "created_at",
            postgresql_where=sa.text("outstanding > 0"),
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("usage_jobs.job_id", ondelete="RESTRICT"), nullable=True
    )
    units: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    outstanding: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)


class UsageEntry(Base):
    """One append-only ledger line. ``created_at`` only: a row is never updated."""

    __tablename__ = "usage_entries"
    __table_args__ = (
        sa.UniqueConstraint(
            "grant_id", "idempotency_key", "kind", name="uq_usage_entries_grant_key_kind"
        ),
        sa.CheckConstraint("units <> 0", name="units_nonzero"),
        sa.CheckConstraint("grant_id IS NOT NULL OR debt_id IS NOT NULL", name="has_target"),
        sa.CheckConstraint(
            "kind NOT IN ('debt', 'debt_repay') OR debt_id IS NOT NULL", name="debt_kinds_link"
        ),
        sa.Index(
            "uq_usage_entries_debt_key_kind",
            "debt_id",
            "idempotency_key",
            "kind",
            unique=True,
            postgresql_where=sa.text("grant_id IS NULL"),
        ),
        sa.Index("ix_usage_entries_grant", "grant_id"),
        sa.Index("ix_usage_entries_job", "job_id"),
        sa.Index("ix_usage_entries_debt", "debt_id"),
        sa.Index(
            "ix_usage_entries_cap",
            "teacher_member_id",
            "event_at",
            postgresql_where=sa.text("teacher_member_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    grant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("usage_grants.id", ondelete="RESTRICT"), nullable=True
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("usage_jobs.job_id", ondelete="RESTRICT"), nullable=True
    )
    debt_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("usage_debts.id", ondelete="RESTRICT"), nullable=True
    )
    teacher_member_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    kind: Mapped[UsageEntryKind] = mapped_column(
        sa.Enum(UsageEntryKind, name="usageentrykind"), nullable=False
    )
    units: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    rate_version: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    event_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(sa.String, nullable=False)
    reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )


# ---------------------------------------------------------------------------
# Append-only trigger (spec §4.5, §6). Migration 0052 runs the same two statements.
# ---------------------------------------------------------------------------

APPEND_ONLY_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION usage_entries_reject_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'usage_entries is append-only: % rejected', TG_OP;
END;
$$
"""

APPEND_ONLY_TRIGGER_SQL = """
CREATE TRIGGER trg_usage_entries_append_only
BEFORE UPDATE OR DELETE ON usage_entries
FOR EACH ROW EXECUTE FUNCTION usage_entries_reject_mutation()
"""


def _install_append_only_trigger(
    target: sa.Table, connection: sa.Connection, **_kw: object
) -> None:
    """Install the append-only trigger right after ``create_all`` creates the table."""
    if connection.dialect.name == "postgresql":
        connection.execute(sa.text(APPEND_ONLY_FUNCTION_SQL))
        connection.execute(sa.text(APPEND_ONLY_TRIGGER_SQL))


event.listen(UsageEntry.__table__, "after_create", _install_append_only_trigger)


__all__ = [
    "APPEND_ONLY_FUNCTION_SQL",
    "APPEND_ONLY_TRIGGER_SQL",
    "EstimatorInputKind",
    "GrantKind",
    "UsageDebt",
    "UsageEntry",
    "UsageEntryKind",
    "UsageEstimator",
    "UsageGrant",
    "UsageGrantBalance",
    "UsageJob",
    "UsageJobStatus",
    "UsageRate",
]
