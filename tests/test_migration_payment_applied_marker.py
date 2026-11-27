"""Migration 0059_payment_applied_marker: the applied marker and the void reason on payments.

Adds ``payments.applied_at`` and ``payments.void_reason`` with three CHECKs (Phase 06 task 9
review I1). Per index R10 this file asserts lineage and a round trip, never that 0059 is the head.
The downgrade refuses while either column is set, so each has a test that seeds exactly that row.
"""

from __future__ import annotations

import importlib.util
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.exc import IntegrityError

from lemely.db.base import Base
from lemely.db.models import import_all_models
from lemely.db.models.billing import (
    CANCEL_SOURCES,
    PAYMENT_VOID_REASONS,
    PaymentPurpose,
    PaymentStatus,
)
from lemely.db.models.enums import Role
from tests.merchant_charge_fixtures import seed_payment_row, seed_user
from tests.subscription_fixtures import seed_subscription, seed_tier
from tests.team_db import team_database
from tests.test_migration_tutoring_enums import column_names, current_revision, upgrade_head
from tests.test_migration_usage_ledger import schema_dump

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session, sessionmaker

import_all_models()

REVISION = "0059_payment_applied_marker"
DOWN_REVISION = "0058_suspend_and_prev_amount"
MIGRATION_FILE = (
    Path(__file__).parents[1] / "lemely" / "db" / "migrations" / "versions" / f"{REVISION}.py"
)
NEW_COLUMNS = {"applied_at", "void_reason"}
CHECKS = {
    "ck_payments_applied_not_credited",
    "ck_payments_applied_not_voided",
    "ck_payments_void_reason_known",
}


def _payment(sm: sessionmaker[Session], assignment: str | None = None) -> uuid.UUID:
    """A paid upgrade payment with ``assignment`` applied, e.g. ``applied_at = now()``."""
    payer = seed_user(sm, Role.student)
    payment_id = seed_payment_row(
        sm,
        payer_id=payer,
        purpose=PaymentPurpose.upgrade_proration,
        amount_minor=5_000,
        status=PaymentStatus.paid,
        paid_at=datetime.now(UTC),
    )
    if assignment is not None:
        with sm.begin() as session:
            session.execute(
                sa.text(f"UPDATE payments SET {assignment} WHERE id = :p"),  # noqa: S608 - test literal
                {"p": payment_id},
            )
    return payment_id


def test_the_model_declares_the_columns_and_checks() -> None:
    table = Base.metadata.tables["payments"]
    assert table.columns["applied_at"].nullable is True
    assert getattr(table.columns["applied_at"].type, "timezone", False) is True
    assert table.columns["void_reason"].nullable is True
    assert {str(c.name) for c in table.constraints} >= CHECKS


def test_the_migration_lists_the_same_void_reasons_as_the_model() -> None:
    module = _load_migration()
    assert tuple(module.VOID_REASONS) == PAYMENT_VOID_REASONS  # type: ignore[attr-defined]


def test_revision_chains_from_0058_and_is_in_the_history() -> None:
    script_dir = ScriptDirectory.from_config(Config("alembic.ini"))
    revision = script_dir.get_revision(REVISION)
    assert revision is not None
    assert revision.down_revision == DOWN_REVISION
    assert len(REVISION) <= 32  # alembic_version.version_num is varchar(32)
    assert len(script_dir.get_heads()) == 1


