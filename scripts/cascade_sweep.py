#!/usr/bin/env python3
"""Fit the correction cascade's triggers offline, from a logged screen and the baseline.

No API calls. For every confidence threshold from 0.50 to 0.99 (step 0.01),
combined with each on/off setting of the disagreement and unaddressed-point
triggers, it simulates the marks and the 2027 cost per script a cascade would
produce, judges the result against the baseline with ``judge()``, and prints the
cheapest combination that passes with a saving. With ``--loo`` the combination
must also pass on every leave-one-case-out subset.

Inputs:

- ``--screen DIR``: a cost-ladder run made with ``gemini.cascade_enabled=true``
  and ``LEMELY_CASCADE_LEAF_LOG=DIR/cascade_leaves.jsonl`` in the environment.
  Its ``results.json`` gives every question's case key, final predicted marks,
  truth marks, type and whether it was scored; the leaf log (one JSON line per
  marked leaf, written by ``lemely.io.correction_ai``) gives each leaf's
  first-pass confidence and marks, the second pass's marks, the unaddressed
  points, the strong re-mark's marks, and each call's cost.
- ``--baseline DIR``: the baseline run. Its ``summary.json`` is what the
  candidate is judged against on the whole run; its ``results.json`` gives the
  baseline's marks (a proxied strong re-mark takes them) and, with its
  ``records.jsonl``, the per-case figures for leave-one-out; its
  ``records.jsonl`` also gives every case's non-correction cost (which the
  cascade does not change) and each leaf's correction cost (the proxy base).

Every simulated mark is judged against ``truth_marks``. The screen's final
(post-processed) mark is known only for the response the screen returned (the
strong re-mark if the screen escalated the leaf, else the first pass). A
combination that keeps the other response is judged on that response's raw AI
mark, even when it equals the returned raw mark, since post-processing depends
on more than the raw marks; the sweep counts those as ``approximated`` and, for
the chosen combination, reports how many were judged correct and flags it
``FRAGILE`` when its extra mismarks plus that count would exceed the allowance.
Scored parts per case come from the ``scored`` flag in ``results.json``.

The leaf log must come from one uninterrupted screen: every line carries the
process's run token, so a resumed or interrupted screen (a new process, a new
token) is refused. Delete the leaf log and re-run the whole label. A leaf marked
twice in one run (an ECF re-mark) is refused too.

The logging screen this is built for runs the cheap model with a fitted
threshold of 1.0 and both triggers on, so every leaf logs a first pass, a second
pass and a real strong re-mark. Logged strong cost, latency and marks are always
used. A leaf without a logged strong call is proxied from the baseline's
correction cost and latency for that leaf, scaled up by the mean ratio of logged
strong to baseline over the leaves that have one (never scaled below 1). With no
logged strong call anywhere the sweep refuses rather than guess. A leaf logged
with ``strong_skipped_identical`` (the strong call would repeat the first pass,
so the cascade never makes it) takes its first pass as the strong result, at no
extra cost.

Where the logs cannot say what would have happened, the simulation assumes the
worse outcome and counts it as ``unknown``: a combination needs the second
pass's marks but the screen never ran it (the trigger is taken to fire, and the
second pass and the strong call are paid for), or a proxied leaf has no baseline
result (counted as mismarked).

The sweep refuses a leaf log that mixes run tokens or cascade configs, a line
without a first-pass cost, a strong or second pass that ran without a cost, an
unpriced (NaN) cost in the log or the baseline records, a ``results.json``
without case keys, and a scored non-MCQ question in the screen's results with no
leaf line. MCQ parts are excluded by ``question_type == "mcq"``: they are marked
deterministically and never reach the AI marker, while every scored non-MCQ part
was marked by it.

Run with the repository on the path:
``PYTHONPATH=. python scripts/cascade_sweep.py --screen DIR --baseline DIR [--loo]``.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import sys
from dataclasses import dataclass, field
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
    strong_awarded: int | None  # set exactly when a strong call was logged
    strong_skipped: bool  # the strong call would repeat the first pass
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
class Result:
    """One question result from a run's ``results.json``."""

    case_key: str
    question_type: str
    predicted: int
    truth: int
    scored: bool


