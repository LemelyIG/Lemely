"""Unit tests for lemely.eval.analyses's six pure analysis functions (spec §3.3)."""

from __future__ import annotations

import random
from pathlib import Path

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

    def test_collapses_duplicate_question_level_rows_to_one_leaf(self) -> None:
        # Two question-level rows for the SAME (paper_id, question_id) leaf —
        # e.g. a fixture_variant duplicate — must not inflate n_pairs. This
        # exercises _distinct_leaves_by_arm's collapsing directly: both rows
        # are already question-level (mark_point_id=None), so a no-op
        # "first one seen" collapse would also pass this — the assertion
        # that catches the real defect is in TestDistinctLeafDA6 below.
        records = [
            _rec(arm="oracle+mark", question_id="1", fixture_variant="correct", outcome="correct"),
            _rec(arm="extract+mark", question_id="1", fixture_variant="correct", outcome="under"),
            _rec(arm="oracle+mark", question_id="1", fixture_variant="wrong", outcome="correct"),
            _rec(arm="extract+mark", question_id="1", fixture_variant="wrong", outcome="under"),
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


class TestDistinctLeafDA6:
    """DA6 (BUILD/DECISIONS.md): a leaf's outcome is derived from ALL of its
    variant/duplicate records, never sampled from them. A leaf counts as
    ``correct`` iff EVERY scored record for that leaf is ``correct``.
    """

    def test_unanimous_correct_variants_count_as_correct(self) -> None:
        records = [
            _rec(paper_id="p1", question_id="1", fixture_variant="correct", outcome="correct"),
            _rec(paper_id="p1", question_id="1", fixture_variant="partial", outcome="correct"),
        ]
        result = wilson(records)
        assert result["n"] == 1
        assert result["successes"] == 1

    def test_one_wrong_variant_prevents_the_leaf_counting_as_correct(self) -> None:
        # The sort-order trap: variants sort correct < partial < wrong, so a
        # naive "keep the first" collapse would represent this leaf by its
        # correct record and inflate accuracy. It must not.
        records = [
            _rec(paper_id="p1", question_id="1", fixture_variant="correct", outcome="correct"),
            _rec(paper_id="p1", question_id="1", fixture_variant="wrong", outcome="under"),
        ]
        result = wilson(records)
        assert result["n"] == 1
        assert result["successes"] == 0

    def test_collapse_is_order_independent(self) -> None:
        base = [
            _rec(paper_id="p1", question_id="1", fixture_variant="correct", outcome="correct"),
            _rec(paper_id="p1", question_id="1", fixture_variant="partial", outcome="under"),
            _rec(paper_id="p1", question_id="1", fixture_variant="wrong", outcome="over"),
            _rec(paper_id="p2", question_id="1", fixture_variant="correct", outcome="correct"),
        ]
        baseline = wilson(base)
        shuffled = list(base)
        rng = random.Random(42)
        for _ in range(20):
            rng.shuffle(shuffled)
            assert wilson(shuffled) == baseline

    def test_collapse_is_order_independent_under_a_full_tie_on_the_sort_key(self) -> None:
        """Two records that tie on every field the old sort key looked at
        (fixture_variant, mark_point_id, run_id, arm, outcome) but differ in
        marker_conf/triggers must still produce an order-independent result —
        the representative choice must be a content-derived total order, never
        "whichever tied record came first in the input list"."""
        r_high_conf = _rec(
            paper_id="p1",
            question_id="1",
            fixture_variant=None,
            outcome="under",
            marker_conf=0.9,
            triggers=["low_confidence"],
        )
        r_low_conf = _rec(
            paper_id="p1",
            question_id="1",
            fixture_variant=None,
            outcome="under",
            marker_conf=0.5,
            triggers=[],
        )
        forward = risk_coverage([r_high_conf, r_low_conf])
        backward = risk_coverage([r_low_conf, r_high_conf])
        assert forward == backward

        # Property-style: shuffle a tie-containing group many times and
        # confirm the collapsed representative's full field set (not just
        # the analysis output) is identical every time.
        from lemely.eval.analyses import _distinct_leaves

        group = [r_high_conf, r_low_conf]
        rng = random.Random(7)
        first = _distinct_leaves(group)
        for _ in range(30):
            rng.shuffle(group)
            assert _distinct_leaves(group) == first


class TestDistinctLeavesOverRealGoldenCorpus:
    def test_wilson_n_is_30_distinct_leaves(self) -> None:
        """Verified against the corpus (BUILD/DECISIONS.md DA6): 11 golden case
        dirs hold 70 answer rows (M0.8/#32 added the 11th, ``_theory_nested``,
        contributing 2 leaves with no fixture-variant suffix to collapse);
        stripping the _correct/_partial/_wrong fixture-variant suffix
        collapses them to 30 distinct (paper, question) leaves. This
        supersedes the pre-#32 baseline of 68 rows / 28 leaves — do not cite
        28 as the current distinct-leaf count."""
        from lemely.accuracy.harness import load_golden_cases

        golden_dir = Path(__file__).resolve().parents[1] / "golden"
        cases = load_golden_cases(golden_dir)
        assert cases, "expected golden fixtures under tests/golden"

        records = [
            _rec(
                paper_id=case.paper_id,
                fixture_variant=case.fixture_variant,
                question_id=qid,
                outcome="correct",
            )
            for case in cases
            for qid in case.ground_truth
        ]
        assert len(records) == 70
        result = wilson(records)
        assert result["n"] == 30

    def test_exclusion_funnel_scored_count_matches_wilson_n(self) -> None:
        """DA6a invariant (BUILD/DECISIONS.md): exclusion_funnel exists to
        *explain* wilson's denominator, so its scored-leaf count must equal
        the ``n`` wilson actually used on the same records — never disagree
        with it. Regression for the case where one fixture variant of a leaf
        failed extraction (``excluded``) while another variant of the SAME
        leaf was scored ``correct``: the leaf as a whole was attempted (one
        variant proves it), so it must count as scored, not excluded, in
        BOTH analyses.

        Built over the real tests/golden corpus: the ``correct``/``partial``
        variants of each multi-variant paper are marked ``correct``, the
        ``wrong`` variant of the SAME leaves is marked ``excluded`` (as if
        that one variant's extraction failed). Every leaf has at least one
        scored record, so wilson's n must be 30 (M0.8/#32 raised this from
        the pre-#32 baseline of 28 — see the docstring on the sibling test
        above), and the funnel's scored count must equal it exactly."""
        from lemely.accuracy.harness import load_golden_cases

        golden_dir = Path(__file__).resolve().parents[1] / "golden"
        cases = load_golden_cases(golden_dir)
        assert cases, "expected golden fixtures under tests/golden"

        records = [
            _rec(
                paper_id=case.paper_id,
                fixture_variant=case.fixture_variant,
                question_id=qid,
                outcome="excluded" if case.fixture_variant == "wrong" else "correct",
            )
            for case in cases
            for qid in case.ground_truth
        ]
        assert len(records) == 70

        wilson_result = wilson(records)
        funnel_result = exclusion_funnel(records)

        assert wilson_result["n"] == 30
        assert funnel_result["scored"] == wilson_result["n"]


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
