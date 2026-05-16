# Phase 1: Foundations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate Lemely from MVP-shaped `lemely_mvp/` package to production-shaped `lemely/{core,io,app,runtime}` package with click-based CLI, runtime infrastructure (config / logging / errors), `pyproject.toml` packaging, and CI quality gates — while preserving all existing behaviour and keeping the 24 existing tests green at every commit.

**Architecture:** Move existing modules into a layered package (`core` pure logic, `io` touches disk, `app` user-facing, `runtime` cross-cutting). Add three new runtime modules (`config`, `logging`, `errors`). Replace `argparse` with `click` and split human-mode rendering into `app/renderers.py`. No new features in this phase; same commands, same JSON output shapes. Quality tooling (`ruff` strict, `mypy` strict, `import-linter`, `pre-commit`, GitHub Actions) enforces the architecture going forward.

**Tech Stack:** Python 3.13, Pydantic v2, `pydantic-settings`, `structlog`, `click`, `rich`, `tenacity`, `hatchling`, `ruff`, `mypy`, `import-linter`, `pytest`, `pytest-cov`, `pre-commit`, GitHub Actions.

---

## Prerequisites

- **Venv:** currently at `./lemely/`. Task 1 renames it to `.venv/` to free the `lemely/` directory for the new source package. Existing memory pointer (`feedback_venv.md`) is updated as part of that task.
- **Baseline:** before starting, confirm 24 tests pass: `source ./lemely/bin/activate && python -m unittest discover -v` → `Ran 24 tests in <Xs> OK`.
- **Git signing:** every commit in this plan uses `git commit -S -m "..."` (SSH signing already configured in this repo).

## Conventions used throughout this plan

- Run commands from the repo root (`/home/sico/Code/Lemely`) unless stated otherwise.
- `pytest` is the test runner from Task 2 onward; the pre-existing `unittest` tests run unchanged under `pytest` because the latter discovers `unittest.TestCase` subclasses natively.
- Every commit message follows: `<type>: <short summary>` where `<type>` is one of `feat`, `refactor`, `chore`, `test`, `docs`, `build`, `ci`.
- The footer of every commit message includes the standard `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>` line — passed via HEREDOC for formatting.

---

### Task 1: Rename venv from `./lemely/` to `.venv/`

**Files:**
- Rename: `./lemely/` → `.venv/`
- Modify: `/home/sico/.claude/projects/-home-sico-Code-Lemely/memory/feedback_venv.md`

The current venv occupies the directory we want for the new source package. Rename it first; subsequent tasks assume `.venv/`.

- [ ] **Step 1: Verify baseline tests pass**

```bash
source ./lemely/bin/activate && python -m unittest discover -v 2>&1 | tail -5
```
Expected last lines:
```
Ran 24 tests in <X>s

OK
```

- [ ] **Step 2: Deactivate and rename**

```bash
deactivate 2>/dev/null; mv ./lemely .venv
```
Expected: no output; `ls -d .venv` succeeds; `ls -d lemely` fails.

- [ ] **Step 3: Re-activate from new path and re-verify**

```bash
source ./.venv/bin/activate && python -m unittest discover -v 2>&1 | tail -5
```
Expected: same `Ran 24 tests in <X>s OK`.

- [ ] **Step 4: Update memory pointer**

Edit `/home/sico/.claude/projects/-home-sico-Code-Lemely/memory/feedback_venv.md` to replace `./lemely/` with `.venv/` everywhere in the body, and update the description line. Keep frontmatter intact.

- [ ] **Step 5: Add `.venv/` to `.gitignore`**

Create or extend `.gitignore` with:
```
.venv/
__pycache__/
*.pyc
.pytest_cache/
.mypy_cache/
.ruff_cache/
htmlcov/
.coverage
build/
dist/
*.egg-info/
.lemely-cache/
```

- [ ] **Step 6: Commit**

```bash
git add .gitignore
git commit -S -m "$(cat <<'EOF'
chore: rename venv to .venv to free lemely/ for new package

The MVP venv lived at ./lemely/; the production restructure needs that
path for the renamed lemely/ source package. Standardising on .venv/ also
matches typical Python project conventions.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Add `pyproject.toml`, lockfile, and dev-tool configuration

**Files:**
- Create: `pyproject.toml`
- Create: `requirements.lock`
- Delete: `requirements.txt`

This task introduces packaging metadata and configures every quality tool the plan uses later (`ruff`, `mypy`, `pytest`, coverage, `import-linter`). No source-code changes yet — existing tests run unchanged.

- [ ] **Step 1: Write `pyproject.toml`**

Create `pyproject.toml` with this exact content:

```toml
[build-system]
requires = ["hatchling>=1.25"]
build-backend = "hatchling.build"

[project]
name = "lemely"
version = "0.1.0"
description = "Accuracy-first educational assessment tool for CAIE marking workflows"
readme = "README.md"
requires-python = ">=3.12,<3.15"
license = { text = "Proprietary" }
authors = [{ name = "Yassin Diab", email = "lemelyig@gmail.com" }]
dependencies = [
  "pydantic>=2.13,<3",
  "pydantic-settings>=2.4,<3",
  "click>=8.3,<9",
  "rich>=15,<16",
  "structlog>=24,<25",
  "tenacity>=9,<10",
  "google-genai>=2.1,<3",
  "PyMuPDF>=1.27,<2",
  "Pillow>=12,<13",
  "jinja2>=3.1,<4",
]

[project.optional-dependencies]
ui = ["gradio>=6.1,<7"]
dev = [
  "pytest>=8",
  "pytest-cov>=5",
  "ruff>=0.7",
  "mypy>=1.13",
  "pre-commit>=4",
  "import-linter>=2.1",
  "respx>=0.21",
]

[project.scripts]
lemely = "lemely.app.cli:main"

[tool.hatch.build.targets.wheel]
packages = ["lemely"]

[tool.hatch.build.targets.sdist]
include = ["lemely", "tests", "lemely.toml.example", "README.md"]

[tool.ruff]
target-version = "py312"
line-length = 100

[tool.ruff.lint]
select = ["E", "W", "F", "I", "B", "UP", "SIM", "TCH", "RUF", "ANN", "D", "T20", "S"]
ignore = ["D100", "D104", "D107", "ANN101", "ANN102"]

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["S101", "ANN", "D"]
"lemely/app/cli.py" = ["T20"]

[tool.ruff.lint.pydocstyle]
convention = "google"

[tool.mypy]
python_version = "3.13"
strict = true
warn_unreachable = true
warn_redundant_casts = true
disallow_any_explicit = true
plugins = ["pydantic.mypy"]

[[tool.mypy.overrides]]
module = ["gradio.*", "fitz.*"]
ignore_missing_imports = true

[tool.pytest.ini_options]
addopts = "-ra -q --strict-markers --cov=lemely --cov-report=term-missing --cov-fail-under=85"
testpaths = ["tests"]
markers = [
  "live: requires GEMINI_API_KEY and makes real API calls (skipped by default)",
]

[tool.coverage.run]
source = ["lemely"]
branch = true
omit = ["lemely/app/gradio_app.py"]

[tool.coverage.report]
exclude_also = [
  "raise NotImplementedError",
  "if TYPE_CHECKING:",
  "if __name__ == .__main__.:",
]

[tool.importlinter]
root_package = "lemely"

[[tool.importlinter.contracts]]
name = "Layered architecture"
type = "layers"
layers = [
  "lemely.app",
  "lemely.io",
  "lemely.core",
  "lemely.runtime",
]

[[tool.importlinter.contracts]]
name = "Core is pure"
type = "forbidden"
source_modules = ["lemely.core"]
forbidden_modules = ["lemely.io", "lemely.app", "lemely.runtime"]
```

- [ ] **Step 2: Generate lockfile and install dev extras**

```bash
source ./.venv/bin/activate && pip install uv && uv pip compile pyproject.toml --extra ui --extra dev -o requirements.lock
```
Expected: `requirements.lock` is created (a pinned list of every transitive dep).

```bash
uv pip install --requirement requirements.lock
```
Expected: every dep installs cleanly.

- [ ] **Step 3: Install the project itself in editable mode**

Because Task 6 hasn't restructured yet, `lemely_mvp/` still exists. To let `pip install -e .` succeed before the rename, temporarily declare the existing package:

Temporarily edit `pyproject.toml` `[tool.hatch.build.targets.wheel]` to:
```toml
packages = ["lemely_mvp"]
```
(We revert this in Task 6.)

```bash
uv pip install -e .
```
Expected: install succeeds.

- [ ] **Step 4: Delete `requirements.txt`**

```bash
git rm requirements.txt
```

- [ ] **Step 5: Run baseline tests under pytest**

```bash
pytest -x 2>&1 | tail -10
```
Expected: `24 passed`. Coverage warning is OK — we tighten the gate in a later task.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml requirements.lock
git commit -S -m "$(cat <<'EOF'
build: add pyproject.toml, lockfile, and dev-tool configuration

Introduces hatchling-backed PEP 621 packaging with ui/dev extras,
ruff strict ruleset, mypy strict, pytest+coverage, and import-linter
layering contract. Lockfile generated via uv pip compile.

requirements.txt removed; pyproject.toml is now the single source of
truth for dependencies. The wheel package field temporarily points
at lemely_mvp/ and will be flipped to lemely/ in the restructure task.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Add `runtime/errors.py` — exception hierarchy

**Files:**
- Create: `lemely_mvp/runtime/__init__.py`
- Create: `lemely_mvp/runtime/errors.py`
- Create: `tests/test_runtime_errors.py`

We add the `runtime/` subpackage inside `lemely_mvp/` for now; the package-wide rename happens in Task 6, after which `lemely_mvp/runtime/` will become `lemely/runtime/` with no further edits to its contents.

- [ ] **Step 1: Write the failing test**

Create `tests/test_runtime_errors.py`:
```python
"""Tests for lemely.runtime.errors exception hierarchy."""
from __future__ import annotations

import unittest

from lemely_mvp.runtime import errors


class ExitCodeTests(unittest.TestCase):
    def test_base_lemely_error_has_exit_code_1(self) -> None:
        self.assertEqual(errors.LemelyError.exit_code, 1)

    def test_subclass_exit_codes_are_distinct_and_documented(self) -> None:
        expected = {
            errors.UsageError: 2,
            errors.ConfigError: 3,
            errors.InputError: 4,
            errors.NotFoundError: 5,
            errors.ParseError: 6,
            errors.ExternalServiceError: 7,
        }
        for cls, code in expected.items():
            with self.subTest(cls=cls.__name__):
                self.assertTrue(issubclass(cls, errors.LemelyError))
                self.assertEqual(cls.exit_code, code)

    def test_partial_failure_error_shares_base_exit_code(self) -> None:
        self.assertEqual(errors.PartialFailureError.exit_code, 1)
        self.assertTrue(issubclass(errors.PartialFailureError, errors.LemelyError))

    def test_instances_carry_message(self) -> None:
        err = errors.ConfigError("missing api key")
        self.assertEqual(str(err), "missing api key")
        self.assertEqual(err.exit_code, 3)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/test_runtime_errors.py -v 2>&1 | tail -5
