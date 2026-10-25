"""Sub-project C real split: frozen real scripts, marked on the production path, scored per leaf.

A real script is loaded only from the frozen reference manifest, and only when every
digest still matches (`load_real_scripts`), so a changed reference stops a run before
any spend. Scoring never narrows the denominator: a leaf the run dropped, lost or
failed to mark counts as mark 0 against its reference.
"""

from __future__ import annotations

import json
import logging
import math
import threading
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from lemely.accuracy.reference import (
    FROZEN_MARKER,
    MANIFEST_FILE,
    REFERENCE_ROOT,
    read_manifest,
    read_reference,
    sha256_file,
)
from lemely.core.schemas import UNSCORED_MARKER_SOURCES, marker_scored

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from pydantic import BaseModel

    from lemely.accuracy.reference import ManifestEntry
    from lemely.core.schemas import CorrectionResult
    from lemely.io.gemini import CallRecord, GeminiClient
    from lemely.runtime.config import Settings

_LOG = logging.getLogger(__name__)
DEFAULT_MANIFEST = REFERENCE_ROOT / MANIFEST_FILE
ESCALATION_TAG = "escalation"
ADJUDICATION_TAG = "adjudication"
#: Task tags whose replies carry a mark: first pass, borderline retry, escalation, adjudication.
CORRECTION_FAMILY_TAGS = frozenset(
    {"correction", "correction_borderline", ESCALATION_TAG, ADJUDICATION_TAG}
)
#: One run's saved marking replies (student data: rationales quote answers).
REPLIES_FILE = "replies.jsonl"
#: The review reason ``correct_paper`` writes when the marking call itself failed.
_AI_FAILED = "AI marking failed"
#: Unscored leaves whose marker never produced output (not a binder drop, not a student blank).
_LOST_SOURCES = UNSCORED_MARKER_SOURCES - {"dropped", "blank"}
#: The borderline retry publishes GEMINI_ESCALATE with this suffix on the model name.
_BORDERLINE_SUFFIX = "(thinking)"


class ReferenceDrift(RuntimeError):
    """A frozen reference, scheme or scan changed or went missing; nothing may run."""


@dataclass(frozen=True)
class RealScript:
    key: str
    scan_path: Path
    scheme_path: Path
    reference_path: Path
    reference_sha256: str
    scheme_sha256: str
    scan_sha256: str


def _frozen_marker_problems(manifest_path: Path, entries: Sequence[ManifestEntry]) -> list[str]:
    """FROZEN markers and manifest entries must agree both ways (freeze writes the marker first)."""
    frozen = {p.parent.resolve() for p in manifest_path.parent.glob(f"*/{FROZEN_MARKER}")}
    listed = {Path(e.reference_path).parent.resolve(): e.key for e in entries}
    problems = [
        f"{d / FROZEN_MARKER} is FROZEN but not in the manifest {manifest_path}"
        for d in sorted(frozen - listed.keys())
    ]
    problems += [
        f"{listed[d]}: manifest entry has no FROZEN marker in {d}"
        for d in sorted(listed.keys() - frozen)
    ]
    for e in entries:
        marker = Path(e.reference_path).parent / FROZEN_MARKER
        if marker.is_file() and marker.read_text(encoding="utf-8").strip() != e.reference_sha256:
            problems.append(f"{e.key}: FROZEN marker {marker} differs from the manifest digest")
    return problems


