"""Unit tests for lemely.io.gemini.GeminiClient (genai.Client mocked)."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from pydantic import BaseModel

from lemely.io.gemini import GeminiClient, _reset_process_counters, _strip_schema
from lemely.runtime.config import PathsSettings, load_settings
from lemely.runtime.errors import ExternalServiceError, ParseError


class _SimpleSchema(BaseModel):
    value: str


class _RecursiveSchema(BaseModel):
    """Simulates Question.parts: list[Question] — Pydantic emits a circular $ref."""

    value: str
    children: list[_RecursiveSchema] = []


class StripSchemaTests(unittest.TestCase):
    def test_circular_ref_does_not_recurse(self) -> None:
        """_strip_schema must not raise RecursionError on self-referential models."""
        schema = _RecursiveSchema.model_json_schema()
        # Sanity: Pydantic does generate a circular $ref for this model.
        self.assertIn("$defs", schema)
        result = _strip_schema(schema)
        # Should complete without RecursionError and return a dict.
        self.assertIsInstance(result, dict)

    def test_circular_ref_replaced_with_object(self) -> None:
        """The leaf of a circular $ref chain becomes {"type": "object"}."""
        schema = _RecursiveSchema.model_json_schema()
        result = _strip_schema(schema)
        # Navigate to the children items — it should be {"type": "object"}.
        props = result.get("properties", {})
        children_items = props.get("children", {}).get("items", {})
        self.assertEqual(children_items, {"type": "object"})


def _mock_response(text: str, in_tok: int = 10, out_tok: int = 20) -> MagicMock:
    resp = MagicMock()
    resp.text = text
    cand = MagicMock()
    finish = MagicMock()
    finish.__str__ = lambda self: "STOP"
    cand.finish_reason = finish
    resp.candidates = [cand]
    resp.usage_metadata = MagicMock(
        prompt_token_count=in_tok,
        candidates_token_count=out_tok,
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
    # Redirect output_dir (persistent ledger lives here) and cache_dir into the
    # tmp dir so the cross-run gemini_spend.json never touches the real repo.
    s = s.model_copy(
        update={
            "paths": PathsSettings(
                cache_dir=Path(tmp) / ".cache",
                output_dir=Path(tmp) / "outputs",
            )
        }
    )
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
                system_prompt="sys",
                user_prompt="user",
                response_schema=_SimpleSchema,
                prompt_version="1",
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
            system_prompt="s",
            user_prompt="u",
            response_schema=_SimpleSchema,
            prompt_version="1",
        )
        r2 = client.generate_structured(
            system_prompt="s",
            user_prompt="u",
            response_schema=_SimpleSchema,
            prompt_version="2",
        )
        self.assertEqual((r1.value, r2.value), ("v1", "v2"))

    def test_cost_guard_raises_after_token_ceiling(self) -> None:
        mock_genai = MagicMock()
        mock_genai.models.generate_content.return_value = _mock_response(
            '{"value": "x"}',
            in_tok=500,
            out_tok=600,
        )
        mock_genai.files.upload.return_value = MagicMock()
        settings = _make_settings(self.tmp, per_run_token_ceiling=100)
        client = GeminiClient(settings, _genai_client=mock_genai)

        client.generate_structured(
            system_prompt="s",
            user_prompt="u1",
            response_schema=_SimpleSchema,
            prompt_version="1",
        )
        with self.assertRaises(ExternalServiceError):
            client.generate_structured(
                system_prompt="s",
                user_prompt="u2",
                response_schema=_SimpleSchema,
                prompt_version="1",
            )

    def test_usd_ceiling_raises_from_persistent_ledger(self) -> None:
        """The USD ceiling is enforced against the persistent ledger, so a
        FRESH client instance is still blocked once the ledger is past ceiling."""
        from lemely.io.cost_ledger import CostLedger

        settings = _make_settings(self.tmp, total_usd_ceiling=8.0)
        # Pre-load the on-disk ledger past $8 (simulating prior process spend).
        ledger = CostLedger(settings.paths.output_dir / "gemini_spend.json")
        ledger.add(8.5, thresholds=[])

        mock_genai = MagicMock()
        mock_genai.models.generate_content.return_value = _mock_response('{"value": "x"}')
        mock_genai.files.upload.return_value = MagicMock()
        # Brand-new client instance — enforcement must come from disk, not memory.
        client = GeminiClient(settings, _genai_client=mock_genai)

        with self.assertRaises(ExternalServiceError):
            client.generate_structured(
                system_prompt="s",
                user_prompt="u",
                response_schema=_SimpleSchema,
                prompt_version="1",
            )
        # The blocked call never reached the API.
        self.assertEqual(mock_genai.models.generate_content.call_count, 0)

    def test_budget_warning_published_once_per_threshold(self) -> None:
        """Each warning threshold publishes BUDGET_WARNING exactly once, even
        across multiple Gemini calls."""
        from lemely.runtime.events import EventType, bus

        # Large token counts so a single call comfortably crosses $4.
        # flash pricing: 0.000150/1k in, 0.000600/1k out → tune to ~$4.5/call.
        settings = _make_settings(
            self.tmp,
            total_usd_ceiling=None,  # disable the hard block for this test
            usd_warning_thresholds=[4.0, 6.0],
        )
        mock_genai = MagicMock()
        mock_genai.models.generate_content.return_value = _mock_response(
            '{"value": "x"}',
            in_tok=10_000_000,
            out_tok=5_000_000,
        )
        mock_genai.files.upload.return_value = MagicMock()
        client = GeminiClient(settings, _genai_client=mock_genai)

        seen: list[float] = []

        def _spy(**payload: object) -> None:
            seen.append(float(payload["threshold"]))  # type: ignore[arg-type]

        bus.subscribe(EventType.BUDGET_WARNING, _spy)
        try:
            for i in range(3):
                client.generate_structured(
                    system_prompt="s",
                    user_prompt=f"u{i}",
                    response_schema=_SimpleSchema,
                    prompt_version="1",
                )
        finally:
            bus.unsubscribe(EventType.BUDGET_WARNING, _spy)

        # Both thresholds fired, each exactly once.
        self.assertEqual(sorted(seen), [4.0, 6.0])

    def test_transient_error_after_retries_raises_external_service_error(self) -> None:
        """A 503 that survives all retries must surface as the public
        ExternalServiceError, never the private _TransientError, so batch
        callers can catch it without importing internals."""
        mock_genai = MagicMock()
        mock_genai.models.generate_content.side_effect = RuntimeError(
            "503 UNAVAILABLE. This model is currently experiencing high demand."
        )
        mock_genai.files.upload.return_value = MagicMock()
        client = GeminiClient(
            _make_settings(self.tmp, max_retries=0),
            _genai_client=mock_genai,
        )

        with self.assertRaises(ExternalServiceError):
            client.generate_structured(
                system_prompt="s",
                user_prompt="u",
                response_schema=_SimpleSchema,
                prompt_version="1",
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
                system_prompt="s",
                user_prompt="u",
                response_schema=_SimpleSchema,
                prompt_version="1",
            )
