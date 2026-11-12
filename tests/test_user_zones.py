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


# -- The services read the user's zone --------------------------------------

from datetime import UTC, date, datetime, time  # noqa: E402

from lemely.db.leaderboard_repo import LeaderboardScope, LeaderboardService  # noqa: E402
from lemely.db.models.enums import NotificationType, XpSource  # noqa: E402
from lemely.db.notification_prefs_repo import NotificationPreferencesService  # noqa: E402
from lemely.db.notification_repo import NotificationService  # noqa: E402
from lemely.db.xp_repo import XpService  # noqa: E402

#: 2026-09-05 22:30Z is 01:30 on the 6th in Cairo (UTC+3) and 15:30 on the 5th
#: in Los Angeles (UTC-7): one instant, two civil dates.
SPLIT_DATE_INSTANT = datetime(2026, 9, 5, 22, 30, tzinfo=UTC)


def _xp(sm: sessionmaker[Session]) -> XpService:
    return XpService(sm, now=lambda: SPLIT_DATE_INSTANT, zones=UserZoneReader(sm))


def test_awarded_on_is_the_students_own_civil_date(pg_sessionmaker: sessionmaker[Session]) -> None:
    cairo = _seed_user(pg_sessionmaker, timezone="Africa/Cairo")
    la = _seed_user(pg_sessionmaker, timezone="America/Los_Angeles")
    xp = _xp(pg_sessionmaker)

    assert xp.award(cairo, XpSource.quiz_completed, "q1").awarded_on == date(2026, 9, 6)
    assert xp.award(la, XpSource.quiz_completed, "q1").awarded_on == date(2026, 9, 5)


def test_a_student_with_no_zone_keeps_the_launch_zone(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _seed_user(pg_sessionmaker)
    assert _xp(pg_sessionmaker).award(student, XpSource.quiz_completed, "q1").awarded_on == date(
        2026, 9, 6
    )


def test_a_pinned_zone_without_a_reader_still_wins(pg_sessionmaker: sessionmaker[Session]) -> None:
    """Every existing test constructs the service with ``zone=`` and no reader."""
    student = _seed_user(pg_sessionmaker, timezone="America/Los_Angeles")
    xp = XpService(pg_sessionmaker, now=lambda: SPLIT_DATE_INSTANT, zone=CAIRO)
    assert xp.award(student, XpSource.quiz_completed, "q1").awarded_on == date(2026, 9, 6)


def test_history_is_not_rewritten_when_a_zone_changes(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """A zone applies forward only (spec §3): rows already stored keep the date
    they were computed with."""
    student = _seed_user(pg_sessionmaker, timezone="Africa/Cairo")
    xp = _xp(pg_sessionmaker)
    xp.award(student, XpSource.quiz_completed, "q1")

    with pg_sessionmaker.begin() as session:
        session.execute(
            sa.update(User).where(User.id == student).values(timezone="America/Los_Angeles")
        )

    by_day = xp.xp_by_day(student, start=date(2026, 9, 1), end=date(2026, 9, 30))
    assert by_day == {date(2026, 9, 6): 30}


def test_quiet_hours_are_evaluated_in_the_recipients_zone(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """05:30Z is 22:30 in Los Angeles (inside 22:00-07:00) and 08:30 in Cairo."""
    moment = datetime(2026, 9, 5, 5, 30, tzinfo=UTC)
    prefs = NotificationPreferencesService(pg_sessionmaker)
    service = NotificationService(
        pg_sessionmaker,
        prefs,
        now=lambda: moment,
        zone=CAIRO,
        zones=UserZoneReader(pg_sessionmaker),
    )
    la = _seed_user(pg_sessionmaker, timezone="America/Los_Angeles")
    cairo = _seed_user(pg_sessionmaker, timezone="Africa/Cairo")
    for uid in (la, cairo):
        prefs.set(uid, quiet_hours_start=time(22, 0), quiet_hours_end=time(7, 0))

    asleep = service.create(la, NotificationType.announcement, "Test", dedupe_key="a")
    awake = service.create(cairo, NotificationType.announcement, "Test", dedupe_key="a")

    assert asleep.row is not None and asleep.push_allowed is False
    assert asleep.push_suppressed_reason == "quiet_hours"
    assert awake.row is not None and awake.push_allowed is True


def test_the_leaderboard_week_is_the_same_for_every_zone(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The regression test for the invariant §3 refuses to break: a shared
    ranking summed over two different weeks would mean nothing. 2026-09-06
    22:30Z is Monday the 7th in Cairo and still Sunday the 6th in Los Angeles;
    both boards use the global week regardless."""
    moment = datetime(2026, 9, 6, 22, 30, tzinfo=UTC)
    cairo = _seed_user(pg_sessionmaker, timezone="Africa/Cairo")
    la = _seed_user(pg_sessionmaker, timezone="America/Los_Angeles")
    board = LeaderboardService(pg_sessionmaker, now=lambda: moment)

    cairo_result = board.board(cairo, LeaderboardScope.global_)
    la_result = board.board(la, LeaderboardScope.global_)

    assert cairo_result.week_start == la_result.week_start == date(2026, 9, 7)
    assert cairo_result.week_end == la_result.week_end == date(2026, 9, 13)


def test_profile_uses_the_students_day_for_the_streak_and_the_global_week(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The seam §3 states plainly: near midnight, far from Cairo, the calendar
    ends on the student's own date while the week window is the shared one."""
    la = _seed_user(pg_sessionmaker, timezone="America/Los_Angeles")
    xp = _xp(pg_sessionmaker)

    profile = xp.profile(la)

    assert profile.calendar_end == date(2026, 9, 5)
    assert profile.week_start == date(2026, 8, 31)  # Monday of the Cairo week containing the 6th
    assert profile.week_end == date(2026, 9, 6)
