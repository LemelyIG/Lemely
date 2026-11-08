"""Teacher team service: leased student seats and assistants (spec §2.2, §2.3, §4.4, §5.9).

:class:`TeacherTeamService` works inside a ``Session`` its caller owns, so the class
join (``ClassService.join_by_code_with_notice``) claims a seat in the same
transaction as the enrolment: a refused seat rolls the enrolment back.
:class:`TeacherTeamStore` opens one transaction per unit of work for routers and the
team-permission guard.

**Seat count.** Active plus leaving ``student_seat`` rows must stay at or below
``included_seats + extra_seats`` of the teacher's live subscription (status
``active`` or ``past_due``; ``past_due`` is the grace period, §5.2). The count is
taken under ``SELECT … FOR UPDATE`` on that subscription row, so two concurrent joins
serialise and the second sees the first's seat. A teacher with no live plan has zero
seats.

**Lock order.** Every path that creates or reactivates a seat takes its locks in one
order, and every other writer must take any lock it shares with this one in the same
order:

1. the teacher's live ``subscriptions`` row (``FOR UPDATE``);
2. the ``teacher_members`` row of the pair (``FOR UPDATE``);
3. the ledger: the owner advisory locks in ascending user-id order, then the grant
   rows in chain order (index R14, ``lemely.db.usage_ledger_repo``).

Steps 1 and 2 are taken here. Step 3 is not taken in this module's Phase 03 body: a
claim touches no ledger row. Phase 05 (Task 10 Step 4) calls
``grant_seat_allowance_on_claim`` inside ``claim_seat_for_class_join``, before each of
its two returns, which puts the ledger locks at step 3 of the same transaction. That
grant is a ``seat_allowance`` grant, which the ledger never uses to repay the student's
own debt (index R13), and the seat's ``cap_units`` and ``cap_period`` bound what the
student may overflow into the teacher's credits.
``set_scope``, ``set_cap`` and ``request_removal`` lock only the member row (step 2).
``release_due`` is one ``UPDATE`` and locks no subscription row: releasing a seat only
ever frees capacity.

**Ownership.** Methods that take a ``member_id`` do not know the caller. Routers call
:meth:`TeacherTeamService.owned_member` first, which answers an id the caller does not
own exactly like an unknown id.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from lemely.core.metered_actions import SEAT_ACTIONS, MeteredAction
from lemely.core.team_permissions import UnknownPermissionError, validate_overrides
from lemely.db.invite_codes import constraint_name, generate_invite_code
from lemely.db.models import (
    ClassEnrollment,
    Invite,
    PlanTier,
    SchoolClass,
    Subject,
    Subscription,
    User,
)
from lemely.db.models.billing import PlanAudience
from lemely.db.models.enums import InviteRole, Role, SubscriptionStatus
from lemely.db.models.team import (
    AssistantRole,
    CapPeriod,
    TeacherMember,
    TeacherMemberKind,
    TeacherMemberStatus,
)

if TYPE_CHECKING:
    import uuid
    from collections.abc import Iterator, Mapping, Sequence

    from sqlalchemy.orm import Session, sessionmaker

LIVE_PLAN_STATUSES: Final = (SubscriptionStatus.active, SubscriptionStatus.past_due)
"""Subscription states whose seats count (``past_due`` is the 3-day grace, spec §5.2)."""

TEACHER_AUDIENCE: Final = PlanAudience.teacher
"""``plan_tiers.audience`` of a teacher tier (Phase 02)."""

_HELD: Final = (TeacherMemberStatus.active, TeacherMemberStatus.leaving)

MAX_LIVE_ASSISTANT_INVITES: Final = 20
"""Cap on a teacher's live (unexpired, unredeemed) assistant invites, as for parent links."""

MAX_ASSISTANT_INVITE_TTL: Final = timedelta(days=30)
"""Longest an assistant invite may live. Spec §4.4 says only "expire"; the frontend
contract (index A24, ``expiresInDays`` 1-30) sets the bound."""

_INVITE_CODE_ATTEMPTS: Final = 8

