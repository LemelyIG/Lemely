"""Click-based CLI entrypoint for lemely."""
from __future__ import annotations

import json
import os
import platform
import sys
from importlib import metadata as _md
from pathlib import Path
from typing import Any

import click

from lemely import __version__
from lemely.core.analytics import generate_quiz, predict_grade, summarize_weaknesses
from lemely.core.correction import correct_mcq_answers
from lemely.core.schemas import (
    AccuracyReport,
    BatchParseResult,
    CorrectionResult,
    CostEstimate,
    GradePrediction,
    QuizPayload,
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


def _print_result(ctx: click.Context, payload: Any) -> None:
    if ctx.obj.get("json_output", False):
        _dump_json(payload)
        return
    from rich.console import Console

    from lemely.app import renderers

    console = Console()
    if isinstance(payload, AccuracyReport):
        for table in renderers.render_accuracy_report(payload):
            console.print(table)
    elif isinstance(payload, BatchParseResult):
        console.print(renderers.render_batch_result(payload))
    elif isinstance(payload, CostEstimate):
        console.print(renderers.render_cost_estimate(payload))
    elif isinstance(payload, WeaknessReport):
        console.print(renderers.render_weakness_report(payload))
    elif isinstance(payload, GradePrediction):
        console.print(renderers.render_grade_prediction(payload))
    elif isinstance(payload, QuizPayload):
        console.print(renderers.render_quiz_payload(payload))
    else:
        _dump_json(payload)


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


def _safe_version(name: str) -> str | None:
    try:
        return _md.version(name)
    except _md.PackageNotFoundError:
        return None


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
    default=False,
    help="Emit JSON to stdout instead of Rich tables.",
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
@click.pass_context
def estimate_cost_cmd(ctx: click.Context, source_root: str) -> None:
    _print_result(ctx, _estimate_cost(source_root))


@cli.command("parse-mark-schemes")
@click.argument("source_root", type=click.Path(exists=True, file_okay=False))
@click.option("--output-root", type=click.Path(file_okay=False), default=None)
@click.option("--force", is_flag=True)
@click.option("--use-gemini", is_flag=True)
@click.option("--gemini-model", default="gemini-2.5-flash", show_default=True)
@click.option(
    "--on-error",
    type=click.Choice(["continue", "fail"]),
    default="continue",
    show_default=True,
)
@click.pass_context
def parse_mark_schemes_cmd(
    ctx: click.Context,
    source_root: str,
    output_root: str | None,
    force: bool,
    use_gemini: bool,
    gemini_model: str,
    on_error: str,
) -> None:
    parser = (
        GeminiMarkSchemeParser(model=gemini_model, raw_output_dir=output_root)
        if use_gemini
        else None
    )
    result = process_mark_scheme_batch(
        source_root, output_root, force=force, parser=parser
    )
    _print_result(ctx, result)
    failures = [
        item for item in result.items if item.status in {"failed", "invalid_existing"}
    ]
    if failures:
        if on_error == "fail":
            raise click.exceptions.Exit(ParseError.exit_code)
        from lemely.runtime.errors import PartialFailureError

        raise click.exceptions.Exit(PartialFailureError.exit_code)


@cli.command("correct-paper")
@click.option("--mark-scheme", "mark_scheme", required=True, type=click.Path(exists=True, dir_okay=False))
@click.option("--answers", required=True, help="Answer text, JSON object, or path to a file.")
@click.pass_context
def correct_paper_cmd(ctx: click.Context, mark_scheme: str, answers: str) -> None:
    payload = _read_text_or_value(answers)
    _print_result(ctx, _build_accuracy_report(mark_scheme, payload))


@cli.command("predict-grade")
@click.argument("correction_json", type=click.Path(exists=True, dir_okay=False))
@click.pass_context
def predict_grade_cmd(ctx: click.Context, correction_json: str) -> None:
    correction = CorrectionResult.model_validate(_load_json_file(correction_json))
    _print_result(ctx, predict_grade(correction))


@cli.command("detect-weaknesses")
@click.argument("correction_json", type=click.Path(exists=True, dir_okay=False))
@click.pass_context
def detect_weaknesses_cmd(ctx: click.Context, correction_json: str) -> None:
    correction = CorrectionResult.model_validate(_load_json_file(correction_json))
    _print_result(ctx, summarize_weaknesses(correction))


@cli.command("generate-quiz")
@click.argument("weakness_json", type=click.Path(exists=True, dir_okay=False))
@click.option("--count", type=int, default=5, show_default=True)
@click.pass_context
def generate_quiz_cmd(ctx: click.Context, weakness_json: str, count: int) -> None:
    report = WeaknessReport.model_validate(_load_json_file(weakness_json))
    _print_result(ctx, generate_quiz(report, question_count=count))


@cli.command("version")
@click.pass_context
def version_cmd(ctx: click.Context) -> None:
    payload = {
        "lemely": __version__,
        "python": platform.python_version(),
        "dependencies": {
            name: ver
            for name in ("pydantic", "click", "structlog", "google-genai", "PyMuPDF")
            if (ver := _safe_version(name)) is not None
        },
    }
    _print_result(ctx, payload)


@cli.command("doctor")
@click.option("--no-network", is_flag=True, help="Skip the live Gemini ping.")
@click.pass_context
def doctor_cmd(ctx: click.Context, no_network: bool) -> None:
    from lemely.runtime.config import load_settings
    from lemely.runtime.errors import ConfigError

    checks: list[dict[str, object]] = []

    def record(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    try:
        settings = load_settings(
            toml_path=Path(ctx.obj["config_path"]) if ctx.obj.get("config_path") else None
        )
        record("config_loads", True)
    except Exception as exc:  # noqa: BLE001
        record("config_loads", False, str(exc))
        _print_result(ctx, {"all_passed": False, "checks": checks})
        raise click.exceptions.Exit(ConfigError.exit_code) from exc

    # Accept GEMINI_API_KEY (standard) or LEMELY_GEMINI_API_KEY (prefixed).
    has_key = bool(
        (settings.gemini_api_key is not None) or os.environ.get("GEMINI_API_KEY")
    )
    record("gemini_api_key", has_key)

    record(
        "sources_dir_readable",
        settings.paths.sources_dir.exists() and os.access(settings.paths.sources_dir, os.R_OK),
        detail=str(settings.paths.sources_dir),
    )
    out = settings.paths.output_dir
    try:
        out.mkdir(parents=True, exist_ok=True)
        record("output_dir_writable", os.access(out, os.W_OK), detail=str(out))
    except OSError as exc:
        record("output_dir_writable", False, str(exc))

    cache = settings.paths.cache_dir
    try:
        cache.mkdir(parents=True, exist_ok=True)
        record("cache_dir_writable", os.access(cache, os.W_OK), detail=str(cache))
    except OSError as exc:
        record("cache_dir_writable", False, str(exc))

    try:
        import gradio  # noqa: F401

        record("gradio_extra_installed", True)
    except ModuleNotFoundError:
        record(
            "gradio_extra_installed",
            False,
            "lemely ui will not work; install with `pip install lemely[ui]`",
        )

    if not no_network:
        record(
            "gemini_reachable",
            False,
            "live ping not yet implemented — pass --no-network to skip",
        )

    fatal_checks = [c for c in checks if c["name"] != "gradio_extra_installed"]
    all_passed = all(c["ok"] for c in fatal_checks)

    _print_result(ctx, {"all_passed": all_passed, "checks": checks})

    if not all_passed:
        raise click.exceptions.Exit(ConfigError.exit_code)


def main(argv: list[str] | None = None) -> int:
    """Top-level entrypoint used by main.py and console-script."""
    import structlog

    log = structlog.get_logger().bind(component="cli")
    try:
        cli.main(args=argv, standalone_mode=False, prog_name="lemely")
        return 0
    except click.UsageError as exc:
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
