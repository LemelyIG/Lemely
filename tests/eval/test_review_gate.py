"""Unit tests for lemely.eval.review_gate's pure M0.9 gate (spec §4 M0.9, §5).

All inputs are synthetic ``ReviewRateResult`` dicts — no I/O, no network, no
Gemini calls, matching the M0.1 "pure analyses" contract this module sits
beside (§7: M0.9 must land before M1.1/#36).
"""

from __future__ import annotations

from lemely.eval.analyses import ReviewRateResult
from lemely.eval.review_gate import evaluate_review_rate_gate


def _rate(**overrides: object) -> ReviewRateResult:
    base: ReviewRateResult = {
        "n": 31,
        "review_rate_signal": 0.03,
        "review_rate_total": 0.03,
        "per_paper_p95": 0.05,
    }
    base.update(overrides)  # type: ignore[typeddict-item]
    return base


class TestSignalLimb:
    def test_pass_at_target(self) -> None:
        result = evaluate_review_rate_gate(
            _rate(review_rate_signal=0.08, review_rate_total=0.08),
            last_merged_review_rate=0.10,
            armed=True,
        )
        assert result["signal_ok"] is True

    def test_fail_just_over_target(self) -> None:
        result = evaluate_review_rate_gate(
            _rate(review_rate_signal=0.081, review_rate_total=0.081),
            last_merged_review_rate=0.10,
            armed=True,
        )
        assert result["signal_ok"] is False
        assert result["blocking_failure"] is True


class TestTotalLimb:
    def test_pass_at_target(self) -> None:
        result = evaluate_review_rate_gate(
            _rate(review_rate_signal=0.03, review_rate_total=0.10),
            last_merged_review_rate=0.10,
            armed=True,
        )
        assert result["total_ok"] is True

    def test_fail_just_over_target(self) -> None:
        result = evaluate_review_rate_gate(
            _rate(review_rate_signal=0.03, review_rate_total=0.101),
            last_merged_review_rate=0.10,
            armed=True,
        )
        assert result["total_ok"] is False
        assert result["blocking_failure"] is True


class TestPerPaperP95Limb:
    def test_pass_at_target(self) -> None:
        result = evaluate_review_rate_gate(
            _rate(per_paper_p95=0.15),
            last_merged_review_rate=0.10,
            armed=True,
        )
        assert result["p95_ok"] is True

    def test_fail_just_over_target(self) -> None:
        result = evaluate_review_rate_gate(
            _rate(per_paper_p95=0.151),
            last_merged_review_rate=0.10,
            armed=True,
        )
        assert result["p95_ok"] is False
        assert result["blocking_failure"] is True


class TestRatchetCeiling:
    def test_ratchet_ceiling_is_min_of_ten_pct_and_last_merged(self) -> None:
        result = evaluate_review_rate_gate(
            _rate(review_rate_signal=0.03, review_rate_total=0.03),
            last_merged_review_rate=0.05,
            armed=True,
        )
        assert result["ratchet_ceiling"] == 0.05

        result2 = evaluate_review_rate_gate(
            _rate(review_rate_signal=0.03, review_rate_total=0.03),
            last_merged_review_rate=0.50,
            armed=True,
        )
        assert result2["ratchet_ceiling"] == 0.10


class TestRatchetDirection:
    def test_ratchet_direction_breach_under_absolute_cap_still_fails_when_armed(self) -> None:
        # 9% is under the absolute 10% cap but above last_merged=8% — the
        # ratchet must still fail this when armed, even though the total-limb
        # alone would pass.
        result = evaluate_review_rate_gate(
            _rate(review_rate_signal=0.09, review_rate_total=0.09),
            last_merged_review_rate=0.08,
            armed=True,
        )
        assert result["total_ok"] is True
        assert result["ratchet_ok"] is False
        assert result["blocking_failure"] is True


class TestArmedFalseNonBlocking:
    def test_armed_false_records_but_does_not_block(self) -> None:
        breaching = _rate(review_rate_signal=0.50, review_rate_total=0.60, per_paper_p95=0.90)
        result = evaluate_review_rate_gate(
            breaching,
            last_merged_review_rate=0.03,
            armed=False,
        )
        assert result["signal_ok"] is False
        assert result["total_ok"] is False
        assert result["p95_ok"] is False
        assert result["ratchet_ok"] is False
        assert result["breaches"] != []
        assert result["blocking_failure"] is False


class TestArmedTrueBlocking:
    def test_armed_true_blocks_on_same_breach(self) -> None:
        breaching = _rate(review_rate_signal=0.50, review_rate_total=0.60, per_paper_p95=0.90)
        result = evaluate_review_rate_gate(
            breaching,
            last_merged_review_rate=0.03,
            armed=True,
        )
        assert result["blocking_failure"] is True
        assert (
            result["breaches"]
            == evaluate_review_rate_gate(breaching, last_merged_review_rate=0.03, armed=False)[
                "breaches"
            ]
        )


