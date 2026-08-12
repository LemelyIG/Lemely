"""Adaptive study-plan scheduler (P4.7 chunk A) — no I/O, no Gemini calls.

Pure by construction, exactly as :mod:`lemely.core.spaced_repetition` (P4.6
chunk A) is: no DB import, no ``io`` import, no wall clock of its own. The
caller injects ``now``; the same ``(inputs, now)`` always produces the same
plan, and the import-linter layering contract (``core`` must not import
``db``/``io``) is what forces the three input signals below to be plain core
dataclasses rather than the repo rows chunk B will actually read them from.

**Why this replaced the old proportional split.** The previous
``build_study_plan`` distributed ``weekly_hours`` across weak topics
proportionally to ``lost_marks`` and emitted one vague
``"Practice and review: {topic}"`` session per topic, with ``week`` a literal
``1``. MISSION §4 requires *concrete* sessions — topic, activity type,
duration — not advice with a number attached; see the module history for the
full critique.

**Three input signals share one vocabulary on purpose.** Weakness
``lost_marks`` (:class:`~lemely.core.schemas.WeakArea`, rolling performance
across every graded attempt), a placement test's per-topic result
(:class:`PlacementTopicResult`), and the S-02 questionnaire's confidence
sliders (:class:`ConfidenceRating`) are all keyed on the P4.2
``"<code> <name>"`` topic-label vocabulary (D4.2/D4.4) — that shared key is
the entire reason merging them is possible at all, and it is deliberate, not
a coincidence to route around.

**Weighting (documented here, pinned by tests — the point of divergence a
reviewer must be able to see, matching the precedent
:mod:`lemely.core.spaced_repetition` sets for its SM-2 departures):**

1. **Rolling weakness performance carries the most weight, 0.5.** It is
   drawn from every graded attempt a student has ever made on a topic
   (:func:`~lemely.core.analytics.aggregate_weaknesses_from_history`), so it
   is both the largest sample and the most current evidence available.
2. **A placement result carries 0.3.** It is real graded evidence — not
   self-report — but it is a single snapshot from one sitting, so it counts
   for less than a rolling aggregate built from many.
3. **The S-02 confidence rating carries 0.2, the least.** It is the
   student's own guess, not a graded outcome, and self-report is the
   evidence type most prone to both over- and under-confidence. It still
   matters — it is often the *only* signal available before a student has
   attempted anything — which is why it is weighted low rather than
   excluded.
4. **A topic missing a signal is not zero-filled; the remaining weights are
   renormalised over whichever signals are actually present.** Zero-filling
   would silently punish a topic for the *absence* of a signal (e.g. a
   student who has never taken this subject's placement test) rather than
   scoring it on the evidence that does exist. This is what makes "S-02 only,
   no placement yet" and every other partial combination produce a real
   score instead of a diluted one — see :func:`_priority_scores`.

**Honesty rules, all pinned by tests verified by their inverse:**

- **No signal at all is a refusal, never an invented week.** A student with
  no weakness rows, no placement result, and no confidence ratings gets
  ``StudyPlan(available=False, reason=StudyPlanUnavailableReason.no_signal)``
  — the same machine-readable-reason shape
  :class:`~lemely.core.placement.Unavailable` uses, reused deliberately
  rather than inventing a third convention (P4.5/P4.6 precedent).
- **Every topic scoring zero is a different, real state — not a refusal.**
  A student with rows but nothing lost and top confidence everywhere gets
  ``available=True`` with an empty ``sessions`` list: there was something to
  evaluate, and the honest answer is "nothing to schedule this week".
- **Activity type must be earned, never assumed.** :class:`TopicAvailability`
  is an *input* (chunk B supplies the real counts from
  ``practice_repo``/``flashcard_repo``); :func:`_earn_activity_type` never
  schedules ``practice`` for a topic the bank cannot serve or ``flashcards``
  for a topic with no deck. ``review`` needs no resource at all and is the
  honest floor every topic can fall back to.
- **Partial signal produces a real plan.** Only the all-three-empty case
  refuses; one signal alone (typically S-02, answered before any grading
  exists) schedules normally.
- **The week's declared budget is the week's scheduled time.** A topic
  allocated more than :data:`MAX_SESSION_MINUTES` is split into several
  shorter blocks **on different days** (:func:`_split_into_blocks`), not
  truncated to one capped sitting. Truncating silently lost most of the
  budget on exactly the students who need the plan most: with three weak
  topics and a ten-hour week, a first implementation of this module
  scheduled **4.5 of the 10 hours** and still rendered "10 hours a week" in
  the S-24 header, because each topic's 200-minute share was clipped to 90
  and the remainder was dropped on the floor. The header would have been
  describing a week the sessions below it did not add up to. Splitting is
  also the better teaching: several spaced blocks beat one 200-minute sitting.
  Residual drift is only the ±:data:`_ROUND_TO_MINUTES` rounding per block.

Clock-injected: :func:`build_study_plan` takes ``now`` and never calls
``datetime.now()`` itself, so day placement is testable by inversion.
"""

