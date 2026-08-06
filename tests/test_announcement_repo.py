"""Postgres integration tests for the announcement service (D3.14/P3.8 chunk a).

Exercises :class:`~lemely.db.announcement_repo.AnnouncementService` against a
throwaway database and skips cleanly when no local server is reachable
(mirrors ``tests/test_class_repo.py``/``tests/test_parent_repo.py``, whose
``pg_sessionmaker`` fixture and seed-helper style this file duplicates
verbatim per this repo's convention). Proves the guarantees D3.14 requires:

* Multi-class fan-out writes exactly N rows, one per class, sharing title/body.
* A teacher cannot post to another teacher's class — 403, and **nothing is
  written**, even for the classes they legitimately own in the same call.
* School-wide is ``school_admin``-only; a teacher requesting it is rejected
  before any row is written.
* ``list_for_author`` never returns another author's rows, newest first.
* ``delete`` is author-scoped; deleting someone else's row is not a silent
  no-op and leaves the row intact.
* ``publish_at`` round-trips, including ``None``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.db.announcement_repo import (
    AnnouncementNotFoundError,
    AnnouncementOwnershipError,
    AnnouncementService,
    AnnouncementValidationError,
)
from lemely.db.base import Base
from lemely.db.class_repo import ClassService
from lemely.db.models import Announcement, School, SchoolMembership, User
from lemely.db.models.enums import MembershipRole, Role
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


@pytest.fixture
def class_service(pg_sessionmaker: sessionmaker[Session]) -> ClassService:
    return ClassService(pg_sessionmaker)


@pytest.fixture
def service(
    pg_sessionmaker: sessionmaker[Session], class_service: ClassService
) -> AnnouncementService:
    return AnnouncementService(pg_sessionmaker, class_service)


# ── Seed helpers ────────────────────────────────────────────────────────────


def _seed_user(
    sm: sessionmaker[Session], role: Role = Role.teacher, display_name: str | None = None
) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role, display_name=display_name))
    return uid


def _seed_school(sm: sessionmaker[Session], *, admin_id: uuid.UUID | None = None) -> uuid.UUID:
    school_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(School(id=school_id, name="Test School", seat_quota=5))
        if admin_id is not None:
            session.add(
                SchoolMembership(
                    school_id=school_id,
                    user_id=admin_id,
                    membership_role=MembershipRole.school_admin,
                )
            )
    return school_id


def _announcement_count(sm: sessionmaker[Session]) -> int:
    with sm() as session:
        return int(session.scalar(select(func.count()).select_from(Announcement)) or 0)


def _all_announcements(sm: sessionmaker[Session]) -> list[Announcement]:
    with sm() as session:
        return list(session.scalars(select(Announcement)).all())


# ── create: multi-class fan-out ─────────────────────────────────────────────


def test_create_writes_one_row_per_class_with_shared_title_and_body(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    service: AnnouncementService,
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    cls_a = class_service.create_class(teacher, "Physics 10A")
    cls_b = class_service.create_class(teacher, "Physics 10B")
    cls_c = class_service.create_class(teacher, "Physics 11A")

    rows = service.create(
        teacher,
        Role.teacher,
        title="Test schedule",
        body="Bring calculators.",
        class_ids=[cls_a.class_id, cls_b.class_id, cls_c.class_id],
    )

    assert len(rows) == 3
    assert {r.class_id for r in rows} == {cls_a.class_id, cls_b.class_id, cls_c.class_id}
    assert all(r.school_id is None for r in rows)
    assert all(r.title == "Test schedule" for r in rows)
    assert all(r.body == "Bring calculators." for r in rows)
    assert all(r.author_id == teacher for r in rows)
    assert _announcement_count(pg_sessionmaker) == 3


def test_create_single_class_writes_one_row(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    service: AnnouncementService,
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    cls = class_service.create_class(teacher, "Physics 10A")

    rows = service.create(teacher, Role.teacher, title="Hi", body="Body", class_ids=[cls.class_id])

    assert len(rows) == 1
    assert rows[0].class_id == cls.class_id
    assert rows[0].school_id is None


# ── create: cross-teacher rejection is all-or-nothing ───────────────────────


def test_teacher_cannot_post_to_another_teachers_class_and_nothing_is_written(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    service: AnnouncementService,
) -> None:
    teacher_a = _seed_user(pg_sessionmaker, Role.teacher)
    teacher_b = _seed_user(pg_sessionmaker, Role.teacher)
    own_cls_1 = class_service.create_class(teacher_a, "Own class 1")
    own_cls_2 = class_service.create_class(teacher_a, "Own class 2")
    other_cls = class_service.create_class(teacher_b, "Someone else's class")

    with pytest.raises(AnnouncementOwnershipError):
        service.create(
            teacher_a,
            Role.teacher,
            title="Hi",
            body="Body",
            class_ids=[own_cls_1.class_id, own_cls_2.class_id, other_cls.class_id],
        )

    # Not a partial fan-out: none of the two legitimate classes got a row either.
    assert _announcement_count(pg_sessionmaker) == 0


def test_unknown_class_id_is_not_found_and_nothing_is_written(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    service: AnnouncementService,
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    own_cls = class_service.create_class(teacher, "Own class")

    with pytest.raises(AnnouncementNotFoundError):
        service.create(
            teacher,
            Role.teacher,
            title="Hi",
            body="Body",
            class_ids=[own_cls.class_id, uuid.uuid4()],
        )

    assert _announcement_count(pg_sessionmaker) == 0


# ── create: school-wide is school_admin-only ────────────────────────────────


def test_teacher_requesting_school_wide_is_rejected(
    pg_sessionmaker: sessionmaker[Session],
    service: AnnouncementService,
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    school = _seed_school(pg_sessionmaker)

    with pytest.raises(AnnouncementOwnershipError):
        service.create(
            teacher,
            Role.teacher,
            title="Hi",
            body="Body",
            school_wide=True,
            school_id=school,
        )

    assert _announcement_count(pg_sessionmaker) == 0


def test_school_admin_school_wide_writes_one_row_with_class_id_null(
    pg_sessionmaker: sessionmaker[Session],
    service: AnnouncementService,
) -> None:
    admin = _seed_user(pg_sessionmaker, Role.school_admin)
    school = _seed_school(pg_sessionmaker, admin_id=admin)

    rows = service.create(
        admin,
        Role.school_admin,
        title="School closed Friday",
        body="Staff training day.",
        school_wide=True,
        school_id=school,
    )

    assert len(rows) == 1
    assert rows[0].school_id == school
    assert rows[0].class_id is None


def test_school_admin_cannot_go_school_wide_for_a_school_they_do_not_administer(
    pg_sessionmaker: sessionmaker[Session],
    service: AnnouncementService,
) -> None:
    admin = _seed_user(pg_sessionmaker, Role.school_admin)
    other_school = _seed_school(pg_sessionmaker)  # admin has no membership here

    with pytest.raises(AnnouncementOwnershipError):
        service.create(
            admin,
            Role.school_admin,
            title="Hi",
            body="Body",
            school_wide=True,
            school_id=other_school,
        )

    assert _announcement_count(pg_sessionmaker) == 0


def test_school_wide_without_school_id_is_a_validation_error(
    pg_sessionmaker: sessionmaker[Session],
    service: AnnouncementService,
) -> None:
    admin = _seed_user(pg_sessionmaker, Role.school_admin)

    with pytest.raises(AnnouncementValidationError):
        service.create(admin, Role.school_admin, title="Hi", body="Body", school_wide=True)


def test_no_target_at_all_is_a_validation_error(
    pg_sessionmaker: sessionmaker[Session],
    service: AnnouncementService,
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)

    with pytest.raises(AnnouncementValidationError):
        service.create(teacher, Role.teacher, title="Hi", body="Body")


# ── list_for_author ──────────────────────────────────────────────────────────


def test_list_for_author_never_returns_another_authors_rows(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    service: AnnouncementService,
) -> None:
    teacher_a = _seed_user(pg_sessionmaker, Role.teacher)
    teacher_b = _seed_user(pg_sessionmaker, Role.teacher)
    cls_a = class_service.create_class(teacher_a, "A's class")
    cls_b = class_service.create_class(teacher_b, "B's class")

    service.create(teacher_a, Role.teacher, title="A1", body="body", class_ids=[cls_a.class_id])
    service.create(teacher_b, Role.teacher, title="B1", body="body", class_ids=[cls_b.class_id])

    a_rows = service.list_for_author(teacher_a)
    assert [r.title for r in a_rows] == ["A1"]

    b_rows = service.list_for_author(teacher_b)
    assert [r.title for r in b_rows] == ["B1"]


def test_list_for_author_orders_newest_first(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    service: AnnouncementService,
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    cls = class_service.create_class(teacher, "A class")

    service.create(teacher, Role.teacher, title="First", body="body", class_ids=[cls.class_id])
    service.create(teacher, Role.teacher, title="Second", body="body", class_ids=[cls.class_id])
    service.create(teacher, Role.teacher, title="Third", body="body", class_ids=[cls.class_id])

    rows = service.list_for_author(teacher)
    assert [r.title for r in rows] == ["Third", "Second", "First"]


def test_list_for_author_empty_when_nothing_authored(
    pg_sessionmaker: sessionmaker[Session],
    service: AnnouncementService,
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    assert service.list_for_author(teacher) == []


# ── delete: author-scoped, never a silent no-op for someone else's row ──────


def test_delete_removes_the_authors_own_row(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    service: AnnouncementService,
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    cls = class_service.create_class(teacher, "A class")
    rows = service.create(teacher, Role.teacher, title="Hi", body="Body", class_ids=[cls.class_id])

    service.delete(teacher, rows[0].announcement_id)

    assert service.list_for_author(teacher) == []
    assert _announcement_count(pg_sessionmaker) == 0


def test_delete_someone_elses_announcement_is_forbidden_not_a_silent_noop(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    service: AnnouncementService,
) -> None:
    teacher_a = _seed_user(pg_sessionmaker, Role.teacher)
    teacher_b = _seed_user(pg_sessionmaker, Role.teacher)
    cls_a = class_service.create_class(teacher_a, "A's class")
    rows = service.create(
        teacher_a, Role.teacher, title="A's announcement", body="Body", class_ids=[cls_a.class_id]
    )

    with pytest.raises(AnnouncementOwnershipError):
        service.delete(teacher_b, rows[0].announcement_id)

    # The row must still exist — a rejected delete is not a silent no-op.
    remaining = _all_announcements(pg_sessionmaker)
    assert len(remaining) == 1
    assert remaining[0].id == rows[0].announcement_id


def test_delete_unknown_id_is_not_found(
    pg_sessionmaker: sessionmaker[Session],
    service: AnnouncementService,
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    with pytest.raises(AnnouncementNotFoundError):
        service.delete(teacher, uuid.uuid4())


def test_delete_malformed_id_raises_value_error(
    pg_sessionmaker: sessionmaker[Session],
    service: AnnouncementService,
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    with pytest.raises(ValueError, match="Identifier must be a UUID"):
        service.delete(teacher, "not-a-uuid")


# ── publish_at round-trip ────────────────────────────────────────────────────


def test_publish_at_round_trips_when_set(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    service: AnnouncementService,
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    cls = class_service.create_class(teacher, "A class")
    scheduled = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)

    rows = service.create(
        teacher,
        Role.teacher,
        title="Hi",
        body="Body",
        class_ids=[cls.class_id],
        publish_at=scheduled,
    )

    assert rows[0].publish_at == scheduled
    listed = service.list_for_author(teacher)
    assert listed[0].publish_at == scheduled


def test_publish_at_round_trips_as_none(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    service: AnnouncementService,
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    cls = class_service.create_class(teacher, "A class")

    rows = service.create(teacher, Role.teacher, title="Hi", body="Body", class_ids=[cls.class_id])

    assert rows[0].publish_at is None
    listed = service.list_for_author(teacher)
    assert listed[0].publish_at is None


def test_publish_at_in_the_past_is_not_an_error(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    service: AnnouncementService,
) -> None:
    """A past ``publish_at`` means "already published" — not a validation failure."""
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    cls = class_service.create_class(teacher, "A class")
    past = datetime(2020, 1, 1, tzinfo=UTC)

    rows = service.create(
        teacher, Role.teacher, title="Hi", body="Body", class_ids=[cls.class_id], publish_at=past
    )

    assert rows[0].publish_at == past
