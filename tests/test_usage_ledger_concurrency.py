"""Races on the usage ledger (spec §5.7 step 3, §9 "Concurrent jobs on one balance").

* **Two jobs, one balance.** A reservation held open makes a second reservation
  on the same owner queue behind it; once the first commits, the second sees the
  held units and is refused. Deterministic: the second transaction is proven to
  be waiting on a lock before the first commits.
* **Many jobs, one balance.** N reservations started together from a barrier:
  exactly as many succeed as the balance covers, and ``held`` equals their sum.
* **Shared cap.** Two jobs under one assistant's cap, against a teacher with
  plenty of credits: the cap admits only one.
* **Settle against the expiry sweeper.** Exactly one of them closes the job and
  the ledger reconciles.
* **Opposite chain orders.** Jobs whose chains name two owners in opposite
  orders run together without a deadlock.
"""

from __future__ import annotations

import threading
import uuid
from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from lemely.core.usage_types import GrantScope, Payer
from lemely.db.models.enums import Role
from lemely.db.models.usage import GrantKind, UsageJobStatus
from lemely.db.usage_ledger_repo import InsufficientBalance, UsageLedger
from tests._concurrency import _Paused, _wait_until_a_backend_waits_on_a_lock
from tests.usage_db import (
    ACTION,
    ESTIMATOR_VERSION,
    NOW,
    RATE_VERSION,
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
    from collections.abc import Callable, Iterator

    from sqlalchemy.orm import Session, sessionmaker

WORKERS = 6


@pytest.fixture(scope="module")
def usage_db() -> Iterator[sessionmaker[Session]]:
    with usage_database() as factory:
        yield factory


@pytest.fixture
def sm(usage_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(usage_db)


def _reserve_in(session: Session, payers: list[Payer], high: int) -> uuid.UUID:
    job_id = uuid.uuid4()
    UsageLedger(session).reserve(
        job_id=job_id,
        actor_user_id=payers[0].owner_user_id,
        action=ACTION,
        payers=payers,
        estimate_low=0,
        estimate_high=high,
        estimator_version=ESTIMATOR_VERSION,
        rate_version=RATE_VERSION,
        teacher_member_id=payers[0].teacher_member_id,
        expires_at=NOW + timedelta(minutes=15),
        now=NOW,
    )
    return job_id


def _run_together(
    factory: sessionmaker[Session], calls: list[Callable[[Session], object]]
) -> list[object]:
    """Start every call from one barrier, each in its own transaction; return results or errors."""
    barrier = threading.Barrier(len(calls))
    results: list[object] = [None] * len(calls)

    def run(index: int) -> None:
        barrier.wait()
        try:
            with factory.begin() as session:
                results[index] = calls[index](session)
        except Exception as exc:  # collected and asserted on by the test
            results[index] = exc

    threads = [threading.Thread(target=run, args=(i,), daemon=True) for i in range(len(calls))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
        assert not thread.is_alive(), "worker thread hung"
    return results


def test_a_second_reservation_waits_for_the_first_and_is_refused(
    sm: sessionmaker[Session],
) -> None:
    owner = add_user(sm)
    gid = grant(sm, owner, 10)
    holder = sm()
    try:
        holder.begin()
        _reserve_in(holder, own_chain(owner), 8)
        second = _Paused(lambda: reserve(sm, own_chain(owner), 8))
        _wait_until_a_backend_waits_on_a_lock(sm)
        holder.commit()
    finally:
        holder.close()
    second.join()
    assert isinstance(second.error, InsufficientBalance)
    assert balance(sm, gid) == (10, 8)


def test_concurrent_reservations_never_overcommit_a_balance(sm: sessionmaker[Session]) -> None:
    owner = add_user(sm)
    gid = grant(sm, owner, 10)
    results = _run_together(
        sm, [lambda s: _reserve_in(s, own_chain(owner), 4) for _ in range(WORKERS)]
    )
    won = [r for r in results if isinstance(r, uuid.UUID)]
    refused = [r for r in results if isinstance(r, InsufficientBalance)]
    assert (len(won), len(refused)) == (2, WORKERS - 2), results
    assert balance(sm, gid) == (10, 8)


def test_concurrent_jobs_under_one_cap_admit_only_what_the_cap_allows(
    sm: sessionmaker[Session],
) -> None:
    teacher, member = add_user(sm, Role.teacher), uuid.uuid4()
    credits = grant(sm, teacher, 1000, kind=GrantKind.credit_pack, visible=True)
    chain = [
        Payer(
            owner_user_id=teacher,
            scope=GrantScope.CREDITS,
            teacher_member_id=member,
            cap_units=10,
        )
    ]
    results = _run_together(sm, [lambda s: _reserve_in(s, chain, 6) for _ in range(WORKERS)])
    assert sum(isinstance(r, uuid.UUID) for r in results) == 1, results
    assert balance(sm, credits) == (1000, 6)


def test_settle_racing_the_expiry_sweeper_closes_the_job_once(sm: sessionmaker[Session]) -> None:
    add_rate(sm)
    owner = add_user(sm)
    gid = grant(sm, owner, 20)
    job_id = reserve(sm, own_chain(owner), 10, expires_at=NOW + timedelta(seconds=1))
    later = NOW + timedelta(minutes=1)
    results = _run_together(
        sm,
        [
            lambda s: UsageLedger(s).settle(job_id, actual_cost_usd=Decimal("0.007"), now=later),
            lambda s: UsageLedger(s).expire_stale_jobs(now=later),
        ],
    )
    assert not [r for r in results if isinstance(r, Exception)], results
    status = job(sm, job_id).status
    assert status in {UsageJobStatus.settled, UsageJobStatus.expired}
    assert balance(sm, gid) == ((13, 0) if status is UsageJobStatus.settled else (20, 0))
    with sm.begin() as session:
        assert UsageLedger(session).reconcile_balances() == []


def test_opposite_chain_orders_do_not_deadlock(sm: sessionmaker[Session]) -> None:
    a, b = add_user(sm), add_user(sm)
    grant(sm, a, 100, kind=GrantKind.credit_pack, visible=True)
    grant(sm, b, 100, kind=GrantKind.credit_pack, visible=True)
    a_first = [own_chain(a)[1], own_chain(b)[1]]
    b_first = [own_chain(b)[1], own_chain(a)[1]]
    calls: list[Callable[[Session], object]] = []
    for _ in range(WORKERS // 2):
        calls.append(lambda s: _reserve_in(s, a_first, 30))
        calls.append(lambda s: _reserve_in(s, b_first, 30))
    results = _run_together(sm, calls)
    assert all(isinstance(r, uuid.UUID | InsufficientBalance) for r in results), results
    with sm.begin() as session:
        assert UsageLedger(session).reconcile_balances() == []
