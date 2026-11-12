"""Correction cascade (cost-ladder lever A2): cheap first pass, strong re-mark on a trigger."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest

from lemely.core.loose_schemas import Question
from lemely.core.schemas import AIMarkResponse, PointVerdict
from lemely.io import correction_ai
from lemely.io.correction_ai import CASCADE_LEAF_LOG_ENV, AICorrector
from lemely.io.gemini import GeminiClient, reset_process_counters, set_call_context
from lemely.runtime.config import GeminiSettings, PathsSettings, Settings, load_settings
from scripts import cascade_sweep
from tests.gemini_fakes import pin_pre_flip, pre_flip_gemini

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _question() -> Question:
    return Question.model_validate(
        {
            "id": "1",
            "marks": 2,
            "type": "explanation",
            "answer_points": [
                {"id": "p1", "point": "gravity", "marks": 1},
                {"id": "p2", "point": "speed", "marks": 1},
            ],
        }
    )


def _mark(awarded: int, confidence: float, verdict_ids: tuple[str, ...] = ()) -> AIMarkResponse:
    return AIMarkResponse(
        awarded_marks=awarded,
        confidence=confidence,
        feedback="f",
        point_verdicts=[PointVerdict(point_id=pid, verdict="awarded") for pid in verdict_ids],
    )


class _FakeClient:
    """Records every `generate_structured` call and answers from a queue.

    ``mark_question`` reads ``_settings.gemini`` and ``resolved_thinking`` only;
    the correction tag thinks "low" and every other tag "high", so the
    non-cascade borderline retry would fire on a low-confidence first pass.
    """

    def __init__(
        self,
        gemini: GeminiSettings,
        responses: list[AIMarkResponse],
        *,
        same_thinking: bool = False,
    ) -> None:
        self._settings = SimpleNamespace(gemini=gemini)
        self._responses = list(responses)
        self._same_thinking = same_thinking
        self.calls: list[dict[str, Any]] = []

    def generate_structured(self, **kwargs: Any) -> AIMarkResponse:
        self.calls.append(kwargs)
        return self._responses.pop(0)

    def resolved_thinking(self, task_tag: str, model: str) -> str:
        if self._same_thinking:
            return "high"
        return "low" if task_tag == "correction" else "high"


def _cascade(**overrides: Any) -> GeminiSettings:
    base: dict[str, Any] = {
        "cascade_enabled": True,
        "correction_model": "cheap-model",
        "escalation_model": "gemini-3.8-flash",
        "escalation_confidence_threshold": 0.80,
    }
    # Pre-flip defaults: the fake client's resolved_thinking takes no leaf kind, and the
    # shipped claude_effort_for (sub-project C) puts one on every correction call.
    return pre_flip_gemini(**{**base, **overrides})


def _run(
    gemini: GeminiSettings, responses: list[AIMarkResponse], *, same_thinking: bool = False
) -> tuple[AIMarkResponse, _FakeClient]:
    fake = _FakeClient(gemini, responses, same_thinking=same_thinking)
    result = AICorrector(cast("GeminiClient", fake)).mark_question(_question(), "gravity")
    return result, fake


def _attempts(fake: _FakeClient) -> list[tuple[str | None, str | None, str | None]]:
    return [(c.get("attempt"), c.get("task_tag"), c.get("model")) for c in fake.calls]


# ---------------------------------------------------------------------------
# Cascade off: byte-identical prompts and cache keys
# ---------------------------------------------------------------------------


def _resp(confidence: float) -> MagicMock:
    body = json.dumps(
        {"awarded_marks": 1, "confidence": confidence, "matched_point_ids": [], "feedback": "f"}
    )
    return MagicMock(
        text=body,
        candidates=[MagicMock(finish_reason=MagicMock(__str__=lambda s: "STOP"))],
        usage_metadata=MagicMock(
            prompt_token_count=10, candidates_token_count=20, cached_content_token_count=0
        ),
    )


@pytest.fixture
def isolated_env() -> Iterator[None]:
    snap = dict(os.environ)
    for k in list(os.environ):
        if k.startswith("LEMELY_"):
            del os.environ[k]
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(snap)


def _real_settings(tmp: Path, **gemini: Any) -> Settings:
    s = pin_pre_flip(load_settings(toml_path=None, cwd=tmp))
    # The mocks and fitted thresholds here are for the pre-A1 correction model,
    # gemini-3.8-flash; the pin holds that model for them (the shipped default
    # is now gemini-3.1-flash-lite).
    gemini = {"correction_model": "gemini-3.8-flash", **gemini}
    return s.model_copy(
        update={
            "paths": PathsSettings(cache_dir=tmp / ".cache", output_dir=tmp / "outputs"),
            "gemini": s.gemini.model_copy(update=gemini),
        }
    )


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


#: Captured from the pre-cascade ``mark_question`` (HEAD 983c977e) with the
#: thinking levels below, so all three steps run: (task_tag, extra_cache_key,
#: cache key, sha256(system)[:16], sha256(user)[:16]).
_PINNED_OFF_CALLS = [
    (
        "correction",
        "q=1",
        "28fddd7b0ac12734",
        "f3c3b9df5d0c756b",
        "ab9ade96eb640d88",
    ),
    (
        "correction_borderline",
        "q=1:thinking",
        "5a2bc7b64efeea2c",
        "f3c3b9df5d0c756b",
        "4123b5e56538ed2d",
    ),
    (
        "escalation",
        "q=1:escalated",
        "774313362cbcf9a1",
        "f3c3b9df5d0c756b",
        "7b92a94030173706",
    ),
]


def _off_call_fingerprints(tmp: Path) -> list[tuple[str, str, str, str, str]]:
    settings = _real_settings(
        tmp,
        thinking_level_for={
            "correction": "low",
            "correction_borderline": "medium",
            "escalation": "high",
            "extraction": "minimal",
            "generation": "low",
        },
    )
    assert settings.gemini.cascade_enabled is False
    genai = MagicMock()
    genai.models.generate_content.side_effect = [_resp(0.5), _resp(0.6), _resp(0.95)]
    client = GeminiClient(settings, _genai_client=genai)
    seen: list[tuple[str, str, str, str, str]] = []
    real = client._structured_cache_key

    def _spy(**kwargs: Any) -> tuple[str, str]:
        model, key = real(**kwargs)
        seen.append(
            (
                kwargs["task_tag"],
                kwargs["extra_cache_key"],
                key,
                _sha(kwargs["system_prompt"]),
                _sha(kwargs["user_prompt"]),
            )
        )
        return model, key

    with patch.object(client, "_structured_cache_key", side_effect=_spy):
        AICorrector(client).mark_question(_question(), "gravity")
    return seen


def test_cascade_off_is_byte_identical(tmp_path: Path, isolated_env: None) -> None:
    assert _off_call_fingerprints(tmp_path) == _PINNED_OFF_CALLS


# ---------------------------------------------------------------------------
# Cascade on: triggers
# ---------------------------------------------------------------------------


def test_low_confidence_escalates_to_strong() -> None:
    result, fake = _run(
        _cascade(cascade_strong_model="strong-model"), [_mark(1, 0.5), _mark(2, 0.95)]
    )
    assert result.awarded_marks == 2
    assert _attempts(fake) == [
        ("first", "correction", None),
        ("escalation", "escalation", "strong-model"),
    ]
    assert all(c["question_id"] == "1" for c in fake.calls)
    assert fake.calls[1]["extra_cache_key"] == "q=1:cascade"
    # The strong model re-marks the original prompt, unprimed by the first pass.
    assert fake.calls[1]["user_prompt"] == fake.calls[0]["user_prompt"]


@pytest.mark.parametrize("strong", [None, ""])
def test_strong_model_falls_back_to_escalation_model(strong: str | None) -> None:
    _, fake = _run(_cascade(cascade_strong_model=strong), [_mark(1, 0.5), _mark(2, 0.95)])
    assert fake.calls[1]["model"] == "gemini-3.8-flash"


def test_high_confidence_does_not_escalate() -> None:
    result, fake = _run(_cascade(), [_mark(1, 0.95)])
    assert result.awarded_marks == 1
    assert _attempts(fake) == [("first", "correction", None)]


def test_disagreement_trigger_fires_on_mark_mismatch() -> None:
    result, fake = _run(
        _cascade(cascade_two_pass_disagreement=True),
        [_mark(1, 0.95), _mark(2, 0.95), _mark(2, 0.97)],
    )
    assert _attempts(fake) == [
        ("first", "correction", None),
        ("borderline", "correction", None),
        ("escalation", "escalation", "gemini-3.8-flash"),
    ]
    assert fake.calls[1]["extra_cache_key"] == "q=1:pass2"
    assert fake.calls[1]["user_prompt"] == fake.calls[0]["user_prompt"]
    assert result.confidence == 0.97


def test_disagreement_trigger_quiet_when_passes_agree() -> None:
    result, fake = _run(
        _cascade(cascade_two_pass_disagreement=True), [_mark(1, 0.95), _mark(1, 0.90)]
    )
    assert len(fake.calls) == 2
    # The first pass is the answer; the second only votes.
    assert result.confidence == 0.95


def test_disagreement_pass_skipped_when_confidence_already_fires() -> None:
    _, fake = _run(_cascade(cascade_two_pass_disagreement=True), [_mark(1, 0.5), _mark(2, 0.95)])
    assert [c["attempt"] for c in fake.calls] == ["first", "escalation"]


def test_unaddressed_point_trigger() -> None:
    _, fired = _run(
        _cascade(cascade_unaddressed_points=True), [_mark(1, 0.95, ("p1",)), _mark(1, 0.95)]
    )
    assert [c["attempt"] for c in fired.calls] == ["first", "escalation"]
    _, quiet = _run(_cascade(cascade_unaddressed_points=True), [_mark(1, 0.95, ("p1", "p2"))])
    assert len(quiet.calls) == 1


def test_unaddressed_trigger_inert_without_point_verdicts() -> None:
    _, fake = _run(_cascade(cascade_unaddressed_points=True), [_mark(1, 0.95)])
    assert len(fake.calls) == 1


def test_unaddressed_trigger_off_ignores_missing_points() -> None:
    _, fake = _run(_cascade(), [_mark(1, 0.95, ("p1",))])
    assert len(fake.calls) == 1


def test_borderline_retry_skipped_under_cascade() -> None:
    # Off: the low first pass gets the borderline thinking retry (and Step 2).
    off = _cascade(cascade_enabled=False)
    _, fake_off = _run(off, [_mark(1, 0.5), _mark(1, 0.6), _mark(1, 0.9)])
    assert "correction_borderline" in [c["task_tag"] for c in fake_off.calls]
    # On: straight to the strong model, no borderline thinking retry.
    _, fake_on = _run(_cascade(), [_mark(1, 0.5), _mark(1, 0.9)])
    assert [c["task_tag"] for c in fake_on.calls] == ["correction", "escalation"]


def test_cascade_off_labels_attempts() -> None:
    off = _cascade(cascade_enabled=False)
    _, fake = _run(off, [_mark(1, 0.5), _mark(1, 0.6), _mark(1, 0.9)])
    assert [c["attempt"] for c in fake.calls] == ["first", "borderline", "escalation"]
    assert all(c["question_id"] == "1" for c in fake.calls)


def test_fitted_threshold_per_model() -> None:
    fitted = _cascade(cascade_threshold_for={"cheap-model": 0.6})
    _, below_default = _run(fitted, [_mark(1, 0.7)])
    assert len(below_default.calls) == 1  # 0.7 clears the fitted 0.6
    _, under_fitted = _run(fitted, [_mark(1, 0.55), _mark(1, 0.9)])
    assert len(under_fitted.calls) == 2
    other = _cascade(cascade_threshold_for={"other-model": 0.1})
    _, falls_back = _run(other, [_mark(1, 0.7), _mark(1, 0.9)])
    assert len(falls_back.calls) == 2  # 0.7 < escalation_confidence_threshold 0.80


def test_unaddressed_trigger_short_circuits_pass2() -> None:
    _, fake = _run(
        _cascade(cascade_unaddressed_points=True, cascade_two_pass_disagreement=True),
        [_mark(1, 0.95, ("p1",)), _mark(2, 0.95)],
    )
    assert [c["attempt"] for c in fake.calls] == ["first", "escalation"]


def test_strong_call_skipped_when_it_repeats_the_first_pass() -> None:
    """Strong model and thinking equal to the first pass's: the re-mark would be
    the identical call, so it is not made (the non-cascade ``last_call`` guard)."""
    same = _cascade(cascade_strong_model="cheap-model")
    result, fake = _run(same, [_mark(1, 0.3)], same_thinking=True)
    assert result.awarded_marks == 1
    assert len(fake.calls) == 1
    # Same model, harder thinking: a different call, so it runs.
    _, harder = _run(same, [_mark(1, 0.3), _mark(2, 0.9)])
    assert [c["attempt"] for c in harder.calls] == ["first", "escalation"]


def test_leaf_log_marks_a_strong_call_skipped_as_identical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = tmp_path / "leaves.jsonl"
    monkeypatch.setenv(CASCADE_LEAF_LOG_ENV, str(log))
    _run(_cascade(cascade_strong_model="cheap-model"), [_mark(1, 0.3)], same_thinking=True)
    (entry,) = [json.loads(line) for line in log.read_text().splitlines()]
    assert entry["strong_skipped_identical"] is True
    assert entry["escalated"] is False
    assert entry["triggers"]["low_confidence"] is True


def test_no_strong_model_keeps_first_pass() -> None:
    result, fake = _run(_cascade(escalation_model=None), [_mark(1, 0.3)])
    assert result.awarded_marks == 1
    assert len(fake.calls) == 1


# ---------------------------------------------------------------------------
# Per-leaf log
# ---------------------------------------------------------------------------


def test_leaf_log_records_first_pass_and_triggers(
    tmp_path: Path, isolated_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = tmp_path / "leaves.jsonl"
    monkeypatch.setenv(CASCADE_LEAF_LOG_ENV, str(log))
    settings = _real_settings(
        tmp_path,
        cascade_enabled=True,
        cascade_two_pass_disagreement=True,
        cascade_unaddressed_points=True,
        cascade_threshold_for={"gemini-3.8-flash": 0.7},
    )
    genai = MagicMock()
    genai.models.generate_content.side_effect = [_resp(0.75), _resp(0.9)]
    client = GeminiClient(settings, _genai_client=genai)
    reset_process_counters()
    set_call_context(case_key="paperA")
    try:
        AICorrector(client).mark_question(_question(), "gravity")
    finally:
        set_call_context(case_key=None)
    (entry,) = [json.loads(line) for line in log.read_text().splitlines()]
    assert entry["case_key"] == "paperA"
    assert entry["question_id"] == "1"
    assert entry["model"] == "gemini-3.8-flash"
    assert entry["threshold"] == 0.7
    assert entry["confidence"] == 0.75
    assert entry["awarded_marks"] == 1
    assert entry["pass2_awarded_marks"] == 1
    assert entry["unaddressed_point_ids"] is None
    assert entry["triggers"] == {
        "low_confidence": False,
        "disagreement": False,
        "unaddressed": None,
    }
    assert entry["escalated"] is False
    assert entry["strong_awarded_marks"] is None
    assert entry["usd_2027"]["first"] > 0
    assert entry["usd_2027"]["pass2"] > 0
    assert entry["usd_2027"]["strong"] is None
    assert set(entry["latency_ms"]) == {"first", "pass2", "strong"}
    assert entry["run_token"] == correction_ai.CASCADE_RUN_TOKEN
    assert entry["strong_skipped_identical"] is False
    assert entry["config"] == {
        "model": "gemini-3.8-flash",
        "strong_model": "gemini-3.8-flash",
        "threshold": 0.7,
        "two_pass_disagreement": True,
        "unaddressed_points": True,
    }


def test_leaf_log_off_without_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(CASCADE_LEAF_LOG_ENV, raising=False)
    monkeypatch.chdir(tmp_path)
    _run(_cascade(), [_mark(1, 0.95)])
    assert list(tmp_path.iterdir()) == []


def test_module_exports_env_name() -> None:
    assert correction_ai.CASCADE_LEAF_LOG_ENV == "LEMELY_CASCADE_LEAF_LOG"


# ---------------------------------------------------------------------------
# Sweep
# ---------------------------------------------------------------------------

_TOKEN = "run-a"
_CONFIG: dict[str, Any] = {
    "model": "cheap-model",
    "strong_model": "gemini-3.8-flash",
    "threshold": 1.0,
    "two_pass_disagreement": True,
    "unaddressed_points": True,
}


def _leaf(
    case: str,
    qid: str,
    confidence: float,
    *,
    awarded: int = 1,
    strong: int = 1,
    pass2: int | None = 1,
    usd_first: float | None = 0.01,
    usd_strong: float | None = 0.10,
    skipped: bool = False,
    run_token: str = _TOKEN,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One logged leaf; a leaf with ``usd_strong`` was re-marked by the strong model."""
    escalated = usd_strong is not None
    return {
        "run_token": run_token,
        "config": config or _CONFIG,
        "case_key": case,
        "question_id": qid,
        "model": "cheap-model",
        "strong_model": "gemini-3.8-flash",
        "threshold": 1.0,
        "confidence": confidence,
        "awarded_marks": awarded,
        "pass2_awarded_marks": pass2,
        "unaddressed_point_ids": None,
        "triggers": {"low_confidence": True, "disagreement": None, "unaddressed": None},
        "escalated": escalated,
        "strong_skipped_identical": skipped,
        "strong_awarded_marks": strong if escalated else None,
        "strong_confidence": 0.9 if escalated else None,
        "usd_2027": {
            "first": usd_first,
            "pass2": 0.01 if pass2 is not None else None,
            "strong": usd_strong,
        },
        "latency_ms": {
            "first": 100,
            "pass2": 100 if pass2 is not None else None,
            "strong": 300 if escalated else None,
        },
    }


