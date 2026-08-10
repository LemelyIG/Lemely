"""Route tests for ``GET /api/student/xp`` (P5.8 chunk A, D5.13).

Self-contained, mirroring ``tests/test_web_leaderboard.py``: a throwaway
Postgres DB per test, skipped cleanly when unreachable, XP seeded directly as
:class:`~lemely.db.models.engagement.XpEvent` rows. This file tests the HTTP
layer — DTO shape, level projection, window boundaries, the authz matrix — not
the award engine or the streak resolution, which have their own suites in
``tests/test_xp_repo.py``.

Covers the four-role authz matrix, the structural impossibility of reading
another student's profile, a brand-new student's well-formed zero profile, the
week window agreeing with the leaderboard's, the calendar's absent-not-zero
rule, and the "no mark on the wire" pin asserted over the real response body
rather than the model definition.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.db.base import Base
from lemely.db.models.engagement import XpEvent
from lemely.db.models.enums import Role, XpSource
from lemely.db.models.users import User
from lemely.db.xp_repo import XpService, week_bounds
from lemely.runtime.config import DatabaseSettings
from lemely.web import create_app
from lemely.web.deps import AuthContext, get_auth_context, get_xp_service

if TYPE_CHECKING:
    from collections.abc import Iterator

# A fixed Cairo-noon Wednesday, clear of any week boundary. Cairo is UTC+3 in
# August (Egypt reinstated summer time in 2023 — P5.6 chunk A's note), so
# 12:00 UTC is 15:00 Cairo on the same civil date either way.
_NOON_UTC = datetime(2026, 8, 5, 12, 0, 0, tzinfo=UTC)
_TODAY = date(2026, 8, 5)
_MONDAY = date(2026, 8, 3)
_SUNDAY = date(2026, 8, 9)


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
def xp_service(pg_sessionmaker: sessionmaker[Session]) -> XpService:
    return XpService(pg_sessionmaker, now=lambda: _NOON_UTC)


def _use_service(client: TestClient, xp_service: XpService) -> None:
    client.app.dependency_overrides[get_xp_service] = lambda: xp_service  # type: ignore[union-attr]


def _auth_as(client: TestClient, user_id: uuid.UUID, role: Role) -> None:
    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(user_id), role=role.value
    )


def _seed_user(sm: sessionmaker[Session], role: Role = Role.student) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role, display_name="Student"))
    return uid


def _award(
    sm: sessionmaker[Session],
    user_id: uuid.UUID,
    amount: int,
    *,
    awarded_on: date = _TODAY,
    source: XpSource = XpSource.flashcard_reviewed,
) -> None:
    with sm.begin() as session:
        session.add(
            XpEvent(
                user_id=user_id,
                source=source,
                amount=amount,
                awarded_on=awarded_on,
                dedupe_key=f"dk-{uuid.uuid4()}",
            )
        )


# ---------------------------------------------------------------------------
# Authorization.
# ---------------------------------------------------------------------------


class TestAuthz:
    @pytest.mark.parametrize(
        "role", [Role.teacher, Role.parent, Role.school_admin, Role.platform_admin]
    )
    def test_only_a_student_may_read_an_xp_profile(
        self,
        client: TestClient,
        pg_sessionmaker: sessionmaker[Session],
        xp_service: XpService,
        role: Role,
    ) -> None:
        """D5.1 §10 fixes XP as a student-only mechanic, so the router is student-gated.

        Unlike P5.6's deliberately role-agnostic notification router — whose
        ``at_risk_alert`` genuinely addresses a teacher and a parent — this
        surface has exactly one intended reader.
        """
        _use_service(client, xp_service)
        _auth_as(client, _seed_user(pg_sessionmaker, role), role)
        assert client.get("/api/student/xp").status_code == 403

    def test_the_route_accepts_no_user_id_parameter_at_all(
        self, client: TestClient, pg_sessionmaker: sessionmaker[Session], xp_service: XpService
    ) -> None:
        """Identity is structural (D5.13 §5), not a check a later edit could drop.

        A caller-supplied id is not merely rejected — the parameter does not
        exist, so passing one changes nothing and the caller still reads their
        own profile.
        """
        _use_service(client, xp_service)
        mine = _seed_user(pg_sessionmaker)
        theirs = _seed_user(pg_sessionmaker)
        _award(pg_sessionmaker, mine, 10)
        _award(pg_sessionmaker, theirs, 999)
        _auth_as(client, mine, Role.student)

        response = client.get(f"/api/student/xp?user_id={theirs}&userId={theirs}")

        assert response.status_code == 200
        assert response.json()["totalXp"] == 10

    def test_the_openapi_path_is_registered(self, client: TestClient) -> None:
        """Read ``app.openapi()``, never ``app.routes``.

        This FastAPI version wraps included routers in an opaque
        ``_IncludedRouter`` with no ``.path``, so an ``app.routes`` scan finds
        nothing and passes for the wrong reason (P5.5 chunk C's trap).
        """
        assert "/api/student/xp" in client.app.openapi()["paths"]  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# The empty state.
# ---------------------------------------------------------------------------


class TestBrandNewStudent:
    def test_a_student_with_no_xp_gets_a_well_formed_zero_profile(
        self, client: TestClient, pg_sessionmaker: sessionmaker[Session], xp_service: XpService
    ) -> None:
        """ "You have not started yet" is a state to render, never a 404."""
        _use_service(client, xp_service)
        _auth_as(client, _seed_user(pg_sessionmaker), Role.student)

        response = client.get("/api/student/xp")

        assert response.status_code == 200
        body = response.json()
        assert body["totalXp"] == 0
        assert body["level"] == 1
        assert body["levelStartXp"] == 0
        assert body["nextLevelXp"] == 100
        assert body["streak"] == {
            "current": 0,
            "longest": 0,
            "lastActiveOn": None,
            "freezesAvailable": 0,
        }
        assert body["week"]["total"] == 0
        assert body["calendar"] == []

    def test_every_source_appears_in_the_week_split_even_at_zero(
        self, client: TestClient, pg_sessionmaker: sessionmaker[Session], xp_service: XpService
    ) -> None:
        """A bar chart never has to special-case a missing key (D5.1 §1's four sources)."""
        _use_service(client, xp_service)
        _auth_as(client, _seed_user(pg_sessionmaker), Role.student)

        by_source = client.get("/api/student/xp").json()["week"]["bySource"]

        assert [entry["source"] for entry in by_source] == [source.value for source in XpSource]
        assert all(entry["xp"] == 0 for entry in by_source)


# ---------------------------------------------------------------------------
# Level projection.
# ---------------------------------------------------------------------------


class TestLevel:
    @pytest.mark.parametrize(
        ("total", "level", "start", "nxt"),
        [(0, 1, 0, 100), (99, 1, 0, 100), (100, 2, 100, 400), (1600, 5, 1600, 2500)],
    )
    def test_the_level_band_reaches_the_wire_intact(
        self,
        client: TestClient,
        pg_sessionmaker: sessionmaker[Session],
        xp_service: XpService,
        total: int,
        level: int,
        start: int,
        nxt: int,
    ) -> None:
        """D5.13 §1: the screen draws its progress bar without re-deriving the curve."""
        _use_service(client, xp_service)
        user_id = _seed_user(pg_sessionmaker)
        if total:
            _award(pg_sessionmaker, user_id, total)
        _auth_as(client, user_id, Role.student)

        body = client.get("/api/student/xp").json()

        assert (body["totalXp"], body["level"]) == (total, level)
        assert (body["levelStartXp"], body["nextLevelXp"]) == (start, nxt)

    def test_the_level_counts_all_time_xp_not_this_week(
        self, client: TestClient, pg_sessionmaker: sessionmaker[Session], xp_service: XpService
    ) -> None:
        """A level is a record of accumulated work; only the *breakdown* is weekly.

        Were the level weekly it would fall every Monday, which is the opposite
        of the "training log" S-31 is specified to feel like.
        """
        _use_service(client, xp_service)
        user_id = _seed_user(pg_sessionmaker)
        _award(pg_sessionmaker, user_id, 400, awarded_on=date(2026, 1, 5))
        _auth_as(client, user_id, Role.student)

        body = client.get("/api/student/xp").json()

        assert body["totalXp"] == 400
        assert body["level"] == 3
        assert body["week"]["total"] == 0


# ---------------------------------------------------------------------------
# The weekly window.
# ---------------------------------------------------------------------------


class TestWeekWindow:
    def test_the_week_is_monday_to_sunday(
        self, client: TestClient, pg_sessionmaker: sessionmaker[Session], xp_service: XpService
    ) -> None:
        """D5.1 §6, and the same helper the leaderboard uses (D5.13 §2)."""
        _use_service(client, xp_service)
        _auth_as(client, _seed_user(pg_sessionmaker), Role.student)

        week = client.get("/api/student/xp").json()["week"]

        assert (week["start"], week["end"]) == (_MONDAY.isoformat(), _SUNDAY.isoformat())
        assert week_bounds(_TODAY) == (_MONDAY, _SUNDAY)

    def test_xp_from_last_week_is_excluded_from_the_split_but_not_the_total(
        self, client: TestClient, pg_sessionmaker: sessionmaker[Session], xp_service: XpService
    ) -> None:
        """The boundary case that would otherwise pass by both numbers being equal."""
        _use_service(client, xp_service)
        user_id = _seed_user(pg_sessionmaker)
        _award(pg_sessionmaker, user_id, 30, awarded_on=_MONDAY - timedelta(days=1))
        _award(pg_sessionmaker, user_id, 20, awarded_on=_MONDAY)
        _auth_as(client, user_id, Role.student)

        body = client.get("/api/student/xp").json()

        assert body["totalXp"] == 50
        assert body["week"]["total"] == 20

    def test_the_split_sums_to_the_week_total(
        self, client: TestClient, pg_sessionmaker: sessionmaker[Session], xp_service: XpService
    ) -> None:
        _use_service(client, xp_service)
        user_id = _seed_user(pg_sessionmaker)
        _award(pg_sessionmaker, user_id, 50, source=XpSource.paper_corrected)
        _award(pg_sessionmaker, user_id, 30, source=XpSource.quiz_completed)
        _award(pg_sessionmaker, user_id, 4, source=XpSource.flashcard_reviewed)
        _auth_as(client, user_id, Role.student)

        week = client.get("/api/student/xp").json()["week"]

        assert sum(entry["xp"] for entry in week["bySource"]) == week["total"] == 84
        by_source = {entry["source"]: entry["xp"] for entry in week["bySource"]}
        assert by_source["paper_corrected"] == 50
        assert by_source["study_session_completed"] == 0


# ---------------------------------------------------------------------------
# The streak calendar.
# ---------------------------------------------------------------------------


class TestCalendar:
    def test_the_window_is_the_last_28_days_ending_today(
        self, client: TestClient, pg_sessionmaker: sessionmaker[Session], xp_service: XpService
    ) -> None:
        """The client fills the grid from the window, so it must be stated (D5.13 §4)."""
        _use_service(client, xp_service)
        _auth_as(client, _seed_user(pg_sessionmaker), Role.student)

        body = client.get("/api/student/xp").json()

        assert body["calendarEnd"] == _TODAY.isoformat()
        assert body["calendarStart"] == (_TODAY - timedelta(days=27)).isoformat()

    def test_days_with_no_xp_are_absent_rather_than_zero(
        self, client: TestClient, pg_sessionmaker: sessionmaker[Session], xp_service: XpService
    ) -> None:
        """D5.13 §4's rule, pinned.

        A zero-valued day and an out-of-window day would otherwise be
        indistinguishable to the client, which is exactly how an empty day gets
        rendered as a missing one.
        """
        _use_service(client, xp_service)
        user_id = _seed_user(pg_sessionmaker)
        _award(pg_sessionmaker, user_id, 10, awarded_on=_TODAY)
        _award(pg_sessionmaker, user_id, 5, awarded_on=_TODAY - timedelta(days=3))
        _auth_as(client, user_id, Role.student)

        calendar = client.get("/api/student/xp").json()["calendar"]

        assert [entry["day"] for entry in calendar] == [
            (_TODAY - timedelta(days=3)).isoformat(),
            _TODAY.isoformat(),
        ]
        assert all(entry["xp"] > 0 for entry in calendar)

    def test_a_days_xp_is_summed_across_sources(
        self, client: TestClient, pg_sessionmaker: sessionmaker[Session], xp_service: XpService
    ) -> None:
        _use_service(client, xp_service)
        user_id = _seed_user(pg_sessionmaker)
        _award(pg_sessionmaker, user_id, 50, source=XpSource.paper_corrected)
        _award(pg_sessionmaker, user_id, 30, source=XpSource.quiz_completed)
        _auth_as(client, user_id, Role.student)

        calendar = client.get("/api/student/xp").json()["calendar"]

        assert calendar == [{"day": _TODAY.isoformat(), "xp": 80}]

    def test_xp_older_than_the_window_is_excluded_from_the_calendar_only(
        self, client: TestClient, pg_sessionmaker: sessionmaker[Session], xp_service: XpService
    ) -> None:
        """Off-by-one guard on both edges of the 28-day window."""
        _use_service(client, xp_service)
        user_id = _seed_user(pg_sessionmaker)
        _award(pg_sessionmaker, user_id, 7, awarded_on=_TODAY - timedelta(days=27))
        _award(pg_sessionmaker, user_id, 9, awarded_on=_TODAY - timedelta(days=28))
        _auth_as(client, user_id, Role.student)

        body = client.get("/api/student/xp").json()

        assert body["calendar"] == [{"day": (_TODAY - timedelta(days=27)).isoformat(), "xp": 7}]
        assert body["totalXp"] == 16


# ---------------------------------------------------------------------------
# D5.1 §0 over the real response body.
# ---------------------------------------------------------------------------


class TestNoMarkOnTheWire:
    def test_the_response_body_carries_nothing_shaped_like_a_mark(
        self, client: TestClient, pg_sessionmaker: sessionmaker[Session], xp_service: XpService
    ) -> None:
        """Asserted over the *body*, not the model, so a projection bug is caught too.

        ``tests/test_schemas_xp.py`` pins the declared field sets; this pins
        what actually reaches the wire, including any key a future
        ``model_extra`` or hand-built dict could add.
        """
        _use_service(client, xp_service)
        user_id = _seed_user(pg_sessionmaker)
        _award(pg_sessionmaker, user_id, 50, source=XpSource.paper_corrected)
        _auth_as(client, user_id, Role.student)

        response = client.get("/api/student/xp")

        assert response.status_code == 200
        rendered = response.text.lower()
        for forbidden in ("mark", "percent", "grade", "accuracy", "score", "confidence"):
            assert forbidden not in rendered, f"{forbidden!r} reached the S-31 wire"
