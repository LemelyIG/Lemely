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
        for qid, m in (marks if marks is not None else {"1a": 2, "1b": 1, "1c": 0}).items()
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
    max_marks: int = 2,
) -> CorrectedQuestion:
    return CorrectedQuestion(
        question_id=qid,
        awarded_marks=awarded,
        maximum_marks=max_marks,
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
    f = rs.real_summary_fields([run1, run2], ["a", "b"])
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
        rs.real_summary_fields([], ["a"])


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
    fields = rs.real_summary_fields([[result]], ["k"])
    assert dict(fields["real_usd_max_by_script"])["k"] == pytest.approx(0.12)  # type: ignore[arg-type]


def _ok(key: str = "a") -> RealScriptResult:
    return _script(key, [_leaf("1", 2, 2)], 0.01)


def test_summary_flags_a_script_a_run_lacks() -> None:
    f = rs.real_summary_fields([[_ok("a"), _ok("b")], [_ok("a")]], ["a", "b"])
    assert f["real_scripts"] == ("a", "b")
    assert f["real_incomplete"] == ("real-2:b (no result)",)


def test_a_script_with_no_result_has_no_figures_not_zero() -> None:
    f = rs.real_summary_fields([[_ok("a")], [_ok("a")]], ["a", "b"])
    for name in (
        "real_usd_by_script",
        "real_usd_max_by_script",
        "real_latency_by_script",
        "real_escalation_usd_by_script",
    ):
        figures = dict(f[name])  # type: ignore[arg-type]
        assert list(figures) == ["a", "b"], name
        assert figures["a"] is not None, name
        assert figures["b"] is None, name


def test_summary_real_scripts_are_the_expected_keys_not_the_first_run() -> None:
    f = rs.real_summary_fields([[_ok("a")]], ["a", "b"])
    assert f["real_scripts"] == ("a", "b")
    assert f["real_incomplete"] == ("real-1:b (no result)",)


@pytest.mark.parametrize(
    ("runs", "keys"),
    [
        ([[]], ["a"]),
        ([[_ok("a"), _ok("a")]], ["a"]),
        ([[_ok("a"), _ok("z")]], ["a"]),
        ([[_ok("a")]], []),
        ([[_ok("a")]], ["a", "a"]),
    ],
)
def test_summary_rejects_malformed_runs(
    runs: list[list[RealScriptResult]], keys: list[str]
) -> None:
    with pytest.raises(ValueError):
        rs.real_summary_fields(runs, keys)


def test_unscored_leaves_carry_no_confidence(tmp_path: Path) -> None:
    script = _frozen(tmp_path)
    correction = _result(
        _cq("1a", 2),
        _cq("1b", 0, source="dropped", review=True, conf=0.0),
        _cq("1c", 0, source="blank", conf=0.0),
    )
    result = rs.score_script(
        script, correction, [], latency_ms=0.0, failure=None, escalations=[], cascade_enabled=False
    )
    by = {leaf.question_id: leaf for leaf in result.leaves}
    for qid in ("1b", "1c"):
        assert by[qid].confidence is None and by[qid].pre_escalation_confidence is None
    assert by["1a"].confidence == 0.9


def test_max_marks_mismatch_makes_the_script_incomplete(tmp_path: Path) -> None:
    script = _frozen(tmp_path)
    correction = _result(_cq("1a", 2, max_marks=3), _cq("1b", 1), _cq("1c", 0))
    result = rs.score_script(
        script, correction, [], latency_ms=0.0, failure=None, escalations=[], cascade_enabled=False
    )
    assert result.incomplete == "max marks differ on 1a: scheme 3, reference 2"


def test_duplicate_question_id_makes_the_script_incomplete(tmp_path: Path) -> None:
    script = _frozen(tmp_path)
    correction = _result(_cq("1a", 2), _cq("1a", 0), _cq("1b", 1), _cq("1c", 0))
    result = rs.score_script(
        script, correction, [], latency_ms=0.0, failure=None, escalations=[], cascade_enabled=False
    )
    assert result.incomplete == "duplicate question_id in marking output: 1a"


def test_loader_refuses_a_frozen_marker_that_differs_from_the_manifest(tmp_path: Path) -> None:
    script = _frozen(tmp_path)
    (script.reference_path.parent / ref.FROZEN_MARKER).write_text("deadbeef\n", encoding="utf-8")
    with pytest.raises(ReferenceDrift, match=r"FROZEN marker .* differs from the manifest"):
        rs.load_real_scripts(tmp_path / ref.MANIFEST_FILE)


class _FakeScheme:
    @classmethod
    def model_validate_json(cls, text: str) -> str:
        return f"parsed:{text}"


def _fake_scheme(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("lemely.core.loose_schemas.MarkScheme", _FakeScheme)


def test_mark_real_script_runs_every_stage_inside_the_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import contextlib
    from types import SimpleNamespace

    script = _frozen(tmp_path)
    script.scheme_path.write_text("SCHEME-TEXT", encoding="utf-8")
    _fake_scheme(monkeypatch)
    events: list[str] = []
    seen: dict[str, object] = {}

    @contextlib.contextmanager
    def fake_scope(settings: object, *, script_key: str):
        seen["scope_key"] = script_key
        events.append("enter")
        yield
        events.append("exit")

    class FakeMeta:
        def __init__(self, client: object) -> None:
            seen["meta_client"] = client

        def __call__(self, path: Path) -> None:
            events.append("meta")
            seen["meta_path"] = path

    class FakeExtractor:
        def __init__(self, client: object) -> None:
            pass

        def __call__(self, *, scan_path: Path, mark_scheme: object) -> str:
            events.append("extract")
            seen["scheme"] = mark_scheme
            return "extracted"

    sentinel = object()

    def fake_correct(**kwargs: object) -> object:
        events.append("correct")
        seen["correct"] = kwargs
        return sentinel

    monkeypatch.setattr("lemely.io.gemini.script_cost_scope", fake_scope)
    monkeypatch.setattr("lemely.io.scan_metadata.ScanMetadataExtractor", FakeMeta)
    monkeypatch.setattr("lemely.io.answer_extraction.GeminiAnswerExtractor", FakeExtractor)
    monkeypatch.setattr("lemely.io.correction_ai.correct_paper", fake_correct)
    options = object()
    settings = SimpleNamespace(
        grading=SimpleNamespace(marking_options=lambda: options),
        gemini=SimpleNamespace(adjudication_model=None),
    )
    client = object()

    assert rs.mark_real_script(script, client, settings) is sentinel  # type: ignore[arg-type]
    assert events == ["enter", "meta", "extract", "correct", "exit"]
    assert seen["scope_key"] == "real:k" and seen["meta_path"] == script.scan_path
    correct = seen["correct"]
    assert isinstance(correct, dict)
    assert correct["options"] is options and correct["extracted_answers"] == "extracted"
    assert seen["scheme"] == "parsed:SCHEME-TEXT"
    assert correct["mark_scheme"] is seen["scheme"] and correct["gemini_client"] is client


def test_mark_real_script_scan_metadata_failure_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import contextlib
    from types import SimpleNamespace

    script = _frozen(tmp_path)
    script.scheme_path.write_text("SCHEME-TEXT", encoding="utf-8")
    _fake_scheme(monkeypatch)
    monkeypatch.setattr(
        "lemely.io.gemini.script_cost_scope", lambda *a, **k: contextlib.nullcontext()
    )

    class Boom:
        def __init__(self, client: object) -> None:
            pass

        def __call__(self, path: Path) -> None:
            raise TimeoutError("meta")

    monkeypatch.setattr("lemely.io.scan_metadata.ScanMetadataExtractor", Boom)
    settings = SimpleNamespace(grading=SimpleNamespace(marking_options=lambda: None))
    with pytest.raises(TimeoutError):
        rs.mark_real_script(script, object(), settings)  # type: ignore[arg-type]


def test_loader_refuses_an_empty_reference(tmp_path: Path) -> None:
    d = tmp_path / "k"
    ref.write_reference(d / ref.REFERENCE_FILE, [])
    (d / ref.SCHEME_FILE).write_text("{}", encoding="utf-8")
    scan = tmp_path / "k.pdf"
    scan.write_bytes(b"%PDF k")
    ref.freeze(
        d,
        key="k",
        scan_path=scan,
        sources={},
        expected_total=None,
        manifest_path=tmp_path / ref.MANIFEST_FILE,
    )
    with pytest.raises(ReferenceDrift, match=r"reference .* has no leaves"):
        rs.load_real_scripts(tmp_path / ref.MANIFEST_FILE)


def test_mark_real_script_passes_pages_only_with_adjudication(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from lemely.accuracy.cost_ladder.runner import apply_overrides
    from lemely.io import answer_extraction, correction_ai, rasterise, scan_metadata
    from lemely.runtime.config import Settings

    script = _frozen(tmp_path)
    script.scheme_path.write_text("SCHEME-TEXT", encoding="utf-8")
    _fake_scheme(monkeypatch)
    seen: list[object] = []
    monkeypatch.setattr(scan_metadata, "ScanMetadataExtractor", lambda client: lambda path: None)
    monkeypatch.setattr(
        answer_extraction,
        "GeminiAnswerExtractor",
        lambda client: lambda scan_path, mark_scheme: "X",
    )
    monkeypatch.setattr(rasterise, "rasterise_scan_to_pages", lambda path: ["PAGE"])
    monkeypatch.setattr(
        correction_ai, "correct_paper", lambda **kw: seen.append(kw["pages"]) or "R"
    )
    rs.mark_real_script(script, object(), Settings())  # type: ignore[arg-type]
    on = apply_overrides(Settings(), {"gemini.adjudication_model": "claude-sonnet-5-5"})
    rs.mark_real_script(script, object(), on)  # type: ignore[arg-type]
    assert seen == [None, ["PAGE"]]


class _ReplyClient:
    """Fake client: generate_structured returns the scripted reply for its call."""

    def __init__(self, reply: object) -> None:
        self.reply = reply
        self.kwargs: list[dict[str, object]] = []

    def _active_model(self, model: str | None, task_tag: str | None) -> str:
        return model or f"model-for-{task_tag}"

    def generate_structured(self, **kwargs: object) -> object:
        self.kwargs.append(kwargs)
        return self.reply


def test_reply_log_records_correction_family_only() -> None:
    from lemely.core.schemas import AIMarkResponse
    from lemely.io.adjudication import AdjudicationReply

    mark = AIMarkResponse(awarded_marks=1, confidence=0.6, feedback="because")
    adj = AdjudicationReply(awarded_marks=2, confidence=0.8, rationale="sonnet says")
    client = _ReplyClient(mark)
    log = rs.ReplyLog()
    log.wrap(client)
    log.current = "k"
    for tag, attempt in (
        ("correction", "first"),
        ("correction_borderline", "borderline"),
        ("escalation", "escalation"),
    ):
        out = client.generate_structured(task_tag=tag, question_id="1a", attempt=attempt)
        assert out is mark  # the return value is unchanged
    client.reply = adj
    client.generate_structured(task_tag="adjudication", question_id="1a", model="claude-sonnet-x")
    # Not recorded: another stage, and a correction call with no question_id.
    client.generate_structured(task_tag="extraction", question_id="1a")
    client.generate_structured(task_tag="correction", question_id=None)
    assert [r.task_tag for r in log.rows] == [
        "correction",
        "correction_borderline",
        "escalation",
        "adjudication",
    ]
    first, last = log.rows[0], log.rows[-1]
    assert (first.case_key, first.question_id, first.attempt) == ("k", "1a", "first")
    assert (first.model, first.mark, first.confidence) == ("model-for-correction", 1, 0.6)
    assert first.rationale == "because" and first.reply["feedback"] == "because"
    assert (last.model, last.mark, last.rationale) == ("claude-sonnet-x", 2, "sonnet says")
    assert log.for_script("k") == log.rows and log.for_script("other") == []


def test_reply_log_leaves_a_stand_in_client_alone() -> None:
    stand_in = object()
    rs.ReplyLog().wrap(stand_in)
    assert not hasattr(stand_in, "generate_structured")


def _reply(tag: str, mark: int, qid: str = "1a", attempt: str | None = None) -> rs.MarkReply:
    return rs.MarkReply("k", qid, tag, attempt, "m", mark, 0.5, "r", {})


def test_score_script_step_marks(tmp_path: Path) -> None:
    script = _frozen(tmp_path, marks={"1a": 2, "1b": 1, "1c": 1, "1d": 1})
    correction = _result(
        _cq("1a", 2),
        _cq("1b", 1),
        _cq("1c", 0, source="dropped", review=True),
        _cq("1d", 1),
    )
    replies = [
        _reply("correction", 0, "1a", "first"),
        _reply("correction_borderline", 1, "1a", "borderline"),
        _reply("escalation", 2, "1a", "escalation"),
        _reply("correction", 1, "1b", "first"),
        _reply("correction", 1, "1c", "first"),
        _reply("correction", 5, "1d", "first"),  # above the leaf's max marks
    ]
    result = rs.score_script(
        script,
        correction,
        [],
        latency_ms=5.0,
        failure=None,
        escalations=[],
        cascade_enabled=False,
        replies=replies,
    )
    by = {leaf.question_id: leaf for leaf in result.leaves}

    def steps(qid: str) -> tuple[int | None, ...]:
        leaf = by[qid]
        return (
            leaf.first_pass_mark,
            leaf.post_borderline_mark,
            leaf.post_escalation_mark,
            leaf.post_adjudication_mark,
        )

    assert steps("1a") == (0, 1, 2, 2)  # adjudication absent: the previous step
    assert steps("1b") == (1, 1, 1, 1)
    assert steps("1c") == (None, None, None, None)  # a dropped leaf is not marker-scored
    assert steps("1d") == (2, 2, 2, 2)  # a reply of 5 is clamped to the reference maximum, 2
    assert by["1a"].predicted == 2


def test_old_real_results_load_without_step_marks(tmp_path: Path) -> None:
    path = tmp_path / "real_results.json"
    rs.write_real_results(path, [_script("a", [_leaf("1", 2, 2)], 0.04)])
    rows = json.loads(path.read_text())
    for leaf in rows[0]["leaves"]:
        for key in (
            "first_pass_mark",
            "post_borderline_mark",
            "post_escalation_mark",
            "post_adjudication_mark",
        ):
            del leaf[key]
    path.write_text(json.dumps(rows))
    (loaded,) = rs.read_real_results(path)
    assert loaded.leaves[0].first_pass_mark is None
    assert loaded.leaves[0].post_adjudication_mark is None


def test_keep_higher_makes_post_borderline_the_held_mark(tmp_path: Path) -> None:
    script = _frozen(tmp_path, marks={"1a": 2})
    replies = [_reply("correction", 2, "1a", "first"), _reply("correction_borderline", 1, "1a")]
    kw: dict[str, object] = {
        "latency_ms": 5.0,
        "failure": None,
        "escalations": [],
        "cascade_enabled": False,
        "replies": replies,
    }
    correction = _result(_cq("1a", 2))
    plain = rs.score_script(script, correction, [], **kw).leaves[0]  # type: ignore[arg-type]
    kept = rs.score_script(script, correction, [], keep_higher=True, **kw).leaves[0]  # type: ignore[arg-type]
    assert plain.post_borderline_mark == 1  # the retry replaced the first mark
    assert kept.post_borderline_mark == 2  # H2a keeps the higher


def test_step_marks_median() -> None:
    def post_borderline(first: int, *borderline: int, median: bool = True) -> int | None:
        replies = [
            _reply("correction", first, "1a", "first"),
            *(_reply("correction_borderline", m, "1a") for m in borderline),
        ]
        return rs._step_marks(replies, "1a", 2, median=median)[1]

    assert post_borderline(1, 0, 2) == 1
    assert post_borderline(1, 0, 2, median=False) == 2  # the last reply
    assert post_borderline(0, 0) == 0
    assert post_borderline(2, 0, 1) == 1


def test_median_makes_post_borderline_the_median_mark(tmp_path: Path) -> None:
    script = _frozen(tmp_path, marks={"1a": 2})
    replies = [
        _reply("correction", 1, "1a", "first"),
        _reply("correction_borderline", 0, "1a"),
        _reply("correction_borderline", 2, "1a"),
    ]
    kw: dict[str, object] = {
        "latency_ms": 5.0,
        "failure": None,
        "escalations": [],
        "cascade_enabled": False,
        "replies": replies,
    }
    correction = _result(_cq("1a", 2))
    plain = rs.score_script(script, correction, [], **kw).leaves[0]  # type: ignore[arg-type]
    med = rs.score_script(script, correction, [], median=True, **kw).leaves[0]  # type: ignore[arg-type]
    assert plain.post_borderline_mark == 2  # the last reply
    assert med.post_borderline_mark == 1  # median_low of 1, 0, 2


def test_reply_log_records_stated_mark_when_present() -> None:
    from types import SimpleNamespace

    reply = SimpleNamespace(
        awarded_marks=1,
        confidence=0.5,
        feedback="f",
        stated_mark=2,
        model_dump=lambda mode: {"stated_mark": 2},
    )
    client = _ReplyClient(reply)
    log = rs.ReplyLog()
    log.wrap(client)
    log.current = "k"
    client.generate_structured(task_tag="correction", question_id="1a")
    client.reply = SimpleNamespace(
        awarded_marks=1, confidence=0.5, feedback="f", model_dump=lambda mode: {}
    )
    client.generate_structured(task_tag="correction", question_id="1b")
    assert [r.stated_mark for r in log.rows] == [2, None]


def test_reason_first_rows_carry_the_checked_mark_and_the_stated_one() -> None:
    from types import SimpleNamespace

    from lemely.core.loose_schemas import AnswerPoint, Question, QuestionType
    from lemely.core.schemas import AIMarkResponseReasoned, PointVerdictReasoned

    question = Question.model_construct(
        id="1a",
        marks=2,
        type=QuestionType.EXPLANATION,
        answer_points=[
            AnswerPoint(id="p1", point="gravity", marks=1),
            AnswerPoint(id="p2", point="mass", marks=1),
        ],
        select_count=None,
        parts=[],
        assessment_objectives=[],
        rejected_answers=[],
        ignored_answers=[],
    )
    reply = AIMarkResponseReasoned(
        awarded_marks=0,  # stated 0, but both points are awarded: the sum is 2
        confidence=0.9,
        matched_point_ids=[],
        feedback="f",
        point_verdicts=[
            PointVerdictReasoned(point_id=pid, verdict="awarded")  # type: ignore[arg-type]
            for pid in ("p1", "p2")
        ],
    )
    client = _ReplyClient(reply)
    log = rs.ReplyLog()
    log.reason_first = True
    log.scheme = SimpleNamespace(get_question_by_id=lambda qid: question)  # type: ignore[assignment]
    log.wrap(client)
    log.current = "k"
    out = client.generate_structured(task_tag="correction", question_id="1a", attempt="first")
    assert out is reply and reply.awarded_marks == 0  # the log never changes the reply
    (row,) = log.rows
    assert (row.mark, row.stated_mark) == (2, 0)
    log.reason_first = False  # lever off: the reply's own mark
    client.generate_structured(task_tag="correction", question_id="1a", attempt="first")
    assert log.rows[-1].mark == 0


def test_reason_first_logs_an_adjudication_reply_with_its_own_mark() -> None:
    from types import SimpleNamespace

    from lemely.core.loose_schemas import AnswerPoint, Question, QuestionType
    from lemely.io.adjudication import AdjudicationReply

    question = Question.model_construct(
        id="1a",
        marks=2,
        type=QuestionType.EXPLANATION,
        answer_points=[AnswerPoint(id="p1", point="gravity", marks=2)],
        select_count=None,
        parts=[],
        assessment_objectives=[],
        rejected_answers=[],
        ignored_answers=[],
    )
    client = _ReplyClient(AdjudicationReply(awarded_marks=1, confidence=0.8, rationale="r"))
    log = rs.ReplyLog()
    log.reason_first = True
    log.scheme = SimpleNamespace(get_question_by_id=lambda qid: question)  # type: ignore[assignment]
    log.wrap(client)
    log.current = "k"
    client.generate_structured(task_tag="adjudication", question_id="1a", model="sonnet-x")
    assert log.skipped == 0
    (row,) = log.rows
    assert (row.task_tag, row.mark, row.rationale) == ("adjudication", 1, "r")
