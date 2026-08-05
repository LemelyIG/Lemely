"""Postgres integration tests for the class-model service (D3.1/P3.1).

Exercises :class:`~lemely.db.class_repo.ClassService` against a throwaway
database and skips cleanly when no local server is reachable (mirrors
``test_seat_repo.py``). Proves the guarantees D3.1 requires:

* **Tenancy** — a teacher sees only their own classes; a school_admin sees
  classes in schools they administer; a platform_admin sees none (no
  super-role bypass, mirroring D1.10). Cross-teacher access is a
  :class:`ClassOwnershipError`, never data.
* **Independent teachers** (``school_id=None``) can create and own a class.
* **Dual enrolment** — join-code self-enrolment (happy, idempotent, unknown
  code rejected) and seat-based direct add (happy, idempotent, rejects a
  non-seated/revoked-seat student and a class with no school).
* ``remove_student`` is idempotent and reachable by both the owning teacher
  and an administering school_admin.
* ``join_code`` uniqueness across classes.
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
from lemely.db.class_repo import (
    ClassHasNoSchoolError,
    ClassNotFoundError,
    ClassOwnershipError,
    ClassService,
    JoinCodeError,
    StudentNotSeatedError,
)
from lemely.db.models import ClassEnrollment, School, SchoolMembership, Seat, User
from lemely.db.models.enums import MembershipRole, Role, SeatStatus
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
    sm: sessionmaker[Session], role: Role = Role.teacher, display_name: str | None = None
) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role, display_name=display_name))
    return uid


def _seed_school(
    sm: sessionmaker[Session],
    *,
    admin_id: uuid.UUID | None = None,
    teacher_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Create a school, optionally granting a school_admin and/or teacher membership."""
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
        if teacher_id is not None:
            session.add(
                SchoolMembership(
                    school_id=school_id,
                    user_id=teacher_id,
                    membership_role=MembershipRole.teacher,
                )
            )
    return school_id


def _seed_seat(
    sm: sessionmaker[Session],
    *,
    school_id: uuid.UUID,
    student_id: uuid.UUID,
    status: SeatStatus = SeatStatus.assigned,
) -> uuid.UUID:
    seat_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            Seat(id=seat_id, school_id=school_id, assigned_user_id=student_id, status=status)
        )
    return seat_id


# ── Tenancy: list_classes / get_class ───────────────────────────────────────


def test_teacher_sees_only_own_classes(pg_sessionmaker: sessionmaker[Session]) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    other_teacher = _seed_user(pg_sessionmaker, Role.teacher)
    service = ClassService(pg_sessionmaker)
    mine = service.create_class(teacher, "Physics 10A")
    service.create_class(other_teacher, "Chem 9B")

    classes = service.list_classes(teacher, Role.teacher)
    assert [c.class_id for c in classes] == [mine.class_id]


def test_school_admin_sees_own_school_classes(pg_sessionmaker: sessionmaker[Session]) -> None:
    admin = _seed_user(pg_sessionmaker, Role.school_admin)
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    other_teacher = _seed_user(pg_sessionmaker, Role.teacher)
    school = _seed_school(pg_sessionmaker, admin_id=admin, teacher_id=teacher)
    other_school = _seed_school(pg_sessionmaker, teacher_id=other_teacher)  # not mine
    service = ClassService(pg_sessionmaker)
    mine = service.create_class(teacher, "Bio 11", school_id=school)
    service.create_class(other_teacher, "Art 12", school_id=other_school)

    classes = service.list_classes(admin, Role.school_admin)
    assert [c.class_id for c in classes] == [mine.class_id]


def test_platform_admin_sees_no_classes(pg_sessionmaker: sessionmaker[Session]) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    admin = _seed_user(pg_sessionmaker, Role.platform_admin)
    service = ClassService(pg_sessionmaker)
    service.create_class(teacher, "Physics 10A")

    assert service.list_classes(admin, Role.platform_admin) == []