SEAT_ACTIONS_OFF_BY_DEFAULT: Final = frozenset({MeteredAction.STUDY_PLAN})
"""Seat actions a teacher turns on per seat (spec §2.2: study plans are off by default)."""


def default_seat_actions() -> list[str]:
    """Return a new seat's ``scope_actions``: every seat action except the opt-in ones."""
    return sorted(action.value for action in SEAT_ACTIONS - SEAT_ACTIONS_OFF_BY_DEFAULT)


class TeamError(Exception):
    """Base class for teacher-team failures."""


class NoFreeSeat(TeamError):
    """The teacher has no free seat for a new student (→ 409 ``no_free_seat``)."""


class TeamMemberNotFound(TeamError):
    """No such member, or not the caller's, or the wrong kind, or removed (→ 404)."""


class TeamStateError(TeamError):
    """The member exists but cannot take this change in its current state (→ 409)."""


class InvalidScope(TeamError):
    """A scope names an unknown subject or an action a seat cannot cover (→ 422)."""


class InvalidCap(TeamError):
    """A cap is negative (→ 422)."""


class NotATeacher(TeamStateError):
    """The account is not a teacher, so it cannot lead or join a team as an assistant (→ 403).

    A :class:`TeamStateError` subclass: a caller that handles only the base class still
    refuses the request, as a 409.
    """


class InvalidInviteExpiry(TeamError):
    """An invite expiry is not in the future or is beyond the longest allowed (→ 422)."""


class InvalidPermissions(TeamError):
    """Permission toggles name something that is not a team permission (→ 422)."""


class AssistantInviteNotFound(TeamError):
    """No live assistant invite has this code (→ 404)."""


class AssistantInviteRedeemed(TeamError):
    """The assistant invite was redeemed by someone else (→ 409)."""


class AssistantInviteLimitError(TeamError):
    """The teacher already holds the most live assistant invites allowed (→ 409)."""


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


_INVITE_CODE_CONSTRAINT: Final = "ix_invites_code"
_PAIR_CONSTRAINT: Final = "uq_teacher_members_teacher_member"


def month_end(now: datetime) -> datetime:
    """Return the first instant of the UTC month after ``now`` (a seat's ``leaves_at``).

    Raises:
        ValueError: ``now`` is naive; a naive instant has no month in UTC.
    """
    _require_aware(now, "now")
    current = now.astimezone(UTC)
    if current.month == 12:
        return datetime(current.year + 1, 1, 1, tzinfo=UTC)
    return datetime(current.year, current.month + 1, 1, tzinfo=UTC)


