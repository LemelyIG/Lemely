"""ORM models for the billing catalogue, subscriptions and payments (billing spec §4.1-§4.3).

Money is integer minor units (piasters). A ``paid`` :class:`Payment` *is* the
receipt; no other receipt record exists (spec §4.2). Lifecycle code for the new
subscription columns lands in Phase 05; this module only declares them.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Final

import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lemely.db.base import Base
from lemely.db.models.admin_audit import APPEND_ONLY_FUNCTION_SQL
from lemely.db.models.enums import PlanInterval, SubscriptionStatus, TimestampMixin

#: The statuses ``uq_subscriptions_one_live_per_user`` allows at most one of, per
#: user, among paid-path rows (spec §4.3; index R8). A pending checkout counts: it
#: holds the user's one live slot until it is paid or superseded.
LIVE_SUBSCRIPTION_STATUSES: Final = (
    SubscriptionStatus.pending_first_payment,
    SubscriptionStatus.active,
    SubscriptionStatus.past_due,
)

#: The statuses in which a plan is in force: access, allowances, teacher seat allowances.
#: ``past_due`` is the 3-day grace after a failed renewal (spec §2.6). A subset of
#: ``LIVE_SUBSCRIPTION_STATUSES`` (a pending checkout is not a plan in force), and equal to
#: ``teacher_team_repo.LIVE_PLAN_STATUSES``, which ``tests/test_migration_subscription_periods.py``
#: pins.
PLAN_LIVE_STATUSES: Final = (SubscriptionStatus.active, SubscriptionStatus.past_due)

#: Compares the enum itself: ``status::text`` is only STABLE, and Postgres rejects a
#: non-IMMUTABLE function in an index predicate. Migration 0053 therefore commits its
#: two ``ADD VALUE`` statements before it creates this index.
_LIVE_PAID_PREDICATE = (
    "status IN ('pending_first_payment', 'active', 'past_due') AND payer_user_id IS NOT NULL"
)


class PlanAudience(enum.Enum):
    """Which role a plan tier is sold to."""

    student = "student"
    teacher = "teacher"


class PaymentPurpose(enum.Enum):
    """What a payment buys (spec §4.2)."""

    subscription_first = "subscription_first"
    subscription_renewal = "subscription_renewal"
    upgrade_proration = "upgrade_proration"
    extra_seats = "extra_seats"
    credit_pack = "credit_pack"
    auto_topup = "auto_topup"


class PaymentStatus(enum.Enum):
    """Lifecycle of one payment attempt (spec §4.2)."""

    created = "created"
    pending = "pending"
    paid = "paid"
    failed = "failed"
    failed_mismatch = "failed_mismatch"
    refunded = "refunded"
    partially_refunded = "partially_refunded"
    voided = "voided"


class PaymobEventKind(enum.Enum):
    """Which Paymob callback a stored event came from."""

    transaction = "transaction"
    token = "token"  # noqa: S105 - a callback kind label, not a credential
    subscription = "subscription"


class PlanTier(TimestampMixin, Base):
    """One purchasable tier at one interval (spec §4.1); monthly and yearly are two rows."""

    __tablename__ = "plan_tiers"
    __table_args__ = (
        sa.CheckConstraint("allowance_units >= 0", name="allowance_nonneg"),
        sa.CheckConstraint("included_seats >= 0", name="seats_nonneg"),
        sa.CheckConstraint("seat_allowance_units >= 0", name="seat_allowance_nonneg"),
        sa.CheckConstraint("extra_seat_price_minor >= 0", name="extra_seat_price_nonneg"),
        sa.CheckConstraint("paymob_plan_mode IN ('test', 'live')", name="paymob_plan_mode_values"),
        sa.CheckConstraint(
            "(paymob_plan_id IS NULL) = (paymob_plan_mode IS NULL)", name="paymob_plan_mode_linked"
        ),
        sa.CheckConstraint("version >= 1", name="version_min"),
        sa.CheckConstraint("terms_version >= 1", name="terms_version_min"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    code: Mapped[str] = mapped_column(sa.String, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(sa.String, nullable=False)
    price_minor: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.literal(0)
    )
    currency: Mapped[str] = mapped_column(
        sa.String, nullable=False, server_default=sa.literal("EGP")
    )
    interval: Mapped[PlanInterval | None] = mapped_column(
        sa.Enum(PlanInterval, name="planinterval"),
        nullable=True,
    )
    max_devices: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.literal(3)
    )
    features: Mapped[dict] = mapped_column(  # type: ignore[type-arg]
        JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
    )
    audience: Mapped[PlanAudience] = mapped_column(
        sa.Enum(PlanAudience, name="planaudience"),
        nullable=False,
        server_default=sa.text("'student'::planaudience"),
    )
    #: Usage units granted per period; hidden from users (spec §2.1).
    allowance_units: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.literal(0)
    )
    paymob_plan_id: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True, unique=True)
    paymob_plan_mode: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    """The Paymob key mode (``test`` or ``live``) ``paymob_plan_id`` was created under; set exactly
    when the id is. A plan id only exists in the mode of the keys that made it, so a checkout
    under the other mode's keys is refused rather than sent to Paymob to 404 (audit I8)."""
    paymob_plan_synced_price_minor: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    """``price_minor`` as last sent to Paymob when the plan was created (drift warning)."""
    paymob_plan_synced_frequency: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    """Paymob plan frequency in days (30 or 360) as last sent when the plan was created."""
    paymob_plan_synced_retrial_days: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    """``retrial_days`` as last sent when the plan was created (the admin grace-days setting)."""
    version: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default=sa.text("1"))
    """Optimistic-concurrency counter: an admin edit sends the version it read."""
    terms_version: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.text("1")
    )
    """The current row of ``plan_tier_terms``. A price or entitlement change inserts the next
    version there; subscribers move to it at their next renewal after a notice."""
    is_active: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.true())
    #: Teacher tiers only (zero on student tiers).
    included_seats: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.literal(0)
    )
    seat_allowance_units: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.literal(0)
    )
    extra_seat_price_minor: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.literal(0)
    )

    subscriptions: Mapped[list[Subscription]] = relationship(
        "Subscription", back_populates="plan_tier", foreign_keys="Subscription.plan_tier_id"
    )


