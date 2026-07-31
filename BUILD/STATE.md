# BUILD STATE — single source of truth

status: RUNNING            # RUNNING | COMPLETE | HALTED
current_phase: 1
last_updated: 2026-07-31T00:00:00Z
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
- [x] done — Local Supabase stack committed: `supabase/` config, `supabase init/start`
       (Docker), seed scripts, Makefile targets (db-up/db-down/db-reset/seed), docs
       (P1.1: supabase/config.toml + seed.sql; Makefile db-* + seed targets; docs/database.md.
       DatabaseSettings/SupabaseSettings added to config. Static gates + suite green.)
- [x] done — SQLAlchemy 2 + Alembic wired to local Postgres; base config + first migration
       (P1.2: lemely/db/{base,session,seed}.py + migrations/env.py; empty 0001_baseline head;
       Base w/ naming convention; alembic reads Settings.database.url. Live boot verified:
       supabase start + alembic upgrade head applied against local Postgres.)
- [x] done — Full relational schema (additive-only for later phases): users/profiles(role),
       schools, school_memberships(teacher↔school), seats, subscriptions+plan_tiers
       (manual activation flag), parent↔child links, classes, class_enrollments, subjects,
       papers(board/subject/session/year/variant/paper#), mark_schemes, uploads, attempts,
       question_results(marks,max,confidence,method-mark breakdown), weakness_records,
       review_queue, announcements, notifications, devices/sessions, xp_events, streaks
       (P1.3: 22 tables across 8 model modules + enums.py; migration 0002_core_schema.
       Fixed a blocking bug in the WIP: uuid/datetime/date were TYPE_CHECKING-only so
       every model failed to configure (MappedAnnotationError) — now runtime-imported.
       Enum server_defaults cast as ::type so alembic check is drift-free (D1.3). Verified
       live: downgrade base→upgrade head applies against local Supabase PG; `alembic check`
       = "No new upgrade operations detected". Added tests/test_db_schema.py (metadata +
       real-PG integration, skips if PG down). Gates green: 402 passed / 84.92% cov;
       ruff/mypy/lint-imports clean.)
- [x] done — Supabase Auth (GoTrue): email/password signup+login per role; parent phone-OTP
       behind provider abstraction with a MOCK SMS provider (logs OTP; one switch to real)
       (P1.4: lemely/auth/ — GoTrue REST client (admin create + password grant), SmsProvider
       protocol + MockSmsProvider, in-memory OTP store, AuthService mirroring GoTrue users →
       public.users, FastAPI /api/auth router. D1.5 recorded AND IMPLEMENTED: backend is the
       sole token issuer — signup/login/OTP all mint self-signed HS256 tokens; GoTrue's ES256
       token is discarded, one offline validation path. The live test (test_auth_live.py)
       initially FAILED — signup forwarded GoTrue's ES256 token which HS256 decode rejects
       ("alg not allowed"); D1.5 was a recorded-but-unimplemented decision. Fixed:
       tokens.mint_access_token(provider=...) generalises the minter; service.signup/login
       call _mint_email_token(provider="email"). Hermetic tests that asserted the old
       `gotrue-access-` prefix now decode+validate claims. Verified LIVE vs real GoTrue+PG:
       429 passed / 12 subtests / 0 skip (keys set) / 85.80% cov; static gates clean.)
- [x] done — FastAPI JWT validation middleware; replace the anonymous get_auth_context stub
       (P1.5: lemely/web/deps.py get_auth_context is now a real dependency — HTTPBearer +
       decode_token (HS256, shared jwt_secret) → AuthContext(user_id=sub, role=app_metadata.role,
       email, phone). Every failure (no header, bad sig, expired, wrong aud, missing/unknown
       role) → 401 with WWW-Authenticate: Bearer. AuthContext is now a frozen dataclass; the
       anonymous default is GONE. Existing web tests already override get_auth_context via
       dependency_overrides so they stayed green. tests/test_auth_dependency.py added (8 tests:
       valid/all-5-roles/missing-header/garbage/wrong-secret/expired/unknown-role/missing-role).
       437 passed / 12 subtests / 85.88% cov; static gates clean. NOTE: routes are not yet
       role-gated — that is P1.6 RBAC.)
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
P1.4 auth + P1.5 JWT dependency DONE. Next non-done task: **RBAC on EVERY route** —
a role-gating dependency (e.g. `require_role(*roles)` built on `get_auth_context`) applied
to every student/teacher/auth route, PLUS row-level ownership checks (student=self;
parent=linked children; teacher=their classes; school_admin=their school; platform_admin=all)
and KILL the two IDOR endpoints (POST /student/plan, POST /student/onboarding — they take a
caller-supplied id; must derive it from AuthContext.user_id instead). Every route needs an
authz test. The route-by-route sweep is a good candidate for a workflow (MISSION §5). Then
HistoryStore→Postgres migration, seat model, device registry, E2E/authz acceptance.
Revisit BUILD/BLOCKERS.md (none currently).

Building context tip: get_auth_context lives in lemely/web/deps.py; AuthContext.role is the
platform role STRING (Role value). student router already threads auth.user_id into
history_store.load(); teacher router does NOT yet depend on auth at all (add it in P1.6).

HEADS-UP for CI: the new DB integration tests (tests/test_db_schema.py) skip when Postgres
is unreachable, so CI stays green today. Before the auth E2E task, CI (.github/workflows/
ci.yml) needs a Postgres `services:` block (or a Supabase step) + `alembic upgrade head`,
otherwise the real-DB auth/authz tests will silently skip in CI.

## Session handoff notes
- 2026-07-31 (P1.4 auth DONE): resumed on a dirty tree carrying the full P1.4 auth work
  (lemely/auth/ + router + tests) plus a recorded D1.5 decision. Verified before trusting:
  static gates clean, hermetic auth tests green — BUT the live test (test_auth_live.py) had
  been SKIPPING (no keys in env). Ran it with the `supabase status` service-role/anon keys
  against the running stack and it FAILED: signup returned GoTrue's ES256 token, which the
  HS256-only decode_token rejects. D1.5 (backend re-mints all tokens HS256) was recorded but
  NOT implemented — signup/login still forwarded `token.access_token`. Implemented D1.5:
  generalised tokens.mint_otp_token → mint_access_token(provider=...); signup/login now mint
  self-signed HS256 via _mint_email_token(provider="email"); GoTrue token discarded. Updated
  the 2 hermetic tests that asserted the old `gotrue-access-` prefix to decode+validate claims
  (they had masked the gap by never decoding). Gitignored BUILD/.supervisor_notify_state.
  Full suite LIVE (keys set): 429 passed / 12 subtests / 0 skip / 85.80% cov (> 84.92% prior);
  ruff+mypy+lint-imports clean. Supabase stack UP; migrations at 0002_core_schema head.
  Committing on feature/phase-1-db-auth-tenancy. Next: JWT validation middleware (P1.5).
- 2026-07-30 (P1.4 auth START): resumed clean tree (ahead 2, unpushed). No auth code on
  disk yet — only D1.4 decision recorded. Supabase stack UP (GoTrue = supabase_auth_Lemely).
  Local keys via `supabase status`: SERVICE_ROLE_KEY + ANON_KEY are the JWT-form keys GoTrue
  wants for admin (Bearer) + apikey; JWT_SECRET matches SupabaseSettings default. Dispatched
  implementer(opus) to build lemely/auth/ per D1.4 + FastAPI /api/auth router + hermetic
  tests + live-skip integration test. Verifying gates before commit.
- 2026-07-30 (P1.3 schema DONE): resumed on a dirty tree that was the WIP schema (8 model
  modules + migration 0002). It did NOT actually work — models were TYPE_CHECKING-only for
  uuid/datetime/date, so SQLAlchemy could not resolve Mapped[...] at runtime (nothing had
  ever loaded them). Fixed the imports, cast enum server_defaults (D1.3) for drift-free
  autogenerate, added tests/test_db_schema.py, verified live against local Supabase PG.
  Committed on feature/phase-1-db-auth-tenancy. Supabase stack is UP (docker). 402 passed /
  84.92% cov. Gemini spend still $0.00. Next: Supabase Auth (GoTrue) + JWT/RBAC.
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
