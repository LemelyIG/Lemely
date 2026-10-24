"""Sub-project C P1: the runner's real split. Fakes only: no model call, no spend."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from lemely.accuracy import reference as ref
from lemely.accuracy.cost_ladder import runner
from lemely.accuracy.cost_ladder.gate import RunSummary
from lemely.accuracy.cost_ladder.real_split import RealScript, load_real_scripts
from lemely.accuracy.cost_ladder.runner import LadderStateError, apply_overrides
from lemely.accuracy.cost_ladder.spend import SpendCapError, SpendCaps
from lemely.core.schemas import CorrectedQuestion, CorrectionResult, ExamMetadata
from lemely.io.gemini import CallRecord, UnpricedModelError
from lemely.runtime.config import Settings
from lemely.runtime.events import EventType, bus

PERFECT = {"1a": 2, "1b": 1}


@pytest.fixture(autouse=True)
def _spend_file_in_tmp(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    path = tmp_path / "spend.json"
    monkeypatch.setattr(runner, "DEFAULT_SPEND_FILE", path)
    return path


def _scripts(tmp_path: Path, keys: tuple[str, ...] = ("a", "b")) -> list[RealScript]:
    root = tmp_path / "ref"
    for key in keys:
        d = root / key
        ref.write_reference(
            d / ref.REFERENCE_FILE,
            [
                ref.ReferenceLeaf("1a", 2, 2, "opus", "e"),
                ref.ReferenceLeaf("1b", 1, 1, "opus", "e"),
            ],
        )
        (d / ref.SCHEME_FILE).write_text("{}", encoding="utf-8")
        scan = root / f"{key}.pdf"
        scan.write_bytes(key.encode())
        ref.freeze(
            d,
            key=key,
            scan_path=scan,
            sources={},
            expected_total=None,
            manifest_path=root / ref.MANIFEST_FILE,
        )
    return load_real_scripts(root / ref.MANIFEST_FILE)


def _correction(marks: dict[str, int]) -> CorrectionResult:
    meta = ExamMetadata(
        subject_code="0625",
        paper_number=4,
        paper_variant=1,
        session_month="Oct/Nov",
        session_year=2024,
    )
    return CorrectionResult(
        metadata=meta,
        questions=[
            CorrectedQuestion(
                question_id=q,
                awarded_marks=m,
                maximum_marks=2 if q == "1a" else 1,
                confidence="high",
                confidence_score=0.9,
                needs_teacher_review=False,
                marker_source="ai",
            )
            for q, m in marks.items()
        ],
    )


def _rec(key: str, usd: float, *, tag: str = "correction", qid: str | None = None) -> CallRecord:
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
        latency_ms=5,
        attempt=None,
        question_id=qid,
        case_key=key,
        parse_ok=True,
    )


class _Harness:
    """Fake production path: bills ``usd`` per script and returns marks in call order."""

    def __init__(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        marks: list[dict[str, int]] | None = None,
        usd: float = 0.01,
        raise_for: tuple[str, ...] = (),
        escalate: tuple[str, ...] = (),
    ) -> None:
        self.records: list[CallRecord] = []
        self.clients: list[tuple[Settings, dict[str, Any]]] = []
        self.calls: list[str] = []
        self.marks = list(marks or [])
        self.usd, self.raise_for, self.escalate = usd, raise_for, escalate
        monkeypatch.setattr(runner, "preflight_prices", lambda settings: None)
        monkeypatch.setattr(runner, "GeminiClient", self._client)
        monkeypatch.setattr(runner, "reset_process_counters", lambda: self.records.clear())
        monkeypatch.setattr(runner, "process_call_records", lambda: list(self.records))
        monkeypatch.setattr(runner, "set_call_context", lambda *, case_key: None)
        monkeypatch.setattr(runner, "mark_real_script", self.mark)

    def _client(self, settings: Settings, **kw: Any) -> object:
        self.clients.append((settings, kw))
        return object()

    def mark(self, script: RealScript, client: object, settings: Settings) -> CorrectionResult:
        self.calls.append(script.key)
        self.records.append(_rec(script.key, self.usd))
        if script.key in self.raise_for:
            raise RuntimeError("boom")
        for qid in self.escalate:
            self.records.append(_rec(script.key, 0.02, tag="escalation", qid=qid))
            bus.publish(
                EventType.GEMINI_ESCALATE,
                question_id=qid,
                confidence=0.7,
                escalation_model="claude-sonnet-5-5",
            )
        return _correction(self.marks.pop(0) if self.marks else PERFECT)


def test_run_real_scores_writes_and_books(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    h = _Harness(monkeypatch, marks=[{"1a": 2, "1b": 0}], escalate=("1a",))
    out = tmp_path / "out"
    results = runner.run_real(
        "base",
        {},
        run_index=1,
        out_dir=out,
        scripts=_scripts(tmp_path),
        settings=Settings(),
        max_run_usd={"anthropic": 1.0, "gemini": 1.0},
    )
    assert [r.key for r in results] == ["a", "b"]
    assert [r.abs_error for r in results] == [1, 0]
    assert results[0].leaves[0].escalated and results[0].leaves[0].pre_escalation_confidence == 0.7
    run_dir = out / "base" / "real-1"
    for name in ("records.jsonl", "real_results.json", "escalations.jsonl", "run_cost.json"):
        assert (run_dir / name).is_file(), name
    spent = json.loads((tmp_path / "spend.json").read_text())
    assert spent["anthropic"] == pytest.approx(2 * (0.01 + 0.02))
    ((settings, kw),) = h.clients
    assert kw == {"default_cache_mode": "bypass"}
    assert settings.paths.cache_dir == runner.cache_dir_for(out, "base-real-1")
    assert settings.gemini.cache_forget_enabled is False


def test_run_real_failed_script_is_incomplete_and_the_rest_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _Harness(monkeypatch, raise_for=("a",))
    results = runner.run_real(
        "base",
        {},
        run_index=1,
        out_dir=tmp_path / "o",
        scripts=_scripts(tmp_path),
        settings=Settings(),
        max_run_usd={"anthropic": 1.0, "gemini": 1.0},
    )
    assert results[0].incomplete == "RuntimeError: boom"
    assert results[1].incomplete is None


def test_run_real_stops_at_the_cap(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    h = _Harness(monkeypatch, usd=0.01)
    results = runner.run_real(
        "base",
        {},
        run_index=1,
        out_dir=tmp_path / "o",
        scripts=_scripts(tmp_path, ("a", "b", "c")),
        settings=Settings(),
        caps=SpendCaps(anthropic_usd=0.025),
        max_run_usd={"anthropic": 0.02, "gemini": 0.0},
    )
    assert h.calls == ["a", "b"]
    assert results[2].incomplete == "not run (spend cap)"


def test_run_real_refuses_without_a_projection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    h = _Harness(monkeypatch)
    with pytest.raises(SpendCapError, match="--max-run-usd"):
        runner.run_real(
            "base",
            {},
            run_index=1,
            out_dir=tmp_path / "o",
            scripts=_scripts(tmp_path),
            settings=Settings(),
        )
    assert h.calls == [] and h.clients == []


def test_run_real_refuses_an_unpriced_model_before_any_client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def boom(*a: object, **k: object) -> None:
        raise AssertionError("must not spend")

    monkeypatch.setattr(runner, "GeminiClient", boom)
    monkeypatch.setattr(runner, "mark_real_script", boom)
    settings = apply_overrides(Settings(), {"gemini.scan_metadata_model": "gemini-9-unknown"})
    with pytest.raises(UnpricedModelError, match="gemini-9-unknown"):
        runner.run_real(
            "base",
            {},
            run_index=1,
            out_dir=tmp_path / "o",
            scripts=_scripts(tmp_path),
            settings=settings,
            max_run_usd={"anthropic": 1.0, "gemini": 1.0},
        )


def test_models_in_play_cover_the_real_path() -> None:
    s = apply_overrides(
        Settings(),
        {
            "gemini.scan_metadata_model": "gemini-x-meta",
            "binding.second_read_model": "claude-x-second",
        },
    )
    names = runner.models_in_play(s)
    assert "gemini-x-meta" in names and "claude-x-second" in names


def _real_baseline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, marks: list[dict[str, int]]
) -> tuple[Path, list[RealScript]]:
    _Harness(monkeypatch, marks=marks)
    scripts = _scripts(tmp_path)
    out = tmp_path / "out"
    runner.run_baseline(
        out_dir=out,
        settings=Settings(),
        split="real",
        real_scripts=scripts,
        max_run_usd={"anthropic": 1.0, "gemini": 1.0},
    )
    return out, scripts


def test_real_baseline_writes_summary_and_real_floor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    out, _ = _real_baseline(monkeypatch, tmp_path, [PERFECT, PERFECT, {"1a": 0, "1b": 1}, PERFECT])
    floors = json.loads((out / runner.AA_FLOOR_FILE).read_text())
    assert floors == {"aa_floor": 0, "real_aa_floor": 2.0}
    s = runner.read_summary(out / "baseline" / "summary.json")
    assert s.real_scripts == ("a", "b") and s.real_abs_error == 1.0
    assert s.scored_parts == 0


def test_screen_real_split_judges_accuracy(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    low = {"1a": 1, "1b": 0}
    out, scripts = _real_baseline(monkeypatch, tmp_path, [low] * 4)
    _Harness(monkeypatch)  # the candidate marks every leaf right
    v = runner.run_screen(
        "b1",
        {"gemini.correction_citations": True},
        out_dir=out,
        settings=Settings(),
        max_run_usd={"anthropic": 1.0, "gemini": 1.0},
        split="real",
        judge_kind="accuracy",
        repeats=2,
        real_scripts=scripts,
    )
    assert v.passed, v.reasons
    verdict = json.loads((out / "b1" / "verdict.json").read_text())
    assert verdict["judge"] == "accuracy" and verdict["repeats"] == 2 and verdict["split"] == "real"
    assert isinstance(verdict["notes"], list)
    assert json.loads((out / "ladder.json").read_text()) == ["b1"]
    summary = json.loads((out / "b1" / "summary.json").read_text())
    assert summary["overrides"] == {"gemini.correction_citations": True}
    assert summary["real_abs_error"] == 0.0
    assert (out / "b1" / "real-2" / "real_results.json").is_file()


def test_screen_real_split_refuses_without_a_real_floor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _Harness(monkeypatch)
    out = tmp_path / "out"
    runner.write_summary(
        runner.EMPTY_DEV_SUMMARY, out / "baseline" / "summary.json", usd_per_script_mean_now=0.0
    )
    (out / runner.AA_FLOOR_FILE).write_text(json.dumps({"aa_floor": 0}))
    with pytest.raises(LadderStateError, match="real_aa_floor"):
        runner.run_screen(
            "b1",
            {},
            out_dir=out,
            settings=Settings(),
            split="real",
            judge_kind="accuracy",
            real_scripts=_scripts(tmp_path),
        )
    assert not (out / "b1").exists()


def test_reference_rung_takes_stored_dev_and_live_real(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _Harness(monkeypatch)
    out = tmp_path / "out"
    stored = tmp_path / "old" / "summary.json"
    runner.write_summary(
        RunSummary(0.2, 9.0, frozenset({"x/1a"}), 78, 1.0, 1.0, ()),
        stored,
        usd_per_script_mean_now=0.2,
    )
    s = runner.run_reference_rung(
        "gemini",
        out_dir=out,
        real_scripts=_scripts(tmp_path),
        dev_summary_from=stored,
        settings=Settings(),
        max_run_usd={"anthropic": 1.0, "gemini": 1.0},
    )
    assert s.mismarked_parts == frozenset({"x/1a"}) and s.real_scripts == ("a", "b")
    data = json.loads((out / "gemini" / "summary.json").read_text())
    assert data["reference_rung"] is True
    assert not (out / "ladder.json").exists()


def _ladder_row(out: Path, label: str, *, passed: bool) -> None:
    (out / runner.LADDER_FILE).write_text(json.dumps([label]))
    (out / label / "verdict.json").write_text(json.dumps({"passed": passed}))


def _reference_rung(path: Path) -> None:
    data = json.loads(path.read_text())
    data["reference_rung"] = True
    path.write_text(json.dumps(data))


def test_flip_verdict_writes_its_file(tmp_path: Path) -> None:
    base = RunSummary(
        0.05,
        1.0,
        frozenset(),
        10,
        1.0,
        1.0,
        (),
        real_scripts=("a",),
        real_abs_error=3.0,
        real_usd_max_by_script=(("a", 0.05),),
        real_review_rate=0.2,
    )
    runner.write_summary(base, tmp_path / "stack" / "summary.json", usd_per_script_mean_now=0.0)
    runner.write_summary(
        replace(base, real_abs_error=4.0),
        tmp_path / "gemini" / "summary.json",
        usd_per_script_mean_now=0.0,
    )
    (tmp_path / runner.AA_FLOOR_FILE).write_text(json.dumps({"aa_floor": 0, "real_aa_floor": 1.0}))
    _ladder_row(tmp_path, "stack", passed=True)
    _reference_rung(tmp_path / "gemini" / "summary.json")
    v = runner.flip_verdict(tmp_path, candidate="stack", gemini="gemini")
    assert v.passed
    data = json.loads((tmp_path / runner.FLIP_VERDICT_FILE).read_text())
    assert data["passed"] is True and data["candidate"] == "stack" and data["gemini"] == "gemini"


def test_resummarise_refuses_a_real_split_run(tmp_path: Path) -> None:
    runner.write_summary(
        RunSummary(0.0, 0.0, frozenset(), 0, 1.0, 1.0, (), real_scripts=("a",)),
        tmp_path / "x" / "summary.json",
        usd_per_script_mean_now=0.0,
    )
    with pytest.raises(LadderStateError, match="real split"):
        runner.resummarise("x", out_dir=tmp_path)


def test_pair_summaries_mean_and_union() -> None:
    a = RunSummary(1.0, 100.0, frozenset({"c/1"}), 10, 1.0, 1.0, ())
    b = RunSummary(3.0, 300.0, frozenset({"c/2"}), 10, 0.5, 0.9, ("c (x)",))
    p = runner.pair_summaries(a, b)
    assert p.usd_per_script_mean == 2.0 and p.latency_p95_ms == 200.0
    assert p.mismarked_parts == frozenset({"c/1", "c/2"})
    assert p.id_match_rate == 0.75 and p.validity_rate == pytest.approx(0.95)
    assert p.incomplete == ("c (x)",)
    narrowed = runner.pair_summaries(a, replace(b, scored_parts=9))
    assert "scored parts differ between the two runs (10, 9)" in narrowed.incomplete


def test_read_summary_round_trips_real_fields(tmp_path: Path) -> None:
    s = RunSummary(
        0.05,
        1.0,
        frozenset(),
        3,
        1.0,
        1.0,
        (),
        real_scripts=("a", "b"),
        real_abs_error=2.5,
        real_abs_error_by_run=(2.0, 3.0),
        real_review_rate=0.3,
        real_usd_by_script=(("a", 0.04),),
        real_escalation_triggers=(("confidence", 2),),
    )
    path = tmp_path / "summary.json"
    runner.write_summary(s, path, usd_per_script_mean_now=0.0)
    assert runner.read_summary(path) == s


def test_failed_script_reaches_real_incomplete_in_the_summary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _Harness(monkeypatch, raise_for=("a",))
    out = tmp_path / "out"
    runner.run_baseline(
        out_dir=out,
        settings=Settings(),
        split="real",
        real_scripts=_scripts(tmp_path),
        max_run_usd={"anthropic": 1.0, "gemini": 1.0},
    )
    s = runner.read_summary(out / "baseline" / "summary.json")
    assert s.real_incomplete == ("real-1:a (RuntimeError: boom)", "real-2:a (RuntimeError: boom)")
    assert s.real_review_rate is not None
    assert set(s.real_incomplete) <= set(s.incomplete)


def test_with_real_reports_an_absent_script_from_the_expected_keys() -> None:
    run = _scored_run("b")
    s = runner.with_real(runner.EMPTY_DEV_SUMMARY, [run], ["a", "b"])
    assert s.real_incomplete == ("real-1:a (no result)",)
    assert s.real_scripts == ("a", "b")


def _scored_run(*keys: str) -> list:
    from lemely.accuracy.cost_ladder.real_split import RealScriptResult

    return [
        RealScriptResult(
            key=k,
            leaves=(),
            binding_verdict=None,
            usd=0.0,
            escalation_usd=0.0,
            adjudication_usd=0.0,
            latency_ms=1.0,
            incomplete=None,
        )
        for k in keys
    ]


def test_screen_rung_always_has_a_review_rate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    out, scripts = _real_baseline(monkeypatch, tmp_path, [{"1a": 1, "1b": 0}] * 4)
    _Harness(monkeypatch)
    runner.run_screen(
        "b1",
        {},
        out_dir=out,
        settings=Settings(),
        max_run_usd={"anthropic": 1.0, "gemini": 1.0},
        split="real",
        judge_kind="accuracy",
        real_scripts=scripts,
    )
    assert runner.read_summary(out / "b1" / "summary.json").real_review_rate is not None
    assert runner.read_summary(out / "baseline" / "summary.json").real_review_rate is not None


def test_per_script_dollars_keep_escalation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _Harness(monkeypatch, escalate=("1a",))
    out = tmp_path / "out"
    results = runner.run_real(
        "base",
        {},
        run_index=1,
        out_dir=out,
        scripts=_scripts(tmp_path),
        settings=Settings(),
        max_run_usd={"anthropic": 1.0, "gemini": 1.0},
    )
    assert results[0].usd == pytest.approx(0.03) and results[0].escalation_usd == pytest.approx(
        0.02
    )


class _DevFake:
    """Fake ``run_config``: writes the run's summary, honours the hooks, spends nothing."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.mismarks: dict[str, frozenset[str]] = {}
        self.now: dict[str, float] = {}
        self.usd: dict[str, float] = {}
        self.labels: list[str] = []
        monkeypatch.setattr(runner, "run_config", self)

    def __call__(
        self,
        label: str,
        overrides: Any,
        *,
        out_dir: Path,
        cache_dir: Path | None = None,
        on_checks_passed: Any = None,
        summary_extra: Any = None,
        live_tags: Any = (),
        frozen_upstream: Any = None,
        **_kw: Any,
    ) -> RunSummary:
        if on_checks_passed is not None:
            on_checks_passed()
        self.labels.append(label)
        if cache_dir is not None:
            cache_dir.mkdir(parents=True, exist_ok=True)
        summary = RunSummary(
            self.usd.get(label, 0.1), 10.0, self.mismarks.get(label, frozenset()), 5, 1.0, 1.0, ()
        )
        run_dir = out_dir / label
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "records.jsonl").write_text("")
        runner.write_summary(
            summary,
            run_dir / "summary.json",
            usd_per_script_mean_now=self.now.get(label, 0.1),
            extra={
                "overrides": dict(overrides),
                "live_tags": list(live_tags),
                "frozen_upstream": frozen_upstream is not None,
                "cache_hits": 0,
                **(summary_extra or {}),
            },
        )
        return summary


