"""Shared Gemini AI client: retry, persistent cache, cost guard, structured logging."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Literal, TypeVar

import structlog
from pydantic import BaseModel
from tenacity import (
    RetryCallState,
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from lemely.io.cost_ledger import CostLedger
from lemely.runtime.config import Settings
from lemely.runtime.errors import ExternalServiceError, ParseError
from lemely.runtime.events import EventType, bus

_T = TypeVar("_T", bound=BaseModel)

# Output-token cap sent on every call. A module constant rather than a literal
# because it feeds the cache-key fingerprint (spec 3.3): changing it changes what
# the model may return, so it must invalidate cached replies.
_MAX_OUTPUT_TOKENS: int = 65536

# Built-in pricing table: model-name substring → (input_usd_per_1k, output_usd_per_1k).
# GA rates (M0.2 / #26) — the table previously carried the preview price sheet
# (flash: $0.150/$0.600 per 1M) while the configured model is GA gemini-2.5-flash
# ($0.30/$2.50 per 1M), which understated real spend against total_usd_ceiling by
# 2-4x. Matched by substring so "gemini-2.5-flash-preview-05-20" still maps to the
# flash row (a *model name* can legitimately say "preview" without the pricing
# tier being the old preview tier).
_DEFAULT_PRICING: dict[str, tuple[float, float]] = {
    "gemini-2.5-flash-lite": (0.000100, 0.000400),
    "gemini-2.5-flash": (0.000300, 0.002500),
    "gemini-2.5-pro": (0.001250, 0.010000),
}

_GEMINI_UNSUPPORTED_KEYS = {
    "additionalProperties",
    "additional_properties",
    "$defs",
    "title",
    "default",
}

_process_input_tokens: int = 0
_process_output_tokens: int = 0
_process_accumulated_usd: float = 0.0
_process_cost_by_task: dict[str, float] = {}


def _reset_process_counters() -> None:
    global \
        _process_input_tokens, \
        _process_output_tokens, \
        _process_accumulated_usd, \
        _process_cost_by_task
    _process_input_tokens = 0
    _process_output_tokens = 0
    _process_accumulated_usd = 0.0
    _process_cost_by_task = {}


def reset_process_counters() -> None:
    """Reset the process-wide token/USD counters that back ``per_run_token_ceiling``.

    M0.2 / #26: until ``cache_mode="bypass"`` existed, a cache hit always
    returned before the check ran, so this ceiling was effectively dead. Bypassed
    calls reach the API every time, which is what arms it.

    The counters accumulate for the lifetime of the process **on purpose**: the
    ceiling is per *run*, and a run is allowed to drive many sweeps. Sizing it
    is therefore a budget decision, not a code one — ``lemely.toml`` sets the
    operative value (2,000,000, against ~115k tokens per golden sweep, so ~17
    sweeps fit). A multi-sweep run must NOT reset between its sweeps: that would
    convert a run-level budget guard into a per-sweep one and let a runaway
    script spend without limit.

    Call this only when a long-lived process genuinely begins a second,
    independent run. Previously exposed only as the private
    ``_reset_process_counters`` test helper.
    """
    _reset_process_counters()


def process_token_totals() -> tuple[int, int]:
    """Read-only accessor for tests / doctor: (input_tokens, output_tokens)."""
    return _process_input_tokens, _process_output_tokens


def process_token_totals_by_task() -> dict[str, float]:
    """Return accumulated USD cost broken down by task_tag."""
    return dict(_process_cost_by_task)


def _resolve_pricing(model: str, settings: Settings) -> tuple[float, float]:
    """Return (input_usd_per_1k, output_usd_per_1k) for the given model.

    Checks user-configured overrides first, then built-in defaults by substring match.
    Falls back to Flash rates with a warning if the model is unrecognised.
    """
    user = settings.gemini.pricing
    if model in user:
        p = user[model]
        return (float(p[0]), float(p[1]))
    # Substring match against built-in table (longest key wins to avoid flash matching flash-lite).
    for key in sorted(_DEFAULT_PRICING, key=len, reverse=True):
        if key in model:
            return _DEFAULT_PRICING[key]
    structlog.get_logger().warning("gemini_unknown_model_pricing", model=model)
    return _DEFAULT_PRICING["gemini-2.5-flash"]


def _resolve_refs(
    schema: Any, defs: dict[str, Any], _resolving: frozenset[str] = frozenset()
) -> Any:
    if isinstance(schema, dict):
        if "$ref" in schema:
            name = schema["$ref"].split("/")[-1]
            if name in _resolving:
                # Circular reference — Gemini can't handle recursive schemas;
                # emit a generic object to break the cycle.
                return {"type": "object"}
            return _resolve_refs(defs[name], defs, _resolving | {name})
        return {
            k: _resolve_refs(v, defs, _resolving)
            for k, v in schema.items()
            if k not in _GEMINI_UNSUPPORTED_KEYS
        }
    if isinstance(schema, list):
        return [_resolve_refs(i, defs, _resolving) for i in schema]
    return schema


def _strip_schema(schema: Any) -> Any:
    defs = schema.get("$defs", {}) if isinstance(schema, dict) else {}
    return _resolve_refs(schema, defs)


class _TransientError(Exception):
    """Wraps transient Gemini SDK errors so tenacity can detect them."""


class _DefaultLedger:
    """Sentinel: build the file ledger under ``paths.output_dir`` (CLI, Gradio, eval)."""


#: Default for :paramref:`GeminiClient.ledger` — build the persistent file
#: ledger at ``settings.paths.output_dir / "gemini_spend.json"``, exactly as
#: today (CLI, Gradio, eval and scripts are untouched by DS3). Pass an
#: explicit ``ledger=None`` to run with no ceiling check, no ledger file and
#: no budget events (the web process; spec DS3).
DEFAULT_LEDGER = _DefaultLedger()


class GeminiClient:
    def __init__(
        self,
        settings: Settings,
        *,
        _genai_client: Any = None,
        default_cache_mode: Literal["read_write", "bypass", "refresh"] = "read_write",
        ledger: CostLedger | _DefaultLedger | None = DEFAULT_LEDGER,
    ) -> None:
        self._settings = settings
        self._raw_client: Any = _genai_client
        self._ledger: CostLedger | None = (
            CostLedger(settings.paths.output_dir / "gemini_spend.json")
            if isinstance(ledger, _DefaultLedger)
            else ledger
        )
        #: Single source of truth for this client's cache behaviour when a
        #: call site does not pass an explicit ``cache_mode`` (spec §3.3):
        #: ``_build_run_manifest`` reads this attribute rather than assuming
        #: the ``"read_write"`` literal (#73).
        self.default_cache_mode = default_cache_mode

    @property
    def _client(self) -> Any:
        if self._raw_client is None:
            from google import genai

            api_key = (
                self._settings.gemini_api_key.get_secret_value()
                if self._settings.gemini_api_key
                else None
            )
            self._raw_client = genai.Client(api_key=api_key)
        return self._raw_client

    def start_new_run(self) -> None:
        """Reset the token/USD counters at the start of a new logical RUN.

        A *run*, not a sweep. ``per_run_token_ceiling`` budgets one whole run —
        every sweep it drives — and that is the point of it: it is the guard
        that stops a runaway multi-sweep script from spending the §10 budget.
        Resetting between sweeps would mean a script doing 100 sweeps never
        trips a ceiling sized for one, which is not a fix but the removal of
        the guard. See :func:`reset_process_counters`.

        A multi-sweep run must therefore NOT call this between its sweeps. It
        exists for a long-lived process that genuinely starts a second,
        independent run — and for tests.
        """
        reset_process_counters()

    def _resolved_gen_params(self, task_tag: str | None) -> dict[str, Any]:
        """Resolve the generation parameters that affect output determinism.

        Single source of truth for both the actual API call config
        (:meth:`_call_once`) and the cache-key fingerprint (:meth:`_cache_key`) —
        keeping them in sync is what makes the fingerprint meaningful.
        """
        g = self._settings.gemini
        key = task_tag or ""
        return {
            "thinking_budget": g.thinking_budget_for.get(key, 0),
            "temperature": g.temperature_for.get(key, g.temperature),
            "top_p": g.top_p_for.get(key, g.top_p),
            "seed": g.seed_for.get(key, g.seed),
        }

    def _params_fingerprint(
        self, model: str, task_tag: str | None, response_schema: type[BaseModel] | None = None
    ) -> str:
        """Hash every input that can change the model's output.

        Includes the response schema and ``max_output_tokens`` per spec §3.3.
        The schema matters for correctness, not just completeness: the cache key
        is ``model:prompt_hash:files_hash:params_fingerprint`` and ``prompt_hash``
        covers only the system/user prompts, so without the schema here two calls
        with identical prompts but different response schemas collide and the
        second silently receives the first one's differently-shaped reply.
        """
        params = self._resolved_gen_params(task_tag)
        schema_hash = ""
        if response_schema is not None:
            schema_json = json.dumps(response_schema.model_json_schema(), sort_keys=True)
            schema_hash = hashlib.sha256(schema_json.encode()).hexdigest()[:12]
        raw = (
            f"{model}|{params['temperature']}|{params['top_p']}"
            f"|{params['seed']}|{params['thinking_budget']}"
            f"|{_MAX_OUTPUT_TOKENS}|{schema_hash}"
        )
        return hashlib.sha256(raw.encode()).hexdigest()[:12]

    def check_reachable(self) -> None:
        """Verify the Gemini API is reachable with the configured credentials.

        Performs a lightweight ``models.list()`` request (no content generation,
        so no token/USD cost) and forces it to execute. Used by ``lemely doctor``
        to report real reachability rather than a stub.

        Raises:
            ExternalServiceError: no key is configured, the key is rejected, or
                the API/network is unreachable.
        """
        if self._settings.gemini_api_key is None:
            raise ExternalServiceError("No Gemini API key configured; cannot reach the API.")
        try:
            # models.list() returns a lazy pager; consume one item to force the
            # HTTP round-trip that actually validates auth + connectivity.
            next(iter(self._client.models.list()), None)
        except Exception as exc:
            raise ExternalServiceError(f"Gemini API not reachable: {exc}") from exc

    def _cache_key(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        prompt_version: str,
        file_paths: list[Path] | None,
        extra_key: str,
        params_fingerprint: str,
    ) -> str:
        prompt_hash = hashlib.sha256(
            (system_prompt + user_prompt + prompt_version + extra_key).encode()
        ).hexdigest()[:12]
        if file_paths:
            h = hashlib.sha256()
            for fp in sorted(file_paths):
                h.update(fp.read_bytes())
            files_hash = h.hexdigest()[:12]
        else:
            files_hash = "none"
        # M0.2 / #26: params_fingerprint (temperature/top_p/seed/thinking_budget)
        # folded in so two calls with identical generation params hit the cache
        # and two with differing params (a real A/B) do not silently collide.
        combined = f"{model}:{prompt_hash}:{files_hash}:{params_fingerprint}"
        return hashlib.sha256(combined.encode()).hexdigest()[:16]

    def _cache_path(self, key: str) -> Path:
        d = self._settings.paths.cache_dir / "gemini"
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{key}.json"

    def _check_cost_ceiling(self) -> None:
        g = self._settings.gemini
        if g.per_run_token_ceiling is not None:
            total = _process_input_tokens + _process_output_tokens
            if total >= g.per_run_token_ceiling:
                raise ExternalServiceError(
                    f"Token ceiling ({g.per_run_token_ceiling}) exceeded; accumulated {total}."
                )
        if g.total_usd_ceiling is not None and self._ledger is not None:
            ledger_total = self._ledger.total()
            if ledger_total >= g.total_usd_ceiling:
                raise ExternalServiceError(
                    f"USD ceiling (${g.total_usd_ceiling:.4f}) exceeded; persistent "
                    f"cumulative spend is ${ledger_total:.4f} (across all runs)."
                )

    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        file_paths: list[Path] | None = None,
        response_schema: type[_T],
        prompt_version: str,
        model: str | None = None,
        extra_cache_key: str = "",
        task_tag: str | None = None,
        cache_mode: Literal["read_write", "bypass", "refresh"] | None = None,
    ) -> _T:
        if cache_mode is None:
            cache_mode = self.default_cache_mode
        if cache_mode not in ("read_write", "bypass", "refresh"):
            raise ValueError(
                f"cache_mode must be one of 'read_write', 'bypass', 'refresh'; got {cache_mode!r}"
            )
        g = self._settings.gemini
        if model is not None:
            active_model = model
        elif task_tag is not None:
            active_model = g.model_for(task_tag)
        else:
            active_model = g.model

        log = structlog.get_logger().bind(
            component="gemini_client",
            model=active_model,
            task=task_tag or "untagged",
        )

        params_fingerprint = self._params_fingerprint(active_model, task_tag, response_schema)
        cache_key = self._cache_key(
            active_model,
            system_prompt,
            user_prompt,
            prompt_version,
            file_paths,
            extra_cache_key,
            params_fingerprint,
        )
        cache_path = self._cache_path(cache_key)

        # cache_mode="read_write" (default): read-then-write, current behaviour.
        # cache_mode="bypass": skip the read (always call the API); does NOT
        #   write either, so a bypassed call — used for A/B churn measurement —
        #   is fully side-effect-free with respect to the shared cache.
        # cache_mode="refresh": skip the read (always call the API) and DOES
        #   write, overwriting any existing entry — used to force-regenerate a
        #   specific known-stale response so later read_write calls see it.
        if cache_mode == "read_write" and cache_path.exists():
            log.info("gemini_cache_hit", cache_key=cache_key)
            bus.publish(
                EventType.GEMINI_CACHE_HIT,
                task=task_tag or "untagged",
                model=active_model,
                cache_key=cache_key,
            )
            return response_schema.model_validate_json(cache_path.read_text(encoding="utf-8"))

        self._check_cost_ceiling()

        bus.publish(
            EventType.GEMINI_CALL_START,
            task=task_tag or "untagged",
            model=active_model,
        )
        t0 = time.monotonic()
        raw_text = self._call_with_retry(
            active_model,
            system_prompt,
            user_prompt,
            file_paths,
            response_schema,
            log,
            task_tag,
        )
        latency_ms = int((time.monotonic() - t0) * 1000)
        log.debug("gemini_latency_ms", latency_ms=latency_ms)

        try:
            result: _T = response_schema.model_validate_json(raw_text)
        except Exception as exc:
            log.debug(
                "gemini_validation_failure",
                schema=response_schema.__name__,
                validation_error=str(exc)[:500],
                raw_response=raw_text[:2000] + ("…" if len(raw_text) > 2000 else ""),
            )
            corrected = (
                user_prompt + f"\n\nYour previous response failed validation for "
                f"{response_schema.__name__} with the following error:\n{exc}\n\n"
                "Fix only the fields mentioned in the error above and return valid JSON "
                "matching the schema exactly. Do not change any other fields."
            )
            raw_text = self._call_with_retry(
                active_model,
                system_prompt,
                corrected,
                file_paths,
                response_schema,
                log,
                task_tag,
            )
            try:
                result = response_schema.model_validate_json(raw_text)
            except Exception as exc:
                log.debug(
                    "gemini_validation_failure_retry",
                    schema=response_schema.__name__,
                    validation_error=str(exc)[:500],
                    raw_response=raw_text[:2000] + ("…" if len(raw_text) > 2000 else ""),
                )
                raise ParseError(
                    f"Gemini response did not validate against {response_schema.__name__} "
                    "even after schema-correction retry."
                ) from exc

        if cache_mode in ("read_write", "refresh"):
            cache_path.write_text(raw_text, encoding="utf-8")
        return result

    def _call_with_retry(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        file_paths: list[Path] | None,
        response_schema: type[_T],
        log: Any,
        task_tag: str | None = None,
    ) -> str:
        def _before_sleep(state: RetryCallState) -> None:
            exc = state.outcome.exception() if state.outcome else None
            err = str(exc) if exc else ""
            log.warning(
                "gemini_retry",
                attempt=state.attempt_number,
                error=err,
            )
            bus.publish(
                EventType.GEMINI_RETRY,
                task=task_tag or "untagged",
                model=model,
                attempt=state.attempt_number,
                error=err[:80],
            )

        g = self._settings.gemini
        try:
            for attempt in Retrying(
                stop=stop_after_attempt(g.max_retries + 1),
                wait=wait_exponential(multiplier=g.backoff_seconds, min=1, max=60),
                retry=retry_if_exception_type(_TransientError),
                before_sleep=_before_sleep,
                reraise=True,
            ):
                with attempt:
                    return self._call_once(
                        model,
                        system_prompt,
                        user_prompt,
                        file_paths,
                        response_schema,
                        log,
                        task_tag,
                    )
        except _TransientError as exc:
            # Retries exhausted on a transient (503/rate-limit) failure. Surface the
            # public ExternalServiceError so callers never see the private signal type.
            raise ExternalServiceError(str(exc)) from exc
        raise ParseError("Unreachable")  # pragma: no cover  # pragma: no cover

    def _call_once(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        file_paths: list[Path] | None,
        response_schema: type[_T],
        log: Any,
        task_tag: str | None = None,
    ) -> str:
        from google.genai import types

        file_parts: list[Any] = []
        if file_paths:
            for fp in file_paths:
                file_parts.append(self._client.files.upload(file=fp))

        gen_params = self._resolved_gen_params(task_tag)
        thinking_budget = gen_params["thinking_budget"]
        stripped_schema = _strip_schema(response_schema.model_json_schema())
        log.debug(
            "gemini_schema_sent",
            schema=response_schema.__name__,
            top_level_properties=list((stripped_schema.get("properties") or {}).keys()),
        )
        t0 = time.monotonic()

        try:
            response = self._client.models.generate_content(
                model=model,
                config=types.GenerateContentConfig(
                    max_output_tokens=_MAX_OUTPUT_TOKENS,
                    thinking_config=types.ThinkingConfig(thinking_budget=thinking_budget),
                    response_mime_type="application/json",
                    response_schema=stripped_schema,
                    system_instruction=system_prompt,
                    temperature=gen_params["temperature"],
                    top_p=gen_params["top_p"],
                    seed=gen_params["seed"],
                ),
                contents=[user_prompt, *file_parts],
            )
        except Exception as exc:
            msg = str(exc).lower()
            if any(
                t in msg for t in ("500", "503", "rate limit", "resource exhausted", "connection")
            ):
                raise _TransientError(str(exc)) from exc
            raise ExternalServiceError(str(exc)) from exc

        latency_ms = int((time.monotonic() - t0) * 1000)

        global \
            _process_input_tokens, \
            _process_output_tokens, \
            _process_accumulated_usd, \
            _process_cost_by_task
        in_tok = int(getattr(response.usage_metadata, "prompt_token_count", 0) or 0)
        candidates_tok = int(getattr(response.usage_metadata, "candidates_token_count", 0) or 0)
        # M0.2 / #26: thoughts_token_count was previously never counted, silently
        # understating both the ledgered output-token count and its USD cost for
        # any call made with a non-zero thinking budget (e.g. mark_scheme's 8000).
        thoughts_tok = int(getattr(response.usage_metadata, "thoughts_token_count", 0) or 0)
        out_tok = candidates_tok + thoughts_tok
        _process_input_tokens += in_tok
        _process_output_tokens += out_tok

        in_price, out_price = _resolve_pricing(model, self._settings)
        usd = in_tok / 1000 * in_price + out_tok / 1000 * out_price
        usd_rounded = round(usd, 6)
        _process_accumulated_usd += usd
        if task_tag:
            _process_cost_by_task[task_tag] = _process_cost_by_task.get(task_tag, 0.0) + usd

        # Persist cumulative spend to the cross-run ledger; this is the source of
        # truth for the hard USD ceiling. Emit budget events for the UI/ntfy.
        # DS3: a ledgerless client (the web process) skips all of this — no
        # ledger file, no budget events. Spend is still observable via the
        # unconditional `gemini_call` log line below.
        g = self._settings.gemini
        if self._ledger is not None:
            new_total, crossed = self._ledger.add(usd, thresholds=g.usd_warning_thresholds)
            for threshold in crossed:
                bus.publish(
                    EventType.BUDGET_WARNING,
                    threshold=threshold,
                    total_usd=round(new_total, 6),
                    ceiling=g.total_usd_ceiling,
                )
            if g.total_usd_ceiling is not None and new_total >= g.total_usd_ceiling:
                bus.publish(
                    EventType.BUDGET_EXCEEDED,
                    total_usd=round(new_total, 6),
                    ceiling=g.total_usd_ceiling,
                )

        log.info(
            "gemini_call",
            input_tokens=in_tok,
            output_tokens=out_tok,
            # Broken out separately from output_tokens (which now includes them)
            # so a thinking-budget change is visible in the logs rather than
            # showing up as unexplained output-token drift.
            thoughts_tokens=thoughts_tok,
            usd_cost=usd_rounded,
            cache_hit=False,
            # M0.4 reads this off the log to record which generation parameters
            # a sweep actually ran under, without re-deriving them from config
            # that may have changed since.
            params_fingerprint=self._params_fingerprint(model, task_tag, response_schema),
        )
        bus.publish(
            EventType.GEMINI_CALL_END,
            task=task_tag or "untagged",
            model=model,
            input_tokens=in_tok,
            output_tokens=out_tok,
            usd_cost=usd_rounded,
            latency_ms=latency_ms,
        )

        raw = response.text or ""
        finish = str(response.candidates[0].finish_reason if response.candidates else "")
        if finish == "MAX_TOKENS":
            raise _TransientError(f"Gemini hit max_output_tokens ({model})")
        return raw
