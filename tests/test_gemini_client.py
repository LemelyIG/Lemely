"""Unit tests for lemely.io.gemini.GeminiClient (genai.Client mocked)."""

from __future__ import annotations

import hashlib
import inspect
import os
import tempfile
import threading
import time
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import structlog
from pydantic import BaseModel, Field
from structlog.testing import capture_logs

from lemely.io.gemini import (
    _MAX_OUTPUT_TOKENS,
    GeminiClient,
    _is_3x,
    _reset_process_counters,
    _strip_schema,
    process_token_totals,
    process_token_totals_by_task,
)
from lemely.runtime.config import PathsSettings, load_settings
from lemely.runtime.errors import CostCeilingError, ExternalServiceError, ParseError
from lemely.runtime.events import EventType, bus
from tests.gemini_fakes import fake_genai_client


class _SimpleSchema(BaseModel):
    value: str


class _PatternSchema(BaseModel):
    """A schema carrying a JSON-Schema `pattern` keyword (F1 3.x strip target)."""

    subject_code: str = Field(pattern=r"^\d{4}$")


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

    def test_pattern_dropped_for_3x(self) -> None:
        """F1 acceptance (3): no schema sent to a 3.x model contains `pattern`."""
        schema = _PatternSchema.model_json_schema()
        self.assertIn("pattern", schema["properties"]["subject_code"])
        result = _strip_schema(schema, is_3x=True)
        self.assertNotIn("pattern", result["properties"]["subject_code"])

    def test_pattern_kept_for_25(self) -> None:
        """2.5 still accepts (and receives) the `pattern` keyword."""
        schema = _PatternSchema.model_json_schema()
        result = _strip_schema(schema, is_3x=False)
        self.assertIn("pattern", result["properties"]["subject_code"])


def _level(v: object) -> str | None:
    """Normalise a ``types.ThinkingLevel`` (or a plain string) to lowercase.

    The SDK coerces the ``thinking_level`` kwarg into a
    ``types.ThinkingLevel`` enum member (``ThinkingLevel.LOW``, value
    ``"LOW"``), so a bare string comparison against the lowercase config
    value always fails even though the level round-tripped correctly.
    """
    if v is None:
        return None
    value = getattr(v, "value", v)
    return str(value).lower()


def _mock_response(
    text: str, in_tok: int = 10, out_tok: int = 20, thoughts_tok: int = 0
) -> MagicMock:
    """A stubbed Gemini response.

    ``thoughts_tok`` is set explicitly, and defaults to 0, because a bare
    MagicMock auto-creates any attribute asked of it: the client reads
    ``int(getattr(um, "thoughts_token_count", 0) or 0)``, and ``int(MagicMock())``
    is 1 — so leaving it unset silently added a phantom thinking token to every
    mocked call and inflated every token and USD figure derived from one.
    """
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
        thoughts_token_count=thoughts_tok,
    )
    return resp


def _mock_response_without_thoughts_attr(
    text: str, in_tok: int = 10, out_tok: int = 20
) -> MagicMock:
    """A response whose usage_metadata genuinely lacks ``thoughts_token_count``.

    Real GA responses for a call made with no thinking budget omit the field
    entirely, so the ``getattr(..., 0)`` default is a live code path, not
    defensive padding. ``spec=[...]`` is what stops MagicMock inventing it.
    """
    resp = MagicMock()
    resp.text = text
    cand = MagicMock()
    finish = MagicMock()
    finish.__str__ = lambda self: "STOP"
    cand.finish_reason = finish
    resp.candidates = [cand]
    um = MagicMock(spec=["prompt_token_count", "candidates_token_count"])
    um.prompt_token_count = in_tok
    um.candidates_token_count = out_tok
    resp.usage_metadata = um
    return resp


def _mock_code_execution_response(
    output: str, in_tok: int = 10, out_tok: int = 20, thoughts_tok: int = 0
) -> MagicMock:
    """A stubbed Gemini response carrying a ``code_execution_result`` part,
    shaped like the real ``google-genai`` SDK response to a call with the
    ``code_execution`` tool enabled: ``candidates[0].content.parts`` holds
    one part whose ``code_execution_result.output`` is the executed code's
    printed output."""
    resp = MagicMock()
    part = MagicMock()
    part.code_execution_result.output = output
    content = MagicMock()
    content.parts = [part]
    cand = MagicMock()
    cand.content = content
    resp.candidates = [cand]
    resp.usage_metadata = MagicMock(
        prompt_token_count=in_tok,
        candidates_token_count=out_tok,
        thoughts_token_count=thoughts_tok,
    )
    return resp