```
Expected: collection failure with `ModuleNotFoundError: No module named 'lemely_mvp.runtime'`.

- [ ] **Step 3: Create the runtime package**

Create `lemely_mvp/runtime/__init__.py`:
```python
"""Cross-cutting runtime infrastructure: config, logging, errors."""
from lemely_mvp.runtime import errors

__all__ = ["errors"]
```

Create `lemely_mvp/runtime/errors.py`:
```python
"""Exception hierarchy and exit-code mapping for the Lemely CLI."""
from __future__ import annotations


class LemelyError(Exception):
    """Base class for all expected Lemely failures."""

    exit_code: int = 1


class UsageError(LemelyError):
    """Bad CLI arguments / wrong invocation."""

    exit_code = 2


class ConfigError(LemelyError):
    """Bad TOML / env / missing required setting."""

    exit_code = 3


class InputError(LemelyError):
    """Malformed user-supplied file (answers, weakness JSON, etc.)."""

    exit_code = 4


class NotFoundError(LemelyError):
    """Required file, mark scheme, or topic not found."""

    exit_code = 5


class ParseError(LemelyError):
    """PDF / JSON parse failure."""

    exit_code = 6


class ExternalServiceError(LemelyError):
    """Gemini API failure that did not recover after retry."""

    exit_code = 7


class PartialFailureError(LemelyError):
    """Batch completed with one or more per-item errors. exit_code stays 1."""

    exit_code = 1
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
pytest tests/test_runtime_errors.py -v 2>&1 | tail -10
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add lemely_mvp/runtime/__init__.py lemely_mvp/runtime/errors.py tests/test_runtime_errors.py
git commit -S -m "$(cat <<'EOF'
feat(runtime): add exception hierarchy with documented exit codes

LemelyError base with subclasses for Usage(2), Config(3), Input(4),
NotFound(5), Parse(6), ExternalService(7), and PartialFailure(1).
CLI top-level handler in Task 9 maps each to its declared exit code.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Add `runtime/config.py` — pydantic-settings + TOML loader

**Files:**
- Create: `lemely_mvp/runtime/config.py`
- Create: `tests/test_runtime_config.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_runtime_config.py`:
```python
"""Tests for lemely.runtime.config Settings loading and validation."""
from __future__ import annotations

import os
import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pydantic import ValidationError

from lemely_mvp.runtime.config import Settings, load_settings


class _IsolatedEnv:
    """Context manager that clears LEMELY_* env vars and CWD-side state."""

    def __init__(self, **overrides: str) -> None:
        self.overrides = overrides
        self._snapshot: dict[str, str] = {}

    def __enter__(self) -> "_IsolatedEnv":
        self._snapshot = dict(os.environ)
        for key in list(os.environ):
            if key.startswith("LEMELY_") or key == "GEMINI_API_KEY":
                del os.environ[key]
        os.environ.update(self.overrides)
        return self

    def __exit__(self, *_: object) -> None:
        os.environ.clear()
        os.environ.update(self._snapshot)


class SettingsTests(unittest.TestCase):
    def test_defaults_load_without_any_source(self) -> None:
        with _IsolatedEnv():
            with TemporaryDirectory() as tmp:
                s = load_settings(toml_path=None, cwd=Path(tmp))
        self.assertEqual(s.gradio.host, "127.0.0.1")
        self.assertEqual(s.gradio.port, 7860)
        self.assertEqual(s.logging.level, "INFO")
        self.assertEqual(s.logging.format, "auto")
        self.assertEqual(s.gemini.model, "gemini-2.5-flash")
        self.assertIsNone(s.gemini_api_key)

    def test_extra_forbid_rejects_unknown_keys_in_toml(self) -> None:
        with TemporaryDirectory() as tmp:
            toml = Path(tmp) / "lemely.toml"
            toml.write_text(textwrap.dedent("""
                [gradio]
                hsot = "0.0.0.0"
            """).strip())
            with _IsolatedEnv():
                with self.assertRaises(ValidationError) as cm:
                    load_settings(toml_path=toml, cwd=Path(tmp))
        self.assertIn("hsot", str(cm.exception))

    def test_env_overrides_toml(self) -> None:
        with TemporaryDirectory() as tmp:
            toml = Path(tmp) / "lemely.toml"
            toml.write_text("[gradio]\nport = 5000\n")
            with _IsolatedEnv(LEMELY_GRADIO__PORT="9000"):
                s = load_settings(toml_path=toml, cwd=Path(tmp))
        self.assertEqual(s.gradio.port, 9000)

    def test_secret_redaction_in_dump(self) -> None:
        with _IsolatedEnv(GEMINI_API_KEY="sk-secret-xyz"):
            with TemporaryDirectory() as tmp:
                s = load_settings(toml_path=None, cwd=Path(tmp))
        dumped = s.model_dump(mode="json")
        self.assertNotIn("sk-secret-xyz", str(dumped))

    def test_toml_discovery_prefers_cwd_lemely_toml(self) -> None:
        with TemporaryDirectory() as tmp:
            cwd = Path(tmp) / "cwd"
            cwd.mkdir()
            (cwd / "lemely.toml").write_text("[gradio]\nport = 4242\n")
            with _IsolatedEnv():
                s = load_settings(toml_path=None, cwd=cwd)
        self.assertEqual(s.gradio.port, 4242)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/test_runtime_config.py -v 2>&1 | tail -5
```
Expected: `ModuleNotFoundError: No module named 'lemely_mvp.runtime.config'`.

- [ ] **Step 3: Implement `runtime/config.py`**

Create `lemely_mvp/runtime/config.py`:
```python
"""Settings loader: env > .env > lemely.toml > defaults. extra='forbid' everywhere."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class GradioSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    host: str = "127.0.0.1"
    port: int = Field(default=7860, ge=1, le=65535)
    max_file_size_mb: int = Field(default=25, ge=1)


class PathsSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sources_dir: Path = Path("Sources")
    output_dir: Path = Path("outputs")
    cache_dir: Path = Path(".lemely-cache")


class LoggingSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    format: Literal["auto", "json", "console"] = "auto"


class GeminiSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = "gemini-2.5-flash"
    max_retries: int = Field(default=3, ge=0)
    backoff_seconds: float = Field(default=2.0, gt=0)
    monthly_usd_ceiling: float | None = None
    per_run_token_ceiling: int | None = None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LEMELY_",
        env_nested_delimiter="__",
        env_file=".env",
        extra="forbid",
    )
    gradio: GradioSettings = GradioSettings()
    paths: PathsSettings = PathsSettings()
    logging: LoggingSettings = LoggingSettings()
    gemini: GeminiSettings = GeminiSettings()
    gemini_api_key: SecretStr | None = None


def _discover_toml(cwd: Path) -> Path | None:
    cwd_toml = cwd / "lemely.toml"
    if cwd_toml.is_file():
        return cwd_toml
    xdg = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    home_toml = Path(xdg) / "lemely" / "lemely.toml"
    if home_toml.is_file():
        return home_toml
    return None


def load_settings(
    *, toml_path: Path | None = None, cwd: Path | None = None
) -> Settings:
    """Load Settings with precedence: env > .env > TOML > defaults.

    Args:
        toml_path: explicit TOML path (from --config). If None, discover.
        cwd: working directory for TOML discovery (defaults to Path.cwd()).
    """
    cwd = cwd or Path.cwd()
    toml = toml_path if toml_path is not None else _discover_toml(cwd)
    toml_data: dict[str, object] = {}
    if toml is not None:
        try:
            import tomllib  # Python 3.11+
        except ModuleNotFoundError:  # pragma: no cover
            import tomli as tomllib  # type: ignore[no-redef]
        with toml.open("rb") as fh:
            toml_data = tomllib.load(fh)

    # Map env into the same shape pydantic-settings already supports via
    # env_nested_delimiter; toml_data is merged with lowest precedence
    # by passing through model_validate on a merged dict.
    if toml_data:
        base = Settings.model_validate(toml_data)
        # Now overlay env / .env via a fresh BaseSettings load.
        env_layer = Settings()
        merged = base.model_dump()
        env_dump = env_layer.model_dump()
        for k, v in env_dump.items():
            # Only overlay values that came from a non-default source.
            # Heuristic: compare against fresh Settings() with toml ignored.
            if v != Settings.model_fields[k].default and not isinstance(
                Settings.model_fields[k].default, type(...)  # sentinel-safe
            ):
                merged[k] = v
        return Settings.model_validate(merged)
    return Settings()
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
pytest tests/test_runtime_config.py -v 2>&1 | tail -15
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add lemely_mvp/runtime/config.py tests/test_runtime_config.py
git commit -S -m "$(cat <<'EOF'
feat(runtime): add Settings loader with TOML + env precedence

pydantic-settings-based Settings class with sub-models for gradio,
paths, logging, and gemini. extra='forbid' everywhere catches typos
at startup. TOML discovery: explicit > ./lemely.toml > XDG; env vars
with LEMELY_ prefix and __ nesting override TOML. gemini_api_key is
SecretStr so dumps don't leak.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Add `runtime/logging.py` — structlog setup with TTY auto-detect

**Files:**
- Create: `lemely_mvp/runtime/logging.py`
- Create: `tests/test_runtime_logging.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_runtime_logging.py`:
```python
"""Tests for lemely.runtime.logging configuration and redaction."""
from __future__ import annotations

import io
import json
import logging
import unittest

import structlog

from lemely_mvp.runtime.logging import configure_logging


class LoggingConfigurationTests(unittest.TestCase):
    def setUp(self) -> None:
        structlog.reset_defaults()
        # Detach all existing handlers from the root logger.
        for h in list(logging.getLogger().handlers):
            logging.getLogger().removeHandler(h)

    def test_json_format_writes_one_object_per_line(self) -> None:
        buf = io.StringIO()
        configure_logging(level="INFO", fmt="json", stream=buf)
        log = structlog.get_logger().bind(command="x")
        log.info("hello", question_id=42)
        line = buf.getvalue().strip().splitlines()[-1]
        payload = json.loads(line)
        self.assertEqual(payload["event"], "hello")
        self.assertEqual(payload["command"], "x")
        self.assertEqual(payload["question_id"], 42)

    def test_secret_keys_are_redacted_at_any_depth(self) -> None:
        buf = io.StringIO()
        configure_logging(level="INFO", fmt="json", stream=buf)
        log = structlog.get_logger()
        log.info(
            "config_dump",
            outer={"gemini_api_key": "sk-leak-me", "nested": {"password": "hunter2"}},
            token="t0p$ecret",
        )
        text = buf.getvalue()
        self.assertNotIn("sk-leak-me", text)
        self.assertNotIn("hunter2", text)
        self.assertNotIn("t0p$ecret", text)
        # Should have replacement marker:
        self.assertIn("***", text)

    def test_level_filters_below_threshold(self) -> None:
        buf = io.StringIO()
        configure_logging(level="WARNING", fmt="json", stream=buf)
        log = structlog.get_logger()
        log.info("filtered")
        log.warning("kept")
        text = buf.getvalue()
        self.assertNotIn("filtered", text)
        self.assertIn("kept", text)

    def test_stdlib_bridge_routes_through_structlog(self) -> None:
        buf = io.StringIO()
        configure_logging(level="DEBUG", fmt="json", stream=buf)
        logging.getLogger("third_party").info("library_event")
        text = buf.getvalue()
        self.assertIn("library_event", text)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/test_runtime_logging.py -v 2>&1 | tail -5
