"""Migration 0056_auto_topup: auto top-up settings and the merchant-charge columns (Phase 06).

Expected object names come from the ORM (``lemely/db/models/billing.py``), so the migration is
compared with an independent declaration. Per index R10 this file asserts only that 0056 is in
the history, chains from 0055 and round-trips; it never asserts that 0056 is the head.

The downgrade refuses while money state exists (0054/0055 precedent), so each probe has its own
test that seeds exactly the row the probe looks for.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.exc import IntegrityError

from lemely.db.base import Base
from lemely.db.models import import_all_models
from lemely.db.models.billing import (
    AutoTopupSettings,
    Payment,
    PaymentPurpose,
    PaymentStatus,
    SavedCard,
    Subscription,
)
from lemely.db.models.enums import Role
from tests.merchant_charge_fixtures import (
    link_parent,
    seed_auto_topup,
    seed_pack,
    seed_payment_row,
    seed_saved_card,
    seed_user,
    student_with_plan,
    teacher_with_plan,
)
from tests.team_db import team_database
from tests.test_migration_tutoring_enums import (
    column_names,
    current_revision,
    object_names,
    public_tables,
    upgrade_head,
)
from tests.test_migration_usage_ledger import schema_dump

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session, sessionmaker

import_all_models()

REVISION = "0056_auto_topup"
DOWN_REVISION = "0055_subscription_periods"
TABLE = "auto_topup_settings"
IN_FLIGHT_INDEX = "ix_payments_auto_topup_in_flight"
DEDUPE_UNIQUE = "uq_payments_dedupe_key"
GRACE_FK = "fk_subscriptions_extra_seat_grace_payment_id_payments"
SUBSCRIPTION_COLUMNS = {"extra_seat_grace_until", "extra_seat_grace_payment_id"}
#: Every table 0056 creates or alters, for the parity check.
PARITY_TABLES = (TABLE, "payments", "subscriptions")


def _orm_names() -> set[str]:
    table = Base.metadata.tables[TABLE]
    names = {str(constraint.name) for constraint in table.constraints}
    return names | {str(index.name) for index in table.indexes}


def test_orm_declares_the_named_objects() -> None:
    """The table's ten objects. ``enabled_needs_card`` is deliberately absent (DV-11)."""
    assert _orm_names() == {
        "pk_auto_topup_settings",
        "uq_auto_topup_settings_beneficiary_user_id",
        "fk_auto_topup_settings_beneficiary_user_id_users",
        "fk_auto_topup_settings_payer_user_id_users",
        "fk_auto_topup_settings_credit_pack_id_credit_packs",
        "fk_auto_topup_settings_saved_card_id_saved_cards",
        "fk_auto_topup_settings_last_payment_id_payments",
        "ck_auto_topup_settings_threshold_positive",
        "ck_auto_topup_settings_cap_nonnegative",
        "ix_auto_topup_settings_payer_user_id",
    }


def test_orm_declares_the_payment_and_subscription_objects() -> None:
    payments = Base.metadata.tables["payments"]
    payment_names = {str(c.name) for c in payments.constraints} | {
        str(i.name) for i in payments.indexes
    }
    assert {DEDUPE_UNIQUE, IN_FLIGHT_INDEX} <= payment_names
    subscriptions = Base.metadata.tables["subscriptions"]
    assert GRACE_FK in {str(c.name) for c in subscriptions.constraints}
    assert {c.name for c in subscriptions.columns} >= SUBSCRIPTION_COLUMNS


def test_revision_chains_from_0055_and_is_in_the_history() -> None:
    """Index R10: in the history and chained from 0055, never "is the head"."""
    script_dir = ScriptDirectory.from_config(Config("alembic.ini"))
    revision = script_dir.get_revision(REVISION)
    assert revision is not None
    assert revision.down_revision == DOWN_REVISION
    assert len(REVISION) <= 32  # alembic_version.version_num is varchar(32)
    assert REVISION in {rev.revision for rev in script_dir.walk_revisions()}


