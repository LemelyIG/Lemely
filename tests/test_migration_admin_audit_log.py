"""Migration 0057_admin_audit_log: the admin audit log and the tables Phase 07 owns.

Expected names come from the ORM (``lemely/db/models/admin_audit.py`` and ``billing_ops.py``),
so these tests compare the migration with an independent declaration, and ``schema_dump``
compares the migrated schema with a ``create_all`` database definition by definition. The
downgrade must remove exactly what the upgrade added, and refuses while the audit log, a
refund or a signup-allowance off period exists. Nothing here assumes 0057 is the head.
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
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import DBAPIError, IntegrityError

from lemely.db.admin_billing_repo import idempotency_lookup
from lemely.db.base import Base
from lemely.db.models import import_all_models
from tests.admin_billing_db import billing_database
from tests.test_migration_tutoring_enums import (
    column_names,
    current_revision,
    head_revision,
    object_names,
    public_tables,
    upgrade_head,
)
from tests.test_migration_usage_ledger import schema_dump

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session, sessionmaker

import_all_models()

REVISION = "0057_admin_audit_log"
DOWN_REVISION = "0056_auto_topup"
MIGRATION_FILE = (
    Path(__file__).parents[1]
    / "lemely"
    / "db"
    / "migrations"
    / "versions"
    / "0057_admin_audit_log.py"
)
NEW_TABLES = (
    "admin_audit_log",
    "job_runs",
    "paymob_webhook_failures",
    "payment_refunds",
    "usage_job_model_costs",
    "credit_conversion_rates",
    "signup_allowance_off_periods",
    "billing_settings",
    "plan_tier_terms",
    "llm_price_overrides",
)
#: Indexes 0057 adds to tables other phases own.
FOREIGN_INDEXES = {
    "ix_admin_usage_jobs_created_at",
    "ix_admin_usage_jobs_action_estimator",
    "ix_admin_payments_paid_at",
    "ix_admin_payments_status_created_at",
    "ix_admin_usage_entries_kind_event_at",
    "ix_admin_paymob_events_created_at",
}
NEW_ENUMS = ("refundkind", "refundstatus")
#: Every table 0057 creates or alters, for the parity check.
PARITY_TABLES = (
    *NEW_TABLES,
    "plan_tiers",
    "credit_packs",
    "payments",
    "subscriptions",
    "subscription_periods",
    "usage_jobs",
    "usage_entries",
)
PARITY_TABLES_WITH_EVENTS = (*PARITY_TABLES, "paymob_events")
PLAN_TIER_COLUMNS = {
    "paymob_plan_synced_price_minor",
    "paymob_plan_synced_frequency",
    "paymob_plan_synced_retrial_days",
    "version",
    "terms_version",
}
SUBSCRIPTION_COLUMNS = {
    "terms_version",
    "pending_terms_version",
    "pending_terms_effective_at",
    "terms_notice_sent_at",
}
#: Tables that carry a trigger this revision installs, and the functions behind them.
TRIGGER_TABLES = ("admin_audit_log", "plan_tier_terms", "plan_tiers")
FUNCTIONS = ("admin_audit_log_append_only", "plan_tiers_seed_terms")
TRIGGERS = {
    "trg_admin_audit_log_append_only",
    "trg_plan_tier_terms_append_only",
    "trg_plan_tiers_seed_terms",
}
TRIGGER = "trg_admin_audit_log_append_only"
FUNCTION = "admin_audit_log_append_only"


@pytest.fixture
def migrated_sessionmaker_with_downgrade(
    migrated_sessionmaker_with_downgrade: tuple[sessionmaker[Session], Callable[[str], None]],
) -> tuple[sessionmaker[Session], Callable[[str], None]]:
    """The conftest fixture, stepped back to 0057 first.

    It migrates to the head and later revisions sit above 0057. ``env.py`` runs one downgrade in
    one transaction, so a refusal at 0057 would also undo the later revisions' downgrades and
    leave the database at the head, not at 0057. Starting at 0057 keeps these tests about 0057
    (the 0056 file does the same by stepping back first).
    """
    _, downgrade_to = migrated_sessionmaker_with_downgrade
    downgrade_to(REVISION)
    return migrated_sessionmaker_with_downgrade


def _orm_names(tables: tuple[str, ...]) -> set[str]:
    names: set[str] = set()
    for name in tables:
        table = Base.metadata.tables[name]
        names |= {str(c.name) for c in table.constraints}
        names |= {str(i.name) for i in table.indexes}
    return names


def _indexes(session: Session) -> set[str]:
    return set(
        session.execute(sa.text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'"))
        .scalars()
        .all()
    )


def _enums(session: Session) -> set[str]:
    return set(
        session.execute(sa.text("SELECT typname FROM pg_type WHERE typtype = 'e'")).scalars()
    )


def _function_count(session: Session) -> int:
    return session.execute(
        sa.text("SELECT count(*) FROM pg_proc WHERE proname = :n"), {"n": FUNCTION}
    ).scalar_one()


def _function_names(session: Session) -> set[str]:
    return set(session.execute(sa.text("SELECT proname FROM pg_proc")).scalars())


def _trigger_names(session: Session) -> set[str]:
    return set(
        session.execute(sa.text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal")).scalars()
    )


def _user(sm: sessionmaker[Session], role: str = "platform_admin") -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.execute(
            sa.text("INSERT INTO users (id, email, role) VALUES (:u, :e, :r)"),
            {"u": uid, "e": f"{uid}@example.com", "r": role},
        )
    return uid


def _audit_row(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    with sm.begin() as session:
        session.execute(
            sa.text(
                "INSERT INTO admin_audit_log (admin_user_id, action, target_kind, target_id, "
                "reason) VALUES (:a, 'customer.grant', 'user', :t, 'why')"
            ),
            {"a": admin, "t": uuid.uuid4()},
        )


def _payment(sm: sessionmaker[Session], payer: uuid.UUID) -> uuid.UUID:
    pid = uuid.uuid4()
    with sm.begin() as session:
        session.execute(
            sa.text(
                "INSERT INTO payments (id, payer_user_id, beneficiary_user_id, purpose, "
                "amount_minor, special_reference) "
                "VALUES (:id, :u, :u, 'extra_seats', 5000, :ref)"
            ),
            {"id": pid, "u": payer, "ref": str(pid)},
        )
    return pid


def _refund_row(
    sm: sessionmaker[Session], payment: uuid.UUID, admin: uuid.UUID, **overrides: object
) -> uuid.UUID:
    values: dict[str, object] = {
        "id": uuid.uuid4(),
        "p": payment,
        "a": admin,
        "amount": 1000,
        "clawed": 0,
        **overrides,
    }
    with sm.begin() as session:
        session.execute(
            sa.text(
                "INSERT INTO payment_refunds (id, payment_id, admin_user_id, kind, amount_minor, "
                "reason, clawed_back_units) "
                "VALUES (:id, :p, :a, 'refund', :amount, 'why', :clawed)"
            ),
            values,
        )
    return uuid.UUID(str(values["id"]))


def _pack(sm: sessionmaker[Session], code: str = "signup_student", units: int = 250) -> uuid.UUID:
    pid = uuid.uuid4()
    with sm.begin() as session:
        session.execute(
            sa.text(
                "INSERT INTO credit_packs (id, code, name, units, price_minor, is_active) "
                "VALUES (:id, :c, :c, :u, 0, false)"
            ),
            {"id": pid, "c": code, "u": units},
        )
    return pid


def _off_period(
    sm: sessionmaker[Session],
    pack: uuid.UUID,
    start: datetime,
    end: datetime | None = None,
) -> None:
    with sm.begin() as session:
        session.execute(
            sa.text(
                "INSERT INTO signup_allowance_off_periods (credit_pack_id, off_from, off_until) "
                "VALUES (:p, :s, :e)"
            ),
            {"p": pack, "s": start, "e": end},
        )


def _tier(sm: sessionmaker[Session], code: str = "pro", price: int = 5000) -> uuid.UUID:
    tid = uuid.uuid4()
    with sm.begin() as session:
        session.execute(
            sa.text(
                "INSERT INTO plan_tiers (id, code, name, price_minor, allowance_units, "
                "included_seats, seat_allowance_units, extra_seat_price_minor) "
                "VALUES (:id, :c, :c, :p, 700, 3, 200, 900)"
            ),
            {"id": tid, "c": code, "p": price},
        )
    return tid


def _subscription(
    sm: sessionmaker[Session], user: uuid.UUID, tier: uuid.UUID, **columns: object
) -> uuid.UUID:
    sid = uuid.uuid4()
    names = ["id", "user_id", "plan_tier_id", *columns]
    marks = ", ".join(f":{n}" for n in names)
    with sm.begin() as session:
        session.execute(
            sa.text(f"INSERT INTO subscriptions ({', '.join(names)}) VALUES ({marks})"),  # noqa: S608
            {"id": sid, "user_id": user, "plan_tier_id": tier, **columns},
        )
    return sid


def _terms_v2(sm: sessionmaker[Session], tier: uuid.UUID, price: int = 6000) -> None:
    with sm.begin() as session:
        session.execute(
            sa.text(
                "INSERT INTO plan_tier_terms (plan_tier_id, terms_version, price_minor, "
                "extra_seat_price_minor, allowance_units, included_seats, seat_allowance_units) "
                "VALUES (:t, 2, :p, 900, 700, 3, 200)"
            ),
            {"t": tier, "p": price},
        )


T0 = datetime(2026, 11, 1, tzinfo=UTC)
T1 = datetime(2026, 11, 8, tzinfo=UTC)


def test_revision_chains_from_0056_and_is_in_the_history() -> None:
    """Index R10: assert lineage and a single head, never "is the head" (later migrations)."""
    script_dir = ScriptDirectory.from_config(Config("alembic.ini"))
    revision = script_dir.get_revision(REVISION)
    assert revision is not None
    assert revision.down_revision == DOWN_REVISION
    assert len(REVISION) <= 32  # alembic_version.version_num is varchar(32)
    assert len(script_dir.get_heads()) == 1
    assert REVISION in {r.revision for r in script_dir.walk_revisions()}


def test_orm_declares_the_named_objects() -> None:
    declared = {str(i.name) for t in Base.metadata.tables.values() for i in t.indexes}
    assert declared >= FOREIGN_INDEXES
    names = _orm_names(NEW_TABLES)
    assert "ck_admin_audit_log_reason_required" in names
    assert "ix_admin_audit_log_idempotency" in names
    assert "uq_usage_job_model_costs_usage_job_id" in names
    assert "uq_signup_allowance_off_periods_open" in names
    assert "ck_credit_conversion_rates_rate_positive" in names
    assert "uq_credit_conversion_rates_currency" in names
    assert {c.name for c in Base.metadata.tables["plan_tiers"].columns} >= PLAN_TIER_COLUMNS
    assert "callback_received_at" in {c.name for c in Base.metadata.tables["payments"].columns}


def test_new_objects_exist_with_the_orm_names(migrated_sessionmaker: sessionmaker[Session]) -> None:
    with migrated_sessionmaker() as session:
        assert set(NEW_TABLES) <= public_tables(session)
        assert object_names(session, NEW_TABLES) == _orm_names(NEW_TABLES)
        assert _indexes(session) >= FOREIGN_INDEXES
        assert column_names(session, "plan_tiers") >= PLAN_TIER_COLUMNS
        assert "callback_received_at" in column_names(session, "payments")
        assert column_names(session, "subscriptions") >= SUBSCRIPTION_COLUMNS
        assert "terms_version" in column_names(session, "subscription_periods")
        assert {"version", "signup_validity_days"} <= column_names(session, "credit_packs")
        assert set(NEW_ENUMS) <= _enums(session)


def test_migrated_schema_equals_the_create_all_schema(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """Parity: the migration builds what the models declare, definition by definition.

    Covers every table 0057 creates, the columns it adds to ``plan_tiers``, ``credit_packs``,
    ``payments``, ``subscriptions`` and ``subscription_periods`` (with the composite foreign
    keys), the indexes it adds to ``usage_jobs``, ``payments``, ``usage_entries``,
    ``subscriptions`` and ``paymob_events``, both enums, and the three triggers and their
    functions, against a ``create_all`` database.
    A model and the migration that disagree by one column type, default, CHECK or index
    predicate make this fail.
    """

    def dump(session: Session) -> dict[str, list[tuple[str, ...]]]:
        result = schema_dump(
            session, PARITY_TABLES_WITH_EVENTS, enums=list(NEW_ENUMS), functions=list(FUNCTIONS)
        )
        result["triggers"] = sorted(
            row
            for table in TRIGGER_TABLES
            for row in schema_dump(session, (), trigger_table=table)["triggers"]
        )
        return result

    with migrated_sessionmaker() as session:
        migrated = dump(session)
    with billing_database() as orm_sessionmaker, orm_sessionmaker() as session:
        orm = dump(session)
    # Non-vacuous: every section found something, and this revision's objects are compared.
    assert all(migrated[section] for section in migrated)
    assert {name for name, _definition in migrated["triggers"]} == TRIGGERS
    assert len(migrated["functions"]) == len(FUNCTIONS)
    assert any(row[1] == "pending_terms_version" for row in migrated["columns"])
    assert any(row[1] == "signup_validity_days" for row in migrated["columns"])
    assert any(row[0] == "billing_settings" for row in migrated["columns"])
    index_rows = " ".join(" ".join(row) for row in migrated["indexes"])
    for name in FOREIGN_INDEXES | {"ix_admin_audit_log_idempotency"}:
        assert name in index_rows, name
    assert any(row[1] == "callback_received_at" for row in migrated["columns"])
    assert any(row[1] == "paymob_plan_synced_price_minor" for row in migrated["columns"])
    for section, rows in migrated.items():
        assert rows == orm[section], section


def test_the_idempotency_index_is_partial_on_the_key_expression(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    with migrated_sessionmaker() as session:
        definition = session.execute(
            sa.text("SELECT indexdef FROM pg_indexes WHERE indexname = :n"),
            {"n": "ix_admin_audit_log_idempotency"},
        ).scalar_one()
    assert definition.startswith("CREATE UNIQUE INDEX")
    assert "(action, ((after ->> 'idempotency_key'::text)))" in definition
    assert "WHERE (after ? 'idempotency_key'::text)" in definition


def test_the_idempotency_lookup_is_served_by_its_index(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """``already_applied`` runs under the idempotency lock on every admin write (DV-13)."""
    statement = idempotency_lookup("customer.grant", "admin-grant:u:r")
    with migrated_sessionmaker() as session:
        session.execute(sa.text("SET LOCAL enable_seqscan = off"))
        compiled = statement.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
        plan = "\n".join(session.execute(sa.text(f"EXPLAIN {compiled}")).scalars().all())
    assert "ix_admin_audit_log_idempotency" in plan


@pytest.mark.parametrize(
    "statement",
    ["UPDATE admin_audit_log SET reason = 'rewritten'", "DELETE FROM admin_audit_log"],
)
def test_migrated_audit_log_is_append_only(
    migrated_sessionmaker: sessionmaker[Session], statement: str
) -> None:
    admin = _user(migrated_sessionmaker)
    _audit_row(migrated_sessionmaker, admin)
    with pytest.raises(DBAPIError, match="append-only"), migrated_sessionmaker.begin() as s:
        s.execute(sa.text(statement))
    with migrated_sessionmaker() as session:
        assert session.execute(sa.text("SELECT reason FROM admin_audit_log")).scalar_one() == "why"
        triggers = set(
            session.execute(
                sa.text(
                    "SELECT tgname FROM pg_trigger WHERE tgrelid = 'admin_audit_log'::regclass "
                    "AND NOT tgisinternal"
                )
            ).scalars()
        )
    assert triggers == {TRIGGER}


def test_a_blank_reason_is_refused_by_the_migrated_database(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    admin = _user(migrated_sessionmaker)
    with pytest.raises(IntegrityError, match="reason_required"), migrated_sessionmaker.begin() as s:
        s.execute(
            sa.text(
                "INSERT INTO admin_audit_log (admin_user_id, action, target_kind, target_id, "
                "reason) VALUES (:a, 'customer.grant', 'user', :t, E' \\t\\n ')"
            ),
            {"a": admin, "t": uuid.uuid4()},
        )


def test_deleting_an_admin_with_audit_rows_is_refused(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    admin = _user(migrated_sessionmaker)
    _audit_row(migrated_sessionmaker, admin)
    with pytest.raises(IntegrityError), migrated_sessionmaker.begin() as session:
        session.execute(sa.text("DELETE FROM users WHERE id = :u"), {"u": admin})


def test_the_webhook_failure_table_has_no_body_column(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """DV-6: kind, a fixed reason, a best-effort address and the arrival time; never a payload."""
    with migrated_sessionmaker() as session:
        assert column_names(session, "paymob_webhook_failures") == {
            "id",
            "kind",
            "reason",
            "remote_addr",
            "received_at",
        }


@pytest.mark.parametrize("kind", ["transaction", "token", "subscription"])
def test_a_known_webhook_failure_kind_is_stored(
    migrated_sessionmaker: sessionmaker[Session], kind: str
) -> None:
    with migrated_sessionmaker.begin() as session:
        session.execute(
            sa.text(
                "INSERT INTO paymob_webhook_failures (kind, reason) VALUES (:k, 'hmac_mismatch')"
            ),
            {"k": kind},
        )


def test_an_unknown_webhook_failure_kind_is_refused(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    with pytest.raises(IntegrityError, match="kind_known"), migrated_sessionmaker.begin() as s:
        s.execute(
            sa.text("INSERT INTO paymob_webhook_failures (kind, reason) VALUES ('other', 'x')")
        )


def test_a_webhook_failure_address_is_capped_at_64_characters(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    with pytest.raises(DBAPIError), migrated_sessionmaker.begin() as session:
        session.execute(
            sa.text(
                "INSERT INTO paymob_webhook_failures (kind, reason, remote_addr) "
                "VALUES ('token', 'hmac_missing', :addr)"
            ),
            {"addr": "x" * 65},
        )


def test_job_runs_are_one_row_per_name_and_the_error_is_capped(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    insert = sa.text(
        "INSERT INTO job_runs (name, last_started_at, last_outcome, last_error) "
        "VALUES (:n, now(), :o, :e)"
    )
    with migrated_sessionmaker.begin() as session:
        session.execute(insert, {"n": "billing.reconcile", "o": "ok", "e": "x" * 200})
    with pytest.raises(IntegrityError), migrated_sessionmaker.begin() as session:
        session.execute(insert, {"n": "billing.reconcile", "o": "failed", "e": None})
    with pytest.raises(DBAPIError), migrated_sessionmaker.begin() as session:
        session.execute(insert, {"n": "billing.other", "o": "failed", "e": "x" * 201})
    with migrated_sessionmaker() as session:
        row = session.execute(
            sa.text(
                "SELECT total_runs, total_failures, consecutive_failures, last_finished_at "
                "FROM job_runs"
            )
        ).one()
    assert tuple(row) == (0, 0, 0, None)


def test_job_runs_refuse_an_unknown_outcome_and_a_negative_streak(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    with pytest.raises(IntegrityError, match="outcome_known"), migrated_sessionmaker.begin() as s:
        s.execute(
            sa.text(
                "INSERT INTO job_runs (name, last_started_at, last_outcome) "
                "VALUES ('a', now(), 'skipped')"
            )
        )
    with (
        pytest.raises(IntegrityError, match="failures_non_negative"),
        migrated_sessionmaker.begin() as s,
    ):
        s.execute(
            sa.text(
                "INSERT INTO job_runs (name, last_started_at, consecutive_failures) "
                "VALUES ('b', now(), -1)"
            )
        )


def test_a_refund_amount_must_be_positive_and_a_clawback_non_negative(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    admin = _user(migrated_sessionmaker)
    payment = _payment(migrated_sessionmaker, admin)
    with pytest.raises(IntegrityError, match="amount_positive"):
        _refund_row(migrated_sessionmaker, payment, admin, amount=0)
    with pytest.raises(IntegrityError, match="clawback_non_negative"):
        _refund_row(migrated_sessionmaker, payment, admin, clawed=-1)
    _refund_row(migrated_sessionmaker, payment, admin)


def test_a_new_refund_is_requested_and_keeps_the_money_only_default(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """UD-4: the admin's "reverse the change" choice is stored on the row written before the
    Paymob call, so the closing transaction (or an inquiry hours later) still knows it."""
    admin = _user(migrated_sessionmaker)
    payment = _payment(migrated_sessionmaker, admin)
    refund = _refund_row(migrated_sessionmaker, payment, admin)
    with migrated_sessionmaker() as session:
        row = session.execute(
            sa.text("SELECT status::text, reverse_change FROM payment_refunds WHERE id = :i"),
            {"i": refund},
        ).one()
    assert tuple(row) == ("requested", False)


def test_a_payment_or_admin_with_refunds_cannot_be_deleted(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    admin = _user(migrated_sessionmaker)
    payment = _payment(migrated_sessionmaker, admin)
    _refund_row(migrated_sessionmaker, payment, admin)
    with pytest.raises(IntegrityError), migrated_sessionmaker.begin() as session:
        session.execute(sa.text("DELETE FROM payments WHERE id = :p"), {"p": payment})
    with pytest.raises(IntegrityError), migrated_sessionmaker.begin() as session:
        session.execute(sa.text("DELETE FROM users WHERE id = :u"), {"u": admin})


def _rate(
    sm: sessionmaker[Session], currency: str, rate: str, admin: uuid.UUID | None = None
) -> None:
    with sm.begin() as session:
        session.execute(
            sa.text(
                "INSERT INTO credit_conversion_rates (currency, units_per_minor, updated_by) "
                "VALUES (:c, :r, :a)"
            ),
            {"c": currency, "r": rate, "a": admin},
        )


def test_a_conversion_rate_must_be_positive(migrated_sessionmaker: sessionmaker[Session]) -> None:
    """UD-12: the admin-set conversion rate is units per minor currency unit, always > 0."""
    for bad in ("0", "-0.5"):
        with (
            pytest.raises(IntegrityError, match="rate_positive"),
            migrated_sessionmaker.begin() as session,
        ):
            session.execute(
                sa.text(
                    "INSERT INTO credit_conversion_rates (currency, units_per_minor) "
                    "VALUES ('EGP', :r)"
                ),
                {"r": bad},
            )
    _rate(migrated_sessionmaker, "EGP", "0.000001")


@pytest.mark.parametrize("currency", ["egp", "EG", "EGPP", "E1P", ""])
def test_a_conversion_rate_currency_must_be_an_uppercase_code(
    migrated_sessionmaker: sessionmaker[Session], currency: str
) -> None:
    with pytest.raises(DBAPIError), migrated_sessionmaker.begin() as session:
        session.execute(
            sa.text(
                "INSERT INTO credit_conversion_rates (currency, units_per_minor) VALUES (:c, 1)"
            ),
            {"c": currency},
        )


def test_there_is_one_conversion_rate_per_currency_and_it_stays_exact(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    _rate(migrated_sessionmaker, "EGP", "0.123457")
    _rate(migrated_sessionmaker, "USD", "12.5")
    with pytest.raises(IntegrityError), migrated_sessionmaker.begin() as session:
        session.execute(
            sa.text(
                "INSERT INTO credit_conversion_rates (currency, units_per_minor) VALUES ('EGP', 2)"
            )
        )
    with migrated_sessionmaker() as session:
        stored = dict(
            session.execute(
                sa.text("SELECT currency, units_per_minor::text FROM credit_conversion_rates")
            ).all()
        )
    assert stored == {"EGP": "0.123457", "USD": "12.500000"}


def test_deleting_the_admin_who_set_a_rate_keeps_the_rate(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    admin = _user(migrated_sessionmaker)
    _rate(migrated_sessionmaker, "EGP", "1", admin)
    with migrated_sessionmaker.begin() as session:
        session.execute(sa.text("DELETE FROM users WHERE id = :u"), {"u": admin})
    with migrated_sessionmaker() as session:
        row = session.execute(
            sa.text("SELECT units_per_minor::text, updated_by FROM credit_conversion_rates")
        ).one()
    assert tuple(row) == ("1.000000", None)


def test_the_usage_job_cost_index_is_partial_so_the_history_plan_is_untouched(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """A plain ``created_at`` index on ``usage_jobs`` would win the lead's history query away
    from ``ix_usage_jobs_member_created`` (``test_migration_subscription_periods`` pins that
    plan). The margin query states ``actual_cost_usd IS NOT NULL``, which the history query
    does not, so only the margin query can use this index."""
    with migrated_sessionmaker() as session:
        definition = session.execute(
            sa.text("SELECT indexdef FROM pg_indexes WHERE indexname = :n"),
            {"n": "ix_admin_usage_jobs_created_at"},
        ).scalar_one()
        session.execute(sa.text("SET LOCAL enable_seqscan = off"))
        plan = "\n".join(
            session.execute(
                sa.text(
                    "EXPLAIN SELECT 1 FROM usage_jobs WHERE created_at >= now() "
                    "AND created_at < now() + interval '1 day' AND actual_cost_usd IS NOT NULL"
                )
            )
            .scalars()
            .all()
        )
    assert "WHERE (actual_cost_usd IS NOT NULL)" in definition
    assert "ix_admin_usage_jobs_created_at" in plan


def test_a_signup_off_period_must_end_after_it_starts(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    pack = _pack(migrated_sessionmaker)
    with pytest.raises(IntegrityError, match="window_ordered"):
        _off_period(migrated_sessionmaker, pack, T1, T0)
    _off_period(migrated_sessionmaker, pack, T0, T1)


def test_a_pack_has_at_most_one_open_off_period(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """Off now means one open row; a closed history of earlier windows is unlimited."""
    pack = _pack(migrated_sessionmaker)
    _off_period(migrated_sessionmaker, pack, T0, T1)
    _off_period(migrated_sessionmaker, pack, datetime(2026, 11, 9, tzinfo=UTC), None)
    with pytest.raises(IntegrityError, match="uq_signup_allowance_off_periods_open"):
        _off_period(migrated_sessionmaker, pack, datetime(2026, 11, 10, tzinfo=UTC), None)
    other = _pack(migrated_sessionmaker, "signup_teacher")
    _off_period(migrated_sessionmaker, other, T0, None)


def test_a_pack_with_off_periods_cannot_be_deleted(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    pack = _pack(migrated_sessionmaker)
    _off_period(migrated_sessionmaker, pack, T0, None)
    with pytest.raises(IntegrityError), migrated_sessionmaker.begin() as session:
        session.execute(sa.text("DELETE FROM credit_packs WHERE id = :p"), {"p": pack})


def test_a_model_cost_is_unique_per_job_and_model_and_never_negative(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    actor = _user(migrated_sessionmaker, "student")
    job = uuid.uuid4()
    with migrated_sessionmaker.begin() as session:
        session.execute(
            sa.text(
                "INSERT INTO usage_jobs (id, job_id, actor_user_id, action, estimate_low, "
                "estimate_high, estimator_version, reserved, rate_version, payer_chain, "
                "expires_at) VALUES (:id, :id, :u, 'mark', 0, 10, 1, 10, 1, '[]'::jsonb, now())"
            ),
            {"id": job, "u": actor},
        )
    cost = sa.text(
        "INSERT INTO usage_job_model_costs (usage_job_id, model, cost_usd) VALUES (:j, :m, :c)"
    )
    with migrated_sessionmaker.begin() as session:
        session.execute(cost, {"j": job, "m": "gemini-3-pro", "c": "0.004100"})
        session.execute(cost, {"j": job, "m": "claude-haiku", "c": "0"})
    with pytest.raises(IntegrityError), migrated_sessionmaker.begin() as session:
        session.execute(cost, {"j": job, "m": "gemini-3-pro", "c": "0.001"})
    with (
        pytest.raises(IntegrityError, match="cost_non_negative"),
        migrated_sessionmaker.begin() as session,
    ):
        session.execute(cost, {"j": job, "m": "other", "c": "-0.000001"})
    with migrated_sessionmaker.begin() as session:
        session.execute(sa.text("DELETE FROM usage_jobs WHERE id = :j"), {"j": job})
    with migrated_sessionmaker() as session:
        remaining = session.execute(
            sa.text("SELECT count(*) FROM usage_job_model_costs")
        ).scalar_one()
    assert remaining == 0


def test_downgrade_refuses_while_the_audit_log_has_a_row(
    migrated_sessionmaker_with_downgrade: tuple[sessionmaker[Session], Callable[[str], None]],
) -> None:
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    admin = _user(sm)
    _audit_row(sm, admin)

    with pytest.raises(RuntimeError, match="admin_audit_log"):
        downgrade_to(DOWN_REVISION)

    with sm() as session:
        assert current_revision(session, within=REVISION) == REVISION
        assert set(NEW_TABLES) <= public_tables(session)
        assert session.execute(sa.text("SELECT count(*) FROM admin_audit_log")).scalar_one() == 1
        assert _function_count(session) == 1


def test_downgrade_refuses_while_a_refund_exists(
    migrated_sessionmaker_with_downgrade: tuple[sessionmaker[Session], Callable[[str], None]],
) -> None:
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    admin = _user(sm)
    _refund_row(sm, _payment(sm, admin), admin)

    with pytest.raises(RuntimeError, match="payment_refunds"):
        downgrade_to(DOWN_REVISION)

    with sm() as session:
        assert current_revision(session, within=REVISION) == REVISION
        assert session.execute(sa.text("SELECT count(*) FROM payment_refunds")).scalar_one() == 1


def test_downgrade_refuses_while_a_conversion_rate_exists(
    migrated_sessionmaker_with_downgrade: tuple[sessionmaker[Session], Callable[[str], None]],
) -> None:
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    _rate(sm, "EGP", "0.5")

    with pytest.raises(RuntimeError, match="credit_conversion_rates"):
        downgrade_to(DOWN_REVISION)

    with sm() as session:
        assert current_revision(session, within=REVISION) == REVISION
        assert "credit_conversion_rates" in public_tables(session)


def test_downgrade_refuses_while_a_signup_off_period_exists(
    migrated_sessionmaker_with_downgrade: tuple[sessionmaker[Session], Callable[[str], None]],
) -> None:
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    _off_period(sm, _pack(sm), T0, None)

    with pytest.raises(RuntimeError, match="signup_allowance_off_periods"):
        downgrade_to(DOWN_REVISION)

    with sm() as session:
        assert current_revision(session, within=REVISION) == REVISION
        assert "signup_allowance_off_periods" in public_tables(session)


def test_upgrade_downgrade_upgrade_round_trip(
    migrated_sessionmaker_with_downgrade: tuple[sessionmaker[Session], Callable[[str], None]],
) -> None:
    """With no audit, refund or off-period rows the downgrade drops exactly what 0057 added."""
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    # Operational rows the downgrade may drop without losing money history.
    with sm.begin() as session:
        session.execute(sa.text("INSERT INTO job_runs (name, last_started_at) VALUES ('a', now())"))
        session.execute(
            sa.text("INSERT INTO paymob_webhook_failures (kind, reason) VALUES ('token', 'x')")
        )
    student = _user(sm, "student")
    _payment(sm, student)
    tier = _tier(sm)
    _subscription(sm, student, tier)
    with sm() as session:
        after_upgrade = object_names(session, PARITY_TABLES_WITH_EVENTS)

    downgrade_to(DOWN_REVISION)

    with sm() as session:
        assert current_revision(session, within=REVISION) == DOWN_REVISION
        assert not set(NEW_TABLES) & public_tables(session)
        assert not FOREIGN_INDEXES & _indexes(session)
        assert not set(NEW_ENUMS) & _enums(session)
        assert not PLAN_TIER_COLUMNS & column_names(session, "plan_tiers")
        assert not SUBSCRIPTION_COLUMNS & column_names(session, "subscriptions")
        assert "terms_version" not in column_names(session, "subscription_periods")
        assert not {"version", "signup_validity_days"} & column_names(session, "credit_packs")
        assert "callback_received_at" not in column_names(session, "payments")
        assert _function_count(session) == 0
        assert not {"plan_tiers_seed_terms"} & _function_names(session)
        assert not TRIGGERS & _trigger_names(session)
        assert session.execute(sa.text("SELECT count(*) FROM subscriptions")).scalar_one() == 1
        # The payment (a Phase 02 row) survives; the older objects are untouched.
        assert session.execute(sa.text("SELECT count(*) FROM payments")).scalar_one() == 1
        assert "ix_payments_dedupe_key_prefix" in _indexes(session)

    # The fixture keeps LEMELY_DATABASE__URL pointed at the throwaway database for the whole
    # test, so ``upgrade_head`` migrates that database.
    upgrade_head()

    with sm() as session:
        assert (
            current_revision(session, within=REVISION) == head_revision()
        )  # later revisions sit above 0057
        # Later revisions add their own objects on top (0058's CHECK on subscriptions, 0059's
        # three CHECKs on payments and its ``cancel_source`` CHECK on subscriptions).
        later = {
            "ck_subscriptions_previous_amount_paired",
            "ck_subscriptions_cancel_source_known",
            "ck_payments_applied_not_credited",
            "ck_payments_applied_not_voided",
            "ck_payments_void_reason_known",
        }
        assert object_names(session, PARITY_TABLES_WITH_EVENTS) - later == after_upgrade
        assert _function_count(session) == 1
        assert session.execute(sa.text("SELECT count(*) FROM job_runs")).scalar_one() == 0
        # The terms history was rebuilt for the tier the downgrade left without one.
        assert session.execute(sa.text("SELECT count(*) FROM plan_tier_terms")).scalar_one() == 1
        assert _trigger_names(session) >= TRIGGERS


def test_upgrade_opens_a_period_for_a_signup_pack_that_is_already_off(
    migrated_sessionmaker_with_downgrade: tuple[sessionmaker[Session], Callable[[str], None]],
) -> None:
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    downgrade_to(DOWN_REVISION)
    off = _pack(sm, "signup_student", units=0)
    on = _pack(sm, "signup_teacher", units=2000)
    other = _pack(sm, "starter", units=0)

    before = datetime.now(UTC)
    upgrade_head()

    with sm() as session:
        rows = session.execute(
            sa.text("SELECT credit_pack_id, off_from, off_until FROM signup_allowance_off_periods")
        ).all()
    assert [r.credit_pack_id for r in rows] == [off]
    assert rows[0].off_until is None
    assert before <= rows[0].off_from <= datetime.now(UTC)
    assert on not in {r.credit_pack_id for r in rows}
    assert other not in {r.credit_pack_id for r in rows}


def test_the_upgrade_backfills_terms_for_existing_tiers_and_subscriptions(
    migrated_sessionmaker_with_downgrade: tuple[sessionmaker[Session], Callable[[str], None]],
) -> None:
    """Existing rows are migrated: a tier with a subscription already on it gets terms version 1
    equal to its own columns BEFORE the subscription's composite foreign key is added (the other
    order fails on this very data), and the signup packs get their validity."""
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    downgrade_to(DOWN_REVISION)
    tier = _tier(sm, "pro", 5000)
    free = _tier(sm, "free", 0)
    _tier(sm, "invalid", -1)  # no CHECK on plan_tiers: it gets no terms, the upgrade still runs
    student = _user(sm, "student")
    sub = _subscription(sm, student, tier)
    teacher_pack = _pack(sm, "signup_teacher", units=2000)
    student_pack = _pack(sm, "signup_student", units=250)

    upgrade_head()

    with sm() as session:
        terms = {
            row.plan_tier_id: row
            for row in session.execute(sa.text("SELECT * FROM plan_tier_terms")).all()
        }
        assert set(terms) == {tier, free}
        pro = terms[tier]
        assert (
            pro.terms_version,
            pro.price_minor,
            pro.extra_seat_price_minor,
            pro.allowance_units,
            pro.included_seats,
            pro.seat_allowance_units,
        ) == (1, 5000, 900, 700, 3, 200)
        assert terms[free].price_minor == 0
        stored = session.execute(
            sa.text(
                "SELECT terms_version, pending_terms_version, pending_terms_effective_at, "
                "terms_notice_sent_at FROM subscriptions WHERE id = :s"
            ),
            {"s": sub},
        ).one()
        assert tuple(stored) == (1, None, None, None)
        assert session.execute(
            sa.text("SELECT version, terms_version FROM plan_tiers WHERE id = :t"), {"t": tier}
        ).one() == (1, 1)
        validity = dict(
            session.execute(sa.text("SELECT id, signup_validity_days FROM credit_packs")).all()
        )
    assert validity == {teacher_pack: 30, student_pack: None}


def test_the_upgrade_seeds_the_one_billing_settings_row(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    with migrated_sessionmaker() as session:
        rows = session.execute(sa.text("SELECT * FROM billing_settings")).mappings().all()
    assert len(rows) == 1
    row = rows[0]
    assert {
        key: row[key]
        for key in (
            "id",
            "credit_validity_months",
            "grace_days",
            "max_extra_seats",
            "price_change_notice_days",
            "margin_egp_per_usd",
            "code_execution_usd_per_hour",
            "version",
            "updated_by",
        )
    } == {
        "id": 1,
        "credit_validity_months": 12,
        "grace_days": 3,
        "max_extra_seats": 200,
        "price_change_notice_days": 14,
        "margin_egp_per_usd": None,
        "code_execution_usd_per_hour": None,
        "version": 1,
        "updated_by": None,
    }


def test_billing_settings_is_a_singleton(migrated_sessionmaker: sessionmaker[Session]) -> None:
    with (
        pytest.raises(IntegrityError, match=r"singleton|pk_billing_settings"),
        migrated_sessionmaker.begin() as session,
    ):
        session.execute(sa.text("INSERT INTO billing_settings (id) VALUES (2)"))
    with pytest.raises(IntegrityError), migrated_sessionmaker.begin() as session:
        session.execute(sa.text("INSERT INTO billing_settings (id) VALUES (1)"))


@pytest.mark.parametrize(
    ("assignment", "constraint"),
    [
        ("credit_validity_months = 0", "credit_validity_range"),
        ("credit_validity_months = 121", "credit_validity_range"),
        ("grace_days = 0", "grace_days_range"),
        ("grace_days = 8", "grace_days_range"),
        ("max_extra_seats = 0", "max_extra_seats_range"),
        ("max_extra_seats = 10001", "max_extra_seats_range"),
        ("price_change_notice_days = 6", "price_change_notice_range"),
        ("price_change_notice_days = 91", "price_change_notice_range"),
        ("margin_egp_per_usd = 0", "margin_rate_range"),
        ("margin_egp_per_usd = 10000.0001", "margin_rate_range"),
        ("code_execution_usd_per_hour = -0.000001", "code_execution_nonneg"),
        ("version = 0", "version_min"),
    ],
)
def test_billing_settings_refuses_a_value_outside_its_range(
    migrated_sessionmaker: sessionmaker[Session], assignment: str, constraint: str
) -> None:
    with (
        pytest.raises(IntegrityError, match=constraint),
        migrated_sessionmaker.begin() as session,
    ):
        session.execute(sa.text(f"UPDATE billing_settings SET {assignment}"))  # noqa: S608


@pytest.mark.parametrize(
    "assignment",
    [
        "credit_validity_months = 1",
        "credit_validity_months = 120",
        "grace_days = 7",
        "max_extra_seats = 10000",
        "price_change_notice_days = 7",
        "price_change_notice_days = 90",
        "margin_egp_per_usd = 10000",
        "margin_egp_per_usd = 0.0001",
        "code_execution_usd_per_hour = 0",
    ],
)
def test_billing_settings_accepts_the_edges_of_its_ranges(
    migrated_sessionmaker: sessionmaker[Session], assignment: str
) -> None:
    with migrated_sessionmaker.begin() as session:
        session.execute(sa.text(f"UPDATE billing_settings SET {assignment}"))  # noqa: S608


def test_a_sold_pack_cannot_carry_a_signup_validity(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    with (
        pytest.raises(IntegrityError, match="signup_validity"),
        migrated_sessionmaker.begin() as session,
    ):
        session.execute(
            sa.text(
                "INSERT INTO credit_packs (code, name, units, price_minor, signup_validity_days) "
                "VALUES ('starter', 'Starter', 100, 5000, 30)"
            )
        )
    for days in (0, 3651):
        with (
            pytest.raises(IntegrityError, match="signup_validity"),
            migrated_sessionmaker.begin() as session,
        ):
            session.execute(
                sa.text(
                    "INSERT INTO credit_packs (code, name, units, price_minor, "
                    "signup_validity_days) VALUES ('signup_x', 'x', 1, 0, :d)"
                ),
                {"d": days},
            )
    with migrated_sessionmaker.begin() as session:
        session.execute(
            sa.text(
                "INSERT INTO credit_packs (code, name, units, price_minor, signup_validity_days) "
                "VALUES ('signup_x', 'x', 1, 0, 3650)"
            )
        )


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE plan_tier_terms SET price_minor = 1",
        "DELETE FROM plan_tier_terms",
    ],
)
def test_migrated_plan_tier_terms_are_append_only(
    migrated_sessionmaker: sessionmaker[Session], statement: str
) -> None:
    _tier(migrated_sessionmaker)
    with (
        pytest.raises(DBAPIError, match="plan_tier_terms is append-only"),
        migrated_sessionmaker.begin() as session,
    ):
        session.execute(sa.text(statement))
    with migrated_sessionmaker() as session:
        assert (
            session.execute(sa.text("SELECT price_minor FROM plan_tier_terms")).scalar_one() == 5000
        )


def test_a_new_tier_gets_terms_version_one_from_its_own_columns(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    tier = _tier(migrated_sessionmaker, "new-tier", 1234)
    with migrated_sessionmaker() as session:
        row = session.execute(
            sa.text(
                "SELECT terms_version, price_minor, extra_seat_price_minor, allowance_units, "
                "included_seats, seat_allowance_units, created_by FROM plan_tier_terms "
                "WHERE plan_tier_id = :t"
            ),
            {"t": tier},
        ).one()
    assert tuple(row) == (1, 1234, 900, 700, 3, 200, None)


def test_a_tier_with_an_invalid_amount_is_inserted_with_no_terms_row(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """``plan_tiers`` has no CHECK on amounts and the history refuses negatives: the tier insert
    itself must not fail (a test seeds one on purpose); it just gets no terms to subscribe to."""
    bad = _tier(migrated_sessionmaker, "bad", -100)
    good = _tier(migrated_sessionmaker, "good", 100)
    with migrated_sessionmaker() as session:
        have = set(session.execute(sa.text("SELECT plan_tier_id FROM plan_tier_terms")).scalars())
    assert have == {good}
    student = _user(migrated_sessionmaker, "student")
    with pytest.raises(IntegrityError, match="fk_subscriptions_terms"):
        _subscription(migrated_sessionmaker, student, bad)


def test_a_tier_with_terms_cannot_be_deleted(migrated_sessionmaker: sessionmaker[Session]) -> None:
    tier = _tier(migrated_sessionmaker)
    with pytest.raises(IntegrityError), migrated_sessionmaker.begin() as session:
        session.execute(sa.text("DELETE FROM plan_tiers WHERE id = :t"), {"t": tier})


@pytest.mark.parametrize(
    ("assignment", "constraint"),
    [
        ("price_minor = -1", "amounts_nonneg"),
        ("extra_seat_price_minor = -1", "amounts_nonneg"),
        ("allowance_units = -1", "amounts_nonneg"),
        ("included_seats = -1", "amounts_nonneg"),
        ("seat_allowance_units = -1", "amounts_nonneg"),
        ("terms_version = 0", "terms_version_min"),
    ],
)
def test_terms_refuse_negative_amounts_and_a_zero_version(
    migrated_sessionmaker: sessionmaker[Session], assignment: str, constraint: str
) -> None:
    tier = _tier(migrated_sessionmaker)
    columns = {
        "terms_version": "2",
        "price_minor": "1",
        "extra_seat_price_minor": "1",
        "allowance_units": "1",
        "included_seats": "1",
        "seat_allowance_units": "1",
    }
    name, value = (part.strip() for part in assignment.split("="))
    columns[name] = value
    with pytest.raises(IntegrityError, match=constraint), migrated_sessionmaker.begin() as session:
        session.execute(
            sa.text(
                f"INSERT INTO plan_tier_terms (plan_tier_id, {', '.join(columns)}) "  # noqa: S608
                f"VALUES (:t, {', '.join(columns.values())})"
            ),
            {"t": tier},
        )


def test_a_tier_has_one_row_per_terms_version(migrated_sessionmaker: sessionmaker[Session]) -> None:
    tier = _tier(migrated_sessionmaker)
    _terms_v2(migrated_sessionmaker, tier)
    with pytest.raises(IntegrityError, match="uq_plan_tier_terms"):
        _terms_v2(migrated_sessionmaker, tier)


def test_pending_terms_need_an_effective_date_and_the_reverse(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    tier = _tier(migrated_sessionmaker)
    _terms_v2(migrated_sessionmaker, tier)
    student = _user(migrated_sessionmaker, "student")
    with (
        pytest.raises(IntegrityError, match="pending_terms_paired"),
        migrated_sessionmaker.begin() as session,
    ):
        session.execute(
            sa.text(
                "INSERT INTO subscriptions (user_id, plan_tier_id, pending_terms_version) "
                "VALUES (:u, :t, 2)"
            ),
            {"u": student, "t": tier},
        )
    with (
        pytest.raises(IntegrityError, match="pending_terms_paired"),
        migrated_sessionmaker.begin() as session,
    ):
        session.execute(
            sa.text(
                "INSERT INTO subscriptions (user_id, plan_tier_id, pending_terms_effective_at) "
                "VALUES (:u, :t, now())"
            ),
            {"u": student, "t": tier},
        )
    _subscription(
        migrated_sessionmaker,
        student,
        tier,
        pending_terms_version=2,
        pending_terms_effective_at=T1,
    )


def test_a_subscription_cannot_name_terms_that_do_not_exist(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """The composite foreign keys: the version must exist for THAT tier."""
    tier = _tier(migrated_sessionmaker, "a")
    other = _tier(migrated_sessionmaker, "b")
    _terms_v2(migrated_sessionmaker, other)
    student = _user(migrated_sessionmaker, "student")
    with pytest.raises(IntegrityError, match="fk_subscriptions_terms"):
        _subscription(migrated_sessionmaker, student, tier, terms_version=2)
    with pytest.raises(IntegrityError, match="fk_subscriptions_pending_terms"):
        _subscription(
            migrated_sessionmaker,
            student,
            tier,
            pending_terms_version=2,
            pending_terms_effective_at=T1,
        )
    _subscription(migrated_sessionmaker, student, other, terms_version=2)


def test_the_terms_move_index_is_partial_on_live_statuses(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    with migrated_sessionmaker() as session:
        definition = session.execute(
            sa.text(
                "SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_subscriptions_terms_move'"
            )
        ).scalar_one()
    assert "(plan_tier_id, terms_version)" in definition
    assert "'active'" in definition
    assert "'past_due'" in definition


def _override(sm: sessionmaker[Session], **columns: object) -> None:
    values: dict[str, object] = {
        "model": "gemini-3-pro",
        "input_usd_per_mtok": "1.25",
        "output_usd_per_mtok": "10",
        **columns,
    }
    names = list(values)
    with sm.begin() as session:
        session.execute(
            sa.text(
                f"INSERT INTO llm_price_overrides ({', '.join(names)}) "  # noqa: S608
                f"VALUES ({', '.join(':' + n for n in names)})"
            ),
            values,
        )


def test_an_ai_price_override_is_one_row_per_model_with_optional_prices(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    _override(migrated_sessionmaker)
    _override(
        migrated_sessionmaker,
        model="claude-haiku-4.5:fast",
        cached_input_usd_per_mtok="0.1",
        cache_write_5m_usd_per_mtok="1.25",
        cache_write_1h_usd_per_mtok="2",
        tier_threshold_tokens=200000,
        tier2_input_usd_per_mtok="2.5",
        tier2_output_usd_per_mtok="15",
    )
    with pytest.raises(IntegrityError, match="uq_llm_price_overrides_model"):
        _override(migrated_sessionmaker)
    with migrated_sessionmaker() as session:
        row = session.execute(
            sa.text(
                "SELECT input_usd_per_mtok::text, version FROM llm_price_overrides "
                "WHERE model = 'gemini-3-pro'"
            )
        ).one()
    assert tuple(row) == ("1.250000", 1)


@pytest.mark.parametrize(
    ("columns", "constraint"),
    [
        ({"input_usd_per_mtok": "-1"}, "rates_nonneg"),
        ({"output_usd_per_mtok": "-0.000001"}, "rates_nonneg"),
        ({"cached_input_usd_per_mtok": "-1"}, "rates_nonneg"),
        ({"cache_write_5m_usd_per_mtok": "-1"}, "rates_nonneg"),
        ({"cache_write_1h_usd_per_mtok": "-1"}, "rates_nonneg"),
        # The tier-2 trio is all NULL or all set, with a positive threshold.
        ({"tier_threshold_tokens": 1000}, "tier_trio"),
        ({"tier2_input_usd_per_mtok": "2"}, "tier_trio"),
        ({"tier2_output_usd_per_mtok": "2"}, "tier_trio"),
        ({"tier_threshold_tokens": 1000, "tier2_input_usd_per_mtok": "2"}, "tier_trio"),
        (
            {
                "tier_threshold_tokens": 0,
                "tier2_input_usd_per_mtok": "2",
                "tier2_output_usd_per_mtok": "3",
            },
            "tier_trio",
        ),
        (
            {
                "tier_threshold_tokens": 1000,
                "tier2_input_usd_per_mtok": "-2",
                "tier2_output_usd_per_mtok": "3",
            },
            "rates_nonneg",
        ),
        ({"model": "has space"}, "model_format"),
        ({"model": ""}, "model_format"),
        ({"model": "a/b"}, "model_format"),
        ({"version": 0}, "version_min"),
    ],
)
def test_an_ai_price_override_refuses_what_its_checks_forbid(
    migrated_sessionmaker: sessionmaker[Session], columns: dict[str, object], constraint: str
) -> None:
    with pytest.raises(IntegrityError, match=constraint):
        _override(migrated_sessionmaker, **columns)


def test_a_model_name_of_128_characters_is_accepted_and_129_is_not(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    _override(migrated_sessionmaker, model="m" * 128)
    with pytest.raises(DBAPIError):
        _override(migrated_sessionmaker, model="m" * 129)


def test_the_conversion_rate_has_a_version_counter(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    _rate(migrated_sessionmaker, "EGP", "1")
    with migrated_sessionmaker() as session:
        assert (
            session.execute(sa.text("SELECT version FROM credit_conversion_rates")).scalar_one()
            == 1
        )
    with pytest.raises(IntegrityError, match="version_min"), migrated_sessionmaker.begin() as s:
        s.execute(sa.text("UPDATE credit_conversion_rates SET version = 0"))


def test_plan_tiers_and_packs_carry_a_version_counter_of_at_least_one(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    tier = _tier(migrated_sessionmaker)
    pack = _pack(migrated_sessionmaker, "starter")
    with migrated_sessionmaker() as session:
        assert session.execute(
            sa.text(
                "SELECT version, terms_version, paymob_plan_synced_retrial_days "
                "FROM plan_tiers WHERE id = :t"
            ),
            {"t": tier},
        ).one() == (1, 1, None)
        assert (
            session.execute(
                sa.text("SELECT version FROM credit_packs WHERE id = :p"), {"p": pack}
            ).scalar_one()
            == 1
        )
    for table, row_id, column in (
        ("plan_tiers", tier, "version"),
        ("plan_tiers", tier, "terms_version"),
        ("credit_packs", pack, "version"),
    ):
        with (
            pytest.raises(IntegrityError, match=f"{table}_{column}_min"),
            migrated_sessionmaker.begin() as session,
        ):
            session.execute(
                sa.text(f"UPDATE {table} SET {column} = 0 WHERE id = :i"),  # noqa: S608
                {"i": row_id},
            )


def test_downgrade_refuses_after_the_billing_settings_were_edited(
    migrated_sessionmaker_with_downgrade: tuple[sessionmaker[Session], Callable[[str], None]],
) -> None:
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    with sm.begin() as session:
        session.execute(sa.text("UPDATE billing_settings SET grace_days = 5, version = 2"))

    with pytest.raises(RuntimeError, match="billing_settings"):
        downgrade_to(DOWN_REVISION)

    with sm() as session:
        assert current_revision(session, within=REVISION) == REVISION
        assert "billing_settings" in public_tables(session)


def test_downgrade_accepts_the_untouched_billing_settings_row(
    migrated_sessionmaker_with_downgrade: tuple[sessionmaker[Session], Callable[[str], None]],
) -> None:
    """The seeded row (version 1) alone is not data worth keeping."""
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    downgrade_to(DOWN_REVISION)
    with sm() as session:
        assert "billing_settings" not in public_tables(session)


def test_downgrade_refuses_while_an_ai_price_override_exists(
    migrated_sessionmaker_with_downgrade: tuple[sessionmaker[Session], Callable[[str], None]],
) -> None:
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    _override(sm)

    with pytest.raises(RuntimeError, match="llm_price_overrides"):
        downgrade_to(DOWN_REVISION)

    with sm() as session:
        assert current_revision(session, within=REVISION) == REVISION
        assert "llm_price_overrides" in public_tables(session)


def test_downgrade_refuses_while_terms_above_version_one_exist(
    migrated_sessionmaker_with_downgrade: tuple[sessionmaker[Session], Callable[[str], None]],
) -> None:
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    _terms_v2(sm, _tier(sm))

    with pytest.raises(RuntimeError, match="plan_tier_terms"):
        downgrade_to(DOWN_REVISION)

    with sm() as session:
        assert current_revision(session, within=REVISION) == REVISION
        assert session.execute(sa.text("SELECT count(*) FROM plan_tier_terms")).scalar_one() == 2


def test_downgrade_refuses_while_a_subscription_has_pending_terms(
    migrated_sessionmaker_with_downgrade: tuple[sessionmaker[Session], Callable[[str], None]],
) -> None:
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    # Version 1 only, so the "terms above version 1" guard cannot be what refuses.
    _subscription(
        sm,
        _user(sm, "student"),
        _tier(sm),
        pending_terms_version=1,
        pending_terms_effective_at=T1,
    )

    with pytest.raises(RuntimeError, match="pending terms"):
        downgrade_to(DOWN_REVISION)

    with sm() as session:
        assert current_revision(session, within=REVISION) == REVISION


def _audit(sm: sessionmaker[Session], admin: uuid.UUID, action: str, key: str | None) -> None:
    after = '\'{"idempotency_key": "' + key + "\"}'::jsonb" if key is not None else "NULL"
    with sm.begin() as session:
        session.execute(
            sa.text(
                "INSERT INTO admin_audit_log (admin_user_id, action, target_kind, target_id, "  # noqa: S608
                f"reason, after) VALUES (:a, :act, 'user', :t, 'why', {after})"
            ),
            {"a": admin, "act": action, "t": uuid.uuid4()},
        )


def test_the_idempotency_key_is_unique_per_action_even_without_the_lock(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """A caller that forgets ``lock_idempotency_key`` cannot record a second grant: the insert
    is refused. The same key under another action, and rows without a key, are unaffected."""
    admin = _user(migrated_sessionmaker)
    _audit(migrated_sessionmaker, admin, "customer.grant", "admin-grant:u:r1")
    with (
        pytest.raises(IntegrityError, match="ix_admin_audit_log_idempotency"),
        migrated_sessionmaker.begin() as session,
    ):
        session.execute(
            sa.text(
                "INSERT INTO admin_audit_log (admin_user_id, action, target_kind, target_id, "
                "reason, after) VALUES (:a, 'customer.grant', 'user', :t, 'why', "
                '\'{"idempotency_key": "admin-grant:u:r1"}\'::jsonb)'
            ),
            {"a": admin, "t": uuid.uuid4()},
        )
    _audit(migrated_sessionmaker, admin, "customer.adjust", "admin-grant:u:r1")
    _audit(migrated_sessionmaker, admin, "customer.grant", "admin-grant:u:r2")
    _audit(migrated_sessionmaker, admin, "customer.grant", None)
    _audit(migrated_sessionmaker, admin, "customer.grant", None)
    with migrated_sessionmaker() as session:
        assert session.execute(sa.text("SELECT count(*) FROM admin_audit_log")).scalar_one() == 5


def test_a_terms_row_blocks_deleting_the_admin_who_wrote_it(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """``created_by`` is RESTRICT: SET NULL would be an UPDATE the append-only trigger refuses,
    which surfaced as a confusing "append-only" error on a user delete."""
    admin = _user(migrated_sessionmaker)
    tier = _tier(migrated_sessionmaker)
    with migrated_sessionmaker.begin() as session:
        session.execute(
            sa.text(
                "INSERT INTO plan_tier_terms (plan_tier_id, terms_version, price_minor, "
                "extra_seat_price_minor, allowance_units, included_seats, "
                "seat_allowance_units, created_by) VALUES (:t, 2, 1, 1, 1, 1, 1, :a)"
            ),
            {"t": tier, "a": admin},
        )
    with (
        pytest.raises(IntegrityError, match="fk_plan_tier_terms_created_by_users"),
        migrated_sessionmaker.begin() as session,
    ):
        session.execute(sa.text("DELETE FROM users WHERE id = :u"), {"u": admin})


def test_a_tier_that_becomes_valid_by_an_update_gets_its_terms(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """A negative amount gets no terms at insert. Fixing it later must write the tier's current
    version then, or the tier could never be subscribed to."""
    tier = _tier(migrated_sessionmaker, "fixed-later", -100)
    with migrated_sessionmaker.begin() as session:
        session.execute(
            sa.text("UPDATE plan_tiers SET name = 'renamed' WHERE id = :t"), {"t": tier}
        )
        session.execute(
            sa.text("UPDATE plan_tiers SET price_minor = -5 WHERE id = :t"), {"t": tier}
        )
    with migrated_sessionmaker() as session:
        assert (
            session.execute(
                sa.text("SELECT count(*) FROM plan_tier_terms WHERE plan_tier_id = :t"),
                {"t": tier},
            ).scalar_one()
            == 0
        )
    with migrated_sessionmaker.begin() as session:
        session.execute(
            sa.text("UPDATE plan_tiers SET price_minor = 7700 WHERE id = :t"), {"t": tier}
        )
    with migrated_sessionmaker() as session:
        row = session.execute(
            sa.text(
                "SELECT terms_version, price_minor, created_by FROM plan_tier_terms "
                "WHERE plan_tier_id = :t"
            ),
            {"t": tier},
        ).one()
    assert tuple(row) == (1, 7700, None)


def test_updating_a_tier_that_has_terms_adds_no_row_and_never_fails(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """The admin API inserts the next version itself before it moves ``terms_version``: the
    trigger must not write, or conflict with, a tier that already has terms."""
    tier = _tier(migrated_sessionmaker, "has-terms", 100)
    _terms_v2(migrated_sessionmaker, tier, 200)
    with migrated_sessionmaker.begin() as session:
        session.execute(
            sa.text("UPDATE plan_tiers SET price_minor = 200, terms_version = 2 WHERE id = :t"),
            {"t": tier},
        )
    with migrated_sessionmaker() as session:
        versions = (
            session.execute(
                sa.text(
                    "SELECT terms_version FROM plan_tier_terms WHERE plan_tier_id = :t "
                    "ORDER BY terms_version"
                ),
                {"t": tier},
            )
            .scalars()
            .all()
        )
    assert list(versions) == [1, 2]


def test_downgrade_refuses_after_a_tier_was_edited(
    migrated_sessionmaker_with_downgrade: tuple[sessionmaker[Session], Callable[[str], None]],
) -> None:
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    tier = _tier(sm)
    with sm.begin() as session:
        session.execute(sa.text("UPDATE plan_tiers SET version = 2 WHERE id = :t"), {"t": tier})

    with pytest.raises(RuntimeError, match="plan tier has been edited"):
        downgrade_to(DOWN_REVISION)

    with sm() as session:
        assert current_revision(session, within=REVISION) == REVISION


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE credit_packs SET version = 2",
        "UPDATE credit_packs SET signup_validity_days = 7 WHERE code = 'signup_student'",
        "UPDATE credit_packs SET signup_validity_days = 45 WHERE code = 'signup_teacher'",
    ],
)
def test_downgrade_refuses_after_a_pack_or_its_signup_validity_was_edited(
    migrated_sessionmaker_with_downgrade: tuple[sessionmaker[Session], Callable[[str], None]],
    statement: str,
) -> None:
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    _pack(sm, "signup_student")
    _pack(sm, "signup_teacher", 2000)
    with sm.begin() as session:
        session.execute(
            sa.text(
                "UPDATE credit_packs SET signup_validity_days = 30 WHERE code = 'signup_teacher'"
            )
        )
        session.execute(sa.text(statement))

    with pytest.raises(RuntimeError, match="credit pack has been edited"):
        downgrade_to(DOWN_REVISION)

    with sm() as session:
        assert current_revision(session, within=REVISION) == REVISION


def test_downgrade_accepts_the_seeded_signup_validity(
    migrated_sessionmaker_with_downgrade: tuple[sessionmaker[Session], Callable[[str], None]],
) -> None:
    """Teacher credits at 30 days, the student allowance with none, and a teacher pack created
    without a validity (a catalogue row written before the setting was used) are all fine."""
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    _pack(sm, "signup_student")
    _pack(sm, "signup_teacher", 2000)
    _pack(sm, "starter", 100)
    with sm.begin() as session:
        session.execute(
            sa.text(
                "UPDATE credit_packs SET signup_validity_days = 30 WHERE code = 'signup_teacher'"
            )
        )

    downgrade_to(DOWN_REVISION)

    with sm() as session:
        assert current_revision(session, within=REVISION) == DOWN_REVISION


def _load_migration() -> object:
    spec = importlib.util.spec_from_file_location("admin_audit_log_migration", MIGRATION_FILE)
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
    """``env.py`` runs a whole ``alembic upgrade`` in one transaction, so a ``SET`` that is not
    reset would silently apply to every later migration of the run (0037/0038/0056 precedent)."""
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
    """``SET lock_timeout`` first: a blocked ``ALTER`` fails in seconds instead of queueing every
    ``payments`` query behind it while the old revision serves traffic."""
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
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
