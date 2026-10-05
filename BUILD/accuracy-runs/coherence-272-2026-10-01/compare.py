r"""#272 review-rate comparison: legacy-path coherence before vs after 9130d714.

Coherence is deterministic Python downstream of the marker's reply, so the
"before" run (parent of the #272 commit) fills a scratch cache cold and the
"after" run (the #272 commit) must replay it. This script is code-only: it
loads the two saved results, validates ``eval_records`` and compares them.

Two modes, both run with ``PYTHONPATH`` pinned to the AFTER tree:

``compare.py --before B.json --after A.json --baseline BASE.json \
    --golden DIR --meta META.json --out report.json``
    Review-rate and coherence-trigger-rate for each run, per-leaf flag flips
    (disappeared / appeared, both flags, never netted), the flip split by
    scheme shape, mark-metric and per-record identity checks, per-path tables
    with the abstention column, the paired exact McNemar test and Wilson
    intervals, and the committed baseline printed next to the before run.

``compare.py --count-out-of-range --config TOML --golden DIR``
    An in-process replay (``measure_accuracy`` against the scratch cache) that
    counts ``QuestionResult``s whose ``review_reason`` starts with
    ``marker returned`` (reason-2, out-of-range). ``save_result`` does not
    write ``review_reason``, so this cannot be read from a saved file. The
    cache file count before and after must match (a replay adds none).

Mark identity is the strongest check and the stop rule: if any
``(paper_id, fixture_variant, question_id, mark_point_id)`` present in both
runs differs in ``predicted_marks`` or ``outcome``, a mark moved.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from lemely.eval.records import EvalRecord

OUTCOMES = ("correct", "over", "under", "abstain", "unmatched", "excluded")
PATHS = ("det", "gemini")
Leaf = tuple[str, str]


def _wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if n == 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def _mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p over the discordant pairs (b, c)."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / (2**n)
    return min(1.0, 2 * tail)


def _load(path: Path) -> tuple[dict[str, Any], list[EvalRecord]]:
    from lemely.eval.records import EvalRecord

    data = json.loads(path.read_text(encoding="utf-8"))
    return data, [EvalRecord.model_validate(r) for r in data["eval_records"]]


def _leaf_groups(records: list[EvalRecord]) -> dict[Leaf, list[EvalRecord]]:
    from lemely.eval.analyses import _group_by_leaf, _question_level, _scored

    return _group_by_leaf(_scored(_question_level(records)))


def _flags(records: list[EvalRecord]) -> tuple[dict[Leaf, bool], dict[Leaf, bool]]:
    """Per-leaf (generic, coherence) flags, by the gate's own union rule."""
    generic: dict[Leaf, bool] = {}
    coherence: dict[Leaf, bool] = {}
    for leaf, group in _leaf_groups(records).items():
        generic[leaf] = any(r.triggers for r in group)
        coherence[leaf] = any("coherence_mismatch" in r.triggers for r in group)
    return generic, coherence


def _leaf_path(group: list[EvalRecord]) -> str:
    paths = sorted({r.parse_path for r in group})
    return paths[0] if len(paths) == 1 else "mixed:" + "+".join(paths)


def _flip(before: dict[Leaf, bool], after: dict[Leaf, bool]) -> dict[str, Any]:
    both = sorted(set(before) & set(after))
    disappeared = [leaf for leaf in both if before[leaf] and not after[leaf]]
    appeared = [leaf for leaf in both if not before[leaf] and after[leaf]]
    kept = sum(1 for leaf in both if before[leaf] and after[leaf])
    neither = sum(1 for leaf in both if not before[leaf] and not after[leaf])
    return {
        "leaves_in_both": len(both),
        "leaves_only_before": sorted(set(before) - set(after)),
        "leaves_only_after": sorted(set(after) - set(before)),
        "flagged_both": kept,
        "flagged_neither": neither,
        "disappeared": [list(x) for x in disappeared],
        "appeared": [list(x) for x in appeared],
        "n_disappeared": len(disappeared),
        "n_appeared": len(appeared),
        "net_change_in_flagged_leaves": len(appeared) - len(disappeared),
        "mcnemar_exact_p_two_sided": _mcnemar_exact(len(disappeared), len(appeared)),
    }


