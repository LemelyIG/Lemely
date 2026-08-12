"""Pure measurement layer for the real-past-paper accuracy fixtures (INBOX-2026-08-07-ACC).

No I/O and no Gemini calls live here — this module only turns a completed run's
per-question rows plus the fixture's known *total* ground truth into the numbers
the directive asks for: absolute error, signed error direction, MAE, and the
confidence distribution across marks.

Ground truth for these fixtures is the paper *total only* (see
``tests/fixtures/real-papers/`` naming: ``SubjectCode_SeasonYear_qp_PaperVariant-
(AchievedMark..MaxMark)``). Per-question ground truth does not exist and must
never be fabricated or back-derived from the pipeline's own output (directive
item 2 — that would be invented precision, UI spec §1.4). Consequently this
module has no notion of "is this question right" — only totals and confidence.

Fully unit-testable without a network: every function here takes plain data in
and returns plain data out.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QuestionRow:
    """One graded question, as it came out of a real ``AccuracyReport.correction``.

    ``confidence_band`` is a plain string (``"high" | "medium" | "low"``) rather
    than importing ``ConfidenceBand`` here, keeping this module's only dependency
    the standard library — it stays trivially unit-testable and mypy-strict clean
    without pulling in the pydantic schema graph.
    """

    question_id: str
    awarded_marks: int
    maximum_marks: int
    confidence_band: str
    confidence_score: float
    needs_teacher_review: bool


@dataclass(frozen=True)
class RealPaperCase:
    """One fixture's measured run: its predicted total against the known truth."""

    fixture_id: str
    predicted_total: int
    ground_truth_total: int
    max_total: int
    marking_path: str  # e.g. "mcq (deterministic)" or "theory (AI method-mark)"
    rows: tuple[QuestionRow, ...]


def signed_error(case: RealPaperCase) -> int:
    """Predicted minus actual. Positive = pipeline over-awarded; negative = under-awarded."""
    return case.predicted_total - case.ground_truth_total


def absolute_error(case: RealPaperCase) -> int:
    """Unsigned magnitude of :func:`signed_error`."""
    return abs(signed_error(case))


def tolerance_marks(max_total: int, tolerance_pct: float = 0.10) -> float:
    """Absolute-mark tolerance for a paper of ``max_total``, at ``tolerance_pct`` of it.

    Fixed at 10% of the paper maximum (directive: ±4 marks on the 40-mark paper 22,
    ±8 marks on the 80-mark paper 41). Adjacent CAIE grade boundaries on these
    papers sit roughly 6-10% of the maximum apart, so a total error inside this
    band risks at most one grade band — the smallest error size that still means
    something to a student. This number is fixed by policy and must not be tuned
    to whatever a given run produces.
    """
    return max_total * tolerance_pct


def within_tolerance(case: RealPaperCase, tolerance_pct: float = 0.10) -> bool:
    """True when ``case``'s total lands within ``tolerance_pct`` of its own max."""
    return absolute_error(case) <= tolerance_marks(case.max_total, tolerance_pct)


def mean_absolute_error(cases: list[RealPaperCase]) -> float:
    """MAE over the given cases.

    The two real-paper fixtures are never averaged together for reporting
    (directive item 5) — callers must invoke this per-paper, with a
    single-element list, and report each paper's MAE separately. This function
    stays general (it is also exercised with synthetic multi-case lists in unit
    tests) rather than hardcoding "exactly one case".
    """
    if not cases:
        raise ValueError("mean_absolute_error requires at least one case")
    return sum(absolute_error(c) for c in cases) / len(cases)


def confidence_distribution(rows: tuple[QuestionRow, ...] | list[QuestionRow]) -> dict[str, int]:
    """Total *marks* (not question count) grouped by confidence band.

    "Across marks" (directive item 3) means weighted by how many marks each
    question is worth, not a simple per-question tally — a 1-mark MCQ question
    marked HIGH and an 8-mark method-mark question marked LOW should not look
    like the same amount of "confidence" in the distribution.
    """
    dist: dict[str, int] = {}
    for row in rows:
        dist[row.confidence_band] = dist.get(row.confidence_band, 0) + row.maximum_marks
    return dist


def review_flagged_marks(rows: tuple[QuestionRow, ...] | list[QuestionRow]) -> int:
    """Total marks belonging to questions flagged ``needs_teacher_review``."""
    return sum(row.maximum_marks for row in rows if row.needs_teacher_review)
