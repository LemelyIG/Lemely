"""The public invite preview never exposes a teacher email and is rate-limited.

``GET /api/invites/{code}`` is unauthenticated and a class join code is unlimited-use
and widely shared, so (a) a blank teacher display name must read as ``null``, never fall
back to the teacher's email, and (b) the route is throttled per client IP and across
every caller. Gemini is never involved; Postgres is a throwaway database per test.
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

from lemely.db.base import Base
from lemely.db.class_repo import ClassService
from lemely.db.invite_repo import InviteService
from lemely.db.models import Invite, School, SchoolClass, User
from lemely.db.models.enums import InviteRole, Role
from lemely.db.models.team import AssistantRole
from lemely.db.parent_repo import ParentLinkService
from lemely.runtime.config import DatabaseSettings
from lemely.web import deps_invites
from lemely.web.app import create_app
from lemely.web.deps import get_invite_service
from lemely.web.deps_invites import (
    INVITE_PREVIEW_GLOBAL_KEY,
    InvitePreviewLimiters,
    get_invite_preview_limiters,
    reset_invite_singletons,
)
from lemely.web.ratelimit import SlidingWindowLimiter

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi import FastAPI

_BLANK_NAMES = [None, "", "   "]
_PER_CLIENT_LIMIT = 3
_GLOBAL_LIMIT = 5


class FakeClock:
    """A settable clock for :class:`SlidingWindowLimiter` (no test sleeps a window out)."""

    def __init__(self, start: float = 1_000_000.0) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


# -- Fixtures ----------------------------------------------------------------------


def _server_reachable(url: str) -> bool:
    engine = create_engine(make_url(url).set(database="postgres"))
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

    admin = create_engine(make_url(base_url).set(database="postgres"), isolation_level="AUTOCOMMIT")
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
def clock() -> FakeClock:
    return FakeClock()


def _limiters(clock: FakeClock) -> InvitePreviewLimiters:
    return InvitePreviewLimiters(
        per_client=SlidingWindowLimiter(limit=_PER_CLIENT_LIMIT, window_seconds=60.0, clock=clock),
        global_=SlidingWindowLimiter(limit=_GLOBAL_LIMIT, window_seconds=60.0, clock=clock),
    )


def _app(sm: sessionmaker[Session], limiters: InvitePreviewLimiters | None = None) -> FastAPI:
    application = create_app()
    application.dependency_overrides[get_invite_service] = lambda: InviteService(
        sm, ClassService(sm), ParentLinkService(sm)
    )
    if limiters is not None:
        application.dependency_overrides[get_invite_preview_limiters] = lambda: limiters
    return application


@pytest.fixture
def limited_client(
    pg_sessionmaker: sessionmaker[Session], clock: FakeClock
) -> Iterator[TestClient]:
    """A client on the real limiter mechanism over a fake clock (tiny limits)."""
    app = _app(pg_sessionmaker, _limiters(clock))
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        reset_invite_singletons()


@pytest.fixture
def open_client(pg_sessionmaker: sessionmaker[Session]) -> Iterator[TestClient]:
    """A client whose limiters are far too generous to interfere with the leak tests."""
    app = _app(
        pg_sessionmaker,
        InvitePreviewLimiters(
            per_client=SlidingWindowLimiter(limit=1000, window_seconds=60.0, clock=FakeClock()),
            global_=SlidingWindowLimiter(limit=1000, window_seconds=60.0, clock=FakeClock()),
        ),
    )
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        reset_invite_singletons()


# -- Seeding -----------------------------------------------------------------------


def _seed_teacher(sm: sessionmaker[Session], display_name: str | None) -> tuple[uuid.UUID, str]:
    uid = uuid.uuid4()
    email = f"private.teacher.{uid.hex[:8]}@leaky-school.example"
    with sm.begin() as session:
        session.add(User(id=uid, email=email, role=Role.teacher, display_name=display_name))
    return uid, email


def _seed_class(sm: sessionmaker[Session], teacher_id: uuid.UUID) -> tuple[uuid.UUID, str]:
    class_id = uuid.uuid4()
    join_code = f"JOIN{uuid.uuid4().hex[:6].upper()}"
    with sm.begin() as session:
        school = School(id=uuid.uuid4(), name="Privacy Test School", seat_quota=5)
        session.add(school)
        session.flush()
        session.add(
            SchoolClass(
                id=class_id,
                teacher_id=teacher_id,
                school_id=school.id,
                name="Privacy Test Class",
                join_code=join_code,
            )
        )
    return class_id, join_code


def _mint_class_invite_code(
    sm: sessionmaker[Session], teacher_id: uuid.UUID, class_id: uuid.UUID
) -> str:
    service = InviteService(sm, ClassService(sm), ParentLinkService(sm))
    return service.mint_class_invite(teacher_id, Role.teacher, class_id).code


def _seed_assistant_invite(sm: sessionmaker[Session], teacher_id: uuid.UUID) -> str:
    code = f"ASST{uuid.uuid4().hex[:6].upper()}"
    with sm.begin() as session:
        session.add(
            Invite(
                code=code,
                role=InviteRole.assistant,
                created_by=teacher_id,
                team_teacher_id=teacher_id,
                assistant_role=AssistantRole.marker,
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
        )
    return code


def _assert_no_email(body_text: str, email: str) -> None:
    assert email not in body_text
    assert "@" not in body_text


# -- The leak: a blank display name must never fall back to the email ---------------


@pytest.mark.parametrize("display_name", _BLANK_NAMES)
def test_class_invite_preview_never_exposes_the_teacher_email(
    pg_sessionmaker: sessionmaker[Session], open_client: TestClient, display_name: str | None
) -> None:
    teacher, email = _seed_teacher(pg_sessionmaker, display_name)
    class_id, _ = _seed_class(pg_sessionmaker, teacher)
    code = _mint_class_invite_code(pg_sessionmaker, teacher, class_id)

    res = open_client.get(f"/api/invites/{code}")

    assert res.status_code == 200
    assert res.json()["className"] == "Privacy Test Class"
    assert res.json()["teacherName"] is None
    _assert_no_email(res.text, email)


@pytest.mark.parametrize("display_name", _BLANK_NAMES)
def test_join_code_preview_never_exposes_the_teacher_email(
    pg_sessionmaker: sessionmaker[Session], open_client: TestClient, display_name: str | None
) -> None:
    teacher, email = _seed_teacher(pg_sessionmaker, display_name)
    _, join_code = _seed_class(pg_sessionmaker, teacher)

    res = open_client.get(f"/api/invites/{join_code}")

    assert res.status_code == 200
    assert res.json()["className"] == "Privacy Test Class"
    assert res.json()["teacherName"] is None
    _assert_no_email(res.text, email)


@pytest.mark.parametrize("display_name", _BLANK_NAMES)
def test_assistant_invite_preview_never_exposes_the_teacher_email(
    pg_sessionmaker: sessionmaker[Session], open_client: TestClient, display_name: str | None
) -> None:
    teacher, email = _seed_teacher(pg_sessionmaker, display_name)
    code = _seed_assistant_invite(pg_sessionmaker, teacher)

    res = open_client.get(f"/api/invites/{code}")

    assert res.status_code == 200
    assert res.json()["teacherName"] is None
    _assert_no_email(res.text, email)


def test_previews_name_the_teacher_by_stripped_display_name(
    pg_sessionmaker: sessionmaker[Session], open_client: TestClient
) -> None:
    teacher, email = _seed_teacher(pg_sessionmaker, "  Ms Iman  ")
    class_id, join_code = _seed_class(pg_sessionmaker, teacher)
    invite_code = _mint_class_invite_code(pg_sessionmaker, teacher, class_id)

    for code in (invite_code, join_code):
        res = open_client.get(f"/api/invites/{code}")
        assert res.status_code == 200
        assert res.json()["teacherName"] == "Ms Iman"
        _assert_no_email(res.text, email)


# -- Rate limiting -------------------------------------------------------------------


def _seed_join_code(sm: sessionmaker[Session]) -> str:
    teacher, _ = _seed_teacher(sm, "Mr Limit")
    return _seed_class(sm, teacher)[1]


def _get(client: TestClient, code: str, ip: str) -> int:
    return client.get(f"/api/invites/{code}", headers={"X-Forwarded-For": ip}).status_code


def test_per_client_limit_returns_429_with_retry_after_and_a_generic_body(
    pg_sessionmaker: sessionmaker[Session], limited_client: TestClient
) -> None:
    code = _seed_join_code(pg_sessionmaker)
    for _ in range(_PER_CLIENT_LIMIT):
        assert _get(limited_client, code, "203.0.113.7") == 200

    res = limited_client.get(f"/api/invites/{code}", headers={"X-Forwarded-For": "203.0.113.7"})

    assert res.status_code == 429
    assert int(res.headers["Retry-After"]) >= 1
    assert res.json() == {"detail": f"Too many requests; retry in {res.headers['Retry-After']}s."}
    assert code not in res.text
    assert "203.0.113.7" not in res.text


def test_a_different_ip_is_still_served_under_the_per_client_limit(
    pg_sessionmaker: sessionmaker[Session], limited_client: TestClient
) -> None:
    code = _seed_join_code(pg_sessionmaker)
    for _ in range(_PER_CLIENT_LIMIT):
        assert _get(limited_client, code, "203.0.113.7") == 200
    assert _get(limited_client, code, "203.0.113.7") == 429

    assert _get(limited_client, code, "198.51.100.9") == 200


def test_per_client_window_expires(
    pg_sessionmaker: sessionmaker[Session], limited_client: TestClient, clock: FakeClock
) -> None:
    code = _seed_join_code(pg_sessionmaker)
    for _ in range(_PER_CLIENT_LIMIT):
        assert _get(limited_client, code, "203.0.113.7") == 200
    assert _get(limited_client, code, "203.0.113.7") == 429

    clock.advance(61.0)

    assert _get(limited_client, code, "203.0.113.7") == 200


def test_global_cap_returns_429_even_for_a_fresh_ip(
    pg_sessionmaker: sessionmaker[Session], limited_client: TestClient
) -> None:
    code = _seed_join_code(pg_sessionmaker)
    # A caller rotating X-Forwarded-For gets a fresh per-client bucket every time, so
    # only the global cap binds it.
    for i in range(_GLOBAL_LIMIT):
        assert _get(limited_client, code, f"192.0.2.{i}") == 200

    res = limited_client.get(f"/api/invites/{code}", headers={"X-Forwarded-For": "192.0.2.200"})

    assert res.status_code == 429
    assert int(res.headers["Retry-After"]) >= 1


def test_unknown_codes_count_toward_the_limit(
    pg_sessionmaker: sessionmaker[Session], limited_client: TestClient
) -> None:
    for _ in range(_PER_CLIENT_LIMIT):
        assert _get(limited_client, "NOSUCHCODE", "203.0.113.7") == 404

    assert _get(limited_client, "NOSUCHCODE", "203.0.113.7") == 429


def test_default_limiters_enforce_the_named_constants() -> None:
    reset_invite_singletons()
    try:
        limiters = get_invite_preview_limiters()
        assert get_invite_preview_limiters() is limiters
        per_client = sum(limiters.per_client.allow("203.0.113.7") for _ in range(10_000))
        global_ = sum(limiters.global_.allow(INVITE_PREVIEW_GLOBAL_KEY) for _ in range(10_000))
        assert per_client == deps_invites._INVITE_PREVIEW_PER_CLIENT_LIMIT
        assert global_ == deps_invites._INVITE_PREVIEW_GLOBAL_LIMIT
    finally:
        reset_invite_singletons()


def test_reset_invite_singletons_evicts_a_populated_cache() -> None:
    get_invite_preview_limiters()
    assert get_invite_preview_limiters.cache_info().currsize == 1

    reset_invite_singletons()

    assert get_invite_preview_limiters.cache_info().currsize == 0
