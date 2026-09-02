"""Pure statistical analyses over ``list[EvalRecord]`` (spec §3.3).

Includes ``paper_grade_confidence`` (spec §4 M1.1), the paper-level
grade-confidence rule added alongside the M1.1 confidence-propagation unit.

No I/O, no Gemini calls, no filesystem access — every function here is a
plain function of its input list. Every analysis filters to question-level
rows (``mark_point_id is None``) before aggregating, unless the analysis is
explicitly point-level, and every interval/power calculation collapses to
**distinct leaves** first (one row per ``(paper_id, question_id)``), per
spec §3.3.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Literal, TypedDict

if TYPE_CHECKING:
    from lemely.eval.records import EvalRecord

ConfidenceBandLabel = Literal["HIGH", "MEDIUM", "LOW"]

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


def _group_by_leaf(records: list[EvalRecord]) -> dict[tuple[str, str], list[EvalRecord]]:
    """Group records by ``(paper_id, question_id)`` leaf, preserving raw rows.

    Shared by every analysis that needs to reason about a leaf's full set of
    raw (pre-collapse) records — e.g. :func:`_distinct_leaves`, which then
    collapses each group to one representative row, and :func:`review_rate`,
    which unions a property (``triggers``) across a group WITHOUT collapsing
    it to a single representative first (collapsing before checking
    ``triggers`` would silently discard sibling records' trigger info — see
    :func:`review_rate`'s docstring).
    """
    groups: dict[tuple[str, str], list[EvalRecord]] = {}
    for r in records:
        groups.setdefault((r.paper_id, r.question_id), []).append(r)
    return groups


def _distinct_leaves(records: list[EvalRecord]) -> list[EvalRecord]:
    """Collapse to one row per ``(paper_id, question_id)`` leaf (DA6).

    Interval/power calculations must not be inflated by duplicate rows for
    the same leaf (e.g. accidental point-level rows slipping through, or
    genuine DA6 fixture-variant duplicates). See :func:`_collapse_leaf_group`
    for how a leaf's collapsed outcome is derived.
    """
    return [_collapse_leaf_group(group) for group in _group_by_leaf(records).values()]


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

    Two caveats govern how a result from this function may be interpreted
    (#28/M0.4):

    - The ``extraction_attributable`` share is a LOWER BOUND ONLY. The
      fixture renderer (``synth.py``) cannot render superscripts or
      crossings-out, so synthetic golden fixtures understate real
      extraction difficulty relative to genuine student scripts — this is
      licensed by M0.0/#56 (closed; see git log for confirmation).
    - The golden corpus currently has 31 distinct leaves, far below
      :data:`MCNEMAR_IMPROVEMENT_N_FLOOR` (219). Any single 2x2 result
      produced from this corpus is therefore a bounded no-detection
      statement, never a directional claim about whether extraction or
      marking dominates error.
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
# mcnemar / n-floor
# ---------------------------------------------------------------------------

#: Paired-McNemar sample-size floor for IMPROVEMENT CLAIMS (spec §6): the n
#: needed to detect an improvement from 83.8% to 88.8% at alpha=0.05,
#: power=0.80 (vs. n=741 unpaired, per arm). This floor governs whether a
#: McNemar result may be PRESENTED as evidence of improvement — see
#: :func:`mcnemar_improvement_p_value`, the sole place that refusal happens.
#: ``mcnemar()`` itself always computes and returns the numeric chi2/p_value
#: regardless of ``n_pairs`` vs. this floor; it does not gate the underlying
#: computation, only the ``underpowered`` flag callers must check before
#: treating the statistic as an improvement claim. See BUILD/DECISIONS.md
#: DA7 for the derivation and why this constant (not a recomputed value) is
#: the source of truth.
MCNEMAR_IMPROVEMENT_N_FLOOR = 219


def _inverse_normal_cdf(p: float) -> float:
    """Standard-normal quantile function (Peter Acklam's rational approximation).

    Max error ~1.15e-9; used only to turn ``alpha``/``power`` into z-scores
    for :func:`paired_proportion_min_n` — no scipy dependency, matching the
    rest of this module.
    """
    a = (
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    )
    b = (
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    )
    c = (
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    )
    d = (
        7.784695709041462e-03,
        3.224671290700398e-01,
        2.445134137142996e00,
        3.754408661907416e00,
    )
    p_low = 0.02425
    p_high = 1 - p_low

    if p < p_low:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
        )
    if p <= p_high:
        q = p - 0.5
        r = q * q
        return ((((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q) / (
            ((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1
        )
    q = math.sqrt(-2 * math.log(1 - p))
    return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
        (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
    )


def paired_proportion_min_n(p1: float, p2: float, *, alpha: float, power: float) -> int:
    """Conservative lower bound on the paired (McNemar) sample size needed to detect ``p1 -> p2``.

    Implements the Connor (1987) / Fleiss favourable-case bound: the
    discordant-pair proportion ``psi`` (how often the two arms disagree on
    the same leaf) is set to its *minimum possible* value, ``psi = d =
    |p2 - p1|`` — the case where every discordant pair moves in the
    ``p1 -> p2`` direction and none reverse. Substituting ``psi = d`` into
    the general paired-proportion sample-size formula

        n = ceil((z_a*sqrt(psi) + z_b*sqrt(psi - d**2))**2 / d**2)

    gives ``psi - d**2 = d*(1 - d)`` and so

        n = ceil((z_a*sqrt(d) + z_b*sqrt(d*(1 - d)))**2 / d**2)

    Any real correlation structure between the two arms needs *at least*
    this many pairs (a smaller discordant-pair proportion than ``d`` is
    impossible, since the marginal difference IS the minimum discordance),
    so this is a genuine, independently-checkable lower bound — but it is
    still not :data:`MCNEMAR_IMPROVEMENT_N_FLOOR`'s exact derivation: the
    actual discordant-pair rate between ``oracle+mark`` and ``extract+mark``
    is an empirical quantity this module has no measurement of yet, so
    ``MCNEMAR_IMPROVEMENT_N_FLOOR`` is taken directly from spec §6 rather
    than recomputed here (see BUILD/DECISIONS.md).
    """
    if not 0.0 < p1 < 1.0 or not 0.0 < p2 < 1.0:
        raise ValueError("p1 and p2 must be in (0, 1)")
    d = abs(p2 - p1)
    if d <= 0.0:
        raise ValueError("p1 and p2 must differ to have a detectable effect")
    z_alpha = _inverse_normal_cdf(1 - alpha / 2)
    z_beta = _inverse_normal_cdf(power)
    return math.ceil((z_alpha * math.sqrt(d) + z_beta * math.sqrt(d * (1 - d))) ** 2 / d**2)


class McNemarResult(TypedDict):
    b: int
    c: int
    n_pairs: int
    underpowered: bool
    chi2: float
    p_value: float


def mcnemar(records: list[EvalRecord]) -> McNemarResult:
    """Paired McNemar test between ``oracle+mark`` and ``extract+mark`` arms.

    Computed over distinct leaves matched by ``(paper_id, question_id)``.
    ``b`` = oracle correct, extract wrong; ``c`` = oracle wrong, extract
    correct. Uses the continuity-corrected chi-square statistic with 1
    degree of freedom; the p-value is exact for 1 df via the complementary
    error function (no scipy dependency).

    ``chi2``/``p_value`` are ALWAYS computed and returned as real numbers,
    regardless of ``n_pairs`` vs. :data:`MCNEMAR_IMPROVEMENT_N_FLOOR` — a
    below-floor sample size makes the statistic unfit to present as an
    IMPROVEMENT CLAIM (that refusal lives solely in
    :func:`mcnemar_improvement_p_value`), but the number itself is real and
    a caller doing its own analysis (e.g. plotting, an ablation breakdown)
    must not be handed ``None`` for it. ``underpowered`` is ``True`` iff
    ``n_pairs < MCNEMAR_IMPROVEMENT_N_FLOOR`` (spec §6/M0.6).
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

    underpowered = n_pairs < MCNEMAR_IMPROVEMENT_N_FLOOR

    if b + c == 0:
        chi2 = 0.0
        p_value = 1.0
    else:
        chi2 = ((abs(b - c) - 1) ** 2) / (b + c)
        p_value = math.erfc(math.sqrt(chi2 / 2))

    return {
        "b": b,
        "c": c,
        "n_pairs": n_pairs,
        "underpowered": underpowered,
        "chi2": chi2,
        "p_value": p_value,
    }


def mcnemar_improvement_p_value(result: McNemarResult) -> float | str:
    """Refuse to present a bare p-value as an improvement claim when underpowered.

    This is the ONLY place that refusal happens (spec §6/M0.6) — ``mcnemar``
    itself always computes and returns the numeric statistic (see its
    docstring). Returns the literal ``"underpowered"`` when
    ``result["underpowered"]`` is ``True``; otherwise returns
    ``result["p_value"]`` unchanged.
    """
    if result["underpowered"]:
        return "underpowered"
    return result["p_value"]


# ---------------------------------------------------------------------------
# wilson
# ---------------------------------------------------------------------------


class WilsonResult(TypedDict):
    n: int
    successes: int
    point: float
    lower: float
    upper: float


def _wilson_interval(*, successes: int, n: int, z: float = 1.96) -> WilsonResult:
    """95%-by-default Wilson score interval on a bare ``(successes, n)`` pair.

    Pure arithmetic, no knowledge of ``EvalRecord`` or any leaf-collapse
    rule — :func:`wilson` (question-level, scored, distinct-leaf mark
    accuracy) and :func:`agreement_wilson` (labeller-A/labeller-B agreement)
    both delegate to this one implementation rather than forking it (#98).
    Returns full uncertainty (``[0.0, 1.0]``) at ``n == 0`` rather than
    dividing by zero.
    """
    if n == 0:
        return {"n": 0, "successes": 0, "point": 0.0, "lower": 0.0, "upper": 1.0}

    phat = successes / n
    denominator = 1 + z**2 / n
    center = phat + z**2 / (2 * n)
    margin = z * math.sqrt(phat * (1 - phat) / n + z**2 / (4 * n**2))
    lower = max(0.0, (center - margin) / denominator)
    upper = min(1.0, (center + margin) / denominator)
    return {"n": n, "successes": successes, "point": phat, "lower": lower, "upper": upper}


def wilson(records: list[EvalRecord], *, z: float = 1.96) -> WilsonResult:
    """95%-by-default Wilson score interval on the ``correct`` proportion.

    Computed over the scored, question-level, distinct-leaf subset (spec
    §3.3's ``mark_accuracy`` denominator). Returns full uncertainty
    (``[0.0, 1.0]``) at ``n == 0`` rather than dividing by zero.
    """
    leaves = _distinct_leaves(_scored(_question_level(records)))
    n = len(leaves)
    successes = sum(1 for r in leaves if r.outcome == "correct")
    return _wilson_interval(successes=successes, n=n, z=z)


# ---------------------------------------------------------------------------
# agreement_wilson
# ---------------------------------------------------------------------------


class MarkingLeafRecord(TypedDict):
    """One labeller-marking record over a leaf (spec §6 pass-2 shape, kept plain).

    Deliberately a bare ``TypedDict``, not
    ``lemely.labelling.records.MarkingRecordPayload`` — this module's "no
    IO, no app" purity contract forbids importing ``lemely.labelling``
    (which does filesystem IO), so label-record data crosses the boundary
    as plain data, never as an imported label-IO type.
    """

    paper_id: str
    question_id: str
    awarded_marks: int
    mark_point_id: str | None
    mark_point_verdicts: dict[str, bool]


def _distinct_marking_leaves(records: list[MarkingLeafRecord]) -> dict[tuple[str, str], int]:
    """Collapse raw marking records to one ``awarded_marks`` per distinct leaf.

    **Leaf identity is ``(paper_id, question_id)``** — the same key
    :func:`_group_by_leaf` and :func:`_distinct_leaves` use for DA6. Keying
    on ``question_id`` alone would merge ``1a`` from every paper into one
    leaf, shrinking the denominator *and* silently discarding every
    disagreement but one: exactly the D18 narrowed-denominator shape this
    programme exists to eliminate, and a direct breach of spec §9 gate 7.

    Repeated records for one leaf must not be counted as separate leaves.
    **The last record wins.** The label log is append-only
    (``lemely.labelling.records``), so a labeller correcting a mistake
    appends a second record rather than editing the first; taking the
    earliest would let a stale value drive the agreement figure while the
    correction sits unread in the same file.

    A question-level row (``mark_point_id is None``) is preferred over a
    per-mark-point row for the same leaf, but only among the *latest* rows —
    and no invariant is assumed about mark-point rows agreeing with each
    other. (``MarkingRecordPayload`` carries no ``mark_point_id`` at all
    today, so on current data every row is question-level; the branch exists
    for the per-mark-point shape spec §6 anticipates, and must not be
    justified by a construction that does not exist.)
    """
    return {k: r["awarded_marks"] for k, r in _leaf_representatives(records).items()}


def _leaf_representatives(
    records: list[MarkingLeafRecord],
) -> dict[tuple[str, str], MarkingLeafRecord]:
    """Collapse raw marking records to one representative record per leaf.

    The selection rule is :func:`_distinct_marking_leaves`' — last record wins,
    question-level preferred among the latest — factored out so the totals
    figure and the per-mark-point figure are computed from the *same* chosen
    record. Two selection rules would let the two figures disagree about which
    record a leaf's label is, which is worse than either rule being wrong.
    """
    by_leaf: dict[tuple[str, str], list[MarkingLeafRecord]] = {}
    for r in records:
        by_leaf.setdefault((r["paper_id"], r["question_id"]), []).append(r)
    result: dict[tuple[str, str], MarkingLeafRecord] = {}
    for leaf_key, group in by_leaf.items():
        question_level = [r for r in group if r.get("mark_point_id") is None]
        result[leaf_key] = question_level[-1] if question_level else group[-1]
    return result


def _distinct_marking_points(
    records: list[MarkingLeafRecord],
) -> dict[tuple[str, str, str], bool]:
    """Expand each leaf's representative record into per-mark-point verdicts.

    **Point identity is ``(paper_id, question_id, mark_point_id)``** — DA6's
    leaf key with one component added, for the same reason DA6 exists. Keying
    on ``mark_point_id`` alone would merge ``p1`` from every leaf in the corpus
    into a single point, shrinking the denominator *and* discarding every
    disagreement but one: the D18 narrowed-denominator shape one level down.
    """
    return {
        (paper_id, question_id, point_id): verdict
        for (paper_id, question_id), rep in _leaf_representatives(records).items()
        for point_id, verdict in rep["mark_point_verdicts"].items()
    }


class AgreementResult(WilsonResult):
    """A Wilson interval that carries its own exclusion funnel (§9 gate 7).

    Gate 7 requires a reported rate to name its denominator **and its
    exclusions**. Naming them in a docstring does not satisfy it: a docstring
    does not travel with the published figure, and a reader handed
    ``n=28, point=0.86`` cannot tell whether 2 leaves were excluded or 200 —
    the difference between a sound 10% sample and a silently narrowed one.

    ``a_only`` and ``b_only`` are **aggregate counts only**. Per DA2, on
    disagreement labeller A's label stands, so nothing per-leaf may appear
    here: a per-leaf field would be one refactor away from being read as a
    corrected A-label.
    """

    a_only: int
    """Distinct leaves A marked that B did not — missing data, not disagreement."""

    b_only: int
    """Distinct leaves B marked that A did not — missing data, not disagreement."""

    shared_leaves: int
    """Distinct leaves both labellers marked — the leaf-stage denominator.

    Reported because ``n`` counts mark points (B12/#140), so without it the
    funnel cannot be read: ``n=40`` over 5 shared leaves and ``n=40`` over 40
    are different measurements.
    """

    shared_leaves_without_shared_points: int
    """Shared leaves contributing **zero** shared mark points.

    A leaf both labellers marked can still contribute nothing — neither
    recorded verdicts, or they recorded disjoint point ids. Under a per-point
    denominator such leaves vanish without trace, which is the
    narrowed-denominator failure mode in a new costume; counting them is what
    makes the shrinkage visible.
    """

    points_a_only: int
    """Mark points A recorded that B did not, **within shared leaves only**.

    Scoped to shared leaves deliberately: points belonging to leaves the other
    labeller never sampled are already accounted for by ``a_only``/``b_only``,
    and counting them here as well would double-count the same exclusion.
    """

    points_b_only: int
    """Mark points B recorded that A did not, within shared leaves only."""

    totals_n: int
    """Secondary figure: shared leaves scored by ``awarded_marks`` equality."""

    totals_successes: int
    """Secondary figure: shared leaves whose ``awarded_marks`` totals match."""

    totals_point: float
    """Secondary figure: the totals-equality agreement rate.

    Kept, not deleted, when B12 moved the headline to mark points. B12 predicts
    the per-point figure reads **lower**; that prediction is only checkable if
    both numbers travel together. A single number cannot demonstrate its own drop.

    **Read it with ``totals_lower``/``totals_upper``, never alone.** At
    ``totals_n == 0`` this is ``0.0`` — the module-wide convention
    (:func:`_wilson_interval` does the same) — which reads as "0% agreement"
    rather than "no data". The interval is what disambiguates the two: no data
    gives ``[0.0, 1.0]``, genuine total disagreement does not.
    """

    totals_lower: float
    """Secondary figure: lower Wilson bound on the totals-equality rate."""

    totals_upper: float
    """Secondary figure: upper Wilson bound on the totals-equality rate."""


def agreement_wilson(
    a_records: list[MarkingLeafRecord],
    b_records: list[MarkingLeafRecord],
    *,
    rulings_settled: bool,
    z: float = 1.96,
) -> AgreementResult:
    """Inter-annotator agreement between labeller A and labeller B (DA2/#51/H7).

    Per DA2, this is genuine two-labeller agreement, not delayed
    self-agreement. **On disagreement, A's label stands** — this function is
    read-only: it never mutates, reorders, or appends to ``a_records``
    (or ``b_records``), and its return type (:class:`WilsonResult`) carries
    no per-leaf field that could be mistaken for a corrected A-label, only
    the aggregate ``(n, successes, point, lower, upper)`` summary.

    **The headline figure is PER MARK POINT** (B12, #140), not equality of
    ``awarded_marks`` totals. Spec §6 defines the pass-2 output per mark point,
    and two labellers can award the same total by crediting *different* points —
    totals equality scores that as agreement, which overstates it. Expect the
    per-point number to read **lower**; that is the measurement working, not a
    regression, and the totals figure is kept beside it (``totals_n``,
    ``totals_successes``, ``totals_point``) precisely so the drop is visible.

    **Denominator, named explicitly**: distinct **mark points** — keyed
    ``(paper_id, question_id, mark_point_id)``, DA6's leaf key with one
    component added (``_distinct_marking_points``) — recorded by **both**
    labellers on a leaf **both** marked. Two exclusion stages, both returned
    rather than described (spec §9 gate 7):

    - **Leaf stage**: a leaf only one labeller marked is missing data, not a
      disagreement — ``a_only`` / ``b_only``, still counted in *leaves*.
    - **Point stage**, scoped to shared leaves so nothing is double-counted: a
      point only one labeller recorded — ``points_a_only`` / ``points_b_only``;
      and shared leaves contributing **zero** shared points —
      ``shared_leaves_without_shared_points``, which is the one a per-point
      denominator would otherwise swallow without trace.

    Those exclusions are **returned, not just described** — see
    :class:`AgreementResult`. Gate 7 is not satisfied by a docstring.

    ``rulings_settled`` is a **required** keyword with no default, and this
    call raises when it is false. It is how DA3 and DA5 stop being prose:

    - **DA3** requires the ``pending_ruling`` tail to reach zero before the
      split freeze, and the freeze is irreversible.
    - **DA5** requires #52's ruling sweep to run **before** #51's sample.

    Neither can be checked here — an import-linter contract ("Evaluation
    analyses must stay pure — no IO") bars this module from importing
    :mod:`lemely.labelling`, which does filesystem reads. Forcing the caller
    to pass the answer puts the precondition at the one place a number is
    actually produced, instead of leaving it in ``DECISIONS.md`` for a future
    run to walk past — which is how #49 was closed with an unmet box.

    **The flag must come from**
    :func:`lemely.labelling.rulings.assert_rulings_settled`, never a literal
    ``True``. A hard-coded ``True`` at a call site is the same defect as no
    check at all, and it is visible in review precisely because it has to be
    written down.

    Delegates the interval arithmetic to :func:`_wilson_interval` — the same
    helper :func:`wilson` uses — rather than a second implementation.
    """
    if not rulings_settled:
        raise ValueError(
            "refusing to compute agreement: rulings are not settled. DA3 requires "
            "the pending_ruling tail at zero (and no orphan resolutions) before the "
            "split freeze, and DA5 requires #52's sweep before #51's sample. Call "
            "lemely.labelling.rulings.assert_rulings_settled() and pass its result."
        )
    a_leaves = _distinct_marking_leaves(a_records)
    b_leaves = _distinct_marking_leaves(b_records)
    shared_leaves = set(a_leaves) & set(b_leaves)

    # Secondary: the totals-equality figure the headline used to be.
    totals_n = len(shared_leaves)
    totals_successes = sum(1 for leaf in shared_leaves if a_leaves[leaf] == b_leaves[leaf])

    # Headline: per mark point, scoped to leaves BOTH labellers marked so a
    # leaf-level exclusion is never re-counted as a point-level one.
    a_points = {
        k: v for k, v in _distinct_marking_points(a_records).items() if k[:2] in shared_leaves
    }
    b_points = {
        k: v for k, v in _distinct_marking_points(b_records).items() if k[:2] in shared_leaves
    }
    shared_points = set(a_points) & set(b_points)
    n = len(shared_points)
    successes = sum(1 for p in shared_points if a_points[p] == b_points[p])

    leaves_with_shared_points = {p[:2] for p in shared_points}
    interval = _wilson_interval(successes=successes, n=n, z=z)
    # The totals figure gets its own interval from the SAME helper, not a bare
    # rate: at totals_n == 0 a lone `0.0` reads as "total disagreement" when it
    # means "no data", and only the [0.0, 1.0] interval tells the two apart.
    totals_interval = _wilson_interval(successes=totals_successes, n=totals_n, z=z)
    return {
        **interval,
        "a_only": len(set(a_leaves) - set(b_leaves)),
        "b_only": len(set(b_leaves) - set(a_leaves)),
        "shared_leaves": len(shared_leaves),
        "shared_leaves_without_shared_points": len(shared_leaves - leaves_with_shared_points),
        "points_a_only": len(set(a_points) - set(b_points)),
        "points_b_only": len(set(b_points) - set(a_points)),
        "totals_n": totals_n,
        "totals_successes": totals_successes,
        "totals_point": totals_interval["point"],
        "totals_lower": totals_interval["lower"],
        "totals_upper": totals_interval["upper"],
    }


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

    ``review_rate_total`` counts a leaf as reviewed iff ANY of its raw
    (pre-DA6-collapse) records carries a non-empty ``triggers`` list —
    a UNION over the leaf's fixture-variant/duplicate records, not a
    property read off the single DA6-collapsed representative row.
    ``review_rate_signal`` is the same union restricted to triggers other
    than ``random_audit`` (until T1.10/M4 ships that trigger, the two are
    equal). This matters because DA6's representative-picker
    (:func:`_collapse_leaf_group`) is free to choose ANY record among a set
    of unanimously-``correct`` variants — if a leaf's variants are all
    ``correct`` but only one of them was flagged for review, reading
    ``triggers`` off the (possibly different) collapsed representative would
    silently drop that flag. The leaf-count denominator (``n``) still comes
    from the DA6-collapsed distinct-leaf count, matching every other
    analysis's leaf discipline — only the reviewed/not-reviewed numerator is
    computed from the raw, uncollapsed group.

    **Callers MUST pass only records from a dev-split run** (``RunManifest.split
    == "dev"``) — spec §5's review-rate budget is defined over the golden dev
    split, and ``EvalRecord`` itself carries no ``split`` field (split lives on
    the run's ``RunManifest``, one level up), so this function cannot check the
    restriction itself. This was previously implicit-by-caller-convention; the
    M0.9 gate (:mod:`lemely.eval.review_gate`) and its callers (the
    ``measure-accuracy`` CLI, ``scripts/check_review_rate_gate.py``) make it
    explicit by only ever invoking this against a dev-split run's records.
    """
    scored_qlevel = _scored(_question_level(records))
    leaf_groups = _group_by_leaf(scored_qlevel)
    n = len(leaf_groups)
    if n == 0:
        return {"n": 0, "review_rate_signal": 0.0, "review_rate_total": 0.0, "per_paper_p95": 0.0}

    total_reviewed = 0
    signal_reviewed = 0
    by_paper: dict[str, list[bool]] = {}
    for (paper_id, _question_id), group in leaf_groups.items():
        leaf_total = any(r.triggers for r in group)
        leaf_signal = any(t != "random_audit" for r in group for t in r.triggers)
        total_reviewed += leaf_total
        signal_reviewed += leaf_signal
        by_paper.setdefault(paper_id, []).append(leaf_total)

    per_paper_rates = sorted(sum(flags) / len(flags) for flags in by_paper.values())
    per_paper_p95 = _percentile(per_paper_rates, 0.95)

    return {
        "n": n,
        "review_rate_signal": signal_reviewed / n,
        "review_rate_total": total_reviewed / n,
        "per_paper_p95": per_paper_p95,
    }


# ---------------------------------------------------------------------------
# coherence_trigger_rate
# ---------------------------------------------------------------------------


class CoherenceTriggerRateResult(TypedDict):
    n: int
    coherence_trigger_rate: float


def coherence_trigger_rate(records: list[EvalRecord]) -> CoherenceTriggerRateResult:
    """M1.5 (#40): the coherence gate's own contribution to review volume.

    Reported as its OWN number, distinct from and never folded into
    ``review_rate_signal``/``review_rate_total`` (spec §9 review-trigger
    discipline for a newly-added trigger) — this function does not touch,
    arm, or re-tune the M0.9 ratchet (``review_rate_ratchet_armed`` stays
    False; see ``lemely/eval/review_gate.py`` and
    ``lemely/runtime/config.py``, neither of which this touches).

    Same leaf discipline as :func:`review_rate`: ``n`` is the DA6-collapse-
    aware distinct-leaf count over ``_scored`` question-level rows, and a
    leaf counts as coherence-flagged via a UNION over its RAW (pre-collapse)
    group's ``triggers`` — not a property read off a single collapsed
    representative row, for the same reason :func:`review_rate` uses a union
    (see its docstring).
    """
    scored_qlevel = _scored(_question_level(records))
    leaf_groups = _group_by_leaf(scored_qlevel)
    n = len(leaf_groups)
    if n == 0:
        return {"n": 0, "coherence_trigger_rate": 0.0}

    flagged = sum(
        1
        for group in leaf_groups.values()
        if any("coherence_mismatch" in r.triggers for r in group)
    )
    return {"n": n, "coherence_trigger_rate": flagged / n}


def _percentile(sorted_values: list[float], p: float) -> float:
    """Nearest-rank percentile over an already-sorted list; 0.0 when empty."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    idx = math.ceil(p * len(sorted_values)) - 1
    idx = max(0, min(idx, len(sorted_values) - 1))
    return sorted_values[idx]


# ---------------------------------------------------------------------------
# paper_grade_confidence
# ---------------------------------------------------------------------------


def _band_for_score(score: float) -> ConfidenceBandLabel:
    if score >= 0.85:
        return "HIGH"
    if score >= 0.65:
        return "MEDIUM"
    return "LOW"


def paper_grade_confidence(
    records: list[EvalRecord],
) -> dict[str, tuple[float, ConfidenceBandLabel]]:
    """Paper-level grade-confidence rule (spec §4 M1.1).

    Per paper, the marks-weighted mean of each question's marking-stage
    confidence (``marker_conf`` -- the confidence used everywhere else in the
    codebase for the marker's own certainty, distinct from ``extraction_conf``
    which is extraction-side), weighted by the question's TARIFF
    (``maximum_marks``, marks available), banded HIGH >= 0.85 / MEDIUM >= 0.65
    / LOW below. Deliberately NOT a min-over-questions rule: a single
    low-confidence, low-weight question must not by itself sink an
    otherwise-confident paper's band.

    Weighting is deliberately NOT ``truth_marks`` (marks EARNED): weighting by
    what the student happened to score would make a high-tariff question
    answered wrong weigh less than the same question answered right, biasing
    the band upward and toward dropping exactly the low-confidence rows a
    grade-confidence signal should be most sensitive to. The weight is
    ``r.maximum_marks or r.truth_marks or 1`` -- the tariff when known,
    falling back to earned marks for rows written before ``maximum_marks``
    existed (never both zero/unknown, in which case the row still counts with
    unit weight rather than being dropped).

    Funnel: filters to question-level rows (``mark_point_id is None``) per
    spec §3.3's convention (the "considered" set). Of those, a row with
    ``marker_conf is None`` (no marking-stage confidence was ever produced --
    e.g. an "excluded"/"unmatched" outcome) carries no weight and is skipped
    entirely; every other row is weighted and counted, even one with
    ``truth_marks == 0`` (a paper scored zero throughout still gets a real
    band -- it is not omitted). A paper is omitted from the result only if
    every one of its question-level rows had ``marker_conf is None``, leaving
    nothing to average.
    """
    by_paper: dict[str, list[EvalRecord]] = {}
    for r in _question_level(records):
        by_paper.setdefault(r.paper_id, []).append(r)

    result: dict[str, tuple[float, ConfidenceBandLabel]] = {}
    for paper_id, group in by_paper.items():
        weighted_sum = 0.0
        total_weight = 0.0
        for r in group:
            if r.marker_conf is None:
                continue
            weight = float(r.maximum_marks or r.truth_marks or 1)
            weighted_sum += r.marker_conf * weight
            total_weight += weight
        if total_weight <= 0:
            continue
        score = weighted_sum / total_weight
        result[paper_id] = (score, _band_for_score(score))

    return result