def _key(leaf: dict[str, Any]) -> str:
    return f"{leaf['case_key']}/{leaf['question_id']}"


def _returned(leaf: dict[str, Any]) -> int:
    """The raw marks the screen's cascade returned for *leaf*."""
    strong = leaf["strong_awarded_marks"]
    return int(strong if strong is not None else leaf["awarded_marks"])


def _qr(key: str, predicted: int, truth: int, *, qtype: str = "theory") -> dict[str, Any]:
    case, _, qid = key.rpartition("/")
    return {
        "case_key": case,
        "question_id": qid,
        "question_type": qtype,
        "predicted_marks": predicted,
        "truth_marks": truth,
        "confidence_score": 0.9,
        "needs_teacher_review": False,
        "scored": True,
        "extraction_confidence": None,
        "maximum_marks": 2,
        "review_reason": None,
    }


def _record(case: str, qid: str | None, tag: str, usd: float, ms: int = 100) -> dict[str, Any]:
    return {
        "case_key": case,
        "question_id": qid,
        "task_tag": tag,
        "usd_2027": usd,
        "latency_ms": ms,
        "attempt": "first" if qid else None,
        "model": "m",
        "parse_ok": True,
    }


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def _write_summary(
    path: Path,
    results: list[dict[str, Any]],
    *,
    usd: float,
    incomplete: tuple[str, ...] = (),
) -> None:
    """``summary.json`` and ``results.json`` for one run, mismarks derived from *results*."""
    path.mkdir(parents=True, exist_ok=True)
    scored = [r for r in results if r["scored"]]
    mismarked = sorted(
        f"{r['case_key']}/{r['question_id']}"
        for r in scored
        if r["predicted_marks"] != r["truth_marks"]
    )
    (path / "summary.json").write_text(
        json.dumps(
            {
                "usd_per_script_mean": usd,
                "latency_p95_ms": 1000.0,
                "mismarked_parts": mismarked,
                "scored_parts": len(scored),
                "id_match_rate": 1.0,
                "validity_rate": 1.0,
                "incomplete": list(incomplete),
            }
        )
    )
    (path / "results.json").write_text(json.dumps({"question_results": results}))


