"""Sub-project C lever c1: no borderline thinking retry."""

from __future__ import annotations

import tempfile
from unittest.mock import MagicMock, patch

from lemely.core.loose_schemas import QuestionType
from lemely.core.schemas import AIMarkResponse
from lemely.io.correction_ai import AICorrector
from lemely.io.gemini import GeminiClient
from lemely.runtime.config import GeminiSettings
from tests.gemini_fakes import fake_genai_client, make_settings
from tests.test_anthropic_adapter import _VALID_MARK

_HAIKU, _SONNET = "claude-haiku-5-5", "claude-sonnet-5-5"


def _tags(confidences: list[float], **gemini: object) -> list[str]:
    settings = make_settings(tempfile.mkdtemp())
    g = settings.gemini.model_copy(
        update={"correction_model": _HAIKU, "escalation_model": _SONNET, **gemini}
    )
    client = GeminiClient(
        settings.model_copy(update={"gemini": g}), _genai_client=fake_genai_client(), ledger=None
    )
    replies = [AIMarkResponse.model_validate({**_VALID_MARK, "confidence": c}) for c in confidences]
    with (
        patch("lemely.io.correction_ai.build_marker_user_prompt", return_value="u"),
        patch.object(client, "generate_structured", side_effect=replies) as call,
    ):
        AICorrector(client).mark_question(
            MagicMock(type=QuestionType.EXPLANATION, id="2", marks=2), "a"
        )
    return [c.kwargs["task_tag"] for c in call.call_args_list]


def test_default_keeps_the_borderline_retry() -> None:
    assert GeminiSettings().correction_borderline_enabled is True
    assert _tags([0.7, 0.9]) == ["correction", "correction_borderline"]


def test_switch_off_goes_straight_to_escalation() -> None:
    assert _tags([0.7, 0.9], correction_borderline_enabled=False) == ["correction", "escalation"]


def test_switch_off_without_low_confidence_makes_one_call() -> None:
    assert _tags([0.95], correction_borderline_enabled=False) == ["correction"]


def test_switch_off_still_escalates_when_the_retry_is_low_too() -> None:
    assert _tags([0.5, 0.6], correction_borderline_enabled=False) == ["correction", "escalation"]


def test_switch_off_dedupes_against_the_first_call() -> None:
    # Escalation would run at the first pass's (model, effort): a repeat, so it is skipped.
    same = {"correction": "low", "escalation": "low", "correction_borderline": "high"}
    assert _tags(
        [0.5],
        correction_borderline_enabled=False,
        escalation_model=_HAIKU,
        claude_effort_for=same,
    ) == ["correction"]


def test_switch_on_dedupes_against_the_borderline_call() -> None:
    # Borderline ran at (haiku, high); escalation at the same pair is the repeat.
    same = {"correction": "low", "escalation": "high", "correction_borderline": "high"}
    assert _tags([0.5, 0.5], escalation_model=_HAIKU, claude_effort_for=same) == [
        "correction",
        "correction_borderline",
    ]
