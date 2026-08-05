# Session journal

## 2026-08-05 — Phase 2, P2.7 steps 5b-8 (student surface complete)
- Did: resumed on a clean tree at P2.7 step 5b. Dispatched three `implementer` rounds
  (CorrectPaper+PaperResult real upload/SSE wiring; StudyPlan+Standings+Onboarding wiring;
  did the final data.ts cleanup pass myself, mechanical grep-verify-delete). Orchestrator-
  verified every round independently — read every diff, re-ran typecheck/lint/build myself
  (never trusted subagent claims), and for Standings specifically read the backend
  `student_standings` handler myself to confirm `rank` is honestly `""` (no cross-student
  cohort) rather than fabricated, per MISSION's leaderboard/grade-privacy rules.
- Learned: caught and fixed one regression the first implementer round flagged but didn't
  resolve — the sidebar's "Paper result" nav link 404'd once `result` became `result/:paperId`;
  removed it (no non-parameterized target exists) rather than leave it broken, matching the
  established remove-don't-fake precedent (D1.6 M2). `student/data.ts` had accumulated dead
  Overview/Subject mock exports across steps 3-4 that nobody cleaned up until step 7 — worth
  double-checking "done" steps' cleanup claims against actual grep results, not just their
  self-report.
- Next: P2.8 — teacher surface wiring (Grading, Review queue, MarkSchemes, Overview; delete
  teacher/data.ts incrementally). Full gate suite is green (web + backend, 81.47% cov, 0
  failed/51 skipped-as-usual) and pushed as of commit 2f9a513. Exiting cleanly here per MISSION
  §5 context-hygiene guidance — this is a clean task-boundary checkpoint, not mid-task.

