"""Tests for ``scripts/fit_review_threshold.py``: a $0 refit of a screen's results."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts import fit_review_threshold as fit


def _q(
    case: str,
    qid: str,
    conf: float,
    *,
    predicted: int = 1,
    truth: int = 1,
    review: bool | None = None,
    reason: str | None = None,
    source: str = "ai",
    scored: bool = True,
) -> dict[str, Any]:
    if review is None:
        review = conf < 0.90
        if review and reason is None:
            reason = f"confidence {conf:.2f} below review threshold 0.90"
    return {
        "case_key": case,
        "question_id": qid,
        "confidence_score": conf,
        "marker_source": source,
        "needs_teacher_review": review,
        "review_reason": reason,
        "predicted_marks": predicted,
        "truth_marks": truth,
        "scored": scored,
    }


def _write(tmp_path: Path, rows: list[dict[str, Any]], records: list[dict[str, Any]]) -> Path:
    results = tmp_path / "results.json"
    results.write_text(json.dumps({"question_results": rows}), encoding="utf-8")
    (tmp_path / "records.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in records), encoding="utf-8"
    )
    return results


def test_rate_recall_precision_follow_the_threshold(tmp_path: Path) -> None:
    rows = [
        _q("a", "1", 0.85, predicted=0, truth=1),  # mismark, flagged below 0.86
        _q("a", "2", 0.85),
        _q("a", "3", 0.95),
        _q("b", "1", 0.95, predicted=0, truth=1),  # mismark never flagged by confidence
    ]
    parts = fit.load_parts(_write(tmp_path, rows, []))
    at_86 = fit.evaluate(parts, 0.86)
    assert at_86.flagged == 2
    assert at_86.review_rate == pytest.approx(0.5)
    assert at_86.flag_recall == pytest.approx(0.5)
    assert at_86.precision == pytest.approx(0.5)
    at_85 = fit.evaluate(parts, 0.85)
    assert at_85.flagged == 0
    assert at_85.flag_recall == 0.0
    assert at_85.precision is None


def test_structural_deterministic_and_escalated_flags_do_not_move(tmp_path: Path) -> None:
    rows = [
        # structural: flagged whatever the threshold
        _q("a", "1", 0.99, review=True, reason="unverified accuracy mark(s): p1"),
        # deterministic MCQ: its threshold is not the correction model's
        _q("a", "2", 0.80, source="deterministic"),
        # escalated: the final mark came from the escalation model (threshold unchanged)
        _q("a", "3", 0.85),
        _q("a", "4", 0.85),
    ]
    records = [{"case_key": "a", "question_id": "3", "task_tag": "escalation"}]
    parts = fit.load_parts(_write(tmp_path, rows, records))
    assert fit.evaluate(parts, 0.50).flagged == 3  # 1, 2, 3 kept; 4 refitted away
    assert fit.evaluate(parts, 0.99).flagged == 4


def test_unscored_parts_are_excluded(tmp_path: Path) -> None:
    rows = [_q("a", "1", 0.85), _q("a", "2", 0.85, scored=False)]
    parts = fit.load_parts(_write(tmp_path, rows, []))
    assert len(parts) == 1


def test_recommend_picks_the_highest_threshold_within_target(tmp_path: Path) -> None:
    rows = [_q("a", str(i), 0.95) for i in range(18)] + [
        _q("a", "x", 0.85),
        _q("a", "y", 0.88),
    ]
    parts = fit.load_parts(_write(tmp_path, rows, []))
    # 2/20 = 10% is within target at 0.89..0.95; 0.96 adds all 18 others
    assert fit.recommend(parts, target=0.10) == pytest.approx(0.95)
    assert fit.recommend(parts, target=0.05) == pytest.approx(0.88)
    assert fit.recommend(parts, target=0.0) == pytest.approx(0.85)


def test_recommend_returns_none_when_no_threshold_meets_target(tmp_path: Path) -> None:
    rows = [_q("a", "1", 0.99, review=True, reason="marker returned 3 marks")]
    parts = fit.load_parts(_write(tmp_path, rows, []))
    assert fit.recommend(parts, target=0.10) is None


def test_leave_one_case_out_refits_without_each_case(tmp_path: Path) -> None:
    rows = [_q("a", str(i), 0.95) for i in range(9)] + [_q("b", "1", 0.85)]
    parts = fit.load_parts(_write(tmp_path, rows, []))
    loo = fit.leave_one_case_out(parts, target=0.10)
    assert loo == {"a": 0.85, "b": 0.95}


def test_grid_is_050_to_099_in_hundredths() -> None:
    grid = fit.threshold_grid()
    assert grid[0] == pytest.approx(0.50)
    assert grid[-1] == pytest.approx(0.99)
    assert len(grid) == 50


def test_main_prints_table_recommendation_and_loo(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rows = [_q("a", str(i), 0.95) for i in range(9)] + [_q("b", "1", 0.85)]
    assert fit.main([str(_write(tmp_path, rows, []))]) == 0
    out = capsys.readouterr().out
    assert "| 0.85 |" in out
    assert "recommended threshold: 0.95" in out
    assert "leave-one-case-out" in out