class TeacherTeamService:
    """Seats and assistants of teachers, inside one caller-owned transaction."""

    def __init__(self, session: Session) -> None:
        """Bind the service to ``session``; the caller owns its transaction."""
        self._session = session

    # -- Seats: capacity -----------------------------------------------------

    def seat_capacity(self, teacher_user_id: uuid.UUID) -> int:
        """Return ``included_seats + extra_seats`` of the live teacher plan, or 0."""
        return self._capacity(teacher_user_id, lock=False)

    def seats_used(self, teacher_user_id: uuid.UUID) -> int:
        """Return the teacher's active plus leaving seats."""
        stmt = (
            select(func.count())
            .select_from(TeacherMember)
            .where(
                TeacherMember.teacher_user_id == teacher_user_id,
                TeacherMember.kind == TeacherMemberKind.student_seat,
                TeacherMember.status.in_(_HELD),
            )
        )
        return int(self._session.scalar(stmt) or 0)

    # -- Seats: claim ----------------------------------------------------------

    def claim_seat_for_class_join(
        self, *, student_user_id: uuid.UUID, class_id: uuid.UUID, now: datetime
    ) -> TeacherMember:
        """Take (or extend) the student's seat with the class's teacher (spec §4.4).

        Call after the enrolment row is written, in the same transaction. The first
        join with a teacher creates the seat with default scope: the subjects of the
        teacher's school-less classes the student is in, and every seat action except
        ``study_plan`` (:func:`default_seat_actions`). A later join adds the class
        subject to the seat. A ``leaving`` seat stays ``leaving`` (the teacher's
        removal stands); a ``removed`` seat is reactivated with fresh defaults if a
        seat is free. The table keeps one row per (teacher, member) pair for ever, so a
        reactivation UPDATEs that row (status, scope, cap) and never inserts. The row
        keeps its original ``created_at``, so a reactivated seat sorts as old as its
        first claim in :meth:`seats_for_student`, which Phase 04's payer chain uses to
        decide which seat pays first ("older seat pays first"). An assistant row, live
        or removed, is never converted to a seat.

        The claim takes the locks of the module docstring's steps 1 and 2 and issues
        no grant itself. ``now`` is the claim instant, passed on to Phase 05's
        seat-allowance-on-claim hook.

        Raises:
            NoFreeSeat: A new or reactivated seat would exceed the plan's seats.
            TeamStateError: The class does not exist, belongs to a school (school
                classes enrol through school seats, spec §2.8), the student is the
                class's own teacher, or the pair is an assistant (live or removed).
        """
        del now  # the claim itself is instant-independent; Phase 05 adds the allowance
        cls = self._session.get(SchoolClass, class_id)
        if cls is None:
            raise TeamStateError(f"Unknown class: {class_id}")
        if cls.school_id is not None:
            raise TeamStateError("A school class enrols through school seats, not teacher seats")
        teacher_id = cls.teacher_id
        if student_user_id == teacher_id:
            raise TeamStateError("A teacher cannot take a seat in their own class")
        capacity = self._capacity(teacher_id, lock=True)
        existing = self._member_row(teacher_id, student_user_id, lock=True)
        if existing is not None and existing.kind is not TeacherMemberKind.student_seat:
            raise TeamStateError("This account is already this teacher's assistant")
        if existing is not None and existing.status is not TeacherMemberStatus.removed:
            subject = cls.subject_code
            current = list(existing.scope_subjects or [])
            if subject is not None and subject not in current:
                existing.scope_subjects = sorted([*current, subject])
                self._session.flush()
            return existing
        if self.seats_used(teacher_id) >= capacity:
            raise NoFreeSeat(f"Teacher {teacher_id} has no free seat")
        subjects = self._joined_subjects(student_user_id, teacher_id, also=cls.subject_code)
        if existing is None:
            member = TeacherMember(
                teacher_user_id=teacher_id,
                member_user_id=student_user_id,
                kind=TeacherMemberKind.student_seat,
                scope_subjects=subjects,
                scope_actions=default_seat_actions(),
                cap_units=None,
                cap_period=CapPeriod.month,
                status=TeacherMemberStatus.active,
            )
            self._session.add(member)
        else:
            # One row per (teacher, member) pair, ever: reuse it, never INSERT a second.
            member = existing
            member.status = TeacherMemberStatus.active
            member.leaves_at = None
            member.scope_subjects = subjects
            member.scope_actions = default_seat_actions()
            member.cap_units = None
            member.cap_period = CapPeriod.month
        self._session.flush()
        return member

    # -- Seats: reads ----------------------------------------------------------

    def seats_for_student(self, student_user_id: uuid.UUID) -> list[TeacherMember]:
        """Return the student's active and leaving seats, oldest first (spec §5.6)."""
        stmt = (
            select(TeacherMember)
            .where(
                TeacherMember.member_user_id == student_user_id,
                TeacherMember.kind == TeacherMemberKind.student_seat,
                TeacherMember.status.in_(_HELD),
            )
            .order_by(TeacherMember.created_at, TeacherMember.id)
        )
        return list(self._session.scalars(stmt))

    def list_seats(self, teacher_user_id: uuid.UUID) -> list[TeacherMember]:
        """Return the teacher's active and leaving seats, oldest first."""
        stmt = (
            select(TeacherMember)
            .where(
                TeacherMember.teacher_user_id == teacher_user_id,
                TeacherMember.kind == TeacherMemberKind.student_seat,
                TeacherMember.status.in_(_HELD),
            )
            .order_by(TeacherMember.created_at, TeacherMember.id)
        )
        return list(self._session.scalars(stmt))

    def owned_member(
        self,
        teacher_user_id: uuid.UUID,
        member_id: uuid.UUID,
        *,
        kind: TeacherMemberKind | None,
    ) -> TeacherMember:
        """Return the teacher's own non-removed member ``member_id`` (of ``kind`` if given).

        Raises:
            TeamMemberNotFound: Unknown, another teacher's, the wrong kind, or removed;
                one answer for all four, so an id leaks nothing.
        """
        stmt = select(TeacherMember).where(
            TeacherMember.id == member_id,
            TeacherMember.teacher_user_id == teacher_user_id,
            TeacherMember.status != TeacherMemberStatus.removed,
        )
        if kind is not None:
            stmt = stmt.where(TeacherMember.kind == kind)
        member = self._session.scalars(stmt).first()
        if member is None:
            raise TeamMemberNotFound(f"Unknown team member: {member_id}")
        return member

    def display_names(self, user_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, str | None]:
        """Return ``users.display_name`` for each id (never the email)."""
        if not user_ids:
            return {}
        rows = self._session.execute(
            select(User.id, User.display_name).where(User.id.in_(list(user_ids)))
        )
        return {user_id: name for user_id, name in rows}

    # -- Seats: scope, cap, removal ----------------------------------------------

    def set_scope(self, member_id: uuid.UUID, *, subjects: list[str], actions: list[str]) -> None:
        """Replace a seat's subjects and actions (spec §2.2).

        Routing is per subject: the seat pays only for work on a paper, quiz or plan
        in one of ``subjects``, and only for the ``actions`` listed.

        Raises:
            TeamMemberNotFound: No such member.
            TeamStateError: The member is an assistant or removed.
            InvalidScope: An action is not in ``SEAT_ACTIONS`` (index R12), or a subject
                is not a ``subjects.code``.
        """
        member = self._locked_member(member_id)
        if (
            member.kind is not TeacherMemberKind.student_seat
            or member.status is TeacherMemberStatus.removed
        ):
            raise TeamStateError("Only a held seat has a scope")
        scopable = {action.value for action in SEAT_ACTIONS}
        unknown_actions = sorted(set(actions) - scopable)
        if unknown_actions:
            raise InvalidScope(f"Actions a seat cannot cover: {unknown_actions}")
        wanted = sorted(set(subjects))
        known = set(self._session.scalars(select(Subject.code).where(Subject.code.in_(wanted))))
        unknown_subjects = [code for code in wanted if code not in known]
        if unknown_subjects:
            raise InvalidScope(f"Unknown subjects: {unknown_subjects}")
        member.scope_subjects = wanted
        member.scope_actions = sorted(set(actions))
        self._session.flush()

    def set_cap(
        self, member_id: uuid.UUID, *, cap_units: int | None, cap_period: CapPeriod
    ) -> None:
        """Set a seat's overflow cap or an assistant's spend cap (``None`` = see model doc).

        Raises:
            TeamMemberNotFound: No such member.
            TeamStateError: The member is removed.
            InvalidCap: ``cap_units`` is negative.
        """
        member = self._locked_member(member_id)
        if member.status is TeacherMemberStatus.removed:
            raise TeamStateError("A removed member has no cap")
        if cap_units is not None and cap_units < 0:
            raise InvalidCap("A cap cannot be negative")
        member.cap_units = cap_units
        member.cap_period = CapPeriod(cap_period)
        self._session.flush()

    def request_removal(self, member_id: uuid.UUID, *, now: datetime) -> None:
        """Mark a seat ``leaving`` until the end of the current month (spec §5.9).

        Idempotent: a seat already leaving keeps its original ``leaves_at``.

        Raises:
            TeamMemberNotFound: No such member.
            TeamStateError: The member is an assistant or already removed.
        """
        member = self._locked_member(member_id)
        if (
            member.kind is not TeacherMemberKind.student_seat
            or member.status is TeacherMemberStatus.removed
        ):
            raise TeamStateError("Only a held seat can be removed this way")
        if member.status is TeacherMemberStatus.leaving:
            return
        member.status = TeacherMemberStatus.leaving
        member.leaves_at = month_end(now)
        self._session.flush()

    def release_due(self, *, now: datetime) -> int:
        """Set every leaving seat whose ``leaves_at`` has passed to ``removed``; the count.

        Run by the ``seats.release_due`` sweeper job (registered in Phase 05). The
        current seat grant runs to its own expiry (spec §5.9).

        Raises:
            ValueError: ``now`` is naive.
        """
        _require_aware(now, "now")
        released = self._session.scalars(
            update(TeacherMember)
            .where(
                TeacherMember.kind == TeacherMemberKind.student_seat,
                TeacherMember.status == TeacherMemberStatus.leaving,
                TeacherMember.leaves_at <= now,
            )
            .values(status=TeacherMemberStatus.removed)
            .returning(TeacherMember.id)
            .execution_options(synchronize_session=False)
        ).all()
        return len(released)

    # -- Assistants ------------------------------------------------------------------

    def create_assistant_invite(
        self, teacher_user_id: uuid.UUID, *, role: AssistantRole, expires_at: datetime
    ) -> Invite:
        """Mint a single-use, expiring assistant invite for the teacher's team (spec §4.4).

        Only a teacher account leads a team, so only a teacher can mint. The mint is
        serialised per teacher by a lock on the teacher's ``users`` row, so the
        live-invite cap holds under concurrent mints. The lock is ``FOR NO KEY UPDATE``:
        it queues other mints but not the foreign-key checks of unrelated inserts.

        Raises:
            ValueError: ``expires_at`` is naive.
            InvalidInviteExpiry: ``expires_at`` is not after now, or is more than
                :data:`MAX_ASSISTANT_INVITE_TTL` ahead.
            NotATeacher: ``teacher_user_id`` is not a teacher account.
            AssistantInviteLimitError: The teacher holds the most live invites allowed.
            TeamError: No unique code after several attempts (astronomically unlikely).
        """
        _require_aware(expires_at, "expires_at")
        issued = datetime.now(UTC)
        if not issued < expires_at <= issued + MAX_ASSISTANT_INVITE_TTL:
            raise InvalidInviteExpiry(
                f"An assistant invite must expire within {MAX_ASSISTANT_INVITE_TTL.days} days"
            )
        lead_role = self._session.scalar(
            select(User.role).where(User.id == teacher_user_id).with_for_update(key_share=True)
        )
        if lead_role is not Role.teacher:
            raise NotATeacher("Only a teacher account can invite assistants")
        live = self._session.scalar(
            select(func.count())
            .select_from(Invite)
            .where(
                Invite.team_teacher_id == teacher_user_id,
                Invite.redeemed_by.is_(None),
                Invite.expires_at > func.now(),
            )
        )
        if int(live or 0) >= MAX_LIVE_ASSISTANT_INVITES:
            raise AssistantInviteLimitError(
                f"A teacher may hold at most {MAX_LIVE_ASSISTANT_INVITES} live assistant invites"
            )
        for _ in range(_INVITE_CODE_ATTEMPTS):
            invite = Invite(
                code=generate_invite_code(),
                role=InviteRole.assistant,
                created_by=teacher_user_id,
                team_teacher_id=teacher_user_id,
                assistant_role=AssistantRole(role),
                expires_at=expires_at,
                reusable=False,
            )
            try:
                with self._session.begin_nested():
                    self._session.add(invite)
                    self._session.flush()
            except IntegrityError as exc:
                if constraint_name(exc) != _INVITE_CODE_CONSTRAINT:
                    raise
                continue
            return invite
        raise TeamError("Could not generate a unique invite code; please retry")

    def redeem_assistant_invite(
        self, *, code: str, user_id: uuid.UUID, now: datetime
    ) -> TeacherMember:
        """Attach ``user_id`` to the invite's teacher as an assistant (spec §2.3).

        The invite row is locked first, so two redemptions of one code serialise and the
        second sees it consumed. An invite is consumed exactly once. Replaying it by the
        same user returns their active row untouched (role and toggles kept). A replay
        after the assistant was removed is refused: the invite is spent, and only a new
        one brings them back. A removed assistant who redeems a fresh invite has the
        same row reactivated (UPDATE, never a second row) with the invite's role and no
        toggles. Nothing is consumed when a check below refuses.

        Raises:
            ValueError: ``now`` is naive.
            AssistantInviteNotFound: No unexpired assistant invite has ``code``.
            AssistantInviteRedeemed: The invite was already used (by anyone), and the
                caller is not its redeemer with an active assistant row.
            NotATeacher: The redeemer is not a teacher account.
            TeamStateError: The redeemer is the lead teacher, or already holds a seat or
                an assistant row (live) with them.
        """
        _require_aware(now, "now")
        invite = self._session.scalars(
            select(Invite).where(Invite.code == code).with_for_update()
        ).first()
        if (
            invite is None
            or invite.role is not InviteRole.assistant
            or invite.team_teacher_id is None
            or invite.assistant_role is None
            or (invite.expires_at is not None and invite.expires_at <= now)
        ):
            raise AssistantInviteNotFound("Unknown assistant invite")
        teacher_id = invite.team_teacher_id
        if invite.redeemed_by is not None:
            if invite.redeemed_by == user_id:
                member = self._member_row(teacher_id, user_id, lock=True)
                if (
                    member is not None
                    and member.kind is TeacherMemberKind.assistant
                    and member.status is TeacherMemberStatus.active
                ):
                    return member
            raise AssistantInviteRedeemed("This assistant invite has already been used")
        if teacher_id == user_id:
            raise TeamStateError("A teacher cannot be their own assistant")
        redeemer_role = self._session.scalar(select(User.role).where(User.id == user_id))
        if redeemer_role is not Role.teacher:
            raise NotATeacher("Only a teacher account can be an assistant")
        member = self._member_row(teacher_id, user_id, lock=True)
        if member is not None and member.kind is not TeacherMemberKind.assistant:
            raise TeamStateError("This account already holds a seat with this teacher")
        if member is not None and member.status is not TeacherMemberStatus.removed:
            raise TeamStateError("This account already assists this teacher")
        if member is None:
            member = self._insert_assistant(teacher_id, user_id, invite.assistant_role)
        else:
            member.status = TeacherMemberStatus.active
            member.leaves_at = None
            member.role_preset = invite.assistant_role
            member.permissions = {}
            member.cap_units = None
            member.cap_period = CapPeriod.month
        invite.redeemed_by = user_id
        invite.redeemed_at = now
        self._session.flush()
        return member

    def list_assistant_invites(self, teacher_user_id: uuid.UUID, *, now: datetime) -> list[Invite]:
        """Return the teacher's unredeemed, unexpired assistant invites, oldest first.

        Raises:
            ValueError: ``now`` is naive.
        """
        _require_aware(now, "now")
        stmt = (
            select(Invite)
            .where(
                Invite.team_teacher_id == teacher_user_id,
                Invite.redeemed_by.is_(None),
                Invite.expires_at > now,
            )
            .order_by(Invite.created_at, Invite.id)
        )
        return list(self._session.scalars(stmt))

    def revoke_assistant_invite(self, teacher_user_id: uuid.UUID, invite_id: uuid.UUID) -> None:
        """Delete the teacher's own unredeemed assistant invite (index R3).

        Locks the invite row, so a revoke racing a redemption of the same code ends with
        exactly one of them winning.

        Raises:
            AssistantInviteNotFound: Unknown, another teacher's, or already redeemed;
                one answer for all three.
        """
        invite = self._session.scalars(
            select(Invite)
            .where(
                Invite.id == invite_id,
                Invite.team_teacher_id == teacher_user_id,
                Invite.redeemed_by.is_(None),
            )
            .with_for_update()
        ).first()
        if invite is None:
            raise AssistantInviteNotFound(f"Unknown assistant invite: {invite_id}")
        self._session.delete(invite)
        self._session.flush()

    def assistant_membership(
        self, assistant_user_id: uuid.UUID, teacher_user_id: uuid.UUID
    ) -> TeacherMember | None:
        """Return the active assistant row linking the two accounts, or ``None``."""
        stmt = select(TeacherMember).where(
            TeacherMember.teacher_user_id == teacher_user_id,
            TeacherMember.member_user_id == assistant_user_id,
            TeacherMember.kind == TeacherMemberKind.assistant,
            TeacherMember.status == TeacherMemberStatus.active,
        )
        return self._session.scalars(stmt).first()

    def memberships_for_assistant(self, assistant_user_id: uuid.UUID) -> list[TeacherMember]:
        """Return every team the account actively assists, oldest first."""
        stmt = (
            select(TeacherMember)
            .where(
                TeacherMember.member_user_id == assistant_user_id,
                TeacherMember.kind == TeacherMemberKind.assistant,
                TeacherMember.status == TeacherMemberStatus.active,
            )
            .order_by(TeacherMember.created_at, TeacherMember.id)
        )
        return list(self._session.scalars(stmt))

    def list_assistants(self, teacher_user_id: uuid.UUID) -> list[TeacherMember]:
        """Return the teacher's active assistants, oldest first."""
        stmt = (
            select(TeacherMember)
            .where(
                TeacherMember.teacher_user_id == teacher_user_id,
                TeacherMember.kind == TeacherMemberKind.assistant,
                TeacherMember.status == TeacherMemberStatus.active,
            )
            .order_by(TeacherMember.created_at, TeacherMember.id)
        )
        return list(self._session.scalars(stmt))

    def update_assistant(
        self,
        member_id: uuid.UUID,
        *,
        role: AssistantRole | None,
        permissions: Mapping[str, object] | None,
    ) -> TeacherMember:
        """Change an assistant's role preset and/or toggles; ``None`` leaves a field as is.

        ``permissions`` replaces the stored overrides (``{}`` clears them). It is checked
        by :func:`~lemely.core.team_permissions.validate_overrides` before anything is
        written, so a refused toggle leaves the role unchanged too. Billing, seats and
        assistants are not team permissions, so no toggle can name them.

        Raises:
            TeamMemberNotFound: No such member.
            TeamStateError: The member is a seat or removed.
            InvalidPermissions: A toggle is not a team permission or not a bool.
        """
        member = self._locked_member(member_id)
        if (
            member.kind is not TeacherMemberKind.assistant
            or member.status is TeacherMemberStatus.removed
        ):
            raise TeamStateError("Only an active assistant has a role")
        if permissions is not None:
            try:
                member.permissions = validate_overrides(permissions)
            except UnknownPermissionError as exc:
                raise InvalidPermissions(str(exc)) from exc
        if role is not None:
            member.role_preset = AssistantRole(role)
        self._session.flush()
        return member

    def remove_assistant(self, member_id: uuid.UUID) -> None:
        """Remove an assistant at once (no month-end period; assistants have no allowance).

        Raises:
            TeamMemberNotFound: No such member.
            TeamStateError: The member is a seat or already removed.
        """
        member = self._locked_member(member_id)
        if (
            member.kind is not TeacherMemberKind.assistant
            or member.status is TeacherMemberStatus.removed
        ):
            raise TeamStateError("Only an active assistant can be removed this way")
        member.status = TeacherMemberStatus.removed
        member.leaves_at = None
        self._session.flush()

    # -- Internals ---------------------------------------------------------------

    def _capacity(self, teacher_user_id: uuid.UUID, *, lock: bool) -> int:
        stmt = (
            select(Subscription.extra_seats, PlanTier.included_seats)
            .join(PlanTier, Subscription.plan_tier_id == PlanTier.id)
            .where(
                Subscription.user_id == teacher_user_id,
                Subscription.status.in_(LIVE_PLAN_STATUSES),
                PlanTier.audience == TEACHER_AUDIENCE,
            )
            .order_by(
                Subscription.payer_user_id.is_(None),  # a paid row beats a manual one (R25)
                Subscription.created_at,
                Subscription.id,
            )
            .limit(1)
        )
        if lock:
            stmt = stmt.with_for_update(of=Subscription)
        row = self._session.execute(stmt).first()
        if row is None:
            return 0
        extra, included = row
        return int(included or 0) + int(extra or 0)

    def _member_row(
        self, teacher_user_id: uuid.UUID, member_user_id: uuid.UUID, *, lock: bool
    ) -> TeacherMember | None:
        stmt = select(TeacherMember).where(
            TeacherMember.teacher_user_id == teacher_user_id,
            TeacherMember.member_user_id == member_user_id,
        )
        if lock:
            stmt = stmt.with_for_update()
        return self._session.scalars(stmt).first()

    def _locked_member(self, member_id: uuid.UUID) -> TeacherMember:
        member = self._session.get(TeacherMember, member_id, with_for_update=True)
        if member is None:
            raise TeamMemberNotFound(f"Unknown team member: {member_id}")
        return member

    def _insert_assistant(
        self, teacher_user_id: uuid.UUID, member_user_id: uuid.UUID, role: AssistantRole
    ) -> TeacherMember:
        """Insert the pair's first row as an assistant.

        The pair row is unique, so a concurrent redemption of a second invite by the same
        user (no row existed to lock) ends in a violation of that constraint here; it is
        reported as the state error it is, and the caller's transaction rolls the invite
        back. Any other violation is not this race and propagates.
        """
        member = TeacherMember(
            teacher_user_id=teacher_user_id,
            member_user_id=member_user_id,
            kind=TeacherMemberKind.assistant,
            role_preset=role,
            permissions={},
            cap_units=None,
            cap_period=CapPeriod.month,
            status=TeacherMemberStatus.active,
        )
        try:
            with self._session.begin_nested():
                self._session.add(member)
                self._session.flush()
        except IntegrityError as exc:
            if constraint_name(exc) != _PAIR_CONSTRAINT:
                raise
            raise TeamStateError("This account already has a place on this team") from exc
        return member

    def _joined_subjects(
        self, student_user_id: uuid.UUID, teacher_user_id: uuid.UUID, *, also: str | None
    ) -> list[str]:
        stmt = (
            select(SchoolClass.subject_code)
            .join(ClassEnrollment, ClassEnrollment.class_id == SchoolClass.id)
            .where(
                ClassEnrollment.student_id == student_user_id,
                SchoolClass.teacher_id == teacher_user_id,
                SchoolClass.school_id.is_(None),
                SchoolClass.subject_code.is_not(None),
            )
            .distinct()
        )
        subjects = {code for code in self._session.scalars(stmt) if code is not None}
        if also is not None:
            subjects.add(also)
        return sorted(subjects)


