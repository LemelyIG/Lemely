"""The student-facing announcement read path (P5.5 chunk A).

Covers :meth:`~lemely.db.announcement_repo.AnnouncementService.list_for_student`,
``unread_count_for_student`` and ``mark_read`` against a real Postgres, in the
same throwaway-database style as :mod:`tests.test_announcement_repo`.

Membership is seeded **through the session**, not through ``ClassService`` /
``SeatService``, so these tests pin what the announcement query itself resolves
rather than re-testing another service's behaviour.

Three things here are load-bearing and each has a test that fails loudly if
someone "simplifies" it:

* the school arm keys on ``Seat``, not ``SchoolMembership`` (D5.4);
* a future ``publish_at`` hides a row from students but **not** from its author;
* ``mark_read`` is idempotent and never moves the first-read timestamp.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.db.announcement_repo import AnnouncementNotFoundError, AnnouncementService
from lemely.db.base import Base
from lemely.db.class_repo import ClassService
from lemely.db.models import (
    AnnouncementRead,
    ClassEnrollment,
    School,
    SchoolMembership,
    Seat,
    User,
)
from lemely.db.models.enums import MembershipRole, Role, SeatStatus
from lemely.runtime.config import DatabaseSettings

if TYPE_CHECKING:
    from collections.abc import Iterator

# A fixed "now" so every publish_at in this module is unambiguously before or
# after it. Injected, never read from the wall clock (the service takes now=).
NOW = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)


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
    return AnnouncementService(pg_sessionmaker, class_service, now=lambda: NOW)


# ── Seed helpers ────────────────────────────────────────────────────────────


def _seed_user(sm: sessionmaker[Session], role: Role = Role.student) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role, display_name="Someone"))
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


def _enroll(sm: sessionmaker[Session], class_id: uuid.UUID, student_id: uuid.UUID) -> None:
    with sm.begin() as session:
        session.add(ClassEnrollment(class_id=class_id, student_id=student_id))


def _seat(
    sm: sessionmaker[Session],
    school_id: uuid.UUID,
    student_id: uuid.UUID,
    status: SeatStatus = SeatStatus.assigned,
) -> None:
    with sm.begin() as session:
        session.add(Seat(school_id=school_id, assigned_user_id=student_id, status=status))


def _titles(rows: list) -> list[str]:  # type: ignore[type-arg]
    return [r.announcement.title for r in rows]


# ── Audience resolution ─────────────────────────────────────────────────────


def test_student_sees_announcement_for_a_class_they_are_enrolled_in(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    service: AnnouncementService,
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    student = _seed_user(pg_sessionmaker)
    cls = class_service.create_class(teacher, "Physics 10A")
    _enroll(pg_sessionmaker, cls.class_id, student)

    service.create(
        teacher, Role.teacher, title="Bring calculators", body="b", class_ids=[cls.class_id]
    )

    rows = service.list_for_student(student)
    assert _titles(rows) == ["Bring calculators"]
    assert rows[0].read_at is None


def test_student_does_not_see_a_class_they_are_not_enrolled_in(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    service: AnnouncementService,
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    student = _seed_user(pg_sessionmaker)
    mine = class_service.create_class(teacher, "Physics 10A")
    theirs = class_service.create_class(teacher, "Physics 10B")
    _enroll(pg_sessionmaker, mine.class_id, student)

    service.create(teacher, Role.teacher, title="Mine", body="b", class_ids=[mine.class_id])
    service.create(teacher, Role.teacher, title="Theirs", body="b", class_ids=[theirs.class_id])

    assert _titles(service.list_for_student(student)) == ["Mine"]


def test_school_wide_announcement_reaches_a_seated_student(
    pg_sessionmaker: sessionmaker[Session],
    service: AnnouncementService,
) -> None:
    """The school arm must key on ``Seat``, not ``SchoolMembership`` (D5.4).

    ``school_memberships`` is staff-only — its role vocabulary is exactly
    ``teacher``/``school_admin`` — so a student never has a row there. Keying
    the school audience on it would make every school-wide announcement
    permanently invisible to the students it was written for, and that reads
    as "the school never posts anything" rather than as a defect. P5.3 lost a
    chunk to exactly this trap.
    """
    admin = _seed_user(pg_sessionmaker, Role.school_admin)
    student = _seed_user(pg_sessionmaker)
    school = _seed_school(pg_sessionmaker, admin_id=admin)
    _seat(pg_sessionmaker, school, student)

    service.create(
        admin,
        Role.school_admin,
        title="Term starts Monday",
        body="b",
        school_wide=True,
        school_id=school,
    )

    assert _titles(service.list_for_student(student)) == ["Term starts Monday"]


def test_revoked_seat_stops_school_wide_delivery(
    pg_sessionmaker: sessionmaker[Session],
    service: AnnouncementService,
) -> None:
    admin = _seed_user(pg_sessionmaker, Role.school_admin)
    student = _seed_user(pg_sessionmaker)
    school = _seed_school(pg_sessionmaker, admin_id=admin)
    _seat(pg_sessionmaker, school, student, status=SeatStatus.revoked)

    service.create(
        admin, Role.school_admin, title="Term starts", body="b", school_wide=True, school_id=school
    )

    assert service.list_for_student(student) == []


def test_a_student_with_no_class_and_no_seat_sees_nothing(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    service: AnnouncementService,
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    stranger = _seed_user(pg_sessionmaker)
    cls = class_service.create_class(teacher, "Physics 10A")
    service.create(teacher, Role.teacher, title="Hi", body="b", class_ids=[cls.class_id])

    assert service.list_for_student(stranger) == []


# ── publish_at, which was inert before P5.5 ─────────────────────────────────


def test_a_future_publish_at_is_invisible_to_students(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    service: AnnouncementService,
) -> None:
    """Without this the composer's scheduling control is a lie.

    A teacher told the UI "send this next week"; if students can read it
    today, the control promised something the backend never honoured.
    """
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    student = _seed_user(pg_sessionmaker)
    cls = class_service.create_class(teacher, "Physics 10A")
    _enroll(pg_sessionmaker, cls.class_id, student)

    service.create(
        teacher,
        Role.teacher,
        title="Next week",
        body="b",
        class_ids=[cls.class_id],
        publish_at=NOW + timedelta(days=7),
    )

    assert service.list_for_student(student) == []


def test_a_past_publish_at_is_visible_and_null_means_immediately(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    service: AnnouncementService,
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    student = _seed_user(pg_sessionmaker)
    cls = class_service.create_class(teacher, "Physics 10A")
    _enroll(pg_sessionmaker, cls.class_id, student)

    service.create(
        teacher,
        Role.teacher,
        title="Yesterday",
        body="b",
        class_ids=[cls.class_id],
        publish_at=NOW - timedelta(days=1),
    )
    service.create(teacher, Role.teacher, title="Unscheduled", body="b", class_ids=[cls.class_id])

    assert set(_titles(service.list_for_student(student))) == {"Yesterday", "Unscheduled"}


def test_the_author_still_sees_their_own_scheduled_announcement(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    service: AnnouncementService,
) -> None:
    """Filtering is a property of the *student* view only.

    A teacher must be able to see and delete what they have queued, so
    ``list_for_author`` deliberately does not filter on ``publish_at``.
    """
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    cls = class_service.create_class(teacher, "Physics 10A")
    service.create(
        teacher,
        Role.teacher,
        title="Next week",
        body="b",
        class_ids=[cls.class_id],
        publish_at=NOW + timedelta(days=7),
    )

    assert [r.title for r in service.list_for_author(teacher)] == ["Next week"]


def test_ordering_is_by_effective_publication_time_not_creation_time(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    service: AnnouncementService,
) -> None:
    """A back-dated post sorts where its author meant it to.

    ``created_at`` alone would put whatever was typed last at the top, which
    is wrong for a row whose author explicitly dated it earlier.
    """
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    student = _seed_user(pg_sessionmaker)
    cls = class_service.create_class(teacher, "Physics 10A")
    _enroll(pg_sessionmaker, cls.class_id, student)

    service.create(
        teacher,
        Role.teacher,
        title="Recent",
        body="b",
        class_ids=[cls.class_id],
        publish_at=NOW - timedelta(hours=1),
    )
    # Written second, but dated a week ago — it must sort last.
    service.create(
        teacher,
        Role.teacher,
        title="Older",
        body="b",
        class_ids=[cls.class_id],
        publish_at=NOW - timedelta(days=7),
    )

    assert _titles(service.list_for_student(student)) == ["Recent", "Older"]


# ── Read receipts ───────────────────────────────────────────────────────────


def _one_visible(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    service: AnnouncementService,
) -> tuple[uuid.UUID, uuid.UUID]:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    student = _seed_user(pg_sessionmaker)
    cls = class_service.create_class(teacher, "Physics 10A")
    _enroll(pg_sessionmaker, cls.class_id, student)
    rows = service.create(teacher, Role.teacher, title="Hi", body="b", class_ids=[cls.class_id])
    return student, rows[0].announcement_id


def test_mark_read_records_a_receipt_and_the_list_reflects_it(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    service: AnnouncementService,
) -> None:
    student, announcement_id = _one_visible(pg_sessionmaker, class_service, service)

    assert service.list_for_student(student)[0].read_at is None
    assert service.mark_read(student, announcement_id) == NOW
    assert service.list_for_student(student)[0].read_at == NOW


def test_mark_read_is_idempotent_and_never_moves_the_first_read_time(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    service: AnnouncementService,
) -> None:
    """Re-opening an announcement must not append a row or re-stamp it.

    ``read_at`` is the *first* read; a "last opened" timestamp is a different
    feature, and silently turning one into the other would destroy the only
    number this table holds.
    """
    student, announcement_id = _one_visible(pg_sessionmaker, class_service, service)

    first = service.mark_read(student, announcement_id)

    later = AnnouncementService(
        pg_sessionmaker,
        ClassService(pg_sessionmaker),
        now=lambda: NOW + timedelta(days=3),
    )
    assert later.mark_read(student, announcement_id) == first

    with pg_sessionmaker() as session:
        assert int(session.scalar(select(func.count()).select_from(AnnouncementRead)) or 0) == 1


def test_marking_an_announcement_outside_your_scope_is_404_not_an_oracle(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    service: AnnouncementService,
) -> None:
    """ "Exists but not yours" and "does not exist" must be indistinguishable.

    A distinguishable error lets a student enumerate other classes'
    announcement ids by probing.
    """
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    outsider = _seed_user(pg_sessionmaker)
    cls = class_service.create_class(teacher, "Physics 10A")
    rows = service.create(teacher, Role.teacher, title="Hi", body="b", class_ids=[cls.class_id])

    with pytest.raises(AnnouncementNotFoundError) as real:
        service.mark_read(outsider, rows[0].announcement_id)
    with pytest.raises(AnnouncementNotFoundError) as absent:
        service.mark_read(outsider, uuid.uuid4())

    # Same exception type and same message shape — nothing distinguishes them.
    assert str(real.value).replace(str(rows[0].announcement_id), "X") == str(absent.value).replace(
        str(absent.value).split(": ")[-1], "X"
    )


def test_an_unpublished_announcement_cannot_be_marked_read(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    service: AnnouncementService,
) -> None:
    """``mark_read`` shares its scope definition with ``list_for_student``.

    If the two drifted, a student could mark-as-read something they cannot
    see listed — and, worse, confirm the existence of a scheduled post.
    """
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    student = _seed_user(pg_sessionmaker)
    cls = class_service.create_class(teacher, "Physics 10A")
    _enroll(pg_sessionmaker, cls.class_id, student)
    rows = service.create(
        teacher,
        Role.teacher,
        title="Next week",
        body="b",
        class_ids=[cls.class_id],
        publish_at=NOW + timedelta(days=7),
    )

    with pytest.raises(AnnouncementNotFoundError):
        service.mark_read(student, rows[0].announcement_id)


def test_unread_count_counts_absences_and_ignores_the_page_limit(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    service: AnnouncementService,
) -> None:
    """The count must not be ``len(list_for_student(...))``.

    That call is ``LIMIT``-ed, so deriving the count from it would tell a
    student with more unread announcements than the page size that they have
    exactly a page's worth.
    """
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    student = _seed_user(pg_sessionmaker)
    cls = class_service.create_class(teacher, "Physics 10A")
    _enroll(pg_sessionmaker, cls.class_id, student)

    created = [
        service.create(teacher, Role.teacher, title=f"A{i}", body="b", class_ids=[cls.class_id])[0]
        for i in range(5)
    ]

    assert service.unread_count_for_student(student) == 5
    service.mark_read(student, created[0].announcement_id)
    assert service.unread_count_for_student(student) == 4

    assert len(service.list_for_student(student, limit=2)) == 2
    assert service.unread_count_for_student(student) == 4


def test_unread_count_excludes_unpublished_and_out_of_scope_rows(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    service: AnnouncementService,
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    student = _seed_user(pg_sessionmaker)
    mine = class_service.create_class(teacher, "Physics 10A")
    theirs = class_service.create_class(teacher, "Physics 10B")
    _enroll(pg_sessionmaker, mine.class_id, student)

    service.create(teacher, Role.teacher, title="Visible", body="b", class_ids=[mine.class_id])
    service.create(teacher, Role.teacher, title="Not mine", body="b", class_ids=[theirs.class_id])
    service.create(
        teacher,
        Role.teacher,
        title="Scheduled",
        body="b",
        class_ids=[mine.class_id],
        publish_at=NOW + timedelta(days=1),
    )

    assert service.unread_count_for_student(student) == 1


def test_a_receipt_does_not_leak_between_students(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    service: AnnouncementService,
) -> None:
    """One announcement row is seen by a whole class; the receipt is per-viewer.

    This is the reason read state cannot live on ``announcements`` itself.
    """
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    reader = _seed_user(pg_sessionmaker)
    other = _seed_user(pg_sessionmaker)
    cls = class_service.create_class(teacher, "Physics 10A")
    _enroll(pg_sessionmaker, cls.class_id, reader)
    _enroll(pg_sessionmaker, cls.class_id, other)
    rows = service.create(teacher, Role.teacher, title="Hi", body="b", class_ids=[cls.class_id])

    service.mark_read(reader, rows[0].announcement_id)

    assert service.list_for_student(reader)[0].read_at == NOW
    assert service.list_for_student(other)[0].read_at is None
    assert service.unread_count_for_student(reader) == 0
    assert service.unread_count_for_student(other) == 1


def test_deleting_an_announcement_cascades_its_receipts(
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    service: AnnouncementService,
) -> None:
    """The teacher delete route predates read receipts.

    Without ``ON DELETE CASCADE`` the first teacher to delete a read
    announcement would hit a foreign-key error on a route that used to work.
    """
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    student = _seed_user(pg_sessionmaker)
    cls = class_service.create_class(teacher, "Physics 10A")
    _enroll(pg_sessionmaker, cls.class_id, student)
    rows = service.create(teacher, Role.teacher, title="Hi", body="b", class_ids=[cls.class_id])
    service.mark_read(student, rows[0].announcement_id)

    service.delete(teacher, rows[0].announcement_id)

    with pg_sessionmaker() as session:
        assert int(session.scalar(select(func.count()).select_from(AnnouncementRead)) or 0) == 0
