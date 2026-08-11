"""Route tests for ``/api/student/announcements`` (P5.5 chunk B).

Self-contained (mirrors ``tests/test_web_friends.py`` and
``tests/test_web_leaderboard.py``) — a throwaway Postgres DB per test, skipped
cleanly when unreachable. This file tests the HTTP layer (DTO shape, scope
derivation, the effective-``publishedAt`` choice, status-code mapping, authz),
not :class:`~lemely.db.announcement_repo.AnnouncementService`, which already
has its own suite (``tests/test_announcement_repo.py``).

Announcements are inserted **directly** rather than through
``AnnouncementService.create``: the composer is the teacher's path and has its
own tests, and a direct insert is the only way to pin the two fields whose
handling this router is responsible for — a future ``publish_at`` and a
back-dated one whose ``created_at`` disagrees with it.

Covers: both audiences (class enrolment and a school ``Seat``), the honest
empty list, future-dated exclusion, ``publishedAt`` being the *effective*
time and driving the order, ``readAt`` before/after a receipt, ``limit``
bounds, the unread count not being page-limited, receipt idempotency
returning the *first* read time, the 404/422 error table, the canonical-id
echo on a non-canonical path id, and the authz matrix across all three routes.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.db.announcement_repo import AnnouncementService
from lemely.db.base import Base
from lemely.db.class_repo import ClassService
from lemely.db.models.enums import Role, SeatStatus
from lemely.db.models.ops import Announcement, AnnouncementRead
from lemely.db.models.orgs import ClassEnrollment, School, SchoolClass, Seat
from lemely.db.models.users import User
from lemely.runtime.config import DatabaseSettings
from lemely.web import create_app
from lemely.web.deps import AuthContext, get_announcement_service, get_auth_context

if TYPE_CHECKING:
    from collections.abc import Iterator

_NOON_UTC = datetime(2026, 8, 5, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Fixtures.
# ---------------------------------------------------------------------------


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app()
    yield TestClient(app)
    app.dependency_overrides.clear()


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
def announcement_service(pg_sessionmaker: sessionmaker[Session]) -> AnnouncementService:
    return AnnouncementService(
        pg_sessionmaker, ClassService(pg_sessionmaker), now=lambda: _NOON_UTC
    )


def _use_service(client: TestClient, service: AnnouncementService) -> None:
    client.app.dependency_overrides[get_announcement_service] = lambda: service  # type: ignore[union-attr]


def _auth_as(client: TestClient, user_id: uuid.UUID, role: Role) -> None:
    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(user_id), role=role.value
    )


# ---------------------------------------------------------------------------
# Seed helpers.
# ---------------------------------------------------------------------------


def _seed_user(
    sm: sessionmaker[Session], role: Role = Role.student, *, display_name: str | None = None
) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role, display_name=display_name))
    return uid


def _seed_school(sm: sessionmaker[Session]) -> uuid.UUID:
    school_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(School(id=school_id, name="Test School"))
    return school_id


def _seed_seat(
    sm: sessionmaker[Session],
    school_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    status: SeatStatus = SeatStatus.assigned,
) -> None:
    with sm.begin() as session:
        session.add(Seat(school_id=school_id, assigned_user_id=user_id, status=status))


def _seed_class(sm: sessionmaker[Session], teacher_id: uuid.UUID) -> uuid.UUID:
    class_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(SchoolClass(id=class_id, school_id=None, teacher_id=teacher_id, name="9A"))
    return class_id


def _enrol(sm: sessionmaker[Session], class_id: uuid.UUID, student_id: uuid.UUID) -> None:
    with sm.begin() as session:
        session.add(ClassEnrollment(class_id=class_id, student_id=student_id))


def _seed_announcement(
    sm: sessionmaker[Session],
    author_id: uuid.UUID,
    *,
    class_id: uuid.UUID | None = None,
    school_id: uuid.UUID | None = None,
    title: str = "Test schedule",
    body: str = "Bring calculators.",
    publish_at: datetime | None = None,
    created_at: datetime | None = None,
) -> uuid.UUID:
    announcement_id = uuid.uuid4()
    with sm.begin() as session:
        row = Announcement(
            id=announcement_id,
            author_id=author_id,
            class_id=class_id,
            school_id=school_id,
            title=title,
            body=body,
            publish_at=publish_at,
        )
        if created_at is not None:
            row.created_at = created_at
        session.add(row)
    return announcement_id


def _enrolled_student_with_announcement(
    sm: sessionmaker[Session], **announcement_kwargs: object
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Seed teacher → class → enrolled student → one class announcement."""
    teacher = _seed_user(sm, Role.teacher, display_name="Ms Rana")
    student = _seed_user(sm)
    class_id = _seed_class(sm, teacher)
    _enrol(sm, class_id, student)
    announcement_id = _seed_announcement(sm, teacher, class_id=class_id, **announcement_kwargs)  # type: ignore[arg-type]
    return student, class_id, announcement_id


