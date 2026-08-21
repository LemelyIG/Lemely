"""The per-row evaluation record (spec §3.3).

``EvalRecord`` is the unit every M0/M1 analysis operates on. It reuses the
``StrictModel``/``Split`` scaffolding already defined in
:mod:`lemely.eval.manifest` (landed with #31/M0.7a) rather than redefining
either — see that module's docstring for why the two manifests share it.
"""

from __future__ import annotations

from typing import Literal

from lemely.eval.manifest import StrictModel

Arm = Literal["extract+mark", "oracle+mark"]
ParsePath = Literal["det", "gemini"]
Outcome = Literal["correct", "over", "under", "abstain", "unmatched", "excluded"]
IdMatch = Literal["exact", "fuzzy", "unmatched"]


class EvalRecord(StrictModel):
    """One scored (or excluded) leaf from one evaluation run (spec §3.3).

    ``mark_point_id`` is ``None`` for a question-level row and set for a
    sub-question row; every analysis in :mod:`lemely.eval.analyses` filters
    to question-level rows before aggregating unless it is explicitly a
    point-level analysis.
    """

    run_id: str
    arm: Arm
    paper_id: str
    fixture_variant: str | None
    question_id: str
    mark_point_id: str | None
    parse_path: ParsePath
    predicted_marks: int | None
    truth_marks: int | None
    outcome: Outcome
    extraction_conf: float | None
    marker_conf: float | None
    id_match: IdMatch
    triggers: list[str]
