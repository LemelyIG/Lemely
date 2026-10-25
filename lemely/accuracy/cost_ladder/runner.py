"""Run accuracy-harness configurations and reduce them to gate `RunSummary` objects."""

from __future__ import annotations

import json
import logging
import math
import shutil
import time
from dataclasses import asdict, dataclass, fields, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

from lemely.accuracy.cost_ladder.gate import (
    RunSummary,
    Verdict,
    aa_floor,
    judge_accuracy_lever,
    judge_cost_lever,
    judge_flip,
    judge_record,
)
from lemely.accuracy.cost_ladder.real_split import (
    REPLIES_FILE,
    RealScript,
    RealScriptResult,
    ReplyLog,
    mark_real_script,
    real_summary_fields,
    score_script,
    write_real_results,
    write_replies,
)
from lemely.accuracy.cost_ladder.spend import (
    DEFAULT_SPEND_FILE,
    RUN_COST_FILE,
    CapWatch,
    SpendCapError,
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
from lemely.io.providers import is_anthropic_model
from lemely.runtime.config import Settings, load_settings
from lemely.runtime.errors import CostCeilingError
from lemely.runtime.events import EventType, bus

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from lemely.core.schemas import CorrectionResult
    from lemely.eval.records import EvalRecord

PINNED_CORPUS_DIGEST = "090492b217365de4"
P95_RANK = 0.95
_UNSCORED_OUTCOMES = frozenset({"excluded", "unmatched"})
#: marker_source of a placeholder leaf left by a marking or extraction that failed.
_FAILED_MARKER_SOURCES = frozenset({"missing", "dropped"})
MARKING_FAILED = " (marking failed)"

_LOG = logging.getLogger(__name__)

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
#: The real path's task tags in call order. A live tag makes its stage and every later stage live.
REAL_STAGES: tuple[frozenset[str], ...] = (
    frozenset({"scan_metadata"}),
    frozenset({"extraction", "binding_overview", "binding_second_read", "second_read"}),
    frozenset({"correction_prefix_cache", "correction"}),
    frozenset({"correction_borderline"}),
    frozenset({"escalation"}),
    frozenset({"adjudication"}),
)
#: Index of the first marking stage: a real screen whose live tags all sit at or after it
#: is judged on the marking-only A/A floor.
MARKING_STAGE = 2
#: The tags a real run calls before marking; a pin counts these as its upstream.
_PRE_MARKING_TAGS = frozenset().union(*REAL_STAGES[:MARKING_STAGE])
PIN_FILE = "pin.json"
UPSTREAM_RECORDS_FILE = "upstream_records.jsonl"
CACHE_SUBDIR = "cache"
ARCHIVE_SUBDIR = "archive"
AA_FLOOR_FILE = "aa_floor.json"
LADDER_FILE = "ladder.json"
REAL_RUN_PREFIX = "real-"
REPEAT_SUFFIX = "-r2"
FLIP_VERDICT_FILE = "flip_verdict.json"

Split = Literal["dev", "real", "both"]
JudgeKind = Literal["cost", "accuracy", "record"]

_SPLITS = ("dev", "real", "both")
_JUDGE_KINDS = ("cost", "accuracy", "record")
RAW_SUMMARY_FILE = "summary_raw.json"

#: The dev side of a real-only rung: nothing scored, nothing spent.
EMPTY_DEV_SUMMARY = RunSummary(
    usd_per_script_mean=0.0,
    latency_p95_ms=0.0,
    mismarked_parts=frozenset(),
    scored_parts=0,
    id_match_rate=1.0,
    validity_rate=1.0,
    incomplete=(),
)

CacheMode = Literal["read_write", "bypass", "refresh"]


def real_live_tags(live_tags: Sequence[str]) -> tuple[str, ...]:
    """The tags a pinned real run calls live: every tag of the earliest live tag's stage and later.

    Raises ValueError for an empty set or a tag in no stage (named, with the known tags).
    Sorted, so it is stable in summaries.
    """
    known = frozenset().union(*REAL_STAGES)
    if not live_tags:
        raise ValueError("a pinned real run needs at least one live tag")
    unknown = sorted(set(live_tags) - known)
    if unknown:
        raise ValueError(
            f"unknown real task tag(s) {', '.join(unknown)}; known: {', '.join(sorted(known))}"
        )
    first = min(i for i, stage in enumerate(REAL_STAGES) if stage & set(live_tags))
    return tuple(sorted(frozenset().union(*REAL_STAGES[first:])))


def real_floor_kind(live: Sequence[str]) -> Literal["marking", "full"]:
    """Which A/A floor fits: marking when every live tag is at or after MARKING_STAGE, else full."""
    marking = frozenset().union(*REAL_STAGES[MARKING_STAGE:])
    return "marking" if live and set(live) <= marking else "full"


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
    """Refuse to run live without a usable key. Never echoes its value."""
    key = environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set; export it or write ~/.config/lemely/gemini_key "
            "(the key is read from the environment or that file)."
        )
    if key != key.strip() or any(ch.isspace() for ch in key):
        raise RuntimeError(
            "GEMINI_API_KEY contains whitespace; check the exported value has no trailing newline."
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
        g.model_for("scan_metadata"),  # the real split's first stage
        settings.binding.second_read_model,  # None reads the second read on read_model
        settings.binding.read_model,  # binding read and second read
        settings.binding.retry_model,
        g.cascade_strong_model,
        g.adjudication_model,
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


def _pairs(raw: object) -> tuple[tuple[str, float | None], ...]:
    """(key, figure) pairs; a null figure stays None (a script with no result)."""
    return tuple((str(k), _opt_float(v)) for k, v in raw) if isinstance(raw, list) else ()


def _opt_float(raw: object) -> float | None:
    return float(raw) if isinstance(raw, int | float) else None


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
        real_scripts=tuple(str(k) for k in data.get("real_scripts", ())),
        real_abs_error=float(data.get("real_abs_error", 0.0)),
        real_abs_error_by_run=tuple(float(x) for x in data.get("real_abs_error_by_run", ())),
        real_exact_rate=_opt_float(data.get("real_exact_rate")),
        real_within1_rate=_opt_float(data.get("real_within1_rate")),
        real_review_rate=_opt_float(data.get("real_review_rate")),
        real_binding_passes=float(data.get("real_binding_passes", 0.0)),
        real_usd_mean=float(data.get("real_usd_mean", 0.0)),
        real_usd_by_script=_pairs(data.get("real_usd_by_script")),
        real_usd_max_by_script=_pairs(data.get("real_usd_max_by_script")),
        real_latency_by_script=_pairs(data.get("real_latency_by_script")),
        real_escalation_rate=_opt_float(data.get("real_escalation_rate")),
        real_escalation_rate_max_script=_opt_float(data.get("real_escalation_rate_max_script")),
        real_escalation_usd_by_script=_pairs(data.get("real_escalation_usd_by_script")),
        real_escalation_triggers=tuple(
            (str(k), int(v)) for k, v in data.get("real_escalation_triggers", ())
        ),
        real_incomplete=tuple(str(x) for x in data.get("real_incomplete", ())),
    )


