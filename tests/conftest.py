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

import lemely.runtime.config as config_module
from lemely.runtime.config import Settings

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture(scope="session", autouse=True)
def _disable_dotenv_file() -> Iterator[None]:
    original = Settings.model_config.get("env_file")
    Settings.model_config["env_file"] = None
    try:
        yield
    finally:
        Settings.model_config["env_file"] = original


@pytest.fixture(scope="session", autouse=True)
def _disable_ambient_toml() -> Iterator[None]:
    """Neutralise *ambient* ``lemely.toml`` discovery for the whole session.

    A developer's local ``lemely.toml`` — at the real repo root (``Path.cwd()``)
    or in ``~/.config/lemely/`` — would otherwise leak into ``load_settings()``
    calls that pass no explicit ``toml_path``/``cwd``, flipping defaults-only
    assertions. This wrapper suppresses discovery of those two ambient files but
    still discovers a ``lemely.toml`` inside a caller-supplied temporary ``cwd``
    (as the TOML-discovery test does) and never touches explicit ``toml_path``.
    """
    from pathlib import Path as _Path

    original = config_module._discover_toml
    real_root_toml = (_Path.cwd() / "lemely.toml").resolve()

    def _guarded_discovery(cwd: Path) -> Path | None:
        found = original(cwd)
        if found is None:
            return None
        resolved = found.resolve()
        # Suppress the real repo-root toml and any home-config toml (ambient
        # developer config); allow temp-cwd tomls that tests create explicitly.
        if resolved == real_root_toml or "lemely" in resolved.parent.parts[-2:]:
            return None
        return found

    config_module._discover_toml = _guarded_discovery  # type: ignore[assignment]
    try:
        yield
    finally:
        config_module._discover_toml = original  # type: ignore[assignment]
