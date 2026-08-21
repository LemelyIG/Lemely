"""Golden-dataset accuracy measurement harness for the Lemely pipeline."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from pathlib import Path

import structlog
from pydantic import BaseModel, Field

from lemely.core.loose_schemas import MarkScheme
from lemely.eval.manifest import RunManifest, Split
from lemely.eval.records import Arm, EvalRecord
from lemely.eval.test_touch import DEFAULT_LEDGER_PATH, authorize_test_split_join
from lemely.io.gemini import _MAX_OUTPUT_TOKENS

log = structlog.get_logger()


class GoldenAnswer(BaseModel):
    """Ground truth for a single leaf question."""

    student_answer: str
    awarded_marks: int = Field(..., ge=0)
    notes: str | None = None


#: Golden-fixture directory-name suffixes denoting which DA6 variant a case
#: is (spec §3.3's ``fixture_variant``, BUILD/DECISIONS.md DA6).
_FIXTURE_VARIANT_SUFFIXES = ("_correct", "_partial", "_wrong")


def _split_fixture_variant(dir_name: str) -> tuple[str, str | None]:
    """Split a golden-case directory name into ``(paper_id, fixture_variant)``.

    Strips a trailing ``_correct``/``_partial``/``_wrong`` suffix, if present,
    from *dir_name* — this is what makes three sibling directories (e.g.
    ``0625_s20_qp_31_theory_correct/_partial/_wrong``) collapse to the same
    ``paper_id`` for distinct-leaf purposes (DA6), while ``fixture_variant``
    keeps the specific variant for record-keeping. Directories without one of
    these suffixes (e.g. the MCQ-only fixture) are returned unchanged with
    ``fixture_variant=None``.
    """
    for suffix in _FIXTURE_VARIANT_SUFFIXES:
        if dir_name.endswith(suffix):
            return dir_name[: -len(suffix)], suffix[1:]
    return dir_name, None


@dataclass
class GoldenCase:
    """One paper-worth of ground truth data."""

    paper_id: str
    mark_scheme: MarkScheme
    ground_truth: dict[str, GoldenAnswer]  # question_id -> GoldenAnswer
    scan_path: Path | None = None  # present only when extraction test is possible
    fixture_variant: str | None = None  # "correct" | "partial" | "wrong" | None
    #: True when this fixture is a deliberate excerpt — it declares a full
    #: paper's ``maximum_mark`` while carrying only a subset of leaves (spec
    #: §2.3(d); M0.8/#32). Sourced from an explicit ``case.json`` sidecar
    #: marker (see `load_golden_cases`), never derived from
    #: ``maximum_mark`` vs. leaf-sum, and never stored inside
    #: ``mark_scheme.json``'s ``MarkSchemeMetadata`` — that model is the
    #: production Gemini-parser schema and would silently drop an unknown key.
    is_excerpt: bool = False


def load_golden_cases(golden_dir: Path) -> list[GoldenCase]:
    """Load all golden cases from direct subdirectories of *golden_dir*.

    Each subdirectory must contain:
      mark_scheme.json  — already-parsed JSON mark scheme
      answers.json      — ground truth per leaf question
      scan.pdf          — optional; enables extraction tests

    A directory name's trailing ``_correct``/``_partial``/``_wrong`` suffix
    (if any) is split off: it becomes ``fixture_variant`` and is stripped
    from ``paper_id``, so the three DA6 variants of the same underlying paper
    share one ``paper_id`` (spec §3.3; BUILD/DECISIONS.md DA6).

    An optional ``case.json`` sidecar (``{"is_excerpt": true}``) marks a
    fixture as a deliberate excerpt (spec §2.3(d); M0.8/#32). It is a plain
    JSON file read directly here, never merged into ``mark_scheme.json`` —
    that file round-trips through ``MarkScheme.model_validate_json``, whose
    ``MarkSchemeMetadata`` is the production Gemini-parser schema and would
    silently drop an unrecognised key. A missing sidecar (or a missing
    ``is_excerpt`` key within it) defaults to ``False``.
    """
    cases: list[GoldenCase] = []
    for case_dir in sorted(golden_dir.iterdir()):
        if not case_dir.is_dir():
            continue
        ms_path = case_dir / "mark_scheme.json"
        ans_path = case_dir / "answers.json"
        if not ms_path.exists() or not ans_path.exists():
            continue

        try:
            mark_scheme = MarkScheme.model_validate_json(ms_path.read_text(encoding="utf-8"))
            raw: dict[str, object] = json.loads(ans_path.read_text(encoding="utf-8"))
            ground_truth = {qid: GoldenAnswer.model_validate(v) for qid, v in raw.items()}
        except Exception as exc:
            log.warning("golden_case_load_error", case_dir=str(case_dir), error=str(exc))
            continue
        scan_path = case_dir / "scan.pdf"
        paper_id, fixture_variant = _split_fixture_variant(case_dir.name)
        is_excerpt = False
        case_marker_path = case_dir / "case.json"
        if case_marker_path.exists():
            try:
                marker: dict[str, object] = json.loads(case_marker_path.read_text(encoding="utf-8"))
                raw_flag = marker.get("is_excerpt", False)
                if not isinstance(raw_flag, bool):
                    raise TypeError(
                        f"is_excerpt must be a JSON boolean, got {raw_flag!r} "
                        f"({type(raw_flag).__name__})"
                    )
                is_excerpt = raw_flag
            except Exception as exc:
                log.warning("golden_case_marker_load_error", case_dir=str(case_dir), error=str(exc))
        cases.append(
            GoldenCase(
                paper_id=paper_id,
                mark_scheme=mark_scheme,
                ground_truth=ground_truth,
                scan_path=scan_path if scan_path.exists() else None,
                fixture_variant=fixture_variant,
                is_excerpt=is_excerpt,
            )
        )
    return cases


# ---------------------------------------------------------------------------
# Per-question result and aggregate metric types
# ---------------------------------------------------------------------------


@dataclass
class QuestionResult:
    """Outcome for a single question in an accuracy measurement run."""

    question_id: str
    question_type: str  # "mcq" | "theory"
    predicted_marks: int
    truth_marks: int
    confidence_score: float
    needs_teacher_review: bool

    @property
    def is_correct(self) -> bool:
        return self.predicted_marks == self.truth_marks

    @property
    def is_confident(self) -> bool:
        """True when the system did NOT flag this question for teacher review."""
        return not self.needs_teacher_review


@dataclass
class CalibrationBucket:
    """One confidence bucket in the calibration curve."""

    label: str
    lower: float  # inclusive lower bound (0.00 for the bottom bucket)
    predictions: int = 0
    correct: int = 0

    @property
    def actual_accuracy(self) -> float | None:
        return self.correct / self.predictions if self.predictions > 0 else None

    @property
    def stated_midpoint(self) -> float:
        _upper = {0.90: 1.00, 0.80: 0.90, 0.70: 0.80, 0.60: 0.70, 0.00: 0.60}
        return (self.lower + _upper.get(self.lower, self.lower + 0.10)) / 2

    @property
    def calibration_gap(self) -> float | None:
        """actual_accuracy - stated_midpoint; negative = overconfident."""
        if self.actual_accuracy is None:
            return None
        return self.actual_accuracy - self.stated_midpoint


@dataclass
class AccuracyMetrics:
    mark_accuracy: float
    mark_accuracy_theory: float
    id_match_rate: float | None  # None when no extraction runs were performed
    flag_precision_high: float
    flag_recall: float


@dataclass
class AccuracyResult:
    metrics: AccuracyMetrics
    calibration: list[CalibrationBucket]
    question_results: list[QuestionResult]
    prompt_versions: dict[str, str]  # {"extraction": "5", "correction": "4", "mark_scheme": "3"}
    manifest: RunManifest  # spec §3.3: the run this result's EvalRecords join to


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _make_calibration_buckets() -> list[CalibrationBucket]:
    """Return buckets in descending order of lower bound (highest confidence first)."""
    return [
        CalibrationBucket("0.90-1.00", 0.90),
        CalibrationBucket("0.80-0.90", 0.80),
        CalibrationBucket("0.70-0.80", 0.70),
        CalibrationBucket("0.60-0.70", 0.60),
        CalibrationBucket("< 0.60", 0.00),
    ]


def _assign_to_bucket(buckets: list[CalibrationBucket], score: float, correct: bool) -> None:
    """Assign *score* to the first bucket where score >= bucket.lower."""
    for bucket in buckets:
        if score >= bucket.lower:
            bucket.predictions += 1
            if correct:
                bucket.correct += 1
            return


def _compute_metrics(
    results: list[QuestionResult], id_match_rate: float | None = None
) -> AccuracyMetrics:
    total = len(results)
    if total == 0:
        return AccuracyMetrics(0.0, 0.0, id_match_rate, 0.0, 1.0)

    theory = [r for r in results if r.question_type == "theory"]

    mark_accuracy = sum(1 for r in results if r.is_correct) / total
    mark_accuracy_theory = sum(1 for r in theory if r.is_correct) / len(theory) if theory else 0.0

    confident = [r for r in results if r.is_confident]
    flag_precision_high = (
        sum(1 for r in confident if r.is_correct) / len(confident) if confident else 0.0
    )

    wrong = [r for r in results if not r.is_correct]
    flag_recall = sum(1 for r in wrong if r.needs_teacher_review) / len(wrong) if wrong else 1.0

    return AccuracyMetrics(
        mark_accuracy=mark_accuracy,
        mark_accuracy_theory=mark_accuracy_theory,
        id_match_rate=id_match_rate,
        flag_precision_high=flag_precision_high,
        flag_recall=flag_recall,
    )


def question_result_to_eval_record(
    result: QuestionResult,
    *,
    run_id: str,
    paper_id: str,
    arm: Arm,
    fixture_variant: str | None = None,
) -> EvalRecord:
    """Adapt one legacy :class:`QuestionResult` into an :class:`EvalRecord` (M0.1, spec §3.3).

    ``arm`` follows the terminology table (spec §1): ``"extract+mark"`` when
    real vision extraction ran (``GoldenCase.scan_path`` set), ``"oracle+mark"``
    when ground-truth answer text was injected directly (the harness's
    correction-only bypass).

    ``parse_path`` is a known gap: spec §1 defines it as the *mark scheme's*
    parsing path (``det`` = deterministic pdfplumber parser, ``gemini`` = AI
    fallback), a per-paper property `load_golden_cases` does not observe (it
    deserializes an already-parsed `mark_scheme.json` directly). Lacking that
    signal, this adapter reuses the same two-value type for the closest
    per-question signal the harness *does* have — ``result.question_type``,
    i.e. which marker handled this question (``"mcq"`` → deterministic →
    ``"det"``; ``"theory"`` → Gemini → ``"gemini"``) — so `mark_accuracy_theory`
    is derivable from `list[EvalRecord]` alone. This is documented here rather
    than invented silently; wiring the real per-paper parse path through
    `GoldenCase` is out of scope for M0.1 (candidate for M0.2/M0.8).

    ``id_match`` is always ``"exact"`` here because `measure_accuracy` already
    drops any question the extractor did not return an answer for before a
    `QuestionResult` is built (see the ``continue`` in the loop below) — there
    is no "fuzzy" or genuinely "unmatched" case reachable from a
    `QuestionResult`. `extraction_conf` is `None`: extraction-side confidence
    is not threaded into `QuestionResult` today.
    """
    if result.predicted_marks == result.truth_marks:
        outcome: Literal["correct", "over", "under"] = "correct"
    elif result.predicted_marks > result.truth_marks:
        outcome = "over"
    else:
        outcome = "under"

    parse_path: Literal["det", "gemini"] = "det" if result.question_type == "mcq" else "gemini"

    return EvalRecord(
        run_id=run_id,
        arm=arm,
        paper_id=paper_id,
        fixture_variant=fixture_variant,
        question_id=result.question_id,
        mark_point_id=None,
        parse_path=parse_path,
        predicted_marks=result.predicted_marks,
        truth_marks=result.truth_marks,
        outcome=outcome,
        extraction_conf=None,
        marker_conf=result.confidence_score,
        id_match="exact",
        triggers=["needs_teacher_review"] if result.needs_teacher_review else [],
    )


def _metrics_from_eval_records(
    records: list[EvalRecord], id_match_rate: float | None = None
) -> AccuracyMetrics:
    """Derive :class:`AccuracyMetrics` from ``list[EvalRecord]`` (spec §4 M0.1).

    Mirrors :func:`_compute_metrics` exactly, reading the same information
    back out of the record fields instead of the legacy `QuestionResult`
    attributes — `outcome == "correct"` for `is_correct`, `triggers` non-empty
    for `needs_teacher_review`, `parse_path == "gemini"` for the theory-only
    subset (see :func:`question_result_to_eval_record`'s docstring for why).
    """
    qlevel = [r for r in records if r.mark_point_id is None]
    total = len(qlevel)
    if total == 0:
        return AccuracyMetrics(0.0, 0.0, id_match_rate, 0.0, 1.0)

    def _is_correct(r: EvalRecord) -> bool:
        return r.outcome == "correct"

    def _needs_review(r: EvalRecord) -> bool:
        return bool(r.triggers)

    theory = [r for r in qlevel if r.parse_path == "gemini"]

    mark_accuracy = sum(1 for r in qlevel if _is_correct(r)) / total
    mark_accuracy_theory = sum(1 for r in theory if _is_correct(r)) / len(theory) if theory else 0.0

    confident = [r for r in qlevel if not _needs_review(r)]
    flag_precision_high = (
        sum(1 for r in confident if _is_correct(r)) / len(confident) if confident else 0.0
    )

    wrong = [r for r in qlevel if not _is_correct(r)]
    flag_recall = sum(1 for r in wrong if _needs_review(r)) / len(wrong) if wrong else 1.0

    return AccuracyMetrics(
        mark_accuracy=mark_accuracy,
        mark_accuracy_theory=mark_accuracy_theory,
        id_match_rate=id_match_rate,
        flag_precision_high=flag_precision_high,
        flag_recall=flag_recall,
    )


def _build_calibration(results: list[QuestionResult]) -> list[CalibrationBucket]:
    """Build calibration buckets from theory-question results only (AI-marked)."""
    buckets = _make_calibration_buckets()
    for r in results:
        if r.question_type == "theory":
            _assign_to_bucket(buckets, r.confidence_score, r.is_correct)
    return buckets


# ---------------------------------------------------------------------------
# Public measurement runner
# ---------------------------------------------------------------------------


def _current_git_sha() -> str:
    """Short git SHA of the working tree's HEAD, or ``"unknown"`` outside a repo."""
    import subprocess

    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


def _corpus_digest(cases: list[GoldenCase]) -> str:
    """Digest of the exact golden corpus fed into this run.

    Derived from what was actually loaded — each case's ``paper_id``,
    ``fixture_variant``, and its ground-truth leaves — not a placeholder: two
    runs over the same corpus reproduce the same digest, and a corpus change
    (a fixture added/edited/removed) changes it.
    """
    h = hashlib.sha256()
    for case in sorted(cases, key=lambda c: (c.paper_id, c.fixture_variant or "")):
        h.update(case.paper_id.encode())
        h.update(b"|")
        h.update((case.fixture_variant or "").encode())
        for qid in sorted(case.ground_truth):
            gt = case.ground_truth[qid]
            h.update(f"|{qid}:{gt.awarded_marks}:{gt.student_answer}".encode())
    return h.hexdigest()[:16]


def _build_run_manifest(
    run_id: str,
    cases: list[GoldenCase],
    settings: object,
    prompt_versions: dict[str, str],
    gemini_client: object = None,
    split: Split = "dev",
) -> RunManifest:
    """Construct the :class:`RunManifest` this run's `EvalRecord`s join to (spec §3.3).

    Every field is sourced honestly from what the harness actually knows:
    ``models_by_task``/``params_fingerprint`` come from ``settings.gemini``
    when a real :class:`~lemely.runtime.config.Settings` is supplied (empty
    dict / digest-of-nothing when it is not, e.g. in unit tests that pass
    ``settings=None``); ``cache_mode`` is read off *gemini_client*'s own
    ``default_cache_mode`` attribute — the client instance is the single
    source of truth for its cache behaviour (falls back to ``"read_write"``
    when no client, e.g. the correction-only bypass tests, was supplied);
    ``split`` is whatever the caller authorised — defaulting to ``"dev"``
    because the golden corpus *is* the golden dev split per spec §5's M1
    acceptance ("The population is the golden dev split") when no override is
    requested. ``corpus_digest`` is a real hash of the loaded corpus, not an
    invented value.

    This function does **not** gate the split itself. It is private and runs
    in ``measure_accuracy``'s final ``return``, long after the corpus has been
    read and the budget spent, so a gate here would refuse too late to prevent
    the very access it guards (spec §4 M0.7a). ``measure_accuracy`` authorises
    up front instead, and this function trusts the already-authorised value —
    which also keeps the ledger at exactly one entry per run rather than two.
    """
    gemini = getattr(settings, "gemini", None)
    if gemini is not None:
        models_by_task = {
            "mark_scheme": gemini.model_for("mark_scheme"),
            "extraction": gemini.model_for("extraction"),
            "correction": gemini.model_for("correction"),
        }
        # The models MUST be in the hash. Without them two runs on different
        # models record the same params_fingerprint, and M0.3's A/B reads that
        # as "same parameters" — a false zero delta produced by the instrument
        # rather than by the models (spec §3.3 names all seven components).
        # ``_MAX_OUTPUT_TOKENS`` is included for the same reason
        # ``GeminiClient._params_fingerprint`` includes it: it can change the
        # output. The per-call response-schema hash is deliberately absent —
        # this manifest is run-level and a run issues calls under several
        # schemas, so there is no single schema to name here. That is a
        # narrower claim than the per-call fingerprint, not a weaker version
        # of it.
        fingerprint_raw = (
            f"{sorted(models_by_task.items())}"
            f"|{gemini.temperature}|{gemini.top_p}|{gemini.seed}"
            f"|{sorted(gemini.thinking_budget_for.items())}"
            f"|{_MAX_OUTPUT_TOKENS}"
        )
    else:
        models_by_task = {}
        fingerprint_raw = ""

    return RunManifest(
        run_id=run_id,
        git_sha=_current_git_sha(),
        timestamp=datetime.now(UTC),
        prompt_versions=prompt_versions,
        params_fingerprint=hashlib.sha256(fingerprint_raw.encode()).hexdigest()[:12],
        models_by_task=models_by_task,
        cache_mode=getattr(gemini_client, "default_cache_mode", "read_write"),
        split=split,
        corpus_digest=_corpus_digest(cases),
    )


def measure_accuracy(
    cases: list[GoldenCase],
    gemini_client: object,  # GeminiClient | None
    settings: object,  # Settings
    *,
    run_id: str | None = None,
    split: Split = "dev",
    test_split_token: str | None = None,
    ledger_path: Path = DEFAULT_LEDGER_PATH,
) -> AccuracyResult:
    """Run correction over all golden cases; compute metrics.

    Cases with ``scan_path`` set run the real end-to-end pipeline: Gemini vision
    extraction (:func:`lemely.web.services.grading.extract_answers`) followed by
    correction — this is the only path that exercises answer transcription and
    feeds ``id_match_rate``. Cases without ``scan_path`` keep the correction-only
    bypass: ground-truth answer text is wrapped in a synthetic, full-confidence
    ``ExtractedAnswers`` and fed straight into correction, useful for testing
    marking logic without needing a rendered scan.

    ``run_id`` (spec §3.3) is the join key between the `EvalRecord`s this run
    produces and its `RunManifest`. It defaults to a fresh id per call (never
    a constant) so repeat runs of the same arm are distinguishable — required
    for M0.3's repeat-run churn measurement.

    ``split`` defaults to ``"dev"``; requesting ``"test"`` requires
    ``test_split_token`` to match the ``LEMELY_TEST_SPLIT_TOKEN`` environment
    variable via :func:`lemely.eval.test_touch.authorize_test_split_join`
    (spec §4 M0.7a), raising
    :class:`~lemely.eval.test_touch.TestSplitAccessError` otherwise.

    That gate fires **here, before any case is read or any Gemini call is
    made** — not down in :func:`_build_run_manifest`, which runs only in the
    final ``return``. Authorising at the end would let an unauthorised
    ``split="test"`` run read the whole test split and spend real budget
    before being refused, which is precisely what M0.7a exists to prevent.
    ``_build_run_manifest`` therefore trusts the ``split`` it is handed and
    does not re-gate, so exactly one ledger entry is written per run.
    """
    if run_id is None:
        run_id = f"run-{uuid.uuid4().hex[:12]}"

    authorize_test_split_join(
        split,
        token=test_split_token,
        run_id=run_id,
        caller="lemely.accuracy.harness.measure_accuracy",
        ledger_path=ledger_path,
    )
    from lemely.core.schemas import ExtractedAnswer, ExtractedAnswers
    from lemely.io.correction_ai import correct_paper
    from lemely.io.prompts.answer_extraction import VERSION as EXT_VERSION
    from lemely.io.prompts.correction_ai import VERSION as COR_VERSION
    from lemely.io.prompts.mark_scheme_parsing import VERSION as MS_VERSION
    from lemely.web.services.grading import extract_answers

    all_results: list[QuestionResult] = []
    eval_records: list[EvalRecord] = []
    ran_extraction = False
    matched_extraction_ids = 0
    total_extraction_questions = 0

    for case in cases:
        # Terminology (spec §1): real vision extraction is "extract+mark"; the
        # correction-only bypass injects ground-truth text and marks only,
        # i.e. "oracle+mark".
        arm: Literal["extract+mark", "oracle+mark"] = (
            "extract+mark" if case.scan_path is not None else "oracle+mark"
        )
        extracted_ids: set[str]
        if case.scan_path is not None:
            ran_extraction = True
            extracted = extract_answers(
                case.scan_path,
                case.mark_scheme,
                gemini_client=gemini_client,  # type: ignore[arg-type]
            )
            extracted_ids = {a.question_id for a in extracted.answers}
            total_extraction_questions += len(case.ground_truth)
            matched_extraction_ids += sum(1 for qid in case.ground_truth if qid in extracted_ids)
        else:
            extracted = ExtractedAnswers(
                paper_id=case.paper_id,
                source_scan="golden",
                answers=[
                    ExtractedAnswer(
                        question_id=qid,
                        answer=gt.student_answer,
                        confidence=1.0,
                    )
                    for qid, gt in case.ground_truth.items()
                ],
            )
            extracted_ids = set(case.ground_truth)

        correction = correct_paper(
            case.mark_scheme,
            extracted,
            gemini_client=gemini_client,  # type: ignore[arg-type]
        )

        for cq in correction.questions:
            # A question the extractor never returned an answer for has nothing
            # to compare against; it only shows up via id_match_rate below.
            if cq.question_id not in extracted_ids:
                continue
            gt = case.ground_truth.get(cq.question_id)
            if gt is None:
                continue
            q_type = "mcq" if cq.marker_source == "deterministic" else "theory"
            question_result = QuestionResult(
                question_id=cq.question_id,
                question_type=q_type,
                predicted_marks=cq.awarded_marks,
                truth_marks=gt.awarded_marks,
                confidence_score=cq.confidence_score,
                needs_teacher_review=cq.needs_teacher_review,
            )
            all_results.append(question_result)
            eval_records.append(
                question_result_to_eval_record(
                    question_result,
                    run_id=run_id,
                    paper_id=case.paper_id,
                    arm=arm,
                    fixture_variant=case.fixture_variant,
                )
            )

    id_match_rate = (
        matched_extraction_ids / total_extraction_questions
        if ran_extraction and total_extraction_questions > 0
        else None
    )

    prompt_versions = {
        "extraction": EXT_VERSION,
        "correction": COR_VERSION,
        "mark_scheme": MS_VERSION,
    }

    return AccuracyResult(
        metrics=_metrics_from_eval_records(eval_records, id_match_rate=id_match_rate),
        calibration=_build_calibration(all_results),
        question_results=all_results,
        prompt_versions=prompt_versions,
        manifest=_build_run_manifest(
            run_id,
            cases,
            settings,
            prompt_versions,
            gemini_client=gemini_client,
            split=split,
        ),
    )


# ---------------------------------------------------------------------------
# Reporting + persistence
# ---------------------------------------------------------------------------


def format_report(result: AccuracyResult, targets: object) -> str:
    """Return a printable ASCII report with metric table and calibration curve."""
    m = result.metrics

    def _pct(v: float | None) -> str:
        return f"{v * 100:.1f}%" if v is not None else "N/A"

    def _target(v: float) -> str:
        return f">{v * 100:.0f}%"

    rows = [
        (
            "Correction",
            "mark_accuracy",
            m.mark_accuracy,
            targets.mark_accuracy_target,  # type: ignore[attr-defined]
            "% of questions where awarded_marks == ground truth",
        ),
        (
            "Correction",
            "mark_accuracy (theory)",
            m.mark_accuracy_theory,
            targets.mark_accuracy_target,  # type: ignore[attr-defined]
            "Same, theory-only (MCQ excluded)",
        ),
        (
            "Extraction",
            "id_match_rate",
            m.id_match_rate,
            targets.id_match_rate_target,  # type: ignore[attr-defined]
            "% of leaf questions found in extracted output",
        ),
        (
            "Confidence",
            "flag_precision (HIGH)",
            m.flag_precision_high,
            targets.flag_precision_target,  # type: ignore[attr-defined]
            "Of HIGH-confidence decisions, % actually correct",
        ),
        (
            "Confidence",
            "flag_recall",
            m.flag_recall,
            targets.flag_recall_target,  # type: ignore[attr-defined]
            "Of wrong marks, % flagged for review",
        ),
    ]

    sep = "─" * 100
    header = f"{'Stage':<12} {'Metric':<26} {'Score':>8} {'Target':>8}   {'Description'}"
    lines = [sep, header, sep]
    for stage, metric, score, target, desc in rows:
        score_s = _pct(score)
        ok = "?" if score is None else ("✓" if score >= target else "✗")
        lines.append(f"{stage:<12} {metric:<26} {score_s:>8} {_target(target):>8} {ok}  {desc}")
    lines.append(sep)

    lines.append("")
    lines.append(
        f"{'Confidence bucket':<20} {'Predictions':>12} {'Accuracy':>10} {'Gap (actual-stated)':>20}"  # noqa: E501
    )
    lines.append("─" * 66)
    for b in result.calibration:
        acc = _pct(b.actual_accuracy)
        gap = f"{b.calibration_gap:+.3f}" if b.calibration_gap is not None else "N/A"
        lines.append(f"{b.label:<20} {b.predictions:>12} {acc:>10} {gap:>20}")

    lines.append("")
    lines.append(
        f"Prompt versions — extraction: {result.prompt_versions.get('extraction', '?')}, "
        f"correction: {result.prompt_versions.get('correction', '?')}, "
        f"mark_scheme: {result.prompt_versions.get('mark_scheme', '?')}"
    )
    return "\n".join(lines)


def save_result(result: AccuracyResult, output_dir: Path) -> Path:
    """Write result JSON to output_dir/YYYY-MM-DD-<git-sha>.json; return the path."""
    import json as _json
    import subprocess
    from datetime import date

    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        sha = "unknown"

    filename = f"{date.today()}-{sha}.json"
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / filename
    data = {
        "metrics": {
            "mark_accuracy": result.metrics.mark_accuracy,
            "mark_accuracy_theory": result.metrics.mark_accuracy_theory,
            "id_match_rate": result.metrics.id_match_rate,
            "flag_precision_high": result.metrics.flag_precision_high,
            "flag_recall": result.metrics.flag_recall,
        },
        "calibration": [
            {
                "label": b.label,
                "lower": b.lower,
                "predictions": b.predictions,
                "correct": b.correct,
                "actual_accuracy": b.actual_accuracy,
                "calibration_gap": b.calibration_gap,
            }
            for b in result.calibration
        ],
        "prompt_versions": result.prompt_versions,
        "question_results": [
            {
                "question_id": r.question_id,
                "question_type": r.question_type,
                "predicted_marks": r.predicted_marks,
                "truth_marks": r.truth_marks,
                "confidence_score": r.confidence_score,
                "needs_teacher_review": r.needs_teacher_review,
                "is_correct": r.is_correct,
            }
            for r in result.question_results
        ],
    }
    out_path.write_text(_json.dumps(data, indent=2), encoding="utf-8")
    return out_path
