"""Sub-project C P4: every task tag defaults to Claude; every default model is priced."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from lemely.accuracy.cost_ladder import runner
from lemely.core.loose_schemas import QuestionType
from lemely.core.schemas import AIMarkResponse
from lemely.io.correction_ai import AICorrector
from lemely.io.gemini import GeminiClient
from lemely.runtime.config import Settings
from tests.gemini_fakes import fake_genai_client
from tests.test_anthropic_adapter import _VALID_MARK

_HAIKU, _SONNET = "claude-haiku-5-5", "claude-sonnet-5-5"


def test_every_task_tag_defaults_to_haiku() -> None:
    g = Settings().gemini
    for tag in (
        "extraction",
        "correction",
        "correction_borderline",
        "scan_metadata",
        "generation",
        "study_plan",
        "self_review_judge",
        "adjudication",
    ):
        assert g.model_for(tag) == _HAIKU, tag
    # The fallback of every tag with no model of its own (question_validity among them).
    assert g.model == _HAIKU


def test_mark_scheme_parsing_stays_on_gemini() -> None:
    """Haiku's LLM parse failed parity with the deterministic parser (c-p4-ms-parity.md)."""
    assert Settings().gemini.model_for("mark_scheme") == "gemini-2.5-flash"


def test_there_is_no_default_escalation() -> None:
    g = Settings().gemini
    assert g.escalation_model is None
    assert g.escalation_cap_per_script is None


def test_binder_reads_on_haiku_and_retries_on_sonnet() -> None:
    b = Settings().binding
    assert b.read_model == _HAIKU and b.retry_model == _SONNET
    assert b.second_read_model is None
    assert b.claude_chunked_read is False


def test_the_screened_correction_levers_are_the_defaults() -> None:
    g = Settings().gemini
    assert g.correction_shared_prefix is True
    assert g.claude_files_api is True and g.claude_image_enhance is True
    assert g.correction_citations is False and g.correction_terse_rationale is False
    assert g.correction_retry_median is True
    assert g.review_confidence_threshold_for == {_HAIKU: 0.72}
    assert g.claude_cache_for == {
        "extraction": ["system", "images"],
        "binding_second_read": ["system", "images"],
        "correction": ["system", "prefix"],
        "correction_borderline": ["system", "prefix"],
        "escalation": ["system", "prefix"],
    }
    assert g.claude_effort_for == {
        "correction:mcq": "low",
        "correction:numeric": "low",
        "correction:short": "low",
        "correction:extended": "medium",
    }


def test_adjudication_defaults_are_the_final_rungs() -> None:
    g = Settings().gemini
    assert g.adjudication_model == _HAIKU
    assert g.adjudication_max_leaves == 6
    assert g.adjudication_confidence_threshold == 0.86
    assert g.adjudication_drawing_leaves is True
    assert g.adjudication_drawing_max_leaves == 6
    assert g.adjudication_reread_disagreed is True


def test_every_default_model_is_priced() -> None:
    runner.preflight_prices(Settings())


def test_default_marking_makes_no_escalation_call() -> None:
    """The final review's I5: a low-confidence leaf is retried but never escalated.

    ECF substitution re-marks through ``mark_question``, the same inline guard this drives.
    """
    s = Settings()
    client = GeminiClient(s, _genai_client=fake_genai_client(), ledger=None)
    ai = AICorrector(client)
    low = AIMarkResponse.model_validate({**_VALID_MARK, "confidence": 0.3, "awarded_marks": 1})
    with (
        patch("lemely.io.correction_ai.build_marker_user_prompt", return_value="u"),
        patch.object(client, "generate_structured", return_value=low) as call,
    ):
        ai.mark_question(MagicMock(type=QuestionType.EXPLANATION, id="1", marks=2), "a")
    tags = [c.kwargs["task_tag"] for c in call.call_args_list]
    assert tags and "escalation" not in tags
    assert {c.kwargs.get("model") for c in call.call_args_list} <= {None, _HAIKU}


