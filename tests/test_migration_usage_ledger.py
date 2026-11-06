"""Migration 0052_usage_ledger: the usage ledger (Paymob billing spec §4.1, §4.5).

The expected constraint and index names come from the ORM
(``lemely/db/models/usage.py``), so these tests compare the migration with an
independent declaration. The trigger must exist on the migrated schema too,
not only on ``create_all`` databases. A downgrade to 0051 must drop the ledger
and leave 0051's schema in place. Nothing here assumes 0052 is the head, so later
migrations (0053-0057) do not have to edit this file.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.exc import DBAPIError, IntegrityError

from lemely.db.base import Base
from lemely.db.models import import_all_models
from tests.test_migration_tutoring_enums import (
    current_revision,
    enum_labels,
    object_names,
    public_tables,
    type_exists,
    upgrade_head,
)
from tests.usage_db import usage_database

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from sqlalchemy.orm import Session, sessionmaker

import_all_models()

REVISION = "0052_usage_ledger"
DOWN_REVISION = "0051_tutor_evidence_uploads"
TABLES = [
    "usage_rates",
    "usage_estimators",
    "usage_grants",
    "usage_grant_balances",
    "usage_jobs",
    "usage_debts",
    "usage_entries",
]
ENUMS = {
    "grantkind": [
        "period_allowance",
        "seat_allowance",
        "signup",
        "credit_pack",
        "auto_topup",
        "refund",
        "adjustment",
    ],
    "usagejobstatus": ["open", "settled", "released", "expired"],
    "usageentrykind": [
        "grant",
        "hold",
        "release",
        "settle",
        "expire",
        "refund",
        "adjust",
        "debt",
        "debt_repay",
    ],
    "estimatorinputkind": ["pages", "marks", "questions", "none"],
}


def _orm_names() -> set[str]:
    names: set[str] = set()
    for name in TABLES:
        table = Base.metadata.tables[name]
        names |= {str(constraint.name) for constraint in table.constraints}
        names |= {str(index.name) for index in table.indexes}
    return names


def _trigger_names(session: Session) -> set[str]:
    return set(
        session.execute(
            sa.text(
                "SELECT tgname FROM pg_trigger WHERE tgrelid = 'usage_entries'::regclass "
                "AND NOT tgisinternal"
            )
        ).scalars()
    )


def test_revision_chains_from_0051() -> None:
    script_dir = ScriptDirectory.from_config(Config("alembic.ini"))
    revision = script_dir.get_revision(REVISION)
    assert revision is not None
    assert revision.down_revision == DOWN_REVISION
    assert len(REVISION) <= 32  # alembic_version.version_num is varchar(32)
    lineage = {r.revision for r in script_dir.iterate_revisions("heads", "base")}
    assert REVISION in lineage


def test_orm_names_are_non_vacuous() -> None:
    names = _orm_names()
    assert "uq_usage_grants_owner_idempotency" in names
    assert "ck_usage_grant_balances_held_within_remaining" in names
    assert "uq_usage_entries_debt_key_kind" in names
    assert "ck_usage_grants_credit_visible" in names
    assert "ix_usage_entries_debt" in names
    assert "ix_usage_debts_job" in names
    # At least the 51 objects 0052 creates; 0053-0055 add foreign keys on usage_grants.
    assert len(names) >= 51


def test_tables_constraints_enums_and_trigger_present(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    with migrated_sessionmaker() as session:
        assert set(TABLES) <= public_tables(session)
        assert object_names(session, TABLES) == _orm_names()
        for name, labels in ENUMS.items():
            assert enum_labels(session, name) == labels
        assert _trigger_names(session) == {"trg_usage_entries_append_only"}


def _index_columns(session: Session, name: str) -> list[str]:
    """The index's key columns in order, from the catalogue."""
    return list(
        session.execute(
            sa.text(
                "SELECT pg_get_indexdef(i.indexrelid, k.n, true) "
                "FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
                "CROSS JOIN LATERAL generate_series(1, i.indnkeyatts) AS k(n) "
                "WHERE c.relname = :name ORDER BY k.n"
            ),
            {"name": name},
        ).scalars()
    )


