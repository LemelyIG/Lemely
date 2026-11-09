"""Per-member usage for the team screens: cap use and seat meter (spec §2.2, §2.3, §5.6)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest

from lemely.db.models.enums import Role
from lemely.db.models.team import CapPeriod
from lemely.db.models.usage import GrantKind, UsageEntryKind
from lemely.db.teacher_team_repo import TeacherTeamService, month_start
from tests.team_db import (
    NOW,
    add_assistant,
    add_entry,
    add_grant,
    add_seat,
    add_user,
    emptied_after,
    set_remaining,
    team_database,
)

if TYPE_CHECKING:
    import uuid
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture(scope="module")
def team_db() -> Iterator[sessionmaker[Session]]:
    with team_database() as factory:
        yield factory


@pytest.fixture
def sm(team_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(team_db)


def _cap_used(
    sm: sessionmaker[Session],
    teacher: uuid.UUID,
    member_id: uuid.UUID,
    *,
    now: datetime = NOW,
) -> int:
    with sm() as session:
        team = TeacherTeamService(session)
        return team.cap_used(team.owned_member(teacher, member_id, kind=None), now=now)


def _meter(sm: sessionmaker[Session], teacher: uuid.UUID, member_id: uuid.UUID) -> float | None:
    with sm() as session:
        team = TeacherTeamService(session)
        return team.seat_meter_fraction(team.owned_member(teacher, member_id, kind=None), now=NOW)


def test_month_start_is_the_first_instant_of_the_month() -> None:
    assert month_start(NOW) == NOW.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (datetime(2026, 11, 1, tzinfo=UTC), datetime(2026, 11, 1, tzinfo=UTC)),
        (datetime(2026, 11, 30, 23, 59, 59, 999999, tzinfo=UTC), datetime(2026, 11, 1, tzinfo=UTC)),
        (datetime(2026, 12, 1, tzinfo=UTC), datetime(2026, 12, 1, tzinfo=UTC)),
        (datetime(2027, 1, 31, 12, tzinfo=UTC), datetime(2027, 1, 1, tzinfo=UTC)),
        # 01:00 on 1 Dec in UTC+2 is still 23:00 on 30 Nov in UTC: the cap window is UTC.
        (
            datetime(2026, 12, 1, 1, tzinfo=timezone(timedelta(hours=2))),
            datetime(2026, 11, 1, tzinfo=UTC),
        ),
    ],
)
def test_month_start_at_month_and_year_boundaries(now: datetime, expected: datetime) -> None:
    assert month_start(now) == expected
    assert month_start(now).tzinfo is not None


def test_month_start_refuses_a_naive_instant() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        month_start(datetime(2026, 11, 14, 12, 0))


def test_seat_cap_use_counts_teacher_draws_in_the_window_plus_open_holds(
    sm: sessionmaker[Session],
) -> None:
    teacher, student, other_student = add_user(sm, Role.teacher), add_user(sm), add_user(sm)
    seat = add_seat(sm, teacher_id=teacher, student_id=student)
    other_seat = add_seat(sm, teacher_id=teacher, student_id=other_student)
    credits = add_grant(sm, owner_id=teacher, kind=GrantKind.credit_pack, units=1000, at=NOW)
    allowance = add_grant(
        sm,
        owner_id=student,
        kind=GrantKind.seat_allowance,
        units=100,
        at=NOW,
        teacher_member_id=seat,
    )
    for kind, units, at, grant, member in (
        (UsageEntryKind.settle, -40, NOW, credits, seat),  # this month: counts
        (UsageEntryKind.settle, -25, NOW - timedelta(days=30), credits, seat),  # last month
        (UsageEntryKind.hold, 10, NOW, credits, seat),  # held then released: nets to 0
        (UsageEntryKind.release, -10, NOW, credits, seat),
        (UsageEntryKind.hold, 7, NOW, credits, seat),  # still open: counts
        (UsageEntryKind.settle, -100, NOW, credits, other_seat),  # another seat
        (UsageEntryKind.settle, -50, NOW, allowance, seat),  # the student's own grant
    ):
        add_entry(sm, grant_id=grant, member_id=member, kind=kind, units=units, at=at)
    assert _cap_used(sm, teacher, seat) == 47
    with sm.begin() as session:
        TeacherTeamService(session).set_cap(seat, cap_units=500, cap_period=CapPeriod.total)
    assert _cap_used(sm, teacher, seat) == 72  # "total" has no window


def test_month_cap_window_opens_at_the_first_instant_of_the_month(
    sm: sessionmaker[Session],
) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    seat = add_seat(sm, teacher_id=teacher, student_id=student)
    credits = add_grant(sm, owner_id=teacher, kind=GrantKind.credit_pack, units=1000, at=NOW)
    start = month_start(NOW)
    for units, at in (
        (-3, start),  # the very first instant: inside the window
        (-5, start - timedelta(microseconds=1)),  # one tick earlier: last month
        (-11, start + timedelta(days=13, hours=12)),  # mid-month
    ):
        add_entry(
            sm, grant_id=credits, member_id=seat, kind=UsageEntryKind.settle, units=units, at=at
        )
    assert _cap_used(sm, teacher, seat) == 14
    # Read as of December, only November's lines fall out of the window.
    assert _cap_used(sm, teacher, seat, now=datetime(2026, 12, 1, tzinfo=UTC)) == 0
    # Read as of the last instant of November, November's lines are all still in.
    assert _cap_used(sm, teacher, seat, now=datetime(2026, 11, 30, 23, 59, tzinfo=UTC)) == 14


def test_open_holds_count_even_when_placed_before_the_window(sm: sessionmaker[Session]) -> None:
    """A hold has no window, as in ``UsageLedger._cap_used``: it counts until released."""
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    seat = add_seat(sm, teacher_id=teacher, student_id=student)
    credits = add_grant(sm, owner_id=teacher, kind=GrantKind.credit_pack, units=1000, at=NOW)
    add_entry(
        sm,
        grant_id=credits,
        member_id=seat,
        kind=UsageEntryKind.hold,
        units=9,
        at=month_start(NOW) - timedelta(days=3),
    )
    assert _cap_used(sm, teacher, seat) == 9


def test_assistant_cap_use_counts_draws_on_the_leads_balance(sm: sessionmaker[Session]) -> None:
    lead, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    member = add_assistant(sm, teacher_id=lead, assistant_id=helper)
    credits = add_grant(sm, owner_id=lead, kind=GrantKind.credit_pack, units=1000, at=NOW)
    add_entry(sm, grant_id=credits, member_id=member, kind=UsageEntryKind.settle, units=-30, at=NOW)
    add_entry(
        sm,
        grant_id=credits,
        member_id=member,
        kind=UsageEntryKind.settle,
        units=-99,
        at=month_start(NOW) - timedelta(seconds=1),
    )
    assert _cap_used(sm, lead, member) == 30


def test_usage_never_crosses_teachers(sm: sessionmaker[Session]) -> None:
    """A member row only counts draws on its own teacher's grants."""
    lead, other_lead, student = add_user(sm, Role.teacher), add_user(sm, Role.teacher), add_user(sm)
    seat = add_seat(sm, teacher_id=lead, student_id=student)
    foreign = add_grant(sm, owner_id=other_lead, kind=GrantKind.credit_pack, units=1000, at=NOW)
    add_entry(sm, grant_id=foreign, member_id=seat, kind=UsageEntryKind.settle, units=-60, at=NOW)
    assert _cap_used(sm, lead, seat) == 0


