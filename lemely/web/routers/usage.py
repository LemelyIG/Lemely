"""``/api/usage/*``: the estimate shown before an action, the meter, the history.

Every signed-in role may call these routes; each answers only about the caller. The
estimate never trusts client numbers for the record it describes: the subject and the
countable inputs of an attempt, question or assignment are read on the server, from a record
the caller owns, exactly as the metered route itself will read them. Another user's record
is the same 404 as a missing one. The estimate writes nothing to the ledger (it may seed a
missing reference catalogue), and is rate-limited per user (spec §7).
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime
from functools import lru_cache
from typing import TYPE_CHECKING, Annotated, NoReturn, cast

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import select

from lemely.core.keyset import CursorError, decode_cursor, encode_cursor
from lemely.core.metered_actions import MeteredAction
from lemely.core.team_permissions import TeamPermission
from lemely.db.models.enums import Role
from lemely.db.models.team import TeacherMember
from lemely.db.teacher_team_repo import TeacherTeamService
from lemely.db.usage_context_repo import quiz_assignment_target, self_review_target
from lemely.db.usage_views_repo import history_page, meter_view, plan_remaining
from lemely.web.deps import (
    ACTING_TEACHER_HEADER,
    AuthContext,
    get_auth_context,
    team_lead_unavailable_error,
    team_permission_denied_error,
)
from lemely.web.ratelimit import SlidingWindowLimiter
from lemely.web.schemas_usage import (
    CreditLotDTO,
    EstimateDTO,
    EstimatePayer,
    EstimateRequestDTO,
    SeatMeterDTO,
    UsageHistoryDTO,
    UsageJobDTO,
    UsageMeterDTO,
)
from lemely.web.usage import UsageMeter, UsageRequest, get_usage_meter, request_from_auth

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/usage")

_HISTORY_CURSOR = "usage_history"

#: Spec §7: an estimate is cheap for the caller to ask for and costs a handful of reads.
#: 60 a minute is a screen refreshing its quote on every keystroke, not a loop.
_ESTIMATE_LIMIT = 60
_ESTIMATE_WINDOW_SECONDS = 60.0


@lru_cache(maxsize=1)
def get_usage_estimate_limiter() -> SlidingWindowLimiter:
    """The per-user limiter on ``POST /api/usage/estimate`` (process-wide)."""
    return SlidingWindowLimiter(
        limit=_ESTIMATE_LIMIT, window_seconds=_ESTIMATE_WINDOW_SECONDS, clock=time.monotonic
    )


def _caller_id(auth: AuthContext) -> uuid.UUID:
    """The caller's user id; a token whose subject is not one is a 401, as on the team guard."""
    try:
        return uuid.UUID(auth.user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access token subject"
        ) from None


def _missing(field: str) -> NoReturn:
    raise HTTPException(status_code=422, detail=f"{field} is required for this action")


#: The team permission each team-billable action's route asks for (phase 03 adoption table).
_TEAM_PERMISSION: dict[MeteredAction, TeamPermission] = {
    MeteredAction.MARK_PAPER: TeamPermission.MARK,
    MeteredAction.REGRADE: TeamPermission.REGRADE,
    MeteredAction.GENERATE_QUIZ: TeamPermission.GENERATE_QUIZ,
    MeteredAction.PREVIEW_QUIZ: TeamPermission.GENERATE_QUIZ,
}


def _assistant_row(
    actor_id: uuid.UUID, lead_id: uuid.UUID, perm: TeamPermission
) -> Callable[[Session], tuple[uuid.UUID | None, bool]]:
    """``assistant_access`` as a read: the granting row's id (or ``None``) and the school flag."""

    def read(session: Session) -> tuple[uuid.UUID | None, bool]:
        access = TeacherTeamService(session).assistant_access(actor_id, lead_id, perm)
        return (access.member.id if access.member is not None else None, access.lead_unavailable)

    return read