def test_migrated_indexes_match_the_spend_order_and_foreign_key_lookups(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """Names alone do not prove column order: read the key columns from the catalogue."""
    with migrated_sessionmaker() as session:
        assert _index_columns(session, "ix_usage_grants_owner_spend") == [
            "owner_user_id",
            "priority",
            "expires_at",
            "effective_at",
            "id",
        ]
        options = session.execute(
            sa.text(
                "SELECT i.indoption::text FROM pg_index i "
                "JOIN pg_class c ON c.oid = i.indexrelid "
                "WHERE c.relname = 'ix_usage_grants_owner_spend'"
            )
        ).scalar_one()
        # 0 = ASC NULLS LAST on every key column (no DESC, no NULLS FIRST).
        assert options.split() == ["0"] * 5
        assert _index_columns(session, "ix_usage_entries_debt") == ["debt_id"]
        assert _index_columns(session, "ix_usage_debts_job") == ["job_id"]


def schema_dump(
    session: Session,
    tables: Sequence[str],
    *,
    enums: Sequence[str] = (),
    trigger_table: str | None = None,
    functions: Sequence[str] = (),
) -> dict[str, list[tuple[str, ...]]]:
    """Catalogue definitions of ``tables`` and the objects around them, as comparable rows.

    Reusable by later phases: pass their tables (and enums, trigger table, functions).
    Everything comes from ``information_schema`` and ``pg_catalog``, so a migrated
    database and a ``create_all`` database give equal dumps exactly when they have the
    same schema.
    """
    params = {"t": list(tables), "e": list(enums), "f": list(functions)}
    queries: dict[str, str] = {
        "columns": (
            "SELECT table_name, column_name, data_type, udt_name, is_nullable, column_default, "
            "numeric_precision, numeric_scale FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = ANY(:t)"
        ),
        "constraints": (
            "SELECT t.relname, c.conname, pg_get_constraintdef(c.oid) FROM pg_constraint c "
            "JOIN pg_class t ON t.oid = c.conrelid WHERE t.relname = ANY(:t)"
        ),
        "indexes": (
            "SELECT tablename, indexname, indexdef FROM pg_indexes "
            "WHERE schemaname = 'public' AND tablename = ANY(:t)"
        ),
        "enums": (
            "SELECT t.typname, array_agg(e.enumlabel ORDER BY e.enumsortorder)::text "
            "FROM pg_type t JOIN pg_enum e ON e.enumtypid = t.oid "
            "WHERE t.typname = ANY(:e) GROUP BY t.typname"
        ),
        "functions": (
            "SELECT p.proname, pg_get_functiondef(p.oid) FROM pg_proc p WHERE p.proname = ANY(:f)"
        ),
    }
    dump = {
        name: sorted(
            tuple("" if v is None else str(v) for v in row)
            for row in session.execute(sa.text(sql), params)
        )
        for name, sql in queries.items()
    }
    triggers: list[tuple[str, ...]] = []
    if trigger_table is not None:
        triggers = [
            (str(name), str(definition))
            for name, definition in session.execute(
                sa.text(
                    "SELECT tgname, pg_get_triggerdef(oid) FROM pg_trigger "
                    "WHERE tgrelid = to_regclass(:tbl) AND NOT tgisinternal"
                ),
                {"tbl": trigger_table},
            )
        ]
    dump["triggers"] = sorted(triggers)
    return dump


def test_migrated_schema_equals_the_create_all_schema(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """Parity: the migration builds what the models declare, definition by definition.

    ``_orm_names`` compares names only; this compares column types, nullability and
    defaults, CHECK/FK/unique definitions, index definitions, enum labels, and the
    trigger and its function against a database built by ``create_all``.
    """
    kwargs = {
        "enums": list(ENUMS),
        "trigger_table": "usage_entries",
        "functions": ["usage_entries_reject_mutation"],
    }
    with migrated_sessionmaker() as session:
        migrated = schema_dump(session, TABLES, **kwargs)
    with usage_database() as orm_sessionmaker, orm_sessionmaker() as session:
        orm = schema_dump(session, TABLES, **kwargs)
    # Non-vacuous: every section found something to compare.
    assert all(migrated[section] for section in migrated)
    for section, rows in migrated.items():
        assert rows == orm[section], section


def test_migrated_credit_grants_must_be_visible(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    user_id = uuid.uuid4()
    with migrated_sessionmaker.begin() as session:
        session.execute(
            sa.text("INSERT INTO users (id, email, role) VALUES (:u, :e, 'student')"),
            {"u": user_id, "e": f"{user_id}@example.com"},
        )
    for kind in ("credit_pack", "auto_topup"):
        with (
            pytest.raises(IntegrityError, match="ck_usage_grants_credit_visible"),
            migrated_sessionmaker.begin() as session,
        ):
            session.execute(
                sa.text(
                    "INSERT INTO usage_grants (owner_user_id, kind, visible, priority, units, "
                    "idempotency_key) VALUES (:u, :k, false, 50, 10, :key)"
                ),
                {"u": user_id, "k": kind, "key": f"hidden-{kind}"},
            )


def test_migrated_trigger_rejects_update_and_delete(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    user_id, grant_id = uuid.uuid4(), uuid.uuid4()
    with migrated_sessionmaker.begin() as session:
        session.execute(
            sa.text("INSERT INTO users (id, email, role) VALUES (:u, :e, 'student')"),
            {"u": user_id, "e": f"{user_id}@example.com"},
        )
        session.execute(
            sa.text(
                "INSERT INTO usage_grants (id, owner_user_id, kind, visible, priority, units, "
                "idempotency_key) VALUES (:g, :u, 'signup', false, 20, 10, 'signup')"
            ),
            {"g": grant_id, "u": user_id},
        )
        session.execute(
            sa.text(
                "INSERT INTO usage_entries (grant_id, kind, units, event_at, idempotency_key) "
                "VALUES (:g, 'grant', 10, now(), 'signup')"
            ),
            {"g": grant_id},
        )
    for statement in (
        "UPDATE usage_entries SET units = 11",
        "DELETE FROM usage_entries",
    ):
        with pytest.raises(DBAPIError, match="append-only"), migrated_sessionmaker.begin() as s:
            s.execute(sa.text(statement))


def test_upgrade_downgrade_upgrade_round_trip(
    migrated_sessionmaker_with_downgrade: tuple[sessionmaker[Session], Callable[[str], None]],
) -> None:
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    with sm() as session:
        before = public_tables(session)

    downgrade_to(DOWN_REVISION)

    with sm() as session:
        assert current_revision(session) == DOWN_REVISION
        # Later revisions' tables are gone too; only "0052's are gone" is this test's claim.
        assert set(TABLES).isdisjoint(public_tables(session))
        assert "tutor_evidence_uploads" in public_tables(session)
        for name in ENUMS:
            assert not type_exists(session, name)
        assert not session.execute(
            sa.text("SELECT count(*) FROM pg_proc WHERE proname = 'usage_entries_reject_mutation'")
        ).scalar_one()

    upgrade_head()

    with sm() as session:
        assert public_tables(session) == before
        assert object_names(session, TABLES) == _orm_names()
        assert _trigger_names(session) == {"trg_usage_entries_append_only"}
