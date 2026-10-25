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
from lemely.io.correction_ai import _BLANK_ANSWER_REVIEW_REASON
from lemely.io.gemini import CallRecord, UnpricedModelError
from lemely.runtime.config import Settings
from lemely.runtime.events import EventType, bus


@pytest.fixture(autouse=True)
def _spend_file_in_tmp(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Never touch the repo's pinned ledger: every test books to ``tmp_path/spend.json``."""
    path = tmp_path / "spend.json"
    monkeypatch.setattr(runner, "DEFAULT_SPEND_FILE", path)
    return path


def _qr(
    qid: str,
    predicted: int,
    truth: int,
    *,
    scored: bool = True,
    needs_teacher_review: bool = False,
    marker_source: str | None = None,
    review_reason: str | None = None,
) -> QuestionResult:
    return QuestionResult(
        question_id=qid,
        question_type="theory",
        predicted_marks=predicted,
        truth_marks=truth,
        confidence_score=0.9,
        needs_teacher_review=needs_teacher_review,
        scored=scored,
        review_reason=review_reason,
        marker_source=marker_source,
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
        corpus_digest="090492b217365de4",
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
    # p4: a call failed to parse but every leaf was marked. Validity counts it;
    # completeness does not (user decision 2026-10-19).
    recs = [_rec("p4", parse_ok=False)]
    ers.append(_er("p4", "1a"))
    qrs.append(_qr("1a", 1, 1))
    # p5: the marking call failed outright; the leaf is a "missing" placeholder
    # (scored=False, needs_teacher_review=True), so the case is incomplete.
    recs.append(_rec("p5", parse_ok=False))
    ers.append(_er("p5", "1a", outcome="abstain"))
    qrs.append(_qr("1a", 0, 1, scored=False, needs_teacher_review=True, marker_source="missing"))
    s = summarise(_result(qrs, ers), recs)
    assert s.incomplete == ("p2", "p3", "p5 (marking failed)")
    assert s.validity_rate == 0.0


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
    with pytest.raises(CorpusDigestMismatch, match="090492b217365de4"):
        assert_corpus_digest([_case("p1")])


def test_corpus_digest_match_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "_corpus_digest", lambda cases: "090492b217365de4")
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
    # A key with stray whitespace (a wrapper that kept the file's newline) is refused,
    # and the refusal names the variable without echoing the value.
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY") as exc:
        require_gemini_key({"GEMINI_API_KEY": " secret-value\n"})
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
    (tmp_path / "spend.json").write_text(json.dumps({"gemini": 5.5}))
    with pytest.raises(SpendCapError, match="gemini"):
        runner.run_config(
            "baseline",
            {},
            out_dir=tmp_path,
            cases=[_case("a")],
            settings=Settings(),
            max_run_usd={"gemini": 0.6},  # 5.5 + 0.6 > 6.00, the default cap
        )
    assert calls == []  # nothing ran
    assert json.loads((tmp_path / "spend.json").read_text()) == {"gemini": 5.5}


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


# --- fix round 1: rung-0 latency, stacking, cache discipline, composition -------------------


def _tagged(
    case: str,
    tag: str,
    *,
    usd_2027: float = 0.0,
    usd_now: float = 0.0,
    latency_ms: int = 0,
    parse_ok: bool = True,
) -> CallRecord:
    return replace(
        _rec(case, usd_2027=usd_2027, usd_now=usd_now, latency_ms=latency_ms, parse_ok=parse_ok),
        task_tag=tag,
    )


def _fake_harness(
    monkeypatch: pytest.MonkeyPatch,
    per_case: dict[str, list[CallRecord]],
    clients: list[tuple[Settings, str]],
    on_case_start: Any = None,
    cache_hits_per_case: int = 0,
) -> None:
    """Fake harness billing per_case[case] live records; captures each client's settings/mode.

    Publishes ``cache_hits_per_case`` GEMINI_CACHE_HIT events per case, as the client does.
    """
    records: list[CallRecord] = []
    monkeypatch.setattr(runner, "_corpus_digest", lambda cases: runner.PINNED_CORPUS_DIGEST)
    monkeypatch.setattr(runner, "preflight_prices", lambda settings: None)

    def fake_client(settings: Settings, *, default_cache_mode: str = "read_write") -> object:
        clients.append((settings, default_cache_mode))
        return object()

    monkeypatch.setattr(runner, "GeminiClient", fake_client)
    monkeypatch.setattr(runner, "reset_process_counters", lambda: records.clear())
    monkeypatch.setattr(runner, "process_call_records", lambda: list(records))
    monkeypatch.setattr(runner, "set_call_context", lambda *, case_key: None)

    def fake_measure(cases: list[GoldenCase], client: object, settings: object, **kw: Any):  # type: ignore[no-untyped-def]
        probe = kw["cost_probe"]
        for case in cases:
            probe()
            if on_case_start is not None:
                on_case_start(case.paper_id)
            records.extend(per_case[case.paper_id])
            for _ in range(cache_hits_per_case):
                bus.publish(EventType.GEMINI_CACHE_HIT, task="t", model="m", cache_key="k")
            probe()
        return _result([_qr("1a", 1, 1) for _ in cases], [_er(c.paper_id, "1a") for c in cases])

    monkeypatch.setattr(runner, "measure_accuracy", fake_measure)


def _seed_ladder(
    out: Path,
    *,
    baseline: RunSummary,
    baseline_records: list[CallRecord] | None = None,
    aa_floor: int = 0,
) -> None:
    """A finished baseline: summary, records, A/A floor and a non-empty frozen cache."""
    runner.write_summary(baseline, out / "baseline" / "summary.json", usd_per_script_mean_now=0.0)
    (out / "baseline" / "records.jsonl").write_text(
        "".join(json.dumps(runner.asdict(r)) + "\n" for r in baseline_records or [])
    )
    (out / "aa_floor.json").write_text(json.dumps({"aa_floor": aa_floor}))
    entry = out / "cache" / "baseline" / "gemini" / "k.json"
    entry.parent.mkdir(parents=True)
    entry.write_text("{}")


def _seed_run(
    out: Path,
    label: str,
    summary: RunSummary,
    *,
    overrides: dict[str, object] | None = None,
    live_tags: list[str] | None = None,
    passed: bool = True,
) -> None:
    """A screened run to stack on: its summary (with recorded overrides) and verdict."""
    runner.write_summary(
        summary,
        out / label / "summary.json",
        usd_per_script_mean_now=0.0,
        extra={"overrides": overrides or {}, "live_tags": live_tags or list(_LIVE)},
    )
    (out / label / "verdict.json").write_text(json.dumps({"passed": passed}))


def _stub_run_config(
    monkeypatch: pytest.MonkeyPatch, candidate: RunSummary, seen: list[dict[str, Any]]
) -> None:
    def fake(label: str, overrides: dict[str, object], **kw: Any) -> RunSummary:
        seen.append({"label": label, "overrides": dict(overrides), **kw})
        if kw.get("on_checks_passed") is not None:
            kw["on_checks_passed"]()
        runner.write_summary(
            candidate,
            kw["out_dir"] / label / "summary.json",
            usd_per_script_mean_now=0.0,
            extra={"overrides": dict(overrides), **(kw.get("summary_extra") or {})},
        )
        return candidate

    monkeypatch.setattr(runner, "run_config", fake)


def test_screen_judges_latency_against_rung0_baseline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _seed_ladder(tmp_path, baseline=_summary(latency_p95_ms=1000.0))
    # The stacked-on run is slower than rung 0: 2x of it would be 6000 ms.
    _seed_run(tmp_path, "lever1", _summary(latency_p95_ms=3000.0))
    seen: list[dict[str, Any]] = []
    # 2500 ms: within 2x the --against run, past 2x the rung-0 baseline.
    _stub_run_config(monkeypatch, _summary(latency_p95_ms=2500.0), seen)
    verdict = runner.run_screen("lever2", {}, out_dir=tmp_path, against="lever1")
    assert not verdict.passed
    assert any("2.0x original 1000.0ms" in r for r in verdict.reasons)


def test_screen_stacks_set_on_against_overrides(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _seed_ladder(tmp_path, baseline=_summary())
    _seed_run(tmp_path, "lever1", _summary(), overrides={"gemini.a": 1, "gemini.b": 2})
    seen: list[dict[str, Any]] = []
    _stub_run_config(monkeypatch, _summary(), seen)
    runner.run_screen(
        "lever2",
        {"gemini.b": 3, "gemini.c": "x"},
        out_dir=tmp_path,
        against="lever1",
        lever="cheaper c",
    )
    combined = {"gemini.a": 1, "gemini.b": 3, "gemini.c": "x"}
    assert seen[0]["overrides"] == combined
    verdict = json.loads((tmp_path / "lever2" / "verdict.json").read_text())
    assert verdict["overrides"] == combined
    assert verdict["against"] == "lever1"
    assert verdict["set"] == {"gemini.b": 3, "gemini.c": "x"}
    summary = json.loads((tmp_path / "lever2" / "summary.json").read_text())
    assert summary["overrides"] == combined
    assert summary["against"] == "lever1"


def test_baseline_runs_fresh_read_write_cache_then_bypass_aa(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    clients: list[tuple[Settings, str]] = []
    _fake_harness(monkeypatch, {"a": [_tagged("a", "extraction", usd_now=0.1)]}, clients)
    floor = runner.run_baseline(
        out_dir=tmp_path, cases=[_case("a")], settings=Settings(), max_run_usd={"gemini": 1.0}
    )
    assert floor == 0
    (base_settings, base_mode), (aa_settings, aa_mode) = clients
    assert base_mode == "read_write"
    assert base_settings.paths.cache_dir == tmp_path / "cache" / "baseline"
    assert aa_mode == "bypass"
    assert aa_settings.paths.cache_dir != base_settings.paths.cache_dir
    for s in (base_settings, aa_settings):
        assert s.gemini.cache_forget_enabled is False
        assert s.gemini.cache_mode_for == {}
    assert json.loads((tmp_path / "aa_floor.json").read_text()) == {"aa_floor": 0}


def test_baseline_refuses_non_empty_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    clients: list[tuple[Settings, str]] = []
    _fake_harness(monkeypatch, {"a": []}, clients)
    stale = tmp_path / "cache" / "baseline" / "gemini" / "old.json"
    stale.parent.mkdir(parents=True)
    stale.write_text("{}")
    with pytest.raises(RuntimeError, match="not empty") as exc:
        runner.run_baseline(
            out_dir=tmp_path, cases=[_case("a")], settings=Settings(), max_run_usd={"gemini": 1.0}
        )
    assert "--restart-baseline" in str(exc.value)
    assert "out-dir" not in str(exc.value)
    assert clients == []


def test_screen_copies_baseline_cache_and_bypasses_live_tags(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _seed_ladder(tmp_path, baseline=_summary(scored_parts=1, id_match_rate=0.9))
    clients: list[tuple[Settings, str]] = []
    _fake_harness(monkeypatch, {"a": [_tagged("a", "correction")]}, clients)
    runner.run_screen(
        "lever1",
        {},
        out_dir=tmp_path,
        cases=[_case("a")],
        settings=Settings(),
        max_run_usd={"gemini": 1.0},
    )
    ((settings, mode),) = clients
    assert mode == "read_write"
    assert settings.paths.cache_dir == tmp_path / "cache" / "lever1"
    assert (tmp_path / "cache" / "lever1" / "gemini" / "k.json").is_file()
    assert settings.gemini.cache_forget_enabled is False
    assert settings.gemini.cache_mode_for == {
        "correction": "bypass",
        "correction_borderline": "bypass",
        "escalation": "bypass",
        "correction_prefix_cache": "bypass",
    }
    tags = ["correction", "correction_borderline", "escalation", "correction_prefix_cache"]
    assert json.loads((tmp_path / "lever1" / "summary.json").read_text())["live_tags"] == tags
    assert json.loads((tmp_path / "lever1" / "verdict.json").read_text())["live_tags"] == tags


def test_screen_honours_custom_live_tags(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _seed_ladder(tmp_path, baseline=_summary(scored_parts=1))
    clients: list[tuple[Settings, str]] = []
    _fake_harness(monkeypatch, {"a": []}, clients)
    runner.run_screen(
        "lever1",
        {},
        out_dir=tmp_path,
        live_tags=("escalation",),
        cases=[_case("a")],
        settings=Settings(),
        max_run_usd={"gemini": 1.0},
    )
    assert clients[0][0].gemini.cache_mode_for == {"escalation": "bypass"}


_LIVE = ("correction", "correction_borderline", "escalation")


def test_default_live_tags_include_prefix_cache() -> None:
    assert "correction_prefix_cache" in runner.DEFAULT_LIVE_TAGS


def _composed_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[RunSummary, list[CallRecord]]:
    """Case a: baseline extraction (frozen) + correction; the screen re-runs correction live."""
    frozen = [
        _tagged("a", "extraction", usd_2027=0.50, usd_now=0.70, latency_ms=4000),
        _tagged("a", "binding", usd_2027=0.20, usd_now=0.30, latency_ms=1000, parse_ok=False),
        _tagged("a", "correction", usd_2027=0.40, usd_now=0.60, latency_ms=2000),
        _tagged("b", "extraction", usd_2027=9.0, usd_now=9.0, latency_ms=9000),  # not in run
    ]
    live = [_tagged("a", "correction", usd_2027=0.10, usd_now=0.15, latency_ms=500)]
    clients: list[tuple[Settings, str]] = []
    _fake_harness(monkeypatch, {"a": live}, clients)
    summary = runner.run_config(
        "lever1",
        {},
        out_dir=tmp_path,
        cases=[_case("a")],
        settings=Settings(),
        max_run_usd={"gemini": 1.0},
        cache_mode="read_write",
        live_tags=_LIVE,
        frozen_upstream=frozen,
    )
    return summary, live


def test_screen_summary_includes_frozen_upstream_cost(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    summary, _ = _composed_run(monkeypatch, tmp_path)
    # live correction 0.10 + frozen extraction 0.50 + frozen binding 0.20;
    # the baseline correction record is dropped (correction is live).
    assert summary.usd_per_script_mean == pytest.approx(0.80)
    data = json.loads((tmp_path / "lever1" / "summary.json").read_text())
    assert data["usd_per_script_mean_now"] == pytest.approx(0.15 + 0.70 + 0.30)


def test_screen_summary_includes_frozen_upstream_latency(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    summary, _ = _composed_run(monkeypatch, tmp_path)
    assert summary.latency_p95_ms == 500 + 4000 + 1000
    # Validity is over the composed set: 2 of 3 parsed (the frozen binding call failed).
    assert summary.validity_rate == pytest.approx(2 / 3)


def test_spend_counts_only_live_records(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _composed_run(monkeypatch, tmp_path)
    assert json.loads((tmp_path / "spend.json").read_text()) == {"gemini": pytest.approx(0.15)}
    assert json.loads((tmp_path / "lever1" / "run_cost.json").read_text()) == {
        "gemini": pytest.approx(0.15)
    }
    lines = (tmp_path / "lever1" / "records.jsonl").read_text().splitlines()
    assert len(lines) == 1


def test_resolve_projection_takes_per_provider_max(tmp_path: Path) -> None:
    from lemely.accuracy.cost_ladder.spend import resolve_projection

    (tmp_path / "baseline").mkdir()
    (tmp_path / "baseline" / "run_cost.json").write_text(
        json.dumps({"gemini": 0.5, "anthropic": 2.0})
    )
    out = resolve_projection(tmp_path, "baseline_aa", {"gemini": 0.8, "anthropic": 1.0})
    assert out == {"gemini": 0.8, "anthropic": 2.0}
    assert resolve_projection(tmp_path, "baseline_aa", None) == {"gemini": 0.5, "anthropic": 2.0}


def test_spend_written_after_each_case(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: list[object] = []

    def snapshot(case: str) -> None:
        path = tmp_path / "spend.json"
        seen.append(json.loads(path.read_text()) if path.is_file() else None)

    clients: list[tuple[Settings, str]] = []
    _fake_harness(
        monkeypatch,
        {"a": [_bill("a", 0.25)], "b": [_bill("b", 0.5)]},
        clients,
        on_case_start=snapshot,
    )
    runner.run_config(
        "baseline",
        {},
        out_dir=tmp_path,
        cases=[_case("a"), _case("b")],
        settings=Settings(),
        max_run_usd={"gemini": 1.0},
    )
    # Case b starts after case a's spend has reached the ledger.
    assert seen == [None, {"gemini": pytest.approx(0.25)}]
    assert json.loads((tmp_path / "spend.json").read_text()) == {"gemini": pytest.approx(0.75)}


def _write_run(out: Path, label: str, *, passed: bool, usd: float, against: str) -> None:
    runner.write_summary(
        _summary(usd_per_script_mean=usd),
        out / label / "summary.json",
        usd_per_script_mean_now=usd * 2,
    )
    (out / label / "verdict.json").write_text(
        json.dumps(
            {
                "lever": label,
                "expected_saving": "10%",
                "proof": str(out / label),
                "against": against,
                "overrides": {"gemini.x": label},
                "set": {"gemini.x": label},
                "live_tags": list(_LIVE),
                "passed": passed,
                "tier": "small",
                "saving": 0.1,
                "extra_mismarks": 0,
                "allowed_extra": 0,
                "reasons": [] if passed else ["nope"],
            }
        )
    )


def test_report_follows_ladder_order_and_final_is_last_pass(tmp_path: Path) -> None:
    from lemely.accuracy.cost_ladder.report import write_report

    runner.write_summary(
        _summary(usd_per_script_mean=1.0),
        tmp_path / "baseline" / "summary.json",
        usd_per_script_mean_now=2.0,
    )
    _write_run(tmp_path, "zeta", passed=True, usd=0.7, against="baseline")
    _write_run(tmp_path, "alpha", passed=True, usd=0.6, against="zeta")
    _write_run(tmp_path, "mid", passed=False, usd=0.5, against="alpha")
    for label in ("zeta", "alpha", "mid"):
        runner.append_ladder(tmp_path, label)
    # mtimes disagree with the append order: the report must not use them.
    import os

    os.utime(tmp_path / "zeta" / "verdict.json", (9e9, 9e9))
    target = write_report(tmp_path, stop_reason="done")
    text = target.read_text()
    rows = [line for line in text.splitlines() if line.startswith("| ") and "lever" not in line]
    assert [r.split(" | ")[0][2:] for r in rows] == ["zeta", "alpha", "mid"]
    assert "stacked on" in text
    assert "| zeta | baseline |" in text
    assert "| alpha | zeta |" in text
    assert "gemini.x=alpha" in text
    # final = alpha (last PASS in ladder order), not mid (rejected) nor zeta (latest mtime).
    assert "$0.6000 vs $1.0000" in text
    assert "$1.2000 vs $2.0000" in text


def test_append_ladder_keeps_explicit_order(tmp_path: Path) -> None:
    for label in ("b", "a", "c", "a"):
        runner.append_ladder(tmp_path, label)
    assert json.loads((tmp_path / "ladder.json").read_text()) == ["b", "c", "a"]


# --- fix round 2: pinned ledger, fail-closed upstream, stacking guards ----------------------


def test_default_spend_file_is_pinned_in_the_repo() -> None:
    from lemely.accuracy.cost_ladder import spend

    path = spend.DEFAULT_SPEND_FILE
    assert path.is_absolute()
    assert path.as_posix().endswith("BUILD/accuracy-runs/cost-ladder-spend.json")
    assert (path.parents[2] / "pyproject.toml").is_file()  # repo root, not the cwd or out-dir


def test_spend_file_independent_of_out_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, _spend_file_in_tmp: Path
) -> None:
    clients: list[tuple[Settings, str]] = []
    _fake_harness(monkeypatch, {"a": [_bill("a", 0.25)]}, clients)
    for out in ("run-1", "run-2"):
        runner.run_config(
            "baseline",
            {},
            out_dir=tmp_path / out,
            cases=[_case("a")],
            settings=Settings(),
            max_run_usd={"gemini": 1.0},
        )
        assert not (tmp_path / out / "spend.json").exists()
    # A new out-dir does not reset the combined total.
    assert json.loads(_spend_file_in_tmp.read_text()) == {"gemini": pytest.approx(0.5)}
    # An explicit spend file is honoured.
    other = tmp_path / "elsewhere.json"
    runner.run_config(
        "baseline",
        {},
        out_dir=tmp_path / "run-3",
        cases=[_case("a")],
        settings=Settings(),
        max_run_usd={"gemini": 1.0},
        spend_file=other,
    )
    assert json.loads(other.read_text()) == {"gemini": pytest.approx(0.25)}


def test_restart_baseline_keeps_spend(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, _spend_file_in_tmp: Path
) -> None:
    _seed_ladder(tmp_path, baseline=_summary())
    (tmp_path / "baseline_aa").mkdir()
    (tmp_path / "baseline_aa" / "stale.txt").write_text("x")
    _spend_file_in_tmp.write_text(json.dumps({"gemini": 1.0}))
    clients: list[tuple[Settings, str]] = []
    _fake_harness(monkeypatch, {"a": [_bill("a", 0.25)]}, clients)
    runner.run_baseline(
        out_dir=tmp_path,
        cases=[_case("a")],
        settings=Settings(),
        max_run_usd={"gemini": 1.0},
        restart=True,
    )
    assert not (tmp_path / "cache" / "baseline" / "gemini" / "k.json").exists()
    assert not (tmp_path / "baseline_aa" / "stale.txt").exists()
    assert [mode for _, mode in clients] == ["read_write", "bypass"]
    # Spend is kept and added to: 1.0 before + 0.25 baseline + 0.25 A/A.
    assert json.loads(_spend_file_in_tmp.read_text()) == {"gemini": pytest.approx(1.5)}


def test_aa_only_reruns_only_the_aa_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _seed_ladder(tmp_path, baseline=_summary(mismarked_parts=frozenset({"a/1a"}), scored_parts=1))
    clients: list[tuple[Settings, str]] = []
    _fake_harness(monkeypatch, {"a": []}, clients)
    floor = runner.run_baseline(
        out_dir=tmp_path,
        cases=[_case("a")],
        settings=Settings(),
        max_run_usd={"gemini": 1.0},
        aa_only=True,
    )
    assert [mode for _, mode in clients] == ["bypass"]
    assert floor == 1  # baseline mismarked a/1a, the A/A rerun did not
    assert (tmp_path / "cache" / "baseline" / "gemini" / "k.json").is_file()  # untouched


def test_aa_only_without_baseline_is_a_clear_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    clients: list[tuple[Settings, str]] = []
    _fake_harness(monkeypatch, {"a": []}, clients)
    with pytest.raises(runner.LadderStateError, match="baseline"):
        runner.run_baseline(out_dir=tmp_path, cases=[_case("a")], aa_only=True)
    assert clients == []


def test_baseline_records_in_run_cache_hits(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    clients: list[tuple[Settings, str]] = []
    # A recovered parse failure lowers validity but leaves rung 0 complete.
    recs = [_tagged("a", "extraction"), _tagged("a", "correction", parse_ok=False)]
    _fake_harness(monkeypatch, {"a": recs}, clients, cache_hits_per_case=2)
    runner.run_baseline(
        out_dir=tmp_path, cases=[_case("a")], settings=Settings(), max_run_usd={"gemini": 1.0}
    )
    data = json.loads((tmp_path / "baseline" / "summary.json").read_text())
    assert data["in_run_cache_hits"] == 2
    assert data["cacheable_live_records"] == 1  # the unparsed call writes no entry
    assert data["cache_entries_written"] == 0  # the fake client writes none
    # The A/A rerun bypasses the cache and is not annotated.
    assert "in_run_cache_hits" not in json.loads(
        (tmp_path / "baseline_aa" / "summary.json").read_text()
    )


def test_report_header_shows_baseline_in_run_cache_hits(tmp_path: Path) -> None:
    from lemely.accuracy.cost_ladder.report import write_report

    runner.write_summary(
        _summary(),
        tmp_path / "baseline" / "summary.json",
        usd_per_script_mean_now=1.0,
        extra={"in_run_cache_hits": 3},
    )
    text = write_report(tmp_path, stop_reason="done").read_text()
    header = text.split("| lever")[0]
    assert "Baseline in-run cache hits: 3" in header


def test_lever_cannot_override_cache_discipline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    clients: list[tuple[Settings, str]] = []
    _fake_harness(monkeypatch, {"a": []}, clients)
    runner.run_config(
        "lever1",
        {"gemini.cache_forget_enabled": True, "gemini.cache_mode_for": {"extraction": "bypass"}},
        out_dir=tmp_path,
        cases=[_case("a")],
        settings=Settings(),
        max_run_usd={"gemini": 1.0},
        live_tags=("correction",),
    )
    ((settings, _),) = clients
    assert settings.gemini.cache_forget_enabled is False
    assert settings.gemini.cache_mode_for == {"correction": "bypass"}


def test_screen_fails_closed_on_upstream_live_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _seed_ladder(tmp_path, baseline=_summary(scored_parts=2))
    # An earlier PASS of the same label must not survive a failed re-screen.
    (tmp_path / "lever1").mkdir()
    (tmp_path / "lever1" / "verdict.json").write_text(json.dumps({"passed": True}))
    runner.append_ladder(tmp_path, "lever1")
    started: list[str] = []
    per_case = {
        "a": [_tagged("a", "correction", usd_now=0.1), _tagged("a", "extraction", usd_now=0.2)],
        "b": [_tagged("b", "correction", usd_now=0.1)],
    }
    clients: list[tuple[Settings, str]] = []
    _fake_harness(monkeypatch, per_case, clients, on_case_start=started.append)
    with pytest.raises(runner.UpstreamNotFrozen) as exc:
        runner.run_screen(
            "lever1",
            {},
            out_dir=tmp_path,
            cases=[_case("a"), _case("b")],
            settings=Settings(),
            max_run_usd={"gemini": 1.0},
        )
    message = str(exc.value)
    assert "extraction" in message
    assert "--live-tags" in message
    assert started == ["a"]  # stopped after the first case that showed the call
    assert not (tmp_path / "lever1" / "verdict.json").exists()
    assert json.loads((tmp_path / "ladder.json").read_text()) == []
    # Its live spend is still booked.
    assert json.loads((tmp_path / "spend.json").read_text()) == {"gemini": pytest.approx(0.3)}


def test_live_tags_inherit_through_stacking(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _seed_ladder(tmp_path, baseline=_summary(scored_parts=1))
    _seed_run(tmp_path, "lever1", _summary(scored_parts=1), live_tags=["correction", "extraction"])
    clients: list[tuple[Settings, str]] = []
    _fake_harness(monkeypatch, {"a": [_tagged("a", "extraction")]}, clients)
    runner.run_screen(
        "lever2",
        {},
        out_dir=tmp_path,
        against="lever1",
        live_tags=("escalation",),
        cases=[_case("a")],
        settings=Settings(),
        max_run_usd={"gemini": 1.0},
    )
    expected = ["escalation", "correction", "extraction"]
    assert set(clients[0][0].gemini.cache_mode_for) == set(expected)
    assert json.loads((tmp_path / "lever2" / "verdict.json").read_text())["live_tags"] == expected
    assert json.loads((tmp_path / "lever2" / "summary.json").read_text())["live_tags"] == expected


def test_stacking_on_a_reject_is_refused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _seed_ladder(tmp_path, baseline=_summary())
    _seed_run(tmp_path, "lever1", _summary(), passed=False)
    clients: list[tuple[Settings, str]] = []
    _fake_harness(monkeypatch, {"a": []}, clients)
    with pytest.raises(runner.LadderStateError, match="lever1"):
        runner.run_screen(
            "lever2",
            {},
            out_dir=tmp_path,
            against="lever1",
            cases=[_case("a")],
            settings=Settings(),
            max_run_usd={"gemini": 1.0},
        )
    assert clients == []
    assert not (tmp_path / "cache" / "lever2").exists()
    assert not (tmp_path / "lever2").exists()


@pytest.mark.parametrize("missing", ["against", "aa_floor"])
def test_missing_ladder_state_is_a_clear_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, missing: str
) -> None:
    _seed_ladder(tmp_path, baseline=_summary())
    if missing == "aa_floor":
        (tmp_path / "aa_floor.json").unlink()
        against = "baseline"
    else:
        against = "nope"
    clients: list[tuple[Settings, str]] = []
    _fake_harness(monkeypatch, {"a": []}, clients)
    with pytest.raises(runner.LadderStateError) as exc:
        runner.run_screen(
            "lever2",
            {},
            out_dir=tmp_path,
            against=against,
            cases=[_case("a")],
            settings=Settings(),
            max_run_usd={"gemini": 1.0},
        )
    assert ("nope" if missing == "against" else "aa_floor.json") in str(exc.value)
    assert clients == []


def test_refused_screen_touches_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, _spend_file_in_tmp: Path
) -> None:
    _seed_ladder(tmp_path, baseline=_summary())
    _spend_file_in_tmp.write_text(json.dumps({"gemini": 5.9}))
    clients: list[tuple[Settings, str]] = []
    _fake_harness(monkeypatch, {"a": []}, clients)
    with pytest.raises(SpendCapError):
        runner.run_screen(
            "lever1",
            {},
            out_dir=tmp_path,
            cases=[_case("a")],
            settings=Settings(),
            max_run_usd={"gemini": 1.0},
        )
    assert clients == []
    assert not (tmp_path / "cache" / "lever1").exists()
    assert not (tmp_path / "lever1").exists()
    assert not (tmp_path / "ladder.json").exists()


def test_results_json_has_case_keyed_question_results(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    clients: list[tuple[Settings, str]] = []
    _fake_harness(monkeypatch, {"a": [], "b": []}, clients)
    variant = GoldenCase(
        paper_id="b",
        fixture_variant="scan2",
        mark_scheme=None,  # type: ignore[arg-type]
        ground_truth={},
    )

    def fake_measure(cases: list[GoldenCase], client: object, settings: object, **kw: Any):  # type: ignore[no-untyped-def]
        qrs = [_qr("1a", 1, 2), _qr("1b", 0, 0, scored=False), _qr("2", 3, 3)]
        ers = [_er("a", "1a"), _er("a", "1b"), _er("a", "1c", outcome="excluded")]
        ers.append(_er("b", "2").model_copy(update={"fixture_variant": "scan2"}))
        return _result(qrs, ers)

    monkeypatch.setattr(runner, "measure_accuracy", fake_measure)
    runner.run_config(
        "baseline",
        {},
        out_dir=tmp_path,
        cases=[_case("a"), variant],
        settings=Settings(),
        max_run_usd={"gemini": 1.0},
    )
    data = json.loads((tmp_path / "baseline" / "results.json").read_text())
    picked = [
        {k: q[k] for k in ("case_key", "question_id", "scored", "predicted_marks", "truth_marks")}
        for q in data["question_results"]
    ]
    assert picked == [
        {
            "case_key": "a",
            "question_id": "1a",
            "scored": True,
            "predicted_marks": 1,
            "truth_marks": 2,
        },
        {
            "case_key": "a",
            "question_id": "1b",
            "scored": False,
            "predicted_marks": 0,
            "truth_marks": 0,
        },
        {
            "case_key": runner.case_key(variant),
            "question_id": "2",
            "scored": True,
            "predicted_marks": 3,
            "truth_marks": 3,
        },
    ]
    # Existing fields are kept.
    assert data["question_results"][0]["confidence_score"] == 0.9
    assert {"metrics", "funnel", "manifest"} <= set(data)


# --- fix round 4: complete-baseline guard, safe restart, ladder integrity -------------------


def _cap_baseline(out: Path) -> None:
    """Rewrite the seeded baseline summary as one stopped by the spend cap."""
    runner.write_summary(
        _summary(incomplete=("b (spend cap)",)),
        out / "baseline" / "summary.json",
        usd_per_script_mean_now=0.0,
        extra={"stopped_by_spend_cap": "gemini: cap reached"},
    )


def test_capped_baseline_refuses_aa_only_and_screen(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _seed_ladder(tmp_path, baseline=_summary())
    _cap_baseline(tmp_path)
    clients: list[tuple[Settings, str]] = []
    _fake_harness(monkeypatch, {"a": []}, clients)
    kwargs: dict[str, Any] = {
        "cases": [_case("a")],
        "settings": Settings(),
        "max_run_usd": {"gemini": 1.0},
    }
    with pytest.raises(runner.LadderStateError, match="--restart-baseline"):
        runner.run_baseline(out_dir=tmp_path, aa_only=True, **kwargs)
    with pytest.raises(runner.LadderStateError, match="--restart-baseline"):
        runner.run_screen("lever1", {}, out_dir=tmp_path, **kwargs)
    assert clients == []
    assert not (tmp_path / "cache" / "lever1").exists()


@pytest.mark.parametrize("capped", ["baseline", "baseline_aa"])
def test_incomplete_baseline_or_aa_writes_no_floor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capped: str
) -> None:
    labels: list[str] = []

    def fake(label: str, overrides: dict[str, object], **kw: Any) -> RunSummary:
        labels.append(label)
        incomplete = ("a",) if label == capped else ()
        s = _summary(incomplete=incomplete)
        runner.write_summary(s, kw["out_dir"] / label / "summary.json", usd_per_script_mean_now=0.0)
        (kw["out_dir"] / label / "records.jsonl").write_text("")
        return s

    monkeypatch.setattr(runner, "run_config", fake)
    with pytest.raises(runner.LadderStateError, match="--restart-baseline"):
        runner.run_baseline(out_dir=tmp_path, cases=[_case("a")])
    assert not (tmp_path / "aa_floor.json").exists()
    # An incomplete baseline is caught before the A/A run spends anything.
    assert labels == (["baseline"] if capped == "baseline" else ["baseline", "baseline_aa"])


def test_restart_archives_screens_and_needs_no_max_run_usd(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _seed_ladder(tmp_path, baseline=_summary())
    (tmp_path / "baseline_aa").mkdir()
    (tmp_path / "baseline_aa" / "run_cost.json").write_text(json.dumps({"gemini": 0.25}))
    _seed_run(tmp_path, "lever1", _summary())
    runner.append_ladder(tmp_path, "lever1")
    (tmp_path / "cache" / "lever1" / "gemini").mkdir(parents=True)
    clients: list[tuple[Settings, str]] = []
    _fake_harness(monkeypatch, {"a": [_bill("a", 0.25)]}, clients)
    runner.run_baseline(out_dir=tmp_path, cases=[_case("a")], settings=Settings(), restart=True)
    (archive,) = (tmp_path / "archive").iterdir()
    assert archive.name.startswith("restart-")
    assert (archive / "ladder.json").is_file()
    assert (archive / "lever1" / "verdict.json").is_file()
    assert not (tmp_path / "lever1").exists()
    assert not (tmp_path / "ladder.json").exists()
    assert not (tmp_path / "cache" / "lever1").exists()
    assert [mode for _, mode in clients] == ["read_write", "bypass"]


def test_restart_refused_by_checks_deletes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, _spend_file_in_tmp: Path
) -> None:
    _seed_ladder(tmp_path, baseline=_summary())
    _seed_run(tmp_path, "lever1", _summary())
    runner.append_ladder(tmp_path, "lever1")
    _spend_file_in_tmp.write_text(json.dumps({"gemini": 5.9}))
    clients: list[tuple[Settings, str]] = []
    _fake_harness(monkeypatch, {"a": []}, clients)
    with pytest.raises(SpendCapError):
        runner.run_baseline(
            out_dir=tmp_path,
            cases=[_case("a")],
            settings=Settings(),
            max_run_usd={"gemini": 1.0},
            restart=True,
        )
    assert (tmp_path / "cache" / "baseline" / "gemini" / "k.json").is_file()
    assert (tmp_path / "baseline" / "summary.json").is_file()
    assert (tmp_path / "lever1" / "verdict.json").is_file()
    assert (tmp_path / "ladder.json").is_file()
    assert not (tmp_path / "archive").exists()


def test_aa_only_refused_while_ladder_has_rows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _seed_ladder(tmp_path, baseline=_summary())
    runner.append_ladder(tmp_path, "lever1")
    clients: list[tuple[Settings, str]] = []
    _fake_harness(monkeypatch, {"a": []}, clients)
    with pytest.raises(runner.LadderStateError, match="--restart-baseline"):
        runner.run_baseline(out_dir=tmp_path, cases=[_case("a")], settings=Settings(), aa_only=True)
    assert clients == []


def test_screen_against_itself_is_refused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _seed_ladder(tmp_path, baseline=_summary())
    _seed_run(tmp_path, "lever1", _summary())
    clients: list[tuple[Settings, str]] = []
    _fake_harness(monkeypatch, {"a": []}, clients)
    with pytest.raises(runner.LadderStateError, match="itself"):
        runner.run_screen("lever1", {}, out_dir=tmp_path, against="lever1", cases=[_case("a")])
    assert clients == []


def test_rescreen_of_a_stacked_on_label_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _seed_ladder(tmp_path, baseline=_summary())
    _seed_run(tmp_path, "lever1", _summary())
    _seed_run(tmp_path, "lever2", _summary())
    verdict2 = tmp_path / "lever2" / "verdict.json"
    verdict2.write_text(json.dumps({"passed": True, "against": "lever1"}))
    runner.append_ladder(tmp_path, "lever1")
    runner.append_ladder(tmp_path, "lever2")
    clients: list[tuple[Settings, str]] = []
    _fake_harness(monkeypatch, {"a": []}, clients)
    with pytest.raises(runner.LadderStateError, match="lever2"):
        runner.run_screen("lever1", {}, out_dir=tmp_path, cases=[_case("a")])
    assert clients == []
    assert (tmp_path / "lever1" / "verdict.json").is_file()


def test_post_run_check_catches_uncased_upstream_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _seed_ladder(tmp_path, baseline=_summary(scored_parts=2))
    started: list[str] = []
    uncased = replace(_tagged("a", "binding", usd_now=0.05), case_key=None)
    per_case = {"a": [_tagged("a", "correction"), uncased], "b": [_tagged("b", "correction")]}
    clients: list[tuple[Settings, str]] = []
    _fake_harness(monkeypatch, per_case, clients, on_case_start=started.append)
    with pytest.raises(runner.UpstreamNotFrozen, match="binding"):
        runner.run_screen(
            "lever1",
            {},
            out_dir=tmp_path,
            cases=[_case("a"), _case("b")],
            settings=Settings(),
            max_run_usd={"gemini": 1.0},
        )
    assert started == ["a", "b"]  # the per-case guard cannot see it; the post-run check does
    assert not (tmp_path / "lever1" / "verdict.json").exists()
    assert json.loads((tmp_path / "spend.json").read_text()) == {"gemini": pytest.approx(0.05)}


def test_report_without_baseline_is_a_clear_error(tmp_path: Path) -> None:
    from lemely.accuracy.cost_ladder.report import write_report

    with pytest.raises(runner.LadderStateError, match="baseline"):
        write_report(tmp_path, stop_reason="x")


# --- fix round 5: parse failures are validity, not completeness; $0 resummarise ------------


def test_parse_failure_with_all_leaves_scored_is_complete() -> None:
    qrs = [_qr("1a", 1, 1), _qr("1b", 2, 2)]
    ers = [_er("p1", "1a"), _er("p1", "1b")]
    recs = [_rec("p1"), _rec("p1", parse_ok=False), _rec("p1"), _rec("p1")]
    s = summarise(_result(qrs, ers), recs)
    assert s.incomplete == ()
    assert s.validity_rate == 0.75
    assert s.scored_parts == 2


def test_case_with_an_unmarked_leaf_is_still_incomplete() -> None:
    qrs = [_qr("1a", 1, 1)]
    ers = [_er("p1", "1a"), _er("p1", "1b", outcome="unmatched")]
    s = summarise(_result(qrs, ers), [_rec("p1")])
    assert s.incomplete == ("p1",)


def test_expected_case_with_no_marking_is_incomplete() -> None:
    s = summarise(
        _result([_qr("1a", 1, 1)], [_er("p1", "1a")]), [_rec("p1")], expected_cases=["p1", "p9"]
    )
    assert s.incomplete == ("p9 (no marking)",)


def test_unpriced_record_still_marks_case_incomplete() -> None:
    rec = replace(_rec("p1", usd_2027=0.1), usd_2027=float("nan"), model="gemini-9-x")
    s = summarise(_result([_qr("1a", 1, 1)], [_er("p1", "1a")]), [rec])
    assert s.incomplete == ("p1 (unpriced model gemini-9-x)",)


def test_results_json_records_cases_and_unmarked_leaves(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    clients: list[tuple[Settings, str]] = []
    _fake_harness(monkeypatch, {"a": [], "b": []}, clients)

    def fake_measure(cases: list[GoldenCase], client: object, settings: object, **kw: Any):  # type: ignore[no-untyped-def]
        qrs = [_qr("1a", 1, 1)]
        ers = [
            _er("a", "1a"),
            _er("a", "1b", outcome="excluded"),
            _er("b", "1", outcome="unmatched"),
        ]
        return _result(qrs, ers)

    monkeypatch.setattr(runner, "measure_accuracy", fake_measure)
    runner.run_config(
        "baseline",
        {},
        out_dir=tmp_path,
        cases=[_case("a"), _case("b")],
        settings=Settings(),
        max_run_usd={"gemini": 1.0},
    )
    data = json.loads((tmp_path / "baseline" / "results.json").read_text())
    assert data["case_keys"] == ["a", "b"]
    # Stored so resummarise keys a failed marking on its source, not on the flags.
    assert "marker_source" in data["question_results"][0]
    assert data["unmarked_leaves"] == [
        {"case_key": "a", "question_id": "1b", "outcome": "excluded"},
        {"case_key": "b", "question_id": "1", "outcome": "unmatched"},
    ]


def _boom(*a: object, **k: object) -> None:
    raise AssertionError("resummarise must not call the model or build a client")


def test_resummarise_recomputes_baseline_at_zero_cost(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, _spend_file_in_tmp: Path
) -> None:
    clients: list[tuple[Settings, str]] = []
    recs = [
        _tagged("a", "extraction", usd_2027=0.2, usd_now=0.3, parse_ok=False),
        _tagged("a", "extraction", usd_2027=0.2, usd_now=0.3),
    ]
    _fake_harness(monkeypatch, {"a": recs}, clients, cache_hits_per_case=1)
    runner.run_baseline(
        out_dir=tmp_path, cases=[_case("a")], settings=Settings(), max_run_usd={"gemini": 1.0}
    )
    path = tmp_path / "baseline" / "summary.json"
    old = json.loads(path.read_text())
    # Simulate a summary written under the old rule (parse failure -> incomplete).
    path.write_text(json.dumps({**old, "incomplete": ["a"], "usd_per_script_mean": 99.0}))
    spend_before = _spend_file_in_tmp.read_text()
    monkeypatch.setattr(runner, "GeminiClient", _boom)
    monkeypatch.setattr(runner, "measure_accuracy", _boom)

    summary = runner.resummarise("baseline", out_dir=tmp_path)

    assert summary.incomplete == ()
    assert summary.usd_per_script_mean == pytest.approx(0.4)
    assert summary.validity_rate == 0.5
    new = json.loads(path.read_text())
    for kept in (
        "in_run_cache_hits",
        "cache_entries_written",
        "cacheable_live_records",
        "overrides",
        "live_tags",
        "cache_mode",
        "cache_hits",
    ):
        assert new[kept] == old[kept]
    assert new["resummarised"]["incomplete_before"] == ["a"]
    assert _spend_file_in_tmp.read_text() == spend_before


def test_aa_only_works_after_resummarised_baseline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    clients: list[tuple[Settings, str]] = []
    _fake_harness(monkeypatch, {"a": [_tagged("a", "extraction")]}, clients)
    runner.run_baseline(
        out_dir=tmp_path, cases=[_case("a")], settings=Settings(), max_run_usd={"gemini": 1.0}
    )
    path = tmp_path / "baseline" / "summary.json"
    path.write_text(json.dumps({**json.loads(path.read_text()), "incomplete": ["a"]}))
    kwargs: dict[str, Any] = {"cases": [_case("a")], "settings": Settings(), "aa_only": True}
    with pytest.raises(runner.LadderStateError, match="--restart-baseline"):
        runner.run_baseline(out_dir=tmp_path, **kwargs)
    runner.resummarise("baseline", out_dir=tmp_path)
    assert runner.run_baseline(out_dir=tmp_path, **kwargs) == 0
    assert [mode for _, mode in clients] == ["read_write", "bypass", "bypass"]


def test_resummarise_screen_keeps_frozen_upstream_composition(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    frozen = [
        _tagged("a", "extraction", usd_2027=0.50, latency_ms=4000),
        _tagged("a", "correction", usd_2027=0.40, latency_ms=2000),
    ]
    _seed_ladder(tmp_path, baseline=_summary(scored_parts=1), baseline_records=frozen)
    clients: list[tuple[Settings, str]] = []
    live = [_tagged("a", "correction", usd_2027=0.10, latency_ms=500)]
    _fake_harness(monkeypatch, {"a": live}, clients)
    first = runner.run_screen(
        "lever1",
        {},
        out_dir=tmp_path,
        cases=[_case("a")],
        settings=Settings(),
        max_run_usd={"gemini": 1.0},
    )
    assert first is not None
    path = tmp_path / "lever1" / "summary.json"
    path.write_text(json.dumps({**json.loads(path.read_text()), "usd_per_script_mean": 99.0}))
    # A judged screen cannot be resummarised (its verdict would no longer match);
    # this exercises the composition on a screen whose verdict was never written.
    (tmp_path / "lever1" / "verdict.json").unlink()
    summary = runner.resummarise("lever1", out_dir=tmp_path)
    assert summary.usd_per_script_mean == pytest.approx(0.60)  # live 0.10 + frozen extraction 0.50
    assert summary.latency_p95_ms == 4500
    data = json.loads(path.read_text())
    assert data["against"] == "baseline"
    assert data["frozen_upstream"] is True


def test_resummarise_refuses_unattributable_unmarked_leaves(tmp_path: Path) -> None:
    run = tmp_path / "baseline"
    run.mkdir()
    runner.write_summary(_summary(), run / "summary.json", usd_per_script_mean_now=0.0)
    (run / "records.jsonl").write_text("")
    # An older results.json: no case_keys / unmarked_leaves, and 3 leaves but 2 results.
    qr = {
        "case_key": "a",
        "question_id": "1a",
        "question_type": "theory",
        "predicted_marks": 1,
        "truth_marks": 1,
        "confidence_score": 0.9,
        "needs_teacher_review": False,
        "scored": True,
    }
    (run / "results.json").write_text(
        json.dumps(
            {
                "metrics": {"id_match_rate": 1.0},
                "funnel": {"leaves": 3, "extracted": 3, "matched": 2, "marked": 2},
                "question_results": [qr, {**qr, "question_id": "1b"}],
            }
        )
    )
    with pytest.raises(runner.LadderStateError, match="unmarked"):
        runner.resummarise("baseline", out_dir=tmp_path)


def test_resummarise_of_missing_run_is_a_clear_error(tmp_path: Path) -> None:
    with pytest.raises(runner.LadderStateError, match=r"results\.json"):
        runner.resummarise("nope", out_dir=tmp_path)


# --- fix round 6: failed marking is a shortfall; resummarise cannot rewrite judged history ---


@pytest.mark.parametrize("source", ["missing", "dropped"])
def test_failed_marking_call_makes_case_incomplete(source: str) -> None:
    # The call failed to parse AND produced no usable marking: correction_ai builds a
    # "missing" (or, for extraction, "dropped") leaf that the harness counts as
    # marked, so the funnel shows no shortfall. The case is still incomplete.
    failed = _qr("1b", 0, 2, scored=False, needs_teacher_review=True, marker_source=source)
    qrs = [_qr("1a", 1, 1, marker_source="ai"), failed, _qr("1a", 1, 1, marker_source="ai")]
    ers = [_er("p1", "1a"), _er("p1", "1b", outcome="abstain"), _er("p2", "1a")]
    recs = [_rec("p1"), _rec("p1", parse_ok=False), _rec("p2")]
    s = summarise(_result(qrs, ers), recs)
    assert s.incomplete == ("p1 (marking failed)",)
    assert s.scored_parts == 2


_BLANK = _BLANK_ANSWER_REVIEW_REASON


@pytest.mark.parametrize(
    ("review", "reason"),
    [(False, _BLANK), (True, f"{_BLANK}; binding unverified")],
    ids=["unflagged", "flagged-by-binder"],
)
def test_blank_answer_leaf_keeps_case_complete(review: bool, reason: str) -> None:
    # A blank is unscored, and the binder may flag it for review after it is built
    # ("unverified" binding). It is a real marking either way: the case is complete.
    blank = _qr(
        "1b",
        0,
        2,
        scored=False,
        needs_teacher_review=review,
        marker_source="blank",
        review_reason=reason,
    )
    qrs = [_qr("1a", 1, 1, marker_source="ai"), blank]
    ers = [_er("p1", "1a"), _er("p1", "1b", outcome="abstain")]
    s = summarise(_result(qrs, ers), [_rec("p1")])
    assert s.incomplete == ()
    assert s.scored_parts == 1


@pytest.mark.parametrize(
    ("reason", "incomplete"),
    [
        (f"{_BLANK}; binding unverified", ()),
        ("AI marking failed: boom", ("p1 (marking failed)",)),
        (None, ("p1 (marking failed)",)),
    ],
    ids=["flagged-blank", "failed-call", "no-reason"],
)
def test_without_marker_source_the_review_reason_decides(
    reason: str | None, incomplete: tuple[str, ...]
) -> None:
    # A QuestionResult with no marker_source (built before it was recorded) falls
    # back to: unscored, flagged, and not a blank by its review reason.
    leaf = _qr("1b", 0, 2, scored=False, needs_teacher_review=True, review_reason=reason)
    s = summarise(_result([_qr("1a", 1, 1), leaf], [_er("p1", "1a"), _er("p1", "1b")]), [])
    assert s.incomplete == incomplete


def _stored_qr(case: str, qid: str, **kw: object) -> dict[str, object]:
    return {
        "case_key": case,
        "question_id": qid,
        "question_type": "theory",
        "predicted_marks": 1,
        "truth_marks": 1,
        "confidence_score": 0.9,
        "needs_teacher_review": False,
        "scored": True,
        **kw,
    }


def _stored_run(
    out: Path,
    label: str,
    question_results: list[dict[str, object]],
    *,
    records: list[CallRecord] | None = None,
    **results: object,
) -> Path:
    """A finished run on disk (summary, records, results.json); returns its summary path."""
    run = out / label
    run.mkdir(parents=True, exist_ok=True)
    runner.write_summary(_summary(), run / "summary.json", usd_per_script_mean_now=0.0)
    (run / "records.jsonl").write_text(
        "".join(json.dumps(runner.asdict(r)) + "\n" for r in records or [])
    )
    payload: dict[str, object] = {
        "metrics": {"id_match_rate": 1.0},
        "case_keys": sorted({str(q["case_key"]) for q in question_results}),
        "unmarked_leaves": [],
        "question_results": question_results,
        **results,
    }
    (run / "results.json").write_text(json.dumps(payload))
    return run / "summary.json"


def test_resummarise_counts_a_failed_marking_leaf_as_incomplete(tmp_path: Path) -> None:
    _stored_run(
        tmp_path,
        "baseline",
        [
            _stored_qr("a", "1a", marker_source="ai"),
            _stored_qr("a", "1b", scored=False, needs_teacher_review=True, marker_source="missing"),
            _stored_qr("b", "1a", scored=False, needs_teacher_review=False, marker_source="blank"),
            _stored_qr("c", "1a", marker_source="ai"),
            _stored_qr(
                "d",
                "1a",
                scored=False,
                needs_teacher_review=True,
                marker_source="blank",
                review_reason=f"{_BLANK}; binding unverified",
            ),
            _stored_qr("e", "1a", scored=False, needs_teacher_review=True, marker_source="dropped"),
        ],
        records=[_rec("a", parse_ok=False), _rec("a"), _rec("b"), _rec("c", parse_ok=False)],
    )
    summary = runner.resummarise("baseline", out_dir=tmp_path)
    # a: parse failure + missing leaf -> incomplete; b: blank -> complete;
    # c: recovered parse failure, all leaves marked -> complete; d: blank the binder
    # flagged -> complete; e: dropped leaf -> incomplete.
    assert summary.incomplete == ("a (marking failed)", "e (marking failed)")
    assert summary.validity_rate == 0.5


def test_resummarise_old_format_counts_a_failed_marking_leaf(tmp_path: Path) -> None:
    # No case_keys / unmarked_leaves (older results.json), funnel with no shortfall.
    path = _stored_run(
        tmp_path,
        "baseline",
        [
            _stored_qr(
                "a",
                "1a",
                scored=False,
                needs_teacher_review=True,
                review_reason="AI marking failed: boom",
            ),
            _stored_qr("b", "1a"),
            _stored_qr(
                "c",
                "1a",
                scored=False,
                needs_teacher_review=True,
                review_reason=f"{_BLANK}; binding unverified",
            ),
        ],
        records=[_rec("a"), _rec("b"), _rec("c")],
    )
    results = path.parent / "results.json"
    data = json.loads(results.read_text())
    del data["case_keys"], data["unmarked_leaves"]
    data["funnel"] = {"leaves": 3, "extracted": 3, "matched": 3, "marked": 3}
    results.write_text(json.dumps(data))
    # No marker_source stored: the review reason tells the flagged blank (c) apart.
    assert runner.resummarise("baseline", out_dir=tmp_path).incomplete == ("a (marking failed)",)


@pytest.mark.parametrize(
    "bad",
    [["a"], [{"question_id": "1a"}], [{"case_key": 3}], "a"],
    ids=["bare-string", "no-case-key", "non-string-key", "not-a-list"],
)
def test_resummarise_rejects_malformed_unmarked_leaves(tmp_path: Path, bad: object) -> None:
    _stored_run(tmp_path, "baseline", [_stored_qr("a", "1a")], unmarked_leaves=bad)
    with pytest.raises(runner.LadderStateError, match="unmarked_leaves"):
        runner.resummarise("baseline", out_dir=tmp_path)


@pytest.mark.parametrize("label", ["baseline", "baseline_aa"])
def test_resummarise_of_baseline_refused_while_ladder_has_rows(tmp_path: Path, label: str) -> None:
    path = _stored_run(tmp_path, label, [_stored_qr("a", "1a")], records=[_rec("a")])
    before = path.read_text()
    runner.append_ladder(tmp_path, "lever1")
    with pytest.raises(runner.LadderStateError, match="--restart-baseline"):
        runner.resummarise(label, out_dir=tmp_path)
    assert path.read_text() == before


def test_resummarise_of_a_judged_screen_is_refused(tmp_path: Path) -> None:
    path = _stored_run(tmp_path, "lever1", [_stored_qr("a", "1a")], records=[_rec("a")])
    (tmp_path / "lever1" / "verdict.json").write_text(json.dumps({"passed": True}))
    before = path.read_text()
    with pytest.raises(runner.LadderStateError, match=r"verdict\.json"):
        runner.resummarise("lever1", out_dir=tmp_path)
    assert path.read_text() == before


# The marker_source decides whenever it is present, even where the review-reason
# fallback would disagree: a blank flagged under another reason stays complete, and
# a missing leaf is a failed marking even if it was never flagged.
_SOURCE_DECIDES = [
    ("blank", True, "binding unverified", ()),
    ("missing", False, None, ("p1 (marking failed)",)),
]


@pytest.mark.parametrize(("source", "review", "reason", "incomplete"), _SOURCE_DECIDES)
def test_marker_source_takes_precedence_live(
    source: str, review: bool, reason: str | None, incomplete: tuple[str, ...]
) -> None:
    leaf = _qr(
        "1b",
        0,
        2,
        scored=False,
        needs_teacher_review=review,
        marker_source=source,
        review_reason=reason,
    )
    qrs = [_qr("1a", 1, 1, marker_source="ai"), leaf]
    s = summarise(_result(qrs, [_er("p1", "1a"), _er("p1", "1b")]), [])
    assert s.incomplete == incomplete


@pytest.mark.parametrize(("source", "review", "reason", "incomplete"), _SOURCE_DECIDES)
def test_marker_source_takes_precedence_stored(
    tmp_path: Path, source: str, review: bool, reason: str | None, incomplete: tuple[str, ...]
) -> None:
    leaf = _stored_qr(
        "p1",
        "1b",
        scored=False,
        needs_teacher_review=review,
        marker_source=source,
        review_reason=reason,
    )
    _stored_run(tmp_path, "baseline", [_stored_qr("p1", "1a", marker_source="ai"), leaf])
    assert runner.resummarise("baseline", out_dir=tmp_path).incomplete == incomplete


def test_run_config_records_real_client_calls_inside_its_recorder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The real record path: the client appends only because ``run_config`` opened a recorder."""
    from unittest.mock import MagicMock

    from pydantic import BaseModel

    from lemely.io.gemini import GeminiClient, process_call_records
    from tests.gemini_fakes import make_settings, mock_response

    class _Out(BaseModel):
        value: str

    monkeypatch.setattr(runner, "_corpus_digest", lambda cases: runner.PINNED_CORPUS_DIGEST)
    monkeypatch.setattr(runner, "preflight_prices", lambda settings: None)
    genai = MagicMock()
    genai.models.generate_content.return_value = mock_response(
        '{"value": "a"}', prompt=100, candidates=10, thoughts=0, cached=0
    )
    client = GeminiClient(make_settings(str(tmp_path)), _genai_client=genai)

    def fake_measure(cases: list[GoldenCase], gemini: GeminiClient, settings: object, **kw: Any):  # type: ignore[no-untyped-def]
        probe = kw["cost_probe"]
        for case in cases:
            probe()
            gemini.generate_structured(
                system_prompt="s",
                user_prompt="u",
                response_schema=_Out,
                prompt_version="1",
                model="gemini-3.8-flash",
                extra_cache_key=case.paper_id,
                cache_mode="bypass",
            )
            probe()
        return _result([_qr("1a", 1, 1) for _ in cases], [_er(c.paper_id, "1a") for c in cases])

    monkeypatch.setattr(runner, "measure_accuracy", fake_measure)
    runner.run_config(
        "baseline",
        {},
        out_dir=tmp_path,
        cases=[_case("a"), _case("b")],
        settings=Settings(),
        client=client,
        max_run_usd={"gemini": 1.0},
    )
    lines = (tmp_path / "baseline" / "records.jsonl").read_text().splitlines()
    assert [json.loads(line)["case_key"] for line in lines] == ["a", "b"]
    # The recorder closed with the run: the process keeps nothing afterwards.
    assert process_call_records() == []


def test_default_gemini_cap_is_six_dollars() -> None:
    assert SpendCaps().gemini_usd == 6.00
    assert SpendCaps().anthropic_usd == 40.00


def test_rescreen_refused_when_a_ladder_row_has_no_verdict(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A row missing verdict.json cannot show it does not stack on the label: refuse."""
    _seed_ladder(tmp_path, baseline=_summary())
    _seed_run(tmp_path, "lever1", _summary())
    _seed_run(tmp_path, "lever2", _summary())
    runner.append_ladder(tmp_path, "lever1")
    runner.append_ladder(tmp_path, "lever2")
    (tmp_path / "lever2" / "verdict.json").unlink()
    clients: list[tuple[Settings, str]] = []
    _fake_harness(monkeypatch, {"a": []}, clients)
    with pytest.raises(runner.LadderStateError, match="lever2"):
        runner.run_screen("lever1", {}, out_dir=tmp_path, cases=[_case("a")])
    assert clients == []
    assert (tmp_path / "lever1" / "verdict.json").is_file()


def test_script_maps_file_not_found_to_exit_2(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from scripts import cost_ladder as script

    def missing(out_dir: Path, *, stop_reason: str) -> Path:
        raise FileNotFoundError(f"{out_dir}/ladder.json")

    monkeypatch.setattr(script, "write_report", missing)
    code = script.main(["--out-dir", str(tmp_path), "report", "--stop-reason", "done"])
    assert code == 2
    assert capsys.readouterr().err.startswith("error: ")


def test_script_cap_defaults_match_spend_caps(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from scripts import cost_ladder as script

    seen: dict[str, Any] = {}

    def fake_baseline(**kw: Any) -> int:
        seen.update(kw)
        return 0

    monkeypatch.setattr(script, "require_gemini_key", lambda env: None)
    monkeypatch.setattr(script, "run_baseline", fake_baseline)
    assert script.main(["--out-dir", str(tmp_path), "baseline"]) == 0
    assert seen["caps"] == SpendCaps()
