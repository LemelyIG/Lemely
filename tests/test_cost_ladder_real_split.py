"""Sub-project C P1: the real split's loader, scoring and aggregation. No model calls."""

from __future__ import annotations

import json
import math
from dataclasses import replace
from pathlib import Path

import pytest

from lemely.accuracy import reference as ref
from lemely.accuracy.cost_ladder import real_split as rs
from lemely.accuracy.cost_ladder.real_split import LeafOutcome, RealScriptResult, ReferenceDrift
from lemely.core.schemas import CorrectedQuestion, CorrectionResult, ExamMetadata
from lemely.io.gemini import CallRecord


def _frozen(tmp_path: Path, key: str = "k", marks: dict[str, int] | None = None) -> rs.RealScript:
    d = tmp_path / key
    leaves = [
        ref.ReferenceLeaf(qid, m, 2, "opus", "e")
        for qid, m in (marks or {"1a": 2, "1b": 1, "1c": 0}).items()
    ]
    ref.write_reference(d / ref.REFERENCE_FILE, leaves)
    (d / ref.SCHEME_FILE).write_text("{}", encoding="utf-8")
    scan = tmp_path / f"{key}.pdf"
    scan.write_bytes(b"%PDF " + key.encode())
    ref.freeze(
        d,
        key=key,
        scan_path=scan,
        sources={},
        expected_total=None,
        manifest_path=tmp_path / ref.MANIFEST_FILE,
    )
    (script,) = rs.load_real_scripts(tmp_path / ref.MANIFEST_FILE, only=[key])
    return script


def _cq(
    qid: str,
    awarded: int,
    *,
    source: str = "ai",
    review: bool = False,
    conf: float = 0.9,
    reason: str | None = None,
) -> CorrectedQuestion:
    return CorrectedQuestion(
        question_id=qid,
        awarded_marks=awarded,
        maximum_marks=2,
        confidence="high",
        confidence_score=conf,
        needs_teacher_review=review,
        marker_source=source,
        review_reason=reason,
    )


def _result(*qs: CorrectedQuestion) -> CorrectionResult:
    meta = ExamMetadata(
        subject_code="0625",
        paper_number=4,
        paper_variant=1,
        session_month="Oct/Nov",
        session_year=2024,
    )
    return CorrectionResult(metadata=meta, questions=list(qs))


def _rec(tag: str, usd: float, qid: str | None = None, key: str = "k") -> CallRecord:
    return CallRecord(
        provider="anthropic",
        task_tag=tag,
        model="claude-haiku-5-5",
        thinking="low",
        input_tokens=1,
        cached_tokens=0,
        output_tokens=1,
        thinking_tokens=0,
        usd_now=usd,
        usd_2027=usd,
        latency_ms=10,
        attempt=None,
        question_id=qid,
        case_key=key,
        parse_ok=True,
    )


def test_loader_returns_frozen_scripts(tmp_path: Path) -> None:
    _frozen(tmp_path, "a")
    _frozen(tmp_path, "b")
    assert [s.key for s in rs.load_real_scripts(tmp_path / ref.MANIFEST_FILE)] == ["a", "b"]


def test_loader_refuses_a_changed_reference(tmp_path: Path) -> None:
    script = _frozen(tmp_path)
    script.reference_path.write_text("[]\n", encoding="utf-8")
    with pytest.raises(ReferenceDrift, match=r"reference .* sha256 differs"):
        rs.load_real_scripts(tmp_path / ref.MANIFEST_FILE)


def test_loader_refuses_a_missing_scan_and_an_empty_manifest(tmp_path: Path) -> None:
    script = _frozen(tmp_path)
    script.scan_path.unlink()
    with pytest.raises(ReferenceDrift, match=r"scan .* is missing"):
        rs.load_real_scripts(tmp_path / ref.MANIFEST_FILE)
    with pytest.raises(ReferenceDrift, match=r"lists no scripts"):
        rs.load_real_scripts(tmp_path / "none.json")


def test_loader_only_unknown_key_is_refused(tmp_path: Path) -> None:
    _frozen(tmp_path)
    with pytest.raises(ReferenceDrift, match=r"zz"):
        rs.load_real_scripts(tmp_path / ref.MANIFEST_FILE, only=["zz"])


