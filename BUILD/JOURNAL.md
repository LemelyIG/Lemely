# Session journal

## 2026-08-12 — Session 107 — P6.12: CI made green again (D6.10)
- Did: fixed the CI red session 106 diagnosed and deferred (`7f11f58`). Two toolchain defects,
  zero product behaviour changed. `pyproject.toml` pinned only `ruff>=0.7`, so the runner
  resolved **0.16.2** while this venv and the pre-commit `rev` both held **0.15.20** — 10 ×
  RUF036 red in CI, green everywhere else on the identical tree. And the `pre-commit` job
  installed `.[dev]` alone, so its `entry: mypy lemely` (`language: system`) hook could not
  import fastapi: **291 errors that are an environment answer, not a verdict on the code**, the
  same lesson STATE already records twice locally. Pinned `ruff==0.15.20` in lockstep with the
  pre-commit rev (a comment on each line says to bump them together), reordered the 10
  annotations so a future bump is unblocked, and gave the job `.[dev,ui,web,db]` — the same
  extras as the `test` job whose identical mypy step is green.
  Then the run went red one step further along and the cause was the same shape a third time:
  `gradio>=6.1,<7` resolved **6.23.1** on the runner against the venv's **6.19.0**, and 6.23's
  event-listener typing gives 12 × `"Button" has no attribute "click"`. So the second commit
  (`f980fbc`) closed the pattern instead of the instance — every tool whose output *is* a gate
  verdict is upper-bounded now (`gradio<6.20`, `pytest<10`, `pytest-cov<8`, `mypy>=2.1,<2.2`,
  `pre-commit<5`, `import-linter<3`), proved with `uv pip compile` on all three CI interpreters:
  each exits 0 and selects exactly the versions this tree is green on.
- Learned: **session 106 deferred to a fix-it PR that predated the failure it was named after.**
  Copilot's PR #4 has been stale since 2026-08-05; RUF036 shipped with ruff 0.16 days later, so
  it could never have fixed this — and two of its four changes would have hurt (narrows the format
  gate to `lemely tests`, dropping `web/` and `scripts/`; `if: matrix.python-version == "3.13"`,
  which GHA cannot parse). Check the dates before treating an open PR as a fix in flight.
  Second: **a green local gate cannot prove a remote red is gone when the versions differ** —
  verification had to be `uvx ruff@0.16.2 check .`, not `.venv/bin/ruff`. That same probe is why
  the fix pins rather than upgrades: 0.16 would also reformat 6 files and widen the format set
  340 → 387, trading a red lint gate for a red format gate on a shipped tree.
- Next: nothing outstanding. Build remains COMPLETE, PR #3 open and unmerged (never mine), PR #4
  left for Habeeby. The deliberate follow-up, if wanted, is the ruff 0.16 upgrade — now a
  formatting decision on its own rather than a blocked one.

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

## 2026-08-09 — P4.7 closed, P4.8 opened (chunks 0 + A)

**Did.** Verified and landed P4.7 chunk C (persisted study-plan routes, D4.13) — found
already on disk from a killed session and, for the first time this phase, clean on every
gate. Closed P4.7. Opened P4.8 and, while scoping S-04, found a real defect by measuring
the live bank: 25 of 273 stems reference a figure the bank structurally cannot hold.
Fixed as chunk 0 (D4.14). Landed chunk A — the real onboarding wizard on the P4.3 backend.

**Learned.** Three things worth not re-deriving. (1) No maths renderer is needed: 1 of 273
stems is LaTeX-shaped, the rest is plain Unicode; what stems actually need is
`white-space: pre-line`. (2) There is no student quiz-taking screen anywhere in the
product — S-04 will be the first, so it must be built reusable. (3) `PlacementService`
does not use `visible_bank_filter`, which is why the obvious one-line fix for the figure
defect would have left the worst-affected path unfixed.

**The pattern that keeps paying.** Two more subagent handovers signed off before their own
gate runs finished. Both happened to be green, but that was established by the
orchestrator's own run each time. Seven of eight handovers this phase have done this; the
five that were actually red were all caught the same way. Keep running the gates.

**Next.** P4.8 chunk B — S-03/S-04/S-05 on the placement + quiz-taking endpoints. S-04
owns answer persistence across a lost connection and resume, and is the reusable
question-rendering surface P4.9 and P5 will compose.

## 2026-08-09 — P4.8 chunk C closed; P4.8 done (session 7)