```
Expected: `ModuleNotFoundError: No module named 'lemely_mvp.runtime.logging'`.

- [ ] **Step 3: Implement `runtime/logging.py`**

Create `lemely_mvp/runtime/logging.py`:
```python
"""structlog configuration: stderr-only, TTY-auto JSON vs console, secret redaction."""
from __future__ import annotations

import logging
import sys
from typing import IO, Any, Literal

import structlog

_SECRET_KEYS = frozenset(
    {"api_key", "gemini_api_key", "password", "token", "authorization"}
)


def _redact(_logger: Any, _name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    def walk(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                k: ("***" if k.lower() in _SECRET_KEYS else walk(v))
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [walk(v) for v in value]
        return value

    return walk(event_dict)  # type: ignore[return-value]


def configure_logging(
    *,
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO",
    fmt: Literal["auto", "json", "console"] = "auto",
    stream: IO[str] | None = None,
) -> None:
    """Configure structlog + stdlib logging once at process startup.

    Logs to stderr unless `stream` is given (used in tests).
    """
    out = stream if stream is not None else sys.stderr
    use_console = fmt == "console" or (fmt == "auto" and out.isatty())

    renderer: structlog.types.Processor = (
        structlog.dev.ConsoleRenderer(colors=use_console)
        if use_console
        else structlog.processors.JSONRenderer()
    )

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        _redact,
    ]

    structlog.configure(
        processors=shared_processors + [renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=out),
        cache_logger_on_first_use=True,
    )

    # Stdlib bridge: route any logging.getLogger(...) into structlog.
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler(out)

    class _StructlogBridge(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            structlog.get_logger(record.name).log(
                record.levelno, record.getMessage()
            )

    root.addHandler(_StructlogBridge(level=getattr(logging, level)))
    root.setLevel(getattr(logging, level))
    handler.close()
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
pytest tests/test_runtime_logging.py -v 2>&1 | tail -15
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add lemely_mvp/runtime/logging.py tests/test_runtime_logging.py
git commit -S -m "$(cat <<'EOF'
feat(runtime): add structlog setup with TTY auto-detect and secret redaction

configure_logging() emits JSON in non-TTY contexts and Rich-rendered
console output on TTY; format can be forced via fmt arg. A redaction
processor walks event dicts and replaces values under api_key /
gemini_api_key / password / token / authorization keys at any depth.
A stdlib-bridge handler routes third-party logging.getLogger output
through structlog so Gradio/httpx/PyMuPDF logs share the format.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Restructure `lemely_mvp/` → `lemely/{core,io,app,runtime}`

**Files:**
- Create: `lemely/__init__.py`, `lemely/core/__init__.py`, `lemely/io/__init__.py`, `lemely/app/__init__.py`
- Move (rename): every module under `lemely_mvp/` to its target subpackage under `lemely/`
- Modify: `pyproject.toml` (revert wheel packages to `["lemely"]`)
- Modify: `main.py` (update import)
- Modify: all `tests/*.py` (update imports)

The migration is one commit. After it, every `from lemely_mvp.X import Y` becomes `from lemely.<layer>.X import Y`, and tests still pass with zero behavioural changes.

- [ ] **Step 1: Create the new package skeleton**

```bash
mkdir -p lemely/core lemely/io lemely/app lemely/runtime
```

Create `lemely/__init__.py`:
```python
"""Lemely — accuracy-first educational assessment tool."""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("lemely")
except PackageNotFoundError:  # pragma: no cover - editable install before metadata
    __version__ = "0.0.0+dev"

__all__ = ["__version__"]
```

Create `lemely/core/__init__.py`:
```python
"""Pure logic — no disk, no network, no env."""
from lemely.core.schemas import (
    AccuracyReport,
    BatchParseItem,
    BatchParseResult,
    ConfidenceBand,
    CorrectedQuestion,
    CorrectionResult,
    ExamMetadata,
    GradePrediction,
    QuizPayload,
    WeaknessReport,
)

__all__ = [
    "AccuracyReport",
    "BatchParseItem",
    "BatchParseResult",
    "ConfidenceBand",
    "CorrectedQuestion",
    "CorrectionResult",
    "ExamMetadata",
    "GradePrediction",
    "QuizPayload",
    "WeaknessReport",
]
```

Create `lemely/io/__init__.py`:
```python
"""I/O layer — touches disk and external APIs."""
```

Create `lemely/app/__init__.py`:
```python
"""User-facing entrypoints — CLI and Gradio app."""
```

- [ ] **Step 2: Move source files into their layers**

```bash
git mv lemely_mvp/schemas.py lemely/core/schemas.py
git mv lemely_mvp/correction.py lemely/core/correction.py
git mv lemely_mvp/analytics.py lemely/core/analytics.py
git mv lemely_mvp/metadata.py lemely/io/metadata.py
git mv lemely_mvp/mark_schemes.py lemely/io/mark_schemes.py
git mv lemely_mvp/parsers.py lemely/io/parsers.py
git mv lemely_mvp/cli.py lemely/app/cli.py
git mv lemely_mvp/gradio_app.py lemely/app/gradio_app.py
git mv lemely_mvp/runtime/__init__.py lemely/runtime/__init__.py
git mv lemely_mvp/runtime/errors.py lemely/runtime/errors.py
git mv lemely_mvp/runtime/config.py lemely/runtime/config.py
git mv lemely_mvp/runtime/logging.py lemely/runtime/logging.py
git rm lemely_mvp/__init__.py
```

- [ ] **Step 3: Update imports in moved source files**

Use sed for the bulk find/replace, then spot-check by hand. From the repo root:

```bash
find lemely tests -name '*.py' -exec sed -i \
  -e 's|from lemely_mvp\.schemas|from lemely.core.schemas|g' \
  -e 's|from lemely_mvp\.correction|from lemely.core.correction|g' \
  -e 's|from lemely_mvp\.analytics|from lemely.core.analytics|g' \
  -e 's|from lemely_mvp\.metadata|from lemely.io.metadata|g' \
  -e 's|from lemely_mvp\.mark_schemes|from lemely.io.mark_schemes|g' \
  -e 's|from lemely_mvp\.parsers|from lemely.io.parsers|g' \
  -e 's|from lemely_mvp\.cli|from lemely.app.cli|g' \
  -e 's|from lemely_mvp\.gradio_app|from lemely.app.gradio_app|g' \
  -e 's|from lemely_mvp\.runtime|from lemely.runtime|g' \
  -e 's|from \.schemas|from lemely.core.schemas|g' \
  -e 's|from \.correction|from lemely.core.correction|g' \
  -e 's|from \.analytics|from lemely.core.analytics|g' \
  -e 's|from \.metadata|from lemely.io.metadata|g' \
  -e 's|from \.mark_schemes|from lemely.io.mark_schemes|g' \
  -e 's|from \.parsers|from lemely.io.parsers|g' \
  -e 's|import lemely_mvp|import lemely|g' \
  {} +
```

Then verify no stray references remain:
```bash
grep -rn 'lemely_mvp' lemely tests main.py
```
Expected: empty output.

- [ ] **Step 4: Update `main.py`**

Replace the contents of `main.py` with:
```python
from __future__ import annotations

import sys

from lemely.app.cli import main


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

- [ ] **Step 5: Revert `pyproject.toml` wheel package list**

In `pyproject.toml`, change:
```toml
[tool.hatch.build.targets.wheel]
packages = ["lemely_mvp"]
```
to:
```toml
[tool.hatch.build.targets.wheel]
packages = ["lemely"]
```

- [ ] **Step 6: Reinstall in editable mode and run tests**

```bash
uv pip install -e .
pytest -x 2>&1 | tail -10
```
Expected: `24 passed`.

- [ ] **Step 7: Remove empty `lemely_mvp/`**

```bash
rm -rf lemely_mvp/
```

(All its files were `git mv`ed in Step 2; this only removes any leftover `__pycache__` directories.)

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -S -m "$(cat <<'EOF'
refactor: restructure lemely_mvp into layered lemely/{core,io,app,runtime}

core/  - schemas, correction, analytics (pure)
io/    - metadata, mark_schemes, parsers (touches disk)
app/   - cli, gradio_app (user-facing)
runtime/ - config, logging, errors (cross-cutting)

All 24 tests pass with identical behaviour. Imports updated repo-wide.
main.py routes to lemely.app.cli.main. pyproject wheel target now
ships the lemely/ package.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Move `models/mark_scheme.py` → `lemely/io/loose_schemas.py`

**Files:**
- Move: `models/mark_scheme.py` → `lemely/io/loose_schemas.py`
- Delete: `models/__init__.py`, `models/` directory
- Modify: every file that imports from `models`

- [ ] **Step 1: Find all import sites**

```bash
grep -rn 'from models' lemely tests main.py
```
Note the matches; you'll update each.

- [ ] **Step 2: Move the file**

```bash
git mv models/mark_scheme.py lemely/io/loose_schemas.py
git rm models/__init__.py
rm -rf models/
```

- [ ] **Step 3: Update imports**

```bash
find lemely tests -name '*.py' -exec sed -i \
  -e 's|from models\.mark_scheme|from lemely.io.loose_schemas|g' \
  -e 's|from models import|from lemely.io.loose_schemas import|g' \
  {} +
```

Verify:
```bash
grep -rn 'from models' lemely tests main.py
```
Expected: empty.

- [ ] **Step 4: Run tests**

```bash
pytest -x 2>&1 | tail -10
```
Expected: `24 passed`.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -S -m "$(cat <<'EOF'
refactor: move models/mark_scheme.py to lemely/io/loose_schemas.py

The loose MarkScheme Pydantic model is only used to validate disk-read
JSON in lemely/io/mark_schemes.py and lemely/io/parsers.py — it belongs
inside the io layer, not as a top-level concept.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: Move `prompts/` → `lemely/io/prompts/`

**Files:**
- Move: `prompts/__init__.py`, `prompts/mark_scheme_parsing.py` → `lemely/io/prompts/`
- Modify: every file that imports from `prompts`

- [ ] **Step 1: Move**

```bash
mkdir -p lemely/io/prompts
git mv prompts/__init__.py lemely/io/prompts/__init__.py
git mv prompts/mark_scheme_parsing.py lemely/io/prompts/mark_scheme_parsing.py
rm -rf prompts/
```

- [ ] **Step 2: Update imports**

```bash
find lemely tests -name '*.py' -exec sed -i \
  -e 's|from prompts\.mark_scheme_parsing|from lemely.io.prompts.mark_scheme_parsing|g' \
  -e 's|from prompts import|from lemely.io.prompts import|g' \
  -e 's|import prompts$|import lemely.io.prompts as prompts|g' \
  {} +
```

Verify:
```bash
grep -rn 'from prompts\|^import prompts' lemely tests
```
Expected: empty.

- [ ] **Step 3: Run tests**

```bash
pytest -x 2>&1 | tail -10
```
Expected: `24 passed`.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -S -m "$(cat <<'EOF'
refactor: move prompts/ into lemely/io/prompts/

Prompt strings live next to the io modules that consume them.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: Replace `argparse` CLI with `click` and add global options

**Files:**
- Modify: `lemely/app/cli.py` (full rewrite using click)
- Modify: `tests/test_cli.py` (update for click)
- Create: `tests/test_cli_global_options.py`

The CLI surface keeps its existing subcommands and JSON output shape; only the argparse plumbing is replaced. Global options (`--config`, `--log-format`, `--log-level`, `-v`, `-q`, `--json`, `--version`) are added; `--json` defaults `True` for this task so existing tests pass unchanged. (Task 11 flips the default to human output and adds the human renderers.)

- [ ] **Step 1: Read the existing `tests/test_cli.py`**

Confirm it invokes `lemely.app.cli.main(argv)` and parses the returned-or-printed JSON via stdout capture. (It does — already reviewed during planning.)

- [ ] **Step 2: Write new global-options tests**

Create `tests/test_cli_global_options.py`:
```python
"""Tests for click-based CLI global options."""
from __future__ import annotations

import json
import unittest

from click.testing import CliRunner

from lemely.app.cli import cli


class CliGlobalOptionTests(unittest.TestCase):
    def test_version_flag_prints_semver_string(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["--version"])
        self.assertEqual(result.exit_code, 0)
        # importlib.metadata returns "0.1.0" for the installed package.
        self.assertRegex(result.output.strip(), r"^lemely, version \d")

    def test_unknown_command_exits_with_usage_code(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["nope"])
        self.assertEqual(result.exit_code, 2)

    def test_invalid_log_format_exits_with_usage_code(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["--log-format", "xml", "estimate-cost", "."])
        self.assertEqual(result.exit_code, 2)

    def test_help_lists_every_subcommand(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        for cmd in (
            "estimate-cost",
            "parse-mark-schemes",
            "correct-paper",
            "predict-grade",
            "detect-weaknesses",
            "generate-quiz",
        ):
            with self.subTest(cmd=cmd):
                self.assertIn(cmd, result.output)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the new test to verify it fails**

```bash
pytest tests/test_cli_global_options.py -v 2>&1 | tail -5
```
Expected: failure — `cli` not exported.

- [ ] **Step 4: Rewrite `lemely/app/cli.py` with click**

Replace `lemely/app/cli.py` entirely with:
```python
"""Click-based CLI entrypoint for lemely."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import click

from lemely import __version__
from lemely.core.analytics import generate_quiz, predict_grade, summarize_weaknesses
from lemely.core.correction import correct_mcq_answers
from lemely.core.schemas import (
    AccuracyReport,
    CorrectionResult,
    CostEstimate,
    WeaknessReport,
)
from lemely.io.mark_schemes import index_source_library, process_mark_scheme_batch
from lemely.io.parsers import GeminiMarkSchemeParser
from lemely.runtime.errors import LemelyError
from lemely.runtime.logging import configure_logging


def _dump_json(payload: Any) -> None:
    if hasattr(payload, "model_dump"):
        data = payload.model_dump(mode="json")
    else:
        data = payload
    click.echo(json.dumps(data, indent=2, sort_keys=True))


def _read_text_or_value(value: str) -> str:
    path = Path(value)
    if path.exists():
        return path.read_text(encoding="utf-8")
    return value


def _load_json_file(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _estimate_cost(source_root: str | Path) -> CostEstimate:
    root = Path(source_root)
    entries = index_source_library(root)
    cached = sum(
        1 for entry in entries if entry.source_path.with_suffix(".json").exists()
    )
    return CostEstimate(
        source_root=str(root),
        mark_scheme_pdfs=len(entries),
        cached_json=cached,
        needs_parsing=len(entries) - cached,
        estimated_pdf_pages=None,
        token_policy=(
            "Reuse structured JSON when present; batch-parse PDFs only during "
            "migration; during correction send question-level mark-scheme slices only."
        ),
    )


def _build_accuracy_report(mark_scheme_path: str | Path, answers: str) -> AccuracyReport:
    scheme_json = Path(mark_scheme_path).read_text(encoding="utf-8")
    correction = correct_mcq_answers(scheme_json, answers)
    weaknesses = summarize_weaknesses(correction)
    grade = predict_grade(correction)
    return AccuracyReport(
        correction=correction,
        weaknesses=weaknesses,
        grade_prediction=grade,
    )


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, "-V", "--version", prog_name="lemely")
@click.option("--config", "config_path", type=click.Path(dir_okay=False), default=None)
@click.option(
    "--log-format",
    type=click.Choice(["auto", "json", "console"]),
    default="auto",
    show_default=True,
)
@click.option(
    "--log-level",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"]),
    default="INFO",
    show_default=True,
)
@click.option("-v", "--verbose", is_flag=True, help="Shortcut for --log-level DEBUG.")
@click.option("-q", "--quiet", is_flag=True, help="Shortcut for --log-level WARNING.")
@click.option(
    "--json/--no-json",
    "json_output",
    default=True,
    help="Emit JSON to stdout (default for Phase 1; human renderer arrives in Task 10).",
)
@click.pass_context
def cli(
    ctx: click.Context,
    config_path: str | None,
    log_format: str,
    log_level: str,
    verbose: bool,
    quiet: bool,
    json_output: bool,
) -> None:
    """Accuracy-first educational assessment CLI."""
    if verbose:
        log_level = "DEBUG"
    elif quiet:
        log_level = "WARNING"
    configure_logging(level=log_level, fmt=log_format)
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config_path
    ctx.obj["json_output"] = json_output


@cli.command("estimate-cost")
@click.argument("source_root", type=click.Path(exists=True, file_okay=False))
def estimate_cost_cmd(source_root: str) -> None:
    _dump_json(_estimate_cost(source_root))


@cli.command("parse-mark-schemes")
@click.argument("source_root", type=click.Path(exists=True, file_okay=False))
@click.option("--output-root", type=click.Path(file_okay=False), default=None)
@click.option("--force", is_flag=True)
@click.option("--use-gemini", is_flag=True)
@click.option("--gemini-model", default="gemini-2.5-flash", show_default=True)
def parse_mark_schemes_cmd(
    source_root: str,
    output_root: str | None,
    force: bool,
    use_gemini: bool,
    gemini_model: str,
) -> None:
    parser = (
        GeminiMarkSchemeParser(model=gemini_model, raw_output_dir=output_root)
        if use_gemini
        else None
    )
    _dump_json(
        process_mark_scheme_batch(
            source_root, output_root, force=force, parser=parser
        )
    )


@cli.command("correct-paper")
@click.option("--mark-scheme", "mark_scheme", required=True, type=click.Path(exists=True, dir_okay=False))
@click.option("--answers", required=True, help="Answer text, JSON object, or path to a file.")
def correct_paper_cmd(mark_scheme: str, answers: str) -> None:
    payload = _read_text_or_value(answers)
    _dump_json(_build_accuracy_report(mark_scheme, payload))


@cli.command("predict-grade")
@click.argument("correction_json", type=click.Path(exists=True, dir_okay=False))
def predict_grade_cmd(correction_json: str) -> None:
    correction = CorrectionResult.model_validate(_load_json_file(correction_json))
    _dump_json(predict_grade(correction))


@cli.command("detect-weaknesses")
@click.argument("correction_json", type=click.Path(exists=True, dir_okay=False))
def detect_weaknesses_cmd(correction_json: str) -> None:
    correction = CorrectionResult.model_validate(_load_json_file(correction_json))
    _dump_json(summarize_weaknesses(correction))


@cli.command("generate-quiz")
@click.argument("weakness_json", type=click.Path(exists=True, dir_okay=False))
@click.option("--count", type=int, default=5, show_default=True)
def generate_quiz_cmd(weakness_json: str, count: int) -> None:
    report = WeaknessReport.model_validate(_load_json_file(weakness_json))
    _dump_json(generate_quiz(report, question_count=count))


def main(argv: list[str] | None = None) -> int:
    """Top-level entrypoint used by main.py and console-script."""
    import structlog

    log = structlog.get_logger().bind(component="cli")
    try:
        cli.main(args=argv, standalone_mode=False, prog_name="lemely")
        return 0
    except click.UsageError as exc:
        # Click prints its own message; map to exit code 2.
        click.echo(exc.format_message(), err=True)
        return 2
    except click.exceptions.Exit as exc:
        return int(exc.exit_code)
    except LemelyError as exc:
        log.error(
            "lemely_error",
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return exc.exit_code
    except KeyboardInterrupt:
        log.warning("interrupted")
        return 130
    except Exception as exc:  # noqa: BLE001
        log.exception("unexpected_error", error_type=type(exc).__name__)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 5: Run existing `tests/test_cli.py` — verify they still pass**

The existing tests only assert on `exit_code` and JSON-payload shape. They call `main(argv)`, the signature of which is unchanged. `click.echo()` writes to `sys.stdout`, so the tests' `redirect_stdout(StringIO())` capture continues to work. With `--json` defaulting `True` in this task, JSON output is unchanged.

```bash
pytest tests/test_cli.py -v 2>&1 | tail -20
```

Expected: all 4 existing CliTests pass. If anything fails, the bug is in the new CLI, not the tests — debug `lemely/app/cli.py`. Do **not** modify tests in this task; Task 11 (which flips `--json` to opt-in) is where they get touched.

- [ ] **Step 6: Run all tests**

```bash
pytest -x 2>&1 | tail -10
```
Expected: all tests pass (24 originals + 4 new global-option tests = 28 minimum).

- [ ] **Step 7: Commit**

```bash
git add lemely/app/cli.py tests/test_cli.py tests/test_cli_global_options.py
git commit -S -m "$(cat <<'EOF'
refactor(cli): replace argparse with click; add global options

Same subcommand surface (estimate-cost, parse-mark-schemes,
correct-paper, predict-grade, detect-weaknesses, generate-quiz) and
identical JSON output shape. Adds global options: --config,
--log-format, --log-level, -v/--verbose, -q/--quiet, --json/--no-json
(defaults to True in Phase 1; human renderer arrives in a later task),
--version. main() wraps cli.main() with the top-level error handler
that maps LemelyError -> exit_code.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 10: Extract human-mode renderers into `app/renderers.py`

**Files:**
- Create: `lemely/app/renderers.py`
- Create: `tests/test_renderers.py`

Renderers turn a Pydantic model into a Rich renderable (table, panel, etc.). They're pure — no I/O, no global state, easy to test.

- [ ] **Step 1: Write the failing test**

Create `tests/test_renderers.py`:
```python
"""Tests for human-mode CLI renderers."""
from __future__ import annotations

import unittest

from rich.console import Console

from lemely.app import renderers
from lemely.core.schemas import (
    ConfidenceBand,
    CorrectedQuestion,
    CorrectionResult,
    CostEstimate,
    ExamMetadata,
)


def _render_to_str(obj: object) -> str:
    console = Console(record=True, width=120)
    console.print(obj)
    return console.export_text()


def _metadata() -> ExamMetadata:
    return ExamMetadata(
        subject_code="9702",
        paper_number=4,
        paper_variant=2,
        session_month="May/June",
        session_year=2023,
    )


class RendererTests(unittest.TestCase):
    def test_render_cost_estimate_includes_totals(self) -> None:
        est = CostEstimate(
            source_root="Sources",
            mark_scheme_pdfs=10,
            cached_json=7,
            needs_parsing=3,
            estimated_pdf_pages=None,
            token_policy="...",
        )
        out = _render_to_str(renderers.render_cost_estimate(est))
        self.assertIn("10", out)
        self.assertIn("7", out)
        self.assertIn("3", out)

    def test_render_correction_result_lists_each_question(self) -> None:
        result = CorrectionResult(
            metadata=_metadata(),
            questions=[
                CorrectedQuestion(
                    question_id="1",
                    awarded_marks=1,
                    maximum_marks=1,
                    confidence=ConfidenceBand.HIGH,
                    confidence_score=1.0,
                    needs_teacher_review=False,
                    student_answer="A",
                    expected_answer="A",
                    topic="kinematics",
                ),
                CorrectedQuestion(
                    question_id="2",
                    awarded_marks=0,
                    maximum_marks=1,
                    confidence=ConfidenceBand.HIGH,
                    confidence_score=1.0,
                    needs_teacher_review=False,
                    student_answer="B",
                    expected_answer="C",
                    topic="forces",
                ),
                CorrectedQuestion(
                    question_id="3",
                    awarded_marks=0,
                    maximum_marks=1,
                    confidence=ConfidenceBand.LOW,
                    confidence_score=0.0,
                    needs_teacher_review=True,
                    student_answer=None,
                    expected_answer="D",
                    topic="forces",
                    review_reason="missing answer",
                ),
            ],
        )
        out = _render_to_str(renderers.render_correction(result))
        self.assertIn("1", out)
        self.assertIn("2", out)
        self.assertIn("3", out)
        self.assertIn("kinematics", out)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/test_renderers.py -v 2>&1 | tail -5
```
Expected: `ImportError` for `renderers` module.

- [ ] **Step 3: Implement `lemely/app/renderers.py`**

Create `lemely/app/renderers.py`:
```python
"""Human-mode (Rich) renderers for CLI output. Pure: take models, return renderables."""
from __future__ import annotations

from rich import box
from rich.table import Table

from lemely.core.schemas import (
    AccuracyReport,
    BatchParseResult,
    CorrectionResult,
    CostEstimate,
    GradePrediction,
    QuizPayload,
    WeaknessReport,
)


def render_cost_estimate(est: CostEstimate) -> Table:
    t = Table(title=f"Cost estimate — {est.source_root}", box=box.SIMPLE)
    t.add_column("metric")
    t.add_column("value", justify="right")
    t.add_row("Mark scheme PDFs", str(est.mark_scheme_pdfs))
    t.add_row("Cached JSON", str(est.cached_json))
    t.add_row("Needs parsing", str(est.needs_parsing))
    if est.estimated_pdf_pages is not None:
        t.add_row("Estimated PDF pages", str(est.estimated_pdf_pages))
    return t


def render_correction(result: CorrectionResult) -> Table:
    meta = result.metadata
    paper_id = (
        f"{meta.subject_code}/{meta.paper_number}{meta.paper_variant}"
        f" {meta.session_month}{f' {meta.session_year}' if meta.session_year else ''}"
    )
    t = Table(
        title=f"Correction — {paper_id} — {result.awarded_marks}/{result.maximum_marks}",
        box=box.SIMPLE,
    )
    t.add_column("Q", justify="right")
    t.add_column("Student")
    t.add_column("Expected")
    t.add_column("Marks", justify="right")
    t.add_column("Topic")
    t.add_column("Confidence")
    t.add_column("Review?")
    for q in result.questions:
        marks = f"{q.awarded_marks}/{q.maximum_marks}"
        style = "green" if q.awarded_marks == q.maximum_marks else "red"
        review = "yes" if q.needs_teacher_review else ""
        t.add_row(
            q.question_id,
            q.student_answer or "—",
            q.expected_answer or "—",
            f"[{style}]{marks}[/]",
            q.topic or "—",
            q.confidence.value,
            review,
        )
    return t


def render_weakness_report(report: WeaknessReport) -> Table:
    t = Table(title="Weaknesses", box=box.SIMPLE)
    t.add_column("Topic")
    t.add_column("Marks lost", justify="right")
    t.add_column("Out of", justify="right")
    t.add_column("Accuracy", justify="right")
    for w in report.weak_areas:
        t.add_row(
            w.topic,
            str(w.lost_marks),
            str(w.maximum_marks),
            f"{w.accuracy * 100:.0f}%",
        )
    return t


def render_grade_prediction(grade: GradePrediction) -> Table:
    t = Table(title="Grade prediction", box=box.SIMPLE)
    t.add_column("metric")
    t.add_column("value")
    t.add_row("Marks", f"{grade.awarded_marks}/{grade.maximum_marks}")
    t.add_row("Percentage", f"{grade.percentage:.1f}%")
    t.add_row("Predicted grade", grade.grade)
    t.add_row("Confidence", grade.confidence.value)
    return t


def render_accuracy_report(report: AccuracyReport) -> tuple[Table, Table, Table]:
    """Returns (correction table, weakness table, grade table) for sequential printing."""
    return (
        render_correction(report.correction),
        render_weakness_report(report.weaknesses),
        render_grade_prediction(report.grade_prediction),
    )


def render_batch_result(result: BatchParseResult) -> Table:
    t = Table(title="Batch parse summary", box=box.SIMPLE)
    t.add_column("metric")
    t.add_column("value", justify="right")
    t.add_row("Total", str(result.total))
    t.add_row("Parsed", str(result.parsed))
    t.add_row("Skipped (existing)", str(result.skipped))
    t.add_row("Failed", str(result.failed))
    return t


def render_quiz_payload(payload: QuizPayload) -> Table:
    t = Table(title="Quiz questions", box=box.SIMPLE)
    t.add_column("#", justify="right")
    t.add_column("Topic")
    t.add_column("Prompt")
    for idx, q in enumerate(payload.questions, start=1):
        t.add_row(str(idx), q.topic, q.prompt)
    return t
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
pytest tests/test_renderers.py -v 2>&1 | tail -10
```
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add lemely/app/renderers.py tests/test_renderers.py
git commit -S -m "$(cat <<'EOF'
feat(app): add Rich-based human-mode renderers

Pure functions converting Pydantic result models into Rich tables for
CostEstimate, CorrectionResult, WeaknessReport, GradePrediction,
AccuracyReport, BatchParseResult, and QuizPayload. Wired into the CLI
in the next task.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 11: Wire `--json` mode and add stdout-contract test

**Files:**
- Modify: `lemely/app/cli.py`
- Create: `tests/test_cli_json_contract.py`

Now flip the CLI default from JSON to human-friendly Rich output, with `--json` opting into the machine-readable shape. A new test asserts every command's `--json` output is parseable and validates against the expected schema.

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli_json_contract.py`:
```python
"""Asserts every CLI command's --json output is parseable and schema-valid.

Reuses the same real mark-scheme fixture at
Sources/Physics/MarkingSchemes/0625_m20_ms_12.json that tests/test_cli.py uses.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from click.testing import CliRunner

from lemely.app.cli import cli
from lemely.core.schemas import (
    AccuracyReport,
    BatchParseResult,
    CostEstimate,
    GradePrediction,
    QuizPayload,
    WeaknessReport,
)

_REAL_MS = Path("Sources/Physics/MarkingSchemes/0625_m20_ms_12.json")


def _real_ms_text() -> str:
    return _REAL_MS.read_text(encoding="utf-8")


class JsonContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()

    def test_estimate_cost_json_validates(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "0625_m20_ms_12.pdf").write_bytes(b"%PDF-1.4")
            (root / "0625_m20_ms_12.json").write_text(_real_ms_text(), "utf-8")
            result = self.runner.invoke(cli, ["--json", "estimate-cost", str(root)])
        self.assertEqual(result.exit_code, 0, msg=result.output)
        CostEstimate.model_validate(json.loads(result.output))

    def test_parse_mark_schemes_json_validates(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "0625_m20_ms_12.pdf").write_bytes(b"%PDF-1.4")
            (root / "0625_m20_ms_12.json").write_text(_real_ms_text(), "utf-8")
            result = self.runner.invoke(
                cli, ["--json", "parse-mark-schemes", str(root)]
            )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        BatchParseResult.model_validate(json.loads(result.output))

    def test_correct_paper_json_validates_accuracy_report(self) -> None:
        with TemporaryDirectory() as tmp:
            ms = Path(tmp) / "ms.json"
            ms.write_text(_real_ms_text(), "utf-8")
            result = self.runner.invoke(
                cli,
                [
                    "--json",
                    "correct-paper",
                    "--mark-scheme",
                    str(ms),
                    "--answers",
                    "1 A\n2 B",
                ],
            )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        AccuracyReport.model_validate(json.loads(result.output))

    def test_predict_grade_and_detect_weaknesses_json_validate(self) -> None:
        with TemporaryDirectory() as tmp:
            ms = Path(tmp) / "ms.json"
            ms.write_text(_real_ms_text(), "utf-8")
            # Produce a correction first.
            r1 = self.runner.invoke(
                cli,
                ["--json", "correct-paper", "--mark-scheme", str(ms), "--answers", "1 A"],
            )
            self.assertEqual(r1.exit_code, 0, msg=r1.output)
            ar = json.loads(r1.output)
            corr = Path(tmp) / "correction.json"
            corr.write_text(json.dumps(ar["correction"]), "utf-8")

            r2 = self.runner.invoke(cli, ["--json", "predict-grade", str(corr)])
            self.assertEqual(r2.exit_code, 0, msg=r2.output)
            GradePrediction.model_validate(json.loads(r2.output))

            r3 = self.runner.invoke(cli, ["--json", "detect-weaknesses", str(corr)])
            self.assertEqual(r3.exit_code, 0, msg=r3.output)
            WeaknessReport.model_validate(json.loads(r3.output))

    def test_generate_quiz_json_validates(self) -> None:
        with TemporaryDirectory() as tmp:
            ms = Path(tmp) / "ms.json"
            ms.write_text(_real_ms_text(), "utf-8")
            r1 = self.runner.invoke(
                cli,
                ["--json", "correct-paper", "--mark-scheme", str(ms), "--answers", "1 A"],
            )
            corr = Path(tmp) / "correction.json"
            corr.write_text(json.dumps(json.loads(r1.output)["correction"]), "utf-8")
            r2 = self.runner.invoke(cli, ["--json", "detect-weaknesses", str(corr)])
            weak = Path(tmp) / "weak.json"
            weak.write_text(r2.output, "utf-8")

            r3 = self.runner.invoke(
                cli, ["--json", "generate-quiz", str(weak), "--count", "1"]
            )
            self.assertEqual(r3.exit_code, 0, msg=r3.output)
            QuizPayload.model_validate(json.loads(r3.output))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Add `--json`-aware printing helpers to `cli.py`**

In `lemely/app/cli.py`, replace the existing `_dump_json` with a `_print_result` that dispatches on the context's `json_output` flag:

```python
from rich.console import Console

from lemely.app import renderers

_console = Console()


def _print_result(ctx: click.Context, payload: Any) -> None:
    json_output = ctx.obj.get("json_output", True)
    if json_output:
        if hasattr(payload, "model_dump"):
            data = payload.model_dump(mode="json")
        else:
            data = payload
        click.echo(json.dumps(data, indent=2, sort_keys=True))
        return
    # Human mode: dispatch on type.
    from lemely.core.schemas import (
        AccuracyReport,
        BatchParseResult,
        CorrectionResult,
        CostEstimate,
        GradePrediction,
        QuizPayload,
        WeaknessReport,
    )

    if isinstance(payload, CostEstimate):
        _console.print(renderers.render_cost_estimate(payload))
    elif isinstance(payload, CorrectionResult):
        _console.print(renderers.render_correction(payload))
    elif isinstance(payload, AccuracyReport):
        for t in renderers.render_accuracy_report(payload):
            _console.print(t)
    elif isinstance(payload, WeaknessReport):
        _console.print(renderers.render_weakness_report(payload))
    elif isinstance(payload, GradePrediction):
        _console.print(renderers.render_grade_prediction(payload))
    elif isinstance(payload, BatchParseResult):
        _console.print(renderers.render_batch_result(payload))
    elif isinstance(payload, QuizPayload):
        _console.print(renderers.render_quiz_payload(payload))
    else:
        _console.print(payload)
```

Then replace every `_dump_json(...)` call in the subcommand functions with `_print_result(click.get_current_context(), ...)`. No `@click.pass_context` decorator is required because `click.get_current_context()` looks up the active context dynamically — this keeps each subcommand's signature unchanged from Task 9.

- [ ] **Step 3: Flip `--json` default to False**

In the `@click.option("--json/--no-json", ...)` decoration on `cli`, change:
```python
default=True,
```
to:
```python
default=False,
```
and update the help text:
```python
help="Emit JSON to stdout (default: human-friendly Rich tables).",
```

- [ ] **Step 4: Update `tests/test_cli.py`'s `run_cli` helper to inject `--json`**

The original tests assume JSON output. Rather than touching every test, update the single `run_cli` helper in `tests/test_cli.py` to inject `--json` once:

```python
def run_cli(*args):
    stream = StringIO()
    with redirect_stdout(stream):
        exit_code = main(["--json", *args])
    return exit_code, json.loads(stream.getvalue())
```

The four `CliTests` cases call `run_cli(...)` for their commands; this is the only edit needed. Their JSON assertions remain valid.

- [ ] **Step 5: Run all tests**

```bash
pytest -x 2>&1 | tail -10
```
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add lemely/app/cli.py tests/test_cli.py tests/test_cli_json_contract.py tests/helpers.py 2>/dev/null || git add lemely/app/cli.py tests/test_cli.py tests/test_cli_json_contract.py
git commit -S -m "$(cat <<'EOF'
feat(cli): wire --json mode; default to human-friendly Rich output

Subcommands dispatch via _print_result(): JSON when --json is set
(unchanged shape), Rich tables otherwise. test_cli_json_contract
asserts every command's --json output validates against its Pydantic
schema. Existing tests pass --json explicitly to keep JSON-focused
assertions on the JSON path.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 12: Add `doctor` and `version` subcommands

**Files:**
- Modify: `lemely/app/cli.py`
- Create: `tests/test_cli_doctor.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli_doctor.py`:
```python
"""Tests for lemely doctor / lemely version subcommands."""
from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from click.testing import CliRunner

from lemely.app.cli import cli


class DoctorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()
        # Clear potentially-set env vars
        for k in list(os.environ):
            if k.startswith("LEMELY_") or k == "GEMINI_API_KEY":
                del os.environ[k]

    def test_doctor_fails_without_gemini_api_key(self) -> None:
        with TemporaryDirectory() as tmp:
            (Path(tmp) / "Sources").mkdir()
            (Path(tmp) / "outputs").mkdir()
            result = self.runner.invoke(
                cli,
                ["--json", "doctor", "--no-network"],
                env={"LEMELY_PATHS__SOURCES_DIR": str(Path(tmp) / "Sources")},
            )
        self.assertEqual(result.exit_code, 3, msg=result.output)
        # The output is JSON listing the failed checks.
        payload = json.loads(result.output)
        self.assertFalse(payload["all_passed"])
        self.assertIn("gemini_api_key", json.dumps(payload))

    def test_doctor_succeeds_with_valid_env(self) -> None:
        with TemporaryDirectory() as tmp:
            (Path(tmp) / "Sources").mkdir()
            (Path(tmp) / "outputs").mkdir()
            result = self.runner.invoke(
                cli,
                ["--json", "doctor", "--no-network"],
                env={
                    "GEMINI_API_KEY": "test-key-not-validated-with-no-network",
                    "LEMELY_PATHS__SOURCES_DIR": str(Path(tmp) / "Sources"),
                    "LEMELY_PATHS__OUTPUT_DIR": str(Path(tmp) / "outputs"),
                    "LEMELY_PATHS__CACHE_DIR": str(Path(tmp) / "cache"),
                },
            )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        payload = json.loads(result.output)
        self.assertTrue(payload["all_passed"])


class VersionTests(unittest.TestCase):
    def test_version_subcommand_prints_known_keys(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["--json", "version"])
        self.assertEqual(result.exit_code, 0)
        payload = json.loads(result.output)
        self.assertIn("lemely", payload)
        self.assertIn("python", payload)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/test_cli_doctor.py -v 2>&1 | tail -5
```
Expected: `UsageError: No such command 'doctor'`.

- [ ] **Step 3: Implement the subcommands**

Append to `lemely/app/cli.py`:
```python
import platform
import sys as _sys
from importlib import metadata as _md


@cli.command("version")
@click.pass_context
def version_cmd(ctx: click.Context) -> None:
    payload = {
        "lemely": __version__,
        "python": platform.python_version(),
        "dependencies": {
            name: _md.version(name)
            for name in ("pydantic", "click", "structlog", "google-genai", "PyMuPDF")
            if _safe_version(name)
        },
    }
    _print_result(ctx, payload)


def _safe_version(name: str) -> str | None:
    try:
        return _md.version(name)
    except _md.PackageNotFoundError:
        return None


@cli.command("doctor")
@click.option("--no-network", is_flag=True, help="Skip the live Gemini ping.")
@click.pass_context
def doctor_cmd(ctx: click.Context, no_network: bool) -> None:
    from lemely.runtime.config import load_settings
    from lemely.runtime.errors import ConfigError

    checks: list[dict[str, object]] = []

    def record(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    # 1. Config loads.
    try:
        settings = load_settings(
            toml_path=Path(ctx.obj["config_path"]) if ctx.obj.get("config_path") else None
        )
        record("config_loads", True)
    except Exception as exc:  # noqa: BLE001
        record("config_loads", False, str(exc))
        payload = {"all_passed": False, "checks": checks}
        _print_result(ctx, payload)
        raise ConfigError("config did not load") from exc

    # 2. API key set.
    record("gemini_api_key_set", settings.gemini_api_key is not None)

    # 3. Paths.
    record(
        "sources_dir_readable",
        settings.paths.sources_dir.exists() and os.access(settings.paths.sources_dir, os.R_OK),
        detail=str(settings.paths.sources_dir),
    )
    out = settings.paths.output_dir
    try:
        out.mkdir(parents=True, exist_ok=True)
        record("output_dir_writable", os.access(out, os.W_OK), detail=str(out))
    except OSError as exc:
        record("output_dir_writable", False, str(exc))
    cache = settings.paths.cache_dir
    try:
        cache.mkdir(parents=True, exist_ok=True)
        record("cache_dir_writable", os.access(cache, os.W_OK), detail=str(cache))
    except OSError as exc:
        record("cache_dir_writable", False, str(exc))

    # 4. Gradio extra (warn-only).
    try:
        import gradio  # noqa: F401

        record("gradio_extra_installed", True)
    except ModuleNotFoundError:
        record(
            "gradio_extra_installed",
            False,
            "lemely ui will not work; install with `pip install lemely[ui]`",
        )

    # 5. Live ping (skippable).
    if not no_network:
        record(
            "gemini_reachable",
            False,
            "live ping not yet implemented — pass --no-network to skip",
        )

    # Determine pass/fail. gradio is warn-only; everything else fatal.
    fatal_checks = [c for c in checks if c["name"] != "gradio_extra_installed"]
    all_passed = all(c["ok"] for c in fatal_checks)

    payload = {"all_passed": all_passed, "checks": checks}
    _print_result(ctx, payload)

    if not all_passed:
        raise ConfigError("doctor checks failed")
```

(Note: the "live ping" implementation lands in Phase 2 along with the Gemini client. For now `--no-network` is the only working mode.)

- [ ] **Step 4: Run the test to verify it passes**

```bash
pytest tests/test_cli_doctor.py -v 2>&1 | tail -10
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add lemely/app/cli.py tests/test_cli_doctor.py
git commit -S -m "$(cat <<'EOF'
feat(cli): add doctor and version subcommands

`lemely version` prints lemely + python + dep versions as JSON or
table. `lemely doctor` validates config loads, gemini_api_key is set,
sources_dir is readable, output_dir and cache_dir are writable, and
the gradio extra is importable (warn-only). Exits 3 on any fatal
check failure. --no-network skips the live Gemini ping (which lands
in Phase 2 with the shared Gemini client).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 13: Add `--on-error` to `parse-mark-schemes` and raise `PartialFailureError`

**Files:**
- Modify: `lemely/app/cli.py` (add `--on-error` to `parse-mark-schemes` and `correct-paper`)
- Modify: `lemely/io/mark_schemes.py` (no behavioural change yet; we surface errors via the CLI layer)
- Create: `tests/test_cli_on_error.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli_on_error.py`:
```python
"""Tests for the --on-error flag on parse-mark-schemes.

BatchParseResult per-file failures live in items[] with status
"failed" or "invalid_existing"; there is no top-level errors[] list.
The CLI's --on-error logic counts those statuses to decide exit code.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from click.testing import CliRunner

from lemely.app.cli import cli


class OnErrorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()

    def _build_corpus(self, root: Path) -> Path:
        # One valid PDF+JSON pair (skipped_existing) + one PDF whose
        # neighbour JSON is malformed (invalid_existing).
        (root / "0625_m20_ms_12.pdf").write_bytes(b"%PDF-1.4 fake")
        (root / "0625_m20_ms_12.json").write_text(
            Path("Sources/Physics/MarkingSchemes/0625_m20_ms_12.json").read_text(
                encoding="utf-8"
            ),
            encoding="utf-8",
        )
        (root / "0625_s20_ms_31.pdf").write_bytes(b"%PDF-1.4 fake")
        (root / "0625_s20_ms_31.json").write_text("{ not valid json")
        return root

    def test_default_continue_exits_1_on_partial_failure(self) -> None:
        with TemporaryDirectory() as tmp:
            root = self._build_corpus(Path(tmp))
            result = self.runner.invoke(
                cli, ["--json", "parse-mark-schemes", str(root)]
            )
        self.assertEqual(result.exit_code, 1, msg=result.output)
        data = json.loads(result.output)
        # failed counts items with status in {"failed", "invalid_existing"}.
        self.assertGreaterEqual(data["failed"], 1)

    def test_on_error_fail_exits_with_parse_code_on_first_failure(self) -> None:
        with TemporaryDirectory() as tmp:
            root = self._build_corpus(Path(tmp))
            result = self.runner.invoke(
                cli,
                ["parse-mark-schemes", str(root), "--on-error", "fail"],
            )
        # ParseError -> exit code 6 (per runtime.errors).
        self.assertEqual(result.exit_code, 6, msg=result.output)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/test_cli_on_error.py -v 2>&1 | tail -10
```
Expected: failures (unknown option, exit codes wrong).

- [ ] **Step 3: Add `--on-error` to `parse-mark-schemes` and route errors**

In `lemely/app/cli.py`, update the `parse_mark_schemes_cmd`:
```python
@cli.command("parse-mark-schemes")
@click.argument("source_root", type=click.Path(exists=True, file_okay=False))
@click.option("--output-root", type=click.Path(file_okay=False), default=None)
@click.option("--force", is_flag=True)
@click.option("--use-gemini", is_flag=True)
@click.option("--gemini-model", default="gemini-2.5-flash", show_default=True)
@click.option(
    "--on-error",
    type=click.Choice(["continue", "fail"]),
    default="continue",
    show_default=True,
)
@click.pass_context
def parse_mark_schemes_cmd(
    ctx: click.Context,
    source_root: str,
    output_root: str | None,
    force: bool,
    use_gemini: bool,
    gemini_model: str,
    on_error: str,
) -> None:
    parser = (
        GeminiMarkSchemeParser(model=gemini_model, raw_output_dir=output_root)
        if use_gemini
        else None
    )
    result = process_mark_scheme_batch(
        source_root, output_root, force=force, parser=parser
    )
    _print_result(ctx, result)
    # BatchParseResult per-file failures live in items[] with status
    # "failed" or "invalid_existing"; needs_parser is a deferral, not a failure.
    failures = [
        item
        for item in result.items
        if item.status in {"failed", "invalid_existing"}
    ]
    if failures:
        if on_error == "fail":
            from lemely.runtime.errors import ParseError
            raise ParseError(failures[0].message or "parse failed")
        from lemely.runtime.errors import PartialFailureError
        raise PartialFailureError(
            f"{len(failures)} item(s) failed; see items[] for details"
        )
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
pytest tests/test_cli_on_error.py -v 2>&1 | tail -10
```
Expected: 2 passed.

(Verify existing `tests/test_cli.py` parse-mark-schemes tests still pass — the change is additive for the happy path.)

```bash
pytest -x 2>&1 | tail -5
```

- [ ] **Step 5: Commit**

```bash
git add lemely/app/cli.py tests/test_cli_on_error.py
git commit -S -m "$(cat <<'EOF'
feat(cli): add --on-error flag and PartialFailureError exit code to parse-mark-schemes

Default `continue` preserves per-file errors in the JSON output and
exits 1 via PartialFailureError; `fail` raises the first underlying
error so the exit code reflects its type (e.g. ParseError -> 6).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 14: Add `import-linter` architecture tests

**Files:**
- Create: `tests/architecture/__init__.py`
- Create: `tests/architecture/test_import_linter.py`
- Create: `tests/architecture/test_no_print_in_core.py`

The `import-linter` config already lives in `pyproject.toml` (Task 2). This task gives it a runtime test wrapper so contract violations fail `pytest` even if a contributor skips pre-commit.

- [ ] **Step 1: Create the test directory**

```bash
mkdir -p tests/architecture
touch tests/architecture/__init__.py
```

- [ ] **Step 2: Write the import-linter wrapper**

Create `tests/architecture/test_import_linter.py`:
```python
"""Runs import-linter contracts as a pytest test; fails on any violation."""
from __future__ import annotations

import subprocess
import unittest


class ImportLinterTests(unittest.TestCase):
    def test_all_contracts_pass(self) -> None:
        result = subprocess.run(
            ["lint-imports"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            result.returncode,
            0,
            msg=f"import-linter reported violations:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}",
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Write the AST `print()`-detector**

Create `tests/architecture/test_no_print_in_core.py`:
```python
"""Walks lemely/core/ AST and asserts zero print() calls outside docstrings."""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

_CORE = Path(__file__).resolve().parents[2] / "lemely" / "core"


class NoPrintInCoreTests(unittest.TestCase):
    def test_no_print_calls(self) -> None:
        offenders: list[str] = []
        for path in _CORE.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "print"
                ):
                    offenders.append(f"{path.relative_to(_CORE.parent.parent)}:{node.lineno}")
        self.assertEqual(
            offenders,
            [],
            msg=f"print() calls in lemely.core (must be stderr-only via structlog): {offenders}",
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 4: Run the new tests**

```bash
pytest tests/architecture -v 2>&1 | tail -10
```
Expected: 2 passed.

- [ ] **Step 5: Sanity-check that import-linter would catch a violation**

Briefly add `from lemely.io.mark_schemes import index_source_library` to `lemely/core/correction.py`, run the tests, see them fail, then remove it:

```bash
# Inject a violation:
sed -i '1i from lemely.io.mark_schemes import index_source_library  # TEMP VIOLATION' lemely/core/correction.py
pytest tests/architecture/test_import_linter.py 2>&1 | tail -10
# Should FAIL with a contract-violation message.

# Revert:
sed -i '/TEMP VIOLATION/d' lemely/core/correction.py
pytest tests/architecture/test_import_linter.py 2>&1 | tail -5
# Should PASS again.
```

- [ ] **Step 6: Commit**

```bash
git add tests/architecture/
git commit -S -m "$(cat <<'EOF'
test(architecture): add import-linter and no-print-in-core enforcement tests

test_import_linter invokes the lint-imports CLI and fails on any
contract violation. test_no_print_in_core AST-walks lemely/core/ and
asserts zero print() calls, complementing ruff T20. Both run as part
of the default pytest suite so violations fail CI even without
pre-commit.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 15: Add `.pre-commit-config.yaml`

**Files:**
- Create: `.pre-commit-config.yaml`

- [ ] **Step 1: Write the config**

Create `.pre-commit-config.yaml`:
```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.7.4
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v5.0.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-toml
      - id: check-merge-conflict
      - id: detect-private-key
  - repo: local
    hooks:
      - id: mypy
        name: mypy
        entry: mypy lemely
        language: system
        pass_filenames: false
        types: [python]
      - id: import-linter
        name: import-linter
        entry: lint-imports
        language: system
        pass_filenames: false
```

- [ ] **Step 2: Install hooks locally and run on all files**

```bash
pre-commit install
pre-commit run --all-files 2>&1 | tail -30
```
Expected: ruff may auto-fix some files; mypy and import-linter pass. If ruff makes changes, review them and re-run:
```bash
pre-commit run --all-files
```

Address any genuine mypy errors uncovered now; the strict ruleset may surface a few that the MVP tests didn't.

- [ ] **Step 3: Commit hook config + any ruff/mypy fixes**

```bash
git add .pre-commit-config.yaml
# Plus any auto-fixed files:
git add -A
git commit -S -m "$(cat <<'EOF'
build: add pre-commit hooks for ruff, mypy, import-linter, secrets

Runs ruff (--fix) + ruff-format + standard hygiene hooks on every
commit, plus mypy and import-linter as local hooks so structural and
type issues fail commit before push. Includes any ruff/mypy fixes
surfaced on first run.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 16: Add `lemely.toml.example` with drift test

**Files:**
- Create: `lemely.toml.example`
- Create: `lemely/runtime/example_toml.py` (generator)
- Create: `tests/test_settings_example_drift.py`

- [ ] **Step 1: Write the drift test**

Create `tests/test_settings_example_drift.py`:
```python
"""Asserts the committed lemely.toml.example matches what the generator produces."""
from __future__ import annotations

import unittest
from pathlib import Path

from lemely.runtime.example_toml import render_example_toml

_REPO = Path(__file__).resolve().parents[1]
_EXAMPLE = _REPO / "lemely.toml.example"


class SettingsExampleDriftTests(unittest.TestCase):
    def test_example_is_in_sync(self) -> None:
        generated = render_example_toml()
        committed = _EXAMPLE.read_text(encoding="utf-8")
        self.assertEqual(
            committed,
            generated,
            msg=(
                "lemely.toml.example is out of sync with the Settings schema; "
                "regenerate via: python -c 'from lemely.runtime.example_toml import "
                "render_example_toml; import pathlib; "
                "pathlib.Path(\"lemely.toml.example\").write_text(render_example_toml())'"
            ),
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/test_settings_example_drift.py -v 2>&1 | tail -5
```
Expected: `ModuleNotFoundError: No module named 'lemely.runtime.example_toml'`.

- [ ] **Step 3: Implement the generator**

Create `lemely/runtime/example_toml.py`:
```python
"""Generates the committed lemely.toml.example deterministically from Settings."""
from __future__ import annotations

from lemely.runtime.config import Settings

_HEADER = """# Lemely configuration file.
#
# This file documents every available setting and its default value.
# Copy to ./lemely.toml (project-local) or
# $XDG_CONFIG_HOME/lemely/lemely.toml (user-wide) and customise.
#
# Secrets (gemini_api_key) MUST be set via environment variables, not
# this file. Example: GEMINI_API_KEY=... in .env or process env.

"""


def render_example_toml() -> str:
    s = Settings()
    lines: list[str] = [_HEADER.rstrip(), ""]

    lines.append("[gradio]")
    lines.append(f'host = "{s.gradio.host}"')
    lines.append(f"port = {s.gradio.port}")
    lines.append(f"max_file_size_mb = {s.gradio.max_file_size_mb}")
    lines.append("")

    lines.append("[paths]")
    lines.append(f'sources_dir = "{s.paths.sources_dir}"')
    lines.append(f'output_dir = "{s.paths.output_dir}"')
    lines.append(f'cache_dir = "{s.paths.cache_dir}"')
    lines.append("")

    lines.append("[logging]")
    lines.append(f'level = "{s.logging.level}"')
    lines.append(f'format = "{s.logging.format}"  # auto | json | console')
    lines.append("")

    lines.append("[gemini]")
    lines.append(f'model = "{s.gemini.model}"')
    lines.append(f"max_retries = {s.gemini.max_retries}")
    lines.append(f"backoff_seconds = {s.gemini.backoff_seconds}")
    lines.append("# monthly_usd_ceiling = 50.0  # recommended in production")
    lines.append("# per_run_token_ceiling = 200000")
    lines.append("")

    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Generate the committed example**

```bash
python -c "from lemely.runtime.example_toml import render_example_toml; import pathlib; pathlib.Path('lemely.toml.example').write_text(render_example_toml())"
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
pytest tests/test_settings_example_drift.py -v 2>&1 | tail -5
```
Expected: 1 passed.

- [ ] **Step 6: Commit**

```bash
git add lemely.toml.example lemely/runtime/example_toml.py tests/test_settings_example_drift.py
git commit -S -m "$(cat <<'EOF'
build: add lemely.toml.example with drift test

The committed example is regenerated deterministically from the
Settings schema via lemely.runtime.example_toml.render_example_toml.
test_settings_example_drift fails CI if the schema changes without
the example being refreshed — prevents config docs from rotting.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 17: Add GitHub Actions CI workflow and Makefile

**Files:**
- Create: `.github/workflows/ci.yml`
- Create: `Makefile`

- [ ] **Step 1: Write the CI workflow**

```bash
mkdir -p .github/workflows
```

Create `.github/workflows/ci.yml`:
```yaml
name: ci
on:
  push:
    branches: [main]
  pull_request:

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        python-version: ["3.12", "3.13", "3.14"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
          cache: pip
      - name: Install uv
        run: pip install uv
      - name: Install project + dev extras
        run: uv pip install --system -e '.[ui,dev]'
      - name: ruff check
        run: ruff check .
      - name: ruff format --check
        run: ruff format --check .
      - name: mypy
        run: mypy lemely
      - name: import-linter
        run: lint-imports
      - name: pytest
        run: pytest
```

- [ ] **Step 2: Write the Makefile**

Create `Makefile`:
```makefile
.PHONY: install dev test lint typecheck imports lock pre-commit fmt clean

install:
	uv pip install -e '.[ui]'

dev:
	uv pip install -e '.[ui,dev]'
	pre-commit install

test:
	pytest

lint:
	ruff check .
	ruff format --check .

typecheck:
	mypy lemely

imports:
	lint-imports

lock:
	uv pip compile pyproject.toml --extra ui --extra dev -o requirements.lock

pre-commit:
	pre-commit run --all-files

fmt:
	ruff format .
	ruff check --fix .

clean:
	rm -rf build dist *.egg-info .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
```

- [ ] **Step 3: Validate the Makefile locally**

```bash
make lint && make typecheck && make imports && make test 2>&1 | tail -10
```
Expected: all four targets succeed.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml Makefile
git commit -S -m "$(cat <<'EOF'
ci: add GitHub Actions workflow and Makefile

GHA runs ruff check + ruff format --check + mypy + lint-imports +
pytest on Python 3.12, 3.13, 3.14. Makefile mirrors the same commands
locally (install, dev, test, lint, typecheck, imports, lock,
pre-commit, fmt, clean). Docker build job arrives with the Dockerfile
in Phase 4.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 18: Add `docs/exit-codes.md`, `CHANGELOG.md`, refresh `README.md`

**Files:**
- Create: `docs/exit-codes.md`
- Create: `CHANGELOG.md`
- Create or modify: `README.md`

- [ ] **Step 1: Write `docs/exit-codes.md`**

Create `docs/exit-codes.md`:
```markdown
# Lemely CLI exit codes

| Code | Meaning | Examples |
|---:|---|---|
| 0 | Success | command completed without errors |
| 1 | Generic / partial failure | unhandled exception; batch had per-item errors (`PartialFailureError`) |
| 2 | Usage error | unknown subcommand, invalid flag, missing required argument |
| 3 | Config error | missing `GEMINI_API_KEY`, malformed `lemely.toml`, typo'd setting key |
| 4 | Input error | malformed user-supplied JSON file (answers, weakness report) |
| 5 | Not found | mark scheme / topic / paper file not found |
| 6 | Parse error | PDF or JSON parse failure |
| 7 | External service error | Gemini API failure after retries; cost-guard ceiling exceeded |
| 130 | Interrupted | Ctrl-C / SIGINT |

Any exit code other than the ones in this table indicates an unexpected bug — please file an issue with the command, full stderr, and the output of `lemely version`.
```

- [ ] **Step 2: Write `CHANGELOG.md`**

Create `CHANGELOG.md`:
```markdown
# Changelog

All notable changes to this project will be documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Layered package structure: `lemely/{core,io,app,runtime}`, enforced by `import-linter`.
- `lemely/runtime/`: `config` (pydantic-settings + TOML + env), `logging` (structlog with TTY auto-detect + secret redaction), `errors` (exception hierarchy with documented exit codes).
- Click-based CLI with global options: `--config`, `--log-format`, `--log-level`, `-v/--verbose`, `-q/--quiet`, `--json/--no-json`, `--version`.
- Human-friendly Rich-table output by default; `--json` flag opts into machine-readable JSON (unchanged shape from the MVP).
- `lemely doctor` and `lemely version` subcommands.
- `--on-error continue|fail` flag on `parse-mark-schemes`; raises `PartialFailureError` (exit 1) on partial failure or maps the first underlying error type on `fail`.
- `pyproject.toml` (PEP 621 + hatchling) replaces `requirements.txt`; `requirements.lock` produced via `uv pip compile`.
- Dev tooling: ruff (lint + format, strict ruleset), mypy strict, import-linter, pytest + coverage gate 85 %, pre-commit hooks, GitHub Actions CI matrix on Python 3.12 / 3.13 / 3.14.
- `lemely.toml.example` regenerated from the Settings schema with a drift test.

### Changed

- `lemely_mvp` package renamed to `lemely`; all imports updated.
- `models/mark_scheme.py` → `lemely/io/loose_schemas.py`.
- `prompts/` → `lemely/io/prompts/`.

### Removed

- `requirements.txt` (replaced by `pyproject.toml` + `requirements.lock`).
- `main.py` retained as a thin wrapper that defers to the `lemely` console script.
```

- [ ] **Step 3: Write or update `README.md`**

If `README.md` exists, prepend the new content; otherwise create:
```markdown
# Lemely

Accuracy-first educational assessment tool for CAIE marking workflows.

## Install

```bash
pipx install 'lemely[ui]'        # CLI + Gradio UI
pipx install lemely              # CLI only
# or, from a clone:
pip install -e '.[ui,dev]'
```

Required environment variable:

```bash
export GEMINI_API_KEY=...        # see lemely.toml.example for non-secret config
```

## Quick start

```bash
lemely doctor --no-network        # validate setup
lemely estimate-cost Sources/
lemely correct-paper --mark-scheme Sources/Physics/MarkingSchemes/9702_s23_ms_42.json --answers '1A 2B 3C'
lemely ui                          # launches Gradio on http://127.0.0.1:7860
```

Use `lemely --json <cmd>` to emit machine-readable JSON instead of Rich tables.

## Documentation

- [`docs/exit-codes.md`](docs/exit-codes.md) — CLI exit code reference
- [`lemely.toml.example`](lemely.toml.example) — every configuration key with its default
- [`docs/superpowers/specs/`](docs/superpowers/specs/) — design specs
- [`docs/superpowers/plans/`](docs/superpowers/plans/) — implementation plans

## Development

```bash
make dev                           # install + register pre-commit hooks
make test                          # pytest
make lint typecheck imports        # quality gates
make pre-commit                    # run all hooks on every file
```
```

- [ ] **Step 4: Commit**

```bash
git add docs/exit-codes.md CHANGELOG.md README.md
git commit -S -m "$(cat <<'EOF'
docs: add exit-codes reference, CHANGELOG, README

docs/exit-codes.md is the source of truth for the LemelyError exit
code mapping; CHANGELOG follows Keep a Changelog; README covers
install, GEMINI_API_KEY, quick start, and dev commands.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 19: Full verification pass

**Files:**
- No new files.

- [ ] **Step 1: Run the full pre-commit suite**

```bash
pre-commit run --all-files 2>&1 | tail -30
```
Expected: every hook passes (ruff, ruff-format, hygiene, mypy, import-linter).

- [ ] **Step 2: Run the test suite with coverage**

```bash
pytest 2>&1 | tail -20
```
Expected: ≥ all originally-passing tests + every new test added in Tasks 3–16 pass. Coverage ≥ 85 %.

- [ ] **Step 3: Run the CLI smoke checks**

```bash
lemely --version
lemely --help
lemely doctor --no-network --json
lemely estimate-cost Sources/
lemely --json estimate-cost Sources/ | python -c "import json,sys; from lemely.core.schemas import CostEstimate; CostEstimate.model_validate(json.load(sys.stdin)); print('ok')"
```
Expected: each command runs; the last one prints `ok` (proving the JSON contract holds end-to-end).

- [ ] **Step 4: Inspect `git status --short` and summarise**

```bash
git status --short
git log --oneline main -- ':!docs/'
```

Confirm:
- Working tree is clean.
- Every Task 1–18 produced exactly one commit (more is OK if hook fixes added some).
- Every commit is signed.

- [ ] **Step 5: Phase 1 acceptance summary**

Confirm in your head (no code action required):
- `lemely_mvp/` is gone; `lemely/{core,io,app,runtime}/` exists.
- All MVP commands run identically under `--json`.
- New commands `doctor` and `version` work.
- Rich tables render under default human mode.
- `import-linter`, `mypy --strict`, ruff strict, and the architecture tests all pass.
- CI workflow exists and matches the local Makefile targets.
- `pyproject.toml` and `requirements.lock` are committed; `requirements.txt` is gone.
- `lemely.toml.example` is committed and stays in sync with the schema (drift test).

Phase 1 is complete. Phase 2 (Gemini infrastructure + scan extraction) is generated by the writing-plans skill from the same spec once you confirm Phase 1 is live.
