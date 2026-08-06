"""Tests for the cohort analytics engine (``lemely.core.class_analytics``, P3.3).

Pure unit tests: no DB, no network, no wall clock — every scenario that cares
about "now" supplies its own fixed clock, mirroring ``tests/test_at_risk.py``.
Scenario names are chosen to match the P3.3 brief's acceptance bullets
directly, so a failing test names exactly which guarantee regressed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from lemely.core.class_analytics import (
    cohort_trend,
    engagement_stats,
    grade_distribution,
    per_paper_comparison,
    rank_topic_weaknesses,
    topic_student_heatmap,
)
from lemely.core.history import GRADE_ORDER, PaperOrigin, PaperRecord, StudentHistory
from lemely.core.schemas import ExamMetadata, WeakArea

_NOW = datetime(2026, 8, 6, 12, 0, 0, tzinfo=UTC)


def _meta(
    subject_code: str = "0625", paper_number: int = 3, paper_variant: int = 1
) -> ExamMetadata:
    return ExamMetadata(
        subject_code=subject_code,
        paper_number=paper_number,
        paper_variant=paper_variant,
        session_month="May/June",
        session_year=2020,
    )


def _area(topic: str, lost: int, maximum: int) -> WeakArea:
    accuracy = 1.0 - (lost / maximum) if maximum else 1.0
    return WeakArea(
        topic=topic, lost_marks=lost, maximum_marks=maximum, accuracy=accuracy, question_ids=[]
    )


def _record(
    student_id: str,
    percentage: float,
    *,
    grade: str = "B",
    weak_areas: list[WeakArea] | None = None,
    recorded_at: str | None = None,
    metadata: ExamMetadata | None = None,
    maximum_marks: int = 80,
    origin: PaperOrigin = "past_paper",
) -> PaperRecord:
    return PaperRecord(
        student_id=student_id,
        metadata=metadata if metadata is not None else _meta(),
        awarded_marks=round(percentage / 100 * maximum_marks),
        maximum_marks=maximum_marks,
        percentage=percentage,
        grade=grade,
        weak_areas=weak_areas or [],
        recorded_at=recorded_at if recorded_at is not None else _NOW.isoformat(),
        origin=origin,
    )


def _quiz(
    student_id: str,
    percentage: float,
    *,
    weak_areas: list[WeakArea] | None = None,
    recorded_at: str | None = None,
) -> PaperRecord:
    """A quiz record as the P3.5 marking path will write it (docs/quiz-model.md §5).

    ``grade=""`` is not incidental — a quiz has no grade boundaries, so the
    marking path never writes one. The helper exists so the quiz-exclusion
    tests below cannot accidentally pass by constructing a quiz that looks
    like a paper.
    """
    return _record(
        student_id,
        percentage,
        grade="",
        weak_areas=weak_areas,
        recorded_at=recorded_at,
        maximum_marks=10,
        origin="quiz",
    )


def _history(student_id: str, *records: PaperRecord) -> StudentHistory:
    return StudentHistory(student_id=student_id, records=list(records))


# ---------------------------------------------------------------------------
# rank_topic_weaknesses
# ---------------------------------------------------------------------------


def test_rank_topic_weaknesses_empty_cohort() -> None:
    assert rank_topic_weaknesses([]) == []


def test_rank_topic_weaknesses_single_student() -> None:
    history = _history(
        "alice",
        _record("alice", 60.0, weak_areas=[_area("Thermal physics", 10, 40)]),
    )
    ranked = rank_topic_weaknesses([history])
    assert len(ranked) == 1
    assert ranked[0].topic == "Thermal physics"
    assert ranked[0].lost_marks == 10
    assert ranked[0].maximum_marks == 40
    assert ranked[0].accuracy == 0.75
    assert ranked[0].student_ids == ["alice"]


def test_rank_topic_weaknesses_orders_by_lost_marks_descending() -> None:
    alice = _history("alice", _record("alice", 50.0, weak_areas=[_area("Waves", 20, 40)]))
    bob = _history("bob", _record("bob", 70.0, weak_areas=[_area("Optics", 5, 40)]))
    ranked = rank_topic_weaknesses([alice, bob])
    assert [w.topic for w in ranked] == ["Waves", "Optics"]


def test_rank_topic_weaknesses_ties_break_alphabetically_by_topic() -> None:
    """Equal total lost marks must sort deterministically, not by insertion order."""
    alice = _history("alice", _record("alice", 50.0, weak_areas=[_area("Zeta", 10, 40)]))
    bob = _history("bob", _record("bob", 50.0, weak_areas=[_area("Alpha", 10, 40)]))
    ranked = rank_topic_weaknesses([alice, bob])
    assert [w.topic for w in ranked] == ["Alpha", "Zeta"]


def test_rank_topic_weaknesses_excludes_all_zero_lost_topic() -> None:
    """A topic where the class-wide total lost marks is zero carries no signal."""
    history = _history(
        "alice",
        _record("alice", 100.0, weak_areas=[_area("Perfect topic", 0, 40)]),
    )
    assert rank_topic_weaknesses([history]) == []


def test_rank_topic_weaknesses_sums_lost_marks_across_multiple_records() -> None:
    history = _history(
        "alice",
        _record("alice", 60.0, weak_areas=[_area("Waves", 10, 40)]),
        _record("alice", 55.0, weak_areas=[_area("Waves", 8, 40)]),
    )
    ranked = rank_topic_weaknesses([history])
    assert ranked[0].lost_marks == 18
    assert ranked[0].maximum_marks == 80


# ---------------------------------------------------------------------------
# topic_student_heatmap
# ---------------------------------------------------------------------------


def test_heatmap_cell_is_none_for_a_student_with_no_data_for_a_ranked_topic() -> None:
    """A student who never touched a ranked topic gets None, never 0%."""
    alice = _history("alice", _record("alice", 50.0, weak_areas=[_area("Waves", 20, 40)]))
    bob = _history("bob", _record("bob", 90.0, weak_areas=[]))  # no weak areas at all
    ranked = rank_topic_weaknesses([alice, bob])
    cells = topic_student_heatmap([alice, bob], ranked)

    bob_cell = next(c for c in cells if c.student_id == "bob" and c.topic == "Waves")
    assert bob_cell.accuracy is None

    alice_cell = next(c for c in cells if c.student_id == "alice" and c.topic == "Waves")
    assert alice_cell.accuracy == 0.5


def test_heatmap_restricted_to_ranked_topics_only() -> None:
    """A topic with zero cohort-wide lost marks (unranked) has no heatmap row."""
    history = _history(
        "alice",
        _record(
            "alice",
            80.0,
            weak_areas=[_area("Waves", 10, 40), _area("Perfect topic", 0, 40)],
        ),
    )
    ranked = rank_topic_weaknesses([history])
    cells = topic_student_heatmap([history], ranked)
    topics_in_heatmap = {c.topic for c in cells}
    assert topics_in_heatmap == {"Waves"}


def test_heatmap_empty_cohort() -> None:
    assert topic_student_heatmap([], []) == []


# ---------------------------------------------------------------------------
# grade_distribution
# ---------------------------------------------------------------------------


def test_grade_distribution_includes_zero_buckets_for_the_full_ladder() -> None:
    history = _history("alice", _record("alice", 90.0, grade="A*"))
    distribution = grade_distribution([history])
    assert [b.grade for b in distribution] == GRADE_ORDER
    counts = {b.grade: b.count for b in distribution}
    assert counts["A*"] == 1
    assert counts["U"] == 0


def test_grade_distribution_empty_cohort_is_all_zero_buckets() -> None:
    distribution = grade_distribution([])
    assert all(b.count == 0 for b in distribution)
    assert len(distribution) == len(GRADE_ORDER)


def test_grade_distribution_ignores_student_with_no_records() -> None:
    history = _history("alice")  # no records at all
    distribution = grade_distribution([history])
    assert all(b.count == 0 for b in distribution)


# ---------------------------------------------------------------------------
# cohort_trend
# ---------------------------------------------------------------------------


def test_cohort_trend_empty_cohort() -> None:
    assert cohort_trend([]) == []


def test_cohort_trend_single_student_single_point() -> None:
    history = _history("alice", _record("alice", 70.0, recorded_at=_NOW.isoformat()))
    points = cohort_trend([history])
    assert len(points) == 1
    assert points[0].mean_percentage == 70.0
    assert points[0].sample_size == 1


def test_cohort_trend_sparse_irregular_timestamps_never_interpolates() -> None:
    """A gap where nobody submitted produces no synthetic point in between."""
    t1 = _NOW.isoformat()
    t2 = (_NOW + timedelta(days=40)).isoformat()  # a large, irregular gap
    alice = _history("alice", _record("alice", 60.0, recorded_at=t1))
    bob = _history("bob", _record("bob", 80.0, recorded_at=t2))
    points = cohort_trend([alice, bob])

    assert [p.timestamp for p in points] == [t1, t2]
    # First point: only alice has submitted -> mean is just alice's percentage.
    assert points[0].mean_percentage == 60.0
    assert points[0].sample_size == 1
    # Second point: both have submitted by now (alice's earlier paper still
    # counts as her most-recent-as-of-t2) -> running cohort mean of both.
    assert points[1].mean_percentage == 70.0
    assert points[1].sample_size == 2


def test_cohort_trend_uses_each_students_most_recent_percentage_at_each_point() -> None:
    t1 = _NOW.isoformat()
    t2 = (_NOW + timedelta(days=5)).isoformat()
    alice = _history(
        "alice",
        _record("alice", 60.0, recorded_at=t1),
        _record("alice", 90.0, recorded_at=t2),
    )
    points = cohort_trend([alice])
    assert points[0].mean_percentage == 60.0
    assert points[1].mean_percentage == 90.0


# ---------------------------------------------------------------------------
# per_paper_comparison
# ---------------------------------------------------------------------------


def test_per_paper_comparison_empty_cohort() -> None:
    assert per_paper_comparison([]) == []


def test_per_paper_comparison_groups_by_subject_paper_variant() -> None:
    alice = _history(
        "alice",
        _record("alice", 60.0, metadata=_meta("0625", 3, 1)),
        _record("alice", 80.0, metadata=_meta("0625", 4, 2)),
    )
    bob = _history("bob", _record("bob", 70.0, metadata=_meta("0625", 3, 1)))
    comparisons = per_paper_comparison([alice, bob])

    assert len(comparisons) == 2
    paper_31 = next(c for c in comparisons if c.paper_id == "0625/31")
    assert paper_31.attempt_count == 2
    assert paper_31.student_count == 2
    assert paper_31.mean_percentage == 65.0

    paper_42 = next(c for c in comparisons if c.paper_id == "0625/42")
    assert paper_42.attempt_count == 1
    assert paper_42.student_count == 1


def test_per_paper_comparison_sorted_deterministically() -> None:
    alice = _history(
        "alice",
        _record("alice", 60.0, metadata=_meta("0625", 4, 1)),
        _record("alice", 60.0, metadata=_meta("0620", 1, 1)),
    )
    comparisons = per_paper_comparison([alice])
    assert [c.subject_code for c in comparisons] == ["0620", "0625"]


# ---------------------------------------------------------------------------
# engagement_stats
# ---------------------------------------------------------------------------


def test_engagement_stats_empty_cohort() -> None:
    stats = engagement_stats([], now=_NOW)
    assert stats.submissions_last_7_days == 0
    assert stats.submissions_last_30_days == 0
    assert stats.active_students_last_7_days == 0
    assert stats.active_students_last_30_days == 0
    assert stats.never_active_count == 0
    assert stats.median_days_since_last_submission is None


def test_engagement_stats_student_with_zero_records_is_never_active() -> None:
    history = _history("alice")
    stats = engagement_stats([history], now=_NOW)
    assert stats.never_active_count == 1
    assert stats.active_students_last_7_days == 0
    assert stats.median_days_since_last_submission is None


def test_engagement_stats_7_day_boundary() -> None:
    """day 6 is inside the 7-day window; day 7 is not (strictly-less-than)."""
    inside = _history(
        "inside", _record("inside", 70.0, recorded_at=(_NOW - timedelta(days=6)).isoformat())
    )
    outside = _history(
        "outside", _record("outside", 70.0, recorded_at=(_NOW - timedelta(days=7)).isoformat())
    )
    stats = engagement_stats([inside, outside], now=_NOW)
    assert stats.active_students_last_7_days == 1
    assert stats.submissions_last_7_days == 1


def test_engagement_stats_30_day_boundary() -> None:
    inside = _history(
        "inside", _record("inside", 70.0, recorded_at=(_NOW - timedelta(days=29)).isoformat())
    )
    outside = _history(
        "outside", _record("outside", 70.0, recorded_at=(_NOW - timedelta(days=30)).isoformat())
    )
    stats = engagement_stats([inside, outside], now=_NOW)
    assert stats.active_students_last_30_days == 1
    assert stats.submissions_last_30_days == 1


def test_engagement_stats_median_days_since_last_submission() -> None:
    a = _history("a", _record("a", 70.0, recorded_at=(_NOW - timedelta(days=2)).isoformat()))
    b = _history("b", _record("b", 70.0, recorded_at=(_NOW - timedelta(days=10)).isoformat()))
    c = _history("c", _record("c", 70.0, recorded_at=(_NOW - timedelta(days=20)).isoformat()))
    stats = engagement_stats([a, b, c], now=_NOW)
    assert stats.median_days_since_last_submission == 10.0


def test_engagement_stats_unparseable_timestamp_excluded_from_median_not_never_active() -> None:
    """A record with a naive/unparseable timestamp cannot assert a recency, but
    the student did submit, so they are not counted as never-active."""
    history = _history("alice", _record("alice", 70.0, recorded_at="not-a-timestamp"))
    stats = engagement_stats([history], now=_NOW)
    assert stats.never_active_count == 0
    assert stats.median_days_since_last_submission is None
    assert stats.submissions_last_7_days == 0


# ---------------------------------------------------------------------------
# P3.5 chunk G — grade-bearing vs topic-bearing (docs/quiz-model.md §5)
#
# Quiz attempts must feed topic analytics ("results feed analytics", MISSION
# §4) and must not feed grade or paper-comparison analytics. Each test below
# pins one row of that table, so a regression names the exact guarantee lost
# rather than "analytics changed".
# ---------------------------------------------------------------------------


def test_grade_distribution_ignores_quiz_attempts() -> None:
    """A quiz has no grade, so it cannot move a grade bucket.

    Alice's only paper graded a B. Adding a later quiz must leave her counted
    on B — not moved to an empty-string bucket, and not dropped entirely
    because "her latest record has no grade".
    """
    history = _history(
        "alice",
        _record("alice", 72.0, grade="B", recorded_at="2026-01-01T00:00:00+00:00"),
        _quiz("alice", 40.0, recorded_at="2026-02-01T00:00:00+00:00"),
    )
    counts = {bucket.grade: bucket.count for bucket in grade_distribution([history])}
    assert counts["B"] == 1
    assert sum(counts.values()) == 1


def test_grade_distribution_quiz_only_student_has_no_grade_bucket() -> None:
    """A student who has only ever done quizzes has no grade to report — and
    is counted nowhere rather than being assigned a default or a zero."""
    history = _history("alice", _quiz("alice", 90.0))
    counts = {bucket.grade: bucket.count for bucket in grade_distribution([history])}
    assert sum(counts.values()) == 0


def test_cohort_trend_ignores_quiz_attempts() -> None:
    """A quiz percentage is not on the same scale as a paper percentage.

    A 40% quiz between two 70% papers must not create a third trend point or
    drag the cohort mean down — the series must be identical to the one the
    two papers alone produce.
    """
    papers_only = _history(
        "alice",
        _record("alice", 70.0, recorded_at="2026-01-01T00:00:00+00:00"),
        _record("alice", 70.0, recorded_at="2026-03-01T00:00:00+00:00"),
    )
    with_quiz = _history(
        "alice",
        _record("alice", 70.0, recorded_at="2026-01-01T00:00:00+00:00"),
        _quiz("alice", 40.0, recorded_at="2026-02-01T00:00:00+00:00"),
        _record("alice", 70.0, recorded_at="2026-03-01T00:00:00+00:00"),
    )
    assert cohort_trend([with_quiz]) == cohort_trend([papers_only])
    assert [p.mean_percentage for p in cohort_trend([with_quiz])] == [70.0, 70.0]


def test_per_paper_comparison_ignores_quiz_attempts() -> None:
    """A quiz carries synthetic paper metadata (§4.3) that is never persisted.

    Grouping on it would invent a paper row that does not exist. Only the real
    paper may appear.
    """
    history = _history(
        "alice",
        _record("alice", 70.0, metadata=_meta("0580", 2, 1)),
        _quiz("alice", 40.0),
    )
    comparisons = per_paper_comparison([history])
    assert [c.paper_id for c in comparisons] == ["0580/21"]
    assert comparisons[0].attempt_count == 1


def test_rank_topic_weaknesses_includes_quiz_attempts() -> None:
    """A weakness is a weakness whatever revealed it — quizzes feed topic
    analytics, which is the whole point of assigning them."""
    history = _history("alice", _quiz("alice", 40.0, weak_areas=[_area("Vectors", 6, 10)]))
    ranked = rank_topic_weaknesses([history])
    assert [(w.topic, w.lost_marks) for w in ranked] == [("Vectors", 6)]


def test_topic_student_heatmap_includes_quiz_attempts() -> None:
    """The heatmap is topic-bearing, so a quiz-only student still gets a real
    accuracy cell rather than the ``None`` that means "no data"."""
    history = _history("alice", _quiz("alice", 40.0, weak_areas=[_area("Vectors", 6, 10)]))
    ranked = rank_topic_weaknesses([history])
    cells = topic_student_heatmap([history], ranked)
    assert [(c.topic, c.student_id, c.accuracy) for c in cells] == [("Vectors", "alice", 0.4)]


def test_engagement_stats_counts_quiz_attempts_as_activity() -> None:
    """A quiz is activity. A student who did a quiz yesterday is active and is
    not "never active", however long since their last full paper."""
    history = _history(
        "alice", _quiz("alice", 40.0, recorded_at=(_NOW - timedelta(days=1)).isoformat())
    )
    stats = engagement_stats([history], now=_NOW)
    assert stats.never_active_count == 0
    assert stats.submissions_last_7_days == 1
    assert stats.active_students_last_7_days == 1
