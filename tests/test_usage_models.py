"""Usage-ledger ORM models: enum pins, CHECK constraints, append-only trigger (spec §4.5, §6)."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError, IntegrityError

from lemely.core.usage_pricing import GRANT_PRIORITY
from lemely.core.usage_types import ESTIMATOR_INPUT_KINDS
from lemely.db.base import Base
from lemely.db.models.usage import (
    EstimatorInputKind,
    GrantKind,
    UsageDebt,
    UsageEntry,
    UsageEntryKind,
    UsageGrant,
    UsageGrantBalance,
    UsageJob,
    UsageJobStatus,
)
from tests.usage_db import NOW, add_user, emptied_after, usage_database

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

USAGE_TABLES = {
    "usage_rates",
    "usage_estimators",
    "usage_grants",
    "usage_grant_balances",
    "usage_jobs",
    "usage_entries",
    "usage_debts",
}


@pytest.fixture(scope="module")
def usage_db() -> Iterator[sessionmaker[Session]]:
    with usage_database() as factory:
        yield factory


@pytest.fixture
def sm(usage_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(usage_db)


# ---------------------------------------------------------------------------
# Metadata layer
# ---------------------------------------------------------------------------


def test_all_usage_tables_registered() -> None:
    assert set(Base.metadata.tables) >= USAGE_TABLES


def test_enum_values_match_the_index_contract() -> None:
    assert [m.value for m in GrantKind] == [
        "period_allowance",
        "seat_allowance",
        "signup",
        "credit_pack",
        "auto_topup",
        "refund",
        "adjustment",
    ]
    assert [m.value for m in UsageJobStatus] == ["open", "settled", "released", "expired"]
    assert [m.value for m in UsageEntryKind] == [
        "grant",
        "hold",
        "release",
        "settle",
        "expire",
        "refund",
        "adjust",
        "debt",
        "debt_repay",
    ]


def test_db_enums_mirror_the_core_vocabularies() -> None:
    """``lemely.db.models`` never imports ``lemely.core``; this pins the copies together."""
    assert {m.value for m in GrantKind} == set(GRANT_PRIORITY)
    assert {m.value for m in EstimatorInputKind} == ESTIMATOR_INPUT_KINDS


def test_foreign_keys_deferred_to_later_phases_are_plain_columns() -> None:
    grants = Base.metadata.tables["usage_grants"]
    for column in ("payment_id", "subscription_period_id", "teacher_member_id"):
        assert grants.c[column].nullable
        assert not grants.c[column].foreign_keys


# ---------------------------------------------------------------------------
# Database layer (create_all)
# ---------------------------------------------------------------------------


def _grant(owner: uuid.UUID, **overrides: object) -> UsageGrant:
    values: dict[str, object] = {
        "owner_user_id": owner,
        "kind": GrantKind.credit_pack,
        "visible": True,
        "priority": 50,
        "units": 10,
        "effective_at": NOW,
        "idempotency_key": f"k:{uuid.uuid4()}",
    }
    values.update(overrides)
    return UsageGrant(**values)


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"units": 0}, "ck_usage_grants_units_positive"),
        ({"expires_at": NOW}, "ck_usage_grants_expires_after_effective"),
        # seat grant with no member
        ({"kind": GrantKind.seat_allowance, "visible": False}, "ck_usage_grants_seat_link"),
        # member on a non-seat grant
        ({"teacher_member_id": uuid.uuid4()}, "ck_usage_grants_seat_link"),
        ({"kind": GrantKind.period_allowance, "visible": True}, "ck_usage_grants_allowance_hidden"),
        ({"kind": GrantKind.credit_pack, "visible": False}, "ck_usage_grants_credit_visible"),
        ({"kind": GrantKind.auto_topup, "visible": False}, "ck_usage_grants_credit_visible"),
    ],
)
def test_usage_grants_checks_reject(
    sm: sessionmaker[Session], overrides: dict[str, object], constraint: str
) -> None:
    owner = add_user(sm)
    with pytest.raises(IntegrityError, match=constraint), sm.begin() as session:
        session.add(_grant(owner, **overrides))


@pytest.mark.parametrize(
    "overrides",
    [
        {"kind": GrantKind.period_allowance, "visible": False, "priority": 10},
        {"kind": GrantKind.signup, "visible": False, "priority": 20},
        {"kind": GrantKind.signup, "visible": True, "priority": 20},
        {"kind": GrantKind.credit_pack, "visible": True},
        {"kind": GrantKind.auto_topup, "visible": True},
    ],
)
def test_usage_grants_checks_accept_valid_visibility(
    sm: sessionmaker[Session], overrides: dict[str, object]
) -> None:
    owner = add_user(sm)
    with sm.begin() as session:
        session.add(_grant(owner, **overrides))


def test_usage_grants_idempotency_key_is_unique_per_owner(sm: sessionmaker[Session]) -> None:
    owner, other = add_user(sm), add_user(sm)
    with sm.begin() as session:
        session.add(_grant(owner, idempotency_key="same"))
        session.add(_grant(other, idempotency_key="same"))
    with (
        pytest.raises(IntegrityError, match="uq_usage_grants_owner_idempotency"),
        sm.begin() as session,
    ):
        session.add(_grant(owner, idempotency_key="same"))


@pytest.mark.parametrize(("remaining", "held"), [(5, 6), (5, -1), (-1, 0)])
def test_balance_check_keeps_held_within_remaining(
    sm: sessionmaker[Session], remaining: int, held: int
) -> None:
    owner = add_user(sm)
    with sm.begin() as session:
        row = _grant(owner)
        session.add(row)
    with (
        pytest.raises(IntegrityError, match="ck_usage_grant_balances_held_within_remaining"),
        sm.begin() as session,
    ):
        session.add(UsageGrantBalance(grant_id=row.id, remaining=remaining, held=held))


def test_usage_entries_are_append_only(sm: sessionmaker[Session]) -> None:
    owner = add_user(sm)
    with sm.begin() as session:
        row = _grant(owner)
        session.add(row)
        session.flush()
        entry = UsageEntry(
            grant_id=row.id,
            kind=UsageEntryKind.grant,
            units=10,
            event_at=NOW,
            idempotency_key="grant",
        )
        session.add(entry)
    with pytest.raises(DBAPIError, match="append-only: UPDATE rejected"), sm.begin() as session:
        session.execute(
            sa.text("UPDATE usage_entries SET units = 99 WHERE id = :i"), {"i": entry.id}
        )
    with pytest.raises(DBAPIError, match="append-only: DELETE rejected"), sm.begin() as session:
        session.execute(sa.text("DELETE FROM usage_entries WHERE id = :i"), {"i": entry.id})
    with sm() as session:
        assert session.scalar(sa.select(UsageEntry.units).where(UsageEntry.id == entry.id)) == 10


def test_usage_entries_unique_per_grant_key_kind(sm: sessionmaker[Session]) -> None:
    owner = add_user(sm)
    with sm.begin() as session:
        row = _grant(owner)
        session.add(row)
        session.flush()
        session.add(
            UsageEntry(
                grant_id=row.id,
                kind=UsageEntryKind.hold,
                units=3,
                event_at=NOW,
                idempotency_key="job:1",
            )
        )
    with (
        pytest.raises(IntegrityError, match="uq_usage_entries_grant_key_kind"),
        sm.begin() as session,
    ):
        session.add(
            UsageEntry(
                grant_id=row.id,
                kind=UsageEntryKind.hold,
                units=3,
                event_at=NOW + timedelta(seconds=1),
                idempotency_key="job:1",
            )
        )


def test_usage_entries_need_a_target_and_nonzero_units(sm: sessionmaker[Session]) -> None:
    with pytest.raises(IntegrityError, match="ck_usage_entries_has_target"), sm.begin() as session:
        session.add(
            UsageEntry(kind=UsageEntryKind.adjust, units=1, event_at=NOW, idempotency_key="x")
        )
    owner = add_user(sm)
    with sm.begin() as session:
        row = _grant(owner)
        session.add(row)
    with (
        pytest.raises(IntegrityError, match="ck_usage_entries_units_nonzero"),
        sm.begin() as session,
    ):
        session.add(
            UsageEntry(
                grant_id=row.id,
                kind=UsageEntryKind.grant,
                units=0,
                event_at=NOW,
                idempotency_key="z",
            )
        )


def test_usage_entries_debt_kinds_need_a_debt(sm: sessionmaker[Session]) -> None:
    owner = add_user(sm)
    with sm.begin() as session:
        row = _grant(owner)
        session.add(row)
    for kind in (UsageEntryKind.debt, UsageEntryKind.debt_repay):
        with (
            pytest.raises(IntegrityError, match="ck_usage_entries_debt_kinds_link"),
            sm.begin() as session,
        ):
            session.add(
                UsageEntry(
                    grant_id=row.id,
                    kind=kind,
                    units=-1,
                    event_at=NOW,
                    idempotency_key=f"d:{kind.value}",
                )
            )


def _debt_entry(debt_id: uuid.UUID, kind: UsageEntryKind, key: str) -> UsageEntry:
    return UsageEntry(debt_id=debt_id, kind=kind, units=-5, event_at=NOW, idempotency_key=key)


def test_usage_entries_unique_per_debt_key_kind_when_there_is_no_grant(
    sm: sessionmaker[Session],
) -> None:
    """The ``(grant_id, key, kind)`` constraint cannot see NULL grants; the partial index can."""
    owner = add_user(sm)
    with sm.begin() as session:
        debt = UsageDebt(owner_user_id=owner, units=5, outstanding=5)
        session.add(debt)
        session.flush()
        debt_id = debt.id
        session.add(_debt_entry(debt_id, UsageEntryKind.debt, "job:1"))
    with (
        pytest.raises(IntegrityError, match="uq_usage_entries_debt_key_kind"),
        sm.begin() as session,
    ):
        session.add(_debt_entry(debt_id, UsageEntryKind.debt, "job:1"))
    # A different kind or key on the same debt is a different ledger line.
    with sm.begin() as session:
        session.add(_debt_entry(debt_id, UsageEntryKind.debt_repay, "job:1"))
        session.add(_debt_entry(debt_id, UsageEntryKind.debt, "job:2"))


def _job(actor: uuid.UUID, **overrides: object) -> UsageJob:
    values: dict[str, object] = {
        "job_id": uuid.uuid4(),
        "actor_user_id": actor,
        "action": "mark_paper",
        "estimate_low": 1,
        "estimate_high": 2,
        "estimator_version": 1,
        "reserved": 2,
        "rate_version": 1,
        "payer_chain": [],
        "expires_at": NOW + timedelta(hours=1),
    }
    values.update(overrides)
    return UsageJob(**values)


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"estimate_low": 5, "estimate_high": 2}, "ck_usage_jobs_estimate_range"),
        ({"estimate_low": -1}, "ck_usage_jobs_estimate_range"),
        ({"reserved": -1}, "ck_usage_jobs_reserved_nonnegative"),
        ({"charged": 2, "debt_created": 3}, "ck_usage_jobs_debt_within_charged"),
        ({"debt_created": -1}, "ck_usage_jobs_debt_within_charged"),
        ({"status": UsageJobStatus.settled}, "ck_usage_jobs_settled_at_matches"),
        ({"settled_at": NOW}, "ck_usage_jobs_settled_at_matches"),
        (
            {"status": UsageJobStatus.released, "settled_at": NOW},
            "ck_usage_jobs_settled_at_matches",
        ),
    ],
)
def test_usage_jobs_checks_reject(
    sm: sessionmaker[Session], overrides: dict[str, object], constraint: str
) -> None:
    actor = add_user(sm)
    with pytest.raises(IntegrityError, match=constraint), sm.begin() as session:
        session.add(_job(actor, **overrides))


def test_usage_jobs_charged_nonnegative_trips_on_its_own(sm: sessionmaker[Session]) -> None:
    """``charged < 0`` also breaks ``debt_within_charged`` (``0 <= debt_created <= charged``).

    Postgres names one violated check, so drop the implying one inside the (rolled back)
    transaction to show ``charged_nonnegative`` fires by itself.
    """
    actor = add_user(sm)
    with (
        pytest.raises(IntegrityError, match="ck_usage_jobs_charged_nonnegative"),
        sm.begin() as session,
    ):
        session.execute(
            sa.text("ALTER TABLE usage_jobs DROP CONSTRAINT ck_usage_jobs_debt_within_charged")
        )
        session.add(_job(actor, charged=-1))
    # The rollback restored the dropped constraint.
    with sm() as session:
        assert session.scalar(
            sa.text(
                "SELECT count(*) FROM pg_constraint "
                "WHERE conname = 'ck_usage_jobs_debt_within_charged'"
            )
        )


def test_usage_jobs_accept_a_settled_job_with_debt(sm: sessionmaker[Session]) -> None:
    actor = add_user(sm)
    with sm.begin() as session:
        session.add(_job(actor))
        session.add(
            _job(
                actor,
                status=UsageJobStatus.settled,
                settled_at=NOW,
                charged=3,
                debt_created=3,
            )
        )


@pytest.mark.parametrize(
    ("units", "outstanding", "constraint"),
    [
        (0, 0, "ck_usage_debts_units_positive"),
        (5, 6, "ck_usage_debts_outstanding_within_units"),
        (5, -1, "ck_usage_debts_outstanding_within_units"),
    ],
)
def test_usage_debts_checks_reject(
    sm: sessionmaker[Session], units: int, outstanding: int, constraint: str
) -> None:
    owner = add_user(sm)
    with pytest.raises(IntegrityError, match=constraint), sm.begin() as session:
        session.add(UsageDebt(owner_user_id=owner, units=units, outstanding=outstanding))


def test_usage_debts_accept_zero_outstanding(sm: sessionmaker[Session]) -> None:
    owner = add_user(sm)
    with sm.begin() as session:
        session.add(UsageDebt(owner_user_id=owner, units=5, outstanding=0))


# ---------------------------------------------------------------------------
# Index layer (create_all)
# ---------------------------------------------------------------------------


def _index_columns(factory: sessionmaker[Session], name: str) -> list[str]:
    """The index's key columns in order, from the catalogue."""
    with factory() as session:
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