## 2026-08-04 — Phase 2, P2.3 step 6 (D2.2 review-confidence threshold, resolved)
- Did: resumed on a clean tree (no wip commit needed). Prior session had escalated step 6 via
  `next_run_model: opus`, but this run launched on Sonnet, so rather than decide an Opus-reserved
  item myself, delegated the full design brief to the `architect` subagent (Opus-tier by MISSION
  §5's own model-discipline table for subagents) — a valid alternative path to the literal
  supervisor-relaunch mechanism. Verified its work rather than trusting the report: read the full
  D2.2 DECISIONS.md entry, then ran ruff/ruff-format/mypy/lint-imports/pytest myself. All clean;
  full suite green (0 failures, 45 skips — Postgres/live-auth pattern, unchanged), 81.92% cov.
- Learned: architect's decision was well-grounded — single shared `REVIEW_CONFIDENCE_THRESHOLD =
  0.90` constant (not config, deliberately — cross-layer invariant, not an operator knob) dedupes
  THREE call sites (found a 4th duplicate in teacher.py nobody had tracked). Rejected the
  `awarded_marks != question.marks` secondary-signal idea on the actual data (proved
  anti-correlated with itself across the 3 failure cases — 2 errors awarded full marks, 1 awarded
  partial). Added a genuinely zero-false-positive signal instead (out-of-range award, fires 0x on
  current corpus). Confirmed the Phase-2 accuracy gate still does NOT pass — this task fixed the
  threshold plumbing/honesty, not the underlying accuracy: mark_accuracy_theory 85.7% is really a
  marking defect (A-marks awarded without checking the final numeric value), which is a future
  accuracy task, not a thresholds task.
- Next: P2.3 step 7 — source real 0580/0606 past papers + mark schemes (required per D2.2 for
  statistical power, not optional/deferred). After that, consider whether the A-mark
  final-value-verification fix belongs inside P2.3's closure or as an explicit follow-up before
  moving to P2.4 (plagiarism/AI-detection flags).

## 2026-08-04 — Phase 2, P2.3 sub-step 5 (live calibration batch) + Opus escalation for step 6
- Did: resumed on a clean tree (no wip commit needed). Verified environment (`lemely doctor`
  all green, gemini_reachable=true) then ran the live-Gemini `measure-accuracy` batch against
  the 4 committed golden fixtures (P2.3 sub-plan step 5). All calls hit the disk cache from an
  earlier live run — genuinely-real Gemini data, zero incremental spend (cumulative_usd stayed
  0.0102). Gitignored the timestamped results dir output (regenerable artifact).
- Learned: current confidence scores do NOT separate correct from wrong marks at this fixture's
  scale — the 3 disagreements (all the same method-mark off-by-one failure mode) score
  0.85/0.98/0.98, directly overlapping 19 correct answers scored 0.98-1.00. Traced THREE
  independent, only-coincidentally-equal threshold values in the codebase (escalation trigger in
  config.py, a hardcoded-duplicate 0.80 literal in correction_ai.py that actually drives the
  harness's flag metrics, and the real DB review-queue gate in attempt_repo.py at 0.90) — none of
  which currently satisfies the Phase-2 gate ("100% of disagreements below review threshold").
  This is squarely the MISSION §5 Opus-reserved "marking-confidence + review-threshold design"
  item, so did not decide it on Sonnet.
- Next: escalated via `next_run_model: opus` in STATE.md with a full brief (three-threshold
  landscape with file:line refs, the overconfidence finding, and the exact questions to resolve
  + record as D2.2) written into the P2.3 sub-plan. Opus run should decide+fix+retest, then
  continue to step 7 (0580/0606 sourcing, bundled into the same decision) and P2.4+.

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

## 2026-08-04 (resumed session — P2.3 step 7 verify+commit, D2.3, marking-fix identified)
- Resumed on a dirty tree carrying the prior session's un-committed step-7 output (dispatched
  two data-engineer subagents for 0580/0606 fixtures, then died before verify/commit). Verified
  before trusting: read page 1 of all 4 sourced PDFs via pdfplumber — genuine Cambridge 0580/22
  and 0606/12 (May/June 2023) headers, not fabricated; validated all 6 mark_scheme.json against
  MarkScheme; spot-checked answer points against fixture content. Found and fixed a real latent
  bug the dispatch surfaced: 0580 had no SubjectProfile registered in lemely/io/det/profiles.py,
  so it silently fell through to _DEFAULT_PROFILE (paper 1 → MCQ) — wrong, 0580 has no MCQ
  component at all. Added the correct profile + fixed a comment that had asserted otherwise.
- Ran the mandatory D2.2 revisit: full measure-accuracy across all 10 golden fixtures (n=68,
  up from n=29). Recorded as D2.3. Metrics got WORSE with more data (mark_accuracy 89.7%→80.9%,
  theory 85.7%→78.3%), confirming D2.2's diagnosis far more strongly than the thin Physics-only
  sample could: no non-degenerate confidence threshold (below the already-rejected 0.99
  flag-everything case) gets close to the §4 100%-disagreements-flagged target. Kept
  REVIEW_CONFIDENCE_THRESHOLD at 0.90 — the data doesn't support moving it. Gemini spend +$0.015
  (cumulative $0.0502/$8.00).
- Learned: local Supabase stack cannot be restarted this session — `supabase/.temp/
  start-secrets/supabase_db_Lemely/` has root-owned directories from a prior crashed container
  that a non-privileged shell cannot rm -rf (recursion needs write access to the root-owned dirs
  themselves, not just their parent). Needs a session with sudo/docker-group cleanup rights.
  DB-integration tests keep skipping locally until then; not a regression, CI is unaffected.
- Also: accidentally echoed the live GEMINI_API_KEY into a debug command's output this session —
  flagged to the user immediately and recommended rotating it. Lesson for future sessions: never
  `env | grep` or `cat` a file known to contain a live secret; check presence via a boolean
  (`bool(settings.gemini.api_key)`) instead.
- Next: P2.3 step 8 — the marking-quality fix (verify the final numeric/algebraic value before
  awarding an A mark on partial-credit theory questions; two approaches sketched in STATE.md).
  This is the last blocker on P2.3's accuracy gate. Re-run measure-accuracy after the fix and
  redo the threshold sweep once more before declaring P2.3 done.

## 2026-08-04 (resumed session — P2.4 verify+commit)
- Resumed on a dirty tree carrying the prior session's un-committed P2.4 implementer output
  (plagiarism/AI-detection advisory-flag wiring). Verified before trusting: read the full diff
  against the recorded PLAN in STATE.md (matched exactly), confirmed `IntegritySettings`/
  `settings.integrity` actually exist via tokensave search, reviewed the new tests for
  substance (not just coverage padding — they assert on flag values, review_reason content,
  marks untouched, independent multi-reason review-queue rows, opt-in Gemini non-call).
  Ran all gates fresh: ruff/format/mypy/lint-imports clean, pytest exit 0 (0 FAILED/ERROR,
  82.04% cov locally — DB-integration tests still skip per the known Supabase-down issue, CI
  unaffected), pre-commit --all-files clean. Committed d31a5ba.
- Noted a gap: `scripts/check.sh` (mandated by MISSION Phase-0 + referenced throughout §8b as
  THE gate command) does not exist on disk despite Phase 0 being marked done. Logged in
  STATE.md as non-blocking opportunistic cleanup, not chased down this session to stay
  focused on P2.4→P2.5 momentum.
- Next: P2.5 — upload path (plain file upload + PWA camera capture → client-side multi-page
  PDF assembly → Supabase Storage → backend job); wire storage bucket + signed access.

## 2026-08-04 (resumed session — P2.5 verify+finish+commit)
- Resumed on a dirty tree carrying the prior session's PARTIAL, uncommitted P2.5 implementer
  output: `lemely/io/storage.py` + `tests/storage_fakes.py` (untracked) and edits to
  `runtime/config.py`/`web/deps.py`/`web/upload_utils.py`. Verified before trusting: read the
  diffs against the recorded PLAN — steps 1-3 (StorageSettings, StorageBackend/
  HttpStorageBackend, FakeStorageBackend, get_storage_backend singleton, check_upload_cap
  extraction) matched exactly and were sound; steps 4-6 (student.py router wiring, tests) had
  NOT been started — `student_upload`/`student_correct` still used local-disk paths, storage.py
  had no callers.
- Completed the unit: wired `student_upload` + `student_correct`'s `run()` closure to the
  `StorageBackend` (object key `uploads/{user_id}/{paperId}/{filename}`; `run()` downloads into
  a `tempfile.TemporaryDirectory`). Found and fixed a design gap in the recorded PLAN itself
  before writing code: the PLAN only described downloading the scan, but `student_upload` has
  always accepted an optional sibling mark-scheme upload that `resolve_mark_scheme` finds via a
  same-directory disk check — downloading only the scan would have silently dropped that
  feature. Added `StorageObjectNotFoundError` (shared between `HttpStorageBackend`'s 404 path
  and `FakeStorageBackend`, moved out of test-only scope) so `run()` can download the sibling
  when present and skip cleanly when not. Recorded both this and the "no hermetic
  HttpStorageBackend test — mirrors HttpGoTrueBackend's live-skip-only precedent, verified via
  grep before assuming a pattern existed" deviation in D2.6's completion note.
- Also caught a test-fixture bug before running anything: the first draft of the
  `get_storage_backend` override used `lambda: FakeStorageBackend()`, which would have handed
  every request a FRESH empty fake instead of the shared one the `upload_repo`/`attempt_repo`
  overrides use — silently breaking the upload→correct flow (upload writes to instance A,
  correct reads from instance B). Fixed to close over one shared instance, same pattern as the
  existing overrides.
- Ran full gates fresh: ruff/format/mypy(clean, 0 errors)/lint-imports all clean; pytest exit 0,
  0 FAILED/ERROR, 49 skipped (Postgres/Supabase-live only — stack still down, confirmed sudo is
  also unavailable in this sandbox so the root-owned `.temp/start-secrets/` cleanup from prior
  sessions' notes still can't be done here either), coverage gate (70%) passed at 81.45%.
  Committing on `feature/phase-2-core-loop`.
- Next: P2.6 — Frontend API foundation (resurrect `web/src/lib/api.ts` + `@tanstack/react-query`,
  typed hooks, deviceId-minting auth per D1.11, verify the Vite proxy end-to-end).

## 2026-08-04 (P2.6 — frontend API foundation)
- Resumed on a clean tree (P2.5 was the last commit, already merged/pushed). No wip commit
  needed. Read STATE/DECISIONS/MISSION, confirmed next non-done task was P2.6.
- Scoped and recorded a PLAN in STATE.md before dispatch (committed separately, 8c872fb):
  session storage + deviceId minting (D1.11), bearer-header wiring in api.ts, an AuthContext
  wrapping the 4 auth endpoints as react-query mutations, a RequireAuth route guard, and one
  minimal Login screen — foundation only, no existing screens touched (student/data.ts and
  teacher/data.ts stay mock until P2.7/P2.8 by design).
- Dispatched to `implementer` (Sonnet); verified independently rather than trusting its report:
  re-ran typecheck/lint/build myself (all clean), and separately started uvicorn + vite and
  curled through the Vite proxy myself — confirmed otp/request 200, malformed login 422,
  well-formed login 401 on the (already-documented, still-down) Supabase dependency. Matched
  the subagent's claims exactly. Also confirmed the `AuthProvider` addition to main.tsx (not
  spelled out in the plan's literal text) was a correct, necessary deviation, not scope creep.
- Local Supabase stack is still down this session — same root-owned `.temp/start-secrets/`
  issue, sudo still unavailable in this sandbox. Unchanged, not re-investigated further (already
  documented, needs a session with root access).
- Committed (9ea2662) and pushed to feature/phase-2-core-loop. ntfy sent (6/10 P2 tasks done).
- Checkpointing here per MISSION §5 context hygiene — clean phase-task boundary, and P2.7 (the
  next task) is a large multi-screen migration MISSION explicitly calls for a workflow on;
  better started fresh than mid-context.
- Next: P2.7 — Student surface on real data, screen-by-screen (Overview, Subject, PaperResult,
  CorrectPaper, Onboarding/StudyPlan/Standings), deleting student/data.ts incrementally. Mission
  explicitly suggests a workflow for this fan-out; keep each workflow under ~30 agents and
  checkpoint to disk after each run.

## 2026-08-05 — PHASE 2 COMPLETE
- Did: resumed on a dirty tree carrying a prior (session-limit-killed) session's uncommitted
  P2.10 WIP (playwright.config.ts, correct-paper.spec.ts, 2 screenshots) — verified rather than
  trusted: ran the E2E suite myself (genuinely passes against the live stack), independently
  confirmed via a direct Postgres query that each run persists a real Attempt+8 QuestionResults+
  5 ReviewQueueItems matching the UI. Re-ran every §6 gate myself (web typecheck/lint/build;
  backend ruff/format/mypy/lint-imports; full pytest with live Supabase keys — 609 passed, 0
  failed, 86.38% cov). Wrote reports/phase-2/REPORT.md covering all of P2.1-P2.10 with the two
  honest carried limitations (accuracy gate 83.8%<95%, D2.5; PWA Lighthouse/camera untestable,
  P2.9) stated plainly. Merged feature/phase-2-core-loop → develop (--no-ff), pushed. Updated
  the existing rolling develop→main PR #3 (title/body extended for Phase 2, not a duplicate)
  — NOT merged. ntfy phase-complete sent. Pruned STATE.md's Phase 0/1/2 detail to summary lines
  per MISSION §8b (rationale preserved in DECISIONS.md + the phase reports) and stubbed a
  Phase 3 checklist from MISSION §4.
- Learned: this sandbox's `pytest -q` (this repo's exact config) never prints the trailing
  "N passed in Xs" summary line even with --collect-only — cause not chased down (not blocking),
  worked around by counting the dot/`s` progress characters directly. Also: 3 of 4 live-skip
  tests skip in a full-suite run despite exported keys but pass individually in isolation — an
  env-var-visibility ordering quirk somewhere in the suite, pre-existing, non-blocking, not
  investigated further this session.
- Next: Phase 3 — Teacher + Parent surfaces. Branch `feature/phase-3-teacher-parent` from
  develop. Start by expanding the MISSION §4 Phase 3 paragraph into a step-by-step checklist
  (same pattern as Phase 1→2) before dispatching implementation. Carried backlog: D1.9 CLI/
  Gradio history migration, D1.6 teacher per-tenant ownership (this phase's class model is
  where it lands).

## 2026-08-05 — Phase 2.5 started: tokens + component library (P2.5.1, P2.5.2)
- Did: resumed on a dirty STATE.md (prior session's Phase-2.5 checklist wip, committed as-is);
  verified environment (node 26.6, python 3.13.5, all 4 design skills present) and DESIGN.md/
  PRODUCT.md/UI-spec/QUALITY-BAR.md (no placeholders). Dispatched scout to read the full
  71-screen/13-component UI spec and cross-check against shipped Phase-2 screens — no conflict,
  scope fixed to tokens+C-1..C-13+6-screen retrofit only, recorded as D2.10 (the other ~60
  screens are Phase 3/4/5, not this phase). Built P2.5.1 (web/src/index.css token layer,
  DESIGN.md hex palette replacing the pre-DESIGN.md OKLCH port under the same var names) and
  P2.5.2 (all 13 cross-cutting components, two parallel worktree-isolated designer agents,
  merged with zero file conflicts, docs/COMPONENT_CATALOGUE.md written). Both verified together
  (tsc/build/oxlint clean) and committed on feature/phase-2.5-design-system.
- Learned: Phase 2's token file (web/src/index.css) predated DESIGN.md entirely — an ad-hoc
  OKLCH port from an earlier design mock — confirming the retrofit step is real, necessary work,
  not busywork. Two pre-token-system components (viz.tsx::Bar, BoundaryRail.tsx) duplicate new
  C-3/C-8 and should be deleted in the retrofit. Worktree isolation for parallel component-file
  builds works cleanly when file ownership is split with zero overlap up front.
- Next: P2.5.3 — retrofit the 6 shipped Phase-2 screens (home, upload/scanner, marking
  progress, results, question detail) onto the new tokens + C-1..C-13, deleting the two
  superseded ad-hoc components. Then P2.5.4 Impeccable pass, P2.5.5/6 screenshot+audit harness,
  P2.5.7 check.sh gates, P2.5.8 quality-bar pass, P2.5.9 report+PR+ntfy.

## 2026-08-05 — Phase 2.5: P2.5.3 screen retrofit
- Did: resumed on a clean tree at P2.5.3. Dispatched one `designer` agent to retrofit
  Overview.tsx (home), CorrectPaper.tsx (upload/scanner/marking-progress — S-14 now uses
  ProcessingState C-10 with 3 real SSE-backed stages instead of a scrolling log), and
  PaperResult.tsx (results/question-detail — QuestionRow C-6, ConfidenceIndicatorSummary,
  BoundaryBar C-3) onto the token layer + C-1..C-13, and to delete the two superseded
  components (viz.tsx::Bar, BoundaryRail.tsx) called out in the catalogue's follow-ups.
  Directions.tsx (out of retrofit scope) needed a minimal import-only fix since it also
  imported BoundaryRail. Orchestrator-verified independently before committing: re-ran
  tsc/build/oxlint myself (all clean), read every diff line-by-line, grepped for stray
  oklch()/leftover imports. Committed 16cb17d.
- Learned: the retrofit surfaced a real pre-existing bug, not just styling debt —
  PaperResult was rendering plagiarism/AI-detection flags directly to students, violating
  QUALITY-BAR.md's teacher-only-integrity-flags rule. Fixed as part of the same commit.
  Also surfaced genuine content/data gaps (no real per-grade boundary thresholds on
  ResultDTO, no SSE signal for 2 of S-14's 5 stages or a live question count, S-15's
  comparison/mistakes/weak-topic-chips have no backing data) — recorded in STATE.md and
  the commit body, not fixed (backend/DTO work, out of this phase's scope).
- Next: P2.5.4 — Impeccable audit → normalize → polish pass on the same 4 touched screens
  (per MISSION §10 command sequence). Then P2.5.5/6 screenshot+audit harness, P2.5.7
  check.sh gates, P2.5.8 quality-bar pass, P2.5.9 report+PR+ntfy.

## 2026-08-05 — Phase 2.5: P2.5.4 Impeccable audit + polish
- Did: resumed on a clean tree at P2.5.4. Found the installed Impeccable skill (v4.0.4)
  has no `normalize` command — recorded D2.11 (audit's Theming dimension + polish's drift
  triage cover the same ground) rather than stalling. Dispatched one `designer` agent to
  run audit→polish on Overview.tsx, CorrectPaper.tsx, PaperResult.tsx (Directions.tsx
  audited only, confirmed 0 regressions from its P2.5.3 import-only fix). Fixed: 9 missing
  h1/live-region/label/aria-pressed a11y gaps, exact and nearest-canonical token swaps,
  and Overview's subjects table (fixed-width grid columns overflowing below 380px)
  rebuilt mobile-first. Orchestrator-verified independently: read every diff, re-ran
  tsc/build/oxlint myself, checked token values against index.css, checked the portal
  shell for h1 duplication. Committed.
- Learned: `pre-commit run --all-files` is unsafe in this repo — its formatting hooks
  (ruff-format, trailing-whitespace, end-of-file-fixer) reformat vendored third-party
  content under `.claude/skills/` that's tracked in git but was never meant to be linted
  (last touched in d83aa67, the original "design stack" commit, never since). Reverted
  that scope creep and ran `pre-commit run --files <changed files>` instead — scope
  pre-commit to the actual diff, not --all-files, in this repo from now on.
- Next: P2.5.5 — Playwright screenshot harness (screen × state × breakpoint, ID
  convention from LEMELY_UI_SPEC.md). Then P2.5.6 Puppeteer audit runner + contact sheet,
  P2.5.7 check.sh UI gates, P2.5.8 full quality-bar grep pass (note: grep already shows
  real pre-existing arbitrary-spacing drift across all 4 screens beyond hex/exact-token
  matches — e.g. Directions.tsx's `text-[34px]`/`gap-[26px]`-style values that don't map
  to index.css's spacing scale or Tailwind's 4px default scale; P2.5.8 owns resolving
  this, not deferred silently), P2.5.9 report+PR+ntfy.
