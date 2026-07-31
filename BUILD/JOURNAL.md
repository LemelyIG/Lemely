# Session journal

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