def load_real_scripts(
    manifest_path: Path = DEFAULT_MANIFEST, *, only: Sequence[str] = ()
) -> list[RealScript]:
    """The frozen scripts of *manifest_path* (all, or the keys in *only*), digests checked."""
    entries = read_manifest(manifest_path)
    if not entries:
        raise ReferenceDrift(f"{manifest_path} lists no scripts; freeze the reference set first")
    known = {e.key for e in entries}
    unknown = sorted(set(only) - known)
    if unknown:
        raise ReferenceDrift(f"not in {manifest_path}: {', '.join(unknown)}")
    problems: list[str] = _frozen_marker_problems(manifest_path, entries)
    scripts: list[RealScript] = []
    for e in entries:
        if only and e.key not in only:
            continue
        for what, raw, want in (
            ("reference", e.reference_path, e.reference_sha256),
            ("scheme", e.scheme_path, e.scheme_sha256),
            ("scan", e.scan_path, e.scan_sha256),
        ):
            path = Path(raw)
            if not path.is_file():
                problems.append(f"{e.key}: {what} {path} is missing")
            elif sha256_file(path) != want:
                problems.append(f"{e.key}: {what} {path} sha256 differs from the manifest")
            elif what == "reference" and not read_reference(path):
                problems.append(f"{e.key}: reference {path} has no leaves")
        scripts.append(
            RealScript(
                key=e.key,
                scan_path=Path(e.scan_path),
                scheme_path=Path(e.scheme_path),
                reference_path=Path(e.reference_path),
                reference_sha256=e.reference_sha256,
                scheme_sha256=e.scheme_sha256,
                scan_sha256=e.scan_sha256,
            )
        )
    if problems:
        raise ReferenceDrift("; ".join(problems) + ". Refusing to run.")
    return scripts


def mark_real_script(
    script: RealScript, client: GeminiClient, settings: Settings
) -> CorrectionResult:
    """Mark one real script the way production does: scan metadata, binder, correction.

    The same stages the E2E driver ran (BUILD/accuracy-runs/claude-e2e2-*/driver.py),
    on the frozen scheme, inside one `script_cost_scope`. Every failure, a scan-metadata
    one included, is raised to the caller, so the script fails closed and is recorded as
    incomplete.
    """
    from lemely.core.loose_schemas import MarkScheme
    from lemely.io.answer_extraction import GeminiAnswerExtractor
    from lemely.io.correction_ai import correct_paper
    from lemely.io.gemini import script_cost_scope
    from lemely.io.rasterise import rasterise_scan_to_pages
    from lemely.io.scan_metadata import ScanMetadataExtractor

    scheme = MarkScheme.model_validate_json(script.scheme_path.read_text(encoding="utf-8"))
    with script_cost_scope(settings, script_key=f"real:{script.key}"):
        ScanMetadataExtractor(client)(script.scan_path)
        extracted = GeminiAnswerExtractor(client)(scan_path=script.scan_path, mark_scheme=scheme)
        # The scan's pages are rasterised only when adjudication (lever c2) will use them.
        pages = (
            rasterise_scan_to_pages(script.scan_path)
            if isinstance(settings.gemini.adjudication_model, str)
            else None
        )
        return correct_paper(
            mark_scheme=scheme,
            extracted_answers=extracted,
            gemini_client=client,
            options=settings.grading.marking_options(),
            pages=pages,
        )


@dataclass(frozen=True)
class LeafOutcome:
    question_id: str
    predicted: int
    reference: int
    max_marks: int
    needs_review: bool
    confidence: float | None
    marker_source: str | None
    review_reason: str | None
    escalated: bool
    trigger: str | None
    #: The confidence that decided escalation: the escalation event's for an escalated
    #: leaf, the final mark's otherwise (the threshold fit reads it).
    pre_escalation_confidence: float | None
    #: The mark after each marking step, from the saved replies. ``predicted`` stays the
    #: final mark, which can differ from the last of these after ECF substitution or
    #: clamping. All four are None when the leaf has no first-pass reply (MCQ, dropped,
    #: blank) or is not marker-scored. Each step falls back to the one before it.
    first_pass_mark: int | None = None
    post_borderline_mark: int | None = None
    post_escalation_mark: int | None = None
    post_adjudication_mark: int | None = None

    @property
    def abs_error(self) -> int:
        return abs(self.predicted - self.reference)


@dataclass(frozen=True)
class RealScriptResult:
    key: str
    leaves: tuple[LeafOutcome, ...]
    binding_verdict: str | None
    usd: float  # 2027 USD of every call of the script
    escalation_usd: float
    adjudication_usd: float
    latency_ms: float  # wall clock of the whole script
    incomplete: str | None  # why the script is incomplete; None when complete

    @property
    def abs_error(self) -> int:
        return sum(leaf.abs_error for leaf in self.leaves)

    @property
    def escalated(self) -> int:
        return sum(1 for leaf in self.leaves if leaf.escalated)


