"""Database helpers shared by the usage-ledger test modules (Paymob billing Phase 01).

Not a test module (no ``test_`` prefix). Each test module defines its own
``usage_db``/``sm`` fixtures from these helpers, as ``tests/tutoring_db.py``'s
callers do.

* :func:`usage_database` builds one throwaway ``create_all`` database per module.
  ``create_all`` installs the ``usage_entries`` append-only trigger through the
  model's ``after_create`` listener.
* :func:`emptied_after` empties it after every test. ``TRUNCATE`` fires no row
  trigger, so the append-only trigger does not block it.
* :func:`add_user` seeds a user directly. Task 4 adds the ledger seeders.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.db.base import Base
from lemely.db.models import import_all_models
from lemely.db.models.enums import Role
from lemely.db.models.users import User
from lemely.runtime.config import DatabaseSettings

if TYPE_CHECKING:
    from collections.abc import Iterator

import_all_models()

#: A fixed instant, so expiry arithmetic in the tests is exact.
NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)


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


__all__ = [
    "NOW",
    "add_user",
    "emptied_after",
    "usage_database",
]
