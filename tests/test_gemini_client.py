"""Unit tests for lemely.io.gemini.GeminiClient (genai.Client mocked)."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from pydantic import BaseModel

from lemely.io.gemini import (
    GeminiClient,
    _reset_process_counters,
    _strip_schema,
    process_token_totals,
)
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
