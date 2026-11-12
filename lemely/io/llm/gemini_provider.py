"""Gemini through google-genai: GeminiClient's call code, moved here unchanged (spec §1).

Request building, the explicit prefix cache, the Files API parts and the
code-execution tool are exactly what ``GeminiClient._call_once`` and
``_call_code_execution_once`` did. Spend is recorded by the client from the
returned reply, before it looks at the stop reason, as before.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, cast

from lemely.io.llm.errors import TransientCallError
from lemely.io.llm.provider import ProviderReply
from lemely.io.providers import ProviderError
from lemely.runtime.errors import ExternalServiceError

if TYPE_CHECKING:
    from pydantic import BaseModel

    from lemely.io.gemini import GeminiClient
    from lemely.io.llm.request import LLMRequest


class GeminiProvider:
    """One attempt on a Gemini model."""

    def __init__(self, client: GeminiClient) -> None:
        self._client = client

    def count_tokens(self, req: LLMRequest) -> int | None:
        """Gemini calls are not preflighted."""
        return None

    def complete(self, req: LLMRequest, *, log: Any) -> ProviderReply:
        """Send ``req``; a transient SDK failure raises ``TransientCallError``."""
        if req.tool is not None:
            return self._complete_code_execution(req)
        from google.genai import types

        from lemely.io.gemini import (
            _MEDIA_RESOLUTION_LEVELS,
            _is_3x,
            _is_transient,
            _strip_schema,
        )

        client = self._client
        model = req.model
        media_resolution = req.media_resolution
        resolved_media_resolution = (
            _MEDIA_RESOLUTION_LEVELS.get(media_resolution, media_resolution)
            if media_resolution is not None
            else None
        )
        file_parts: list[Any] = []
        if req.uploads is not None:
            for uploaded in req.uploads.ensure():
                file_parts.append(
                    types.Part.from_uri(
                        file_uri=uploaded.uri,
                        mime_type=uploaded.mime_type,
                        media_resolution=resolved_media_resolution,
                    )
                )
        elif req.images:
            for image in req.images:
                file_parts.append(
                    types.Part.from_bytes(
                        data=image.data,
                        mime_type="image/png",
                        media_resolution=resolved_media_resolution,
                    )
                )
        elif req.documents:
            for doc in req.documents:
                if doc.source_path is None:
                    raise ProviderError("a Gemini document needs a source_path to upload")
                file_parts.append(client._client.files.upload(file=doc.source_path))

        is_3x = _is_3x(model)
        gen_params = client._resolved_gen_params(req.task_tag, model)
        schema = cast("type[BaseModel]", req.response_schema)
        stripped_schema = _strip_schema(schema.model_json_schema(), is_3x=is_3x)
        log.debug(
            "gemini_schema_sent",
            schema=schema.__name__,
            top_level_properties=list((stripped_schema.get("properties") or {}).keys()),
        )
        t0 = time.monotonic()
        config_kwargs: dict[str, Any] = {
            "max_output_tokens": req.max_output_tokens,
            "response_mime_type": "application/json",
            "system_instruction": req.system,
        }
        if is_3x:
            config_kwargs["thinking_config"] = types.ThinkingConfig(
                thinking_level=gen_params["thinking_level"]
            )
            config_kwargs["response_json_schema"] = stripped_schema
        else:
            config_kwargs["thinking_config"] = types.ThinkingConfig(
                thinking_budget=gen_params["thinking_budget"]
            )
            config_kwargs["response_schema"] = stripped_schema
            config_kwargs["temperature"] = gen_params["temperature"]
            config_kwargs["top_p"] = gen_params["top_p"]
            config_kwargs["seed"] = gen_params["seed"]
        prefix = req.shared_prefix
        if prefix is not None and prefix.cache == "explicit" and is_3x:
            cache_name = client.cached_prefix_handle(model, prefix, log=log)
            if cache_name is not None:
                # The cache carries the system instruction; the API refuses both.
                del config_kwargs["system_instruction"]
                config_kwargs["cached_content"] = cache_name
        try:
            response = client._client.models.generate_content(
                model=model,
                config=types.GenerateContentConfig(**config_kwargs),
                contents=[req.prompt, *file_parts],
            )
        except Exception as exc:
            if _is_transient(exc):
                raise TransientCallError(str(exc)) from exc
            raise ExternalServiceError(str(exc)) from exc
        latency_ms = int((time.monotonic() - t0) * 1000)
        finish_reason = response.candidates[0].finish_reason if response.candidates else None
        # The SDK's FinishReason is a str-enum: str() gives "FinishReason.MAX_TOKENS",
        # so the normalised value compares the member name; stop_detail keeps str().
        name = getattr(finish_reason, "name", str(finish_reason))
        return ProviderReply(
            text=response.text or "",
            usage_response=response,
            stop_reason="max_tokens" if name == "MAX_TOKENS" else None,
            stop_detail=str(finish_reason),
            latency_ms=latency_ms,
        )

    def _complete_code_execution(self, req: LLMRequest) -> ProviderReply:
        """Gemini's ``code_execution`` tool; the reply text is what the code printed."""
        from google.genai import types

        tool = types.Tool(code_execution=types.ToolCodeExecution())
        t0 = time.monotonic()
        try:
            response = self._client._client.models.generate_content(
                model=req.model,
                config=types.GenerateContentConfig(tools=[tool]),
                contents=[req.prompt],
            )
        except Exception as exc:
            raise ExternalServiceError(str(exc)) from exc
        latency_ms = int((time.monotonic() - t0) * 1000)
        candidates = response.candidates or []
        parts = candidates[0].content.parts if candidates and candidates[0].content else []
        output = ""
        for part in parts or []:
            result = getattr(part, "code_execution_result", None)
            value = getattr(result, "output", None) if result is not None else None
            if value:
                output = str(value)
                break
        return ProviderReply(
            text=output,
            usage_response=response,
            stop_reason=None,
            stop_detail="",
            latency_ms=latency_ms,
        )
