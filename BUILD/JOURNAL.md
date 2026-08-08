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

## 2026-08-05 — Phase 2.5: P2.5.5 Playwright screenshot harness
- Did: resumed a session that had died mid-P2.5.5 (STATE.md said a `visual-qa` agent was
  "running" but no task was actually tracked). Found `web/e2e/screenshots.spec.ts` and 24
  of an expected 30 screenshots already on disk, uncommitted. Verified rather than trusted
  before committing (MISSION delegation protocol): ran the suite myself against the live
  Supabase stack. It failed, exposing two real bugs in the harness (not the app): (1)
  React.StrictMode double-invoking the mount effect aborts the first overview fetch on
  reload, so the delayed-route handler simulating the loading state threw "Route is
  already handled!" when its `continue()` finally fired — wrapped in try/catch, benign;
  (2) the zero-console-errors assertion caught the browser's own "Failed to load
  resource: 500/413" logging from the two states this suite deliberately simulates as
  failures — excluded that one message pattern from the watcher, still catching real app
  errors. Fixed both, re-ran: 6/6 screenshot tests green, all 30 PNGs captured, full E2E
  suite green (8/8, no regression to _smoke/correct-paper), tsc/build/oxlint clean,
  pre-commit scoped to the changed spec file clean. Reverted two Phase-2 baseline PNGs
  that a full-suite run regenerated as a side effect (out of scope). Committed.
- Learned: a STATE.md line claiming a background agent is "running" does not mean it
  still is — TaskList showed nothing tracked, meaning the session that wrote that line
  died before finishing. Always verify by actually running the deliverable, not by
  reading the last-known status.
- Next: P2.5.6 — Puppeteer audit runner (axe-core, Lighthouse, console errors, full-page
  captures) + contact-sheet generator; commit baselines.

## 2026-08-05 — Phase 2.5: P2.5.6 Puppeteer audit runner
- Did: resumed on a dirty tree — a prior session had left `web/scripts/audit.mjs` plus
  package.json/vite.config.ts changes on disk, uncommitted, with output for only 2 of 4
  routes (died mid-run). Verified rather than trusted (MISSION delegation protocol): ran
  it myself, and it failed on route 3 with a real script bug — `waitForText(page, "out
  of")` checks `document.body.innerText`, but the "N out of M marks" string only exists
  in MarkDisplay's `aria-label` (visible text is "5/8"), which `innerText` never sees; it
  had only worked on routes 1-2 by coincidence of what text was actually visible there.
  Fixed to wait on `[aria-label*="out of"]` directly (matches Playwright's `getByLabel`
  used for the same assertion in screenshots.spec.ts). Re-ran clean end-to-end against
  the live Supabase stack: all 4 in-scope routes (G-04 login, S-10 correct-entry, S-15/
  S-17 result, S-06 overview) audited with axe + Lighthouse, screenshots captured for
  G-04 (the one route with no existing Playwright capture, 9 PNGs), contact sheet
  regenerated (39 thumbnails, 5 screen dirs). tsc/build/oxlint
  clean, pre-commit scoped to the 3 changed source files clean, 0 console errors across
  the whole run. Committed.
- Learned: Lighthouse 13.4.1 (the pinned version) has no PWA category at all — Google
  removed it upstream around v11/v12, confirmed by reading the installed package source,
  not assumed. Audited performance/accessibility/best-practices/seo instead and recorded
  the gap in the script's own header rather than silently dropping the requirement. Also:
  a subagent's on-disk work with no STATE.md task entry and no TaskList record cannot be
  assumed complete OR assumed abandoned — the only way to know is to run it.
