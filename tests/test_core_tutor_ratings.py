"""Tutor rating maths (SPEC section e.1 ``tutor_ratings``, SC-16, rows 6 and 7).

Expected values are derived here with ``fractions.Fraction`` from the formula in
the SPEC prose (a Bayesian mean with a prior of 4.0 and weight 5), not by calling
the code under test, so a wrong formula cannot agree with itself.
"""

from __future__ import annotations

import random
import re
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import pytest

from lemely.core import tutor_ratings
from lemely.core.tutor_ratings import (
    BAYES_PRIOR_MEAN,
    BAYES_PRIOR_WEIGHT,
    NEW_THRESHOLD,
    REVIEW_EDIT_WINDOW,
    REVIEW_MIN_ACCOUNT_AGE,
    RatingDisplay,
    aggregate_latest_per_student,
    bayesian_score,
    quarter_label,
    rating_display,
    review_edit_deadline,
)

_SPEC = Path(__file__).resolve().parents[1] / "docs" / "tutoring" / "SPEC.md"
_T0 = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
_EN_DASH = "\U00002013"


def _spec_line(name: str) -> str:
    spec = _SPEC.read_text(encoding="utf-8")
    line = re.search(rf"^{name}:.*$", spec, re.MULTILINE)
    assert line is not None, name
    return line.group(0)


def _expected_score(total: int, count: int) -> Fraction:
    """(prior_weight * prior_mean + sum) / (prior_weight + count), straight from the prose."""
    return (Fraction(5) * Fraction(4) + total) / (5 + count)


def test_constants_equal_spec_text() -> None:
    mean_line = _spec_line("BAYES_PRIOR_MEAN")
    mean = re.search(r'Decimal\("([\d.]+)"\)', mean_line)
    weight = re.search(r"BAYES_PRIOR_WEIGHT: Final = (\d+)", mean_line)
    assert mean is not None
    assert weight is not None
    assert Decimal(mean.group(1)) == BAYES_PRIOR_MEAN
    assert int(weight.group(1)) == BAYES_PRIOR_WEIGHT
    new_threshold = re.search(r"NEW_THRESHOLD: Final = (\d+)", _spec_line("NEW_THRESHOLD"))
    assert new_threshold is not None
    assert int(new_threshold.group(1)) == NEW_THRESHOLD
    for name, value in (
        ("REVIEW_EDIT_WINDOW", REVIEW_EDIT_WINDOW),
        ("REVIEW_MIN_ACCOUNT_AGE", REVIEW_MIN_ACCOUNT_AGE),
    ):
        days = re.search(r"timedelta\(days=(\d+)\)", _spec_line(name))
        assert days is not None, name
        assert timedelta(days=int(days.group(1))) == value, name


def test_review_open_at_lives_in_booking_not_here() -> None:
    # PLAN section 1.4 item 8: ``review_open_at`` moved to ``core.booking`` (T03).
    assert not hasattr(tutor_ratings, "review_open_at")


def test_bayesian_zero_reviews_is_4_000000() -> None:
    score = bayesian_score(0, 0)
    assert score == Decimal("4.000000")
    assert str(score) == "4.000000"
    assert isinstance(score, Decimal)


@pytest.mark.parametrize(
    ("total", "count"),
    [(5, 1), (1, 1), (3, 1), (9, 2), (10, 2), (13, 3), (14, 3), (17, 4), (90, 20), (100, 20),
     (4, 1), (7, 2), (11, 3), (250, 52), (500, 100)],
)  # fmt: skip
def test_bayesian_score_matches_formula_quantised_to_six_places(total: int, count: int) -> None:
    score = bayesian_score(total, count)
    exact = _expected_score(total, count)
    assert score.as_tuple().exponent == -6
    assert abs(Fraction(score) - exact) <= Fraction(1, 2_000_000)
    # Round-half-up to six places, as Postgres numeric(7,6) stores it.
    scaled = exact * 1_000_000
    floor = scaled.numerator // scaled.denominator
    rounded = floor + (1 if scaled - floor >= Fraction(1, 2) else 0)
    assert score == Decimal(rounded) / Decimal(1_000_000)