@dataclass(frozen=True)
class Inputs:
    leaves: tuple[Leaf, ...]
    run_token: str
    screen: RunSummary
    baseline: RunSummary
    aa_floor: int
    original_latency_p95_ms: float
    leaf_usd: dict[str, float]  # leaf key -> baseline correction USD
    leaf_ms: dict[str, float]
    upstream_usd: dict[str, float]  # case key -> baseline non-correction USD
    upstream_ms: dict[str, float]
    case_usd: dict[str, float]  # case key -> baseline total USD
    case_ms: dict[str, float]
    strong_usd_factor: float  # >= 1: scales a proxied strong call's cost
    strong_ms_factor: float
    cases: tuple[str, ...]
    screen_results: dict[str, Result]  # "<case_key>/<question_id>" -> result
    baseline_results: dict[str, Result]
    screen_scored_by_case: dict[str, int]
    baseline_scored_by_case: dict[str, int]


@dataclass(frozen=True)
class Simulation:
    combo: Combo
    summary: RunSummary
    unknown: int
    proxied: int
    approximated: int  # marks judged raw: not the response the screen returned
    approximated_correct: int  # of those, judged equal to the truth


@dataclass(frozen=True)
class Choice:
    combo: Combo
    summary: RunSummary
    verdict: Verdict
    unknown: int
    proxied: int
    approximated: int
    approximated_correct: int
    loo: tuple[tuple[str, Verdict], ...] = field(default=())