@dataclass(frozen=True)
class MarkReply:
    case_key: str
    question_id: str
    task_tag: str
    attempt: str | None
    model: str
    mark: int
    confidence: float
    rationale: str  # AIMarkResponse.feedback, AdjudicationReply.rationale
    reply: dict[str, object]  # the parsed reply, model_dump(mode="json")
    #: The mark the model stated when the reply also carries per-point verdicts that decide
    #: the mark (lever H2b); None when the reply has no ``stated_mark``.
    stated_mark: int | None = None


class ReplyLog:
    """The correction-family replies of one real run, per script. Student data: never committed."""

    def __init__(self) -> None:
        #: The script being marked; `run_real` sets it per script.
        self.current: str | None = None
        self.rows: list[MarkReply] = []
        self._lock = threading.Lock()

    def wrap(self, client: object) -> None:
        """Record every correction-family generate_structured reply that has a question_id.

        Replaces the bound method on this one client instance. Production code is untouched,
        so the Gemini golden path stays byte-identical. A stand-in client without
        generate_structured is left as it is.
        """
        original = getattr(client, "generate_structured", None)
        if not callable(original):
            return

        def recording(**kwargs: object) -> object:
            result = original(**kwargs)
            try:
                self._record(client, kwargs, result)
            except Exception:
                _LOG.warning("reply log skipped a reply", exc_info=True)
            return result

        client.generate_structured = recording  # type: ignore[attr-defined]  # one instance

    def _record(self, client: object, kwargs: dict[str, object], result: object) -> None:
        tag, qid = kwargs.get("task_tag"), kwargs.get("question_id")
        if (
            not isinstance(tag, str)
            or tag not in CORRECTION_FAMILY_TAGS
            or not isinstance(qid, str)
            or self.current is None
        ):
            return
        rationale = getattr(result, "feedback", None)
        if rationale is None:
            rationale = getattr(result, "rationale", "")
        attempt = kwargs.get("attempt")
        model_arg = kwargs.get("model")
        active = cast("GeminiClient", client)._active_model(
            model_arg if isinstance(model_arg, str) else None, tag
        )
        stated = getattr(result, "stated_mark", None)
        row = MarkReply(
            case_key=self.current,
            question_id=qid,
            task_tag=tag,
            attempt=attempt if isinstance(attempt, str) else None,
            model=str(active),
            mark=int(getattr(result, "awarded_marks", 0)),
            confidence=float(getattr(result, "confidence", 0.0)),
            rationale=str(rationale),
            reply=cast("BaseModel", result).model_dump(mode="json"),
            stated_mark=stated
            if isinstance(stated, int) and not isinstance(stated, bool)
            else None,
        )
        with self._lock:
            self.rows.append(row)

    def for_script(self, key: str) -> list[MarkReply]:
        with self._lock:
            return [r for r in self.rows if r.case_key == key]


def write_replies(path: Path, rows: Sequence[MarkReply]) -> None:
    """``replies.jsonl``, one reply per row. Student data: stays in the gitignored BUILD tree."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(asdict(r), sort_keys=True, default=str) + "\n" for r in rows),
        encoding="utf-8",
    )


def _step_marks(
    replies: Sequence[MarkReply], qid: str, max_marks: int, *, keep_higher: bool = False
) -> tuple[int | None, int | None, int | None, int | None]:
    """A leaf's mark after the first pass, the borderline retry, escalation and adjudication."""
    mine = [r for r in replies if r.question_id == qid]

    def clamp(mark: int) -> int:
        return max(0, min(mark, max_marks))

    firsts = [r for r in mine if r.task_tag == "correction" and r.attempt in (None, "first")]
    if not firsts:
        return None, None, None, None
    first = clamp(firsts[0].mark)
    marks = [first]
    for tag in ("correction_borderline", ESCALATION_TAG, ADJUDICATION_TAG):
        later = [r for r in mine if r.task_tag == tag]
        mark = clamp(later[-1].mark) if later else marks[-1]
        if tag == "correction_borderline" and later and keep_higher:
            # H2a: the leaf holds the higher of the first and retry marks, not the retry's own.
            mark = max(mark, first)
        marks.append(mark)
    return marks[0], marks[1], marks[2], marks[3]


