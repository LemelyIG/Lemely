"""Class model service — teacher-owned classes, rosters, and enrolment (D3.1).

Mirrors :mod:`lemely.db.seat_repo`'s shape directly: pure ownership/CRUD logic
over a ``sessionmaker``, domain errors mapped to HTTP status codes by a thin
router layer, testable against Postgres with no GoTrue dependency.

Ownership (this is D1.6's deferred row-level teacher tenancy, landed here):

* ``teacher`` sees and mutates **only** classes where ``classes.teacher_id ==
  caller``. A class the caller does not own is a
  :class:`ClassOwnershipError` (403) carrying no data — though the 403-vs-404
  split does leak whether an id exists at all; see ``user_exists``.
* ``school_admin`` sees classes whose ``school_id`` is a school they hold a
  ``school_admin`` :class:`~lemely.db.models.orgs.SchoolMembership` for
  (read + roster management — they do not create/update/delete classes,
  which stay teacher-owned).
* ``platform_admin`` sees **no** classes. No super-role bypass, mirroring
  :class:`~lemely.db.seat_repo.SeatService`.

Two enrolment paths (MISSION §4 P3.1): a join code (self-enrolment, the only
path available to an independent teacher's class, which has no seat pool) and
a direct add against an existing, non-revoked school :class:`Seat` (only
possible when the class has a ``school_id``).
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from lemely.db.models import ClassEnrollment, School, SchoolClass, SchoolMembership, Seat, User
from lemely.db.models.enums import MembershipRole, Role, SeatStatus

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker


class ClassError(Exception):
    """Base class for class-model failures."""


class ClassOwnershipError(ClassError):
    """The caller does not own/administer the target class (→ 403)."""


class ClassNotFoundError(ClassError):
    """No class exists for the supplied id (→ 404)."""


class ClassHasNoSchoolError(ClassError):
    """The class has no ``school_id``, so it has no seat pool (→ 409)."""


class StudentNotSeatedError(ClassError):
    """The student holds no non-revoked seat in the class's school (→ 409)."""


class JoinCodeError(ClassError):
    """No class exists for the supplied join code (→ 404)."""


# Alphabet excludes visually-ambiguous characters (0/O, 1/I/L) so a student can
# reliably transcribe a code read off a whiteboard.
_JOIN_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_JOIN_CODE_LENGTH = 7
_JOIN_CODE_MAX_ATTEMPTS = 8


@dataclass(frozen=True, slots=True)
class ClassRow:
    """A single class with its owner, optional school, and enrolled-student count."""

    class_id: uuid.UUID
    teacher_id: uuid.UUID
    school_id: uuid.UUID | None
    name: str
    subject_code: str | None
    join_code: str | None
    student_count: int


@dataclass(frozen=True, slots=True)
class RosterEntry:
    """One enrolled student: identity only (no history/analytics)."""

    student_id: uuid.UUID
    display_name: str


@dataclass(frozen=True, slots=True)
class StudentClassRow:
    """One class a student is enrolled in, with its name and school (P3.6).

    Unlike :class:`RosterEntry` (a class's students), this is a student's
    classes — the direction :meth:`~ClassService.student_classes` serves.
    ``school_name`` is ``None`` for an independent teacher's class (no
    ``school_id``), never a fabricated placeholder.
    """

    class_id: uuid.UUID
    name: str
    subject_code: str | None
    school_name: str | None


