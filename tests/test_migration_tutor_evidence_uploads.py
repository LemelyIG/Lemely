"""Migration 0051_tutor_evidence_uploads: the T6 upload-attempt log (T30 F30-5).

One additive table and its index. The expected names come from the ORM
(``lemely/db/models/tutoring.py``), so these tests compare the migration with an
independent declaration; SPEC §a.2 has no section for this table to parse.
The downgrade must drop only this table: every earlier tutoring table keeps its
constraints, its indexes and its rows.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory

from lemely.db.base import Base
from lemely.db.models import import_all_models
from tests.test_migration_tutoring_enums import (
    current_revision,
    head_revision,
    object_names,
    public_tables,
    spec_tutoring_tables,
    upgrade_head,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session, sessionmaker

import_all_models()

REVISION = "0051_tutor_evidence_uploads"
DOWN_REVISION = "0050_tutoring_safety"
TABLE = "tutor_evidence_uploads"


def _orm_names() -> set[str]:
    """Every constraint and index name the ORM declares on the table."""
    table = Base.metadata.tables[TABLE]
    names = {str(constraint.name) for constraint in table.constraints}
    return names | {str(index.name) for index in table.indexes}


def test_orm_declares_the_three_named_objects() -> None:
    """Non-vacuity for the name checks below: primary key, foreign key, index."""
    assert _orm_names() == {
        "pk_tutor_evidence_uploads",
        "fk_tutor_evidence_uploads_tutor_profile_id_tutor_profiles",
        "ix_tutor_evidence_uploads_profile_day",
    }


def test_revision_chains_from_0050_and_is_the_head() -> None:
    script_dir = ScriptDirectory.from_config(Config("alembic.ini"))
    revision = script_dir.get_revision(REVISION)
    assert revision is not None
    assert revision.down_revision == DOWN_REVISION
    assert len(REVISION) <= 32  # alembic_version.version_num is varchar(32)
    assert head_revision() == REVISION


def test_constraints_present_by_name(migrated_sessionmaker: sessionmaker[Session]) -> None:
    with migrated_sessionmaker() as session:
        assert object_names(session, [TABLE]) == _orm_names()


def test_upgrade_downgrade_upgrade_round_trip(
    migrated_sessionmaker_with_downgrade: tuple[sessionmaker[Session], Callable[[str], None]],
) -> None:
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    earlier = spec_tutoring_tables()
    assert len(earlier) == 17
    user_id, profile_id = uuid.uuid4(), uuid.uuid4()
    with sm.begin() as session:
        before = object_names(session, earlier)
        session.execute(
            sa.text("INSERT INTO users (id, email, role) VALUES (:u, :e, 'teacher')"),
            {"u": user_id, "e": f"{user_id}@example.com"},
        )
        session.execute(
            sa.text(
                "INSERT INTO tutor_profiles (id, user_id, public_first_name, headline, "
                "offers_virtual, area_code) VALUES (:p, :u, 'Sara', 'IGCSE Mathematics', "
                "true, 'cairo')"
            ),
            {"p": profile_id, "u": user_id},
        )
        session.execute(
            sa.text(f"INSERT INTO {TABLE} (tutor_profile_id) VALUES (:p)"),  # noqa: S608 - constant
            {"p": profile_id},
        )

    downgrade_to(DOWN_REVISION)

    with sm() as session:
        assert current_revision(session) == DOWN_REVISION
        assert TABLE not in public_tables(session)
        assert set(earlier) <= public_tables(session)
        # Nothing else changed: the same constraints and indexes, the same rows.
        assert object_names(session, earlier) == before
        assert (
            session.execute(
                sa.text("SELECT user_id FROM tutor_profiles WHERE id = :p"), {"p": profile_id}
            ).scalar_one()
            == user_id
        )

    upgrade_head()

    with sm() as session:
        assert current_revision(session) == REVISION
        assert object_names(session, [TABLE]) == _orm_names()
        assert object_names(session, earlier) == before
        count = session.execute(sa.text(f"SELECT count(*) FROM {TABLE}")).scalar_one()  # noqa: S608 - constant
        assert count == 0  # the downgrade dropped the log; nothing restores it