class TestAllLimbsPassNeverBlocks:
    def test_all_limbs_pass_is_never_blocking_regardless_of_armed(self) -> None:
        clean = _rate(review_rate_signal=0.03, review_rate_total=0.03, per_paper_p95=0.05)
        for armed in (False, True):
            result = evaluate_review_rate_gate(clean, last_merged_review_rate=0.10, armed=armed)
            assert result["blocking_failure"] is False
            assert result["breaches"] == []


class TestSignalEqualsTotalInvariant:
    def test_total_exceeding_signal_is_a_breach_not_silent_headroom(self) -> None:
        # Until the random_audit trigger (M4/T1.10) exists, review_rate_total
        # must equal review_rate_signal — a caller feeding a hand-built
        # ReviewRateResult where they diverge must not be silently accepted.
        diverged = _rate(review_rate_signal=0.03, review_rate_total=0.09, per_paper_p95=0.05)
        result = evaluate_review_rate_gate(diverged, last_merged_review_rate=0.10, armed=True)
        assert result["invariant_ok"] is False
        assert result["blocking_failure"] is True

    def test_equal_signal_and_total_satisfies_invariant(self) -> None:
        equal = _rate(review_rate_signal=0.03, review_rate_total=0.03, per_paper_p95=0.05)
        result = evaluate_review_rate_gate(equal, last_merged_review_rate=0.10, armed=True)
        assert result["invariant_ok"] is True


class TestC13RestatementDidNotLoosenTheGate:
    """#161 / ruling C13 restated ``review_rate_last_merged`` 0.2903 -> 0.4838.

    The number went UP, which looks like a loosening and must be pinned as not
    being one. The effective ceiling is ``min(total_target, last_merged)``, and
    both values sit above ``total_target``, so the ceiling is 0.10 either way.
    These tests exist so a future reader — or a future edit — cannot quietly
    turn the restatement into headroom.
    """

    def test_effective_ceiling_is_identical_before_and_after_the_restatement(self) -> None:
        rate = _rate(review_rate_signal=0.2903, review_rate_total=0.2903, per_paper_p95=0.8333)
        before = evaluate_review_rate_gate(rate, last_merged_review_rate=0.2903, armed=False)
        after = evaluate_review_rate_gate(rate, last_merged_review_rate=0.4838, armed=False)
        assert before["ratchet_ceiling"] == after["ratchet_ceiling"] == 0.10
        assert before["ratchet_ok"] is after["ratchet_ok"] is False

    def test_shipped_defaults_still_fail_every_limb_on_the_measured_rate(self) -> None:
        # The measured dev-split rate (BUILD/review-rate-baseline.json). Arming
        # today would block every merge, and the restatement did not change
        # that — three of the four limbs fail on ABSOLUTE targets that
        # last_merged does not touch.
        from lemely.runtime.config import AccuracyEvalSettings

        t = AccuracyEvalSettings()
        measured = _rate(review_rate_signal=0.2903, review_rate_total=0.2903, per_paper_p95=0.8333)
        result = evaluate_review_rate_gate(
            measured,
            last_merged_review_rate=t.review_rate_last_merged,
            armed=True,
            signal_target=t.review_rate_signal_target,
            total_target=t.review_rate_total_target,
            p95_target=t.review_rate_p95_target,
        )
        assert result["signal_ok"] is False
        assert result["total_ok"] is False
        assert result["p95_ok"] is False
        assert result["ratchet_ok"] is False
        assert result["blocking_failure"] is True

    def test_ratchet_limb_is_pinned_by_total_target_not_by_last_merged(self) -> None:
        # Whatever last_merged is set to above total_target, the ceiling does
        # not move. This is why restating the statistic could not unblock
        # arming, and why the arming blocker is M1 accuracy work instead.
        rate = _rate(review_rate_signal=0.2903, review_rate_total=0.2903, per_paper_p95=0.05)
        ceilings = {
            evaluate_review_rate_gate(rate, last_merged_review_rate=lm, armed=False)[
                "ratchet_ceiling"
            ]
            for lm in (0.2903, 0.4838, 0.99, 1.0)
        }
        assert ceilings == {0.10}

    def test_last_merged_below_the_target_still_tightens(self) -> None:
        # The ratchet must remain functional once the rate actually comes down
        # — the restatement must not have broken the mechanism it restated.
        rate = _rate(review_rate_signal=0.07, review_rate_total=0.07, per_paper_p95=0.05)
        result = evaluate_review_rate_gate(rate, last_merged_review_rate=0.05, armed=True)
        assert result["ratchet_ceiling"] == 0.05
        assert result["total_ok"] is True
        assert result["ratchet_ok"] is False
        assert result["blocking_failure"] is True
