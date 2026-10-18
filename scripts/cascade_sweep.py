#!/usr/bin/env python3
"""Fit the correction cascade's triggers offline, from a logged screen and the baseline.

No API calls. For every confidence threshold from 0.50 to 0.99 (step 0.01),
combined with each on/off setting of the disagreement and unaddressed-point
triggers, it simulates the marks and the 2027 cost per script a cascade would
produce, judges the result against the baseline with ``judge()``, and prints the
cheapest combination that passes with a saving.

Inputs:

- ``--screen DIR``: a cost-ladder run made with ``gemini.cascade_enabled=true``
  and ``LEMELY_CASCADE_LEAF_LOG=DIR/cascade_leaves.jsonl`` in the environment.
  Its ``summary.json`` gives the cheap marks' mismarks; the leaf log (one JSON
  line per marked leaf, written by ``lemely.io.correction_ai``) gives each
  leaf's first-pass confidence and marks, the second pass's marks, the
  unaddressed points, whether the screen escalated, and each call's cost.
- ``--baseline DIR``: the baseline run. Its ``summary.json`` is what the
  candidate is judged against and gives the strong model's mismarks; its
  ``records.jsonl`` gives the strong re-mark's cost and latency per leaf (the
  baseline's correction calls for that leaf) and every case's non-correction
  cost, which the cascade does not change.

A screen that gathers the most data runs with the second pass and the
unaddressed check on and a fitted threshold of 0 for the cheap model, so the
confidence trigger never short-circuits the second pass.

Where the logs cannot say what would have happened, the simulation assumes the
worse outcome and counts it as ``unknown``:

- a combination needs the second pass's marks but the screen never ran it: the
  trigger is taken to fire (the second pass and the strong call are paid for);
- a leaf the screen escalated keeps its cheap mark under a combination, and the
  strong re-mark gave different marks: the cheap mark is counted as mismarked.

Run with the repository on the path:
``PYTHONPATH=. python scripts/cascade_sweep.py --screen DIR --baseline DIR``.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from lemely.accuracy.cost_ladder.gate import RunSummary, Verdict, judge  # noqa: E402
from lemely.accuracy.cost_ladder.runner import read_summary  # noqa: E402

LEAF_LOG = "cascade_leaves.jsonl"
AA_FLOOR_FILE = "aa_floor.json"
CORRECTION_TAGS = frozenset({"correction", "correction_borderline", "escalation"})
THRESHOLDS = tuple(round(0.50 + step / 100, 2) for step in range(50))
P95_RANK = 0.95


@dataclass(frozen=True)
class Leaf:
    """One marked leaf as the screen's cascade logged it."""

    key: str  # "<case_key>/<question_id>", as in RunSummary.mismarked_parts
    case_key: str
    model: str
    confidence: float
    awarded: int
    pass2_awarded: int | None
    unaddressed: bool | None  # None: the response carried no point verdicts
    screen_escalated: bool
    strong_awarded: int | None
    usd_first: float
    usd_pass2: float | None
    usd_strong: float | None
    ms_first: float
    ms_pass2: float | None
    ms_strong: float | None


@dataclass(frozen=True)
class Combo:
    threshold: float
    disagreement: bool
    unaddressed: bool


@dataclass(frozen=True)
class Inputs:
    leaves: tuple[Leaf, ...]
    screen: RunSummary
    baseline: RunSummary
    aa_floor: int
    original_latency_p95_ms: float
    strong_usd: dict[str, float]  # leaf key -> baseline correction USD
    strong_ms: dict[str, float]
    upstream_usd: dict[str, float]  # case key -> baseline non-correction USD
    upstream_ms: dict[str, float]
    cases: tuple[str, ...]


@dataclass(frozen=True)
class Simulation:
    combo: Combo
    summary: RunSummary
    unknown: int


@dataclass(frozen=True)
class Choice:
    combo: Combo
    summary: RunSummary
    verdict: Verdict
    unknown: int


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    if not isinstance(value, int | float):
        raise ValueError(f"expected a number, got {value!r}")
    number = float(value)
    if math.isnan(number):
        raise ValueError("leaf log carries an unpriced (NaN) call; the screen is incomplete")
    return number


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int):
        raise ValueError(f"expected an integer, got {value!r}")
    return value


