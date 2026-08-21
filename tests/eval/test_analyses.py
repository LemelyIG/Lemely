"""Unit tests for lemely.eval.analyses's six pure analysis functions (spec §3.3)."""

from __future__ import annotations

from lemely.eval.analyses import (
    ablation_2x2,
    exclusion_funnel,
    mcnemar,
    review_rate,
    risk_coverage,
    wilson,
)
from lemely.eval.records import EvalRecord


def _rec(**overrides: object) -> EvalRecord:
    base: dict[str, object] = {
        "run_id": "run-1",
        "arm": "extract+mark",
        "paper_id": "p1",
        "fixture_variant": None,
        "question_id": "1",
        "mark_point_id": None,
        "parse_path": "det",
        "predicted_marks": 2,
        "truth_marks": 2,
        "outcome": "correct",
        "extraction_conf": 0.9,
        "marker_conf": 0.95,
        "id_match": "exact",
        "triggers": [],
    }
    base.update(overrides)
    return EvalRecord(**base)  # type: ignore[arg-type]


class TestAblation2x2:
    def test_cross_tabulates_outcomes_per_question(self) -> None:
        records = [
            # both correct
            _rec(arm="oracle+mark", question_id="1", outcome="correct"),
            _rec(arm="extract+mark", question_id="1", outcome="correct"),
            # extraction-attributable: oracle correct, extract wrong
            _rec(arm="oracle+mark", question_id="2", outcome="correct"),
            _rec(arm="extract+mark", question_id="2", outcome="under"),
            # marking-attributable: both wrong
            _rec(arm="oracle+mark", question_id="3", outcome="under"),
            _rec(arm="extract+mark", question_id="3", outcome="over"),
            # masked: oracle wrong, extract correct
            _rec(arm="oracle+mark", question_id="4", outcome="under"),
            _rec(arm="extract+mark", question_id="4", outcome="correct"),
        ]
        result = ablation_2x2(records)
        assert result == {
            "both_correct": 1,
            "extraction_attributable": 1,
            "marking_attributable": 1,
            "masked": 1,
        }

    def test_empty_input_returns_all_zero_buckets(self) -> None:
        result = ablation_2x2([])
        assert result == {
            "both_correct": 0,
            "extraction_attributable": 0,
            "marking_attributable": 0,
            "masked": 0,
        }

    def test_excludes_point_level_rows(self) -> None:
        records = [
            _rec(arm="oracle+mark", question_id="1", outcome="correct"),
            _rec(arm="extract+mark", question_id="1", outcome="correct"),
            # point-level rows for the same question — must not double count
            _rec(arm="oracle+mark", question_id="1", mark_point_id="1a", outcome="correct"),
            _rec(arm="extract+mark", question_id="1", mark_point_id="1a", outcome="correct"),
        ]
        result = ablation_2x2(records)
        assert result["both_correct"] == 1


class TestMcnemar:
    def test_discordant_pairs_produce_nonzero_statistic(self) -> None:
        records = [
            _rec(arm="oracle+mark", question_id="1", outcome="correct"),
            _rec(arm="extract+mark", question_id="1", outcome="under"),
            _rec(arm="oracle+mark", question_id="2", outcome="correct"),
            _rec(arm="extract+mark", question_id="2", outcome="under"),
            _rec(arm="oracle+mark", question_id="3", outcome="correct"),
            _rec(arm="extract+mark", question_id="3", outcome="correct"),
        ]
        result = mcnemar(records)
        assert result["b"] == 2
        assert result["c"] == 0
        assert result["chi2"] > 0
        assert 0.0 <= result["p_value"] <= 1.0

    def test_no_discordant_pairs_gives_zero_statistic(self) -> None:
        records = [
            _rec(arm="oracle+mark", question_id="1", outcome="correct"),
            _rec(arm="extract+mark", question_id="1", outcome="correct"),
        ]
        result = mcnemar(records)
        assert result["b"] == 0
        assert result["c"] == 0
        assert result["chi2"] == 0.0
        assert result["p_value"] == 1.0

    def test_collapses_duplicate_mark_point_rows_to_one_leaf(self) -> None:
        # Same question_id repeated at mark-point level must not inflate n.
        records = [
            _rec(arm="oracle+mark", question_id="1", outcome="correct"),
            _rec(arm="extract+mark", question_id="1", outcome="under"),
            _rec(
                arm="oracle+mark",
                question_id="1",
                mark_point_id="1a",
                outcome="correct",
            ),
            _rec(
                arm="extract+mark",
                question_id="1",
                mark_point_id="1a",
                outcome="under",
            ),
        ]
        result = mcnemar(records)
        assert result["n_pairs"] == 1


