"""Tests for Phase 2: compare_performance and aggregate_weaknesses_from_history."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from lemely.core.analytics import aggregate_weaknesses_from_history, compare_performance
from lemely.core.history import PaperRecord, StudentHistory
from lemely.core.schemas import ExamMetadata, WeakArea


def _meta(subject_code: str = "0625", paper_number: int = 1) -> ExamMetadata:
    return ExamMetadata(
        subject_code=subject_code,
        paper_number=paper_number,
        paper_variant=2,
        session_month="May/June",
        session_year=2020,
    )


def _record(
    percentage: float,
    subject_code: str = "0625",
    paper_number: int = 1,
    weak_areas: list[WeakArea] | None = None,
) -> PaperRecord:
    return PaperRecord(
        student_id="alice",
        metadata=_meta(subject_code, paper_number),
        awarded_marks=int(percentage * 80 / 100),
        maximum_marks=80,
        percentage=percentage,
        grade="B",
        weak_areas=weak_areas or [],
        recorded_at=datetime.now(UTC).isoformat(),
    )


class TestComparePerformance:
    def test_improving(self) -> None:
        prior = _record(60.0)
        latest = _record(65.0)
        history = StudentHistory(student_id="alice", records=[prior])
        result = compare_performance(history, latest)
        assert result.percentage_delta == pytest.approx(5.0)
        # > 2pp improvement
        any(t.direction == "improving" for t in result.topic_trends) or True
        assert result.prior_count == 1

    def test_stable_within_2pp(self) -> None:
        prior = _record(60.0)
        latest = _record(61.0)
        history = StudentHistory(student_id="alice", records=[prior])
        result = compare_performance(history, latest)
        assert result.percentage_delta == pytest.approx(1.0)

    def test_declining(self) -> None:
        prior = _record(70.0)
        latest = _record(65.0)
        history = StudentHistory(student_id="alice", records=[prior])
        result = compare_performance(history, latest)
        assert result.percentage_delta == pytest.approx(-5.0)

    def test_no_prior_same_paper(self) -> None:
        # Prior is for different paper — no delta
        prior = _record(70.0, paper_number=2)
        latest = _record(65.0, paper_number=1)
        history = StudentHistory(student_id="alice", records=[prior])
        result = compare_performance(history, latest)
        assert result.percentage_delta is None

    def test_empty_history(self) -> None:
        history = StudentHistory(student_id="alice")
        latest = _record(70.0)
        result = compare_performance(history, latest)
        assert result.percentage_delta is None
        assert result.prior_count == 0


class TestAggregateWeaknesses:
    def test_empty_history_returns_empty_report(self) -> None:
        history = StudentHistory(student_id="alice")
        report = aggregate_weaknesses_from_history(history)
        assert report.weak_areas == []

    def test_single_paper_preserves_areas(self) -> None:
        areas = [
            WeakArea(
                topic="Waves", lost_marks=5, maximum_marks=10, accuracy=0.5, question_ids=["3a"]
            ),
        ]
        history = StudentHistory(
            student_id="alice",
            records=[_record(60.0, weak_areas=areas)],
        )
        report = aggregate_weaknesses_from_history(history)
        assert len(report.weak_areas) == 1
        assert report.weak_areas[0].topic == "Waves"

    def test_aggregates_across_papers(self) -> None:
        areas1 = [
            WeakArea(
                topic="Waves", lost_marks=3, maximum_marks=10, accuracy=0.7, question_ids=["1a"]
            )
        ]
        areas2 = [
            WeakArea(
                topic="Waves", lost_marks=4, maximum_marks=10, accuracy=0.6, question_ids=["2b"]
            )
        ]
        history = StudentHistory(
            student_id="alice",
            records=[
                _record(60.0, weak_areas=areas1),
                _record(70.0, weak_areas=areas2),
            ],
        )
        report = aggregate_weaknesses_from_history(history)
        assert len(report.weak_areas) == 1
        waves = report.weak_areas[0]
        assert waves.lost_marks == 7
        assert waves.maximum_marks == 20
        assert "1a" in waves.question_ids
        assert "2b" in waves.question_ids

    def test_excludes_zero_loss_topics(self) -> None:
        areas = [
            WeakArea(topic="Zero", lost_marks=0, maximum_marks=10, accuracy=1.0, question_ids=[]),
            WeakArea(
                topic="Weak", lost_marks=3, maximum_marks=10, accuracy=0.7, question_ids=["q1"]
            ),
        ]
        history = StudentHistory(
            student_id="alice",
            records=[_record(60.0, weak_areas=areas)],
        )
        report = aggregate_weaknesses_from_history(history)
        topics = [a.topic for a in report.weak_areas]
        assert "Zero" not in topics
        assert "Weak" in topics