def _rollback_toml() -> str:
    import re
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / "docs" / "deployment.md").read_text("utf-8")
    section = text.split("### 5.9 Roll back to Gemini", 1)[1]
    match = re.search(r"```toml\n(.*?)```", section, re.S)
    assert match is not None
    return match.group(1)


def test_the_documented_rollback_toml_restores_the_gemini_configuration(tmp_path: Path) -> None:
    from lemely.runtime.config import load_settings
    from tests.gemini_fakes import PRE_FLIP_DEFAULTS

    toml = tmp_path / "lemely.toml"
    toml.write_text(_rollback_toml(), "utf-8")
    s = load_settings(toml_path=toml, cwd=tmp_path)
    for dotted, value in PRE_FLIP_DEFAULTS.items():
        section, _, field = dotted.partition(".")
        got = getattr(getattr(s, section), field)
        if dotted == "gemini.adjudication_model":
            assert got == ""  # TOML cannot write None; "" means off
        else:
            assert got == value, dotted


def test_the_rollback_passes_doctor_without_an_anthropic_key(tmp_path: Path) -> None:
    import json

    from click.testing import CliRunner

    from lemely.app.cli import cli

    toml = tmp_path / "lemely.toml"
    toml.write_text(_rollback_toml(), "utf-8")
    (tmp_path / "Sources").mkdir()
    (tmp_path / "outputs").mkdir()
    result = CliRunner().invoke(
        cli,
        ["--json", "--config", str(toml), "doctor", "--no-network"],
        env={
            "GEMINI_API_KEY": "test-key",
            "ANTHROPIC_API_KEY": None,  # type: ignore[dict-item]
            "LEMELY_ANTHROPIC_API_KEY": None,  # type: ignore[dict-item]
            "LEMELY_PATHS__SOURCES_DIR": str(tmp_path / "Sources"),
            "LEMELY_PATHS__OUTPUT_DIR": str(tmp_path / "outputs"),
            "LEMELY_PATHS__CACHE_DIR": str(tmp_path / "cache"),
        },
    )
    payload = json.loads(result.output)
    checks = {c["name"]: c for c in payload["checks"]}
    assert checks["anthropic_api_key"]["ok"] is True, checks["anthropic_api_key"]
    assert "adjudication" not in checks["gemini_model_table"]["detail"]


def test_an_empty_adjudication_model_renders_and_calls_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rollback's ``adjudication_model = ""``: no pages source, no rasterise, no warning."""
    from lemely.io import adjudication, correction_ai
    from lemely.runtime.config import load_settings

    toml = tmp_path / "lemely.toml"
    toml.write_text(_rollback_toml(), "utf-8")
    s = load_settings(toml_path=toml, cwd=tmp_path)
    client = MagicMock(_settings=s)
    rendered: list[object] = []
    monkeypatch.setattr(
        "lemely.io.rasterise.rasterise_scan_to_pages", lambda p: rendered.append(p) or []
    )
    monkeypatch.setattr(correction_ai, "_adjudication_without_pages_logged", False)
    assert adjudication.adjudication_pages(client, tmp_path / "scan.pdf") is None
    assert adjudication.configured_adjudication_model(client) is None
    correction_ai._warn_adjudication_without_pages(client)
    assert correction_ai._adjudication_without_pages_logged is False
    assert rendered == []


def test_the_shipped_default_leaves_the_claude_binder_cap_at_32768() -> None:
    """F4: Haiku second reads reached 19k tokens. The Gemini 16,384 in the default map is not
    the Claude cap, and pinning the Gemini path must not turn it into one."""
    from tests.gemini_fakes import pin_pre_flip

    for settings in (Settings(), pin_pre_flip(Settings())):
        g = settings.gemini
        assert "max_output_tokens_for" not in g.model_fields_set
        client = GeminiClient(settings, _genai_client=fake_genai_client(), ledger=None)
        assert client._claude_output_cap("binding_second_read") == 32_768
