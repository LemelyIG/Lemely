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

**Parent invites are the one documented exception to "single-use"** (spec
"two invite kinds, one table" §3). A student mints either a single-use link
(:meth:`mint_parent_invite` with ``reusable=False``, 7-day expiry via
:data:`PARENT_INVITE_TTL`) or holds one rotatable, non-expiring reusable
code (:meth:`get_or_create_parent_code`/:meth:`rotate_parent_code`). The
link behaves exactly like every other ``invites`` row here — ``redeemed_by``
marks it consumed and a second parent is refused. The reusable code is
never marked redeemed at all: each redemption only inserts a
``parent_child_links`` row via
:meth:`~lemely.db.parent_repo.ParentLinkService.link_in_session`, so a
second (or third) parent can use the identical code a sibling's other
parent already used. Both kinds are minted with ``created_by`` and
``child_id`` set to the same student — the invite proves who issued it and
who it links to in one row.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import delete, func, or_, select
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

    from lemely.db.parent_repo import ParentLinkService


PARENT_INVITE_TTL = timedelta(days=7)
"""How long a single-use parent invite link lives before it reads as unknown
(spec §3). The reusable parent code carries no expiry at all — it lives
until rotated."""


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


class InviteRoleMismatchError(InviteError):
    """The code's role and the redeeming caller's role disagree (→ 403).

    Two directions matter, both required by the spec: a parent invite
    (``role=parent``) redeemed by anyone whose ``caller_role`` is not
    :attr:`~lemely.db.models.enums.Role.parent`, and a student/teacher
    invite redeemed by a caller whose ``caller_role`` *is*
    :attr:`~lemely.db.models.enums.Role.parent`. Nothing else is checked
    here — a bare ``classes.join_code`` and every other role combination
    keep their pre-existing, unchecked behaviour.
    """


# Alphabet excludes visually-ambiguous characters (0/O, 1/I/L), mirroring
# `class_repo._JOIN_CODE_ALPHABET` for the same reason: a holder must be able
# to reliably transcribe a code read off a screen or a slip of paper. The
# length differs from a class join code's on purpose, so the two families
# read as visually distinct even though `preview`/`redeem` accept either
# interchangeably.
_INVITE_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_INVITE_CODE_LENGTH = 10
_INVITE_CODE_MAX_ATTEMPTS = 8

#: Name of the partial unique index `Invite.__table_args__` declares on
#: ``(child_id) WHERE reusable`` — the DB-level backstop for "a student has
#: at most one reusable row at a time" (review round 3, Important C).
_REUSABLE_CHILD_CONSTRAINT_NAME = "uq_invites_reusable_child"


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
    child_name: str | None
    """Set only for a ``role=parent`` invite: the child's ``display_name``,
    or ``"your child"`` when blank. Never the child's email or id — a
    parent invite gets the identical disclosure discipline binding rule 4
    already applies to a school/class/teacher name."""


@dataclass(frozen=True, slots=True)
class RedeemResult:
    """What redeeming a code produced, for the router to report back.

    ``school_id``/``class_id`` mirror :class:`~lemely.db.models.invites.Invite`'s
    own nullable target columns: a seat invite yields a school and no class;
    a class invite (or a bare ``classes.join_code``) yields a class, whose
    school is filled in from the class itself when the invite did not carry
    one directly (a class invite never does — see the module docstring).
    ``child_id`` is set only for a parent invite, mirroring
    :attr:`~lemely.db.models.invites.Invite.child_id`.
    """

    role: InviteRole
    school_id: uuid.UUID | None
    class_id: uuid.UUID | None
    child_id: uuid.UUID | None


