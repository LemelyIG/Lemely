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
