"""Migration 0058_suspend_and_prev_amount: the suspension marker and the replaced amount.

Adds ``subscriptions.suspended_at``, ``previous_amount_minor`` and ``amount_replaced_at`` (Phase 05
task 8).

Per index R10 this file asserts lineage and a round trip, never that 0058 is the head. The
downgrade refuses while a suspension is recorded, so it has a test that seeds exactly that row.
"""

from __future__ import annotations

import importlib.util
import threading
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
from lemely.db.models.enums import Role
from tests.subscription_fixtures import seed_subscription, seed_tier, seed_user
from tests.team_db import team_database
from tests.test_migration_tutoring_enums import column_names, current_revision, upgrade_head
from tests.test_migration_usage_ledger import schema_dump

if TYPE_CHECKING:
    import uuid
    from collections.abc import Callable

    from sqlalchemy.orm import Session, sessionmaker

import_all_models()

REVISION = "0058_suspend_and_prev_amount"
DOWN_REVISION = "0057_admin_audit_log"
MIGRATION_FILE = (
    Path(__file__).parents[1] / "lemely" / "db" / "migrations" / "versions" / f"{REVISION}.py"
)


NEW_COLUMNS = {
    "suspended_at",
    "previous_amount_minor",
    "amount_replaced_at",
    "amount_sync_uncertain_at",
    "drift_checked_at",
}
PAIRED_CHECK = "ck_subscriptions_previous_amount_paired"


def _marked_subscription(sm: sessionmaker[Session], assignment: str) -> uuid.UUID:
    """A subscription with ``assignment`` applied, e.g. ``suspended_at = now()``."""
    user = seed_user(sm, Role.student)
    sid = seed_subscription(sm, user_id=user, tier_id=seed_tier(sm), payer_id=user)
    with sm.begin() as session:
        session.execute(
            sa.text(f"UPDATE subscriptions SET {assignment} WHERE id = :s"),  # noqa: S608 - test literal
            {"s": sid},
        )
    return sid


def test_the_model_declares_the_columns() -> None:
    columns = Base.metadata.tables["subscriptions"].columns
    for name in (
        "suspended_at",
        "amount_replaced_at",
        "amount_sync_uncertain_at",
        "drift_checked_at",
    ):
        assert columns[name].nullable is True
        assert getattr(columns[name].type, "timezone", False) is True
    assert columns["previous_amount_minor"].nullable is True
    assert isinstance(columns["previous_amount_minor"].type, sa.BigInteger)
    names = {str(c.name) for c in Base.metadata.tables["subscriptions"].constraints}
    assert PAIRED_CHECK in names


def test_revision_chains_from_0057_and_is_in_the_history() -> None:
    script_dir = ScriptDirectory.from_config(Config("alembic.ini"))
    revision = script_dir.get_revision(REVISION)
    assert revision is not None
    assert revision.down_revision == DOWN_REVISION
    assert len(REVISION) <= 32  # alembic_version.version_num is varchar(32)
    assert len(script_dir.get_heads()) == 1


