"""The two fixtures every sandbox-aware test module imports.

``from tests.sandbox_fixtures import in_process_sandbox, sandboxed  # noqa: F401``

Both shut the module workers down and clear the cached settings on setup as
well as on teardown, so a child left over from another module, or the start
cool-down of a failed start, never leaks into a test.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from lemely.runtime import sandbox
from lemely.runtime.config import SandboxSettings

#: The cached function itself: during a test ``sandbox.sandbox_settings`` is
#: the patched stand-in, which has no ``cache_clear``.
_CACHED_SANDBOX_SETTINGS = sandbox.sandbox_settings


def _reset_workers() -> None:
    sandbox.EXTRACTION_WORKER.shutdown()
    sandbox.INTERACTIVE_WORKER.shutdown()
    _CACHED_SANDBOX_SETTINGS.cache_clear()


@pytest.fixture
def in_process_sandbox(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Run every sandboxed target in the test process.

    For tests that patch ``pymupdf``, ``pdfium`` or ``PIL`` in this process,
    which a child would never see.
    """
    _reset_workers()
    monkeypatch.setattr(sandbox, "sandbox_settings", lambda: SandboxSettings(enabled=False))
    yield
    _reset_workers()


@pytest.fixture
def sandboxed(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Run sandboxed targets in real children, under the default settings.

    A test that needs other limits or timeouts patches
    ``sandbox.sandbox_settings`` again with its own ``SandboxSettings``.
    """
    _reset_workers()
    monkeypatch.setattr(sandbox, "sandbox_settings", lambda: SandboxSettings(enabled=True))
    yield
    _reset_workers()