#: The payments an auto top-up still waits on, for ``ix_payments_auto_topup_in_flight``.
_AUTO_TOPUP_IN_FLIGHT_PREDICATE = "purpose = 'auto_topup' AND status IN ('created', 'pending')"

#: Ties a queue ``dedupe_key`` to the purpose it was minted for
#: (``ck_payments_dedupe_key_purpose``).
#: A renewal seat charge and a seat purchase are both ``extra_seats``: only the key's prefix tells
#: the paid handler to clear a grace instead of granting seats, so a wrong pairing is an error.
#: ``starts_with`` (not ``LIKE``) so the ``_`` in a prefix is literal.
_DEDUPE_KEY_PURPOSE_CHECK = (
    "dedupe_key IS NULL "
    "OR (purpose = 'auto_topup' AND starts_with(dedupe_key, 'auto_topup:')) "
    "OR (purpose = 'extra_seats' AND starts_with(dedupe_key, 'extra_seat_renewal:'))"
)


class Subscription(TimestampMixin, Base):
    """A user's subscription to a :class:`PlanTier`.

    ``user_id`` is the beneficiary; ``payer_user_id`` is who pays (a parent for a
    child) and is ``NULL`` on the manual-activation path. A user may hold a
    personal subscription *and* a school seat simultaneously.
    """

    __tablename__ = "subscriptions"
    __table_args__ = (
        sa.Index("ix_subscriptions_user_id_status", "user_id", "status"),
        sa.Index(
            "uq_subscriptions_one_live_per_user",
            "user_id",
            unique=True,
            postgresql_where=sa.text(_LIVE_PAID_PREDICATE),
        ),
        # The subscription sweeps of Phase 05 (migration 0055). Each is partial on the sweep's own
        # predicate and ordered as the sweep orders its batch; a sweep whose WHERE does not imply
        # the index predicate loses the index (``tests/test_migration_subscription_periods.py``
        # pins the predicates).
        # ``expire_overdue``: past due, past its grace, linked to Paymob.
        sa.Index(
            "ix_subscriptions_grace_expiry",
            "grace_until",
            "id",
            postgresql_where=sa.text("status = 'past_due' AND paymob_subscription_id IS NOT NULL"),
        ),
        # The Paymob cancel still to push (cancel at period end, ended rows).
        sa.Index(
            "ix_subscriptions_paymob_cancel_pending",
            "current_period_end",
            "id",
            postgresql_where=sa.text(
                "paymob_subscription_id IS NOT NULL AND paymob_cancelled_at IS NULL"
            ),
        ),
        # Period-end ends and amount candidates: linked rows in a live status, by period end.
        sa.Index(
            "ix_subscriptions_paymob_live_period_end",
            "current_period_end",
            "id",
            postgresql_where=sa.text(
                "paymob_subscription_id IS NOT NULL"
                " AND status IN ('pending_first_payment', 'active', 'past_due')"
            ),
        ),
        # The daily drift check: linked rows that are live or still to be cancelled, oldest first.
        sa.Index(
            "ix_subscriptions_paymob_drift",
            "updated_at",
            "id",
            postgresql_where=sa.text(
                "paymob_subscription_id IS NOT NULL AND (paymob_cancelled_at IS NULL"
                " OR status IN ('pending_first_payment', 'active', 'past_due'))"
            ),
        ),
        sa.CheckConstraint("extra_seats >= 0", name="extra_seats_nonneg"),
        sa.CheckConstraint(
            "pending_extra_seats IS NULL OR pending_extra_seats >= 0",
            name="pending_extra_seats_nonneg",
        ),
        sa.CheckConstraint("terms_version >= 1", name="terms_version_min"),
        sa.CheckConstraint(
            "(pending_terms_version IS NULL) = (pending_terms_effective_at IS NULL)",
            name="pending_terms_paired",
        ),
        sa.CheckConstraint(
            "(previous_amount_minor IS NULL) = (amount_replaced_at IS NULL)",
            name="previous_amount_paired",
        ),
        # The terms the subscriber is on, and the terms it moves to at renewal. Composite so a
        # version of another tier is impossible. ``MATCH SIMPLE`` (the default) skips the
        # pending key while ``pending_terms_version`` is NULL.
        sa.ForeignKeyConstraint(
            ["plan_tier_id", "terms_version"],
            ["plan_tier_terms.plan_tier_id", "plan_tier_terms.terms_version"],
            name="fk_subscriptions_terms",
        ),
        sa.ForeignKeyConstraint(
            ["plan_tier_id", "pending_terms_version"],
            ["plan_tier_terms.plan_tier_id", "plan_tier_terms.terms_version"],
            name="fk_subscriptions_pending_terms",
        ),
        # Which live subscribers of a tier are still on older terms (the renewal move sweep).
        sa.Index(
            "ix_subscriptions_terms_move",
            "plan_tier_id",
            "terms_version",
            postgresql_where=sa.text("status IN ('active', 'past_due')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    plan_tier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("plan_tiers.id"),
        nullable=False,
    )
    status: Mapped[SubscriptionStatus] = mapped_column(
        sa.Enum(SubscriptionStatus, name="subscriptionstatus"),
        nullable=False,
        server_default=sa.text("'inactive'::subscriptionstatus"),
    )
    is_manually_activated: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.false()
    )
    activated_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    activation_note: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    """Why a platform admin activated or rejected this subscription (X-02).

    Nullable because a note is a human sentence with no honest default; see
    migration ``0019`` for why it is not ``NOT NULL DEFAULT ''``."""
    current_period_end: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    payer_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True
    )
    cancel_at_period_end: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.false()
    )
    pending_plan_tier_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("plan_tiers.id"), nullable=True
    )
    current_period_start: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    grace_until: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    extra_seats: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.literal(0)
    )
    pending_extra_seats: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    paymob_subscription_id: Mapped[int | None] = mapped_column(
        sa.BigInteger, nullable=True, unique=True
    )
    #: Optimistic-lock counter for webhook races; Phase 05 decides its use.
    version: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default=sa.literal(1))
    paymob_amount_minor: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    """The renewal amount Lemely last set at Paymob: the first payment's amount, then each PUT.
    The next renewal charge must equal it (spec §6 mismatch rule)."""
    paymob_cancelled_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    """When the Paymob subscription was cancelled; ``None`` while Paymob may still charge."""
    suspended_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    """Set when a Paymob suspension scheduled this row's cancel at period end (migration 0058).

    The cause marker that lets a ``resumed`` callback undo that cancel and no other. Cleared by
    the resume and by the payer's own cancel."""
    previous_amount_minor: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    """The renewal amount the last PUT replaced, with ``amount_replaced_at`` (migration 0058).

    Paymob can charge up to three days early, so a PUT can land after it charged the old amount.
    A renewal at this amount, charged before ``amount_replaced_at``, is still paid. Cleared when a
    renewal grants a period."""
    amount_replaced_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    extra_seat_grace_until: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    """Fallback path (spec §5.4): when the extra seats lapse if no seat charge succeeds."""
    extra_seat_grace_payment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("payments.id", ondelete="SET NULL"), nullable=True
    )
    """First failed renewal seat charge of the grace episode; kept after the drop so the
    same failure never starts a second grace."""
    terms_version: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.text("1")
    )
    """The ``plan_tier_terms`` version this subscription is billed on."""
    pending_terms_version: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    """The terms it moves to at ``pending_terms_effective_at`` (its next renewal)."""
    pending_terms_effective_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    terms_notice_sent_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    """When the notice email for the pending move was sent (never earlier than the notice period
    before the effective date)."""

    plan_tier: Mapped[PlanTier] = relationship(
        "PlanTier", back_populates="subscriptions", foreign_keys=[plan_tier_id]
    )


