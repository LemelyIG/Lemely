#!/usr/bin/env python3
r"""LLM cost-ladder driver: baseline + A/A floor, one-lever screens, and the report.

Live runs spend Gemini budget. Keys come from the environment only (a wrapper
exports GEMINI_API_KEY / ANTHROPIC_API_KEY); this script never prints them.
The default spend ledger is per worktree (repo-relative): run all ladder commands from one checkout.

    cost_ladder.py baseline [--restart-baseline | --aa-only]
    cost_ladder.py screen --label L --lever "..." --expected-saving 40% \\
        --set gemini.correction_model=... [--against <label>] \\
        [--live-tags correction,correction_borderline,escalation]
    cost_ladder.py resummarise --label L        # $0, from stored records; not judged runs
    cost_ladder.py report --stop-reason "..."
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from lemely.accuracy.cost_ladder.report import write_report
from lemely.accuracy.cost_ladder.runner import (
    BASELINE_LABEL,
    DEFAULT_LIVE_TAGS,
    parse_override_value,
    require_gemini_key,
    resummarise,
    run_baseline,
    run_screen,
)
from lemely.accuracy.cost_ladder.spend import DEFAULT_SPEND_FILE, SpendCaps
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


def _max_run_usd(args: argparse.Namespace) -> dict[str, float] | None:
    max_run: dict[str, float] = {}
    for pair in args.max_run_usd:
        provider, sep, raw = pair.partition("=")
        if not sep:
            raise SystemExit(f"--max-run-usd expects provider=usd, got {pair!r}")
        max_run[provider] = float(raw)
    return max_run or None


def _caps(args: argparse.Namespace) -> SpendCaps:
    return SpendCaps(gemini_usd=args.cap_gemini_usd, anthropic_usd=args.cap_anthropic_usd)


def _baseline(args: argparse.Namespace) -> int:
    require_gemini_key(os.environ)
    floor = run_baseline(
        out_dir=args.out_dir,
        golden_dir=args.golden,
        caps=_caps(args),
        max_run_usd=_max_run_usd(args),
        spend_file=args.spend_file,
        restart=args.restart_baseline,
        aa_only=args.aa_only,
    )
    print(f"A/A floor: {floor} newly mismarked parts between two baseline runs")
    return 0


def _screen(args: argparse.Namespace) -> int:
    require_gemini_key(os.environ)
    live_tags = tuple(t.strip() for t in args.live_tags.split(",") if t.strip())
    verdict = run_screen(
        args.label,
        _parse_sets(args.set),
        out_dir=args.out_dir,
        against=args.against,
        live_tags=live_tags,
        lever=args.lever,
        expected_saving=args.expected_saving,
        golden_dir=args.golden,
        caps=_caps(args),
        max_run_usd=_max_run_usd(args),
        spend_file=args.spend_file,
    )
    print(
        f"{'ACCEPT' if verdict.passed else 'REJECT'} {args.label} "
        f"(stacked on {args.against}): saving {verdict.saving:.1%}"
    )
    for reason in verdict.reasons:
        print(f"  - {reason}")
    return 0 if verdict.passed else 1


def _resummarise(args: argparse.Namespace) -> int:
    # $0: stored records only. No key, no client, no spend.
    summary = resummarise(args.label, out_dir=args.out_dir)
    print(
        f"resummarised {args.label}: ${summary.usd_per_script_mean:.4f}/script (2027), "
        f"validity {summary.validity_rate:.3f}, "
        f"incomplete: {', '.join(summary.incomplete) or 'none'}"
    )
    return 0


def _report(args: argparse.Namespace) -> int:
    target = write_report(args.out_dir, stop_reason=args.stop_reason)
    print(f"wrote {target}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--golden", type=Path, default=GOLDEN_DIR)
    parser.add_argument("--cap-gemini-usd", type=float, default=SpendCaps().gemini_usd)
    parser.add_argument("--cap-anthropic-usd", type=float, default=SpendCaps().anthropic_usd)
    parser.add_argument(
        "--max-run-usd",
        action="append",
        default=[],
        metavar="provider=usd",
        help="projected per-provider cost of a run; the larger of this and the last run's cost",
    )
    parser.add_argument(
        "--spend-file",
        type=Path,
        default=None,
        help=(
            f"combined spend ledger (default {DEFAULT_SPEND_FILE}, whatever --out-dir is). "
            "The default is per worktree (repo-relative): "
            "run all ladder commands from one checkout."
        ),
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    baseline = sub.add_parser("baseline")
    mode = baseline.add_mutually_exclusive_group()
    mode.add_argument(
        "--restart-baseline",
        action="store_true",
        help="delete this out-dir's baseline cache, baseline and A/A runs first (spend is kept)",
    )
    mode.add_argument(
        "--aa-only", action="store_true", help="rerun only the A/A run against the baseline"
    )
    baseline.set_defaults(fn=_baseline)
    screen = sub.add_parser("screen")
    screen.add_argument("--label", required=True)
    screen.add_argument("--lever")
    screen.add_argument("--expected-saving", default="n/a")
    screen.add_argument("--set", action="append", default=[], metavar="key=value")
    screen.add_argument(
        "--against",
        default=BASELINE_LABEL,
        help="label of the accepted run this lever stacks on (overrides and live tags inherit)",
    )
    screen.add_argument(
        "--live-tags",
        default=",".join(DEFAULT_LIVE_TAGS),
        help="comma-separated task tags called live; all others replay the baseline cache",
    )
    screen.set_defaults(fn=_screen)
    resum = sub.add_parser(
        "resummarise", help="$0: recompute a run's summary.json from its stored records"
    )
    resum.add_argument("--label", required=True)
    resum.set_defaults(fn=_resummarise)
    report = sub.add_parser("report")
    report.add_argument("--stop-reason", required=True)
    report.set_defaults(fn=_report)
    args = parser.parse_args(argv)
    try:
        return int(args.fn(args))
    except (RuntimeError, ValueError, FileNotFoundError, UnpricedModelError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
