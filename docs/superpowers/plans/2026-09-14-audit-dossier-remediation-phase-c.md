# Audit Dossier Remediation — Phase C (`feat/ui-kit-and-dark-mode`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land every Phase C row of the remediation ledger (36 rows, packets C1–C5): five kit primitives (brand lockup, section head, subject glyph, progress ring, table cell density), the teacher table and forms migrations onto the kit, twenty screen-level fixes across student, onboarding, teacher and marketing surfaces, the cross-cutting print/perf-floor/reduced-motion/copy-gate work, and a real dark theme (token inversion, toggle, flash-free pre-mount, AA-measured, captured).

**Architecture:** Additive changes to the Vite/React PWA (`web/`). New kit files under `web/src/components/ui/` (`brand-lockup.tsx`, `section-head.tsx`, `subject-glyph.tsx`, `progress-ring.tsx`), one new `web/src/lib/theme/` family plus `web/src/lib/countdown.ts`, a second colour ladder in `web/src/index.css` under `:root[data-theme="dark"]`, theme resolution in `web/public/shell-init.js` (CSP forbids inline scripts), build-time dark placeholders in `web/vite/preMountShell.ts`/`themeColor.ts`, one backend DTO field (`total` on `GET /teacher/review`), CI wiring for the copy gate, DESIGN.md §3/§3.2/§3.6/§12/§13/§14 edits plus a new §16 "Recorded decisions", and `docs/design-canvas-notes.md`. No new runtime dependencies. Each packet is one or more commits; the ledger row status is updated in the same commit.

**Tech Stack:** React 19 + react-router-dom 7 (data router), Tailwind 4 (`@theme inline` maps every `--color-*` utility to a `var(--token)`, so a token ladder swap re-themes every utility with no class changes), Phosphor icons (`@phosphor-icons/react`), Nivo (`lib/nivoTheme.ts` resolves tokens at runtime via `getComputedStyle`), Vitest (Node environment, no jsdom), Playwright 1.62 (`page.emulateMedia({ colorScheme, media, reducedMotion })`), Puppeteer + Lighthouse 13 in `scripts/audit.mjs`, FastAPI + SQLAlchemy (`lemely/web/routers/teacher.py`, `lemely/db/review_repo.py`).

**Spec:** `docs/superpowers/specs/2026-09-10-audit-dossier-remediation-design.md` (Phase C section, lines 379–461) · **Ledger:** `docs/superpowers/specs/2026-09-10-audit-dossier-remediation-ledger.md` (36 rows with `phase = C`; ids listed per task below) · **Phase B plan (mirror):** `docs/superpowers/plans/2026-09-13-audit-dossier-remediation-phase-b.md`

## Global Constraints

