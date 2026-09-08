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


# -- streak_warning ---------------------------------------------------------

from datetime import timedelta  # noqa: E402

from lemely.db.models.engagement import Streak  # noqa: E402
from lemely.db.models.enums import NotificationType  # noqa: E402
from lemely.db.notification_prefs_repo import NotificationPreferencesService  # noqa: E402
from lemely.db.notification_repo import NotificationService  # noqa: E402
from lemely.web.push import RecordingPushTransport  # noqa: E402
from lemely.web.scheduled_notifications import (  # noqa: E402
    STREAK_WARNING_TITLE,
    streak_tonight,
    warn_streaks,
)

#: 16:30Z on 5 Sept 2026: 19:30 in Cairo (past 19:00), 09:30 in Los Angeles.
CAIRO_EVENING = datetime(2026, 9, 5, 16, 30, tzinfo=UTC)
#: Ten hours later: 02:30Z on the 6th — 19:30 on the 5th in Los Angeles, and
#: 05:30 on the 6th in Cairo, which is a new date and not yet 19:00.
LA_EVENING = CAIRO_EVENING + timedelta(hours=10)


@pytest.fixture
def notifications(pg_sessionmaker: sessionmaker[Session]) -> NotificationService:
    return NotificationService(pg_sessionmaker, NotificationPreferencesService(pg_sessionmaker))


@pytest.fixture
def transport() -> RecordingPushTransport:
    return RecordingPushTransport()


def _seed_streak(
    sm: sessionmaker[Session],
    user: uuid.UUID,
    *,
    length: int,
    last_active_on: date | None,
    freezes: int = 0,
) -> None:
    with sm.begin() as session:
        session.add(
            Streak(
                user_id=user,
                current_length=length,
                longest_length=max(length, 1),
                last_active_on=last_active_on,
                freezes_available=freezes,
            )
        )


def _warn(
    sm: sessionmaker[Session],
    notifications: NotificationService,
    transport: RecordingPushTransport,
    *,
    now: datetime,
    memo: ZoneDateMemo | None = None,
) -> int:
    return warn_streaks(sm, notifications, transport, now=now, hour=19, memo=memo or ZoneDateMemo())


def test_an_inactive_student_with_a_live_streak_is_warned_once_at_their_19_00(
    pg_sessionmaker: sessionmaker[Session],
    notifications: NotificationService,
    transport: RecordingPushTransport,
) -> None:
    """One warning at 19:00; a second pass with the same memo skips the zone,
    and a third pass with a fresh memo is discarded by the unique index. Both
    later passes send nothing."""
    student = _seed_user(pg_sessionmaker, timezone="Africa/Cairo")
    _seed_streak(pg_sessionmaker, student, length=12, last_active_on=date(2026, 9, 4))
    notifications.subscribe(student, "https://push.example.test/s", "p", "a")
    memo = ZoneDateMemo()

    assert _warn(pg_sessionmaker, notifications, transport, now=CAIRO_EVENING, memo=memo) == 1
    assert _warn(pg_sessionmaker, notifications, transport, now=CAIRO_EVENING, memo=memo) == 0
    assert _warn(pg_sessionmaker, notifications, transport, now=CAIRO_EVENING) == 0

    rows = notifications.list_for_user(student)
    assert len(rows) == 1
    assert rows[0].type is NotificationType.streak_warning
    assert rows[0].title == STREAK_WARNING_TITLE
    assert rows[0].body == "Your 12-day streak ends if today stays empty."
    assert rows[0].payload == {"streakLength": "12", "freezeAvailable": "false"}
    assert len(transport.endpoints) == 1


def test_a_student_who_earned_xp_today_is_not_warned(
    pg_sessionmaker: sessionmaker[Session],
    notifications: NotificationService,
    transport: RecordingPushTransport,
) -> None:
    student = _seed_user(pg_sessionmaker, timezone="Africa/Cairo")
    _seed_streak(pg_sessionmaker, student, length=3, last_active_on=date(2026, 9, 5))

    assert _warn(pg_sessionmaker, notifications, transport, now=CAIRO_EVENING) == 0
    assert notifications.list_for_user(student) == []


