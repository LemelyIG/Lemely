"""Migration 0053_billing_payments: payments, events, saved cards, packs; catalogue columns.

Expected object names come from the ORM (``lemely/db/models/billing.py``), an
independent declaration of the same schema. The downgrade removes everything this
migration added. Postgres cannot drop an enum label, so rows holding the two new
``subscriptionstatus`` labels are moved to ``expired`` and the type is rebuilt with its
five original labels.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.exc import IntegrityError

from lemely.db.base import Base
from lemely.db.models import import_all_models
from tests.test_migration_tutoring_enums import (
    column_names,
    current_revision,
    enum_labels,
    head_revision,
    object_names,
    public_tables,
    type_exists,
    upgrade_head,
)
from tests.test_migration_usage_ledger import schema_dump
from tests.usage_db import usage_database

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session, sessionmaker

import_all_models()

REVISION = "0053_billing_payments"
DOWN_REVISION = "0052_usage_ledger"
NEW_TABLES = ("credit_packs", "payments", "paymob_events", "saved_cards")
NEW_TYPES = ("planaudience", "paymentpurpose", "paymentstatus", "paymobeventkind")
PLAN_TIER_COLUMNS = {
    "audience",
    "allowance_units",
    "paymob_plan_id",
    "is_active",
    "included_seats",
    "seat_allowance_units",
    "extra_seat_price_minor",
}
SUBSCRIPTION_COLUMNS = {
    "payer_user_id",
    "cancel_at_period_end",
    "pending_plan_tier_id",
    "current_period_start",
    "grace_until",
    "extra_seats",
    "pending_extra_seats",
    "paymob_subscription_id",
    "version",
}
PLAN_TIER_OBJECTS = {
    "uq_plan_tiers_paymob_plan_id",
    "ck_plan_tiers_allowance_nonneg",
    "ck_plan_tiers_seats_nonneg",
    "ck_plan_tiers_seat_allowance_nonneg",
    "ck_plan_tiers_extra_seat_price_nonneg",
}
SUBSCRIPTION_OBJECTS = {
    "fk_subscriptions_payer_user_id_users",
    "fk_subscriptions_pending_plan_tier_id_plan_tiers",
    "uq_subscriptions_paymob_subscription_id",
    "ck_subscriptions_extra_seats_nonneg",
    "ck_subscriptions_pending_extra_seats_nonneg",
    "uq_subscriptions_one_live_per_user",
}
GRANT_FK = "fk_usage_grants_payment_id_payments"
PREVIOUS_STATUS_LABELS = ["inactive", "active", "cancelled", "expired", "rejected"]


#: Every table 0053 creates or alters, for the parity check.
PARITY_TABLES = (*NEW_TABLES, "plan_tiers", "subscriptions", "usage_grants")
PARITY_ENUMS = (*NEW_TYPES, "subscriptionstatus")


def _orm_names(table: str) -> set[str]:
    t = Base.metadata.tables[table]
    return {str(c.name) for c in t.constraints} | {str(i.name) for i in t.indexes}


def _seed_user(session: Session) -> uuid.UUID:
    uid = uuid.uuid4()
    session.execute(
        sa.text("INSERT INTO users (id, email, role) VALUES (:u, :e, 'student')"),
        {"u": uid, "e": f"{uid}@example.com"},
    )
    return uid


def _seed_tier(session: Session) -> uuid.UUID:
    return session.execute(
        sa.text("INSERT INTO plan_tiers (code, name) VALUES (:c, 'Tier') RETURNING id"),
        {"c": f"tier_{uuid.uuid4().hex[:8]}"},
    ).scalar_one()


def test_orm_declares_the_named_objects_of_the_new_tables() -> None:
    assert _orm_names("credit_packs") == {
        "pk_credit_packs",
        "uq_credit_packs_code",
        "ck_credit_packs_units_nonneg",
        "ck_credit_packs_price_nonneg",
    }
    assert _orm_names("saved_cards") == {
        "pk_saved_cards",
        "fk_saved_cards_user_id_users",
        "uq_saved_cards_user_id",
    }
    assert _orm_names("paymob_events") == {"pk_paymob_events", "uq_paymob_events_dedupe_key"}
    assert {
        "pk_payments",
        "fk_payments_payer_user_id_users",
        "fk_payments_beneficiary_user_id_users",
        "fk_payments_plan_tier_id_plan_tiers",
        "fk_payments_credit_pack_id_credit_packs",
        "fk_payments_subscription_id_subscriptions",
        "uq_payments_special_reference",
        "uq_payments_paymob_order_id",
        "uq_payments_paymob_txn_id",
        "ck_payments_amount_positive",
        "ck_payments_seat_quantity_positive",
        "ck_payments_grant_units_positive",
        "ck_payments_credit_pack_link",
        "ix_payments_status_next_reconcile_at",
        "ix_payments_payer_user_id_paid_at",
    } == _orm_names("payments")
    assert _orm_names("plan_tiers") >= PLAN_TIER_OBJECTS
    assert _orm_names("subscriptions") >= SUBSCRIPTION_OBJECTS
    assert GRANT_FK in _orm_names("usage_grants")


def test_revision_chains_from_0052_and_is_in_the_head_lineage() -> None:
    """Index R10: assert lineage, never head, so later migrations do not break this."""
    script_dir = ScriptDirectory.from_config(Config("alembic.ini"))
    revision = script_dir.get_revision(REVISION)
    assert revision is not None
    assert revision.down_revision == DOWN_REVISION
    assert len(REVISION) <= 32
    lineage = {r.revision for r in script_dir.iterate_revisions(head_revision(), "base")}
    assert REVISION in lineage


def test_new_tables_match_the_orm(migrated_sessionmaker: sessionmaker[Session]) -> None:
    with migrated_sessionmaker() as session:
        for table in NEW_TABLES:
            assert object_names(session, [table]) == _orm_names(table), table


def test_migrated_schema_equals_the_create_all_schema(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """Parity: 0053 builds what the models declare, definition by definition.

    Names alone (above) miss a changed CHECK expression, column type, default or
    index predicate; this compares the full catalogue definitions of every table 0053
    creates or alters against a database built by ``create_all``.
    """
    with migrated_sessionmaker() as session:
        migrated = schema_dump(session, PARITY_TABLES, enums=PARITY_ENUMS)
    with usage_database() as orm_sessionmaker, orm_sessionmaker() as session:
        orm = schema_dump(session, PARITY_TABLES, enums=PARITY_ENUMS)
    # Non-vacuous: every section the dump can fill found something to compare.
    for section in ("columns", "constraints", "indexes", "enums"):
        assert migrated[section], section
    for section, rows in migrated.items():
        assert rows == orm[section], section


def test_extended_tables_gain_columns_and_constraints(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    with migrated_sessionmaker() as session:
        assert column_names(session, "plan_tiers") >= PLAN_TIER_COLUMNS
        assert column_names(session, "subscriptions") >= SUBSCRIPTION_COLUMNS
        assert object_names(session, ["plan_tiers"]) >= PLAN_TIER_OBJECTS
        assert object_names(session, ["subscriptions"]) >= SUBSCRIPTION_OBJECTS
        assert GRANT_FK in object_names(session, ["usage_grants"])


def test_subscription_status_gains_the_two_lifecycle_labels(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    with migrated_sessionmaker() as session:
        labels = enum_labels(session, "subscriptionstatus")
    assert {"pending_first_payment", "past_due"} <= set(labels)
    assert {"inactive", "active", "cancelled", "expired", "rejected"} <= set(labels)


def test_existing_tiers_default_to_student_and_active(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    with migrated_sessionmaker.begin() as session:
        tier = _seed_tier(session)
        row = session.execute(
            sa.text(
                "SELECT audience::text, allowance_units, is_active, included_seats "
                "FROM plan_tiers WHERE id = :t"
            ),
            {"t": tier},
        ).one()
    assert tuple(row) == ("student", 0, True, 0)


def test_one_live_paid_subscription_per_beneficiary(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    insert = sa.text(
        "INSERT INTO subscriptions (user_id, plan_tier_id, status, payer_user_id) "
        "VALUES (:u, :t, CAST(:s AS subscriptionstatus), :p)"
    )
    with migrated_sessionmaker.begin() as session:
        user, tier = _seed_user(session), _seed_tier(session)
        session.execute(insert, {"u": user, "t": tier, "s": "active", "p": user})
        # Not live: a cancelled paid row and manual (payer-less) rows never collide.
        session.execute(insert, {"u": user, "t": tier, "s": "cancelled", "p": user})
        session.execute(insert, {"u": user, "t": tier, "s": "active", "p": None})
        session.execute(insert, {"u": user, "t": tier, "s": "active", "p": None})
    with pytest.raises(IntegrityError), migrated_sessionmaker.begin() as session:
        session.execute(insert, {"u": user, "t": tier, "s": "past_due", "p": user})


def test_a_credit_pack_payment_must_name_its_pack(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    with pytest.raises(IntegrityError), migrated_sessionmaker.begin() as session:
        user = _seed_user(session)
        ref = str(uuid.uuid4())
        session.execute(
            sa.text(
                "INSERT INTO payments (payer_user_id, beneficiary_user_id, purpose, "
                "amount_minor, special_reference) VALUES (:u, :u, 'credit_pack', 100, :r)"
            ),
            {"u": user, "r": ref},
        )


def test_credit_packs_allow_zero_price_and_units_but_not_negative(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """Index R11: Phase 04's inactive signup rows have price 0; units 0 disables one."""
    insert = sa.text(
        "INSERT INTO credit_packs (code, name, units, price_minor, is_active) "
        "VALUES (:c, 'Signup', :u, :p, false)"
    )
    with migrated_sessionmaker.begin() as session:
        session.execute(insert, {"c": "signup_student", "u": 200, "p": 0})
        session.execute(insert, {"c": "signup_teacher", "u": 0, "p": 0})
    for units, price in ((-1, 0), (1, -1)):
        with pytest.raises(IntegrityError), migrated_sessionmaker.begin() as session:
            session.execute(insert, {"c": f"bad_{uuid.uuid4().hex[:6]}", "u": units, "p": price})


