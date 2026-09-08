"""Postgres integration tests for the invite service (D7.3, spec §1.2).

Exercises :class:`~lemely.db.invite_repo.InviteService` against a throwaway
database and skips cleanly when no local server is reachable (mirrors
``test_seat_repo.py``/``test_class_repo.py``). Proves the guarantees Task 11
requires:

* **Dual resolution** — :meth:`~InviteService.preview` and
  :meth:`~InviteService.redeem` accept either an ``invites.code`` or a bare
  ``classes.join_code``; an unknown code is a clean
  :class:`~lemely.db.invite_repo.InviteNotFoundError`.
* **Disclosure** — a preview is public and pre-account, so it names only the
  school/class/teacher and leaks no student, id, roster, or count.
* **Reservation** — a seat invite consumes its seat at *mint* time, so
  minting past a school's quota is refused outright
  (:class:`~lemely.db.invite_repo.InviteQuotaExceededError`), and the seat
  it reserved is exactly what :meth:`~InviteService.redeem` later assigns.
* **Single-use** — redeeming your own invite twice is a no-op; redeeming an
  invite someone else already claimed is refused
  (:class:`~lemely.db.invite_repo.InviteAlreadyRedeemedError`), the property
  that matters most in this file.
* **Ownership** — both mint methods re-verify the caller's own standing
  (school_admin membership; teacher ownership or administering school_admin)
  rather than trusting the router.

Account creation never appears here: unlike :class:`~lemely.db.seat_repo.SeatService`,
:meth:`~InviteService.redeem` always attaches an *existing* account (the
route is authenticated) — there is no GoTrue seam to fake.
"""

from __future__ import annotations

import dataclasses
import threading
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.db.base import Base
from lemely.db.class_repo import ClassService
from lemely.db.invite_repo import (
    PARENT_INVITE_TTL,
    InviteAlreadyRedeemedError,
    InviteNotFoundError,
    InviteOwnershipError,
    InviteQuotaExceededError,
    InviteRoleMismatchError,
    InviteService,
)
from lemely.db.models import (
    ClassEnrollment,
    Invite,
    ParentChildLink,
    School,
    SchoolClass,
    SchoolMembership,
    Seat,
    User,
)
from lemely.db.models.enums import InviteRole, MembershipRole, Role, SeatStatus
from lemely.db.parent_repo import ParentLinkService
from lemely.runtime.config import DatabaseSettings

if TYPE_CHECKING:
    from collections.abc import Iterator


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


# ── Seed helpers ────────────────────────────────────────────────────────────


def _seed_user(
    sm: sessionmaker[Session], role: Role = Role.student, display_name: str | None = None
) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role, display_name=display_name))
    return uid


def _seed_school(
    sm: sessionmaker[Session], *, quota: int, admin_id: uuid.UUID, name: str = "Test School"
) -> uuid.UUID:
    school_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(School(id=school_id, name=name, seat_quota=quota))
        session.add(
            SchoolMembership(
                school_id=school_id, user_id=admin_id, membership_role=MembershipRole.school_admin
            )
        )
    return school_id


def _seed_class(
    sm: sessionmaker[Session],
    *,
    teacher_id: uuid.UUID,
    school_id: uuid.UUID | None = None,
    name: str = "Physics 10A",
    join_code: str | None = None,
) -> uuid.UUID:
    class_id = uuid.uuid4()
    code = join_code or f"JOIN{uuid.uuid4().hex[:6].upper()}"
    with sm.begin() as session:
        session.add(
            SchoolClass(
                id=class_id, teacher_id=teacher_id, school_id=school_id, name=name, join_code=code
            )
        )
    return class_id


def _service(sm: sessionmaker[Session]) -> InviteService:
    return InviteService(sm, ClassService(sm), ParentLinkService(sm))


# ── preview: dual resolution ────────────────────────────────────────────────


