# LEMELY BUILD MISSION

You are the **orchestrator** for an unattended, multi-day build of Lemely. The human
(Habeeby) will NOT be available to answer questions. Every decision you need has
already been made and is recorded in this document. If you hit a genuinely
undecidable fork, pick the option that is simplest, cheapest, and most reversible,
record the decision in `BUILD/DECISIONS.md`, notify via ntfy, and continue. Never
stop to wait for a human.

You are running headless (`claude -p`) under a supervisor loop. Your session may be
killed at any moment (usage limits, crashes). Therefore: **all state lives on disk
and in git, never in your context.** Work in small, committed, checkpointed units.

---

## 1. What Lemely is

Lemely is a SaaS platform for IGCSE/O-Level/AS/A-Level students, their parents, and
their teachers/schools, launching in Egypt (English-only UI for v1).

Core value proposition: a student photographs or uploads their attempted past paper
(handwritten, camera-scanned PDF); Lemely extracts their answers, marks them against
the official marking scheme with **method-mark awareness** (partial credit for
working, human-examiner-level accuracy), and returns: per-question marks, letter +
numerical grade, predicted grade after boundaries, mistakes, weakness topics, and
performance trends. Around that core loop sit dashboards (student/teacher/parent),
AI content generation (topic-classified practice, flashcards, teacher quizzes),
adaptive study plans, and Duolingo-style engagement (XP, streaks, leaderboards).

Buyers: students/parents subscribe directly; schools/tutoring centres subscribe and
are granted N student seats. A teacher can be independent, belong to a school, or
both. A student can hold a school seat AND a personal subscription simultaneously.

**Scope for this run:** CAIE (Cambridge) only — Mathematics 0580, Additional
Mathematics 0606, Physics 0625. Architecture must be board-agnostic (Edexcel and
Oxford AQA arrive later as data + parser plugins). Payment processing is OUT of
scope (build the subscription/seat data model and plan gating; account activation is
a manual platform-admin toggle). The igclub calculator is out of scope for v1.

## 2. Current codebase state (from the audited dossier)

Read `LEMELY_AUDIT.md` in the repo root before doing anything else. Summary:

- Strong Python core: mark-scheme parsing (deterministic + Gemini fallback), answer
  extraction (Gemini vision), AI marking, MCQ deterministic correction, grade
  prediction, weakness detection, quiz generation, study plans, accuracy harness.
  mypy strict clean, 308 tests, 82% coverage, import-linter layering.
- **No database** (JSON files, single shared "anonymous" bucket), **no auth** (all
  24 FastAPI routes effectively anonymous; two IDOR-shaped endpoints), **React SPA
  is 100% hardcoded mock data** (`web/lib/api.ts` is dead code), **no deployment**,
  **CI red** (`ruff format --check` fails), `monthly_usd_ceiling` cost cap is
  broken (resets per-process), `HistoryStore.load()` swallows corruption,
  `lemely/io/det/` is ~1,256 LOC of dead code, grade-boundary table has zero
  per-paper-variant entries, two drifting lockfiles.

## 3. Locked architecture decisions

- **DB:** PostgreSQL via a **local Supabase stack** (`supabase init` / `supabase
  start`, Docker). SQLAlchemy 2 + Alembic for schema/migrations owned by the Python
  backend. Supabase **Auth (GoTrue)** for identity: email/password for all roles
  now; parent **phone-OTP behind a provider abstraction with a mock SMS provider**
  (logs the OTP; one config switch to a real provider later). Supabase **Storage**
  for uploaded PDFs/scans. FastAPI validates Supabase JWTs; RBAC enforced
  server-side on every route.
- **Roles:** `student`, `parent`, `teacher`, `school_admin`, `platform_admin`.
- **Frontend:** the existing React 19 + Vite SPA in `web/` becomes the real product:
  wire every screen to the API (react-query), delete all mock data, add PWA
  (manifest, service worker, installable, camera capture → multi-page PDF client
  side), and web push (VAPID). Gradio stays as an internal debug tool only.
