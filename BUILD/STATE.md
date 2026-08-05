# BUILD STATE — single source of truth

status: RUNNING            # RUNNING | COMPLETE | HALTED
current_phase: 2.5
last_updated: 2026-08-05T21:35:00Z
gemini_spend_usd: 0.0580

## Rules for maintaining this file
- Update BEFORE starting and AFTER finishing every task. Assume sudden death.
- Keep exactly one task `doing` at a time.
- When all Phase-6 acceptance criteria pass and DELIVERY.md is committed,
  set `status: COMPLETE` — the supervisor stops on this value.
- Prune a phase's detail to a single summary line once its `reports/phase-N/REPORT.md`
  is committed and merged to develop (MISSION §8b) — full rationale lives in
  `BUILD/DECISIONS.md` and the phase report, not here.

## Phase 0 — Foundation repair — DONE (2026-07-30)
All 8 tasks complete: CI green (ruff/web), `lemely/io/det/` wired + monolith deleted (D0.5),
persistent Gemini cost ledger ($8 cap, D0.6), HistoryStore corruption surfaced, single lockfile,
`lemely doctor` real reachability. 395 passed / 84.56% cov. Merged to develop.
Report: `reports/phase-0/REPORT.md`. PR #3 (rolling develop→main, NOT merged).

## Phase 1 — Database + Auth + Tenancy — DONE (2026-08-01)
Local Supabase stack, 22-table schema (additive-only, D1.2/D1.3), GoTrue auth + backend-issued
HS256 JWTs (D1.4/D1.5), RBAC on every route + both IDORs killed (D1.6), HistoryStore→Postgres
for the web surface (D1.8/D1.9 — CLI/Gradio kept on JSON store), seat model (D1.10), 3-device
session registry (D1.11). Adversarial review: no Critical/High bypass (D1.12). 548 passed /
85.44% cov. Merged to develop. Report: `reports/phase-1/REPORT.md`.

### Carried backlog from Phase 1 (non-blocking, do opportunistically)
- [ ] todo — (D1.9) Migrate CLI + Gradio history to the DB (or retire Gradio), then delete
      `lemely/io/history_store.py` + `tests/test_history_store.py`. Parity already proven.
- [ ] todo — (D1.6) Teacher per-tenant ownership (own-classes-only) — lands with the Phase 3
      class model; role boundary is already enforced, row-level ownership is not yet.

## Phase 2 — The core loop, real and end-to-end — DONE (2026-08-05)
Real SSE correction pipeline (P2.1), grade-boundary ingestion from cambridgeinternational.org
(P2.2, D2.1), accuracy harness + 10 golden fixtures across 0580/0606/0625 (P2.3), plagiarism/
AI-detection advisory flags (P2.4), Supabase Storage upload path (P2.5, D2.6), frontend
resurrected from dead code + auth/session foundation (P2.6), student + teacher surfaces wired
to real data (P2.7/P2.8), PWA foundation + camera capture (P2.9), Playwright E2E acceptance
verified against the live Supabase stack with an independent Postgres persistence check
(P2.10). 609 passed / 3 skipped (live-only) / 86.38% cov. Merged to develop (6254879), pushed.
PR #3 updated (title "Phases 0–2", body extended), NOT merged. ntfy sent.
Report: `reports/phase-2/REPORT.md`. Gemini cumulative spend $0.058/$8.00.

### Honest limitations carried forward from Phase 2 (must appear in DELIVERY.md, not silently resolved)
- **Accuracy gate NOT met (D2.5):** mark-level agreement 83.8% vs ≥95% target; flag_recall
  27.3% vs the 100%-disagreements-flagged target. Threshold tuning (D2.2/D2.3) and
  deterministic calculated-answer verification (D2.4) are both exhausted; the remaining gap
  is free-form algebraic method-verification — materially harder, out of scope so far.
- **PWA Lighthouse + camera-capture** not live-tested (no Chromium/camera in this sandbox,
  P2.9) — verified by inspection/manual trace only; see `reports/phase-2/pwa-limitations.md`.
  Needs a real-device/browser pass before claiming a hard pass.

## Phase 2.5 — Design system + frontend quality foundation — RUNNING
- [x] Verify environment: node v26.6.0 (≥24 ok), python3 3.13.5,
      .claude/skills/ has accuracy-check, design-taste-frontend, impeccable, ui-ux-pro-max
- [x] Confirm DESIGN.md + PRODUCT.md + docs/LEMELY_UI_SPEC.md + BUILD/QUALITY-BAR.md exist,
      no TODO/TBD/placeholder markers found (grep clean)
- [x] Read docs/LEMELY_UI_SPEC.md in full (71 screens / 13 components / 5 principles) —
      no conflict with Phase-2, scope fixed to tokens+C-1..C-13+6-screen retrofit (D2.10)
