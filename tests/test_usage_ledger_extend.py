"""Restarting a hold's clock when queued work starts (``UsageLedger.extend``).

* **Only the deadline moves.** Amounts, holds and entries are untouched, and a deadline
  never moves earlier.
* **A closed job is left alone.** The caller sees the status and re-reserves.
* **Extend against the expiry sweeper.** Both take the same owner and job locks. An
  extend queued behind an open sweep finds the job expired. A sweep that read the job
  as stale but queued behind an open extend re-checks the deadline under the lock and
  closes nothing. Either way the job is never both held and released.
"""

from __future__ import annotations

import threading
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa

from lemely.db.models.usage import UsageEntry, UsageJobStatus
from lemely.db.usage_ledger_repo import UsageLedger
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
    from datetime import datetime

    from sqlalchemy.orm import Session, sessionmaker

LATER = NOW + timedelta(minutes=1)
EXTENDED = NOW + timedelta(hours=2)


@pytest.fixture(scope="module")
def usage_db() -> Iterator[sessionmaker[Session]]:
    with usage_database() as factory:
        yield factory


@pytest.fixture
def sm(usage_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(usage_db)


def _stale_job(sm: sessionmaker[Session]) -> tuple[uuid.UUID, uuid.UUID]:
    """A 20-unit grant with one open 10-unit job whose deadline has passed at ``LATER``."""
    add_rate(sm)
    owner = add_user(sm)
    gid = grant(sm, owner, 20)
    job_id = reserve(sm, own_chain(owner), 10, expires_at=NOW + timedelta(seconds=1))
    return gid, job_id


def _extend(
    factory: sessionmaker[Session], job_id: uuid.UUID, expires_at: datetime, now: datetime
) -> tuple[UsageJobStatus, datetime]:
    with factory.begin() as session:
        extended = UsageLedger(session).extend(job_id, expires_at=expires_at, now=now)
        return extended.status, extended.expires_at


def _sweep(factory: sessionmaker[Session], now: datetime) -> int:
    with factory.begin() as session:
        return UsageLedger(session).expire_stale_jobs(now=now)


def _entry_count(factory: sessionmaker[Session], job_id: uuid.UUID) -> int:
    with factory() as session:
        return int(
            session.scalar(
                sa.select(sa.func.count())
                .select_from(UsageEntry)
                .where(UsageEntry.job_id == job_id)
            )
            or 0
        )


def _reconciled(factory: sessionmaker[Session]) -> None:
    with factory.begin() as session:
        assert UsageLedger(session).reconcile_balances() == []


def test_extend_moves_only_the_deadline(sm: sessionmaker[Session]) -> None:
    gid, job_id = _stale_job(sm)
    before = job(sm, job_id)
    entries = _entry_count(sm, job_id)
    assert _extend(sm, job_id, EXTENDED, LATER) == (UsageJobStatus.open, EXTENDED)
    after = job(sm, job_id)
    assert (after.reserved, after.charged, after.estimate_high, after.payer_chain) == (
        before.reserved,
        before.charged,
        before.estimate_high,
        before.payer_chain,
    )
    assert balance(sm, gid) == (20, 10)
    assert _entry_count(sm, job_id) == entries
    _reconciled(sm)


def test_extend_never_moves_a_deadline_earlier(sm: sessionmaker[Session]) -> None:
    _gid, job_id = _stale_job(sm)
    assert _extend(sm, job_id, EXTENDED, LATER)[1] == EXTENDED
    assert _extend(sm, job_id, NOW + timedelta(minutes=30), LATER) == (
        UsageJobStatus.open,
        EXTENDED,
    )


def test_extend_leaves_a_closed_job_unchanged(sm: sessionmaker[Session]) -> None:
    gid, job_id = _stale_job(sm)
    assert _sweep(sm, LATER) == 1
    status, deadline = _extend(sm, job_id, EXTENDED, LATER)
    assert status is UsageJobStatus.expired
    assert deadline == NOW + timedelta(seconds=1)
    assert balance(sm, gid) == (20, 0)
    _reconciled(sm)


def test_extend_refuses_a_deadline_that_is_not_in_the_future(sm: sessionmaker[Session]) -> None:
    _gid, job_id = _stale_job(sm)
    with pytest.raises(ValueError, match="after now"):
        _extend(sm, job_id, LATER, LATER)


def test_an_extend_queued_behind_an_open_sweep_finds_the_job_expired(
    sm: sessionmaker[Session],
) -> None:
    gid, job_id = _stale_job(sm)
    holder = sm()
    try:
        holder.begin()
        assert UsageLedger(holder).expire_stale_jobs(now=LATER) == 1
        extending = _Paused(lambda: _extend(sm, job_id, EXTENDED, LATER))
        _wait_until_a_backend_waits_on_a_lock(sm)  # the extend is queued behind the sweep
        holder.commit()
    finally:
        holder.close()
    extending.join()
    assert extending.error is None
    assert extending.result == (UsageJobStatus.expired, NOW + timedelta(seconds=1))
    assert balance(sm, gid) == (20, 0)
    _reconciled(sm)


def test_a_sweep_queued_behind_an_open_extend_closes_nothing(sm: sessionmaker[Session]) -> None:
    """The sweep read the job as stale before the extend committed; it re-checks under the lock."""
    gid, job_id = _stale_job(sm)
    holder = sm()
    try:
        holder.begin()
        UsageLedger(holder).extend(job_id, expires_at=EXTENDED, now=LATER)
        sweeping = _Paused(lambda: _sweep(sm, LATER))
        _wait_until_a_backend_waits_on_a_lock(sm)  # the sweep is queued behind the extend
        holder.commit()
    finally:
        holder.close()
    sweeping.join()
    assert sweeping.error is None
    assert sweeping.result == 0
    row = job(sm, job_id)
    assert (row.status, row.expires_at) == (UsageJobStatus.open, EXTENDED)
    assert balance(sm, gid) == (20, 10)
    _reconciled(sm)


@pytest.mark.parametrize("attempt", range(5))
def test_extend_and_sweep_started_together_never_both_win(
    sm: sessionmaker[Session], attempt: int
) -> None:
    """Whichever locks first decides; the job ends either open and held or expired and freed."""
    gid, job_id = _stale_job(sm)
    barrier = threading.Barrier(2)

    def extend() -> tuple[UsageJobStatus, datetime]:
        barrier.wait()
        return _extend(sm, job_id, EXTENDED, LATER)

    def sweep() -> int:
        barrier.wait()
        return _sweep(sm, LATER)

    extending, sweeping = _Paused(extend), _Paused(sweep)
    extending.join()
    sweeping.join()
    assert extending.error is None
    assert sweeping.error is None
    row = job(sm, job_id)
    if row.status is UsageJobStatus.open:
        assert (extending.result, sweeping.result) == ((UsageJobStatus.open, EXTENDED), 0)
        assert balance(sm, gid) == (20, 10)
    else:
        assert row.status is UsageJobStatus.expired
        assert sweeping.result == 1
        assert extending.result == (UsageJobStatus.expired, NOW + timedelta(seconds=1))
        assert balance(sm, gid) == (20, 0)
    _reconciled(sm)
