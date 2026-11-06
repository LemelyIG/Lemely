# Portal Shell Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One shared, portal-neutral shell in `web/src/components/shell/` (sidebar, floating top bar, drawer, bottom tabs, notifications panel, account panel, settings dialog by URL), styled as design A, used by both the student and the teacher portal.

**Architecture:** The teacher top-bar pieces on `develop` (`NotificationsMenu`, `ProfileMenu`, `ProfileAvatar`, `TopBarSheets`) move into `components/shell/` and take their portal facts as props. New `ShellTopBar`, `ShellSidebar` (+ `ShellNavList`, `ShellTree`) and `PortalShell` own the frame. The teacher portal adopts them one layer at a time (top bar, sidebar, layout), each gated by before/after screenshots; then the student portal is wired in one step against the design A preview, and student settings become the URL-driven `SettingsModal` the teacher already uses. A Playwright + pixelmatch drift gate (`web/scripts/home-drift.mjs`, scenes as a data list) is the acceptance step of every UI task.

**Tech Stack:** React 19, react-router-dom 7, TanStack Query 5, Radix (`radix-ui`), Tailwind v4 (`@theme` tokens in `web/src/index.css`), Phosphor icons, Vitest 4 (Node environment, no jsdom), Playwright 1.62, pixelmatch + pngjs (new dev deps).

## Global Constraints

- Contract: `docs/superpowers/specs/2026-11-06-portal-shell-design.md`. Companion: `docs/superpowers/specs/2026-11-06-student-home-overview-design.md` (shares the drift script; that plan runs after this one).
- Approach B: ONE shared shell for student and teacher. Teacher components move (not copy) into `web/src/components/shell/`; nothing stays duplicated.
- Teacher also moves to design A. Teacher drift = before (merged `develop`) / after screenshots; every difference must be a design A shell change and is logged with its reason. Page content below the shell must not change.
- Settings: a dialog opened by URL (`/<portal>/settings/:tab`), the page underneath stays mounted; closing returns to that page; a fresh load opens over the portal home. Reuse `web/src/portals/settings` sections.
- Phones: bottom tabs stay for both portals (approved, logged drift).
- Bell and avatar: panels over the page, as in design A.
- Styling: Tailwind v4 with the existing `@theme` tokens in `web/src/index.css`. No ported stylesheet. (This plan adds three layout tokens, Task 3, because design A's breakpoints and sidebar width have no token yet.)
- Fidelity: drift gate is acceptance for every UI task. 0 differing pixels, or up to 15% only with a written justification per difference in the spec's drift log. Over 15% always fails. Read the diff image, fix drift, re-run.
- All motion stops under `prefers-reduced-motion`. Light and dark themes match the design.
- Accessibility: skip link; one labelled `nav` landmark for the sidebar; panels keyboard-reachable with visible focus and focus returned to the trigger; touch targets at least 44px on coarse pointers; 375px top bar keeps a readable title.
- UI copy: no em dashes (existing copy tests enforce this).
- Git: signed commits only, `git commit -S -- <explicit paths>`; conventional messages with scopes (`feat(web):`, `refactor(web):`, `test(web):`, `chore(web):`, `docs(web):`). Never `git add -A`. Do not push. Never bare `git stash`.
- Before every commit: `/home/sico/Code/Lemely/.venv/bin/pre-commit run --files <changed files>` and fix failures in files you touched. mypy/pyright currently fail repo-wide on unresolved imports from the shared venv: report those, do not chase them in untouched Python.
- Never run the full test suite (no `make test`, no bare `pytest`, no bare `npx vitest run`). Run only named test files: `cd web && npx vitest run tests/unit/<file>.test.ts …`. (Vitest's `include` is `tests/unit/**/*.test.ts`.)
- Never put secrets in files.
- Vitest runs in Node with no DOM and no Testing Library (decision D3.20 in `web/vitest.config.ts`). Logic is unit-tested there (pure functions, `renderToStaticMarkup` + `MemoryRouter`, source scans, the existing pattern in `tests/unit/teacherTopBarSheets.test.ts`). Browser behaviour (focus trap, Escape, focus return, keyboard on the subject tree, settings by URL) is tested by the Playwright behaviour runner this plan adds (`web/scripts/shell-behaviour.mjs`), which needs no backend.
- Working directory for all commands: `/home/sico/Code/Lemely/.claude/worktrees/student-home-variants` (repo root) or its `web/` folder as stated.

### Existing tests that must keep passing (exact names on `develop`)

Navigation and shell: `web/tests/unit/navigation.test.ts`, `web/tests/unit/navShells.test.ts`, `web/tests/unit/navigationModel.test.ts`, `web/tests/unit/navigationDirection.test.ts`, `web/tests/unit/settingsTabs.test.ts`, `web/tests/unit/teacherTopBarSheets.test.ts`, `web/tests/unit/backgroundLocation.test.ts`, `web/tests/unit/overlayExit.test.ts`, `web/tests/unit/notFoundFallback.test.ts`, `web/tests/unit/preMountShell.test.ts`, `web/tests/unit/navRowIconGuard.test.ts`, `web/tests/unit/notifications.test.ts`, `web/tests/unit/teacherRedirect.test.ts`.

Tests that pin the portal layout files (update only where the shell moved): `web/tests/unit/offlineBanner.test.ts`, `web/tests/unit/outletBoundary.test.ts`, `web/tests/unit/routeSkeleton.test.ts`, `web/tests/unit/screenEntrance.test.ts`, `web/tests/unit/brandLockup.test.ts`, `web/tests/unit/subjectGlyph.test.ts`, `web/tests/unit/streakChip.test.ts`, `web/tests/unit/prefetchWiring.test.ts`, `web/tests/unit/reviewBadge.test.ts`, `web/tests/unit/recentlyDeletedWiring.test.ts`, `web/tests/unit/capabilityWiring.test.ts`.

Source-walking gates (every new `.tsx` must pass them): `web/tests/unit/a11yRules.test.ts`, `web/tests/unit/contrastRules.test.ts`, `web/tests/unit/elevationScale.test.ts`, `web/tests/unit/adaptRules.test.ts`, `web/tests/unit/motionDefaults.test.ts`, `web/tests/unit/utilityExistence.test.ts`, `web/tests/unit/rtlSafety.test.ts`, `web/tests/unit/design-tokens.test.ts`, `web/tests/unit/darkConsumers.test.ts`, `web/tests/unit/hoverTransition.test.ts`, `web/tests/unit/checkNativeInvariants.test.ts`, `web/tests/unit/nativeMechanics.test.ts`.

**Shell sweep command** (used at the end of Tasks 3 to 9; it is a named list, not the full suite):

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/student-home-variants/web && npx vitest run \
  tests/unit/navigation.test.ts tests/unit/navShells.test.ts tests/unit/navigationModel.test.ts \
  tests/unit/navigationDirection.test.ts tests/unit/settingsTabs.test.ts tests/unit/teacherTopBarSheets.test.ts \
  tests/unit/backgroundLocation.test.ts tests/unit/overlayExit.test.ts tests/unit/notFoundFallback.test.ts \
  tests/unit/preMountShell.test.ts tests/unit/navRowIconGuard.test.ts tests/unit/notifications.test.ts \
  tests/unit/teacherRedirect.test.ts tests/unit/offlineBanner.test.ts tests/unit/outletBoundary.test.ts \
  tests/unit/routeSkeleton.test.ts tests/unit/screenEntrance.test.ts tests/unit/brandLockup.test.ts \
  tests/unit/subjectGlyph.test.ts tests/unit/streakChip.test.ts tests/unit/prefetchWiring.test.ts \
  tests/unit/reviewBadge.test.ts tests/unit/recentlyDeletedWiring.test.ts tests/unit/capabilityWiring.test.ts \
  tests/unit/a11yRules.test.ts tests/unit/contrastRules.test.ts tests/unit/elevationScale.test.ts \
  tests/unit/adaptRules.test.ts tests/unit/motionDefaults.test.ts tests/unit/utilityExistence.test.ts \
  tests/unit/rtlSafety.test.ts tests/unit/design-tokens.test.ts tests/unit/darkConsumers.test.ts \
  tests/unit/hoverTransition.test.ts tests/unit/checkNativeInvariants.test.ts tests/unit/nativeMechanics.test.ts \
  tests/unit/shellModel.test.ts tests/unit/shellPanels.test.ts tests/unit/shellTree.test.ts tests/unit/studentShell.test.ts
```

Files in that list that do not exist yet (created by later tasks) are skipped by passing only the ones that exist; Vitest errors on a missing path, so drop not-yet-created files from the command in early tasks.

### Design A source rules (quoted once, referenced by the tasks)

Source: `web/dev-previews/student-home/variant-a.css` lines 726 to 1212 (`.as-*`, `.a-bottombar`), tokens in `web/dev-previews/student-home/tokens.css`. Token mapping to the app's `@theme`:

| Preview token | App Tailwind name |
|---|---|
| `--md-surface-lowest` / `-low` / `-container` / `-high` / `-highest` | `surface-container-lowest` / `-low` / `surface-container` / `-high` / `-highest` |
| `--text-body` | `on-surface` |
| `--text-muted` | `on-surface-variant` |
| `--border-subtle` (`--md-outline-subtle`) | `outline-variant` (same oklch values) |
| `--surface-card` (light: lowest, dark: high) | `surface-container-lowest`, `dark:surface-container-high` |
| `--surface-row`, `--surface-hover-tint` | hover only, not captured: `surface-container-low` / `surface-container` |
| `--radius-chip` 12, `--radius-inner` 18, `--radius-tile` 20, `--radius-card` 24, `--radius-pill`, `--as-radius-row` 10 | `rounded-chip`, `rounded-inner`, `rounded-tile`, `rounded-card`, `rounded-pill`, `rounded-row` |
| `--shadow-panel`, `--shadow-hover` | `shadow-[var(--shadow-panel)]`, `shadow-[var(--shadow-hover)]` |
| `--fs-label` 11, `--fs-body-sm` 14, `--fs-title` 21, `--fs-headline` 32 | `text-[11px]`, `text-body-sm`, `text-[21px]`, `text-display-md` |
| `--font-ui` (Schibsted), `--font-mono` | `font-sans` (default), `font-mono` |
| `--space-1..12` | Tailwind 4px scale (`1`=4px, `2`=8px, `3`=12px, `4`=16px, `6`=24px, `8`=32px, `12`=48px) |
| `@container ashell (max-width: 1000px)` | `max-shell-lg:` (new token, Task 3) |
| `@container ashell (max-width: 720px)` | `max-shell-sm:` (new token, Task 3) |
| `--as-side: 216px` | `w-shell-sidebar` (new token, Task 3) |

---

## File structure

Create:

| File | Responsibility |
|---|---|
| `web/scripts/home-drift.mjs` | Drift gate CLI: expands scenes × windows × themes, captures, diffs, writes report. |
| `web/scripts/drift/harness.mjs` | Servers (app `vite preview`, preview kit `vite --config vite.preview.config.ts`), page setup (session, theme, clock, mocks), capture and width matching. |
| `web/scripts/drift/compare.mjs` | pixelmatch diff, padding, verdict, justification lookup. |
| `web/scripts/drift/scenes.mjs` | The scene list both plans append to; window and theme matrices. |
| `web/scripts/drift/scenes-shell.mjs` | Shell scenes (teacher before/after; student vs preview; settings). |
| `web/scripts/drift/mocks.mjs` | API mocks for shell scenes (teacher notifications; student shell data). |
| `web/scripts/drift/justifications.json` | Machine-readable drift log (scene key → difference, justification, approved). |
| `web/scripts/shell-behaviour.mjs` | Playwright behaviour + axe runner over `drift/checks-shell.mjs`. |
| `web/scripts/drift/checks-shell.mjs` | Behaviour checks list (focus return, Escape, focus trap, tree keys, settings URL). |
| `web/src/components/shell/shellStyles.ts` | Shared class strings mapped from design A rules. |
| `web/src/components/shell/shellModel.ts` | Pure shell logic: trigger label, panel time label, settings tab keys. |
| `web/src/components/shell/shellTree.ts` | Pure open-state logic for the expandable sidebar group. |
| `web/src/components/shell/icons.tsx` | Design A stroke icons (`ShellIcon`). |
| `web/src/components/shell/ShellAvatar.tsx` | Avatar circle, placeholder, `profileName` (moved from `ProfileAvatar.tsx`). |
| `web/src/components/shell/NotificationsPanel.tsx` | Bell panel (moved from `NotificationsMenu.tsx`). |
| `web/src/components/shell/AccountPanel.tsx` | Avatar panel (moved from `ProfileMenu.tsx`). |
| `web/src/components/shell/TopBarSheets.tsx` | Generic `ActionSheet` (moved from `TopBarSheets.tsx`). |
| `web/src/components/shell/ShellTopBar.tsx` | Floating top bar. |
| `web/src/components/shell/ShellNavList.tsx` | Design A nav rows. |
| `web/src/components/shell/ShellTree.tsx` | Expandable rows (student subjects). |
| `web/src/components/shell/ShellSidebar.tsx` | Sidebar frame (rail and drawer variants) and `ShellUserBlock`. |
| `web/src/components/shell/PortalShell.tsx` | Layout: rail, drawer, top bar, main, banners, outlet, bottom tabs. |
| `web/src/portals/teacher/components/CreateSheet.tsx` | Teacher Create sheet on top of `ActionSheet`. |
| `web/src/portals/student/shell.tsx` | Student shell content passed to `PortalShell`. |
| `web/src/portals/student/GradeRing.tsx` | Subject grade ring. |
| `web/src/lib/studentInbox.ts` | Student notification destinations (moved out of the Notifications screen so the shell does not pull the screen into the entry chunk). |
| `web/tests/unit/shellModel.test.ts`, `shellPanels.test.ts`, `shellTree.test.ts`, `studentShell.test.ts` | Unit tests. |

Modify: `web/package.json` (dev deps), `web/src/index.css` (3 tokens + 1 utility), `web/src/components/ui/nav-shells.tsx` (export `NavShellLink`), `web/src/components/ui/nav-drawer.tsx` (`variant="shell"`), `web/src/portals/teacher/index.tsx`, `web/src/portals/student/index.tsx`, `web/src/portals/student/data.ts`, `web/src/portals/student/screens/Notifications.tsx`, `web/src/portals/student/screens/Profile.tsx`, `web/src/portals/settings/settingsTabs.ts`, `web/src/portals/settings/SettingsModal.tsx`, `web/e2e/theme.spec.ts`, the pinned tests listed above, the spec's drift log.

Delete (moved): `web/src/portals/teacher/components/NotificationsMenu.tsx`, `ProfileMenu.tsx`, `ProfileAvatar.tsx`, `TopBarSheets.tsx`.

---

### Task 0: Baseline: merge `origin/develop`, and settle open questions

**Files:** none created. Merge commit only.

**Interfaces:** Produces the merged tree every later task plans against (paths in this plan are `develop` paths).

- [ ] **Step 1: Check where you are**

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/student-home-variants
git status --short --branch
git log --oneline -3
```

Expected: branch `design/student-home-variants`; staged changes in `web/.gitignore`, `web/dev-previews/student-home-a.html`, `web/dev-previews/student-home/fixtures.ts`, `shell.css`, `variant-a.css`, `variant-a.js`; untracked `.impeccable/critique/`, `web/.impeccable/`. If the branch is different, stop and report.

- [ ] **Step 2: Ask the user how to keep the staged preview changes safe (blocking)**

The user declined a commit of these files once. Ask (AskUserQuestion if available) with these options, and do nothing until answered:
1. Signed WIP commit of exactly the staged files: `git commit -S -m "wip(web): design A preview polish" -- web/.gitignore web/dev-previews/student-home-a.html web/dev-previews/student-home/fixtures.ts web/dev-previews/student-home/shell.css web/dev-previews/student-home/variant-a.css web/dev-previews/student-home/variant-a.js`
2. Tagged stash: `git stash push -m "portal-shell-task0-preview-$(date +%s)" -- <same six paths>`, then record the SHA with `git stash list --format='%H %gs' | grep portal-shell-task0-preview`, restore later with `git stash apply <sha>` (never `pop`), then drop that entry by re-finding its `stash@{n}` by tag.
3. Leave them staged and merge on top (works only if the merge touches none of those six paths; check with Step 3 first).

Never run bare `git stash`. Leave the untracked `.impeccable/` folders alone.

- [ ] **Step 3: Ask the user the open spec questions in the same message (blocking)**

These come from reading `develop` against the spec. Record the answers in the spec under a new "Decisions (2026-11-06, plan)" list and use them in later tasks; the plan's defaults are in brackets.

1. Drawer breakpoint: the spec says "drawer below 1248px", design A's CSS switches at 1000px (`@container ashell (max-width: 1000px)`), and the drift gate's 1024px window shows a sidebar in the design. [Default: 1001px, the design.]
2. Student nav: design A lists Overview, Your classes, Standings, Friends. `develop` also has Tutors and Sessions, which have no home in the design (Profile, Parents, Recently deleted go to the account panel; Notifications and Announcements to the bell; Settings to the gear; Correct to Upload). [Default: add Tutors and Sessions as sidebar rows after Friends and log the drift.]
3. The spec removes `HeaderStreak` because "the streak now lives in the Overview hero", but that hero ships in the later Overview plan; until then `Overview.tsx` hides its own streak chip at `sm` and above, so the streak is not visible on tablets and desktops in between. [Default: accept the gap; Overview plan restores it.]
4. Design A's avatar is a circle; DESIGN.md §6 reserves circles for status dots (the kit `Avatar` is a squircle). [Default: circle, as the design.]
5. Design A also has its own 4-item phone bottom bar (`.a-bottombar`, at 720px and below). The spec's drift log says "design has none". The approved decision keeps today's 5-tab `BottomNav` below 820px. [Default: keep `BottomNav`; correct the drift-log wording.]

- [ ] **Step 4: Find the files this branch changed since the merge base**

```bash
git fetch origin
BASE=$(git merge-base HEAD origin/develop)
git diff --name-only "$BASE" HEAD > /tmp/claude-1000/-home-sico-Code-Lemely--claude-worktrees-student-home-variants/434df4f0-2e68-4bd1-be6c-be25b534c21c/scratchpad/branch-changed.txt
wc -l /tmp/claude-1000/-home-sico-Code-Lemely--claude-worktrees-student-home-variants/434df4f0-2e68-4bd1-be6c-be25b534c21c/scratchpad/branch-changed.txt
```

- [ ] **Step 5: Merge (signed)**

```bash
git merge --no-ff --no-commit origin/develop
git diff --name-only --diff-filter=U
```

For each conflicted path NOT in `branch-changed.txt`: `git checkout --theirs -- <path> && git add -- <path>`. For each conflicted path IN `branch-changed.txt` (expected: only `web/dev-previews/**`, `docs/superpowers/**`, `web/vite.preview.config.ts`, `web/.gitignore`): resolve by hand keeping both sides' intent, then `git add -- <path>`. Then:

```bash
git commit -S -m "chore(web): merge origin/develop into design/student-home-variants"
git log --show-signature -1 | head -5
```

Expected: a merge commit with two parents; the signature block present (local verification may show `N`, which is fine: signing works, verification is unset).

- [ ] **Step 6: Verify the merged tree builds and the baseline tests pass**

```bash
cd web && npm ci && npm run typecheck && npx vitest run tests/unit/navigation.test.ts tests/unit/navShells.test.ts tests/unit/settingsTabs.test.ts tests/unit/teacherTopBarSheets.test.ts
```

Expected: typecheck exits 0; 4 files pass. If the staged preview files were stashed, restore them now (`git stash apply <sha>`) and confirm `git status` shows them staged again.

---

### Task 1: Drift gate base (`web/scripts/home-drift.mjs`) and teacher "before" baseline

**Files:**
- Modify: `web/package.json` (devDependencies)
- Create: `web/scripts/home-drift.mjs`, `web/scripts/drift/harness.mjs`, `web/scripts/drift/compare.mjs`, `web/scripts/drift/scenes.mjs`, `web/scripts/drift/scenes-shell.mjs`, `web/scripts/drift/mocks.mjs`, `web/scripts/drift/justifications.json`

**Interfaces:**
- Consumes: `SURFACES`, `SESSION`, `PROFILE` from `web/scripts/capture_surface.mjs`; `startPreview`, `assertPortFree` from `web/scripts/serve_guard.mjs`.
- Produces (the Overview plan appends to these):
  - `SCENES: Scene[]` in `web/scripts/drift/scenes.mjs`, built as `[...SHELL_SCENES, ...HOME_SCENES]`; each area exports its own array from its own file.
  - `Scene` shape:
    ```js
    /** @typedef {{
     *   id: string,                       // unique, kebab-case; scene key is `${id}@${window}@${theme}`
     *   kind: "preview-vs-app" | "before-vs-after",
     *   capture: "frame" | "content",     // frame: viewport with page content hidden; content: the content box only
     *   rule?: "gate" | "log",            // default "gate"; "log" records the diff, needs a justification, no 15% cap
     *   windows?: number[],               // default WINDOWS
     *   themes?: ("light"|"dark")[],      // default THEMES
     *   app: { path?: string, surface?: string, state?: string, session?: object, profile?: object,
     *          mocks?: (page) => Promise<void>, act?: (page, ctx) => Promise<void> },
     *   preview?: { state: string, act?: (page, ctx) => Promise<void> },
     * }} Scene */
    ```
    `ctx` is `{ width: number, theme: "light"|"dark" }`.
  - `openApp(browser, opts)`, `openPreview(browser, opts)`, `capture(page, opts)`, `matchContentWidth(page, selector, target, height)` from `harness.mjs`; `diffPngs(a, b, diffPath)`, `verdict(result, justification, rule)`, `findJustification(key)` from `compare.mjs`.
  - CLI: `node scripts/home-drift.mjs [--scene <prefix>[,<prefix>]] [--windows 390,1440] [--themes light] [--record-baseline] [--selftest] [--list]`. Exit 0 only when every selected scene key passes.

- [ ] **Step 1: Add the two dev dependencies**

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/student-home-variants/web
npm install --save-dev pixelmatch@^7.1.0 pngjs@^7.0.0
git diff --stat package.json package-lock.json
```

Expected: both added under `devDependencies`. `pixelmatch` 7 is ESM with a default export.

- [ ] **Step 2: Write `web/scripts/drift/compare.mjs`**

```js
/*
 * Pixel comparison for the drift gate (home-drift.mjs).
 *
 * A "differing pixel" is what pixelmatch reports at threshold 0.1 (its YIQ
 * colour-distance default), with anti-aliased pixels excluded (its default).
 * That is the gate's definition of a pixel that differs; the spec's "0
 * differing pixels" means 0 under this definition.
 *
 * Two captures of different sizes are padded to the larger size with opaque
 * magenta, so every row or column one side lacks counts as differing.
 */
import fs from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"
import { PNG } from "pngjs"
import pixelmatch from "pixelmatch"

export const MAX_PCT = 15
const HERE = path.dirname(fileURLToPath(import.meta.url))
const JUSTIFICATIONS_PATH = path.join(HERE, "justifications.json")

function padTo(png, width, height) {
  if (png.width === width && png.height === height) return png
  const out = new PNG({ width, height })
  for (let i = 0; i < out.data.length; i += 4) {
    out.data[i] = 255
    out.data[i + 1] = 0
    out.data[i + 2] = 255
    out.data[i + 3] = 255
  }
  PNG.bitblt(png, out, 0, 0, png.width, png.height, 0, 0)
  return out
}

/** Diff two PNG buffers, write the diff image, return the counts. */
export function diffPngs(aBuffer, bBuffer, diffPath) {
  const a = PNG.sync.read(aBuffer)
  const b = PNG.sync.read(bBuffer)
  const width = Math.max(a.width, b.width)
  const height = Math.max(a.height, b.height)
  const pa = padTo(a, width, height)
  const pb = padTo(b, width, height)
  const out = new PNG({ width, height })
  const diff = pixelmatch(pa.data, pb.data, out.data, width, height, { threshold: 0.1 })
  fs.mkdirSync(path.dirname(diffPath), { recursive: true })
  fs.writeFileSync(diffPath, PNG.sync.write(out))
  const total = width * height
  return {
    diff,
    total,
    pct: total === 0 ? 0 : (diff / total) * 100,
    sizes: { a: [a.width, a.height], b: [b.width, b.height] },
  }
}

/** Most specific justification for a scene key `${id}@${window}@${theme}`:
 * exact key, then `${id}@${window}`, then `${id}@*@${theme}`, then `${id}`. */
export function findJustification(key, table = readJustifications()) {
  const [id, win, theme] = key.split("@")
  for (const candidate of [key, `${id}@${win}`, `${id}@*@${theme}`, id]) {
    if (table[candidate]) return { key: candidate, ...table[candidate] }
  }
  return null
}

export function readJustifications() {
  return JSON.parse(fs.readFileSync(JUSTIFICATIONS_PATH, "utf8"))
}

/**
 * "pass": 0 differing pixels.
 * "pass-justified": differs, has a written justification, and (rule "gate") is at most 15%.
 * "fail": anything else. A gate scene over 15% fails even when justified.
 */
export function verdict(result, justification, rule = "gate") {
  if (result.diff === 0) return "pass"
  const written = Boolean(justification && justification.justification && justification.justification.trim())
  if (rule === "gate" && result.pct > MAX_PCT) return "fail"
  return written ? "pass-justified" : "fail"
}
```

- [ ] **Step 3: Write `web/scripts/drift/harness.mjs`**

```js
/*
 * Page and server setup for the drift gate and the shell behaviour runner.
 *
 * App side: the production build served by `vite preview` (run `npm run build`
 * first), every `/api/**` call mocked, so no backend is needed. Preview side:
 * the design kit dev server (`vite --config vite.preview.config.ts`) serving
 * `student-home-a.html`. Both sides get the same viewport, theme, frozen clock
 * (2026-11-05 10:00, the preview fixtures' "now") and no animation.
 */
import { spawn } from "node:child_process"
import path from "node:path"
import { fileURLToPath } from "node:url"
import { SURFACES, SESSION, PROFILE } from "../capture_surface.mjs"
import { assertPortFree, startPreview } from "../serve_guard.mjs"

export const WEB_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..")
export const REPO_DIR = path.resolve(WEB_DIR, "..")
export const APP_PORT = 4321
export const APP_BASE = `http://127.0.0.1:${APP_PORT}`
export const KIT_PORT = 5180
export const KIT_BASE = `http://127.0.0.1:${KIT_PORT}`
export const NOW = new Date(2026, 10, 5, 10, 0)
export const SELECTORS = { app: "#main-content", preview: "#as-main" }

const STILL_CSS =
  "*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important}"
const PREVIEW_CSS = ".sh-toolbar{display:none!important}.sh-root{--as-top:0px!important}"

async function waitUntilUp(url, proc, label) {
  const deadline = Date.now() + 60_000
  for (;;) {
    if (proc.child.exitCode !== null) throw new Error(`${label} exited\n${proc.log()}`)
    try {
      if ((await fetch(url, { signal: AbortSignal.timeout(2000) })).ok) return
    } catch {
      /* not up yet */
    }
    if (Date.now() > deadline) throw new Error(`${label} never answered\n${proc.log()}`)
    await new Promise((r) => setTimeout(r, 300))
  }
}

export async function startServers({ needKit }) {
  await assertPortFree(APP_BASE, APP_PORT, "the drift gate")
  const app = startPreview(APP_PORT, WEB_DIR)
  await waitUntilUp(APP_BASE, app, "app preview")
  let kit = null
  if (needKit) {
    await assertPortFree(KIT_BASE, KIT_PORT, "the drift gate")
    const bin = path.join(WEB_DIR, "node_modules", ".bin", "vite")
    const child = spawn(
      bin,
      ["--config", "vite.preview.config.ts", "--port", String(KIT_PORT), "--strictPort", "--host", "127.0.0.1"],
      { cwd: WEB_DIR, stdio: ["ignore", "pipe", "pipe"] },
    )
    const lines = []
    child.stdout.on("data", (d) => lines.push(String(d)))
    child.stderr.on("data", (d) => lines.push(String(d)))
    kit = { child, log: () => lines.join(""), stop: () => child.kill("SIGTERM") }
    await waitUntilUp(`${KIT_BASE}/student-home-a.html`, kit, "preview kit")
  }
  return {
    stop() {
      app.stop()
      kit?.stop()
    },
  }
}

function json(route, body, status = 200) {
  return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) })
}

async function newContext(browser, { width, height, theme }) {
  return browser.newContext({
    viewport: { width, height },
    deviceScaleFactor: 1,
    reducedMotion: "reduce",
    colorScheme: theme,
  })
}