def _usd(records: Sequence[CallRecord], tag: str | None = None) -> float:
    return sum(
        r.usd_2027
        for r in records
        if (tag is None or r.task_tag == tag) and not math.isnan(r.usd_2027)
    )


def score_script(
    script: RealScript,
    correction: CorrectionResult | None,
    records: Sequence[CallRecord],
    *,
    latency_ms: float,
    failure: str | None,
    escalations: Sequence[Mapping[str, object]],
    cascade_enabled: bool,
    replies: Sequence[MarkReply] = (),
    keep_higher: bool = False,
) -> RealScriptResult:
    """One script's leaves against its reference; every reference leaf is scored."""
    reference = read_reference(script.reference_path)
    by_id = {q.question_id: q for q in correction.questions} if correction is not None else {}
    duplicates = (
        sorted(
            qid for qid, n in Counter(q.question_id for q in correction.questions).items() if n > 1
        )
        if correction is not None
        else []
    )
    escalated_ids = {
        r.question_id for r in records if r.task_tag == ESCALATION_TAG and r.question_id
    }
    event_confidence: dict[str, float] = {}
    for event in escalations:
        qid, conf = event.get("question_id"), event.get("confidence")
        model = str(event.get("escalation_model", ""))
        if (
            isinstance(qid, str)
            and isinstance(conf, int | float)
            and not model.endswith(_BORDERLINE_SUFFIX)
        ):
            event_confidence[qid] = float(conf)
    incomplete = failure
    if incomplete is None and duplicates:
        incomplete = f"duplicate question_id in marking output: {', '.join(duplicates)}"
    leaves: list[LeafOutcome] = []
    for qid in sorted(reference):
        leaf_ref = reference[qid]
        q = by_id.get(qid)
        if incomplete is None and correction is not None:
            if q is None:
                incomplete = f"no marking output for {qid}"
            elif q.marker_source in _LOST_SOURCES or (q.review_reason or "").startswith(_AI_FAILED):
                incomplete = f"marking failed on {qid}"
            elif q.maximum_marks != leaf_ref.max_marks:
                incomplete = (
                    f"max marks differ on {qid}: scheme {q.maximum_marks}, "
                    f"reference {leaf_ref.max_marks}"
                )
        scored = q is not None and marker_scored(q.marker_source)
        predicted = q.awarded_marks if q is not None and scored else 0
        escalated = qid in escalated_ids
        steps = (
            _step_marks(replies, qid, leaf_ref.max_marks, keep_higher=keep_higher)
            if scored
            else (None, None, None, None)
        )
        # An unscored leaf carries no confidence: a placeholder must not reach calibration.
        final_conf = q.confidence_score if q is not None and scored else None
        leaves.append(
            LeafOutcome(
                question_id=qid,
                predicted=predicted,
                reference=leaf_ref.mark,
                max_marks=leaf_ref.max_marks,
                needs_review=q.needs_teacher_review if q is not None else True,
                confidence=final_conf,
                marker_source=q.marker_source if q is not None else None,
                review_reason=q.review_reason if q is not None else None,
                escalated=escalated,
                trigger=("cascade" if cascade_enabled else "confidence") if escalated else None,
                pre_escalation_confidence=(
                    event_confidence.get(qid, final_conf) if escalated else final_conf
                ),
                first_pass_mark=steps[0],
                post_borderline_mark=steps[1],
                post_escalation_mark=steps[2],
                post_adjudication_mark=steps[3],
            )
        )
    if correction is None and incomplete is None:
        incomplete = "no marking"
    unpriced = [r.model for r in records if math.isnan(r.usd_2027)]
    if unpriced and incomplete is None:
        incomplete = f"unpriced model {unpriced[0]}"
    binding = correction.binding if correction is not None else None
    return RealScriptResult(
        key=script.key,
        leaves=tuple(leaves),
        binding_verdict=binding.verdict if binding is not None else None,
        usd=_usd(records),
        escalation_usd=_usd(records, ESCALATION_TAG),
        adjudication_usd=_usd(records, ADJUDICATION_TAG),
        latency_ms=latency_ms,
        incomplete=incomplete,
    )


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _rate(run: Sequence[RealScriptResult], hit: str) -> float:
    leaves = [leaf for script in run for leaf in script.leaves]
    if not leaves:
        return 0.0
    tests = {
        "exact": lambda leaf: leaf.abs_error == 0,
        "within1": lambda leaf: leaf.abs_error <= 1,
        "review": lambda leaf: leaf.needs_review,
        "escalated": lambda leaf: leaf.escalated,
    }
    return sum(1 for leaf in leaves if tests[hit](leaf)) / len(leaves)


