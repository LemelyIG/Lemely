"""Sweeper jobs for subscriptions and seats (Paymob billing spec §3 Jobs, §5.2, §5.9).

The subscription jobs open a session and let ``SubscriptionService`` commit per subscription.
The monthly seat allowance takes the sessionmaker and opens one
transaction per seat (DV-19). Every job is idempotent: re-running after a crash, or on a second
replica, changes nothing twice.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from lemely.db.seat_allowance_repo import grant_monthly_seat_allowances
from lemely.db.teacher_team_repo import TeacherTeamService

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.orm import Session, sessionmaker

    from lemely.web.subscription_deps import SubscriptionDeps


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
]
