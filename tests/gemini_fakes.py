"""Fakes for the google-genai client surface Lemely touches.

`MagicMock()` is fine for `models.generate_content`, but not for `files`:
once whole-paper page images go through the Files API (spec 2026-09-26
§7), `types.Part.from_uri(file_uri=<MagicMock>)` fails pydantic validation.
`FakeFiles` returns objects with real ``str`` fields, records every upload
and delete, and exposes hooks so a test can block inside an upload (to
prove overlap with a ``threading.Barrier``) or make one fail.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock


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