def test_upgrade_downgrade_upgrade_round_trip(
    migrated_sessionmaker_with_downgrade: tuple[sessionmaker[Session], Callable[[str], None]],
) -> None:
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    with sm.begin() as session:
        user, tier = _seed_user(session), _seed_tier(session)
        sub = session.execute(
            sa.text(
                "INSERT INTO subscriptions (user_id, plan_tier_id, status, payer_user_id) "
                "VALUES (:u, :t, 'past_due', :u) RETURNING id"
            ),
            {"u": user, "t": tier},
        ).scalar_one()

    downgrade_to(DOWN_REVISION)

    with sm() as session:
        assert current_revision(session) == DOWN_REVISION
        assert not set(NEW_TABLES) & public_tables(session)
        assert not PLAN_TIER_COLUMNS & column_names(session, "plan_tiers")
        assert not SUBSCRIPTION_COLUMNS & column_names(session, "subscriptions")
        assert GRANT_FK not in object_names(session, ["usage_grants"])
        assert not any(type_exists(session, name) for name in NEW_TYPES)
        status = session.execute(
            sa.text("SELECT status::text FROM subscriptions WHERE id = :s"), {"s": sub}
        ).scalar_one()
        assert status == "expired"
        assert enum_labels(session, "subscriptionstatus") == PREVIOUS_STATUS_LABELS
        assert not type_exists(session, "subscriptionstatus_old")
        default = session.execute(
            sa.text(
                "SELECT column_default FROM information_schema.columns "
                "WHERE table_name = 'subscriptions' AND column_name = 'status'"
            )
        ).scalar_one()
        assert default == "'inactive'::subscriptionstatus"

    upgrade_head()

    with sm() as session:
        assert current_revision(session) == head_revision()
        for table in NEW_TABLES:
            assert object_names(session, [table]) == _orm_names(table)
        assert object_names(session, ["subscriptions"]) >= SUBSCRIPTION_OBJECTS