def test_a_student_with_no_streak_is_not_warned(
    pg_sessionmaker: sessionmaker[Session],
    notifications: NotificationService,
    transport: RecordingPushTransport,
) -> None:
    student = _seed_user(pg_sessionmaker, timezone="Africa/Cairo")
    _seed_streak(pg_sessionmaker, student, length=0, last_active_on=date(2026, 9, 1))

    assert _warn(pg_sessionmaker, notifications, transport, now=CAIRO_EVENING) == 0
    assert notifications.list_for_user(student) == []


def test_the_freeze_and_no_freeze_bodies_differ_and_name_the_real_length(
    pg_sessionmaker: sessionmaker[Session],
    notifications: NotificationService,
    transport: RecordingPushTransport,
) -> None:
    """Fires even when a freeze would cover the day, because a freeze is
    consumed silently by ``_resolve_gap`` and a student who is never told
    burns freezes without knowing they had them (spec §2)."""
    frozen = _seed_user(pg_sessionmaker, timezone="Africa/Cairo")
    _seed_streak(pg_sessionmaker, frozen, length=7, last_active_on=date(2026, 9, 4), freezes=1)
    bare = _seed_user(pg_sessionmaker, timezone="Africa/Cairo")
    _seed_streak(pg_sessionmaker, bare, length=21, last_active_on=date(2026, 9, 4))

    assert _warn(pg_sessionmaker, notifications, transport, now=CAIRO_EVENING) == 2

    assert notifications.list_for_user(frozen)[0].body == (
        "A freeze will cover today. Your 7-day streak stays."
    )
    assert notifications.list_for_user(frozen)[0].payload["freezeAvailable"] == "true"
    assert notifications.list_for_user(bare)[0].body == (
        "Your 21-day streak ends if today stays empty."
    )


def test_a_streak_resolve_gap_would_already_have_reset_is_not_warned() -> None:
    """Two days missed, no freeze held: the row still says 5, the truth is 0,
    and a warning would name a streak that has already ended."""
    row = Streak(
        current_length=5, longest_length=5, last_active_on=date(2026, 9, 2), freezes_available=0
    )
    assert streak_tonight(row, date(2026, 9, 5)) is None


def test_a_freeze_spent_on_a_missed_day_is_not_available_for_tonight() -> None:
    """One day missed, one freeze held: the freeze covers yesterday, nothing
    covers today, so the body is the no-freeze one."""
    row = Streak(
        current_length=5, longest_length=5, last_active_on=date(2026, 9, 3), freezes_available=1
    )
    assert streak_tonight(row, date(2026, 9, 5)) == (5, False)
    two = Streak(
        current_length=5, longest_length=5, last_active_on=date(2026, 9, 3), freezes_available=2
    )
    assert streak_tonight(two, date(2026, 9, 5)) == (5, True)


def test_a_streak_warning_preference_of_false_suppresses_the_row(
    pg_sessionmaker: sessionmaker[Session],
    notifications: NotificationService,
    transport: RecordingPushTransport,
) -> None:
    student = _seed_user(pg_sessionmaker, timezone="Africa/Cairo")
    _seed_streak(pg_sessionmaker, student, length=4, last_active_on=date(2026, 9, 4))
    NotificationPreferencesService(pg_sessionmaker).set(student, streak_warning=False)

    assert _warn(pg_sessionmaker, notifications, transport, now=CAIRO_EVENING) == 0
    assert notifications.list_for_user(student) == []


def test_one_pass_warns_cairo_and_not_los_angeles_then_los_angeles_ten_hours_later(
    pg_sessionmaker: sessionmaker[Session],
    notifications: NotificationService,
    transport: RecordingPushTransport,
) -> None:
    """Each is keyed on their own civil date, so the second pass — which
    spans a date boundary in Cairo but not in Los Angeles — double-sends to
    neither: Cairo is on a new date before 19:00, Los Angeles gets its one."""
    cairo = _seed_user(pg_sessionmaker, timezone="Africa/Cairo")
    la = _seed_user(pg_sessionmaker, timezone="America/Los_Angeles")
    for student in (cairo, la):
        _seed_streak(pg_sessionmaker, student, length=2, last_active_on=date(2026, 9, 4))
    memo = ZoneDateMemo()

    assert _warn(pg_sessionmaker, notifications, transport, now=CAIRO_EVENING, memo=memo) == 1
    assert len(notifications.list_for_user(cairo)) == 1
    assert notifications.list_for_user(la) == []

    assert _warn(pg_sessionmaker, notifications, transport, now=LA_EVENING, memo=memo) == 1
    assert len(notifications.list_for_user(cairo)) == 1
    assert len(notifications.list_for_user(la)) == 1


