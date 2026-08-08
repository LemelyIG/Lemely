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
from lemely.core.analytics import (
    aggregate_weaknesses_from_history,
    compare_performance,
    generate_quiz,
    predict_grade,
    summarize_weaknesses,
)
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


def _load_correction_result(path: str | Path) -> CorrectionResult:
    """Load a CorrectionResult from a file that may be a bare result or an AccuracyReport."""
    data = _load_json_file(path)
    if isinstance(data, dict) and "correction" in data:
        data = data["correction"]
    return CorrectionResult.model_validate(data)


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
@click.option(
    "--gemini-model", default=None, help="Override gemini model (default: settings.gemini.model)"
)
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
    gemini_model: str | None,
    on_error: str,
) -> None:
    from lemely.io.det import DeterministicMarkSchemeParser
    from lemely.io.gemini import GeminiClient
    from lemely.io.parsers import ChainedMarkSchemeParser, GeminiMarkSchemeParser
    from lemely.runtime.errors import PartialFailureError

    settings = _get_settings(ctx)
    det_parser = DeterministicMarkSchemeParser(cfg=settings.det_parser)
    if use_gemini:
        if gemini_model:
            settings = settings.model_copy(
                update={"gemini": settings.gemini.model_copy(update={"model": gemini_model})}
            )
        gemini = GeminiMarkSchemeParser(GeminiClient(settings))
        parser = ChainedMarkSchemeParser(primary=det_parser, fallback=gemini)
    else:
        parser = det_parser  # type: ignore[assignment]

    result = process_mark_scheme_batch(source_root, output_root, force=force, parser=parser)
    _print_result(ctx, result)
    failures = [
        item
        for item in result.items
        if item.status in {"failed", "invalid_existing", "transient_failed"}
    ]
    if failures:
        if on_error == "fail":
            raise click.exceptions.Exit(ParseError.exit_code)
        raise click.exceptions.Exit(PartialFailureError.exit_code)


