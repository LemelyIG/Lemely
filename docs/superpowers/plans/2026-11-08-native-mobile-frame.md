# Native Mobile Frame Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Below the `shell-sm` breakpoint (720px and narrower), on iPhone and Android, the student and teacher portals run in a native frame. That frame has a pinned large-title header that collapses, a per-platform tab bar, bottom sheets instead of dialogs and popovers, edge-to-edge grouped lists, press feedback, swipe-back and pull-to-refresh. Desktop, tablet and the `other` platform keep design A unchanged.

**Architecture:** A boot-time resolver in `public/shell-init.js` sets `html[data-platform="ios|android|other"]` before first paint. Tailwind v4 custom variants (`ios:`, `android:`, and `native:` = phone width AND ios|android) and a `useNativeFrame()` hook key every change off it. There are no separate component trees. `ShellTopBar`, `BottomNav`, `Modal`, `ConfirmModal`, `Sheet`, the shell panels, `Popover`, `Card` and the new `ListGroup`/`ListRow` vary by unlayered `lm-native-*` classes, `native:` utilities, and one JS switch where the markup has to differ (sheets). The design A preview, `student-home-a.html` with `?platform=ios|android&page=root|detail`, is the reference. The existing drift gate gains platform emulation (UA, touch, mobile) and a native scene list. Every UI task is accepted against it. The desktop and `other`-platform scenes must stay exactly as they are.

**Tech Stack:** React 19, react-router-dom 7, TanStack Query 5, Radix (`radix-ui`), Tailwind v4 (`@theme inline` tokens and `@custom-variant` in `web/src/index.css`), Phosphor icons (`regular`/`fill` weights), Vitest 4 (Node, no DOM), Playwright 1.62 + pixelmatch (existing drift harness and behaviour runner).

## Inputs

- Spec: `docs/superpowers/specs/2026-11-08-native-mobile-feel-brief.md` (confirmed 2026-11-08). Its user decisions bind this plan:
  1. Update the preview first, then port under the drift gate.
  2. This frame lands **before** P2 (`docs/superpowers/plans/2026-11-06-student-home-overview.md`).
  3. Brand fonts everywhere, with no SF Pro.
  4. Teachers get the same frame.
  5. DESIGN.md replaces "drawer for teachers" when the frame lands.
- Prior shell: `docs/superpowers/specs/2026-11-06-portal-shell-design.md`, `docs/superpowers/plans/2026-11-06-portal-shell.md` (P1, done through Task 8 at `1c7cc095`), and the ledger `.superpowers/sdd/progress.md`.
- Base commit for this plan: `ba79e15c` on `design/student-home-variants`.

## Global Constraints

- Everything in `.superpowers/sdd/p1-global-constraints.md` still holds. In particular, it covers the drift rule as built, **Drift acceptance**, signed commits, pre-commit, "never the full test suite", Node-only Vitest (no DOM, no Testing Library), no em dashes in UI copy, and the working directory. Copied here where a task depends on the exact wording:
  - Gate scenes (no `rule`) pass at 0 px. With an entry in `web/scripts/drift/justifications.json` whose `approved` is `"yes"`, they also pass up to 15%. Over 15% always fails.
  - Log scenes (`rule: "log"`) have no cap, but still need an entry with `approved: "yes"`.
  - Implementers write new or changed entries with `"approved": "pending"`. **They never set `"yes"`.** Only Task 16 does, after the user approves. Editing an entry's `difference` or `justification` resets it to `"pending"`.
  - **Drift acceptance:** every key is `pass` or `pass-justified`, or is a `fail` whose reason is exactly `justified but approval is pending (approved must be "yes")`. To list the failures that are not pending approval, run from the repo root: `node -e 'for(const k of require(require("path").resolve(process.argv[1],"report.json")))if(k.outcome==="fail"&&!/approval is pending/.test(k.reason))console.log(k.key,k.reason)' <dir>`. Expected output: nothing.
- **Scope gate (new):** the native frame applies only when the width is at most 720px **and** `html[data-platform]` is `ios` or `android`. Desktop, tablet (721px and up) and `other` at any width keep design A. Every existing drift scene runs with no UA override, which resolves to `other`. **Every existing `student-*` and `teacher-*` key must produce the same outcome after each task as before it.** Desktop keys stay at 0 px.
- Brand stays: Abyss/Tide, Clip Letters, Bricolage (display, at least 28px), Schibsted (UI), JetBrains Mono (data). Never SF Pro, never a system font in the chrome, never an iOS-blue accent, never Material You dynamic colour. No emoji, no confetti.
- No bottom sheets at 721px and up. No gesture may start on selectable content text: gestures start on chrome, a grabber or an edge zone, never mid-paragraph.
- All motion stops under `prefers-reduced-motion`. That covers the collapse fade (it becomes a step at the threshold), sheet slides, the scale-back animation, swipe parallax, the ripple and view-transition slides.
- Accessibility: sheets keep the existing dialog contract, `role="dialog"`, `aria-modal`, a label, a focus trap, focus returned to the trigger, and Escape plus browser Back closing (`useDialogHistory`). Targets are at least 44px on coarse pointers. A collapsed bar keeps a readable title. RTL mirrors the swipe-back edge and all logical properties.
- Styling: Tailwind v4 with the existing tokens. New raw values go in **one** `:root` block, "Native frame tokens" (Task 0). Components never inline a raw px or colour for the native frame. The only blur is `var(--blur-nav)` (DESIGN §3.2 item 6, enforced by `elevationScale.test.ts`).
- Commits: `SKIP=import-linter git commit -S -m "<conventional message>" -- <explicit paths>`, after `/home/sico/Code/Lemely/.venv/bin/pre-commit run --files <paths>`. Run git commands one at a time, with no `&&` chains. Never `git add -A`, never bare `git stash`, never push.
- Tests: run only named files, `cd web && npx vitest run tests/unit/<file>.test.ts …`. Vitest's `include` is `tests/unit/**/*.test.ts`, so test files are `.ts` and render with `createElement` + `renderToStaticMarkup`. Browser behaviour goes in the Playwright behaviour runner: `web/scripts/shell-behaviour.mjs` over `drift/checks-shell.mjs` plus the new `drift/checks-native.mjs`.
- Build before every drift or behaviour run: `cd web && npm run build` (the harness serves `dist/`).
- Every UI task ends with the **Native sweep command** below, the touched-file tests, and a drift run of `--scene native-` plus `--scene student-,teacher-` (the existing scenes, which must not move).

**Native sweep command** (a named list, not the full suite; drop files that do not exist yet):

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/student-home-variants/web && npx vitest run \
  tests/unit/platform.test.ts tests/unit/nativeFrameCss.test.ts tests/unit/nativeTopBar.test.ts \
  tests/unit/nativeTabBar.test.ts tests/unit/sheetMath.test.ts tests/unit/nativeSheets.test.ts \
  tests/unit/listGroup.test.ts tests/unit/pressFeedback.test.ts tests/unit/edgeSwipeBack.test.ts \
  tests/unit/shellPullToRefresh.test.ts tests/unit/tableOrList.test.ts \
  tests/unit/nativeMechanics.test.ts tests/unit/checkNativeInvariants.test.ts tests/unit/themeInit.test.ts \
  tests/unit/navShells.test.ts tests/unit/shellPanels.test.ts tests/unit/studentShell.test.ts \
  tests/unit/shellTopBarGlass.test.ts tests/unit/teacherTopBarSheets.test.ts tests/unit/overlayExit.test.ts \
  tests/unit/a11yRules.test.ts tests/unit/contrastRules.test.ts tests/unit/elevationScale.test.ts \
  tests/unit/adaptRules.test.ts tests/unit/motionDefaults.test.ts tests/unit/utilityExistence.test.ts \
  tests/unit/rtlSafety.test.ts tests/unit/design-tokens.test.ts tests/unit/darkConsumers.test.ts \
  tests/unit/hoverTransition.test.ts
```

## Decisions made while planning (for the user)

These are planner decisions where the brief left room or conflicted with the code. Each is restated in the task that implements it.

- **D1. `other` keeps design A at every width.** The brief says "Desktop and `other` keep design A". So a narrow desktop window, or any unrecognised phone browser, shows today's flat design A phone bar, not the native frame. Consequence: all 390px scenes recorded so far run as `other` and stay untouched. The native frame gets its own scenes with UA emulation.
- **D2. Page title API: no new route field.** `ShellTopBar` keeps `title` and derives the level from the existing trail: `titleLevel = trail.length > 1 ? "detail" : "root"`. An optional `titleLevel` prop overrides it. Root pages get the large title. Detail pages get the compact bar with a leading back chevron. The bar renders the chevron itself on native from a new required `backFallback` prop (the portal root). Student's existing in-actions `BackControl` gets `native:hidden`.
- **D3. The large title lives outside `<main>`**, in `ShellTopBar`'s fragment, and is `aria-hidden="true"`. The bar's inline title stays the accessible name, so screen readers do not hear it twice. This also keeps it in the drift harness's "frame" capture, which hides `main > *`.
- **D4. Select stays a native `<select>`.** The brief lists selects among the sheets, but `ui/select.tsx` is deliberately native. Its doc comment records why: the OS picker on iOS and Android already is the platform's own sheet or wheel. A custom listbox sheet would be a worse picker and would re-implement typeahead and screen-reader semantics. Task 9 makes only Popover a sheet and pins Select as native with a test. If the user wants a custom select sheet anyway, it becomes a follow-up.
- **D5. Edge swipe-back = iOS standalone only.** The brief's rule is "all phone sessions where the browser has no own back gesture; defer to iOS Safari tabs and Android system back". Applied literally, that leaves iOS (and iPadOS) standalone, where swipe-back is installed with the new interactive parallax. It is **removed** on Android standalone, where it competed with the system back gesture. Today's gate is "any standalone". So this narrows it, even though the brief's wording says "extends".
- **D6. Pull-to-refresh moves into the shell.** One `ShellPullToRefresh` wraps `<main>` content on root-level pages (`titleLevel === "root"`) in both portals. It refetches active queries. This covers "every list and overview root" without wiring 15 screens by hand. The three per-screen copies (student Overview, Notifications, Announcements) are removed, so two gestures never nest.
- **D7. Status bar `black-translucent` flips three pinned gates.** `nativeMechanics.test.ts`, `checkNativeInvariants.test.ts` and `scripts/check-native-invariants.mjs` currently assert `"default"`. The meta only affects iOS home-screen apps, so standalone mode is the only place it matters. Task 3 flips the gates and pads every non-shell standalone root with the top safe-area inset.
- **D8. Immersive routes hide the tab bar on native:** student `correct` (camera and correction run), student paper result (paper review) and teacher review-a-mark. A route opts in with `handle.immersive: true`.
- **D9. Phone scene sizes.** The user's instruction is 390×844 for **both** platforms (gate scenes). The brief's proof also asks for 412×915 on Android. That is added as a log-only scene (`native-android-412-*`) so the screenshot exists without gating on a size the preview may not tune.
- **D10. Sheet dismissal thresholds:** a drag of more than 25% of the sheet's height, or a fling faster than 0.5 px/ms, dismisses. Otherwise the sheet snaps to the nearest detent. Swipe-back commits at 35% of width or the same fling (the brief's number). Non-dismissible dialogs (`ConfirmModal`) get no grabber and no drag.

## Open questions (not blocking; record answers in the ledger)

- [ ] Should a screen's own top `<h1>` that repeats the large title be visually hidden on native? Many of the 93 screens hand-roll an `<h1>`, and some will read twice visually (large title plus page heading). Task 10 hides only the shared shapes it touches. A per-screen sweep is a follow-up, or it can wait for P2's new home.
- [ ] Do Android standalone users want an in-app swipe-back at all (D5)? The default is no: the system back is reliable there.
- [ ] Should the paper result route be immersive (D8) or keep the tab bar? It is a long reading page.

## File structure

Create:

| File | Responsibility |
|---|---|
| `web/src/lib/platform.ts` | `Platform`, `resolvePlatform`, `readPlatform`: pure platform resolution (shell-init.js mirrors it in ES5). |
| `web/src/lib/useNativeFrame.ts` | `useNativeFrame()`, `isNativeFrame`, `NativeFrameProvider` (test override), `PHONE_MEDIA`. |
| `web/scripts/drift/native-preview.mjs` | Selectors and query builder for the preview's phone frame (filled from the committed preview in Task 0). |
| `web/scripts/drift/scenes-native.mjs` | `NATIVE_SCENES`: app vs preview per platform at 390×844, plus the log-only Android 412×915. |
| `web/scripts/drift/checks-native.mjs` | `NATIVE_CHECKS`: platform resolution, collapse, tab re-tap, sheets, swipe-back, pull-to-refresh. |
| `web/src/components/shell/largeTitle.ts` | Pure: `titleLevelFor`, `largeTitleCollapsed`. |
| `web/src/components/shell/useLargeTitleCollapse.ts` | Scroll listener and rAF fallback; writes `--lm-large-title-block`. |
| `web/src/components/shell/tabTap.ts` | Pure: `activeTabTap`. |
| `web/src/lib/gestures/sheetMath.ts` | Pure: detents, release decision, swipe-back release. |
| `web/src/components/ui/bottom-sheet.tsx` | `BottomSheetSurface`, `SheetGrabber`, `useSheetScaleBack`, `useKeyboardInset`. |
| `web/src/components/shell/PanelSheet.tsx` | Bell and avatar panel content as a native sheet. |
| `web/src/components/ui/list-group.tsx` | `ListGroup`, `ListRow` (iOS inset-grouped, Android full-width). |
| `web/src/lib/pressFeedback.ts` | `pressOrigin` (pure), `installPressFeedback` (one delegated listener). |
| `web/src/components/shell/ShellPullToRefresh.tsx` | Shell-level pull-to-refresh for root pages. |
| `web/src/components/ui/table-or-list.tsx` | `TableOrList`: list rows on native, with a "View table" escape hatch. |
| `web/tests/unit/{platform,nativeFrameCss,nativeTopBar,nativeTabBar,sheetMath,nativeSheets,listGroup,pressFeedback,edgeSwipeBack,shellPullToRefresh,tableOrList}.test.ts` | Unit tests. |

Modify: `web/public/shell-init.js`, `web/index.html`, `web/src/index.css`, `web/scripts/drift/harness.mjs`, `web/scripts/drift/scenes.mjs`, `web/scripts/shell-behaviour.mjs`, `web/scripts/check-native-invariants.mjs`, `web/scripts/drift/justifications.json`, `web/src/components/shell/{ShellTopBar,PortalShell,NotificationsPanel,AccountPanel,shellStyles}.tsx|ts`, `web/src/components/ui/{nav-shells,modal,confirm-modal,sheet,popover,card,button,select}.tsx`, `web/src/components/edge-swipe-back.tsx`, `web/src/lib/nav/edgeSwipeBack.ts`, `web/src/lib/haptics.ts`, `web/src/lib/gestures/useLongPress.ts`, `web/src/portals/settings/{SettingsModal,SettingsRows}.tsx`, `web/src/portals/student/{shell.tsx,index.tsx}`, `web/src/portals/teacher/index.tsx`, student `Overview`/`Notifications`/`Announcements` screens (PTR removal), teacher table screens (Tasks 14 and 15), `web/tests/unit/{nativeMechanics,checkNativeInvariants,themeInit}.test.ts`, `DESIGN.md`, `docs/superpowers/plans/2026-11-06-student-home-overview.md` (adjustment note only).

## Per-task model suggestion

| Task | Implement | Review |
|---|---|---|
| 0 tokens from preview | sonnet | opus (low) |
| 1 platform resolver | sonnet | opus |
| 2 harness and native scenes | sonnet | opus |
| 3 PWA meta and touch CSS | sonnet | opus |
| 4 large-title header | sonnet (high effort) | opus |
| 5 tab bar | sonnet | opus |
| 6 sheet primitive | sonnet (high effort) | opus |
| 7 Modal / ConfirmModal sheets | sonnet | opus |
| 8 panels and settings sheets | sonnet | opus |
| 9 Popover sheet, Select native | sonnet | opus (low) |
| 10 grouped lists | sonnet | opus |
| 11 press states | sonnet | opus |
| 12 swipe-back | sonnet (high effort) | opus |
| 13 pull-to-refresh and haptics | sonnet | opus |
| 14 table-or-list primitive | sonnet | opus |
| 15 table rollout | sonnet (one agent per 2 to 3 screens, parallel, disjoint commit paths) | opus |
| 16 final verification and approvals | sonnet | opus |
| 17 DESIGN.md and P2 note | sonnet | opus (low) |

Waves: 0 → 1 → 2 → 3, then {4, 6} in parallel (disjoint files), then 5 after 4, {7, 8, 9} after 6, then {10, 11}, {12, 13}, then 14 → 15, 16, 17. Parallel agents must be given their commit paths up front (they share one index).

---

### Task 0: Pull exact values from the committed preview into tokens

The designer agent is adding the phone frame to `web/dev-previews/student-home-a.html`, with `?platform=ios|android&page=root|detail`. This task starts only after that work is **committed**. Never read uncommitted preview edits.

**Files:**
- Modify: `web/src/index.css` (one new `:root` block, "Native frame tokens", directly after the `@theme inline` blocks)
- Create: `web/scripts/drift/native-preview.mjs`
- Create: `web/tests/unit/nativeFrameCss.test.ts` (token part; Task 1 extends it)

**Interfaces:**
- Consumes: the committed preview HTML, CSS and JS for the phone frame.
- Produces:
  - CSS custom properties: `--native-large-title-size`, `--native-large-title-lh`, `--native-inline-title-size`, `--native-bar-h-ios`, `--native-bar-h-android`, `--native-bar-pad-inline`, `--native-tabbar-h-ios`, `--native-tabbar-h-android`, `--native-tab-label-size`, `--native-tab-pill-w`, `--native-tab-pill-h`, `--native-grabber-w-ios`, `--native-grabber-h-ios`, `--native-grabber-w-android`, `--native-grabber-h-android`, `--native-group-radius-ios`, `--native-group-inset`, `--native-row-min-ios`, `--native-row-1-android`, `--native-row-2-android`, `--native-row-3-android`, `--native-press-dim`, `--native-state-pressed`, `--native-press-scale`, `--native-sheet-scale-back`, `--native-sheet-medium`, `--native-parallax`, `--native-hairline`, `--ease-ios-spring`, `--ease-m3-emphasized`, `--dur-sheet`.
  - `native-preview.mjs` exports `NATIVE_PREVIEW` (selectors: `bar`, `largeTitle`, `inlineTitle`, `back`, `bell`, `settings`, `avatar`, `sheet`, `tabbar`) and `previewNativeQuery({ state, theme, platform, page })` (`URLSearchParams`).

- [ ] **Step 1: Confirm the preview is committed and find its phone-frame rules**

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/student-home-variants
git status --short web/dev-previews
git log --oneline -5 -- web/dev-previews/student-home-a.html web/dev-previews/student-home
```

Expected: no `M` lines for `web/dev-previews/` (anything uncommitted means stop and report), and a recent designer commit that mentions the phone frame. Then list the preview's phone-frame selectors and custom properties:

```bash
grep -nE "platform|data-page|large-title|grabber|tabbar|sheet" web/dev-previews/student-home/variant-a.css | head -80
grep -nE "platform|page" web/dev-previews/student-home/controller.ts | head -40
```

- [ ] **Step 2: Write the token test (fails: block missing)**

```ts
// web/tests/unit/nativeFrameCss.test.ts
import { readFileSync } from "node:fs"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

const SRC = join(fileURLToPath(new URL("../../", import.meta.url)), "src")
export const css = readFileSync(join(SRC, "index.css"), "utf8")

const TOKENS = [
  "--native-large-title-size", "--native-large-title-lh", "--native-inline-title-size",
  "--native-bar-h-ios", "--native-bar-h-android", "--native-bar-pad-inline",
  "--native-tabbar-h-ios", "--native-tabbar-h-android", "--native-tab-label-size",
  "--native-tab-pill-w", "--native-tab-pill-h",
  "--native-grabber-w-ios", "--native-grabber-h-ios", "--native-grabber-w-android", "--native-grabber-h-android",
  "--native-group-radius-ios", "--native-group-inset", "--native-row-min-ios",
  "--native-row-1-android", "--native-row-2-android", "--native-row-3-android",
  "--native-press-dim", "--native-state-pressed", "--native-press-scale",
  "--native-sheet-scale-back", "--native-sheet-medium", "--native-parallax", "--native-hairline",
  "--ease-ios-spring", "--ease-m3-emphasized", "--dur-sheet",
]

function tokenBlock(): string {
  const start = css.indexOf("/* ── Native frame tokens")
  if (start < 0) return ""
  const open = css.indexOf(":root {", start)
  return css.slice(open, css.indexOf("\n}", open) + 2)
}

describe("native frame tokens (Task 0)", () => {
  it("one :root block declares every token once", () => {
    const block = tokenBlock()
    expect(block).not.toBe("")
    for (const t of TOKENS) {
      expect(block, t).toMatch(new RegExp(`${t}:\\s*[^;]+;`))
      expect(css.split(`${t}:`).length - 1, `${t} declared once`).toBe(1)
    }
  })

  it("the large title is display size (Bricolage is allowed at 28px and up)", () => {
    const size = tokenBlock().match(/--native-large-title-size:\s*(\d+)px/)
    expect(Number(size?.[1])).toBeGreaterThanOrEqual(28)
  })
})
```

Run: `cd web && npx vitest run tests/unit/nativeFrameCss.test.ts`
Expected: FAIL (block missing).

- [ ] **Step 3: Add the token block, with the preview's exact values**

Seed it with the brief's numbers below. Then replace **each** value with the one the committed preview uses (Step 1 output), and cite the preview's line in a trailing comment. Where the preview has no value, keep the brief's number and mark the comment `brief §N`.

```css
/* ── Native frame tokens (docs/superpowers/plans/2026-11-08-native-mobile-frame.md, Task 0).
   Values pulled from the committed design A preview (student-home-a.html,
   ?platform=ios|android). Raw px for the native frame live here and nowhere else. */
:root {
  --native-large-title-size: 34px;   /* brief §3.1: Bricolage 800 */
  --native-large-title-lh: 41px;
  --native-inline-title-size: 17px;  /* brief §3.1: Schibsted 600 */
  --native-bar-h-ios: 44px;
  --native-bar-h-android: 64px;
  --native-bar-pad-inline: 16px;
  --native-tabbar-h-ios: 49px;       /* brief §3.2, plus the home indicator inset */
  --native-tabbar-h-android: 80px;   /* brief §3.2: 80dp */
  --native-tab-label-size: 11px;
  --native-tab-pill-w: 64px;         /* brief §3.2: M3 active indicator 64x32 */
  --native-tab-pill-h: 32px;
  --native-grabber-w-ios: 36px;      /* brief §3.3 */
  --native-grabber-h-ios: 5px;
  --native-grabber-w-android: 32px;
  --native-grabber-h-android: 4px;
  --native-group-radius-ios: 12px;   /* brief §3.4: 10 to 12 */
  --native-group-inset: 16px;
  --native-row-min-ios: 44px;
  --native-row-1-android: 56px;
  --native-row-2-android: 72px;
  --native-row-3-android: 88px;
  --native-press-dim: 8%;            /* brief §3.5 */
  --native-state-pressed: 10%;
  --native-press-scale: 0.97;
  --native-sheet-scale-back: 0.94;
  --native-sheet-medium: 50dvh;
  --native-parallax: 0.3;            /* brief §3.6 */
  --native-hairline: 0.5px;
  --ease-ios-spring: cubic-bezier(0.32, 0.72, 0, 1);
  --ease-m3-emphasized: cubic-bezier(0.2, 0, 0, 1);
  --dur-sheet: 300ms;                /* brief §6: 250 to 350ms */
}
```

