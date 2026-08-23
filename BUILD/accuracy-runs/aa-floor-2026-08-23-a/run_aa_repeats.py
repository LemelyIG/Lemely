"""Driver for the aa-repeats arm of run_label=aa-floor-2026-08-23-a.

Runs the IDENTICAL configuration (full golden corpus, extract+mark arm,
cache_mode='bypass') N times, capturing per-call Gemini usage tokens via a
structlog capture processor, re-costing at corrected GA pricing
($0.30/1M in, $2.50/1M out, thoughts counted as output), and writing one
EvalRecord-jsonl file plus a per-repeat manifest per repeat. Stops early
(completed=false) if cumulative re-costed spend reaches 150% of the
preflight estimate ($1.58 -> stop at $2.37).
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import structlog

REPO = Path("/home/sico/Lemely-worktrees/accuracy")
WORKDIR = REPO / "BUILD/accuracy-runs/aa-floor-2026-08-23-a"
N_REPEATS = 10
STOP_USD = 1.58 * 1.5  # 150% of preflight estimate
IN_PRICE_PER_TOK = 0.30 / 1_000_000
OUT_PRICE_PER_TOK = 2.50 / 1_000_000  # candidates + thoughts

sys.path.insert(0, str(REPO))

captured_calls: list[dict] = []


def _capture_processor(_logger, _name, event_dict):
    event = event_dict.get("event")
    if event in ("gemini_call", "gemini_cache_hit"):
        captured_calls.append(dict(event_dict))
    return event_dict


def configure_capture_logging() -> None:
    """Configure structlog with our capture processor inserted, JSON to stderr."""
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        _capture_processor,
    ]
    structlog.configure(
        processors=[*shared_processors, structlog.processors.JSONRenderer()],
        wrapper_class=structlog.make_filtering_bound_logger(20),  # INFO
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )


def main() -> None:
    configure_capture_logging()

    from lemely.accuracy.harness import load_golden_cases, measure_accuracy
    from lemely.io.gemini import GeminiClient
    from lemely.runtime.config import load_settings

    settings = load_settings()
    golden_dir = REPO / "tests/golden"
    cases = load_golden_cases(golden_dir)

    git_sha = subprocess.check_output(
        ["git", "-C", str(REPO), "rev-parse", "HEAD"], text=True
    ).strip()

    corpus_listing = sorted(p.name for p in golden_dir.iterdir() if p.is_dir() and p.name != "results")

    cumulative_recosted_usd = 0.0
    repeats_summary = []
    anomalies: list[str] = []
    run_ids: list[str] = []
    completed = True

    for i in range(1, N_REPEATS + 1):
        repeat_label = f"repeat-{i:02d}"
        run_id_ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        run_id = f"aa-floor-2026-08-23-a-aa-repeats-{repeat_label}-{run_id_ts}"
        run_ids.append(run_id)

        captured_calls.clear()

        attempt = 0
        max_attempts = 2  # one retry if a cache HIT is observed
        result = None
        cache_hit_detected = False

        while attempt < max_attempts:
            attempt += 1
            captured_calls.clear()
            client = GeminiClient(settings, default_cache_mode="bypass")
            try:
                result = measure_accuracy(
                    cases,
                    client,
                    settings,
                    run_id=f"{run_id}-a{attempt}",
                    split="dev",
                )
            except Exception as exc:  # noqa: BLE001
                anomalies.append(f"{repeat_label} attempt {attempt}: EXCEPTION {exc!r}")
                result = None
                break

            cache_hit_events = [c for c in captured_calls if c.get("event") == "gemini_cache_hit"]
            if cache_hit_events:
                cache_hit_detected = True
                anomalies.append(
                    f"{repeat_label} attempt {attempt}: {len(cache_hit_events)} cache HIT(s) "
                    f"observed under cache_mode=bypass -- INVALID, rerunning once"
                )
                if attempt < max_attempts:
                    continue
                else:
                    anomalies.append(
                        f"{repeat_label}: cache HIT again on retry -- repeat invalid, aborting sweep"
                    )
                    completed = False
                    result = None
            break

        if result is None:
            completed = False
            break

        # Sum usage from captured gemini_call events (real API calls only).
        call_events = [c for c in captured_calls if c.get("event") == "gemini_call"]
        sum_in = sum(int(c.get("input_tokens", 0) or 0) for c in call_events)
        sum_out_total = sum(int(c.get("output_tokens", 0) or 0) for c in call_events)  # candidates+thoughts
        sum_thoughts = sum(int(c.get("thoughts_tokens", 0) or 0) for c in call_events)
        n_calls = len(call_events)

        repeat_recosted_usd = sum_in * IN_PRICE_PER_TOK + sum_out_total * OUT_PRICE_PER_TOK
        cumulative_recosted_usd += repeat_recosted_usd

        # Write records file (EvalRecords from this repeat).
        records_path = WORKDIR / f"records-{repeat_label}.jsonl"
        with records_path.open("w", encoding="utf-8") as fh:
            for rec in result.eval_records:
                fh.write(json.dumps(rec.model_dump(mode="json")) + "\n")

        # Per-repeat manifest.
        manifest_path = WORKDIR / f"manifest-{repeat_label}.json"
        manifest_data = result.manifest.model_dump(mode="json")
        manifest_data["_actual_cache_mode_requested"] = "bypass"
        manifest_data["_n_gemini_calls"] = n_calls
        manifest_data["_sum_input_tokens"] = sum_in
        manifest_data["_sum_output_tokens_incl_thoughts"] = sum_out_total
        manifest_data["_sum_thoughts_tokens"] = sum_thoughts
        manifest_data["_recosted_usd_corrected_pricing"] = round(repeat_recosted_usd, 6)
        manifest_data["_cache_hit_detected_any_attempt"] = cache_hit_detected
        manifest_data["_attempts"] = attempt
        manifest_path.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")

        repeats_summary.append(
            {
                "repeat_label": repeat_label,
                "run_id": manifest_data["run_id"],
                "n_gemini_calls": n_calls,
                "input_tokens": sum_in,
                "output_tokens_incl_thoughts": sum_out_total,
                "thoughts_tokens": sum_thoughts,
                "recosted_usd": round(repeat_recosted_usd, 6),
                "cache_hit_detected": cache_hit_detected,
                "attempts": attempt,
                "mark_accuracy": result.metrics.mark_accuracy,
                "mark_accuracy_theory": result.metrics.mark_accuracy_theory,
                "id_match_rate": result.metrics.id_match_rate,
                "flag_precision_high": result.metrics.flag_precision_high,
                "flag_recall": result.metrics.flag_recall,
                "funnel": {
                    "leaves": result.funnel.leaves,
                    "extracted": result.funnel.extracted,
                    "matched": result.funnel.matched,
                    "marked": result.funnel.marked,
                },
                "n_eval_records": len(result.eval_records),
                "records_path": str(records_path),
                "manifest_path": str(manifest_path),
            }
        )

        print(
            f"[{repeat_label}] calls={n_calls} in={sum_in} out(incl thoughts)={sum_out_total} "
            f"recosted_usd={repeat_recosted_usd:.4f} cumulative_usd={cumulative_recosted_usd:.4f} "
            f"mark_accuracy={result.metrics.mark_accuracy:.4f}",
            file=sys.stderr,
        )

        if cumulative_recosted_usd >= STOP_USD:
            anomalies.append(
                f"STOPPED after {repeat_label}: cumulative re-costed spend "
                f"${cumulative_recosted_usd:.4f} reached 150% of preflight estimate "
                f"(${STOP_USD:.4f}) -- estimate was wrong, human review needed"
            )
            completed = False
            break

    top_manifest = {
        "run_label": "aa-floor-2026-08-23-a",
        "arm": "aa-repeats",
        "git_sha": git_sha,
        "model": settings.gemini.model,
        "cache_mode_requested": "bypass",
        "split": "dev (pre-M0.7a)",
        "n_repeats_planned": N_REPEATS,
        "n_repeats_completed": len(repeats_summary),
        "completed": completed,
        "corpus_listing": corpus_listing,
        "corpus_digest": repeats_summary[0]["manifest_path"] if repeats_summary else None,
        "cumulative_recosted_usd": round(cumulative_recosted_usd, 6),
        "preflight_estimate_usd": 1.58,
        "stop_threshold_usd": round(STOP_USD, 6),
        "run_ids": run_ids,
        "anomalies": anomalies,
        "repeats": repeats_summary,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    (WORKDIR / "manifest.json").write_text(json.dumps(top_manifest, indent=2), encoding="utf-8")
    print(json.dumps({"completed": completed, "cumulative_recosted_usd": cumulative_recosted_usd, "anomalies": anomalies}))


if __name__ == "__main__":
    main()
