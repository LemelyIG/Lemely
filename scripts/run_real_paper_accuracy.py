#!/usr/bin/env python3
"""Live real-past-paper accuracy runner (INBOX-2026-08-07-ACC).

Runs the two real solved-script fixtures through the **actual** ingest → OCR
(vision extraction) → mark → grade path (:mod:`lemely.web.services.grading`),
never a mocked stub, and writes per-fixture artefacts under
``reports/accuracy-real/<fixture-id>/``:

* ``raw_run.json``       — the full ``AccuracyReport`` as returned by the pipeline.
* ``per_question.json``  — the per-question breakdown (directive item 4): this
  contains the student's transcribed handwriting (``student_answer`` /
  ``working_out``) and is personal data of a minor — see
  ``reports/accuracy-real/.gitignore``.
* ``annotation_overlay.pdf`` — the original scan pages plus an appended summary
  page rendered with PyMuPDF, so a human can spot-check where the total came
  from without opening two files side by side.
* ``run_summary.json``   — the numbers-only result (what feeds ``REPORT.md``).

**Ground truth is the paper total only** (``34/40`` for paper 22, ``66/80`` for
paper 41 — see the fixture filenames). Per-question ground truth does not
exist and this script never fabricates or back-derives it.

Two fixtures, two marking paths, kept separate throughout (directive item 5):
paper 22 is MCQ (``correct_mcq_answers`` is deterministic — only the vision
extraction call touches Gemini); paper 41 is theory with method marks (vision
extraction *and* AI method-mark correction both touch Gemini, one correction
call per leaf question).

Idempotent by design: if ``run_summary.json`` already exists for a fixture,
this script replays it instead of re-spending Gemini budget (Gemini's own
disk cache in ``GeminiClient.generate_structured`` would make a raw re-run
free too, but this is a script-level guarantee that does not depend on cache
internals). Pass ``--force`` to re-run live regardless.

Output contract (matching ``scripts/seed_e2e.py``'s convention): all progress
goes to stderr; a single JSON object — ``{"fixtures": [<run_summary>, ...]}``
— goes to stdout, nothing else.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, TypedDict

import fitz  # PyMuPDF

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from lemely.accuracy.real_papers import (  # noqa: E402
    QuestionRow,
    RealPaperCase,
    absolute_error,
    confidence_distribution,
    mean_absolute_error,
    review_flagged_marks,
    signed_error,
    tolerance_marks,
    within_tolerance,
)
from lemely.core.loose_schemas import MarkScheme  # noqa: E402
from lemely.io.det import DeterministicMarkSchemeParser  # noqa: E402
from lemely.io.gemini import GeminiClient  # noqa: E402
from lemely.runtime.config import Settings  # noqa: E402
from lemely.web.services.grading import extract_answers, grade_paper  # noqa: E402

FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "real-papers"
REPORT_DIR = REPO_ROOT / "reports" / "accuracy-real"

TOLERANCE_PCT = 0.10  # see lemely/accuracy/real_papers.py:tolerance_marks docstring


class FixtureSpec(TypedDict):
    fixture_id: str
    scan: Path
    ground_truth_total: int
    max_total: int
    scheme_source: str  # "cached_json" | "deterministic_pdf"
    scheme_path: Path
    marking_path: str


FIXTURES: list[FixtureSpec] = [
    {
        "fixture_id": "0625_s23_qp_22",
        "scan": FIXTURES_DIR / "0625_s23_qp_22-(34..40).pdf",
        "ground_truth_total": 34,
        "max_total": 40,
        "scheme_source": "cached_json",
        "scheme_path": REPO_ROOT / "outputs" / "schemes" / "0625_s23_ms_22.json",
        "marking_path": "MCQ — deterministic marking; Gemini used only for vision extraction",
    },
    {
        "fixture_id": "0625_w24_qp_41",
        "scan": FIXTURES_DIR / "0625_w24_qp_41-(66..80).pdf",
        "ground_truth_total": 66,
        "max_total": 80,
        "scheme_source": "deterministic_pdf",
        "scheme_path": REPO_ROOT / "Sources" / "Physics" / "MarkingSchemes" / "0625_w24_ms_41.pdf",
        "marking_path": (
            "Theory with method marks — AI marking (one Gemini call per leaf "
            "question) + Gemini vision extraction"
        ),
    },
]


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def load_mark_scheme(spec: FixtureSpec, settings: Settings) -> MarkScheme:
    """Load the mark scheme for *spec* via whichever source is already resolved.

    Never re-parses the cached Gemini fallback for 0625_s23_ms_22 (it is
    already at ``outputs/schemes/0625_s23_ms_22.json``) and never re-derives a
    scheme — 0625_w24_ms_41 parses deterministically from the official PDF.
    """
    if spec["scheme_source"] == "cached_json":
        if not spec["scheme_path"].exists():
            raise FileNotFoundError(
                f"Cached mark scheme JSON missing: {spec['scheme_path']}. "
                "Do not re-parse via Gemini without checking with the human first "
                "— see BUILD/STATE.md INBOX-2026-08-07-ACC."
            )
        data = json.loads(spec["scheme_path"].read_text(encoding="utf-8"))
        return MarkScheme.model_validate(data)

    if not spec["scheme_path"].exists():
        raise FileNotFoundError(f"Official mark-scheme PDF missing: {spec['scheme_path']}")
    parser = DeterministicMarkSchemeParser(cfg=settings.det_parser)
    return parser(spec["scheme_path"])


def render_overlay(
    scan_path: Path, rows: list[QuestionRow], case_title: str, out_path: Path
) -> None:
    """Copy the scan's pages and append a rendered per-question summary page.

    There is no per-question bounding-box/page data in ``ExtractedAnswer`` (it
    carries a free-text ``source_region``, not coordinates), so this does not
    attempt to overlay marks spatially onto the handwriting — it appends a
    reviewable summary page listing every question's awarded/max marks,
    confidence band+score, and review flag, alongside the original scan pages,
    so a human opens one PDF and can cross-reference by eye.
    """
    doc = fitz.open(scan_path)
    page = doc.new_page(width=595, height=842)  # A4 portrait, points
    margin = 36.0
    y = margin
    page.insert_text((margin, y), f"Accuracy artefact — {case_title}", fontsize=14)
    y += 22
    page.insert_text(
        (margin, y),
        "Machine-generated review overlay. No per-question ground truth exists;",
        fontsize=8,
    )
    y += 11
    page.insert_text(
        (margin, y),
        "this lists the pipeline's own awarded marks/confidence for spot-checking only.",
        fontsize=8,
    )
    y += 20
    header = f"{'question':<12}{'awarded/max':<14}{'band':<9}{'score':<8}{'review?'}"
    page.insert_text((margin, y), header, fontsize=9, fontname="Courier")
    y += 14
    page.draw_line((margin, y), (595 - margin, y))
    y += 10
    for row in rows:
        if y > 842 - margin:
            page = doc.new_page(width=595, height=842)
            y = margin
        line = (
            f"{row.question_id:<12}"
            f"{row.awarded_marks}/{row.maximum_marks:<12}"
            f"{row.confidence_band:<9}"
            f"{row.confidence_score:<8.2f}"
            f"{'YES' if row.needs_teacher_review else '-'}"
        )
        page.insert_text((margin, y), line, fontsize=9)
        y += 13
    doc.save(out_path)
    doc.close()


def run_or_replay_fixture(
    spec: FixtureSpec, *, force: bool = False, settings: Settings | None = None
) -> dict[str, Any]:
    """Run *spec* through the real pipeline, or replay a cached ``run_summary.json``.

    Replay is the default (idempotent, free re-runs); pass ``force=True`` to
    always hit the live pipeline.
    """
    out_dir = REPORT_DIR / spec["fixture_id"]
    summary_path = out_dir / "run_summary.json"
    if summary_path.exists() and not force:
        log(f"[{spec['fixture_id']}] replaying cached artefact at {summary_path}")
        result: dict[str, Any] = json.loads(summary_path.read_text(encoding="utf-8"))
        return result

    settings = settings or Settings()
    gemini_client = GeminiClient(settings)

    log(f"[{spec['fixture_id']}] loading mark scheme ({spec['scheme_source']})")
    mark_scheme = load_mark_scheme(spec, settings)

    log(f"[{spec['fixture_id']}] extracting answers — live Gemini vision call")
    extracted = extract_answers(spec["scan"], mark_scheme, gemini_client=gemini_client)

    log(f"[{spec['fixture_id']}] grading")
    report = grade_paper(mark_scheme, extracted, gemini_client=gemini_client)

    rows = [
        QuestionRow(
            question_id=q.question_id,
            awarded_marks=q.awarded_marks,
            maximum_marks=q.maximum_marks,
            confidence_band=q.confidence.value,
            confidence_score=q.confidence_score,
            needs_teacher_review=q.needs_teacher_review,
        )
        for q in report.correction.questions
    ]
    case = RealPaperCase(
        fixture_id=spec["fixture_id"],
        predicted_total=report.correction.awarded_marks,
        ground_truth_total=spec["ground_truth_total"],
        max_total=spec["max_total"],
        marking_path=spec["marking_path"],
        rows=tuple(rows),
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "raw_run.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
    (out_dir / "per_question.json").write_text(
        json.dumps([asdict(r) for r in rows], indent=2), encoding="utf-8"
    )
    log(f"[{spec['fixture_id']}] rendering annotation overlay")
    render_overlay(spec["scan"], rows, spec["fixture_id"], out_dir / "annotation_overlay.pdf")

    result = {
        "fixture_id": spec["fixture_id"],
        "predicted_total": case.predicted_total,
        "ground_truth_total": case.ground_truth_total,
        "max_total": case.max_total,
        "signed_error": signed_error(case),
        "absolute_error": absolute_error(case),
        "mae": mean_absolute_error([case]),
        "tolerance_marks": tolerance_marks(case.max_total, TOLERANCE_PCT),
        "within_tolerance": within_tolerance(case, TOLERANCE_PCT),
        "confidence_distribution": confidence_distribution(case.rows),
        "review_flagged_marks": review_flagged_marks(case.rows),
        "predicted_grade": report.grade_prediction.grade,
        "grade_confidence": report.grade_prediction.confidence.value,
        "marking_path": spec["marking_path"],
        "num_questions": len(rows),
        "artefact_dir": str(out_dir.relative_to(REPO_ROOT)),
    }
    summary_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    log(
        f"[{spec['fixture_id']}] done: {result['predicted_total']}/{result['max_total']} "
        f"(truth {result['ground_truth_total']}/{result['max_total']}, "
        f"signed_error={result['signed_error']}, within_tolerance={result['within_tolerance']})"
    )
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--force", action="store_true", help="Re-run live even if cached artefacts exist"
    )
    args = ap.parse_args()

    settings = Settings()
    results = [
        run_or_replay_fixture(spec, force=args.force, settings=settings) for spec in FIXTURES
    ]
    print(json.dumps({"fixtures": results}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
