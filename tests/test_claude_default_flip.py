"""Sub-project C P4: every task tag defaults to Claude; every default model is priced."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

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
        "mark_scheme",
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


def test_default_marking_makes_no_escalation_call_with_ecf_substitution_on() -> None:
    """The final review's I5: no Sonnet escalation, so ECF's re-mark cannot reach one either."""
    base = Settings()
    s = base.model_copy(
        update={
            "grading": base.grading.model_copy(
                update={"equivalence_gate": True, "ecf_substitution": True}
            )
        }
    )
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
