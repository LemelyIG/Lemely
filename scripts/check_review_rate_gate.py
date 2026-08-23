#!/usr/bin/env python3
"""M0.9 (#33): run the review-rate two-part ratchet gate against a real baseline.

Loads thresholds/ratchet state from ``lemely.toml``/env via
``lemely.runtime.config.load_settings`` (mirroring every other accuracy-eval
target), loads the most recent dev-split golden-run's ``ReviewRateResult`` —
preferring a fresh ``tests/golden/results/*.json`` if one exists (that
directory is gitignored, so it will not exist on a clean checkout or in CI),
and otherwise falling back to the committed baseline artifact
``BUILD/review-rate-baseline.json`` — and evaluates
:func:`lemely.eval.review_gate.evaluate_review_rate_gate` against it.

Prints a check.sh-style PASS/FAIL/breach report. Exits non-zero only on a
``blocking_failure`` (i.e. only once ``review_rate_ratchet_armed = true``);
at M0 (unarmed) breaches are printed but the script exits 0.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BASELINE_ARTIFACT = REPO_ROOT / "BUILD" / "review-rate-baseline.json"
GOLDEN_RESULTS_DIR = REPO_ROOT / "tests" / "golden" / "results"


def _baseline_provenance() -> tuple[str | None, str | None]:
    """Return (run_id, corpus_digest) recorded on the committed baseline, if any.

    Used only to WARN when a preferred fresh local run diverges from the
    corpus the committed baseline (and therefore CI, which never has a fresh
    golden run — that directory is gitignored) was computed against, so a
    local/CI data divergence is visible instead of silent.
    """
    if not BASELINE_ARTIFACT.is_file():
        return None, None
    artifact = json.loads(BASELINE_ARTIFACT.read_text(encoding="utf-8"))
    return artifact.get("run_id"), artifact.get("corpus_digest")


def _load_review_rate_result() -> tuple[dict[str, object], str, list[str]]:
    """Return (ReviewRateResult-shaped dict, source description, warnings).

    CI never has a fresh ``tests/golden/results/*.json`` (that directory is
    gitignored), so it deterministically falls through to the committed
    baseline artifact below. A fresh local run is only ever preferred
    outside CI, and even then its ``corpus_digest``/``run_id`` are compared
    against the committed baseline's so a silent local/CI data divergence
    surfaces as a printed warning rather than an invisible difference in
    gated numbers.
    """
    from lemely.eval.analyses import review_rate
    from lemely.eval.records import EvalRecord

    fresh_runs = sorted(GOLDEN_RESULTS_DIR.glob("*.json")) if GOLDEN_RESULTS_DIR.is_dir() else []
    if fresh_runs:
        latest = fresh_runs[-1]
        data = json.loads(latest.read_text(encoding="utf-8"))
        manifest = data.get("manifest", {})
        if manifest.get("split") != "dev":
            raise SystemExit(
                f"check_review_rate_gate: {latest} is a '{manifest.get('split')}'-split run, "
                "not 'dev' — refusing to compute review_rate over it (spec §5)."
            )
        records = [EvalRecord.model_validate(r) for r in data["eval_records"]]
        result = dict(review_rate(records))
        warnings: list[str] = []
        baseline_run_id, baseline_digest = _baseline_provenance()
        fresh_digest = manifest.get("corpus_digest")
        known_digests = baseline_digest is not None and fresh_digest is not None
        digests_diverge = known_digests and fresh_digest != baseline_digest
        if digests_diverge:
            warnings.append(
                f"preferred local run {latest.name} (corpus_digest={fresh_digest}, "
                f"run_id={manifest.get('run_id')}) diverges from the committed baseline "
                f"{BASELINE_ARTIFACT.name} (corpus_digest={baseline_digest}, "
                f"run_id={baseline_run_id}) — CI, which always uses the committed baseline, "
                "may gate on different data than this local run."
            )
        return result, str(latest.relative_to(REPO_ROOT)), warnings

    if not BASELINE_ARTIFACT.is_file():
        raise SystemExit(
            "check_review_rate_gate: no fresh golden run under "
            f"{GOLDEN_RESULTS_DIR} and no committed baseline at {BASELINE_ARTIFACT}. "
            "Run `lemely measure-accuracy` (dev split) first."
        )
    artifact = json.loads(BASELINE_ARTIFACT.read_text(encoding="utf-8"))
    if artifact.get("split") != "dev":
        raise SystemExit(f"check_review_rate_gate: {BASELINE_ARTIFACT} is not marked split='dev'.")
    return dict(artifact["review_rate"]), str(BASELINE_ARTIFACT.relative_to(REPO_ROOT)), []


def main() -> int:
    from lemely.eval.review_gate import evaluate_review_rate_gate
    from lemely.runtime.config import load_settings

    settings = load_settings()
    t = settings.accuracy_eval

    rate, source, provenance_warnings = _load_review_rate_result()
    gate = evaluate_review_rate_gate(
        rate,  # type: ignore[arg-type]
        last_merged_review_rate=t.review_rate_last_merged,
        armed=t.review_rate_ratchet_armed,
        signal_target=t.review_rate_signal_target,
        total_target=t.review_rate_total_target,
        p95_target=t.review_rate_p95_target,
    )

    print(f"review-rate-gate: source={source} n={rate['n']}")
    for w in provenance_warnings:
        print(f"  WARN: {w}")
    print(
        f"  signal={rate['review_rate_signal']:.4f} (target <= {t.review_rate_signal_target}) "
        f"{'PASS' if gate['signal_ok'] else 'FAIL'}"
    )
    print(
        f"  total ={rate['review_rate_total']:.4f} (target <= {t.review_rate_total_target}) "
        f"{'PASS' if gate['total_ok'] else 'FAIL'}"
    )
    print(
        f"  p95   ={rate['per_paper_p95']:.4f} (target <= {t.review_rate_p95_target}) "
        f"{'PASS' if gate['p95_ok'] else 'FAIL'}"
    )
    print(
        f"  ratchet: total <= {gate['ratchet_ceiling']:.4f} "
        f"(min({t.review_rate_total_target}, last_merged={t.review_rate_last_merged})) "
        f"{'PASS' if gate['ratchet_ok'] else 'FAIL'}"
    )
    print(f"  invariant total==signal: {'PASS' if gate['invariant_ok'] else 'FAIL'}")
    print(f"  armed={gate['armed']}")

    if gate["breaches"]:
        print("  breaches:")
        for b in gate["breaches"]:
            print(f"    ! {b}")
        if not gate["armed"]:
            print("  (ratchet unarmed — recorded, not blocking)")

    if gate["blocking_failure"]:
        print("FAIL   review-rate-gate")
        return 1
    print("PASS   review-rate-gate")
    return 0


if __name__ == "__main__":
    sys.exit(main())