/** Open the real app at a route with mocked API and the scene's theme. */
export async function openApp(browser, { width, height, theme, app }) {
  const surface = app.surface ? SURFACES[app.surface] : null
  if (app.surface && !surface) throw new Error(`unknown capture surface ${app.surface}`)
  const session = { ...SESSION, ...(surface?.session ?? {}), ...(app.session ?? {}) }
  const profile = { ...PROFILE, ...(surface?.profile ?? {}), ...(app.profile ?? {}) }
  const context = await newContext(browser, { width, height, theme })
  await context.addInitScript(
    ([sess, chosenTheme]) => {
      window.localStorage.setItem("lemely.session", JSON.stringify(sess))
      window.localStorage.setItem("lemely.deviceId", "drift-device")
      window.localStorage.setItem("lemely.theme", chosenTheme)
    },
    [session, theme],
  )
  const page = await context.newPage()
  await page.clock.setFixedTime(NOW)
  // Registration order matters: Playwright tries the most recent route first.
  await page.route("**/api/**", (route) => json(route, {}))
  await page.route("**/api/me/profile", (route) => json(route, profile))
  if (surface) await surface.stub(page, surface.states[app.state ?? Object.keys(surface.states)[0]])
  if (app.mocks) await app.mocks(page)
  await page.goto(`${APP_BASE}${app.path ?? surface.route}`, { waitUntil: "networkidle" })
  await page.addStyleTag({ content: STILL_CSS })
  await page.evaluate(() => document.fonts.ready)
  if (app.act) await app.act(page, { width, theme })
  await page.waitForTimeout(150)
  return { context, page }
}

/** Open the design A preview in a state, with its toolbar removed. */
export async function openPreview(browser, { width, height, theme, preview }) {
  const context = await newContext(browser, { width, height, theme })
  const page = await context.newPage()
  await page.clock.setFixedTime(NOW)
  const query = new URLSearchParams({ state: preview.state, theme, motion: "reduce", width: "desktop" })
  await page.goto(`${KIT_BASE}/student-home-a.html?${query}`, { waitUntil: "networkidle" })
  await page.addStyleTag({ content: STILL_CSS + PREVIEW_CSS })
  await page.evaluate(() => document.fonts.ready)
  if (preview.act) await preview.act(page, { width, theme })
  await page.waitForTimeout(150)
  return { context, page }
}

/** The content box (padding excluded) of `selector`, in page coordinates. */
export async function contentBox(page, selector) {
  return page.$eval(selector, (el) => {
    const r = el.getBoundingClientRect()
    const s = getComputedStyle(el)
    const pl = parseFloat(s.paddingLeft)
    const pr = parseFloat(s.paddingRight)
    const pt = parseFloat(s.paddingTop)
    const pb = parseFloat(s.paddingBottom)
    return {
      x: Math.round(r.left + pl),
      y: Math.round(r.top + window.scrollY + pt),
      width: Math.round(r.width - pl - pr),
      height: Math.max(1, Math.round(el.scrollHeight - pt - pb)),
    }
  })
}

/** Resize the window until the content box is `target` px wide. */
export async function matchContentWidth(page, selector, target, height) {
  for (let i = 0; i < 8; i++) {
    const box = await contentBox(page, selector)
    const delta = target - box.width
    if (delta === 0) return true
    const vp = page.viewportSize()
    await page.setViewportSize({ width: vp.width + delta, height })
    await page.waitForTimeout(80)
  }
  return false
}

/**
 * frame: the viewport, with the page content hidden (layout kept), so only the
 * shell and any panel or dialog over it is compared.
 * content: the content box only; `neutral` paints its own background magenta on
 * both sides so a shell background change cannot leak into a content compare.
 */
export async function capture(page, { capture: mode, selector, neutral = false }) {
  if (mode === "frame") {
    await page.addStyleTag({ content: `${selector} > * { visibility: hidden !important; }` })
    return page.screenshot({ animations: "disabled", caret: "hide" })
  }
  if (neutral) await page.addStyleTag({ content: `${selector} { background: rgb(255 0 255) !important; }` })
  const clip = await contentBox(page, selector)
  return page.screenshot({ fullPage: true, clip, animations: "disabled", caret: "hide" })
}
```

- [ ] **Step 4: Write `web/scripts/drift/mocks.mjs` (teacher part; Task 6 appends the student part)**

```js
/*
 * API mocks for the shell scenes. Teacher scenes layer these on top of the
 * capture-surface registry's own stubs (`capture_surface.mjs`).
 */

function json(route, body) {
  return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) })
}

export const TEACHER_NOTIFICATIONS = {
  notifications: [
    {
      notificationId: "tn-1",
      type: "at_risk_alert",
      title: "Omar Said may need support in 0625",
      body: "Two papers below his target grade",
      payload: { studentId: "stu-1" },
      createdAt: "2026-11-05T09:12:00",
      readAt: null,
    },
    {
      notificationId: "tn-2",
      type: "announcement",
      title: "Mock exams start on 16 Nov",
      body: "Year 11, all subjects",
      payload: {},
      createdAt: "2026-11-04T18:00:00",
      readAt: "2026-11-04T19:00:00",
    },
  ],
}
export const TEACHER_COUNTS = { unread: 1, total: 2, unreadByType: { at_risk_alert: 1 } }

export async function teacherShellMocks(page) {
  await page.route("**/api/notifications", (route) => json(route, TEACHER_NOTIFICATIONS))
  await page.route("**/api/notifications/counts", (route) => json(route, TEACHER_COUNTS))
  await page.route("**/api/teacher/review?**", (route) => json(route, { items: [], total: 3 }))
}
```

- [ ] **Step 5: Write `web/scripts/drift/scenes-shell.mjs` (teacher scenes now; student scenes in Task 6, settings in Task 7)**

```js
import { teacherShellMocks } from "./mocks.mjs"

const teacher = (extra) => ({ surface: "teacher-overview", state: "populated", mocks: teacherShellMocks, ...extra })

async function openTeacherNav(page) {
  const more = page.getByRole("button", { name: "More", exact: true })
  if (await more.isVisible()) await more.click()
  else await page.getByRole("button", { name: /Open teacher navigation/ }).click()
  await page.getByRole("dialog").waitFor()
}
async function openBell(page) {
  await page.getByRole("button", { name: /^Notifications/ }).click()
  await page.getByRole("menu").waitFor()
}
async function openAccount(page) {
  await page.getByRole("button", { name: /^Your profile and account/ }).click()
  await page.getByRole("menu").waitFor()
}

const TEACHER_SETTINGS = [
  ["profile", ""],
  ["account", "/devices"],
  ["notifications", "/notifications"],
  ["appearance", "/appearance"],
  ["classes", "/classes"],
  ["install", "/install"],
]

/** Teacher: no design A preview exists, so each scene compares the merged
 * `develop` capture (recorded with --record-baseline in Task 1) to the current
 * one. Frame scenes are "log": the shell is meant to change; every difference
 * needs a justification naming the design A rule. Content scenes are "gate":
 * the page below the shell must not change. */
export const TEACHER_SCENES = [
  { id: "teacher-home-frame", kind: "before-vs-after", capture: "frame", rule: "log", app: teacher({}) },
  { id: "teacher-home-content", kind: "before-vs-after", capture: "content", app: teacher({}) },
  {
    id: "teacher-class-frame",
    kind: "before-vs-after",
    capture: "frame",
    rule: "log",
    app: { surface: "teacher-analytics", mocks: teacherShellMocks },
  },
  {
    id: "teacher-class-content",
    kind: "before-vs-after",
    capture: "content",
    app: { surface: "teacher-analytics", mocks: teacherShellMocks },
  },
  {
    id: "teacher-notifications-frame",
    kind: "before-vs-after",
    capture: "frame",
    rule: "log",
    app: teacher({ path: "/teacher/notifications" }),
  },
  {
    id: "teacher-notifications-content",
    kind: "before-vs-after",
    capture: "content",
    app: teacher({ path: "/teacher/notifications" }),
  },
  {
    id: "teacher-drawer",
    kind: "before-vs-after",
    capture: "frame",
    rule: "log",
    windows: [390, 768],
    app: teacher({ act: openTeacherNav }),
  },
  { id: "teacher-bell", kind: "before-vs-after", capture: "frame", rule: "log", app: teacher({ act: openBell }) },
  { id: "teacher-account", kind: "before-vs-after", capture: "frame", rule: "log", app: teacher({ act: openAccount }) },
  ...TEACHER_SETTINGS.map(([tab, suffix]) => ({
    id: `teacher-settings-${tab}`,
    kind: "before-vs-after",
    capture: "frame",
    rule: "log",
    app: teacher({ path: `/teacher/settings${suffix}` }),
  })),
]

export const SHELL_SCENES = [...TEACHER_SCENES]
```

- [ ] **Step 6: Write `web/scripts/drift/scenes.mjs` and `justifications.json`**

```js
/*
 * The drift gate's scene list. Each area keeps its scenes in its own file and
 * this list concatenates them: the shell plan owns scenes-shell.mjs, the
 * Overview plan adds scenes-home.mjs and appends HOME_SCENES below.
 */
import { SHELL_SCENES } from "./scenes-shell.mjs"

export const WINDOWS = [390, 768, 1024, 1440, 1920]
export const HEIGHT = { 390: 844, 768: 1024, 1024: 768, 1440: 900, 1920: 1080 }
export const THEMES = ["light", "dark"]

export const SCENES = [...SHELL_SCENES]

const ids = new Set()
for (const scene of SCENES) {
  if (ids.has(scene.id)) throw new Error(`duplicate drift scene id ${scene.id}`)
  ids.add(scene.id)
}
```

`web/scripts/drift/justifications.json`:

```json
{}
```

- [ ] **Step 7: Write `web/scripts/home-drift.mjs`**

```js
#!/usr/bin/env node
/*
 * Drift gate (docs/superpowers/specs/2026-11-06-portal-shell-design.md §4 and
 * 2026-11-06-student-home-overview-design.md §4).
 *
 *   node scripts/home-drift.mjs [--scene a,b] [--windows 390,1440] [--themes light]
 *                               [--record-baseline] [--selftest] [--list]
 *
 * Needs a fresh `npm run build` (the app side is `vite preview` of dist/).
 * Writes reports/.scratch/drift/<timestamp>/{<key>.a.png,<key>.b.png,<key>.diff.png,report.json,report.md}.
 * Baselines for before-vs-after scenes live in reports/.scratch/drift/baseline/.
 * Exit 0 only when every selected scene key passes (see compare.mjs verdict).
 */
import fs from "node:fs"
import path from "node:path"
import { chromium } from "@playwright/test"
import { HEIGHT, SCENES, THEMES, WINDOWS } from "./drift/scenes.mjs"
import {
  REPO_DIR,
  SELECTORS,
  capture,
  contentBox,
  matchContentWidth,
  openApp,
  openPreview,
  startServers,
} from "./drift/harness.mjs"
import { diffPngs, findJustification, verdict } from "./drift/compare.mjs"

function parseArgs(argv) {
  const out = { scene: [], windows: null, themes: null, recordBaseline: false, selftest: false, list: false }
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]
    if (a === "--scene") out.scene = argv[++i].split(",")
    else if (a === "--windows") out.windows = argv[++i].split(",").map(Number)
    else if (a === "--themes") out.themes = argv[++i].split(",")
    else if (a === "--record-baseline") out.recordBaseline = true
    else if (a === "--selftest") out.selftest = true
    else if (a === "--list") out.list = true
    else throw new Error(`unknown argument ${a}`)
  }
  return out
}

const args = parseArgs(process.argv.slice(2))
const DRIFT_DIR = path.join(REPO_DIR, "reports", ".scratch", "drift")
const BASELINE_DIR = path.join(DRIFT_DIR, "baseline")

function expand() {
  const keys = []
  for (const scene of SCENES) {
    if (args.scene.length && !args.scene.some((p) => scene.id.startsWith(p))) continue
    for (const width of args.windows ?? scene.windows ?? WINDOWS) {
      if (scene.windows && !scene.windows.includes(width)) continue
      for (const theme of args.themes ?? scene.themes ?? THEMES) {
        keys.push({ scene, width, theme, key: `${scene.id}@${width}@${theme}` })
      }
    }
  }
  return keys
}

async function shoot(browser, side, item, targetWidth) {
  const { scene, width, theme } = item
  const height = HEIGHT[width] ?? 900
  const opened =
    side === "preview"
      ? await openPreview(browser, { width, height, theme, preview: scene.preview })
      : await openApp(browser, { width, height, theme, app: scene.app })
  try {
    const selector = SELECTORS[side === "preview" ? "preview" : "app"]
    if (scene.capture === "content" && targetWidth !== undefined) {
      const ok = await matchContentWidth(opened.page, selector, targetWidth, height)
      if (!ok) throw new Error(`${item.key}: could not match content width ${targetWidth}`)
    }
    const width_ = scene.capture === "content" ? (await contentBox(opened.page, selector)).width : undefined
    const png = await capture(opened.page, {
      capture: scene.capture,
      selector,
      neutral: scene.kind === "before-vs-after",
    })
    return { png, contentWidth: width_ }
  } finally {
    await opened.context.close()
  }
}

async function runSelftest(browser) {
  // Proves the gate can go red: the same preview twice must be 0 px, and the
  // same preview with its title recoloured must fail.
  const item = {
    scene: { id: "selftest", kind: "preview-vs-app", capture: "frame", preview: { state: "populated" } },
    width: 1440,
    theme: "light",
    key: "selftest@1440@light",
  }
  const a = await shoot(browser, "preview", item)
  const b = await shoot(browser, "preview", item)
  const same = diffPngs(a.png, b.png, path.join(DRIFT_DIR, "selftest", "same.diff.png"))
  const perturbed = await shoot(browser, "preview", {
    ...item,
    scene: {
      ...item.scene,
      preview: {
        state: "populated",
        act: (page) => page.addStyleTag({ content: ".as-title{color:rgb(255 0 0)!important}" }),
      },
    },
  })
  const changed = diffPngs(a.png, perturbed.png, path.join(DRIFT_DIR, "selftest", "changed.diff.png"))
  console.log(`selftest same: ${same.diff} px; perturbed: ${changed.diff} px`)
  if (same.diff !== 0) throw new Error("selftest: identical captures differ, the capture is not deterministic")
  if (verdict(changed, null) !== "fail") throw new Error("selftest: a recoloured title did not fail the gate")
  console.log("selftest passed")
}

async function main() {
  const items = expand()
  if (args.list) {
    for (const i of items) console.log(i.key)
    return
  }
  const needKit = args.selftest || items.some((i) => i.scene.kind === "preview-vs-app")
  const servers = await startServers({ needKit })
  const browser = await chromium.launch()
  const runDir = path.join(DRIFT_DIR, new Date().toISOString().replace(/[:.]/g, "-"))
  fs.mkdirSync(runDir, { recursive: true })
  fs.mkdirSync(BASELINE_DIR, { recursive: true })
  const rows = []
  try {
    if (args.selftest) {
      await runSelftest(browser)
      return
    }
    for (const item of items) {
      const { scene, key } = item
      if (args.recordBaseline) {
        if (scene.kind !== "before-vs-after") continue
        const shot = await shoot(browser, "app", item)
        fs.writeFileSync(path.join(BASELINE_DIR, `${key}.png`), shot.png)
        fs.writeFileSync(
          path.join(BASELINE_DIR, `${key}.json`),
          JSON.stringify({ contentWidth: shot.contentWidth ?? null }),
        )
        console.log(`baseline ${key}`)
        continue
      }
      let a
      let b
      if (scene.kind === "preview-vs-app") {
        a = await shoot(browser, "preview", item)
        b = await shoot(browser, "app", item, a.contentWidth)
      } else {
        const basePng = path.join(BASELINE_DIR, `${key}.png`)
        if (!fs.existsSync(basePng)) throw new Error(`${key}: no baseline; run with --record-baseline on merged develop`)
        const meta = JSON.parse(fs.readFileSync(path.join(BASELINE_DIR, `${key}.json`), "utf8"))
        a = { png: fs.readFileSync(basePng) }
        b = await shoot(browser, "app", item, meta.contentWidth ?? undefined)
      }
      fs.writeFileSync(path.join(runDir, `${key}.a.png`), a.png)
      fs.writeFileSync(path.join(runDir, `${key}.b.png`), b.png)
      const result = diffPngs(a.png, b.png, path.join(runDir, `${key}.diff.png`))
      const justification = findJustification(key)
      const outcome = verdict(result, justification, scene.rule ?? "gate")
      rows.push({ key, ...result, outcome, justification })
      console.log(`${outcome.padEnd(14)} ${result.pct.toFixed(3).padStart(8)}%  ${key}`)
    }
  } finally {
    await browser.close()
    servers.stop()
  }
  if (args.recordBaseline || args.selftest) return
  fs.writeFileSync(path.join(runDir, "report.json"), JSON.stringify(rows, null, 2))
  const md = [
    "| Scene | Difference | % pixels | Justification | Approved |",
    "|---|---|---|---|---|",
    ...rows
      .filter((r) => r.diff > 0)
      .map(
        (r) =>
          `| ${r.key} | ${r.justification?.difference ?? "(none)"} | ${r.pct.toFixed(2)} | ${
            r.justification?.justification ?? "(missing)"
          } | ${r.justification?.approved ?? "no"} |`,
      ),
  ].join("\n")
  fs.writeFileSync(path.join(runDir, "report.md"), md + "\n")
  console.log(`report: ${path.relative(REPO_DIR, runDir)}`)
  const failed = rows.filter((r) => r.outcome === "fail")
  if (failed.length) {
    console.error(`${failed.length} scene key(s) failed`)
    process.exitCode = 1
  }
}

main().catch((error) => {
  console.error(error)
  process.exitCode = 1
})
```

`justifications.json` entries (written in later tasks) have this exact shape:

```json
{
  "teacher-home-frame": {
    "difference": "Sidebar 252px to 216px; page ground surface to surface-container; floating bar restyled",
    "justification": "Design A shell (.as-side, .as-app, .as-bar in variant-a.css)",
    "approved": "yes"
  }
}
```

- [ ] **Step 8: Prove the gate can go red (selftest)**

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/student-home-variants/web
npm run build
node scripts/home-drift.mjs --selftest
```

Expected output ends with `selftest same: 0 px; perturbed: <N> px` (N > 0) and `selftest passed`. If `same` is not 0, fix determinism (fonts, clock, animation) before going on; a gate that is red on identical input proves nothing.

- [ ] **Step 9: Record the teacher "before" baseline on the merged tree (no shell code yet)**

```bash
node scripts/home-drift.mjs --scene teacher- --record-baseline
ls ../reports/.scratch/drift/baseline | wc -l
node scripts/home-drift.mjs --scene teacher-
```

Expected: baseline count = 2 × (number of teacher scene keys) (`.png` + `.json`); `--list --scene teacher-` shows the keys. The second command (baseline vs the same tree) reports `pass` with 0.000% for every key. Any non-zero key means the capture is not deterministic for that scene: fix before going on. `reports/.scratch/` is gitignored; do not commit PNGs. Keep this baseline until Task 9.

