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


def _fake_result(
    *,
    n_reviewed: int,
    n_total: int = 10,
    mark_accuracy: float = 1.0,
    split: str = "dev",
) -> AccuracyResult:
    """An ``AccuracyResult`` with a controllable review rate (``n_reviewed``
    of ``n_total`` records carry a non-empty ``triggers`` list), a
    controllable ``mark_accuracy`` (defaults to a clean 1.0), and a
    controllable manifest ``split`` (defaults to the real "dev" split
    ``measure-accuracy`` always uses).
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
        split=split,
        corpus_digest="digest",
    )
    return AccuracyResult(
        metrics=AccuracyMetrics(
            mark_accuracy=mark_accuracy,
            mark_accuracy_theory=mark_accuracy,
            id_match_rate=1.0,
            flag_precision_high=1.0,
            flag_recall=1.0,
        ),
        calibration=[],
        question_results=[],
        prompt_versions={"extraction": "1", "correction": "1", "mark_scheme": "1"},
        manifest=manifest,
        eval_records=records,
        # #29 (M0.5) made ``funnel`` a required field. Every record this
        # fixture builds is a fully-marked leaf, so all four pipeline stages
        # equal the record count — keyed off ``records`` rather than a literal
        # so the funnel cannot drift out of step with ``n_total``.
        funnel=FunnelCounts(
            leaves=len(records),
            extracted=len(records),
            matched=len(records),
            marked=len(records),
        ),
    )


def _run_cli(
    tmp_path: object,
    *,
    armed: bool,
    n_reviewed: int,
    mark_accuracy: float = 1.0,
    split: str = "dev",
) -> object:
    from lemely.app.cli import cli

    breaching_result = _fake_result(n_reviewed=n_reviewed, mark_accuracy=mark_accuracy, split=split)

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
        # Filters on the per-line `line` variable, not (vacuously) on whether
        # "Targets missed" appears anywhere in `result.output` — with a clean
        # run (no metric failures) and an unarmed, non-blocking review-rate
        # breach, the "Targets missed:" section must never print at all.
        targets_missed_lines = [
            line for line in result.output.splitlines() if "Targets missed" in line
        ]
        assert targets_missed_lines == [], result.output

    def test_armed_false_breach_does_not_leak_into_targets_missed_section(self, tmp_path) -> None:
        # A genuine metric failure (mark_accuracy below target) makes the
        # "Targets missed:" section print at all; the review-rate breach
        # text — which legitimately appears elsewhere, in the unconditional
        # "Review-rate gate breaches:" block — must NOT leak into that
        # section while the ratchet is unarmed. A filter that checks
        # membership in the whole `result.output` (the pre-fix bug) cannot
        # tell "printed somewhere" apart from "printed in the missed-targets
        # list": once ANY line makes the header appear, that buggy filter
        # selects every line of output, so it would incorrectly flag this
        # non-blocking review-rate breach as if it were a missed target.
        result = _run_cli(tmp_path, armed=False, n_reviewed=3, mark_accuracy=0.5)
        assert result.exit_code != 0, result.output  # mark_accuracy alone blocks
        assert "review_rate_total" in result.output  # the breach IS printed somewhere

        missed_lines: list[str] = []
        in_missed_section = False
        for line in result.output.splitlines():
            if "Targets missed" in line:
                in_missed_section = True
                continue
            if in_missed_section:
                missed_lines.append(line)

        assert any("mark_accuracy" in line for line in missed_lines), result.output
        assert not any("review_rate_total" in line for line in missed_lines), result.output
        assert not any("review_rate_gate" in line for line in missed_lines), result.output

    def test_armed_true_breaching_review_rate_exits_nonzero_naming_the_gate(self, tmp_path) -> None:
        result = _run_cli(tmp_path, armed=True, n_reviewed=3)
        assert result.exit_code != 0, result.output
        assert "review_rate_gate" in result.output

    def test_armed_true_clean_review_rate_exits_zero(self, tmp_path) -> None:
        # 0/10 reviewed = 0%, clean on every limb — armed must not block a
        # genuinely clean run (no false positive).
        result = _run_cli(tmp_path, armed=True, n_reviewed=0)
        assert result.exit_code == 0, result.output


class TestMeasureAccuracyRefusesNonDevSplit:
    def test_non_dev_split_manifest_fails_loudly_instead_of_computing_review_rate(
        self, tmp_path
    ) -> None:
        # Forces measure_accuracy() to return a "train"-split manifest —
        # something the real command never does today, but this must not be
        # relied on as an implicit guarantee. The CLI must refuse loudly
        # rather than silently compute review_rate over the wrong split
        # (spec §5: review_rate is only defined over the golden dev split).
        result = _run_cli(tmp_path, armed=False, n_reviewed=0, split="train")
        assert result.exit_code != 0, result.output
        assert "dev" in result.output
        assert "train" in result.output
        # And it must fail BEFORE computing/printing a review rate line.
        assert "Review rate" not in result.output