def test_bayesian_score_rounds_half_up_not_to_even() -> None:
    # (20 + 125) / (5 + 123) = 145 / 128 = 1.1328125 exactly: a tie at the seventh decimal.
    # Half-up gives 1.132813; round-half-even would give 1.132812.
    assert Fraction(20 + 125, 5 + 123) * 10_000_000 == 11_328_125
    assert bayesian_score(125, 123) == Decimal("1.132813")


def test_n1_five_star_ranks_below_twenty_at_4_5() -> None:
    lone_five_star = bayesian_score(5, 1)
    twenty_at_four_and_a_half = bayesian_score(90, 20)
    assert lone_five_star < twenty_at_four_and_a_half
    # Independent confirmation of the two figures: 25/6 and 110/25.
    assert abs(Fraction(lone_five_star) - Fraction(25, 6)) < Fraction(1, 1_000_000)
    assert twenty_at_four_and_a_half == Decimal("4.400000")


def test_bayesian_score_is_monotone_in_the_sum_and_tends_to_the_mean() -> None:
    scores = [bayesian_score(total, 10) for total in range(10, 51)]
    assert scores == sorted(scores)
    assert len(set(scores)) == len(scores)
    big = bayesian_score(5 * 100_000, 100_000)
    assert Decimal("4.99") < big < Decimal("5")


def test_bayesian_score_stays_within_one_to_five() -> None:
    for count in (1, 2, 3, 10, 500):
        assert Decimal(1) <= bayesian_score(count, count) <= Decimal(5)
        assert Decimal(1) <= bayesian_score(5 * count, count) <= Decimal(5)


@pytest.mark.parametrize(
    ("total", "count"),
    [(-1, 0), (1, 0), (0, -1), (0, 1), (4, 5), (26, 5), (5, 0), (-5, -1)],
)
def test_bayesian_score_rejects_inconsistent_inputs(total: int, count: int) -> None:
    # Mirrors the DB checks: rating_count >= 0 and rating_sum BETWEEN count AND 5 * count.
    with pytest.raises(ValueError, match="rating"):
        bayesian_score(total, count)


def _review(student: str, stars: int, minutes: int) -> tuple[str, int, datetime]:
    return (student, stars, _T0 + timedelta(minutes=minutes))


def test_aggregate_latest_per_student_counts_once() -> None:
    reviews = [
        _review("s1", 2, 0),
        _review("s1", 5, 60),  # s1's latest: counts, the 2 does not
        _review("s2", 4, 10),
        _review("s3", 1, 5),
        _review("s3", 3, 6),
        _review("s3", 2, 7),  # s3's latest is 2
    ]
    rating_sum, rating_count = aggregate_latest_per_student(reviews)
    assert (rating_sum, rating_count) == (5 + 4 + 2, 3)


def test_aggregate_latest_per_student_is_order_independent() -> None:
    reviews = [
        _review("a", 1, 0),
        _review("a", 4, 30),
        _review("b", 5, 5),
        _review("b", 3, 50),
        _review("c", 2, 1),
        _review("d", 5, 2),
        _review("d", 5, 3),
    ]
    expected = aggregate_latest_per_student(reviews)
    assert expected == (4 + 3 + 2 + 5, 4)
    rng = random.Random(20261025)
    for _ in range(25):
        shuffled = reviews[:]
        rng.shuffle(shuffled)
        assert aggregate_latest_per_student(shuffled) == expected


def test_aggregate_latest_per_student_empty_and_single() -> None:
    assert aggregate_latest_per_student([]) == (0, 0)
    assert aggregate_latest_per_student([_review("only", 3, 0)]) == (3, 1)


