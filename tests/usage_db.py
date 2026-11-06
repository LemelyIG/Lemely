"""Database helpers shared by the usage-ledger test modules (Paymob billing Phase 01).

Not a test module (no ``test_`` prefix). Each test module defines its own
``usage_db``/``sm`` fixtures from these helpers, as ``tests/tutoring_db.py``'s
callers do.

* :func:`usage_database` builds one throwaway ``create_all`` database per module.
  ``create_all`` installs the ``usage_entries`` append-only trigger through the
  model's ``after_create`` listener.
* :func:`emptied_after` empties it after every test. ``TRUNCATE`` fires no row
  trigger, so the append-only trigger does not block it.
* ``add_*`` seed users and rates directly; ``balance``/``entries`` read the
  ledger back without going through the repository under test.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.core.usage_types import GrantScope, Payer
from lemely.db.base import Base
from lemely.db.models import import_all_models
from lemely.db.models.enums import Role
from lemely.db.models.usage import (
    GrantKind,
    UsageDebt,
    UsageEntry,
    UsageGrant,
    UsageGrantBalance,
    UsageRate,
)
from lemely.db.models.users import User
from lemely.db.usage_ledger_repo import UsageLedger
from lemely.runtime.config import DatabaseSettings

if TYPE_CHECKING:
    from collections.abc import Iterator

import_all_models()

#: A fixed instant, so expiry arithmetic in the tests is exact.
NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
RATE_VERSION = 1
ESTIMATOR_VERSION = 1
ACTION = "mark_paper"
#: 1000 units per USD: ``Decimal("0.0042")`` USD is 5 units (ceil of 4.2).
UNITS_PER_USD = 1000


@contextmanager
def usage_database() -> Iterator[sessionmaker[Session]]:
    """A fresh ``create_all`` database for one test module."""
    base = make_url(DatabaseSettings().url)
    admin = create_engine(base.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect():
            pass
    except OperationalError:
        admin.dispose()
        pytest.skip("local Postgres not reachable")
    name = f"lemely_usage_{uuid.uuid4().hex[:12]}"
    with admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{name}"'))
    engine = create_engine(base.set(database=name))
    try:
        Base.metadata.create_all(engine)
        yield sessionmaker(bind=engine, expire_on_commit=False, future=True)
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def emptied_after(factory: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    """Yield ``factory``, then empty every table that references users, and the rates."""
    yield factory
    with factory.begin() as session:
        session.execute(sa.text("TRUNCATE users, usage_rates, usage_estimators CASCADE"))


def add_user(factory: sessionmaker[Session], role: Role = Role.student) -> uuid.UUID:
    uid = uuid.uuid4()
    with factory.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role))
    return uid


def add_rate(
    factory: sessionmaker[Session],
    *,
    version: int = RATE_VERSION,
    action: str = ACTION,
    units_per_usd: int = UNITS_PER_USD,
) -> None:
    with factory.begin() as session:
        session.add(
            UsageRate(
                version=version,
                action=action,
                units_per_usd=units_per_usd,
                effective_from=NOW - timedelta(days=30),
            )
        )


def grant(
    factory: sessionmaker[Session],
    owner: uuid.UUID,
    units: int,
    *,
    kind: GrantKind = GrantKind.period_allowance,
    visible: bool = False,
    expires_at: datetime | None = None,
    effective_at: datetime | None = None,
    teacher_member_id: uuid.UUID | None = None,
    key: str | None = None,
) -> uuid.UUID:
    """Issue a grant through the ledger in its own transaction; return its id."""
    with factory.begin() as session:
        issued = UsageLedger(session).issue_grant(
            owner_user_id=owner,
            kind=kind,
            units=units,
            idempotency_key=key or f"test:{uuid.uuid4()}",
            expires_at=expires_at,
            visible=visible,
            effective_at=effective_at or NOW - timedelta(days=1),
            teacher_member_id=teacher_member_id,
        )
        return issued.id


def own_chain(owner: uuid.UUID) -> list[Payer]:
    """``own allowance -> own credits`` (spec §5.6, "anyone else")."""
    return [
        Payer(owner_user_id=owner, scope=GrantScope.ALLOWANCE),
        Payer(owner_user_id=owner, scope=GrantScope.CREDITS),
    ]


def seat_chain(
    student: uuid.UUID, teacher: uuid.UUID, member: uuid.UUID, cap: int | None
) -> list[Payer]:
    """Seated student, in-scope action: seat -> teacher credits (if capped) -> own (§5.6)."""
    chain = [
        Payer(
            owner_user_id=student, scope=GrantScope.SEAT, teacher_member_id=member, debt_exempt=True
        )
    ]
    if cap is not None:
        chain.append(
            Payer(
                owner_user_id=teacher,
                scope=GrantScope.CREDITS,
                teacher_member_id=member,
                cap_units=cap,
            )
        )
    return [*chain, *own_chain(student)]


def add_debt(factory: sessionmaker[Session], owner: uuid.UUID, units: int) -> uuid.UUID:
    """A debt row with no job, inserted directly, bypassing the ledger."""
    with factory.begin() as session:
        debt = UsageDebt(owner_user_id=owner, units=units, outstanding=units)
        session.add(debt)
        session.flush()
        return debt.id


def balance(factory: sessionmaker[Session], grant_id: uuid.UUID) -> tuple[int, int]:
    """``(remaining, held)`` from the cache row."""
    with factory() as session:
        row = session.get(UsageGrantBalance, grant_id)
        assert row is not None
        return row.remaining, row.held


def entries(factory: sessionmaker[Session], **filters: object) -> list[UsageEntry]:
    with factory() as session:
        stmt = sa.select(UsageEntry).order_by(UsageEntry.created_at, UsageEntry.id)
        for column, value in filters.items():
            stmt = stmt.where(getattr(UsageEntry, column) == value)
        return list(session.scalars(stmt))


def debts(factory: sessionmaker[Session], owner: uuid.UUID) -> list[UsageDebt]:
    with factory() as session:
        return list(
            session.scalars(
                sa.select(UsageDebt)
                .where(UsageDebt.owner_user_id == owner)
                .order_by(UsageDebt.created_at, UsageDebt.id)
            )
        )


def grant_row(factory: sessionmaker[Session], grant_id: uuid.UUID) -> UsageGrant:
    with factory() as session:
        row = session.get(UsageGrant, grant_id)
        assert row is not None
        return row


__all__ = [
    "ACTION",
    "ESTIMATOR_VERSION",
    "NOW",
    "RATE_VERSION",
    "UNITS_PER_USD",
    "add_debt",
    "add_rate",
    "add_user",
    "balance",
    "debts",
    "emptied_after",
    "entries",
    "grant",
    "grant_row",
    "own_chain",
    "seat_chain",
    "usage_database",
]
