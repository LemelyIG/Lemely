"""Pure threshold fits for sub-project C lever d: the review and escalation thresholds, at $0.

Moved from ``scripts/fit_review_threshold.py`` (whose CLI stays). The fits read stored
results only: no client, no model call.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from lemely.accuracy.cost_ladder.real_split import read_real_results

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from lemely.accuracy.cost_ladder.real_split import LeafOutcome, RealScriptResult

#: The reason ``lemely.io.correction_ai`` writes when confidence alone flags a part.
CONFIDENCE_REASON = re.compile(r"^confidence \d+(?:\.\d+)? below review threshold \d+(?:\.\d+)?$")
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


RECALL_TARGET = 0.90
#: One Sonnet escalation reading the cached correction prefix (claude-e2e2 COST.md,
#: opportunity 3: $0.0015 cache read plus about 400 output tokens). Used only when a
#: rung made no escalation call to measure the cost from.
ESCALATION_USD_ESTIMATE = 0.0056


def recommend_for_recall(parts: Sequence[Part], *, recall: float = RECALL_TARGET) -> float | None:
    """The lowest grid threshold whose flag recall reaches *recall*; None if none does.

    None also when *parts* holds no mismarked part: there is nothing to recall, so no basis.
    """
    for t in threshold_grid():
        got = evaluate(parts, t).flag_recall
        if got is not None and got + _EPS >= recall:
            return t
    return None


def _structural(flag: bool, reason: str | None) -> bool:
    return flag and not (isinstance(reason, str) and CONFIDENCE_REASON.match(reason) is not None)


def _runs(paths: Sequence[Path]) -> list[tuple[str, list[RealScriptResult]]]:
    """Each run's name (its directory) and scripts; two runs sharing a name are refused.

    A shared name would merge two runs' scripts under one ``<run>:<script>`` case key.
    """
    names = [path.parent.name for path in paths]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    if duplicates:
        raise ValueError(f"run directories must have distinct names; repeated: {duplicates}")
    return [(path.parent.name, read_real_results(path)) for path in paths]


def _has_confidence(leaf: LeafOutcome) -> bool:
    """The one test for "scored" in the review fit; the rest of the leaves are excluded."""
    return leaf.confidence is not None


def parts_from_real(paths: Sequence[Path]) -> list[Part]:
    """Every scored leaf of a real rung's runs as a `Part`; mismarked means abs_error > 0.

    A leaf with no confidence (dropped, blank or missing: never scored) is left out, not
    read as confidence 0; `unscored_leaves` counts them.
    """
    parts: list[Part] = []
    for run, scripts in _runs(paths):
        for script in scripts:
            for leaf in script.leaves:
                if leaf.confidence is None:
                    continue
                refittable = (
                    leaf.marker_source == "ai"
                    and not leaf.escalated
                    and not _structural(leaf.needs_review, leaf.review_reason)
                )
                parts.append(
                    Part(
                        case_key=f"{run}:{script.key}",
                        question_id=leaf.question_id,
                        confidence=leaf.confidence,
                        mismarked=leaf.abs_error > 0,
                        refittable=refittable,
                        recorded_flag=leaf.needs_review,
                    )
                )
    return parts


def unscored_leaves(paths: Sequence[Path]) -> int:
    """How many leaves `parts_from_real` excludes for having no confidence (never scored)."""
    return sum(
        1
        for _, scripts in _runs(paths)
        for script in scripts
        for leaf in script.leaves
        if not _has_confidence(leaf)
    )


def unscored_escalation_leaves(paths: Sequence[Path]) -> int:
    """How many AI-marked leaves `escalation_leaves` excludes for having no confidence."""
    return sum(
        1
        for _, scripts in _runs(paths)
        for script in scripts
        for leaf in script.leaves
        if leaf.marker_source == "ai" and leaf.pre_escalation_confidence is None
    )


@dataclass(frozen=True)
class EscalationLeaf:
    case_key: str  # "<run>:<script>"
    script: str
    confidence: float  # the confidence the escalation decision reads
    wrong: bool  # abs_error > 0 against the reference
    #: The leaf escalated in the source rung, so ``wrong`` is its post-escalation verdict.
    escalated: bool = False


#: Why an `EscalationFit` is not a clean, recall-meeting threshold.
REASON_NO_BASIS = "no_basis"  # no leaf with a wrong mark to recall
REASON_SOURCE_ESCALATED = "source_rung_escalated"  # wrongness is post-escalation
REASON_CAP_BREACHED = "cap_breached_at_zero_escalations"  # base cost alone exceeds the cap
REASON_RECALL_UNREACHABLE = "recall_unreachable_within_cap"  # threshold is the cap's best


@dataclass(frozen=True)
class EscalationFit:
    """The escalation fit; ``threshold`` None means no basis, and ``reason`` says why.

    ``reason`` is None only for a threshold that meets the recall target. ``worst_script``
    is the ``<run>:<script>`` case with the highest cost at the fitted threshold.
    """

    threshold: float | None
    recall: float | None
    escalated: int
    worst_script: str | None
    worst_script_usd: float | None
    met_recall: bool
    reason: str | None = None


def escalation_leaves(paths: Sequence[Path]) -> list[EscalationLeaf]:
    """AI-marked leaves with the confidence their escalation was (or would be) decided on.

    A leaf with no ``pre_escalation_confidence`` (never scored) is left out. ``wrong`` is
    the final mark's error: for a leaf that escalated that is the post-escalation mark,
    which the stored records cannot undo (the correction call keeps no response and the
    escalation event only the confidence), so such a leaf is flagged ``escalated`` and the
    fit refuses it.
    """
    out: list[EscalationLeaf] = []
    for run, scripts in _runs(paths):
        for script in scripts:
            for leaf in script.leaves:
                if leaf.marker_source == "ai" and leaf.pre_escalation_confidence is not None:
                    out.append(
                        EscalationLeaf(
                            case_key=f"{run}:{script.key}",
                            script=script.key,
                            confidence=leaf.pre_escalation_confidence,
                            wrong=leaf.abs_error > 0,
                            escalated=leaf.escalated,
                        )
                    )
    return out


def case_base_usd(paths: Sequence[Path]) -> dict[str, float]:
    """Each ``<run>:<script>`` case's cost without its escalation calls."""
    return {
        f"{run}:{script.key}": script.usd - script.escalation_usd
        for run, scripts in _runs(paths)
        for script in scripts
    }


