"""Pure statistical analyses over ``list[EvalRecord]`` (spec §3.3).

No I/O, no Gemini calls, no filesystem access — every function here is a
plain function of its input list. Every analysis filters to question-level
rows (``mark_point_id is None``) before aggregating, unless the analysis is
explicitly point-level, and every interval/power calculation collapses to
**distinct leaves** first (one row per ``(paper_id, question_id)``), per
spec §3.3.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from lemely.eval.records import EvalRecord

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _question_level(records: list[EvalRecord]) -> list[EvalRecord]:
    """Drop sub-question (mark-point-level) rows, per spec §3.3."""
    return [r for r in records if r.mark_point_id is None]


def _opt(value: object) -> tuple[bool, object]:
    """Wrap an optional field so ``None`` sorts deterministically and safely.

    Tuple comparison in Python compares element-by-element and only inspects
    the second slot when the first slots are equal, so two records that are
    both ``None`` compare their (equal, throwaway) second slots, and two
    records with differing None-ness never reach a cross-type comparison
    (e.g. ``None < 0.5``) that would raise ``TypeError``.
    """
    return (value is None, value if value is not None else "")


def _leaf_sort_key(
    r: EvalRecord,
) -> tuple[object, ...]:
    """Deterministic, position-independent, *exhaustive* ordering key.

    Used only to make the DA6 collapse deterministic and order-independent —
    picking *which* record represents a leaf must not depend on the order
    records arrived in, only on their content. Two records tie under this
    key iff they are identical in every field a downstream analysis might
    read (``marker_conf``, ``triggers``, ``extraction_conf``, etc.) — a
    partial key (e.g. one that stops at ``outcome``) can leave genuinely
    distinct records tied, at which point ``min()`` falls back to input-list
    position and silently reintroduces order-dependence.
    """
    return (
        _opt(r.fixture_variant),
        _opt(r.mark_point_id),
        r.run_id,
        r.arm,
        r.outcome,
        r.parse_path,
        _opt(r.predicted_marks),
        _opt(r.truth_marks),
        _opt(r.extraction_conf),
        _opt(r.marker_conf),
        r.id_match,
        tuple(r.triggers),
        r.paper_id,
        r.question_id,
    )


def _collapse_leaf_group(group: list[EvalRecord]) -> EvalRecord:
    """Collapse one leaf's variant/duplicate records into a single representative.

    Per BUILD/DECISIONS.md DA6: a leaf's outcome is derived from ALL of its
    records, never sampled from them. A leaf counts as ``correct`` iff EVERY
    record for it is ``correct``; otherwise it is represented by one of its
    non-``correct`` records. This is deliberately NOT "sort and keep the
    first" — fixture variants sort ``correct`` < ``partial`` < ``wrong``, so
    that naive rule would represent every partially-disagreeing leaf by its
    ``correct`` variant and inflate accuracy by construction. Choosing the
    representative via a content-derived sort key (rather than input-list
    position) makes the result order-independent.
    """
    if all(r.outcome == "correct" for r in group):
        candidates = group
    else:
        candidates = [r for r in group if r.outcome != "correct"]
    return min(candidates, key=_leaf_sort_key)


def _distinct_leaves(records: list[EvalRecord]) -> list[EvalRecord]:
    """Collapse to one row per ``(paper_id, question_id)`` leaf (DA6).

    Interval/power calculations must not be inflated by duplicate rows for
    the same leaf (e.g. accidental point-level rows slipping through, or
    genuine DA6 fixture-variant duplicates). See :func:`_collapse_leaf_group`
    for how a leaf's collapsed outcome is derived.
    """
    groups: dict[tuple[str, str], list[EvalRecord]] = {}
    for r in records:
        groups.setdefault((r.paper_id, r.question_id), []).append(r)
    return [_collapse_leaf_group(group) for group in groups.values()]


def _collapse_leaf_group_scored_aware(group: list[EvalRecord]) -> EvalRecord:
    """DA6a: collapse a leaf's records with ``excluded`` treated as non-evidence.

    Per BUILD/DECISIONS.md DA6a: a leaf is ``excluded`` iff EVERY record for
    it is ``excluded`` (i.e. the leaf was never attempted at all — one
    fixture variant's extraction succeeding is proof the question WAS
    attempted). Otherwise the leaf is scored, and its outcome is derived by
    :func:`_collapse_leaf_group`'s DA6 unanimity rule over its SCORED records
    only — ``excluded`` records carry no marking-accuracy evidence and must
    not be allowed to make an otherwise-scored leaf look excluded or
    non-correct.
    """
    if all(r.outcome == "excluded" for r in group):
        return min(group, key=_leaf_sort_key)
    scored = [r for r in group if r.outcome != "excluded"]
    return _collapse_leaf_group(scored)


def _distinct_leaves_scored_aware(records: list[EvalRecord]) -> list[EvalRecord]:
    """DA6a leaf collapse.

    Like :func:`_distinct_leaves`, but ``excluded`` records only make a leaf
    ``excluded`` when they are the ONLY evidence for that leaf (see
    :func:`_collapse_leaf_group_scored_aware`).

    Used by :func:`exclusion_funnel`, which — unlike ``wilson``/
    ``review_rate``/``risk_coverage`` — must classify leaves as
    scored-vs-excluded itself rather than starting from an already
    ``_scored()``-filtered record list; it therefore needs a collapse rule
    that makes the same scored/excluded call those functions make, so its
    scored-leaf count matches their denominator exactly (spec §9 gate 7).
    """
    groups: dict[tuple[str, str], list[EvalRecord]] = {}
    for r in records:
        groups.setdefault((r.paper_id, r.question_id), []).append(r)
    return [_collapse_leaf_group_scored_aware(group) for group in groups.values()]


def _scored(records: list[EvalRecord]) -> list[EvalRecord]:
    """Rows counted in the ``mark_accuracy`` denominator (spec §3.3 table).

    ``excluded`` (never attempted) is the only outcome dropped here.
    """
    return [r for r in records if r.outcome != "excluded"]


# ---------------------------------------------------------------------------
# ablation_2x2
# ---------------------------------------------------------------------------


class Ablation2x2Result(TypedDict):
    both_correct: int
    extraction_attributable: int
    marking_attributable: int
    masked: int


def ablation_2x2(records: list[EvalRecord]) -> Ablation2x2Result:
    """Cross-tabulate ``oracle+mark`` outcome against ``extract+mark`` outcome.

    Per question (spec M0.4 acceptance): both-correct; extraction-attributable
    (oracle correct, extract wrong); marking-attributable (both wrong);
    masked (oracle wrong, extract correct).
    """
    qlevel = _distinct_leaves_by_arm(_question_level(records))
    oracle = qlevel["oracle+mark"]
    extract = qlevel["extract+mark"]

    result: Ablation2x2Result = {
        "both_correct": 0,
        "extraction_attributable": 0,
        "marking_attributable": 0,
        "masked": 0,
    }
    for key, o in oracle.items():
        e = extract.get(key)
        if e is None:
            continue
        o_correct = o.outcome == "correct"
        e_correct = e.outcome == "correct"
        if o_correct and e_correct:
            result["both_correct"] += 1
        elif o_correct and not e_correct:
            result["extraction_attributable"] += 1
        elif not o_correct and not e_correct:
            result["marking_attributable"] += 1
        else:  # not o_correct and e_correct
            result["masked"] += 1
    return result


def _distinct_leaves_by_arm(
    records: list[EvalRecord],
) -> dict[str, dict[tuple[str, str], EvalRecord]]:
    """Per-arm DA6 collapse, keyed by ``(paper_id, question_id)``.

    See :func:`_collapse_leaf_group` for the collapse rule.
    """
    groups: dict[str, dict[tuple[str, str], list[EvalRecord]]] = {
        "oracle+mark": {},
        "extract+mark": {},
    }
    for r in records:
        bucket = groups.get(r.arm)
        if bucket is None:
            continue
        key = (r.paper_id, r.question_id)
        bucket.setdefault(key, []).append(r)
    return {
        arm: {key: _collapse_leaf_group(group) for key, group in bucket.items()}
        for arm, bucket in groups.items()
    }


# ---------------------------------------------------------------------------
# mcnemar
# ---------------------------------------------------------------------------


class McNemarResult(TypedDict):
    b: int
    c: int
    n_pairs: int
    chi2: float
    p_value: float


def mcnemar(records: list[EvalRecord]) -> McNemarResult:
    """Paired McNemar test between ``oracle+mark`` and ``extract+mark`` arms.

    Computed over distinct leaves matched by ``(paper_id, question_id)``.
    ``b`` = oracle correct, extract wrong; ``c`` = oracle wrong, extract
    correct. Uses the continuity-corrected chi-square statistic with 1
    degree of freedom; the p-value is exact for 1 df via the complementary
    error function (no scipy dependency).
    """
    qlevel = _distinct_leaves_by_arm(_question_level(records))
    oracle = qlevel["oracle+mark"]
    extract = qlevel["extract+mark"]

    b = c = n_pairs = 0
    for key, o in oracle.items():
        e = extract.get(key)
        if e is None:
            continue
        n_pairs += 1
        o_correct = o.outcome == "correct"
        e_correct = e.outcome == "correct"
        if o_correct and not e_correct:
            b += 1
        elif not o_correct and e_correct:
            c += 1

    if b + c == 0:
        return {"b": b, "c": c, "n_pairs": n_pairs, "chi2": 0.0, "p_value": 1.0}

    chi2 = ((abs(b - c) - 1) ** 2) / (b + c)
    p_value = math.erfc(math.sqrt(chi2 / 2))
    return {"b": b, "c": c, "n_pairs": n_pairs, "chi2": chi2, "p_value": p_value}


# ---------------------------------------------------------------------------
# wilson
# ---------------------------------------------------------------------------


class WilsonResult(TypedDict):
    n: int
    successes: int
    point: float
    lower: float
    upper: float


def wilson(records: list[EvalRecord], *, z: float = 1.96) -> WilsonResult:
    """95%-by-default Wilson score interval on the ``correct`` proportion.

    Computed over the scored, question-level, distinct-leaf subset (spec
    §3.3's ``mark_accuracy`` denominator). Returns full uncertainty
    (``[0.0, 1.0]``) at ``n == 0`` rather than dividing by zero.
    """
    leaves = _distinct_leaves(_scored(_question_level(records)))
    n = len(leaves)
    if n == 0:
        return {"n": 0, "successes": 0, "point": 0.0, "lower": 0.0, "upper": 1.0}

    successes = sum(1 for r in leaves if r.outcome == "correct")
    phat = successes / n
    denominator = 1 + z**2 / n
    center = phat + z**2 / (2 * n)
    margin = z * math.sqrt(phat * (1 - phat) / n + z**2 / (4 * n**2))
    lower = max(0.0, (center - margin) / denominator)
    upper = min(1.0, (center + margin) / denominator)
    return {"n": n, "successes": successes, "point": phat, "lower": lower, "upper": upper}


# ---------------------------------------------------------------------------
# risk_coverage
# ---------------------------------------------------------------------------


class RiskCoveragePoint(TypedDict):
    coverage: float
    risk: float
    threshold: float


def risk_coverage(records: list[EvalRecord]) -> list[RiskCoveragePoint]:
    """Risk-coverage curve: sorted by descending ``marker_conf``.

    Rows without a ``marker_conf`` cannot be placed on the curve and are
    excluded. Question-level, scored, distinct-leaf rows only.
    """
    leaves = [
        r for r in _distinct_leaves(_scored(_question_level(records))) if r.marker_conf is not None
    ]
    if not leaves:
        return []

    ordered = sorted(leaves, key=lambda r: r.marker_conf, reverse=True)  # type: ignore[arg-type,return-value]
    n = len(ordered)
    points: list[RiskCoveragePoint] = []
    errors = 0
    for i, r in enumerate(ordered, start=1):
        if r.outcome != "correct":
            errors += 1
        points.append(
            {
                "coverage": round(i / n, 10),
                "risk": round(errors / i, 10),
                "threshold": r.marker_conf,  # type: ignore[typeddict-item]
            }
        )
    return points


# ---------------------------------------------------------------------------
# exclusion_funnel
# ---------------------------------------------------------------------------


class ExclusionFunnelResult(TypedDict):
    total: int
    scored: int
    excluded: int
    by_outcome: dict[str, int]


def exclusion_funnel(records: list[EvalRecord]) -> ExclusionFunnelResult:
    """Publish the funnel: how many leaves were never attempted vs scored.

    Per spec §3.3's outcome-semantics table, only ``excluded`` (never
    attempted — non-leaf, no scan region) is dropped from the scored
    denominator. Per BUILD/DECISIONS.md DA6a, a leaf counts as ``excluded``
    here iff EVERY record for it is ``excluded`` — matching the leaf set
    that ``wilson``/``review_rate``/``risk_coverage`` treat as scored, so
    this funnel's ``scored`` count never disagrees with the denominator it
    exists to explain (spec §9 gate 7).
    """
    leaves = _distinct_leaves_scored_aware(_question_level(records))
    by_outcome: dict[str, int] = {}
    for r in leaves:
        by_outcome[r.outcome] = by_outcome.get(r.outcome, 0) + 1

    excluded = by_outcome.get("excluded", 0)
    total = len(leaves)
    return {
        "total": total,
        "scored": total - excluded,
        "excluded": excluded,
        "by_outcome": by_outcome,
    }


# ---------------------------------------------------------------------------
# review_rate
# ---------------------------------------------------------------------------


class ReviewRateResult(TypedDict):
    n: int
    review_rate_signal: float
    review_rate_total: float
    per_paper_p95: float


def review_rate(records: list[EvalRecord]) -> ReviewRateResult:
    """Two-part review-rate gate (spec §5): signal vs total, plus per-paper p95.

    ``review_rate_total`` counts any non-empty ``triggers`` list as reviewed.
    ``review_rate_signal`` counts everything except the ``random_audit``
    trigger (until T1.10/M4 ships that trigger, the two are equal). Computed
    over the scored, question-level, distinct-leaf subset.
    """
    leaves = _distinct_leaves(_scored(_question_level(records)))
    n = len(leaves)
    if n == 0:
        return {"n": 0, "review_rate_signal": 0.0, "review_rate_total": 0.0, "per_paper_p95": 0.0}

    total_reviewed = sum(1 for r in leaves if r.triggers)
    signal_reviewed = sum(1 for r in leaves if [t for t in r.triggers if t != "random_audit"])

    by_paper: dict[str, list[EvalRecord]] = {}
    for r in leaves:
        by_paper.setdefault(r.paper_id, []).append(r)
    per_paper_rates = sorted(
        sum(1 for r in rows if r.triggers) / len(rows) for rows in by_paper.values()
    )
    per_paper_p95 = _percentile(per_paper_rates, 0.95)

    return {
        "n": n,
        "review_rate_signal": signal_reviewed / n,
        "review_rate_total": total_reviewed / n,
        "per_paper_p95": per_paper_p95,
    }


def _percentile(sorted_values: list[float], p: float) -> float:
    """Nearest-rank percentile over an already-sorted list; 0.0 when empty."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    idx = math.ceil(p * len(sorted_values)) - 1
    idx = max(0, min(idx, len(sorted_values) - 1))
    return sorted_values[idx]
