from __future__ import annotations

from pathlib import Path

from .cli import _build_accuracy_report


def run_correction_demo(mark_scheme_path: str, answers: str) -> dict[str, object]:
    result = _build_accuracy_report(Path(mark_scheme_path), answers).model_dump(mode="json")
    return result


def build_app() -> object:
    try:
        import gradio as gr
    except ImportError as exc:
        raise RuntimeError(
            "gradio is not installed. Install it to run the Week 2 UI: pip install gradio"
        ) from exc

    with gr.Blocks(title="Lemely Assessment MVP") as demo:
        gr.Markdown("# Lemely Assessment MVP")
        with gr.Row():
            mark_scheme_path = gr.Textbox(
                label="Structured mark scheme JSON path",
                value="Sources/Physics/MarkingSchemes/0625_m20_ms_12.json",
            )
            answers = gr.Textbox(
                label="Student answers",
                lines=8,
            )
        run_button = gr.Button("Correct")
        output = gr.JSON(label="Strict JSON accuracy report")
        run_button.click(run_correction_demo, inputs=[mark_scheme_path, answers], outputs=output)
    return demo


def launch() -> None:
    build_app().launch()  # type: ignore[attr-defined]


if __name__ == "__main__":
    launch()
