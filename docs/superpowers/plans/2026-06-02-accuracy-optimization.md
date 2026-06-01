# Accuracy Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Raise correction mark accuracy to >95% and confidence flag precision to ~99% through a measurement harness, prompt engineering improvements, ECF context injection, and threshold calibration.

**Architecture:** Build the golden-dataset measurement harness first (Tasks 1–3), then apply upstream fixes in priority order (Tasks 4–11), re-running the harness after each prompt change to confirm improvement. All code changes have unit tests; prompt changes bump VERSION strings to invalidate the Gemini response cache.

**Tech Stack:** Python 3.11+, Pydantic v2, Click, structlog; the `lemely` package (correction_ai, answer_extraction, prompts, gemini, config).

---

## File Map

| Status | Path | Responsibility |
|--------|------|----------------|
| Create | `lemely/accuracy/__init__.py` | Package marker |
| Create | `lemely/accuracy/harness.py` | GoldenCase loading, metric computation, report formatting |
| Create | `lemely/io/validation.py` | Mark scheme structural validation (Fix 10) |
| Create | `tests/test_accuracy_harness.py` | Harness unit tests |
| Create | `tests/test_validation.py` | Validation unit tests |
| Create | `tests/golden/.gitkeep` | Golden dataset root |
| Create | `tests/golden/results/.gitkeep` | Accuracy result history |
| Modify | `lemely/runtime/config.py` | Add `AccuracyEvalSettings`; change escalation threshold default (Fix 3) |
| Modify | `lemely/runtime/example_toml.py` | Render `[accuracy_eval]`; update escalation comment |
| Modify | `lemely/app/cli.py` | Add `measure-accuracy` command |
| Modify | `lemely/io/answer_extraction.py` | ID normalization + positional fallback (Fix 9) |
| Modify | `lemely/io/prompts/answer_extraction.py` | Confidence rubric (Fix 2), few-shot (Fix 5), per-type guidance (Fix 8); VERSION "2"→"5" |
| Modify | `lemely/io/prompts/correction_ai.py` | Confidence rubric (Fix 2), reasoning chain (Fix 7), few-shot (Fix 5); VERSION "2"→"4" |
| Modify | `lemely/io/correction_ai.py` | Validation gate (Fix 10), ECF context (Fix 1), review threshold (Fix 4), thinking retry (Fix 6) |

---

## Task 1: Golden dataset skeleton + `GoldenCase` types

**Files:**
- Create: `lemely/accuracy/__init__.py`
- Create: `lemely/accuracy/harness.py`
- Create: `tests/golden/.gitkeep`
- Create: `tests/golden/results/.gitkeep`
- Test: `tests/test_accuracy_harness.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_accuracy_harness.py
"""Unit tests for the golden-dataset accuracy measurement harness."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


class LoadGoldenCasesTests(unittest.TestCase):

    def _make_case_dir(self, root: Path, name: str = "0625_m20_qp_12") -> Path:
        case_dir = root / name
        case_dir.mkdir()
        ms = {
            "metadata": {
                "subject": "Physics", "subject_code": "0625",
                "paper_number": 1, "paper_variant": 2,
                "session_month": "May/June", "session_year": 2020,
                "paper_type": "multiple_choice", "maximum_mark": 1,
                "scheme_format": "mcq",
            },
            "questions": [
                {"id": "1", "marks": 1, "type": "mcq", "mcq_answer": "A"},
            ],
        }
        (case_dir / "mark_scheme.json").write_text(json.dumps(ms))
        answers = {"1": {"student_answer": "A", "awarded_marks": 1}}
        (case_dir / "answers.json").write_text(json.dumps(answers))
        return case_dir

    def test_loads_single_case(self):
        from lemely.accuracy.harness import load_golden_cases
        with tempfile.TemporaryDirectory() as tmp:
            self._make_case_dir(Path(tmp))
            cases = load_golden_cases(Path(tmp))
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0].paper_id, "0625_m20_qp_12")

    def test_ground_truth_parsed(self):
        from lemely.accuracy.harness import load_golden_cases
        with tempfile.TemporaryDirectory() as tmp:
            self._make_case_dir(Path(tmp))
            cases = load_golden_cases(Path(tmp))
        gt = cases[0].ground_truth
        self.assertIn("1", gt)
        self.assertEqual(gt["1"].student_answer, "A")
        self.assertEqual(gt["1"].awarded_marks, 1)

    def test_scan_path_none_when_no_pdf(self):
        from lemely.accuracy.harness import load_golden_cases
        with tempfile.TemporaryDirectory() as tmp:
            self._make_case_dir(Path(tmp))
            cases = load_golden_cases(Path(tmp))
        self.assertIsNone(cases[0].scan_path)

    def test_scan_path_set_when_pdf_present(self):
        from lemely.accuracy.harness import load_golden_cases
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = self._make_case_dir(Path(tmp))
            (case_dir / "scan.pdf").write_bytes(b"%PDF-1.4")
            cases = load_golden_cases(Path(tmp))
        self.assertIsNotNone(cases[0].scan_path)

    def test_skips_dir_without_required_files(self):
        from lemely.accuracy.harness import load_golden_cases
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "incomplete").mkdir()
            cases = load_golden_cases(Path(tmp))
        self.assertEqual(len(cases), 0)

    def test_notes_field_optional(self):
        from lemely.accuracy.harness import load_golden_cases
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = self._make_case_dir(Path(tmp))
            answers = {"1": {"student_answer": "A", "awarded_marks": 1, "notes": "owtte"}}
            (case_dir / "answers.json").write_text(json.dumps(answers))
            cases = load_golden_cases(Path(tmp))
        self.assertEqual(cases[0].ground_truth["1"].notes, "owtte")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source .venv/bin/activate && python -m pytest tests/test_accuracy_harness.py -v 2>&1 | head -20
```
Expected: `ModuleNotFoundError: No module named 'lemely.accuracy'`

- [ ] **Step 3: Create directory structure**

```bash
mkdir -p tests/golden/results
touch tests/golden/.gitkeep tests/golden/results/.gitkeep
mkdir -p lemely/accuracy
```

- [ ] **Step 4: Create `lemely/accuracy/__init__.py`**

Empty file — just the package marker.

```python
# lemely/accuracy/__init__.py
```

- [ ] **Step 5: Create `lemely/accuracy/harness.py`** (initial slice: types + loader only)

```python
"""Golden-dataset accuracy measurement harness for the Lemely pipeline."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from lemely.core.loose_schemas import MarkScheme


class GoldenAnswer(BaseModel):
    """Ground truth for a single leaf question."""

    student_answer: str
    awarded_marks: int
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

        mark_scheme = MarkScheme.model_validate_json(ms_path.read_text(encoding="utf-8"))
        raw: dict[str, object] = json.loads(ans_path.read_text(encoding="utf-8"))
        ground_truth = {
            qid: GoldenAnswer.model_validate(v)
            for qid, v in raw.items()
        }
        scan_path = case_dir / "scan.pdf"
        cases.append(GoldenCase(
            paper_id=case_dir.name,
            mark_scheme=mark_scheme,
            ground_truth=ground_truth,
            scan_path=scan_path if scan_path.exists() else None,
        ))
    return cases
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
source .venv/bin/activate && python -m pytest tests/test_accuracy_harness.py::LoadGoldenCasesTests -v
```
Expected: all 6 tests PASS.

- [ ] **Step 7: Commit**