def _acting_member(
    meter: UsageMeter,
    auth: AuthContext,
    actor_id: uuid.UUID,
    action: MeteredAction,
    acting_teacher: list[str] | None,
) -> uuid.UUID | None:
    """The assistant row to bill under ``X-Lemely-Acting-Teacher``, or ``None`` (own chain).

    The same decision ``require_team_permission`` makes, through the same
    ``TeacherTeamService.assistant_access``: no header, or a header naming the caller, is the
    own chain. Otherwise the caller must be a teacher holding the action's team permission
    under that lead. Anything else is 403: a malformed or repeated header, an action with no
    team permission, a stranger, a viewer (``team_permission_denied``), and a lead who holds
    school data, which only an assistant of that lead is told (``team_lead_unavailable``).
    """
    if acting_teacher is None:
        return None
    if len(acting_teacher) != 1:
        raise team_permission_denied_error()
    try:
        lead_id = uuid.UUID(acting_teacher[0].strip())
    except ValueError:
        raise team_permission_denied_error() from None
    if lead_id == actor_id:
        return None
    perm = _TEAM_PERMISSION.get(action)
    if perm is None or auth.role != Role.teacher.value:
        raise team_permission_denied_error()
    # Read the row's id inside the session, as the team guard does.
    member_id, lead_unavailable = meter.read(_assistant_row(actor_id, lead_id, perm))
    if lead_unavailable:
        raise team_lead_unavailable_error()
    if member_id is None:
        raise team_permission_denied_error()
    log.info(
        "team_acting",
        actor_user_id=str(actor_id),
        lead_teacher_user_id=str(lead_id),
        member_id=str(member_id),
        permission=str(perm),
    )
    return member_id


def _lead_of(meter: UsageMeter, member_id: uuid.UUID) -> uuid.UUID:
    """The lead teacher an assistant row works for."""
    lead = meter.read(
        lambda session: session.scalar(
            select(TeacherMember.teacher_user_id).where(TeacherMember.id == member_id)
        )
    )
    if lead is None:
        raise team_permission_denied_error()
    return lead


def _capped(percent: int | None) -> int | None:
    """An estimate percentage never reads above the whole plan (history caps the same way)."""
    return None if percent is None else min(100, percent)


def _estimate_request(
    meter: UsageMeter,
    auth: AuthContext,
    actor_id: uuid.UUID,
    body: EstimateRequestDTO,
    acting_teacher: list[str] | None,
) -> UsageRequest:
    action = body.action
    role = Role(auth.role)
    # R4: an assistant's estimate for team work is quoted against the lead's chain, read
    # from the same header the metered route's `require_team_permission` reads, and only
    # when the assistant holds the permission that route asks for.
    member = _acting_member(meter, auth, actor_id, action, acting_teacher)
    if action is MeteredAction.MARK_PAPER:
        return request_from_auth(
            auth, action, subject_pending=role is Role.student, assistant_member_id=member
        )
    if action is MeteredAction.REGRADE:
        return request_from_auth(auth, action, assistant_member_id=member)
    if action in (MeteredAction.PREVIEW_QUIZ, MeteredAction.GENERATE_QUIZ):
        if body.count is None:
            _missing("count")
        return request_from_auth(auth, action, input_count=body.count, assistant_member_id=member)
    if action is MeteredAction.SELF_REVIEW:
        if body.attemptId is None or body.questionResultId is None:
            _missing("attemptId and questionResultId")
        attempt_id, question_id = str(body.attemptId), str(body.questionResultId)
        review = meter.resolve_target(
            lambda session: self_review_target(
                session,
                student_id=str(actor_id),
                attempt_id=attempt_id,
                question_result_id=question_id,
            )
        )
        if review is None:
            raise HTTPException(status_code=404, detail="No such question")
        return request_from_auth(
            auth, action, subject_code=review.subject_code, input_count=review.input_count
        )
    if action is MeteredAction.MARK_QUIZ:
        if body.assignmentId is None:
            _missing("assignmentId")
        assignment_id = str(body.assignmentId)
        quiz = meter.resolve_target(
            lambda session: quiz_assignment_target(
                session, student_id=str(actor_id), assignment_id=assignment_id
            )
        )
        if quiz is None:
            raise HTTPException(status_code=404, detail="No such assignment")
        return request_from_auth(
            auth, action, subject_code=quiz.subject_code, input_count=quiz.input_count
        )
    if action is MeteredAction.GENERATE_FLASHCARDS:
        if body.subjectCode is None or body.origin is None or body.count is None:
            _missing("subjectCode, origin and count")
        # The route's rule (``_seat_subject``): only a weakness deck has a topic the server
        # picks, so only it can be seat-paid; a topic deck is billed to the student's own
        # allowance and credits whatever subject it names.
        seat_subject = body.subjectCode if body.origin == "weakness" else None
        return request_from_auth(auth, action, subject_code=seat_subject, input_count=body.count)
    if body.subjectCode is None:  # MeteredAction.STUDY_PLAN
        _missing("subjectCode")
    return request_from_auth(auth, action, subject_code=body.subjectCode)


