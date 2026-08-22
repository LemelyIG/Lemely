"""M0.9 (#33): measure-accuracy's exit code is driven by the review-rate gate.

Falsifiable against pre-fix ``cli.py``: before this issue, the CLI never
computed ``review_rate``/``evaluate_review_rate_gate`` at all, so a breaching
review rate with every metric target met exited 0 regardless of the ratchet's
armed state. These tests prove the post-fix behaviour actually differs by
armed state — not merely that a review-rate line gets printed.

Mocks ``measure_accuracy``/``save_result`` in ``lemely.accuracy.harness`` (the
module ``cli.py`` imports them from at call time) so nothing here spends
Gemini budget or touches the network.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

from click.testing import CliRunner

from lemely.accuracy.harness import AccuracyMetrics, AccuracyResult
from lemely.eval.manifest import RunManifest
from lemely.eval.records import EvalRecord


def _rec(question_id: str, *, triggers: list[str]) -> EvalRecord:
    return EvalRecord(
        run_id="run-test",
        arm="extract+mark",
        paper_id="p1",
        fixture_variant=None,
        question_id=question_id,
        mark_point_id=None,
        parse_path="det",
        predicted_marks=2,
        truth_marks=2,
        outcome="correct",
        extraction_conf=0.95,
        marker_conf=0.95,
        id_match="exact",
        triggers=triggers,
    )


def _fake_result(*, n_reviewed: int, n_total: int = 10) -> AccuracyResult:
    """A dev-split AccuracyResult with every metric target met and a
    controllable review rate: ``n_reviewed`` of ``n_total`` records carry a
    non-empty ``triggers`` list.
    """
    records = [
        _rec(str(i), triggers=["low_confidence"] if i < n_reviewed else []) for i in range(n_total)
    ]
    manifest = RunManifest(
        run_id="run-test",
        git_sha="deadbeef",
        timestamp=datetime.now(UTC),
        prompt_versions={"extraction": "1", "correction": "1", "mark_scheme": "1"},
        params_fingerprint="fp",
        models_by_task={},
        cache_mode="bypass",
        split="dev",
        corpus_digest="digest",
    )
    return AccuracyResult(
        metrics=AccuracyMetrics(
            mark_accuracy=1.0,
            mark_accuracy_theory=1.0,
            id_match_rate=1.0,
            flag_precision_high=1.0,
            flag_recall=1.0,
        ),
        calibration=[],
        question_results=[],
        prompt_versions={"extraction": "1", "correction": "1", "mark_scheme": "1"},
        manifest=manifest,
        eval_records=records,
    )


def _run_cli(tmp_path: object, *, armed: bool, n_reviewed: int) -> object:
    from lemely.app.cli import cli

    breaching_result = _fake_result(n_reviewed=n_reviewed)

    runner = CliRunner()
    with (
        patch("lemely.accuracy.harness.measure_accuracy", return_value=breaching_result),
        patch("lemely.accuracy.harness.save_result", return_value=f"{tmp_path}/fake.json"),
        patch("lemely.io.gemini.GeminiClient"),
    ):
        env = {
            "LEMELY_ACCURACY_EVAL__REVIEW_RATE_RATCHET_ARMED": "true" if armed else "false",
            # Keep last_merged permissive so only the signal/total limbs (not
            # the ratchet) drive the breach in these tests.
            "LEMELY_ACCURACY_EVAL__REVIEW_RATE_LAST_MERGED": "0.5",
        }
        return runner.invoke(
            cli,
            ["measure-accuracy", "--golden", "tests/golden", "--results-dir", str(tmp_path)],
            env=env,
        )


class TestReviewRateGateDrivesExitCode:
    def test_armed_false_breaching_review_rate_exits_zero(self, tmp_path) -> None:
        # 3/10 reviewed = 30%, breaches both the 8% signal and 10% total
        # limbs, but the ratchet is unarmed — non-blocking.
        result = _run_cli(tmp_path, armed=False, n_reviewed=3)
        assert result.exit_code == 0, result.output
        assert "Review rate" in result.output
        assert "review_rate_gate" not in "\n".join(
            line for line in result.output.splitlines() if "Targets missed" in result.output
        )

    def test_armed_true_breaching_review_rate_exits_nonzero_naming_the_gate(self, tmp_path) -> None:
        result = _run_cli(tmp_path, armed=True, n_reviewed=3)
        assert result.exit_code != 0, result.output
        assert "review_rate_gate" in result.output

    def test_armed_true_clean_review_rate_exits_zero(self, tmp_path) -> None:
        # 0/10 reviewed = 0%, clean on every limb — armed must not block a
        # genuinely clean run (no false positive).
        result = _run_cli(tmp_path, armed=True, n_reviewed=0)
        assert result.exit_code == 0, result.output
