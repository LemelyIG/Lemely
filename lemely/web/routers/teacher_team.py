"""Teacher team routes: seats, scope, caps and assistants (spec §2.2, §2.3, §4.4, §7).

Every route is lead-teacher only. It acts on the caller's own team, keyed by
``auth.user_id``, and never honours ``X-Lemely-Acting-Teacher``: a request that names
anyone but the caller in that header is refused with a 403 (``team_lead_only``), so an
assistant acting for a lead can never manage that lead's seats, caps, invites or
assistants. Without the header, an assistant (a teacher account too) reaches only their
own, separate team. Ids from the path are re-checked against the caller
(``owned_member``, ``revoke_assistant_invite``). An id the caller does not own, an id of
the wrong kind, a removed member and a malformed id all get the same 404.

Names shown are ``users.display_name`` only, never an email (names-only privacy).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status

from lemely.core.team_permissions import effective_permissions
from lemely.db.models.enums import Role
from lemely.db.models.team import AssistantRole, CapPeriod, TeacherMemberKind
from lemely.db.teacher_team_repo import (
    AssistantInviteNotFound,
    TeacherTeamService,
    TeacherTeamStore,
    TeamError,
    TeamMemberNotFound,
)
from lemely.web.deps import (
    ACTING_TEACHER_HEADER,
    AuthContext,
    get_assistant_redeem_limiter,
    get_teacher_team_store,
    require_role,
)
from lemely.web.ratelimit import SlidingWindowLimiter
from lemely.web.schemas_team import (
    AssistantDTO,
    AssistantInviteDTO,
    AssistantInviteListDTO,
    AssistantListDTO,
    CreateAssistantInviteRequestDTO,
    MembershipDTO,
    MembershipListDTO,
    RedeemAssistantInviteRequestDTO,
    SeatCapacityDTO,
    SeatDTO,
    SeatListDTO,
    SetCapRequestDTO,
    SetSeatScopeRequestDTO,
    UpdateAssistantRequestDTO,
)
from lemely.web.team_http import lead_only_error, team_error_to_http

if TYPE_CHECKING:
    from collections.abc import Sequence

    from lemely.db.models import Invite
    from lemely.db.models.team import TeacherMember

router = APIRouter(prefix="/api/teacher/team")


def _lead_teacher(
    auth: Annotated[AuthContext, Depends(require_role(Role.teacher))],
    acting_teacher: Annotated[list[str] | None, Header(alias=ACTING_TEACHER_HEADER)] = None,
) -> AuthContext:
    """Resolve the caller as the lead of their own team, refusing any other acting identity.

    ``require_role`` has already rejected non-teachers. The acting-teacher header is
    meaningful only on routes an assistant may use for their lead
    (``require_team_permission``); here it may be absent or name the caller, and
    anything else (another account, malformed, empty, repeated) is a 403.
    """
    try:
        caller = uuid.UUID(auth.user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access token subject"
        ) from None
    if acting_teacher is not None:
        try:
            names_caller = (
                len(acting_teacher) == 1 and uuid.UUID(acting_teacher[0].strip()) == caller
            )
        except ValueError:
            names_caller = False
        if not names_caller:
            raise lead_only_error()
    return auth


LeadTeacher = Annotated[AuthContext, Depends(_lead_teacher)]
Store = Annotated[TeacherTeamStore, Depends(get_teacher_team_store)]


def _member_uuid(raw: str) -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except ValueError:
        raise team_error_to_http(TeamMemberNotFound(raw)) from None


def _invite_uuid(raw: str) -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except ValueError:
        raise team_error_to_http(AssistantInviteNotFound(raw)) from None


def _sorted_permissions(member: TeacherMember) -> list[str]:
    if member.role_preset is None:
        return []
    granted = effective_permissions(member.role_preset, member.permissions or {})
    return sorted(permission.value for permission in granted)


def _seat_dtos(
    team: TeacherTeamService, seats: Sequence[TeacherMember], *, now: datetime
) -> list[SeatDTO]:
    names = team.display_names([s.member_user_id for s in seats])
    return [
        SeatDTO(
            kind="student_seat",
            memberId=str(seat.id),
            studentId=str(seat.member_user_id),
            studentName=names.get(seat.member_user_id) or "Student",
            status="leaving" if seat.status.value == "leaving" else "active",
            leavesAt=seat.leaves_at,
            scopeSubjects=list(seat.scope_subjects or []),
            scopeActions=list(seat.scope_actions or []),
            capUnits=seat.cap_units,
            capPeriod=seat.cap_period.value,
            capUsedUnits=team.cap_used(seat, now=now),
            meterFraction=team.seat_meter_fraction(seat, now=now),
            joinedAt=seat.created_at,
        )
        for seat in seats
    ]


def _assistant_dtos(
    team: TeacherTeamService, members: Sequence[TeacherMember], *, now: datetime
) -> list[AssistantDTO]:
    names = team.display_names([m.member_user_id for m in members])
    return [
        AssistantDTO(
            kind="assistant",
            memberId=str(member.id),
            assistantId=str(member.member_user_id),
            assistantName=names.get(member.member_user_id) or "Assistant",
            role=member.role_preset.value if member.role_preset is not None else "viewer",
            permissions=dict(member.permissions or {}),
            effectivePermissions=_sorted_permissions(member),
            capUnits=member.cap_units,
            capPeriod=member.cap_period.value,
            capUsedUnits=team.cap_used(member, now=now),
        )
        for member in members
    ]


def _membership_dto(team: TeacherTeamService, member: TeacherMember) -> MembershipDTO:
    names = team.display_names([member.teacher_user_id])
    return MembershipDTO(
        memberId=str(member.id),
        teacherId=str(member.teacher_user_id),
        teacherName=names.get(member.teacher_user_id) or "Teacher",
        role=member.role_preset.value if member.role_preset is not None else "viewer",
        effectivePermissions=_sorted_permissions(member),
    )


def _invite_dto(invite: Invite) -> AssistantInviteDTO:
    role = invite.assistant_role.value if invite.assistant_role is not None else "viewer"
    expires_at = invite.expires_at if invite.expires_at is not None else invite.created_at
    return AssistantInviteDTO(
        inviteId=str(invite.id),
        code=invite.code,
        role=role,
        expiresAt=expires_at,
        createdAt=invite.created_at,
    )


# ── seats ─────────────────────────────────────────────────────────────────────


@router.get("/seats", response_model=SeatListDTO)
def list_seats(auth: LeadTeacher, store: Store) -> SeatListDTO:
    """The caller's active and leaving seats, oldest first, with per-seat usage."""
    now = datetime.now(UTC)
    with store.transaction() as team:
        seats = team.list_seats(uuid.UUID(auth.user_id))
        return SeatListDTO(seats=_seat_dtos(team, seats, now=now))


