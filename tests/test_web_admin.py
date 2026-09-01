"""Platform-admin schools surface (D7.8) — the account graph's missing first link.

Spec §1.1: tracing the account graph found that **no production code path
creates a ``School`` row or a ``school_admin`` account.** Only
``lemely/db/seed.py`` and test files ever construct either — so
``POST /api/school/teachers/invite``, the only teacher-creation path D1.7
allows, was unreachable in any real deployment. The four routes under test
here (``GET``/``POST /api/admin/schools``, ``PATCH .../{id}``,
``POST .../{id}/admins``) are that missing first link:
``platform_admin -> School -> school_admin -> teacher``.

Four properties get the most attention, one per named test the plan carries
(Task 12):

* **A school_admin administers a school; they do not mint one.** The 403
  boundary on school creation is exactly where getting it wrong would create a
  tenant (``test_create_school_requires_platform_admin``).
* **An account with no membership is indistinguishable, on screen, from a
  broken one** (D4.10's own finding) — so a school_admin account and its
  ``SchoolMembership`` are written together, never one without the other
  (``test_create_school_admin_creates_the_account_and_the_membership``).
* **The temporary password is generated once and returned once** — the same
  credential handling ``invite_teacher`` already established, because no email
  provider exists to deliver it
  (``test_create_school_admin_returns_the_temporary_password_once``).
* **Lowering a quota below seats already assigned is a 409 naming both
  numbers**, never a silent accept that would leave usage over capacity
  (``test_quota_below_assigned_seats_is_refused``).

This module has no per-school ownership to defend (platform_admin holds no
tenant, mirroring ``PlatformAdminService``/D1.6), so unlike
``test_web_school_admin.py`` there is no "wrong caller, right school" case —
the only authorization question this surface has is the role gate itself.
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
from lemely.db.models import School, SchoolMembership, Seat, User
from lemely.db.models.enums import MembershipRole, Role, SeatStatus
from lemely.db.school_provisioning_repo import (
    QuotaBelowAssignedSeatsError,
    SchoolNotFoundError,
    SchoolProvisioningService,
)
from lemely.runtime.config import DatabaseSettings
from lemely.web.app import create_app
from lemely.web.deps import AuthContext, get_auth_context, get_school_provisioning_service

if TYPE_CHECKING:
    from collections.abc import Iterator


# ── Fakes and fixtures ────────────────────────────────────────────────────────


class _FakeSchoolAdminCreator:
    """Inserts a ``school_admin`` ``User`` row directly, standing in for GoTrue.

    Mirrors ``_FakeTeacherCreator``/``_FakeStudentCreator`` in
    ``tests/test_web_school_admin.py``: deliberately pinned to
    :attr:`Role.school_admin` with no role parameter, because the role a
    provisioning path may mint is the security property under test, and the
    fake must not be able to mint anything else either.
    """

    def __init__(self, sm: sessionmaker[Session]) -> None:
        self._sm = sm
        self.created: list[tuple[str, str]] = []

    def create_school_admin(
        self, email: str, password: str, display_name: str | None = None
    ) -> uuid.UUID:
        self.created.append((email, password))
        uid = uuid.uuid4()
        with self._sm.begin() as session:
            session.add(
                User(id=uid, email=email, role=Role.school_admin, display_name=display_name)
            )
        return uid


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
    """A throwaway database, dropped afterwards (mirrors the other admin suites)."""
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


# ── Seeding helpers ───────────────────────────────────────────────────────────


def _user(sm: sessionmaker[Session], role: Role) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role, display_name=role.value))
    return uid


def _school(sm: sessionmaker[Session], *, quota: int, name: str = "Test School") -> uuid.UUID:
    school_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(School(id=school_id, name=name, seat_quota=quota))
    return school_id


def _seat(
    sm: sessionmaker[Session], school_id: uuid.UUID, status: SeatStatus = SeatStatus.assigned
) -> None:
    with sm.begin() as session:
        session.add(Seat(school_id=school_id, status=status))


def _admin_membership(sm: sessionmaker[Session], school_id: uuid.UUID, user_id: uuid.UUID) -> None:
    with sm.begin() as session:
        session.add(
            SchoolMembership(
                school_id=school_id, user_id=user_id, membership_role=MembershipRole.school_admin
            )
        )


def _service(
    sm: sessionmaker[Session],
) -> tuple[SchoolProvisioningService, _FakeSchoolAdminCreator]:
    creator = _FakeSchoolAdminCreator(sm)
    return SchoolProvisioningService(sm, creator), creator


def _client(
    sm: sessionmaker[Session],
    *,
    role: Role = Role.platform_admin,
    user_id: uuid.UUID | None = None,
) -> Iterator[TestClient]:
    """A ``TestClient`` wired to a fresh service, authenticated as ``role``.

    ``user_id`` defaults to a random, unmirrored id — fine for every route
    that only *checks* the caller's role, since ``require_role`` rejects an
    unpermitted caller before any handler runs. ``create_school`` is the one
    route that *writes* the caller's id (``schools.created_by``, FK to
    ``users``), so a test asserting on that column must pass a real seeded id.
    """
    service, _ = _service(sm)
    app = create_app()
    app.dependency_overrides[get_school_provisioning_service] = lambda: service
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id=str(user_id or uuid.uuid4()), role=role.value
    )
    client = TestClient(app)
    try:
        yield client
    finally:
        app.dependency_overrides.clear()


# ── The four decisions (exact names the plan carries) ─────────────────────────


def test_create_school_requires_platform_admin(pg_sessionmaker: sessionmaker[Session]) -> None:
    """A school_admin administers a school; they do not mint one (D7.8).

    This is the boundary where getting it wrong creates a tenant, so all three
    non-``platform_admin`` roles are asserted explicitly rather than sampled —
    losing ``school_admin`` from this list is the one regression that matters
    most here, since it is the role most plausibly (wrongly) granted this.
    """
    for role in (Role.student, Role.teacher, Role.school_admin):
        for client in _client(pg_sessionmaker, role=role):
            res = client.post("/api/admin/schools", json={"name": "New School", "seatQuota": 10})
        assert res.status_code == 403, f"{role.value} should not create a school"


def test_create_school_admin_creates_the_account_and_the_membership(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """Both halves, in one call — an account with no membership administers
    nothing and meets an empty console, indistinguishable on screen from a
    broken one (D4.10's own finding)."""
    school_id = _school(pg_sessionmaker, quota=5)
    service, creator = _service(pg_sessionmaker)

    result = service.create_school_admin(
        school_id, "admin@newschool.example", "pw", display_name="New Admin"
    )

    assert creator.created == [("admin@newschool.example", "pw")]
    with pg_sessionmaker() as session:
        user = session.get(User, result.user_id)
        assert user is not None
        assert user.role is Role.school_admin
        assert user.display_name == "New Admin"
        membership = session.scalars(
            sa.select(SchoolMembership).where(SchoolMembership.user_id == result.user_id)
        ).one()
        assert membership.school_id == school_id
        assert membership.membership_role is MembershipRole.school_admin
        assert membership.id == result.membership_id


def test_create_school_admin_over_http_also_writes_both_rows(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The HTTP round-trip of the same guarantee, through the router's DTOs."""
    school_id = _school(pg_sessionmaker, quota=5)

    for client in _client(pg_sessionmaker):
        res = client.post(
            f"/api/admin/schools/{school_id}/admins",
            json={"email": "admin@newschool.example", "displayName": "New Admin"},
        )

    assert res.status_code == 200
    body = res.json()
    with pg_sessionmaker() as session:
        user = session.get(User, uuid.UUID(body["userId"]))
        assert user is not None and user.role is Role.school_admin
        membership = session.scalars(
            sa.select(SchoolMembership).where(SchoolMembership.user_id == user.id)
        ).one()
        assert membership.school_id == school_id


def test_create_school_admin_returns_the_temporary_password_once(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """Same credential handling as ``invite_teacher``: no email provider
    delivers, so a password is generated once and returned once for
    out-of-band conveyance."""
    school_id = _school(pg_sessionmaker, quota=5)

    for client in _client(pg_sessionmaker):
        generated_res = client.post(
            f"/api/admin/schools/{school_id}/admins",
            json={"email": "admin@newschool.example", "displayName": "New Admin"},
        )

    assert generated_res.status_code == 200
    generated_body = generated_res.json()
    assert generated_body["temporaryPassword"]
    assert len(generated_body["temporaryPassword"]) > 20

    # A caller-supplied password is conveyed, not regenerated or echoed back —
    # the response must not hand a real credential over HTTP a second time.
    for client in _client(pg_sessionmaker):
        chosen_res = client.post(
            f"/api/admin/schools/{school_id}/admins",
            json={"email": "admin2@newschool.example", "password": "a-chosen-password"},
        )
    assert chosen_res.json()["temporaryPassword"] is None


def test_create_school_admin_unknown_school_is_404(pg_sessionmaker: sessionmaker[Session]) -> None:
    service, _ = _service(pg_sessionmaker)
    with pytest.raises(SchoolNotFoundError):
        service.create_school_admin(uuid.uuid4(), "nobody@example.com", "pw")


def test_quota_below_assigned_seats_is_refused(pg_sessionmaker: sessionmaker[Session]) -> None:
    """Lowering a quota under the seats already assigned would make usage
    exceed capacity - a 409 naming both numbers, never a silent accept."""
    school_id = _school(pg_sessionmaker, quota=5)
    _seat(pg_sessionmaker, school_id)
    _seat(pg_sessionmaker, school_id)
    _seat(pg_sessionmaker, school_id, status=SeatStatus.revoked)  # freed; must not count

    for client in _client(pg_sessionmaker):
        res = client.patch(f"/api/admin/schools/{school_id}", json={"seatQuota": 1})

    assert res.status_code == 409
    detail = res.json()["detail"]
    assert "1" in detail
    assert "2" in detail
    # The quota was refused, not silently clamped or partially applied.
    with pg_sessionmaker() as session:
        assert session.get(School, school_id).seat_quota == 5


def test_update_school_service_raises_naming_both_numbers(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The service-level half of the same guarantee, independent of the router's
    error mapping."""
    school_id = _school(pg_sessionmaker, quota=5)
    _seat(pg_sessionmaker, school_id)
    _seat(pg_sessionmaker, school_id)
    service, _ = _service(pg_sessionmaker)

    with pytest.raises(QuotaBelowAssignedSeatsError) as excinfo:
        service.update_school(school_id, seat_quota=1)

    assert excinfo.value.requested_quota == 1
    assert excinfo.value.seats_assigned == 2


def test_quota_equal_to_assigned_seats_is_accepted(pg_sessionmaker: sessionmaker[Session]) -> None:
    """The refusal is strictly "below", not "at" — a quota tightened to fit
    exactly what is in use is a legitimate edit, not a violation."""
    school_id = _school(pg_sessionmaker, quota=5)
    _seat(pg_sessionmaker, school_id)
    _seat(pg_sessionmaker, school_id)
    service, _ = _service(pg_sessionmaker)

    summary = service.update_school(school_id, seat_quota=2)

    assert summary.seat_quota == 2
    assert summary.seats_available == 0


# ── Supporting coverage: list / create / update / not-found ───────────────────


def test_list_schools_reports_quota_seat_usage_and_admins(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    school_id = _school(pg_sessionmaker, quota=10, name="Al-Nasr Language School")
    _seat(pg_sessionmaker, school_id)
    _seat(pg_sessionmaker, school_id, status=SeatStatus.revoked)  # not assigned; excluded
    admin_id = _user(pg_sessionmaker, Role.school_admin)
    _admin_membership(pg_sessionmaker, school_id, admin_id)

    service, _ = _service(pg_sessionmaker)
    schools = service.list_schools()

    assert len(schools) == 1
    row = schools[0]
    assert row.school_id == school_id
    assert row.name == "Al-Nasr Language School"
    assert row.seat_quota == 10
    assert row.seats_assigned == 1
    assert row.seats_available == 9
    assert [a.user_id for a in row.admins] == [admin_id]


def test_list_schools_over_http_requires_platform_admin_and_serves_camel_case(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _school(pg_sessionmaker, quota=3, name="Solo School")

    for client in _client(pg_sessionmaker, role=Role.teacher):
        forbidden = client.get("/api/admin/schools")
    for client in _client(pg_sessionmaker):
        allowed = client.get("/api/admin/schools")

    assert forbidden.status_code == 403
    assert allowed.status_code == 200
    body = allowed.json()["schools"][0]
    assert body["name"] == "Solo School"
    assert body["seatQuota"] == 3
    assert body["seatsAssigned"] == 0
    assert body["seatsAvailable"] == 3
    assert body["admins"] == []


def test_create_school_sets_quota_and_records_the_creator(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    creator_id = _user(pg_sessionmaker, Role.platform_admin)
    service, _ = _service(pg_sessionmaker)

    summary = service.create_school("Brand New School", 25, created_by=creator_id)

    assert summary.name == "Brand New School"
    assert summary.seat_quota == 25
    assert summary.seats_assigned == 0
    assert summary.seats_available == 25
    assert summary.admins == []
    with pg_sessionmaker() as session:
        row = session.get(School, summary.school_id)
        assert row is not None
        assert row.created_by == creator_id


def test_create_school_over_http_uses_the_caller_as_creator(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    caller_id = _user(pg_sessionmaker, Role.platform_admin)

    for client in _client(pg_sessionmaker, user_id=caller_id):
        res = client.post("/api/admin/schools", json={"name": "HTTP School", "seatQuota": 4})

    assert res.status_code == 200
    body = res.json()
    assert body["name"] == "HTTP School"
    assert body["seatQuota"] == 4
    with pg_sessionmaker() as session:
        row = session.get(School, uuid.UUID(body["schoolId"]))
        assert row is not None
        assert row.created_by == caller_id


def test_update_school_renames_without_changing_quota(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    school_id = _school(pg_sessionmaker, quota=8, name="Old Name")
    service, _ = _service(pg_sessionmaker)

    summary = service.update_school(school_id, name="New Name")

    assert summary.name == "New Name"
    assert summary.seat_quota == 8


def test_update_unknown_school_raises_not_found(pg_sessionmaker: sessionmaker[Session]) -> None:
    service, _ = _service(pg_sessionmaker)
    with pytest.raises(SchoolNotFoundError):
        service.update_school(uuid.uuid4(), name="Nope")


def test_update_unknown_school_over_http_is_404(pg_sessionmaker: sessionmaker[Session]) -> None:
    for client in _client(pg_sessionmaker):
        res = client.patch(f"/api/admin/schools/{uuid.uuid4()}", json={"name": "Nope"})
    assert res.status_code == 404


def test_all_school_routes_require_platform_admin(pg_sessionmaker: sessionmaker[Session]) -> None:
    """A sweep of the remaining three routes: the router-level gate must cover
    every one of them, not just the one named test above exercises directly."""
    school_id = _school(pg_sessionmaker, quota=5)

    for client in _client(pg_sessionmaker, role=Role.teacher):
        listing = client.get("/api/admin/schools")
        update = client.patch(f"/api/admin/schools/{school_id}", json={"name": "Hijack"})
        create_admin = client.post(
            f"/api/admin/schools/{school_id}/admins", json={"email": "x@example.com"}
        )

    assert listing.status_code == 403
    assert update.status_code == 403
    assert create_admin.status_code == 403