def test_aggregate_latest_per_student_compares_instants_not_wall_clocks() -> None:
    cairo = timezone(timedelta(hours=3))
    earlier_in_utc = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    later_in_utc_but_smaller_wall_clock = datetime(2026, 9, 1, 14, 0, tzinfo=UTC).astimezone(
        timezone(timedelta(hours=-10))
    )  # 04:00 local, a smaller wall-clock than 12:00 below, yet the later instant
    reviews = [
        ("s", 1, earlier_in_utc.astimezone(cairo)),
        ("s", 5, later_in_utc_but_smaller_wall_clock),
    ]
    assert aggregate_latest_per_student(reviews) == (5, 1)


def test_aggregate_latest_per_student_tie_goes_to_the_later_entry() -> None:
    same = _T0
    assert aggregate_latest_per_student([("s", 2, same), ("s", 4, same)]) == (4, 1)
    assert aggregate_latest_per_student([("s", 4, same), ("s", 2, same)]) == (2, 1)


def test_aggregate_latest_per_student_rejects_bad_stars_and_naive_times() -> None:
    for stars in (0, 6, -1):
        with pytest.raises(ValueError, match="stars"):
            aggregate_latest_per_student([("s", stars, _T0)])
    with pytest.raises(ValueError, match="timezone"):
        aggregate_latest_per_student([("s", 3, datetime(2026, 9, 1, 10, 0))])


def test_aggregate_result_feeds_bayesian_score_in_the_same_order() -> None:
    reviews = [_review("s1", 5, 0), _review("s2", 4, 1), _review("s3", 4, 2)]
    score = bayesian_score(*aggregate_latest_per_student(reviews))
    assert score == bayesian_score(13, 3)


@pytest.mark.parametrize("count", [0, 1, 2])
def test_rating_display_new_below_three_students(count: int) -> None:
    display = rating_display(5 * count, count)
    assert display == RatingDisplay(state="new", average=None, count=count)


@pytest.mark.parametrize(
    ("total", "count", "average"),
    [
        (15, 3, 5.0),
        (3, 3, 1.0),
        (13, 3, 4.3),  # 4.333...
        (14, 3, 4.7),  # 4.666...
        (17, 4, 4.3),  # exactly 4.25: half-up gives 4.3 (banker's rounding would give 4.2)
        (18, 4, 4.5),
        (19, 4, 4.8),  # exactly 4.75
        (277, 60, 4.6),  # 4.6166...
        (92, 20, 4.6),
        (91, 20, 4.6),  # exactly 4.55: half-up gives 4.6
        (89, 20, 4.5),  # 4.45 -> 4.5
    ],
)
def test_rating_display_rated_one_decimal_half_up(total: int, count: int, average: float) -> None:
    display = rating_display(total, count)
    assert display.state == "rated"
    assert display.count == count
    assert display.average == average
    assert isinstance(display.average, float)


def test_rating_display_threshold_is_exactly_three_distinct_students() -> None:
    assert rating_display(10, 2).state == "new"
    assert rating_display(12, 3).state == "rated"
    assert NEW_THRESHOLD == 3


def test_rating_display_rejects_inconsistent_inputs() -> None:
    with pytest.raises(ValueError, match="rating"):
        rating_display(2, 3)
    with pytest.raises(ValueError, match="rating"):
        rating_display(16, 3)
    with pytest.raises(ValueError, match="rating"):
        rating_display(1, 0)


def test_rating_display_is_frozen() -> None:
    display = rating_display(0, 0)
    with pytest.raises(AttributeError):
        display.count = 9


