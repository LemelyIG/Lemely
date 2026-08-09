"""Route tests for ``GET /api/student/leaderboard`` (P5.3 chunk B).

Self-contained (mirrors ``tests/test_web_study_plan.py``) — a throwaway
Postgres DB per test, skipped cleanly when unreachable. XP rows are seeded
directly as :class:`~lemely.db.models.engagement.XpEvent` rows, mirroring
``tests/test_leaderboard_repo.py`` — this file tests the HTTP layer (DTO
shape, query-param parsing, status-code mapping), not the ranking query
itself, which already has its own suite.

Covers the authz matrix (non-student roles rejected on every scope; a
student requesting a class they are not enrolled in; the structural
impossibility of a student requesting another student's board), the
school-unavailable wire shape, a zero-XP viewer's null rank, an opted-out
student's absence from someone else's board body, and the opt-out/opt-in
round trip restoring an identical rank.
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
from lemely.db.leaderboard_repo import ANONYMOUS_DISPLAY_NAME, LeaderboardService
from lemely.db.models.academic import Subject
from lemely.db.models.engagement import XpEvent
from lemely.db.models.enums import Role, SeatStatus, XpSource
from lemely.db.models.orgs import ClassEnrollment, School, SchoolClass, Seat
from lemely.db.models.profiles import StudentProfile
from lemely.db.models.users import User
from lemely.db.student_profile_repo import StudentProfileService
from lemely.runtime.config import DatabaseSettings
from lemely.web import create_app
from lemely.web.deps import (
    AuthContext,
    get_auth_context,
    get_leaderboard_service,
    get_student_profile_service,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

# A fixed Cairo-noon Wednesday, clear of any week boundary.
_NOON_UTC = datetime(2026, 8, 5, 12, 0, 0, tzinfo=UTC)
_THIS_WEEK_DATE = date(2026, 8, 5)


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
def leaderboard_service(pg_sessionmaker: sessionmaker[Session]) -> LeaderboardService:
    return LeaderboardService(pg_sessionmaker, now=lambda: _NOON_UTC)


@pytest.fixture
def student_profile_service(pg_sessionmaker: sessionmaker[Session]) -> StudentProfileService:
    return StudentProfileService(pg_sessionmaker)


def _use_services(
    client: TestClient,
    leaderboard_service: LeaderboardService,
    student_profile_service: StudentProfileService,
) -> None:
    client.app.dependency_overrides[get_leaderboard_service] = lambda: leaderboard_service  # type: ignore[union-attr]
    client.app.dependency_overrides[get_student_profile_service] = lambda: student_profile_service  # type: ignore[union-attr]


def _auth_as(client: TestClient, user_id: uuid.UUID, role: Role) -> None:
    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(user_id), role=role.value
    )


def _seed_user(
    sm: sessionmaker[Session], role: Role = Role.student, *, display_name: str | None = None
) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role, display_name=display_name))
    return uid


def _award(
    sm: sessionmaker[Session],
    user_id: uuid.UUID,
    amount: int,
    *,
    awarded_on: date = _THIS_WEEK_DATE,
    subject_code: str | None = None,
    dedupe_key: str | None = None,
) -> None:
    with sm.begin() as session:
        session.add(
            XpEvent(
                user_id=user_id,
                source=XpSource.flashcard_reviewed,
                amount=amount,
                awarded_on=awarded_on,
                subject_code=subject_code,
                dedupe_key=dedupe_key or f"dk-{uuid.uuid4()}",
            )
        )


def _seed_subject(sm: sessionmaker[Session], code: str) -> None:
    with sm.begin() as session:
        existing = session.scalar(sa.select(Subject).where(Subject.code == code))
        if existing is None:
            session.add(Subject(code=code, name=f"Subject {code}"))


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


def _seed_class(sm: sessionmaker[Session]) -> uuid.UUID:
    class_id = uuid.uuid4()
    teacher_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=teacher_id, email=f"{teacher_id}@example.com", role=Role.teacher))
        session.flush()
        session.add(SchoolClass(id=class_id, school_id=None, teacher_id=teacher_id, name="9A"))
    return class_id


def _enrol(sm: sessionmaker[Session], class_id: uuid.UUID, student_id: uuid.UUID) -> None:
    with sm.begin() as session:
        session.add(ClassEnrollment(class_id=class_id, student_id=student_id))


# ---------------------------------------------------------------------------
# Basic ranking, per scope and per basis.
# ---------------------------------------------------------------------------


def test_global_scope_returns_correctly_ordered_rows(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    leaderboard_service: LeaderboardService,
    student_profile_service: StudentProfileService,
) -> None:
    _use_services(client, leaderboard_service, student_profile_service)
    top = _seed_user(pg_sessionmaker, display_name="Top Student")
    mid = _seed_user(pg_sessionmaker, display_name="Mid Student")
    viewer = _seed_user(pg_sessionmaker, display_name="Viewer")
    _award(pg_sessionmaker, top, 100)
    _award(pg_sessionmaker, mid, 50)
    _auth_as(client, viewer, Role.student)

    resp = client.get("/api/student/leaderboard", params={"scope": "global"})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ok"
    assert [row["userId"] for row in body["rows"]] == [str(top), str(mid)]
    assert body["rows"][0]["displayName"] == "Top Student"
    assert body["rows"][0]["rank"] == 1
    assert body["rows"][1]["rank"] == 2
    # Inverse: reversing the seeded XP would reverse this order, so the
    # assertion is proving real ordering, not an accidental match.
    assert body["rows"][0]["xp"] > body["rows"][1]["xp"]


def test_a_student_without_a_display_name_is_never_shown_by_email(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    leaderboard_service: LeaderboardService,
    student_profile_service: StudentProfileService,
) -> None:
    """An unnamed student ranks normally, under a placeholder — never their email.

    ``display_name`` is nullable at signup, and the rest of the codebase falls
    back to ``email`` when it is unset. That is fine for a quiz result list,
    which only the class that sat the quiz can see. It is not fine here:
    ``scope=global`` shows every ranked student to every other student on the
    platform, so the same fallback would broadcast a real contact address to
    strangers — undercutting the premise D5.1 §0 reasons from, that the
    leaderboard is the one public surface in this product.

    Asserting over the **response body** is the point: this is about what
    leaves the server, not about what the repo intended.
    """
    _use_services(client, leaderboard_service, student_profile_service)
    unnamed = _seed_user(pg_sessionmaker, display_name=None)
    viewer = _seed_user(pg_sessionmaker, display_name="Viewer")
    _award(pg_sessionmaker, unnamed, 100)
    _auth_as(client, viewer, Role.student)

    resp = client.get("/api/student/leaderboard", params={"scope": "global"})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    # They are still ranked — anonymity is not exclusion.
    assert [row["userId"] for row in body["rows"]] == [str(unnamed)]
    assert body["rows"][0]["rank"] == 1
    assert body["rows"][0]["displayName"] == ANONYMOUS_DISPLAY_NAME
    # The strong form: no address escapes anywhere in the payload, not just in
    # the field we happened to check.
    assert "@" not in resp.text


def test_per_subject_basis_filters_to_that_subject_only(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    leaderboard_service: LeaderboardService,
    student_profile_service: StudentProfileService,
) -> None:
    _use_services(client, leaderboard_service, student_profile_service)
    _seed_subject(pg_sessionmaker, "0625")
    _seed_subject(pg_sessionmaker, "0580")
    student = _seed_user(pg_sessionmaker)
    viewer = _seed_user(pg_sessionmaker)
    _award(pg_sessionmaker, student, 40, subject_code="0625", dedupe_key="p")
    _award(pg_sessionmaker, student, 30, subject_code="0580", dedupe_key="m")
    _auth_as(client, viewer, Role.student)

    physics = client.get(
        "/api/student/leaderboard", params={"scope": "global", "basis": "0625"}
    ).json()
    row = next(r for r in physics["rows"] if r["userId"] == str(student))
    assert row["xp"] == 40

    # Inverse: the total basis sums across subjects rather than filtering.
    total = client.get(
        "/api/student/leaderboard", params={"scope": "global", "basis": "total"}
    ).json()
    row = next(r for r in total["rows"] if r["userId"] == str(student))
    assert row["xp"] == 70


def test_class_scope_returns_only_classmates(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    leaderboard_service: LeaderboardService,
    student_profile_service: StudentProfileService,
) -> None:
    _use_services(client, leaderboard_service, student_profile_service)
    class_id = _seed_class(pg_sessionmaker)
    viewer = _seed_user(pg_sessionmaker)
    classmate = _seed_user(pg_sessionmaker)
    outsider = _seed_user(pg_sessionmaker)
    _enrol(pg_sessionmaker, class_id, viewer)
    _enrol(pg_sessionmaker, class_id, classmate)
    _award(pg_sessionmaker, viewer, 10)
    _award(pg_sessionmaker, classmate, 20)
    _award(pg_sessionmaker, outsider, 999)
    _auth_as(client, viewer, Role.student)

    resp = client.get(
        "/api/student/leaderboard", params={"scope": "class", "class_id": str(class_id)}
    )

    assert resp.status_code == 200
    ids = {row["userId"] for row in resp.json()["rows"]}
    assert ids == {str(viewer), str(classmate)}
    assert str(outsider) not in ids


# ---------------------------------------------------------------------------
# Authz matrix.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("role", [Role.teacher, Role.parent, Role.school_admin])
def test_non_student_roles_are_rejected(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    leaderboard_service: LeaderboardService,
    student_profile_service: StudentProfileService,
    role: Role,
) -> None:
    _use_services(client, leaderboard_service, student_profile_service)
    non_student = _seed_user(pg_sessionmaker, role)
    _auth_as(client, non_student, role)

    resp = client.get("/api/student/leaderboard")

    assert resp.status_code == 403
    # Inverse: the identical route, as a student, succeeds.
    student = _seed_user(pg_sessionmaker, Role.student)
    _auth_as(client, student, Role.student)
    assert client.get("/api/student/leaderboard").status_code == 200


def test_student_not_enrolled_in_requested_class_gets_403(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    leaderboard_service: LeaderboardService,
    student_profile_service: StudentProfileService,
) -> None:
    _use_services(client, leaderboard_service, student_profile_service)
    class_id = _seed_class(pg_sessionmaker)
    viewer = _seed_user(pg_sessionmaker)  # never enrolled
    _auth_as(client, viewer, Role.student)

    resp = client.get(
        "/api/student/leaderboard", params={"scope": "class", "class_id": str(class_id)}
    )

    assert resp.status_code == 403
    # Inverse: enrolling the same viewer in the same class flips it to 200.
    _enrol(pg_sessionmaker, class_id, viewer)
    ok = client.get(
        "/api/student/leaderboard", params={"scope": "class", "class_id": str(class_id)}
    )
    assert ok.status_code == 200


def test_class_scope_without_class_id_is_422(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    leaderboard_service: LeaderboardService,
    student_profile_service: StudentProfileService,
) -> None:
    _use_services(client, leaderboard_service, student_profile_service)
    student = _seed_user(pg_sessionmaker)
    _auth_as(client, student, Role.student)

    resp = client.get("/api/student/leaderboard", params={"scope": "class"})

    assert resp.status_code == 422


def test_a_student_cannot_see_another_students_board_as_their_own(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    leaderboard_service: LeaderboardService,
    student_profile_service: StudentProfileService,
) -> None:
    """Identity is always the token's ``sub`` — there is no caller-supplied
    viewer id anywhere on this route, so a smuggled id is simply ignored,
    never honoured (mirrors ``test_post_takes_identity_from_the_token_never_the_payload``
    in ``tests/test_web_study_plan.py``)."""
    _use_services(client, leaderboard_service, student_profile_service)
    victim = _seed_user(pg_sessionmaker)
    attacker = _seed_user(pg_sessionmaker)
    _award(pg_sessionmaker, victim, 500)
    _award(pg_sessionmaker, attacker, 5)
    _auth_as(client, attacker, Role.student)

    # extra query params outside this route's declared signature are simply
    # dropped by FastAPI, never bound to anything -- this proves the viewer
    # seen server-side is the token's, not any smuggled value.
    resp = client.get(
        "/api/student/leaderboard",
        params={"scope": "global", "userId": str(victim), "studentId": str(victim)},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["viewer"]["userId"] == str(attacker)
    assert body["viewer"]["xp"] == 5
    # Inverse: the victim's real board, read as themselves, shows their own xp.
    _auth_as(client, victim, Role.student)
    victim_body = client.get("/api/student/leaderboard", params={"scope": "global"}).json()
    assert victim_body["viewer"]["userId"] == str(victim)
    assert victim_body["viewer"]["xp"] == 500


# ---------------------------------------------------------------------------
# Opt-out — absence from the response body, and the school-unavailable shape.
# ---------------------------------------------------------------------------


def test_opted_out_student_absent_from_response_body(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    leaderboard_service: LeaderboardService,
    student_profile_service: StudentProfileService,
) -> None:
    _use_services(client, leaderboard_service, student_profile_service)
    opted_out = _seed_user(pg_sessionmaker)
    viewer = _seed_user(pg_sessionmaker)
    with pg_sessionmaker.begin() as session:
        session.add(StudentProfile(user_id=opted_out, leaderboard_opt_out=True))
    _award(pg_sessionmaker, opted_out, 999)
    _award(pg_sessionmaker, viewer, 10)
    _auth_as(client, viewer, Role.student)

    resp = client.get("/api/student/leaderboard", params={"scope": "global"})

    assert resp.status_code == 200
    body_text = resp.text
    assert str(opted_out) not in body_text
    ids = {row["userId"] for row in resp.json()["rows"]}
    assert str(opted_out) not in ids
    # Inverse: the un-opted-out viewer is present.
    assert str(viewer) in ids


def test_school_scope_no_school_is_a_successful_unavailable_response(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    leaderboard_service: LeaderboardService,
    student_profile_service: StudentProfileService,
) -> None:
    _use_services(client, leaderboard_service, student_profile_service)
    viewer = _seed_user(pg_sessionmaker)  # no Seat anywhere
    _auth_as(client, viewer, Role.student)

    resp = client.get("/api/student/leaderboard", params={"scope": "school"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "unavailable"
    assert body["unavailableReason"] == "no_school"
    assert body["rows"] == []
    assert body["viewer"] is None

    # Inverse: a seated student on the same scope gets a real ok board.
    school_id = _seed_school(pg_sessionmaker)
    _seed_seat(pg_sessionmaker, school_id, viewer)
    ok = client.get("/api/student/leaderboard", params={"scope": "school"}).json()
    assert ok["status"] == "ok"


def test_viewer_with_zero_xp_gets_null_rank(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    leaderboard_service: LeaderboardService,
    student_profile_service: StudentProfileService,
) -> None:
    _use_services(client, leaderboard_service, student_profile_service)
    viewer = _seed_user(pg_sessionmaker)
    other = _seed_user(pg_sessionmaker)
    _award(pg_sessionmaker, other, 100)
    _auth_as(client, viewer, Role.student)

    resp = client.get("/api/student/leaderboard", params={"scope": "global"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["viewer"]["rank"] is None
    assert body["viewer"]["xp"] == 0
    # Inverse: a viewer who does have XP this week gets a real integer rank.
    _award(pg_sessionmaker, viewer, 5)
    with_xp = client.get("/api/student/leaderboard", params={"scope": "global"}).json()
    assert with_xp["viewer"]["rank"] is not None


# ---------------------------------------------------------------------------
# Opt-out round trip via PATCH /api/me/student-profile.
# ---------------------------------------------------------------------------


def test_opt_out_then_opt_in_restores_identical_rank(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    leaderboard_service: LeaderboardService,
    student_profile_service: StudentProfileService,
) -> None:
    _use_services(client, leaderboard_service, student_profile_service)
    viewer = _seed_user(pg_sessionmaker)
    other = _seed_user(pg_sessionmaker)
    _award(pg_sessionmaker, viewer, 50)
    _award(pg_sessionmaker, other, 30)
    _auth_as(client, viewer, Role.student)

    before = client.get("/api/student/leaderboard", params={"scope": "global"}).json()
    assert before["viewer"]["rank"] == 1
    assert str(viewer) in {r["userId"] for r in before["rows"]}

    opt_out_resp = client.patch("/api/me/student-profile", json={"leaderboardOptOut": True})
    assert opt_out_resp.status_code == 200
    assert opt_out_resp.json()["leaderboardOptOut"] is True

    during = client.get("/api/student/leaderboard", params={"scope": "global"}).json()
    assert str(viewer) not in {r["userId"] for r in during["rows"]}
    assert during["viewerOptedOut"] is True
    assert during["viewer"]["rank"] is None
    # Opting out never touches XP history: the total is unchanged.
    assert during["viewer"]["xp"] == 50

    opt_in_resp = client.patch("/api/me/student-profile", json={"leaderboardOptOut": False})
    assert opt_in_resp.status_code == 200
    assert opt_in_resp.json()["leaderboardOptOut"] is False

    after = client.get("/api/student/leaderboard", params={"scope": "global"}).json()
    assert after["viewerOptedOut"] is False
    assert after["viewer"]["rank"] == before["viewer"]["rank"] == 1
    assert after["viewer"]["xp"] == before["viewer"]["xp"] == 50
    assert str(viewer) in {r["userId"] for r in after["rows"]}


def test_explicit_null_leaderboard_opt_out_is_422(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    leaderboard_service: LeaderboardService,
    student_profile_service: StudentProfileService,
) -> None:
    """Unlike every other field on this DTO, ``leaderboardOptOut`` is not
    nullable on the model (D5.1 §9) -- an explicit ``null`` is rejected
    rather than silently coerced to ``False`` or ignored."""
    _use_services(client, leaderboard_service, student_profile_service)
    student = _seed_user(pg_sessionmaker)
    _auth_as(client, student, Role.student)

    resp = client.patch("/api/me/student-profile", json={"leaderboardOptOut": None})

    assert resp.status_code == 422
    # Inverse: omitting the field entirely is a no-op success, not an error.
    ok = client.patch("/api/me/student-profile", json={"schoolName": "X"})
    assert ok.status_code == 200


# ---------------------------------------------------------------------------
# Router-level error mapping. Each of these is a branch the router documents
# but that no other test in this file reaches.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_scope", ["friends", "class_", "global_", "", "CLASS"])
def test_unknown_scope_is_422(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    leaderboard_service: LeaderboardService,
    student_profile_service: StudentProfileService,
    bad_scope: str,
) -> None:
    """The route accepts only the readable spellings, never the Python enum's
    trailing-underscore member names -- and ``friends`` is P5.4's scope, which
    must fail loudly now rather than silently returning a global board."""
    _use_services(client, leaderboard_service, student_profile_service)
    student = _seed_user(pg_sessionmaker)
    _auth_as(client, student, Role.student)

    resp = client.get("/api/student/leaderboard", params={"scope": bad_scope})

    assert resp.status_code == 422
    # Inverse: the three readable spellings all succeed on the same client.
    for good in ("global", "school"):
        assert client.get("/api/student/leaderboard", params={"scope": good}).status_code == 200


def test_viewer_id_with_no_user_row_is_404(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    leaderboard_service: LeaderboardService,
    student_profile_service: StudentProfileService,
) -> None:
    """A well-formed token for a user that no longer exists (deleted between
    issue and use) is 404, not a 500 and not an empty board."""
    _use_services(client, leaderboard_service, student_profile_service)
    _auth_as(client, uuid.uuid4(), Role.student)  # never seeded

    resp = client.get("/api/student/leaderboard")

    assert resp.status_code == 404
    # Inverse: seeding a user and authing as them succeeds.
    real = _seed_user(pg_sessionmaker)
    _auth_as(client, real, Role.student)
    assert client.get("/api/student/leaderboard").status_code == 200


def test_token_role_student_but_db_row_is_not_a_student_is_403(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    leaderboard_service: LeaderboardService,
    student_profile_service: StudentProfileService,
) -> None:
    """Defence in depth (D5.1 s10). ``require_role`` trusts the token's role
    claim; the service independently re-checks the persisted ``users.role``.
    This is the divergence between the two -- a token claiming ``student`` for
    a user whose DB row says ``teacher`` -- which is exactly the case the
    router's ``LeaderboardIneligibleViewerError`` branch exists for, and which
    ``test_non_student_roles_are_rejected`` cannot reach because it is stopped
    one layer earlier by the role dependency.
    """
    _use_services(client, leaderboard_service, student_profile_service)
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    _auth_as(client, teacher, Role.student)  # token lies about the role

    resp = client.get("/api/student/leaderboard")

    assert resp.status_code == 403
    # Inverse: the identical token shape over a genuine student row is 200.
    student = _seed_user(pg_sessionmaker, Role.student)
    _auth_as(client, student, Role.student)
    assert client.get("/api/student/leaderboard").status_code == 200
