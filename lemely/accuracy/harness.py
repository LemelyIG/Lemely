"""Golden-dataset accuracy measurement harness for the Lemely pipeline."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import structlog
from pydantic import BaseModel, Field

from lemely.core.loose_schemas import MarkScheme

log = structlog.get_logger()


class GoldenAnswer(BaseModel):
    """Ground truth for a single leaf question."""

    student_answer: str
    awarded_marks: int = Field(..., ge=0)
    notes: str | None = None


@dataclass
class GoldenCase:
    """One paper-worth of ground truth data."""

    paper_id: str
    mark_scheme: MarkScheme
    ground_truth: dict[str, GoldenAnswer]   # question_id -> GoldenAnswer
    scan_path: Path | None = None           # present only when extraction test is possible


def load_golden_cases(golden_dir: Path) -> list[GoldenCase]:
    """Load all golden cases from direct subdirectories of *golden_dir*.

    Each subdirectory must contain:
      mark_scheme.json  — already-parsed JSON mark scheme
      answers.json      — ground truth per leaf question
      scan.pdf          — optional; enables extraction tests
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
        cases.append(GoldenCase(
            paper_id=case_dir.name,
            mark_scheme=mark_scheme,
            ground_truth=ground_truth,
            scan_path=scan_path if scan_path.exists() else None,
        ))
    return cases


# ---------------------------------------------------------------------------
# Per-question result and aggregate metric types
# ---------------------------------------------------------------------------

@dataclass
class QuestionResult:
    """Outcome for a single question in an accuracy measurement run."""

    question_id: str
    question_type: str          # "mcq" | "theory"
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
    lower: float    # inclusive lower bound (0.00 for the bottom bucket)
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
        """actual_accuracy − stated_midpoint; negative = overconfident."""
        if self.actual_accuracy is None:
            return None
        return self.actual_accuracy - self.stated_midpoint


@dataclass
class AccuracyMetrics:
    mark_accuracy: float
    mark_accuracy_theory: float
    id_match_rate: float | None     # None when no extraction runs were performed
    flag_precision_high: float
    flag_recall: float


@dataclass
class AccuracyResult:
    metrics: AccuracyMetrics
    calibration: list[CalibrationBucket]
    question_results: list[QuestionResult]
    prompt_versions: dict[str, str]     # {"extraction": "5", "correction": "4", "mark_scheme": "3"}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _make_calibration_buckets() -> list[CalibrationBucket]:
    """Return buckets in descending order of lower bound (highest confidence first)."""
    return [
        CalibrationBucket("0.90–1.00", 0.90),
        CalibrationBucket("0.80–0.90", 0.80),
        CalibrationBucket("0.70–0.80", 0.70),
        CalibrationBucket("0.60–0.70", 0.60),
        CalibrationBucket("< 0.60",    0.00),
    ]


def _assign_to_bucket(buckets: list[CalibrationBucket], score: float, correct: bool) -> None:
    """Assign *score* to the first bucket where score >= bucket.lower."""
    for bucket in buckets:
        if score >= bucket.lower:
            bucket.predictions += 1
            if correct:
                bucket.correct += 1
            return


def _compute_metrics(results: list[QuestionResult]) -> AccuracyMetrics:
    total = len(results)
    if total == 0:
        return AccuracyMetrics(0.0, 0.0, None, 0.0, 1.0)

    theory = [r for r in results if r.question_type == "theory"]

    mark_accuracy = sum(1 for r in results if r.is_correct) / total
    mark_accuracy_theory = (
        sum(1 for r in theory if r.is_correct) / len(theory)
        if theory else 0.0
    )

    confident = [r for r in results if r.is_confident]
    flag_precision_high = (
        sum(1 for r in confident if r.is_correct) / len(confident)
        if confident else 0.0
    )

    wrong = [r for r in results if not r.is_correct]
    flag_recall = (
        sum(1 for r in wrong if r.needs_teacher_review) / len(wrong)
        if wrong else 1.0
    )

    return AccuracyMetrics(
        mark_accuracy=mark_accuracy,
        mark_accuracy_theory=mark_accuracy_theory,
        id_match_rate=None,
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

def measure_accuracy(
    cases: list[GoldenCase],
    gemini_client: object,   # GeminiClient | None
    settings: object,        # Settings
) -> AccuracyResult:
    """Run correction over all golden cases using ground-truth answers; compute metrics."""
    from lemely.core.schemas import ExtractedAnswer, ExtractedAnswers
    from lemely.io.correction_ai import correct_paper
    from lemely.io.prompts.answer_extraction import VERSION as EXT_VERSION
    from lemely.io.prompts.correction_ai import VERSION as COR_VERSION
    from lemely.io.prompts.mark_scheme_parsing import VERSION as MS_VERSION

    all_results: list[QuestionResult] = []

    for case in cases:
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

        correction = correct_paper(
            case.mark_scheme,
            extracted,
            gemini_client=gemini_client,  # type: ignore[arg-type]
        )

        for cq in correction.questions:
            gt = case.ground_truth.get(cq.question_id)
            if gt is None:
                continue
            q_type = "mcq" if cq.marker_source == "deterministic" else "theory"
            all_results.append(QuestionResult(
                question_id=cq.question_id,
                question_type=q_type,
                predicted_marks=cq.awarded_marks,
                truth_marks=gt.awarded_marks,
                confidence_score=cq.confidence_score,
                needs_teacher_review=cq.needs_teacher_review,
            ))

    return AccuracyResult(
        metrics=_compute_metrics(all_results),
        calibration=_build_calibration(all_results),
        question_results=all_results,
        prompt_versions={
            "extraction": EXT_VERSION,
            "correction": COR_VERSION,
            "mark_scheme": MS_VERSION,
        },
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
        ("Correction", "mark_accuracy",         m.mark_accuracy,
         targets.mark_accuracy_target,  # type: ignore[attr-defined]
         "% of questions where awarded_marks == ground truth"),
        ("Correction", "mark_accuracy (theory)", m.mark_accuracy_theory,
         targets.mark_accuracy_target,
         "Same, theory-only (MCQ excluded)"),
        ("Extraction", "id_match_rate",          m.id_match_rate,
         targets.id_match_rate_target,
         "% of leaf questions found in extracted output"),
        ("Confidence", "flag_precision (HIGH)",  m.flag_precision_high,
         targets.flag_precision_target,
         "Of HIGH-confidence decisions, % actually correct"),
        ("Confidence", "flag_recall",            m.flag_recall,
         targets.flag_recall_target,
         "Of wrong marks, % flagged for review"),
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
        f"{'Confidence bucket':<20} {'Predictions':>12} {'Accuracy':>10} {'Gap (actual−stated)':>20}"
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
            ["git", "rev-parse", "--short", "HEAD"],
            text=True, stderr=subprocess.DEVNULL,
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
                "label": b.label, "lower": b.lower,
                "predictions": b.predictions, "correct": b.correct,
                "actual_accuracy": b.actual_accuracy,
                "calibration_gap": b.calibration_gap,
            }
            for b in result.calibration
        ],
        "prompt_versions": result.prompt_versions,
        "question_results": [
            {
                "question_id": r.question_id, "question_type": r.question_type,
                "predicted_marks": r.predicted_marks, "truth_marks": r.truth_marks,
                "confidence_score": r.confidence_score,
                "needs_teacher_review": r.needs_teacher_review,
                "is_correct": r.is_correct,
            }
            for r in result.question_results
        ],
    }
    out_path.write_text(_json.dumps(data, indent=2), encoding="utf-8")
    return out_path
