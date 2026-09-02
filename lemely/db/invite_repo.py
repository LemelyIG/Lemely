"""Redeemable invite codes — service layer (D7.3, spec §1.2).

Two working endpoints existed with no user interface. ``POST
/api/student/classes/join`` (join a class by code) was implemented,
ownership-safe and tested; ``ClassRoster.tsx`` told teachers "They enter it
from the student portal to join" and no such screen existed.
``POST /api/school/seats/invite`` created a student account outright and
handed a temporary password back once, for the admin to convey out of band —
the student logged in cold, never having seen which school they joined. This
module, its router (:mod:`lemely.web.routers.invites`) and the two mint
routes added to ``school.py``/``classes.py`` are what makes both endpoints
reachable, and what gives a seat invite a preview a holder can see before
committing.

Mirrors :mod:`lemely.db.seat_repo` and :mod:`lemely.db.class_repo`'s shape:
pure ownership/mutation logic over a ``sessionmaker``, domain errors mapped
to HTTP status codes by a thin router layer, testable against Postgres with
no GoTrue dependency — unlike :class:`~lemely.db.seat_repo.SeatService`,
nothing here ever creates an account. :meth:`InviteService.redeem` always
attaches an *existing* one (its route is authenticated); minting reserves a
place for someone who does not have an account yet.

Class ownership is delegated entirely to a composed
:class:`~lemely.db.class_repo.ClassService` — this module runs no
``classes``/``school_memberships`` query of its own for that question, the
same discipline :class:`~lemely.db.announcement_repo.AnnouncementService`
already follows, so "may this caller touch this class" stays defined in
exactly one place.

Four rules are binding throughout this module:

1. **Ownership is checked here, never only in the router** (D1.10, the
   pattern :class:`~lemely.db.seat_repo.SeatService` and
   :class:`~lemely.db.class_repo.ClassService` already establish).
   :meth:`mint_seat_invite` touches only a school the caller holds a
   ``school_admin`` membership for; :meth:`mint_class_invite` only a class
   they own (``teacher``) or administer (``school_admin``).
2. **A seat invite reserves its seat at mint time**
   (:meth:`mint_seat_invite`), never at redemption. Otherwise
   :meth:`preview` promises a place that a second admin's invite — or a
   direct :meth:`~lemely.db.seat_repo.SeatService.invite_student` call —
   could take in the interval between "the code was handed out" and
   "someone typed it in".
3. **Redemption of anything class-shaped goes through**
   :meth:`~lemely.db.class_repo.ClassService.join_by_code`, never a second,
   hand-rolled ``ClassEnrollment`` insert — that method's own docstring asks
   callers not to write one, and this holds whether the code arrived as an
   ``invites.code`` pointing at a class or as a bare ``classes.join_code``
   typed straight in.
4. **:meth:`preview` is public and pre-account, so it is the one place in
   this module to be paranoid about disclosure.** It may name the school,
   the class and the teacher — every one of those is a fact whoever handed
   over the code already told its holder — and it must expose no student,
   no roster, no count, and no id. Compare
   :meth:`~lemely.db.class_repo.ClassService.user_exists`, which accepts a
   narrow, deliberate one-bit leak to an *authenticated staff* caller; this
   route has no authentication at all, so it gets none of that latitude.

**Why a code resolves against two tables.** ``classes.join_code``
(:class:`~lemely.db.models.orgs.SchoolClass`) predates this table by several
phases (D3.1) and is already handed out by every teacher who has ever
created a class; a new ``invites`` table cannot retroactively convert that
install base, and G-08's single "enter a code" box has no way to ask its
holder which kind they were given. So :meth:`preview` and :meth:`redeem`
both try ``invites.code`` first and fall back to ``classes.join_code`` — but
the two stay semantically distinct. An ``invites`` row is single-use
(``redeemed_by``/``redeemed_at``, mirroring
:class:`~lemely.db.models.auth_tokens.AuthToken.used_at`); a bare class join
code remains exactly as unlimited-use as it always was (D3.1). That
difference is why a class invite is minted as its own ``invites`` row rather
than simply handing out the class's existing ``join_code`` a second time —
doing so would make a "single-use" invite as shareable as the code it wraps.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from lemely.db.class_repo import (
    ClassNotFoundError,
    ClassOwnershipError,
    ClassService,
    JoinCodeError,
)
from lemely.db.models import Invite, School, SchoolClass, SchoolMembership, Seat, User
from lemely.db.models.enums import InviteRole, MembershipRole, Role, SeatStatus

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker


class InviteError(Exception):
    """Base class for invite failures."""


class InviteOwnershipError(InviteError):
    """The caller does not own/administer the invite's target (→ 403)."""