@router.get("/capacity", response_model=SeatCapacityDTO)
def seat_capacity(auth: LeadTeacher, store: Store) -> SeatCapacityDTO:
    """Seats in the caller's live plan, seats held, and seats free."""
    teacher_id = uuid.UUID(auth.user_id)
    with store.transaction() as team:
        capacity = team.seat_capacity(teacher_id)
        used = team.seats_used(teacher_id)
    return SeatCapacityDTO(capacity=capacity, used=used, free=max(capacity - used, 0))


@router.put("/seats/{member_id}/scope", response_model=SeatDTO)
def set_seat_scope(
    member_id: str, body: SetSeatScopeRequestDTO, auth: LeadTeacher, store: Store
) -> SeatDTO:
    """Replace a seat's subjects and actions (``study_plan`` is opt-in, spec §2.2)."""
    member_uuid = _member_uuid(member_id)
    now = datetime.now(UTC)
    try:
        with store.transaction() as team:
            member = team.owned_member(
                uuid.UUID(auth.user_id), member_uuid, kind=TeacherMemberKind.student_seat
            )
            team.set_scope(member.id, subjects=body.subjects, actions=body.actions)
            return _seat_dtos(team, [member], now=now)[0]
    except TeamError as exc:
        raise team_error_to_http(exc) from exc


@router.delete("/seats/{member_id}", response_model=SeatDTO)
def remove_seat(member_id: str, auth: LeadTeacher, store: Store) -> SeatDTO:
    """Free a seat at the end of the current month (spec §2.2, §5.9)."""
    member_uuid = _member_uuid(member_id)
    now = datetime.now(UTC)
    try:
        with store.transaction() as team:
            member = team.owned_member(
                uuid.UUID(auth.user_id), member_uuid, kind=TeacherMemberKind.student_seat
            )
            team.request_removal(member.id, now=now)
            return _seat_dtos(team, [member], now=now)[0]
    except TeamError as exc:
        raise team_error_to_http(exc) from exc


@router.put("/members/{member_id}/cap", response_model=SeatDTO | AssistantDTO)
def set_member_cap(
    member_id: str, body: SetCapRequestDTO, auth: LeadTeacher, store: Store
) -> SeatDTO | AssistantDTO:
    """Set a seat's overflow cap or an assistant's spend cap; return the updated member.

    The body is a :class:`SeatDTO` for a seat and an :class:`AssistantDTO` for an
    assistant; ``kind`` tells them apart.
    """
    member_uuid = _member_uuid(member_id)
    now = datetime.now(UTC)
    try:
        with store.transaction() as team:
            member = team.owned_member(uuid.UUID(auth.user_id), member_uuid, kind=None)
            team.set_cap(member.id, cap_units=body.capUnits, cap_period=CapPeriod(body.capPeriod))
            if member.kind is TeacherMemberKind.student_seat:
                return _seat_dtos(team, [member], now=now)[0]
            return _assistant_dtos(team, [member], now=now)[0]
    except TeamError as exc:
        raise team_error_to_http(exc) from exc


# ── assistants and invites ────────────────────────────────────────────────────


