"""Auto top-up settings and merchant-charge columns (Paymob billing phase 06).

Revision ID: 0056_auto_topup
Revises: 0055_subscription_periods
Create Date: 2026-11-13 00:00:00.000000

Paymob billing spec §4.6, §5.4, §5.5 (Phase 06). Additive:

* ``auto_topup_settings``: one row per beneficiary balance, owned by the payer. Unique on
  ``beneficiary_user_id``. ``saved_card_id`` is ``ON DELETE SET NULL`` and there is deliberately
  no CHECK that an enabled row has a card: a user deletion cascades ``saved_cards``, and such a
  CHECK would make every card delete fail while auto top-up is on. The service and the job
  enforce "enabled needs a card". ``credit_pack_id`` is ``RESTRICT`` (a pack in use is never
  deleted).
* ``payments.dedupe_key``: unique queue identity for background charges (NULL for user-initiated
  payments, and NULLs are distinct).
* ``ix_payments_auto_topup_in_flight`` (partial, ``purpose = 'auto_topup' AND status IN
  ('created', 'pending')``): the post-settle hook probes for an in-flight top-up on every settle.
  The predicate compares the enum labels directly: ``::text`` is not IMMUTABLE, and Postgres
  rejects it in an index predicate.
* ``subscriptions.extra_seat_grace_until`` / ``extra_seat_grace_payment_id``: fallback seat grace
  (spec §5.4); the payment link is ``ON DELETE SET NULL``.

* ``ix_payments_subscription_purpose`` (partial, ``subscription_id IS NOT NULL``): the
  per-subscription payment lookups (``charge_in_flight``, the void rules, the seat-renewal
  checks).
* ``ix_payments_dedupe_key_prefix`` (partial, ``dedupe_key IS NOT NULL``, ``text_pattern_ops``):
  the queue scans ``dedupe_key LIKE 'prefix%'``, which the unique btree cannot serve under an ICU
  collation (``ix_paymob_events_dedupe_key_prefix``, 0053, is the precedent).
* ``ck_payments_dedupe_key_purpose``: a ``dedupe_key`` is NULL, or ``auto_topup:`` on an
  ``auto_topup`` payment, or ``extra_seat_renewal:`` on an ``extra_seats`` payment. A renewal
  seat charge and a seat purchase are both ``extra_seats`` and only the prefix tells the paid
  handler to clear a grace instead of granting seats, so a wrong pairing must be an error, not a
  double grant. ``starts_with`` keeps the ``_`` in the prefix literal.
* ``payments.sent_at`` (nullable): when a queued charge was claimed and sent to Paymob. Reconcile
  gives a payment up 24 hours after its clock starts and stops polling it after 7 days, and for
  a checkout that clock is ``created_at``. A queued row can wait before it is charged (charges
  paused, a backlog), so counted from ``created_at`` it would be failed straight after a real
  charge, and a seat or top-up sweep would read that as "not charged" and charge again.
  Reconcile measures from ``coalesce(sent_at, created_at)``; the charge claim stamps ``sent_at``.
  NULL for every checkout payment. No backfill: no queued charge exists before this revision.
* ``auto_topup_settings.consented_at`` (nullable): when the payer consented to unattended
  charges, the evidence in a chargeback dispute over a MOTO charge made while they were away.
  The service sets it when ``enabled`` turns true.

No ``ALTER TYPE`` and no new enum value (the ``billing`` notification type is 0055's).

**Lock behaviour**, as 0037 and 0038: both directions take ACCESS EXCLUSIVE on ``payments`` and
``subscriptions`` while the old revision may be serving traffic. ``SET lock_timeout`` first makes a
blocked statement fail fast and retriably instead of queueing every ``payments`` query behind it.
``env.py`` runs one ``alembic upgrade``/``downgrade`` in ONE transaction, so both directions
``RESET lock_timeout`` before returning, or the timeout would leak into the next migration of the
run. The order (``payments``, then ``subscriptions``) is the callback's lock order, so the
migration cannot deadlock against a callback.

``downgrade`` refuses while money state exists, as 0054 and 0055 do: any ``auto_topup_settings``
row, any ``payments.dedupe_key`` that is not NULL, or any ``subscriptions`` row with a grace
column set. Dropping them would lose a payer's top-up consent, the identity that keeps a queued
charge from running twice, or the record of a seat grace, silently. ``sent_at`` needs no probe of its own: only a charge with a ``dedupe_key`` sets it. Otherwise it
drops what the upgrade added, in reverse order, and nothing else.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
# Kept to <=32 chars: alembic_version.version_num is varchar(32).
revision: str = "0056_auto_topup"
down_revision: str | Sequence[str] | None = "0055_subscription_periods"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

IN_FLIGHT_INDEX = "ix_payments_auto_topup_in_flight"
#: The ORM declares the same predicate (``_AUTO_TOPUP_IN_FLIGHT_PREDICATE``); the parity test
#: compares the two catalogue definitions.
IN_FLIGHT_PREDICATE = "purpose = 'auto_topup' AND status IN ('created', 'pending')"
GRACE_FK = "fk_subscriptions_extra_seat_grace_payment_id_payments"
SUBSCRIPTION_PURPOSE_INDEX = "ix_payments_subscription_purpose"
DEDUPE_PREFIX_INDEX = "ix_payments_dedupe_key_prefix"
DEDUPE_PURPOSE_CHECK = "ck_payments_dedupe_key_purpose"
#: The ORM declares the same predicate (``_DEDUPE_KEY_PURPOSE_CHECK``).
DEDUPE_PURPOSE_PREDICATE = (
    "dedupe_key IS NULL "
    "OR (purpose = 'auto_topup' AND starts_with(dedupe_key, 'auto_topup:')) "
    "OR (purpose = 'extra_seats' AND starts_with(dedupe_key, 'extra_seat_renewal:'))"
)


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("SET lock_timeout = '5s'")
    op.create_table(
        "auto_topup_settings",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("beneficiary_user_id", sa.UUID(), nullable=False),
        sa.Column("payer_user_id", sa.UUID(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("threshold_units", sa.BigInteger(), nullable=False),
        sa.Column("credit_pack_id", sa.UUID(), nullable=False),
        sa.Column("saved_card_id", sa.UUID(), nullable=True),
        sa.Column("monthly_cap_minor", sa.BigInteger(), nullable=False),
        sa.Column("armed", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("crossing_seq", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_payment_id", sa.UUID(), nullable=True),
        sa.Column("disabled_reason", sa.String(), nullable=True),
        sa.Column("consented_at", sa.DateTime(timezone=True), nullable=True),
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
            "threshold_units > 0", name=op.f("ck_auto_topup_settings_threshold_positive")
        ),
        sa.CheckConstraint(
            "monthly_cap_minor >= 0", name=op.f("ck_auto_topup_settings_cap_nonnegative")
        ),
        sa.ForeignKeyConstraint(
            ["beneficiary_user_id"],
            ["users.id"],
            name=op.f("fk_auto_topup_settings_beneficiary_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["payer_user_id"],
            ["users.id"],
            name=op.f("fk_auto_topup_settings_payer_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["credit_pack_id"],
            ["credit_packs.id"],
            name=op.f("fk_auto_topup_settings_credit_pack_id_credit_packs"),
        ),
        sa.ForeignKeyConstraint(
            ["saved_card_id"],
            ["saved_cards.id"],
            name=op.f("fk_auto_topup_settings_saved_card_id_saved_cards"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["last_payment_id"],
            ["payments.id"],
            name=op.f("fk_auto_topup_settings_last_payment_id_payments"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auto_topup_settings")),
        sa.UniqueConstraint(
            "beneficiary_user_id", name=op.f("uq_auto_topup_settings_beneficiary_user_id")
        ),
    )
    op.create_index(
        "ix_auto_topup_settings_payer_user_id", "auto_topup_settings", ["payer_user_id"]
    )

    op.add_column("payments", sa.Column("dedupe_key", sa.String(length=200), nullable=True))
    op.add_column("payments", sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True))
    op.create_unique_constraint(op.f("uq_payments_dedupe_key"), "payments", ["dedupe_key"])
    op.create_index(
        IN_FLIGHT_INDEX,
        "payments",
        ["beneficiary_user_id"],
        postgresql_where=sa.text(IN_FLIGHT_PREDICATE),
    )
    op.create_index(
        SUBSCRIPTION_PURPOSE_INDEX,
        "payments",
        ["subscription_id", "purpose"],
        postgresql_where=sa.text("subscription_id IS NOT NULL"),
    )
    op.create_index(
        DEDUPE_PREFIX_INDEX,
        "payments",
        ["dedupe_key"],
        postgresql_ops={"dedupe_key": "text_pattern_ops"},
        postgresql_where=sa.text("dedupe_key IS NOT NULL"),
    )
    op.create_check_constraint(op.f(DEDUPE_PURPOSE_CHECK), "payments", DEDUPE_PURPOSE_PREDICATE)

    op.add_column(
        "subscriptions",
        sa.Column("extra_seat_grace_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "subscriptions", sa.Column("extra_seat_grace_payment_id", sa.UUID(), nullable=True)
    )
    op.create_foreign_key(
        op.f(GRACE_FK),
        "subscriptions",
        "payments",
        ["extra_seat_grace_payment_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.execute("RESET lock_timeout")


def _refuse_if_any(probe: str, message: str) -> None:
    """Raise ``RuntimeError(message)`` when the ``SELECT 1 ... LIMIT 1`` probe finds a row."""
    if op.get_bind().execute(sa.text(probe)).first() is not None:
        raise RuntimeError(message)


def downgrade() -> None:
    """Downgrade schema.

    Refuses while an auto top-up setting, a payment dedupe key or a seat grace exists (see the
    module docstring).
    """
    op.execute("SET lock_timeout = '5s'")
    _refuse_if_any(
        "SELECT 1 FROM auto_topup_settings LIMIT 1",
        "Cannot downgrade 0056_auto_topup: auto_topup_settings still has rows. A row is a "
        "payer's standing consent to charge their card, and dropping the table would lose it "
        "silently. Downgrading past 0056 is not possible once any setting exists.",
    )
    _refuse_if_any(
        "SELECT 1 FROM payments WHERE dedupe_key IS NOT NULL LIMIT 1",
        "Cannot downgrade 0056_auto_topup: payments still has rows with a dedupe_key. The key "
        "is what keeps a queued background charge from running twice, and dropping the column "
        "would lose it silently. Downgrading past 0056 is not possible once any exists.",
    )
    _refuse_if_any(
        "SELECT 1 FROM subscriptions WHERE extra_seat_grace_until IS NOT NULL "
        "OR extra_seat_grace_payment_id IS NOT NULL LIMIT 1",
        "Cannot downgrade 0056_auto_topup: subscriptions still has an extra_seat_grace_until "
        "or extra_seat_grace_payment_id set. Dropping the columns would lose a seat grace "
        "episode silently. Downgrading past 0056 is not possible once any exists.",
    )
    op.drop_constraint(op.f(GRACE_FK), "subscriptions", type_="foreignkey")
    op.drop_column("subscriptions", "extra_seat_grace_payment_id")
    op.drop_column("subscriptions", "extra_seat_grace_until")
    op.drop_index(IN_FLIGHT_INDEX, table_name="payments")
    op.drop_constraint(op.f(DEDUPE_PURPOSE_CHECK), "payments", type_="check")
    op.drop_index(DEDUPE_PREFIX_INDEX, table_name="payments")
    op.drop_index(SUBSCRIPTION_PURPOSE_INDEX, table_name="payments")
    op.drop_constraint(op.f("uq_payments_dedupe_key"), "payments", type_="unique")
    op.drop_column("payments", "sent_at")
    op.drop_column("payments", "dedupe_key")
    op.drop_index("ix_auto_topup_settings_payer_user_id", table_name="auto_topup_settings")
    op.drop_table("auto_topup_settings")
    op.execute("RESET lock_timeout")