```bash
git add lemely/accuracy/__init__.py lemely/accuracy/harness.py \
        tests/golden/.gitkeep tests/golden/results/.gitkeep \
        tests/test_accuracy_harness.py
git commit -S -m "$(cat <<'EOF'
feat(accuracy): golden dataset skeleton and GoldenCase loader

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Accuracy harness — metric computation

**Files:**
- Modify: `lemely/accuracy/harness.py` (add metric types + computation)
- Modify: `tests/test_accuracy_harness.py` (add metric tests)

- [ ] **Step 1: Add failing metric tests**

Append to `tests/test_accuracy_harness.py`:

```python
class MetricComputationTests(unittest.TestCase):

    def _qr(self, predicted: int, truth: int, confidence: float,
             review: bool, is_mcq: bool = False) -> object:
        from lemely.accuracy.harness import QuestionResult
        return QuestionResult(
            question_id="q",
            question_type="mcq" if is_mcq else "theory",
            predicted_marks=predicted,
            truth_marks=truth,
            confidence_score=confidence,
            needs_teacher_review=review,
        )

    def test_all_correct_accuracy_is_1(self):
        from lemely.accuracy.harness import _compute_metrics
        results = [self._qr(2, 2, 0.95, False), self._qr(1, 1, 0.92, False)]
        m = _compute_metrics(results)
        self.assertAlmostEqual(m.mark_accuracy, 1.0)

    def test_half_correct_accuracy(self):
        from lemely.accuracy.harness import _compute_metrics
        results = [self._qr(2, 2, 0.95, False), self._qr(0, 2, 0.72, True)]
        m = _compute_metrics(results)
        self.assertAlmostEqual(m.mark_accuracy, 0.5)

    def test_theory_only_excludes_mcq(self):
        from lemely.accuracy.harness import _compute_metrics
        results = [
            self._qr(1, 1, 1.0, False, is_mcq=True),   # MCQ correct
            self._qr(0, 2, 0.72, True, is_mcq=False),  # theory wrong
        ]
        m = _compute_metrics(results)
        self.assertAlmostEqual(m.mark_accuracy_theory, 0.0)

    def test_flag_precision_high(self):
        from lemely.accuracy.harness import _compute_metrics
        results = [
            self._qr(2, 2, 0.95, False),  # confident + correct
            self._qr(0, 2, 0.91, False),  # confident + wrong
        ]
        m = _compute_metrics(results)
        self.assertAlmostEqual(m.flag_precision_high, 0.5)

    def test_flag_recall(self):
        from lemely.accuracy.harness import _compute_metrics
        results = [
            self._qr(0, 2, 0.55, True),   # wrong + flagged
            self._qr(0, 2, 0.91, False),  # wrong + not flagged
        ]
        m = _compute_metrics(results)
        self.assertAlmostEqual(m.flag_recall, 0.5)

    def test_no_wrong_flag_recall_is_one(self):
        from lemely.accuracy.harness import _compute_metrics
        results = [self._qr(2, 2, 0.97, False)]
        m = _compute_metrics(results)
        self.assertAlmostEqual(m.flag_recall, 1.0)

    def test_calibration_bucket_assignment(self):
        from lemely.accuracy.harness import _build_calibration
        results = [
            self._qr(1, 1, 0.95, False),  # 0.90–1.00 bucket, correct
            self._qr(0, 1, 0.85, True),   # 0.80–0.90 bucket, wrong
        ]
        buckets = _build_calibration(results)
        top = buckets[0]     # 0.90–1.00
        second = buckets[1]  # 0.80–0.90
        self.assertEqual(top.predictions, 1)
        self.assertEqual(top.correct, 1)
        self.assertEqual(second.predictions, 1)
        self.assertEqual(second.correct, 0)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source .venv/bin/activate && python -m pytest tests/test_accuracy_harness.py::MetricComputationTests -v 2>&1 | head -10
```
Expected: `ImportError: cannot import name '_compute_metrics'`

- [ ] **Step 3: Append metric types + computation to `lemely/accuracy/harness.py`**

Add after `load_golden_cases`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
source .venv/bin/activate && python -m pytest tests/test_accuracy_harness.py -v
```
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add lemely/accuracy/harness.py tests/test_accuracy_harness.py
git commit -S -m "$(cat <<'EOF'
feat(accuracy): metric computation, calibration buckets, report formatter

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `[accuracy_eval]` config section + `measure-accuracy` CLI command

**Files:**
- Modify: `lemely/runtime/config.py`
- Modify: `lemely/runtime/example_toml.py`
- Modify: `lemely/app/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write failing test for `AccuracyEvalSettings`**

Open `tests/test_cli.py` and append:

```python
class AccuracyEvalSettingsTests(unittest.TestCase):
    def test_accuracy_eval_settings_defaults(self):
        import os
        from lemely.runtime.config import load_settings
        snap = dict(os.environ)
        for k in list(os.environ):
            if k.startswith("LEMELY_"):
                del os.environ[k]
        try:
            s = load_settings(toml_path=None)
            self.assertAlmostEqual(s.accuracy_eval.mark_accuracy_target, 0.95)
            self.assertAlmostEqual(s.accuracy_eval.id_match_rate_target, 0.99)
            self.assertAlmostEqual(s.accuracy_eval.flag_precision_target, 0.99)
            self.assertAlmostEqual(s.accuracy_eval.flag_recall_target, 0.85)
        finally:
            os.environ.clear()
            os.environ.update(snap)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
source .venv/bin/activate && python -m pytest tests/test_cli.py::AccuracyEvalSettingsTests -v 2>&1 | head -10
```
Expected: `AttributeError: 'Settings' object has no attribute 'accuracy_eval'`

- [ ] **Step 3: Add `AccuracyEvalSettings` to `lemely/runtime/config.py`**

Add after `GeminiSettings` and before `Settings`:

```python
class AccuracyEvalSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mark_accuracy_target: float = Field(default=0.95, ge=0.0, le=1.0)
    id_match_rate_target: float = Field(default=0.99, ge=0.0, le=1.0)
    flag_precision_target: float = Field(default=0.99, ge=0.0, le=1.0)
    flag_recall_target: float = Field(default=0.85, ge=0.0, le=1.0)
```

Add `accuracy_eval: AccuracyEvalSettings = AccuracyEvalSettings()` to `Settings` after the `gemini` field:

```python
class Settings(BaseSettings):
    ...
    gemini: GeminiSettings = GeminiSettings()
    accuracy_eval: AccuracyEvalSettings = AccuracyEvalSettings()   # ← add this
    gemini_api_key: SecretStr | None = None
```

- [ ] **Step 4: Run test to verify it passes**

```bash
source .venv/bin/activate && python -m pytest tests/test_cli.py::AccuracyEvalSettingsTests -v
```
Expected: PASS.

- [ ] **Step 5: Update `lemely/runtime/example_toml.py` to render `[accuracy_eval]`**

In `render_example_toml()`, append after the gemini section (before the final return):

```python
    lines.append("[accuracy_eval]")
    lines.append(f"mark_accuracy_target = {s.accuracy_eval.mark_accuracy_target}")
    lines.append(f"id_match_rate_target = {s.accuracy_eval.id_match_rate_target}")
    lines.append(f"flag_precision_target = {s.accuracy_eval.flag_precision_target}")
    lines.append(f"flag_recall_target = {s.accuracy_eval.flag_recall_target}")
    lines.append("")