def real_summary_fields(
    runs: Sequence[Sequence[RealScriptResult]], expected_keys: Sequence[str]
) -> dict[str, object]:
    """The `RunSummary` real fields of a rung's runs: means over the runs, max for the cap.

    *expected_keys* are the scripts `load_real_scripts` returned. A script a run lacks is
    reported in ``real_incomplete`` as ``(no result)``; malformed runs raise.
    """
    if not runs:
        raise ValueError("a rung needs at least one real run")
    keys = list(expected_keys)
    if not keys or len(set(keys)) != len(keys):
        raise ValueError(f"expected_keys must be non-empty and unique: {keys}")
    per_key: dict[str, list[RealScriptResult]] = {k: [] for k in keys}
    absent: list[str] = []
    for i, run in enumerate(runs, start=1):
        if not run:
            raise ValueError(f"real run {i} has no results")
        seen = [script.key for script in run]
        if len(set(seen)) != len(seen):
            raise ValueError(f"real run {i} repeats a script key: {seen}")
        stray = sorted(set(seen) - set(keys))
        if stray:
            raise ValueError(f"real run {i} has keys outside the expected set: {stray}")
        absent += [f"real-{i}:{k} (no result)" for k in keys if k not in seen]
        for script in run:
            per_key[script.key].append(script)
    by_run_abs = tuple(float(sum(s.abs_error for s in run)) for run in runs)
    script_esc_rates = [s.escalated / len(s.leaves) for run in runs for s in run if s.leaves]
    triggers = Counter(
        leaf.trigger for run in runs for s in run for leaf in s.leaves if leaf.trigger
    )
    return {
        "real_scripts": tuple(keys),
        "real_abs_error": _mean(by_run_abs),
        "real_abs_error_by_run": by_run_abs,
        "real_exact_rate": _mean([_rate(run, "exact") for run in runs]),
        "real_within1_rate": _mean([_rate(run, "within1") for run in runs]),
        "real_review_rate": _mean([_rate(run, "review") for run in runs]),
        "real_binding_passes": _mean(
            [float(sum(1 for s in run if s.binding_verdict == "pass")) for run in runs]
        ),
        "real_usd_mean": _mean([s.usd for run in runs for s in run]),
        # A script with no result in any run is None, never 0: a missing cost is not a cheap one.
        "real_usd_by_script": tuple(
            (k, _mean([s.usd for s in v]) if v else None) for k, v in per_key.items()
        ),
        "real_usd_max_by_script": tuple(
            (k, max(s.usd for s in v) if v else None) for k, v in per_key.items()
        ),
        "real_latency_by_script": tuple(
            (k, _mean([s.latency_ms for s in v]) if v else None) for k, v in per_key.items()
        ),
        "real_escalation_rate": _mean([_rate(run, "escalated") for run in runs]),
        "real_escalation_rate_max_script": max(script_esc_rates, default=0.0),
        "real_escalation_usd_by_script": tuple(
            (k, _mean([s.escalation_usd for s in v]) if v else None) for k, v in per_key.items()
        ),
        "real_escalation_triggers": tuple(sorted(triggers.items())),
        "real_incomplete": tuple(
            f"real-{i}:{s.key} ({s.incomplete})"
            for i, run in enumerate(runs, start=1)
            for s in run
            if s.incomplete
        )
        + tuple(absent),
    }


def write_real_results(path: Path, results: Sequence[RealScriptResult]) -> None:
    """``real_results.json``: per-leaf marks. Student data: stays in the gitignored BUILD tree."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([asdict(r) for r in results], indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def read_real_results(path: Path) -> list[RealScriptResult]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    return [
        RealScriptResult(
            **{k: v for k, v in row.items() if k != "leaves"},
            leaves=tuple(LeafOutcome(**leaf) for leaf in row["leaves"]),
        )
        for row in rows
    ]
