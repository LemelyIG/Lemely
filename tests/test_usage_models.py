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
    UsageEntry,
    UsageEntryKind,
    UsageGrant,
    UsageGrantBalance,
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
    "overrides",
    [
        {"units": 0},
        {"expires_at": NOW},
        {"kind": GrantKind.seat_allowance, "visible": False},  # seat grant with no member
        {"teacher_member_id": uuid.uuid4()},  # member on a non-seat grant
        {"kind": GrantKind.period_allowance, "visible": True},
    ],
)
def test_usage_grants_checks_reject(
    sm: sessionmaker[Session], overrides: dict[str, object]
) -> None:
    owner = add_user(sm)
    with pytest.raises(IntegrityError), sm.begin() as session:
        session.add(_grant(owner, **overrides))


def test_usage_grants_idempotency_key_is_unique_per_owner(sm: sessionmaker[Session]) -> None:
    owner, other = add_user(sm), add_user(sm)
    with sm.begin() as session:
        session.add(_grant(owner, idempotency_key="same"))
        session.add(_grant(other, idempotency_key="same"))
    with pytest.raises(IntegrityError), sm.begin() as session:
        session.add(_grant(owner, idempotency_key="same"))


@pytest.mark.parametrize(("remaining", "held"), [(5, 6), (5, -1), (-1, 0)])
def test_balance_check_keeps_held_within_remaining(
    sm: sessionmaker[Session], remaining: int, held: int
) -> None:
    owner = add_user(sm)
    with sm.begin() as session:
        row = _grant(owner)
        session.add(row)
    with pytest.raises(IntegrityError), sm.begin() as session:
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
    with pytest.raises(IntegrityError), sm.begin() as session:
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
    with pytest.raises(IntegrityError), sm.begin() as session:
        session.add(
            UsageEntry(kind=UsageEntryKind.adjust, units=1, event_at=NOW, idempotency_key="x")
        )
    owner = add_user(sm)
    with sm.begin() as session:
        row = _grant(owner)
        session.add(row)
    with pytest.raises(IntegrityError), sm.begin() as session:
        session.add(
            UsageEntry(
                grant_id=row.id,
                kind=UsageEntryKind.grant,
                units=0,
                event_at=NOW,
                idempotency_key="z",
            )
        )
