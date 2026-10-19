"""Cost-ladder B12: a per-task-tag output-token cap on Gemini calls."""

from __future__ import annotations

import tempfile
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel, ValidationError

from lemely.io import gemini as gemini_module
from lemely.io.gemini import (
    GeminiClient,
    _reset_process_counters,
    process_call_records,
    set_call_context,
)
from lemely.runtime.config import GeminiSettings, Settings
from lemely.runtime.errors import CostCeilingError, ExternalServiceError, ParseError
from tests.gemini_fakes import make_settings, mock_response

_MODEL = "gemini-3.8-flash"


class _Schema(BaseModel):
    value: str


def _settings(caps: dict[str, int]) -> Settings:
    base = make_settings(tempfile.mkdtemp())
    gemini = base.gemini.model_copy(update={"max_output_tokens_for": caps, "backoff_seconds": 0.01})
    return base.model_copy(update={"gemini": gemini})


def _client(settings: Settings, *responses: MagicMock) -> tuple[GeminiClient, MagicMock]:
    genai = MagicMock()
    genai.models.generate_content.side_effect = list(responses)
    return GeminiClient(settings, _genai_client=genai), genai


def _call(client: GeminiClient, tag: str = "extraction") -> _Schema:
    return client.generate_structured(
        system_prompt="s",
        user_prompt="u",
        response_schema=_Schema,
        prompt_version="1",
        model=_MODEL,
        task_tag=tag,
    )


def _sent_cap(genai: MagicMock) -> int:
    return int(genai.models.generate_content.call_args.kwargs["config"].max_output_tokens)


def _truncated(text: str = '{"value": "x') -> MagicMock:
    return mock_response(text, candidates=500, thoughts=100, finish_reason="MAX_TOKENS")


def test_setting_defaults_empty_and_bounded() -> None:
    assert GeminiSettings().max_output_tokens_for == {}
    assert GeminiSettings(max_output_tokens_for={"extraction": 8000}).max_output_tokens_for == {
        "extraction": 8000
    }
    for bad in (0, -1):
        with pytest.raises(ValidationError):
            GeminiSettings(max_output_tokens_for={"extraction": bad})


def test_default_sends_constant_and_fingerprint_unchanged() -> None:
    client, genai = _client(_settings({}), mock_response('{"value": "a"}'))
    _call(client)
    assert _sent_cap(genai) == gemini_module._MAX_OUTPUT_TOKENS
    # An unrelated tag's cap leaves this tag's fingerprint untouched.
    other = GeminiClient(_settings({"other": 100}), _genai_client=MagicMock())
    assert client._params_fingerprint(_MODEL, "extraction", _Schema) == other._params_fingerprint(
        _MODEL, "extraction", _Schema
    )


def test_per_tag_cap_sent_and_fingerprinted() -> None:
    client, genai = _client(_settings({"extraction": 8000}), mock_response('{"value": "a"}'))
    _call(client)
    assert _sent_cap(genai) == 8000
    plain = GeminiClient(_settings({}), _genai_client=MagicMock())
    assert client._params_fingerprint(_MODEL, "extraction", _Schema) != plain._params_fingerprint(
        _MODEL, "extraction", _Schema
    )
    # Another tag still gets the default and the old fingerprint.
    assert client._params_fingerprint(_MODEL, "other", _Schema) == plain._params_fingerprint(
        _MODEL, "other", _Schema
    )


def test_cap_does_not_touch_anthropic_fingerprint() -> None:
    capped = GeminiClient(_settings({"extraction": 8000}), _genai_client=MagicMock())
    plain = GeminiClient(_settings({}), _genai_client=MagicMock())
    model = "claude-sonnet-5-5"
    assert capped._params_fingerprint(model, "extraction", _Schema) == plain._params_fingerprint(
        model, "extraction", _Schema
    )


def test_truncated_twice_raises_after_exactly_two_calls_both_billed() -> None:
    _reset_process_counters()
    client, genai = _client(
        _settings({"extraction": 8000}), _truncated(), _truncated(), _truncated(), _truncated()
    )
    with patch("lemely.io.gemini.time.sleep"), pytest.raises(ExternalServiceError) as err:
        _call(client)
    assert genai.models.generate_content.call_count == 2
    records = process_call_records()
    assert len(records) == 2
    assert all(r.parse_ok is False and r.output_tokens > 0 and r.usd_now > 0 for r in records)
    assert "8000" in str(err.value)


def test_truncated_then_ok_makes_one_fresh_call_and_bills_both() -> None:
    _reset_process_counters()
    client, genai = _client(
        _settings({"extraction": 8000}), _truncated(), mock_response('{"value": "a"}')
    )
    set_call_context(case_key=None)
    assert _call(client).value == "a"
    assert genai.models.generate_content.call_count == 2
    first, second = (c.kwargs for c in genai.models.generate_content.call_args_list)
    assert first["contents"] == second["contents"]
    assert first["config"].max_output_tokens == second["config"].max_output_tokens == 8000
    # Same request, not a schema-correction prompt.
    assert "failed validation" not in str(second["contents"])
    r1, r2 = process_call_records()
    assert (r1.parse_ok, r2.parse_ok) == (False, True)
    assert (r1.attempt, r1.question_id) == (r2.attempt, r2.question_id)
    assert r1.usd_now > 0 and r2.usd_now > 0


def test_ceiling_checked_before_the_retry() -> None:
    _reset_process_counters()
    base = _settings({"extraction": 8000})
    settings = base.model_copy(
        update={"gemini": base.gemini.model_copy(update={"per_run_token_ceiling": 100})}
    )
    client, genai = _client(settings, _truncated(), mock_response('{"value": "a"}'))
    with pytest.raises(CostCeilingError):
        _call(client)
    assert genai.models.generate_content.call_count == 1


def test_default_path_truncation_goes_to_schema_correction_then_parse_error() -> None:
    # The old str() comparison never matched the real enum, so on the default path
    # a truncated reply is just unparseable JSON: one schema-correction call, then
    # ParseError. Pinned so a global "fix" is a deliberate decision.
    _reset_process_counters()
    client, genai = _client(_settings({}), _truncated(), _truncated())
    with pytest.raises(ParseError):
        _call(client)
    assert genai.models.generate_content.call_count == 2
    first, second = (c.kwargs for c in genai.models.generate_content.call_args_list)
    assert "failed validation" not in str(first["contents"])
    assert "failed validation" in str(second["contents"])
    records = process_call_records()
    assert [r.parse_ok for r in records] == [False, False]