def _write_run(
    tmp: Path,
    *,
    upstream: dict[str, float],
    leaves: list[dict[str, Any]],
    truth: dict[str, int] | None = None,
    baseline_pred: dict[str, int] | None = None,
    screen_pred: dict[str, int] | None = None,
    mcq: tuple[str, ...] = (),
    screen_incomplete: tuple[str, ...] = (),
    extra_screen_results: list[dict[str, Any]] | None = None,
    baseline_correction_usd: float = 0.10,
) -> tuple[Path, Path]:
    """Lay out ``<tmp>/{baseline,screen}`` and ``<tmp>/aa_floor.json`` (floor 0).

    Truth defaults to the screen's returned marks (every screen mark right);
    the baseline predicts *baseline_pred*, else the truth. *mcq* parts are
    scored and right in both runs. The baseline pays ``upstream[case]`` once
    per case and ``baseline_correction_usd`` per leaf.
    """
    baseline, screen = tmp / "baseline", tmp / "screen"
    truth = {**{_key(leaf): _returned(leaf) for leaf in leaves}, **(truth or {})}
    base_pred = {**truth, **(baseline_pred or {})}
    final = {**{_key(leaf): _returned(leaf) for leaf in leaves}, **(screen_pred or {})}
    screen_results = [_qr(_key(leaf), final[_key(leaf)], truth[_key(leaf)]) for leaf in leaves]
    base_results = [_qr(_key(leaf), base_pred[_key(leaf)], truth[_key(leaf)]) for leaf in leaves]
    for key in mcq:
        screen_results.append(_qr(key, 1, 1, qtype="mcq"))
        base_results.append(_qr(key, 1, 1, qtype="mcq"))
    rows: list[dict[str, Any]] = []
    per_case: dict[str, float] = {}
    for case, usd in upstream.items():
        rows.append(_record(case, None, "extraction", usd))
        per_case[case] = usd
    for leaf in leaves:
        rows.append(
            _record(leaf["case_key"], leaf["question_id"], "correction", baseline_correction_usd)
        )
        per_case[leaf["case_key"]] += baseline_correction_usd
    _write_summary(baseline, base_results, usd=sum(per_case.values()) / len(per_case))
    _write_summary(
        screen,
        screen_results + (extra_screen_results or []),
        usd=0.0,
        incomplete=screen_incomplete,
    )
    _write_jsonl(baseline / "records.jsonl", rows)
    _write_jsonl(screen / "cascade_leaves.jsonl", leaves)
    (tmp / "aa_floor.json").write_text(json.dumps({"aa_floor": 0}))
    return screen, baseline