def _rates(records: list[EvalRecord]) -> dict[str, Any]:
    from lemely.eval.analyses import coherence_trigger_rate, review_rate

    rr = review_rate(records)
    ct = coherence_trigger_rate(records)
    n = rr["n"]
    out: dict[str, Any] = dict(rr)
    out["coherence_trigger_rate"] = ct["coherence_trigger_rate"]
    generic, coherence = _flags(records)
    out["n_flagged_leaves"] = sum(generic.values())
    out["n_coherence_flagged_leaves"] = sum(coherence.values())
    out["wilson95_review_rate_total"] = _wilson(out["n_flagged_leaves"], n)
    out["wilson95_coherence_trigger_rate"] = _wilson(out["n_coherence_flagged_leaves"], n)
    return out


def _funnel(records: list[EvalRecord]) -> dict[str, Any]:
    from lemely.eval.analyses import _distinct_leaves_scored_aware, _question_level

    qlevel = _question_level(records)
    leaves = _distinct_leaves_scored_aware(qlevel)
    scored = [r for r in leaves if r.outcome != "excluded"]
    by_path: dict[str, dict[str, int]] = {}
    for path in PATHS:
        rows = [r for r in leaves if r.parse_path == path]
        by_path[path] = {"leaves": len(rows)}
        for o in OUTCOMES:
            by_path[path][o] = sum(1 for r in rows if r.outcome == o)
        by_path[path]["scored_leaves"] = sum(1 for r in rows if r.outcome != "excluded")
        # Abstention is its own column and is NOT in "correct"; the rate below
        # keeps it in the denominator (scored = everything but excluded).
        sc = by_path[path]["scored_leaves"]
        by_path[path]["correct_rate"] = by_path[path]["correct"] / sc if sc else None  # type: ignore[assignment]
        by_path[path]["wilson95_correct_rate"] = _wilson(by_path[path]["correct"], sc)  # type: ignore[assignment]
    return {
        "records_total": len(records),
        "question_level_records": len(qlevel),
        "point_level_records_dropped": len(records) - len(qlevel),
        "distinct_leaves": len(leaves),
        "excluded_leaves_dropped_from_denominator": len(leaves) - len(scored),
        "scored_leaves_denominator": len(scored),
        "by_parse_path": by_path,
        "abstain_leaves": sum(1 for r in leaves if r.outcome == "abstain"),
    }


