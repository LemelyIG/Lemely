"""The per-row evaluation record (spec §3.3).

``EvalRecord`` is the unit every M0/M1 analysis operates on. It reuses the
``StrictModel``/``Split`` scaffolding already defined in
:mod:`lemely.eval.manifest` (landed with #31/M0.7a) rather than redefining
either — see that module's docstring for why the two manifests share it.
``Arm`` is likewise defined in :mod:`lemely.eval.manifest` (not here) and
re-imported below: ``RunManifest`` needs it too (#28), and this module
already depends on ``lemely.eval.manifest`` for ``StrictModel``, so defining
``Arm`` there and importing it here is the direction that avoids a circular
import.
"""

from __future__ import annotations

from typing import Literal

from lemely.eval.manifest import Arm as Arm
from lemely.eval.manifest import StrictModel

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
    maximum_marks: int | None = None
    """The question's tariff (``CorrectedQuestion.maximum_marks``), i.e. marks
    available -- NOT marks earned (that is ``truth_marks``). Used to weight
    :func:`lemely.eval.analyses.paper_grade_confidence` so a wrongly-answered
    high-tariff question still carries its full weight instead of vanishing.
    Defaults to ``None`` (load-bearing: keeps rows written before this field
    existed -- e.g. ``BUILD/accuracy-runs/aa-floor-2026-08-23-a/*.jsonl`` --
    parseable under ``StrictModel``'s ``extra="forbid"``, since a missing key
    with a default is accepted even though an unknown key is rejected). Is
    ``None`` for the "excluded" outcome (no ``CorrectedQuestion`` was ever
    produced for that leaf, so no tariff is known)."""
