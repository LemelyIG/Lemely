"""Migration 0055_flashcard_generation: a generation status on flashcard decks.

Additive. Existing decks read as ``ready``; the check constraint refuses an unknown status; the
downgrade drops the four columns and the constraint and nothing else.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.exc import IntegrityError

from lemely.db.base import Base
from lemely.db.models import User, import_all_models
from lemely.db.models.enums import Role
from tests.test_migration_tutoring_enums import current_revision, head_revision, upgrade_head

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session, sessionmaker

import_all_models()

REVISION = "0055_flashcard_generation"
DOWN_REVISION = "0054_waitlist_email_confirmation"
TABLE = "flashcard_decks"
NEW_COLUMNS = {"generation_status", "requested_count", "generation_started_at", "generation_error"}

_COLUMNS_SQL = sa.text(
    "SELECT column_name, data_type, character_maximum_length, is_nullable, column_default "
    "FROM information_schema.columns WHERE table_name = :t"
)


def _user(session: Session) -> uuid.UUID:
    uid = uuid.uuid4()
    session.add(User(id=uid, email=f"{uid}@example.com", role=Role.student))
    session.flush()
    return uid


def _insert_old_style_deck(session: Session, user_id: uuid.UUID) -> None:
    # Only pre-0055 columns, as a deck written before this migration would be.
    session.execute(
        sa.text(
            "INSERT INTO flashcard_decks (user_id, subject_code, title, origin) "
            "VALUES (:u, '0580', 'Vectors', 'manual')"
        ),
        {"u": user_id},
    )


def test_revision_chains_from_0054() -> None:
    script_dir = ScriptDirectory.from_config(Config("alembic.ini"))
    revision = script_dir.get_revision(REVISION)
    assert revision is not None
    assert revision.down_revision == DOWN_REVISION
    assert len(REVISION) <= 32  # alembic_version.version_num is varchar(32)


def test_columns_defaults_and_orm_match(migrated_sessionmaker: sessionmaker[Session]) -> None:
    with migrated_sessionmaker.begin() as session:
        cols = {row[0]: row for row in session.execute(_COLUMNS_SQL, {"t": TABLE})}
        assert set(cols) >= NEW_COLUMNS
        assert cols["generation_status"][1:4] == ("character varying", 16, "NO")
        assert "ready" in (cols["generation_status"][4] or "")
        assert cols["requested_count"][1] == "integer"
        assert cols["requested_count"][3] == "YES"
        assert cols["generation_started_at"][1] == "timestamp with time zone"
        assert cols["generation_error"][1:4] == ("character varying", 64, "YES")

        user_id = _user(session)
        _insert_old_style_deck(session, user_id)
        status = session.execute(
            sa.text("SELECT generation_status FROM flashcard_decks")
        ).scalar_one()
        assert status == "ready"

        diff = compare_metadata(
            MigrationContext.configure(session.connection(), opts={"compare_type": True}),
            Base.metadata,
        )
    assert [d for d in diff if TABLE in repr(d)] == []


def test_check_constraint_refuses_an_unknown_status(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    with migrated_sessionmaker() as session:
        user_id = _user(session)
        _insert_old_style_deck(session, user_id)
        with pytest.raises(IntegrityError):
            session.execute(sa.text("UPDATE flashcard_decks SET generation_status = 'cooking'"))
            session.flush()
        session.rollback()


def test_upgrade_downgrade_upgrade_round_trip(
    migrated_sessionmaker_with_downgrade: tuple[sessionmaker[Session], Callable[[str], None]],
) -> None:
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    with sm.begin() as session:
        user_id = _user(session)
        _insert_old_style_deck(session, user_id)

    downgrade_to(DOWN_REVISION)

    with sm() as session:
        assert current_revision(session) == DOWN_REVISION
        cols = {row[0] for row in session.execute(_COLUMNS_SQL, {"t": TABLE})}
        assert cols.isdisjoint(NEW_COLUMNS)
        assert session.execute(sa.text(f"SELECT count(*) FROM {TABLE}")).scalar_one() == 1  # noqa: S608 - constant

    upgrade_head()

    with sm() as session:
        assert current_revision(session) == head_revision()
        status = session.execute(
            sa.text("SELECT generation_status FROM flashcard_decks")
        ).scalar_one()
        assert status == "ready"