class TeacherTeamStore:
    """Opens one transaction per unit of team work (routers and the team guard)."""

    def __init__(self, sessionmaker: sessionmaker[Session]) -> None:
        """Wire the store to a session factory."""
        self._sessionmaker = sessionmaker

    @contextmanager
    def transaction(self) -> Iterator[TeacherTeamService]:
        """Yield a service bound to a new transaction; commit on exit, roll back on error."""
        with self._sessionmaker() as session, session.begin():
            yield TeacherTeamService(session)


__all__ = [
    "LIVE_PLAN_STATUSES",
    "MAX_ASSISTANT_INVITE_TTL",
    "MAX_LIVE_ASSISTANT_INVITES",
    "SEAT_ACTIONS_OFF_BY_DEFAULT",
    "TEACHER_AUDIENCE",
    "AssistantInviteLimitError",
    "AssistantInviteNotFound",
    "AssistantInviteRedeemed",
    "InvalidCap",
    "InvalidInviteExpiry",
    "InvalidPermissions",
    "InvalidScope",
    "NoFreeSeat",
    "NotATeacher",
    "TeacherTeamService",
    "TeacherTeamStore",
    "TeamError",
    "TeamMemberNotFound",
    "TeamStateError",
    "default_seat_actions",
    "month_end",
]
