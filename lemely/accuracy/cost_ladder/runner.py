"""Run accuracy-harness configurations and reduce them to gate `RunSummary` objects."""

from __future__ import annotations

import json
import math
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from lemely.accuracy.cost_ladder.gate import RunSummary, Verdict, aa_floor, judge
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

BASELINE_LABEL = "baseline"
AA_LABEL = "baseline_aa"
#: Task tags a frozen-upstream screen calls live; every other tag replays the
#: rung-0 baseline's cache.
DEFAULT_LIVE_TAGS: tuple[str, ...] = ("correction", "correction_borderline", "escalation")
CACHE_SUBDIR = "cache"
AA_FLOOR_FILE = "aa_floor.json"
LADDER_FILE = "ladder.json"

CacheMode = Literal["read_write", "bypass", "refresh"]


class CorpusDigestMismatch(RuntimeError):
    """The loaded golden cases are not the pinned 12-case dev corpus."""


def case_key(case: GoldenCase) -> str:
    """The key a case carries in `CallRecord.case_key` and the mismark set."""
    if case.fixture_variant is None:
        return case.paper_id
    return f"{case.paper_id}/{case.fixture_variant}"


def require_gemini_key(environ: Mapping[str, str]) -> None:
    """Refuse to run live without a usable wrapper-provided key. Never echoes its value."""
    key = environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set; run through the wrapper that exports it "
            "(the key is read from the environment only)."
        )
    if key != key.strip() or any(ch.isspace() for ch in key):
        raise RuntimeError(
            "GEMINI_API_KEY contains whitespace; check the wrapper strips the key file's newline."
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
    """Books each finished case's billed records to the ledger and the run total.

    The ledger (``spend.json``) is written after every case, so a run killed
    mid-way still leaves its billed spend on record; ``run_config`` books only
    the records of unfinished cases at the end. Stops the run at the cap.
    """

    def __init__(self, watch: CapWatch, ledger: SpendLedger) -> None:
        self._watch = watch
        self._ledger = ledger
        self.completed: list[str] = []

    def __call__(self, key: str) -> None:
        mine = [r for r in process_call_records() if r.case_key == key]
        self._ledger.add(cost_by_provider(mine))
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


def read_overrides(path: Path) -> dict[str, object]:
    """The combined lever overrides a run recorded in its ``summary.json`` ({} for rung 0)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return dict(data.get("overrides") or {})


def read_records(path: Path) -> list[CallRecord]:
    """The `CallRecord`s a run wrote to its ``records.jsonl``."""
    return [
        CallRecord(**json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def compose_records(
    live: Sequence[CallRecord],
    frozen_upstream: Sequence[CallRecord],
    *,
    live_tags: Sequence[str],
    case_keys: Sequence[str],
) -> list[CallRecord]:
    """The calls a frozen-upstream screen's cost, latency and validity are judged on.

    A screen replays every non-live task tag from the baseline's cache, and a
    cache hit records no call, so its live records alone would omit the upstream
    cost and latency and flatter the saving. Per case, compose this screen's live
    records with the baseline's records for that case whose tag is not live.
    Billed spend is not composed: only *live* reaches the ledger.
    """
    tags = set(live_tags)
    keys = set(case_keys)
    upstream = [r for r in frozen_upstream if r.task_tag not in tags and r.case_key in keys]
    return [*live, *upstream]


def cache_dir_for(out_dir: Path, label: str) -> Path:
    """The run's own Gemini cache directory, ``<out_dir>/cache/<label>``."""
    return out_dir / CACHE_SUBDIR / label


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
    cache_dir: Path | None = None,
    cache_mode: CacheMode = "bypass",
    live_tags: Sequence[str] = (),
    frozen_upstream: Sequence[CallRecord] | None = None,
    summary_extra: Mapping[str, object] | None = None,
) -> RunSummary:
    """Run the pinned dev cases under *overrides*; write the run's artefacts and return its summary.

    Writes ``<out_dir>/<label>/{summary,records,results}.json[l]`` and
    ``run_cost.json``. *overrides* are the lever settings (recorded in
    ``summary.json`` so a later screen can stack on them); the cache discipline
    is applied on top of them and not recorded as a lever:

    - ``gemini.cache_forget_enabled`` is always False, so no run deletes a cached read;
    - *cache_dir*, when given, becomes ``paths.cache_dir``;
    - ``gemini.cache_mode_for`` maps each of *live_tags* to ``"bypass"`` (and nothing else);
    - the client's default mode is *cache_mode*.

    With *frozen_upstream* (the baseline's records), the summary is judged on
    `compose_records`; ``records.jsonl``, ``run_cost.json`` and the ledger hold
    only this run's live records. Every precondition (corpus digest, price rows,
    spend caps) is checked before the client is built. Billed spend is added to
    ``<out_dir>/spend.json`` after each case and for any remainder when the run ends.
    """
    caps = caps or SpendCaps()
    if cases is None:
        loaded = load_golden_cases(golden_dir)
        if loaded.unparseable:
            raise RuntimeError(f"{len(loaded.unparseable)} golden case(s) failed to parse")
        cases = list(loaded)
    assert_corpus_digest(cases)

    discipline: dict[str, object] = {
        "gemini.cache_forget_enabled": False,
        "gemini.cache_mode_for": dict.fromkeys(live_tags, "bypass"),
    }
    if cache_dir is not None:
        discipline["paths.cache_dir"] = str(cache_dir)
    effective = apply_overrides(apply_overrides(settings or load_settings(), overrides), discipline)
    preflight_prices(effective)

    ledger = SpendLedger(out_dir)
    spent_before = ledger.spent()
    check_can_start(spent_before, resolve_projection(ledger, label, max_run_usd), caps)

    gemini = client or GeminiClient(effective, default_cache_mode=cache_mode)
    keys = [case_key(c) for c in cases]
    guard = _CapGuard(CapWatch(caps, spent_before), ledger)
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
        booked = set(guard.completed)
        ledger.add(cost_by_provider([r for r in records if r.case_key not in booked]))
        (run_dir / "records.jsonl").write_text(
            "".join(json.dumps(asdict(r), sort_keys=True) + "\n" for r in records),
            encoding="utf-8",
        )

    done = keys if result is not None else list(guard.completed)
    judged = (
        records
        if frozen_upstream is None
        else compose_records(records, frozen_upstream, live_tags=live_tags, case_keys=done)
    )
    if result is not None:
        summary = summarise(result, judged)
        now = mean_usd(result, judged, rate="now")
        (run_dir / "results.json").write_text(
            json.dumps(_result_json(result), indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )
    else:
        summary = _capped_summary(judged, keys, done)
        now = (
            sum(_per_case_sum(judged, done, lambda r: r.usd_now).values()) / len(done)
            if done
            else 0.0
        )
    extra: dict[str, object] = {
        "overrides": dict(overrides),
        "live_tags": list(live_tags),
        "cache_mode": cache_mode,
        "frozen_upstream": frozen_upstream is not None,
    }
    if frozen_upstream is not None:
        tags = set(live_tags)
        # A live call under a non-live tag means the upstream was not frozen (a cache
        # miss); its cost is then counted twice (live and from the baseline).
        extra["upstream_live_calls"] = sum(1 for r in records if r.task_tag not in tags)
    if stopped is not None:
        extra["stopped_by_spend_cap"] = str(stopped)
    extra.update(summary_extra or {})
    write_summary(summary, run_dir / "summary.json", usd_per_script_mean_now=now, extra=extra)
    return summary


def run_baseline(
    *,
    out_dir: Path,
    golden_dir: Path = Path("tests/golden"),
    cases: Sequence[GoldenCase] | None = None,
    settings: Settings | None = None,
    caps: SpendCaps | None = None,
    max_run_usd: Mapping[str, float] | None = None,
) -> int:
    """Rung 0 and its A/A rerun; write and return the churn floor.

    The baseline runs on a fresh, empty ``<out_dir>/cache/baseline`` at
    ``read_write``: every call is live and every response is written, which is the
    frozen upstream later screens replay. The A/A rerun bypasses the cache
    entirely (fully live, writes nothing) on its own directory.
    """
    base_cache = cache_dir_for(out_dir, BASELINE_LABEL)
    if base_cache.exists() and any(base_cache.iterdir()):
        raise RuntimeError(
            f"baseline cache {base_cache} is not empty; a baseline must start from an "
            "empty cache so every call is live. Use a fresh --out-dir."
        )
    base_cache.mkdir(parents=True, exist_ok=True)
    aa_cache = cache_dir_for(out_dir, AA_LABEL)
    aa_cache.mkdir(parents=True, exist_ok=True)

    def one(label: str, cache: Path, mode: CacheMode) -> RunSummary:
        return run_config(
            label,
            {},
            out_dir=out_dir,
            golden_dir=golden_dir,
            cases=cases,
            settings=settings,
            caps=caps,
            max_run_usd=max_run_usd,
            cache_dir=cache,
            cache_mode=mode,
        )

    a = one(BASELINE_LABEL, base_cache, "read_write")
    b = one(AA_LABEL, aa_cache, "bypass")
    floor = aa_floor(a, b)
    (out_dir / AA_FLOOR_FILE).write_text(json.dumps({"aa_floor": floor}) + "\n", encoding="utf-8")
    return floor


def append_ladder(out_dir: Path, label: str) -> list[str]:
    """Append *label* to ``<out_dir>/ladder.json``, the report's row order.

    A re-screened label moves to the end: its verdict is the latest decision.
    """
    path = out_dir / LADDER_FILE
    labels: list[str] = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []
    labels = [*(x for x in labels if x != label), label]
    out_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(labels, indent=2) + "\n", encoding="utf-8")
    return labels


