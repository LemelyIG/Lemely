"""Usage ledger sweeps (billing spec §5.7 step 7, §5.8, §6), run by ``Sweeper``.

* ``usage.expire_stale_jobs``: open jobs past ``expires_at`` (a crashed worker, a pool
  job that never ran) are released and marked ``expired``; no charge. A running job
  keeps its hold alive (``MeteredJob.run``'s hold renewer), and the ledger re-checks each
  deadline under the owners' locks, so the sweep never closes a job whose clock was just
  restarted. Each job closes in its own savepoint: a job whose chain no longer reaches its
  holds is released and alerted on, never a poison pill for the rest.
* ``usage.expire_grants``: grants past ``expires_at`` expire their unheld remainder.
* Both take at most :data:`EXPIRE_BATCH` rows per pass, oldest first; a full batch is
  logged (``usage_sweep_batch_full``) and the next pass continues the backlog.
* ``usage.repair_signup_grants``: every verified student or teacher without a signup grant
  gets one. It backfills accounts verified before metering shipped and heals a grant that
  failed after the verification committed (``signup_grant_failed``).
* ``usage.reconcile_balances``: once per UTC day after ``RECONCILE_HOUR_UTC``, compare the
  cached balances with the entries and log every drift as an error (the alert). The
  ledger repairs the cache as it reports.

All four are idempotent, so a second replica running the same pass does no harm: the
ledger takes its owner locks in a fixed order and a re-run finds nothing left to do.
``run_jobs`` wraps each job, so one that raises is a logged ``sweep_job_failed`` and the
others still run; the repair also isolates each user, so one account the ledger refuses
cannot hold up the rest of its batch.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, timedelta
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import event, exists, select

from lemely.db.models.billing import CreditPack
from lemely.db.models.enums import Role
from lemely.db.models.usage import UsageGrant
from lemely.db.models.users import User
from lemely.db.usage_catalogue_repo import (
    SIGNUP_IDEMPOTENCY_KEY,
    SIGNUP_STUDENT_PACK,
    SIGNUP_TEACHER_PACK,
    grant_signup_allowance,
)
from lemely.db.usage_ledger_repo import UsageLedger

if TYPE_CHECKING:
    import uuid
    from collections.abc import Callable
    from datetime import date, datetime

    from sqlalchemy.orm import Session, sessionmaker

log = structlog.get_logger(__name__)

RECONCILE_HOUR_UTC = 2
#: How long a failed reconcile waits before this process tries the full scan again.
RECONCILE_RETRY = timedelta(hours=1)
#: Jobs or grants one ``usage.expire_*`` pass handles, oldest first.
EXPIRE_BATCH = 500
#: Users examined per ``usage.repair_signup_grants`` pass: the bound on one sweep's work.
SIGNUP_REPAIR_BATCH = 200
#: Drift lines logged per reconcile; the total is always logged, so a runaway bug cannot
#: flood the log. The ledger repairs every drifted row regardless.
MAX_DRIFT_LINES = 100

#: The roles that get a signup grant, and the pack that sizes it (spec §2.1).
_SIGNUP_PACKS: dict[Role, str] = {
    Role.student: SIGNUP_STUDENT_PACK,
    Role.teacher: SIGNUP_TEACHER_PACK,
}


@dataclass(slots=True)
class ReconcileMemo:
    """The UTC date the reconcile last completed in this process, and its back-off.

    ``retry_after`` is set when a reconcile starts and cleared when it completes, so a
    reconcile that keeps failing reruns its full scan once per :data:`RECONCILE_RETRY`,
    not every sweep pass.
    """

    last_date: date | None = None
    retry_after: datetime | None = None


@dataclass(slots=True)
class RepairCursor:
    """Where the signup repair resumes: the last user id of the previous batch.

    Keyset paging by user id keeps one sweep bounded without letting accounts the ledger
    cannot grant (a failing one) sit at the head of the queue forever. ``None`` means
    start from the beginning; a batch shorter than the limit means the walk is done, and
    the cursor goes back to ``None``.
    """

    after: uuid.UUID | None = None


def expire_stale_jobs(sm: sessionmaker[Session], *, now: datetime) -> int:
    """Close the open jobs past their deadline; returns how many this pass closed."""
    with sm.begin() as session:
        result = UsageLedger(session).sweep_stale_jobs(now=now, limit=EXPIRE_BATCH)
    if result.expired:
        log.info("usage_jobs_expired", count=result.expired)
    # Candidates, not closures: a batch full of failing jobs is still a full batch.
    _note_full_batch("expire_stale_jobs", result.candidates, failed=len(result.failed))
    return result.expired


def expire_grants(sm: sessionmaker[Session], *, now: datetime) -> int:
    """Expire the unheld remainder of grants past expiry; returns how many were expired."""
    with sm.begin() as session:
        expired = UsageLedger(session).expire_grants(now=now, limit=EXPIRE_BATCH)
    if expired:
        log.info("usage_grants_expired", count=expired)
    _note_full_batch("expire_grants", expired)
    return expired


def _note_full_batch(sweep: str, count: int, *, failed: int = 0) -> None:
    """A full batch means a backlog: the next pass continues it, and this line shows it."""
    if count >= EXPIRE_BATCH:
        log.info("usage_sweep_batch_full", sweep=sweep, limit=EXPIRE_BATCH, failed=failed)


def reconcile_balances(sm: sessionmaker[Session], *, now: datetime, memo: ReconcileMemo) -> int:
    """Log every cached-balance drift; returns how many values drifted.

    The day is recorded only once the ledger finished, so a failed reconcile is retried by
    the next pass instead of waiting for tomorrow, but not before ``memo.retry_after``: a
    failing full scan backs off for :data:`RECONCILE_RETRY` instead of rerunning every pass.
    """
    memo.retry_after = now + RECONCILE_RETRY
    with sm.begin() as session:
        drift = UsageLedger(session).reconcile_balances()
    for row_id, cached, actual in drift[:MAX_DRIFT_LINES]:
        log.error("usage_balance_drift", row_id=str(row_id), cached=cached, actual=actual)
    if drift:
        log.error(
            "usage_balance_drift_total", count=len(drift), logged=min(len(drift), MAX_DRIFT_LINES)
        )
    memo.last_date = now.astimezone(UTC).date()
    memo.retry_after = None
    return len(drift)


def _roles_to_repair(sm: sessionmaker[Session]) -> list[Role]:
    """The roles whose signup pack is not disabled (``units = 0``).

    A pack row that does not exist yet counts as enabled: ``grant_signup_allowance`` seeds
    the defaults on its first miss. Reading the packs here keeps a disabled grant from
    turning every sweep into a walk over every account for nothing.
    """
    with sm() as session:
        units = {
            code: count
            for code, count in session.execute(
                select(CreditPack.code, CreditPack.units).where(
                    CreditPack.code.in_(_SIGNUP_PACKS.values())
                )
            )
        }
    return [role for role, code in _SIGNUP_PACKS.items() if units.get(code, 1) > 0]


def _watch_new_grants(session: Session) -> list[UsageGrant]:
    """A list that fills with every ``UsageGrant`` this session's flushes insert.

    ``grant_signup_allowance`` returns the stored grant on a replay, so its return value
    cannot tell a new grant from an old one; a row in this transaction's ``session.new``
    at flush time can. The listener dies with the session.
    """
    inserted: list[UsageGrant] = []
    event.listen(
        session,
        "after_flush",
        lambda sess, _ctx: inserted.extend(o for o in sess.new if isinstance(o, UsageGrant)),
    )
    return inserted


def repair_signup_grants(
    sm: sessionmaker[Session],
    *,
    now: datetime,
    cursor: RepairCursor,
    limit: int = SIGNUP_REPAIR_BATCH,
) -> int:
    """Grant the signup allowance to up to ``limit`` verified accounts that lack one.

    Idempotent through the ledger's per-owner lock and its unique (owner, ``signup``)
    key, so racing ``mark_email_verified`` or another replica yields one grant. Each user
    is granted in its own transaction: one the ledger refuses is logged
    (``usage_signup_repair_failed``) and skipped, and the next pass past the cursor wrap
    tries it again. The teacher's 30 days count from ``now``, the grant time.

    Returns the number of grants this call issued, and logs it when it is not zero. A user
    whose grant another replica committed first is answered with that stored grant and is
    not counted.
    """
    roles = _roles_to_repair(sm)
    if not roles:
        cursor.after = None
        return 0
    has_signup_grant = exists().where(
        UsageGrant.owner_user_id == User.id,
        UsageGrant.idempotency_key == SIGNUP_IDEMPOTENCY_KEY,
    )
    query = (
        select(User.id, User.role)
        .where(User.email_verified_at.is_not(None), User.role.in_(roles), ~has_signup_grant)
        .order_by(User.id)
        .limit(limit)
    )
    if cursor.after is not None:
        query = query.where(User.id > cursor.after)
    with sm() as session:
        batch = [(row.id, row.role) for row in session.execute(query)]
    granted = 0
    for user_id, role in batch:
        try:
            with sm.begin() as session:
                issued = _watch_new_grants(session)
                grant_signup_allowance(session, user_id=user_id, role=role, now=now)
                if issued:
                    granted += 1
        except Exception:
            log.exception("usage_signup_repair_failed", user_id=str(user_id))
    cursor.after = batch[-1][0] if len(batch) >= limit else None
    if granted:
        log.info("signup_grants_repaired", count=granted)
    return granted


def usage_jobs(
    sm: sessionmaker[Session],
    *,
    now: datetime,
    memo: ReconcileMemo,
    repair: RepairCursor | None = None,
) -> list[tuple[str, Callable[[], int]]]:
    """This pass's usage jobs, named for ``run_jobs``'s result map and the admin health view.

    ``repair`` is the cursor the signup repair carries between passes; without one, every
    pass starts from the first account.
    """
    cursor = repair if repair is not None else RepairCursor()
    moment = now.astimezone(UTC)
    jobs: list[tuple[str, Callable[[], int]]] = [
        ("usage.expire_stale_jobs", lambda: expire_stale_jobs(sm, now=now)),
        ("usage.expire_grants", lambda: expire_grants(sm, now=now)),
        (
            "usage.repair_signup_grants",
            lambda: repair_signup_grants(sm, now=now, cursor=cursor),
        ),
    ]
    backing_off = memo.retry_after is not None and now < memo.retry_after
    if memo.last_date != moment.date() and moment.hour >= RECONCILE_HOUR_UTC and not backing_off:
        jobs.append(
            ("usage.reconcile_balances", lambda: reconcile_balances(sm, now=now, memo=memo))
        )
    return jobs