def test_preview_resolves_a_class_join_code(pg_sessionmaker: sessionmaker[Session]) -> None:
    """G-08 must accept the code teachers already hand out. ``classes.join_code``
    predates this table (D3.1) and thousands of nothing depend on it, but the
    screen that reads a code cannot ask the holder which kind they have.
    """
    teacher = _seed_user(pg_sessionmaker, Role.teacher, display_name="Ms Iman")
    admin = _seed_user(pg_sessionmaker, Role.school_admin)
    school = _seed_school(pg_sessionmaker, quota=5, admin_id=admin)
    _seed_class(pg_sessionmaker, teacher_id=teacher, school_id=school, join_code="PHYS123")
    service = _service(pg_sessionmaker)

    preview = service.preview("PHYS123")

    assert preview.role is InviteRole.student
    assert preview.class_name == "Physics 10A"
    assert preview.school_name == "Test School"
    assert preview.teacher_name == "Ms Iman"


def test_preview_resolves_an_invite_code(pg_sessionmaker: sessionmaker[Session]) -> None:
    admin = _seed_user(pg_sessionmaker, Role.school_admin)
    school = _seed_school(pg_sessionmaker, quota=5, admin_id=admin)
    service = _service(pg_sessionmaker)
    invite = service.mint_seat_invite(admin, school)

    preview = service.preview(invite.code)

    assert preview.role is InviteRole.student
    assert preview.school_name == "Test School"
    assert preview.class_name is None
    assert preview.teacher_name is None