class InviteQuotaExceededError(InviteError):
    """The school has no free seats left against its quota (→ 409)."""


class InviteNotFoundError(InviteError):
    """No invite or class join code resolves to the supplied code (→ 404)."""


class InviteAlreadyRedeemedError(InviteError):
    """The invite was already redeemed by a different user (→ 409)."""


# Alphabet excludes visually-ambiguous characters (0/O, 1/I/L), mirroring
# `class_repo._JOIN_CODE_ALPHABET` for the same reason: a holder must be able
# to reliably transcribe a code read off a screen or a slip of paper. The
# length differs from a class join code's on purpose, so the two families
# read as visually distinct even though `preview`/`redeem` accept either
# interchangeably.
_INVITE_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_INVITE_CODE_LENGTH = 10
_INVITE_CODE_MAX_ATTEMPTS = 8


@dataclass(frozen=True, slots=True)
class InvitePreview:
    """What a code's holder sees before creating an account or committing (binding rule 4).

    Public and pre-account: every field here is something the holder already
    learned from whoever handed them the code — a school's name, a class's
    name, a teacher's name. Nothing else. No id, no roster, no seat or
    enrolment count.
    """

    role: InviteRole
    school_name: str | None
    class_name: str | None
    teacher_name: str | None


@dataclass(frozen=True, slots=True)
class RedeemResult:
    """What redeeming a code produced, for the router to report back.

    ``school_id``/``class_id`` mirror :class:`~lemely.db.models.invites.Invite`'s
    own nullable target columns: a seat invite yields a school and no class;
    a class invite (or a bare ``classes.join_code``) yields a class, whose
    school is filled in from the class itself when the invite did not carry
    one directly (a class invite never does — see the module docstring).
    """

    role: InviteRole
    school_id: uuid.UUID | None
    class_id: uuid.UUID | None


