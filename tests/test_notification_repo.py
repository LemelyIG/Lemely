"""Postgres integration tests for the notification inbox + push storage (P5.6 chunk A).

Exercises :class:`~lemely.db.notification_repo.NotificationService` against a
throwaway database and skips cleanly when no local server is reachable. The
``pg_sessionmaker`` fixture and seed helpers are duplicated from
``tests/test_notification_prefs_repo.py`` per this repo's convention — every
``test_*_repo.py`` carries its own copy rather than sharing one via conftest.

What these tests are actually defending (D5.9):

* **A type toggle off suppresses the row itself**, while **quiet hours
  suppress only the push and always write the row.** These are the two halves
  of §2 and confusing them either fills an inbox with refused items or loses a
  notification for having arrived at 2am.
* **A missing preferences row means opted-in**, so a user who never opened
  settings is not silently silenced.
* ``grade_ready`` is idempotent per upload (§6, the shape D5.3 found the hard
  way in the XP paper seam) while an unkeyed notification is deliberately not
  deduped.
* Re-subscribing an endpoint that belongs to someone else **moves** the row,
  because an endpoint identifies a browser and not a person.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, time
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.db.base import Base
from lemely.db.models import Notification, NotificationType, PushSubscription, User
from lemely.db.models.enums import Role
from lemely.db.notification_prefs_repo import NotificationPreferencesService
from lemely.db.notification_repo import (
    PREFERENCE_FIELD_FOR_TYPE,
    NotificationOutcome,
    NotificationService,
    civil_time_in_zone,
    is_within_quiet_hours,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

CAIRO = ZoneInfo("Africa/Cairo")


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
    from lemely.runtime.config import DatabaseSettings

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


def _service(
    sm: sessionmaker[Session],
    *,
    now: datetime | None = None,
) -> NotificationService:
    clock = (lambda: now) if now is not None else (lambda: datetime.now(UTC))
    return NotificationService(
        sm,
        NotificationPreferencesService(sm),
        now=clock,
        zone=CAIRO,
    )


def _notification_count(sm: sessionmaker[Session]) -> int:
    with sm() as session:
        return int(session.scalar(select(func.count()).select_from(Notification)) or 0)


# ── The preference vocabulary pin ───────────────────────────────────────────


def test_every_notification_type_has_a_preference_field() -> None:
    """The gate map must cover the enum exactly — no member unmapped, none invented.

    A sixth ``NotificationType`` with no entry here would raise ``KeyError``
    inside the send path at runtime; this fails at collection time instead.
    """
    assert set(PREFERENCE_FIELD_FOR_TYPE) == set(NotificationType)


def test_every_preference_field_exists_on_the_preferences_row() -> None:
    """Each mapped field name must actually exist on the preferences dataclass."""
    from lemely.db.notification_prefs_repo import DEFAULTS

    for field_name in PREFERENCE_FIELD_FOR_TYPE.values():
        assert hasattr(DEFAULTS, field_name), field_name


# ── Quiet-hours arithmetic (pure, no DB) ────────────────────────────────────


@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        (time(23, 0), True),  # after start, before midnight
        (time(2, 0), True),  # after midnight, before end
        (time(21, 59), False),  # a minute before the window opens
        (time(7, 0), False),  # end is exclusive
        (time(12, 0), False),  # broad daylight
    ],
)
def test_quiet_hours_window_wraps_midnight(moment: time, expected: bool) -> None:
    """22:00→07:00 is the *normal* configuration and a naive comparison matches nothing."""
    assert is_within_quiet_hours(moment, time(22, 0), time(7, 0)) is expected


@pytest.mark.parametrize(
    ("moment", "expected"),
    [(time(10, 0), True), (time(8, 59), False), (time(17, 0), False)],
)
def test_quiet_hours_window_within_one_day(moment: time, expected: bool) -> None:
    assert is_within_quiet_hours(moment, time(9, 0), time(17, 0)) is expected


@pytest.mark.parametrize(
    ("start", "end"),
    [(time(22, 0), None), (None, time(7, 0)), (None, None)],
)
def test_a_half_configured_window_is_not_a_window(start: time | None, end: time | None) -> None:
    """Treating one set bound as an open-ended window would disable push forever."""
    assert is_within_quiet_hours(time(23, 30), start, end) is False


def test_zero_length_window_is_no_quiet_hours() -> None:
    """``start == end`` reads as "none", never as 24 hours of silence."""
    assert is_within_quiet_hours(time(3, 0), time(22, 0), time(22, 0)) is False


def test_civil_time_is_local_not_utc() -> None:
    """23:00 UTC is 02:00 in Cairo in August — a UTC clock is three hours wrong here.

    Three, not two: Egypt reinstated summer time in 2023, so Cairo is UTC+3
    from late April to late October. That is exactly why this converts through
    ``ZoneInfo`` rather than adding a fixed offset — a hardcoded +2 would put
    every August quiet-hours decision an hour out, and only an hour, which is
    the size of error nobody notices until a student is woken at 07:30.
    """
    august = datetime(2026, 8, 10, 23, 0, tzinfo=UTC)
    january = datetime(2026, 1, 10, 23, 0, tzinfo=UTC)

    assert civil_time_in_zone(august, zone=CAIRO) == time(2, 0)
    assert civil_time_in_zone(january, zone=CAIRO) == time(1, 0)


def test_civil_time_rejects_a_naive_datetime() -> None:
    with pytest.raises(ValueError, match="aware datetime"):
        civil_time_in_zone(datetime(2026, 8, 10, 23, 0), zone=CAIRO)


# ── create: the preference gate ─────────────────────────────────────────────


def test_a_user_with_no_preferences_row_receives_everything(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """No row means opted-IN. Reading absence as opt-out silences everyone who never
    opened settings."""
    user = _seed_user(pg_sessionmaker)
    service = _service(pg_sessionmaker)

    result = service.create(user, NotificationType.grade_ready, "Your paper is marked")

    assert result.outcome is NotificationOutcome.created
    assert result.push_allowed is True
    assert result.row is not None
    assert _notification_count(pg_sessionmaker) == 1


def test_a_type_toggled_off_writes_no_row_at_all(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """D5.9 §2: a type toggle is a *content* preference, so it suppresses the row."""
    user = _seed_user(pg_sessionmaker)
    NotificationPreferencesService(pg_sessionmaker).set(user, grade_ready=False)
    service = _service(pg_sessionmaker)

    result = service.create(user, NotificationType.grade_ready, "Your paper is marked")

    assert result.outcome is NotificationOutcome.opted_out
    assert result.row is None
    assert result.push_allowed is False
    assert _notification_count(pg_sessionmaker) == 0


def test_toggling_one_type_off_leaves_the_others_alone(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The gate must read the mapped column, not any truthy preference."""
    user = _seed_user(pg_sessionmaker)
    NotificationPreferencesService(pg_sessionmaker).set(user, grade_ready=False)
    service = _service(pg_sessionmaker)

    blocked = service.create(user, NotificationType.grade_ready, "marked")
    allowed = service.create(user, NotificationType.announcement, "Class notice")

    assert blocked.outcome is NotificationOutcome.opted_out
    assert allowed.outcome is NotificationOutcome.created