- [ ] **Step 10: Commit**

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/student-home-variants
/home/sico/Code/Lemely/.venv/bin/pre-commit run --files web/package.json web/package-lock.json web/scripts/home-drift.mjs web/scripts/drift/harness.mjs web/scripts/drift/compare.mjs web/scripts/drift/scenes.mjs web/scripts/drift/scenes-shell.mjs web/scripts/drift/mocks.mjs web/scripts/drift/justifications.json
git commit -S -m "test(web): drift gate base with teacher before/after scenes" -- web/package.json web/package-lock.json web/scripts/home-drift.mjs web/scripts/drift/harness.mjs web/scripts/drift/compare.mjs web/scripts/drift/scenes.mjs web/scripts/drift/scenes-shell.mjs web/scripts/drift/mocks.mjs web/scripts/drift/justifications.json
```

---

### Task 2: Move the teacher panels into `components/shell/`, portal-neutral (pure move), and the behaviour runner

The look does not change in this task. The drift gate proves it: every teacher key stays at 0 px.

**Files:**
- Move: `web/src/portals/teacher/components/NotificationsMenu.tsx` → `web/src/components/shell/NotificationsPanel.tsx`
- Move: `web/src/portals/teacher/components/ProfileMenu.tsx` → `web/src/components/shell/AccountPanel.tsx`
- Move: `web/src/portals/teacher/components/ProfileAvatar.tsx` → `web/src/components/shell/ShellAvatar.tsx`
- Move: `web/src/portals/teacher/components/TopBarSheets.tsx` → `web/src/components/shell/TopBarSheets.tsx`
- Create: `web/src/portals/teacher/components/CreateSheet.tsx`
- Modify: `web/src/portals/teacher/index.tsx` (imports and the `TeacherTopBar` call sites only)
- Create: `web/tests/unit/shellPanels.test.ts`
- Create: `web/scripts/shell-behaviour.mjs`, `web/scripts/drift/checks-shell.mjs`
- Unchanged and still passing: `web/tests/unit/teacherTopBarSheets.test.ts` (it imports `topBarActions`, which stays in `portals/teacher/components/` because it is teacher data)

**Interfaces:**
- Produces:
  ```ts
  // web/src/components/shell/NotificationsPanel.tsx
  export interface NotificationsPanelProps {
    /** Badge text from the counts query (`unreadBadgeLabel`), null for none. */
    unread: string | null
    triggerClassName: string
    /** Where a row goes; null sends the reader to `inboxTo`. */
    destinationFor: (notification: Notification) => string | null
    /** The glyph for a row's notification type. */
    iconFor: (type: string) => ReactNode
    inboxTo: string
    footerLinks: readonly { to: string; label: string }[]
    emptyMessage: string
    errorHeading: string
    /** Rows shown; default 4. */
    previewLimit?: number
  }
  export function NotificationsPanel(props: NotificationsPanelProps): JSX.Element

  // web/src/components/shell/AccountPanel.tsx
  export interface AccountLink {
    id: string
    label: string
    icon: ReactNode
    /** An in-app route. Exactly one of `to` / `href`. */
    to?: string
    href?: string
    /** Carry the current page as the overlay background (settings links). */
    overlay?: boolean
    /** A second line under the label. */
    description?: string
  }
  export interface AccountPanelProps {
    links: readonly AccountLink[]
    /** The line under the email (teacher: role; student: qualification and subject count). */
    detail: string | null
    triggerClassName?: string
  }
  export function AccountPanel(props: AccountPanelProps): JSX.Element

  // web/src/components/shell/ShellAvatar.tsx (Task 2 keeps develop's exports; Task 3 adds ShellAvatar)
  export const PROFILE_AVATAR_BOX: string
  export function profileName(profile: Pick<Profile, "displayName" | "email">): string
  export function ShellAvatarPlaceholder(): JSX.Element   // renamed from ProfileAvatarPlaceholder

  // web/src/components/shell/TopBarSheets.tsx
  export const SHEET_FOCUS_RING: string                    // renamed from FOCUS_RING
  export function IconTile(props: { children: ReactNode }): JSX.Element
  export interface SheetAction { id: string; title: string; description: string; to: string; icon: ReactNode }
  export interface ActionSheetProps {
    triggerClassName: string
    triggerIcon: ReactNode
    triggerLabel: string
    eyebrow: string
    title: string
    actions: readonly SheetAction[]
  }
  export function ActionSheet(props: ActionSheetProps): JSX.Element

  // web/src/portals/teacher/components/CreateSheet.tsx
  export function CreateSheet(props: { triggerClassName: string }): JSX.Element

  // web/scripts/drift/checks-shell.mjs
  /** @typedef {{ id: string, width?: number, theme?: "light"|"dark", app: object, run: (page) => Promise<void>, axe?: boolean }} Check */
  export const SHELL_CHECKS: Check[]
  export function assertFocused(locator, label): Promise<void>
  export function assertHidden(locator, label): Promise<void>
  ```

- [ ] **Step 1: Write the failing unit test `web/tests/unit/shellPanels.test.ts`**

```ts
import { readFileSync, existsSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import { profileName } from "@/components/shell/ShellAvatar"
import { stripComments } from "./support/jsxSource"

/*
 * The teacher top-bar pieces moved into components/shell and became
 * portal-neutral: no file under components/shell may import a portal, and the
 * old teacher copies are gone (moved, not copied).
 */

const SRC = join(import.meta.dirname, "..", "..", "src")
const SHELL_FILES = ["NotificationsPanel.tsx", "AccountPanel.tsx", "ShellAvatar.tsx", "TopBarSheets.tsx"]

describe("components/shell is portal-neutral", () => {
  it.each(SHELL_FILES)("%s imports no portal module", (file) => {
    const source = stripComments(readFileSync(join(SRC, "components/shell", file), "utf8"))
    expect(source).not.toMatch(/from\s+"@\/portals\/(teacher|student)\//)
    expect(source).not.toMatch(/from\s+"\.\.\/\.\.\/portals\//)
  })

  it.each(["NotificationsMenu.tsx", "ProfileMenu.tsx", "ProfileAvatar.tsx", "TopBarSheets.tsx"])(
    "the teacher copy %s no longer exists",
    (file) => {
      expect(existsSync(join(SRC, "portals/teacher/components", file))).toBe(false)
    },
  )
})

describe("profileName", () => {
  it("uses the display name when set", () => {
    expect(profileName({ displayName: "Mariam", email: "m@x.io" })).toBe("Mariam")
  })
  it("falls back to the email's local part, never an invented name", () => {
    expect(profileName({ displayName: null, email: "mariam.hassan@student.lemely.app" })).toBe("mariam.hassan")
  })
})
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd web && npx vitest run tests/unit/shellPanels.test.ts`
Expected: FAIL, `Cannot find module '@/components/shell/ShellAvatar'`.

- [ ] **Step 3: Move the files with history**

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/student-home-variants/web/src
mkdir -p components/shell
git mv portals/teacher/components/NotificationsMenu.tsx components/shell/NotificationsPanel.tsx
git mv portals/teacher/components/ProfileMenu.tsx components/shell/AccountPanel.tsx
git mv portals/teacher/components/ProfileAvatar.tsx components/shell/ShellAvatar.tsx
git mv portals/teacher/components/TopBarSheets.tsx components/shell/TopBarSheets.tsx
```

- [ ] **Step 4: Make `ShellAvatar.tsx` neutral**

In `web/src/components/shell/ShellAvatar.tsx` rename `ProfileAvatarPlaceholder` to `ShellAvatarPlaceholder` (function name and its doc comment's mention of "the profile menu" becomes "the account panel"). Nothing else changes.

- [ ] **Step 5: Make `TopBarSheets.tsx` a generic `ActionSheet`**

Replace the whole file body below the imports with this (imports: `ReactNode` from react, `Link` from react-router-dom, `X` from Phosphor, the `Sheet*` parts from `@/components/ui/sheet`, `cn`):

```tsx
export const SHEET_FOCUS_RING =
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"

/** Light: the lowest container, like every panel. Dark: one step up so it lifts off the page. */
const SHEET_SURFACE =
  "gap-1.5 rounded-card border-0 bg-surface-container-lowest p-6 text-on-surface dark:bg-surface-container-high"

const ROW =
  "flex items-center gap-3 rounded-lg p-2.5 text-on-surface transition-colors duration-150 hover:bg-surface-container-low dark:hover:bg-surface-container-highest " +
  SHEET_FOCUS_RING

function CloseButton() {
  return (
    <SheetClose
      className={cn(
        "absolute end-4 top-4 flex h-9 w-9 items-center justify-center rounded-pill bg-surface-container-low text-on-surface-variant transition-colors hover:text-on-surface pointer-coarse:h-11 pointer-coarse:w-11 dark:bg-surface-container-highest",
        SHEET_FOCUS_RING,
      )}
    >
      <X size={16} aria-hidden="true" />
      <span className="sr-only">Close</span>
    </SheetClose>
  )
}

export function IconTile({ children }: { children: ReactNode }) {
  return (
    <span className="flex h-10 w-10 flex-none items-center justify-center rounded-md bg-primary-container text-primary">
      {children}
    </span>
  )
}

export interface SheetAction {
  id: string
  title: string
  description: string
  to: string
  icon: ReactNode
}

export interface ActionSheetProps {
  triggerClassName: string
  triggerIcon: ReactNode
  triggerLabel: string
  eyebrow: string
  title: string
  actions: readonly SheetAction[]
}

/**
 * A top-bar button and the sheet it opens: a list of starting points, each a
 * link to the screen that does the work. Radix Dialog underneath gives the
 * focus trap, Escape, scrim dismissal, the title as the accessible name and
 * focus back on the button on close.
 */
export function ActionSheet({ triggerClassName, triggerIcon, triggerLabel, eyebrow, title, actions }: ActionSheetProps) {
  return (
    <Sheet>
      <SheetTrigger className={triggerClassName}>
        {triggerIcon}
        <span className="hidden sm:inline">{triggerLabel}</span>
        <span className="sr-only sm:hidden">{triggerLabel}</span>
      </SheetTrigger>
      <SheetContent side="adaptive" showCloseButton={false} aria-describedby={undefined} className={SHEET_SURFACE}>
        <CloseButton />
        <p className="text-eyebrow text-on-surface-variant">{eyebrow}</p>
        <SheetTitle className="mb-2 text-display-md">{title}</SheetTitle>
        <ul className="flex flex-col gap-1">
          {actions.map((action) => (
            <li key={action.id}>
              <SheetClose asChild>
                <Link to={action.to} className={ROW}>
                  <IconTile>{action.icon}</IconTile>
                  <span className="min-w-0">
                    <span className="block text-label">{action.title}</span>
                    <span className="block text-body-sm text-on-surface-variant">{action.description}</span>
                  </span>
                </Link>
              </SheetClose>
            </li>
          ))}
        </ul>
      </SheetContent>
    </Sheet>
  )
}
```

- [ ] **Step 6: Create `web/src/portals/teacher/components/CreateSheet.tsx`**

```tsx
import { Books, Megaphone, Plus, Sparkle, UsersThree, type Icon } from "@phosphor-icons/react"
import { ActionSheet } from "@/components/shell/TopBarSheets"
import { CREATE_ACTIONS, type CreateActionIcon } from "./topBarActions"

const ACTION_ICON: Record<CreateActionIcon, Icon> = {
  scheme: Books,
  quiz: Sparkle,
  announcement: Megaphone,
  class: UsersThree,
}

/** The teacher top bar's Create button: four starting points (`CREATE_ACTIONS`). */
export function CreateSheet({ triggerClassName }: { triggerClassName: string }) {
  return (
    <ActionSheet
      triggerClassName={triggerClassName}
      triggerIcon={<Plus size={16} aria-hidden="true" />}
      triggerLabel="Create"
      eyebrow="Create"
      title="Start something"
      actions={CREATE_ACTIONS.map((action) => {
        const Glyph = ACTION_ICON[action.icon]
        return {
          id: action.id,
          title: action.title,
          description: action.description,
          to: action.to,
          icon: <Glyph size={20} aria-hidden="true" />,
        }
      })}
    />
  )
}
```

- [ ] **Step 7: Make `NotificationsPanel.tsx` take its portal facts as props**

In `web/src/components/shell/NotificationsPanel.tsx`:
- Remove the imports of `STAFF_INBOX_ERROR`, `TEACHER_INBOX_EMPTY`, `staffDestinationFor` (keep `showMarkAllRead` from `@/lib/staffInbox`), of `./topBarActions`, of `formatAge` from `@/portals/student/screens/Notifications` (the neutrality test forbids portal imports), and of `Megaphone`, `Warning`, `type Icon`. Import `SHEET_FOCUS_RING as FOCUS_RING` and `IconTile` from `./TopBarSheets`, and `formatAge` from `./shellModel`, a byte-for-byte copy you create now (Task 3 replaces it with `panelTimeLabel`):

Create `web/src/components/shell/shellModel.ts` with exactly this (Task 3 extends it):

```ts
/** Day-granularity age, identical to the student inbox's `formatAge`
 * (`portals/student/screens/Notifications.tsx`). Replaced by `panelTimeLabel`
 * in Task 3. */
export function formatAge(iso: string, now: Date = new Date()): string {
  const created = new Date(iso)
  if (Number.isNaN(created.getTime())) return ""
  const days = Math.floor((now.getTime() - created.getTime()) / 86_400_000)
  if (days <= 0) return "Today"
  if (days === 1) return "Yesterday"
  if (days < 7) return `${days} days ago`
  const weeks = Math.floor(days / 7)
  if (weeks === 1) return "1 week ago"
  if (weeks < 5) return `${weeks} weeks ago`
  return created.toLocaleDateString(undefined, { day: "numeric", month: "short" })
}
```

- Replace `TYPE_ICON` and the `Glyph` lookup with the `iconFor` prop; replace `staffDestinationFor("teacher", notification)` with `destinationFor(notification)`; `INBOX_TO` → `inboxTo`; `NOTIFICATION_PREVIEW_LIMIT` → `previewLimit`; the two hard-coded footer links → `footerLinks`; `TEACHER_INBOX_EMPTY.heading` / `.body` → one `<p className="text-label">{emptyMessage}</p>`; `STAFF_INBOX_ERROR.heading` → `errorHeading`. `Row` and `Panel` receive the props they need. The exported component becomes:

```tsx
export function NotificationsPanel({ unread, triggerClassName, ...panel }: NotificationsPanelProps) {
  return (
    <DropdownMenu.Root modal={false}>
      <DropdownMenu.Trigger
        aria-label={unread ? `Notifications, ${unread} unread` : "Notifications"}
        className={triggerClassName}
      >
        <Bell size={20} aria-hidden="true" />
        {unread ? (
          <span className="absolute -end-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-pill bg-primary px-1 text-data-sm text-on-primary">
            {unread}
          </span>
        ) : null}
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content align="end" sideOffset={8} collisionPadding={10} className={PANEL_SURFACE}>
          <Panel {...panel} previewLimit={panel.previewLimit ?? 4} />
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  )
}
```

The teacher's empty copy is now passed as one string, so the empty state renders `"Nothing yet. When a student you teach may need support, it will appear here."` in one `text-label` line instead of a heading plus body. That is the one visible change in this task; it shows only in an empty inbox, which no drift scene captures. Note it in the commit body.

- [ ] **Step 8: Make `AccountPanel.tsx` take its links and detail as props**

In `web/src/components/shell/AccountPanel.tsx`: rename the component `ProfileMenu` → `AccountPanel` with `AccountPanelProps`; imports from `./ShellAvatar` (`PROFILE_AVATAR_BOX`, `ShellAvatarPlaceholder`, `profileName`) and `./TopBarSheets` (`SHEET_FOCUS_RING as FOCUS_RING`, `IconTile`); remove `./topBarActions` and the `Gear`, `Lifebuoy`, `UserCircle` imports. Replace the role line with `{detail ? <p className="text-body-sm text-on-surface-variant">{detail}</p> : null}`. Replace the three hard-coded items with:

```tsx
{links.map((link) => (
  <DropdownMenu.Item key={link.id} asChild>
    {link.href ? (
      <a href={link.href} className={MENU_ITEM}>
        <IconTile>{link.icon}</IconTile>
        <LinkText link={link} />
      </a>
    ) : (
      <Link to={link.to ?? "/"} state={link.overlay ? overlayState : undefined} className={MENU_ITEM}>
        <IconTile>{link.icon}</IconTile>
        <LinkText link={link} />
      </Link>
    )}
  </DropdownMenu.Item>
))}
```

with, in the same file:

```tsx
function LinkText({ link }: { link: AccountLink }) {
  return link.description ? (
    <span className="min-w-0">
      <span className="block text-label">{link.label}</span>
      <span className="block text-body-sm text-on-surface-variant">{link.description}</span>
    </span>
  ) : (
    <span className="text-label">{link.label}</span>
  )
}
```

The Sign out item stays exactly as on `develop` (it awaits `logout()` before navigating to `/login`).

- [ ] **Step 9: Point the teacher portal at the moved components**

In `web/src/portals/teacher/index.tsx`:

```tsx
// replace the old imports
import { CreateSheet } from "./components/CreateSheet"
import { ShellAvatarPlaceholder } from "@/components/shell/ShellAvatar"
import { HELP_HREF, INBOX_TO, ANNOUNCEMENTS_TO, PROFILE_EDIT_TO, SETTINGS_TO, roleLabel } from "./components/topBarActions"
import { STAFF_INBOX_ERROR, TEACHER_INBOX_EMPTY, staffDestinationFor, unreadBadgeLabel } from "@/lib/staffInbox"
import { Lifebuoy, UserCircle } from "@phosphor-icons/react"   // add to the existing Phosphor import list
import type { AccountLink } from "@/components/shell/AccountPanel"
import type { NotificationsPanelProps } from "@/components/shell/NotificationsPanel"

const NotificationsPanel = lazy(() =>
  import("@/components/shell/NotificationsPanel").then((m) => ({ default: m.NotificationsPanel })),
)
const AccountPanel = lazy(() => import("@/components/shell/AccountPanel").then((m) => ({ default: m.AccountPanel })))

const TEACHER_TYPE_ICON: Record<string, Icon> = { at_risk_alert: Warning, announcement: Megaphone }

/** The teacher bell panel's portal facts. */
export const TEACHER_NOTIFICATIONS_PANEL: Omit<NotificationsPanelProps, "unread" | "triggerClassName"> = {
  destinationFor: (notification) => staffDestinationFor("teacher", notification),
  iconFor: (type) => {
    const Glyph = TEACHER_TYPE_ICON[type] ?? Bell
    return <Glyph size={20} aria-hidden="true" />
  },
  inboxTo: INBOX_TO,
  footerLinks: [
    { to: INBOX_TO, label: "All notifications" },
    { to: ANNOUNCEMENTS_TO, label: "Announcements" },
  ],
  emptyMessage: `${TEACHER_INBOX_EMPTY.heading}. ${TEACHER_INBOX_EMPTY.body}`,
  errorHeading: STAFF_INBOX_ERROR.heading,
}

/** The teacher account panel's links, in order. */
export const TEACHER_ACCOUNT_LINKS: readonly AccountLink[] = [
  { id: "profile", label: "Edit profile", to: PROFILE_EDIT_TO, overlay: true, icon: <UserCircle size={20} aria-hidden="true" /> },
  { id: "settings", label: "Settings", to: SETTINGS_TO, overlay: true, icon: <Gear size={20} aria-hidden="true" /> },
  {
    id: "help",
    label: "Help and feedback",
    description: "Email the Lemely team",
    href: HELP_HREF,
    icon: <Lifebuoy size={20} aria-hidden="true" />,
  },
]
```

and in `TeacherTopBar` replace the two lazy menus:

```tsx
<NotificationsPanel {...TEACHER_NOTIFICATIONS_PANEL} unread={unread} triggerClassName={TOP_BAR_ICON_BUTTON} />
…
<Suspense fallback={<ShellAvatarPlaceholder />}>
  <TeacherAccountPanel />
</Suspense>
```

with, near `UserBlock`:

```tsx
function TeacherAccountPanel() {
  const { data } = useProfile()
  return (
    <AccountPanel
      links={TEACHER_ACCOUNT_LINKS}
      detail={data ? roleLabel(data.role) : null}
      triggerClassName="cursor-pointer"
    />
  )
}
```

(the old `ProfileAvatarPlaceholder` import and the old `NotificationsMenu`/`ProfileMenu` lazy constants are deleted).

- [ ] **Step 10: Write the behaviour runner and the first checks**

`web/scripts/drift/checks-shell.mjs`:

```js
/*
 * Browser behaviour the Node-only unit runner cannot see (vitest.config.ts,
 * D3.20): focus return, Escape, focus trap, keyboard on the subject tree and
 * settings by URL. Each check opens the real app (mocked API, harness.mjs)
 * and throws on the first broken expectation. Later tasks append checks.
 */
import { teacherShellMocks } from "./mocks.mjs"

export async function assertFocused(locator, label) {
  const focused = await locator.evaluate((el) => el === document.activeElement)
  if (!focused) throw new Error(`${label}: expected focus on the element`)
}
export async function assertHidden(locator, label) {
  await locator.waitFor({ state: "hidden", timeout: 3000 }).catch(() => {
    throw new Error(`${label}: expected it to close`)
  })
}

const TEACHER_HOME = { surface: "teacher-overview", state: "populated", mocks: teacherShellMocks }

export const SHELL_CHECKS = [
  {
    id: "teacher-bell-escape-returns-focus",
    app: TEACHER_HOME,
    async run(page) {
      const bell = page.getByRole("button", { name: /^Notifications/ })
      await bell.click()
      await page.getByRole("menu").waitFor()
      await page.keyboard.press("Escape")
      await assertHidden(page.getByRole("menu"), "bell panel")
      await assertFocused(bell, "bell trigger")
    },
  },
  {
    id: "teacher-account-escape-returns-focus",
    app: TEACHER_HOME,
    async run(page) {
      const avatar = page.getByRole("button", { name: /^Your profile and account/ })
      await avatar.click()
      await page.getByRole("menu").waitFor()
      await page.keyboard.press("Escape")
      await assertHidden(page.getByRole("menu"), "account panel")
      await assertFocused(avatar, "avatar trigger")
    },
  },
  {
    id: "teacher-bell-keyboard-reachable",
    app: TEACHER_HOME,
    async run(page) {
      const bell = page.getByRole("button", { name: /^Notifications/ })
      await bell.focus()
      await page.keyboard.press("Enter")
      await page.getByRole("menu").waitFor()
      const first = page.getByRole("menuitem").first()
      await first.waitFor()
      await page.keyboard.press("Escape")
      await assertFocused(bell, "bell after keyboard open")
    },
  },
]
```

`web/scripts/shell-behaviour.mjs`:

```js
#!/usr/bin/env node
/*
 *   node scripts/shell-behaviour.mjs [--check <prefix>] [--axe]
 *
 * Runs SHELL_CHECKS against `vite preview` of dist/ (run `npm run build`
 * first). --axe additionally runs axe-core after each check marked `axe: true`
 * (and after every check's final state when no check is marked) and fails on
 * any violation. Exit 0 only when every check passes.
 */
import path from "node:path"
import { chromium } from "@playwright/test"
import { SHELL_CHECKS } from "./drift/checks-shell.mjs"
import { WEB_DIR, openApp, startServers } from "./drift/harness.mjs"

const argv = process.argv.slice(2)
const prefix = argv.includes("--check") ? argv[argv.indexOf("--check") + 1] : ""
const withAxe = argv.includes("--axe")
const AXE = path.join(WEB_DIR, "node_modules", "axe-core", "axe.min.js")

async function main() {
  const servers = await startServers({ needKit: false })
  const browser = await chromium.launch()
  let failed = 0
  try {
    for (const check of SHELL_CHECKS.filter((c) => c.id.startsWith(prefix))) {
      const width = check.width ?? 1440
      const { context, page } = await openApp(browser, {
        width,
        height: width <= 390 ? 844 : 900,
        theme: check.theme ?? "light",
        app: check.app,
      })
      try {
        await check.run(page)
        if (withAxe && check.axe !== false) {
          await page.addScriptTag({ path: AXE })
          const result = await page.evaluate(async () => await window.axe.run())
          if (result.violations.length) {
            const lines = result.violations.map((v) => `${v.impact} ${v.id} (${v.nodes.length})`).join("; ")
            throw new Error(`axe: ${lines}`)
          }
        }
        console.log(`pass  ${check.id}`)
      } catch (error) {
        failed++
        console.log(`FAIL  ${check.id}: ${error.message}`)
      } finally {
        await context.close()
      }
    }
  } finally {
    await browser.close()
    servers.stop()
  }
  if (failed) {
    console.error(`${failed} check(s) failed`)
    process.exitCode = 1
  }
}

main().catch((error) => {
  console.error(error)
  process.exitCode = 1
})
```

- [ ] **Step 11: Run unit tests, typecheck, behaviour, drift**

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/student-home-variants/web
npx vitest run tests/unit/shellPanels.test.ts tests/unit/teacherTopBarSheets.test.ts tests/unit/navigation.test.ts tests/unit/navShells.test.ts tests/unit/settingsTabs.test.ts tests/unit/rtlSafety.test.ts tests/unit/utilityExistence.test.ts
npm run typecheck && npx oxlint src/components/shell src/portals/teacher
npm run build
node scripts/shell-behaviour.mjs
node scripts/home-drift.mjs --scene teacher-
```

Expected: all named Vitest files pass; typecheck and oxlint exit 0; build passes the bundle budget (the panels stay lazy chunks); 3 behaviour checks `pass`; every teacher drift key `pass` at 0.000% (pure move). Then prove a behaviour check can go red: temporarily change the first check's last line to `await assertFocused(page.locator("body"), "bell trigger")`, run `node scripts/shell-behaviour.mjs --check teacher-bell-escape`, expect `FAIL  teacher-bell-escape-returns-focus`, then revert the edit and re-run to `pass`.

- [ ] **Step 12: Commit**

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/student-home-variants
FILES="web/src/components/shell/NotificationsPanel.tsx web/src/components/shell/AccountPanel.tsx web/src/components/shell/ShellAvatar.tsx web/src/components/shell/TopBarSheets.tsx web/src/components/shell/shellModel.ts web/src/portals/teacher/components/NotificationsMenu.tsx web/src/portals/teacher/components/ProfileMenu.tsx web/src/portals/teacher/components/ProfileAvatar.tsx web/src/portals/teacher/components/TopBarSheets.tsx web/src/portals/teacher/components/CreateSheet.tsx web/src/portals/teacher/index.tsx web/tests/unit/shellPanels.test.ts web/scripts/shell-behaviour.mjs web/scripts/drift/checks-shell.mjs"
/home/sico/Code/Lemely/.venv/bin/pre-commit run --files $FILES
git commit -S -m "refactor(web): move teacher top-bar panels into components/shell" -m "Portal facts (destinations, icons, links, copy) are now props. The empty inbox renders its heading and body as one line." -- $FILES
```

---

### Task 3: Shell styles, icons, tokens, design A panels and `ShellTopBar`; teacher uses it

**Files:**
- Modify: `web/src/index.css` (tokens near `--breakpoint-sidebar` / `--sidebar-width`; utility near `.w-sidebar`)
- Create: `web/src/components/shell/shellStyles.ts`, `web/src/components/shell/icons.tsx`, `web/src/components/shell/ShellTopBar.tsx`
- Modify: `web/src/components/shell/shellModel.ts`, `ShellAvatar.tsx`, `NotificationsPanel.tsx`, `AccountPanel.tsx`
- Modify: `web/src/portals/teacher/index.tsx` (replace `TeacherTopBar` and `TOP_BAR_ICON_BUTTON`)
- Create: `web/tests/unit/shellModel.test.ts`
- Modify: `web/scripts/drift/justifications.json`

**Interfaces:**
- Consumes: Task 2's `NotificationsPanelProps`, `AccountPanelProps`, `AccountLink`, `profileName`, `ShellAvatarPlaceholder`, `TEACHER_NOTIFICATIONS_PANEL`, `TEACHER_ACCOUNT_LINKS`.
- Produces:
  ```ts
  // shellStyles.ts
  export const SHELL_FOCUS_RING: string
  export const SHELL_BUTTON_PRIMARY: string
  export const SHELL_BUTTON_TONAL: string
  export const SHELL_ICON_BUTTON: string
  export const SHELL_PANEL: string
  // shellModel.ts (formatAge is removed)
  export function notificationsTriggerLabel(unread: string | null): string
  export function panelTimeLabel(iso: string, now?: Date): string
  export function nextSettingsTabIndex(current: number, key: string, count: number): number | null
  // icons.tsx
  export type ShellIconName = "home" | "review" | "class" | "mega" | "bell" | "up" | "out" | "menu" | "x" | "trophy" | "friends" | "practice" | "cards" | "plan" | "heart" | "user" | "trash" | "more" | "chev"
  export function ShellIcon(props: { name: ShellIconName; size?: number; className?: string }): JSX.Element
  // ShellAvatar.tsx
  export function avatarInitial(name: string): string
  export function ShellAvatar(props: { name: string; src?: string | null; size?: "sm" | "md"; className?: string }): JSX.Element
  // ShellTopBar.tsx
  export interface ShellTopBarProps {
    title: string
    /** Breadcrumb trail; rendered only when it has more than one crumb. */
    trail: readonly Crumb[]
    onOpenNav: () => void
    /** aria-label of the menu button, e.g. "Open teacher navigation". */
    navLabel: string
    /** The portal's own bar buttons (Create, Upload), already styled with SHELL_BUTTON_*. */
    actions?: ReactNode
    notifications: Omit<NotificationsPanelProps, "unread" | "triggerClassName">
    settingsTo: string
    account: Omit<AccountPanelProps, "triggerClassName">
  }
  export function ShellTopBar(props: ShellTopBarProps): JSX.Element
  ```
  New Tailwind variants: `shell-lg:` (≥1001px), `max-shell-lg:` (<1001px), `shell-sm:` / `max-shell-sm:` (721px), utility `w-shell-sidebar` (216px).

Design A rule → Tailwind mapping for this task (source `variant-a.css`):

| Selector and values | Tailwind |
|---|---|
| `.as-bar` sticky, top `--space-2`, z 6, flex, gap `--space-2`, block-size 56px, margin `8px 28px 24px`, padding-inline `17px 11px`, border 1px `--border-subtle`, radius `--radius-inner`, bg `--md-surface-lowest`, transition box-shadow | `sticky top-2 z-nav mx-7 mt-2 mb-6 flex h-14 items-center gap-2 rounded-inner border border-outline-variant bg-surface-container-lowest ps-[17px] pe-[11px] transition-shadow duration-200` |
| `.as-bar.is-stuck` box-shadow `--shadow-hover`; dark: border transparent, bg `--surface-card`, stuck no shadow | `data-[stuck=true]:shadow-[var(--shadow-hover)] dark:border-transparent dark:bg-surface-container-high dark:data-[stuck=true]:shadow-none` |
| ≤1000: `.as-bar` margin-inline 10px, padding-inline 12px 10px | `max-shell-lg:mx-2.5 max-shell-lg:ps-3 max-shell-lg:pe-2.5` |
| ≤720: `.as-bar` relative, block-size 44px, margin 0, padding-inline 14px 8px, no border, radius 0, transparent, no shadow | `max-shell-sm:relative max-shell-sm:top-auto max-shell-sm:m-0 max-shell-sm:h-11 max-shell-sm:rounded-none max-shell-sm:border-0 max-shell-sm:bg-transparent max-shell-sm:ps-3.5 max-shell-sm:pe-2 max-shell-sm:shadow-none dark:max-shell-sm:bg-transparent` |
| `.as-title` 800 21px/1, letter-spacing -0.02em, margin-inline-end auto | `me-auto min-w-0 truncate text-[21px] font-extrabold leading-none tracking-[-0.02em] text-on-surface` |
| `.as-menu` hidden above 1000, grid at ≤1000, hidden ≤720 | `shell-lg:hidden max-shell-sm:hidden` on an icon button |
| `.as-bar-upload` margin-inline-end 10px; hidden ≤720 | `me-2.5 max-shell-sm:hidden` (portal applies to its Upload link) |
| `.as-btn` inline-flex, gap 7px, 36px, padding 0 14px, radius chip, 700 14px/1, nowrap, `:active` scale .97 | `inline-flex h-9 items-center gap-[7px] whitespace-nowrap rounded-chip px-3.5 btn-text active:scale-[0.97]` |
| `.as-btn-primary` / `:hover` | `bg-primary text-on-primary hover:bg-primary-hover` |
| `.as-btn-tonal` / `:hover` color-mix 8% primary | `bg-secondary-container text-on-secondary-container hover:bg-[color-mix(in_oklch,var(--color-secondary-container),var(--color-primary)_8%)]` |
| `.as-iconbtn` 36px grid, radius chip, muted; hover/open bg `--md-surface-low`, color on-surface | `relative grid size-9 place-items-center rounded-chip text-on-surface-variant hover:bg-surface-container-low hover:text-on-surface data-[state=open]:bg-surface-container-low data-[state=open]:text-on-surface` |
| `.as-dot` top 6px, end 7px, 8px, pill, primary, ring 2px lowest | `absolute end-[7px] top-1.5 size-2 rounded-pill bg-primary shadow-[0_0_0_2px_var(--color-surface-container-lowest)]` (dark ring: `--color-surface-container-high`) |
| `.as-avatar` 32px circle, primary-container, primary, 800 11px/1; `.as-ident .as-avatar` 38px, 14px | `size-8 rounded-pill bg-primary-container text-primary text-[11px] font-extrabold leading-none` / `size-[38px] text-[14px]` |
| `.as-ico` 18px, stroke 1.7, round caps/joins; `.as-ico-ph` (gear) 20px filled | `ShellIcon` defaults; `<Gear size={20} />` |
| `.as-pop-panel` top 100%+8px, end 0, z 30, 320px, padding 8px, radius inner, lowest, `--shadow-panel`; dark highest + 1px outline ring | `z-dropdown w-80 rounded-inner bg-surface-container-lowest p-2 text-on-surface shadow-[var(--shadow-panel)] dark:bg-surface-container-highest dark:shadow-[0_0_0_1px_var(--color-outline)]` with Radix `sideOffset={8}` `align="end"` |
| ≤720: panels inset-inline 10px | `max-shell-sm:w-[calc(100vw-20px)]` with Radix `collisionPadding={10}` |
| `.as-pop-me .as-pop-panel` 260px | `w-65` |
| `.as-pop-head` baseline, space-between, gap 12px, margin 6px 8px; h2 800 14px/1.2 -0.01em | `mx-2 my-1.5 flex items-baseline justify-between gap-3`; `text-body-sm font-extrabold leading-[1.2] tracking-[-0.01em]` |
| `.as-textbtn` margin -4px -8px, padding 4px 8px, radius chip, primary 600 11px/1.3; hover `--surface-row`; disabled muted, no bg | `-mx-2 -my-1 rounded-chip px-2 py-1 text-[11px] font-semibold leading-[1.3] text-primary hover:bg-surface-container-low disabled:cursor-default disabled:bg-transparent disabled:text-on-surface-variant` |
| `.as-item` grid 32px/1fr/auto, gap 10px, start, padding 8px, radius chip, 14px; hover low | `grid grid-cols-[32px_minmax(0,1fr)_auto] items-start gap-2.5 rounded-chip p-2 text-body-sm data-[highlighted]:bg-surface-container-low` |
| `.as-item-ico` 32px, radius row 10px, primary-container, primary | `grid size-8 place-items-center rounded-row bg-primary-container text-primary` |
| `.as-item-t b` 700 body; `small` 11px muted | `font-bold text-on-surface [text-wrap:pretty] line-clamp-2`; `text-[11px] text-on-surface-variant` |
| `.as-item time` column end, gap 8px, 500 11px/1.3 mono muted; unread `::after` 8px pill primary | `flex flex-col items-end gap-2 font-mono text-[11px] font-medium leading-[1.3] text-on-surface-variant` + `<span className="size-2 rounded-pill bg-primary" />` |
| `.as-pop-empty` padding 8px 8px 12px, 14px/1.5 muted | `px-2 pt-2 pb-3 text-body-sm leading-normal text-on-surface-variant` |
| `.as-pop-foot` gap 4px, mt 4px, pt 4px, top border; links flex 1, padding 8px, radius chip, center, primary 600 11px/1.3 | `mt-1 flex gap-1 border-t border-outline-variant pt-1`; `flex-1 rounded-chip p-2 text-center text-[11px] font-semibold leading-[1.3] text-primary data-[highlighted]:bg-surface-container-low` |
| `.as-ident` gap 10px, padding 10px 8px 12px, mb 4px, bottom border; `.as-who b` 700 14px/1.3; `small` 14px/1.4 muted, ellipsis | `mb-1 flex items-center gap-2.5 border-b border-outline-variant px-2 pt-2.5 pb-3`; `text-body-sm font-bold leading-[1.3]`; `truncate text-body-sm leading-[1.4] text-on-surface-variant` |
| `.as-links :is(a,button)` flex, gap 10px, padding 9px 8px, radius chip, 600 14px/1.3 body; hover low; icon muted | `flex w-full items-center gap-2.5 rounded-chip px-2 py-[9px] text-start text-label text-on-surface data-[highlighted]:bg-surface-container-low` |
| `@media (pointer: coarse)` icon buttons 44px; rows, textbtn, foot links, buttons min 44px | `pointer-coarse:size-11`, `pointer-coarse:min-h-11` |

- [ ] **Step 1: Write the failing test `web/tests/unit/shellModel.test.ts`**

```ts
import { describe, expect, it } from "vitest"
import { nextSettingsTabIndex, notificationsTriggerLabel, panelTimeLabel } from "@/components/shell/shellModel"
import { avatarInitial } from "@/components/shell/ShellAvatar"

const NOW = new Date(2026, 10, 5, 10, 0) // Thu 5 Nov 2026, the preview fixtures' "now"

describe("notificationsTriggerLabel", () => {
  it("names the unread count when there is one", () => {
    expect(notificationsTriggerLabel("3")).toBe("Notifications, 3 unread")
    expect(notificationsTriggerLabel("99+")).toBe("Notifications, 99+ unread")
  })
  it("is plain when nothing is unread or the count is unknown", () => {
    expect(notificationsTriggerLabel(null)).toBe("Notifications")
  })
})

describe("panelTimeLabel (design A: 9:12, Wed, 27 Oct)", () => {
  it("shows the clock time for today, without a leading zero on the hour", () => {
    expect(panelTimeLabel(new Date(2026, 10, 5, 9, 12).toISOString(), NOW)).toBe("9:12")
    expect(panelTimeLabel(new Date(2026, 10, 5, 8, 4).toISOString(), NOW)).toBe("8:04")
  })
  it("shows the weekday within the last six days", () => {
    expect(panelTimeLabel(new Date(2026, 10, 4, 18, 0).toISOString(), NOW)).toBe("Wed")
    expect(panelTimeLabel(new Date(2026, 10, 2, 17, 0).toISOString(), NOW)).toBe("Mon")
    expect(panelTimeLabel(new Date(2026, 9, 30, 9, 0).toISOString(), NOW)).toBe("Fri")
  })
  it("shows day and month from a week back", () => {
    expect(panelTimeLabel(new Date(2026, 9, 29, 9, 0).toISOString(), NOW)).toBe("29 Oct")
    expect(panelTimeLabel(new Date(2026, 9, 27, 16, 0).toISOString(), NOW)).toBe("27 Oct")
  })
  it("is empty for an unparseable time rather than 'Invalid Date'", () => {
    expect(panelTimeLabel("not a date", NOW)).toBe("")
  })
})

describe("nextSettingsTabIndex (arrow keys on the settings tabs)", () => {
  it.each([
    [0, "ArrowDown", 5, 1],
    [0, "ArrowRight", 5, 1],
    [4, "ArrowDown", 5, 0],
    [0, "ArrowUp", 5, 4],
    [2, "ArrowLeft", 5, 1],
    [3, "Home", 5, 0],
    [1, "End", 5, 4],
  ])("from %i, %s over %i tabs goes to %i", (current, key, count, expected) => {
    expect(nextSettingsTabIndex(current, key, count)).toBe(expected)
  })
  it("ignores other keys and an unknown current tab", () => {
    expect(nextSettingsTabIndex(0, "Enter", 5)).toBeNull()
    expect(nextSettingsTabIndex(-1, "ArrowDown", 5)).toBeNull()
  })
})

describe("avatarInitial", () => {
  it("is the first letter, upper-cased", () => {
    expect(avatarInitial("mariam")).toBe("M")
    expect(avatarInitial("  Ömer ")).toBe("Ö")
  })
  it("falls back to ? for an empty name", () => {
    expect(avatarInitial("")).toBe("?")
  })
})
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd web && npx vitest run tests/unit/shellModel.test.ts`
Expected: FAIL (`notificationsTriggerLabel` is not exported).

- [ ] **Step 3: Replace `web/src/components/shell/shellModel.ts`**

```ts
/*
 * Pure shell logic, unit-tested in tests/unit/shellModel.test.ts (the unit
 * runner has no DOM, so anything worth pinning lives here, not in a component).
 */

/** The bell's accessible name. `unread` is `unreadBadgeLabel(counts)`. */
export function notificationsTriggerLabel(unread: string | null): string {
  return unread ? `Notifications, ${unread} unread` : "Notifications"
}

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

/** The bell panel's time column, as design A writes it: the clock time today
 * ("9:12"), the weekday within the last six days ("Wed"), day and month
 * before that ("27 Oct"). The exact instant stays in `<time dateTime>`. */
export function panelTimeLabel(iso: string, now: Date = new Date()): string {
  const t = new Date(iso)
  if (Number.isNaN(t.getTime())) return ""
  const sameDay =
    t.getFullYear() === now.getFullYear() && t.getMonth() === now.getMonth() && t.getDate() === now.getDate()
  if (sameDay) return `${t.getHours()}:${String(t.getMinutes()).padStart(2, "0")}`
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  const days = Math.ceil((startOfToday - t.getTime()) / 86_400_000)
  if (days >= 0 && days < 7) return WEEKDAYS[t.getDay()]
  return `${t.getDate()} ${MONTHS[t.getMonth()]}`
}

const STEP: Record<string, 1 | -1> = { ArrowDown: 1, ArrowRight: 1, ArrowUp: -1, ArrowLeft: -1 }

/** Arrow keys move between settings tabs (up/down on the rail, left/right on
 * the phone strip), wrapping; Home and End jump to the ends. */
export function nextSettingsTabIndex(current: number, key: string, count: number): number | null {
  if (current < 0 || count <= 0) return null
  if (key in STEP) return (current + STEP[key] + count) % count
  if (key === "Home") return 0
  if (key === "End") return count - 1
  return null
}
```

- [ ] **Step 4: Add the layout tokens to `web/src/index.css`**

Directly after the `--breakpoint-sidebar: 820px;` line:

```css
  /* Portal shell (design A, docs/superpowers/specs/2026-11-06-portal-shell-design.md).
     `shell-lg:` is where the sidebar is a column (design A's drawer range is
     max-width 1000px); `max-shell-sm:` is the phone range where the top bar
     goes flat (design A: max-width 720px). */
  --breakpoint-shell-lg: 1001px;
  --breakpoint-shell-sm: 721px;
```

Directly after `--sidebar-width: 252px;`:

```css
  /* Design A's sidebar column (`--as-side: 216px`), used by components/shell. */
  --shell-sidebar-width: 216px;
```

Directly after the `.w-sidebar { … }` rule:

```css
.w-shell-sidebar {
  width: var(--shell-sidebar-width);
}
```

- [ ] **Step 5: Create `web/src/components/shell/shellStyles.ts`**

```ts
/*
 * Class strings shared by the shell, each mapped from a design A rule in
 * web/dev-previews/student-home/variant-a.css (selector named on each).
 */

export const SHELL_FOCUS_RING =
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"

/** `.as-btn` */
const SHELL_BUTTON =
  "inline-flex h-9 flex-none cursor-pointer items-center gap-[7px] whitespace-nowrap rounded-chip px-3.5 btn-text transition-[transform,background-color] duration-150 active:scale-[0.97] pointer-coarse:min-h-11 " +
  SHELL_FOCUS_RING

/** `.as-btn-primary` */
export const SHELL_BUTTON_PRIMARY = `${SHELL_BUTTON} bg-primary text-on-primary hover:bg-primary-hover`

/** `.as-btn-tonal` */
export const SHELL_BUTTON_TONAL = `${SHELL_BUTTON} bg-secondary-container text-on-secondary-container hover:bg-[color-mix(in_oklch,var(--color-secondary-container),var(--color-primary)_8%)]`

/** `.as-iconbtn`, open state from Radix's `data-state`. */
export const SHELL_ICON_BUTTON =
  "relative grid size-9 flex-none cursor-pointer place-items-center rounded-chip text-on-surface-variant transition-colors duration-150 hover:bg-surface-container-low hover:text-on-surface data-[state=open]:bg-surface-container-low data-[state=open]:text-on-surface pointer-coarse:size-11 " +
  SHELL_FOCUS_RING

/** `.as-pop-panel` (+ its ≤720px inset rule). */
export const SHELL_PANEL =
  "z-dropdown w-80 rounded-inner bg-surface-container-lowest p-2 text-on-surface shadow-[var(--shadow-panel)] dark:bg-surface-container-highest dark:shadow-[0_0_0_1px_var(--color-outline)] max-shell-sm:w-[calc(100vw-20px)] motion-safe:animate-[lm-in_var(--dur-base)_var(--ease-out)_both]"
```

- [ ] **Step 6: Create `web/src/components/shell/icons.tsx`**

```tsx
import { cn } from "@/lib/utils"

/*
 * Design A's stroke icons (the <symbol>s at the top of
 * web/dev-previews/student-home-a.html, 24-unit grid). Drawn as the design
 * draws `.as-ico`: 18px, no fill, 1.7 stroke, round caps and joins.
 */
const PATHS = {
  home: "M3 11l9-8 9 8v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z",
  review: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z M8 12l3 3 5-6",
  class: "M9 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6z M3 20c0-3.3 2.7-6 6-6s6 2.7 6 6 M17 11a2.5 2.5 0 1 0 0-5 M17 14c2.5 0 4 2 4 5",
  mega: "M3 10v4h4l7 4V6l-7 4z M17 9a4 4 0 0 1 0 6",
  bell: "M6 9a6 6 0 0 1 12 0c0 6 2 7 2 7H4s2-1 2-7 M10 20a2 2 0 0 0 4 0",
  up: "M12 16V4 M7 9l5-5 5 5 M4 20h16",
  out: "M9 4H5v16h4 M16 8l4 4-4 4 M20 12H9",
  menu: "M4 7h16M4 12h16M4 17h16",
  x: "M6 6l12 12M18 6L6 18",
  trophy: "M7 4h10v5a5 5 0 0 1-10 0z M7 6H4v1a3 3 0 0 0 3 3 M17 6h3v1a3 3 0 0 1-3 3 M12 14v3 M8 20h8",
  friends: "M8 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6z M2 20c0-3.3 2.7-6 6-6s6 2.7 6 6 M16 11a3 3 0 1 0 0-6 M16 14c3.3 0 6 2.7 6 6",
  practice: "M15 4l5 5L9 20H4v-5z M13 6l5 5",
  cards: "M4 8h12v12H4z M8 4h12v12",
  plan: "M4 6h16v14H4z M4 10h16 M8 3v4 M16 3v4 M8 14h3 M8 17h6",
  heart: "M12 20s-8-4.6-8-10.2A4.3 4.3 0 0 1 12 7.5a4.3 4.3 0 0 1 8 2.3C20 15.4 12 20 12 20z",
  user: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8z M4 21c0-4.4 3.6-7 8-7s8 2.6 8 7",
  trash: "M4 7h16 M9 7V4h6v3 M6 7l1 13h10l1-13 M10 11v6 M14 11v6",
  more: "M4 4h6v6H4z M14 4h6v6h-6z M4 14h6v6H4z M14 14h6v6h-6z",
  chev: "M9 6l6 6-6 6",
} as const

export type ShellIconName = keyof typeof PATHS

export function ShellIcon({ name, size = 18, className }: { name: ShellIconName; size?: number; className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.7}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      className={cn("flex-none", className)}
    >
      <path d={PATHS[name]} />
    </svg>
  )
}
```

- [ ] **Step 7: Replace `web/src/components/shell/ShellAvatar.tsx`**

```tsx
import { useProfile } from "@/lib/hooks/useMeApi"
import type { Profile } from "@/lib/meTypes"
import { cn } from "@/lib/utils"

/** The name the avatar's initial and the panel's label come from. */
export function profileName(profile: Pick<Profile, "displayName" | "email">): string {
  return profile.displayName ?? profile.email.split("@")[0]
}

/** Design A's avatar shows one letter. */
export function avatarInitial(name: string): string {
  const first = Array.from(name.trim())[0]
  return first ? first.toLocaleUpperCase() : "?"
}

/** `.as-avatar` (32px) and `.as-ident .as-avatar` (38px): a circle, as design A draws it. */
export function ShellAvatar({
  name,
  src,
  size = "sm",
  className,
}: {
  name: string
  src?: string | null
  size?: "sm" | "md"
  className?: string
}) {
  const box = size === "sm" ? "size-8 text-[11px]" : "size-[38px] text-[14px]"
  if (src) {
    return <img src={src} alt="" className={cn("flex-none rounded-pill object-cover", box, className)} />
  }
  return (
    <span
      aria-hidden="true"
      className={cn(
        "grid flex-none place-items-center rounded-pill bg-primary-container font-extrabold leading-none text-primary",
        box,
        className,
      )}
    >
      {avatarInitial(name)}
    </span>
  )
}

/**
 * What stands in the account panel's slot until its chunk and the profile
 * have loaded: the same box, so nothing shifts when the trigger replaces it.
 * Not interactive.
 */
export function ShellAvatarPlaceholder() {
  const { data } = useProfile()
  return (
    <span aria-hidden="true" className="grid size-9 flex-none place-items-center pointer-coarse:size-11">
      {data ? (
        <ShellAvatar name={profileName(data)} src={data.avatarUrl} />
      ) : (
        <span className="size-8 rounded-pill bg-surface-container" />
      )}
    </span>
  )
}
```

(`PROFILE_AVATAR_BOX` is gone; grep `web/src` for it and expect no hits.)

- [ ] **Step 8: Replace `web/src/components/shell/NotificationsPanel.tsx` with the design A panel**

```tsx
import type { ReactNode } from "react"
import { Link, useNavigate } from "react-router-dom"
import { DropdownMenu } from "radix-ui"
import { useMarkAllNotificationsRead, useMarkNotificationRead, useNotifications } from "@/lib/hooks/useNotificationApi"
import type { Notification } from "@/lib/notificationTypes"
import { unreadCountOf } from "@/lib/staffInbox"
import { cn } from "@/lib/utils"
import { ShellIcon } from "./icons"
import { notificationsTriggerLabel, panelTimeLabel } from "./shellModel"
import { SHELL_FOCUS_RING, SHELL_PANEL } from "./shellStyles"

export interface NotificationsPanelProps {
  unread: string | null
  triggerClassName: string
  destinationFor: (notification: Notification) => string | null
  iconFor: (type: string) => ReactNode
  inboxTo: string
  footerLinks: readonly { to: string; label: string }[]
  emptyMessage: string
  errorHeading: string
  previewLimit?: number
}

type PanelProps = Omit<NotificationsPanelProps, "unread" | "triggerClassName">

const ITEM =
  "grid w-full cursor-pointer grid-cols-[32px_minmax(0,1fr)_auto] items-start gap-2.5 rounded-chip p-2 text-start text-body-sm text-on-surface outline-none transition-colors duration-150 data-[highlighted]:bg-surface-container-low focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-primary"

const FOOT_LINK =
  "flex-1 cursor-pointer rounded-chip p-2 text-center text-[11px] font-semibold leading-[1.3] text-primary outline-none transition-colors duration-150 data-[highlighted]:bg-surface-container-low pointer-coarse:min-h-11 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-primary"

function Row({ notification, destinationFor, iconFor, inboxTo }: { notification: Notification } & PanelProps) {
  const navigate = useNavigate()
  const markRead = useMarkNotificationRead()
  const unread = notification.readAt === null
  return (
    <DropdownMenu.Item
      className={ITEM}
      onSelect={() => {
        if (unread) markRead.mutate(notification.notificationId)
        void navigate(destinationFor(notification) ?? inboxTo)
      }}
    >
      <span className="grid size-8 place-items-center rounded-row bg-primary-container text-primary">
        {iconFor(notification.type)}
      </span>
      <span className="flex min-w-0 flex-col">
        {unread ? <span className="sr-only">Unread: </span> : null}
        <b className="line-clamp-2 font-bold text-on-surface [text-wrap:pretty]">{notification.title}</b>
        {notification.body ? (
          <small className="text-[11px] text-on-surface-variant">{notification.body}</small>
        ) : null}
      </span>
      <time
        dateTime={notification.createdAt}
        className="flex flex-col items-end gap-2 font-mono text-[11px] font-medium leading-[1.3] text-on-surface-variant"
      >
        {panelTimeLabel(notification.createdAt)}
        {unread ? <span aria-hidden="true" className="size-2 rounded-pill bg-primary" /> : null}
      </time>
    </DropdownMenu.Item>
  )
}

/** Mounts only while the panel is open, so the inbox is fetched on first open. */
function Panel(props: PanelProps) {
  const query = useNotifications()
  const markAll = useMarkAllNotificationsRead()
  const page = query.data
  const hasRows = Boolean(page && page.notifications.length > 0)
  const unreadRows = page ? unreadCountOf(page) : 0
  return (
    <>
      <div className="mx-2 my-1.5 flex items-baseline justify-between gap-3">
        <p className="text-body-sm font-extrabold leading-[1.2] tracking-[-0.01em]">Notifications</p>
        {hasRows ? (
          <button
            type="button"
            onClick={() => markAll.mutate()}
            disabled={unreadRows === 0 || markAll.isPending}
            className={cn(
              "-mx-2 -my-1 cursor-pointer rounded-chip px-2 py-1 text-[11px] font-semibold leading-[1.3] text-primary transition-colors duration-150 hover:bg-surface-container-low disabled:cursor-default disabled:bg-transparent disabled:text-on-surface-variant pointer-coarse:min-h-11",
              SHELL_FOCUS_RING,
            )}
          >
            Mark all read
          </button>
        ) : null}
      </div>
      {query.isPending ? (
        <p role="status" className="px-2 pt-2 pb-3 text-body-sm text-on-surface-variant">
          Loading
        </p>
      ) : query.isError ? (
        <div role="alert" className="px-2 pt-2 pb-3 text-body-sm">
          <p className="font-bold">{props.errorHeading}</p>
          <button
            type="button"
            onClick={() => void query.refetch()}
            className={cn("mt-1 rounded-chip font-bold text-primary hover:underline", SHELL_FOCUS_RING)}
          >
            Try again
          </button>
        </div>
      ) : !hasRows ? (
        <p className="px-2 pt-2 pb-3 text-body-sm leading-normal text-on-surface-variant">{props.emptyMessage}</p>
      ) : (
        <div className="flex flex-col">
          {page!.notifications.slice(0, props.previewLimit ?? 4).map((n) => (
            <Row key={n.notificationId} notification={n} {...props} />
          ))}
        </div>
      )}
      <div className="mt-1 flex gap-1 border-t border-outline-variant pt-1">
        {props.footerLinks.map((link) => (
          <DropdownMenu.Item key={link.to} asChild>
            <Link to={link.to} className={FOOT_LINK}>
              {link.label}
            </Link>
          </DropdownMenu.Item>
        ))}
      </div>
    </>
  )
}

/**
 * The bell and the panel it drops (Radix DropdownMenu: anchored, no scroll
 * lock, arrow keys, Escape and outside click close it and focus returns to
 * the bell). `unread` comes from the counts query the top bar already reads,
 * so the dot shows before the panel is ever opened.
 */
export function NotificationsPanel({ unread, triggerClassName, ...panel }: NotificationsPanelProps) {
  return (
    <DropdownMenu.Root modal={false}>
      <DropdownMenu.Trigger aria-label={notificationsTriggerLabel(unread)} className={triggerClassName}>
        <ShellIcon name="bell" />
        {unread ? (
          <i
            aria-hidden="true"
            className="absolute end-[7px] top-1.5 size-2 rounded-pill bg-primary shadow-[0_0_0_2px_var(--color-surface-container-lowest)] dark:shadow-[0_0_0_2px_var(--color-surface-container-high)]"
          />
        ) : null}
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content align="end" sideOffset={8} collisionPadding={10} className={SHELL_PANEL}>
          <Panel {...panel} />
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  )
}
```

(`unreadCountOf` is exported by `web/src/lib/staffInbox.ts` on `develop`. The panel heading stays a `<p>`, as on `develop`: a heading inside `role="menu"` trips axe's required-children rule. Log that against design A's `<h2>`.)

- [ ] **Step 9: Replace the body of `web/src/components/shell/AccountPanel.tsx` with the design A panel**

```tsx
import type { ReactNode } from "react"
import { Link, useNavigate } from "react-router-dom"
import { DropdownMenu } from "radix-ui"
import { useAuth } from "@/lib/auth/AuthContext"
import { useProfile } from "@/lib/hooks/useMeApi"
import { useOverlayState } from "@/lib/nav/useOverlayState"
import { cn } from "@/lib/utils"
import { ShellIcon } from "./icons"
import { ShellAvatar, ShellAvatarPlaceholder, profileName } from "./ShellAvatar"
import { SHELL_ICON_BUTTON, SHELL_PANEL } from "./shellStyles"

export interface AccountLink {
  id: string
  label: string
  icon: ReactNode
  to?: string
  href?: string
  overlay?: boolean
  description?: string
}

export interface AccountPanelProps {
  links: readonly AccountLink[]
  detail: string | null
  triggerClassName?: string
}

const LINK =
  "flex w-full cursor-pointer items-center gap-2.5 rounded-chip px-2 py-[9px] text-start text-label text-on-surface outline-none transition-colors duration-150 data-[highlighted]:bg-surface-container-low pointer-coarse:min-h-11 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-primary [&>svg]:text-on-surface-variant"

function LinkText({ link }: { link: AccountLink }) {
  return link.description ? (
    <span className="min-w-0">
      <span className="block">{link.label}</span>
      <span className="block text-body-sm font-normal text-on-surface-variant">{link.description}</span>
    </span>
  ) : (
    <span>{link.label}</span>
  )
}

/**
 * The signed-in person's avatar at the end of the top bar and the panel it
 * drops: who, then the portal's links, then Sign out. Until the profile
 * resolves the slot holds `ShellAvatarPlaceholder`. Radix DropdownMenu gives
 * aria-haspopup/expanded, focus into the panel and back to the avatar.
 */
export function AccountPanel({ links, detail, triggerClassName }: AccountPanelProps) {
  const { data } = useProfile()
  const { logout } = useAuth()
  const navigate = useNavigate()
  const overlayState = useOverlayState()
  if (!data) return <ShellAvatarPlaceholder />
  const name = profileName(data)
  return (
    <DropdownMenu.Root modal={false}>
      <DropdownMenu.Trigger
        aria-label={`Your profile and account, ${name}`}
        className={cn(SHELL_ICON_BUTTON, "rounded-pill", triggerClassName)}
      >
        <ShellAvatar name={name} src={data.avatarUrl} />
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content align="end" sideOffset={8} collisionPadding={10} className={cn(SHELL_PANEL, "w-65")}>
          <div className="mb-1 flex items-center gap-2.5 border-b border-outline-variant px-2 pt-2.5 pb-3">
            <ShellAvatar name={name} src={data.avatarUrl} size="md" />
            <span className="flex min-w-0 flex-col">
              <b className="text-body-sm font-bold leading-[1.3] text-on-surface">{name}</b>
              <small className="truncate text-body-sm leading-[1.4] text-on-surface-variant">{data.email}</small>
              {detail ? (
                <small className="truncate text-body-sm leading-[1.4] text-on-surface-variant">{detail}</small>
              ) : null}
            </span>
          </div>
          {links.map((link) => (
            <DropdownMenu.Item key={link.id} asChild>
              {link.href ? (
                <a href={link.href} className={LINK}>
                  {link.icon}
                  <LinkText link={link} />
                </a>
              ) : (
                <Link to={link.to ?? "/"} state={link.overlay ? overlayState : undefined} className={LINK}>
                  {link.icon}
                  <LinkText link={link} />
                </Link>
              )}
            </DropdownMenu.Item>
          ))}
          <DropdownMenu.Item
            className={LINK}
            onSelect={() => {
              // Session caches finish clearing before the sign-in screen mounts.
              void logout().then(() => navigate("/login", { replace: true }))
            }}
          >
            <ShellIcon name="out" />
            <span>Sign out</span>
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  )
}
```

`TopBarSheets.tsx`'s `IconTile` is no longer used by the panels (design A links have bare icons); it stays for `ActionSheet`.

- [ ] **Step 10: Create `web/src/components/shell/ShellTopBar.tsx`**

```tsx
import { lazy, Suspense, useEffect, useState, type ReactNode } from "react"
import { Link } from "react-router-dom"
import { Gear } from "@phosphor-icons/react"
import { Breadcrumbs, type Crumb } from "@/components/ui/breadcrumbs"
import { useNotificationCounts } from "@/lib/hooks/useNotificationApi"
import { useOverlayState } from "@/lib/nav/useOverlayState"
import { unreadBadgeLabel } from "@/lib/staffInbox"
import { cn } from "@/lib/utils"
import type { AccountPanelProps } from "./AccountPanel"
import type { NotificationsPanelProps } from "./NotificationsPanel"
import { ShellAvatarPlaceholder } from "./ShellAvatar"
import { ShellIcon } from "./icons"
import { SHELL_ICON_BUTTON } from "./shellStyles"

// Lazy so Radix's menu stays out of the entry chunk's budget (check:bundle).
const NotificationsPanel = lazy(() =>
  import("./NotificationsPanel").then((m) => ({ default: m.NotificationsPanel })),
)
const AccountPanel = lazy(() => import("./AccountPanel").then((m) => ({ default: m.AccountPanel })))

export interface ShellTopBarProps {
  title: string
  trail: readonly Crumb[]
  onOpenNav: () => void
  navLabel: string
  actions?: ReactNode
  notifications: Omit<NotificationsPanelProps, "unread" | "triggerClassName">
  settingsTo: string
  account: Omit<AccountPanelProps, "triggerClassName">
}

/** `.as-bar.is-stuck`: the bar lifts once the page scrolls under it. */
function useScrolled(): boolean {
  const [scrolled, setScrolled] = useState(false)
  useEffect(() => {
    const sync = () => setScrolled(window.scrollY > 0)
    sync()
    window.addEventListener("scroll", sync, { passive: true })
    return () => window.removeEventListener("scroll", sync)
  }, [])
  return scrolled
}

const BAR = cn(
  "lm-nav-chrome sticky top-2 z-nav mx-7 mt-2 mb-6 flex h-14 items-center gap-2 rounded-inner border border-outline-variant bg-surface-container-lowest ps-[17px] pe-[11px] transition-shadow duration-200",
  "data-[stuck=true]:shadow-[var(--shadow-hover)] dark:border-transparent dark:bg-surface-container-high dark:data-[stuck=true]:shadow-none",
  "max-shell-lg:mx-2.5 max-shell-lg:ps-3 max-shell-lg:pe-2.5",
  "max-shell-sm:relative max-shell-sm:top-auto max-shell-sm:m-0 max-shell-sm:h-11 max-shell-sm:rounded-none max-shell-sm:border-0 max-shell-sm:bg-transparent max-shell-sm:ps-3.5 max-shell-sm:pe-2 max-shell-sm:shadow-none dark:max-shell-sm:bg-transparent",
)

/**
 * The floating top bar (design A `.as-bar`): menu button (drawer range only),
 * the page title, the portal's actions, bell, gear and avatar. The breadcrumb
 * trail renders under it only when the reader has drilled in.
 */
export function ShellTopBar({ title, trail, onOpenNav, navLabel, actions, notifications, settingsTo, account }: ShellTopBarProps) {
  const overlayState = useOverlayState()
  const { data: counts } = useNotificationCounts()
  const unread = unreadBadgeLabel(counts)
  const stuck = useScrolled()
  return (
    <>
      <header data-stuck={stuck} className={BAR}>
        <button
          type="button"
          onClick={onOpenNav}
          aria-label={navLabel}
          aria-haspopup="dialog"
          className={cn(SHELL_ICON_BUTTON, "shell-lg:hidden max-shell-sm:hidden")}
        >
          <ShellIcon name="menu" />
        </button>
        <p className="me-auto min-w-0 truncate text-[21px] font-extrabold leading-none tracking-[-0.02em] text-on-surface">
          {title}
        </p>
        {actions}
        <Suspense
          fallback={
            <Link to={notifications.inboxTo} aria-label="Notifications" className={SHELL_ICON_BUTTON}>
              <ShellIcon name="bell" />
            </Link>
          }
        >
          <NotificationsPanel {...notifications} unread={unread} triggerClassName={SHELL_ICON_BUTTON} />
        </Suspense>
        <Link
          to={settingsTo}
          state={overlayState}
          aria-label="Settings"
          aria-haspopup="dialog"
          className={SHELL_ICON_BUTTON}
        >
          <Gear size={20} aria-hidden="true" />
        </Link>
        <Suspense fallback={<ShellAvatarPlaceholder />}>
          <AccountPanel {...account} />
        </Suspense>
      </header>
      {trail.length > 1 ? (
        <div className="-mt-3 mb-4 px-[72px] max-shell-lg:px-3.5">
          <Breadcrumbs items={[...trail]} />
        </div>
      ) : null}
    </>
  )
}
```

- [ ] **Step 11: Teacher uses `ShellTopBar`**

In `web/src/portals/teacher/index.tsx`: delete `TeacherTopBar`, `TOP_BAR_ICON_BUTTON`, `TeacherAccountPanel`, the two lazy panel constants, and the `NavDrawerTrigger`, `Breadcrumbs`, `useNotificationCounts`, `unreadBadgeLabel`, `ShellAvatarPlaceholder` imports that only they used. Add:

```tsx
import { ShellTopBar } from "@/components/shell/ShellTopBar"
import { ShellIcon } from "@/components/shell/icons"
import { SHELL_BUTTON_PRIMARY, SHELL_BUTTON_TONAL } from "@/components/shell/shellStyles"

function TeacherTopBarActions() {
  return (
    <>
      <CreateSheet triggerClassName={cn(SHELL_BUTTON_TONAL, "max-sm:px-0 max-sm:w-9 max-sm:justify-center max-sm:pointer-coarse:w-11")} />
      <Link to="/teacher/grading" className={cn(SHELL_BUTTON_PRIMARY, "me-2.5 max-shell-sm:hidden")}>
        <ShellIcon name="up" />
        Upload papers
      </Link>
    </>
  )
}

function TeacherTopBar({ onOpenNav }: { onOpenNav: () => void }) {
  const location = useLocation()
  const { data: profile } = useProfile()
  // While Settings is a dialog the page underneath is still the page: title
  // and trail follow the background location.
  const trail = resolveTrail(
    underlyingPathname({ pathname: location.pathname, state: location.state, overlayBase: TEACHER_SETTINGS_BASE }),
  )
  return (
    <ShellTopBar
      title={trail[trail.length - 1]?.label ?? "Overview"}
      trail={trail}
      onOpenNav={onOpenNav}
      navLabel="Open teacher navigation"
      actions={<TeacherTopBarActions />}
      notifications={TEACHER_NOTIFICATIONS_PANEL}
      settingsTo={TEACHER_SETTINGS_BASE}
      account={{ links: TEACHER_ACCOUNT_LINKS, detail: profile ? roleLabel(profile.role) : null }}
    />
  )
}
```

Change `TEACHER_NOTIFICATIONS_PANEL.iconFor` to design A glyph sizes: `announcement` → `<ShellIcon name="mega" />`, `at_risk_alert` → `<Warning size={18} aria-hidden="true" />`, default → `<ShellIcon name="bell" />`. Change `TEACHER_ACCOUNT_LINKS` icons to `<ShellIcon name="user" />`, `<Gear size={18} aria-hidden="true" />`, `<Lifebuoy size={18} aria-hidden="true" />`.

`TeacherLayout` keeps calling `<TeacherTopBar onOpenNav={() => setNavOpen(true)} />`. On teacher, below 721px the menu button is hidden; the bottom tab bar's "More" opens the drawer (it already does).

- [ ] **Step 12: Run tests**

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/student-home-variants/web
npx vitest run tests/unit/shellModel.test.ts tests/unit/shellPanels.test.ts tests/unit/teacherTopBarSheets.test.ts tests/unit/navigation.test.ts tests/unit/navShells.test.ts tests/unit/design-tokens.test.ts tests/unit/utilityExistence.test.ts tests/unit/rtlSafety.test.ts tests/unit/a11yRules.test.ts tests/unit/contrastRules.test.ts tests/unit/elevationScale.test.ts tests/unit/motionDefaults.test.ts tests/unit/darkConsumers.test.ts tests/unit/hoverTransition.test.ts tests/unit/preMountShell.test.ts
npm run typecheck && npx oxlint src/components/shell src/portals/teacher
```

Expected: all pass. If `utilityExistence.test.ts` rejects `w-shell-sidebar` or a `shell-lg:` variant, read its allow-list logic and register the new utility/variant the way `w-sidebar`/`sidebar:` are registered (do not weaken the gate).

- [ ] **Step 13: Drift acceptance (teacher before/after) and behaviour**

```bash
npm run build
node scripts/shell-behaviour.mjs
node scripts/home-drift.mjs --scene teacher-
```

Expected: behaviour 3/3 pass. Drift: every `teacher-*-content` key `pass` (0 px; the page below the shell must not move or change). The `teacher-home-frame`, `teacher-class-frame`, `teacher-notifications-frame`, `teacher-bell`, `teacher-account`, `teacher-drawer`, `teacher-settings-*` keys now differ (the bar changed). Open each `.diff.png` in the report folder and confirm every changed region is the top bar, the bell panel or the account panel; anything else (sidebar, page content, dialog) is a bug to fix now. Then add one justification per changed scene id to `web/scripts/drift/justifications.json`, e.g.:

```json
{
  "teacher-home-frame": {
    "difference": "Top bar: 1px outline instead of ring, 21px/800 title, design A icons, dot instead of count badge, gear visible at every width",
    "justification": "Design A .as-bar, .as-title, .as-iconbtn, .as-dot (variant-a.css)",
    "approved": "pending"
  },
  "teacher-bell": {
    "difference": "Bell panel: 320px, 32px icon tiles, mono times (9:12/Wed/27 Oct), unread dot under time, design A footer",
    "justification": "Design A .as-pop-panel, .as-item, .as-pop-foot",
    "approved": "pending"
  },
  "teacher-account": {
    "difference": "Account panel: circle avatar, bare 18px icons instead of 40px tiles, 9px row padding",
    "justification": "Design A .as-pop-me, .as-ident, .as-links",
    "approved": "pending"
  }
}
```

Re-run `node scripts/home-drift.mjs --scene teacher-`. Expected: exit 0, no `fail`.

- [ ] **Step 14: Commit**

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/student-home-variants
FILES="web/src/index.css web/src/components/shell/shellStyles.ts web/src/components/shell/shellModel.ts web/src/components/shell/icons.tsx web/src/components/shell/ShellAvatar.tsx web/src/components/shell/NotificationsPanel.tsx web/src/components/shell/AccountPanel.tsx web/src/components/shell/ShellTopBar.tsx web/src/portals/teacher/index.tsx web/tests/unit/shellModel.test.ts web/scripts/drift/justifications.json"
/home/sico/Code/Lemely/.venv/bin/pre-commit run --files $FILES
git commit -S -m "feat(web): design A top bar and panels in the shared shell; teacher adopts it" -- $FILES
```

---

### Task 4: `ShellNavList`, `ShellTree`, `ShellSidebar`, drawer variant; teacher uses the sidebar

**Files:**
- Modify: `web/src/components/ui/nav-shells.tsx` (export `NavShellLink`; no behaviour change)
- Modify: `web/src/components/ui/nav-drawer.tsx` (add `variant?: "default" | "shell"`)
- Create: `web/src/components/shell/ShellNavList.tsx`, `web/src/components/shell/shellTree.ts`, `web/src/components/shell/ShellTree.tsx`, `web/src/components/shell/ShellSidebar.tsx`
- Modify: `web/src/portals/teacher/index.tsx` (`Sidebar`, `SidebarFooter`, `UserBlock`, `TeacherNav`, `ClassesNavSection` replaced)
- Create: `web/tests/unit/shellTree.test.ts`
- Modify: `web/tests/unit/navShells.test.ts`, `web/tests/unit/screenEntrance.test.ts`, `web/tests/unit/brandLockup.test.ts` (teacher entries only)
- Modify: `web/scripts/drift/checks-shell.mjs`, `web/scripts/drift/justifications.json`

**Interfaces:**
- Consumes: `NavShellItem` (`web/src/components/ui/nav-shells.tsx`), `ShellIcon`, `ShellAvatar`, `SHELL_FOCUS_RING`, `SHELL_ICON_BUTTON`.
- Produces:
  ```ts
  // nav-shells.tsx (now exported)
  export function NavShellLink(props: {
    item: NavShellItem
    className: (isActive: boolean) => string
    children: (isActive: boolean) => ReactNode
  }): JSX.Element
  // nav-drawer.tsx
  export interface NavDrawerProps { open: boolean; onClose: () => void; title: ReactNode; children: ReactNode; footer?: ReactNode; variant?: "default" | "shell" }
  // ShellNavList.tsx
  export const SHELL_ROW: string
  export const SHELL_LABEL: string
  export function ShellNavList(props: { items: readonly NavShellItem[]; className?: string }): JSX.Element
  // shellTree.ts
  export function initialOpenIds(rowIds: readonly string[], currentId: string | null, fallbackId?: string | null): Set<string>
  export function toggleOpen(open: ReadonlySet<string>, id: string): Set<string>
  export function openOnNavigate(open: ReadonlySet<string>, currentId: string | null): Set<string>
  // ShellTree.tsx
  export interface ShellTreeRow {
    id: string
    label: string
    /** Native tooltip, e.g. "Additional Mathematics · 0606". */
    title?: string
    /** Short mono text after the label (the CAIE code). */
    trailing?: string
    /** Right-most adornment (the grade ring). */
    adornment?: ReactNode
    children: NavShellItem[]
  }
  export interface ShellTreeProps {
    labelledBy: string
    rows: readonly ShellTreeRow[]
    /** The row the current route belongs to; it starts open. */
    currentId: string | null
    /** Opened when no row matches the route (Overview plan: today's session subject). */
    fallbackId?: string | null
    /** Shown instead of rows when there are none; null renders nothing. */
    empty?: ReactNode
  }
  export function ShellTree(props: ShellTreeProps): JSX.Element
  // ShellSidebar.tsx
  export interface ShellSidebarGroup { id: string; label: string; render: (labelId: string) => ReactNode }
  export interface ShellSidebarProps {
    variant: "rail" | "drawer"
    /** aria-label of the sidebar's single nav landmark. */
    navLabel: string
    homeTo: string
    /** aria-label of the wordmark link, e.g. "Lemely, overview". */
    homeLabel: string
    items: readonly NavShellItem[]
    groups?: readonly ShellSidebarGroup[]
    /** The foot's primary action (Upload). Hidden in the phone sheet, where the bottom bar has it. */
    footerAction?: ReactNode
    user: ReactNode
    /** Drawer only: renders the close button in the head. */
    onClose?: () => void
  }
  export type ShellSidebarContent = Omit<ShellSidebarProps, "variant" | "onClose">
  export function ShellSidebar(props: ShellSidebarProps): JSX.Element
  export function ShellUserBlock(props: { name: string; avatarUrl?: string | null; detail: string | null }): JSX.Element
  ```

Design A rule → Tailwind mapping for this task:

| Selector and values | Tailwind |
|---|---|
| `.as-side` sticky top 0, flex column, gap 16px, height 100dvh, padding `18px 12px 12px`, overflow-y auto, overscroll contain, `box-shadow: 1px 0 0 --border-subtle` (rtl mirrored), bg lowest, width 216px (grid column) | `sticky top-0 hidden h-dvh w-shell-sidebar flex-none flex-col gap-4 overflow-y-auto overscroll-contain bg-surface-container-lowest px-3 pt-[18px] pb-3 text-on-surface shadow-[1px_0_0_var(--color-outline-variant)] rtl:shadow-[-1px_0_0_var(--color-outline-variant)] shell-lg:flex` |
| `.as-side-head` flex, align start, space-between | `flex items-start justify-between` |
| `.as-wm` inline-flex, align end, self start, padding `2px 8px 8px`, radius chip, 32px; `.as-wm-clip` width 0.451em, height 1.1em | `inline-flex self-start rounded-chip px-2 pt-0.5 pb-2` around `<BrandLockup as="span" className="[--wm-size:32px] [&_svg]:w-[0.451em]" />` |
| `.as-list a` flex, center, gap 10px, padding `9px 10px`, radius chip, muted, 600 14px/1.3; current: primary-container/primary; list gap 1px | `flex w-full items-center gap-2.5 rounded-chip px-2.5 py-[9px] text-label` + `bg-primary-container text-primary` / `text-on-surface-variant hover:bg-surface-container hover:text-on-surface`; `flex flex-col gap-px` |
| `.as-lb` min-inline-size 0, `text-box: trim-both cap alphabetic` | `min-w-0 flex-1 [text-box:trim-both_cap_alphabetic]` |
| `.as-n` margin-inline-start auto, padding `1px 7px`, pill, surface-high, 600 11px mono tabular; hot/current: primary/on-primary | `ms-auto rounded-pill px-[7px] py-px font-mono text-[11px] font-semibold tabular-nums bg-surface-container-high text-on-surface` / `bg-primary text-on-primary` |
| `.as-label` margin `6px 10px -6px`, 600 11px mono, uppercase, 0.08em, muted | `mx-2.5 mt-1.5 -mb-1.5 text-eyebrow text-on-surface-variant` (`.text-eyebrow` is 600 11px mono uppercase in index.css) |
| `.as-subj` flex, gap 10px, full width, padding `6px 10px`, radius chip, on-surface, 600 14px/1.3, start | `flex w-full cursor-pointer items-center gap-2.5 rounded-chip px-2.5 py-1.5 text-start text-label text-on-surface hover:bg-surface-container` |
| `.as-chev` muted, rotate 90deg when expanded, mirrored in rtl | `text-on-surface-variant transition-transform duration-200 group-aria-expanded:rotate-90 rtl:-scale-x-100 rtl:group-aria-expanded:rotate-90` |
| `.as-code` margin-inline-start auto, 500 11px mono tabular, muted | `ms-auto font-mono text-[11px] font-medium tabular-nums text-on-surface-variant` |
| `.as-sub` padding-block 1px; links indented `10 + 18 + 10 = 38px` | `flex flex-col gap-px py-px`; `ps-[38px]` |
| `.as-subj-empty` padding `6px 10px`, 400 14px/1.45 muted | `px-2.5 py-1.5 text-body-sm text-on-surface-variant` |
| `.as-foot` column, gap 12px, margin-top auto, padding-top 16px, top border; `.as-foot .as-btn` centred | `mt-auto flex flex-col gap-3 border-t border-outline-variant pt-4` + `[&>*]:justify-center` |
| `.as-user` flex, center, gap 10px, padding-inline 2px; `b` 500 14px/1.45 ellipsis; `small` 400 14px/1.45 muted | `flex items-center gap-2.5 px-0.5`; `truncate text-body-sm font-medium text-on-surface`; `text-body-sm text-on-surface-variant` |
| `.as-side:popover-open` (drawer ≤1000): fixed, inset-block 10px, inset-inline-start 10px, width min(280px, 100vw-20px), radius card, `--shadow-panel` | NavDrawer shell panel: `fixed inset-y-2.5 start-2.5 w-[min(280px,calc(100vw-20px))] rounded-card shadow-[var(--shadow-panel)] bg-surface-container-lowest` |
| ≤720 sheet: inset-block `auto 0`, inline 0, full width, max-height 85dvh, padding `12px 12px calc(16px + safe-area)`, radius `card card 0 0`; wordmark hidden; foot button hidden | `max-shell-sm:inset-x-0 max-shell-sm:top-auto max-shell-sm:bottom-0 max-shell-sm:start-0 max-shell-sm:w-full max-shell-sm:max-h-[85dvh] max-shell-sm:rounded-b-none`; sidebar `max-shell-sm:pt-3 max-shell-sm:pb-[calc(1rem+env(safe-area-inset-bottom))]`, wordmark `max-shell-sm:invisible`, foot action `max-shell-sm:hidden` |
| `.as-side::backdrop` scrim | NavDrawer's existing `bg-scrim` |
| coarse pointer: rows 44px | `pointer-coarse:min-h-11` |

- [ ] **Step 1: Write the failing test `web/tests/unit/shellTree.test.ts`**

```ts
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it } from "vitest"
import { ShellTree } from "@/components/shell/ShellTree"
import { initialOpenIds, openOnNavigate, toggleOpen } from "@/components/shell/shellTree"

const ROWS = ["0580", "0606", "0625"]

describe("initialOpenIds", () => {
  it("opens the current route's row", () => {
    expect([...initialOpenIds(ROWS, "0606")]).toEqual(["0606"])
  })
  it("falls back to the fallback row when the route matches none", () => {
    expect([...initialOpenIds(ROWS, null, "0625")]).toEqual(["0625"])
    expect([...initialOpenIds(ROWS, "9999", "0625")]).toEqual(["0625"])
  })
  it("opens nothing when neither matches", () => {
    expect([...initialOpenIds(ROWS, null)]).toEqual([])
    expect([...initialOpenIds(ROWS, null, "9999")]).toEqual([])
  })
})

describe("toggleOpen (design A: each subject is its own disclosure)", () => {
  it("opens a closed row and keeps the others", () => {
    expect([...toggleOpen(new Set(["0580"]), "0606")].sort()).toEqual(["0580", "0606"])
  })
  it("closes an open row", () => {
    expect([...toggleOpen(new Set(["0580", "0606"]), "0580")]).toEqual(["0606"])
  })
  it("does not mutate its input", () => {
    const open = new Set(["0580"])
    toggleOpen(open, "0580")
    expect([...open]).toEqual(["0580"])
  })
})

describe("openOnNavigate", () => {
  it("opens the row the reader navigated into, without closing others", () => {
    expect([...openOnNavigate(new Set(["0580"]), "0625")].sort()).toEqual(["0580", "0625"])
  })
  it("never closes a row when the route leaves the subjects", () => {
    expect([...openOnNavigate(new Set(["0580"]), null)]).toEqual(["0580"])
  })
})

describe("ShellTree markup", () => {
  const rows = [
    {
      id: "0580",
      label: "Mathematics",
      title: "Mathematics · 0580",
      trailing: "0580",
      children: [{ id: "p", label: "Practice", to: "/student/practice/0580", icon: null }],
    },
    {
      id: "0606",
      label: "Add Maths",
      trailing: "0606",
      children: [{ id: "q", label: "Practice", to: "/student/practice/0606", icon: null }],
    },
  ]
  const html = renderToStaticMarkup(
    createElement(
      MemoryRouter,
      { initialEntries: ["/student/practice/0606"] },
      createElement(ShellTree, { labelledBy: "subj-h", rows, currentId: "0606" }),
    ),
  )

  it("labels the list by the group heading", () => {
    expect(html).toContain('aria-labelledby="subj-h"')
  })
  it("renders each row as a button that controls its own sub-list", () => {
    const buttons = html.match(/<button[^>]*>/g) ?? []
    expect(buttons).toHaveLength(2)
    for (const b of buttons) {
      expect(b).toContain('type="button"')
      expect(b).toMatch(/aria-controls="[^"]+"/)
    }
  })
  it("starts the current route's row expanded and the others collapsed (hidden sub-list)", () => {
    expect(html).toMatch(/aria-expanded="false"[^>]*title="Mathematics · 0580"|title="Mathematics · 0580"[^>]*aria-expanded="false"/)
    expect(html).toMatch(/<ul[^>]*hidden=""[^>]*>[\s\S]*?\/student\/practice\/0580/)
    expect(html).toContain('aria-expanded="true"')
  })
  it("renders the empty message when there are no rows", () => {
    const empty = renderToStaticMarkup(
      createElement(
        MemoryRouter,
        null,
        createElement(ShellTree, { labelledBy: "h", rows: [], currentId: null, empty: "Nothing here yet." }),
      ),
    )
    expect(empty).toContain("Nothing here yet.")
    expect(empty).not.toContain("<button")
  })
})
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd web && npx vitest run tests/unit/shellTree.test.ts`
Expected: FAIL, cannot resolve `@/components/shell/ShellTree`.

- [ ] **Step 3: Export `NavShellLink`**

In `web/src/components/ui/nav-shells.tsx` change `function NavShellLink(` to `export function NavShellLink(`. Nothing else.

- [ ] **Step 4: Create `web/src/components/shell/shellTree.ts`**

```ts
/*
 * Open-state rules for the sidebar's expandable group (student subjects).
 * Design A (variant-a.js `setSubject`) makes each row its own disclosure: any
 * number can be open. The current route's row starts open; navigating into a
 * row opens it and never closes another.
 */

export function initialOpenIds(
  rowIds: readonly string[],
  currentId: string | null,
  fallbackId: string | null = null,
): Set<string> {
  if (currentId && rowIds.includes(currentId)) return new Set([currentId])
  if (fallbackId && rowIds.includes(fallbackId)) return new Set([fallbackId])
  return new Set()
}

export function toggleOpen(open: ReadonlySet<string>, id: string): Set<string> {
  const next = new Set(open)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  return next
}

export function openOnNavigate(open: ReadonlySet<string>, currentId: string | null): Set<string> {
  const next = new Set(open)
  if (currentId) next.add(currentId)
  return next
}
```

- [ ] **Step 5: Create `web/src/components/shell/ShellNavList.tsx`**

```tsx
import { NavShellLink, type NavShellItem } from "@/components/ui/nav-shells"
import { cn } from "@/lib/utils"
import { SHELL_FOCUS_RING } from "./shellStyles"

/** `.as-list a` / `.as-sub a` */
export const SHELL_ROW =
  "flex w-full items-center gap-2.5 rounded-chip px-2.5 py-[9px] text-start text-label transition-colors duration-150 pointer-coarse:min-h-11 " +
  SHELL_FOCUS_RING

/** `.as-lb` */
export const SHELL_LABEL = "min-w-0 flex-1 [text-box:trim-both_cap_alphabetic]"

export function shellRowClass(active: boolean): string {
  return cn(
    SHELL_ROW,
    active ? "bg-primary-container text-primary" : "text-on-surface-variant hover:bg-surface-container hover:text-on-surface",
  )
}

/** Design A's nav rows. Links come from nav-shells' `NavShellLink` (react-router
 * `NavLink`, `viewTransition`, `aria-current="page"`). No landmark of its own:
 * the sidebar is the one `nav`. */
export interface ShellNavListProps {
  items: readonly NavShellItem[]
  className?: string
  id?: string
  hidden?: boolean
  "aria-labelledby"?: string
}

export function ShellNavList({ items, className, id, hidden, "aria-labelledby": labelledBy }: ShellNavListProps) {
  return (
    <ul
      id={id}
      hidden={hidden}
      aria-labelledby={labelledBy}
      className={cn("m-0 flex list-none flex-col gap-px p-0", hidden && "hidden", className)}
    >
      {items.map((item) => (
        <li key={item.id}>
          <NavShellLink item={item} className={shellRowClass}>
            {(active) => (
              <>
                {item.icon}
                <span className={SHELL_LABEL}>{item.label}</span>
                {item.badge !== undefined ? (
                  <span
                    className={cn(
                      "ms-auto rounded-pill px-[7px] py-px font-mono text-[11px] font-semibold tabular-nums",
                      active || item.urgent ? "bg-primary text-on-primary" : "bg-surface-container-high text-on-surface",
                    )}
                  >
                    {item.badge}
                  </span>
                ) : null}
              </>
            )}
          </NavShellLink>
        </li>
      ))}
    </ul>
  )
}
```

- [ ] **Step 6: Create `web/src/components/shell/ShellTree.tsx`**

```tsx
import { useEffect, useId, useState, type ReactNode } from "react"
import type { NavShellItem } from "@/components/ui/nav-shells"
import { cn } from "@/lib/utils"
import { ShellIcon } from "./icons"
import { ShellNavList } from "./ShellNavList"
import { initialOpenIds, openOnNavigate, toggleOpen } from "./shellTree"
import { SHELL_FOCUS_RING } from "./shellStyles"

export interface ShellTreeRow {
  id: string
  label: string
  title?: string
  trailing?: string
  adornment?: ReactNode
  children: NavShellItem[]
}

export interface ShellTreeProps {
  labelledBy: string
  rows: readonly ShellTreeRow[]
  currentId: string | null
  fallbackId?: string | null
  empty?: ReactNode
}

/** Design A `.as-subjects`: one disclosure button per row (`aria-expanded`,
 * `aria-controls`), its sub-links in a list that is `hidden` when closed.
 * Enter and Space toggle (native button). */
export function ShellTree({ labelledBy, rows, currentId, fallbackId = null, empty }: ShellTreeProps) {
  const baseId = useId()
  const rowIds = rows.map((r) => r.id)
  const [open, setOpen] = useState(() => initialOpenIds(rowIds, currentId, fallbackId))
  useEffect(() => {
    setOpen((prev) => openOnNavigate(prev, currentId && rowIds.includes(currentId) ? currentId : null))
    // rowIds is derived from rows; re-run when the route or the row set changes.
  }, [currentId, rowIds.join("|")]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <ul aria-labelledby={labelledBy} className="m-0 flex list-none flex-col gap-px p-0">
      {rows.length === 0 && empty ? (
        <li className="px-2.5 py-1.5 text-body-sm text-on-surface-variant">{empty}</li>
      ) : null}
      {rows.map((row) => {
        const expanded = open.has(row.id)
        const subId = `${baseId}-${row.id}`
        return (
          <li key={row.id}>
            <button
              type="button"
              aria-expanded={expanded}
              aria-controls={subId}
              title={row.title}
              onClick={() => setOpen((prev) => toggleOpen(prev, row.id))}
              className={cn(
                "group flex w-full cursor-pointer items-center gap-2.5 rounded-chip px-2.5 py-1.5 text-start text-label text-on-surface transition-colors duration-150 hover:bg-surface-container pointer-coarse:min-h-11",
                SHELL_FOCUS_RING,
              )}
            >
              <ShellIcon
                name="chev"
                className="text-on-surface-variant transition-transform duration-200 group-aria-expanded:rotate-90 rtl:-scale-x-100 rtl:group-aria-expanded:rotate-90"
              />
              <span className="min-w-0 flex-1 truncate [text-box:trim-both_cap_alphabetic]">{row.label}</span>
              {row.trailing ? (
                <small className="ms-auto font-mono text-[11px] font-medium tabular-nums text-on-surface-variant">
                  {row.trailing}
                </small>
              ) : null}
              {row.adornment}
            </button>
            <ShellNavList id={subId} hidden={!expanded} items={row.children} className="py-px [&_a]:ps-[38px]" />
          </li>
        )
      })}
    </ul>
  )
}
```

- [ ] **Step 7: Create `web/src/components/shell/ShellSidebar.tsx`**

```tsx
import { useId, type ReactNode } from "react"
import { Link } from "react-router-dom"
import { BrandLockup } from "@/components/ui/brand-lockup"
import type { NavShellItem } from "@/components/ui/nav-shells"
import { cn } from "@/lib/utils"
import { ShellIcon } from "./icons"
import { ShellAvatar } from "./ShellAvatar"
import { ShellNavList } from "./ShellNavList"
import { SHELL_FOCUS_RING, SHELL_ICON_BUTTON } from "./shellStyles"

export interface ShellSidebarGroup {
  id: string
  label: string
  render: (labelId: string) => ReactNode
}

export interface ShellSidebarProps {
  variant: "rail" | "drawer"
  navLabel: string
  homeTo: string
  homeLabel: string
  items: readonly NavShellItem[]
  groups?: readonly ShellSidebarGroup[]
  footerAction?: ReactNode
  user: ReactNode
  onClose?: () => void
}

export type ShellSidebarContent = Omit<ShellSidebarProps, "variant" | "onClose">

const RAIL =
  "lm-scroll sticky top-0 hidden h-dvh w-shell-sidebar flex-none overflow-y-auto overscroll-contain bg-surface-container-lowest px-3 pt-[18px] pb-3 shadow-[1px_0_0_var(--color-outline-variant)] rtl:shadow-[-1px_0_0_var(--color-outline-variant)] shell-lg:flex"

const DRAWER =
  "lm-scroll flex min-h-0 flex-1 overflow-y-auto overscroll-contain px-3 pt-[18px] pb-3 max-shell-sm:pt-3 max-shell-sm:pb-[calc(1rem+env(safe-area-inset-bottom))]"

function Group({ group }: { group: ShellSidebarGroup }) {
  const labelId = useId()
  return (
    <>
      <p id={labelId} className="mx-2.5 mt-1.5 -mb-1.5 text-eyebrow text-on-surface-variant">
        {group.label}
      </p>
      {group.render(labelId)}
    </>
  )
}

/** Design A `.as-side`: the sidebar is the portal's one `nav` landmark. The
 * rail is a sticky column from `shell-lg`; the drawer variant is the same
 * content inside `NavDrawer variant="shell"` (a floating drawer, a bottom
 * sheet on phones). */
export function ShellSidebar({ variant, navLabel, homeTo, homeLabel, items, groups, footerAction, user, onClose }: ShellSidebarProps) {
  const rail = variant === "rail"
  return (
    <nav aria-label={navLabel} className={cn("flex-col gap-4 text-on-surface", rail ? RAIL : DRAWER)}>
      <div className="flex items-start justify-between">
        <Link
          to={homeTo}
          aria-label={homeLabel}
          className={cn("inline-flex self-start rounded-chip px-2 pt-0.5 pb-2", SHELL_FOCUS_RING, !rail && "max-shell-sm:invisible")}
        >
          <BrandLockup as="span" className="[--wm-size:32px] [&_svg]:w-[0.451em]" />
        </Link>
        {onClose ? (
          <button type="button" onClick={onClose} aria-label="Close menu" className={SHELL_ICON_BUTTON}>
            <ShellIcon name="x" />
          </button>
        ) : null}
      </div>
      <ShellNavList items={items} />
      {groups?.map((group) => <Group key={group.id} group={group} />)}
      <div className="mt-auto flex flex-col gap-3 border-t border-outline-variant pt-4">
        {footerAction ? (
          <div className={cn("flex flex-col [&>*]:justify-center", !rail && "max-shell-sm:hidden")}>{footerAction}</div>
        ) : null}
        {user}
      </div>
    </nav>
  )
}

/** `.as-user`: who is signed in, under the foot's action. */
export function ShellUserBlock({ name, avatarUrl, detail }: { name: string; avatarUrl?: string | null; detail: string | null }) {
  return (
    <div className="flex items-center gap-2.5 px-0.5">
      <ShellAvatar name={name} src={avatarUrl} />
      <span className="flex min-w-0 flex-col">
        <b className="truncate text-body-sm font-medium text-on-surface">{name}</b>
        {detail ? <small className="text-body-sm text-on-surface-variant">{detail}</small> : null}
      </span>
    </div>
  )
}
```

- [ ] **Step 8: Add `variant="shell"` to `NavDrawer`**

In `web/src/components/ui/nav-drawer.tsx`: add `variant?: "default" | "shell"` to `NavDrawerProps` (doc: "`shell`: design A's floating drawer, a bottom sheet below 721px; the children supply their own head and close button") and to the destructured props (`variant = "default"`). Replace the panel's `className={cn(…)}` with:

```tsx
className={cn(
  variant === "shell"
    ? "lm-nav-chrome fixed inset-y-2.5 start-2.5 z-modal flex w-[min(280px,calc(100vw-20px))] flex-col rounded-card bg-surface-container-lowest text-on-surface shadow-[var(--shadow-panel)] max-shell-sm:inset-x-0 max-shell-sm:top-auto max-shell-sm:bottom-0 max-shell-sm:start-0 max-shell-sm:w-full max-shell-sm:max-h-[85dvh] max-shell-sm:rounded-b-none"
    : cn(
        "lm-nav-chrome fixed inset-y-0 start-0 z-modal flex w-[min(20rem,85vw)] flex-col gap-5",
        "border-e border-outline-variant bg-surface-container-lowest px-4 py-5 shadow-[var(--shadow-float)]",
      ),
  phase === "closing"
    ? "lm-slide-out-start"
    : "motion-safe:animate-[lm-slide-in-start_var(--dur-base)_var(--ease-spring)_both]",
)}
```

and replace the header + children + footer block with:

```tsx
{variant === "shell" ? (
  <>
    <h2 id={titleId} className="sr-only">
      {title}
    </h2>
    {children}
  </>
) : (
  <>
    {/* existing header row, children wrapper and footer, unchanged */}
  </>
)}
```

(keep the existing three blocks verbatim inside the `default` branch). Focus handling, Escape, scrim, scroll lock, history and the swipe-to-close are unchanged and apply to both variants; the closing animation classes are shared so `onAnimationEnd` still fires.

- [ ] **Step 9: Teacher uses `ShellSidebar` in its rail and drawer**

In `web/src/portals/teacher/index.tsx`, delete `Sidebar`, `SidebarFooter`, `UserBlock`, `TeacherNav` and the `SidebarNav` / `BrandLockup` / `Avatar` imports they alone used. Rename `ClassesNavSection` to `ClassesNavList({ labelledBy }: { labelledBy: string })` (first `grep -rn "ClassesNavSection" web/src web/tests`; expect only this file) and in it: delete the `"Your classes"` heading `<div>` (the shell renders the group label), and make its outer element `<div aria-labelledby={labelledBy} className="flex flex-col gap-px">`. Leave its rows' classes unchanged (teacher class rows have no design A reference; log). Add:

```tsx
import { ShellSidebar, ShellUserBlock, type ShellSidebarContent } from "@/components/shell/ShellSidebar"
import { ShellNavList } from "@/components/shell/ShellNavList"
import { profileName } from "@/components/shell/ShellAvatar"

const NAV_ICON: Record<NavItem["icon"], ReactNode> = {
  overview: <ShellIcon name="home" />,
  grading: <FileText size={18} aria-hidden="true" />,
  review: <SealQuestion size={18} aria-hidden="true" />,
  classes: <ShellIcon name="class" />,
  atRisk: <Warning size={18} aria-hidden="true" />,
  schemes: <Books size={18} aria-hidden="true" />,
  quizzes: <Sparkle size={18} aria-hidden="true" />,
  tutoring: <GraduationCap size={18} aria-hidden="true" />,
  announcements: <ShellIcon name="mega" />,
  notifications: <ShellIcon name="bell" />,
  settings: <Gear size={18} aria-hidden="true" />,
  deleted: <ShellIcon name="trash" />,
}
```

(replacing the old `NAV_ICON: Record<…, Icon>`; `toNavShellItem` now uses `icon: NAV_ICON[item.icon]`, keeping its `options` and the `item.badge === "review-queue"` mapping exactly), and:

```tsx
/** The teacher sidebar's content; the shell renders it as the rail and the drawer. */
function useTeacherSidebar(): ShellSidebarContent {
  const location = useLocation()
  const { data } = useTeacherClasses()
  const visibleClassIds = data?.classes.slice(0, 5).map((c) => c.id) ?? []
  const reviewQueueCount = useReviewQueueCount()
  const reviewBadge = reviewQueueCount && reviewQueueCount > 0 ? reviewQueueCount : undefined
  const profile = useProfile()
  const toShell = (item: NavItem) =>
    toNavShellItem(item, {
      forceActive: item.to === "/teacher/classes" ? classesItemActive(location.pathname, visibleClassIds) : undefined,
      badge: item.badge === "review-queue" ? reviewBadge : undefined,
      urgent: item.badge === "review-queue",
    })
  return {
    navLabel: "Teacher",
    homeTo: "/teacher",
    homeLabel: "Lemely, overview",
    items: navItems.filter((i) => SIDEBAR_PRIMARY.includes(i.icon)).map(toShell),
    groups: [
      { id: "classes", label: "Your classes", render: (labelId) => <ClassesNavList labelledBy={labelId} /> },
      {
        id: "tools",
        label: "Tools",
        render: (labelId) => (
          <ShellNavList aria-labelledby={labelId} items={navItems.filter((i) => SIDEBAR_TOOLS.includes(i.icon)).map(toShell)} />
        ),
      },
    ],
    footerAction: (
      <Link to="/teacher/grading" className={SHELL_BUTTON_PRIMARY}>
        <ShellIcon name="up" />
        Upload papers
      </Link>
    ),
    user: profile.data ? (
      <ShellUserBlock name={profileName(profile.data)} avatarUrl={profile.data.avatarUrl} detail={roleLabel(profile.data.role)} />
    ) : (
      <p className="px-0.5 text-body-sm text-on-surface-variant">{profile.isPending ? "Loading…" : "Signed in"}</p>
    ),
  }
}
```

In `TeacherLayout`:

```tsx
const sidebar = useTeacherSidebar()
…
<ShellSidebar variant="rail" {...sidebar} />
<NavDrawer variant="shell" open={navOpen} onClose={() => setNavOpen(false)} title="Lemely">
  <ShellSidebar variant="drawer" {...sidebar} onClose={() => setNavOpen(false)} />
</NavDrawer>
```

The rest of `TeacherLayout` (top bar, main, bottom nav) is unchanged in this task. Note the rail is now hidden below 1001px (it was hidden below 820px): between 820 and 1000px the teacher gets the menu button and drawer, as design A.

- [ ] **Step 10: Update the teacher entries of the pinned tests**

- `web/tests/unit/navShells.test.ts`, describe "every portal shell imports SidebarNav": change `PORTALS` to `["portals/admin/index.tsx"]` and add:

```ts
describe("student and teacher render the shared shell sidebar", () => {
  it("teacher/index.tsx imports from components/shell", () => {
    expect(read("portals/teacher/index.tsx")).toMatch(/from\s+"@\/components\/shell\//)
  })

  it("ShellNavList renders its rows through nav-shells' NavShellLink", () => {
    const source = stripComments(read("components/shell/ShellNavList.tsx"))
    expect(source).toMatch(/import\s*\{[^}]*\bNavShellLink\b[^}]*\}\s*from\s*"@\/components\/ui\/nav-shells"/)
  })

  it("ShellSidebar is one nav landmark", () => {
    const source = stripComments(read("components/shell/ShellSidebar.tsx"))
    expect(source.match(/<nav\b/g)).toHaveLength(1)
    expect(source).toContain("aria-label={navLabel}")
  })
})
```

- `web/tests/unit/screenEntrance.test.ts`, the `it.each(["src/portals/teacher/index.tsx", "src/portals/admin/index.tsx"])` block: change the list to `["src/portals/admin/index.tsx"]` and add:

```ts
it("the shell sidebar renders through ShellNavList, which uses nav-shells' NavLink (viewTransition)", () => {
  expect(sourceOf("src/components/shell/ShellNavList.tsx")).toContain("NavShellLink")
  expect(sourceOf("src/components/ui/nav-shells.tsx")).toContain("viewTransition")
})
```

- `web/tests/unit/brandLockup.test.ts`: in `LOCKUP_SITES` replace `"src/portals/teacher/index.tsx"` with `"src/components/shell/ShellSidebar.tsx"` (the student entry is replaced in Task 6).

- [ ] **Step 11: Append drawer behaviour checks to `web/scripts/drift/checks-shell.mjs`**

```js
async function openNavFromMore(page) {
  const more = page.getByRole("button", { name: "More", exact: true })
  await more.click()
  const dialog = page.getByRole("dialog")
  await dialog.waitFor()
  return { more, dialog }
}

SHELL_CHECKS.push(
  {
    id: "teacher-drawer-traps-focus-and-escape-returns",
    width: 768,
    app: TEACHER_HOME,
    async run(page) {
      const { more, dialog } = await openNavFromMore(page)
      for (let i = 0; i < 40; i++) {
        await page.keyboard.press("Tab")
        const inside = await dialog.evaluate((el) => el.contains(document.activeElement))
        if (!inside) throw new Error(`drawer: focus left the dialog after ${i + 1} Tab presses`)
      }
      await page.keyboard.press("Shift+Tab")
      if (!(await dialog.evaluate((el) => el.contains(document.activeElement)))) throw new Error("drawer: Shift+Tab escaped")
      await page.keyboard.press("Escape")
      await assertHidden(dialog, "drawer")
      await assertFocused(more, "More tab")
    },
  },
  {
    id: "teacher-drawer-has-one-labelled-nav",
    width: 768,
    app: TEACHER_HOME,
    async run(page) {
      const { dialog } = await openNavFromMore(page)
      const navs = await dialog.locator("nav[aria-label]").count()
      if (navs !== 1) throw new Error(`drawer: expected 1 labelled nav, found ${navs}`)
      await page.getByRole("button", { name: "Close menu" }).click()
      await assertHidden(dialog, "drawer via Close menu")
    },
  },
  {
    id: "teacher-rail-is-one-labelled-nav",
    width: 1440,
    app: TEACHER_HOME,
    async run(page) {
      const navs = await page.locator('nav[aria-label="Teacher"]').count()
      if (navs !== 1) throw new Error(`rail: expected 1 nav labelled Teacher, found ${navs}`)
    },
  },
)
```

- [ ] **Step 12: Run tests, behaviour, drift**

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/student-home-variants/web
npx vitest run tests/unit/shellTree.test.ts tests/unit/shellModel.test.ts tests/unit/shellPanels.test.ts tests/unit/navShells.test.ts tests/unit/screenEntrance.test.ts tests/unit/brandLockup.test.ts tests/unit/navigation.test.ts tests/unit/reviewBadge.test.ts tests/unit/a11yRules.test.ts tests/unit/rtlSafety.test.ts tests/unit/utilityExistence.test.ts tests/unit/motionDefaults.test.ts tests/unit/nativeMechanics.test.ts tests/unit/checkNativeInvariants.test.ts
npm run typecheck && npx oxlint src/components src/portals/teacher && npm run check:native
npm run build
node scripts/shell-behaviour.mjs
node scripts/home-drift.mjs --scene teacher-
```

Expected: all pass; 6 behaviour checks pass; drift content keys 0 px (if a `teacher-*-content` key fails, the page reflowed: the content-width matcher should absorb a narrower sidebar, so a failure means real content drift; read the diff and fix). Frame and drawer keys differ: confirm from the diff images that only the sidebar, the drawer and the earlier top-bar areas changed, then update the justifications, e.g.:

```json
"teacher-home-frame": {
  "difference": "Top bar (Task 3); sidebar 216px, design A rows (9px 10px, 18px icons), group labels, wordmark 32px, foot with primary Upload and circle avatar; sidebar becomes a drawer below 1001px",
  "justification": "Design A .as-bar, .as-side, .as-list, .as-label, .as-wm, .as-foot, .as-user; drawer range @container ashell (max-width: 1000px)",
  "approved": "pending"
},
"teacher-drawer": {
  "difference": "Floating 280px drawer with 24px radius (bottom sheet at 390px) instead of a full-height edge drawer; wordmark head with close button",
  "justification": "Design A .as-side:popover-open and its max-width 720px sheet rule",
  "approved": "pending"
}
```

Re-run until the command exits 0.

- [ ] **Step 13: Commit**

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/student-home-variants
FILES="web/src/components/ui/nav-shells.tsx web/src/components/ui/nav-drawer.tsx web/src/components/shell/ShellNavList.tsx web/src/components/shell/shellTree.ts web/src/components/shell/ShellTree.tsx web/src/components/shell/ShellSidebar.tsx web/src/portals/teacher/index.tsx web/tests/unit/shellTree.test.ts web/tests/unit/navShells.test.ts web/tests/unit/screenEntrance.test.ts web/tests/unit/brandLockup.test.ts web/scripts/drift/checks-shell.mjs web/scripts/drift/justifications.json"
/home/sico/Code/Lemely/.venv/bin/pre-commit run --files $FILES
git commit -S -m "feat(web): design A sidebar, subject tree and drawer in the shared shell; teacher adopts the sidebar" -- $FILES
```

---

### Task 5: `PortalShell` layout; teacher layout replaced

**Files:**
- Create: `web/src/components/shell/PortalShell.tsx`
- Modify: `web/src/portals/teacher/index.tsx` (`TeacherLayout` becomes a `PortalShell` call; `TeacherTopBar` helper folds into it)
- Modify: `web/tests/unit/navShells.test.ts`, `web/tests/unit/offlineBanner.test.ts`, `web/tests/unit/outletBoundary.test.ts`, `web/tests/unit/screenEntrance.test.ts` (teacher entries only)
- Modify: `web/scripts/drift/justifications.json`

**Interfaces:**
- Consumes: `ShellSidebarContent`, `ShellSidebar`, `ShellTopBarProps`, `ShellTopBar`, `NavDrawer` (`variant="shell"`), `BottomNav`, `NavShellItem`, `ScreenOverlay` (`web/src/components/ui/screen-outlet.tsx`), `ScreenOutlet`, `SkipLink`, `MAIN_CONTENT_ID`, `BadgeSync`, `EdgeSwipeBack`, `OfflineBanner`, `VerifyEmailBanner`, `InstallBanner`, `RouteSkeleton`, `ErrorBoundary`, `portalErrorFallback`.
- Produces:
  ```ts
  export interface PortalShellProps {
    portal: "student" | "teacher"
    sidebar: ShellSidebarContent
    topBar: Omit<ShellTopBarProps, "onOpenNav">
    /** Route tabs for the phone bar; the shell appends "More", which opens the drawer. */
    bottomTabs: NavShellItem[]
    bottomEmphasisId?: string
    /** Accessible name of the drawer dialog. */
    drawerTitle: string
    /** The portal's gate query is pending: the content slot shows RouteSkeleton. */
    pending: boolean
    /** Settings-as-dialog wiring for ScreenOutlet. */
    overlay?: ScreenOverlay
  }
  export function PortalShell(props: PortalShellProps): JSX.Element
  ```

Design A rule → Tailwind mapping for this task:

| Selector and values | Tailwind |
|---|---|
| `.as-app` grid `216px 1fr`, min-height 100dvh, bg `--md-surface-container` | `flex min-h-dvh bg-surface-container` (rail is the 216px flex item) |
| `.as-col` column, min-inline-size 0 | `flex min-w-0 flex-1 flex-col` |
| `.as-main` container `home`, padding `4px 72px 40px`, no max width | `@container/home w-full min-w-0 flex-1 px-[72px] pt-1 pb-10` |
| ≤1000: `.as-main` padding `4px 14px 36px` | `max-shell-lg:px-3.5 max-shell-lg:pb-9` |
| ≤720: `.as-main` padding `4px 14px 32px` | not used: below 820px `max-sidebar:pb-bottom-nav` must win so the fixed `BottomNav` never covers content (approved drift). Do not add `max-shell-sm:pb-8`: Tailwind orders the smaller max breakpoint later, so it would override the clearance. |
| `.as-main:focus` no outline | `focus:outline-none` |
| `.as-skip` | existing `SkipLink` (same behaviour; style difference logged) |

- [ ] **Step 1: Write the failing source test (in `navShells.test.ts`)**

Replace the teacher half of describe "student and teacher shells mount BottomNav with the five labels in order" with:

```ts
it("PortalShell mounts BottomNav and appends More after the portal's tabs", () => {
  const source = stripComments(read("components/shell/PortalShell.tsx"))
  expect(source).toMatch(/import\s*\{[^}]*\bBottomNav\b[^}]*\}\s*from\s*"@\/components\/ui\/nav-shells"/)
  expect(source).toMatch(/\.\.\.bottomTabs[\s\S]*"More"/)
})

it("teacher/index.tsx passes its four tabs to PortalShell in order", () => {
  const source = stripComments(read("portals/teacher/index.tsx"))
  expect(source).toMatch(/<PortalShell\b/)
  expect(source).toMatch(/"Overview"[\s\S]*"Grading"[\s\S]*"Review"[\s\S]*"Classes"/)
})
```

Run: `cd web && npx vitest run tests/unit/navShells.test.ts`
Expected: FAIL (`PortalShell.tsx` does not exist).

- [ ] **Step 2: Create `web/src/components/shell/PortalShell.tsx`**

```tsx
import { Suspense, useState } from "react"
import { useLocation } from "react-router-dom"
import { useQueryClient } from "@tanstack/react-query"
import { List } from "@phosphor-icons/react"
import { BadgeSync } from "@/components/badge-sync"
import { EdgeSwipeBack } from "@/components/edge-swipe-back"
import { InstallBanner } from "@/components/InstallBanner"
import { portalErrorFallback } from "@/components/route-error"
import { ErrorBoundary } from "@/components/ui/error-boundary"
import { NavDrawer } from "@/components/ui/nav-drawer"
import { BottomNav, type NavShellItem } from "@/components/ui/nav-shells"
import { OfflineBanner } from "@/components/ui/offline-banner"
import { RouteSkeleton } from "@/components/ui/route-skeleton"
import { ScreenOutlet, type ScreenOverlay } from "@/components/ui/screen-outlet"
import { MAIN_CONTENT_ID, SkipLink } from "@/components/ui/skip-link"
import { VerifyEmailBanner } from "@/components/ui/verify-email-banner"
import { ShellSidebar, type ShellSidebarContent } from "./ShellSidebar"
import { ShellTopBar, type ShellTopBarProps } from "./ShellTopBar"

export interface PortalShellProps {
  portal: "student" | "teacher"
  sidebar: ShellSidebarContent
  topBar: Omit<ShellTopBarProps, "onOpenNav">
  bottomTabs: NavShellItem[]
  bottomEmphasisId?: string
  drawerTitle: string
  pending: boolean
  overlay?: ScreenOverlay
}

/**
 * The frame around every student and teacher page (design A `.as-app`): the
 * sidebar column from `shell-lg`, the same sidebar as a drawer below it, the
 * floating top bar, the page well, and the phone tab bar below the `sidebar`
 * breakpoint (approved drift: design A's own phone bar differs).
 *
 * `<main>` holds only what the route rendered, so the skip link skips the
 * navigation. One error boundary around the outlet keeps the shell painted
 * when a screen crashes; `resetKey` clears it on navigation. A pending gate
 * query shows the same RouteSkeleton a chunk load does.
 */
export function PortalShell({ portal, sidebar, topBar, bottomTabs, bottomEmphasisId, drawerTitle, pending, overlay }: PortalShellProps) {
  const [navOpen, setNavOpen] = useState(false)
  const location = useLocation()
  const queryClient = useQueryClient()
  const closeNav = () => setNavOpen(false)
  return (
    <div data-portal={portal} className="flex min-h-dvh bg-surface-container">
      <SkipLink />
      <BadgeSync />
      <ShellSidebar variant="rail" {...sidebar} />
      <NavDrawer variant="shell" open={navOpen} onClose={closeNav} title={drawerTitle}>
        <ShellSidebar variant="drawer" {...sidebar} onClose={closeNav} />
      </NavDrawer>
      <EdgeSwipeBack />
      <div className="flex min-w-0 flex-1 flex-col">
        <ShellTopBar {...topBar} onOpenNav={() => setNavOpen(true)} />
        <main
          id={MAIN_CONTENT_ID}
          tabIndex={-1}
          className="@container/home w-full min-w-0 flex-1 overflow-x-hidden px-[72px] pt-1 pb-10 focus:outline-none max-shell-lg:px-3.5 max-shell-lg:pb-9 max-sidebar:pb-bottom-nav"
        >
          <OfflineBanner
            onRetry={() =>
              void queryClient.refetchQueries({ type: "active", predicate: (query) => query.state.status === "error" })
            }
          />
          <VerifyEmailBanner />
          <InstallBanner />
          {pending ? (
            <RouteSkeleton />
          ) : (
            <Suspense fallback={<RouteSkeleton />}>
              <ErrorBoundary label="This page" resetKey={location.pathname} fallback={portalErrorFallback}>
                <ScreenOutlet overlay={overlay} />
              </ErrorBoundary>
            </Suspense>
          )}
        </main>
      </div>
      <BottomNav
        items={[
          ...bottomTabs,
          {
            id: "more",
            label: "More",
            icon: <List size={22} aria-hidden="true" />,
            onClick: () => setNavOpen(true),
          },
        ]}
        emphasisId={bottomEmphasisId}
        className="sidebar:hidden"
      />
    </div>
  )
}
```

(`ScreenOutlet` accepts `{ overlay?: ScreenOverlay }` on `develop`; passing `undefined` renders the plain outlet. `max-sidebar:` is Tailwind's max variant of the existing `--breakpoint-sidebar`.)

- [ ] **Step 3: Replace `TeacherLayout`**

```tsx
function TeacherLayout() {
  const location = useLocation()
  // Same query the class list subscribes to (deduped by key); a pending list
  // shows the skeleton inside the shell. A zero-class teacher sees setup on home.
  const classesQuery = useTeacherClasses()
  // Shares its request with the sidebar's own subscriber (same query key).
  const reviewQueueCount = useReviewQueueCount()
  const { data: profile } = useProfile()
  const sidebar = useTeacherSidebar()
  const trail = resolveTrail(
    underlyingPathname({ pathname: location.pathname, state: location.state, overlayBase: TEACHER_SETTINGS_BASE }),
  )
  return (
    <PortalShell
      portal="teacher"
      drawerTitle="Lemely"
      pending={classesQuery.isPending}
      overlay={{ routes: teacherContentRoutes(), overlayBase: TEACHER_SETTINGS_BASE, fallbackPath: "/teacher" }}
      sidebar={sidebar}
      topBar={{
        title: trail[trail.length - 1]?.label ?? "Overview",
        trail,
        navLabel: "Open teacher navigation",
        actions: <TeacherTopBarActions />,
        notifications: TEACHER_NOTIFICATIONS_PANEL,
        settingsTo: TEACHER_SETTINGS_BASE,
        account: { links: TEACHER_ACCOUNT_LINKS, detail: profile ? roleLabel(profile.role) : null },
      }}
      bottomTabs={TEACHER_BOTTOM_TABS.map(
        (tab): NavShellItem => ({
          id: tab.id,
          to: tab.to,
          end: tab.end,
          label: tab.label,
          icon: <tab.icon size={22} aria-hidden="true" />,
          badge: tab.id === "review" && reviewQueueCount && reviewQueueCount > 0 ? reviewQueueCount : undefined,
        }),
      )}
    />
  )
}
```

Delete `TeacherTopBar` and every import only the old layout used (`OfflineBanner`, `VerifyEmailBanner`, `InstallBanner`, `BadgeSync`, `RouteSkeleton`, `ScreenOutlet`, `ErrorBoundary`, `portalErrorFallback`, `NavDrawer`, `BottomNav`, `EdgeSwipeBack`, `SkipLink`, `MAIN_CONTENT_ID`, `List`, `useState`, `useQueryClient`, `ShellSidebar`, `ShellTopBar`). Keep `TEACHER_BOTTOM_TABS` exported (navigation.test imports it) and `teacherRoute` unchanged.

- [ ] **Step 4: Update the other pinned lists (teacher entry → `PortalShell.tsx`)**

In each of these, replace `"src/portals/teacher/index.tsx"` with `"src/components/shell/PortalShell.tsx"`; leave the student entry (Task 6 removes it): `web/tests/unit/offlineBanner.test.ts` (`PORTAL_LAYOUTS`), `web/tests/unit/outletBoundary.test.ts` (`PORTAL_LAYOUTS`), `web/tests/unit/screenEntrance.test.ts` (the `PORTAL_LAYOUTS` inside "every portal layout renders <ScreenOutlet instead of a bare <Outlet"). Add a one-line comment above each list: `// The student and teacher layouts are components/shell/PortalShell.tsx (portal shell spec).`

- [ ] **Step 5: Run tests**

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/student-home-variants/web
npx vitest run tests/unit/navShells.test.ts tests/unit/offlineBanner.test.ts tests/unit/outletBoundary.test.ts tests/unit/screenEntrance.test.ts tests/unit/routeSkeleton.test.ts tests/unit/navigation.test.ts tests/unit/reviewBadge.test.ts tests/unit/settingsTabs.test.ts tests/unit/teacherTopBarSheets.test.ts tests/unit/teacherRedirect.test.ts tests/unit/notFoundFallback.test.ts tests/unit/shellTree.test.ts tests/unit/shellModel.test.ts tests/unit/shellPanels.test.ts tests/unit/a11yRules.test.ts tests/unit/utilityExistence.test.ts tests/unit/rtlSafety.test.ts
npm run typecheck && npx oxlint src/components src/portals/teacher
```

Expected: all pass.

- [ ] **Step 6: Behaviour and drift acceptance**

```bash
npm run build
node scripts/shell-behaviour.mjs
node scripts/home-drift.mjs --scene teacher-
```

Expected: 6 behaviour checks pass; content keys 0 px; frame keys show the page ground (`surface` → `surface-container`) and gutter changes on top of Tasks 3 and 4. Confirm from the diffs, then extend each teacher frame justification's `difference` with "page ground surface-container; main padding 4px 72px 40px (14px below 1001px), no 1600px cap" and its `justification` with "Design A .as-app, .as-main". Re-run until exit 0.

- [ ] **Step 7: Commit**

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/student-home-variants
FILES="web/src/components/shell/PortalShell.tsx web/src/portals/teacher/index.tsx web/tests/unit/navShells.test.ts web/tests/unit/offlineBanner.test.ts web/tests/unit/outletBoundary.test.ts web/tests/unit/screenEntrance.test.ts web/scripts/drift/justifications.json"
/home/sico/Code/Lemely/.venv/bin/pre-commit run --files $FILES
git commit -S -m "feat(web): PortalShell layout; teacher portal renders inside it" -- $FILES
```

---

### Task 6: Student shell (nav, subject tree, footer, top bar, account links, bottom tabs) vs design A

The old student shell code is deleted in this task, not later: once `StudentLayout` renders `PortalShell`, `Sidebar`, `Header`, `UserBlock`, `HeaderStreak`, `NavRow`, `SubjectNavGroup` and `NavGroups` have no callers and fail lint/typecheck as unused.

**Files:**
- Create: `web/src/portals/student/shell.tsx`, `web/src/portals/student/GradeRing.tsx`, `web/src/lib/studentInbox.ts`
- Modify: `web/src/portals/student/data.ts`, `web/src/portals/student/index.tsx`, `web/src/portals/student/screens/Notifications.tsx`
- Create: `web/tests/unit/studentShell.test.ts`
- Modify: `web/tests/unit/navShells.test.ts`, `streakChip.test.ts`, `subjectGlyph.test.ts`, `screenEntrance.test.ts`, `offlineBanner.test.ts`, `outletBoundary.test.ts`, `brandLockup.test.ts` (student entries)
- Modify: `web/scripts/drift/mocks.mjs`, `web/scripts/drift/scenes-shell.mjs`, `web/scripts/drift/checks-shell.mjs`, `web/scripts/drift/justifications.json`

**Interfaces:**
- Consumes: `PortalShell`, `PortalShellProps`, `ShellTree`, `ShellTreeRow`, `ShellUserBlock`, `ShellIcon`, `ShellIconName`, `SHELL_BUTTON_PRIMARY`, `AccountLink`, `NotificationsPanelProps`, `profileName`, `qualificationLevelLabel` (`web/src/lib/qualificationLevels.ts`), `resolveCrumbTrail`, `currentSubjectCode` (`portals/student/data.ts`), `prefetchOnIntent` (`web/src/lib/prefetchOnIntent.ts`).
- Produces:
  ```ts
  // portals/student/data.ts
  export interface NavItem { to: string; label: string; tag?: string; end?: boolean; icon: ShellIconName | Icon }
  export const studentNavItems: NavItem[]
  export const studentAccountLinks: NavItem[]
  export const studentInboxLinks: NavItem[]
  export const STUDENT_INBOX_EMPTY: string
  export const navGroups: NavGroup[]          // every destination the student shell links to
  export function studentShellTrail(pathname: string): Crumb[]
  export function studentPageTitle(pathname: string, subjects?: readonly { code: string; name: string }[]): string
  export function studentDetailLine(qualificationLabel: string | null, subjectCount: number): string
  // lib/studentInbox.ts
  export function studentDestinationFor(notification: Pick<Notification, "type" | "payload">): string | null
  // portals/student/GradeRing.tsx
  export function GradeRing(props: { grade: string; pct: number }): JSX.Element
  // portals/student/shell.tsx
  export const STUDENT_SETTINGS_BASE = "/student/settings"
  export const STUDENT_BOTTOM_TABS: readonly { id: string; label: string; to: string; end?: boolean; icon: Icon }[]
  export interface StudentShellProps {
    pending: boolean
    prefetchCorrectPaper: ReturnType<typeof prefetchOnIntent>
    overlay?: ScreenOverlay
  }
  export function StudentShell(props: StudentShellProps): JSX.Element
  ```
  `portals/student/index.tsx` keeps exporting `STUDENT_BOTTOM_TABS` (re-export from `./shell`), `studentRoute`, `studentOnboardingRedirect`.

Grade ring mapping (`variant-a.css` line 1701 onward):

| Selector and values | Tailwind |
|---|---|
| `.as-side .as-ring` grid, 28px, pill, `conic-gradient(var(--ring) var(--p), var(--md-surface-high) 0)`, 800 11px/1, on-surface, relative | `relative grid size-7 flex-none place-items-center rounded-pill text-[11px] font-extrabold leading-none text-on-surface` + inline `style={{ background: conic-gradient(…) }}` (the percentage is data, so it is the one inline style) |
| `::before` inset 3px, inherit radius, `--surface-card` | `before:absolute before:inset-[3px] before:rounded-pill before:bg-surface-container-lowest dark:before:bg-surface-container-high` |
| `[data-grade="A"]` etc. → `--sh-grade-a` = app `--grade-a` | `var(--color-grade-a)` (A*, A, B, C, D, E) |

- [ ] **Step 1: Write the failing test `web/tests/unit/studentShell.test.ts`**

```ts
import { describe, expect, it } from "vitest"
import {
  STUDENT_INBOX_EMPTY,
  studentAccountLinks,
  studentDetailLine,
  studentInboxLinks,
  studentNavItems,
  studentPageTitle,
  studentShellTrail,
} from "@/portals/student/data"
import { studentRoute, STUDENT_BOTTOM_TABS } from "@/portals/student"
import { studentDestinationFor } from "@/lib/studentInbox"

const studentRoutePaths = (studentRoute.children ?? []).flatMap((child) => {
  const base = child.index ? "/student" : `/student/${(child as { path: string }).path}`
  const nested = (child.children ?? []).map((grand) =>
    grand.index ? base : `${base}/${(grand as { path: string }).path}`,
  )
  return [base, ...nested]
})
const mounted = (to: string) =>
  studentRoutePaths.some((p) => new RegExp(`^${p.replace(/:[^/]+/g, "[^/]+")}$`).test(to))

describe("student shell destinations (design A)", () => {
  it("leads the sidebar with design A's four rows, in order", () => {
    expect(studentNavItems.slice(0, 4).map((i) => i.label)).toEqual([
      "Overview",
      "Your classes",
      "Standings",
      "Friends",
    ])
  })

  it("puts Your profile, Your parents and Recently deleted in the account panel", () => {
    expect(studentAccountLinks.map((l) => [l.label, l.to])).toEqual([
      ["Your profile", "/student/profile"],
      ["Your parents", "/student/parents"],
      ["Recently deleted", "/student/recently-deleted"],
    ])
  })

  it("links the bell panel's footer to the inbox and announcements", () => {
    expect(studentInboxLinks.map((l) => l.to)).toEqual(["/student/notifications", "/student/announcements"])
  })

  it.each([...studentNavItems, ...studentAccountLinks, ...studentInboxLinks].map((i) => [i.label, i.to]))(
    "%s (%s) is a mounted student route",
    (_label, to) => {
      expect(mounted(to)).toBe(true)
    },
  )

  it("keeps today's four bottom tabs", () => {
    expect(STUDENT_BOTTOM_TABS.map((t) => t.label)).toEqual(["Overview", "Correct", "Classes", "Profile"])
  })

  it("uses design A's empty bell copy, with no em dash", () => {
    expect(STUDENT_INBOX_EMPTY).toBe("Nothing yet. Marked papers and messages from your teachers land here.")
    expect(STUDENT_INBOX_EMPTY).not.toMatch(/[—–]/)
  })
})

describe("studentShellTrail and studentPageTitle", () => {
  it("titles the portal root Overview with no trail", () => {
    expect(studentShellTrail("/student")).toEqual([])
    expect(studentPageTitle("/student")).toBe("Overview")
  })
  it("titles a section by its own name, one crumb, so no breadcrumbs", () => {
    expect(studentShellTrail("/student/friends")).toEqual([{ label: "Friends" }])
    expect(studentPageTitle("/student/friends")).toBe("Friends")
    expect(studentPageTitle("/student/correct")).toBe("Correct a paper")
  })
  it("titles a subject page by the subject's name when it is known", () => {
    const subjects = [{ code: "0606", name: "Add Maths" }]
    expect(studentPageTitle("/student/subject/0606", subjects)).toBe("Add Maths")
    expect(studentPageTitle("/student/subject/0606")).toBe("0606")
  })
  it("keeps a trail when drilled in, so breadcrumbs render", () => {
    expect(studentShellTrail("/student/practice/0580").map((c) => c.label)).toEqual(["Practice", "0580"])
  })
})

describe("studentDetailLine (design A: IGCSE · 3 subjects)", () => {
  it.each([
    ["IGCSE", 3, "IGCSE · 3 subjects"],
    ["IGCSE", 1, "IGCSE · 1 subject"],
    ["IGCSE", 0, "IGCSE · no subjects yet"],
    [null, 2, "2 subjects"],
  ] as const)("%s with %i subjects reads %s", (qualification, count, expected) => {
    expect(studentDetailLine(qualification, count)).toBe(expected)
  })
})

describe("studentDestinationFor", () => {
  it("matches the inbox screen's destinations", () => {
    expect(studentDestinationFor({ type: "announcement", payload: {} })).toBe("/student/announcements")
    expect(studentDestinationFor({ type: "streak_warning", payload: {} })).toBe("/student/profile")
    expect(
      studentDestinationFor({ type: "study_plan_reminder", payload: { subjectCode: "0580", sessionId: "s 1" } }),
    ).toBe("/student/plan/0580/session/s%201")
    expect(studentDestinationFor({ type: "grade_ready", payload: {} })).toBeNull()
  })
})
```

Run: `cd web && npx vitest run tests/unit/studentShell.test.ts`
Expected: FAIL (`studentNavItems` is not exported).

- [ ] **Step 2: Create `web/src/lib/studentInbox.ts` and point the screen at it**

```ts
import type { Notification } from "@/lib/notificationTypes"

/**
 * Where a student notification row goes, or null for no action. Moved out of
 * `portals/student/screens/Notifications.tsx` so the shell's bell panel can
 * use it without pulling the inbox screen into the entry chunk. Kept
 * consistent with `pushClientBridge.destinationFor`. `grade_ready` has no
 * destination on purpose (see the screen's note).
 */
export function studentDestinationFor(notification: Pick<Notification, "type" | "payload">): string | null {
  switch (notification.type) {
    case "announcement":
      return "/student/announcements"
    case "streak_warning":
      return "/student/profile"
    case "study_plan_reminder": {
      const { subjectCode, sessionId } = notification.payload
      if (!subjectCode || !sessionId) return null
      return `/student/plan/${encodeURIComponent(subjectCode)}/session/${encodeURIComponent(sessionId)}`
    }
    default:
      return null
  }
}
```

In `web/src/portals/student/screens/Notifications.tsx`, replace the body of `export function destinationFor(notification: Notification): string | null { … }` (keep its doc comment) with `return studentDestinationFor(notification)` and add `import { studentDestinationFor } from "@/lib/studentInbox"`. The export name stays, so its callers and `notifications.test.ts` are unaffected.

- [ ] **Step 3: Rework `web/src/portals/student/data.ts`**

Replace the `NavItem` interface, `navGroups` and the now-unused Phosphor imports (keep `CalendarCheck`, `Gear`, `GraduationCap`) with:

```ts
import type { ShellIconName } from "@/components/shell/icons"

export interface NavItem {
  to: string
  label: string
  tag?: string
  end?: boolean
  /** A design A shell icon by name, or a Phosphor glyph for rows design A has no icon for. */
  icon: ShellIconName | Icon
}

/** The sidebar rows: design A's four, then the two `develop` rows design A has
 * no place for (Task 0 decision 2; drift logged). */
export const studentNavItems: NavItem[] = [
  { to: "/student", label: "Overview", end: true, icon: "home" },
  { to: "/student/classes", label: "Your classes", icon: "class" },
  { to: "/student/board", label: "Standings", icon: "trophy" },
  { to: "/student/friends", label: "Friends", icon: "friends" },
  { to: "/student/tutors", label: "Tutors", icon: GraduationCap },
  // S-38 ("Tutors & your data") has no nav entry of its own (SPEC C-13); Sessions links to it.
  { to: "/student/sessions", label: "Sessions", icon: CalendarCheck },
]

/** The account panel's links (design A `.as-links`), before Sign out. */
export const studentAccountLinks: NavItem[] = [
  { to: "/student/profile", label: "Your profile", icon: "user" },
  { to: "/student/parents", label: "Your parents", icon: "heart" },
  { to: "/student/recently-deleted", label: "Recently deleted", icon: "trash" },
]

/** The bell panel's footer links (design A `.as-pop-foot`). */
export const studentInboxLinks: NavItem[] = [
  { to: "/student/notifications", label: "All notifications", icon: "bell" },
  { to: "/student/announcements", label: "Announcements", icon: "mega" },
]

export const STUDENT_INBOX_EMPTY = "Nothing yet. Marked papers and messages from your teachers land here."

/**
 * Every destination the student shell links to, grouped by where it sits.
 * `navigation.test.ts` checks each one is a mounted route with a real
 * breadcrumb, so a renamed screen breaks a test rather than a link.
 */
export const navGroups: NavGroup[] = [
  { label: "Sidebar", items: studentNavItems },
  { label: "Account", items: studentAccountLinks },
  { label: "Inbox", items: studentInboxLinks },
  { label: "Marking", items: [{ to: "/student/correct", label: "Upload a paper", icon: "up" }] },
  { label: "Settings", items: [{ to: "/student/settings", label: "Settings", icon: Gear }] },
]
```

and add, after `resolveCrumbTrail`:

```ts
const ROOT_CRUMBS = new Set(["Home", "Marking"])

/** The top bar's trail: the crumb trail without its root ("Home" / "Marking"),
 * so a section is one crumb (title only) and only a drilled-in page has
 * breadcrumbs, as design A shows. */
export function studentShellTrail(pathname: string): Crumb[] {
  const trail = resolveCrumbTrail(pathname)
  return ROOT_CRUMBS.has(trail[0]?.label ?? "") ? trail.slice(1) : trail
}

/** The top bar's title. A subject page shows the subject's name when known. */
export function studentPageTitle(pathname: string, subjects: readonly { code: string; name: string }[] = []): string {
  const subject = pathname.match(/^\/student\/subject\/([^/]+)$/)
  if (subject) return subjects.find((s) => s.code === subject[1])?.name ?? subject[1]
  const trail = studentShellTrail(pathname)
  return trail[trail.length - 1]?.label ?? "Overview"
}

/** The line under the student's name (sidebar user block and account panel). */
export function studentDetailLine(qualificationLabel: string | null, subjectCount: number): string {
  const count = subjectCount === 0 ? "no subjects yet" : subjectCount === 1 ? "1 subject" : `${subjectCount} subjects`
  return qualificationLabel ? `${qualificationLabel} · ${count}` : count
}
```

- [ ] **Step 4: Create `web/src/portals/student/GradeRing.tsx`**

```tsx
const RING_COLOR: Record<string, string> = {
  "A*": "var(--color-grade-a-star)",
  A: "var(--color-grade-a)",
  B: "var(--color-grade-b)",
  C: "var(--color-grade-c)",
  D: "var(--color-grade-d)",
  E: "var(--color-grade-e)",
}

/** Design A `.as-ring`: the subject's grade in a 28px ring filled to `pct`. */
export function GradeRing({ grade, pct }: { grade: string; pct: number }) {
  const color = RING_COLOR[grade] ?? "var(--color-on-surface-variant)"
  const p = Math.max(0, Math.min(100, Math.round(pct)))
  return (
    <span
      aria-hidden="true"
      className="relative grid size-7 flex-none place-items-center rounded-pill text-[11px] font-extrabold leading-none text-on-surface before:absolute before:inset-[3px] before:rounded-pill before:bg-surface-container-lowest dark:before:bg-surface-container-high"
      style={{ background: `conic-gradient(${color} ${p}%, var(--color-surface-container-high) 0)` }}
    >
      <b className="relative">{grade}</b>
    </span>
  )
}
```

- [ ] **Step 5: Create `web/src/portals/student/shell.tsx`**

```tsx
import { Link, useLocation } from "react-router-dom"
import { ChalkboardTeacher, House, NotePencil, UserCircle, type Icon } from "@phosphor-icons/react"
import type { AccountLink } from "@/components/shell/AccountPanel"
import { ShellIcon, type ShellIconName } from "@/components/shell/icons"
import type { NotificationsPanelProps } from "@/components/shell/NotificationsPanel"
import { PortalShell } from "@/components/shell/PortalShell"
import { profileName } from "@/components/shell/ShellAvatar"
import { ShellUserBlock } from "@/components/shell/ShellSidebar"
import { ShellTree, type ShellTreeRow } from "@/components/shell/ShellTree"
import { SHELL_BUTTON_PRIMARY } from "@/components/shell/shellStyles"
import type { NavShellItem } from "@/components/ui/nav-shells"
import type { ScreenOverlay } from "@/components/ui/screen-outlet"
import { useProfile, useStudentProfile } from "@/lib/hooks/useMeApi"
import { useReference } from "@/lib/hooks/useReferenceApi"
import { useOverview } from "@/lib/hooks/useStudentApi"
import { underlyingPathname } from "@/lib/nav/backgroundLocation"
import type { prefetchOnIntent } from "@/lib/prefetchOnIntent"
import { qualificationLevelLabel } from "@/lib/qualificationLevels"
import { STAFF_INBOX_ERROR } from "@/lib/staffInbox"
import { studentDestinationFor } from "@/lib/studentInbox"
import type { SubjectRow } from "@/lib/studentTypes"
import { cn } from "@/lib/utils"
import { GradeRing } from "./GradeRing"
import {
  STUDENT_INBOX_EMPTY,
  currentSubjectCode,
  studentAccountLinks,
  studentDetailLine,
  studentInboxLinks,
  studentNavItems,
  studentPageTitle,
  studentShellTrail,
  type NavItem,
} from "./data"

export const STUDENT_SETTINGS_BASE = "/student/settings"

/** The four route-backed phone tabs, unchanged from `develop` (approved
 * drift). Declared in tab order; the shell appends "More". */
export const STUDENT_BOTTOM_TABS: readonly { id: string; label: string; to: string; end?: boolean; icon: Icon }[] = [
  { id: "overview", label: "Overview", to: "/student", end: true, icon: House },
  { id: "correct", label: "Correct", to: "/student/correct", icon: NotePencil },
  { id: "classes", label: "Classes", to: "/student/classes", icon: ChalkboardTeacher },
  { id: "profile", label: "Profile", to: "/student/profile", icon: UserCircle },
]

function NavGlyph({ icon }: { icon: NavItem["icon"] }) {
  if (typeof icon === "string") return <ShellIcon name={icon} />
  const Glyph = icon
  return <Glyph size={18} aria-hidden="true" />
}

const toShellItem = (item: NavItem): NavShellItem => ({
  id: item.to,
  to: item.to,
  end: item.end,
  label: item.label,
  icon: <NavGlyph icon={item.icon} />,
})

const TYPE_ICON: Record<string, ShellIconName> = {
  announcement: "mega",
  grade_ready: "review",
  study_plan_reminder: "plan",
}

const STUDENT_NOTIFICATIONS_PANEL: Omit<NotificationsPanelProps, "unread" | "triggerClassName"> = {
  destinationFor: studentDestinationFor,
  iconFor: (type) => <ShellIcon name={TYPE_ICON[type] ?? "bell"} />,
  inboxTo: "/student/notifications",
  footerLinks: studentInboxLinks.map(({ to, label }) => ({ to, label })),
  emptyMessage: STUDENT_INBOX_EMPTY,
  errorHeading: STAFF_INBOX_ERROR.heading,
}

const STUDENT_ACCOUNT_LINKS: readonly AccountLink[] = studentAccountLinks.map((link) => ({
  id: link.to,
  label: link.label,
  to: link.to,
  icon: <NavGlyph icon={link.icon} />,
}))

function subjectRows(subjects: readonly SubjectRow[]): ShellTreeRow[] {
  return subjects.map((s) => ({
    id: s.code,
    label: s.name,
    title: `${s.name} · ${s.code}`,
    trailing: s.code,
    adornment: s.grade ? <GradeRing grade={s.grade} pct={s.pct} /> : null,
    children: [
      { id: `${s.code}-practice`, label: "Practice", to: `/student/practice/${s.code}`, icon: <ShellIcon name="practice" /> },
      { id: `${s.code}-cards`, label: "Flashcards", to: `/student/flashcards/${s.code}`, icon: <ShellIcon name="cards" /> },
      { id: `${s.code}-plan`, label: "Study plan", to: `/student/plan/${s.code}`, icon: <ShellIcon name="plan" /> },
    ],
  }))
}

export interface StudentShellProps {
  pending: boolean
  prefetchCorrectPaper: ReturnType<typeof prefetchOnIntent>
  overlay?: ScreenOverlay
}

/** The student portal's content for the shared shell (portal shell spec §1). */
export function StudentShell({ pending, prefetchCorrectPaper, overlay }: StudentShellProps) {
  const location = useLocation()
  // Same queries Overview and Profile read; react-query dedupes by key.
  const overview = useOverview()
  const profile = useProfile()
  const studentProfile = useStudentProfile()
  const { data: reference } = useReference()
  const subjects = overview.data?.subjects ?? []
  // While Settings is a dialog, the title follows the page underneath.
  const pagePath = underlyingPathname({
    pathname: location.pathname,
    state: location.state,
    overlayBase: STUDENT_SETTINGS_BASE,
  })
  const detail = studentDetailLine(
    qualificationLevelLabel(reference?.qualificationLevels, studentProfile.data?.profile.qualificationLevel),
    subjects.length,
  )
  const upload = (className?: string) => (
    <Link to="/student/correct" viewTransition className={cn(SHELL_BUTTON_PRIMARY, className)} {...prefetchCorrectPaper}>
      <ShellIcon name="up" />
      <span>Upload a paper</span>
    </Link>
  )

  return (
    <PortalShell
      portal="student"
      drawerTitle="Lemely"
      pending={pending}
      overlay={overlay}
      sidebar={{
        navLabel: "Main",
        homeTo: "/student",
        homeLabel: "Lemely, overview",
        items: studentNavItems.map(toShellItem),
        groups: [
          {
            id: "subjects",
            label: "Subjects",
            render: (labelId) => (
              <ShellTree
                labelledBy={labelId}
                rows={subjectRows(subjects)}
                currentId={currentSubjectCode(location.pathname)}
                empty={overview.isPending ? null : "Your subjects show up here after your first marked paper."}
              />
            ),
          },
        ],
        footerAction: upload(),
        user: profile.data ? (
          <ShellUserBlock name={profileName(profile.data)} avatarUrl={profile.data.avatarUrl} detail={detail} />
        ) : (
          <p className="px-0.5 text-body-sm text-on-surface-variant">{profile.isPending ? "Loading…" : "Signed in"}</p>
        ),
      }}
      topBar={{
        title: studentPageTitle(pagePath, subjects),
        trail: studentShellTrail(pagePath),
        navLabel: "Open student navigation",
        // Not on the upload screen itself, where it would do nothing.
        actions: location.pathname === "/student/correct" ? null : upload("me-2.5 max-shell-sm:hidden"),
        notifications: STUDENT_NOTIFICATIONS_PANEL,
        settingsTo: STUDENT_SETTINGS_BASE,
        account: { links: STUDENT_ACCOUNT_LINKS, detail },
      }}
      bottomTabs={STUDENT_BOTTOM_TABS.map(
        (tab): NavShellItem => ({
          id: tab.id,
          to: tab.to,
          end: tab.end,
          label: tab.label,
          icon: <tab.icon size={22} aria-hidden="true" />,
          prefetch: tab.id === "correct" ? prefetchCorrectPaper.onPointerEnter : undefined,
        }),
      )}
      bottomEmphasisId="correct"
    />
  )
}
```

(Check `prefetchOnIntent`'s return type on `develop` has `onPointerEnter`; `index.tsx` already uses `prefetchCorrectPaper.onPointerEnter`.)

- [ ] **Step 6: Rewire `web/src/portals/student/index.tsx`**

Delete `UserBlock`, `NavRow`, `SubjectNavGroup`, `NavGroups`, `Sidebar`, `HeaderStreak`, `Header`, the local `STUDENT_BOTTOM_TABS`, and every import only they used (keep `loadCorrectPaper`, `prefetchCorrectPaper`, the lazy screens, `studentOnboardingRedirect`, `studentRoute`). Then:

```tsx
import { StudentShell } from "./shell"
export { STUDENT_BOTTOM_TABS } from "./shell"

function StudentLayout() {
  const location = useLocation()
  // The S-02 record onboarding writes (`/me/student-profile`). A pending query
  // never redirects and shows the skeleton inside the shell.
  const studentProfile = useStudentProfile()
  const onboardingRedirect = studentOnboardingRedirect(
    studentProfile.status,
    studentProfile.data?.profile.onboardingCompletedAt ?? null,
    location.pathname,
  )
  if (onboardingRedirect) return <Navigate to={onboardingRedirect} replace />
  return <StudentShell pending={studentProfile.isPending} prefetchCorrectPaper={prefetchCorrectPaper} />
}
```

The settings route stays page-based (`PortalSettingsLayout`) until Task 7.

- [ ] **Step 7: Update the student entries of the pinned tests**

- `navShells.test.ts`: replace the student half of "… mount BottomNav with the five labels in order" with

```ts
it("student/shell.tsx passes its four tabs to PortalShell in order", () => {
  const source = stripComments(read("portals/student/shell.tsx"))
  expect(source).toMatch(/<PortalShell\b/)
  expect(source).toMatch(/"Overview"[\s\S]*"Correct"[\s\S]*"Classes"[\s\S]*"Profile"/)
})
```

and in "student and teacher render the shared shell sidebar" add `it("student/shell.tsx imports from components/shell", () => expect(read("portals/student/shell.tsx")).toMatch(/from\s+"@\/components\/shell\//))`.
- `streakChip.test.ts`: replace the `describe("student/index.tsx", …)` block with

```ts
describe("student shell", () => {
  // Portal shell spec §1 "Removed": the header streak is gone; the streak lives
  // in the Overview page (its hero, in the Overview plan).
  it("no longer renders a streak chip in the shell", () => {
    expect(sourceOf("src/portals/student/index.tsx")).not.toContain("<XPStreak")
    expect(sourceOf("src/portals/student/shell.tsx")).not.toContain("<XPStreak")
  })
})
```

- `subjectGlyph.test.ts`: replace "the student sidebar's per-subject accordion rows render SubjectGlyph" with

```ts
it("the student sidebar's subject rows render design A's grade ring", () => {
  expect(sourceOf("src/portals/student/shell.tsx")).toContain("<GradeRing")
})
```

- `screenEntrance.test.ts`: replace "student's sidebar NavLink passes viewTransition inline" with `expect(sourceOf("src/portals/student/shell.tsx")).toContain("viewTransition")` (the Upload link), and remove `"src/portals/student/index.tsx"` from its `PORTAL_LAYOUTS` ScreenOutlet list (PortalShell already covers it).
- `offlineBanner.test.ts` and `outletBoundary.test.ts`: remove `"src/portals/student/index.tsx"` from `PORTAL_LAYOUTS` (PortalShell covers it).
- `brandLockup.test.ts`: remove `"src/portals/student/index.tsx"` from `LOCKUP_SITES` (ShellSidebar covers it).

- [ ] **Step 8: Run unit tests**

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/student-home-variants/web
npx vitest run tests/unit/studentShell.test.ts tests/unit/navigation.test.ts tests/unit/navShells.test.ts tests/unit/navigationModel.test.ts tests/unit/streakChip.test.ts tests/unit/subjectGlyph.test.ts tests/unit/screenEntrance.test.ts tests/unit/offlineBanner.test.ts tests/unit/outletBoundary.test.ts tests/unit/brandLockup.test.ts tests/unit/prefetchWiring.test.ts tests/unit/recentlyDeletedWiring.test.ts tests/unit/notifications.test.ts tests/unit/navRowIconGuard.test.ts tests/unit/routeSkeleton.test.ts
npm run typecheck && npx oxlint src/portals/student src/components/shell src/lib/studentInbox.ts
```

Expected: all pass. `navigation.test.ts` needs no edit: every `navGroups` destination is still a mounted route with a non-"Home" crumb, and `/student/notifications` is still in `navGroups` (D1.3).

- [ ] **Step 9: Add the student mocks to `web/scripts/drift/mocks.mjs`**

The values copy the preview's populated and new states (`student-home-a.html` shell markup): Mariam, IGCSE, the three subjects with their ring percentages, and the bell rows with their times.

```js
export const STUDENT_PROFILE = {
  userId: "capture-student",
  email: "mariam.hassan@student.lemely.app",
  displayName: "Mariam",
  role: "student",
  emailVerified: true,
  avatarUrl: null,
  timezone: "Africa/Cairo",
  timezoneIsExplicit: true,
}

const STUDENT_PROFILE_RECORD = {
  profile: {
    qualificationLevel: "igcse",
    gradeLevel: null,
    schoolName: null,
    hasExternalLessons: null,
    weeklyStudyHours: null,
    onboardingCompletedAt: "2026-09-01T10:00:00Z",
    leaderboardOptOut: false,
  },
  enrolments: [],
}

const REFERENCE = {
  subjects: [],
  targetGradeVocabularies: [],
  qualificationLevels: [{ value: "igcse", label: "IGCSE" }],
  sessionMonths: [],
  difficultyBands: [],
}

const row = (code, name, grade, pct) => ({
  code,
  name,
  qualificationLevel: "igcse",
  detail: "",
  pct,
  papers: 1,
  trend: "",
  grade,
  barColor: "accent",
  trendUp: true,
})

const STUDENT_DATA = {
  populated: {
    subjects: [row("0580", "Mathematics", "A", 40), row("0606", "Add Maths", "B", 36), row("0625", "Physics", "C", 43)],
    notifications: [
      { notificationId: "sn-1", type: "announcement", title: "Physics mock moved to Thu 12 Nov", body: "Ms Farouk · Year 11 Physics", payload: {}, createdAt: "2026-11-05T09:12:00", readAt: null },
      { notificationId: "sn-2", type: "friend_added", title: "Youssef added you as a friend", body: "See where you both stand this week", payload: {}, createdAt: "2026-11-05T08:40:00", readAt: null },
      { notificationId: "sn-3", type: "grade_ready", title: "0580/42 is marked", body: "Grade A, up from B", payload: {}, createdAt: "2026-11-04T18:00:00", readAt: "2026-11-04T18:30:00" },
    ],
    counts: { unread: 2, total: 3, unreadByType: { announcement: 1, friend_added: 1 } },
  },
  new: { subjects: [], notifications: [], counts: { unread: 0, total: 0, unreadByType: {} } },
}

export function studentShellMocks(state) {
  const data = STUDENT_DATA[state]
  if (!data) throw new Error(`no student shell mock for ${state}`)
  return async (page) => {
    await page.route("**/api/me/student-profile", (route) => json(route, STUDENT_PROFILE_RECORD))
    await page.route("**/api/reference", (route) => json(route, REFERENCE))
    await page.route("**/api/student/overview", (route) =>
      json(route, { studentName: "Mariam", forecast: "", subjects: data.subjects, weakGlobal: [], momentum: { points: [] } }),
    )
    await page.route("**/api/notifications", (route) => json(route, { notifications: data.notifications }))
    await page.route("**/api/notifications/counts", (route) => json(route, data.counts))
  }
}
```

(`friend_added` is not an API type: the API has no friend notification. The row exists so the panel matches the design; it renders the fallback bell icon. Logged.)

- [ ] **Step 10: Add the student scenes to `web/scripts/drift/scenes-shell.mjs`**

```js
import { STUDENT_PROFILE, studentShellMocks } from "./mocks.mjs"

const student = (state, extra = {}) => ({
  path: "/student",
  profile: STUDENT_PROFILE,
  mocks: studentShellMocks(state),
  ...extra,
})

/** Make the preview stand for another route: its route-dependent parts are a
 * title and which row is current (design A rules), nothing else. */
function asRoute({ title, current }) {
  return (page) =>
    page.evaluate(
      ([t, c]) => {
        document.querySelector(".as-title").textContent = t
        for (const a of document.querySelectorAll(".as-list a[aria-current]")) a.removeAttribute("aria-current")
        if (c) document.querySelector(`.as-list a[href="${c}"]`)?.setAttribute("aria-current", "page")
      },
      [title, current],
    )
}

async function openStudentNav(page) {
  const more = page.getByRole("button", { name: "More", exact: true })
  if (await more.isVisible()) await more.click()
  else await page.getByRole("button", { name: "Open student navigation" }).click()
  await page.getByRole("dialog").waitFor()
}
async function openPreviewNav(page) {
  const more = page.locator(".a-bottombar button[popovertarget]")
  if (await more.isVisible()) await more.click()
  else await page.click(".as-menu")
}

export const STUDENT_SCENES = [
  ...["populated", "new"].map((state) => ({
    id: `student-${state}-frame`,
    kind: "preview-vs-app",
    capture: "frame",
    app: student(state),
    preview: { state },
  })),
  {
    id: "student-subject-frame",
    kind: "preview-vs-app",
    capture: "frame",
    app: student("populated", { path: "/student/subject/0606" }),
    preview: { state: "populated", act: asRoute({ title: "Add Maths", current: null }) },
  },
  {
    id: "student-notifications-frame",
    kind: "preview-vs-app",
    capture: "frame",
    app: student("populated", { path: "/student/notifications" }),
    preview: { state: "populated", act: asRoute({ title: "Notifications", current: null }) },
  },
  {
    id: "student-drawer",
    kind: "preview-vs-app",
    capture: "frame",
    windows: [390, 768],
    app: student("populated", { act: openStudentNav }),
    preview: { state: "populated", act: openPreviewNav },
  },
  {
    id: "student-bell",
    kind: "preview-vs-app",
    capture: "frame",
    app: student("populated", { act: openBell }),
    preview: { state: "populated", act: (page) => page.click(".as-pop-bell summary") },
  },
  {
    id: "student-account",
    kind: "preview-vs-app",
    capture: "frame",
    app: student("populated", { act: openAccount }),
    preview: { state: "populated", act: (page) => page.click(".as-pop-me summary") },
  },
]
```

and change the last line to `export const SHELL_SCENES = [...TEACHER_SCENES, ...STUDENT_SCENES]`.

- [ ] **Step 11: Append student behaviour checks to `web/scripts/drift/checks-shell.mjs`**

```js
import { STUDENT_PROFILE, studentShellMocks } from "./mocks.mjs"

const STUDENT_HOME = { path: "/student", profile: STUDENT_PROFILE, mocks: studentShellMocks("populated") }

SHELL_CHECKS.push(
  {
    id: "student-subject-tree-keyboard",
    app: STUDENT_HOME,
    async run(page) {
      const physics = page.getByRole("button", { name: /Physics/ })
      if ((await physics.getAttribute("aria-expanded")) !== "false") throw new Error("tree: Physics should start closed on /student")
      await physics.focus()
      await page.keyboard.press("Enter")
      if ((await physics.getAttribute("aria-expanded")) !== "true") throw new Error("tree: Enter did not expand Physics")
      const practice = page.locator(`#${await physics.getAttribute("aria-controls")} a`, { hasText: "Practice" })
      await practice.waitFor()
      await page.keyboard.press("Space")
      if ((await physics.getAttribute("aria-expanded")) !== "false") throw new Error("tree: Space did not collapse Physics")
      await practice.waitFor({ state: "hidden" })
    },
  },
  {
    id: "student-subject-tree-opens-current-route",
    app: { ...STUDENT_HOME, path: "/student/practice/0606" },
    async run(page) {
      const addMaths = page.getByRole("button", { name: /Add Maths/ })
      if ((await addMaths.getAttribute("aria-expanded")) !== "true") throw new Error("tree: route subject 0606 should start open")
    },
  },
  {
    id: "student-drawer-traps-focus-and-escape-returns",
    width: 768,
    app: STUDENT_HOME,
    async run(page) {
      const { more, dialog } = await openNavFromMore(page)
      for (let i = 0; i < 40; i++) {
        await page.keyboard.press("Tab")
        if (!(await dialog.evaluate((el) => el.contains(document.activeElement)))) {
          throw new Error(`drawer: focus left the dialog after ${i + 1} Tab presses`)
        }
      }
      await page.keyboard.press("Escape")
      await assertHidden(dialog, "drawer")
      await assertFocused(more, "More tab")
    },
  },
  {
    id: "student-phone-sheet-hides-wordmark-and-upload",
    width: 390,
    app: STUDENT_HOME,
    async run(page) {
      const { dialog } = await openNavFromMore(page)
      if (await dialog.getByRole("link", { name: "Upload a paper" }).isVisible()) throw new Error("sheet: Upload should be hidden (bottom bar has it)")
      const visibility = await dialog.getByRole("link", { name: "Lemely, overview" }).evaluate((el) => getComputedStyle(el).visibility)
      if (visibility !== "hidden") throw new Error("sheet: wordmark should be visibility:hidden")
    },
  },
  {
    id: "student-bell-escape-returns-focus",
    app: STUDENT_HOME,
    async run(page) {
      const bell = page.getByRole("button", { name: "Notifications, 2 unread" })
      await bell.click()
      await page.getByRole("menu").waitFor()
      await page.keyboard.press("Escape")
      await assertHidden(page.getByRole("menu"), "bell panel")
      await assertFocused(bell, "bell trigger")
    },
  },
  {
    id: "student-account-escape-returns-focus",
    app: STUDENT_HOME,
    async run(page) {
      const avatar = page.getByRole("button", { name: "Your profile and account, Mariam" })
      await avatar.click()
      await page.getByRole("menuitem", { name: "Sign out" }).waitFor()
      await page.keyboard.press("Escape")
      await assertFocused(avatar, "avatar trigger")
    },
  },
  {
    id: "student-375-title-readable",
    width: 375,
    app: STUDENT_HOME,
    async run(page) {
      const title = page.locator("header p").first()
      const box = await title.boundingBox()
      if (!box || box.width < 100) throw new Error(`375px: title is ${box?.width ?? 0}px wide`)
    },
  },
)
```

(`openNavFromMore`, `assertFocused`, `assertHidden` are the helpers already in this file.) Prove one goes red: temporarily change `Enter` to `Tab` in the first check, run `node scripts/shell-behaviour.mjs --check student-subject-tree-keyboard`, expect `FAIL`, revert.

- [ ] **Step 12: Drift acceptance (student vs design A)**

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/student-home-variants/web
npm run build
node scripts/shell-behaviour.mjs
node scripts/home-drift.mjs --scene student-
```

For each failing key, open `<key>.a.png` (design), `<key>.b.png` (app) and `<key>.diff.png`, fix the Tailwind classes against the mapping tables in Tasks 3 to 6, rebuild, re-run that scene (`--scene student-populated-frame --windows 1440 --themes light` for a quick loop, then the full set). Expected differences that stay, each logged in `justifications.json` (keep each pair ≤15%):

- `student-*-frame@390`, `@768`: `BottomNav` (5 tabs, below 820px) in place of design A's 4-item bar at 720px and below, and no bar at 768px. "Approved: phone navigation parity with teacher; user decision 2026-11-06." Measure and record the %.
- `student-populated-frame`: sidebar has Tutors and Sessions rows (Task 0 decision 2); the Add Maths group is closed on `/student` (design A opens today's session subject; session data arrives with the Overview plan, which passes `fallbackId`).
- `student-bell`: the mono spans in "Thu 12 Nov" and "0580/42" render in the sans face (titles are plain API strings); the friend row shows the fallback bell icon (no friend type in the API); the panel heading is a `<p>` (axe: no heading inside `role="menu"`); at 390px the panel sits 8px below the 36px trigger instead of 4px under the 44px bar.
- `student-subject-frame`, `student-notifications-frame`: same as `student-populated-frame`.

Every other difference is drift to fix. Re-run until `node scripts/home-drift.mjs --scene student-` exits 0. Also re-run `--scene teacher-` (shared components changed) and expect exit 0.

- [ ] **Step 13: Commit**

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/student-home-variants
FILES="web/src/portals/student/shell.tsx web/src/portals/student/GradeRing.tsx web/src/portals/student/data.ts web/src/portals/student/index.tsx web/src/portals/student/screens/Notifications.tsx web/src/lib/studentInbox.ts web/tests/unit/studentShell.test.ts web/tests/unit/navShells.test.ts web/tests/unit/streakChip.test.ts web/tests/unit/subjectGlyph.test.ts web/tests/unit/screenEntrance.test.ts web/tests/unit/offlineBanner.test.ts web/tests/unit/outletBoundary.test.ts web/tests/unit/brandLockup.test.ts web/scripts/drift/mocks.mjs web/scripts/drift/scenes-shell.mjs web/scripts/drift/checks-shell.mjs web/scripts/drift/justifications.json"
/home/sico/Code/Lemely/.venv/bin/pre-commit run --files $FILES
git commit -S -m "feat(web): student portal renders the shared design A shell" -m "Removes the old student Sidebar, Header, UserBlock and HeaderStreak." -- $FILES
```

---

### Task 7: Student settings as a dialog by URL; arrow keys on the tabs

**Files:**
- Modify: `web/src/portals/settings/settingsTabs.ts` (add `STUDENT_SETTINGS_TABS`)
- Modify: `web/src/portals/settings/SettingsModal.tsx` (arrow keys; design A frame has no border)
- Modify: `web/src/portals/student/index.tsx` (settings route block; overlay; content routes)
- Modify: `web/src/portals/student/data.ts` (two crumbs)
- Modify: `web/src/portals/student/screens/Profile.tsx` (line 480: carry the overlay state)
- Modify: `web/e2e/theme.spec.ts` (theme radios now on the Appearance tab)
- Modify: `web/tests/unit/settingsTabs.test.ts`
- Modify: `web/scripts/drift/scenes-shell.mjs`, `web/scripts/drift/checks-shell.mjs`, `web/scripts/drift/justifications.json`

**Interfaces:**
- Consumes: `SettingsModalRoute` (`{ tabs, basePath, fallbackPath }`), `SettingsTab`, `settingsTabPath`, `activeSettingsTab`, `nextSettingsTabIndex` (Task 3), `STUDENT_SETTINGS_BASE` (Task 6), `StudentShellProps.overlay`, `useOverlayState`.
- Produces:
  ```ts
  // settingsTabs.ts
  export const STUDENT_SETTINGS_TABS: readonly SettingsTab[]   // profile "", account "devices", notifications, appearance, install
  ```
  Student routes: `/student/settings`, `/student/settings/devices`, `/student/settings/notifications`, `/student/settings/appearance`, `/student/settings/install`, each a dialog over the page the reader came from (or over `/student` on a fresh load).

- [ ] **Step 1: Write the failing tests (append to `web/tests/unit/settingsTabs.test.ts`)**

```ts
import { STUDENT_SETTINGS_TABS } from "@/portals/settings/settingsTabs"
import { studentRoute } from "@/portals/student"

const STUDENT_BASE = "/student/settings"

function studentSettingsRoute() {
  const route = (studentRoute.children ?? []).find((child) => child.path === "settings")
  if (!route) throw new Error("student portal has no settings route")
  return route
}

describe("STUDENT_SETTINGS_TABS (design A dialog)", () => {
  it("lists design A's five tabs in rail order", () => {
    expect(STUDENT_SETTINGS_TABS.map((tab) => tab.label)).toEqual([
      "Profile",
      "Account and devices",
      "Notifications",
      "Appearance",
      "Install Lemely",
    ])
  })

  it("keeps every path the page-based student settings used", () => {
    const paths = STUDENT_SETTINGS_TABS.map((tab) => settingsTabPath(STUDENT_BASE, tab))
    for (const legacy of [STUDENT_BASE, `${STUDENT_BASE}/devices`, `${STUDENT_BASE}/notifications`, `${STUDENT_BASE}/install`]) {
      expect(paths).toContain(legacy)
    }
  })

  it("says offline practice, not marking, for students", () => {
    expect(STUDENT_SETTINGS_TABS.find((t) => t.id === "install")?.description).toBe(
      "Add Lemely to your home screen for faster access and offline practice.",
    )
  })

  it("has no em dash in any label or helper", () => {
    for (const tab of STUDENT_SETTINGS_TABS) {
      expect(tab.label).not.toContain("—")
      expect(tab.description).not.toContain("—")
    }
  })

  it("mounts exactly one child route per tab, index for the empty segment", () => {
    const children = studentSettingsRoute().children ?? []
    const mounted = children.map((child) => (child.index ? "" : child.path))
    expect(mounted.sort()).toEqual(STUDENT_SETTINGS_TABS.map((tab) => tab.segment).sort())
  })

  it("titles every tab route", () => {
    for (const child of studentSettingsRoute().children ?? []) {
      expect((child.handle as { title?: string } | undefined)?.title, String(child.path)).toBeTruthy()
    }
  })

  it("resolves the active student tab from a pathname", () => {
    expect(activeSettingsTab(STUDENT_SETTINGS_TABS, STUDENT_BASE, STUDENT_BASE)?.id).toBe("profile")
    expect(activeSettingsTab(STUDENT_SETTINGS_TABS, STUDENT_BASE, `${STUDENT_BASE}/appearance`)?.id).toBe("appearance")
    expect(activeSettingsTab(STUDENT_SETTINGS_TABS, STUDENT_BASE, `${STUDENT_BASE}/classes`)).toBeNull()
  })

  it("renders the settings route as the dialog, not the old page layout", () => {
    const source = fs.readFileSync(path.join(process.cwd(), "src/portals/student/index.tsx"), "utf8")
    expect(source).toContain("<SettingsModalRoute")
    expect(source).not.toContain("<PortalSettingsLayout")
  })
})
```

Run: `cd web && npx vitest run tests/unit/settingsTabs.test.ts`
Expected: FAIL (`STUDENT_SETTINGS_TABS` is not exported).

- [ ] **Step 2: Add `STUDENT_SETTINGS_TABS` to `web/src/portals/settings/settingsTabs.ts`**

```ts
/** The student portal's tabs (design A's settings dialog), in rail order.
 * Segments keep the paths the page-based student settings used. */
export const STUDENT_SETTINGS_TABS: readonly SettingsTab[] = TEACHER_SETTINGS_TABS.filter(
  (tab) => tab.id !== "classes",
).map((tab) =>
  tab.id === "install"
    ? { ...tab, description: "Add Lemely to your home screen for faster access and offline practice." }
    : tab,
)
```

Update the file header comment's "The route block in `portals/teacher/index.tsx`" to "The route blocks in `portals/teacher/index.tsx` and `portals/student/index.tsx`".

- [ ] **Step 3: Arrow keys and the design A frame in `SettingsModal.tsx`**

Add `import { nextSettingsTabIndex } from "@/components/shell/shellModel"`, and inside `SettingsModal`:

```tsx
/** Design A: arrow keys move between sections (up/down on the rail,
 * left/right on the phone strip), Home/End jump; switching replaces history. */
function handleTabKeys(event: ReactKeyboardEvent<HTMLElement>) {
  const links = Array.from(event.currentTarget.querySelectorAll<HTMLAnchorElement>("a"))
  const next = nextSettingsTabIndex(links.indexOf(document.activeElement as HTMLAnchorElement), event.key, links.length)
  if (next === null) return
  event.preventDefault()
  links[next].focus()
  links[next].click()
}
```

and add `onKeyDown={handleTabKeys}` to both `<nav aria-label="Settings sections" …>` elements. In the dialog panel's class list, change `md:rounded-card md:border md:border-outline-variant md:shadow-[var(--shadow-float)]` to `md:rounded-card md:shadow-[var(--shadow-panel)]` (design A `.as-modal`: `border: 0`, `box-shadow: var(--shadow-panel)`, whose 1px ring already draws the edge). This also changes the teacher dialog (logged under `teacher-settings-*`).

- [ ] **Step 4: Student settings route, overlay and content routes in `web/src/portals/student/index.tsx`**

Replace the lazy `PortalSettingsLayout` and `DeviceSettingsSection` constants with lazy `SettingsModalRoute`, `AccountSettingsSection` and `AppearanceSettingsSection` (same per-module lazy pattern the teacher file uses), import `STUDENT_SETTINGS_TABS`, and `STUDENT_SETTINGS_BASE` from `./shell`. Replace the `settings` route object with:

```tsx
{
  // A dialog over the current page: PortalShell's ScreenOutlet overlay renders
  // the page underneath, this route renders the dialog. One child per entry in
  // STUDENT_SETTINGS_TABS; settingsTabs.test.ts holds the two in step.
  path: "settings",
  element: <SettingsModalRoute tabs={STUDENT_SETTINGS_TABS} basePath={STUDENT_SETTINGS_BASE} fallbackPath="/student" />,
  handle: { title: "Settings", skeleton: "page-header" },
  children: [
    {
      index: true,
      // Appearance has its own tab here, so not inside Profile.
      element: <ProfileSettingsSection appearance={false} />,
      handle: { title: "Profile settings", skeleton: "page-header" },
    },
    { path: "devices", element: <AccountSettingsSection />, handle: { title: "Account and devices", skeleton: "page-header" } },
    { path: "notifications", element: <NotificationSettingsSection />, handle: { title: "Notification settings", skeleton: "page-header" } },
    { path: "appearance", element: <AppearanceSettingsSection />, handle: { title: "Appearance", skeleton: "page-header" } },
    { path: "install", element: <InstallSettingsSection />, handle: { title: "Install Lemely", skeleton: "page-header" } },
  ],
},
```

Add, after `studentRoute`:

```tsx
let contentRoutesCache: RouteObject[] | null = null

/** The portal's child routes minus the settings dialog, matched against the
 * page underneath while the dialog is open. Built on first use because
 * `studentRoute` is declared after the layout that reads it. */
function studentContentRoutes(): RouteObject[] {
  contentRoutesCache ??= (studentRoute.children ?? []).filter((route) => route.path !== "settings")
  return contentRoutesCache
}
```

and in `StudentLayout` pass `overlay={{ routes: studentContentRoutes(), overlayBase: STUDENT_SETTINGS_BASE, fallbackPath: "/student" }}` to `StudentShell`.

- [ ] **Step 5: Crumbs, Profile link, e2e spec**

- `web/src/portals/student/data.ts` `crumbs`: add `"/student/settings/appearance": "Home / Settings / Appearance"` and `"/student/settings/install": "Home / Settings / Install Lemely"`.
- `web/src/portals/student/screens/Profile.tsx` line 480: add `const overlayState = useOverlayState()` at the component top (import from `@/lib/nav/useOverlayState`) and change the call to `navigate("/student/settings/devices", { state: overlayState })`, so the dialog opens over Profile and closing returns there.
- `web/e2e/theme.spec.ts`: change the three `page.goto("/student/settings")` to `page.goto("/student/settings/appearance")` (the theme radios moved from Profile to the Appearance tab, as in the teacher dialog).

- [ ] **Step 6: Settings behaviour checks (append to `checks-shell.mjs`)**

```js
SHELL_CHECKS.push(
  {
    id: "student-settings-opens-over-the-page-and-closes-back",
    app: { ...STUDENT_HOME, path: "/student/friends" },
    async run(page) {
      await page.evaluate(() => {
        document.body.style.minHeight = "3000px"
        window.scrollTo(0, 300)
      })
      const gear = page.getByRole("link", { name: "Settings" })
      await gear.click()
      const dialog = page.getByRole("dialog", { name: "Settings" })
      await dialog.waitFor()
      if (new URL(page.url()).pathname !== "/student/settings") throw new Error(`URL is ${page.url()}`)
      const title = await page.locator("header p").first().textContent()
      if (title !== "Friends") throw new Error(`top bar title under the dialog is "${title}", expected Friends`)
      await page.keyboard.press("Escape")
      await assertHidden(dialog, "settings dialog")
      if (new URL(page.url()).pathname !== "/student/friends") throw new Error(`closed to ${page.url()}`)
      const y = await page.evaluate(() => window.scrollY)
      if (y !== 300) throw new Error(`page underneath scrolled to ${y}, expected 300`)
      await assertFocused(gear, "gear")
    },
  },
  {
    id: "student-settings-fresh-load-opens-over-home",
    app: { ...STUDENT_HOME, path: "/student/settings/appearance" },
    async run(page) {
      const dialog = page.getByRole("dialog", { name: "Settings" })
      await dialog.waitFor()
      const current = dialog.locator('nav[data-settings-tabs="rail"] a[aria-current="page"]')
      if ((await current.textContent()) !== "Appearance") throw new Error("fresh load: Appearance tab is not current")
      await dialog.getByRole("button", { name: "Close settings" }).last().click()
      await assertHidden(dialog, "settings dialog")
      if (new URL(page.url()).pathname !== "/student") throw new Error(`fresh load closed to ${page.url()}`)
    },
  },
  {
    id: "student-settings-arrow-keys-and-focus-trap",
    app: { ...STUDENT_HOME, path: "/student/settings" },
    async run(page) {
      const dialog = page.getByRole("dialog", { name: "Settings" })
      await dialog.waitFor()
      await page.waitForFunction(() => document.activeElement?.getAttribute("aria-current") === "page")
      await page.keyboard.press("ArrowDown")
      await page.waitForURL("**/student/settings/devices")
      const focused = await page.evaluate(() => document.activeElement?.textContent)
      if (focused !== "Account and devices") throw new Error(`ArrowDown focused "${focused}"`)
      await page.keyboard.press("End")
      await page.waitForURL("**/student/settings/install")
      for (let i = 0; i < 40; i++) {
        await page.keyboard.press("Tab")
        if (!(await dialog.evaluate((el) => el.contains(document.activeElement)))) {
          throw new Error(`settings: focus left the dialog after ${i + 1} Tab presses`)
        }
      }
    },
  },
  {
    id: "teacher-settings-arrow-keys",
    app: { ...TEACHER_HOME, path: "/teacher/settings" },
    async run(page) {
      await page.getByRole("dialog", { name: "Settings" }).waitFor()
      await page.waitForFunction(() => document.activeElement?.getAttribute("aria-current") === "page")
      await page.keyboard.press("ArrowUp")
      await page.waitForURL("**/teacher/settings/install")
    },
  },
)
```

- [ ] **Step 7: Student settings scenes (append to `STUDENT_SCENES` in `scenes-shell.mjs`)**

```js
...[
  ["profile", ""],
  ["account", "/devices"],
  ["notifications", "/notifications"],
  ["appearance", "/appearance"],
  ["install", "/install"],
].map(([tab, suffix]) => ({
  id: `student-settings-${tab}`,
  kind: "preview-vs-app",
  capture: "frame",
  app: student("populated", { path: `/student/settings${suffix}` }),
  preview: {
    state: "populated",
    act: async (page) => {
      await page.click('[data-a-open="as-settings"]')
      await page.click(`[data-a-tab="${tab}"]`)
    },
  },
})),
```

- [ ] **Step 8: Run tests, behaviour, drift**

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/student-home-variants/web
npx vitest run tests/unit/settingsTabs.test.ts tests/unit/navigation.test.ts tests/unit/notFoundFallback.test.ts tests/unit/backgroundLocation.test.ts tests/unit/overlayExit.test.ts tests/unit/shellModel.test.ts tests/unit/studentShell.test.ts tests/unit/routeSkeleton.test.ts
npm run typecheck && npx oxlint src/portals/settings src/portals/student
npm run build
node scripts/shell-behaviour.mjs
node scripts/home-drift.mjs --scene student-settings-
node scripts/home-drift.mjs --scene teacher-settings-
```

Expected: tests pass; all behaviour checks pass. Drift: fix the frame (rail, tabs, header, close buttons, title block) to 0 px where you can. The section bodies are the real settings sections (`ProfileSettingsSection`, `AccountSettingsSection`, …), shared with the teacher dialog; where a body differs from design A's demo rows, either fix it in the shared section (and accept the matching `teacher-settings-*` change, logged) or log it with a justification such as "real device list from `GET /me/devices`; design shows two demo devices". Keep each key ≤15%. Teacher settings keys must also exit 0 (log the border removal and any section change). If a local Supabase stack is up (`supabase status` answers), run `npx playwright test e2e/theme.spec.ts`; otherwise state in the report that it was not run and why.

- [ ] **Step 9: Commit**

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/student-home-variants
FILES="web/src/portals/settings/settingsTabs.ts web/src/portals/settings/SettingsModal.tsx web/src/portals/student/index.tsx web/src/portals/student/data.ts web/src/portals/student/screens/Profile.tsx web/e2e/theme.spec.ts web/tests/unit/settingsTabs.test.ts web/scripts/drift/scenes-shell.mjs web/scripts/drift/checks-shell.mjs web/scripts/drift/justifications.json"
/home/sico/Code/Lemely/.venv/bin/pre-commit run --files $FILES
git commit -S -m "feat(web): student settings open as a dialog by URL; arrow keys move between tabs" -- $FILES
```

---

### Task 8: Orphan sweep

Unused locals were removed where they went dead (Tasks 3 to 7), but an exported symbol whose last importer went away is invisible to the typechecker. This task finds and removes those, nothing else.

**Files:** only files that hold an orphaned export (expected candidates below), plus tests that pinned them.

**Interfaces:** none produced.

- [ ] **Step 1: List candidates and their remaining users**

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/student-home-variants/web
for s in NavDrawerTrigger BackControl XPStreak SidebarNav ClassesNavList TOP_BAR_ICON_BUTTON ProfileAvatarPlaceholder PROFILE_AVATAR_BOX IconTile formatAge PortalSettingsLayout DeviceSettingsSection SHEET_FOCUS_RING; do
  printf '%-26s %s\n' "$s" "$(grep -rln "\b$s\b" src tests e2e scripts | tr '\n' ' ')"
done
```

Expected: each symbol's definition file plus any remaining users. A symbol whose only hit is its own definition (or its definition plus a barrel re-export) is an orphan.

- [ ] **Step 2: Remove true orphans; report the rest**

Delete an orphaned export (and its file if the file becomes empty), and any test assertion that only pinned its existence. Do NOT delete:
- `PortalSettingsLayout` or `DeviceSettingsSection`: still referenced by `routes.tsx`, the settings barrel and `notFoundFallback.test.ts` (the top-level `/settings` lane). List them in the report as a follow-up question for the user instead.
- `SidebarNav` and its `abyss` variant if the admin portal still uses them.

- [ ] **Step 3: Verify**

Run the **Shell sweep command** (Global Constraints), then `npm run typecheck && npm run lint && npm run build`.
Expected: all pass; build within the bundle budget.

- [ ] **Step 4: Commit (only if something was removed)**

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/student-home-variants
/home/sico/Code/Lemely/.venv/bin/pre-commit run --files <removed or edited files>
git commit -S -m "refactor(web): remove exports orphaned by the shared shell" -- <removed or edited files>
```

---

### Task 9: Final verification, axe sweep and drift log

**Files:**
- Modify: `docs/superpowers/specs/2026-11-06-portal-shell-design.md` (drift log; decisions recorded in Task 0)
- Modify: `web/scripts/drift/justifications.json` (approval states)

**Interfaces:** none produced; this task certifies the tree it runs on. If any later fix commit lands, re-run this task from Step 1.

- [ ] **Step 1: Re-check where you are**

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/student-home-variants
git status --short --branch
```

Expected: clean apart from the staged preview files if the user chose option 3 in Task 0, and the untracked `.impeccable/` folders.

- [ ] **Step 2: Derive the web gate list from CI and run each one that needs no backend**

```bash
grep -nE "run:|npm run|npx " .github/workflows/ci.yml | grep -iE "web|npm|npx"
```

Run every web gate listed there that does not need the backend or Supabase (expected at least: `npm run typecheck`, `npm run lint`, `npm run check:copy`, `npm run check:native`, `npm run build` with its `check:bundle`), from `web/`. Do not run the full Vitest suite; run the **Shell sweep command** instead. Expected: every command exits 0. Report any CI gate you could not run locally and why.

- [ ] **Step 3: Behaviour and axe**

```bash
cd web && npm run build && node scripts/shell-behaviour.mjs --axe
```

Expected: every check `pass` with no axe violations (the checks leave the shell in its interaction states: bell open, account open, drawer open, settings tabs, both portals). Fix any violation in the component, not by excluding the rule.

- [ ] **Step 4: Full drift run**

```bash
node scripts/home-drift.mjs --scene teacher-,student-
```

Expected: exit 0; no `fail`; every non-zero key `pass-justified`. Teacher content keys 0 px (or justified ≤15% with a reason that is a shell change, never a page-content change).

- [ ] **Step 5: Write the drift log into the spec**

Replace the spec's "Drift log" table with the rows of the run's `report.md` (path printed by the script), one row per scene id (collapse windows and themes into one row when the justification is the same; give the max %). Correct the bottom-tab row: design A has its own 4-item phone bar at 720px and below; the app keeps `BottomNav` (5 tabs) below 820px (user decision 2026-11-06), with the measured %. Add a "Not captured" note for hover colours (design A's `--surface-hover-tint` mapped to `surface-container`) and the pre-mount shell (`index.html` still paints the 252px / 820px sidebar before React mounts; see Risks below).

- [ ] **Step 6: Ask the user to approve the pending rows (blocking for "Approved")**

List every row whose `approved` is `"pending"` with its % and justification, and ask the user to approve or reject each (AskUserQuestion when available). Set `approved` to `"yes"` for approved rows in both `justifications.json` and the spec. Rejected rows are drift to fix: fix, rebuild, re-run Steps 3 and 4.

- [ ] **Step 7: Commit**

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/student-home-variants
/home/sico/Code/Lemely/.venv/bin/pre-commit run --files docs/superpowers/specs/2026-11-06-portal-shell-design.md web/scripts/drift/justifications.json
git commit -S -m "docs(web): portal shell drift log" -- docs/superpowers/specs/2026-11-06-portal-shell-design.md web/scripts/drift/justifications.json
```

Do not push.

---

## Risks and spec gaps found while planning

1. **Drawer breakpoint.** Spec: "drawer below 1248px". Design A CSS: 1000px. The plan uses 1001px (`shell-lg`) and asks the user in Task 0.
2. **Design A's phone bar.** The spec's drift log says the design has no bottom bar; it has a 4-item `.a-bottombar` at 720px and below. The app keeps `BottomNav` below 820px (decision); between 721 and 819px both the menu button and the tab bar show.
3. **`TopBarSheets` on `develop` is the teacher Create sheet**, not "phone sheets for the panels"; design A has no phone panel sheets (panels drop under the bar). The plan moves it as a generic `ActionSheet`.
4. **Student destinations without a home in design A**: Tutors and Sessions (Task 0 question); the subject page itself is no longer linked from the sidebar (design A's subject row is a disclosure button only).
5. **Streak gap**: removing `HeaderStreak` before the Overview hero exists hides the streak at `sm` and up until the Overview plan ships.
6. **No DOM in Vitest** (D3.20): behaviour tests live in `web/scripts/shell-behaviour.mjs` (Playwright, mocked API), not in Testing Library.
7. **Data the design shows that the API does not have**: short subject names ("Add Maths"), the ring percentage's meaning (`SubjectRow.pct` is used), today's session subject (opens a subject by default), a friend notification type, mono spans inside titles.
8. **Teacher frame scenes cannot meet the 15% cap**: the page ground changes from `surface` to `surface-container` under the whole page. Teacher frames are log-only; teacher content scenes are gated (with a neutral background so the ground change cannot leak in).
9. **Pre-mount shell**: `web/vite/preMountShell.ts` fills `index.html` from `--sidebar-width` (252px) and `--breakpoint-sidebar` (820px), so the first paint before React mounts shows the old sidebar geometry for student and teacher. Fixing it touches the admin portal's shell too; left as a follow-up.
10. **Circle avatar** contradicts DESIGN.md §6 (Task 0 question).
11. **New dev dependencies**: `pixelmatch`, `pngjs`. The preview server config uses port 5199; the drift script starts it on 5180 explicitly.