def _inputs(screen: Path, baseline: Path) -> cascade_sweep.Inputs:
    return cascade_sweep.load_inputs(screen_dir=screen, baseline_dir=baseline)


def test_sweep_picks_cheapest_passing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Two cases, two leaves each, every leaf re-marked by the strong model in
    the logging screen (all strong marks right). The cheap model is wrong on
    c1/q1 (confidence 0.60) and c2/q1 (0.70). The saving is big-tier, which
    allows ceil(2% of 4) = 1 extra mismark, so the cheapest pass is 0.61: it
    escalates c1/q1 alone. Below that both mismarks stand; above 0.70 a second
    strong call is paid for."""
    screen, baseline = _write_run(
        tmp_path,
        upstream={"c1": 0.05, "c2": 0.05},
        leaves=[
            _leaf("c1", "q1", 0.60, strong=2),
            _leaf("c1", "q2", 0.90),
            _leaf("c2", "q1", 0.70, strong=2),
            _leaf("c2", "q2", 0.95),
        ],
    )
    best = cascade_sweep.sweep(_inputs(screen, baseline))
    assert best is not None
    assert best.combo == cascade_sweep.Combo(0.61, False, False)
    assert best.verdict.passed
    # c1: extraction 0.05 + two cheap passes 0.02 + one logged strong 0.10; c2: no strong.
    assert best.summary.usd_per_script_mean == pytest.approx((0.17 + 0.07) / 2)
    assert best.summary.mismarked_parts == frozenset({"c2/q1"})
    assert best.proxied == 0

    code = cascade_sweep.main(["--screen", str(screen), "--baseline", str(baseline)])
    out = capsys.readouterr().out
    assert code == 0
    assert "threshold=0.61" in out
    assert "proxied=0" in out
    assert '"cheap-model": 0.61' in out
    # c1/q2 and c2/q2 keep a cheap mark the screen did not return, judged right:
    # 1 extra mismark + 2 = 3 > 1 allowed.
    assert "approximated judged correct: 2" in out
    assert "FRAGILE" in out


def test_sweep_reports_none_when_nothing_passes(tmp_path: Path) -> None:
    # Baseline $0.012/script: the cheap pass alone saves 17%, a small-tier
    # saving that allows no extra mismark; anything more costs more than baseline.
    screen, baseline = _write_run(
        tmp_path,
        upstream={"c1": 0.0},
        leaves=[_leaf("c1", "q1", 0.995, strong=2)],
        baseline_correction_usd=0.012,
    )
    assert cascade_sweep.sweep(_inputs(screen, baseline)) is None
    assert cascade_sweep.main(["--screen", str(screen), "--baseline", str(baseline)]) == 1


def test_sweep_judges_every_mark_against_truth(tmp_path: Path) -> None:
    """The strong re-mark (2) was wrong and the cheap mark (1) right: keeping
    the cheap mark is correct, escalating is a mismark. Nothing is unknown."""
    screen, baseline = _write_run(
        tmp_path,
        upstream={"c1": 0.0},
        leaves=[_leaf("c1", "q1", 0.5, strong=2, usd_strong=0.07)],
        truth={"c1/q1": 1},
    )
    inputs = _inputs(screen, baseline)
    keep = cascade_sweep.simulate(inputs, cascade_sweep.Combo(0.4, False, False))
    assert keep.summary.mismarked_parts == frozenset()
    assert keep.unknown == 0
    # The cheap mark differs from the returned one, so it is judged raw.
    assert keep.approximated == 1
    escalate = cascade_sweep.simulate(inputs, cascade_sweep.Combo(0.9, False, False))
    assert escalate.summary.mismarked_parts == frozenset({"c1/q1"})
    assert escalate.summary.usd_per_script_mean == pytest.approx(0.08)
    assert escalate.approximated == 0


def test_sweep_strong_mark_uses_the_screen_final_mark(tmp_path: Path) -> None:
    screen, baseline = _write_run(
        tmp_path,
        upstream={"c1": 0.0},
        leaves=[_leaf("c1", "q1", 0.5, strong=2)],
        baseline_pred={"c1/q1": 0},
    )
    inputs = _inputs(screen, baseline)
    escalate = cascade_sweep.simulate(inputs, cascade_sweep.Combo(0.9, False, False))
    # The screen's own strong re-mark was right, whatever the baseline did.
    assert escalate.summary.mismarked_parts == frozenset()
    keep = cascade_sweep.simulate(inputs, cascade_sweep.Combo(0.4, False, False))
    assert keep.summary.mismarked_parts == frozenset({"c1/q1"})


def test_sweep_other_response_is_approximated_even_with_equal_raw_marks(tmp_path: Path) -> None:
    """The screen returned the strong re-mark. Keeping the cheap pass is judged
    on its raw mark even when that equals the strong raw mark: post-processing
    depends on more than the raw marks, so the screen's final is not borrowed."""
    screen, baseline = _write_run(
        tmp_path,
        upstream={"c1": 0.0},
        leaves=[_leaf("c1", "q1", 0.5, awarded=2, strong=2)],
        screen_pred={"c1/q1": 1},
        truth={"c1/q1": 1},
    )
    inputs = _inputs(screen, baseline)
    keep = cascade_sweep.simulate(inputs, cascade_sweep.Combo(0.4, False, False))
    assert keep.approximated == 1
    assert keep.approximated_correct == 0
    assert keep.summary.mismarked_parts == frozenset({"c1/q1"})
    escalate = cascade_sweep.simulate(inputs, cascade_sweep.Combo(0.9, False, False))
    assert escalate.approximated == 0
    assert escalate.summary.mismarked_parts == frozenset()