# ---------------------------------------------------------------------------
# GET "" — the two audiences.
# ---------------------------------------------------------------------------


def test_class_announcement_is_visible_with_the_full_dto(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    announcement_service: AnnouncementService,
) -> None:
    _use_service(client, announcement_service)
    student, class_id, announcement_id = _enrolled_student_with_announcement(pg_sessionmaker)
    _auth_as(client, student, Role.student)

    resp = client.get("/api/student/announcements")

    assert resp.status_code == 200, resp.text
    (row,) = resp.json()["announcements"]
    assert row["announcementId"] == str(announcement_id)
    assert row["scope"] == "class"
    assert row["classId"] == str(class_id)
    assert row["schoolId"] is None
    assert row["title"] == "Test schedule"
    assert row["body"] == "Bring calculators."
    assert row["readAt"] is None
    assert row["publishedAt"] is not None


def test_school_wide_announcement_reaches_a_seated_student(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    announcement_service: AnnouncementService,
) -> None:
    """The school arm keys on ``Seat``, not ``SchoolMembership`` (D5.4).

    Pinned at the HTTP layer as well as the service layer because the failure
    mode is an *empty list*, which reads as "the school never posts anything"
    rather than as a bug.
    """
    _use_service(client, announcement_service)
    admin = _seed_user(pg_sessionmaker, Role.school_admin)
    student = _seed_user(pg_sessionmaker)
    school_id = _seed_school(pg_sessionmaker)
    _seed_seat(pg_sessionmaker, school_id, student)
    _seed_announcement(pg_sessionmaker, admin, school_id=school_id, title="Half term")
    _auth_as(client, student, Role.student)

    resp = client.get("/api/student/announcements")

    assert resp.status_code == 200, resp.text
    (row,) = resp.json()["announcements"]
    assert row["scope"] == "school"
    assert row["schoolId"] == str(school_id)
    assert row["classId"] is None
    assert row["title"] == "Half term"


def test_revoked_seat_does_not_receive_school_announcements(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    announcement_service: AnnouncementService,
) -> None:
    _use_service(client, announcement_service)
    admin = _seed_user(pg_sessionmaker, Role.school_admin)
    student = _seed_user(pg_sessionmaker)
    school_id = _seed_school(pg_sessionmaker)
    _seed_seat(pg_sessionmaker, school_id, student, status=SeatStatus.revoked)
    _seed_announcement(pg_sessionmaker, admin, school_id=school_id)
    _auth_as(client, student, Role.student)

    resp = client.get("/api/student/announcements")

    assert resp.status_code == 200, resp.text
    assert resp.json()["announcements"] == []


def test_a_student_never_sees_another_classs_announcement(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    announcement_service: AnnouncementService,
) -> None:
    _use_service(client, announcement_service)
    _, _, _ = _enrolled_student_with_announcement(pg_sessionmaker)
    outsider = _seed_user(pg_sessionmaker)
    _auth_as(client, outsider, Role.student)

    resp = client.get("/api/student/announcements")

    assert resp.status_code == 200, resp.text
    assert resp.json()["announcements"] == []


def test_no_audience_is_an_empty_list_not_an_error(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    announcement_service: AnnouncementService,
) -> None:
    """A student with no class and no seat has no audience.

    That is a true "nothing has been posted to you" and must be a successful
    empty response, never a 404 — the same reasoning that made the
    leaderboard's no-school case a successful ``unavailable`` rather than a
    404 (P5.3 chunk B).
    """
    _use_service(client, announcement_service)
    _auth_as(client, _seed_user(pg_sessionmaker), Role.student)

    resp = client.get("/api/student/announcements")

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"announcements": []}


# ---------------------------------------------------------------------------
# GET "" — scheduling, ordering, limit.
# ---------------------------------------------------------------------------


def test_a_future_dated_announcement_is_not_yet_visible(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    announcement_service: AnnouncementService,
) -> None:
    _use_service(client, announcement_service)
    student, _, _ = _enrolled_student_with_announcement(
        pg_sessionmaker, publish_at=_NOON_UTC + timedelta(days=1)
    )
    _auth_as(client, student, Role.student)

    resp = client.get("/api/student/announcements")

    assert resp.status_code == 200, resp.text
    assert resp.json()["announcements"] == []