# ── create: quiet hours suppress the push, never the row ────────────────────


def test_quiet_hours_write_the_row_and_only_block_the_push(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The inverse of the toggle test, and the pair is the whole of D5.9 §2.

    Losing the row here would mean a student never learns their grade is ready
    for the sole reason that the marking finished while they were asleep.
    """
    user = _seed_user(pg_sessionmaker)
    NotificationPreferencesService(pg_sessionmaker).set(
        user, quiet_hours_start=time(22, 0), quiet_hours_end=time(7, 0)
    )
    # 00:30 Cairo == 22:30 UTC the previous day.
    service = _service(pg_sessionmaker, now=datetime(2026, 8, 9, 22, 30, tzinfo=UTC))

    result = service.create(user, NotificationType.grade_ready, "Your paper is marked")

    assert result.outcome is NotificationOutcome.created
    assert result.row is not None
    assert result.push_allowed is False
    assert result.push_suppressed_reason == "quiet_hours"
    assert _notification_count(pg_sessionmaker) == 1


def test_outside_quiet_hours_the_push_is_allowed(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    user = _seed_user(pg_sessionmaker)
    NotificationPreferencesService(pg_sessionmaker).set(
        user, quiet_hours_start=time(22, 0), quiet_hours_end=time(7, 0)
    )
    # 15:00 Cairo == 12:00 UTC.
    service = _service(pg_sessionmaker, now=datetime(2026, 8, 10, 12, 0, tzinfo=UTC))

    result = service.create(user, NotificationType.grade_ready, "Your paper is marked")

    assert result.push_allowed is True
    assert result.push_suppressed_reason is None


def test_an_explicit_now_overrides_the_injected_clock(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    user = _seed_user(pg_sessionmaker)
    NotificationPreferencesService(pg_sessionmaker).set(
        user, quiet_hours_start=time(22, 0), quiet_hours_end=time(7, 0)
    )
    service = _service(pg_sessionmaker, now=datetime(2026, 8, 10, 12, 0, tzinfo=UTC))

    result = service.create(
        user,
        NotificationType.grade_ready,
        "marked",
        now=datetime(2026, 8, 9, 22, 30, tzinfo=UTC),
    )

    assert result.push_allowed is False


# ── create: dedupe ──────────────────────────────────────────────────────────


def test_the_same_dedupe_key_never_creates_a_second_row(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """D5.9 §6 / D5.3: a re-corrected paper must not re-notify."""
    user = _seed_user(pg_sessionmaker)
    service = _service(pg_sessionmaker)
    upload = uuid.uuid4()

    first = service.create(
        user, NotificationType.grade_ready, "marked", dedupe_key=f"upload:{upload}"
    )
    second = service.create(
        user, NotificationType.grade_ready, "marked again", dedupe_key=f"upload:{upload}"
    )

    assert first.outcome is NotificationOutcome.created
    assert second.outcome is NotificationOutcome.duplicate
    assert second.row is None
    assert second.push_allowed is False
    assert _notification_count(pg_sessionmaker) == 1


def test_dedupe_is_scoped_per_user(pg_sessionmaker: sessionmaker[Session]) -> None:
    """Two students in one class must each get their own copy of the same event."""
    first_user = _seed_user(pg_sessionmaker)
    second_user = _seed_user(pg_sessionmaker)
    service = _service(pg_sessionmaker)
    key = f"announcement:{uuid.uuid4()}"

    a = service.create(first_user, NotificationType.announcement, "Notice", dedupe_key=key)
    b = service.create(second_user, NotificationType.announcement, "Notice", dedupe_key=key)

    assert a.outcome is NotificationOutcome.created
    assert b.outcome is NotificationOutcome.created
    assert _notification_count(pg_sessionmaker) == 2


def test_dedupe_is_scoped_per_type(pg_sessionmaker: sessionmaker[Session]) -> None:
    """Two types deriving the same key from one row are not duplicates of each other."""
    user = _seed_user(pg_sessionmaker)
    service = _service(pg_sessionmaker)
    key = f"paper:{uuid.uuid4()}"

    a = service.create(user, NotificationType.grade_ready, "marked", dedupe_key=key)
    b = service.create(user, NotificationType.at_risk_alert, "at risk", dedupe_key=key)

    assert a.outcome is NotificationOutcome.created
    assert b.outcome is NotificationOutcome.created


def test_notifications_without_a_dedupe_key_are_never_deduped(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """Two study-plan reminders a week apart are two reminders, not a duplicate.

    The partial index is ``WHERE dedupe_key IS NOT NULL`` precisely so this
    stays possible — D5.3's split, where the paper seam dedupes and the
    flashcard seam deliberately does not.
    """
    user = _seed_user(pg_sessionmaker)
    service = _service(pg_sessionmaker)

    first = service.create(user, NotificationType.study_plan_reminder, "Session due")
    second = service.create(user, NotificationType.study_plan_reminder, "Session due")

    assert first.outcome is NotificationOutcome.created
    assert second.outcome is NotificationOutcome.created
    assert _notification_count(pg_sessionmaker) == 2


# ── Reading ─────────────────────────────────────────────────────────────────


def test_list_is_newest_first_and_scoped_to_the_user(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    mine = _seed_user(pg_sessionmaker)
    theirs = _seed_user(pg_sessionmaker)
    service = _service(pg_sessionmaker)

    service.create(mine, NotificationType.announcement, "first")
    service.create(mine, NotificationType.announcement, "second")
    service.create(theirs, NotificationType.announcement, "not mine")

    rows = service.list_for_user(mine)

    assert [row.title for row in rows] == ["second", "first"]
    assert all(row.user_id == mine for row in rows)


def test_unread_only_filters_and_counts_agree(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    user = _seed_user(pg_sessionmaker)
    service = _service(pg_sessionmaker)
    first = service.create(user, NotificationType.announcement, "one").row
    service.create(user, NotificationType.grade_ready, "two")
    assert first is not None

    service.mark_read(user, first.id)

    assert [row.title for row in service.list_for_user(user, unread_only=True)] == ["two"]
    counts = service.counts(user)
    assert counts.total == 2
    assert counts.unread == 1
    assert counts.by_type == {NotificationType.grade_ready: 1}


def test_counts_for_a_user_with_no_notifications_are_zero(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """An empty inbox must read as 0/0, never crash on a ``SUM`` over no rows."""
    user = _seed_user(pg_sessionmaker)
    counts = _service(pg_sessionmaker).counts(user)

    assert counts.unread == 0
    assert counts.total == 0
    assert counts.by_type == {}


def test_list_limit_is_capped(pg_sessionmaker: sessionmaker[Session]) -> None:
    user = _seed_user(pg_sessionmaker)
    service = _service(pg_sessionmaker)
    for index in range(3):
        service.create(user, NotificationType.announcement, f"n{index}")

    assert len(service.list_for_user(user, limit=2)) == 2
    assert len(service.list_for_user(user, limit=0)) == 1  # floored at 1, never unbounded


# ── Marking read ────────────────────────────────────────────────────────────


def test_mark_read_is_idempotent_and_keeps_the_first_read_time(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    user = _seed_user(pg_sessionmaker)
    service = _service(pg_sessionmaker)
    created = service.create(user, NotificationType.announcement, "notice").row
    assert created is not None

    first = service.mark_read(user, created.id, now=datetime(2026, 8, 10, 9, 0, tzinfo=UTC))
    second = service.mark_read(user, created.id, now=datetime(2026, 8, 10, 18, 0, tzinfo=UTC))

    assert first is not None
    assert second is not None
    assert first.read_at == second.read_at


def test_mark_read_on_another_users_notification_returns_none(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """Not-yours and does-not-exist must be indistinguishable — no existence oracle."""
    mine = _seed_user(pg_sessionmaker)
    theirs = _seed_user(pg_sessionmaker)
    service = _service(pg_sessionmaker)
    created = service.create(theirs, NotificationType.announcement, "theirs").row
    assert created is not None

    assert service.mark_read(mine, created.id) is None
    assert service.mark_read(mine, uuid.uuid4()) is None

    with pg_sessionmaker() as session:
        still_unread = session.get(Notification, created.id)
        assert still_unread is not None
        assert still_unread.read_at is None


def test_mark_all_read_returns_the_number_changed_and_is_idempotent(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    user = _seed_user(pg_sessionmaker)
    service = _service(pg_sessionmaker)
    service.create(user, NotificationType.announcement, "one")
    service.create(user, NotificationType.grade_ready, "two")

    assert service.mark_all_read(user) == 2
    assert service.mark_all_read(user) == 0
    assert service.counts(user).unread == 0


def test_mark_read_rejects_a_malformed_uuid(pg_sessionmaker: sessionmaker[Session]) -> None:
    service = _service(pg_sessionmaker)
    with pytest.raises(ValueError, match="Identifier must be a UUID"):
        service.mark_read("not-a-uuid", uuid.uuid4())


# ── Push subscriptions ──────────────────────────────────────────────────────


def test_subscribe_is_idempotent_per_endpoint(pg_sessionmaker: sessionmaker[Session]) -> None:
    user = _seed_user(pg_sessionmaker)
    service = _service(pg_sessionmaker)

    first = service.subscribe(user, "https://push.example/abc", "key-1", "auth-1")
    second = service.subscribe(user, "https://push.example/abc", "key-2", "auth-2")

    assert first.id == second.id
    assert second.p256dh == "key-2"  # rotated keys are refreshed, not duplicated
    assert len(service.subscriptions_for(user)) == 1


def test_resubscribing_another_users_endpoint_moves_the_row(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """An endpoint identifies a browser, not a person.

    If this kept both rows, the first user's notifications would keep being
    pushed to a browser the second user is now signed into — a privacy
    defect, not a duplicate-row nuisance.
    """
    first_user = _seed_user(pg_sessionmaker)
    second_user = _seed_user(pg_sessionmaker)
    service = _service(pg_sessionmaker)
    endpoint = "https://push.example/shared-browser"

    service.subscribe(first_user, endpoint, "k1", "a1")
    service.subscribe(second_user, endpoint, "k2", "a2")

    assert service.subscriptions_for(first_user) == []
    assert [row.endpoint for row in service.subscriptions_for(second_user)] == [endpoint]
    with pg_sessionmaker() as session:
        assert int(session.scalar(select(func.count()).select_from(PushSubscription)) or 0) == 1


def test_unsubscribe_is_scoped_to_the_caller(pg_sessionmaker: sessionmaker[Session]) -> None:
    """One user must not be able to unsubscribe another's browser by guessing an endpoint."""
    owner = _seed_user(pg_sessionmaker)
    stranger = _seed_user(pg_sessionmaker)
    service = _service(pg_sessionmaker)
    endpoint = "https://push.example/owned"
    service.subscribe(owner, endpoint, "k", "a")

    assert service.unsubscribe(stranger, endpoint) is False
    assert len(service.subscriptions_for(owner)) == 1

    assert service.unsubscribe(owner, endpoint) is True
    assert service.subscriptions_for(owner) == []


def test_forget_endpoint_is_not_user_scoped(pg_sessionmaker: sessionmaker[Session]) -> None:
    """The 404/410 cleanup path has no caller identity — it is the push service speaking."""
    owner = _seed_user(pg_sessionmaker)
    service = _service(pg_sessionmaker)
    endpoint = "https://push.example/dead"
    service.subscribe(owner, endpoint, "k", "a")

    assert service.forget_endpoint(endpoint) is True
    assert service.forget_endpoint(endpoint) is False
    assert service.subscriptions_for(owner) == []


def test_subscribe_rejects_an_empty_endpoint(pg_sessionmaker: sessionmaker[Session]) -> None:
    user = _seed_user(pg_sessionmaker)
    with pytest.raises(ValueError, match="endpoint must not be empty"):
        _service(pg_sessionmaker).subscribe(user, "", "k", "a")


def test_deleting_a_user_takes_their_subscriptions_with_them(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """A deleted user must not leave live endpoints still receiving their notifications."""
    user = _seed_user(pg_sessionmaker)
    service = _service(pg_sessionmaker)
    service.subscribe(user, "https://push.example/cascade", "k", "a")

    with pg_sessionmaker.begin() as session:
        session.execute(sa.delete(User).where(User.id == user))

    with pg_sessionmaker() as session:
        assert int(session.scalar(select(func.count()).select_from(PushSubscription)) or 0) == 0