def test_sweep_refuses_a_leaf_marked_twice_in_one_run(tmp_path: Path) -> None:
    screen, baseline = _write_run(
        tmp_path,
        upstream={"c1": 0.0},
        leaves=[_leaf("c1", "q1", 0.5), _leaf("c1", "q1", 0.6)],
    )
    with pytest.raises(ValueError, match="marked twice"):
        _inputs(screen, baseline)


def test_loo_filters_incomplete_entries_by_case(tmp_path: Path) -> None:
    screen, baseline = _write_run(
        tmp_path,
        upstream={"c1": 0.0, "c2": 0.0},
        leaves=[_leaf("c1", "q1", 0.5), _leaf("c2", "q1", 0.5)],
        screen_incomplete=("c1 (unpriced model x)",),
    )
    inputs = _inputs(screen, baseline)
    combo = cascade_sweep.Combo(0.9, False, False)
    assert cascade_sweep.simulate(inputs, combo).summary.incomplete == ("c1 (unpriced model x)",)
    assert cascade_sweep.simulate(inputs, combo, held_out="c1").summary.incomplete == ()
    assert cascade_sweep.simulate(inputs, combo, held_out="c2").summary.incomplete == (
        "c1 (unpriced model x)",
    )
    _, verdict = cascade_sweep.judge_combo(inputs, combo, held_out="c1")
    assert not any("incomplete" in reason for reason in verdict.reasons)
    _, verdict = cascade_sweep.judge_combo(inputs, combo, held_out="c2")
    assert any("incomplete" in reason for reason in verdict.reasons)


