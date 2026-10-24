"""Sub-project C real split: frozen real scripts, marked on the production path, scored per leaf.

A real script is loaded only from the frozen reference manifest, and only when every
digest still matches (`load_real_scripts`), so a changed reference stops a run before
any spend. Scoring never narrows the denominator: a leaf the run dropped, lost or
failed to mark counts as mark 0 against its reference.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING

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

    from lemely.accuracy.reference import ManifestEntry
    from lemely.core.schemas import CorrectionResult
    from lemely.io.gemini import CallRecord, GeminiClient
    from lemely.runtime.config import Settings

DEFAULT_MANIFEST = REFERENCE_ROOT / MANIFEST_FILE
ESCALATION_TAG = "escalation"
ADJUDICATION_TAG = "adjudication"
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
    on the frozen scheme, inside one `script_cost_scope`. A failure is raised to the
    caller, which records the script as incomplete.
    """
    from lemely.core.loose_schemas import MarkScheme
    from lemely.io.answer_extraction import GeminiAnswerExtractor
    from lemely.io.correction_ai import correct_paper
    from lemely.io.gemini import script_cost_scope
    from lemely.io.scan_metadata import ScanMetadataExtractor

    scheme = MarkScheme.model_validate_json(script.scheme_path.read_text(encoding="utf-8"))
    with script_cost_scope(settings, script_key=f"real:{script.key}"):
        ScanMetadataExtractor(client)(script.scan_path)
        extracted = GeminiAnswerExtractor(client)(scan_path=script.scan_path, mark_scheme=scheme)
        return correct_paper(
            mark_scheme=scheme,
            extracted_answers=extracted,
            gemini_client=client,
            options=settings.grading.marking_options(),
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
) -> RealScriptResult:
    """One script's leaves against its reference; every reference leaf is scored."""
    reference = read_reference(script.reference_path)
    by_id = {q.question_id: q for q in correction.questions} if correction is not None else {}
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
    leaves: list[LeafOutcome] = []
    for qid in sorted(reference):
        leaf_ref = reference[qid]
        q = by_id.get(qid)
        if incomplete is None and correction is not None:
            if q is None:
                incomplete = f"no marking output for {qid}"
            elif q.marker_source in _LOST_SOURCES or (q.review_reason or "").startswith(_AI_FAILED):
                incomplete = f"marking failed on {qid}"
        predicted = q.awarded_marks if q is not None and marker_scored(q.marker_source) else 0
        escalated = qid in escalated_ids
        final_conf = q.confidence_score if q is not None else None
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


def real_summary_fields(runs: Sequence[Sequence[RealScriptResult]]) -> dict[str, object]:
    """The `RunSummary` real fields of a rung's runs: means over the runs, max for the cap."""
    if not runs:
        raise ValueError("a rung needs at least one real run")
    keys = [script.key for script in runs[0]]
    per_key: dict[str, list[RealScriptResult]] = {k: [] for k in keys}
    for run in runs:
        for script in run:
            per_key.setdefault(script.key, []).append(script)
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
        "real_usd_by_script": tuple((k, _mean([s.usd for s in v])) for k, v in per_key.items()),
        "real_usd_max_by_script": tuple(
            (k, max((s.usd for s in v), default=0.0)) for k, v in per_key.items()
        ),
        "real_latency_by_script": tuple(
            (k, _mean([s.latency_ms for s in v])) for k, v in per_key.items()
        ),
        "real_escalation_rate": _mean([_rate(run, "escalated") for run in runs]),
        "real_escalation_rate_max_script": max(script_esc_rates, default=0.0),
        "real_escalation_usd_by_script": tuple(
            (k, _mean([s.escalation_usd for s in v])) for k, v in per_key.items()
        ),
        "real_escalation_triggers": tuple(sorted(triggers.items())),
        "real_incomplete": tuple(
            f"real-{i}:{s.key} ({s.incomplete})"
            for i, run in enumerate(runs, start=1)
            for s in run
            if s.incomplete
        ),
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