class TestWilson:
    def test_happy_path_interval_contains_point_estimate(self) -> None:
        records = [_rec(question_id=str(i), outcome="correct") for i in range(8)] + [
            _rec(question_id=str(i), outcome="under") for i in range(8, 10)
        ]
        result = wilson(records)
        assert result["n"] == 10
        assert result["point"] == 0.8
        assert result["lower"] < result["point"] < result["upper"]
        assert 0.0 <= result["lower"] <= result["upper"] <= 1.0

    def test_zero_count_denominator_returns_full_uncertainty(self) -> None:
        result = wilson([])
        assert result["n"] == 0
        assert result["lower"] == 0.0
        assert result["upper"] == 1.0

    def test_excludes_excluded_outcome_from_denominator(self) -> None:
        records = [
            _rec(question_id="1", outcome="correct"),
            _rec(question_id="2", outcome="excluded"),
        ]
        result = wilson(records)
        assert result["n"] == 1


class TestRiskCoverage:
    def test_happy_path_curve_is_monotonic_in_coverage(self) -> None:
        records = [
            _rec(question_id="1", marker_conf=0.95, outcome="correct"),
            _rec(question_id="2", marker_conf=0.85, outcome="correct"),
            _rec(question_id="3", marker_conf=0.60, outcome="under"),
        ]
        points = risk_coverage(records)
        assert [p["coverage"] for p in points] == [
            round(1 / 3, 10),
            round(2 / 3, 10),
            1.0,
        ]
        assert points[-1]["risk"] == round(1 / 3, 10)

    def test_empty_input_returns_empty_curve(self) -> None:
        assert risk_coverage([]) == []

    def test_records_without_marker_conf_are_excluded(self) -> None:
        records = [
            _rec(question_id="1", marker_conf=None, outcome="correct"),
            _rec(question_id="2", marker_conf=0.9, outcome="correct"),
        ]
        points = risk_coverage(records)
        assert len(points) == 1


class TestExclusionFunnel:
    def test_scored_denominator_excludes_never_attempted(self) -> None:
        records = [
            _rec(question_id="1", outcome="correct"),
            _rec(question_id="2", outcome="over"),
            _rec(question_id="3", outcome="abstain"),
            _rec(question_id="4", outcome="unmatched"),
            _rec(question_id="5", outcome="excluded"),
        ]
        result = exclusion_funnel(records)
        assert result["total"] == 5
        assert result["excluded"] == 1
        assert result["scored"] == 4

    def test_empty_input(self) -> None:
        result = exclusion_funnel([])
        assert result["total"] == 0
        assert result["scored"] == 0
        assert result["excluded"] == 0

    def test_by_outcome_breakdown(self) -> None:
        records = [
            _rec(question_id="1", outcome="correct"),
            _rec(question_id="2", outcome="correct"),
            _rec(question_id="3", outcome="excluded"),
        ]
        result = exclusion_funnel(records)
        assert result["by_outcome"]["correct"] == 2
        assert result["by_outcome"]["excluded"] == 1


class TestReviewRate:
    def test_two_denominators_signal_vs_total(self) -> None:
        records = [
            _rec(question_id="1", paper_id="p1", triggers=["low_confidence"]),
            _rec(question_id="2", paper_id="p1", triggers=["random_audit"]),
            _rec(question_id="3", paper_id="p1", triggers=[]),
            _rec(question_id="4", paper_id="p1", triggers=[]),
        ]
        result = review_rate(records)
        assert result["n"] == 4
        assert result["review_rate_signal"] == 0.25
        assert result["review_rate_total"] == 0.5

    def test_empty_input_reports_zero_with_zero_n(self) -> None:
        result = review_rate([])
        assert result["n"] == 0
        assert result["review_rate_signal"] == 0.0
        assert result["review_rate_total"] == 0.0
        assert result["per_paper_p95"] == 0.0

    def test_per_paper_p95_reflects_worst_paper(self) -> None:
        records = [
            _rec(question_id="1", paper_id="p1", triggers=["low_confidence"]),
            _rec(question_id="2", paper_id="p1", triggers=[]),
            _rec(question_id="3", paper_id="p2", triggers=[]),
            _rec(question_id="4", paper_id="p2", triggers=[]),
        ]
        result = review_rate(records)
        # p1: 1/2 = 0.5, p2: 0/2 = 0.0 — p95 across two papers is dominated by
        # the worst one.
        assert result["per_paper_p95"] == 0.5


class TestQuestionLevelFiltering:
    def test_mixed_question_and_point_level_rows_exclude_points(self) -> None:
        records = [
            _rec(question_id="1", outcome="correct"),
            _rec(question_id="1", mark_point_id="1a", outcome="correct"),
            _rec(question_id="1", mark_point_id="1b", outcome="under"),
        ]
        result = wilson(records)
        assert result["n"] == 1

        funnel = exclusion_funnel(records)
        assert funnel["total"] == 1
