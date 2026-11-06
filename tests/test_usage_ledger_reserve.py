"""UsageLedger reserve, release and job expiry (spec §5.6, §5.7 steps 3, 6, 7)."""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa

from lemely.core.usage_types import GrantScope, Payer, payer_to_json
from lemely.db.models.enums import Role
from lemely.db.models.usage import GrantKind, UsageEntryKind, UsageJob, UsageJobStatus
from lemely.db.usage_ledger_repo import InsufficientBalance, UsageLedger
from tests._concurrency import _Paused, _wait_until_a_backend_waits_on_a_lock
from tests.usage_db import (
    ACTION,
    ESTIMATOR_VERSION,
    NOW,
    RATE_VERSION,
    add_debt,
    add_user,
    balance,
    debts,
    emptied_after,
    entries,
    grant,
    job,
    own_chain,
    reserve,
    seat_chain,
    usage_database,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture(scope="module")
def usage_db() -> Iterator[sessionmaker[Session]]:
    with usage_database() as factory:
        yield factory


@pytest.fixture
def sm(usage_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(usage_db)


def _job_count(sm: sessionmaker[Session]) -> int:
    with sm() as session:
        return int(session.scalar(sa.select(sa.func.count()).select_from(UsageJob)) or 0)


# ---------------------------------------------------------------------------
# reserve
# ---------------------------------------------------------------------------


def test_reserve_holds_the_top_of_the_range_in_chain_order(sm: sessionmaker[Session]) -> None:
    owner = add_user(sm)
    allowance = grant(sm, owner, 6)
    credits = grant(sm, owner, 20, kind=GrantKind.credit_pack, visible=True)
    job_id = reserve(sm, own_chain(owner), 10, low=4)
    assert balance(sm, allowance) == (6, 6)
    assert balance(sm, credits) == (20, 4)
    holds = entries(sm, job_id=job_id, kind=UsageEntryKind.hold)
    assert {(e.grant_id, e.units, e.idempotency_key) for e in holds} == {
        (allowance, 6, f"job:{job_id}"),
        (credits, 4, f"job:{job_id}"),
    }
    row = job(sm, job_id)
    assert (row.status, row.reserved, row.estimate_low, row.estimate_high) == (
        UsageJobStatus.open,
        10,
        4,
        10,
    )
    assert row.payer_chain == [payer_to_json(p) for p in own_chain(owner)]


def test_reserve_spends_by_priority_then_soonest_expiry(sm: sessionmaker[Session]) -> None:
    owner = add_user(sm)
    later = grant(
        sm, owner, 5, kind=GrantKind.credit_pack, visible=True, expires_at=NOW + timedelta(days=60)
    )
    never = grant(sm, owner, 5, kind=GrantKind.credit_pack, visible=True)
    sooner = grant(
        sm, owner, 5, kind=GrantKind.credit_pack, visible=True, expires_at=NOW + timedelta(days=5)
    )
    adjustment = grant(sm, owner, 5, kind=GrantKind.adjustment, visible=True)
    reserve(sm, [own_chain(owner)[1]], 12)
    assert balance(sm, adjustment) == (5, 5)  # priority 40 before 50
    assert balance(sm, sooner) == (5, 5)
    assert balance(sm, later) == (5, 2)
    assert balance(sm, never) == (5, 0)  # never-expiring last


def test_reserve_refuses_when_the_chain_is_short_and_writes_nothing(
    sm: sessionmaker[Session],
) -> None:
    owner = add_user(sm)
    gid = grant(sm, owner, 9)
    with pytest.raises(InsufficientBalance) as caught:
        reserve(sm, own_chain(owner), 10)
    assert (caught.value.available, caught.value.required) == (9, 10)
    assert balance(sm, gid) == (9, 0)
    assert entries(sm, kind=UsageEntryKind.hold) == []
    assert _job_count(sm) == 0


def test_insufficient_balance_message_defaults_to_the_numbers() -> None:
    assert str(InsufficientBalance(available=3, required=5)) == "available 3 < required 5"
    assert str(InsufficientBalance("not enough")) == "not enough"


def test_reserve_validates(sm: sessionmaker[Session]) -> None:
    owner = add_user(sm)
    with pytest.raises(ValueError, match="payers"):
        reserve(sm, [], 1, actor=owner)
    with pytest.raises(ValueError, match="estimate_low"):
        reserve(sm, own_chain(owner), 1, low=2)
    with pytest.raises(ValueError, match="expires_at"):
        reserve(sm, own_chain(owner), 1, expires_at=NOW)
    with pytest.raises(ValueError, match="expires_at"):
        reserve(sm, own_chain(owner), 1, expires_at=NOW - timedelta(minutes=1))


def test_debt_blocks_the_owners_own_balance_but_not_a_seat(sm: sessionmaker[Session]) -> None:
    student, teacher, member = add_user(sm), add_user(sm, Role.teacher), uuid.uuid4()
    own = grant(sm, student, 50)
    seat = grant(sm, student, 8, kind=GrantKind.seat_allowance, teacher_member_id=member)
    add_debt(sm, student, 1)
    with pytest.raises(InsufficientBalance):
        reserve(sm, own_chain(student), 5)
    reserve(sm, seat_chain(student, teacher, member, cap=None), 8)
    assert balance(sm, seat) == (8, 8)
    assert balance(sm, own) == (50, 0)


def test_teacher_credits_stop_at_the_seat_cap_counting_open_holds(
    sm: sessionmaker[Session],
) -> None:
    student, teacher, member = add_user(sm), add_user(sm, Role.teacher), uuid.uuid4()
    teacher_credits = grant(sm, teacher, 100, kind=GrantKind.credit_pack, visible=True)
    chain = seat_chain(student, teacher, member, cap=10)
    reserve(sm, chain, 6, actor=student, teacher_member_id=member)
    assert balance(sm, teacher_credits) == (100, 6)
    # Only 4 of the cap is left; the student has nothing of their own.
    with pytest.raises(InsufficientBalance) as caught:
        reserve(sm, chain, 6, actor=student, teacher_member_id=member)
    assert (caught.value.available, caught.value.required) == (4, 6)
    own = grant(sm, student, 2)
    reserve(sm, chain, 6, actor=student, teacher_member_id=member)
    assert balance(sm, teacher_credits) == (100, 10)
    assert balance(sm, own) == (2, 2)


def test_hold_entries_carry_the_payers_member_for_cap_accounting(
    sm: sessionmaker[Session],
) -> None:
    """Two seats on one subject: the second teacher's credits count against the second cap."""
    student = add_user(sm)
    teacher_a, teacher_b = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    seat_a, seat_b = uuid.uuid4(), uuid.uuid4()
    credits_b = grant(sm, teacher_b, 100, kind=GrantKind.credit_pack, visible=True)
    chain = [
        Payer(
            owner_user_id=student, scope=GrantScope.SEAT, teacher_member_id=seat_a, debt_exempt=True
        ),
        Payer(
            owner_user_id=student, scope=GrantScope.SEAT, teacher_member_id=seat_b, debt_exempt=True
        ),
        Payer(
            owner_user_id=teacher_a, scope=GrantScope.CREDITS, teacher_member_id=seat_a, cap_units=5
        ),
        Payer(
            owner_user_id=teacher_b, scope=GrantScope.CREDITS, teacher_member_id=seat_b, cap_units=5
        ),
        *own_chain(student),
    ]
    job_id = reserve(sm, chain, 5, actor=student, teacher_member_id=seat_a)
    [hold] = entries(sm, job_id=job_id, kind=UsageEntryKind.hold)
    assert (hold.grant_id, hold.teacher_member_id) == (credits_b, seat_b)


# ---------------------------------------------------------------------------
# release and expiry
# ---------------------------------------------------------------------------


def test_release_frees_every_hold_at_no_charge(sm: sessionmaker[Session]) -> None:
    owner = add_user(sm)
    allowance = grant(sm, owner, 6)
    credits = grant(sm, owner, 20, kind=GrantKind.credit_pack, visible=True)
    job_id = reserve(sm, own_chain(owner), 10)
    with sm.begin() as session:
        released = UsageLedger(session).release(job_id, now=NOW)
        assert released.status is UsageJobStatus.released
    assert balance(sm, allowance) == (6, 0)
    assert balance(sm, credits) == (20, 0)
    releases = entries(sm, job_id=job_id, kind=UsageEntryKind.release)
    assert sorted(e.units for e in releases) == [-6, -4]
    assert job(sm, job_id).charged == 0
    with sm.begin() as session:  # a second release is a no-op
        UsageLedger(session).release(job_id, now=NOW)
    assert len(entries(sm, job_id=job_id, kind=UsageEntryKind.release)) == 2


def test_release_of_an_unknown_job_raises(sm: sessionmaker[Session]) -> None:
    with pytest.raises(LookupError), sm.begin() as session:
        UsageLedger(session).release(uuid.uuid4(), now=NOW)


def test_expire_stale_jobs_releases_only_jobs_past_expiry(sm: sessionmaker[Session]) -> None:
    owner = add_user(sm)
    gid = grant(sm, owner, 30)
    stale = reserve(sm, own_chain(owner), 10, expires_at=NOW + timedelta(minutes=5))
    fresh = reserve(sm, own_chain(owner), 10, expires_at=NOW + timedelta(hours=1))
    with sm.begin() as session:
        assert UsageLedger(session).expire_stale_jobs(now=NOW + timedelta(minutes=10)) == 1
    assert job(sm, stale).status is UsageJobStatus.expired
    assert job(sm, fresh).status is UsageJobStatus.open
    assert balance(sm, gid) == (30, 10)
    with sm.begin() as session:
        assert UsageLedger(session).expire_stale_jobs(now=NOW + timedelta(minutes=10)) == 0


# ---------------------------------------------------------------------------
# Task 4 review follow-ups (debt ordering, repay dating, replay mismatch)
# ---------------------------------------------------------------------------


def test_debts_created_in_one_transaction_repay_in_creation_order(
    sm: sessionmaker[Session],
) -> None:
    """``now()`` ties inside a transaction; ``clock_timestamp()`` keeps creation order."""
    owner = add_user(sm)
    with sm.begin() as session:
        ledger = UsageLedger(session)
        created = [ledger._open_debt(owner, 10).id for _ in range(8)]
    gid = grant(sm, owner, 25, kind=GrantKind.credit_pack, visible=True)
    assert balance(sm, gid) == (0, 0)
    rows = {d.id: d.outstanding for d in debts(sm, owner)}
    assert [rows[i] for i in created] == [0, 0, 5, 10, 10, 10, 10, 10]
    repays = entries(sm, grant_id=gid, kind=UsageEntryKind.debt_repay)
    assert {e.debt_id: e.units for e in repays} == {
        created[0]: -10,
        created[1]: -10,
        created[2]: -5,
    }


def test_open_debt_links_the_job_and_starts_fully_outstanding(sm: sessionmaker[Session]) -> None:
    owner = add_user(sm)
    grant(sm, owner, 5)
    job_id = reserve(sm, own_chain(owner), 5)
    with sm.begin() as session:
        debt = UsageLedger(session)._open_debt(owner, 7, job_id=job_id)
        assert (debt.owner_user_id, debt.units, debt.outstanding) == (owner, 7, 7)
        assert debt.job_id == job_id
    [row] = debts(sm, owner)
    assert (row.units, row.outstanding, row.job_id) == (7, 7, job_id)


def test_debt_repay_entries_are_never_dated_before_now(sm: sessionmaker[Session]) -> None:
    owner = add_user(sm)
    add_debt(sm, owner, 10)
    started = datetime.now(UTC)
    backdated = started - timedelta(days=30)
    gid = grant(sm, owner, 50, kind=GrantKind.credit_pack, visible=True, effective_at=backdated)
    [grant_entry] = entries(sm, grant_id=gid, kind=UsageEntryKind.grant)
    [repay] = entries(sm, grant_id=gid, kind=UsageEntryKind.debt_repay)
    assert grant_entry.event_at == backdated
    assert repay.event_at >= started


def test_debt_repay_entry_follows_a_future_dated_grant(sm: sessionmaker[Session]) -> None:
    owner = add_user(sm)
    add_debt(sm, owner, 10)
    future = datetime.now(UTC) + timedelta(days=3)
    gid = grant(sm, owner, 50, kind=GrantKind.credit_pack, visible=True, effective_at=future)
    [repay] = entries(sm, grant_id=gid, kind=UsageEntryKind.debt_repay)
    assert repay.event_at == future


def test_replay_with_a_different_kind_or_units_warns_and_returns_the_existing_grant(
    sm: sessionmaker[Session], caplog: pytest.LogCaptureFixture
) -> None:
    owner = add_user(sm)
    first = grant(sm, owner, 50, key="period:2026-11")
    with caplog.at_level(logging.WARNING, logger="lemely.db.usage_ledger_repo"):
        same = grant(sm, owner, 50, key="period:2026-11")
        assert caplog.records == []  # an identical replay is silent
        more = grant(sm, owner, 60, key="period:2026-11")
        other = grant(sm, owner, 50, kind=GrantKind.credit_pack, visible=True, key="period:2026-11")
    assert first == same == more == other
    assert len(caplog.records) == 2
    assert all(r.levelno == logging.WARNING for r in caplog.records)
    assert all("period:2026-11" in r.getMessage() for r in caplog.records)
    assert balance(sm, first) == (50, 0)


# ---------------------------------------------------------------------------
# Task 5 review fixes (expired grants, stranded holds, lock order)
# ---------------------------------------------------------------------------


def test_release_frees_a_hold_on_a_grant_that_expired_after_reserving(
    sm: sessionmaker[Session],
) -> None:
    owner = add_user(sm)
    gid = grant(sm, owner, 30, expires_at=NOW + timedelta(minutes=10))
    job_id = reserve(sm, own_chain(owner), 10)
    assert balance(sm, gid) == (30, 10)
    with sm.begin() as session:
        UsageLedger(session).release(job_id, now=NOW + timedelta(minutes=20))
    assert balance(sm, gid) == (30, 0)
    assert job(sm, job_id).status is UsageJobStatus.released
    [release] = entries(sm, job_id=job_id, kind=UsageEntryKind.release)
    assert (release.grant_id, release.units) == (gid, -10)


def test_expire_stale_jobs_frees_a_hold_on_a_grant_that_expired_after_reserving(
    sm: sessionmaker[Session],
) -> None:
    owner = add_user(sm)
    gid = grant(sm, owner, 30, expires_at=NOW + timedelta(minutes=10))
    job_id = reserve(sm, own_chain(owner), 10, expires_at=NOW + timedelta(minutes=15))
    with sm.begin() as session:
        assert UsageLedger(session).expire_stale_jobs(now=NOW + timedelta(minutes=20)) == 1
    assert balance(sm, gid) == (30, 0)
    assert job(sm, job_id).status is UsageJobStatus.expired


def test_closing_a_job_whose_chain_no_longer_reaches_its_holds_raises(
    sm: sessionmaker[Session],
) -> None:
    owner, other = add_user(sm), add_user(sm)
    gid = grant(sm, owner, 30)
    job_id = reserve(sm, own_chain(owner), 10)
    with sm.begin() as session:
        session.execute(
            sa.update(UsageJob)
            .where(UsageJob.job_id == job_id)
            .values(payer_chain=[payer_to_json(p) for p in own_chain(other)])
        )
    with pytest.raises(RuntimeError, match="no longer reaches"), sm.begin() as session:
        UsageLedger(session).release(job_id, now=NOW)
    assert balance(sm, gid) == (30, 10)  # the failed close rolled back
    assert job(sm, job_id).status is UsageJobStatus.open


def test_sweeper_and_reserve_over_the_same_owners_do_not_deadlock(
    sm: sessionmaker[Session],
) -> None:
    """The sweeper closes B's job before A's; a reserve locks A before B.

    Without one sorted pre-lock in ``expire_stale_jobs`` the sweeper holds B
    while waiting for A, and the reserve holds A while waiting for B.
    """
    low, high = sorted([add_user(sm), add_user(sm)])
    grant(sm, low, 100)
    grant(sm, high, 100)
    reserve(sm, own_chain(high), 10, expires_at=NOW + timedelta(minutes=5))  # closed first
    reserve(sm, own_chain(low), 10, expires_at=NOW + timedelta(minutes=8))
    holds_low = threading.Event()
    go = threading.Event()
    reserved = uuid.uuid4()

    def reserver() -> None:
        with sm.begin() as session:
            ledger = UsageLedger(session)
            ledger._lock_owners([low])
            holds_low.set()
            assert go.wait(30)
            ledger.reserve(
                job_id=reserved,
                actor_user_id=low,
                action=ACTION,
                payers=[*own_chain(low), *own_chain(high)],
                estimate_low=0,
                estimate_high=5,
                estimator_version=ESTIMATOR_VERSION,
                rate_version=RATE_VERSION,
                teacher_member_id=None,
                expires_at=NOW + timedelta(hours=1),
                now=NOW,
            )

    def sweeper() -> int:
        assert holds_low.wait(30)
        with sm.begin() as session:
            return UsageLedger(session).expire_stale_jobs(now=NOW + timedelta(minutes=10))

    reserving = _Paused(reserver)
    sweeping = _Paused(sweeper)
    assert holds_low.wait(30)
    _wait_until_a_backend_waits_on_a_lock(sm)  # the sweeper is queued behind the reserver
    go.set()
    reserving.join()
    sweeping.join()
    assert reserving.error is None
    assert sweeping.error is None
    assert sweeping.result == 2
    assert job(sm, reserved).status is UsageJobStatus.open