def _leaf(raw: dict[str, object]) -> Leaf:
    case_key = raw.get("case_key")
    question_id = raw.get("question_id")
    if not isinstance(case_key, str) or not isinstance(question_id, str):
        raise ValueError(f"leaf log line without case_key/question_id: {raw!r}")
    usd = raw["usd_2027"]
    ms = raw["latency_ms"]
    if not isinstance(usd, dict) or not isinstance(ms, dict):
        raise ValueError(f"leaf log line without usd_2027/latency_ms: {raw!r}")
    unaddressed_ids = raw.get("unaddressed_point_ids")
    confidence = _optional_float(raw["confidence"])
    awarded = _optional_int(raw["awarded_marks"])
    if confidence is None or awarded is None:
        raise ValueError(f"leaf log line without confidence/awarded_marks: {raw!r}")
    return Leaf(
        key=f"{case_key}/{question_id}",
        case_key=case_key,
        model=str(raw["model"]),
        confidence=confidence,
        awarded=awarded,
        pass2_awarded=_optional_int(raw.get("pass2_awarded_marks")),
        unaddressed=None if unaddressed_ids is None else bool(unaddressed_ids),
        screen_escalated=bool(raw.get("escalated")),
        strong_awarded=_optional_int(raw.get("strong_awarded_marks")),
        usd_first=_optional_float(usd.get("first")) or 0.0,
        usd_pass2=_optional_float(usd.get("pass2")),
        usd_strong=_optional_float(usd.get("strong")),
        ms_first=_optional_float(ms.get("first")) or 0.0,
        ms_pass2=_optional_float(ms.get("pass2")),
        ms_strong=_optional_float(ms.get("strong")),
    )


def read_leaves(path: Path) -> tuple[Leaf, ...]:
    """The leaf log, one leaf per key; a later line for the same leaf replaces an earlier one."""
    by_key: dict[str, Leaf] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            leaf = _leaf(json.loads(line))
            by_key[leaf.key] = leaf
    if not by_key:
        raise ValueError(f"{path} has no cascade leaves")
    return tuple(by_key.values())


def load_inputs(
    *,
    screen_dir: Path,
    baseline_dir: Path,
    leaf_log: Path | None = None,
    aa_floor: int | None = None,
    original_latency_p95_ms: float | None = None,
) -> Inputs:
    """Read everything the simulation needs; defaults follow the cost-ladder layout."""
    screen = read_summary(screen_dir / "summary.json")
    baseline = read_summary(baseline_dir / "summary.json")
    if aa_floor is None:
        floor_path = baseline_dir.parent / AA_FLOOR_FILE
        aa_floor = int(json.loads(floor_path.read_text(encoding="utf-8"))["aa_floor"])
    leaves = read_leaves(leaf_log or screen_dir / LEAF_LOG)

    strong_usd: dict[str, float] = {}
    strong_ms: dict[str, float] = {}
    upstream_usd: dict[str, float] = {}
    upstream_ms: dict[str, float] = {}
    cases: dict[str, None] = {}
    records = baseline_dir / "records.jsonl"
    for line in records.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        case = rec.get("case_key")
        if not isinstance(case, str):
            continue
        cases[case] = None
        usd = float(rec["usd_2027"])
        usd = 0.0 if math.isnan(usd) else usd
        ms = float(rec["latency_ms"])
        qid = rec.get("question_id")
        if rec.get("task_tag") in CORRECTION_TAGS and isinstance(qid, str):
            key = f"{case}/{qid}"
            strong_usd[key] = strong_usd.get(key, 0.0) + usd
            strong_ms[key] = strong_ms.get(key, 0.0) + ms
        else:
            upstream_usd[case] = upstream_usd.get(case, 0.0) + usd
            upstream_ms[case] = upstream_ms.get(case, 0.0) + ms
    for leaf in leaves:
        cases[leaf.case_key] = None

    return Inputs(
        leaves=leaves,
        screen=screen,
        baseline=baseline,
        aa_floor=aa_floor,
        original_latency_p95_ms=(
            baseline.latency_p95_ms if original_latency_p95_ms is None else original_latency_p95_ms
        ),
        strong_usd=strong_usd,
        strong_ms=strong_ms,
        upstream_usd=upstream_usd,
        upstream_ms=upstream_ms,
        cases=tuple(cases),
    )


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _nearest_rank(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(math.ceil(q * len(ordered)) - 1, 0)]


