"""Tests for the pure SM-2 scheduler (``lemely.core.spaced_repetition``, P4.6 chunk A).

Every rule is verified alongside its inverse: a test that shows ``good``
lengthens the interval is paired with one showing ``again`` shortens it and
increments ``lapses``; the ease floor is proven by driving a card into it and
showing it does not go below; the 1 -> 6 -> interval*EF progression is pinned
explicitly; and purity is proven directly (same inputs, same output; two
calls with different injected ``now`` differ only in the timestamps).

No wall clock anywhere in this file either — every scenario supplies its own
fixed ``now``, matching ``tests/test_at_risk.py``'s style.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from lemely.core.spaced_repetition import (
    AGAIN_REVIEW_DELAY,
    EASE_FACTOR_FLOOR,
    INITIAL_EASE_FACTOR,
    CardSchedule,
    ReviewGrade,
    initial_schedule,
    review,
)

_NOW = datetime(2026, 8, 6, 12, 0, 0, tzinfo=UTC)


# ── initial_schedule ──────────────────────────────────────────────────────


def test_initial_schedule_is_due_immediately() -> None:
    schedule = initial_schedule(_NOW)

    assert schedule.repetitions == 0
    assert schedule.ease_factor == INITIAL_EASE_FACTOR
    assert schedule.interval_days == 0
    assert schedule.lapses == 0
    assert schedule.due_at == _NOW
    assert schedule.last_reviewed_at is None


# ── the 1 -> 6 -> interval*EF progression, pinned ─────────────────────────


def test_good_progression_is_one_then_six_then_interval_times_ease() -> None:
    schedule = initial_schedule(_NOW)

    t1 = _NOW + timedelta(days=1)
    schedule = review(schedule, ReviewGrade.good, now=t1)
    assert schedule.repetitions == 1
    assert schedule.interval_days == 1
    assert schedule.due_at == t1 + timedelta(days=1)
    # quality 4 leaves ease factor unchanged: 0.1 - 1*(0.08+1*0.02) == 0.0
    assert schedule.ease_factor == pytest.approx(2.5)

    t2 = t1 + timedelta(days=1)
    schedule = review(schedule, ReviewGrade.good, now=t2)
    assert schedule.repetitions == 2
    assert schedule.interval_days == 6
    assert schedule.due_at == t2 + timedelta(days=6)
    assert schedule.ease_factor == pytest.approx(2.5)

    t3 = t2 + timedelta(days=6)
    schedule = review(schedule, ReviewGrade.good, now=t3)
    assert schedule.repetitions == 3
    # round(prev_interval_days * prev_ease_factor) == round(6 * 2.5) == 15
    assert schedule.interval_days == 15
    assert schedule.due_at == t3 + timedelta(days=15)


# ── good lengthens the interval / again shortens it (inverse pair) ───────


def test_good_lengthens_the_interval() -> None:
    schedule = initial_schedule(_NOW)
    schedule = review(schedule, ReviewGrade.good, now=_NOW)

    assert schedule.interval_days == 1
    assert schedule.due_at > _NOW


def test_again_shortens_the_interval_and_increments_lapses() -> None:
    schedule = initial_schedule(_NOW)
    # Build up some progress first, so there is an interval to collapse.
    schedule = review(schedule, ReviewGrade.good, now=_NOW)
    schedule = review(schedule, ReviewGrade.good, now=_NOW + timedelta(days=1))
    assert schedule.interval_days == 6
    assert schedule.lapses == 0

    failed = review(schedule, ReviewGrade.again, now=_NOW + timedelta(days=7))

    assert failed.interval_days == 0
    assert failed.repetitions == 0
    assert failed.lapses == schedule.lapses + 1
    assert failed.due_at == (_NOW + timedelta(days=7)) + AGAIN_REVIEW_DELAY
    # The relearning step is far shorter than the interval it replaced.
    assert failed.due_at < (_NOW + timedelta(days=7)) + timedelta(days=schedule.interval_days)


def test_again_from_a_fresh_card_still_increments_lapses_and_resets_repetitions() -> None:
    schedule = initial_schedule(_NOW)

    failed = review(schedule, ReviewGrade.again, now=_NOW)

    assert failed.repetitions == 0
    assert failed.lapses == 1
    assert failed.interval_days == 0
    assert failed.due_at == _NOW + AGAIN_REVIEW_DELAY


# ── ease factor: easy raises it, hard/again lower it (inverse pairs) ─────


def test_easy_raises_the_ease_factor() -> None:
    schedule = initial_schedule(_NOW)
    schedule = review(schedule, ReviewGrade.easy, now=_NOW)

    # quality 5: delta == 0.1 - 0*(...) == +0.1
    assert schedule.ease_factor == pytest.approx(2.6)


def test_hard_lowers_the_ease_factor() -> None:
    schedule = initial_schedule(_NOW)
    schedule = review(schedule, ReviewGrade.hard, now=_NOW)

    # quality 3: delta == 0.1 - 2*(0.08 + 2*0.02) == 0.1 - 0.24 == -0.14
    assert schedule.ease_factor == pytest.approx(2.36)


def test_hard_still_counts_as_a_pass_unlike_again() -> None:
    """``hard`` (quality 3) is SM-2's lowest *passing* grade: repetitions

    build up and lapses do not increment, unlike ``again``.
    """
    schedule = initial_schedule(_NOW)
    schedule = review(schedule, ReviewGrade.hard, now=_NOW)

    assert schedule.repetitions == 1
    assert schedule.lapses == 0
    assert schedule.interval_days == 1


# ── the ease floor: proven by driving a card into it ──────────────────────


def test_ease_factor_is_floored_and_does_not_go_below_it() -> None:
    schedule = initial_schedule(_NOW)  # ease_factor == 2.5

    # quality 0 drops ease by ~0.8 per review: 2.5 -> 1.7 -> (0.9, floored to 1.3).
    schedule = review(schedule, ReviewGrade.again, now=_NOW)
    assert schedule.ease_factor == pytest.approx(1.7)

    schedule = review(schedule, ReviewGrade.again, now=_NOW + timedelta(minutes=10))
    assert schedule.ease_factor == pytest.approx(EASE_FACTOR_FLOOR)

    # A third failure would drive it further negative without the floor;
    # it must stay pinned at the floor instead.
    schedule = review(schedule, ReviewGrade.again, now=_NOW + timedelta(minutes=20))
    assert schedule.ease_factor == pytest.approx(EASE_FACTOR_FLOOR)
    assert schedule.ease_factor >= EASE_FACTOR_FLOOR


# ── purity: same inputs -> same outputs; only `now` may vary the timestamps ─


def test_review_is_pure_same_inputs_same_outputs() -> None:
    schedule = initial_schedule(_NOW)

    first = review(schedule, ReviewGrade.good, now=_NOW)
    second = review(schedule, ReviewGrade.good, now=_NOW)

    assert first == second


def test_review_does_not_depend_on_wall_clock_only_injected_now() -> None:
    schedule = initial_schedule(_NOW)

    later_now = _NOW + timedelta(days=365)
    at_now = review(schedule, ReviewGrade.good, now=_NOW)
    at_later_now = review(schedule, ReviewGrade.good, now=later_now)

    # Non-timestamp fields are identical: only due_at/last_reviewed_at track
    # the injected `now`.
    assert at_now.repetitions == at_later_now.repetitions
    assert at_now.ease_factor == at_later_now.ease_factor
    assert at_now.interval_days == at_later_now.interval_days
    assert at_now.lapses == at_later_now.lapses

    assert at_now.due_at == _NOW + timedelta(days=at_now.interval_days)
    assert at_later_now.due_at == later_now + timedelta(days=at_later_now.interval_days)
    assert at_now.last_reviewed_at == _NOW
    assert at_later_now.last_reviewed_at == later_now


def test_card_schedule_is_frozen() -> None:
    schedule = initial_schedule(_NOW)

    with pytest.raises(AttributeError):
        schedule.repetitions = 5  # type: ignore[misc]


def test_card_schedule_round_trips_field_values() -> None:
    schedule = CardSchedule(
        repetitions=3,
        ease_factor=2.1,
        interval_days=15,
        lapses=1,
        due_at=_NOW,
        last_reviewed_at=_NOW - timedelta(days=15),
    )

    assert schedule.repetitions == 3
    assert schedule.ease_factor == 2.1
    assert schedule.interval_days == 15
    assert schedule.lapses == 1
    assert schedule.due_at == _NOW
    assert schedule.last_reviewed_at == _NOW - timedelta(days=15)