- **Did:** ran the Phase-4 audit registry for the first time (six prior sessions only read it).
  Confirmed session 6's two fixes work — the `ready`-driven wizard survives the repeated
  navigation, and S-04 is genuinely reachable, so the placement seed is real. Then fixed the two
  defects the run exposed: **no `<h1>` on any of the five new screens** (QUALITY-BAR.md:45; axe
  rates it *moderate*, so gate 8's serious/critical threshold had been passing over it) and a
  **seed that still collided on rerun**, failing `playwright-e2e` on a real IntegrityError.
  Ran `/impeccable audit` (16/20, detector clean) and fixed its P1: three controls under the
  44px touch floor. All 13 gates green, 0 skipped; 2308 passed / 6 skipped / 0 failed / 90.30%.
- **Learned:** reading and running find different defect classes, and this chunk is the cleanest
  evidence of it in the build so far. The `h1` gap screenshots perfectly clean and only harms
  screen-reader users; the seed collision needed ~18 accumulated runs to surface. Also: a gate
  threshold looser than the written bar (axe *serious/critical* vs QUALITY-BAR's "one h1 per
  page") is a permanent blind spot, not a one-off miss — worth checking the bar directly rather
  than trusting the gate. And a "rerun-safety" helper that hashes 2 of 12 characters is a
  100-value namespace wearing a uniqueness guarantee's docstring.
- **Next:** P4.9 — frontend S-20/S-21 (practice) + S-22/S-23 (flashcards) on the P4.5/P4.6
  backends. Four audit findings deliberately deferred and recorded in STATE + D4.16 §4; the
  `prefers-reduced-motion` blanket kill is P5's, because Phase 5's own acceptance requires a
  test that cannot honestly pass against it.

## 2026-08-09 — P4.9 opened; chunk 0 (backend read paths) done
- **Did:** scoped P4.9 by measurement before briefing anything, which turned up two missing
  backend read paths and made them chunk 0 (`dc0c0ac`). A practice set **is** marked on submit
  — marking fires for every quiz kind — but had **no result route anywhere**: the take DTO
  carries no marks at all and placement's result route is narrowed to `kind == placement`. And
  no topic-listing endpoint existed in any router, so S-20's topic selection had no data
  source. Both added; both filtered/narrowed through the *existing* shared predicates rather
  than second copies. All 13 gates green, 0 skipped; 2331 / 6 / 0, 90.37% cov.
- **Learned:** the live bank mixes taxonomy levels — `"1 Motion, forces and energy"` (152) comes
  back as a **peer** of `"1.2 Motion"` (6) on disjoint row sets, so a flat chip list would offer
  a parent that silently excludes its own children while looking perfectly correct. Only
  querying the real bank showed it; reading the code could not. It is the same defect class as
  P4.4 chunk B-3's breadth bug, which is why the helper to fix it already existed.
  Second lesson, cheaper to have learned here than during a phase report: **running `pytest`
  concurrently with `check.sh` corrupts the coverage figure while still exiting 0** — 89.67%
  concurrent vs 90.37% serial on an identical tree, with test counts identical both times. I
  spent real effort chasing a regression that did not exist. Recorded in STATE's environment
  facts.
  Third: the handover omitted the structural-exclusion test the brief explicitly required, and
  the existing precedent it would have copied asserts on a response *body* — which passes
  vacuously the moment `questions` is empty, i.e. exactly the unmarked case. Added in the
  stronger field-set form.
- **Next:** P4.9 chunk A — S-20 (practice generator) + S-21 (working view), composing the
  existing `QuizTaker` rather than forking it, and reading chunk 0's result route for the
  finish summary. Chunk 0's `syllabusGroup` is what S-20 must nest by. Note S-21's
  reveal-answer is deliberately **not** built (no route exposes a model answer, and D3.8's
  structural exclusion is on purpose) — recorded as a scope decision in STATE, not an omission.

## 2026-08-10 (sixth session) — P4.9 chunks A and B closed

**Did.** Verified P4.9 chunk A, which arrived as two wip commits with gates never run: all 13
gates green, 249 web unit tests, zero backend diff. Then scoped, briefed and verified chunk B
(S-22/S-23 flashcards on the ten P4.6 routes): 13 gates green, 279 web unit tests, still zero
backend diff. Recorded D4.17 (S-23 ships with no XP) and scoped chunk C.

**Learned.** The handover-is-not-evidence pattern held for the tenth time this phase, but the
interesting part is *what kind* of defect keeps surviving. All three found this session render
perfectly and pass every automated gate: a weak-topic prefill that applied an invisible filter
(8 of 15 real weakness topics have no servable chip), a dead `useEditCard` leaving S-22's
spec'd edit action half-built, and a hand-made deck labelled "Topic-generated". None is a
crash; each is a **provenance or honesty** defect, which is precisely the class this product
cannot afford and no linter can see. Also: the pure-logic-module split is what makes them
fixable *and* pinnable — hoisting the origin decision out of JSX into `manualDeckRequest` took
one edit and bought a real test.

**Next.** P4.9 chunk C — the standing UI gate for all four screens. Unlike A and B it carries a
`scripts/` diff (seed + registry). Its scoping block in STATE.md is written to start cold; the
mutually-exclusive-state analysis (a student with weaknesses cannot show `no_weaknesses`) is
the thing to do before writing the seed, not after.

## 2026-08-10 — P4.9 chunk C closed; P4.9 done

- **Did:** ran the gate over chunk C's on-disk seed + registry (13 entries / 14 states for
  S-20..S-23). First run failed on two serious axe violations and, silently, a third defect.
  Fixed all three, re-ran: **all 13 gates green, 0 skipped**. P4.9 closed; D4.18 recorded.
- **Learned (1):** both contrast failures were `opacity` applied to *text*, not token faults —
  `--t3` is 5.58–7.17:1 everywhere; axe was measuring it composited at 50%. The S-20 one had a
  root cause a level down: C-14 `Checkbox` only self-dimmed on its own `disabled` prop, never on
  an ancestor `<fieldset disabled>`, so the screen had no way to show the state except washing
  the whole card — heading and prose included. Fixed at the component (`has-disabled:`).
- **Learned (2), the one that matters:** the seed's documented "hermetic 24-row bank" was
  **96 rows** — no teardown, 24 added per run, and the student pool is scoped by subject+paper,
  never by run. S-20's `insufficient_pool` is the first capture that depends on pool *size*, so
  it passed on a virgin DB and failed on every run after. It was invisible in the summary
  because the audit already exited non-zero for the axe findings; found only by listing
  `screens/S-20/` and noticing `default--*.png` was missing. **Verify captures by listing them,
  never from the exit code.**
- **Next:** P4.10 — frontend S-24/S-25 (study-plan week view + session detail), replacing the
  placeholder `StudyPlan.tsx`. Backend is landed and route-tested (P4.7 chunk C, D4.13); the
  `CurrentStudyPlanDTO {generated, plan}` envelope's three distinguishable states are the thing
  the screen must render honestly rather than collapse.

## 2026-08-09 — twenty-second session (P4.10, D4.20 + D4.21)

- **Did:** chunk C's gate run had finished and failed **two** gates, neither from chunk C's
  diff. Fixed both in `8181f7c`: the placement band flake (D4.20) and a 380px horizontal
  overflow (D4.21). Re-gated; backend + web legs all green, live-stack legs confirmed after.
- **Learned (1), the trap the last session flagged and it was real:** the failing assertion
  `spans_multiple_bands is True` had *two* causes, and only one was the flake. The fixture's
  `uuid.uuid4()` made the tie-break random (measured: **1 failure in 30 runs**) — but
  `assemble` never reads `Candidate.difficulty` at all, so the assertion pinned a rule that was
  never implemented. Making the fixture deterministic alone would have made it pass every time
  and turned a lucky draw into a guarantee. Deleted the assertion instead and replaced it with
  an inverse pair proving what the flag really is: a *report*, deliberately False sometimes,
  because that is what stops S-05 inventing a working level from a one-band sample.
- **Learned (2):** the 273-row 0625 corpus had been lost from the local Postgres in a DB reset —
  the bank held only E2E seed rows. Re-ingested from PaperScraper ($0.00, deterministic) and
  **verified the reconstruction against the recorded figures before drawing any conclusion**
  (273/273/26/211/248 and 10 q / 17.06 min / 6 topics — all exact). The first measurement was
  still wrong (8 q / 15.94 min) because the seed's 24 fixture rows were also in the bank.
  **A measurement taken against a seeded DB is not a measurement of the corpus.**
- **Learned (3):** the responsive failure was reported against one screen but lived in the
  shared `StateView`, so *every* empty/error/offline/refusal state in the product overflowed at
  380px. `max-w-sm` caps a box but does not make it shrink — without `w-full` it keeps its
  intrinsic 384px. The screen named in a gate failure is where it was observed, not where it is.
- **Next:** P4.10 chunk D — the legacy-route cleanup, fully scoped in STATE and D4.19. Its
  three traps are already measured: deleting the routes silently shrinks the RBAC matrix
  (replacements must land in the same commit), there are two different `StudentProfileDTO`
  classes, and `lemely/io/study_plan_ai.py` must survive for the CLI.

## 2026-08-09 — twenty-eighth session (P4.10 closed, P4.11 chunk A)

- **Did:** confirmed the twenty-seventh session's gate run (all 13 green, 0 skipped) and
  committed the two replacement IDOR pins (`65c846c`), which closes P4.10 entirely. Then wrote
  **P4.11 chunk A**: `SeedContract` extended to all 14 top-level keys, plus a new
  `web/e2e/seed-contract.spec.ts` drift pin. Scoped chunk B read-only while the gate ran.
- **Learned (1), and it is why chunk A is not just a types edit:** the mirror is protected by
  *nothing*. `readSeed()` is an unchecked `as SeedContract` cast, **and `web/e2e/` is in no
  tsconfig `include` (D3.20)** — so neither the cast nor `web-typecheck` can see a Python-side
  rename. It typechecks, arrives `undefined`, and surfaces inside whichever spec dereferenced
  it; on a `SeedAccount` field that means a login form filled with `undefined`, which fails as
  a bad credential and reads as an auth bug. The pin re-reads the JSON as `unknown` —
  deliberately not through `readSeed()`, whose cast is the thing under test.
- **Learned (2):** the same missing typecheck meant the new spec could not be verified by
  typechecking it, only by running it — so it was, and then inverted for real: renaming
  `"studyPlan"` and one nested `"deckId"` in `seed_e2e.py` failed 2 of 3 tests with named
  messages, and the third correctly stayed green because it covers other fields. Reverted;
  `git diff` on `seed_e2e.py` clean.
- **Learned (3):** the twenty-fifth session's read-only shape note was right in substance but
  wrong in two details — it said "11 top-level keys" while enumerating 14, and it missed the
  `subjectCode` on both `practice` and `studyPlan`. Both were caught only because the shapes
  were re-read out of `build_result_payload` rather than trusted, and the note itself said to
  read the emitting code and not the docstring. **A prior session's "do not re-derive" covers
  the expensive discovery, not the arithmetic around it.**
- **Next:** P4.11 chunk B, the greenfield onboard → placement → plan acceptance journey. It is
  scoped in STATE with every route, seeded account and identifying string taken from
  `audit.mjs`, plus its three inherited traps: `waitForText` strings are regexes, S-05 must not
  be identified by a phrase `PlacementInvite` also renders, and the onboarding wizard's step is
  component state so S-02 cannot be deep-linked.

## 2026-08-09 — thirty-third session (P4.11 chunks B and C both landed green)

- **Did:** committed **chunk B** (`32cd131`) after its 24-minute foreground gate run came back
  13/13 green, then wrote, inverted, gated and committed **chunk C** (`0a78b3b`, also 13/13,
  0 skipped, on its own separate run). Both halves of MISSION §4's named Phase-4 acceptance now
  exist as real Playwright behaviour: onboard → placement → plan (5 legs), and
  practice-demonstrably-targets-a-seeded-weakness (3 tests). Attribution for both was checked by
  mtime against the run window rather than assumed.
- **Learned (1):** **one round of product inversion is not automatically enough.** Chunk C's
  round 1 broke three sites and all three tests went red — which looks like proof — but test 1
  had failed on its *shortfall* wait, several assertions before the one carrying the word
  *demonstrably*. The break was legitimate (no prefill → unfiltered preview → 248 match a
  request for 10 → the screen honestly renders "N match" instead of the shortfall panel); the
  *inference* was not. Round 2 pointed the prefill at a servable non-weak topic so the panel
  still rendered, and the targeting assertion then failed on its own terms while test 3 stayed
  green. **Check which assertion the inversion actually reached, not just that the test is red.**
- **Learned (2):** the scoping for chunk D was necessary but not sufficient. "Additive only, a
  new account" does not cover the fact that a fourth *enrolled* student moves the seeded class's
  average off the `"69%"` and its at-risk count off the `"2"` that `teacher-journey.spec.ts`
  hardcodes at `:48`/`:58`/`:59`. `seed_e2e.py:354` already names this exact trap for the
  review-queue item and dodges it by reusing an attempt. Recorded in STATE as a design question
  with the two candidate answers and the two measurements that decide between them.
- **Next:** P4.11 chunk D — resolve the enrolled-vs-second-class question by measuring first
  (is the overview "69%" class-scoped or teacher-wide; does the classes table's `nth()` indexing
  survive a second row), then the seeded below-target scenario plus the two `seed_e2e.py`
  docstring defects (`:20-23` false, `:18` mis-numbered). Then chunk E, whose blocking finding —
  the seeded stems are pure ASCII, so item 6's screenshot inspection would pass vacuously — is
  already recorded and must not be budgeted as a pure evidence pass.

## 2026-08-09 — thirty-eighth session (P4.11 chunks D + E; P4.11 COMPLETE)

**Did.** Inherited chunk D's gate run mid-flight, confirmed all 13 gates PASS /
0 skipped and checked attribution by mtime before committing (`bdfc9bf`) — at-risk
rule 2 is now pinned by a seeded scenario for the first time since D3.3 wrote it.
Then wrote and landed chunk E (`5983af5`), closing P4.11.

**Learned — chunk E was not the evidence pass it was scoped as.** The two screens
that render a question stem (S-04, S-21) are both fed by the E2E seed, and every
seeded stem was pure ASCII on a single line. So MISSION §4's "verify the maths
renders, do not assume" would have been a **vacuous pass against the existing
corpus** — it could not fail, and it looks identical to a real one. Seeded a
verbatim corpus sample (`0625_w23_qp_42#1c`) and then actually opened the
captures: newlines render as line breaks, `1.1 × 10⁵ J` renders correctly at
380px where the wrap splits it.

**Learned — two checks that were assumed rather than run.** `ruff` caught the `×`
as an ambiguous character (RUF001/RUF003) *before* a 25-minute gate was spent, and
`_FIGURE_DEPENDENT_PATTERN` turned out to be a **Postgres** regex that raises
`PatternError` under Python `re` — so figure-safety had to be evaluated in
Postgres, with a positive control to prove the check itself was not vacuous.

**Learned — D4.25, the finding I did not go looking for.** Reading the Lighthouse
numbers instead of the PASS line: `check_ui_gates.py` enforces a11y ≥ 95 and has
**no performance check at all**, while MISSION §11 and `audit.mjs:218` both state
performance ≥ 80 is gated. `student-flashcards-due` is at 79 and passes. Recorded,
deliberately not fixed — the remedy is frontend perf work outside P4.11, and
lowering the floor to stay green is the dishonest gate that comment warns against.

**Next.** P4.12: Phase-4 report, merge to develop, push, update PR #3, ntfy. Carry
D4.25 and the standing Phase-3 limitations into the report and DELIVERY.md.

## 2026-08-09 — thirty-ninth session — P4.12, and Phase 4 is complete

**Did.** Wrote `reports/phase-4/REPORT.md` and captured the committed phase-4
baseline the report hangs off — `LEMELY_REPORT_DIR=reports/phase-4` for both the
Playwright and Puppeteer legs, which is the explicit re-baseline `check.sh:20-25`
demands precisely so a gate run can never overwrite the reference it compares
against. Merged to develop (`321fdfc`), pushed both branches, retitled PR #3 to
"Phases 0–4" with a full Phase-4 section appended, left open. Pruned STATE.md per
MISSION §8b: 2206 → 229 lines.

**Learned — the gate evidence was already earned, and saying so precisely mattered
more than re-earning it.** No source file changed this session, so the tree is
byte-identical to `bf74b89` — the tree chunk E's run took through all 13 gates.
Re-running check.sh would have cost ~25 minutes to produce the same result on the
same bytes. What genuinely needed doing was the *baseline*, which is a different
artifact, and the report says which run each number came from rather than implying
one run produced them all.

**Learned — two more hand-copied mirrors drifted, which is now a pattern with three
instances.** `gemini_spend_usd` read 0.1612 while the ledger that actually enforces
the $8 cap read **0.18429**; `SeedContract` had drifted the same way (P4.11 chunk A);
`STATE.md`'s own chunk-D path reference had drifted earlier in the phase. Every one
is a value copied by hand from an authoritative source with nothing generating one
from the other. Re-read the source before quoting it.

**Learned — the compare's `changed` count is not a regression signal and never can
be.** The seed's `run_tag` is random per run, so every screen rendering a class name
differs on every re-baseline. `0 removed` is what carries the gate. Verifying the 78
changed captures by *opening* them found the phase's best artifact rather than a
defect: `T-06/default--1440.png` shows all three MISSION at-risk rules firing at
once, each labelled — impossible before P4.3 supplied targets and P4.11 seeded the
scenario.

**Next.** Phase 5, the engagement layer. XP has no schema at all (only the
`completed_at` seam), students still cannot see announcements, and
`notification_preferences` is written and read by nothing — all three are P5's, and
none has a helper waiting from Phase 3 or 4.

## 2026-08-09 — fortieth session (P5.2 complete)

- **Did:** resumed on a dirty tree carrying an uncommitted P5.2 chunk A (XP engine + migration
  0013 + 42 tests); verified it rather than trusting it, committed it, then wired chunk B — the
  four XP award seams — and closed P5.2. Full suite green on the committed tree: 0 failed, 6
  live-only skips, 90.30% cov (develop 90.18%).
- **Learned (schema):** `alembic check` can fail while `pytest` passes, because tests build
  their schema fresh and the dev DB does not. Chunk A's migration had been *amended* after being
  applied, so the file said `subject_code` and the DB still said `subject_id`. After amending an
  uncommitted migration: drop its artifacts, `alembic stamp` the prior revision, re-upgrade.
- **Learned (process), the one that mattered:** the paper seam originally deduped on the attempt
  id, which `persist_correction` re-mints on every call — a re-marked paper would have re-awarded
  every time, 250 XP/day farmable from a single PDF. D5.1 §8 had already forbidden exactly this;
  my *brief* to the implementer paraphrased it and lost the meaning. The implementer flagged the
  seam as "not idempotency-safe by construction" instead of quietly shipping it, which is the
  same instruction that produced D5.2 last session. A restated requirement is a copy that drifts;
  point briefs at the spec by line number.
- **Also:** proved the regression tests by inversion before believing them — with the old key
  restored they fail 2 != 1 on xp_events rows, and they assert two Attempt rows exist so they
  cannot pass vacuously. Caught a phantom coverage gap that was just me editing a file mid-run.
- **Next:** P5.3 leaderboards. Its hardest requirement is D5.1 §0's test asserting over the
  *emitted SQL* that no marking table is reachable, plus migration 0014 for `leaderboard_opt_out`.

## 2026-08-09 (fortieth session, continued) — P5.3 leaderboards backend, done

- **Did:** committed P5.3 chunk B (`3a2c445`) — `GET /api/student/leaderboard` over the chunk-A
  query engine, plus the `leaderboard_opt_out` control on the student profile. Verified before
  committing rather than after: a full foreground `./scripts/check.sh` came back **all 13 gates
  PASS, 0 skipped**, coverage **90.43%** against develop's 90.18%. P5.3 is now done end to end;
  4/12 Phase-5 tasks complete.
- **Learned, and it is the fourth instance of one pattern:** D5.4 and D5.5 were both defects the
  gates could not have caught. The school scope was briefed onto `school_memberships` — a
  staff-only table, so the board would have been silently, permanently empty for every real
  student and looked like missing data. And `display_names_for()` inherited the codebase's
  `display_name or email` fallback, which is fine when a class sees its own quiz results and is
  an email leak to strangers on a *global* board. With D5.2 and D5.3 that is four in this phase:
  **a brief paraphrasing the schema or the spec is not a source of truth about either.** Neither
  an empty board nor a leaked address is a test failure; only reading the model catches them.
- **Also worth not re-deriving:** read the coverage number off the run `check.sh` just did
  (`.venv/bin/coverage report --precision=2`). Re-running pytest to get it costs ~10 minutes and
  risks the concurrent-`.coverage` corruption already recorded in STATE.
- **Judged and not fixed:** `board()`'s three queries are not snapshot-pinned, so a concurrent
  award can put the viewer's own row a few XP out of step with the top-N. A leaderboard is an
  inherently stale read and it self-corrects next request; recorded in D5.5 so a later reader
  knows it was seen, not missed.
- **Next:** P5.4 — friends backend + migration, which also lands the leaderboard's fourth scope
  (`LeaderboardScope.friends`) and must extend the D5.1 §0 emitted-SQL guard test to cover it.

## 2026-08-10 — forty-third session — P5.4 closed by its gate run

- **Did:** resumed with a clean tree, no unhandled INBOX items and no open blockers. P5.4's three
  code chunks (`7397df0`, `71d1a9b`, `63a4bbc`) were already committed by the two prior sessions,
  so the only outstanding work was the verification the forty-first session died before finishing.
  Ran the full `./scripts/check.sh` twice: **all 13 gates PASS, 0 skipped, 2532 tests / 6
  live-only skips / 0 failures, coverage 90.48%** (develop 90.18% — no drop), `alembic check`
  clean. Nothing was re-implemented or re-planned.
- **Learned — the one defect, and it is a class not an incident.** The first run failed on
  `tests/test_db_schema.py::test_all_expected_tables_registered`: migration 0015 created
  `friendships` but the hand-maintained `EXPECTED_TABLES` set was never extended, so the suite
  died on `Extra items in the left set`. Fixed by adding the table (`72330b8`), **not** by
  loosening the assertion — exact set equality is precisely what forces a new table to be
  acknowledged deliberately instead of arriving by accident. The generalisable form: **a new
  table costs two edits, the migration and that set.** Phase 5's earlier migrations (0013, 0014)
  added only columns, which is why this could not fire until now, and it fires roughly ten
  minutes into a gate run — make the `EXPECTED_TABLES` edit in the same chunk as the
  `create_table`.
- **Also worth not re-deriving:** `check.sh` suppresses output for every gate that passes, so a
  fully green log contains no pytest counts whatsoever — the counts I could quote from the *first*
  run existed only because pytest failed there. Read coverage with
  `.venv/bin/coverage report --precision=2` off the run that just happened, and get the test
  count from `pytest --collect-only -q --no-cov`. Never re-run the suite for a number.
- **Confirmed rather than assumed:** `.venv/bin/pre-commit run --all-files` still fails its
  `mypy` and `import-linter` hooks with *"Executable not found"* — the already-recorded hook
  environment defect, not a code failure; both tools pass directly inside `check.sh` on the same
  tree.
- **Next:** P5.5 — announcements. Student-facing read (there is no student route at all today),
  read-receipts (needs migration 0016), the school-admin whole-school audience, and
  auto-populated official CAIE session dates. Backend only; the screens are P5.8/P5.9.

## 2026-08-10 — forty-third session (continued) — P5.5 chunk A

- **Did:** started P5.5 (announcements). Committed chunk A (`446e7fa`): migration 0016
  (`announcement_reads`) plus the student read path on `AnnouncementService`
  (`list_for_student`, `unread_count_for_student`, `mark_read`) and 17 tests. `alembic check`
  clean both directions, ruff/format/mypy clean, related suites green. The full `check.sh` has
  **not** been run since.
- **Learned — P5.0's reconnaissance was wrong about a whole bullet.** It recorded the
  school-admin → whole-school audience as absent. It has been fully built since P3.8/D3.14:
  `create` takes `school_wide` + `school_id`, restricts to `school_admin`, validates through
  `ClassService.member_school_ids`, and the router exposes it. I nearly built it a second time.
  **Fifth instance in Phase 5** of a note paraphrasing the codebase from memory and being wrong
  (D5.2–D5.5). The rule keeps paying: read the code, not the note about the code.
- **The interesting design call: `publish_at` had been inert since P3.8.** Teachers could
  schedule an announcement and nothing ever read the column back — harmless while no student
  surface existed. This chunk is its first consumer, so honouring it was not optional: shipping
  the read path without the filter would have turned a control that did nothing into a control
  that actively lied. The author's own list stays unfiltered, since a teacher must see what they
  queued.
- **Both guards verified by inversion rather than asserted** (D5.7's lesson). Swapping the school
  arm to `SchoolMembership` makes the seated student see an *empty list* — the exact
  "reads as a data problem, not a defect" shape D5.4 warns about. Replacing the `publish_at`
  predicate with `sa.true()` fails two tests.
- **Applied this morning's own lesson:** `announcement_reads` went into `EXPECTED_TABLES` in the
  same commit as the `create_table`, not ten minutes into a gate run.
- **Next:** P5.5 chunk B — student announcement endpoints (thin router at
  `/api/student/announcements`, own schemas module, deps + `reset_singletons`), then chunk C, the
  exam calendar, which must ship honestly empty because no CAIE timetable data exists anywhere
  on this machine.

## 2026-08-10 — forty-fourth session — P5.5 chunks B and C

- **Did:** finished P5.5's remaining two chunks. **Chunk B** (`51657f8`) is the student
  announcement surface — a thin student-only router at `/api/student/announcements`
  (list / unread-count / mark-read), its own reader DTO module kept separate from the
  teacher composer's, 24 route tests + 11 schema-introspection tests. **Chunk C** is the
  exam calendar: migration 0017 (`exam_dates`), `ExamCalendarService` (ingest, strict
  payload parser, per-student read), `GET /api/student/exam-calendar`, 41 tests, D5.8.
- **The brief was wrong about chunk B and the code won again** — the sixth Phase-5
  instance. It predicted a new `deps.py` entry plus a `reset_singletons()` line; both
  already existed, because `get_announcement_service` has been there since P3.8. Reusing
  that singleton is not just less code: two instances would carry two clocks, and the
  clock decides whether a scheduled announcement is published, so a student and their
  teacher could have disagreed about it.
- **Learned, and it cost real time:** `sa.Enum(..., create_type=False)` **silently ignores
  the flag** — only `sa.dialects.postgresql.ENUM` honours it. The failure is nasty because
  `pytest` stayed green (tests build the schema with `create_all`) while `alembic upgrade`
  died on "type sessionmonth already exists". Same shape as P5.2's trap: the tests and the
  real migration path do not agree by default.
- **Learned:** this FastAPI version wraps an included router in an opaque `_IncludedRouter`
  with no `.path`, so a test that walks `app.routes` to assert a router's surface finds
  **nothing and passes for the wrong reason**. Caught only because I asserted an exact
  expected list rather than a subset. Read `app.openapi()["paths"]` instead.
- **Chunk C ships a table with zero rows on purpose (D5.8)** and that is the deliverable,
  not a gap. No CAIE timetable exists on this machine, so ingestion is built and nothing
  populates a row; the read path names *which* of three causes made a calendar empty, so a
  student who never onboarded is never told that Cambridge has not published dates.
  Four guards across both chunks verified by inversion, not asserted.
- **Next:** P5.6 — notifications inbox + web push (VAPID) with a headless-testable
  transport, and making `notification_preferences` actually gate delivery. It is the first
  P5 task with a genuine *consumer* for those preferences, which have been written and read
  by nothing since migration 0008.

## 2026-08-10 — forty-fourth session — P5.5 closed on a clean gate run

- **Did:** ran the outstanding full `./scripts/check.sh` on P5.5's three already-committed
  chunks and closed the task. **All 13 gates PASS, 0 skipped, exit 0; 2623 tests; coverage
  90.57%** (develop 90.18%, P5.4 90.48% — no drop); `alembic check` clean. Nothing was
  re-implemented; no defect surfaced. 6/12 Phase-5 tasks done.
- **Learned — a written-down trap paid off on first contact.** P5.4 cost ~10 minutes of gate
  time discovering that a new table needs *two* edits (the migration and `EXPECTED_TABLES` in
  `tests/test_db_schema.py`), and wrote that into STATE. P5.5 added two tables
  (`announcement_reads`, `exam_dates`), both registered in the same commit as their
  `create_table`, and the trap did not fire. That is the cheapest possible outcome and the
  argument for keeping these notes specific enough to act on.
- **Did:** recon for P5.6 by reading the models rather than trusting the phase plan. Three
  facts that change the task's shape: `notifications` exists with **zero writers anywhere**
  (`grep -rln "Notification("` outside `models/` returns nothing), `notification_preferences`
  **already** carries one boolean per `NotificationType` plus `quiet_hours_start/end`, and
  nothing in `lemely/` or `web/src/` mentions VAPID or push subscriptions. So "make
  preferences gate delivery" needs **no schema work at all** — only a consumer — and the
  push-subscription table is the single genuine migration in P5.6.
- **Next:** P5.6. Record the transport-seam design in DECISIONS.md before implementing
  (MISSION §4 mandates spec-before-code for this layer): a `NotificationTransport` protocol
  with a real VAPID impl and a recording double, the **inbox row as source of truth with push
  as a best-effort side effect**, and quiet hours suppressing the *push* but never the row —
  a student must not silently lose a notification for having received it at 2am.
- **Same session, continued into P5.6.** Recorded **D5.9** before any code (MISSION §4's
  spec-first mandate), then committed chunk A: migration 0018 + `notification_repo.py` + 60
  tests, all four backend gates clean, `alembic check` clean both directions.
- **The design call that matters:** a preference *type toggle* and *quiet hours* are
  different mechanisms and collapsing them is the bug. A toggle off suppresses the inbox row
  (content preference); quiet hours suppress only the push and always write the row (timing
  preference). Both proven by inversion. Safe only because a notification is a pointer and
  never the data — I wrote that condition into the module so a future type that *is* the sole
  record forces a revisit rather than silently inheriting the rule.
- **Learned:** Cairo is UTC+3 in August (Egypt reinstated summer time in 2023), so a
  hardcoded +2 would be wrong for half the year by exactly one hour — small enough to go
  unnoticed until a student is woken at 07:30. And `Session.execute` is typed as returning
  `Result`, which has no `rowcount`; mypy here forbids explicit `Any`, so the fix is a
  one-attribute `Protocol`, not `cast("CursorResult[Any]", ...)`.
- **Next:** P5.6 chunk B (VAPID transport + headless recording double), then chunk C (routes
  + the three action seams that can actually fire). Carrying to the Phase-5 limitations:
  `streak_warning`/`study_plan_reminder` are time-triggered and this build has **no
  scheduler**, so they ship as methods nothing invokes on a timer.

## 2026-08-10 — forty-fifth session — P5.6 chunks B and C1

**Did.** Built the notification transport seam (chunk B, `58fa04c`) and the inbox
routes plus the fail-open notify helper (chunk C1, `dbc5d9f`). Recorded **D5.10**
before writing chunk B, per the phase's spec-before-code precedent. 86 new tests;
ruff/format/mypy(207 files)/lint-imports clean throughout. `check.sh` still not run
since chunk A — it belongs at the end of chunk C2.

**Learned — the decision.** Web push here carries **no payload**: an empty RFC 8030
body with a VAPID auth header, and the service worker fetches the inbox. That is
just D5.9 §1 ("the inbox row is the source of truth, push is one delivery of it")
stated on the wire, and it keeps student notification content off third-party push
infrastructure entirely. What made the choice easy was not cost but *verifiability*:
hand-rolled RFC 8291 encryption cannot be honestly proven on a machine with no test
vector and no live push service, and a vector generated from my own implementation
would prove only that the code agrees with itself. Payload-less push needs no such
thing — the ES256 assertion is verified by decoding it with the public key.
`pywebpush` was measured rather than assumed (11 packages, including a second HTTP
stack) before being set aside.

**Learned — two traps, both cheap next time.** A router's `Annotated[...]` parameter
types must be **runtime** imports, not `TYPE_CHECKING`: FastAPI resolves them through
pydantic, so a type-checking-only name leaves an unresolvable ForwardRef and the route
raises on its *first request* rather than at import. And a new `lemely/web/schemas_*.py`
must join the `disallow_any_explicit` override list in `pyproject.toml` — every
existing schemas module already is.

**Verified rather than asserted.** Six guards proven by inversion across the two
chunks: attaching a push payload, folding a 503 into "subscription gone", signing the
endpoint path instead of its origin, plus C1's opted-out/quiet-hours split and the
fail-open paths driven by a service and a transport that raise.

**Next.** Chunk C2 — the three action seams. `grade_ready` is small and self-contained
(the seam sits beside the existing XP call in `student.py`); `announcement` needs a
school-wide recipient reader that does not exist yet; `at_risk_alert` must state
honestly that rule 3 (14 days inactive) cannot fire without a scheduler. STATE carries
the full recon of which lookup methods exist. Split C2 if it runs long — shipping
`grade_ready` alone is a real increment.

## 2026-08-10 — forty-sixth session: P5.6 closed on a clean gate run

**Did.** No code. Every P5.6 chunk was already committed (spec/D5.9, A, B, C1, and the
three C2 seams); the one outstanding item was the first full `./scripts/check.sh` since
chunk A. It came back **all 13 gates PASS, 0 skipped, exit 0 — 2767 tests, coverage
90.78%** (develop 90.18%, P5.5 90.57%: no drop), `alembic check` clean. P5.6 marked done;
7/12 Phase-5 tasks complete.

**Learned.** Nothing was red — and that is the observation worth keeping. Five chunks
spanning a migration, a push transport, seven routes and three award seams passed a
15-gate-minute run on first full contact. The per-chunk discipline (targeted test files
plus ruff/mypy/alembic after every commit) is what bought that, and it is cheaper than
the P5.4 pattern where `EXPECTED_TABLES` failed ten minutes into a run. The counter-case
still stands: a gate run that finds nothing is not a gate run that was unnecessary.

**Next.** P5.7 — the 3-device limit in the UI (G-10) and device management (G-11). It is
the **first Phase-5 task with a frontend leg**, so MISSION §6.8 applies for the first time
this phase: axe, Lighthouse ≥95, screenshots, `/impeccable audit`, visual compare. The
session registry itself is Phase-1 work (D1.11) and exists — read it before assuming a
backend gap, per this phase's seven-times-repeated lesson that the code beats the note.

## 2026-08-11 — P5.7: the device limit learns to ask first

**Did.** D5.12 before any code, then two chunks. Backend: `register_login` grew
`allow_eviction`, refusing a fourth slot from **inside** its existing `FOR UPDATE`
transaction (a preflight query would be a TOCTOU two tabs could both pass); `POST
/api/auth/login` maps the refusal to a **409** carrying the account's devices — after the
credential is verified, so an email address alone cannot enumerate a stranger's browsers —
and the client confirms by re-sending the same login. Frontend: G-10 in place of the login
form, G-11 at `/settings/devices` for all five roles. All 13 gates green: **2789 tests,
90.83% coverage**, and the new screen measured at **axe 0 violations, Lighthouse a11y 100**,
screenshots at three breakpoints.

**Learned.** Three things worth keeping. (1) `npx prettier --write` is not this repo's
formatter — no config, not a dependency — and it silently semicoloned eight files against
the house style; the web gate chain formats nothing, so never run a formatter it does not
run. (2) An inversion caught a test that passed for the wrong reason: scanning a response
body for "location" is trivially satisfied by a 200 that has no challenge in it at all. A
negative assertion needs a positive one beside it. (3) The spec asked for a rough location
in G-10 and this build has no geo-IP source and stores no IP — so the field is absent, not
guessed, because it is precisely the field a user would decide on.

**Next.** P5.8 — screens S-28..S-31. Two P5.7 gaps are recorded in STATE and belong to
later tasks, not to a future session's rediscovery: G-10 has no audit-registry entry (it
needs a seeded three-device account) and no nav entry yet reaches `/settings/devices`.

## 2026-08-11 — forty-seventh session · P5.8 chunks A and B

**Did.** Corrected P5.8's brief (S-31 had no backend: `XpService` was wired at
write seams only, nothing read it), then built chunk A — `GET /api/student/xp`,
the XP→level curve D5.1 §10 deferred here, `XpService.profile`/`xp_by_day`, and
D5.13 recorded before the code. 91 tests. Then chunk B — S-28, announcements +
exam calendar, with D5.8's three empty causes reaching the screen as three
distinct states. 13 vitest cases; all web gates clean.