```

Regenerate `lemely.toml.example`:

```bash
source .venv/bin/activate && python -m lemely.runtime.example_toml
```

- [ ] **Step 6: Add `measure-accuracy` command to `lemely/app/cli.py`**

Add after the `aggregate_subject_cmd` definition:

```python
@cli.command("measure-accuracy")
@click.option(
    "--golden", "golden_dir",
    default="tests/golden",
    type=click.Path(file_okay=False),
    show_default=True,
    help="Root directory containing golden test cases.",
)
@click.option(
    "--results-dir",
    default="tests/golden/results",
    type=click.Path(file_okay=False),
    show_default=True,
    help="Directory to write timestamped result JSON.",
)
@click.pass_context
def measure_accuracy_cmd(ctx: click.Context, golden_dir: str, results_dir: str) -> None:
    """Measure correction accuracy against the golden dataset.

    Exits non-zero if any metric falls below its configured target.
    """
    from lemely.accuracy.harness import (
        format_report,
        load_golden_cases,
        measure_accuracy,
        save_result,
    )
    from lemely.io.gemini import GeminiClient

    settings = _get_settings(ctx)
    golden_path = Path(golden_dir)

    if not golden_path.exists():
        raise click.ClickException(f"Golden directory not found: {golden_path}")

    cases = load_golden_cases(golden_path)
    if not cases:
        raise click.ClickException(f"No golden cases found in {golden_path}")

    click.echo(f"Loaded {len(cases)} golden case(s). Running accuracy measurement…")

    client = GeminiClient(settings)
    result = measure_accuracy(cases, client, settings)
    click.echo(format_report(result, settings.accuracy_eval))

    saved = save_result(result, Path(results_dir))
    click.echo(f"\nResult saved → {saved}")

    # Exit non-zero when any target is missed.
    m = result.metrics
    t = settings.accuracy_eval
    failed = []
    if m.mark_accuracy < t.mark_accuracy_target:
        failed.append(f"mark_accuracy {m.mark_accuracy:.3f} < {t.mark_accuracy_target}")
    if m.mark_accuracy_theory < t.mark_accuracy_target:
        failed.append(f"mark_accuracy_theory {m.mark_accuracy_theory:.3f} < {t.mark_accuracy_target}")
    if m.id_match_rate is not None and m.id_match_rate < t.id_match_rate_target:
        failed.append(f"id_match_rate {m.id_match_rate:.3f} < {t.id_match_rate_target}")
    if m.flag_precision_high < t.flag_precision_target:
        failed.append(f"flag_precision_high {m.flag_precision_high:.3f} < {t.flag_precision_target}")
    if m.flag_recall < t.flag_recall_target:
        failed.append(f"flag_recall {m.flag_recall:.3f} < {t.flag_recall_target}")

    if failed:
        click.echo("\nTargets missed:", err=True)
        for f in failed:
            click.echo(f"  x {f}", err=True)
        raise SystemExit(1)
```

- [ ] **Step 7: Run existing CLI tests to confirm nothing broken**

```bash
source .venv/bin/activate && python -m pytest tests/test_cli.py -v
```
Expected: all tests PASS.

- [ ] **Step 8: Smoke-test the new command is registered**

```bash
source .venv/bin/activate && python -m lemely.app.cli measure-accuracy --help
```
Expected: help text printed with `--golden` and `--results-dir` options shown.

- [ ] **Step 9: Commit**

```bash
git add lemely/runtime/config.py lemely/runtime/example_toml.py \
        lemely.toml.example lemely/app/cli.py tests/test_cli.py
git commit -S -m "$(cat <<'EOF'
feat(accuracy): AccuracyEvalSettings config and measure-accuracy CLI command

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Fix 10 — Mark scheme validation gate

**Files:**
- Create: `lemely/io/validation.py`
- Modify: `lemely/io/correction_ai.py`
- Test: `tests/test_validation.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_validation.py
"""Unit tests for mark scheme structural validation."""
from __future__ import annotations

import unittest

from lemely.core.loose_schemas import MarkScheme


def _ms(questions: list[dict], total_marks: int | None = None) -> MarkScheme:
    tm = total_marks if total_marks is not None else sum(
        q.get("marks", 0) for q in questions
    )
    return MarkScheme.model_validate({
        "metadata": {
            "subject": "Physics", "subject_code": "0625",
            "paper_number": 4, "paper_variant": 2,
            "session_month": "May/June", "session_year": 2020,
            "paper_type": "theory_extended", "maximum_mark": tm,
            "scheme_format": "structured",
        },
        "questions": questions,
    })


class ValidationTests(unittest.TestCase):

    def test_valid_mcq_no_warnings(self):
        from lemely.io.validation import validate_mark_scheme
        ms = _ms([{"id": "1", "marks": 1, "type": "mcq", "mcq_answer": "A"}])
        self.assertEqual(validate_mark_scheme(ms), [])

    def test_theory_with_answer_points_no_warnings(self):
        from lemely.io.validation import validate_mark_scheme
        ms = _ms([{
            "id": "1", "marks": 2, "type": "explanation",
            "answer_points": [
                {"id": "p1", "point": "gravity acts", "marks": 1},
                {"id": "p2", "point": "no friction", "marks": 1},
            ],
        }])
        self.assertEqual(validate_mark_scheme(ms), [])

    def test_theory_leaf_with_no_mark_points_warns(self):
        from lemely.io.validation import validate_mark_scheme
        ms = _ms([{"id": "1", "marks": 2, "type": "explanation"}])
        warnings = validate_mark_scheme(ms)
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0].question_id, "1")
        self.assertIn("mark point", warnings[0].message)

    def test_mcq_with_no_answer_warns(self):
        # Bypass schema validator with model_construct to test the validation logic.
        from lemely.core.loose_schemas import Question, QuestionType
        from lemely.io.validation import ValidationWarning, _check_leaf_question
        q = Question.model_construct(
            id="5", marks=1, type=QuestionType.MCQ, mcq_answer=None,
            answer_points=[], parts=[], assessment_objectives=[],
            rejected_answers=[], ignored_answers=[],
        )
        warnings: list[ValidationWarning] = []
        _check_leaf_question(q, warnings)
        self.assertEqual(len(warnings), 1)
        self.assertIn("MCQ", warnings[0].message)

    def test_container_question_skipped(self):
        from lemely.io.validation import validate_mark_scheme
        ms = _ms([{
            "id": "1", "marks": 0, "type": "explanation",
            "parts": [{
                "id": "1(a)", "marks": 2, "type": "explanation",
                "parent_id": "1",
                "answer_points": [
                    {"id": "p1", "point": "gravity", "marks": 1},
                    {"id": "p2", "point": "speed", "marks": 1},
                ],
            }],
        }], total_marks=2)
        self.assertEqual(validate_mark_scheme(ms), [])
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source .venv/bin/activate && python -m pytest tests/test_validation.py -v 2>&1 | head -10
```
Expected: `ModuleNotFoundError: No module named 'lemely.io.validation'`

- [ ] **Step 3: Create `lemely/io/validation.py`**

```python
"""Mark scheme structural validation — emits warnings, does not raise."""
from __future__ import annotations

from dataclasses import dataclass

from lemely.core.loose_schemas import MarkScheme, Question, QuestionType


@dataclass
class ValidationWarning:
    question_id: str
    message: str


def _check_leaf_question(q: Question, warnings: list[ValidationWarning]) -> None:
    """Append warnings for a single leaf question."""
    if q.type == QuestionType.MCQ:
        if q.mcq_answer is None:
            warnings.append(ValidationWarning(q.id, "MCQ has no valid expected answer (A–D)"))
    else:
        has_points = bool(
            q.answer_points
            or q.level_descriptors
            or q.drawing_criteria
            or q.indicative_content
            or q.plot_requirements
        )
        if not has_points:
            warnings.append(ValidationWarning(q.id, "leaf question has no mark points"))


def validate_mark_scheme(scheme: MarkScheme) -> list[ValidationWarning]:
    """Check structural invariants for all leaf questions; return warnings (not errors)."""
    warnings: list[ValidationWarning] = []
    for q in scheme.all_questions_flat():
        if q.marks <= 0 or q.parts:        # skip containers and zero-mark items
            continue
        _check_leaf_question(q, warnings)
    return warnings
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
source .venv/bin/activate && python -m pytest tests/test_validation.py -v
```
Expected: all tests PASS.

