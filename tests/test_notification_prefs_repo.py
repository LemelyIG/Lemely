"""Postgres integration tests for the notification-preferences service (P3.6 chunk B).

Exercises :class:`~lemely.db.notification_prefs_repo.NotificationPreferencesService`
against a throwaway database and skips cleanly when no local server is
reachable (mirrors ``tests/test_parent_repo.py``, whose ``pg_sessionmaker``
fixture and seed-helper style this file duplicates verbatim per this repo's
convention — every ``test_*_repo.py`` file carries its own copy rather than
sharing one via conftest). Proves the guarantees the chunk brief requires:

* ``get`` for a user with no row returns :data:`DEFAULTS` and creates
  nothing — the row count stays zero afterwards.
* ``set`` upserts: the first call materialises a row seeded from
  :data:`DEFAULTS`, a later partial call leaves unmentioned fields
  untouched, and no second row is ever created for the same user.
* The quiet-hours pair round-trips when both are set, clears when both are
  explicitly set back to ``None``, and raises ``ValueError`` when the merged
  result would leave exactly one of the pair set.
* A malformed UUID is a clean ``ValueError`` on both ``get`` and ``set``.
"""

from __future__ import annotations

import uuid
from datetime import time
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.db.base import Base
from lemely.db.models import NotificationPreference, User
from lemely.db.models.enums import Role
from lemely.db.notification_prefs_repo import DEFAULTS, NotificationPreferencesService
from lemely.runtime.config import DatabaseSettings

if TYPE_CHECKING:
    from collections.abc import Iterator


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


@pytest.fixture
def pg_sessionmaker() -> Iterator[sessionmaker[Session]]:
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
        yield sessionmaker(bind=engine, expire_on_commit=False, future=True)
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)'))
        admin.dispose()


# ── Seed helpers ────────────────────────────────────────────────────────────


def _seed_user(sm: sessionmaker[Session], role: Role = Role.student) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role))
    return uid


def _row_count(sm: sessionmaker[Session]) -> int:
    with sm() as session:
        return int(session.scalar(select(func.count()).select_from(NotificationPreference)) or 0)


# ── get: absent row reads as defaults, never creates ────────────────────────


def test_get_absent_row_returns_defaults_and_creates_nothing(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    user = _seed_user(pg_sessionmaker)
    service = NotificationPreferencesService(pg_sessionmaker)

    row = service.get(user)

    assert row == DEFAULTS
    assert row.grade_ready is True
    assert row.announcement is True
    assert row.streak_warning is True
    assert row.study_plan_reminder is True
    assert row.at_risk_alert is True
    assert row.quiet_hours_start is None
    assert row.quiet_hours_end is None
    assert _row_count(pg_sessionmaker) == 0


def test_get_malformed_uuid_raises_value_error(pg_sessionmaker: sessionmaker[Session]) -> None:
    service = NotificationPreferencesService(pg_sessionmaker)
    with pytest.raises(ValueError, match="Identifier must be a UUID"):
        service.get("not-a-uuid")


# ── set: upsert, partial update, round trip ──────────────────────────────────


def test_set_then_get_round_trips(pg_sessionmaker: sessionmaker[Session]) -> None:
    user = _seed_user(pg_sessionmaker)
    service = NotificationPreferencesService(pg_sessionmaker)

    written = service.set(user, grade_ready=False, streak_warning=False)
    read = service.get(user)

    assert written == read
    assert read.grade_ready is False
    assert read.streak_warning is False
    # Unmentioned fields land at the documented default on first write.
    assert read.announcement is True
    assert read.study_plan_reminder is True
    assert read.at_risk_alert is True
    assert _row_count(pg_sessionmaker) == 1


def test_partial_set_leaves_other_fields_untouched(pg_sessionmaker: sessionmaker[Session]) -> None:
    user = _seed_user(pg_sessionmaker)
    service = NotificationPreferencesService(pg_sessionmaker)

    service.set(user, grade_ready=False, announcement=False, at_risk_alert=False)
    updated = service.set(user, grade_ready=True)

    assert updated.grade_ready is True
    # Untouched by the second call — must still reflect the first call.
    assert updated.announcement is False
    assert updated.at_risk_alert is False
    assert updated.streak_warning is True
    assert updated.study_plan_reminder is True
    assert _row_count(pg_sessionmaker) == 1


def test_set_is_upsert_not_a_duplicate_row(pg_sessionmaker: sessionmaker[Session]) -> None:
    user = _seed_user(pg_sessionmaker)
    service = NotificationPreferencesService(pg_sessionmaker)

    service.set(user, grade_ready=False)
    service.set(user, grade_ready=True)
    service.set(user, announcement=False)

    assert _row_count(pg_sessionmaker) == 1
    final = service.get(user)
    assert final.grade_ready is True
    assert final.announcement is False


def test_set_malformed_uuid_raises_value_error(pg_sessionmaker: sessionmaker[Session]) -> None:
    service = NotificationPreferencesService(pg_sessionmaker)
    with pytest.raises(ValueError, match="Identifier must be a UUID"):
        service.set("not-a-uuid", grade_ready=False)


# ── Quiet hours: pair invariant ──────────────────────────────────────────────


def test_quiet_hours_both_set_round_trips(pg_sessionmaker: sessionmaker[Session]) -> None:
    user = _seed_user(pg_sessionmaker)
    service = NotificationPreferencesService(pg_sessionmaker)

    start, end = time(22, 0), time(7, 0)
    service.set(user, quiet_hours_start=start, quiet_hours_end=end)
    read = service.get(user)

    assert read.quiet_hours_start == start
    assert read.quiet_hours_end == end


def test_quiet_hours_can_be_cleared_together(pg_sessionmaker: sessionmaker[Session]) -> None:
    user = _seed_user(pg_sessionmaker)
    service = NotificationPreferencesService(pg_sessionmaker)

    service.set(user, quiet_hours_start=time(22, 0), quiet_hours_end=time(7, 0))
    cleared = service.set(user, quiet_hours_start=None, quiet_hours_end=None)

    assert cleared.quiet_hours_start is None
    assert cleared.quiet_hours_end is None


def test_quiet_hours_start_without_end_raises_value_error(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    user = _seed_user(pg_sessionmaker)
    service = NotificationPreferencesService(pg_sessionmaker)

    with pytest.raises(ValueError, match="must be set"):
        service.set(user, quiet_hours_start=time(22, 0))
    # The rejected write must not have partially landed.
    assert service.get(user) == DEFAULTS


def test_quiet_hours_end_without_start_raises_value_error(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    user = _seed_user(pg_sessionmaker)
    service = NotificationPreferencesService(pg_sessionmaker)

    with pytest.raises(ValueError, match="must be set"):
        service.set(user, quiet_hours_end=time(7, 0))
    assert service.get(user) == DEFAULTS


def test_clearing_only_one_bound_of_an_existing_pair_raises_value_error(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    user = _seed_user(pg_sessionmaker)
    service = NotificationPreferencesService(pg_sessionmaker)
    service.set(user, quiet_hours_start=time(22, 0), quiet_hours_end=time(7, 0))

    with pytest.raises(ValueError, match="must be set"):
        service.set(user, quiet_hours_start=None)
    # The rejected write must not have partially landed either.
    read = service.get(user)
    assert read.quiet_hours_start == time(22, 0)
    assert read.quiet_hours_end == time(7, 0)
