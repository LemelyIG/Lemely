"""Platform-admin school provisioning — the account graph's missing first link.

Tracing the account graph (spec §1.1) found a hole: ``D1.7`` reserves elevated
roles for "an authenticated admin via the seat/invite flow", and that flow —
``POST /api/school/teachers/invite``, gated to ``school_admin`` — genuinely
exists. But no production code path created the ``School`` row a
``school_admin`` needs to administer, or the ``school_admin`` account itself.
``grep`` for ``School(`` found the model, eighteen test files, and nothing
else; the only ``school_admin`` ever minted came from ``lemely/db/seed.py``
calling :meth:`~lemely.auth.service.AuthService.signup` directly. So the chain
``platform_admin -> School -> school_admin -> teacher`` had no first link, and
issue #12 was not a missing form — it was a hole in the graph. This module is
that link (D7.8).

**Why this is a new file rather than new methods on**
:class:`~lemely.db.admin_repo.PlatformAdminService`. That service's whole
reason for existing separately from every tenant-scoped service
(``class_repo``, ``seat_repo``, ``school_admin_repo``) is that it
answers **only in aggregate** — counted facts, plus two narrow row lists a
human acts on — and its one mutating route (X-02's activation decision)
decides on a row that already exists. Creating a tenant is a different kind
of operation: it is the one write in the whole product with no owner to check
because the row being created *is* the boundary a later query will scope to.
Reached by its own door, following the same principle
:class:`~lemely.db.admin_repo.PlatformAdminService`'s own docstring states for
itself — a widening flag on an existing service would blur exactly the
line that service exists to keep sharp.

**Ownership, or the deliberate absence of it.** Every method here is reachable
only by ``platform_admin`` (enforced at the router,
``lemely/web/routers/admin.py``), and none of them scope to a caller's own
schools, because a platform admin does not *have* schools (D1.6/D1.10, no
super-role bypass) — they administer the platform, and every school is
equally theirs to see and provision. That is not a gap to close; it is the
same "no tenant scope at all" property :class:`PlatformAdminService` already
documents, extended to writes.

**Creating a school_admin reuses** :meth:`~lemely.auth.service.AuthService.signup`
**at the service layer**, via the injected :class:`SchoolAdminAccountCreator`
seam — exactly the pattern :class:`~lemely.db.seat_repo.StudentAccountCreator`
and :class:`~lemely.db.school_admin_repo.TeacherAccountCreator` already
establish, and exactly what ``seed.py`` does when it seeds the demo
school_admin: call ``signup`` directly, bypassing the router's role guard by
design, because *this* is the authenticated admin surface D1.7 reserves
elevated-role creation for. The seam keeps the pure provisioning logic
(school existence, quota arithmetic, membership) testable against Postgres
without the live GoTrue stack.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from sqlalchemy import func, select

from lemely.db.models import School, SchoolMembership, Seat, User
from lemely.db.models.enums import MembershipRole, Role, SeatStatus

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker


class SchoolProvisioningError(Exception):
    """Base class for platform-admin school-provisioning failures."""


class SchoolNotFoundError(SchoolProvisioningError):
    """No school exists for the supplied id (→ 404)."""


class QuotaBelowAssignedSeatsError(SchoolProvisioningError):
    """The requested quota is below the seats already assigned (→ 409).

    Carries both numbers so the caller can name them without a second query —
    Task 12's own test for this is titled for exactly that requirement: "never
    a silent accept". Lowering a quota under what is already in use would make
    ``used > quota`` true, a state :class:`~lemely.db.seat_repo.SeatService`
    was never written to expect (its ``available`` property assumes the
    quota is always the larger number), so this is refused here rather than
    discovered later as a negative "available seats" figure on a screen.
    """

    def __init__(self, requested_quota: int, seats_assigned: int) -> None:
        """Record both numbers so the caller can name them in one message."""
        super().__init__(
            f"Requested quota {requested_quota} is below the {seats_assigned} "
            "seat(s) already assigned"
        )
        self.requested_quota = requested_quota
        self.seats_assigned = seats_assigned


class SchoolAdminAccountCreator(Protocol):
    """Creates a school_admin identity and returns its ``public.users`` id.

    Mirrors :class:`~lemely.db.school_admin_repo.TeacherAccountCreator` and
    :class:`~lemely.db.seat_repo.StudentAccountCreator` exactly: the real
    implementation (``lemely.web.deps.AuthServiceSchoolAdminCreator``) wraps
    :meth:`~lemely.auth.service.AuthService.signup` pinned to
    :attr:`~lemely.db.models.enums.Role.school_admin`; tests substitute a fake
    that inserts a ``User`` row directly. A dedicated class per role (rather
    than one creator taking a ``role`` argument) is deliberate throughout this
    family: the role a provisioning seam may mint is the security property,
    and a ``role`` parameter is a thing a future caller could pass
    ``platform_admin`` to.
    """

    def create_school_admin(
        self,
        email: str,
        password: str,
        display_name: str | None = None,
    ) -> uuid.UUID:
        """Create a school_admin account and return its user id."""
        ...


@dataclass(frozen=True, slots=True)
class SchoolAdminRow:
    """One school_admin staffing a school, for the roster on the schools list."""

    user_id: uuid.UUID
    email: str
    display_name: str | None


@dataclass(frozen=True, slots=True)
class SchoolSummary:
    """One school's provisioning state: quota, seat usage, and its admins.

    ``seats_assigned`` counts non-revoked :class:`~lemely.db.models.orgs.Seat`
    rows — the identical predicate :meth:`~lemely.db.seat_repo.SeatService`
    uses for its own "used" figure — so a seat count never means two different
    things depending on which screen reads it.
    """

    school_id: uuid.UUID
    name: str
    seat_quota: int
    seats_assigned: int
    admins: list[SchoolAdminRow]

    @property
    def seats_available(self) -> int:
        """Free seats remaining against the quota (never negative)."""
        return max(0, self.seat_quota - self.seats_assigned)


@dataclass(frozen=True, slots=True)
class CreateSchoolAdminResult:
    """The created school_admin's identity and the membership binding them.

    Both ids are returned — never just the user id — because the membership is
    the other half of the guarantee this module exists to make: a
    school_admin with no membership administers nothing (see the module
    docstring and D4.10).
    """

    user_id: uuid.UUID
    membership_id: uuid.UUID
    email: str


class SchoolProvisioningService:
    """Creates and administers ``School`` rows and their ``school_admin`` staff.

    Constructed with a ``sessionmaker`` and a :class:`SchoolAdminAccountCreator`,
    mirroring :class:`~lemely.db.seat_repo.SeatService` and
    :class:`~lemely.db.school_admin_repo.SchoolAdminService`. Unlike either of
    those, no method here takes a caller/admin id to scope against — see the
    module docstring on why ``platform_admin`` has no tenant to scope to.
    """

    def __init__(
        self,
        sessionmaker: sessionmaker[Session],
        account_creator: SchoolAdminAccountCreator,
    ) -> None:
        """Wire the service to a session factory and a school_admin creator."""
        self._sessionmaker = sessionmaker
        self._account_creator = account_creator

    # -- Introspection --------------------------------------------------------

    def list_schools(self) -> list[SchoolSummary]:
        """Return every school on the platform, with quota, usage and admins.

        Ordered by name: this is a management list a platform admin scans and
        searches, not a "what just happened" feed like X-01's recent-signups
        row, so alphabetical is the useful order rather than newest-first.
        """
        with self._sessionmaker() as session:
            schools = list(session.scalars(select(School).order_by(School.name)).all())
            if not schools:
                return []
            school_ids = [school.id for school in schools]
            assigned_by_school = self._seats_assigned_by_school(session, school_ids)
            admins_by_school = self._admins_by_school(session, school_ids)
            return [
                SchoolSummary(
                    school_id=school.id,
                    name=school.name,
                    seat_quota=school.seat_quota,
                    seats_assigned=assigned_by_school.get(school.id, 0),
                    admins=admins_by_school.get(school.id, []),
                )
                for school in schools
            ]

    # -- Mutations --------------------------------------------------------------

    def create_school(
        self,
        name: str,
        seat_quota: int,
        created_by: uuid.UUID | str | None = None,
    ) -> SchoolSummary:
        """Create a school with an initial seat quota.

        ``created_by`` is recorded on the ``schools`` row (nullable, unused by
        every path before this one) — the first write to a column that has sat
        idle since the schema was drawn, now meaningful because this is the
        first path that creates a school as a traceable act by an identified
        admin rather than a fixture a test inserted directly.
        """
        created_by_uuid = _as_uuid(created_by) if created_by is not None else None
        with self._sessionmaker() as session, session.begin():
            school = School(name=name, seat_quota=seat_quota, created_by=created_by_uuid)
            session.add(school)
            session.flush()
            return SchoolSummary(
                school_id=school.id,
                name=school.name,
                seat_quota=school.seat_quota,
                seats_assigned=0,
                admins=[],
            )

    def update_school(
        self,
        school_id: uuid.UUID | str,
        *,
        name: str | None = None,
        seat_quota: int | None = None,
    ) -> SchoolSummary:
        """Rename a school and/or change its seat quota. Both fields optional.

        The row is locked ``FOR UPDATE`` for the duration so a concurrent seat
        invite cannot slip a seat in between the quota check below and the
        write (the same TOCTOU concern :meth:`~lemely.db.seat_repo.SeatService.invite_student`
        already guards against, from the other direction).

        Raises:
            SchoolNotFoundError: No school exists with ``school_id``.
            QuotaBelowAssignedSeatsError: ``seat_quota`` was supplied and is
                lower than the seats already assigned.
        """
        school_uuid = _as_uuid(school_id)
        with self._sessionmaker() as session, session.begin():
            school = session.get(School, school_uuid, with_for_update=True)
            if school is None:
                raise SchoolNotFoundError(f"Unknown school: {school_uuid}")
            assigned = self._seats_assigned(session, school_uuid)
            if seat_quota is not None:
                if seat_quota < assigned:
                    raise QuotaBelowAssignedSeatsError(seat_quota, assigned)
                school.seat_quota = seat_quota
            if name is not None:
                school.name = name
            session.flush()
            return SchoolSummary(
                school_id=school.id,
                name=school.name,
                seat_quota=school.seat_quota,
                seats_assigned=assigned,
                admins=self._admins_for(session, school_uuid),
            )

    def create_school_admin(
        self,
        school_id: uuid.UUID | str,
        email: str,
        password: str,
        display_name: str | None = None,
    ) -> CreateSchoolAdminResult:
        """Create a school_admin account and bind it to ``school_id`` as staff.

        Both the account and the :class:`~lemely.db.models.orgs.SchoolMembership`
        are written from this one call: a school_admin with no membership
        administers nothing and meets an empty console — indistinguishable on
        screen from a broken one (D4.10) — so the two are never allowed to
        exist independently through this path. School existence is checked
        *before* the account is created, the same ordering
        :meth:`~lemely.db.school_admin_repo.SchoolAdminService.invite_teacher`
        uses, so a rejected creation never leaves an orphaned identity behind.

        Raises:
            SchoolNotFoundError: No school exists with ``school_id``.
        """
        school_uuid = _as_uuid(school_id)
        with self._sessionmaker() as session, session.begin():
            school = session.get(School, school_uuid)
            if school is None:
                raise SchoolNotFoundError(f"Unknown school: {school_uuid}")
            user_id = self._account_creator.create_school_admin(email, password, display_name)
            membership = SchoolMembership(
                school_id=school_uuid,
                user_id=user_id,
                membership_role=MembershipRole.school_admin,
            )
            session.add(membership)
            session.flush()
            return CreateSchoolAdminResult(
                user_id=user_id, membership_id=membership.id, email=email
            )

    # -- Internals --------------------------------------------------------------

    def _seats_assigned(self, session: Session, school_uuid: uuid.UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(Seat)
            .where(Seat.school_id == school_uuid, Seat.status != SeatStatus.revoked)
        )
        return int(session.scalar(stmt) or 0)

    def _seats_assigned_by_school(
        self, session: Session, school_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, int]:
        stmt = (
            select(Seat.school_id, func.count())
            .where(Seat.school_id.in_(school_ids), Seat.status != SeatStatus.revoked)
            .group_by(Seat.school_id)
        )
        return {school_id: int(count) for school_id, count in session.execute(stmt).all()}

    def _admins_for(self, session: Session, school_uuid: uuid.UUID) -> list[SchoolAdminRow]:
        return self._admins_by_school(session, [school_uuid]).get(school_uuid, [])

    def _admins_by_school(
        self, session: Session, school_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, list[SchoolAdminRow]]:
        # Membership is the roster, not `users.role`, mirroring
        # `SchoolAdminService._teachers_for`: filtering on Role.school_admin too
        # guards the one inconsistency the schema permits — a membership row
        # pointing at a non-school_admin account.
        stmt = (
            select(SchoolMembership.school_id, User.id, User.email, User.display_name)
            .join(User, User.id == SchoolMembership.user_id)
            .where(
                SchoolMembership.school_id.in_(school_ids),
                SchoolMembership.membership_role == MembershipRole.school_admin,
                User.role == Role.school_admin,
            )
            .order_by(User.display_name, User.email)
        )
        by_school: dict[uuid.UUID, list[SchoolAdminRow]] = {}
        for school_id, user_id, email, display_name in session.execute(stmt).all():
            by_school.setdefault(school_id, []).append(
                SchoolAdminRow(user_id=user_id, email=email, display_name=display_name)
            )
        return by_school


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    """Coerce a str/UUID to :class:`uuid.UUID`, raising ``ValueError`` if invalid."""
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Identifier must be a UUID, got {value!r}") from exc


__all__ = [
    "CreateSchoolAdminResult",
    "QuotaBelowAssignedSeatsError",
    "SchoolAdminAccountCreator",
    "SchoolAdminRow",
    "SchoolNotFoundError",
    "SchoolProvisioningError",
    "SchoolProvisioningService",
    "SchoolSummary",
]