def test_published_at_is_the_scheduled_time_not_the_creation_time(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    announcement_service: AnnouncementService,
) -> None:
    """A back-dated post reports the time its author meant, not typing time.

    ``publishedAt`` is the single time field on the wire precisely so a screen
    cannot sort by ``created_at`` and disagree with the server's ordering.
    """
    _use_service(client, announcement_service)
    scheduled = _NOON_UTC - timedelta(days=3)
    student, _, _ = _enrolled_student_with_announcement(
        pg_sessionmaker, publish_at=scheduled, created_at=_NOON_UTC
    )
    _auth_as(client, student, Role.student)

    (row,) = client.get("/api/student/announcements").json()["announcements"]

    assert datetime.fromisoformat(row["publishedAt"]) == scheduled


def test_list_is_ordered_by_effective_publication_newest_first(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    announcement_service: AnnouncementService,
) -> None:
    _use_service(client, announcement_service)
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    student = _seed_user(pg_sessionmaker)
    class_id = _seed_class(pg_sessionmaker, teacher)
    _enrol(pg_sessionmaker, class_id, student)
    # Written last, back-dated three days: it must sort *below* the older-typed
    # post published yesterday, not above it.
    _seed_announcement(
        pg_sessionmaker,
        teacher,
        class_id=class_id,
        title="Older",
        publish_at=_NOON_UTC - timedelta(days=3),
        created_at=_NOON_UTC,
    )
    _seed_announcement(
        pg_sessionmaker,
        teacher,
        class_id=class_id,
        title="Newer",
        publish_at=_NOON_UTC - timedelta(days=1),
        created_at=_NOON_UTC - timedelta(days=5),
    )
    _auth_as(client, student, Role.student)

    rows = client.get("/api/student/announcements").json()["announcements"]

    assert [r["title"] for r in rows] == ["Newer", "Older"]


def test_limit_is_honoured(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    announcement_service: AnnouncementService,
) -> None:
    _use_service(client, announcement_service)
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    student = _seed_user(pg_sessionmaker)
    class_id = _seed_class(pg_sessionmaker, teacher)
    _enrol(pg_sessionmaker, class_id, student)
    for index in range(4):
        _seed_announcement(
            pg_sessionmaker,
            teacher,
            class_id=class_id,
            title=f"Notice {index}",
            publish_at=_NOON_UTC - timedelta(days=index),
        )
    _auth_as(client, student, Role.student)

    rows = client.get("/api/student/announcements", params={"limit": 2}).json()["announcements"]

    assert len(rows) == 2


@pytest.mark.parametrize("limit", [0, -1, 201])
def test_out_of_range_limit_is_rejected(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    announcement_service: AnnouncementService,
    limit: int,
) -> None:
    _use_service(client, announcement_service)
    _auth_as(client, _seed_user(pg_sessionmaker), Role.student)

    resp = client.get("/api/student/announcements", params={"limit": limit})

    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET "/unread-count".
# ---------------------------------------------------------------------------


def test_unread_count_counts_the_whole_scope_not_one_page(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    announcement_service: AnnouncementService,
) -> None:
    """The badge must not stop counting at the page size.

    This is why the count is its own endpoint rather than ``len()`` of the
    list response: with more unread announcements than the default page, a
    page-derived badge would report exactly a page's worth.
    """
    _use_service(client, announcement_service)
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    student = _seed_user(pg_sessionmaker)
    class_id = _seed_class(pg_sessionmaker, teacher)
    _enrol(pg_sessionmaker, class_id, student)
    for index in range(5):
        _seed_announcement(pg_sessionmaker, teacher, class_id=class_id, title=f"N{index}")
    _auth_as(client, student, Role.student)

    listed = client.get("/api/student/announcements", params={"limit": 2}).json()["announcements"]
    counted = client.get("/api/student/announcements/unread-count").json()

    assert len(listed) == 2
    assert counted == {"unreadCount": 5}


def test_unread_count_drops_after_a_receipt(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    announcement_service: AnnouncementService,
) -> None:
    _use_service(client, announcement_service)
    student, _, announcement_id = _enrolled_student_with_announcement(pg_sessionmaker)
    _auth_as(client, student, Role.student)

    before = client.get("/api/student/announcements/unread-count").json()["unreadCount"]
    client.post(f"/api/student/announcements/{announcement_id}/read")
    after = client.get("/api/student/announcements/unread-count").json()["unreadCount"]

    assert (before, after) == (1, 0)


# ---------------------------------------------------------------------------
# POST "/{id}/read".
# ---------------------------------------------------------------------------


def test_marking_read_returns_the_receipt_and_shows_up_in_the_list(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    announcement_service: AnnouncementService,
) -> None:
    _use_service(client, announcement_service)
    student, _, announcement_id = _enrolled_student_with_announcement(pg_sessionmaker)
    _auth_as(client, student, Role.student)

    resp = client.post(f"/api/student/announcements/{announcement_id}/read")

    assert resp.status_code == 200, resp.text
    assert resp.json()["announcementId"] == str(announcement_id)
    assert datetime.fromisoformat(resp.json()["readAt"]) == _NOON_UTC

    (row,) = client.get("/api/student/announcements").json()["announcements"]
    assert datetime.fromisoformat(row["readAt"]) == _NOON_UTC


