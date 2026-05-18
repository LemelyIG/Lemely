"""Click-based CLI entrypoint for lemely."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import click

from lemely import __version__
from lemely.core.analytics import generate_quiz, predict_grade, summarize_weaknesses
from lemely.core.correction import correct_mcq_answers
from lemely.core.schemas import (
    AccuracyReport,
    CorrectionResult,
    CostEstimate,
    WeaknessReport,
)
from lemely.io.mark_schemes import index_source_library, process_mark_scheme_batch
from lemely.io.parsers import GeminiMarkSchemeParser
from lemely.runtime.errors import LemelyError, ParseError
from lemely.runtime.logging import configure_logging


def _dump_json(payload: Any) -> None:
    if hasattr(payload, "model_dump"):
        data = payload.model_dump(mode="json")
    else:
        data = payload
    click.echo(json.dumps(data, indent=2, sort_keys=True))


def _read_text_or_value(value: str) -> str:
    path = Path(value)
    if path.exists():
        return path.read_text(encoding="utf-8")
    return value


def _load_json_file(path: str | Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ParseError(f"Invalid JSON in {path}: {exc}") from exc


def _estimate_cost(source_root: str | Path) -> CostEstimate:
    root = Path(source_root)
    entries = index_source_library(root)
    cached = sum(
        1 for entry in entries if entry.source_path.with_suffix(".json").exists()
    )
    return CostEstimate(
        source_root=str(root),
        mark_scheme_pdfs=len(entries),
        cached_json=cached,
        needs_parsing=len(entries) - cached,
        estimated_pdf_pages=None,
        token_policy=(
            "Reuse structured JSON when present; batch-parse PDFs only during "
            "migration; during correction send question-level mark-scheme slices only."
        ),
    )


def _build_accuracy_report(mark_scheme_path: str | Path, answers: str) -> AccuracyReport:
    scheme_json = Path(mark_scheme_path).read_text(encoding="utf-8")
    correction = correct_mcq_answers(scheme_json, answers)
    weaknesses = summarize_weaknesses(correction)
    grade = predict_grade(correction)
    return AccuracyReport(
        correction=correction,
        weaknesses=weaknesses,
        grade_prediction=grade,
    )


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, "-V", "--version", prog_name="lemely")
@click.option("--config", "config_path", type=click.Path(dir_okay=False), default=None)
@click.option(
    "--log-format",
    type=click.Choice(["auto", "json", "console"]),
    default="auto",
    show_default=True,
)
@click.option(
    "--log-level",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"]),
    default="INFO",
    show_default=True,
)
@click.option("-v", "--verbose", is_flag=True, help="Shortcut for --log-level DEBUG.")
@click.option("-q", "--quiet", is_flag=True, help="Shortcut for --log-level WARNING.")
@click.option(
    "--json/--no-json",
    "json_output",
    default=True,
    help="Emit JSON to stdout (default for Phase 1; human renderer arrives in Task 10).",
)
@click.pass_context
def cli(
    ctx: click.Context,
    config_path: str | None,
    log_format: str,
    log_level: str,
    verbose: bool,
    quiet: bool,
    json_output: bool,
) -> None:
    """Accuracy-first educational assessment CLI."""
    if verbose and quiet:
        raise click.UsageError("--verbose and --quiet are mutually exclusive.")
    if verbose:
        log_level = "DEBUG"
    elif quiet:
        log_level = "WARNING"
    configure_logging(level=log_level, fmt=log_format)
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config_path
    ctx.obj["json_output"] = json_output


@cli.command("estimate-cost")
@click.argument("source_root", type=click.Path(exists=True, file_okay=False))
def estimate_cost_cmd(source_root: str) -> None:
    _dump_json(_estimate_cost(source_root))


@cli.command("parse-mark-schemes")
@click.argument("source_root", type=click.Path(exists=True, file_okay=False))
@click.option("--output-root", type=click.Path(file_okay=False), default=None)
@click.option("--force", is_flag=True)
@click.option("--use-gemini", is_flag=True)
@click.option("--gemini-model", default="gemini-2.5-flash", show_default=True)
def parse_mark_schemes_cmd(
    source_root: str,
    output_root: str | None,
    force: bool,
    use_gemini: bool,
    gemini_model: str,
) -> None:
    parser = (
        GeminiMarkSchemeParser(model=gemini_model, raw_output_dir=output_root)
        if use_gemini
        else None
    )
    _dump_json(
        process_mark_scheme_batch(
            source_root, output_root, force=force, parser=parser
        )
    )


@cli.command("correct-paper")
@click.option("--mark-scheme", "mark_scheme", required=True, type=click.Path(exists=True, dir_okay=False))
@click.option("--answers", required=True, help="Answer text, JSON object, or path to a file.")
def correct_paper_cmd(mark_scheme: str, answers: str) -> None:
    payload = _read_text_or_value(answers)
    _dump_json(_build_accuracy_report(mark_scheme, payload))


@cli.command("predict-grade")
@click.argument("correction_json", type=click.Path(exists=True, dir_okay=False))
def predict_grade_cmd(correction_json: str) -> None:
    correction = CorrectionResult.model_validate(_load_json_file(correction_json))
    _dump_json(predict_grade(correction))


@cli.command("detect-weaknesses")
@click.argument("correction_json", type=click.Path(exists=True, dir_okay=False))
def detect_weaknesses_cmd(correction_json: str) -> None:
    correction = CorrectionResult.model_validate(_load_json_file(correction_json))
    _dump_json(summarize_weaknesses(correction))


@cli.command("generate-quiz")
@click.argument("weakness_json", type=click.Path(exists=True, dir_okay=False))
@click.option("--count", type=int, default=5, show_default=True)
def generate_quiz_cmd(weakness_json: str, count: int) -> None:
    report = WeaknessReport.model_validate(_load_json_file(weakness_json))
    _dump_json(generate_quiz(report, question_count=count))


def main(argv: list[str] | None = None) -> int:
    """Top-level entrypoint used by main.py and console-script."""
    import structlog

    log = structlog.get_logger().bind(component="cli")
    try:
        cli.main(args=argv, standalone_mode=False, prog_name="lemely")
        return 0
    except click.UsageError as exc:
        # Click prints its own message; map to exit code 2.
        click.echo(f"Error: {exc.format_message()}", err=True)
        return 2
    except click.exceptions.Exit as exc:
        return int(exc.exit_code)
    except LemelyError as exc:
        log.error(
            "lemely_error",
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return exc.exit_code
    except KeyboardInterrupt:
        log.warning("interrupted")
        return 130
    except Exception as exc:  # noqa: BLE001
        log.exception("unexpected_error", error_type=type(exc).__name__)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