@router.post("/estimate", response_model=EstimateDTO)
def estimate_usage(
    body: EstimateRequestDTO,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    meter: Annotated[UsageMeter, Depends(get_usage_meter)],
    limiter: Annotated[SlidingWindowLimiter, Depends(get_usage_estimate_limiter)],
    acting_teacher: Annotated[list[str] | None, Header(alias=ACTING_TEACHER_HEADER)] = None,
) -> EstimateDTO:
    """The range the caller will see before an action ("3-5 credits" / "2-4% of your plan")."""
    actor_id = _caller_id(auth)
    if not limiter.allow(auth.user_id):
        retry = limiter.retry_after(auth.user_id)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many estimates; retry in {retry}s.",
            headers={"Retry-After": str(retry)},
        )
    request = _estimate_request(meter, auth, actor_id, body, acting_teacher)
    view = meter.estimate(request)
    member = request.assistant_member_id
    payer = view.payer
    percent_low, percent_high = view.percent_low, view.percent_high
    if payer == "allowance":
        # The hidden allowance scope also holds the one-time signup grant. A percentage is
        # only true while a live plan has something left to spend; otherwise credits pay, as
        # the meter and the history say.
        plan_owner = actor_id if member is None else _lead_of(meter, member)
        left = meter.read(
            lambda session: plan_remaining(session, owner_user_id=plan_owner, now=meter.now())
        )
        if percent_low is None or left <= 0:
            payer, percent_low, percent_high = "credits", None, None
    if member is not None:
        # Units are the same for every caller, so units beside a percentage of the lead's
        # plan would give its size away: an assistant is told the units and who pays only.
        percent_low = percent_high = None
    return EstimateDTO(
        low=view.low,
        high=view.high,
        payer=cast("EstimatePayer", payer),
        percentLow=_capped(percent_low),
        percentHigh=_capped(percent_high),
        blockedReason=view.blocked_reason.value if view.blocked_reason is not None else None,
    )


@router.get("/meter", response_model=UsageMeterDTO)
def usage_meter(
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    meter: Annotated[UsageMeter, Depends(get_usage_meter)],
) -> UsageMeterDTO:
    """The caller's allowance meter, credits with expiry breakdown, seat meters and debt."""
    user_id, now = _caller_id(auth), meter.now()
    view = meter.read(lambda session: meter_view(session, user_id=user_id, now=now))
    return UsageMeterDTO(
        allowanceFraction=view.allowance_fraction,
        allowanceResetsAt=view.allowance_resets_at,
        creditsBalance=view.credits_balance,
        creditLots=[
            CreditLotDTO(remaining=lot.remaining, expiresAt=lot.expires_at)
            for lot in view.credit_lots
        ],
        seats=[
            SeatMeterDTO(
                teacherMemberId=str(s.teacher_member_id),
                teacherUserId=str(s.teacher_user_id),
                fraction=s.fraction,
                resetsAt=s.resets_at,
            )
            for s in view.seats
        ],
        debtUnits=view.debt_units,
    )


def _decode_history_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    """The page start a client cursor names. Anything this route did not mint is a 400."""
    try:
        created_at, row_id = decode_cursor(
            cursor, endpoint=_HISTORY_CURSOR, types=(datetime, uuid.UUID)
        )
    except CursorError as exc:
        raise HTTPException(status_code=400, detail="Invalid cursor") from exc
    if not isinstance(created_at, datetime) or not isinstance(row_id, uuid.UUID):
        raise HTTPException(status_code=400, detail="Invalid cursor")
    return created_at, row_id


@router.get("/history", response_model=UsageHistoryDTO)
def usage_history(
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    meter: Annotated[UsageMeter, Depends(get_usage_meter)],
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: str | None = None,
) -> UsageHistoryDTO:
    """Each job with its estimate range and actual charge (spec §2.4: no usage receipts)."""
    user_id = _caller_id(auth)
    after = _decode_history_cursor(cursor) if cursor is not None else None
    rows = meter.read(
        lambda session: history_page(session, user_id=user_id, limit=limit + 1, after=after)
    )
    page = rows[:limit]
    next_cursor = (
        encode_cursor(_HISTORY_CURSOR, [page[-1].created_at, page[-1].row_id])
        if len(rows) > limit
        else None
    )
    return UsageHistoryDTO(
        jobs=[
            UsageJobDTO(
                jobId=str(r.job_id),
                action=r.action,
                status=r.status,
                paidBy=r.paid_by,
                percentOfPlan=r.percent_of_plan,
                credits=r.credits,
                debtCredits=r.debt_credits,
                estimatePercentOfPlan=(
                    list(r.estimate_percent_of_plan) if r.estimate_percent_of_plan else None
                ),
                estimateCredits=list(r.estimate_credits) if r.estimate_credits else None,
                actorUserId=str(r.actor_user_id),
                createdAt=r.created_at,
                settledAt=r.settled_at,
            )
            for r in page
        ],
        nextCursor=next_cursor,
    )
