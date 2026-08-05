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

### Phases 0–2 — COMPLETE (do not redo)

Foundation repair, database + auth + tenancy, and the core correction loop are
finished and merged. Their reports are in `reports/phase-0/`, `reports/phase-1/`
and `reports/phase-2/`; read those (and `BUILD/DECISIONS.md`) rather than
re-deriving what was built. If you find a defect in that work, fix it as a
scoped task inside the current phase — do not reopen a completed phase.

### Phase 2.5 — Design system + frontend quality foundation

**Why this phase exists.** Phases 3–5 add roughly forty new screens. Building
them without an established design system produces forty inconsistent screens
and an unshippable product. This phase installs the design rails, defines the
system, retro-fits the Phase-2 screens onto it, and stands up the visual/
accessibility test harness that every later phase is gated on.

**The design skills are already installed by the human** (Impeccable, UI/UX Pro
Max, Taste-Skill). Verify with `ls .claude/skills/` and `/impeccable check`
equivalents at phase start; if a skill is missing, record it in BLOCKERS.md,
notify, and proceed with `frontend-design` (the built-in skill) rather than
stalling. Full usage rules are in §10.

- **Read `docs/LEMELY_UI_SPEC.md` first.** It is the authoritative product and
  UI specification: every screen, its contents, states, interactions, and the
  flows between them. It also states five product principles that constrain the
  UI (visible confidence; flags are signals not verdicts; grades private and XP
  public; teacher has final authority; never invent precision). Those are
  non-negotiable and any design that violates one is wrong regardless of how
  good it looks.
- **`DESIGN.md` and `PRODUCT.md`** exist at the repo root (written by the human
  via `/impeccable init`). They are the brand source of truth: colours, type,
  voice, anti-references. Never invent brand values that contradict them, and
  never hardcode a colour or font that is not in DESIGN.md. If DESIGN.md is
  missing or has unfilled placeholders, that is a blocker — record it, notify
  with priority high, and continue with non-visual tasks in this phase.
- **Design tokens in code.** Produce a single token source (Tailwind v4 theme +
  CSS custom properties) covering colour (including the semantic scales that
  carry meaning: confidence levels, correct/partial/wrong, grade bands),
  spacing on a 4px scale, type scale, radii, shadows, motion durations and
  easings, and breakpoints. Every token traceable to DESIGN.md. Delete ad-hoc
  values from Phase-2 components as you go.
- **Component library.** Build the cross-cutting components named in
  §4 of the UI spec (grade badge, mark display, boundary bar, confidence
  indicator, weakness chip, question row, paper identity line, trend sparkline,
  XP/streak, processing state, empty/error/offline family, navigation shells) as
  real components with every state, and document each in the component
  catalogue. Later phases compose these; they do not invent new primitives
  without adding them here.
- **Retro-fit Phase 2.** Bring the existing student screens (home, upload flow,
  scanner, marking progress, results, question detail) onto the token system and
  component library. Run `/impeccable audit` then `/impeccable normalize` then
  `/impeccable polish` on them, per §10.
- **Visual + accessibility test harness** (see §11): Playwright screenshot
  corpus across breakpoints and states, Puppeteer audit runner with axe-core and
  Lighthouse, contact-sheet generation, and baseline snapshots committed.
- **Acceptance:** token file is the only source of design values (grep proves no
  stray hex codes or arbitrary spacing in components); every cross-cutting
  component exists with all states and appears in the catalogue; every Phase-2
  screen passes the quality bar in `BUILD/QUALITY-BAR.md`; axe reports zero
  serious or critical violations across all existing routes; Lighthouse
  accessibility ≥ 95 on every route; the screenshot corpus builds and the
  contact sheet is committed to `reports/phase-2.5/`.
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
- Every screen built in this phase follows `docs/LEMELY_UI_SPEC.md` and uses
  only Phase-2.5 tokens and components.