class SubscriptionPeriod(TimestampMixin, Base):
    """One paid period of a :class:`Subscription` (spec §4.3).

    Unique ``(subscription_id, period_start)`` guarantees one allowance grant per period, so a
    duplicate renewal webhook is harmless. ``payment_id`` is unique: one payment pays for one
    period at most.
    """

    __tablename__ = "subscription_periods"
    __table_args__ = (
        sa.UniqueConstraint(
            "subscription_id",
            "period_start",
            name="uq_subscription_periods_subscription_id_period_start",
        ),
        sa.CheckConstraint("period_end > period_start", name="period_order"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("subscriptions.id", ondelete="CASCADE"),
        nullable=False,
    )
    period_start: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    payment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("payments.id", ondelete="RESTRICT"),
        nullable=True,
        unique=True,
    )
    terms_version: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    """The ``plan_tier_terms`` version this period was billed on; NULL means the subscription's
    ``terms_version`` at the time (rows written before terms existed)."""


class PlanTierTerms(Base):
    """One immutable version of a tier's price and entitlements (UD13-A).

    A price or entitlement change inserts the next ``terms_version``; ``plan_tiers`` keeps the
    current number, and a subscription keeps the version it is billed on until its renewal after
    the notice. Append-only: a trigger rejects UPDATE and DELETE (the function is the audit log's,
    ``admin_audit_log_append_only``), installed by migration ``0057_admin_audit_log`` and by the
    ``after_create`` listeners below on ``create_all`` databases.

    Every valid tier has version 1 from its first insert: ``trg_plan_tiers_seed_terms`` writes it
    from the new tier's own columns (and when a tier without terms is fixed by an UPDATE), so a
    valid tier can never exist without the history row the subscription foreign keys point at.
    """

    __tablename__ = "plan_tier_terms"
    __table_args__ = (
        sa.UniqueConstraint("plan_tier_id", "terms_version"),
        sa.CheckConstraint("terms_version >= 1", name="terms_version_min"),
        sa.CheckConstraint(
            "price_minor >= 0 AND extra_seat_price_minor >= 0 AND allowance_units >= 0 "
            "AND included_seats >= 0 AND seat_allowance_units >= 0",
            name="amounts_nonneg",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
    )
    plan_tier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("plan_tiers.id", ondelete="RESTRICT"), nullable=False
    )
    terms_version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    price_minor: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    extra_seat_price_minor: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    allowance_units: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    included_seats: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    seat_allowance_units: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    """The admin who wrote this version; NULL on a version the seed trigger wrote (the audit log
    records who created the tier). ``RESTRICT``: ``SET NULL`` would be an UPDATE the append-only
    trigger refuses."""


