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

### D0.5 — DET parser: wire the modular `lemely/io/det/`, delete the monolith `parsers_det.py`
- **What:** Adopt the staged modular package `lemely/io/det/` as the one
  `DeterministicMarkSchemeParser`; delete `lemely/io/parsers_det.py`; rewire the
  3 call sites (cli, gradio, teacher router) and rewrite the parser test suite to
  target the modular package. Both expose the same
  `DeterministicMarkSchemeParser.__call__(pdf_path) -> MarkScheme`; the modular one
  additionally takes `cfg: DetParserSettings | None`.
- **Why (evidence, not assumption):** Ran BOTH parsers head-to-head on the 4 real
  Physics mark-scheme PDFs in `Sources/`:
  - MCQ (`0625_m20_ms_12`) and alternative-practical (`0625_m21_ms_62`): identical,
    correct output — leaf-mark total == `maximum_mark` (40 == 40) for both parsers.
  - Theory (`0625_s19_ms_43`, `0625_s20_ms_31`): the **monolith silently returns
    wrong totals** (88 and 76 vs the stated 80) with no error — audit blocker #10,
    the exact "silent mis-parse" that poisons marking accuracy. The **modular parser
    runs its Stage-4 reconciler**, detects the mismatch, and raises `ParseError` so
    `ChainedMarkSchemeParser` routes the paper to Gemini instead of persisting
    garbage. It also honors `DetParserSettings` (the monolith ignores it entirely).
  - The modular package is already `mypy --strict` clean.
- **Consequence (recorded honestly):** With the modular parser, theory papers can
  no longer be "deterministically parsed" into a (wrong) scheme — they escalate to
  Gemini via the chain. On the raw no-Gemini path (`parse-mark-schemes` without
  `--use-gemini`) a theory paper now raises `ParseError` (fail-loud) instead of
  writing a silently-wrong JSON. For an accuracy-first product this is the correct
  trade: MCQ/practical stay fully deterministic; complex theory uses Gemini (the
  intended chain design) rather than emitting numbers that don't sum to the max.
- **Alternatives:** Keep the monolith and bolt reconciliation onto it (rejected:
  duplicates work the modular package already does cleanly, and the monolith still
  ignores `DetParserSettings`); keep both (rejected: MISSION requires picking one).

### D0.6 — Gemini cost cap: persistent file-backed USD ledger, $8 hard ceiling
- **What:** New `lemely/io/cost_ledger.py` (`CostLedger`) persists cumulative USD to
  `{output_dir}/gemini_spend.json` (atomic write, survives process restarts).
  Renamed `GeminiSettings.monthly_usd_ceiling` → `total_usd_ceiling` (default now
  **8.0**, active); added `usd_warning_thresholds=[4.0, 6.0]`. `GeminiClient` checks
  the ledger total before/after calls and publishes `BUDGET_WARNING`/`BUDGET_EXCEEDED`
  bus events on threshold crossings (each fires once, tracked in the ledger).
  `lemely/runtime/notify.py` (`post_ntfy`, stdlib urllib, no-op unless
  `LEMELY_NTFY_TOPIC` set) + `budget_notify.register_budget_ntfy()` (idempotent)
  deliver those events to ntfy, registered from the CLI and web entrypoints.
- **Why:** Audit blocker #5 — `monthly_usd_ceiling` reset every process, so there was
  no real cross-run cap. Verified fix with two separate OS processes sharing one
  ledger file: proc2 reads proc1's spend; $4/$6 warnings fire exactly once across
  the boundary. `lemely.runtime` stays free of domain imports (notify uses only
  stdlib) so the import-linter contract holds.
- **Test hermeticity:** `tests/conftest.py` now also neutralises ambient `lemely.toml`
  discovery (repo-root + ~/.config/lemely), needed because the rename would make a
  developer's local `monthly_usd_ceiling` key an `extra=forbid` error. Explicit
  `toml_path`/temp-cwd discovery still works.