#: The only model whose escalation calls price the fit: the escalation model of the flip.
ESCALATION_MODEL = "claude-sonnet-5-5"


def escalation_price(records: Sequence[Mapping[str, object]]) -> tuple[float, list[str]]:
    """USD per escalation at Sonnet prices from call records, and notes on how it was got.

    Only escalation records of `ESCALATION_MODEL` count; those of another model are
    excluded with a warning. With none left the `ESCALATION_USD_ESTIMATE` is used, and
    the notes say so.
    """
    notes: list[str] = []
    esc = [r for r in records if r.get("task_tag") == "escalation"]
    other = sorted({str(r.get("model")) for r in esc if r.get("model") != ESCALATION_MODEL})
    if other:
        notes.append(f"WARNING: escalation records from {other} excluded (not {ESCALATION_MODEL})")
    usd = [float(str(r["usd_2027"])) for r in esc if r.get("model") == ESCALATION_MODEL]
    if not usd:
        notes.append(f"no {ESCALATION_MODEL} escalation call to price from: using the estimate")
        return ESCALATION_USD_ESTIMATE, notes
    return sum(usd) / len(usd), notes


def fit_escalation_threshold(
    leaves: Sequence[EscalationLeaf],
    *,
    case_base_usd: Mapping[str, float],
    usd_per_escalation: float,
    cap_usd: float = 0.10,
    recall: float = RECALL_TARGET,
) -> EscalationFit:
    """The escalation threshold: escalate the wrong leaves, keep every case under the cap.

    For each grid threshold t, the leaves with confidence below t escalate. A case (one
    ``<run>:<script>``) then costs its base cost (without escalation) plus its escalations
    at *usd_per_escalation*; the cap applies to the highest-cost case, so a script is
    judged on its worst run, not the mean. Picks the lowest t whose recall of wrong leaves
    reaches *recall* with every case within *cap_usd*; when no such t exists, the highest
    t within the cap (``met_recall`` False, reason `REASON_RECALL_UNREACHABLE`).

    Otherwise ``threshold`` is None with a reason: no leaf is wrong (`REASON_NO_BASIS`),
    any leaf escalated in the source rung (`REASON_SOURCE_ESCALATED`: its wrongness is
    post-escalation, so the fit would undercount what escalation must catch), or even no
    escalation breaches the cap (`REASON_CAP_BREACHED`).

    Borderline retries (``correction_borderline``, which fire on the same threshold) are
    not priced: they run on the cheap correction model, a small fraction of one Sonnet
    escalation, so leaving them out moves no case across the cap by itself.
    """

    def none(reason: str) -> EscalationFit:
        return EscalationFit(None, None, 0, None, None, False, reason)

    wrong = sum(1 for leaf in leaves if leaf.wrong)
    if any(leaf.escalated for leaf in leaves):
        return none(REASON_SOURCE_ESCALATED)
    if wrong == 0:
        return none(REASON_NO_BASIS)

    def cost(t: float) -> tuple[dict[str, float], int, float]:
        escalate = [leaf for leaf in leaves if leaf.confidence < t]
        per_case = {
            c: case_base_usd.get(c, 0.0)
            + usd_per_escalation * sum(1 for leaf in escalate if leaf.case_key == c)
            for c in set(case_base_usd) | {leaf.case_key for leaf in leaves}
        }
        hit = sum(1 for leaf in escalate if leaf.wrong)
        return per_case, len(escalate), hit / wrong

    best_within: tuple[float, dict[str, float], int, float] | None = None
    for t in threshold_grid():
        per_case, count, got = cost(t)
        if max(per_case.values(), default=0.0) > cap_usd + _EPS:
            continue
        best_within = (t, per_case, count, got)
        if got + _EPS >= recall:
            worst = max(per_case, key=lambda c: per_case[c])
            return EscalationFit(t, got, count, worst, per_case[worst], True)
    if best_within is None:
        return none(REASON_CAP_BREACHED)
    t, per_case, count, got = best_within
    worst = max(per_case, key=lambda c: per_case[c])
    return EscalationFit(t, got, count, worst, per_case[worst], False, REASON_RECALL_UNREACHABLE)
