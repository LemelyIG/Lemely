"""Review rate in the cost ladder: ``summary.json`` and the LADDER.md column.

Reporting only: the gate (``gate.judge``) and ``RunSummary`` do not read it.
"""

from __future__ import annotations

import json
from dataclasses import fields
from typing import TYPE_CHECKING, Any

import pytest

from lemely.accuracy.cost_ladder import runner
from lemely.accuracy.cost_ladder.gate import RunSummary, judge
from lemely.accuracy.cost_ladder.report import (
    HEADER,
    LadderFooter,
    LadderRow,
    write_ladder,
    write_report,
)
from lemely.runtime.config import Settings
from tests.test_cost_ladder_runner import (
    _case,
    _er,
    _fake_harness,
    _qr,
    _result,
    _spend_file_in_tmp,  # noqa: F401 -- autouse fixture: keep the ledger in tmp_path
    _summary,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_review_rate_is_flagged_share_of_scored_parts() -> None:
    result = _result(
        [
            _qr("1a", 1, 1, needs_teacher_review=True),
            _qr("1b", 1, 1),
            _qr("1c", 0, 1),
            _qr("1d", 0, 1, scored=False, needs_teacher_review=True, marker_source="missing"),
        ],
        [_er("a", "1a"), _er("a", "1b"), _er("a", "1c"), _er("a", "1d")],
    )
    marking = runner._marking(result)
    assert runner.review_rate(marking) == pytest.approx(1 / 3)


def test_review_rate_of_no_scored_parts_is_none() -> None:
    marking = runner._marking(_result([], []))
    assert runner.review_rate(marking) is None


def test_review_rate_does_not_enter_run_summary() -> None:
    assert "review_rate" not in {f.name for f in fields(RunSummary)}


def test_live_run_writes_review_rate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    clients: list[tuple[Settings, str]] = []
    _fake_harness(monkeypatch, {"a": [], "b": []}, clients)
    runner.run_config(
        "lever1",
        {},
        out_dir=tmp_path,
        cases=[_case("a"), _case("b")],
        settings=Settings(),
        max_run_usd={"gemini": 1.0},
    )
    data = json.loads((tmp_path / "lever1" / "summary.json").read_text())
    assert data["review_rate"] == 0.0
    # The gate's own view still round-trips unchanged.
    assert runner.read_summary(tmp_path / "lever1" / "summary.json").scored_parts == 2


def _stored_qr(qid: str, *, review: bool, scored: bool = True) -> dict[str, Any]:
    return {
        "case_key": "a",
        "question_id": qid,
        "question_type": "theory",
        "predicted_marks": 1,
        "truth_marks": 1,
        "confidence_score": 0.85 if review else 0.95,
        "needs_teacher_review": review,
        "review_reason": "confidence 0.85 below review threshold 0.90" if review else None,
        "marker_source": "ai",
        "scored": scored,
    }


def test_resummarise_writes_review_rate(tmp_path: Path) -> None:
    run = tmp_path / "lever1"
    run.mkdir()
    runner.write_summary(_summary(), run / "summary.json", usd_per_script_mean_now=0.0)
    (run / "records.jsonl").write_text("")
    (run / "results.json").write_text(
        json.dumps(
            {
                "case_keys": ["a"],
                "unmarked_leaves": [],
                "metrics": {"id_match_rate": 1.0},
                "question_results": [
                    _stored_qr("1", review=True),
                    _stored_qr("2", review=False),
                    _stored_qr("3", review=False),
                    _stored_qr("4", review=False),
                ],
            }
        )
    )
    runner.resummarise("lever1", out_dir=tmp_path)
    data = json.loads((run / "summary.json").read_text())
    assert data["review_rate"] == pytest.approx(0.25)


# ---------------------------------------------------------------------------
# LADDER.md
# ---------------------------------------------------------------------------


def _footer() -> LadderFooter:
    return LadderFooter(
        baseline_usd_2026=1.0,
        baseline_usd_2027=1.0,
        final_usd_2026=1.0,
        final_usd_2027=1.0,
        stop_reason="done",
    )


def _row(review_rate: float | None) -> LadderRow:
    base = _summary()
    cand = _summary(usd_per_script_mean=0.5)
    return LadderRow(
        lever="cheaper model",
        expected_saving="40%",
        candidate=cand,
        verdict=judge(base, cand, aa_floor=1, original_latency_p95_ms=1000.0),
        proof="runs/x",
        review_rate=review_rate,
    )


def test_header_has_review_rate_after_validity() -> None:
    assert HEADER[HEADER.index("validity") + 1] == "review rate"


def test_ladder_row_shows_review_rate_percent(tmp_path: Path) -> None:
    out = tmp_path / "LADDER.md"
    write_ladder([_row(16 / 78), _row(None)], out, footer=_footer())
    lines = [ln for ln in out.read_text().splitlines() if ln.startswith("| cheaper model")]
    cells = [ln.split(" | ") for ln in lines]
    col = HEADER.index("review rate")
    assert cells[0][col] == "20.5%"
    assert cells[1][col] == "-"
    assert all(len(c) == len(HEADER) for c in cells)


def test_report_reads_review_rate_from_summary(tmp_path: Path) -> None:
    runner.write_summary(
        _summary(), tmp_path / "baseline" / "summary.json", usd_per_script_mean_now=1.0
    )
    for label, rate in (("old", None), ("new", 0.125)):
        extra = {} if rate is None else {"review_rate": rate}
        runner.write_summary(
            _summary(), tmp_path / label / "summary.json", usd_per_script_mean_now=1.0, extra=extra
        )
        verdict = judge(_summary(), _summary(), aa_floor=1, original_latency_p95_ms=1000.0)
        (tmp_path / label / "verdict.json").write_text(
            json.dumps(
                {
                    "lever": label,
                    "expected_saving": "-",
                    "proof": label,
                    "passed": verdict.passed,
                    "tier": verdict.tier,
                    "saving": verdict.saving,
                    "extra_mismarks": verdict.extra_mismarks,
                    "allowed_extra": verdict.allowed_extra,
                    "reasons": list(verdict.reasons),
                }
            )
        )
        runner.append_ladder(tmp_path, label)
    text = write_report(tmp_path, stop_reason="done").read_text()
    col = HEADER.index("review rate")
    rows = {ln.split(" | ")[0]: ln.split(" | ") for ln in text.splitlines() if ln.startswith("| ")}
    assert rows["| old"][col] == "-"
    assert rows["| new"][col] == "12.5%"
