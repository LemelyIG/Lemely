"""Sub-project C P2.5: which triggers escalate with the cascade off (characterization)."""

from __future__ import annotations

import tempfile
from unittest.mock import MagicMock, patch

from lemely.core.loose_schemas import QuestionType
from lemely.core.schemas import AIMarkResponse
from lemely.io.correction_ai import AICorrector
from lemely.io.gemini import GeminiClient
from tests.gemini_fakes import fake_genai_client, make_settings
from tests.test_anthropic_adapter import _VALID_MARK

_HAIKU = "claude-haiku-5-5"
_SONNET = "claude-sonnet-5-5"


def _tags(confidences: list[float], **gemini: object) -> list[tuple[str, str | None]]:
    settings = make_settings(tempfile.mkdtemp())
    g = settings.gemini.model_copy(update={"correction_model": _HAIKU, **gemini})
    client = GeminiClient(
        settings.model_copy(update={"gemini": g}), _genai_client=fake_genai_client(), ledger=None
    )
    replies = [AIMarkResponse.model_validate({**_VALID_MARK, "confidence": c}) for c in confidences]
    question = MagicMock(type=QuestionType.EXPLANATION, id="2", marks=2)
    with (
        patch("lemely.io.correction_ai.build_marker_user_prompt", return_value="u"),
        patch.object(client, "generate_structured", side_effect=replies) as call,
    ):
        AICorrector(client).mark_question(question, "answer")
    return [(c.kwargs["task_tag"], c.kwargs.get("model")) for c in call.call_args_list]


def test_all_haiku_never_escalates_after_a_borderline_retry() -> None:
    # The E2E config: escalation on Haiku, borderline and escalation both at "high".
    assert _tags([0.70, 0.70], escalation_model=_HAIKU) == [
        ("correction", None),
        ("correction_borderline", None),
    ]


def test_sonnet_escalation_fires_when_still_below_the_threshold() -> None:
    assert _tags([0.70, 0.70, 0.95], escalation_model=_SONNET) == [
        ("correction", None),
        ("correction_borderline", None),
        ("escalation", _SONNET),
    ]


def test_a_borderline_retry_that_recovers_stops_escalation() -> None:
    assert _tags([0.70, 0.85], escalation_model=_SONNET) == [
        ("correction", None),
        ("correction_borderline", None),
    ]


def test_confidence_at_the_threshold_does_not_retry() -> None:
    assert _tags([0.80], escalation_model=_SONNET) == [("correction", None)]


def test_cascade_off_ignores_cascade_triggers() -> None:
    assert _tags(
        [0.95],
        escalation_model=_SONNET,
        cascade_unaddressed_points=True,
        cascade_two_pass_disagreement=True,
    ) == [("correction", None)]
