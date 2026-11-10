"""Migration 0053_waitlist_applicant_name: a nullable ``name`` column on the waitlist table.

Additive. Rows that exist before the migration keep working with ``name`` NULL; the downgrade
removes the column and nothing else.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory

from lemely.db.base import Base
from lemely.db.models import import_all_models
from tests.test_migration_tutoring_enums import current_revision, head_revision, upgrade_head

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session, sessionmaker

import_all_models()

REVISION = "0053_waitlist_applicant_name"
DOWN_REVISION = "0052_waitlist_applicants"
TABLE = "waitlist_applicants"

_COLUMN_SQL = sa.text(
    "SELECT data_type, character_maximum_length, is_nullable FROM information_schema.columns "
    "WHERE table_name = :t AND column_name = 'name'"
)


def _insert(session: Session, email: str) -> None:
    session.execute(
        sa.text(
            "INSERT INTO waitlist_applicants "
            "(email, role, consent_version, consent_text, consent_at) "
            "VALUES (:e, 'student', 'v', 'c', now())"
        ),
        {"e": email},
    )


def test_revision_chains_from_0052() -> None:
    script_dir = ScriptDirectory.from_config(Config("alembic.ini"))
    revision = script_dir.get_revision(REVISION)
    assert revision is not None
    assert revision.down_revision == DOWN_REVISION
    assert len(REVISION) <= 32  # alembic_version.version_num is varchar(32)


def test_name_is_a_nullable_varchar_100_and_matches_the_orm(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    with migrated_sessionmaker.begin() as session:
        data_type, length, nullable = session.execute(_COLUMN_SQL, {"t": TABLE}).one()
        assert (data_type, length, nullable) == ("character varying", 100, "YES")
        _insert(session, "old@example.com")  # a row with no name is still valid
        assert session.execute(sa.text("SELECT name FROM waitlist_applicants")).scalar_one() is None
        diff = compare_metadata(
            MigrationContext.configure(session.connection(), opts={"compare_type": True}),
            Base.metadata,
        )
    assert [d for d in diff if TABLE in repr(d)] == []


def test_upgrade_downgrade_upgrade_round_trip(
    migrated_sessionmaker_with_downgrade: tuple[sessionmaker[Session], Callable[[str], None]],
) -> None:
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    with sm.begin() as session:
        _insert(session, "keep@example.com")

    downgrade_to(DOWN_REVISION)

    with sm() as session:
        assert current_revision(session) == DOWN_REVISION
        assert session.execute(_COLUMN_SQL, {"t": TABLE}).first() is None
        # The rest of the table (and the row) survives.
        assert session.execute(sa.text(f"SELECT count(*) FROM {TABLE}")).scalar_one() == 1  # noqa: S608 - constant

    upgrade_head()

    with sm() as session:
        assert current_revision(session) == head_revision()
        assert session.execute(_COLUMN_SQL, {"t": TABLE}).one()[2] == "YES"