@cli.command("correct-paper")
@click.option(
    "--mark-scheme", "mark_scheme", required=True, type=click.Path(exists=True, dir_okay=False)
)
@click.option(
    "--answers",
    required=True,
    help="Answer JSON object, ExtractedAnswers JSON file path, or simple text.",
)
@click.option(
    "--mcq-only",
    is_flag=True,
    help="Skip AI marking for non-MCQ questions (they'll be marker_source=missing).",
)
@click.option(
    "--on-error", type=click.Choice(["continue", "fail"]), default="fail", show_default=True
)
@click.option("--student-id", default=None, help="Student ID for history recording.")
@click.option(
    "--record", is_flag=True, help="Append result to student history (requires --student-id)."
)
@click.pass_context
def correct_paper_cmd(
    ctx: click.Context,
    mark_scheme: str,
    answers: str,
    mcq_only: bool,
    on_error: str,
    student_id: str | None,
    record: bool,
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
    from lemely.io.grade_boundaries import GradeBoundaryStore

    store = GradeBoundaryStore()
    boundaries, boundary_source = store.resolve(correction.metadata)
    grade_pred = predict_grade(correction, boundaries=boundaries, boundary_source=boundary_source)
    weaknesses = summarize_weaknesses(correction)
    report = AccuracyReport(
        correction=correction,
        weaknesses=weaknesses,
        grade_prediction=grade_pred,
    )

    if record:
        if not student_id:
            raise click.UsageError("--student-id is required when --record is set.")
        import datetime

        from lemely.core.history import PaperRecord
        from lemely.io.history_store import HistoryStore

        settings = _get_settings(ctx)
        history_store = HistoryStore(settings.paths.output_dir / "history")
        history_store.append(
            student_id,
            PaperRecord(
                student_id=student_id,
                metadata=correction.metadata,
                awarded_marks=correction.awarded_marks,
                maximum_marks=correction.maximum_marks,
                percentage=grade_pred.percentage,
                grade=grade_pred.grade,
                weak_areas=weaknesses.weak_areas,
                recorded_at=datetime.datetime.now(datetime.UTC).isoformat(),
            ),
        )

    _print_result(ctx, report)


@cli.command("predict-grade")
@click.argument("correction_json", type=click.Path(exists=True, dir_okay=False))
@click.pass_context
def predict_grade_cmd(ctx: click.Context, correction_json: str) -> None:
    from lemely.io.grade_boundaries import GradeBoundaryStore

    correction = _load_correction_result(correction_json)
    store = GradeBoundaryStore()
    boundaries, boundary_source = store.resolve(correction.metadata)
    _print_result(
        ctx, predict_grade(correction, boundaries=boundaries, boundary_source=boundary_source)
    )


@cli.command("compare-performance")
@click.option("--student-id", required=True, help="Student ID to look up in the history store.")
@click.pass_context
def compare_performance_cmd(ctx: click.Context, student_id: str) -> None:
    from lemely.io.history_store import HistoryStore

    settings = _get_settings(ctx)
    store = HistoryStore(settings.paths.output_dir / "history")
    history = store.load(student_id)
    if not history.records:
        raise click.UsageError(f"No history records found for student '{student_id}'.")
    latest = history.records[-1]
    _print_result(ctx, compare_performance(history, latest))


@cli.command("detect-weaknesses")
@click.argument("correction_json", type=click.Path(exists=True, dir_okay=False))
@click.pass_context
def detect_weaknesses_cmd(ctx: click.Context, correction_json: str) -> None:
    correction = _load_correction_result(correction_json)
    _print_result(ctx, summarize_weaknesses(correction))


@cli.command("generate-quiz")
@click.argument("weakness_json", type=click.Path(exists=True, dir_okay=False))
@click.option("--count", type=int, default=5, show_default=True)
@click.option(
    "--use-ai", is_flag=True, help="Generate real questions via Gemini (requires API key)."
)
@click.option(
    "--subject-code", default=None, help="CAIE subject code (e.g. 0625). Required with --use-ai."
)
@click.pass_context
def generate_quiz_cmd(
    ctx: click.Context, weakness_json: str, count: int, use_ai: bool, subject_code: str | None
) -> None:
    report = WeaknessReport.model_validate(_load_json_file(weakness_json))
    if use_ai:
        if not subject_code:
            raise click.UsageError("--subject-code is required when --use-ai is set.")
        from lemely.io.gemini import GeminiClient
        from lemely.io.question_generation import QuestionGenerator

        client = GeminiClient(_get_settings(ctx))
        _print_result(
            ctx, QuestionGenerator(client).generate(report, subject_code=subject_code, count=count)
        )
    else:
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
        if not has_key:
            record(
                "gemini_reachable",
                False,
                "no API key configured; set GEMINI_API_KEY or pass --no-network to skip",
            )
        else:
            from lemely.io.gemini import GeminiClient

            try:
                GeminiClient(settings).check_reachable()
                record("gemini_reachable", True, "models.list() ok")
            except Exception as exc:
                # Any failure (auth, network, SDK) is a reachability failure to report.
                record("gemini_reachable", False, str(exc))

    fatal_checks = [c for c in checks if c["name"] != "gradio_extra_installed"]
    all_passed = all(c["ok"] for c in fatal_checks)

    _print_result(ctx, {"all_passed": all_passed, "checks": checks})

    if not all_passed:
        raise click.exceptions.Exit(ConfigError.exit_code)


@cli.command("extract-answers")
@click.option(
    "--mark-scheme", "mark_scheme", required=True, type=click.Path(exists=True, dir_okay=False)
)
@click.option(
    "--scan",
    required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Scanned student paper (PDF, PNG, or JPG).",
)
@click.option(
    "--on-error", type=click.Choice(["continue", "fail"]), default="fail", show_default=True
)
@click.option(
    "--detect-metadata",
    is_flag=True,
    help="Derive ExamMetadata from scan via Gemini vision and cross-check against mark scheme.",
)
@click.pass_context
def extract_answers_cmd(
    ctx: click.Context,
    mark_scheme: str,
    scan: str,
    on_error: str,
    detect_metadata: bool,
) -> None:
    from lemely.core.loose_schemas import MarkScheme
    from lemely.io.answer_extraction import GeminiAnswerExtractor
    from lemely.io.gemini import GeminiClient

    settings = _get_settings(ctx)
    client = GeminiClient(settings)
    ms = MarkScheme.model_validate(_load_json_file(mark_scheme))

    if detect_metadata and ms.metadata is not None:
        from lemely.core.schemas import ExamMetadata
        from lemely.io.scan_metadata import ScanMetadataExtractor, cross_check_metadata

        scan_meta = ScanMetadataExtractor(client)(Path(scan))
        raw_month = ms.metadata.session_month
        ms_exam_meta = ExamMetadata(
            subject_code=ms.metadata.subject_code or "",
            paper_number=ms.metadata.paper_number or 0,
            paper_variant=ms.metadata.paper_variant or 0,
            session_month=raw_month.value if raw_month is not None else "May/June",
            session_year=ms.metadata.session_year,
        )
        cross_check_metadata(scan_meta, ms_exam_meta)

    extractor = GeminiAnswerExtractor(client)
    result = extractor(scan_path=Path(scan), mark_scheme=ms)
    _print_result(ctx, result)


@cli.command("study-plan")
@click.option("--student-id", required=True, help="Student ID to load history for.")
@click.option("--weekly-hours", type=float, required=True, help="Hours available per week.")
@click.option(
    "--profile",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help="Optional StudentProfile JSON file.",
)
@click.option("--use-ai", is_flag=True, help="Enrich plan with AI narrative (requires API key).")
@click.pass_context
def study_plan_cmd(
    ctx: click.Context,
    student_id: str,
    weekly_hours: float,
    profile: str | None,
    use_ai: bool,
) -> None:
    from lemely.core.study import StudentProfile
    from lemely.core.study_plan import build_study_plan
    from lemely.io.history_store import HistoryStore

    settings = _get_settings(ctx)
    store = HistoryStore(settings.paths.output_dir / "history")
    history = store.load(student_id)
    profile_obj = StudentProfile.model_validate(_load_json_file(profile)) if profile else None
    weaknesses = aggregate_weaknesses_from_history(history)
    plan = build_study_plan(profile_obj, weaknesses, weekly_hours=weekly_hours)
    if use_ai:
        from lemely.io.gemini import GeminiClient
        from lemely.io.study_plan_ai import StudyPlanNarrator

        plan = StudyPlanNarrator(GeminiClient(settings)).narrate(plan)
    _print_result(ctx, plan)


@cli.command("check-integrity")
@click.option(
    "--answers",
    "answers_json",
    required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="ExtractedAnswers JSON file.",
)
@click.option(
    "--mark-scheme", "mark_scheme", required=True, type=click.Path(exists=True, dir_okay=False)
)
@click.pass_context
def check_integrity_cmd(ctx: click.Context, answers_json: str, mark_scheme: str) -> None:
    from lemely.core.integrity_schemas import IntegrityReport
    from lemely.core.loose_schemas import MarkScheme
    from lemely.core.plagiarism import PlagiarismChecker

    settings = _get_settings(ctx)
    ea = ExtractedAnswers.model_validate(_load_json_file(answers_json))
    ms = MarkScheme.model_validate(_load_json_file(mark_scheme))
    checker = PlagiarismChecker(settings.integrity.plagiarism_threshold)

    answer_map: dict[str, str] = {str(a.question_id): (a.answer or "") for a in ea.answers}
    expected_map: dict[str, str] = {}
    for q in ms.questions:
        key = str(q.id)
        points = q.answer_points or []
        expected_map[key] = " ".join(str(p) for p in points)

    findings = []
    for qid, student_text in answer_map.items():
        expected_text = expected_map.get(qid, "")
        if student_text and expected_text:
            findings.append(checker.check(qid, student_text, expected_text))

    report = IntegrityReport(
        findings=findings,
        needs_teacher_review=any(f.flagged for f in findings),
    )
    _print_result(ctx, report)


@cli.command("teacher-quiz")
@click.option("--subject", required=True, help="CAIE subject code (e.g. 0625).")
@click.option("--topics", multiple=True, help="Target topics (repeat for multiple).")
@click.option(
    "--count", type=int, default=10, show_default=True, help="Number of questions to build."
)
@click.pass_context
def teacher_quiz_cmd(
    ctx: click.Context,
    subject: str,
    topics: tuple[str, ...],
    count: int,
) -> None:
    from lemely.core.schemas import WeakArea, WeaknessReport
    from lemely.io.gemini import GeminiClient
    from lemely.io.question_generation import QuestionGenerator
    from lemely.io.teacher_quiz import TeacherQuizBuilder

    settings = _get_settings(ctx)
    client = GeminiClient(settings)
    generator = QuestionGenerator(client)
    weak_areas = [
        WeakArea(topic=t, lost_marks=1, maximum_marks=1, accuracy=0.0, question_ids=[])
        for t in topics
    ]
    weaknesses = WeaknessReport(weak_areas=weak_areas)
    builder = TeacherQuizBuilder(generator)
    _print_result(ctx, builder.build(subject, weaknesses, count=count, topics=list(topics)))


@cli.group("question-bank")
def question_bank_group() -> None:
    """Question-bank survey and generated-question import (P3.5 chunk B)."""


@question_bank_group.command("survey-past-papers")
@click.pass_context
def question_bank_survey_cmd(ctx: click.Context) -> None:
    """Report how many bank-ready questions exist in the parsed mark-scheme corpus.

    Reporting only: docs/quiz-model.md §2 and BUILD/DECISIONS.md D3.7 record
    that persisting past-paper questions is blocked on a question-paper stem
    extractor that does not exist yet, so this command never writes to the
    question bank. It always prints the real counts, including the zeros.
    """
    from lemely.db.question_bank_repo import survey_past_paper_questions
    from lemely.db.session import get_sessionmaker

    settings = _get_settings(ctx)
    report = survey_past_paper_questions(get_sessionmaker(settings))

    if ctx.obj.get("json_output", False):
        _dump_json(
            {
                "markSchemesScanned": report.mark_schemes_scanned,
                "parseFailures": report.parse_failures,
                "leafQuestionsSeen": report.leaf_questions_seen,
                "produced": report.produced,
                "skippedNoPrompt": report.skipped_no_prompt,
                "topicHintsPresent": report.topic_hints_present,
                "bandDistribution": report.band_distribution,
                "explanation": report.explanation(),
            }
        )
        return

    click.echo(f"Mark schemes scanned: {report.mark_schemes_scanned}")
    if report.parse_failures:
        click.echo(f"Parse failures (skipped, malformed payload): {report.parse_failures}")
    click.echo(f"Leaf questions seen: {report.leaf_questions_seen}")
    click.echo(f"Produced: {report.produced}")
    click.echo(f"Skipped (no prompt text): {report.skipped_no_prompt}")
    click.echo(f"Topic hints present: {report.topic_hints_present}")
    click.echo(f"Band distribution (inferred from marks): {report.band_distribution}")
    click.echo("")
    click.echo(report.explanation())


@question_bank_group.command("classify-topics")
@click.option("--subject", default=None, help="Restrict to one subject code, e.g. 0625.")
@click.option(
    "--reclassify",
    is_flag=True,
    help="Re-derive rows that already carry a topic (use after editing the taxonomy).",
)
@click.option("--dry-run", is_flag=True, help="Report what would change without writing.")
@click.pass_context
def question_bank_classify_topics_cmd(
    ctx: click.Context, subject: str | None, reclassify: bool, dry_run: bool
) -> None:
    """Backfill ``question_bank.topic`` from the bundled CAIE syllabus taxonomies (P4.2).

    Deterministic and free: keyword scoring against
    ``lemely/data/syllabus_topics.json``, no Gemini call. Idempotent unless
    ``--reclassify`` is passed.

    Only ``high``- and ``medium``-confidence matches are written; ``low`` ones
    are counted and discarded (``lemely.core.topics.WRITABLE_BANDS`` explains
    why). The printed counters are the honest yield, zeros included.
    """
    from lemely.db.question_bank_repo import classify_bank_topics
    from lemely.db.session import get_sessionmaker

    settings = _get_settings(ctx)
    report = classify_bank_topics(
        get_sessionmaker(settings),
        subject_code=subject,
        reclassify=reclassify,
        dry_run=dry_run,
    )

    if ctx.obj.get("json_output", False):
        _dump_json(
            {
                "rowsExamined": report.rows_examined,
                "alreadyClassified": report.already_classified,
                "assigned": report.assigned,
                "skippedLowConfidence": report.skipped_low_confidence,
                "unclassified": report.unclassified,
                "noTaxonomy": report.no_taxonomy,
                "coverage": round(report.coverage, 4),
                "bandDistribution": report.band_distribution,
                "labelDistribution": report.label_distribution,
                "dryRun": dry_run,
            }
        )
        return

    if dry_run:
        click.echo("DRY RUN — nothing written.")
    click.echo(f"Rows examined: {report.rows_examined}")
    click.echo(f"Already classified (left alone): {report.already_classified}")
    click.echo(f"Assigned: {report.assigned}")
    click.echo(f"Skipped (low confidence, left NULL): {report.skipped_low_confidence}")
    click.echo(f"Unclassified (no confident match): {report.unclassified}")
    if report.no_taxonomy:
        click.echo(f"Skipped (no bundled syllabus for subject): {report.no_taxonomy}")
    click.echo(f"Coverage: {report.coverage:.1%}")
    click.echo(f"Confidence bands (assigned only): {report.band_distribution}")
    click.echo(f"Distinct topics assigned: {len(report.label_distribution)}")


@question_bank_group.command("link-papers")
@click.option("--dry-run", is_flag=True, help="Report what would change without writing.")
@click.pass_context
def question_bank_link_papers_cmd(ctx: click.Context, dry_run: bool) -> None:
    """Fill ``question_bank.paper_id`` for banked past-paper questions (P4.4).

    P4.1 banked real past-paper questions without creating ``Paper`` rows, so
    every one of them was left unlinked. P4.4 made that link load-bearing: a
    placement duration estimate is derived from the paper's transcribed
    duration and mark total, reachable only through this column (D4.6 §5).
    Until this runs, placement reports ``no_eligible_questions`` for every
    subject.

    Deterministic and free — the paper identity is parsed from each row's
    ``source_question_id`` (which already carries the source PDF's filename),
    never inferred. Rows whose stem does not parse are counted and left
    unlinked. Idempotent: only NULL ``paper_id`` rows are considered.
    """
    from lemely.db.question_bank_repo import QuestionBankService
    from lemely.db.session import get_sessionmaker

    settings = _get_settings(ctx)
    outcome = QuestionBankService(get_sessionmaker(settings)).link_past_paper_rows(dry_run=dry_run)

    if ctx.obj.get("json_output", False):
        _dump_json(
            {
                "considered": outcome.considered,
                "linked": outcome.linked,
                "papersCreated": outcome.papers_created,
                "unparseable": outcome.unparseable,
                "noSubjectTaxonomy": outcome.no_subject_taxonomy,
                "dryRun": dry_run,
            }
        )
        return

    if dry_run:
        click.echo("DRY RUN — nothing written.")
    click.echo(f"Rows considered (past_paper, paper_id IS NULL): {outcome.considered}")
    click.echo(f"Linked: {outcome.linked}")
    click.echo(f"Paper rows created: {outcome.papers_created}")
    click.echo(f"Unparseable source_question_id (left unlinked): {outcome.unparseable}")
    click.echo(f"Skipped (no bundled syllabus for subject): {outcome.no_subject_taxonomy}")


@question_bank_group.command("import-generated")
@click.option(
    "--questions-dir",
    type=click.Path(file_okay=False),
    default=None,
    help="Directory of GeneratedQuiz JSON files (default: <output_dir>/questions).",
)
@click.pass_context
def question_bank_import_generated_cmd(ctx: click.Context, questions_dir: str | None) -> None:
    """Import on-disk GeneratedQuiz files into the question bank (one-shot).

    docs/quiz-model.md §2: existing files are imported once with
    owner_id=NULL; the disk path stays dead afterwards until a later cleanup
    removes it. Prints real counts, including the zero when the directory
    does not exist or holds nothing yet.
    """
    from lemely.db.question_bank_repo import QuestionBankService, import_generated_quiz_files
    from lemely.db.session import get_sessionmaker

    settings = _get_settings(ctx)
    directory = Path(questions_dir) if questions_dir else settings.paths.output_dir / "questions"
    service = QuestionBankService(get_sessionmaker(settings))
    result = import_generated_quiz_files(service, directory)

    if ctx.obj.get("json_output", False):
        _dump_json(
            {
                "directory": str(directory),
                "filesRead": result.files_read,
                "rowsCreated": result.rows_created,
                "skipped": [{"path": str(s.path), "reason": s.reason} for s in result.skipped],
            }
        )
        return

    click.echo(f"Directory: {directory}")
    click.echo(f"Files read: {result.files_read}")
    click.echo(f"Rows created: {result.rows_created}")
    click.echo(f"Skipped (malformed): {len(result.skipped)}")
    for s in result.skipped:
        click.echo(f"  - {s.path}: {s.reason}")


@question_bank_group.command("ingest-question-papers")
@click.argument("qp_dir", type=click.Path(exists=True, file_okay=False))
@click.option(
    "--schemes-dir",
    type=click.Path(exists=True, file_okay=False),
    default=None,
    help="Directory of parsed MarkScheme JSON (default: <output_dir>/schemes).",
)
@click.pass_context
def question_bank_ingest_question_papers_cmd(
    ctx: click.Context, qp_dir: str, schemes_dir: str | None
) -> None:
    """Deterministically extract question-paper PDFs under QP_DIR and bank them (P4.1).

    Closes the D3.7 prerequisite: pairs each extracted question-paper leaf
    with its matching mark-scheme question (by ref) from the parsed-scheme
    cache and writes real `source=past_paper` bank rows. Never invents a
    question the mark scheme can't grade and never banks a stem that
    depends on a figure it cannot represent — every exclusion is counted
    and printed by reason, honestly, not hidden. Safe to re-run.
    """
    from lemely.db.question_bank_repo import QuestionBankService
    from lemely.db.session import get_sessionmaker
    from lemely.io.question_papers import ingest_question_papers_dir

    settings = _get_settings(ctx)
    schemes_directory = Path(schemes_dir) if schemes_dir else settings.paths.output_dir / "schemes"
    service = QuestionBankService(get_sessionmaker(settings))
    report = ingest_question_papers_dir(service, qp_dir, schemes_directory)

    if ctx.obj.get("json_output", False):
        _dump_json(
            {
                "papersScanned": report.papers_scanned,
                "papersExtractFailed": report.papers_extract_failed,
                "papersNoScheme": report.papers_no_scheme,
                "papersReconcileMismatch": report.papers_reconcile_mismatch,
                "leavesExamined": report.leaves_examined,
                "produced": report.produced,
                "skippedAlreadyBanked": report.skipped_already_banked,
                "skippedFigure": report.skipped_figure,
                "skippedNoSchemeMatch": report.skipped_no_scheme_match,
                "skippedNoMarkingPoints": report.skipped_no_marking_points,
                "skippedMarksMismatch": report.skipped_marks_mismatch,
                "extractFailures": report.extract_failures,
                "noSchemePapers": report.no_scheme_papers,
                "reconcileMismatchPapers": report.reconcile_mismatch_papers,
            }
        )
        return

    click.echo(f"Question papers scanned: {report.papers_scanned}")
    click.echo(f"Extraction failures: {report.papers_extract_failed}")
    click.echo(f"No paired mark scheme found: {report.papers_no_scheme}")
    click.echo(
        f"Reconcile mismatch (extracted total != stated total): {report.papers_reconcile_mismatch}"
    )
    click.echo(f"Leaves examined: {report.leaves_examined}")
    click.echo(f"Produced (banked): {report.produced}")
    click.echo(f"Skipped — already banked: {report.skipped_already_banked}")
    click.echo(f"Skipped — has_figure: {report.skipped_figure}")
    click.echo(f"Skipped — no scheme match / container: {report.skipped_no_scheme_match}")
    click.echo(f"Skipped — no marking points: {report.skipped_no_marking_points}")
    click.echo(f"Skipped — marks mismatch: {report.skipped_marks_mismatch}")
    if report.extract_failures:
        click.echo("Extraction failures:")
        for line in report.extract_failures:
            click.echo(f"  - {line}")
    if report.reconcile_mismatch_papers:
        click.echo("Reconcile-mismatch papers:")
        for name in report.reconcile_mismatch_papers:
            click.echo(f"  - {name}")


@cli.command("aggregate-subject")
@click.argument(
    "correction_jsons", nargs=-1, required=True, type=click.Path(exists=True, dir_okay=False)
)
@click.option(
    "--on-error", type=click.Choice(["continue", "fail"]), default="fail", show_default=True
)
@click.pass_context
def aggregate_subject_cmd(
    ctx: click.Context,
    correction_jsons: tuple[str, ...],
    on_error: str,
) -> None:
    from lemely.io.subject import aggregate_subject

    papers = [_load_correction_result(p) for p in correction_jsons]
    _print_result(ctx, aggregate_subject(papers))


@cli.command("measure-accuracy")
@click.option(
    "--golden",
    "golden_dir",
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
        failed.append(
            f"mark_accuracy_theory {m.mark_accuracy_theory:.3f} < {t.mark_accuracy_target}"
        )
    if m.id_match_rate is not None and m.id_match_rate < t.id_match_rate_target:
        failed.append(f"id_match_rate {m.id_match_rate:.3f} < {t.id_match_rate_target}")
    if m.flag_precision_high < t.flag_precision_target:
        failed.append(
            f"flag_precision_high {m.flag_precision_high:.3f} < {t.flag_precision_target}"
        )
    if m.flag_recall < t.flag_recall_target:
        failed.append(f"flag_recall {m.flag_recall:.3f} < {t.flag_recall_target}")

    if failed:
        click.echo("\nTargets missed:", err=True)
        for f in failed:
            click.echo(f"  x {f}", err=True)
        raise click.exceptions.Exit(1)


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
        settings = settings.model_copy(
            update={
                "gradio": GradioSettings(
                    host=host or cur.host,
                    port=port or cur.port,
                    max_file_size_mb=cur.max_file_size_mb,
                )
            }
        )
    launch(settings)


def main(argv: list[str] | None = None) -> int:
    """Top-level entrypoint used by main.py and console-script."""
    import structlog

    from lemely.runtime.budget_notify import register_budget_ntfy

    register_budget_ntfy()

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