**Learned.** Two things worth the ink. (1) **An inversion I ran disproved my own
decision record.** D5.13 §1 justified the integer level curve by claiming the
float form breaks at level boundaries; inverting the implementation left all 62
tests green, because at `100·N²` both the float operations are exact. Corrected
D5.13 in place rather than leaving a confident sentence that was untrue — third
instance this phase (P5.6 C2b, D5.7). **New rule: invert first, then write why.**
(2) **`npm run build` runs `tsc -b` over a wider project set than `npx tsc
--noEmit -p tsconfig.json`** — the bare form passed on a tree the build then
failed on twice. The build is the typecheck gate; the bare form is not.

**Next.** Chunk C (S-29 leaderboards + S-30 friends — read `Standings.tsx`'s
header first, it records what was deliberately removed rather than mocked), then
chunk D (S-31 on chunk A's route), then one UI-gate run for the whole task.

## 2026-08-10 — session 67: the gate went green because it did not know the screen existed

**Did.** Caught the exit of session 61's 31-minute P5.9 gate run (all 13 gates
PASS, 0 skipped, EXIT=0; 2927 tests, 90.91% coverage, 67 axe route-states, a11y
floor 96 — read off that run, never re-run). Then found the green was
incomplete: `audit.mjs` had **no entry for G-13**, chunk B's own notification
inbox. Added it, and the entry immediately produced the **first non-zero axe
count in this build** — 1 moderate `page-has-heading-one`, because the `<h1>`
lived inside the populated branch only and the empty state is the state this
screen ships in. Fixed across all four states. Also wrote and proved P5.10
(`e2e/reduced-motion.spec.ts`, 2 tests, no CSS), inverted properly. One full
`check.sh` in flight covering all three changes (`5df4807`).

**Learned.** (1) **A hand-maintained registry fails silently in the one
direction that matters**: a missing entry does not fail the gate, it removes the
screen from the gate. Third instance of that shape (`EXPECTED_TABLES` P5.4, the
`SeedContract` mirror P4.11) and the first where green was actively misleading
rather than merely incomplete. **Write the registry entry in the same chunk as
the screen.** (2) **The zero-at-any-severity standard is not enforced by
anything** — `check_ui_gates.py` fails on serious/critical only, so this
moderate would have passed `ui-thresholds`. That standard lives in whoever reads
the summary. (3) **D3.20 cost something concrete for the first time**:
`test.use({ reducedMotion })` is a type error on the pinned Playwright, and
`web/e2e/` is in no tsconfig include, so nothing would have caught it. Used
`page.emulateMedia` instead. (4) The waiting time also measured P5.11 point 10 —
only G-10 pays the three-edit seed-contract tax; the leaderboard-ordering rows
reuse contracted students and pay nothing.

**Next.** Read `/tmp/p59b-gate.log` (PID 1232528) for the `EXIT=` line — do not
relaunch it. Green closes **both P5.9 and P5.10** → 11/12, and P5.11 is next
with a brief that is now ten points deep.

## 2026-08-10 — session 68

**Did.** Found the second gate run alive at 5m36s (4/13, inside `pytest`) — the
PID that matters is the surviving `bash -c` wrapper **1232550**, which the
previous entry recorded wrongly as the already-exited `setsid` helper 1232528.
Attached, armed a Monitor on `EXIT=`/`FAIL`, relaunched nothing, touched no
source file. Working tree clean on entry; INBOX had no unhandled items.

**Learned.** The waiting time went into the half of P5.11 that no session had
ever looked at — points 1–11 all measure the four E2E flows, while the task
line's other clause (axe/Lighthouse/screenshots/visual compare) had never been
measured. New point 12, three findings. (1) **The screenshot corpus comes from
`audit.mjs`'s registry, not from `screenshots.spec.ts`** — that spec captures
only the five Phase-2.5 ids; the other 34 in `reports/phase-4/screens/` are
registry output. So P5.11's screenshot leg needs no new Playwright spec, just an
explicit `LEMELY_REPORT_DIR=reports/phase-5` re-baseline. (2) **`audit.mjs`'s
four-route exclusion list is false in every entry** — `/student/board` has been
audited since P5.8 (`:1960`), and `/student/subject/:code` runs on the real
`useSubject` hook rather than the mock data the list claims. The false statement
is in the operator-facing `log()` at `:2451` as well as the comment — which is
precisely the failure that same header documents happening twice before, so it
has now happened a third time *to the sentence describing the previous two*. The
G-13 miss inverted: present-and-falsely-declared-absent, plus three genuinely
unaudited live routes excused by a stale reason. (3) **`compare-screens` defaults
its baseline to `reports/phase-2.5/screens`**, so a bare run diffs Phase 5
against a 2.5-era corpus and buries any real regression; it also exits 0 by
design, so its output must be read, not trusted.

**Next.** Read `/tmp/p59b-gate.log` (PID **1232550**) for the `EXIT=` line — do
not relaunch it. Green closes **both P5.9 and P5.10** → 11/12, and P5.11 is next
with a brief that is now twelve points deep and covers both of its legs.

## 2026-08-10 — session 69

**Did.** Found the second P5.9/P5.10 gate run (PID **1232550**) alive at 11m18s,
4/13, inside `pytest` — attached, armed a Monitor, did **not** relaunch it, and
touched no source file, because the run is verifying this exact tree. `pytest`
cleared at ~17m (5/13). Working tree clean on entry; INBOX had no unhandled
items. The waiting time went into the one P5.11 mechanic no session had checked:
the announcement flow needs **two roles in one spec**, and nobody had asked
whether the suite has a role-switching idiom or whether the teacher's POST even
has a screen. Recorded as points **13** and **14**, and repaired point 9's
opening line, which my first edit swallowed.

**Learned.** (1) **The teacher's announcement POST has a real compose screen**
(`/teacher/announcements`), so the flow is genuinely through-the-UI per MISSION
§5 rather than an API-only setup step — and every locator it needs is already
accessible-name-addressable. (2) **Two roles cost nothing**: `injectSession`
(`seed.ts:184-207`) writes the session into `localStorage` before page scripts
run, which is the split `phase4-journey.spec.ts` already documents. (3) The class
checkbox's visible text is **exactly** `seed.class.name` — `routers/classes.py:211`
is `label=row.name`, verbatim, so no substring hedging. (4) S-28's read half needs
no markup change either: the title is a real `<h3>`, and opening *is* reading, so
one `Read it` click asserts the whole receipt round trip. **Three of the four E2E
flows now need zero a11y work; only S-29 and S-31 do.** (5) Two traps, both of
which fail as something other than what they are: `audience` defaults to
`"classes"` so the radio needs no click, which makes title+message+submit look
like the whole driver — but the unticked class checkbox gates the submit button's
`disabled`, so the spec clicks a dead button and dies as a **30s "element is not
enabled" timeout that reads as a hung app**; and `Read it` is **not** a unique
accessible name — it resolves only because the seed seeds zero announcements, so
it becomes a strict-mode violation the day any session seeds one.

**Next.** Read `/tmp/p59b-gate.log` (PID **1232550**) for the `EXIT=` line — do
not relaunch it. Green closes **both P5.9 and P5.10** → 11/12, and P5.11 is next
with a brief that is now fourteen points deep and covers both of its legs.

---

## 2026-08-11 — session 93 — **P5.12: Phase 5 is complete, merged and reported**

**Did.** Wrote `reports/phase-5/REPORT.md` (`1f6354a`) against the section structure
Phase 4 established, merged `feature/phase-5-engagement` into develop (`322118b`),
pushed, and retitled PR #3 to "Phases 0–5" with a Phase-5 section **appended** —
then verified all seven phase sections were still present afterwards, because
P3.11 found the PR body had silently lost a section once before. Nothing was
re-implemented and no gate was re-run: session 92's `EXIT=0` run is the tree that
merged. Pruned the Phase-5 section of `BUILD/STATE.md` from ~1930 lines to a
summary block per MISSION §8b (the file went 2351 → 396 lines).