class InviteService:
    """Mint, preview and redeem invite codes for a school seat or a class.

    Constructed with a ``sessionmaker`` (mirroring
    :class:`~lemely.db.seat_repo.SeatService`) and the same
    :class:`~lemely.db.class_repo.ClassService` singleton every other
    class-scoped service composes, so class ownership and class enrolment
    can never diverge from what the rest of the teacher/student portals
    already enforce (D3.1).
    """

    def __init__(self, sessionmaker: sessionmaker[Session], class_service: ClassService) -> None:
        """Wire the service to a session factory and the shared ``ClassService``."""
        self._sessionmaker = sessionmaker
        self._class_service = class_service

    # -- Minting --------------------------------------------------------------

    def mint_seat_invite(self, admin_id: uuid.UUID | str, school_id: uuid.UUID | str) -> Invite:
        """Mint a redeemable seat invite, reserving its seat immediately (binding rule 2).

        The reservation is the whole point: if the seat were assigned only at
        redemption, :meth:`preview` would be promising a place that a second
        admin's invite — or a direct
        :meth:`~lemely.db.seat_repo.SeatService.invite_student` call — could
        take in the interval between "the code was handed out" and "someone
        typed it in". Reserving here means the school's ``seat_quota``
        reflects this invite the instant it exists, exactly like a
        directly-created seat: the two are indistinguishable to the quota
        arithmetic (:meth:`_used_seats`), which is what makes a school unable
        to oversell through either path.

        The reserved seat starts in
        :attr:`~lemely.db.models.enums.SeatStatus.available` (school-bound,
        unassigned) rather than ``assigned`` — that status exists in the
        schema for exactly this state and is otherwise never produced, since
        :meth:`~lemely.db.seat_repo.SeatService.invite_student` allocates and
        assigns in the same step. :meth:`redeem` is what flips it to
        ``assigned`` once someone actually claims it.

        The school row is locked ``FOR UPDATE`` for the duration, mirroring
        ``SeatService.invite_student`` exactly: ownership, the quota check
        and the seat insert must serialise against a concurrent invite (or a
        direct ``invite_student`` call) for the identical TOCTOU reason that
        method already documents.

        Raises:
            InviteOwnershipError: ``admin_id`` holds no ``school_admin``
                membership for ``school_id`` (→ 403).
            InviteQuotaExceededError: The school has no free seats left
                against its quota (→ 409).
        """
        admin_uuid = _as_uuid(admin_id)
        school_uuid = _as_uuid(school_id)
        with self._sessionmaker() as session, session.begin():
            self._assert_school_admin_of(session, admin_uuid, school_uuid)
            school = session.get(School, school_uuid, with_for_update=True)
            if school is None:  # pragma: no cover - ownership check already loaded it
                raise InviteOwnershipError(f"Unknown school: {school_uuid}")
            used = self._used_seats(session, school_uuid)
            if used >= school.seat_quota:
                raise InviteQuotaExceededError(
                    f"School {school_uuid} has no free seats ({used}/{school.seat_quota} used)"
                )
            seat = Seat(school_id=school_uuid, status=SeatStatus.available)
            session.add(seat)
            session.flush()
            return self._insert_invite(
                session,
                role=InviteRole.student,
                created_by=admin_uuid,
                school_id=school_uuid,
                seat_id=seat.id,
            )

    def mint_class_invite(
        self,
        caller_id: uuid.UUID | str,
        caller_role: Role | str,
        class_id: uuid.UUID | str,
    ) -> Invite:
        """Mint a redeemable class invite. Ownership mirrors ``ClassService`` exactly.

        Delegates the ownership question entirely to
        :meth:`~lemely.db.class_repo.ClassService.get_class` — a ``teacher``
        may mint for a class they own, a ``school_admin`` for a class in a
        school they administer, the identical dual rule D3.1 already
        establishes for roster management. This method runs no
        ``classes``/``school_memberships`` query of its own for that check
        (binding rule 1).

        Unlike a seat invite, no quota is consumed and nothing is reserved: a
        class has no capacity limit, and self-enrolment via
        ``classes.join_code`` already works with no seat pool at all — an
        independent teacher's class included (D3.1). This invite is another
        way to hand out that same capability, not a new one.

        Raises:
            InviteNotFoundError: No class exists with ``class_id`` (→ 404).
            InviteOwnershipError: The caller may not manage this class
                (→ 403).
        """
        caller_uuid = _as_uuid(caller_id)
        class_uuid = _as_uuid(class_id)
        try:
            self._class_service.get_class(caller_uuid, caller_role, class_uuid)
        except ClassNotFoundError as exc:
            raise InviteNotFoundError(str(exc)) from exc
        except ClassOwnershipError as exc:
            raise InviteOwnershipError(str(exc)) from exc
        with self._sessionmaker() as session, session.begin():
            return self._insert_invite(
                session,
                role=InviteRole.student,
                created_by=caller_uuid,
                class_id=class_uuid,
            )

    # -- Preview (public, pre-account) -----------------------------------------

    def preview(self, code: str) -> InvitePreview:
        """Resolve a code to what its holder is about to join. No account required.

        Accepts either an ``invites.code`` or a bare ``classes.join_code``
        (see the module docstring for why both must resolve here).

        **This is the one place in the module to be paranoid about
        disclosure** (binding rule 4): the route this backs is public and
        reachable before any account exists. Every field on
        :class:`InvitePreview` is something the code's holder already
        learned from whoever handed them the code, and nothing else.

        Raises:
            InviteNotFoundError: ``code`` matches neither a live invite nor a
                class join code (→ 404).
        """
        with self._sessionmaker() as session:
            invite = self._find_live_invite(session, code)
            if invite is not None:
                return self._preview_for_invite(session, invite)
            cls = self._find_class_by_join_code(session, code)
            if cls is not None:
                return self._preview_for_class(session, cls)
        raise InviteNotFoundError(f"Unknown code: {code!r}")

    # -- Redemption -------------------------------------------------------------

    def redeem(self, user_id: uuid.UUID | str, code: str) -> RedeemResult:
        """Redeem a code for the authenticated caller. Idempotent (binding rule 3).

        Assumes the caller already has an account — unlike :meth:`preview`,
        this route is authenticated — and attaches it to whatever the code
        provisions: a seat invite assigns the seat :meth:`mint_seat_invite`
        already reserved; a class invite or a bare ``classes.join_code``
        enrols the caller via
        :meth:`~lemely.db.class_repo.ClassService.join_by_code`, reused
        rather than re-implemented per that method's own docstring.

        **Idempotent for the same caller, refused for a different one** — the
        test that matters most for this module. An ``invites`` row is
        single-use, tracked by ``redeemed_by``/``redeemed_at``:
        re-presenting your own code is a no-op (mirroring
        ``ClassService.join_by_code``'s own idempotency), but a code shared
        onward after someone else already redeemed it is a **refusal**,
        never a second seat consumed or a stranger silently attached to a
        school. A bare ``classes.join_code`` carries no such row and stays,
        by design, unlimited-use (D3.1) — that is unchanged, existing
        behaviour; this single-use rule applies only to an ``invites.code``.

        Raises:
            InviteNotFoundError: ``code`` matches neither a live invite nor a
                class join code (→ 404).
            InviteAlreadyRedeemedError: The invite was already redeemed by a
                different user (→ 409).
        """
        user_uuid = _as_uuid(user_id)
        with self._sessionmaker() as session, session.begin():
            invite = self._find_live_invite(session, code, for_update=True)
            if invite is not None:
                return self._redeem_invite(session, invite, user_uuid)
        try:
            row = self._class_service.join_by_code(user_uuid, code)
        except JoinCodeError as exc:
            raise InviteNotFoundError(str(exc)) from exc
        return RedeemResult(role=InviteRole.student, school_id=row.school_id, class_id=row.class_id)

    def _redeem_invite(
        self, session: Session, invite: Invite, user_uuid: uuid.UUID
    ) -> RedeemResult:
        """Fulfil one ``invites`` row's promise for ``user_uuid``. Called under its lock."""
        if invite.redeemed_by is not None and invite.redeemed_by != user_uuid:
            raise InviteAlreadyRedeemedError(f"Invite {invite.code!r} has already been redeemed")
        school_id = invite.school_id
        class_id = invite.class_id
        if invite.seat_id is not None:
            self._assign_seat(session, invite.seat_id, user_uuid)
        if invite.class_id is not None:
            cls = session.get(SchoolClass, invite.class_id)
            if cls is not None:  # pragma: no cover - class_id is FK-guaranteed to resolve
                join_code = cls.join_code
                if join_code is not None:  # pragma: no cover - create_class always sets one
                    self._class_service.join_by_code(user_uuid, join_code)
                school_id = school_id or cls.school_id
        if invite.redeemed_by is None:
            invite.redeemed_by = user_uuid
            invite.redeemed_at = datetime.now(UTC)
        return RedeemResult(role=invite.role, school_id=school_id, class_id=class_id)

    def _assign_seat(self, session: Session, seat_id: uuid.UUID, user_uuid: uuid.UUID) -> None:
        seat = session.get(Seat, seat_id, with_for_update=True)
        if seat is None:  # pragma: no cover - seat_id is set only by mint_seat_invite
            return
        if seat.assigned_user_id is not None:
            return  # already assigned - an idempotent replay by the same caller.
        seat.assigned_user_id = user_uuid
        seat.status = SeatStatus.assigned
        seat.assigned_at = datetime.now(UTC)

    # -- Internals: lookups -----------------------------------------------------

    def _find_live_invite(
        self, session: Session, code: str, *, for_update: bool = False
    ) -> Invite | None:
        """Resolve ``code`` to an unexpired ``invites`` row, or ``None``.

        An expired invite reads identically to an unknown code (binding rule
        4): the caller of :meth:`preview` is anonymous, and "this code once
        existed" is exactly the kind of fact it must not learn.
        """
        stmt = select(Invite).where(Invite.code == code)
        if for_update:
            stmt = stmt.with_for_update()
        invite = session.scalars(stmt).first()
        if invite is None:
            return None
        if invite.expires_at is not None and invite.expires_at < datetime.now(UTC):
            return None
        return invite

    def _find_class_by_join_code(self, session: Session, join_code: str) -> SchoolClass | None:
        """Read-only lookup mirroring ``ClassService.join_by_code``'s own query.

        Necessarily duplicated rather than reused: that method enrols as a
        side effect, which :meth:`preview` — public, pre-account — must never
        do.
        """
        stmt = select(SchoolClass).where(SchoolClass.join_code == join_code)
        return session.scalars(stmt).first()

    def _preview_for_invite(self, session: Session, invite: Invite) -> InvitePreview:
        school_name = self._school_name(session, invite.school_id)
        class_name: str | None = None
        teacher_name: str | None = None
        if invite.class_id is not None:
            cls = session.get(SchoolClass, invite.class_id)
            if cls is not None:  # pragma: no cover - class_id is FK-guaranteed to resolve
                class_name = cls.name
                teacher_name = self._teacher_name(session, cls.teacher_id)
                school_name = school_name or self._school_name(session, cls.school_id)
        return InvitePreview(
            role=invite.role,
            school_name=school_name,
            class_name=class_name,
            teacher_name=teacher_name,
        )

    def _preview_for_class(self, session: Session, cls: SchoolClass) -> InvitePreview:
        return InvitePreview(
            role=InviteRole.student,
            school_name=self._school_name(session, cls.school_id),
            class_name=cls.name,
            teacher_name=self._teacher_name(session, cls.teacher_id),
        )

    def _school_name(self, session: Session, school_id: uuid.UUID | None) -> str | None:
        if school_id is None:
            return None
        school = session.get(School, school_id)
        return school.name if school is not None else None

    def _teacher_name(self, session: Session, teacher_id: uuid.UUID) -> str | None:
        teacher = session.get(User, teacher_id)
        if teacher is None:  # pragma: no cover - SchoolClass.teacher_id is a NOT NULL FK
            return None
        return teacher.display_name or teacher.email

    # -- Internals: ownership and quota ------------------------------------------

    def _assert_school_admin_of(
        self, session: Session, admin_uuid: uuid.UUID, school_uuid: uuid.UUID
    ) -> None:
        stmt = select(SchoolMembership.id).where(
            SchoolMembership.user_id == admin_uuid,
            SchoolMembership.school_id == school_uuid,
            SchoolMembership.membership_role == MembershipRole.school_admin,
        )
        if session.scalars(stmt).first() is None:
            raise InviteOwnershipError(f"Caller does not administer school {school_uuid}")

    def _used_seats(self, session: Session, school_uuid: uuid.UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(Seat)
            .where(Seat.school_id == school_uuid, Seat.status != SeatStatus.revoked)
        )
        return int(session.scalar(stmt) or 0)

    # -- Internals: code generation -----------------------------------------------

    def _insert_invite(
        self,
        session: Session,
        *,
        role: InviteRole,
        created_by: uuid.UUID,
        school_id: uuid.UUID | None = None,
        class_id: uuid.UUID | None = None,
        seat_id: uuid.UUID | None = None,
    ) -> Invite:
        """Insert a new ``Invite`` row with a freshly generated, unique code.

        Each attempt runs in its own ``SAVEPOINT`` (``session.begin_nested()``)
        so a rare code collision (``ix_invites_code``'s uniqueness) rolls back
        only the failed insert, not the caller's already-locked/quota-checked
        transaction — the school-row lock :meth:`mint_seat_invite` holds must
        survive a retry here exactly as it must survive
        ``SeatService.invite_student``'s own account-creation step.

        Raises:
            InviteError: A unique code could not be generated after several
                attempts (astronomically unlikely; mirrors
                ``ClassService.create_class``'s identical retry for join
                codes).
        """
        for _ in range(_INVITE_CODE_MAX_ATTEMPTS):
            invite = Invite(
                code=_generate_invite_code(),
                role=role,
                created_by=created_by,
                school_id=school_id,
                class_id=class_id,
                seat_id=seat_id,
            )
            try:
                with session.begin_nested():
                    session.add(invite)
                    session.flush()
            except IntegrityError:
                continue
            return invite
        raise InviteError("Could not generate a unique invite code; please retry")


def _generate_invite_code() -> str:
    """Generate a random invite code from a non-ambiguous alphabet."""
    return "".join(secrets.choice(_INVITE_CODE_ALPHABET) for _ in range(_INVITE_CODE_LENGTH))


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    """Coerce a str/UUID to :class:`uuid.UUID`, raising ``ValueError`` if invalid."""
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Identifier must be a UUID, got {value!r}") from exc


__all__ = [
    "InviteAlreadyRedeemedError",
    "InviteError",
    "InviteNotFoundError",
    "InviteOwnershipError",
    "InvitePreview",
    "InviteQuotaExceededError",
    "InviteService",
    "RedeemResult",
]