@pytest.mark.parametrize(
    ("instant", "zone", "label"),
    [
        (datetime(2026, 7, 1, 0, 0, tzinfo=UTC), "UTC", f"Jul{_EN_DASH}Sep 2026"),
        (datetime(2026, 7, 1, 0, 0, tzinfo=UTC), "Africa/Cairo", f"Jul{_EN_DASH}Sep 2026"),
        (datetime(2026, 9, 15, 12, 0, tzinfo=UTC), "Africa/Cairo", f"Jul{_EN_DASH}Sep 2026"),
        # 22:30Z on 30 Sep is 01:30 on 1 Oct in Cairo (UTC+3 until 29 Oct 2026).
        (datetime(2026, 9, 30, 22, 30, tzinfo=UTC), "Africa/Cairo", f"Oct{_EN_DASH}Dec 2026"),
        (datetime(2026, 9, 30, 22, 30, tzinfo=UTC), "UTC", f"Jul{_EN_DASH}Sep 2026"),
        # 22:30Z on 31 Dec is 00:30 on 1 Jan in Cairo (UTC+2).
        (datetime(2026, 12, 31, 22, 30, tzinfo=UTC), "Africa/Cairo", f"Jan{_EN_DASH}Mar 2027"),
        (datetime(2026, 12, 31, 22, 30, tzinfo=UTC), "UTC", f"Oct{_EN_DASH}Dec 2026"),
        (datetime(2026, 1, 1, 0, 0, tzinfo=UTC), "UTC", f"Jan{_EN_DASH}Mar 2026"),
        (datetime(2026, 3, 31, 21, 59, tzinfo=UTC), "UTC", f"Jan{_EN_DASH}Mar 2026"),
        (datetime(2026, 4, 1, 0, 0, tzinfo=UTC), "UTC", f"Apr{_EN_DASH}Jun 2026"),
        (datetime(2026, 6, 30, 23, 59, tzinfo=UTC), "UTC", f"Apr{_EN_DASH}Jun 2026"),
        # The input may carry any offset; only the instant and the zone matter.
        (datetime(2026, 9, 30, 20, 0, tzinfo=timezone(timedelta(hours=-5))), "UTC",
         f"Oct{_EN_DASH}Dec 2026"),
    ],
)  # fmt: skip
def test_quarter_label(instant: datetime, zone: str, label: str) -> None:
    assert quarter_label(instant, zone) == label


def test_quarter_label_uses_an_en_dash_and_the_spec_example() -> None:
    spec = _SPEC.read_text(encoding="utf-8")
    example = re.search(r'def quarter_label\(.*?# "([^"]+)"', spec)
    assert example is not None
    assert example.group(1) == quarter_label(datetime(2026, 8, 1, tzinfo=UTC), "Africa/Cairo")
    assert _EN_DASH in example.group(1)


def test_quarter_label_refuses_naive_datetimes_and_unknown_zones() -> None:
    with pytest.raises(ValueError, match="timezone"):
        quarter_label(datetime(2026, 7, 1), "Africa/Cairo")
    with pytest.raises(ValueError, match="zone"):
        quarter_label(_T0, "Mars/Olympus_Mons")


def test_review_edit_deadline_is_created_plus_14_days() -> None:
    created = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
    assert review_edit_deadline(created) == datetime(2026, 9, 15, 10, 0, tzinfo=UTC)
    assert review_edit_deadline(created) - created == timedelta(days=14)


def test_review_edit_deadline_is_exact_elapsed_time_across_a_clock_change() -> None:
    from zoneinfo import ZoneInfo

    cairo = ZoneInfo("Africa/Cairo")
    created = datetime(2026, 10, 20, 12, 0, tzinfo=cairo)  # DST ends 29 Oct 2026 in Cairo
    deadline = review_edit_deadline(created)
    # Fourteen real days (336 hours) later, whatever the wall clock then reads.
    assert deadline.astimezone(UTC) - created.astimezone(UTC) == timedelta(hours=336)
    assert deadline.astimezone(UTC) == datetime(2026, 11, 3, 9, 0, tzinfo=UTC)


def test_review_edit_deadline_refuses_naive_datetime() -> None:
    with pytest.raises(ValueError, match="timezone"):
        review_edit_deadline(datetime(2026, 9, 1, 10, 0))
