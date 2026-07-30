# BUILD STATE — single source of truth

status: RUNNING            # RUNNING | COMPLETE | HALTED
current_phase: 1
last_updated: 2026-07-30T04:32:00Z
gemini_spend_usd: 0.00

## Rules for maintaining this file
- Update BEFORE starting and AFTER finishing every task. Assume sudden death.
- Keep exactly one task `doing` at a time.
- When all Phase-6 acceptance criteria pass and DELIVERY.md is committed,
  set `status: COMPLETE` — the supervisor stops on this value.

## Phase 0 — Foundation repair
- [x] done — Read LEMELY_AUDIT.md fully; verify repo builds & tests pass locally
- [x] done — Fix ruff format on main-derived develop branch; create develop branch
- [x] done — Add web/ (typecheck, lint, build) + web extra to CI
- [x] done — Decide det parser: wire io/det/ OR keep monolith; delete the loser
       (D0.5: wired io/det/, deleted monolith. 371 passed, 84.13% cov. MCQ/practical
       parse correct; theory escalates via reconciliation ParseError — verified on 4 PDFs)
- [x] done — Persistent file-backed Gemini USD tracker, $8 hard cap, $4/$6 ntfy warnings
       (D0.6: CostLedger at {output_dir}/gemini_spend.json; verified cross-process
       persistence + once-per-threshold with 2 real OS processes; 388 passed, 84.62%)
- [x] done — HistoryStore: surface corruption, add schema_version
       (load() now raises ParseError on unreadable/invalid-JSON/schema-mismatch/
       future-version files; missing file still returns empty. schema_version=1
       persisted. Also fixed example_toml trailing-newline drift. 393 passed, 84.66%)
- [x] done — Single lockfile mechanism; .env.example; fix GEMINI_API_KEY mapping trap
- [x] done — Remove dead: respx, live marker; leave lib/api.ts for Phase 2
- [x] done — Acceptance: doctor real Gemini reachability (models.list zero-token ping)
- [x] done — Quality gates green; phase report; merged develop; PR #3 develop→main; ntfy
       (PHASE 0 COMPLETE. reports/phase-0/REPORT.md; 395 passed/84.56%; PR #3 open,
       NOT merged — human reviews main. Gemini spend $0.00.)

## Phase 1 — Database + Auth + Tenancy
Branch from `develop` as `feature/phase-1-db-auth-tenancy`. Expanded from MISSION §4.
- [ ] todo — Local Supabase stack committed: `supabase/` config, `supabase init/start`
       (Docker), seed scripts, Makefile targets (db-up/db-down/db-reset/seed), docs
- [ ] todo — SQLAlchemy 2 + Alembic wired to local Postgres; base config + first migration
- [ ] todo — Full relational schema (additive-only for later phases): users/profiles(role),
       schools, school_memberships(teacher↔school), seats, subscriptions+plan_tiers
       (manual activation flag), parent↔child links, classes, class_enrollments, subjects,
       papers(board/subject/session/year/variant/paper#), mark_schemes, uploads, attempts,
       question_results(marks,max,confidence,method-mark breakdown), weakness_records,
       review_queue, announcements, notifications, devices/sessions, xp_events, streaks
- [ ] todo — Supabase Auth (GoTrue): email/password signup+login per role; parent phone-OTP
       behind provider abstraction with a MOCK SMS provider (logs OTP; one switch to real)
- [ ] todo — FastAPI JWT validation middleware; replace the anonymous get_auth_context stub
- [ ] todo — RBAC dependency on EVERY route; kill both IDOR endpoints
       (POST /student/plan, POST /student/onboarding); row-level ownership checks
       (student=self; parent=linked children; teacher=their classes; school_admin=their
       school; platform_admin=all)
- [ ] todo — Migrate HistoryStore JSON → Postgres; migration script + parity tests; then
       delete the JSON store (io/history_store.py) after parity proven
- [ ] todo — Seat model: school_admin invites/creates N students against seat quota; a
       student may ALSO hold a personal subscription simultaneously
- [ ] todo — Device/session registry: max 3 concurrent devices; 4th login silently
       invalidates the oldest session
- [ ] todo — Acceptance: E2E auth tests for all 5 roles; adversarial security review
       (reviewer subagent) finds no unauthenticated/cross-tenant access; every route has
       an authz test. Quality gates (§6) green; report reports/phase-1/REPORT.md; merge
       develop; PR develop→main; ntfy

## Next action
Phase 0 is COMPLETE (PR #3 open, do not merge). Start Phase 1: read MISSION §4 Phase 1,
branch `feature/phase-1-db-auth-tenancy` from `develop`, begin with the local Supabase
stack + SQLAlchemy/Alembic foundation. Revisit BUILD/BLOCKERS.md (none currently).

## Session handoff notes
- 2026-07-30 (Phase 0 COMPLETE): all 8 tasks + doctor-reachability acceptance done.
  On `develop` (Phase 0 merged, pushed). PR #3 develop→main OPEN — DO NOT MERGE.
  Gates green: 395 passed / 84.56% cov; ruff/mypy/lint-imports clean; web ok.
  Gemini live spend $0.00 (all mocked). Next: Phase 1 (branch from develop).
  Reminder: run pytest with dev `.env`/`lemely.toml` present is fine now — conftest
  isolates them. Real PDFs: Sources/Physics/MarkingSchemes/ (4). Signed commits (-S),
  pre-commit before each commit, never merge the develop→main PR.
- 2026-07-30: Started Phase 0. Created `develop` + `feature/phase-0-foundation-repair`
  branches off main (e091c81). Verified suite: 306 passed / 2 skipped / 82.39% cov
  ONLY when local dev `.env` + `lemely.toml` are absent. Those files carry a real
  GEMINI key that makes 3 "without-key" tests fail locally (test_cli_doctor,
  test_runtime_config defaults, test_web_student plan_post 503). CI is clean (no
  .env/toml), so this is a local-only artifact — DO NOT "fix" those tests.
- Reverted trivial EOF-newline diffs on 2 tracked Sources/*.json; gitignored BUILD/logs/.