PLAN_TIER_TERMS_TRIGGER_SQL = """
CREATE TRIGGER trg_plan_tier_terms_append_only
BEFORE UPDATE OR DELETE ON plan_tier_terms
FOR EACH ROW EXECUTE FUNCTION admin_audit_log_append_only()
"""

SEED_TERMS_FUNCTION_SQL = """
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

SEED_TERMS_TRIGGER_SQL = """
CREATE TRIGGER trg_plan_tiers_seed_terms
AFTER INSERT OR UPDATE OF price_minor, extra_seat_price_minor, allowance_units,
    included_seats, seat_allowance_units ON plan_tiers
FOR EACH ROW EXECUTE FUNCTION plan_tiers_seed_terms()
"""


def _install_terms_append_only(target: sa.Table, connection: sa.Connection, **_kw: object) -> None:
    """Install the append-only trigger after ``create_all`` creates ``plan_tier_terms``.

    The shared function is created here too, idempotently, because table creation order is not
    fixed.
    """
    if connection.dialect.name == "postgresql":
        connection.execute(sa.text(APPEND_ONLY_FUNCTION_SQL))
        connection.execute(sa.text(PLAN_TIER_TERMS_TRIGGER_SQL))


def _install_terms_seed(target: sa.Table, connection: sa.Connection, **_kw: object) -> None:
    """After ``create_all`` creates ``plan_tiers``: seed version 1 of every new tier's terms."""
    if connection.dialect.name == "postgresql":
        connection.execute(sa.text(SEED_TERMS_FUNCTION_SQL))
        connection.execute(sa.text(SEED_TERMS_TRIGGER_SQL))