- Real findings, deliberately not fixed here (P2.5.8's job, not P2.5.6's): Lighthouse
  accessibility 95-100 across all 4 routes (gate met). Axe: login has 3 moderate
  landmark/heading violations (bare pre-auth shell, no `<main>`/h1); the 3 authenticated
  routes each carry 1-2 **serious** violations from shared-shell components — the
  `text-t3` muted-label color (#7e6865) measures 4.45:1, just under the 4.5:1 AA
  threshold, on every subject-card caption/nav label; student-overview's mastery
  progress bars (`role="progressbar"`) have no accessible name. All pre-existing gaps in
  shared components (not new regressions), now measured for the first time because this
  is the first working run of a tool that can measure them. Zero serious/critical axe
  violations is a phase-level acceptance criterion (MISSION §4) — flagged in STATE.md as
  a P2.5.8 blocker, not silently dropped.
- Next: P2.5.7 — extend scripts/check.sh with the UI gates (axe/Lighthouse/impeccable
  detect). Then P2.5.8 (full QUALITY-BAR.md pass — must resolve this session's axe
  findings), P2.5.9 (report + PR + ntfy).

## 2026-08-05 — Phase 2.5: P2.5.7 scripts/check.sh (the gate command that never existed)
- Did: `scripts/check.sh` did not exist on disk at all — noted as a non-blocking gap back
  on 2026-08-04, never chased down since. Built it from scratch per MISSION §8b/§11:
  backend gates (ruff check/format, mypy, lint-imports, pytest) and web gates (typecheck,
  oxlint, build, `npx impeccable detect src/`) always run; Playwright E2E, `npm run audit`
  (P2.5.6), and a new `scripts/check_ui_gates.py` (parses the audit's `_summary.json`
  files, enforces QUALITY-BAR.md's zero-serious/critical-axe + Lighthouse-a11y≥95
  thresholds) run only when the local Supabase stack answers `supabase status`, SKIPping
  (not failing) otherwise. Output format matches the §8b mandate: suppress passing
  output, print failures + one PASS/FAIL/SKIP line per tool + a final summary.
- Learned (D2.13): building it surfaced a real, pre-existing, unrelated bug — plain
  `ruff check .` (the exact command `.github/workflows/ci.yml` runs) reports 329 errors,
  328 of them inside vendored `.claude/skills/ui-ux-pro-max/scripts/` content that was
  never excluded from `pyproject.toml`'s ruff config. D2.11 (2026-08-05, P2.5.4) had
  already fixed this exact problem for `pre-commit run --all-files` but nobody connected
  it to plain `ruff check .`/CI, because nobody had run that exact command against this
  branch since the skill pack landed in d83aa67. CI's `ruff check .` step has very likely
  been red on this branch since then. Fixed by adding `.claude` to `extend-exclude` — a
  config change, so it fixes CI without touching `ci.yml`. General lesson: "STATE.md says
  CI was green" is a historical fact about a specific past commit, not a standing
  guarantee — verify the actual gate command against the actual current tree before
  trusting it, especially after any commit that adds a new top-level directory.
- Verified: full `./scripts/check.sh` run — everything PASS except `ui-thresholds`, which
  correctly FAILs on exactly the 3 axe findings P2.5.6 recorded (not a new problem, the
  gate working as designed). Committed.
- Next: P2.5.8 — full QUALITY-BAR.md pass. Must turn `ui-thresholds` green (login
  landmarks, shared-shell color-contrast, overview progressbar labels) plus the grep-based
  stray hex/spacing sweep. Then P2.5.9 (phase report + contact sheet + PR + ntfy).

## 2026-08-05 — Phase 2.5: P2.5.8 full QUALITY-BAR.md pass
- Did: dispatched one `designer` agent with a precise brief (exact files/lines for the 3
  axe violations, the full grep-sweep file list, explicit per-category guidance for
  spacing vs. typography vs. line-height/ch-unit values, and a 5-step self-verification
  checklist including re-running `npm run audit` and `scripts/check_ui_gates.py`).
  Orchestrator-verified independently before trusting (MISSION delegation protocol): read
  every source diff, re-ran tsc/build/oxlint/`npx impeccable detect`/pre-commit myself,
  re-ran `npm run audit` myself (fresh axe 0/0/0/0 on all 4 routes, Lighthouse a11y
  100/100/100/100, confirmed independently of the agent's own numbers), re-ran the grep
  sweep myself (only the 2 documented `ch`-unit exceptions remain), and visually spot-
  checked several regenerated screenshots. Also ran `npm run test:e2e` afterward (not
  requested by the brief) to refresh the 30 Playwright-owned phase-2.5 baselines against
  the new tokens, since the color/radius/spacing changes made the existing ones stale
  evidence for the phase report — 8/8 green, no regression. Reverted 2 incidentally-
  regenerated Phase-2 baseline PNGs (same known side effect as P2.5.5). Committed.
- Learned (D2.14): the agent's own fix — re-mixing `--t3`, adding `Meter`'s `label` prop,
  `<main>`/`<h1>` on Login — introduced a real, separate, self-caught bug along the way:
  naming new composite classes `.text-button-text-sm/-lg` silently broke `tailwind-merge`,
  which buckets any unrecognized `text-*`-prefixed class into its default text-color
  conflict group and evicts the real color utility with no error anywhere in the
  toolchain (build/lint/types all pass). Only the agent's own `npm run audit` re-run
  catching a *new* serious color-contrast violation on Login's button surfaced it before
  it shipped. Renamed to `.btn-text*`. General lesson recorded in DECISIONS.md: never
  name a custom composite utility class starting with a string tailwind-merge treats as a
  real Tailwind group prefix (`text-`, `bg-`, `p-`, `gap-`, ...) unless it IS that exact
  utility — verify empirically with `twMerge()` when in doubt, not by eye.
- Phase 2.5's content work is now done: tokens (P2.5.1), component library (P2.5.2),
  screen retrofit (P2.5.3), Impeccable polish (P2.5.4), Playwright screenshot corpus
  (P2.5.5), Puppeteer audit runner (P2.5.6), the gate command (P2.5.7), and now a clean
  QUALITY-BAR pass (P2.5.8) with zero serious/critical axe violations and Lighthouse a11y
  100 across all 4 in-scope routes.
- Next: P2.5.9 — phase report (`reports/phase-2.5/REPORT.md`) + contact sheet (already
  regenerating correctly via both `npm run audit` and `npm run test:e2e`) + `develop`
  merge + `gh pr create` (develop→main) + ntfy. This is the last task in Phase 2.5.

## 2026-08-05 — Phase 2.5: P2.5.9 milestone report + merge — Phase 2.5 COMPLETE
- Did: ran the full `./scripts/check.sh` one more time at HEAD to confirm every gate
  passes before merging (all PASS, 0 skipped — reverted the incidental report-artifact
  noise it regenerated, same known side effect as every prior audit/e2e re-run this
  phase). Wrote `reports/phase-2.5/REPORT.md` covering all 9 tasks, the MISSION §4
  acceptance checklist (every item met, none silently worked around), test/coverage
  summary, gate evidence, D2.10-D2.14, screenshots, and known limitations carried
  forward unchanged from Phase 2 (accuracy gate, PWA live-test). Committed, fast-forward
  merged `feature/phase-2.5-design-system` → `develop` (fcc3e07), pushed. Pruned
  STATE.md's ~200-line Phase 2.5 task log to a single summary paragraph per MISSION §8b
  (the detail survives in git history + the phase report, not duplicated here).
- Learned: `git push origin develop` surfaced a GitHub Dependabot notice — 18
  vulnerabilities (15 high, 3 moderate), almost certainly transitive deps pulled in by
  this phase's new devDependencies (puppeteer/lighthouse/axe-core, added back in
  d83aa67's "design stack" commit, first actually installed+used this phase). Not
  triaged this session — MISSION has no dependency-vulnerability gate, and doing so
  properly (checking which are transitive-only vs. reachable, whether upgrades break
  the pinned Lighthouse/Puppeteer versions the audit runner depends on) is its own task.
  Flagging here rather than silently ignoring it; worth a dedicated look before ship
  (Phase 6 hardening, or sooner if any high-severity one is directly reachable).
- Phase 2.5 is COMPLETE: all 9 tasks done, every MISSION §4 acceptance criterion met
  (grep-clean token/spacing sweep, full component catalogue, zero serious/critical axe,
  Lighthouse a11y 100 across all 4 routes, 39-screenshot corpus + contact sheet
  committed). `current_phase` in STATE.md advanced to 3.
- Next: Phase 3 — Teacher + Parent surfaces. Branch `feature/phase-3-teacher-parent` from
  `develop`. Read MISSION §4's Phase 3 section (class management, at-risk flagging,
  review-queue override-and-annotate, teacher quiz builder, parent portal with mock
  phone-OTP) plus the carried backlog items (D1.6 teacher per-tenant ownership, D1.9
  CLI/Gradio history migration) before starting task breakdown.

## 2026-08-06 — P3.1, P3.1b, P3.2 (Phase 3, tasks 1–2 of 11)

- Did: **P3.1** — the real class model (D3.1). `lemely/db/class_repo.py` (`ClassService`,
  modelled on `SeatService`), migration `0004_class_model`, `lemely/web/routers/classes.py`.
  This finally closes the tenancy hole D1.6 has carried since Phase 1: `GET
  /api/teacher/classes` used to treat *every* student with history as one cohort keyed
  `"all"`. Teacher → own classes; school_admin → their school's; platform_admin → none.
  Out-of-scope access is 403 not 404, so the endpoint isn't an existence oracle.
- Did: **P3.2** — the at-risk engine (D3.3). `lemely/core/at_risk.py`, pure, injected clock,
  three OR'd rules each carrying reason + evidence. Replaced a heuristic that matched none
  of MISSION's three rules.
- Learned (the useful one): **the visual-regression gate was vacuous and had been since
  P2.5.6.** `audit.mjs`, both Playwright specs and `check_ui_gates.py` all wrote into the
  *committed* phase baselines, so every `check.sh` run overwrote the reference it compares
  against — "no unintended visual regression" could never fail. It surfaced only because
  P3.1 is backend-only and still dirtied 53 PNGs. Fixed in **P3.1b** behind
  `LEMELY_REPORT_DIR` → gitignored `reports/.scratch`; re-baselining is now explicit and
  names its phase. Worth remembering as a class of bug: a check that mutates its own
  oracle always passes.
- Learned: `classes.school_id` was `NOT NULL`, making an independent teacher's class
  unrepresentable even though MISSION §1 requires independent teachers. Relaxed it — a
  deliberate, recorded exception to D1.2's additive-only rule (no row invalidated, no
  backfill, reversible).
- Honest limitation carried forward: at-risk rule 2 (predicted ≥2 grades below target) is
  implemented and unit-tested but **cannot fire in production** — no target-grade column
  until P4's onboarding questionnaire. The engine reports it as *not evaluable*, never as
  a pass. Must appear in DELIVERY.md.
