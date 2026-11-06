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

if TYPE_CHECKING:
    from collections.abc import Callable

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


def test_migrated_indexes_match_the_spend_order_and_foreign_key_lookups(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """Names alone do not prove column order: read the key columns from the catalogue."""
    with migrated_sessionmaker() as session:
        spend = session.execute(
            sa.text(
                "SELECT pg_get_indexdef(i.indexrelid, k.n, true), i.indoption::text "
                "FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
                "CROSS JOIN LATERAL generate_series(1, i.indnkeyatts) AS k(n) "
                "WHERE c.relname = 'ix_usage_grants_owner_spend' ORDER BY k.n"
            )
        ).all()
        assert [row[0] for row in spend] == [
            "owner_user_id",
            "priority",
            "expires_at",
            "effective_at",
            "id",
        ]
        # 0 = ASC NULLS LAST on every key column (no DESC, no NULLS FIRST).
        assert spend[0][1].split() == ["0"] * 5
        for index, column in (
            ("ix_usage_entries_debt", "debt_id"),
            ("ix_usage_debts_job", "job_id"),
        ):
            definition = session.execute(
                sa.text("SELECT indexdef FROM pg_indexes WHERE indexname = :n"), {"n": index}
            ).scalar_one()
            assert f"({column})" in definition


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