**Learned.** Every headline figure was recomputed from the committed artifacts
instead of copied from STATE, and one of them was wrong: the axe route-state count
is **73** (`axe/_summary.json`'s own row count, one row per audited state), not the
**146** STATE carried — exactly double. Phase 4's report has the same shape (122
against a 61-row summary), so it is a propagated arithmetic error rather than a
coverage regression, and the verdict is unaffected: zero violations at every impact
however the states are counted. Corrected in the report with the reasoning, not
quietly restated. Two smaller ones fell out of the same recompute (8 routes below
Lighthouse performance 80, not 9; 44 route reports, floor 96 on `teacher-review`),
and testing every appendix path for existence caught two wrong file locations. This
is the same lesson the phase paid for four times in code — **a hand-copied figure
that nothing regenerates drifts, and it drifts toward looking better.**

**Next.** Phase 6 (hardening + ship) on a fresh `feature/phase-6-*` branch off
develop. P6.0 is reconnaissance; it should start from the `### Honest limitations`
blocks in every phase section of STATE, since `DELIVERY.md` must account for all of
them whether or not Phase 6 fixes them.

## 2026-08-11/12 — session 94 (Phase 6 started)

- **Did:** P6.0 recon + the 12-task Phase-6 plan; P6.1 closed both long-carried gate
  holes (D3.20 `web/e2e/` never typechecked → own tsconfig project, found one real
  `string | undefined` bug; D4.25 Lighthouse perf floor never enforced → real gate,
  scoped to `/student` as MISSION words it); P6.2 built the concurrency + load-sanity
  pass that never existed. Branch `feature/phase-6-hardening`, 5 commits.
- **Learned:** the 65–87 Lighthouse band across all 44 routes was one cause — a single
  1.3 MB bundle serving every route. Splitting took the entry chunk to 397 kB and the
  student floor from 70 to 89. Also: `XpService.award` had a live TOCTOU that let
  concurrency defeat the anti-farming caps, fixed with the lock idiom already used
  next door.
- **The lesson worth keeping:** two things I was handed as "verified" were not. A
  subagent's device-cap test passed with the lock it claimed to verify removed, and my
  own first inversion check misread pytest's output and looked flaky. Both were only
  settled by a counted loop. Inversion, repeated and counted, is the only thing that
  distinguishes a regression test from decoration.
- **Next:** P6.3 security re-review (authz matrix over every Phase-4/5 route + a
  reviewer sweep), then P6.4 Docker Compose — which is greenfield: no Dockerfile,
  compose file, deployment doc or DELIVERY.md exists anywhere in the repo.

## 2026-08-12 — session 95 (P6.3)

- **Did:** the Phase-6 security re-review. Rewrote the authz matrix as a *generated*
  one (`tests/test_authz_matrix_complete.py`): it derives the route set from the app
  and asserts it equals a declared table, so an undeclared route now fails the build.
  Added 21 real-minted-token cases and a recursive mass-assignment gate over all 39
  request-body models. Started P6.4 (Docker Compose) — greenfield.
- **Found:** nothing to fix. All 121 route operations were already guarded and every
  Phase-4/5 route keys its query on `auth.user_id`. **No production code changed in
  P6.3**, and that is the honest result rather than a shortfall — what was actually
  broken was the *method*, a hand-typed list whose coverage silently froze at Phase 3.
- **Learned — a test that mocks the thing upstream of the guarantee is not testing the
  guarantee.** My 403 sweep overrode `get_auth_context`, so it proved `require_role`
  given a correct context while being structurally blind to a token-decoding break.
  The reviewer caught it; the fix was tokens that are actually minted.
- **Learned — do not run a read-only reviewer against a checkout with an inversion in
  flight.** The reviewer read `deps.py` during the two minutes I had the role guard
  deliberately disabled and filed a Critical "something is mutating the auth guard on
  disk". Its observation was exact and its conclusion was wrong; I only knew because I
  was the cause. Serialise them, or say so in the brief.
- **Next:** finish P6.4 (verify the images actually build and the nginx `/api` proxy
  really reaches the backend), then P6.5 deployment docs.

## 2026-08-12 — session 101

- **Did:** confirmed P6.6 green (`EXIT=0`, all 13 gates, 0 skipped — the build's first
  fully green full-suite run) and closed P6.8. Built P6.10's seeder against the untracked
  `tests/test_seed.py` found on arrival, extracted `ensure_supabase_env` to
  `lemely/runtime/supabase_env.py`, and retired the `make seed` caveats from README,
  DELIVERY.md and `docs/deployment.md` (`b5bc7c7`, `e2ed097`).
- **Learned:** a hermetic test of an entry point tests everything except that it is an
  entry point — 12 green tests and a clean `mypy` did not stop `make seed` dying on the
  live stack. Verify entry points by running them, on a *clean slate*: an already-seeded
  DB cannot tell you whether `created` is right.
- **Also learned, the hard way:** a demo-data cleanup filter must be anchored to the demo
  constants, never to a domain suffix another seeder shares. `%parents.lemely.local`
  matched 206 rows, not 5. Harmless here (auth/mirror stayed consistent, and `seed_e2e.py`
  re-tags every run) but the pattern is the point.
- **Next:** poll `/tmp/check_p610.log` for `EXIT=`; then the fresh-clone acceptance run that
  closes P6.10, then P6.7's visual sweep, P6.9's §6 evidence, and P6.11.

## 2026-08-12 — session 102
- **Did:** found session 101's gate run alive at 4 minutes (PID 847893, 84-byte log) and did
  not relaunch — sixth consecutive session to make that call correctly. Cleaned the tree
  (harness MCP config only, `1e23540`), then closed **P6.9** by writing DELIVERY.md §6
  Evidence (`2b0e506`) and pruned STATE.md's header from 126 narrative lines to a 30-line
  read-this-first block (`7a38185`).
- **Learned:** the discipline §6 asks for pays immediately when you apply it to yourself.
  Re-running the measurements instead of copying them corrected two live figures — the E2E
  suite is 34 tests in 13 files, not the 30 STATE had carried since P5.11, and Phase-5's
  Lighthouse directory holds 45 files but **44 route reports**, because `_summary.json` is a
  list rather than a route and a naive `ls | wc -l` counts it. The a11y floor (96,
  `teacher-review`) and the 8 sub-80 performance routes both reconfirmed, so the phase report
  was right where it mattered.
- **Also:** §6.3 lists the figures no artifact holds yet as deliberately blank, each named
  with the task that fills it. A blank with an owner is honest; an estimate is not.
- **Next:** the `EXIT=` line, then P6.7's visual sweep, the fresh-clone run that closes P6.10,
  and P6.11.

## 2026-08-12 — session 103

- **Did:** closed **P6.10** by actually running the fresh-clone acceptance — cloned this branch
  at `be49d34` into `/tmp/lemely-fresh-1`, ran the documented commands from it, and checked
  every claim against the running containers. `make up` reached `EXIT=0` with both containers
  healthy, and **all five demo roles authenticate through nginx on :8080**, each confirmed by
  reading `/api/me/profile` back. Four defects fixed in `310fade` (D6.8), evidence artifact at
  `reports/phase-6/fresh-clone.md` (`fe8f514`), and DELIVERY.md §6.3's fresh-clone row filled.
  Also confirmed the earlier in-flight run: `/tmp/check_p610.log`, `EXIT=0`, all 13 gates.
- **Learned:** **an empty environment variable is not an unset one.** `docker-compose.yml`
  forwards optional credentials as `${VAR:-}`, so pydantic built `SecretStr("")` — not `None` —
  and every `is None` "not configured" check answered *configured*. `/api/health` returned
  `apiKeyConfigured: true` on a stack with no Gemini key at all, and GoTrue's explicit "key is
  not configured" error never fired: an empty `apikey` header went out instead, which **local
  Kong accepts and Supabase Cloud would reject**. Works locally, every test green, broken in the
  deploy that matters. The general form: `if value is None` is a claim about *presence*, never
  about *usability*.
- **Also learned:** the value of this task was entirely in running the documented commands **as
  written** rather than the ones I knew worked. `pip install -e ".[dev,ui]"` omits the `db` and
  `web` extras, so `make db-migrate` and `make seed` both failed outright from a clone, and
  `python` is not a command on Debian-family systems. All 13 gates had gone green with 0 skipped
  on this same tree hours earlier and saw none of it — gates run inside an environment that is
  already correct.
- **Then:** re-ran the full suite on `310fade` because config.py is loaded by every surface.
  **`EXIT=1` — the first non-green run since P6.6.** The config change is clean; the one failure
  is `ui-thresholds` on `student-standings` (performance 74 < 80), and pulling the JSON before
  the scratch dir was overwritten shows it is **CLS 0.386, not bundle weight** — TBT, LCP and
  Speed Index are all healthy. Plausibly a cost of P6.1's own `React.lazy` fix on the very route
  P6.1 reported as 70→92.
- **Next:** P6.7's visual sweep, which now starts with that finding already diagnosed on its
  STATE entry rather than rediscovering it. Then the P6.10 follow-up (the OTP-code-in-the-log
  claim, unconfirmed inside the container) and P6.11.

## 2026-08-12 — session 104 (P6.7 closed, P6.10-followup closed, P6.11's run launched)

- **Did:** closed **P6.7**, the full-product visual QA sweep. `AUDIT_EXIT=0`,
  `check_ui_gates.py` EXIT=0, **`removed: 0` against both the Phase-2.5 and Phase-5 baselines**.
  48 screens / 246 screenshots, 73 axe route-states with zero violations at any impact, 44
  Lighthouse reports with an a11y floor of 96, zero console errors, zero horizontal scroll.
  Fixed the one live defect (`student-standings` CLS), added the per-role contact sheets MISSION
  asks for and nothing produced (`web/scripts/contact_sheets.mjs`), and wrote
  `reports/phase-6/visual-qa.md` + `impeccable-audit.md`. Then closed **P6.10-followup** by
  fixing the container's logging rather than weakening the two documents that described it.
  Launched P6.11's full-suite run detached on the clean tree at `66950f3`.
- **Learned — the artifact you already committed may hold the answer you were about to re-measure.**
  The standing hypothesis for the CLS failure was `RouteFallback`. It was wrong, and
  `reports/phase-5/lighthouse/student-standings.json` had said so for a phase: its `layout-shifts`
  audit names `<section aria-labelledby="s29-subjects">` in both recorded shifts. Reading it cost
  one command and replaced an 11-minute measurement plus a plausible wrong fix. It also showed
  CLS was **0.220 back in Phase 5**, so this was never the P6.1 regression it looked like — the
  shifts only score when the skeleton paints before the data lands, which is the whole reason the
  same tree scored 92 on one run and 74 on the next.
- **Also learned — the corpus has three producers and running one silently drops the others.**
  The audit runner covers 43 screen ids; `screenshots.spec.ts` and `correct-paper.spec.ts` own
  the other seven. Running only the first made the compare report those seven as **`removed`** —
  the exact signal MISSION §4 defines a blocker by, from screens that had never regressed. A
  regression detector that is fed a partial candidate reports a catastrophe. Enumerate the
  producers before believing the count: `grep -ln "SCREENS_DIR" web/e2e/*.ts`.
- **Also learned — a silent gate is not a passing gate.** `npx impeccable detect` returns `[]`
  for `web/src/` and also for a file written deliberately to trip it, so MISSION §6 gate 8 has
  been green and vacuous. The tell was cheap: feed the detector something it should catch. Worth
  doing to any check whose output is "nothing".
- **Also learned — `logging.lastResort` is pinned at WARNING, and that is how a container loses
  every INFO record without an error.** uvicorn's `LOGGING_CONFIG` has no `root` entry, so
  `dictConfig` leaves root handler-less and `lemely.*` INFO propagates into nothing. P6.10 saw
  the missing OTP line; the real scope was every `lemely.*` record below WARNING.
- **Next:** P6.11 — poll `/tmp/check_p611.log` for `EXIT=`, write `reports/phase-6/REPORT.md`,
  merge to develop, push, update PR #3, ntfy, then set `status: COMPLETE`.

## 2026-08-12 — session 105 — P6.11: the build is complete

- **Did:** polled the in-flight gate run to `EXIT=0` (**all 13 gates PASS, 0 skipped**), then ran
  a **separate serial** `pytest` for the figures `check.sh` does not hold — **3508 tests, 3502
  passed / 6 skipped / 0 failed, 90.92% coverage** (Phase 5: 2927 / 90.91%, so no drop). Wrote
  `reports/phase-6/REPORT.md`, closed the last two `DELIVERY.md` §6.3 rows, added **D6.9**,
  merged to develop (`dd260f2`), pushed, retitled PR #3 to "Phases 0–6" with a full Phase-6
  section and left it **open**, and set `status: COMPLETE`.
- **Learned:** *a green gate is a statement about a tree, not about a branch.* P6.6 ended `EXIT=0`
  and three commits landed after it, one of them product code — so the verdict was true of a tree
  HEAD had already left. The cheap fix is one command: `git diff <run-tree>..HEAD -- lemely web
  scripts tests …` must be empty before the verdict is quoted. Ran it; it was.
- **Learned:** the six skips had been carried as a number for three phases. Re-derived them in two
  short targeted runs: 2 live *billed* accuracy tests, 4 gated on Supabase keys being exported.
  None broken — but "6 skipped" was a hand-written mirror, the exact failure this build paid for
  four separate times (`EXPECTED_TABLES`, the seed contract, the version string, the seeder stub).
- **Next:** nothing. The supervisor stops on `status: COMPLETE`. PR #3 is open for Habeeby to
  merge — it is deliberately not merged (MISSION §4). `DELIVERY.md` is the entry point.

## Session 106 — 2026-08-12
- **Did:** nothing to the product. Resumed on `status: COMPLETE`, clean tree, no unhandled INBOX
  item, B1–B3 resolved, develop pushed, PR #3 open. Declined to start Phase 1's opportunistic
  D1.9 backlog: product code landing after P6.11's `EXIT=0` would break the one property that run
  established, that the verdict describes the shipped tree.
- **Found:** **GitHub Actions has been red on PR #3 since ~2026-08-09 while all 13 local gates are
  green.** CI installs the dev extra fresh and `pyproject.toml:45` pins only `ruff>=0.7`, so the
  runner resolved **ruff 0.16.2** against this venv's **0.15.20**. 0.16 enforces **RUF036**;
  `notification_prefs_repo.py:110-111` and `student_profile_repo.py:164+` write
  `X | None | _UnsetType`. Locally ruff check and ruff format --check both pass.
- **Learned:** *an unpinned linter is a gate whose verdict changes without a commit.* Same shape as
  P6.6's VAPID assertion — a red that arrives on a calendar rather than on a change, invisible to
  every local run. A phase-end full suite catches the dated ones; only CI catches this one.
- **Next:** nothing autonomous. Copilot's PR #4 already proposes the dependency alignment, so the
  fix is in flight and merging is not mine (MISSION §4). One line either way: cap `ruff` in the dev
  extra, or take the two RUF036 autofixes.

## 2026-08-12 — session 108
- **Did:** nothing but confirm, which was the whole job. Resumed on a clean tree, `status: COMPLETE`,
  no unhandled INBOX item, B1–B3 resolved. A CI run for HEAD (`36074a2`) was already in flight, so I
  watched it to its verdict rather than starting work that would invalidate it.
- **Result:** **`completed / success` — all five jobs green** (`test (3.12)`, `test (3.13)`,
  `test (3.14)`, `web`, `pre-commit`). The **first green CI run of the build**; every run before it
  failed back through 2026-08-09.
- **Learned:** sessions 106/107 could diagnose the drift locally but could never *close* it locally —
  the failure class was "CI resolves fresh and this venv does not", so only the runner's own verdict
  settles it. `uv pip compile` predicting `gradio==6.19.0` / `mypy==2.1.0` / `ruff==0.15.20` was good
  evidence; it was not proof. Now local gates and remote gates agree about the same tree.
