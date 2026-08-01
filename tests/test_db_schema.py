"""Schema-level tests for the SQLAlchemy ORM models and the core migration.

Two layers:

* **Metadata assertions** run everywhere with no database. They guard against
  regressions such as an unresolved ``Mapped[...]`` annotation (which silently
  breaks every model at mapper-configuration time) and confirm the naming
  convention that the additive-migration guarantee depends on.
* **Integration tests** create a throwaway Postgres database, run
  ``create_all``, and exercise enums, server defaults, and foreign keys against
  a real server. They skip cleanly when no local Postgres is reachable (CI
  without a DB service, or the local Supabase stack being down).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from lemely.db.base import Base
from lemely.db.models import import_all_models
from lemely.runtime.config import DatabaseSettings

if TYPE_CHECKING:
    from collections.abc import Iterator

# Populate Base.metadata with every model before any assertion runs.
import_all_models()

EXPECTED_TABLES = {
    "users",
    "parent_child_links",
    "devices",
    "schools",
    "school_memberships",
    "seats",
    "classes",
    "class_enrollments",
    "subjects",
    "papers",
    "mark_schemes",
    "plan_tiers",
    "subscriptions",
    "uploads",
    "attempts",
    "question_results",
    "weakness_records",
    "review_queue",
    "announcements",
    "notifications",
    "xp_events",
    "streaks",
}


# ---------------------------------------------------------------------------
# Metadata layer — no database required
# ---------------------------------------------------------------------------


def test_all_expected_tables_registered() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_registry_configures() -> None:
    # Fails loudly if any Mapped[...] annotation cannot be resolved at runtime
    # (e.g. a type imported only under TYPE_CHECKING).
    Base.registry.configure()


def test_naming_convention_applied() -> None:
    users = Base.metadata.tables["users"]
    assert users.primary_key.name == "pk_users"
    fk_names = [
        fk.name for table in Base.metadata.tables.values() for fk in table.foreign_key_constraints
    ]
    assert fk_names, "expected foreign keys across the schema"
    assert all(str(name).startswith("fk_") for name in fk_names)


def test_every_model_has_timestamps() -> None:
    for name, table in Base.metadata.tables.items():
        assert "created_at" in table.c, f"{name} missing created_at"
        assert "updated_at" in table.c, f"{name} missing updated_at"


# ---------------------------------------------------------------------------
# Integration layer — real Postgres, skipped when unreachable
# ---------------------------------------------------------------------------


def _server_reachable(url: str) -> bool:
    server_url = make_url(url).set(database="postgres")
    engine = create_engine(server_url)
    try:
        with engine.connect():
            return True
    except OperationalError:
        return False
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def pg_engine() -> Iterator[sa.Engine]:
    base_url = DatabaseSettings().url
    if not _server_reachable(base_url):
        pytest.skip("local Postgres not reachable")

    server_url = make_url(base_url).set(database="postgres")
    admin = create_engine(server_url, isolation_level="AUTOCOMMIT")
    dbname = f"lemely_test_{uuid.uuid4().hex[:12]}"
    with admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{dbname}"'))

    engine = create_engine(make_url(base_url).set(database=dbname))
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)'))
        admin.dispose()


def test_server_defaults_and_enums(pg_engine: sa.Engine) -> None:
    from lemely.db.models import PlanTier, Subscription, User
    from lemely.db.models.enums import Role, SubscriptionStatus

    uid = uuid.uuid4()
    with Session(pg_engine) as session:
        session.add(User(id=uid, email="student@example.com", role=Role.student))
        tier = PlanTier(code="free", name="Free")
        session.add(tier)
        session.flush()  # populate server-default id via RETURNING
        sub = Subscription(user_id=uid, plan_tier_id=tier.id)
        session.add(sub)
        session.commit()

        session.refresh(sub)
        user = session.get(User, uid)
        assert user is not None
        assert user.is_active is False  # server_default false
        assert user.locale == "en"  # server_default 'en'
        assert user.created_at is not None
        assert sub.status is SubscriptionStatus.inactive  # enum server_default
        assert tier.currency == "EGP"
        assert tier.max_devices == 3
        assert tier.features == {}


def test_unique_email_enforced(pg_engine: sa.Engine) -> None:
    from lemely.db.models import User
    from lemely.db.models.enums import Role

    with Session(pg_engine) as session:
        session.add(User(id=uuid.uuid4(), email="dup@example.com", role=Role.parent))
        session.commit()

    with Session(pg_engine) as session, pytest.raises(IntegrityError):
        session.add(User(id=uuid.uuid4(), email="dup@example.com", role=Role.teacher))
        session.commit()


def test_foreign_key_enforced(pg_engine: sa.Engine) -> None:
    from lemely.db.models import Subscription

    with Session(pg_engine) as session, pytest.raises(IntegrityError):
        session.add(Subscription(user_id=uuid.uuid4(), plan_tier_id=uuid.uuid4()))
        session.commit()
