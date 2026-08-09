"""Tests for the adaptive study-plan scheduler (P4.7 chunk A).

Every documented decision — the signal weights, activity-type earning, the
``no_signal`` refusal, partial-signal handling, and clock injection — gets a
test, and each rule is verified by its inverse: a test that only shows a rule
firing does not show it is doing anything.
"""

from __future__ import annotations

import datetime

from lemely.core.schemas import WeakArea
from lemely.core.study import ActivityType, StudyPlan, StudyPlanUnavailableReason
from lemely.core.study_plan import (
    MAX_SESSION_MINUTES,
    MIN_SESSION_MINUTES,
    ConfidenceRating,
    PlacementTopicResult,
    TopicAvailability,
    build_study_plan,
)

_NOW = datetime.datetime(2026, 8, 10, 9, 0, tzinfo=datetime.UTC)  # a Monday


def _weak(topic: str, lost: int, maximum: int = 10) -> WeakArea:
    accuracy = 1.0 - (lost / maximum) if maximum else 0.0
    return WeakArea(
        topic=topic, lost_marks=lost, maximum_marks=maximum, accuracy=accuracy, question_ids=["q1"]
    )


def _minutes_by_topic_desc(plan: StudyPlan) -> list[str]:
    """Topics ordered by total scheduled minutes, most first.

    Priority is read off the **minutes a topic is allocated**, not off the
    position of its first session. Sessions are laid out by calendar date so
    S-24 can render a week in order, and a high-priority topic is split
    across several days — so position stopped being a proxy for priority the
    moment splitting landed. Minutes are what the weighting actually decides,
    which makes this the more direct assertion, not a looser one.
    """
    totals: dict[str, int] = {}
    for session in plan.sessions:
        totals[session.topic] = totals.get(session.topic, 0) + session.duration_minutes
    return sorted(totals, key=lambda topic: (-totals[topic], topic))


class TestNoSignalRefusal:
    """Requirement 3: no signal at all is an honest refusal, never an invented week."""

    def test_all_three_signals_empty_is_no_signal(self) -> None:
        plan = build_study_plan("s1", "0625", weekly_hours=10.0, now=_NOW)
        assert plan.available is False
        assert plan.reason == StudyPlanUnavailableReason.no_signal.value
        assert plan.sessions == []

    def test_inverse_any_single_signal_present_is_not_a_refusal(self) -> None:
        """The inverse: one non-empty signal (even confidence alone) is enough to avoid refusal."""
        plan = build_study_plan(
            "s1",
            "0625",
            weekly_hours=10.0,
            now=_NOW,
            confidence_ratings=[ConfidenceRating(topic="Waves", rating=1)],
        )
        assert plan.available is True
        assert plan.reason is None


class TestAllZeroIsARealPlanNotARefusal:
    """Requirement 3: a topic with rows but nothing lost is a different, real state."""

    def test_zero_loss_and_top_confidence_gives_empty_but_available_plan(self) -> None:
        plan = build_study_plan(
            "s1",
            "0625",
            weekly_hours=10.0,
            now=_NOW,
            weaknesses=[_weak("Waves", 0), _weak("Moles", 0)],
        )
        assert plan.available is True
        assert plan.reason is None
        assert plan.sessions == []

    def test_inverse_nonzero_loss_produces_sessions(self) -> None:
        plan = build_study_plan(
            "s1", "0625", weekly_hours=10.0, now=_NOW, weaknesses=[_weak("Waves", 5)]
        )
        assert plan.sessions != []


