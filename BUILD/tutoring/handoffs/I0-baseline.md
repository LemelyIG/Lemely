# I0b baseline (2026-10-25, tree `864bf9c9`+)

Standing reds that exist BEFORE any tutoring code. A wave gate compares against this file; only a new finding is a failure.

| Gate | Baseline | Detail |
|---|---|---|
| `gate_db.sh upgrade` | PASS | empty `lemely_tutoring_gate` upgrades to `0043_merge_heads` |
| `gate_db.sh check` (`alembic check`) | 1 standing diff, informational | `Detected removed table 'ai_detection_removal_audit_log'`: the migration `0037` audit table exists in the database but has no ORM model. Not ours. Any additional diff after T01 is a finding, except what SPEC §a.4 F20 says `alembic check` cannot see (exclusion constraints, computed columns, partial predicates) |
| `npx --yes impeccable detect web/src/` | 1 standing finding (exit 2) | `web/src/portals/teacher/index.tsx:205 [side-tab] border-s-2`. 9 advisories (bounce easing in `index.css`, `marketing.css`). Regex mode only: an undercount |
| pytest skips | none recorded | no suite ran at I0b; the files each task runs must show 0 skipped |
| P-6 live DB mode | **dedicated** | `live_e2e.sh dedicated e2e/seed-contract.spec.ts e2e/tutoring-smoke.spec.ts`: 7 passed; shared `postgres` `alembic_version` `0043_merge_heads` before and after, verified |

## Findings from getting the live probe green
- The dedicated database needs the ingested grade-threshold rows: `seed_e2e.py` refuses to grade without verified `component_thresholds`, and they come from the network (`scripts/ingest_thresholds.py`). `live_e2e.sh` now migrates the dedicated database and copies `component_thresholds` and `option_thresholds` from the dev database (4 verified component rows there on 2026-10-25). Commit `864bf9c9`.
- The Playwright browser for this worktree's version (`chromium-1234`) was not in `~/.cache/ms-playwright`; installed with `npm --prefix web exec -- playwright install chromium`.
- `npm --prefix web ci` needs `PUPPETEER_SKIP_DOWNLOAD=1` here (Puppeteer's browser download fails).
- Web exports now carry `DESIGN.md`, `docs/design-canvas-notes.md`, `.github/workflows/ci.yml` (commit `7c5fd10e`), because web unit tests read them from the repo root.
