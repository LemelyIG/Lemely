# BUILD STATE — single source of truth

status: RUNNING            # RUNNING | COMPLETE | HALTED
current_phase: 2
last_updated: 2026-08-01T06:30:00Z
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
- [x] done — RBAC dependency on EVERY route; kill both IDOR endpoints
       (POST /student/plan, POST /student/onboarding); row-level ownership checks
       (student=self; parent=linked children; teacher=their classes; school_admin=their
       school; platform_admin=all)
       (P1.6, D1.6: require_role(*roles) factory in deps.py (401 then 403). Student routes →
       require_role(Role.student), all keyed off auth.user_id (self-ownership inherent).
       Teacher router → router-level require_role(teacher, school_admin, platform_admin).
       IDOR killed: studentId removed from StudyPlanRequest/OnboardingRequest; identity is
       auth.user_id, smuggled id → 422. /health + /auth/* stay public. tests/test_authz_matrix.py
       (31 tests: no-token→401, wrong-role→403, IDOR-kill, real-token e2e). 468 passed / 12
       subtests / 86% cov; ruff/mypy/lint-imports clean. HONEST LIMITATION (D1.6): teacher
       per-tenant ownership (own classes only) is DEFERRED — teacher routes still read the
       shared interim HistoryStore; role boundary IS enforced (students/parents locked out),
       row-level teacher→class ownership lands when routes move to the DB class model.
       Parent routes: none exist yet (parent portal is Phase 3). ADVERSARIAL REVIEW still
       pending — run reviewer subagent on this diff at phase acceptance.)
- [x] done — Migrate HistoryStore JSON → Postgres; migration script + parity tests; the
       WEB/product surface now reads/writes history in Postgres (D1.8/D1.9).
       (D1.8: lemely/db/history_repo.py DbHistoryStore preserves the load/append/list_students
       surface over StudentHistory/PaperRecord (→ Attempt + WeaknessRecord rows); migrate_json_history()
       walks JSON students, reports unmigratable legacy keys. tests/test_history_repo_parity.py:
       6 PG-integration parity tests (model_dump parity vs JSON store, ordering, list_students,
       non-UUID rejection, migration incl. skipped legacy key). D1.9: get_history_store → DB store;
       HistoryStoreProtocol + now_iso moved to core/history.py; student/teacher routers + web
       grading service annotate the Protocol. 488 passed / 1 skipped / 12 subtests / 84.92% cov;
       ruff/format/mypy/lint-imports clean. THREE commits: 26b0b0d (repo+parity), 5cabb58 (web swap).
       DEVIATION (D1.9): io/history_store.py NOT deleted — it is ALSO used by app/cli.py and
       app/gradio_* (local, unauthenticated, no-UUID tools). Deleting it would force Postgres on
       those; out of the task's "web routers" scope. Web migrated now; JSON store retained for
       CLI/Gradio; full deletion deferred to the explicit follow-up below.)
- [ ] todo — (deferred, D1.9) Migrate CLI + Gradio history to the DB (or retire Gradio), THEN
       delete lemely/io/history_store.py + tests/test_history_store.py. Parity already proven, so
       low-risk. Not blocking Phase 1.
- [x] done — Seat model: school_admin invites/creates N students against seat quota; a
       student may ALSO hold a personal subscription simultaneously
       (P1.10/D1.10: SeatService (lemely/db/seat_repo.py) — on-demand seat allocation w/
       FOR UPDATE quota lock (TOCTOU-safe); ownership+quota checked before account creation so
       no orphaned accounts; revoke frees a slot, keeps the account, idempotent. Account creation
       via StudentAccountCreator seam; real AuthServiceStudentCreator (web/deps.py) wraps
       AuthService.signup pinned Role.student; invite generates one-time temp password when
       omitted. /api/school/seats router (list/invite/{id}/revoke) gated school_admin-only at
       router level (even platform_admin → 403). get_seat_service wired in deps + reset_singletons.
       Coexistence with personal Subscription proven. tests/test_seat_repo.py (12 PG-integration:
       quota/ownership/revoke/coexistence/non-uuid) + 6 new /api/school authz-matrix cases.
       509 passed / 1 skipped / 12 subtests / 85.00% cov; ruff/format/mypy/lint-imports clean.)
- [x] done — Device/session registry: max 3 concurrent devices; 4th login silently
       invalidates the oldest session (P1.11, D1.11 — chose fork (a) sid-gated request-time
       DB liveness check).
       (lemely/db/device_repo.py DeviceRegistry: register_login locks the user row FOR UPDATE
       (TOCTOU-safe like SeatService), reuses the row for a matching (user, client_device_id)
       or mints a fresh device, then evicts the oldest-by-last_seen_at beyond MAX_DEVICES=3 by
       setting revoked_at. tokens.mint_access_token gained an optional session_id claim;
       decode_token surfaces it. get_auth_context does a single indexed liveness read ONLY when
       a session_id claim is present (offline path preserved for hermetic/seat-invite tokens) →
       401 on evicted/unknown session. AuthService.signup/login/verify_otp take an optional
       DeviceContext; the /api/auth router builds it from body.deviceId + User-Agent. Additive
       migration 0003_device_client_id adds devices.client_device_id + index; applied live +
       `alembic check` drift-free. get_device_registry singleton wired in deps (+ reset_singletons).
       tests/test_device_repo.py: 10 PG-integration (3-coexist, 4th-evicts-oldest-only, same/distinct
       client-id dedupe, no-id fresh, liveness unknown/garbage, revoke ownership+idempotent,
       active_devices ordering, unknown-user, non-uuid). test_auth_dependency.py +3 hermetic
       (no-sid skips check; live→200; evicted→401). 522 passed / 1 skipped (live auth, no keys) /
       12 subtests / 85.41% cov (>85.00% prior); ruff/format/mypy/lint-imports clean.)
- [x] done — Acceptance: E2E auth tests for all 5 roles; adversarial security review
       (reviewer subagent) finds no unauthenticated/cross-tenant access; every route has
       an authz test. Quality gates (§6) green; report reports/phase-1/REPORT.md; merge
       develop; PR develop→main; ntfy
       (PHASE 1 COMPLETE 2026-08-01. tests/test_auth_e2e_roles.py: 5-role RBAC matrix (allowed→200,
       denied→403, no-super-role invariant) + parent OTP E2E through get_auth_context. Live
       tests/test_seat_invite_live.py PASSES vs real Supabase+GoTrue (seat-invite→login→app_role=
       student) — verified this session (both live tests green with keys). Reviewer adversarial
       sweep: NO Critical/High auth bypass; verified-clean on alg-confusion/session-liveness/
       signup-escalation/seat-IDOR/token-aud-exp/role-forgery. Fixed 3 findings, recorded D1.12:
       H2 teacher-upload cross-tenant-write kill (dropped caller student_id → paper_id key),
       M1 non-UUID schoolId/seat_id → 422 not 500 (typed uuid.UUID + regression tests),
       M2 removed fabricated "0" scheme stat cards (honesty). Gates: 548 passed / 2 skipped
       (live-only, pass with keys) / 12 subtests / 85.44% hermetic cov (>84.56% baseline);
       ruff/format/mypy(111 files)/lint-imports clean; web inherited-green (untouched since
       develop). reports/phase-1/REPORT.md committed. Merged develop; PR develop→main opened
       (NOT merged); ntfy sent.)

## Next action
**PHASE 1 COMPLETE** (2026-08-01) — merged to develop, pushed, develop→main PR opened (DO NOT MERGE),
ntfy sent. **Next: Phase 2** (branch `feature/phase-2-core-loop` from develop). Per MISSION §4 Phase 2:
wire the SPA to the API (resurrect web/lib/api.ts + react-query, delete student/data.ts + teacher/data.ts
mocks screen-by-screen), real SSE pipeline for CorrectPaper, PWA camera→multi-page-PDF→Supabase Storage
upload path, full metadata→mark-scheme→extraction→marking→confidence→grade/boundary→weakness pipeline,
grade-boundary ingestion (0580/0606/0625 per-variant), accuracy harness w/ golden fixtures (≥99% MCQ,
≥95% mark-level, 100% disagreements below review threshold), student dashboard on real data, plagiarism/
AI-detection advisory flags, PWA installable (Lighthouse). START by reading LEMELY_AUDIT.md's web section
+ web/lib/api.ts + web/**/data.ts to scope the mock→real migration; use a workflow for the screen-by-screen
sweep and for boundary scraping/fixture generation (keep each workflow < ~30 agents, checkpoint to disk).

### (carried, non-blocking) Deferred Phase-1 follow-ups
- (D1.9) Migrate CLI + Gradio history to the DB (or retire Gradio), THEN delete lemely/io/history_store.py
  + tests/test_history_store.py. Parity already proven; low-risk. Do opportunistically.
- (D1.6) Teacher per-tenant ownership (own-classes-only) lands with the DB class model in Phase 2/3.
- GoTrue is not run in CI (live auth/seat tests skip there); hermetic tests cover the logic.

## Superseded — Phase-1 acceptance detail (kept for provenance)
Device/session registry DONE (P1.11/D1.11 — ready to commit). Next non-done task: the FINAL
Phase-1 task — **Phase-1 acceptance**:
  1. E2E auth tests for all 5 roles (student/parent/teacher/school_admin/platform_admin): a full
     signup/login (or OTP for parent) → authed request → correct RBAC outcome path. Some of this
     is covered by test_authz_matrix.py + test_auth_router.py already; audit for the gap (esp. a
     real end-to-end parent OTP flow and a school_admin seat-invited student logging in) and fill it.
  2. Adversarial security review of the WHOLE auth surface via the `reviewer` subagent (the D1.7
     pass was only ONE partial review; the acceptance sweep is still owed). Give it: lemely/auth/**,
     lemely/web/deps.py, lemely/web/routers/{auth,student,teacher,school}.py, lemely/db/{seat_repo,
     device_repo,history_repo}.py. Verify findings yourself; address them.
  3. [DONE this session, commit 9b287a9] "Every route has an authz test" — authz matrix is now
     exhaustive: added /student/correct, student-POST wrong-role→403, and the two missing teacher
     GETs. Teacher/school routers are router-level gated so their POSTs are covered by the guard
     proof. If the adversarial review (item 2) flags a specific untested route, add it then.
  4. [DONE this session, commit 35aec2a] CI now runs the real-DB tests: postgres:16 service on
     port 54322 + `alembic upgrade head` added to .github/workflows/ci.yml test job. (GoTrue is
     still not run in CI, so test_auth_live.py stays skipped — that's fine; hermetic tests cover it.)
  5. Quality gates (§6) green; write reports/phase-1/REPORT.md; merge feature→develop; push;
     open develop→main PR via `gh` (DO NOT MERGE it); ntfy phase-complete.
The deferred CLI/Gradio history→DB deletion (D1.9) is NOT blocking; do it opportunistically or at
Gradio retirement. Revisit BUILD/BLOCKERS.md (none currently).

CI HEADS-UP (unchanged): DB/auth integration tests skip when Postgres unreachable, so CI is
green today; before the acceptance task add a Postgres services block + `alembic upgrade head`
to .github/workflows/ci.yml so real-DB auth/authz tests actually run in CI.

HEADS-UP for CI: the new DB integration tests (tests/test_db_schema.py) skip when Postgres
is unreachable, so CI stays green today. Before the auth E2E task, CI (.github/workflows/
ci.yml) needs a Postgres `services:` block (or a Supabase step) + `alembic upgrade head`,
otherwise the real-DB auth/authz tests will silently skip in CI.

## Session handoff notes
- 2026-07-31 (Device/session registry DONE, P1.11/D1.11): resumed on a dirty tree carrying a
  prior session's PARTIAL device-registry work — modified auth/service.py (DeviceContext + wiring),
  auth/tokens.py (session_id claim), db/models/users.py (client_device_id column + index), an
  untracked db/device_repo.py (complete, well-crafted DeviceRegistry), and D1.11 recorded in
  DECISIONS. Verified before trusting: the WIP was INCOMPLETE — no migration 0003 (model had the
  new column but no migration → DB drift), get_auth_context had NO liveness check (the whole point
  of the feature was unwired), the router passed no DeviceContext, and there were ZERO tests.
  Completed the unit: wrote migration 0003_device_client_id (additive; applied live; `alembic check`
  drift-free); added get_device_registry singleton + wired it into get_auth_service AND the
  get_auth_context liveness check (sid-gated, offline path preserved) + reset_singletons; added
  optional deviceId to the 3 auth DTOs and User-Agent extraction in the router → DeviceContext;
  exported DeviceContext; wrote tests/test_device_repo.py (10 PG-integration) + 3 hermetic liveness
  tests in test_auth_dependency.py. Gates: 522 passed / 1 skipped (live auth, no keys) / 12 subtests
  / 85.41% cov (>85.00% prior); ruff/format/mypy/lint-imports clean. Supabase stack UP; migrations
  at 0003 head. Committing on feature/phase-1-db-auth-tenancy. Next: Phase-1 acceptance (final task).
- 2026-07-31 (Seat model DONE, P1.10/D1.10): resumed on a dirty tree carrying a prior
  session's PARTIAL, UNRUN seat work — three untracked files (lemely/db/seat_repo.py,
  lemely/web/routers/school.py, lemely/web/schemas_school.py). Verified before trusting:
  the WIP was INCOMPLETE — the router imported `get_seat_service` from deps.py which did
  NOT exist, the school router was NOT registered in app.py, and there were NO tests.
  The service/router/DTO code itself was sound and matched the P1.3 models. Completed the
  unit: added `AuthServiceStudentCreator` + `get_seat_service` (+ reset_singletons) to
  web/deps.py; registered school.router in app.py; added schemas_school to the mypy
  disallow-any-explicit override list (same false-positive class as the other DTO modules).
  Wrote tests/test_seat_repo.py (12 PG-integration tests: quota boundary + no-orphaned-account,
  ownership on invite/usage/list/revoke, revoke frees+keeps-account+idempotent, unknown-seat
  404, personal-subscription coexistence, non-UUID rejection) + 6 /api/school authz cases in
  test_authz_matrix.py. NOTE this FastAPI version registers included routers lazily as
  `_IncludedRouter`, so `app.routes` inspection shows no seat paths — TestClient requests
  (401/403) are the real proof. Gates: 509 passed / 1 skipped (live auth, no keys) / 12
  subtests / 85.00% cov (>84.92% prior); ruff/format/mypy/lint-imports clean. Supabase stack
  UP. Committing on feature/phase-1-db-auth-tenancy. Next: device/session registry (max 3).
- 2026-07-31 (HistoryStore→Postgres web migration DONE, same session as D1.7): after the D1.7
  hardening, executed the HistoryStore→Postgres task in two committed increments against LIVE
  Postgres (supabase stack up). Increment A (26b0b0d): lemely/db/history_repo.py DbHistoryStore
  (interface-preserving) + migrate_json_history() + 6 PG parity tests — parity proven via
  model_dump equality vs the JSON store. Increment B (5cabb58): get_history_store → DB store;
  extracted HistoryStoreProtocol + now_iso into core/history.py; student/teacher routers + web
  grading service annotate the Protocol. KEY DEVIATION recorded as D1.9: did NOT delete
  io/history_store.py — it is also used by app/cli.py + app/gradio_* (local, unauthenticated,
  no-UUID tools); deleting it would force Postgres on them, out of the task's web-routers scope.
  Web migrated; JSON store retained for CLI/Gradio; deletion deferred to an explicit follow-up
  todo. Web tests untouched (they override get_history_store with a JSON store double at runtime,
  so the web suite never hits PG). 488 passed / 1 skipped (live auth, no keys) / 12 subtests /
  84.92% cov; ruff/format/mypy/lint-imports clean. STATE task marked done. Next: Seat model.
- 2026-07-31 (D1.7 hardening committed on resume): resumed on a dirty tree carrying a
  prior session's *incomplete, unrun* adversarial-security fixes (otp.py resend cooldown,
  history_store.py _safe_key guard, auth.py signup-role restriction, config/deps wiring).
  Verified before trusting: the OtpRateLimitError raise had NO caller handling it (would
  500, not 429) and the source change silently BROKE two existing tests
  (test_signup_endpoint signed up as teacher; test_reissue_resets reissued same-instant).
  Completed the unit: router maps OtpRateLimitError→429; added cooldown tests, signup
  elevated-role 403 tests (3 roles), history unsafe-key rejection tests (7 hostile keys);
  fixed the 2 broken tests; recorded D1.7 in DECISIONS.md. 482 passed / 1 skipped (live
  auth, no keys) / 12 subtests / 84.77% cov; ruff/format/mypy/lint-imports clean. Committed
  (2596ddf) on feature/phase-1-db-auth-tenancy. NOTE the full adversarial reviewer pass over
  the whole auth surface is STILL due at Phase-1 acceptance (this was one prior partial pass).
  Next: HistoryStore→Postgres migration (unchanged).
- 2026-07-31 (P1.5 + P1.6 DONE, same session): after P1.4, implemented the JWT bearer
  dependency (P1.5) then RBAC (P1.6). deps.py get_auth_context validates HS256 tokens →
  AuthContext or 401; require_role(*roles) adds 403 role-gating. Student routes gated to
  Role.student (self-owned via auth.user_id); teacher router gated at router level to
  {teacher, school_admin, platform_admin}. Killed both IDORs (removed studentId from the two
  request DTOs; identity = auth.user_id). Existing web tests override get_auth_context so they
  stayed green after the DTO changes. New: test_auth_dependency.py (8), test_authz_matrix.py
  (31). Full suite 468 passed / 12 subtests / 86% cov; all static gates clean. Two focused
  commits (P1.5, P1.6). Adversarial reviewer pass over the auth surface is deferred to the
  Phase-1 acceptance task (still enforce it there). Next: HistoryStore→Postgres migration.
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