def test_sweep_returned_response_takes_the_screen_final_mark(tmp_path: Path) -> None:
    """Post-processing turned the strong re-mark's raw 2 into a final 1, which
    is the truth: escalating is right, judged on the final mark, not the raw one."""
    screen, baseline = _write_run(
        tmp_path,
        upstream={"c1": 0.0},
        leaves=[_leaf("c1", "q1", 0.5, awarded=0, strong=2)],
        screen_pred={"c1/q1": 1},
        truth={"c1/q1": 1},
    )
    inputs = _inputs(screen, baseline)
    escalate = cascade_sweep.simulate(inputs, cascade_sweep.Combo(0.9, False, False))
    assert escalate.summary.mismarked_parts == frozenset()
    assert escalate.approximated == 0
    keep = cascade_sweep.simulate(inputs, cascade_sweep.Combo(0.4, False, False))
    assert keep.summary.mismarked_parts == frozenset({"c1/q1"})
    assert keep.approximated == 1


@pytest.mark.parametrize(("logged_strong", "proxy"), [(0.20, 0.20), (0.05, 0.10)])
def test_sweep_proxies_unlogged_strong_never_cheap(
    tmp_path: Path, logged_strong: float, proxy: float
) -> None:
    """A leaf with no logged strong call costs the baseline's correction cost
    scaled by max(1, mean logged-strong / baseline ratio), and takes the
    baseline's mark."""
    screen, baseline = _write_run(
        tmp_path,
        upstream={"c1": 0.0},
        leaves=[
            _leaf("c1", "q1", 0.5, usd_strong=logged_strong),
            _leaf("c1", "q2", 0.5, usd_strong=None),
        ],
        baseline_pred={"c1/q2": 0},
    )
    sim = cascade_sweep.simulate(_inputs(screen, baseline), cascade_sweep.Combo(0.9, False, False))
    assert sim.proxied == 1
    assert sim.summary.usd_per_script_mean == pytest.approx(0.01 + logged_strong + 0.01 + proxy)
    assert sim.summary.mismarked_parts == frozenset({"c1/q2"})