def run_screen(
    label: str,
    sets: Mapping[str, object],
    *,
    out_dir: Path,
    against: str = BASELINE_LABEL,
    live_tags: Sequence[str] = DEFAULT_LIVE_TAGS,
    lever: str | None = None,
    expected_saving: str = "n/a",
    golden_dir: Path = Path("tests/golden"),
    cases: Sequence[GoldenCase] | None = None,
    settings: Settings | None = None,
    caps: SpendCaps | None = None,
    max_run_usd: Mapping[str, float] | None = None,
) -> Verdict:
    """Screen one lever stacked on the *against* run, frozen upstream, and judge it.

    - Stacking: *sets* are merged over the *against* run's recorded combined
      overrides, and the combined set is what runs and what is recorded.
    - Cache: the baseline's cache is copied to a fresh ``<out_dir>/cache/<label>``;
      the client reads and writes it, and only *live_tags* bypass it.
    - Judging: savings, mismarks, id-match and validity against *against*;
      latency always against the rung-0 baseline's p95.

    Writes ``verdict.json`` beside the run's summary and appends *label* to
    ``ladder.json``.
    """
    if label in (BASELINE_LABEL, AA_LABEL):
        raise ValueError(f"{label!r} is reserved for the baseline runs")
    against_summary_path = out_dir / against / "summary.json"
    stacked_on = read_overrides(against_summary_path)
    combined = {**stacked_on, **sets}
    base_dir = out_dir / BASELINE_LABEL
    original_p95 = read_summary(base_dir / "summary.json").latency_p95_ms
    floor = int(json.loads((out_dir / AA_FLOOR_FILE).read_text(encoding="utf-8"))["aa_floor"])
    frozen = read_records(base_dir / "records.jsonl")

    cache = cache_dir_for(out_dir, label)
    if cache.exists():
        shutil.rmtree(cache)
    shutil.copytree(cache_dir_for(out_dir, BASELINE_LABEL), cache)

    candidate = run_config(
        label,
        combined,
        out_dir=out_dir,
        golden_dir=golden_dir,
        cases=cases,
        settings=settings,
        caps=caps,
        max_run_usd=max_run_usd,
        cache_dir=cache,
        cache_mode="read_write",
        live_tags=live_tags,
        frozen_upstream=frozen,
        summary_extra={"against": against, "set": dict(sets)},
    )
    verdict = judge(
        read_summary(against_summary_path),
        candidate,
        aa_floor=floor,
        original_latency_p95_ms=original_p95,
    )
    run_dir = out_dir / label
    (run_dir / "verdict.json").write_text(
        json.dumps(
            {
                "lever": lever or label,
                "expected_saving": expected_saving,
                "proof": str(run_dir),
                "against": against,
                "overrides": combined,
                "set": dict(sets),
                "live_tags": list(live_tags),
                "passed": verdict.passed,
                "tier": verdict.tier,
                "saving": verdict.saving,
                "extra_mismarks": verdict.extra_mismarks,
                "allowed_extra": verdict.allowed_extra,
                "reasons": list(verdict.reasons),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    append_ladder(out_dir, label)
    return verdict
