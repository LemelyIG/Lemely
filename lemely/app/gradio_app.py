"""Gradio UI — 6 tabs. Tabs 2 and 3 stream live activity from the EventBus."""

from __future__ import annotations

import json
import threading
from collections.abc import Generator
from pathlib import Path
from typing import Any


def run_correction_demo(mark_scheme_path: str, answers: str) -> dict[str, object]:
    """Legacy helper retained for test compatibility."""
    from lemely.app.cli import _build_accuracy_report

    return _build_accuracy_report(Path(mark_scheme_path), answers).model_dump(mode="json")


def _render_questions_md(report_dict: dict[str, Any], ms: Any = None) -> str:
    """Return a Markdown string summarising per-question correction results."""
    lines = ["### Per-question results\n"]
    source_badge = {"deterministic": "🔢", "ai": "🤖", "missing": "❓"}
    for q in report_dict.get("correction", {}).get("questions", []):
        qid = q.get("question_id", "?")
        awarded = q.get("awarded_marks", 0)
        max_m = q.get("max_marks", "?")
        src = q.get("marker_source", "?")
        conf = q.get("confidence_score")
        fb = q.get("feedback") or ""
        pts = q.get("matched_point_ids") or []
        review = q.get("review_reason") or ""

        badge = source_badge.get(src, "?")
        conf_str = f"  conf={conf:.2f}" if conf is not None else ""
        lines.append(f"**{qid}** — {awarded}/{max_m} {badge}{conf_str}")
        if pts:
            lines.append(f"  - Matched points: `{', '.join(pts)}`")
        if fb:
            lines.append(f"  - *{fb}*")
        if review:
            lines.append(f"  - ⚠ {review}")
        lines.append("")
    return "\n".join(lines)


_LEMELY_CSS = """
/* ── Header ─────────────────────────────────────────────────────────── */
.lemely-header {
    padding: 1.25rem 0 1rem;
    border-bottom: 1px solid oklch(0.87 0.006 40);
    margin-bottom: 0.5rem;
}
.lemely-header h1 {
    font-size: 1.375rem;
    font-weight: 700;
    color: oklch(0.20 0.02 35);
    margin: 0 0 0.2rem;
    letter-spacing: -0.025em;
    line-height: 1.2;
}
.lemely-header p {
    font-size: 0.8125rem;
    color: oklch(0.50 0.018 35);
    margin: 0;
    letter-spacing: 0.01em;
}

/* ── Activity / log blocks ───────────────────────────────────────────── */
.lemely-activity label { font-size: 0.75rem !important; }

/* ── Grade display ───────────────────────────────────────────────────── */
.lemely-grade-hero {
    font-size: 2.25rem;
    font-weight: 700;
    color: oklch(0.62 0.13 35);
    line-height: 1;
    letter-spacing: -0.03em;
}

/* ── Token counter ───────────────────────────────────────────────────── */
.lemely-tokens {
    font-size: 0.75rem;
    color: oklch(0.60 0.010 35);
    font-variant-numeric: tabular-nums;
}

/* ── Marker source legend ────────────────────────────────────────────── */
.lemely-legend {
    font-size: 0.75rem;
    color: oklch(0.50 0.018 35);
    margin-top: 0.5rem;
}

/* ── Subtle section labels ───────────────────────────────────────────── */
.lemely-section-label {
    font-size: 0.8125rem;
    font-weight: 600;
    color: oklch(0.40 0.020 35);
    margin-bottom: 0.25rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
}

/* ── Tab active accent ───────────────────────────────────────────────── */
.tab-nav button.selected {
    color: oklch(0.55 0.13 35) !important;
    font-weight: 600 !important;
}

/* ── Primary button ──────────────────────────────────────────────────── */
.gr-button-primary {
    background: oklch(0.62 0.13 35) !important;
    border-color: oklch(0.62 0.13 35) !important;
}
.gr-button-primary:hover {
    background: oklch(0.57 0.13 35) !important;
    border-color: oklch(0.57 0.13 35) !important;
}
"""


