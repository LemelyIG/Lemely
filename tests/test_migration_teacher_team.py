"""Migration 0054_teacher_team: teacher_members, assistant invites, usage_grants FK (§4.4).

Expected object names come from the ORM (``lemely/db/models/team.py``), an independent
declaration of the same schema. The downgrade removes everything this migration added,
including the ``inviterole`` label: Postgres cannot drop an enum label, so assistant
invites are deleted and the type is rebuilt with its three original labels.
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
from tests.team_db import team_database
from tests.test_migration_tutoring_enums import (
    column_names,
    current_revision,
    enum_labels,
    object_names,
    public_tables,
    type_exists,
    upgrade_head,
)
from tests.test_migration_usage_ledger import schema_dump

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session, sessionmaker

import_all_models()

REVISION = "0054_teacher_team"
DOWN_REVISION = "0053_billing_payments"
TABLE = "teacher_members"
NEW_TYPES = ("teachermemberkind", "teachermemberstatus", "assistantrole", "capperiod")
INVITE_OBJECTS = {
    "ck_invites_target",
    "ck_invites_assistant_shape",
    "fk_invites_team_teacher_id_users",
    "ix_invites_team_teacher_id",
}
INVITE_COLUMNS = {"team_teacher_id", "assistant_role"}
GRANT_FK = "fk_usage_grants_teacher_member_id_teacher_members"
PREVIOUS_INVITE_ROLE_LABELS = ["student", "teacher", "parent"]

#: Every table 0054 creates or alters, for the parity check.
PARITY_TABLES = (TABLE, "invites", "usage_grants")
PARITY_ENUMS = (*NEW_TYPES, "inviterole")


def _orm_names() -> set[str]:
    table = Base.metadata.tables[TABLE]
    names = {str(constraint.name) for constraint in table.constraints}
    return names | {str(index.name) for index in table.indexes}


def test_orm_declares_the_named_objects() -> None:
    assert _orm_names() == {
        "pk_teacher_members",
        "fk_teacher_members_teacher_user_id_users",
        "fk_teacher_members_member_user_id_users",
        "uq_teacher_members_teacher_member",
        "ck_teacher_members_not_self",
        "ck_teacher_members_seat_fields",
        "ck_teacher_members_assistant_fields",
        "ck_teacher_members_cap_nonnegative",
        "ck_teacher_members_leaving_has_date",
        "ck_teacher_members_active_has_no_date",
        "ix_teacher_members_member_user_id",
        "ix_teacher_members_teacher_kind_status",
        "ix_teacher_members_leaves_at",
    }


def test_orm_invites_declares_the_named_objects() -> None:
    names = {str(c.name) for c in Base.metadata.tables["invites"].constraints}
    names |= {str(i.name) for i in Base.metadata.tables["invites"].indexes}
    assert names >= INVITE_OBJECTS
    assert "ck_invites_ck_invites_target" not in names


def test_revision_is_in_the_history_after_0053() -> None:
    """In the history and chained from 0053; never asserted to be head (index R10)."""
    script_dir = ScriptDirectory.from_config(Config("alembic.ini"))
    assert REVISION in {rev.revision for rev in script_dir.walk_revisions()}
    revision = script_dir.get_revision(REVISION)
    assert revision is not None
    assert revision.down_revision == DOWN_REVISION
    assert len(REVISION) <= 32


def test_objects_present_by_name(migrated_sessionmaker: sessionmaker[Session]) -> None:
    with migrated_sessionmaker() as session:
        assert object_names(session, [TABLE]) == _orm_names()
        assert object_names(session, ["invites"]) >= INVITE_OBJECTS
        assert GRANT_FK in object_names(session, ["usage_grants"])
        assert "assistant" in enum_labels(session, "inviterole")
        assert enum_labels(session, "assistantrole") == ["co_teacher", "marker", "viewer"]
        assert column_names(session, "invites") >= INVITE_COLUMNS


def test_migrated_schema_equals_the_create_all_schema(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """Parity: the migration builds what the models declare, definition by definition.

    Compares column types, nullability and defaults, CHECK/FK/unique definitions, index
    definitions and enum labels (in order) of the three touched tables against a database
    built by ``create_all``.
    """
    with migrated_sessionmaker() as session:
        migrated = schema_dump(session, PARITY_TABLES, enums=PARITY_ENUMS)
    with team_database() as orm_sessionmaker, orm_sessionmaker() as session:
        orm = schema_dump(session, PARITY_TABLES, enums=PARITY_ENUMS)
    # Non-vacuous: every section that applies found something to compare.
    for section in ("columns", "constraints", "indexes", "enums"):
        assert migrated[section], section
    for section, rows in migrated.items():
        assert rows == orm[section], section


def test_migrated_check_constraints_refuse_bad_rows(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """The migrated CHECKs are live, not just present by name."""
    teacher, helper = uuid.uuid4(), uuid.uuid4()
    with migrated_sessionmaker.begin() as session:
        for uid in (teacher, helper):
            session.execute(
                sa.text("INSERT INTO users (id, email, role) VALUES (:u, :e, 'teacher')"),
                {"u": uid, "e": f"{uid}@example.com"},
            )
    with (
        pytest.raises(IntegrityError, match="ck_teacher_members_seat_fields"),
        migrated_sessionmaker.begin() as session,
    ):
        session.execute(
            sa.text(
                "INSERT INTO teacher_members (teacher_user_id, member_user_id, kind) "
                "VALUES (:t, :h, 'student_seat')"
            ),
            {"t": teacher, "h": helper},
        )
    with (
        pytest.raises(IntegrityError, match="ck_invites_assistant_shape"),
        migrated_sessionmaker.begin() as session,
    ):
        session.execute(
            sa.text(
                "INSERT INTO invites (code, role, created_by, team_teacher_id) "
                "VALUES ('BADSHAPE01', 'assistant', :t, :t)"
            ),
            {"t": teacher},
        )
    with (
        pytest.raises(IntegrityError, match="ck_invites_target"),
        migrated_sessionmaker.begin() as session,
    ):
        session.execute(
            sa.text(
                "INSERT INTO invites (code, role, created_by) VALUES ('NOTARGET01', 'student', :t)"
            ),
            {"t": teacher},
        )


def test_leaving_sweep_index_is_partial_on_leaving_seats(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    with migrated_sessionmaker() as session:
        definition = session.execute(
            sa.text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE tablename = 'teacher_members' AND indexname = 'ix_teacher_members_leaves_at'"
            )
        ).scalar_one()
    assert "(leaves_at)" in definition
    assert "WHERE" in definition
    assert "'leaving'" in definition


def test_seat_grant_fk_restricts_deleting_the_member(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """``RESTRICT`` is stated, not left to the ``NO ACTION`` default."""
    with migrated_sessionmaker() as session:
        definition = session.execute(
            sa.text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :n"),
            {"n": GRANT_FK},
        ).scalar_one()
    assert "ON DELETE RESTRICT" in definition


def test_downgrade_refuses_while_a_seat_grant_exists(
    migrated_sessionmaker_with_downgrade: tuple[sessionmaker[Session], Callable[[str], None]],
) -> None:
    """A seat grant cannot be deleted (ledger entries RESTRICT) or nulled (seat_link CHECK).

    Dropping ``teacher_members`` would orphan it and make the next upgrade fail with a
    foreign-key violation, so the downgrade stops, and the revision stays at 0054.
    """
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    teacher, student, member = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with sm.begin() as session:
        for uid, role in ((teacher, "teacher"), (student, "student")):
            session.execute(
                sa.text("INSERT INTO users (id, email, role) VALUES (:u, :e, :r)"),
                {"u": uid, "e": f"{uid}@example.com", "r": role},
            )
        session.execute(
            sa.text(
                "INSERT INTO teacher_members (id, teacher_user_id, member_user_id, kind, "
                "scope_subjects, scope_actions) "
                "VALUES (:m, :t, :s, 'student_seat', '{}', '{}')"
            ),
            {"m": member, "t": teacher, "s": student},
        )
        session.execute(
            sa.text(
                "INSERT INTO usage_grants (owner_user_id, kind, visible, teacher_member_id, "
                "priority, units, idempotency_key) "
                "VALUES (:t, 'seat_allowance', false, :m, 10, 100, 'seat-grant-1')"
            ),
            {"t": teacher, "m": member},
        )

    with pytest.raises(RuntimeError, match="seat grant"):
        downgrade_to(DOWN_REVISION)

    with sm() as session:
        assert current_revision(session) == REVISION
        assert TABLE in public_tables(session)
        assert GRANT_FK in object_names(session, ["usage_grants"])
        left = session.execute(
            sa.text("SELECT count(*) FROM usage_grants WHERE teacher_member_id = :m"),
            {"m": member},
        ).scalar_one()
        assert left == 1


def test_upgrade_downgrade_upgrade_round_trip(
    migrated_sessionmaker_with_downgrade: tuple[sessionmaker[Session], Callable[[str], None]],
) -> None:
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    teacher, helper, child = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with sm.begin() as session:
        for uid, role in ((teacher, "teacher"), (helper, "teacher"), (child, "student")):
            session.execute(
                sa.text("INSERT INTO users (id, email, role) VALUES (:u, :e, :r)"),
                {"u": uid, "e": f"{uid}@example.com", "r": role},
            )
        session.execute(
            sa.text(
                "INSERT INTO teacher_members (teacher_user_id, member_user_id, kind, "
                "role_preset, permissions) VALUES (:t, :h, 'assistant', 'marker', '{}')"
            ),
            {"t": teacher, "h": helper},
        )
        session.execute(
            sa.text(
                "INSERT INTO invites (code, role, created_by, team_teacher_id, assistant_role, "
                "expires_at) VALUES ('ASSIST0001', 'assistant', :t, :t, 'viewer', now())"
            ),
            {"t": teacher},
        )
        session.execute(
            sa.text(
                "INSERT INTO invites (code, role, created_by, child_id) "
                "VALUES ('PARENT0001', 'parent', :c, :c)"
            ),
            {"c": child},
        )

    downgrade_to(DOWN_REVISION)

    with sm() as session:
        assert current_revision(session) == DOWN_REVISION
        assert TABLE not in public_tables(session)
        codes = set(session.execute(sa.text("SELECT code FROM invites")).scalars())
        assert codes == {"PARENT0001"}  # assistant invites cannot satisfy the old target check
        assert not (INVITE_OBJECTS - {"ck_invites_target"}) & object_names(session, ["invites"])
        assert not INVITE_COLUMNS & column_names(session, "invites")
        assert GRANT_FK not in object_names(session, ["usage_grants"])
        # The enums are gone, and ``inviterole`` is back to its three labels.
        assert not any(type_exists(session, name) for name in NEW_TYPES)
        assert enum_labels(session, "inviterole") == PREVIOUS_INVITE_ROLE_LABELS
    # The old narrow target check is the one in force again.
    with pytest.raises(IntegrityError, match="ck_invites_target"), sm.begin() as session:
        session.execute(
            sa.text(
                "INSERT INTO invites (code, role, created_by) VALUES ('NOTARGET02', 'student', :t)"
            ),
            {"t": teacher},
        )

    upgrade_head()

    with sm() as session:
        assert object_names(session, [TABLE]) == _orm_names()
        assert object_names(session, ["invites"]) >= INVITE_OBJECTS
        assert GRANT_FK in object_names(session, ["usage_grants"])
        assert "assistant" in enum_labels(session, "inviterole")
        assert all(type_exists(session, name) for name in NEW_TYPES)
        # The surviving parent invite still satisfies the widened checks.
        codes = set(session.execute(sa.text("SELECT code FROM invites")).scalars())
        assert codes == {"PARENT0001"}
