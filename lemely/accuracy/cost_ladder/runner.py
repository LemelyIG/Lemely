"""Run accuracy-harness configurations and reduce them to gate `RunSummary` objects."""

from __future__ import annotations

import json
import math
import shutil
from dataclasses import asdict, dataclass, fields
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from lemely.accuracy.cost_ladder.gate import RunSummary, Verdict, aa_floor, judge
from lemely.accuracy.cost_ladder.spend import (
    DEFAULT_SPEND_FILE,
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
from lemely.io.correction_ai import _BLANK_ANSWER_REVIEW_REASON
from lemely.io.gemini import (
    PRICE_DATE_2027,
    CallRecord,
    GeminiClient,
    price_row,
    process_call_records,
    process_token_totals_by_task,
    record_calls,
    reset_process_counters,
    set_call_context,
)
from lemely.runtime.config import Settings, load_settings
from lemely.runtime.events import EventType, bus

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from lemely.eval.records import EvalRecord

PINNED_CORPUS_DIGEST = "090492b217365de4"
P95_RANK = 0.95
_UNSCORED_OUTCOMES = frozenset({"excluded", "unmatched"})
#: marker_source of a placeholder leaf left by a marking or extraction that failed.
_FAILED_MARKER_SOURCES = frozenset({"missing", "dropped"})
MARKING_FAILED = " (marking failed)"

BASELINE_LABEL = "baseline"
AA_LABEL = "baseline_aa"
#: Task tags a frozen-upstream screen calls live; every other tag replays the
#: rung-0 baseline's cache.
DEFAULT_LIVE_TAGS: tuple[str, ...] = (
    "correction",
    "correction_borderline",
    "escalation",
    "correction_prefix_cache",
)
CACHE_SUBDIR = "cache"
ARCHIVE_SUBDIR = "archive"
AA_FLOOR_FILE = "aa_floor.json"
LADDER_FILE = "ladder.json"

CacheMode = Literal["read_write", "bypass", "refresh"]


class CorpusDigestMismatch(RuntimeError):
    """The loaded golden cases are not the pinned 12-case dev corpus."""


class LadderStateError(RuntimeError):
    """The out-dir does not hold what this step needs (a run, a verdict, the A/A floor)."""


class UpstreamNotFrozen(RuntimeError):
    """A frozen-upstream screen made a live call under a task tag it does not call live.

    Its upstream cost would then be counted twice (live and from the baseline), so
    the screen fails closed: no verdict, no ladder row.
    """

    def __init__(self, label: str, tags: Sequence[str], live_tags: Sequence[str]) -> None:
        self.tags = list(tags)
        suggested = ",".join(dict.fromkeys([*live_tags, *tags]))
        super().__init__(
            f"screen {label!r} made live calls under task tags not in its live tags: "
            f"{', '.join(self.tags)}. The upstream is not frozen for this lever, so no "
            f"verdict was written. Rescreen with them in --live-tags "
            f"(--live-tags {suggested})."
        )


def _untagged_live(records: Sequence[CallRecord], live_tags: frozenset[str]) -> list[str]:
    """Sorted task tags of *records* that are not live (``None`` shown as "untagged")."""
    return sorted({r.task_tag or "untagged" for r in records if r.task_tag not in live_tags})


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

    The ledger is written after every case, so a run killed mid-way still leaves
    its billed spend on record; ``run_config`` books only the records of
    unfinished cases at the end. Stops the run at the cap, and (for a
    frozen-upstream screen) after the first case with a live non-live-tag call.
    """

    def __init__(
        self,
        watch: CapWatch,
        ledger: SpendLedger,
        *,
        label: str = "",
        frozen_live_tags: Sequence[str] | None = None,
    ) -> None:
        self._watch = watch
        self._ledger = ledger
        self._label = label
        self._frozen_live_tags = frozen_live_tags
        self.completed: list[str] = []

    def __call__(self, key: str) -> None:
        mine = [r for r in process_call_records() if r.case_key == key]
        self._ledger.add(cost_by_provider(mine))
        self.completed.append(key)
        if self._frozen_live_tags is not None:
            bad = _untagged_live(mine, frozenset(self._frozen_live_tags))
            if bad:
                raise UpstreamNotFrozen(self._label, bad, self._frozen_live_tags)
        message = self._watch.add_case(mine)
        if message is not None:
            raise SpendCapReached(message, self.completed)


def _eval_case_key(e: EvalRecord) -> str:
    return e.paper_id if e.fixture_variant is None else f"{e.paper_id}/{e.fixture_variant}"


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
    return [(_eval_case_key(e), q) for e, q in zip(marked, result.question_results, strict=True)]


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
    return list(dict.fromkeys(_eval_case_key(e) for e in result.eval_records))


def _nearest_rank(values: Sequence[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(math.ceil(q * len(ordered)) - 1, 0)]


def _mean_usd(keys: Sequence[str], records: Sequence[CallRecord], *, rate: str) -> float:
    """Mean over *keys* of each case's summed per-call USD, at the ``now`` or ``2027`` rate."""
    if not keys:
        return 0.0
    pick: Callable[[CallRecord], float] = (
        (lambda r: r.usd_2027) if rate == "2027" else (lambda r: r.usd_now)
    )
    return sum(_per_case_sum(records, keys, pick).values()) / len(keys)


@dataclass(frozen=True)
class _Marking:
    """What `summarise` needs from a run's marking, from a live result or a stored one."""

    case_keys: tuple[str, ...]  # every case the run covered, in run order
    scored: tuple[tuple[str, str, int, int], ...]  # (case, question_id, predicted, truth)
    review_flagged: int  # scored parts flagged ``needs_teacher_review``
    unmarked_cases: frozenset[str]  # cases with a ground-truth leaf that was not marked
    failed_cases: frozenset[str]  # cases with a placeholder leaf (`_failed_marking`)
    missing_cases: frozenset[str]  # cases that produced no marking at all
    id_match_rate: float | None


def _failed_marking(
    *,
    marker_source: str | None,
    scored: bool,
    needs_teacher_review: bool,
    review_reason: str | None,
) -> bool:
    """A placeholder leaf the harness counts as marked although no marker marked it.

    correction_ai leaves marker_source "missing" when no marker ran (the AI call
    failed, no AI client was given, or the paper was marked MCQ-only) and
    "dropped" when extraction lost the answer. The harness counts both as marked,
    so the funnel shows no shortfall. A blank ("blank") is a real marking, even
    when the binder later flags it for review.

    Without a marker_source (a result stored before it was recorded), a failed
    leaf is one that is unscored, flagged for review, and whose review reason is
    not the blank answer's.
    """
    if marker_source is not None:
        return marker_source in _FAILED_MARKER_SOURCES
    return (
        not scored
        and needs_teacher_review
        and not (review_reason or "").startswith(_BLANK_ANSWER_REVIEW_REASON)
    )


def _marking(result: AccuracyResult, expected_cases: Sequence[str] = ()) -> _Marking:
    produced = _case_keys(result)
    paired = _paired(result)
    return _Marking(
        case_keys=tuple(dict.fromkeys([*expected_cases, *produced])),
        scored=tuple(
            (k, q.question_id, q.predicted_marks, q.truth_marks) for k, q in paired if q.scored
        ),
        review_flagged=sum(1 for _, q in paired if q.scored and q.needs_teacher_review),
        unmarked_cases=frozenset(
            _eval_case_key(e) for e in result.eval_records if e.outcome in _UNSCORED_OUTCOMES
        ),
        failed_cases=frozenset(
            k
            for k, q in paired
            if _failed_marking(
                marker_source=q.marker_source,
                scored=q.scored,
                needs_teacher_review=q.needs_teacher_review,
                review_reason=q.review_reason,
            )
        ),
        missing_cases=frozenset(expected_cases) - set(produced),
        id_match_rate=result.metrics.id_match_rate,
    )


def review_rate(marking: _Marking) -> float | None:
    """Share of scored parts flagged for teacher review; None when nothing was scored.

    Reported beside the gate's view (``summary.json``, LADDER.md), never judged:
    `RunSummary` and `gate.judge` do not read it.
    """
    return marking.review_flagged / len(marking.scored) if marking.scored else None


def _summarise_marking(marking: _Marking, records: Sequence[CallRecord]) -> RunSummary:
    """The gate's view of a run.

    A case is incomplete only when its marking is short: a ground-truth leaf was
    not marked (a funnel shortfall; or, listed as "<case> (marking failed)", a
    placeholder leaf no marker formed an opinion on, see `_failed_marking`), the
    case produced no marking at all, or one of its calls is unpriced (NaN cost). A
    call that failed to parse but was recovered leaves the case complete; it is
    counted in ``validity_rate`` instead, which the gate requires not to drop.
    """
    keys = list(marking.case_keys)
    latency = _per_case_sum(records, keys, lambda r: float(r.latency_ms))
    ok = sum(1 for r in records if r.parse_ok)
    incomplete: dict[str, str] = dict.fromkeys(marking.unmarked_cases, "")
    for key in marking.failed_cases:
        incomplete[key] = MARKING_FAILED
    for key in marking.missing_cases:
        incomplete[key] = " (no marking)"
    for r in records:
        if r.case_key is not None and math.isnan(r.usd_2027):
            incomplete[r.case_key] = f" (unpriced model {r.model})"
    return RunSummary(
        usd_per_script_mean=_mean_usd(keys, records, rate="2027"),
        latency_p95_ms=_nearest_rank(list(latency.values()), P95_RANK),
        mismarked_parts=frozenset(
            f"{case}/{qid}" for case, qid, predicted, truth in marking.scored if predicted != truth
        ),
        scored_parts=len(marking.scored),
        id_match_rate=1.0 if marking.id_match_rate is None else marking.id_match_rate,
        validity_rate=ok / len(records) if records else 1.0,
        incomplete=tuple(f"{k}{incomplete[k]}" for k in sorted(incomplete)),
    )


def summarise(
    result: AccuracyResult,
    records: list[CallRecord],
    *,
    expected_cases: Sequence[str] = (),
) -> RunSummary:
    """Reduce one harness run and its call records to what the gate judges.

    *expected_cases* are the cases the run was given; one that produced no
    marking is incomplete. See `_summarise_marking` for the completeness rule.
    """
    return _summarise_marking(_marking(result, expected_cases), records)


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


def _result_json(result: AccuracyResult, case_keys: Sequence[str]) -> dict[str, object]:
    return {
        # Everything `resummarise` needs to rebuild the marking without the model:
        # the cases run, and the per-case leaves that were not marked.
        "case_keys": list(case_keys),
        "unmarked_leaves": [
            {"case_key": _eval_case_key(e), "question_id": e.question_id, "outcome": e.outcome}
            for e in result.eval_records
            if e.outcome in _UNSCORED_OUTCOMES
        ],
        "metrics": asdict(result.metrics),
        "funnel": asdict(result.funnel),
        "manifest": result.manifest.model_dump(mode="json"),
        "cost_usd_by_paper": result.cost_usd_by_paper,
        "cost_usd_total": result.cost_usd_total,
        # Each entry carries the case it belongs to (`case_key`'s format) so offline
        # tools can count scored parts per case and judge marks against truth exactly.
        "question_results": [{"case_key": k, **asdict(q)} for k, q in _paired(result)],
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
    spend_file: Path | None = None,
    on_checks_passed: Callable[[], None] | None = None,
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
    only this run's live records. Any live call under a non-live tag raises
    `UpstreamNotFrozen` (after the case that made it, its spend booked).

    Every precondition (corpus digest, price rows, spend caps) is checked before
    anything is written; *on_checks_passed* then runs (a screen seeds its cache
    there), and only then is the client built. Billed spend is added to the
    ledger at *spend_file* (default `DEFAULT_SPEND_FILE`, independent of
    *out_dir*) after each case and for any remainder when the run ends.
    Every ``GEMINI_CACHE_HIT`` during the run is counted into ``cache_hits``.
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

    ledger = SpendLedger(spend_file or DEFAULT_SPEND_FILE)
    spent_before = ledger.spent()
    check_can_start(spent_before, resolve_projection(out_dir, label, max_run_usd), caps)
    if on_checks_passed is not None:
        on_checks_passed()

    gemini = client or GeminiClient(effective, default_cache_mode=cache_mode)
    keys = [case_key(c) for c in cases]
    guard = _CapGuard(
        CapWatch(caps, spent_before),
        ledger,
        label=label,
        frozen_live_tags=list(live_tags) if frozen_upstream is not None else None,
    )
    hits: list[object] = []

    def count_hit(**_payload: object) -> None:
        hits.append(None)

    bus.subscribe(EventType.GEMINI_CACHE_HIT, count_hit)
    # Records are kept only inside this block (the web process keeps none).
    with record_calls():
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
            bus.unsubscribe(EventType.GEMINI_CACHE_HIT, count_hit)
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

    if frozen_upstream is not None:
        # Calls made outside any case (no case_key) are not seen by the guard.
        bad = _untagged_live(records, frozenset(live_tags))
        if bad:
            raise UpstreamNotFrozen(label, bad, live_tags)
    done = keys if result is not None else list(guard.completed)
    judged = (
        records
        if frozen_upstream is None
        else compose_records(records, frozen_upstream, live_tags=live_tags, case_keys=done)
    )
    rate: float | None = None
    if result is not None:
        marking = _marking(result, keys)
        summary = _summarise_marking(marking, judged)
        rate = review_rate(marking)
        now = _mean_usd(marking.case_keys, judged, rate="now")
        (run_dir / "results.json").write_text(
            json.dumps(_result_json(result, keys), indent=2, sort_keys=True, default=str) + "\n",
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
        "cache_hits": len(hits),
        "review_rate": rate,
    }
    if stopped is not None:
        extra["stopped_by_spend_cap"] = str(stopped)
    extra.update(summary_extra or {})
    write_summary(summary, run_dir / "summary.json", usd_per_script_mean_now=now, extra=extra)
    return summary


def require_file(path: Path, what: str) -> Path:
    """*path*, or a `LadderStateError` naming *what* is missing (never a bare traceback)."""
    if not path.is_file():
        raise LadderStateError(f"{what} not found at {path}")
    return path


def require_complete(summary_path: Path, what: str) -> RunSummary:
    """Read a baseline-side summary, refusing one stopped by the cap or with incomplete cases.

    A floor or a screen judged against a partial rung 0 would be meaningless.
    """
    data = json.loads(require_file(summary_path, what).read_text(encoding="utf-8"))
    problems: list[str] = []
    if data.get("stopped_by_spend_cap"):
        problems.append(f"stopped by the spend cap ({data['stopped_by_spend_cap']})")
    if data.get("incomplete"):
        problems.append("incomplete cases: " + ", ".join(data["incomplete"]))
    if problems:
        raise LadderStateError(
            f"{what} at {summary_path} is not a complete run ({'; '.join(problems)}). "
            "Rerun it with `baseline --restart-baseline`."
        )
    return read_summary(summary_path)


def _ladder_labels(out_dir: Path) -> list[str]:
    path = out_dir / LADDER_FILE
    return list(json.loads(path.read_text(encoding="utf-8"))) if path.is_file() else []


def _archive_ladder(out_dir: Path) -> None:
    """Move ladder.json and every screen run dir to ``archive/restart-<UTC>/``.

    Screens were judged against the baseline being restarted, so they leave the
    live ladder; their cache copies are deleted.
    """
    keep = {BASELINE_LABEL, AA_LABEL, CACHE_SUBDIR, ARCHIVE_SUBDIR}
    screens = [d for d in out_dir.iterdir() if d.is_dir() and d.name not in keep]
    ladder = out_dir / LADDER_FILE
    if not screens and not ladder.exists():
        return
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    dest = out_dir / ARCHIVE_SUBDIR / f"restart-{stamp}"
    dest.mkdir(parents=True)
    if ladder.exists():
        shutil.move(ladder, dest / LADDER_FILE)
    for run_dir in screens:
        shutil.move(run_dir, dest / run_dir.name)
        cache = cache_dir_for(out_dir, run_dir.name)
        if cache.exists():
            shutil.rmtree(cache)


def _baseline_cache_stats(out_dir: Path) -> dict[str, int]:
    """In-run cache evidence for the rung-0 baseline, recorded in its summary.

    ``in_run_cache_hits`` counts ``GEMINI_CACHE_HIT`` events during the run: a call
    that replayed an entry written earlier in the same run made no record, so its
    cost and latency are missing from rung 0. ``cache_entries_written`` vs
    ``cacheable_live_records`` (parsed live calls) shows calls that shared a key.
    """
    run_dir = out_dir / BASELINE_LABEL
    data = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    entries = cache_dir_for(out_dir, BASELINE_LABEL) / "gemini"
    return {
        "in_run_cache_hits": int(data.get("cache_hits", 0)),
        "cache_entries_written": sum(1 for _ in entries.glob("*.json")) if entries.is_dir() else 0,
        "cacheable_live_records": sum(
            1 for r in read_records(run_dir / "records.jsonl") if r.parse_ok
        ),
    }


def run_baseline(
    *,
    out_dir: Path,
    golden_dir: Path = Path("tests/golden"),
    cases: Sequence[GoldenCase] | None = None,
    settings: Settings | None = None,
    caps: SpendCaps | None = None,
    max_run_usd: Mapping[str, float] | None = None,
    spend_file: Path | None = None,
    restart: bool = False,
    aa_only: bool = False,
) -> int:
    """Rung 0 and its A/A rerun; write and return the churn floor.

    The baseline runs on a fresh, empty ``<out_dir>/cache/baseline`` at
    ``read_write``: every call is live and every response is written, which is the
    frozen upstream later screens replay. Its summary records the in-run cache
    evidence (`_baseline_cache_stats`); it does not fail on it. The A/A rerun
    bypasses the cache entirely (fully live, writes nothing) on its own directory.

    Both runs must be complete (`require_complete`) before the floor is written;
    an incomplete baseline stops before the A/A run spends anything.

    *restart* replaces this out-dir's baseline: once `run_config`'s checks pass
    (projection, caps, prices; nothing is touched before), it archives the ladder
    and screens (`_archive_ladder`) and deletes the baseline cache, ``baseline/``,
    ``baseline_aa/`` and ``aa_floor.json``. The spend ledger is kept.

    *aa_only* reruns only the A/A run against the existing, complete baseline; it
    is refused while ``ladder.json`` has rows, since a new floor would change the
    rule earlier verdicts were judged under.
    """
    if restart and aa_only:
        raise ValueError("--restart-baseline and --aa-only are mutually exclusive")
    base_cache = cache_dir_for(out_dir, BASELINE_LABEL)
    aa_cache = cache_dir_for(out_dir, AA_LABEL)

    def one(
        label: str, cache: Path, mode: CacheMode, hook: Callable[[], None] | None = None
    ) -> RunSummary:
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
            spend_file=spend_file,
            on_checks_passed=hook,
        )

    base_summary = out_dir / BASELINE_LABEL / "summary.json"
    if aa_only:
        if _ladder_labels(out_dir):
            raise LadderStateError(
                "--aa-only is refused while ladder.json has rows: a new A/A floor would "
                "change the rule earlier verdicts were judged under. Use --restart-baseline."
            )
    else:

        def wipe() -> None:
            _archive_ladder(out_dir)
            for path in (base_cache, aa_cache, out_dir / BASELINE_LABEL, out_dir / AA_LABEL):
                if path.exists():
                    shutil.rmtree(path)
            (out_dir / AA_FLOOR_FILE).unlink(missing_ok=True)
            base_cache.mkdir(parents=True, exist_ok=True)

        if not restart and base_cache.exists() and any(base_cache.iterdir()):
            raise RuntimeError(
                f"baseline cache {base_cache} is not empty; a baseline must start from an "
                "empty cache so every call is live. Pass --restart-baseline to delete this "
                "baseline (cache, baseline and A/A runs; spend is kept), or --aa-only to "
                "rerun only the A/A run."
            )
        if not restart:
            base_cache.mkdir(parents=True, exist_ok=True)
        one(BASELINE_LABEL, base_cache, "read_write", wipe if restart else None)
        data = json.loads(base_summary.read_text(encoding="utf-8"))
        data.update(_baseline_cache_stats(out_dir))
        base_summary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", "utf-8")
    a = require_complete(base_summary, "baseline summary")
    aa_cache.mkdir(parents=True, exist_ok=True)
    one(AA_LABEL, aa_cache, "bypass")
    b = require_complete(out_dir / AA_LABEL / "summary.json", "A/A summary")
    floor = aa_floor(a, b)
    (out_dir / AA_FLOOR_FILE).write_text(json.dumps({"aa_floor": floor}) + "\n", encoding="utf-8")
    return floor


def _drop_from_ladder(out_dir: Path, label: str) -> None:
    path = out_dir / LADDER_FILE
    if path.is_file():
        labels = [x for x in json.loads(path.read_text(encoding="utf-8")) if x != label]
        path.write_text(json.dumps(labels, indent=2) + "\n", encoding="utf-8")


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
    spend_file: Path | None = None,
) -> Verdict:
    """Screen one lever stacked on the *against* run, frozen upstream, and judge it.

    - Stacking: only on the baseline or on a run whose verdict passed. *sets*
      are merged over that run's recorded combined overrides, and *live_tags*
      are unioned with its recorded live tags; the combined sets are what runs
      and what is recorded.
    - Cache: once every check has passed, the baseline's cache is copied to a
      fresh ``<out_dir>/cache/<label>`` and any earlier verdict for *label* is
      withdrawn; the client reads and writes it, and only the live tags bypass it.
    - Fail closed: a live call under a non-live tag raises `UpstreamNotFrozen`;
      no verdict is written and *label* is not in ``ladder.json``.
    - Judging: savings, mismarks, id-match and validity against *against*;
      latency always against the rung-0 baseline's p95.

    A refused screen (missing state, a rejected *against*, a failed precondition
    in `run_config`) writes nothing. Otherwise writes ``verdict.json`` beside the
    run's summary and appends *label* to ``ladder.json``.
    """
    if label in (BASELINE_LABEL, AA_LABEL, CACHE_SUBDIR, ARCHIVE_SUBDIR):
        raise ValueError(f"{label!r} is reserved")
    if against == label:
        raise LadderStateError(f"screen {label!r} cannot stack on itself (--against {against})")
    for row in _ladder_labels(out_dir):
        row_verdict = out_dir / row / "verdict.json"
        if row_verdict.is_file() and (
            json.loads(row_verdict.read_text(encoding="utf-8")).get("against") == label
        ):
            raise LadderStateError(
                f"cannot re-screen {label!r}: ladder row {row!r} stacks on it. "
                "Screen the change under a new label."
            )
    base_dir = out_dir / BASELINE_LABEL
    original_p95 = require_complete(
        base_dir / "summary.json", "baseline summary (run `baseline` first)"
    ).latency_p95_ms
    floor_path = require_file(
        out_dir / AA_FLOOR_FILE, "A/A floor aa_floor.json (run `baseline` first)"
    )
    floor = int(json.loads(floor_path.read_text(encoding="utf-8"))["aa_floor"])
    frozen = read_records(require_file(base_dir / "records.jsonl", "baseline records"))
    against_summary_path = require_file(
        out_dir / against / "summary.json", f"--against run {against!r} summary"
    )
    if against != BASELINE_LABEL:
        against_verdict = require_file(
            out_dir / against / "verdict.json", f"--against run {against!r} verdict"
        )
        if not json.loads(against_verdict.read_text(encoding="utf-8")).get("passed"):
            raise LadderStateError(
                f"--against run {against!r} did not pass; a lever stacks only on the "
                "baseline or on an accepted rung"
            )
    against_data = json.loads(against_summary_path.read_text(encoding="utf-8"))
    combined = {**dict(against_data.get("overrides") or {}), **sets}
    inherited: list[str] = [str(t) for t in against_data.get("live_tags") or []]
    tags: list[str] = list(dict.fromkeys([*live_tags, *inherited]))
    run_dir = out_dir / label
    cache = cache_dir_for(out_dir, label)

    def seed() -> None:
        for stale in ("verdict.json", "summary.json", "results.json"):
            (run_dir / stale).unlink(missing_ok=True)
        _drop_from_ladder(out_dir, label)
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
        live_tags=tags,
        frozen_upstream=frozen,
        summary_extra={"against": against, "set": dict(sets)},
        spend_file=spend_file,
        on_checks_passed=seed,
    )
    verdict = judge(
        read_summary(against_summary_path),
        candidate,
        aa_floor=floor,
        original_latency_p95_ms=original_p95,
    )
    (run_dir / "verdict.json").write_text(
        json.dumps(
            {
                "lever": lever or label,
                "expected_saving": expected_saving,
                "proof": str(run_dir),
                "against": against,
                "overrides": combined,
                "set": dict(sets),
                "live_tags": tags,
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


def _stored_int(value: object) -> int:
    if not isinstance(value, int):
        raise LadderStateError(f"results.json holds a non-integer mark {value!r}")
    return value


def _stored_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _marking_from_results(results: Mapping[str, object], records: Sequence[CallRecord]) -> _Marking:
    """Rebuild a run's `_Marking` from its stored ``results.json``.

    An older results.json has no ``case_keys``; its cases are then the union of
    the question results' and the records' case keys (in that order), so a case
    with neither (no marking and no call) cannot be seen as missing. Refuses
    (`LadderStateError`) what it cannot attribute to a case, and a malformed
    ``unmarked_leaves``.
    """
    raw = results.get("question_results")
    if not isinstance(raw, list) or any(
        not isinstance(q, dict) or "case_key" not in q for q in raw
    ):
        raise LadderStateError(
            "results.json predates case-keyed question results; this run cannot be resummarised"
        )
    qrs: list[dict[str, object]] = raw
    stored_cases = results.get("case_keys")
    if isinstance(stored_cases, list):
        case_keys = tuple(str(k) for k in stored_cases)
    else:
        case_keys = tuple(
            dict.fromkeys(
                [*(str(q["case_key"]) for q in qrs), *(r.case_key for r in records if r.case_key)]
            )
        )
    unmarked: frozenset[str]
    if "unmarked_leaves" in results:
        unmarked_raw = results["unmarked_leaves"]
        if not isinstance(unmarked_raw, list) or any(
            not isinstance(u, dict) or not isinstance(u.get("case_key"), str) for u in unmarked_raw
        ):
            raise LadderStateError(
                "results.json unmarked_leaves is malformed (expected a list of objects with a "
                "string case_key); this run cannot be resummarised"
            )
        unmarked = frozenset(u["case_key"] for u in unmarked_raw)
    else:
        funnel = results.get("funnel")
        leaves = funnel.get("leaves") if isinstance(funnel, dict) else None
        if not isinstance(leaves, int):
            raise LadderStateError("results.json has neither unmarked_leaves nor a funnel")
        if leaves > len(qrs):
            raise LadderStateError(
                f"results.json predates per-case leaf outcomes and has {leaves - len(qrs)} "
                "unmarked leaves that cannot be attributed to cases; this run cannot be "
                "resummarised"
            )
        unmarked = frozenset()
    marked = {str(q["case_key"]) for q in qrs}
    metrics = results.get("metrics")
    id_match = metrics.get("id_match_rate") if isinstance(metrics, dict) else None
    return _Marking(
        case_keys=case_keys,
        scored=tuple(
            (
                str(q["case_key"]),
                str(q["question_id"]),
                _stored_int(q["predicted_marks"]),
                _stored_int(q["truth_marks"]),
            )
            for q in qrs
            if q.get("scored", True)
        ),
        review_flagged=sum(
            1 for q in qrs if q.get("scored", True) and q.get("needs_teacher_review") is True
        ),
        unmarked_cases=unmarked,
        failed_cases=frozenset(
            str(q["case_key"])
            for q in qrs
            if _failed_marking(
                marker_source=_stored_str(q.get("marker_source")),
                scored=q.get("scored", True) is not False,
                needs_teacher_review=q.get("needs_teacher_review") is True,
                review_reason=_stored_str(q.get("review_reason")),
            )
        ),
        missing_cases=frozenset(case_keys) - marked - unmarked,
        id_match_rate=float(id_match) if isinstance(id_match, int | float) else None,
    )


def resummarise(label: str, *, out_dir: Path) -> RunSummary:
    """Recompute ``<out_dir>/<label>/summary.json`` from the run's stored records. $0.

    Uses the run's ``records.jsonl`` and ``results.json`` and the same reduction as
    a live run (`_summarise_marking`); a frozen-upstream screen is recomposed with
    the baseline's records under its recorded live tags. Every other field of the
    old summary (overrides, live tags, cache stats, against) is kept, and the old
    ``incomplete`` list is kept under ``resummarised``. No client, no model call,
    no ledger change.

    Judged history is not rewritten: the baseline and A/A runs are refused while
    ``ladder.json`` has rows (the verdicts were judged against them), and a run
    with a ``verdict.json`` is refused (its verdict would no longer match).
    """
    run_dir = out_dir / label
    if label in (BASELINE_LABEL, AA_LABEL) and _ladder_labels(out_dir):
        raise LadderStateError(
            f"resummarise {label!r} is refused while ladder.json has rows: those verdicts "
            "were judged against this run. Use `baseline --restart-baseline`."
        )
    if (run_dir / "verdict.json").is_file():
        raise LadderStateError(
            f"resummarise {label!r} is refused: it has a verdict.json, which would no longer "
            "match its summary. Screen the change under a new label."
        )
    results = json.loads(
        require_file(
            run_dir / "results.json",
            f"run {label!r} results.json (only a finished run can be resummarised)",
        ).read_text(encoding="utf-8")
    )
    records = read_records(require_file(run_dir / "records.jsonl", f"run {label!r} records"))
    summary_path = require_file(run_dir / "summary.json", f"run {label!r} summary")
    old: dict[str, object] = json.loads(summary_path.read_text(encoding="utf-8"))
    marking = _marking_from_results(results, records)
    judged: list[CallRecord] = list(records)
    if old.get("frozen_upstream"):
        frozen = read_records(
            require_file(out_dir / BASELINE_LABEL / "records.jsonl", "baseline records")
        )
        live = old.get("live_tags")
        judged = compose_records(
            records,
            frozen,
            live_tags=[str(t) for t in live] if isinstance(live, list) else [],
            case_keys=marking.case_keys,
        )
    summary = _summarise_marking(marking, judged)
    replaced = {f.name for f in fields(RunSummary)} | {
        "usd_per_script_mean_now",
        "resummarised",
        "review_rate",
    }
    extra = {k: v for k, v in old.items() if k not in replaced}
    extra["review_rate"] = review_rate(marking)
    extra["resummarised"] = {
        "from": ["records.jsonl", "results.json"],
        "incomplete_before": old.get("incomplete", []),
    }
    write_summary(
        summary,
        summary_path,
        usd_per_script_mean_now=_mean_usd(marking.case_keys, judged, rate="now"),
        extra=extra,
    )
    return summary
