"""The two daily engagement jobs and the per-zone machinery they share (spec §2, §4).

Work is proportional to the number of *zones in use*, not to the user count:
a pass lists distinct zones, keeps the ones past the trigger hour, and queries
candidates per zone keyed on that zone's civil date.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.db.base import Base
from lemely.db.models.enums import Role
from lemely.db.models.users import User
from lemely.db.xp_repo import DEFAULT_ZONE
from lemely.runtime.config import DatabaseSettings
from lemely.web.scheduled_notifications import ZoneDateMemo, due_zones, zones_in_use

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


def _seed_user(
    sm: sessionmaker[Session], *, role: Role = Role.student, timezone: str | None = None
) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role, timezone=timezone))
    return uid


# -- Zones in use -----------------------------------------------------------


def test_zones_in_use_is_distinct_zones_plus_the_default_bucket(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _seed_user(pg_sessionmaker)
    _seed_user(pg_sessionmaker, timezone="America/Los_Angeles")
    _seed_user(pg_sessionmaker, timezone="America/Los_Angeles")
    _seed_user(pg_sessionmaker, timezone="Asia/Tokyo")

    with pg_sessionmaker() as session:
        assert zones_in_use(session) == ["Africa/Cairo", "America/Los_Angeles", "Asia/Tokyo"]


def test_zones_in_use_always_includes_the_default_even_with_no_users(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    with pg_sessionmaker() as session:
        assert zones_in_use(session) == [DEFAULT_ZONE.key]


# -- Due zones ---------------------------------------------------------------


def test_due_zones_keeps_the_zones_at_or_past_the_hour_with_their_own_date() -> None:
    """16:30Z on 5 Sept: 19:30 in Cairo (UTC+3, due), 09:30 in Los Angeles
    (UTC-7, not due), 01:30 on the 6th in Tokyo (UTC+9, a new day, not due)."""
    now = datetime(2026, 9, 5, 16, 30, tzinfo=UTC)

    due = due_zones(["Africa/Cairo", "America/Los_Angeles", "Asia/Tokyo"], now=now, hour=19)

    assert due == [("Africa/Cairo", date(2026, 9, 5))]


def test_due_zones_at_the_exact_hour_is_due() -> None:
    now = datetime(2026, 9, 5, 16, 0, tzinfo=UTC)  # 19:00 in Cairo
    assert due_zones(["Africa/Cairo"], now=now, hour=19) == [("Africa/Cairo", date(2026, 9, 5))]


def test_due_zones_falls_back_for_an_unresolvable_stored_name() -> None:
    """A retired zone name is bucketed under its own name but timed on the
    launch zone, so its users are still reached — an hour or two off, never
    never."""
    now = datetime(2026, 9, 5, 16, 30, tzinfo=UTC)
    assert due_zones(["Mars/Base"], now=now, hour=19) == [("Mars/Base", date(2026, 9, 5))]


# -- The per-zone memo -------------------------------------------------------


def test_the_memo_skips_a_zone_until_its_date_changes() -> None:
    memo = ZoneDateMemo()
    assert memo.is_done("Africa/Cairo", date(2026, 9, 5)) is False
    memo.mark_done("Africa/Cairo", date(2026, 9, 5))
    assert memo.is_done("Africa/Cairo", date(2026, 9, 5)) is True
    assert memo.is_done("Africa/Cairo", date(2026, 9, 6)) is False
    assert memo.is_done("Asia/Tokyo", date(2026, 9, 5)) is False
