"""Spec 2026-10-19 §1: Gemini and Claude providers behind GeminiClient, no behaviour change."""

from __future__ import annotations

import tempfile
import unittest
from typing import Any
from unittest.mock import MagicMock

from pydantic import BaseModel, SecretStr

from lemely.io.gemini import GeminiClient
from lemely.io.llm.claude_provider import ClaudeProvider, usage_as_gemini_response
from lemely.io.llm.errors import TransientCallError
from lemely.io.llm.gemini_provider import GeminiProvider
from lemely.io.llm.provider import Usage
from lemely.io.llm.request import CodeExecution
from lemely.io.providers import ProviderTransientError
from lemely.runtime.errors import ExternalServiceError
from tests.gemini_fakes import fake_genai_client, make_settings, mock_response


class _Reply(BaseModel):
    value: str


def _client(genai: Any = None, anthropic_client: Any = None) -> GeminiClient:
    settings = make_settings(tempfile.mkdtemp()).model_copy(
        update={"anthropic_api_key": SecretStr("test-key")}
    )
    return GeminiClient(
        settings,
        _genai_client=genai or fake_genai_client(),
        _anthropic_client=anthropic_client,
        ledger=None,
    )


class GeminiProviderTests(unittest.TestCase):
    def test_reply_carries_text_stop_and_the_raw_response(self) -> None:
        genai = fake_genai_client()
        response = mock_response('{"value": "ok"}', finish_reason="MAX_TOKENS")
        genai.models.generate_content.return_value = response
        client = _client(genai)
        req = client._build_request(
            model="gemini-3.8-flash",
            task_tag="extraction",
            system_prompt="sys",
            user_prompt="user",
            response_schema=_Reply,
        )
        reply = GeminiProvider(client).complete(req, log=MagicMock())
        self.assertEqual(reply.text, '{"value": "ok"}')
        self.assertEqual(reply.stop_reason, "max_tokens")
        self.assertEqual(reply.stop_detail, str(response.candidates[0].finish_reason))
        self.assertIs(reply.usage_response, response)

    def test_transient_sdk_error_becomes_transient_call_error(self) -> None:
        genai = fake_genai_client()
        genai.models.generate_content.side_effect = Exception("503 unavailable")
        client = _client(genai)
        req = client._build_request(
            model="gemini-3.8-flash",
            task_tag="correction",
            system_prompt="s",
            user_prompt="u",
            response_schema=_Reply,
        )
        with self.assertRaises(TransientCallError):
            GeminiProvider(client).complete(req, log=MagicMock())

    def test_code_execution_reply_is_the_executed_output(self) -> None:
        genai = fake_genai_client()
        response = mock_response("", prompt=5, candidates=1)
        part = MagicMock()
        part.code_execution_result.output = "42"
        response.candidates[0].content.parts = [part]
        genai.models.generate_content.return_value = response
        client = _client(genai)
        req = client._build_request(
            model="gemini-2.5-flash",
            task_tag="question_validity",
            system_prompt="",
            user_prompt="compute",
            response_schema=None,
            tool=CodeExecution(),
        )
        self.assertEqual(GeminiProvider(client).complete(req, log=MagicMock()).text, "42")


class _RaisingAdapter:
    def complete(self, **kwargs: Any) -> Any:
        raise ProviderTransientError("529 overloaded")


class ClaudeProviderTests(unittest.TestCase):
    def test_adapter_transient_becomes_transient_call_error(self) -> None:
        client = _client()
        req = client._build_request(
            model="claude-haiku-5-5",
            task_tag="correction",
            system_prompt="s",
            user_prompt="u",
            response_schema=_Reply,
        )
        with self.assertRaises(TransientCallError):
            ClaudeProvider(_RaisingAdapter(), client._settings).complete(req, log=MagicMock())  # type: ignore[arg-type]

    def test_usage_in_the_gemini_shape(self) -> None:
        shaped = usage_as_gemini_response(
            Usage(input_tokens=100, cached_tokens=40, output_tokens=30, thinking_tokens=10)
        )
        meta = shaped.usage_metadata
        self.assertEqual(
            (
                meta.prompt_token_count,
                meta.candidates_token_count,
                meta.thoughts_token_count,
                meta.cached_content_token_count,
            ),
            (100, 20, 10, 40),
        )


class DispatchTests(unittest.TestCase):
    def test_provider_by_model_prefix(self) -> None:
        client = _client(anthropic_client=MagicMock())
        self.assertIsInstance(client._provider_for_model("gemini-3.8-flash"), GeminiProvider)
        claude = client._provider_for_model("claude-haiku-5-5")
        self.assertIsInstance(claude, ClaudeProvider)
        self.assertIs(client._provider_for_model("claude-haiku-5-5"), claude)

    def test_claude_request_splits_a_shared_prefix(self) -> None:
        from lemely.io.gemini import SharedPrefix

        prefix = SharedPrefix(instructions="I", paper="P", text="IP", cache="implicit", version="v")
        client = _client()
        req = client._build_request(
            model="claude-haiku-5-5",
            task_tag="correction",
            system_prompt="IP",
            user_prompt="u",
            response_schema=_Reply,
            shared_prefix=prefix,
        )
        self.assertEqual((req.system, req.cache_prefix, req.shared_prefix), ("I", "P", None))

    def test_unknown_error_from_claude_adapter_is_not_rewrapped(self) -> None:
        class _Broken:
            def complete(self, **kwargs: Any) -> Any:
                raise ExternalServiceError("permanent")

        client = _client()
        req = client._build_request(
            model="claude-haiku-5-5",
            task_tag="correction",
            system_prompt="s",
            user_prompt="u",
            response_schema=_Reply,
        )
        with self.assertRaisesRegex(ExternalServiceError, "permanent"):
            ClaudeProvider(_Broken(), client._settings).complete(req, log=MagicMock())  # type: ignore[arg-type]