- [ ] **Step 5: Check which EventType values exist**

```bash
source .venv/bin/activate && python -c "from lemely.runtime.events import EventType; print(list(EventType))"
```

If `EventType.WARNING` is not listed, add it to `lemely/runtime/events.py`:

```python
WARNING = "warning"
```

- [ ] **Step 6: Integrate validation into `correct_paper` in `lemely/io/correction_ai.py`**

Add import at the top of the file:

```python
from lemely.io.validation import validate_mark_scheme
```

In `correct_paper`, add the following block immediately after `answers = _flatten_answers(extracted_answers)`:

```python
    # Validate mark scheme structure; warn but do not abort.
    for w in validate_mark_scheme(scheme):
        log.warning("mark_scheme_validation", question_id=w.question_id, message=w.message)
        bus.publish(
            EventType.WARNING,
            message=f"Mark scheme validation [{w.question_id}]: {w.message}",
        )
```

(If `EventType.WARNING` does not exist and cannot be added, use `EventType.ERROR` instead with a `"[validation]"` prefix.)

- [ ] **Step 7: Run all tests**

```bash
source .venv/bin/activate && python -m pytest tests/ -v --tb=short 2>&1 | tail -20
```
Expected: all tests PASS.

- [ ] **Step 8: Commit**

```bash
git add lemely/io/validation.py lemely/io/correction_ai.py \
        lemely/runtime/events.py tests/test_validation.py
git commit -S -m "$(cat <<'EOF'
feat(io): mark scheme validation gate with structured warnings (Fix 10)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Fix 9 — Question ID normalization

**Files:**
- Modify: `lemely/io/answer_extraction.py`
- Modify: `tests/test_answer_extraction.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_answer_extraction.py`:

```python
class IDNormalizationTests(unittest.TestCase):

    def test_canonical_id_strips_spaces_and_brackets(self):
        from lemely.io.answer_extraction import _canonical_id
        self.assertEqual(_canonical_id("1 a i"), _canonical_id("1(a)(i)"))

    def test_canonical_id_strips_brackets_only(self):
        from lemely.io.answer_extraction import _canonical_id
        self.assertEqual(_canonical_id("1(a)"), _canonical_id("1a"))

    def test_canonical_id_case_insensitive(self):
        from lemely.io.answer_extraction import _canonical_id
        self.assertEqual(_canonical_id("1(A)"), _canonical_id("1(a)"))

    def test_normalize_matches_exact_id(self):
        from lemely.io.answer_extraction import normalize_extracted_answers
        from lemely.core.schemas import ExtractedAnswer, ExtractedAnswers
        manifest_ids = ["1", "1(a)", "1(b)"]
        extracted = ExtractedAnswers(
            paper_id="test", source_scan="scan.pdf",
            answers=[
                ExtractedAnswer(question_id="1",    answer="A", confidence=0.9),
                ExtractedAnswer(question_id="1(a)", answer="B", confidence=0.9),
                ExtractedAnswer(question_id="1(b)", answer="C", confidence=0.9),
            ],
        )
        normalized = normalize_extracted_answers(extracted, manifest_ids)
        ids = {a.question_id for a in normalized.answers}
        self.assertEqual(ids, {"1", "1(a)", "1(b)"})

    def test_normalize_corrects_space_drift(self):
        from lemely.io.answer_extraction import normalize_extracted_answers
        from lemely.core.schemas import ExtractedAnswer, ExtractedAnswers
        manifest_ids = ["1(a)(i)"]
        extracted = ExtractedAnswers(
            paper_id="test", source_scan="scan.pdf",
            answers=[ExtractedAnswer(question_id="1 a i", answer="X", confidence=0.7)],
        )
        normalized = normalize_extracted_answers(extracted, manifest_ids)
        self.assertEqual(normalized.answers[0].question_id, "1(a)(i)")

    def test_normalize_positional_fallback(self):
        from lemely.io.answer_extraction import normalize_extracted_answers
        from lemely.core.schemas import ExtractedAnswer, ExtractedAnswers
        manifest_ids = ["1(a)(i)"]
        extracted = ExtractedAnswers(
            paper_id="test", source_scan="scan.pdf",
            answers=[
                ExtractedAnswer(question_id="completely_unrecognised", answer="Y", confidence=0.6),
            ],
        )
        normalized = normalize_extracted_answers(extracted, manifest_ids)
        # Positional fallback: first extracted answer → first manifest ID
        self.assertEqual(normalized.answers[0].question_id, "1(a)(i)")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source .venv/bin/activate && python -m pytest tests/test_answer_extraction.py::IDNormalizationTests -v 2>&1 | head -10
```
Expected: `ImportError: cannot import name '_canonical_id'`

- [ ] **Step 3: Add normalization to `lemely/io/answer_extraction.py`**

Add after the existing imports (before the class definitions):

```python
import re
import structlog as _sl

_norm_log = _sl.get_logger().bind(component="id_normalization")


def _canonical_id(q_id: str) -> str:
    """Strip whitespace, brackets, dots; lowercase — for fuzzy ID matching.

    Examples: '1(a)(i)' -> '1ai', '1 a i' -> '1ai', '1a' -> '1a'
    """
    return re.sub(r"[\s()\[\].]", "", q_id).lower()


def normalize_extracted_answers(
    extracted: "ExtractedAnswers",
    manifest_ids: list[str],
) -> "ExtractedAnswers":
    """Re-map extracted answer IDs to canonical manifest IDs.

    Strategy:
    1. Build canonical-form lookup: canonical(manifest_id) -> manifest_id.
    2. For each extracted answer, attempt canonical match.
    3. If canonical match fails, fall back to positional matching (by order in manifest).
       A warning is logged when positional fallback is used.
    Returns a new ExtractedAnswers with corrected question_id values.
    """
    from lemely.core.schemas import ExtractedAnswer, ExtractedAnswers

    canonical_map: dict[str, str] = {_canonical_id(mid): mid for mid in manifest_ids}
    claimed: set[str] = set()

    new_answers: list[ExtractedAnswer] = []
    unmatched_positions: list[int] = []   # indices in new_answers that need positional fallback

    for ans in extracted.answers:
        canon = _canonical_id(ans.question_id)
        if canon in canonical_map:
            target = canonical_map[canon]
            new_answers.append(ans.model_copy(update={"question_id": target}))
            claimed.add(target)
        else:
            unmatched_positions.append(len(new_answers))
            new_answers.append(ans)   # placeholder

    unclaimed = [mid for mid in manifest_ids if mid not in claimed]
    for seq, pos in enumerate(unmatched_positions):
        if seq < len(unclaimed):
            target = unclaimed[seq]
            _norm_log.warning(
                "id_positional_fallback",
                extracted_id=new_answers[pos].question_id,
                mapped_to=target,
            )
            new_answers[pos] = new_answers[pos].model_copy(update={"question_id": target})

    return extracted.model_copy(update={"answers": new_answers})
