"""Read models for the usage meter and usage history (billing spec §2.1, §2.4).

Both views answer only about the caller. The meter reads the caller's own grants, seats and
debt. The history lists the caller's own jobs, plus jobs run by someone else that charged a
grant the caller owns or funds through a seat or assistant row they lead. For those it counts
only that part: a seat's teacher never sees what the student paid from the student's own
balance, and never sees a job the seat did not pay for at all.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, NamedTuple

from sqlalchemy import and_, func, or_, select

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
    import uuid
    from collections.abc import Sequence
    from datetime import datetime

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


class _Draw(NamedTuple):
    """One hold or settle entry with the grant it landed on."""

    job_id: uuid.UUID
    kind: UsageEntryKind
    units: int
    grant_kind: GrantKind
    visible: bool
    grant_owner: uuid.UUID
    grant_member_id: uuid.UUID | None
    grant_units: int


def _bucket(draw: _Draw, viewer: uuid.UUID) -> Bucket:
    """Which display bucket a draw belongs to, from the viewer's point of view."""
    if draw.grant_kind is GrantKind.seat_allowance:
        return "seat"
    if not draw.visible:
        return "allowance"
    return "credits" if draw.grant_owner == viewer else "teacher_credits"


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
                UsageGrant.visible.is_(True),
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
            UsageGrant.units,
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
    # A job the caller did not run is theirs to see only if it charged a grant they own or
    # fund through a row they lead. One that charged nothing there (a seat in the chain with
    # nothing left in it, the student's own balance paying) is the runner's private usage.
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
    stmt = select(UsageJob).where(or_(UsageJob.actor_user_id == user_id, charged_to_caller))
    if after is not None:
        stmt = stmt.where(
            or_(
                UsageJob.created_at < after[0],
                and_(UsageJob.created_at == after[0], UsageJob.id < after[1]),
            )
        )
    jobs = list(
        session.scalars(stmt.order_by(UsageJob.created_at.desc(), UsageJob.id.desc()).limit(limit))
    )
    draws = _draws(session, [job.job_id for job in jobs])
    # Debt is shown only where it landed on the caller's own account: a job's debt goes to
    # its payer of last resort, who may be a student or a lead, never the other viewer.
    debts = _debts(session, [job.job_id for job in jobs], user_id)
    funded = set(led_members)
    rows = []
    for job in jobs:
        mine = draws[job.job_id]
        if job.actor_user_id != user_id:
            # Someone else ran this job under the caller's seat or assistant row: only the
            # grants the caller owns, or funds through that row, are the caller's to see.
            mine = [d for d in mine if d.grant_owner == user_id or d.grant_member_id in funded]
        percent = 0.0
        credits = 0
        buckets: set[Bucket] = set()
        for draw in mine:
            if draw.kind is not UsageEntryKind.settle:
                continue
            bucket = _bucket(draw, user_id)
            buckets.add(bucket)
            if bucket in ("allowance", "seat"):
                percent += 100 * abs(draw.units) / draw.grant_units
            else:
                credits += abs(draw.units)
        paid_by: PaidBy = (
            next(iter(buckets)) if len(buckets) == 1 else "mixed" if buckets else "none"
        )
        # The estimate is shown in the terms of the grant that took the first hold.
        first_hold = next((d for d in mine if d.kind is UsageEntryKind.hold), None)
        estimate_percent: tuple[float, float] | None = None
        estimate_credits: tuple[int, int] | None = None
        if first_hold is not None and _bucket(first_hold, user_id) in ("allowance", "seat"):
            estimate_percent = (
                _percent(job.estimate_low, first_hold.grant_units),
                _percent(job.estimate_high, first_hold.grant_units),
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
                percent_of_plan=round(percent, 1) if percent > 0 else None,
                credits=credits if credits > 0 else None,
                debt_credits=debts.get(job.job_id) or None,
                estimate_percent_of_plan=estimate_percent,
                estimate_credits=estimate_credits,
            )
        )
    return rows
