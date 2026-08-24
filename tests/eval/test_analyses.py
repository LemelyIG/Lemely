"""Unit tests for lemely.eval.analyses's six pure analysis functions (spec §3.3)."""

from __future__ import annotations

import inspect
import json
import math
import random
from pathlib import Path

import pytest

from lemely.eval.analyses import (
    MCNEMAR_IMPROVEMENT_N_FLOOR,
    ablation_2x2,
    coherence_trigger_rate,
    exclusion_funnel,
    mcnemar,
    mcnemar_improvement_p_value,
    paired_proportion_min_n,
    paper_grade_confidence,
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


def _concordant_filler_pairs(n: int) -> list[EvalRecord]:
    """``n`` extra concordant (both-correct) leaf pairs, to push ``n_pairs``
    at/above :data:`MCNEMAR_IMPROVEMENT_N_FLOOR` without disturbing ``b``/``c``."""
    records: list[EvalRecord] = []
    for i in range(n):
        qid = f"filler-{i}"
        records.append(_rec(arm="oracle+mark", question_id=qid, outcome="correct"))
        records.append(_rec(arm="extract+mark", question_id=qid, outcome="correct"))
    return records


class TestMcnemar:
    def test_discordant_pairs_produce_nonzero_statistic(self) -> None:
        # Padded to n_pairs >= MCNEMAR_IMPROVEMENT_N_FLOOR with concordant filler so this
        # exercises the numeric (non-underpowered) branch's chi2/p_value math.
        records = [
            *_concordant_filler_pairs(MCNEMAR_IMPROVEMENT_N_FLOOR),
            _rec(arm="oracle+mark", question_id="1", outcome="correct"),
            _rec(arm="extract+mark", question_id="1", outcome="under"),
            _rec(arm="oracle+mark", question_id="2", outcome="correct"),
            _rec(arm="extract+mark", question_id="2", outcome="under"),
            _rec(arm="oracle+mark", question_id="3", outcome="correct"),
            _rec(arm="extract+mark", question_id="3", outcome="correct"),
        ]
        result = mcnemar(records)
        assert result["underpowered"] is False
        assert result["b"] == 2
        assert result["c"] == 0
        assert result["chi2"] is not None and result["chi2"] > 0
        assert result["p_value"] is not None and 0.0 <= result["p_value"] <= 1.0

    def test_no_discordant_pairs_gives_zero_statistic(self) -> None:
        records = [
            *_concordant_filler_pairs(MCNEMAR_IMPROVEMENT_N_FLOOR),
            _rec(arm="oracle+mark", question_id="1", outcome="correct"),
            _rec(arm="extract+mark", question_id="1", outcome="correct"),
        ]
        result = mcnemar(records)
        assert result["underpowered"] is False
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


class TestNFloor:
    """M0.6 (#30): a McNemar result below the paired-comparison n-floor must
    report ``underpowered`` rather than a numeric p-value/statistic (spec
    §6: n=219 to detect 83.8%->88.8% at alpha=0.05/power=0.80)."""

    def test_below_floor_still_returns_numeric_statistic(self) -> None:
        """Real ~31-leaf golden corpus, replayed as paired oracle/extract
        arms — an order of magnitude below MCNEMAR_IMPROVEMENT_N_FLOOR (spec
        §6's own example of exactly this population). The floor governs
        whether the result may be PRESENTED as an improvement claim (see
        TestReportingLayer below), not whether the statistic gets computed
        at all: ``chi2``/``p_value`` must be real floats even here."""
        from lemely.accuracy.harness import load_golden_cases

        golden_dir = Path(__file__).resolve().parents[1] / "golden"
        cases = load_golden_cases(golden_dir)
        assert cases, "expected golden fixtures under tests/golden"

        records = [
            _rec(
                arm=arm,
                paper_id=case.paper_id,
                fixture_variant=case.fixture_variant,
                question_id=qid,
                outcome="correct" if arm == "oracle+mark" else "under",
            )
            for case in cases
            for qid in case.ground_truth
            for arm in ("oracle+mark", "extract+mark")
        ]
        result = mcnemar(records)
        assert result["n_pairs"] < MCNEMAR_IMPROVEMENT_N_FLOOR
        assert result["underpowered"] is True
        assert result["b"] == 31
        assert result["c"] == 0
        assert isinstance(result["chi2"], float)
        assert isinstance(result["p_value"], float)
        assert result["chi2"] is not None
        assert result["p_value"] is not None

    def test_at_or_above_floor_returns_numeric_result(self) -> None:
        """Synthetic paired data with n_pairs >= MCNEMAR_IMPROVEMENT_N_FLOOR — no real
        corpus reaches this yet — proves the underpowered branch is a real
        branch, not vacuously always-true."""
        records = []
        for i in range(MCNEMAR_IMPROVEMENT_N_FLOOR):
            qid = f"q{i}"
            oracle_outcome = "correct"
            extract_outcome = "under" if i % 5 == 0 else "correct"
            records.append(_rec(arm="oracle+mark", question_id=qid, outcome=oracle_outcome))
            records.append(_rec(arm="extract+mark", question_id=qid, outcome=extract_outcome))

        result = mcnemar(records)
        assert result["n_pairs"] == MCNEMAR_IMPROVEMENT_N_FLOOR
        assert result["underpowered"] is False
        assert isinstance(result["chi2"], float)
        assert isinstance(result["p_value"], float)
        assert 0.0 <= result["p_value"] <= 1.0

    def test_paired_proportion_min_n_pinned_value_and_monotonicity(self) -> None:
        """`paired_proportion_min_n` implements the Connor/Fleiss
        favourable-case bound: the discordant-pair proportion is set to its
        minimum possible value (psi = d = |p2 - p1|, i.e. every discordant
        pair moves p1->p2 and none reverse), giving

            n = ceil((z_a*sqrt(d) + z_b*sqrt(d*(1-d)))**2 / d**2)

        This pins the exact value for spec §6's effect size (83.8% ->
        88.8%, alpha=0.05, power=0.80), recomputed independently here from
        the module's own ``_inverse_normal_cdf`` rather than asserting a
        bare literal, plus the monotonicity any real bound must have:
        a bigger effect size needs fewer pairs, and more power needs more."""
        from lemely.eval.analyses import _inverse_normal_cdf

        def expected(p1: float, p2: float, alpha: float, power: float) -> int:
            z_alpha = _inverse_normal_cdf(1 - alpha / 2)
            z_beta = _inverse_normal_cdf(power)
            d = abs(p2 - p1)
            return math.ceil((z_alpha * math.sqrt(d) + z_beta * math.sqrt(d * (1 - d))) ** 2 / d**2)

        pinned = expected(0.838, 0.888, alpha=0.05, power=0.80)
        assert paired_proportion_min_n(0.838, 0.888, alpha=0.05, power=0.80) == pinned
        assert 0 < pinned <= MCNEMAR_IMPROVEMENT_N_FLOOR

        # Larger effect size -> strictly smaller n.
        bigger_effect = paired_proportion_min_n(0.75, 0.888, alpha=0.05, power=0.80)
        assert bigger_effect < pinned

        # Higher power -> strictly larger n.
        higher_power = paired_proportion_min_n(0.838, 0.888, alpha=0.05, power=0.90)
        assert higher_power > pinned


class TestReportingLayer:
    """M0.6 (#30): the refusal to present a bare p-value as an improvement
    claim below the n-floor lives ONLY in this reporting-layer function —
    ``mcnemar()`` itself always returns the numeric statistic (see
    TestNFloor.test_below_floor_still_returns_numeric_statistic)."""

    def test_underpowered_result_returns_the_sentinel(self) -> None:
        result = mcnemar(
            [
                _rec(arm="oracle+mark", question_id="1", outcome="correct"),
                _rec(arm="extract+mark", question_id="1", outcome="under"),
            ]
        )
        assert result["underpowered"] is True
        reported = mcnemar_improvement_p_value(result)
        assert reported == "underpowered"

    def test_powered_result_returns_the_numeric_p_value(self) -> None:
        records = [
            *_concordant_filler_pairs(MCNEMAR_IMPROVEMENT_N_FLOOR),
            _rec(arm="oracle+mark", question_id="1", outcome="correct"),
            _rec(arm="extract+mark", question_id="1", outcome="under"),
        ]
        result = mcnemar(records)
        assert result["underpowered"] is False
        reported = mcnemar_improvement_p_value(result)
        assert reported == result["p_value"]
        assert isinstance(reported, float)


def test_mcnemar_signature_rejects_unpaired_rate_summaries() -> None:
    """AC1: the sole parameter of ``mcnemar`` is ``records: list[EvalRecord]``
    — there is no code path that accepts two independent rate summaries
    (e.g. two bare proportions/counts) and returns a p-value."""
    sig = inspect.signature(mcnemar)
    assert list(sig.parameters) == ["records"]
    (param,) = sig.parameters.values()
    assert param.annotation in ("list[EvalRecord]", list[EvalRecord])


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

    def test_diverges_from_clamped_normal_approximation(self) -> None:
        """AC2: small n (10) at an extreme point estimate (100% correct) is
        exactly the case where a clamped normal approximation degenerates —
        ``se = sqrt(p*(1-p)/n) == 0`` at p=1, so the clamped-normal interval
        collapses to the point estimate ``[1.0, 1.0]`` and would falsely
        report zero uncertainty. Wilson does not degenerate here: its lower
        bound is pinned at the independently-computed value below, proving
        this is the score interval, not a normal approximation with the
        endpoints clamped into range."""
        records = [_rec(question_id=str(i), outcome="correct") for i in range(10)]
        result = wilson(records)
        assert result["n"] == 10
        assert result["point"] == 1.0

        # A clamped normal approximation at p=1.0 degenerates to [1.0, 1.0].
        normal_lower = max(0.0, 1.0 - 1.96 * math.sqrt(1.0 * (1.0 - 1.0) / 10))
        assert normal_lower == 1.0

        # Wilson must not degenerate: its lower bound is pinned well below 1.0.
        assert result["lower"] == 0.7224598312333834
        assert result["upper"] == 1.0
        assert result["lower"] < normal_lower


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

    def test_counts_leaf_via_trigger_union_not_representative(self) -> None:
        # Two fixture-variant records for the SAME leaf, both outcome="correct"
        # (so DA6's unanimity rule makes both eligible candidates for the
        # min()-picked representative), but only one carries a trigger. The
        # leaf must be counted as reviewed regardless of which record
        # _collapse_leaf_group's min() would have picked as representative.
        records = [
            _rec(
                paper_id="p1",
                question_id="1",
                fixture_variant="a",
                outcome="correct",
                triggers=[],
            ),
            _rec(
                paper_id="p1",
                question_id="1",
                fixture_variant="b",
                outcome="correct",
                triggers=["low_confidence"],
            ),
        ]
        result = review_rate(records)
        assert result["n"] == 1
        assert result["review_rate_total"] == 1.0
        assert result["review_rate_signal"] == 1.0

    def test_leaf_with_no_triggered_variants_is_not_reviewed(self) -> None:
        # Companion case: both variant records triggerless — the union fix
        # must not manufacture a false positive.
        records = [
            _rec(
                paper_id="p1",
                question_id="1",
                fixture_variant="a",
                outcome="correct",
                triggers=[],
            ),
            _rec(
                paper_id="p1",
                question_id="1",
                fixture_variant="b",
                outcome="correct",
                triggers=[],
            ),
        ]
        result = review_rate(records)
        assert result["n"] == 1
        assert result["review_rate_total"] == 0.0
        assert result["review_rate_signal"] == 0.0

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


class TestCoherenceTriggerRate:
    """M1.5 (#40): coherence_mismatch's own leaf-level rate, reported
    separately from review_rate_signal/review_rate_total — NOT double-counted
    into either."""

    def test_coherence_trigger_rate_is_reported_separately_from_review_rate(self) -> None:
        records = [
            _rec(question_id="1", paper_id="p1", triggers=["coherence_mismatch"]),
            _rec(question_id="2", paper_id="p1", triggers=["needs_teacher_review"]),
            _rec(question_id="3", paper_id="p1", triggers=[]),
            _rec(question_id="4", paper_id="p1", triggers=[]),
        ]
        rr = review_rate(records)
        ctr = coherence_trigger_rate(records)
        assert ctr["n"] == 4
        assert ctr["coherence_trigger_rate"] == 0.25
        # Distinct from review_rate: 2/4 leaves carry SOME trigger, only 1/4
        # carries the coherence one specifically. Not double-counted into
        # either denominator: review_rate itself is unaffected by whether the
        # trigger token spells "coherence_mismatch" or something else.
        assert rr["review_rate_total"] == 0.5
        assert ctr["coherence_trigger_rate"] != rr["review_rate_total"]
        assert ctr["coherence_trigger_rate"] != rr["review_rate_signal"]

    def test_empty_input_reports_zero_with_zero_n(self) -> None:
        result = coherence_trigger_rate([])
        assert result["n"] == 0
        assert result["coherence_trigger_rate"] == 0.0

    def test_counts_leaf_via_trigger_union_not_representative(self) -> None:
        # Two fixture-variant records for the same leaf, both correct (DA6
        # unanimity), but only one carries the coherence trigger — the leaf
        # must be counted regardless of which record DA6 would collapse to.
        records = [
            _rec(
                paper_id="p1",
                question_id="1",
                fixture_variant="a",
                outcome="correct",
                triggers=[],
            ),
            _rec(
                paper_id="p1",
                question_id="1",
                fixture_variant="b",
                outcome="correct",
                triggers=["coherence_mismatch"],
            ),
        ]
        result = coherence_trigger_rate(records)
        assert result["n"] == 1
        assert result["coherence_trigger_rate"] == 1.0

    def test_excluded_leaves_are_not_counted_in_denominator(self) -> None:
        records = [
            _rec(question_id="1", paper_id="p1", outcome="excluded", triggers=[]),
            _rec(question_id="2", paper_id="p1", triggers=["coherence_mismatch"]),
        ]
        result = coherence_trigger_rate(records)
        assert result["n"] == 1
        assert result["coherence_trigger_rate"] == 1.0


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
    def test_wilson_n_is_31_distinct_leaves(self) -> None:
        """Verified against the corpus (BUILD/DECISIONS.md DA6): 11 golden case
        dirs hold 71 answer rows (M0.8/#32 added the 11th, ``_theory_nested``,
        contributing 3 leaves — 1a_i, 1a_ii, 1b — with no fixture-variant
        suffix to collapse); stripping the _correct/_partial/_wrong
        fixture-variant suffix collapses them to 7+6+8+7+3 = 31 distinct
        (paper, question) leaves. This supersedes the pre-#32 baseline of 68
        rows / 28 leaves — do not cite 28 as the current distinct-leaf count."""
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
        assert len(records) == 71
        result = wilson(records)
        assert result["n"] == 31

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
        scored record, so wilson's n must be 31 (M0.8/#32 raised this from
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
        assert len(records) == 71

        wilson_result = wilson(records)
        funnel_result = exclusion_funnel(records)

        assert wilson_result["n"] == 31
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


class TestPaperGradeConfidence:
    """paper_grade_confidence: marks-weighted mean of per-question marker_conf,
    banded per paper (spec §4 M1.1) -- NOT a min-over-questions."""

    def test_marks_weighted_mean_arithmetic(self) -> None:
        # weights 1 and 3 (truth_marks): (0.5*1 + 0.9*3) / 4 = 3.2/4 = 0.80
        records = [
            _rec(paper_id="p1", question_id="1", truth_marks=1, marker_conf=0.5),
            _rec(paper_id="p1", question_id="2", truth_marks=3, marker_conf=0.9),
        ]
        result = paper_grade_confidence(records)
        score, band = result["p1"]
        assert score == 0.8
        assert band == "MEDIUM"

    def test_boundary_at_exactly_0_85_is_high(self) -> None:
        records = [_rec(paper_id="p1", question_id="1", truth_marks=1, marker_conf=0.85)]
        score, band = paper_grade_confidence(records)["p1"]
        assert score == 0.85
        assert band == "HIGH"

    def test_boundary_at_exactly_0_65_is_medium(self) -> None:
        records = [_rec(paper_id="p1", question_id="1", truth_marks=1, marker_conf=0.65)]
        score, band = paper_grade_confidence(records)["p1"]
        assert score == 0.65
        assert band == "MEDIUM"

    def test_just_below_0_65_is_low(self) -> None:
        records = [_rec(paper_id="p1", question_id="1", truth_marks=1, marker_conf=0.6499)]
        score, band = paper_grade_confidence(records)["p1"]
        assert band == "LOW"

    def test_min_over_questions_would_disagree_with_the_weighted_mean(self) -> None:
        """One low-confidence, low-weight question must not drag the whole
        paper down to LOW the way a min-over-questions rule would."""
        records = [
            _rec(paper_id="p1", question_id="1", truth_marks=1, marker_conf=0.10),
            _rec(paper_id="p1", question_id="2", truth_marks=9, marker_conf=0.95),
        ]
        score, band = paper_grade_confidence(records)["p1"]
        # weighted mean: (0.10*1 + 0.95*9)/10 = 8.65/10 = 0.865 -> HIGH
        assert score == pytest.approx(0.865)
        assert band == "HIGH"

    def test_weights_by_tariff_maximum_marks_not_earned_truth_marks(self) -> None:
        """A 6-mark question answered wrong (truth_marks=0) must still weigh
        6, not 0 and not clamped to 1 -- weighting must use the question's
        tariff (``maximum_marks``), never what the student happened to earn.
        ``max(truth_marks, 1)`` would still weigh this row 1, not 6, and
        would still under-weight a wrongly-answered high-tariff question
        relative to a rightly-answered one -- the same bias, merely
        attenuated. This is the MUST-FIX regression test for #36.
        """
        records = [
            _rec(
                paper_id="p1",
                question_id="1",
                truth_marks=0,
                maximum_marks=6,
                marker_conf=0.2,
            ),
            _rec(
                paper_id="p1",
                question_id="2",
                truth_marks=1,
                maximum_marks=1,
                marker_conf=0.9,
            ),
        ]
        score, band = paper_grade_confidence(records)["p1"]
        # weighted by tariff: (0.2*6 + 0.9*1)/7 = 2.1/7 = 0.3
        assert score == pytest.approx(0.3)
        assert band == "LOW"

    def test_all_zero_truth_marks_paper_gets_a_real_band(self) -> None:
        """A paper where every question scored zero marks must not vanish
        from the result. Before the fix, ``if not r.truth_marks: continue``
        dropped every row of an all-zero paper, so ``total_weight`` stayed 0
        and the paper was omitted entirely -- exactly the papers a
        grade-confidence signal should be most sensitive to. With no
        ``maximum_marks`` supplied here either, the weight falls back to
        ``r.truth_marks or 1`` = 1 per row (equal weighting), not to zero.
        """
        records = [
            _rec(paper_id="p1", question_id="1", truth_marks=0, marker_conf=0.9),
            _rec(paper_id="p1", question_id="2", truth_marks=0, marker_conf=0.7),
        ]
        result = paper_grade_confidence(records)
        assert "p1" in result, "an all-zero-truth_marks paper must not vanish from the result"
        score, band = result["p1"]
        assert score == pytest.approx((0.9 + 0.7) / 2)
        assert band == "MEDIUM"

    def test_excludes_point_level_rows(self) -> None:
        records = [
            _rec(paper_id="p1", question_id="1", truth_marks=1, marker_conf=0.9),
            _rec(
                paper_id="p1",
                question_id="1",
                mark_point_id="1a",
                truth_marks=1,
                marker_conf=0.1,
            ),
        ]
        score, _band = paper_grade_confidence(records)["p1"]
        assert score == 0.9

    def test_m0_baseline_band_distribution_reported_honestly(self) -> None:
        """Re-scored from the saved M0 A/A-floor records (no new spend, per
        the sequencing constraint on #36).

        The expected per-paper scores are computed HERE, independently, by
        looping over the same input rows the production function sees --
        not pasted from an earlier run's output. A hardcoded 16-significant-
        figure float is a change-detector, not a test: it would pass or fail
        based on floating-point noise nobody could reason about from the
        assertion alone. ``_independent_weighted_mean`` below intentionally
        does not import or call :func:`paper_grade_confidence`; it recomputes
        the marks-weighted mean directly from the filtered rows so a bug
        shared between production and test code cannot cancel out.

        None of these published rows carry ``maximum_marks`` (the field did
        not exist when they were written), so the weight here still falls
        back to ``truth_marks``. This is therefore an honest report of the
        *current* band distribution on this corpus, not a claim about what a
        tariff-weighted rerun would show -- see the docstring on
        :func:`paper_grade_confidence` for that distinction.
        """
        run_dir = (
            Path(__file__).resolve().parents[2]
            / "BUILD"
            / "accuracy-runs"
            / ("aa-floor-2026-08-23-a")
        )
        records_path = run_dir / "records-repeat-01.jsonl"
        assert records_path.exists(), "expected the saved M0 A/A-floor records"

        records = [
            EvalRecord.model_validate(json.loads(line))
            for line in records_path.read_text().splitlines()
            if line.strip()
        ]
        result = paper_grade_confidence(records)
        assert result, "expected at least one paper"

        def _independent_weighted_mean(paper_id: str) -> float:
            numerator = 0.0
            denominator = 0.0
            for r in records:
                if r.paper_id != paper_id or r.mark_point_id is not None:
                    continue
                if r.marker_conf is None:
                    continue
                weight = r.maximum_marks if r.maximum_marks else (r.truth_marks or 1)
                numerator += r.marker_conf * weight
                denominator += weight
            assert denominator > 0
            return numerator / denominator

        def _independent_band(score: float) -> str:
            # Recomputed independently of `_band_for_score` for the same
            # reason `_independent_weighted_mean` avoids `paper_grade_confidence`.
            if score >= 0.85:
                return "HIGH"
            if score >= 0.65:
                return "MEDIUM"
            return "LOW"

        expected_paper_ids = {
            "0580_s23_qp_22_theory",
            "0606_s23_qp_12_theory",
            "0625_m20_qp_12_mcq",
            "0625_s20_qp_31_theory",
            "0625_w21_qp_32_theory_nested",
        }
        assert set(result) == expected_paper_ids

        # Reported, not assumed non-degenerate: whatever the real band
        # distribution comes out to below is the honest finding (spec §9
        # gate 8 discipline -- never narrow a denominator or relabel a
        # metric to force a particular distribution).
        bands = {band for _score, band in result.values()}
        for paper_id in expected_paper_ids:
            score, band = result[paper_id]
            assert score == pytest.approx(_independent_weighted_mean(paper_id))
            assert band == _independent_band(score)

        # HONEST FINDING, not a forced pass: on this 5-paper corpus, every
        # paper still lands in HIGH after the tariff-weighting fix -- the
        # dropped low-confidence rows (marker_conf as low as 0.55/0.65) were
        # not, on this corpus, enough by themselves to pull any paper's
        # weighted mean below 0.85. The band distribution IS still
        # degenerate here; that is reported, not spun. It would take either
        # a larger/more heterogeneous corpus or a genuinely low-confidence
        # paper to exercise MEDIUM/LOW, neither of which this test may
        # invent.
        assert bands == {"HIGH"}, f"band distribution: {result}"
