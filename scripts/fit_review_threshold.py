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

Usage: ``python scripts/fit_review_threshold.py BUILD/.../a1-haiku/results.json``
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

#: The reason ``lemely.io.correction_ai`` writes when confidence alone flags a part.
_CONFIDENCE_REASON = re.compile(r"^confidence \d+(?:\.\d+)? below review threshold \d+(?:\.\d+)?$")
#: Float slack when comparing a rate with the target (2/20 must count as 10%).
_EPS = 1e-9


@dataclass(frozen=True)
class Part:
    """One scored part of the screen, reduced to what the review decision reads."""

    case_key: str
    question_id: str
    confidence: float
    mismarked: bool
    #: True when the threshold being fitted decides this part's flag.
    refittable: bool
    #: The flag the run recorded; used as-is when ``refittable`` is False.
    recorded_flag: bool


@dataclass(frozen=True)
class ThresholdStats:
    threshold: float
    scored: int
    flagged: int
    mismarked: int
    flagged_mismarked: int

    @property
    def review_rate(self) -> float:
        return self.flagged / self.scored if self.scored else 0.0

    @property
    def flag_recall(self) -> float | None:
        return self.flagged_mismarked / self.mismarked if self.mismarked else None

    @property
    def precision(self) -> float | None:
        return self.flagged_mismarked / self.flagged if self.flagged else None


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
            isinstance(reason, str) and _CONFIDENCE_REASON.match(reason) is not None
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


def _flagged(part: Part, threshold: float) -> bool:
    return part.confidence < threshold if part.refittable else part.recorded_flag


def evaluate(parts: Sequence[Part], threshold: float) -> ThresholdStats:
    """Review rate, recall and precision with ``threshold`` for the refittable parts."""
    flagged = [p for p in parts if _flagged(p, threshold)]
    return ThresholdStats(
        threshold=threshold,
        scored=len(parts),
        flagged=len(flagged),
        mismarked=sum(p.mismarked for p in parts),
        flagged_mismarked=sum(p.mismarked for p in flagged),
    )


def threshold_grid() -> list[float]:
    """0.50, 0.51, ..., 0.99, built from integers so each value is the literal."""
    return [c / 100 for c in range(50, 100)]


def recommend(parts: Sequence[Part], *, target: float) -> float | None:
    """The highest grid threshold with review rate <= ``target``; None if none is."""
    within = [t for t in threshold_grid() if evaluate(parts, t).review_rate <= target + _EPS]
    return max(within) if within else None


def leave_one_case_out(parts: Sequence[Part], *, target: float) -> dict[str, float | None]:
    """The recommendation refitted without each case in turn, keyed by the case left out."""
    cases = sorted({p.case_key for p in parts})
    return {
        case: recommend([p for p in parts if p.case_key != case], target=target) for case in cases
    }


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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0] if __doc__ else None)
    parser.add_argument("results", type=Path, help="a screen's results.json")
    parser.add_argument(
        "--records", type=Path, default=None, help="records.jsonl (default: beside results)"
    )
    parser.add_argument("--target", type=float, default=0.10, help="max review rate")
    args = parser.parse_args(argv)
    parts = load_parts(args.results, args.records)
    sys.stdout.write(render(parts, target=args.target) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