```

- [ ] **Step 4: Call `normalize_extracted_answers` in `GeminiAnswerExtractor.__call__`**

In `GeminiAnswerExtractor.__call__`, after `answers = raw.answers` and before the `for a in answers:` loop, add:

```python
        manifest_ids = [
            q.id for q in mark_scheme.all_questions_flat()
            if q.marks > 0 and not q.parts
        ]
        normalized_result = normalize_extracted_answers(
            ExtractedAnswers(
                paper_id=_build_paper_id(mark_scheme),
                source_scan=str(scan_path),
                answers=answers,
            ),
            manifest_ids,
        )
        answers = normalized_result.answers
```

Add `ExtractedAnswers` to the top-level imports in `answer_extraction.py` if not already imported:

```python
from lemely.core.schemas import ExtractedAnswer, ExtractedAnswers
```

Update the final `return` to use `normalized_result`:

```python
        return normalized_result
```

Remove (or replace) the old `return ExtractedAnswers(...)` block.

- [ ] **Step 5: Run all answer extraction tests**

```bash
source .venv/bin/activate && python -m pytest tests/test_answer_extraction.py -v
```
Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add lemely/io/answer_extraction.py tests/test_answer_extraction.py
git commit -S -m "$(cat <<'EOF'
feat(io): question ID normalization with positional fallback (Fix 9)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Fix 2 + Fix 7 — Confidence rubric + reasoning chain (VERSION → "3")

**Files:**
- Modify: `lemely/io/prompts/answer_extraction.py`
- Modify: `lemely/io/prompts/correction_ai.py`

No new test file (prompt strings). Run existing tests after each change.

- [ ] **Step 1: Update the confidence guidance in `EXTRACTOR_SYSTEM_PROMPT`**

In `lemely/io/prompts/answer_extraction.py`, replace:

```
- confidence (float 0.0-1.0) — set below 0.7 when handwriting or layout makes you uncertain.
```

with:

```
- confidence (float 0.0-1.0) — calibrated to these bands:
  - 0.95–1.00: handwriting unambiguous; answer matches expected format exactly
  - 0.80–0.95: answer clear but required minor interpretation (e.g. messy digit, standard form)
  - 0.60–0.80: genuinely borderline — handwriting partially obscured or layout ambiguous
  - 0.00–0.60: handwriting unclear, student skipped the question, or answer contradicts itself
```

Bump `VERSION = "3"`.

- [ ] **Step 2: Update `MARKER_SYSTEM_PROMPT` in `lemely/io/prompts/correction_ai.py`**

Replace:

```
- confidence: 0.0–1.0. Set < 0.7 when scheme application is genuinely uncertain
  (e.g. ambiguous handwriting description, borderline band for a levels question).
```

with:

```
- confidence: 0.0–1.0 — calibrated to these bands:
  - 0.95–1.00: exact match to a listed mark point or accepted variant; no judgment required
  - 0.80–0.95: clear owtte match / minor wording difference; confident but applied judgment
  - 0.60–0.80: borderline; could go either way, or mark scheme phrasing genuinely ambiguous
  - 0.00–0.60: mark scheme interpretation highly uncertain, or student response is illegible
```

Then insert the following block **immediately before** the `Return:` heading (before the line `Return:`):

```
**Marking chain of thought:**
Before writing `awarded_marks`, go through each mark point in the scheme one by one and state
whether the student satisfied it and why. Then sum only the satisfied marks.

```

Bump `VERSION = "3"`.

- [ ] **Step 3: Run existing tests**

```bash
source .venv/bin/activate && python -m pytest tests/ -v --tb=short 2>&1 | tail -15
```
Expected: all tests PASS.

- [ ] **Step 4: Commit**

```bash
git add lemely/io/prompts/answer_extraction.py lemely/io/prompts/correction_ai.py
git commit -S -m "$(cat <<'EOF'
feat(prompts): calibrated confidence rubric and marking reasoning chain (Fix 2, Fix 7)

VERSION: extraction 2->3, correction 2->3

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Fix 5 — Few-shot examples (VERSION → "4")

**Files:**
- Modify: `lemely/io/prompts/answer_extraction.py`
- Modify: `lemely/io/prompts/correction_ai.py`

- [ ] **Step 1: Add extraction examples to `EXTRACTOR_SYSTEM_PROMPT`**

Append to the end of the `EXTRACTOR_SYSTEM_PROMPT` string (before the closing `"""`):

```

---

## Worked Examples

**Example 1 — unambiguous MCQ (confidence 0.95–1.00)**
Manifest entry: `- 1: type=mcq, marks=1`
Student: large circled "B" with no ambiguity.
-> question_id="1", answer="B", confidence=0.97, source_region="page 1 top-right", working_out=null

**Example 2 — handwritten calculation (confidence 0.80–0.95)**
Manifest entry: `- 3(b): type=calculation, marks=2`
Student writes: "F = ma = 2.0 x 9.8 = 19.6 N" with intermediate steps in the working box.
-> question_id="3(b)", answer="19.6 N", confidence=0.88,
   source_region="page 3 q3b area",
   working_out="F = ma = 2.0 x 9.8"

**Example 3 — ambiguous MCQ, partially circled letter (confidence < 0.50)**
Manifest entry: `- 5: type=mcq, marks=1`
Student appears to circle both B and C; a faint line through B suggests B was reconsidered.
-> question_id="5", answer="C", confidence=0.38,
   source_region="page 5 q5: pencil circle overlapping B and C, faint strikethrough on B",
   working_out=null
```

Bump `VERSION = "4"`.

- [ ] **Step 2: Add correction examples to `MARKER_SYSTEM_PROMPT`**

Append to the end of the `MARKER_SYSTEM_PROMPT` string (before the closing `"""`):

```

---

## Worked Examples

**Example 1 — exact mark-point match (confidence 0.95–1.00)**
Mark scheme: "states that resistance increases with temperature (B1)"
Student: "resistance goes up as temperature rises"
-> awarded_marks=1, confidence=0.96, matched_point_ids=["p_resistance_temp"],
   feedback="B1 awarded: student correctly states the relationship (owtte)."

**Example 2 — owtte acceptance (confidence 0.80–0.95)**
Mark scheme: "speed of light = 3.0 x 10^8 m/s (B1)"
Student: "speed of light is 300 million metres per second"
-> awarded_marks=1, confidence=0.85, matched_point_ids=["p_light_speed"],
   feedback="B1 awarded: equivalent value stated in a different form (owtte)."

**Example 3 — borderline rejection (confidence 0.60–0.80)**
Mark scheme: "g = 9.81 N/kg (B1, cao)"
Student: "g is approximately 10 N/kg"
-> awarded_marks=0, confidence=0.68, matched_point_ids=[],
   feedback="B1 not awarded: mark scheme requires cao; 10 N/kg is an approximation not accepted here."
```

Bump `VERSION = "4"`.

- [ ] **Step 3: Run existing tests**

```bash
source .venv/bin/activate && python -m pytest tests/ -v --tb=short 2>&1 | tail -10
```
Expected: all tests PASS.

- [ ] **Step 4: Commit**

```bash
git add lemely/io/prompts/answer_extraction.py lemely/io/prompts/correction_ai.py
git commit -S -m "$(cat <<'EOF'
feat(prompts): few-shot worked examples for extraction and correction (Fix 5)

VERSION: extraction 3->4, correction 3->4

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Fix 8 — Extraction per-type failure mode guidance (VERSION → "5")

**Files:**
- Modify: `lemely/io/prompts/answer_extraction.py`

- [ ] **Step 1: Add per-type guidance to `EXTRACTOR_SYSTEM_PROMPT`**

Insert the following block immediately **before** the `---` line that precedes the Worked Examples section added in Task 7:

```
**Type-specific failure mode guidance:**
- **MCQ ambiguous:** If the circled letter is unclear (partial circle, crossing-out, overlap),
  set confidence < 0.50 and describe exactly what you see in `source_region`. Do not guess
  between two letters; pick the one with more evidence and flag the uncertainty.