- **LLM:** Google Gemini stays the app's provider (`gemini-2.5-flash` default; keep
  the per-task model override slots). All automated tests mock Gemini. Live calls
  only for controlled accuracy validation under the budget protocol (§8).
- **Marking confidence is mandatory:** every marking/extraction operation emits a
  per-question and per-paper confidence value; low-confidence results are flagged
  into a human-review queue surfaced to teachers.
- **Definition of done for deployment:** one-command local run via Docker Compose
  (backend + built SPA served properly with CORS/proxy configured + Supabase local)
  plus written deployment docs for a future free-tier cloud deploy. No live hosting.
- **Leaderboards show XP (effort), never grades.** Grades are private to the
  student, their parents, and their teachers.

## 4. Phase roadmap

Execute phases strictly in order. A phase is complete only when its acceptance
criteria pass, the quality gates (§6) pass, the milestone report (§7) is committed,
develop is merged and pushed, a `develop → main` PR is opened via `gh` (never merge
it yourself), and an ntfy notification is sent.

### Phase 0 — Foundation repair
- Make CI green (`ruff format`), add `web/` (typecheck, lint, build) and the `web`
  extra to CI.
- Evaluate `lemely/io/det/` (dead staged parser) vs the wired monolith
  `parsers_det.py`: pick ONE (prefer whichever gives reconciliation + honors
  `DetParserSettings`), wire it, delete the other. Record rationale in DECISIONS.md.
- Fix the Gemini cost cap: persistent, file-backed cumulative USD tracker
  (survives process restarts), hard ceiling **$8.00**, warning events at $4 and $6
  (→ ntfy). Rename config to reflect reality.
- Fix `HistoryStore.load()` silent-fail (surface corruption; add schema_version).
  This store is interim — Phase 1 replaces it — but corruption must not be silent.
- Collapse to a single lockfile mechanism; add `.env.example` documenting BOTH
  `GEMINI_API_KEY` and `LEMELY_GEMINI_API_KEY` (fix the env-mapping trap: one env
  var must work everywhere, CLI, Gradio, and web).
- Remove other confirmed dead code (`respx`, unused `live` marker, dead
  `lib/api.ts` gets rescued in Phase 2, leave it).
- Acceptance: CI fully green including web; cost-cap tests prove persistence
  across processes; `lemely doctor` reports the real Gemini reachability.

### Phase 1 — Database + Auth + Tenancy
- Local Supabase stack committed (`supabase/` config, seed scripts, Makefile
  targets, docs).