@router.get("/assistants", response_model=AssistantListDTO)
def list_assistants(auth: LeadTeacher, store: Store) -> AssistantListDTO:
    """The caller's active assistants, oldest first, with per-assistant usage."""
    now = datetime.now(UTC)
    with store.transaction() as team:
        members = team.list_assistants(uuid.UUID(auth.user_id))
        return AssistantListDTO(assistants=_assistant_dtos(team, members, now=now))


@router.post("/assistants/invites", response_model=AssistantInviteDTO, status_code=201)
def create_assistant_invite(
    body: CreateAssistantInviteRequestDTO, auth: LeadTeacher, store: Store
) -> AssistantInviteDTO:
    """Mint a single-use assistant invite for the caller's team (spec §2.3, §4.4)."""
    expires_at = datetime.now(UTC) + timedelta(days=body.expiresInDays)
    try:
        with store.transaction() as team:
            invite = team.create_assistant_invite(
                uuid.UUID(auth.user_id), role=AssistantRole(body.role), expires_at=expires_at
            )
            return _invite_dto(invite)
    except TeamError as exc:
        raise team_error_to_http(exc) from exc


@router.get("/invites", response_model=AssistantInviteListDTO)
def list_assistant_invites(auth: LeadTeacher, store: Store) -> AssistantInviteListDTO:
    """The caller's live (unredeemed, unexpired) assistant invites, oldest first."""
    with store.transaction() as team:
        invites = team.list_assistant_invites(uuid.UUID(auth.user_id), now=datetime.now(UTC))
        return AssistantInviteListDTO(invites=[_invite_dto(i) for i in invites])


@router.delete("/invites/{invite_id}", status_code=204)
def revoke_assistant_invite(invite_id: str, auth: LeadTeacher, store: Store) -> Response:
    """Revoke one of the caller's unredeemed assistant invites (index R3).

    Another teacher's invite, a redeemed one, an unknown id and a malformed id all get
    the same 404.
    """
    invite_uuid = _invite_uuid(invite_id)
    try:
        with store.transaction() as team:
            team.revoke_assistant_invite(uuid.UUID(auth.user_id), invite_uuid)
    except TeamError as exc:
        raise team_error_to_http(exc) from exc
    return Response(status_code=204)


@router.post("/assistants/redeem", response_model=MembershipDTO)
def redeem_assistant_invite(
    body: RedeemAssistantInviteRequestDTO,
    auth: LeadTeacher,
    store: Store,
    limiter: Annotated[SlidingWindowLimiter, Depends(get_assistant_redeem_limiter)],
) -> MembershipDTO:
    """Join a teacher's team as an assistant with one's own teacher account (spec §2.3).

    Rate-limited per caller (spec §7): the 11th attempt in 10 minutes is a 429.
    """
    if not limiter.allow(auth.user_id):
        raise HTTPException(
            status_code=429,
            detail={"code": "rate_limited", "message": "Too many attempts. Try again later."},
            headers={"Retry-After": str(limiter.retry_after(auth.user_id))},
        )
    try:
        with store.transaction() as team:
            member = team.redeem_assistant_invite(
                code=body.code, user_id=uuid.UUID(auth.user_id), now=datetime.now(UTC)
            )
            return _membership_dto(team, member)
    except TeamError as exc:
        raise team_error_to_http(exc) from exc


@router.patch("/assistants/{member_id}", response_model=AssistantDTO)
def update_assistant(
    member_id: str, body: UpdateAssistantRequestDTO, auth: LeadTeacher, store: Store
) -> AssistantDTO:
    """Change an assistant's role preset and/or per-permission toggles."""
    member_uuid = _member_uuid(member_id)
    now = datetime.now(UTC)
    try:
        with store.transaction() as team:
            member = team.owned_member(
                uuid.UUID(auth.user_id), member_uuid, kind=TeacherMemberKind.assistant
            )
            updated = team.update_assistant(
                member.id,
                role=AssistantRole(body.role) if body.role is not None else None,
                permissions=body.permissions,
            )
            return _assistant_dtos(team, [updated], now=now)[0]
    except TeamError as exc:
        raise team_error_to_http(exc) from exc


@router.delete("/assistants/{member_id}", status_code=204)
def remove_assistant(member_id: str, auth: LeadTeacher, store: Store) -> Response:
    """Remove an assistant from the caller's team at once."""
    member_uuid = _member_uuid(member_id)
    try:
        with store.transaction() as team:
            member = team.owned_member(
                uuid.UUID(auth.user_id), member_uuid, kind=TeacherMemberKind.assistant
            )
            team.remove_assistant(member.id)
    except TeamError as exc:
        raise team_error_to_http(exc) from exc
    return Response(status_code=204)


@router.get("/memberships", response_model=MembershipListDTO)
def list_memberships(auth: LeadTeacher, store: Store) -> MembershipListDTO:
    """The teams the caller assists, with their effective permissions (for the UI's switcher)."""
    with store.transaction() as team:
        members = team.memberships_for_assistant(uuid.UUID(auth.user_id))
        return MembershipListDTO(memberships=[_membership_dto(team, m) for m in members])


__all__ = ["router"]
