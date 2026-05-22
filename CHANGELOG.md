# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Layered package layout `lemely/{core,io,app,runtime}` enforced by import-linter.
- `lemely/runtime/config.py`: pydantic-settings loader with precedence
  env > `.env` > TOML > defaults; `extra='forbid'` on every section.
- `lemely/runtime/logging.py`: structlog with TTY auto-detect, JSON-in-CI,
  secret-redaction processor for `*_api_key` / `*_token` keys.
- `lemely/runtime/errors.py`: typed exception hierarchy with documented exit codes
  (see `docs/exit-codes.md`).
- Click-based CLI (`lemely.app.cli`) replacing the legacy argparse entrypoint,
  with global `--json`, `--config`, `--log-level`, `--log-format`, `-v/-q`.
- New subcommands: `doctor` (config + env + path readiness) and `version`.
- `parse-mark-schemes --on-error continue|fail` and a dedicated
  `PartialFailureError` exit code path.
- Rich-based renderers for human-mode CLI output; JSON mode unchanged for scripts.
- `lemely.toml.example` plus a generator (`lemely/runtime/example_toml.py`) and
  drift test that fails CI when the example falls behind the schema.
- Pre-commit hooks (ruff, ruff-format, mypy, import-linter, basic hygiene,
  detect-private-key).
- GitHub Actions CI matrix (Python 3.12 / 3.13 / 3.14) plus pre-commit job.
- `Makefile` mirroring CI targets (`make dev test lint typecheck imports fmt`).
- Architecture tests: import-linter contract runner and `no-print-in-core`.

### Changed

- `BatchParseResult` now exposes `total`, `parsed`, `skipped`, `failed` as
  Pydantic computed fields instead of ad-hoc attributes.
- CLI error messages routed through `LemelyError.exit_code` so shell scripts and
  CI can branch on a stable contract.

### Removed

- Legacy `lemely_mvp/` package (migrated to `lemely/`).