def test_the_columns_have_the_right_types_and_start_null(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    payment_id = _payment(migrated_sessionmaker)
    with migrated_sessionmaker() as session:
        types = {
            row[0]: row[1]
            for row in session.execute(
                sa.text(
                    "SELECT column_name, data_type FROM information_schema.columns "
                    "WHERE table_name = 'payments' AND column_name = ANY(:n) "
                    "AND is_nullable = 'YES'"
                ),
                {"n": sorted(NEW_COLUMNS)},
            ).all()
        }
        stamped = session.execute(
            sa.text("SELECT applied_at, void_reason FROM payments WHERE id = :p"), {"p": payment_id}
        ).one()
    assert types == {"applied_at": "timestamp with time zone", "void_reason": "text"}
    assert tuple(stamped) == (None, None)


def test_a_payment_is_never_both_applied_and_credited(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    with pytest.raises(IntegrityError, match="ck_payments_applied_not_credited"):
        _payment(migrated_sessionmaker, "applied_at = now(), grant_units = 10")
    _payment(migrated_sessionmaker, "applied_at = now()")
    _payment(migrated_sessionmaker, "grant_units = 10, void_reason = 'plan_ended'")


def test_a_payment_is_never_both_applied_and_voided(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    with pytest.raises(IntegrityError, match="ck_payments_applied_not_voided"):
        _payment(migrated_sessionmaker, "applied_at = now(), void_reason = 'superseded'")


@pytest.mark.parametrize("reason", PAYMENT_VOID_REASONS)
def test_every_known_void_reason_is_accepted(
    migrated_sessionmaker: sessionmaker[Session], reason: str
) -> None:
    _payment(migrated_sessionmaker, f"void_reason = '{reason}'")


def test_an_unknown_void_reason_is_refused(migrated_sessionmaker: sessionmaker[Session]) -> None:
    with pytest.raises(IntegrityError, match="ck_payments_void_reason_known"):
        _payment(migrated_sessionmaker, "void_reason = 'because'")


def test_migrated_schema_equals_the_create_all_schema(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    with migrated_sessionmaker() as session:
        migrated = schema_dump(session, ("payments",))
    with team_database() as orm_sessionmaker, orm_sessionmaker() as session:
        orm = schema_dump(session, ("payments",))
    assert {row[1] for row in migrated["columns"]} >= NEW_COLUMNS
    constraint_rows = " ".join(" ".join(row) for row in migrated["constraints"])
    for name in CHECKS:
        assert name in constraint_rows
    for section, rows in migrated.items():
        assert rows == orm[section], section


@pytest.mark.parametrize(
    ("assignment", "mentions"),
    [("applied_at = now()", "applied_at"), ("void_reason = 'plan_ended'", "void_reason")],
)
def test_downgrade_refuses_while_a_marker_or_reason_is_recorded(
    migrated_sessionmaker_with_downgrade: tuple[sessionmaker[Session], Callable[[str], None]],
    assignment: str,
    mentions: str,
) -> None:
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    _payment(sm, assignment)
    with pytest.raises(Exception, match=mentions):
        downgrade_to(DOWN_REVISION)
    with sm() as session:
        assert column_names(session, "payments") >= NEW_COLUMNS
        assert current_revision(session, within=REVISION) != DOWN_REVISION


def test_upgrade_downgrade_upgrade_round_trip(
    migrated_sessionmaker_with_downgrade: tuple[sessionmaker[Session], Callable[[str], None]],
) -> None:
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    _payment(sm)

    downgrade_to(DOWN_REVISION)
    with sm() as session:
        assert current_revision(session, within=REVISION) == DOWN_REVISION
        assert not NEW_COLUMNS & column_names(session, "payments")
        assert session.execute(sa.text("SELECT count(*) FROM payments")).scalar_one() == 1

    upgrade_head()
    with sm() as session:
        assert column_names(session, "payments") >= NEW_COLUMNS
        assert (
            session.execute(
                sa.text(
                    "SELECT count(*) FROM payments WHERE applied_at IS NULL AND void_reason IS NULL"
                )
            ).scalar_one()
            == 1
        )


def _subscription_with_source(sm: sessionmaker[Session], source: str | None) -> uuid.UUID:
    owner = seed_user(sm, Role.student)
    sid = seed_subscription(sm, user_id=owner, tier_id=seed_tier(sm), payer_id=owner)
    if source is not None:
        with sm.begin() as session:
            session.execute(
                sa.text("UPDATE subscriptions SET cancel_source = :s WHERE id = :i"),
                {"s": source, "i": sid},
            )
    return sid


def test_the_model_declares_cancel_source_and_its_check() -> None:
    table = Base.metadata.tables["subscriptions"]
    assert table.columns["cancel_source"].nullable is True
    assert {str(c.name) for c in table.constraints} >= {"ck_subscriptions_cancel_source_known"}


def test_the_migration_lists_the_same_cancel_sources_as_the_model() -> None:
    module = _load_migration()
    assert tuple(module.CANCEL_SOURCES) == CANCEL_SOURCES  # type: ignore[attr-defined]


def test_cancel_source_starts_null_and_is_text(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sid = _subscription_with_source(migrated_sessionmaker, None)
    with migrated_sessionmaker() as session:
        kind = session.execute(
            sa.text(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_name = 'subscriptions' AND column_name = 'cancel_source' "
                "AND is_nullable = 'YES'"
            )
        ).scalar_one()
        value = session.execute(
            sa.text("SELECT cancel_source FROM subscriptions WHERE id = :i"), {"i": sid}
        ).scalar_one()
    assert (kind, value) == ("text", None)


@pytest.mark.parametrize("source", CANCEL_SOURCES)
def test_every_known_cancel_source_is_accepted(
    migrated_sessionmaker: sessionmaker[Session], source: str
) -> None:
    _subscription_with_source(migrated_sessionmaker, source)


def test_an_unknown_cancel_source_is_refused(migrated_sessionmaker: sessionmaker[Session]) -> None:
    with pytest.raises(IntegrityError, match="ck_subscriptions_cancel_source_known"):
        _subscription_with_source(migrated_sessionmaker, "somebody")


def test_downgrade_refuses_while_a_cancel_source_is_recorded(
    migrated_sessionmaker_with_downgrade: tuple[sessionmaker[Session], Callable[[str], None]],
) -> None:
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    _subscription_with_source(sm, "platform_terms")
    with pytest.raises(Exception, match="cancel_source"):
        downgrade_to(DOWN_REVISION)
    with sm() as session:
        assert "cancel_source" in column_names(session, "subscriptions")
        assert current_revision(session, within=REVISION) != DOWN_REVISION


def test_downgrade_drops_cancel_source_when_none_is_recorded_and_upgrade_restores_it(
    migrated_sessionmaker_with_downgrade: tuple[sessionmaker[Session], Callable[[str], None]],
) -> None:
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    _subscription_with_source(sm, None)
    downgrade_to(DOWN_REVISION)
    with sm() as session:
        assert "cancel_source" not in column_names(session, "subscriptions")
    upgrade_head()
    with sm() as session:
        assert "cancel_source" in column_names(session, "subscriptions")


def _load_migration() -> object:
    spec = importlib.util.spec_from_file_location("payment_applied_migration", MIGRATION_FILE)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("direction", ["upgrade", "downgrade"])
def test_the_migration_resets_its_lock_timeout(
    migrated_sessionmaker_with_downgrade: tuple[sessionmaker[Session], Callable[[str], None]],
    direction: str,
) -> None:
    """One ``alembic upgrade`` is one transaction: a ``SET`` left set would leak (0037/0038)."""
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    if direction == "upgrade":
        downgrade_to(DOWN_REVISION)
    module = _load_migration()
    with sm.kw["bind"].connect() as connection:  # type: ignore[union-attr]
        before = connection.execute(sa.text("SHOW lock_timeout")).scalar_one()
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            getattr(module, direction)()
        after = connection.execute(sa.text("SHOW lock_timeout")).scalar_one()
        connection.rollback()
    assert after == before


@pytest.mark.parametrize("direction", ["upgrade", "downgrade"])
def test_the_migration_fails_fast_when_payments_is_locked(
    migrated_sessionmaker_with_downgrade: tuple[sessionmaker[Session], Callable[[str], None]],
    direction: str,
) -> None:
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    downgrade_to(REVISION)  # later migrations may sit above 0059: start from it
    if direction == "upgrade":
        downgrade_to(DOWN_REVISION)
    engine = sm.kw["bind"]
    outcome: dict[str, BaseException] = {}

    def run() -> None:
        try:
            if direction == "upgrade":
                upgrade_head()
            else:
                downgrade_to(DOWN_REVISION)
        except BaseException as exc:  # handed to the test thread to assert on
            outcome["error"] = exc

    holder = engine.connect()  # type: ignore[union-attr]
    try:
        holder.execute(sa.text("LOCK TABLE payments IN ACCESS EXCLUSIVE MODE"))
        worker = threading.Thread(target=run)
        worker.start()
        worker.join(timeout=60)
        failed_fast = not worker.is_alive()
    finally:
        holder.rollback()
        holder.close()
    worker.join()
    assert failed_fast, "the migration waited for the lock instead of timing out"
    assert "lock timeout" in str(outcome["error"])
    with sm() as session:
        expected = DOWN_REVISION if direction == "upgrade" else REVISION
        assert current_revision(session, within=REVISION) == expected
