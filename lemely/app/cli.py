from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from lemely.core.analytics import generate_quiz, predict_grade, summarize_weaknesses
from lemely.core.correction import correct_mcq_answers
from lemely.io.mark_schemes import index_source_library, process_mark_scheme_batch
from lemely.io.parsers import GeminiMarkSchemeParser
from lemely.core.schemas import AccuracyReport, CorrectionResult, CostEstimate, WeaknessReport


def _dump_json(payload: Any) -> None:
    if hasattr(payload, "model_dump"):
        data = payload.model_dump(mode="json")
    else:
        data = payload
    print(json.dumps(data, indent=2, sort_keys=True))


def _read_text_or_value(value: str) -> str:
    path = Path(value)
    if path.exists():
        return path.read_text(encoding="utf-8")
    return value


def _load_json_file(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def estimate_cost(source_root: str | Path) -> CostEstimate:
    root = Path(source_root)
    entries = index_source_library(root)
    cached = sum(1 for entry in entries if entry.source_path.with_suffix(".json").exists())
    return CostEstimate(
        source_root=str(root),
        mark_scheme_pdfs=len(entries),
        cached_json=cached,
        needs_parsing=len(entries) - cached,
        estimated_pdf_pages=None,
        token_policy=(
            "Reuse structured JSON when present; batch-parse PDFs only during migration; "
            "during correction send question-level mark-scheme slices only."
        ),
    )


def build_accuracy_report(mark_scheme_path: str | Path, answers: str) -> AccuracyReport:
    scheme_json = Path(mark_scheme_path).read_text(encoding="utf-8")
    correction = correct_mcq_answers(scheme_json, answers)
    weaknesses = summarize_weaknesses(correction)
    grade = predict_grade(correction)
    return AccuracyReport(
        correction=correction,
        weaknesses=weaknesses,
        grade_prediction=grade,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lemely",
        description="Accuracy-first educational assessment MVP CLI.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    estimate = sub.add_parser("estimate-cost", help="Estimate mark-scheme migration work.")
    estimate.add_argument("source_root")

    parse = sub.add_parser("parse-mark-schemes", help="Validate or batch parse mark-scheme PDFs.")
    parse.add_argument("source_root")
    parse.add_argument("--output-root", default=None)
    parse.add_argument("--force", action="store_true")
    parse.add_argument("--use-gemini", action="store_true")
    parse.add_argument("--gemini-model", default="gemini-2.5-flash")

    correct = sub.add_parser("correct-paper", help="Correct MCQ answers against structured JSON.")
    correct.add_argument("--mark-scheme", required=True)
    correct.add_argument("--answers", required=True, help="Answer text, JSON object, or path to a file.")

    grade = sub.add_parser("predict-grade", help="Predict grade from a correction JSON file.")
    grade.add_argument("correction_json")

    weaknesses = sub.add_parser("detect-weaknesses", help="Summarize weaknesses from correction JSON.")
    weaknesses.add_argument("correction_json")

    quiz = sub.add_parser("generate-quiz", help="Generate deterministic quiz prompts from weakness JSON.")
    quiz.add_argument("weakness_json")
    quiz.add_argument("--count", type=int, default=5)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "estimate-cost":
        _dump_json(estimate_cost(args.source_root))
        return 0

    if args.command == "parse-mark-schemes":
        parser = (
            GeminiMarkSchemeParser(model=args.gemini_model, raw_output_dir=args.output_root)
            if args.use_gemini
            else None
        )
        _dump_json(
            process_mark_scheme_batch(
                args.source_root,
                args.output_root,
                force=args.force,
                parser=parser,
            )
        )
        return 0

    if args.command == "correct-paper":
        answers = _read_text_or_value(args.answers)
        _dump_json(build_accuracy_report(args.mark_scheme, answers))
        return 0

    if args.command == "predict-grade":
        correction = CorrectionResult.model_validate(_load_json_file(args.correction_json))
        _dump_json(predict_grade(correction))
        return 0

    if args.command == "detect-weaknesses":
        correction = CorrectionResult.model_validate(_load_json_file(args.correction_json))
        _dump_json(summarize_weaknesses(correction))
        return 0

    if args.command == "generate-quiz":
        weakness_report = WeaknessReport.model_validate(_load_json_file(args.weakness_json))
        _dump_json(generate_quiz(weakness_report, question_count=args.count))
        return 0

    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
