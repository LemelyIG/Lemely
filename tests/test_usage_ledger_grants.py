"""UsageLedger grants, debt repayment, availability and the meter (spec §4.5, §5.6, §5.8)."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

from lemely.core.usage_types import GrantScope, Payer
from lemely.db.models.enums import Role
from lemely.db.models.usage import GrantKind, UsageEntryKind
from lemely.db.usage_ledger_repo import UsageLedger
from tests.usage_db import (
    NOW,
    add_debt,
    add_seat_member,
    add_user,
    balance,
    debts,
    emptied_after,
    entries,
    grant,
    grant_row,
    own_chain,
    usage_database,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from datetime import datetime

    from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture(scope="module")
def usage_db() -> Iterator[sessionmaker[Session]]:
    with usage_database() as factory:
        yield factory


@pytest.fixture
def sm(usage_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(usage_db)


# ---------------------------------------------------------------------------
# issue_grant
# ---------------------------------------------------------------------------


def test_issue_grant_writes_grant_balance_and_grant_entry(sm: sessionmaker[Session]) -> None:
    owner = add_user(sm)
    gid = grant(sm, owner, 120, kind=GrantKind.credit_pack, visible=True, key="pack:1")
    row = grant_row(sm, gid)
    assert (row.kind, row.priority, row.units, row.visible) == (
        GrantKind.credit_pack,
        50,
        120,
        True,
    )
    assert balance(sm, gid) == (120, 0)
    [entry] = entries(sm, grant_id=gid)
    assert (entry.kind, entry.units, entry.idempotency_key) == (UsageEntryKind.grant, 120, "pack:1")


def test_issue_grant_is_idempotent_per_owner_and_key(sm: sessionmaker[Session]) -> None:
    owner, other = add_user(sm), add_user(sm)
    first = grant(sm, owner, 50, key="period:2026-11")
    again = grant(sm, owner, 999, key="period:2026-11")
    elsewhere = grant(sm, other, 50, key="period:2026-11")
    assert again == first
    assert elsewhere != first
    assert balance(sm, first) == (50, 0)
    assert len(entries(sm, grant_id=first)) == 1


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"units": 0}, "units must be > 0"),
        ({"kind": GrantKind.seat_allowance}, "teacher_member_id"),
        ({"teacher_member_id": uuid.uuid4()}, "teacher_member_id"),
        ({"visible": True}, "never visible"),
    ],
)
def test_issue_grant_validates(
    sm: sessionmaker[Session], kwargs: dict[str, object], message: str
) -> None:
    owner = add_user(sm)
    values: dict[str, object] = {
        "owner_user_id": owner,
        "kind": GrantKind.period_allowance,
        "units": 10,
        "idempotency_key": "k",
        "expires_at": None,
        "visible": False,
    }
    values.update(kwargs)
    with pytest.raises(ValueError, match=message), sm.begin() as session:
        UsageLedger(session).issue_grant(**values)  # type: ignore[arg-type]


def test_new_grant_repays_debts_oldest_first(sm: sessionmaker[Session]) -> None:
    owner = add_user(sm)
    older = add_debt(sm, owner, 30)
    newer = add_debt(sm, owner, 50)
    gid = grant(sm, owner, 60, kind=GrantKind.credit_pack, visible=True)
    assert balance(sm, gid) == (0, 0)
    assert [(d.id, d.outstanding) for d in debts(sm, owner)] == [(older, 0), (newer, 20)]
    repays = entries(sm, grant_id=gid, kind=UsageEntryKind.debt_repay)
    assert {e.debt_id: e.units for e in repays} == {older: -30, newer: -30}


def test_seat_allowance_does_not_repay_the_students_debt(sm: sessionmaker[Session]) -> None:
    student = add_user(sm)
    add_debt(sm, student, 30)
    member = add_seat_member(sm, student)
    seat = grant(sm, student, 40, kind=GrantKind.seat_allowance, teacher_member_id=member)
    assert balance(sm, seat) == (40, 0)
    assert debts(sm, student)[0].outstanding == 30


def test_has_debt(sm: sessionmaker[Session]) -> None:
    owner = add_user(sm)
    with sm() as session:
        assert not UsageLedger(session).has_debt(owner)
    add_debt(sm, owner, 5)
    with sm() as session:
        assert UsageLedger(session).has_debt(owner)
    grant(sm, owner, 5, kind=GrantKind.credit_pack, visible=True)
    with sm() as session:
        assert not UsageLedger(session).has_debt(owner)


# ---------------------------------------------------------------------------
# available
# ---------------------------------------------------------------------------


def test_available_filters_by_scope_and_validity(sm: sessionmaker[Session]) -> None:
    owner = add_user(sm)
    member = add_seat_member(sm, owner)
    grant(sm, owner, 10)  # hidden allowance
    grant(sm, owner, 20, kind=GrantKind.credit_pack, visible=True)
    grant(sm, owner, 40, kind=GrantKind.seat_allowance, teacher_member_id=member)
    grant(sm, owner, 80, expires_at=NOW)  # expired at NOW
    grant(sm, owner, 160, effective_at=NOW + timedelta(hours=1))  # not yet effective
    seat = Payer(owner_user_id=owner, scope=GrantScope.SEAT, teacher_member_id=member)
    other_seat = Payer(owner_user_id=owner, scope=GrantScope.SEAT, teacher_member_id=uuid.uuid4())
    with sm() as session:
        ledger = UsageLedger(session)
        assert ledger.available([own_chain(owner)[0]], now=NOW) == 10
        assert ledger.available([own_chain(owner)[1]], now=NOW) == 20
        assert ledger.available(own_chain(owner), now=NOW) == 30
        assert ledger.available([seat], now=NOW) == 40
        assert ledger.available([other_seat], now=NOW) == 0
        assert ledger.available([seat, *own_chain(owner)], now=NOW) == 70


def test_available_skips_an_indebted_payer_but_not_a_debt_exempt_seat(
    sm: sessionmaker[Session],
) -> None:
    student = add_user(sm)
    member = add_seat_member(sm, student)
    grant(sm, student, 25, kind=GrantKind.seat_allowance, teacher_member_id=member)
    grant(sm, student, 10)
    add_debt(sm, student, 3)  # added after the grants, so nothing repays it
    seat = Payer(
        owner_user_id=student, scope=GrantScope.SEAT, teacher_member_id=member, debt_exempt=True
    )
    with sm() as session:
        assert UsageLedger(session).available([seat, *own_chain(student)], now=NOW) == 25


def test_available_honours_a_cap_shared_by_payers_with_the_same_member(
    sm: sessionmaker[Session],
) -> None:
    teacher, member = add_user(sm, Role.teacher), uuid.uuid4()
    grant(sm, teacher, 50)
    grant(sm, teacher, 50, kind=GrantKind.credit_pack, visible=True)
    capped = [
        Payer(
            owner_user_id=teacher,
            scope=GrantScope.ALLOWANCE,
            teacher_member_id=member,
            cap_units=30,
        ),
        Payer(
            owner_user_id=teacher,
            scope=GrantScope.CREDITS,
            teacher_member_id=member,
            cap_units=30,
        ),
    ]
    with sm() as session:
        assert UsageLedger(session).available(capped, now=NOW) == 30


# ---------------------------------------------------------------------------
# meter_fraction
# ---------------------------------------------------------------------------


def test_meter_fraction_sums_current_period_allowances(sm: sessionmaker[Session]) -> None:
    owner = add_user(sm)
    with sm() as session:
        assert UsageLedger(session).meter_fraction(owner, teacher_member_id=None, now=NOW) is None
    add_debt(sm, owner, 30)
    grant(sm, owner, 100, expires_at=NOW + timedelta(days=10))  # repays 30
    grant(sm, owner, 100, expires_at=NOW + timedelta(days=10))  # an upgrade's top-up
    grant(
        sm, owner, 100, expires_at=NOW - timedelta(minutes=1), effective_at=NOW - timedelta(days=40)
    )
    with sm() as session:
        assert UsageLedger(session).meter_fraction(
            owner, teacher_member_id=None, now=NOW
        ) == pytest.approx(0.15)


def test_meter_fraction_reads_the_seat_grant_for_in_scope_work(sm: sessionmaker[Session]) -> None:
    student = add_user(sm)
    member = add_seat_member(sm, student)
    grant(sm, student, 40, kind=GrantKind.seat_allowance, teacher_member_id=member)
    grant(sm, student, 100)
    with sm() as session:
        ledger = UsageLedger(session)
        assert ledger.meter_fraction(student, teacher_member_id=member, now=NOW) == 0.0
        assert ledger.meter_fraction(student, teacher_member_id=uuid.uuid4(), now=NOW) is None


# ---------------------------------------------------------------------------
# extend_grant_expiry
# ---------------------------------------------------------------------------


def _extend_expiry(
    factory: sessionmaker[Session], grant_id: uuid.UUID, expires_at: datetime
) -> datetime | None:
    with factory.begin() as session:
        return (
            UsageLedger(session)
            .extend_grant_expiry(grant_id, expires_at=expires_at, now=NOW)
            .expires_at
        )


def test_extend_grant_expiry_moves_only_the_expiry_and_keeps_the_leftover_usable(
    sm: sessionmaker[Session],
) -> None:
    owner = add_user(sm)
    soon = NOW + timedelta(hours=1)
    later = NOW + timedelta(days=3)
    gid = grant(sm, owner, 100, expires_at=soon)
    before = (balance(sm, gid), [e.id for e in entries(sm, grant_id=gid)])
    assert _extend_expiry(sm, gid, later) == later
    after = (balance(sm, gid), [e.id for e in entries(sm, grant_id=gid)])
    assert after == before  # no entry, no balance change
    with sm() as session:
        ledger = UsageLedger(session)
        assert ledger.available(own_chain(owner), now=soon + timedelta(hours=1)) == 100
        assert ledger.available(own_chain(owner), now=later) == 0  # the new expiry still binds


def test_extend_grant_expiry_never_moves_an_expiry_earlier(sm: sessionmaker[Session]) -> None:
    owner = add_user(sm)
    far = NOW + timedelta(days=9)
    gid = grant(sm, owner, 100, expires_at=far)
    assert _extend_expiry(sm, gid, NOW + timedelta(days=3)) == far


def test_extend_grant_expiry_is_idempotent(sm: sessionmaker[Session]) -> None:
    owner = add_user(sm)
    later = NOW + timedelta(days=3)
    gid = grant(sm, owner, 100, expires_at=NOW + timedelta(hours=1))
    assert _extend_expiry(sm, gid, later) == later
    assert _extend_expiry(sm, gid, later) == later
    assert len(entries(sm, grant_id=gid)) == 1


def test_extend_grant_expiry_leaves_a_grant_that_never_expires_alone(
    sm: sessionmaker[Session],
) -> None:
    owner = add_user(sm)
    gid = grant(sm, owner, 100, expires_at=None)
    assert _extend_expiry(sm, gid, NOW + timedelta(days=3)) is None


def test_extend_grant_expiry_refuses_a_grant_that_already_expired(
    sm: sessionmaker[Session],
) -> None:
    owner = add_user(sm)
    gone = NOW - timedelta(minutes=1)
    gid = grant(sm, owner, 100, expires_at=gone, effective_at=NOW - timedelta(days=30))
    with pytest.raises(ValueError, match="already expired"), sm.begin() as session:
        UsageLedger(session).extend_grant_expiry(gid, expires_at=NOW + timedelta(days=3), now=NOW)
    assert grant_row(sm, gid).expires_at == gone


def test_extend_grant_expiry_refuses_an_expiry_that_is_not_in_the_future(
    sm: sessionmaker[Session],
) -> None:
    owner = add_user(sm)
    gid = grant(sm, owner, 100, expires_at=NOW + timedelta(hours=1))
    with pytest.raises(ValueError, match="after now"), sm.begin() as session:
        UsageLedger(session).extend_grant_expiry(gid, expires_at=NOW, now=NOW)


def test_extend_grant_expiry_of_an_unknown_grant_raises(sm: sessionmaker[Session]) -> None:
    with pytest.raises(LookupError), sm.begin() as session:
        UsageLedger(session).extend_grant_expiry(
            uuid.uuid4(), expires_at=NOW + timedelta(days=3), now=NOW
        )
