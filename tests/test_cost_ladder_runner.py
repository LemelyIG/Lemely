"""Tests for the cost-ladder runner and report. Fakes only: no model calls."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from lemely.accuracy.cost_ladder import runner
from lemely.accuracy.cost_ladder.gate import RunSummary, Verdict, judge
from lemely.accuracy.cost_ladder.report import LadderFooter, LadderRow, write_ladder
from lemely.accuracy.cost_ladder.runner import (
    CorpusDigestMismatch,
    ProbeContext,
    apply_overrides,
    assert_corpus_digest,
    require_gemini_key,
    summarise,
)
from lemely.accuracy.cost_ladder.spend import SpendCapError, SpendCaps
from lemely.accuracy.harness import (
    AccuracyMetrics,
    AccuracyResult,
    FunnelCounts,
    GoldenCase,
    QuestionResult,
)
from lemely.eval.manifest import RunManifest
from lemely.eval.records import EvalRecord
from lemely.io.gemini import CallRecord, UnpricedModelError
from lemely.runtime.config import Settings


def _qr(qid: str, predicted: int, truth: int, *, scored: bool = True) -> QuestionResult:
    return QuestionResult(
        question_id=qid,
        question_type="theory",
        predicted_marks=predicted,
        truth_marks=truth,
        confidence_score=0.9,
        needs_teacher_review=False,
        scored=scored,
    )


def _er(paper: str, qid: str, outcome: str = "correct") -> EvalRecord:
    marked = outcome not in ("excluded", "unmatched")
    return EvalRecord(
        run_id="r",
        arm="oracle+mark",
        paper_id=paper,
        fixture_variant=None,
        question_id=qid,
        mark_point_id=None,
        parse_path="gemini",
        predicted_marks=1 if marked else None,
        truth_marks=1,
        outcome=outcome,  # type: ignore[arg-type]
        extraction_conf=None,
        marker_conf=0.9,
        id_match="exact" if marked else "unmatched",
        triggers=[],
    )


def _manifest() -> RunManifest:
    return RunManifest(
        run_id="r",
        git_sha="abc",
        timestamp=datetime(2026, 10, 19, tzinfo=UTC),
        prompt_versions={},
        params_fingerprint="f",
        models_by_task={},
        cache_mode="bypass",
        split="dev",
        corpus_digest="76989782d6fda9fc",
    )


def _result(
    qrs: list[QuestionResult],
    ers: list[EvalRecord],
    *,
    id_match_rate: float | None = 0.9,
) -> AccuracyResult:
    return AccuracyResult(
        metrics=AccuracyMetrics(
            mark_accuracy=0.9,
            mark_accuracy_theory=0.9,
            id_match_rate=id_match_rate,
            flag_precision_high=1.0,
            flag_recall=1.0,
        ),
        calibration=[],
        question_results=qrs,
        prompt_versions={},
        manifest=_manifest(),
        eval_records=ers,
        funnel=FunnelCounts(),
    )


def _rec(
    case: str | None,
    *,
    usd_2027: float = 0.0,
    usd_now: float = 0.0,
    latency_ms: int = 0,
    parse_ok: bool = True,
) -> CallRecord:
    return CallRecord(
        provider="gemini",
        task_tag="correction",
        model="m",
        thinking=None,
        input_tokens=1,
        cached_tokens=0,
        output_tokens=1,
        thinking_tokens=0,
        usd_now=usd_now,
        usd_2027=usd_2027,
        latency_ms=latency_ms,
        attempt="first",
        question_id=None,
        case_key=case,
        parse_ok=parse_ok,
    )


def test_summarise_counts_only_scored_mismarks() -> None:
    qrs = [
        _qr("1a", 1, 2),  # mismarked, scored
        _qr("1b", 2, 2),  # right
        _qr("1c", 0, 3, scored=False),  # wrong but unscored: ignored
    ]
    ers = [_er("p1", "1a"), _er("p1", "1b"), _er("p1", "1c")]
    s = summarise(_result(qrs, ers), [_rec("p1")])
    assert s.mismarked_parts == frozenset({"p1/1a"})
    assert s.scored_parts == 2


def test_mismark_keys_do_not_collide_across_cases() -> None:
    qrs = [_qr("1a", 0, 1), _qr("1a", 0, 1)]
    ers = [_er("p1", "1a"), _er("p2", "1a")]
    s = summarise(_result(qrs, ers), [])
    assert s.mismarked_parts == frozenset({"p1/1a", "p2/1a"})


def test_summarise_uses_2027_usd() -> None:
    qrs = [_qr("1a", 1, 1), _qr("1a", 1, 1)]
    ers = [_er("p1", "1a"), _er("p2", "1a")]
    recs = [
        _rec("p1", usd_2027=0.10, usd_now=9.0),
        _rec("p1", usd_2027=0.20, usd_now=9.0),
        _rec("p2", usd_2027=0.30, usd_now=9.0),
    ]
    s = summarise(_result(qrs, ers), recs)
    assert s.usd_per_script_mean == pytest.approx((0.30 + 0.30) / 2)


def test_latency_p95_nearest_rank() -> None:
    cases = [f"p{i}" for i in range(20)]
    qrs = [_qr("1a", 1, 1) for _ in cases]
    ers = [_er(c, "1a") for c in cases]
    # per-case summed latency = 100 * (i + 1): 100 .. 2000; nearest-rank p95 of 20 is rank 19.
    recs = [_rec(c, latency_ms=100 * (i + 1)) for i, c in enumerate(cases)]
    s = summarise(_result(qrs, ers), recs)
    assert s.latency_p95_ms == 1900.0


def test_latency_sums_calls_within_a_case() -> None:
    s = summarise(
        _result([_qr("1a", 1, 1)], [_er("p1", "1a")]),
        [_rec("p1", latency_ms=400), _rec("p1", latency_ms=600)],
    )
    assert s.latency_p95_ms == 1000.0


def test_validity_rate_is_share_of_parse_ok() -> None:
    recs = [_rec("p1"), _rec("p1"), _rec("p1"), _rec("p1", parse_ok=False)]
    s = summarise(_result([_qr("1a", 1, 1)], [_er("p1", "1a")]), recs)
    assert s.validity_rate == 0.75


def test_incomplete_case_listed() -> None:
    qrs = [_qr("1a", 1, 1), _qr("1a", 1, 1)]
    ers = [
        _er("p1", "1a"),
        _er("p2", "1a"),
        _er("p2", "1b", outcome="excluded"),  # funnel shortfall in p2
        _er("p3", "1a", outcome="unmatched"),  # funnel shortfall in p3
    ]
    recs = [_rec("p4", parse_ok=False)]  # failed call in p4
    ers.append(_er("p4", "1a"))
    qrs.append(_qr("1a", 1, 1))
    s = summarise(_result(qrs, ers), recs)
    assert s.incomplete == ("p2", "p3", "p4")


def test_clean_run_has_no_incomplete_and_full_validity() -> None:
    s = summarise(_result([_qr("1a", 1, 1)], [_er("p1", "1a")]), [_rec("p1")])
    assert s.incomplete == ()
    assert s.validity_rate == 1.0


def test_missing_id_match_rate_counts_as_perfect() -> None:
    s = summarise(_result([_qr("1a", 1, 1)], [_er("p1", "1a")], id_match_rate=None), [_rec("p1")])
    assert s.id_match_rate == 1.0


def _case(paper: str) -> GoldenCase:
    return GoldenCase(
        paper_id=paper,
        mark_scheme=None,  # type: ignore[arg-type]
        ground_truth={},
    )


def test_corpus_digest_mismatch_aborts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "_corpus_digest", lambda cases: "deadbeefdeadbeef")
    with pytest.raises(CorpusDigestMismatch, match="76989782d6fda9fc"):
        assert_corpus_digest([_case("p1")])


def test_corpus_digest_match_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "_corpus_digest", lambda cases: "76989782d6fda9fc")
    assert_corpus_digest([_case("p1")])


def test_probe_context_sets_case_before_each_case(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str | None] = []
    monkeypatch.setattr(runner, "set_call_context", lambda *, case_key: seen.append(case_key))
    probe = ProbeContext(["a", "b"], lambda: {"t": 1.0})
    # measure_accuracy samples the probe before and after each case.
    assert [probe(), probe(), probe(), probe()] == [{"t": 1.0}] * 4
    assert seen == ["a", "b"]


def test_require_gemini_key_refuses_without_value() -> None:
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        require_gemini_key({})
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        require_gemini_key({"GEMINI_API_KEY": ""})
    require_gemini_key({"GEMINI_API_KEY": "x"})


def test_require_gemini_key_error_does_not_leak_value() -> None:
    with pytest.raises(RuntimeError) as exc:
        require_gemini_key({"GEMINI_API_KEY": ""})
    assert "secret-value" not in str(exc.value)


def test_apply_overrides_sets_nested_field() -> None:
    base = Settings()
    out = apply_overrides(base, {"gemini.correction_model": "gemini-x"})
    assert out.gemini.correction_model == "gemini-x"
    assert base.gemini.correction_model != "gemini-x"


def test_apply_overrides_rejects_unknown_and_undotted() -> None:
    with pytest.raises(ValueError, match=r"gemini\.nope"):
        apply_overrides(Settings(), {"gemini.nope": 1})
    with pytest.raises(ValueError, match="dotted"):
        apply_overrides(Settings(), {"nodot": 1})


def test_parse_override_value() -> None:
    assert runner.parse_override_value("true") is True
    assert runner.parse_override_value("3") == 3
    assert runner.parse_override_value("gemini-3-flash") == "gemini-3-flash"


def _summary(**kw: Any) -> RunSummary:
    base = RunSummary(
        usd_per_script_mean=1.0,
        latency_p95_ms=1000.0,
        mismarked_parts=frozenset(),
        scored_parts=100,
        id_match_rate=0.9,
        validity_rate=1.0,
        incomplete=(),
    )
    return replace(base, **kw)


def test_summary_json_round_trip(tmp_path: Path) -> None:
    s = _summary(mismarked_parts=frozenset({"p/1a", "p/1b"}), incomplete=("p2",))
    path = tmp_path / "summary.json"
    runner.write_summary(s, path, usd_per_script_mean_now=2.5)
    assert runner.read_summary(path) == s
    assert json.loads(path.read_text())["usd_per_script_mean_now"] == 2.5


def test_ladder_table_has_reasons_and_stop_line(tmp_path: Path) -> None:
    base = _summary()
    good = _summary(usd_per_script_mean=0.5)
    bad = _summary(usd_per_script_mean=0.9, mismarked_parts=frozenset({"p/1a", "p/1b"}))
    rows = [
        LadderRow(
            lever="cheaper model",
            expected_saving="40%",
            candidate=good,
            verdict=judge(base, good, aa_floor=1, original_latency_p95_ms=1000.0),
            proof="runs/good",
        ),
        LadderRow(
            lever="thin prompt",
            expected_saving="10%",
            candidate=bad,
            verdict=judge(base, bad, aa_floor=1, original_latency_p95_ms=1000.0),
            proof="runs/bad",
        ),
    ]
    assert isinstance(rows[1].verdict, Verdict)
    footer = LadderFooter(
        baseline_usd_2026=2.0,
        baseline_usd_2027=1.0,
        final_usd_2026=1.0,
        final_usd_2027=0.5,
        stop_reason="next lever below the 5% floor",
    )
    out = tmp_path / "LADDER.md"
    write_ladder(rows, out, footer=footer)
    text = out.read_text()
    for col in (
        "lever",
        "expected saving",
        "measured saving (2027)",
        "extra mismarks / allowed",
        "id-match",
        "p95 latency",
        "validity",
        "proof",
        "verdict",
        "reasons",
    ):
        assert col in text
    assert "cheaper model" in text
    assert "ACCEPT" in text
    assert "REJECT" in text
    assert "newly mismarked parts exceed the allowed" in text
    assert "50.0%" in text  # measured saving for the accepted row
    assert "2026 rates" in text
    assert "2027 rates" in text
    assert "Stop reason: next lever below the 5% floor" in text


def test_nan_usd_marks_case_incomplete() -> None:
    qrs = [_qr("1a", 1, 1), _qr("1a", 1, 1)]
    ers = [_er("p1", "1a"), _er("p2", "1a")]
    recs = [
        _rec("p1", usd_2027=0.10),
        replace(_rec("p2", usd_2027=0.10), usd_2027=float("nan"), model="gemini-9-unknown"),
    ]
    s = summarise(_result(qrs, ers), recs)
    assert s.incomplete == ("p2 (unpriced model gemini-9-unknown)",)
    assert s.usd_per_script_mean == pytest.approx(0.05)  # NaN is not summed into the mean


def test_preflight_aborts_on_unpriced_model(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = apply_overrides(Settings(), {"gemini.correction_model": "gemini-9-unknown"})
    assert "gemini-9-unknown" in runner.models_in_play(settings)
    with pytest.raises(UnpricedModelError, match="gemini-9-unknown"):
        runner.preflight_prices(settings)

    # run_config aborts before any model call or client construction.
    monkeypatch.setattr(runner, "_corpus_digest", lambda cases: runner.PINNED_CORPUS_DIGEST)

    def boom(*a: object, **k: object) -> None:
        raise AssertionError("must not spend")

    monkeypatch.setattr(runner, "measure_accuracy", boom)
    monkeypatch.setattr(runner, "GeminiClient", boom)
    with pytest.raises(UnpricedModelError):
        runner.run_config(
            "x",
            {"gemini.correction_model": "gemini-9-unknown"},
            out_dir=Path("/nonexistent"),
            cases=[_case("p1")],
            settings=Settings(),
        )


def test_default_models_are_all_priced() -> None:
    runner.preflight_prices(Settings())


# --- spend caps ---------------------------------------------------------------------------


def _bill(case: str, usd: float, provider: str = "gemini") -> CallRecord:
    return replace(_rec(case, usd_now=usd), provider=provider)


def _stub_run(
    monkeypatch: pytest.MonkeyPatch, per_case_usd: dict[str, float], calls: list[str]
) -> list[CallRecord]:
    """Fake harness: samples the probe twice per case and bills per_case_usd[case]."""
    records: list[CallRecord] = []
    monkeypatch.setattr(runner, "_corpus_digest", lambda cases: runner.PINNED_CORPUS_DIGEST)
    monkeypatch.setattr(runner, "preflight_prices", lambda settings: None)
    monkeypatch.setattr(runner, "GeminiClient", lambda *a, **k: object())
    monkeypatch.setattr(runner, "reset_process_counters", lambda: records.clear())
    monkeypatch.setattr(runner, "process_call_records", lambda: list(records))
    monkeypatch.setattr(runner, "set_call_context", lambda *, case_key: None)

    def fake_measure(cases: list[GoldenCase], client: object, settings: object, **kw: Any):  # type: ignore[no-untyped-def]
        probe = kw["cost_probe"]
        for case in cases:
            probe()
            calls.append(case.paper_id)
            records.append(_bill(case.paper_id, per_case_usd[case.paper_id]))
            probe()
        qrs = [_qr("1a", 1, 1) for _ in cases]
        ers = [_er(c.paper_id, "1a") for c in cases]
        return _result(qrs, ers)

    monkeypatch.setattr(runner, "measure_accuracy", fake_measure)
    return records


def test_cap_blocks_run_before_start(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[str] = []
    _stub_run(monkeypatch, {"a": 1.0}, calls)
    (tmp_path / "spend.json").write_text(json.dumps({"gemini": 2.5}))
    with pytest.raises(SpendCapError, match="gemini"):
        runner.run_config(
            "baseline",
            {},
            out_dir=tmp_path,
            cases=[_case("a")],
            settings=Settings(),
            max_run_usd={"gemini": 0.6},  # 2.5 + 0.6 > 3.00
        )
    assert calls == []  # nothing ran
    assert json.loads((tmp_path / "spend.json").read_text()) == {"gemini": 2.5}


def test_first_run_refused_without_max_run_usd(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[str] = []
    _stub_run(monkeypatch, {"a": 1.0}, calls)
    with pytest.raises(SpendCapError, match="max-run-usd"):
        runner.run_config("baseline", {}, out_dir=tmp_path, cases=[_case("a")], settings=Settings())
    assert calls == []


def test_cap_stops_mid_run_after_case(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[str] = []
    costs = {"a": 1.0, "b": 1.0, "c": 1.0, "d": 1.0}
    _stub_run(monkeypatch, costs, calls)
    caps = SpendCaps(gemini_usd=3.0, anthropic_usd=40.0)
    summary = runner.run_config(
        "baseline",
        {},
        out_dir=tmp_path,
        cases=[_case(k) for k in costs],
        settings=Settings(),
        caps=caps,
        max_run_usd={"gemini": 2.0},
    )
    # After b: total 2.0 < cap 3.0 - largest case 1.0 = 2.0? No: 2.0 >= 2.0, so stop after b.
    assert calls == ["a", "b"]
    assert summary.incomplete == ("c (spend cap)", "d (spend cap)")
    # The gate fails a capped run: it is incomplete and scored no parts.
    verdict = judge(_summary(), summary, aa_floor=0, original_latency_p95_ms=1000.0)
    assert not verdict.passed
    stopped = json.loads((tmp_path / "baseline" / "summary.json").read_text())
    assert "stopped_by_spend_cap" in stopped
    # The two billed cases were still recorded against the combined cap.
    assert json.loads((tmp_path / "spend.json").read_text()) == {"gemini": pytest.approx(2.0)}


def test_spend_file_accumulates_across_runs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[str] = []
    _stub_run(monkeypatch, {"a": 0.4, "b": 0.6}, calls)
    kwargs: dict[str, Any] = {
        "out_dir": tmp_path,
        "cases": [_case("a"), _case("b")],
        "settings": Settings(),
        "max_run_usd": {"gemini": 1.0},
    }
    runner.run_config("baseline", {}, **kwargs)
    assert json.loads((tmp_path / "spend.json").read_text()) == {"gemini": pytest.approx(1.0)}
    # Same prefix: the second run projects from the first, and adds to the shared total.
    runner.run_config("baseline_aa", {}, **kwargs)
    assert json.loads((tmp_path / "spend.json").read_text()) == {"gemini": pytest.approx(2.0)}
    assert json.loads((tmp_path / "baseline_aa" / "run_cost.json").read_text()) == {
        "gemini": pytest.approx(1.0)
    }


def test_anthropic_and_google_providers_are_capped_separately() -> None:
    from lemely.accuracy.cost_ladder.spend import CapWatch, cost_by_provider

    recs = [_bill("a", 1.0, "google"), _bill("a", 5.0, "anthropic")]
    assert cost_by_provider(recs) == {"gemini": 1.0, "anthropic": 5.0}
    watch = CapWatch(SpendCaps(gemini_usd=3.0, anthropic_usd=40.0), {"anthropic": 30.0})
    message = watch.add_case(recs)  # anthropic 30 + 5 = 35 >= 40 - 5; gemini 1 < 3 - 1
    assert message is not None
    assert message.startswith("anthropic")
