"""Click-based CLI entrypoint for lemely."""

from __future__ import annotations

import json
import os
import platform
import sys
from importlib import metadata as _md
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

if TYPE_CHECKING:
    from lemely.runtime.config import Settings

import click

from lemely import __version__
from lemely.core.analytics import generate_quiz, predict_grade, summarize_weaknesses
from lemely.core.correction import correct_mcq_answers
from lemely.core.schemas import (
    AccuracyReport,
    BatchParseResult,
    CorrectionResult,
    CostEstimate,
    ExtractedAnswers,
    GradePrediction,
    QuizPayload,
    SubjectResult,
    WeaknessReport,
)
from lemely.io.mark_schemes import index_source_library, process_mark_scheme_batch
from lemely.runtime.errors import LemelyError, ParseError
from lemely.runtime.logging import configure_logging


def _dump_json(payload: object) -> None:
    data = payload.model_dump(mode="json") if hasattr(payload, "model_dump") else payload
    click.echo(json.dumps(data, indent=2, sort_keys=True))


def _print_result(ctx: click.Context, payload: object) -> None:
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
    elif isinstance(payload, ExtractedAnswers):
        console.print(renderers.render_extracted_answers(payload))
    elif isinstance(payload, SubjectResult):
        for table in renderers.render_subject_result(payload):
            console.print(table)
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


def _load_json_file(path: str | Path) -> object:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ParseError(f"Invalid JSON in {path}: {exc}") from exc


def _get_settings(ctx: click.Context) -> Settings:
    from lemely.runtime.config import load_settings

    cfg = ctx.obj.get("config_path")
    return load_settings(toml_path=Path(cfg) if cfg else None)


def _estimate_cost(source_root: str | Path) -> CostEstimate:
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
    configure_logging(
        level=cast("Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']", log_level),
        fmt=cast("Literal['auto', 'json', 'console']", log_format),
    )
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
@click.option("--gemini-model", default=None,
              help="Override gemini model (default: settings.gemini.model)")
@click.option(
    "--on-error",
    type=click.Choice(["continue", "fail"]),
    default="continue", show_default=True,
)
@click.pass_context
def parse_mark_schemes_cmd(
    ctx: click.Context,
    source_root: str,
    output_root: str | None,
    force: bool,
    use_gemini: bool,
    gemini_model: str | None,
    on_error: str,
) -> None:
    from lemely.io.gemini import GeminiClient
    from lemely.io.parsers import GeminiMarkSchemeParser
    from lemely.runtime.errors import PartialFailureError

    parser = None
    if use_gemini:
        settings = _get_settings(ctx)
        if gemini_model:
            settings = settings.model_copy(
                update={"gemini": settings.gemini.model_copy(update={"model": gemini_model})}
            )
        parser = GeminiMarkSchemeParser(GeminiClient(settings))

    result = process_mark_scheme_batch(source_root, output_root, force=force, parser=parser)
    _print_result(ctx, result)
    failures = [item for item in result.items if item.status in {"failed", "invalid_existing"}]
    if failures:
        if on_error == "fail":
            raise click.exceptions.Exit(ParseError.exit_code)
        raise click.exceptions.Exit(PartialFailureError.exit_code)


@cli.command("correct-paper")
@click.option("--mark-scheme", "mark_scheme", required=True,
              type=click.Path(exists=True, dir_okay=False))
@click.option("--answers", required=True,
              help="Answer JSON object, ExtractedAnswers JSON file path, or simple text.")
@click.option("--mcq-only", is_flag=True,
              help="Skip AI marking for non-MCQ questions (they'll be marker_source=missing).")
@click.option("--on-error", type=click.Choice(["continue", "fail"]),
              default="fail", show_default=True)