Run: `cd web && npx vitest run tests/unit/nativeFrameCss.test.ts tests/unit/design-tokens.test.ts tests/unit/motionDefaults.test.ts`
Expected: PASS. If `design-tokens.test.ts` rejects a raw value (for example an off-scale px), add the token to that test's documented allow-list with a one-line reason pointing at this block. Do not move the value into a component.

- [ ] **Step 4: Record the preview selectors (`web/scripts/drift/native-preview.mjs`)**

Fill each selector from the committed preview markup (Step 1). The keys are fixed, because later tasks import them.

```js
/*
 * The design A preview's native phone frame (student-home-a.html with
 * ?platform=ios|android&page=root|detail), as committed by the designer.
 * Selectors are read off the committed markup; update them here, nowhere else.
 */
export const NATIVE_PREVIEW = {
  bar: "<the preview's phone bar selector>",
  largeTitle: "<the preview's large title selector>",
  inlineTitle: "<the preview's inline (bar) title selector>",
  back: "<the preview's back chevron selector>",
  bell: "<the preview's bell trigger selector>",
  settings: "<the preview's settings trigger selector>",
  avatar: "<the preview's avatar trigger selector>",
  sheet: "<the preview's open sheet panel selector>",
  tabbar: "<the preview's tab bar selector>",
}

export function previewNativeQuery({ state, theme, platform, page }) {
  return new URLSearchParams({ state, theme, motion: "reduce", width: "desktop", platform, page })
}
```

The angle-bracket strings are not placeholders left for later. Step 4 **is** the step that replaces them, from the committed markup. The task is not done while any `<` remains:

```bash
cd web && node -e 'const s=require("fs").readFileSync("scripts/drift/native-preview.mjs","utf8");if(/"<[^"]*>"/.test(s)){console.error("unfilled selector");process.exit(1)}'
```

Expected: exit 0.

- [ ] **Step 5: Commit**

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/student-home-variants
/home/sico/Code/Lemely/.venv/bin/pre-commit run --files web/src/index.css web/scripts/drift/native-preview.mjs web/tests/unit/nativeFrameCss.test.ts
SKIP=import-linter git commit -S -m "feat(web): native frame tokens from the design A phone preview" -- web/src/index.css web/scripts/drift/native-preview.mjs web/tests/unit/nativeFrameCss.test.ts
```

---

### Task 1: Platform resolver, `ios:` / `android:` / `native:` variants, `useNativeFrame`

**Files:**
- Create: `web/src/lib/platform.ts`, `web/src/lib/useNativeFrame.ts`, `web/tests/unit/platform.test.ts`
- Modify: `web/public/shell-init.js` (set `data-platform` before paint), `web/src/index.css` (three `@custom-variant`s after the `dark` one), `web/tests/unit/nativeFrameCss.test.ts`

**Interfaces:**
- Produces:
  - `type Platform = "ios" | "android" | "other"`
  - `resolvePlatform(input: { uaDataPlatform?: string | null; userAgent: string; maxTouchPoints: number }): Platform`
  - `readPlatform(): Platform` (reads `document.documentElement.dataset.platform`; `"other"` without a DOM)
  - `PHONE_MEDIA = "(max-width: 720px)"`, `isNativeFrame(platform: Platform, phone: boolean): boolean`
  - `useNativeFrame(): { platform: Platform; phone: boolean; native: boolean }`
  - `NativeFrameProvider({ value, children })` (tests and harness overrides only)
  - Tailwind variants: `ios:`, `android:`, `native:`.

- [ ] **Step 1: Write the failing test `web/tests/unit/platform.test.ts`**

```ts
import { readFileSync } from "node:fs"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { runInNewContext } from "node:vm"
import { describe, expect, it } from "vitest"
import { isNativeFrame, PHONE_MEDIA } from "@/lib/useNativeFrame"
import { resolvePlatform, type Platform } from "@/lib/platform"

const ROOT = fileURLToPath(new URL("../../", import.meta.url))

const UA = {
  iphone: "Mozilla/5.0 (iPhone; CPU iPhone OS 26_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.0 Mobile/15E148 Safari/604.1",
  ipadOs: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.0 Safari/605.1.15",
  mac: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
  android: "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Mobile Safari/537.36",
  linux: "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
  crios: "Mozilla/5.0 (iPhone; CPU iPhone OS 26_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/141.0 Mobile/15E148 Safari/604.1",
}

const CASES: [string, Parameters<typeof resolvePlatform>[0], Platform][] = [
  ["iPhone Safari", { userAgent: UA.iphone, maxTouchPoints: 5 }, "ios"],
  ["iPhone Chrome (CriOS)", { userAgent: UA.crios, maxTouchPoints: 5 }, "ios"],
  ["iPadOS desktop UA with touch", { userAgent: UA.ipadOs, maxTouchPoints: 5 }, "ios"],
  ["real Mac (no touch)", { userAgent: UA.mac, maxTouchPoints: 0 }, "other"],
  ["Android Chrome via UA-CH", { uaDataPlatform: "Android", userAgent: UA.android, maxTouchPoints: 5 }, "android"],
  ["Android via UA fallback", { uaDataPlatform: null, userAgent: UA.android, maxTouchPoints: 5 }, "android"],
  // Playwright emulation on a Linux host: UA-CH still says "Linux"; the UA string decides.
  ["iPhone UA on a Linux host", { uaDataPlatform: "Linux", userAgent: UA.iphone, maxTouchPoints: 5 }, "ios"],
  ["desktop Linux", { uaDataPlatform: "Linux", userAgent: UA.linux, maxTouchPoints: 0 }, "other"],
]

describe("resolvePlatform", () => {
  it.each(CASES)("%s", (_name, input, want) => {
    expect(resolvePlatform(input)).toBe(want)
  })
})

/** Run public/shell-init.js in a sandbox and return the data-platform it set. */
function shellInitPlatform(input: Parameters<typeof resolvePlatform>[0]): string | undefined {
  const source = readFileSync(join(ROOT, "public/shell-init.js"), "utf8")
  const html = { dataset: {} as Record<string, string> }
  runInNewContext(source, {
    document: {
      documentElement: html,
      querySelector: () => null,
      getElementById: () => ({ dataset: {} }),
      addEventListener: () => {},
    },
    navigator: {
      userAgent: input.userAgent,
      maxTouchPoints: input.maxTouchPoints,
      userAgentData: input.uaDataPlatform ? { platform: input.uaDataPlatform } : undefined,
    },
    localStorage: { getItem: () => null },
    matchMedia: () => ({ matches: false }),
    window: { matchMedia: () => ({ matches: false }) },
    location: { pathname: "/student" },
  })
  return html.dataset.platform
}

describe("shell-init.js sets html[data-platform] before paint, same table as resolvePlatform", () => {
  it.each(CASES)("%s", (_name, input, want) => {
    expect(shellInitPlatform(input)).toBe(want)
  })
})