- Acceptance: E2E per role (Playwright); at-risk flags verified against seeded
  scenarios; **plus the standing UI gate** — quality bar in
  `BUILD/QUALITY-BAR.md` met, zero serious/critical axe violations, Lighthouse
  a11y ≥ 95, screenshot corpus captured for every new screen × state ×
  breakpoint, Impeccable audit/polish run and clean, no visual regressions on
  existing screens.

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
  generated practice demonstrably targets seeded weaknesses; **plus the
  standing UI gate** (see Phase 3 acceptance and `BUILD/QUALITY-BAR.md`).
  Question rendering (maths notation, diagrams) must be verified visually in
  screenshots, not assumed.

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
  (headless push mock), announcement flow; **plus the standing UI gate**.
  Motion added in this phase must respect `prefers-reduced-motion`, proven by
  a test.

### Phase 6 — Hardening + ship
- Full-suite pass: backend, frontend, E2E across all roles on seeded realistic
  data; concurrency test (parallel uploads/markings); basic load sanity on the
  API; security re-review (authz matrix re-verified).
- Docker Compose: one command brings up Supabase-local + backend + served SPA
  build with correct CORS/proxy; documented.
- Deployment docs for future free-tier cloud (Supabase cloud + container host).
- **Full-product visual QA sweep**: regenerate the entire screenshot corpus,
  produce a per-role contact sheet, run `/impeccable audit` across all
  frontend source, run `npx impeccable detect src/` and resolve every
  finding, and run the axe + Lighthouse suite over every route in both
  themes. Any regression against Phase-2.5 baselines is a blocker.
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
- **Model discipline (this is a hard cost constraint):** you run on
  **Sonnet by default**. Opus is expensive and scarce on this plan, so it is
  reserved for work where a wrong answer is costly and hard to reverse.
  Escalate a single run to Opus by setting `next_run_model: opus` in
  `BUILD/STATE.md`, writing STATE.md carefully, and exiting cleanly — the
  supervisor relaunches you on Opus for exactly one run, then reverts to
  Sonnet. Escalate ONLY for: the database/tenancy schema design (Phase 1), the
  auth + RBAC model (Phase 1), the det-parser keep/delete decision (Phase 0),
  the marking-confidence + review-threshold design (Phase 2), and any bug that
  survived two serious Sonnet debugging attempts. That is roughly 5–8 Opus runs
  across the entire build; if you find yourself escalating more often, you are
  using it as a crutch. Never escalate for implementation, tests, wiring,
  docs, scraping, or refactors. The same rule governs subagents: `architect`
  (Opus) is for design documents only, budget ~2 invocations per phase; use
  `scout` and `reporter` (Haiku) freely, `implementer`/`test-engineer`/
  `reviewer`/`debugger`/`data-engineer` (Sonnet) for everything else.
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
8. **Any diff touching `web/`** additionally requires: `BUILD/QUALITY-BAR.md`
   satisfied; `/impeccable audit` on the changed files with findings fixed;
   `npx impeccable detect` clean; axe zero serious/critical; Lighthouse
   accessibility ≥ 95 on affected routes; screenshots captured for every
   new or changed screen × state × breakpoint; no unintended visual
   regression against committed baselines.

## 7. Reporting protocol

- Per phase: `reports/phase-N/REPORT.md` — what was built, feature mapping,
  decisions made, test summary (counts, coverage, accuracy metrics), Playwright
  **screenshots** of every new/changed screen (`reports/phase-N/screens/`),
  command outputs proving gates, known issues. Commit it; it must render on GitHub.
