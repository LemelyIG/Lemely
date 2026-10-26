"""Sub-project C lever H4c: the median of up to three borderline-retry marks."""

from __future__ import annotations

import tempfile
from unittest.mock import MagicMock, patch

from lemely.core.loose_schemas import QuestionType
from lemely.core.schemas import AIMarkResponse
from lemely.io import correction_ai
from lemely.io.correction_ai import AICorrector, _median_of
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
) -> tuple[AIMarkResponse, list[dict[str, object]], AICorrector]:
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
    return out, [dict(c.kwargs) for c in call.call_args_list], ai


def _tags(calls: list[dict[str, object]]) -> list[object]:
    return [c["task_tag"] for c in calls]


_ON = {"correction_retry_median": True, "escalation_model": None}


def test_off_by_default_the_retry_replaces() -> None:
    out, calls, _ = _run([_reply(1, 0.70), _reply(0, 0.95)])
    assert out.awarded_marks == 0
    assert len(calls) == 2


def test_on_agreeing_retry_stops_at_two() -> None:
    out, calls, _ = _run([_reply(1, 0.82), _reply(1, 0.91)], **_ON)
    assert (out.awarded_marks, out.confidence) == (1, 0.91)
    assert _tags(calls) == ["correction", "correction_borderline"]


def test_on_disagreement_draws_a_third_and_takes_the_median() -> None:
    out, calls, _ = _run([_reply(2, 0.70, "A"), _reply(0, 0.90, "B"), _reply(2, 0.80, "C")], **_ON)
    assert (out.awarded_marks, out.feedback, out.confidence) == (2, "C", 0.70)
    assert len(calls) == 3


def test_third_sample_has_its_own_cache_key() -> None:
    _, calls, _ = _run([_reply(2, 0.70), _reply(0, 0.90), _reply(2, 0.80)], **_ON)
    keys = [c["extra_cache_key"] for c in calls]
    assert keys == ["q=2", "q=2:thinking", "q=2:thinking:2"]
    assert len(set(keys)) == 3
    assert (calls[2]["task_tag"], calls[2]["attempt"]) == ("correction_borderline", "borderline")


def test_median_low_on_an_even_spread() -> None:
    out, _, _ = _run([_reply(0, 0.70), _reply(2, 0.90), _reply(1, 0.80)], **_ON)
    assert out.awarded_marks == 1


def test_on_the_retry_fires_below_the_lever_threshold() -> None:
    _, on_calls, _ = _run([_reply(1, 0.84), _reply(1, 0.9)], **_ON)
    assert _tags(on_calls) == ["correction", "correction_borderline"]
    _, off_calls, _ = _run([_reply(1, 0.84)])
    assert _tags(off_calls) == ["correction"]


def test_switched_off_borderline_makes_the_lever_inert() -> None:
    _, calls, _ = _run([_reply(1, 0.84)], correction_borderline_enabled=False, **_ON)
    assert _tags(calls) == ["correction"]


def test_magicmock_settings_leave_the_lever_off() -> None:
    client = MagicMock()
    client._settings.gemini.escalation_confidence_threshold = 0.8
    client._settings.gemini.escalation_model = None
    client.generate_structured.return_value = _reply(1, 0.95)
    ai = AICorrector(client)
    with (
        patch.object(ai, "_resolved_thinking", side_effect=["low", "high"]),
        patch.object(correction_ai, "_median_of") as med,
    ):
        ai._retry_low_confidence(MagicMock(id="2"), "s", "u", _reply(1, 0.7), prefix_kwargs={})
    med.assert_not_called()
    assert client.generate_structured.call_count == 1


def test_escalation_sees_the_combined_confidence() -> None:
    split = [_reply(2, 0.70), _reply(0, 0.90), _reply(2, 0.95), _reply(1, 0.99, "esc")]
    out, calls, _ = _run(split, correction_retry_median=True)
    assert _tags(calls)[3] == "escalation"
    assert out.feedback == "esc"
    _, calls, ai = _run(
        split[:3], defer=True, correction_retry_median=True, escalation_cap_per_script=1
    )
    assert len(calls) == 3
    assert ai.deferred["2"][4] == 0.70


def test_median_and_keep_higher_fail_the_run_not_the_leaves() -> None:
    import pytest

    from lemely.io.correction_ai import correct_paper
    from lemely.runtime.errors import ConfigError
    from tests.test_escalation_cap import _SCHEME
    from tests.test_reason_first import _client

    client = _client()
    client._settings.gemini.__dict__["correction_retry_median"] = True
    client._settings.gemini.__dict__["correction_retry_keep_higher"] = True
    with pytest.raises(ConfigError):
        AICorrector(client)
    with pytest.raises(ConfigError):
        correct_paper(_SCHEME, {"1a": "x", "2a": "y"}, gemini_client=client)


def test_median_of_two_against_one_takes_the_majority_zero() -> None:
    out = _median_of([_reply(2, 0.7, "first"), _reply(0, 0.9, "b"), _reply(0, 0.8, "c")])
    assert (out.awarded_marks, out.feedback) == (0, "b")


def test_median_of_a_split_vote_takes_the_minimum_confidence() -> None:
    out = _median_of([_reply(2, 0.95), _reply(0, 0.6), _reply(2, 0.9)])
    assert (out.awarded_marks, out.confidence) == (2, 0.6)


def test_median_of_unanimous_takes_the_most_confident() -> None:
    out = _median_of([_reply(1, 0.8, "a"), _reply(1, 0.95, "b"), _reply(1, 0.9, "c")])
    assert (out.feedback, out.confidence) == ("b", 0.95)


def test_median_of_two_agreeing_keeps_that_mark() -> None:
    assert _median_of([_reply(2, 0.8), _reply(2, 0.9)]).awarded_marks == 2


def test_median_of_leaves_an_omitted_field_omitted() -> None:
    data = {k: v for k, v in _VALID_MARK.items() if k != "addresses_question"}
    omitted = AIMarkResponse.model_validate({**data, "awarded_marks": 2, "confidence": 0.99})
    out = _median_of([omitted, _reply(2, 0.5)])
    assert out.confidence == 0.99
    assert "addresses_question" not in out.model_fields_set


def test_failed_third_sample_falls_back_to_the_lower_of_two() -> None:
    boom = RuntimeError("api down")
    out, calls, _ = _run(
        [_reply(2, 0.70, "A"), _reply(1, 0.90, "B"), boom],  # type: ignore[list-item]
        **_ON,
    )
    assert len(calls) == 3
    assert (out.awarded_marks, out.feedback, out.confidence) == (1, "B", 0.70)


def test_a_client_without_settings_constructs_with_every_lever_off() -> None:
    ai = AICorrector(MagicMock(spec=GeminiClient))
    assert ai.escalate_deferred() == {}
