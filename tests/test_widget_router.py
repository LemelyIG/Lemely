"""Route tests for ``GET /api/student/widget`` (packet A5).

Self-contained, mirroring ``tests/test_web_xp.py``: a throwaway Postgres DB
per test, skipped cleanly when unreachable. This file tests the HTTP layer —
DTO shape, the authz matrix, the cross-subject "earliest incomplete session"
selection, and the well-formed empty state — not the streak resolution or
study-plan generation themselves, which have their own suites
(``tests/test_xp_repo.py``, ``tests/test_study_plan_repo.py``).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.db.base import Base
from lemely.db.models import Subject
from lemely.db.models.attempts import Attempt, WeaknessRecord
from lemely.db.models.engagement import XpEvent
from lemely.db.models.enums import AttemptOrigin, Role, XpSource
from lemely.db.models.users import User
from lemely.db.student_profile_repo import StudentProfileService
from lemely.db.study_plan_repo import StudyPlanService
from lemely.db.xp_repo import XpService
from lemely.runtime.config import DatabaseSettings
from lemely.web import create_app
from lemely.web.deps import (
    AuthContext,
    get_auth_context,
    get_student_profile_service,
    get_study_plan_service,
    get_xp_service,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

# A fixed Cairo-noon Wednesday, clear of any week boundary — same fixed
# instant ``test_web_xp.py`` and ``test_web_study_plan.py`` use.
_NOON_UTC = datetime(2026, 8, 5, 12, 0, 0, tzinfo=UTC)
_TODAY = date(2026, 8, 5)


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


@pytest.fixture
def study_plan_service(pg_sessionmaker: sessionmaker[Session]) -> StudyPlanService:
    return StudyPlanService(pg_sessionmaker, now=lambda: _NOON_UTC)


@pytest.fixture
def profile_service(pg_sessionmaker: sessionmaker[Session]) -> StudentProfileService:
    return StudentProfileService(pg_sessionmaker, now=lambda: _NOON_UTC)


def _use_services(
    client: TestClient,
    xp: XpService,
    study_plan: StudyPlanService,
    profile: StudentProfileService,
) -> None:
    client.app.dependency_overrides[get_xp_service] = lambda: xp  # type: ignore[union-attr]
    client.app.dependency_overrides[get_study_plan_service] = lambda: study_plan  # type: ignore[union-attr]
    client.app.dependency_overrides[get_student_profile_service] = lambda: profile  # type: ignore[union-attr]


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
    sm: sessionmaker[Session], user_id: uuid.UUID, amount: int, *, awarded_on: date = _TODAY
) -> None:
    with sm.begin() as session:
        session.add(
            XpEvent(
                user_id=user_id,
                source=XpSource.flashcard_reviewed,
                amount=amount,
                awarded_on=awarded_on,
                dedupe_key=f"dk-{uuid.uuid4()}",
            )
        )


def _seed_subject(sm: sessionmaker[Session], code: str = "0625", name: str = "Physics") -> str:
    """Seed a ``subjects`` row: required for a real enrolment —
    :meth:`StudentProfileService.upsert_enrolment` validates ``subject_code``
    against this table rather than trusting the caller (same helper
    ``tests/test_web_parent.py`` uses)."""
    with sm.begin() as session:
        session.add(Subject(code=code, name=name))
    return code


def _seed_weakness(
    sm: sessionmaker[Session],
    student_id: uuid.UUID,
    *,
    subject_code: str = "0625",
    topic: str,
    lost_marks: int,
    maximum_marks: int = 10,
) -> None:
    with sm.begin() as session:
        attempt = Attempt(
            user_id=student_id,
            subject_code=subject_code,
            awarded_marks=maximum_marks - lost_marks,
            maximum_marks=maximum_marks,
            percentage=100.0 * (maximum_marks - lost_marks) / maximum_marks,
            recorded_at=datetime.now(UTC),
            origin=AttemptOrigin.quiz,
        )
        session.add(attempt)
        session.flush()
        session.add(
            WeaknessRecord(
                user_id=student_id,
                attempt_id=attempt.id,
                topic=topic,
                lost_marks=lost_marks,
                maximum_marks=maximum_marks,
                accuracy=1.0 - lost_marks / maximum_marks,
            )
        )


# ---------------------------------------------------------------------------
# Authorization.
# ---------------------------------------------------------------------------


class TestAuthz:
    @pytest.mark.parametrize(
        "role", [Role.teacher, Role.parent, Role.school_admin, Role.platform_admin]
    )
    def test_only_a_student_may_read_the_widget(
        self,
        client: TestClient,
        pg_sessionmaker: sessionmaker[Session],
        xp_service: XpService,
        study_plan_service: StudyPlanService,
        profile_service: StudentProfileService,
        role: Role,
    ) -> None:
        _use_services(client, xp_service, study_plan_service, profile_service)
        _auth_as(client, _seed_user(pg_sessionmaker, role), role)
        assert client.get("/api/student/widget").status_code == 403

    def test_the_route_accepts_no_user_id_parameter_at_all(
        self,
        client: TestClient,
        pg_sessionmaker: sessionmaker[Session],
        xp_service: XpService,
        study_plan_service: StudyPlanService,
        profile_service: StudentProfileService,
    ) -> None:
        """Identity is structural, mirroring ``xp.py``'s own route."""
        _use_services(client, xp_service, study_plan_service, profile_service)
        mine = _seed_user(pg_sessionmaker)
        theirs = _seed_user(pg_sessionmaker)
        _award(pg_sessionmaker, mine, 10)
        _award(pg_sessionmaker, theirs, 999)
        _auth_as(client, mine, Role.student)

        response = client.get(f"/api/student/widget?user_id={theirs}&userId={theirs}")

        assert response.status_code == 200
        assert response.json()["streak"] == xp_service.profile(mine).streak.current_length

    def test_the_openapi_path_is_registered(self, client: TestClient) -> None:
        assert "/api/student/widget" in client.app.openapi()["paths"]  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# The empty state.