def test_the_columns_have_the_right_types_and_start_null(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    with migrated_sessionmaker() as session:
        types = {
            row[0]: row[1]
            for row in session.execute(
                sa.text(
                    "SELECT column_name, data_type FROM information_schema.columns "
                    "WHERE table_name = 'subscriptions' AND column_name = ANY(:n) "
                    "AND is_nullable = 'YES'"
                ),
                {"n": sorted(NEW_COLUMNS)},
            ).all()
        }
        user = seed_user(migrated_sessionmaker, Role.student)
        sid = seed_subscription(
            migrated_sessionmaker, user_id=user, tier_id=seed_tier(migrated_sessionmaker)
        )
        stamped = session.execute(
            sa.text(
                "SELECT suspended_at, previous_amount_minor, amount_replaced_at, "
                "amount_sync_uncertain_at, drift_checked_at "
                "FROM subscriptions WHERE id = :s"
            ),
            {"s": sid},
        ).one()
    assert types == {
        "suspended_at": "timestamp with time zone",
        "previous_amount_minor": "bigint",
        "amount_replaced_at": "timestamp with time zone",
        "amount_sync_uncertain_at": "timestamp with time zone",
        "drift_checked_at": "timestamp with time zone",
    }
    assert tuple(stamped) == (None, None, None, None, None)  # every row starts unmarked


def test_the_previous_amount_and_its_time_are_set_together_or_not_at_all(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    for assignment in ("previous_amount_minor = 100", "amount_replaced_at = now()"):
        with pytest.raises(IntegrityError, match=PAIRED_CHECK):
            _marked_subscription(migrated_sessionmaker, assignment)
    _marked_subscription(
        migrated_sessionmaker, "previous_amount_minor = 100, amount_replaced_at = now()"
    )


def test_migrated_schema_equals_the_create_all_schema(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    with migrated_sessionmaker() as session:
        migrated = schema_dump(session, ("subscriptions",))
    with team_database() as orm_sessionmaker, orm_sessionmaker() as session:
        orm = schema_dump(session, ("subscriptions",))
    assert {row[1] for row in migrated["columns"]} >= NEW_COLUMNS
    assert any(PAIRED_CHECK in " ".join(row) for row in migrated["constraints"])
    for section, rows in migrated.items():
        assert rows == orm[section], section


@pytest.mark.parametrize(
    ("assignment", "mentions"),
    [
        ("suspended_at = now()", "suspended_at"),
        ("previous_amount_minor = 100, amount_replaced_at = now()", "previous_amount_minor"),
        ("amount_sync_uncertain_at = now()", "amount_sync_uncertain_at"),
    ],
)
def test_downgrade_refuses_while_a_suspension_or_replaced_amount_is_recorded(
    migrated_sessionmaker_with_downgrade: tuple[sessionmaker[Session], Callable[[str], None]],
    assignment: str,
    mentions: str,
) -> None:
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    _marked_subscription(sm, assignment)
    with pytest.raises(Exception, match=mentions):
        downgrade_to(DOWN_REVISION)
    with sm() as session:
        assert column_names(session, "subscriptions") >= NEW_COLUMNS
        assert current_revision(session, within=REVISION) != DOWN_REVISION


def test_upgrade_downgrade_upgrade_round_trip(
    migrated_sessionmaker_with_downgrade: tuple[sessionmaker[Session], Callable[[str], None]],
) -> None:
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    _marked_subscription(sm, "drift_checked_at = now()")  # bookkeeping: no downgrade guard

    downgrade_to(DOWN_REVISION)
    with sm() as session:
        assert current_revision(session, within=REVISION) == DOWN_REVISION
        assert not NEW_COLUMNS & column_names(session, "subscriptions")
        assert session.execute(sa.text("SELECT count(*) FROM subscriptions")).scalar_one() == 1

    upgrade_head()
    with sm() as session:
        assert column_names(session, "subscriptions") >= NEW_COLUMNS
        assert (
            session.execute(
                sa.text(
                    "SELECT count(*) FROM subscriptions WHERE suspended_at IS NULL "
                    "AND previous_amount_minor IS NULL AND amount_replaced_at IS NULL "
                    "AND amount_sync_uncertain_at IS NULL AND drift_checked_at IS NULL"
                )
            ).scalar_one()
            == 1
        )


def _load_migration() -> object:
    spec = importlib.util.spec_from_file_location("prev_amount_migration", MIGRATION_FILE)
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
def test_the_migration_fails_fast_when_subscriptions_is_locked(
    migrated_sessionmaker_with_downgrade: tuple[sessionmaker[Session], Callable[[str], None]],
    direction: str,
) -> None:
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    downgrade_to(REVISION)  # later migrations may sit above 0058: start from it
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
        holder.execute(sa.text("LOCK TABLE subscriptions IN ACCESS EXCLUSIVE MODE"))
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
