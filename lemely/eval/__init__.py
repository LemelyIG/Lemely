"""Evaluation record model and analyses.

See spec §3 (`docs/superpowers/specs/2026-08-17-accuracy-programme-design.md`).
Label *data* does not live in this package (spec §3.1) — it lives at
repository-root ``eval/labels/…`` so labels are never importable and the
labeller process cannot reach pipeline code (spec §6).
"""

from __future__ import annotations

from lemely.eval.analyses import (
    MCNEMAR_IMPROVEMENT_N_FLOOR,
    ablation_2x2,
    exclusion_funnel,
    mcnemar,
    mcnemar_improvement_p_value,
    paired_proportion_min_n,
    review_rate,
    risk_coverage,
    wilson,
)
from lemely.eval.manifest import LabelManifest, RunManifest
from lemely.eval.records import EvalRecord

__all__ = [
    "MCNEMAR_IMPROVEMENT_N_FLOOR",
    "EvalRecord",
    "LabelManifest",
    "RunManifest",
    "ablation_2x2",
    "exclusion_funnel",
    "mcnemar",
    "mcnemar_improvement_p_value",
    "paired_proportion_min_n",
    "review_rate",
    "risk_coverage",
    "wilson",
]
