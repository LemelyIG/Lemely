"""HTTP-boundary tests for redeemable invite codes (``/api/invites/*``, D7.3).

Complements ``tests/test_invite_repo.py`` (the service-level proof of every
business rule) by proving the *wiring*: the two new routes exist at their
documented paths, ``GET /api/invites/{code}`` genuinely requires no
authentication at all (not merely "any role passes"), ``POST
.../redeem`` genuinely requires *some* authenticated caller, domain errors
map to the documented status codes, and the two mint routes added to
``school.py``/``classes.py`` carry the guard the plan specifies (school_admin;
teacher-or-school_admin) end to end through real DTOs.

``tests/test_authz_matrix_complete.py`` is the exhaustive, generated proof
that every route here carries its declared guard against every role; this
file is the focused, readable proof that the four routes actually do what
they are for.
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
from lemely.db.invite_repo import InviteService
from lemely.db.models import School, SchoolClass, SchoolMembership, Seat, User
from lemely.db.models.enums import MembershipRole, Role, SeatStatus
from lemely.runtime.config import DatabaseSettings
from lemely.web.app import create_app
from lemely.web.deps import AuthContext, get_auth_context, get_invite_service

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi import FastAPI


# ── Fixtures ─────────────────────────────────────────────────────────────────


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


def _seed_user(sm: sessionmaker[Session], role: Role, display_name: str | None = None) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role, display_name=display_name))
    return uid


def _seed_school(sm: sessionmaker[Session], *, quota: int, admin_id: uuid.UUID) -> uuid.UUID:
    school_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(School(id=school_id, name="Web Test School", seat_quota=quota))
        session.add(
            SchoolMembership(
                school_id=school_id, user_id=admin_id, membership_role=MembershipRole.school_admin
            )
        )
    return school_id


def _seed_class(
    sm: sessionmaker[Session], *, teacher_id: uuid.UUID, school_id: uuid.UUID | None = None
) -> uuid.UUID:
    class_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            SchoolClass(
                id=class_id,
                teacher_id=teacher_id,
                school_id=school_id,
                name="Web Test Class",
                join_code=f"JOIN{uuid.uuid4().hex[:6].upper()}",
            )
        )
    return class_id


def _app(sm: sessionmaker[Session]) -> FastAPI:
    application = create_app()
    application.dependency_overrides[get_invite_service] = lambda: InviteService(
        sm, ClassService(sm)
    )
    return application


def _client(
    sm: sessionmaker[Session], *, role: Role | None, user_id: uuid.UUID | None = None
) -> TestClient:
    """A ``TestClient`` wired to a fresh, throwaway-DB-backed ``InviteService``.

    ``role=None`` leaves ``get_auth_context`` un-overridden entirely — used by
    the public-preview tests, which must pass with **no** bearer token, not
    merely a token of *some* role.
    """
    application = _app(sm)
    if role is not None:
        application.dependency_overrides[get_auth_context] = lambda: AuthContext(
            user_id=str(user_id or uuid.uuid4()), role=role.value
        )
    return TestClient(application)


# ── GET /api/invites/{code}: public preview ─────────────────────────────────


def test_preview_route_requires_no_authentication(pg_sessionmaker: sessionmaker[Session]) -> None:
    admin = _seed_user(pg_sessionmaker, Role.school_admin)
    school = _seed_school(pg_sessionmaker, quota=5, admin_id=admin)
    service = InviteService(pg_sessionmaker, ClassService(pg_sessionmaker))
    invite = service.mint_seat_invite(admin, school)

    client = _client(pg_sessionmaker, role=None)
    res = client.get(f"/api/invites/{invite.code}")

    assert res.status_code == 200
    body = res.json()
    assert body["role"] == "student"
    assert body["schoolName"] == "Web Test School"
    assert body["className"] is None
    assert body["teacherName"] is None


def test_preview_route_of_an_unknown_code_is_404(pg_sessionmaker: sessionmaker[Session]) -> None:
    client = _client(pg_sessionmaker, role=None)
    res = client.get("/api/invites/NOSUCHCODE")
    assert res.status_code == 404


def test_preview_route_response_carries_no_extra_fields(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """``ApiModel``'s ``extra=\"forbid\"`` guarantees the DTO's shape; this
    pins that shape to exactly the four disclosure-safe fields."""
    teacher = _seed_user(pg_sessionmaker, Role.teacher, display_name="Mx Teacher")
    class_id = _seed_class(pg_sessionmaker, teacher_id=teacher)
    with pg_sessionmaker() as session:
        join_code = session.get(SchoolClass, class_id).join_code  # type: ignore[union-attr]

    client = _client(pg_sessionmaker, role=None)
    res = client.get(f"/api/invites/{join_code}")

    assert res.status_code == 200
    assert set(res.json()) == {"role", "schoolName", "className", "teacherName"}


# ── POST /api/invites/{code}/redeem ─────────────────────────────────────────


def test_redeem_route_requires_authentication(pg_sessionmaker: sessionmaker[Session]) -> None:
    """No bearer token at all - a real, wired ``create_app()``, no override."""
    application = _app(pg_sessionmaker)
    res = TestClient(application).post("/api/invites/ANYCODE/redeem")
    assert res.status_code == 401
    assert res.headers.get("WWW-Authenticate") == "Bearer"


def test_redeem_route_assigns_the_seat(pg_sessionmaker: sessionmaker[Session]) -> None:
    admin = _seed_user(pg_sessionmaker, Role.school_admin)
    school = _seed_school(pg_sessionmaker, quota=5, admin_id=admin)
    service = InviteService(pg_sessionmaker, ClassService(pg_sessionmaker))
    invite = service.mint_seat_invite(admin, school)
    student = _seed_user(pg_sessionmaker, Role.student)

    client = _client(pg_sessionmaker, role=Role.student, user_id=student)
    res = client.post(f"/api/invites/{invite.code}/redeem")

    assert res.status_code == 200
    body = res.json()
    assert body["role"] == "student"
    assert body["schoolId"] == str(school)
    assert body["classId"] is None
    with pg_sessionmaker() as session:
        seat = session.get(Seat, invite.seat_id)
        assert seat is not None
        assert seat.assigned_user_id == student
        assert seat.status is SeatStatus.assigned


def test_redeem_route_of_an_unknown_code_is_404(pg_sessionmaker: sessionmaker[Session]) -> None:
    client = _client(pg_sessionmaker, role=Role.student)
    res = client.post("/api/invites/NOSUCHCODE/redeem")
    assert res.status_code == 404


def test_redeem_route_already_redeemed_by_another_is_409(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    admin = _seed_user(pg_sessionmaker, Role.school_admin)
    school = _seed_school(pg_sessionmaker, quota=1, admin_id=admin)
    service = InviteService(pg_sessionmaker, ClassService(pg_sessionmaker))
    invite = service.mint_seat_invite(admin, school)
    first, second = (
        _seed_user(pg_sessionmaker, Role.student),
        _seed_user(pg_sessionmaker, Role.student),
    )
    service.redeem(first, invite.code)

    client = _client(pg_sessionmaker, role=Role.student, user_id=second)
    res = client.post(f"/api/invites/{invite.code}/redeem")

    assert res.status_code == 409


# ── POST /api/school/seats/invite-code: mint a seat invite ─────────────────


def test_mint_seat_invite_code_requires_school_admin(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    admin = _seed_user(pg_sessionmaker, Role.school_admin)
    school = _seed_school(pg_sessionmaker, quota=5, admin_id=admin)

    for role in (Role.student, Role.teacher, Role.platform_admin, Role.parent):
        client = _client(pg_sessionmaker, role=role)
        res = client.post("/api/school/seats/invite-code", json={"schoolId": str(school)})
        assert res.status_code == 403, f"{role.value} must not mint a seat invite"


def test_mint_seat_invite_code_reserves_a_seat(pg_sessionmaker: sessionmaker[Session]) -> None:
    admin = _seed_user(pg_sessionmaker, Role.school_admin)
    school = _seed_school(pg_sessionmaker, quota=5, admin_id=admin)

    client = _client(pg_sessionmaker, role=Role.school_admin, user_id=admin)
    res = client.post("/api/school/seats/invite-code", json={"schoolId": str(school)})

    assert res.status_code == 200
    body = res.json()
    assert body["role"] == "student"
    assert body["schoolId"] == str(school)
    assert body["classId"] is None
    assert len(body["code"]) >= 8
    with pg_sessionmaker() as session:
        seats = list(session.scalars(sa.select(Seat).where(Seat.school_id == school)))
        assert len(seats) == 1
        assert seats[0].status is SeatStatus.available


def test_mint_seat_invite_code_at_quota_is_409(pg_sessionmaker: sessionmaker[Session]) -> None:
    admin = _seed_user(pg_sessionmaker, Role.school_admin)
    school = _seed_school(pg_sessionmaker, quota=1, admin_id=admin)
    service = InviteService(pg_sessionmaker, ClassService(pg_sessionmaker))
    service.mint_seat_invite(admin, school)

    client = _client(pg_sessionmaker, role=Role.school_admin, user_id=admin)
    res = client.post("/api/school/seats/invite-code", json={"schoolId": str(school)})

    assert res.status_code == 409


def test_mint_seat_invite_code_of_an_unowned_school_is_403(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    owner = _seed_user(pg_sessionmaker, Role.school_admin)
    stranger = _seed_user(pg_sessionmaker, Role.school_admin)
    school = _seed_school(pg_sessionmaker, quota=5, admin_id=owner)

    client = _client(pg_sessionmaker, role=Role.school_admin, user_id=stranger)
    res = client.post("/api/school/seats/invite-code", json={"schoolId": str(school)})

    assert res.status_code == 403


# ── POST /api/school/classes/{id}/invite-code: mint a class invite ─────────


def test_mint_class_invite_code_requires_teacher_or_school_admin(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    class_id = _seed_class(pg_sessionmaker, teacher_id=teacher)

    for role in (Role.student, Role.parent, Role.platform_admin):
        client = _client(pg_sessionmaker, role=role)
        res = client.post(f"/api/school/classes/{class_id}/invite-code")
        assert res.status_code == 403, f"{role.value} must not mint a class invite"


def test_mint_class_invite_code_by_owning_teacher_succeeds(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    class_id = _seed_class(pg_sessionmaker, teacher_id=teacher)

    client = _client(pg_sessionmaker, role=Role.teacher, user_id=teacher)
    res = client.post(f"/api/school/classes/{class_id}/invite-code")

    assert res.status_code == 200
    body = res.json()
    assert body["classId"] == str(class_id)
    assert body["schoolId"] is None


def test_mint_class_invite_code_by_non_owning_teacher_is_403(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    stranger = _seed_user(pg_sessionmaker, Role.teacher)
    class_id = _seed_class(pg_sessionmaker, teacher_id=teacher)

    client = _client(pg_sessionmaker, role=Role.teacher, user_id=stranger)
    res = client.post(f"/api/school/classes/{class_id}/invite-code")

    assert res.status_code == 403


def test_mint_class_invite_code_unknown_class_is_404(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    client = _client(pg_sessionmaker, role=Role.teacher)
    res = client.post(f"/api/school/classes/{uuid.uuid4()}/invite-code")
    assert res.status_code == 404


# ── deps.py wiring sanity ───────────────────────────────────────────────────


def test_reset_singletons_clears_get_invite_service() -> None:
    """``reset_singletons``'s docstring promises to clear *every* cached
    singleton (D7.3's own copy of the lesson Task 12 already recorded for
    ``get_platform_admin_service``/``get_school_admin_service``): calling it
    must not raise, and must actually evict a populated cache."""
    from lemely.web.deps import reset_singletons

    get_invite_service()  # populate the cache (lazy construction, no I/O)
    assert get_invite_service.cache_info().currsize == 1
    reset_singletons()
    assert get_invite_service.cache_info().currsize == 0