- Also: the two subagents both stalled waiting on background runs rather than reporting;
  verified and finished both myself. Worth briefing future agents to run gates in the
  foreground.
- Next: **P3.3** teacher analytics (per-class/per-student, ranked weakness topics for the
  T-04 heatmap, grade distribution, trend series). Branch pushed at 82d60dd.

## 2026-08-06 — P3.4 closed out, P3.4b shipped, P3.5 designed and started

**Did.** Committed the in-flight P3.4 follow-up (a teacher override recomputed the
attempt total but left weakness records at the AI's values, so a restored question
still read as a weakness on the student's list and the T-04 heatmap — now both run
one extracted `group_weak_areas`). Shipped **P3.4b**, the last open P3.4 item:
at-risk flag acknowledgement (T-06, D3.5). Commissioned and recorded the **P3.5
design** (`docs/quiz-model.md`, D3.6) and built its chunk C, `lemely/core/difficulty.py`.

**Learned.** Two things worth not re-deriving. (1) At-risk flags are *derived per
request*, never stored, so "dismiss this flag" has no row to point at — the ack has to
reference the evidence instead, which is what makes it re-raise when the student
declines further rather than becoming a permanent mute. Fingerprinting on
`last_active_at` and not `days_inactive` is load-bearing: the latter increments daily
and would silently un-acknowledge every inactivity flag overnight. (2) There is no quiz
persistence in this codebase at all — the existing `/quizzes/*` routes build an
ephemeral preview and save nothing — and T-09's promised *live count* of matching
questions cannot be served from on-disk JSON, so a real `question_bank` table is
unavoidable rather than a nice-to-have. Today's disk-scan pool is also a tenancy hole.

**Watch.** D3.6 risk 2 is the sharp one: P3.4's `_recompute_attempt_totals` assigns
`grade`/`boundary_source` unconditionally, so the first teacher override on a quiz
attempt would invent a grade the marking path deliberately never wrote. Chunk F must
guard it and test the guard. Chunk G must land before F, not after.

**Next.** P3.5 chunk A (migration 0007 + ORM models), then G, then B — and B starts
with a measurement of past-paper ingest yield before anything is persisted, because a
genuine zero-count is an acceptable product answer but only if found early.

## 2026-08-06 — P3.5 chunks A + G

**Did.** Chunk A (0cedc1b): migration `0007_quiz_model` + six quiz tables + seven enums +
`attempts.origin`, schema only. Verified on the live stack — upgrade → downgrade → upgrade
with `alembic check` clean both ways, not just "it applied". Chunk G (60668ea): the
grade-bearing/topic-bearing split from `docs/quiz-model.md` §5, landed as one predicate
before any quiz attempt can exist. 1519 tests / 87.48% cov, all 12 gates green.

**Learned.** Three things worth not re-deriving. (1) The test counts recorded for
P3.1–P3.4b were guesses — `pytest -q` here emits no `N passed` summary line, so the real
count comes from counting progress characters; it was 1485 at chunk A, not 826. Method is
now written into STATE. (2) Bumping `HISTORY_SCHEMA_VERSION` is not free: because
`StudentHistory.schema_version` defaults to the *current* version, a pre-versioning file
silently relabelled itself v2 and stopped being detectable as old. The loader already
resolved absent-means-1 for its own guard and then threw that away at `model_validate`.
(3) `is_grade_bearing` bundles origin AND grade-validity, so applying it naively to
`grade_distribution` was not the no-op it looked like — it turns "latest paper unreadable →
no standing to report" into "fall back to the older, better grade".

**Watch.** The §5 table only covers `lemely/core/`. Eight web-layer sites
(`classes.py:125,187`, `teacher.py:1090,1300-1301,1541`, `student.py:144-193,263,280`)
derive a grade or percentage claim straight off `history.records` and are still unfiltered
— harmless until F, live corruption the moment F writes the first quiz attempt. The exact
list is in STATE as a chunk-F prerequisite.

**Next.** Chunk B — the riskiest. Start with the measurement (rows produced / skipped for
missing prompt text / topic coverage) and report it before persisting anything; a genuine
zero-count is an acceptable answer, a late-discovered one is not.

## 2026-08-06 — P3.5 chunk B: the measurement came back zero, and that is the answer

**Did.** Ran the mandated chunk-B measurement before writing any persistence, and it
settled the chunk's scope: 122 leaf questions across the entire 4-mark-scheme corpus,
**0 with prompt text, 0 with a topic hint**. Recorded as D3.7 and committed on its own
(0184701) before implementing, so the finding survives a session death independently of
the code. Then shipped `lemely/db/question_bank_repo.py` (82cafb9): `visible_bank_filter`,
`QuestionBankService.count_by_band`/`.select_questions` over one shared `_filters()`,
`import_generated_quiz_files`, `survey_past_paper_questions`, and a `lemely question-bank`
CLI. 1537 tests (1533 passed / 4 live-only skips), 87.83% cov, repo file 100%, all 12
gates green, `alembic check` clean.

**Learned.** The zero is structural, not a data-quality gap, and that distinction changed
what got built. `loose_schemas.Question` has no question-stem field *at all* — not an
unpopulated one, an absent one — because a CAIE mark scheme document contains marking
points and the stem lives in the question paper, which this codebase only ever consumes as
a scanned student submission. `lemely/io/integrity.py:113` had already recorded the same
fact in a comment and worked around it. So no corpus growth or re-parse changes the number,
and the design's "create the row with `is_active = false`" was written for a *sometimes*-
missing stem: here the row can never become live, and `prompt` is NOT NULL, so persisting
would have meant inventing a placeholder into the exact column a teacher reads. The ingest
therefore ships as a survey with no write path — an unreachable persist branch is dead code
testable only by stubbing a field the schema lacks.

Two smaller ones. §2's "GeneratedQuestion maps field-for-field" cannot hold —
`GeneratedQuestion` has no `question_type` and the column is NOT NULL; it is a documented
default (`explanation`), safe only because marking branches on MCQ vs non-MCQ and generated
questions are never MCQ. And my first pass at the survey's zero-yield message asserted the
structural finding even when it had scanned nothing — a report claiming a conclusion it did
not reach. Split into two messages.

**Watch.** The bank ships **empty**, both paths at 0. That makes chunk D's
`/quizzes/generate`-writes-bank-rows the *only* thing that fills it — load-bearing, not
optional — and T-09's live count honestly reads 0 until a teacher generates questions.
Making past papers a real question source needs a question-paper stem extractor: out of
Phase-3 scope, and now a prerequisite of P4's "questions from the ingested past-paper
corpus" rather than an assumption it can make.

**Next.** Chunk D — quiz CRUD, draft PATCH, pool-count endpoint, question selection, and
`/quizzes/pools` off disk onto the bank. Build on chunk B's predicate; do not write a
second WHERE clause for the bank.

## 2026-08-06 (cont.) — P3.5 chunk D: quiz CRUD, and two defects that only appear once the disk path dies

**Did.** Shipped chunk D (d19c32d): `QuizService`, the `/api/teacher/quizzes` router, quiz
DTOs, the `pool-count` endpoint, and question selection — with `/quizzes/pools` and the
preview/generate reuse pool both moved off the process-global `output_dir/questions` scan
onto the bank behind `visible_bank_filter`. 1595 tests (1591 passed / 4 live-only skips),
88.00% cov, all 12 gates green, `alembic check` clean, no schema change.

