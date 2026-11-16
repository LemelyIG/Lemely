"""Sweeper jobs for subscriptions and seats (Paymob billing spec §3 Jobs, §5.2, §5.9).

The subscription jobs open a session and let ``SubscriptionService`` commit per subscription.
The monthly seat allowance takes the sessionmaker and opens one
transaction per seat (DV-19). Every job is idempotent: re-running after a crash, or on a second
replica, changes nothing twice.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from sqlalchemy import select

from lemely.db.models.billing import Subscription
from lemely.db.plan_terms_repo import fixed_path_move_ids, queue_terms_change_notices
from lemely.db.seat_allowance_repo import grant_monthly_seat_allowances
from lemely.db.teacher_team_repo import TeacherTeamService

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.orm import Session, sessionmaker

    from lemely.web.subscription_deps import SubscriptionDeps

log = structlog.get_logger("lemely.web.subscription_jobs")


def expire_overdue_job(deps: SubscriptionDeps, *, now: datetime) -> int:
    """Expire ``past_due`` subscriptions whose grace has elapsed; the count."""
    with deps.sessionmaker() as session:
        return deps.service(session).expire_overdue(now=now)


def period_end_job(deps: SubscriptionDeps, *, now: datetime) -> int:
    """Push amounts and cancels to Paymob and end cancelled plans at period end; the count."""
    with deps.sessionmaker() as session:
        return deps.service(session).apply_period_end_changes(now=now)


def drift_check_job(deps: SubscriptionDeps, *, now: datetime) -> int:
    """Run the drift check; the database, not the process, makes it once a row a UTC day.

    ``check_drift`` takes only rows not yet checked on ``now``'s UTC day, so calling it every
    tick drains any backlog over successive ticks and costs one indexed query when none is left.
    """
    with deps.sessionmaker() as session:
        return deps.service(session).check_drift(now=now)


def terms_change_notices_job(deps: SubscriptionDeps, *, now: datetime) -> int:
    """Notify subscribers of plan terms changes (job ``billing.terms_change_notices``)."""
    return queue_terms_change_notices(
        deps.sessionmaker,
        now=now,
        amount_updatable=deps.settings.subscription_amount_updatable,
    )


def terms_move_fixed_path_job(deps: SubscriptionDeps, *, now: datetime) -> int:
    """Cancel at period end the plans a terms move would reprice on the fixed-amount path.

    ``billing.terms_move_fixed_path`` (UD-P4): Paymob cannot change the amount of those
    subscriptions, so the move is never applied by a renewal. The system schedules the cancel (no
    Paymob call here: the cancel sweep pushes it) and the subscriber subscribes again at the new
    price. One transaction per row, re-checked under the row's lock. The count of rows scheduled.
    """
    if deps.settings.subscription_amount_updatable:
        return 0
    with deps.sessionmaker() as session:
        ids = fixed_path_move_ids(session, now=now)
    scheduled = 0
    for sub_id in ids:
        try:
            with deps.sessionmaker.begin() as session:
                held = session.scalar(
                    select(Subscription.id)
                    .where(Subscription.id == sub_id)
                    .with_for_update(skip_locked=True)
                )
                if held is None or not fixed_path_move_ids(session, now=now, only=sub_id):
                    continue  # locked elsewhere or changed since the read: the next tick decides
                deps.service(session).schedule_cancel_as_system(sub_id, now=now)
            scheduled += 1
            log.info("subscription_terms_move_cancel_scheduled", subscription_id=str(sub_id))
        except Exception:
            log.error(
                "subscription_terms_move_cancel_failed",
                subscription_id=str(sub_id),
                alert=True,
                exc_info=True,
            )
    return scheduled


def release_due_seats_job(sm: sessionmaker[Session], *, now: datetime) -> int:
    """Remove every leaving seat whose ``leaves_at`` has passed: one UPDATE, one transaction."""
    with sm.begin() as session:
        return TeacherTeamService(session).release_due(now=now)


def monthly_seat_allowance_job(sm: sessionmaker[Session], *, now: datetime) -> int:
    """Grant this month's seat allowances; opens its own transaction per seat (DV-19)."""
    return grant_monthly_seat_allowances(sm, now=now)


__all__ = [
    "drift_check_job",
    "expire_overdue_job",
    "monthly_seat_allowance_job",
    "period_end_job",
    "release_due_seats_job",
    "terms_change_notices_job",
    "terms_move_fixed_path_job",
]