def _number(value: object, what: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{what}: expected a number, got {value!r}")
    number = float(value)
    if math.isnan(number):
        raise ValueError(f"{what}: unpriced (NaN) cost; the run is incomplete")
    return number


def _integer(value: object, what: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{what}: expected an integer, got {value!r}")
    return value


def _leaf(raw: dict[str, object]) -> Leaf:
    case_key = raw.get("case_key")
    question_id = raw.get("question_id")
    if not isinstance(case_key, str) or not isinstance(question_id, str):
        raise ValueError(f"leaf log line without case_key/question_id: {raw!r}")
    key = f"{case_key}/{question_id}"
    usd = raw.get("usd_2027")
    ms = raw.get("latency_ms")
    if not isinstance(usd, dict) or not isinstance(ms, dict):
        raise ValueError(f"{key}: leaf log line without usd_2027/latency_ms")
    confidence = _number(raw.get("confidence"), f"{key} confidence")
    awarded = _integer(raw.get("awarded_marks"), f"{key} awarded_marks")
    usd_first = _number(usd.get("first"), f"{key} first-pass cost")
    ms_first = _number(ms.get("first"), f"{key} first-pass latency")
    if confidence is None or awarded is None:
        raise ValueError(f"{key}: leaf log line without confidence/awarded_marks")
    if usd_first is None or ms_first is None:
        raise ValueError(f"{key}: no first-pass cost logged (no call record); refusing $0")
    pass2 = _integer(raw.get("pass2_awarded_marks"), f"{key} pass2_awarded_marks")
    usd_pass2 = _number(usd.get("pass2"), f"{key} pass2 cost")
    if pass2 is not None and usd_pass2 is None:
        raise ValueError(f"{key}: second pass ran without a logged cost; refusing $0")
    escalated = bool(raw.get("escalated"))
    usd_strong = _number(usd.get("strong"), f"{key} strong cost")
    if escalated and usd_strong is None:
        raise ValueError(f"{key}: strong call ran without a logged cost; refusing $0")
    unaddressed_ids = raw.get("unaddressed_point_ids")
    return Leaf(
        key=key,
        case_key=case_key,
        model=str(raw.get("model")),
        confidence=confidence,
        awarded=awarded,
        pass2_awarded=pass2,
        unaddressed=None if unaddressed_ids is None else bool(unaddressed_ids),
        strong_awarded=(
            _integer(raw.get("strong_awarded_marks"), f"{key} strong_awarded_marks")
            if escalated
            else None
        ),
        usd_first=usd_first,
        usd_pass2=usd_pass2,
        strong_skipped=bool(raw.get("strong_skipped_identical")),
        usd_strong=usd_strong if escalated else None,
        ms_first=ms_first,
        ms_pass2=_number(ms.get("pass2"), f"{key} pass2 latency"),
        ms_strong=_number(ms.get("strong"), f"{key} strong latency") if escalated else None,
    )


def read_leaves(path: Path) -> tuple[tuple[Leaf, ...], str]:
    """The leaf log, one leaf per key, and its run token.

    Refuses a log with more than one run token or cascade config, and a leaf
    logged twice in one run.
    """
    by_key: dict[str, Leaf] = {}
    tokens: set[str] = set()
    configs: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        tokens.add(str(raw.get("run_token")))
        configs.add(json.dumps(raw.get("config"), sort_keys=True))
        leaf = _leaf(raw)
        if leaf.key in by_key:
            raise ValueError(
                f"{path}: {leaf.key} is logged more than once; "
                "leaf marked twice in one run (ECF re-mark?); not supported"
            )
        by_key[leaf.key] = leaf
    if not by_key:
        raise ValueError(f"{path} has no cascade leaves")
    if len(tokens) > 1:
        raise ValueError(f"{path} holds more than one run (run tokens {sorted(tokens)})")
    if len(configs) > 1:
        raise ValueError(f"{path} holds more than one cascade config: {sorted(configs)}")
    return tuple(by_key.values()), tokens.pop()


def _jsonl(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def read_results(path: Path) -> dict[str, Result]:
    """A run's question results by ``<case_key>/<question_id>``; refuses missing case keys."""
    data = json.loads(path.read_text(encoding="utf-8"))
    results: dict[str, Result] = {}
    for row in data["question_results"]:
        case, qid = row.get("case_key"), row.get("question_id")
        if not isinstance(case, str) or not isinstance(qid, str):
            raise ValueError(
                f"{path}: question result without case_key/question_id; "
                "re-run with a runner that writes case-keyed results"
            )
        predicted = _integer(row.get("predicted_marks"), f"{case}/{qid} predicted_marks")
        truth = _integer(row.get("truth_marks"), f"{case}/{qid} truth_marks")
        if predicted is None or truth is None:
            raise ValueError(f"{path}: {case}/{qid} without predicted/truth marks")
        results[f"{case}/{qid}"] = Result(
            case_key=case,
            question_type=str(row.get("question_type")),
            predicted=predicted,
            truth=truth,
            scored=bool(row.get("scored", True)),
        )
    return results


def _scored_by_case(results: dict[str, Result]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for result in results.values():
        if result.scored:
            counts[result.case_key] = counts.get(result.case_key, 0) + 1
    return counts


def _mismarked(results: dict[str, Result], kept: frozenset[str] | None = None) -> set[str]:
    return {
        key
        for key, r in results.items()
        if r.scored and r.predicted != r.truth and (kept is None or r.case_key in kept)
    }


def _ratio_factor(observed: list[float]) -> float:
    return max(1.0, sum(observed) / len(observed)) if observed else 1.0


def load_inputs(
    *,
    screen_dir: Path,
    baseline_dir: Path,
    leaf_log: Path | None = None,
    aa_floor: int | None = None,
    original_latency_p95_ms: float | None = None,
) -> Inputs:
    """Read and check everything the simulation needs; defaults follow the cost-ladder layout."""
    screen = read_summary(screen_dir / "summary.json")
    baseline = read_summary(baseline_dir / "summary.json")
    if aa_floor is None:
        floor_path = baseline_dir.parent / AA_FLOOR_FILE
        aa_floor = int(json.loads(floor_path.read_text(encoding="utf-8"))["aa_floor"])
    leaves, run_token = read_leaves(leaf_log or screen_dir / LEAF_LOG)
    screen_results = read_results(screen_dir / "results.json")
    baseline_results = read_results(baseline_dir / "results.json")
    logged = {leaf.key for leaf in leaves}
    missing = sorted(
        key
        for key, r in screen_results.items()
        if r.scored and r.question_type != "mcq" and key not in logged
    )
    if missing:
        raise ValueError(f"scored non-MCQ parts with no leaf-log line: {', '.join(missing)}")

    leaf_usd: dict[str, float] = {}
    leaf_ms: dict[str, float] = {}
    upstream_usd: dict[str, float] = {}
    upstream_ms: dict[str, float] = {}
    case_usd: dict[str, float] = {}
    case_ms: dict[str, float] = {}
    cases: dict[str, None] = {}
    for rec in _jsonl(baseline_dir / "records.jsonl"):
        case = rec.get("case_key")
        if not isinstance(case, str):
            continue
        cases[case] = None
        usd = _number(rec.get("usd_2027"), f"baseline record for {case}") or 0.0
        ms = _number(rec.get("latency_ms"), f"baseline record for {case}") or 0.0
        case_usd[case] = case_usd.get(case, 0.0) + usd
        case_ms[case] = case_ms.get(case, 0.0) + ms
        qid = rec.get("question_id")
        if rec.get("task_tag") in CORRECTION_TAGS and isinstance(qid, str):
            key = f"{case}/{qid}"
            leaf_usd[key] = leaf_usd.get(key, 0.0) + usd
            leaf_ms[key] = leaf_ms.get(key, 0.0) + ms
        else:
            upstream_usd[case] = upstream_usd.get(case, 0.0) + usd
            upstream_ms[case] = upstream_ms.get(case, 0.0) + ms
    for leaf in leaves:
        cases[leaf.case_key] = None
    for result in screen_results.values():
        cases[result.case_key] = None

    with_strong = [leaf for leaf in leaves if leaf.usd_strong is not None]
    needs_proxy = any(leaf.usd_strong is None and not leaf.strong_skipped for leaf in leaves)
    if needs_proxy and not with_strong:
        raise ValueError(
            "no leaf has a logged strong call; refusing to proxy the strong cost "
            "(log the screen with threshold 1.0 so every leaf is re-marked)"
        )
    usd_ratios = [
        (leaf.usd_strong or 0.0) / leaf_usd[leaf.key]
        for leaf in with_strong
        if leaf_usd.get(leaf.key, 0.0) > 0
    ]
    ms_ratios = [
        (leaf.ms_strong or 0.0) / leaf_ms[leaf.key]
        for leaf in with_strong
        if leaf_ms.get(leaf.key, 0.0) > 0
    ]

    return Inputs(
        leaves=leaves,
        run_token=run_token,
        screen=screen,
        baseline=baseline,
        aa_floor=aa_floor,
        original_latency_p95_ms=(
            baseline.latency_p95_ms if original_latency_p95_ms is None else original_latency_p95_ms
        ),
        leaf_usd=leaf_usd,
        leaf_ms=leaf_ms,
        upstream_usd=upstream_usd,
        upstream_ms=upstream_ms,
        case_usd=case_usd,
        case_ms=case_ms,
        strong_usd_factor=_ratio_factor(usd_ratios),
        strong_ms_factor=_ratio_factor(ms_ratios),
        cases=tuple(cases),
        screen_results=screen_results,
        baseline_results=baseline_results,
        screen_scored_by_case=_scored_by_case(screen_results),
        baseline_scored_by_case=_scored_by_case(baseline_results),
    )


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _nearest_rank(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(math.ceil(q * len(ordered)) - 1, 0)]


def _kept_cases(inputs: Inputs, held_out: str | None) -> tuple[str, ...]:
    if held_out is not None and held_out not in inputs.cases:
        raise ValueError(f"unknown case {held_out!r}")
    return tuple(case for case in inputs.cases if case != held_out)


def _scored_in(by_case: dict[str, int], kept: frozenset[str]) -> int:
    return sum(n for case, n in by_case.items() if case in kept)


def _incomplete_in(incomplete: tuple[str, ...], kept: frozenset[str]) -> tuple[str, ...]:
    return tuple(
        entry
        for entry in incomplete
        if any(entry == case or entry.startswith(f"{case} ") for case in kept)
    )


def baseline_summary(inputs: Inputs, held_out: str | None = None) -> RunSummary:
    """The baseline as judged: the run's own summary, or rebuilt on the kept cases."""
    if held_out is None:
        return inputs.baseline
    cases = _kept_cases(inputs, held_out)
    kept = frozenset(cases)
    base = inputs.baseline
    return RunSummary(
        usd_per_script_mean=_mean([inputs.case_usd.get(c, 0.0) for c in cases]),
        latency_p95_ms=_nearest_rank([inputs.case_ms.get(c, 0.0) for c in cases], P95_RANK),
        mismarked_parts=frozenset(_mismarked(inputs.baseline_results, kept)),
        scored_parts=_scored_in(inputs.baseline_scored_by_case, kept),
        id_match_rate=base.id_match_rate,
        validity_rate=base.validity_rate,
        incomplete=_incomplete_in(base.incomplete, kept),
    )


def simulate(inputs: Inputs, combo: Combo, held_out: str | None = None) -> Simulation:
    """The run summary a cascade with *combo* would have produced, optionally without one case."""
    cases = _kept_cases(inputs, held_out)
    kept = frozenset(cases)
    usd = {case: inputs.upstream_usd.get(case, 0.0) for case in cases}
    ms = {case: inputs.upstream_ms.get(case, 0.0) for case in cases}
    leaves = [leaf for leaf in inputs.leaves if leaf.case_key in kept]
    logged = {leaf.key for leaf in inputs.leaves}
    mismarked = {k for k in _mismarked(inputs.screen_results, kept) if k not in logged}
    proxy_usd_base = max(inputs.leaf_usd.values(), default=0.0)
    proxy_ms_base = max(inputs.leaf_ms.values(), default=0.0)
    unknown = proxied = approximated = approximated_correct = 0

    for leaf in leaves:
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

        # The raw marks the cascade would return, and whether they come from the
        # strong re-mark; raw None: take the baseline's mark.
        raw: int | None
        from_strong = False
        if not fire or leaf.strong_skipped:
            raw = leaf.awarded
        elif leaf.strong_awarded is not None:
            raw = leaf.strong_awarded
            from_strong = True
            cost += leaf.usd_strong or 0.0
            latency += leaf.ms_strong or 0.0
        else:
            raw = None
            proxied += 1
            cost += inputs.leaf_usd.get(leaf.key, proxy_usd_base) * inputs.strong_usd_factor
            latency += inputs.leaf_ms.get(leaf.key, proxy_ms_base) * inputs.strong_ms_factor
        usd[leaf.case_key] += cost
        ms[leaf.case_key] += latency

        result = inputs.screen_results.get(leaf.key)
        if result is None or not result.scored:
            continue
        if raw is None:
            base = inputs.baseline_results.get(leaf.key)
            if base is None:
                unknown += 1
                mismarked.add(leaf.key)
                continue
            mark = base.predicted
        else:
            screen_returned_strong = leaf.strong_awarded is not None
            if from_strong == screen_returned_strong:
                mark = result.predicted  # the screen's final, post-processed mark
            else:
                mark = raw
                approximated += 1
                approximated_correct += mark == result.truth
        if mark != result.truth:
            mismarked.add(leaf.key)

    screen = inputs.screen
    summary = RunSummary(
        usd_per_script_mean=_mean(list(usd.values())),
        latency_p95_ms=_nearest_rank(list(ms.values()), P95_RANK),
        mismarked_parts=frozenset(mismarked),
        scored_parts=(
            screen.scored_parts
            if held_out is None
            else _scored_in(inputs.screen_scored_by_case, kept)
        ),
        id_match_rate=screen.id_match_rate,
        validity_rate=screen.validity_rate,
        incomplete=screen.incomplete
        if held_out is None
        else _incomplete_in(screen.incomplete, kept),
    )
    return Simulation(
        combo=combo,
        summary=summary,
        unknown=unknown,
        proxied=proxied,
        approximated=approximated,
        approximated_correct=approximated_correct,
    )


def judge_combo(
    inputs: Inputs, combo: Combo, held_out: str | None = None
) -> tuple[Simulation, Verdict]:
    """Simulate *combo* (optionally without *held_out*) and judge it on the same cases.

    The A/A floor and the original latency stay the whole run's values.
    """
    sim = simulate(inputs, combo, held_out)
    verdict = judge(
        baseline_summary(inputs, held_out),
        sim.summary,
        aa_floor=inputs.aa_floor,
        original_latency_p95_ms=inputs.original_latency_p95_ms,
    )
    return sim, verdict


def combos() -> list[Combo]:
    return [
        Combo(threshold, disagreement, unaddressed)
        for threshold, disagreement, unaddressed in itertools.product(
            THRESHOLDS, (False, True), (False, True)
        )
    ]


def sweep(inputs: Inputs, *, loo: bool = False) -> Choice | None:
    """The cheapest combination ``judge()`` passes with a positive saving, else None.

    With *loo* it must also pass on every subset that leaves one case out.
    Ties go to fewer mismarks, then the lower threshold.
    """
    passing: list[Choice] = []
    for combo in combos():
        sim, verdict = judge_combo(inputs, combo)
        if not (verdict.passed and verdict.saving > 0):
            continue
        held: tuple[tuple[str, Verdict], ...] = ()
        if loo:
            held = tuple((case, judge_combo(inputs, combo, case)[1]) for case in inputs.cases)
            if not all(v.passed for _, v in held):
                continue
        passing.append(
            Choice(
                combo,
                sim.summary,
                verdict,
                sim.unknown,
                sim.proxied,
                sim.approximated,
                sim.approximated_correct,
                held,
            )
        )
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
    models = {leaf.model for leaf in inputs.leaves}
    if len(models) != 1:
        raise ValueError(f"leaf log mixes first-pass models: {sorted(models)}")
    return next(iter(models))


def _verdict_line(verdict: Verdict) -> str:
    return (
        f"saving={verdict.saving:.1%} tier={verdict.tier} "
        f"extra_mismarks={verdict.extra_mismarks}/{verdict.allowed_extra}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--screen", type=Path, required=True, help="logged cascade screen run")
    parser.add_argument("--baseline", type=Path, required=True, help="baseline run")
    parser.add_argument("--leaf-log", type=Path, help=f"default: <screen>/{LEAF_LOG}")
    parser.add_argument("--aa-floor", type=int, help=f"default: <baseline>/../{AA_FLOOR_FILE}")
    parser.add_argument("--original-p95-ms", type=float, help="default: the baseline's latency p95")
    parser.add_argument(
        "--loo", action="store_true", help="also require a pass on every leave-one-case-out subset"
    )
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
        best = sweep(inputs, loo=args.loo)
    except (OSError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(
        f"{len(combos())} combinations over {len(inputs.leaves)} logged leaves "
        f"in {len(inputs.cases)} cases (run {inputs.run_token}); "
        f"proxy factors usd x{inputs.strong_usd_factor:.2f} latency x{inputs.strong_ms_factor:.2f}"
    )
    if best is None:
        scope = "the whole run and every held-out subset" if args.loo else "the whole run"
        print(f"no combination passes judge() with a saving on {scope}")
        return 1
    combo = best.combo
    print(
        f"cheapest passing: threshold={combo.threshold:.2f} "
        f"disagreement={combo.disagreement} unaddressed={combo.unaddressed} "
        f"usd/script={best.summary.usd_per_script_mean:.4f} {_verdict_line(best.verdict)} "
        f"unknown={best.unknown} proxied={best.proxied} approximated={best.approximated}"
    )
    verdict = best.verdict
    fragile = verdict.extra_mismarks + best.approximated_correct > verdict.allowed_extra
    print(
        f"approximated judged correct: {best.approximated_correct} "
        f"(extra_mismarks {verdict.extra_mismarks} + {best.approximated_correct} "
        f"{'>' if fragile else '<='} allowed {verdict.allowed_extra})"
        + (" FRAGILE: the pass rests on raw-judged marks" if fragile else "")
    )
    for case, verdict in best.loo:
        print(f"  held out {case}: {'PASS' if verdict.passed else 'FAIL'} {_verdict_line(verdict)}")
    print(
        "settings: "
        f"gemini.cascade_threshold_for={json.dumps({model: combo.threshold})} "
        f"gemini.cascade_two_pass_disagreement={json.dumps(combo.disagreement)} "
        f"gemini.cascade_unaddressed_points={json.dumps(combo.unaddressed)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