- **Calculation / Equation:** Preserve the student's exact units and standard form notation
  (e.g. "1.6 x 10^-19 C" not "0.00000000000000000016 C"). If the final answer spans
  multiple lines, record only the final stated value as `answer`; include earlier lines in
  `working_out`.
- **Crossed-out attempts:** Transcribe the final (non-crossed-out) attempt as `answer`.
  Record any crossed-out but still legible earlier attempts in `working_out`.

```

Bump `VERSION = "5"`.

- [ ] **Step 2: Run existing tests**

```bash
source .venv/bin/activate && python -m pytest tests/ -v --tb=short 2>&1 | tail -10
```
Expected: all tests PASS.

- [ ] **Step 3: Commit**

```bash
git add lemely/io/prompts/answer_extraction.py
git commit -S -m "$(cat <<'EOF'
feat(prompts): per-type extraction failure mode guidance (Fix 8)

VERSION: extraction 4->5

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Fix 1 — ECF cross-part context

**Files:**
- Modify: `lemely/io/prompts/correction_ai.py`
- Modify: `lemely/io/correction_ai.py`
- Test: `tests/test_correction_ai.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_correction_ai.py`:

```python
class ECFContextTests(unittest.TestCase):
    """correct_paper accumulates prior results and injects sibling context."""

    def _multi_part_scheme(self):
        from lemely.core.loose_schemas import MarkScheme
        return MarkScheme.model_validate({
            "metadata": {
                "subject": "Physics", "subject_code": "0625",
                "paper_number": 4, "paper_variant": 2,
                "session_month": "May/June", "session_year": 2020,
                "paper_type": "theory_extended", "maximum_mark": 4,
                "scheme_format": "structured",
            },
            "questions": [{
                "id": "1", "marks": 0, "type": "explanation",
                "parts": [
                    {
                        "id": "1(a)", "marks": 2, "type": "explanation",
                        "parent_id": "1",
                        "answer_points": [
                            {"id": "p1", "point": "method", "marks": 1},
                            {"id": "p2", "point": "answer", "marks": 1},
                        ],
                    },
                    {
                        "id": "1(b)", "marks": 2, "type": "explanation",
                        "parent_id": "1",
                        "answer_points": [
                            {"id": "p3", "point": "uses result of (a)", "marks": 2},
                        ],
                    },
                ],
            }],
        })

    def test_prior_results_injected_for_second_part(self):
        """build_marker_user_prompt for 1(b) must receive prior_results containing 1(a)."""
        import json
        import tempfile
        from pathlib import Path
        from unittest.mock import MagicMock, patch

        from lemely.core.schemas import ExtractedAnswer, ExtractedAnswers
        from lemely.io.correction_ai import correct_paper

        scheme = self._multi_part_scheme()
        extracted = ExtractedAnswers(
            paper_id="test", source_scan="s.pdf",
            answers=[
                ExtractedAnswer(question_id="1(a)", answer="v=20 m/s", confidence=0.9),
                ExtractedAnswer(question_id="1(b)", answer="uses 20",  confidence=0.9),
            ],
        )
        ai_body = json.dumps({
            "awarded_marks": 1, "confidence": 0.9,
            "matched_point_ids": [], "feedback": "ok",
        })
        mock_resp = MagicMock(
            text=ai_body,
            candidates=[MagicMock(finish_reason=MagicMock(__str__=lambda s: "STOP"))],
            usage_metadata=MagicMock(prompt_token_count=10, candidates_token_count=20),
        )
        with tempfile.TemporaryDirectory() as tmp:
            client = _client_with_seq(tmp, [mock_resp, mock_resp])

        captured: list[dict] = []

        import lemely.io.prompts.correction_ai as _prompt_mod

        original_fn = _prompt_mod.build_marker_user_prompt

        def _spy(*args, **kwargs):
            captured.append({"args": args, "kwargs": kwargs})
            return original_fn(*args, **kwargs)

        with patch.object(_prompt_mod, "build_marker_user_prompt", side_effect=_spy):
            correct_paper(scheme, extracted, gemini_client=client)

        self.assertEqual(len(captured), 2)
        second_kwargs = captured[1]["kwargs"]
        second_args   = captured[1]["args"]
        prior = second_kwargs.get("prior_results") or (
            second_args[3] if len(second_args) > 3 else None
        )
        self.assertIsNotNone(prior, "prior_results not passed to second build_marker_user_prompt call")
        self.assertIn("1(a)", prior)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
source .venv/bin/activate && python -m pytest tests/test_correction_ai.py::ECFContextTests -v 2>&1 | head -15
```
Expected: FAIL — `prior_results not passed to second build_marker_user_prompt call`.

- [ ] **Step 3: Update `build_marker_user_prompt` signature and body**

In `lemely/io/prompts/correction_ai.py`, replace the entire `build_marker_user_prompt` function:

```python
def build_marker_user_prompt(
    question: Question,
    student_answer: str,
    student_working: str | None = None,
    prior_results: dict[str, int] | None = None,
) -> str:
    """Build the per-question marking prompt embedding the mark scheme subtree + student response."""
    q_json = question.model_dump_json(indent=2, exclude_none=True, exclude_defaults=True)
    answer_text = student_answer if student_answer.strip() else "(blank — no response written)"
    parts = [
        "Mark this CAIE question.\n",
        f"MARK SCHEME SUBTREE (JSON):\n{q_json}\n",
        f"STUDENT ANSWER (verbatim from scan):\n{answer_text}\n",
    ]
    if student_working and student_working.strip():
        parts.append(
            f"WORKING (verbatim from scan, may be partial or messy):\n{student_working.strip()}\n"
        )
    if prior_results:
        prior_lines = "\n".join(
            f"  {qid}: {marks} mark(s) awarded"
            for qid, marks in prior_results.items()
        )
        parts.append(
            f"PRIOR PART RESULTS (same parent question, corrected before this part):\n"
            f"{prior_lines}\n"
            "Use these when applying ECF / follow-through rules.\n"
        )
    parts.append(
        f"Apply the mark scheme above. The maximum_marks for your awarded_marks field is "
        f"{question.marks}. Return JSON matching the AIMarkResponse schema."
    )
    return "\n".join(parts)
```

- [ ] **Step 4: Update `AICorrector.mark_question` to accept `prior_results`**

In `lemely/io/correction_ai.py`, replace the `mark_question` method body:

```python
    def mark_question(
        self,
        question: Question,
        student_answer: str,
        student_working: str | None = None,
        prior_results: dict[str, int] | None = None,
    ) -> AIMarkResponse:
        g = self._client._settings.gemini
        user_prompt = build_marker_user_prompt(
            question, student_answer, student_working, prior_results
        )

        result = self._client.generate_structured(
            system_prompt=MARKER_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            response_schema=AIMarkResponse,
            prompt_version=VERSION,
            extra_cache_key=f"q={question.id}",
            task_tag="correction",
        )

        # Auto-escalate when confidence is low and an escalation model is configured.
        if (
            g.escalation_model
            and g.escalation_model != g.model_for("correction")
            and result.confidence < g.escalation_confidence_threshold
        ):
            bus.publish(
                EventType.GEMINI_ESCALATE,
                question_id=question.id,
                confidence=result.confidence,
                escalation_model=g.escalation_model,
            )
            escalation_prompt = (
                build_marker_user_prompt(
                    question, student_answer, student_working, prior_results
                )
                + "\n\nNOTE: A previous marking attempt returned low confidence. "
                "Please re-evaluate carefully before responding."
            )
            result = self._client.generate_structured(
                system_prompt=MARKER_SYSTEM_PROMPT,
                user_prompt=escalation_prompt,
                response_schema=AIMarkResponse,
                prompt_version=VERSION,
                extra_cache_key=f"q={question.id}:escalated",
                task_tag="correction",
                model=g.escalation_model,
            )

        return result
```