event.listen(PlanTierTerms.__table__, "after_create", _install_terms_append_only)
event.listen(PlanTier.__table__, "after_create", _install_terms_seed)


class CreditPack(TimestampMixin, Base):
    """A prepaid credit pack (spec §4.1).

    Both CHECKs allow zero (index R11): Phase 04 stores the free signup allowances
    as inactive ``signup_student`` / ``signup_teacher`` rows with ``price_minor = 0``,
    and ``units = 0`` disables one. Checkout refuses any pack that is inactive or
    has a zero price or zero units.
    """

    __tablename__ = "credit_packs"
    __table_args__ = (
        sa.CheckConstraint("units >= 0", name="units_nonneg"),
        sa.CheckConstraint("price_minor >= 0", name="price_nonneg"),
        sa.CheckConstraint("version >= 1", name="version_min"),
        sa.CheckConstraint(
            "signup_validity_days IS NULL "
            "OR (starts_with(code, 'signup_') AND signup_validity_days BETWEEN 1 AND 3650)",
            name="signup_validity",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
    )
    code: Mapped[str] = mapped_column(sa.String, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(sa.String, nullable=False)
    units: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    price_minor: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(
        sa.String(3), nullable=False, server_default=sa.literal("EGP")
    )
    is_active: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.true())
    version: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default=sa.text("1"))
    """Optimistic-concurrency counter: an admin edit sends the version it read."""
    signup_validity_days: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    """How long the grant of a ``signup_*`` pack lasts; NULL means it never expires. Only a
    signup pack may set it (``ck_credit_packs_signup_validity``)."""