@click.pass_context
def correct_paper_cmd(
    ctx: click.Context,
    mark_scheme: str,
    answers: str,
    mcq_only: bool,
    on_error: str,
) -> None:
    import json as _json

    from lemely.core.loose_schemas import MarkScheme
    from lemely.io.correction_ai import correct_paper as hybrid_correct_paper
    from lemely.io.gemini import GeminiClient

    ms = MarkScheme.model_validate(_load_json_file(mark_scheme))

    payload = _read_text_or_value(answers)
    try:
        ea = ExtractedAnswers.model_validate_json(payload)
        extracted: object = ea
    except Exception:
        try:
            ea_dict = _json.loads(payload)
            if isinstance(ea_dict, dict):
                extracted = ea_dict
            else:
                raise ValueError("Answers JSON must be an object.")
        except Exception:
            from lemely.core.correction import parse_answer_input
            extracted = parse_answer_input(payload)

    settings = _get_settings(ctx)
    client = None if mcq_only else GeminiClient(settings)

    correction = hybrid_correct_paper(
        mark_scheme=ms,
        extracted_answers=extracted,  # type: ignore[arg-type]
        gemini_client=client,
        mcq_only=mcq_only,
    )
    report = AccuracyReport(
        correction=correction,
        weaknesses=summarize_weaknesses(correction),
        grade_prediction=predict_grade(correction),
    )
    _print_result(ctx, report)


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
    except Exception as exc:
        record("config_loads", False, str(exc))
        _print_result(ctx, {"all_passed": False, "checks": checks})
        raise click.exceptions.Exit(ConfigError.exit_code) from exc

    # Accept GEMINI_API_KEY (standard) or LEMELY_GEMINI_API_KEY (prefixed).
    has_key = bool((settings.gemini_api_key is not None) or os.environ.get("GEMINI_API_KEY"))
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


@cli.command("extract-answers")
@click.option("--mark-scheme", "mark_scheme", required=True,
              type=click.Path(exists=True, dir_okay=False))
@click.option("--scan", required=True, type=click.Path(exists=True, dir_okay=False),
              help="Scanned student paper (PDF, PNG, or JPG).")
@click.option("--on-error", type=click.Choice(["continue", "fail"]),
              default="fail", show_default=True)
@click.pass_context
def extract_answers_cmd(
    ctx: click.Context, mark_scheme: str, scan: str, on_error: str,
) -> None:
    from lemely.core.loose_schemas import MarkScheme
    from lemely.io.answer_extraction import GeminiAnswerExtractor
    from lemely.io.gemini import GeminiClient

    settings = _get_settings(ctx)
    ms = MarkScheme.model_validate(_load_json_file(mark_scheme))
    extractor = GeminiAnswerExtractor(GeminiClient(settings))
    result = extractor(scan_path=Path(scan), mark_scheme=ms)
    _print_result(ctx, result)


@cli.command("aggregate-subject")
@click.argument("correction_jsons", nargs=-1, required=True,
                type=click.Path(exists=True, dir_okay=False))
@click.option("--on-error", type=click.Choice(["continue", "fail"]),
              default="fail", show_default=True)
@click.pass_context
def aggregate_subject_cmd(
    ctx: click.Context, correction_jsons: tuple[str, ...], on_error: str,
) -> None:
    from lemely.io.subject import aggregate_subject

    papers = [
        CorrectionResult.model_validate(_load_json_file(p))
        for p in correction_jsons
    ]
    _print_result(ctx, aggregate_subject(papers))


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


@cli.command("ui")
@click.option("--host", default=None)
@click.option("--port", default=None, type=int)
@click.pass_context
def ui_cmd(ctx: click.Context, host: str | None, port: int | None) -> None:
    from lemely.app.gradio_app import launch
    from lemely.runtime.config import GradioSettings

    settings = _get_settings(ctx)
    if host is not None or port is not None:
        cur = settings.gradio
        settings = settings.model_copy(update={"gradio": GradioSettings(
            host=host or cur.host, port=port or cur.port,
            max_file_size_mb=cur.max_file_size_mb,
        )})
    launch(settings)


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
    except Exception as exc:
        log.exception("unexpected_error", error_type=type(exc).__name__)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