- Branch `feat/ui-kit-and-dark-mode` (exists, branched from `develop` at `521edaf1` = merged Phase B), PR into `develop`, never `main`. Worktree `.claude/worktrees/feat-ui-kit-and-dark-mode`; all file and git operations happen there. The worktree is a fresh checkout: `web/node_modules` does not exist (Task 0 runs `npm ci`); the venv is the main checkout's `/home/sico/Code/Lemely/.venv` (`source /home/sico/Code/Lemely/.venv/bin/activate`).
- Signed commits: `git commit -S`; conventional scopes (`feat(ui):` kit primitives, `refactor(web):` migrations, `feat(web):` screens, `feat(theme):` dark mode, `feat(api):` backend, `docs(design):`, `test(e2e):`, `ci(web):`); `pre-commit run --all-files` (inside the venv) before every commit; trailer `Claude-Session: https://claude.ai/code/session_01CxbrmXri2Fm1p2KFgjL3rr`.
- **Never run the full test suite locally** (memory `no-full-test-suite-locally`). Web: `npm run typecheck && npm run lint && npx vitest run <named files> && npm run build`. Backend: `pytest --no-cov tests/<named file>` + `ruff check` + `mypy lemely`. CI runs everything.
- **Test-architecture constraint, hard rule (D3.20):** `web/vitest.config.ts` is `environment: "node"`, `include: ["tests/unit/**/*.test.ts"]`. No jsdom, no `@testing-library`, no `.test.tsx` anywhere, no `matchMedia` mocks. Every new unit test is a plain `.ts` file using either (a) source-text assertions (`readFileSync` + `stripComments` from `tests/unit/support/jsxSource.ts`, the pattern in `tests/unit/screenEntrance.test.ts`) or (b) pure-function extraction (the decision lives in an exported function with injected inputs, the component only wires it — `tests/unit/navigationDirection.test.ts`). Component *behaviour* coverage lives in Playwright only (`web/e2e/theme.spec.ts`, Task 13).
- Implementers are `executor` model=sonnet (`designer` model=sonnet for Tasks 1, 2, 12 — pure kit/visual work); reviewers `code-reviewer` model=opus; verifier `verifier` model=opus. Main orchestrating session (Fable, ralph + `Skill(orchestrator)`) never writes code (memories `delegate-by-model`, `plan-authoring-by-fable`).
- Every implementer brief starts with: `Skill(superpowers:test-driven-development)`, `Skill(superpowers:verification-before-completion)`, `Skill(vitest-testing-patterns)`, `Skill(react-best-practices)` (any `.tsx`), `Skill(checklist-discipline)` + the task's domain skills (table below). Invoke before writing code; follow; do not summarise it back. Every skill named in this plan was verified present on disk at `~/.claude/skills/` or `.claude/skills/` on 2026-09-14.
- **Hallmark stamp** on every new file under `web/src/components/`: first line `/* Hallmark · pre-emit critique: P_ H_ E_ S_ R_ V_ */`, each axis 1–5 and ≥3, derived per file from `.claude/skills/hallmark/SKILL.md` (Philosophy/Hierarchy/Execution/Specificity/Restraint/Variety), never copied flat from a sibling. 36 existing kit files carry one; `tests/unit/hallmarkStamp.test.ts` (Task 1 creates it) pins every file under `web/src/components/ui/` created on this branch.
- DESIGN.md §14 rule 3: tokens only, no arbitrary Tailwind values. Where this plan removes a hand-rolled literal (`px-[16px] py-[10px]` on the teacher tables, `min-[640px]` on the student header) it replaces it with the scale (`px-4 py-2.5`, `sm:`), never with a new literal. New dimensions become tokens or `@utility` in `index.css` first.
- **Line numbers below were read on `develop` at `521edaf1` and are approximate; re-grep at the start of every task.**
- Ledger update in every commit: set the row's `status` to `done C<n>` and `evidence` to the verification command that passed plus a one-clause pointer to the file that proves it (the Phase B format: `` `npx vitest run tests/unit/x.test.ts` — `file.tsx` does Y ``). The phase-close verifier (Task 15) replaces `done C<n>` with `done <short sha>` and recounts the summary tables.
- Copy rules: no em-dashes in user-facing strings (`npm run check:copy` must stay at 0 findings — Task 11 puts it in CI); DESIGN.md error-copy voice; Caveat never carries meaning (§4.1); no red backgrounds anywhere in the app (PRODUCT.md "avoid red-heavy error states").
- CI guards from Phases A/B must stay green: `web/scripts/check-native-invariants.mjs` (runs in `npm run lint`), `web/scripts/check-bundle-budget.mjs` (`DEFAULT_BUDGET_KB = 150` gzip per chunk, `KNOWN_HEAVY_LAZY_CHUNKS` exempts `assemblePages-` at 175), `npm run check:installable` (CI only). Task 0 records the current largest chunks; the dark ladder (~45 declarations) must not push `index-*.css` over budget — it will not, but the number is recorded before and after.
- **Lessons from Phase B, now rules:** (1) a test failure labelled "pre-existing" is not dismissed until proven against `git show develop:<file>` and named in the report; (2) Pyright LSP diagnostics are not evidence — run `mypy lemely` and `ruff check`; (3) a "dead code" claim is verified numerically (call sites, reachable inputs) before deletion; (4) an agent that cannot run something (no browser, no backend) says "not run" — never "passes".
- Backend touch is minimal and additive: one DTO field (Task 9). No migrations in Phase C.
- If a packet needs a capability no listed skill covers, invoke `Skill(skill-coach)` to create it before implementing (orchestrator's gap rule, design spec "Orchestration protocol" item 1).

## Skills per packet

Process, every packet (in Global Constraints above, not repeated per task): `superpowers:test-driven-development`, `superpowers:verification-before-completion`, `vitest-testing-patterns`, `react-best-practices` (any `.tsx`), `checklist-discipline`.

| Packet | Domain skills |
|---|---|
| C1 (kit primitives) — Tasks 1, 2 | `composition-patterns`, `design-system`, `ui-refactor`, `hallmark` (stamp only) |
| C2 (table migrations) — Tasks 3, 4 | `ui-refactor`, `composition-patterns`, `design-system` |
| C2 (forms migration + audit assertion) — Task 5 | `form-validation-architect`, `ui-refactor`, `playwright-screenshot-inspector` (audit.mjs) |
| C3 (student screens, red-pen) — Task 6 | `ui-refactor`, `ux-heuristics`, `web-design-guidelines`, `impeccable`, `color-contrast-auditor`, `design-accessibility-auditor` |
| C3 (onboarding, study plan) — Task 7 | `ui-refactor`, `ux-heuristics`, `impeccable` |
| C3 (teacher tools, camera) — Task 8 | `ui-refactor`, `ux-heuristics`, `web-design-guidelines`, `impeccable` |
| C3 (teacher analytics, nav badge, review strip; backend `total`) — Task 9 | `ui-refactor`, `ux-heuristics`, `rest-api-design` |
| C3 (docs, decisions, marketing padding) — Task 10 | `technical-writer`, `writing-guidelines` |
| C4 (print, perf floor, reduced-motion unit half, copy gate CI, DESIGN.md §13/§14) — Task 11 | `playwright-screenshot-inspector`, `vitest-testing-patterns`, `github-actions-pipeline-builder`, `technical-writer` |
| C5 (dark ladder + AA) — Task 12 | `dark-mode-design-expert`, `color-contrast-auditor`, `design-system`, `typography-expert` |
| C5 (theme toggle, storage, pre-mount, theme-color, e2e) — Task 13 | `dark-mode-design-expert`, `pwa-expert`, `playwright-e2e-tester` |
| C5 (consumers, captures, DESIGN.md) — Task 14 | `dark-mode-design-expert`, `playwright-screenshot-inspector`, `technical-writer` |
| Reviewers (opus, every packet) | `code-review-checklist`, `design-accessibility-auditor`; Task 9 additionally `security-auditor` (backend) |
| Phase close (Task 15) | `ai-slop-cleaner`, `merge-readiness` |

## Orchestration

Main session: Fable, `/oh-my-claudecode:ralph` against this plan file, invoking `Skill(orchestrator)` as coordinator. The orchestrator decomposes into the packets below, dispatches `executor`/`designer` (sonnet) / `code-reviewer` (opus) / `verifier` (opus) per packet (protocol steps a–e in the design spec), and synthesises results into the ledger. Ralph exits Phase C only when every ledger row with `phase = C` is non-`pending` and verifier evidence is recorded.

Parallelism (up to 3 packets when file ownership is disjoint):
- **Wave 1 (parallel):** Task 1 (C1a), Task 2 (C1b), Task 11 (C4). Disjoint: Task 1 owns `brand-lockup.tsx`/`section-head.tsx`/`primitives.tsx` and the seven lockup sites + the two Overview headers; Task 2 owns `subject-glyph.tsx`/`subject-tag.tsx`/`progress-ring.tsx`/`table.tsx`/`Grading.tsx`; Task 11 owns the `@media print` block in `index.css`, `question-row.tsx` (print class only), `audit.mjs`, `check_ui_gates.py`, `lib/celebration.ts`, `ci.yml`, DESIGN.md §13/§14.
- **Wave 2, lane A (sequential):** Task 3 → Task 4 → Task 5. All three touch `Review.tsx`, `ClassRoster.tsx`, `Classes.tsx`, `AtRiskList.tsx` (tables and raw fields live in the same files). Task 3 follows Task 2 (needs `density`).
- **Wave 2, lane B (parallel with lane A):** Task 6 (student: `PaperResult.tsx`, `Overview.tsx`, `question-row.tsx` red-pen — after Task 11's print class lands in the same file), Task 7 (onboarding/study plan: `StudyPlanWeek.tsx`, `studyPlanData.ts`, `QuestionnaireStep.tsx`, `Announcements.tsx`, new `lib/countdown.ts`), Task 10 (docs + marketing). Task 8 (`QuizBuilder.tsx`, `PracticeGenerator.tsx`, `Grading.tsx`) follows Task 2 (same file `Grading.tsx`). Task 9 (`ClassAnalytics.tsx`, `nav-shells.tsx`, `teacher/index.tsx`, `ReviewItem.tsx`, backend) follows Task 1 (`teacher/index.tsx`) and Task 4 (`ClassAnalytics.tsx` tables).
- **Wave 3 (sequential, last):** Task 12 → Task 13 → Task 14. Dark mode measures and captures the *final* token consumers, so it runs after every UI task; Tasks 12–14 own `index.css` `:root` blocks, `index.html`, `shell-init.js`, `vite/*.ts`, `ProfileSettings.tsx`, `nivoTheme.ts`, `screenshots.spec.ts`. **Never run Task 12–14 in parallel with anything.**
- **Task 15** closes the phase.

Phase end: `superpowers:finishing-a-development-branch` → push + PR into `develop` (body ends with the session URL), `merge-readiness` skill report. User merges; Phase D plan is written against merged `develop`.

---

### Task 0: Branch bootstrap, baseline, re-verify, ledger wiring

**Files:**
- Modify: `docs/superpowers/specs/2026-09-10-audit-dossier-remediation-ledger.md` (status/evidence columns only)
- Add: this plan file (`docs/superpowers/plans/2026-09-14-audit-dossier-remediation-phase-c.md`) to the branch

**Skills:** none beyond process skills.

- [ ] **Step 1: Confirm branch state.** Run: `git status --short --branch && git log --oneline -1`. Expected: `## feat/ui-kit-and-dark-mode...origin/develop`, HEAD `521edaf1`, untracked: this plan file only.
- [ ] **Step 2: Install and baseline.** `cd web && npm ci` (background), then `npm run typecheck && npm run lint && npm run build` → green. Record from the build output the three largest gzip chunks and the `check:bundle` line (Phase B's PR reported `assemblePages-*` 171KB exempt at 175, `CorrectPaper-*` and `index-*` under 150). Backend: `source /home/sico/Code/Lemely/.venv/bin/activate && ruff check . && mypy lemely` → clean.
- [ ] **Step 3: Re-verify spec claims against `521edaf1`; record the real numbers in the commit body** (each is used by a task below):
  - Brand lockup copies: **7** sites, not 5 — `student/index.tsx:509`, `teacher/index.tsx:343`, `parent/index.tsx:212`, `admin/index.tsx:243` (with a subtitle line), `settings/SettingsFrame.tsx:161` (inside a `Link`), `auth/Login.tsx:98` (`h-7 w-9` + `text-display-md`), `marketing/index.tsx:125` (lowercase "lemely" wordmark per `design-import-spec.md`). `marketing/index.tsx:183` is a footer sentence beside a small mark, not a lockup — untouched.
  - Raw form fields under `web/src/portals`: **39** sites in 14 files (`rg -n "<input|<select|<textarea" web/src/portals`), not 29: 23 `<input` outside checkbox/radio/file/hidden types, 16 `<select`/`<textarea`. Per file: `ReviewItem.tsx` 8, `Announcements.tsx` 6, `Classes.tsx` 4, `Review.tsx` 3, `AtRiskList.tsx` 3, `QuestionnaireStep.tsx` 3, `Grading.tsx` 2 (file inputs), `FlashcardDecks.tsx` 2, `ProfileSettings.tsx` 2, `parent/index.tsx` 2, `MarkSchemes.tsx` 1, `CreateFirstClass.tsx` 1, `ClassRoster.tsx` 1, `SubjectsStep.tsx` 1.
  - Teacher `<table>` sites: **9 tables in 6 files** — `Review.tsx:496`, `ClassRoster.tsx:279`, `StudentDetail.tsx:150,366`, `AtRiskList.tsx:373`, `ClassAnalytics.tsx:239,421,580`, `Classes.tsx:268`. `ClassDetail.tsx` has no table (three stat cards in a grid); `MarkSchemes.tsx:41` is a CSS-grid table (`COLS = "grid grid-cols-[minmax(0,1.6fr)_84px_…]"` — an arbitrary value, §14 rule 3 violation) — Task 4 migrates it to the primitive. No teacher file imports `Table` today (six admin/marketing files do).
  - `check:copy` is a package script (`web/package.json:17`) and **not** a CI step (`.github/workflows/ci.yml` web job: typecheck, unit tests, lint, build, installability). Task 11 adds it.
  - `@media print` exists at `index.css:1013` and hides only texture (`.paper-grain::after`, `.ruled-bg`, `.dotted-bg`, `.sticker`). `audit.mjs`'s `student-practice-print` state (`:1982`) captures a print *route*, not print media (`emulateMedia` never called). Task 11 adds both.
  - Practice `source` filter: backend already accepts it (`lemely/web/routers/practice.py:65-71 _parse_source`, `:173`, `:244`; `schemas_practice.py:28`); frontend sends it (`usePracticeApi.ts:29`) but `PracticeGenerator.tsx:77` hardcodes `source: null` — the UI control is what's missing (Task 8).
  - Student streak: the header renders `XPStreak variant="compact"` inside `hidden min-[640px]:inline-flex` (`student/index.tsx:582`) — hidden below 640px, and the breakpoint is an arbitrary value. Task 6 fixes both.
  - Reduced-motion decision: `prefersReducedMotion()` (`lib/celebration.ts:203`) reads `window.matchMedia` directly; `useCountUp` (`celebration.tsx:67`) and `Flourish` (`:171`) call it. Task 11 injects the query so it is unit-testable without jsdom.
  - `ReviewQueueList` (`teacherTypes.ts:689`) carries `items` + `nextCursor`, **no `total`**; `teacher/index.tsx:594-599` records that Review's bottom tab has no badge for exactly that reason. Task 9 adds `total`.
  - Theme: `index.html:45` has one `<meta name="theme-color" content="%LEMELY_THEME_COLOR%">` filled by `vite/themeColor.ts` from `--paper`; the pre-mount shell's colours are seven `%LEMELY_COLOR_*%` placeholders filled by `vite/preMountShell.ts`; CSP is `script-src 'self'` with no inline scripts, so the flash-free theme init lives in `public/shell-init.js` (Task 13), not an inline script as the spec says.
  - `screenshots.spec.ts:16` says "No dark mode — this product is single-theme"; `reduced-motion.spec.ts:170` notes `colorScheme` *is* a typed Playwright option. Task 14 uses `page.emulateMedia({ colorScheme: "dark" })`.
- [ ] **Step 4: Ledger wiring.** No Phase C row is already fixed on develop; all 36 stay `pending`. Note in the ledger's Phase C paragraph (below the summary tables) that the real counts above supersede the spec's 5/29/8.
- [ ] **Step 5: Commit** `docs(plan): Phase C plan and baseline re-verification against develop 521edaf1 (C0)` (plan file + ledger note).

---

### Task 1 (C1a): `BrandLockup`, `SectionHead`, hallmark-stamp test

**Files:**
- Create: `web/src/components/ui/brand-lockup.tsx` (`BrandLockup`), `web/src/components/ui/section-head.tsx` (`SectionHead`)
- Modify: the seven lockup sites from Task 0 (`student/index.tsx:505-513` `Brand()` helper, `teacher/index.tsx:340-346`, `parent/index.tsx:210-215`, `admin/index.tsx:241-250`, `settings/SettingsFrame.tsx:158-164`, `auth/Login.tsx:96-101`, `marketing/index.tsx:123-130`)
- Modify: `web/src/portals/student/screens/Overview.tsx:506-520` (page header → `SectionHead`), `web/src/portals/teacher/screens/Overview.tsx:194-199,249-256,275-279` (page header and "Needs you" head → `SectionHead`), `web/src/portals/teacher/screens/ClassAnalytics.tsx` (every `text-eyebrow` + title pair that heads a panel — 14 `text-eyebrow` sites, migrate the ones that are section heads, leave stat labels), `web/src/portals/teacher/screens/Review.tsx` (page header; 8 sites, same rule)
- Modify: `web/src/components/ui/primitives.tsx` (`Eyebrow`, `Display` unchanged; `SectionHead` composes them — no new primitive here)
- Test: `web/tests/unit/brandLockup.test.ts`, `web/tests/unit/sectionHead.test.ts` (source text), `web/tests/unit/hallmarkStamp.test.ts` (every `.tsx` under `web/src/components/ui/` whose path is in `git diff --name-only --diff-filter=A develop...HEAD` carries the stamp on line 1 with six axes ≥3; the test reads the file list from `git` via `execFileSync`, falling back to "no new files" when git is unavailable)

**Interfaces:**
- Produces: `BrandLockup({ size = "sm", casing = "title", animated, as = "div", className, children }: { size?: "sm" | "md"; casing?: "title" | "lower"; animated?: boolean; as?: "div" | "span"; className?: string; children?: ReactNode })` — renders `<BrandMark aria-hidden="true" className={size === "sm" ? "h-6 w-8 shrink-0" : "h-7 w-9 shrink-0"} animated={animated} />` followed by `<span className={size === "sm" ? "text-display-sm text-ink" : "text-display-md text-ink"}>{casing === "lower" ? "lemely" : "Lemely"}</span>`, then `children` (admin's subtitle line). **Contract:** the mark is `aria-hidden`; the wordmark text is the accessible name; a caller that wraps it in a `Link` supplies no extra `aria-label` (the text is enough). `BrandMark` itself gains nothing.
- Produces: `SectionHead({ eyebrow, title, kicker, action, level = 2, rung = "display-md", className }: { eyebrow?: string; title: string; kicker?: string; action?: ReactNode; level?: 1 | 2 | 3; rung?: "display-lg" | "display-md" | "display-sm"; className?: string })` — layout `flex items-end justify-between gap-4`; left column: `<Eyebrow>` (when given) above `<Display as={h${level}} rung>` above kicker (`text-body-md text-ink-muted`, when given); right: the `action` slot. Exactly one `h*` element, level chosen by the caller so document outline stays honest. Page headers use `rung="display-lg" level={1}`; panel heads `display-md`/`level={2}`.
- Consumed by: Task 7 (`StudyPlanWeek` countdown header uses `SectionHead kicker`), Task 9 (`ClassAnalytics` panels already migrated here), Task 14 (dark captures of Overview/Review/ClassAnalytics show the migrated heads).

**Skills:** `composition-patterns`, `design-system`, `ui-refactor`, `hallmark` (read the six axes; stamp each new file).

**Behaviours:**
1. All seven lockup sites render `<BrandLockup>`; no `<BrandMark` remains under `web/src/portals` except `marketing/index.tsx:183` (footer sentence). Marketing header passes `casing="lower"`; Login passes `size="md"`; admin passes its subtitle as `children`.
2. Screen readers announce the lockup once ("Lemely"), never "image" + "Lemely".
3. Student Overview, teacher Overview, ClassAnalytics and Review page/panel heads render through `SectionHead`; the visual result is pixel-equivalent (same rungs, same tokens) — this task changes structure, not look.
4. Every new kit file carries a derived hallmark stamp.

- [ ] **Step 1: Re-grep** `<BrandMark` (8 sites incl. footer), `text-eyebrow` in the four screens, `Eyebrow`/`Display` signatures in `primitives.tsx:18-46`.
- [ ] **Step 2: Failing tests.** `brandLockup.test.ts`: `brand-lockup.tsx` contains `aria-hidden="true"` on the mark and both wordmark casings; no file under `web/src/portals` except `marketing/index.tsx` contains `<BrandMark`, and `marketing/index.tsx` contains it exactly once; each of the seven files contains `<BrandLockup`. `sectionHead.test.ts`: `section-head.tsx` imports `Eyebrow` and `Display` from `./primitives`, renders no `h` element except through `Display`; `student/screens/Overview.tsx`, `teacher/screens/Overview.tsx`, `ClassAnalytics.tsx`, `Review.tsx` each contain `<SectionHead`. `hallmarkStamp.test.ts` as described in Files.
- [ ] **Step 3: Run** `npx vitest run tests/unit/brandLockup.test.ts tests/unit/sectionHead.test.ts tests/unit/hallmarkStamp.test.ts` → FAIL.
- [ ] **Step 4: Implement behaviours 1–4.**
- [ ] **Step 5: Run** the three files → PASS; `npm run typecheck && npm run lint && npm run build && npm run check:copy`.
- [ ] **Step 6: Ledger:** `x-brandlockup-duplicated-5x` (evidence names the real count, 7), `x-sectionhead-no-equivalent` → `done C1`.
- [ ] **Step 7: Commits** (two): `feat(ui): BrandLockup replaces seven hand-rolled mark+wordmark copies (C1)`, `feat(ui): SectionHead primitive, migrated on Overview, ClassAnalytics, Review (C1)`.

---

### Task 2 (C1b): `SubjectGlyph`, `ProgressRing`, table cell density

**Files:**
- Create: `web/src/components/ui/subject-glyph.tsx` (`SubjectGlyph`, `subjectGlyphFor`), `web/src/components/ui/progress-ring.tsx` (`ProgressRing`, pure `ringDash`)
- Modify: `web/src/components/ui/subject-tag.tsx:77-90` (`SubjectTag` gains `icon?: boolean`), `web/src/components/ui/table.tsx` (`Table` gains `density`, `TH`/`TD` read it), `web/src/portals/teacher/screens/Grading.tsx:355-445` (inline ring → `ProgressRing`)
- Test: `web/tests/unit/subjectGlyph.test.ts` (pure `subjectGlyphFor` + source text), `web/tests/unit/progressRing.test.ts` (pure `ringDash` + source text: `Grading.tsx` no longer contains `strokeDasharray`), `web/tests/unit/tableDensity.test.ts` (pure `CELL_PADDING` + source text)

**Interfaces:**
- Produces: `subjectGlyphFor(tone: BadgeTone): Icon` (Phosphor): `sky → MathOperations`, `lilac → Atom`, `sage → Flask`, `clay → Leaf`, `amber → BookOpen`, `rose → GraduationCap`, any other tone → `GraduationCap`. `SubjectGlyph({ subject, size = "md", className }: { subject: string; size?: "sm" | "md"; className?: string })` — a `rounded-md` pastel tile (`bg-pastel-{tone}` from `subjectTone(subject)`, `text-pastel-{tone}-ink`), `h-8 w-8` (`sm`) / `h-10 w-10` (`md`), glyph `aria-hidden`, tile carries `role="img"` + `aria-label={subject}`. `SubjectTag` with `icon` renders `subjectGlyphFor(tone)` at `size={12}` before the text, `aria-hidden`.
- Produces: `ringDash(value: number, circumference: number): string` — clamps `value` to 0..100, returns `` `${(circumference * value / 100).toFixed(1)} ${circumference.toFixed(1)}` `` (exactly what `Grading.tsx:361` computes today). `ProgressRing({ value, tone = "accent", label, size = 48, strokeWidth = 4, className }: { value: number; tone?: ProgressTone; label: string; size?: number; strokeWidth?: number; className?: string })` — `ProgressTone` imported from `progress-bar.tsx`; `<svg role="img" aria-label={label}>` with a `--rule` track circle and a `stroke-{tone}` value circle using `strokeDasharray={ringDash(value, circumference)}`; **no transition on `stroke-dashoffset`/`dasharray`** (§9.2: transform/opacity only — the ring changes value discretely, as Grading's does today); `label` is the whole accessible sentence ("12 of 30 papers graded"), mirroring `ProgressBar`'s `label`.
- Produces: `type TableDensity = "comfortable" | "operate"`; `CELL_PADDING: Record<TableDensity, string> = { comfortable: "px-4 py-3", operate: "px-4 py-2.5" }` (operate = the `16px/10px` rhythm every hand-rolled teacher table uses, on the scale); `Table` gains `density?: TableDensity` (default `"comfortable"`) provided via `TableDensityContext`; `TH`/`TD` read the context and apply `CELL_PADDING[density]` instead of their literal `px-4 py-3`. `THead`'s `sticky` default and `z-sticky` unchanged.
- Consumed by: Tasks 3–4 (`<Table density="operate">` on every teacher table), Task 7 (`SessionRow` may use `SubjectGlyph` only if the row shows a subject — it shows a topic, so it uses `activityIcon` instead; `SubjectGlyph` lands on `Subject.tsx`'s header and the student sidebar's subject rows in this task as its first consumers), Task 8 (`Grading.tsx` keeps the ring), Task 14 (ring/glyph in dark captures).

**Skills:** `composition-patterns`, `design-system`, `ui-refactor`, `hallmark`.

**Behaviours:**
1. `Grading.tsx`'s graded/all ring renders through `ProgressRing`, same numbers, same label sentence; the `CIRC`/`dash` locals are gone.
2. `SubjectGlyph` appears on `student/screens/Subject.tsx`'s header (beside the subject name) and in the student sidebar's per-subject rows (`student/index.tsx` `NavGroups` subject items) at `size="sm"`; `SubjectTag icon` is used on `student/screens/Overview.tsx`'s subject rows.
3. `Table` accepts `density`; existing admin/marketing tables (six files) are unchanged (default `comfortable`).
4. Both new files carry a derived hallmark stamp.

- [ ] **Step 1: Re-grep** `strokeDasharray|CIRC` in `Grading.tsx`, `subjectTone` callers, `px-4 py-3` in `table.tsx`, admin `<Table` sites (must stay green).
- [ ] **Step 2: Failing tests.** `subjectGlyph.test.ts`: the six tone→icon pairs; `subject-glyph.tsx` contains `role="img"`; `subject-tag.tsx` contains `icon`; `Subject.tsx` and `student/index.tsx` contain `<SubjectGlyph`. `progressRing.test.ts`: `ringDash(50, 100) === "50.0 100.0"`, `ringDash(150, 100)` clamps to full, `ringDash(-5, 100)` to `"0.0 100.0"`; `progress-ring.tsx` contains no `transition`; `Grading.tsx` contains `<ProgressRing` and not `strokeDasharray`. `tableDensity.test.ts`: `CELL_PADDING.operate === "px-4 py-2.5"`; `table.tsx` contains `TableDensityContext` and no literal `px-4 py-3` outside `CELL_PADDING`.
- [ ] **Step 3: Run** the three files → FAIL.
- [ ] **Step 4: Implement behaviours 1–4.**
- [ ] **Step 5: Run** the three files plus `tests/unit/hallmarkStamp.test.ts` → PASS; `npm run typecheck && npm run lint && npm run build && npm run check:copy`.
- [ ] **Step 6: Ledger:** `x-motifs-subjectglyph-tile-missing`, `brand-subject-glyph-vs-subject-tag`, `x-progressring-inline-duplication-risk`, `x-motifs-progress-ring-not-systematized`, `x-motion-progress-ring-no-production-equivalent`, `x-density-operate-row-rhythm-matches-but-uncodified` → `done C1`.
- [ ] **Step 7: Commits** (three): `feat(ui): SubjectGlyph tile and SubjectTag leading icon (C1)`, `feat(ui): ProgressRing extracted from Grading's inline ring (C1)`, `feat(ui): Table density prop codifies the operate cell rhythm (C1)`.

---

### Task 3 (C2a): Table migration — Review, ClassRoster

**Files:**
- Modify: `web/src/portals/teacher/screens/Review.tsx:490-560` (`<table>` → `Table/THead/TBody/TR/TH/TD`), `web/src/portals/teacher/screens/ClassRoster.tsx:275-330`
- Test: `web/tests/unit/teacherTables.test.ts` (source text; created here, extended in Task 4)

**Interfaces:**
- Consumes: `Table density="operate"`, `THead sticky` (default true), `TR selected/disabled/onClick`, `TH numeric/scope`, `TD numeric` from `table.tsx` (Task 2).
- Produces: the migration pattern the remaining files copy: `<Table density="operate"><THead><TR><TH>…</TH><TH numeric>…</TH></TR></THead><TBody>{rows.map(r => <TR key onClick={…}><TD>…</TD><TD numeric>…</TD></TR>)}</TBody></Table>`; every numeric column (marks, counts, percentages, ages in hours) uses `numeric`; `THead sticky={false}` only where the table is inside its own scroll container that is not the page (none in these two files).

**Skills:** `ui-refactor`, `composition-patterns`, `design-system`.

**Behaviours:**
1. Review's queue table and ClassRoster's roster table render through the primitive: `--paper-sunk` header surface, sticky header at `z-sticky`, `tabular-nums` right-aligned numbers, `--rule` dividers (DESIGN.md §12 "Tables").
2. Row click/keyboard behaviour (Review rows navigate to `/teacher/review/:itemId`; roster rows to the student) is preserved through `TR onClick/onKeyDown`.
3. The `px-[16px] py-[10px]` literals in these two files are gone (`density="operate"` carries the rhythm).

- [ ] **Step 1: Re-grep** `<table|<thead|<th |<td |px-\[16px\]` in both files; read `table.tsx` whole.
- [ ] **Step 2: Failing test.** `teacherTables.test.ts`: for `Review.tsx` and `ClassRoster.tsx`: source contains `<Table density="operate"` and does not contain `<table`, `px-[16px]`, `py-[10px]`.
- [ ] **Step 3: Run** `npx vitest run tests/unit/teacherTables.test.ts` → FAIL.
- [ ] **Step 4: Implement behaviours 1–3.**
- [ ] **Step 5: Run** → PASS; `npm run typecheck && npm run lint && npm run build`. If the backend is up: `npx playwright test e2e/teacher-journey.spec.ts` (it walks Review) → PASS; else record "e2e deferred to CI".
- [ ] **Step 6: Ledger:** `x-completeness-teacher-tables-bypass-table-primitive` stays `pending` until Task 4 finishes the set (note "2 of 6 files" in the evidence column).
- [ ] **Step 7: Commit** `refactor(web): Review and ClassRoster tables onto the Table primitive (C2)`.

---

### Task 4 (C2b): Table migration — StudentDetail, AtRiskList, ClassAnalytics, Classes, MarkSchemes

**Files:**
- Modify: `web/src/portals/teacher/screens/StudentDetail.tsx:150,366`, `AtRiskList.tsx:373`, `ClassAnalytics.tsx:239,421,580`, `Classes.tsx:268`, `MarkSchemes.tsx:41-120` (CSS-grid table → real `Table`)
- Test: `web/tests/unit/teacherTables.test.ts` (extend)

**Interfaces:**
- Consumes: Task 3's pattern. `ClassAnalytics.tsx:239`'s trend table sits inside a `max-h-[180px] overflow-y-auto` region (`:234-238`): the header stays sticky *inside that region* (sticky is relative to the scroll container, which is the point), so `sticky` stays default — but the region's own `max-h-[180px]` literal is replaced by a `max-h-48` scale step (192px) in the same edit. `:421` (a small inline stats table) passes `sticky={false}` — it has no scroll container and a sticky header inside a card is wrong.
- Produces: `MarkSchemes.tsx` columns become `TH`s with `scope="col"`; the `COLS` arbitrary grid template is deleted.

**Skills:** `ui-refactor`, `composition-patterns`, `design-system`.

**Behaviours:**
1. All 9 `<table>` sites + MarkSchemes' grid render through the primitive; no `<table` literal remains under `web/src/portals/teacher`.
2. `ClassAnalytics.tsx:241`'s header surface is `--paper-sunk` via `THead` (the finding's "header surface" clause).
3. Explicit `sticky={false}` appears exactly where the Interfaces block says and nowhere else; the commit body lists each table and its sticky decision.
4. `ClassDetail.tsx` is untouched (no table) — recorded in the commit body and the ledger evidence.

- [ ] **Step 1: Re-grep** `<table` under `web/src/portals/teacher` (expect 9 after Task 3: 7), `COLS` in `MarkSchemes.tsx`, `max-h-[`.
- [ ] **Step 2: Failing test (extend).** For every `.tsx` under `web/src/portals/teacher/screens`: source does not contain `<table`, `px-[16px]`, `py-[10px]`, `grid-cols-[minmax`; `ClassAnalytics.tsx` contains exactly one `sticky={false}`; `MarkSchemes.tsx` contains `<Table density="operate"`.
- [ ] **Step 3: Run** → FAIL.
- [ ] **Step 4: Implement behaviours 1–4.**
- [ ] **Step 5: Run** → PASS; `npm run typecheck && npm run lint && npm run build`; `npx playwright test e2e/teacher-journey.spec.ts e2e/at-risk-flags.spec.ts` if the backend is up, else "deferred to CI".
- [ ] **Step 6: Ledger:** `x-completeness-teacher-tables-bypass-table-primitive` → `done C2` (evidence: "9 tables in 6 files + MarkSchemes grid; ClassDetail has no table").
- [ ] **Step 7: Commits** (two): `refactor(web): StudentDetail, AtRiskList, Classes tables onto the Table primitive (C2)`, `refactor(web): ClassAnalytics tables and MarkSchemes grid onto the Table primitive (C2)`.

---

### Task 5 (C2c): Forms migration onto `Input`/`Select`/`Textarea`, audit assertion

**Files:**
- Modify: the 14 files from Task 0 (start with `teacher/screens/Classes.tsx:200,220,230,319`), in this order: `Classes.tsx`, `Review.tsx` (3 selects at `:358,373,387`), `ClassRoster.tsx:194`, `AtRiskList.tsx`, `ReviewItem.tsx` (8), `Announcements.tsx` (6), `MarkSchemes.tsx`, `CreateFirstClass.tsx`, `Grading.tsx` (2 file inputs — stay native but gain `data-kit-field="file"` via the existing `FileDrop` if not already; if `Grading` uses a bare `<input type="file">` behind a button, leave it and allowlist), `QuestionnaireStep.tsx` (3: free-text fields → `Input`; the `SkippableSlider` already wraps the kit `Slider`), `SubjectsStep.tsx` (1 select), `FlashcardDecks.tsx` (2), `ProfileSettings.tsx` (2: the timezone `<select>` → `Select`; the avatar `<input type="file">` stays, allowlisted), `parent/index.tsx` (2)
- Modify: `web/src/components/ui/input.tsx`, `select.tsx`, `textarea.tsx` (each root element gains `data-kit-field="input" | "select" | "textarea"`), `slider.tsx` (`data-kit-field="slider"`), `checkbox.tsx`/`radio.tsx` (`"checkbox"`/`"radio"`)
- Modify: `web/scripts/audit.mjs` (new per-route assertion after the axe pass: every `input:not([type=checkbox]):not([type=radio]):not([type=file]):not([type=hidden]):not([type=submit]), select, textarea` in the document has `[data-kit-field]`; a miss is a route failure listed in `route-failures.json` with the element's `outerHTML` head)
- Test: `web/tests/unit/formsMigration.test.ts` (source text: no `<input`, `<select`, `<textarea` under `web/src/portals` except lines whose tag carries `type="checkbox"|"radio"|"file"|"hidden"`; plus an explicit allowlist array in the test naming each surviving site with its reason), `web/tests/unit/kitFieldMarker.test.ts` (each kit field file contains its `data-kit-field` value)

**Interfaces:**
- Consumes: `Input { label: string; hint?; error?; state?; leadingIcon?; wrapperClassName? }` (`input.tsx:20-58`; `label` is required — visually hidden labels use the existing `labelClassName="sr-only"` path, check `select.tsx:8-26` for the shared prop), `Select { label; hint?; error?; labelClassName? }`, `Textarea`, `Slider { value; onValueChange; min; max; step?; "aria-label" }`.
- Produces: `data-kit-field` marker contract; the `audit.mjs` assertion named `kit-fields` in its per-route report.

**Skills:** `form-validation-architect`, `ui-refactor`, `playwright-screenshot-inspector` (for the `audit.mjs` edit — read its route/state schema at `:100-130` first).

**Behaviours:**
1. Every text-like field under `web/src/portals` renders the kit component with a visible or `sr-only` label (§12 "Inputs": never placeholder-as-label); search fields keep `type="search"` through `Input`'s `type` passthrough; number fields keep `type="number"` + `inputMode`.
2. Existing behaviour (controlled values, `autoFocus` on the rename field in `Classes.tsx:319`, `required`, `aria-label`s) is preserved via prop passthrough.
3. Checkbox/radio/file/hidden inputs are untouched; each survivor is named in the test's allowlist with a reason.
4. `audit.mjs` fails a route that renders a hand-rolled field; the assertion runs on every captured state, so the gate covers all portals.
5. `check:copy` stays at 0 (labels are new user-facing strings).

- [ ] **Step 1: Re-grep** `<input|<select|<textarea` under `web/src/portals` (39), `labelClassName|sr-only` in `select.tsx`/`input.tsx`, the `axe` pass in `audit.mjs` (where per-route checks run).
- [ ] **Step 2: Failing tests** as described in Files; the allowlist starts empty so the first run enumerates every survivor.
- [ ] **Step 3: Run** `npx vitest run tests/unit/formsMigration.test.ts tests/unit/kitFieldMarker.test.ts` → FAIL.
- [ ] **Step 4: Implement behaviours 1–5**, one file per commit chunk, `Classes.tsx` first.
- [ ] **Step 5: Run** the two files → PASS; `npm run typecheck && npm run lint && npm run build && npm run check:copy`; `node scripts/audit.mjs --help` (or its dry-run flag, re-grep) parses; if the backend is up, `npm run audit` on one teacher route confirms the `kit-fields` assertion reports; else "audit assertion exercised in CI".
- [ ] **Step 6: Ledger:** `x-completeness-forms-dimension-unaudited` → `done C2` (evidence names the real count: 39 sites, N migrated, M allowlisted).
- [ ] **Step 7: Commits** (four): `refactor(web): teacher Classes, Review, ClassRoster, AtRiskList fields onto kit Input/Select (C2)`, `refactor(web): ReviewItem, Announcements, MarkSchemes, CreateFirstClass fields onto the kit (C2)`, `refactor(web): student onboarding, flashcards, settings, parent fields onto the kit (C2)`, `test(web): kit-field markers and the hand-rolled-field assertion in audit.mjs (C2)`.

---

### Task 6 (C3a): PaperResult filter tabs, red-pen register, Overview streak chip

**Files:**
- Create: `web/src/lib/questionFilter.ts` (pure `filterQuestions`, `isFlagged`, `QuestionFilter`)
- Modify: `web/src/portals/student/screens/PaperResult.tsx:87-93` (`markState` moves to `lib/questionFilter.ts` and is re-exported), `:300-345` (`Tabs`/`TabsList` above the question list; the list reads `filterQuestions(questions, filter)`; filter in `?q=all|lost|flagged` via `useSearchParams` so it survives back-navigation, default `all`)
- Modify: `web/src/components/ui/question-row.tsx` (new `register?: "plain" | "red-pen"` prop; when `red-pen` the *expanded explanation slot* gets class `lm-red-pen`), `web/src/index.css` (new `.lm-red-pen` rule beside the `--mark-*` tokens: `color: var(--mark-wrong); font-weight: 500; border-inline-start: 2px solid var(--mark-wrong); padding-inline-start: var(--space-3)` — ink and a left rule only, **no background, no Caveat**)
- Modify: `web/src/portals/student/screens/PaperResult.tsx:318` (pass `register={markState(q) === "wrong" ? "red-pen" : "plain"}`; the feedback block at `:329-333` keeps `bg-paper-sunk` — the register applies to the explanation text, not the panel)
- Modify: `web/src/portals/student/screens/Overview.tsx:506-520` (below `sm`: `XPStreak variant="compact"` beside the greeting, from the same `useXp()`-style hook the header uses — re-grep `xp.data?.streak` in `student/index.tsx:560-586` for the hook name), `web/src/portals/student/index.tsx:582` (`hidden min-[640px]:inline-flex` → `hidden sm:inline-flex`)
- Modify: `DESIGN.md` §3.6 (new paragraph "The red-pen register": scope = the per-question wrong-answer explanation only; PRODUCT.md's "avoid red-heavy error states" caveat recorded verbatim; why ink+rule and never a fill)
- Test: `web/tests/unit/questionFilter.test.ts` (pure), `web/tests/unit/redPen.test.ts` (source text: `.lm-red-pen` declares no `background`; `question-row.tsx` applies it only inside the expanded slot; `PaperResult.tsx` passes `register`), `web/tests/unit/streakChip.test.ts` (source text: `Overview.tsx` contains `<XPStreak` with `sm:hidden`; `student/index.tsx` contains no `min-[640px]`)

**Interfaces:**
- Produces: `type QuestionFilter = "all" | "lost" | "flagged"`; `markState(q: QuestionResult): MarkState` (moved, unchanged); `isFlagged(q: QuestionResult): boolean` = `q.reviewReason != null || confidenceTierFor(q) === <the lowest tier in lib/markingConfidence.ts — re-grep the union and name it in the test>`; `filterQuestions(questions: readonly QuestionResult[], filter: QuestionFilter): QuestionResult[]` (`lost` = `markState !== "correct"`, `flagged` = `isFlagged`). `QuestionRowProps.register?: "plain" | "red-pen"` (default `plain`).
- Consumed by: Task 11 (the print layout keeps the filter's current selection — printing "Lost" prints only lost questions, which is the use case), Task 14 (dark capture of PaperResult shows the register in dark).

**Skills:** `ui-refactor`, `ux-heuristics`, `web-design-guidelines`, `impeccable` (audit/normalize/polish on PaperResult and Overview after the change), `color-contrast-auditor` (measure `--mark-wrong` on `--paper-sunk` and `--paper`: `--err` is 8.86:1 on its wash and ≥5.38:1 on paper per §3.6 — record the two numbers in the commit body), `design-accessibility-auditor`, `technical-writer`.

**Behaviours:**
1. PaperResult shows three tabs above the question list — All (n) · Lost (n) · Flagged (n) — counts from `filterQuestions`; empty filter result renders the existing `EmptyState` with marginalia "Nothing lost here" / "Nothing flagged".
2. The expanded explanation of a wrong question reads in `--mark-wrong` ink at weight 500 with a 2px left rule; partial/correct explanations are unchanged; no red background anywhere on the screen.
3. Below `sm`, Overview's greeting header shows the compact streak chip; at `sm` and above the header's existing chip shows and Overview's is hidden — never both.
4. DESIGN.md §3.6 carries the register's scope and the PRODUCT.md caveat.

- [ ] **Step 1: Re-grep** `ConfidenceTier` union in `lib/markingConfidence.ts`, `Tabs`/`TabsList` API at `tabs.tsx:47-110`, the xp hook in `student/index.tsx`, `EmptyState` props.
- [ ] **Step 2: Failing tests.** `questionFilter.test.ts`: `markState` for full/zero/between/`maxMarks 0`; `isFlagged` true on `reviewReason`, true on the lowest tier, false otherwise; `filterQuestions` for each filter on a 4-question fixture. Source-text tests as in Files.
- [ ] **Step 3: Run** `npx vitest run tests/unit/questionFilter.test.ts tests/unit/redPen.test.ts tests/unit/streakChip.test.ts` → FAIL.
- [ ] **Step 4: Implement behaviours 1–4; DESIGN.md first.**
- [ ] **Step 5: Run** the three files → PASS; `npm run typecheck && npm run lint && npm run build && npm run check:copy`; `npx playwright test e2e/student-journey.spec.ts` if the backend is up (it opens PaperResult), else "deferred to CI".
- [ ] **Step 6: Ledger:** `paper-no-question-filter-tabs`, `paper-red-pen-register-missing`, `student-home-streak-hidden-on-phone` → `done C3`.
- [ ] **Step 7: Commits** (three): `feat(web): PaperResult All/Lost/Flagged question filter (C3)`, `feat(web): red-pen register on wrong-answer explanations, DESIGN.md §3.6 scope (C3)`, `fix(web): streak chip visible on Overview below sm, header breakpoint on the scale (C3)`.

---

### Task 7 (C3b): Study-plan countdown header, session icons, session-length presets

**Files:**
- Create: `web/src/lib/countdown.ts` (`daysUntil`, `formatCountdown` moved out of `Announcements.tsx:67-77`; Announcements imports them)
- Modify: `web/src/portals/student/screens/studyplan/StudyPlanWeek.tsx:60-150` (page header → `SectionHead` with `kicker` = countdown line), `:151-200` (`SessionRow` gains a leading activity icon), `web/src/portals/student/screens/studyplan/studyPlanData.ts:255-300` (`activityIcon`)
- Modify: `web/src/portals/student/screens/onboarding/QuestionnaireStep.tsx:344-357` (three preset `Chip` buttons above the `SkippableSlider`), `web/src/portals/student/screens/onboarding/onboardingData.ts` (`SESSION_LENGTH_PRESETS`, `presetToWeeklyHours`)
- Test: `web/tests/unit/countdown.test.ts` (pure, moved from wherever Announcements' tests live — re-grep `daysUntil` in `tests/unit`), `web/tests/unit/activityIcon.test.ts` (pure), `web/tests/unit/sessionLengthPresets.test.ts` (pure), `web/tests/unit/studyPlanHeader.test.ts` (source text)

**Interfaces:**
- Consumes: `SectionHead` (Task 1); `StudyPlanWeekDTO` (`lib/studyPlanTypes.ts:50-70`: `subjectCode`, `weekStart`, stated hours); the student's target grade per subject from `meTypes.ts:83` (`targetGrade: string | null` on the profile's subject rows — re-grep the hook that serves it, likely `useMe()`/`useProfile()`); the exam date from the same source Announcements' countdown uses (re-grep `examDate` producers in `lib/hooks/`).
- Produces: `daysUntil(examDate: string, today: Date): number`, `formatCountdown(days: number): string` (unchanged bodies, new home). `activityIcon(activityType: string): Icon` — `practice → PencilSimple`, `flashcards → Cards`, `past_paper → FileText`, `review → BookOpen`, unknown → `Circle`. `SESSION_LENGTH_PRESETS = [{ id: "20m", label: "20 min a day", weeklyHours: 2 }, { id: "45m", label: "45 min a day", weeklyHours: 5 }, { id: "1h", label: "An hour or more", weeklyHours: 7 }] as const`; `presetToWeeklyHours(id: SessionLengthPresetId): number`; `presetForWeeklyHours(hours: number | null): SessionLengthPresetId | null` (exact match only — the slider stays the source of truth, chips are shortcuts and reflect selection only when the value equals a preset).

**Skills:** `ui-refactor`, `ux-heuristics`, `impeccable`.

**Behaviours:**
1. `StudyPlanWeek`'s header reads: eyebrow "This week" (perpetual-week framing; the 14-day canvas framing is gone), title = subject name, kicker = "Target grade B · Exam in 41 days" (either half omitted when unknown; both unknown → no kicker). Uses `daysUntil`/`formatCountdown`.
2. Each `SessionRow` starts with the activity glyph (`aria-hidden`; the text label `activityLabel` beside it already carries the meaning — §8 restraint rule).
3. The weekly-hours question offers three preset chips; tapping one sets the slider to the mapped hours; the chip whose hours equal the slider value renders pressed (`aria-pressed`).
4. `Announcements.tsx` behaves identically (import path change only).

- [ ] **Step 1: Re-grep** `daysUntil|formatCountdown` (definitions + tests), `targetGrade` hook, `examDate` producer, `SkippableSlider` props, `Chip` `aria-pressed` support (`chip.tsx:63-80`; add `pressed?: boolean` mapping to `aria-pressed` if absent).
- [ ] **Step 2: Failing tests.** `countdown.test.ts` (move existing cases; add 0/1/n days). `activityIcon.test.ts`: five mappings. `sessionLengthPresets.test.ts`: `presetToWeeklyHours("45m") === 5`; `presetForWeeklyHours(5) === "45m"`, `(6) === null`, `(null) === null`. `studyPlanHeader.test.ts`: `StudyPlanWeek.tsx` contains `<SectionHead` and `formatCountdown`, not `14 days`; `Announcements.tsx` imports from `@/lib/countdown`; `QuestionnaireStep.tsx` contains `SESSION_LENGTH_PRESETS`.
- [ ] **Step 3: Run** the four files → FAIL.
- [ ] **Step 4: Implement behaviours 1–4.**
- [ ] **Step 5: Run** → PASS; `npm run typecheck && npm run lint && npm run build && npm run check:copy`.
- [ ] **Step 6: Ledger:** `onboarding-plan-rows-no-icon-coding-no-live-type`, `onboarding-14day-framing-vs-perpetual-week`, `onboarding-session-length-chips-vs-weekly-hours-slider` → `done C3`.
- [ ] **Step 7: Commits** (two): `feat(web): study-plan countdown header and session activity icons (C3)`, `feat(web): session-length presets on the weekly-hours question (C3)`.

---

### Task 8 (C3c): QuizBuilder rail + length slider, practice source control + topic mark-loss, camera source on Grading

**Files:**
- Create: `web/src/lib/quizBuilderSummary.ts` (pure `settingsSoFar`, `estimateQuizMinutes`, `QUIZ_MINUTES_PER_QUESTION`, `quizLengthUpperBound`), `web/src/lib/practiceSources.ts` (`PRACTICE_SOURCES`)
- Modify: `web/src/portals/teacher/screens/QuizBuilder.tsx` (`<aside>` rail beside the `Stepper` at `md` and above listing `settingsSoFar(quiz, step)`; `StepPool:651-657`'s `Input type="number"` → `Slider` + caption `~N min`)
- Modify: `web/src/portals/student/screens/practice/PracticeGenerator.tsx:71-80` (`source` state + `Tabs` segmented control; per-topic mark-loss stat beside each topic `Checkbox`)
- Modify: `web/src/portals/teacher/screens/Grading.tsx` (third source: "Use camera" button opening `CameraCapture` from `web/src/components/CameraCapture.tsx`; captured pages go through `assemblePagesToPdf` from `lib/pdf/assemblePages.ts` (lazy import, as `CorrectPaper.tsx` does) into the same upload path the file input uses)
- Backend verify-first (no edit unless needed): `lemely/web/schemas_practice.py` topic DTO — if it lacks a per-topic marks-lost figure, add `marksLost: int` to the topic model and compute it in the practice repo from the student's lost marks on that topic (re-grep `weak_topics`/`lost` in `lemely/db/practice_repo.py`); `QuestionSource` enum values (`rg -n "class QuestionSource" lemely/`) become `PRACTICE_SOURCES`
- Test: `web/tests/unit/quizBuilderSummary.test.ts` (pure), `web/tests/unit/practiceSources.test.ts` (source text: `PRACTICE_SOURCES` values equal the backend enum — the test reads `lemely/core/…py` with a regex, the same cross-language pin `design-tokens.test.ts` uses for `index.css`), `web/tests/unit/gradingCamera.test.ts` (source text: `Grading.tsx` imports `CameraCapture` and lazy-imports `assemblePages`), backend `tests/test_practice_topics_marks_lost.py` if the DTO changes

**Interfaces:**
- Produces: `settingsSoFar(quiz: QuizDetail, currentStep: number): { label: string; value: string }[]` (steps strictly below `currentStep` that have a value: Title, Subject, Questions, Difficulty, Pool; empty array at step 1). `QUIZ_MINUTES_PER_QUESTION = 2.5`; `estimateQuizMinutes(count: number): number` (`Math.ceil(count * 2.5)`); `quizLengthUpperBound(poolCount: number | null): number` (`poolCount ?? 50`, min 1, max 50). `PRACTICE_SOURCES: readonly { value: string; label: string }[]` + `"All sources"` as the `null` option. Grading's camera path reuses `CameraCapture`'s existing `onCapture(pages: Blob[])` contract (re-grep its props; it was extended in Phase B Task 8).
- Consumed by: Task 14 (dark captures of QuizBuilder are not in the list — none).

**Skills:** `ui-refactor`, `ux-heuristics`, `web-design-guidelines`, `impeccable`, `rest-api-design` (only if the DTO gains `marksLost`).

**Behaviours:**
1. QuizBuilder shows a "So far" rail (`SectionHead` eyebrow "So far", `dl` of label/value) beside the stepper from `md`; below `md` it collapses to a single line under the stepper. It lists only steps already completed.
2. Quiz length is a `Slider` 1..`quizLengthUpperBound(poolCount)` with the value and "~N min" (2.5 min per question) rendered beside it; the stored `requestedCount` semantics are unchanged; the upper bound is the pool count when known.
3. PracticeGenerator has a segmented source control (All · <each `QuestionSource`>) that sets `filters.source`; the preview count updates through the existing `usePracticePreview`.
4. Each topic checkbox shows "N marks lost" from the DTO (omitted when the figure is absent or 0 — never "0 marks lost" as decoration).
5. Grading offers "Use camera" as a third source beside drop/browse; captured pages become one PDF upload through the existing path; the wake-lock/scanner behaviour of `CameraCapture` is reused unchanged.
6. `content-classified-practice-mental-model`: the practice generator's header kicker states the mental model in one sentence ("Questions come from past papers, your own marked papers, or Lemely's practice bank; pick a source or use all") — copy without em-dashes.

- [ ] **Step 1: Re-grep** `Stepper` props (`stepper.tsx`), `poolCountQuery`/`requestedCount` in `StepPool`, `QuestionSource` enum, `PracticeTopicsDTO` fields, `CameraCapture` props, `assemblePagesToPdf` import site in `CorrectPaper.tsx`.
- [ ] **Step 2: Failing tests** as in Files (`settingsSoFar` for steps 1, 3, 6 on a fixture; `estimateQuizMinutes(7) === 18`; `quizLengthUpperBound(null) === 50`, `(12) === 12`, `(0) === 1`).
- [ ] **Step 3: Run** → FAIL.
- [ ] **Step 4: Implement behaviours 1–6.** Backend first if the DTO changes (`pytest --no-cov tests/test_practice_topics_marks_lost.py`, `ruff check`, `mypy lemely`).
- [ ] **Step 5: Run** the unit files → PASS; `npm run typecheck && npm run lint && npm run build && npm run check:copy` (the build must keep `CorrectPaper-*`/`Grading-*` chunks under 150KB — `assemblePages` stays a separate lazy chunk).
- [ ] **Step 6: Ledger:** `teacher-tools-quizbuilder-structure-divergence`, `teacher-tools-quiz-length-slider-vs-input`, `content-practice-source-filter-dead-in-ui`, `content-classified-practice-mental-model`, `teacher-flow-no-camera-capture-on-upload` → `done C3`.
- [ ] **Step 7: Commits** (three): `feat(web): QuizBuilder settings-so-far rail and quiz-length slider (C3)`, `feat(web): practice source control and per-topic marks-lost stat (C3)`, `feat(web): camera capture as a third upload source on Grading (C3)`.

---

### Task 9 (C3d): Top-grade caption, review-queue badge (+ backend `total`), review queue strip

**Files:**
- Backend: `lemely/web/schemas_teacher.py` (or wherever `ReviewQueueListDTO` lives — re-grep) gains `total: int`; `lemely/web/routers/teacher.py` review list handler fills it from the existing count helper (`_count_review_items` or the repo's count — re-grep `review_repo.py`), respecting the same filters as the page; `tests/test_teacher_review_total.py`
- Create: `web/src/lib/hooks/useReviewQueueCount.ts` (`useReviewQueueCount`), `web/src/lib/gradeSummary.ts` (pure `topGradeCount`), `web/src/lib/queuePosition.ts` (pure `queuePosition`)
- Modify: `web/src/lib/teacherTypes.ts:689` (`ReviewQueueList.total: number`), `web/src/portals/teacher/index.tsx:470` (Review nav item `badge`) and `:594-610` (BottomNav Review tab `badge`; delete the "no badge" comment), `web/src/portals/teacher/screens/ClassAnalytics.tsx:102-145` (`GradeDistributionPanel` subtitle), `web/src/portals/teacher/screens/ReviewItem.tsx:354-365` (`QueueStrip`)
- Test: `web/tests/unit/gradeSummary.test.ts`, `web/tests/unit/queuePosition.test.ts` (pure), `web/tests/unit/reviewBadge.test.ts` (source text: both nav sites pass `badge`; `useReviewQueueCount.ts` uses `limit: 1` and the shared query key prefix so the queue page and the badge dedupe)

**Interfaces:**
- Produces (backend): `GET /teacher/review` response gains `total` (count of items matching the request's filters, ignoring `limit`/`cursor`). Additive; existing clients ignore it.
- Produces (web): `useReviewQueueCount(): number | null` — `useReviewQueue({ limit: 1 })` with `select: (d) => d.total`, `staleTime: 60_000`; returns `null` while loading/erroring so the badge simply does not render. `topGradeCount(buckets: readonly { grade: string; count: number }[]): number` — sum of counts whose `gradeBand(grade) === "top"` (`gradeBand` from `grade-badge.tsx`). `queuePosition(ids: readonly string[], currentId: string): { index: number; total: number; prevId: string | null; nextId: string | null } | null` (null when `currentId` is not in `ids`).
- Consumed by: Task 14 (dark capture of Review shows the badge).

**Skills:** `ui-refactor`, `ux-heuristics`, `rest-api-design`; reviewer adds `security-auditor` (the count must be tenant-scoped exactly like the list — same repo query, same `teacher_id`).

**Behaviours:**
1. `GradeDistributionPanel`'s subtitle reads "N students on A* or A · Students by their latest paper grade" (N from `topGradeCount`; omitted when 0 → the existing subtitle alone).
2. Sidebar "Review" and the bottom "Review" tab show the queue count as `badge` when > 0; both read one deduped query; the count refreshes when the queue page's own mutations invalidate the shared key prefix.
3. `ReviewItem` shows a compact strip under the page header: "Item 3 of 12" with Prev/Next `Link`s (`viewTransition`, same filter querystring — `ReviewItem.tsx:30-40`'s route model kept); the strip reuses `queueQuery` (no new fetch); when the item is not in the current filtered queue the strip renders nothing (the existing "next" logic already handles that case — reuse its ids).
4. Backend: `total` equals `len(items)` when the queue fits one page; unit test proves it respects `class_id`/`reason`/`min_age_hours` filters and tenant scope.

- [ ] **Step 1: Re-grep** `ReviewQueueListDTO`, count helper in `review_repo.py`/`routers/teacher.py`, `queueIds`/"next" logic in `ReviewItem.tsx:354-380`, `gradeBand` export, `NavShellItem.badge` (`nav-shells.tsx:51-52`).
- [ ] **Step 2: Failing tests.** Backend `tests/test_teacher_review_total.py` (list with 3 items → `total == 3`; filter to 1 → `total == 1`; other teacher → `total == 0`). Web pure tests: `topGradeCount` on a fixture with A*, A, B, U; `queuePosition` first/middle/last/absent. Source-text test as in Files.
- [ ] **Step 3: Run** `pytest --no-cov tests/test_teacher_review_total.py` and the three vitest files → FAIL.
- [ ] **Step 4: Implement behaviours 1–4**, backend first (`ruff check`, `mypy lemely`, `pytest --no-cov tests/test_teacher_review_total.py` → PASS).
- [ ] **Step 5: Run** the vitest files → PASS; `npm run typecheck && npm run lint && npm run build && npm run check:copy`.
- [ ] **Step 6: Ledger:** `teacher-analytics-no-headline-top-grade-count`, `teacher-flow-no-nav-badge-counts`, `teacher-flow-no-queue-rail-during-review` → `done C3`.
- [ ] **Step 7: Commits** (three): `feat(api): total on GET /teacher/review (C3)`, `feat(web): review-queue count badge on teacher sidebar and bottom tab (C3)`, `feat(web): top-grade caption on the grade distribution, prev/next queue strip on ReviewItem (C3)`.

---

### Task 10 (C3e): Recorded decisions, canvas notes, marketing card padding, §13 knob range

**Files:**
- Create: `docs/design-canvas-notes.md` — one section per superseded canvas fact: device limit (canvas said a count that diverges from `PRODUCT.md:71` "Maximum 3 concurrent devices"; product wins), subject colour mapping (DESIGN.md §3.8 is authoritative; the canvas mapping is listed and marked superseded), Instrument Serif (rejected; §4 names the four faces), "Academic Warmth" colour system (superseded by §3's OKLCH ladder), hero grade on the student home (not built: Overview reports per-subject predicted grades; a single hero grade would be a cross-subject aggregate the product does not compute — see `student-home-no-hero-grade`)
- Modify: `DESIGN.md` — new `## 16. Recorded decisions (audit remediation)` listing the same five with one line each and a pointer to the notes file; §13 "Card padding" row: `space-5 … space-10` → `space-6 … space-8` (the range the product actually uses: §12's 24px default and the marketing `p-8`); §12 "Cards" gains "Marketing cards turn the knob to `space-8`".
- Modify: `web/src/portals/marketing/DataHandling.tsx:79` (`p-6` → `p-8`) and every `<Card` / `.lm-card` under `web/src/portals/marketing/` (re-grep; `Landing.tsx` was rebuilt on develop and may have none — record the real list)
- Test: `web/tests/unit/marketingCardPadding.test.ts` (source text: no `<Card className="p-6"` under `web/src/portals/marketing`), `web/tests/unit/designDocs.test.ts` (source text: `DESIGN.md` contains `## 16. Recorded decisions` and each of the five ids; `docs/design-canvas-notes.md` exists and names the five)

**Skills:** `technical-writer`, `writing-guidelines`.

**Behaviours:**
1. The five "decision" ledger rows point at a written, findable decision; nothing in the product changes for four of them.
2. Marketing cards use the `space-8` knob setting; the §13 table range matches reality.

- [ ] **Step 1: Re-grep** `<Card|lm-card` under `web/src/portals/marketing`, `PRODUCT.md` device limit line, DESIGN.md §13 table.
- [ ] **Step 2: Failing tests** as in Files.
- [ ] **Step 3: Run** `npx vitest run tests/unit/marketingCardPadding.test.ts tests/unit/designDocs.test.ts` → FAIL.
- [ ] **Step 4: Implement behaviours 1–2.**
- [ ] **Step 5: Run** → PASS; `npm run typecheck && npm run lint && npm run build && npm run check:copy` (the copy gate scans docs? re-grep `check_copy.mjs` globs; if it does, the new docs must be dash-clean).
- [ ] **Step 6: Ledger:** `trust-ops-device-limit-count-divergence`, `brand-subject-color-mapping-mismatch`, `x-type-instrument-serif-rejected`, `brand-color-system-superseded`, `student-home-no-hero-grade`, `x-density-card-padding-knob-underused` → `done C3`.
- [ ] **Step 7: Commits** (two): `docs(design): recorded decisions §16 and design-canvas-notes for superseded canvas facts (C3)`, `feat(web): marketing cards on the space-8 padding knob, §13 range corrected (C3)`.

---

### Task 11 (C4): Print, perf floor, reduced-motion unit half, copy gate in CI, §14 gate list

**Files:**
- Modify: `web/src/index.css:1013-1021` (`@media print` grows: `[data-print="hide"] { display: none !important }`; `main { padding: 0; max-width: none }`; `.lm-print-avoid-break { break-inside: avoid; page-break-inside: avoid }`; link underlines on; `--paper` forced white via `:root { --paper: #fff; --paper-raised: #fff; --paper-sunk: #fff }` inside the print block — the one place a literal is allowed, and the test pins that it is inside `@media print`)
- Modify: shell chrome gets `data-print="hide"`: every portal `<aside>` (the four `index.tsx` sidebars), `Header` components, `BottomNav`/`BottomActionBar` roots (`nav-shells.tsx`, `bottom-action-bar.tsx`), `NavDrawer`, `Toast` viewport, `SkipLink`, `InstallBanner`, `UpdateToast`, `OfflineBanner`, the Review/PaperResult tab strips
- Modify: `web/src/components/ui/question-row.tsx` (root gains `lm-print-avoid-break`)
- Modify: `web/scripts/audit.mjs` (route/state schema gains `media?: "print"`; the capture step calls `page.emulateMedia({ media: state.media ?? null })` before shooting and resets after; new state on the student result route: `{ state: "print-media", slug: "student-result-print", lighthouse: false, media: "print" }`)
- Modify: `scripts/check_ui_gates.py:100-120,170-180` (`PERF_GATED_TEACHER_SLUGS = ("teacher-class-analytics", "teacher-review")`; `is_perf_gated_route(route)` = student subtree OR slug in that tuple; the summary line names both groups); `tests/test_check_ui_gates.py` (re-grep; extend or create)
- Modify: `web/src/lib/celebration.ts:203-208` (`prefersReducedMotion(matchMedia: MatchMediaLike | undefined = globalThis.window?.matchMedia)`; `type MatchMediaLike = (query: string) => { matches: boolean }`; behaviour identical for callers)
- Modify: `.github/workflows/ci.yml` (web job: `- name: Copy gate` / `run: npm run check:copy` after Lint)
- Modify: `DESIGN.md` §14 gate list: new rule 9 "Logical properties only (P3.4): `inline-start/end`, `ms-/me-/ps-/pe-`, `text-start/end`; never `left/right`, `ml-/mr-`, `text-left/right`. `scripts/adapt_audit.mjs` and the responsive gate read `dir="rtl"`."
- Test: `web/tests/unit/printStyles.test.ts` (source text: the print block contains the four rules; every portal `index.tsx` and `nav-shells.tsx` contain `data-print="hide"`; `question-row.tsx` contains `lm-print-avoid-break`; the only `#fff` in `index.css` is inside `@media print`), `web/tests/unit/reducedMotionDecision.test.ts` (pure: `prefersReducedMotion(() => ({ matches: true })) === true`, `(() => ({ matches: false })) === false`, `(undefined) === true`; source text: `celebration.tsx`'s `useCountUp` and `Flourish` both call `prefersReducedMotion(`), `web/tests/unit/auditPrintState.test.ts` (source text: `audit.mjs` contains `emulateMedia` and `student-result-print`), `web/tests/unit/ciCopyGate.test.ts` (source text: `ci.yml` contains `npm run check:copy`)

**Interfaces:**
- Produces: `data-print="hide"` contract (any chrome that must not print sets it); `.lm-print-avoid-break`; `audit.mjs` state `media`; `check_ui_gates.is_perf_gated_route`; `prefersReducedMotion(matchMedia?)`.
- Consumed by: Task 6 (question rows already carry the class by the time the filter lands), Task 13 (`shell-init.js` must not set `data-print`), Task 14 (`audit.mjs` gains `colorScheme` next to `media`).

**Skills:** `playwright-screenshot-inspector`, `vitest-testing-patterns`, `github-actions-pipeline-builder`, `technical-writer`.

**Behaviours:**
1. Printing any portal screen prints the main content only: no sidebar, header, bottom nav, drawer, toasts, banners; paper white; texture already hidden.
2. PaperResult prints one question per block, never split across pages.
3. `npm run audit` produces `student-result-print` under print media; `check_ui_gates.py` fails when ClassAnalytics or Review scores below the performance floor; the summary line says "performance >= 80 on N student route(s) + 2 teacher route(s)".
4. `prefersReducedMotion` is unit-tested with an injected query; `useCountUp` and `Flourish` keep calling the zero-arg form.
5. CI runs the copy gate; DESIGN.md §14 lists the logical-property rule.

- [ ] **Step 1: Re-grep** the chrome roots listed in Files, the capture loop in `audit.mjs` (where `page.setViewportSize`/screenshot happen), `is_student_route` in `check_ui_gates.py`, `tests/test_check_ui_gates.py` existence.
- [ ] **Step 2: Failing tests** as in Files (+ `pytest --no-cov tests/test_check_ui_gates.py` cases: a teacher-review route at 79 fails, at 80 passes; a teacher-grading route at 50 is not gated).
- [ ] **Step 3: Run** the four vitest files + the pytest file → FAIL.
- [ ] **Step 4: Implement behaviours 1–5.**
- [ ] **Step 5: Run** → PASS; `npm run typecheck && npm run lint && npm run build && npm run check:copy`; `ruff check scripts/check_ui_gates.py`; `npx playwright test e2e/reduced-motion.spec.ts` if the backend is up.
- [ ] **Step 6: Ledger:** `x-completeness-print-only-one-screen`, `x-copy-friendly-tone-em-dash` → `done C4` (the only two `C4` rows). Two rows owned by earlier phases gain evidence only, status unchanged: `x-completeness-perf-floor-student-only` (row 192, `done A8`, whose evidence says "primary C4 (full extension to ClassAnalytics+Review) remains open") — append "C4: `check_ui_gates.py` gates `teacher-class-analytics` + `teacher-review`, `tests/test_check_ui_gates.py`"; `x-motion-reduced-motion-e2e-narrow-scope` (row 231, `done 7b2f1101`, "unit half stays with C4") — append "unit half: `tests/unit/reducedMotionDecision.test.ts`".
- [ ] **Step 7: Commits** (three): `feat(web): global print stylesheet hides portal chrome, PaperResult rows avoid page breaks, print-media capture (C4)`, `ci(web): copy gate in CI, Lighthouse perf floor extended to ClassAnalytics and Review (C4)`, `test(web): injectable reduced-motion decision, DESIGN.md §14 logical-property rule (C4)`.

---

### Task 12 (C5a): Dark token ladder, AA measurement, DESIGN.md §3 dark table

**Files:**
- Modify: `web/src/index.css:49-175` (after the light `:root` block: `:root[data-theme="dark"] { … }` redefining every token the light block defines: `--paper*` (4), `--ink*` (4), `--rule*` (3), `--accent*` (5, `--accent-on` stays `#ffffff` only if it still measures ≥4.5:1 on the dark `--accent`; else it becomes the dark `--paper`), the 12 pastel fill/ink pairs, the 4 semantic pairs (`--ok/-wash`, `--warn/-wash`, `--err/-wash`, `--info/-wash`), `--focus-ring`, `--grade-*` (they alias semantic/pastel tokens — unchanged, verify), `--mark-*` (aliases — unchanged). Nothing else: `--bg`/`--surface`/`--t1` etc. (`:497-527`) alias the primary tokens and follow automatically; `@theme inline` (`:231`, `:529`) maps utilities to `var(--token)` and follows automatically. Also `color-scheme: dark` on the dark root (native form controls, scrollbars).
- Modify: `tests/test_design_tokens.py` (parse both blocks: the existing `:root {` and the new `:root[data-theme="dark"] {`; every existing parametrised contrast test runs against both ladders; new test: the dark ladder declares exactly the token set the light one does, minus aliases; new test: `--ink-faint` (dark) ≥4.5:1 on every dark surface including the dark washes, and the binding surface is named)
- Modify: `web/tests/unit/design-tokens.test.ts` (the `--info` hue-collision test runs on both ladders; new: both ladders declare the same token names)
- Modify: `DESIGN.md` §3 intro (`:70-73`: "Light mode only ships now" → both ship; dark is a token swap under `data-theme`), §3.2 item 8 (whatever it says about dark — re-grep — updated to "shipped in Phase C"), new §3.10 "Dark ladder" table: token, dark OKLCH, ≈hex, measured ratio on its dark surface, for every redefined token

**Interfaces:**
- Produces: the dark ladder. Starting values (measured by the tests; nudge L until every test passes, keep hue and chroma unless a pair cannot clear AA): paper `0.20 / 0.24 / 0.17 / inverse 0.92`; ink `0.93 / 0.78 / 0.72 / inverse 0.25`; rule `0.30 / 0.36 / 0.26`; accent `0.72 (chroma 0.13)`, hover `0.78`, wash `0.28 (chroma 0.05)`, ink `0.80`; pastel fills L `0.30` chroma as light, pastel inks L `0.85`; semantic text L `0.78–0.82`, washes L `0.27–0.29`; focus ring `0.72`; `--accent-on` measured. Every value ends up in the §3.10 table exactly as shipped.
- Consumed by: Task 13 (`shell-init.js` sets `data-theme`; `preMountShell.ts` reads this block), Task 14 (consumers, captures).

**Skills:** `dark-mode-design-expert`, `color-contrast-auditor`, `design-system`, `typography-expert` (weight/size adjustments if dark text needs them — record any as a rule, not a per-site tweak).

**Behaviours:**
1. Setting `data-theme="dark"` on `<html>` re-themes the whole app through tokens alone: no component changes in this task.
2. Every text/surface pairing the light ladder guarantees is guaranteed in dark by the same tests (`test_design_tokens.py` runs each claim twice).
3. The `--ok/--warn/--err` lightness ladder is monotonic in dark too (the greyscale-survival property, §3.6) — in dark it ascends where light descends; the test asserts strict ordering in either direction and names it.
4. DESIGN.md §3.10 is the measured record; §3's intro no longer says dark is unshipped.

- [ ] **Step 1: Re-grep** every `--` declaration in the light `:root` (`:49-175`), `oklch_to_srgb` and block parsing in `test_design_tokens.py:19-60,319-340`, `brandTokens.ts:109` (its `:root` parser must not choke on a second root block — read it; Task 13 extends it).
- [ ] **Step 2: Failing tests.** Extend `test_design_tokens.py` and `design-tokens.test.ts` as in Files; they fail because the dark block does not exist.
- [ ] **Step 3: Run** `pytest --no-cov tests/test_design_tokens.py` and `npx vitest run tests/unit/design-tokens.test.ts` → FAIL.
- [ ] **Step 4: Implement behaviours 1–4**, iterating token values until the measurements pass; DESIGN.md table last, transcribed from the shipped CSS (the existing "transcribed token matches the CSS" test covers the light table; extend it to §3.10).
- [ ] **Step 5: Run** → PASS; `npm run typecheck && npm run lint && npm run build` (record `index-*.css` gzip before/after in the commit body).
- [ ] **Step 6: Ledger:** `x-tokens-dark-theme-deferred`, `x-dark-retrofit-token-surface` → `done C5`. `x-dark-deliberately-deferred`, `x-a11y-dark-theme-exploration-correctly-unshipped` stay `pending` until Task 14 (they close on the shipped toggle + captures).
- [ ] **Step 7: Commit** `feat(theme): dark token ladder under data-theme, AA-measured, DESIGN.md §3.10 (C5)`.

---

### Task 13 (C5b): Theme preference, toggle, flash-free pre-mount, `theme-color` swap, e2e

**Files:**
- Create: `web/src/lib/theme/theme.ts` (pure: `ThemePreference`, `ResolvedTheme`, `THEME_STORAGE_KEY`, `resolveTheme`, `readThemePreference`, `isThemePreference`), `web/src/lib/theme/applyTheme.ts` (`applyTheme`, `themeColorFor`), `web/src/lib/theme/useTheme.ts` (`useTheme`), `web/e2e/theme.spec.ts`
- Modify: `web/public/shell-init.js` (before the `data-shell` block: read `localStorage["lemely.theme"]`, resolve with `matchMedia("(prefers-color-scheme: dark)")`, set `document.documentElement.dataset.theme` and the `theme-color` meta content from its `data-theme-light`/`data-theme-dark` attributes — plain ES5, wrapped in `try/catch` because `localStorage` throws in some contexts)
- Modify: `web/vite/themeColor.ts` (emits `content="%LIGHT%" data-theme-light="%LIGHT%" data-theme-dark="%DARK%"`; `%LEMELY_THEME_COLOR_DARK%` resolved from the dark `--paper`), `web/vite/brandTokens.ts:109` (parser gains `readTokenBlock(css, selector)`; `tokenHex(name, theme = "light")`), `web/vite/preMountShell.ts` (a second set of placeholders `%LEMELY_COLOR_DARK_*%` for the same seven colours, emitted as a `[data-theme="dark"] #root { … }` override inside the inline `<style>`; `fillPreMountShell` fills both; the leftover-placeholder check at `:269` covers the new prefix), `web/index.html:45,134-160` (the two attributes on the meta; the dark override block in the shell style)
- Modify: `web/src/main.tsx` (mount `useTheme`'s effect once at the root — a `ThemeSync` component beside `TimezoneSync`/`BadgeSync`, re-grep `web/src/components/timezone-sync.tsx` for the pattern), `web/src/portals/settings/ProfileSettings.tsx:65-120` (new "Appearance" fieldset after the timezone select: three `Radio`s System / Light / Dark bound to `useTheme()`), `web/src/lib/auth/storage.ts` `endSession()` (does **not** clear the theme key — it is a device preference, not session data; record in a comment)
- Test: `web/tests/unit/theme.test.ts` (pure: `resolveTheme("system", true) === "dark"`, `("system", false) === "light"`, `("light", true) === "light"`, `("dark", false) === "dark"`; `readThemePreference` on `null`/garbage/valid; `isThemePreference`), `web/tests/unit/themeInit.test.ts` (source text: `shell-init.js` contains `lemely.theme`, `prefers-color-scheme: dark`, `dataset.theme`, `data-theme-dark`, and a `try {`; `index.html` meta has both attributes; `index.css` contains no `prefers-color-scheme` media query — the attribute is the single switch; `ProfileSettings.tsx` contains `Appearance`; `endSession` does not reference `THEME_STORAGE_KEY`), `web/tests/unit/preMountShell.test.ts` (extend: dark placeholders resolved, no leftover), `web/tests/unit/themeColor.test.ts` (new or extend: both placeholders resolved to distinct hexes)

**Interfaces:**
- Produces: `type ThemePreference = "system" | "light" | "dark"`; `type ResolvedTheme = "light" | "dark"`; `THEME_STORAGE_KEY = "lemely.theme"`; `resolveTheme(pref: ThemePreference, systemPrefersDark: boolean): ResolvedTheme`; `readThemePreference(raw: string | null): ThemePreference` (`"system"` for anything invalid); `isThemePreference(x: unknown): x is ThemePreference`. `applyTheme(root: HTMLElement, meta: HTMLMetaElement | null, theme: ResolvedTheme): void` — sets `root.dataset.theme` and `meta.content = meta.dataset[theme === "dark" ? "themeDark" : "themeLight"]`. `themeColorFor(meta, theme)` pure helper for the test. `useTheme(): { preference: ThemePreference; resolved: ResolvedTheme; setPreference: (p: ThemePreference) => void }` — reads storage once, subscribes to the `matchMedia` change event while `preference === "system"`, writes storage on change, calls `applyTheme` in a layout effect. `shell-init.js` implements the same `resolveTheme` table inline (no imports possible); `themeInit.test.ts` pins the three-way table in both files by regex.
- Consumed by: Task 14 (`nivoTheme` re-resolves on `data-theme` change; captures set `colorScheme`).

**Skills:** `dark-mode-design-expert`, `pwa-expert` (installed-app `theme-color` behaviour, `color-scheme` meta), `playwright-e2e-tester`.

**Behaviours:**
1. First paint is already in the resolved theme: `shell-init.js` sets `data-theme` before the shell markup parses; the pre-mount skeleton uses the dark colours in dark; no light flash on reload in dark (e2e asserts `document.documentElement.dataset.theme === "dark"` at `domcontentloaded` with `colorScheme: "dark"` emulated and no stored preference).
2. Profile settings → Appearance: System / Light / Dark. Choosing persists to `localStorage["lemely.theme"]`, applies immediately (no reload), survives reload and sign-out, and "System" follows the OS live.
3. `<meta name="theme-color">` content equals the dark `--paper` hex in dark and the light one in light, at first paint and after toggling.
4. `index.css` has exactly one dark block and no `prefers-color-scheme` query — the attribute is the single switch (deviation from the spec's two selectors; reason: one ladder, no drift, and the pre-mount shell/meta need the attribute anyway).

- [ ] **Step 1: Re-grep** `shell-init.js` whole, `themeColor.ts`/`preMountShell.ts` placeholder lists, `tokenHex` in `brandTokens.ts`, `Radio` API (`radio.tsx`), `TimezoneSync` mount in `main.tsx`, `endSession` in `lib/auth/storage.ts`, `e2e/native-feel.helpers.ts` (login helper for the e2e).
- [ ] **Step 2: Failing tests** as in Files; `theme.spec.ts`: (a) no-preference + `colorScheme: "dark"` → `data-theme="dark"` at `domcontentloaded` and meta content equals the dark hex; (b) log in, Profile → Appearance → Light → reload → `data-theme="light"` under dark emulation; (c) choose System → live switch when `emulateMedia({ colorScheme: "light" })` flips; (d) Nivo chart text fill on ClassAnalytics equals the resolved `--ink-muted` (this case is added in Task 14 — leave a `test.fixme` **only** as a named placeholder that Task 14 removes; Task 15 asserts no `fixme`/`skip` survives).
- [ ] **Step 3: Run** the vitest files → FAIL.
- [ ] **Step 4: Implement behaviours 1–4**, `shell-init.js` and the vite plugins first (they are what the no-flash test needs), then `lib/theme`, then the settings UI.
- [ ] **Step 5: Run** the vitest files → PASS; `npm run typecheck && npm run lint && npm run build && npm run check:copy`; `node scripts/check-native-invariants.mjs` (the CSP check must still pass — nothing inline); `npx playwright test e2e/theme.spec.ts` if the backend is up, else "deferred to CI" with the reason.
- [ ] **Step 6: Ledger:** `x-dark-deliberately-deferred` → `done C5` (the toggle ships). `x-a11y-dark-theme-exploration-correctly-unshipped` stays until Task 14's captures.
- [ ] **Step 7: Commits** (three): `feat(theme): theme preference, flash-free init in shell-init.js, theme-color swap, dark pre-mount shell (C5)`, `feat(web): Appearance setting System/Light/Dark on Profile (C5)`, `test(e2e): theme spec — no flash, persistence, system follow (C5)`.

---

### Task 14 (C5c): Token-driven consumers, dark captures, DESIGN.md close

**Files:**
- Modify: `web/src/lib/nivoTheme.ts:243-290` (`useNivoTheme` re-runs `resolveChartTokens()` when `data-theme` changes: a `MutationObserver` on `document.documentElement` for `attributes: ["data-theme"]`, disconnected on unmount), `web/src/components/ui/chart-frame.tsx` (nothing if it only composes — verify), `web/src/components/ui/skeleton.tsx` (already `bg-paper-sunk` — verify, no change), `web/src/components/ui/celebration.tsx:147-160` (confetti already `bg-pastel-*` — verify), `web/src/components/ui/brand-mark.tsx` (paints via `var(--accent)`/`var(--ink)` — verify), `web/src/portals/marketing/marketing.css` (`.band` uses `--paper-inverse`/`--ink-inverse` — in dark these invert to a light band; keep, it is the one permitted inverse surface), any file found by `rg -n "#[0-9a-fA-F]{6}|oklch\(|rgb\(" web/src --type-add 'tsx:*.tsx' -t tsx -t ts -g '!index.css'` (expect: `--accent-on` only lives in `index.css`; fix any literal found by lifting it to a token)
- Modify: `web/scripts/audit.mjs` (state schema gains `colorScheme?: "dark"`, applied via `page.emulateMedia({ colorScheme })` beside Task 11's `media`; five dark states: `student-overview-dark`, `student-result-dark`, `teacher-review-dark`, `teacher-class-analytics-dark`, `login-dark`, each `lighthouse: false`, reusing the light state's `ready`), `web/e2e/screenshots.spec.ts:10-17` (comment: dark is captured by `audit.mjs`; the corpus stays light), `web/e2e/theme.spec.ts` (replace the `fixme` with the chart-fill assertion)
- Modify: `DESIGN.md:70-73` (already updated in Task 12 — verify), §11 "Chart theme" (one line: tokens re-resolve on theme change), §12 "Skeletons" (one line: token-driven, both themes), §16 (Task 10's section) gains "Dark mode: shipped as a token swap; the exploration artboards' bespoke dark palette was not adopted — see §3.10")
- Test: `web/tests/unit/darkConsumers.test.ts` (source text: `nivoTheme.ts` contains `MutationObserver` and `data-theme`; no literal colour outside `index.css` and the print block; `audit.mjs` contains the five dark slugs and `colorScheme`; `theme.spec.ts` contains no `fixme`)

**Interfaces:**
- Consumes: Task 13's `data-theme` attribute and `theme.spec.ts`.
- Produces: the five dark captures in `reports/.scratch/screens/` (CI artefact), `audit.mjs` `colorScheme` state option.

**Skills:** `dark-mode-design-expert`, `playwright-screenshot-inspector`, `technical-writer`.

**Behaviours:**
1. Charts re-theme live when the preference changes (no reload); skeletons, confetti, the brand mark and every component paint from tokens in both themes; no literal colour exists in a component.
2. `npm run audit` captures the five named screens in dark; a reviewer can open `student-result-dark.png` and see the red-pen register, the filter tabs and the ring in dark.
3. `theme.spec.ts` proves the chart text fill equals the resolved dark `--ink-muted`.
4. DESIGN.md §11/§12/§16 record the dark behaviour.

- [ ] **Step 1: Re-grep** the literal-colour sweep command above, `useNivoTheme`'s resolution effect, the audit state loop from Task 11, `theme.spec.ts`'s `fixme`.
- [ ] **Step 2: Failing test** `darkConsumers.test.ts` as in Files.
- [ ] **Step 3: Run** → FAIL.
- [ ] **Step 4: Implement behaviours 1–4.**
- [ ] **Step 5: Run** → PASS; `npm run typecheck && npm run lint && npm run build && npm run check:copy`; `npx playwright test e2e/theme.spec.ts` and `npm run audit` (five dark slugs present in `route-failures.json` = none) if the backend is up, else "deferred to CI".
- [ ] **Step 6: Ledger:** `x-a11y-dark-theme-exploration-correctly-unshipped` → `done C5`. Confirm all four C5 rows are `done`.
- [ ] **Step 7: Commits** (two): `feat(theme): charts re-resolve tokens on theme change, literal-colour sweep (C5)`, `test(web): dark captures for Overview, PaperResult, Review, ClassAnalytics, Login; DESIGN.md dark notes (C5)`.

---

### Task 15: Phase close — review, deslop, verification, PR

- [ ] **Step 1: Opus review of the whole branch diff** (`code-reviewer`, skills `code-review-checklist`, `design-accessibility-auditor`; `security-auditor` for Task 9's backend): `git diff develop...HEAD`. Fix critical/high in follow-up commits per packet scope. The reviewer's brief includes the four Phase B lessons from Global Constraints verbatim.
- [ ] **Step 2: `ai-slop-cleaner` pass** on the diff (comments that restate code, dead flags, placeholder copy, any `fixme`/`skip`, leftover arbitrary values the migrations were meant to remove: `rg -n "\[[0-9]+px\]" web/src/portals/teacher`).
- [ ] **Step 3: Verifier** (`verifier`, opus): re-run every Step 5 command above; `node scripts/check-native-invariants.mjs`; `npm run build` (150KB budget; record `index-*.css` delta from Task 0's baseline); `npm run check:copy`; `pytest --no-cov tests/test_design_tokens.py tests/test_check_ui_gates.py tests/test_teacher_review_total.py`; `ruff check . && mypy lemely`; confirm the ledger has no `pending` row with `phase = C`; every `done C<n>` → `done <short sha>` of the commit that landed it; recount the ledger's summary tables (`done` should read 161 = 125 + 36; `pending` 25 = phase D); confirm `hallmarkStamp.test.ts` covers every new kit file; confirm no `test.fixme`/`test.skip`/`.only` anywhere under `web/e2e` and `web/tests`.
- [ ] **Step 4: `merge-readiness` skill report**; `superpowers:finishing-a-development-branch`.
- [ ] **Step 5: Push and open PR** into `develop` (ask the user before pushing — CLAUDE.md "Do not push unless asked"):
```bash
git push -u origin feat/ui-kit-and-dark-mode
gh pr create --base develop --title "feat: UI kit primitives, table/forms migration, screen fixes, dark mode (audit remediation phase C)" --body-file /tmp/claude-1000/-home-sico-Code-Lemely/bfaf7342-f8db-4c8d-b308-bab0d30a0bac/scratchpad/pr-c.md
```
PR body: packet list C1–C5 with ledger row counts (C1 8, C2 2, C3 20, C4 2, C5 4 = 36; plus the two evidence-only appends to rows 192 and 231), the real counts that superseded the spec's (7 lockups, 39 fields, 9 tables + 1 grid), the deviations (single `data-theme` switch instead of two selectors; `shell-init.js` instead of an inline script; `ReviewQueueList.total` as the one backend change; ClassDetail has no table), the dark ladder's worst-case measured ratio, `index-*.css` gzip before/after, the manual device checklist (dark first paint on an installed PWA on iOS and Android, `theme-color` bar colour in dark, print preview of PaperResult, camera source on Grading on a phone, red-pen register legibility on an OLED phone at low brightness), and the session URL `https://claude.ai/code/session_01CxbrmXri2Fm1p2KFgjL3rr` as the last line.
- [ ] **Step 6: Hand off** — user merges; Phase D plan is written against merged `develop`.

---

## Self-review (done while writing)

- **Spec coverage:** every Phase C packet in the design spec maps to Tasks 1–14; all 36 `phase = C` ledger ids appear in exactly one task's Step 6: C1 (8) — Task 1: `x-brandlockup-duplicated-5x`, `x-sectionhead-no-equivalent`; Task 2: `x-motifs-subjectglyph-tile-missing`, `brand-subject-glyph-vs-subject-tag`, `x-progressring-inline-duplication-risk`, `x-motifs-progress-ring-not-systematized`, `x-motion-progress-ring-no-production-equivalent`, `x-density-operate-row-rhythm-matches-but-uncodified`. C2 (2) — Task 4: `x-completeness-teacher-tables-bypass-table-primitive`; Task 5: `x-completeness-forms-dimension-unaudited`. C3 (20) — Task 6: `paper-no-question-filter-tabs`, `paper-red-pen-register-missing`, `student-home-streak-hidden-on-phone`; Task 7: `onboarding-plan-rows-no-icon-coding-no-live-type`, `onboarding-14day-framing-vs-perpetual-week`, `onboarding-session-length-chips-vs-weekly-hours-slider`; Task 8: `teacher-tools-quizbuilder-structure-divergence`, `teacher-tools-quiz-length-slider-vs-input`, `content-practice-source-filter-dead-in-ui`, `content-classified-practice-mental-model`, `teacher-flow-no-camera-capture-on-upload`; Task 9: `teacher-analytics-no-headline-top-grade-count`, `teacher-flow-no-nav-badge-counts`, `teacher-flow-no-queue-rail-during-review`; Task 10: `trust-ops-device-limit-count-divergence`, `brand-subject-color-mapping-mismatch`, `x-type-instrument-serif-rejected`, `brand-color-system-superseded`, `student-home-no-hero-grade`, `x-density-card-padding-knob-underused`. C4 (2) — Task 11: `x-completeness-print-only-one-screen`, `x-copy-friendly-tone-em-dash`. C5 (4) — Task 12: `x-tokens-dark-theme-deferred`, `x-dark-retrofit-token-surface`; Task 13: `x-dark-deliberately-deferred`; Task 14: `x-a11y-dark-theme-exploration-correctly-unshipped`. Count 8 + 2 + 20 + 2 + 4 = 36, matching `rg -c '\| C \| C[0-9] \|'` on the ledger (verified 2026-09-14: C1 8, C2 2, C3 20, C4 2, C5 4). Two spec items under C4 have ledger rows owned by earlier phases and get evidence appended only: `x-completeness-perf-floor-student-only` (row 192, phase A, `done A8`) and `x-motion-reduced-motion-e2e-narrow-scope` (row 231, phase B, `done 7b2f1101`); both rows' own evidence text names C4 as the remaining owner. Every id above exists in the ledger; none is assigned twice.
- **Deviations from the spec, each with the reason in the task:** 7 lockup sites not 5 (Task 0/1); 39 raw fields not 29, checkbox/radio/file/hidden allowlisted (Task 5); 9 tables + 1 CSS-grid table in 6 files, ClassDetail has none (Tasks 3–4); practice `source` already exists server-side, only the control is added (Task 8); `total` added to the review list DTO because the badge needs a count the API does not return (Task 9); Landing.tsx was rebuilt on develop — its card padding is applied where cards exist, recorded (Task 10); the reduced-motion unit half is an injected-query pure test, not a `matchMedia` mock (Task 11, D3.20); one `:root[data-theme="dark"]` block plus `shell-init.js` resolving the system preference, instead of the spec's second `@media` selector (Task 13); theme init in `shell-init.js`, not an inline script (CSP); dark captures in `audit.mjs` rather than `screenshots.spec.ts` (that suite covers student screens only and says so at `:16`) (Task 14); `light-dark()` CSS not used (browser floor).
- **Placeholders:** none — each step names files, values, tests and commands. Code bodies intentionally absent (memory `delegate-by-model`): implementers author code, opus reviews. The single `test.fixme` in Task 13 is a named hand-off removed by Task 14 and asserted gone by Task 15.
- **Type consistency:** `BrandLockup`/`SectionHead` (Task 1) are what Tasks 7–9 consume; `TableDensity`/`CELL_PADDING`/`density` (Task 2) are what Tasks 3–4 pass; `ProgressTone` is imported from `progress-bar.tsx` by `progress-ring.tsx`; `subjectTone`/`BadgeTone` (existing) feed `subjectGlyphFor`; `QuestionFilter`/`filterQuestions`/`markState` (Task 6) share `lib/questionFilter.ts`; `daysUntil`/`formatCountdown` keep their signatures in `lib/countdown.ts`; `ReviewQueueList.total` (Task 9 DTO + type) matches `useReviewQueueCount`'s `select`; `data-print="hide"` (Task 11) is the attribute `shell-init.js` must not set (Task 13); `ThemePreference`/`ResolvedTheme`/`resolveTheme`/`THEME_STORAGE_KEY` (Task 13) are pinned against `shell-init.js` by `themeInit.test.ts`; `audit.mjs` state options `media` (Task 11) and `colorScheme` (Task 14) sit side by side.
- **Deferred by design:** `light-dark()`; a backend-persisted theme preference (device preference only); dark variants for every screen (five named ones ship; the rest are token-driven and covered by the AA tests); virtualised tables.
