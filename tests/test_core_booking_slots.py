"""Bookable slots and daylight saving in Africa/Cairo (SPEC §e.1, §e.4 "Slots (F27)"; PLAN T03).

Cairo 2026 (installed tzdata, checked in each test): clocks jump from 00:00 EET to
01:00 EEST at 2026-04-23 22:00Z (Friday 24 April, 00:00-01:00 does not exist) and
fall back from 24:00 EEST to 23:00 EET at 2026-10-29 21:00Z (Thursday 29 October,
23:00-24:00 happens twice).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from lemely.core.booking import (
    ALLOWED_DURATIONS,
    MAX_BOOKING_HORIZON,
    MIN_NOTICE,
    SLOT_STEP,
    AvailabilityRule,
    OverlappingRules,
    bookable,
    bookable_slots,
    normalize_rules,
    occurrences,
)

CAIRO = "Africa/Cairo"
TZ = ZoneInfo(CAIRO)
MON, TUE, WED, THU, FRI, SAT, SUN = range(1, 8)


def _z(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)  # type: ignore[misc]


def _wall(instant: datetime) -> datetime:
    return instant.astimezone(TZ).replace(tzinfo=None)


def _wall_is_ambiguous_or_missing(wall: datetime) -> bool:
    first = wall.replace(tzinfo=TZ, fold=0).astimezone(UTC)
    return first != wall.replace(tzinfo=TZ, fold=1).astimezone(UTC)


def _minutes(value: int) -> timedelta:
    return timedelta(minutes=value)


def _overlaps(slot: tuple[datetime, datetime], interval: tuple[datetime, datetime]) -> bool:
    return slot[0] < interval[1] and interval[0] < slot[1]


def test_dst_end_2026_10_29_thursday_17_is_14z_then_15z() -> None:
    assert datetime(2026, 10, 29, 17, tzinfo=TZ).utcoffset() == timedelta(hours=3)
    assert datetime(2026, 11, 5, 17, tzinfo=TZ).utcoffset() == timedelta(hours=2)
    rule = AvailabilityRule(THU, 17 * 60, 18 * 60)
    window = {"zone": CAIRO, "start": date(2026, 10, 29), "days": 8}
    expected = [
        (_z(2026, 10, 29, 14), _z(2026, 10, 29, 15)),
        (_z(2026, 11, 5, 15), _z(2026, 11, 5, 16)),
    ]
    assert occurrences([rule], **window) == expected
    slots = bookable_slots([rule], **window, duration=_minutes(60), busy=[], now=_z(2026, 10, 20))
    assert slots == expected
    assert [f"{_wall(start):%a %H:%M}" for start, _ in slots] == ["Thu 17:00", "Thu 17:00"]


def test_repeated_hour_offers_no_slot_and_no_duplicate_label() -> None:
    assert _wall_is_ambiguous_or_missing(datetime(2026, 10, 29, 23, 30))
    rule = AvailabilityRule(THU, 22 * 60, 24 * 60)
    window = {"zone": CAIRO, "start": date(2026, 10, 29), "days": 1}
    now = _z(2026, 10, 20)
    # F27: that night the 22:00-24:00 window spans three absolute hours
    assert occurrences([rule], **window) == [(_z(2026, 10, 29, 19), _z(2026, 10, 29, 22))]
    offered = {}
    for minutes in ALLOWED_DURATIONS:
        slots = bookable_slots([rule], **window, duration=_minutes(minutes), busy=[], now=now)
        offered[minutes] = slots
        for start, end in slots:
            assert not _wall_is_ambiguous_or_missing(_wall(start))
            assert not _wall_is_ambiguous_or_missing(_wall(end))
        labels = [f"{_wall(start):%H:%M}" for start, _ in slots]
        assert len(labels) == len(set(labels))
        assert all(f"{_wall(start):%H:%M}" != f"{_wall(end):%H:%M}" for start, end in slots)
    # only 22:00-22:45 ends before the repeated hour; every longer slot touches it
    assert offered == {
        45: [(_z(2026, 10, 29, 19), _z(2026, 10, 29, 19, 45))],
        60: [],
        90: [],
        120: [],
    }
    # a week later the same rule is an ordinary two hours
    ordinary = bookable_slots(
        [rule], zone=CAIRO, start=date(2026, 11, 5), days=1, duration=_minutes(60), busy=[], now=now
    )
    assert [f"{_wall(start):%H:%M}" for start, _ in ordinary] == ["22:00", "22:30", "23:00"]


def test_dst_start_nonexistent_0030_offers_nothing() -> None:
    now = _z(2026, 4, 20)
    window = {"zone": CAIRO, "start": date(2026, 4, 24), "days": 1}
    jump = _z(2026, 4, 23, 22)  # 00:00 EET becomes 01:00 EEST
    assert _wall(jump) == datetime(2026, 4, 24, 1, 0)
    # premise (F27): zoneinfo does not raise for the missing 00:30, it silently shifts it
    shifted = datetime(2026, 4, 24, 0, 30, tzinfo=TZ).astimezone(UTC)
    assert _wall(shifted) == datetime(2026, 4, 24, 1, 30)
    # a rule whose start is missing begins at the first valid instant: the jump
    rule = AvailabilityRule(FRI, 30, 2 * 60)  # 00:30-02:00
    assert occurrences([rule], **window) == [(jump, _z(2026, 4, 23, 23))]
    slots = bookable_slots([rule], **window, duration=_minutes(60), busy=[], now=now)
    assert slots == [(jump, _z(2026, 4, 23, 23))]
    assert all(_wall(start) >= datetime(2026, 4, 24, 1, 0) for start, _ in slots)
    # a rule that lies wholly inside the missing hour offers nothing
    gap_rule = AvailabilityRule(FRI, 0, 45)  # 00:00-00:45
    assert occurrences([gap_rule], **window) == []
    for minutes in ALLOWED_DURATIONS:
        assert (
            bookable_slots([gap_rule], **window, duration=_minutes(minutes), busy=[], now=now) == []
        )
    # the Thursday window that ends at the missing midnight ends at the jump
    thursday = AvailabilityRule(THU, 23 * 60, 24 * 60)
    assert occurrences([thursday], zone=CAIRO, start=date(2026, 4, 23), days=1) == [
        (_z(2026, 4, 23, 21), jump)
    ]


def test_slots_never_overlap_busy_or_leave_rule() -> None:
    rules = [
        AvailabilityRule(MON, 9 * 60, 12 * 60),
        AvailabilityRule(MON, 12 * 60, 13 * 60 + 30),  # adjacent to the one before
        AvailabilityRule(WED, 15 * 60 + 15, 19 * 60),
        AvailabilityRule(SAT, 10 * 60, 11 * 60),
    ]
    window = {"zone": CAIRO, "start": date(2026, 6, 1), "days": 7}  # Monday 1 June (EEST)
    now = _z(2026, 5, 31)
    busy = [
        (_z(2026, 6, 1, 7), _z(2026, 6, 1, 8)),  # Mon 10:00-11:00 Cairo
        (_z(2026, 6, 3, 13), _z(2026, 6, 3, 13, 45)),  # Wed 16:00-16:45 Cairo
    ]
    windows = occurrences(rules, **window)
    assert len(windows) == 4
    offered = removed = 0
    for minutes in ALLOWED_DURATIONS:
        free = bookable_slots(rules, **window, duration=_minutes(minutes), busy=[], now=now)
        slots = bookable_slots(rules, **window, duration=_minutes(minutes), busy=busy, now=now)
        for slot in slots:
            assert any(lo <= slot[0] and slot[1] <= hi for lo, hi in windows), slot
            assert not any(_overlaps(slot, interval) for interval in busy), slot
        clashing = {slot for slot in free if any(_overlaps(slot, i) for i in busy)}
        assert set(free) - set(slots) == clashing
        assert set(slots) <= set(free)
        offered += len(slots)
        removed += len(clashing)
    assert offered > 20
    assert removed > 0
    hour = bookable_slots(rules, **window, duration=_minutes(60), busy=busy, now=now)
    assert (_z(2026, 6, 1, 6), _z(2026, 6, 1, 7)) in hour  # 09:00-10:00 ends where busy starts
    assert (_z(2026, 6, 1, 8), _z(2026, 6, 1, 9)) in hour  # 11:00-12:00 starts where it ends
    # slots are stepped inside one rule's window: none spans the 12:00 boundary
    assert (_z(2026, 6, 1, 8, 30), _z(2026, 6, 1, 9, 30)) not in hour


def test_slots_respect_min_notice_horizon_step_durations() -> None:
    assert timedelta(hours=2) == MIN_NOTICE
    assert timedelta(minutes=30) == SLOT_STEP
    rules = [AvailabilityRule(day, 8 * 60 + 15, 21 * 60) for day in range(1, 8)]
    window = {"zone": CAIRO, "start": date(2026, 6, 1), "days": 35}
    now = _z(2026, 6, 1, 9, 10)  # 12:10 Cairo
    windows = occurrences(rules, **window)
    assert len(windows) == 35
    for minutes in ALLOWED_DURATIONS:
        duration = _minutes(minutes)
        slots = bookable_slots(rules, **window, duration=duration, busy=[], now=now)
        assert slots == sorted(slots)
        assert len(slots) > 500
        for start, end in slots:
            assert end - start == duration
            assert start >= now + MIN_NOTICE
            assert start <= now + MAX_BOOKING_HORIZON
            anchor = next(lo for lo, hi in windows if lo <= start < hi)
            assert (start - anchor) % SLOT_STEP == timedelta(0)
        # first: first step at or after 14:10 Cairo; last: last step at or before 12:10 on 29 June
        assert slots[0][0] == _z(2026, 6, 1, 11, 15)
        assert slots[-1][0] == _z(2026, 6, 29, 8, 45)
    for minutes in (30, 50, 150):
        with pytest.raises(ValueError, match="duration"):
            bookable_slots(rules, **window, duration=_minutes(minutes), busy=[], now=now)


def test_bookable_equals_membership_in_bookable_slots() -> None:
    rules = [
        AvailabilityRule(THU, 17 * 60, 18 * 60 + 30),
        AvailabilityRule(THU, 22 * 60, 24 * 60),
        AvailabilityRule(FRI, 0, 2 * 60),
        AvailabilityRule(SAT, 9 * 60, 12 * 60),
    ]
    busy = [
        (_z(2026, 4, 25, 7), _z(2026, 4, 25, 8)),
        (_z(2026, 10, 31, 8), _z(2026, 10, 31, 9)),
    ]
    scans = [
        (date(2026, 4, 23), _z(2026, 4, 21)),  # spring forward
        (date(2026, 10, 29), _z(2026, 10, 27)),  # fall back
        (date(2026, 4, 23), _z(2026, 3, 20)),  # every candidate beyond the horizon
    ]
    candidates = members = 0
    codes: set[str | None] = set()
    for first_day, now in scans:
        offered = {
            minutes: set(
                bookable_slots(
                    rules,
                    zone=CAIRO,
                    start=first_day - timedelta(days=1),
                    days=6,
                    duration=_minutes(minutes),
                    busy=busy,
                    now=now,
                )
            )
            for minutes in ALLOWED_DURATIONS
        }
        origin = datetime.combine(first_day, time(), tzinfo=UTC)
        for step in range(3 * 24 * 4):
            start = origin + _minutes(15 * step)
            for minutes in (*ALLOWED_DURATIONS, 30, 50):
                end = start + _minutes(minutes)
                got = bookable(rules, zone=CAIRO, starts_at=start, ends_at=end, busy=busy, now=now)
                member = minutes in ALLOWED_DURATIONS and (start, end) in offered[minutes]
                assert (got is None) == member, (start, minutes, got)
                candidates += 1
                members += member
                codes.add(None if got is None else got.code)
    assert candidates == 3 * 288 * 6
    assert members >= 20
    assert codes == {None, "not_bookable", "beyond_horizon"}
    # only instants that bookable_slots produced are bookable (BK-7), in any offset
    now = _z(2026, 10, 27)
    hour_slots = bookable_slots(
        rules,
        zone=CAIRO,
        start=date(2026, 10, 29),
        days=1,
        duration=_minutes(60),
        busy=busy,
        now=now,
    )
    start, end = hour_slots[0]
    assert (start, end) == (_z(2026, 10, 29, 14), _z(2026, 10, 29, 15))
    assert bookable(rules, zone=CAIRO, starts_at=start, ends_at=end, busy=busy, now=now) is None
    as_cairo = (start.astimezone(TZ), end.astimezone(TZ))
    assert (
        bookable(rules, zone=CAIRO, starts_at=as_cairo[0], ends_at=as_cairo[1], busy=busy, now=now)
        is None
    )
    nudged = start + timedelta(microseconds=1)
    refusal = bookable(rules, zone=CAIRO, starts_at=nudged, ends_at=end, busy=busy, now=now)
    assert refusal is not None
    assert refusal.code == "not_bookable"


def test_normalize_rules_rejects_overlap() -> None:
    morning = AvailabilityRule(MON, 9 * 60, 12 * 60)
    overlapping = AvailabilityRule(MON, 11 * 60 + 45, 13 * 60)
    inside = AvailabilityRule(MON, 10 * 60, 11 * 60)
    for rules in (
        [morning, overlapping],
        [overlapping, morning],
        [morning, morning],
        [inside, morning],
    ):
        with pytest.raises(OverlappingRules):
            normalize_rules(rules)
    assert issubclass(OverlappingRules, ValueError)
    with pytest.raises(OverlappingRules):
        occurrences([morning, overlapping], zone=CAIRO, start=date(2026, 6, 1), days=1)
    # adjacency is not overlap ('[)' like the DB exclusion constraint); other days are separate
    noon = AvailabilityRule(MON, 12 * 60, 13 * 60)
    tue_early = AvailabilityRule(TUE, 0, 60)
    tue_late = AvailabilityRule(TUE, 23 * 60, 24 * 60)
    same_time_sunday = AvailabilityRule(SUN, 9 * 60, 12 * 60)
    rules = [tue_late, same_time_sunday, noon, tue_early, morning]
    assert normalize_rules(rules) == (morning, noon, tue_early, tue_late, same_time_sunday)
    assert normalize_rules([]) == ()
    # rules outside the SPEC §a.2 CHECKs are refused too
    for bad in (
        AvailabilityRule(0, 60, 120),
        AvailabilityRule(8, 60, 120),
        AvailabilityRule(MON, -15, 60),
        AvailabilityRule(MON, 1440, 1455),
        AvailabilityRule(MON, 10, 60),
        AvailabilityRule(MON, 60, 70),
        AvailabilityRule(MON, 60, 60),
        AvailabilityRule(MON, 120, 60),
        AvailabilityRule(MON, 0, 1455),
    ):
        with pytest.raises(ValueError, match="availability rule"):
            normalize_rules([bad])


DAILY = [AvailabilityRule(day, 8 * 60, 20 * 60) for day in range(1, 8)]


def test_slot_exactly_min_notice_ahead_is_offered() -> None:
    now = _z(2026, 6, 1, 9, 0)  # 12:00 Cairo; 14:00 Cairo is a step of the 08:00 window
    earliest = now + MIN_NOTICE
    assert (earliest - _z(2026, 6, 1, 5, 0)) % SLOT_STEP == timedelta(0)
    hour = _minutes(60)
    slots = bookable_slots(
        DAILY, zone=CAIRO, start=date(2026, 6, 1), days=1, duration=hour, busy=[], now=now
    )
    assert slots[0] == (earliest, earliest + hour)
    assert (
        bookable(DAILY, zone=CAIRO, starts_at=earliest, ends_at=earliest + hour, busy=[], now=now)
        is None
    )
    early = earliest - SLOT_STEP
    refusal = bookable(DAILY, zone=CAIRO, starts_at=early, ends_at=early + hour, busy=[], now=now)
    assert refusal is not None
    assert refusal.code == "not_bookable"


NAIVE = datetime(2026, 6, 1, 9, 0)
AWARE = _z(2026, 6, 1, 9, 0)
HOUR = _minutes(60)


def _slots(*, now: datetime, busy: list[tuple[datetime, datetime]]) -> object:
    return bookable_slots(
        DAILY, zone=CAIRO, start=date(2026, 6, 2), days=1, duration=HOUR, busy=busy, now=now
    )


def _one(*, starts_at: datetime, now: datetime, busy: list[tuple[datetime, datetime]]) -> object:
    return bookable(
        DAILY, zone=CAIRO, starts_at=starts_at, ends_at=starts_at + HOUR, busy=busy, now=now
    )


# ``occurrences`` takes a date and a zone, no instant, so it has nothing to refuse.
_NAIVE_SLOT_CALLS = {
    "bookable_slots now": lambda: _slots(now=NAIVE, busy=[]),
    "bookable_slots busy": lambda: _slots(now=AWARE, busy=[(NAIVE, NAIVE + HOUR)]),
    "bookable starts_at": lambda: _one(starts_at=NAIVE + timedelta(days=1), now=AWARE, busy=[]),
    "bookable now": lambda: _one(starts_at=AWARE + timedelta(days=1), now=NAIVE, busy=[]),
    "bookable all naive": lambda: _one(starts_at=NAIVE + timedelta(days=1), now=NAIVE, busy=[]),
    "bookable busy": lambda: _one(
        starts_at=AWARE + timedelta(days=1), now=AWARE, busy=[(NAIVE, NAIVE + HOUR)]
    ),
}


@pytest.mark.parametrize("call", list(_NAIVE_SLOT_CALLS.values()), ids=list(_NAIVE_SLOT_CALLS))
def test_naive_datetimes_refused_by_slot_functions(call: Callable[[], object]) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        call()