def test_preview_of_an_unknown_code_raises_invite_not_found(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    service = _service(pg_sessionmaker)
    with pytest.raises(InviteNotFoundError):
        service.preview("NOSUCHCODE")


def test_preview_of_an_expired_invite_raises_invite_not_found(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """Neither mint method ever sets ``expires_at`` today, but the column
    exists and a row could carry one by other means; an expired invite must
    read as gone, not as "found but stale" (which would leak that the code
    once existed to an anonymous, pre-account caller)."""
    admin = _seed_user(pg_sessionmaker, Role.school_admin)
    school = _seed_school(pg_sessionmaker, quota=5, admin_id=admin)
    with pg_sessionmaker.begin() as session:
        session.add(
            Invite(
                code="EXPIREDCODE",
                role=InviteRole.student,
                school_id=school,
                created_by=admin,
                expires_at=datetime.now(UTC) - timedelta(hours=1),
            )
        )
    service = _service(pg_sessionmaker)

    with pytest.raises(InviteNotFoundError):
        service.preview("EXPIREDCODE")


def test_preview_does_not_leak_member_identities(pg_sessionmaker: sessionmaker[Session]) -> None:
    """A preview is public and pre-account. It may name the school, the class
    and the teacher - all of which the code's holder was told by whoever gave
    it to them - and must expose no student, no roster count and no id.
    """
    teacher = _seed_user(pg_sessionmaker, Role.teacher, display_name="Mr Sabry")
    admin = _seed_user(pg_sessionmaker, Role.school_admin)
    school = _seed_school(pg_sessionmaker, quota=5, admin_id=admin)
    class_id = _seed_class(pg_sessionmaker, teacher_id=teacher, school_id=school, name="Chem 9B")
    student = _seed_user(pg_sessionmaker, Role.student, display_name="Secret Student")
    with pg_sessionmaker.begin() as session:
        session.add(ClassEnrollment(class_id=class_id, student_id=student))
        session.add(Seat(school_id=school, assigned_user_id=student, status=SeatStatus.assigned))
    service = _service(pg_sessionmaker)
    invite = service.mint_class_invite(teacher, Role.teacher, class_id)

    preview = service.preview(invite.code)

    dumped = dataclasses.asdict(preview)
    assert set(dumped) == {"role", "school_name", "class_name", "teacher_name", "child_name"}
    rendered = repr(dumped)
    assert "Secret Student" not in rendered
    assert str(student) not in rendered
    assert str(class_id) not in rendered
    assert str(school) not in rendered
    assert str(invite.id) not in rendered


# ── redeem: assignment, idempotency, single-use ─────────────────────────────


def test_redeem_assigns_the_seat_and_marks_the_invite_used(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    admin = _seed_user(pg_sessionmaker, Role.school_admin)
    school = _seed_school(pg_sessionmaker, quota=2, admin_id=admin)
    student = _seed_user(pg_sessionmaker, Role.student)
    service = _service(pg_sessionmaker)
    invite = service.mint_seat_invite(admin, school)
    invite_id, seat_id, code = invite.id, invite.seat_id, invite.code
    assert seat_id is not None

    result = service.redeem(student, code)

    assert result.role is InviteRole.student
    assert result.school_id == school
    assert result.class_id is None
    with pg_sessionmaker() as session:
        seat = session.get(Seat, seat_id)
        assert seat is not None
        assert seat.assigned_user_id == student
        assert seat.status is SeatStatus.assigned
        redeemed = session.get(Invite, invite_id)
        assert redeemed is not None
        assert redeemed.redeemed_by == student
        assert redeemed.redeemed_at is not None


def test_redeem_is_idempotent(pg_sessionmaker: sessionmaker[Session]) -> None:
    """Re-redeeming your own invite is a no-op, matching ``join_by_code``."""
    admin = _seed_user(pg_sessionmaker, Role.school_admin)
    school = _seed_school(pg_sessionmaker, quota=1, admin_id=admin)
    student = _seed_user(pg_sessionmaker, Role.student)
    service = _service(pg_sessionmaker)
    invite = service.mint_seat_invite(admin, school)
    code = invite.code

    first = service.redeem(student, code)
    second = service.redeem(student, code)

    assert first == second
    with pg_sessionmaker() as session:
        seats = list(session.scalars(sa.select(Seat).where(Seat.school_id == school)))
        assert len(seats) == 1
        assert seats[0].assigned_user_id == student
        assert seats[0].status is SeatStatus.assigned


def test_redeem_an_already_redeemed_invite_by_another_user_is_refused(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The one that matters most: a code shared onward must not consume a
    second seat or attach a stranger to a school.
    """
    admin = _seed_user(pg_sessionmaker, Role.school_admin)
    school = _seed_school(pg_sessionmaker, quota=1, admin_id=admin)
    first_student = _seed_user(pg_sessionmaker, Role.student)
    second_student = _seed_user(pg_sessionmaker, Role.student)
    service = _service(pg_sessionmaker)
    invite = service.mint_seat_invite(admin, school)
    code = invite.code
    service.redeem(first_student, code)

    with pytest.raises(InviteAlreadyRedeemedError):
        service.redeem(second_student, code)

    with pg_sessionmaker() as session:
        seats = list(session.scalars(sa.select(Seat).where(Seat.school_id == school)))
        assert len(seats) == 1, "a second user must not consume a second seat"
        assert seats[0].assigned_user_id == first_student
        assert seats[0].status is SeatStatus.assigned
        redeemed = session.scalars(sa.select(Invite).where(Invite.code == code)).one()
        assert redeemed.redeemed_by == first_student


def test_redeem_of_an_unknown_code_raises_invite_not_found(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _seed_user(pg_sessionmaker, Role.student)
    service = _service(pg_sessionmaker)
    with pytest.raises(InviteNotFoundError):
        service.redeem(student, "NOSUCHCODE")


def test_redeem_resolves_a_bare_class_join_code(pg_sessionmaker: sessionmaker[Session]) -> None:
    """Closes spec §1.2: a student holding the join code teachers already
    hand out (never an ``invites`` row) can redeem it from ``/join`` too."""
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    class_id = _seed_class(pg_sessionmaker, teacher_id=teacher, join_code="BAREJOIN")
    student = _seed_user(pg_sessionmaker, Role.student)
    service = _service(pg_sessionmaker)

    result = service.redeem(student, "BAREJOIN")

    assert result.role is InviteRole.student
    assert result.class_id == class_id
    with pg_sessionmaker() as session:
        enrolled = session.scalars(
            sa.select(ClassEnrollment).where(
                ClassEnrollment.class_id == class_id, ClassEnrollment.student_id == student
            )
        ).first()
        assert enrolled is not None
    # A bare join code stays unlimited-use, unlike an invites row - a second
    # student redeeming the SAME code is not a conflict.
    other_student = _seed_user(pg_sessionmaker, Role.student)
    service.redeem(other_student, "BAREJOIN")


# ── mint_seat_invite: reservation, ownership, quota ─────────────────────────


def test_mint_seat_invite_reserves_an_available_seat(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    admin = _seed_user(pg_sessionmaker, Role.school_admin)
    school = _seed_school(pg_sessionmaker, quota=2, admin_id=admin)
    service = _service(pg_sessionmaker)

    invite = service.mint_seat_invite(admin, school)

    assert invite.school_id == school
    assert invite.class_id is None
    assert invite.seat_id is not None
    assert invite.role is InviteRole.student
    assert invite.redeemed_by is None
    with pg_sessionmaker() as session:
        seat = session.get(Seat, invite.seat_id)
        assert seat is not None
        assert seat.status is SeatStatus.available
        assert seat.assigned_user_id is None


def test_mint_seat_invite_by_non_admin_is_ownership_error(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    owner = _seed_user(pg_sessionmaker, Role.school_admin)
    stranger = _seed_user(pg_sessionmaker, Role.school_admin)
    school = _seed_school(pg_sessionmaker, quota=5, admin_id=owner)
    service = _service(pg_sessionmaker)

    with pytest.raises(InviteOwnershipError):
        service.mint_seat_invite(stranger, school)
    with pg_sessionmaker() as session:
        assert session.scalars(sa.select(Seat).where(Seat.school_id == school)).first() is None


def test_mint_seat_invite_at_quota_raises(pg_sessionmaker: sessionmaker[Session]) -> None:
    """A code that cannot be redeemed must not be mintable - reserving the
    seat at mint time is what makes the preview's promise true.
    """
    admin = _seed_user(pg_sessionmaker, Role.school_admin)
    school = _seed_school(pg_sessionmaker, quota=1, admin_id=admin)
    service = _service(pg_sessionmaker)
    service.mint_seat_invite(admin, school)

    with pytest.raises(InviteQuotaExceededError):
        service.mint_seat_invite(admin, school)

    with pg_sessionmaker() as session:
        seats = list(session.scalars(sa.select(Seat).where(Seat.school_id == school)))
        assert len(seats) == 1, "the failed mint must not have reserved a second seat"
        invites = list(session.scalars(sa.select(Invite).where(Invite.school_id == school)))
        assert len(invites) == 1


# ── mint_class_invite: ownership (teacher and administering school_admin) ──


def test_mint_class_invite_by_owning_teacher_succeeds(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    class_id = _seed_class(pg_sessionmaker, teacher_id=teacher)
    service = _service(pg_sessionmaker)

    invite = service.mint_class_invite(teacher, Role.teacher, class_id)

    assert invite.class_id == class_id
    assert invite.school_id is None
    assert invite.role is InviteRole.student
    assert invite.created_by == teacher


def test_mint_class_invite_by_administering_school_admin_succeeds(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    admin = _seed_user(pg_sessionmaker, Role.school_admin)
    school = _seed_school(pg_sessionmaker, quota=5, admin_id=admin)
    class_id = _seed_class(pg_sessionmaker, teacher_id=teacher, school_id=school)
    service = _service(pg_sessionmaker)

    invite = service.mint_class_invite(admin, Role.school_admin, class_id)

    assert invite.class_id == class_id
    assert invite.created_by == admin


def test_mint_class_invite_by_non_owner_is_ownership_error(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    stranger = _seed_user(pg_sessionmaker, Role.teacher)
    class_id = _seed_class(pg_sessionmaker, teacher_id=teacher)
    service = _service(pg_sessionmaker)

    with pytest.raises(InviteOwnershipError):
        service.mint_class_invite(stranger, Role.teacher, class_id)


def test_mint_class_invite_unknown_class_is_not_found(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    service = _service(pg_sessionmaker)

    with pytest.raises(InviteNotFoundError):
        service.mint_class_invite(teacher, Role.teacher, uuid.uuid4())


# ── redeem: a class invite (via ``invites.code``, not a bare join code) ────


def test_redeem_of_a_minted_class_invite_enrols_via_join_by_code(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """Distinct from ``test_redeem_resolves_a_bare_class_join_code``: this
    code is an ``invites`` row (single-use), not the class's own permanent
    join code, and redemption must still go through ``join_by_code`` rather
    than a hand-rolled ``ClassEnrollment`` insert (binding rule 3)."""
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    admin = _seed_user(pg_sessionmaker, Role.school_admin)
    school = _seed_school(pg_sessionmaker, quota=5, admin_id=admin)
    class_id = _seed_class(pg_sessionmaker, teacher_id=teacher, school_id=school, name="Bio 11C")
    student = _seed_user(pg_sessionmaker, Role.student)
    service = _service(pg_sessionmaker)
    invite = service.mint_class_invite(teacher, Role.teacher, class_id)
    invite_id, code = invite.id, invite.code

    result = service.redeem(student, code)

    assert result.role is InviteRole.student
    assert result.class_id == class_id
    assert result.school_id == school  # filled in from the class, not the invite row
    with pg_sessionmaker() as session:
        enrolled = session.scalars(
            sa.select(ClassEnrollment).where(
                ClassEnrollment.class_id == class_id, ClassEnrollment.student_id == student
            )
        ).first()
        assert enrolled is not None
        redeemed = session.get(Invite, invite_id)
        assert redeemed is not None
        assert redeemed.redeemed_by == student

    # Single-use, unlike the bare join code: a second student is refused.
    other_student = _seed_user(pg_sessionmaker, Role.student)
    with pytest.raises(InviteAlreadyRedeemedError):
        service.redeem(other_student, code)


# ── mint_parent_invite / get_or_create_parent_code / rotate_parent_code ────


def test_mint_parent_link_sets_child_created_by_and_seven_day_expiry(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _seed_user(pg_sessionmaker, Role.student)
    service = _service(pg_sessionmaker)

    invite = service.mint_parent_invite(student, reusable=False)

    assert invite.role is InviteRole.parent
    assert invite.child_id == student
    assert invite.created_by == student
    assert invite.reusable is False
    assert invite.redeemed_by is None
    assert invite.expires_at is not None
    expected = datetime.now(UTC) + PARENT_INVITE_TTL
    assert abs((invite.expires_at - expected).total_seconds()) < 5


def test_get_or_create_parent_code_is_lazy_and_stable(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _seed_user(pg_sessionmaker, Role.student)
    service = _service(pg_sessionmaker)
    with pg_sessionmaker() as session:
        existing = session.scalars(sa.select(Invite).where(Invite.child_id == student)).first()
        assert existing is None, "no row until first request - lazy"

    first = service.get_or_create_parent_code(student)
    second = service.get_or_create_parent_code(student)

    assert first.id == second.id
    assert first.code == second.code
    assert first.reusable is True
    assert first.expires_at is None
    with pg_sessionmaker() as session:
        rows = list(
            session.scalars(
                sa.select(Invite).where(Invite.child_id == student, Invite.reusable.is_(True))
            )
        )
        assert len(rows) == 1


def test_rotate_parent_code_replaces_the_row(pg_sessionmaker: sessionmaker[Session]) -> None:
    student = _seed_user(pg_sessionmaker, Role.student)
    service = _service(pg_sessionmaker)
    original = service.get_or_create_parent_code(student)

    rotated = service.rotate_parent_code(student)

    assert rotated.id != original.id
    assert rotated.code != original.code
    assert rotated.reusable is True
    with pg_sessionmaker() as session:
        assert session.get(Invite, original.id) is None
        assert session.get(Invite, rotated.id) is not None
        rows = list(
            session.scalars(
                sa.select(Invite).where(Invite.child_id == student, Invite.reusable.is_(True))
            )
        )
        assert len(rows) == 1


# ── list_parent_invites / revoke_parent_invite ──────────────────────────────


def test_list_parent_invites_excludes_expired_redeemed_and_reusable(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _seed_user(pg_sessionmaker, Role.student)
    parent = _seed_user(pg_sessionmaker, Role.parent)
    service = _service(pg_sessionmaker)
    first_live = service.mint_parent_invite(student, reusable=False)
    second_live = service.mint_parent_invite(student, reusable=False)
    service.mint_parent_invite(student, reusable=True)  # the reusable code - excluded
    redeemed = service.mint_parent_invite(student, reusable=False)
    service.redeem(parent, redeemed.code, caller_role=Role.parent)
    with pg_sessionmaker.begin() as session:
        session.add(
            Invite(
                code="EXPIREDPARENT",
                role=InviteRole.parent,
                child_id=student,
                created_by=student,
                expires_at=datetime.now(UTC) - timedelta(hours=1),
            )
        )

    invites = service.list_parent_invites(student)

    assert [i.id for i in invites] == [first_live.id, second_live.id]


def test_revoke_parent_invite_refuses_another_students_code(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _seed_user(pg_sessionmaker, Role.student)
    other_student = _seed_user(pg_sessionmaker, Role.student)
    service = _service(pg_sessionmaker)
    invite = service.mint_parent_invite(student, reusable=False)

    with pytest.raises(InviteNotFoundError):
        service.revoke_parent_invite(other_student, invite.code)
    with pg_sessionmaker() as session:
        assert session.get(Invite, invite.id) is not None

    # Owner can revoke it.
    service.revoke_parent_invite(student, invite.code)
    with pg_sessionmaker() as session:
        assert session.get(Invite, invite.id) is None

    # The reusable code is never revocable through this method.
    code_row = service.get_or_create_parent_code(student)
    with pytest.raises(InviteNotFoundError):
        service.revoke_parent_invite(student, code_row.code)

    with pytest.raises(InviteNotFoundError):
        service.revoke_parent_invite(student, "NOSUCHCODE")


# ── preview: parent invite names the child ──────────────────────────────────


def test_preview_parent_invite_names_child_never_email_or_id(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    named_student = _seed_user(pg_sessionmaker, Role.student, display_name="Amira")
    blank_student = _seed_user(pg_sessionmaker, Role.student, display_name=None)
    service = _service(pg_sessionmaker)
    named_invite = service.mint_parent_invite(named_student, reusable=False)
    blank_invite = service.mint_parent_invite(blank_student, reusable=False)

    named_preview = service.preview(named_invite.code)
    blank_preview = service.preview(blank_invite.code)

    assert named_preview.role is InviteRole.parent
    assert named_preview.child_name == "Amira"
    assert blank_preview.role is InviteRole.parent
    assert blank_preview.child_name == "your child"
    for preview, student in ((named_preview, named_student), (blank_preview, blank_student)):
        assert preview.school_name is None
        assert preview.class_name is None
        assert preview.teacher_name is None
        dumped = dataclasses.asdict(preview)
        rendered = repr(dumped)
        assert str(student) not in rendered
        with pg_sessionmaker() as session:
            email = session.get(User, student).email  # type: ignore[union-attr]
        assert email not in rendered


# ── redeem: parent invite links, role mismatch, idempotency ────────────────


def test_redeem_parent_link_links_and_consumes(pg_sessionmaker: sessionmaker[Session]) -> None:
    student = _seed_user(pg_sessionmaker, Role.student)
    parent = _seed_user(pg_sessionmaker, Role.parent)
    service = _service(pg_sessionmaker)
    invite = service.mint_parent_invite(student, reusable=False)

    result = service.redeem(parent, invite.code, caller_role=Role.parent)

    assert result.role is InviteRole.parent
    assert result.child_id == student
    assert result.school_id is None
    assert result.class_id is None
    with pg_sessionmaker() as session:
        redeemed = session.get(Invite, invite.id)
        assert redeemed is not None
        assert redeemed.redeemed_by == parent
        assert redeemed.redeemed_at is not None
        link = session.scalars(
            sa.select(ParentChildLink).where(
                ParentChildLink.parent_id == parent, ParentChildLink.child_id == student
            )
        ).first()
        assert link is not None

    # Single-use, like every other invites row: a second parent is refused.
    other_parent = _seed_user(pg_sessionmaker, Role.parent)
    with pytest.raises(InviteAlreadyRedeemedError):
        service.redeem(other_parent, invite.code, caller_role=Role.parent)


def test_redeem_parent_code_links_without_consuming_so_a_second_parent_can_use_it(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _seed_user(pg_sessionmaker, Role.student)
    first_parent = _seed_user(pg_sessionmaker, Role.parent)
    second_parent = _seed_user(pg_sessionmaker, Role.parent)
    service = _service(pg_sessionmaker)
    code_invite = service.get_or_create_parent_code(student)

    first_result = service.redeem(first_parent, code_invite.code, caller_role=Role.parent)
    second_result = service.redeem(second_parent, code_invite.code, caller_role=Role.parent)

    assert first_result.child_id == student
    assert second_result.child_id == student
    with pg_sessionmaker() as session:
        redeemed = session.get(Invite, code_invite.id)
        assert redeemed is not None
        assert redeemed.redeemed_by is None
        assert redeemed.redeemed_at is None
        links = list(
            session.scalars(sa.select(ParentChildLink).where(ParentChildLink.child_id == student))
        )
        assert {link.parent_id for link in links} == {first_parent, second_parent}


def test_redeem_parent_invite_by_student_is_role_mismatch(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _seed_user(pg_sessionmaker, Role.student)
    other_student = _seed_user(pg_sessionmaker, Role.student)
    service = _service(pg_sessionmaker)
    invite = service.mint_parent_invite(student, reusable=False)

    with pytest.raises(InviteRoleMismatchError):
        service.redeem(other_student, invite.code, caller_role=Role.student)

    with pg_sessionmaker() as session:
        redeemed = session.get(Invite, invite.id)
        assert redeemed is not None
        assert redeemed.redeemed_by is None
        link = session.scalars(
            sa.select(ParentChildLink).where(ParentChildLink.child_id == student)
        ).first()
        assert link is None


def test_redeem_class_invite_by_parent_is_role_mismatch(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    class_id = _seed_class(pg_sessionmaker, teacher_id=teacher)
    parent = _seed_user(pg_sessionmaker, Role.parent)
    service = _service(pg_sessionmaker)
    invite = service.mint_class_invite(teacher, Role.teacher, class_id)

    with pytest.raises(InviteRoleMismatchError):
        service.redeem(parent, invite.code, caller_role=Role.parent)

    with pg_sessionmaker() as session:
        redeemed = session.get(Invite, invite.id)
        assert redeemed is not None
        assert redeemed.redeemed_by is None


def test_redeem_parent_invite_twice_by_same_parent_is_idempotent(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = _seed_user(pg_sessionmaker, Role.student)
    parent = _seed_user(pg_sessionmaker, Role.parent)
    service = _service(pg_sessionmaker)
    invite = service.mint_parent_invite(student, reusable=False)

    first = service.redeem(parent, invite.code, caller_role=Role.parent)
    second = service.redeem(parent, invite.code, caller_role=Role.parent)

    assert first == second
    with pg_sessionmaker() as session:
        links = list(
            session.scalars(
                sa.select(ParentChildLink).where(
                    ParentChildLink.parent_id == parent, ParentChildLink.child_id == student
                )
            )
        )
        assert len(links) == 1


# ── review round 1 fixes: concurrency, cross-child isolation, join-code role ─


def test_get_or_create_parent_code_survives_concurrent_calls(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The second caller, racing the first, must be serialised behind the
    first's still-open transaction rather than reading "no row yet" and
    minting a second one - the failure mode review round 1's Important 1
    described (an unstable code, since ``_find_reusable_parent_code`` has no
    ``ORDER BY`` and would return either row on different calls).

    A bare two-thread race can pass by luck even on unfixed code (the OS
    may simply run the threads one after the other), so this deliberately
    controls the interleaving: a holder thread opens a transaction, inserts
    a reusable row and *does not commit*, proving via ``Event`` that it has
    done so; only then does a second thread call the real
    ``get_or_create_parent_code``. Without the fix that second call reads
    "no row" (the holder's insert is uncommitted, invisible under read
    committed) and inserts its own - a duplicate - and returns immediately.
    With the fix it blocks on the same row lock the holder took, so this
    also asserts it is still running half a second later, before the holder
    releases it.
    """
    student = _seed_user(pg_sessionmaker, Role.student)
    service = _service(pg_sessionmaker)
    holder_locked = threading.Event()
    release_holder = threading.Event()
    held: dict[str, uuid.UUID] = {}

    def hold_first_transaction() -> None:
        with pg_sessionmaker() as session, session.begin():
            session.get(User, student, with_for_update=True)
            invite = Invite(
                code="HELDCODE1",
                role=InviteRole.parent,
                child_id=student,
                created_by=student,
                reusable=True,
            )
            session.add(invite)
            session.flush()
            held["id"] = invite.id
            holder_locked.set()
            assert release_holder.wait(timeout=5), "test setup failed to signal release in time"
        # `session.begin()` commits here, on clean context-manager exit.

    holder = threading.Thread(target=hold_first_transaction)
    holder.start()
    assert holder_locked.wait(timeout=5), "holder thread failed to insert+lock in time"

    second_result: dict[str, Invite] = {}

    def call_second() -> None:
        second_result["invite"] = service.get_or_create_parent_code(student)

    second = threading.Thread(target=call_second)
    second.start()
    second.join(timeout=0.5)
    assert second.is_alive(), (
        "get_or_create_parent_code must block behind the holder's row lock, "
        "not race ahead and insert a second reusable row"
    )

    release_holder.set()
    holder.join(timeout=5)
    second.join(timeout=5)

    assert second_result["invite"].id == held["id"]
    with pg_sessionmaker() as session:
        rows = list(
            session.scalars(
                sa.select(Invite).where(Invite.child_id == student, Invite.reusable.is_(True))
            )
        )
        assert len(rows) == 1, "a race must not leave two reusable rows for one child"


def test_get_or_create_parent_code_is_isolated_per_student(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """``_find_reusable_parent_code`` filters on ``child_id`` - prove it does
    not hand one student a sibling's reusable row (review round 1, Minor 6)."""
    first_student = _seed_user(pg_sessionmaker, Role.student)
    second_student = _seed_user(pg_sessionmaker, Role.student)
    service = _service(pg_sessionmaker)

    first_code = service.get_or_create_parent_code(first_student)
    second_code = service.get_or_create_parent_code(second_student)

    assert first_code.id != second_code.id
    assert first_code.code != second_code.code
    assert service.get_or_create_parent_code(first_student).id == first_code.id
    assert service.get_or_create_parent_code(second_student).id == second_code.id


def test_redeem_class_join_code_by_parent_is_role_mismatch(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """The role-mismatch guard must also cover the bare ``classes.join_code``
    fall-through, not just an ``invites`` row - otherwise a parent handed (or
    guessing) a class join code is silently enrolled as a student (review
    round 1, Important 2)."""
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    class_id = _seed_class(pg_sessionmaker, teacher_id=teacher, join_code="PARENTJOIN")
    parent = _seed_user(pg_sessionmaker, Role.parent)
    service = _service(pg_sessionmaker)

    with pytest.raises(InviteRoleMismatchError):
        service.redeem(parent, "PARENTJOIN", caller_role=Role.parent)

    with pg_sessionmaker() as session:
        enrolled = session.scalars(
            sa.select(ClassEnrollment).where(ClassEnrollment.class_id == class_id)
        ).first()
        assert enrolled is None, "a parent must not be enrolled as a student via a join code"
