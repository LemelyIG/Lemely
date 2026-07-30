# Decisions log
(orchestrator records every non-trivial decision here: what, why, alternatives)

## Phase 0

### D0.1 — Single lockfile: keep `uv.lock`, delete `requirements.lock`
- **What:** Standardise on `uv.lock` (uv's native universal lockfile) as the one
  dependency lock. Deleted `requirements.lock`. `Makefile` `lock` target changed
  from `pip freeze --exclude-editable > requirements.lock` to `uv lock`.
- **Why:** The two lockfiles drifted (audit §1): `requirements.lock` was compiled
  via `uv pip compile ... --extra ui --extra dev` (missing the `web` extra) while
  the Makefile regenerated it via `pip freeze` — a different mechanism. `uv` is
  installed (0.11.29) and `uv.lock` already resolves all extras (ui+web+dev).
  CI installs from `pyproject.toml` (not a lockfile), so removing the pip-format
  lock costs nothing operationally while killing the drift.
- **Alternatives:** Keep only `requirements.lock` (rejected: pip-freeze output is
  environment-specific and lossy); keep both (rejected: guaranteed drift).

### D0.2 — GEMINI_API_KEY env-mapping trap fix (validation_alias + populate_by_name)
- **What:** `Settings.gemini_api_key` now uses
  `validation_alias=AliasChoices("LEMELY_GEMINI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY")`
  and the model enables `populate_by_name=True`.
- **Why:** Audit blocker #11: an unprefixed `GEMINI_API_KEY` authenticated the
  CLI/Gradio (google-genai SDK env fallback) but left the web portal degraded/503
  because web AI gates read `settings.gemini_api_key`, which only
  `LEMELY_GEMINI_API_KEY` populated. Now one env var works everywhere.
  `populate_by_name=True` is required so `Settings.model_validate(model_dump())`
  round-trips (test fixtures rebuild Settings from a dump) don't reject the
  field-name key under `extra="forbid"`.
- **Alternatives:** Custom env source override (rejected: more code, less idiomatic);
  reading the SDK vars manually in each gate (rejected: scattered, error-prone).

### D0.3 — Test hermeticity against a developer's repo `.env`
- **What:** Added `tests/conftest.py` (session autouse) that disables `.env` file
  discovery in `Settings.model_config` for the test session; hardened
  `_IsolatedEnv` in `test_runtime_config.py` to also clear the unprefixed keys and
  chdir into a temp dir.
- **Why:** `Settings(env_file=".env")` reads a repo-root `.env` at every
  instantiation. A developer keeping a real `.env` (with a Gemini key) for local
  runs flipped 3 "without key" assertions (doctor, config defaults, web plan 503).
  CI has no `.env` and always passed; this makes the suite green everywhere so the
  unattended `pytest` gate is trustworthy. No `os.environ` mutation, no assertion
  weakened — only the stray file source is neutralised.

### D0.4 — CI now installs the `web` extra and adds a `web` job
- **What:** Test job installs `.[dev,ui,web]` (was `.[dev,ui]`); new `web` CI job
  runs `npm ci`, `typecheck`, `oxlint`, `build` for the SPA.
- **Why:** The FastAPI tests import `fastapi` (web extra) — CI omitting it was a
  latent failure once CI got past the (previously red) ruff-format step. Audit §9
  flagged the SPA has zero CI coverage.
