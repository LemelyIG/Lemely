"""Route tests for ``GET /api/student/classes`` (P5.8 chunk C, D5.14 §1).

Self-contained (mirrors ``tests/test_web_leaderboard.py``) — a throwaway
Postgres DB per test, skipped cleanly when unreachable.

This route exists for one reason: S-29's ``scope=class`` board needs a
``class_id`` and nothing student-facing supplied one. So the properties worth
pinning are the ones that would let it become a leak or a lie — that it never
returns another student's classes, that its empty state is a successful answer
rather than an error, and that a class with no school reports ``null`` instead
of a fabricated school name.
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

from lemely.db.base import Base
from lemely.db.class_repo import ClassService
from lemely.db.models.enums import Role
from lemely.db.models.orgs import ClassEnrollment, School, SchoolClass
from lemely.db.models.users import User
from lemely.runtime.config import DatabaseSettings
from lemely.web import create_app
from lemely.web.deps import AuthContext, get_auth_context, get_class_service

if TYPE_CHECKING:
    from collections.abc import Iterator


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
def class_service(pg_sessionmaker: sessionmaker[Session]) -> ClassService:
    return ClassService(pg_sessionmaker)


def _use_service(client: TestClient, class_service: ClassService) -> None:
    client.app.dependency_overrides[get_class_service] = lambda: class_service  # type: ignore[union-attr]


def _auth_as(client: TestClient, user_id: uuid.UUID, role: Role) -> None:
    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(user_id), role=role.value
    )


def _seed_user(sm: sessionmaker[Session], role: Role = Role.student) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role))
    return uid


def _seed_class(
    sm: sessionmaker[Session],
    *,
    name: str = "9A",
    subject_code: str | None = None,
    school_name: str | None = None,
) -> uuid.UUID:
    class_id = uuid.uuid4()
    teacher_id = uuid.uuid4()
    school_id: uuid.UUID | None = None
    with sm.begin() as session:
        session.add(User(id=teacher_id, email=f"{teacher_id}@example.com", role=Role.teacher))
        if school_name is not None:
            school_id = uuid.uuid4()
            session.add(School(id=school_id, name=school_name))
        session.flush()
        session.add(
            SchoolClass(
                id=class_id,
                school_id=school_id,
                teacher_id=teacher_id,
                name=name,
                subject_code=subject_code,
            )
        )
    return class_id


def _enrol(sm: sessionmaker[Session], class_id: uuid.UUID, student_id: uuid.UUID) -> None:
    with sm.begin() as session:
        session.add(ClassEnrollment(class_id=class_id, student_id=student_id))


# ---------------------------------------------------------------------------
# The happy path and the empty state.
# ---------------------------------------------------------------------------


def test_returns_the_callers_own_classes(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], class_service: ClassService
) -> None:
    _use_service(client, class_service)
    student = _seed_user(pg_sessionmaker)
    class_id = _seed_class(
        pg_sessionmaker, name="Physics 9A", subject_code="0625", school_name="Test School"
    )
    _enrol(pg_sessionmaker, class_id, student)
    _auth_as(client, student, Role.student)

    resp = client.get("/api/student/classes")

    assert resp.status_code == 200
    assert resp.json() == {
        "classes": [
            {
                "classId": str(class_id),
                "name": "Physics 9A",
                "subjectCode": "0625",
                "schoolName": "Test School",
            }
        ]
    }


def test_no_classes_is_a_successful_empty_answer_not_an_error(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], class_service: ClassService
) -> None:
    """A direct subscriber with no teacher genuinely has no classes.

    That is a normal account state, so it must be a 200 the screen can render
    as "no classes to rank against" — never a 404 the screen has to guess the
    meaning of.
    """
    _use_service(client, class_service)
    student = _seed_user(pg_sessionmaker)
    _auth_as(client, student, Role.student)

    resp = client.get("/api/student/classes")

    assert resp.status_code == 200
    assert resp.json() == {"classes": []}


def test_an_independent_teachers_class_reports_a_null_school(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], class_service: ClassService
) -> None:
    """`schoolName` is `None`, never a placeholder (UI spec §1.4).

    An independent teacher's class has no ``school_id`` at all; "Independent"
    or "—" here would be the screen's wording leaking into the wire, and would
    be indistinguishable from a school actually named that.
    """
    _use_service(client, class_service)
    student = _seed_user(pg_sessionmaker)
    class_id = _seed_class(pg_sessionmaker, name="Tutoring group", school_name=None)
    _enrol(pg_sessionmaker, class_id, student)
    _auth_as(client, student, Role.student)

    resp = client.get("/api/student/classes")

    assert resp.status_code == 200
    row = resp.json()["classes"][0]
    assert row["schoolName"] is None
    assert row["subjectCode"] is None


# ---------------------------------------------------------------------------
# Tenancy and authz.
# ---------------------------------------------------------------------------


def test_another_students_classes_are_not_returned(
    client: TestClient, pg_sessionmaker: sessionmaker[Session], class_service: ClassService
) -> None:
    """The route has no caller-supplied student id, so this is structural.

    Pinned anyway: the assertion is what would catch a future edit that adds
    one "for the teacher view" and forgets that this router is mounted for
    students.
    """
    _use_service(client, class_service)
    mine = _seed_user(pg_sessionmaker)
    theirs = _seed_user(pg_sessionmaker)
    my_class = _seed_class(pg_sessionmaker, name="Mine")
    their_class = _seed_class(pg_sessionmaker, name="Theirs")
    _enrol(pg_sessionmaker, my_class, mine)
    _enrol(pg_sessionmaker, their_class, theirs)
    _auth_as(client, mine, Role.student)

    resp = client.get("/api/student/classes")

    assert resp.status_code == 200
    names = [row["name"] for row in resp.json()["classes"]]
    assert names == ["Mine"]


@pytest.mark.parametrize(
    "role", [Role.teacher, Role.parent, Role.school_admin, Role.platform_admin]
)
def test_non_students_are_rejected(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    class_service: ClassService,
    role: Role,
) -> None:
    """Unlike P5.6's deliberately role-agnostic notification router, this
    surface has exactly one intended reader — it answers "your classes" and a
    teacher's classes are a different question with a different route."""
    _use_service(client, class_service)
    caller = _seed_user(pg_sessionmaker, role=role)
    _auth_as(client, caller, role)

    resp = client.get("/api/student/classes")

    assert resp.status_code == 403


def test_the_route_is_registered_under_the_student_prefix(client: TestClient) -> None:
    """Read from the OpenAPI paths, never ``app.routes``.

    This FastAPI version wraps an included router in an opaque
    ``_IncludedRouter`` with no ``.path``, so an ``app.routes`` scan finds
    nothing and passes for the wrong reason (P5.5 chunk C's trap).
    """
    paths = client.app.openapi()["paths"]  # type: ignore[union-attr]
    assert "/api/student/classes" in paths
    assert "get" in paths["/api/student/classes"]
