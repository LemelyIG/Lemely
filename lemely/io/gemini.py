"""Shared Gemini AI client: retry, persistent cache, cost guard, structured logging."""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any, TypeVar

import structlog
from pydantic import BaseModel
from tenacity import (
    RetryCallState,
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from lemely.runtime.config import Settings
from lemely.runtime.errors import ExternalServiceError, ParseError
from lemely.runtime.events import EventType, bus

_T = TypeVar("_T", bound=BaseModel)

# Built-in pricing table: model-name substring → (input_usd_per_1k, output_usd_per_1k).
# Matched by substring so "gemini-2.5-flash-preview-05-20" maps to the flash row.
_DEFAULT_PRICING: dict[str, tuple[float, float]] = {
    "gemini-2.5-flash-lite": (0.000075, 0.000300),
    "gemini-2.5-flash": (0.000150, 0.000600),
    "gemini-2.5-pro": (0.001250, 0.005000),
}

_GEMINI_UNSUPPORTED_KEYS = {"additionalProperties", "additional_properties", "$defs", "title", "default"}

_process_input_tokens: int = 0
_process_output_tokens: int = 0
_process_accumulated_usd: float = 0.0
_process_cost_by_task: dict[str, float] = {}


def _reset_process_counters() -> None:
    global _process_input_tokens, _process_output_tokens, _process_accumulated_usd, _process_cost_by_task
    _process_input_tokens = 0
    _process_output_tokens = 0
    _process_accumulated_usd = 0.0
    _process_cost_by_task = {}


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


def _resolve_refs(schema: Any, defs: dict[str, Any], _resolving: frozenset[str] = frozenset()) -> Any:
    if isinstance(schema, dict):
        if "$ref" in schema:
            name = schema["$ref"].split("/")[-1]
            if name in _resolving:
                # Circular reference — Gemini can't handle recursive schemas;
                # emit a generic object to break the cycle.
                return {"type": "object"}
            return _resolve_refs(defs[name], defs, _resolving | {name})
        return {k: _resolve_refs(v, defs, _resolving) for k, v in schema.items() if k not in _GEMINI_UNSUPPORTED_KEYS}
    if isinstance(schema, list):
        return [_resolve_refs(i, defs, _resolving) for i in schema]
    return schema


def _strip_schema(schema: Any) -> Any:
    defs = schema.get("$defs", {}) if isinstance(schema, dict) else {}
    return _resolve_refs(schema, defs)


class _TransientError(Exception):
    """Wraps transient Gemini SDK errors so tenacity can detect them."""


class GeminiClient:
    def __init__(self, settings: Settings, *, _genai_client: Any = None) -> None:
        self._settings = settings
        self._raw_client: Any = _genai_client

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

    def _cache_key(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        prompt_version: str,
        file_paths: list[Path] | None,
        extra_key: str,
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
        combined = f"{model}:{prompt_hash}:{files_hash}"
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
        if g.monthly_usd_ceiling is not None:
            if _process_accumulated_usd >= g.monthly_usd_ceiling:
                raise ExternalServiceError(
                    f"USD ceiling (${g.monthly_usd_ceiling:.4f}) exceeded; "
                    f"accumulated ${_process_accumulated_usd:.4f} this process."
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
    ) -> _T:
        g = self._settings.gemini
        if model is not None:
            active_model = model
        elif task_tag is not None:
            active_model = g.model_for(task_tag)
        else:
            active_model = g.model

        log = structlog.get_logger().bind(
            component="gemini_client", model=active_model, task=task_tag or "untagged",
        )

        cache_key = self._cache_key(
            active_model, system_prompt, user_prompt, prompt_version, file_paths, extra_cache_key,
        )
        cache_path = self._cache_path(cache_key)

        if cache_path.exists():
            log.info("gemini_cache_hit", cache_key=cache_key)
            bus.publish(
                EventType.GEMINI_CACHE_HIT,
                task=task_tag or "untagged",
                model=active_model,
                cache_key=cache_key,
            )
            return response_schema.model_validate_json(
                cache_path.read_text(encoding="utf-8")
            )

        self._check_cost_ceiling()

        bus.publish(
            EventType.GEMINI_CALL_START,
            task=task_tag or "untagged",
            model=active_model,
        )
        t0 = time.monotonic()
        raw_text = self._call_with_retry(
            active_model, system_prompt, user_prompt, file_paths, response_schema, log, task_tag,
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
                user_prompt
                + f"\n\nYour previous response failed validation for "
                f"{response_schema.__name__} with the following error:\n{exc}\n\n"
                "Fix only the fields mentioned in the error above and return valid JSON "
                "matching the schema exactly. Do not change any other fields."
            )
            raw_text = self._call_with_retry(
                active_model, system_prompt, corrected, file_paths, response_schema, log, task_tag,
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
                        model, system_prompt, user_prompt, file_paths, response_schema, log, task_tag,
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

        thinking_budget = self._settings.gemini.thinking_budget_for.get(task_tag or "", 0)
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
                    max_output_tokens=65536,
                    thinking_config=types.ThinkingConfig(thinking_budget=thinking_budget),
                    response_mime_type="application/json",
                    response_schema=stripped_schema,
                    system_instruction=system_prompt,
                ),
                contents=[user_prompt, *file_parts],
            )
        except Exception as exc:
            msg = str(exc).lower()
            if any(t in msg for t in ("500", "503", "rate limit", "resource exhausted", "connection")):
                raise _TransientError(str(exc)) from exc
            raise ExternalServiceError(str(exc)) from exc

        latency_ms = int((time.monotonic() - t0) * 1000)

        global _process_input_tokens, _process_output_tokens, _process_accumulated_usd, _process_cost_by_task
        in_tok = int(getattr(response.usage_metadata, "prompt_token_count", 0) or 0)
        out_tok = int(getattr(response.usage_metadata, "candidates_token_count", 0) or 0)
        _process_input_tokens += in_tok
        _process_output_tokens += out_tok

        in_price, out_price = _resolve_pricing(model, self._settings)
        usd = in_tok / 1000 * in_price + out_tok / 1000 * out_price
        usd_rounded = round(usd, 6)
        _process_accumulated_usd += usd
        if task_tag:
            _process_cost_by_task[task_tag] = _process_cost_by_task.get(task_tag, 0.0) + usd

        log.info(
            "gemini_call",
            input_tokens=in_tok, output_tokens=out_tok,
            usd_cost=usd_rounded, cache_hit=False,
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
