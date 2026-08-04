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

## 2026-08-01 — Phase 1 COMPLETE (acceptance)
- Did: finished the final Phase-1 task. Resumed on a dirty tree carrying a prior session's
  partial acceptance work (5-role E2E test file, live seat-invite test, and a teacher-upload
  fix referencing an unrecorded "D1.12"). Verified before trusting: the teacher.py change was
  sound (removes a caller-supplied student_id cross-tenant-write vector) and broke no existing
  tests, but D1.12 was never recorded and the review it implied was owed. Recorded D1.12; ran a
  full `reviewer` adversarial sweep of the whole auth surface → NO Critical/High bypass. Fixed
  its two real findings: M1 (non-UUID schoolId/seat_id → 422 not 500, typed uuid.UUID + 2
  regression tests) and M2 (removed fabricated "0" scheme stat cards). Wrote reports/phase-1/
  REPORT.md. Merged to develop, pushed, opened develop→main PR (unmerged), ntfy.
- Learned: this pytest+cov addopts suppresses the "N passed" summary under -q; use
  `-o addopts=""` to see it (548 passed / 2 skipped / 12 subtests / 85.44% hermetic cov). The
  2 skips are live-only tests — they PASS against the local Supabase+GoTrue stack when both
  SERVICE_ROLE_KEY + ANON_KEY are exported (newer `supabase status` emits JSON; parse it).
- Next: Phase 2 — core loop end-to-end. Branch feature/phase-2-core-loop from develop; scope
  the SPA mock→real migration (web/lib/api.ts + **/data.ts) and boundary/fixture pipelines;
  drive the fan-out with small checkpointed workflows.

## 2026-08-03 — P2.1 real correction pipeline (Phase 2)
- Did: Resumed clean tree on feature/phase-2-core-loop (P2.1 marked `doing`). Scoped the stub
  `/api/student/correct`, the marking pipeline (grading service, correct_paper), and the DB models
  (Attempt/QuestionResult/WeaknessRecord/ReviewQueueItem — all columns already exist from P1.3).
  Delegated implementation to implementer(opus) with a full self-contained brief; verified every
  §6 gate myself (never trusted the claim): ruff/format/mypy(114)/lint-imports clean; 561 passed /
  2 skipped (live-only) / 12 subtests; new tests 12 passed. Adversarially reviewed the /correct
  rewrite + the one replaced test (honest evolution, not a weakening). Committed signed f2d4c97.
- Learned: `grade_paper(student_id=None)` returns the AccuracyReport without persisting — reused it,
  then persisted the full report (Attempt + per-question QuestionResult + WeaknessRecord +
  ReviewQueue) via a new AttemptRepository. `matched_point_ids` JSONB is the method-mark breakdown
  (no separate column). SSE bus is global/single-stream — /correct tests run serially. pre-commit
  `--all-files` keeps re-flagging 2 newline-less Sources/*.json (pre-existing drift) — stage only
  the task's files and run pre-commit on the staged set instead.
- Next: P2.2 grade-boundary ingestion (scrape 0580/0606/0625 per-variant thresholds w/ provenance
  → parse into boundary table → exact lookup + per-subject-avg fallback with "estimated" flag).
  Use a checkpointed Workflow for the scrape/parse fan-out (MISSION authorizes it). Start by scoping
  lemely/io/grade_boundaries.py (GradeBoundaryStore.resolve) + its boundary data source.
  CARRIED: restore coverage 85.10%→≥85.44% before the P2.10 develop merge (named branches in STATE).

## 2026-08-04 — P2.2 grade-boundary ingestion (Phase 2)
- Did: Resumed on a dirty tree carrying a prior session's COMPLETE but uncommitted P2.2 work
  (scripts/ingest_grade_boundaries.py, populated lemely/data/grade_boundaries.json +
  grade_boundaries_provenance.json, D2.1 already drafted in DECISIONS.md, test + student.py copy
  changes, a uv.lock drift fix). Verified before trusting: reran the script's math independently
  (347 exact keys == provenance keys, per-subject `_defaults` genuinely distinct, sample entries
  match provenance URLs), ran all §6 static gates fresh (ruff/format/mypy incl. scripts//
  lint-imports all clean) and the full pytest suite (green, cov-fail-under=70 met at 81.28% —
  lower than the 85%+ baseline only because Postgres/Supabase were down this session so all
  DB-integration tests skip, same known pattern as prior sessions) plus test_grade_boundaries.py
  standalone (20/20 pass). Everything checked out — committed as-is rather than redoing the work.
  Added BUILD/.supervisor_phase to .gitignore (new marker file type, same family as the ones
  already ignored).
- Learned: gceguide.com (one of the 3 mirrors MISSION §4 named) is now a squatted gambling-slot
  site — do not fetch it again. cambridgeinternational.org publishes the same grade-threshold PDFs
  directly with a predictable per-session index; better provenance than any mirror. The `db` extra
  in pyproject.toml (alembic/sqlalchemy/psycopg/pyjwt) was declared but had never actually been
  resolved into uv.lock — fixed as a drive-by.
- Next: P2.3 accuracy harness + golden fixtures (real past papers/mark schemes for the 3 subjects,
  synthetic handwritten answer sheets with known ground truth, ≥99% MCQ / ≥95% mark-level gates).
  Kicked off `supabase start` in the background at session end (stack was fully torn down —
  no containers existed, first-run image pulls) to restore DB-integration test coverage for the
  next session; check it came up before relying on Postgres-backed tests.
