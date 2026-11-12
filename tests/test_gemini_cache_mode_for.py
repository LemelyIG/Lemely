"""Cost-ladder Task 4: ``GeminiSettings.cache_mode_for`` overrides the cache mode per task tag.

Effective mode = explicit call-site ``cache_mode``, else ``cache_mode_for[task_tag]``,
else the client's ``default_cache_mode``.
"""

from __future__ import annotations

import tempfile
import unittest
from typing import Literal
from unittest.mock import MagicMock

from pydantic import BaseModel

from lemely.io.gemini import GeminiClient
from lemely.runtime.config import Settings
from tests.gemini_fakes import make_settings, mock_response

_Mode = Literal["read_write", "bypass", "refresh"]
_MODEL = "gemini-3.8-flash"


class _Schema(BaseModel):
    value: str


def _settings(tmp: str, cache_mode_for: dict[str, _Mode]) -> Settings:
    base = make_settings(tmp)
    return base.model_copy(
        update={"gemini": base.gemini.model_copy(update={"cache_mode_for": cache_mode_for})}
    )


class CacheModeForTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()

    def _client(self, cache_mode_for: dict[str, _Mode]) -> tuple[GeminiClient, MagicMock]:
        genai = MagicMock()
        genai.models.generate_content.side_effect = lambda **_: mock_response('{"value": "x"}')
        return GeminiClient(_settings(self.tmp, cache_mode_for), _genai_client=genai), genai

    def _call(self, client: GeminiClient, tag: str, **kwargs: _Mode) -> _Schema:
        return client.generate_structured(
            system_prompt="sys",
            user_prompt=f"user {tag}",
            response_schema=_Schema,
            prompt_version="1",
            model=_MODEL,
            task_tag=tag,
            **kwargs,
        )

    def _warm(self) -> None:
        client, _ = self._client({})
        self._call(client, "extraction")
        self._call(client, "correction")

    def test_tag_override_bypasses_only_that_tag(self) -> None:
        self._warm()
        client, genai = self._client({"correction": "bypass"})
        self._call(client, "extraction")
        self.assertEqual(genai.models.generate_content.call_count, 0)
        self._call(client, "correction")
        self.assertEqual(genai.models.generate_content.call_count, 1)

    def test_explicit_call_site_mode_wins(self) -> None:
        self._warm()
        client, genai = self._client({"correction": "bypass"})
        self._call(client, "correction", cache_mode="read_write")
        self.assertEqual(genai.models.generate_content.call_count, 0)

    def test_empty_map_is_todays_behaviour(self) -> None:
        self._warm()
        client, genai = self._client({})
        self._call(client, "extraction")
        self._call(client, "correction")
        self.assertEqual(genai.models.generate_content.call_count, 0)

    def test_effective_mode_resolution_order(self) -> None:
        client, _ = self._client({"escalation": "bypass"})
        self.assertEqual(client._effective_cache_mode(None, "escalation"), "bypass")
        self.assertEqual(client._effective_cache_mode(None, "extraction"), "read_write")
        self.assertEqual(client._effective_cache_mode(None, None), "read_write")
        self.assertEqual(client._effective_cache_mode("refresh", "escalation"), "refresh")

    def test_code_execution_honours_tag_override(self) -> None:
        def _ce_response() -> MagicMock:
            resp = MagicMock()
            part = MagicMock()
            part.code_execution_result.output = "42"
            resp.candidates = [MagicMock(content=MagicMock(parts=[part]))]
            resp.usage_metadata = MagicMock(
                prompt_token_count=10, candidates_token_count=20, thoughts_token_count=0
            )
            return resp

        def _client(cache_mode_for: dict[str, _Mode]) -> tuple[GeminiClient, MagicMock]:
            genai = MagicMock()
            genai.models.generate_content.side_effect = lambda **_: _ce_response()
            return GeminiClient(_settings(self.tmp, cache_mode_for), _genai_client=genai), genai

        def _run(client: GeminiClient) -> str:
            return client.generate_with_code_execution(
                prompt="p", prompt_version="1", model=_MODEL, task_tag="question_gate"
            )

        warm, _ = _client({})
        _run(warm)
        cached, cached_genai = _client({})
        _run(cached)
        self.assertEqual(cached_genai.models.generate_content.call_count, 0)
        bypassed, bypass_genai = _client({"question_gate": "bypass"})
        _run(bypassed)
        self.assertEqual(bypass_genai.models.generate_content.call_count, 1)


if __name__ == "__main__":
    unittest.main()