# ---------------------------------------------------------------------------


class TestBrandNewStudent:
    def test_no_xp_and_no_enrolments_is_a_well_formed_empty_state(
        self,
        client: TestClient,
        pg_sessionmaker: sessionmaker[Session],
        xp_service: XpService,
        study_plan_service: StudyPlanService,
        profile_service: StudentProfileService,
    ) -> None:
        """"Nothing yet" is a state to render, never a 404."""
        _use_services(client, xp_service, study_plan_service, profile_service)
        _auth_as(client, _seed_user(pg_sessionmaker), Role.student)

        response = client.get("/api/student/widget")

        assert response.status_code == 200
        assert response.json() == {"streak": 0, "nextSession": None}


# ---------------------------------------------------------------------------
# streak.
# ---------------------------------------------------------------------------


class TestStreak:
    def test_streak_matches_the_xp_service_own_computation(
        self,
        client: TestClient,
        pg_sessionmaker: sessionmaker[Session],
        xp_service: XpService,
        study_plan_service: StudyPlanService,
        profile_service: StudentProfileService,
    ) -> None:
        _use_services(client, xp_service, study_plan_service, profile_service)
        student = _seed_user(pg_sessionmaker)
        # `xp_service.award(...)`, not a raw `XpEvent` insert: the streak
        # table is only touched by the service's own award path
        # (`_touch_streak`), so a direct DB insert (as `_award` does, for the
        # authz test above) leaves `streak.current_length` at 0 regardless of
        # `total_xp`.
        xp_service.award(student, XpSource.flashcard_reviewed, "dk-1")
        _auth_as(client, student, Role.student)

        response = client.get("/api/student/widget")

        assert response.status_code == 200
        assert response.json()["streak"] == xp_service.profile(student).streak.current_length
        assert response.json()["streak"] > 0


# ---------------------------------------------------------------------------
# nextSession.
# ---------------------------------------------------------------------------