describe("native frame = phone width AND ios|android", () => {
  it("the phone media query is the shell-sm edge (721px - 1)", () => {
    expect(PHONE_MEDIA).toBe("(max-width: 720px)")
  })
  it.each([
    ["ios", true, true],
    ["android", true, true],
    ["other", true, false],
    ["ios", false, false],
  ] as const)("%s phone=%s -> %s", (platform, phone, want) => {
    expect(isNativeFrame(platform, phone)).toBe(want)
  })
})
```

Append to `nativeFrameCss.test.ts`:

```ts
describe("platform variants (Task 1)", () => {
  it("declares ios:, android: and native: on html[data-platform]", () => {
    expect(css).toContain('@custom-variant ios (&:where([data-platform="ios"], [data-platform="ios"] *));')
    expect(css).toContain('@custom-variant android (&:where([data-platform="android"], [data-platform="android"] *));')
    expect(css).toMatch(
      /@custom-variant native \{\s*@media \(max-width: 720px\) \{\s*&:where\(\[data-platform="ios"\], \[data-platform="ios"\] \*, \[data-platform="android"\], \[data-platform="android"\] \*\) \{\s*@slot;/,
    )
  })
  it("720 stays one below --breakpoint-shell-sm", () => {
    expect(css).toContain("--breakpoint-shell-sm: 721px;")
  })
})
```

Run: `cd web && npx vitest run tests/unit/platform.test.ts tests/unit/nativeFrameCss.test.ts`
Expected: FAIL (modules missing; shell-init sets no platform; variants missing).

- [ ] **Step 2: Implement `web/src/lib/platform.ts`**

```ts
/*
 * One boot-time platform answer for the native phone frame (brief §3.7).
 * `public/shell-init.js` runs the same table in ES5 before first paint and
 * writes `html[data-platform]`; this module is the typed twin, pinned against
 * it by tests/unit/platform.test.ts. UA-CH only decides "Android" (Safari has
 * no UA-CH, and an emulated UA on a Linux host still reports "Linux"); the UA
 * string decides the rest. iPadOS sends a Mac UA, so Mac + touch is iOS.
 */
export type Platform = "ios" | "android" | "other"

export interface PlatformInput {
  uaDataPlatform?: string | null
  userAgent: string
  maxTouchPoints: number
}

export function resolvePlatform({ uaDataPlatform, userAgent, maxTouchPoints }: PlatformInput): Platform {
  if (uaDataPlatform === "Android") return "android"
  if (/\b(iPhone|iPad|iPod)\b/.test(userAgent)) return "ios"
  if (/\bMacintosh\b/.test(userAgent) && maxTouchPoints > 1) return "ios"
  if (/\bAndroid\b/.test(userAgent)) return "android"
  return "other"
}

export function readPlatform(): Platform {
  if (typeof document === "undefined") return "other"
  const value = document.documentElement.dataset.platform
  return value === "ios" || value === "android" ? value : "other"
}
```

- [ ] **Step 3: Mirror it in `web/public/shell-init.js`**

Inside the IIFE, before the theme block, add its own try/catch, so a failure never blocks the theme or `data-shell`:

```js
  // Platform for the native phone frame (docs/superpowers/plans/
  // 2026-11-08-native-mobile-frame.md). Same table as src/lib/platform.ts's
  // resolvePlatform, duplicated in ES5 because this runs before any bundle;
  // tests/unit/platform.test.ts runs this file and pins the two together.
  try {
    var nav = window.navigator || navigator
    var ua = (nav && nav.userAgent) || ""
    var uaData = nav && nav.userAgentData
    var platform = "other"
    if (uaData && uaData.platform === "Android") platform = "android"
    else if (/\b(iPhone|iPad|iPod)\b/.test(ua)) platform = "ios"
    else if (/\bMacintosh\b/.test(ua) && nav.maxTouchPoints > 1) platform = "ios"
    else if (/\bAndroid\b/.test(ua)) platform = "android"
    document.documentElement.dataset.platform = platform
  } catch (platformError) {
    // Worst case the page keeps design A (no data-platform = "other").
  }
```

Note: the sandbox's `window` has no `navigator`, so the code falls back to the global `navigator`. Keep the `window.navigator || navigator` form.

- [ ] **Step 4: Implement `web/src/lib/useNativeFrame.ts`**

```ts
import { createContext, createElement, useContext, useSyncExternalStore, type ReactNode } from "react"
import { readPlatform, type Platform } from "@/lib/platform"

/** The shell-sm edge (`--breakpoint-shell-sm: 721px`), as a media query. */
export const PHONE_MEDIA = "(max-width: 720px)"

export interface NativeFrame {
  platform: Platform
  phone: boolean
  native: boolean
}

export function isNativeFrame(platform: Platform, phone: boolean): boolean {
  return phone && platform !== "other"
}

const Override = createContext<NativeFrame | null>(null)

/** Tests and harness only: force a frame without a DOM. */
export function NativeFrameProvider({ value, children }: { value: NativeFrame; children: ReactNode }) {
  return createElement(Override.Provider, { value }, children)
}

function subscribe(onChange: () => void): () => void {
  const media = window.matchMedia(PHONE_MEDIA)
  media.addEventListener("change", onChange)
  return () => media.removeEventListener("change", onChange)
}

/**
 * The one JS switch for markup that differs on the native frame (sheets).
 * Styling differences use the `native:`/`ios:`/`android:` variants instead.
 */
export function useNativeFrame(): NativeFrame {
  const forced = useContext(Override)
  const phone = useSyncExternalStore(
    subscribe,
    () => window.matchMedia(PHONE_MEDIA).matches,
    () => false,
  )
  if (forced) return forced
  const platform = readPlatform()
  return { platform, phone, native: isNativeFrame(platform, phone) }
}
```

- [ ] **Step 5: Add the variants to `web/src/index.css`** (directly after `@custom-variant dark …`)

```css
/* Native phone frame (docs/superpowers/plans/2026-11-08-native-mobile-frame.md):
   `html[data-platform]` is set by public/shell-init.js before paint. `native:` is
   the phone range (the shell-sm edge) on iOS or Android only; desktop, tablet and
   `other` keep design A. */
@custom-variant ios (&:where([data-platform="ios"], [data-platform="ios"] *));
@custom-variant android (&:where([data-platform="android"], [data-platform="android"] *));
@custom-variant native {
  @media (max-width: 720px) {
    &:where([data-platform="ios"], [data-platform="ios"] *, [data-platform="android"], [data-platform="android"] *) {
      @slot;
    }
  }
}
```

Run: `cd web && npx vitest run tests/unit/platform.test.ts tests/unit/nativeFrameCss.test.ts tests/unit/themeInit.test.ts tests/unit/utilityExistence.test.ts`
Expected: PASS. Then run `npm run build` and confirm the variant compiles: `grep -c 'data-platform="ios"' dist/assets/*.css` should print at least 1 once a later task uses it. For now the build just has to succeed.

- [ ] **Step 6: Commit**

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/student-home-variants
FILES="web/src/lib/platform.ts web/src/lib/useNativeFrame.ts web/public/shell-init.js web/src/index.css web/tests/unit/platform.test.ts web/tests/unit/nativeFrameCss.test.ts"
/home/sico/Code/Lemely/.venv/bin/pre-commit run --files $FILES
SKIP=import-linter git commit -S -m "feat(web): boot-time platform resolver and ios/android/native variants" -- $FILES
```

---

### Task 2: Drift harness platform emulation and the native scene list

The scenes are defined now, so every later UI task is gated against the preview. Native keys will fail until their task lands; each task names the keys it must turn to pass or pending.

**Files:**
- Modify: `web/scripts/drift/harness.mjs` (`newContext`, `openApp`, `openPreview` take `platform` and `page`)
- Modify: `web/scripts/home-drift.mjs` (pass `scene.platform`)
- Modify: `web/scripts/drift/scenes.mjs` (`HEIGHT[412] = 915`; append `NATIVE_SCENES`)
- Modify: `web/scripts/shell-behaviour.mjs` (run `NATIVE_CHECKS` too; pass `check.platform`; height for 412)
- Create: `web/scripts/drift/scenes-native.mjs`, `web/scripts/drift/checks-native.mjs`

**Interfaces:**
- Consumes: `NATIVE_PREVIEW`, `previewNativeQuery` (Task 0); `studentShellMocks`, `STUDENT_PROFILE`, `teacherShellMocks` (`mocks.mjs`).
- Produces:
  - `PLATFORM_UA` in `harness.mjs`.
  - `openApp(browser, { width, height, theme, app, platform? })` and `openPreview(browser, { width, height, theme, preview, platform? })`, with `preview.page`.
  - `NATIVE_SCENES`, and `NATIVE_CHECKS` (an array that later tasks push onto).
  - Scene ids: `native-<ios|android>-<root-top|root-scrolled|detail|bell|settings>`, `native-teacher-<ios|android>-root-top` (log), `native-android-412-<root-top|root-scrolled>` (log).

- [ ] **Step 1: Platform emulation in `harness.mjs`**

Replace `newContext` with:

```js
/** UA strings the app's resolver maps to each platform (src/lib/platform.ts). */
export const PLATFORM_UA = {
  ios: "Mozilla/5.0 (iPhone; CPU iPhone OS 26_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.0 Mobile/15E148 Safari/604.1",
  android: "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Mobile Safari/537.36",
}

async function newContext(browser, { width, height, theme, platform }) {
  const device = platform ? { userAgent: PLATFORM_UA[platform], isMobile: true, hasTouch: true } : {}
  if (platform && !device.userAgent) throw new Error(`unknown platform ${platform}`)
  return browser.newContext({
    viewport: { width, height },
    deviceScaleFactor: 1,
    reducedMotion: "reduce",
    colorScheme: theme,
    ...device,
  })
}
```

`openApp` takes `platform` and passes it to `newContext`. After `page.goto`, if `platform` is set, assert the resolver agreed:

```js
  if (platform) {
    const got = await page.evaluate(() => document.documentElement.dataset.platform)
    if (got !== platform) throw new Error(`html[data-platform] is ${got}, expected ${platform}`)
  }
```

`openPreview` takes `platform`. When `platform` is set, it builds its query with `previewNativeQuery({ state: preview.state, theme, platform, page: preview.page ?? "root" })` (import from `./native-preview.mjs`). Otherwise it uses today's query unchanged.

In `home-drift.mjs` line ~110, pass `platform: scene.platform` to both `openPreview` and `openApp`. In `scenes.mjs`, add `412: 915` to `HEIGHT` and append `NATIVE_SCENES`.

- [ ] **Step 2: The scenes (`web/scripts/drift/scenes-native.mjs`)**

```js
import { NATIVE_PREVIEW } from "./native-preview.mjs"
import { STUDENT_PROFILE, studentShellMocks, teacherShellMocks } from "./mocks.mjs"

/*
 * Native phone frame vs the design A preview (?platform=…&page=…), at 390x844
 * for both platforms (user instruction), light and dark. Gate scenes: 0 px, or
 * at most 15% with an approved justification. The existing student-/teacher-
 * scenes run without a UA ("other") and must not change.
 */
const NO_GUTTER = "html{scrollbar-gutter:auto!important}"
const DETAIL_PATH = "/student/practice/0606"
/** The app's bar title on DETAIL_PATH (studentPageTitle); confirmed in Step 2. */
const DETAIL_TITLE = "Practice"

const app = (extra = {}) => ({
  path: "/student",
  profile: STUDENT_PROFILE,
  mocks: studentShellMocks("populated"),
  css: NO_GUTTER,
  ...extra,
})

async function scrollPast(page) {
  await page.evaluate(() => window.scrollTo(0, 240))
  await page.waitForFunction(() => document.querySelector("header[data-title-level]")?.getAttribute("data-collapsed") === "true")
}
async function previewScroll(page) {
  await page.evaluate(() => window.scrollTo(0, 240))
}
async function openAppSheet(page, name) {
  await page.getByRole("button", { name }).first().click()
  await page.getByRole("dialog").waitFor()
}

function perPlatform(build) {
  return ["ios", "android"].map((platform) => build(platform))
}

export const NATIVE_SCENES = [
  ...perPlatform((platform) => ({
    id: `native-${platform}-root-top`, kind: "preview-vs-app", capture: "frame", platform, windows: [390],
    app: app(), preview: { state: "populated", page: "root" },
  })),
  ...perPlatform((platform) => ({
    id: `native-${platform}-root-scrolled`, kind: "preview-vs-app", capture: "frame", platform, windows: [390],
    app: app({ act: scrollPast }), preview: { state: "populated", page: "root", act: previewScroll },
  })),
  ...perPlatform((platform) => ({
    id: `native-${platform}-detail`, kind: "preview-vs-app", capture: "frame", platform, windows: [390],
    app: app({ path: DETAIL_PATH }),
    preview: {
      state: "populated",
      page: "detail",
      // The preview's detail title is fixed; make it read what the app's route says.
      act: (page) => page.evaluate(([sel, title]) => {
        for (const el of document.querySelectorAll(sel)) el.textContent = title
      }, [NATIVE_PREVIEW.inlineTitle, DETAIL_TITLE]),
    },
  })),
  ...perPlatform((platform) => ({
    id: `native-${platform}-bell`, kind: "preview-vs-app", capture: "frame", platform, windows: [390],
    app: app({ act: (page) => openAppSheet(page, /^Notifications/) }),
    preview: { state: "populated", page: "root", act: (page) => page.click(NATIVE_PREVIEW.bell) },
  })),
  ...perPlatform((platform) => ({
    id: `native-${platform}-settings`, kind: "preview-vs-app", capture: "frame", platform, windows: [390],
    app: app({ path: "/student/settings" }),
    preview: { state: "populated", page: "root", act: (page) => page.click(NATIVE_PREVIEW.settings) },
  })),
  // Teachers share the frame; no teacher preview exists, so log-only captures.
  ...perPlatform((platform) => ({
    id: `native-teacher-${platform}-root-top`, kind: "before-vs-after", capture: "frame", rule: "log", platform,
    windows: [390], baselineless: [390],
    app: { surface: "teacher-overview", state: "populated", mocks: teacherShellMocks },
  })),
  // Brief §2 proof size for Android; log-only (D9).
  {
    id: "native-android-412-root-top", kind: "preview-vs-app", capture: "frame", rule: "log", platform: "android",
    windows: [412], app: app(), preview: { state: "populated", page: "root" },
  },
  {
    id: "native-android-412-root-scrolled", kind: "preview-vs-app", capture: "frame", rule: "log", platform: "android",
    windows: [412], app: app({ act: scrollPast }), preview: { state: "populated", page: "root", act: previewScroll },
  },
]
```

Before running, check the detail title. Open `/student/practice/0606` in the app at 390 and read the bar's `[data-shell-title]`. If it is not "Practice", set `DETAIL_TITLE` to the app's title. The preview is made to match the app's route title, never the other way round.

- [ ] **Step 3: The behaviour checks file (`web/scripts/drift/checks-native.mjs`)**

```js
import { STUDENT_PROFILE, studentShellMocks, teacherShellMocks } from "./mocks.mjs"

export const NATIVE_HOME = { path: "/student", profile: STUDENT_PROFILE, mocks: studentShellMocks("populated") }
export const NATIVE_TEACHER_HOME = { surface: "teacher-overview", state: "populated", mocks: teacherShellMocks }

/** Each check: { id, platform, width (default 390), theme, app, run(page) }. */
export const NATIVE_CHECKS = [
  ...["ios", "android"].map((platform) => ({
    id: `native-${platform}-platform-resolves`,
    platform,
    width: 390,
    app: NATIVE_HOME,
    async run(page) {
      const got = await page.evaluate(() => document.documentElement.dataset.platform)
      if (got !== platform) throw new Error(`data-platform=${got}`)
    },
  })),
  {
    id: "native-other-keeps-design-a",
    width: 390,
    app: NATIVE_HOME,
    async run(page) {
      const got = await page.evaluate(() => document.documentElement.dataset.platform)
      if (got !== "other") throw new Error(`no UA override should resolve to other, got ${got}`)
    },
  },
]
```

In `shell-behaviour.mjs`, import `NATIVE_CHECKS` and filter over `[...SHELL_CHECKS, ...NATIVE_CHECKS]`. Pass `platform: check.platform` to `openApp`, and use `height: { 390: 844, 412: 915 }[width] ?? 900`.

- [ ] **Step 4: Run it**

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/student-home-variants/web
npm run build
node scripts/shell-behaviour.mjs --check native-
node scripts/home-drift.mjs --list | grep '^native-' | wc -l
node scripts/home-drift.mjs --scene student-,teacher-
```

Expected:
- the three behaviour checks pass;
- the list shows 28 native keys: 10 gate scenes × 2 themes = 20, plus 2 teacher log scenes × 2 themes = 4, plus 2 Android-412 log scenes × 2 themes = 4;
- the `student-,teacher-` run gives exactly the outcomes it gave at `ba79e15c`. Compare the two `report.json` files key by key; the harness change must be a no-op without a platform.

Then run `node scripts/home-drift.mjs --scene native-` once. Native gate keys are expected to fail now, because the frame is not built. Keep the report as the "before" evidence and do not add justifications yet.

- [ ] **Step 5: Commit**

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/student-home-variants
FILES="web/scripts/drift/harness.mjs web/scripts/home-drift.mjs web/scripts/drift/scenes.mjs web/scripts/drift/scenes-native.mjs web/scripts/drift/checks-native.mjs web/scripts/shell-behaviour.mjs"
/home/sico/Code/Lemely/.venv/bin/pre-commit run --files $FILES
SKIP=import-linter git commit -S -m "test(web): drift harness platform emulation and native phone scenes" -- $FILES
```

---

### Task 3: PWA meta and global touch CSS

**Files:**
- Modify: `web/index.html` (status bar style)
- Modify: `web/src/index.css` (`html, body` rule; `(pointer: coarse)` list; a standalone top-inset utility)
- Modify: `web/tests/unit/nativeMechanics.test.ts`, `web/tests/unit/checkNativeInvariants.test.ts`, `web/scripts/check-native-invariants.mjs`
- Modify: every non-shell full-screen root that paints at the top in standalone mode. Find them in Step 4; expect the auth screens, onboarding, the marketing landing and the camera view.

**Interfaces:**
- Produces: CSS class `.lm-standalone-top`: `padding-top: env(safe-area-inset-top)` in `display-mode: standalone` only.

- [ ] **Step 1: Flip the three gates to the new contract (tests first)**

In `nativeMechanics.test.ts`, replace the `apple-mobile-web-app-status-bar-style` block:

```ts
describe("apple-mobile-web-app-status-bar-style", () => {
  it("is black-translucent: the native frame's glass runs under the clock in standalone (native frame D7)", () => {
    expect(html).toContain('<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />')
  })
})

describe("text-size-adjust", () => {
  it("html, body keep author font sizes on rotation", () => {
    const body = css.match(/html,\s*body\s*\{([\s\S]*?)\}/)?.[1] ?? ""
    expect(body).toContain("-webkit-text-size-adjust: 100%")
    expect(body).toMatch(/(?<!-webkit-)text-size-adjust: 100%/)
  })
})

describe("standalone top inset utility", () => {
  it("lm-standalone-top pads the safe area only in standalone", () => {
    expect(css).toMatch(/@media \(display-mode: standalone\)\s*\{\s*\.lm-standalone-top\s*\{\s*padding-top: env\(safe-area-inset-top\);/)
  })
})
```

In `checkNativeInvariants.test.ts` (around line 30 and 416), the fixture HTML becomes `black-translucent`. The "fails when" case swaps: it now fails when the value is `default`. In `check-native-invariants.mjs` line ~514, the check becomes `'index.html: apple-mobile-web-app-status-bar-style="black-translucent"'` with the matching `includes`.

Run: `cd web && npx vitest run tests/unit/nativeMechanics.test.ts tests/unit/checkNativeInvariants.test.ts`
Expected: FAIL (index.html still `default`; no text-size-adjust; no utility).

- [ ] **Step 2: The meta and CSS**

`web/index.html`: `<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />`. `theme-color` already swaps per scheme (`data-theme-light`/`data-theme-dark`, `shell-init.js` plus `applyTheme.ts`), so it needs no change. Say so in the commit body.

`web/src/index.css`, inside the `html, body { … }` rule, after `-webkit-tap-highlight-color`:

```css
  /* iOS and Android may inflate text after rotation; the type scale is set
     by the design system, not by the browser (native frame Task 3). */
  -webkit-text-size-adjust: 100%;
  text-size-adjust: 100%;
```

In the `(pointer: coarse)` selector list, add `a[href]` and `summary` before `button`, so every tap target drops the double-tap delay. Do **not** add `a[href]` to the `min-block-size` rule: inline prose links stay exempt, as that block's comment explains. Split it into its own rule that only sets `touch-action: manipulation`.

After the `.lm-shell-bar-inset` media blocks, add:

```css
/* With black-translucent (index.html), an iOS home-screen app draws under the
   status bar. The shell bar already adds the inset (.lm-shell-bar-inset,
   .lm-native-bar); full-screen roots outside the shell opt in with this. */
@media (display-mode: standalone) {
  .lm-standalone-top {
    padding-top: env(safe-area-inset-top);
  }
}
```

Run: `cd web && npx vitest run tests/unit/nativeMechanics.test.ts tests/unit/checkNativeInvariants.test.ts tests/unit/utilityExistence.test.ts && node scripts/check-native-invariants.mjs`
Expected: PASS, exit 0.

- [ ] **Step 3: Chrome is not selectable and has no callout**

Native chrome must not start a text selection or the iOS long-press callout. Content stays selectable (anti-goal). In `index.css`, extend `.lm-nav-chrome`, which every nav and header already carries (`nativeMechanics.test.ts` "lm-nav-chrome coverage"):

```css
.lm-nav-chrome {
  -webkit-user-select: none;
  user-select: none;
  -webkit-touch-callout: none;
}
```

If `.lm-nav-chrome` already has a rule, append these declarations to it. Do not create a second rule.

- [ ] **Step 4: Pad the full-screen roots outside the shell**

```bash
cd web && grep -rn "min-h-dvh\|h-dvh\|fixed inset-0" src/portals src/components --include='*.tsx' | grep -v "components/shell\|ui/modal\|ui/sheet\|nav-drawer\|SettingsModal"
```

For each match that is a route root painting from the top edge, outside `PortalShell`, add `lm-standalone-top` to that root's `className`. Expect the auth screens, onboarding, landing and the camera view. Skip it where the root already reads `env(safe-area-inset-top)`, for example `SettingsModal`'s `pt-[max(env(safe-area-inset-top),1rem)]`. List every file you changed, and every file you skipped with its reason, in the commit body.

- [ ] **Step 5: Verify and commit**

```bash
cd web && npm run build && node scripts/home-drift.mjs --scene student-,teacher-
```

Expected: identical outcomes to Task 2's run. Drift runs in a browser tab, not standalone, so neither the inset nor the meta can show.

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/student-home-variants
FILES="web/index.html web/src/index.css web/tests/unit/nativeMechanics.test.ts web/tests/unit/checkNativeInvariants.test.ts web/scripts/check-native-invariants.mjs <roots from Step 4>"
/home/sico/Code/Lemely/.venv/bin/pre-commit run --files $FILES
SKIP=import-linter git commit -S -m "feat(web): black-translucent status bar, text-size-adjust and touch chrome rules" -- $FILES
```

---

### Task 4: Sticky collapsing large-title header (ShellTopBar native variant)

**Page title API (decided here, D2/D3):** `ShellTopBarProps.title` stays the single title string. The level is `titleLevel ?? titleLevelFor(trail)`, where `titleLevelFor(trail) = trail.length > 1 ? "detail" : "root"`. New required prop: `backFallback: string`, the portal root that the native back chevron falls back to. On native:
- `root`: the bar row holds only the actions. A large title, `<p aria-hidden data-shell-large-title>`, sits under the bar, outside `<main>`. The inline `[data-shell-title]` fades in once the large title's bottom crosses the bar.
- `detail`: no large title. There is a leading back chevron and the inline title from the start, and the breadcrumb row is hidden.

**Files:**
- Create: `web/src/components/shell/largeTitle.ts`, `web/src/components/shell/useLargeTitleCollapse.ts`, `web/tests/unit/nativeTopBar.test.ts`
- Modify: `web/src/components/shell/ShellTopBar.tsx`, `web/src/index.css` (native bar block), `web/src/portals/student/shell.tsx` (`backFallback`, `native:hidden` on the in-actions `BackControl`), `web/src/portals/teacher/index.tsx` (`backFallback`), `web/scripts/drift/checks-native.mjs`, `web/scripts/drift/justifications.json`

**Interfaces:**
- Consumes: `useNativeFrame` (Task 1), the tokens (Task 0), `BackControl` (`@/components/ui/back-control`, props `fallback`, `className`).
- Produces:
  - `titleLevelFor(trail: readonly unknown[]): "root" | "detail"`
  - `largeTitleCollapsed(scrollY: number, titleHeight: number): boolean`
  - `useLargeTitleCollapse(ref: RefObject<HTMLElement | null>, enabled: boolean): boolean`
  - `ShellTopBarProps` gains `titleLevel?: "root" | "detail"` and `backFallback: string`.
  - DOM contract: `header[data-title-level][data-collapsed]`, `[data-shell-large-title]`, and CSS classes `.lm-native-bar`, `.lm-native-large-title`.

- [ ] **Step 1: Failing tests (`web/tests/unit/nativeTopBar.test.ts`)**

```ts
import { readFileSync } from "node:fs"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"
import { largeTitleCollapsed, titleLevelFor } from "@/components/shell/largeTitle"

const SRC = join(fileURLToPath(new URL("../../", import.meta.url)), "src")
const css = readFileSync(join(SRC, "index.css"), "utf8")
const bar = readFileSync(join(SRC, "components/shell/ShellTopBar.tsx"), "utf8")

describe("title level comes from the trail (D2)", () => {
  it("section pages are roots, drilled-in pages are details", () => {
    expect(titleLevelFor([])).toBe("root")
    expect(titleLevelFor([{ label: "Classes" }])).toBe("root")
    expect(titleLevelFor([{ label: "Practice" }, { label: "0606" }])).toBe("detail")
  })
})

describe("one collapse threshold: the large title's bottom crossing the bar", () => {
  it.each([
    [0, 41, false],
    [40, 41, false],
    [41, 41, true],
    [300, 82, true],
  ])("scrollY %i, title %ipx -> %s", (y, h, want) => {
    expect(largeTitleCollapsed(y, h)).toBe(want)
  })
  it("an unmeasured title (0px) never reports collapsed at the top", () => {
    expect(largeTitleCollapsed(0, 0)).toBe(false)
  })
})

describe("ShellTopBar native markup", () => {
  it("marks the bar and renders an aria-hidden large title outside main", () => {
    expect(bar).toContain("lm-native-bar")
    expect(bar).toContain("data-title-level={level}")
    expect(bar).toContain("data-collapsed={collapsed}")
    expect(bar).toMatch(/<p[^>]*aria-hidden="true"[^>]*data-shell-large-title/)
  })
  it("renders the native back chevron only for details, from backFallback", () => {
    expect(bar).toMatch(/level === "detail" \? \(\s*<BackControl fallback=\{backFallback\}/)
  })
})

describe("native bar CSS", () => {
  const block = css.slice(css.indexOf("/* ── Native frame: top bar"))
  it("is sticky under the status bar, phone width and ios|android only", () => {
    expect(block).toMatch(/@media \(max-width: 720px\)/)
    expect(block).toMatch(/:root:is\(\[data-platform="ios"\], \[data-platform="android"\]\) \.lm-native-bar \{[^}]*position: sticky;[^}]*top: 0;[^}]*padding-top: env\(safe-area-inset-top\);/)
  })
  it("iOS goes glass with a hairline when collapsed; Android lifts to surface-container", () => {
    expect(block).toMatch(/\[data-platform="ios"\] \.lm-native-bar:is\(\[data-collapsed="true"\][^{]*\{[^}]*backdrop-filter: blur\(var\(--blur-nav\)\)/)
    expect(block).toMatch(/\[data-platform="ios"\] \.lm-native-bar:is\(\[data-collapsed="true"\][^{]*\{[^}]*box-shadow: inset 0 calc\(-1 \* var\(--native-hairline\)\) 0 var\(--md-outline-variant\)/)
    expect(block).toMatch(/\[data-platform="android"\] \.lm-native-bar:is\(\[data-collapsed="true"\][^{]*\{[^}]*background-color: var\(--md-surface-container\)/)
  })
  it("scroll-driven fade only where supported and motion is allowed", () => {
    expect(block).toMatch(/@supports \(animation-timeline: scroll\(\)\)\s*\{\s*@media \(prefers-reduced-motion: no-preference\) and \(max-width: 720px\)/)
    expect(block).toContain("animation-timeline: scroll(root block)")
    expect(block).toContain("animation-range: calc(var(--lm-large-title-block) - 16px) var(--lm-large-title-block)")
  })
})
```

Run: `cd web && npx vitest run tests/unit/nativeTopBar.test.ts`
Expected: FAIL.

- [ ] **Step 2: Pure logic (`web/src/components/shell/largeTitle.ts`)**

```ts
/** Native frame Task 4: a section page (trail of 0 or 1 crumbs) is a tab root
 * with a large title; a drilled-in page is a detail with the compact bar. */
export function titleLevelFor(trail: readonly unknown[]): "root" | "detail" {
  return trail.length > 1 ? "detail" : "root"
}

/** The large title sits directly under the sticky bar, so its bottom reaches
 * the bar's bottom exactly when the page has scrolled by its own height. */
export function largeTitleCollapsed(scrollY: number, titleHeight: number): boolean {
  return titleHeight > 0 && scrollY >= titleHeight
}
```

- [ ] **Step 3: The hook (`web/src/components/shell/useLargeTitleCollapse.ts`)**

```ts
import { useEffect, useState, type RefObject } from "react"
import { largeTitleCollapsed } from "./largeTitle"

/**
 * Writes the large title's height to `--lm-large-title-block` (the CSS
 * scroll-driven fade reads it) and returns the collapsed state from a passive
 * scroll listener batched to one rAF. The state drives `data-collapsed`, which
 * is the whole effect on iOS < 26, under reduced motion, and in tests.
 */
export function useLargeTitleCollapse(ref: RefObject<HTMLElement | null>, enabled: boolean): boolean {
  const [collapsed, setCollapsed] = useState(false)
  useEffect(() => {
    const el = ref.current
    if (!enabled || !el) {
      setCollapsed(false)
      return
    }
    let height = el.offsetHeight
    let frame = 0
    const root = document.documentElement
    const write = () => root.style.setProperty("--lm-large-title-block", `${height}px`)
    const sync = () => {
      frame = 0
      setCollapsed(largeTitleCollapsed(window.scrollY, height))
    }
    const onScroll = () => {
      if (!frame) frame = requestAnimationFrame(sync)
    }
    const resize = new ResizeObserver(() => {
      height = el.offsetHeight
      write()
      onScroll()
    })
    write()
    sync()
    resize.observe(el)
    window.addEventListener("scroll", onScroll, { passive: true })
    return () => {
      cancelAnimationFrame(frame)
      resize.disconnect()
      window.removeEventListener("scroll", onScroll)
      root.style.removeProperty("--lm-large-title-block")
    }
  }, [ref, enabled])
  return collapsed
}
```

- [ ] **Step 4: `ShellTopBar.tsx`**

Add `useRef`, `BackControl`, `useNativeFrame`, `titleLevelFor` and `useLargeTitleCollapse` imports. Extend the props:

```ts
  /** Overrides the trail-derived level (native frame D2). */
  titleLevel?: "root" | "detail"
  /** Where the native back chevron goes when there is no history (portal root). */
  backFallback: string
```

In the component body:

```tsx
  const { native } = useNativeFrame()
  const level = titleLevel ?? titleLevelFor(trail)
  const largeRef = useRef<HTMLParagraphElement>(null)
  const collapsed = useLargeTitleCollapse(largeRef, native && level === "root")
```

The header becomes:

```tsx
      <header
        data-stuck={stuck}
        data-title-level={level}
        data-collapsed={collapsed}
        className={cn(BAR, "lm-native-bar")}
      >
        {level === "detail" ? (
          <BackControl fallback={backFallback} className="hidden native:flex" />
        ) : null}
        {/* menu button unchanged */}
        <p data-shell-title className="me-auto min-w-0 truncate text-title-bar text-on-surface lm-native-inline-title">
          {title}
        </p>
        {/* actions, bell, gear, avatar unchanged */}
      </header>
      <p ref={largeRef} aria-hidden="true" data-shell-large-title className="lm-native-large-title hidden">
        {title}
      </p>
      {trail.length > 1 ? (
        <div className="-mt-3 mb-4 px-[72px] max-shell-lg:px-3.5 native:hidden">
          <Breadcrumbs items={[...trail]} />
        </div>
      ) : null}
```

The large title has `hidden` by default and is shown only by the native CSS for `root`. A `hidden` element measures 0, so the hook's `largeTitleCollapsed` returns false for it.

- [ ] **Step 5: Native bar CSS (`web/src/index.css`, after the `.lm-shell-bar-glass` block)**

```css
/* ── Native frame: top bar (native frame Task 4). Phone width on iOS/Android
   only. Unlayered and more specific than .lm-shell-bar-inset, so it replaces
   the flat design A phone bar's margins, height and transparency. */
@media (max-width: 720px) {
  :root[data-platform="ios"] { --native-bar-h: var(--native-bar-h-ios); }
  :root[data-platform="android"] { --native-bar-h: var(--native-bar-h-android); }
  :root:is([data-platform="ios"], [data-platform="android"]) .lm-native-bar {
    position: sticky;
    top: 0;
    margin: 0;
    height: auto;
    min-height: calc(var(--native-bar-h) + env(safe-area-inset-top));
    padding-top: env(safe-area-inset-top);
    padding-inline: var(--native-bar-pad-inline);
    border: 0;
    border-radius: 0;
    box-shadow: none;
  }
  :root:is([data-platform="ios"], [data-platform="android"]) .lm-native-inline-title {
    font-size: var(--native-inline-title-size);
    font-weight: 600;
    transition: opacity var(--dur-fast) var(--ease-out-soft);
  }
  :root:is([data-platform="ios"], [data-platform="android"]) .lm-native-bar[data-title-level="root"]:not([data-collapsed="true"]) .lm-native-inline-title {
    opacity: 0;
  }
  /* iOS: the inline title is centred over the bar. */
  :root[data-platform="ios"] .lm-native-inline-title {
    position: absolute;
    inset-inline: 25%;
    bottom: calc((var(--native-bar-h) - 1lh) / 2);
    text-align: center;
  }
  :root:is([data-platform="ios"], [data-platform="android"]) .lm-native-large-title {
    margin: 0;
    padding-inline: var(--native-bar-pad-inline);
    padding-bottom: 8px;
    font-family: var(--font-display);
    font-weight: 800;
    font-size: var(--native-large-title-size);
    line-height: var(--native-large-title-lh);
    color: var(--md-on-surface);
    /* Long titles ("0625 Physics · Paper 4 · May/June 2024") wrap to 2 lines. */
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  :root:is([data-platform="ios"], [data-platform="android"]) .lm-native-bar[data-title-level="detail"] + .lm-native-large-title {
    display: none;
  }
  /* iOS: transparent at rest, glass with a hairline once content is under it. */
  :root[data-platform="ios"] .lm-native-bar {
    background-color: transparent;
  }
  :root[data-platform="ios"] .lm-native-bar:is([data-collapsed="true"], [data-title-level="detail"][data-stuck="true"]) {
    background-color: color-mix(in oklch, var(--md-surface-container-lowest) 86%, transparent);
    -webkit-backdrop-filter: blur(var(--blur-nav));
    backdrop-filter: blur(var(--blur-nav));
    box-shadow: inset 0 calc(-1 * var(--native-hairline)) 0 var(--md-outline-variant);
  }
  :root[data-theme="dark"][data-platform="ios"] .lm-native-bar:is([data-collapsed="true"], [data-title-level="detail"][data-stuck="true"]) {
    background-color: color-mix(in oklch, var(--md-surface-container-high) 86%, transparent);
  }
  /* Android: M3 lift-on-scroll, no shadow, no hairline. */
  :root[data-platform="android"] .lm-native-bar {
    background-color: var(--md-surface);
  }
  :root[data-platform="android"] .lm-native-bar:is([data-collapsed="true"], [data-title-level="detail"][data-stuck="true"]) {
    background-color: var(--md-surface-container);
  }
}
@supports (animation-timeline: scroll()) {
  @media (prefers-reduced-motion: no-preference) and (max-width: 720px) {
    @keyframes lm-native-title-in {
      from { opacity: 0; transform: translateY(4px); }
      to { opacity: 1; transform: none; }
    }
    :root:is([data-platform="ios"], [data-platform="android"]) .lm-native-bar[data-title-level="root"] .lm-native-inline-title {
      animation: lm-native-title-in linear both;
      animation-timeline: scroll(root block);
      animation-range: calc(var(--lm-large-title-block) - 16px) var(--lm-large-title-block);
    }
  }
}
```

The `--md-surface` and dark mappings above are the starting point. If the preview (Task 0) uses different surfaces for the phone bar, use the preview's surfaces and say so in the commit body. The inline-title `opacity: 0` rule is overridden by the animation's `both` fill where scroll timelines exist. Elsewhere `data-collapsed` toggles it with a short transition, which `motionDefaults` already strips under reduced motion.

- [ ] **Step 6: Portals pass `backFallback`**

- `student/shell.tsx`: add `backFallback: "/student"` to `topBar`, and add `native:hidden` to the existing `BackControl`'s `className` (`"shell-lg:hidden native:hidden"`).
- `teacher/index.tsx`: add `backFallback: "/teacher"`.

Update `studentShell.test.ts` only where it pins the `BackControl` class string.

Run: `cd web && npx vitest run tests/unit/nativeTopBar.test.ts tests/unit/studentShell.test.ts tests/unit/shellTopBarGlass.test.ts tests/unit/nativeMechanics.test.ts tests/unit/elevationScale.test.ts tests/unit/utilityExistence.test.ts tests/unit/rtlSafety.test.ts`
Expected: PASS. If `rtlSafety` rejects the `inset-inline`, `padding-inline` or `text-align: center` rules, those are logical already; fix anything physical it names.

- [ ] **Step 7: Behaviour checks (append to `checks-native.mjs`)**

```js
NATIVE_CHECKS.push(
  ...["ios", "android"].map((platform) => ({
    id: `native-${platform}-large-title-collapses`,
    platform,
    app: NATIVE_HOME,
    async run(page) {
      const header = page.locator("header[data-title-level]")
      if ((await header.getAttribute("data-title-level")) !== "root") throw new Error("/student should be a root")
      const large = page.locator("[data-shell-large-title]")
      if (!(await large.isVisible())) throw new Error("large title hidden at the top of a root")
      const box = await large.boundingBox()
      await page.evaluate((y) => window.scrollTo(0, y - 1), box.height)
      await page.waitForTimeout(80)
      if ((await header.getAttribute("data-collapsed")) !== "false") throw new Error("collapsed 1px before the threshold")
      await page.evaluate((y) => window.scrollTo(0, y), box.height)
      await page.waitForFunction(() => document.querySelector("header[data-title-level]").dataset.collapsed === "true")
      const inline = page.locator("header [data-shell-title]")
      const opacity = await inline.evaluate((el) => getComputedStyle(el).opacity)
      if (opacity !== "1") throw new Error(`inline title opacity ${opacity} after collapse`)
      const sticky = await header.evaluate((el) => getComputedStyle(el).position)
      if (sticky !== "sticky") throw new Error(`bar position ${sticky}`)
    },
  })),
  ...["ios", "android"].map((platform) => ({
    id: `native-${platform}-detail-has-back`,
    platform,
    app: { ...NATIVE_HOME, path: "/student/practice/0606" },
    async run(page) {
      const header = page.locator("header[data-title-level]")
      if ((await header.getAttribute("data-title-level")) !== "detail") throw new Error("practice page should be a detail")
      if (await page.locator("[data-shell-large-title]").isVisible()) throw new Error("detail shows a large title")
      const backs = await page.getByRole("button", { name: /back/i }).or(page.getByRole("link", { name: /back/i })).filter({ visible: true }).count()
      if (backs !== 1) throw new Error(`expected one visible back control, got ${backs}`)
    },
  })),
  {
    id: "native-other-has-no-large-title",
    width: 390,
    app: NATIVE_HOME,
    async run(page) {
      if (await page.locator("[data-shell-large-title]").isVisible()) throw new Error("other platform shows the native large title")
    },
  },
)
```

Show it can go red: delete the `.lm-native-large-title` `display: -webkit-box` line, rebuild, run `--check native-ios-large-title`, and expect FAIL "large title hidden". Restore it and rebuild.

- [ ] **Step 8: Drift**

```bash
cd web && npm run build
node scripts/shell-behaviour.mjs --check native-
node scripts/home-drift.mjs --scene native-ios-root,native-android-root,native-ios-detail,native-android-detail,native-teacher-,native-android-412-
node scripts/home-drift.mjs --scene student-,teacher-
```

Expected: every behaviour check passes. The `student-,teacher-` outcomes are unchanged from Task 2. Native root and detail keys reach 0 px, or at most 15% with a new entry in `justifications.json` (`"approved": "pending"`) that names each difference. The tab bar is not built until Task 5, so the root and detail keys may differ in the tab bar's box only. Enter that difference as `"tab bar: native styling lands in Task 5"`, to be removed in Task 5. **Drift acceptance** holds for the native keys you ran.

- [ ] **Step 9: Commit**

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/student-home-variants
FILES="web/src/components/shell/largeTitle.ts web/src/components/shell/useLargeTitleCollapse.ts web/src/components/shell/ShellTopBar.tsx web/src/index.css web/src/portals/student/shell.tsx web/src/portals/teacher/index.tsx web/tests/unit/nativeTopBar.test.ts web/tests/unit/studentShell.test.ts web/scripts/drift/checks-native.mjs web/scripts/drift/justifications.json"
/home/sico/Code/Lemely/.venv/bin/pre-commit run --files $FILES
SKIP=import-linter git commit -S -m "feat(web): native large-title header that collapses into the pinned bar" -- $FILES
```

---

### Task 5: Tab bar per platform, active-tab re-tap, immersive routes

**Files:**
- Create: `web/src/components/shell/tabTap.ts`, `web/tests/unit/nativeTabBar.test.ts`
- Modify: `web/src/components/ui/nav-shells.tsx` (`activeIcon`, `onActiveTap`, `lm-native-tabbar`), `web/src/components/shell/PortalShell.tsx` (re-tap wiring, immersive), `web/src/index.css` (tab bar block), `web/src/portals/student/shell.tsx` and `web/src/portals/teacher/index.tsx` (`activeIcon` with `weight="fill"`), `web/src/portals/student/index.tsx` and `web/src/portals/teacher/index.tsx` (route `handle.immersive`), `web/scripts/drift/checks-native.mjs`, `web/scripts/drift/justifications.json`

**Interfaces:**
- Consumes: `useNativeFrame` (Task 1).
- Produces:
  - `activeTabTap(input: { pathname: string; tabTo: string; scrollY: number }): "scroll-top" | "pop-root" | "none"`
  - `NavShellItem.activeIcon?: ReactNode`
  - `BottomNavProps.onActiveTap?: (item: NavShellItem, event: MouseEvent) => void`
  - Route handle field `immersive?: true`.

- [ ] **Step 1: Failing tests (`web/tests/unit/nativeTabBar.test.ts`)**

```ts
import { readFileSync } from "node:fs"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"
import { activeTabTap } from "@/components/shell/tabTap"

const SRC = join(fileURLToPath(new URL("../../", import.meta.url)), "src")
const css = readFileSync(join(SRC, "index.css"), "utf8")
const nav = readFileSync(join(SRC, "components/ui/nav-shells.tsx"), "utf8")
const shell = readFileSync(join(SRC, "components/shell/PortalShell.tsx"), "utf8")

describe("tapping the active tab (brief §3.2)", () => {
  it("first scrolls to the top", () => {
    expect(activeTabTap({ pathname: "/student/classes/7", tabTo: "/student/classes", scrollY: 300 })).toBe("scroll-top")
  })
  it("then pops to the tab root", () => {
    expect(activeTabTap({ pathname: "/student/classes/7", tabTo: "/student/classes", scrollY: 0 })).toBe("pop-root")
  })
  it("does nothing at the top of the root itself", () => {
    expect(activeTabTap({ pathname: "/student/classes", tabTo: "/student/classes", scrollY: 0 })).toBe("none")
    expect(activeTabTap({ pathname: "/student/classes/", tabTo: "/student/classes", scrollY: 0 })).toBe("none")
  })
})

describe("BottomNav native markup", () => {
  it("carries the native tab bar class and swaps to the filled icon only on native", () => {
    expect(nav).toContain("lm-native-tabbar")
    expect(nav).toMatch(/<span className="native:hidden">\{item\.icon\}<\/span>/)
    expect(nav).toMatch(/<span className="hidden native:inline-flex">\{item\.activeIcon\}<\/span>/)
  })
  it("PortalShell hides the tab bar on immersive routes on native", () => {
    expect(shell).toMatch(/immersive && "native:hidden"/)
  })
})

describe("tab bar CSS", () => {
  const block = css.slice(css.indexOf("/* ── Native frame: tab bar"))
  it("iOS: 49px + home indicator, glass, small labels", () => {
    expect(block).toMatch(/\[data-platform="ios"\] \.lm-native-tabbar \{[^}]*min-height: calc\(var\(--native-tabbar-h-ios\) \+ env\(safe-area-inset-bottom\)\)/)
    expect(block).toMatch(/\[data-platform="ios"\] \.lm-native-tabbar \{[^}]*backdrop-filter: blur\(var\(--blur-nav\)\)/)
  })
  it("Android: 80dp with a 64x32 secondary-container pill behind the active icon", () => {
    expect(block).toMatch(/\[data-platform="android"\] \.lm-native-tabbar \{[^}]*min-height: calc\(var\(--native-tabbar-h-android\) \+ env\(safe-area-inset-bottom\)\)/)
    expect(block).toMatch(/\[data-platform="android"\] \.lm-native-tabbar \[aria-current="page"\] \.lm-native-tab-icon::before \{[^}]*inline-size: var\(--native-tab-pill-w\);[^}]*block-size: var\(--native-tab-pill-h\);[^}]*background: var\(--md-secondary-container\)/)
  })
})
```

Run: `cd web && npx vitest run tests/unit/nativeTabBar.test.ts`
Expected: FAIL.

- [ ] **Step 2: `tabTap.ts`**

```ts
/** Native frame Task 5: the first tap on the active tab scrolls to the top;
 * once at the top, the next tap pops a drilled-in page back to the tab root. */
export function activeTabTap({ pathname, tabTo, scrollY }: { pathname: string; tabTo: string; scrollY: number }):
  | "scroll-top"
  | "pop-root"
  | "none" {
  if (scrollY > 0) return "scroll-top"
  const here = pathname.replace(/\/+$/, "")
  return here === tabTo.replace(/\/+$/, "") ? "none" : "pop-root"
}
```

- [ ] **Step 3: `nav-shells.tsx`**

Add `activeIcon?: ReactNode` to `NavShellItem` (doc comment: "Native frame: the selected tab's icon (Phosphor `fill`); design A keeps `icon`"). Add `onActiveTap?: (item: NavShellItem, event: React.MouseEvent) => void` to `BottomNavProps`. In `NavShellLink`, accept an optional `onActiveClick` and pass `onClick={(e) => { if (isActiveNow) onActiveClick?.(e) }}` to `NavLink`. Compute `isActiveNow` with `useMatch({ path: item.to, end: item.end ?? false })`. On the `<nav>` className add `lm-native-tabbar`. Inside the icon span:

```tsx
{isActive && item.activeIcon ? (
  <>
    <span className="native:hidden">{item.icon}</span>
    <span className="hidden native:inline-flex">{item.activeIcon}</span>
  </>
) : (
  item.icon
)}
```

Also add `lm-native-tab-icon` to the icon span's classes and `lm-native-tab-label` to the label span. Design A keeps its exact classes; only the new `lm-native-*` names are added, and those do nothing outside the native media block.

- [ ] **Step 4: Tab bar CSS (`index.css`, after the top bar block)**

```css
/* ── Native frame: tab bar (native frame Task 5). */
@media (max-width: 720px) {
  :root[data-platform="ios"] .lm-native-tabbar {
    min-height: calc(var(--native-tabbar-h-ios) + env(safe-area-inset-bottom));
    border-top: var(--native-hairline) solid var(--md-outline-variant);
    background-color: color-mix(in oklch, var(--md-surface-container-lowest) 86%, transparent);
    -webkit-backdrop-filter: blur(var(--blur-nav));
    backdrop-filter: blur(var(--blur-nav));
  }
  :root[data-theme="dark"][data-platform="ios"] .lm-native-tabbar {
    background-color: color-mix(in oklch, var(--md-surface-container-high) 86%, transparent);
  }
  :root[data-platform="ios"] .lm-native-tabbar .lm-native-tab-label {
    font-size: var(--native-tab-label-size);
  }
  :root[data-platform="android"] .lm-native-tabbar {
    min-height: calc(var(--native-tabbar-h-android) + env(safe-area-inset-bottom));
    border-top: 0;
    background-color: var(--md-surface-container);
  }
  :root[data-platform="android"] .lm-native-tabbar .lm-native-tab-icon {
    isolation: isolate;
  }
  :root[data-platform="android"] .lm-native-tabbar [aria-current="page"] .lm-native-tab-icon::before {
    content: "";
    position: absolute;
    z-index: -1;
    inset-inline-start: 50%;
    inset-block-start: 50%;
    inline-size: var(--native-tab-pill-w);
    block-size: var(--native-tab-pill-h);
    translate: -50% -50%;
    border-radius: 9999px;
    background: var(--md-secondary-container);
  }
  :root[data-platform="android"] .lm-native-tabbar [aria-current="page"] {
    color: var(--md-on-secondary-container);
  }
}
```

The raised "Correct" emphasis tab keeps its circle. Check that the `::before` pill is not drawn behind it: `emphasisId` items never carry `aria-current` styling, because `isActive && !emphasis`. If one does, add `:not(:has(.rounded-full))` to the pill rule. `translate: -50% -50%` is an RTL-safe centring idiom; if `rtlSafety` objects, use `inset-inline: 0; margin-inline: auto` instead.

- [ ] **Step 5: PortalShell wiring and immersive routes**

In `PortalShell.tsx`:

```tsx
  const navigate = useNavigate()
  const matches = useMatches()
  const immersive = matches.some((m) => (m.handle as { immersive?: boolean } | undefined)?.immersive)
  const onActiveTap = (item: NavShellItem, event: React.MouseEvent) => {
    if (!item.to) return
    const action = activeTabTap({ pathname: location.pathname, tabTo: item.to, scrollY: window.scrollY })
    if (action === "none") return
    event.preventDefault()
    if (action === "scroll-top") {
      const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches
      window.scrollTo({ top: 0, behavior: reduce ? "auto" : "smooth" })
    } else navigate(item.to, { viewTransition: true })
  }
```

Pass `onActiveTap` to `BottomNav`, and give it `className={cn("sidebar:hidden", immersive && "native:hidden")}`. Add the imports `cn` (`@/lib/utils`), `useMatches` and `useNavigate` (`react-router-dom`) and `activeTabTap` (`./tabTap`). On `<main>`, add `native:pb-[calc(var(--native-tabbar-h-ios)+env(safe-area-inset-bottom))]` with an `android:` twin using `--native-tabbar-h-android`, so content clears the taller native bar. Drop both when `immersive`.

Routes: add `immersive: true` to the `handle` of student `correct` ("Mark a paper"), the student paper-result route ("Paper result") and teacher review-a-mark ("Review a mark"). Do not change their `title` or `skeleton`.

Portals: in `STUDENT_BOTTOM_TABS.map` and `TEACHER_BOTTOM_TABS.map`, add `activeIcon: <tab.icon size={22} weight="fill" aria-hidden="true" />`.

Run: `cd web && npx vitest run tests/unit/nativeTabBar.test.ts tests/unit/navShells.test.ts tests/unit/navigation.test.ts tests/unit/studentShell.test.ts tests/unit/reviewBadge.test.ts tests/unit/hoverTransition.test.ts tests/unit/rtlSafety.test.ts tests/unit/elevationScale.test.ts`
Expected: PASS.

- [ ] **Step 6: Behaviour checks (append to `checks-native.mjs`)**

```js
NATIVE_CHECKS.push(
  {
    id: "native-ios-tab-retap-scrolls-to-top",
    platform: "ios",
    app: { ...NATIVE_HOME, path: "/student/classes" },
    async run(page) {
      await page.evaluate(() => { document.body.style.minHeight = "3000px"; window.scrollTo(0, 600) })
      const tab = page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Classes" })
      await tab.click()
      await page.waitForFunction(() => window.scrollY === 0)
      if (new URL(page.url()).pathname !== "/student/classes") throw new Error("a tap while scrolled navigated")
    },
  },
  {
    id: "native-ios-tab-retap-pops-to-root",
    platform: "ios",
    // A drilled-in page under the active Profile tab (TAB_DRILL_PATH: confirm
    // the route in student/index.tsx, e.g. the parent-access page under /student/profile).
    app: { ...NATIVE_HOME, path: TAB_DRILL_PATH },
    async run(page) {
      const tab = page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Profile" })
      await tab.click()
      await page.waitForURL(/\/student\/profile$/)
    },
  },
  {
    id: "native-android-immersive-hides-tabs",
    platform: "android",
    app: { ...NATIVE_HOME, path: "/student/correct" },
    async run(page) {
      if (await page.getByRole("navigation", { name: "Primary" }).isVisible()) throw new Error("tab bar shows on an immersive route")
    },
  },
)
```

Declare `const TAB_DRILL_PATH = "<path>"` at the top of the push block. Set it to a real route nested under `/student/profile` that the shell treats as the Profile tab being active: read the `profile` children in `web/src/portals/student/index.tsx`. If no such nested route exists, use one nested under `/student/classes` and the "Classes" tab instead. The step is not done while `<path>` remains.

- [ ] **Step 7: Drift and commit**

```bash
cd web && npm run build
node scripts/shell-behaviour.mjs --check native-
node scripts/home-drift.mjs --scene native-
node scripts/home-drift.mjs --scene student-,teacher-
```

Expected: behaviour passes. Existing scenes are unchanged. Native root, detail and scrolled keys reach 0 px or have justified entries (pending). Remove Task 4's temporary "tab bar: native styling lands in Task 5" text from any entry that now passes at 0 px. Bell and settings keys may still fail (Tasks 7 and 8).

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/student-home-variants
FILES="web/src/components/shell/tabTap.ts web/src/components/ui/nav-shells.tsx web/src/components/shell/PortalShell.tsx web/src/index.css web/src/portals/student/shell.tsx web/src/portals/student/index.tsx web/src/portals/teacher/index.tsx web/tests/unit/nativeTabBar.test.ts web/scripts/drift/checks-native.mjs web/scripts/drift/justifications.json"
/home/sico/Code/Lemely/.venv/bin/pre-commit run --files $FILES
SKIP=import-linter git commit -S -m "feat(web): native tab bar per platform, active-tab re-tap and immersive routes" -- $FILES
```

---

### Task 6: Sheet primitive upgrade (grabber, drag-to-dismiss, detents, iOS scale-back, keyboard)

**Files:**
- Create: `web/src/lib/gestures/sheetMath.ts`, `web/src/components/ui/bottom-sheet.tsx`, `web/tests/unit/sheetMath.test.ts`, `web/tests/unit/nativeSheets.test.ts`
- Modify: `web/src/components/ui/sheet.tsx` (`side="bottom" | "adaptive"` uses `BottomSheetSurface` on native), `web/src/index.css` (sheet block, scale-back), `web/scripts/drift/checks-native.mjs`

**Interfaces:**
- Consumes: `useNativeFrame`, `readPlatform`, the tokens, `haptic` (`@/lib/haptics`).
- Produces:
  - `type Detent = "content" | "medium" | "large"`
  - `sheetRelease(input: { dy: number; velocity: number; height: number; detent: Detent; detents: readonly Detent[]; dismissible: boolean }): { kind: "dismiss" } | { kind: "snap"; detent: Detent }`
  - `swipeBackRelease(input: { dx: number; velocity: number; width: number }): "commit" | "cancel"` (used by Task 12)
  - `DISMISS_FRACTION = 0.25`, `FLING_PX_PER_MS = 0.5`, `SWIPE_COMMIT_FRACTION = 0.35`
  - `BottomSheetSurface(props: BottomSheetSurfaceProps)`, where `BottomSheetSurfaceProps = { detents?: readonly Detent[]; initialDetent?: Detent; dismissible?: boolean; onDismiss: () => void; closing?: boolean; className?: string; children: ReactNode; panelRef?: Ref<HTMLDivElement> } & HTMLAttributes<HTMLDivElement>`. The props spread onto the panel, so callers keep `role`, `aria-*`, `tabIndex` and `onAnimationEnd` there.
  - `SheetGrabber()`, `useSheetScaleBack(active: boolean)`, `useKeyboardInset(): number`
  - CSS: `.lm-sheet`, `.lm-sheet-grabber`, `.lm-sheet[data-detent]`, `html[data-sheet-depth]`.

- [ ] **Step 1: Failing tests (`web/tests/unit/sheetMath.test.ts`)**

```ts
import { describe, expect, it } from "vitest"
import { DISMISS_FRACTION, FLING_PX_PER_MS, sheetRelease, swipeBackRelease } from "@/lib/gestures/sheetMath"

const base = { height: 400, detent: "large" as const, detents: ["medium", "large"] as const, dismissible: true }

describe("sheetRelease (D10)", () => {
  it("a short slow drag snaps back to the current detent", () => {
    expect(sheetRelease({ ...base, dy: 40, velocity: 0.1 })).toEqual({ kind: "snap", detent: "large" })
  })
  it("past a quarter of the height dismisses from the lowest detent", () => {
    expect(sheetRelease({ ...base, detent: "medium", dy: 400 * DISMISS_FRACTION + 1, velocity: 0.1 })).toEqual({ kind: "dismiss" })
  })
  it("a downward drag from large steps to medium before it dismisses", () => {
    expect(sheetRelease({ ...base, dy: 160, velocity: 0.1 })).toEqual({ kind: "snap", detent: "medium" })
  })
  it("a fast fling down dismisses even when short", () => {
    expect(sheetRelease({ ...base, detent: "medium", dy: 20, velocity: FLING_PX_PER_MS + 0.1 })).toEqual({ kind: "dismiss" })
  })
  it("dragging up from medium goes to large", () => {
    expect(sheetRelease({ ...base, detent: "medium", dy: -120, velocity: -0.2 })).toEqual({ kind: "snap", detent: "large" })
  })
  it("a non-dismissible sheet never dismisses", () => {
    expect(sheetRelease({ ...base, detent: "medium", dy: 999, velocity: 3, dismissible: false })).toEqual({ kind: "snap", detent: "medium" })
  })
  it("a content-fit sheet has one detent", () => {
    expect(sheetRelease({ ...base, detents: ["content"], detent: "content", dy: 50, velocity: 0 })).toEqual({ kind: "snap", detent: "content" })
  })
})

describe("swipeBackRelease (brief §6: 35% or a fast fling)", () => {
  it.each([
    [136, 0.1, 390, "commit"],
    [100, 0.1, 390, "cancel"],
    [40, 0.8, 390, "commit"],
    [-50, -0.9, 390, "cancel"],
  ] as const)("dx %i v %f w %i -> %s", (dx, velocity, width, want) => {
    expect(swipeBackRelease({ dx, velocity, width })).toBe(want)
  })
})
```

`web/tests/unit/nativeSheets.test.ts`. Later tasks append here.

```ts
import { readFileSync } from "node:fs"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

const SRC = join(fileURLToPath(new URL("../../", import.meta.url)), "src")
const read = (p: string) => readFileSync(join(SRC, p), "utf8")
const css = read("index.css")

describe("BottomSheetSurface (Task 6)", () => {
  const src = read("components/ui/bottom-sheet.tsx")
  it("drags only from the grabber and header region, never from content text", () => {
    expect(src).toContain("data-sheet-drag-region")
    expect(src).not.toMatch(/onPointerDown=\{[^}]*\}[^>]*data-sheet-body/)
  })
  it("Android-only haptic on snap", () => {
    expect(src).toMatch(/readPlatform\(\) === "android"[^\n]*haptic\("tap"\)/)
  })
  it("iOS keyboard: positions by visualViewport", () => {
    expect(src).toContain("window.visualViewport")
    expect(src).toContain("--lm-keyboard-inset")
  })
})

describe("sheet CSS", () => {
  const block = css.slice(css.indexOf("/* ── Native frame: sheets"))
  it("top radius is the card radius; grabber sizes per platform", () => {
    expect(block).toMatch(/\.lm-sheet \{[^}]*border-start-start-radius: var\(--radius-card\);[^}]*border-start-end-radius: var\(--radius-card\);/)
    expect(block).toMatch(/\[data-platform="ios"\] \.lm-sheet-grabber \{[^}]*inline-size: var\(--native-grabber-w-ios\);[^}]*block-size: var\(--native-grabber-h-ios\)/)
    expect(block).toMatch(/\[data-platform="android"\] \.lm-sheet-grabber \{[^}]*inline-size: var\(--native-grabber-w-android\);[^}]*block-size: var\(--native-grabber-h-android\)/)
  })
  it("iOS scales the page back at the large detent; reduced motion keeps it instant", () => {
    expect(block).toMatch(/:root\[data-platform="ios"\]\[data-sheet-depth\] #root \{[^}]*scale: var\(--native-sheet-scale-back\)/)
    expect(css).toMatch(/@media \(prefers-reduced-motion: reduce\)[\s\S]*#root[\s\S]*transition: none/)
  })
  it("the sheet sits above the keyboard", () => {
    expect(block).toContain("bottom: var(--lm-keyboard-inset, 0px)")
  })
})
```

Run: `cd web && npx vitest run tests/unit/sheetMath.test.ts tests/unit/nativeSheets.test.ts`
Expected: FAIL.

- [ ] **Step 2: `sheetMath.ts`**

```ts
/*
 * Native frame sheets and swipe-back: release decisions, pure (D10).
 * Units: px and px/ms; positive dy is downward, positive dx is away from the
 * leading edge (callers multiply by the RTL sign first).
 */
export type Detent = "content" | "medium" | "large"

export const DISMISS_FRACTION = 0.25
export const FLING_PX_PER_MS = 0.5
export const SWIPE_COMMIT_FRACTION = 0.35

const ORDER: Detent[] = ["content", "medium", "large"]

export function sheetRelease({
  dy,
  velocity,
  height,
  detent,
  detents,
  dismissible,
}: {
  dy: number
  velocity: number
  height: number
  detent: Detent
  detents: readonly Detent[]
  dismissible: boolean
}): { kind: "dismiss" } | { kind: "snap"; detent: Detent } {
  const sorted = ORDER.filter((d) => detents.includes(d))
  const i = sorted.indexOf(detent)
  const far = Math.abs(dy) > height * DISMISS_FRACTION
  const fling = Math.abs(velocity) > FLING_PX_PER_MS
  if (dy > 0 && (far || fling)) {
    if (i > 0) return { kind: "snap", detent: sorted[i - 1] }
    return dismissible ? { kind: "dismiss" } : { kind: "snap", detent }
  }
  if (dy < 0 && (far || fling) && i < sorted.length - 1) return { kind: "snap", detent: sorted[i + 1] }
  return { kind: "snap", detent }
}

export function swipeBackRelease({ dx, velocity, width }: { dx: number; velocity: number; width: number }): "commit" | "cancel" {
  if (dx <= 0) return "cancel"
  return dx >= width * SWIPE_COMMIT_FRACTION || velocity > FLING_PX_PER_MS ? "commit" : "cancel"
}
```

Check the "large → medium at 160px" case in the test. 160 is more than 400 × 0.25 = 100, so the sheet steps down one detent. Expected: PASS.

- [ ] **Step 3: `bottom-sheet.tsx`**

```tsx
import { forwardRef, useEffect, useImperativeHandle, useRef, useState, type HTMLAttributes, type ReactNode } from "react"
import { haptic } from "@/lib/haptics"
import { readPlatform } from "@/lib/platform"
import { sheetRelease, type Detent } from "@/lib/gestures/sheetMath"
import { cn } from "@/lib/utils"

/*
 * The native frame's bottom sheet surface (brief §3.3). Presentation and
 * gesture only: the caller keeps the dialog contract (role, aria-modal,
 * label, focus trap, Escape, history) on the props it spreads here. Drag
 * starts only on [data-sheet-drag-region] (grabber + header), so text in the
 * body stays selectable and inner scrolling stays native.
 */
export interface BottomSheetSurfaceProps extends HTMLAttributes<HTMLDivElement> {
  detents?: readonly Detent[]
  initialDetent?: Detent
  dismissible?: boolean
  onDismiss: () => void
  closing?: boolean
  header?: ReactNode
  children: ReactNode
}

export function SheetGrabber() {
  return <span aria-hidden="true" className="lm-sheet-grabber" />
}

/** iOS: while any sheet sits at the large detent, the page behind scales back. */
export function useSheetScaleBack(active: boolean): void {
  useEffect(() => {
    if (!active || readPlatform() !== "ios") return
    const root = document.documentElement
    const depth = Number(root.dataset.sheetDepth ?? 0) + 1
    root.dataset.sheetDepth = String(depth)
    return () => {
      const next = Number(root.dataset.sheetDepth ?? 1) - 1
      if (next > 0) root.dataset.sheetDepth = String(next)
      else delete root.dataset.sheetDepth
    }
  }, [active])
}

/** iOS ignores interactive-widget: lift the sheet by the keyboard's height. */
export function useKeyboardInset(): number {
  const [inset, setInset] = useState(0)
  useEffect(() => {
    const vv = window.visualViewport
    if (!vv) return
    const sync = () => setInset(Math.max(0, Math.round(window.innerHeight - vv.height - vv.offsetTop)))
    sync()
    vv.addEventListener("resize", sync)
    vv.addEventListener("scroll", sync)
    return () => {
      vv.removeEventListener("resize", sync)
      vv.removeEventListener("scroll", sync)
    }
  }, [])
  return inset
}

export const BottomSheetSurface = forwardRef<HTMLDivElement, BottomSheetSurfaceProps>(function BottomSheetSurface(
  { detents = ["content"], initialDetent, dismissible = true, onDismiss, closing = false, header, children, className, style, ...panel },
  ref,
) {
  const panelRef = useRef<HTMLDivElement>(null)
  useImperativeHandle(ref, () => panelRef.current as HTMLDivElement)
  const [detent, setDetent] = useState<Detent>(initialDetent ?? detents[detents.length - 1])
  const keyboard = useKeyboardInset()
  useSheetScaleBack(!closing && detent === "large")
  const drag = useRef<{ id: number; y: number; t: number; lastY: number; lastT: number } | null>(null)

  function onPointerDown(e: React.PointerEvent) {
    if (!(e.target as Element).closest("[data-sheet-drag-region]")) return
    if (!dismissible && detents.length < 2) return
    drag.current = { id: e.pointerId, y: e.clientY, t: e.timeStamp, lastY: e.clientY, lastT: e.timeStamp }
    ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
  }
  function onPointerMove(e: React.PointerEvent) {
    const d = drag.current
    if (!d || d.id !== e.pointerId || !panelRef.current) return
    const dy = e.clientY - d.y
    panelRef.current.style.translate = `0 ${Math.max(dy, -24)}px`
    d.lastY = e.clientY
    d.lastT = e.timeStamp
  }
  function onPointerUp(e: React.PointerEvent) {
    const d = drag.current
    drag.current = null
    const el = panelRef.current
    if (!d || !el) return
    el.style.translate = ""
    const dy = e.clientY - d.y
    const velocity = (e.clientY - d.lastY) / Math.max(1, e.timeStamp - d.lastT) || dy / Math.max(1, e.timeStamp - d.t)
    const decision = sheetRelease({ dy, velocity, height: el.offsetHeight, detent, detents, dismissible })
    if (decision.kind === "dismiss") onDismiss()
    else if (decision.detent !== detent) {
      setDetent(decision.detent)
      if (readPlatform() === "android") haptic("tap")
    }
  }

  return (
    <div
      ref={panelRef}
      data-detent={detent}
      data-closing={closing || undefined}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
      style={{ ...style, ["--lm-keyboard-inset" as string]: `${keyboard}px` }}
      className={cn("lm-sheet", className)}
      {...panel}
    >
      <div data-sheet-drag-region className="flex flex-col items-center gap-2 pt-2 select-none">
        {dismissible || detents.length > 1 ? <SheetGrabber /> : null}
        {header}
      </div>
      <div data-sheet-body className="min-h-0 flex-1 overflow-y-auto overscroll-contain lm-scroll">
        {children}
      </div>
    </div>
  )
})
```

Note: `readPlatform() === "android"` and `haptic("tap")` must sit on the same line, because the test pins that. Task 13 swaps this to `nativeHaptic`.

- [ ] **Step 4: Sheet CSS (`index.css`)**

```css
/* ── Native frame: sheets (native frame Task 6). Only rendered on the native
   frame; desktop dialogs never use .lm-sheet. */
.lm-sheet {
  position: fixed;
  inset-inline: 0;
  bottom: var(--lm-keyboard-inset, 0px);
  z-index: var(--z-modal);
  display: flex;
  flex-direction: column;
  max-block-size: calc(100dvh - env(safe-area-inset-top) - 10px - var(--lm-keyboard-inset, 0px));
  padding-bottom: env(safe-area-inset-bottom);
  background: var(--md-surface-container-lowest);
  border-start-start-radius: var(--radius-card);
  border-start-end-radius: var(--radius-card);
  transition: translate var(--dur-sheet) var(--ease-ios-spring);
}
:root[data-theme="dark"] .lm-sheet { background: var(--md-surface-container-high); }
:root[data-platform="android"] .lm-sheet { transition-timing-function: var(--ease-m3-emphasized); }
.lm-sheet[data-detent="medium"] { block-size: var(--native-sheet-medium); }
.lm-sheet[data-detent="large"] { block-size: calc(100dvh - env(safe-area-inset-top) - 10px - var(--lm-keyboard-inset, 0px)); }
.lm-sheet:not([data-closing]) { animation: lm-sheet-in var(--dur-sheet) var(--ease-ios-spring) both; }
.lm-sheet[data-closing] { animation: lm-sheet-out var(--dur-fast) var(--ease-in-soft) both; }
@keyframes lm-sheet-in { from { translate: 0 100%; } }
@keyframes lm-sheet-out { to { translate: 0 100%; } }
.lm-sheet-grabber {
  display: block;
  border-radius: 9999px;
  background: var(--md-outline-variant);
}
:root[data-platform="ios"] .lm-sheet-grabber { inline-size: var(--native-grabber-w-ios); block-size: var(--native-grabber-h-ios); }
:root[data-platform="android"] .lm-sheet-grabber { inline-size: var(--native-grabber-w-android); block-size: var(--native-grabber-h-android); }
:root[data-platform="ios"] #root {
  transition: scale var(--dur-sheet) var(--ease-ios-spring), border-radius var(--dur-sheet) var(--ease-ios-spring);
  transform-origin: 50% 0;
}
:root[data-platform="ios"][data-sheet-depth] #root {
  scale: var(--native-sheet-scale-back);
  translate: 0 calc(env(safe-area-inset-top) + 10px);
  border-radius: var(--native-group-radius-ios);
  overflow: clip;
}
:root[data-platform="ios"][data-sheet-depth] body { background: var(--md-inverse-surface); }
```

Inside the existing `@media (prefers-reduced-motion: reduce)` block, add:

```css
  .lm-sheet,
  .lm-sheet[data-closing],
  :root[data-platform="ios"] #root {
    animation: none;
    transition: none;
  }
```

`#root` is the React mount (`index.html`). Sheets portal into `document.body`, outside `#root`, so they never scale. If `--z-modal` is not the variable name for `z-modal`, use the one `@theme` defines for that utility. Check with `grep -n "z-modal\|--z-" web/src/index.css`.

- [ ] **Step 5: `ui/sheet.tsx` uses it on native**

In `SheetContent`, for `side === "bottom" || side === "adaptive"`, call `const { native } = useNativeFrame()`. When `native`, render `SheetPrimitive.Content asChild` around `<BottomSheetSurface detents={["content"]} onDismiss={() => closeRef.current?.click()} header={null}>{children}</BottomSheetSurface>`, plus a visually hidden `<SheetPrimitive.Close ref={closeRef} className="sr-only">Close</SheetPrimitive.Close>`. Radix keeps the focus trap, Escape and the label. Desktop and `other` keep today's markup byte for byte.

Add a test to `nativeSheets.test.ts`:

```ts
describe("ui/sheet.tsx (Task 6)", () => {
  const src = read("components/ui/sheet.tsx")
  it("bottom and adaptive sheets use BottomSheetSurface on the native frame", () => {
    expect(src).toContain("useNativeFrame()")
    expect(src).toMatch(/native && \(side === "bottom" \|\| side === "adaptive"\)/)
    expect(src).toContain("<BottomSheetSurface")
  })
})
```

Run: `cd web && npx vitest run tests/unit/sheetMath.test.ts tests/unit/nativeSheets.test.ts tests/unit/teacherTopBarSheets.test.ts tests/unit/elevationScale.test.ts tests/unit/motionDefaults.test.ts tests/unit/rtlSafety.test.ts tests/unit/a11yRules.test.ts`
Expected: PASS.

- [ ] **Step 6: Behaviour check: the teacher Create sheet drags closed and keeps focus rules**

Append to `checks-native.mjs`:

```js
NATIVE_CHECKS.push({
  id: "native-ios-sheet-drag-dismiss-and-escape",
  platform: "ios",
  app: NATIVE_TEACHER_HOME,
  async run(page) {
    const trigger = page.getByRole("button", { name: /^Create/ }).first()
    await trigger.click()
    const dialog = page.getByRole("dialog")
    await dialog.waitFor()
    const grab = dialog.locator(".lm-sheet-grabber")
    const box = await grab.boundingBox()
    await page.mouse.move(box.x + box.width / 2, box.y + 2)
    await page.mouse.down()
    await page.mouse.move(box.x + box.width / 2, box.y + 400, { steps: 8 })
    await page.mouse.up()
    await dialog.waitFor({ state: "detached" })
    if (!(await trigger.evaluate((el) => el === document.activeElement))) throw new Error("focus did not return to the trigger after drag-dismiss")
    await trigger.click()
    await dialog.waitFor()
    await page.keyboard.press("Escape")
    await dialog.waitFor({ state: "detached" })
  },
})
```

If the teacher Create trigger is not on the native bar at 390, use whichever control opens `ActionSheet` there, and name it in a comment.

Show it can go red: make `onPointerUp` ignore the dismiss decision, rebuild, and expect FAIL "detached" timeout. Restore it.

- [ ] **Step 7: Verify and commit**

```bash
cd web && npm run build && node scripts/shell-behaviour.mjs --check native- && node scripts/home-drift.mjs --scene student-,teacher-
```

Expected: behaviour passes and existing scenes are unchanged.

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/student-home-variants
FILES="web/src/lib/gestures/sheetMath.ts web/src/components/ui/bottom-sheet.tsx web/src/components/ui/sheet.tsx web/src/index.css web/tests/unit/sheetMath.test.ts web/tests/unit/nativeSheets.test.ts web/scripts/drift/checks-native.mjs"
/home/sico/Code/Lemely/.venv/bin/pre-commit run --files $FILES
SKIP=import-linter git commit -S -m "feat(web): native bottom sheet surface with grabber, detents, drag-to-dismiss and iOS scale-back" -- $FILES
```

---

### Task 7: `Modal` and `ConfirmModal` become bottom sheets on the native frame

All 14 `Modal` and 16 `ConfirmModal` call sites keep their props. Only the internals branch.

**Files:**
- Modify: `web/src/components/ui/modal.tsx`, `web/src/components/ui/confirm-modal.tsx`, `web/src/index.css` (action-sheet rows), `web/tests/unit/nativeSheets.test.ts`, `web/scripts/drift/checks-native.mjs`

**Interfaces:**
- Consumes: `BottomSheetSurface`, `useNativeFrame` (Tasks 1 and 6).
- Produces:
  - Internal (not for call sites) `ModalProps.presentation?: "auto" | "action-sheet"`. The default `"auto"` means a sheet on native and a centred dialog elsewhere.
  - `ConfirmModal` renders `presentation="action-sheet"` on iOS native and an M3 dialog-style sheet on Android native.

- [ ] **Step 1: Failing tests (append to `nativeSheets.test.ts`)**

```ts
describe("Modal on the native frame (Task 7)", () => {
  const src = read("components/ui/modal.tsx")
  it("keeps one dialog contract and only swaps the surface", () => {
    expect(src).toContain("useNativeFrame()")
    expect(src.match(/role: "dialog"/g)?.length).toBe(1)
    expect(src).not.toContain('role="dialog"')
    expect(src).toContain("<BottomSheetSurface")
    expect(src).toMatch(/detents=\{size === "lg" \? \["medium", "large"\] : \["content"\]\}/)
    expect(src).toMatch(/dismissible=\{dismissible\}/)
  })
  it("call sites are untouched: the public props are unchanged", () => {
    expect(src).toMatch(/export interface ModalProps \{[\s\S]*open: boolean[\s\S]*onClose: \(\) => void[\s\S]*title: ReactNode/)
  })
})

describe("ConfirmModal (Task 7)", () => {
  const src = read("components/ui/confirm-modal.tsx")
  it("iOS native uses an action sheet with Cancel in its own group", () => {
    expect(src).toMatch(/platform === "ios"[\s\S]*presentation="action-sheet"/)
    expect(src).toContain("lm-action-sheet-cancel")
  })
  it("stays non-dismissible (no scrim close, no drag, no grabber)", () => {
    expect(src).toContain("dismissible={false}")
  })
})
```

Run: `cd web && npx vitest run tests/unit/nativeSheets.test.ts`
Expected: FAIL.

- [ ] **Step 2: `modal.tsx`**

Restructure the return so the panel `<div ref={panelRef} role="dialog" …>` is built once as `panelProps`, and the frame differs:

```tsx
  const { native } = useNativeFrame()
  const panelProps = {
    role: "dialog" as const,
    "aria-modal": true as const,
    "aria-labelledby": titleId,
    "aria-describedby": description ? descriptionId : undefined,
    tabIndex: -1,
    onAnimationEnd: phase === "closing"
      ? (event: React.AnimationEvent<HTMLDivElement>) => { if (event.target === event.currentTarget) onAnimationEnd() }
      : undefined,
  }
  const heading = (/* the existing title + description + close button block */)
  const body = (/* existing children wrapper */)
  const foot = footer ? (/* existing footer */) : null

  if (native) {
    return createPortal(
      <div className="fixed inset-0 z-modal" onKeyDown={handleKeyDown}>
        <div className="fixed inset-0 z-scrim bg-scrim motion-safe:animate-[lm-in_var(--dur-base)_var(--ease-out-soft)_both]" aria-hidden="true" onClick={dismissible ? onClose : undefined} />
        <BottomSheetSurface
          ref={panelRef}
          {...panelProps}
          detents={size === "lg" ? ["medium", "large"] : ["content"]}
          initialDetent={size === "lg" ? "medium" : "content"}
          dismissible={dismissible}
          onDismiss={onClose}
          closing={phase === "closing"}
          header={presentation === "action-sheet" ? null : heading}
          className={cn("gap-4 px-4 pb-4", presentation === "action-sheet" && "lm-action-sheet", className)}
        >
          {presentation === "action-sheet" ? children : (<>{body}{foot}</>)}
        </BottomSheetSurface>
      </div>,
      document.body,
    )
  }
  // desktop / other: today's markup, unchanged
```

`handleKeyDown`, the focus effect, `lockScroll` and `useDialogHistory` all stay above and apply to both branches. The native branch's exit animation comes from `.lm-sheet[data-closing]`, whose `animationend` fires `onAnimationEnd` through `panelProps`. Under reduced motion, `useOverlayPhase` already skips the closing phase; check `src/lib/overlayPhase.ts` and do not change it.

The role appears exactly once, as `role: "dialog"` in `panelProps`. The desktop branch spreads `{...panelProps}` on its panel div, so there is no JSX `role="dialog"` left.

- [ ] **Step 3: `confirm-modal.tsx`**

```tsx
  const { native, platform } = useNativeFrame()
  if (native && platform === "ios") {
    return (
      <Modal open={open} onClose={onCancel} title={title} description={description} size="sm" dismissible={false} hideCloseButton presentation="action-sheet">
        <div className="lm-action-sheet-group">
          <div className="flex flex-col gap-1 px-4 py-3 text-center">
            <h2 className="text-label text-on-surface-variant">{title}</h2>
            <p className="text-body-sm text-on-surface-variant">{consequence}</p>
            {error ? <p className="text-body-sm text-error">{error}</p> : null}
          </div>
          <button type="button" className="lm-action-sheet-row text-error" onClick={() => onConfirm()} disabled={pending} aria-busy={pending || undefined}>
            {pending ? (pendingLabel ?? confirmLabel) : confirmLabel}
          </button>
        </div>
        <button type="button" className="lm-action-sheet-row lm-action-sheet-cancel" onClick={onCancel} disabled={pending}>
          {cancelLabel}
        </button>
      </Modal>
    )
  }
```

The Android native case falls through to today's `Modal` call, which renders as a content-fit sheet with the footer buttons (the M3 dialog-style sheet). There is no `haptic("tap")` on iOS, which has no Vibration API. The safe path keeps the weight: Cancel is semibold in its own group (`lm-action-sheet-cancel`). The `title` id: the action sheet still needs `aria-labelledby`. Pass `title` through `Modal`, which renders a visually hidden `<h2 id={titleId}>` when `presentation === "action-sheet"`. Add that `sr-only` heading inside `modal.tsx`'s native branch.

CSS (`index.css`, sheet block):

```css
.lm-action-sheet { background: transparent; gap: 8px; padding-inline: 8px; }
.lm-action-sheet-group,
.lm-action-sheet-cancel {
  border-radius: var(--native-group-radius-ios);
  background: var(--md-surface-container-lowest);
}
:root[data-theme="dark"] :is(.lm-action-sheet-group, .lm-action-sheet-cancel) { background: var(--md-surface-container-high); }
.lm-action-sheet-row {
  display: block;
  inline-size: 100%;
  min-block-size: 56px;
  border-top: var(--native-hairline) solid var(--md-outline-variant);
  font-size: var(--native-inline-title-size);
  text-align: center;
}
.lm-action-sheet-cancel { border-top: 0; font-weight: 600; }
```

Run: `cd web && npx vitest run tests/unit/nativeSheets.test.ts tests/unit/overlayExit.test.ts tests/unit/a11yRules.test.ts tests/unit/hoverTransition.test.ts tests/unit/contrastRules.test.ts tests/unit/utilityExistence.test.ts`
Expected: PASS.

- [ ] **Step 4: Behaviour checks**

Pick one real `ConfirmModal` call site reachable with the existing mocks, for example the student flashcard deck delete in `FlashcardDecks.tsx`, and one `Modal` call site. Note both in the check comments.

```js
NATIVE_CHECKS.push(
  {
    id: "native-ios-confirm-is-action-sheet",
    platform: "ios",
    app: { ...NATIVE_HOME, path: "<route of the chosen ConfirmModal call site>" },
    async run(page) {
      await /* open the confirm: click the call site's destructive trigger */ page.getByRole("button", { name: /<its trigger label>/ }).click()
      const dialog = page.getByRole("dialog")
      await dialog.waitFor()
      if (!(await dialog.evaluate((el) => el.classList.contains("lm-action-sheet")))) throw new Error("not an action sheet")
      await page.keyboard.press("Escape")
      if (!(await dialog.isVisible())) throw new Error("Escape answered a destructive question")
      await dialog.getByRole("button", { name: "Keep it" }).click()
      await dialog.waitFor({ state: "detached" })
    },
  },
  {
    id: "native-android-modal-back-closes",
    platform: "android",
    app: { ...NATIVE_HOME, path: "<route of the chosen Modal call site>" },
    async run(page) {
      await page.getByRole("button", { name: /<its trigger label>/ }).click()
      const dialog = page.getByRole("dialog")
      await dialog.waitFor()
      if (!(await dialog.evaluate((el) => el.classList.contains("lm-sheet")))) throw new Error("Modal is not a sheet on native")
      await page.goBack()
      await dialog.waitFor({ state: "detached" })
    },
  },
)
```

The three `<…>` strings are filled in **by this step** from the call sites you chose. The task is not done while any remain. Run `grep -n '"<' web/scripts/drift/checks-native.mjs` and expect nothing.

Show it can go red: force `native` to false in `modal.tsx`, rebuild, and expect `native-android-modal-back-closes` FAIL "not a sheet". Restore it.

- [ ] **Step 5: Verify and commit**

```bash
cd web && npm run build && node scripts/shell-behaviour.mjs && node scripts/home-drift.mjs --scene student-,teacher-
```

Expected: all behaviour checks pass, the existing shell checks included (desktop focus trap, Escape). Existing scenes are unchanged.

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/student-home-variants
FILES="web/src/components/ui/modal.tsx web/src/components/ui/confirm-modal.tsx web/src/index.css web/tests/unit/nativeSheets.test.ts web/scripts/drift/checks-native.mjs"
/home/sico/Code/Lemely/.venv/bin/pre-commit run --files $FILES
SKIP=import-linter git commit -S -m "feat(web): Modal and ConfirmModal open as native sheets on phones; iOS confirms use an action sheet" -- $FILES
```

---

### Task 8: Bell, avatar and settings panels become sheets on the native frame

**Files:**
- Create: `web/src/components/shell/PanelSheet.tsx`
- Modify: `web/src/components/shell/NotificationsPanel.tsx`, `web/src/components/shell/AccountPanel.tsx`, `web/src/portals/settings/SettingsModal.tsx`, `web/tests/unit/nativeSheets.test.ts`, `web/tests/unit/shellPanels.test.ts` (only where it pins the menu-only markup), `web/scripts/drift/checks-native.mjs`, `web/scripts/drift/justifications.json`

**Interfaces:**
- Consumes: `BottomSheetSurface`, `useNativeFrame`, `useDialogHistory`, `lockScroll`.
- Produces: `PanelSheet(props: { triggerLabel: string; triggerClassName?: string; trigger: ReactNode; title: string; children: (close: () => void) => ReactNode })`. It is a button plus a portal dialog with the full `Modal`-equivalent contract. `NotificationsPanel` and `AccountPanel` render it when `native`, and Radix `DropdownMenu` otherwise. Their panel body is factored into `NotificationsBody({ onNavigate, Row })` and `AccountBody({ onNavigate, Row })`. `Row` is `DropdownMenu.Item asChild` in the menu, and a plain `Fragment` wrapper in the sheet.

- [ ] **Step 1: Failing tests (append to `nativeSheets.test.ts`)**

```ts
describe("shell panels on the native frame (Task 8)", () => {
  for (const file of ["components/shell/NotificationsPanel.tsx", "components/shell/AccountPanel.tsx"]) {
    const src = read(file)
    it(`${file}: one body, two frames`, () => {
      expect(src).toContain("useNativeFrame()")
      expect(src).toMatch(/native \? \(\s*<PanelSheet/)
      expect(src).toContain("<DropdownMenu.Root modal={false}>")
    })
  }
  it("PanelSheet keeps the dialog contract", () => {
    const src = read("components/shell/PanelSheet.tsx")
    expect(src).toContain('role="dialog"')
    expect(src).toContain('aria-modal="true"')
    expect(src).toContain("useDialogHistory(")
    expect(src).toContain("lockScroll()")
    expect(src).toMatch(/previouslyFocused\.current\?\.focus\(\)/)
  })
  it("SettingsModal is a large-detent sheet on native and keeps routing close", () => {
    const src = read("portals/settings/SettingsModal.tsx")
    expect(src).toContain("useNativeFrame()")
    expect(src).toMatch(/initialDetent="large"/)
    expect(src).toMatch(/onDismiss=\{onClose\}/)
  })
})
```

Run: `cd web && npx vitest run tests/unit/nativeSheets.test.ts`
Expected: FAIL.

- [ ] **Step 2: `PanelSheet.tsx`**

Write it as a small dialog. Its focus, Escape, Tab-trap, history and scroll-lock code is the same contract as `modal.tsx`, but it must not import `Modal`. A `Modal` needs `open` state owned by the caller, and the shell panels own their trigger. The trigger is a `<button aria-haspopup="dialog" aria-expanded={open}>`. The body is `<BottomSheetSurface role="dialog" aria-modal="true" aria-labelledby={titleId} detents={["medium", "large"]} initialDetent="medium" onDismiss={close} header={<h2 id={titleId} className="text-title-bar text-on-surface">{title}</h2>}>{children(close)}</BottomSheetSurface>`, portalled to `document.body` with the scrim. Copy the `FOCUSABLE_SELECTOR`, the rAF first-focus and the Tab-cycle code from `modal.tsx` verbatim, and keep the comment that says so. Use `useDialogHistory({ open, dismissible: true, onClose: close })`.

- [ ] **Step 3: Split the two panel bodies and branch**

In `NotificationsPanel.tsx`, move everything inside `DropdownMenu.Content` into `function NotificationsBody({ panel, Row, onNavigate })`. Each `<DropdownMenu.Item asChild>` becomes `<Row>` (`type Row = (p: { children: ReactElement }) => ReactElement`). In the export:

```tsx
  const { native } = useNativeFrame()
  return native ? (
    <PanelSheet triggerLabel={notificationsTriggerLabel(unread)} triggerClassName={triggerClassName} trigger={/* bell icon + badge, same JSX as today */} title="Notifications">
      {(close) => <NotificationsBody panel={panel} Row={({ children }) => children} onNavigate={close} />}
    </PanelSheet>
  ) : (
    <DropdownMenu.Root modal={false}>{/* today's trigger + Content with <NotificationsBody Row={MenuRow} … /> */}</DropdownMenu.Root>
  )
```

`MenuRow = ({ children }) => <DropdownMenu.Item asChild>{children}</DropdownMenu.Item>`. Apply the same shape to `AccountPanel.tsx`, with sheet title "Account". The rows inside the sheet use the native list styling from Task 10. Until then they keep their panel classes, and Task 10 restyles them.

- [ ] **Step 4: `SettingsModal.tsx` on native**

When `native`, wrap the existing panel markup in `BottomSheetSurface` with `detents={["large"]} initialDetent="large" onDismiss={onClose}`. The scale-back follows from `detent === "large"` on iOS. Keep the existing routing-based close (`onClose` is already `overlayCloseAction`), and keep the existing focus and Escape code. The mobile top tabs stay as they are. Drop the `pt-[max(env(safe-area-inset-top),1rem)]` top padding on native: the sheet already starts below the safe area.

- [ ] **Step 5: Behaviour checks and drift**

Append to `checks-native.mjs`:

```js
NATIVE_CHECKS.push(
  ...["ios", "android"].map((platform) => ({
    id: `native-${platform}-bell-sheet`,
    platform,
    app: NATIVE_HOME,
    async run(page) {
      const bell = page.getByRole("button", { name: /^Notifications/ })
      await bell.click()
      const dialog = page.getByRole("dialog", { name: "Notifications" })
      await dialog.waitFor()
      if ((await page.getByRole("menu").count()) !== 0) throw new Error("native bell still opens a menu")
      await page.keyboard.press("Escape")
      await dialog.waitFor({ state: "detached" })
      if (!(await bell.evaluate((el) => el === document.activeElement))) throw new Error("focus not returned to the bell")
    },
  })),
  {
    id: "native-ios-settings-sheet-back-closes",
    platform: "ios",
    app: NATIVE_HOME,
    async run(page) {
      await page.getByRole("link", { name: "Settings" }).click()
      const dialog = page.getByRole("dialog")
      await dialog.waitFor()
      const scaled = await page.evaluate(() => document.documentElement.hasAttribute("data-sheet-depth"))
      if (!scaled) throw new Error("iOS large detent did not scale the page back")
      await page.goBack()
      await dialog.waitFor({ state: "detached" })
      if (new URL(page.url()).pathname !== "/student") throw new Error("back did not return to the page")
    },
  },
)
```

```bash
cd web && npm run build
node scripts/shell-behaviour.mjs
node scripts/home-drift.mjs --scene native-ios-bell,native-android-bell,native-ios-settings,native-android-settings
node scripts/home-drift.mjs --scene student-,teacher-
```

Expected: all behaviour checks pass, including the existing desktop panel checks (`menu` role, ArrowDown). The native bell and settings keys reach 0 px or carry justified pending entries. Existing scenes are unchanged.

- [ ] **Step 6: Commit**

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/student-home-variants
FILES="web/src/components/shell/PanelSheet.tsx web/src/components/shell/NotificationsPanel.tsx web/src/components/shell/AccountPanel.tsx web/src/portals/settings/SettingsModal.tsx web/tests/unit/nativeSheets.test.ts web/tests/unit/shellPanels.test.ts web/scripts/drift/checks-native.mjs web/scripts/drift/justifications.json"
/home/sico/Code/Lemely/.venv/bin/pre-commit run --files $FILES
SKIP=import-linter git commit -S -m "feat(web): bell, account and settings open as sheets on native phones" -- $FILES
```

---

### Task 9: Popover becomes a sheet; Select stays native (D4)

**Files:**
- Modify: `web/src/components/ui/popover.tsx`, `web/src/components/ui/select.tsx` (doc comment only), `web/tests/unit/nativeSheets.test.ts`, `web/scripts/drift/checks-native.mjs`

**Interfaces:**
- Consumes: `BottomSheetSurface`, `useNativeFrame`, `useDialogHistory`, `lockScroll`.
- Produces: the same `PopoverProps` as today. On native, `contentClassName` is ignored and the content renders in a content-fit sheet with `aria-labelledby` pointing at the trigger.

- [ ] **Step 1: Failing tests (append)**

```ts
describe("Popover and Select (Task 9, D4)", () => {
  it("Popover renders a sheet on native and keeps its render-prop API", () => {
    const src = read("components/ui/popover.tsx")
    expect(src).toContain("useNativeFrame()")
    expect(src).toContain("<BottomSheetSurface")
    expect(src).toMatch(/renderTrigger: \(props: PopoverRenderProps\) => ReactNode/)
  })
  it("Select stays a native <select>: the OS picker is already the platform sheet", () => {
    const src = read("components/ui/select.tsx")
    expect(src).toMatch(/<select\b/)
    expect(src).not.toContain("BottomSheetSurface")
    expect(src).toContain("native frame D4")
  })
})
```

- [ ] **Step 2: Implement**

In `popover.tsx`, when `native && open`, render `createPortal(<><scrim onClick={close}/><BottomSheetSurface role="dialog" aria-modal="true" aria-labelledby={triggerId} id={contentId} detents={["content"]} onDismiss={() => setOpen(false)}>{children}</BottomSheetSurface></>, document.body)`. Add `useDialogHistory({ open: native && open, dismissible: true, onClose: () => setOpen(false) })` and `lockScroll` while it is open on native. The outside-click and Escape logic stays for desktop. `triggerProps` gains an `id` (`triggerId`). `triggerProps["aria-haspopup"]` stays `"dialog"`.

In `select.tsx`, add to the doc comment: `Native frame D4 (docs/superpowers/plans/2026-11-08-native-mobile-frame.md): on iOS and Android phones the native picker already is the platform's sheet or wheel, so this stays native there too.`

- [ ] **Step 3: Behaviour check**

Append a check on student Notifications (`/student/notifications`), one of the two `Popover` call sites. Open its popover trigger on iOS, expect `getByRole("dialog")` with class `lm-sheet`, press Escape, and expect it detached. Show it can go red the same way as Task 7 (force `native` false).

- [ ] **Step 4: Verify and commit**

```bash
cd web && npx vitest run tests/unit/nativeSheets.test.ts tests/unit/a11yRules.test.ts && npm run build && node scripts/shell-behaviour.mjs --check native- && node scripts/home-drift.mjs --scene student-,teacher-
```

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/student-home-variants
FILES="web/src/components/ui/popover.tsx web/src/components/ui/select.tsx web/tests/unit/nativeSheets.test.ts web/scripts/drift/checks-native.mjs"
/home/sico/Code/Lemely/.venv/bin/pre-commit run --files $FILES
SKIP=import-linter git commit -S -m "feat(web): Popover opens as a native sheet on phones; Select stays native" -- $FILES
```

---

### Task 10: Grouped-list primitives and edge-to-edge cards

**Files:**
- Create: `web/src/components/ui/list-group.tsx`, `web/tests/unit/listGroup.test.ts`
- Modify: `web/src/components/ui/card.tsx` (native classes), `web/src/components/shell/PortalShell.tsx` (native page ground and main padding), `web/src/components/shell/NotificationsPanel.tsx` and `AccountPanel.tsx` (sheet rows use `ListRow`), `web/src/portals/settings/SettingsRows.tsx` (sections become `ListGroup` on native), `web/src/components/ui/route-skeleton.tsx` (list skeleton in the group shape on native), `web/scripts/drift/justifications.json`

**Interfaces:**
- Produces:
  - `ListGroup(props: { label?: string; footer?: ReactNode; children: ReactNode; className?: string })`: a `<section>` with an optional label header (the `label` style) and a rows container.
  - `ListRow(props: { title: ReactNode; subtitle?: ReactNode; leading?: ReactNode; trailing?: ReactNode; to?: string; onClick?: () => void; lines?: 1 | 2 | 3 })`: a `Link` when `to`, a `button` when `onClick`, otherwise a `div`.
  - Card native classes. Main native padding `px-4`, and ground `surface-container-low`.

- [ ] **Step 1: Failing tests (`web/tests/unit/listGroup.test.ts`)**

```ts
import { readFileSync } from "node:fs"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it } from "vitest"
import { ListGroup, ListRow } from "@/components/ui/list-group"

const SRC = join(fileURLToPath(new URL("../../", import.meta.url)), "src")
const html = (node: Parameters<typeof renderToStaticMarkup>[0]) =>
  renderToStaticMarkup(createElement(MemoryRouter, null, node))

describe("ListGroup / ListRow (brief §3.4)", () => {
  it("a labelled section with rows", () => {
    const out = html(createElement(ListGroup, { label: "Subjects" }, createElement(ListRow, { title: "Physics", to: "/student/subject/0625" })))
    expect(out).toMatch(/<section[^>]*aria-labelledby="[^"]+"/)
    expect(out).toContain(">Subjects<")
    expect(out).toMatch(/<a[^>]*href="\/student\/subject\/0625"/)
  })
  it("iOS: inset-grouped radius, 44px rows, separators inset from the leading edge", () => {
    const out = html(createElement(ListGroup, null, createElement(ListRow, { title: "A" })))
    expect(out).toContain("ios:rounded-[var(--native-group-radius-ios)]")
    expect(out).toContain("ios:min-h-[var(--native-row-min-ios)]")
    expect(out).toContain("lm-list-row")
  })
  it("Android: full width, 56/72/88 by line count, no separators", () => {
    for (const [lines, token] of [[1, "--native-row-1-android"], [2, "--native-row-2-android"], [3, "--native-row-3-android"]] as const) {
      expect(html(createElement(ListRow, { title: "A", lines }))).toContain(`android:min-h-[var(${token})]`)
    }
    expect(html(createElement(ListGroup, null, createElement(ListRow, { title: "A" })))).toContain("android:rounded-none")
  })
})

describe("Card on the native frame", () => {
  const card = readFileSync(join(SRC, "components/ui/card.tsx"), "utf8")
  it("drops the outline; iOS insets, Android bleeds full width", () => {
    expect(card).toContain("native:border-0")
    expect(card).toContain("native:ios:rounded-[var(--native-group-radius-ios)]")
    expect(card).toContain("native:android:-mx-4 native:android:rounded-none")
  })
})
```

Run: `cd web && npx vitest run tests/unit/listGroup.test.ts`
Expected: FAIL.

- [ ] **Step 2: `list-group.tsx`**

```tsx
import { useId, type ReactNode } from "react"
import { Link } from "react-router-dom"
import { cn } from "@/lib/utils"

/*
 * Native frame grouped lists (brief §3.4). One component, two platform looks:
 * iOS inset-grouped (radius, 16px margins from the page padding, 44px rows,
 * separators inset from the leading edge); Android full-width M3 list items
 * (56/72/88 by line count, 16px padding, no separators). Design A, desktop
 * and `other` get the card look: surface-container-lowest, outline, radius-lg.
 */
const ROW_H = { 1: "android:min-h-[var(--native-row-1-android)]", 2: "android:min-h-[var(--native-row-2-android)]", 3: "android:min-h-[var(--native-row-3-android)]" } as const

export function ListGroup({ label, footer, children, className }: { label?: string; footer?: ReactNode; children: ReactNode; className?: string }) {
  const id = useId()
  return (
    <section aria-labelledby={label ? id : undefined} className={cn("flex flex-col gap-2", className)}>
      {label ? (
        <h2 id={id} className="px-1 text-label text-on-surface-variant native:px-4">
          {label}
        </h2>
      ) : null}
      <div
        className={cn(
          "overflow-hidden rounded-lg border border-outline-variant bg-surface-container-lowest dark:bg-surface-container-high",
          "native:border-0 ios:rounded-[var(--native-group-radius-ios)] android:-mx-4 android:rounded-none",
        )}
      >
        {children}
      </div>
      {footer ? <div className="px-1 text-body-sm text-on-surface-variant native:px-4">{footer}</div> : null}
    </section>
  )
}

export function ListRow({
  title, subtitle, leading, trailing, to, onClick, lines = subtitle ? 2 : 1,
}: {
  title: ReactNode; subtitle?: ReactNode; leading?: ReactNode; trailing?: ReactNode
  to?: string; onClick?: () => void; lines?: 1 | 2 | 3
}) {
  const cls = cn(
    "lm-list-row lm-press flex w-full items-center gap-3 px-4 py-2.5 text-start",
    "ios:min-h-[var(--native-row-min-ios)]",
    ROW_H[lines],
  )
  const inner = (
    <>
      {leading ? <span className="flex-none">{leading}</span> : null}
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="truncate text-body-md text-on-surface">{title}</span>
        {subtitle ? <span className={cn("text-body-sm text-on-surface-variant", lines === 3 ? "line-clamp-2" : "truncate")}>{subtitle}</span> : null}
      </span>
      {trailing ? <span className="flex-none text-on-surface-variant">{trailing}</span> : null}
    </>
  )
  if (to) return <Link to={to} viewTransition className={cls}>{inner}</Link>
  if (onClick) return <button type="button" onClick={onClick} className={cls}>{inner}</button>
  return <div className={cls}>{inner}</div>
}
```

`lm-press` gets its native rules in Task 11. `utilityExistence.test.ts` needs every `lm-` class defined, so this task adds the marker rule `.lm-press { --lm-press: 1; }` below. It has no visual effect; Task 11 keeps it and adds the native rules after it.

CSS for the iOS separator (`index.css`, new block):

```css
/* ── Native frame: grouped lists (native frame Task 10). */
/* Opt-in marker for press feedback; Task 11 adds the native rules. */
.lm-press { --lm-press: 1; }
.lm-list-row + .lm-list-row { border-top: 1px solid var(--md-outline-variant); }
@media (max-width: 720px) {
  :root[data-platform="android"] .lm-list-row + .lm-list-row { border-top: 0; }
  :root[data-platform="ios"] .lm-list-row + .lm-list-row {
    border-top: 0;
    box-shadow: inset calc(var(--native-group-inset)) var(--native-hairline) 0 -0.25px var(--md-outline-variant);
  }
}
```

The iOS separator is drawn inset from the inline-start edge by 16px. If `rtlSafety` rejects the inset `box-shadow`'s physical x offset, replace it with a `::before` line using `inset-inline-start: var(--native-group-inset); inset-inline-end: 0`.

- [ ] **Step 3: Card and PortalShell**

`card.tsx` class string:

```ts
"bg-surface-container-lowest border border-outline-variant rounded-lg native:border-0 native:ios:rounded-[var(--native-group-radius-ios)] native:android:-mx-4 native:android:rounded-none"
```

Data-heavy blocks (charts, mark tables, the grade ladder) already sit in one `Card`, so they become one full-width group. No per-screen change is needed for that.

In `PortalShell.tsx`: the root `div` gets `native:bg-surface-container-low`, and `<main>` gets `native:px-4`.

- [ ] **Step 4: Roll out to shell-owned and shared surfaces**

- `NotificationsBody` and `AccountBody` (Task 8): when rendered in the sheet, rows become `ListRow` inside one `ListGroup`. The menu rows are untouched.
- `SettingsRows.tsx`: each settings section's container gets the `ListGroup` look on native. Add the native classes from `ListGroup`'s container to its section wrapper; do not change its desktop classes. Read the file first, and change only the section wrapper and row classes.
- `route-skeleton.tsx`: the `list` skeleton renders its rows inside a `ListGroup`-shaped container on native (`native:` classes only), so loading looks like the group.

Run: `cd web && npx vitest run tests/unit/listGroup.test.ts tests/unit/routeSkeleton.test.ts tests/unit/settingsTabs.test.ts tests/unit/shellPanels.test.ts tests/unit/utilityExistence.test.ts tests/unit/rtlSafety.test.ts tests/unit/darkConsumers.test.ts tests/unit/contrastRules.test.ts`
Expected: PASS.

- [ ] **Step 5: Drift and commit**

```bash
cd web && npm run build && node scripts/home-drift.mjs --scene native- && node scripts/home-drift.mjs --scene student-,teacher-
```

Expected: existing scenes are unchanged (no `native:` class applies without a platform). Native bell and settings keys move toward 0 px. Update their entries with any remaining differences (pending).

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/student-home-variants
FILES="web/src/components/ui/list-group.tsx web/src/components/ui/card.tsx web/src/components/shell/PortalShell.tsx web/src/components/shell/NotificationsPanel.tsx web/src/components/shell/AccountPanel.tsx web/src/portals/settings/SettingsRows.tsx web/src/components/ui/route-skeleton.tsx web/src/index.css web/tests/unit/listGroup.test.ts web/scripts/drift/justifications.json"
/home/sico/Code/Lemely/.venv/bin/pre-commit run --files $FILES
SKIP=import-linter git commit -S -m "feat(web): grouped list primitives and edge-to-edge cards on native phones" -- $FILES
```

---

### Task 11: Press states (iOS dim + scale, Android state layer + ripple)

**Files:**
- Create: `web/src/lib/pressFeedback.ts`, `web/tests/unit/pressFeedback.test.ts`
- Modify: `web/src/index.css` (native press rules after the `.lm-press` marker), `web/src/components/ui/button.tsx` (recipe base gets `lm-press`), `web/src/components/ui/nav-shells.tsx` (tab and row cells), `web/src/components/shell/shellStyles.ts` (`SHELL_ICON_BUTTON`), `web/src/components/shell/PortalShell.tsx` (install once)

**Interfaces:**
- Produces:
  - `pressOrigin(rect: { left: number; top: number; width: number; height: number }, x: number, y: number): { x: string; y: string; r: string }`, the ripple origin and radius as CSS px strings.
  - `installPressFeedback(root: Document | HTMLElement): () => void`, one delegated `pointerdown` listener for `.lm-press`. It sets `--lm-press-x`, `--lm-press-y` and `--lm-press-r` and toggles `data-pressed` until `pointerup` or `pointercancel`.

- [ ] **Step 1: Failing tests**

```ts
// web/tests/unit/pressFeedback.test.ts
import { readdirSync, readFileSync, statSync } from "node:fs"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"
import { pressOrigin } from "@/lib/pressFeedback"

const SRC = join(fileURLToPath(new URL("../../", import.meta.url)), "src")
const css = readFileSync(join(SRC, "index.css"), "utf8")
const read = (p: string) => readFileSync(join(SRC, p), "utf8")

describe("pressOrigin", () => {
  it("the ripple starts at the touch point and covers the farthest corner", () => {
    expect(pressOrigin({ left: 10, top: 20, width: 100, height: 40 }, 10, 20)).toEqual({ x: "0px", y: "0px", r: `${Math.ceil(Math.hypot(100, 40))}px` })
    expect(pressOrigin({ left: 0, top: 0, width: 100, height: 40 }, 50, 20)).toEqual({ x: "50px", y: "20px", r: `${Math.ceil(Math.hypot(50, 20))}px` })
  })
})

describe("press CSS (brief §3.5)", () => {
  const block = css.slice(css.indexOf("/* ── Native frame: press states"))
  it("iOS: dim plus scale while pressed", () => {
    expect(block).toMatch(/\[data-platform="ios"\] \.lm-press:is\(:active, \[data-pressed\]\) \{[^}]*scale: var\(--native-press-scale\)/)
    expect(block).toMatch(/background-color: color-mix\(in oklch, currentColor var\(--native-press-dim\), transparent\)/)
  })
  it("Android: state layer plus a ripple from the touch point", () => {
    expect(block).toMatch(/\[data-platform="android"\] \.lm-press\[data-pressed\]::after \{[^}]*radial-gradient\(circle at var\(--lm-press-x\) var\(--lm-press-y\)/)
    expect(block).toContain("var(--native-state-pressed)")
  })
  it("visible in under 50ms: no transition delay on the press-in", () => {
    expect(block).not.toMatch(/\.lm-press[^{]*\{[^}]*transition-delay/)
  })
})

describe("press is applied to the primitives", () => {
  it("button, tab, shell icon button, list row", () => {
    expect(read("components/ui/button.tsx")).toContain("lm-press")
    expect(read("components/ui/nav-shells.tsx")).toContain("lm-press")
    expect(read("components/shell/shellStyles.ts")).toContain("lm-press")
    expect(read("components/ui/list-group.tsx")).toContain("lm-press")
  })
})

describe("no hover-only affordances on phones", () => {
  it("no element is revealed only by group-hover without a touch fallback", () => {
    const offenders: string[] = []
    const walk = (dir: string): string[] => {
      return readdirSync(dir).flatMap((f) => { const p = join(dir, f); return statSync(p).isDirectory() ? walk(p) : p.endsWith(".tsx") ? [p] : [] })
    }
    for (const file of [...walk(join(SRC, "components")), ...walk(join(SRC, "portals"))]) {
      for (const [i, line] of readFileSync(file, "utf8").split("\n").entries()) {
        if (/\bopacity-0\b/.test(line) && /group-hover:opacity-100/.test(line) && !/(pointer-coarse|focus-within|focus-visible|native):opacity-100/.test(line)) {
          offenders.push(`${file.slice(SRC.length + 1)}:${i + 1}`)
        }
      }
    }
    expect(offenders).toEqual([])
  })
})
```

Run: `cd web && npx vitest run tests/unit/pressFeedback.test.ts`
Expected: FAIL. The hover-only scan may also list existing offenders. Fix each one in this task by adding `pointer-coarse:opacity-100` next to `group-hover:opacity-100`, and list the files in the commit body.

- [ ] **Step 2: `pressFeedback.ts`**

```ts
/*
 * Native frame press feedback (brief §3.5). One delegated listener for the
 * whole app; elements opt in with `.lm-press`. CSS does the drawing; this only
 * records the touch point (Android ripple) and the pressed flag.
 */
export function pressOrigin(rect: { left: number; top: number; width: number; height: number }, x: number, y: number) {
  const px = x - rect.left
  const py = y - rect.top
  const r = Math.ceil(Math.hypot(Math.max(px, rect.width - px), Math.max(py, rect.height - py)))
  return { x: `${px}px`, y: `${py}px`, r: `${r}px` }
}

export function installPressFeedback(root: Document | HTMLElement): () => void {
  let pressed: HTMLElement | null = null
  const release = () => {
    pressed?.removeAttribute("data-pressed")
    pressed = null
  }
  const down = (event: Event) => {
    const e = event as PointerEvent
    const el = (e.target as Element | null)?.closest<HTMLElement>(".lm-press")
    if (!el || (el as HTMLButtonElement).disabled) return
    const o = pressOrigin(el.getBoundingClientRect(), e.clientX, e.clientY)
    el.style.setProperty("--lm-press-x", o.x)
    el.style.setProperty("--lm-press-y", o.y)
    el.style.setProperty("--lm-press-r", o.r)
    el.setAttribute("data-pressed", "")
    pressed = el
  }
  root.addEventListener("pointerdown", down, { passive: true })
  for (const type of ["pointerup", "pointercancel", "pointerleave", "dragstart"]) root.addEventListener(type, release, { passive: true })
  return () => {
    root.removeEventListener("pointerdown", down)
    for (const type of ["pointerup", "pointercancel", "pointerleave", "dragstart"]) root.removeEventListener(type, release)
  }
}
```

- [ ] **Step 3: CSS (after Task 10's `.lm-press` marker rule)**

```css
/* ── Native frame: press states (native frame Task 11). Phone width on
   iOS/Android; design A keeps its own active:scale-[0.98] rules. */
@media (max-width: 720px) {
  :root:is([data-platform="ios"], [data-platform="android"]) .lm-press {
    position: relative;
    isolation: isolate;
    transition: scale var(--dur-instant) var(--ease-out-soft), background-color var(--dur-instant) var(--ease-out-soft);
  }
  :root[data-platform="ios"] .lm-press:is(:active, [data-pressed]) {
    scale: var(--native-press-scale);
    background-color: color-mix(in oklch, currentColor var(--native-press-dim), transparent);
  }
  :root[data-platform="android"] .lm-press { overflow: hidden; }
  :root[data-platform="android"] .lm-press[data-pressed]::after {
    content: "";
    position: absolute;
    inset: 0;
    z-index: -1;
    pointer-events: none;
    background:
      radial-gradient(circle at var(--lm-press-x) var(--lm-press-y), color-mix(in oklch, currentColor var(--native-state-pressed), transparent) 0 var(--lm-press-r), transparent var(--lm-press-r)),
      color-mix(in oklch, currentColor var(--native-state-pressed), transparent);
    animation: lm-ripple var(--dur-base) var(--ease-out-soft) both;
  }
}
@keyframes lm-ripple {
  from { clip-path: circle(0 at var(--lm-press-x) var(--lm-press-y)); }
  to { clip-path: circle(var(--lm-press-r) at var(--lm-press-x) var(--lm-press-y)); }
}
```

In the reduced-motion block, add `.lm-press, .lm-press::after { transition: none; animation: none; }`. The state layer stays visible, but the ripple does not grow.

The press-in has no delay. The CSS transition runs from the first frame, so the press shows in under 50ms.

- [ ] **Step 4: Apply and install**

- `button.tsx`: add `lm-press` to the `cva` base string.
- `nav-shells.tsx`: add `lm-press` to the `BottomNav` cell and both `SidebarNav` row recipes.
- `shellStyles.ts`: add `lm-press` to `SHELL_ICON_BUTTON`.
- `list-group.tsx`: already has it.
- `PortalShell.tsx`: `useEffect(() => installPressFeedback(document), [])`.

Run: `cd web && npx vitest run tests/unit/pressFeedback.test.ts tests/unit/hoverTransition.test.ts tests/unit/navShells.test.ts tests/unit/utilityExistence.test.ts tests/unit/motionDefaults.test.ts && node scripts/check-native-invariants.mjs`
Expected: PASS.

- [ ] **Step 5: Drift and commit**

```bash
cd web && npm run build && node scripts/home-drift.mjs --scene student-,teacher-,native-
```

Expected: no drift anywhere. The press state is not captured at rest, and `.lm-press` does nothing outside native.

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/student-home-variants
FILES="web/src/lib/pressFeedback.ts web/src/index.css web/src/components/ui/button.tsx web/src/components/ui/nav-shells.tsx web/src/components/shell/shellStyles.ts web/src/components/shell/PortalShell.tsx web/tests/unit/pressFeedback.test.ts <hover-only fixes from Step 1>"
/home/sico/Code/Lemely/.venv/bin/pre-commit run --files $FILES
SKIP=import-linter git commit -S -m "feat(web): native press states, iOS dim and scale, Android state layer and ripple" -- $FILES
```

---

### Task 12: Interactive edge swipe-back (iOS standalone, D5)

**Files:**
- Modify: `web/src/lib/nav/edgeSwipeBack.ts` (`edgeSwipeEnabled`), `web/src/components/edge-swipe-back.tsx` (interactive transform, parallax, release), `web/src/components/shell/PortalShell.tsx` (`data-shell-column` on the column div), `web/src/index.css` (swipe underlay and `data-direction="swipe"`), `web/tests/unit/edgeSwipeBack.test.ts` (create, or extend the existing one if present: `ls web/tests/unit | grep -i edge`)

**Interfaces:**
- Consumes: `swipeBackRelease` (Task 6), `readPlatform`, `useDragGesture` (its `onProgress`, `transformTarget` and `touchAction` options exist).
- Produces: `edgeSwipeEnabled(input: { platform: Platform; standalone: boolean; phone: boolean }): boolean`. `edgeSwipeDecision` loses its `standalone` field, because the gate moves to `edgeSwipeEnabled`.

- [ ] **Step 1: Failing tests**

```ts
// web/tests/unit/edgeSwipeBack.test.ts (append if the file exists)
import { describe, expect, it } from "vitest"
import { edgeSwipeEnabled } from "@/lib/nav/edgeSwipeBack"

describe("edge swipe-back gate (native frame D5)", () => {
  it.each([
    ["ios", true, true, true],     // iOS home-screen app: no system back gesture
    ["ios", false, true, false],   // iOS Safari tab: the system swipe wins
    ["android", true, true, false],// Android: system back (gesture or button) wins
    ["other", true, true, false],
    ["ios", true, false, false],   // iPad width: not the phone frame
  ] as const)("%s standalone=%s phone=%s -> %s", (platform, standalone, phone, want) => {
    expect(edgeSwipeEnabled({ platform, standalone, phone })).toBe(want)
  })
})
```

Update any existing `edgeSwipeDecision` tests that pass `standalone`: drop the field, and remove the case "standalone false → none", which is now `edgeSwipeEnabled`'s job.

- [ ] **Step 2: Logic**

In `edgeSwipeBack.ts`:

```ts
import type { Platform } from "@/lib/platform"

/** Native frame D5: only where the browser gives no back gesture of its own:
 * an iOS (or iPadOS) home-screen app on the phone frame. iOS Safari tabs and
 * every Android session already have a system back. */
export function edgeSwipeEnabled({ platform, standalone, phone }: { platform: Platform; standalone: boolean; phone: boolean }): boolean {
  return platform === "ios" && standalone && phone
}
```

Remove `standalone` from `EdgeSwipeInput` and from `edgeSwipeDecision`'s body. Update the file's header comment to say the gate moved.

- [ ] **Step 3: Interactive component**

In `edge-swipe-back.tsx`:
- `enabled: edgeSwipeEnabled({ platform: readPlatform(), standalone, phone })`, with `phone` from `useNativeFrame()`.
- `transformTarget`: a ref to `document.querySelector("[data-shell-column]")`.
- `touchAction: "pan-y"`.
- `onProgress(dx)`: set `--lm-swipe-progress` (0..1) on `html` and `data-swiping` on `html`. The column follows the finger through `useDragGesture`'s own transform. The underlay is drawn by CSS (below).
- `onCommit(dx, dy)`: compute the velocity from the last two progress samples, kept in a ref with `performance.now()`. If `swipeBackRelease({ dx: dx * dir, velocity, width })` is `"commit"` and `edgeSwipeDecision(...)` is `"back"`, set `html[data-direction="swipe"]` and navigate exactly as today. Otherwise let the hook spring back. Always clear `data-swiping` and `--lm-swipe-progress`.

`RootOutlet` sets `data-direction` in a layout effect on navigation. After a swipe it must keep `"swipe"` for that one navigation. Set a module flag `swipeNavPending = true` before `navigate`, and have `RootOutlet` read and clear it: `document.documentElement.dataset.direction = consumeSwipeNav() ? "swipe" : navigationDirection(type)`. Export `consumeSwipeNav` from `edgeSwipeBack.ts`.

CSS (`index.css`):

```css
/* ── Native frame: swipe-back (native frame Task 12). The column follows the
   finger; the shell ground under it shows a dimmed parallax strip. */
html[data-swiping] [data-shell-column] {
  box-shadow: calc(-1 * var(--native-group-inset)) 0 var(--native-group-inset) color-mix(in oklch, var(--md-shadow) 18%, transparent);
}
html[data-swiping] body::before {
  content: "";
  position: fixed;
  inset: 0;
  background: color-mix(in oklch, var(--md-scrim) calc((1 - var(--lm-swipe-progress, 0)) * 30%), transparent);
  translate: calc((var(--lm-swipe-progress, 0) - 1) * var(--native-parallax) * 100%) 0;
  pointer-events: none;
}
/* Pushes and pops: platform easing on the existing data-direction slides (brief §3.6). */
:root[data-platform="android"]::view-transition-old(root),
:root[data-platform="android"]::view-transition-new(root) { animation-timing-function: var(--ease-m3-emphasized); }
:root[data-platform="ios"]::view-transition-old(root),
:root[data-platform="ios"]::view-transition-new(root) { animation-timing-function: var(--ease-ios-spring); }
html[data-direction="swipe"]::view-transition-old(root) { animation: none; }
html[data-direction="swipe"]::view-transition-new(root) {
  animation: lm-swipe-in var(--dur-base) var(--ease-ios-spring) both;
}
@keyframes lm-swipe-in { from { translate: calc(-1 * var(--native-parallax) * 100%) 0; } }
```

In RTL, the parallax direction mirrors. Add `[dir="rtl"]` twins with the sign flipped. The reduced-motion block already strips `::view-transition-*`; add `html[data-swiping] body::before { translate: none; }`.

- [ ] **Step 4: Behaviour check (emulated standalone)**

Playwright's `emulateMedia` cannot set `display-mode`. Instead, an init script fakes `navigator.standalone = true` (iOS) and stubs `matchMedia("(display-mode: standalone)")`. `isStandaloneDisplay` reads both, so the stub covers it. Add one optional field, `app.init`, to `openApp` in `harness.mjs`. It is a function passed to `context.addInitScript` before the page opens.

```js
const STANDALONE = () => {
  Object.defineProperty(navigator, "standalone", { value: true })
  const real = window.matchMedia.bind(window)
  window.matchMedia = (q) => (q.includes("display-mode: standalone") ? { matches: true, media: q, addEventListener() {}, removeEventListener() {} } : real(q))
}
NATIVE_CHECKS.push(
  {
    id: "native-ios-standalone-swipe-back",
    platform: "ios",
    app: { ...NATIVE_HOME, path: "/student", init: STANDALONE },
    async run(page) {
      await page.getByRole("link", { name: "Classes" }).first().click()
      await page.waitForURL(/\/student\/classes/)
      await page.mouse.move(4, 400)
      await page.mouse.down()
      await page.mouse.move(60, 402, { steps: 4 })
      if (!(await page.evaluate(() => document.documentElement.hasAttribute("data-swiping")))) throw new Error("drag did not start an interactive swipe")
      await page.mouse.move(200, 404, { steps: 6 })
      await page.mouse.up()
      await page.waitForURL(/\/student$/)
    },
  },
  {
    id: "native-ios-swipe-short-cancels",
    platform: "ios",
    app: { ...NATIVE_HOME, path: "/student/classes", init: STANDALONE },
    async run(page) {
      await page.mouse.move(4, 400)
      await page.mouse.down()
      await page.mouse.move(60, 402, { steps: 20 })
      await page.mouse.up()
      await page.waitForTimeout(400)
      if (!/\/student\/classes/.test(page.url())) throw new Error("a short slow swipe navigated")
    },
  },
  {
    id: "native-android-no-swipe-back",
    platform: "android",
    app: { ...NATIVE_HOME, path: "/student/classes", init: STANDALONE },
    async run(page) {
      await page.mouse.move(4, 400)
      await page.mouse.down()
      await page.mouse.move(250, 402, { steps: 6 })
      await page.mouse.up()
      await page.waitForTimeout(400)
      if (!/\/student\/classes/.test(page.url())) throw new Error("Android installed an in-app swipe-back (D5)")
    },
  },
  {
    id: "native-ios-swipe-keeps-text-selectable",
    platform: "ios",
    app: { ...NATIVE_HOME, path: "/student/classes", init: STANDALONE },
    async run(page) {
      const sel = await page.evaluate(() => getComputedStyle(document.querySelector("main")).userSelect)
      if (sel === "none") throw new Error("content lost text selection")
    },
  },
)
```

Show it can go red: return `false` from `edgeSwipeEnabled`, rebuild, and expect the first check FAIL "did not start". Restore it.

- [ ] **Step 5: Verify and commit**

```bash
cd web && npx vitest run tests/unit/edgeSwipeBack.test.ts tests/unit/navigationDirection.test.ts tests/unit/rtlSafety.test.ts tests/unit/motionDefaults.test.ts && npm run build && node scripts/shell-behaviour.mjs && node scripts/home-drift.mjs --scene student-,teacher-
```

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/student-home-variants
FILES="web/src/lib/nav/edgeSwipeBack.ts web/src/components/edge-swipe-back.tsx web/src/components/root-outlet.tsx web/src/components/shell/PortalShell.tsx web/src/index.css web/scripts/drift/harness.mjs web/scripts/drift/checks-native.mjs web/tests/unit/edgeSwipeBack.test.ts"
/home/sico/Code/Lemely/.venv/bin/pre-commit run --files $FILES
SKIP=import-linter git commit -S -m "feat(web): interactive swipe-back with parallax on iOS home-screen apps" -- $FILES
```

---

### Task 13: Shell pull-to-refresh on every root (D6) and Android-only haptics

**Files:**
- Create: `web/src/components/shell/ShellPullToRefresh.tsx`, `web/tests/unit/shellPullToRefresh.test.ts`
- Modify: `web/src/components/shell/PortalShell.tsx` (wrap the outlet on roots), `web/src/lib/haptics.ts` (`nativeHaptic`), `web/src/components/ui/bottom-sheet.tsx` (snap uses `nativeHaptic`), `web/src/lib/gestures/useLongPress.ts` (`nativeHaptic` on commit), student `screens/Overview.tsx`, `screens/Notifications.tsx` and `screens/Announcements.tsx` (remove their own `usePullToRefresh` and `PullIndicator`), `web/tests/unit/nativeSheets.test.ts` (the haptic assertion moves), `web/scripts/drift/checks-native.mjs`

**Interfaces:**
- Consumes: `usePullToRefresh`, `PullIndicator`, `useQueryClient`, `titleLevelFor`.
- Produces:
  - `ShellPullToRefresh({ enabled, children })`: refetches `{ type: "active" }` queries and fires `nativeHaptic("tap")` when a pull arms.
  - `nativeHaptic(kind: HapticKind, platform?: Platform): boolean` (vibrates only when the platform is `android`).

- [ ] **Step 1: Failing tests**

```ts
// web/tests/unit/shellPullToRefresh.test.ts
import { readFileSync } from "node:fs"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { describe, expect, it, vi } from "vitest"
import { nativeHaptic } from "@/lib/haptics"

const SRC = join(fileURLToPath(new URL("../../", import.meta.url)), "src")
const read = (p: string) => readFileSync(join(SRC, p), "utf8")

describe("nativeHaptic (brief §3.5: Android only)", () => {
  it("vibrates on Android, nowhere else", () => {
    const vibrate = vi.fn(() => true)
    const nav = { vibrate }
    expect(nativeHaptic("tap", "android", nav)).toBe(true)
    expect(nativeHaptic("tap", "ios", nav)).toBe(false)
    expect(nativeHaptic("tap", "other", nav)).toBe(false)
    expect(vibrate).toHaveBeenCalledTimes(1)
    expect(vibrate).toHaveBeenCalledWith(10)
  })
})

describe("one pull-to-refresh, owned by the shell (D6)", () => {
  it("PortalShell wraps root pages only", () => {
    const shell = read("components/shell/PortalShell.tsx")
    expect(shell).toMatch(/<ShellPullToRefresh enabled=\{native && level === "root"\}>/)
  })
  it("the scroller contains overscroll", () => {
    expect(read("components/shell/ShellPullToRefresh.tsx")).toContain("overscroll-y-contain")
  })
  it("screens no longer wire their own", () => {
    for (const f of ["portals/student/screens/Overview.tsx", "portals/student/screens/Notifications.tsx", "portals/student/screens/Announcements.tsx"]) {
      expect(read(f), f).not.toContain("usePullToRefresh")
    }
  })
  it("sheet snap and long-press use the Android-only haptic", () => {
    expect(read("components/ui/bottom-sheet.tsx")).toContain('nativeHaptic("tap")')
    expect(read("lib/gestures/useLongPress.ts")).toContain("nativeHaptic(")
  })
})
```

Change Task 6's `nativeSheets.test.ts` assertion "Android-only haptic on snap" to `expect(src).toContain('nativeHaptic("tap")')`.

- [ ] **Step 2: `haptics.ts`**

```ts
import { readPlatform, type Platform } from "@/lib/platform"

/** Native frame: commit gestures (pull-to-refresh trigger, sheet snap,
 * long-press) buzz on Android only. iOS Safari has no Vibration API, and
 * desktop Chrome's `vibrate` exists but means nothing. */
export function nativeHaptic(
  kind: HapticKind,
  platform: Platform = readPlatform(),
  nav: VibrationCapableNavigator | undefined = typeof navigator === "undefined" ? undefined : navigator,
): boolean {
  return platform === "android" ? haptic(kind, nav) : false
}
```

- [ ] **Step 3: `ShellPullToRefresh.tsx`**

```tsx
import { useRef, type ReactNode } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { PullIndicator } from "@/components/ui/pull-indicator"
import { usePullToRefresh } from "@/lib/gestures/usePullToRefresh"
import { nativeHaptic } from "@/lib/haptics"

/** Native frame D6: one pull-to-refresh on every root page of both portals.
 * It refetches whatever the page is showing (active queries), so no screen
 * has to wire its own. */
export function ShellPullToRefresh({ enabled, children }: { enabled: boolean; children: ReactNode }) {
  const surface = useRef<HTMLDivElement>(null)
  const queryClient = useQueryClient()
  const { pulling, refreshing } = usePullToRefresh(surface, {
    enabled,
    onRefresh: async () => {
      nativeHaptic("tap")
      await queryClient.refetchQueries({ type: "active" })
    },
  })
  return (
    <div ref={surface} className="overscroll-y-contain">
      {enabled ? <PullIndicator progress={pulling ? 1 : 0} refreshing={refreshing} /> : null}
      {children}
    </div>
  )
}
```

In `PortalShell.tsx`, compute `level = titleLevelFor(topBar.trail)` (or `topBar.titleLevel ?? …`) and `const { native } = useNativeFrame()`. Wrap the `ErrorBoundary`/`ScreenOutlet` block in `<ShellPullToRefresh enabled={native && level === "root"}>`.

Remove the screen-level `usePullToRefresh` and `PullIndicator` (imports, ref and JSX) from student `Overview.tsx`, `Notifications.tsx` and `Announcements.tsx`. If one of those screens refetched something that is not an active query, for example by calling a non-query function, keep that call inside a `useEffect` keyed on the shell's refetch, and note it in the commit body. Otherwise delete it.

In `useLongPress.ts`, call `nativeHaptic("tap")` where the long-press commits. In `bottom-sheet.tsx`, replace `if (readPlatform() === "android") haptic("tap")` with `nativeHaptic("tap")`.

- [ ] **Step 4: Behaviour check**

```js
NATIVE_CHECKS.push({
  id: "native-android-pull-to-refresh-refetches",
  platform: "android",
  app: NATIVE_HOME,
  async run(page) {
    let calls = 0
    await page.route("**/api/student/overview**", (route) => { calls++; return route.fallback() })
    const main = page.locator("main")
    const box = await main.boundingBox()
    await page.mouse.move(box.x + 100, box.y + 40)
    await page.mouse.down()
    await page.mouse.move(box.x + 100, box.y + 200, { steps: 10 })
    await page.mouse.up()
    await page.waitForTimeout(500)
    if (calls < 1) throw new Error("pull did not refetch the page's queries")
  },
})
```

The route glob must be the overview API path that `studentShellMocks` serves; check `mocks.mjs` and name it exactly. Add the same check for a teacher root (`app: NATIVE_TEACHER_HOME`, counting the teacher dashboard's API path). Show it can go red: pass `enabled={false}` and expect FAIL.

- [ ] **Step 5: Verify and commit**

```bash
cd web && npx vitest run tests/unit/shellPullToRefresh.test.ts tests/unit/nativeSheets.test.ts tests/unit/prefetchWiring.test.ts tests/unit/screenEntrance.test.ts && npm run build && node scripts/shell-behaviour.mjs && node scripts/home-drift.mjs --scene student-,teacher-,native-
```

Expected: existing scenes are unchanged. `PullIndicator` renders nothing at rest. Check the `student-populated-frame` keys in particular: the Overview's own indicator is gone, and the shell's is disabled on `other`.

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/student-home-variants
FILES="web/src/components/shell/ShellPullToRefresh.tsx web/src/components/shell/PortalShell.tsx web/src/lib/haptics.ts web/src/components/ui/bottom-sheet.tsx web/src/lib/gestures/useLongPress.ts web/src/portals/student/screens/Overview.tsx web/src/portals/student/screens/Notifications.tsx web/src/portals/student/screens/Announcements.tsx web/tests/unit/shellPullToRefresh.test.ts web/tests/unit/nativeSheets.test.ts web/scripts/drift/checks-native.mjs"
/home/sico/Code/Lemely/.venv/bin/pre-commit run --files $FILES
SKIP=import-linter git commit -S -m "feat(web): shell pull-to-refresh on every root and Android-only haptics" -- $FILES
```

---

### Task 14: Teacher dense tables become list rows on phones (primitive + Review queue + Class roster)

**Files:**
- Create: `web/src/components/ui/table-or-list.tsx`, `web/tests/unit/tableOrList.test.ts`
- Modify: `web/src/portals/teacher/screens/Review.tsx`, `web/src/portals/teacher/screens/ClassRoster.tsx`, `web/scripts/drift/checks-native.mjs`

**Interfaces:**
- Consumes: `ListGroup`, `ListRow` (Task 10), `useNativeFrame`.
- Produces: `TableOrList(props: { label: string; table: ReactNode; list: ReactNode; storageKey: string })`. On native it shows `list` with a "View table" text button. That button swaps to `table` inside a horizontally scrollable region with `role="region"`, `aria-label={label}`, `tabIndex={0}`, plus a "View list" button. The choice persists in `sessionStorage[storageKey]`, wrapped in try/catch. Off native it renders `table` unchanged.

- [ ] **Step 1: Failing tests (`web/tests/unit/tableOrList.test.ts`)**

```ts
import { readFileSync } from "node:fs"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import { TableOrList } from "@/components/ui/table-or-list"
import { NativeFrameProvider } from "@/lib/useNativeFrame"

const SRC = join(fileURLToPath(new URL("../../", import.meta.url)), "src")
const props = { label: "Review queue", storageKey: "t", table: createElement("table", null, "T"), list: createElement("ul", null, "L") }
const render = (native: boolean) =>
  renderToStaticMarkup(
    createElement(NativeFrameProvider, { value: { platform: native ? "android" : "other", phone: native, native } }, createElement(TableOrList, props)),
  )

describe("TableOrList (brief decision 4)", () => {
  it("off native: the table, untouched, no toggle", () => {
    const out = render(false)
    expect(out).toContain("<table>T</table>")
    expect(out).not.toContain("View table")
  })
  it("on native: the list first, with a View table escape hatch", () => {
    const out = render(true)
    expect(out).toContain("<ul>L</ul>")
    expect(out).toMatch(/<button[^>]*type="button"[^>]*>View table<\/button>/)
    expect(out).not.toContain("<table>")
  })
  it("Review and ClassRoster use it", () => {
    for (const f of ["portals/teacher/screens/Review.tsx", "portals/teacher/screens/ClassRoster.tsx"]) {
      expect(readFileSync(join(SRC, f), "utf8"), f).toContain("<TableOrList")
    }
  })
})
```

- [ ] **Step 2: Implement `table-or-list.tsx`**

```tsx
import { useState, type ReactNode } from "react"
import { useNativeFrame } from "@/lib/useNativeFrame"

/** Native frame: dense teacher tables read as list rows on phones, with
 * "View table" for when the grid itself is the point (brief decision 4). */
export function TableOrList({ label, table, list, storageKey }: { label: string; table: ReactNode; list: ReactNode; storageKey: string }) {
  const { native } = useNativeFrame()
  const [asTable, setAsTable] = useState(() => {
    try {
      return typeof sessionStorage !== "undefined" && sessionStorage.getItem(storageKey) === "table"
    } catch {
      return false
    }
  })
  if (!native) return <>{table}</>
  const toggle = () => {
    const next = !asTable
    setAsTable(next)
    try {
      sessionStorage.setItem(storageKey, next ? "table" : "list")
    } catch {
      /* private mode: the choice lasts until reload */
    }
  }
  return (
    <div className="flex flex-col gap-2">
      <div className="flex justify-end px-4">
        <button type="button" onClick={toggle} className="lm-press text-label text-primary">
          {asTable ? "View list" : "View table"}
        </button>
      </div>
      {asTable ? (
        <div role="region" aria-label={label} tabIndex={0} className="-mx-4 overflow-x-auto px-4 lm-scroll">
          {table}
        </div>
      ) : (
        list
      )}
    </div>
  )
}
```

- [ ] **Step 3: Review queue and Class roster**

Read each screen. Keep the existing `<Table>…</Table>` JSX as the `table` prop. Write a `list` that renders the same rows as `ListRow`s inside one `ListGroup`:
- Review: title = student name, subtitle = paper code and question, trailing = confidence %, in mono. Each row links where the table row links.
- ClassRoster: title = student name, subtitle = latest grade and papers count, trailing = chevron. Same link.

Empty, loading and error states stay as the screen renders them today. Loading uses the Task 10 list skeleton on native. The rows come from the same data array the table maps over, so the two cannot drift. Make sure the list maps that same variable.

- [ ] **Step 4: Behaviour check, verify, commit**

Add a check `native-android-review-list-and-table` on `/teacher/review` with the teacher mocks. Expect a `ListRow` link per queued item, click "View table", and expect `getByRole("region", { name: "Review queue" })` to contain a `table`. Reload and expect the table view to persist (`sessionStorage`).

```bash
cd web && npx vitest run tests/unit/tableOrList.test.ts tests/unit/a11yRules.test.ts tests/unit/reviewBadge.test.ts && npm run build && node scripts/shell-behaviour.mjs --check native- && node scripts/home-drift.mjs --scene teacher-
```

Expected: the teacher `content` gate keys stay 0 px. They run as `other`, so the table is unchanged.

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/student-home-variants
FILES="web/src/components/ui/table-or-list.tsx web/src/portals/teacher/screens/Review.tsx web/src/portals/teacher/screens/ClassRoster.tsx web/tests/unit/tableOrList.test.ts web/scripts/drift/checks-native.mjs"
/home/sico/Code/Lemely/.venv/bin/pre-commit run --files $FILES
SKIP=import-linter git commit -S -m "feat(web): teacher review queue and roster read as list rows on phones, with View table" -- $FILES
```

---

### Task 15: Roll `TableOrList` out to the remaining teacher table screens

The screens are `ClassPapers`, `AtRiskList`, `MarkSchemes`, `Quizzes`, `QuizResults`, `StudentDetail`, `ClassAnalytics`, `Classes` and `tutoring/PreviewReviews`, all under `web/src/portals/teacher/screens/`. Admin and marketing tables are out of scope: admin is not on this shell, and the brief covers students, teachers and later parents.

This task can be split across up to three parallel agents. Each gets a disjoint set of three screens and commits only its own paths with `git commit -S -- <its paths>`.

**Files:** the nine screens above, `web/tests/unit/tableOrList.test.ts` (extend the "uses it" list; one agent owns this file, the others report their screen names to it), `web/scripts/drift/checks-native.mjs` (the same single owner).

**Interfaces:** consumes `TableOrList`, `ListGroup` and `ListRow`. Produces nothing new.

- [ ] **Step 1: Extend the test list** with the nine paths, so it fails for each screen not yet converted.

Run: `cd web && npx vitest run tests/unit/tableOrList.test.ts`
Expected: FAIL, naming each unconverted screen.

- [ ] **Step 2: Convert each screen** as in Task 14 Step 3. The list maps the same data array as the table. Title is the row's primary name, subtitle holds its one or two most decision-relevant columns, and trailing holds the single number a teacher scans (mono). Data-heavy charts on `ClassAnalytics` stay as one full-width `Card`; only its table converts. Commit one screen at a time:

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/student-home-variants
/home/sico/Code/Lemely/.venv/bin/pre-commit run --files web/src/portals/teacher/screens/<Screen>.tsx
SKIP=import-linter git commit -S -m "feat(web): <screen> reads as list rows on phones, with View table" -- web/src/portals/teacher/screens/<Screen>.tsx
```

- [ ] **Step 3: Verify and commit the test and checks**

```bash
cd web && npx vitest run tests/unit/tableOrList.test.ts tests/unit/a11yRules.test.ts tests/unit/capabilityWiring.test.ts tests/unit/recentlyDeletedWiring.test.ts && npm run build && node scripts/home-drift.mjs --scene teacher-
```

Expected: PASS. Teacher content keys stay 0 px.

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/student-home-variants
FILES="web/tests/unit/tableOrList.test.ts web/scripts/drift/checks-native.mjs"
/home/sico/Code/Lemely/.venv/bin/pre-commit run --files $FILES
SKIP=import-linter git commit -S -m "test(web): every teacher table screen offers list rows on phones" -- $FILES
```

---

### Task 16: Final verification, drift sweep, approvals

**Files:**
- Modify: `web/scripts/drift/justifications.json` (approval states, only as the user decides)
- Modify: `docs/superpowers/specs/2026-11-08-native-mobile-feel-brief.md` (append a "Drift log" table)

**Interfaces:** none. This task certifies only the tree it ran on; if a fix commit lands afterwards, re-run it from Step 1.

- [ ] **Step 1: Re-check where you are**

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/student-home-variants
git status --short --branch
git log --oneline -25
```

Expected: branch `design/student-home-variants`, with the Task 0 to 15 commits present. Untracked `.impeccable/` folders and designer preview edits are left alone and listed in the report.

- [ ] **Step 2: CI web gates that need no backend**

```bash
grep -nE "run:|npm run|npx " .github/workflows/ci.yml | grep -iE "web|npm|npx"
```

Run each web gate it lists that needs no backend, from `web/`. Expect at least `npm run typecheck`, `npm run lint`, `npm run check:copy`, `npm run check:native` and `npm run build` with `check:bundle`. `bottom-sheet.tsx`, `PanelSheet.tsx` and the list primitives join the entry chunk. If `check:bundle` fails, lazy-load `PanelSheet` the way `ShellTopBar` lazy-loads the panels. Then run the **Native sweep command** plus the P1 **Shell sweep command** (`.superpowers/sdd/p1-global-constraints.md`). Expected: every command exits 0.

- [ ] **Step 3: Behaviour and axe**

```bash
cd web && npm run build && node scripts/shell-behaviour.mjs --axe
```

Expected: every check passes, both `SHELL_CHECKS` and `NATIVE_CHECKS`, with no axe violations. Fix violations in the component; never by excluding a rule or marking a check `axe: false`.

- [ ] **Step 4: Full drift run**

```bash
node scripts/home-drift.mjs
```

Expected: **Drift acceptance** holds, and:
- every `student-*` and `teacher-*` key has the same outcome as at `ba79e15c`, with desktop keys at 0 px;
- every native gate key is `pass`, `pass-justified`, or pending approval at 15% or less;
- the log keys (`native-teacher-*`, `native-android-412-*`) all have entries.

- [ ] **Step 5: Drift log and one approval request**

Write a "Drift log" table into the brief: one row per native scene id, with the max % per platform and theme and the justification. Then collect every entry whose `approved` is not `"yes"`:

```bash
node -e 'const j=require("./scripts/drift/justifications.json");const r=require(require("path").resolve("..",process.argv[1],"report.json"));for(const [id,e] of Object.entries(j)){if(String(e.approved).toLowerCase()==="yes")continue;const keys=r.filter(k=>k.justification?.key===id);const max=Math.max(0,...keys.map(k=>k.pct));console.log(`${id} | ${keys.length} keys | max ${max.toFixed(2)}% | ${e.difference} | ${e.justification}`)}' <report dir>
```

Send the user **one** message with the whole list, grouped as native iOS gate scenes, native Android gate scenes, teacher and Android-412 log scenes, and any P1 entries still pending. Ask them to approve or reject per group, using AskUserQuestion when it is available. After they answer, set `approved: "yes"` only for the approved rows, in both files. Rejected rows are drift to fix: fix them, then re-run Steps 3 and 4. Finally re-run Step 4 and expect **exit 0**.

- [ ] **Step 6: Proof capture (brief §2)**

Copy the `native-*` app-side PNGs at 390 (both platforms) and 412 (Android), light and dark, at rest and scrolled, from the run's report directory into the report for the user. Record a short screen capture of the collapse, sheet drag, swipe-back and pull-to-refresh with Playwright's `recordVideo` on the four behaviour checks (`--check native-ios-large-title,…`; add a `--video` flag to `shell-behaviour.mjs` if needed, writing to `reports/.scratch/native-proof/`). Do not commit `reports/`.

- [ ] **Step 7: Commit**

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/student-home-variants
FILES="docs/superpowers/specs/2026-11-08-native-mobile-feel-brief.md web/scripts/drift/justifications.json"
/home/sico/Code/Lemely/.venv/bin/pre-commit run --files $FILES
SKIP=import-linter git commit -S -m "docs(web): native frame drift log and approvals" -- $FILES
```

---

### Task 17: DESIGN.md native-frame rules and the P2 adjustment note

**Files:**
- Modify: `DESIGN.md` (§5 Navigation; a new "Native phone frame" subsection under §5; §6 Do's and Don'ts)
- Modify: `.impeccable/design.json` only if it mirrors DESIGN.md's navigation text (check with `grep -n "drawer for teachers" .impeccable/design.json`)
- Modify: `docs/superpowers/plans/2026-11-06-student-home-overview.md` (an adjustment note at the top; do not rewrite tasks)

- [ ] **Step 1: DESIGN.md**

In §5 "Navigation", replace the last sentence ("On mobile the sidebar collapses to a bottom bar for students and a drawer for teachers.") with:

> On phones (720px and narrower) on iOS and Android, both portals use the native frame (below); every other phone browser keeps the flat design A bar with the bottom tabs.

Add under §5:

```markdown
### Native phone frame
"The page is the app's own list; the chrome is glass." Applies at 720px and narrower when `html[data-platform]` is `ios` or `android` (Tailwind `native:`, `ios:`, `android:`). Desktop, tablet and `other` keep design A.
- **Header:** tab roots show a large title (Bricolage 800, `--native-large-title-size`) under an actions-only bar; it collapses into a 17px Schibsted 600 inline title (centred on iOS, start-aligned on Android) when the large title's bottom crosses the bar. iOS: transparent to glass (`--blur-nav`, 86%) with a 0.5px `outline-variant` hairline once content is under it. Android: `surface` to `surface-container`, no shadow, no hairline. Detail pages use the compact bar with a back chevron from the start.
- **Tab bar:** iOS 49px plus the home indicator, glass, 11px labels, outline icons at rest and filled when selected, tinted `primary`. Android 80dp with a 64x32 `secondary-container` pill. The raised Correct button stays. Tapping the active tab scrolls to the top, then pops to the tab root. Camera, the correction run, paper review and review-a-mark hide it.
- **Sheets, not dialogs or popovers:** `Modal`, `ConfirmModal`, settings, bell, account and popovers open as bottom sheets with a grabber (36x5 iOS, 32x4 Android), `--radius-card` top corners, a scrim, drag to dismiss, and medium/large detents for long content. iOS scales the page back at the large detent. Destructive confirms are an action sheet on iOS (Cancel separate) and an M3 dialog-style sheet on Android. Selects stay native: the OS picker is the platform sheet.
- **Grouped content:** cards drop their outline. iOS: inset-grouped, 12px radius, 16px margins, 44px rows, separators inset from the leading edge. Android: full-width items (56/72/88), no separators. Page ground `surface-container-low`, rows `surface-container-lowest`. Dense teacher tables read as list rows with "View table".
- **Touch:** every tappable element has a press state (iOS 8% dim and 0.97 scale; Android 10% state layer and ripple). No hover-only affordances. 44px targets. Android-only haptics on commit gestures.
- **Gestures:** pull-to-refresh on every root (shell-owned). Swipe-back only in an iOS home-screen app (iOS Safari tabs and Android use the system back), with 30% parallax, committing at 35% width or a fast fling. Pushes slide with M3 emphasized easing on Android and a spring on iOS. Reduced motion turns it all off.
- **Brand stays:** Bricolage, Schibsted, JetBrains Mono everywhere, never SF Pro or an iOS-blue accent.
```

In §6 "Don't", add: `- **Don't** show a bottom sheet at 721px and up, or start a gesture on selectable content text.`

- [ ] **Step 2: P2 adjustment note**

Insert directly under P2's title block (above "## Revised 2026-11-06 for design `c880a54c`"):

```markdown
## Adjusted 2026-11-08 for the native mobile frame

`docs/superpowers/plans/2026-11-08-native-mobile-frame.md` lands first. Adjust these tasks when you run them (task text is not rewritten):
- **Task 9 (drift scenes):** add native scenes for the home (`platform: "ios"|"android"`, 390x844, preview `?platform=…&page=root`) next to the existing `other` scenes, using `NATIVE_PREVIEW`/`previewNativeQuery` (`web/scripts/drift/native-preview.mjs`). The existing 390 scenes keep running without a UA (design A).
- **Task 10 (home primitives):** home sections on the native frame use `ListGroup`/`ListRow` (`web/src/components/ui/list-group.tsx`) and the `native:` card rules; do not add a second card look.
- **Task 14 (Your grades):** the "one card per subject at 560px and narrower" rule is design A (`other`). On the native frame the list is one `ListGroup` (iOS inset-grouped, Android full-width), per the preview's native page.
- **Task 18 (StudentHome):** drop its own `usePullToRefresh` and `PullIndicator`; the shell's `ShellPullToRefresh` already covers root pages (native frame D6). Its page title comes from the shell's large title; any in-page `<h1>` that repeats it gets `native:sr-only`.
- **Task 19:** the old `Overview.tsx` no longer has a pull-to-refresh to remove (native frame Task 13 did it).
- **Task 20 (sweep):** include `--scene native-` and the behaviour runner's `native-` checks.
```

- [ ] **Step 3: Commit**

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/student-home-variants
FILES="DESIGN.md docs/superpowers/plans/2026-11-06-student-home-overview.md"
/home/sico/Code/Lemely/.venv/bin/pre-commit run --files $FILES
SKIP=import-linter git commit -S -m "docs(web): native phone frame rules in DESIGN.md and the P2 adjustment note" -- $FILES
```

Add `.impeccable/design.json` to `FILES` only if Step 1 changed it.

---

## Risks

1. **iOS earlier than 26 has no scroll-driven animations.** The collapse falls back to `data-collapsed`, set by a passive scroll listener batched to one rAF (Task 4). The fallback is a fade at the threshold rather than a scrubbed one. The behaviour check asserts the attribute path, so it covers older iOS, and drift (reduced motion) always uses it. Watch for jank: the listener does one `setState` per frame at most, and only on root pages on native.
2. **The iOS keyboard and sheets.** iOS ignores `interactive-widget=resizes-content`, so a focused input inside a sheet can sit under the keyboard. `useKeyboardInset` positions the sheet by `visualViewport` (`--lm-keyboard-inset`) and shrinks its max height (Task 6). Risks: `visualViewport` `scroll` events fire late on some iOS versions, and `position: fixed` with the keyboard open can jump. Test on a real iPhone before Task 16 sign-off. No emulator reproduces this, and the Playwright checks cannot.
3. **Gestures vs text selection.** Sheet drags start only on `[data-sheet-drag-region]` (grabber and header, `select-none`). Swipe-back starts only in the 24px leading edge zone and skips interactive targets. Pull-to-refresh starts only at scroll top on a vertical drag. Content keeps `user-select: auto`, which Task 12's check asserts. Remaining risk: a long-press text selection that starts within 24px of the edge. iOS standalone gives the gesture priority there, which matches native apps.
4. **View transitions on iOS earlier than 18.** `document.startViewTransition` does not exist there. react-router's `viewTransition` falls back to an instant swap, so the push slide and the swipe-in parallax do not run. That is acceptable, because navigation still works, and the swipe gesture's own finger-following transform still runs. Do not polyfill.
5. **`transform`/`scale` on `#root` for the iOS scale-back** re-anchors `position: fixed` descendants (the tab bar, banners) to `#root` while a large sheet is open. They scale with the page, which is the intended look. Sticky elements in the scaled tree also stop sticking for the duration. That is invisible, because the scroll is locked.
6. **The status bar flip (D7)** affects every standalone route at once, including screens this plan does not otherwise touch. Task 3 Step 4 is a grep-driven audit; a route it misses will draw under the clock. Check: launch standalone on a real iPhone and walk auth, onboarding and the camera.
7. **Platform emulation in drift.** Playwright's UA override does not change `navigator.userAgentData.platform` on a Linux host. The resolver therefore trusts UA-CH only for "Android" and parses the UA string otherwise. `openApp` asserts `data-platform` after load, so a resolver regression fails loudly instead of silently capturing design A.
8. **Bundle budget.** `BottomSheetSurface`, `PanelSheet` and the list primitives join shared chunks. `check:bundle` may fail at Task 16; the remedy is lazy `PanelSheet`, the same pattern as the panels.
9. **A screen's own `<h1>` repeating the large title** (open question). Hiding them is per screen and is left to a follow-up and to P2.
10. **The preview gap.** The native scenes depend on the designer's preview supporting `platform` and `page`. If the preview lacks a state (for example the settings sheet on Android), mark that scene log-only with a justification. Do not invent a reference.

## Self-review against the brief

- §3.1 header: Task 4. §3.2 tab bar: Task 5. §3.3 sheets: Tasks 6 to 9 (selects per D4). §3.4 grouped content: Tasks 10, 14 and 15. §3.5 touch feedback: Tasks 3, 11 and 13. §3.6 gestures and motion: Tasks 12 and 13. Sheet easing is in Task 6. Per-platform push easing on the existing `data-direction` slides, and the swipe-in parallax, are in Task 12's CSS. Tab crossfade is unchanged (existing view transition). §3.7 platform switch: Task 1.
- §5 states: long titles (Task 4 line clamp and truncate), badges (unchanged `BottomNav` badge), keyboard (Task 6), list states (Task 10 skeleton, Task 14 states), banners between the bar and content (the large title sits directly under the bar, and banners stay in `<main>` under it), standalone vs tab (Tasks 3 and 12).
- §7 decisions 1 to 5: preview first (Task 0), before P2 (sequencing, Task 17 note), brand fonts (Global Constraints), teachers (Tasks 4, 14 and 15, teacher scenes), DESIGN.md (Task 17).
- §2 proof: Task 16 Step 6.
