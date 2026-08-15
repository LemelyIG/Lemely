"""School-admin console service — the counts, the teacher roster, and staffing.

:mod:`lemely.db.seat_repo` owns *seats*: quota, invite, revoke. This module owns
everything else a ``school_admin`` console needs (UI spec K-01/K-03) and which no
service previously exposed at all — the school's teacher roster, the counts on
the dashboard, and the two staffing mutations (invite a teacher, remove one).

It shares :class:`~lemely.db.seat_repo.SeatService`'s authorization model exactly,
and for the same reason: a caller may only touch a school they hold a
``school_admin`` :class:`~lemely.db.models.orgs.SchoolMembership` for. There is no
super-role — a ``platform_admin`` reaching here administers nothing and gets an
empty list, never every school (D1.6/D1.10). That is not an oversight to be fixed
by widening the query; it is the same rule ``class_repo`` and ``at_risk_repo``
already enforce.

**What this module deliberately does not compute: the school's average
performance.** The counts here are pure row counts, so they can be SQL. A mean
percentage cannot: ``docs/quiz-model.md`` §5 makes it "latest *grade-bearing*
record per student", a filter that lives in
:func:`lemely.core.history.latest_grade_bearing` and is pinned by
``tests/test_web_quiz_origin_filtering.py``. Re-expressing that rule in SQL would
be a second definition of the number the teacher portal already shows, free to
drift from it. So :meth:`SchoolAdminService.overview` returns the *student ids*
and the web layer averages them through the same ``_average_for`` the class
screens use.

Teacher account creation is injected as a :class:`TeacherAccountCreator` seam for
the same reason :class:`~lemely.db.seat_repo.StudentAccountCreator` exists: the
membership and reassignment logic is then testable against Postgres without the
live GoTrue stack.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from sqlalchemy import func, select

from lemely.db.models import (
    ClassEnrollment,
    School,
    SchoolClass,
    SchoolMembership,
    User,
)
from lemely.db.models.enums import MembershipRole, Role

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker


class SchoolAdminError(Exception):
    """Base class for school-console failures."""


class SchoolOwnershipError(SchoolAdminError):
    """The caller does not administer the target school (→ 403)."""


class TeacherNotFoundError(SchoolAdminError):
    """No teacher with that id holds a membership in the target school (→ 404)."""


class ClassesWouldBeOrphanedError(SchoolAdminError):
    """Removing this teacher would leave classes with no owner (→ 409).

    UI spec K-03 requires reassignment be "handled explicitly rather than
    orphaned", so this is raised instead of silently deleting, nulling, or
    cascading the classes. It carries the count so the caller can say how many.
    """

    def __init__(self, class_count: int) -> None:
        """Record how many classes block the removal."""
        super().__init__(f"Teacher still owns {class_count} class(es); supply reassignToTeacherId")
        self.class_count = class_count


class InvalidReassignmentError(SchoolAdminError):
    """The reassignment target is not a teacher in this school (→ 409)."""


class TeacherAccountCreator(Protocol):
    """Creates a teacher identity and returns its ``public.users`` id.

    Mirrors :class:`~lemely.db.seat_repo.StudentAccountCreator`. The real
    implementation admin-creates a GoTrue user pinned to :attr:`Role.teacher`;
    tests substitute a fake that inserts a ``User`` row directly.
    """

    def create_teacher(
        self,
        email: str,
        password: str,
        display_name: str | None = None,
    ) -> uuid.UUID:
        """Create a teacher account and return its user id."""
        ...


@dataclass(frozen=True, slots=True)
class SchoolCounts:
    """Row counts for one school, plus the student ids behind the roll.

    ``student_ids`` is returned rather than a bare count because the web layer
    needs the identities to compute the school's average through the same
    grade-bearing filter the class screens use (see the module docstring).
    ``enrolled_student_count`` is ``len(student_ids)`` and is spelled out so a
    reader of the DTO does not have to know that.
    """

    school_id: uuid.UUID
    school_name: str
    teacher_count: int
    class_count: int
    student_ids: list[uuid.UUID]

    @property
    def enrolled_student_count(self) -> int:
        """Distinct students enrolled in at least one of the school's classes."""
        return len(self.student_ids)


@dataclass(frozen=True, slots=True)
class TeacherRow:
    """One teacher on a school's staff, with the size of what they teach."""

    user_id: uuid.UUID
    email: str
    display_name: str | None
    class_count: int
    student_count: int


@dataclass(frozen=True, slots=True)
class SchoolTeachers:
    """A school's staff roster."""

    school_id: uuid.UUID
    school_name: str
    teachers: list[TeacherRow]


@dataclass(frozen=True, slots=True)
class InviteTeacherResult:
    """The created teacher's identity and the membership binding them."""

    user_id: uuid.UUID
    membership_id: uuid.UUID
    email: str