CAPS = {"anthropic": 1.0, "gemini": 1.0}


def test_bad_judge_kind_and_split_are_refused_before_any_spend(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    out, scripts = _real_baseline(monkeypatch, tmp_path, [PERFECT] * 2)
    h = _Harness(monkeypatch)
    spend = (tmp_path / "spend.json").read_text()
    for kw in ({"judge_kind": "typo"}, {"split": "bogus"}, {"repeats": 3}):
        with pytest.raises(ValueError):
            runner.run_screen(
                "b1",
                {},
                out_dir=out,
                settings=Settings(),
                real_scripts=scripts,
                max_run_usd=CAPS,
                **{"split": "real", **kw},
            )  # type: ignore[arg-type]
    assert not (out / "b1").exists() and h.clients == []
    assert (tmp_path / "spend.json").read_text() == spend
    with pytest.raises(ValueError, match="judge_kind"):
        runner._judge(
            "typo",
            runner.EMPTY_DEV_SUMMARY,
            runner.EMPTY_DEV_SUMMARY,  # type: ignore[arg-type]
            floor=0,
            real_floor=0.0,
            original_p95=0.0,
        )
    with pytest.raises(ValueError, match="split"):
        runner.run_baseline(out_dir=tmp_path / "o2", split="bogus")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="repeats"):
        runner.run_baseline(out_dir=tmp_path / "o2", repeats=3)
    assert not (tmp_path / "o2").exists()


