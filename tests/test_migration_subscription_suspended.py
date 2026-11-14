"""Migration 0058_subscription_suspended: ``subscriptions.suspended_at`` (Phase 05 task 8).

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

REVISION = "0058_subscription_suspended"
DOWN_REVISION = "0057_admin_audit_log"
MIGRATION_FILE = (
    Path(__file__).parents[1] / "lemely" / "db" / "migrations" / "versions" / f"{REVISION}.py"
)


def _suspended_subscription(sm: sessionmaker[Session]) -> uuid.UUID:
    user = seed_user(sm, Role.student)
    sid = seed_subscription(sm, user_id=user, tier_id=seed_tier(sm), payer_id=user)
    with sm.begin() as session:
        session.execute(
            sa.text("UPDATE subscriptions SET suspended_at = now() WHERE id = :s"), {"s": sid}
        )
    return sid


def test_the_model_declares_the_column() -> None:
    column = Base.metadata.tables["subscriptions"].columns["suspended_at"]
    assert column.nullable is True
    assert getattr(column.type, "timezone", False) is True


def test_revision_chains_from_0057_and_is_in_the_history() -> None:
    script_dir = ScriptDirectory.from_config(Config("alembic.ini"))
    revision = script_dir.get_revision(REVISION)
    assert revision is not None
    assert revision.down_revision == DOWN_REVISION
    assert len(REVISION) <= 32  # alembic_version.version_num is varchar(32)
    assert len(script_dir.get_heads()) == 1


def test_the_column_is_a_nullable_timestamptz(migrated_sessionmaker: sessionmaker[Session]) -> None:
    with migrated_sessionmaker() as session:
        row = session.execute(
            sa.text(
                "SELECT data_type, is_nullable FROM information_schema.columns "
                "WHERE table_name = 'subscriptions' AND column_name = 'suspended_at'"
            )
        ).one()
        user = seed_user(migrated_sessionmaker, Role.student)
        sid = seed_subscription(
            migrated_sessionmaker, user_id=user, tier_id=seed_tier(migrated_sessionmaker)
        )
        stamped = session.execute(
            sa.text("SELECT suspended_at FROM subscriptions WHERE id = :s"), {"s": sid}
        ).scalar_one()
    assert tuple(row) == ("timestamp with time zone", "YES")
    assert stamped is None  # every row starts unsuspended


def test_migrated_schema_equals_the_create_all_schema(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    with migrated_sessionmaker() as session:
        migrated = schema_dump(session, ("subscriptions",))
    with team_database() as orm_sessionmaker, orm_sessionmaker() as session:
        orm = schema_dump(session, ("subscriptions",))
    assert any(row[1] == "suspended_at" for row in migrated["columns"])
    for section, rows in migrated.items():
        assert rows == orm[section], section


def test_downgrade_refuses_while_a_suspension_is_recorded(
    migrated_sessionmaker_with_downgrade: tuple[sessionmaker[Session], Callable[[str], None]],
) -> None:
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    _suspended_subscription(sm)
    with pytest.raises(Exception, match="suspended_at"):
        downgrade_to(DOWN_REVISION)
    with sm() as session:
        assert "suspended_at" in column_names(session, "subscriptions")
        assert current_revision(session) != DOWN_REVISION


def test_upgrade_downgrade_upgrade_round_trip(
    migrated_sessionmaker_with_downgrade: tuple[sessionmaker[Session], Callable[[str], None]],
) -> None:
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    user = seed_user(sm, Role.student)
    seed_subscription(sm, user_id=user, tier_id=seed_tier(sm), payer_id=user)

    downgrade_to(DOWN_REVISION)
    with sm() as session:
        assert current_revision(session) == DOWN_REVISION
        assert "suspended_at" not in column_names(session, "subscriptions")
        assert session.execute(sa.text("SELECT count(*) FROM subscriptions")).scalar_one() == 1

    upgrade_head()
    with sm() as session:
        assert "suspended_at" in column_names(session, "subscriptions")
        assert (
            session.execute(
                sa.text("SELECT count(*) FROM subscriptions WHERE suspended_at IS NULL")
            ).scalar_one()
            == 1
        )


def _load_migration() -> object:
    spec = importlib.util.spec_from_file_location("suspended_migration", MIGRATION_FILE)
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
        assert current_revision(session) == expected