class TestWeighting:
    """Requirement 2: weights are documented and pinned, most-consequential to least."""

    def test_weakness_outweighs_placement_outweighs_confidence(self) -> None:
        """Three topics, each maxed on exactly one signal (others present at zero/best).

        Because all three signal collections cover every topic here, no
        renormalisation kicks in (see ``TestPartialSignal`` for that), so the
        resulting priority order is a direct readout of
        ``WEIGHT_WEAKNESS > WEIGHT_PLACEMENT > WEIGHT_CONFIDENCE``.
        """
        plan = build_study_plan(
            "s1",
            "0625",
            weekly_hours=10.0,
            now=_NOW,
            weaknesses=[_weak("A", 10), _weak("B", 0), _weak("C", 0)],
            placement_results=[
                PlacementTopicResult(topic="A", lost_marks=0, maximum_marks=10),
                PlacementTopicResult(topic="B", lost_marks=10, maximum_marks=10),
                PlacementTopicResult(topic="C", lost_marks=0, maximum_marks=10),
            ],
            confidence_ratings=[
                ConfidenceRating(topic="A", rating=5),
                ConfidenceRating(topic="B", rating=5),
                ConfidenceRating(topic="C", rating=1),
            ],
        )
        assert _minutes_by_topic_desc(plan) == ["A", "B", "C"]

    def test_inverse_flipping_which_topic_is_maxed_flips_the_order(self) -> None:
        """The order above is not an artefact of topic name/insertion order."""
        plan = build_study_plan(
            "s1",
            "0625",
            weekly_hours=10.0,
            now=_NOW,
            weaknesses=[_weak("A", 0), _weak("B", 0), _weak("C", 10)],
            placement_results=[
                PlacementTopicResult(topic="A", lost_marks=0, maximum_marks=10),
                PlacementTopicResult(topic="B", lost_marks=10, maximum_marks=10),
                PlacementTopicResult(topic="C", lost_marks=0, maximum_marks=10),
            ],
            confidence_ratings=[
                ConfidenceRating(topic="A", rating=1),
                ConfidenceRating(topic="B", rating=5),
                ConfidenceRating(topic="C", rating=5),
            ],
        )
        assert _minutes_by_topic_desc(plan) == ["C", "B", "A"]


class TestPartialSignal:
    """Requirement 3: partial signal must produce a real plan, not a diluted one."""

    def test_missing_signal_is_not_zero_filled(self) -> None:
        """A topic seen only by S-02 confidence scores on that evidence alone.

        If a missing signal were zero-filled instead of the weights being
        renormalised over what is present, a confidence-only topic maxed at
        rating=1 would score only ``WEIGHT_CONFIDENCE * 1.0 == 0.2`` — below
        a topic with real but partial weakness evidence. Renormalisation
        means it instead scores the full ``1.0`` on the one signal it has.
        """
        plan = build_study_plan(
            "s1",
            "0625",
            weekly_hours=3.0,
            now=_NOW,
            weaknesses=[_weak("Partial", 3)],  # weakness score 0.3, only one signal
            confidence_ratings=[ConfidenceRating(topic="ConfidenceOnly", rating=1)],
        )
        # Totals, not per-session durations: a high-priority topic may be
        # split across days, which would otherwise hide its real allocation.
        assert _minutes_by_topic_desc(plan)[0] == "ConfidenceOnly"

    def test_inverse_questionnaire_only_still_produces_a_real_plan(self) -> None:
        """No weaknesses, no placement — questionnaire alone is enough (D4.7 partial signal)."""
        plan = build_study_plan(
            "s1",
            "0625",
            weekly_hours=10.0,
            now=_NOW,
            confidence_ratings=[
                ConfidenceRating(topic="Waves", rating=1),
                ConfidenceRating(topic="Moles", rating=5),
            ],
        )
        assert plan.available is True
        topics = {s.topic for s in plan.sessions}
        assert "Waves" in topics
        assert "Moles" not in topics  # top confidence, zero score, correctly excluded


