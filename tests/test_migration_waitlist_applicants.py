"""Migration 0052_waitlist_applicants: the landing-page waitlist table.

Additive: one table, two enum types. The migrated schema must match the ORM (no drift), the
downgrade must drop exactly what the upgrade added, and the unique email and one-time-token
indexes must hold in the migrated database, not just in ``create_all``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.exc import IntegrityError

from lemely.db.base import Base
from lemely.db.models import import_all_models
from tests.test_migration_tutoring_enums import (
    current_revision,
    head_revision,
    object_names,
    public_tables,
    upgrade_head,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session, sessionmaker

import_all_models()

REVISION = "0052_waitlist_applicants"
DOWN_REVISION = "0051_tutor_evidence_uploads"
TABLE = "waitlist_applicants"


def _insert(session: Session, email: str, token_hash: str | None = None) -> None:
    session.execute(
        sa.text(
            "INSERT INTO waitlist_applicants "
            "(email, role, consent_version, consent_text, consent_at, completion_token_hash) "
            "VALUES (:e, 'student', 'v', 'c', now(), :h)"
        ),
        {"e": email, "h": token_hash},
    )


def test_revision_chains_from_0051() -> None:
    script_dir = ScriptDirectory.from_config(Config("alembic.ini"))
    revision = script_dir.get_revision(REVISION)
    assert revision is not None
    assert revision.down_revision == DOWN_REVISION
    assert len(REVISION) <= 32  # alembic_version.version_num is varchar(32)


def test_migrated_schema_matches_the_orm(migrated_sessionmaker: sessionmaker[Session]) -> None:
    table = Base.metadata.tables[TABLE]
    orm_names = {str(c.name) for c in table.constraints} | {str(i.name) for i in table.indexes}
    with migrated_sessionmaker() as session:
        assert object_names(session, [TABLE]) >= orm_names
        connection = session.connection()
        diff = compare_metadata(
            MigrationContext.configure(connection, opts={"compare_type": True}),
            Base.metadata,
        )
    mine = [d for d in diff if TABLE in repr(d)]
    assert mine == []


def test_email_is_unique_and_a_token_digest_is_unique_when_present(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    with migrated_sessionmaker.begin() as session:
        _insert(session, "a@example.com", "h1")
        _insert(session, "b@example.com", None)
        _insert(session, "c@example.com", None)  # many cleared tokens are fine
    with pytest.raises(IntegrityError), migrated_sessionmaker.begin() as session:
        _insert(session, "a@example.com")
    with pytest.raises(IntegrityError), migrated_sessionmaker.begin() as session:
        _insert(session, "d@example.com", "h1")


def test_upgrade_downgrade_upgrade_round_trip(
    migrated_sessionmaker_with_downgrade: tuple[sessionmaker[Session], Callable[[str], None]],
) -> None:
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    with sm.begin() as session:
        before = object_names(session, ["users"])
        _insert(session, "gone@example.com")

    downgrade_to(DOWN_REVISION)

    with sm() as session:
        assert current_revision(session) == DOWN_REVISION
        assert TABLE not in public_tables(session)
        types = set(
            session.execute(
                sa.text("SELECT typname FROM pg_type WHERE typname LIKE 'waitlist%'")
            ).scalars()
        )
        assert types == set()
        assert object_names(session, ["users"]) == before

    upgrade_head()

    with sm() as session:
        assert current_revision(session) == head_revision()
        assert TABLE in public_tables(session)
        assert session.execute(sa.text(f"SELECT count(*) FROM {TABLE}")).scalar_one() == 0  # noqa: S608 - constant
