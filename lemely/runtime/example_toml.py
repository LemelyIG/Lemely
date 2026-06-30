"""Generates `lemely.toml.example` from current Settings defaults."""

from __future__ import annotations

from lemely.runtime.config import Settings

_HEADER = """\
# lemely.toml — configuration template
#
# Precedence (highest wins): environment variables (LEMELY_*) > .env > this TOML > defaults.
# Nested keys use double-underscore in env vars (e.g. LEMELY_GRADIO__PORT=9000).
# All sections use extra='forbid'; unknown keys raise a validation error at startup.
"""


def render_example_toml() -> str:
    s = Settings()
    lines: list[str] = [_HEADER.rstrip(), ""]

    lines.append("[gradio]")
    lines.append(f'host = "{s.gradio.host}"')
    lines.append(f"port = {s.gradio.port}")
    lines.append(f"max_file_size_mb = {s.gradio.max_file_size_mb}")
    lines.append("")

    lines.append("[paths]")
    lines.append(f'sources_dir = "{s.paths.sources_dir}"')
    lines.append(f'output_dir = "{s.paths.output_dir}"')
    lines.append(f'cache_dir = "{s.paths.cache_dir}"')
    lines.append("")

    lines.append("[logging]")
    lines.append(f'level = "{s.logging.level}"')
    lines.append(f'format = "{s.logging.format}"')
    lines.append("")

    lines.append("[gemini]")
    lines.append(f'model = "{s.gemini.model}"')
    lines.append("")
    lines.append("# Per-task model overrides (omit a key to use the global `model` above).")
    lines.append('# mark_scheme_model = "gemini-2.5-pro"   # one-off parse; accuracy matters')
    lines.append('# extraction_model  = "gemini-2.5-flash" # vision-heavy, per paper')
    lines.append('# correction_model  = "gemini-2.5-flash" # per question; highest call volume')
    lines.append("")
    lines.append("# Escalation: re-mark with a stronger model when confidence < threshold.")
    lines.append('# escalation_model = "gemini-2.5-pro"')
    lines.append(f"# escalation_confidence_threshold = {s.gemini.escalation_confidence_threshold}")
    lines.append("")
    lines.append("# Thinking budget per task (tokens; 0 = disabled).")
    lines.append("[gemini.thinking_budget_for]")
    for tag, budget in s.gemini.thinking_budget_for.items():
        lines.append(f"{tag} = {budget}")
    lines.append("# correction_borderline = 2000  # retry borderline marks before Pro escalation")
    lines.append("")
    lines.append(f"max_retries = {s.gemini.max_retries}")
    lines.append(f"backoff_seconds = {s.gemini.backoff_seconds}")
    lines.append("# monthly_usd_ceiling = 25.0")
    lines.append("# per_run_token_ceiling = 200000")
    lines.append("")

    lines.append("# gemini_api_key is a secret — prefer the GEMINI_API_KEY env var instead.")
    lines.append('# gemini_api_key = "sk-..."')
    lines.append("")

    lines.append("[accuracy_eval]")
    lines.append(f"mark_accuracy_target = {s.accuracy_eval.mark_accuracy_target}")
    lines.append(f"id_match_rate_target = {s.accuracy_eval.id_match_rate_target}")
    lines.append(f"flag_precision_target = {s.accuracy_eval.flag_precision_target}")
    lines.append(f"flag_recall_target = {s.accuracy_eval.flag_recall_target}")
    lines.append("")

    return "\n".join(lines) + "\n"


def main() -> None:
    from pathlib import Path

    target = Path("lemely.toml.example")
    target.write_text(render_example_toml(), encoding="utf-8")
    print(f"wrote {target}")  # noqa: T201


if __name__ == "__main__":
    main()