class TestActivityTypeIsEarned:
    """Requirement 3: activity type must be earned from availability, never assumed."""

    def test_past_paper_earned_when_available(self) -> None:
        plan = build_study_plan(
            "s1",
            "0625",
            weekly_hours=10.0,
            now=_NOW,
            weaknesses=[_weak("Waves", 5)],
            availability={"Waves": TopicAvailability(past_paper_question_count=3)},
        )
        assert plan.sessions[0].activity_type == ActivityType.past_paper

    def test_practice_earned_when_only_practice_available(self) -> None:
        plan = build_study_plan(
            "s1",
            "0625",
            weekly_hours=10.0,
            now=_NOW,
            weaknesses=[_weak("Waves", 5)],
            availability={"Waves": TopicAvailability(practice_question_count=3)},
        )
        assert plan.sessions[0].activity_type == ActivityType.practice

    def test_flashcards_earned_when_only_a_deck_exists(self) -> None:
        plan = build_study_plan(
            "s1",
            "0625",
            weekly_hours=10.0,
            now=_NOW,
            weaknesses=[_weak("Waves", 5)],
            availability={"Waves": TopicAvailability(has_flashcard_deck=True)},
        )
        assert plan.sessions[0].activity_type == ActivityType.flashcards

    def test_past_paper_beats_practice_when_both_available(self) -> None:
        plan = build_study_plan(
            "s1",
            "0625",
            weekly_hours=10.0,
            now=_NOW,
            weaknesses=[_weak("Waves", 5)],
            availability={
                "Waves": TopicAvailability(past_paper_question_count=1, practice_question_count=1)
            },
        )
        assert plan.sessions[0].activity_type == ActivityType.past_paper

    def test_inverse_no_availability_never_invents_practice_or_flashcards(self) -> None:
        """No availability entry at all (chunk B not wired yet) — nothing is invented."""
        plan_no_map = build_study_plan(
            "s1", "0625", weekly_hours=10.0, now=_NOW, weaknesses=[_weak("Waves", 5)]
        )
        plan_empty_entry = build_study_plan(
            "s1",
            "0625",
            weekly_hours=10.0,
            now=_NOW,
            weaknesses=[_weak("Waves", 5)],
            availability={"Waves": TopicAvailability()},
        )
        assert plan_no_map.sessions[0].activity_type == ActivityType.review
        assert plan_empty_entry.sessions[0].activity_type == ActivityType.review


class TestClockInjection:
    """The scheduler never reads the wall clock — dates come only from injected ``now``."""

    def test_same_now_gives_same_dates(self) -> None:
        plan_a = build_study_plan(
            "s1", "0625", weekly_hours=10.0, now=_NOW, weaknesses=[_weak("Waves", 5)]
        )
        plan_b = build_study_plan(
            "s1", "0625", weekly_hours=10.0, now=_NOW, weaknesses=[_weak("Waves", 5)]
        )
        assert plan_a.sessions[0].date == plan_b.sessions[0].date == _NOW.date()

    def test_inverse_a_different_now_shifts_the_dates(self) -> None:
        later = _NOW + datetime.timedelta(days=3)
        plan = build_study_plan(
            "s1", "0625", weekly_hours=10.0, now=later, weaknesses=[_weak("Waves", 5)]
        )
        assert plan.sessions[0].date == later.date()
        assert plan.sessions[0].date != _NOW.date()


class TestDurationGranularity:
    def test_duration_capped_at_max_session_minutes(self) -> None:
        plan = build_study_plan(
            "s1", "0625", weekly_hours=100.0, now=_NOW, weaknesses=[_weak("Waves", 10)]
        )
        assert plan.sessions[0].duration_minutes == MAX_SESSION_MINUTES

    def test_inverse_a_tiny_budget_drops_the_topic_instead_of_padding(self) -> None:
        """A share smaller than MIN_SESSION_MINUTES is dropped, not padded up — and this
        is still a real (available) empty plan, not a refusal."""
        plan = build_study_plan(
            "s1", "0625", weekly_hours=0.1, now=_NOW, weaknesses=[_weak("Waves", 5)]
        )
        assert plan.sessions == []
        assert plan.available is True

    def test_durations_round_to_five_minutes(self) -> None:
        plan = build_study_plan(
            "s1",
            "0625",
            weekly_hours=1.0,
            now=_NOW,
            weaknesses=[_weak("Waves", 7), _weak("Moles", 3)],
        )
        for session in plan.sessions:
            assert session.duration_minutes % 5 == 0
            assert session.duration_minutes >= MIN_SESSION_MINUTES


class TestZeroMaximumMarksIsSafe:
    """A weakness/placement row with ``maximum_marks=0`` must not raise a ZeroDivisionError."""

    def test_zero_maximum_marks_scores_zero_not_a_crash(self) -> None:
        plan = build_study_plan(
            "s1",
            "0625",
            weekly_hours=10.0,
            now=_NOW,
            weaknesses=[
                WeakArea(
                    topic="Empty", lost_marks=0, maximum_marks=0, accuracy=0.0, question_ids=[]
                )
            ],
        )
        assert plan.available is True
        assert plan.sessions == []

    def test_inverse_nonzero_maximum_marks_on_the_same_topic_schedules_it(self) -> None:
        plan = build_study_plan(
            "s1", "0625", weekly_hours=10.0, now=_NOW, weaknesses=[_weak("Empty", 5, 10)]
        )
        assert plan.sessions != []