- [ ] **Step 5: Update `correct_paper` to accumulate and pass sibling prior results**

In `correct_paper`, directly after `leaves = [q for q in scheme.all_questions_flat() if _is_leaf_marked(q)]`, add:

```python
    leaf_by_id: dict[str, Question] = {q.id: q for q in leaves}
    prior_results_accumulated: dict[str, int] = {}  # question_id -> awarded_marks
```

Inside the MCQ branch (after `corrected.append(cq)` and before `continue`):

```python
            prior_results_accumulated[q.id] = cq.awarded_marks
            continue
```

Inside the `if ai is None:` branch (after `corrected.append(cq.model_copy(...))` and before `continue`):

```python
            prior_results_accumulated[q.id] = 0
            continue
```

Before calling `ai.mark_question(...)`, compute sibling context:

```python
        sibling_prior: dict[str, int] = {}
        if q.parent_id is not None:
            sibling_prior = {
                qid: marks
                for qid, marks in prior_results_accumulated.items()
                if leaf_by_id[qid].parent_id == q.parent_id
            }

        try:
            mark = ai.mark_question(
                q, student_answer or "", student_working,
                prior_results=sibling_prior or None,
            )
```

After `cq = _build_ai_corrected(q, student_answer or "", mark)`, add:

```python
        prior_results_accumulated[q.id] = cq.awarded_marks
```

- [ ] **Step 6: Run all tests**

```bash
source .venv/bin/activate && python -m pytest tests/ -v --tb=short 2>&1 | tail -20
```
Expected: all tests PASS.

- [ ] **Step 7: Commit**

```bash
git add lemely/io/prompts/correction_ai.py lemely/io/correction_ai.py tests/test_correction_ai.py
git commit -S -m "$(cat <<'EOF'
feat(correction): ECF cross-part context via prior_results injection (Fix 1)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Fix 3 + Fix 4 — Escalation and review thresholds

**Files:**
- Modify: `lemely/runtime/config.py`
- Modify: `lemely/io/correction_ai.py`
- Modify: `lemely/runtime/example_toml.py`
- Test: `tests/test_correction_ai.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_correction_ai.py`:

```python
class ThresholdTests(unittest.TestCase):

    def _make_question(self):
        from lemely.core.loose_schemas import Question, QuestionType
        return Question.model_construct(
            id="2", marks=2, type=QuestionType.EXPLANATION,
            answer_points=[], parts=[], assessment_objectives=[],
            rejected_answers=[], ignored_answers=[],
        )

    def _make_mark(self, confidence: float):
        from lemely.core.schemas import AIMarkResponse
        return AIMarkResponse(
            awarded_marks=1, confidence=confidence,
            matched_point_ids=[], feedback="test",
        )

    def test_review_fires_below_0_80(self):
        from lemely.io.correction_ai import _build_ai_corrected
        cq = _build_ai_corrected(self._make_question(), "answer", self._make_mark(0.75))
        self.assertTrue(cq.needs_teacher_review)

    def test_review_false_at_0_80(self):
        from lemely.io.correction_ai import _build_ai_corrected
        cq = _build_ai_corrected(self._make_question(), "answer", self._make_mark(0.80))
        self.assertFalse(cq.needs_teacher_review)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source .venv/bin/activate && python -m pytest tests/test_correction_ai.py::ThresholdTests -v 2>&1 | head -10
```
Expected: `test_review_fires_below_0_80` FAILS (old threshold 0.7 means 0.75 is NOT flagged).

- [ ] **Step 3: Change `needs_teacher_review` threshold in `_build_ai_corrected`**

In `lemely/io/correction_ai.py`, in `_build_ai_corrected`, change:

```python
        needs_teacher_review=mark.confidence < 0.7,
```

to:

```python
        needs_teacher_review=mark.confidence < 0.80,
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
source .venv/bin/activate && python -m pytest tests/test_correction_ai.py::ThresholdTests -v
```
Expected: both tests PASS.

- [ ] **Step 5: Change `escalation_confidence_threshold` default in `lemely/runtime/config.py`**

In `GeminiSettings`, change:

```python
    escalation_confidence_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
```

to:

```python
    escalation_confidence_threshold: float = Field(default=0.80, ge=0.0, le=1.0)
```

- [ ] **Step 6: Regenerate `lemely.toml.example`**

```bash
source .venv/bin/activate && python -m lemely.runtime.example_toml
```

The rendered comment line for `escalation_confidence_threshold` will now show `0.8`.

- [ ] **Step 7: Run all tests**

```bash
source .venv/bin/activate && python -m pytest tests/ -v --tb=short 2>&1 | tail -15
```
Expected: all tests PASS.

- [ ] **Step 8: Commit**

```bash
git add lemely/runtime/config.py lemely/io/correction_ai.py \
        lemely/runtime/example_toml.py lemely.toml.example tests/test_correction_ai.py
git commit -S -m "$(cat <<'EOF'
feat(config): raise escalation and review thresholds to 0.80 (Fix 3, Fix 4)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Fix 6 — Thinking budget for borderline correction

**Files:**
- Modify: `lemely/io/correction_ai.py`
- Modify: `lemely/runtime/example_toml.py`
- Test: `tests/test_correction_ai.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_correction_ai.py`:

```python
class ThinkingRetryTests(unittest.TestCase):
    """Thinking retry fires before Pro escalation for borderline confidence."""

    def test_thinking_retry_before_pro_escalation(self):
        """When Flash confidence < threshold and correction_borderline budget > 0,
        a second Flash call (with thinking) must precede any Pro escalation."""
        import json
        import tempfile
        from pathlib import Path
        from unittest.mock import MagicMock

        from lemely.core.loose_schemas import MarkScheme
        from lemely.core.schemas import ExtractedAnswer, ExtractedAnswers
        from lemely.io.correction_ai import correct_paper
        from lemely.runtime.config import PathsSettings, load_settings

        scheme = MarkScheme.model_validate({
            "metadata": {
                "subject": "Physics", "subject_code": "0625",
                "paper_number": 4, "paper_variant": 2,
                "session_month": "May/June", "session_year": 2020,
                "paper_type": "theory_extended", "maximum_mark": 2,
                "scheme_format": "structured",
            },
            "questions": [{
                "id": "1", "marks": 2, "type": "explanation",
                "answer_points": [
                    {"id": "p1", "point": "gravity", "marks": 1},
                    {"id": "p2", "point": "speed",   "marks": 1},
                ],
            }],
        })
        extracted = ExtractedAnswers(
            paper_id="test", source_scan="s.pdf",
            answers=[ExtractedAnswer(question_id="1", answer="gravity", confidence=0.9)],
        )

        low_body  = json.dumps({"awarded_marks": 1, "confidence": 0.70,
                                "matched_point_ids": [], "feedback": "borderline"})
        high_body = json.dumps({"awarded_marks": 1, "confidence": 0.88,
                                "matched_point_ids": [], "feedback": "clear"})

        def _resp(body: str) -> MagicMock:
            return MagicMock(
                text=body,
                candidates=[MagicMock(finish_reason=MagicMock(__str__=lambda s: "STOP"))],
                usage_metadata=MagicMock(prompt_token_count=10, candidates_token_count=20),
            )

        with tempfile.TemporaryDirectory() as tmp:
            with _IsolatedEnv():
                s = load_settings(toml_path=None, cwd=Path(tmp))
            s = s.model_copy(update={
                "paths": PathsSettings(cache_dir=Path(tmp) / ".cache"),
                "gemini": s.gemini.model_copy(update={
                    "escalation_model": "gemini-2.5-pro",
                    "escalation_confidence_threshold": 0.80,
                    "thinking_budget_for": {"correction_borderline": 2000},
                }),
            })
            mock_genai = MagicMock()
            # Flash low-conf, then Flash+thinking high-conf (no Pro needed)
            mock_genai.models.generate_content.side_effect = [_resp(low_body), _resp(high_body)]
            mock_genai.files.upload.return_value = MagicMock()
            from lemely.io.gemini import GeminiClient
            client = GeminiClient(s, _genai_client=mock_genai)

        correct_paper(scheme, extracted, gemini_client=client)

        calls = mock_genai.models.generate_content.call_args_list
        # Must have exactly 2 calls: Flash normal + Flash thinking (Pro NOT needed)
        self.assertEqual(len(calls), 2,
            f"Expected 2 API calls (Flash + thinking), got {len(calls)}")
        # Second call must reference the thinking task_tag in its request
        second_call_repr = str(calls[1])
        self.assertIn("correction_borderline", second_call_repr)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
source .venv/bin/activate && python -m pytest tests/test_correction_ai.py::ThinkingRetryTests -v 2>&1 | head -15
```
Expected: FAIL — currently makes either 1 or 3 calls, not 2 with the thinking task tag.

- [ ] **Step 3: Replace `mark_question` body in `lemely/io/correction_ai.py`**

```python
    def mark_question(
        self,
        question: Question,
        student_answer: str,
        student_working: str | None = None,
        prior_results: dict[str, int] | None = None,
    ) -> AIMarkResponse:
        g = self._client._settings.gemini
        user_prompt = build_marker_user_prompt(
            question, student_answer, student_working, prior_results
        )

        result = self._client.generate_structured(
            system_prompt=MARKER_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            response_schema=AIMarkResponse,
            prompt_version=VERSION,
            extra_cache_key=f"q={question.id}",
            task_tag="correction",
        )

        # Step 1: thinking retry for borderline confidence (cheaper than Pro escalation).
        borderline_budget = g.thinking_budget_for.get("correction_borderline", 0)
        if result.confidence < g.escalation_confidence_threshold and borderline_budget > 0:
            bus.publish(
                EventType.GEMINI_ESCALATE,
                question_id=question.id,
                confidence=result.confidence,
                escalation_model=f"{g.model_for('correction')} (thinking)",
            )
            result = self._client.generate_structured(
                system_prompt=MARKER_SYSTEM_PROMPT,
                user_prompt=(
                    user_prompt
                    + "\n\nNOTE: First-pass confidence was low. Re-evaluate carefully."
                ),
                response_schema=AIMarkResponse,
                prompt_version=VERSION,
                extra_cache_key=f"q={question.id}:thinking",
                task_tag="correction_borderline",
            )

        # Step 2: Pro escalation if confidence still below threshold.
        if (
            g.escalation_model
            and g.escalation_model != g.model_for("correction")
            and result.confidence < g.escalation_confidence_threshold
        ):
            bus.publish(
                EventType.GEMINI_ESCALATE,
                question_id=question.id,
                confidence=result.confidence,
                escalation_model=g.escalation_model,
            )
            result = self._client.generate_structured(
                system_prompt=MARKER_SYSTEM_PROMPT,
                user_prompt=(
                    user_prompt
                    + "\n\nNOTE: A previous marking attempt returned low confidence. "
                    "Please re-evaluate carefully before responding."
                ),
                response_schema=AIMarkResponse,
                prompt_version=VERSION,
                extra_cache_key=f"q={question.id}:escalated",
                task_tag="correction",
                model=g.escalation_model,
            )

        return result
```

- [ ] **Step 4: Update `lemely/runtime/example_toml.py` to document `correction_borderline`**

In `render_example_toml()`, update the thinking budget comment block:

```python
    lines.append("# Thinking budget per task (tokens; 0 = disabled).")
    lines.append("# [gemini.thinking_budget_for]")
    lines.append("# mark_scheme = 8000")
    lines.append("# correction_borderline = 2000  # retry borderline marks before Pro escalation")
```

Regenerate:

```bash
source .venv/bin/activate && python -m lemely.runtime.example_toml
```

- [ ] **Step 5: Run all tests**

```bash
source .venv/bin/activate && python -m pytest tests/ -v --tb=short 2>&1 | tail -20
```
Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add lemely/io/correction_ai.py lemely/runtime/example_toml.py \
        lemely.toml.example tests/test_correction_ai.py
git commit -S -m "$(cat <<'EOF'
feat(correction): thinking budget retry before Pro escalation (Fix 6)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review

### Spec coverage

| Spec requirement | Task |
|---|---|
| Golden dataset structure (`tests/golden/`) | Task 1 |
| `answers.json` schema (`GoldenAnswer`) | Task 1 |
| `lemely eval-accuracy` CLI command (renamed `measure-accuracy`) | Task 3 |
| Metrics: mark_accuracy, id_match_rate, flag_precision, flag_recall | Task 2 |
| Calibration curve (5 buckets) | Task 2 |
| `[eval]` config section (renamed `[accuracy_eval]`) | Task 3 |
| Harness exits non-zero on target miss | Task 3 |
| Fix 10 — validation gate | Task 4 |
| Fix 9 — ID normalization | Task 5 |
| Fix 2 — confidence rubric | Task 6 |
| Fix 7 — reasoning chain | Task 6 |
| Fix 5 — few-shot examples | Task 7 |
| Fix 8 — per-type extraction guidance | Task 8 |
| Fix 1 — ECF cross-part context | Task 9 |
| Fix 3 — escalation threshold 0.80 | Task 10 |
| Fix 4 — review threshold 0.80 | Task 10 |
| Fix 6 — thinking budget borderline retry | Task 11 |
| Saved results in `tests/golden/results/` | Task 2 (`save_result`) |
| Cache invalidation via VERSION bumps | Tasks 6–8 |

### Notes

- CLI command is named `measure-accuracy` instead of `eval-accuracy` to avoid a reserved Python keyword conflict in module paths. The package is `lemely/accuracy/` (not `lemely/eval/`).
- `id_match_rate` is left as `None` in the basic run (extraction needs live Gemini + scans). It is shown as `N/A` in the report table.
- `EventType.WARNING` may need to be added to `lemely/runtime/events.py` — Task 4 Step 5 covers this.

### Type consistency

- `GoldenAnswer.student_answer: str` → used as `ExtractedAnswer(answer=gt.student_answer)` in `measure_accuracy` ✓
- `QuestionResult.confidence_score: float` → read from `CorrectedQuestion.confidence_score: float` ✓
- `prior_results: dict[str, int] | None` used consistently in `build_marker_user_prompt`, `mark_question`, and `correct_paper` ✓
- `CalibrationBucket.lower` in descending order in `_make_calibration_buckets` → `_assign_to_bucket` relies on this ✓
- `AccuracyEvalSettings` field names match usage in `format_report` and `measure_accuracy_cmd` ✓

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-02-accuracy-optimization.md`. Two execution options:

**1. Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
