# Session journal

## 2026-07-31 — Phase 1 (Device/session registry P1.11/D1.11 + acceptance groundwork)
- Did: completed the device/session registry. Resumed on a dirty tree carrying a prior
  session's PARTIAL device work — a complete untracked device_repo.py (DeviceRegistry) plus
  service.py/tokens.py/models wiring and a recorded D1.11, but INCOMPLETE: no migration 0003
  (model column with no migration → drift), no liveness check in get_auth_context (the feature
  was unwired), no DeviceContext passed from the router, and zero tests. Finished the unit:
  migration 0003_device_client_id (additive, applied live, `alembic check` drift-free);
  get_device_registry singleton wired into get_auth_service + the sid-gated liveness check in
  get_auth_context (offline path preserved for tokens without a session_id); optional deviceId
  on the 3 auth DTOs + User-Agent → DeviceContext in the router; 10 PG-integration device tests
  + 3 hermetic liveness tests. Committed (d8a7a70) + pushed. Then two acceptance sub-items:
  a Postgres service + `alembic upgrade head` in CI so DB/authz/seat/device tests actually RUN
  instead of skip (35aec2a); and made the authz matrix exhaustive — /student/correct, student
  POST wrong-role→403, two missing teacher GETs (9b287a9). 522 passed / 1 skipped / 12 subtests
  / 85.41% cov; all static gates clean; all three commits pushed.
- Learned: eviction sets `revoked_at`, and because get_auth_context does a per-request liveness
  read only when a `session_id` claim is present, an evicted session's next request 401s
  immediately — this is why D1.11 chose fork (a) over refresh-boundary revocation (no refresh
  flow exists, so an evicted token would otherwise live its 3600s TTL). Constructing DeviceRegistry
  opens no DB connection (engine is lazy), so injecting it into get_auth_context keeps the hermetic
  auth-dependency suite offline. Teacher/school routers are router-level gated, so a representative
  GET spread legitimately proves the guard for their POSTs too.
- Next: FINAL Phase-1 task = acceptance. Remaining: (1) E2E auth tests for all 5 roles;
  (2) adversarial `reviewer` subagent pass over the WHOLE auth surface (D1.7 was only partial) —
  verify + fix findings; (3) confirm every route has an authz test (done for the guard model);
  (4) quality gates; write reports/phase-1/REPORT.md; merge feature→develop; open develop→main PR
  (do NOT merge); ntfy phase-complete. CI Postgres block + authz-matrix completeness already landed.

## 2026-07-31 — Phase 1 (Seat model, P1.10/D1.10)
- Did: completed the seat model. Resumed on a dirty tree carrying a prior session's
  PARTIAL, UNRUN seat work (3 untracked files: seat_repo.py, routers/school.py,
  schemas_school.py). Verified before trusting — the WIP was incomplete: router imported
  a non-existent get_seat_service, the router was never registered in app.py, and there
  were no tests. Finished it: AuthServiceStudentCreator + get_seat_service in web/deps.py,
  registered school.router, added schemas_school to the mypy any-explicit override, wrote
  12 PG-integration seat tests + 6 /api/school authz cases. On-demand allocation with a
  FOR UPDATE quota lock (TOCTOU-safe), ownership before account-creation (no orphans),
  idempotent revoke, personal-subscription coexistence. 509 passed / 1 skipped / 12
  subtests / 85.00% cov; all static gates clean. Committed (b7d2bc9) + pushed.
- Learned: this FastAPI version registers included routers lazily as `_IncludedRouter`,
  so `app.routes` shows no seat paths — TestClient 401/403 requests are the real proof,
  not route introspection. The recurring end-of-file-fixer diff on two tracked
  Sources/Physics/*.json is unrelated noise; revert it to keep commits scoped (a prior
  session made the same call).
- Next: device/session registry (max 3, 4th evicts oldest). Device model already exists
  (no migration). OPEN FORK to settle as D1.11: per-request session-revocation lookup
  (breaks D1.5's offline-only token validation) vs. revoke-at-refresh (but no refresh flow
  exists, so an evicted access token lives out its 3600s TTL). Decide before implementing.

## 2026-07-30 — Phase 0 (Foundation repair)
- Did: completed all Phase 0 tasks — green CI (ruff format) + web CI job + web extra;
  fixed GEMINI_API_KEY mapping trap (validation_alias); consolidated to uv.lock;
  removed dead respx/live marker; adopted modular io/det parser and deleted the
  monolith (evidence: theory papers now escalate instead of silently mis-parsing);
  persistent $8 Gemini USD ledger with $4/$6 ntfy warnings; HistoryStore surfaces
  corruption + schema_version; doctor real reachability ping. Report + PR opened.
- Learned: a developer's local `.env`/`lemely.toml` leaks into pytest via
  `env_file=".env"` and TOML discovery — made the suite hermetic in conftest so the
  unattended gate is trustworthy. DO NOT "fix" the 3 no-key tests; they were env
  pollution. Real PDFs live in `Sources/Physics/MarkingSchemes/` (4 of them).
- Next: Phase 1 — DB + Auth + Tenancy. Expand STATE.md Phase-1 checklist from
  MISSION §4, stand up local Supabase, SQLAlchemy+Alembic schema, JWT middleware + RBAC.
