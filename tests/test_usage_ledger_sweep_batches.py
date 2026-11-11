"""The expiry sweeps survive a bad row and work in bounded batches (billing Task 14 follow-up).

* **No poison pill.** A stale job whose stored chain no longer reaches a grant it holds
  units on used to raise out of ``expire_stale_jobs`` and abort every pass, so no job
  behind it ever expired. Each job now closes in its own savepoint. A stranded job's
  holds go back to the grants that hold them (releasing never needs the chain; only a
  charge does), it is marked expired, and an error-level ``alert=True`` event names it.
  Any other per-job failure is rolled back alone, alerted, and the job is left open.
* **Bounded batches.** Both sweeps take ``limit`` (oldest due rows first), and the web
  sweeper passes a bounded one, so a backlog drains over several passes.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from structlog.testing import capture_logs

from lemely.core.usage_types import payer_to_json
from lemely.db.models.usage import GrantKind, UsageJob, UsageJobStatus
from lemely.db.usage_ledger_repo import DEFAULT_SWEEP_LIMIT, UsageLedger
from lemely.web import usage_sweeps
from tests._concurrency import _Paused, _wait_until_a_backend_waits_on_a_lock
from tests.usage_db import (
    NOW,
    add_rate,
    add_user,
    balance,
    emptied_after,
    grant,
    job,
    own_chain,
    reserve,
    usage_database,
)

if TYPE_CHECKING:
    import uuid
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

LATER = NOW + timedelta(hours=1)


@pytest.fixture(scope="module")
def usage_db() -> Iterator[sessionmaker[Session]]:
    with usage_database() as factory:
        yield factory


@pytest.fixture
def sm(usage_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(usage_db)


def _stale(sm: sessionmaker[Session], owner: uuid.UUID, units: int, minutes: int) -> uuid.UUID:
    """A job on ``owner``'s own chain whose deadline is ``minutes`` after ``NOW``."""
    return reserve(sm, own_chain(owner), units, expires_at=NOW + timedelta(minutes=minutes))


def _strand(sm: sessionmaker[Session], job_id: uuid.UUID, onto: uuid.UUID) -> None:
    """Rewrite the stored chain so it no longer reaches the grant the job holds units on."""
    with sm.begin() as session:
        session.execute(
            sa.update(UsageJob)
            .where(UsageJob.job_id == job_id)
            .values(payer_chain=[payer_to_json(p) for p in own_chain(onto)])
        )


def _sweep(sm: sessionmaker[Session], **kwargs: object) -> int:
    with sm.begin() as session:
        return UsageLedger(session).expire_stale_jobs(now=LATER, **kwargs)  # type: ignore[arg-type]


def _reconciled(sm: sessionmaker[Session]) -> None:
    with sm.begin() as session:
        assert UsageLedger(session).reconcile_balances() == []


# --- no poison pill ---------------------------------------------------------------------


def test_a_stranded_job_never_stops_the_sweep_and_its_holds_go_back(
    sm: sessionmaker[Session],
) -> None:
    add_rate(sm)
    first, second, stranded_owner, other = (add_user(sm) for _ in range(4))
    g1, g2, gs = grant(sm, first, 30), grant(sm, second, 30), grant(sm, stranded_owner, 30)
    stranded = _stale(sm, stranded_owner, 10, minutes=1)  # the oldest: swept first
    good = [_stale(sm, first, 10, minutes=2), _stale(sm, second, 10, minutes=3)]
    _strand(sm, stranded, onto=other)
    with capture_logs() as logs:
        assert _sweep(sm) == 3
    assert [job(sm, j).status for j in good] == [UsageJobStatus.expired] * 2
    assert (balance(sm, g1), balance(sm, g2)) == ((30, 0), (30, 0))
    assert job(sm, stranded).status is UsageJobStatus.expired
    assert balance(sm, gs) == (30, 0)  # no unit stays held on a grant nothing will release
    (alert,) = [e for e in logs if e["event"] == "usage_job_stranded_holds"]
    assert (alert["log_level"], alert["alert"], alert["job_id"]) == ("error", True, str(stranded))
    assert (alert["grant_ids"], alert["released_units"]) == ([str(gs)], 10)
    _reconciled(sm)


def test_the_sweep_locks_the_stranded_grants_owner_before_releasing_it(
    sm: sessionmaker[Session],
) -> None:
    """The grant's owner is not in the job's chain; its lock is taken up front, in order."""
    add_rate(sm)
    stranded_owner, other = add_user(sm), add_user(sm)
    gs = grant(sm, stranded_owner, 30)
    stranded = _stale(sm, stranded_owner, 10, minutes=1)
    _strand(sm, stranded, onto=other)
    holder = sm()
    try:
        holder.begin()
        holder.execute(
            sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"usage:{stranded_owner}"},
        )
        sweeping = _Paused(lambda: _sweep(sm))
        _wait_until_a_backend_waits_on_a_lock(sm)  # queued behind the grant owner's lock
        holder.commit()
    finally:
        holder.close()
    sweeping.join()
    assert (sweeping.error, sweeping.result) == (None, 1)
    assert balance(sm, gs) == (30, 0)


