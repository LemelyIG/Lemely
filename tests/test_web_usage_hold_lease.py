"""The hold is a lease: restarted when the work starts, renewed while it runs.

* **Heartbeat.** A run longer than its timeout keeps its hold and settles once; renewal
  stops before the settle, so no extend ever lands after the job finished. A failed
  renewal is logged and the next tick retries.
* **Fail closed at start.** An extend that fails twice lets the work start only while the
  old deadline is still a whole timeout away; otherwise the hold is released and
  :class:`UsageUnavailable` is raised before any work. A re-reserve that fails for any
  reason never lets the work run unmetered.
* **Only an expired hold is reserved again.** A job settled or released by someone else
  raises instead of billing the work twice or billing cancelled work.
* **Races with the sweeper at the meter level.** A run whose extend queues behind an open
  sweep reserves again; a sweep queued behind a run's extend closes nothing.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from sqlalchemy.exc import OperationalError
from structlog.testing import capture_logs

from lemely.core.metered_actions import MeteredAction
from lemely.core.payer_chain import UsageBlockReason
from lemely.db.models.enums import Role
from lemely.db.models.team import TeacherMember, TeacherMemberStatus
from lemely.db.models.usage import UsageJobStatus
from lemely.db.usage_ledger_repo import UsageLedger
from lemely.io.llm.cost_meter import record_llm_cost
from lemely.web.usage import (
    LEASE_CAP,
    USAGE_UNAVAILABLE_MESSAGE,
    UsageBlocked,
    UsageMeter,
    UsageRequest,
    UsageUnavailable,
)
from tests._concurrency import _Paused, _wait_until_a_backend_waits_on_a_lock
from tests.usage_helpers import NOW, assistant, give, jobs_for, seed_catalogue, seed_user

if TYPE_CHECKING:
    import uuid
    from collections.abc import Callable

    from sqlalchemy.orm import Session, sessionmaker

#: mark_paper: 45 min timeout + 10 min slack.
LEASE = timedelta(minutes=55)


def _req(
    actor: uuid.UUID, *, role: Role = Role.student, assistant_member_id: uuid.UUID | None = None
) -> UsageRequest:
    return UsageRequest(
        actor_user_id=actor,
        actor_role=role,
        action=MeteredAction.MARK_PAPER,
        assistant_member_id=assistant_member_id,
    )


def _student(sm: sessionmaker[Session], units: int = 1000) -> uuid.UUID:
    seed_catalogue(sm)
    student = seed_user(sm)
    give(sm, student, units=units)
    return student


def _meter(
    sm: sessionmaker[Session], clock: list[datetime], renew_every: timedelta | None = None
) -> UsageMeter:
    return UsageMeter(sm, enforce=True, now=lambda: clock[0], renew_every=renew_every)


def _sweep(sm: sessionmaker[Session], now: datetime) -> int:
    with sm.begin() as session:
        return UsageLedger(session).expire_stale_jobs(now=now)


def _deadline(sm: sessionmaker[Session], actor: uuid.UUID) -> datetime:
    (row,) = [j for j in jobs_for(sm, actor) if j.status is UsageJobStatus.open]
    return row.expires_at


def _eventually(check: Callable[[], bool], what: str) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.02)
    pytest.fail(f"timed out waiting for {what}")


def _count_extends(
    monkeypatch: pytest.MonkeyPatch,
    fail_first: int = 0,
    fail_calls: frozenset[int] = frozenset(),
    seen: list[UsageJobStatus] | None = None,
) -> list[datetime]:
    """Wrap ``UsageLedger.extend``: record each call, fail the first N or the numbered ones.

    ``seen`` collects the status each successful extend found the job in.
    """
    calls: list[datetime] = []
    original = UsageLedger.extend

    def counted(self: UsageLedger, job_id: uuid.UUID, *, expires_at: datetime, now: datetime):  # type: ignore[no-untyped-def]
        calls.append(expires_at)
        if len(calls) <= fail_first or len(calls) in fail_calls:
            raise OperationalError("SELECT 1", {}, Exception("ledger down"))
        result = original(self, job_id, expires_at=expires_at, now=now)
        if seen is not None:
            seen.append(result.status)
        return result

    monkeypatch.setattr(UsageLedger, "extend", counted)
    return calls


# --- heartbeat --------------------------------------------------------------------------


def test_a_run_longer_than_its_timeout_keeps_its_hold_and_settles_once(
    migrated_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    sm = migrated_sessionmaker
    student = _student(sm)
    clock = [NOW]
    meter = _meter(sm, clock, renew_every=timedelta(milliseconds=50))
    seen: list[UsageJobStatus] = []
    calls = _count_extends(monkeypatch, seen=seen)
    job = meter.reserve(meter.authorize(_req(student)))
    with job.run():
        record_llm_cost(Decimal("0.020"))
        clock[0] = NOW + timedelta(minutes=50)
        _eventually(lambda: _deadline(sm, student) == clock[0] + LEASE, "a renewal at +50 min")
        clock[0] = NOW + timedelta(minutes=100)  # the reserve-time deadline (+55) is long gone
        _eventually(lambda: _deadline(sm, student) == clock[0] + LEASE, "a renewal at +100 min")
        assert _sweep(sm, clock[0] + timedelta(minutes=1)) == 0
    finished = len(calls)
    (row,) = jobs_for(sm, student)
    assert (row.status, row.charged) == (UsageJobStatus.settled, 20)
    time.sleep(0.3)  # six renewal intervals
    assert len(calls) == finished, "the heartbeat renewed a job after it finished"
    # Renewal stops (and waits out one in flight) before the settle: no extend ever
    # found the job settled.
    assert set(seen) == {UsageJobStatus.open}


def test_a_failed_renewal_is_logged_and_the_next_tick_retries(
    migrated_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    sm = migrated_sessionmaker
    student = _student(sm)
    clock = [NOW]
    meter = _meter(sm, clock, renew_every=timedelta(milliseconds=50))
    calls = _count_extends(monkeypatch, fail_calls=frozenset({2}))  # #1 is run()'s own extend
    job = meter.reserve(meter.authorize(_req(student)))
    with capture_logs() as logs, job.run():
        clock[0] = NOW + timedelta(minutes=30)
        _eventually(lambda: _deadline(sm, student) == clock[0] + LEASE, "a retried renewal")
        record_llm_cost(Decimal("0.020"))
    assert len(calls) >= 3
    assert "usage_renew_failed" in [e["event"] for e in logs]
    (row,) = jobs_for(sm, student)
    assert (row.status, row.charged) == (UsageJobStatus.settled, 20)


def test_a_hung_run_stops_renewing_at_the_lease_cap(
    migrated_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run stuck for hours keeps its hold at most LEASE_CAP leases past its start."""
    sm = migrated_sessionmaker
    student = _student(sm)
    clock = [NOW]
    meter = _meter(sm, clock, renew_every=timedelta(milliseconds=50))
    calls = _count_extends(monkeypatch)
    cap = NOW + LEASE_CAP * LEASE
    job = meter.reserve(meter.authorize(_req(student)))
    with capture_logs() as logs, job.run():
        clock[0] = NOW + timedelta(minutes=100)
        _eventually(lambda: _deadline(sm, student) == clock[0] + LEASE, "a renewal under the cap")
        clock[0] = NOW + timedelta(minutes=150)  # a full lease from here would pass the cap
        _eventually(
            lambda: "usage_lease_cap_reached" in [e["event"] for e in logs], "the cap alert"
        )
        assert _deadline(sm, student) == cap  # clamped to the cap, not now + a lease
        at_cap = len(calls)
        clock[0] = NOW + timedelta(minutes=200)
        time.sleep(0.3)  # six renewal intervals
        assert len(calls) == at_cap, "renewed past the cap"
        assert _sweep(sm, cap) == 1  # the sweeper can now expire the hung run's hold
    (alert,) = [e for e in logs if e["event"] == "usage_lease_cap_reached"]
    assert (alert["log_level"], alert["alert"]) == ("error", True)
    assert alert["job_id"] == str(job.job_id)
    (row,) = jobs_for(sm, student)
    assert (row.status, row.charged) == (UsageJobStatus.expired, 0)