from __future__ import annotations

import datetime
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from lemely.core.study import ActivityType, StudyPlan, StudyPlanUnavailableReason, StudySession

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from lemely.core.schemas import WeakArea

#: Weighting between the three signals — see the module docstring.
WEIGHT_WEAKNESS = 0.5
WEIGHT_PLACEMENT = 0.3
WEIGHT_CONFIDENCE = 0.2

#: A session shorter than this is not a real study block; the topic is
#: dropped from this week's plan rather than padded up to the floor.
MIN_SESSION_MINUTES = 20

#: A session longer than this stops being one sitting. A topic allocated more
#: than this is **split across several days** rather than truncated — see
#: :func:`_split_into_blocks` and the module docstring's budget rule.
MAX_SESSION_MINUTES = 90

#: Durations are rounded to this granularity — a plan that claims 37-minute
#: precision is inventing precision the three input signals cannot support.
_ROUND_TO_MINUTES = 5

#: Days in a week, for the day-index cycle sessions are laid out across.
_DAYS_IN_WEEK = 7


@dataclass(frozen=True, slots=True)
class PlacementTopicResult:
    """One topic's outcome from a placement test.

    Same shape as :class:`~lemely.db.placement_repo.PlacementTopicBreakdown`,
    defined here rather than imported because ``core`` must not import
    ``db`` (import-linter layering contract) — chunk B maps the real rows
    onto this type.
    """

    topic: str
    lost_marks: int
    maximum_marks: int


@dataclass(frozen=True, slots=True)
class ConfidenceRating:
    """One topic's S-02 self-assessment slider value.

    ``rating`` is 1 (least confident) .. 5 (most confident), mirroring
    ``lemely.db.student_profile_repo.ConfidenceRatingRow`` — again a mirror,
    not an import, for the same layering reason.
    """

    topic: str
    rating: int


@dataclass(frozen=True, slots=True)
class TopicAvailability:
    """What chunk B's repos can actually serve for one topic.

    Every field defaults to "nothing available" — a topic absent from the
    ``availability`` mapping entirely is indistinguishable from one whose
    counts are all zero, and both earn nothing but ``review``. Chunk B is
    the only thing that ever supplies non-default values; this module never
    guesses them.
    """

    practice_question_count: int = 0
    past_paper_question_count: int = 0
    has_flashcard_deck: bool = False


_FOCUS_TEXT: dict[ActivityType, str] = {
    ActivityType.practice: "Practice questions",
    ActivityType.flashcards: "Flashcard review",
    ActivityType.past_paper: "Past-paper questions",
    ActivityType.review: "Review notes",
}


def _fraction_lost(lost_marks: int, maximum_marks: int) -> float:
    """Fraction of marks lost, clamped to ``[0, 1]``. Zero when there is nothing to divide by."""
    if maximum_marks <= 0:
        return 0.0
    return max(0.0, min(1.0, lost_marks / maximum_marks))


def _confidence_gap(rating: int) -> float:
    """How far a 1..5 confidence rating sits from full confidence, as a ``[0, 1]`` gap."""
    clamped = max(1, min(5, rating))
    return (5 - clamped) / 4