def test_a_student_with_no_zone_is_warned_on_the_launch_zone(
    pg_sessionmaker: sessionmaker[Session],
    notifications: NotificationService,
    transport: RecordingPushTransport,
) -> None:
    student = _seed_user(pg_sessionmaker)
    _seed_streak(pg_sessionmaker, student, length=1, last_active_on=date(2026, 9, 4))

    assert _warn(pg_sessionmaker, notifications, transport, now=CAIRO_EVENING) == 1


# -- study_plan_reminder ----------------------------------------------------

from lemely.db.models.study_plan import (  # noqa: E402
    StudyPlan,
    StudyPlanActivityType,
    StudyPlanSession,
)
from lemely.web.scheduled_notifications import (  # noqa: E402
    STUDY_PLAN_REMINDER_TITLE,
    remind_study_plans,
)

#: 06:30Z on 5 Sept 2026: 09:30 in Cairo, past 08:00.
CAIRO_MORNING = datetime(2026, 9, 5, 6, 30, tzinfo=UTC)


def _seed_session(
    sm: sessionmaker[Session],
    user: uuid.UUID,
    *,
    subject_code: str = "0625",
    on: date = date(2026, 9, 5),
    topic: str = "Algebraic fractions",
    duration: int = 40,
    completed: bool = False,
    superseded: bool = False,
) -> uuid.UUID:
    with sm.begin() as session:
        plan = StudyPlan(
            user_id=user,
            subject_code=subject_code,
            week_start=date(2026, 8, 31),
            weekly_hours=5.0,
            available=True,
            generated_at=datetime(2026, 8, 31, 8, 0, tzinfo=UTC),
            superseded_at=datetime(2026, 9, 1, 8, 0, tzinfo=UTC) if superseded else None,
        )
        session.add(plan)
        session.flush()
        row = StudyPlanSession(
            plan_id=plan.id,
            date=on,
            topic=topic,
            activity_type=StudyPlanActivityType.practice,
            duration_minutes=duration,
            focus="Cancel common factors first.",
            completed_at=datetime(2026, 9, 5, 5, 0, tzinfo=UTC) if completed else None,
        )
        session.add(row)
        session.flush()
        return row.id


def _remind(
    sm: sessionmaker[Session],
    notifications: NotificationService,
    transport: RecordingPushTransport,
    *,
    now: datetime = CAIRO_MORNING,
    memo: ZoneDateMemo | None = None,
) -> int:
    return remind_study_plans(
        sm, notifications, transport, now=now, hour=8, memo=memo or ZoneDateMemo()
    )


def test_an_incomplete_session_dated_today_is_reminded_once(
    pg_sessionmaker: sessionmaker[Session],
    notifications: NotificationService,
    transport: RecordingPushTransport,
) -> None:
    student = _seed_user(pg_sessionmaker, timezone="Africa/Cairo")
    session_id = _seed_session(pg_sessionmaker, student)

    assert _remind(pg_sessionmaker, notifications, transport) == 1
    assert _remind(pg_sessionmaker, notifications, transport) == 0

    rows = notifications.list_for_user(student)
    assert len(rows) == 1
    assert rows[0].type is NotificationType.study_plan_reminder
    assert rows[0].title == STUDY_PLAN_REMINDER_TITLE
    assert rows[0].body == "Algebraic fractions · 40 min"
    assert rows[0].payload == {
        "sessionId": str(session_id),
        "subjectCode": "0625",
        "topic": "Algebraic fractions",
    }


@pytest.mark.parametrize(
    "kwargs",
    [
        {"completed": True},
        {"on": date(2026, 9, 6)},
        {"on": date(2026, 9, 4)},
        {"superseded": True},
    ],
)
def test_completed_other_day_and_superseded_sessions_are_skipped(
    pg_sessionmaker: sessionmaker[Session],
    notifications: NotificationService,
    transport: RecordingPushTransport,
    kwargs: dict[str, object],
) -> None:
    student = _seed_user(pg_sessionmaker, timezone="Africa/Cairo")
    _seed_session(pg_sessionmaker, student, **kwargs)  # type: ignore[arg-type]

    assert _remind(pg_sessionmaker, notifications, transport) == 0
    assert notifications.list_for_user(student) == []


