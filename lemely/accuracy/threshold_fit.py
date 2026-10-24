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


def parts_from_real(paths: Sequence[Path]) -> list[Part]:
    """Every scored leaf of a real rung's runs as a `Part`; mismarked means abs_error > 0.

    A leaf with no confidence (dropped, blank or missing: never scored) is left out, not
    read as confidence 0; `unscored_leaves` counts them.
    """
    parts: list[Part] = []
    for path in paths:
        run = path.parent.name
        for script in read_real_results(path):
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
    """How many leaves the fits exclude for having no confidence (never scored)."""
    return sum(
        1
        for path in paths
        for script in read_real_results(path)
        for leaf in script.leaves
        if leaf.confidence is None
    )


@dataclass(frozen=True)
class EscalationLeaf:
    case_key: str  # "<run>:<script>"
    script: str
    confidence: float  # the confidence the escalation decision reads
    wrong: bool  # abs_error > 0 against the reference


@dataclass(frozen=True)
class EscalationFit:
    """The escalation fit; ``threshold`` None means no basis (see `fit_escalation_threshold`)."""

    threshold: float | None
    recall: float | None
    escalated: int
    worst_script: str | None
    worst_script_usd: float | None
    met_recall: bool


def escalation_leaves(paths: Sequence[Path]) -> list[EscalationLeaf]:
    """AI-marked leaves with the confidence their escalation was (or would be) decided on.

    A leaf with no ``pre_escalation_confidence`` (never scored) is left out.
    """
    out: list[EscalationLeaf] = []
    for path in paths:
        run = path.parent.name
        for script in read_real_results(path):
            for leaf in script.leaves:
                if leaf.marker_source == "ai" and leaf.pre_escalation_confidence is not None:
                    out.append(
                        EscalationLeaf(
                            case_key=f"{run}:{script.key}",
                            script=script.key,
                            confidence=leaf.pre_escalation_confidence,
                            wrong=leaf.abs_error > 0,
                        )
                    )
    return out


def fit_escalation_threshold(
    leaves: Sequence[EscalationLeaf],
    *,
    script_base_usd: Mapping[str, float],
    usd_per_escalation: float,
    cap_usd: float = 0.10,
    recall: float = RECALL_TARGET,
) -> EscalationFit:
    """The escalation threshold: escalate the wrong leaves, keep every script under the cap.

    For each grid threshold t, the leaves with confidence below t escalate. A run's
    script then costs its base cost (without escalation) plus its escalations at
    *usd_per_escalation*; scripts are averaged over the runs (case keys). Picks the
    lowest t whose recall of wrong leaves reaches *recall* with every script within
    *cap_usd*; when no such t exists, the highest t within the cap (``met_recall``
    False); None when even no escalation breaches the cap. No leaves, or no wrong leaf
    to recall, is no basis: the all-None fit, never a threshold.
    """
    wrong = sum(1 for leaf in leaves if leaf.wrong)
    if wrong == 0:
        return EscalationFit(None, None, 0, None, None, False)
    runs_per_script: dict[str, set[str]] = {}
    for leaf in leaves:
        runs_per_script.setdefault(leaf.script, set()).add(leaf.case_key)

    def cost(t: float) -> tuple[dict[str, float], int, float | None]:
        escalate = [leaf for leaf in leaves if leaf.confidence < t]
        per_script = {
            s: script_base_usd.get(s, 0.0)
            + usd_per_escalation
            * sum(1 for leaf in escalate if leaf.script == s)
            / max(len(runs_per_script.get(s, ())), 1)
            for s in set(script_base_usd) | set(runs_per_script)
        }
        hit = sum(1 for leaf in escalate if leaf.wrong)
        return per_script, len(escalate), (hit / wrong if wrong else None)

    best_within: tuple[float, dict[str, float], int, float | None] | None = None
    for t in threshold_grid():
        per_script, count, got = cost(t)
        if max(per_script.values(), default=0.0) > cap_usd + _EPS:
            continue
        best_within = (t, per_script, count, got)
        if got is not None and got + _EPS >= recall:
            worst = max(per_script, key=lambda s: per_script[s])
            return EscalationFit(t, got, count, worst, per_script[worst], True)
    if best_within is None:
        return EscalationFit(None, None, 0, None, None, False)
    t, per_script, count, got = best_within
    worst = max(per_script, key=lambda s: per_script[s])
    return EscalationFit(t, got, count, worst, per_script[worst], False)