def test_scoring_counts_dropped_missing_and_absent_leaves_as_zero(tmp_path: Path) -> None:
    script = _frozen(tmp_path, marks={"1a": 2, "1b": 1, "1c": 2})
    correction = _result(_cq("1a", 2), _cq("1b", 1, source="dropped", review=True))
    result = rs.score_script(
        script, correction, [], latency_ms=5.0, failure=None, escalations=[], cascade_enabled=False
    )
    by = {leaf.question_id: leaf for leaf in result.leaves}
    assert by["1b"].predicted == 0 and by["1c"].predicted == 0
    assert by["1c"].needs_review is True  # a leaf the correction lost goes to review
    assert result.abs_error == 3
    assert result.incomplete == "no marking output for 1c"  # a lost leaf is never dropped silently
    assert len(result.leaves) == 3  # the denominator never shrinks


def test_failed_ai_marking_makes_the_script_incomplete(tmp_path: Path) -> None:
    script = _frozen(tmp_path)
    correction = _result(
        _cq("1a", 0, source="missing", review=True, reason="AI marking failed: boom"),
        _cq("1b", 1),
        _cq("1c", 0),
    )
    result = rs.score_script(
        script, correction, [], latency_ms=0.0, failure=None, escalations=[], cascade_enabled=False
    )
    assert result.incomplete == "marking failed on 1a"


def test_no_correction_is_incomplete_with_the_failure(tmp_path: Path) -> None:
    script = _frozen(tmp_path)
    result = rs.score_script(
        script,
        None,
        [],
        latency_ms=0.0,
        failure="TimeoutError: x",
        escalations=[],
        cascade_enabled=False,
    )
    assert result.incomplete == "TimeoutError: x"
    assert [leaf.predicted for leaf in result.leaves] == [0, 0, 0]


def test_unpriced_call_makes_the_script_incomplete(tmp_path: Path) -> None:
    script = _frozen(tmp_path)
    rec = replace(_rec("correction", math.nan), model="claude-x")
    result = rs.score_script(
        script,
        _result(_cq("1a", 2), _cq("1b", 1), _cq("1c", 0)),
        [rec],
        latency_ms=0.0,
        failure=None,
        escalations=[],
        cascade_enabled=False,
    )
    assert result.incomplete == "unpriced model claude-x"


def test_escalation_costs_triggers_and_pre_escalation_confidence(tmp_path: Path) -> None:
    script = _frozen(tmp_path)
    records = [
        _rec("correction", 0.01, "1a"),
        _rec("escalation", 0.02, "1a"),
        _rec("adjudication", 0.005, "1b"),
    ]
    events = [
        {"question_id": "1a", "confidence": 0.7, "escalation_model": "claude-haiku-5-5 (thinking)"},
        {"question_id": "1a", "confidence": 0.75, "escalation_model": "claude-sonnet-5-5"},
    ]
    correction = _result(_cq("1a", 2, conf=0.95), _cq("1b", 1), _cq("1c", 0))
    result = rs.score_script(
        script,
        correction,
        records,
        latency_ms=0.0,
        failure=None,
        escalations=events,
        cascade_enabled=False,
    )
    (esc,) = [leaf for leaf in result.leaves if leaf.escalated]
    assert esc.question_id == "1a" and esc.trigger == "confidence"
    assert esc.pre_escalation_confidence == 0.75
    assert result.escalation_usd == pytest.approx(0.02)
    assert result.adjudication_usd == pytest.approx(0.005)
    assert result.usd == pytest.approx(0.035)
    other = next(leaf for leaf in result.leaves if leaf.question_id == "1b")
    assert other.pre_escalation_confidence == 0.9 and other.trigger is None


def _leaf(
    qid: str, predicted: int, reference: int, *, review: bool = False, escalated: bool = False
) -> LeafOutcome:
    return LeafOutcome(
        qid,
        predicted,
        reference,
        2,
        review,
        0.9,
        "ai",
        None,
        escalated,
        "confidence" if escalated else None,
        0.9,
    )


def _script(
    key: str,
    leaves: list[LeafOutcome],
    usd: float,
    *,
    verdict: str = "pass",
    esc_usd: float = 0.0,
    incomplete: str | None = None,
) -> RealScriptResult:
    return RealScriptResult(key, tuple(leaves), verdict, usd, esc_usd, 0.0, 1000.0, incomplete)