def simulate(inputs: Inputs, combo: Combo) -> Simulation:
    """The run summary a cascade with *combo* would have produced on the screen's cases."""
    usd = {case: inputs.upstream_usd.get(case, 0.0) for case in inputs.cases}
    ms = {case: inputs.upstream_ms.get(case, 0.0) for case in inputs.cases}
    mean_strong_usd = _mean(list(inputs.strong_usd.values()))
    mean_strong_ms = _mean(list(inputs.strong_ms.values()))
    logged = {leaf.key for leaf in inputs.leaves}
    mismarked = {k for k in inputs.screen.mismarked_parts if k not in logged}
    unknown = 0

    for leaf in inputs.leaves:
        cost, latency = leaf.usd_first, leaf.ms_first
        fire = leaf.confidence < combo.threshold or (combo.unaddressed and leaf.unaddressed is True)
        if not fire and combo.disagreement:
            cost += leaf.usd_pass2 if leaf.usd_pass2 is not None else leaf.usd_first
            latency += leaf.ms_pass2 if leaf.ms_pass2 is not None else leaf.ms_first
            if leaf.pass2_awarded is None:
                unknown += 1
                fire = True
            else:
                fire = leaf.pass2_awarded != leaf.awarded

        if fire:
            if leaf.screen_escalated and leaf.usd_strong is not None:
                cost += leaf.usd_strong
                latency += leaf.ms_strong or 0.0
            else:
                cost += inputs.strong_usd.get(leaf.key, mean_strong_usd)
                latency += inputs.strong_ms.get(leaf.key, mean_strong_ms)
            source = inputs.screen if leaf.screen_escalated else inputs.baseline
            wrong = leaf.key in source.mismarked_parts
        elif not leaf.screen_escalated or leaf.strong_awarded == leaf.awarded:
            wrong = leaf.key in inputs.screen.mismarked_parts
        else:
            # The screen's final mark is the strong one, which differs from the
            # cheap one: if the strong mark was right the cheap one is wrong,
            # and if it was wrong the cheap one is unknown -- count it wrong.
            wrong = True
            if leaf.key in inputs.screen.mismarked_parts:
                unknown += 1
        if wrong:
            mismarked.add(leaf.key)
        usd[leaf.case_key] += cost
        ms[leaf.case_key] += latency

    screen = inputs.screen
    summary = RunSummary(
        usd_per_script_mean=_mean(list(usd.values())),
        latency_p95_ms=_nearest_rank(list(ms.values()), P95_RANK),
        mismarked_parts=frozenset(mismarked),
        scored_parts=screen.scored_parts,
        id_match_rate=screen.id_match_rate,
        validity_rate=screen.validity_rate,
        incomplete=screen.incomplete,
    )
    return Simulation(combo=combo, summary=summary, unknown=unknown)


def combos() -> list[Combo]:
    return [
        Combo(threshold, disagreement, unaddressed)
        for threshold, disagreement, unaddressed in itertools.product(
            THRESHOLDS, (False, True), (False, True)
        )
    ]


def sweep(inputs: Inputs) -> Choice | None:
    """The cheapest combination ``judge()`` passes with a positive saving, else None.

    Ties go to fewer mismarks, then the lower threshold.
    """
    passing: list[Choice] = []
    for combo in combos():
        sim = simulate(inputs, combo)
        verdict = judge(
            inputs.baseline,
            sim.summary,
            aa_floor=inputs.aa_floor,
            original_latency_p95_ms=inputs.original_latency_p95_ms,
        )
        if verdict.passed and verdict.saving > 0:
            passing.append(Choice(combo, sim.summary, verdict, sim.unknown))
    if not passing:
        return None
    return min(
        passing,
        key=lambda c: (
            c.summary.usd_per_script_mean,
            len(c.summary.mismarked_parts),
            c.combo.threshold,
        ),
    )


def cheap_model(inputs: Inputs) -> str:
    models = Counter(leaf.model for leaf in inputs.leaves)
    if len(models) != 1:
        raise ValueError(f"leaf log mixes first-pass models: {sorted(models)}")
    return next(iter(models))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--screen", type=Path, required=True, help="logged cascade screen run")
    parser.add_argument("--baseline", type=Path, required=True, help="baseline run")
    parser.add_argument("--leaf-log", type=Path, help=f"default: <screen>/{LEAF_LOG}")
    parser.add_argument("--aa-floor", type=int, help=f"default: <baseline>/../{AA_FLOOR_FILE}")
    parser.add_argument("--original-p95-ms", type=float, help="default: the baseline's latency p95")
    args = parser.parse_args(argv)
    try:
        inputs = load_inputs(
            screen_dir=args.screen,
            baseline_dir=args.baseline,
            leaf_log=args.leaf_log,
            aa_floor=args.aa_floor,
            original_latency_p95_ms=args.original_p95_ms,
        )
        model = cheap_model(inputs)
    except (OSError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    best = sweep(inputs)
    print(f"{len(combos())} combinations over {len(inputs.leaves)} logged leaves")
    if best is None:
        print("no combination passes judge() with a saving")
        return 1
    combo, verdict = best.combo, best.verdict
    print(
        f"cheapest passing: threshold={combo.threshold:.2f} "
        f"disagreement={combo.disagreement} unaddressed={combo.unaddressed} "
        f"usd/script={best.summary.usd_per_script_mean:.4f} saving={verdict.saving:.1%} "
        f"tier={verdict.tier} extra_mismarks={verdict.extra_mismarks}/{verdict.allowed_extra} "
        f"unknown={best.unknown}"
    )
    print(
        "settings: "
        f"gemini.cascade_threshold_for={json.dumps({model: combo.threshold})} "
        f"gemini.cascade_two_pass_disagreement={json.dumps(combo.disagreement)} "
        f"gemini.cascade_unaddressed_points={json.dumps(combo.unaddressed)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
