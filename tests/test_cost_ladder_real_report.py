"""Sub-project C P1: real-split and escalation figures in LADDER.md and FLIP.md (counts only)."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from lemely.accuracy.cost_ladder import runner
from lemely.accuracy.cost_ladder.gate import RunSummary, Verdict
from lemely.accuracy.cost_ladder.report import (
    HEADER,
    REAL_HEADER,
    LadderFooter,
    LadderRow,
    write_flip,
    write_ladder,
    write_report,
)

_FOOT = LadderFooter(0.1, 0.1, 0.05, 0.05, "done")


def _real(**kw: object) -> RunSummary:
    base = RunSummary(
        0.05,
        1000.0,
        frozenset(),
        78,
        1.0,
        1.0,
        (),
        real_scripts=("a", "b"),
        real_abs_error=12.5,
        real_exact_rate=0.8,
        real_within1_rate=0.95,
        real_review_rate=0.3,
        real_binding_passes=2.0,
        real_usd_mean=0.05,
        real_usd_by_script=(("a", 0.04), ("b", 0.06)),
        real_usd_max_by_script=(("a", 0.045), ("b", 0.07)),
        real_escalation_rate=0.05,
        real_escalation_rate_max_script=0.08,
        real_escalation_usd_by_script=(("a", 0.004), ("b", 0.006)),
    )
    return replace(base, **kw)  # type: ignore[arg-type]


def _verdict(**kw: object) -> Verdict:
    return Verdict(True, "small", 0.1, 0, 0, (), **kw)  # type: ignore[arg-type]


def _row_of(text: str, lever: str) -> str:
    return next(line for line in text.splitlines() if line.startswith(f"| {lever} "))


def test_ladder_without_real_keeps_todays_header(tmp_path: Path) -> None:
    out = tmp_path / "L.md"
    write_ladder(
        [LadderRow("x", "1%", RunSummary(1, 1, frozenset(), 1, 1, 1, ()), _verdict(), "p")],
        out,
        footer=_FOOT,
    )
    assert "| " + " | ".join(HEADER) + " |" in out.read_text()
    assert REAL_HEADER[0] not in out.read_text()


def test_ladder_with_real_adds_the_columns(tmp_path: Path) -> None:
    out = tmp_path / "L.md"
    write_ladder(
        [LadderRow("a1", "13%", _real(), _verdict(notes=("real saving 4.0%",)), "p")],
        out,
        footer=_FOOT,
        real=True,
    )
    text = out.read_text()
    assert "| " + " | ".join(HEADER + REAL_HEADER) + " |" in text
    row = _row_of(text, "a1")
    for cell in (
        "12.5",
        "80.0%",
        "95.0%",
        "30.0%",
        "2.0/2",
        "b $0.0700",
        "5.0%",
        "10.0%",
        "real saving 4.0%",
    ):
        assert f"| {cell} |" in row or row.endswith(f"| {cell} |"), cell


def test_dev_only_rung_in_a_real_ladder_shows_dashes_not_zeros(tmp_path: Path) -> None:
    out = tmp_path / "L.md"
    dev = RunSummary(1, 1, frozenset(), 1, 1, 1, ())
    write_ladder([LadderRow("d1", "1%", dev, _verdict(), "p")], out, footer=_FOOT, real=True)
    cells = _row_of(out.read_text(), "d1").split(" | ")[-len(REAL_HEADER) :]
    assert cells[:-1] == ["-"] * (len(REAL_HEADER) - 1)


def test_incomplete_real_rung_is_visibly_incomplete(tmp_path: Path) -> None:
    out = tmp_path / "L.md"
    cand = _real(real_incomplete=("script-z (no result)",))
    write_ladder([LadderRow("i1", "1%", cand, _verdict(), "p")], out, footer=_FOOT, real=True)
    row = _row_of(out.read_text(), "i1")
    assert "12.5 (incomplete)" in row
    assert "INCOMPLETE real cases: script-z (no result)" in row


def test_every_reason_is_rendered(tmp_path: Path) -> None:
    out = tmp_path / "L.md"
    reasons = tuple(f"reason number {i}" for i in range(9))
    v = Verdict(False, "small", 0.0, 0, 0, reasons)
    write_ladder([LadderRow("r1", "1%", _real(), v, "p")], out, footer=_FOOT, real=True)
    row = _row_of(out.read_text(), "r1")
    assert all(r in row for r in reasons)
    assert "REJECT" in row


def test_write_report_switches_real_columns_on_from_the_baseline(tmp_path: Path) -> None:
    runner.write_summary(
        _real(), tmp_path / "baseline" / "summary.json", usd_per_script_mean_now=0.05
    )
    path = write_report(tmp_path, stop_reason="none")
    assert REAL_HEADER[0] in path.read_text()
    assert "Baseline real split: abs error 12.5 marks over 2 scripts" in path.read_text()


def test_write_report_dev_only_keeps_todays_header(tmp_path: Path) -> None:
    dev = RunSummary(1, 1, frozenset(), 1, 1, 1, ())
    runner.write_summary(dev, tmp_path / "baseline" / "summary.json", usd_per_script_mean_now=0.05)
    assert REAL_HEADER[0] not in write_report(tmp_path, stop_reason="none").read_text()


def _flip_dir(tmp_path: Path, **verdict: object) -> None:
    runner.write_summary(_real(), tmp_path / "stack" / "summary.json", usd_per_script_mean_now=0.0)
    runner.write_summary(
        _real(real_abs_error=14.0, real_escalation_rate=None),
        tmp_path / "gemini" / "summary.json",
        usd_per_script_mean_now=0.0,
    )
    body = {
        "candidate": "stack",
        "gemini": "gemini",
        "passed": True,
        "reasons": [],
        "notes": ["escalation rate 5.0% (max script 8.0%)"],
    } | verdict
    (tmp_path / runner.FLIP_VERDICT_FILE).write_text(json.dumps(body))


def test_flip_report_has_both_sides_and_no_leaf_marks(tmp_path: Path) -> None:
    _flip_dir(tmp_path)
    text = write_flip(tmp_path, candidate="stack", gemini="gemini").read_text()
    assert "| real abs error (marks) | 14.0 | 12.5 |" in text
    assert "| escalation rate | - | 5.0% |" in text
    assert "Verdict: PASS" in text
    assert "escalation rate 5.0% (max script 8.0%)" in text
    assert "| b | $0.0700 | $0.0700 | $0.0060 |" in text


def test_flip_report_renders_every_failure_reason(tmp_path: Path) -> None:
    reasons = [f"flip reason {i}" for i in range(7)]
    _flip_dir(tmp_path, passed=False, reasons=reasons)
    text = write_flip(tmp_path, candidate="stack", gemini="gemini").read_text()
    assert "Verdict: FAIL" in text
    assert all(f"- {r}" in text for r in reasons)


def test_flip_report_marks_missing_real_split_and_incomplete(tmp_path: Path) -> None:
    runner.write_summary(
        _real(real_incomplete=("script-z (no result)",)),
        tmp_path / "stack" / "summary.json",
        usd_per_script_mean_now=0.0,
    )
    runner.write_summary(
        RunSummary(1, 1, frozenset(), 1, 1, 1, ()),
        tmp_path / "gemini" / "summary.json",
        usd_per_script_mean_now=0.0,
    )
    (tmp_path / runner.FLIP_VERDICT_FILE).write_text(
        json.dumps({"candidate": "stack", "gemini": "gemini", "passed": False, "reasons": ["x"]})
    )
    text = write_flip(tmp_path, candidate="stack", gemini="gemini").read_text()
    assert "| real abs error (marks) | - | 12.5 |" in text
    assert "Candidate: INCOMPLETE real cases: script-z (no result)" in text
    assert "| a | - | $0.0450 | $0.0040 |" in text
    assert "nan" not in text


def test_flip_report_refuses_a_verdict_for_other_rungs(tmp_path: Path) -> None:
    _flip_dir(tmp_path, candidate="other")
    with pytest.raises(runner.LadderStateError, match="re-run"):
        write_flip(tmp_path, candidate="stack", gemini="gemini")


def test_reports_carry_counts_only(tmp_path: Path) -> None:
    secret = "STUDENT-ANSWER-TEXT-xyzzy"
    parts = frozenset({f"case-1/{secret}", "case-1/Q2b"})
    _flip_dir(tmp_path)
    for rung in ("stack", "gemini"):
        path = tmp_path / rung / "summary.json"
        data = json.loads(path.read_text())
        data.update(
            mismarked_parts=sorted(parts),
            answer_text=secret,
            evidence=[secret],
            per_leaf_marks={"Q2b": 3},
        )
        path.write_text(json.dumps(data))
    stack = replace(_real(), mismarked_parts=parts)
    runner.write_summary(
        stack, tmp_path / "baseline" / "summary.json", usd_per_script_mean_now=0.05
    )
    (tmp_path / "ladder.json").write_text(json.dumps(["stack"]))
    (tmp_path / "stack" / "verdict.json").write_text(
        json.dumps(
            {
                "lever": "stack",
                "expected_saving": "1%",
                "proof": "p",
                "passed": True,
                "tier": "small",
                "saving": 0.1,
                "extra_mismarks": 0,
                "allowed_extra": 0,
                "reasons": [],
                "evidence": secret,
            }
        )
    )
    ladder = write_report(tmp_path, stop_reason="none").read_text()
    flip = write_flip(tmp_path, candidate="stack", gemini="gemini").read_text()
    for text in (ladder, flip):
        assert secret not in text
        assert "Q2b" not in text
    assert "| synthetic mismarked parts | 2 | 2 |" in flip