def test_no_usage_is_zero(sm: sessionmaker[Session]) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    seat = add_seat(sm, teacher_id=teacher, student_id=student)
    assert _cap_used(sm, teacher, seat) == 0


def test_seat_meter_reads_the_seat_allowance(sm: sessionmaker[Session]) -> None:
    teacher, student, helper = add_user(sm, Role.teacher), add_user(sm), add_user(sm, Role.teacher)
    seat = add_seat(sm, teacher_id=teacher, student_id=student)
    assistant = add_assistant(sm, teacher_id=teacher, assistant_id=helper)
    assert _meter(sm, teacher, seat) is None  # no grant yet
    allowance = add_grant(
        sm,
        owner_id=student,
        kind=GrantKind.seat_allowance,
        units=100,
        at=NOW,
        teacher_member_id=seat,
    )
    set_remaining(sm, allowance, 70)
    assert _meter(sm, teacher, seat) == pytest.approx(0.3)
    assert _meter(sm, teacher, assistant) is None  # assistants have no allowance


def test_seat_meter_ignores_another_seats_allowance(sm: sessionmaker[Session]) -> None:
    teacher, student, other_student = add_user(sm, Role.teacher), add_user(sm), add_user(sm)
    seat = add_seat(sm, teacher_id=teacher, student_id=student)
    other_seat = add_seat(sm, teacher_id=teacher, student_id=other_student)
    other_grant = add_grant(
        sm,
        owner_id=other_student,
        kind=GrantKind.seat_allowance,
        units=100,
        at=NOW,
        teacher_member_id=other_seat,
    )
    set_remaining(sm, other_grant, 0)
    assert _meter(sm, teacher, seat) is None
    assert _meter(sm, teacher, other_seat) == pytest.approx(1.0)
