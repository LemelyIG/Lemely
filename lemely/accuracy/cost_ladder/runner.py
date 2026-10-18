"""Run accuracy-harness configurations and reduce them to gate `RunSummary` objects."""

from __future__ import annotations

import json
import math
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING

from lemely.accuracy.cost_ladder.gate import RunSummary
from lemely.accuracy.cost_ladder.spend import (
    RUN_COST_FILE,
    CapWatch,
    SpendCaps,
    SpendLedger,
    check_can_start,
    cost_by_provider,
    resolve_projection,
)
from lemely.accuracy.harness import (
    AccuracyResult,
    GoldenCase,
    QuestionResult,
    _corpus_digest,
    load_golden_cases,
    measure_accuracy,
)
from lemely.io.gemini import (
    PRICE_DATE_2027,
    CallRecord,
    GeminiClient,
    price_row,
    process_call_records,
    process_token_totals_by_task,
    reset_process_counters,
    set_call_context,
)
from lemely.runtime.config import Settings, load_settings

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

PINNED_CORPUS_DIGEST = "76989782d6fda9fc"
P95_RANK = 0.95
_UNSCORED_OUTCOMES = frozenset({"excluded", "unmatched"})


class CorpusDigestMismatch(RuntimeError):
    """The loaded golden cases are not the pinned 12-case dev corpus."""


def case_key(case: GoldenCase) -> str:
    """The key a case carries in `CallRecord.case_key` and the mismark set."""
    if case.fixture_variant is None:
        return case.paper_id
    return f"{case.paper_id}/{case.fixture_variant}"


def require_gemini_key(environ: Mapping[str, str]) -> None:
    """Refuse to run live without the wrapper-provided key. Never echoes its value."""
    if not environ.get("GEMINI_API_KEY"):
        raise RuntimeError(
            "GEMINI_API_KEY is not set; run through the wrapper that exports it "
            "(the key is read from the environment only)."
        )


def assert_corpus_digest(cases: Sequence[GoldenCase]) -> None:
    """Abort before any spend when the case set is not the pinned corpus."""
    digest = _corpus_digest(list(cases))
    if digest != PINNED_CORPUS_DIGEST:
        raise CorpusDigestMismatch(
            f"corpus digest {digest} != pinned {PINNED_CORPUS_DIGEST}; refusing to run"
        )


def parse_override_value(raw: str) -> object:
    """`--set key=value` values: JSON when it parses (true, 3, 0.5), else the raw string."""
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def apply_overrides(settings: Settings, overrides: Mapping[str, object]) -> Settings:
    """A copy of *settings* with dotted ``section.field`` overrides validated and applied."""
    updated = settings
    for dotted, value in overrides.items():
        section_name, sep, field = dotted.partition(".")
        if not sep or not field:
            raise ValueError(f"override {dotted!r} must be a dotted section.field path")
        section = getattr(updated, section_name, None)
        if section is None or field not in type(section).model_fields:
            raise ValueError(f"unknown setting {dotted}")
        new_section = type(section).model_validate({**section.model_dump(), field: value})
        updated = updated.model_copy(update={section_name: new_section})
    return updated


def models_in_play(settings: Settings) -> list[str]:
    """Every model the pinned run can call, resolved from *settings*, de-duplicated."""
    g = settings.gemini
    names: list[str | None] = [
        g.model_for("extraction"),
        g.model_for("correction"),
        g.model_for("correction_borderline"),
        g.model_for("escalation"),
        settings.binding.read_model,  # binding read and second read
        settings.binding.retry_model,
        g.cascade_strong_model,
    ]
    if g.second_reader == "cross_model":
        names.append(g.second_read_model)
    return list(dict.fromkeys(n for n in names if n))


def preflight_prices(settings: Settings) -> None:
    """Raise `UnpricedModelError` before any spend if a model in play has no price row."""
    for model in models_in_play(settings):
        price_row(model, settings, on=PRICE_DATE_2027)


class ProbeContext:
    """A `cost_probe` that also tells the Gemini layer which case is running.

    `measure_accuracy` samples its probe once before and once after each case,
    in case order, and does not set the per-call context itself. The "before"
    sample is the only per-case hook the harness offers without editing it, so
    the context is set there; the "after" sample reports the finished case to
    ``after_case`` (the spend-cap check) and passes through.
    """

    def __init__(
        self,
        case_keys: Sequence[str],
        inner: Callable[[], dict[str, float]],
        after_case: Callable[[str], None] | None = None,
    ) -> None:
        self._keys = list(case_keys)
        self._inner = inner
        self._after_case = after_case
        self._calls = 0

    def __call__(self) -> dict[str, float]:
        index, after = divmod(self._calls, 2)
        self._calls += 1
        if index < len(self._keys):
            if not after:
                set_call_context(case_key=self._keys[index])
            elif self._after_case is not None:
                self._after_case(self._keys[index])
        return self._inner()


