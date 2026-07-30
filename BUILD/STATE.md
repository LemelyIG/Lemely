# BUILD STATE — single source of truth

status: RUNNING            # RUNNING | COMPLETE | HALTED
current_phase: 0
last_updated: (orchestrator writes ISO timestamp here on every update)
gemini_spend_usd: 0.00

## Rules for maintaining this file
- Update BEFORE starting and AFTER finishing every task. Assume sudden death.
- Keep exactly one task `doing` at a time.
- When all Phase-6 acceptance criteria pass and DELIVERY.md is committed,
  set `status: COMPLETE` — the supervisor stops on this value.

## Phase 0 — Foundation repair
- [ ] todo — Read LEMELY_AUDIT.md fully; verify repo builds & tests pass locally
- [ ] todo — Fix ruff format on main-derived develop branch; create develop branch
- [ ] todo — Add web/ (typecheck, lint, build) + web extra to CI
- [ ] todo — Decide det parser: wire io/det/ OR keep monolith; delete the loser
- [ ] todo — Persistent file-backed Gemini USD tracker, $8 hard cap, $4/$6 ntfy warnings
- [ ] todo — HistoryStore: surface corruption, add schema_version
- [ ] todo — Single lockfile mechanism; .env.example; fix GEMINI_API_KEY mapping trap
- [ ] todo — Remove dead: respx, live marker; leave lib/api.ts for Phase 2
- [ ] todo — Quality gates green; phase report + screenshots N/A; PR develop→main; ntfy

## Phase 1 — Database + Auth + Tenancy
(orchestrator expands this checklist from MISSION.md §4 when Phase 0 completes;
 same for later phases)

## Next action
Read BUILD/MISSION.md end to end, then LEMELY_AUDIT.md, then start Phase 0 task 1.

## Session handoff notes
(most recent session writes 2–4 lines here for the next session)