def _mock_response_without_code_execution_result(in_tok: int = 10, out_tok: int = 20) -> MagicMock:
    """A response whose parts carry no ``code_execution_result`` at all —
    the model answered in prose instead of running code."""
    resp = MagicMock()
    part = MagicMock(spec=[])
    content = MagicMock()
    content.parts = [part]
    cand = MagicMock()
    cand.content = content
    resp.candidates = [cand]
    resp.usage_metadata = MagicMock(
        prompt_token_count=in_tok, candidates_token_count=out_tok, thoughts_token_count=0
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


def _capture(event_type: EventType) -> tuple[list[dict], Callable[[], None]]:
    """Record every payload published on ``event_type``; call the returned
    function to unsubscribe (``bus`` is a process-wide singleton)."""
    seen: list[dict] = []

    def _spy(**payload: object) -> None:
        seen.append(payload)

    bus.subscribe(event_type, _spy)
    return seen, lambda: bus.unsubscribe(event_type, _spy)


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

    def test_default_pricing_is_ga_rate(self) -> None:
        """_DEFAULT_PRICING must carry GA rates, not the stale preview sheet."""
        from lemely.io.gemini import _DEFAULT_PRICING

        self.assertEqual(_DEFAULT_PRICING["gemini-2.5-flash"], (0.000300, 0.002500))
        self.assertEqual(_DEFAULT_PRICING["gemini-2.5-flash-lite"], (0.000100, 0.000400))
        self.assertEqual(_DEFAULT_PRICING["gemini-2.5-pro"], (0.001250, 0.010000))

    def test_params_fingerprint_cache_hit_and_miss(self) -> None:
        """Two calls with identical temperature/top_p/seed hit the cache; two
        with a differing seed do not — _cache_key must fold in a
        params_fingerprint derived from the resolved generation params."""
        mock_genai = MagicMock()
        mock_genai.models.generate_content.side_effect = [
            _mock_response('{"value": "a"}'),
            _mock_response('{"value": "b"}'),
        ]
        mock_genai.files.upload.return_value = MagicMock()
        settings = _make_settings(self.tmp, temperature=0.2, top_p=0.9, seed=42)
        client = GeminiClient(settings, _genai_client=mock_genai)

        r1 = client.generate_structured(
            system_prompt="s",
            user_prompt="u",
            response_schema=_SimpleSchema,
            prompt_version="1",
        )
        # Identical params → cache hit, no second API call.
        r1b = client.generate_structured(
            system_prompt="s",
            user_prompt="u",
            response_schema=_SimpleSchema,
            prompt_version="1",
        )
        self.assertEqual((r1.value, r1b.value), ("a", "a"))
        self.assertEqual(mock_genai.models.generate_content.call_count, 1)

        # Different seed → different params_fingerprint → cache miss, second call.
        settings2 = _make_settings(self.tmp, temperature=0.2, top_p=0.9, seed=43)
        client2 = GeminiClient(settings2, _genai_client=mock_genai)
        r2 = client2.generate_structured(
            system_prompt="s",
            user_prompt="u",
            response_schema=_SimpleSchema,
            prompt_version="1",
        )
        self.assertEqual(r2.value, "b")
        self.assertEqual(mock_genai.models.generate_content.call_count, 2)

    def test_cache_mode_bypass_ignores_existing_cache_entry(self) -> None:
        """cache_mode='bypass' must call the API even when a cache entry exists."""
        mock_genai = MagicMock()
        mock_genai.models.generate_content.side_effect = [
            _mock_response('{"value": "first"}'),
            _mock_response('{"value": "second"}'),
        ]
        mock_genai.files.upload.return_value = MagicMock()
        client = GeminiClient(_make_settings(self.tmp), _genai_client=mock_genai)

        r1 = client.generate_structured(
            system_prompt="s",
            user_prompt="u",
            response_schema=_SimpleSchema,
            prompt_version="1",
        )
        self.assertEqual(r1.value, "first")
        self.assertEqual(mock_genai.models.generate_content.call_count, 1)

        r2 = client.generate_structured(
            system_prompt="s",
            user_prompt="u",
            response_schema=_SimpleSchema,
            prompt_version="1",
            cache_mode="bypass",
        )
        self.assertEqual(r2.value, "second")
        self.assertEqual(mock_genai.models.generate_content.call_count, 2)

    def test_cache_mode_refresh_overwrites_existing_entry(self) -> None:
        """cache_mode='refresh' calls the API and overwrites the stale entry."""
        mock_genai = MagicMock()
        mock_genai.models.generate_content.side_effect = [
            _mock_response('{"value": "stale"}'),
            _mock_response('{"value": "fresh"}'),
        ]
        mock_genai.files.upload.return_value = MagicMock()
        client = GeminiClient(_make_settings(self.tmp), _genai_client=mock_genai)

        client.generate_structured(
            system_prompt="s",
            user_prompt="u",
            response_schema=_SimpleSchema,
            prompt_version="1",
        )
        r2 = client.generate_structured(
            system_prompt="s",
            user_prompt="u",
            response_schema=_SimpleSchema,
            prompt_version="1",
            cache_mode="refresh",
        )
        self.assertEqual(r2.value, "fresh")

        # A subsequent read_write call must now read the refreshed entry, not
        # make a third API call.
        r3 = client.generate_structured(
            system_prompt="s",
            user_prompt="u",
            response_schema=_SimpleSchema,
            prompt_version="1",
        )
        self.assertEqual(r3.value, "fresh")
        self.assertEqual(mock_genai.models.generate_content.call_count, 2)

    def test_thinking_tokens_counted_in_ledger(self) -> None:
        """thoughts_token_count must be folded into the output-token/usd ledger,
        not just candidates_token_count."""
        from lemely.io.gemini import process_token_totals

        resp_no_thinking = _mock_response('{"value": "a"}', in_tok=100, out_tok=50)
        resp_with_thinking = _mock_response('{"value": "b"}', in_tok=100, out_tok=50)
        resp_with_thinking.usage_metadata.thoughts_token_count = 200

        mock_genai = MagicMock()
        mock_genai.models.generate_content.side_effect = [
            resp_no_thinking,
            resp_with_thinking,
        ]
        mock_genai.files.upload.return_value = MagicMock()
        client = GeminiClient(_make_settings(self.tmp), _genai_client=mock_genai)

        client.generate_structured(
            system_prompt="s",
            user_prompt="u1",
            response_schema=_SimpleSchema,
            prompt_version="1",
        )
        _, out_after_first = process_token_totals()

        client.generate_structured(
            system_prompt="s",
            user_prompt="u2",
            response_schema=_SimpleSchema,
            prompt_version="1",
        )
        _, out_after_second = process_token_totals()

        # The second call's thinking budget (200 thoughts tokens) must be
        # reflected, so output tokens grow by more than candidates_token_count
        # (50) alone would account for.
        self.assertGreater(out_after_second - out_after_first, 50)
        self.assertEqual(out_after_second - out_after_first, 250)

    def test_bypassed_multi_sweep_does_not_trip_token_ceiling(self) -> None:
        """A cache-bypassed 2-sweep run completes under a run-sized ceiling.

        Deliberately calls NO reset anywhere: the counters accumulate straight
        through both sweeps, exactly as they do in production. That is the
        point — ``per_run_token_ceiling`` budgets the whole run, so the fix for
        the false trip is sizing it for a run (lemely.toml uses 2,000,000
        against ~115k tokens/sweep), not resetting between sweeps.

        An earlier version of this test called ``reset_process_counters()``
        inside its own sweep loop. That made it vacuous: it passed identically
        against the pre-existing private helper and failed only when the
        in-test reset was removed, so it certified the workaround rather than
        the shipped behaviour.
        """
        mock_genai = MagicMock()
        # ~70 calls/sweep, ~1650 tokens/call ≈ 115k tokens/sweep, ~230k for two.
        mock_genai.models.generate_content.side_effect = [
            _mock_response('{"value": "x"}', in_tok=800, out_tok=850) for _ in range(140)
        ]
        mock_genai.files.upload.return_value = MagicMock()
        settings = _make_settings(self.tmp, per_run_token_ceiling=2_000_000)
        client = GeminiClient(settings, _genai_client=mock_genai)

        for sweep in range(2):
            for i in range(70):
                client.generate_structured(
                    system_prompt="s",
                    user_prompt=f"sweep{sweep}-call{i}",
                    response_schema=_SimpleSchema,
                    prompt_version="1",
                    cache_mode="bypass",
                )
        self.assertEqual(mock_genai.models.generate_content.call_count, 140)
        in_tok, out_tok = process_token_totals()
        self.assertGreater(in_tok + out_tok, 150_000, "both sweeps must be on one tally")

    def test_differing_response_schema_does_not_reuse_a_cached_reply(self) -> None:
        """Identical prompts + different response schema must not share a cache entry.

        The cache key is model:prompt_hash:files_hash:params_fingerprint, and
        prompt_hash covers only the prompts — so before the schema entered the
        fingerprint, the second call silently received the first call's
        differently-shaped reply instead of calling the API.
        """

        class _OtherSchema(BaseModel):
            other: str

        mock_genai = MagicMock()
        mock_genai.models.generate_content.side_effect = [
            _mock_response('{"value": "x"}'),
            _mock_response('{"other": "y"}'),
        ]
        mock_genai.files.upload.return_value = MagicMock()
        client = GeminiClient(_make_settings(self.tmp), _genai_client=mock_genai)

        common = {"system_prompt": "s", "user_prompt": "u", "prompt_version": "1"}
        client.generate_structured(response_schema=_SimpleSchema, **common)
        client.generate_structured(response_schema=_OtherSchema, **common)

        self.assertEqual(
            mock_genai.models.generate_content.call_count,
            2,
            "second schema must miss the cache, not reuse the first schema's reply",
        )

    def test_missing_thoughts_token_count_ledgers_candidates_only(self) -> None:
        """usage_metadata without thoughts_token_count must ledger candidates alone.

        Guards the getattr default against a regression to a bare attribute
        read, which would raise on every no-thinking-budget GA response.
        """
        mock_genai = MagicMock()
        mock_genai.models.generate_content.return_value = _mock_response_without_thoughts_attr(
            '{"value": "x"}', in_tok=100, out_tok=40
        )
        mock_genai.files.upload.return_value = MagicMock()
        client = GeminiClient(_make_settings(self.tmp), _genai_client=mock_genai)

        _reset_process_counters()
        client.generate_structured(
            system_prompt="s",
            user_prompt="u",
            response_schema=_SimpleSchema,
            prompt_version="1",
            cache_mode="bypass",
        )
        self.assertEqual(process_token_totals(), (100, 40))

    def test_run_token_ceiling_still_fires_when_a_run_really_exceeds_it(self) -> None:
        """The companion to the above: sizing the ceiling must not disarm it.

        Same accumulate-through-sweeps behaviour, but with a ceiling a two-sweep
        run genuinely exceeds — it must raise rather than spend on.
        """
        mock_genai = MagicMock()
        mock_genai.models.generate_content.side_effect = [
            _mock_response('{"value": "x"}', in_tok=800, out_tok=850) for _ in range(140)
        ]
        mock_genai.files.upload.return_value = MagicMock()
        settings = _make_settings(self.tmp, per_run_token_ceiling=150_000)
        client = GeminiClient(settings, _genai_client=mock_genai)

        with self.assertRaises(ExternalServiceError):
            for sweep in range(2):
                for i in range(70):
                    client.generate_structured(
                        system_prompt="s",
                        user_prompt=f"sweep{sweep}-call{i}",
                        response_schema=_SimpleSchema,
                        prompt_version="1",
                        cache_mode="bypass",
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

    def _one_call(self, client: GeminiClient) -> None:
        client.generate_structured(
            system_prompt="sys",
            user_prompt="user",
            response_schema=_SimpleSchema,
            prompt_version="1",
        )

    def test_default_client_enforces_the_file_ledger_ceiling(self) -> None:
        """Unchanged behaviour for the CLI/Gradio/eval path: a zero ceiling stops the call."""
        mock_genai = MagicMock()
        mock_genai.models.generate_content.return_value = _mock_response('{"value": "hi"}')
        settings = _make_settings(self.tmp, total_usd_ceiling=0.0)
        client = GeminiClient(settings, _genai_client=mock_genai)
        with self.assertRaisesRegex(ExternalServiceError, "USD ceiling"):
            self._one_call(client)

    def test_an_explicitly_passed_ledger_is_the_one_used(self) -> None:
        """The third state the signature promises, which nothing else exercises.

        ``ledger`` is typed ``CostLedger | _DefaultLedger | None``, but
        production only ever uses the sentinel (CLI) or ``None`` (web). A
        regression that quietly ignored an explicitly-passed ledger — resolving
        it to the default path anyway — would be invisible to every other test
        here, because none of them supply one.
        """
        from lemely.io.cost_ledger import CostLedger

        settings = _make_settings(self.tmp)
        elsewhere = Path(self.tmp) / "elsewhere" / "ledger.json"
        mock_genai = MagicMock()
        mock_genai.models.generate_content.return_value = _mock_response('{"value": "hi"}')
        client = GeminiClient(settings, _genai_client=mock_genai, ledger=CostLedger(elsewhere))
        self._one_call(client)
        self.assertTrue(elsewhere.exists(), "the explicitly passed ledger was never written")
        self.assertFalse(
            (settings.paths.output_dir / "gemini_spend.json").exists(),
            "the default ledger path was written even though an explicit ledger was given",
        )

    def test_ledgerless_client_neither_checks_nor_records(self) -> None:
        """DS3: ledger=None means no ceiling check, no ledger file, no budget events."""
        mock_genai = MagicMock()
        mock_genai.models.generate_content.return_value = _mock_response('{"value": "hi"}')
        settings = _make_settings(self.tmp, total_usd_ceiling=0.0)
        events: list[EventType] = []
        on_warning = lambda **_: events.append(EventType.BUDGET_WARNING)  # noqa: E731
        on_exceeded = lambda **_: events.append(EventType.BUDGET_EXCEEDED)  # noqa: E731
        bus.subscribe(EventType.BUDGET_WARNING, on_warning)
        bus.subscribe(EventType.BUDGET_EXCEEDED, on_exceeded)
        try:
            client = GeminiClient(settings, _genai_client=mock_genai, ledger=None)
            self._one_call(client)  # succeeds despite a zero ceiling
        finally:
            bus.unsubscribe(EventType.BUDGET_WARNING, on_warning)
            bus.unsubscribe(EventType.BUDGET_EXCEEDED, on_exceeded)
        self.assertEqual(events, [])
        self.assertFalse((settings.paths.output_dir / "gemini_spend.json").exists())
        self.assertEqual(mock_genai.models.generate_content.call_count, 1)


class F1MigrationTests(unittest.TestCase):
    """F1 (Gemini 3.x migration) acceptance tests: request shape and cache-key
    fingerprint behaviour on the two disjoint API lines."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        _reset_process_counters()

    def test_is_3x_detector(self) -> None:
        self.assertTrue(_is_3x("gemini-3.8-flash"))
        self.assertTrue(_is_3x("gemini-3.5-flash-lite"))
        self.assertFalse(_is_3x("gemini-2.5-flash"))
        self.assertFalse(_is_3x("gemini-2.5-pro"))

    def test_3x_request_omits_determinism_params_has_thinking_level(self) -> None:
        """F1 acceptance (2): a recorded 3.x request has no temperature/top_p/
        seed/candidate_count and does contain thinking_level."""
        mock_genai = MagicMock()
        mock_genai.models.generate_content.return_value = _mock_response('{"value": "hi"}')
        mock_genai.files.upload.return_value = MagicMock()
        settings = _make_settings(self.tmp, model="gemini-3.8-flash")
        client = GeminiClient(settings, _genai_client=mock_genai)

        client.generate_structured(
            system_prompt="sys",
            user_prompt="user",
            response_schema=_SimpleSchema,
            prompt_version="1",
        )

        config = mock_genai.models.generate_content.call_args.kwargs["config"]
        self.assertIsNone(config.temperature)
        self.assertIsNone(config.top_p)
        self.assertIsNone(config.seed)
        self.assertFalse(hasattr(config, "candidate_count") and config.candidate_count)
        self.assertEqual(_level(config.thinking_config.thinking_level), "low")
        self.assertIsNone(config.thinking_config.thinking_budget)
        # 3.x uses response_json_schema, not response_schema (google-genai
        # 2.10.0, types.py:6029 GenerateContentConfig.response_json_schema).
        self.assertIsNotNone(config.response_json_schema)
        self.assertIsNone(config.response_schema)

    def test_25_request_still_has_thinking_budget(self) -> None:
        """F1 acceptance (2): a 2.5 request still carries thinking_budget
        (and the temperature/top_p/seed substrate, and response_schema)."""
        mock_genai = MagicMock()
        mock_genai.models.generate_content.return_value = _mock_response('{"value": "hi"}')
        mock_genai.files.upload.return_value = MagicMock()
        settings = _make_settings(
            self.tmp, model="gemini-2.5-flash", temperature=0.1, top_p=0.9, seed=7
        )
        client = GeminiClient(settings, _genai_client=mock_genai)

        client.generate_structured(
            system_prompt="sys",
            user_prompt="user",
            response_schema=_SimpleSchema,
            prompt_version="1",
        )

        config = mock_genai.models.generate_content.call_args.kwargs["config"]
        self.assertEqual(config.temperature, 0.1)
        self.assertEqual(config.top_p, 0.9)
        self.assertEqual(config.seed, 7)
        self.assertEqual(config.thinking_config.thinking_budget, 0)
        self.assertIsNone(config.thinking_config.thinking_level)
        self.assertIsNotNone(config.response_schema)
        self.assertIsNone(config.response_json_schema)

    def test_extraction_minimal_falls_back_to_low_off_supported_models(self) -> None:
        """F1 approach (b) note ‡: "minimal" is only honoured on 3.6-flash /
        3.5-flash-lite; every other 3.x model demotes it to "low"."""
        mock_genai = MagicMock()
        mock_genai.models.generate_content.return_value = _mock_response('{"value": "hi"}')
        mock_genai.files.upload.return_value = MagicMock()
        # task_tag="extraction" resolves via extraction_model, not the global
        # `model` — override the tag-specific field so this actually exercises
        # a non-minimal-capable 3.x model.
        settings = _make_settings(self.tmp, extraction_model="gemini-3.8-flash")
        client = GeminiClient(settings, _genai_client=mock_genai)

        client.generate_structured(
            system_prompt="sys",
            user_prompt="user",
            response_schema=_SimpleSchema,
            prompt_version="1",
            task_tag="extraction",
        )
        config = mock_genai.models.generate_content.call_args.kwargs["config"]
        # thinking_level_for["extraction"] defaults to "minimal", but
        # gemini-3.8-flash is not one of the two models that honour it.
        self.assertEqual(_level(config.thinking_config.thinking_level), "low")

    def test_extraction_minimal_honoured_on_flash_lite(self) -> None:
        mock_genai = MagicMock()
        mock_genai.models.generate_content.return_value = _mock_response('{"value": "hi"}')
        mock_genai.files.upload.return_value = MagicMock()
        settings = _make_settings(self.tmp, extraction_model="gemini-3.5-flash-lite")
        client = GeminiClient(settings, _genai_client=mock_genai)

        client.generate_structured(
            system_prompt="sys",
            user_prompt="user",
            response_schema=_SimpleSchema,
            prompt_version="1",
            task_tag="extraction",
        )
        config = mock_genai.models.generate_content.call_args.kwargs["config"]
        self.assertEqual(_level(config.thinking_config.thinking_level), "minimal")

    def test_cache_key_3x_ignores_temperature_reads_thinking_level(self) -> None:
        """F1 acceptance (4): on a 3.x model, changing temperature_for["correction"]
        leaves _cache_key unchanged; changing thinking_level_for["correction"]
        changes it."""
        mock_genai = MagicMock()
        mock_genai.models.generate_content.side_effect = [
            _mock_response('{"value": "a"}'),
            _mock_response('{"value": "b"}'),
            _mock_response('{"value": "c"}'),
        ]
        mock_genai.files.upload.return_value = MagicMock()

        # task_tag="correction" resolves via correction_model — F1's default
        # already points it at gemini-3.8-flash, made explicit here.
        base = _make_settings(self.tmp, correction_model="gemini-3.8-flash")
        client = GeminiClient(base, _genai_client=mock_genai)
        r1 = client.generate_structured(
            system_prompt="s",
            user_prompt="u",
            response_schema=_SimpleSchema,
            prompt_version="1",
            task_tag="correction",
        )
        self.assertEqual(r1.value, "a")

        # Changing temperature_for["correction"] is inert on a 3.x model -> cache hit.
        temp_changed = base.model_copy(
            update={
                "gemini": base.gemini.model_copy(update={"temperature_for": {"correction": 0.99}})
            }
        )
        client2 = GeminiClient(temp_changed, _genai_client=mock_genai)
        r2 = client2.generate_structured(
            system_prompt="s",
            user_prompt="u",
            response_schema=_SimpleSchema,
            prompt_version="1",
            task_tag="correction",
        )
        self.assertEqual(r2.value, "a")  # cache hit, not "b"
        self.assertEqual(mock_genai.models.generate_content.call_count, 1)

        # Changing thinking_level_for["correction"] DOES change the fingerprint -> cache miss.
        level_changed = base.model_copy(
            update={
                "gemini": base.gemini.model_copy(
                    update={
                        "thinking_level_for": {
                            **base.gemini.thinking_level_for,
                            "correction": "high",
                        }
                    }
                )
            }
        )
        client3 = GeminiClient(level_changed, _genai_client=mock_genai)
        r3 = client3.generate_structured(
            system_prompt="s",
            user_prompt="u",
            response_schema=_SimpleSchema,
            prompt_version="1",
            task_tag="correction",
        )
        self.assertEqual(r3.value, "b")
        self.assertEqual(mock_genai.models.generate_content.call_count, 2)

    def test_cache_key_25_reads_temperature_ignores_thinking_level(self) -> None:
        """F1 acceptance (4), the mirror case: on a 2.5 model, the reverse holds."""
        mock_genai = MagicMock()
        mock_genai.models.generate_content.side_effect = [
            _mock_response('{"value": "a"}'),
            _mock_response('{"value": "b"}'),
        ]
        mock_genai.files.upload.return_value = MagicMock()

        # task_tag="correction" resolves via correction_model, not the global
        # `model` — override the tag-specific field to actually get a 2.5 call.
        base = _make_settings(self.tmp, correction_model="gemini-2.5-flash")
        client = GeminiClient(base, _genai_client=mock_genai)
        r1 = client.generate_structured(
            system_prompt="s",
            user_prompt="u",
            response_schema=_SimpleSchema,
            prompt_version="1",
            task_tag="correction",
        )
        self.assertEqual(r1.value, "a")

        # thinking_level_for is inert on a 2.5 model -> cache hit.
        level_changed = base.model_copy(
            update={
                "gemini": base.gemini.model_copy(
                    update={
                        "thinking_level_for": {
                            **base.gemini.thinking_level_for,
                            "correction": "high",
                        }
                    }
                )
            }
        )
        client2 = GeminiClient(level_changed, _genai_client=mock_genai)
        r2 = client2.generate_structured(
            system_prompt="s",
            user_prompt="u",
            response_schema=_SimpleSchema,
            prompt_version="1",
            task_tag="correction",
        )
        self.assertEqual(r2.value, "a")
        self.assertEqual(mock_genai.models.generate_content.call_count, 1)

        # temperature_for DOES change the fingerprint on a 2.5 model -> cache miss.
        temp_changed = base.model_copy(
            update={
                "gemini": base.gemini.model_copy(update={"temperature_for": {"correction": 0.4}})
            }
        )
        client3 = GeminiClient(temp_changed, _genai_client=mock_genai)
        r3 = client3.generate_structured(
            system_prompt="s",
            user_prompt="u",
            response_schema=_SimpleSchema,
            prompt_version="1",
            task_tag="correction",
        )
        self.assertEqual(r3.value, "b")
        self.assertEqual(mock_genai.models.generate_content.call_count, 2)


class F1PricingTests(unittest.TestCase):
    def test_3x_pricing_rows_present(self) -> None:
        from lemely.io.gemini import _DEFAULT_PRICING

        self.assertIn("gemini-3.5-flash-lite", _DEFAULT_PRICING)
        self.assertEqual(_DEFAULT_PRICING["gemini-3.5-flash-lite"], (0.000300, 0.002500))


class US026PromoPricingBoundaryTests(unittest.TestCase):
    """US-026: the 3.8/3.7/3.6-flash promotional rate ($0.75/$3.75 per 1M)
    lapses to the real Google rate ($1.50/$7.50 per 1M) on
    ``FLASH_3X_PROMO_END_DATE`` — pinned on BOTH sides of that boundary with an
    injectable clock so the assertion cannot rot as the real calendar moves."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()

    def test_promo_rate_applies_on_the_last_promotional_day(self) -> None:
        from datetime import date

        from lemely.io.gemini import FLASH_3X_PROMO_END_DATE, _resolve_pricing

        settings = _make_settings(self.tmp)
        for model in ("gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash"):
            with self.subTest(model=model):
                price = _resolve_pricing(model, settings, today=lambda: FLASH_3X_PROMO_END_DATE)
                self.assertEqual(price, (0.000750, 0.003750))
        self.assertEqual(FLASH_3X_PROMO_END_DATE, date(2026, 12, 31))

    def test_post_promo_rate_applies_the_day_after(self) -> None:
        from datetime import date, timedelta

        from lemely.io.gemini import FLASH_3X_PROMO_END_DATE, _resolve_pricing

        settings = _make_settings(self.tmp)
        day_after = FLASH_3X_PROMO_END_DATE + timedelta(days=1)
        self.assertEqual(day_after, date(2027, 1, 1))
        for model in ("gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash"):
            with self.subTest(model=model):
                price = _resolve_pricing(model, settings, today=lambda: day_after)
                self.assertEqual(price, (0.001500, 0.007500))

    def test_default_clock_resolves_pricing_without_an_explicit_today(self) -> None:
        """The `today` param is optional — the real ledger call site (`_call_once`)
        never passes one, so the module clock must be used by default. Patches the
        module clock `_today` (rather than passing `today=`) and pins the exact
        resulting rate, so this is not the vacuous "either value is fine" check the
        adversarial review flagged (US-026 review, NIT 4)."""
        from datetime import date
        from unittest.mock import patch

        from lemely.io.gemini import FLASH_3X_PROMO_END_DATE, _resolve_pricing

        settings = _make_settings(self.tmp)
        post_promo_day = date(FLASH_3X_PROMO_END_DATE.year + 1, 6, 1)
        with patch("lemely.io.gemini._today", return_value=post_promo_day):
            price = _resolve_pricing("gemini-3.8-flash", settings)
        self.assertEqual(price, (0.001500, 0.007500))

    def test_module_clock_patch_reaches_resolve_pricing_default(self) -> None:
        """Review finding 2: `_resolve_pricing`'s `today` default must resolve
        `_today` BY NAME at call time, not capture the function object at def
        time — otherwise `mock.patch("lemely.io.gemini._today", ...)` would
        silently fail to reach it, and a test relying on that patch would pass
        vacuously whenever the real calendar happened to agree anyway."""
        from datetime import timedelta
        from unittest.mock import patch

        from lemely.io.gemini import FLASH_3X_PROMO_END_DATE, _resolve_pricing

        settings = _make_settings(self.tmp)
        promo_day = FLASH_3X_PROMO_END_DATE
        post_promo_day = FLASH_3X_PROMO_END_DATE + timedelta(days=1)

        with patch("lemely.io.gemini._today", return_value=promo_day):
            self.assertEqual(_resolve_pricing("gemini-3.8-flash", settings), (0.000750, 0.003750))
        with patch("lemely.io.gemini._today", return_value=post_promo_day):
            self.assertEqual(_resolve_pricing("gemini-3.8-flash", settings), (0.001500, 0.007500))

    def test_a_correctly_priced_lite_row_is_not_shadowed_by_the_promo_merge(self) -> None:
        """Review finding 1: the promo rate must be merged into a COPY of
        `_DEFAULT_PRICING` under the three exact promo-model keys, so the
        existing length-descending substring match keeps governing lookup.
        Before the fix, an unanchored `promo_model in model` check ran BEFORE
        that sort and unconditionally won for any `gemini-3.8-flash*` string —
        proven by injecting a correctly priced `-lite` row and observing it
        was still shadowed by the (wrong) promo rate."""
        from unittest.mock import patch

        from lemely.io.gemini import _DEFAULT_PRICING, FLASH_3X_PROMO_END_DATE, _resolve_pricing

        settings = _make_settings(self.tmp)
        lite_price = (0.000100, 0.000400)
        with (
            patch.dict(_DEFAULT_PRICING, {"gemini-3.8-flash-lite": lite_price}),
            patch("lemely.io.gemini._today", return_value=FLASH_3X_PROMO_END_DATE),
        ):
            lite_result = _resolve_pricing("gemini-3.8-flash-lite", settings)
            flash_result = _resolve_pricing("gemini-3.8-flash", settings)
        # The longer, more specific key wins for the -lite model...
        self.assertEqual(lite_result, lite_price)
        # ...while the bare flash model still gets the promo rate.
        self.assertEqual(flash_result, (0.000750, 0.003750))


class US026PromoPricingOverrideTests(unittest.TestCase):
    """Review finding 3: a `settings.gemini.pricing` override on a promo model
    bypasses `FLASH_3X_PROMO_END_DATE` entirely (pre-existing, intentional
    override-wins precedence) — but `promo_pricing_status`'s advisory text
    must not then claim a post-promo rate it never checked."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()

    def test_override_bypasses_the_date_gate_regardless_of_today(self) -> None:
        from datetime import date

        from lemely.io.gemini import _resolve_pricing

        settings = _make_settings(self.tmp, pricing={"gemini-3.8-flash": [0.000750, 0.003750]})
        far_future = date(2030, 1, 1)
        price = _resolve_pricing("gemini-3.8-flash", settings, today=lambda: far_future)
        self.assertEqual(price, (0.000750, 0.003750))

    def test_status_reports_the_override_instead_of_a_false_post_promo_claim(self) -> None:
        from datetime import timedelta

        from lemely.io.gemini import FLASH_3X_PROMO_END_DATE, promo_pricing_status

        settings = _make_settings(self.tmp, pricing={"gemini-3.8-flash": [0.000750, 0.003750]})
        far_future = FLASH_3X_PROMO_END_DATE + timedelta(days=365)
        ok, detail = promo_pricing_status(settings, today=far_future)
        self.assertFalse(ok)
        self.assertIn("gemini-3.8-flash", detail)
        self.assertIn("pins a fixed price", detail)
        # Must NOT assert the post-promo rate is in effect — the override means
        # it never checked.
        self.assertNotIn("post-promo rate", detail)

    def test_status_is_unaffected_when_no_promo_model_is_overridden(self) -> None:
        from datetime import timedelta

        from lemely.io.gemini import FLASH_3X_PROMO_END_DATE, promo_pricing_status

        settings = _make_settings(self.tmp, pricing={"gemini-2.5-pro": [0.00125, 0.01]})
        ok, detail = promo_pricing_status(
            settings, today=FLASH_3X_PROMO_END_DATE - timedelta(days=90)
        )
        self.assertTrue(ok)
        self.assertNotIn("pins a fixed price", detail)


class F1LedgerCeilingDefaultTests(unittest.TestCase):
    """F1 acceptance (6), the shipped-default path specifically.

    The pre-existing ``ExternalServiceError``-path tests
    (``test_default_client_enforces_the_file_ledger_ceiling``,
    ``test_usd_ceiling_raises_from_persistent_ledger``) prove the *mechanism*
    works, but both override ``total_usd_ceiling`` explicitly (0.0, and a
    pre-loaded ledger against no override respectively) rather than exercising
    the actual shipped $14 default end-to-end against a genuinely fresh ($0)
    ledger. This closes that gap directly.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        _reset_process_counters()

    def test_fresh_ledger_reads_zero_and_the_14_default_is_not_yet_tripped(self) -> None:
        from lemely.io.cost_ledger import CostLedger

        settings = _make_settings(self.tmp)  # no override: real 14.0 default
        self.assertEqual(settings.gemini.total_usd_ceiling, 14.0)
        ledger = CostLedger(settings.paths.output_dir / "gemini_spend.json")
        self.assertEqual(ledger.total(), 0.0, "a freshly created ledger must read $0")

        mock_genai = MagicMock()
        mock_genai.models.generate_content.return_value = _mock_response('{"value": "hi"}')
        mock_genai.files.upload.return_value = MagicMock()
        client = GeminiClient(settings, _genai_client=mock_genai)

        # A normal call succeeds — the $14 default ceiling does not trip at $0.
        client.generate_structured(
            system_prompt="s",
            user_prompt="u",
            response_schema=_SimpleSchema,
            prompt_version="1",
        )
        self.assertEqual(mock_genai.models.generate_content.call_count, 1)

    def test_14_default_ceiling_is_enforced_once_the_ledger_reaches_it(self) -> None:
        from lemely.io.cost_ledger import CostLedger

        settings = _make_settings(self.tmp)  # real 14.0 default, not overridden
        ledger = CostLedger(settings.paths.output_dir / "gemini_spend.json")
        ledger.add(14.0, thresholds=[])

        mock_genai = MagicMock()
        mock_genai.models.generate_content.return_value = _mock_response('{"value": "hi"}')
        mock_genai.files.upload.return_value = MagicMock()
        client = GeminiClient(settings, _genai_client=mock_genai)

        with self.assertRaisesRegex(ExternalServiceError, "USD ceiling"):
            client.generate_structured(
                system_prompt="s",
                user_prompt="u",
                response_schema=_SimpleSchema,
                prompt_version="1",
            )
        self.assertEqual(mock_genai.models.generate_content.call_count, 0)


class I1MediaResolutionTests(unittest.TestCase):
    """I1 acceptance (5): the request recorder shows media_resolution set per
    image part, and it is folded into the cache-key fingerprint so a
    media_resolution call never collides with one that set none."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        _reset_process_counters()

    def test_image_parts_carry_media_resolution_per_part(self) -> None:
        mock_genai = MagicMock()
        mock_genai.models.generate_content.return_value = _mock_response('{"value": "hi"}')
        client = GeminiClient(_make_settings(self.tmp), _genai_client=mock_genai)

        client.generate_structured(
            system_prompt="sys",
            user_prompt="user",
            image_parts=[b"page-0-bytes", b"page-1-bytes"],
            media_resolution="medium",
            response_schema=_SimpleSchema,
            prompt_version="1",
            task_tag="extraction",
        )

        contents = mock_genai.models.generate_content.call_args.kwargs["contents"]
        image_parts = [p for p in contents if getattr(p, "inline_data", None) is not None]
        self.assertEqual(len(image_parts), 2)
        for part in image_parts:
            self.assertIsNotNone(part.media_resolution)
            self.assertEqual(
                str(part.media_resolution.level).upper().rsplit(".", 1)[-1],
                "MEDIA_RESOLUTION_MEDIUM",
            )
        # No Files API upload call — image_parts take the inline-bytes path.
        mock_genai.files.upload.assert_not_called()

    def test_media_resolution_none_does_not_warn_and_uses_files_upload(self) -> None:
        """The pre-I1 file_paths path is untouched: no media_resolution is
        set (so no PartMediaResolutionLevel warning fires), and the Files
        API upload path is used exactly as before."""
        import warnings

        mock_genai = MagicMock()
        mock_genai.models.generate_content.return_value = _mock_response('{"value": "hi"}')
        mock_genai.files.upload.return_value = MagicMock()
        client = GeminiClient(_make_settings(self.tmp), _genai_client=mock_genai)

        scan = Path(self.tmp) / "scan.pdf"
        scan.write_bytes(b"%PDF-1.4 fake")

        with warnings.catch_warnings():
            warnings.simplefilter("error")
            client.generate_structured(
                system_prompt="sys",
                user_prompt="user",
                file_paths=[scan],
                response_schema=_SimpleSchema,
                prompt_version="1",
            )
        mock_genai.files.upload.assert_called_once()

    def test_media_resolution_changes_the_cache_key(self) -> None:
        """Two calls identical except for media_resolution must NOT share a
        cache entry — the exact collision I1's harness/GeminiClient
        fingerprint fix exists to prevent."""
        mock_genai = MagicMock()
        mock_genai.models.generate_content.side_effect = [
            _mock_response('{"value": "a"}'),
            _mock_response('{"value": "b"}'),
        ]
        client = GeminiClient(_make_settings(self.tmp), _genai_client=mock_genai)

        r1 = client.generate_structured(
            system_prompt="sys",
            user_prompt="user",
            image_parts=[b"same-bytes"],
            media_resolution="medium",
            response_schema=_SimpleSchema,
            prompt_version="1",
        )
        r2 = client.generate_structured(
            system_prompt="sys",
            user_prompt="user",
            image_parts=[b"same-bytes"],
            media_resolution="high",
            response_schema=_SimpleSchema,
            prompt_version="1",
        )
        self.assertEqual((r1.value, r2.value), ("a", "b"))
        self.assertEqual(mock_genai.models.generate_content.call_count, 2)

    def test_media_resolution_none_vs_set_also_changes_the_cache_key(self) -> None:
        mock_genai = MagicMock()
        mock_genai.models.generate_content.side_effect = [
            _mock_response('{"value": "a"}'),
            _mock_response('{"value": "b"}'),
        ]
        client = GeminiClient(_make_settings(self.tmp), _genai_client=mock_genai)

        r1 = client.generate_structured(
            system_prompt="sys",
            user_prompt="user",
            image_parts=[b"same-bytes"],
            response_schema=_SimpleSchema,
            prompt_version="1",
        )
        r2 = client.generate_structured(
            system_prompt="sys",
            user_prompt="user",
            image_parts=[b"same-bytes"],
            media_resolution="medium",
            response_schema=_SimpleSchema,
            prompt_version="1",
        )
        self.assertEqual((r1.value, r2.value), ("a", "b"))
        self.assertEqual(mock_genai.models.generate_content.call_count, 2)

    def test_different_image_bytes_with_identical_prompt_issue_two_api_calls(self) -> None:
        """I1 review MUST-FIX 4: making ``_cache_key`` ignore ``image_parts``
        entirely broke zero of the 18 I1 tests -- with that branch gone,
        every paper in a sweep (same system/user prompt) would share one
        cache key and one paper's answers would be read back as every
        paper's. Guard the mechanism directly: two otherwise-identical calls
        whose page bytes differ must not share a cache entry."""
        mock_genai = MagicMock()
        mock_genai.models.generate_content.side_effect = [
            _mock_response('{"value": "a"}'),
            _mock_response('{"value": "b"}'),
        ]
        client = GeminiClient(_make_settings(self.tmp), _genai_client=mock_genai)

        r1 = client.generate_structured(
            system_prompt="sys",
            user_prompt="user",
            image_parts=[b"page-bytes-one"],
            media_resolution="medium",
            response_schema=_SimpleSchema,
            prompt_version="1",
        )
        r2 = client.generate_structured(
            system_prompt="sys",
            user_prompt="user",
            image_parts=[b"page-bytes-two"],
            media_resolution="medium",
            response_schema=_SimpleSchema,
            prompt_version="1",
        )
        self.assertEqual((r1.value, r2.value), ("a", "b"))
        self.assertEqual(mock_genai.models.generate_content.call_count, 2)

    def test_reread_cache_key_never_collides_with_its_primary(self) -> None:
        """I1 review MUST-FIX 4, part (ii): the same page bytes at the same
        media_resolution, once shaped like a primary extraction call and
        once shaped like the re-read call it triggers (differing only by
        ``extra_cache_key``, exactly as ``Rereader.reread`` sets it), must
        not collide."""
        mock_genai = MagicMock()
        mock_genai.models.generate_content.side_effect = [
            _mock_response('{"value": "primary"}'),
            _mock_response('{"value": "reread"}'),
        ]
        client = GeminiClient(_make_settings(self.tmp), _genai_client=mock_genai)

        r1 = client.generate_structured(
            system_prompt="sys",
            user_prompt="user",
            image_parts=[b"same-bytes"],
            media_resolution="high",
            response_schema=_SimpleSchema,
            prompt_version="1",
            extra_cache_key="manifestkey",
        )
        r2 = client.generate_structured(
            system_prompt="sys",
            user_prompt="user",
            image_parts=[b"same-bytes"],
            media_resolution="high",
            response_schema=_SimpleSchema,
            prompt_version="1",
            extra_cache_key="manifestkey:reread:1:0:[1, 2, 3, 4]",
        )
        self.assertEqual((r1.value, r2.value), ("primary", "reread"))
        self.assertEqual(mock_genai.models.generate_content.call_count, 2)


class CodeExecutionTests(unittest.TestCase):
    """N3 (US-012): `generate_with_code_execution` and its cache-key
    separation from plain `generate_structured` calls
    (docs/plans/ai-improvements-plan.md:615, "cache key includes tool
    flag"). This is Gemini's own `code_execution` tool, not a locally-built
    sandbox — every test here mocks the `google-genai` client, so none of
    it spends real API budget."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        _reset_process_counters()

    def test_returns_the_code_execution_result_output(self) -> None:
        mock_genai = MagicMock()
        mock_genai.models.generate_content.return_value = _mock_code_execution_response("42")
        client = GeminiClient(_make_settings(self.tmp), _genai_client=mock_genai)

        result = client.generate_with_code_execution(prompt="compute 6*7", prompt_version="1")

        self.assertEqual(result, "42")

    def test_no_code_execution_result_part_raises_parse_error(self) -> None:
        mock_genai = MagicMock()
        mock_genai.models.generate_content.return_value = (
            _mock_response_without_code_execution_result()
        )
        client = GeminiClient(_make_settings(self.tmp), _genai_client=mock_genai)

        with self.assertRaises(ParseError):
            client.generate_with_code_execution(prompt="compute 6*7", prompt_version="1")

    def test_repeated_call_hits_its_own_cache(self) -> None:
        mock_genai = MagicMock()
        mock_genai.models.generate_content.return_value = _mock_code_execution_response("42")
        client = GeminiClient(_make_settings(self.tmp), _genai_client=mock_genai)

        r1 = client.generate_with_code_execution(prompt="compute 6*7", prompt_version="1")
        r2 = client.generate_with_code_execution(prompt="compute 6*7", prompt_version="1")

        self.assertEqual((r1, r2), ("42", "42"))
        self.assertEqual(mock_genai.models.generate_content.call_count, 1)

    def test_params_fingerprint_tool_flag_changes_the_fingerprint(self) -> None:
        """The load-bearing pin: `tool` alone, with everything else held
        fixed (including `response_schema=None`, which a real code-execution
        call always has), must change `_params_fingerprint`'s output — this
        is the exact mechanism `_cache_key` relies on to keep a
        code-execution call out of a plain call's cache entry."""
        client = GeminiClient(_make_settings(self.tmp), _genai_client=MagicMock())

        fp_plain = client._params_fingerprint("gemini-2.5-flash", "question_validity", None)
        fp_tool = client._params_fingerprint(
            "gemini-2.5-flash", "question_validity", None, tool="code_execution"
        )

        self.assertNotEqual(fp_plain, fp_tool)

    def test_plain_call_fingerprint_unaffected_by_tool_param_existence(self) -> None:
        """The companion pin: a `tool=None` call (every plain
        `generate_structured` call has one) must produce the exact
        fingerprint the pre-N3 format did — the `|tool` segment must be
        entirely absent when tool is None, not present as `|none`.
        Appending it unconditionally moves EVERY plain call's fingerprint
        (measured against the parent module: a correction+schema call's
        fingerprint moved from `c484bb603401` to `b7cbee1f90ef`), which
        orphans the entire on-disk cache the moment this runs against a
        populated one."""
        client = GeminiClient(_make_settings(self.tmp), _genai_client=MagicMock())
        model = "gemini-2.5-flash"
        params = client._resolved_gen_params("question_validity", model)
        api_line = "3x" if _is_3x(model) else "2x"
        expected_raw = (
            f"{model}|{api_line}|{params['temperature']}|{params['top_p']}"
            f"|{params['seed']}|{params['thinking_budget']}|{params['thinking_level']}"
            f"|{_MAX_OUTPUT_TOKENS}||none"
        )
        expected = hashlib.sha256(expected_raw.encode()).hexdigest()[:12]

        actual = client._params_fingerprint(model, "question_validity", None)

        self.assertEqual(actual, expected)

    def test_code_execution_call_does_not_hit_a_plain_calls_cache_entry(self) -> None:
        """The observable-behaviour version of the pin above: a plain
        `generate_structured` call and a `generate_with_code_execution`
        call built from the SAME text (so their `prompt_hash` component is
        identical — `system_prompt=""` + `user_prompt=X` on one side,
        `prompt=X` + `""` on the other) must still issue two separate API
        calls, never a cache hit across them. If this ever collapsed to one
        API call, a verification that never ran would be silently satisfied
        by a cached plain reply — the failure mode the plan's cache-key
        note exists to prevent."""
        mock_genai = MagicMock()
        mock_genai.models.generate_content.side_effect = [
            _mock_response('{"value": "plain"}'),
            _mock_code_execution_response("42"),
        ]
        client = GeminiClient(_make_settings(self.tmp), _genai_client=mock_genai)

        plain = client.generate_structured(
            system_prompt="",
            user_prompt="same prompt text",
            response_schema=_SimpleSchema,
            prompt_version="1",
        )
        code_exec = client.generate_with_code_execution(
            prompt="same prompt text", prompt_version="1"
        )

        self.assertEqual(plain.value, "plain")
        self.assertEqual(code_exec, "42")
        self.assertEqual(mock_genai.models.generate_content.call_count, 2)

    def test_cache_mode_bypass_never_reads_or_writes(self) -> None:
        mock_genai = MagicMock()
        mock_genai.models.generate_content.side_effect = [
            _mock_code_execution_response("1"),
            _mock_code_execution_response("2"),
        ]
        client = GeminiClient(_make_settings(self.tmp), _genai_client=mock_genai)

        r1 = client.generate_with_code_execution(
            prompt="p", prompt_version="1", cache_mode="bypass"
        )
        r2 = client.generate_with_code_execution(
            prompt="p", prompt_version="1", cache_mode="bypass"
        )

        self.assertEqual((r1, r2), ("1", "2"))
        self.assertEqual(mock_genai.models.generate_content.call_count, 2)

    def test_code_execution_spend_publishes_a_crossed_budget_warning(self) -> None:
        """Spec 2026-09-26 §9 (#7): the code-execution path used to discard
        the thresholds `CostLedger.add` returned -- and the ledger had
        already recorded them as sent, so the warning was lost for good."""
        from lemely.io.cost_ledger import CostLedger

        settings = _make_settings(self.tmp, usd_warning_thresholds=[4.0], total_usd_ceiling=None)
        CostLedger(settings.paths.output_dir / "gemini_spend.json").add(3.999, thresholds=[])
        mock_genai = MagicMock()
        mock_genai.models.generate_content.return_value = _mock_code_execution_response(
            "42", in_tok=10_000_000, out_tok=10_000_000
        )
        client = GeminiClient(settings, _genai_client=mock_genai)
        warnings, stop = _capture(EventType.BUDGET_WARNING)
        try:
            client.generate_with_code_execution(
                prompt="compute 6*7", prompt_version="1", task_tag="question_validity"
            )
        finally:
            stop()
        self.assertEqual([w["threshold"] for w in warnings], [4.0])

    def test_code_execution_spend_is_attributed_to_its_task_tag(self) -> None:
        mock_genai = MagicMock()
        mock_genai.models.generate_content.return_value = _mock_code_execution_response("42")
        client = GeminiClient(_make_settings(self.tmp), _genai_client=mock_genai)
        client.generate_with_code_execution(
            prompt="compute 6*7", prompt_version="1", task_tag="question_validity"
        )
        self.assertGreater(process_token_totals_by_task()["question_validity"], 0.0)

    def test_code_execution_spend_publishes_budget_exceeded_at_the_ceiling(self) -> None:
        from lemely.io.cost_ledger import CostLedger

        settings = _make_settings(self.tmp, usd_warning_thresholds=[], total_usd_ceiling=5.0)
        CostLedger(settings.paths.output_dir / "gemini_spend.json").add(4.9, thresholds=[])
        mock_genai = MagicMock()
        mock_genai.models.generate_content.return_value = _mock_code_execution_response(
            "42", in_tok=10_000_000, out_tok=10_000_000
        )
        client = GeminiClient(settings, _genai_client=mock_genai)
        exceeded, stop = _capture(EventType.BUDGET_EXCEEDED)
        try:
            client.generate_with_code_execution(prompt="compute 6*7", prompt_version="1")
        finally:
            stop()
        self.assertEqual(len(exceeded), 1)
        self.assertEqual(exceeded[0]["ceiling"], 5.0)


class SpendLockTests(unittest.TestCase):
    """Spec 2026-09-26 §9: the process counters and `CostLedger.add` are a
    read-modify-write; wave-2's threaded re-reads and uploads make them
    concurrent, so they run under one module-level lock."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        _reset_process_counters()

    def test_record_spend_holds_the_spend_lock_around_the_ledger_write(self) -> None:
        from lemely.io import gemini as gemini_module
        from lemely.io.cost_ledger import CostLedger

        held: list[bool] = []
        original_add = CostLedger.add

        def _spy(self_, usd, *, thresholds):  # type: ignore[no-untyped-def]
            held.append(gemini_module._SPEND_LOCK.locked())
            return original_add(self_, usd, thresholds=thresholds)

        mock_genai = MagicMock()
        mock_genai.models.generate_content.return_value = _mock_response('{"value": "x"}')
        client = GeminiClient(_make_settings(self.tmp), _genai_client=mock_genai)
        with patch.object(CostLedger, "add", _spy):
            client.generate_structured(
                system_prompt="s",
                user_prompt="u",
                response_schema=_SimpleSchema,
                prompt_version="1",
            )
        self.assertEqual(held, [True])

    def test_record_spend_totals_are_exact_under_concurrent_callers(self) -> None:
        from lemely.io.cost_ledger import CostLedger
        from lemely.io.gemini import _resolve_pricing

        settings = _make_settings(self.tmp, usd_warning_thresholds=[])
        client = GeminiClient(settings, _genai_client=MagicMock())
        in_price, out_price = _resolve_pricing("gemini-2.5-flash", settings)
        per_call = 10 / 1000 * in_price + 20 / 1000 * out_price
        log = structlog.get_logger()

        def _worker() -> None:
            for _ in range(50):
                client._record_spend(
                    response=_mock_response("x", in_tok=10, out_tok=20),
                    model="gemini-2.5-flash",
                    task_tag="soak",
                    latency_ms=1,
                    log=log,
                    params_fingerprint="fp",
                )

        threads = [threading.Thread(target=_worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(process_token_totals(), (8 * 50 * 10, 8 * 50 * 20))
        self.assertAlmostEqual(process_token_totals_by_task()["soak"], 400 * per_call, places=9)
        ledger = CostLedger(settings.paths.output_dir / "gemini_spend.json")
        self.assertAlmostEqual(ledger.total(), 400 * per_call, places=9)

    def test_record_spend_log_line_has_exactly_the_pinned_fields_for_the_structured_path(
        self,
    ) -> None:
        """Fix round 1: pins the `gemini_call` field set M0.4 reads for a
        plain call -- no `latency_ms`/`tool` leaking in from the
        code-execution path's `extra_log_fields`."""
        client = GeminiClient(_make_settings(self.tmp), _genai_client=MagicMock())
        log = structlog.get_logger()
        with capture_logs() as logs:
            client._record_spend(
                response=_mock_response("x", in_tok=10, out_tok=20),
                model="gemini-2.5-flash",
                task_tag="extraction",
                latency_ms=5,
                log=log,
                params_fingerprint="fp",
            )
        [entry] = [e for e in logs if e["event"] == "gemini_call"]
        self.assertEqual(
            set(entry) - {"log_level"},
            {
                "event",
                "input_tokens",
                "output_tokens",
                "thoughts_tokens",
                "usd_cost",
                "cache_hit",
                "params_fingerprint",
            },
        )

    def test_record_spend_log_line_has_exactly_the_pinned_fields_for_the_code_execution_path(
        self,
    ) -> None:
        """Fix round 1: pins the code-execution path's `extra_log_fields`
        addition -- `latency_ms` and `tool`, on top of the shared fields."""
        client = GeminiClient(_make_settings(self.tmp), _genai_client=MagicMock())
        log = structlog.get_logger()
        with capture_logs() as logs:
            client._record_spend(
                response=_mock_response("x", in_tok=10, out_tok=20),
                model="gemini-2.5-flash",
                task_tag="question_validity",
                latency_ms=5,
                log=log,
                params_fingerprint="fp",
                extra_log_fields={"latency_ms": 5, "tool": "code_execution"},
            )
        [entry] = [e for e in logs if e["event"] == "gemini_call"]
        self.assertEqual(
            set(entry) - {"log_level"},
            {
                "event",
                "input_tokens",
                "output_tokens",
                "thoughts_tokens",
                "usd_cost",
                "cache_hit",
                "params_fingerprint",
                "latency_ms",
                "tool",
            },
        )


class ImageUploadsTests(unittest.TestCase):
    """Spec 2026-09-26 §7, client half."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        _reset_process_counters()

    def _client(self, **gemini_overrides: object) -> tuple[GeminiClient, MagicMock]:
        mock_genai = fake_genai_client()
        mock_genai.models.generate_content.return_value = _mock_response('{"value": "x"}')
        return GeminiClient(
            _make_settings(self.tmp, **gemini_overrides), _genai_client=mock_genai
        ), mock_genai

    def _call(self, client: GeminiClient, images: list[bytes], uploads) -> None:  # type: ignore[no-untyped-def]
        client.generate_structured(
            system_prompt="s",
            user_prompt="u",
            image_parts=images,
            image_uploads=uploads,
            media_resolution="medium",
            response_schema=_SimpleSchema,
            prompt_version="1",
            task_tag="extraction",
        )

    def test_generate_structured_sends_file_uri_parts_and_no_inline_data(self) -> None:
        client, mock_genai = self._client()
        images = [b"page-0", b"page-1"]
        with client.image_uploads(images, concurrency=2) as uploads:
            self._call(client, images, uploads)
        contents = mock_genai.models.generate_content.call_args.kwargs["contents"]
        parts = contents[1:]
        self.assertEqual(len(parts), 2)
        for part in parts:
            self.assertIsNone(part.inline_data)
            self.assertTrue(part.file_data.file_uri.endswith(("files/fake-1", "files/fake-2")))
            self.assertEqual(part.file_data.mime_type, "image/png")
        self.assertEqual([u[0] for u in mock_genai.files.uploads], images)

    def test_uploads_are_lazy_and_skipped_on_a_cache_hit(self) -> None:
        """The cache key is computed from the page BYTES, exactly as for an
        inline call, and a hit returns before anything is uploaded -- so an
        inline call and an uploads call with the same bytes share one cache
        entry, and a warm harness sweep uploads nothing."""
        client, mock_genai = self._client()
        images = [b"page-0"]
        client.generate_structured(
            system_prompt="s",
            user_prompt="u",
            image_parts=images,
            media_resolution="medium",
            response_schema=_SimpleSchema,
            prompt_version="1",
            task_tag="extraction",
        )
        with client.image_uploads(images, concurrency=2) as uploads:
            self._call(client, images, uploads)
        self.assertEqual(mock_genai.models.generate_content.call_count, 1)
        self.assertEqual(mock_genai.files.uploads, [])
        self.assertEqual(mock_genai.files.deleted, [])

    def test_ensure_uploads_once_across_two_calls(self) -> None:
        client, mock_genai = self._client()
        images = [b"page-0", b"page-1", b"page-2"]
        with client.image_uploads(images, concurrency=2) as uploads:
            self._call(client, images, uploads)
            client.generate_structured(
                system_prompt="second read",
                user_prompt="u",
                image_parts=images,
                image_uploads=uploads,
                media_resolution="medium",
                response_schema=_SimpleSchema,
                prompt_version="1",
                task_tag="second_read",
            )
        self.assertEqual(len(mock_genai.files.uploads), 3)
        self.assertEqual(mock_genai.models.generate_content.call_count, 2)

    def test_uploads_overlap_up_to_upload_concurrency(self) -> None:
        client, mock_genai = self._client()
        barrier = threading.Barrier(4, timeout=5)
        mock_genai.files.upload_hook = lambda _data: barrier.wait()
        images = [b"a", b"b", b"c", b"d"]
        with client.image_uploads(images, concurrency=4) as uploads:
            files = uploads.ensure()
        # Four parties met at the barrier, so four uploads were in flight at once.
        self.assertEqual(sorted(f.name for f in files), [f"files/fake-{i}" for i in (1, 2, 3, 4)])

    def test_uploads_overlap_at_least_up_to_the_configured_concurrency(self) -> None:
        """Fix round 3, Minor 3, narrowed by round 5, Minor 1: replaces
        round 1's `Barrier(3, timeout=0.3)` -- whose PASS depended on
        nobody reaching a third slot inside a 0.3s wall-clock window,
        flaky on a loaded runner -- with a deterministic proof. A
        `Barrier(2)` rendezvous only returns once a SECOND thread reaches
        it too, so it proves "at least 2 concurrent" without any timing
        dependency on the happy path; its `timeout` is a hang-guard for a
        genuine regression, not the pass/fail signal.

        This is the ">= 2" half only -- round 5: a Barrier only proves a
        LOWER bound (enough parties showed up), never an upper one; with a
        `concurrency=3` regression this same test's `max_in_flight` still
        came out exactly 2 in 191/200 runs (three workers racing for two
        rendezvous slots plus one still queued does not reliably surface
        a third). The upper bound ("<= configured concurrency") is proven
        deterministically by the `..._build_their_pool_with_max_workers...`
        test below instead, which asserts the actual `max_workers`
        argument rather than inferring it from observed timing.
        """
        client, mock_genai = self._client()
        lock = threading.Lock()
        in_flight = 0
        max_in_flight = 0
        rendezvous = threading.Barrier(2, timeout=5)

        def _hook(_data: bytes) -> None:
            nonlocal in_flight, max_in_flight
            with lock:
                in_flight += 1
                max_in_flight = max(max_in_flight, in_flight)
            rendezvous.wait()
            with lock:
                in_flight -= 1

        mock_genai.files.upload_hook = _hook
        images = [b"a", b"b", b"c", b"d", b"e", b"f"]
        with client.image_uploads(images, concurrency=2) as uploads:
            files = uploads.ensure()
        self.assertEqual(len(files), 6)
        self.assertGreaterEqual(max_in_flight, 2)

    def test_a_cold_sdk_client_is_created_once_by_ensure_before_the_upload_pool(self) -> None:
        """Final review M2: ``GeminiClient._client`` is created lazily and
        unlocked, and a cold client was first touched by the upload
        workers, so up to ``upload_concurrency`` threads could each build a
        ``genai.Client``. ``ensure()`` creates it on the calling thread
        before starting the pool; the Barrier proves all four uploads were
        in flight at once, so the workers really did overlap."""
        fake = fake_genai_client()
        barrier = threading.Barrier(4, timeout=5)
        fake.files.upload_hook = lambda _data: barrier.wait()
        constructed_on: list[threading.Thread] = []
        lock = threading.Lock()

        def _construct(**_kwargs: object) -> MagicMock:
            with lock:
                constructed_on.append(threading.current_thread())
            return fake

        # The suite-wide conftest guard replaces the `_client` property so no
        # test can build a real SDK client; this test needs the production
        # lazy-creation path, with `genai.Client` itself patched instead.
        guarded = GeminiClient.__dict__["_client"].fget
        production_fget = inspect.getclosurevars(guarded).nonlocals.get("original", guarded)
        client = GeminiClient(_make_settings(self.tmp))
        with (
            patch.object(GeminiClient, "_client", property(production_fget)),
            patch("google.genai.Client", side_effect=_construct),
            client.image_uploads([b"a", b"b", b"c", b"d"], concurrency=4) as uploads,
        ):
            files = uploads.ensure()
        self.assertEqual(len(files), 4)
        self.assertEqual(constructed_on, [threading.current_thread()])

    def test_ensure_and_delete_build_their_pool_with_max_workers_equal_to_concurrency(
        self,
    ) -> None:
        """Fix round 5, Minor 1: deterministic proof of the UPPER bound --
        patches `lemely.io.gemini.ThreadPoolExecutor` with a recording
        wrapper (still backed by the real executor) and asserts every
        pool `ensure()`/`delete()` builds is constructed with
        `max_workers` equal to the configured concurrency, never more."""
        from lemely.io import gemini as gemini_module

        client, mock_genai = self._client()
        recorded: list[object] = []
        real_executor = gemini_module.ThreadPoolExecutor

        def _recording_executor(*args: object, **kwargs: object) -> Any:
            recorded.append(kwargs.get("max_workers"))
            return real_executor(*args, **kwargs)

        images = [b"a", b"b", b"c", b"d", b"e", b"f"]
        with (
            patch.object(gemini_module, "ThreadPoolExecutor", _recording_executor),
            client.image_uploads(images, concurrency=2) as uploads,
        ):
            files = uploads.ensure()
        self.assertEqual(len(files), 6)
        self.assertTrue(recorded)
        self.assertTrue(all(w == 2 for w in recorded), recorded)

    def test_uploaded_files_keep_page_order(self) -> None:
        client, mock_genai = self._client()
        images = [b"a", b"b", b"c", b"d", b"e", b"f"]
        with client.image_uploads(images, concurrency=3) as uploads:
            files = uploads.ensure()
        by_name = {
            name: data for data, cfg in mock_genai.files.uploads for name in [cfg["display_name"]]
        }
        self.assertEqual([by_name[f"page-{i}"] for i in range(6)], images)
        self.assertEqual(len(files), 6)

    def test_a_transient_upload_error_with_no_retries_left_is_raised_as_external_service_error(
        self,
    ) -> None:
        """Fix round 1: renamed from "..._is_retried_then_raised..." -- with
        `max_retries=0` there is exactly one attempt, so this test never
        actually exercised a retry. See the next test for that."""
        client, mock_genai = self._client(max_retries=0)
        mock_genai.files.upload_hook = lambda _data: (_ for _ in ()).throw(
            RuntimeError("503 unavailable")
        )
        with (
            client.image_uploads([b"a"], concurrency=1) as uploads,
            self.assertRaises(ExternalServiceError),
        ):
            uploads.ensure()

    def test_a_transient_upload_error_retries_then_a_non_transient_one_raises(self) -> None:
        """Fix round 1: proves the retry actually happens -- attempt 1 is
        transient (retried), attempt 2 is not (raised immediately, no third
        attempt) -- rather than asserting a bare failure that a single
        no-retry attempt would also satisfy."""
        client, mock_genai = self._client(max_retries=2, backoff_seconds=0.01)
        attempts: list[int] = []

        def _flaky_then_fatal(_data: bytes) -> None:
            attempts.append(1)
            if len(attempts) == 1:
                raise RuntimeError("503 unavailable")
            raise RuntimeError("400 bad request")

        mock_genai.files.upload_hook = _flaky_then_fatal
        with (
            patch("lemely.io.gemini.time.sleep"),
            client.image_uploads([b"a"], concurrency=1) as uploads,
            self.assertRaises(ExternalServiceError),
        ):
            uploads.ensure()
        self.assertEqual(len(attempts), 2)

    def test_a_transient_upload_error_is_retried_and_then_succeeds(self) -> None:
        client, mock_genai = self._client(max_retries=1, backoff_seconds=0.01)
        attempts: list[int] = []

        def _flaky(_data: bytes) -> None:
            attempts.append(1)
            if len(attempts) == 1:
                raise RuntimeError("503 unavailable")

        mock_genai.files.upload_hook = _flaky
        with (
            patch("lemely.io.gemini.time.sleep"),
            client.image_uploads([b"a"], concurrency=1) as uploads,
        ):
            files = uploads.ensure()
        self.assertEqual(len(files), 1)
        self.assertEqual(len(attempts), 2)

    def test_partial_upload_failure_deletes_what_uploaded_and_skips_queued_pages(self) -> None:
        """Fix round 1, Important 1: `ensure()` used to build `self.files`
        with a plain list comprehension over `[f.result() for f in
        futures]`, which raises on the FIRST failed future -- `self.files`
        was then never set, so `delete()` (via `__exit__`) deleted nothing,
        orphaning every page that HAD uploaded. With `concurrency=1` and 4
        pages, page 2 failing must: (a) raise `ExternalServiceError`, (b)
        still delete pages 0 and 1 (the ones that did upload), and (c) never
        upload page 3 at all -- it was still queued behind the single
        worker when page 2 failed."""
        client, mock_genai = self._client(max_retries=0)

        def _fail_on_c(data: bytes) -> None:
            if data == b"c":
                raise RuntimeError("400 bad request")

        mock_genai.files.upload_hook = _fail_on_c
        images = [b"a", b"b", b"c", b"d"]
        with (
            client.image_uploads(images, concurrency=1) as uploads,
            self.assertRaises(ExternalServiceError),
        ):
            uploads.ensure()
        # "c"'s upload_hook raises before FakeFiles.upload records it, so only
        # "a" and "b" ever reach `mock_genai.files.uploads`; "d" was still
        # queued behind the single worker and is never attempted at all.
        uploaded_data = [data for data, _ in mock_genai.files.uploads]
        self.assertEqual(uploaded_data, [b"a", b"b"])
        self.assertEqual(sorted(mock_genai.files.deleted), ["files/fake-1", "files/fake-2"])

    def test_a_second_ensure_after_a_failure_reraises_the_original_cause(self) -> None:
        """Fix round 3, Minor 2: a second `ensure()` call after a failed
        first one used to resubmit every page fresh -- and since
        `_stop_event` was already set, each one immediately raised a
        generic "page N skipped" message instead of the real cause (the
        400). It must now re-raise the SAME real exception, both times."""
        client, mock_genai = self._client(max_retries=0)

        def _fail_on_b(data: bytes) -> None:
            if data == b"b":
                raise RuntimeError("400 bad request")

        mock_genai.files.upload_hook = _fail_on_b
        with client.image_uploads([b"a", b"b"], concurrency=1) as uploads:
            with self.assertRaises(ExternalServiceError) as first:
                uploads.ensure()
            with self.assertRaises(ExternalServiceError) as second:
                uploads.ensure()
        self.assertIn("400 bad request", str(first.exception))
        self.assertIn("400 bad request", str(second.exception))
        # The second call must not have re-uploaded "a" again.
        self.assertEqual(len(mock_genai.files.uploads), 1)

    def test_a_second_ensure_reraise_does_not_mutate_the_stored_exceptions_traceback(
        self,
    ) -> None:
        """Fix round 5, Minor 2: `raise self._first_error` re-raises the
        SAME stored exception object from multiple threads/call sites --
        every `raise` mutates that object's `__traceback__` (and
        `__context__`) as a side effect, corrupting whatever the FIRST
        raise had recorded. A second `ensure()` call must instead raise a
        FRESH `ExternalServiceError` chained `from` the original, leaving
        the stored original -- and its traceback -- untouched."""
        client, mock_genai = self._client(max_retries=0)

        def _fail_on_b(data: bytes) -> None:
            if data == b"b":
                raise RuntimeError("400 bad request")

        mock_genai.files.upload_hook = _fail_on_b
        with client.image_uploads([b"a", b"b"], concurrency=1) as uploads:
            with self.assertRaises(ExternalServiceError):
                uploads.ensure()
            original = uploads._first_error
            original_traceback = original.__traceback__
            with self.assertRaises(ExternalServiceError) as second:
                uploads.ensure()
        self.assertIs(uploads._first_error, original)
        self.assertIs(original.__traceback__, original_traceback)
        self.assertIsNot(second.exception, original)
        self.assertIs(second.exception.__cause__, original)

    def test_cost_ceiling_is_checked_before_any_upload(self) -> None:
        from lemely.io.cost_ledger import CostLedger

        client, mock_genai = self._client(total_usd_ceiling=1.0)
        CostLedger(client._settings.paths.output_dir / "gemini_spend.json").add(1.5, thresholds=[])
        images = [b"page-0"]
        with (
            client.image_uploads(images, concurrency=1) as uploads,
            self.assertRaises(CostCeilingError),
        ):
            self._call(client, images, uploads)
        self.assertEqual(mock_genai.files.uploads, [])

    def test_non_active_file_is_polled_until_active(self) -> None:
        client, mock_genai = self._client()
        mock_genai.files.initial_state = "PROCESSING"
        with (
            patch("lemely.io.gemini.time.sleep"),
            client.image_uploads([b"a"], concurrency=1) as uploads,
        ):
            files = uploads.ensure()
        self.assertEqual(files[0].state, "ACTIVE")
        self.assertEqual(mock_genai.files.get_calls, ["files/fake-1"])

    def test_a_failed_file_raises_external_service_error(self) -> None:
        client, mock_genai = self._client()
        mock_genai.files.initial_state = "FAILED"
        with (
            client.image_uploads([b"a"], concurrency=1) as uploads,
            self.assertRaises(ExternalServiceError),
        ):
            uploads.ensure()

    def test_processing_forever_times_out(self) -> None:
        from lemely.io import gemini as gemini_module

        client, mock_genai = self._client()
        mock_genai.files.initial_state = "PROCESSING"
        mock_genai.files.get_state = "PROCESSING"
        with (
            patch("lemely.io.gemini.time.sleep"),
            patch.object(gemini_module, "_UPLOAD_ACTIVE_TIMEOUT_SECONDS", 0.0),
            client.image_uploads([b"a"], concurrency=1) as uploads,
            self.assertRaises(ExternalServiceError),
        ):
            uploads.ensure()

    def test_a_transient_then_fatal_poll_error_raises_and_still_deletes_the_file(self) -> None:
        """Fix round 1, Important 2: `files.get` in the ACTIVE poll was
        unwrapped -- an SDK exception there escaped raw, not classified or
        retried like an upload call. A transient 503 on the first poll is
        retried; a non-transient 400 on the second raises
        `ExternalServiceError`. The file WAS created (just never reached
        ACTIVE), so it is still recorded for deletion."""
        client, mock_genai = self._client(max_retries=1, backoff_seconds=0.01)
        mock_genai.files.initial_state = "PROCESSING"
        get_calls: list[int] = []

        def _flaky_get(*, name: str, config: Any = None) -> Any:
            get_calls.append(1)
            if len(get_calls) == 1:
                raise RuntimeError("503 unavailable")
            raise RuntimeError("400 bad request")

        mock_genai.files.get = _flaky_get
        with (
            patch("lemely.io.gemini.time.sleep"),
            client.image_uploads([b"a"], concurrency=1) as uploads,
            self.assertRaises(ExternalServiceError),
        ):
            uploads.ensure()
        self.assertEqual(len(get_calls), 2)
        self.assertEqual(mock_genai.files.deleted, ["files/fake-1"])

    def test_delete_removes_every_file_and_a_delete_failure_only_warns(self) -> None:
        client, mock_genai = self._client()

        def _fail_first(name: str) -> None:
            if name.endswith("fake-1"):
                raise RuntimeError("boom")

        mock_genai.files.delete_hook = _fail_first
        with capture_logs() as logs, client.image_uploads([b"a", b"b"], concurrency=2) as uploads:
            uploads.ensure()
        self.assertEqual(mock_genai.files.deleted, ["files/fake-2"])
        self.assertIsNone(uploads.files)
        warnings = [e for e in logs if e["event"] == "gemini_file_delete_failed"]
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0]["name"], "files/fake-1")
        self.assertEqual(warnings[0]["error"], "boom")

    def test_delete_racing_an_in_flight_ensure_still_deletes_everything(self) -> None:
        """Fix round 3, Minor 1: `delete()` used to drain `_uploaded`
        BEFORE taking `_lock` -- so a `delete()` called from another
        thread while `ensure()` was still uploading snapshotted whatever
        had been recorded SO FAR (nothing, if called while every upload is
        still in flight) and missed every page `ensure()` went on to
        upload afterwards. `delete()` now takes `_lock` first -- the same
        lock `ensure()` holds for its whole pass -- so it blocks until
        `ensure()` is done before draining.

        Fix round 5, Minor 3: spins (bounded, no sleep-and-hope) until
        `delete_thread` is both alive and genuinely blocked -- `_lock` is
        locked (held by `ensure_thread` since before `delete_thread` even
        started) -- before releasing the uploads, so this actually proves
        `delete()` was waiting rather than merely finishing to race ahead
        by luck. Asserts both threads are gone (`join` truly returned, not
        timed out) at the end.
        """
        client, mock_genai = self._client()
        lock = threading.Lock()
        started = 0
        both_started = threading.Event()
        release = threading.Event()

        def _hook(_data: bytes) -> None:
            nonlocal started
            with lock:
                started += 1
                if started == 2:
                    both_started.set()
            self.assertTrue(release.wait(timeout=5))

        mock_genai.files.upload_hook = _hook
        uploads = client.image_uploads([b"a", b"b"], concurrency=2)
        ensure_thread = threading.Thread(target=uploads.ensure)
        ensure_thread.start()
        # Both uploads are now blocked INSIDE the hook -- before FakeFiles
        # ever records them -- so `_uploaded` is guaranteed empty at this
        # instant. A `delete()` racing in here is the exact scenario Minor
        # 1 fixes.
        self.assertTrue(both_started.wait(timeout=5))
        delete_thread = threading.Thread(target=uploads.delete)
        delete_thread.start()
        deadline = time.monotonic() + 5
        while not (delete_thread.is_alive() and uploads._lock.locked()):
            if time.monotonic() >= deadline:
                self.fail("delete_thread never reached the blocked-on-_lock state")
            time.sleep(0.01)
        release.set()
        ensure_thread.join(timeout=5)
        delete_thread.join(timeout=5)
        self.assertFalse(ensure_thread.is_alive())
        self.assertFalse(delete_thread.is_alive())
        self.assertEqual(sorted(mock_genai.files.deleted), ["files/fake-1", "files/fake-2"])

    def test_retry_of_the_generate_call_does_not_re_upload(self) -> None:
        client, mock_genai = self._client(max_retries=1, backoff_seconds=0.01)
        mock_genai.models.generate_content.side_effect = [
            RuntimeError("503 unavailable"),
            _mock_response('{"value": "x"}'),
        ]
        images = [b"page-0", b"page-1"]
        with (
            patch("lemely.io.gemini.time.sleep"),
            client.image_uploads(images, concurrency=2) as uploads,
        ):
            self._call(client, images, uploads)
        self.assertEqual(len(mock_genai.files.uploads), 2)
        self.assertEqual(mock_genai.models.generate_content.call_count, 2)

    def test_image_uploads_without_image_parts_is_a_value_error(self) -> None:
        client, _ = self._client()
        with client.image_uploads([b"a"], concurrency=1) as uploads, self.assertRaises(ValueError):
            client.generate_structured(
                system_prompt="s",
                user_prompt="u",
                image_uploads=uploads,
                response_schema=_SimpleSchema,
                prompt_version="1",
            )

    def test_image_uploads_carrying_different_images_than_image_parts_is_a_value_error(
        self,
    ) -> None:
        """Fix round 1, Minor 2: `image_uploads` must be built from the SAME
        page bytes as `image_parts` -- the cache key is derived from
        `image_parts`, so a mismatch would silently cache one paper's key
        against another paper's uploaded images."""
        client, _ = self._client()
        with (
            client.image_uploads([b"a", b"b"], concurrency=1) as uploads,
            self.assertRaises(ValueError),
        ):
            client.generate_structured(
                system_prompt="s",
                user_prompt="u",
                image_parts=[b"a", b"different"],
                image_uploads=uploads,
                response_schema=_SimpleSchema,
                prompt_version="1",
            )


class US034MissingFlashRowTests(unittest.TestCase):
    """US-034: `gemini-3.5-flash` had no row in `_DEFAULT_PRICING`, so it fell
    through the length-descending substring match to the unrecognised-model
    fallback and was silently billed at the `gemini-2.5-flash` rate
    ($0.30/$2.50 per 1M) instead of its real rate ($1.50/$9.00 per 1M,
    ai.google.dev/gemini-api/docs/pricing, retrieved 2026-09-21) — understating
    the $14 total_usd_ceiling's ledger for any run configured to use it."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()

    def test_default_pricing_has_gemini_3_5_flash_row(self) -> None:
        from lemely.io.gemini import _DEFAULT_PRICING

        self.assertEqual(_DEFAULT_PRICING["gemini-3.5-flash"], (0.001500, 0.009000))

    def test_gemini_3_5_flash_resolves_to_its_own_row_not_the_2_5_flash_fallback(self) -> None:
        """The regression that matters: the length-descending substring match
        must resolve `gemini-3.5-flash` to its own row, not let
        `gemini-2.5-flash` (or any other key) shadow it via the fallback."""
        from lemely.io.gemini import _resolve_pricing

        settings = _make_settings(self.tmp)
        price = _resolve_pricing("gemini-3.5-flash", settings)
        self.assertEqual(price, (0.001500, 0.009000))
        self.assertNotEqual(price, (0.000300, 0.002500))


class US034FallbackVisibilityTests(unittest.TestCase):
    """US-034: `lemely doctor` must name any configured model resolving
    through `_resolve_pricing`'s unrecognised-model fallback rather than an
    exact or promo-dated row, so a future misconfiguration is visible instead
    of silently under-billing the $14 ceiling."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()

    def test_an_unrecognised_model_is_reported_as_resolving_via_fallback(self) -> None:
        from lemely.io.gemini import fallback_pricing_status

        settings = _make_settings(self.tmp)
        ok, detail = fallback_pricing_status(settings, {"extraction": "totally-fake-model-xyz"})
        self.assertFalse(ok)
        self.assertIn("totally-fake-model-xyz", detail)
        self.assertIn("extraction", detail)

    def test_the_three_really_configured_models_do_not_hit_the_fallback(self) -> None:
        """No currently configured model hits the fallback today (US-034) —
        this is a no-op guard until someone configures a model this table
        does not recognise."""
        from lemely.io.gemini import fallback_pricing_status

        settings = _make_settings(self.tmp)
        configured = {
            "extraction": settings.gemini.extraction_model,
            "correction": settings.gemini.correction_model,
            "mark_scheme": settings.gemini.mark_scheme_model,
        }
        ok, detail = fallback_pricing_status(settings, configured)
        self.assertTrue(ok, msg=detail)

    def test_a_pricing_override_is_not_reported_as_a_fallback_hit(self) -> None:
        from lemely.io.gemini import fallback_pricing_status

        settings = _make_settings(self.tmp, pricing={"totally-custom-model": [0.001, 0.002]})
        ok, detail = fallback_pricing_status(settings, {"extraction": "totally-custom-model"})
        self.assertTrue(ok, msg=detail)
