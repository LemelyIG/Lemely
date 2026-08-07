"""Real past-paper accuracy fixtures (INBOX-2026-08-07-ACC).

Two parts, per MISSION §5's testing-at-the-right-level rule:

1. Hermetic unit tests over :mod:`lemely.accuracy.real_papers` — pure
   functions, no I/O, no network, always run.
2. A live-gated end-to-end test per directive item 1: runs each real fixture
   PDF through the actual ingest → OCR → mark → grade path (never a mocked
   stub), via ``scripts/run_real_paper_accuracy.py`` (which itself replays a
   cached artefact when one already exists, so a re-run after the first live
   pass costs nothing). Gated on ``LEMELY_LIVE_ACCURACY=1`` AND a resolvable
   Gemini key, joining the existing live-only skip pattern in
   ``test_auth_live.py`` / ``test_seat_invite_live.py`` / ``test_storage_live.py``
   so this never fires on a bare ``pytest``.

Paper 22 and paper 41 are two separate test cases with separately asserted
numbers — never averaged (directive item 5).

Tolerance is ±10% of each paper's own maximum mark (see
``lemely/accuracy/real_papers.py::tolerance_marks`` for the justification).
This number is fixed by policy; if a paper misses it the test MUST stay red —
no loosening, no skip, no xfail (directive item 8).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from lemely.accuracy.real_papers import (
    QuestionRow,
    RealPaperCase,
    absolute_error,
    confidence_distribution,
    mean_absolute_error,
    review_flagged_marks,
    signed_error,
    tolerance_marks,
    within_tolerance,
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.run_real_paper_accuracy import FIXTURES, run_or_replay_fixture

# ---------------------------------------------------------------------------
# Hermetic unit tests — always run
# ---------------------------------------------------------------------------


def _row(
    question_id: str = "q1",
    awarded: int = 2,
    maximum: int = 2,
    band: str = "high",
    score: float = 0.95,
    review: bool = False,
) -> QuestionRow:
    return QuestionRow(
        question_id=question_id,
        awarded_marks=awarded,
        maximum_marks=maximum,
        confidence_band=band,
        confidence_score=score,
        needs_teacher_review=review,
    )


def _case(
    predicted: int, truth: int, max_total: int = 40, rows: tuple[QuestionRow, ...] = ()
) -> RealPaperCase:
    return RealPaperCase(
        fixture_id="test-case",
        predicted_total=predicted,
        ground_truth_total=truth,
        max_total=max_total,
        marking_path="test",
        rows=rows,
    )


def test_signed_error_positive_when_over_awarded() -> None:
    assert signed_error(_case(38, 34)) == 4


def test_signed_error_negative_when_under_awarded() -> None:
    assert signed_error(_case(30, 34)) == -4


def test_signed_error_zero_on_exact_match() -> None:
    assert signed_error(_case(34, 34)) == 0


def test_absolute_error_is_magnitude_regardless_of_direction() -> None:
    assert absolute_error(_case(38, 34)) == 4
    assert absolute_error(_case(30, 34)) == 4


def test_tolerance_marks_is_ten_percent_of_max_by_default() -> None:
    assert tolerance_marks(40) == pytest.approx(4.0)
    assert tolerance_marks(80) == pytest.approx(8.0)


def test_tolerance_marks_respects_custom_percentage() -> None:
    assert tolerance_marks(40, tolerance_pct=0.05) == pytest.approx(2.0)


def test_within_tolerance_true_at_exact_boundary() -> None:
    # 40-mark paper, tolerance = 4. An error of exactly 4 must still pass
    # ("within" is inclusive of the boundary).
    assert within_tolerance(_case(30, 34, max_total=40)) is True


def test_within_tolerance_false_just_outside_boundary() -> None:
    assert within_tolerance(_case(29, 34, max_total=40)) is False


def test_within_tolerance_uses_case_own_max_not_a_shared_constant() -> None:
    # Same absolute error (8), different max totals -> different verdicts.
    assert within_tolerance(_case(58, 66, max_total=80)) is True  # exactly 10%
    assert within_tolerance(_case(58, 66, max_total=40)) is False  # 8 >> 10% of 40


def test_mean_absolute_error_single_case_equals_its_own_absolute_error() -> None:
    case = _case(38, 34)
    assert mean_absolute_error([case]) == pytest.approx(4.0)


def test_mean_absolute_error_multiple_cases_averages() -> None:
    cases = [_case(38, 34), _case(30, 34)]  # errors 4 and 4
    assert mean_absolute_error(cases) == pytest.approx(4.0)
    cases2 = [_case(36, 34), _case(24, 34)]  # errors 2 and 10
    assert mean_absolute_error(cases2) == pytest.approx(6.0)


def test_mean_absolute_error_empty_list_raises() -> None:
    with pytest.raises(ValueError, match="at least one case"):
        mean_absolute_error([])


def test_confidence_distribution_weighted_by_marks_not_question_count() -> None:
    rows = (
        _row("q1", maximum=1, band="high"),
        _row("q2", maximum=8, band="low"),
        _row("q3", maximum=1, band="high"),
    )
    dist = confidence_distribution(rows)
    assert dist == {"high": 2, "low": 8}


def test_confidence_distribution_empty_rows() -> None:
    assert confidence_distribution(()) == {}


def test_review_flagged_marks_sums_only_flagged_questions() -> None:
    rows = (
        _row("q1", maximum=3, review=True),
        _row("q2", maximum=5, review=False),
        _row("q3", maximum=2, review=True),
    )
    assert review_flagged_marks(rows) == 5


def test_review_flagged_marks_zero_when_none_flagged() -> None:
    rows = (_row("q1", maximum=3, review=False),)
    assert review_flagged_marks(rows) == 0


def test_fixtures_are_declared_as_two_separate_cases() -> None:
    # Directive item 5: never averaged into one number. Structurally, the
    # runner's FIXTURES list must keep paper 22 and paper 41 as distinct
    # entries with their own ground truth and max — this pins that shape.
    ids = [f["fixture_id"] for f in FIXTURES]
    assert ids == ["0625_s23_qp_22", "0625_w24_qp_41"]
    by_id = {f["fixture_id"]: f for f in FIXTURES}
    assert by_id["0625_s23_qp_22"]["ground_truth_total"] == 34
    assert by_id["0625_s23_qp_22"]["max_total"] == 40
    assert by_id["0625_w24_qp_41"]["ground_truth_total"] == 66
    assert by_id["0625_w24_qp_41"]["max_total"] == 80


# ---------------------------------------------------------------------------
# Live-gated end-to-end tests
# ---------------------------------------------------------------------------


def _live_gemini_key_present() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("LEMELY_GEMINI_API_KEY"))


live_accuracy = pytest.mark.skipif(
    os.environ.get("LEMELY_LIVE_ACCURACY") != "1" or not _live_gemini_key_present(),
    reason=(
        "Set LEMELY_LIVE_ACCURACY=1 and a Gemini key (GEMINI_API_KEY) to run the "
        "live, billed real-past-paper accuracy test. Skipped by default so this "
        "never fires on a bare `pytest`."
    ),
)


@live_accuracy
def test_real_paper_22_mcq_total_within_tolerance() -> None:
    """Paper 22 (0625_s23_qp_22): MCQ, ground truth 34/40. Deterministic marking."""
    spec = next(f for f in FIXTURES if f["fixture_id"] == "0625_s23_qp_22")
    result = run_or_replay_fixture(spec)
    assert result["predicted_total"] is not None
    assert result["within_tolerance"], (
        f"Paper 22 total {result['predicted_total']}/{result['max_total']} misses the "
        f"±{result['tolerance_marks']}-mark tolerance around ground truth "
        f"{result['ground_truth_total']}/{result['max_total']} "
        f"(signed_error={result['signed_error']}). Per directive item 8: do not loosen "
        "this tolerance or skip this test — record the gap in BUILD/DECISIONS.md instead."
    )


@live_accuracy
def test_real_paper_41_theory_total_within_tolerance() -> None:
    """Paper 41 (0625_w24_qp_41): theory w/ method marks, ground truth 66/80. AI marking."""
    spec = next(f for f in FIXTURES if f["fixture_id"] == "0625_w24_qp_41")
    result = run_or_replay_fixture(spec)
    assert result["predicted_total"] is not None
    assert result["within_tolerance"], (
        f"Paper 41 total {result['predicted_total']}/{result['max_total']} misses the "
        f"±{result['tolerance_marks']}-mark tolerance around ground truth "
        f"{result['ground_truth_total']}/{result['max_total']} "
        f"(signed_error={result['signed_error']}). Per directive item 8: do not loosen "
        "this tolerance or skip this test — record the gap in BUILD/DECISIONS.md instead."
    )
