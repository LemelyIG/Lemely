#!/usr/bin/env python3
r"""LLM cost-ladder driver: baseline + A/A floor, one-lever screens, and the report.

Live runs spend Gemini budget. Keys are read inside this process from
~/.config/lemely/{anthropic,gemini}_key (an exported variable wins); this script never prints them.
The default spend ledger is per worktree (repo-relative): run all ladder commands from one checkout.

    cost_ladder.py [--config base.toml] [--split dev|real|both] [--repeats 1|2] \\
        baseline [--restart-baseline | --aa-only]
    cost_ladder.py ... screen --label L --lever "..." --expected-saving 40% \\
        --judge cost|accuracy|record --set gemini.correction_model=... \\
        [--against <label>] [--live-tags correction,...]
    cost_ladder.py --split real --config gemini.toml reference-rung --label gemini \\
        --dev-from OLD/summary.json
    cost_ladder.py judge-flip --candidate stack --gemini gemini
    cost_ladder.py resummarise --label L        # $0, dev runs only
    cost_ladder.py report --stop-reason "..."
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from lemely.accuracy.cost_ladder.real_split import (
    DEFAULT_MANIFEST,
    ReferenceDrift,
    load_real_scripts,
)
from lemely.accuracy.cost_ladder.report import write_flip, write_report
from lemely.accuracy.cost_ladder.runner import (
    BASELINE_LABEL,
    DEFAULT_LIVE_TAGS,
    LadderStateError,
    apply_overrides,
    flip_verdict,
    parse_override_value,
    require_gemini_key,
    resummarise,
    run_baseline,
    run_reference_rung,
    run_screen,
)
from lemely.accuracy.cost_ladder.spend import DEFAULT_SPEND_FILE, SpendCapError, SpendCaps
from lemely.io.gemini import UnpricedModelError
from lemely.io.model_table import configured_models
from lemely.runtime.config import Settings, anthropic_key_missing_tags, load_settings

if TYPE_CHECKING:
    from lemely.accuracy.cost_ladder.real_split import RealScript

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


class _Refusal(Exception):
    """A command refused before any spend; main prints it and exits 2."""


# Everything else (a pydantic error, a corrupt file) surfaces with its traceback.
_REFUSALS = (
    _Refusal,
    LadderStateError,
    ReferenceDrift,
    SpendCapError,
    UnpricedModelError,
    FileNotFoundError,
)

_KEY_FILES = (
    ("ANTHROPIC_API_KEY", "~/.config/lemely/anthropic_key"),
    ("GEMINI_API_KEY", "~/.config/lemely/gemini_key"),
)


def load_keys() -> None:
    """Read the API keys from their files into this process; an exported value wins."""
    for var, key_path in _KEY_FILES:
        path = Path(key_path).expanduser()
        if path.is_file() and not os.environ.get(var):
            os.environ[var] = path.read_text(encoding="utf-8").strip()


def _settings(args: argparse.Namespace) -> Settings:
    return load_settings(toml_path=args.config) if args.config is not None else load_settings()


def _scripts(args: argparse.Namespace) -> list[RealScript] | tuple[()]:
    if args.split == "dev":
        return ()
    return load_real_scripts(args.manifest, only=args.only)


def _live(args: argparse.Namespace, sets: dict[str, object] | None = None) -> Settings:
    """Load the keys, then refuse before any spend if a configured model has no key."""
    load_keys()
    try:
        require_gemini_key(os.environ)
    except RuntimeError as exc:
        raise _Refusal(str(exc)) from exc
    settings = _settings(args)
    effective = apply_overrides(settings, sets or {})
    missing = anthropic_key_missing_tags(effective, configured_models(effective))
    if missing:
        models = configured_models(effective)
        raise _Refusal(
            "no ANTHROPIC_API_KEY (set it or write ~/.config/lemely/anthropic_key) but task tag(s) "
            + ", ".join(f"{t}={models[t]}" for t in missing)
            + " use a claude- model"
        )
    return settings


def _refuse_ladder_flags(args: argparse.Namespace) -> None:
    if args.split != "dev" or args.repeats != 1 or args.config is not None or args.only:
        raise _Refusal(
            f"{args.cmd} reads stored dev runs; --split/--repeats/--config/--only do not apply"
        )


def _baseline(args: argparse.Namespace) -> int:
    settings = _live(args)
    floor = run_baseline(
        out_dir=args.out_dir,
        golden_dir=args.golden,
        caps=_caps(args),
        max_run_usd=_max_run_usd(args),
        spend_file=args.spend_file,
        restart=args.restart_baseline,
        aa_only=args.aa_only,
        settings=settings,
        split=args.split,
        repeats=args.repeats,
        real_scripts=_scripts(args),
    )
    print(f"A/A floor: {floor} newly mismarked parts between two baseline runs")
    return 0


def _screen(args: argparse.Namespace) -> int:
    sets = _parse_sets(args.set)
    settings = _live(args, sets)
    live_tags = tuple(t.strip() for t in args.live_tags.split(",") if t.strip())
    verdict = run_screen(
        args.label,
        sets,
        out_dir=args.out_dir,
        against=args.against,
        live_tags=live_tags,
        lever=args.lever,
        expected_saving=args.expected_saving,
        golden_dir=args.golden,
        caps=_caps(args),
        max_run_usd=_max_run_usd(args),
        spend_file=args.spend_file,
        settings=settings,
        split=args.split,
        repeats=args.repeats,
        judge_kind=args.judge,
        real_scripts=_scripts(args),
    )
    print(
        f"{'ACCEPT' if verdict.passed else 'REJECT'} {args.label} "
        f"(stacked on {args.against}): saving {verdict.saving:.1%}"
    )
    for reason in verdict.reasons:
        print(f"  - {reason}")
    for note in verdict.notes:
        print(f"  note: {note}")
    return 0 if verdict.passed else 1


def _reference_rung(args: argparse.Namespace) -> int:
    settings = _live(args)
    summary = run_reference_rung(
        args.label,
        out_dir=args.out_dir,
        real_scripts=_scripts(args) or load_real_scripts(args.manifest, only=args.only),
        dev_summary_from=args.dev_from,
        settings=settings,
        repeats=2,  # the Gemini rung always runs twice (spec P4)
        caps=_caps(args),
        max_run_usd=_max_run_usd(args),
        spend_file=args.spend_file,
    )
    print(
        f"reference rung {args.label}: real abs error {summary.real_abs_error:.1f}, "
        f"mean ${summary.real_usd_mean:.4f}/script"
    )
    return 0


def _judge_flip(args: argparse.Namespace) -> int:
    verdict = flip_verdict(args.out_dir, candidate=args.candidate, gemini=args.gemini)
    target = write_flip(args.out_dir, candidate=args.candidate, gemini=args.gemini)
    print(
        f"{'PASS' if verdict.passed else 'FAIL'} flip {args.candidate} vs {args.gemini}: {target}"
    )
    for reason in verdict.reasons:
        print(f"  - {reason}")
    return 0 if verdict.passed else 1


def _resummarise(args: argparse.Namespace) -> int:
    # $0: stored records only. No key, no client, no spend.
    _refuse_ladder_flags(args)
    summary = resummarise(args.label, out_dir=args.out_dir)
    print(
        f"resummarised {args.label}: ${summary.usd_per_script_mean:.4f}/script (2027), "
        f"validity {summary.validity_rate:.3f}, "
        f"incomplete: {', '.join(summary.incomplete) or 'none'}"
    )
    return 0


def _report(args: argparse.Namespace) -> int:
    _refuse_ladder_flags(args)
    target = write_report(args.out_dir, stop_reason=args.stop_reason)
    print(f"wrote {target}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--golden", type=Path, default=GOLDEN_DIR)
    parser.add_argument("--cap-gemini-usd", type=float, default=SpendCaps().gemini_usd)
    parser.add_argument("--cap-anthropic-usd", type=float, default=SpendCaps().anthropic_usd)
    parser.add_argument("--config", type=Path, default=None, help="lemely TOML every run uses")
    parser.add_argument("--split", choices=("dev", "real", "both"), default="dev")
    parser.add_argument("--repeats", type=int, choices=(1, 2), default=1)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--only", action="append", default=[], metavar="KEY")
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
    screen.add_argument("--judge", choices=("cost", "accuracy", "record"), default="cost")
    screen.set_defaults(fn=_screen)
    resum = sub.add_parser(
        "resummarise", help="$0: recompute a run's summary.json from its stored records"
    )
    resum.add_argument("--label", required=True)
    resum.set_defaults(fn=_resummarise)
    rung = sub.add_parser("reference-rung", help="a comparison rung (the Gemini rung)")
    rung.add_argument("--label", required=True)
    rung.add_argument("--dev-from", type=Path, required=True, help="a complete dev summary.json")
    rung.set_defaults(fn=_reference_rung)
    flip = sub.add_parser("judge-flip", help="judge_flip of a rung against the Gemini rung")
    flip.add_argument("--candidate", required=True)
    flip.add_argument("--gemini", required=True)
    flip.set_defaults(fn=_judge_flip)
    report = sub.add_parser("report")
    report.add_argument("--stop-reason", required=True)
    report.set_defaults(fn=_report)
    args = parser.parse_args(argv)
    try:
        return int(args.fn(args))
    except _REFUSALS as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        if type(exc) is not ValueError:  # pydantic / JSON errors are not argument refusals
            raise
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