def test_sweep_refuses_to_proxy_without_any_logged_strong(tmp_path: Path) -> None:
    screen, baseline = _write_run(
        tmp_path, upstream={"c1": 0.0}, leaves=[_leaf("c1", "q1", 0.5, usd_strong=None)]
    )
    with pytest.raises(ValueError, match="logged strong"):
        _inputs(screen, baseline)


def test_sweep_treats_a_skipped_identical_strong_call_as_the_first_pass(tmp_path: Path) -> None:
    """The strong call would have repeated the first pass, so the first pass is
    the strong result: no proxy, no extra cost, the cheap mark stands."""
    screen, baseline = _write_run(
        tmp_path,
        upstream={"c1": 0.0},
        leaves=[_leaf("c1", "q1", 0.5, awarded=1, usd_strong=None, skipped=True)],
        baseline_pred={"c1/q1": 0},
    )
    inputs = _inputs(screen, baseline)  # no logged strong anywhere, yet nothing to proxy
    sim = cascade_sweep.simulate(inputs, cascade_sweep.Combo(0.9, False, False))
    assert sim.proxied == 0
    assert sim.summary.usd_per_script_mean == pytest.approx(0.01)
    assert sim.summary.mismarked_parts == frozenset()


def test_sweep_missing_pass2_is_pessimistic(tmp_path: Path) -> None:
    """A combination that needs a second pass the screen never ran assumes the
    trigger fired: the second pass and the strong call are paid for."""
    screen, baseline = _write_run(
        tmp_path, upstream={"c1": 0.0}, leaves=[_leaf("c1", "q1", 0.95, pass2=None)]
    )
    sim = cascade_sweep.simulate(_inputs(screen, baseline), cascade_sweep.Combo(0.5, True, False))
    assert sim.unknown == 1
    # first 0.01 + assumed pass2 0.01 + logged strong 0.10
    assert sim.summary.usd_per_script_mean == pytest.approx(0.12)