- [x] P2.5.1: Token source built (web/src/index.css) — DESIGN.md hex palette replacing the
      pre-DESIGN.md OKLCH port, same var names (no screen breakage), + type scale, spacing,
      radii, motion tokens, 380/1440 breakpoints, confidence/mark-state/grade-band semantic
      scales. Verified: tsc clean, build clean, oxlint clean. Committed 98c6068 on
      feature/phase-2.5-design-system.
- [x] P2.5.2: C-1..C-13 built (web/src/components/ui/, 13 files) via 2 parallel
      worktree-isolated designer agents, merged + verified together (tsc/build/oxlint
      clean). docs/COMPONENT_CATALOGUE.md documents every component. Committed 8882834.
- [x] P2.5.3: Retro-fit done — Overview.tsx (home), CorrectPaper.tsx (upload/scanner/
      marking-progress, S-14 now uses ProcessingState C-10 with 3 real SSE-backed stages),
      PaperResult.tsx (results/question-detail, QuestionRow C-6 + ConfidenceIndicatorSummary
      + BoundaryBar C-3) onto tokens + C-1..C-13. Deleted viz.tsx::Bar + BoundaryRail.tsx;
      Directions.tsx (out-of-scope screen) got a minimal import-swap-only fix to BoundaryBar
      so the build stays green. Also fixed a pre-existing bug found during retrofit:
      PaperResult rendered plagiarism/AI-detection flags to the student — removed
      (QUALITY-BAR.md: integrity flags are teacher-only, never shown to students). tsc/
      build/oxlint clean, grep for oklch()/stray literals in the 4 touched screens clean.
      Verified independently (diffs read, commands re-run) before commit, per MISSION
      delegation protocol. Content gaps found, not fixed (backend/DTO work, out of this
      phase): no real per-grade boundary thresholds on ResultDTO (BoundaryBar now honestly
      shows "not available" instead of the old fake fixed-percent gradient); S-14 has no
      SSE signal for "identifying the paper" / "analysing weak topics" stages or a running
      question count; S-15's comparison-to-previous-attempts / top-3-mistakes / weak-topic-
      chips have no backing data; CorrectPaper.tsx is still a single-step form, not the
      full S-10..S-13 wizard. Committed on feature/phase-2.5-design-system.