- Full relational schema + Alembic migrations: users/profiles (role), schools,
  school_memberships (teacher↔school), seats, subscriptions & plan tiers (manual
  activation flag), parent↔child links, classes, class_enrollments, subjects,
  papers (board/subject/session/year/variant/paper#), mark_schemes,
  uploads, attempts, question_results (marks, max, confidence, method-mark
  breakdown), weakness_records, review_queue, announcements, notifications,
  devices/sessions, xp_events, streaks — designed so Phases 2–5 need additive
  migrations only.
- Auth end-to-end: signup/login flows per role, Supabase JWT validation middleware
  in FastAPI, RBAC dependency on EVERY route (kill both IDOR endpoints), row-level
  ownership checks (student sees self; parent sees linked children; teacher sees
  their classes; school_admin sees their school; platform_admin sees all).
- Migrate `HistoryStore` JSON into Postgres; delete the JSON store after a
  migration script + tests prove parity.
- Seat model: school_admin invites/creates N student accounts against seat quota;
  a student account can simultaneously hold a personal subscription.
- Device/session registry: max **3** concurrent devices per account; logging in on
  a 4th silently invalidates the oldest session.
- Acceptance: E2E auth tests for all 5 roles; a security-focused adversarial
  review pass (reviewer subagent) finds no unauthenticated or cross-tenant access;
  every route has an authz test.

### Phase 2 — The core loop, real and end-to-end
- Wire the SPA to the API: resurrect `lib/api.ts` + react-query, screen by screen
  delete `student/data.ts` and `teacher/data.ts` mock imports. The `CorrectPaper`
  setTimeout theatre becomes the real SSE-driven pipeline.
- Upload path: PWA camera capture → client-side multi-page PDF assembly → Supabase
  Storage → backend job. Also plain file upload. 25MB cap kept.
- Pipeline: metadata detection (subject code/session/year/variant/paper#) →
  fetch/parse marking scheme (from stored corpus; if absent, fetch from public
  mirrors and persist) → answer extraction (handwritten, Gemini vision) → marking
  with method-mark awareness → per-question confidence → grade + boundary
  prediction → weakness detection → persist → dashboard.
- **Grade-boundary ingestion pipeline:** scrape historical per-paper-variant grade
  thresholds for 0580/0606/0625 (all available sessions) from public mirrors
  (gceguide, papacambridge, xtremepapers, or any working source), parse into the
  per-paper-variant table, with provenance. Prediction = exact lookup, falling
  back to per-subject historical average with an "estimated" flag surfaced in UI.
- **Accuracy harness with golden fixtures:** download real past papers + mark
  schemes for the 3 subjects; generate synthetic handwritten answer sheets
  (handwriting-style fonts, ink variation, scan noise/skew/blur/rotation
  augmentation) with known ground-truth answers spanning correct, partially
  correct (method marks), and wrong answers. Commit fixtures. Thresholds that
  gate the phase: **≥99% MCQ agreement; ≥95% mark-level agreement on structured
  questions; 100% of disagreements must carry confidence below the review
  threshold** (i.e., the system knows when it doesn't know). Calibrate the review
  threshold from harness data. Live-Gemini validation obeys the budget protocol.
- Student dashboard on real data: overall + per-subject performance, per-paper
  history, predicted boundaries and final grade, weakness topics, comparison to
  past attempts.
- Plagiarism (answer ≈ mark-scheme text) + AI-detection flags wired into results
  as advisory teacher-review flags only — never auto-penalize; copy in UI must
  present these as signals, not verdicts.
- PWA installable; Lighthouse PWA checks pass.
- Acceptance: Playwright E2E — a seeded student uploads a fixture scan and sees
  correct marks, grade, and weaknesses in the dashboard; accuracy thresholds met;
  screenshots in the report.

### Phase 3 — Teacher + Parent surfaces
- Teacher: class management, per-class and per-student analytics, aggregate
  weakness topics, **at-risk flagging** (declining trend across last N papers, OR
  predicted grade ≥2 boundaries below target, OR ≥14 days inactive — each flag
  labeled with its reason), human-review queue for low-confidence/integrity-flagged
  marks with an override-and-annotate flow (overrides feed back as recorded
  corrections).
- Teacher quiz builder: difficulty targeting by expected grade (question pool
  filtered/generated to match), included-material selection, pool from generated
  or classified past-paper questions; assign to class; auto-marked; results feed
  analytics.
- Parent portal: phone-OTP login (mock provider), linked children, performance +
  weakness views (read-only), notification preferences.
- Acceptance: E2E per role; at-risk flags verified against seeded scenarios.

### Phase 4 — Content generation + study plans
- Topic-classified practice material generator: questions from the ingested
  past-paper corpus grouped by topic, filtered to a student's weak topics;
  exportable/printable.
- Flashcards (AI-generated per topic, spaced-repetition review flow).
- Placement test: auto-assembled from real past-paper questions across topics,
  **~15 minutes** per subject, marked by the existing engine, initializes the
  student's weakness/level profile.
- Onboarding questionnaire (sliders/semantic inputs): enrolled subjects + session,
  school, external sessions y/n, weekly study time, grade level, target grades.
- Adaptive study plan: uses placement + questionnaire + rolling performance;
  regenerates weekly; concrete sessions (topic, activity, duration) not vague
  advice; visible on dashboard; push reminders.
- Acceptance: E2E — new student onboards, takes placement, receives a plan;
  generated practice demonstrably targets seeded weaknesses.

### Phase 5 — Engagement layer
- XP system (design it Duolingo-style and record the spec in DECISIONS.md before
  implementing): XP for corrected papers, quizzes, flashcards, study-plan session
  completion; daily streaks with streak-freeze; anti-farming caps.
- Leaderboards: friends, class, school, global, per-subject, total — **weekly XP
  based, never grades**; opt-out flag.
- Announcements: teachers → their classes, school_admins → school; auto-populated
  official CAIE session dates; calendar UI on student dashboard.
- Web push notifications (VAPID): grades ready, new announcement, streak about to
  break, study-plan reminder; at-risk alerts to the teacher and (if opted-in)
  parent. Per-user notification preferences.
- Account-sharing friction: the 3-device limit from Phase 1 enforced in UI with
  clear device management screen.
- Acceptance: E2E covering XP accrual, leaderboard ordering, push delivery
  (headless push mock), announcement flow.

### Phase 6 — Hardening + ship
- Full-suite pass: backend, frontend, E2E across all roles on seeded realistic
  data; concurrency test (parallel uploads/markings); basic load sanity on the
  API; security re-review (authz matrix re-verified).
- Docker Compose: one command brings up Supabase-local + backend + served SPA
  build with correct CORS/proxy; documented.
- Deployment docs for future free-tier cloud (Supabase cloud + container host).
- **`DELIVERY.md`**: the comprehensive final document — every feature from the
  inventory (§9), its status, what was added/fixed/changed, which files, which
  tests prove it, with links to each phase report. Plus honest "known limitations
  / deferred" section.
- Update README, CHANGELOG; bump version.
- Acceptance: fresh-clone test — `git clone` → documented commands → working
  product with seeded demo accounts for all 5 roles.

## 5. Execution protocol

- **State:** `BUILD/STATE.md` is the single source of truth: current phase, task
  checklist with statuses (`todo/doing/done/blocked`), last checkpoint, next
  action. Update it BEFORE and AFTER every task. Assume you can die at any line.
- **Resume:** on session start: read `BUILD/STATE.md`, `BUILD/DECISIONS.md`, the
  current phase section here, and `git log --oneline -15`. Verify the working tree
  is clean (commit or stash leftovers with a `wip:` commit). Continue from the
  first non-done task. Do not re-plan completed work.
- **Git:** work on `feature/<phase>-<slug>` branches. Merge to `develop` yourself
  ONLY after all quality gates pass locally. Push after every merge and at least
  hourly during long tasks. Open `develop → main` PRs per phase with `gh pr create`
  — never merge them. Never force-push. Never touch anything outside
  `/home/sico/Code/Lemely`.
- **Delegation:** you orchestrate; subagents (defined in `.claude/agents/`) do the
  work. Give each subagent a self-contained brief: relevant file paths, the
  acceptance criteria, constraints, and what "done" means. Verify their output
  yourself (run the tests) — never trust a subagent's claim of success.
- **Dynamic workflows:** for fan-out work, explicitly request a workflow ("use a
  workflow to ..."): the mock-data screen-by-screen migration, route-by-route
  authz sweep + adversarial verification, boundary-document scraping/parsing,
  fixture generation, keep-fixing-until-green loops (type check, lint, test
  suite), and PR-wide reviews. Prefer many small workflows over one giant one —
  interrupted workflows do not survive session restarts, so keep each under ~30
  agents and checkpoint results to disk immediately after each run.
- **Stuck protocol:** 3 failed attempts on the same problem → stop, write the
  problem + attempts to `BUILD/BLOCKERS.md`, ntfy with priority=high, mark the
  task `blocked`, move to the next independent task. Revisit blocked tasks once
  per session start with fresh eyes. Never loop indefinitely; never fake a pass.
- **Testing is non-negotiable:** every behavior gets tests at the right level
  (unit, integration with a real local Postgres, Playwright E2E through the real
  UI against the real backend with mocked Gemini). "It compiles" is not tested.
  Never weaken, skip, or delete a failing test to get green — fix the code, or if
  the test is genuinely wrong, document why in the commit message.
- **Context hygiene:** keep your own context lean — delegate reading of large
  files to subagents that return summaries; when your context grows past roughly
  70% or you finish a phase, write STATE.md meticulously, commit, and exit(0) so
  the supervisor relaunches you fresh. Exiting cleanly is ALWAYS safe because
  disk is the source of truth.

## 6. Quality gates (required for every merge to develop)

1. `ruff check` + `ruff format --check` + `mypy lemely` + `lint-imports` clean.
2. `pytest` green, coverage never drops below the previous develop value.
3. `web/`: typecheck, oxlint, `npm run build` clean; frontend unit tests green.
4. Playwright E2E suite green for all flows the change touches.
5. Anything touching marking/extraction/prediction: accuracy harness meets §4
   Phase-2 thresholds.
6. Anything touching auth/routes: authz test matrix updated and green.
7. Reviewer subagent has adversarially reviewed the diff; findings addressed.

## 7. Reporting protocol

- Per phase: `reports/phase-N/REPORT.md` — what was built, feature mapping,
  decisions made, test summary (counts, coverage, accuracy metrics), Playwright
  **screenshots** of every new/changed screen (`reports/phase-N/screens/`),
  command outputs proving gates, known issues. Commit it; it must render on GitHub.
- ntfy (topic below): phase start, phase complete (with 2-line summary), blocker
  raised, budget warnings, run complete, and a daily one-line heartbeat.
  `curl -s -H "Title: Lemely" -d "<message>" ntfy.sh/lemely-ErBPK7TIRGD1sQP5`
  Use `-H "Priority: high"` for blockers/budget/final-complete.
- Session journal: append a dated entry to `BUILD/JOURNAL.md` at the end of each
  session (3–6 lines: did, learned, next).

## 8. Budget protocol (Gemini)

Hard ceiling **$8.00** total, enforced by the Phase-0 persistent tracker; ntfy at
$4 and $6. Mock Gemini in all automated tests. Live calls are permitted only for:
(a) small controlled accuracy-validation batches (estimate cost first with the
existing `estimate-cost` machinery, cache aggressively — the disk cache is your
friend), (b) smoke-testing each AI feature once E2E. If the ceiling is reached:
continue building with mocks/cache, record what still needs live validation in
DELIVERY.md, ntfy priority=high. The human can top up (max +$12) but do not assume
it.

## 9. Full feature inventory (traceability — every item appears in DELIVERY.md)

Correction: in-app PDF scanner (P2), file upload (P2), metadata detection (P2),
mark-scheme fetch/parse/store (P2), method-mark marking + confidence (P2),
plagiarism flag (P2), AI-detection flag (P2), letter/numerical/total grade (P2),
predicted grade after boundary (P2), mistakes + weakness identification (P2),
performance vs past papers (P2), custom exam + custom mark-scheme correction (P3,
via review/override + teacher quiz marking). Student: announcements calendar (P5),
push notifications (P5), overall performance (P2), per-subject performance (P2),
single-subject overview with per-paper performance and predicted boundaries/final
grade (P2). Teacher: at-risk flagging (P3), overall/individual performance +
weakness points (P3), academic statistics (P3), review queue (P3), quiz creation
with difficulty/material/pool controls (P3). Parent: child performance + weaknesses
(P3), phone login (P3, mock SMS). Content: classified-like practice targeting
weaknesses (P4), flashcards (P4), quiz generation (P3/P4). Study plan: placement
test ~15min (P4), questionnaire (P4), data collection fields (P4), adaptive plan
(P4). Engagement: XP/streaks (P5), leaderboards friends/school/global/per-subject/
total (P5). Accounts: personalized accounts (P1), 3-device limit + sharing
friction (P1/P5). Platform: subscriptions/seats/manual activation (P1), RBAC (P1),
Docker Compose + docs (P6), DELIVERY.md (P6). Deferred (documented, not built):
payments (Paymob/Fawry), igclub calculator, Edexcel/Oxford AQA, Arabic UI, real
SMS provider, cloud hosting.

Begin: read `LEMELY_AUDIT.md` and `BUILD/STATE.md`, then execute.
