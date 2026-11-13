"""Monthly seat allowances for seated students (Paymob billing spec §2.2, §5.9).

While a teacher's plan is live (``active`` or ``past_due``; monthly or yearly), each active
``student_seat`` gets one ``seat_allowance`` grant per UTC calendar month. The grant is owned by
the student, carries the ``teacher_member_id`` (so it pays only for in-scope work) and expires at
the month end. A seat claimed mid-month gets an allowance prorated to the days left, today
included. The idempotency key ``seat:{member_id}:{YYYY-MM}`` is the dedupe
``(teacher_member_id, month_start)``, so removing and re-claiming a seat inside one month never
grants twice. A lapsed plan issues nothing; existing grants run out. The ledger never uses a seat
grant to repay the student's own debt (index R13).

Two entry points:

* :func:`grant_seat_allowance_on_claim` writes in the caller's session and never commits. The
  class-join claim calls it inside a savepoint (``TeacherTeamService.claim_seat_for_class_join``).
* :func:`grant_monthly_seat_allowances` is the ``seats.monthly_allowance`` sweeper job. It reads a
  bounded list of seats that lack this month's grant, then grants each in its own transaction: a
  seat whose grant fails is alerted and skipped, and the next tick repairs it.

**Lock order** (``lemely.db.teacher_team_repo`` docstring): the teacher's live subscription row,
then the member row, then the ledger. This module must not import ``teacher_team_repo`` (that
module imports this one), so the month arithmetic comes from ``lemely.core.subscription_rules``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import sqlalchemy as sa
import structlog
from sqlalchemy import select

from lemely.core.subscription_rules import calendar_month_bounds, start_of_day
from lemely.core.usage_pricing import prorate_units
from lemely.db.models.billing import PLAN_LIVE_STATUSES, PlanAudience, PlanTier, Subscription
from lemely.db.models.team import TeacherMember, TeacherMemberKind, TeacherMemberStatus
from lemely.db.models.usage import GrantKind, UsageGrant
from lemely.db.usage_ledger_repo import UsageLedger

if TYPE_CHECKING:
    import uuid
    from datetime import datetime

    from sqlalchemy.orm import Session, sessionmaker

log = structlog.get_logger(__name__)
alerts = structlog.get_logger("lemely.db.seat_allowance_repo")

SEAT_GRANT_BATCH: Final = 500
"""Most seats one monthly run grants; a full batch is logged and the next tick resumes."""


def seat_grant_key(member_id: uuid.UUID, month_start: datetime) -> str:
    """The grant idempotency key for one seat and one month."""
    return f"seat:{member_id}:{month_start:%Y-%m}"


# Which of a teacher's live plans counts: a paid row beats a manual one, then the oldest (R25).
_PLAN_ORDER = (Subscription.payer_user_id.is_(None), Subscription.created_at, Subscription.id)


def _live_teacher_tier(
    session: Session, teacher_user_id: uuid.UUID, *, lock: bool
) -> PlanTier | None:
    """The tier of the teacher's counted live plan (index R25), or ``None`` without one.

    ``lock`` takes ``FOR UPDATE`` on that subscription row: step 1 of the lock order. The claim
    already holds it, so there it is a no-op re-lock.
    """
    stmt = (
        select(PlanTier)
        .join(Subscription, Subscription.plan_tier_id == PlanTier.id)
        .where(
            Subscription.user_id == teacher_user_id,
            Subscription.status.in_(PLAN_LIVE_STATUSES),
            PlanTier.audience == PlanAudience.teacher,
        )
        .order_by(*_PLAN_ORDER)
        .limit(1)
    )
    if lock:
        stmt = stmt.with_for_update(of=Subscription)
    return session.scalars(stmt).first()


def grant_seat_allowance_on_claim(
    session: Session, member_id: uuid.UUID, *, now: datetime
) -> UsageGrant | None:
    """This month's seat allowance for one seat, prorated to the days left; idempotent.

    ``None`` when the member is not an active student seat, the teacher has no live plan, the
    counted tier has no seat allowance, or the prorated amount is zero. A grant already issued
    for this seat this month is returned as it is: a later claim in the month never reissues or
    shrinks it. The caller commits.
    """
    teacher_user_id = session.scalar(
        select(TeacherMember.teacher_user_id).where(TeacherMember.id == member_id)
    )
    if teacher_user_id is None:
        return None
    tier = _live_teacher_tier(session, teacher_user_id, lock=True)  # step 1
    member = session.get(  # step 2
        TeacherMember, member_id, with_for_update=True, populate_existing=True
    )
    if (
        member is None
        or member.kind is not TeacherMemberKind.student_seat
        or member.status is not TeacherMemberStatus.active
        or tier is None
        or not tier.seat_allowance_units
    ):
        return None
    month_start, month_end = calendar_month_bounds(now)
    key = seat_grant_key(member.id, month_start)
    stored = session.scalars(
        select(UsageGrant).where(
            UsageGrant.owner_user_id == member.member_user_id,
            UsageGrant.idempotency_key == key,
        )
    ).first()
    if stored is not None:
        return stored
    units = prorate_units(
        tier.seat_allowance_units, month_start, month_end, max(start_of_day(now), month_start)
    )
    if units <= 0:
        return None
    grant = UsageLedger(session).issue_grant(  # step 3
        owner_user_id=member.member_user_id,
        kind=GrantKind.seat_allowance,
        units=units,
        idempotency_key=key,
        expires_at=month_end,
        visible=False,
        effective_at=now,
        teacher_member_id=member.id,
    )
    log.info("seat_allowance_granted", teacher_member_id=str(member.id), units=units)
    return grant


def _seats_lacking_a_grant(session: Session, *, now: datetime, limit: int) -> list[uuid.UUID]:
    """Active seats of a teacher whose counted plan grants seat units, with no grant this month."""
    _, month_end = calendar_month_bounds(now)
    ranked = (
        select(
            Subscription.user_id.label("teacher_user_id"),
            PlanTier.seat_allowance_units.label("units"),
            sa.func.row_number()
            .over(partition_by=Subscription.user_id, order_by=_PLAN_ORDER)
            .label("position"),
        )
        .join(PlanTier, PlanTier.id == Subscription.plan_tier_id)
        .where(
            Subscription.status.in_(PLAN_LIVE_STATUSES),
            PlanTier.audience == PlanAudience.teacher,
        )
        .subquery()
    )
    # Only the counted plan (position 1, index R25) decides: a teacher whose counted tier grants
    # nothing has no candidates, so its seats can never fill the batch and starve the rest.
    paying_teachers = select(ranked.c.teacher_user_id).where(
        ranked.c.position == 1, ranked.c.units > 0
    )
    return list(
        session.scalars(
            select(TeacherMember.id)
            .where(
                TeacherMember.kind == TeacherMemberKind.student_seat,
                TeacherMember.status == TeacherMemberStatus.active,
                TeacherMember.teacher_user_id.in_(paying_teachers),
                ~sa.exists().where(
                    UsageGrant.teacher_member_id == TeacherMember.id,
                    UsageGrant.kind == GrantKind.seat_allowance,
                    UsageGrant.expires_at == month_end,
                ),
            )
            .order_by(TeacherMember.teacher_user_id, TeacherMember.created_at, TeacherMember.id)
            .limit(limit)
        )
    )


def grant_monthly_seat_allowances(
    sm: sessionmaker[Session], *, now: datetime, limit: int = SEAT_GRANT_BATCH
) -> int:
    """Grant this month's allowance to every active seat of a live teacher plan that lacks one.

    One bounded read of at most ``limit`` seat ids, then one transaction per seat. A seat whose
    grant raises is logged (``seat_allowance_grant_failed``, ``alert=True``) and skipped; the
    others are unaffected. Returns the number of seats granted. Safe to run every sweep: the
    anti-join skips seats already granted for this month and the idempotency key makes a race
    harmless. When the batch was full the rest wait for the next tick, and
    ``seat_allowance_batch_full`` is logged.
    """
    with sm() as session:
        candidates = _seats_lacking_a_grant(session, now=now, limit=limit)
    if len(candidates) >= limit:
        log.warning("seat_allowance_batch_full", limit=limit)
    granted = 0
    for member_id in candidates:
        try:
            with sm.begin() as session:
                grant = grant_seat_allowance_on_claim(session, member_id, now=now)
        except Exception:
            alerts.error(
                "seat_allowance_grant_failed",
                alert=True,
                teacher_member_id=str(member_id),
                exc_info=True,
            )
            continue
        if grant is not None:
            granted += 1
    return granted


__all__ = [
    "SEAT_GRANT_BATCH",
    "grant_monthly_seat_allowances",
    "grant_seat_allowance_on_claim",
    "seat_grant_key",
]
