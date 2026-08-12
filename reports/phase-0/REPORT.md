# Phase 0 — Foundation Repair — Milestone Report

**Status:** ✅ Complete — all acceptance criteria and quality gates pass.
**Branch:** `feature/phase-0-foundation-repair` → merged to `develop`; `develop → main` PR opened.
**Date:** 2026-07-30.
**Baseline (audited `main` @ e091c81):** 306 passed / 2 skipped, 82.39% coverage, **CI red**.
**After Phase 0:** **395 passed**, **84.56% coverage**, all gates green (backend + web).

---

## 1. What was fixed (task → outcome)

| # | Task | Outcome |
|---|------|---------|
| 1 | Verify build & tests locally | Confirmed 306/2 baseline; discovered the 3 local "without-key" failures are caused by a developer `.env`/`lemely.toml` leaking into the suite (CI is clean). Fixed hermetically (see task 7). |
| 2 | Fix red CI (`ruff format`) + create `develop` | Reformatted `tests/test_cli_new_commands.py`; `ruff format --check` now clean. `develop` branched from `main`. |
| 3 | Add `web/` to CI + `web` extra | Test job installs `.[dev,ui,web]` (FastAPI tests need it — was a latent CI failure). New `web` CI job: `npm ci` → typecheck → oxlint → build. |
| 4 | DET parser decision | **Wired the modular `lemely/io/det/`, deleted the monolith `parsers_det.py`** (see §3, decision D0.5). |
| 5 | Persistent Gemini USD cap | New `CostLedger` persists cumulative spend to `{output_dir}/gemini_spend.json`; **$8 hard ceiling** (default active); **$4/$6 ntfy warnings** once each. Proven across real OS processes. |
| 6 | HistoryStore corruption + `schema_version` | `load()` now raises `ParseError` on unreadable/invalid/schema-mismatch/future-version files (missing file still returns empty). `schema_version=1` persisted. |
| 7 | Single lockfile + `.env.example` + key mapping | Standardised on `uv.lock` (deleted `requirements.lock`); `GEMINI_API_KEY`/`GOOGLE_API_KEY`/`LEMELY_GEMINI_API_KEY` all populate settings (web portal no longer silently degraded); added `.env.example`. |
| 8 | Remove dead code | Dropped unused `respx` dep and the dead `live` pytest marker. |
| — | Acceptance: `doctor` real reachability | `GeminiClient.check_reachable()` (zero-token `models.list()`) replaces the `gemini_reachable` stub. |

`web/lib/api.ts` intentionally left for Phase 2 (per MISSION).

## 2. Acceptance criteria (MISSION §4)

- ✅ **CI fully green including web** — backend gates + a new `web` job (typecheck/lint/build) all pass locally; CI workflow updated.
- ✅ **Cost-cap tests prove persistence across processes** — verified with two separate `python` processes sharing one ledger file: proc2 reads proc1's $5.00; $4/$6 warnings fire exactly once across the boundary; next call hits the $8 ceiling. Unit tests: `test_persistence_across_instances`, `test_threshold_persists_across_instances`, `test_usd_ceiling_raises_from_persistent_ledger`.
- ✅ **`lemely doctor` reports real Gemini reachability** — live `models.list()` ping (skippable with `--no-network`).

## 3. Key decision — DET parser (D0.5)

Ran **both** parsers head-to-head on the 4 real Physics mark-scheme PDFs:

| Paper | Type | Monolith `parsers_det.py` | Modular `io/det/` |
|-------|------|---------------------------|-------------------|
| 0625_m20_ms_12 | MCQ | leaf 40 == max 40 ✅ | leaf 40 == max 40 ✅ |
| 0625_m21_ms_62 | practical | leaf 40 == max 40 ✅ | leaf 40 == max 40 ✅ |
| 0625_s19_ms_43 | theory | **leaf 88 ≠ max 80** (silent) | reconcile → `ParseError` → escalate to Gemini |
| 0625_s20_ms_31 | theory | **leaf 76 ≠ max 80** (silent) | reconcile → `ParseError` → escalate to Gemini |

The monolith silently emitted wrong theory totals (audit blocker #10); the modular parser honors `DetParserSettings` and reconciles, failing loud so the chain routes complex papers to Gemini. Adopted the modular parser; rewrote the parser test suite against it. Full rationale in `BUILD/DECISIONS.md` D0.5.

## 4. Test & coverage summary

- **395 passed, 0 failed, 12 subtests** (baseline 306). +89 tests, mostly the rewritten modular-parser suite (111 parser tests) plus cost-ledger/notify/history/doctor coverage.
- **Total coverage 84.56%** (baseline 82.39%; gate ≥70%). New modules: `cost_ledger.py` 100%, `notify.py` 100%, `budget_notify.py` 100%; `io/det/*` 83–100%.
- Suite is now **hermetic** against a developer's local `.env`/`lemely.toml` (`tests/conftest.py`), so the gate is trustworthy for unattended runs.

## 5. Gate evidence (final run)

```
ruff check .            → All checks passed!
ruff format --check .   → 123 files already formatted
mypy lemely             → Success: no issues found in 80 source files
lint-imports            → Contracts: 2 kept, 0 broken.
pytest                  → 395 passed, 1 warning, 12 subtests; Total coverage: 84.56%
web: npm run typecheck  → OK
web: npm run lint       → OK (exit 0; 6 pre-existing fast-refresh warnings)
web: npm run build      → OK
```

## 6. Commits (develop..HEAD)

```
3d03d4d feat(doctor): real Gemini reachability ping (models.list, zero-token)
73beab1 fix(history_store): surface corruption, add schema_version
7553e9c feat(gemini): persistent USD cost cap with $8 ceiling and ntfy warnings
9c4e025 refactor(parsers_det): adopt modular io/det parser, delete monolith
2e32f48 fix(config,ci): fix GEMINI_API_KEY mapping, add web CI, consolidate lockfile
cbcc38d fix(ci): apply ruff format to test_cli_new_commands.py; gitignore BUILD/logs
```

## 7. Screenshots

N/A — Phase 0 touched no UI. Screens begin in Phase 2.

## 8. Known issues / carried forward

- `gemini_spend.json` ledger uses last-writer-wins on concurrent writes (documented; acceptable for the single-writer CLI/build use). Phase 1's DB can supersede if needed.
- The audit's larger blockers (auth/RBAC, DB, mock-only SPA, deployment) are the subject of Phases 1–6, not Phase 0.
- Gemini live-call budget: $0.00 spent this phase (doctor ping mocked in tests; no live calls made).