def test_constraints_present_by_name(migrated_sessionmaker: sessionmaker[Session]) -> None:
    with migrated_sessionmaker() as session:
        assert object_names(session, [TABLE]) == _orm_names()
        payments = object_names(session, ["payments"])
        assert {DEDUPE_UNIQUE, IN_FLIGHT_INDEX} <= payments
        assert GRACE_FK in object_names(session, ["subscriptions"])
        assert column_names(session, "subscriptions") >= SUBSCRIPTION_COLUMNS
        assert "dedupe_key" in column_names(session, "payments")


def test_migrated_schema_equals_the_create_all_schema(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """Parity: the migration builds what the models declare, definition by definition.

    Covers the new table and the two tables 0056 alters (column types, nullability and
    defaults, CHECK/FK/unique definitions and index definitions, including the partial index's
    predicate) against a database built by ``create_all``.
    """
    with migrated_sessionmaker() as session:
        migrated = schema_dump(session, PARITY_TABLES)
    with team_database() as orm_sessionmaker, orm_sessionmaker() as session:
        orm = schema_dump(session, PARITY_TABLES)
    # Non-vacuous: every section that applies found something to compare, and the objects this
    # revision adds are among the rows compared.
    for section in ("columns", "constraints", "indexes"):
        assert migrated[section], section
    index_rows = " ".join(" ".join(row) for row in migrated["indexes"])
    assert IN_FLIGHT_INDEX in index_rows
    assert any(row[1] == "dedupe_key" for row in migrated["columns"])
    for section, rows in migrated.items():
        assert rows == orm[section], section


def test_the_in_flight_index_is_partial_on_auto_topup_created_and_pending(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """The predicate compares the enum labels directly (``::text`` is not IMMUTABLE)."""
    with migrated_sessionmaker() as session:
        definition = session.execute(
            sa.text("SELECT indexdef FROM pg_indexes WHERE indexname = :n"), {"n": IN_FLIGHT_INDEX}
        ).scalar_one()
    assert "(beneficiary_user_id)" in definition
    assert "'auto_topup'" in definition
    assert "'created'" in definition
    assert "'pending'" in definition
    assert "::text" not in definition


def test_the_in_flight_probe_uses_its_index(migrated_sessionmaker: sessionmaker[Session]) -> None:
    """The post-settle hook's probe (one per settle) is served by the partial index."""
    with migrated_sessionmaker() as session:
        session.execute(sa.text("SET LOCAL enable_seqscan = off"))
        plan = "\n".join(
            session.execute(
                sa.text(
                    "EXPLAIN SELECT 1 FROM payments WHERE beneficiary_user_id = :u "
                    "AND purpose = 'auto_topup' AND status IN ('created', 'pending')"
                ),
                {"u": uuid.uuid4()},
            )
            .scalars()
            .all()
        )
    assert IN_FLIGHT_INDEX in plan


def test_one_setting_per_beneficiary(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    child = seed_user(sm, Role.student)
    parent = seed_user(sm, Role.parent)
    pack = seed_pack(sm)
    card = seed_saved_card(sm, parent)
    seed_auto_topup(sm, beneficiary_id=child, payer_id=parent, pack_id=pack, card_id=card)
    with pytest.raises(IntegrityError, match="uq_auto_topup_settings_beneficiary_user_id"):
        seed_auto_topup(sm, beneficiary_id=child, payer_id=parent, pack_id=pack, card_id=card)


@pytest.mark.parametrize(
    ("threshold", "cap", "constraint"),
    [
        (0, 100, "ck_auto_topup_settings_threshold_positive"),
        (-1, 100, "ck_auto_topup_settings_threshold_positive"),
        (100, -1, "ck_auto_topup_settings_cap_nonnegative"),
    ],
)
def test_threshold_must_be_positive_and_cap_non_negative(
    migrated_sessionmaker: sessionmaker[Session], threshold: int, cap: int, constraint: str
) -> None:
    sm = migrated_sessionmaker
    user = seed_user(sm, Role.student)
    pack = seed_pack(sm)
    with pytest.raises(IntegrityError, match=constraint):
        seed_auto_topup(
            sm,
            beneficiary_id=user,
            payer_id=user,
            pack_id=pack,
            card_id=None,
            enabled=False,
            threshold=threshold,
            cap=cap,
        )


def test_a_zero_cap_is_allowed(migrated_sessionmaker: sessionmaker[Session]) -> None:
    """A switched-off save with no cap typed sends ``monthlyCapMinor: 0`` (contract fact 8)."""
    sm = migrated_sessionmaker
    user = seed_user(sm, Role.student)
    pack = seed_pack(sm)
    setting = seed_auto_topup(
        sm, beneficiary_id=user, payer_id=user, pack_id=pack, card_id=None, enabled=False, cap=0
    )
    with sm() as session:
        row = session.get(AutoTopupSettings, setting)
        assert row is not None
        assert (row.monthly_cap_minor, row.enabled, row.armed, row.crossing_seq) == (
            0,
            False,
            True,
            0,
        )
        assert row.disabled_reason is None
        assert row.last_payment_id is None


def test_a_saved_card_delete_clears_the_setting_card(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """DV-11: no ``enabled_needs_card`` CHECK, so deleting the card (a user deletion cascades
    ``saved_cards``) never fails while auto top-up is on; the service and job enforce the rule."""
    sm = migrated_sessionmaker
    parent = seed_user(sm, Role.parent)
    child = seed_user(sm, Role.student)
    pack = seed_pack(sm)
    card = seed_saved_card(sm, parent)
    setting = seed_auto_topup(
        sm, beneficiary_id=child, payer_id=parent, pack_id=pack, card_id=card, enabled=True
    )
    with sm.begin() as session:
        session.execute(sa.delete(SavedCard).where(SavedCard.id == card))
    with sm() as session:
        row = session.get(AutoTopupSettings, setting)
        assert row is not None
        assert row.saved_card_id is None
        assert row.enabled is True


def test_deleting_the_payer_removes_the_setting_and_a_used_pack_is_restricted(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    user = seed_user(sm, Role.student)
    pack = seed_pack(sm)
    seed_auto_topup(sm, beneficiary_id=user, payer_id=user, pack_id=pack, card_id=None)
    with (
        pytest.raises(IntegrityError, match="fk_auto_topup_settings_credit_pack_id_credit_packs"),
        sm.begin() as session,
    ):
        session.execute(sa.text("DELETE FROM credit_packs WHERE id = :p"), {"p": pack})
    with sm.begin() as session:
        session.execute(sa.text("DELETE FROM users WHERE id = :u"), {"u": user})
    with sm() as session:
        assert (
            session.execute(sa.text("SELECT count(*) FROM auto_topup_settings")).scalar_one() == 0
        )


def test_last_payment_delete_clears_the_link(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    user = seed_user(sm, Role.student)
    pack = seed_pack(sm)
    setting = seed_auto_topup(sm, beneficiary_id=user, payer_id=user, pack_id=pack, card_id=None)
    payment = seed_payment_row(
        sm,
        payer_id=user,
        purpose=PaymentPurpose.auto_topup,
        amount_minor=100,
        dedupe_key=f"auto_topup:{user}:0",
    )
    with sm.begin() as session:
        session.execute(
            sa.text("UPDATE auto_topup_settings SET last_payment_id = :p WHERE id = :s"),
            {"p": payment, "s": setting},
        )
        session.execute(sa.text("DELETE FROM payments WHERE id = :p"), {"p": payment})
    with sm() as session:
        row = session.get(AutoTopupSettings, setting)
        assert row is not None
        assert row.last_payment_id is None


def test_payment_dedupe_key_is_unique(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    user = seed_user(sm, Role.student)
    key = "auto_topup:x:0"
    seed_payment_row(
        sm, payer_id=user, purpose=PaymentPurpose.auto_topup, amount_minor=100, dedupe_key=key
    )
    with pytest.raises(IntegrityError, match=DEDUPE_UNIQUE):
        seed_payment_row(
            sm, payer_id=user, purpose=PaymentPurpose.auto_topup, amount_minor=100, dedupe_key=key
        )


def test_payments_without_a_dedupe_key_never_collide(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """User-initiated payments leave the key NULL, and NULLs are distinct in a unique index."""
    sm = migrated_sessionmaker
    user = seed_user(sm, Role.student)
    pack = seed_pack(sm)
    for _ in range(3):
        seed_payment_row(
            sm,
            payer_id=user,
            purpose=PaymentPurpose.credit_pack,
            amount_minor=100,
            credit_pack_id=pack,
        )
    with sm() as session:
        count = session.execute(
            sa.text("SELECT count(*) FROM payments WHERE dedupe_key IS NULL")
        ).scalar_one()
    assert count == 3


def test_a_grace_payment_delete_clears_the_subscription_link(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    scene = teacher_with_plan(sm)
    attempt = seed_payment_row(
        sm,
        payer_id=scene["payer_id"],
        beneficiary_id=scene["user_id"],
        purpose=PaymentPurpose.extra_seats,
        amount_minor=2_000,
        subscription_id=scene["subscription_id"],
        dedupe_key=f"extra_seat_renewal:{scene['period_id']}:0",
        status=PaymentStatus.failed,
    )
    until = datetime(2026, 12, 13, tzinfo=UTC)
    with sm.begin() as session:
        sub = session.get(Subscription, scene["subscription_id"])
        assert sub is not None
        sub.extra_seat_grace_until = until
        sub.extra_seat_grace_payment_id = attempt
    with sm.begin() as session:
        session.execute(sa.text("DELETE FROM payments WHERE id = :p"), {"p": attempt})
    with sm() as session:
        sub = session.get(Subscription, scene["subscription_id"])
        assert sub is not None
        assert sub.extra_seat_grace_payment_id is None
        assert sub.extra_seat_grace_until == until


def test_scenes_seed_a_consistent_plan(migrated_sessionmaker: sessionmaker[Session]) -> None:
    """The shared fixtures build a plan the later tasks can charge against."""
    sm = migrated_sessionmaker
    teacher = teacher_with_plan(sm, extra=1, pending=0)
    parent = seed_user(sm, Role.parent)
    student = student_with_plan(sm, payer_id=parent)
    link_parent(sm, parent_id=parent, child_id=student["user_id"])
    with sm() as session:
        sub = session.get(Subscription, teacher["subscription_id"])
        assert sub is not None
        # 30_000 price + 1 extra seat at 2_000, "in step" with the first payment.
        assert sub.paymob_amount_minor == 32_000
        assert sub.paymob_subscription_id is not None
        first = session.get(Payment, teacher["payment_id"])
        assert first is not None
        assert first.amount_minor == 32_000
        assert first.status is PaymentStatus.paid
        card = session.get(SavedCard, teacher["card_id"])
        assert card is not None
        assert card.user_id == teacher["user_id"]
        student_card = session.get(SavedCard, student["card_id"])
        assert student_card is not None
        assert student_card.user_id == parent
    assert "card_id" not in teacher_with_plan(sm, card=False)


def test_downgrade_refuses_while_a_setting_exists(
    migrated_sessionmaker_with_downgrade: tuple[sessionmaker[Session], Callable[[str], None]],
) -> None:
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    with sm() as session:
        revision_before = current_revision(session)
    user = seed_user(sm, Role.student)
    pack = seed_pack(sm)
    seed_auto_topup(
        sm, beneficiary_id=user, payer_id=user, pack_id=pack, card_id=None, enabled=False
    )

    with pytest.raises(RuntimeError, match=TABLE):
        downgrade_to(DOWN_REVISION)

    with sm() as session:
        assert current_revision(session) == revision_before
        assert TABLE in public_tables(session)
        assert (
            session.execute(sa.text("SELECT count(*) FROM auto_topup_settings")).scalar_one() == 1
        )
        assert "dedupe_key" in column_names(session, "payments")


def test_downgrade_refuses_while_a_payment_has_a_dedupe_key(
    migrated_sessionmaker_with_downgrade: tuple[sessionmaker[Session], Callable[[str], None]],
) -> None:
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    with sm() as session:
        revision_before = current_revision(session)
    user = seed_user(sm, Role.student)
    seed_payment_row(
        sm,
        payer_id=user,
        purpose=PaymentPurpose.auto_topup,
        amount_minor=100,
        dedupe_key="auto_topup:x:0",
    )

    with pytest.raises(RuntimeError, match="dedupe_key"):
        downgrade_to(DOWN_REVISION)

    with sm() as session:
        assert current_revision(session) == revision_before
        assert "dedupe_key" in column_names(session, "payments")
        assert TABLE in public_tables(session)
        count = session.execute(
            sa.text("SELECT count(*) FROM payments WHERE dedupe_key IS NOT NULL")
        ).scalar_one()
        assert count == 1


@pytest.mark.parametrize("which", ["until", "payment", "both"])
def test_downgrade_refuses_while_extra_seat_grace_is_set(
    migrated_sessionmaker_with_downgrade: tuple[sessionmaker[Session], Callable[[str], None]],
    which: str,
) -> None:
    """Either grace column alone is money state: the probe is an OR, not an AND."""
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    with sm() as session:
        revision_before = current_revision(session)
    scene = teacher_with_plan(sm)
    attempt = seed_payment_row(
        sm,
        payer_id=scene["payer_id"],
        beneficiary_id=scene["user_id"],
        purpose=PaymentPurpose.extra_seats,
        amount_minor=2_000,
        subscription_id=scene["subscription_id"],
        status=PaymentStatus.failed,
    )
    with sm.begin() as session:
        sub = session.get(Subscription, scene["subscription_id"])
        assert sub is not None
        if which in ("until", "both"):
            sub.extra_seat_grace_until = datetime(2026, 12, 13, tzinfo=UTC)
        if which in ("payment", "both"):
            sub.extra_seat_grace_payment_id = attempt

    with pytest.raises(RuntimeError, match="extra_seat_grace"):
        downgrade_to(DOWN_REVISION)

    with sm() as session:
        assert current_revision(session) == revision_before
        assert column_names(session, "subscriptions") >= SUBSCRIPTION_COLUMNS


def test_upgrade_downgrade_upgrade_round_trip(
    migrated_sessionmaker_with_downgrade: tuple[sessionmaker[Session], Callable[[str], None]],
) -> None:
    """With no money state the downgrade drops exactly what 0056 added, and re-upgrades."""
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    # Rows that exist without any 0056 state survive the downgrade: a live subscription with no
    # grace and a payment with no dedupe key.
    scene = teacher_with_plan(sm)
    user = seed_user(sm, Role.student)
    pack = seed_pack(sm)
    seed_payment_row(
        sm,
        payer_id=user,
        purpose=PaymentPurpose.credit_pack,
        amount_minor=100,
        credit_pack_id=pack,
    )

    downgrade_to(DOWN_REVISION)

    with sm() as session:
        assert current_revision(session) == DOWN_REVISION
        assert TABLE not in public_tables(session)
        assert "dedupe_key" not in column_names(session, "payments")
        assert not SUBSCRIPTION_COLUMNS & column_names(session, "subscriptions")
        assert IN_FLIGHT_INDEX not in object_names(session, ["payments"])
        assert DEDUPE_UNIQUE not in object_names(session, ["payments"])
        assert GRACE_FK not in object_names(session, ["subscriptions"])
        assert session.execute(sa.text("SELECT count(*) FROM payments")).scalar_one() == 2
        assert session.execute(sa.text("SELECT count(*) FROM subscriptions")).scalar_one() == 1
        # The enum labels and the 0055 objects are untouched.
        assert "uq_subscriptions_one_live_per_user" in object_names(session, ["subscriptions"])

    # The fixture keeps LEMELY_DATABASE__URL pointed at the throwaway database for the whole
    # test, so ``upgrade_head`` migrates that database.
    upgrade_head()

    with sm() as session:
        assert object_names(session, [TABLE]) == _orm_names()
        assert {DEDUPE_UNIQUE, IN_FLIGHT_INDEX} <= object_names(session, ["payments"])
        assert GRACE_FK in object_names(session, ["subscriptions"])
        assert column_names(session, "subscriptions") >= SUBSCRIPTION_COLUMNS
        sub = session.get(Subscription, scene["subscription_id"])
        assert sub is not None
        assert sub.extra_seat_grace_until is None