def test_a_job_that_fails_for_another_reason_is_left_open_and_the_rest_expire(
    sm: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    add_rate(sm)
    owner = add_user(sm)
    gid = grant(sm, owner, 50)
    broken, ok = _stale(sm, owner, 10, minutes=1), _stale(sm, owner, 10, minutes=2)
    original = UsageLedger._close

    def close(self: UsageLedger, job_id: uuid.UUID, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        result = original(self, job_id, *args, **kwargs)  # type: ignore[arg-type]
        if job_id == broken:
            raise sa.exc.OperationalError("UPDATE", {}, Exception("row went away"))
        return result

    monkeypatch.setattr(UsageLedger, "_close", close)
    with capture_logs() as logs:
        assert _sweep(sm) == 1
    assert (job(sm, broken).status, job(sm, ok).status) == (
        UsageJobStatus.open,
        UsageJobStatus.expired,
    )
    assert balance(sm, gid) == (50, 10)  # the failed job's writes were rolled back alone
    (alert,) = [e for e in logs if e["event"] == "usage_expire_job_failed"]
    assert (alert["log_level"], alert["alert"], alert["job_id"]) == ("error", True, str(broken))
    _reconciled(sm)


# --- bounded batches --------------------------------------------------------------------


def test_expire_stale_jobs_takes_the_oldest_due_jobs_up_to_the_limit(
    sm: sessionmaker[Session],
) -> None:
    add_rate(sm)
    owner = add_user(sm)
    grant(sm, owner, 100)
    jobs = [_stale(sm, owner, 5, minutes=m) for m in (5, 1, 4, 2, 3)]
    by_age = [jobs[1], jobs[3], jobs[4], jobs[2], jobs[0]]
    assert _sweep(sm, limit=2) == 2
    assert [job(sm, j).status for j in by_age] == [
        UsageJobStatus.expired,
        UsageJobStatus.expired,
        UsageJobStatus.open,
        UsageJobStatus.open,
        UsageJobStatus.open,
    ]
    assert _sweep(sm, limit=2) == 2
    assert _sweep(sm, limit=2) == 1
    assert _sweep(sm, limit=2) == 0
    _reconciled(sm)


def test_expire_grants_takes_the_oldest_due_grants_up_to_the_limit(
    sm: sessionmaker[Session],
) -> None:
    owner = add_user(sm)
    grants = [
        grant(
            sm,
            owner,
            10,
            kind=GrantKind.credit_pack,
            visible=True,
            expires_at=NOW + timedelta(minutes=m),
        )
        for m in (3, 1, 2)
    ]
    with sm.begin() as session:
        assert UsageLedger(session).expire_grants(now=LATER, limit=2) == 2
    assert [balance(sm, g)[0] for g in grants] == [10, 0, 0]  # the newest is left for later
    with sm.begin() as session:
        assert UsageLedger(session).expire_grants(now=LATER, limit=2) == 1
    assert [balance(sm, g)[0] for g in grants] == [0, 0, 0]
    _reconciled(sm)


@pytest.mark.parametrize("sweep", ["expire_stale_jobs", "expire_grants"])
def test_a_limit_below_one_is_refused(sm: sessionmaker[Session], sweep: str) -> None:
    with sm.begin() as session, pytest.raises(ValueError, match="limit"):
        getattr(UsageLedger(session), sweep)(now=LATER, limit=0)


def test_the_default_limit_is_bounded() -> None:
    assert 1 <= DEFAULT_SWEEP_LIMIT <= 1000


@pytest.mark.parametrize("sweep", ["expire_stale_jobs", "expire_grants"])
def test_the_web_sweeper_passes_a_bounded_limit(
    sm: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch, sweep: str
) -> None:
    seen: list[object] = []

    def capture(_self: UsageLedger, **kwargs: object) -> int:
        seen.append(kwargs.get("limit"))
        return 0

    monkeypatch.setattr(UsageLedger, sweep, capture)
    getattr(usage_sweeps, sweep)(sm, now=LATER)
    assert seen == [usage_sweeps.EXPIRE_BATCH]
    assert 1 <= usage_sweeps.EXPIRE_BATCH <= 1000


def test_a_full_batch_is_logged_so_a_backlog_is_visible(
    sm: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(usage_sweeps, "EXPIRE_BATCH", 2)
    add_rate(sm)
    owner = add_user(sm)
    grant(sm, owner, 100)
    for m in (1, 2, 3):
        _stale(sm, owner, 5, minutes=m)
    with capture_logs() as logs:
        assert usage_sweeps.expire_stale_jobs(sm, now=LATER) == 2
    (full,) = [e for e in logs if e["event"] == "usage_sweep_batch_full"]
    assert (full["sweep"], full["limit"]) == ("expire_stale_jobs", 2)