def test_summary_fields_average_two_runs_and_take_the_max_cost() -> None:
    run1 = [
        _script("a", [_leaf("1", 2, 2), _leaf("2", 0, 1, review=True)], 0.04),
        _script("b", [_leaf("1", 1, 1, escalated=True)], 0.02, verdict="hold", esc_usd=0.01),
    ]
    run2 = [
        _script("a", [_leaf("1", 2, 2), _leaf("2", 1, 1)], 0.06),
        _script("b", [_leaf("1", 0, 1)], 0.02, verdict="hold", incomplete="x"),
    ]
    f = rs.real_summary_fields([run1, run2])
    assert f["real_scripts"] == ("a", "b")
    assert f["real_abs_error_by_run"] == (1.0, 1.0)
    assert f["real_abs_error"] == 1.0
    assert f["real_exact_rate"] == pytest.approx((2 / 3 + 2 / 3) / 2)
    assert f["real_review_rate"] == pytest.approx((1 / 3 + 0) / 2)
    assert f["real_binding_passes"] == 1.0
    assert dict(f["real_usd_max_by_script"]) == {"a": 0.06, "b": 0.02}  # type: ignore[arg-type]
    assert dict(f["real_usd_by_script"])["a"] == pytest.approx(0.05)  # type: ignore[arg-type]
    assert f["real_escalation_rate"] == pytest.approx((1 / 3 + 0) / 2)
    assert f["real_escalation_rate_max_script"] == 1.0
    assert f["real_escalation_triggers"] == (("confidence", 1),)
    assert f["real_incomplete"] == ("real-2:b (x)",)


def test_summary_fields_need_at_least_one_run() -> None:
    with pytest.raises(ValueError):
        rs.real_summary_fields([])


def test_results_round_trip(tmp_path: Path) -> None:
    results = [_script("a", [_leaf("1", 2, 2, escalated=True)], 0.04, esc_usd=0.01)]
    path = tmp_path / "real_results.json"
    rs.write_real_results(path, results)
    assert rs.read_real_results(path) == results
    assert json.loads(path.read_text())[0]["key"] == "a"


def test_loader_refuses_a_frozen_script_missing_from_the_manifest(tmp_path: Path) -> None:
    _frozen(tmp_path, "a")
    _frozen(tmp_path, "b")
    manifest = tmp_path / ref.MANIFEST_FILE
    data = json.loads(manifest.read_text())
    data["scripts"] = [e for e in data["scripts"] if e["key"] != "b"]
    manifest.write_text(json.dumps(data))  # a crash after FROZEN, before the manifest write
    with pytest.raises(ReferenceDrift, match=r"FROZEN .* not in the manifest"):
        rs.load_real_scripts(manifest)
    with pytest.raises(ReferenceDrift, match=r"FROZEN .* not in the manifest"):
        rs.load_real_scripts(manifest, only=["a"])


def test_loader_refuses_a_manifest_entry_that_is_not_frozen(tmp_path: Path) -> None:
    script = _frozen(tmp_path)
    (script.reference_path.parent / ref.FROZEN_MARKER).unlink()
    with pytest.raises(ReferenceDrift, match=r"manifest entry has no FROZEN"):
        rs.load_real_scripts(tmp_path / ref.MANIFEST_FILE)


def test_loader_refuses_a_changed_scheme(tmp_path: Path) -> None:
    script = _frozen(tmp_path)
    script.scheme_path.write_text('{"x": 1}', encoding="utf-8")
    with pytest.raises(ReferenceDrift, match=r"scheme .* sha256 differs"):
        rs.load_real_scripts(tmp_path / ref.MANIFEST_FILE)


def test_a_failed_call_record_makes_the_script_incomplete(tmp_path: Path) -> None:
    script = _frozen(tmp_path)
    correction = _result(_cq("1a", 2), _cq("1b", 1), _cq("1c", 0))
    result = rs.score_script(
        script,
        correction,
        [],
        latency_ms=0.0,
        failure="boom",
        escalations=[],
        cascade_enabled=False,
    )
    assert result.incomplete == "boom"


def test_script_cost_includes_escalation_and_adjudication_for_the_cap(tmp_path: Path) -> None:
    script = _frozen(tmp_path)
    records = [
        _rec("correction", 0.05, "1a"),
        _rec("escalation", 0.03, "1a"),
        _rec("adjudication", 0.04, "1b"),
    ]
    correction = _result(_cq("1a", 2), _cq("1b", 1), _cq("1c", 0))
    result = rs.score_script(
        script,
        correction,
        records,
        latency_ms=0.0,
        failure=None,
        escalations=[],
        cascade_enabled=False,
    )
    fields = rs.real_summary_fields([[result]])
    assert dict(fields["real_usd_max_by_script"])["k"] == pytest.approx(0.12)  # type: ignore[arg-type]
