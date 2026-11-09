"""UsageLedger settle: actual cost, chain draw-down and debt (spec §5.7 step 5, §5.8, §9)."""

from __future__ import annotations

import itertools
import threading
import uuid
from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa

from lemely.core.usage_types import GrantScope, Payer, payer_to_json
from lemely.db.models.enums import Role
from lemely.db.models.usage import GrantKind, UsageEntryKind, UsageJob, UsageJobStatus
from lemely.db.usage_ledger_repo import InsufficientBalance, UsageLedger
from tests._concurrency import _Paused, _wait_until_a_backend_waits_on_a_lock
from tests.usage_db import (
    NOW,
    add_rate,
    add_seat_member,
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


@pytest.fixture(autouse=True)
def _rate(sm: sessionmaker[Session]) -> None:
    """``emptied_after`` truncates ``usage_rates`` too, so every test re-adds its rate."""
    add_rate(sm)  # 1000 units per USD


def settle(factory: sessionmaker[Session], job_id: uuid.UUID, usd: str) -> None:
    with factory.begin() as session:
        UsageLedger(session).settle(job_id, actual_cost_usd=Decimal(usd), now=NOW)


def test_settle_under_the_reservation_charges_actual_and_releases_the_rest(
    sm: sessionmaker[Session],
) -> None:
    owner = add_user(sm)
    gid = grant(sm, owner, 20)
    job_id = reserve(sm, own_chain(owner), 10)
    settle(sm, job_id, "0.0042")  # ceil(4.2) = 5 units
    assert balance(sm, gid) == (15, 0)
    row = job(sm, job_id)
    assert (row.status, row.charged, row.debt_created, row.settled_at) == (
        UsageJobStatus.settled,
        5,
        0,
        NOW,
    )
    assert row.actual_cost_usd == Decimal("0.004200")
    kinds = [(e.kind, e.units) for e in entries(sm, job_id=job_id)]
    assert sorted(kinds, key=lambda k: k[0].value) == [
        (UsageEntryKind.hold, 10),
        (UsageEntryKind.release, -10),
        (UsageEntryKind.settle, -5),
    ]
    assert all(e.rate_version == 1 for e in entries(sm, job_id=job_id))


def test_settle_at_the_reservation(sm: sessionmaker[Session]) -> None:
    owner = add_user(sm)
    gid = grant(sm, owner, 10)
    job_id = reserve(sm, own_chain(owner), 10)
    settle(sm, job_id, "0.010")
    assert balance(sm, gid) == (0, 0)
    assert job(sm, job_id).charged == 10


def test_settle_over_the_reservation_keeps_drawing_down_the_chain(
    sm: sessionmaker[Session],
) -> None:
    owner = add_user(sm)
    allowance = grant(sm, owner, 10)
    credits = grant(sm, owner, 20, kind=GrantKind.credit_pack, visible=True)
    job_id = reserve(sm, own_chain(owner), 10)
    assert balance(sm, credits) == (20, 0)
    settle(sm, job_id, "0.025")
    assert balance(sm, allowance) == (0, 0)
    assert balance(sm, credits) == (5, 0)
    assert job(sm, job_id).debt_created == 0
    assert debts(sm, owner) == []


def test_settle_beyond_the_chain_creates_debt_that_blocks_and_is_repaid(
    sm: sessionmaker[Session],
) -> None:
    owner = add_user(sm)
    gid = grant(sm, owner, 10)
    credits = grant(sm, owner, 30, kind=GrantKind.credit_pack, visible=True)
    allowance_only = own_chain(owner)[:1]
    job_id = reserve(sm, allowance_only, 10)
    settle(sm, job_id, "0.025")  # the credits are not in this chain
    assert balance(sm, gid) == (0, 0)
    assert balance(sm, credits) == (30, 0)
    row = job(sm, job_id)
    assert (row.charged, row.debt_created) == (25, 15)
    [debt] = debts(sm, owner)
    assert (debt.units, debt.outstanding, debt.job_id) == (15, 15, job_id)
    [debt_entry] = entries(sm, kind=UsageEntryKind.debt)
    assert (debt_entry.debt_id, debt_entry.units, debt_entry.grant_id) == (debt.id, -15, None)
    # Debt blocks new jobs on the owner's own balance, even one the credits could cover.
    with pytest.raises(InsufficientBalance):
        reserve(sm, own_chain(owner), 1)
    # The next own grant pays the debt first.
    pack = grant(sm, owner, 20, kind=GrantKind.credit_pack, visible=True)
    assert balance(sm, pack) == (5, 0)
    assert debts(sm, owner)[0].outstanding == 0
    reserve(sm, own_chain(owner), 5)


def test_debt_lands_on_the_payer_of_last_resort_not_the_teacher(
    sm: sessionmaker[Session],
) -> None:
    student, teacher = add_user(sm), add_user(sm, Role.teacher)
    member = add_seat_member(sm, student, teacher)
    seat = grant(sm, student, 10, kind=GrantKind.seat_allowance, teacher_member_id=member)
    teacher_credits = grant(sm, teacher, 100, kind=GrantKind.credit_pack, visible=True)
    chain = seat_chain(student, teacher, member, cap=5)
    job_id = reserve(sm, chain, 10, actor=student, teacher_member_id=member)
    settle(sm, job_id, "0.030")  # 30 units: seat 10, teacher cap 5, then 15 of debt
    assert balance(sm, seat) == (0, 0)
    assert balance(sm, teacher_credits) == (95, 0)
    assert debts(sm, teacher) == []
    assert [d.units for d in debts(sm, student)] == [15]


def test_cap_window_ignores_settled_draws_before_it(sm: sessionmaker[Session]) -> None:
    student, teacher, member = add_user(sm), add_user(sm, Role.teacher), uuid.uuid4()
    teacher_credits = grant(sm, teacher, 100, kind=GrantKind.credit_pack, visible=True)
    lifetime = seat_chain(student, teacher, member, cap=10)
    first = reserve(sm, lifetime, 8, actor=student, teacher_member_id=member)
    settle(sm, first, "0.008")
    assert balance(sm, teacher_credits) == (92, 0)
    # Lifetime cap: 2 left. A monthly window starting after the first job: 10 left.
    with pytest.raises(InsufficientBalance):
        reserve(sm, lifetime, 8, actor=student, teacher_member_id=member)
    windowed = seat_chain(student, teacher, member, cap=10)
    windowed[1] = Payer(
        owner_user_id=teacher,
        scope=GrantScope.CREDITS,
        teacher_member_id=member,
        cap_units=10,
        cap_window_start=NOW + timedelta(seconds=1),
    )
    reserve(sm, windowed, 8, actor=student, teacher_member_id=member)
    assert balance(sm, teacher_credits) == (92, 8)


def test_held_units_on_a_grant_that_expired_still_settle(sm: sessionmaker[Session]) -> None:
    owner = add_user(sm)
    gid = grant(sm, owner, 10, expires_at=NOW + timedelta(minutes=1))
    job_id = reserve(sm, own_chain(owner), 10)
    with sm.begin() as session:
        UsageLedger(session).settle(
            job_id, actual_cost_usd=Decimal("0.004"), now=NOW + timedelta(minutes=5)
        )
    assert balance(sm, gid) == (6, 0)
    assert job(sm, job_id).debt_created == 0


def test_settle_is_a_no_op_on_a_closed_job(sm: sessionmaker[Session]) -> None:
    owner = add_user(sm)
    gid = grant(sm, owner, 10)
    job_id = reserve(sm, own_chain(owner), 10)
    with sm.begin() as session:
        UsageLedger(session).release(job_id, now=NOW)
    settle(sm, job_id, "0.005")
    assert balance(sm, gid) == (10, 0)
    assert job(sm, job_id).status is UsageJobStatus.released
    settled = reserve(sm, own_chain(owner), 10)
    settle(sm, settled, "0.002")
    settle(sm, settled, "0.009")
    assert job(sm, settled).charged == 2
    assert balance(sm, gid) == (8, 0)


def test_settle_needs_the_jobs_rate_and_an_existing_job(sm: sessionmaker[Session]) -> None:
    owner = add_user(sm)
    grant(sm, owner, 10)
    job_id = reserve(sm, own_chain(owner), 1)
    with sm.begin() as session:
        session.execute(sa.text("DELETE FROM usage_rates"))
    with pytest.raises(LookupError, match="no usage rate"):
        settle(sm, job_id, "0.001")
    with pytest.raises(LookupError, match="no usage job"):
        settle(sm, uuid.uuid4(), "0.001")


# ---------------------------------------------------------------------------
# Task 6 review fixes (debt order, stranded holds, concurrent release)
# ---------------------------------------------------------------------------


def test_debts_from_one_transaction_repay_in_creation_order(sm: sessionmaker[Session]) -> None:
    """``_open_debt`` stamps ``clock_timestamp()``, so same-transaction debts do not tie."""
    owner = add_user(sm)
    jobs = [reserve(sm, own_chain(owner), 0) for _ in range(8)]
    with sm.begin() as session:
        ledger = UsageLedger(session)
        for n, job_id in enumerate(jobs, start=1):
            ledger.settle(job_id, actual_cost_usd=Decimal(n) / 1000, now=NOW)  # n units of debt
    rows = {d.job_id: d for d in debts(sm, owner)}
    assert [rows[j].units for j in jobs] == list(range(1, 9))
    stamps = [rows[j].created_at for j in jobs]
    assert all(a < b for a, b in itertools.pairwise(stamps))
    grant(sm, owner, 10, kind=GrantKind.credit_pack, visible=True)
    repaid = {d.job_id: d.outstanding for d in debts(sm, owner)}
    assert [repaid[j] for j in jobs] == [0, 0, 0, 0, 5, 6, 7, 8]


def test_settle_with_stranded_holds_raises_and_writes_nothing(
    sm: sessionmaker[Session],
) -> None:
    """The chain still reaches the seat grant but no longer the teacher's credits."""
    student, teacher = add_user(sm), add_user(sm, Role.teacher)
    member = add_seat_member(sm, student, teacher)
    seat = grant(sm, student, 5, kind=GrantKind.seat_allowance, teacher_member_id=member)
    credits = grant(sm, teacher, 50, kind=GrantKind.credit_pack, visible=True)
    chain = seat_chain(student, teacher, member, cap=100)
    job_id = reserve(sm, chain, 10, actor=student, teacher_member_id=member)
    assert (balance(sm, seat), balance(sm, credits)) == ((5, 5), (50, 5))
    with sm.begin() as session:
        session.execute(
            sa.update(UsageJob)
            .where(UsageJob.job_id == job_id)
            .values(payer_chain=[payer_to_json(chain[0])])
        )
    with sm.begin() as session:
        with pytest.raises(RuntimeError, match="no longer reaches"):
            UsageLedger(session).settle(job_id, actual_cost_usd=Decimal("0.005"), now=NOW)
        assert not session.new
        assert not session.dirty
    assert (balance(sm, seat), balance(sm, credits)) == ((5, 5), (50, 5))
    assert job(sm, job_id).status is UsageJobStatus.open


def test_settle_waits_for_a_concurrent_release_and_then_does_nothing(
    sm: sessionmaker[Session],
) -> None:
    owner = add_user(sm)
    gid = grant(sm, owner, 30)
    job_id = reserve(sm, own_chain(owner), 10)
    holds_owner = threading.Event()
    go = threading.Event()

    def releaser() -> None:
        with sm.begin() as session:
            ledger = UsageLedger(session)
            ledger._lock_owners([owner])
            holds_owner.set()
            assert go.wait(30)
            ledger.release(job_id, now=NOW)

    def settler() -> UsageJobStatus:
        assert holds_owner.wait(30)
        with sm.begin() as session:
            row = UsageLedger(session).settle(job_id, actual_cost_usd=Decimal("0.007"), now=NOW)
            return row.status

    releasing = _Paused(releaser)
    settling = _Paused(settler)
    assert holds_owner.wait(30)
    _wait_until_a_backend_waits_on_a_lock(sm)  # the settle is queued behind the release
    go.set()
    releasing.join()
    settling.join()
    assert releasing.error is None
    assert settling.error is None
    assert settling.result is UsageJobStatus.released
    assert balance(sm, gid) == (30, 0)
    assert job(sm, job_id).charged == 0
    assert [e.kind for e in entries(sm, job_id=job_id) if e.kind is UsageEntryKind.settle] == []


def test_settle_quantizes_the_cost_so_stored_usd_and_units_agree(
    sm: sessionmaker[Session],
) -> None:
    owner = add_user(sm)
    grant(sm, owner, 100)
    finer = reserve(sm, own_chain(owner), 10)
    settle(sm, finer, "0.0000001")  # below 6 dp: rounds to zero, so no unit is charged
    row = job(sm, finer)
    assert (row.actual_cost_usd, row.charged) == (Decimal("0.000000"), 0)
    half = reserve(sm, own_chain(owner), 10)
    settle(sm, half, "0.0000005")  # rounds half up to 0.000001: one unit at 1000/USD
    row = job(sm, half)
    assert (row.actual_cost_usd, row.charged) == (Decimal("0.000001"), 1)


def test_settle_cap_counts_what_the_held_slot_already_took(sm: sessionmaker[Session]) -> None:
    """Overage after a capped hold: the cap covers the held draw plus the walk, not each alone."""
    student, teacher, member = add_user(sm), add_user(sm, Role.teacher), uuid.uuid4()
    credits = grant(sm, teacher, 100, kind=GrantKind.credit_pack, visible=True)
    chain = seat_chain(student, teacher, member, cap=20)
    job_id = reserve(sm, chain, 5, actor=student, teacher_member_id=member)
    assert balance(sm, credits) == (100, 5)
    settle(sm, job_id, "0.030")  # 30 units: 5 from the hold, 15 more up to the cap, 10 debt
    assert balance(sm, credits) == (80, 0)
    row = job(sm, job_id)
    assert (row.charged, row.debt_created) == (30, 10)
    assert debts(sm, teacher) == []
    assert [d.units for d in debts(sm, student)] == [10]