def test_aa_only_pairs_from_the_raw_baseline_not_a_pair(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    dev = _DevFake(monkeypatch)
    out = tmp_path / "out"
    dev.mismarks = {"baseline": frozenset({"x/1"}), "baseline_aa": frozenset({"x/2"})}
    runner.run_baseline(out_dir=out, settings=Settings(), repeats=2)
    path = out / "baseline" / "summary.json"
    assert runner.read_summary(path).mismarked_parts == {"x/1", "x/2"}
    dev.mismarks["baseline_aa"] = frozenset({"x/3"})
    runner.run_baseline(out_dir=out, settings=Settings(), repeats=2, aa_only=True)
    assert runner.read_summary(path).mismarked_parts == {"x/1", "x/3"}


def test_baseline_both_writes_both_floors_and_keeps_cache_stats(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _DevFake(monkeypatch)
    _Harness(monkeypatch, marks=[PERFECT, PERFECT, {"1a": 0, "1b": 1}, PERFECT])
    out = tmp_path / "out"
    runner.run_baseline(
        out_dir=out,
        settings=Settings(),
        split="both",
        real_scripts=_scripts(tmp_path),
        max_run_usd=CAPS,
    )
    assert json.loads((out / runner.AA_FLOOR_FILE).read_text()) == {
        "aa_floor": 0,
        "real_aa_floor": 2.0,
    }
    data = json.loads((out / "baseline" / "summary.json").read_text())
    assert "in_run_cache_hits" in data and data["real_scripts"] == ["a", "b"]
    assert data["split"] == "both" and data["scored_parts"] == 5


def test_baseline_repeats_two_pairs_and_means_the_now_cost(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    dev = _DevFake(monkeypatch)
    dev.usd = {"baseline": 0.1, "baseline_aa": 0.3}
    dev.now = {"baseline": 0.2, "baseline_aa": 0.4}
    out = tmp_path / "out"
    runner.run_baseline(out_dir=out, settings=Settings(), repeats=2)
    data = json.loads((out / "baseline" / "summary.json").read_text())
    assert data["usd_per_script_mean"] == pytest.approx(0.2)
    assert data["usd_per_script_mean_now"] == pytest.approx(0.3)
    assert data["split"] == "dev"


def test_aa_only_keeps_the_real_floor(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _DevFake(monkeypatch)
    _Harness(monkeypatch)
    out = tmp_path / "out"
    runner.run_baseline(
        out_dir=out,
        settings=Settings(),
        split="both",
        real_scripts=_scripts(tmp_path),
        max_run_usd=CAPS,
    )
    runner.run_baseline(out_dir=out, settings=Settings(), aa_only=True)
    floors = json.loads((out / runner.AA_FLOOR_FILE).read_text())
    assert "real_aa_floor" in floors
    assert runner.read_summary(out / "baseline" / "summary.json").real_scripts == ("a", "b")


def test_screen_both_with_repeats_pairs_and_records_the_split(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    dev = _DevFake(monkeypatch)
    _Harness(monkeypatch)
    out = tmp_path / "out"
    scripts = _scripts(tmp_path)
    runner.run_baseline(
        out_dir=out, settings=Settings(), split="both", real_scripts=scripts, max_run_usd=CAPS
    )
    dev.mismarks = {"b1": frozenset({"x/1"}), "b1-r2": frozenset({"x/2"})}
    runner.run_screen(
        "b1",
        {"gemini.correction_citations": True},
        out_dir=out,
        settings=Settings(),
        split="both",
        judge_kind="record",
        repeats=2,
        real_scripts=scripts,
        max_run_usd=CAPS,
    )
    assert (out / "b1" / "summary.json").is_file() and (out / "b1-r2" / "summary.json").is_file()
    s = runner.read_summary(out / "b1" / "summary.json")
    assert s.mismarked_parts == {"x/1", "x/2"} and s.real_scripts == ("a", "b")
    verdict = json.loads((out / "b1" / "verdict.json").read_text())
    assert verdict["split"] == "both" and verdict["judge"] == "record"
    assert json.loads((out / "b1" / "summary.json").read_text())["split"] == "both"
    assert (out / "b1" / "real-2" / "real_results.json").is_file()
    assert dev.labels.count("b1-r2") == 1


@pytest.mark.parametrize("kind", ["cost", "record"])
def test_screen_judge_kinds_run_through(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, kind: str
) -> None:
    out, scripts = _real_baseline(monkeypatch, tmp_path, [PERFECT] * 2)
    _Harness(monkeypatch)
    v = runner.run_screen(
        "b1",
        {},
        out_dir=out,
        settings=Settings(),
        split="real",
        judge_kind=kind,
        real_scripts=scripts,
        max_run_usd=CAPS,
    )  # type: ignore[arg-type]
    assert v.passed, v.reasons
    assert json.loads((out / "b1" / "verdict.json").read_text())["judge"] == kind
    assert any("recorded" in n for n in v.notes) == (kind == "record")


def test_flip_verdict_refuses_an_unaccepted_candidate_or_a_non_reference_rung(
    tmp_path: Path,
) -> None:
    base = RunSummary(
        0.05, 1.0, frozenset(), 10, 1.0, 1.0, (), real_scripts=("a",), real_review_rate=0.2
    )
    for label in ("stack", "gemini"):
        runner.write_summary(base, tmp_path / label / "summary.json", usd_per_script_mean_now=0.0)
    (tmp_path / runner.AA_FLOOR_FILE).write_text(json.dumps({"aa_floor": 0}))
    with pytest.raises(LadderStateError, match="not a ladder row"):
        runner.flip_verdict(tmp_path, candidate="stack", gemini="gemini")
    _ladder_row(tmp_path, "stack", passed=False)
    with pytest.raises(LadderStateError, match="did not pass"):
        runner.flip_verdict(tmp_path, candidate="stack", gemini="gemini")
    _ladder_row(tmp_path, "stack", passed=True)
    with pytest.raises(LadderStateError, match="not a reference rung"):
        runner.flip_verdict(tmp_path, candidate="stack", gemini="gemini")
    assert not (tmp_path / runner.FLIP_VERDICT_FILE).exists()


def test_reference_rung_drops_a_stale_summary_and_guards_its_label(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    h = _Harness(monkeypatch)
    out = tmp_path / "out"
    stored = tmp_path / "old" / "summary.json"
    runner.write_summary(
        RunSummary(0.2, 9.0, frozenset(), 78, 1.0, 1.0, ()), stored, usd_per_script_mean_now=0.2
    )
    scripts = _scripts(tmp_path)
    kw: dict[str, Any] = {
        "out_dir": out,
        "real_scripts": scripts,
        "dev_summary_from": stored,
        "settings": Settings(),
        "max_run_usd": CAPS,
    }
    runner.run_reference_rung("gemini", **kw)
    stale = out / "gemini" / "summary.json"
    seen: list[bool] = []
    original = h.mark

    def spy(script: RealScript, client: object, settings: Settings) -> CorrectionResult:
        seen.append(stale.exists())
        return original(script, client, settings)

    monkeypatch.setattr(runner, "mark_real_script", spy)
    runner.run_reference_rung("gemini", **kw)
    assert seen[0] is False and stale.is_file()
    with pytest.raises(LadderStateError, match="second run"):
        runner.run_reference_rung("gem-r2", **kw)
    (out / "plain").mkdir()
    with pytest.raises(LadderStateError, match="not a reference rung"):
        runner.run_reference_rung("plain", **kw)


def test_run_real_requires_a_projection_for_every_provider(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    h = _Harness(monkeypatch)
    with pytest.raises(SpendCapError, match="gemini"):
        runner.run_real(
            "base",
            {},
            run_index=1,
            out_dir=tmp_path / "o",
            scripts=_scripts(tmp_path),
            settings=Settings(),
            max_run_usd={"anthropic": 1.0},
        )
    assert h.clients == [] and h.calls == []


def test_a_run_cut_short_writes_no_run_cost(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _Harness(monkeypatch, usd=0.01)
    out = tmp_path / "o"
    runner.run_real(
        "base",
        {},
        run_index=1,
        out_dir=out,
        scripts=_scripts(tmp_path, ("a", "b", "c")),
        settings=Settings(),
        caps=SpendCaps(anthropic_usd=0.025),
        max_run_usd={"anthropic": 0.02, "gemini": 0.0},
    )
    assert not (out / "base" / "real-1" / "run_cost.json").exists()
    assert (out / "base" / "real-1" / "records.jsonl").is_file()


def test_resummarise_refuses_a_second_run_label(tmp_path: Path) -> None:
    with pytest.raises(LadderStateError, match="second run"):
        runner.resummarise("b1-r2", out_dir=tmp_path)