def test_marking_read_twice_returns_the_first_read_time(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    announcement_service: AnnouncementService,
) -> None:
    """Idempotent, and the timestamp does not move.

    ``readAt`` is first-read only; a re-open must not overwrite it, or the one
    number the receipt table holds silently becomes "last opened".
    """
    _use_service(client, announcement_service)
    student, _, announcement_id = _enrolled_student_with_announcement(pg_sessionmaker)
    _auth_as(client, student, Role.student)

    first = client.post(f"/api/student/announcements/{announcement_id}/read")
    second = client.post(f"/api/student/announcements/{announcement_id}/read")

    assert (first.status_code, second.status_code) == (200, 200)
    assert first.json() == second.json()
    with pg_sessionmaker() as session:
        assert session.scalar(sa.select(sa.func.count()).select_from(AnnouncementRead)) == 1


def test_marking_read_echoes_the_canonical_id_for_a_non_canonical_path(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    announcement_service: AnnouncementService,
) -> None:
    """``uuid.UUID`` accepts forms that are not the row's own string.

    Echoing the raw path back would hand the client a receipt id that does not
    match the one in the list response, so its unread state would never clear.
    """
    _use_service(client, announcement_service)
    student, _, announcement_id = _enrolled_student_with_announcement(pg_sessionmaker)
    _auth_as(client, student, Role.student)
    non_canonical = f"urn:uuid:{str(announcement_id).upper()}"

    resp = client.post(f"/api/student/announcements/{non_canonical}/read")

    assert resp.status_code == 200, resp.text
    assert resp.json()["announcementId"] == str(announcement_id)


def test_marking_read_an_out_of_scope_announcement_is_404(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    announcement_service: AnnouncementService,
) -> None:
    """ "Exists but not yours" and "does not exist" must be indistinguishable.

    A student able to tell them apart could enumerate other classes'
    announcement ids one 404-vs-403 at a time.
    """
    _use_service(client, announcement_service)
    _, _, announcement_id = _enrolled_student_with_announcement(pg_sessionmaker)
    outsider = _seed_user(pg_sessionmaker)
    _auth_as(client, outsider, Role.student)

    existing = client.post(f"/api/student/announcements/{announcement_id}/read")
    absent = client.post(f"/api/student/announcements/{uuid.uuid4()}/read")

    assert existing.status_code == 404
    assert absent.status_code == 404
    with pg_sessionmaker() as session:
        assert session.scalar(sa.select(sa.func.count()).select_from(AnnouncementRead)) == 0


def test_marking_read_a_future_dated_announcement_is_404(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    announcement_service: AnnouncementService,
) -> None:
    _use_service(client, announcement_service)
    student, _, announcement_id = _enrolled_student_with_announcement(
        pg_sessionmaker, publish_at=_NOON_UTC + timedelta(days=1)
    )
    _auth_as(client, student, Role.student)

    resp = client.post(f"/api/student/announcements/{announcement_id}/read")

    assert resp.status_code == 404


def test_malformed_announcement_id_is_422(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    announcement_service: AnnouncementService,
) -> None:
    _use_service(client, announcement_service)
    _auth_as(client, _seed_user(pg_sessionmaker), Role.student)

    resp = client.post("/api/student/announcements/not-a-uuid/read")

    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Authz matrix + the D5.5 no-leak discipline.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("role", [Role.teacher, Role.parent, Role.school_admin])
def test_non_students_are_rejected_on_every_route(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    announcement_service: AnnouncementService,
    role: Role,
) -> None:
    _use_service(client, announcement_service)
    _auth_as(client, _seed_user(pg_sessionmaker, role), role)

    responses = [
        client.get("/api/student/announcements"),
        client.get("/api/student/announcements/unread-count"),
        client.post(f"/api/student/announcements/{uuid.uuid4()}/read"),
    ]

    assert [r.status_code for r in responses] == [403, 403, 403]


def test_no_email_address_appears_anywhere_in_the_list_response(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    announcement_service: AnnouncementService,
) -> None:
    """D5.5's discipline, applied to a second surface.

    The author is exposed as an opaque id and nothing else; the moment someone
    resolves a display name here, the codebase-wide ``display_name or email``
    fallback would broadcast a member of staff's contact address to a class.
    """
    _use_service(client, announcement_service)
    student, _, _ = _enrolled_student_with_announcement(pg_sessionmaker)
    _auth_as(client, student, Role.student)

    resp = client.get("/api/student/announcements")

    assert resp.status_code == 200, resp.text
    assert "@" not in resp.text