class Payment(TimestampMixin, Base):
    """One payment attempt; when ``paid`` it is the payer's receipt (spec §4.2).

    ``special_reference`` is ``str(id)``, sent to Paymob and returned as
    ``order.merchant_order_id``. ``grant_units`` snapshots what a credit purchase
    buys at checkout. ``next_reconcile_at`` / ``reconcile_attempts`` drive the
    inquiry backoff for a missed callback (spec §5.10).
    """

    __tablename__ = "payments"
    __table_args__ = (
        sa.CheckConstraint("amount_minor > 0", name="amount_positive"),
        sa.CheckConstraint(
            "seat_quantity IS NULL OR seat_quantity > 0", name="seat_quantity_positive"
        ),
        sa.CheckConstraint("grant_units IS NULL OR grant_units > 0", name="grant_units_positive"),
        sa.CheckConstraint(_DEDUPE_KEY_PURPOSE_CHECK, name="dedupe_key_purpose"),
        sa.CheckConstraint(
            "purpose <> 'credit_pack' OR credit_pack_id IS NOT NULL", name="credit_pack_link"
        ),
        sa.Index("ix_payments_status_next_reconcile_at", "status", "next_reconcile_at"),
        sa.Index("ix_payments_payer_user_id_paid_at", "payer_user_id", "paid_at"),
        # The auto top-up hook's in-flight probe runs on every settle. Compares the enum
        # labels directly, as ``_LIVE_PAID_PREDICATE`` does: ``::text`` is not IMMUTABLE.
        sa.Index(
            "ix_payments_auto_topup_in_flight",
            "beneficiary_user_id",
            postgresql_where=sa.text(_AUTO_TOPUP_IN_FLIGHT_PREDICATE),
        ),
        # Per-subscription lookups: ``charge_in_flight``, the void rules, the seat-renewal checks.
        sa.Index(
            "ix_payments_subscription_purpose",
            "subscription_id",
            "purpose",
            postgresql_where=sa.text("subscription_id IS NOT NULL"),
        ),
        # Serves ``dedupe_key LIKE 'prefix%'`` (the queue scans); the unique btree cannot under an
        # ICU collation. Same reason as ``ix_paymob_events_dedupe_key_prefix``.
        sa.Index(
            "ix_payments_dedupe_key_prefix",
            "dedupe_key",
            postgresql_ops={"dedupe_key": "text_pattern_ops"},
            postgresql_where=sa.text("dedupe_key IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
    )
    payer_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
    )
    beneficiary_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
    )
    purpose: Mapped[PaymentPurpose] = mapped_column(
        sa.Enum(PaymentPurpose, name="paymentpurpose"), nullable=False
    )
    plan_tier_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("plan_tiers.id"), nullable=True
    )
    credit_pack_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("credit_packs.id"), nullable=True
    )
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("subscriptions.id"), nullable=True
    )
    seat_quantity: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    grant_units: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    amount_minor: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(
        sa.String(3), nullable=False, server_default=sa.literal("EGP")
    )
    status: Mapped[PaymentStatus] = mapped_column(
        sa.Enum(PaymentStatus, name="paymentstatus"),
        nullable=False,
        server_default=sa.text("'created'::paymentstatus"),
    )
    special_reference: Mapped[str] = mapped_column(sa.String, nullable=False, unique=True)
    paymob_intention_id: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    paymob_order_id: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True, unique=True)
    paymob_txn_id: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True, unique=True)
    method: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    last_callback: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    reconcile_attempts: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.literal(0)
    )
    next_reconcile_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    sent_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    """When a queued charge was claimed and sent to Paymob; ``NULL`` until then and for every
    checkout payment. A queued row can wait before it is charged, so reconcile's give-up and stuck
    windows run from ``coalesce(sent_at, created_at)``: counted from ``created_at`` a row older than
    a day would be failed right after a real charge (which a seat or top-up sweep reads as "not
    charged" and charges again)."""
    dedupe_key: Mapped[str | None] = mapped_column(sa.String(200), nullable=True, unique=True)
    """Queue identity for background charges (``auto_topup:{setting}:{crossing}``,
    ``extra_seat_renewal:{period}:{attempt}``). NULL for user-initiated payments."""
    callback_received_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    """When Paymob last called us about this payment (admin "missing callback" queue)."""


