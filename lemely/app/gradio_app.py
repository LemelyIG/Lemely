"""Gradio UI — 6 tabs. Tab 2 (Correct a Paper) and Tab 3 (Subject Result) are live."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def run_correction_demo(mark_scheme_path: str, answers: str) -> dict[str, object]:
    """Legacy helper retained for test compatibility."""
    from lemely.app.cli import _build_accuracy_report
    return _build_accuracy_report(Path(mark_scheme_path), answers).model_dump(mode="json")


def build_app(settings: Any = None) -> Any:
    try:
        import gradio as gr
    except ImportError as exc:
        raise RuntimeError("gradio is not installed. Run: pip install 'lemely[ui]'") from exc

    from lemely.app.gradio_callbacks import (
        build_mark_scheme_dropdown_choices,
        build_subject_session_choices,
        extracted_to_table_rows,
        load_papers_for_subject_session,
        parse_mark_scheme_path_from_label,
        rows_to_reviewed_answers_json,
        save_correction_artifacts,
    )
    from lemely.core.analytics import predict_grade, summarize_weaknesses
    from lemely.core.loose_schemas import MarkScheme
    from lemely.core.schemas import AccuracyReport, ExtractedAnswers
    from lemely.io.answer_extraction import GeminiAnswerExtractor
    from lemely.io.correction_ai import correct_paper as hybrid_correct_paper
    from lemely.io.gemini import GeminiClient
    from lemely.io.subject import aggregate_subject
    from lemely.runtime.config import load_settings as _load_settings

    if settings is None:
        settings = _load_settings()

    # --- Tab 2 callbacks ------------------------------------------------
    def _ms_choices() -> list[str]:
        return build_mark_scheme_dropdown_choices(settings.paths.sources_dir)

    def _extract(ms_label: str, scan_file: str) -> tuple[list[list[str]], str]:
        ms_path = parse_mark_scheme_path_from_label(ms_label)
        ms = MarkScheme.model_validate_json(ms_path.read_text(encoding="utf-8"))
        extractor = GeminiAnswerExtractor(GeminiClient(settings))
        result = extractor(scan_path=Path(scan_file), mark_scheme=ms)
        return extracted_to_table_rows(result), result.model_dump_json(indent=2)

    def _grade(
        ms_label: str, table_data: list[list[str]], mcq_only: bool,
    ) -> dict[str, Any]:
        ms_path = parse_mark_scheme_path_from_label(ms_label)
        ms = MarkScheme.model_validate_json(ms_path.read_text(encoding="utf-8"))
        reviewed = json.loads(rows_to_reviewed_answers_json(table_data))
        client = None if mcq_only else GeminiClient(settings)
        correction = hybrid_correct_paper(
            mark_scheme=ms, extracted_answers=reviewed,
            gemini_client=client, mcq_only=mcq_only,
        )
        report = AccuracyReport(
            correction=correction,
            weaknesses=summarize_weaknesses(correction),
            grade_prediction=predict_grade(correction),
        )
        return report.model_dump(mode="json")

    def _save(
        ms_label: str,
        extracted_json: str,
        table_data: list[list[str]],
        report: dict[str, Any],
    ) -> str:
        reviewed_json = rows_to_reviewed_answers_json(table_data)
        session_dir = save_correction_artifacts(
            output_dir=settings.paths.output_dir,
            mark_scheme_label=ms_label,
            extracted_answers_json=extracted_json or "{}",
            reviewed_answers_json=reviewed_json,
            accuracy_report_dict=report,
        )
        return f"Saved to {session_dir}"

    # --- Tab 3 callbacks ------------------------------------------------
    def _subject_choices() -> list[str]:
        return build_subject_session_choices(settings.paths.output_dir)

    def _aggregate(subject_session_label: str) -> dict[str, Any]:
        papers = load_papers_for_subject_session(settings.paths.output_dir, subject_session_label)
        result = aggregate_subject(papers)
        return result.model_dump(mode="json")

    with gr.Blocks(title="Lemely Assessment Tool") as demo:
        gr.Markdown("# Lemely Assessment Tool")

        # ------------------------------------------------------------------
        # Tab 1: Library (stub)
        # ------------------------------------------------------------------
        with gr.Tab("Library"):
            gr.Markdown("Browse / parse mark schemes. *(Full library tab — Phase 3.)*")
            gr.Textbox(label="Sources directory",
                       value=str(settings.paths.sources_dir), interactive=False)

        # ------------------------------------------------------------------
        # Tab 2: Correct a Paper (live)
        # ------------------------------------------------------------------
        with gr.Tab("Correct a Paper"):
            gr.Markdown(
                "Upload a scanned paper, extract answers with AI, review, then grade.\n"
                "MCQ questions are graded deterministically; theory / ATP questions are AI-marked."
            )
            ms_dropdown = gr.Dropdown(label="Mark scheme", choices=_ms_choices(), interactive=True)
            refresh = gr.Button("↻ Refresh", size="sm")
            refresh.click(fn=_ms_choices, inputs=[], outputs=[ms_dropdown])

            scan_upload = gr.File(
                label="Scanned student paper (PDF / PNG / JPG)",
                file_types=[".pdf", ".png", ".jpg", ".jpeg"],
            )
            extract_btn = gr.Button("Extract answers", variant="primary")

            answers_table = gr.Dataframe(
                headers=["Question", "Answer", "Confidence"],
                datatype=["str", "str", "str"],
                col_count=(3, "fixed"),
                interactive=True,
                label="Extracted answers — edit before grading",
            )
            extracted_json_state = gr.State("")
            extract_btn.click(fn=_extract,
                              inputs=[ms_dropdown, scan_upload],
                              outputs=[answers_table, extracted_json_state])

            mcq_only_cb = gr.Checkbox(label="MCQ-only (skip AI marking for non-MCQ questions)",
                                       value=False)
            grade_btn = gr.Button("Grade", variant="secondary")
            report_out = gr.JSON(label="Accuracy report")
            grade_btn.click(fn=_grade,
                            inputs=[ms_dropdown, answers_table, mcq_only_cb],
                            outputs=[report_out])

            save_btn = gr.Button("Save result")
            save_status = gr.Textbox(label="Save status", interactive=False)
            save_btn.click(fn=_save,
                           inputs=[ms_dropdown, extracted_json_state, answers_table, report_out],
                           outputs=[save_status])

        # ------------------------------------------------------------------
        # Tab 3: Subject Result (live)
        # ------------------------------------------------------------------
        with gr.Tab("Subject Result"):
            gr.Markdown(
                "Combine all paper corrections for a subject + session into a single grade."
            )
            subject_dropdown = gr.Dropdown(
                label="Subject + session", choices=_subject_choices(), interactive=True,
            )
            refresh_subj = gr.Button("↻ Refresh", size="sm")
            refresh_subj.click(fn=_subject_choices, inputs=[], outputs=[subject_dropdown])

            aggregate_btn = gr.Button("Aggregate subject grade", variant="primary")
            subject_out = gr.JSON(label="Subject result")
            aggregate_btn.click(fn=_aggregate, inputs=[subject_dropdown], outputs=[subject_out])

        # ------------------------------------------------------------------
        # Tab 4: Past Results (stub)
        # ------------------------------------------------------------------
        with gr.Tab("Past Results"):
            gr.Markdown("*(Past results browser — Phase 3.)*")

        # ------------------------------------------------------------------
        # Tab 5: Quiz (stub)
        # ------------------------------------------------------------------
        with gr.Tab("Quiz"):
            gr.Markdown("*(Interactive quiz — Phase 3.)*")

        # ------------------------------------------------------------------
        # Tab 6: Settings
        # ------------------------------------------------------------------
        with gr.Tab("Settings"):
            gr.Markdown("**Effective configuration** (read-only)")
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
                    ["gemini.model", settings.gemini.model],
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
        log.warning("gradio_non_localhost", host=settings.gradio.host,
                    message="Exposing Gradio outside localhost — ensure this is intentional.")

    build_app(settings).launch(
        server_name=settings.gradio.host,
        server_port=settings.gradio.port,
        share=False,
        show_api=False,
        max_file_size=f"{settings.gradio.max_file_size_mb}mb",
        allowed_paths=[str(settings.paths.sources_dir.resolve())],
    )