def _lemely_theme() -> Any:
    """Build the Lemely Gradio theme: Soft base with terracotta OKLCH accent."""
    try:
        import gradio as gr
    except ImportError:
        return None  # theme is optional; build_app handles the import error
    return gr.themes.Soft(
        primary_hue=gr.themes.colors.orange,
        neutral_hue=gr.themes.colors.stone,
        font=gr.themes.GoogleFont("Inter"),
    ).set(
        body_background_fill="oklch(0.97 0.007 40)",
        background_fill_primary="oklch(0.995 0.003 40)",
        background_fill_secondary="oklch(0.96 0.006 40)",
        border_color_primary="oklch(0.87 0.006 40)",
        body_text_color="oklch(0.20 0.02 35)",
        body_text_color_subdued="oklch(0.48 0.018 35)",
        button_primary_background_fill="oklch(0.62 0.13 35)",
        button_primary_background_fill_hover="oklch(0.57 0.13 35)",
        button_primary_text_color="oklch(0.99 0.003 40)",
        button_primary_border_color="oklch(0.62 0.13 35)",
        button_secondary_background_fill="oklch(0.99 0.003 40)",
        button_secondary_background_fill_hover="oklch(0.94 0.04 35)",
        button_secondary_border_color="oklch(0.87 0.006 40)",
        button_secondary_text_color="oklch(0.20 0.02 35)",
        input_background_fill="oklch(0.99 0.003 40)",
        input_border_color="oklch(0.87 0.006 40)",
        input_border_color_focus="oklch(0.62 0.13 35)",
        link_text_color="oklch(0.55 0.13 35)",
        link_text_color_hover="oklch(0.48 0.13 35)",
        block_label_text_color="oklch(0.48 0.018 35)",
        block_label_background_fill="oklch(0.96 0.006 40)",
    )