class PaymobEvent(TimestampMixin, Base):
    """Every verified Paymob callback (and inquiry result), stored once (spec §4.2)."""

    __tablename__ = "paymob_events"
    __table_args__ = (
        # Backs the prefix LIKE that finds a transaction's recorded final state
        # (``BillingService._has_recorded_final_state``); a plain btree cannot serve
        # LIKE under an ICU collation.
        sa.Index(
            "ix_paymob_events_dedupe_key_prefix",
            "dedupe_key",
            postgresql_ops={"dedupe_key": "text_pattern_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
    )
    kind: Mapped[PaymobEventKind] = mapped_column(
        sa.Enum(PaymobEventKind, name="paymobeventkind"), nullable=False
    )
    dedupe_key: Mapped[str] = mapped_column(sa.String, nullable=False, unique=True)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)


class SavedCard(TimestampMixin, Base):
    """A card token for merchant-initiated charges; ``token`` is AES-GCM ciphertext (§7)."""

    __tablename__ = "saved_cards"
    __table_args__ = (sa.UniqueConstraint("user_id", "token_fingerprint"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token: Mapped[str] = mapped_column(sa.Text, nullable=False)
    token_fingerprint: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    masked_pan: Mapped[str] = mapped_column(sa.String, nullable=False)
    brand: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    paymob_token_id: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.true())


class AutoTopupSettings(TimestampMixin, Base):
    """Auto top-up for one balance (spec §4.6, §5.5).

    The payer owns the row and the card. The beneficiary owns the balance. ``armed`` and
    ``crossing_seq`` implement the dedupe key ``(user, threshold crossing)``: a crossing
    below the threshold enqueues at most one top-up and disarms; seeing the balance at or
    above the threshold again, or the top-up resolving, re-arms and bumps ``crossing_seq``.

    There is deliberately no CHECK that an enabled row has a card: ``saved_card_id`` is
    ``ON DELETE SET NULL`` (a user deletion cascades ``saved_cards``), and such a CHECK would
    make every card delete fail while auto top-up is on. The service and the job enforce it.
    """

    __tablename__ = "auto_topup_settings"
    __table_args__ = (
        sa.UniqueConstraint("beneficiary_user_id"),
        sa.CheckConstraint("threshold_units > 0", name="threshold_positive"),
        sa.CheckConstraint("monthly_cap_minor >= 0", name="cap_nonnegative"),
        sa.Index("ix_auto_topup_settings_payer_user_id", "payer_user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
    )
    beneficiary_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    payer_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    enabled: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.false())
    threshold_units: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    credit_pack_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("credit_packs.id"), nullable=False
    )
    saved_card_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("saved_cards.id", ondelete="SET NULL"), nullable=True
    )
    monthly_cap_minor: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    armed: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.true())
    crossing_seq: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.literal(0)
    )
    last_payment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("payments.id", ondelete="SET NULL"), nullable=True
    )
    disabled_reason: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    consented_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    """When the payer consented to unattended charges (set when ``enabled`` turns true): the
    evidence in a chargeback dispute over a MOTO charge made while the payer was away."""


__all__ = [
    "LIVE_SUBSCRIPTION_STATUSES",
    "PLAN_LIVE_STATUSES",
    "AutoTopupSettings",
    "CreditPack",
    "Payment",
    "PaymentPurpose",
    "PaymentStatus",
    "PaymobEvent",
    "PaymobEventKind",
    "PlanAudience",
    "PlanTier",
    "PlanTierTerms",
    "SavedCard",
    "Subscription",
    "SubscriptionPeriod",
]
