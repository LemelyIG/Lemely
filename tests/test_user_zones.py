"""Per-user civil-time zones (spec §3): ``resolve_zone`` and ``UserZoneReader``.

A stored zone that tzdata later retires must never be able to fail a student's
XP award, so resolution falls back to the launch zone and never raises.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.db.base import Base
from lemely.db.models.enums import Role
from lemely.db.models.users import User
from lemely.db.xp_repo import DEFAULT_ZONE, UserZoneReader, resolve_zone
from lemely.runtime.config import DatabaseSettings

if TYPE_CHECKING:
    from collections.abc import Iterator

CAIRO = ZoneInfo("Africa/Cairo")
LOS_ANGELES = ZoneInfo("America/Los_Angeles")


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
    sm: sessionmaker[Session],
    *,
    role: Role = Role.student,
    timezone: str | None = None,
    explicit: bool = False,
) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            User(
                id=uid,
                email=f"{uid}@example.com",
                role=role,
                timezone=timezone,
                timezone_is_explicit=explicit,
            )
        )
    return uid


# -- resolve_zone -----------------------------------------------------------


@pytest.mark.parametrize("name", [None, "", "   "])
def test_resolve_zone_falls_back_to_the_launch_zone_for_unset(name: str | None) -> None:
    assert resolve_zone(name) is DEFAULT_ZONE


@pytest.mark.parametrize("name", ["Not/AZone", "../etc/passwd", "Africa/Cairo/../Nope"])
def test_resolve_zone_never_raises_for_an_unresolvable_name(name: str) -> None:
    """A retired or corrupt stored name is wrong by an hour or two if it falls
    back; raising would be wrong by the whole feature."""
    assert resolve_zone(name) is DEFAULT_ZONE


def test_resolve_zone_resolves_a_real_name() -> None:
    assert resolve_zone("America/Los_Angeles").key == "America/Los_Angeles"


# -- UserZoneReader ---------------------------------------------------------


def test_reader_returns_the_stored_zone(pg_sessionmaker: sessionmaker[Session]) -> None:
    uid = _seed_user(pg_sessionmaker, timezone="America/Los_Angeles")
    assert UserZoneReader(pg_sessionmaker).zone_for(uid).key == "America/Los_Angeles"


def test_reader_returns_the_launch_zone_for_a_null_column(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """NULL means never set, so the migration is a no-op for every existing row."""
    uid = _seed_user(pg_sessionmaker)
    assert UserZoneReader(pg_sessionmaker).zone_for(uid) is DEFAULT_ZONE


def test_reader_returns_the_launch_zone_for_an_unknown_user(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    assert UserZoneReader(pg_sessionmaker).zone_for(uuid.uuid4()) is DEFAULT_ZONE


def test_reader_memoises_until_told_to_forget(pg_sessionmaker: sessionmaker[Session]) -> None:
    uid = _seed_user(pg_sessionmaker, timezone="America/Los_Angeles")
    reader = UserZoneReader(pg_sessionmaker)
    assert reader.zone_for(uid).key == "America/Los_Angeles"

    with pg_sessionmaker.begin() as session:
        session.execute(sa.update(User).where(User.id == uid).values(timezone="Africa/Cairo"))

    # Still the memoised answer: the reader has not been told the row changed.
    assert reader.zone_for(uid).key == "America/Los_Angeles"
    reader.forget(uid)
    assert reader.zone_for(uid).key == "Africa/Cairo"


def test_reader_accepts_a_string_id(pg_sessionmaker: sessionmaker[Session]) -> None:
    uid = _seed_user(pg_sessionmaker, timezone="Asia/Tokyo")
    assert UserZoneReader(pg_sessionmaker).zone_for(str(uid)).key == "Asia/Tokyo"
