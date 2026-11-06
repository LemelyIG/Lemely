"""UsageLedger.reconcile_balances: entries against the cache and the debts (spec §4.5, §6, §11)."""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa

from lemely.db.models.enums import Role
from lemely.db.models.usage import GrantKind, UsageEntry, UsageEntryKind
from lemely.db.usage_ledger_repo import UsageLedger
from tests._concurrency import _Paused, _wait_until_a_backend_waits_on_a_lock
from tests.usage_db import (
    ACTION,
    ESTIMATOR_VERSION,
    NOW,
    RATE_VERSION,
    add_debt,
    add_rate,
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

LATER = NOW + timedelta(minutes=5)


@pytest.fixture(scope="module")
def usage_db() -> Iterator[sessionmaker[Session]]:
    with usage_database() as factory:
        yield factory


@pytest.fixture
def sm(usage_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(usage_db)


def reconcile(factory: sessionmaker[Session]) -> list[tuple[uuid.UUID, int, int]]:
    with factory.begin() as session:
        return UsageLedger(session).reconcile_balances()


def _busy_ledger(factory: sessionmaker[Session]) -> uuid.UUID:
    """Every entry kind at least once; returns the student, who ends up in debt."""
    add_rate(factory)
    student, teacher, member = add_user(factory), add_user(factory, Role.teacher), uuid.uuid4()
    grant(factory, student, 10, expires_at=NOW + timedelta(minutes=1))
    grant(factory, student, 6, kind=GrantKind.seat_allowance, teacher_member_id=member)
    pack = grant(factory, teacher, 50, kind=GrantKind.credit_pack, visible=True)
    chain = seat_chain(student, teacher, member, cap=5)
    settled = reserve(factory, chain, 8, actor=student, teacher_member_id=member)
    released = reserve(factory, own_chain(student), 3)
    reserve(factory, own_chain(student), 2, expires_at=NOW + timedelta(seconds=30))  # goes stale
    with factory.begin() as session:
        ledger = UsageLedger(session)
        ledger.settle(settled, actual_cost_usd=Decimal("0.040"), now=LATER)  # overage -> debt
        ledger.release(released, now=LATER)
        ledger.expire_stale_jobs(now=LATER)
        ledger.expire_grants(now=LATER)
        ledger.claw_back_grant(pack, reason="refund", now=LATER)
        ledger.forgive_debt(student, units=3, reason="support", now=LATER)
        ledger.adjust(owner_user_id=student, units=4, reason="fix", idempotency_key="a", now=LATER)
    # A new credit pack repays more debt; a negative adjust then debits it.
    grant(factory, student, 5, kind=GrantKind.credit_pack, visible=True, key="repay-pack")
    with factory.begin() as session:
        UsageLedger(session).adjust(
            owner_user_id=student, units=-2, reason="abuse", idempotency_key="b", now=LATER
        )
    return student


def test_a_busy_ledger_reconciles_with_zero_drift(sm: sessionmaker[Session]) -> None:
    student = _busy_ledger(sm)
    assert debts(sm, student)  # the run really did create (and partly repay) debt
    assert reconcile(sm) == []


def test_reconcile_reports_and_repairs_grant_drift(sm: sessionmaker[Session]) -> None:
    owner = add_user(sm)
    gid = grant(sm, owner, 20)
    reserve(sm, own_chain(owner), 5)
    with sm.begin() as session:
        session.execute(
            sa.text(
                "UPDATE usage_grant_balances SET remaining = remaining + 3, held = held + 1 "
                "WHERE grant_id = :g"
            ),
            {"g": gid},
        )
    assert balance(sm, gid) == (23, 6)
    assert sorted(reconcile(sm)) == sorted([(gid, 23, 20), (gid, 6, 5)])
    assert balance(sm, gid) == (20, 5)
    assert reconcile(sm) == []


def test_reconcile_reports_and_repairs_debt_drift(sm: sessionmaker[Session]) -> None:
    student = _busy_ledger(sm)
    debt = debts(sm, student)[0]  # the settle overage; a job-less debt follows it
    assert debt.job_id is not None
    with sm.begin() as session:
        session.execute(
            sa.text("UPDATE usage_debts SET outstanding = units WHERE id = :d"), {"d": debt.id}
        )
    assert reconcile(sm) == [(debt.id, debt.units, debt.outstanding)]
    assert debts(sm, student)[0].outstanding == debt.outstanding
    assert reconcile(sm) == []


def _jobless_debts(factory: sessionmaker[Session]) -> tuple[uuid.UUID, uuid.UUID]:
    """A debt seeded by a negative adjust and then partly forgiven; and one repaid by a grant."""
    forgiven, repaid = add_user(factory), add_user(factory)
    with factory.begin() as session:
        ledger = UsageLedger(session)
        ledger.adjust(
            owner_user_id=forgiven, units=-9, reason="seed", idempotency_key="seed", now=NOW
        )
        ledger.forgive_debt(forgiven, units=4, reason="support", now=LATER)
        ledger.adjust(
            owner_user_id=repaid, units=-6, reason="seed", idempotency_key="seed", now=NOW
        )
    grant(factory, repaid, 10, kind=GrantKind.credit_pack, visible=True)
    return forgiven, repaid


def test_job_less_debts_reconcile_through_forgiveness_and_repayment(
    sm: sessionmaker[Session],
) -> None:
    forgiven, repaid = _jobless_debts(sm)
    assert [d.outstanding for d in debts(sm, forgiven)] == [5]
    assert [d.outstanding for d in debts(sm, repaid)] == [0]
    assert reconcile(sm) == []


def test_a_debt_with_no_entries_at_all_is_fully_outstanding(sm: sessionmaker[Session]) -> None:
    owner = add_user(sm)
    add_debt(sm, owner, 7)  # inserted directly: no debt entry, no repayment
    assert reconcile(sm) == []


def test_reconcile_reports_exactly_one_cached_remaining_held_and_debt_and_repairs_them(
    sm: sessionmaker[Session],
) -> None:
    student = _busy_ledger(sm)
    _forgiven, repaid = _jobless_debts(sm)
    assert reconcile(sm) == []
    with sm.begin() as session:
        rows = session.execute(
            sa.text("SELECT grant_id, remaining, held FROM usage_grant_balances ORDER BY grant_id")
        ).all()
    # The grant that repaid a debt and kept 4 units has room under its remaining for the
    # held drift; the remaining drift goes on a different grant.
    [held_row] = [r for r in rows if r.remaining - r.held >= 1]
    remaining_row = next(r for r in rows if r.grant_id != held_row.grant_id)
    student_debt = debts(sm, student)[0]
    assert student_debt.outstanding > 1
    with sm.begin() as session:
        session.execute(
            sa.text(
                "UPDATE usage_grant_balances SET remaining = remaining + 7 WHERE grant_id = :g"
            ),
            {"g": remaining_row.grant_id},
        )
        session.execute(
            sa.text("UPDATE usage_grant_balances SET held = held + 1 WHERE grant_id = :g"),
            {"g": held_row.grant_id},
        )
        session.execute(
            sa.text("UPDATE usage_debts SET outstanding = outstanding - 1 WHERE id = :d"),
            {"d": student_debt.id},
        )
    assert sorted(reconcile(sm)) == sorted(
        [
            (remaining_row.grant_id, remaining_row.remaining + 7, remaining_row.remaining),
            (held_row.grant_id, held_row.held + 1, held_row.held),
            (student_debt.id, student_debt.outstanding - 1, student_debt.outstanding),
        ]
    )
    assert balance(sm, remaining_row.grant_id)[0] == remaining_row.remaining
    assert balance(sm, held_row.grant_id)[1] == held_row.held
    assert debts(sm, student)[0].outstanding == student_debt.outstanding
    assert reconcile(sm) == []


def _in_id_order(
    first_is_stray: bool, one: uuid.UUID, other: uuid.UUID
) -> tuple[uuid.UUID, uuid.UUID]:
    """``(stray, clean)`` so that the stray row's id sorts first or last: reconcile walks by id."""
    low, high = sorted([one, other])
    return (low, high) if first_is_stray else (high, low)


@pytest.mark.parametrize("stray_first", [True, False], ids=["stray-first", "stray-last"])
def test_a_grant_whose_repair_breaks_a_check_does_not_stop_the_rest(
    sm: sessionmaker[Session], caplog: pytest.LogCaptureFixture, stray_first: bool
) -> None:
    """One grant is cleanly drifted; another has a stray hold entry, so its recomputed
    ``held`` (15) exceeds its ``remaining`` (10) and the repair would violate
    ``held_within_remaining``. Whichever sorts first, the clean one is repaired, both
    are reported, the run does not raise, and the error names the row that failed."""
    owner = add_user(sm)
    stray, clean = _in_id_order(stray_first, grant(sm, owner, 10), grant(sm, owner, 10))
    with sm.begin() as session:
        session.execute(
            sa.text(
                "UPDATE usage_grant_balances SET remaining = remaining + 5 WHERE grant_id = :g"
            ),
            {"g": clean},
        )
        session.add(
            UsageEntry(
                grant_id=stray,
                kind=UsageEntryKind.hold,
                units=15,
                event_at=NOW,
                idempotency_key="stray-hold",
            )
        )
    stray_remaining = balance(sm, stray)[0]
    clean_remaining = balance(sm, clean)[0] - 5
    with (
        caplog.at_level(logging.ERROR, logger="lemely.db.usage_ledger_repo"),
        sm.begin() as session,
    ):
        drift = UsageLedger(session).reconcile_balances()
        # Inside the reconciling session: the rejected value did not stay on the row.
        rows = {
            gid: (rem, held)
            for gid, rem, held in session.execute(
                sa.text("SELECT grant_id, remaining, held FROM usage_grant_balances")
            )
        }
        assert rows[stray] == (stray_remaining, 0)
        assert rows[clean] == (clean_remaining, 0)
    assert sorted(drift) == sorted([(clean, clean_remaining + 5, clean_remaining), (stray, 0, 15)])
    assert balance(sm, clean) == (clean_remaining, 0)
    assert balance(sm, stray) == (stray_remaining, 0)  # left as it was: the repair is impossible
    errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert str(stray) in errors[0]
    assert str(clean) not in errors[0]


@pytest.mark.parametrize("stray_first", [True, False], ids=["stray-first", "stray-last"])
def test_a_debt_whose_repair_breaks_a_check_does_not_stop_the_rest(
    sm: sessionmaker[Session], caplog: pytest.LogCaptureFixture, stray_first: bool
) -> None:
    """The same for debts: a stray 9-unit repayment on a 7-unit debt recomputes to -2
    outstanding, which breaks ``outstanding_within_units``; the other debt, drifted
    cleanly from 7 to 3, is still repaired."""
    owner = add_user(sm)
    stray, clean = _in_id_order(stray_first, add_debt(sm, owner, 7), add_debt(sm, owner, 7))
    with sm.begin() as session:
        session.execute(
            sa.text("UPDATE usage_debts SET outstanding = 3 WHERE id = :d"), {"d": clean}
        )
        session.add(
            UsageEntry(
                debt_id=stray,
                kind=UsageEntryKind.debt_repay,
                units=-9,
                event_at=NOW,
                idempotency_key="stray-repay",
            )
        )
    with (
        caplog.at_level(logging.ERROR, logger="lemely.db.usage_ledger_repo"),
        sm.begin() as session,
    ):
        drift = UsageLedger(session).reconcile_balances()
        rows = dict(session.execute(sa.text("SELECT id, outstanding FROM usage_debts")).all())
        assert rows[stray] == 7
        assert rows[clean] == 7
    assert sorted(drift) == sorted([(clean, 3, 7), (stray, 7, -2)])
    assert sorted(d.outstanding for d in debts(sm, owner)) == [7, 7]
    errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert str(stray) in errors[0]
    assert str(clean) not in errors[0]


def test_a_clean_ledger_and_an_empty_one_report_nothing(sm: sessionmaker[Session]) -> None:
    assert reconcile(sm) == []
    owner = add_user(sm)
    grant(sm, owner, 5)
    assert reconcile(sm) == []


def test_reconcile_ignores_drift_another_transaction_repairs_before_the_lock(
    sm: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Guard: a drifted row is re-read under its lock, so a repair that lands after the scan
    is not reported again."""
    owner = add_user(sm)
    gid = grant(sm, owner, 20)
    with sm.begin() as session:
        session.execute(
            sa.text("UPDATE usage_grant_balances SET remaining = 25 WHERE grant_id = :g"),
            {"g": gid},
        )
    real_lock = UsageLedger._lock_owners

    def lock_after_a_rival_repairs(self: UsageLedger, owner_ids: object) -> None:
        monkeypatch.setattr(UsageLedger, "_lock_owners", real_lock)
        with sm.begin() as rival:
            rival.execute(
                sa.text("UPDATE usage_grant_balances SET remaining = 20 WHERE grant_id = :g"),
                {"g": gid},
            )
        real_lock(self, owner_ids)  # type: ignore[arg-type]

    monkeypatch.setattr(UsageLedger, "_lock_owners", lock_after_a_rival_repairs)
    assert reconcile(sm) == []
    assert balance(sm, gid) == (20, 0)


def test_reconcile_and_a_reserve_over_the_same_owners_do_not_deadlock(
    sm: sessionmaker[Session],
) -> None:
    """Reconcile repairs grants of two owners; a reserve spans the same two.

    The reserver holds the lower owner's advisory lock and the row of the grant
    reconcile reaches second, then wants the grant reconcile reaches first. Without
    one sorted owner pre-lock, reconcile takes the first grant's row and queues for
    the second: a deadlock once the reserver goes on. With it, reconcile queues on
    the owner lock holding no row at all.
    """
    low, high = sorted([add_user(sm), add_user(sm)])
    low_grant, high_grant = grant(sm, low, 20), grant(sm, high, 20)
    with sm.begin() as session:
        session.execute(sa.text("UPDATE usage_grant_balances SET remaining = remaining + 1"))
    owner_of = {low_grant: low, high_grant: high}
    first, second = sorted([low_grant, high_grant])  # the order reconcile walks the grants in
    holds = threading.Event()
    go = threading.Event()
    reserved = uuid.uuid4()

    def reserver() -> None:
        with sm.begin() as session:
            ledger = UsageLedger(session)
            ledger._lock_owners([low])
            ledger._locked_balance(second)
            holds.set()
            assert go.wait(30)
            ledger.reserve(
                job_id=reserved,
                actor_user_id=owner_of[second],
                action=ACTION,
                payers=[*own_chain(owner_of[second]), *own_chain(owner_of[first])],
                estimate_low=0,
                estimate_high=5,
                estimator_version=ESTIMATOR_VERSION,
                rate_version=RATE_VERSION,
                teacher_member_id=None,
                expires_at=NOW + timedelta(hours=1),
                now=NOW,
            )

    def reconciler() -> list[tuple[uuid.UUID, int, int]]:
        assert holds.wait(30)
        return reconcile(sm)

    reserving = _Paused(reserver)
    reconciling = _Paused(reconciler)
    assert holds.wait(30)
    _wait_until_a_backend_waits_on_a_lock(sm)  # reconcile is queued behind the reserver
    go.set()
    reserving.join()
    reconciling.join()
    assert reserving.error is None
    assert reconciling.error is None
    assert sorted(reconciling.result or []) == sorted([(first, 21, 20), (second, 21, 20)])  # type: ignore[arg-type]
    assert job(sm, reserved).reserved == 5
    assert balance(sm, second) == (20, 5)  # the reserve's hold survived the reconcile
    assert reconcile(sm) == []


def test_reconcile_counts_the_entries_the_ledger_wrote_for_each_kind(
    sm: sessionmaker[Session],
) -> None:
    """The scenario really did exercise every entry kind the formulas must cover."""
    _busy_ledger(sm)
    _jobless_debts(sm)
    kinds = {e.kind for e in entries(sm)}
    assert kinds == set(UsageEntryKind)
