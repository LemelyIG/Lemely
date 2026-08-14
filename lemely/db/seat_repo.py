"""Seat allocation service — school_admin invites students against a seat quota.

A :class:`~lemely.db.models.orgs.School` buys a fixed ``seat_quota``; each
occupied slot is a non-revoked :class:`~lemely.db.models.orgs.Seat` row. Seats are
allocated **on demand** (there is no pre-provisioning step): an invite creates a
student account and, in the same locked transaction, inserts an ``assigned`` seat
— provided the school still has headroom. Revoking a seat flips it to ``revoked``
(freeing quota) without deleting the student's account.

Ownership is membership-based: a caller may only touch a school for which they
hold a ``school_admin`` :class:`~lemely.db.models.orgs.SchoolMembership`. There is
no implicit super-role (mirrors D1.6); a ``platform_admin`` operates via a
dedicated surface later, not this one.

Account creation is injected as a :class:`StudentAccountCreator` seam so the pure
seat/quota/ownership logic is testable against Postgres without the live GoTrue
stack; the real implementation wraps :meth:`AuthService.signup`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from lemely.db.models import (
    Attempt,
    ClassEnrollment,
    School,
    SchoolClass,
    SchoolMembership,
    Seat,
    User,
)
from lemely.db.models.enums import MembershipRole, SeatStatus

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker


class SeatError(Exception):
    """Base class for seat-allocation failures."""


class SeatOwnershipError(SeatError):
    """The caller does not administer the target school (→ 403)."""


class SeatQuotaExceededError(SeatError):
    """The school has no free seats left against its quota (→ 409)."""


class SeatNotFoundError(SeatError):
    """No seat exists for the supplied id (→ 404)."""


class StudentAccountCreator(Protocol):
    """Creates a student identity and returns its ``public.users`` id.

    The real implementation admin-creates a GoTrue user and mirrors it into
    ``public.users`` as a student (see :class:`AuthServiceStudentCreator`); tests
    substitute a fake that inserts a ``User`` row directly.
    """

    def create_student(
        self,
        email: str,
        password: str,
        display_name: str | None = None,
    ) -> uuid.UUID:
        """Create a student account and return its user id."""
        ...


@dataclass(frozen=True, slots=True)
class SeatClass:
    """One class, inside this school, that a seated student is enrolled in."""

    class_id: uuid.UUID
    name: str
    teacher_name: str | None


@dataclass(frozen=True, slots=True)
class SeatRow:
    """A single seat with the identity it is (or was) assigned to.

    ``classes`` is a **list**, not a single class, because nothing in the schema
    makes a student's enrolment within one school exclusive
    (``uq_class_enrollments_class_id_student_id`` is per class, not per school).
    UI spec K-02 asks for one "class" column; collapsing a real many to a
    displayed one would pick a winner arbitrarily, so the list is returned as it
    is and the screen renders what is actually there.

    ``last_attempt_at`` is the most recent :class:`~lemely.db.models.attempts.Attempt`
    this student recorded, and is deliberately **not** named ``last_active_at``
    (K-02's own wording). No table records a session or a login — ``users`` has
    no ``last_seen``, and ``devices`` records registration, not use — so the only
    honest reading is "last marked something". The screen labels it that way.
    """

    seat_id: uuid.UUID
    status: SeatStatus
    assigned_user_id: uuid.UUID | None
    assigned_email: str | None
    assigned_display_name: str | None
    assigned_at: datetime | None
    classes: list[SeatClass]
    last_attempt_at: datetime | None


@dataclass(frozen=True, slots=True)
class SeatUsage:
    """A school's seat headroom plus its current (non-revoked) seat rows."""

    school_id: uuid.UUID
    school_name: str
    quota: int
    used: int
    seats: list[SeatRow]

    @property
    def available(self) -> int:
        """Free seats remaining against the quota (never negative)."""
        return max(0, self.quota - self.used)


@dataclass(frozen=True, slots=True)
class InviteResult:
    """The outcome of inviting a student onto a seat."""

    user_id: uuid.UUID
    seat_id: uuid.UUID
    email: str


class SeatService:
    """Seat allocation, revocation, and per-school introspection.

    Constructed with a ``sessionmaker`` (mirroring
    :class:`~lemely.db.history_repo.DbHistoryStore`) and a
    :class:`StudentAccountCreator`. Every mutating call re-verifies that the
    caller administers the target school before touching any row.
    """

    def __init__(
        self,
        sessionmaker: sessionmaker[Session],
        account_creator: StudentAccountCreator,
    ) -> None:
        """Wire the service to a session factory and an account creator."""
        self._sessionmaker = sessionmaker
        self._account_creator = account_creator

    # -- Introspection ------------------------------------------------------

    def list_admin_schools(self, admin_user_id: uuid.UUID | str) -> list[SeatUsage]:
        """Return seat usage for every school the caller administers.

        A school appears only when the caller holds a ``school_admin`` membership
        for it; a caller who administers nothing gets an empty list (not an
        error).
        """
        admin_uuid = _as_uuid(admin_user_id)
        with self._sessionmaker() as session:
            school_ids = self._admin_school_ids(session, admin_uuid)
            return [self._seat_usage(session, sid) for sid in school_ids]

    def seat_usage(self, admin_user_id: uuid.UUID | str, school_id: uuid.UUID | str) -> SeatUsage:
        """Return seat usage for one school the caller administers.

        Raises:
            SeatOwnershipError: The caller does not administer ``school_id``.
        """
        admin_uuid = _as_uuid(admin_user_id)
        school_uuid = _as_uuid(school_id)
        with self._sessionmaker() as session:
            self._assert_admin_of(session, admin_uuid, school_uuid)
            return self._seat_usage(session, school_uuid)

    # -- Mutations ----------------------------------------------------------

    def invite_student(
        self,
        admin_user_id: uuid.UUID | str,
        school_id: uuid.UUID | str,
        email: str,
        password: str,
        display_name: str | None = None,
    ) -> InviteResult:
        """Create a student account and assign it a seat in ``school_id``.

        The school row is locked ``FOR UPDATE`` for the duration so concurrent
        invites cannot both slip past the quota check (TOCTOU). Ownership and
        quota are verified *before* the account is created, so a rejected invite
        never leaves an orphaned account behind.

        Raises:
            SeatOwnershipError: The caller does not administer ``school_id``.
            SeatQuotaExceededError: The school is at its seat quota.
        """
        admin_uuid = _as_uuid(admin_user_id)
        school_uuid = _as_uuid(school_id)
        with self._sessionmaker() as session, session.begin():
            self._assert_admin_of(session, admin_uuid, school_uuid)
            # Lock the school row so a parallel invite serialises behind us.
            school = session.get(School, school_uuid, with_for_update=True)
            if school is None:  # pragma: no cover - ownership check already loaded it
                raise SeatOwnershipError("Unknown school")
            used = self._used_seats(session, school_uuid)
            if used >= school.seat_quota:
                raise SeatQuotaExceededError(
                    f"School {school_uuid} has no free seats ({used}/{school.seat_quota} used)"
                )
            # Account creation is a separate transaction (GoTrue + mirror); the
            # school row stays locked so no other invite can consume the slot we
            # are about to fill.
            user_id = self._account_creator.create_student(email, password, display_name)
            seat = Seat(
                school_id=school_uuid,
                assigned_user_id=user_id,
                status=SeatStatus.assigned,
                assigned_at=datetime.now(UTC),
            )
            session.add(seat)
            session.flush()
            return InviteResult(user_id=user_id, seat_id=seat.id, email=email)

    def revoke_seat(self, admin_user_id: uuid.UUID | str, seat_id: uuid.UUID | str) -> None:
        """Revoke a seat, freeing its slot against the school's quota.

        The student's account is left intact; only the seat is released. Revoking
        an already-revoked seat is idempotent.

        Raises:
            SeatNotFoundError: No seat with ``seat_id`` exists.
            SeatOwnershipError: The caller does not administer the seat's school.
        """
        admin_uuid = _as_uuid(admin_user_id)
        seat_uuid = _as_uuid(seat_id)
        with self._sessionmaker() as session, session.begin():
            seat = session.get(Seat, seat_uuid)
            if seat is None:
                raise SeatNotFoundError(f"Unknown seat: {seat_uuid}")
            self._assert_admin_of(session, admin_uuid, seat.school_id)
            seat.status = SeatStatus.revoked

    # -- Internals ----------------------------------------------------------

    def _admin_school_ids(self, session: Session, admin_uuid: uuid.UUID) -> list[uuid.UUID]:
        stmt = (
            select(SchoolMembership.school_id)
            .where(
                SchoolMembership.user_id == admin_uuid,
                SchoolMembership.membership_role == MembershipRole.school_admin,
            )
            .order_by(SchoolMembership.school_id)
        )
        return list(session.scalars(stmt).all())

    def _assert_admin_of(
        self, session: Session, admin_uuid: uuid.UUID, school_uuid: uuid.UUID
    ) -> None:
        stmt = select(SchoolMembership.id).where(
            SchoolMembership.user_id == admin_uuid,
            SchoolMembership.school_id == school_uuid,
            SchoolMembership.membership_role == MembershipRole.school_admin,
        )
        if session.scalars(stmt).first() is None:
            raise SeatOwnershipError(f"Caller does not administer school {school_uuid}")

    def _used_seats(self, session: Session, school_uuid: uuid.UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(Seat)
            .where(Seat.school_id == school_uuid, Seat.status != SeatStatus.revoked)
        )
        return int(session.scalar(stmt) or 0)

    def _seat_usage(self, session: Session, school_uuid: uuid.UUID) -> SeatUsage:
        school = session.get(School, school_uuid)
        if school is None:  # pragma: no cover - callers pass ids from memberships
            raise SeatNotFoundError(f"Unknown school: {school_uuid}")
        stmt = (
            select(Seat, User.email, User.display_name)
            .outerjoin(User, User.id == Seat.assigned_user_id)
            .where(Seat.school_id == school_uuid, Seat.status != SeatStatus.revoked)
            .order_by(Seat.assigned_at)
        )
        seats = list(session.execute(stmt).all())
        # Two grouped lookups rather than one per seat: a school at its quota is
        # hundreds of rows, and K-02 renders all of them at once.
        occupant_ids = [seat.assigned_user_id for seat, _, _ in seats if seat.assigned_user_id]
        classes_by_student = self._classes_by_student(session, school_uuid, occupant_ids)
        last_attempt_by_student = self._last_attempt_by_student(session, occupant_ids)
        rows = [
            SeatRow(
                seat_id=seat.id,
                status=seat.status,
                assigned_user_id=seat.assigned_user_id,
                assigned_email=email,
                assigned_display_name=display_name,
                assigned_at=seat.assigned_at,
                classes=classes_by_student.get(seat.assigned_user_id, []),
                last_attempt_at=last_attempt_by_student.get(seat.assigned_user_id),
            )
            for seat, email, display_name in seats
        ]
        return SeatUsage(
            school_id=school.id,
            school_name=school.name,
            quota=school.seat_quota,
            used=len(rows),
            seats=rows,
        )

    def _classes_by_student(
        self,
        session: Session,
        school_uuid: uuid.UUID,
        student_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, list[SeatClass]]:
        """Map each student to the classes **of this school** they are enrolled in.

        Scoped to ``school_uuid`` on purpose: a seated student may also be
        enrolled in an independent teacher's class (``SchoolClass.school_id`` is
        nullable, D3.1), and that class is none of this admin's business.
        """
        if not student_ids:
            return {}
        teacher = aliased(User)
        stmt = (
            select(
                ClassEnrollment.student_id,
                SchoolClass.id,
                SchoolClass.name,
                teacher.display_name,
            )
            .join(SchoolClass, SchoolClass.id == ClassEnrollment.class_id)
            .outerjoin(teacher, teacher.id == SchoolClass.teacher_id)
            .where(
                SchoolClass.school_id == school_uuid,
                ClassEnrollment.student_id.in_(student_ids),
            )
            .order_by(SchoolClass.name)
        )
        grouped: dict[uuid.UUID, list[SeatClass]] = {}
        for student_id, class_id, name, teacher_name in session.execute(stmt).all():
            grouped.setdefault(student_id, []).append(
                SeatClass(class_id=class_id, name=name, teacher_name=teacher_name)
            )
        return grouped

    def _last_attempt_by_student(
        self, session: Session, student_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, datetime]:
        """Map each student to the timestamp of their most recent attempt.

        Every attempt origin counts (a quiz is activity too); this is a recency
        signal, not a performance one.
        """
        if not student_ids:
            return {}
        stmt = (
            select(Attempt.user_id, func.max(Attempt.recorded_at))
            .where(Attempt.user_id.in_(student_ids))
            .group_by(Attempt.user_id)
        )
        return {user_id: recorded_at for user_id, recorded_at in session.execute(stmt).all()}


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    """Coerce a str/UUID to :class:`uuid.UUID`, raising ``ValueError`` if invalid."""
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Identifier must be a UUID, got {value!r}") from exc


__all__ = [
    "InviteResult",
    "SeatClass",
    "SeatError",
    "SeatNotFoundError",
    "SeatOwnershipError",
    "SeatQuotaExceededError",
    "SeatRow",
    "SeatService",
    "SeatUsage",
    "StudentAccountCreator",
]
