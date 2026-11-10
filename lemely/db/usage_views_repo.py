"""Read models for the usage meter and usage history (billing spec §2.1, §2.4).

Both views answer only about the caller. The meter reads the caller's own grants, seats and
debt. The history lists the caller's own jobs, plus jobs run by someone else that charged a
grant the caller owns or funds through a seat or assistant row they lead. For those it counts
only that part: a seat's teacher never sees what the student paid from the student's own
balance, and never sees a job the seat did not pay for at all.

What is "the plan" and what is "credits", the same on the meter, the estimate and the history:

* The plan is a ``period_allowance`` (a subscription's hidden monthly allowance) or a
  ``seat_allowance`` (a teacher's hidden grant to one student). It is shown only as a
  percentage, never as units. Its size, the denominator of every percentage, is the sum of that
  owner's grants of that kind (for a seat, of that seat) that are live at the moment in
  question: ``allowance_units`` for the estimate, the job's creation time for the history.
* Everything else the caller can spend is credits, shown as units: purchased packs, top-ups,
  refunds, adjustments and the hidden one-time ``signup`` grant. So a student who only has the
  free start has no plan: the meter lists it as a credit lot, the estimate quotes credits with
  no percentage, and the history charges credits with no percentage.
* A history row reports one plan percentage, for the plan its chain drew on first (the plan the
  estimate quotes), capped at 100. A job that drew on several plans, or on a plan and credits,
  is ``mixed``; percentages of different plans are never added together.
* A caller who acts for a lead (an assistant) sees the lead's plan as percentages only, in the
  estimate and here, so the plan's size cannot be derived from what the API returns.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, NamedTuple

from sqlalchemy import and_, func, or_, select

from lemely.core.usage_types import GrantScope, Payer, payer_from_json
from lemely.db.models.team import TeacherMember, TeacherMemberKind, TeacherMemberStatus
from lemely.db.models.usage import (
    GrantKind,
    UsageDebt,
    UsageEntry,
    UsageEntryKind,
    UsageGrant,
    UsageGrantBalance,
    UsageJob,
)
from lemely.db.usage_ledger_repo import UsageLedger

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from sqlalchemy import Select
    from sqlalchemy.orm import Session
    from sqlalchemy.sql import ColumnElement


@dataclass(frozen=True)
class CreditLot:
    remaining: int
    expires_at: datetime | None


@dataclass(frozen=True)
class SeatMeter:
    teacher_member_id: uuid.UUID
    teacher_user_id: uuid.UUID
    fraction: float | None
    resets_at: datetime | None


@dataclass(frozen=True)
class MeterView:
    allowance_fraction: float | None
    allowance_resets_at: datetime | None
    credits_balance: int
    credit_lots: list[CreditLot]
    seats: list[SeatMeter]
    debt_units: int


Bucket = Literal["allowance", "seat", "credits", "teacher_credits"]
PaidBy = Literal["allowance", "seat", "credits", "teacher_credits", "mixed", "none"]


@dataclass(frozen=True)
class HistoryRow:
    """One job, displayed without allowance unit counts (spec §2.1 hidden allowance).

    Allowance and seat portions are a percentage of the grant they drew on; credits
    portions (own or a teacher's) are credit units. ``paid_by`` is ``none`` for a job that
    charged nothing (open, released, expired, or settled at 0).
    """

    row_id: uuid.UUID
    job_id: uuid.UUID
    action: str
    status: str
    actor_user_id: uuid.UUID
    created_at: datetime
    settled_at: datetime | None
    paid_by: PaidBy
    percent_of_plan: float | None
    credits: int | None
    debt_credits: int | None
    estimate_percent_of_plan: tuple[float, float] | None
    estimate_credits: tuple[int, int] | None


_PLAN_KINDS = (GrantKind.period_allowance, GrantKind.seat_allowance)

#: The plan a draw belongs to: ``(owner, seat row)``; the seat row is ``None`` for a period plan.
PlanScope = tuple[uuid.UUID, uuid.UUID | None]


class _Draw(NamedTuple):
    """One hold or settle entry with the grant it landed on."""

    job_id: uuid.UUID
    kind: UsageEntryKind
    units: int
    grant_kind: GrantKind
    visible: bool
    grant_owner: uuid.UUID
    grant_member_id: uuid.UUID | None


def _bucket(draw: _Draw, viewer: uuid.UUID) -> Bucket:
    """Which display bucket a draw belongs to, from the viewer's point of view."""
    if draw.grant_kind is GrantKind.seat_allowance:
        return "seat"
    if draw.grant_kind is GrantKind.period_allowance:
        return "allowance"
    return "credits" if draw.grant_owner == viewer else "teacher_credits"


def _plan_scope(draw: _Draw) -> PlanScope | None:
    """The plan a draw belongs to, or ``None`` for credits."""
    if draw.grant_kind in _PLAN_KINDS:
        return (draw.grant_owner, draw.grant_member_id)
    return None


def _chain_index(draw: _Draw, chain: Sequence[Payer]) -> int:
    """Position of the first payer of the job's chain that can spend this draw's grant."""
    for index, payer in enumerate(chain):
        if payer.owner_user_id != draw.grant_owner:
            continue
        if payer.scope is GrantScope.SEAT:
            fits = (
                draw.grant_kind is GrantKind.seat_allowance
                and draw.grant_member_id == payer.teacher_member_id
            )
        elif payer.scope is GrantScope.ALLOWANCE:
            fits = not draw.visible and draw.grant_member_id is None
        else:
            fits = draw.visible
        if fits:
            return index
    return len(chain)


def _percent(units: int, of: int) -> float:
    return round(100 * units / of, 1)


def _live(now: datetime) -> ColumnElement[bool]:
    return or_(UsageGrant.expires_at.is_(None), UsageGrant.expires_at > now)


def meter_view(session: Session, *, user_id: uuid.UUID, now: datetime) -> MeterView:
    """The caller's allowance meter, credit lots by expiry, seat meters and debt."""
    ledger = UsageLedger(session)
    allowance_resets_at = session.scalar(
        select(func.min(UsageGrant.expires_at)).where(
            UsageGrant.owner_user_id == user_id,
            UsageGrant.kind == GrantKind.period_allowance,
            UsageGrant.expires_at > now,
        )
    )
    spendable = UsageGrantBalance.remaining - UsageGrantBalance.held
    lots = [
        CreditLot(remaining=int(remaining), expires_at=expires_at)
        for remaining, expires_at in session.execute(
            select(spendable, UsageGrant.expires_at)
            .join(UsageGrant, UsageGrant.id == UsageGrantBalance.grant_id)
            .where(
                UsageGrant.owner_user_id == user_id,
                UsageGrant.kind.not_in(_PLAN_KINDS),
                _live(now),
                spendable > 0,
            )
            .order_by(UsageGrant.expires_at.asc().nulls_last(), UsageGrant.id)
        )
    ]
    seats = []
    for member in session.scalars(
        select(TeacherMember)
        .where(
            TeacherMember.member_user_id == user_id,
            TeacherMember.kind == TeacherMemberKind.student_seat,
            TeacherMember.status.in_((TeacherMemberStatus.active, TeacherMemberStatus.leaving)),
        )
        .order_by(TeacherMember.created_at, TeacherMember.id)
    ):
        resets_at = session.scalar(
            select(func.max(UsageGrant.expires_at)).where(
                UsageGrant.owner_user_id == user_id,
                UsageGrant.kind == GrantKind.seat_allowance,
                UsageGrant.teacher_member_id == member.id,
                UsageGrant.expires_at > now,
            )
        )
        seats.append(
            SeatMeter(
                teacher_member_id=member.id,
                teacher_user_id=member.teacher_user_id,
                fraction=ledger.meter_fraction(user_id, teacher_member_id=member.id, now=now),
                resets_at=resets_at,
            )
        )
    debt = session.scalar(
        select(func.coalesce(func.sum(UsageDebt.outstanding), 0)).where(
            UsageDebt.owner_user_id == user_id
        )
    )
    return MeterView(
        allowance_fraction=ledger.meter_fraction(user_id, teacher_member_id=None, now=now),
        allowance_resets_at=allowance_resets_at,
        credits_balance=sum(lot.remaining for lot in lots),
        credit_lots=lots,
        seats=seats,
        debt_units=int(debt or 0),
    )


def _draws(session: Session, job_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, list[_Draw]]:
    """Holds and settles of these jobs in the ledger's spend order, grouped by job."""
    grouped: dict[uuid.UUID, list[_Draw]] = defaultdict(list)
    if not job_ids:
        return grouped
    for row in session.execute(
        select(
            UsageEntry.job_id,
            UsageEntry.kind,
            UsageEntry.units,
            UsageGrant.kind,
            UsageGrant.visible,
            UsageGrant.owner_user_id,
            UsageGrant.teacher_member_id,
        )
        .join(UsageGrant, UsageGrant.id == UsageEntry.grant_id)
        .where(
            UsageEntry.job_id.in_(job_ids),
            UsageEntry.kind.in_((UsageEntryKind.settle, UsageEntryKind.hold)),
        )
        # The ledger's spend order (priority, soonest expiry, oldest, id), so the first hold
        # of a job is the grant its chain drew on first, not an arbitrary one.
        .order_by(
            UsageGrant.priority,
            UsageGrant.expires_at.asc().nulls_last(),
            UsageGrant.effective_at,
            UsageGrant.id,
            UsageEntry.id,
        )
    ):
        draw = _Draw(*row)
        grouped[draw.job_id].append(draw)
    return grouped


class _PlanGrant(NamedTuple):
    units: int
    effective_at: datetime
    expires_at: datetime | None


def _plan_grants(session: Session, owners: set[uuid.UUID]) -> dict[PlanScope, list[_PlanGrant]]:
    """Every plan grant of these owners, by plan, to size a plan at a moment."""
    grouped: dict[PlanScope, list[_PlanGrant]] = defaultdict(list)
    if not owners:
        return grouped
    for owner, member, units, effective_at, expires_at in session.execute(
        select(
            UsageGrant.owner_user_id,
            UsageGrant.teacher_member_id,
            UsageGrant.units,
            UsageGrant.effective_at,
            UsageGrant.expires_at,
        ).where(UsageGrant.owner_user_id.in_(owners), UsageGrant.kind.in_(_PLAN_KINDS))
    ):
        grouped[(owner, member)].append(_PlanGrant(int(units), effective_at, expires_at))
    return grouped


def _plan_size(grants: Sequence[_PlanGrant], at: datetime) -> int:
    """Units of the plan live at ``at``: the estimate's denominator (``allowance_units``).

    A job can settle after its grants lapsed (a settle may draw an expired grant), so a plan
    with nothing live at ``at`` is sized by all its grants rather than divided by zero.
    """
    live = sum(
        g.units
        for g in grants
        if g.effective_at <= at and (g.expires_at is None or g.expires_at > at)
    )
    return live or sum(g.units for g in grants) or 1


def _debts(
    session: Session, job_ids: Sequence[uuid.UUID], owner: uuid.UUID
) -> dict[uuid.UUID, int]:
    """Units of debt these jobs created on ``owner``'s own account, by job."""
    if not job_ids:
        return {}
    return {
        job_id: int(units)
        for job_id, units in session.execute(
            select(UsageDebt.job_id, func.sum(UsageDebt.units))
            .where(UsageDebt.job_id.in_(job_ids), UsageDebt.owner_user_id == owner)
            .group_by(UsageDebt.job_id)
        )
        if job_id is not None
    }


def history_jobs_statement(
    user_id: uuid.UUID,
    *,
    led_members: Sequence[uuid.UUID],
    after: tuple[datetime, uuid.UUID] | None,
    limit: int,
) -> Select[tuple[UsageJob]]:
    """The jobs on one history page, newest first.

    A caller always sees the jobs they ran (``ix_usage_jobs_actor_created``). Nobody else can
    draw on a user's grants except through a seat or assistant row that user leads, so only a
    caller who leads a row can also be a funder, and only for a job that names such a row. A
    job someone else ran is theirs to see only if it charged a grant they own or fund through
    a row they lead; one that charged nothing there (a seat in the chain with nothing left in
    it, the student's own balance paying) is the runner's private usage.

    The funder branch is added only for a caller who leads a row: a correlated ``EXISTS`` in an
    ``OR`` defeats the index and would scan the whole ledger for every plain student.
    ``usage_jobs.teacher_member_id`` has no index of its own, so a lead still scans (a later
    migration should add one, or drive the funder half from ``usage_entries``).
    """
    visible = UsageJob.actor_user_id == user_id
    if led_members:
        charged_to_caller = (
            select(UsageEntry.id)
            .join(UsageGrant, UsageGrant.id == UsageEntry.grant_id)
            .where(
                UsageEntry.job_id == UsageJob.job_id,
                UsageEntry.kind == UsageEntryKind.settle,
                or_(
                    UsageGrant.owner_user_id == user_id,
                    UsageGrant.teacher_member_id.in_(led_members),
                ),
            )
            .exists()
        )
        visible = or_(visible, and_(UsageJob.teacher_member_id.is_not(None), charged_to_caller))
    stmt = select(UsageJob).where(visible)
    if after is not None:
        stmt = stmt.where(
            or_(
                UsageJob.created_at < after[0],
                and_(UsageJob.created_at == after[0], UsageJob.id < after[1]),
            )
        )
    return stmt.order_by(UsageJob.created_at.desc(), UsageJob.id.desc()).limit(limit)


def history_page(
    session: Session,
    *,
    user_id: uuid.UUID,
    limit: int,
    after: tuple[datetime, uuid.UUID] | None,
) -> list[HistoryRow]:
    """Jobs the caller ran, plus jobs run under their seats and assistants, newest first."""
    led_members = list(
        session.scalars(select(TeacherMember.id).where(TeacherMember.teacher_user_id == user_id))
    )
    jobs = list(
        session.scalars(
            history_jobs_statement(user_id, led_members=led_members, after=after, limit=limit)
        )
    )
    draws = _draws(session, [job.job_id for job in jobs])
    plans = _plan_grants(
        session, {d.grant_owner for ds in draws.values() for d in ds if d.grant_kind in _PLAN_KINDS}
    )
    # Debt is shown only where it landed on the caller's own account: a job's debt goes to
    # its payer of last resort, who may be a student or a lead, never the other viewer.
    debts = _debts(session, [job.job_id for job in jobs], user_id)
    funded = set(led_members)
    rows = []
    for job in jobs:
        chain = [payer_from_json(p) for p in job.payer_chain]
        # In the order the job's chain drew on them, so "first" is the plan the estimate quoted.
        mine = sorted(draws[job.job_id], key=lambda d: _chain_index(d, chain))
        if job.actor_user_id != user_id:
            # Someone else ran this job under the caller's seat or assistant row: only the
            # grants the caller owns, or funds through that row, are the caller's to see.
            mine = [d for d in mine if d.grant_owner == user_id or d.grant_member_id in funded]
        settles = [d for d in mine if d.kind is UsageEntryKind.settle]
        parts: set[tuple[Bucket, PlanScope | None]] = {
            (_bucket(d, user_id), _plan_scope(d)) for d in settles
        }
        paid_by: PaidBy = next(iter(parts))[0] if len(parts) == 1 else "mixed" if parts else "none"
        credits = sum(abs(d.units) for d in settles if _plan_scope(d) is None)
        percent: float | None = None
        first_scope = next((sc for d in settles if (sc := _plan_scope(d)) is not None), None)
        if first_scope is not None:
            drawn = sum(abs(d.units) for d in settles if _plan_scope(d) == first_scope)
            size = _plan_size(plans[first_scope], job.created_at)
            percent = min(100.0, _percent(drawn, size))
        # The estimate is shown in the terms of the first thing the chain held on.
        first_hold = next((d for d in mine if d.kind is UsageEntryKind.hold), None)
        estimate_percent: tuple[float, float] | None = None
        estimate_credits: tuple[int, int] | None = None
        hold_scope = _plan_scope(first_hold) if first_hold is not None else None
        if hold_scope is not None:
            size = _plan_size(plans[hold_scope], job.created_at)
            estimate_percent = (
                min(100.0, _percent(job.estimate_low, size)),
                min(100.0, _percent(job.estimate_high, size)),
            )
        else:
            estimate_credits = (job.estimate_low, job.estimate_high)
        rows.append(
            HistoryRow(
                row_id=job.id,
                job_id=job.job_id,
                action=job.action,
                status=job.status.value,
                actor_user_id=job.actor_user_id,
                created_at=job.created_at,
                settled_at=job.settled_at,
                paid_by=paid_by,
                percent_of_plan=percent if percent else None,
                credits=credits if credits > 0 else None,
                debt_credits=debts.get(job.job_id) or None,
                estimate_percent_of_plan=estimate_percent,
                estimate_credits=estimate_credits,
            )
        )
    return rows
