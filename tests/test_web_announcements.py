"""HTTP-layer tests for the announcement endpoints (D3.14/P3.8 chunk a).

Exercises ``/api/teacher/announcements/*`` (:mod:`lemely.web.routers.announcements`)
against a real :class:`~lemely.db.announcement_repo.AnnouncementService` and
:class:`~lemely.db.class_repo.ClassService` bound to a throwaway Postgres
database (mirrors ``tests/test_web_parent.py``'s Postgres-backed fixture
block). Proves:

* A teacher can compose a multi-class announcement in one request and list it
  back; a class they do not own is a 403 and the fan-out writes nothing.
* ``schoolWide: true`` from a teacher is a 403; a school_admin succeeds and
  the row carries ``classId: null``.
* Every non-staff role (student, parent) and ``platform_admin`` is rejected
  from every route.
* A non-UUID id is a 422; an unknown announcement id is a 404; someone else's
  announcement is a 403 on delete.
"""

from __future__ import annotations

import uuid
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
from lemely.db.models import School, SchoolMembership, User
from lemely.db.models.enums import MembershipRole, Role
from lemely.runtime.config import DatabaseSettings
from lemely.web import create_app
from lemely.web.deps import (
    AuthContext,
    get_announcement_service,
    get_auth_context,
    get_class_service,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

# ---------------------------------------------------------------------------
# Fixtures.
# ---------------------------------------------------------------------------


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
    """A sessionmaker bound to a throwaway Postgres DB; skips if unreachable."""
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
def announcement_service(
    pg_sessionmaker: sessionmaker[Session], class_service: ClassService
) -> AnnouncementService:
    return AnnouncementService(pg_sessionmaker, class_service)


@pytest.fixture
def client(
    class_service: ClassService, announcement_service: AnnouncementService
) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_class_service] = lambda: class_service
    app.dependency_overrides[get_announcement_service] = lambda: announcement_service
    yield TestClient(app)
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Seed helpers.
# ---------------------------------------------------------------------------


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


def _auth_as(client: TestClient, user_id: uuid.UUID, role: Role) -> None:
    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(user_id), role=role.value
    )


# ---------------------------------------------------------------------------
# Compose: multi-class fan-out.
# ---------------------------------------------------------------------------


