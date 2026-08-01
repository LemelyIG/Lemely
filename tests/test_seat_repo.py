"""Postgres integration tests for the seat-allocation service (D1.10).

These exercise :class:`~lemely.db.seat_repo.SeatService` against a throwaway
database and skip cleanly when no local server is reachable (mirrors
``test_history_repo_parity.py``). They prove the four guarantees the Phase-1 seat
model requires:

* **Quota** — a school never exceeds its ``seat_quota``; the boundary invite is a
  :class:`SeatQuotaExceededError`.
* **Ownership** — a caller may only touch a school (or a seat's school) they hold a
  ``school_admin`` membership for; anyone else gets a :class:`SeatOwnershipError`,
  never data or a mutation.
* **Revocation** — revoking frees a slot against the quota, leaves the student
  account intact, and is idempotent.
* **Coexistence** — a seated student may *also* hold a personal subscription (the
  two are independent; no exclusivity is enforced).

Account creation is a :class:`StudentAccountCreator` seam so the seat/quota/
ownership logic is testable without the live GoTrue stack; the fake inserts a
``student`` ``User`` row directly, exactly as the real creator's mirror would.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.db.base import Base
from lemely.db.models import School, SchoolMembership, Seat, Subscription, User
from lemely.db.models.billing import PlanTier
from lemely.db.models.enums import (
    MembershipRole,
    Role,
    SeatStatus,
    SubscriptionStatus,
)
from lemely.db.seat_repo import (
    SeatNotFoundError,
    SeatOwnershipError,
    SeatQuotaExceededError,
    SeatService,
)
from lemely.runtime.config import DatabaseSettings

if TYPE_CHECKING:
    from collections.abc import Iterator


class _FakeAccountCreator:
    """Inserts a ``student`` ``User`` row directly, standing in for GoTrue signup.

    Records every ``(email, password)`` it was asked to create so tests can assert
    an ownership/quota rejection never reached account creation.
    """

    def __init__(self, sm: sessionmaker[Session]) -> None:
        self._sm = sm
        self.created: list[tuple[str, str]] = []

    def create_student(
        self,
        email: str,
        password: str,
        display_name: str | None = None,
    ) -> uuid.UUID:
        self.created.append((email, password))
        uid = uuid.uuid4()
        with self._sm.begin() as session:
            session.add(User(id=uid, email=email, role=Role.student, display_name=display_name))
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


def _seed_user(sm: sessionmaker[Session], role: Role = Role.school_admin) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role))
    return uid


def _seed_school(sm: sessionmaker[Session], *, quota: int, admin_id: uuid.UUID) -> uuid.UUID:
    """Create a school with ``quota`` seats and grant ``admin_id`` school_admin over it."""
    school_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(School(id=school_id, name="Test School", seat_quota=quota))
        session.add(
            SchoolMembership(
                school_id=school_id,
                user_id=admin_id,
                membership_role=MembershipRole.school_admin,
            )
        )
    return school_id


def _service(sm: sessionmaker[Session]) -> tuple[SeatService, _FakeAccountCreator]:
    creator = _FakeAccountCreator(sm)
    return SeatService(sm, creator), creator


# ── Invite + quota ────────────────────────────────────────────────────────────


def test_invite_allocates_seat_and_decrements_availability(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    admin = _seed_user(pg_sessionmaker)
    school = _seed_school(pg_sessionmaker, quota=2, admin_id=admin)
    service, _ = _service(pg_sessionmaker)

    result = service.invite_student(admin, school, "a@student.local", "pw")

    usage = service.seat_usage(admin, school)
    assert usage.quota == 2
    assert usage.used == 1
    assert usage.available == 1
    assert usage.seats[0].assigned_user_id == result.user_id
    assert usage.seats[0].assigned_email == "a@student.local"
    assert usage.seats[0].status is SeatStatus.assigned


def test_invite_beyond_quota_is_rejected_without_creating_account(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    admin = _seed_user(pg_sessionmaker)
    school = _seed_school(pg_sessionmaker, quota=1, admin_id=admin)
    service, creator = _service(pg_sessionmaker)

    service.invite_student(admin, school, "first@student.local", "pw")
    with pytest.raises(SeatQuotaExceededError):
        service.invite_student(admin, school, "second@student.local", "pw")

    # The rejected invite must not have created an orphaned account.
    assert creator.created == [("first@student.local", "pw")]
    assert service.seat_usage(admin, school).used == 1


def test_zero_quota_school_rejects_every_invite(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    admin = _seed_user(pg_sessionmaker)
    school = _seed_school(pg_sessionmaker, quota=0, admin_id=admin)
    service, creator = _service(pg_sessionmaker)

    with pytest.raises(SeatQuotaExceededError):
        service.invite_student(admin, school, "x@student.local", "pw")
    assert creator.created == []


# ── Ownership ─────────────────────────────────────────────────────────────────


def test_invite_by_non_admin_is_ownership_error(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    owner = _seed_user(pg_sessionmaker)
    stranger = _seed_user(pg_sessionmaker)  # a school_admin, but of no school here
    school = _seed_school(pg_sessionmaker, quota=5, admin_id=owner)
    service, creator = _service(pg_sessionmaker)

    with pytest.raises(SeatOwnershipError):
        service.invite_student(stranger, school, "x@student.local", "pw")
    assert creator.created == []
    assert service.seat_usage(owner, school).used == 0


def test_seat_usage_of_unowned_school_is_ownership_error(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    owner = _seed_user(pg_sessionmaker)
    stranger = _seed_user(pg_sessionmaker)
    school = _seed_school(pg_sessionmaker, quota=5, admin_id=owner)
    service, _ = _service(pg_sessionmaker)

    with pytest.raises(SeatOwnershipError):
        service.seat_usage(stranger, school)


def test_list_admin_schools_returns_only_administered(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    admin = _seed_user(pg_sessionmaker)
    other_admin = _seed_user(pg_sessionmaker)
    mine = _seed_school(pg_sessionmaker, quota=3, admin_id=admin)
    _seed_school(pg_sessionmaker, quota=3, admin_id=other_admin)  # not mine
    service, _ = _service(pg_sessionmaker)

    usages = service.list_admin_schools(admin)
    assert [u.school_id for u in usages] == [mine]
    assert service.list_admin_schools(_seed_user(pg_sessionmaker)) == []


# ── Revocation ────────────────────────────────────────────────────────────────


def test_revoke_frees_a_slot_and_keeps_the_account(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    admin = _seed_user(pg_sessionmaker)
    school = _seed_school(pg_sessionmaker, quota=1, admin_id=admin)
    service, _ = _service(pg_sessionmaker)

    result = service.invite_student(admin, school, "a@student.local", "pw")
    service.revoke_seat(admin, result.seat_id)

    usage = service.seat_usage(admin, school)
    assert usage.used == 0
    assert usage.available == 1
    # The freed slot can be filled again.
    service.invite_student(admin, school, "b@student.local", "pw")
    assert service.seat_usage(admin, school).used == 1
    # The revoked student's account still exists.
    with pg_sessionmaker() as session:
        assert session.get(User, result.user_id) is not None


def test_revoke_is_idempotent(pg_sessionmaker: sessionmaker[Session]) -> None:
    admin = _seed_user(pg_sessionmaker)
    school = _seed_school(pg_sessionmaker, quota=1, admin_id=admin)
    service, _ = _service(pg_sessionmaker)

    result = service.invite_student(admin, school, "a@student.local", "pw")
    service.revoke_seat(admin, result.seat_id)
    service.revoke_seat(admin, result.seat_id)  # no error, still revoked
    with pg_sessionmaker() as session:
        seat = session.get(Seat, result.seat_id)
        assert seat is not None
        assert seat.status is SeatStatus.revoked


def test_revoke_unknown_seat_is_not_found(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    admin = _seed_user(pg_sessionmaker)
    service, _ = _service(pg_sessionmaker)
    with pytest.raises(SeatNotFoundError):
        service.revoke_seat(admin, uuid.uuid4())


def test_revoke_seat_of_unowned_school_is_ownership_error(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    owner = _seed_user(pg_sessionmaker)
    stranger = _seed_user(pg_sessionmaker)
    school = _seed_school(pg_sessionmaker, quota=1, admin_id=owner)
    service, _ = _service(pg_sessionmaker)
    result = service.invite_student(owner, school, "a@student.local", "pw")

    with pytest.raises(SeatOwnershipError):
        service.revoke_seat(stranger, result.seat_id)
    # Still assigned — the unowned revoke was a no-op.
    assert service.seat_usage(owner, school).seats[0].status is SeatStatus.assigned


# ── Coexistence with a personal subscription ──────────────────────────────────


def test_seated_student_may_also_hold_a_personal_subscription(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    admin = _seed_user(pg_sessionmaker)
    school = _seed_school(pg_sessionmaker, quota=1, admin_id=admin)
    service, _ = _service(pg_sessionmaker)
    result = service.invite_student(admin, school, "dual@student.local", "pw")

    # The same student takes out a personal subscription — no exclusivity.
    with pg_sessionmaker.begin() as session:
        tier = PlanTier(code="student_monthly", name="Student Monthly")
        session.add(tier)
        session.flush()
        session.add(
            Subscription(
                user_id=result.user_id,
                plan_tier_id=tier.id,
                status=SubscriptionStatus.active,
                is_manually_activated=True,
            )
        )

    with pg_sessionmaker() as session:
        sub = session.scalars(
            sa.select(Subscription).where(Subscription.user_id == result.user_id)
        ).one()
        seat = session.scalars(sa.select(Seat).where(Seat.assigned_user_id == result.user_id)).one()
    assert sub.status is SubscriptionStatus.active
    assert seat.status is SeatStatus.assigned


# ── Input validation ──────────────────────────────────────────────────────────


def test_non_uuid_identifiers_rejected(pg_sessionmaker: sessionmaker[Session]) -> None:
    service, _ = _service(pg_sessionmaker)
    with pytest.raises(ValueError, match="must be a UUID"):
        service.seat_usage("not-a-uuid", uuid.uuid4())
    with pytest.raises(ValueError, match="must be a UUID"):
        service.revoke_seat(uuid.uuid4(), "not-a-uuid")