class SchoolAdminService:
    """Counts, staff roster, and staffing mutations for administered schools."""

    def __init__(
        self,
        sessionmaker: sessionmaker[Session],
        account_creator: TeacherAccountCreator,
    ) -> None:
        """Wire the service to a session factory and a teacher-account creator."""
        self._sessionmaker = sessionmaker
        self._account_creator = account_creator

    # -- Introspection ------------------------------------------------------

    def overview(self, admin_user_id: uuid.UUID | str) -> list[SchoolCounts]:
        """Return counts for every school the caller administers.

        A caller who administers nothing gets an empty list, not an error — the
        same shape :meth:`~lemely.db.seat_repo.SeatService.list_admin_schools`
        returns, so K-01 has one empty state rather than two.
        """
        admin_uuid = _as_uuid(admin_user_id)
        with self._sessionmaker() as session:
            return [
                self._counts_for(session, school_id)
                for school_id in self._admin_school_ids(session, admin_uuid)
            ]

    def list_teachers(self, admin_user_id: uuid.UUID | str) -> list[SchoolTeachers]:
        """Return the staff roster for every school the caller administers."""
        admin_uuid = _as_uuid(admin_user_id)
        with self._sessionmaker() as session:
            return [
                self._teachers_for(session, school_id)
                for school_id in self._admin_school_ids(session, admin_uuid)
            ]

    # -- Mutations ----------------------------------------------------------

    def invite_teacher(
        self,
        admin_user_id: uuid.UUID | str,
        school_id: uuid.UUID | str,
        email: str,
        password: str,
        display_name: str | None = None,
    ) -> InviteTeacherResult:
        """Create a teacher account and bind it to ``school_id`` as staff.

        Unlike a seat invite this consumes no quota: seats are a *student*
        allocation (``Seat.assigned_user_id`` is filled by
        :meth:`~lemely.db.seat_repo.SeatService.invite_student`), and a school's
        teachers are not billed against them anywhere in the schema. So there is
        deliberately no quota check here — adding one would invent a limit the
        product does not have.

        Ownership is verified before the account is created, so a rejected invite
        never leaves an orphaned identity behind (same ordering as
        :meth:`~lemely.db.seat_repo.SeatService.invite_student`).

        Raises:
            SchoolOwnershipError: The caller does not administer ``school_id``.
        """
        admin_uuid = _as_uuid(admin_user_id)
        school_uuid = _as_uuid(school_id)
        with self._sessionmaker() as session, session.begin():
            self._assert_admin_of(session, admin_uuid, school_uuid)
            user_id = self._account_creator.create_teacher(email, password, display_name)
            membership = SchoolMembership(
                school_id=school_uuid,
                user_id=user_id,
                membership_role=MembershipRole.teacher,
            )
            session.add(membership)
            session.flush()
            return InviteTeacherResult(user_id=user_id, membership_id=membership.id, email=email)

    def remove_teacher(
        self,
        admin_user_id: uuid.UUID | str,
        school_id: uuid.UUID | str,
        teacher_id: uuid.UUID | str,
        reassign_to: uuid.UUID | str | None = None,
    ) -> int:
        """Remove a teacher from a school, reassigning their classes first.

        Returns the number of classes reassigned (0 when the teacher owned none).

        The teacher's **account is not deleted** — only their membership of this
        school. Deleting the identity would take their name off every class they
        ever ran and every announcement they ever wrote, which is a destruction a
        staffing change should not perform.

        Raises:
            SchoolOwnershipError: The caller does not administer ``school_id``.
            TeacherNotFoundError: No such teacher membership in this school.
            ClassesWouldBeOrphanedError: They own classes and no target was given.
            InvalidReassignmentError: The target is not another teacher here.
        """
        admin_uuid = _as_uuid(admin_user_id)
        school_uuid = _as_uuid(school_id)
        teacher_uuid = _as_uuid(teacher_id)
        target_uuid = _as_uuid(reassign_to) if reassign_to is not None else None
        with self._sessionmaker() as session, session.begin():
            self._assert_admin_of(session, admin_uuid, school_uuid)
            membership = session.scalars(
                select(SchoolMembership).where(
                    SchoolMembership.school_id == school_uuid,
                    SchoolMembership.user_id == teacher_uuid,
                    SchoolMembership.membership_role == MembershipRole.teacher,
                )
            ).first()
            if membership is None:
                raise TeacherNotFoundError(
                    f"No teacher membership for {teacher_uuid} in school {school_uuid}"
                )
            owned = list(
                session.scalars(
                    select(SchoolClass).where(
                        SchoolClass.school_id == school_uuid,
                        SchoolClass.teacher_id == teacher_uuid,
                    )
                ).all()
            )
            if owned and target_uuid is None:
                raise ClassesWouldBeOrphanedError(len(owned))
            if target_uuid is not None:
                if target_uuid == teacher_uuid:
                    raise InvalidReassignmentError(
                        "Cannot reassign a teacher's classes to themselves"
                    )
                self._assert_teacher_of(session, target_uuid, school_uuid)
                for school_class in owned:
                    school_class.teacher_id = target_uuid
            session.delete(membership)
            return len(owned)

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
            raise SchoolOwnershipError(f"Caller does not administer school {school_uuid}")

    def _assert_teacher_of(
        self, session: Session, teacher_uuid: uuid.UUID, school_uuid: uuid.UUID
    ) -> None:
        stmt = select(SchoolMembership.id).where(
            SchoolMembership.user_id == teacher_uuid,
            SchoolMembership.school_id == school_uuid,
            SchoolMembership.membership_role == MembershipRole.teacher,
        )
        if session.scalars(stmt).first() is None:
            raise InvalidReassignmentError(
                f"{teacher_uuid} is not a teacher in school {school_uuid}"
            )

    def _counts_for(self, session: Session, school_uuid: uuid.UUID) -> SchoolCounts:
        school = session.get(School, school_uuid)
        if school is None:  # pragma: no cover - ids come from live memberships
            raise SchoolOwnershipError(f"Unknown school: {school_uuid}")
        teacher_count = int(
            session.scalar(
                select(func.count())
                .select_from(SchoolMembership)
                .where(
                    SchoolMembership.school_id == school_uuid,
                    SchoolMembership.membership_role == MembershipRole.teacher,
                )
            )
            or 0
        )
        class_count = int(
            session.scalar(
                select(func.count())
                .select_from(SchoolClass)
                .where(SchoolClass.school_id == school_uuid)
            )
            or 0
        )
        # DISTINCT because a student enrolled in two of the school's classes is
        # one student on the roll, not two.
        student_ids = list(
            session.scalars(
                select(ClassEnrollment.student_id)
                .join(SchoolClass, SchoolClass.id == ClassEnrollment.class_id)
                .where(SchoolClass.school_id == school_uuid)
                .distinct()
            ).all()
        )
        return SchoolCounts(
            school_id=school.id,
            school_name=school.name,
            teacher_count=teacher_count,
            class_count=class_count,
            student_ids=student_ids,
        )

    def _teachers_for(self, session: Session, school_uuid: uuid.UUID) -> SchoolTeachers:
        school = session.get(School, school_uuid)
        if school is None:  # pragma: no cover - ids come from live memberships
            raise SchoolOwnershipError(f"Unknown school: {school_uuid}")
        # Membership is the roster, not `users.role`: a teacher account exists
        # platform-wide, but it is a member of *this* school only via the join
        # row. Filtering on Role.teacher as well guards the one inconsistency the
        # schema permits — a membership row pointing at a non-teacher account.
        staff = list(
            session.execute(
                select(User.id, User.email, User.display_name)
                .join(SchoolMembership, SchoolMembership.user_id == User.id)
                .where(
                    SchoolMembership.school_id == school_uuid,
                    SchoolMembership.membership_role == MembershipRole.teacher,
                    User.role == Role.teacher,
                )
                .order_by(User.display_name, User.email)
            ).all()
        )
        teacher_ids = [row[0] for row in staff]
        classes_by_teacher = self._class_counts_by_teacher(session, school_uuid, teacher_ids)
        students_by_teacher = self._student_counts_by_teacher(session, school_uuid, teacher_ids)
        return SchoolTeachers(
            school_id=school.id,
            school_name=school.name,
            teachers=[
                TeacherRow(
                    user_id=user_id,
                    email=email,
                    display_name=display_name,
                    class_count=classes_by_teacher.get(user_id, 0),
                    student_count=students_by_teacher.get(user_id, 0),
                )
                for user_id, email, display_name in staff
            ],
        )

    def _class_counts_by_teacher(
        self, session: Session, school_uuid: uuid.UUID, teacher_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, int]:
        if not teacher_ids:
            return {}
        stmt = (
            select(SchoolClass.teacher_id, func.count())
            .where(
                SchoolClass.school_id == school_uuid,
                SchoolClass.teacher_id.in_(teacher_ids),
            )
            .group_by(SchoolClass.teacher_id)
        )
        return {teacher_id: int(count) for teacher_id, count in session.execute(stmt).all()}

    def _student_counts_by_teacher(
        self, session: Session, school_uuid: uuid.UUID, teacher_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, int]:
        """Distinct students per teacher, across that teacher's classes here.

        DISTINCT for the same reason as :meth:`_counts_for`: a student taught by
        one teacher in two classes is one student that teacher is responsible
        for. Summing per-class rosters would double-count them.
        """
        if not teacher_ids:
            return {}
        stmt = (
            select(
                SchoolClass.teacher_id,
                func.count(func.distinct(ClassEnrollment.student_id)),
            )
            .join(ClassEnrollment, ClassEnrollment.class_id == SchoolClass.id)
            .where(
                SchoolClass.school_id == school_uuid,
                SchoolClass.teacher_id.in_(teacher_ids),
            )
            .group_by(SchoolClass.teacher_id)
        )
        return {teacher_id: int(count) for teacher_id, count in session.execute(stmt).all()}


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    """Coerce a str/UUID to :class:`uuid.UUID`, raising ``ValueError`` if invalid."""
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Identifier must be a UUID, got {value!r}") from exc


__all__ = [
    "ClassesWouldBeOrphanedError",
    "InvalidReassignmentError",
    "InviteTeacherResult",
    "SchoolAdminError",
    "SchoolAdminService",
    "SchoolCounts",
    "SchoolOwnershipError",
    "SchoolTeachers",
    "TeacherAccountCreator",
    "TeacherNotFoundError",
    "TeacherRow",
]
