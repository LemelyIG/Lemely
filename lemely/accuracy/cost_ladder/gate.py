"""Pure accept/reject gates for the cost ladder: cost levers, accuracy levers, the flip. No I/O."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Literal

BIG_TIER_SAVING = 0.30
BIG_TIER_ALLOWED_FRACTION = 0.02
BIG_TIER_TOLERANCE = 1e-9  # 1 - 0.07/0.1 is 0.29999999999999993, not 0.3
LATENCY_FACTOR = 2.0
#: Spec 2026-10-24 global constraint: every real script, not the mean.
REAL_SCRIPT_CAP_USD = 0.10
#: judge_accuracy_lever: the review rate may rise this much unless abs_error fell.
ACCURACY_REVIEW_RISE = 0.05
#: judge_flip: absolute cap on the candidate's review rate. Claude at review
#: threshold 0.72 flags ~21.7% of leaves and catches 65% of wrong leaves vs
#: Gemini's 28% (user decision 2026-10-26).
FLIP_REVIEW_CAP = 0.22
_EPS = 1e-9


@dataclass(frozen=True)
class RunSummary:
    usd_per_script_mean: float  # at 2027 rates
    latency_p95_ms: float  # per script
    mismarked_parts: frozenset[str]  # "<case_key>/<question_id>" with predicted != truth
    scored_parts: int
    id_match_rate: float
    validity_rate: float  # structured outputs parsed / attempted
    incomplete: tuple[str, ...]  # case keys with a failed call or missing leaf
    # Real split (sub-project C). Defaults: a dev-only run, as before.
    real_scripts: tuple[str, ...] = ()
    real_abs_error: float = 0.0  # mean over the runs of sum |mark - reference|
    real_abs_error_by_run: tuple[float, ...] = ()
    real_exact_rate: float | None = None
    real_within1_rate: float | None = None
    real_review_rate: float | None = None
    real_binding_passes: float = 0.0  # mean over the runs of scripts with verdict "pass"
    real_usd_mean: float = 0.0  # 2027 USD, mean over scripts and runs
    real_usd_by_script: tuple[tuple[str, float | None], ...] = ()  # mean over the runs
    real_usd_max_by_script: tuple[tuple[str, float | None], ...] = ()  # highest run: the cap check
    real_latency_by_script: tuple[tuple[str, float | None], ...] = ()  # wall clock ms, mean
    real_escalation_rate: float | None = None  # escalated leaves / leaves, mean
    real_escalation_rate_max_script: float | None = None
    real_escalation_usd_by_script: tuple[tuple[str, float | None], ...] = ()
    real_escalation_triggers: tuple[tuple[str, int], ...] = ()
    real_incomplete: tuple[str, ...] = ()


@dataclass(frozen=True)
class Verdict:
    passed: bool
    tier: Literal["small", "big"]
    saving: float  # 1 - candidate/baseline usd
    extra_mismarks: int
    allowed_extra: int
    reasons: tuple[str, ...]  # every failed check, human-readable
    notes: tuple[str, ...] = ()  # reported beside the checks, never judged


def aa_floor(a: RunSummary, b: RunSummary) -> int:
    """Churn between two runs of the same config: the symmetric difference."""
    return len(a.mismarked_parts ^ b.mismarked_parts)


def real_aa_floor(a: RunSummary, b: RunSummary) -> float:
    """Real-split noise: the abs_error difference between two identical base runs."""
    return abs(a.real_abs_error - b.real_abs_error)


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


def _saving(base_usd: float, candidate_usd: float) -> float:
    return 0.0 if base_usd == 0 else 1 - candidate_usd / base_usd


def _over_cap(candidate: RunSummary) -> list[str]:
    """Over-cap scripts, and scripts with no cost figure: a missing one is never under the cap."""
    return [
        f"{key} has no cost figure (no result)"
        if usd is None
        else f"{key} ${usd:.4f} exceeds ${REAL_SCRIPT_CAP_USD:.2f} per script"
        for key, usd in candidate.real_usd_max_by_script
        if usd is None or usd > REAL_SCRIPT_CAP_USD + _EPS
    ]


def _missing_real(baseline: RunSummary, candidate: RunSummary, other: str) -> list[str]:
    return [
        f"{who} has no real-split results"
        for who, summary in ((other, baseline), ("candidate", candidate))
        if not summary.real_scripts
    ]


def _pct(rate: float | None) -> str:
    return "-" if rate is None else f"{rate * 100:.1f}%"


def escalation_notes(c: RunSummary) -> tuple[str, ...]:
    """Escalation rate, dollars and triggers of a real-split run (spec "Escalation rate")."""
    if c.real_escalation_rate is None:
        return ()
    notes = [
        f"escalation rate {_pct(c.real_escalation_rate)} "
        f"(max script {_pct(c.real_escalation_rate_max_script)})"
    ]
    usd = dict(c.real_usd_by_script)
    for key, esc in c.real_escalation_usd_by_script:
        if esc is None:
            notes.append(f"{key} escalation - (no result)")
            continue
        total = usd.get(key)
        share = f"{esc / total * 100:.1f}%" if total else "-"
        notes.append(f"{key} escalation ${esc:.4f} ({share} of script)")
    if c.real_escalation_triggers:
        notes.append(
            "triggers " + ", ".join(f"{name}={n}" for name, n in c.real_escalation_triggers)
        )
    return tuple(notes)


def _incomplete(candidate: RunSummary) -> list[str]:
    reasons = []
    if candidate.incomplete:
        reasons.append("incomplete cases: " + ", ".join(candidate.incomplete))
    if candidate.real_incomplete:
        reasons.append("incomplete real cases: " + ", ".join(candidate.real_incomplete))
    return reasons


def judge_cost_lever(
    baseline: RunSummary,
    candidate: RunSummary,
    *,
    aa_floor: int,
    real_aa_floor: float,
    original_latency_p95_ms: float,
) -> Verdict:
    """`judge`, plus the real split when either side has it.

    A cost lever may not raise real abs_error by more than the real A/A floor, may
    not raise the mean real cost, and must keep every real script at or below the
    cap. Dev-only summaries are judged by `judge` alone.
    """
    if baseline.real_scripts and baseline.scored_parts == 0 and candidate.scored_parts == 0:
        # A real-only rung: its dev split is empty, and `judge` would fail it on a zero cost.
        verdict = Verdict(
            passed=True,
            tier="small",
            saving=0.0,
            extra_mismarks=0,
            allowed_extra=aa_floor,
            reasons=(),
        )
    else:
        verdict = judge(
            baseline, candidate, aa_floor=aa_floor, original_latency_p95_ms=original_latency_p95_ms
        )
    if not baseline.real_scripts and not candidate.real_scripts:
        return verdict
    reasons = list(verdict.reasons) + _missing_real(baseline, candidate, "baseline")
    reasons += [r for r in _incomplete(candidate) if r not in reasons]
    if baseline.real_scripts and candidate.real_scripts:
        rise = candidate.real_abs_error - baseline.real_abs_error
        if rise > real_aa_floor + _EPS:
            reasons.append(
                f"real abs error rose by {rise:.2f} marks, above the A/A floor {real_aa_floor:.2f}"
            )
        if candidate.real_usd_mean > baseline.real_usd_mean + _EPS:
            reasons.append(
                f"real cost rose from ${baseline.real_usd_mean:.4f} to "
                f"${candidate.real_usd_mean:.4f} per script"
            )
        if candidate.real_scripts != baseline.real_scripts:
            reasons.append("real scripts differ from the baseline's")
    reasons += _over_cap(candidate)
    notes = (
        f"real saving {_saving(baseline.real_usd_mean, candidate.real_usd_mean) * 100:.1f}%",
        *escalation_notes(candidate),
    )
    return replace(verdict, passed=not reasons, reasons=tuple(reasons), notes=notes)


def judge_accuracy_lever(
    baseline: RunSummary,
    candidate: RunSummary,
    *,
    aa_floor: int,
    real_aa_floor: float,
) -> Verdict:
    """A lever that adds cost or aims at accuracy (spec P1, judge 2).

    Passes when real abs_error falls by at least the real A/A floor, synthetic extra
    mismarks stay within the dev floor, every real script is at most the cap, and the
    review rate rises by no more than 5 points unless abs_error fell.
    """
    if aa_floor < 0 or real_aa_floor < 0:
        raise ValueError(f"floors must be non-negative, got {aa_floor} and {real_aa_floor}")
    reasons = _missing_real(baseline, candidate, "baseline")
    fall = baseline.real_abs_error - candidate.real_abs_error
    if not reasons:
        if fall <= _EPS:
            reasons.append(
                f"real abs error did not fall (changed by {-fall + 0.0:+.2f} marks); "
                "a lever must reduce it"
            )
        elif fall + _EPS < real_aa_floor:
            reasons.append(
                f"real abs error fell by {fall:.2f} marks, less than the A/A floor "
                f"{real_aa_floor:.2f}"
            )
    extra = len(candidate.mismarked_parts - baseline.mismarked_parts)
    if extra > aa_floor:
        reasons.append(f"{extra} newly mismarked synthetic parts exceed the A/A floor {aa_floor}")
    if candidate.scored_parts != baseline.scored_parts:
        reasons.append(
            f"scored parts changed from {baseline.scored_parts} to "
            f"{candidate.scored_parts} (narrowed screen)"
        )
    reasons += _over_cap(candidate)
    if baseline.real_scripts and candidate.real_scripts:
        if baseline.real_review_rate is None:
            reasons.append("baseline has no review rate")
        if candidate.real_review_rate is None:
            reasons.append("candidate has no review rate")
        if baseline.real_review_rate is not None and candidate.real_review_rate is not None:
            rise = candidate.real_review_rate - baseline.real_review_rate
            if rise > ACCURACY_REVIEW_RISE + _EPS and not fall > _EPS:
                reasons.append(
                    f"review rate rose {rise * 100:.1f} points (more than "
                    f"{ACCURACY_REVIEW_RISE * 100:.0f}) while real abs error did not fall"
                )
    reasons += _incomplete(candidate)
    return Verdict(
        passed=not reasons,
        tier="small",
        saving=_saving(baseline.real_usd_mean, candidate.real_usd_mean),
        extra_mismarks=extra,
        allowed_extra=aa_floor,
        reasons=tuple(reasons),
        notes=escalation_notes(candidate),
    )


def judge_flip(gemini: RunSummary, candidate: RunSummary, *, aa_floor: int) -> Verdict:
    """The stacked Claude configuration against a Gemini rung (spec P1, judge 3)."""
    if aa_floor < 0:
        raise ValueError(f"aa_floor must be non-negative, got {aa_floor}")
    reasons = _missing_real(gemini, candidate, "Gemini rung")
    if not reasons:
        if candidate.real_abs_error > gemini.real_abs_error + _EPS:
            reasons.append(
                f"real abs error {candidate.real_abs_error:.2f} is above Gemini's "
                f"{gemini.real_abs_error:.2f}"
            )
        if candidate.real_scripts != gemini.real_scripts:
            reasons.append("real scripts differ from Gemini's")
        if candidate.real_binding_passes + _EPS < gemini.real_binding_passes:
            reasons.append(
                f"binding passes {candidate.real_binding_passes:.1f} are below Gemini's "
                f"{gemini.real_binding_passes:.1f}"
            )
        cand_rate = candidate.real_review_rate
        gem_rate = gemini.real_review_rate
        if gem_rate is None:
            reasons.append("Gemini rung has no review rate")
        if cand_rate is None:
            reasons.append("candidate has no review rate")
        if cand_rate is not None and gem_rate is not None and cand_rate > FLIP_REVIEW_CAP + _EPS:
            reasons.append(
                f"review rate {_pct(cand_rate)} is above the {FLIP_REVIEW_CAP * 100:.0f}% cap "
                f"(Gemini {_pct(gem_rate)})"
            )
    if candidate.scored_parts != gemini.scored_parts:
        reasons.append(
            f"scored parts changed from {gemini.scored_parts} to "
            f"{candidate.scored_parts} (narrowed screen)"
        )
    extra = len(candidate.mismarked_parts - gemini.mismarked_parts)
    if extra > aa_floor:
        reasons.append(
            f"{extra} synthetic parts mismarked against Gemini's set exceed the A/A floor "
            f"{aa_floor}"
        )
    reasons += _over_cap(candidate)
    reasons += _incomplete(candidate)
    notes = (
        f"real abs error {candidate.real_abs_error:.2f} vs Gemini {gemini.real_abs_error:.2f}",
        f"review rate {_pct(candidate.real_review_rate)} vs Gemini {_pct(gemini.real_review_rate)}",
        f"binding passes {candidate.real_binding_passes:.1f} vs Gemini "
        f"{gemini.real_binding_passes:.1f}",
        *escalation_notes(candidate),
    )
    return Verdict(
        passed=not reasons,
        tier="small",
        saving=_saving(gemini.real_usd_mean, candidate.real_usd_mean),
        extra_mismarks=extra,
        allowed_extra=aa_floor,
        reasons=tuple(reasons),
        notes=notes,
    )


def judge_record(baseline: RunSummary, candidate: RunSummary) -> Verdict:
    """A rung recorded, not judged (the fitted thresholds): it passes unless incomplete."""
    reasons = _incomplete(candidate)
    return Verdict(
        passed=not reasons,
        tier="small",
        saving=_saving(baseline.real_usd_mean, candidate.real_usd_mean),
        extra_mismarks=len(candidate.mismarked_parts - baseline.mismarked_parts),
        allowed_extra=0,
        reasons=tuple(reasons),
        notes=("recorded, not judged", *escalation_notes(candidate)),
    )