def _per_path_flips(
    before: dict[Leaf, bool],
    after: dict[Leaf, bool],
    paths: dict[Leaf, str],
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for path in (*PATHS, "other"):
        leaves = [
            leaf
            for leaf in sorted(set(before) & set(after))
            if (paths.get(leaf, "other") == path or (path == "other" and paths.get(leaf) not in PATHS))
        ]
        dis = sum(1 for leaf in leaves if before[leaf] and not after[leaf])
        app = sum(1 for leaf in leaves if not before[leaf] and after[leaf])
        out[path] = {
            "leaves": len(leaves),
            "flagged_before": sum(before[leaf] for leaf in leaves),
            "flagged_after": sum(after[leaf] for leaf in leaves),
            "disappeared": dis,
            "appeared": app,
        }
    return out


def _mark_identity(
    before: list[EvalRecord], after: list[EvalRecord]
) -> dict[str, Any]:
    def key(r: EvalRecord) -> tuple[str, str | None, str, str | None]:
        return (r.paper_id, r.fixture_variant, r.question_id, r.mark_point_id)

    b = {key(r): r for r in before}
    a = {key(r): r for r in after}
    common = sorted(set(b) & set(a), key=lambda k: tuple(str(x) for x in k))
    diffs = [
        {
            "key": list(k),
            "before": {"predicted_marks": b[k].predicted_marks, "outcome": b[k].outcome},
            "after": {"predicted_marks": a[k].predicted_marks, "outcome": a[k].outcome},
        }
        for k in common
        if (b[k].predicted_marks, b[k].outcome) != (a[k].predicted_marks, a[k].outcome)
    ]
    return {
        "records_before": len(b),
        "records_after": len(a),
        "keys_in_both": len(common),
        "keys_only_before": sorted(map(list, set(b) - set(a)), key=str),  # type: ignore[arg-type]
        "keys_only_after": sorted(map(list, set(a) - set(b)), key=str),  # type: ignore[arg-type]
        "predicted_marks_and_outcome_identical_on_every_shared_key": not diffs,
        "differences": diffs,
    }


# ---------------------------------------------------------------------------
# Flip split by scheme shape
# ---------------------------------------------------------------------------

SHAPES = (
    "stated_pool_over_award",
    "unequal_tariff_either_or_summed",
    "unstated_pool_leftover_cap_binds",
    "pool_capped_at_0",
    "later_stated_pool_no_room",
    # Not one of the five named shapes: the T1 docstring's "either/or pair
    # matched both ways", with equal tariffs (the global rule over-counted it).
    "equal_tariff_either_or_matched_both_ways",
)


def _shapes_of(question: Any) -> tuple[list[str], str]:
    """Candidate scheme shapes for one question, from its groups alone.

    A SCHEME property: it says which non-additive structures the leaf has, not
    which one the marker's reply actually exercised (``matched_point_ids`` is
    not in the saved records). Reported as a candidate, never as a mechanism.
    """
    from lemely.io.correction_ai import _scheme_groups

    points, groups = _scheme_groups(question)
    by_key: dict[str, list[int]] = {}
    caps: dict[str, int] = {}
    for p, (key, cap) in zip(points, groups, strict=True):
        if key is None:
            continue
        by_key.setdefault(key, []).append(p.marks)
        caps[key] = cap or 0
    found: list[str] = []
    stated = question.select_count is not None
    seen_stated_pool = False
    for key, tariffs in by_key.items():
        cap = caps[key]
        if key.startswith("alt:"):
            if len(set(tariffs)) > 1:
                found.append("unequal_tariff_either_or_summed")
            else:
                found.append("equal_tariff_either_or_matched_both_ways")
            continue
        if stated:
            if cap == 0:
                found.append("later_stated_pool_no_room" if seen_stated_pool else "pool_capped_at_0")
            elif sum(tariffs) > cap:
                found.append("stated_pool_over_award")
            seen_stated_pool = True
        elif cap == 0:
            found.append("pool_capped_at_0")
        elif cap < sum(tariffs):
            found.append("unstated_pool_leftover_cap_binds")
    if found:
        return sorted(set(found)), ""
    independent = sum(p.marks for p, (key, _c) in zip(points, groups, strict=True) if key is None)
    if not by_key and independent > question.marks:
        return [], "no non-additive group; independent tariffs exceed the question (det-shaped)"
    if not by_key:
        return [], "no non-additive group in the scheme"
    return [], "non-additive groups present but none matches the five shapes (cap not binding)"


def _classify_flips(
    flips: dict[str, list[list[str]]], golden: Path
) -> dict[str, Any]:
    from lemely.accuracy.harness import load_golden_cases

    cases = {c.paper_id: c for c in load_golden_cases(golden)}
    out: dict[str, Any] = {}
    for direction, leaves in flips.items():
        rows: list[dict[str, Any]] = []
        counts = dict.fromkeys(SHAPES, 0)
        counts["unclassified"] = 0
        counts["multiple_shapes"] = 0
        for paper_id, question_id in leaves:
            case = cases.get(paper_id)
            question = case.mark_scheme.get_question_by_id(question_id) if case else None
            if question is None:
                shapes: list[str] = []
                reason = "question not found in the golden mark scheme"
            else:
                shapes, reason = _shapes_of(question)
            if not shapes:
                counts["unclassified"] += 1
            elif len(shapes) > 1:
                counts["multiple_shapes"] += 1
            else:
                counts[shapes[0]] += 1
            rows.append(
                {
                    "leaf": [paper_id, question_id],
                    "shapes": shapes or ["unclassified"],
                    "reason": reason,
                    "select_count": getattr(question, "select_count", None),
                    "marks": getattr(question, "marks", None),
                }
            )
        out[direction] = {"counts": counts, "leaves": rows}
    return out


def _shape_inventory(leaves: list[Leaf], golden: Path) -> dict[str, Any]:
    """How many scored leaves could exercise each shape at all (exposure)."""
    from lemely.accuracy.harness import load_golden_cases

    cases = {c.paper_id: c for c in load_golden_cases(golden)}
    counts = dict.fromkeys(SHAPES, 0)
    counts["no_candidate_shape"] = 0
    counts["question_not_found"] = 0
    no_shape_reasons: dict[str, int] = {}
    for paper_id, question_id in leaves:
        case = cases.get(paper_id)
        question = case.mark_scheme.get_question_by_id(question_id) if case else None
        if question is None:
            counts["question_not_found"] += 1
            continue
        shapes, reason = _shapes_of(question)
        if not shapes:
            counts["no_candidate_shape"] += 1
            no_shape_reasons[reason] = no_shape_reasons.get(reason, 0) + 1
        for shape in shapes:
            counts[shape] += 1
    return {
        "scored_leaves": len(leaves),
        "leaves_with_shape": counts,
        "no_shape_reasons": no_shape_reasons,
    }


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------


def _compare(args: argparse.Namespace) -> None:
    before_data, before = _load(Path(args.before))
    after_data, after = _load(Path(args.after))
    bm, am = before_data["manifest"], after_data["manifest"]

    g_b, c_b = _flags(before)
    g_a, c_a = _flags(after)
    paths = {leaf: _leaf_path(grp) for leaf, grp in _leaf_groups(before).items()}
    for leaf, grp in _leaf_groups(after).items():
        paths.setdefault(leaf, _leaf_path(grp))

    generic = _flip(g_b, g_a)
    coherence = _flip(c_b, c_a)
    metrics = {
        "before": before_data["metrics"],
        "after": after_data["metrics"],
        "mark_accuracy_equal": before_data["metrics"]["mark_accuracy"]
        == after_data["metrics"]["mark_accuracy"],
        "mark_accuracy_theory_equal": before_data["metrics"]["mark_accuracy_theory"]
        == after_data["metrics"]["mark_accuracy_theory"],
    }
    funnel_b, funnel_a = _funnel(before), _funnel(after)
    path_correct_equal = all(
        funnel_b["by_parse_path"][p]["correct"] == funnel_a["by_parse_path"][p]["correct"]
        and funnel_b["by_parse_path"][p]["scored_leaves"]
        == funnel_a["by_parse_path"][p]["scored_leaves"]
        for p in PATHS
    )
    identity = _mark_identity(before, after)

    baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    rates_b = _rates(before)
    base_rr = baseline["review_rate"]
    baseline_cmp = {
        "committed_baseline": {k: baseline[k] for k in ("git_sha", "computed_at", "corpus_digest", "run_id")}
        | {"review_rate": base_rr},
        "before_run": {"n": rates_b["n"], "corpus_digest": bm["corpus_digest"]},
        "n_matches": base_rr["n"] == rates_b["n"],
        "corpus_digest_matches": baseline["corpus_digest"] == bm["corpus_digest"],
        "reading": (
            "match: any before-vs-baseline gap is not corpus drift"
            if base_rr["n"] == rates_b["n"] and baseline["corpus_digest"] == bm["corpus_digest"]
            else "MISMATCH: before-vs-baseline difference is corpus/code drift since the "
            "baseline's git_sha, not #272"
        ),
    }

    report: dict[str, Any] = {
        "manifest": {
            "before": {k: bm.get(k) for k in ("run_id", "git_sha", "params_fingerprint", "cache_mode", "split", "corpus_digest", "n_cases")},
            "after": {k: am.get(k) for k in ("run_id", "git_sha", "params_fingerprint", "cache_mode", "split", "corpus_digest", "n_cases")},
            "corpus_digest_equal": bm["corpus_digest"] == am["corpus_digest"],
            "params_fingerprint_equal": bm["params_fingerprint"] == am["params_fingerprint"],
        },
        "review_rate": {"before": rates_b, "after": _rates(after)},
        "funnel": {"before": funnel_b, "after": funnel_a},
        "flips": {
            "generic": generic,
            "coherence": coherence,
            "by_parse_path_generic": _per_path_flips(g_b, g_a, paths),
            "by_parse_path_coherence": _per_path_flips(c_b, c_a, paths),
            "by_scheme_shape_coherence": _classify_flips(
                {"disappeared": coherence["disappeared"], "appeared": coherence["appeared"]},
                Path(args.golden),
            ),
            "by_scheme_shape_generic": _classify_flips(
                {"disappeared": generic["disappeared"], "appeared": generic["appeared"]},
                Path(args.golden),
            ),
        },
        "scheme_shape_exposure_after_run": _shape_inventory(sorted(g_a), Path(args.golden)),
        "mark_metrics": metrics,
        "per_parse_path_correct_equal": path_correct_equal,
        "record_identity": identity,
        "baseline_comparison": baseline_cmp,
    }
    if args.meta:
        report["meta"] = json.loads(Path(args.meta).read_text(encoding="utf-8"))
    Path(args.out).write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")

    print(json.dumps({
        "review_rate_before": report["review_rate"]["before"],
        "review_rate_after": report["review_rate"]["after"],
        "generic": {k: generic[k] for k in ("n_disappeared", "n_appeared", "disappeared", "appeared")},
        "coherence": {k: coherence[k] for k in ("n_disappeared", "n_appeared", "disappeared", "appeared")},
        "marks_identical": identity["predicted_marks_and_outcome_identical_on_every_shared_key"],
        "mark_metrics_equal": metrics["mark_accuracy_equal"] and metrics["mark_accuracy_theory_equal"],
        "per_path_correct_equal": path_correct_equal,
        "baseline_reading": baseline_cmp["reading"],
    }, indent=2, default=str))
    if not identity["predicted_marks_and_outcome_identical_on_every_shared_key"]:
        print("STOP: a mark or outcome moved; do not refresh the baseline.", file=sys.stderr)
        sys.exit(3)


def _count_files(path: Path) -> int:
    return sum(1 for p in path.rglob("*") if p.is_file())


def _count_out_of_range(args: argparse.Namespace) -> None:
    from lemely.accuracy.harness import load_golden_cases, measure_accuracy
    from lemely.io.gemini import GeminiClient
    from lemely.runtime.config import load_settings

    settings = load_settings(toml_path=Path(args.config))
    cache_dir = Path(settings.paths.cache_dir)
    n_before = _count_files(cache_dir)
    client = GeminiClient(settings, default_cache_mode="read_write")
    cases = load_golden_cases(Path(args.golden))
    result = measure_accuracy(cases, client, settings)
    n_after = _count_files(cache_dir)
    hits = [
        {"question_id": r.question_id, "review_reason": r.review_reason}
        for r in result.question_results
        if (r.review_reason or "").startswith("marker returned")
    ]
    print(json.dumps({
        "mode": "count_out_of_range",
        "run_id": result.manifest.run_id,
        "cache_files_before": n_before,
        "cache_files_after": n_after,
        "cache_files_added": n_after - n_before,
        "question_results": len(result.question_results),
        "out_of_range_count": len(hits),
        "out_of_range": hits,
        "cost_usd_total": result.cost_usd_total,
    }, indent=2, default=str))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--count-out-of-range", action="store_true")
    ap.add_argument("--before")
    ap.add_argument("--after")
    ap.add_argument("--baseline")
    ap.add_argument("--golden", required=True)
    ap.add_argument("--meta")
    ap.add_argument("--out")
    ap.add_argument("--config")
    args = ap.parse_args()
    if args.count_out_of_range:
        if not args.config:
            ap.error("--count-out-of-range needs --config")
        _count_out_of_range(args)
        return
    for name in ("before", "after", "baseline", "out"):
        if not getattr(args, name):
            ap.error(f"--{name} is required")
    _compare(args)


if __name__ == "__main__":
    main()
