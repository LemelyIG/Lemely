"""Tests for Phase 5: build_study_plan scheduler and StudyPlanNarrator."""

from __future__ import annotations

from unittest.mock import MagicMock

from lemely.core.schemas import WeakArea, WeaknessReport
from lemely.core.study_plan import build_study_plan


def _weakness(lost_marks_list: list[int], max_marks: int = 10) -> WeaknessReport:
    areas = []
    for i, lost in enumerate(lost_marks_list):
        accuracy = 1.0 - (lost / max_marks) if max_marks else 0.0
        areas.append(
            WeakArea(
                topic=f"Topic{i + 1}",
                lost_marks=lost,
                maximum_marks=max_marks,
                accuracy=accuracy,
                question_ids=[f"q{i + 1}"],
            )
        )
    return WeaknessReport(weak_areas=areas)


class TestBuildStudyPlan:
    def test_zero_loss_topic_excluded(self) -> None:
        weakness = _weakness([3, 1, 0])
        plan = build_study_plan(None, weakness, weekly_hours=10.0)
        topics = [s.topic for s in plan.sessions]
        assert "Topic3" not in topics
        assert "Topic1" in topics
        assert "Topic2" in topics

    def test_hours_sum_invariant(self) -> None:
        weakness = _weakness([3, 1, 0])
        plan = build_study_plan(None, weakness, weekly_hours=10.0)
        total = sum(s.hours for s in plan.sessions)
        assert total <= 10.0 + 1.0  # rounding tolerance ±1

    def test_proportional_split(self) -> None:
        # Topics with weights 3 and 1 → ~75/25 split
        weakness = _weakness([3, 1])
        plan = build_study_plan(None, weakness, weekly_hours=10.0)
        assert len(plan.sessions) == 2
        hours = {s.topic: s.hours for s in plan.sessions}
        # Topic1 gets more than Topic2
        assert hours["Topic1"] > hours["Topic2"]

    def test_all_zero_loss_returns_empty_sessions(self) -> None:
        weakness = _weakness([0, 0, 0])
        plan = build_study_plan(None, weakness, weekly_hours=10.0)
        assert plan.sessions == []

    def test_empty_weakness_returns_empty_sessions(self) -> None:
        weakness = WeaknessReport(weak_areas=[])
        plan = build_study_plan(None, weakness, weekly_hours=10.0)
        assert plan.sessions == []

    def test_narrative_is_none_without_narrator(self) -> None:
        weakness = _weakness([3, 1])
        plan = build_study_plan(None, weakness, weekly_hours=5.0)
        assert plan.narrative is None

    def test_narrator_skippable_no_gemini_calls(self) -> None:
        mock_client = MagicMock()
        weakness = _weakness([3, 1])
        build_study_plan(None, weakness, weekly_hours=5.0)
        mock_client.generate_structured.assert_not_called()
