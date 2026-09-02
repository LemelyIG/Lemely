"""M1.5 (#40) bullet 4: coherence_trigger_rate's own contribution to review
volume must be measured AND reported, as its own separate line — not folded
into the "Review rate: ..." line.

Falsifiable against pre-fix ``cli.py``: before this fix, ``measure-accuracy``
imported and called only ``review_rate``. ``coherence_trigger_rate`` existed
in ``lemely/eval/analyses.py`` but had zero callers, so a fresh run never
computed or printed it, no matter how many records carried a
``coherence_mismatch`` trigger.

Mocks ``measure_accuracy``/``save_result`` in ``lemely.accuracy.harness`` (the
module ``cli.py`` imports them from at call time) so nothing here spends
Gemini budget or touches the network.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

from click.testing import CliRunner

from lemely.accuracy.harness import AccuracyMetrics, AccuracyResult, FunnelCounts
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


def _fake_result(*, n_total: int = 10, n_coherence_flagged: int = 4) -> AccuracyResult:
    """An ``AccuracyResult`` with a controllable coherence-trigger rate
    (``n_coherence_flagged`` of ``n_total`` records carry a
    ``coherence_mismatch`` trigger), a clean review rate otherwise (no other
    triggers), and a clean 1.0 ``mark_accuracy`` so no metric target fires and
    the only thing under test is the new report line.
    """
    records = [
        _rec(str(i), triggers=["coherence_mismatch"] if i < n_coherence_flagged else [])
        for i in range(n_total)
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
        funnel=FunnelCounts(
            leaves=len(records),
            extracted=len(records),
            matched=len(records),
            marked=len(records),
        ),
    )


def _run_cli(tmp_path: object, *, n_total: int = 10, n_coherence_flagged: int = 4) -> object:
    from lemely.app.cli import cli

    fake_result = _fake_result(n_total=n_total, n_coherence_flagged=n_coherence_flagged)

    runner = CliRunner()
    with (
        patch("lemely.accuracy.harness.measure_accuracy", return_value=fake_result),
        patch("lemely.accuracy.harness.save_result", return_value=f"{tmp_path}/fake.json"),
        patch("lemely.io.gemini.GeminiClient"),
    ):
        env = {
            "LEMELY_ACCURACY_EVAL__REVIEW_RATE_RATCHET_ARMED": "false",
        }
        return runner.invoke(
            cli,
            ["measure-accuracy", "--golden", "tests/golden", "--results-dir", str(tmp_path)],
            env=env,
        )


class TestCoherenceTriggerRateIsReported:
    def test_coherence_trigger_rate_line_appears_and_is_correct(self, tmp_path) -> None:
        result = _run_cli(tmp_path, n_total=10, n_coherence_flagged=4)
        assert result.exit_code == 0, result.output
        lines = result.output.splitlines()
        coherence_lines = [line for line in lines if "coherence" in line.lower()]
        assert coherence_lines, result.output
        # Reported separately: the "Review rate: ..." line itself must not
        # carry the coherence-trigger-rate number/label.
        review_rate_lines = [line for line in lines if line.strip().startswith("Review rate:")]
        assert review_rate_lines, result.output
        assert "coherence" not in review_rate_lines[0].lower()
        # 4/10 flagged = 0.400, n=10.
        assert any("0.400" in line for line in coherence_lines), result.output
        assert any("n=10" in line for line in coherence_lines), result.output

    def test_coherence_trigger_rate_zero_when_no_records_flagged(self, tmp_path) -> None:
        result = _run_cli(tmp_path, n_total=10, n_coherence_flagged=0)
        assert result.exit_code == 0, result.output
        coherence_lines = [
            line for line in result.output.splitlines() if "coherence" in line.lower()
        ]
        assert coherence_lines, result.output
        assert any("0.000" in line for line in coherence_lines), result.output