- ntfy (topic `lemely-ErBPK7TIRGD1sQP5`): phase start, phase complete (with
  2-line summary), blocker raised, budget warnings, run complete, and a daily
  one-line heartbeat. Use the JSON publish endpoint so you get markdown, tags,
  priority, and a click-through in one request:
  ```
  curl -s ntfy.sh -d '{
    "topic": "lemely-ErBPK7TIRGD1sQP5",
    "title": "<short title>",
    "message": "<markdown message, e.g. **Phase 2** complete: ...>",
    "tags": ["<emoji-shortcode-or-two>"],
    "priority": <1-5>,
    "markdown": true,
    "click": "https://github.com/LemelyIG/Lemely",
    "actions": [{"action":"view","label":"Open repo","url":"https://github.com/LemelyIG/Lemely"}]
  }'
  ```
  Every message you send must include a progress line as its first line:
  `**Phase N** — X/Y tasks · <what just happened>`. A notification that says
  only "task complete" is useless from a phone.
  Send one on: phase start, each significant task completed (not every file
  edit — roughly every 30–60 minutes of work), phase complete, blocker raised,
  budget warning, and any decision recorded in DECISIONS.md.
  Priority: 2=low (routine task progress), 3=default (phase start), 4=high
  (blocker, budget warning, phase complete), 5=urgent (build complete, halted).
  Use `sequence_id` for repeating message types so they update in place instead
  of stacking: `lemely-task` for routine progress, `lemely-budget` for spend
  updates. One-off events (phase complete, blockers) get no sequence_id so they
  persist in the notification list. The supervisor owns `lemely-heartbeat`,
  `lemely-limit`, `lemely-checkpoint` and `lemely-watchdog` — do not publish to
  those sequence IDs yourself. Suggested tags: `rocket` (phase
  start), `white_check_mark` (phase/gate pass), `warning` (blocker),
  `moneybag` (budget), `tada` (build complete). When a notification concerns a
  specific artifact (a phase report, a failing test log), attach it instead of
  just describing it — PUT the file with a `Filename` header to
  `ntfy.sh/lemely-ErBPK7TIRGD1sQP5` (truncate to under 2MB; tail is usually
  what matters). The supervisor script (`supervisor.sh`) already applies this
  same format to its own crash/limit/complete notifications, including
  deduplication: it suppresses a repeat notification for a failure with the
  same signature (log tail, timestamps/paths scrubbed) seen again within 30
  minutes, so you don't need to replicate that dedup logic yourself — just
  don't spam near-identical blocker notifications in a tight loop; if you're
  re-raising the same blocker, check `BUILD/BLOCKERS.md` first and skip the
  notification if you already recorded it recently.
- Session journal: append a dated entry to `BUILD/JOURNAL.md` at the end of each
  session (3–6 lines: did, learned, next).

## 7b. What the supervisor does for you

You do not manage the process lifecycle — `supervisor.sh` does. It relaunches
you after every exit, parses the reset time out of usage-limit messages and
sleeps until precisely then (falling back to an hourly retry if no time is
parseable), sends a 20-minute in-place progress heartbeat, refreshes a
dead-man's-switch alert so the human is told if the machine dies, attaches new
`reports/phase-N/REPORT.md` files to notifications as they appear, and stops
cleanly if a reset is more than 14 hours out (weekly cap). It also honours
`next_run_model: opus` for one-run escalation. Because it restarts you freely,
**exiting is cheap and safe** — take that option rather than limping along in a
bloated context.

## 8. Budget protocol (Gemini)

Hard ceiling **$8.00** total, enforced by the Phase-0 persistent tracker; ntfy at
$4 and $6. Mock Gemini in all automated tests. Live calls are permitted only for:
(a) small controlled accuracy-validation batches (estimate cost first with the
existing `estimate-cost` machinery, cache aggressively — the disk cache is your
friend), (b) smoke-testing each AI feature once E2E. If the ceiling is reached:
continue building with mocks/cache, record what still needs live validation in
DELIVERY.md, ntfy priority=high. The human can top up (max +$12) but do not assume
it.

## 8b. Token discipline (treat tokens as a budget, like Gemini dollars)

Every token you spend is capacity you cannot spend later in the build. These
are requirements, not suggestions:

- **Never read a large file to "get oriented."** Delegate to `scout` (Haiku)
  and work from its summary. Read files in full only when you are about to
  edit them, and prefer `Grep`/`Glob` with narrow patterns over `Read` on
  anything over ~400 lines. Read specific line ranges when you know them.