def read_records(path: Path) -> list[CallRecord]:
    """The `CallRecord`s a run wrote to its ``records.jsonl``."""
    return [
        CallRecord(**json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _check_split(split: str, repeats: int) -> None:
    if split not in _SPLITS:
        raise ValueError(f"split must be one of {_SPLITS}, got {split!r}")
    if repeats not in (1, 2):
        raise ValueError(f"repeats must be 1 or 2, got {repeats}")


def _stamp_split(path: Path, split: str) -> None:
    """Record the split a rung ran on in its ``summary.json``."""
    data = json.loads(path.read_text(encoding="utf-8"))
    data["split"] = split
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def pair_summaries(a: RunSummary, b: RunSummary) -> RunSummary:
    """Two dev runs of one config as one: the mean of each figure, the union of mismarks."""
    incomplete = list(dict.fromkeys([*a.incomplete, *b.incomplete]))
    if a.scored_parts != b.scored_parts:
        incomplete.append(
            f"scored parts differ between the two runs ({a.scored_parts}, {b.scored_parts})"
        )
    return replace(
        a,
        usd_per_script_mean=(a.usd_per_script_mean + b.usd_per_script_mean) / 2,
        latency_p95_ms=(a.latency_p95_ms + b.latency_p95_ms) / 2,
        mismarked_parts=a.mismarked_parts | b.mismarked_parts,
        id_match_rate=(a.id_match_rate + b.id_match_rate) / 2,
        validity_rate=(a.validity_rate + b.validity_rate) / 2,
        incomplete=tuple(incomplete),
    )


def with_real(
    summary: RunSummary,
    runs: Sequence[Sequence[RealScriptResult]],
    expected_keys: Sequence[str],
) -> RunSummary:
    """*summary* with the real split's fields; real incompletes join ``incomplete``.

    *expected_keys* are the scripts the rung was asked to mark, so one a run lacks is
    reported incomplete rather than silently narrowing the split.
    """
    real = real_summary_fields(runs, expected_keys)
    real_incomplete = cast("tuple[str, ...]", real["real_incomplete"])
    merged = replace(summary, **real)  # type: ignore[arg-type]
    return replace(merged, incomplete=tuple(dict.fromkeys([*summary.incomplete, *real_incomplete])))


def _summary_extras(path: Path) -> tuple[dict[str, object], float]:
    """The non-`RunSummary` keys of a stored summary, and its ``usd_per_script_mean_now``."""
    data: dict[str, object] = json.loads(path.read_text(encoding="utf-8"))
    names = {f.name for f in fields(RunSummary)} | {"usd_per_script_mean_now"}
    now = data.get("usd_per_script_mean_now", 0.0)
    return {k: v for k, v in data.items() if k not in names}, float(cast("float", now))


def _rewrite_summary(
    path: Path,
    summary: RunSummary,
    *,
    usd_now: float | None = None,
    extra_update: Mapping[str, object] | None = None,
) -> None:
    """Replace the `RunSummary` fields of a stored summary, keeping its other keys."""
    extra, stored_now = _summary_extras(path)
    extra.update(extra_update or {})
    write_summary(
        summary,
        path,
        usd_per_script_mean_now=stored_now if usd_now is None else usd_now,
        extra=extra,
    )


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


def _real_projection(
    out_dir: Path,
    max_run_usd: Mapping[str, float] | None,
    providers: Sequence[str] = (),
    *,
    pinned: bool = False,
) -> dict[str, float]:
    """A real run's projected cost: the larger of *max_run_usd* and the latest real run's.

    The latest run is of the same kind: a pinned run (it has ``upstream_records.jsonl``)
    costs less than a live one, so mixing them would under-project the next live baseline.
    Every provider in *providers* (those of the models in play) must be projected, so
    a stage's spend (the Gemini scan metadata) is checked against its cap up front.
    """
    costs = sorted(
        (
            p
            for p in out_dir.glob(f"*/{REAL_RUN_PREFIX}*/{RUN_COST_FILE}")
            if (p.parent / UPSTREAM_RECORDS_FILE).is_file() is pinned
        ),
        key=lambda p: p.stat().st_mtime,
    )
    last: dict[str, float] = {}
    if costs:
        data = json.loads(costs[-1].read_text(encoding="utf-8"))
        last = {str(k): float(v) for k, v in data.items()}
    explicit = dict(max_run_usd or {})
    if not last and not explicit:
        raise SpendCapError(
            "no real run in this out-dir to project the cost from; pass "
            "--max-run-usd provider=usd for the first one"
        )
    projected = {
        provider: max(last.get(provider, 0.0), explicit.get(provider, 0.0))
        for provider in sorted(set(last) | set(explicit))
    }
    missing = sorted(set(providers) - set(projected))
    if missing:
        raise SpendCapError(
            f"no projected cost for provider(s) {', '.join(missing)}, which the real path "
            "calls; pass --max-run-usd provider=usd for each"
        )
    return projected


def _require_pin(
    out_dir: Path, against: str, run_index: int, scripts: Sequence[RealScript]
) -> list[CallRecord]:
    """The *against* rung's composed real records for repeat *run_index*, or `LadderStateError`.

    Refuses, before any spend, when the rung's upstream was not pinned (a run from before
    pins, a reference rung), its cache is gone, or a script is missing, incomplete, not
    upstream-called or changed since the pin was written. Never falls back to a live run.
    """
    run_name = f"{REAL_RUN_PREFIX}{run_index}"
    run_dir = out_dir / against / run_name
    pin_path = run_dir / PIN_FILE
    if not pin_path.is_file():
        raise LadderStateError(
            f"{pin_path} is missing: the --against rung's {run_name} upstream was not pinned "
            "(a run from before H1, or a reference rung); re-run "
            "`baseline --split real --restart-baseline` (or into a new --out-dir)"
        )
    cache = cache_dir_for(out_dir, f"{against}-{run_name}")
    if not cache.is_dir():
        raise LadderStateError(
            f"{cache} is missing: the --against rung's {run_name} cache was deleted, so its "
            "upstream cannot be replayed; re-run `baseline --split real --restart-baseline`"
        )
    pinned = json.loads(pin_path.read_text(encoding="utf-8")).get("scripts") or {}
    bad: list[str] = []
    for script in scripts:
        entry = pinned.get(script.key)
        if not isinstance(entry, dict):
            bad.append(f"{script.key} ({run_name}: not in the pin)")
        elif entry.get("complete") is not True:
            bad.append(f"{script.key} ({run_name}: the pinned run did not complete it)")
        elif not entry.get("upstream_calls"):
            bad.append(f"{script.key} ({run_name}: the pin holds no upstream calls)")
        elif (
            entry.get("scan_sha256") != script.scan_sha256
            or entry.get("scheme_sha256") != script.scheme_sha256
        ):
            bad.append(f"{script.key} ({run_name}: scan or scheme changed since the pin)")
    if bad:
        raise LadderStateError(
            f"the --against rung {against!r} cannot be replayed: {'; '.join(bad)}. "
            "Re-run `baseline --split real --restart-baseline`."
        )
    keys = {script.key for script in scripts}
    records = read_records(require_file(run_dir / "records.jsonl", f"{against} {run_name} records"))
    upstream = run_dir / UPSTREAM_RECORDS_FILE
    if upstream.is_file():
        records += read_records(upstream)
    return [r for r in records if r.case_key in keys]


def run_real(
    label: str,
    overrides: Mapping[str, object],
    *,
    run_index: int,
    out_dir: Path,
    scripts: Sequence[RealScript],
    settings: Settings | None = None,
    caps: SpendCaps | None = None,
    max_run_usd: Mapping[str, float] | None = None,
    spend_file: Path | None = None,
    mark: Callable[[RealScript, GeminiClient, Settings], CorrectionResult] | None = None,
    on_checks_passed: Callable[[], None] | None = None,
    cache_mode: CacheMode = "bypass",
    pin_from: str | None = None,
    live_tags: Sequence[str] = (),
) -> tuple[RealScriptResult, ...]:
    """One live pass over the frozen real scripts under *overrides*; write and score it.

    Writes ``<out_dir>/<label>/real-<run_index>/`` (records, scored results, the
    escalation events, the marking replies, the run's cost). The run's cache dir is
    ``cache/<label>-real-<run_index>``. Prices and the spend caps are checked before
    anything is written (the reference digests were checked when *scripts* were
    loaded); *on_checks_passed* runs next, and only then is the client built. Each
    finished script is booked to the ledger by `_CapGuard`. A script whose marking
    raised is incomplete (its reason reaches ``real_incomplete``); scripts the cap
    stopped are "not run (spend cap)".

    - *cache_mode* ``bypass`` (the default): every call is live and nothing is kept.
    - ``read_write`` with no *pin_from*: a pin. The cache dir starts empty, every call
      is live and its reply is kept; ``pin.json`` is written when the loop ends.
    - ``read_write`` with *pin_from*: a pinned run. The cache dir starts as a copy of
      the *pin_from* rung's for this repeat; the tags `real_live_tags` expands *live_tags*
      to are refreshed (live, and their replies kept), every other tag replays. The
      *pin_from* rung's non-live records are saved as ``upstream_records.jsonl`` and
      scored with this run's, so cost covers the whole pipeline; billed spend is only
      the live records. A live call under a pinned tag raises `UpstreamNotFrozen`.
    """
    if not scripts:
        raise LadderStateError("no real scripts: build and freeze the reference set first")
    if pin_from is not None and cache_mode == "bypass":
        raise ValueError("pin_from replays a cache: use cache_mode='read_write'")
    if live_tags and pin_from is None:
        raise ValueError("live_tags names what a pinned run calls live; pass pin_from too")
    caps = caps or SpendCaps()
    run_name = f"{REAL_RUN_PREFIX}{run_index}"
    run_dir = out_dir / label / run_name
    cache_dir = cache_dir_for(out_dir, f"{label}-{run_name}")
    pinned = pin_from is not None
    live = real_live_tags(live_tags) if pinned else ()
    discipline: dict[str, object] = {
        "gemini.cache_forget_enabled": False,
        "paths.cache_dir": str(cache_dir),
    }
    if cache_mode != "bypass":
        discipline["gemini.cache_mode_for"] = dict.fromkeys(live, "refresh")
    effective = apply_overrides(apply_overrides(settings or load_settings(), overrides), discipline)
    preflight_prices(effective)
    upstream: list[CallRecord] = []
    if pin_from is not None:
        upstream = [
            r for r in _require_pin(out_dir, pin_from, run_index, scripts) if r.task_tag not in live
        ]
    ledger = SpendLedger(spend_file or DEFAULT_SPEND_FILE)
    spent_before = ledger.spent()
    providers = sorted(
        {"anthropic" if is_anthropic_model(m) else "gemini" for m in models_in_play(effective)}
    )
    check_can_start(
        spent_before, _real_projection(out_dir, max_run_usd, providers, pinned=pinned), caps
    )
    if on_checks_passed is not None:
        on_checks_passed()
    if cache_mode != "bypass":
        if cache_dir.exists():
            shutil.rmtree(cache_dir)
        if pin_from is not None:
            shutil.copytree(cache_dir_for(out_dir, f"{pin_from}-{run_name}"), cache_dir)
        else:
            cache_dir.mkdir(parents=True)
        # A rerun must not leave the last run's pin beside this run's records.
        (run_dir / PIN_FILE).unlink(missing_ok=True)
        (run_dir / UPSTREAM_RECORDS_FILE).unlink(missing_ok=True)
        if pinned:
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / UPSTREAM_RECORDS_FILE).write_text(
                "".join(json.dumps(asdict(r), sort_keys=True) + "\n" for r in upstream),
                encoding="utf-8",
            )
    marker = mark or mark_real_script
    gemini = GeminiClient(effective, default_cache_mode=cache_mode)
    guard = _CapGuard(
        CapWatch(caps, spent_before),
        ledger,
        label=f"{label}/{run_name}",
        frozen_live_tags=list(live) if pinned else None,
    )
    replies = ReplyLog()
    replies.wrap(gemini)
    escalations: list[dict[str, object]] = []
    current: list[str] = []

    def on_escalate(**payload: object) -> None:
        escalations.append({"case_key": current[-1] if current else None, **payload})

    outcomes: dict[str, tuple[CorrectionResult | None, float, str | None]] = {}
    bus.subscribe(EventType.GEMINI_ESCALATE, on_escalate)
    with record_calls():
        reset_process_counters()
        try:
            for script in scripts:
                current.append(script.key)
                replies.current = script.key
                set_call_context(case_key=script.key)
                started = time.monotonic()
                correction: CorrectionResult | None = None
                failure: str | None = None
                try:
                    correction = marker(script, gemini, effective)
                except CostCeilingError as exc:
                    failure = "cost ceiling"
                    _LOG.warning("real script %s: cost ceiling: %s", script.key, exc)
                except Exception as exc:
                    # The type only: a message can quote model output, i.e. student text, and
                    # `failure` reaches the committed reports. The full text stays in the log.
                    failure = type(exc).__name__
                    _LOG.warning("real script %s: %s: %s", script.key, type(exc).__name__, exc)
                outcomes[script.key] = (correction, (time.monotonic() - started) * 1000, failure)
                try:
                    guard(script.key)
                except SpendCapReached:
                    break
        finally:
            bus.unsubscribe(EventType.GEMINI_ESCALATE, on_escalate)
            set_call_context(case_key=None)
            records = process_call_records()
            run_dir.mkdir(parents=True, exist_ok=True)
            if len(outcomes) == len(scripts) and any(o[2] is None for o in outcomes.values()):
                # A run cut short, or one where every script failed, is not written: it
                # would lower the next projection.
                (run_dir / RUN_COST_FILE).write_text(
                    json.dumps(cost_by_provider(records), sort_keys=True) + "\n", encoding="utf-8"
                )
            booked = set(guard.completed)
            ledger.add(cost_by_provider([r for r in records if r.case_key not in booked]))
            (run_dir / "records.jsonl").write_text(
                "".join(json.dumps(asdict(r), sort_keys=True) + "\n" for r in records),
                encoding="utf-8",
            )
            (run_dir / "escalations.jsonl").write_text(
                "".join(json.dumps(e, sort_keys=True, default=str) + "\n" for e in escalations),
                encoding="utf-8",
            )
            write_replies(run_dir / REPLIES_FILE, replies.rows)
    if pinned:
        # Calls made outside any script (no case_key) are not seen by the guard.
        bad = _untagged_live(records, frozenset(live))
        if bad:
            raise UpstreamNotFrozen(f"{label}/{run_name}", bad, live)
    composed = [*records, *upstream]
    if cache_mode != "bypass":
        _write_pin(
            run_dir / PIN_FILE,
            label=label,
            run_index=run_index,
            pin_from=pin_from,
            live=live,
            scripts=scripts,
            outcomes=outcomes,
            records=composed,
        )
    cascade = effective.gemini.cascade_enabled is True
    not_run: tuple[CorrectionResult | None, float, str | None] = (None, 0.0, "not run (spend cap)")
    results = tuple(
        score_script(
            script,
            outcomes.get(script.key, not_run)[0],
            [r for r in composed if r.case_key == script.key],
            latency_ms=outcomes.get(script.key, not_run)[1],
            failure=outcomes.get(script.key, not_run)[2],
            escalations=[e for e in escalations if e.get("case_key") == script.key],
            cascade_enabled=cascade,
            replies=replies.for_script(script.key),
            keep_higher=effective.gemini.correction_retry_keep_higher is True,
        )
        for script in scripts
    )
    write_real_results(run_dir / "real_results.json", results)
    return results


def _write_pin(
    path: Path,
    *,
    label: str,
    run_index: int,
    pin_from: str | None,
    live: Sequence[str],
    scripts: Sequence[RealScript],
    outcomes: Mapping[str, tuple[CorrectionResult | None, float, str | None]],
    records: Sequence[CallRecord],
) -> None:
    """``pin.json``: which scripts' upstream this run's cache holds, for `_require_pin`."""
    entries: dict[str, dict[str, object]] = {}
    for script in scripts:
        outcome = outcomes.get(script.key)
        entries[script.key] = {
            # Complete only when the marker returned: a failure or a cap stop is not.
            "complete": outcome is not None and outcome[0] is not None and outcome[2] is None,
            "upstream_calls": sum(
                1 for r in records if r.case_key == script.key and r.task_tag in _PRE_MARKING_TAGS
            ),
            "scan_sha256": script.scan_sha256,
            "scheme_sha256": script.scheme_sha256,
        }
    path.write_text(
        json.dumps(
            {
                "label": label,
                "run_index": run_index,
                "pinned_from": pin_from,
                "live_tags": list(live),
                "scripts": entries,
            },
            indent=1,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _judge(
    kind: JudgeKind,
    against: RunSummary,
    candidate: RunSummary,
    *,
    floor: int,
    real_floor: float,
    original_p95: float,
) -> Verdict:
    if kind == "cost":
        return judge_cost_lever(
            against,
            candidate,
            aa_floor=floor,
            real_aa_floor=real_floor,
            original_latency_p95_ms=original_p95,
        )
    if kind == "accuracy":
        return judge_accuracy_lever(against, candidate, aa_floor=floor, real_aa_floor=real_floor)
    if kind == "record":
        return judge_record(against, candidate)
    raise ValueError(f"judge_kind must be one of {_JUDGE_KINDS}, got {kind!r}")


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
    screens = [
        d
        for d in out_dir.iterdir()
        if d.is_dir() and d.name not in keep and not _is_reference_rung(d)
    ]
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
        for real_cache in (out_dir / CACHE_SUBDIR).glob(f"{run_dir.name}-{REAL_RUN_PREFIX}*"):
            shutil.rmtree(real_cache)


def _is_reference_rung(run_dir: Path) -> bool:
    """A comparison rung (the Gemini rung) is evidence, not a screen: a restart keeps it."""
    summary = run_dir / "summary.json"
    if not summary.is_file():
        return False
    return json.loads(summary.read_text(encoding="utf-8")).get("reference_rung") is True


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
    split: Split = "dev",
    repeats: int = 1,
    real_scripts: Sequence[RealScript] = (),
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

    *split* real or both adds two live real runs, each a pin (``cache/baseline-real-N``,
    ``pin.json``), and ``real_aa_floor`` (the absolute difference of the two runs'
    abs_error: the full-pipeline floor). It then re-runs marking twice on those pins
    (``baseline_aa/real-N``) for ``real_marking_aa_floor``, the mean over the repeats of
    the absolute difference between a baseline repeat and its A/A repeat: the floor of a
    screen that changes only marking. *repeats* 2 stores the dev baseline as the
    pair of the baseline and A/A runs. The real side always runs twice, whatever
    *repeats* is.
    """
    if restart and aa_only:
        raise ValueError("--restart-baseline and --aa-only are mutually exclusive")
    _check_split(split, repeats)
    if split != "dev" and aa_only:
        raise ValueError("--aa-only reruns the dev A/A run only; use --split dev")
    if aa_only and repeats == 2 and not (out_dir / BASELINE_LABEL / RAW_SUMMARY_FILE).exists():
        raise LadderStateError(
            f"--aa-only with repeats=2 needs {RAW_SUMMARY_FILE}, the unpaired baseline; this "
            "baseline predates it and may already be a pair. Use --restart-baseline."
        )
    if split != "dev" and not real_scripts:
        raise LadderStateError("the real split needs the frozen reference scripts")
    base_summary = out_dir / BASELINE_LABEL / "summary.json"
    floor = 0
    if split in ("dev", "both"):
        floor = _dev_baseline(
            out_dir=out_dir,
            golden_dir=golden_dir,
            cases=cases,
            settings=settings,
            caps=caps,
            max_run_usd=max_run_usd,
            spend_file=spend_file,
            restart=restart,
            aa_only=aa_only,
        )
        raw = base_summary.parent / RAW_SUMMARY_FILE
        if not aa_only or not raw.exists():
            # The unpaired baseline run: an --aa-only rerun pairs from it, never from a pair.
            shutil.copyfile(base_summary, raw)
        if repeats == 2 or aa_only:
            current = read_summary(base_summary)
            real_part = {
                f.name: getattr(current, f.name)
                for f in fields(RunSummary)
                if f.name.startswith("real_")
            }
            unpaired = replace(read_summary(raw), **real_part)
            _, base_now = _summary_extras(raw)
            if repeats == 2:
                _, aa_now = _summary_extras(out_dir / AA_LABEL / "summary.json")
                _rewrite_summary(
                    base_summary,
                    pair_summaries(unpaired, read_summary(out_dir / AA_LABEL / "summary.json")),
                    usd_now=(base_now + aa_now) / 2,
                )
            else:
                _rewrite_summary(base_summary, unpaired, usd_now=base_now)
    if split in ("real", "both"):
        hook: Callable[[], None] | None = None
        if split == "real":
            if base_summary.exists() and not restart:
                raise LadderStateError(
                    f"{base_summary} exists; pass --restart-baseline to replace this baseline"
                )

            def wipe_real() -> None:
                _archive_ladder(out_dir)
                if (out_dir / BASELINE_LABEL).exists():
                    shutil.rmtree(out_dir / BASELINE_LABEL)
                (out_dir / AA_FLOOR_FILE).unlink(missing_ok=True)

            hook = wipe_real if restart else None
        runs = [
            run_real(
                BASELINE_LABEL,
                {},
                run_index=index,
                out_dir=out_dir,
                scripts=real_scripts,
                settings=settings,
                caps=caps,
                max_run_usd=max_run_usd,
                spend_file=spend_file,
                on_checks_passed=hook if index == 1 else None,
                cache_mode="read_write",
            )
            for index in (1, 2)
        ]
        keys = [script.key for script in real_scripts]
        if split == "real":
            write_summary(
                with_real(EMPTY_DEV_SUMMARY, runs, keys),
                base_summary,
                usd_per_script_mean_now=0.0,
                extra={"overrides": {}, "live_tags": [], "frozen_upstream": False, "split": "real"},
            )
        else:
            _rewrite_summary(base_summary, with_real(read_summary(base_summary), runs, keys))
        first, second = (float(sum(s.abs_error for s in run)) for run in runs)
        marking_floor: float | None = None
        if all(s.incomplete is None for run in runs for s in run):
            # The same upstream, marking re-run: what a pinned marking screen's null looks like.
            # An incomplete baseline has no usable pin, so it spends nothing more and sets no floor.
            aa_runs = [
                run_real(
                    AA_LABEL,
                    {},
                    run_index=index,
                    out_dir=out_dir,
                    scripts=real_scripts,
                    settings=settings,
                    caps=caps,
                    max_run_usd=max_run_usd,
                    spend_file=spend_file,
                    cache_mode="read_write",
                    pin_from=BASELINE_LABEL,
                    live_tags=DEFAULT_LIVE_TAGS,
                )
                for index in (1, 2)
            ]
            # A failed pinned script scores 0 on every leaf and would inflate the floor, which
            # the judges then treat as allowed noise: never compute a floor from incomplete runs.
            failed = [
                f"{AA_LABEL} real-{i}:{s.key} ({s.incomplete})"
                for i, run in enumerate(aa_runs, start=1)
                for s in run
                if s.incomplete
            ]
            if failed:
                raise LadderStateError(
                    f"the marking-only A/A runs are incomplete: {'; '.join(failed)}. No "
                    "real_marking_aa_floor was written; re-run `baseline --split real "
                    "--restart-baseline`."
                )
            # The mean of the per-repeat absolute differences, not the absolute mean difference:
            # two repeats whose noise cancels cannot produce a floor near 0.
            marking_floor = sum(
                abs(sum(s.abs_error for s in base) - sum(s.abs_error for s in aa))
                for base, aa in zip(runs, aa_runs, strict=True)
            ) / len(runs)
        floors_path = out_dir / AA_FLOOR_FILE
        floors: dict[str, object] = (
            json.loads(floors_path.read_text(encoding="utf-8"))
            if split == "both" and floors_path.is_file()
            else {"aa_floor": 0}
        )
        floors["real_aa_floor"] = abs(first - second)
        if marking_floor is not None:
            floors["real_marking_aa_floor"] = marking_floor
        floors_path.write_text(json.dumps(floors, sort_keys=True) + "\n", encoding="utf-8")
    if not aa_only:
        _stamp_split(base_summary, split)
    return floor


def _dev_baseline(
    *,
    out_dir: Path,
    golden_dir: Path,
    cases: Sequence[GoldenCase] | None,
    settings: Settings | None,
    caps: SpendCaps | None,
    max_run_usd: Mapping[str, float] | None,
    spend_file: Path | None,
    restart: bool,
    aa_only: bool,
) -> int:
    """The dev rung 0 and its A/A rerun; write and return the churn floor."""
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
            raise LadderStateError(
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
    raw = base_summary.parent / RAW_SUMMARY_FILE
    # An --aa-only rerun measures churn against the unpaired baseline, never a pair.
    a = require_complete(base_summary, "baseline summary")
    if aa_only and raw.exists():
        a = require_complete(raw, "unpaired baseline summary")
    aa_cache.mkdir(parents=True, exist_ok=True)
    one(AA_LABEL, aa_cache, "bypass")
    b = require_complete(out_dir / AA_LABEL / "summary.json", "A/A summary")
    floor = aa_floor(a, b)
    floors_path = out_dir / AA_FLOOR_FILE
    floors: dict[str, object] = (
        json.loads(floors_path.read_text(encoding="utf-8")) if floors_path.is_file() else {}
    )
    floors["aa_floor"] = floor
    floors_path.write_text(json.dumps(floors, sort_keys=True) + "\n", encoding="utf-8")
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


def _check_label(label: str) -> None:
    """``-real-`` in a label would collide ``cache/<label>`` with another rung's real pin."""
    if f"-{REAL_RUN_PREFIX}" in label:
        raise ValueError(
            f"{label!r} contains '-{REAL_RUN_PREFIX}', which names a real-run cache dir"
        )


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
    split: Split = "dev",
    judge_kind: JudgeKind = "cost",
    repeats: int = 1,
    real_scripts: Sequence[RealScript] = (),
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

    - Split: *split* real or both also runs the real scripts live *repeats* times;
      *judge_kind* picks the judge (cost, accuracy, or record-only). *repeats* 2 on
      the dev split reruns it as ``<label>-r2`` and judges the pair.

    A refused screen (missing state, a rejected *against*, a failed precondition
    in `run_config`) writes nothing. Otherwise writes ``verdict.json`` beside the
    run's summary and appends *label* to ``ladder.json``.
    """
    if label in (BASELINE_LABEL, AA_LABEL, CACHE_SUBDIR, ARCHIVE_SUBDIR):
        raise ValueError(f"{label!r} is reserved")
    if label.endswith(REPEAT_SUFFIX):
        raise ValueError(f"{label!r} ends in {REPEAT_SUFFIX!r}, which names a screen's second run")
    _check_label(label)
    _check_split(split, repeats)
    if judge_kind not in _JUDGE_KINDS:
        raise ValueError(f"judge_kind must be one of {_JUDGE_KINDS}, got {judge_kind!r}")
    if split != "dev" and not real_scripts:
        raise LadderStateError("the real split needs the frozen reference scripts")
    if against == label:
        raise LadderStateError(f"screen {label!r} cannot stack on itself (--against {against})")
    for row in _ladder_labels(out_dir):
        # A row without its verdict cannot show it does not stack on *label*:
        # refuse rather than skip it (skipping would let a re-screen orphan it).
        row_verdict = require_file(
            out_dir / row / "verdict.json", f"ladder row {row!r} verdict (needed to re-screen)"
        )
        if json.loads(row_verdict.read_text(encoding="utf-8")).get("against") == label:
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
    floors = json.loads(floor_path.read_text(encoding="utf-8"))
    floor = int(floors["aa_floor"])
    real_floor_raw = floors.get("real_aa_floor")
    if split != "dev" and real_floor_raw is None:
        raise LadderStateError(
            f"{floor_path} has no real_aa_floor: the baseline has no real split. "
            "Run `baseline --split both` first."
        )
    real_floor = float(real_floor_raw or 0.0)
    real_live: tuple[str, ...] = ()
    floor_kind: Literal["marking", "full"] = "full"
    if split != "dev":
        real_live = real_live_tags(live_tags)
        floor_kind = real_floor_kind(real_live)
        if floor_kind == "marking":
            marking_raw = floors.get("real_marking_aa_floor")
            if marking_raw is None:
                raise LadderStateError(
                    f"{floor_path} has no real_marking_aa_floor: the baseline predates the "
                    "marking-only floor. Run `baseline --split real --restart-baseline`."
                )
            real_floor = float(marking_raw)
    frozen = (
        read_records(require_file(base_dir / "records.jsonl", "baseline records"))
        if split != "real"
        else []
    )
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
    if split != "dev":
        # Before any spend, dev runs included: a refused real screen costs nothing.
        for index in range(1, repeats + 1):
            _require_pin(out_dir, against, index, real_scripts)
    run_dir = out_dir / label
    cache = cache_dir_for(out_dir, label)

    summary_path = run_dir / "summary.json"
    base_cache = cache_dir_for(out_dir, BASELINE_LABEL)

    def drop_stale() -> None:
        for stale in ("verdict.json", "summary.json", "results.json"):
            (run_dir / stale).unlink(missing_ok=True)
        _drop_from_ladder(out_dir, label)

    def seed() -> None:
        drop_stale()
        if cache.exists():
            shutil.rmtree(cache)
        shutil.copytree(base_cache, cache)

    candidate: RunSummary | None = None
    usd_now: float | None = None
    if split in ("dev", "both"):
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
            summary_extra={"against": against, "set": dict(sets), "split": split},
            spend_file=spend_file,
            on_checks_passed=seed,
        )
        if repeats == 2:
            second_label = f"{label}{REPEAT_SUFFIX}"
            second_cache = cache_dir_for(out_dir, second_label)

            def seed_second() -> None:
                if second_cache.exists():
                    shutil.rmtree(second_cache)
                shutil.copytree(base_cache, second_cache)

            second = run_config(
                second_label,
                combined,
                out_dir=out_dir,
                golden_dir=golden_dir,
                cases=cases,
                settings=settings,
                caps=caps,
                max_run_usd=max_run_usd,
                cache_dir=second_cache,
                cache_mode="read_write",
                live_tags=tags,
                frozen_upstream=frozen,
                summary_extra={
                    "against": against,
                    "set": dict(sets),
                    "repeat_of": label,
                    "split": split,
                },
                spend_file=spend_file,
                on_checks_passed=seed_second,
            )
            _, first_now = _summary_extras(summary_path)
            _, second_now = _summary_extras(out_dir / second_label / "summary.json")
            usd_now = (first_now + second_now) / 2
            candidate = pair_summaries(candidate, second)
    if split in ("real", "both"):
        runs = [
            run_real(
                label,
                combined,
                run_index=index,
                out_dir=out_dir,
                scripts=real_scripts,
                settings=settings,
                caps=caps,
                max_run_usd=max_run_usd,
                spend_file=spend_file,
                on_checks_passed=drop_stale if candidate is None and index == 1 else None,
                cache_mode="read_write",
                pin_from=against,
                live_tags=live_tags,
            )
            for index in range(1, repeats + 1)
        ]
        candidate = with_real(
            candidate or EMPTY_DEV_SUMMARY, runs, [script.key for script in real_scripts]
        )
    if candidate is None:  # unreachable: `_check_split` ran first
        raise ValueError(f"split must be one of {_SPLITS}, got {split!r}")
    real_extra: dict[str, object] = {}
    if split != "dev":
        real_extra["frozen_upstream_real"] = {
            "from": against,
            "live_tags": list(real_live),
            "pinned_tags": sorted(frozenset().union(*REAL_STAGES) - set(real_live)),
        }
    if summary_path.is_file():
        _rewrite_summary(summary_path, candidate, usd_now=usd_now, extra_update=real_extra)
    else:
        write_summary(
            candidate,
            summary_path,
            usd_per_script_mean_now=0.0,
            extra={
                "overrides": combined,
                "live_tags": tags,
                "frozen_upstream": False,
                "against": against,
                "set": dict(sets),
                "split": split,
                **real_extra,
            },
        )
    verdict = _judge(
        judge_kind,
        read_summary(against_summary_path),
        candidate,
        floor=floor,
        real_floor=real_floor,
        original_p95=original_p95,
    )
    verdict_extra: dict[str, object] = {}
    if split != "dev":
        pinned_count = len(frozenset().union(*REAL_STAGES) - set(real_live))
        basis = (
            f"judged on the marking-only A/A floor {real_floor:.2f}"
            if floor_kind == "marking"
            else f"judged on the full-pipeline A/A floor {real_floor:.2f}"
        )
        verdict = replace(
            verdict,
            notes=(
                *verdict.notes,
                f"real upstream pinned from {against} ({pinned_count} stage tags not live, "
                f"replayed where the rung called them); {basis}; "
                "real latency excludes the replayed upstream",
            ),
        )
        verdict_extra = {
            "real_live_tags": list(real_live),
            "real_pinned_from": against,
            "real_floor_kind": floor_kind,
            "real_floor": real_floor,
        }
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
                "judge": judge_kind,
                "split": split,
                "repeats": repeats,
                "notes": list(verdict.notes),
                **verdict_extra,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    append_ladder(out_dir, label)
    return verdict


def run_reference_rung(
    label: str,
    *,
    out_dir: Path,
    real_scripts: Sequence[RealScript],
    dev_summary_from: Path,
    settings: Settings | None = None,
    repeats: int = 2,
    caps: SpendCaps | None = None,
    max_run_usd: Mapping[str, float] | None = None,
    spend_file: Path | None = None,
) -> RunSummary:
    """A comparison rung (the Gemini rung `judge_flip` reads): never a ladder row.

    The real split runs live *repeats* times under *settings*. The dev figures are
    read from *dev_summary_from*, a complete earlier run of the same configuration on
    the pinned corpus: two fresh Gemini dev runs do not fit under the Gemini cap.
    """
    if label in (BASELINE_LABEL, AA_LABEL, CACHE_SUBDIR, ARCHIVE_SUBDIR) or label in _ladder_labels(
        out_dir
    ):
        raise LadderStateError(f"{label!r} is reserved or already a ladder row")
    _check_label(label)
    if label.endswith(REPEAT_SUFFIX):
        raise LadderStateError(
            f"{label!r} ends in {REPEAT_SUFFIX!r}, which names a screen's second run"
        )
    if repeats not in (1, 2):
        raise ValueError(f"repeats must be 1 or 2, got {repeats}")
    stored = out_dir / label / "summary.json"
    if (out_dir / label).exists() and not (
        stored.is_file() and json.loads(stored.read_text(encoding="utf-8")).get("reference_rung")
    ):
        raise LadderStateError(
            f"{out_dir / label} exists and is not a reference rung; use another label"
        )
    dev = require_complete(dev_summary_from, "dev summary of the reference rung")

    def drop_stale() -> None:
        stored.unlink(missing_ok=True)

    runs = [
        run_real(
            label,
            {},
            run_index=index,
            out_dir=out_dir,
            scripts=real_scripts,
            settings=settings,
            caps=caps,
            max_run_usd=max_run_usd,
            spend_file=spend_file,
            on_checks_passed=drop_stale if index == 1 else None,
        )
        for index in range(1, repeats + 1)
    ]
    summary = with_real(dev, runs, [script.key for script in real_scripts])
    write_summary(
        summary,
        out_dir / label / "summary.json",
        usd_per_script_mean_now=0.0,
        extra={
            "reference_rung": True,
            "split": "real",
            "dev_from": str(dev_summary_from),
            "overrides": {},
            "live_tags": [],
        },
    )
    return summary


def flip_verdict(out_dir: Path, *, candidate: str, gemini: str) -> Verdict:
    """`judge_flip` of the *candidate* rung against the *gemini* rung; writes flip_verdict.json."""
    if candidate not in _ladder_labels(out_dir):
        raise LadderStateError(f"{candidate!r} is not a ladder row")
    cand_verdict = require_file(out_dir / candidate / "verdict.json", f"rung {candidate!r} verdict")
    if json.loads(cand_verdict.read_text(encoding="utf-8")).get("passed") is not True:
        raise LadderStateError(f"{candidate!r} did not pass its screen; it cannot be flipped")
    cand = read_summary(require_file(out_dir / candidate / "summary.json", f"rung {candidate!r}"))
    gem_path = require_file(out_dir / gemini / "summary.json", f"Gemini rung {gemini!r}")
    if json.loads(gem_path.read_text(encoding="utf-8")).get("reference_rung") is not True:
        raise LadderStateError(f"{gemini!r} is not a reference rung (run_reference_rung)")
    gem = read_summary(gem_path)
    floors = json.loads(
        require_file(out_dir / AA_FLOOR_FILE, "A/A floor aa_floor.json").read_text(encoding="utf-8")
    )
    verdict = judge_flip(gem, cand, aa_floor=int(floors["aa_floor"]))
    (out_dir / FLIP_VERDICT_FILE).write_text(
        json.dumps(
            {
                "candidate": candidate,
                "gemini": gemini,
                "passed": verdict.passed,
                "saving": verdict.saving,
                "extra_mismarks": verdict.extra_mismarks,
                "allowed_extra": verdict.allowed_extra,
                "reasons": list(verdict.reasons),
                "notes": list(verdict.notes),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
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
    if label.endswith(REPEAT_SUFFIX):
        raise LadderStateError(
            f"resummarise {label!r} is refused: it is a screen's second run, folded into the "
            "paired summary of the screen it repeats. Rescreen that screen instead."
        )
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
    stored = run_dir / "summary.json"
    if stored.is_file() and json.loads(stored.read_text(encoding="utf-8")).get("real_scripts"):
        raise LadderStateError(
            f"resummarise {label!r} is refused: it has a real split, whose per-leaf results "
            "are not rebuilt from records. Rescreen it instead."
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