def _index_options(factory: sessionmaker[Session], name: str) -> list[int]:
    """``indoption`` per key column: bit 0 = DESC, bit 1 = NULLS FIRST (0 = ASC NULLS LAST)."""
    with factory() as session:
        raw = session.execute(
            sa.text(
                "SELECT i.indoption::text FROM pg_index i "
                "JOIN pg_class c ON c.oid = i.indexrelid WHERE c.relname = :name"
            ),
            {"name": name},
        ).scalar_one()
    return [int(part) for part in raw.split()]


def test_spend_order_index_covers_the_spec_order(usage_db: sessionmaker[Session]) -> None:
    """Priority, then soonest expiry with NULL (no expiry) last, then oldest, then id."""
    assert _index_columns(usage_db, "ix_usage_grants_owner_spend") == [
        "owner_user_id",
        "priority",
        "expires_at",
        "effective_at",
        "id",
    ]
    assert _index_options(usage_db, "ix_usage_grants_owner_spend") == [0, 0, 0, 0, 0]


@pytest.mark.parametrize(
    ("index", "column"),
    [("ix_usage_entries_debt", "debt_id"), ("ix_usage_debts_job", "job_id")],
)
def test_foreign_key_lookup_indexes_exist(
    usage_db: sessionmaker[Session], index: str, column: str
) -> None:
    assert _index_columns(usage_db, index) == [column]