**Learned.** The interesting part was not the CRUD, it was the second-order effect of
chunk B's decision. Moving `/quizzes/generate`'s *write* off disk silently orphaned the
*read*: `_existing_questions` kept scanning a directory that nothing writes any more, so
the reuse-before-calling-Gemini optimization would have returned nothing forever — every
preview re-generating against the $8 ceiling, the no-key degraded path returning an empty
quiz, and a docstring still describing a working pool. Nothing fails when this happens;
the tests that covered it seeded the disk themselves and kept passing, which is precisely
why they kept passing. Pointing the reuse at the bank then produced defect two: the write
path re-inserted every question it had just read, so each generate doubled the pool. The
partial unique index that makes the past-paper ingest idempotent does not cover generated
rows (no `paper_id`), so this had to be enforced in the write path — `_build_quiz` now
returns `(quiz, reused_prompts)` and only fresh questions are persisted.

Both defects share a shape worth remembering: a test that constructs the state it asserts
on (writing the pool file it then reads) proves the code path works, not that anything
still reaches it. When a data source moves, the tests that seeded the old source are the
last place the old source still exists.

**Watch.** The bank is still empty on a fresh install and `/quizzes/generate` is the only
thing that fills it, so every pool count a teacher sees before generating is honestly 0.
Chunk F's `_recompute_attempt_totals` quiz guard and the eight unfiltered web-layer
grade/percentage sites listed under chunk G remain the two known landmines.

**Next.** Chunk E — assignment endpoints, student take/submit (S-26), `quiz_answers`.

## 2026-08-06 — P3.5 chunk E (assignment + take/submit)

**Did.** Chunk E: three teacher assignment endpoints on `QuizService`, four student
endpoints on a new `student_router` in `routers/quiz.py`, and `QuizTakingService`
(`lemely/db/quiz_taking_repo.py`) scoped by enrolment via the new
`ClassService.enrolled_class_ids`. 1668 tests (1664 passed / 4 live-only skips), 88.35%
cov (from 88.00%), all 12 gates green, `alembic check` clean, no schema change.

**Learned.** S-26's "not yet open" state has no backing column and needs none — an
assignment does not exist until assigned, so the state is just a 404 (D3.8). The unassign
guard reads finer than it fires: submissions are born `in_progress`, so "refuse unless
`not_started`" is really "refuse if any row exists" — recorded honestly rather than
claiming a distinction that never triggers. Answer leakage is excluded by *field absence*
on `QuizTakeQuestionRow`, not by omitting fields at the DTO layer.

**Next.** Chunk F — `QuizMarkingService`, `persist_quiz_correction`, the shared `_persist`
refactor, review-queue integration, the `_recompute_attempt_totals` quiz guard, T-10. Also
still open: the eight unfiltered web-layer grade/percentage sites chunk G handed to F,
which must be filtered in the same commit that first writes a quiz attempt.

## 2026-08-06 — P3.5 chunk F1 (quiz marking core + the grade-bearing web-layer filter)

**Did.** F1: `AttemptRepository._persist` extracted as the single writer behind
`persist_correction` and the new `persist_quiz_correction`; `QuizMarkingService`
(`lemely/db/quiz_marking_repo.py`) adapting quiz questions through the pure
`quiz_question_to_scheme_question` into the *existing* `correct_paper`; background marking
on submit; the mandated `_recompute_attempt_totals` quiz guard. Discharged chunk G's
handed prerequisite in the same commit — every web-layer grade/percentage site now filters
(D3.9). 1703 tests (1699 passed / 4 live-only skips), 88.48% cov (from 88.35%), all 12
gates green, `alembic check` clean.

**Learned.** The §5 grade-bearing/topic-bearing split is two predicates short at the web
layer: three surfaces report a *count* that says "papers", and `is_grade_bearing` drops a
real paper whose grade failed to parse from a count that has nothing to do with grades.
Hence `is_paper` (origin only) beside it — chunk G had hit the same edge from the other
direction in `grade_distribution` and solved it locally. Also: the new tests passing first
try was not evidence they worked; reverting the three routers and confirming 16 of 18 fail
was.

**Watch.** A quiz-only student now reports `grade=""` on three teacher DTOs and 404s on
`GET /student/subject/{code}`. Both are deliberate (D3.9) and both need the *frontend* to
render them as "no paper yet" rather than as an error — that lands in P3.7/P3.8, and is
the one place this filter can still look like a bug.

**Next.** F2 — T-10 teacher class-results endpoints, then P3.6 (parent portal backend).

## 2026-08-06 — P3.5 chunk F2 (T-10 class results): P3.5 complete

**Did.** `QuizResultsService` (`lemely/db/quiz_results_repo.py`, 100% cov) plus one route,
`GET /api/teacher/quizzes/{quiz_id}/assignments/{assignment_id}/results`. All five §4.6
panels are pure projections over a single load of one assignment's submissions and their
attempts — completion vs the live roster, a percentage score distribution, per-question
analysis, per-student results, and T-04's own `rank_topic_weaknesses`. Ownership is
`QuizService.get_quiz`, scope is `ClassService.roster`; neither is re-derived. Made
`history_repo._to_record` public as `attempt_to_record` so the weaknesses panel reuses the
one attempt→`PaperRecord` projection instead of writing a second. 1721 tests
(1717 passed / 4 live-only skips), 88.75% cov. All 12 gates green, no schema change.

**Learned.** §4.6 fixes the completion *denominator* as the live roster but says nothing
about a student who submits and is then removed from the class — read literally, the
numerator can exceed the denominator. Roster-scoping everything is right, but doing only
that makes a teacher's marked work vanish with no trace, so the excluded count is reported
(`offRosterSubmissionCount`, D3.10). Separately: ruff's TC001 only moves an import when
*every* member of that statement is annotation-only, which is why a new
`from ... import A, B` in `routers/quiz.py` tripped a rule the file's existing imports never
had; the fix is the same per-file exemption every other web DI module already carries.

**Watch.** The route's per-student panel carries `marksByQuestion` for every roster
student — fine at class size, but it is the one payload here that grows with
students × questions. If a school ever assigns a 40-question quiz to a 200-student cohort
this is where to paginate first.

**Next.** P3.6 — parent portal backend (P-01..P-04): linked children, child overview /
subject detail / weaknesses read-only, notification preferences, parent-authz scoped to own
linked children only.

## 2026-08-06 — P3.6 chunk a (parent portal read surface)
- Did: fixed the P3.6 design as D3.11 (student invites a parent by phone; only an
  already-OTP-authenticated parent can be linked, so a student-supplied string is never an
  account-creation primitive), then built `ParentLinkService` + the four P-01..P-04 read
  routes + the three student link routes. Committed 3ee592c.
- Learned: `is_grade_bearing` already implies `grade in GRADE_ORDER`, so off-ladder guards
  downstream of `grade_bearing()` cannot fire from a route — cover them as preconditions,
  not with a fictional HTTP test. Same shape for `BelowTargetEvidence`: unreachable until P4.
