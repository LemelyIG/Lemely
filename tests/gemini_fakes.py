"""Fakes for the google-genai client surface Lemely touches.

`MagicMock()` is fine for `models.generate_content`, but not for `files`:
once whole-paper page images go through the Files API (spec 2026-09-26
§7), `types.Part.from_uri(file_uri=<MagicMock>)` fails pydantic validation.
`FakeFiles` returns objects with real ``str`` fields, records every upload
and delete, and exposes hooks so a test can block inside an upload (to
prove overlap with a ``threading.Barrier``) or make one fail.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from unittest.mock import MagicMock

from google.genai import types

from lemely.runtime.config import GeminiSettings, PathsSettings, Settings, load_settings


@dataclass
class FakeFile:
    name: str
    uri: str
    mime_type: str
    state: str = "ACTIVE"


class FakeFiles:
    """Stands in for ``genai.Client().files``."""

    def __init__(self, *, initial_state: str = "ACTIVE") -> None:
        self.initial_state = initial_state
        self.uploads: list[tuple[bytes, dict[str, Any]]] = []
        self.deleted: list[str] = []
        self.get_calls: list[str] = []
        self.get_state: str = "ACTIVE"
        self.upload_hook: Callable[[bytes], None] | None = None
        self.delete_hook: Callable[[str], None] | None = None
        self._lock = threading.Lock()
        self._counter = 0

    def upload(self, *, file: Any, config: Any = None) -> FakeFile:
        data = file.read() if hasattr(file, "read") else Path(file).read_bytes()
        cfg = dict(config or {})
        if self.upload_hook is not None:
            self.upload_hook(data)
        with self._lock:
            self._counter += 1
            name = f"files/fake-{self._counter}"
            self.uploads.append((data, cfg))
        return FakeFile(
            name=name,
            uri=f"https://generativelanguage.googleapis.com/v1beta/{name}",
            mime_type=str(cfg.get("mime_type", "application/octet-stream")),
            state=self.initial_state,
        )

    def get(self, *, name: str, config: Any = None) -> FakeFile:
        with self._lock:
            self.get_calls.append(name)
        return FakeFile(
            name=name,
            uri=f"https://generativelanguage.googleapis.com/v1beta/{name}",
            mime_type="image/png",
            state=self.get_state,
        )

    def delete(self, *, name: str, config: Any = None) -> None:
        if self.delete_hook is not None:
            self.delete_hook(name)
        with self._lock:
            self.deleted.append(name)


def fake_genai_client() -> MagicMock:
    """A ``MagicMock`` SDK client whose ``files`` is a :class:`FakeFiles`."""
    client = MagicMock()
    client.files = FakeFiles()
    return client


#: Sub-project C P4: the pre-flip default of every setting the flip changed. The
#: fake-based tests, tests/test_llm_golden.py among them, pin the Gemini path with it.
PRE_FLIP_DEFAULTS: dict[str, object] = {
    "gemini.model": "gemini-2.5-flash",
    "gemini.mark_scheme_model": "gemini-2.5-flash",
    "gemini.extraction_model": "gemini-3.5-flash-lite",
    "gemini.correction_model": "gemini-3.1-flash-lite",
    "gemini.generation_model": "gemini-3.5-flash-lite",
    "gemini.scan_metadata_model": "gemini-3.5-flash-lite",
    "gemini.escalation_model": "gemini-3.8-flash",
    "gemini.escalation_confidence_threshold": 0.80,
    "gemini.correction_shared_prefix": False,
    "gemini.claude_cache_for": {},
    "gemini.claude_effort_for": {},
    "gemini.review_confidence_threshold_for": {},
    "gemini.adjudication_model": None,
    "gemini.adjudication_max_leaves": 3,
    "gemini.adjudication_confidence_threshold": 0.80,
    "gemini.adjudication_drawing_leaves": False,
    "gemini.adjudication_drawing_max_leaves": 3,
    "gemini.adjudication_reread_disagreed": False,
    "gemini.correction_retry_median": False,
    "binding.read_model": "gemini-3.8-flash",
    "binding.retry_model": "gemini-3.8-flash",
}


def _pinned(settings: Settings, values: Mapping[str, object]) -> Settings:
    for dotted, value in values.items():
        section_name, _, field = dotted.partition(".")
        section = getattr(settings, section_name)
        settings = settings.model_copy(
            update={
                section_name: type(section).model_validate({**section.model_dump(), field: value})
            }
        )
    return settings


def pre_flip_gemini(**overrides: Any) -> GeminiSettings:
    """``GeminiSettings`` at the pre-flip defaults, with ``overrides`` on top."""
    pinned = {
        k.partition(".")[2]: v for k, v in PRE_FLIP_DEFAULTS.items() if k.startswith("gemini.")
    }
    return GeminiSettings(**{**pinned, **overrides})


def pin_pre_flip(settings: Settings) -> Settings:
    """``settings`` with the pre-flip Gemini defaults (:data:`PRE_FLIP_DEFAULTS`) put back."""
    return _pinned(settings, PRE_FLIP_DEFAULTS)


def make_settings(tmp: str) -> Settings:
    """Default settings with cache/output redirected into ``tmp`` (env-isolated)."""
    snap = dict(os.environ)
    for k in list(os.environ):
        if k.startswith("LEMELY_"):
            del os.environ[k]
    try:
        s = load_settings(toml_path=None, cwd=Path(tmp))
    finally:
        os.environ.clear()
        os.environ.update(snap)
    return _pinned(
        s.model_copy(
            update={
                "paths": PathsSettings(
                    cache_dir=Path(tmp) / ".cache", output_dir=Path(tmp) / "outputs"
                )
            }
        ),
        PRE_FLIP_DEFAULTS,
    )


def mock_response(
    text: str,
    *,
    prompt: int = 10,
    candidates: int = 20,
    thoughts: int = 0,
    cached: int = 0,
    finish_reason: Literal["STOP", "MAX_TOKENS"] = "STOP",
) -> MagicMock:
    """A stubbed Gemini response with every usage field set to a real int.

    A bare ``MagicMock`` attribute reads as 1 via ``int()``, so each token field
    is set explicitly.
    """
    resp = MagicMock()
    resp.text = text
    cand = MagicMock()
    # The SDK's own str-enum member, so str() is "FinishReason.STOP" as in production.
    cand.finish_reason = types.FinishReason[finish_reason]
    resp.candidates = [cand]
    resp.usage_metadata = MagicMock(
        prompt_token_count=prompt,
        candidates_token_count=candidates,
        thoughts_token_count=thoughts,
        cached_content_token_count=cached,
    )
    return resp