@pytest.mark.parametrize(
    "second",
    [
        _leaf("c1", "q2", 0.9, run_token="run-b"),
        _leaf("c1", "q2", 0.9, config={**_CONFIG, "threshold": 0.8}),
    ],
)
def test_sweep_refuses_a_log_from_two_runs(tmp_path: Path, second: dict[str, Any]) -> None:
    screen, baseline = _write_run(
        tmp_path, upstream={"c1": 0.0}, leaves=[_leaf("c1", "q1", 0.5), second]
    )
    with pytest.raises(ValueError, match="more than one"):
        _inputs(screen, baseline)


def test_sweep_refuses_a_scored_theory_part_without_a_leaf_line(tmp_path: Path) -> None:
    screen, baseline = _write_run(
        tmp_path,
        upstream={"c1": 0.0},
        leaves=[_leaf("c1", "q1", 0.5)],
        extra_screen_results=[_qr("c1/q9", 1, 1)],
    )
    with pytest.raises(ValueError, match="c1/q9"):
        _inputs(screen, baseline)


def test_sweep_cross_check_excludes_mcq_and_unscored(tmp_path: Path) -> None:
    unscored = {**_qr("c1/q8", 0, 1), "scored": False}
    screen, baseline = _write_run(
        tmp_path,
        upstream={"c1": 0.0},
        leaves=[_leaf("c1", "q1", 0.5)],
        mcq=("c1/m1",),
        extra_screen_results=[unscored],
    )
    inputs = _inputs(screen, baseline)
    assert inputs.screen_scored_by_case == {"c1": 2}


def test_sweep_refuses_results_without_case_keys(tmp_path: Path) -> None:
    screen, baseline = _write_run(tmp_path, upstream={"c1": 0.0}, leaves=[_leaf("c1", "q1", 0.5)])
    data = json.loads((screen / "results.json").read_text())
    for row in data["question_results"]:
        del row["case_key"]
    (screen / "results.json").write_text(json.dumps(data))
    with pytest.raises(ValueError, match="case_key"):
        _inputs(screen, baseline)


def test_sweep_refuses_missing_first_pass_cost(tmp_path: Path) -> None:
    screen, baseline = _write_run(
        tmp_path, upstream={"c1": 0.0}, leaves=[_leaf("c1", "q1", 0.5, usd_first=None)]
    )
    with pytest.raises(ValueError, match="first"):
        _inputs(screen, baseline)


def test_sweep_refuses_unpriced_baseline_record(tmp_path: Path) -> None:
    screen, baseline = _write_run(
        tmp_path, upstream={"c1": float("nan")}, leaves=[_leaf("c1", "q1", 0.5)]
    )
    with pytest.raises(ValueError, match="unpriced"):
        _inputs(screen, baseline)


def test_loo_rejects_combination_failing_a_held_out_case(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """c1 is cheap to run, so it carries the whole-run saving into the big tier,
    where 1 extra mismark (c2/q1, cheap confidence 0.70) is allowed. Holding c1
    out drops the saving to the small tier, which allows none, so leave-one-out
    must escalate c2/q1: threshold 0.71. Each case also has a scored MCQ part,
    which counts towards the exact per-case scored parts."""
    screen, baseline = _write_run(
        tmp_path,
        upstream={"c1": 0.0, "c2": 0.25, "c3": 0.25},
        leaves=[
            _leaf("c1", "q1", 0.95),
            _leaf("c2", "q1", 0.70, strong=2),
            _leaf("c3", "q1", 0.95),
        ],
        mcq=("c1/m1", "c2/m1", "c3/m1"),
    )
    inputs = _inputs(screen, baseline)
    assert cascade_sweep.baseline_summary(inputs, "c1").scored_parts == 4
    whole = cascade_sweep.sweep(inputs)
    assert whole is not None
    assert whole.combo == cascade_sweep.Combo(0.50, False, False)
    sim, verdict = cascade_sweep.judge_combo(inputs, whole.combo, held_out="c1")
    assert sim.summary.scored_parts == 4
    assert not verdict.passed
    assert verdict.tier == "small"

    loo = cascade_sweep.sweep(inputs, loo=True)
    assert loo is not None
    assert loo.combo == cascade_sweep.Combo(0.71, False, False)
    assert loo.summary.usd_per_script_mean == pytest.approx((0.01 + 0.36 + 0.26) / 3)
    assert [case for case, _ in loo.loo] == ["c1", "c2", "c3"]
    assert all(v.passed for _, v in loo.loo)

    code = cascade_sweep.main(["--screen", str(screen), "--baseline", str(baseline), "--loo"])
    out = capsys.readouterr().out
    assert code == 0
    assert "threshold=0.71" in out
    assert "held out c1: PASS" in out