- **One gate command, not seven.** Phase 0 creates `scripts/check.sh` which
  runs ruff + mypy + import-linter + pytest + the web checks, suppresses all
  passing output, and prints only failures plus a one-line summary per tool
  (`pytest -q --tb=short`, `ruff --quiet`, etc.). After Phase 0, run gates via
  `./scripts/check.sh` and never by invoking the tools individually — verbose
  green output is pure waste.
- **Pipe noisy commands to a file and read the tail.** `cmd > /tmp/out 2>&1;
  tail -n 40 /tmp/out`. Never let a full test suite, npm install, Docker build,
  or scraper dump its entire output into context.
- **Briefs carry paths, not contents.** When delegating, give the subagent file
  paths and acceptance criteria; do not paste code into the brief. The subagent
  can read what it needs.
- **Keep the stable stuff stable.** `BUILD/MISSION.md` and `CLAUDE.md` are read
  every session and benefit from prompt caching — do not rewrite them casually.
  Volatile state belongs in `BUILD/STATE.md`, which stays small: a checklist,
  not a narrative. Prune completed phases from STATE.md down to a single done
  line once their report is committed.
- **Checkpoint early.** Exit cleanly at ~60% context rather than pushing to the
  limit; a fresh session re-reading a tight STATE.md is far cheaper than a
  bloated one carrying dead context. Exiting is always safe.