class SpendCapReached(Exception):
    """Raised from the probe to end a run whose provider spend is at its cap."""

    def __init__(self, message: str, completed: Sequence[str]) -> None:
        super().__init__(message)
        self.completed = list(completed)


class _CapGuard:
    """Adds each finished case's billed records to the run total; stops at the cap."""

    def __init__(self, watch: CapWatch) -> None:
        self._watch = watch
        self.completed: list[str] = []

    def __call__(self, key: str) -> None:
        mine = [r for r in process_call_records() if r.case_key == key]
        self.completed.append(key)
        message = self._watch.add_case(mine)
        if message is not None:
            raise SpendCapReached(message, self.completed)


def _paired(result: AccuracyResult) -> list[tuple[str, QuestionResult]]:
    """(case key, QuestionResult) per marked leaf.

    The harness appends a `QuestionResult` and its `EvalRecord` together, only
    for marked leaves, so the two lists align once the unscored records are skipped.
    """
    marked = [e for e in result.eval_records if e.outcome not in _UNSCORED_OUTCOMES]
    if len(marked) != len(result.question_results):
        raise ValueError(
            f"{len(marked)} marked eval records but "
            f"{len(result.question_results)} question results; cannot attribute cases"
        )
    return [
        (e.paper_id if e.fixture_variant is None else f"{e.paper_id}/{e.fixture_variant}", q)
        for e, q in zip(marked, result.question_results, strict=True)
    ]


def _per_case_sum(
    records: Sequence[CallRecord], keys: Sequence[str], value: Callable[[CallRecord], float]
) -> dict[str, float]:
    totals = dict.fromkeys(keys, 0.0)
    for rec in records:
        amount = value(rec)
        if rec.case_key in totals and not math.isnan(amount):
            totals[rec.case_key] += amount
    return totals


def _case_keys(result: AccuracyResult) -> list[str]:
    keys: dict[str, None] = {}
    for e in result.eval_records:
        keys[e.paper_id if e.fixture_variant is None else f"{e.paper_id}/{e.fixture_variant}"] = (
            None
        )
    return list(keys)