class InviteService:
    """Mint, preview and redeem invite codes for a school seat or a class.

    Constructed with a ``sessionmaker`` (mirroring
    :class:`~lemely.db.seat_repo.SeatService`), the same
    :class:`~lemely.db.class_repo.ClassService` singleton every other
    class-scoped service composes, so class ownership and class enrolment
    can never diverge from what the rest of the teacher/student portals
    already enforce (D3.1), and a
    :class:`~lemely.db.parent_repo.ParentLinkService` — the seam a parent
    invite's redemption links an existing parent account to a child
    through, never a hand-rolled ``parent_child_links`` insert of its own
    (the same single-writer discipline that service's own docstring
    establishes).
    """

    def __init__(
        self,
        sessionmaker: sessionmaker[Session],
        class_service: ClassService,
        parent_link_service: ParentLinkService,
    ) -> None:
        """Wire the service to a session factory, ``ClassService`` and ``ParentLinkService``."""
        self._sessionmaker = sessionmaker
        self._class_service = class_service
        self._parent_link_service = parent_link_service

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

    # -- Parent invites (child-issued) -------------------------------------------

    def mint_parent_invite(self, student_id: uuid.UUID | str, *, reusable: bool) -> Invite:
        """Mint a ``role=parent`` invite naming ``student_id`` as its child.

        No ownership check runs here — unlike a seat or class invite, a
        parent invite's caller and its target (``child_id``) are the same
        person, so there is no "may this caller touch this target" question
        to ask (the router only ever calls this with the authenticated
        student's own id).

        ``reusable=False`` mints a single-use link, ``expires_at`` set to
        now plus :data:`PARENT_INVITE_TTL`; ``reusable=True`` mints the
        rotatable code, ``expires_at`` left ``NULL`` (spec §3's table).
        Prefer :meth:`get_or_create_parent_code`/:meth:`rotate_parent_code`
        over calling this directly with ``reusable=True`` — calling this
        directly still cannot leave two live reusable rows for one child
        (``uq_invites_reusable_child`` refuses the second insert outright,
        surfaced as :class:`InviteError`), but it skips the locked
        read-then-insert those two methods use to make the *common* case a
        clean "here is your existing code" rather than an avoidable error.

        Raises:
            InviteError: ``student_id`` names no ``users`` row (see
                :meth:`get_or_create_parent_code`'s identical check —
                review round 3, Minor 2), or (``reusable=True`` only) the
                child already has a live reusable row.
        """
        student_uuid = _as_uuid(student_id)
        expires_at = None if reusable else datetime.now(UTC) + PARENT_INVITE_TTL
        with self._sessionmaker() as session, session.begin():
            if session.get(User, student_uuid) is None:
                raise InviteError(f"Unknown user: {student_uuid}")
            return self._insert_invite(
                session,
                role=InviteRole.parent,
                created_by=student_uuid,
                child_id=student_uuid,
                reusable=reusable,
                expires_at=expires_at,
            )

    def get_or_create_parent_code(self, student_id: uuid.UUID | str) -> Invite:
        """Return this child's reusable parent code, minting one lazily.

        Mirrors ``classes.join_code``'s "a class always has a join code"
        rule: a student never sees an empty state for their code, only a
        value. ``uq_invites_reusable_child`` (a partial unique index on
        ``invites (child_id) WHERE reusable``) is what finally guarantees
        "at most one reusable row per child" at the database, closing the
        saga review rounds 1 through 3 ran through pure lock ordering. This
        method still locks the child's own ``users`` row ``FOR UPDATE`` for
        the duration of the read-then-insert (mirroring
        :meth:`mint_seat_invite`'s school-row lock for the identical TOCTOU
        reason) so the *common* case — two concurrent calls for the same
        student — serialises into "the second caller sees the first's
        committed row and returns it", a clean read, rather than relying on
        the index to turn every race into a caught :class:`InviteError` no
        one asked for.

        **This method's lock order is ``users`` first, then a lock-free
        read of the reusable row — the opposite of** :meth:`rotate_parent_code`,
        **which locks the reusable row first and ``users`` second.** That
        is safe only because :meth:`_find_reusable_parent_code` is a plain
        ``SELECT`` with no ``FOR UPDATE``, so it never blocks waiting for a
        row lock (MVCC hands it a snapshot instead) — this method's lock
        set is ``users`` alone. Adding ``.with_for_update()`` to that
        lookup would make this method also want the invites row while
        holding ``users``, which is exactly :meth:`rotate_parent_code`'s
        order in reverse and would reopen the deadlock cycle review round 2
        closed (review round 3, Minor 1). Do not "harden" that lookup.

        Raises:
            InviteError: ``student_id`` names no ``users`` row. Unreachable
                through the authenticated router (which only ever calls
                this with the caller's own id), but worth a clear error
                instead of letting the insert below fail its ``child_id``
                foreign key and get misreported by :meth:`_insert_invite`'s
                retry loop as an exhausted *code*-collision search (review
                round 2, Minor 2).
        """
        student_uuid = _as_uuid(student_id)
        with self._sessionmaker() as session, session.begin():
            if session.get(User, student_uuid, with_for_update=True) is None:
                raise InviteError(f"Unknown user: {student_uuid}")
            existing = self._find_reusable_parent_code(session, student_uuid)
            if existing is not None:
                return existing
            return self._insert_invite(
                session,
                role=InviteRole.parent,
                created_by=student_uuid,
                child_id=student_uuid,
                reusable=True,
                expires_at=None,
            )

    def rotate_parent_code(self, student_id: uuid.UUID | str) -> Invite:
        """Replace this child's reusable code with a freshly minted one.

        Deletes the old row (which locks it, exactly as ``DELETE`` always
        does for the rows it removes) *before* locking the child's own
        ``users`` row — that order matters, not just the fact of locking
        both. :meth:`redeem` locks an ``invites`` row first
        (``_find_live_invite(..., for_update=True)``) and only needs the
        child's ``users`` row second, implicitly, when
        :meth:`_redeem_parent_invite` calls
        :meth:`~lemely.db.parent_repo.ParentLinkService.link_in_session`
        (whose ``INSERT`` takes a ``FOR KEY SHARE`` lock on ``users`` to
        satisfy the FK). Locking ``users`` first here, as the original fix
        for review round 1 did, opened a deadlock cycle against a
        concurrent :meth:`redeem` of the same child's reusable code — this
        order closes it by matching ``redeem``'s invites-then-users
        sequence (review round 2, Important A). Deleting first also means a
        rotation with no existing reusable row locks and deletes nothing,
        so a first-ever mint via this path takes no unnecessary lock beyond
        the ``users`` row itself.

        **The ``DELETE`` runs twice.** Under READ COMMITTED, a statement
        only sees rows committed as of *its own start* — so the first
        ``DELETE`` above can run, find nothing (or find and remove a stale
        row), then this transaction blocks waiting for the ``users`` lock a
        concurrent :meth:`rotate_parent_code`/:meth:`get_or_create_parent_code`
        call holds; by the time that lock frees up, the other transaction
        may have committed a *new* reusable row this statement's snapshot
        cannot see. Taking the ``users`` lock and stopping there left
        exactly that race able to produce two live reusable rows (review
        round 3, Important C) — the same instability review round 1's
        Important 1 first described, reopened by round 2's own deadlock
        fix. Re-issuing the ``DELETE`` immediately after the lock is held
        starts a fresh statement with a fresh snapshot, and nothing else
        can insert a reusable row for this child while that lock stands, so
        it cannot miss a racer's row. ``uq_invites_reusable_child`` (the
        partial unique index review round 3 added) is the backstop behind
        even this: if some future caller still finds a way to slip past
        both ``DELETE``s, the insert below fails loudly with a clear
        :class:`InviteError` rather than silently doubling the row.
        """
        student_uuid = _as_uuid(student_id)
        with self._sessionmaker() as session, session.begin():
            session.execute(
                delete(Invite).where(Invite.child_id == student_uuid, Invite.reusable.is_(True))
            )
            if session.get(User, student_uuid, with_for_update=True) is None:
                raise InviteError(f"Unknown user: {student_uuid}")
            # Re-run now that the `users` lock is held (see the docstring):
            # a fresh statement, a fresh snapshot, nothing else can insert
            # a reusable row for this child while we hold that lock.
            session.execute(
                delete(Invite).where(Invite.child_id == student_uuid, Invite.reusable.is_(True))
            )
            return self._insert_invite(
                session,
                role=InviteRole.parent,
                created_by=student_uuid,
                child_id=student_uuid,
                reusable=True,
                expires_at=None,
            )

    def list_parent_invites(self, student_id: uuid.UUID | str) -> list[Invite]:
        """Return this child's live, unredeemed single-use links, oldest first.

        The reusable code is deliberately excluded — it is not a pending
        invite a student manages one at a time, it is a standing code
        surfaced separately by :meth:`get_or_create_parent_code`. A
        redeemed or expired link is equally excluded: both have already
        served their purpose and clutter a "pending" list otherwise.
        """
        student_uuid = _as_uuid(student_id)
        now = datetime.now(UTC)
        with self._sessionmaker() as session:
            stmt = (
                select(Invite)
                .where(
                    Invite.child_id == student_uuid,
                    Invite.reusable.is_(False),
                    Invite.redeemed_by.is_(None),
                    or_(Invite.expires_at.is_(None), Invite.expires_at > now),
                )
                .order_by(Invite.created_at, Invite.id)
            )
            return list(session.scalars(stmt).all())

    def revoke_parent_invite(self, student_id: uuid.UUID | str, code: str) -> None:
        """Delete a single-use parent link that belongs to ``student_id``.

        Deletes only when ``code`` resolves to an ``invites`` row whose
        ``child_id`` is ``student_id`` and whose ``reusable`` is ``False``;
        anything else — another student's code, the reusable code, or an
        unknown code — is the identical :class:`InviteNotFoundError`, so a
        student learns nothing about whether a code they don't own exists
        (the same disclosure discipline binding rule 4 applies to
        :meth:`preview`). Locked ``FOR UPDATE``, mirroring :meth:`redeem`'s
        own lock on the row it resolves — a revoke racing a redemption
        serialises against it rather than deleting out from under an
        in-flight link.
        """
        student_uuid = _as_uuid(student_id)
        with self._sessionmaker() as session, session.begin():
            invite = session.scalars(
                select(Invite).where(Invite.code == code).with_for_update()
            ).first()
            if invite is None or invite.child_id != student_uuid or invite.reusable:
                raise InviteNotFoundError(f"Unknown code: {code!r}")
            session.delete(invite)

    def _find_reusable_parent_code(
        self, session: Session, student_uuid: uuid.UUID
    ) -> Invite | None:
        """Look up the reusable row for ``student_uuid``, oldest first.

        The ``ORDER BY`` guards a case ``uq_invites_reusable_child`` cannot:
        a stray second row from before that index existed, or from a caller
        that predates it entirely. An unordered ``.first()`` would let
        Postgres return either one on different calls — the exact
        "unstable code" failure review round 1's Important 1 described.
        Ordering degrades that to a stable choice (the oldest row wins)
        rather than an unstable one.

        **Deliberately a plain ``SELECT``, no ``.with_for_update()``.** See
        :meth:`get_or_create_parent_code`'s docstring: that method locks
        ``users`` first and calls this lock-free, the opposite order
        :meth:`rotate_parent_code` uses for the same two resources. Locking
        here would reopen the exact deadlock cycle review round 2 closed
        (review round 3, Minor 1).
        """
        stmt = (
            select(Invite)
            .where(Invite.child_id == student_uuid, Invite.reusable.is_(True))
            .order_by(Invite.created_at, Invite.id)
        )
        return session.scalars(stmt).first()

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
                if invite.role is InviteRole.parent:
                    return self._preview_for_parent_invite(session, invite)
                return self._preview_for_invite(session, invite)
            cls = self._find_class_by_join_code(session, code)
            if cls is not None:
                return self._preview_for_class(session, cls)
        raise InviteNotFoundError(f"Unknown code: {code!r}")

    # -- Redemption -------------------------------------------------------------

    def redeem(
        self,
        user_id: uuid.UUID | str,
        code: str,
        *,
        caller_role: Role | None = None,
    ) -> RedeemResult:
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
            InviteRoleMismatchError: ``code`` is a parent invite and
                ``caller_role`` is not
                :attr:`~lemely.db.models.enums.Role.parent`, or ``code`` is
                a student/teacher invite and ``caller_role`` *is*
                :attr:`~lemely.db.models.enums.Role.parent` (→ 403).
        """
        user_uuid = _as_uuid(user_id)
        with self._sessionmaker() as session, session.begin():
            invite = self._find_live_invite(session, code, for_update=True)
            if invite is not None:
                if invite.role is InviteRole.parent:
                    if caller_role is not Role.parent:
                        raise InviteRoleMismatchError(
                            f"Invite {code!r} is a parent invite; caller role is {caller_role}"
                        )
                    return self._redeem_parent_invite(session, invite, user_uuid)
                if caller_role is Role.parent:
                    raise InviteRoleMismatchError(
                        f"Invite {code!r} is not a parent invite; caller is a parent"
                    )
                return self._redeem_invite(session, invite, user_uuid)
        if caller_role is Role.parent:
            # A bare `classes.join_code` carries no `invites` row and so no
            # `role` to check above, but a parent enrolling as a student
            # through it is exactly the mistake `InviteRoleMismatchError`
            # exists to catch on the branch above - the guard must not stop
            # short of this one just because the code is the older, class-
            # native kind (review round 1, Important 2). Resolved read-only
            # first, though: a parent who simply mistyped their invite code
            # must get the ordinary `InviteNotFoundError`, not a confident,
            # false "this is a class join code" mismatch (review round 2,
            # Important B) - and this lookup itself never enrols anyone,
            # unlike calling `join_by_code` to find out the same thing.
            with self._sessionmaker() as session:
                cls = self._find_class_by_join_code(session, code)
            if cls is None:
                raise InviteNotFoundError(f"Unknown code: {code!r}")
            raise InviteRoleMismatchError(
                f"Code {code!r} is a class join code, not a parent invite; caller is a parent"
            )
        try:
            row = self._class_service.join_by_code(user_uuid, code)
        except JoinCodeError as exc:
            raise InviteNotFoundError(str(exc)) from exc
        return RedeemResult(
            role=InviteRole.student, school_id=row.school_id, class_id=row.class_id, child_id=None
        )

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
        return RedeemResult(role=invite.role, school_id=school_id, class_id=class_id, child_id=None)

    def _redeem_parent_invite(
        self, session: Session, invite: Invite, user_uuid: uuid.UUID
    ) -> RedeemResult:
        """Link the redeeming parent to ``invite.child_id``. Called under its lock.

        Marks ``redeemed_by``/``redeemed_at`` only when the invite is not
        ``reusable`` — a reusable code is never consumed (spec §3), so every
        parent who holds it links successfully and the row itself is
        untouched by any redemption. The single-use link, by contrast,
        behaves exactly like :meth:`_redeem_invite`: idempotent for the
        parent who already redeemed it, refused for a different one.
        """
        if invite.redeemed_by is not None and invite.redeemed_by != user_uuid:
            raise InviteAlreadyRedeemedError(f"Invite {invite.code!r} has already been redeemed")
        if invite.child_id is None:  # pragma: no cover - mint_parent_invite always sets it
            return RedeemResult(role=invite.role, school_id=None, class_id=None, child_id=None)
        self._parent_link_service.link_in_session(session, user_uuid, invite.child_id)
        if not invite.reusable and invite.redeemed_by is None:
            invite.redeemed_by = user_uuid
            invite.redeemed_at = datetime.now(UTC)
        return RedeemResult(
            role=invite.role, school_id=None, class_id=None, child_id=invite.child_id
        )

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
            child_name=None,
        )

    def _preview_for_class(self, session: Session, cls: SchoolClass) -> InvitePreview:
        return InvitePreview(
            role=InviteRole.student,
            school_name=self._school_name(session, cls.school_id),
            class_name=cls.name,
            teacher_name=self._teacher_name(session, cls.teacher_id),
            child_name=None,
        )

    def _preview_for_parent_invite(self, session: Session, invite: Invite) -> InvitePreview:
        """Name the child, never their email or id (binding rule 4).

        ``child_id`` is FK-guaranteed to resolve to a live ``users`` row for
        the lifetime of the invite (``ON DELETE CASCADE`` deletes the invite
        alongside the child, rather than leaving a dangling reference).
        """
        child_name = "your child"
        if invite.child_id is not None:
            child = session.get(User, invite.child_id)
            if child is not None:  # pragma: no cover - child_id is FK-guaranteed to resolve
                child_name = child.display_name or "your child"
        return InvitePreview(
            role=InviteRole.parent,
            school_name=None,
            class_name=None,
            teacher_name=None,
            child_name=child_name,
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
        child_id: uuid.UUID | None = None,
        reusable: bool = False,
        expires_at: datetime | None = None,
    ) -> Invite:
        """Insert a new ``Invite`` row with a freshly generated, unique code.

        Each attempt runs in its own ``SAVEPOINT`` (``session.begin_nested()``)
        so a rare code collision (``ix_invites_code``'s uniqueness) rolls back
        only the failed insert, not the caller's already-locked/quota-checked
        transaction — the school-row lock :meth:`mint_seat_invite` holds must
        survive a retry here exactly as it must survive
        ``SeatService.invite_student``'s own account-creation step.

        ``child_id``, ``reusable`` and ``expires_at`` exist for
        :meth:`mint_parent_invite`/:meth:`rotate_parent_code`; every other
        caller leaves them at their defaults (no child, single-use, no
        expiry).

        Raises:
            InviteError: A unique code could not be generated after several
                attempts (astronomically unlikely; mirrors
                ``ClassService.create_class``'s identical retry for join
                codes) — or, for a ``reusable=True`` insert,
                ``uq_invites_reusable_child`` (the child already has a live
                reusable row). The retry loop must not treat that second
                case as a code collision: retrying with a fresh *code*
                changes nothing about the child already having a reusable
                row, so it would exhaust all ``_INVITE_CODE_MAX_ATTEMPTS``
                attempts and still report the misleading "could not
                generate a unique invite code" (review round 3, Important
                C) instead of the real, immediate cause.
        """
        for _ in range(_INVITE_CODE_MAX_ATTEMPTS):
            invite = Invite(
                code=_generate_invite_code(),
                role=role,
                created_by=created_by,
                school_id=school_id,
                class_id=class_id,
                seat_id=seat_id,
                child_id=child_id,
                reusable=reusable,
                expires_at=expires_at,
            )
            try:
                with session.begin_nested():
                    session.add(invite)
                    session.flush()
            except IntegrityError as exc:
                if _is_reusable_child_violation(exc):
                    raise InviteError(
                        f"Child {child_id} already has a reusable parent code"
                    ) from exc
                continue
            return invite
        raise InviteError("Could not generate a unique invite code; please retry")


def _generate_invite_code() -> str:
    """Generate a random invite code from a non-ambiguous alphabet."""
    return "".join(secrets.choice(_INVITE_CODE_ALPHABET) for _ in range(_INVITE_CODE_LENGTH))


def _is_reusable_child_violation(exc: IntegrityError) -> bool:
    """``True`` only for a violation of ``uq_invites_reusable_child``.

    Any other ``IntegrityError`` — a code collision on ``ix_invites_code``,
    chiefly — must keep being retried by :meth:`InviteService._insert_invite`'s
    caller. Treating every ``IntegrityError`` alike would either retry a
    reusable-row collision (that repeats every time, since a new code changes
    nothing about it) or, the other way round, stop retrying a genuine,
    fixable code collision (mirrors ``notification_repo``'s and ``xp_repo``'s
    identical narrow-match discipline for the same reason).
    """
    return _constraint_name(exc) == _REUSABLE_CHILD_CONSTRAINT_NAME


def _constraint_name(exc: IntegrityError) -> str | None:
    """Best-effort constraint name off a psycopg ``IntegrityError``."""
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    name = getattr(diag, "constraint_name", None)
    return str(name) if name is not None else None


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    """Coerce a str/UUID to :class:`uuid.UUID`, raising ``ValueError`` if invalid."""
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Identifier must be a UUID, got {value!r}") from exc


__all__ = [
    "PARENT_INVITE_TTL",
    "InviteAlreadyRedeemedError",
    "InviteError",
    "InviteNotFoundError",
    "InviteOwnershipError",
    "InvitePreview",
    "InviteQuotaExceededError",
    "InviteRoleMismatchError",
    "InviteService",
    "RedeemResult",
]