- Learned: the subagent's work was correct but left `routers/parent.py` at 80% — the at-risk
  panel and the empty-child state were both unpinned. Verifying coverage per-file, not just
  the total, is what caught it.
- Next: chunk b — notification preferences (migration 0008, `GET/PUT
  /api/me/notification-preferences`), then P3.7 teacher frontend.

## 2026-08-06 — P3.6 chunk b (notification preferences) — P3.6 DONE
- Did: migration 0008 + `notification_preferences` (explicit boolean column per
  `NotificationType`, enum↔column vocabulary pin), `NotificationPreferencesService`, and
  `GET/PUT /api/me/notification-preferences` for any authenticated role. Committed 622a692.
  P3.6 complete; 1805 tests / 89.16% cov, all 12 gates green.
- Learned: the chunk-b subagent stalled waiting on a background run — the *same* failure
  mode STATE.md already recorded for P3.1/P3.2, and it happened despite an explicit
  "foreground, never backgrounded" instruction in the brief. Treat the brief line as
  insufficient: plan on finishing the gate run and the last coverage gaps yourself.
- Learned: per-file coverage is the useful signal, not the total. Both chunks came back
  with the total up and a new router 4-6 points short, hiding untested behaviour each time.
- Next: P3.7 — teacher frontend T-01..T-06. First frontend task since P2.5, so the standing
  UI gate (QUALITY-BAR, axe, Lighthouse, screenshot corpus, Impeccable) applies in full,
  and `LEMELY_REPORT_DIR` must name the phase when re-baselining (D3.2).

## 2026-08-06 — P3.7 complete: all six teacher screens on real data
- Did: P3.7 in four chunks. (a) Additive DTO enrichment after auditing all six T-screens
  against the DTOs meant to feed them — three gaps found before a line of UI was written
  (T-01 had no recent-activity field, T-01/T-02 no per-class weakness/activity/at-risk,
  T-03 only a bare at-risk bool where the spec demands the reason). (b) client API layer +
  T-01/T-02 + `GET /api/me/profile`. (c) T-03 roster + T-04 analytics. (d) T-05 student
  detail + T-06 at-risk list. Commits c95c52f, 3b0eb3c, e789dc7, 15738f4. 1826 tests /
  89.18% cov, 12/12 gates green throughout. D3.12 and D3.13 recorded.
- Learned, the big one: **all twelve gates were green while every at-risk acknowledge call
  500'd on any real stack.** `sa.Enum(AtRiskReason, ...)` bound the member `.name` while
  migration 0006's Postgres type holds the lowercase `.value`s. `pytest` missed it because
  the test schema comes from `create_all()`, deriving the enum DDL from the same buggy
  declaration — self-consistently wrong. `alembic check` missed it because its comparator
  doesn't diff enum labels. Only a live E2E write caught it. Closed with a structural
  metadata test over all 25 enums (D3.13). **A green suite over a `create_all()` schema is
  not evidence the column works against the migrated DB.**
- Learned: reviewing the subagent diff rather than the subagent report keeps paying. Chunk
  a had inlined a mean, leaving a D3.9 regression test guarding a function no route called;
  chunk c shipped two raw NUL bytes that made git treat a source file as binary while
  typecheck and build passed silently. Neither appeared in either agent's own report.
- Learned: `supabase` is not on PATH in a non-interactive shell, so `scripts/check.sh`
  silently decides the stack is down and skips three of the twelve gates. Always
  `PATH="$HOME/.local/bin:$PATH" ./scripts/check.sh`. Earlier "12 gates green" claims in
  this build may have been 9.
- Next: P3.8 — T-07/T-08 (review queue + remark), T-09/T-10 (quiz builder + class results),
  T-12 (announcement composer). The quiz backend is fully built (P3.5 chunks A-F2); this is
  the UI over it. Note P3.10 now carries three inherited items: the audit runner still only
  sees the 4 student routes (so the UI gate is vacuous for every teacher screen), the
  teacher portal's token-literal debt, and the absent frontend test runner.

## 2026-08-07 — P3.8 chunk b: T-07 review queue + T-08 remark on real data
- Did: resumed a session that died mid-chunk with the work written but unverified. Reviewed
  the diff rather than trusting it, ran the gates, re-seeded and re-ran the throwaway live
  verification myself (20/20), independently checked the mutations in Postgres, deleted the
  throwaway files, committed 51425cd. Zero backend files touched — 1863 tests / 89.34% cov
  unchanged from chunk a.
- Learned: **a throwaway spec left in `web/e2e/` is picked up by `scripts/check.sh`'s
  Playwright gate.** The first gate run came back `FAILED (2): ruff-check playwright-e2e`,
  and both failures were the throwaway files, not the diff — ruff on the seed script's
  hardcoded test password, Playwright on seed rows the *previous* session's mutating tests
  had already consumed. The committed suite alone was 8/8 green. A verification artifact
  that lives inside a gate's glob is not neutral; keep it outside or delete it before the
  gate run.
- Learned: `./scripts/check.sh` needs `source .venv/bin/activate` as well as the known
  `PATH="$HOME/.local/bin:$PATH"` fix. Without the venv all five backend gates report
  "command not found" — as FAIL, not SKIP, so it looks like a real regression. The PATH
  quirk was already in STATE.md; the venv half was not.
- Learned: the P3.7d/D3.13 lesson paid off again as *process* rather than as a bug. Green
  Playwright asserted navigation happened; only the direct Postgres query showed what
  actually persisted — override writes `teacher_awarded_marks` and leaves the AI's
  `awarded_marks` alone, dismiss writes nothing to the `QuestionResult` at all. Worth the
  five minutes every time a chunk mutates rows.
- Next: P3.8 chunk c — T-09 quiz builder stepped flow, replacing the mock `Quizzes.tsx`;
  `portals/teacher/data.ts` should be gone by the end of it.

## 2026-08-07 — P3.8 chunk c (T-09 quiz builder)

- Did: resumed onto a dirty tree carrying a near-complete chunk c (QuizBuilder.tsx,
  a new C-15 Stepper, the rewritten Quizzes.tsx, and the client hooks/types). Rather
  than wip-committing it blind, verified it first: all 12 gates green, then committed
  it properly (7b80532), then ran the live-stack verification the chunk still owed.
- Did: 6/6 green against the real Alembic-migrated stack — list empty state, the full
  six-step walk, draft-resume-at-`builderStep`, and 380/768/1440 — each asserting zero
  serious/critical axe violations, zero console errors, no horizontal scroll. Followed
  by the direct Postgres check: every step's field persisted, `quiz_questions` carry
  **copied** prompt text with `question_bank_id` as provenance only (§1.5), the
  assignment row converted the local due date to UTC correctly, and `status` reached
  `assigned` without the UI ever posting `/status` — D3.15's claim, now evidenced.
- Learned: the plan line "data.ts should be gone by the end of chunk c" was simply
  wrong — `navItems` and the `StatCard` interface have two other real importers. The
  previous session caught it and corrected the plan in the file's header rather than
  deleting the file to satisfy a checklist. Corrected in STATE.md too.
- Learned: `text-t3` at 10-13px measures 4.36:1, under WCAG AA's 4.5:1. This screen
  sidesteps it with `text-t2`, but every other teacher screen still emits it — invisible
  only because `audit.mjs` is still scoped to D2.10's four *student* routes. That makes
  P3.10's carried item (a) a correctness fix, not housekeeping: the gate currently
  passes by never looking.
