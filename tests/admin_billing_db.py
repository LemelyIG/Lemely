"""Database helpers shared by the admin billing test modules (Phase 07).

Not a test module (no ``test_`` prefix). Each test module defines its own
``billing_db`` (module scope) and ``sm`` (per test) fixtures from these helpers:

    @pytest.fixture(scope="module")
    def billing_db() -> Iterator[sessionmaker[Session]]:
        with billing_database() as factory:
            yield factory

    @pytest.fixture
    def sm(billing_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
        yield from emptied_after(billing_db)

``NOW`` is the fixed clock every service under test is given. Seeds always pass
explicit instants: a server-default ``now()`` would be the real clock, not ``NOW``.
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

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)

# Tables with no foreign key to ``users`` that the admin billing tests write directly. A
# ``TRUNCATE ... CASCADE`` on these also empties every table that references them:
# ``admin_audit_log``, ``payment_refunds`` and ``payments`` through ``users``,
# ``signup_allowance_off_periods`` through ``credit_packs``, ``usage_job_model_costs`` through
# the jobs of a user, ``plan_tier_terms`` through ``plan_tiers``. ``billing_settings`` and
# ``llm_price_overrides`` reference ``users`` (``updated_by``) so a cascade reaches them too;
# they are listed to be explicit.
_ROOT_TABLES = (
    "users",
    "plan_tiers",
    "credit_packs",
    "usage_rates",
    "usage_estimators",
    "job_runs",
    "paymob_webhook_failures",
    "paymob_events",
    "billing_settings",
    "llm_price_overrides",
)


@contextmanager
def billing_database() -> Iterator[sessionmaker[Session]]:
    """A fresh ``create_all`` database for one test module, dropped afterwards.

    Skips the test module when no local Postgres is reachable.
    """
    base = make_url(DatabaseSettings().url)
    admin = create_engine(base.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect():
            pass
    except OperationalError:
        admin.dispose()
        pytest.skip("local Postgres not reachable")
    name = f"lemely_test_{uuid.uuid4().hex[:12]}"
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
    """Yield ``factory``, then empty every table the admin billing tests write.

    ``billing_settings`` is emptied with the rest and its single row inserted again, as
    ``create_all`` and the migration leave it: a settings read never finds the table empty.
    """
    yield factory
    with factory.begin() as session:
        session.execute(sa.text(f"TRUNCATE {', '.join(_ROOT_TABLES)} CASCADE"))
        session.execute(sa.text("INSERT INTO billing_settings (id) VALUES (1)"))


def add_user(
    factory: sessionmaker[Session],
    role: Role | str = Role.student,
    *,
    email: str | None = None,
    display_name: str | None = None,
) -> uuid.UUID:
    """Insert one user and return its id."""
    uid = uuid.uuid4()
    with factory.begin() as session:
        session.add(
            User(
                id=uid,
                email=email or f"{uid}@example.com",
                role=Role(role),
                display_name=display_name,
                created_at=NOW,
            )
        )
    return uid