- **Don't re-derive.** Anything you learned that cost real work to discover
  (an environment quirk, a mirror's URL pattern, a schema decision) goes into
  `BUILD/DECISIONS.md` or `docs/` immediately so no future session pays for it
  twice.
- **Batch related edits.** One considered pass over a file beats five
  re-reads and five small patches.
- **No speculative work.** Do not build abstractions, tests, or docs for
  features outside the current phase.

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


## 10. Design skills — how to use them

Three skill packs are installed alongside the built-in `frontend-design` skill.
They overlap; using all of them on everything wastes tokens and produces
muddled output. Use them for what each is actually good at.

**Authority order when guidance conflicts:**
`docs/LEMELY_UI_SPEC.md` (product truth) > `DESIGN.md` / `PRODUCT.md` (brand
truth) > `BUILD/QUALITY-BAR.md` (quality floor) > skill opinions. A skill that
wants a bolder, more animated, or more asymmetric interface than the spec calls
for is overruled by the spec. Record any conflict you resolve in DECISIONS.md.

### Impeccable — the primary design workflow
Command sequence for a new surface:
`/impeccable shape <surface>` (structure and concept, before any code) → build
the screen → `/impeccable audit <path>` (diagnose) → `/impeccable critique
<path>` (evaluate against intent) → fix → `/impeccable normalize <path>` (align
with our tokens) → `/impeccable polish <path>` (final pass).
Also useful: `document` and `extract` for the component catalogue, `onboard` for
empty/first-run states, `harden` for edge cases, `adapt` for responsive work,
`quieter` where a surface has become noisy.
- `/impeccable craft` is **deprecated** — never use it.
- **Live mode is beta and needs an interactive dev server — never invoke it.**
  This run is unattended; it will hang.
- `npx impeccable detect src/` is the CI-side deterministic detector. It needs
  **Node 24+**; verify with `node -v` at Phase 2.5 start and record a blocker if
  the version is lower rather than silently skipping the check.
- Impeccable does **not** cover accessibility testing. Run axe afterwards
  regardless of how clean an audit comes back.

### UI/UX Pro Max — the reference database
Query it for concrete decisions: palettes, font pairings, per-product-type
rules, UX guidelines, chart types, icon choices, motion presets. It is a
**lookup**, not a generator of our system — DESIGN.md already fixes brand.
Invoked through its Python search script (it requires Python 3):
`python .claude/skills/ui-ux-pro-max/scripts/search.py "<query>" [--design-system]
[--variance 1-10] [--motion 1-10] [--density 1-10]`
Use `--density` high for the teacher and admin surfaces, low-to-mid for student
screens. Do not let `--design-system` output overwrite our tokens; take from it
only what fills a genuine gap, and record what you took in DECISIONS.md.

### Taste-Skill (`design-taste-frontend`) — anti-generic pressure
Best on the marketing/landing surface (G-01) and anywhere a screen has come out
looking templated. **Its v2 defaults are wrong for this product and must be
overridden explicitly in every invocation:**
- It assumes Next.js + Framer Motion + Radix. **We are React 19 + Vite +
  Tailwind v4.** Never introduce Next.js, and do not add a new animation or
  component library without an explicit decision recorded in DECISIONS.md.
- Its default dials (variance 8 / motion 6 / density 4) are "artsy and kinetic."
  Use instead: **landing/marketing → variance 7, motion 5, density 3;
  student app → variance 4, motion 3, density 5; teacher/admin → variance 3,
  motion 2, density 8.** A student checking a mark at 11pm and a teacher
  triaging thirty students both need clarity over expression.
- It is instructed to apply taste decisions without asking. Constrain it by
  naming the tokens and components it must use.

### Built-in `frontend-design`
The fallback if any pack is missing, and a useful second opinion on typography
and hierarchy. Its guidance on avoiding default AI aesthetics applies
throughout.

### Token cost control for design work
These skills are verbose. Load a skill when you are about to do the work it
serves, not speculatively; do one audit→fix→polish cycle per screen rather than
iterating indefinitely; batch several screens into one audit pass where they
share a pattern; and never run all three packs on the same screen.

## 11. Web testing, screenshots, and visual QA

Both Playwright and Puppeteer are used, with a strict division of labour so
they do not duplicate each other:

**Playwright — behaviour and the screenshot corpus.**
All functional E2E: user journeys per role, auth and RBAC paths, the correction
pipeline end to end, forms, keyboard navigation, offline behaviour. Also owns
the screenshot corpus, because it can drive the app into arbitrary states.
Run headless, Chromium primary, WebKit for the PWA/iOS-adjacent paths.

**Puppeteer — audit and measurement.**
The standalone audit runner: axe-core injection per route, Lighthouse runs
(performance, accessibility, best practices, PWA), full-page captures for the
contact sheets, and console-error collection. Kept separate so audits can run
against a built preview without the E2E suite.

**Screenshot policy — capture generously.** Storage is cheap; the human is
reviewing this remotely from a phone and screenshots are the primary evidence
that anything actually works.
- Capture **every screen × every state × every breakpoint**, and both themes if
  the design is dual-mode. States means the real ones: default, loading, empty,
  error, offline, and for anything showing a mark also low-confidence and
  teacher-corrected. Breakpoints: **380, 768, 1440** minimum.
- Path convention:
  `reports/phase-N/screens/<screen-id>/<state>--<breakpoint>[--dark].png`
  using the screen IDs from `docs/LEMELY_UI_SPEC.md` (S-15, T-08, …) so the
  corpus is navigable and diffable across phases.
- Also capture: every step of a multi-step flow (the upload/scanner sequence and
  the marking progress stages especially), each meaningful interaction state of
  the cross-cutting components, and any bug you fix — before and after.
- Generate a **contact sheet** (an HTML index with thumbnails grouped by screen)
  per phase, commit it, and attach it to the phase-complete ntfy notification.
- Commit baselines. Compare against them each phase; an unintended diff is a
  blocker, an intended diff is re-baselined with a note in the phase report.

**Standing automated checks**, wired into `scripts/check.sh` and CI:
axe-core (zero serious/critical), Lighthouse thresholds (accessibility ≥ 95,
performance ≥ 80 on the student routes), `npx impeccable detect src/`,
TypeScript + oxlint, Playwright suite, Puppeteer audit runner, console-error
assertion (zero errors on every route), and the responsive check (no horizontal
scroll at any breakpoint from 320px up).

Keep the harness cheap in tokens: these runs produce enormous output. Always
redirect to a file and read the summary plus failures only — never let a
Lighthouse or axe JSON dump land in context.

---

Begin: read `BUILD/STATE.md`, `docs/LEMELY_UI_SPEC.md`, `DESIGN.md`, and the
reports for phases 0–2, then execute the current phase.
