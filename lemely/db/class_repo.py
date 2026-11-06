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

**The roster side door (tutoring SPEC §c.4, decision row 14 = SC-2).** A
teacher who met a student through the tutoring marketplace could see that
student's progress through a school-less class's roster, with no grant, no
audit row and no way out (THREAT-MODEL XT-1). So, without changing who may
call any route:

* a new enrolment in a school-less class whose teacher holds a tutor profile
  queues a ``class_joined_tutor`` email to each of the student's linked parents
  in the enrolment's transaction (:meth:`ClassService.join_by_code_with_notice`;
  the router sends the inbox notices after commit);
* a student may leave a school-less class (:meth:`ClassService.leave_school_less_class`);
* the block, suspension and close sweeps remove a teacher's school-less
  enrolments (:meth:`ClassService.remove_school_less_enrolments_in_session` for
  named students, :meth:`ClassService.remove_all_school_less_enrolments_in_session`
  for every student);
* a student can list the teachers who see their progress through a class
  (:meth:`ClassService.class_access_for_student`).

School classes are never touched by any of these: the school, not the
student, decides who teaches there.
"""

from __future__ import annotations

import secrets
import unicodedata
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from sqlalchemy import and_, delete, func, or_, select, true
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from lemely.core.tutor_directory import public_name
from lemely.db.email_outbox_repo import enqueue_in_session
from lemely.db.models import ClassEnrollment, School, SchoolClass, SchoolMembership, Seat, User
from lemely.db.models.enums import MembershipRole, Role, SeatStatus
from lemely.db.models.tutoring import TutorBooking, TutorDataGrant, TutorProfile
from lemely.db.parent_repo import ParentLinkService

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy import ColumnElement
    from sqlalchemy.orm import Session, sessionmaker

#: The teacher name S16 shows when the account's display name is blank or holds an
#: address (no tutoring DTO carries a ``users.email`` value, SPEC §c.3 O29).
UNNAMED_TEACHER: Final = "Your teacher"


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


@dataclass(frozen=True, slots=True)
class TutorClassJoin:
    """A new enrolment in a school-less class whose teacher holds a tutor profile (SC-2d).

    What the router needs for the after-commit ``tutor_access`` notices: the
    enrolment (the notice's dedupe key), the student, the tutor's public name
    and the parents linked when the enrolment committed, who are the same
    parents its ``class_joined_tutor`` outbox rows were written for.
    """

    enrollment_id: uuid.UUID
    student_id: uuid.UUID
    tutor_name: str
    linked_parent_ids: tuple[uuid.UUID, ...]


@dataclass(frozen=True, slots=True)
class ClassJoinOutcome:
    """What one join by code did: the class, whether it enrolled anyone, and the notice."""

    row: ClassRow
    newly_enrolled: bool
    tutor_join: TutorClassJoin | None


@dataclass(frozen=True, slots=True)
class ClassAccessItem:
    """S16: one class whose teacher sees the student's progress through its roster (SC-2e).

    ``leavable`` is true exactly for a school-less class (S17).
    ``teacher_is_your_tutor`` is true when the class teacher holds a tutor
    profile with which the student has any booking or any grant, current or
    ended (XT-2): computed for the student only, never shown to the teacher.
    """

    class_id: uuid.UUID
    class_name: str
    teacher_name: str
    school_name: str | None
    leavable: bool
    teacher_is_your_tutor: bool


class ClassService:
    """Class CRUD, roster management, and dual enrolment (join code / seat).

    Constructed with a ``sessionmaker`` (mirroring
    :class:`~lemely.db.seat_repo.SeatService`). Every method re-verifies
    ownership before touching any row; there is no super-role bypass.
    """

    def __init__(self, sessionmaker: sessionmaker[Session]) -> None:
        """Wire the service to a session factory.

        Builds its own :class:`~lemely.db.parent_repo.ParentLinkService` on the
        same factory: the class-join notice reads a student's linked parents
        through that service (the single ``parent_child_links`` query), inside
        the enrolment's transaction.
        """
        self._sessionmaker = sessionmaker
        self._parent_links = ParentLinkService(sessionmaker)

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

    def class_access_for_student(self, student_id: uuid.UUID | str) -> list[ClassAccessItem]:
        """S16: every class the student is enrolled in, with who teaches it (SC-2e, O25).

        Each class's teacher sees the student's progress through the roster,
        so the list is exactly the student's enrolments, ordered by class name
        then id, in one statement. The teacher's name never falls back to an
        address (:func:`_teacher_label`).
        """
        student_uuid = _as_uuid(student_id)
        is_your_tutor = or_(
            select(TutorBooking.id)
            .where(
                TutorBooking.tutor_profile_id == TutorProfile.id,
                TutorBooking.student_id == student_uuid,
            )
            .exists(),
            select(TutorDataGrant.id)
            .where(
                TutorDataGrant.tutor_profile_id == TutorProfile.id,
                TutorDataGrant.student_id == student_uuid,
            )
            .exists(),
        )
        stmt = (
            select(
                SchoolClass.id,
                SchoolClass.name,
                SchoolClass.school_id,
                School.name,
                User.display_name,
                TutorProfile.public_first_name,
                TutorProfile.public_last_initial,
                and_(TutorProfile.id.is_not(None), is_your_tutor).label("is_your_tutor"),
            )
            .join(ClassEnrollment, ClassEnrollment.class_id == SchoolClass.id)
            .join(User, User.id == SchoolClass.teacher_id)
            .outerjoin(School, School.id == SchoolClass.school_id)
            .outerjoin(TutorProfile, TutorProfile.user_id == SchoolClass.teacher_id)
            .where(ClassEnrollment.student_id == student_uuid)
            .order_by(SchoolClass.name, SchoolClass.id)
        )
        with self._sessionmaker() as session:
            return [
                ClassAccessItem(
                    class_id=class_id,
                    class_name=class_name,
                    teacher_name=_teacher_label(display_name, first_name, last_initial),
                    school_name=school_name,
                    leavable=school_id is None,
                    teacher_is_your_tutor=bool(your_tutor),
                )
                for (
                    class_id,
                    class_name,
                    school_id,
                    school_name,
                    display_name,
                    first_name,
                    last_initial,
                    your_tutor,
                ) in session.execute(stmt).all()
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

        The same enrolment as :meth:`join_by_code_with_notice`, which this
        delegates to, so the tutoring class-join outbox rows are written here
        too: no entry point enrols a student in a tutor's school-less class
        without telling their parents (SPEC §c.4, SC-2d). Only the after-commit
        inbox notices are left out; the routes use the ``_with_notice`` form.

        Raises:
            JoinCodeError: No class carries ``join_code``.
        """
        return self.join_by_code_with_notice(student_id, join_code).row

    def join_by_code_outcome(
        self, student_id: uuid.UUID | str, join_code: str
    ) -> tuple[ClassRow, bool]:
        """Self-enrol via a join code: ``(class, newly_enrolled)``. Idempotent.

        The same enrolment and tutoring class-join outbox rows as
        :meth:`join_by_code_with_notice`, which this delegates to.
        ``newly_enrolled`` is ``False`` when the student was already in the
        class.

        Raises:
            JoinCodeError: No class carries ``join_code``.
        """
        outcome = self.join_by_code_with_notice(student_id, join_code)
        return outcome.row, outcome.newly_enrolled

    def join_by_code_with_notice(
        self, student_id: uuid.UUID | str, join_code: str
    ) -> ClassJoinOutcome:
        """Self-enrol via a join code and queue the tutoring class-join emails. Idempotent.

        Identity is always the authenticated student (never a caller-supplied
        id, per D1.6). The enrolment is an ``INSERT … ON CONFLICT DO NOTHING``,
        so "newly enrolled" is exact even when two joins race. When it is new,
        the class has no school and its teacher holds a tutor profile, a
        ``class_joined_tutor`` email is queued for each of the student's linked
        parents in the same transaction (SPEC §c.4, SC-2d), and
        :attr:`ClassJoinOutcome.tutor_join` carries what the router's
        after-commit inbox notices need. Any profile state counts: owning a
        tutor profile is the fact that makes the class a side door. A re-join,
        a school class and a teacher without a profile tell nobody.

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
            enrollment_id = session.scalars(
                pg_insert(ClassEnrollment)
                .values(class_id=cls.id, student_id=student_uuid)
                .on_conflict_do_nothing(index_elements=["class_id", "student_id"])
                .returning(ClassEnrollment.id)
            ).first()
            tutor_join = None
            if enrollment_id is not None and cls.school_id is None:
                tutor_join = self._queue_tutor_class_join(
                    session, cls.teacher_id, student_uuid, enrollment_id
                )
            return ClassJoinOutcome(
                row=self._to_class_row(session, cls),
                newly_enrolled=enrollment_id is not None,
                tutor_join=tutor_join,
            )

    def leave_school_less_class(
        self, student_id: uuid.UUID | str, class_id: uuid.UUID | str
    ) -> bool:
        """Remove the student's own enrolment from a school-less class (S17, SC-2c, O24).

        ``True`` when an enrolment was removed. ``False`` (nothing written) when
        the class does not exist, has a school, or the student is not in it:
        the route answers all three with the same 404. Only the caller's own
        row can match, because ``student_id`` is always ``auth.user_id``.
        """
        student_uuid = _as_uuid(student_id)
        class_uuid = _as_uuid(class_id)
        school_less = select(SchoolClass.id).where(
            SchoolClass.id == class_uuid, SchoolClass.school_id.is_(None)
        )
        with self._sessionmaker() as session, session.begin():
            removed = session.scalars(
                delete(ClassEnrollment)
                .where(
                    ClassEnrollment.student_id == student_uuid,
                    ClassEnrollment.class_id.in_(school_less),
                )
                .returning(ClassEnrollment.id)
                .execution_options(synchronize_session=False)
            ).first()
            return removed is not None

    def remove_school_less_enrolments_in_session(
        self,
        session: Session,
        *,
        teacher_user_id: uuid.UUID,
        student_ids: Sequence[uuid.UUID],
    ) -> int:
        """Delete these students' enrolments in ``teacher_user_id``'s school-less classes.

        For the safeguarding sweeps (SPEC §c.4, SC-2 a and b), inside the
        caller's transaction: a block passes the one blocked student, a
        suspension the students who ever booked or granted the tutor. Returns
        the count removed. An empty sequence removes nothing: it never widens
        to every student (that sweep is
        :meth:`remove_all_school_less_enrolments_in_session`, by name). Classes
        with a school, and other teachers' classes, are never touched.
        """
        if not student_ids:
            return 0
        return self._delete_school_less_enrolments(
            session,
            teacher_user_id,
            ClassEnrollment.student_id.in_(list(student_ids)),
        )

    def remove_all_school_less_enrolments_in_session(
        self, session: Session, *, teacher_user_id: uuid.UUID
    ) -> int:
        """Delete every enrolment in ``teacher_user_id``'s school-less classes; the count removed.

        For a sweep that removes every student, such as a close (SPEC §c.4,
        SC-2), inside the caller's transaction. Classes with a school, and
        other teachers' classes, are never touched.
        """
        return self._delete_school_less_enrolments(session, teacher_user_id, true())

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

    def _delete_school_less_enrolments(
        self,
        session: Session,
        teacher_user_id: uuid.UUID,
        students: ColumnElement[bool],
    ) -> int:
        """Delete the ``students`` enrolments in the teacher's school-less classes; the count."""
        teacher_school_less = select(SchoolClass.id).where(
            SchoolClass.teacher_id == teacher_user_id, SchoolClass.school_id.is_(None)
        )
        removed = session.scalars(
            delete(ClassEnrollment)
            .where(ClassEnrollment.class_id.in_(teacher_school_less), students)
            .returning(ClassEnrollment.id)
            .execution_options(synchronize_session=False)
        ).all()
        return len(removed)

    def _queue_tutor_class_join(
        self,
        session: Session,
        teacher_id: uuid.UUID,
        student_id: uuid.UUID,
        enrollment_id: uuid.UUID,
    ) -> TutorClassJoin | None:
        """Queue each linked parent's ``class_joined_tutor`` email; ``None`` without a profile."""
        profile = session.execute(
            select(TutorProfile.public_first_name, TutorProfile.public_last_initial).where(
                TutorProfile.user_id == teacher_id
            )
        ).first()
        if profile is None:
            return None
        first_name, last_initial = profile
        parents = tuple(self._parent_links.linked_parent_ids_in_session(session, student_id))
        for parent in parents:
            enqueue_in_session(
                session,
                recipient_user_id=parent,
                template="class_joined_tutor",
                context={
                    "tutor_first_name": first_name,
                    "tutor_last_initial": last_initial,
                    "enrollment_id": enrollment_id,
                    "child_id": student_id,
                },
                dedupe_key=f"class-join:{enrollment_id}:{parent}",
            )
        return TutorClassJoin(
            enrollment_id=enrollment_id,
            student_id=student_id,
            tutor_name=public_name(first_name, last_initial),
            linked_parent_ids=parents,
        )

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


def _teacher_label(
    display_name: str | None, tutor_first_name: str | None, tutor_last_initial: str | None
) -> str:
    """The class teacher's name for S16, never an address (SPEC §c.3 O29).

    The display name with format characters removed, when it is not blank and
    holds no ``@`` (after compatibility folding); otherwise the tutor's public
    name when the teacher holds a profile; otherwise :data:`UNNAMED_TEACHER`.
    Unlike the rest of this module, never the ``display_name or email``
    fallback.
    """
    name = "".join(c for c in (display_name or "") if unicodedata.category(c) != "Cf").strip()
    if name and "@" not in unicodedata.normalize("NFKC", name):
        return name
    if tutor_first_name:
        return public_name(tutor_first_name, tutor_last_initial)
    return UNNAMED_TEACHER


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
    "UNNAMED_TEACHER",
    "ClassAccessItem",
    "ClassError",
    "ClassHasNoSchoolError",
    "ClassJoinOutcome",
    "ClassNotFoundError",
    "ClassOwnershipError",
    "ClassRow",
    "ClassService",
    "JoinCodeError",
    "RosterEntry",
    "StudentClassRow",
    "StudentNotSeatedError",
    "TutorClassJoin",
]
