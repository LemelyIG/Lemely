"""Sub-project C lever H2a: the borderline retry keeps the higher of the two marks."""

from __future__ import annotations

import tempfile
from unittest.mock import MagicMock, patch

from lemely.core.loose_schemas import QuestionType
from lemely.core.schemas import AIMarkResponse
from lemely.io import correction_ai
from lemely.io.correction_ai import AICorrector, _keep_higher
from lemely.io.gemini import GeminiClient
from tests.gemini_fakes import fake_genai_client, make_settings
from tests.test_anthropic_adapter import _VALID_MARK

_HAIKU, _SONNET = "claude-haiku-5-5", "claude-sonnet-5-5"


def _reply(marks: int, conf: float, feedback: str = "f") -> AIMarkResponse:
    return AIMarkResponse.model_validate(
        {**_VALID_MARK, "awarded_marks": marks, "confidence": conf, "feedback": feedback}
    )


def _run(
    replies: list[AIMarkResponse], *, defer: bool = False, **gemini: object
) -> tuple[AIMarkResponse, list[str], AICorrector]:
    settings = make_settings(tempfile.mkdtemp())
    g = settings.gemini.model_copy(
        update={"correction_model": _HAIKU, "escalation_model": _SONNET, **gemini}
    )
    client = GeminiClient(
        settings.model_copy(update={"gemini": g}), _genai_client=fake_genai_client(), ledger=None
    )
    ai = AICorrector(client)
    ai.defer_escalation = defer
    with (
        patch("lemely.io.correction_ai.build_marker_user_prompt", return_value="u"),
        patch.object(client, "generate_structured", side_effect=replies) as call,
    ):
        out = ai.mark_question(MagicMock(type=QuestionType.EXPLANATION, id="2", marks=2), "a")
    return out, [c.kwargs["task_tag"] for c in call.call_args_list], ai


def test_off_by_default_the_retry_replaces() -> None:
    out, tags, _ = _run([_reply(1, 0.70), _reply(0, 0.95)])
    assert out.awarded_marks == 0
    assert tags == ["correction", "correction_borderline"]


def test_on_keeps_the_higher_mark_and_its_feedback() -> None:
    out, _, _ = _run(
        [_reply(2, 0.70, "A"), _reply(1, 0.95, "B")],
        correction_retry_keep_higher=True,
        escalation_model=None,
    )
    assert (out.awarded_marks, out.feedback, out.confidence) == (2, "A", 0.70)


def test_on_agreeing_samples_keep_the_more_confident() -> None:
    out, _, _ = _run(
        [_reply(1, 0.82), _reply(1, 0.91)],
        correction_retry_keep_higher=True,
        escalation_model=None,
    )
    assert (out.awarded_marks, out.confidence) == (1, 0.91)


def test_on_the_retry_fires_below_the_lever_threshold() -> None:
    _, on_tags, _ = _run([_reply(1, 0.84), _reply(1, 0.9)], correction_retry_keep_higher=True)
    assert on_tags == ["correction", "correction_borderline"]
    _, off_tags, _ = _run([_reply(1, 0.84)])
    assert off_tags == ["correction"]


def test_on_disagreement_still_escalates_on_min_confidence() -> None:
    out, tags, _ = _run(
        [_reply(2, 0.75), _reply(1, 0.90), _reply(0, 0.99, "esc")],
        correction_retry_keep_higher=True,
    )
    assert tags == ["correction", "correction_borderline", "escalation"]
    assert out.feedback == "esc"


def test_on_deferred_escalation_stores_the_combined_confidence() -> None:
    _, tags, ai = _run(
        [_reply(2, 0.75), _reply(1, 0.90)],
        defer=True,
        correction_retry_keep_higher=True,
        escalation_cap_per_script=1,
    )
    assert tags == ["correction", "correction_borderline"]
    assert ai.deferred["2"][4] == 0.75


def test_switched_off_borderline_makes_the_lever_inert() -> None:
    _, tags, _ = _run(
        [_reply(1, 0.84)],
        correction_retry_keep_higher=True,
        correction_borderline_enabled=False,
    )
    assert tags == ["correction"]


def test_magicmock_settings_leave_the_lever_off() -> None:
    client = MagicMock()
    client._settings.gemini.escalation_confidence_threshold = 0.8
    client._settings.gemini.escalation_model = None
    client.generate_structured.return_value = _reply(1, 0.95)
    ai = AICorrector(client)
    with (
        patch.object(ai, "_resolved_thinking", side_effect=["low", "high"]),
        patch.object(correction_ai, "_keep_higher") as kh,
    ):
        ai._retry_low_confidence(MagicMock(id="2"), "s", "u", _reply(1, 0.7), prefix_kwargs={})
    kh.assert_not_called()
    assert client.generate_structured.call_count == 1


def test_keep_higher_higher_mark_wins_either_order() -> None:
    lo, hi = _reply(1, 0.9, "lo"), _reply(2, 0.8, "hi")
    for a, b in ((lo, hi), (hi, lo)):
        out = _keep_higher(a, b)
        assert (out.awarded_marks, out.feedback, out.confidence) == (2, "hi", 0.8)


def test_keep_higher_tie_takes_higher_confidence_then_retry() -> None:
    a, b = _reply(1, 0.8, "a"), _reply(1, 0.9, "b")
    assert _keep_higher(a, b).feedback == "b"
    assert _keep_higher(b, a).feedback == "b"
    assert _keep_higher(_reply(1, 0.8, "first"), _reply(1, 0.8, "retry")).feedback == "retry"


def test_keep_higher_leaves_an_omitted_field_omitted() -> None:
    data = {k: v for k, v in _VALID_MARK.items() if k != "addresses_question"}
    omitted = AIMarkResponse.model_validate({**data, "awarded_marks": 2})
    out = _keep_higher(omitted, _reply(1, 0.9))
    assert "addresses_question" not in out.model_fields_set
