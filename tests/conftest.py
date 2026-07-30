"""Shared pytest fixtures and test-environment isolation.

The test suite assumes a clean configuration environment: many tests exercise
"no API key" / "defaults only" code paths and construct :class:`Settings`
directly. Pydantic-settings, however, reads a repo-root ``.env`` file
(``env_file=".env"``) at every instantiation. A developer who keeps a real
``.env`` (with ``GEMINI_API_KEY`` / ``LEMELY_GEMINI_API_KEY``) for local runs
would otherwise see those secrets leak into the suite and flip "without key"
assertions. CI has no ``.env`` and is unaffected either way.

This autouse fixture neutralises that single source for the whole session by
disabling ``.env`` file discovery in ``Settings.model_config``. It does NOT
touch ``os.environ`` — tests that need specific env vars still set them, and the
shell's exported vars (if any) still apply, exactly as in CI.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from lemely.runtime.config import Settings

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(scope="session", autouse=True)
def _disable_dotenv_file() -> Iterator[None]:
    original = Settings.model_config.get("env_file")
    Settings.model_config["env_file"] = None
    try:
        yield
    finally:
        Settings.model_config["env_file"] = original