class ClassService:
    """Class CRUD, roster management, and dual enrolment (join code / seat).

    Constructed with a ``sessionmaker`` (mirroring
    :class:`~lemely.db.seat_repo.SeatService`). Every method re-verifies
    ownership before touching any row; there is no super-role bypass.
    """

    def __init__(self, sessionmaker: sessionmaker[Session]) -> None:
        """Wire the service to a session factory."""
        self._sessionmaker = sessionmaker

    # -- Introspection ------------------------------------------------------

    def list_classes(self, caller_id: uuid.UUID | str, caller_role: Role | str) -> list[ClassRow]:
        """Return every class the caller may see, scoped by role.

        ``teacher`` gets their own classes; ``school_admin`` gets classes in
        schools they administer; ``platform_admin`` always gets an empty list
        (no super-role — a dedicated admin surface reaches class data later).
        """
        caller_uuid = _as_uuid(caller_id)
        role = _normalize_role(caller_role)
        with self._sessionmaker() as session:
            if role == Role.teacher:
                stmt = (
                    select(SchoolClass)
                    .where(SchoolClass.teacher_id == caller_uuid)
                    .order_by(SchoolClass.created_at)
                )
            elif role == Role.school_admin:
                school_ids = self._admin_school_ids(session, caller_uuid)
                if not school_ids:
                    return []
                stmt = (
                    select(SchoolClass)
                    .where(SchoolClass.school_id.in_(school_ids))
                    .order_by(SchoolClass.created_at)
                )
            else:
                return []
            rows = session.scalars(stmt).all()
            return [self._to_class_row(session, row) for row in rows]

    def get_class(
        self, caller_id: uuid.UUID | str, caller_role: Role | str, class_id: uuid.UUID | str
    ) -> ClassRow:
        """Return one class, scoped by role.

        Raises:
            ClassNotFoundError: No class exists with ``class_id`` (anywhere).
            ClassOwnershipError: The class exists but is outside the caller's
                scope — never data, and this is checked identically regardless
                of *why* it is out of scope (wrong teacher, wrong school,
                platform_admin's always-empty scope).
        """
        caller_uuid = _as_uuid(caller_id)
        class_uuid = _as_uuid(class_id)
        with self._sessionmaker() as session:
            cls = session.get(SchoolClass, class_uuid)
            if cls is None:
                raise ClassNotFoundError(f"Unknown class: {class_uuid}")
            self._assert_scope(session, caller_uuid, caller_role, cls)
            return self._to_class_row(session, cls)

    def roster(
        self, caller_id: uuid.UUID | str, caller_role: Role | str, class_id: uuid.UUID | str
    ) -> list[RosterEntry]:
        """Return a class's enrolled students, scoped by role.

        Raises:
            ClassNotFoundError: No class exists with ``class_id``.
            ClassOwnershipError: The caller may not see this class's roster.
        """
        caller_uuid = _as_uuid(caller_id)
        class_uuid = _as_uuid(class_id)
        with self._sessionmaker() as session:
            cls = session.get(SchoolClass, class_uuid)
            if cls is None:
                raise ClassNotFoundError(f"Unknown class: {class_uuid}")
            self._assert_scope(session, caller_uuid, caller_role, cls)
            return self._roster_entries(session, class_uuid)

    def member_school_ids(self, user_id: uuid.UUID | str) -> list[uuid.UUID]:
        """Return every school id ``user_id`` holds *any* membership in.

        Unlike ``_admin_school_ids`` (``school_admin`` only), this includes
        both :class:`~lemely.db.models.enums.MembershipRole` values — used by
        :func:`~lemely.db.question_bank_repo.visible_bank_filter` (D3.6 §1.3),
        where a plain teacher's own school membership, not just an admin's,
        is what makes a school-shared question-bank row visible to them.
        """
        user_uuid = _as_uuid(user_id)
        with self._sessionmaker() as session:
            stmt = (
                select(SchoolMembership.school_id)
                .where(SchoolMembership.user_id == user_uuid)
                .order_by(SchoolMembership.school_id)
            )
            return list(session.scalars(stmt).all())

    def enrolled_class_ids(self, student_id: uuid.UUID | str) -> list[uuid.UUID]:
        """Return every class id ``student_id`` is enrolled in, deterministically ordered.

        Modeled on :meth:`member_school_ids`: the single seam
        :class:`~lemely.db.quiz_taking_repo.QuizTakingService` uses for every
        student-side quiz scoping decision (P3.5 chunk E). Do not write a
        second ``ClassEnrollment`` query anywhere else for that purpose — see
        that module's docstring.
        """
        student_uuid = _as_uuid(student_id)
        with self._sessionmaker() as session:
            stmt = (
                select(ClassEnrollment.class_id)
                .where(ClassEnrollment.student_id == student_uuid)
                .order_by(ClassEnrollment.class_id)
            )
            return list(session.scalars(stmt).all())

    def display_name_for(self, user_id: uuid.UUID | str) -> str:
        """Return one user's display name, falling back to their email (P5.6 chunk C2c).

        The same fallback :meth:`_roster_entry_for` and :meth:`roster` already
        apply, deliberately: an ``at_risk_alert`` names a student to their own
        teachers and parents, who are looking at that exact string on their
        roster already, so a second convention here would make one person read
        as two. **This is not D5.5's leak** — that was the *global leaderboard*
        broadcasting an unnamed student's email to strangers, and the audience
        is what made it a leak. An unknown id returns ``"Student"`` rather
        than raising: a missing name must never cost an alert.
        """
        with self._sessionmaker() as session:
            user = session.get(User, _as_uuid(user_id))
            if user is None:
                return "Student"
            return user.display_name or user.email

    def teachers_for_student(self, student_id: uuid.UUID | str) -> list[uuid.UUID]:
        """Return the distinct teachers who teach ``student_id``, ordered (P5.6 chunk C2c).

        The recipient seam for ``at_risk_alert``: a student's teachers are the
        people the alert is *for*. Deliberately its own narrow method rather
        than a field added to :class:`StudentClassRow` — that row is the
        parent portal's shape (P-01/P-02 render class names to a parent) and
        putting a teacher id on it would push staff identity onto a screen
        that has no use for it. ``SchoolClass.teacher_id`` is NOT NULL, so
        every enrolled class yields exactly one teacher; ``distinct`` collapses
        the common case of one teacher taking a student for two classes into
        one alert rather than two.
        """
        student_uuid = _as_uuid(student_id)
        with self._sessionmaker() as session:
            stmt = (
                select(SchoolClass.teacher_id)
                .join(ClassEnrollment, ClassEnrollment.class_id == SchoolClass.id)
                .where(ClassEnrollment.student_id == student_uuid)
                .distinct()
                .order_by(SchoolClass.teacher_id)
            )
            return list(session.scalars(stmt).all())

    def student_classes(self, student_id: uuid.UUID | str) -> list[StudentClassRow]:
        """Return every class ``student_id`` is enrolled in, with names (P3.6).

        Unlike :meth:`enrolled_class_ids` (ids only, the seam
        :class:`~lemely.db.quiz_taking_repo.QuizTakingService` uses for
        student quiz scoping), this joins :class:`SchoolClass` — and
        :class:`~lemely.db.models.orgs.School`, when the class has a
        ``school_id`` — so a caller can render "which classes, with names"
        without a second, independently-derived roster query. Both the
        parent-portal home (P-01) and child-overview (P-02) screens call this
        one method; do not write a second ``ClassEnrollment`` query anywhere
        else for that purpose.
        """
        student_uuid = _as_uuid(student_id)
        with self._sessionmaker() as session:
            stmt = (
                select(SchoolClass, School.name)
                .join(ClassEnrollment, ClassEnrollment.class_id == SchoolClass.id)
                .outerjoin(School, School.id == SchoolClass.school_id)
                .where(ClassEnrollment.student_id == student_uuid)
                .order_by(SchoolClass.name)
            )
            return [
                StudentClassRow(
                    class_id=cls.id,
                    name=cls.name,
                    subject_code=cls.subject_code,
                    school_name=school_name,
                )
                for cls, school_name in session.execute(stmt).all()
            ]

    def user_exists(self, user_id: uuid.UUID | str) -> bool:
        """Return whether any user exists with ``user_id``.

        Deliberately carries no ownership/tenancy check — this exists purely
        so a caller (the teacher-portal student-detail route, P3.3) can
        distinguish "no such user anywhere" (404) from "exists, but outside my
        classes" (403) rather than collapsing the two into one response.

        That distinction is, precisely, a user-existence oracle, and this
        method is the thing that makes it possible. It leaks one bit
        (does this uuid belong to a user?) to any authenticated staff caller
        and no data whatsoever. Accepted because ids are random 122-bit
        UUIDs; see ``teacher_student_detail``'s docstring for the full
        rationale. Do not widen this method to return anything about the
        user — the one bit is the entire contract.
        """
        user_uuid = _as_uuid(user_id)
        with self._sessionmaker() as session:
            return session.get(User, user_uuid) is not None

    # -- CRUD (owner-scoped: the creating teacher only) ----------------------

    def create_class(
        self,
        teacher_id: uuid.UUID | str,
        name: str,
        subject_code: str | None = None,
        school_id: uuid.UUID | str | None = None,
    ) -> ClassRow:
        """Create a class owned by ``teacher_id``, generating a unique join code.

        ``school_id`` is only accepted when the caller holds *any*
        :class:`~lemely.db.models.orgs.SchoolMembership` for that school — an
        independent teacher passes ``None`` (MISSION §1: "a teacher can be
        independent, belong to a school, or both").

        Raises:
            ClassOwnershipError: ``school_id`` was supplied but the caller
                holds no membership there.
            ClassError: A unique join code could not be generated after
                several attempts (astronomically unlikely; see
                :data:`_JOIN_CODE_MAX_ATTEMPTS`).
        """
        teacher_uuid = _as_uuid(teacher_id)
        school_uuid = _as_uuid(school_id) if school_id is not None else None
        with self._sessionmaker() as session:
            if school_uuid is not None:
                self._assert_member_of(session, teacher_uuid, school_uuid)
            for _ in range(_JOIN_CODE_MAX_ATTEMPTS):
                cls = SchoolClass(
                    teacher_id=teacher_uuid,
                    school_id=school_uuid,
                    name=name,
                    subject_code=subject_code,
                    join_code=_generate_join_code(),
                )
                session.add(cls)
                try:
                    session.commit()
                except IntegrityError:
                    session.rollback()
                    continue
                session.refresh(cls)
                return self._to_class_row(session, cls)
            raise ClassError("Could not generate a unique join code; please retry")

    def update_class(
        self,
        teacher_id: uuid.UUID | str,
        class_id: uuid.UUID | str,
        name: str | None = None,
        subject_code: str | None = None,
    ) -> ClassRow:
        """Rename a class and/or change its subject code. Owner-scoped.

        Raises:
            ClassNotFoundError: No class exists with ``class_id``.
            ClassOwnershipError: ``teacher_id`` does not own the class.
        """
        teacher_uuid = _as_uuid(teacher_id)
        class_uuid = _as_uuid(class_id)
        with self._sessionmaker() as session, session.begin():
            cls = session.get(SchoolClass, class_uuid, with_for_update=True)
            if cls is None:
                raise ClassNotFoundError(f"Unknown class: {class_uuid}")
            if cls.teacher_id != teacher_uuid:
                raise ClassOwnershipError(f"Caller does not own class {class_uuid}")
            if name is not None:
                cls.name = name
            if subject_code is not None:
                cls.subject_code = subject_code
            session.flush()
            return self._to_class_row(session, cls)

    def delete_class(self, teacher_id: uuid.UUID | str, class_id: uuid.UUID | str) -> None:
        """Delete a class (cascades to its enrolments). Owner-scoped.

        Raises:
            ClassNotFoundError: No class exists with ``class_id``.
            ClassOwnershipError: ``teacher_id`` does not own the class.
        """
        teacher_uuid = _as_uuid(teacher_id)
        class_uuid = _as_uuid(class_id)
        with self._sessionmaker() as session, session.begin():
            cls = session.get(SchoolClass, class_uuid)
            if cls is None:
                raise ClassNotFoundError(f"Unknown class: {class_uuid}")
            if cls.teacher_id != teacher_uuid:
                raise ClassOwnershipError(f"Caller does not own class {class_uuid}")
            session.delete(cls)

    # -- Enrolment ------------------------------------------------------------

    def enroll_by_seat(
        self,
        caller_id: uuid.UUID | str,
        caller_role: Role | str,
        class_id: uuid.UUID | str,
        student_id: uuid.UUID | str,
    ) -> RosterEntry:
        """Enrol a seated student directly. Idempotent.

        Raises:
            ClassNotFoundError: No class exists with ``class_id``.
            ClassOwnershipError: The caller may not manage this class's roster.
            ClassHasNoSchoolError: The class has no ``school_id`` (an
                independent teacher's class has no seat pool by construction).
            StudentNotSeatedError: The student holds no non-revoked seat in the
                class's school.
        """
        caller_uuid = _as_uuid(caller_id)
        class_uuid = _as_uuid(class_id)
        student_uuid = _as_uuid(student_id)
        with self._sessionmaker() as session, session.begin():
            cls = session.get(SchoolClass, class_uuid, with_for_update=True)
            if cls is None:
                raise ClassNotFoundError(f"Unknown class: {class_uuid}")
            self._assert_scope(session, caller_uuid, caller_role, cls)
            if cls.school_id is None:
                raise ClassHasNoSchoolError(f"Class {class_uuid} has no school; no seat pool")
            seat_stmt = select(Seat.id).where(
                Seat.school_id == cls.school_id,
                Seat.assigned_user_id == student_uuid,
                Seat.status != SeatStatus.revoked,
            )
            if session.scalars(seat_stmt).first() is None:
                raise StudentNotSeatedError(
                    f"Student {student_uuid} holds no active seat in school {cls.school_id}"
                )
            self._enrol_if_absent(session, class_uuid, student_uuid)
            return self._roster_entry_for(session, student_uuid)

    def join_by_code(self, student_id: uuid.UUID | str, join_code: str) -> ClassRow:
        """Self-enrol a student via a class's join code. Idempotent.

        Identity is always the authenticated student (never a caller-supplied
        id, per D1.6) — the router passes ``auth.user_id``.

        Raises:
            JoinCodeError: No class carries ``join_code``.
        """
        student_uuid = _as_uuid(student_id)
        with self._sessionmaker() as session, session.begin():
            cls = session.scalars(
                select(SchoolClass).where(SchoolClass.join_code == join_code)
            ).first()
            if cls is None:
                raise JoinCodeError("Unknown join code")
            self._enrol_if_absent(session, cls.id, student_uuid)
            return self._to_class_row(session, cls)

    def remove_student(
        self,
        caller_id: uuid.UUID | str,
        caller_role: Role | str,
        class_id: uuid.UUID | str,
        student_id: uuid.UUID | str,
    ) -> None:
        """Remove a student from a class's roster. Owner/admin-scoped, idempotent.

        Raises:
            ClassNotFoundError: No class exists with ``class_id``.
            ClassOwnershipError: The caller may not manage this class's roster.
        """
        caller_uuid = _as_uuid(caller_id)
        class_uuid = _as_uuid(class_id)
        student_uuid = _as_uuid(student_id)
        with self._sessionmaker() as session, session.begin():
            cls = session.get(SchoolClass, class_uuid)
            if cls is None:
                raise ClassNotFoundError(f"Unknown class: {class_uuid}")
            self._assert_scope(session, caller_uuid, caller_role, cls)
            session.execute(
                delete(ClassEnrollment).where(
                    ClassEnrollment.class_id == class_uuid,
                    ClassEnrollment.student_id == student_uuid,
                )
            )

    # -- Internals ------------------------------------------------------------

    def _enrol_if_absent(
        self, session: Session, class_uuid: uuid.UUID, student_uuid: uuid.UUID
    ) -> None:
        existing = session.scalars(
            select(ClassEnrollment.id).where(
                ClassEnrollment.class_id == class_uuid,
                ClassEnrollment.student_id == student_uuid,
            )
        ).first()
        if existing is None:
            session.add(ClassEnrollment(class_id=class_uuid, student_id=student_uuid))
            session.flush()

    def _assert_scope(
        self,
        session: Session,
        caller_uuid: uuid.UUID,
        caller_role: Role | str,
        cls: SchoolClass,
    ) -> None:
        role = _normalize_role(caller_role)
        if role == Role.teacher:
            if cls.teacher_id != caller_uuid:
                raise ClassOwnershipError(f"Caller does not own class {cls.id}")
            return
        if role == Role.school_admin:
            if cls.school_id is None:
                raise ClassOwnershipError(f"Caller does not administer class {cls.id}")
            self._assert_admin_of(session, caller_uuid, cls.school_id)
            return
        # platform_admin (or anything else): no super-role bypass (D1.6/D1.10).
        raise ClassOwnershipError(f"Caller does not administer class {cls.id}")

    def _assert_admin_of(
        self, session: Session, admin_uuid: uuid.UUID, school_uuid: uuid.UUID
    ) -> None:
        stmt = select(SchoolMembership.id).where(
            SchoolMembership.user_id == admin_uuid,
            SchoolMembership.school_id == school_uuid,
            SchoolMembership.membership_role == MembershipRole.school_admin,
        )
        if session.scalars(stmt).first() is None:
            raise ClassOwnershipError(f"Caller does not administer school {school_uuid}")

    def _assert_member_of(
        self, session: Session, user_uuid: uuid.UUID, school_uuid: uuid.UUID
    ) -> None:
        stmt = select(SchoolMembership.id).where(
            SchoolMembership.user_id == user_uuid,
            SchoolMembership.school_id == school_uuid,
        )
        if session.scalars(stmt).first() is None:
            raise ClassOwnershipError(f"Caller does not belong to school {school_uuid}")

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

    def _roster_entries(self, session: Session, class_uuid: uuid.UUID) -> list[RosterEntry]:
        stmt = (
            select(User.id, User.display_name, User.email)
            .join(ClassEnrollment, ClassEnrollment.student_id == User.id)
            .where(ClassEnrollment.class_id == class_uuid)
            .order_by(User.display_name, User.email)
        )
        return [
            RosterEntry(student_id=uid, display_name=display_name or email)
            for uid, display_name, email in session.execute(stmt).all()
        ]

    def _roster_entry_for(self, session: Session, student_uuid: uuid.UUID) -> RosterEntry:
        user = session.get(User, student_uuid)
        if user is None:  # pragma: no cover - the seat check already loaded this user
            raise ClassError(f"Unknown student: {student_uuid}")
        return RosterEntry(student_id=user.id, display_name=user.display_name or user.email)

    def _to_class_row(self, session: Session, cls: SchoolClass) -> ClassRow:
        count = (
            session.scalar(
                select(func.count())
                .select_from(ClassEnrollment)
                .where(ClassEnrollment.class_id == cls.id)
            )
            or 0
        )
        return ClassRow(
            class_id=cls.id,
            teacher_id=cls.teacher_id,
            school_id=cls.school_id,
            name=cls.name,
            subject_code=cls.subject_code,
            join_code=cls.join_code,
            student_count=int(count),
        )


def _generate_join_code() -> str:
    """Generate a random join code from a non-ambiguous alphabet."""
    return "".join(secrets.choice(_JOIN_CODE_ALPHABET) for _ in range(_JOIN_CODE_LENGTH))


def _normalize_role(role: Role | str) -> Role:
    """Coerce a str/Role to :class:`Role`, raising ``ValueError`` if unknown."""
    if isinstance(role, Role):
        return role
    try:
        return Role(role)
    except ValueError as exc:
        raise ValueError(f"Unknown role: {role!r}") from exc


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    """Coerce a str/UUID to :class:`uuid.UUID`, raising ``ValueError`` if invalid."""
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Identifier must be a UUID, got {value!r}") from exc


__all__ = [
    "ClassError",
    "ClassHasNoSchoolError",
    "ClassNotFoundError",
    "ClassOwnershipError",
    "ClassRow",
    "ClassService",
    "JoinCodeError",
    "RosterEntry",
    "StudentClassRow",
    "StudentNotSeatedError",
]