def test_get_class_by_non_owner_teacher_is_ownership_error(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    owner = _seed_user(pg_sessionmaker, Role.teacher)
    stranger = _seed_user(pg_sessionmaker, Role.teacher)
    service = ClassService(pg_sessionmaker)
    cls = service.create_class(owner, "Physics 10A")

    with pytest.raises(ClassOwnershipError):
        service.get_class(stranger, Role.teacher, cls.class_id)


def test_platform_admin_get_class_is_ownership_error_not_data(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    admin = _seed_user(pg_sessionmaker, Role.platform_admin)
    service = ClassService(pg_sessionmaker)
    cls = service.create_class(teacher, "Physics 10A")

    with pytest.raises(ClassOwnershipError):
        service.get_class(admin, Role.platform_admin, cls.class_id)


def test_get_unknown_class_is_not_found(pg_sessionmaker: sessionmaker[Session]) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    service = ClassService(pg_sessionmaker)

    with pytest.raises(ClassNotFoundError):
        service.get_class(teacher, Role.teacher, uuid.uuid4())


# ── Independent teacher + create ownership ──────────────────────────────────


def test_independent_teacher_can_create_and_own_class(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    service = ClassService(pg_sessionmaker)

    cls = service.create_class(teacher, "Home Tuition", school_id=None)
    assert cls.school_id is None
    assert cls.teacher_id == teacher

    fetched = service.get_class(teacher, Role.teacher, cls.class_id)
    assert fetched.class_id == cls.class_id


def test_create_class_in_school_without_membership_is_ownership_error(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    school = _seed_school(pg_sessionmaker)  # no membership granted to teacher
    service = ClassService(pg_sessionmaker)

    with pytest.raises(ClassOwnershipError):
        service.create_class(teacher, "Physics 10A", school_id=school)


def test_join_codes_are_unique(pg_sessionmaker: sessionmaker[Session]) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    service = ClassService(pg_sessionmaker)

    a = service.create_class(teacher, "A")
    b = service.create_class(teacher, "B")
    assert a.join_code is not None
    assert b.join_code is not None
    assert a.join_code != b.join_code


# ── Join-code self-enrolment ─────────────────────────────────────────────────


def test_join_by_code_happy_and_idempotent(pg_sessionmaker: sessionmaker[Session]) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    student = _seed_user(pg_sessionmaker, Role.student, display_name="Amelia")
    service = ClassService(pg_sessionmaker)
    cls = service.create_class(teacher, "Physics 10A")
    assert cls.join_code is not None

    joined = service.join_by_code(student, cls.join_code)
    assert joined.class_id == cls.class_id
    roster = service.roster(teacher, Role.teacher, cls.class_id)
    assert [r.student_id for r in roster] == [student]

    # Re-joining is a no-op, not a duplicate row.
    service.join_by_code(student, cls.join_code)
    assert len(service.roster(teacher, Role.teacher, cls.class_id)) == 1


def test_join_by_unknown_code_is_join_code_error(pg_sessionmaker: sessionmaker[Session]) -> None:
    student = _seed_user(pg_sessionmaker, Role.student)
    service = ClassService(pg_sessionmaker)

    with pytest.raises(JoinCodeError):
        service.join_by_code(student, "NOPE1234")


# ── Seat-based direct enrolment ──────────────────────────────────────────────


def test_enroll_by_seat_happy_and_idempotent(pg_sessionmaker: sessionmaker[Session]) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    student = _seed_user(pg_sessionmaker, Role.student, display_name="Jonas")
    school = _seed_school(pg_sessionmaker, teacher_id=teacher)
    _seed_seat(pg_sessionmaker, school_id=school, student_id=student)
    service = ClassService(pg_sessionmaker)
    cls = service.create_class(teacher, "Physics 10A", school_id=school)

    entry = service.enroll_by_seat(teacher, Role.teacher, cls.class_id, student)
    assert entry.student_id == student
    assert entry.display_name == "Jonas"

    # Idempotent: re-enrolling does not duplicate the roster row.
    service.enroll_by_seat(teacher, Role.teacher, cls.class_id, student)
    assert len(service.roster(teacher, Role.teacher, cls.class_id)) == 1


def test_enroll_by_seat_rejects_non_seated_student(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    student = _seed_user(pg_sessionmaker, Role.student)
    school = _seed_school(pg_sessionmaker, teacher_id=teacher)
    service = ClassService(pg_sessionmaker)
    cls = service.create_class(teacher, "Physics 10A", school_id=school)

    with pytest.raises(StudentNotSeatedError):
        service.enroll_by_seat(teacher, Role.teacher, cls.class_id, student)


def test_enroll_by_seat_rejects_revoked_seat(pg_sessionmaker: sessionmaker[Session]) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    student = _seed_user(pg_sessionmaker, Role.student)
    school = _seed_school(pg_sessionmaker, teacher_id=teacher)
    _seed_seat(pg_sessionmaker, school_id=school, student_id=student, status=SeatStatus.revoked)
    service = ClassService(pg_sessionmaker)
    cls = service.create_class(teacher, "Physics 10A", school_id=school)

    with pytest.raises(StudentNotSeatedError):
        service.enroll_by_seat(teacher, Role.teacher, cls.class_id, student)


def test_enroll_by_seat_rejects_class_with_no_school(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    student = _seed_user(pg_sessionmaker, Role.student)
    service = ClassService(pg_sessionmaker)
    cls = service.create_class(teacher, "Home Tuition")  # no school -> no seat pool

    with pytest.raises(ClassHasNoSchoolError):
        service.enroll_by_seat(teacher, Role.teacher, cls.class_id, student)


# ── remove_student ────────────────────────────────────────────────────────────


def test_remove_student_is_idempotent(pg_sessionmaker: sessionmaker[Session]) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    student = _seed_user(pg_sessionmaker, Role.student)
    service = ClassService(pg_sessionmaker)
    cls = service.create_class(teacher, "Physics 10A")
    assert cls.join_code is not None
    service.join_by_code(student, cls.join_code)

    service.remove_student(teacher, Role.teacher, cls.class_id, student)
    assert service.roster(teacher, Role.teacher, cls.class_id) == []
    # Removing an already-absent student is a no-op, not an error.
    service.remove_student(teacher, Role.teacher, cls.class_id, student)


def test_remove_student_reachable_by_administering_school_admin(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    admin = _seed_user(pg_sessionmaker, Role.school_admin)
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    school = _seed_school(pg_sessionmaker, admin_id=admin, teacher_id=teacher)
    student = _seed_user(pg_sessionmaker, Role.student)
    service = ClassService(pg_sessionmaker)
    cls = service.create_class(teacher, "Physics 10A", school_id=school)
    assert cls.join_code is not None
    service.join_by_code(student, cls.join_code)

    service.remove_student(admin, Role.school_admin, cls.class_id, student)
    assert service.roster(teacher, Role.teacher, cls.class_id) == []


def test_remove_student_by_non_owner_teacher_is_ownership_error(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    owner = _seed_user(pg_sessionmaker, Role.teacher)
    stranger = _seed_user(pg_sessionmaker, Role.teacher)
    student = _seed_user(pg_sessionmaker, Role.student)
    service = ClassService(pg_sessionmaker)
    cls = service.create_class(owner, "Physics 10A")
    assert cls.join_code is not None
    service.join_by_code(student, cls.join_code)

    with pytest.raises(ClassOwnershipError):
        service.remove_student(stranger, Role.teacher, cls.class_id, student)
    # Unaffected by the rejected removal.
    assert len(service.roster(owner, Role.teacher, cls.class_id)) == 1


# ── update / delete (owner-scoped) ──────────────────────────────────────────


def test_update_class_is_owner_scoped(pg_sessionmaker: sessionmaker[Session]) -> None:
    owner = _seed_user(pg_sessionmaker, Role.teacher)
    stranger = _seed_user(pg_sessionmaker, Role.teacher)
    service = ClassService(pg_sessionmaker)
    cls = service.create_class(owner, "Physics 10A")

    updated = service.update_class(owner, cls.class_id, name="Physics 10B")
    assert updated.name == "Physics 10B"

    with pytest.raises(ClassOwnershipError):
        service.update_class(stranger, cls.class_id, name="Hijacked")


def test_delete_class_is_owner_scoped_and_cascades_enrolments(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    owner = _seed_user(pg_sessionmaker, Role.teacher)
    student = _seed_user(pg_sessionmaker, Role.student)
    service = ClassService(pg_sessionmaker)
    cls = service.create_class(owner, "Physics 10A")
    assert cls.join_code is not None
    service.join_by_code(student, cls.join_code)

    service.delete_class(owner, cls.class_id)

    with pytest.raises(ClassNotFoundError):
        service.get_class(owner, Role.teacher, cls.class_id)
    with pg_sessionmaker() as session:
        remaining = session.scalars(
            sa.select(ClassEnrollment).where(ClassEnrollment.class_id == cls.class_id)
        ).all()
        assert remaining == []


# ── Roster count + identity ─────────────────────────────────────────────────


def test_student_count_reflects_roster(pg_sessionmaker: sessionmaker[Session]) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    student_a = _seed_user(pg_sessionmaker, Role.student)
    student_b = _seed_user(pg_sessionmaker, Role.student)
    service = ClassService(pg_sessionmaker)
    cls = service.create_class(teacher, "Physics 10A")
    assert cls.join_code is not None
    service.join_by_code(student_a, cls.join_code)
    service.join_by_code(student_b, cls.join_code)

    refreshed = service.get_class(teacher, Role.teacher, cls.class_id)
    assert refreshed.student_count == 2


def test_roster_identity_falls_back_to_email_without_display_name(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    teacher = _seed_user(pg_sessionmaker, Role.teacher)
    student = _seed_user(pg_sessionmaker, Role.student, display_name=None)
    service = ClassService(pg_sessionmaker)
    cls = service.create_class(teacher, "Physics 10A")
    assert cls.join_code is not None
    service.join_by_code(student, cls.join_code)

    roster = service.roster(teacher, Role.teacher, cls.class_id)
    assert roster[0].display_name == f"{student}@example.com"


# ── Input validation ─────────────────────────────────────────────────────────


def test_non_uuid_identifiers_rejected(pg_sessionmaker: sessionmaker[Session]) -> None:
    service = ClassService(pg_sessionmaker)
    with pytest.raises(ValueError, match="must be a UUID"):
        service.get_class("not-a-uuid", Role.teacher, uuid.uuid4())
    with pytest.raises(ValueError, match="must be a UUID"):
        service.get_class(uuid.uuid4(), Role.teacher, "not-a-uuid")