def _priority_scores(
    weaknesses: Sequence[WeakArea],
    placement_results: Sequence[PlacementTopicResult],
    confidence_ratings: Sequence[ConfidenceRating],
) -> dict[str, float]:
    """Weighted-average priority per topic, renormalised over present signals.

    See the module docstring's weighting section (point 4 especially): a
    topic missing a signal has its score computed only from the signals it
    does have, not diluted by a zero standing in for the missing one.
    """
    components: dict[str, list[tuple[float, float]]] = {}
    for area in weaknesses:
        components.setdefault(area.topic, []).append(
            (WEIGHT_WEAKNESS, _fraction_lost(area.lost_marks, area.maximum_marks))
        )
    for result in placement_results:
        components.setdefault(result.topic, []).append(
            (WEIGHT_PLACEMENT, _fraction_lost(result.lost_marks, result.maximum_marks))
        )
    for rating in confidence_ratings:
        components.setdefault(rating.topic, []).append(
            (WEIGHT_CONFIDENCE, _confidence_gap(rating.rating))
        )

    scores: dict[str, float] = {}
    for topic, parts in components.items():
        weight_sum = sum(weight for weight, _ in parts)
        if weight_sum == 0:
            scores[topic] = 0.0
            continue
        scores[topic] = sum(weight * value for weight, value in parts) / weight_sum
    return scores


def _earn_activity_type(availability: TopicAvailability | None) -> ActivityType:
    """Choose the highest-value activity type this topic has actually earned.

    Ordered past-paper > practice > flashcards > review: a past-paper
    question is the closest simulation of the real exam and therefore the
    most valuable revision available; ordinary bank practice is the
    next-most authentic; flashcards suit recall once material has a deck
    behind it; and review — re-reading notes and worked examples — needs no
    bank row or deck at all, so it is always earned and is the honest floor,
    never a gap this module fills with invented precision (UI spec §1.4).
    """
    if availability is None:
        return ActivityType.review
    if availability.past_paper_question_count > 0:
        return ActivityType.past_paper
    if availability.practice_question_count > 0:
        return ActivityType.practice
    if availability.has_flashcard_deck:
        return ActivityType.flashcards
    return ActivityType.review


def _round_minutes(value: float) -> int:
    """Round to the nearest :data:`_ROUND_TO_MINUTES`, banker's rounding (built-in ``round()``)."""
    return int(_ROUND_TO_MINUTES * round(value / _ROUND_TO_MINUTES))