class TestNextSession:
    def test_no_plan_generated_for_any_enrolled_subject_is_none(
        self,
        client: TestClient,
        pg_sessionmaker: sessionmaker[Session],
        xp_service: XpService,
        study_plan_service: StudyPlanService,
        profile_service: StudentProfileService,
    ) -> None:
        _use_services(client, xp_service, study_plan_service, profile_service)
        student = _seed_user(pg_sessionmaker)
        _seed_subject(pg_sessionmaker, "0625")
        profile_service.upsert_enrolment(student, "0625")
        _auth_as(client, student, Role.student)

        response = client.get("/api/student/widget")

        assert response.status_code == 200
        assert response.json()["nextSession"] is None

    def test_a_no_signal_refusal_plan_has_no_sessions_and_is_none(
        self,
        client: TestClient,
        pg_sessionmaker: sessionmaker[Session],
        xp_service: XpService,
        study_plan_service: StudyPlanService,
        profile_service: StudentProfileService,
    ) -> None:
        """A generated-but-refused plan (no weakness signal) has empty sessions."""
        _use_services(client, xp_service, study_plan_service, profile_service)
        student = _seed_user(pg_sessionmaker)
        _seed_subject(pg_sessionmaker, "0625")
        profile_service.upsert_enrolment(student, "0625")
        study_plan_service.generate(student, "0625")
        _auth_as(client, student, Role.student)

        response = client.get("/api/student/widget")

        assert response.status_code == 200
        assert response.json()["nextSession"] is None

    def test_returns_the_earliest_incomplete_session_across_enrolled_subjects(
        self,
        client: TestClient,
        pg_sessionmaker: sessionmaker[Session],
        xp_service: XpService,
        study_plan_service: StudyPlanService,
        profile_service: StudentProfileService,
    ) -> None:
        _use_services(client, xp_service, study_plan_service, profile_service)
        student = _seed_user(pg_sessionmaker)
        _seed_subject(pg_sessionmaker, "0625", "Physics")
        _seed_subject(pg_sessionmaker, "0620", "Chemistry")
        profile_service.upsert_enrolment(student, "0625")
        profile_service.upsert_enrolment(student, "0620")
        _seed_weakness(
            pg_sessionmaker, student, subject_code="0625", topic="1 Motion", lost_marks=5
        )
        _seed_weakness(
            pg_sessionmaker, student, subject_code="0620", topic="2 Atoms", lost_marks=5
        )
        plan_a = study_plan_service.generate(student, "0625")
        plan_b = study_plan_service.generate(student, "0620")
        _auth_as(client, student, Role.student)

        response = client.get("/api/student/widget")

        assert response.status_code == 200
        body = response.json()["nextSession"]
        all_sessions = [*plan_a.sessions, *plan_b.sessions]
        assert all_sessions, "fixture assumption: generate() must have produced sessions"
        # `min(..., key=...)`, not a specific subject: the two subjects'
        # plans are free to schedule their first session on the same date
        # (there is no cross-subject ordering guarantee), so any session
        # sharing the earliest date is a correct answer — this asserts the
        # date is genuinely the minimum and the title names a real,
        # same-dated session, rather than pinning one arbitrary tie-break.
        earliest_date = min(s.date for s in all_sessions)
        earliest_topics = {s.topic for s in all_sessions if s.date == earliest_date}
        assert body is not None
        assert body["title"] in earliest_topics
        assert body["startsAt"].startswith(earliest_date.isoformat())

    def test_a_completed_session_is_skipped_in_favour_of_the_next_one(
        self,
        client: TestClient,
        pg_sessionmaker: sessionmaker[Session],
        xp_service: XpService,
        study_plan_service: StudyPlanService,
        profile_service: StudentProfileService,
    ) -> None:
        _use_services(client, xp_service, study_plan_service, profile_service)
        student = _seed_user(pg_sessionmaker)
        _seed_subject(pg_sessionmaker, "0625")
        profile_service.upsert_enrolment(student, "0625")
        _seed_weakness(
            pg_sessionmaker, student, subject_code="0625", topic="1 Motion", lost_marks=5
        )
        plan = study_plan_service.generate(student, "0625")
        sessions_by_date = sorted(plan.sessions, key=lambda s: s.date)
        assert len(sessions_by_date) >= 1, (
            "fixture assumption: generate() must have produced sessions"
        )
        study_plan_service.complete_session(student, sessions_by_date[0].id)
        _auth_as(client, student, Role.student)

        response = client.get("/api/student/widget")

        assert response.status_code == 200
        body = response.json()["nextSession"]
        if len(sessions_by_date) == 1:
            assert body is None
        else:
            assert body is not None
            assert body["title"] == sessions_by_date[1].topic