def test_teacher_composes_multi_class_announcement(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    cls_a = class_service.create_class(teacher, "Physics 10A")
    cls_b = class_service.create_class(teacher, "Physics 10B")
    _auth_as(client, teacher, Role.teacher)

    resp = client.post(
        "/api/teacher/announcements",
        json={
            "title": "Test next week",
            "body": "Bring a calculator.",
            "classIds": [str(cls_a.class_id), str(cls_b.class_id)],
        },
    )

    assert resp.status_code == 200, resp.text
    announcements = resp.json()["announcements"]
    assert len(announcements) == 2
    assert {a["classId"] for a in announcements} == {str(cls_a.class_id), str(cls_b.class_id)}
    assert all(a["title"] == "Test next week" for a in announcements)
    assert all(a["schoolId"] is None for a in announcements)
    assert all(a["authorId"] == str(teacher) for a in announcements)

    listed = client.get("/api/teacher/announcements")
    assert listed.status_code == 200
    assert len(listed.json()["announcements"]) == 2


def test_teacher_cannot_post_to_another_teachers_class(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
) -> None:
    teacher_a = _seed_user(pg_sessionmaker, Role.teacher)
    teacher_b = _seed_user(pg_sessionmaker, Role.teacher)
    own_cls = class_service.create_class(teacher_a, "A's class")
    other_cls = class_service.create_class(teacher_b, "B's class")
    _auth_as(client, teacher_a, Role.teacher)

    resp = client.post(
        "/api/teacher/announcements",
        json={
            "title": "Hi",
            "body": "Body",
            "classIds": [str(own_cls.class_id), str(other_cls.class_id)],
        },
    )

    assert resp.status_code == 403

    _auth_as(client, teacher_a, Role.teacher)
    listed = client.get("/api/teacher/announcements")
    assert listed.json()["announcements"] == []


def test_publish_at_round_trips_through_the_wire(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    cls = class_service.create_class(teacher, "A class")
    _auth_as(client, teacher, Role.teacher)

    resp = client.post(
        "/api/teacher/announcements",
        json={
            "title": "Scheduled",
            "body": "Body",
            "classIds": [str(cls.class_id)],
            "publishAt": "2026-09-01T08:00:00+00:00",
        },
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["announcements"][0]["publishAt"] == "2026-09-01T08:00:00+00:00"


def test_publish_at_omitted_is_null(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    cls = class_service.create_class(teacher, "A class")
    _auth_as(client, teacher, Role.teacher)

    resp = client.post(
        "/api/teacher/announcements",
        json={"title": "Immediate", "body": "Body", "classIds": [str(cls.class_id)]},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["announcements"][0]["publishAt"] is None


# ---------------------------------------------------------------------------
# School-wide: school_admin only.
# ---------------------------------------------------------------------------


def test_teacher_requesting_school_wide_gets_403(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    school = _seed_school(pg_sessionmaker)
    _auth_as(client, teacher, Role.teacher)

    resp = client.post(
        "/api/teacher/announcements",
        json={
            "title": "Hi",
            "body": "Body",
            "schoolWide": True,
            "schoolId": str(school),
        },
    )

    assert resp.status_code == 403


def test_school_admin_school_wide_succeeds_with_null_class_id(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    admin = _seed_user(pg_sessionmaker, Role.school_admin)
    school = _seed_school(pg_sessionmaker, admin_id=admin)
    _auth_as(client, admin, Role.school_admin)

    resp = client.post(
        "/api/teacher/announcements",
        json={
            "title": "Training day",
            "body": "School closed Friday.",
            "schoolWide": True,
            "schoolId": str(school),
        },
    )

    assert resp.status_code == 200, resp.text
    announcements = resp.json()["announcements"]
    assert len(announcements) == 1
    assert announcements[0]["classId"] is None
    assert announcements[0]["schoolId"] == str(school)


# ---------------------------------------------------------------------------
# Role gate.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("role", [Role.student, Role.parent, Role.platform_admin])
def test_non_staff_roles_are_rejected(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], role: Role
) -> None:
    user = _seed_user(pg_sessionmaker, role)
    _auth_as(client, user, role)

    assert client.get("/api/teacher/announcements").status_code == 403
    assert (
        client.post(
            "/api/teacher/announcements",
            json={"title": "Hi", "body": "Body", "classIds": []},
        ).status_code
        == 403
    )
    assert client.delete(f"/api/teacher/announcements/{uuid.uuid4()}").status_code == 403


# ---------------------------------------------------------------------------
# List: never another author's rows.
# ---------------------------------------------------------------------------


def test_list_never_returns_another_authors_announcements(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
) -> None:
    teacher_a = _seed_user(pg_sessionmaker, Role.teacher)
    teacher_b = _seed_user(pg_sessionmaker, Role.teacher)
    cls_a = class_service.create_class(teacher_a, "A's class")
    cls_b = class_service.create_class(teacher_b, "B's class")

    _auth_as(client, teacher_a, Role.teacher)
    client.post(
        "/api/teacher/announcements",
        json={"title": "A1", "body": "Body", "classIds": [str(cls_a.class_id)]},
    )

    _auth_as(client, teacher_b, Role.teacher)
    client.post(
        "/api/teacher/announcements",
        json={"title": "B1", "body": "Body", "classIds": [str(cls_b.class_id)]},
    )

    resp = client.get("/api/teacher/announcements")
    titles = [a["title"] for a in resp.json()["announcements"]]
    assert titles == ["B1"]


# ---------------------------------------------------------------------------
# Delete: author-scoped, 422/404/403.
# ---------------------------------------------------------------------------


def test_delete_own_announcement_returns_204(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    cls = class_service.create_class(teacher, "A class")
    _auth_as(client, teacher, Role.teacher)
    created = client.post(
        "/api/teacher/announcements",
        json={"title": "Hi", "body": "Body", "classIds": [str(cls.class_id)]},
    ).json()["announcements"][0]

    resp = client.delete(f"/api/teacher/announcements/{created['announcementId']}")
    assert resp.status_code == 204

    listed = client.get("/api/teacher/announcements")
    assert listed.json()["announcements"] == []


def test_delete_someone_elses_announcement_is_403(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
) -> None:
    teacher_a = _seed_user(pg_sessionmaker, Role.teacher)
    teacher_b = _seed_user(pg_sessionmaker, Role.teacher)
    cls_a = class_service.create_class(teacher_a, "A's class")

    _auth_as(client, teacher_a, Role.teacher)
    created = client.post(
        "/api/teacher/announcements",
        json={"title": "A's own", "body": "Body", "classIds": [str(cls_a.class_id)]},
    ).json()["announcements"][0]

    _auth_as(client, teacher_b, Role.teacher)
    resp = client.delete(f"/api/teacher/announcements/{created['announcementId']}")
    assert resp.status_code == 403

    _auth_as(client, teacher_a, Role.teacher)
    listed = client.get("/api/teacher/announcements")
    assert len(listed.json()["announcements"]) == 1


def test_delete_unknown_id_is_404(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    _auth_as(client, teacher, Role.teacher)

    resp = client.delete(f"/api/teacher/announcements/{uuid.uuid4()}")
    assert resp.status_code == 404


def test_delete_non_uuid_id_is_422(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    _auth_as(client, teacher, Role.teacher)

    resp = client.delete("/api/teacher/announcements/not-a-uuid")
    assert resp.status_code == 422


def test_create_with_non_uuid_class_id_is_422(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    _auth_as(client, teacher, Role.teacher)

    resp = client.post(
        "/api/teacher/announcements",
        json={"title": "Hi", "body": "Body", "classIds": ["not-a-uuid"]},
    )
    assert resp.status_code == 422


def test_create_with_malformed_publish_at_is_422(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    cls = class_service.create_class(teacher, "A class")
    _auth_as(client, teacher, Role.teacher)

    resp = client.post(
        "/api/teacher/announcements",
        json={
            "title": "Hi",
            "body": "Body",
            "classIds": [str(cls.class_id)],
            "publishAt": "not-a-date",
        },
    )
    assert resp.status_code == 422


def test_create_with_no_target_is_422(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    _auth_as(client, teacher, Role.teacher)

    resp = client.post("/api/teacher/announcements", json={"title": "Hi", "body": "Body"})
    assert resp.status_code == 422