class TestSubjectCodeAndTopicPropagation:
    def test_subject_code_applied_to_every_session(self) -> None:
        plan = build_study_plan(
            "s1",
            "0606",
            weekly_hours=10.0,
            now=_NOW,
            weaknesses=[_weak("Waves", 5), _weak("Moles", 5)],
        )
        assert plan.sessions
        assert all(s.subject_code == "0606" for s in plan.sessions)

    def test_focus_text_names_the_earned_activity_and_topic(self) -> None:
        plan = build_study_plan(
            "s1",
            "0625",
            weekly_hours=10.0,
            now=_NOW,
            weaknesses=[_weak("Waves", 5)],
            availability={"Waves": TopicAvailability(practice_question_count=2)},
        )
        assert plan.sessions[0].focus == "Practice questions: Waves"


class TestWeeklyBudgetIsActuallyScheduled:
    """The budget rule: a topic over the cap is split across days, not truncated.

    Regression cover for the defect the orchestrator measured against the
    first implementation of this module: three weak topics on a ten-hour week
    scheduled **270 of 600 minutes**, because each topic's 200-minute share
    was clipped to ``MAX_SESSION_MINUTES`` and the remainder was dropped —
    while ``weekly_hours`` still reported 10 for the S-24 header to render.
    """

    def test_a_three_topic_ten_hour_week_schedules_almost_all_of_its_budget(self) -> None:
        plan = build_study_plan(
            "s1",
            "0625",
            weekly_hours=10.0,
            now=_NOW,
            weaknesses=[_weak("A", 5), _weak("B", 5), _weak("C", 5)],
        )
        scheduled = sum(s.duration_minutes for s in plan.sessions)
        # Only per-block rounding may go missing: three topics x at most
        # _ROUND_TO_MINUTES each. The pre-fix figure was 270.
        assert scheduled >= 600 - 3 * 5
        assert scheduled <= 600

    def test_the_split_is_what_recovers_the_budget_not_a_longer_session(self) -> None:
        """The inverse of truncation: more sessions than topics, none over the cap."""
        plan = build_study_plan(
            "s1",
            "0625",
            weekly_hours=10.0,
            now=_NOW,
            weaknesses=[_weak("A", 5), _weak("B", 5), _weak("C", 5)],
        )
        assert len(plan.sessions) > 3
        assert all(s.duration_minutes <= MAX_SESSION_MINUTES for s in plan.sessions)
        assert all(s.duration_minutes >= MIN_SESSION_MINUTES for s in plan.sessions)

    def test_a_small_enough_allocation_is_not_split(self) -> None:
        """The inverse: a topic that fits in one sitting gets exactly one session."""
        plan = build_study_plan(
            "s1", "0625", weekly_hours=1.0, now=_NOW, weaknesses=[_weak("A", 5)]
        )
        assert len(plan.sessions) == 1
        assert plan.sessions[0].duration_minutes == 60


class TestASplitTopicIsRevisitedOnDistinctDays:
    """Splitting is pointless if the blocks land in one evening."""

    def test_no_topic_is_scheduled_twice_on_the_same_day(self) -> None:
        for topic_count in range(1, 11):
            plan = build_study_plan(
                "s1",
                "0625",
                weekly_hours=10.0,
                now=_NOW,
                weaknesses=[_weak(f"T{i}", 5) for i in range(topic_count)],
            )
            seen = [(s.topic, s.date) for s in plan.sessions]
            assert len(seen) == len(set(seen)), f"duplicate topic/day with {topic_count} topics"

    def test_a_split_topic_really_does_span_multiple_days(self) -> None:
        """The inverse: the distinctness above is not vacuous — a split happened."""
        plan = build_study_plan(
            "s1", "0625", weekly_hours=5.0, now=_NOW, weaknesses=[_weak("A", 5)]
        )
        assert len({s.date for s in plan.sessions}) == len(plan.sessions) > 1

    def test_every_session_lands_inside_the_week_the_clock_starts(self) -> None:
        plan = build_study_plan(
            "s1",
            "0625",
            weekly_hours=10.0,
            now=_NOW,
            weaknesses=[_weak(f"T{i}", 5) for i in range(6)],
        )
        first = _NOW.date()
        assert all(first <= s.date <= first + datetime.timedelta(days=6) for s in plan.sessions)
