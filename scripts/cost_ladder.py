#!/usr/bin/env python3
r"""LLM cost-ladder driver: baseline + A/A floor, one-lever screens, and the report.

Live runs spend Gemini budget. Keys come from the environment only (a wrapper
exports GEMINI_API_KEY / ANTHROPIC_API_KEY); this script never prints them.

    cost_ladder.py baseline
    cost_ladder.py screen --label L --lever "..." --expected-saving 40% \\
        --set gemini.correction_model=... [--against runs/baseline/summary.json]
    cost_ladder.py report --stop-reason "..."
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from lemely.accuracy.cost_ladder.gate import aa_floor, judge
from lemely.accuracy.cost_ladder.report import LadderFooter, LadderRow, write_ladder
from lemely.accuracy.cost_ladder.runner import (
    parse_override_value,
    read_summary,
    require_gemini_key,
    run_config,
)
from lemely.accuracy.cost_ladder.spend import SpendCaps
from lemely.io.gemini import UnpricedModelError

DEFAULT_OUT_DIR = Path("reports/cost-ladder")
GOLDEN_DIR = Path("tests/golden")


def _parse_sets(pairs: list[str]) -> dict[str, object]:
    out: dict[str, object] = {}
    for pair in pairs:
        key, sep, raw = pair.partition("=")
        if not sep:
            raise SystemExit(f"--set expects key=value, got {pair!r}")
        out[key] = parse_override_value(raw)
    return out


def _run_kwargs(args: argparse.Namespace) -> dict[str, object]:
    max_run: dict[str, float] = {}
    for pair in args.max_run_usd:
        provider, sep, raw = pair.partition("=")
        if not sep:
            raise SystemExit(f"--max-run-usd expects provider=usd, got {pair!r}")
        max_run[provider] = float(raw)
    return {
        "out_dir": args.out_dir,
        "golden_dir": args.golden,
        "caps": SpendCaps(gemini_usd=args.cap_gemini_usd, anthropic_usd=args.cap_anthropic_usd),
        "max_run_usd": max_run or None,
    }


def _now_usd(run_dir: Path) -> float:
    return float(json.loads((run_dir / "summary.json").read_text())["usd_per_script_mean_now"])


def _baseline(args: argparse.Namespace) -> int:
    require_gemini_key(os.environ)
    out_dir: Path = args.out_dir
    a = run_config("baseline", {}, **_run_kwargs(args))
    b = run_config("baseline_aa", {}, **_run_kwargs(args))
    floor = aa_floor(a, b)
    (out_dir / "aa_floor.json").write_text(json.dumps({"aa_floor": floor}) + "\n")
    print(f"A/A floor: {floor} newly mismarked parts between two baseline runs")
    return 0


def _screen(args: argparse.Namespace) -> int:
    require_gemini_key(os.environ)
    out_dir: Path = args.out_dir
    against: Path = args.against or out_dir / "baseline" / "summary.json"
    baseline = read_summary(against)
    floor = int(json.loads((out_dir / "aa_floor.json").read_text())["aa_floor"])
    overrides = _parse_sets(args.set)
    candidate = run_config(args.label, overrides, **_run_kwargs(args))
    verdict = judge(
        baseline,
        candidate,
        aa_floor=floor,
        original_latency_p95_ms=baseline.latency_p95_ms,
    )
    run_dir = out_dir / args.label
    (run_dir / "verdict.json").write_text(
        json.dumps(
            {
                "lever": args.lever or args.label,
                "expected_saving": args.expected_saving,
                "proof": str(run_dir),
                "against": str(against),
                "overrides": overrides,
                "passed": verdict.passed,
                "tier": verdict.tier,
                "saving": verdict.saving,
                "extra_mismarks": verdict.extra_mismarks,
                "allowed_extra": verdict.allowed_extra,
                "reasons": list(verdict.reasons),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    print(f"{'ACCEPT' if verdict.passed else 'REJECT'} {args.label}: saving {verdict.saving:.1%}")
    for reason in verdict.reasons:
        print(f"  - {reason}")
    return 0 if verdict.passed else 1


def _report(args: argparse.Namespace) -> int:
    from lemely.accuracy.cost_ladder.gate import Verdict

    out_dir: Path = args.out_dir
    rows: list[LadderRow] = []
    last_accepted = out_dir / "baseline"
    for vpath in sorted(out_dir.glob("*/verdict.json"), key=lambda p: p.stat().st_mtime):
        v = json.loads(vpath.read_text())
        verdict = Verdict(
            passed=v["passed"],
            tier=v["tier"],
            saving=v["saving"],
            extra_mismarks=v["extra_mismarks"],
            allowed_extra=v["allowed_extra"],
            reasons=tuple(v["reasons"]),
        )
        rows.append(
            LadderRow(
                lever=v["lever"],
                expected_saving=v["expected_saving"],
                candidate=read_summary(vpath.parent / "summary.json"),
                verdict=verdict,
                proof=v["proof"],
            )
        )
        if verdict.passed:
            last_accepted = vpath.parent
    base = out_dir / "baseline"
    footer = LadderFooter(
        baseline_usd_2026=_now_usd(base),
        baseline_usd_2027=read_summary(base / "summary.json").usd_per_script_mean,
        final_usd_2026=_now_usd(last_accepted),
        final_usd_2027=read_summary(last_accepted / "summary.json").usd_per_script_mean,
        stop_reason=args.stop_reason,
    )
    target = out_dir / "LADDER.md"
    write_ladder(rows, target, footer=footer)
    print(f"wrote {target}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--golden", type=Path, default=GOLDEN_DIR)
    parser.add_argument("--split", default="dev", choices=["dev"])
    parser.add_argument("--cap-gemini-usd", type=float, default=3.0)
    parser.add_argument("--cap-anthropic-usd", type=float, default=40.0)
    parser.add_argument(
        "--max-run-usd",
        action="append",
        default=[],
        metavar="provider=usd",
        help="projected per-provider cost of a first run (no earlier run to project from)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("baseline").set_defaults(fn=_baseline)
    screen = sub.add_parser("screen")
    screen.add_argument("--label", required=True)
    screen.add_argument("--lever")
    screen.add_argument("--expected-saving", default="n/a")
    screen.add_argument("--set", action="append", default=[], metavar="key=value")
    screen.add_argument("--against", type=Path)
    screen.set_defaults(fn=_screen)
    report = sub.add_parser("report")
    report.add_argument("--stop-reason", required=True)
    report.set_defaults(fn=_report)
    args = parser.parse_args(argv)
    try:
        return int(args.fn(args))
    except (RuntimeError, UnpricedModelError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