def _nearest_rank(values: Sequence[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(math.ceil(q * len(ordered)) - 1, 0)]


def mean_usd(result: AccuracyResult, records: Sequence[CallRecord], *, rate: str) -> float:
    """Mean over cases of the summed per-call USD, at the ``now`` or ``2027`` rate."""
    keys = _case_keys(result)
    if not keys:
        return 0.0
    pick: Callable[[CallRecord], float] = (
        (lambda r: r.usd_2027) if rate == "2027" else (lambda r: r.usd_now)
    )
    return sum(_per_case_sum(records, keys, pick).values()) / len(keys)


def summarise(result: AccuracyResult, records: list[CallRecord]) -> RunSummary:
    """Reduce one harness run and its call records to what the gate judges."""
    keys = _case_keys(result)
    scored = [(k, q) for k, q in _paired(result) if q.scored]
    mismarked = frozenset(
        f"{k}/{q.question_id}" for k, q in scored if q.predicted_marks != q.truth_marks
    )

    latency = _per_case_sum(records, keys, lambda r: float(r.latency_ms))
    ok = sum(1 for r in records if r.parse_ok)
    validity = ok / len(records) if records else 1.0

    shortfall = {
        e.paper_id if e.fixture_variant is None else f"{e.paper_id}/{e.fixture_variant}"
        for e in result.eval_records
        if e.outcome in _UNSCORED_OUTCOMES
    }
    incomplete: dict[str, str] = dict.fromkeys(shortfall, "")
    for r in records:
        if r.case_key is None:
            continue
        if math.isnan(r.usd_2027):
            incomplete[r.case_key] = f" (unpriced model {r.model})"
        elif not r.parse_ok:
            incomplete.setdefault(r.case_key, "")
    id_match = result.metrics.id_match_rate

    return RunSummary(
        usd_per_script_mean=mean_usd(result, records, rate="2027"),
        latency_p95_ms=_nearest_rank(list(latency.values()), P95_RANK),
        mismarked_parts=mismarked,
        scored_parts=len(scored),
        id_match_rate=1.0 if id_match is None else id_match,
        validity_rate=validity,
        incomplete=tuple(f"{k}{incomplete[k]}" for k in sorted(incomplete)),
    )


def write_summary(
    summary: RunSummary,
    path: Path,
    *,
    usd_per_script_mean_now: float,
    extra: Mapping[str, object] | None = None,
) -> None:
    data: dict[str, object] = dict(asdict(summary))
    data["mismarked_parts"] = sorted(summary.mismarked_parts)
    data["incomplete"] = list(summary.incomplete)
    data["usd_per_script_mean_now"] = usd_per_script_mean_now
    data.update(extra or {})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_summary(path: Path) -> RunSummary:
    data = json.loads(path.read_text(encoding="utf-8"))
    return RunSummary(
        usd_per_script_mean=data["usd_per_script_mean"],
        latency_p95_ms=data["latency_p95_ms"],
        mismarked_parts=frozenset(data["mismarked_parts"]),
        scored_parts=data["scored_parts"],
        id_match_rate=data["id_match_rate"],
        validity_rate=data["validity_rate"],
        incomplete=tuple(data["incomplete"]),
    )


def _result_json(result: AccuracyResult) -> dict[str, object]:
    return {
        "metrics": asdict(result.metrics),
        "funnel": asdict(result.funnel),
        "manifest": result.manifest.model_dump(mode="json"),
        "cost_usd_by_paper": result.cost_usd_by_paper,
        "cost_usd_total": result.cost_usd_total,
        "question_results": [asdict(q) for q in result.question_results],
    }


def _capped_summary(
    records: Sequence[CallRecord], keys: Sequence[str], completed: Sequence[str]
) -> RunSummary:
    """Summary of a run stopped by the cap: no marks were recovered, so the gate fails it.

    `measure_accuracy` returns nothing when interrupted, so the completed cases'
    marks are not available; only cost, latency and validity are.
    """
    done = list(completed)
    latency = _per_case_sum(records, done, lambda r: float(r.latency_ms))
    usd = _per_case_sum(records, done, lambda r: r.usd_2027)
    ok = sum(1 for r in records if r.parse_ok)
    return RunSummary(
        usd_per_script_mean=sum(usd.values()) / len(done) if done else 0.0,
        latency_p95_ms=_nearest_rank(list(latency.values()), P95_RANK),
        mismarked_parts=frozenset(),
        scored_parts=0,
        id_match_rate=0.0,
        validity_rate=ok / len(records) if records else 1.0,
        incomplete=tuple(f"{k} (spend cap)" for k in keys if k not in done),
    )


def run_config(
    label: str,
    overrides: Mapping[str, object],
    *,
    out_dir: Path,
    golden_dir: Path = Path("tests/golden"),
    cases: Sequence[GoldenCase] | None = None,
    settings: Settings | None = None,
    client: GeminiClient | None = None,
    caps: SpendCaps | None = None,
    max_run_usd: Mapping[str, float] | None = None,
) -> RunSummary:
    """Run the pinned dev cases under *overrides*; write the run's artefacts and return its summary.

    Writes ``<out_dir>/<label>/{summary,records,results}.json[l]`` and
    ``run_cost.json``. Always runs at ``cache_mode="bypass"``: a cached call
    records no spend and would flatter both cost and the A/A floor. Every
    precondition (corpus digest, price rows, spend caps) is checked before the
    client is built. Billed spend is added to ``<out_dir>/spend.json`` even if the run fails.
    """
    caps = caps or SpendCaps()
    if cases is None:
        loaded = load_golden_cases(golden_dir)
        if loaded.unparseable:
            raise RuntimeError(f"{len(loaded.unparseable)} golden case(s) failed to parse")
        cases = list(loaded)
    assert_corpus_digest(cases)

    effective = apply_overrides(settings or load_settings(), overrides)
    preflight_prices(effective)

    ledger = SpendLedger(out_dir)
    spent_before = ledger.spent()
    check_can_start(spent_before, resolve_projection(ledger, label, max_run_usd), caps)

    gemini = client or GeminiClient(effective, default_cache_mode="bypass")
    keys = [case_key(c) for c in cases]
    guard = _CapGuard(CapWatch(caps, spent_before))
    reset_process_counters()
    probe = ProbeContext(keys, process_token_totals_by_task, guard)
    run_dir = out_dir / label
    result: AccuracyResult | None = None
    stopped: SpendCapReached | None = None
    try:
        result = measure_accuracy(
            list(cases),
            gemini,
            effective,
            run_id=label,
            split="dev",
            cost_probe=probe,
        )
    except SpendCapReached as exc:
        stopped = exc
    finally:
        set_call_context(case_key=None)
        records = process_call_records()
        billed = cost_by_provider(records)
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / RUN_COST_FILE).write_text(json.dumps(billed, sort_keys=True) + "\n")
        ledger.add(billed)
        (run_dir / "records.jsonl").write_text(
            "".join(json.dumps(asdict(r), sort_keys=True) + "\n" for r in records),
            encoding="utf-8",
        )

    if result is not None:
        summary = summarise(result, records)
        now = mean_usd(result, records, rate="now")
        (run_dir / "results.json").write_text(
            json.dumps(_result_json(result), indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )
    else:
        stop = stopped if stopped is not None else SpendCapReached("run did not finish", [])
        summary = _capped_summary(records, keys, stop.completed)
        done = stop.completed
        now = (
            sum(_per_case_sum(records, done, lambda r: r.usd_now).values()) / len(done)
            if done
            else 0.0
        )
    write_summary(
        summary,
        run_dir / "summary.json",
        usd_per_script_mean_now=now,
        extra={"stopped_by_spend_cap": str(stopped)} if stopped is not None else None,
    )
    return summary