def _split_into_blocks(total_minutes: float) -> list[int]:
    """Split one topic's weekly allocation into equal per-day study blocks.

    A topic allocated more than :data:`MAX_SESSION_MINUTES` gets several
    shorter blocks instead of one capped sitting, so the week's declared
    budget is actually scheduled rather than silently clipped (see the module
    docstring's budget rule).

    The block count is capped at :data:`_DAYS_IN_WEEK` because
    :func:`_day_offsets` places each of a topic's blocks on a **distinct**
    day, and a week has seven of them. That ceiling only binds above
    ``7 * MAX_SESSION_MINUTES`` (10.5 hours) on a *single* topic, where the
    honest answer is that the excess does not fit in the week at all.

    Returns:
        Per-block durations, or an empty list when the allocation is too
        small to be a real session (below :data:`MIN_SESSION_MINUTES` — it is
        dropped, never padded up to the floor).
    """
    if total_minutes < MIN_SESSION_MINUTES:
        return []
    block_count = min(
        math.ceil(total_minutes / MAX_SESSION_MINUTES),
        _DAYS_IN_WEEK,
    )
    per_block = min(_round_minutes(total_minutes / block_count), MAX_SESSION_MINUTES)
    if per_block < MIN_SESSION_MINUTES:
        # Rounding a many-way split can drop each block under the floor even
        # though the total clears it. Prefer fewer, real blocks over several
        # unusable ones.
        block_count = max(1, int(total_minutes // MIN_SESSION_MINUTES))
        per_block = min(_round_minutes(total_minutes / block_count), MAX_SESSION_MINUTES)
    return [per_block] * block_count


def _day_offsets(block_count: int, stagger: int) -> list[int]:
    """Day-of-week offsets for one topic's blocks — always distinct days.

    Blocks are spread as evenly as the week allows (``7 // block_count``
    apart) so a split topic is genuinely revisited across the week rather
    than sat twice in one evening, which would defeat the point of splitting
    it. ``stagger`` shifts each topic's start day so topics do not all pile
    onto day zero.
    """
    step = _DAYS_IN_WEEK // block_count
    return [(stagger + index * step) % _DAYS_IN_WEEK for index in range(block_count)]


def build_study_plan(
    student_id: str,
    subject_code: str,
    *,
    weekly_hours: float,
    now: datetime.datetime,
    weaknesses: Sequence[WeakArea] = (),
    placement_results: Sequence[PlacementTopicResult] = (),
    confidence_ratings: Sequence[ConfidenceRating] = (),
    availability: Mapping[str, TopicAvailability] | None = None,
) -> StudyPlan:
    """Build one week's adaptive study plan from up to three weighted signals.

    Pure: the same inputs and the same ``now`` always produce the same plan.
    ``now`` is the injected clock — sessions are laid out on the calendar
    dates that follow it, never on ``datetime.now()`` read internally.

    Args:
        student_id: Whose plan this is.
        subject_code: The subject this plan covers (a plan is single-subject,
            mirroring the surface that previously took ``profile.subjects[0]``).
        weekly_hours: The study budget for the week, in hours.
        now: The injected clock. Session dates start at ``now.date()``.
        weaknesses: Rolling per-topic performance (weight
            :data:`WEIGHT_WEAKNESS`). Usually
            ``aggregate_weaknesses_from_history(...).weak_areas``.
        placement_results: One-off placement-test topic outcomes (weight
            :data:`WEIGHT_PLACEMENT`).
        confidence_ratings: S-02 self-assessment sliders (weight
            :data:`WEIGHT_CONFIDENCE`).
        availability: What each topic has actually earned — practice/past-paper
            question counts and flashcard-deck presence. ``None`` (or a topic
            missing from the mapping) means nothing is available, so that
            topic's sessions fall back to ``review``.

    Returns:
        A :class:`~lemely.core.study.StudyPlan`. ``available=False`` with
        ``reason=StudyPlanUnavailableReason.no_signal`` only when
        ``weaknesses``, ``placement_results``, and ``confidence_ratings`` are
        all empty — see the module docstring's honesty rules for every other
        state, including the real "nothing to schedule" empty-sessions case.
    """
    if not weaknesses and not placement_results and not confidence_ratings:
        return StudyPlan(
            student_id=student_id,
            weekly_hours=weekly_hours,
            sessions=[],
            available=False,
            reason=StudyPlanUnavailableReason.no_signal.value,
        )

    scores = _priority_scores(weaknesses, placement_results, confidence_ratings)
    eligible = sorted(
        ((topic, score) for topic, score in scores.items() if score > 0),
        key=lambda item: (-item[1], item[0]),
    )
    if not eligible:
        # A real "nothing to schedule" state, not a refusal — see the module
        # docstring's honesty rules.
        return StudyPlan(student_id=student_id, weekly_hours=weekly_hours, sessions=[])

    total_score = sum(score for _, score in eligible)
    weekly_minutes = weekly_hours * 60
    availability_map = availability or {}

    sessions: list[StudySession] = []
    for stagger, (topic, score) in enumerate(eligible):
        raw_minutes = weekly_minutes * score / total_score
        blocks = _split_into_blocks(raw_minutes)
        if not blocks:
            # Too small a share of the week to be a real session — dropped,
            # not padded up to the floor (the ±1-session rounding tolerance
            # the old scheduler documented, generalised to minutes).
            continue
        activity_type = _earn_activity_type(availability_map.get(topic))
        sessions.extend(
            StudySession(
                date=now.date() + datetime.timedelta(days=day_offset),
                topic=topic,
                subject_code=subject_code,
                activity_type=activity_type,
                duration_minutes=duration,
                focus=f"{_FOCUS_TEXT[activity_type]}: {topic}",
            )
            for duration, day_offset in zip(blocks, _day_offsets(len(blocks), stagger), strict=True)
        )

    sessions.sort(key=lambda session: (session.date, session.topic))

    return StudyPlan(student_id=student_id, weekly_hours=weekly_hours, sessions=sessions)


__all__ = [
    "MAX_SESSION_MINUTES",
    "MIN_SESSION_MINUTES",
    "WEIGHT_CONFIDENCE",
    "WEIGHT_PLACEMENT",
    "WEIGHT_WEAKNESS",
    "ConfidenceRating",
    "PlacementTopicResult",
    "TopicAvailability",
    "build_study_plan",
]