- Learned: seeding cost three iterations on field names alone (`ClassRow.class_id` not
  `.id`; `QuestionBank.total_marks`/`difficulty_source` not `.marks`). Recorded in
  STATE.md so chunk d doesn't pay for it again.
- Next: P3.8 chunk d — T-10 quiz results + T-12 announcement composer. `useSetQuizStatus`
  is already written and waiting for the results screen to consume it.

## 2026-08-07 (later) — P3.8 chunk d, phase task done

- Did: built T-10 quiz results and T-12 announcement composer, closing P3.8. Both
  verified against the live stack (8/8, axe clean at 380/768/1440) plus the direct
  Postgres check: the composed announcement row has the right class, `school_id`
  NULL, `publish_at` converted local→UTC, and the delete round trip leaves zero
  rows — a real delete, not a hidden list entry.
- Learned: T-12's school-wide option looked like it needed a backend change (a
  `school_admin` has no client-visible school id), and the instinct was to enrich
  `/api/me/profile`. It didn't — the `school_admin`-gated `GET /api/school/seats`
  from Phase 1 already returns `schoolId` + `schoolName`. Ten minutes of looking
  beat a speculative DTO addition and a second source for the same fact.
- Learned: `npx tsc --noEmit -p tsconfig.json` passed while `npm run build` failed
  with three real narrowing errors — the root tsconfig is not the one the build
  uses. Trust the build, not a hand-rolled tsc invocation, when checking types here.
- Learned: two helpers were about to be copied into a second screen (`downloadCsv`,
  and the accuracy→tone→severity ladder). Extracted them instead — `lib/utils.ts`
  and the new `lib/severity.ts`. The codebase has fixed "same label, two numbers"
  three times already (D3.3/D3.4/D3.5); the thresholds are exactly the thing that
  must not exist twice.