- **Next:** nothing autonomous remains. Both PRs (#3 Phases 0–6, #4 Copilot's stale and partly
  harmful CI attempt) are open and Habeeby's to merge or close (MISSION §4). Declined again to start
  Phase 1's opportunistic D1.9 backlog: landing product code now would break the property that both
  green verdicts describe the shipped tree.

## 2026-08-12 — session 110: three sessions' worth of docs were never actually on the remote

- **Did:** resumed on a complete build — tree clean, INBOX fully handled (both items `- [x]`),
  BLOCKERS B1/B2/B3 all RESOLVED, no `BUILD/PAUSE`, no orphaned `pytest`. The one real finding was
  in `git status -sb`, not in any of the state files: **`develop` was 3 commits ahead of
  `origin/develop`** — `92e4beb` (the STATE prune), `49f06bc` (the DELIVERY §5.5 fix) and
  `cb21675` (the Gemini-ledger re-read). Pushed them; `5cd56f8..cb21675`.
- **Why it mattered more than "some docs were local."** PR #3 (develop → main) is open and is
  Habeeby's to merge. It renders `origin/develop`, so for three sessions the PR was showing the
  **1012-line STATE.md that session 109 had already pruned**, a `reports/phase-6/REPORT.md` whose
  §5.5 claim was still untrue, and the stale `gemini_spend_usd` mirror. Every one of those commits
  exists to make the record honest for a human reading it on GitHub, and none of them had reached
  the place that human looks. A clean working tree says nothing about the remote.
- **Learned:** the resume protocol's tree check (`git status --short`, empty) and `status: COMPLETE`
  both passed while the shipped artifact was three commits stale. **Check `git status -sb` for the
  ahead/behind count, not just the porcelain file list** — "clean" and "pushed" are different
  properties and this build's own §5 requires the second.
