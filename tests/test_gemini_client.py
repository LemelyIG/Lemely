"""Unit tests for lemely.io.gemini.GeminiClient (genai.Client mocked)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from pydantic import BaseModel

from lemely.io.gemini import GeminiClient, _reset_process_counters
from lemely.runtime.config import GeminiSettings, PathsSettings, load_settings
from lemely.runtime.errors import ExternalServiceError, ParseError


class _SimpleSchema(BaseModel):
    value: str


def _mock_response(text: str, in_tok: int = 10, out_tok: int = 20) -> MagicMock:
    resp = MagicMock()
    resp.text = text
    cand = MagicMock()
    finish = MagicMock()
    finish.__str__ = lambda self: "STOP"
    cand.finish_reason = finish
    resp.candidates = [cand]
    resp.usage_metadata = MagicMock(
        prompt_token_count=in_tok, candidates_token_count=out_tok,
    )
    return resp


class _IsolatedEnv:
    def __enter__(self) -> _IsolatedEnv:
        self._snap = dict(os.environ)
        for k in list(os.environ):
            if k.startswith("LEMELY_"):
                del os.environ[k]
        return self

    def __exit__(self, *_: object) -> None:
        os.environ.clear()
        os.environ.update(self._snap)


def _make_settings(tmp: str, **gemini_overrides: object):
    with _IsolatedEnv():
        s = load_settings(toml_path=None, cwd=Path(tmp))
    s = s.model_copy(update={"paths": PathsSettings(cache_dir=Path(tmp) / ".cache")})
    if gemini_overrides:
        s = s.model_copy(update={"gemini": s.gemini.model_copy(update=gemini_overrides)})
    return s


class GeminiClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        _reset_process_counters()

    def test_cache_hit_skips_api(self) -> None:
        mock_genai = MagicMock()
        mock_genai.models.generate_content.return_value = _mock_response('{"value": "hi"}')
        mock_genai.files.upload.return_value = MagicMock()
        client = GeminiClient(_make_settings(self.tmp), _genai_client=mock_genai)

        for _ in range(2):
            r = client.generate_structured(
                system_prompt="sys", user_prompt="user",
                response_schema=_SimpleSchema, prompt_version="1",
            )
            self.assertEqual(r.value, "hi")
        self.assertEqual(mock_genai.models.generate_content.call_count, 1)

    def test_version_bump_busts_cache(self) -> None:
        mock_genai = MagicMock()
        mock_genai.models.generate_content.side_effect = [
            _mock_response('{"value": "v1"}'),
            _mock_response('{"value": "v2"}'),
        ]
        mock_genai.files.upload.return_value = MagicMock()
        client = GeminiClient(_make_settings(self.tmp), _genai_client=mock_genai)

        r1 = client.generate_structured(
            system_prompt="s", user_prompt="u", response_schema=_SimpleSchema, prompt_version="1",
        )
        r2 = client.generate_structured(
            system_prompt="s", user_prompt="u", response_schema=_SimpleSchema, prompt_version="2",
        )
        self.assertEqual((r1.value, r2.value), ("v1", "v2"))

    def test_cost_guard_raises_after_token_ceiling(self) -> None:
        mock_genai = MagicMock()
        mock_genai.models.generate_content.return_value = _mock_response(
            '{"value": "x"}', in_tok=500, out_tok=600,
        )
        mock_genai.files.upload.return_value = MagicMock()
        settings = _make_settings(self.tmp, per_run_token_ceiling=100)
        client = GeminiClient(settings, _genai_client=mock_genai)

        client.generate_structured(
            system_prompt="s", user_prompt="u1",
            response_schema=_SimpleSchema, prompt_version="1",
        )
        with self.assertRaises(ExternalServiceError):
            client.generate_structured(
                system_prompt="s", user_prompt="u2",
                response_schema=_SimpleSchema, prompt_version="1",
            )

    def test_schema_validation_failure_raises_parse_error(self) -> None:
        mock_genai = MagicMock()
        mock_genai.models.generate_content.return_value = _mock_response('{"wrong": "key"}')
        mock_genai.files.upload.return_value = MagicMock()
        client = GeminiClient(
            _make_settings(self.tmp, max_retries=0),
            _genai_client=mock_genai,
        )

        with self.assertRaises(ParseError):
            client.generate_structured(
                system_prompt="s", user_prompt="u",
                response_schema=_SimpleSchema, prompt_version="1",
            )
