#!/usr/bin/env python3
"""Refit the review-confidence threshold for a correction model, at $0.

Reads a screen's ``results.json`` (and, beside it, ``records.jsonl``) and replays
the human-review decision for every threshold from 0.50 to 0.99 in steps of 0.01.
For each threshold it reports the review rate (flagged scored parts / scored
parts), the flag recall (flagged mismarked parts / mismarked parts) and the
precision (flagged mismarked parts / flagged parts). It recommends the highest
threshold whose review rate is within ``--target`` (default 10%).

Only a part whose final mark the screen's correction model gave moves with the
threshold. These keep the flag the run recorded:

- a part flagged for a structural reason (out of range, value or coherence
  mismatch, no span): it is flagged at any threshold;
- a part not marked by AI (``marker_source != "ai"``, e.g. a deterministic MCQ);
- a part with an ``escalation`` call in ``records.jsonl``: its final mark came
  from the escalation model, whose threshold is not the one being fitted.

The fit is in-sample: it is judged on the same cases it is fitted on. The
leave-one-case-out table shows how far the recommendation moves when any one
case is left out, which is the only stability evidence a 12-case screen gives.

Real mode (``--real RUN_DIR``, repeatable) reads each run's ``real_results.json`` and
fits the lowest threshold that flags at least 90% of leaves with abs_error > 0;
``--escalation`` adds the escalation-threshold fit under the per-script cap. Leaves with
no confidence (never scored) are excluded and counted.

Usage: ``python scripts/fit_review_threshold.py BUILD/.../a1-haiku/results.json``
   or: ``python scripts/fit_review_threshold.py --real RUN_DIR [--real RUN_DIR2] [--escalation]``
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from lemely.accuracy.threshold_fit import (
    CONFIDENCE_REASON,
    Part,
    ThresholdStats,
    case_base_usd,
    escalation_leaves,
    escalation_price,
    evaluate,
    fit_escalation_threshold,
    leave_one_case_out,
    parts_from_real,
    recommend,
    recommend_for_recall,
    threshold_grid,
    unscored_escalation_leaves,
    unscored_leaves,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = [
    "Part",
    "ThresholdStats",
    "evaluate",
    "leave_one_case_out",
    "recommend",
    "threshold_grid",
]


def _escalated(records_path: Path) -> set[tuple[str, str]]:
    """(case_key, question_id) of every part with an escalation call."""
    if not records_path.is_file():
        return set()
    out: set[tuple[str, str]] = set()
    for line in records_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        if rec.get("task_tag") == "escalation" and rec.get("question_id") is not None:
            out.add((str(rec.get("case_key")), str(rec["question_id"])))
    return out


def load_parts(results_path: Path, records_path: Path | None = None) -> list[Part]:
    """The scored parts of ``results_path``; records default to ``records.jsonl`` beside it."""
    data = json.loads(results_path.read_text(encoding="utf-8"))
    escalated = _escalated(records_path or results_path.with_name("records.jsonl"))
    parts: list[Part] = []
    for row in data["question_results"]:
        if row.get("scored") is not True:
            continue
        case_key, qid = str(row["case_key"]), str(row["question_id"])
        flag = row.get("needs_teacher_review") is True
        reason = row.get("review_reason")
        structural = flag and not (
            isinstance(reason, str) and CONFIDENCE_REASON.match(reason) is not None
        )
        refittable = (
            row.get("marker_source") == "ai" and not structural and (case_key, qid) not in escalated
        )
        parts.append(
            Part(
                case_key=case_key,
                question_id=qid,
                confidence=float(row["confidence_score"]),
                mismarked=row.get("predicted_marks") != row.get("truth_marks"),
                refittable=refittable,
                recorded_flag=flag,
            )
        )
    return parts


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def render(parts: Sequence[Part], *, target: float) -> str:
    """The markdown report: the table, the recommendation and its LOO stability."""
    lines = [
        f"scored parts: {len(parts)}; refittable: {sum(p.refittable for p in parts)}; "
        f"mismarked: {sum(p.mismarked for p in parts)}",
        "",
        "| threshold | flagged | review rate | flag recall | precision |",
        "|---|---|---|---|---|",
    ]
    for t in threshold_grid():
        s = evaluate(parts, t)
        lines.append(
            f"| {t:.2f} | {s.flagged} | {s.review_rate:.3f} | {_fmt(s.flag_recall)} "
            f"| {_fmt(s.precision)} |"
        )
    best = recommend(parts, target=target)
    lines += ["", f"target review rate: <= {target:.2f}"]
    if best is None:
        lines.append("recommended threshold: none (no threshold meets the target)")
    else:
        s = evaluate(parts, best)
        lines.append(
            f"recommended threshold: {best:.2f} (review rate {s.review_rate:.3f}, "
            f"flag recall {_fmt(s.flag_recall)}, precision {_fmt(s.precision)})"
        )
    lines += [
        "",
        "leave-one-case-out (case left out -> refitted threshold):",
        "",
        "| case left out | threshold |",
        "|---|---|",
    ]
    for case, value in leave_one_case_out(parts, target=target).items():
        lines.append(f"| {case} | {'none' if value is None else f'{value:.2f}'} |")
    return "\n".join(lines)


def _real_report(args: argparse.Namespace) -> str:
    paths = [d / "real_results.json" for d in args.real]
    parts = parts_from_real(paths)
    best = recommend_for_recall(parts)
    stats = evaluate(parts, best) if best is not None else None
    lines = [
        render(parts, target=args.target),
        "",
        f"review fit: leaves excluded for having no confidence (never scored): "
        f"{unscored_leaves(paths)}",
        "lowest threshold flagging >= 90% of leaves with abs_error > 0: "
        + ("none (no basis)" if best is None else f"{best:.2f}")
        + ("" if stats is None else f" (review rate {stats.review_rate:.3f})"),
    ]
    if args.escalation:
        records = [
            json.loads(line)
            for d in args.real
            for line in (d / "records.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        per_call, notes = escalation_price(records)
        fitted = fit_escalation_threshold(
            escalation_leaves(paths),
            case_base_usd=case_base_usd(paths),
            usd_per_escalation=per_call,
            cap_usd=args.cap_usd,
        )
        recall = "n/a" if fitted.recall is None else f"{fitted.recall:.3f}"
        worst = (
            "n/a"
            if fitted.worst_script_usd is None
            else f"{fitted.worst_script} ${fitted.worst_script_usd:.4f}"
        )
        lines += [
            f"escalation fit: AI-marked leaves excluded for having no confidence "
            f"(never scored): {unscored_escalation_leaves(paths)}",
            *notes,
            "escalation_confidence_threshold: "
            + ("none" if fitted.threshold is None else f"{fitted.threshold:.2f}")
            + f" (recall {recall}, escalated {fitted.escalated} leaves over the runs, "
            f"worst case {worst}, per escalation ${per_call:.4f}, "
            + ("recall target met" if fitted.met_recall else "recall target NOT met")
            + (f"; reason: {fitted.reason}" if fitted.reason else "")
            + ")",
        ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0] if __doc__ else None)
    parser.add_argument("results", type=Path, nargs="?", help="a screen's results.json")
    parser.add_argument(
        "--records", type=Path, default=None, help="records.jsonl (default: beside results)"
    )
    parser.add_argument("--target", type=float, default=0.10, help="max review rate")
    parser.add_argument(
        "--real",
        type=Path,
        action="append",
        default=[],
        metavar="RUN_DIR",
        help="a real run dir (holds real_results.json)",
    )
    parser.add_argument(
        "--escalation",
        action="store_true",
        help="with --real: also fit escalation_confidence_threshold",
    )
    parser.add_argument("--cap-usd", type=float, default=0.10)
    args = parser.parse_args(argv)
    if args.escalation and not args.real:
        parser.error("--escalation needs --real RUN_DIR")
    if args.real:
        missing = [
            d / name
            for d in args.real
            for name in ("real_results.json", *(("records.jsonl",) if args.escalation else ()))
            if not (d / name).is_file()
        ]
        if missing:
            parser.error(f"missing file(s): {', '.join(str(m) for m in missing)}")
        try:
            report = _real_report(args)
        except ValueError as exc:
            parser.error(str(exc))
        sys.stdout.write(report + "\n")
        return 0
    if args.results is None:
        parser.error("give a results.json or --real RUN_DIR")
    parts = load_parts(args.results, args.records)
    sys.stdout.write(render(parts, target=args.target) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
