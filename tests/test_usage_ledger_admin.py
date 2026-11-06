"""UsageLedger grant expiry, claw-back, adjustments and debt forgiveness (spec §5.7-§5.8, §6)."""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from lemely.db.models.usage import GrantKind, UsageEntryKind, UsageGrant, UsageJobStatus
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
    grant_row,
    job,
    own_chain,
    reserve,
    usage_database,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture(scope="module")
def usage_db() -> Iterator[sessionmaker[Session]]:
    with usage_database() as factory:
        yield factory


@pytest.fixture
def sm(usage_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(usage_db)


def expire_grants(factory: sessionmaker[Session], at: datetime) -> int:
    with factory.begin() as session:
        return UsageLedger(session).expire_grants(now=at)


# ---------------------------------------------------------------------------
# expire_grants
# ---------------------------------------------------------------------------


def test_expire_grants_expires_only_grants_past_expiry(sm: sessionmaker[Session]) -> None:
    owner = add_user(sm)
    old = grant(sm, owner, 10, expires_at=NOW + timedelta(minutes=1))
    live = grant(sm, owner, 10, expires_at=NOW + timedelta(days=1))
    forever = grant(sm, owner, 10, kind=GrantKind.credit_pack, visible=True)
    assert expire_grants(sm, NOW + timedelta(minutes=2)) == 1
    assert balance(sm, old) == (0, 0)
    assert balance(sm, live) == (10, 0)
    assert balance(sm, forever) == (10, 0)
    [entry] = entries(sm, grant_id=old, kind=UsageEntryKind.expire)
    assert entry.units == -10
    assert expire_grants(sm, NOW + timedelta(minutes=3)) == 0


def test_a_grant_expiring_while_held_expires_only_the_unheld_part(
    sm: sessionmaker[Session],
) -> None:
    owner = add_user(sm)
    gid = grant(sm, owner, 10, expires_at=NOW + timedelta(minutes=1))
    job_id = reserve(sm, own_chain(owner), 4)
    assert expire_grants(sm, NOW + timedelta(minutes=2)) == 1
    assert balance(sm, gid) == (4, 4)
    with sm.begin() as session:
        UsageLedger(session).release(job_id, now=NOW + timedelta(minutes=3))
    assert balance(sm, gid) == (4, 0)
    # The released units are past expiry: unusable now, and the next sweep takes them.
    with sm() as session:
        assert UsageLedger(session).available(own_chain(owner), now=NOW + timedelta(minutes=3)) == 0
    assert expire_grants(sm, NOW + timedelta(minutes=4)) == 1
    assert balance(sm, gid) == (0, 0)
    assert [e.units for e in entries(sm, grant_id=gid, kind=UsageEntryKind.expire)] == [-6, -4]


# ---------------------------------------------------------------------------
# claw_back_grant
# ---------------------------------------------------------------------------


def test_claw_back_removes_unspent_units_and_closes_the_grant(sm: sessionmaker[Session]) -> None:
    owner = add_user(sm)
    pack = grant(sm, owner, 50, kind=GrantKind.credit_pack, visible=True)
    reserve(sm, own_chain(owner), 15)
    with sm.begin() as session:
        assert UsageLedger(session).claw_back_grant(pack, reason="refund #12", now=NOW) == 35
    assert balance(sm, pack) == (15, 15)
    assert grant_row(sm, pack).expires_at == NOW
    [entry] = entries(sm, grant_id=pack, kind=UsageEntryKind.refund)
    assert (entry.units, entry.reason) == (-35, "refund #12")
    with sm.begin() as session:
        assert UsageLedger(session).claw_back_grant(pack, reason="again", now=NOW) == 0
    with pytest.raises(LookupError), sm.begin() as session:
        UsageLedger(session).claw_back_grant(uuid.uuid4(), reason="x", now=NOW)


# ---------------------------------------------------------------------------
# adjust
# ---------------------------------------------------------------------------


def test_positive_adjust_issues_a_visible_grant_that_repays_debt(
    sm: sessionmaker[Session],
) -> None:
    owner = add_user(sm)
    add_debt(sm, owner, 4)
    with sm.begin() as session:
        UsageLedger(session).adjust(
            owner_user_id=owner, units=10, reason="goodwill", idempotency_key="adj:1", now=NOW
        )
    [entry] = entries(sm, kind=UsageEntryKind.grant)
    assert (entry.units, entry.reason) == (10, "goodwill")
    assert entry.grant_id is not None
    adjustment = grant_row(sm, entry.grant_id)
    assert (adjustment.kind, adjustment.visible) == (GrantKind.adjustment, True)
    assert balance(sm, entry.grant_id) == (6, 0)
    assert debts(sm, owner)[0].outstanding == 0


def test_negative_adjust_debits_own_grants_then_records_debt_never_a_seat(
    sm: sessionmaker[Session],
) -> None:
    owner = add_user(sm)
    seat = grant(sm, owner, 100, kind=GrantKind.seat_allowance, teacher_member_id=uuid.uuid4())
    allowance = grant(sm, owner, 5)
    credits = grant(sm, owner, 20, kind=GrantKind.credit_pack, visible=True)
    with sm.begin() as session:
        UsageLedger(session).adjust(
            owner_user_id=owner, units=-8, reason="abuse", idempotency_key="adj:2", now=NOW
        )
    assert balance(sm, allowance) == (0, 0)
    assert balance(sm, credits) == (17, 0)
    assert balance(sm, seat) == (100, 0)
    with sm.begin() as session:  # the same key again is a no-op
        UsageLedger(session).adjust(
            owner_user_id=owner, units=-8, reason="abuse", idempotency_key="adj:2", now=NOW
        )
    assert balance(sm, credits) == (17, 0)
    # A debit the balance cannot cover leaves the rest as debt on the owner (§6).
    with sm.begin() as session:
        UsageLedger(session).adjust(
            owner_user_id=owner, units=-25, reason="too much", idempotency_key="adj:3", now=NOW
        )
    assert balance(sm, credits) == (0, 0)
    assert balance(sm, seat) == (100, 0)
    [debt] = debts(sm, owner)
    assert (debt.units, debt.outstanding, debt.job_id) == (8, 8, None)
    [debt_entry] = entries(sm, kind=UsageEntryKind.debt)
    assert (debt_entry.units, debt_entry.reason, debt_entry.grant_id) == (-8, "too much", None)
    with sm.begin() as session:  # idempotent even when the debit was all or partly debt
        UsageLedger(session).adjust(
            owner_user_id=owner, units=-25, reason="too much", idempotency_key="adj:3", now=NOW
        )
    assert len(debts(sm, owner)) == 1
    empty = add_user(sm)
    with sm.begin() as session:
        UsageLedger(session).adjust(
            owner_user_id=empty, units=-300, reason="seed debt", idempotency_key="adj:5", now=NOW
        )
    with sm() as session:
        assert UsageLedger(session).has_debt(empty)
    with pytest.raises(ValueError, match="must not be 0"), sm.begin() as session:
        UsageLedger(session).adjust(
            owner_user_id=owner, units=0, reason="zero", idempotency_key="adj:4", now=NOW
        )


# ---------------------------------------------------------------------------
# forgive_debt
# ---------------------------------------------------------------------------


def test_forgive_debt_oldest_first_partial_then_all(sm: sessionmaker[Session]) -> None:
    owner = add_user(sm)
    older = add_debt(sm, owner, 10)
    newer = add_debt(sm, owner, 10)
    with sm.begin() as session:
        assert UsageLedger(session).forgive_debt(owner, units=12, reason="support", now=NOW) == 12
    assert [(d.id, d.outstanding) for d in debts(sm, owner)] == [(older, 0), (newer, 8)]
    with sm.begin() as session:
        assert UsageLedger(session).forgive_debt(owner, units=None, reason="close", now=NOW) == 8
    with sm() as session:
        assert not UsageLedger(session).has_debt(owner)
    forgiven = entries(sm, kind=UsageEntryKind.adjust)
    assert sorted((e.debt_id == older, e.units, e.reason) for e in forgiven) == [
        (False, 2, "support"),
        (False, 8, "close"),
        (True, 10, "support"),
    ]
    with pytest.raises(ValueError, match="units"), sm.begin() as session:
        UsageLedger(session).forgive_debt(owner, units=0, reason="x", now=NOW)


def test_expire_grants_and_reserve_over_the_same_owners_do_not_deadlock(
    sm: sessionmaker[Session],
) -> None:
    """The sweep expires B's grant before A's; a reserve locks A before B.

    Without one sorted pre-lock over every owner involved, ``expire_grants``
    holds B while waiting for A, and the reserve holds A while waiting for B.
    """
    low, high = sorted([add_user(sm), add_user(sm)])
    high_grant = grant(sm, high, 100, expires_at=NOW + timedelta(minutes=5))  # expired first
    low_grant = grant(sm, low, 100, expires_at=NOW + timedelta(minutes=8))
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
        return expire_grants(sm, NOW + timedelta(minutes=10))

    reserving = _Paused(reserver)
    sweeping = _Paused(sweeper)
    assert holds_low.wait(30)
    _wait_until_a_backend_waits_on_a_lock(sm)  # the sweep is queued behind the reserver
    go.set()
    reserving.join()
    sweeping.join()
    assert reserving.error is None
    assert sweeping.error is None
    assert sweeping.result == 2
    assert job(sm, reserved).status is UsageJobStatus.open
    assert balance(sm, high_grant) == (0, 0)
    assert balance(sm, low_grant) == (5, 5)  # the reserve's hold survived the sweep


# ---------------------------------------------------------------------------
# validation leaves nothing half-written
# ---------------------------------------------------------------------------


def test_claw_back_of_an_unknown_grant_stages_nothing(sm: sessionmaker[Session]) -> None:
    """Guard: the lookup fails before any entry or grant change is staged."""
    with sm() as session:
        with pytest.raises(LookupError):
            UsageLedger(session).claw_back_grant(uuid.uuid4(), reason="x", now=NOW)
        assert not session.new
        assert not session.dirty


def test_adjust_of_zero_stages_nothing(sm: sessionmaker[Session]) -> None:
    """Guard: the zero check runs before any lock, entry or debt is staged."""
    owner = add_user(sm)
    grant(sm, owner, 5)
    with sm() as session:
        with pytest.raises(ValueError, match="must not be 0"):
            UsageLedger(session).adjust(
                owner_user_id=owner, units=0, reason="zero", idempotency_key="adj:z", now=NOW
            )
        assert not session.new
        assert not session.dirty


def test_forgive_debt_validates_before_staging_anything(sm: sessionmaker[Session]) -> None:
    """Guard: a bad ``units`` raises before any forgiveness entry is staged."""
    owner = add_user(sm)
    add_debt(sm, owner, 5)
    with sm() as session:
        with pytest.raises(ValueError, match="units"):
            UsageLedger(session).forgive_debt(owner, units=-1, reason="x", now=NOW)
        assert not session.new
        assert not session.dirty
    assert debts(sm, owner)[0].outstanding == 5


def test_a_negative_adjust_that_records_debt_does_not_take_a_seat_or_leave_a_partial_plan(
    sm: sessionmaker[Session],
) -> None:
    """Guard: the debit is planned in full first; allowance, credits and debt land together."""
    owner = add_user(sm)
    allowance = grant(sm, owner, 3)
    credits = grant(sm, owner, 2, kind=GrantKind.credit_pack, visible=True)
    with sm.begin() as session:
        UsageLedger(session).adjust(
            owner_user_id=owner, units=-10, reason="abuse", idempotency_key="adj:p", now=NOW
        )
    assert balance(sm, allowance) == (0, 0)
    assert balance(sm, credits) == (0, 0)
    [debt] = debts(sm, owner)
    assert (debt.units, debt.outstanding) == (5, 5)
    kinds = sorted((e.kind.value, e.units) for e in entries(sm, reason="abuse"))
    assert kinds == [("adjust", -3), ("adjust", -2), ("debt", -5)]


# ---------------------------------------------------------------------------
# settle: a negative cost is refused before it is quantized
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cost", ["-0.0000001", "-0.000001", "-1"])
def test_settle_refuses_a_negative_actual_cost_even_one_that_would_round_to_zero(
    sm: sessionmaker[Session], cost: str
) -> None:
    add_rate(sm)
    owner = add_user(sm)
    gid = grant(sm, owner, 100)
    job_id = reserve(sm, own_chain(owner), 10)
    with pytest.raises(ValueError, match="actual_cost_usd"), sm.begin() as session:
        UsageLedger(session).settle(job_id, actual_cost_usd=Decimal(cost), now=NOW)
    assert job(sm, job_id).status is UsageJobStatus.open
    assert balance(sm, gid) == (100, 10)


# ---------------------------------------------------------------------------
# money safety: units held past a claw-back or an expiry
# ---------------------------------------------------------------------------


def test_clawed_back_held_units_are_not_spendable_once_released_and_expire_next(
    sm: sessionmaker[Session],
) -> None:
    owner = add_user(sm)
    pack = grant(sm, owner, 50, kind=GrantKind.credit_pack, visible=True)
    job_id = reserve(sm, own_chain(owner), 15)
    with sm.begin() as session:
        assert UsageLedger(session).claw_back_grant(pack, reason="refund", now=NOW) == 35
    later = NOW + timedelta(minutes=1)
    with sm.begin() as session:
        UsageLedger(session).release(job_id, now=later)
    assert balance(sm, pack) == (15, 0)
    with sm() as session:
        assert UsageLedger(session).available(own_chain(owner), now=later) == 0
    assert expire_grants(sm, later) == 1
    assert balance(sm, pack) == (0, 0)
    assert [e.units for e in entries(sm, grant_id=pack, kind=UsageEntryKind.expire)] == [-15]


def test_claw_back_closes_a_grant_that_starts_at_now_one_microsecond_later(
    sm: sessionmaker[Session],
) -> None:
    owner = add_user(sm)
    pack = grant(sm, owner, 50, kind=GrantKind.credit_pack, visible=True, effective_at=NOW)
    job_id = reserve(sm, own_chain(owner), 15)
    with sm.begin() as session:
        assert UsageLedger(session).claw_back_grant(pack, reason="refund", now=NOW) == 35
    assert grant_row(sm, pack).expires_at == NOW + timedelta(microseconds=1)
    later = NOW + timedelta(minutes=1)
    with sm.begin() as session:
        UsageLedger(session).release(job_id, now=later)
    with sm() as session:
        assert UsageLedger(session).available(own_chain(owner), now=later) == 0
    assert expire_grants(sm, later) == 1
    assert balance(sm, pack) == (0, 0)


def test_claw_back_keeps_an_earlier_expiry(sm: sessionmaker[Session]) -> None:
    owner = add_user(sm)
    soon = NOW + timedelta(minutes=1)
    pack = grant(sm, owner, 10, kind=GrantKind.credit_pack, visible=True, expires_at=soon)
    with sm.begin() as session:
        assert UsageLedger(session).claw_back_grant(pack, reason="refund", now=NOW) == 10
    assert grant_row(sm, pack).expires_at == NOW  # closed now, not left at the later date
    other = grant(sm, owner, 10, kind=GrantKind.credit_pack, visible=True, expires_at=NOW)
    with sm.begin() as session:
        UsageLedger(session).claw_back_grant(other, reason="refund", now=NOW + timedelta(days=1))
    assert grant_row(sm, other).expires_at == NOW  # an expiry already passed is kept


def test_a_grant_expiring_under_a_hold_settles_below_the_hold(sm: sessionmaker[Session]) -> None:
    add_rate(sm)
    owner = add_user(sm)
    held = grant(sm, owner, 10, expires_at=NOW + timedelta(minutes=1))
    credits = grant(sm, owner, 20, kind=GrantKind.credit_pack, visible=True)
    job_id = reserve(sm, own_chain(owner), 10)
    assert balance(sm, held) == (10, 10)
    with sm.begin() as session:
        UsageLedger(session).settle(
            job_id, actual_cost_usd=Decimal("0.004"), now=NOW + timedelta(minutes=5)
        )
    assert balance(sm, held) == (6, 0)  # charged 4 on the expired grant; 6 left to expire
    assert balance(sm, credits) == (20, 0)
    assert expire_grants(sm, NOW + timedelta(minutes=6)) == 1
    assert balance(sm, held) == (0, 0)


def test_a_grant_expiring_under_a_hold_settles_above_the_hold_from_usable_grants_only(
    sm: sessionmaker[Session],
) -> None:
    """The excess draws on a usable grant, never on the expired grant's unheld rest."""
    add_rate(sm)
    owner = add_user(sm)
    held = grant(sm, owner, 12, expires_at=NOW + timedelta(minutes=1))
    credits = grant(sm, owner, 20, kind=GrantKind.credit_pack, visible=True)
    job_id = reserve(sm, own_chain(owner), 10)
    assert balance(sm, held) == (12, 10)
    with sm.begin() as session:
        UsageLedger(session).settle(
            job_id, actual_cost_usd=Decimal("0.014"), now=NOW + timedelta(minutes=5)
        )
    assert balance(sm, held) == (2, 0)  # the held 10 charged; the unheld 2 stay unspent
    assert balance(sm, credits) == (16, 0)  # the other 4 came from the usable grant
    assert job(sm, job_id).debt_created == 0


# ---------------------------------------------------------------------------
# adjust idempotency: one namespace for credits and debits
# ---------------------------------------------------------------------------


def _adjust(sm: sessionmaker[Session], owner: uuid.UUID, units: int, key: str, reason: str) -> None:
    with sm.begin() as session:
        UsageLedger(session).adjust(
            owner_user_id=owner, units=units, reason=reason, idempotency_key=key, now=NOW
        )


def test_negative_adjust_replay_that_differs_warns_and_changes_nothing(
    sm: sessionmaker[Session], caplog: pytest.LogCaptureFixture
) -> None:
    owner = add_user(sm)
    credits = grant(sm, owner, 20, kind=GrantKind.credit_pack, visible=True)
    _adjust(sm, owner, -8, "adj:r", "abuse")
    with caplog.at_level(logging.WARNING, logger="lemely.db.usage_ledger_repo"):
        _adjust(sm, owner, -8, "adj:r", "abuse")  # identical replay: silent
        assert not caplog.records
        _adjust(sm, owner, -9, "adj:r", "abuse")
        _adjust(sm, owner, -8, "adj:r", "other reason")
    assert len(caplog.records) == 2
    assert all("adj:r" in r.getMessage() for r in caplog.records)
    assert balance(sm, credits) == (12, 0)
    assert len(entries(sm, kind=UsageEntryKind.adjust)) == 1


def test_a_key_used_for_a_credit_cannot_be_reused_for_a_debit_nor_the_reverse(
    sm: sessionmaker[Session], caplog: pytest.LogCaptureFixture
) -> None:
    owner = add_user(sm)
    _adjust(sm, owner, 10, "adj:c", "goodwill")
    [credit_entry] = entries(sm, kind=UsageEntryKind.grant)
    assert credit_entry.grant_id is not None
    with caplog.at_level(logging.WARNING, logger="lemely.db.usage_ledger_repo"):
        _adjust(sm, owner, -10, "adj:c", "oops")  # debit under a credit's key
    assert balance(sm, credit_entry.grant_id) == (10, 0)
    assert not debts(sm, owner)
    assert len(caplog.records) == 1
    caplog.clear()
    _adjust(sm, owner, -4, "adj:d", "abuse")  # debits 4 from that grant
    assert balance(sm, credit_entry.grant_id) == (6, 0)
    with caplog.at_level(logging.WARNING, logger="lemely.db.usage_ledger_repo"):
        _adjust(sm, owner, 4, "adj:d", "oops")  # credit under a debit's key
    assert len(caplog.records) == 1
    assert balance(sm, credit_entry.grant_id) == (6, 0)
    assert len(entries(sm, kind=UsageEntryKind.grant)) == 1
    # A debit that was all debt also blocks a credit under its key.
    empty = add_user(sm)
    _adjust(sm, empty, -5, "adj:e", "seed")
    _adjust(sm, empty, 5, "adj:e", "oops")
    assert [d.outstanding for d in debts(sm, empty)] == [5]
    assert not entries(sm, kind=UsageEntryKind.grant, reason="oops")


def test_a_credit_replay_with_a_different_reason_only_warns_and_changes_nothing(
    sm: sessionmaker[Session], caplog: pytest.LogCaptureFixture
) -> None:
    owner = add_user(sm)
    _adjust(sm, owner, 10, "adj:r", "goodwill")
    with caplog.at_level(logging.WARNING, logger="lemely.db.usage_ledger_repo"):
        _adjust(sm, owner, 10, "adj:r", "goodwill")  # identical replay: silent
        assert not caplog.records
        _adjust(sm, owner, 10, "adj:r", "other reason")
    assert len(caplog.records) == 1
    assert "adj:r" in caplog.records[0].getMessage()
    assert "other reason" in caplog.records[0].getMessage()
    [stored] = entries(sm, kind=UsageEntryKind.grant)
    assert stored.reason == "goodwill"


def test_a_grant_under_a_key_does_not_make_a_debit_under_that_key_a_replay(
    sm: sessionmaker[Session],
) -> None:
    """Guard: only an ``adjustment`` grant is a positive adjust's record."""
    owner = add_user(sm)
    pack = grant(sm, owner, 20, kind=GrantKind.credit_pack, visible=True, key="shared-key")
    _adjust(sm, owner, -5, "shared-key", "abuse")
    assert balance(sm, pack) == (15, 0)
    assert len(entries(sm, kind=UsageEntryKind.adjust)) == 1


# ---------------------------------------------------------------------------
# expire_grants re-checks expiry under the lock
# ---------------------------------------------------------------------------


def test_expire_grants_skips_a_grant_re_dated_between_the_candidate_read_and_the_lock(
    sm: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = add_user(sm)
    gid = grant(sm, owner, 10, expires_at=NOW + timedelta(minutes=1))
    real_lock = UsageLedger._lock_owners

    def lock_after_a_rival_extends(self: UsageLedger, owner_ids: Sequence[uuid.UUID]) -> None:
        monkeypatch.setattr(UsageLedger, "_lock_owners", real_lock)
        with sm.begin() as rival:
            row = rival.get(UsageGrant, gid)
            assert row is not None
            row.expires_at = NOW + timedelta(days=30)
        real_lock(self, owner_ids)

    monkeypatch.setattr(UsageLedger, "_lock_owners", lock_after_a_rival_extends)
    assert expire_grants(sm, NOW + timedelta(minutes=2)) == 0
    assert balance(sm, gid) == (10, 0)
    assert not entries(sm, grant_id=gid, kind=UsageEntryKind.expire)
