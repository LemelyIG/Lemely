"""Tutor rating maths: the ranking score, the display state, the review edit window.

Three decisions from the SPEC meet here, and all three are about not letting a
small number of reviews mislead a student:

* **Ranking** uses a Bayesian mean, not the raw average (locked row 6): with a
  prior of 4.0 worth five reviews, one five-star review scores 4.17, below twenty
  reviews averaging 4.5 (4.40). The score is what ``tutor_profiles.rank_score``
  stores and what the directory sorts by.
* **Counting** is per distinct student (SC-16): a student who reviews the same
  tutor after ten sessions still counts once, by their latest stars, so one loyal
  account cannot move a tutor's rating by writing many reviews.
* **Display** hides stars until three distinct students have rated (row 6):
  below that the card says "New".

Everything is a pure function of integers and instants. The two integers are the
``tutor_profiles`` columns ``rating_sum`` (the sum of each counted student's
latest stars) and ``rating_count`` (distinct students), always passed in that
order, sum first. ``review_open_at`` is not here: it is a booking-time rule and
lives in ``core.booking`` (PLAN section 1.4, item 8).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Final, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

if TYPE_CHECKING:
    from collections.abc import Sequence

BAYES_PRIOR_MEAN: Final = Decimal("4.0")
BAYES_PRIOR_WEIGHT: Final = 5
NEW_THRESHOLD: Final = 3  # row 6, counted in distinct students
REVIEW_EDIT_WINDOW: Final = timedelta(days=14)  # row 7
REVIEW_MIN_ACCOUNT_AGE: Final = timedelta(days=14)  # F7

_MIN_STARS: Final = 1
_MAX_STARS: Final = 5

# ``tutor_profiles.rank_score`` is numeric(7,6); Postgres rounds half away from
# zero, which for these positive scores is ROUND_HALF_UP.
_SCORE_QUANTUM: Final = Decimal("0.000001")
_AVERAGE_QUANTUM: Final = Decimal("0.1")

# Calendar quarters as the card prints them. The dash is U+2013 (the SPEC example
# "Jul-Sep 2026" uses an en dash).
_QUARTER_MONTHS: Final = (
    "Jan\U00002013Mar",
    "Apr\U00002013Jun",
    "Jul\U00002013Sep",
    "Oct\U00002013Dec",
)


@dataclass(frozen=True, slots=True)
class RatingDisplay:
    """What a card shows: ``New`` (no stars) or a one-decimal average and the student count."""

    state: Literal["new", "rated"]
    average: float | None
    count: int


def _check_totals(rating_sum: int, rating_count: int) -> None:
    """Refuse totals the database CHECKs would refuse: they can only come from a bug."""
    if rating_count < 0:
        raise ValueError(f"rating_count must be >= 0, got {rating_count}")
    if not rating_count * _MIN_STARS <= rating_sum <= rating_count * _MAX_STARS:
        raise ValueError(
            f"rating_sum {rating_sum} is impossible for rating_count {rating_count}: "
            f"it must lie between {rating_count * _MIN_STARS} and {rating_count * _MAX_STARS}"
        )


def bayesian_score(rating_sum: int, rating_count: int) -> Decimal:
    """``(prior_weight * prior_mean + rating_sum) / (prior_weight + rating_count)``, to 6 places.

    With no reviews the score is the prior mean, ``4.000000``, which is also the
    column default. Rounded half up and quantised so ``str()`` is always six
    decimals, matching ``numeric(7,6)``.
    """
    _check_totals(rating_sum, rating_count)
    weight = Decimal(BAYES_PRIOR_WEIGHT)
    score = (weight * BAYES_PRIOR_MEAN + rating_sum) / (weight + rating_count)
    return score.quantize(_SCORE_QUANTUM, rounding=ROUND_HALF_UP)


def aggregate_latest_per_student(
    reviews: Sequence[tuple[str, int, datetime]],
) -> tuple[int, int]:
    """Collapse reviews to each student's latest stars: returns ``(rating_sum, rating_count)``.

    ``reviews`` is ``(student_id, stars, created_at)`` for every counted review of
    one tutor, in any order. A student's latest review is the one with the latest
    ``created_at`` (compared as instants); on an exact tie the entry later in the
    sequence wins, so the result is deterministic. The result feeds
    :func:`bayesian_score` and :func:`rating_display` directly, in the same order.
    """
    latest: dict[str, tuple[int, datetime]] = {}
    for student_id, stars, created_at in reviews:
        if not _MIN_STARS <= stars <= _MAX_STARS:
            raise ValueError(f"stars must be {_MIN_STARS} to {_MAX_STARS}, got {stars}")
        _require_aware(created_at)
        current = latest.get(student_id)
        if current is None or created_at >= current[1]:
            latest[student_id] = (stars, created_at)
    return sum(stars for stars, _ in latest.values()), len(latest)


def rating_display(rating_sum: int, rating_count: int) -> RatingDisplay:
    """``New`` below :data:`NEW_THRESHOLD` students, else the average to one decimal (half up)."""
    _check_totals(rating_sum, rating_count)
    if rating_count < NEW_THRESHOLD:
        return RatingDisplay(state="new", average=None, count=rating_count)
    average = (Decimal(rating_sum) / Decimal(rating_count)).quantize(
        _AVERAGE_QUANTUM, rounding=ROUND_HALF_UP
    )
    return RatingDisplay(state="rated", average=float(average), count=rating_count)


def review_edit_deadline(created_at: datetime) -> datetime:
    """The last instant a review can be edited: fourteen elapsed days after it was written.

    Returned in UTC and computed on the instant, not the wall clock, so a clock
    change inside the window cannot shorten or lengthen it.
    """
    _require_aware(created_at)
    return created_at.astimezone(UTC) + REVIEW_EDIT_WINDOW


def quarter_label(created_at: datetime, zone: str) -> str:
    """The calendar quarter of ``created_at`` in ``zone`` as printed on a review (``Jul-Sep 2026``).

    Reviews show a season rather than a date so the timing does not identify the
    reviewer (SC-12). The quarter is the one in the tutor's zone, the same clock
    every other tutoring screen uses.
    """
    _require_aware(created_at)
    try:
        local = created_at.astimezone(ZoneInfo(zone))
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"unknown time zone: {zone!r}") from exc
    return f"{_QUARTER_MONTHS[(local.month - 1) // 3]} {local.year}"


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetimes must carry a timezone")
