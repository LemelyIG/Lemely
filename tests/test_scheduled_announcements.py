"""The announcement sweeper job (push-delivery spec §1).

``notified_at`` means "fan-out for this row completed". The job claims due rows
with ``FOR UPDATE SKIP LOCKED``, fans out through the same code the composer
uses, and stamps **after** the send: a crash between the two re-runs the row,
and migration 0018's unique index makes the re-run harmless.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.db.announcement_repo import AnnouncementService
from lemely.db.base import Base
from lemely.db.class_repo import ClassService
from lemely.db.models import Announcement, User
from lemely.db.models.enums import Role
from lemely.db.models.orgs import ClassEnrollment
from lemely.db.notification_prefs_repo import NotificationPreferencesService
from lemely.db.notification_repo import NotificationService
from lemely.runtime.config import DatabaseSettings
from lemely.web.push import RecordingPushTransport
from lemely.web.scheduled_notifications import publish_due_announcements

if TYPE_CHECKING:
    from collections.abc import Iterator

NOW = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)


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


@pytest.fixture
def class_service(pg_sessionmaker: sessionmaker[Session]) -> ClassService:
    return ClassService(pg_sessionmaker)


@pytest.fixture
def announcements(
    pg_sessionmaker: sessionmaker[Session], class_service: ClassService
) -> AnnouncementService:
    return AnnouncementService(pg_sessionmaker, class_service, now=lambda: NOW)


@pytest.fixture
def notifications(pg_sessionmaker: sessionmaker[Session]) -> NotificationService:
    return NotificationService(
        pg_sessionmaker, NotificationPreferencesService(pg_sessionmaker), now=lambda: NOW
    )


@pytest.fixture
def transport() -> RecordingPushTransport:
    return RecordingPushTransport()


def _seed_user(sm: sessionmaker[Session], role: Role = Role.student) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role))
    return uid


def _enroll(sm: sessionmaker[Session], class_id: uuid.UUID, student_id: uuid.UUID) -> None:
    with sm.begin() as session:
        session.add(ClassEnrollment(class_id=class_id, student_id=student_id))


def _subscribe(notifications: NotificationService, user: uuid.UUID) -> str:
    endpoint = f"https://push.example.test/{user}"
    notifications.subscribe(user, endpoint, "p256dh", "auth")
    return endpoint


def _class_with_students(
    sm: sessionmaker[Session], class_service: ClassService, count: int
) -> tuple[uuid.UUID, uuid.UUID, list[uuid.UUID]]:
    teacher = _seed_user(sm, Role.teacher)
    cls = class_service.create_class(teacher, "Physics 10A")
    students = [_seed_user(sm) for _ in range(count)]
    for student in students:
        _enroll(sm, cls.class_id, student)
    return teacher, cls.class_id, students


def _scheduled(
    announcements: AnnouncementService,
    teacher: uuid.UUID,
    class_id: uuid.UUID,
    *,
    publish_at: datetime | None,
) -> uuid.UUID:
    rows = announcements.create(
        teacher,
        Role.teacher,
        title="Trip forms",
        body="Due Monday.",
        class_ids=[class_id],
        publish_at=publish_at,
    )
    return rows[0].announcement_id


def _notified_at(sm: sessionmaker[Session], announcement_id: uuid.UUID) -> datetime | None:
    with sm() as session:
        return session.scalar(
            select(Announcement.notified_at).where(Announcement.id == announcement_id)
        )


def _inbox(notifications: NotificationService, user: uuid.UUID) -> list[str]:
    return [row.payload["announcementId"] for row in notifications.list_for_user(user)]


def test_the_job_claims_a_due_row_fans_out_to_the_audience_and_stamps_it(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    announcements: AnnouncementService,
    notifications: NotificationService,
    transport: RecordingPushTransport,
) -> None:
    teacher, class_id, students = _class_with_students(pg_sessionmaker, class_service, 3)
    for student in students:
        _subscribe(notifications, student)
    announcement_id = _scheduled(
        announcements, teacher, class_id, publish_at=NOW - timedelta(minutes=1)
    )

    claimed = publish_due_announcements(announcements, notifications, transport, now=NOW)

    assert claimed == 1
    for student in students:
        assert _inbox(notifications, student) == [str(announcement_id)]
    assert len(transport.endpoints) == 3
    assert _notified_at(pg_sessionmaker, announcement_id) == NOW


def test_the_job_ignores_rows_already_stamped_and_rows_not_yet_due(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    announcements: AnnouncementService,
    notifications: NotificationService,
    transport: RecordingPushTransport,
) -> None:
    teacher, class_id, students = _class_with_students(pg_sessionmaker, class_service, 1)
    stamped = _scheduled(announcements, teacher, class_id, publish_at=NOW - timedelta(hours=1))
    announcements.mark_notified([stamped], now=NOW - timedelta(hours=1))
    future = _scheduled(announcements, teacher, class_id, publish_at=NOW + timedelta(hours=1))
    immediate = _scheduled(announcements, teacher, class_id, publish_at=None)

    claimed = publish_due_announcements(announcements, notifications, transport, now=NOW)

    # ``publish_at IS NULL`` rows are the composer's to notify at create time,
    # never the sweeper's: a NULL is "published immediately", not "due".
    assert claimed == 0
    assert _inbox(notifications, students[0]) == []
    assert _notified_at(pg_sessionmaker, future) is None
    assert _notified_at(pg_sessionmaker, immediate) is None


def test_a_run_interrupted_between_send_and_stamp_is_harmless_when_re_run(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    announcements: AnnouncementService,
    notifications: NotificationService,
    transport: RecordingPushTransport,
) -> None:
    """The direct test of stamp-after-send. The fan-out completes, the stamp
    never lands (the claim's transaction rolls back), and the next pass finds
    the row still unstamped. The unique index rejects the second inbox row,
    ``create`` answers ``duplicate`` with ``push_allowed=False``, and no
    second push is attempted."""
    from lemely.web.scheduled_notifications import notify_announcement_audience

    teacher, class_id, students = _class_with_students(pg_sessionmaker, class_service, 2)
    for student in students:
        _subscribe(notifications, student)
    announcement_id = _scheduled(
        announcements, teacher, class_id, publish_at=NOW - timedelta(minutes=5)
    )

    class _Crash(RuntimeError):
        pass

    with pytest.raises(_Crash), announcements.claim_due(now=NOW) as claim:
        assert [row.announcement_id for row in claim.rows] == [announcement_id]
        assert notify_announcement_audience(announcements, notifications, transport, claim.rows)
        raise _Crash  # before claim.stamp(): the send happened, the stamp did not

    assert _notified_at(pg_sessionmaker, announcement_id) is None
    assert len(transport.endpoints) == 2
    transport.reset()

    claimed = publish_due_announcements(announcements, notifications, transport, now=NOW)

    assert claimed == 1
    for student in students:
        assert _inbox(notifications, student) == [str(announcement_id)]
    assert transport.endpoints == []
    assert _notified_at(pg_sessionmaker, announcement_id) == NOW


def test_two_concurrent_runs_do_not_both_claim_one_row(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    announcements: AnnouncementService,
    notifications: NotificationService,
    transport: RecordingPushTransport,
) -> None:
    """``SKIP LOCKED`` is what makes two replicas safe without a lock table.
    A second session holds the row's lock; the job sees nothing to do. Once the
    lock is released the row is claimed normally."""
    teacher, class_id, students = _class_with_students(pg_sessionmaker, class_service, 1)
    announcement_id = _scheduled(
        announcements, teacher, class_id, publish_at=NOW - timedelta(minutes=5)
    )

    with pg_sessionmaker() as other, other.begin():
        other.execute(
            select(Announcement).where(Announcement.id == announcement_id).with_for_update()
        ).all()
        assert publish_due_announcements(announcements, notifications, transport, now=NOW) == 0
        assert _inbox(notifications, students[0]) == []

    assert publish_due_announcements(announcements, notifications, transport, now=NOW) == 1
    assert _inbox(notifications, students[0]) == [str(announcement_id)]


def test_a_second_pass_after_a_stamp_does_nothing(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    announcements: AnnouncementService,
    notifications: NotificationService,
    transport: RecordingPushTransport,
) -> None:
    teacher, class_id, students = _class_with_students(pg_sessionmaker, class_service, 1)
    _scheduled(announcements, teacher, class_id, publish_at=NOW - timedelta(minutes=5))

    assert publish_due_announcements(announcements, notifications, transport, now=NOW) == 1
    assert publish_due_announcements(announcements, notifications, transport, now=NOW) == 0
    assert len(_inbox(notifications, students[0])) == 1