- [x] P2.5.4: Impeccable audit → polish pass (D2.11: installed skill has no `normalize`
      command, audit's Theming dimension + polish's drift triage cover it) on Overview.tsx,
      CorrectPaper.tsx, PaperResult.tsx via `designer` agent; Directions.tsx audited only
      (0 diff, out of retrofit scope, confirmed no regression from P2.5.3's import swap).
      Fixes: missing h1/live-region/label/aria-pressed a11y gaps (9 branches across the 3
      screens), exact-token swaps (gap/p-[22px]→*-container-mobile, rounded-[8px]→rounded),
      nearest-canonical-step swaps (text-[36px]/[34px]→text-display-lg/-md,
      rounded-[10px]→rounded-md — DESIGN.md scale doesn't have exact steps at 34/36/10),
      and Overview's subjects table (fixed grid-cols summing 336px+ that overflowed <380px)
      rebuilt mobile-first (flex stack + md:grid, no duplicate a11y announcement since the
      hidden GradeBadge copy uses display:none). `npx impeccable detect` on all 4: zero
      findings before and after (ruleset has no signal on hex-free Tailwind-utility TSX).
      Orchestrator-verified independently: tsc/build/oxlint re-run clean, diffs read
      line-by-line, portal shell checked for no duplicate h1, token values checked against
      index.css. Pre-commit run scoped to changed files only — `--all-files` was tried first
      and found to reformat unrelated vendored `.claude/skills/` files (last touched in
      d83aa67, never previously through pre-commit); reverted that scope creep, see D2.11
      addendum note in commit body instead of a new decision entry.
      Flagged, not fixed (component-library/backend, out of this task's 4-file scope):
      Overview's momentum chart duplicates C-8 TrendSparkline but ResultDTO/OverviewDTO
      ships precomputed SVG paths not raw numbers; CorrectPaper's pulse-dot animation
      duration (1.6s) isn't a motion token; confidence-indicator.tsx's compact chip has a
      sub-44px touch target; state-views.tsx's Empty/Error/OfflineState heading is a `div`
      not a real heading tag (screens compensated locally with sr-only h1s); student portal
      shell uses raw oklch() nav literals and has no C-13 BottomNav mounted on mobile.
      These are real gaps for a future component-library/DTO pass, not P2.5.4 scope.
      Uncommitted at write time — committing this + STATE.md + JOURNAL.md together next.
- [x] P2.5.5: Playwright screenshot harness (screen × state × breakpoint, ID convention
      from LEMELY_UI_SPEC.md screen IDs). Prereq fixed first (D2.12, committed 2148e41 +
      ad727c8): the E2E harness had a silent PATH blocker that meant the suite hadn't run at
      all since P2.5.1, and its first real run caught + fixed a genuine nested-<button> a11y
      bug in QuestionRow (C-6). `web/e2e/screenshots.spec.ts` drives the 4 retrofitted
      screens against the live stack (Overview→S-06, CorrectPaper→S-10 entry + S-14
      marking-in-progress, PaperResult→S-15/S-17; Directions.tsx explicitly excluded — it's
      a static internal design gallery, not a docs/LEMELY_UI_SPEC.md screen, out of D2.10
      scope) at 380/768/1440, capturing every real state reachable without a second live
      paper (default/empty/loading/error for S-06, default/file-selected for S-10,
      marking-in-progress/error for S-14, default for S-15, expanded for S-17) = 30 PNGs
      under `reports/phase-2.5/screens/`. Found on disk uncommitted from a prior session
      (dispatched to `visual-qa`, STATE.md said "running") but the corpus was short 6 files
      (S-06/error, S-14/error) — verified by actually running the suite myself rather than
      trusting the prior session's claim, per MISSION delegation protocol, and it failed:
      2 real bugs in the harness, not the app. (1) The delayed-route handler simulating
      S-06's loading state called `route.continue()` unguarded; React.StrictMode
      (`main.tsx`) double-invokes the mount effect in dev, aborting the first overview
      fetch on remount, so the delayed `continue()` fired against an already-aborted
      request and threw "Route is already handled!" before the error-state reload ever
      ran — wrapped in try/catch (aborted-first-request is benign, the second real request
      gets its own route invocation). (2) The zero-console-errors assertion caught the
      browser's own "Failed to load resource: 500/413" logging, which fires for ANY
      non-2xx response — including the ones this suite deliberately simulates to reach the
      error states it's supposed to capture; `watchConsole` now excludes that one message
      pattern, still catching genuine app errors (React warnings, uncaught exceptions).
      All 30 screenshots now captured, full E2E suite green (8/8, including the
      pre-existing _smoke/correct-paper specs — no regression), tsc/build/oxlint clean,
      pre-commit scoped to the changed spec file clean. Two incidentally-regenerated
      Phase-2 baseline PNGs (side effect of re-running correct-paper.spec.ts) reverted,
      not committed — out of this task's scope.
- [x] P2.5.6: Puppeteer audit runner (`web/scripts/audit.mjs`, `npm run audit`) built on a
      prior session's in-progress, uncommitted work (found on disk: script + package.json/
      vite.config.ts changes + partial output for 2/4 routes). Verified rather than trusted
      per MISSION delegation protocol — ran it myself, it failed on the 3rd route with a
      real script bug: `waitForText(page, "out of")` checks `document.body.innerText`, but
      MarkDisplay (C-2) renders "5/8" as visible text and puts "5 out of 8 marks, ..." only
      in an `aria-label`, which `innerText` never surfaces — worked by luck on routes 1-2
      because their wait text was genuinely visible. Fixed: wait on
      `page.waitForSelector('[aria-label*="out of"]')` instead (mirrors Playwright's
      `getByLabel` used for the same assertion in `web/e2e/screenshots.spec.ts`). Re-ran
      clean end-to-end: builds the frontend, boots the real backend + `vite preview`,
      signs up + logs in through the real UI, uploads the golden fixture to reach a real
      corrected-paper state, audits all 4 in-scope routes (G-04 login, S-10 correct-entry,
      S-15/S-17 result, S-06 overview) with axe + Lighthouse, captures G-04's screenshots
      (only route with no existing Playwright capture — 9 PNGs, default/error/loading ×
      380/768/1440), and regenerates `reports/phase-2.5/contact-sheet.html` from the full
      corpus (39 thumbnails across 5 screen dirs). tsc/build/oxlint clean, pre-commit
      scoped to the 3 changed source files clean, console-errors.json empty (0 real errors
      across the whole run). Lighthouse has no PWA category at all in the pinned v13.4.1
      (confirmed by reading its source — Google removed it upstream around v11/v12);
      audited performance/accessibility/best-practices/seo instead, noted in the script's
      own header comment rather than silently dropping the requirement.
      Baselines captured, real findings — NOT fixed here, P2.5.8's job (full
      QUALITY-BAR.md pass is a separate, later task in this same phase):
      Lighthouse accessibility 95-100 across all 4 routes (meets the ≥95 gate). Axe:
      login 3 moderate (landmark-one-main, page-has-heading-one, region — the bare
      pre-auth shell has no `<main>`/h1 landmark structure); student-correct/-result/
      -overview each have 1-2 **serious** color-contrast violations, all the same root
      cause — the shared portal shell's `text-t3` muted-label color (#7e6865) measures
      4.45:1 against its background, just under the 4.5:1 AA threshold, on subject-card
      captions and nav labels that appear on every authenticated route; student-overview
      additionally has 2 serious `aria-progressbar-name` violations (unlabeled
      `role="progressbar"` elements, 0/100 style subject-mastery bars). None of these are
      new regressions from this task — pre-existing gaps in shared components carried
      from P2.5.3/2.5.4, now measured for the first time because this is the first run of
      a tool that can measure them. Zero serious/critical violations is a phase-level
      acceptance criterion (MISSION §4); P2.5.8 must resolve these before the phase
      report, not silently drop them.
- [x] P2.5.7: `scripts/check.sh` created (it did not exist — a Phase-0 gap carried since
      2026-08-04, see JOURNAL.md) plus `scripts/check_ui_gates.py`. check.sh runs backend
      (ruff check/format, mypy, lint-imports, pytest) + web (typecheck, oxlint, build,
      `npx impeccable detect src/`) gates unconditionally, then Playwright E2E + `npm run
      audit` (P2.5.6's Puppeteer runner) + `check_ui_gates.py` (enforces QUALITY-BAR.md's
      zero-serious/critical-axe + Lighthouse-a11y≥95 thresholds by parsing the audit's
      `_summary.json` files) only when the local Supabase stack is reachable — SKIPs
      (not FAILs) those three otherwise, mirroring pytest's existing DB-test skip
      pattern. Suppresses passing output, prints only failures + a PASS/FAIL/SKIP line
      per tool + one final summary line, per MISSION §8b.
      Building it surfaced a real, independent bug (D2.13): plain `ruff check .` /
      `ruff format --check .` — the exact commands `.github/workflows/ci.yml` runs — pick
      up 329 errors from vendored `.claude/skills/ui-ux-pro-max/scripts/` content that was
      never excluded from `pyproject.toml`'s ruff config (only pre-commit's `--all-files`
      scope had been fixed for this, per D2.11, back in P2.5.4 — the plain-CLI-command gap
      was never connected to it). This branch's CI `ruff check .` step has very likely been
      red since d83aa67 added the skill pack, unrelated to anything built in this phase so
      far. Fixed: added `.claude` to `extend-exclude` — a `pyproject.toml` change, so it
      fixes CI too without touching `ci.yml`. Full `./scripts/check.sh` run afterward:
      everything PASS except `ui-thresholds`, which correctly FAILs on exactly the 3
      pre-existing axe findings P2.5.6 recorded above — confirms the gate enforces what it
      claims to, and correctly blocks merge until P2.5.8 fixes them.