def build_app(settings: Any = None) -> Any:
    try:
        import gradio as gr
    except ImportError as exc:
        raise RuntimeError("gradio is not installed. Run: pip install 'lemely[ui]'") from exc

    from lemely.app.gradio_callbacks import (
        build_history_trend_markdown,
        build_library_table_rows,
        build_mark_scheme_dropdown_choices,
        build_subject_session_choices,
        extracted_to_table_rows,
        history_to_table_rows,
        load_papers_for_subject_session,
        parse_mark_scheme_path_from_label,
        rows_to_reviewed_answers_json,
        save_correction_artifacts,
    )
    from lemely.app.live_log import LiveLogBuffer
    from lemely.core.analytics import predict_grade, summarize_weaknesses
    from lemely.core.loose_schemas import MarkScheme
    from lemely.core.schemas import AccuracyReport
    from lemely.io.answer_extraction import GeminiAnswerExtractor
    from lemely.io.correction_ai import correct_paper as hybrid_correct_paper
    from lemely.io.gemini import GeminiClient
    from lemely.io.subject import aggregate_subject
    from lemely.runtime.config import load_settings as _load_settings

    if settings is None:
        settings = _load_settings()

    g = settings.gemini

    # ------------------------------------------------------------------ #
    # Shared helpers
    # ------------------------------------------------------------------ #

    def _token_text() -> str:
        import lemely.io.gemini as _gm

        in_tok, out_tok = _gm.process_token_totals()
        usd = _gm._process_accumulated_usd
        return f"**In:** {in_tok:,}  **Out:** {out_tok:,}  **USD:** ${usd:.4f}"

    # ------------------------------------------------------------------ #
    # Tab 2 callbacks (generator = live-streaming)
    # ------------------------------------------------------------------ #

    def _ms_choices() -> list[str]:
        return build_mark_scheme_dropdown_choices(settings.paths.sources_dir)

    def _extract(
        ms_label: str,
        scan_file: str,
    ) -> Generator[tuple[list[list[str]], str, str, str], None, None]:
        """Extract answers from a scanned paper; streams EventBus events live."""
        buf = LiveLogBuffer()
        buf.start()
        result_holder: dict[str, Any] = {}
        error_holder: dict[str, Exception] = {}

        def _run() -> None:
            try:
                ms_path = parse_mark_scheme_path_from_label(ms_label)
                ms = MarkScheme.model_validate_json(ms_path.read_text(encoding="utf-8"))
                extractor = GeminiAnswerExtractor(GeminiClient(settings))
                result = extractor(scan_path=Path(scan_file), mark_scheme=ms)
                result_holder["rows"] = extracted_to_table_rows(result)
                result_holder["json"] = result.model_dump_json(indent=2)
            except Exception as exc:
                error_holder["err"] = exc
            finally:
                from lemely.runtime.events import bus as _bus

                _bus.publish_done()

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()

        empty: list[list[str]] = []
        for log_text in buf.drain_until_done():
            yield empty, "", log_text, _token_text()

        buf.stop()
        thread.join()

        if "err" in error_holder:
            yield empty, "", f"ERROR: {error_holder['err']}", _token_text()
            return
        yield (
            result_holder.get("rows", empty),
            result_holder.get("json", ""),
            buf.current_text(),
            _token_text(),
        )

    def _grade(
        ms_label: str,
        table_data: list[list[str]],
        mcq_only: bool,
        extracted_json: str,
    ) -> Generator[tuple[dict[str, Any], str, str, str], None, None]:
        """Grade the paper via AI + deterministic marking; streams events live."""
        buf = LiveLogBuffer()
        buf.start()
        result_holder: dict[str, Any] = {}
        error_holder: dict[str, Exception] = {}

        def _run() -> None:
            try:
                from lemely.io.grade_boundaries import GradeBoundaryStore

                ms_path = parse_mark_scheme_path_from_label(ms_label)
                ms = MarkScheme.model_validate_json(ms_path.read_text(encoding="utf-8"))
                reviewed = json.loads(rows_to_reviewed_answers_json(table_data))
                client = None if mcq_only else GeminiClient(settings)
                correction = hybrid_correct_paper(
                    mark_scheme=ms,
                    extracted_answers=reviewed,
                    gemini_client=client,
                    mcq_only=mcq_only,
                )
                store = GradeBoundaryStore()
                boundaries, boundary_source = store.resolve(correction.metadata)
                report = AccuracyReport(
                    correction=correction,
                    weaknesses=summarize_weaknesses(correction),
                    grade_prediction=predict_grade(
                        correction,
                        boundaries=boundaries,
                        boundary_source=boundary_source,
                    ),
                )
                result_holder["report"] = report.model_dump(mode="json")
                result_holder["qmd"] = _render_questions_md(result_holder["report"], ms)
            except Exception as exc:
                error_holder["err"] = exc
            finally:
                from lemely.runtime.events import bus as _bus

                _bus.publish_done()

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()

        for log_text in buf.drain_until_done():
            yield {}, "*(grading…)*", log_text, _token_text()

        buf.stop()
        thread.join()

        if "err" in error_holder:
            yield {}, f"**Error:** {error_holder['err']}", buf.current_text(), _token_text()
            return
        yield (
            result_holder.get("report", {}),
            result_holder.get("qmd", ""),
            buf.current_text(),
            _token_text(),
        )

    def _save(
        ms_label: str,
        extracted_json: str,
        table_data: list[list[str]],
        report: dict[str, Any],
        student_id: str,
    ) -> str:
        if not report:
            return "Grade the paper before saving."
        reviewed_json = rows_to_reviewed_answers_json(table_data)
        session_dir = save_correction_artifacts(
            output_dir=settings.paths.output_dir,
            mark_scheme_label=ms_label,
            extracted_answers_json=extracted_json or "{}",
            reviewed_answers_json=reviewed_json,
            accuracy_report_dict=report,
            student_id=student_id.strip() if student_id else None,
        )
        return f"Saved to {session_dir}"

    # ------------------------------------------------------------------ #
    # Tab 3 callbacks (generator = live-streaming)
    # ------------------------------------------------------------------ #

    def _subject_choices() -> list[str]:
        return build_subject_session_choices(settings.paths.output_dir)

    def _aggregate(
        subject_session_label: str,
    ) -> Generator[tuple[dict[str, Any], str, str, str], None, None]:
        """Aggregate subject results; streams events live."""
        buf = LiveLogBuffer()
        buf.start()
        result_holder: dict[str, Any] = {}
        error_holder: dict[str, Exception] = {}

        def _run() -> None:
            try:
                papers = load_papers_for_subject_session(
                    settings.paths.output_dir,
                    subject_session_label,
                )
                result = aggregate_subject(papers)
                result_holder["result"] = result.model_dump(mode="json")
            except Exception as exc:
                error_holder["err"] = exc
            finally:
                from lemely.runtime.events import bus as _bus

                _bus.publish_done()

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()

        for log_text in buf.drain_until_done():
            yield {}, log_text, _token_text(), ""

        buf.stop()
        thread.join()

        if "err" in error_holder:
            yield {}, f"ERROR: {error_holder['err']}", _token_text(), ""
            return

        result = result_holder.get("result", {})
        # Build summary markdown from key fields
        sc = result.get("subject_code", "")
        awarded = result.get("total_awarded_marks", "?")
        max_m = result.get("total_maximum_marks", "?")
        pct = result.get("percentage")
        grade = result.get("grade", "?")
        pct_str = f"{pct:.1f}%" if isinstance(pct, float) else "?"
        summary_md = (
            f"**Subject:** {sc}  \n"
            f"**Total:** {awarded}/{max_m}  \n"
            f"**Percentage:** {pct_str}  \n"
            f"**Grade:** {grade}"
        )
        yield result, buf.current_text(), _token_text(), summary_md

    # ------------------------------------------------------------------ #
    # UI layout
    # ------------------------------------------------------------------ #

    with gr.Blocks(title="Lemely") as demo:
        gr.HTML(
            "<div class='lemely-header'>"
            "<h1>Lemely</h1>"
            "<p>Accuracy-first CAIE assessment tool</p>"
            "</div>"
        )

        # ── Tab 1: Library ─────────────────────────────────────────────
        with gr.Tab("Library"):
            gr.Markdown(
                "Browse mark schemes in your sources directory. "
                "Select a PDF and click **Parse selected** to extract it deterministically."
            )
            gr.Textbox(
                label="Sources directory",
                value=str(settings.paths.sources_dir),
                interactive=False,
            )
            with gr.Row():
                lib_refresh_btn = gr.Button("↻ Refresh list", size="sm")
                lib_parse_btn = gr.Button("Parse selected", variant="primary", size="sm")
            lib_table = gr.Dataframe(
                headers=["File", "Status", "Subject", "Paper", "Session"],
                datatype=["str", "str", "str", "str", "str"],
                column_count=5,
                value=build_library_table_rows(settings.paths.sources_dir),
                interactive=True,
                type="array",
                label="Mark schemes",
            )
            lib_status = gr.Textbox(label="Parse status", interactive=False)
            lib_log = gr.Code(
                label="Activity",
                language=None,
                lines=10,
                interactive=False,
            )

            def _lib_refresh() -> list[list[str]]:
                return build_library_table_rows(settings.paths.sources_dir)

            def _lib_parse(
                table_data: list[list[str]],
            ) -> Generator[tuple[str, str], None, None]:
                """Parse the first selected row's PDF using DeterministicMarkSchemeParser."""
                from lemely.io.det import DeterministicMarkSchemeParser
                from lemely.runtime.errors import ParseError

                # Find first row with a filename
                selected_filename: str | None = None
                for row in table_data:
                    if row and row[0]:
                        selected_filename = row[0]
                        break

                if not selected_filename:
                    yield "No file selected.", ""
                    return

                pdf_path = settings.paths.sources_dir / selected_filename
                if not pdf_path.exists():
                    yield f"File not found: {pdf_path}", ""
                    return

                buf = LiveLogBuffer()
                buf.start()
                result_holder: dict[str, str] = {}
                error_holder: dict[str, Exception] = {}

                def _run() -> None:
                    try:
                        parser = DeterministicMarkSchemeParser(cfg=settings.det_parser)
                        ms = parser(pdf_path)
                        out_path = pdf_path.with_suffix(".json")
                        out_path.write_text(ms.model_dump_json(indent=2), encoding="utf-8")
                        result_holder["msg"] = f"Parsed and saved: {out_path.name}"
                    except (ParseError, Exception) as exc:
                        error_holder["err"] = exc
                    finally:
                        from lemely.runtime.events import bus as _bus

                        _bus.publish_done()

                thread = threading.Thread(target=_run, daemon=True)
                thread.start()

                for log_text in buf.drain_until_done():
                    yield "Parsing…", log_text

                buf.stop()
                thread.join()

                if "err" in error_holder:
                    yield f"ERROR: {error_holder['err']}", buf.current_text()
                    return
                yield result_holder.get("msg", "Done."), buf.current_text()

            lib_refresh_btn.click(fn=_lib_refresh, inputs=[], outputs=[lib_table])
            lib_parse_btn.click(
                fn=_lib_parse,
                inputs=[lib_table],
                outputs=[lib_status, lib_log],
            )

        # ── Tab 2: Correct a Paper ─────────────────────────────────────
        with gr.Tab("Correct a Paper"):
            gr.Markdown(
                "Upload a scanned paper, extract answers, review them, then grade.\n\n"
                "🔢 MCQ questions are graded deterministically. "
                "🤖 Theory / ATP questions are AI-assisted. "
                "❓ Unmatched questions need teacher review."
            )
            with gr.Row():
                # Main column
                with gr.Column(scale=3):
                    ms_dropdown = gr.Dropdown(
                        label="Mark scheme",
                        choices=_ms_choices(),
                        interactive=True,
                    )
                    refresh = gr.Button("↻ Refresh mark schemes", size="sm")

                    def _refresh_ms() -> Any:
                        choices = _ms_choices()
                        return gr.Dropdown(choices=choices, value=choices[0] if choices else None)

                    refresh.click(fn=_refresh_ms, inputs=[], outputs=[ms_dropdown])

                    scan_upload = gr.File(
                        label="Scanned student paper (PDF / PNG / JPG)",
                        file_types=[".pdf", ".png", ".jpg", ".jpeg"],
                    )
                    extract_btn = gr.Button("Extract answers", variant="primary")

                    answers_table = gr.Dataframe(
                        headers=[
                            "Question",
                            "Answer",
                            "Confidence",
                            "Working (from scan)",
                            "Source region",
                        ],
                        datatype=["str", "str", "str", "str", "str"],
                        column_count=5,
                        interactive=True,
                        type="array",
                        label="Extracted answers — edit before grading",
                    )
                    extracted_json_state = gr.State("")

                    mcq_only_cb = gr.Checkbox(
                        label="MCQ-only (skip AI marking for non-MCQ questions)",
                        value=False,
                    )
                    grade_btn = gr.Button("Grade", variant="primary")

                    questions_detail = gr.Markdown(
                        "*(Extract then grade to see per-question breakdown.)*",
                    )
                    with gr.Accordion("Raw accuracy report (JSON)", open=False):
                        report_out = gr.JSON(label="")

                    student_id_input = gr.Textbox(
                        label="Student ID (optional — leave blank to skip history recording)",
                        placeholder="e.g. S12345",
                    )
                    save_btn = gr.Button("Save result")
                    save_status = gr.Textbox(label="Save status", interactive=False)

                # Live Activity column
                with gr.Column(scale=2):
                    gr.Markdown("### Live Activity")
                    token_counter_t2 = gr.Markdown(
                        "**In:** —  **Out:** —  **USD:** —", elem_classes=["lemely-tokens"]
                    )
                    live_log_t2 = gr.Code(
                        label="Activity",
                        language=None,
                        lines=18,
                        interactive=False,
                    )

            extract_btn.click(
                fn=_extract,
                inputs=[ms_dropdown, scan_upload],
                outputs=[answers_table, extracted_json_state, live_log_t2, token_counter_t2],
            )
            grade_btn.click(
                fn=_grade,
                inputs=[ms_dropdown, answers_table, mcq_only_cb, extracted_json_state],
                outputs=[report_out, questions_detail, live_log_t2, token_counter_t2],
            )
            save_btn.click(
                fn=_save,
                inputs=[
                    ms_dropdown,
                    extracted_json_state,
                    answers_table,
                    report_out,
                    student_id_input,
                ],
                outputs=[save_status],
            )

        # ── Tab 3: Subject Result ──────────────────────────────────────
        with gr.Tab("Subject Result"):
            gr.Markdown(
                "Combine all paper corrections for a subject + session into a single grade."
            )
            with gr.Row():
                with gr.Column(scale=3):
                    subject_dropdown = gr.Dropdown(
                        label="Subject + session",
                        choices=_subject_choices(),
                        interactive=True,
                    )
                    refresh_subj = gr.Button("↻ Refresh", size="sm")

                    def _refresh_subject() -> Any:
                        choices = _subject_choices()
                        return gr.Dropdown(choices=choices, value=choices[0] if choices else None)

                    refresh_subj.click(
                        fn=_refresh_subject,
                        inputs=[],
                        outputs=[subject_dropdown],
                    )
                    aggregate_btn = gr.Button("Aggregate subject grade", variant="primary")
                    subject_summary_md = gr.Markdown("*(Aggregate to see summary.)*")
                    with gr.Accordion("Raw subject result (JSON)", open=False):
                        subject_out = gr.JSON(label="Subject result")

                with gr.Column(scale=2):
                    gr.Markdown("### Live Activity")
                    token_counter_t3 = gr.Markdown(
                        "**In:** —  **Out:** —  **USD:** —", elem_classes=["lemely-tokens"]
                    )
                    live_log_t3 = gr.Code(
                        label="Activity",
                        language=None,
                        lines=12,
                        interactive=False,
                    )

            aggregate_btn.click(
                fn=_aggregate,
                inputs=[subject_dropdown],
                outputs=[subject_out, live_log_t3, token_counter_t3, subject_summary_md],
            )

        # ── Tab 4: Past Results ────────────────────────────────────────
        with gr.Tab("Past Results"):
            gr.Markdown(
                "Track a student's progress across papers. "
                "Records are saved when you use **Save result** in Correct a Paper, "
                "or via `correct-paper --record --student-id` in the CLI."
            )
            with gr.Row():
                hist_student_id = gr.Textbox(label="Student ID", placeholder="e.g. S12345")
                hist_load_btn = gr.Button("Load history", variant="primary")
            hist_table = gr.Dataframe(
                headers=["Date", "Subject", "Paper", "Awarded", "Max", "%", "Grade"],
                datatype=["str", "str", "str", "str", "str", "str", "str"],
                column_count=7,
                interactive=False,
                type="array",
                label="Paper records",
            )
            hist_trend_md = gr.Markdown(
                "*Enter a student ID and click Load history to see their progress.*"
            )
            with gr.Accordion("Raw history (JSON)", open=False):
                hist_raw = gr.JSON(label="")

            def _load_history(
                student_id: str,
            ) -> tuple[list[list[str]], str, dict[str, Any]]:
                from lemely.io.history_store import HistoryStore

                store = HistoryStore(settings.paths.output_dir / "history")
                history = store.load(student_id.strip())
                rows = history_to_table_rows(history)
                trend = build_history_trend_markdown(history)
                raw = history.model_dump(mode="json")
                return rows, trend, raw

            hist_load_btn.click(
                fn=_load_history,
                inputs=[hist_student_id],
                outputs=[hist_table, hist_trend_md, hist_raw],
            )

        # ── Tab 5: Quiz ────────────────────────────────────────────────
        with gr.Tab("Quiz"):
            gr.Markdown(
                "Generate targeted practice questions from a student's weak areas. "
                "Load from history or upload a weakness JSON file from `detect-weaknesses`."
            )
            quiz_weakness_state = gr.State(None)
            with gr.Row():
                with gr.Column(scale=1):
                    quiz_student_id = gr.Textbox(
                        label="Student ID",
                        placeholder="e.g. S12345",
                    )
                    quiz_load_btn = gr.Button("Load weaknesses from history", size="sm")
                    quiz_file = gr.File(
                        label="Or upload weakness JSON",
                        file_types=[".json"],
                    )
                    quiz_weakness_status = gr.Textbox(
                        label="Weakness source",
                        interactive=False,
                    )
                with gr.Column(scale=2):
                    quiz_count = gr.Slider(
                        minimum=1,
                        maximum=20,
                        value=5,
                        step=1,
                        label="Number of questions",
                    )
                    quiz_generate_btn = gr.Button("Generate Quiz", variant="primary")
                    quiz_output = gr.Markdown(
                        "*Load weaknesses from history or upload a file, then click Generate Quiz.*"
                    )

            def _load_quiz_weaknesses(
                student_id: str,
            ) -> tuple[Any, str]:
                from lemely.core.analytics import aggregate_weaknesses_from_history
                from lemely.io.history_store import HistoryStore

                store = HistoryStore(settings.paths.output_dir / "history")
                history = store.load(student_id.strip())
                weakness_report = aggregate_weaknesses_from_history(history)
                n = len(weakness_report.weak_areas)
                status = (
                    f"Loaded {n} weak area{'s' if n != 1 else ''} "
                    f"from history for '{student_id.strip()}'."
                )
                return weakness_report, status

            def _load_quiz_weaknesses_from_file(
                file_path: str | None,
            ) -> tuple[Any, str]:
                from lemely.core.schemas import WeaknessReport

                if not file_path:
                    return None, "No file uploaded."
                try:
                    data = Path(file_path).read_text(encoding="utf-8")
                    weakness_report = WeaknessReport.model_validate_json(data)
                    n = len(weakness_report.weak_areas)
                    return (
                        weakness_report,
                        f"Loaded {n} weak area{'s' if n != 1 else ''} from file.",
                    )
                except Exception as exc:
                    return None, f"Failed to parse file: {exc}"

            def _generate_quiz(
                weakness_report: Any,
                question_count: int,
            ) -> str:
                from lemely.core.analytics import generate_quiz

                if weakness_report is None:
                    return "*No weaknesses loaded. Load from history or upload a file first.*"
                payload = generate_quiz(weakness_report, question_count=int(question_count))
                if not payload.questions:
                    return "*No questions could be generated (no weak areas found).*"
                lines: list[str] = []
                for i, q in enumerate(payload.questions, 1):
                    lines.append(f"### Question {i} — {q.topic}")
                    lines.append(f"{q.prompt}")
                    if q.source_question_ids:
                        ids_str = ", ".join(q.source_question_ids)
                        lines.append(
                            f"\n<details><summary>Source questions</summary>\n\n"
                            f"{ids_str}\n\n</details>"
                        )
                    lines.append("")
                return "\n".join(lines)

            quiz_load_btn.click(
                fn=_load_quiz_weaknesses,
                inputs=[quiz_student_id],
                outputs=[quiz_weakness_state, quiz_weakness_status],
            )
            quiz_file.change(
                fn=_load_quiz_weaknesses_from_file,
                inputs=[quiz_file],
                outputs=[quiz_weakness_state, quiz_weakness_status],
            )
            quiz_generate_btn.click(
                fn=_generate_quiz,
                inputs=[quiz_weakness_state, quiz_count],
                outputs=[quiz_output],
            )

        # ── Tab 6: Settings ────────────────────────────────────────────
        with gr.Tab("Settings"):
            gr.Markdown(
                "To change settings, edit `lemely.toml` in your project root and restart.\n\n"
                "**Effective configuration** (read-only)"
            )
            gr.Dataframe(
                headers=["Setting", "Value"],
                value=[
                    ["gradio.host", settings.gradio.host],
                    ["gradio.port", str(settings.gradio.port)],
                    ["gradio.max_file_size_mb", str(settings.gradio.max_file_size_mb)],
                    ["paths.sources_dir", str(settings.paths.sources_dir)],
                    ["paths.output_dir", str(settings.paths.output_dir)],
                    ["paths.cache_dir", str(settings.paths.cache_dir)],
                    ["logging.level", settings.logging.level],
                    ["gemini.model (default)", g.model],
                    ["gemini.mark_scheme_model", g.mark_scheme_model or f"→ {g.model}"],
                    ["gemini.extraction_model", g.extraction_model or f"→ {g.model}"],
                    ["gemini.correction_model", g.correction_model or f"→ {g.model}"],
                    ["gemini.escalation_model", g.escalation_model or "(off)"],
                    [
                        "gemini.escalation_confidence_threshold",
                        str(g.escalation_confidence_threshold),
                    ],
                    ["gemini_api_key", "***" if settings.gemini_api_key else "(not set)"],
                ],
                interactive=False,
            )

    return demo


def launch(settings: Any = None) -> None:
    from lemely.runtime.config import load_settings as _load_settings

    if settings is None:
        settings = _load_settings()

    import structlog

    log = structlog.get_logger().bind(component="gradio")
    if settings.gradio.host != "127.0.0.1":
        log.warning(
            "gradio_non_localhost",
            host=settings.gradio.host,
            message="Exposing Gradio outside localhost — ensure this is intentional.",
        )

    build_app(settings).launch(
        server_name=settings.gradio.host,
        server_port=settings.gradio.port,
        share=False,
        max_file_size=f"{settings.gradio.max_file_size_mb}mb",
        allowed_paths=[str(settings.paths.sources_dir.resolve())],
        theme=_lemely_theme(),
        css=_LEMELY_CSS,
    )