def test_three_subjects_with_a_session_each_today_produce_three_notifications(
    pg_sessionmaker: sessionmaker[Session],
    notifications: NotificationService,
    transport: RecordingPushTransport,
) -> None:
    """The volume is asserted, not left to be discovered in production (spec
    §2): a plan is single-subject, so three subjects are three reminders."""
    student = _seed_user(pg_sessionmaker, timezone="Africa/Cairo")
    for code in ("0625", "0580", "0606"):
        _seed_session(pg_sessionmaker, student, subject_code=code)

    assert _remind(pg_sessionmaker, notifications, transport) == 3
    assert sorted(row.payload["subjectCode"] for row in notifications.list_for_user(student)) == [
        "0580",
        "0606",
        "0625",
    ]


def test_a_study_plan_reminder_preference_of_false_suppresses_the_row(
    pg_sessionmaker: sessionmaker[Session],
    notifications: NotificationService,
    transport: RecordingPushTransport,
) -> None:
    student = _seed_user(pg_sessionmaker, timezone="Africa/Cairo")
    _seed_session(pg_sessionmaker, student)
    NotificationPreferencesService(pg_sessionmaker).set(student, study_plan_reminder=False)

    assert _remind(pg_sessionmaker, notifications, transport) == 0
    assert notifications.list_for_user(student) == []


def test_a_session_is_reminded_on_its_owners_civil_date(
    pg_sessionmaker: sessionmaker[Session],
    notifications: NotificationService,
    transport: RecordingPushTransport,
) -> None:
    """06:30Z is 09:30 in Cairo and 23:30 on the 4th in Los Angeles: the
    Los Angeles session dated the 5th is not today there yet."""
    cairo = _seed_user(pg_sessionmaker, timezone="Africa/Cairo")
    la = _seed_user(pg_sessionmaker, timezone="America/Los_Angeles")
    _seed_session(pg_sessionmaker, cairo)
    _seed_session(pg_sessionmaker, la)

    assert _remind(pg_sessionmaker, notifications, transport) == 1
    assert len(notifications.list_for_user(cairo)) == 1
    assert notifications.list_for_user(la) == []


# -- The sweeper (§4) ---------------------------------------------------------

import asyncio  # noqa: E402

from lemely.web.scheduled_notifications import Sweeper, run_jobs, run_sweeper  # noqa: E402


def test_a_job_that_throws_is_a_logged_warning_and_the_others_still_run() -> None:
    ran: list[str] = []

    def ok_one() -> int:
        ran.append("one")
        return 1

    def boom() -> int:
        raise RuntimeError("database went away")

    def ok_two() -> int:
        ran.append("two")
        return 2

    results = run_jobs([("one", ok_one), ("boom", boom), ("two", ok_two)])

    assert ran == ["one", "two"]
    assert results == {"one": 1, "boom": None, "two": 2}


def test_the_sweeper_loop_sweeps_immediately_and_stops_when_asked() -> None:
    """The loop must not wait a full poll interval before its first pass — a
    freshly started instance on Cloud Run has to sweep now — and must exit
    promptly on ``stop`` rather than sleeping out the interval."""
    sweeps: list[int] = []

    class _Fake:
        def sweep_once(self) -> dict[str, int | None]:
            sweeps.append(len(sweeps))
            return {}

    async def scenario() -> None:
        stop = asyncio.Event()
        task = asyncio.create_task(run_sweeper(_Fake(), poll_seconds=60, stop=stop))  # type: ignore[arg-type]
        await asyncio.sleep(0.05)
        assert sweeps == [0]
        stop.set()
        await asyncio.wait_for(task, timeout=1)

    asyncio.run(scenario())


def test_a_sweeper_pass_runs_all_three_jobs_against_an_empty_database(
    pg_sessionmaker: sessionmaker[Session],
    notifications: NotificationService,
    transport: RecordingPushTransport,
) -> None:
    from lemely.db.announcement_repo import AnnouncementService
    from lemely.db.class_repo import ClassService
    from lemely.runtime.config import NotificationsSettings

    sweeper = Sweeper(
        sessionmaker=pg_sessionmaker,
        announcements=AnnouncementService(pg_sessionmaker, ClassService(pg_sessionmaker)),
        notifications=notifications,
        transport=transport,
        settings=NotificationsSettings(),
        now=lambda: CAIRO_EVENING,
    )

    assert sweeper.sweep_once() == {
        "publish_due_announcements": 0,
        "warn_streaks": 0,
        "remind_study_plans": 0,
    }