- [ ] doing — P2.5.8: Full BUILD/QUALITY-BAR.md pass; grep proves no stray hex/spacing values;
      must resolve the P2.5.6 axe baseline findings (login landmarks, shared-shell
      color-contrast, overview progressbar labels) — `./scripts/check.sh`'s `ui-thresholds`
      step (P2.5.7) currently and correctly FAILs on these; it must go green as part of
      this task, not be worked around
- [ ] P2.5.9: Phase report + contact sheet + PR develop→main + ntfy

Decisions: D2.10 (scope). Reference: reports/phase-2.5/ for screenshots + contact sheet.

## Phase 3 — Teacher + Parent surfaces
Not yet started. Branch from `develop` as `feature/phase-3-teacher-parent`. Per MISSION §4:
- Teacher: class management, per-class/per-student analytics, aggregate weakness topics,
  at-risk flagging (declining trend OR predicted grade ≥2 boundaries below target OR ≥14
  days inactive — each flag labeled with its reason), human-review queue override-and-annotate
  flow (overrides feed back as recorded corrections; the review-queue *display* already exists
  from P2.8 — this phase adds the override action and at-risk logic on top of it).
- Teacher quiz builder: difficulty targeting by expected grade, included-material selection,
  question pool from generated/classified past-paper questions, assign to class, auto-marked,
  results feed analytics.
- Parent portal: phone-OTP login (the mock-provider auth backend already exists from P1.4 —
  this phase builds the actual portal screens/routes, which don't exist yet), linked children,
  performance + weakness views (read-only), notification preferences.
- This phase is also where teacher per-tenant ownership (own-classes-only, deferred from D1.6)
  should land, since it needs the real class model this phase builds.
- Acceptance: E2E per role; at-risk flags verified against seeded scenarios.


## Session journal
See `BUILD/JOURNAL.md` for the dated 3-6 line entries; decisions and rationale live in
`BUILD/DECISIONS.md` (D0.x/D1.x/D2.x). Superseded per-task narrative for Phases 0-2 has been
pruned from this file per MISSION §8b now that their reports are committed — see the git
history of this file, or the phase REPORT.md files, if the detail is ever needed again.