- **Next:** nothing product-side. The D1.9 backlog item stays deliberately unstarted (starting it
  would put code after P6.11's closing `EXIT=0`, which that run existed to establish). Both PRs
  stay open — merging is Habeeby's call, MISSION §4.

## 2026-08-12 — session 109: STATE.md had outgrown the one file every session must read

- **Did:** resumed on a complete build — tree clean, INBOX fully handled, develop pushed, nothing
  in flight. Found a CI run already running on HEAD (`5cd56f8`, docs-only) and set it watching
  rather than starting a second. Then pruned `BUILD/STATE.md` per MISSION §8b: **1012 lines /
  ~34k tokens → 227**, collapsing eight phases of per-task narrative into a report/decision table
  and keeping the operational and environment knowledge **verbatim**, because that is the part a
  resuming session actually spends tokens rediscovering.
- **Why it was worth doing on a shipped tree:** the file had passed the point where it could be
  read in one call — my own first `Read` returned 62% of it with a "PARTIAL view" cap. A single
  source of truth that no session can read in full is not one. Verified the record was safe
  elsewhere *before* deleting anything: `DELIVERY.md` §5 carries all six limitation subsections
  (148 lines), each phase's §7 carries its own, and D0.1–D6.10 all exist.
- **Learned — the check I nearly got wrong twice.** `grep -c "^### D6\." DECISIONS.md` returned
  **0**, which reads exactly like "the Phase-6 rationale was never recorded" — the one fact that
  would have made this prune destructive. It is a heading-level artifact: the file is newest-first
  and switches from `###` to `##` at D5.8. A second grep pinned to `##` then missed D4.1–D4.4.
  **Match the identifier, not the formatting** (`grep -oE "\bD6\.[0-9]+"`); a zero from a pattern
  pinned to incidental syntax is not evidence of absence. Recorded in STATE so the next prune
  starts with it.
- **Also corrected:** the phase table said D0.1–D0.6; the real range is D0.1–**D0.7**.
- **Next:** the green CI verdict (`31564822523`, `36074a2`) still covers HEAD's code —
  `git diff 36074a2..HEAD -- lemely web scripts tests Makefile pyproject.toml .github` is empty,
  so every commit since is docs. Both PRs stay open; merging is Habeeby's call (MISSION §4).

## 2026-08-12 — session 112 (verification only; no product change)

- **Resume checks, all clean.** INBOX has no unhandled `- [ ]`; working tree clean; `git status -sb`
  shows `develop...origin/develop` with **no ahead/behind** (the check session 110 added after
  finding three unpushed commits); no orphaned `check.sh`/`pytest` under PID 1; no `BUILD/PAUSE`;
  BLOCKERS' last entry is RESOLVED. `status: COMPLETE` stands — all phases done, PRs #3 and #4 open
  and Habeeby's call.
- **The one thing that was not settled: CI on HEAD.** STATE's green claim named `31567025713` on
  `e32a3d1`, but a run was **`in_progress` on `4b042e6`** at that moment and went unmentioned — so
  the recorded verdict was about the parent commit, not HEAD. Watched it to completion rather than
  inferring: `31567949171` on `4b042e6` → **`completed / success`**, the third consecutive green.
- **Learned.** "CI is green on HEAD" decays silently the moment another commit lands; the previous
  run's conclusion says nothing about the newest SHA. `gh run watch <id> --exit-status` settles it
  in one blocking call for ~the cost of guessing wrong. Recorded in STATE next to the green claim,
  which is the only place a future session will look.
- **Deliberately did nothing else.** The remaining non-done item in the whole build is Phase 1's
  opportunistic D1.9 backlog, left unstarted on purpose: touching `lemely/` would put code after
  P6.11's closing `EXIT=0`, the one property that run exists to establish. Docs-only is the safe
  work on a shipped tree.
- **Next:** nothing queued. A future session should re-check INBOX, re-confirm CI against the
  then-current HEAD, and otherwise leave the tree alone until Habeeby merges or sends a directive.

## 2026-08-12 — session 113 (verification only; no product change)
- **Resumed on a shipped, COMPLETE tree.** INBOX had no unhandled items, `git status -sb` showed
  `develop...origin/develop` with no divergence and no leftovers, and BLOCKERS B1 is RESOLVED. The
  only non-done checklist item is Phase 1's opportunistic D1.9 backlog, left unstarted on purpose.
- **Acted on the previous session's own directive.** `24e223f` ("watch CI on HEAD instead of
  inheriting the previous run's verdict") had itself pushed HEAD past the last verified SHA, so the
  green in STATE was again about a parent commit. Watched run `31568906164` on `24e223f` to
  completion: **all five jobs `success`** — the fourth consecutive green.
- **Learned (a trap that would have let a red through).** `gh run watch <id> --exit-status | tail`
  prints `WATCH_EXIT=0` regardless of the run's outcome — the pipeline returns `tail`'s status, not
  `gh`'s. The verdict came from `gh run view --json conclusion,jobs` instead, which is also the
  only form that names which jobs passed. Recorded in STATE beside the green claim.
- **Noted the recursion, not just the fact.** Every docs push to `develop` triggers a fresh
  `ci-refs/pull/3/merge` run, so the session that records "CI green on HEAD" is the reason the next
  session's HEAD is unverified. That is now written down so session 114 expects it rather than
  rediscovering it.
- **Spend unchanged:** `outputs/gemini_spend.json` reads **$0.19750 / $8.00** (read from the
  ledger, not from STATE's mirror). No Gemini calls this session.
- **Next:** nothing queued. Re-check INBOX, re-confirm CI against the then-current HEAD, and
  otherwise leave the tree alone until Habeeby merges PR #3/#4 or sends a directive.

## 2026-08-12 — session 114

- **Did what 113 asked, then stopped the thing that asked it.** Watched run `31569918054` on
  HEAD `2d6fb78` to completion — **all five jobs `success`**, the fifth consecutive green.
  Verdict taken from `gh run view --json conclusion,jobs`, and `gh run watch` was run
  *unpiped* so its `--exit-status` meant something (113's trap, avoided).
- **The real finding: STATE asserted a diff was empty without running it.** For four sessions
  this file said `git diff 66950f3..HEAD -- lemely web scripts tests` is empty, and used that
  to argue P6.11's closing `EXIT=0` still describes HEAD. It returns **10 changed lines in
  `notification_prefs_repo.py` and `student_profile_repo.py`** — `7f11f58`'s RUF036 union
  reorderings. The conclusion survives (reordering `X | None | _UnsetType` binds nothing at
  runtime or in mypy, and `web/` really is untouched, so the visual leg carries outright) but
  the evidence for it did not. Same failure mode the file warns about twice: a hand-copied
  claim nothing regenerates.
- **Learned — the CI loop was self-sustaining by construction.** Sessions 108 and 110–114 each
  spent a whole run confirming CI on a tree no session had changed, because the docs commit
  recording the green *is* the push that unverifies the next HEAD. Noting the recursion (113)
  did not stop it; only a rule that terminates does. STATE now carries one: a docs-only commit
  can reach exactly one of CI's five jobs (`pre-commit`, via the markdown hooks), so run
  `pre-commit` locally and check the code/pins diff — watch a run only when code or pins moved.
- **Spend unchanged:** `outputs/gemini_spend.json` reads **$0.19750 / $8.00** (from the ledger).
  No Gemini calls this session.
- **Next:** nothing queued, and deliberately no CI re-check. The build is COMPLETE; PRs #3 and
  #4 are Habeeby's call. A future session should read INBOX and otherwise leave the tree alone.

## 2026-08-12 — session 115: the last open item was a decision wearing a chore's clothes

- **Did — closed D1.9, the build's last non-done checklist item, as won't-do (D6.11).** The
  previous session's rule held: I did not re-verify CI. Instead I read the one thing six
  sessions had deferred without opening. D1.9 reads like cleanup ("migrate CLI + Gradio history
  to the DB, then delete `lemely/io/history_store.py`"), and STATE justified skipping it on
  process grounds — *code after P6.11's closing `EXIT=0`*. Both framings were wrong.
- **Learned — the two history stores have incompatible id contracts, so there was never a
  migration to do.** `parse_user_id` (`lemely/db/history_repo.py:128`) raises on any non-UUID
  `student_id`, and `append` requires a row that already exists in `users` (FK enforced). The
  CLI's `--student-id` is a free-form label — its own tests pass `alice`, `bob`, `test_student`,
  every one of which raises under the DB store. "Migrate the CLI" therefore means *give three
  offline commands a hard Postgres dependency*, which is a regression traded for a deletion.
- **Learned — D1.9's text under-counted its own blast radius.** It names CLI and Gradio; it
  never mentions that `tests/test_web_teacher.py` uses the JSON store as the in-process double
  for `HistoryStoreProtocol`. Deleting the class drags ~1000 lines of teacher-analytics tests
  onto live Postgres or a new fake, to remove 147 lines of working, tested code.
- **Learned — "opportunistic backlog" is where an unmade decision hides.** Six sessions carried
  this as a chore because the checklist called it one, and a chore is easy to defer without
  reading. The cost of finally reading it was three greps. **A deferred item nobody has opened
  has an unknown size, not a small one.**
- **Not done deliberately:** no code touched, so no gate run and no CI watch — docs-only, per
  STATE's terminating rule (verified `pre-commit` locally, code/pin diff unchanged).
- **Spend unchanged:** `outputs/gemini_spend.json` reads **$0.19750 / $8.00**. No Gemini calls.
- **Next:** genuinely nothing. The build is COMPLETE with **zero open checklist items**; PRs #3
  and #4 remain Habeeby's call. A future session should read INBOX and otherwise stop.

## 2026-08-12 — session 115: the build shipped, and the last open loop closed itself

- **Did:** read INBOX (no unhandled `- [ ]`), MISSION, STATE, BLOCKERS and the log. Found the
  one fact STATE.md still had wrong: it said "two PRs are open and both are Habeeby's call".
  They are not. **Habeeby merged PR #3** (`74d33e6`, develop → main, Phases 0–6) and **closed
  PR #4**. Corrected STATE.md's header and the PR bullet. No code touched.
- **Verified rather than assumed:** `git rev-list --left-right --count origin/main...origin/develop`
  is `1 0` and `git diff origin/main..origin/develop` is **empty** — main is the merge commit
  plus everything develop had, so all eight phases are on `main`. Working tree clean, `main`
  level with `origin/main`.
- **Learned — the last stale fact in a finished build is the one that looks like a task.**
  "PR #3 is open" reads as an outstanding item even though the orchestrator is forbidden from
  merging it (MISSION §4), so it survived as a permanent almost-todo. It is exactly the shape
  of the CI loop sessions 108 and 110–114 burned themselves on: something that *looks*
  actionable, is not, and re-presents itself every session. Fixing the record is the only way
  that class of loop ends.
- **Not done deliberately:** no gate run, no CI watch. Docs-only change; per STATE's
  terminating rule the code/pin diff is what CI can see, and it is unchanged.
- **Spend unchanged:** `outputs/gemini_spend.json` reads **$0.19750 / $8.00**. No Gemini calls.
- **Next:** nothing. The build is COMPLETE, **merged to `main`**, zero open checklist items,
  zero open PRs. A future session should read INBOX and, absent a new directive, stop.

## 2026-08-12 — session 116: the shipped tree had a login-breaking bug, uncommitted, untested by design

- **Did:** found a real, complete, *uncommitted* fix in the working tree (`web/src/lib/uuid.ts`
  + its test, both untracked; `storage.ts` and `CameraCapture.tsx` modified). Verified it rather
  than wip-committing it: web tests **460 passed / 16 files**, `tsc -b --force`, oxlint, build,
  and all ten pre-commit hooks green. Committed as `7bbf256`, pushed, recorded **D6.12**, opened
  **PR #6** to `main`.
- **The bug:** `crypto.randomUUID` is **secure-context-only**. `getDeviceId` called it bare on
  the **login path**, so on any plain-HTTP non-localhost origin — LAN IP, `*.local`, tunnel,
  i.e. the Docker-Compose deployment reached from a second device — sign-in threw and the form
  rendered `crypto.randomUUID is not a function` as its own error. `crypto.getRandomValues` is
  not gated, so the v4 layout is now built from it.
- **Learned — a condition every harness shares is a condition no harness tests.** 13/13 gates,
  3508 tests, 73 axe route-states, 44 Lighthouse reports, all green over a codebase where
  sign-in was dead outside localhost. Every harness in this build drives `http://localhost`,
  and localhost is a secure context by definition. The gates were uniform, not weak. Third of
  its family after D6.9 (vacuous detector) and P6.6 (dated VAPID assertion).
- **Learned — "docs-only is the safe work on a shipped tree" was itself the trap.** It is the
  rule that kept six sessions writing prose, and it was false the whole time: real, tested,
  user-facing code was sitting in the tree unread. The resume protocol's "clean up a dirty tree
  with a wip commit" would have buried it under a `wip:` message. **Read the dirty tree before
  deciding what it is.** The real distinction is changed-input vs unchanged-input, not
  docs-vs-code.
- **Spend unchanged:** `outputs/gemini_spend.json` reads **$0.19750 / $8.00**. No Gemini calls.
- **Next:** PR #6 is Habeeby's to merge. The one open piece of work D6.12 names but does not do:
  a harness that exercises the SPA over a **non-localhost HTTP origin** — the only thing that
  would close this defect class rather than this defect.

## 2026-08-14 — redesign session 4: the gate that could not reach the pages it was measuring

- **Did:** closed Phase 6.5 (5 of 5). D6.8 timed out unanswered after nine polls, so §10's
  default applied: `/data`, "How your data is handled", one factual page linked once from the
  marketing footer, no ToS and no privacy policy. Fixed the `adapt` gate, which turned out to
  be unable to reach 27 of its 35 surfaces, and then fixed the 10 findings its first honest run
  produced. Recorded **D6.10**.
- **The bug:** `adapt_audit.mjs` served `dist/` on port **4321** while six of the `act`
  callbacks it *imports* from `capture_surface.mjs` navigate by absolute URL to **4319**. The
  run died at the `landing` surface, **eighth of thirty-five**, with `ERR_CONNECTION_REFUSED`,
  so everything after it was never measured at any width. Live since Phase 6.1's own wip commit.
- **Learned — the restatement was in the one file that had already named the rule.** That
  script's header opens with "this walks the SAME registry that harness does — imported, never
  restated". The registry was imported. The port was restated. D6.7 asked "what re-states a
  value, and what checks that the two still agree?" and this is the fourth file this phase has
  had to ask it of.
- **Learned — the failure mode was not the crash, it was the crash's absence.** The run only
  survives if *something else* is listening on 4319, and then a stranger's server answers a
  question about our build. That is BLOCKERS B4 ("runs against whatever is already on port
  8000") inside the gate written three phases after B4, and it was watched happening live: a
  leftover `vite preview` from a diagnostic made the failure vanish, because `server.kill()`
  kills the `npx` wrapper and not the vite process under it. The gate now checks the child's
  exit code before believing the fetch, and names the port when it refuses.
- **Learned — a gate that discards the evidence of its own failure makes every failure look
  like a flake.** Both server pipes were opened and never read, so vite's own "Port 4319 is
  already in use" went into a buffer nobody emptied and took a throwaway script to recover.
- **Learned — `sr-only` does not mean what it says on a `<table>`.** Four of the ten findings
  were `ChartDataTable`'s hidden copy measuring **357px** wide, because auto table layout
  treats `width: 1px` as a minimum. Invisible, silent, and reachable only by a gate that
  measures geometry through `overflow-x: clip`. The tempting fix was one line in the gate's own
  sr-only exemption, which would have turned all four green and been the waiver-that-swallows-
  the-check pattern; the wrapper is the honest fix.
- **Learned — the same run caught this phase's own defect.** The other six findings were the
  new footer link wrapping to two lines at 320px and pushing "Parent sign in" onto two as well.
  That is the argument for repairing a gate *before* the work rather than after it.
- **Spend unchanged:** `outputs/gemini_spend.json` reads **$0.19750 / $8.00**. No Gemini calls.
- **Next:** Phase 7 (final QA and report). It should not trust the "745 page-states, 0 findings"
  number D6.1 recorded for 6.1: `reports/redesign/p6-adapt/` was empty with nothing committed,
  and that run cannot be reproduced from this tree. This session's committed `findings.json` is
  the honest baseline.

## 2026-08-21 — accuracy run-2026-08-21-a: #31 landed, #25 caught with an inert denominator

- **#31 (M0.7a) landed.** `accuracy-review` returned merge-with-fixes, no blocker; PR #68
  squash-merged to `develop` as `47977cf` with all five CI jobs green on `0c493c9`. Board
  Done, finish comment posted, branch pruned.
- **`accuracy-pr-land` opened the PR but could not close it.** Its CI watch hit the 690s cap
  with the pytest matrix still pending and correctly reported `timeout` — neither pass nor
  fail. The merge was finished by hand once all five jobs reported. This is the third run to
  meet that cap; the workflow's watch window is shorter than a 17-minute pytest matrix.
- **Learned — a watcher that cannot run its own tools reports success.** The first CI poll
  loop printed `SETTLED after 60s` while three jobs were still pending. The cause was not
  `gh`'s exit code (my first guess) but that **`jq` is not installed in this shell**: `jq -e`
  failed, and the negated test read that failure as "nothing pending". A missing binary and
  a green build were indistinguishable. `gh --jq` is the fix; the absence is now recorded in
  the state file.
- **Learned — the review found the resume pointer had been blinded.** `ACCURACY-STATE.md`
  carried two `in_the_middle_of:` keys, the first empty, and the supervisor reads with
  `grep -m1`. Every handoff note written into that file was invisible to the next run. That
  is the same class of failure §7 records as having stalled #56 for seven runs, sitting in
  the one file whose only job is to survive the session.
- **#25 (M0.1) implemented, blocked, no PR.** `ready_for_pr: false`, review verdict blocked.
  Two mechanical blockers fixed here: the committed tree failed `ruff format --check`
  (the implementer's auto-fix was never amended into the commit, so its "pre-commit green"
  described a tree that was never committed), and the working tree was dirty.
- **Learned — the blocking finding was a denominator that silently did nothing.**
  `_distinct_leaves` keys on `(paper_id, question_id)` while `harness.py:245` hardcodes
  `fixture_variant=None` and the corpus encodes the variant *inside* `paper_id`. The collapse
  removes nothing: 68 records where spec §3.3 requires 28 distinct leaves. Its tests passed
  because they fed mark-point rows that `_question_level()` strips before the collapse ever
  runs — the reviewer proved it by monkeypatching `_distinct_leaves` to the identity and
  watching every assertion stay green. An inflated denominator with a green test defending it
  is precisely D18, the defect M0 exists to remove.
- **Ordering — `board next` was overridden deliberately.** It selects #32 (M0.8), but spec §4's
  tighter order is M0.0 → M0.1/M0.2 → M0.8, and #25 was open only because nobody moved it out
  of Backlog. #32 would have jumped the queue; §8 says an ordering violation invalidates the
  measurement.
- **Spend unchanged:** no Gemini calls this run; ledger still $0.4026 (a lower bound until
  M0.2's corrected table is exercised).
- **Next:** re-run the implement stage on the existing #25 branch for the three structural
  MUST-FIXes. No new branch, and no assertion weakened to go green.

## 2026-08-21 — accuracy run-2026-08-21-a (cont.): M0.1 landed, and three false-green agent reports

- **#25 (M0.1) landed.** PR #71 → `develop` as `d5a8424`, CI green on all five jobs. M0's Done
  count is now 4 of 11 (#56, #26, #31, #25). The spec §4 ordering constraint is finally
  satisfied, so `board next`'s selection of #32 no longer needs overriding.
- **#69/PR #70 landed first, by necessity.** The supervisor-tooling fix had to reach `develop`
  *before* #25 could drop it, because a #25 that carried the removal would have deleted those
  files from `develop` on merge. Ordering, not preference.
- **Learned — the collapse rule the review asked for would have inverted the defect.**
  `_distinct_leaves` counted 68 records where the spec requires 28 leaves; the prescribed fix
  was "a deterministic (not first-seen) collapse rule". Taken literally that keeps the first
  of `correct` < `partial` < `wrong` — every leaf represented by its *correct* variant, and
  accuracy driven toward 100% by construction. An honest denominator bolted to a dishonest
  numerator is worse than the inert bug it replaces, because it looks rigorous. DA6 derives
  the outcome from all variants instead (correct iff *every* scored record is correct).
- **Learned — my own decision record was wrong within the hour.** DA6 asserted
  "`exclusion_funnel` counts leaves and is unaffected by the outcome rule". The implementer
  showed it false: the funnel collapses without a `_scored` prefilter while `wilson` filters
  first, so one leaf could be scored+correct to `wilson` and excluded to the funnel — the
  funnel contradicting the denominator it exists to explain. DA6a fixes it and pins
  `exclusion_funnel` scored-count == `wilson` n with a real-corpus test. The agent was right
  to stop and ask rather than invent the policy.
- **Learned — `params_fingerprint` could not tell two models apart.** It hashed
  `temperature|top_p|seed|thinking_budget` and omitted the model, while the codebase's own
  canonical fingerprint hashes seven components. Two different models both produced
  `ce5aa7b9ccad`. Once M0.3's A/B reads that field it reports "same parameters" — a false zero
  delta manufactured by the instrument rather than observed in the models.
- **Learned — agent reports were false-green three times in one session**, each caught only by
  re-running the gate rather than accepting the claim: a "pre-commit green" describing a tree
  that was never committed (the auto-fix was never amended in); a "ruff clean" with a live
  D205; and a report citing commit shas that were not on the branch. The last one was a
  *concurrency* symptom — see below.
- **Learned — two agents ran on the single shared worktree at once, and one rewrote the branch
  history.** Four commits left the branch under me. §3.2 forbids exactly this. It was benign
  only because `git diff` between the old and new tips was empty and both produced an
  identical diff against `develop` — verified, not assumed. The same race could as easily have
  destroyed work. Never dispatch an implementer while another is live.
- **Learned — the state-file corruption was a tool bug, and my first fix was a symptom fix.**
  `_parse_state_header` tested `": " in line`, so an empty-valued key was invisible; `state set`
  then *inserted* a duplicate and the supervisor's `grep -m1` read the empty one. Every handoff
  note was invisible to the next run — the §7 failure that stalled #56 for seven runs. Repaired
  by hand during #31, it silently returned. Now #69, with 6 tests, 4 failing against the old
  parser.
- **Also learned — a CI watcher that cannot run its own tools reports success.** A poll loop
  printed `SETTLED` while three jobs were pending, because `jq` is not installed and the
  negated `jq -e` read its own failure as "nothing pending".
- **Deferred and filed rather than left in a state file:** #72 (`EvalRecord`s are discarded, so
  the `run_id` → `RunManifest` join is unobservable outside `measure_accuracy`) and #73
  (`_build_run_manifest` hardcodes `cache_mode`/`split`, which becomes wrong the moment M0.2's
  cache bypass or an M0.7a-gated read depends on the manifest being truthful).
- **Spend unchanged:** no Gemini calls this run; ledger still $0.4026.
- **Next:** #32 (M0.8). No baseline run before it lands — §2 forbids it and #32 is the last
  fixture prerequisite.

## run-2026-08-24-b — human-gated; one free finding on #37

- **The run had nothing it was allowed to start.** `accuracy_board.py next` returns nothing
  Ready. #88 (M2.1b) holds the single in-flight slot MISSION §3.2 permits, and it is parked on
  three questions the human has not answered. That also keeps #45 shut, even though #88's census
  already handed it the 229-scheme failure set for free.
- **The open M1 set is spend-gated, not free.** #38/#39/#41 are mark-changing and need their own
  before/after number under the gate-9 directive; #58 requires a golden-set run at
  `cache_mode=bypass`. No spend is authorised for any of them, so none was started.
- **#37 is MARK-CHANGING, and that reclassifies it.** The 2026-08-24 inbox directive listed it as
  probably routing-only "unless one of them turns out to move marks". It does.
  `normalize_extracted_answers` rewrites `question_id` (`answer_extraction.py:78`), and its only
  production caller is `GeminiAnswerExtractor.__call__` (`:187`) — so a reassigned answer is
  marked against the wrong question's scheme. Removing the fallback moves `awarded_marks`
  wherever it fires. Said so rather than taking the cheaper branch, as the directive asked.
- **The fallback's firing rate is unmeasured, not zero — and the metric is blind by
  construction.** `question_result_to_eval_record` (`harness.py:337`) hardcodes
  `id_match="exact"` for every leaf that has an answer, so a fallback rewrite records as `exact`.
  The 773 `exact` / 8 `unmatched` rows across `BUILD/accuracy-runs/` therefore prove nothing
  about it, and no structured logs are persisted in either run directory, so the
  `id_positional_fallback` warning at `:73` is lost. Consequence for #37: acceptance bullet 3 is
  not a rename — `id_match` has no path that can emit `fuzzy` at all, and must be made to measure
  three states before any CI target is re-derived. Recorded on #37.
- **Spend unchanged:** no Gemini calls this run; ledger still 1.488057.
- **Next:** whatever the human answers on #88. Nothing else can legitimately start before it.

## run-2026-08-24-c — the #88 census made durable; still human-gated

- **Nothing had changed.** No new inbox directive, no answers on #88's three questions, board
  `next` still empty, tree clean. Verified rather than assumed.
- **The one thing worth doing was free and on the in-flight item.** #88's census existed only in
  `/tmp/acc57-full`, which the state pointer itself flagged as non-durable and which would have
  cost a 40-minute re-parse to recover. `/tmp` had survived, so the window was open.
- **Every published number reproduced exactly** before anything was written down: 479 PDFs, 250
  det-parsed, 229 failed (52.2%), 12,358 leaves over 4,339 roots, 2,894 unbanded (23.4%), strata
  0580 1992/2110/1635 · 0606 46/107/239 · 0625 2521/525/289, and all 229 failures logging
  `mark_total_mismatch_escalating`. Persisted as `BUILD/accuracy-runs/census-2026-08-24-a/`.
- **The parsed corpus was deliberately left out.** The 250 `MarkScheme` JSONs (~18MB) and
  `parse.log` carry CAIE mark-scheme text verbatim, and publishing real-paper content is a human
  decision (§12.7). Only derived counts and public PDF filenames went in; `manifest.json` records
  what was withheld, why, and the free steps to regenerate it.
- **A reading trap recorded rather than smoothed over.** `census-leaves.txt` prints "DA1 strata
  populated: 12" because the script counts its own `0/unknown` catch-all as a band. DA1 defines
  three bands, so the honest figure is 9 of 18, with the 2,894 unbanded leaves held out. The
  manifest says not to cite the 12.
- **Still nothing else startable.** §3.2 allows one issue in flight and #88 holds the slot, which
  keeps #45 shut even though this census is precisely its input. #37 (reclassified last run),
  #38, #39 and #41 are all mark-changing and need a sweep; #58 needs a golden-set bypass run.
  Every one is unauthorised spend.
- **Spend unchanged:** no Gemini calls; ledger still 1.488057.
- **Next:** the human's answers on #88. Nothing else can legitimately start before them.

## run-2026-08-24-d — three falsified records in BLOCKERS.md, corrected in place

- **Nothing external changed again.** No inbox directive, no answers on #88's three questions,
  board `next` still empty, tree clean. Third consecutive run.
- **The free work was the record itself.** `BUILD/BLOCKERS.md` is read by every future run, and it
  was carrying three claims that measurement or the human had already falsified. A stale blocker
  is not inert — it actively misleads. All three were corrected **in place**, never deleted.
- **#28's section still said "OPEN — needs the human, and only the human"** three runs after the
  inbox authorised the spend with no per-item cap. #28 is CLOSED, PR #87 merged, the sweep ran as
  `ablation-2026-08-24-a`. Appended a RESOLVED note recording the real outcome: **NOT REPORTABLE
  as an ablation**, because the `oracle+mark` arm produced zero records — `measure_accuracy()`
  picks the arm from `case.scan_path` and all 11 golden cases ship a `scan.pdf`, so the oracle
  branch is dead code. Recorded as the outcome, not as a failure to retry; §12.9 forbids re-running
  at higher `n`.
- **§E's header still said "blocked on a human decision about spend."** That was answered on
  2026-08-24; #57 is now blocked on #88. The header says so, and now tells the reader to read the
  measured finding at the *end* of the section before citing the volume framing above it.
- **The machine-written `## #57` block still asserted "ZERO parsed mark schemes" and "71 golden
  leaves vs a ~300 target."** Both measured false: 250 parsed at $0.00, and 12,358 leaves — about
  41× the target. That block asks for a RESOLVED line; it now has one, restating the real
  constraint as **stratum coverage** (9 of 18 populated, the 9 Gemini-path strata empty by
  construction) rather than volume.
- **§F gained the durable-evidence pointer** to `BUILD/accuracy-runs/census-2026-08-24-a/`, with
  both cautions attached: the 250 parsed JSONs (~18MB) stay out of the repo as real-paper content
  (§12.7), and `census-leaves.txt`'s "DA1 strata populated: 12" must not be cited.
- **Spend unchanged:** no Gemini calls; ledger still 1.488057.
- **Next:** the human's answers on #88. If they have still not arrived, the honest next run is a
  quiescent one per E5 — re-verify, report in prose, commit nothing. The record is now correct;
  restating it again would buy nothing.

## run-2026-08-24-e — the #58 review moved to where the merge happens

- **Nothing external changed.** Fourth consecutive run with no inbox directive, no answer on any
  of the three asks, board `next` empty, tree clean.
- **The one thing done: attached the #58 review to PR #90 itself** (`gh pr review --comment`). It
  had existed only as an issue comment, so the PR read `reviews=0` and the MISSION §9 merge
  evidence was not sitting where the merge happens. Now `reviews=1`. Deliberately **not**
  approved: it is my own branch, and a self-approval would not be independent review.
- **A better CI fact than the previous run had recorded.** PR #90 is green on **all 5 jobs at its
  actual tip `605df52`** — run `32758424509`: pre-commit 1m19s, web 1m40s, test 3.12 15m42s,
  3.13 27m26s, 3.14 13m6s. The prior record only established green at `10b5ec5`, an earlier
  commit, which is weaker evidence than the merge gate needs. State/mergeable verified
  OPEN/MERGEABLE.
- **Deliberately NOT done, and the reason is the point.** No further #45 rows were instrumented.
  #45 pre-committed a stopping rule ("if round 5 blocks on the same defect class a fifth time,
  stop delegating and escalate — no round 6 will be attempted"), and systematically instrumenting
  more rows **is option 3**, one of the three choices the human must make. The previous run's
  single-row investigation was justified as evidence *about* the choice; continuing would decide
  it by doing it.
- **Also not done:** no BLOCKERS.md section added. Section `G` exists only on the #45 branch, so a
  new section cut from develop manufactures a tail conflict. That hazard is still live.
- **Spend unchanged:** ledger still 1.488057.

## run-2026-08-24-f — quiescent, exactly as run-d prescribed

- **Fifth consecutive run with no human input.** Re-verified rather than assumed: inbox has no
  unhandled item (last directive 2026-08-24T01:14, all `[x]`), `accuracy_board.py next` returns
  `nothing ready`, `origin/develop` unchanged at `1092d8f`, PR #90 still OPEN/MERGEABLE at
  `605df52` with `reviews=1`, tree clean.
- **The supervisor sweep covered the actual branch tip this time** — PASS over `38f66e6`, which
  *is* the #45 branch tip, so §9.3's pytest-green is genuinely satisfied rather than covering an
  ancestor.
- **Committed nothing**, per E5: restating an unchanged fact buys nothing and adds re-write debt.
- **One action taken:** a consolidated notify to the accuracy topic naming all three pending
  decisions, since the outbound steering channel is the only thing that can unstick the queue.
- **Why nothing was started, checked item by item rather than assumed:** #58/PR #90 needs the
  bullet-4 spend call (~USD 0.144) or a formal retirement; #88 q1/q3 are DA1/H4 (#49) and §3.5
  forbids working around them; #45 is the 3-option design question whose stopping rule already
  fired; #37/#38/#39/#41 are all mark-changing under the gate-9 test and need a sweep that is
  unauthorised spend. `lemely/io/det/mcq.py` and `lemely/config/profiles.py:50` are both known
  real bugs with measured blast radius, both left **zero-diff**, because both change awarded marks.
- **Spend unchanged:** ledger still 1.488057.

## run-2026-08-24-g — closing the record gap the volatile header was hiding

- **Sixth consecutive run with no human input.** Verified rather than remembered: no new inbox
  directive, board `next` still empty, `origin/develop` still `1092d8f`, both live branches fully
  pushed (nothing unpushed on either), tree clean. Checked the **issues** as well as the inbox, in
  case the human had answered there instead — the newest comment on #58, #88 or #45 is still my
  own from 18:53Z. Nothing changed.
- **The free work was a genuine record gap, not a restatement.** Runs `e` and `f` had never been
  journaled, and MISSION §11 requires a per-run narrative. Run `e`'s substantive facts — the
  `reviews=0 → 1` fix and the all-5-jobs-green-at-`605df52` evidence — existed **only** in
  `ACCURACY-STATE.md`'s `in_the_middle_of` header, which is a resume pointer that every run
  overwrites. They would have been destroyed by the next `state set`, and a future run would have
  paid to re-verify CI that had already been verified. That is the difference between this commit
  and the ones E5 forbids: E5 bars restating an unchanged fact, not recording an unrecorded one.
- **Routed to avoid the live tail-conflict hazard.** `BUILD/JOURNAL.md` is **byte-identical on
  `origin/develop` and on both live branches** (`git diff origin/develop..HEAD -- BUILD/JOURNAL.md`
  is empty), so this entry was written on a chore branch cut straight from `develop` and cannot
  conflict with #45 or #58 — unlike a BLOCKERS.md section, which run `e` correctly declined to add
  for exactly that reason. This is the fix E4 prescribed: re-write surviving content onto develop
  as its own chore commit, rather than pile it onto a branch that squashes from origin's tip.
- **Spend unchanged:** no Gemini calls; ledger still 1.488057.
- **Next:** still the human's three decisions. Nothing else can legitimately start before them.

## run-2026-08-26-b — B6 settled: the q11b reorder violation reproduces, and is still not established

- **Landed the queue first.** PR **#135** (the run-46 close) was open, CLEAN, and green on all five
  checks; merged to `develop` as `1146b5e`. The PR queue is empty again and the §4 precondition
  (`origin/develop..origin/main`) reads **0**, measured this run rather than quoted.
- **B6 ran, as authorised, for $0.013608.** Costed preflight posted to #58 **before** any spend;
  20 calls, every one `cache_hit=False`, the $0.040 in-process brake never approached. Ledger for
  this worktree 2.720069 → 2.733677; programme-wide sum (DA11) **3.124540 → 3.138147**.
- **The result is genuinely two-sided and is recorded that way.** Unperturbed `1×10`, perturbed
  `1 2 1 1 1 1 1 1 1 2` — so the violation **reproduces** (2/10) against **zero** same-input churn
  on the same leaf (0/10 here, 0/14 pooling every prior unperturbed marking of it already on disk).
  The pre-committed Fisher exact gives **p = 0.4737**, so it is **not established** at α = 0.05.
  Post-hoc pooling reaches 3/11 vs 0/14, p = 0.0717 — reported as secondary, never as the finding.
  **Not re-run at higher n**: ~n=25/arm would be needed and MISSION §12.9 forbids exactly that move.
- **The preflight was honest about being 1.6× the authorisation, before the fact rather than after.**
  B6 said ~$0.01; the projection was $0.0156 and said so in the comment, anchored on the 107 real
  calls in `control-58-2026-08-25/run.log` rather than on a scaled aggregate — which is precisely
  the error that made the #37 preflight wrong by 4–5×. Actual came in **under** projection.
- **Two things verified rather than assumed, either of which would have invalidated the run.**
  (1) *Which variant.* The report records only `paper_id` and all three `0625_s20_qp_31_theory`
  fixtures share it (DA6). Identified as `_partial` by outcomes-list position, then independently
  confirmed by mark values — the variants' q11b score 3 / 1 / 0 and the violated `baseline_marks`
  is 1. (2) *That "q11b alone" is the same experiment.* `correct_paper` builds `sibling_prior` only
  when `q.parent_id is not None` (`correction_ai.py:639-645`) and q11b's parent is `None`, so the
  prompt is byte-identical at one leaf or seven. Had it had a parent, the restriction would have
  changed the input and the design would have been illegitimate.
- **Acceptance boxes audited, not swept along.** Bullet 4 ticked as B6 directed; bullets 2 and 5
  ticked on live evidence. **Bullets 1 and 3 left unticked deliberately** — bullet 1 is a property
  a live run falsifies, and bullet 3 has **no live evidence at all**: the live bypass run predates
  #134's whitespace fixtures, so live it reads 0 held / 71 skipped, and #134's "7 held" is a
  zero-spend *offline* run. Closing that gap is ~14 calls / ~$0.01 and is **not authorised**.
- **Two zero-spend rulings discharged.** **B4** → **#136** (det mark-total escalation: three
  distinct bugs, the two 0625 deficits recorded as UNRESOLVED-not-diagnosed, and the falsified
  `rows.py` `flush()`/`q_row_had_answer` lead written down so it is not re-derived); #95 blocked on
  it. **B13** → **#137** (`GoldenCase` must hold more than one render of the same paper); #59
  blocked on it and its `Effort: S` recorded void.
- **Still owed by me, none blocked:** B12 (#105 wire `mark_point_verdicts`), B15 (#112 three
  sub-defects, mark-changing, joint sweep with #110), B16 (#114 annotate `cumulative_usd` as a
  contaminated upper bound). **Still the human's:** #88 item 2 (preflight falsified 1.83×, sweep
  stopped), B1/#41 (stopped on a falsified premise), and the four open H issues.

## run-2026-08-26-c — B16: the spend ledger is an upper bound, and says so at source

- **#138 landed.** All five CI checks green, and the supervisor sweep passed over its **exact sha**
  (`13802c3`), so §9.3's pytest condition is satisfied by evidence rather than by assertion. Merged
  as `8bcf0f7`; queue empty again; no new inbox directive.
- **B16 done, zero spend.** `cumulative_usd` is now documented at source
  (`lemely/io/cost_ledger.py`) as an **UPPER BOUND on money spent, not money spent**, with the
  mechanism re-verified rather than carried forward: bare `load_settings()` in some tests resolves
  `paths.output_dir` to the real repo, and `GeminiClient` builds its ledger path from exactly that
  (`gemini.py:162`). **DA17** amends DA11 — "authoritative for money spent" narrows to
  "authoritative as a conservative upper bound" — and keeps the total, with no re-baseline and no
  rebuild from per-call logs, as B16 required.
- **The ground for keeping a contaminated number is direction, not convenience.** Contamination is
  **one-directional**: a test can add cost, never remove it. So a contaminated total can only
  *overstate* spend and every ceiling check against it stays conservative, whereas re-baselining
  would swap a known-conservative figure for a reconstructed one that would itself need auditing.
- **One observation, recorded as an observation.** The 20:05Z supervisor sweep (21 min, full
  `pytest`) did **not** move this worktree's ledger — `2.7336773500000575`, `updated_at`
  `19:33:25Z`, the B6 run's own figure, unchanged either side. So the contamination is
  **intermittent, not every-sweep**. That is one uninstrumented sweep; it does **not** close #114
  and is **not** evidence the writer is gone, and DA17 says so in those words.
- **The gap is named rather than implied.** This annotation does not stop the writes. #114's scope
  item 2 — the autouse guard that would fail any test resolving `output_dir` inside the repo — is
  unstarted, and #114 is CLOSED. An annotation that read as a resolution would leave the next run
  treating the ledger as exact, which is the failure this entry exists to prevent.
- **Docstring-only diff**, so there is nothing to regress and no regression test ships with it;
  `tests/test_cost_ledger.py` 12/12 green (with `--no-cov`, since one module cannot clear the 70%
  project floor).
- **Still owed by me:** B12 (#105), B15 (#112). **Still the human's:** #88 item 2, B1/#41, the two
  questions raised on #58 in run 47, and the four open H issues.

## run-2026-08-26-d — agreement moves to the mark point; a fabricated zero caught in self-review

- **#141 merged** (`0bf1672`) on all five green checks plus a supervisor sweep over its exact
  tip `2565436`. **#140 closed** through `accuracy_board.py done`'s off-board path (B17's route) and
  verified CLOSED, since PRs merge to `develop` and GitHub only auto-closes on `main`.
- **B12 implemented, zero spend.** `mark_point_verdicts` was declared and **never read**, so
  agreement was equality of `awarded_marks` totals and two labellers awarding 2/3 by crediting
  **different** mark points counted as agreeing. The headline is now per mark point, keyed
  `(paper_id, question_id, mark_point_id)` — DA6's key plus one component, for the reason DA6
  exists. **DA18** records the unit, the two-stage funnel and why the totals figure was kept.
- **The design decision most worth attacking, so it is stated plainly:**
  `shared_leaves_without_shared_points`. A leaf both labellers marked can contribute **zero**
  points — no verdicts, or disjoint ids — and under a per-point denominator those vanish with no
  trace of why `n` shrank. That is the narrowed-denominator failure mode in a new costume, so it
  is counted and returned rather than described.
- **I caught a defect in my own diff before it landed, and fixed it rather than shipping it.**
  `totals_point` was a bare rate: at `totals_n == 0` it read `0.0`, which is indistinguishable
  from genuine total disagreement, and unlike the headline the secondary had **no interval** to
  say which. It now comes from the same `_wilson_interval` helper, so no data spans `[0.0, 1.0]`
  and real 0/1 disagreement does not. The regression test asserts that **distinction**, not the
  zero. A secondary figure that can publish a fabricated zero is worse than no secondary figure.
- **Tests: six new, all proven to fail on the pre-change code**, including the case B12 exists to
  catch and one built so it **cannot pass by coincidence** on totals-equality code. The eight
  existing agreement tests were **updated to assert the `totals_*` secondary, not deleted** —
  every property they guard (DA6 leaf identity, last-record-wins, shared-leaves-only,
  no-mutation) is still guarded, because both figures now derive from one shared collapse helper.
- **A correction to my own first edit, recorded because it nearly shipped:** the mechanical
  rename of `result["n"]` was scoped between two class markers and the new class had been
  appended at end of file, so it silently rewrote **15 assertions in six unrelated test classes**.
  Caught by running the file, reverted precisely, and the run ends green.
- **B15 (#112/#110) NOT started, deliberately, and the question is posted rather than assumed.**
  B15 requires a before/after sweep run jointly across the two. The golden harness reads
  **pre-parsed** `mark_scheme.json` and never invokes the det parser, so that sweep is null by
  construction — the same ground #38 (A6(a)) and #93 (B2) were waived on, which B15 was not
  shown. Unlike those, this one **is** measurable deterministically at **$0.00** over the 289
  schemes committed under `corpus/`. Both questions are on #112 and #110. Starting the
  implementation now would produce another complete-but-unmergeable branch, which is exactly what
  the 2026-08-24 gate-9 ruling was written to retire.
- **Spend unchanged: $0.00 this run**, ledger still 3.138147 programme-wide.

## run-2026-08-27-a — two issues shipped after their premises were checked, not assumed

- **Three PRs landed: #142 (#94), #143 (#137)**, each on five green checks plus a supervisor
  sweep over its exact tip. Both issues verified CLOSED afterwards through
  `accuracy_board.py done` — PRs merge to `develop`, and GitHub only auto-closes on `main`.
- **The run started with the queue empty and the board Ready empty**, i.e. everything on the
  mission's own list was human-gated. Rather than stop there, I looked for work no one had
  blocked and found two: **#94** (instrumentation, explicitly not mark-changing) and **#137**
  (authorised by B13 in terms). Neither needed a sweep, a ruling or a dollar.
- **#94's premise was falsified before a line was written, and the issue says so.** It claimed
  the parser drops questions silently; re-parsing `0625_s24_ms_21` today raises
  `ParseError: parsed 12, expected 40 (discrepancy 28)` — `reconcile` has been comparing against
  `maximum_mark` all along, and the premise most likely died when **#93** landed and the paper
  began being typed MCQ. What **is** silent is the *mechanism*. Acceptance bullet 3 is recorded
  **restated, not ticked as written**.
- **And the prevalence cuts against the issue's framing: 1 paper in 80.** 479 schemes opened,
  0 unreadable, 80 MCQ-typed, exactly one with a discarded table, one disqualifying value corpus
  wide (`QUESTION DISCOUNTED`). **The eventual repair is a one-paper repair on today's corpus** —
  put in the commit, the PR, the issue and DA19, because it is the fact most likely to be
  quietly dropped in favour of the more exciting one.
- **#137's load-bearing property is that renders never add cases.** A render producing its own
  case would inflate `n` with a duplicate of a leaf that already exists — the DA14 trap in a new
  costume. Verified against the real corpus rather than asserted: 12 cases, 31 distinct leaves,
  78 rows, unchanged. The rejected alternative (minting a second `paper_id`) is recorded in the
  docstring at the point someone would be tempted to do it. **DA20.**
- **A process slip, reported rather than buried.** #94's commits initially landed on **local
  `develop`**: `accuracy_board.py start` printed the branch name and I never checked it out.
  Caught at push time, moved onto the feature branch, `develop` reset hard to `origin/develop`.
  Nothing reached `develop` remotely and no pushed history was rewritten. It is in PR #142's body
  too, not only here.
- **Two test-honesty notes I would rather state than let pass.** #137's
  `test_extra_renders_do_not_add_cases` would also have passed before the change — it is a
  regression guard, not a change-detector, and the PR says so instead of counting six
  failing-before tests. And #94's real-PDF test **skips** when the PaperScraper file is absent;
  I verified it passing rather than skipping here, because a silently-skipping test is worse than
  no test.
- **#59 was NOT moved to Ready** even though its data-model blocker is now gone. Two blockers
  remain and neither is mine: the handwritten renders are verbatim CAIE content needing a
  MISSION §12.7 decision, and the measurement is unauthorised live spend. Posted on the issue.
- **Spend: $0.00 this run.** Ledger unmoved at 3.138147 programme-wide.

## run-2026-08-27-d — the queue was genuinely blocked, so the asks were answered; then one answer was measured

**Spend: $0.00.** Ledger unmoved at **3.138148**, re-summed across all four worktree
ledgers per B16 rather than carried forward from the header (the header's 3.138147 differs
by 1e-6 float rounding, not drift).

- **The "everything is blocked" claim was verified, not trusted.** The standing lesson is
  that a 'done' note is not evidence, and it applies to a *blocked* note too. Checked
  independently: `develop` @ `ec875a1` is **0 commits behind `main`** (§4 precondition
  holds); the board reports **Ready = 0** in every milestone and `next` returns "nothing
  ready"; and each of #38, #39, #41, #58, #59, #95, #110, #112, #127, #136 carries a posted,
  unanswered human question. The claim held. There was nothing to execute.
- **So the asks were put to the human directly, and seven rulings came back** — C1–C7,
  recorded in `BUILD/ACCURACY-ASKS.md` and posted to all ten affected issues. **DA22**
  (the C1/C3 sweep waiver and its deterministic substitute), **DA23** (C6), **DA24** (C7).
- **PR #150 merged** (`3a5b378`) once all five checks went green. Bookkeeping only, and no
  further close PR was opened for it — that regress ends there, as its own body said.
- **#136 and #112 had NO labels at all**, so they were invisible to every `owner:`-based
  query the programme uses to find outstanding work — the exact bug that hid #127 until run
  54. Both now `accuracy` / `owner:agent` / `blocked`, and both now return from
  `gh issue list --label owner:agent`. Found by listing issues rather than by trusting the
  board, which does not carry them either.
- **The run's real finding: C6 was ruled, and then the ruling was measured.** The human's
  answer to #41 was *"deterministic parsing for MCQ ONLY"*, programme-wide, confirmed on a
  second ask. **MCQ schemes carry zero `answer_points`** — MCQ answers live in the separate
  `mcq_answer` field — so C6 retires not *most* of the det marking path but **all** of it:
  **210 of 289 schemes (72.7%) and 10,314 of 10,314 answer points (100%)**. The figure
  reconciles exactly with #41's own independent census, which is why I trust it.
- **And it does not fit the ceiling.** Recurring cost per full corpus rebuild goes
  **$5–$7 → $10–$14**, permanently. Against the **committed** `total_usd_ceiling` of
  **$8.00** (`config.py:111`) the **one-off alone** breaches at $8.55–$9.66 from a ledger of
  $3.138148. The $25.00 in `lemely.toml` is **gitignored and worktree-local** — DA13's
  hazard class, invisible to CI — and I am not treating it as the programme's ceiling.
  MISSION §12.4 makes this a stop-and-ask.
- **The fork went back rather than the code going forward, as #151**, with #41, #39 and #110
  moved to Backlog and blocked on it. The alternative was to spend a run fixing #136 — the
  sequencing the human chose in the same interview, *before* C6 was clarified — on a code
  path about to be retired. **I did not offer a recommendation between "proceed" and
  "narrow it"**: that is an architecture and product call, and choosing it would have been
  me picking the shape of the programme rather than reporting on it.
- **The cost model was validated against the prior artifact rather than re-derived.**
  Re-running #88's failing set through the new script reproduces its four published
  scenarios to the cent ($4.92 / $5.70 / $6.82 / $7.26), so the C6 numbers and the #88
  numbers are the same model, not two.
- **B17 bit again and is recorded as C10.** `accuracy_board.py` gates *every* subcommand,
  `comment` included, on board membership, so four rulings — **#112, #136, #127, #151** —
  had to be posted via raw `gh issue comment`. B17 ruled option 3 and it is still not
  implemented. Naming it rather than quietly working around it a fourth time.
- **Nothing authorised was spent.** C4's ~$0.01 for #58 and C7's #59 measurement are both
  authorised and both left unstarted — they keep, and neither was worth interleaving with an
  unresolved architectural fork. C7's renders in particular are the one action here a revert
  cannot undo, so they get their own considered step rather than a rider on a bookkeeping run.

## run-2026-08-27-f — four merges, and two of my own preflights falsified

**Spend: $0.008332**, all of it #58's authorised bullet-3 run. Ledger 3.138148 → **3.146479**,
re-summed across all four worktrees rather than carried forward.

- **#153 — B17 was half-implemented and nobody had noticed.** B17 ruled that board membership
  must stop standing in for the H-guard; that landed on `done` and never on `comment`, so the
  path MISSION §3.4 makes *mandatory* refused every off-board issue. Run 55 alone worked around
  it four times. Fixed, with the asymmetry pinned by test: **`done` refuses a human task,
  `comment` must allow one** (§3.5 requires commenting on H issues), so a later "make this
  consistent" pass cannot break the protocol. Verified live twice — including by posting the
  #151 correction through the path the fix repaired.
- **#58 bullet 3 — MET LIVE.** 7 held / 0 violated / 0 skipped, `cache_mode=bypass`, all 14
  Gemini calls `cache_hit=False`, **$0.008332**. Replaces #134's zero-spend offline "7 held".
  Reported as **7 live outcomes, not 78**: the other 71 leaves are no-ops determined by string
  comparison at $0.00 and are labelled `determined_offline` in the artifact, so the run cannot
  later be misread as the very offline/live conflation the bullet existed to fix.
- **DA25 — I called the human's own authorisation incoherent, and I was the one who was wrong.**
  My preflight declared C4's *"~14 calls / ~$0.01"* inconsistent by ~13× and announced which
  figure I would break. "Calls" meant **Gemini calls**; the run made **exactly 14** and cost
  within rounding of $0.01. I had divided the 2026-08-25 run's spend by its `correct_paper`
  invocations — a **per-paper** rate measured on larger papers — and applied it as per-call.
  Actual came in at **42% of my own central estimate**. The rule: **state the unit**, and name
  the population a carried-over rate was measured on.
- **DA26 — the worse one, because I had published it as a strength.** #151's C6 costs reused
  `preflight-88`'s token model, and DA23 recorded that reuse as validation: *"it reproduces #88's
  four published scenarios to the cent."* **#88's item-2 sweep had already falsified that model
  at 1.83× — the same day, this repository, this exact task**, measured at n=1, confirmed at n=6,
  aborted at 6 of 190. I checked a model against a *number* when a *measurement falsifying that
  number* was on file. **A model and its own output always agree.**
- **C6 re-costed on the measured $0.07005/scheme, and it crosses thresholds it previously fitted
  inside:** one-off $5.41–6.52 → **$11.92–14.71**; recurring $10.33–13.79 → **$25.23–28.02**. The
  recurring rebuild now **breaches even the gitignored local $25.00**, and **both plans trip the
  5M `per_run_token_ceiling`** (6.49M / 13.74M) — the ceiling #88 had already flagged as undersized
  on this same estimate. **DA23's structural finding is NOT withdrawn**: it was *counted*, not
  modelled — MCQ schemes carry zero `answer_points`, so C6 retires 210/289 schemes and
  10,314/10,314 answer points.
- **#59 blocker 1 discharged; blocker 2 authorised and deliberately not run.** 54 render pages
  committed under C7, digests re-verified against #102 and 0 text chars confirmed on the committed
  bytes. Placed in `tests/fixtures/`, **not** `tests/golden/` — promoting them would change corpus
  membership (the B5 consequence) and #49 is reopened, so C7's grant to publish pixels was not
  quietly widened into a membership decision.
- **And a scope finding that shrinks #59 permanently: n = 3 is unachievable.** `0625_w24_ms_42` is
  parsed; `0625_s25_ms_42` exists but is unparsed (one of #88's det-failures); **`0625_w25_ms_42`
  does not exist locally at all.** So n = 1 today, n = 2 at best, never 3. The $4.00 cap was not
  the constraint — the synthetic counterpart arm does not exist for any Paper 42, and at n = 1 the
  figure cannot carry the claim the issue was written for.
- **A privacy escalation I raised and then had to withdraw.** I described #59's renders as carrying
  "a real student's handwritten exam answers" and asked the human to reconfirm on that basis. The
  issue's own limit 6 already said otherwise — *one person (the teacher) solved every question
  themselves and marked their own work; there is no student attempt and no second author*. I had
  conflated them with `tests/fixtures/real-papers/`. The correction is on #59 rather than left to
  rot, because the false framing is on the record.
- **MISSION §13 is not reachable by an agent and this run says so plainly** rather than working
  toward an implied completion: #47's ~300 labels are human-owned, and #49/#51/#52/#55 are H
  issues §3.5 forbids closing or working around. Everything agent-ownable that was not blocked has
  now been done; the rest sits behind **#151 (ask C8)**.

## run-2026-08-27-f addendum — two §13 components were reachable after all

**Zero spend.** Written after claiming the mission was unreachable and then checking that
claim properly.

- **I had written off §13 wholesale. That was lazy.** Two of its six components were
  agent-ownable and undone: **the develop→main PR** (§12.3 permits *opening* it; only
  merging is human-only) and **"the H issues that remain open are cleanly documented as
  awaiting their human"**. Both are now met. #49, #51, #52 and #55 each carry a current,
  specific "what is needed" record, and **PR #159** is open with an honest
  component-by-component scorecard in its body and an explicit statement that it is not a
  claim the programme is finished.
- **#57's dependency list was wrong, and I had repeated it.** The board, the resume pointer
  and my own reporting all carried *"#57 blocked on #49"*. Read against the acceptance
  criteria, **bullet 1 — propose the stratified split — is agent work and needs no #49**;
  #49 gates only the approval bullet. Both listed predecessors, **#44 and #31, are CLOSED**.
  I had trusted a status line, which is the exact failure the programme's own standing
  lesson names.
- **It is blocked anyway, by a cause nobody had written down.** DA1 stratifies on syllabus
  code × **parse path (det/Gemini)** × tariff band. The **Gemini strata are empty** because
  #88's sweep aborted at 6 of 190 — and **#151/C6 would collapse the axis entirely**, since
  MCQ schemes carry zero `answer_points` and every answer point would land on the Gemini
  path. Proposing a split now would stratify on an axis with one level of 6 members, or on
  one that is about to become a constant. DA1 was fixed in a human interview and must not
  be re-derived around a degenerate axis by an agent.
- **So the blocking chain is #88 → #151 → #57 → #49 → #47 → #51 → #55**, and it is now
  written on each of those issues rather than inferred. The practical consequence is
  unchanged and worth stating without softening: **§13 cannot be completed by an agent**,
  because ~300 human labels sit in the middle of that chain — but the *reason* is now a
  named, checkable dependency instead of a shrug.
- **The lesson, and it is the same one twice in one run:** a dependency recorded on a board
  is a claim, not evidence. DA25 and DA26 were both cases of trusting a derived number over
  an available measurement; this was trusting a derived *status* over the acceptance
  criteria sitting in the issue body. Verify against the source, including when the source
  is the issue itself.

---

## run-2026-08-27-g — the budget held, the sweep did not, and the failure was the finding

**Two rulings arrived and both were executed the same run.** C20: *"make the
sweep cost < $3.00."* C21: *"set the token ceiling to be whatever is most optimal
(no hard limit)."*

**C21 first, because it changed how C20 could be run safely.**
`per_run_token_ceiling` went to `None` — the gitignored 5,000,000 override
removed, matching what C12 did to the dollar ceiling. That ceiling had been sized
twice and wrong twice, both times from a cost model DA26 records as falsified at
1.83×. The committed **$8.00 `total_usd_ceiling` is now the sole guard**, and it
guards the thing that is actually scarce. Recorded as **DA32**.

**Then C20, built so the estimate was allowed to be wrong.** The obvious way to
hit $3.00 is to size a sample from a rate and hope. That is exactly what failed
on #88 — a rate estimate stood between the programme and the money, and it was
out by 1.83×. So `run_sweep_c20.py` re-reads the live ledger before every scheme
and stops when `spent + reserve` would cross $3.00. The cap is arithmetic, not a
projection.

**It held. $2.8470 of $3.00, stopped before scheme 24 of 37.** That part of the
run did exactly what it was asked to.

**And the sweep failed anyway, on a dimension the budget could not see.**
24 attempted, **12 parsed, 12 failed**. Cost per *success* $0.2372 — **3.39×** the
$0.07005 projection, extrapolating to **$45.08** for all 190. The estimate was
wrong a second time, in the same direction, and the cap absorbed it. That is the
design working.

**The verdict is NOT REPORTABLE, and for the right reason.** The spend was
justified by populating DA1's empty Gemini-path strata. **Four strata got zero
successes** — `0606/p1`, `0606/p2`, `0625/p4`, `0625/p5`. There was a real
temptation here to report 12 successful parses as progress. They are not
progress toward the stated goal, and calling a sample with empty strata a
stratified sample is precisely the narrowed-denominator move MISSION §14 names.
The 12 are kept; they are not coverage.

**What the run actually found, which is larger than the cost question.** The
Gemini parse path — C11's designated fallback for every scheme det cannot handle
— **fails on half of them, systematically by size**. 0580 82%, 0625 33%, **0606
0%**. Failures average 10.0 pages / 11,637 chars against 7.3 / 8,608. Two causes
ruled out by measurement rather than assumed away: **not truncation** (65,536
limit, largest success 26,571), and **not fully deterministic** — the n=1 probe
failed, then succeeded unchanged.

**Why nobody had seen it, and the rule that follows.** The 2026-08-26 run aborted
at **6 of 190 on cost** — and all 6 happened to succeed. **An abort is not a
pilot.** A run cut short for an unrelated reason leaves survivors that are not a
random sample of what it never reached, and reading a success rate off that
prefix is how a 50% failure rate hid behind a cost overrun for two days.

**Stopped short of diagnosing, deliberately.** Reproducing one 0606 failure with
logging costs ~$0.15 of the **$2.01** headroom left. Retrying the 12 failures
would consume the rest and still leave 0606 unproven. Both are spend decisions,
so both went to the human as **#166** rather than into this run.

**Ledger 3.146479 → 5.993470**, re-summed from the worktree files rather than
carried forward from the header. Recorded as **DA31**.

---

## run-2026-08-28-a — the ratchet was restated, and the restatement falsified the issue that asked for it

**Ruling C13 gave the statistic**: publish an *upper interval bound* of the
measured distribution and arm against that — never 29.03%, never the mean.
**Zero spend**, re-derived from the existing 10-repeat A/A floor, because
MISSION §12.9 forbids re-running to get a tighter number and the ~13pp spread is
a property of the system rather than noise to average away.

**`review_rate_last_merged`: 0.2903 → 0.4838** — the 95th percentile of the
beta-binomial predictive for a single new run, Jeffreys prior on the pooled
101/310 leaf-repeats. Zero of the ten observed repeats exceed it.

**Predictive rather than a CI on the mean, and the distinction is the whole
point.** The gate judges *one* run. A confidence interval on the mean narrows as
n grows until it sits inside the spread unchanged code actually produces — which
is DA9a's single-figure trap wearing a different hat. Choosing the wrong interval
here would have reproduced the exact failure C13 was ruled to prevent.

**Two things found while deriving it, both worse for the programme than what was
on record.**

**First, 0.2903 was the minimum, not a middle.** And because it was truncated
*down* from 0.29032258…, **all 10 of 10** unchanged repeats exceed it — not the
7 in 10 DA9a estimated. Arming against it would have failed every no-op diff
without exception. DA9a was right and had understated itself.

**Second, and this is the run's real finding: restating the statistic does not
unblock arming, and `last_merged` was never the blocker.** #161's body — which I
wrote — framed it as the thing standing in the way. Running the gate says
otherwise:

| limb | measured | target | miss |
|---|---|---|---|
| signal | 0.2903 | 0.08 | 3.6× |
| total | 0.2903 | 0.10 | 2.9× |
| p95 | **0.8333** | 0.15 | **5.6×** |
| ratchet | ceiling 0.10 | — | pinned by `total_target` |

**All four fail; three fail on absolute targets `last_merged` cannot touch.**
While the measured rate sits above 10%, `min(total_target, last_merged)` is
pinned at 0.10 and **no value of `last_merged` moves it**. So the restatement was
worth doing — the published number is now honest about which statistic it is —
but it does not bring arming one step closer. **Arming needs the review rate to
actually come down.** That is M1 accuracy work, and the p95 limb missing by 5.6×
is the honest measure of how far.

**The number went up, which is what a loosening looks like**, so it is pinned as
not being one: the effective ceiling is 0.10 before and after, and
`TestC13RestatementDidNotLoosenTheGate` asserts that plus the ratchet limb's
immovability at any `last_merged` above the target. Both shortcuts are named and
foreclosed in `config.py` — do not flip the flag to finish the gate, and do not
loosen 0.08/0.10/0.15 to make arming comfortable.

**The lesson, and it is the same shape as yesterday's:** I had written #161's
premise into an issue body and then carried it forward as established. It took
running the gate — one command — to see that three of four limbs never involved
the field the issue blamed. **A premise I wrote is not evidence either.**

Recorded as **DA33**. The dangling `#36` citations in `config.py` and
`ACCURACY-STATE.md` now point at #161 and at the measured reason.
