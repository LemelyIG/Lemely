"""Pure accept/reject gate for cost-cutting levers. No I/O."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

BIG_TIER_SAVING = 0.30
BIG_TIER_ALLOWED_FRACTION = 0.02
BIG_TIER_TOLERANCE = 1e-9  # 1 - 0.07/0.1 is 0.29999999999999993, not 0.3
LATENCY_FACTOR = 2.0


@dataclass(frozen=True)
class RunSummary:
    usd_per_script_mean: float  # at 2027 rates
    latency_p95_ms: float  # per script
    mismarked_parts: frozenset[str]  # "<case_key>/<question_id>" with predicted != truth
    scored_parts: int
    id_match_rate: float
    validity_rate: float  # structured outputs parsed / attempted
    incomplete: tuple[str, ...]  # case keys with a failed call or missing leaf


@dataclass(frozen=True)
class Verdict:
    passed: bool
    tier: Literal["small", "big"]
    saving: float  # 1 - candidate/baseline usd
    extra_mismarks: int
    allowed_extra: int
    reasons: tuple[str, ...]  # every failed check, human-readable


def aa_floor(a: RunSummary, b: RunSummary) -> int:
    """Churn between two runs of the same config: the symmetric difference."""
    return len(a.mismarked_parts ^ b.mismarked_parts)


def judge(
    baseline: RunSummary,
    candidate: RunSummary,
    *,
    aa_floor: int,
    original_latency_p95_ms: float,
) -> Verdict:
    if aa_floor < 0:
        raise ValueError(f"aa_floor must be non-negative, got {aa_floor}")
    reasons: list[str] = []

    if baseline.usd_per_script_mean == 0:
        saving = 0.0
        reasons.append("baseline cost is zero")
    else:
        saving = 1 - candidate.usd_per_script_mean / baseline.usd_per_script_mean
    tier: Literal["small", "big"] = (
        "big" if saving >= BIG_TIER_SAVING - BIG_TIER_TOLERANCE else "small"
    )

    extra = len(candidate.mismarked_parts - baseline.mismarked_parts)
    if tier == "big":
        allowed = max(aa_floor, math.ceil(BIG_TIER_ALLOWED_FRACTION * candidate.scored_parts))
    else:
        allowed = aa_floor
    if extra > allowed:
        reasons.append(f"{extra} newly mismarked parts exceed the allowed {allowed} ({tier} tier)")
    if candidate.id_match_rate < baseline.id_match_rate:
        reasons.append(
            f"id match rate fell from {baseline.id_match_rate} to {candidate.id_match_rate}"
        )
    if candidate.validity_rate < baseline.validity_rate:
        reasons.append(
            f"validity rate fell from {baseline.validity_rate} to {candidate.validity_rate}"
        )
    if candidate.latency_p95_ms > LATENCY_FACTOR * original_latency_p95_ms:
        reasons.append(
            f"latency p95 {candidate.latency_p95_ms}ms exceeds "
            f"{LATENCY_FACTOR}x original {original_latency_p95_ms}ms"
        )
    if candidate.incomplete:
        reasons.append("incomplete cases: " + ", ".join(candidate.incomplete))
    if candidate.scored_parts != baseline.scored_parts:
        reasons.append(
            f"scored parts changed from {baseline.scored_parts} to "
            f"{candidate.scored_parts} (narrowed screen)"
        )

    return Verdict(
        passed=not reasons,
        tier=tier,
        saving=saving,
        extra_mismarks=extra,
        allowed_extra=allowed,
        reasons=tuple(reasons),
    )