- Honest gap recorded: T-10's populated state had to be seeded directly into
  `quiz_submissions`/`attempts`/`question_results`, because the e2e harness forces
  `gemini_api_key = None`. The rendering and route are proven; the marking pipeline
  is not exercised by this pass (it is covered by F2's own 100%-cov tests).
- Next: P3.9 — parent frontend G-05 (phone+OTP login) + P-01..P-04. No parent portal
  exists at all yet; the backend landed in P3.6.

## 2026-08-07 (later still) — P3.9 complete, parent portal exists

- Did: all four chunks of P3.9. Chunk a added G-05's mandated developer OTP
  affordance (D3.16); b built the parent portal shell, phone+OTP login, P-01 and
  P-02; c added P-03 and P-04; d added the student-side link management that makes
  any of it reachable without a seed script. 1868 tests / 89.35% cov, 12 gates green.
- Learned: the standing gates cannot see this work at all. Three real defects came
  out of hand-verification and none from `./scripts/check.sh` — parents were being
  routed into the *teacher* portal (`"parent"` was in `TEACHER_ROLES`), two
  icon-only controls lost their accessible name below 640px, and a synthesised
  `phone+20…@parents.lemely.local` address was being shown to students as their
  parent's name. `audit.mjs` is still scoped to D2.10's four student routes, so
  P3.10 item (a) is now three-times evidenced, not a tidy-up.
- Learned: gating a secret's disclosure on a *provider capability*
  (`delivers_out_of_band`) rather than an environment string turned out to also be
  the thing that made the Playwright OTP flow trivial — the test reads the code off
  the screen. The safe design and the testable design were the same design.
- Learned: two verification specs were wrong in the same way — they assumed a clean
  database. A previous run's link silently disabled the empty state and the
  single-child skip under test. Per-run unique phone numbers fixed it; worth doing
  by default for anything that asserts an empty state.
- Honest gap recorded: the student sidebar still renders "Maya Rahman / Year 11 -
  Helwan Science Centre" from `data.ts` — the same fiction P3.7 removed from the
  teacher sidebar. Left alone deliberately (out of P3.9's scope), carried to P3.10.
- Next: P3.10 — acceptance. Extend `audit.mjs` past the four student routes (the
  gate is vacuous for ~15 teacher/parent routes), decide the `text-t3` contrast fix,
  and run the standing UI gate properly.

## 2026-08-07 (later) — P3.10 chunk b, the UI gate stops being vacuous

- Did: rebuilt `web/scripts/audit.mjs` from a 506-line linear 4-route journey into a
  declarative 21-route registry (D3.17), promoted console-errors and horizontal-scroll
  to real gates in `check_ui_gates.py`, and fixed everything the expanded gate found.
  Final: 21 routes, **zero axe violations at any severity**, Lighthouse a11y 100 on
  every route, 0 console errors, 0 responsive violations. 1892 tests / 89.35% cov,
  all 12 gates green with 0 skipped.
- Learned: the gate really was passing by never looking. Three of the five defects were
  in product code no previous run had ever loaded — `/teacher/grading` and
  `/teacher/schemes` have no `<h1>` at all, and `/student/result` overflowed 380px by
  10px because the student header is one non-wrapping flex row whose fixed items sum to
  391px. The other two were harness defects that would have made the new gates lie.
- Learned: "no populated fixture" is not a reason to leave a route out of an audit. Both
  h1 findings came from screens audited in their genuinely *empty* state.
- Learned: hand-calculated WCAG luminance and axe cannot disagree given the same two
  colours. P3.8c's 4.36:1 `text-t3` reading is below the ratio against every base
  surface token, so axe was sampling a darker composited background — never
  root-caused, and `index.css`'s claim that axe accounts for glyph rasterization was
  simply false. Corrected rather than carried.
- Learned: collecting route failures instead of failing fast turned three ~11-minute
  debug cycles into one. A responsive gate that names the offending element turned a
  fourth into zero.
- Next: P3.10 chunk c — token retrofit of the teacher + parent portals onto the
  DESIGN.md scale, plus the student-sidebar `useProfile()` fix. Chunk b's 21-route
  registry is the safety net that makes that retrofit checkable.

## 2026-08-07 — P3.10 chunk c (token retrofit + the defect it uncovered)
- Did: retrofitted the teacher portal, shared `components/` and the student shell onto
  the token scale — 598 literals, zero left in all three. Added the two serif rungs
  DESIGN.md's table implies but never writes down (its `typography:` jumps 15px → 30px,
  which is exactly why 18 screens invented 19/20/22/24/26/34px ad hoc), size-only
  aliases for the values that were only reachable through composite classes, and a
  per-portal `--accent-subtle-on`. Killed the student sidebar's fake identity, a
  non-functional search box and a hardcoded "24 day streak".
- Learned: **measure the brief before executing it.** The inherited item said "five
  teacher screens; P2.5.3 retrofitted the student ones". It was 18 files / 482
  literals, the parent portal was already clean, and P2.5.3 had *not* failed — read
  per-file rather than in aggregate, every student screen in scope then is clean. My
  own first draft of D3.18 got that wrong and had to be corrected; an aggregate count
  across in-scope and out-of-scope files is a misleading number.
- Learned: **D2.9 was only half-applied and the other half was live.** The composite
  type classes stayed in tailwind-merge's colour-collision trap —
  `twMerge("text-display-md text-t1")` returned `"text-t1"`, dropping the type outright
  — and five shared C-* components hit that shape. Nothing in this build could see it:
  a dropped type class degrades to *inherited* type, so it is not a type error, lint
  error, console error, axe violation or overflow. Renaming (D2.9's rule) treats the
  symptom; registering the classes with twMerge fixes the cause.
- Learned: a whole class of frontend defect is invisible to every gate we have, because
  every gate looks for a *failure* and this one produces a plausible-looking success.
  That is what `check-design-tokens.mjs` exists for, and why it is verified by
  inversion rather than trusted.
- Next: P3.10 chunk d — Playwright E2E per role, with at-risk flags asserted against
  chunk a's seeded scenarios (`scripts/seed_e2e.py`). That is the phase's named
  acceptance criterion. Chunk e then owns the screenshot corpus + re-baselining, and
  must decide the frontend-runner question (if a runner lands, fold
  `check-design-tokens.mjs`'s two checks into it verbatim).

## 2026-08-07 — P3.10 chunk d + a blocking INBOX directive

- **Did:** P3.10 chunk d — the phase's named acceptance criterion. Five Playwright
  specs (18 tests, all green): per-role journeys (teacher T-01..T-06, parent G-05 via
  the real OTP UI + P-01..P-04, student), at-risk flags asserted against chunk a's
  seeded `expectedAtRiskReasons` at both the API and T-06 layers including the D3.5
  acknowledge/undo round trip, and a cross-role RBAC denial matrix. Seeding moved to a
  Playwright `globalSetup`. All 13 gates green, 0 skipped; 1892 tests / 89.35% cov
  unchanged (zero `lemely/` files touched).
- **Learned:** Playwright forks a worker process per test file even at `workers: 1`, so
  a "seed once, cache the promise" helper silently re-seeds per file — `globalSetup`
  plus a file on disk is the only thing every worker can read back. Also: proving a
  green suite is worth anything needs inversion — expecting the control student to be
  flagged fails both layers, which is what makes the at-risk assertions load-bearing.
- **Blocked:** a mid-session INBOX directive added two real solved 0625 scripts for
  end-to-end accuracy testing. Its own item 6 fires — the matching official mark
  schemes are absent and no code path can fetch them (`resolve_mark_scheme` is
  sibling-PDF or local-JSON only; `outputs/schemes/` is empty). Raised as BLOCKERS.md
  B1, ntfy'd, $0.00 spent, nothing reconstructed.
- **Next:** P3.10 chunk e (screenshot corpus re-baselined into `reports/phase-3/`,
  contact sheet, regression check vs the Phase-2.5 baselines, frontend-runner decision),
  then P3.11.

## 2026-08-07 — B1/B2 resolved, B3 raised, P3.10 e1 landed

**Did.** Resolved B1 using the `paperscraper` skill the human installed mid-run —
fetched both official 0625 mark schemes, verified via the scraper's catalogue
rather than its exit code, kept them gitignored per the skill's copyright rule.
Delegated and verified two subagent tasks: P3.10 chunk e1 (seed a review item, a
marked quiz, and genuinely-empty accounts — unblocking T-08/T-10, which had zero
audit coverage) and B2 (the `w24_ms_41` 83-vs-80 parse failure). Committed both,
plus the skill itself. All 13 gates green on a clean run.

**Learned.** Three things worth not re-paying for. (1) My B2 hypothesis was
wrong in a specific, instructive way: I assumed the *reconciliation rule* was
wrong about alternative marks; it was two *extraction* defects (−9 dropped
table, +12 compensatory C-marks) masking each other down to +3. The small
discrepancy made it look like a rounding-tolerance concern, which is exactly why
raising the tolerance would have been so tempting and so wrong. (2) A cached
`.json` sibling is NOT evidence its PDF parses today — I recorded `s20_ms_31` as
passing on that inference and it had been failing at 38/80. (3) The E2E gate is
unsound under `reuseExistingServer: true`: concurrent runs kill each other's
server (three false FAILs this session, mis-attributed by two subagents), and
worse, a stale server runs stale code, so the gate can PASS against source no
longer on disk.

**Also.** B3 raised and independently re-verified: every *correct* MCQ answer is
flagged as plagiarism, because both sides of the similarity check are the same
single letter, so the ratio is 1.000 against a 0.85 threshold. A 40/40 paper
generates 40 flags; a 0/40 paper none. It shipped in P2.4 and directly poisons
the accuracy fixture (paper 22 is MCQ, 34/40).

**Next.** Fix B3 before reporting any accuracy numbers. Then P3.10 e2 (screenshot
states + regression compare), e3 (frontend runner), then the accuracy fixture
work itself — both schemes are now available.

## 2026-08-07 — P3.11: Phase 3 closed, reported, merged, PR #3 updated

**Did.** Committed the accuracy work the previous session left staged-but-uncommitted
(the recurring failure mode of this build — the work was finished, the commit was not).
Then P3.11: verified all 13 gates green with 0 skipped in the foreground, measured
1939 tests / 1933 passed / 6 skipped / 89.42% cov, wrote `reports/phase-3/REPORT.md`,
merged to `develop` (49d9750, no-ff, signed), pushed, and updated PR #3 to "Phases 0–3".

**Learned.** Two things worth not re-deriving. (i) PR #3's body had **never** carried a
Phase-2.5 section, despite that phase's own STATE line claiming the PR was updated — a
claim nobody had checked for two phases. Added it alongside the Phase-3 section. (ii)
STATE.md had grown to 1983 lines; MISSION §8b's prune-on-report rule had not been applied
to Phase 3 as its chunks landed. Pruned to 150 lines with the forward-looking facts
(P4 prerequisites, environment quirks) kept and everything else pointed at the report,
DECISIONS.md, and git history.

**Worried about.** The `teacher-quiz-detail` Lighthouse performance score of 67. It is
honestly reported as debt outside MISSION §11's student-route floor, but Phase 4 adds
more teacher-adjacent surface on top of it, so the number will get worse before anyone
looks at it.

**Next.** Phase 4 — content generation + study plans. Its two hard prerequisites were
established by Phase 3, not left open: the question-stem extractor (D3.7 — the bank is
empty and corpus growth cannot change that) and the target-grade column (D3.3 — at-risk
rule 2 cannot fire without it).

## 2026-08-08 — P4.1 landed, P4.2 done (topic taxonomy)

**Did.** Committed the P4.1 quality fixes that were sitting staged and ungated from
the previous session (symbol recovery, corrupt-leaf exclusion, the conftest guard that
stops the test suite making billed Gemini calls) after verifying all 13 gates green —
1999431. Then P4.2 end to end: syllabus taxonomy, deterministic classifier, loader,
bank backfill, CLI, 27 new tests — a05db60, D4.4.

**Learned.**
- *Don't author reference data from memory when the source is fetchable.* First instinct
  was to write the CAIE topic lists from knowledge. CAIE renumbers topics between
  syllabus cycles, so that would have put invented precision at the root of the phase.
  The three syllabus PDFs were one curl away from a domain Phase 2 already scrapes.
- *Calibrate on the real corpus before tuning thresholds.* Two defects only the real
  273 rows could show: hyphens never matched at all (`double-insulated` vs `double
  insulated`), and `mcq_options` — already in the DB, unused — carried coverage from
  78.8% to 89.4% on its own. No synthetic fixture would have surfaced either.
- *Writing the tests found two scoring bugs.* A same-parent subtopic tie was being
  resolved by file order and reported as a finding; and an *uncontested* single strong
  hit was banded the same as a contested one. Both fixed in the code, not the test.
- *The honest yield is 77.3%, not 89.7%.* Scoring places 245/273 but only 211 get
  written. There is no confidence column on `question_bank.topic`, so a low-confidence
  label is indistinguishable downstream from a certain one — and the low band contained
  real nonsense (radioactivity labelled "Electrical quantities").

**Next.** P4.3 — student profile + onboarding data model (migration 0009), which also
activates target grades and closes at-risk rule 2 (D3.3). Carry into P4.4: the marking
side still has **no** topics (`topic_hint` is None on all 637 questions in all 33 parsed
0625 schemes), so practice-targets-weakness does not join up until that fill is done at
the db/io boundary. D4.4 §6.

## 2026-08-08 — P4.3: the student profile, and the at-risk rule that never fired

**Did.** P4.3 in two chunks. Migration 0009 adds four additive tables (profile,
per-subject enrolment, papers, confidence ratings) plus a service and student-only
onboarding routes on `/api/me`. Then the part that actually mattered: at-risk rule 2
("predicted ≥2 grades below target") has been permanently *not evaluable* since Phase 3
for want of a target-grade column, and is now live. D4.5 records both.

**Learned.** The tempting shape for `assess_at_risk` was to keep its scalar
`target_grade` and just start passing a value. That is wrong the moment a student enrols
in two subjects — it would compare a physics paper against a maths target and put a false
flag on a teacher's dashboard. Targets had to become a subject-keyed mapping resolved
against the latest *grade-bearing* record. Worth remembering generally: activating a
dormant rule is not the same task as filling in its missing input.

**Also.** Two subagents deadlocked waiting on each other's gate run and produced nothing
for ~20 minutes; I finished that chunk by hand. Watch for the wait-loop pattern — an
agent that reports "waiting for X" twice is not working.

**Next.** P4.4 — placement-test backend, which also carries P4.2's marking-side topic
fill (D4.4 §6) and therefore needs the accuracy harness re-verified (MISSION §6 gate 5).

---

## 2026-08-08 — P4.4 chunk B: placement assembly is real, and three defects only measurement could find

**Did.** Committed B-1 (the ownership schema, already written but uncommitted), then
B-2 (`_load_permitted` — the owning student can now take a class-less assignment at all,
which no code path previously allowed) and B-3 (the assembler, `paper_timing.json`
transcribed from the three syllabus PDFs' Assessment overview, and the pure
`core/placement.py`). D4.8 records the reasoning.

**Learned.** Every one of the three defects in D4.8 was invisible from the code and
obvious from one query against the real bank. The worst was silent rather than loud:
`question_bank.paper_id` was NULL on all 273 rows and `papers` was an empty table, so
placement returned "unavailable" for 0625 — which looks *identical* to the expected
0580/0606 corpus gap. A designed-in honest-failure path is exactly where a real failure
hides best. The second worst was a number that was true and meaningless: "13 topics" for
a set with nine of 13 questions under physics topic 1, because D4.2's classifier writes
both `"3 Waves"` and `"1.2 Motion"` and nothing had ever had to treat those as different
levels. Both go in DELIVERY.md's honesty section, not just the report.

**Also.** Wrote the assembler before the wiring, deliberately — it is where the rules
live, and the DB/route layer around it is now mechanical with no open questions.
$0.00 Gemini this session; everything here is deterministic.

**Next.** B-4: `PlacementService` + the three routes in D4.6 §4. Take/resume/submit are
the existing endpoints — reusing them is the point. Then P4.5.

## 2026-08-08 (session 2) — P4.4 finished, P4.5 landed

**Did.** Closed P4.4 with chunk B-4: `PlacementService` (availability/create/result) and
the three S-03/S-05 routes over the assembler chunk B-3 had already measured (D4.9). Then
P4.5 end to end: `PracticeService` (preview/create/export), `/api/student/practice`, and
the `list_assigned` branch D4.6 §3 had explicitly deferred to this task (D4.10). Feature
branch pushed for the first time.

**Learned — the same lesson twice, from two different subagents.** Neither reported back;
both had to be verified from the artefacts instead. The placement implementer silently
dropped one clause of D4.6 §5 (narrow to the papers the student will actually sit), which
would have measured a 0625 **Core** student on **Extended** questions — inventing a
weakness in every topic that sample touched, then feeding it into P4.7's study plan. **No
test could have caught it**: the seeded bank is single-paper, so the narrowing is
unobservable unless a test deliberately enrols the student elsewhere. Found by reading the
code against the decision record, not by running anything. The practice implementer
reported done with `ruff format` red on two of its own files. MISSION §5's "verify their
output yourself" is not ceremony.

**Also worth keeping:** practice deliberately draws from 273 rows where placement draws
from 211. An untopiced question cannot support a weakness *profile* but is perfectly good
practice *material* — the two services filter differently on purpose, and that asymmetry is
easy to mistake for a bug later.

**Next.** P4.6 flashcards backend (decks by subject/topic, AI generation from a weakness,
SM-2 review). Then P4.7 study plan, then the four frontend tasks.

## 2026-08-09 — P4.6 closed, P4.7 chunks A and B landed

**Did.** Found P4.6 chunk C uncommitted on disk from a killed session; verified it with my
own gate run rather than the handover's word and it came back clean — the first one this
phase that did. Committed (`b1a44bf`). Then P4.7 chunk A (`fc4dca9`): the adaptive scheduler
rebuilt pure and clock-injected, sessions carrying topic + activity type + duration + a real
date, three weighted signals (0.5 rolling weakness / 0.3 placement / 0.2 self-report) with
renormalisation instead of zero-filling. Then chunk B (`27f6a16`): migration 0012,
persistence, ISO-week regeneration by supersession, per-session completion. D4.12 recorded.

**Learned.** The thing worth carrying forward is *measure the output, don't read the code and
nod*. Chunk A looked right — good docstrings, honest refusal path, every rule tested — and
scheduled **270 of 600 minutes** for a student with three weak topics, because sessions capped
at 90 minutes silently dropped the excess while the header still claimed ten hours a week. No
test failed. Nothing was obviously wrong on the page. It took running the function over a few
realistic inputs and looking at the totals. The worst failures in this phase have all been
this shape: plausible code, invisible to the suite, wrong in a way only arithmetic reveals.

**Also.** Five of five handovers this phase have now reported done with a gate red — this
time `test_db_schema.py`'s EXPECTED_TABLES registry, the deliberate schema-drift guard the
two new tables were never added to. It caught the diff exactly as designed. The pattern is
stable enough that the orchestrator's own `./scripts/check.sh` run should be treated as part
of the task, not as a formality after it.

**Next.** P4.7 chunk C — the routes, and the DTO decision. `StudyPlanDTO` currently carries
no `available`/`reason`, so chunk A's honest `no_signal` refusal and a genuine "nothing to
schedule this week" both arrive at the frontend as an empty list. That distinction is the
whole point of chunk A and it dies at the wire until chunk C fixes it. Then P4.8–P4.12.
