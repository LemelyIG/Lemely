"""Unit tests for lemely.io.gemini.GeminiClient (genai.Client mocked)."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from pydantic import BaseModel, Field

from lemely.io.gemini import (
    GeminiClient,
    _is_3x,
    _reset_process_counters,
    _strip_schema,
    process_token_totals,
)
from lemely.runtime.config import PathsSettings, load_settings
from lemely.runtime.errors import ExternalServiceError, ParseError
from lemely.runtime.events import EventType, bus


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
