"""Sub-project C P1: the runner's real split. Fakes only: no model call, no spend."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from lemely.accuracy import reference as ref
from lemely.accuracy.cost_ladder import runner
from lemely.accuracy.cost_ladder.gate import RunSummary
from lemely.accuracy.cost_ladder.real_split import RealScript, load_real_scripts
from lemely.accuracy.cost_ladder.report import write_flip, write_report
from lemely.accuracy.cost_ladder.runner import (
    DEFAULT_LIVE_TAGS,
    LadderStateError,
    UpstreamNotFrozen,
    apply_overrides,
    real_floor_kind,
    real_live_tags,
)
from lemely.accuracy.cost_ladder.spend import SpendCapError, SpendCaps
from lemely.core.schemas import AIMarkResponse, CorrectedQuestion, CorrectionResult, ExamMetadata
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


class _FakeClient:
    """Stand-in for the production client: scripted marking replies, nothing on the wire."""

    def __init__(self, cache_mode: str = "bypass") -> None:
        self.mark = 0
        self.cache_mode = cache_mode

    def _active_model(self, model: str | None, task_tag: str | None) -> str:
        return model or "claude-haiku-5-5"

    def generate_structured(self, **kwargs: Any) -> AIMarkResponse:
        return AIMarkResponse(awarded_marks=self.mark, confidence=0.9, feedback="because")


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
        raise_message: str = "boom",
        raise_type: type[BaseException] = RuntimeError,
        leak_upstream: bool = False,
        leak_orphan: bool = False,
    ) -> None:
        self.leak_upstream = leak_upstream
        self.leak_orphan = leak_orphan
        self.raise_message = raise_message
        self.raise_type = raise_type
        self.records: list[CallRecord] = []
        self.clients: list[tuple[Settings, dict[str, Any]]] = []
        self.calls: list[str] = []
        self.settings_seen: list[Settings] = []
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
        return _FakeClient(kw.get("default_cache_mode", "bypass"))

    def mark(self, script: RealScript, client: Any, settings: Settings) -> CorrectionResult:
        self.calls.append(script.key)
        self.settings_seen.append(settings)
        pinned_run = "correction" in settings.gemini.cache_mode_for
        if self.leak_upstream or (client.cache_mode == "read_write" and not pinned_run):
            # A pin (a baseline run): its upstream is live. A pinned run replays it instead.
            self.records.append(_rec(script.key, 0.002, tag="extraction"))
        if self.leak_orphan:  # a live call made outside any script
            self.records.append(replace(_rec(script.key, 0.002, tag="extraction"), case_key=None))
        self.records.append(_rec(script.key, self.usd))
        if script.key in self.raise_for:
            raise self.raise_type(self.raise_message)
        for qid in self.escalate:
            self.records.append(_rec(script.key, 0.02, tag="escalation", qid=qid))
            bus.publish(
                EventType.GEMINI_ESCALATE,
                question_id=qid,
                confidence=0.7,
                escalation_model="claude-sonnet-5-5",
            )
        correction = _correction(self.marks.pop(0) if self.marks else PERFECT)
        for q in correction.questions:
            client.mark = q.awarded_marks  # type: ignore[attr-defined]
            client.generate_structured(  # type: ignore[attr-defined]
                task_tag="correction", question_id=q.question_id, attempt="first"
            )
        return correction


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


def test_run_real_writes_replies_and_step_marks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _Harness(monkeypatch, marks=[{"1a": 2, "1b": 0}, PERFECT])
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
    run_dir = out / "base" / "real-1"
    rows = [json.loads(line) for line in (run_dir / "replies.jsonl").read_text().splitlines()]
    assert {(r["case_key"], r["question_id"], r["mark"]) for r in rows} == {
        ("a", "1a", 2),
        ("a", "1b", 0),
        ("b", "1a", 2),
        ("b", "1b", 1),
    }
    assert (run_dir / "real_results.json").is_file()
    assert [leaf.first_pass_mark for leaf in results[0].leaves] == [2, 0]


@pytest.mark.parametrize("raise_type", [RuntimeError, KeyboardInterrupt])
def test_replies_survive_a_failed_script(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, raise_type: type[BaseException]
) -> None:
    _Harness(monkeypatch, raise_for=("b",), raise_type=raise_type)
    out = tmp_path / "out"
    try:
        runner.run_real(
            "base",
            {},
            run_index=1,
            out_dir=out,
            scripts=_scripts(tmp_path),
            settings=Settings(),
            max_run_usd={"anthropic": 1.0, "gemini": 1.0},
        )
    except KeyboardInterrupt:
        assert (
            raise_type is KeyboardInterrupt
        )  # an interrupt propagates; the files are still written
    rows = [
        json.loads(line)
        for line in (out / "base" / "real-1" / "replies.jsonl").read_text().splitlines()
    ]
    assert {r["case_key"] for r in rows} == {"a"}


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
    assert results[0].incomplete == "RuntimeError"
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
    # Two baseline runs, then the two marking-only A/A runs (marks are used in call order).
    out, _ = _real_baseline(
        monkeypatch, tmp_path, [PERFECT, PERFECT, {"1a": 0, "1b": 1}, PERFECT, *[PERFECT] * 4]
    )
    floors = json.loads((out / runner.AA_FLOOR_FILE).read_text())
    assert floors == {"aa_floor": 0, "real_aa_floor": 2.0, "real_marking_aa_floor": 1.0}
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
    assert s.real_incomplete == ("real-1:a (RuntimeError)", "real-2:a (RuntimeError)")
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
    floor = runner.run_baseline(out_dir=out, settings=Settings(), repeats=2, aa_only=True)
    assert runner.read_summary(path).mismarked_parts == {"x/1", "x/3"}
    assert floor == 2
    assert json.loads((out / runner.AA_FLOOR_FILE).read_text())["aa_floor"] == 2


def test_aa_only_repeats_two_refuses_a_baseline_without_the_raw_summary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    dev = _DevFake(monkeypatch)
    out = tmp_path / "out"
    runner.run_baseline(out_dir=out, settings=Settings(), repeats=2)
    (out / "baseline" / runner.RAW_SUMMARY_FILE).unlink()
    dev.labels.clear()
    with pytest.raises(LadderStateError, match="summary_raw"):
        runner.run_baseline(out_dir=out, settings=Settings(), repeats=2, aa_only=True)
    assert dev.labels == []


def test_a_run_where_every_script_failed_writes_no_run_cost(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _Harness(monkeypatch, raise_for=("a", "b"))
    out = tmp_path / "o"
    runner.run_real(
        "base",
        {},
        run_index=1,
        out_dir=out,
        scripts=_scripts(tmp_path),
        settings=Settings(),
        max_run_usd=CAPS,
    )
    assert not (out / "base" / "real-1" / "run_cost.json").exists()


def test_baseline_both_writes_both_floors_and_keeps_cache_stats(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _DevFake(monkeypatch)
    _Harness(monkeypatch, marks=[PERFECT, PERFECT, {"1a": 0, "1b": 1}, PERFECT, *[PERFECT] * 4])
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
        "real_marking_aa_floor": 1.0,
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


_SECRET = "STUDENT-ANSWER-TEXT-xyzzy"


def test_exception_text_stays_out_of_the_summary_and_the_reports(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _Harness(monkeypatch, raise_for=("a",), raise_message=f"validation error: {_SECRET}")
    out = tmp_path / "out"
    runner.run_baseline(
        out_dir=out,
        settings=Settings(),
        split="real",
        real_scripts=_scripts(tmp_path),
        max_run_usd={"anthropic": 1.0, "gemini": 1.0},
    )
    summary = (out / "baseline" / "summary.json").read_text(encoding="utf-8")
    assert _SECRET not in summary
    assert "real-1:a (RuntimeError)" in summary
    assert _SECRET in caplog.text  # the full message stays in the local log
    for rung in ("stack", "gemini"):
        shutil.copytree(out / "baseline", out / rung)
    (out / runner.FLIP_VERDICT_FILE).write_text(
        '{"candidate": "stack", "gemini": "gemini", "passed": false, "reasons": []}',
        encoding="utf-8",
    )
    texts = [
        write_report(out, stop_reason="none").read_text(encoding="utf-8"),
        write_flip(out, candidate="stack", gemini="gemini").read_text(encoding="utf-8"),
    ]
    for text in texts:
        assert _SECRET not in text
        assert "real-1:a (RuntimeError)" in text


# --- H1: frozen upstream for the real split -------------------------------------------------


def _pinned_baseline(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    marks: list[dict[str, int]] | None = None,
    **harness: Any,
) -> tuple[_Harness, Path, list[RealScript]]:
    """A real baseline (two pins and two marking-only A/A runs) built on the fake harness."""
    h = _Harness(monkeypatch, marks=marks, **harness)
    scripts = _scripts(tmp_path)
    out = tmp_path / "out"
    runner.run_baseline(
        out_dir=out, settings=Settings(), split="real", real_scripts=scripts, max_run_usd=CAPS
    )
    return h, out, scripts


def _screen(out: Path, scripts: list[RealScript], label: str = "b1", **kw: Any) -> Any:
    args: dict[str, Any] = {
        "out_dir": out,
        "settings": Settings(),
        "max_run_usd": CAPS,
        "split": "real",
        "judge_kind": "accuracy",
        "repeats": 2,
        "real_scripts": scripts,
    }
    args.update(kw)
    return runner.run_screen(label, {"gemini.correction_citations": True}, **args)


def _spent(tmp_path: Path) -> float:
    return float(json.loads((tmp_path / "spend.json").read_text())["anthropic"])


def test_real_live_tags_expand_to_later_stages() -> None:
    marking = {"correction_prefix_cache", "correction", "correction_borderline", "escalation"}
    assert set(real_live_tags(("correction",))) == marking | {"adjudication"}
    assert real_live_tags(("escalation",)) == ("adjudication", "escalation")
    binding = {"extraction", "binding_overview", "binding_second_read", "second_read"}
    assert set(real_live_tags(("binding_second_read",))) == binding | marking | {"adjudication"}
    assert len(real_live_tags(("scan_metadata",))) == 1 + len(binding) + len(marking) + 1
    assert real_live_tags(("adjudication", "correction")) == real_live_tags(("correction",))
    with pytest.raises(ValueError, match="nonsense"):
        real_live_tags(("nonsense",))
    with pytest.raises(ValueError, match="at least one"):
        real_live_tags(())
    assert real_floor_kind(real_live_tags(DEFAULT_LIVE_TAGS)) == "marking"
    assert real_floor_kind(real_live_tags(("escalation",))) == "marking"
    assert real_floor_kind(real_live_tags(("binding_second_read",))) == "full"
    assert real_floor_kind(()) == "full"


def test_baseline_real_pins_and_writes_the_marking_floor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Baseline repeat 1 is two marks short, repeat 2 exact; the A/A repeats the other way round,
    # so the signed differences cancel: abs(mean) would be 0, the mean of abs is 2.
    short = {"1a": 0, "1b": 1}
    h, out, _ = _pinned_baseline(
        monkeypatch, tmp_path, [short, PERFECT, PERFECT, PERFECT, PERFECT, PERFECT, short, PERFECT]
    )
    floors = json.loads((out / runner.AA_FLOOR_FILE).read_text())
    assert floors["real_aa_floor"] == 2.0 and floors["real_marking_aa_floor"] == 2.0
    live = {t: "refresh" for t in real_live_tags(DEFAULT_LIVE_TAGS)}
    assert [(kw, s.gemini.cache_mode_for) for s, kw in h.clients] == [
        ({"default_cache_mode": "read_write"}, {}),
        ({"default_cache_mode": "read_write"}, {}),
        ({"default_cache_mode": "read_write"}, live),
        ({"default_cache_mode": "read_write"}, live),
    ]
    for rung, pinned_from in (("baseline", None), ("baseline_aa", "baseline")):
        for n in (1, 2):
            pin = json.loads((out / rung / f"real-{n}" / "pin.json").read_text())
            assert pin["pinned_from"] == pinned_from and pin["run_index"] == n
            assert set(pin["scripts"]) == {"a", "b"}
            for entry in pin["scripts"].values():
                assert entry["complete"] is True and entry["upstream_calls"] == 1
    assert (out / "cache" / "baseline-real-1").is_dir()
    assert not (out / "baseline" / "real-1" / "upstream_records.jsonl").exists()
    assert (out / "baseline_aa" / "real-1" / "upstream_records.jsonl").is_file()


def test_baseline_with_an_incomplete_script_runs_no_marking_aa(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    h, out, _ = _pinned_baseline(monkeypatch, tmp_path, raise_for=("b",))
    assert len(h.clients) == 2  # no A/A on a baseline whose pin is incomplete
    floors = json.loads((out / runner.AA_FLOOR_FILE).read_text())
    assert "real_marking_aa_floor" not in floors and "real_aa_floor" in floors
    pin = json.loads((out / "baseline" / "real-1" / "pin.json").read_text())
    assert pin["scripts"]["a"]["complete"] is True and pin["scripts"]["b"]["complete"] is False


def test_screen_real_replays_the_against_upstream(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, out, scripts = _pinned_baseline(monkeypatch, tmp_path, [{"1a": 1, "1b": 0}] * 4)
    sentinel = out / "cache" / "baseline-real-1" / "gemini" / "s.json"
    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.write_text("{}")
    before = _spent(tmp_path)
    _Harness(monkeypatch)
    v = _screen(out, scripts)
    assert v.passed, v.reasons
    assert (out / "cache" / "b1-real-1" / "gemini" / "s.json").is_file()
    assert not (out / "cache" / "b1-real-2" / "gemini" / "s.json").exists()
    upstream = [
        json.loads(line)
        for line in (out / "b1" / "real-1" / "upstream_records.jsonl").read_text().splitlines()
    ]
    assert sorted((r["case_key"], r["task_tag"]) for r in upstream) == [
        ("a", "extraction"),
        ("b", "extraction"),
    ]
    results = json.loads((out / "b1" / "real-1" / "real_results.json").read_text())
    assert [r["usd"] for r in results] == [pytest.approx(0.012)] * 2  # live 0.01 + replayed 0.002
    assert _spent(tmp_path) - before == pytest.approx(4 * 0.01)  # only live records are billed
    live_only = [
        json.loads(line)
        for line in (out / "b1" / "real-1" / "records.jsonl").read_text().splitlines()
    ]
    assert {r["task_tag"] for r in live_only} == {"correction"}
    summary = json.loads((out / "b1" / "summary.json").read_text())
    pinned = summary["frozen_upstream_real"]
    assert pinned["from"] == "baseline"
    assert pinned["live_tags"] == list(real_live_tags(DEFAULT_LIVE_TAGS))
    assert "extraction" in pinned["pinned_tags"] and "correction" not in pinned["pinned_tags"]
    floors = json.loads((out / runner.AA_FLOOR_FILE).read_text())
    verdict = json.loads((out / "b1" / "verdict.json").read_text())
    assert verdict["real_floor_kind"] == "marking"
    assert verdict["real_floor"] == floors["real_marking_aa_floor"]
    assert verdict["real_pinned_from"] == "baseline"
    assert verdict["real_live_tags"] == list(real_live_tags(DEFAULT_LIVE_TAGS))
    (note,) = [n for n in verdict["notes"] if n.startswith("real upstream pinned from baseline")]
    assert "marking-only A/A floor" in note and "excludes the replayed upstream" in note


def test_screen_real_refuses_a_missing_pin_before_any_spend(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, out, scripts = _pinned_baseline(monkeypatch, tmp_path)
    (out / "baseline" / "real-2" / "pin.json").unlink()
    before = _spent(tmp_path)
    h = _Harness(monkeypatch)
    with pytest.raises(LadderStateError, match=r"real-2.*pin\.json|pin\.json.*real-2") as err:
        _screen(out, scripts)
    assert "--restart-baseline" in str(err.value)
    assert h.calls == [] and h.clients == []
    assert _spent(tmp_path) == before
    assert not (out / "b1").exists()
    assert not list((out / "cache").glob("b1-real-*"))


def _edit_pin(out: Path, mutate: Any) -> None:
    path = out / "baseline" / "real-1" / "pin.json"
    pin = json.loads(path.read_text())
    mutate(pin["scripts"])
    path.write_text(json.dumps(pin))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda sc: sc["b"].update(scan_sha256="0" * 64),
        lambda sc: sc["b"].update(scheme_sha256="0" * 64),
        lambda sc: sc["b"].update(complete=False),
        lambda sc: sc["b"].update(upstream_calls=0),
        lambda sc: sc.pop("b"),
    ],
    ids=["scan", "scheme", "incomplete", "no-upstream", "not-in-pin"],
)
def test_screen_real_refuses_a_foreign_or_incomplete_pin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mutate: Any
) -> None:
    _, out, scripts = _pinned_baseline(monkeypatch, tmp_path)
    _edit_pin(out, mutate)
    h = _Harness(monkeypatch)
    with pytest.raises(LadderStateError, match=r"b \(real-1"):
        _screen(out, scripts)
    assert h.calls == []


def test_pinned_upstream_live_call_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, out, scripts = _pinned_baseline(monkeypatch, tmp_path)
    h = _Harness(monkeypatch, leak_upstream=True)
    with pytest.raises(UpstreamNotFrozen, match="extraction"):
        _screen(out, scripts)
    assert h.calls == ["a"]  # stopped after the first script that broke the freeze
    run_dir = out / "b1" / "real-1"
    assert not (out / "b1" / "verdict.json").exists()
    assert not (out / runner.LADDER_FILE).exists() or "b1" not in json.loads(
        (out / runner.LADDER_FILE).read_text()
    )
    assert (run_dir / "records.jsonl").is_file() and (run_dir / "replies.jsonl").is_file()
    assert not (run_dir / "real_results.json").exists()


def test_pinned_upstream_call_outside_any_script_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, out, scripts = _pinned_baseline(monkeypatch, tmp_path)
    _Harness(monkeypatch, leak_orphan=True)
    with pytest.raises(UpstreamNotFrozen, match="extraction"):
        _screen(out, scripts)
    assert not (out / "b1" / "verdict.json").exists()
    assert not (out / "b1" / "real-1" / "real_results.json").exists()


def test_binder_lever_runs_binding_live_on_the_full_floor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, out, scripts = _pinned_baseline(monkeypatch, tmp_path, [{"1a": 1, "1b": 0}] * 4)
    h = _Harness(monkeypatch)
    tags = ("binding_second_read", *DEFAULT_LIVE_TAGS)
    _screen(out, scripts, live_tags=tags)
    expected = {t: "refresh" for t in real_live_tags(tags)}
    assert {"binding_second_read", "extraction", "correction"} <= set(expected)
    assert all(s.gemini.cache_mode_for == expected for s, _ in h.clients)
    summary = json.loads((out / "b1" / "summary.json").read_text())
    assert summary["frozen_upstream_real"]["pinned_tags"] == ["scan_metadata"]
    floors = json.loads((out / runner.AA_FLOOR_FILE).read_text())
    verdict = json.loads((out / "b1" / "verdict.json").read_text())
    assert verdict["real_floor_kind"] == "full" and verdict["real_floor"] == floors["real_aa_floor"]
    assert any("full-pipeline A/A floor" in n for n in verdict["notes"])


def test_stacked_screen_pins_from_its_against_rung(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, out, scripts = _pinned_baseline(monkeypatch, tmp_path, [{"1a": 1, "1b": 0}] * 4)
    _Harness(monkeypatch)
    assert _screen(out, scripts).passed
    sentinel = out / "cache" / "b1-real-1" / "gemini" / "only-b1.json"
    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.write_text("{}")
    _Harness(monkeypatch)
    runner.run_screen(
        "b2",
        {"gemini.correction_citations": False},
        out_dir=out,
        against="b1",
        settings=Settings(),
        max_run_usd=CAPS,
        split="real",
        judge_kind="accuracy",
        repeats=2,
        real_scripts=scripts,
    )
    assert (out / "cache" / "b2-real-1" / "gemini" / "only-b1.json").is_file()
    upstream = [
        json.loads(line)
        for line in (out / "b2" / "real-1" / "upstream_records.jsonl").read_text().splitlines()
    ]
    # Chained through b1: its records.jsonl holds no extraction, the baseline's does.
    assert sorted(r["task_tag"] for r in upstream) == ["extraction", "extraction"]


def test_marking_screen_refuses_without_a_marking_floor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, out, scripts = _pinned_baseline(monkeypatch, tmp_path)
    floors_path = out / runner.AA_FLOOR_FILE
    floors = json.loads(floors_path.read_text())
    del floors["real_marking_aa_floor"]
    floors_path.write_text(json.dumps(floors))
    before = _spent(tmp_path)
    h = _Harness(monkeypatch)
    with pytest.raises(LadderStateError, match="real_marking_aa_floor"):
        _screen(out, scripts)
    assert h.calls == [] and _spent(tmp_path) == before


def test_real_projection_keeps_pinned_and_live_apart(tmp_path: Path) -> None:
    live = tmp_path / "baseline" / "real-1"
    pinned = tmp_path / "baseline_aa" / "real-1"
    for run_dir, usd in ((live, 0.5), (pinned, 0.1)):
        run_dir.mkdir(parents=True)
        (run_dir / "run_cost.json").write_text(json.dumps({"anthropic": usd}))
    (pinned / "upstream_records.jsonl").write_text("")
    os.utime(live / "run_cost.json", (1, 1))  # the pinned run is the latest
    assert runner._real_projection(tmp_path, None, pinned=False) == {"anthropic": 0.5}
    assert runner._real_projection(tmp_path, None, pinned=True) == {"anthropic": 0.1}


def test_restart_keeps_reference_rungs_and_drops_real_caches(tmp_path: Path) -> None:
    (tmp_path / "gemini").mkdir()
    (tmp_path / "gemini" / "summary.json").write_text(json.dumps({"reference_rung": True}))
    (tmp_path / "cap1").mkdir()
    (tmp_path / "cap1" / "summary.json").write_text(json.dumps({}))
    for name in ("cap1-real-1", "cap1-real-2", "baseline-real-1"):
        (tmp_path / "cache" / name / "gemini").mkdir(parents=True)
    (tmp_path / runner.LADDER_FILE).write_text(json.dumps(["cap1"]))
    runner._archive_ladder(tmp_path)
    assert (tmp_path / "gemini" / "summary.json").is_file()
    assert not (tmp_path / "cap1").exists()
    assert not list((tmp_path / "cache").glob("cap1-real-*"))
    assert (tmp_path / "cache" / "baseline-real-1").is_dir()
    assert any((tmp_path / "archive").glob("restart-*/cap1/summary.json"))


def test_real_infix_labels_are_refused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _, out, scripts = _pinned_baseline(monkeypatch, tmp_path)
    before = _spent(tmp_path)
    h = _Harness(monkeypatch)
    with pytest.raises(ValueError, match="-real-"):
        _screen(out, scripts, label="x-real-1")
    with pytest.raises(ValueError, match="-real-"):
        runner.run_reference_rung(
            "y-real-2",
            out_dir=out,
            real_scripts=scripts,
            dev_summary_from=tmp_path / "none.json",
            settings=Settings(),
            max_run_usd=CAPS,
        )
    assert h.calls == [] and _spent(tmp_path) == before


def test_reference_rung_stays_live_and_unpinned(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    h = _Harness(monkeypatch)
    out = tmp_path / "out"
    stored = tmp_path / "old" / "summary.json"
    runner.write_summary(
        RunSummary(0.2, 9.0, frozenset(), 78, 1.0, 1.0, ()), stored, usd_per_script_mean_now=0.2
    )
    runner.run_reference_rung(
        "gemini",
        out_dir=out,
        real_scripts=_scripts(tmp_path),
        dev_summary_from=stored,
        settings=Settings(),
        max_run_usd=CAPS,
    )
    assert all(kw == {"default_cache_mode": "bypass"} for _, kw in h.clients)
    assert not list((out / "gemini").glob("real-*/pin.json"))
    assert not list((out / "gemini").glob("real-*/upstream_records.jsonl"))


def test_run_real_refuses_a_pin_replay_on_a_bypass_client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    h = _Harness(monkeypatch)
    kw: dict[str, Any] = {
        "run_index": 1,
        "out_dir": tmp_path / "o",
        "scripts": _scripts(tmp_path),
        "settings": Settings(),
        "max_run_usd": CAPS,
    }
    with pytest.raises(ValueError, match="read_write"):
        runner.run_real("x", {}, pin_from="baseline", live_tags=("correction",), **kw)
    with pytest.raises(ValueError, match="pin_from"):
        runner.run_real("x", {}, cache_mode="read_write", live_tags=("correction",), **kw)
    assert h.calls == [] and h.clients == []