def test_exit_waits_for_a_renewal_already_in_flight(
    migrated_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """remove() blocks until the renewer's current extend returns: none lands after exit."""
    sm = migrated_sessionmaker
    student = _student(sm)
    clock = [NOW]
    meter = _meter(sm, clock, renew_every=timedelta(milliseconds=50))
    started, proceed, exited = threading.Event(), threading.Event(), threading.Event()
    original = UsageLedger.extend
    calls: list[int] = []

    def blocking(self: UsageLedger, job_id: uuid.UUID, *, expires_at: datetime, now: datetime):  # type: ignore[no-untyped-def]
        calls.append(1)
        if len(calls) == 2:  # #1 is run()'s own extend; #2 is the first renewal
            started.set()
            assert proceed.wait(timeout=30)
        return original(self, job_id, expires_at=expires_at, now=now)

    monkeypatch.setattr(UsageLedger, "extend", blocking)
    job = meter.reserve(meter.authorize(_req(student)))

    def work() -> None:
        with job.run():
            record_llm_cost(Decimal("0.020"))
            assert started.wait(timeout=30)
        exited.set()

    worker = _Paused(work)
    assert started.wait(timeout=30)
    assert not exited.wait(timeout=0.3), "exit returned while a renewal was in flight"
    proceed.set()
    worker.join()
    assert worker.error is None
    assert exited.is_set()
    (row,) = jobs_for(sm, student)
    assert (row.status, row.charged) == (UsageJobStatus.settled, 20)


def test_the_renewer_stops_once_the_hold_is_gone(
    migrated_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    sm = migrated_sessionmaker
    student = _student(sm)
    clock = [NOW]
    meter = _meter(sm, clock, renew_every=timedelta(milliseconds=50))
    calls = _count_extends(monkeypatch)
    job = meter.reserve(meter.authorize(_req(student)))
    with capture_logs() as logs, job.run():
        assert _sweep(sm, NOW + timedelta(days=1)) == 1  # the hold is gone mid-run
        _eventually(
            lambda: "usage_hold_lost_mid_run" in [e["event"] for e in logs], "the lost-hold line"
        )
        after = len(calls)
        time.sleep(0.3)  # six renewal intervals
        assert len(calls) == after, "kept renewing a hold that is gone"
    assert [e["event"] for e in logs].count("usage_hold_lost_mid_run") == 1


# --- fail closed at start ---------------------------------------------------------------


def test_a_failed_extend_proceeds_only_while_a_whole_timeout_remains(
    migrated_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    sm = migrated_sessionmaker
    student = _student(sm)
    clock = [NOW]
    meter = _meter(sm, clock)
    calls = _count_extends(monkeypatch, fail_first=10)
    job = meter.reserve(meter.authorize(_req(student)))
    clock[0] = NOW + timedelta(minutes=5)  # 50 min left of the 45 min timeout: enough
    with capture_logs() as logs, job.run():
        record_llm_cost(Decimal("0.020"))
    assert len(calls) == 2  # one retry
    assert [e["event"] for e in logs].count("usage_extend_failed") == 2
    (row,) = jobs_for(sm, student)
    assert (row.status, row.charged) == (UsageJobStatus.settled, 20)


def test_a_failed_extend_near_the_old_deadline_refuses_before_the_work(
    migrated_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    sm = migrated_sessionmaker
    student = _student(sm)
    clock = [NOW]
    meter = _meter(sm, clock)
    calls = _count_extends(monkeypatch, fail_first=10)
    job = meter.reserve(meter.authorize(_req(student)))
    clock[0] = NOW + timedelta(minutes=20)  # 35 min left: the sweeper could close it mid-run
    ran: list[bool] = []
    with pytest.raises(UsageUnavailable) as info, job.run():
        ran.append(True)
    assert ran == []
    assert str(info.value) == USAGE_UNAVAILABLE_MESSAGE  # a worker's generic handler shows it
    assert len(calls) == 2
    (row,) = jobs_for(sm, student)
    assert (row.status, row.charged) == (UsageJobStatus.released, 0)
    with pytest.raises(RuntimeError, match="already released"), job.run():
        ran.append(True)
    assert ran == []


def test_an_extend_that_succeeds_on_the_retry_proceeds(
    migrated_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    sm = migrated_sessionmaker
    student = _student(sm)
    clock = [NOW]
    meter = _meter(sm, clock)
    calls = _count_extends(monkeypatch, fail_first=1)
    job = meter.reserve(meter.authorize(_req(student)))
    clock[0] = NOW + timedelta(minutes=40)
    with job.run():
        assert _deadline(sm, student) == clock[0] + LEASE
        record_llm_cost(Decimal("0.020"))
    assert len(calls) == 2
    assert jobs_for(sm, student)[0].charged == 20


def test_a_re_reserve_that_fails_in_the_database_never_runs_unmetered(
    migrated_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    sm = migrated_sessionmaker
    student = _student(sm)
    clock = [NOW]
    meter = _meter(sm, clock)
    job = meter.reserve(meter.authorize(_req(student)))
    clock[0] = NOW + timedelta(hours=2)
    assert _sweep(sm, clock[0]) == 1

    def down(*_a: object, **_k: object) -> None:
        raise OperationalError("INSERT", {}, Exception("ledger down"))

    monkeypatch.setattr(UsageLedger, "reserve", down)
    ran: list[bool] = []
    with pytest.raises(OperationalError), job.run():
        ran.append(True)
    assert ran == []
    with pytest.raises(RuntimeError, match="already released"), job.run():
        ran.append(True)
    assert ran == []
    assert [j.status for j in jobs_for(sm, student)] == [UsageJobStatus.expired]


# --- only an expired hold is reserved again ---------------------------------------------


@pytest.mark.parametrize("closer", ["release", "settle"])
def test_a_job_closed_by_someone_else_is_never_reserved_again(
    migrated_sessionmaker: sessionmaker[Session], closer: str
) -> None:
    sm = migrated_sessionmaker
    student = _student(sm)
    clock = [NOW]
    meter = _meter(sm, clock)
    job = meter.reserve(meter.authorize(_req(student)))
    with sm.begin() as session:
        ledger = UsageLedger(session)
        if closer == "release":
            ledger.release(job.job_id, now=NOW)
        else:
            ledger.settle(job.job_id, actual_cost_usd=Decimal("0.010"), now=NOW)
    clock[0] = NOW + timedelta(hours=2)
    ran: list[bool] = []
    with (
        capture_logs() as logs,
        pytest.raises(RuntimeError, match="before its work started"),
        job.run(),
    ):
        ran.append(True)
    assert ran == []
    assert [e["log_level"] for e in logs if e["event"] == "usage_job_closed_before_start"] == [
        "error"
    ]
    assert len(jobs_for(sm, student)) == 1


def test_a_removed_assistants_queued_job_is_a_block_not_a_403_in_the_worker(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """The stale chain's re-check would raise phase 03's 403 inside the worker."""
    sm = migrated_sessionmaker
    seed_catalogue(sm)
    lead, helper = seed_user(sm, Role.teacher), seed_user(sm, Role.teacher)
    give(sm, lead, units=150)
    member = assistant(sm, teacher=lead, member=helper)
    clock = [NOW]
    meter = _meter(sm, clock)
    request = _req(helper, role=Role.teacher, assistant_member_id=member)
    queued = meter.reserve(meter.authorize(request))
    clock[0] = NOW + timedelta(hours=2)
    assert _sweep(sm, clock[0]) == 1
    meter.reserve(meter.authorize(request))  # the lead's 150 now cover only this one
    with sm.begin() as session:
        row = session.get(TeacherMember, member)
        assert row is not None
        row.status = TeacherMemberStatus.removed
    with pytest.raises(UsageBlocked) as info, queued.run():
        pass
    assert info.value.reason is UsageBlockReason.INSUFFICIENT_CREDITS


# --- races with the sweeper at the meter level ------------------------------------------


def test_a_run_whose_extend_queues_behind_an_open_sweep_reserves_again(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    student = _student(sm)
    clock = [NOW]
    meter = _meter(sm, clock)
    job = meter.reserve(meter.authorize(_req(student)))
    first_id = job.job_id
    clock[0] = NOW + timedelta(hours=2)

    def work() -> None:
        with job.run():
            record_llm_cost(Decimal("0.020"))

    holder = sm()
    try:
        holder.begin()
        assert UsageLedger(holder).expire_stale_jobs(now=clock[0]) == 1
        running = _Paused(work)
        _wait_until_a_backend_waits_on_a_lock(sm)  # run()'s extend is queued behind the sweep
        holder.commit()
    finally:
        holder.close()
    running.join()
    assert running.error is None
    old, new = jobs_for(sm, student)
    assert (old.job_id, old.status, old.charged) == (first_id, UsageJobStatus.expired, 0)
    assert (new.job_id, new.status, new.charged) == (job.job_id, UsageJobStatus.settled, 20)


def test_a_sweep_queued_behind_a_runs_extend_closes_nothing(
    migrated_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    sm = migrated_sessionmaker
    student = _student(sm)
    clock = [NOW]
    meter = _meter(sm, clock)
    job = meter.reserve(meter.authorize(_req(student)))
    clock[0] = NOW + timedelta(hours=2)
    extended, proceed = threading.Event(), threading.Event()
    original = UsageLedger.extend

    def held_open(self: UsageLedger, job_id: uuid.UUID, *, expires_at: datetime, now: datetime):  # type: ignore[no-untyped-def]
        result = original(self, job_id, expires_at=expires_at, now=now)
        extended.set()
        assert proceed.wait(timeout=30)  # the extend's transaction (and locks) stay open
        return result

    monkeypatch.setattr(UsageLedger, "extend", held_open)

    def work() -> None:
        with job.run():
            record_llm_cost(Decimal("0.020"))

    running = _Paused(work)
    assert extended.wait(timeout=30)
    sweeping = _Paused(lambda: _sweep(sm, clock[0]))
    _wait_until_a_backend_waits_on_a_lock(sm)  # the sweep read the job as stale, then queued
    proceed.set()
    running.join()
    sweeping.join()
    assert (running.error, sweeping.error, sweeping.result) == (None, None, 0)
    (row,) = jobs_for(sm, student)
    assert (row.status, row.charged) == (UsageJobStatus.settled, 20)
