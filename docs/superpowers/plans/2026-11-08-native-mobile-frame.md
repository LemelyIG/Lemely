# Native Mobile Frame Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Below the `shell-sm` breakpoint (720px and narrower), on iPhone and Android, the student and teacher portals run in a native frame. That frame has a pinned large-title header that collapses, a per-platform tab bar, bottom sheets instead of dialogs and popovers, edge-to-edge grouped lists, press feedback, swipe-back and pull-to-refresh. Desktop, tablet and the `other` platform keep design A unchanged.

**Architecture:** A boot-time resolver in `public/shell-init.js` sets `html[data-platform="ios|android|other"]` before first paint. Tailwind v4 custom variants (`ios:`, `android:`, and `native:` = phone width AND ios|android) and a `useNativeFrame()` hook key every change off it. There are no separate component trees. `ShellTopBar`, `BottomNav`, `Modal`, `ConfirmModal`, `Sheet`, the shell panels, `Popover`, `Card` and the new `ListGroup`/`ListRow` vary by unlayered `lm-native-*` classes, `native:` utilities, and one JS switch where the markup has to differ (sheets). On native phones the shell's large title replaces a screen's own heading when that heading repeats it: screens render their top heading through one `PageHeading` component, which is visually hidden on the native frame and stays the page's one `h1` for assistive technology (D11). The design A preview, `student-home-a.html` with `?platform=ios|android&page=root|detail` (committed at `4447a571` and approved as the port reference), is the reference. The existing drift gate gains platform emulation (UA, touch, mobile) and a native scene list. Every UI task is accepted against it. The desktop and `other`-platform scenes must stay exactly as they are.

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
  tests/unit/nativeTabBar.test.ts tests/unit/pageHeading.test.ts tests/unit/sheetMath.test.ts tests/unit/nativeSheets.test.ts \
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
- **D3. The large title lives outside `<main>`**, in `ShellTopBar`'s fragment, and is always `aria-hidden="true"`. It is never a heading for assistive technology. The bar's inline title stays plain text (not a heading), as it is on desktop today. The page's one `h1` is the screen's own heading inside `<main>` (D11). Keeping the large title out of `<main>` also keeps it in the drift harness's "frame" capture, which hides `main > *`.
- **D4. Select stays a native `<select>`.** The brief lists selects among the sheets, but `ui/select.tsx` is deliberately native. Its doc comment records why: the OS picker on iOS and Android already is the platform's own sheet or wheel. A custom listbox sheet would be a worse picker and would re-implement typeahead and screen-reader semantics. Task 9 makes only Popover a sheet and pins Select as native with a test. If the user wants a custom select sheet anyway, it becomes a follow-up.
- **D5. Edge swipe-back = standalone on both platforms (user decision, 2026-11-09).** Lemely's edge swipe runs in standalone display on iOS and Android, and stays off in browser tabs, where Safari's swipe and Chrome's own back take over. That is today's gate (`standalone`), unchanged: Task 12 only makes the gesture interactive (finger-following, parallax, fling) and does not narrow or widen where it runs. The earlier draft's "iOS standalone only" is reverted.
- **D6. Pull-to-refresh moves into the shell.** One `ShellPullToRefresh` wraps `<main>` content on root-level pages (`titleLevel === "root"`) in both portals. It refetches active queries. This covers "every list and overview root" without wiring 15 screens by hand. The three per-screen copies (student Overview, Notifications, Announcements) are removed, so two gestures never nest.
- **D7. Status bar `black-translucent` flips three pinned gates.** `nativeMechanics.test.ts`, `checkNativeInvariants.test.ts` and `scripts/check-native-invariants.mjs` currently assert `"default"`. The meta only affects iOS home-screen apps, so standalone mode is the only place it matters. Task 3 flips the gates and pads every non-shell standalone root with the top safe-area inset.
- **D8. Immersive routes hide the tab bar on native:** student `correct` (camera and correction run), student paper result (paper review) and teacher review-a-mark. A route opts in with `handle.immersive: true`.
- **D9. Phone scene sizes.** The user's instruction is 390×844 for **both** platforms (gate scenes). The brief's proof also asks for 412×915 on Android. That is added as a log-only scene (`native-android-412-*`) so the screenshot exists without gating on a size the preview may not tune.
- **D10. Sheet dismissal thresholds:** a drag of more than 25% of the sheet's height, or a fling faster than 0.5 px/ms, dismisses. Otherwise the sheet snaps to the nearest detent. Swipe-back commits at 35% of width or the same fling (the brief's number). Non-dismissible dialogs (`ConfirmModal`) get no grabber and no drag. Detents follow the preview: the bell and account panels are content-fit sheets, the settings sheet and `Modal size="lg"` open at medium and drag up to large.
- **D11. One page heading on phones (user decision, 2026-11-09).** On the native frame the shell's large title **replaces** a screen's own heading when that heading repeats the page title. Desktop and tablet keep the screen's heading visible.
  - **Accessibility:** exactly one `h1` reaches assistive technology on every page, and it is the screen's own heading inside `<main>`. On native phones a repeating heading is visually hidden (`sr-only`), not removed, so it stays in the accessibility tree and in heading navigation. The large title stays `aria-hidden` (D3). Screen readers therefore never get two `h1`s (the large title is hidden from them) and never get zero (the screen's heading is still there).
  - **Mechanism:** one shared component, `PageHeading` (`web/src/components/ui/page-heading.tsx`), renders every screen's top `h1`. Its required `repeatsTitle` prop says whether the heading repeats the shell title. `repeatsTitle` adds `native:sr-only`. A heading that says something else (a greeting such as "Hi, Mariam") passes `repeatsTitle={false}` and stays visible. A unit source scan forbids a raw `<h1>` in the student and teacher screens, so no screen can bypass the component. The existing `sr-only` `h1` pattern (`query-state.tsx` `srHeading`, the Overview's `<h1 className="sr-only">`) stays allowed: it is already invisible.
  - **Rollout:** Task 5b migrates the screens' `h1`s (51 student and teacher files contain `<h1` at `4447a571`) and adds a behaviour check that fails when a native page shows a visible heading repeating the bar title, or exposes other than one `h1`.

## Open questions (not blocking; record answers in the ledger)

- [x] ~~Should a screen's own top `<h1>` that repeats the large title be visually hidden on native?~~ Answered 2026-11-09: yes, the large title replaces it on phones (D11, Task 5b).
- [x] ~~Do Android standalone users want an in-app swipe-back at all?~~ Answered 2026-11-09: yes, keep it alongside iOS (D5).
- [x] ~~Should the paper result route be immersive (D8)?~~ Answered 2026-11-09: no. The paper result keeps the tab bar. Only the camera, the correction run and teacher mark review are immersive.
- [x] ~~Glass blur radius?~~ Answered 2026-11-09: keep the one-blur rule. Task 0 changes the preview's phone glass from `blur(14px)` to `var(--blur-nav)` (10px), touching phone and `[data-platform]` rules only, so desktop stays at 0 px. The app uses `var(--blur-nav)`.
- [x] ~~Pull-to-refresh indicator?~~ Answered 2026-11-09: port the preview's per-platform indicators in Task 13: the iOS 8-spoke indicator with the content following the pull and holding 56px down, and the Android M3 disc with a growing arc, content still, holding at 64px. They replace `PullIndicator` inside the native frame. `PullIndicator` stays for anything outside the native frame.

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
| `web/src/components/shell/NativeBack.tsx` | The native bar's back control: iOS chevron plus the parent title, Android arrow. |
| `web/src/components/ui/page-heading.tsx` | `PageHeading`: every screen's top `h1`; visually hidden on native when it repeats the title (D11). |
| `web/src/components/shell/PanelSheet.tsx` | Bell and avatar trigger plus a `Modal` (a sheet on native). |
| `web/src/components/ui/use-dialog-focus.ts` | `useDialogFocus`: first focus, Tab cycle and focus return, shared by `Modal` and the native `Popover`. |
| `web/src/components/ui/list-group.tsx` | `ListGroup`, `ListRow` (iOS inset-grouped, Android full-width). |
| `web/src/lib/pressFeedback.ts` | `pressOrigin` (pure), `installPressFeedback` (one delegated listener). |
| `web/src/components/shell/ShellPullToRefresh.tsx` | Shell-level pull-to-refresh for root pages. |
| `web/src/components/ui/table-or-list.tsx` | `TableOrList`: list rows on native, with a "View table" escape hatch. |
| `web/tests/unit/{platform,nativeFrameCss,nativeTopBar,nativeTabBar,pageHeading,sheetMath,nativeSheets,listGroup,pressFeedback,shellPullToRefresh,tableOrList}.test.ts` | Unit tests (`edgeSwipeBack.test.ts` already exists and is extended). |

Modify: `web/public/shell-init.js`, `web/index.html`, `web/src/index.css`, `web/scripts/drift/harness.mjs`, `web/scripts/home-drift.mjs`, `web/scripts/drift/scenes.mjs`, `web/scripts/shell-behaviour.mjs`, `web/scripts/check-native-invariants.mjs`, `web/scripts/drift/justifications.json`, `web/src/components/shell/{ShellTopBar,PortalShell,NotificationsPanel,AccountPanel,shellStyles}.tsx|ts`, `web/src/components/ui/{nav-shells,modal,confirm-modal,sheet,popover,card,button,select,back-control,route-skeleton}.tsx`, `web/src/components/edge-swipe-back.tsx`, `web/src/components/root-outlet.tsx`, `web/src/lib/nav/edgeSwipeBack.ts`, `web/src/lib/haptics.ts`, `web/src/lib/gestures/useLongPress.ts`, `web/src/portals/settings/{SettingsModal,SettingsRows}.tsx`, `web/src/portals/student/{shell.tsx,index.tsx}`, `web/src/portals/teacher/index.tsx`, every student and teacher screen with a top `h1` (Task 5b), student `Overview`/`Notifications`/`Announcements` screens (PTR removal), teacher table screens (Tasks 14 and 15), `web/tests/unit/{nativeMechanics,checkNativeInvariants,themeInit}.test.ts`, `DESIGN.md`, `docs/superpowers/plans/2026-11-06-student-home-overview.md` (adjustment note only).

## Per-task model suggestion

| Task | Implement | Review |
|---|---|---|
| 0 tokens from preview | sonnet | opus (low) |
| 1 platform resolver | sonnet | opus |
| 2 harness and native scenes | sonnet | opus |
| 3 PWA meta and touch CSS | sonnet | opus |
| 4 large-title header | sonnet (high effort) | opus |
| 5 tab bar | sonnet | opus |
| 5b page heading sweep | sonnet (screen batches may fan out, disjoint commit paths) | opus |
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

Order: 0 → 1 → 2 → 3 → 4 → 5 → 5b → 6 → 7 → 8 → 9 → 10 → 11 → 12 → 13 → 14 → 15 → 16, with 17 alongside 16 (docs only, disjoint paths). The tasks run one at a time because every task from 4 to 14 shares at least one file with its neighbours (`web/src/index.css`, `PortalShell.tsx`, `ShellTopBar.tsx`, `checks-native.mjs`, `nativeSheets.test.ts` or `justifications.json`), and `git commit -- <paths>` would sweep one agent's half-done edits into another's commit. The only fan-outs are inside Task 5b and Task 15: disjoint screen sets per agent, with one named owner for the shared test and check files. Parallel agents must be given their commit paths up front (they share one index).

---

### Task 0: Pull exact values from the committed preview into tokens

The phone frame is committed in `web/dev-previews/student-home-a.html` at `4447a571` ("feat(web): native phone frame in design A preview"), with `?platform=ios|android&page=root|detail`, and the user approved it as the port reference. Read it at that commit (`git show 4447a571:<path>`), never from uncommitted edits. The token values and selectors below are pre-filled from the designer's report on that commit. This task **verifies each one** against the committed files and corrects any that differ.

Designer-reported hooks (verify in Step 1):
- Root attributes on `.sh-root`: `[data-platform]`, `[data-page]`, and `[data-sheet="medium|large|fit"]` while a phone sheet is open.
- Elements: `.as-lt` (large title), `.as-back` with `.as-back-ios`, `.as-back-md` and `.as-back-l`, `.as-grab`, `.as-ptr` with `.as-ptr-ios` and `.as-ptr-md`, and `[data-detents]`.
- State classes: `.as-bar.is-collapsed` and `.is-raised`, `.is-press` and `.is-release`, `.is-sheet-snapping`, and `.as-col[data-ptr="pulling|refreshing|settling"]`.
- Custom properties set by JS: `--pf-rx`, `--pf-ry`, `--pf-rr`, `--pf-ro`, `--pf-pull`, `--pf-pull-p`, `--pf-sy`, `--pf-kb`.
- Params: `platform=ios|android`, `page=root|detail`. The preview toolbar shows only with `width=mobile`, so drift uses `width=desktop` at a 390px viewport (the shell container is then 390px wide and the phone frame applies, with no toolbar in the capture).

**Files:**
- Modify: `web/src/index.css` (one new `:root` block, "Native frame tokens", directly after the `@theme inline` blocks)
- Modify: `web/dev-previews/student-home/controller.ts`, `web/dev-previews/student-home/variant-a.js` (Step 1b only: the preview's default platform is `other`)
- Create: `web/scripts/drift/native-preview.mjs`
- Create: `web/tests/unit/nativeFrameCss.test.ts` (token part; Task 1 extends it)

**Interfaces:**
- Consumes: the committed preview HTML, CSS and JS for the phone frame.
- Preview contract after Step 1b: no `platform` param means `other` (no `data-platform`, design A's own phone frame); the native frame applies only with an explicit `platform=ios|android`.
- Produces:
  - CSS custom properties: the `TOKENS` list in Step 2 (one name per measurement, a value per platform where the preview differs).
  - `native-preview.mjs` exports `NATIVE_PREVIEW` (selectors: `root`, `bar`, `largeTitle`, `inlineTitle`, `back`, `bell`, `settings`, `avatar`, `sheet`, `tabbar`) and `previewNativeQuery({ state, theme, platform, page })` (`URLSearchParams`).

- [ ] **Step 1: Confirm the preview commit and read its phone-frame rules**

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/student-home-variants
git status --short web/dev-previews
git log --oneline -5 -- web/dev-previews/student-home-a.html web/dev-previews/student-home
```

Expected: `4447a571` in the log. Uncommitted `M` lines under `web/dev-previews/` are someone else's work in progress: ignore them and read only the committed files. Then list the phone-frame tokens, selectors and JS hooks at that commit:

```bash
git show 4447a571:web/dev-previews/student-home/tokens.css | grep -nE -- "--pf-|data-platform"
git show 4447a571:web/dev-previews/student-home/variant-a.css | sed -n '/Native phone frame/,$p' | grep -nE "as-(bar|lt|title|back|grab|ptr|pop|modal|iconbtn)|a-bottombar|data-sheet|is-(collapsed|raised|press|release|sheet-snapping)|animation-range|font:"
git show 4447a571:web/dev-previews/student-home/variant-a.js | grep -nE "data(set)?\.(platform|page|sheet|ptr)|--pf-|is-collapsed|is-raised|detents"
git show 4447a571:web/dev-previews/student-home-a.html | grep -nE "as-bar|as-lt|as-title|as-back|as-pop-bell|as-pop-me|as-settings|a-bottombar"
```

Check every value in Step 3's block and every selector in Step 4 against this output. Where the commit differs from the pre-filled value, use the commit's value and note it in the commit body.

- [ ] **Step 1b: The preview defaults to `other` (design A's own phone frame), like the app (D1)**

Evidence: a P1 drift run on `4447a571` (`reports/.scratch/drift/2026-11-09T09-32-00-158Z`) failed 9 keys at 23 to 68%: `student-bell@390` (light and dark), `student-account@390` (light and dark), and `student-settings-{profile,account,notifications,appearance,install}@390@light`. Cause: `controller.ts` lists `platform: ["ios", "android"]`, so a URL without `platform` resolves to `ios`. The harness's `openPreview` passes `width=desktop` and no platform, so at a 390px viewport the preview now draws the native frame (with sheets) where the app, running as `other`, keeps design A.

Fix it in the preview, at the source of the default:
- `web/dev-previews/student-home/controller.ts`: `CONTROLS.platform` becomes `["other", "ios", "android"]`, so a missing or unknown `platform` resolves to `other`. In `apply`, `other` **removes** `root.dataset.platform` (`delete root.dataset.platform`) instead of writing it: every phone-frame rule keys off the attribute's presence (`.sh-root[data-platform]`), so `data-platform="other"` would still draw the native frame. Keep the user's view unchanged: when the URL has `width=mobile` and no `platform`, `pick("platform")` returns `ios`, and the controller writes `platform=ios` into the URL (`history.replaceState`), so the toolbar's default choice is an explicit `ios` and the variant links carry it.
- `web/dev-previews/student-home/variant-a.js`: `isPhone()` also requires the attribute (`Boolean(root.dataset.platform) && root.clientWidth <= PHONE_MAX`), so the collapse, sheet, press and pull-to-refresh code never sets `is-collapsed`, `data-sheet`, `is-press` or `data-ptr` on design A.

Verify:

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/student-home-variants/web
npm run build
node scripts/home-drift.mjs --scene teacher-,student-
git diff --stat -- scripts/drift/justifications.json
grep -c '"approved": "yes"' scripts/drift/justifications.json
```

Expected: the drift run exits 0, except keys the run reports as captured (new baselines); the 9 keys above pass again. `justifications.json` is unchanged and still has 48 `"approved": "yes"` entries. Then open the preview with `?platform=ios&page=root&width=mobile` and with `?width=mobile` and no platform: both show the iOS native frame with the toolbar, as before.

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
  // header
  "--native-large-title-size", "--native-large-title-lh", "--native-large-title-pad",
  "--native-inline-title-size", "--native-inline-title-lh",
  "--native-bar-h-ios", "--native-bar-h-android", "--native-bar-pad-inline",
  "--native-title-inset-ios", "--native-title-inset-detail-ios",
  "--native-iconbtn-ios", "--native-iconbtn-android", "--native-bar-icon",
  // tab bar
  "--native-tabbar-h-ios", "--native-tabbar-h-android", "--native-tab-label-ios", "--native-tab-label-android",
  "--native-tab-icon", "--native-tab-pill-w", "--native-tab-pill-h", "--native-tab-press-opacity-ios",
  // sheets
  "--native-grabber-w-ios", "--native-grabber-h-ios", "--native-grabber-gap-ios",
  "--native-grabber-w-android", "--native-grabber-h-android", "--native-grabber-gap-android",
  "--native-sheet-medium", "--native-sheet-large-ios", "--native-sheet-large-android",
  "--native-sheet-scale-back", "--native-sheet-backdrop", "--native-action-row-h",
  "--dur-sheet-ios", "--dur-sheet-android",
  "--ease-ios-spring", "--ease-m3-emphasized", "--ease-m3-emphasized-decelerate",
  // grouped content
  "--native-group-radius-ios", "--native-group-inset-ios", "--native-gutter-android", "--native-sep-inset-ios",
  "--native-row-min-ios", "--native-row-1-android", "--native-row-2-android", "--native-row-3-android",
  // glass
  "--native-glass-mix", "--native-glass-saturate", "--native-hairline",
  // press
  "--native-press-dim", "--native-press-ink-light", "--native-press-ink-dark", "--native-press-scale",
  "--native-state-pressed", "--native-ripple-dur",
  // gestures
  "--native-parallax", "--native-ptr-threshold",
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

The values below are the committed preview's (designer report on `4447a571`, `tokens.css` `--pf-*` and the phone-frame block of `variant-a.css`). Verify each against Step 1's output and cite the preview's line in the trailing comment. Where the preview has no value, the brief's number stays and the comment says `brief §N`.

Colours are not tokens here: the phone frame uses existing roles. The preview's names map to the app's as follows: preview `--md-surface-lowest`/`-low`/`-high` are the app's `--md-surface-container-lowest`/`-low`/`-high`, preview `--md-outline-subtle` is `--md-outline-variant`, and preview `--surface-card` is `--md-surface-container-lowest` in light and `--md-surface-container-high` in dark. The surfaces later tasks use, from the preview:

| Surface | iOS light / dark | Android light / dark |
|---|---|---|
| Page ground | `surface-container` / `surface-container-lowest` | `surface-container-low` / `surface` |
| Groups (cards, list groups) | `surface-container-lowest` / `surface-container-high` | same |
| Sheets | `surface-container-low` (both themes) | same |
| Bar at rest | transparent (the page shows) | transparent (the page shows) |
| Bar raised (collapsed, or a scrolled detail) | glass: 86% `surface-container-lowest` / 86% `surface-container-low`, blur, saturate 1.6, 0.5px `outline-variant` hairline | `surface-container`, no hairline |
| Tab bar | the same glass, hairline on top | `surface-container` |
| Separators / grabber | `outline` / `outline` | none / 40% `on-surface-variant` |

```css
/* ── Native frame tokens (docs/superpowers/plans/2026-11-08-native-mobile-frame.md, Task 0).
   Values from the committed design A preview at 4447a571 (student-home/tokens.css --pf-*,
   variant-a.css "Native phone frame"). Raw values for the native frame live here and nowhere else. */
:root {
  /* Header */
  --native-large-title-size: 34px;          /* .as-lt: 800 34px/41px Bricolage */
  --native-large-title-lh: 41px;
  --native-large-title-pad: 2px 16px 8px;   /* .as-lt padding: 2px var(--space-4) var(--space-2) */
  --native-inline-title-size: 17px;         /* .as-title: 600 17px/22px Schibsted */
  --native-inline-title-lh: 22px;
  --native-bar-h-ios: 44px;                 /* --pf-bar-h */
  --native-bar-h-android: 64px;
  --native-bar-pad-inline: 8px;             /* .as-bar padding-inline: var(--space-2) */
  --native-title-inset-ios: 144px;          /* --pf-title-inset: centred title clears three 44px actions */
  --native-title-inset-detail-ios: 124px;   /* --pf-title-inset-detail: clears the back chevron and label */
  --native-iconbtn-ios: 44px;               /* --pf-iconbtn */
  --native-iconbtn-android: 48px;
  --native-bar-icon: 22px;                  /* .as-bar .as-ico */
  /* Tab bar */
  --native-tabbar-h-ios: 49px;              /* --pf-tab-h, plus the home indicator inset */
  --native-tabbar-h-android: 80px;
  --native-tab-label-ios: 10px;             /* --pf-tab-label */
  --native-tab-label-android: 12px;
  --native-tab-icon: 24px;                  /* --pf-tab-ico, both platforms */
  --native-tab-pill-w: 64px;                /* --pf-pill-w/h: M3 active indicator */
  --native-tab-pill-h: 32px;
  --native-tab-press-opacity-ios: 0.55;     /* iOS tab items dim instead of drawing a layer */
  /* Sheets */
  --native-grabber-w-ios: 36px;             /* --pf-grab-w/h/gap */
  --native-grabber-h-ios: 5px;
  --native-grabber-gap-ios: 5px 6px;        /* above / below */
  --native-grabber-w-android: 32px;
  --native-grabber-h-android: 4px;
  --native-grabber-gap-android: 22px 22px;  /* M3 drag handle centred in a 48dp touch area */
  --native-sheet-medium: 50dvh;             /* --pf-sheet-medium, both platforms */
  --native-sheet-large-ios: calc(100dvh - max(env(safe-area-inset-top), 20px) - 10px);
  --native-sheet-large-android: calc(100dvh - max(env(safe-area-inset-top), 24px) - 24px);
  --native-sheet-scale-back: 0.94;          /* --pf-sheet-scale, iOS only */
  --native-sheet-backdrop: oklch(0.1 0.01 245); /* behind the scaled-back page, both themes */
  --native-action-row-h: 56px;              /* brief §3.3 action sheet rows; no preview value */
  --dur-sheet-ios: 320ms;                   /* --pf-sheet-dur */
  --dur-sheet-android: 300ms;
  --ease-ios-spring: cubic-bezier(0.32, 0.72, 0, 1);              /* --pf-sheet-ease (iOS) */
  --ease-m3-emphasized-decelerate: cubic-bezier(0.05, 0.7, 0.1, 1); /* --pf-sheet-ease (Android) */
  --ease-m3-emphasized: cubic-bezier(0.2, 0, 0, 1);               /* ripple; Android push slides */
  /* Grouped content */
  --native-group-radius-ios: 12px;          /* --pf-group-radius (Android: 0) */
  --native-group-inset-ios: 16px;           /* --pf-group-margin (Android: 0, full-bleed) */
  --native-gutter-android: 14px;            /* the page gutter Android keeps (preview --as-gutter-sm = PortalShell max-shell-lg:px-3.5) */
  --native-sep-inset-ios: 16px;             /* --pf-sep-inset (Android: no separators) */
  --native-row-min-ios: 44px;               /* --pf-row-min */
  --native-row-1-android: 56px;
  --native-row-2-android: 72px;             /* brief §3.4 */
  --native-row-3-android: 88px;             /* brief §3.4 */
  /* Glass (iOS only) */
  --native-glass-mix: 86%;                  /* --pf-glass-mix */
  --native-glass-saturate: 1.6;             /* saturate(1.6) */
  --native-hairline: 0.5px;                 /* --pf-hairline */
  /* Press */
  --native-press-dim: 8%;                   /* --pf-press-layer (iOS) */
  --native-press-ink-light: oklch(0 0 0);   /* --pf-ink-dim: iOS dims toward black in light... */
  --native-press-ink-dark: oklch(1 0 0);    /* ...and toward white in dark */
  --native-press-scale: 0.97;               /* --pf-press-scale, buttons only */
  --native-state-pressed: 10%;              /* --pf-press-layer (Android) */
  --native-ripple-dur: 450ms;               /* --pf-ripple-dur, eased by --ease-m3-emphasized */
  /* Gestures */
  --native-parallax: 0.3;                   /* brief §3.6 */
  --native-ptr-threshold: 64px;             /* --pf-ptr-threshold, both platforms */
}
```

Values that are not tokens because they are behaviour, not measurements: the collapse fades the inline title and the bar's surface over 70% to 100% of the large title's exit, and the large title's own opacity over its whole exit (Task 4); the hero height is unchanged.

Run: `cd web && npx vitest run tests/unit/nativeFrameCss.test.ts tests/unit/design-tokens.test.ts tests/unit/motionDefaults.test.ts`
Expected: PASS. If `design-tokens.test.ts` rejects a raw value (for example an off-scale px), add the token to that test's documented allow-list with a one-line reason pointing at this block. Do not move the value into a component.

- [ ] **Step 4: Record the preview selectors (`web/scripts/drift/native-preview.mjs`)**

The keys are fixed, because later tasks import them. The selectors are pre-filled from the designer's hooks; confirm each one matches exactly one element (or the stated set) in the committed markup at `4447a571`.

```js
/*
 * The design A preview's native phone frame (student-home-a.html with
 * ?platform=ios|android&page=root|detail), as committed at 4447a571.
 * Selectors are read off the committed markup; update them here, nowhere else.
 * State hooks the scenes may wait on: `.as-bar.is-collapsed` (root, scrolled past
 * the large title), `.as-bar.is-raised` (bar surface shown), and
 * `.sh-root[data-sheet="medium|large|fit"]` (a phone sheet is open).
 */
export const NATIVE_PREVIEW = {
  root: ".sh-root",
  bar: ".as-bar",
  largeTitle: ".as-lt",
  inlineTitle: ".as-title",
  back: ".as-back",
  bell: ".as-pop-bell > summary",
  settings: '[data-a-open="as-settings"]',
  avatar: ".as-pop-me > summary",
  sheet: ".as-pop[open] > .as-pop-panel, .as-modal[open]",
  tabbar: ".a-bottombar",
}

/** `width: "desktop"` on purpose: at a 390px viewport the shell container is
 * 390px, so the phone frame applies; `width=mobile` would add the preview
 * toolbar above the frame and into the capture. */
export function previewNativeQuery({ state, theme, platform, page }) {
  return new URLSearchParams({ state, theme, motion: "reduce", width: "desktop", platform, page })
}
```

Verify each selector against the committed preview at 390×844, for both platforms and both pages (a throwaway script under `reports/.scratch/`, not committed): `root`, `bar`, `largeTitle` (root page), `inlineTitle`, `back` (detail page), `bell`, `settings`, `avatar` and `tabbar` each match exactly one visible element; after clicking `bell`, `sheet` matches one visible element and `root` has `data-sheet="fit"`; after clicking `settings`, `root` has `data-sheet="medium"`. Any selector that fails is corrected here from the markup, and the correction is named in the commit body.

- [ ] **Step 5: Commit**

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/student-home-variants
FILES="web/src/index.css web/scripts/drift/native-preview.mjs web/tests/unit/nativeFrameCss.test.ts web/dev-previews/student-home/controller.ts web/dev-previews/student-home/variant-a.js"
/home/sico/Code/Lemely/.venv/bin/pre-commit run --files $FILES
SKIP=import-linter git commit -S -m "feat(web): native frame tokens from the design A phone preview; preview defaults to other" -- $FILES
```

Step 1b may be committed on its own first (`fix(web): design A preview defaults to the other platform`), so the P1 drift is green again before the token work; if so, drop the two preview paths from `FILES` here.

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

`openPreview` takes `platform`. When `platform` is set, it builds its query with `previewNativeQuery({ state: preview.state, theme, platform, page: preview.page ?? "root" })` (import from `./native-preview.mjs`), so every native scene passes `platform` explicitly. Otherwise it uses today's query unchanged, with no `platform` param, which the preview resolves to `other` (Task 0 Step 1b). After loading a native preview, assert the frame is on: `document.querySelector(".sh-root").dataset.platform === platform`, and throw otherwise, the same way `openApp` asserts the app's resolver.

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
/** The app's iOS back label on DETAIL_PATH: the parent crumb's label (Task 4
 * NativeBack); confirmed in Step 2. The preview's `.as-back-l` reads "Overview". */
const DETAIL_BACK_LABEL = "Overview"

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
  await page.waitForSelector(`${NATIVE_PREVIEW.bar}.is-collapsed`)
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
      // The preview's detail title and back label are fixed; make them read what the app's route says.
      act: (page) => page.evaluate(([title, titleText, backLabel, backText]) => {
        for (const el of document.querySelectorAll(title)) el.textContent = titleText
        for (const el of document.querySelectorAll(backLabel)) el.textContent = backText
      }, [NATIVE_PREVIEW.inlineTitle, DETAIL_TITLE, `${NATIVE_PREVIEW.back} .as-back-l`, DETAIL_BACK_LABEL]),
    },
  })),
  ...perPlatform((platform) => ({
    id: `native-${platform}-bell`, kind: "preview-vs-app", capture: "frame", platform, windows: [390],
    app: app({ act: (page) => openAppSheet(page, /^Notifications/) }),
    preview: {
      state: "populated",
      page: "root",
      act: async (page) => {
        await page.click(NATIVE_PREVIEW.bell)
        await page.waitForSelector(`${NATIVE_PREVIEW.root}[data-sheet="fit"]`)
      },
    },
  })),
  ...perPlatform((platform) => ({
    // The preview's settings sheet opens at the medium detent (data-detents="medium large").
    id: `native-${platform}-settings`, kind: "preview-vs-app", capture: "frame", platform, windows: [390],
    app: app({ path: "/student/settings" }),
    preview: {
      state: "populated",
      page: "root",
      act: async (page) => {
        await page.click(NATIVE_PREVIEW.settings)
        await page.waitForSelector(`${NATIVE_PREVIEW.root}[data-sheet="medium"]`)
      },
    },
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

Before running, check the detail title and back label. Open `/student/practice/0606` in the app at 390 and read the bar's `[data-shell-title]`, and the label of the trail's second-to-last crumb (the `topBar.trail` the student shell builds for that route). Set `DETAIL_TITLE` and `DETAIL_BACK_LABEL` to those. The preview is made to match the app's route, never the other way round.

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
FILES="web/index.html web/src/index.css web/tests/unit/nativeMechanics.test.ts web/tests/unit/checkNativeInvariants.test.ts web/scripts/check-native-invariants.mjs"
# Append each root Step 4 changed (FILES="$FILES <that path>"), one per file it lists in the commit body.
/home/sico/Code/Lemely/.venv/bin/pre-commit run --files $FILES
SKIP=import-linter git commit -S -m "feat(web): black-translucent status bar, text-size-adjust and touch chrome rules" -- $FILES
```

---

### Task 4: Sticky collapsing large-title header (ShellTopBar native variant)

**Page title API (decided here, D2/D3):** `ShellTopBarProps.title` stays the single title string. The level is `titleLevel ?? titleLevelFor(trail)`, where `titleLevelFor(trail) = trail.length > 1 ? "detail" : "root"`. New required prop: `backFallback: string`, the portal root that the native back chevron falls back to. On native:
- `root`: the bar row holds only the actions. A large title, `<p aria-hidden data-shell-large-title>`, sits under the bar, outside `<main>`. The inline `[data-shell-title]` and the bar's surface fade in over the last 30% of the large title's exit (70% to 100%), the large title fades out over its whole exit, and `data-collapsed` flips at the one threshold: the large title's bottom crossing the bar.
- `detail`: no large title. The bar is back, title, one action (the bell): a leading native back control (iOS chevron plus the parent page's title, Android arrow), the inline title from the start, and the settings and account actions hidden. The breadcrumb row is hidden.

**Files:**
- Create: `web/src/components/shell/largeTitle.ts`, `web/src/components/shell/useLargeTitleCollapse.ts`, `web/src/components/shell/NativeBack.tsx`, `web/tests/unit/nativeTopBar.test.ts`
- Modify: `web/src/components/shell/ShellTopBar.tsx`, `web/src/components/shell/shellStyles.ts` (`lm-native-iconbtn` on `SHELL_ICON_BUTTON`), `web/src/components/ui/back-control.tsx` (extract `useBackAction`), `web/src/index.css` (native bar block), `web/src/portals/student/shell.tsx` (`backFallback`, `native:hidden` on the in-actions `BackControl`), `web/src/portals/teacher/index.tsx` (`backFallback`), `web/scripts/drift/checks-native.mjs`, `web/scripts/drift/justifications.json`

**Interfaces:**
- Consumes: `useNativeFrame` (Task 1), the tokens (Task 0), `BackControl` (`@/components/ui/back-control`, props `fallback`, `label`, `className`), `Crumb` (`@/components/ui/breadcrumbs`).
- Produces:
  - `titleLevelFor(trail: readonly unknown[]): "root" | "detail"`
  - `largeTitleCollapsed(scrollY: number, titleHeight: number): boolean`
  - `useLargeTitleCollapse(ref: RefObject<HTMLElement | null>, enabled: boolean): boolean`
  - `useBackAction(fallback: string): () => void` (exported from `back-control.tsx`; `BackControl` and `NativeBack` both call it, so the history-or-fallback logic exists once)
  - `NativeBack({ fallback, label }: { fallback: string; label: string })`
  - `ShellTopBarProps` gains `titleLevel?: "root" | "detail"` and `backFallback: string`.
  - DOM contract: `header[data-title-level][data-collapsed]`, `[data-shell-large-title]`, `[data-shell-action="settings"|"account"]`, and CSS classes `.lm-native-bar`, `.lm-native-large-title`, `.lm-native-inline-title`, `.lm-native-back`, `.lm-native-iconbtn`.

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
  it("marks the bar and renders an aria-hidden large title outside main (D3)", () => {
    expect(bar).toContain("lm-native-bar")
    expect(bar).toContain("data-title-level={level}")
    expect(bar).toContain("data-collapsed={collapsed}")
    expect(bar).toMatch(/<p[^>]*aria-hidden="true"[^>]*data-shell-large-title/)
  })
  it("renders the native back only for details, from backFallback and the parent crumb", () => {
    expect(bar).toMatch(/level === "detail" \? \(\s*<NativeBack fallback=\{backFallback\} label=\{backLabel\}/)
  })
  it("marks the settings and account actions so details can hide them", () => {
    expect(bar).toContain('data-shell-action="settings"')
    expect(bar).toContain('data-shell-action="account"')
  })
  it("one back logic: BackControl and NativeBack share useBackAction", () => {
    const back = readFileSync(join(SRC, "components/ui/back-control.tsx"), "utf8")
    const native = readFileSync(join(SRC, "components/shell/NativeBack.tsx"), "utf8")
    expect(back).toMatch(/export function useBackAction\(fallback: string\)/)
    expect(back).toContain("useBackAction(fallback)")
    expect(native).toContain("useBackAction(fallback)")
    expect(native).not.toContain("backTarget(")
  })
})

describe("native bar CSS (preview 4447a571)", () => {
  const block = css.slice(css.indexOf("/* ── Native frame: top bar"))
  it("is sticky under the status bar, phone width and ios|android only", () => {
    expect(block).toMatch(/@media \(max-width: 720px\)/)
    expect(block).toMatch(/:root:is\(\[data-platform="ios"\], \[data-platform="android"\]\) \.lm-native-bar \{[^}]*position: sticky;[^}]*top: 0;[^}]*padding-top: env\(safe-area-inset-top\);/)
  })
  it("the bar's surface is a layer under its content, transparent at rest", () => {
    expect(block).toMatch(/\.lm-native-bar::before \{[^}]*z-index: -1;[^}]*opacity: 0;/)
    expect(block).toMatch(/\.lm-native-bar:is\(\[data-collapsed="true"\], \[data-title-level="detail"\]\[data-stuck="true"\]\)::before \{[^}]*opacity: 1;/)
  })
  it("iOS raises to glass with a hairline; Android to surface-container", () => {
    expect(block).toMatch(/\[data-platform="ios"\] \.lm-native-bar::before \{[^}]*background: color-mix\(in oklch, var\(--md-surface-container-lowest\) var\(--native-glass-mix\), transparent\);[^}]*backdrop-filter: blur\(var\(--blur-nav\)\) saturate\(var\(--native-glass-saturate\)\);[^}]*border-block-end: var\(--native-hairline\) solid var\(--md-outline-variant\)/)
    expect(block).toMatch(/\[data-theme="dark"\]\[data-platform="ios"\] \.lm-native-bar::before \{[^}]*var\(--md-surface-container-low\) var\(--native-glass-mix\)/)
    expect(block).toMatch(/\[data-platform="android"\] \.lm-native-bar::before \{[^}]*background: var\(--md-surface-container\)/)
  })
  it("inline title: 17/22 Schibsted 600; iOS centred between the 144px (root) and 124px (detail) insets", () => {
    expect(block).toMatch(/\[data-platform="ios"\] \.lm-native-inline-title \{[^}]*inset-inline: var\(--native-title-inset-ios\)/)
    expect(block).toMatch(/\[data-platform="ios"\] \.lm-native-bar\[data-title-level="detail"\] \.lm-native-inline-title \{[^}]*inset-inline: var\(--native-title-inset-detail-ios\)/)
  })
  it("details show back, title and one action", () => {
    expect(block).toMatch(/\.lm-native-bar\[data-title-level="detail"\] :is\(\[data-shell-action="settings"\], \[data-shell-action="account"\]\) \{[^}]*display: none/)
  })
  it("scroll-driven fades only where supported and motion is allowed: 70-100% for the bar, the whole exit for the large title", () => {
    expect(block).toMatch(/@supports \(animation-timeline: scroll\(\)\)\s*\{\s*@media \(prefers-reduced-motion: no-preference\) and \(max-width: 720px\)/)
    expect(block).toContain("animation-timeline: scroll(root block)")
    expect(block).toContain("animation-range: calc(var(--lm-large-title-block) * 0.7) var(--lm-large-title-block)")
    expect(block).toContain("animation-range: 0px var(--lm-large-title-block)")
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

- [ ] **Step 4: `useBackAction`, `NativeBack` and `ShellTopBar.tsx`**

In `back-control.tsx`, move `BackControl`'s `handleClick` body (the `backTarget` history-or-fallback decision, comments included) into an exported hook, and make `BackControl` call it. Its rendered markup does not change:

```tsx
/** The history-or-fallback back action, shared by BackControl and the native bar's NativeBack. */
export function useBackAction(fallback: string): () => void {
  const navigate = useNavigate()
  return () => {
    const target = backTarget(window.history.state?.idx, fallback)
    if (target.kind === "history") navigate(-1) // (keep the existing comment on why no viewTransition here)
    else navigate(target.to, { replace: true, viewTransition: true })
  }
}
```

and in `BackControl`: `const handleClick = useBackAction(fallback)`.

`web/src/components/shell/NativeBack.tsx`, the preview's `.as-back` (an iOS chevron plus the parent page's title, a Material arrow on Android; both glyphs render and CSS shows one):

```tsx
import { ArrowLeft, CaretLeft } from "@phosphor-icons/react"
import { useBackAction } from "@/components/ui/back-control"

/** Native frame Task 4: the detail bar's leading back control (preview `.as-back`). */
export function NativeBack({ fallback, label }: { fallback: string; label: string }) {
  const back = useBackAction(fallback)
  return (
    <button type="button" onClick={back} aria-label={`Back to ${label}`} className="lm-native-back lm-native-iconbtn hidden native:flex">
      <CaretLeft className="lm-native-back-ios" aria-hidden="true" />
      <ArrowLeft className="lm-native-back-md" aria-hidden="true" />
      <span className="lm-native-back-label" aria-hidden="true">{label}</span>
    </button>
  )
}
```

`shellStyles.ts`: append `lm-native-iconbtn` to `SHELL_ICON_BUTTON` (it does nothing outside the native block).

In `ShellTopBar.tsx`, add `useRef`, `NativeBack`, `useNativeFrame`, `titleLevelFor` and `useLargeTitleCollapse` imports. Extend the props:

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
  /** iOS shows the parent page's title beside the chevron (preview `.as-back-l`). */
  const backLabel = trail.at(-2)?.label ?? title
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
          <NativeBack fallback={backFallback} label={backLabel} />
        ) : null}
        {/* menu button unchanged */}
        <p data-shell-title className="me-auto min-w-0 truncate text-title-bar text-on-surface lm-native-inline-title">
          {title}
        </p>
        {/* actions and bell unchanged; wrap the gear in <span data-shell-action="settings" className="contents">
            and the avatar panel in <span data-shell-action="account" className="contents"> */}
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

The large title has `hidden` by default and is shown only by the native CSS for `root`. A `hidden` element measures 0, so the hook's `largeTitleCollapsed` returns false for it. If `Crumb.label` is not a string, render `backLabel` with the same text the breadcrumb shows for that crumb.

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
  :root:is([data-platform="ios"], [data-platform="android"]) .lm-native-bar {
    isolation: isolate;
    background-color: transparent; /* the page ground shows until the surface layer fades in */
  }
  /* The bar's surface is a layer under its content (preview .as-bar::before), so it
     fades without fading the icons. */
  :root:is([data-platform="ios"], [data-platform="android"]) .lm-native-bar::before {
    content: "";
    position: absolute;
    inset: 0;
    z-index: -1;
    pointer-events: none;
    opacity: 0;
    transition: opacity var(--dur-base) var(--ease-out-soft);
  }
  :root:is([data-platform="ios"], [data-platform="android"]) .lm-native-bar:is([data-collapsed="true"], [data-title-level="detail"][data-stuck="true"])::before {
    opacity: 1;
  }
  /* iOS: glass with a hairline. Android: M3 lift-on-scroll, no shadow, no hairline. */
  :root[data-platform="ios"] .lm-native-bar::before {
    background: color-mix(in oklch, var(--md-surface-container-lowest) var(--native-glass-mix), transparent);
    -webkit-backdrop-filter: blur(var(--blur-nav)) saturate(var(--native-glass-saturate));
    backdrop-filter: blur(var(--blur-nav)) saturate(var(--native-glass-saturate));
    border-block-end: var(--native-hairline) solid var(--md-outline-variant);
  }
  :root[data-theme="dark"][data-platform="ios"] .lm-native-bar::before {
    background: color-mix(in oklch, var(--md-surface-container-low) var(--native-glass-mix), transparent);
  }
  :root[data-platform="android"] .lm-native-bar::before {
    background: var(--md-surface-container);
  }
  /* Actions: 44px (iOS) / 48px (Android) targets with 22px glyphs; iOS tints them primary,
     Android keeps on-surface-variant. Root and detail both put the actions at the end. */
  :root[data-platform="ios"] .lm-native-bar { --native-iconbtn: var(--native-iconbtn-ios); justify-content: flex-end; }
  :root[data-platform="android"] .lm-native-bar { --native-iconbtn: var(--native-iconbtn-android); }
  :root:is([data-platform="ios"], [data-platform="android"]) .lm-native-bar .lm-native-iconbtn {
    inline-size: var(--native-iconbtn);
    block-size: var(--native-iconbtn);
    border-radius: 9999px;
  }
  :root:is([data-platform="ios"], [data-platform="android"]) .lm-native-bar .lm-native-iconbtn svg {
    inline-size: var(--native-bar-icon);
    block-size: var(--native-bar-icon);
  }
  :root[data-platform="ios"] .lm-native-bar .lm-native-iconbtn { color: var(--md-primary); }
  :root[data-platform="android"] .lm-native-bar .lm-native-iconbtn { color: var(--md-on-surface-variant); }
  /* Detail: back, title, one action. */
  :root:is([data-platform="ios"], [data-platform="android"]) .lm-native-bar[data-title-level="detail"] :is([data-shell-action="settings"], [data-shell-action="account"]) {
    display: none;
  }
  :root:is([data-platform="ios"], [data-platform="android"]) .lm-native-back { margin-inline-end: auto; }
  :root[data-platform="ios"] .lm-native-back {
    inline-size: auto;
    padding-inline-end: var(--space-2);
    font-size: var(--native-inline-title-size);
    line-height: var(--native-inline-title-lh);
  }
  :root[data-platform="ios"] .lm-native-back-md,
  :root[data-platform="android"] :is(.lm-native-back-ios, .lm-native-back-label) { display: none; }
  :root[data-platform="android"] .lm-native-back { color: var(--md-on-surface); }
  :root:is([data-platform="ios"], [data-platform="android"]) .lm-native-back svg:dir(rtl) { transform: scaleX(-1); }
  /* Inline title. */
  :root:is([data-platform="ios"], [data-platform="android"]) .lm-native-inline-title {
    font-size: var(--native-inline-title-size);
    line-height: var(--native-inline-title-lh);
    font-weight: 600;
    letter-spacing: -0.01em;
    color: var(--md-on-surface);
    transition: opacity var(--dur-fast) var(--ease-out-soft);
  }
  :root:is([data-platform="ios"], [data-platform="android"]) .lm-native-bar[data-title-level="root"]:not([data-collapsed="true"]) .lm-native-inline-title {
    opacity: 0;
  }
  /* iOS: centred over the bar, clear of three actions (root) or the back label (detail). */
  :root[data-platform="ios"] .lm-native-inline-title {
    position: absolute;
    inset-inline: var(--native-title-inset-ios);
    inset-block-end: 0;
    block-size: var(--native-bar-h);
    line-height: var(--native-bar-h);
    text-align: center;
  }
  :root[data-platform="ios"] .lm-native-bar[data-title-level="detail"] .lm-native-inline-title {
    inset-inline: var(--native-title-inset-detail-ios);
  }
  /* Android: start-aligned in the row. */
  :root[data-platform="android"] .lm-native-inline-title {
    flex: 1;
    margin-inline: var(--space-3) var(--space-2);
  }
  /* Large title. */
  :root:is([data-platform="ios"], [data-platform="android"]) .lm-native-large-title {
    margin: 0;
    padding: var(--native-large-title-pad);
    font-family: var(--font-display);
    font-weight: 800;
    font-size: var(--native-large-title-size);
    line-height: var(--native-large-title-lh);
    letter-spacing: -0.03em;
    color: var(--md-on-surface);
    text-wrap: balance;
    overflow-wrap: anywhere;
    /* Long titles ("0625 Physics · Paper 4 · May/June 2024") wrap to 2 lines. */
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    transition: opacity var(--dur-fast) var(--ease-out-soft);
  }
  :root:is([data-platform="ios"], [data-platform="android"]) .lm-native-bar[data-collapsed="true"] + .lm-native-large-title {
    opacity: 0;
  }
  :root:is([data-platform="ios"], [data-platform="android"]) .lm-native-bar[data-title-level="detail"] + .lm-native-large-title {
    display: none;
  }
}
/* Collapse, scroll-driven where supported (Chrome 115+, Safari 26+), as in the preview:
   the inline title and the bar's surface fade in over 70% to 100% of the large title's
   exit, and the large title fades out over its whole exit. Elsewhere, and under reduced
   motion, data-collapsed flips the same end state at the same threshold. */
@supports (animation-timeline: scroll()) {
  @media (prefers-reduced-motion: no-preference) and (max-width: 720px) {
    @keyframes lm-native-fade-in { from { opacity: 0; } to { opacity: 1; } }
    @keyframes lm-native-fade-out { from { opacity: 1; } to { opacity: 0; } }
    :root:is([data-platform="ios"], [data-platform="android"]) .lm-native-bar[data-title-level="root"] :is(.lm-native-inline-title),
    :root:is([data-platform="ios"], [data-platform="android"]) .lm-native-bar[data-title-level="root"]::before {
      animation: lm-native-fade-in linear both;
      animation-timeline: scroll(root block);
      animation-range: calc(var(--lm-large-title-block) * 0.7) var(--lm-large-title-block);
    }
    :root:is([data-platform="ios"], [data-platform="android"]) .lm-native-bar[data-title-level="root"] + .lm-native-large-title {
      animation: lm-native-fade-out linear both;
      animation-timeline: scroll(root block);
      animation-range: 0px var(--lm-large-title-block);
    }
  }
}
```

The surfaces are the preview's (Task 0's surface table). The glass blur stays `var(--blur-nav)` (10px) under the one-blur rule; the preview's 14px is an open question. The inline-title, bar-surface and large-title `opacity` rules are overridden by the animations' `both` fill where scroll timelines exist. Elsewhere `data-collapsed` toggles them with a short transition, which `motionDefaults` already strips under reduced motion.

- [ ] **Step 6: Portals pass `backFallback`**

- `student/shell.tsx`: add `backFallback: "/student"` to `topBar`, and add `native:hidden` to the existing `BackControl`'s `className` (`"shell-lg:hidden native:hidden"`).
- `teacher/index.tsx`: add `backFallback: "/teacher"`.

Update `studentShell.test.ts` only where it pins the `BackControl` class string.

Run: `cd web && npx vitest run tests/unit/nativeTopBar.test.ts tests/unit/studentShell.test.ts tests/unit/shellTopBarGlass.test.ts tests/unit/shellPanels.test.ts tests/unit/nativeMechanics.test.ts tests/unit/elevationScale.test.ts tests/unit/utilityExistence.test.ts tests/unit/rtlSafety.test.ts tests/unit/a11yRules.test.ts`
Expected: PASS. If `rtlSafety` rejects the `inset-inline`, `padding-inline` or `text-align: center` rules, those are logical already; fix anything physical it names. If `shellPanels.test.ts` pins `SHELL_ICON_BUTTON`'s exact string, add `lm-native-iconbtn` to the pinned string and add that test file to Step 9's `FILES`.

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
      const label = page.locator("header .lm-native-back-label")
      if ((await label.isVisible()) !== (platform === "ios")) throw new Error("the back label shows on iOS only")
      for (const action of ["settings", "account"]) {
        if (await page.locator(`header [data-shell-action="${action}"] :is(a, button)`).first().isVisible()) throw new Error(`detail shows the ${action} action`)
      }
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
FILES="web/src/components/shell/largeTitle.ts web/src/components/shell/useLargeTitleCollapse.ts web/src/components/shell/NativeBack.tsx web/src/components/shell/ShellTopBar.tsx web/src/components/shell/shellStyles.ts web/src/components/ui/back-control.tsx web/src/index.css web/src/portals/student/shell.tsx web/src/portals/teacher/index.tsx web/tests/unit/nativeTopBar.test.ts web/tests/unit/studentShell.test.ts web/scripts/drift/checks-native.mjs web/scripts/drift/justifications.json"
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
  it("main clears the native tab bar through one per-platform height", () => {
    expect(shell).toContain("lm-native-main")
    expect(shell).toContain("data-immersive={immersive || undefined}")
  })
})

describe("tab bar CSS (preview 4447a571)", () => {
  const block = css.slice(css.indexOf("/* ── Native frame: tab bar"))
  it("one --native-tabbar-h per platform, which main's padding reads", () => {
    expect(block).toMatch(/:root\[data-platform="ios"\] \{[^}]*--native-tabbar-h: var\(--native-tabbar-h-ios\)/)
    expect(block).toMatch(/:root\[data-platform="android"\] \{[^}]*--native-tabbar-h: var\(--native-tabbar-h-android\)/)
    expect(block).toMatch(/\.lm-native-main:not\(\[data-immersive\]\) \{[^}]*padding-bottom: calc\(var\(--native-tabbar-h\) \+ env\(safe-area-inset-bottom\)\)/)
  })
  it("iOS: 49px + home indicator, glass, 10px labels", () => {
    expect(block).toMatch(/\[data-platform="ios"\] \.lm-native-tabbar \{[^}]*min-height: calc\(var\(--native-tabbar-h-ios\) \+ env\(safe-area-inset-bottom\)\)/)
    expect(block).toMatch(/\[data-platform="ios"\] \.lm-native-tabbar \{[^}]*backdrop-filter: blur\(var\(--blur-nav\)\) saturate\(var\(--native-glass-saturate\)\)/)
    expect(block).toMatch(/\[data-theme="dark"\]\[data-platform="ios"\] \.lm-native-tabbar \{[^}]*var\(--md-surface-container-low\) var\(--native-glass-mix\)/)
    expect(block).toMatch(/\[data-platform="ios"\] \.lm-native-tabbar \.lm-native-tab-label \{[^}]*font-size: var\(--native-tab-label-ios\)/)
  })
  it("Android: 80dp, 12px labels, a 64x32 secondary-container pill behind the active icon", () => {
    expect(block).toMatch(/\[data-platform="android"\] \.lm-native-tabbar \{[^}]*min-height: calc\(var\(--native-tabbar-h-android\) \+ env\(safe-area-inset-bottom\)\)/)
    expect(block).toMatch(/\[data-platform="android"\] \.lm-native-tabbar \.lm-native-tab-label \{[^}]*font-size: var\(--native-tab-label-android\)/)
    expect(block).toMatch(/\[data-platform="android"\] \.lm-native-tabbar \[aria-current="page"\] \.lm-native-tab-icon::before \{[^}]*inline-size: var\(--native-tab-pill-w\);[^}]*block-size: var\(--native-tab-pill-h\);[^}]*background: var\(--md-secondary-container\)/)
  })
  it("24px icons on both platforms", () => {
    expect(block).toMatch(/\.lm-native-tabbar \.lm-native-tab-icon svg \{[^}]*inline-size: var\(--native-tab-icon\);[^}]*block-size: var\(--native-tab-icon\)/)
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
/* ── Native frame: tab bar (native frame Task 5; preview .a-bottombar). */
@media (max-width: 720px) {
  :root[data-platform="ios"] { --native-tabbar-h: var(--native-tabbar-h-ios); }
  :root[data-platform="android"] { --native-tabbar-h: var(--native-tabbar-h-android); }
  :root:is([data-platform="ios"], [data-platform="android"]) .lm-native-main:not([data-immersive]) {
    padding-bottom: calc(var(--native-tabbar-h) + env(safe-area-inset-bottom));
  }
  :root:is([data-platform="ios"], [data-platform="android"]) .lm-native-main[data-immersive] {
    padding-bottom: env(safe-area-inset-bottom);
  }
  :root:is([data-platform="ios"], [data-platform="android"]) .lm-native-tabbar .lm-native-tab-icon svg {
    inline-size: var(--native-tab-icon);
    block-size: var(--native-tab-icon);
  }
  :root[data-platform="ios"] .lm-native-tabbar {
    min-height: calc(var(--native-tabbar-h-ios) + env(safe-area-inset-bottom));
    border-top: var(--native-hairline) solid var(--md-outline-variant);
    background-color: color-mix(in oklch, var(--md-surface-container-lowest) var(--native-glass-mix), transparent);
    -webkit-backdrop-filter: blur(var(--blur-nav)) saturate(var(--native-glass-saturate));
    backdrop-filter: blur(var(--blur-nav)) saturate(var(--native-glass-saturate));
  }
  :root[data-theme="dark"][data-platform="ios"] .lm-native-tabbar {
    background-color: color-mix(in oklch, var(--md-surface-container-low) var(--native-glass-mix), transparent);
  }
  :root[data-platform="ios"] .lm-native-tabbar .lm-native-tab-label {
    font-size: var(--native-tab-label-ios);
  }
  :root[data-platform="ios"] .lm-native-tabbar [aria-current="page"] {
    color: var(--md-primary);
    font-weight: 600;
  }
  :root[data-platform="android"] .lm-native-tabbar {
    min-height: calc(var(--native-tabbar-h-android) + env(safe-area-inset-bottom));
    border-top: 0;
    background-color: var(--md-surface-container);
  }
  :root[data-platform="android"] .lm-native-tabbar .lm-native-tab-label {
    font-size: var(--native-tab-label-android);
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
  /* Selected: the label stays on-surface (bold); only the icon takes on-secondary-container. */
  :root[data-platform="android"] .lm-native-tabbar [aria-current="page"] {
    color: var(--md-on-surface);
    font-weight: 700;
  }
  :root[data-platform="android"] .lm-native-tabbar [aria-current="page"] .lm-native-tab-icon {
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

Pass `onActiveTap` to `BottomNav`, and give it `className={cn("sidebar:hidden", immersive && "native:hidden")}`. Add the imports `cn` (`@/lib/utils`), `useMatches` and `useNavigate` (`react-router-dom`) and `activeTabTap` (`./tabTap`). On `<main>`, add the class `lm-native-main` and `data-immersive={immersive || undefined}`. The unlayered native rule above then pads it by the platform's tab bar height (so content clears the taller native bar) and drops that padding on immersive routes. It is a class, not a `native:pb-[…]` utility, because a variant utility and the existing `max-sidebar:pb-bottom-nav` have the same specificity and their order in the build is not something to rely on.

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

### Task 5b: One page heading on phones: `PageHeading` and the heading sweep (D11)

On the native frame the shell's large title replaces a screen's own heading when that heading repeats the page title. The screen's `h1` stays the page's one heading for assistive technology, and stays visible on desktop and tablet. This runs right after Task 5, so the native root and detail drift keys never carry a "duplicate heading" difference.

**Files:**
- Create: `web/src/components/ui/page-heading.tsx`, `web/tests/unit/pageHeading.test.ts`
- Modify: every student and teacher screen with a top `h1` (list them in Step 1; 51 files under `web/src/portals/student` and `web/src/portals/teacher` contain `<h1` at `4447a571`), `web/scripts/drift/checks-native.mjs`

**Interfaces:**
- Produces: `PageHeading(props: HTMLAttributes<HTMLHeadingElement> & { repeatsTitle: boolean })`. It renders `<h1 data-page-heading={repeatsTitle ? "title" : "own"}>`, and adds `native:sr-only` when `repeatsTitle`. The prop is required, so every heading states whether it repeats the shell title.
- Rule: no raw `<h1` in `web/src/portals/{student,teacher}/**/*.tsx`, except an always-hidden `<h1 className="sr-only">` (the existing pattern for screens whose visible heading lives elsewhere).

**Accessibility contract (D3 + D11):** on every page, exactly one `h1` is in the accessibility tree: the screen's own, inside `<main>`. The large title is `aria-hidden` (Task 4) and the bar's inline title is plain text. `native:sr-only` hides the repeating heading visually only, so heading navigation and the page's name for screen readers are unchanged on phones.

**What "repeats the title" means:** the heading names the same page as the shell title. Decide per heading while migrating. As a mechanical floor, the behaviour check treats two texts as repeating when they are equal after lowercasing, collapsing whitespace, and dropping a leading "your " or "my " ("Your classes" repeats "Classes"). A heading that says something else ("Hi, Mariam", a paper's full name under a "Practice" title) passes `repeatsTitle={false}` and stays visible.

- [ ] **Step 1: Inventory**

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/student-home-variants/web
grep -rn "<h1" src/portals/student src/portals/teacher --include='*.tsx'
```

For each hit, note the screen, its route's shell title (`studentPageTitle` / the teacher route `handle.title`), the heading's text, and your `repeatsTitle` call. Comment-only hits and `<h1 className="sr-only">` stay as they are. Put the table in the commit body.

- [ ] **Step 2: Failing tests (`web/tests/unit/pageHeading.test.ts`)**

```ts
import { readdirSync, readFileSync, statSync } from "node:fs"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import { PageHeading } from "@/components/ui/page-heading"

const SRC = join(fileURLToPath(new URL("../../", import.meta.url)), "src")

describe("PageHeading (D11)", () => {
  it("a repeating heading is visually hidden on the native frame only, and stays an h1", () => {
    const out = renderToStaticMarkup(createElement(PageHeading, { repeatsTitle: true, className: "text-display-md" }, "Classes"))
    expect(out).toMatch(/^<h1 data-page-heading="title" class="[^"]*\bnative:sr-only\b[^"]*">Classes<\/h1>$/)
    expect(out).toContain("text-display-md")
  })
  it("a heading that says something else stays visible everywhere", () => {
    const out = renderToStaticMarkup(createElement(PageHeading, { repeatsTitle: false }, "Hi, Mariam"))
    expect(out).toMatch(/^<h1 data-page-heading="own"/)
    expect(out).not.toContain("sr-only")
  })
})

describe("no screen bypasses PageHeading", () => {
  const walk = (dir: string): string[] =>
    readdirSync(dir).flatMap((f) => {
      const p = join(dir, f)
      return statSync(p).isDirectory() ? walk(p) : p.endsWith(".tsx") ? [p] : []
    })
  it("student and teacher screens render no raw <h1> except an always-hidden one", () => {
    const offenders: string[] = []
    for (const file of [...walk(join(SRC, "portals/student")), ...walk(join(SRC, "portals/teacher"))]) {
      for (const [i, line] of readFileSync(file, "utf8").split("\n").entries()) {
        const code = line.replace(/\/\/.*$/, "").replace(/\/\*.*?\*\//g, "")
        if (/^\s*\*/.test(line)) continue // block comment body
        if (/<h1\b/.test(code) && !/<h1 className="sr-only">/.test(code)) offenders.push(`${file.slice(SRC.length + 1)}:${i + 1}`)
      }
    }
    expect(offenders).toEqual([])
  })
})
```

Run: `cd web && npx vitest run tests/unit/pageHeading.test.ts`
Expected: FAIL (module missing; the scan lists every raw `<h1>`). Keep the scan's offender list: it is the migration worklist.

- [ ] **Step 3: `page-heading.tsx`**

```tsx
import type { HTMLAttributes } from "react"
import { cn } from "@/lib/utils"

/*
 * Every student and teacher screen's top heading (native frame D11). On the native
 * frame the shell's large title already shows the page title, so a heading that
 * repeats it is visually hidden there (`native:sr-only`) and stays the page's one
 * h1 for assistive technology; the large title itself is aria-hidden. Desktop,
 * tablet and `other` see the heading as before. `repeatsTitle` is required: say
 * whether this heading names the same page as the shell title.
 */
export function PageHeading({ repeatsTitle, className, ...props }: HTMLAttributes<HTMLHeadingElement> & { repeatsTitle: boolean }) {
  return <h1 data-page-heading={repeatsTitle ? "title" : "own"} className={cn(className, repeatsTitle && "native:sr-only")} {...props} />
}
```

Run the test again: the two `PageHeading` cases pass; the scan still fails. Commit the component on its own now, so every migration commit in Step 4 builds:

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/student-home-variants
/home/sico/Code/Lemely/.venv/bin/pre-commit run --files web/src/components/ui/page-heading.tsx
SKIP=import-linter git commit -S -m "feat(web): PageHeading, the one screen h1 that native phones hide when it repeats the title" -- web/src/components/ui/page-heading.tsx
```

- [ ] **Step 4: Migrate the screens**

For each offender: `<h1 className="…">` becomes `<PageHeading repeatsTitle={…} className="…">`, with the same classes, children and attributes, and the import from `@/components/ui/page-heading`. Change nothing else on the line. Desktop markup is identical apart from `data-page-heading`, so the existing drift keys cannot move.

If a screen's wrapper only exists to space the heading (a `div` holding the `h1` and nothing else), leave it: the native drift scenes show whether an empty gap remains, and Task 10's grouped layout revisits page spacing.

This step may fan out to up to three agents with disjoint screen sets (student A to M, student N to Z, teacher). Each commits only its own screens with `git commit -S -- <its paths>`; the agent that owns Step 2's test and Step 5's checks commits those.

Run: `cd web && npx vitest run tests/unit/pageHeading.test.ts tests/unit/a11yRules.test.ts tests/unit/utilityExistence.test.ts`
Expected: PASS, with an empty offender list.

- [ ] **Step 5: Behaviour check: one h1, no visible duplicate on native**

Append to `checks-native.mjs`:

```js
/** D11: two heading texts "repeat" when equal after these steps (see Task 5b). */
const normTitle = (s) => s.trim().toLowerCase().replace(/\s+/g, " ").replace(/^(your|my) /, "")

/** Tab roots of both portals plus the detail paths other checks use. Add a route
 * here when a screen's heading changes; skip only routes the mocks cannot serve,
 * with the reason in a comment. */
const HEADING_ROUTES = [
  ...[...STUDENT_TAB_PATHS, DETAIL_PATH, TAB_DRILL_PATH].map((path) => ({ ...NATIVE_HOME, path })),
  ...TEACHER_TAB_PATHS.map((path) => ({ ...NATIVE_TEACHER_HOME, path })),
]

NATIVE_CHECKS.push(
  ...["ios", "android"].flatMap((platform) =>
    HEADING_ROUTES.map((app) => ({
      id: `native-${platform}-one-heading-${app.path}`,
      platform,
      app,
      async run(page) {
        const h1s = await page.getByRole("heading", { level: 1 }).count()
        if (h1s !== 1) throw new Error(`${app.path}: ${h1s} level-1 headings reach assistive technology, expected 1`)
        const { title, headings } = await page.evaluate(() => ({
          title: document.querySelector("header [data-shell-title]")?.textContent ?? "",
          headings: [...document.querySelectorAll("main :is(h1, h2, [role=heading])")]
            .filter((el) => {
              const r = el.getBoundingClientRect()
              return el.checkVisibility() && r.width > 1 && r.height > 1
            })
            .map((el) => ({ text: el.textContent ?? "", html: el.outerHTML.slice(0, 120) })),
        }))
        const dupes = headings.filter((h) => normTitle(h.text) === normTitle(title))
        if (dupes.length) throw new Error(`${app.path}: visible heading repeats the large title: ${dupes.map((h) => h.html).join(" | ")}`)
      },
    })),
  ),
)
```

`DETAIL_PATH` and `TAB_DRILL_PATH` move to the top of `checks-native.mjs` as exported constants (Task 2's scenes import `DETAIL_PATH` from there; Task 5's re-tap check already uses `TAB_DRILL_PATH`), so one value serves every check. Define `STUDENT_TAB_PATHS` and `TEACHER_TAB_PATHS` beside them: the `to` of each entry in `STUDENT_BOTTOM_TABS` (`web/src/portals/student/shell.tsx`) and `TEACHER_BOTTOM_TABS` (`web/src/portals/teacher/index.tsx`), minus the raised Correct action, which is immersive and has no shell title.

Show it can go red: in one migrated screen whose heading repeats its title (name it from Step 1's table), set `repeatsTitle={false}`, rebuild, and expect `native-ios-one-heading-<that path>` FAIL "visible heading repeats the large title". Then delete that screen's `h1` entirely, rebuild, and expect FAIL "0 level-1 headings". Restore it and rebuild.

- [ ] **Step 6: Verify and commit**

```bash
cd web && npm run build
node scripts/shell-behaviour.mjs --check native-
node scripts/home-drift.mjs --scene native-ios-root,native-android-root,native-ios-detail,native-android-detail
node scripts/home-drift.mjs --scene student-,teacher-
```

Expected: every behaviour check passes; the `student-,teacher-` outcomes are unchanged (desktop markup only gains `data-page-heading`); the native root and detail keys are no further from the preview than after Task 5, and any entry that named a duplicate heading loses that text.

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/student-home-variants
FILES="web/tests/unit/pageHeading.test.ts web/scripts/drift/checks-native.mjs web/scripts/drift/scenes-native.mjs"
/home/sico/Code/Lemely/.venv/bin/pre-commit run --files $FILES
SKIP=import-linter git commit -S -m "test(web): one h1 per page and no duplicate title on native phones" -- $FILES
```

The component is committed in Step 3 and the screen migrations in Step 4, in batches, each with its own explicit paths.

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
  - `BottomSheetSurface` (`forwardRef<HTMLDivElement, BottomSheetSurfaceProps>`), where `BottomSheetSurfaceProps = { detents?: readonly Detent[]; initialDetent?: Detent; dismissible?: boolean; onDismiss: () => void; closing?: boolean; header?: ReactNode; className?: string; children: ReactNode } & HTMLAttributes<HTMLDivElement>`. The ref is the panel. The remaining props spread onto the panel, so callers keep `role`, `aria-*`, `tabIndex` and `onAnimationEnd` there.
  - `SheetGrabber()`, `useSheetScaleBack(active: boolean)`, `useKeyboardInset(): number`
  - CSS: `.lm-sheet`, `.lm-sheet-grabber`, `.lm-sheet[data-detent]`, `html[data-sheet-depth]`, and the custom property `--native-sheet-sy` (the scroll offset the scale-back pivots on, the preview's `--pf-sy`).

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
  it("iOS scales the page back at the large detent, pivoting on the visible top; reduced motion keeps it instant", () => {
    expect(block).toMatch(/:root\[data-platform="ios"\]\[data-sheet-depth\] #root \{[^}]*scale: var\(--native-sheet-scale-back\)/)
    expect(block).toMatch(/:root\[data-platform="ios"\] #root \{[^}]*transform-origin: 50% calc\(var\(--native-sheet-sy, 0px\) \+ env\(safe-area-inset-top\)\)/)
    expect(css).toMatch(/@media \(prefers-reduced-motion: reduce\)[\s\S]*#root[\s\S]*transition: none/)
  })
  it("per-platform large detent, motion and grabber (preview 4447a571)", () => {
    expect(block).toMatch(/:root\[data-platform="ios"\] \{[^}]*--native-sheet-large: var\(--native-sheet-large-ios\);[^}]*--native-sheet-dur: var\(--dur-sheet-ios\);[^}]*--native-sheet-ease: var\(--ease-ios-spring\)/)
    expect(block).toMatch(/:root\[data-platform="android"\] \{[^}]*--native-sheet-large: var\(--native-sheet-large-android\);[^}]*--native-sheet-dur: var\(--dur-sheet-android\);[^}]*--native-sheet-ease: var\(--ease-m3-emphasized-decelerate\)/)
    expect(block).toMatch(/\.lm-sheet \{[^}]*background: var\(--md-surface-container-low\)/)
    expect(block).toMatch(/\[data-platform="ios"\] \.lm-sheet-grabber \{[^}]*margin-block: var\(--native-grabber-gap-ios\)/)
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

/** iOS: while any sheet sits at the large detent, the page behind scales back.
 * It pivots on the top of what the reader sees: `lockScroll` pins the body at
 * `top: -scrollY`, so the scroll offset is read from there when it is locked. */
export function useSheetScaleBack(active: boolean): void {
  useEffect(() => {
    if (!active || readPlatform() !== "ios") return
    const root = document.documentElement
    const body = document.body.style
    const scrollY = body.position === "fixed" ? -parseFloat(body.top || "0") : window.scrollY
    root.style.setProperty("--native-sheet-sy", `${scrollY}px`)
    const depth = Number(root.dataset.sheetDepth ?? 0) + 1
    root.dataset.sheetDepth = String(depth)
    return () => {
      const next = Number(root.dataset.sheetDepth ?? 1) - 1
      if (next > 0) root.dataset.sheetDepth = String(next)
      else {
        delete root.dataset.sheetDepth
        root.style.removeProperty("--native-sheet-sy")
      }
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
      <div data-sheet-drag-region className="flex flex-col items-center select-none">
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
/* ── Native frame: sheets (native frame Task 6; preview .as-pop-panel / .as-modal).
   Only rendered on the native frame; desktop dialogs never use .lm-sheet. */
:root[data-platform="ios"] {
  --native-sheet-large: var(--native-sheet-large-ios);
  --native-sheet-dur: var(--dur-sheet-ios);
  --native-sheet-ease: var(--ease-ios-spring);
}
:root[data-platform="android"] {
  --native-sheet-large: var(--native-sheet-large-android);
  --native-sheet-dur: var(--dur-sheet-android);
  --native-sheet-ease: var(--ease-m3-emphasized-decelerate);
}
.lm-sheet {
  position: fixed;
  inset-inline: 0;
  bottom: var(--lm-keyboard-inset, 0px);
  z-index: var(--z-index-modal);
  display: flex;
  flex-direction: column;
  max-block-size: calc(var(--native-sheet-large) - var(--lm-keyboard-inset, 0px));
  padding-bottom: env(safe-area-inset-bottom);
  background: var(--md-surface-container-low);
  border-start-start-radius: var(--radius-card);
  border-start-end-radius: var(--radius-card);
  transition: translate var(--native-sheet-dur) var(--native-sheet-ease);
}
.lm-sheet[data-detent="medium"] { block-size: var(--native-sheet-medium); }
.lm-sheet[data-detent="large"] { block-size: calc(var(--native-sheet-large) - var(--lm-keyboard-inset, 0px)); }
.lm-sheet:not([data-closing]) { animation: lm-sheet-in var(--native-sheet-dur) var(--native-sheet-ease) both; }
.lm-sheet[data-closing] { animation: lm-sheet-out var(--dur-fast) var(--ease-in-soft) both; }
@keyframes lm-sheet-in { from { translate: 0 100%; } }
@keyframes lm-sheet-out { to { translate: 0 100%; } }
.lm-sheet-grabber {
  display: block;
  flex: none;
  border-radius: 9999px;
  touch-action: none;
}
:root[data-platform="ios"] .lm-sheet-grabber {
  inline-size: var(--native-grabber-w-ios);
  block-size: var(--native-grabber-h-ios);
  margin-block: var(--native-grabber-gap-ios);
  background: var(--md-outline);
}
:root[data-platform="android"] .lm-sheet-grabber {
  inline-size: var(--native-grabber-w-android);
  block-size: var(--native-grabber-h-android);
  margin-block: var(--native-grabber-gap-android);
  background: color-mix(in oklch, var(--md-on-surface-variant) 40%, transparent);
}
/* iOS large detent: the page behind scales back, pivoting on the top of the visible area
   (--native-sheet-sy, written by useSheetScaleBack), over a near-black backdrop. */
:root[data-platform="ios"] #root {
  transition: scale var(--native-sheet-dur) var(--native-sheet-ease), translate var(--native-sheet-dur) var(--native-sheet-ease), border-radius var(--native-sheet-dur) var(--native-sheet-ease);
  transform-origin: 50% calc(var(--native-sheet-sy, 0px) + env(safe-area-inset-top));
}
:root[data-platform="ios"][data-sheet-depth] #root {
  scale: var(--native-sheet-scale-back);
  translate: 0 calc(env(safe-area-inset-top) + 10px);
  border-radius: var(--native-group-radius-ios);
  overflow: clip;
}
:root[data-platform="ios"][data-sheet-depth] body { background: var(--native-sheet-backdrop); }
```

The `10px` drop and the 40% grabber mix are the preview's own numbers (`.as-app` transform, `--pf-grab`); if `design-tokens.test.ts` flags either, move it into the token block with that citation.

Inside the existing `@media (prefers-reduced-motion: reduce)` block, add:

```css
  .lm-sheet,
  .lm-sheet[data-closing],
  :root[data-platform="ios"] #root {
    animation: none;
    transition: none;
  }
```

`#root` is the React mount (`index.html`). Sheets portal into `document.body`, outside `#root`, so they never scale. The modal layer is `--z-index-modal` (the `z-modal` utility's variable in `index.css`).

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
  it("the action sheet's visible title is aria-hidden; Modal's sr-only copy labels the dialog", () => {
    expect(src).toMatch(/<div aria-hidden="true"[^>]*>\s*<p[^>]*>\{title\}<\/p>/)
    const modal = read("components/ui/modal.tsx")
    expect(modal).toMatch(/presentation === "action-sheet"[\s\S]*<h2 id=\{titleId\} className="sr-only">/)
    expect(modal).toMatch(/<p id=\{descriptionId\} className="sr-only">/)
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
          {presentation === "action-sheet" ? (
            <>
              <h2 id={titleId} className="sr-only">{title}</h2>
              {description ? <p id={descriptionId} className="sr-only">{description}</p> : null}
              {children}
            </>
          ) : (
            <>{body}{foot}</>
          )}
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
      <Modal open={open} onClose={onCancel} title={title} description={consequence} size="sm" dismissible={false} hideCloseButton presentation="action-sheet">
        <div className="lm-action-sheet-group">
          {/* Visible copy only: Modal's sr-only title and description are what
              aria-labelledby and aria-describedby point at, so nothing is read twice. */}
          <div aria-hidden="true" className="flex flex-col gap-1 px-4 py-3 text-center">
            <p className="text-label text-on-surface-variant">{title}</p>
            <p className="text-body-sm text-on-surface-variant">{consequence}</p>
          </div>
          {error ? <p role="alert" className="px-4 pb-3 text-center text-body-sm text-error">{error}</p> : null}
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

The Android native case falls through to today's `Modal` call, which renders as a content-fit sheet with the footer buttons (the M3 dialog-style sheet). There is no `haptic("tap")` on iOS, which has no Vibration API. The safe path keeps the weight: Cancel is semibold in its own group (`lm-action-sheet-cancel`). Labelling: when `presentation === "action-sheet"`, `modal.tsx`'s native branch renders a visually hidden `<h2 id={titleId}>{title}</h2>` and, when `description` is set, a visually hidden `<p id={descriptionId}>{description}</p>`, so `aria-labelledby` and `aria-describedby` always point at real elements. The visible copy in `ConfirmModal` is `aria-hidden`, so a screen reader hears the title and consequence once.

CSS (`index.css`, sheet block). Groups use the group surface (Task 0's table):

```css
.lm-action-sheet { background: transparent; gap: var(--space-2); padding-inline: var(--space-2); }
.lm-action-sheet-group,
.lm-action-sheet-cancel {
  border-radius: var(--native-group-radius-ios);
  background: var(--md-surface-container-lowest);
}
:root[data-theme="dark"] :is(.lm-action-sheet-group, .lm-action-sheet-cancel) { background: var(--md-surface-container-high); }
.lm-action-sheet-row {
  display: block;
  inline-size: 100%;
  min-block-size: var(--native-action-row-h);
  border-top: var(--native-hairline) solid var(--md-outline);
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

The four `<…>` strings (two routes, two trigger labels) are filled in **by this step** from the call sites you chose. The task is not done while any remain. Run `grep -nE '"<|/<' web/scripts/drift/checks-native.mjs` and expect nothing.

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
- Modify: `web/src/components/shell/NotificationsPanel.tsx`, `web/src/components/shell/AccountPanel.tsx`, `web/src/portals/settings/SettingsModal.tsx`, `web/src/components/ui/modal.tsx` (only if its focus return needs the fix named in Step 2; then add it to Step 6's `FILES`), `web/tests/unit/nativeSheets.test.ts`, `web/tests/unit/shellPanels.test.ts` (only where it pins the menu-only markup), `web/scripts/drift/checks-native.mjs`, `web/scripts/drift/justifications.json`

**Interfaces:**
- Consumes: `Modal` (Task 7: a sheet on native), `BottomSheetSurface`, `useNativeFrame`.
- Produces: `PanelSheet(props: { triggerLabel: string; triggerClassName?: string; trigger: ReactNode; title: string; children: (close: () => void) => ReactNode })`. It is a trigger button that owns `open`, plus a `Modal` (`size="md"`, so a content-fit sheet, the preview's `data-sheet="fit"`). `Modal` already carries the dialog contract (focus, Tab cycle, focus return, Escape, history, scroll lock), so `PanelSheet` writes none of it. `NotificationsPanel` and `AccountPanel` render it when `native`, and Radix `DropdownMenu` otherwise. Their panel body is factored into `NotificationsBody({ onNavigate, Row })` and `AccountBody({ onNavigate, Row })`. `Row` is `DropdownMenu.Item asChild` in the menu, and a plain `Fragment` wrapper in the sheet.

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
  it("PanelSheet reuses Modal's dialog contract instead of copying it", () => {
    const src = read("components/shell/PanelSheet.tsx")
    expect(src).toMatch(/<Modal\b[^>]*open=\{open\}[^>]*size="md"/)
    expect(src).toContain('aria-haspopup="dialog"')
    expect(src).toContain("aria-expanded={open}")
    expect(src).not.toContain("FOCUSABLE_SELECTOR")
    expect(src).not.toContain('role="dialog"')
  })
  it("SettingsModal is a medium/large sheet on native (preview data-detents) and keeps routing close", () => {
    const src = read("portals/settings/SettingsModal.tsx")
    expect(src).toContain("useNativeFrame()")
    expect(src).toMatch(/detents=\{\["medium", "large"\]\}/)
    expect(src).toMatch(/initialDetent="medium"/)
    expect(src).toMatch(/onDismiss=\{onClose\}/)
  })
})
```

Run: `cd web && npx vitest run tests/unit/nativeSheets.test.ts`
Expected: FAIL.

- [ ] **Step 2: `PanelSheet.tsx`**

`PanelSheet` owns the `open` state and its trigger, and hands the dialog to `Modal`, which on native is already a sheet with the full contract (Task 7). `PanelSheet` only renders on native, so this `Modal` always takes its sheet branch.

```tsx
import { useState, type ReactNode } from "react"
import { Modal } from "@/components/ui/modal"

/** Native frame Task 8: the bell and account panels as content-fit sheets
 * (preview: `data-sheet="fit"`, no scale-back). Modal owns focus, Escape,
 * history and scroll lock; focus returns to this trigger on close. */
export function PanelSheet({ triggerLabel, triggerClassName, trigger, title, children }: {
  triggerLabel: string; triggerClassName?: string; trigger: ReactNode; title: string; children: (close: () => void) => ReactNode
}) {
  const [open, setOpen] = useState(false)
  const close = () => setOpen(false)
  return (
    <>
      <button type="button" aria-label={triggerLabel} aria-haspopup="dialog" aria-expanded={open} className={triggerClassName} onClick={() => setOpen(true)}>
        {trigger}
      </button>
      <Modal open={open} onClose={close} title={title} size="md" hideCloseButton>
        {children(close)}
      </Modal>
    </>
  )
}
```

If `Modal` does not return focus to the element that was focused before it opened, fix that in `Modal` (both branches benefit), not here.

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

When `native`, wrap the existing panel markup in `BottomSheetSurface` with `detents={["medium", "large"]} initialDetent="medium" onDismiss={onClose}`, as the preview's settings sheet (`data-detents="medium large"`, opening at medium). Dragging the grabber up snaps to large, and on iOS the scale-back follows from `detent === "large"`. Keep the existing routing-based close (`onClose` is already `overlayCloseAction`), and keep the existing focus and Escape code. The mobile top tabs stay as they are. Drop the `pt-[max(env(safe-area-inset-top),1rem)]` top padding on native: the sheet already starts below the safe area.

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
      const depth = () => page.evaluate(() => document.documentElement.hasAttribute("data-sheet-depth"))
      if (await depth()) throw new Error("settings opened at large; the preview opens it at medium")
      const grab = await dialog.locator(".lm-sheet-grabber").boundingBox()
      await page.mouse.move(grab.x + grab.width / 2, grab.y + 2)
      await page.mouse.down()
      await page.mouse.move(grab.x + grab.width / 2, grab.y - 300, { steps: 8 })
      await page.mouse.up()
      await page.waitForFunction(() => document.documentElement.hasAttribute("data-sheet-depth"))
      await page.goBack()
      await dialog.waitFor({ state: "detached" })
      if (new URL(page.url()).pathname !== "/student") throw new Error("back did not return to the page")
      if (await depth()) throw new Error("the page stayed scaled back after the sheet closed")
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
- Create: `web/src/components/ui/use-dialog-focus.ts`
- Modify: `web/src/components/ui/popover.tsx`, `web/src/components/ui/modal.tsx` (uses `useDialogFocus`; behaviour unchanged), `web/src/components/ui/select.tsx` (doc comment only), `web/tests/unit/nativeSheets.test.ts`, `web/scripts/drift/checks-native.mjs`

**Interfaces:**
- Consumes: `BottomSheetSurface`, `useNativeFrame`, `useDialogHistory`, `lockScroll`.
- Produces:
  - `useDialogFocus(panelRef: RefObject<HTMLElement | null>, open: boolean): (event: KeyboardEvent) => void`. It is `modal.tsx`'s existing focus code, moved: on open it remembers `document.activeElement` and focuses the first focusable element in the panel (one rAF later); the returned handler cycles Tab and Shift+Tab inside the panel; on close it returns focus to the remembered element. `FOCUSABLE_SELECTOR` moves with it.
  - The same `PopoverProps` as today. On native, `contentClassName` is ignored and the content renders in a content-fit sheet with `aria-labelledby` pointing at the trigger.

- [ ] **Step 1: Failing tests (append)**

```ts
describe("Popover and Select (Task 9, D4)", () => {
  it("Popover renders a sheet on native and keeps its render-prop API", () => {
    const src = read("components/ui/popover.tsx")
    expect(src).toContain("useNativeFrame()")
    expect(src).toContain("<BottomSheetSurface")
    expect(src).toMatch(/renderTrigger: \(props: PopoverRenderProps\) => ReactNode/)
  })
  it("one focus trap: Modal and the native Popover share useDialogFocus", () => {
    for (const f of ["components/ui/modal.tsx", "components/ui/popover.tsx"]) {
      expect(read(f), f).toContain("useDialogFocus(")
      expect(read(f), f).not.toContain("FOCUSABLE_SELECTOR =")
    }
    expect(read("components/ui/use-dialog-focus.ts")).toContain("FOCUSABLE_SELECTOR")
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

First move `modal.tsx`'s focus code (`FOCUSABLE_SELECTOR`, the `previouslyFocused` ref, the rAF first-focus effect, focus return, and the Tab-cycle branch of `handleKeyDown`) into `useDialogFocus` in `use-dialog-focus.ts`, and make `Modal` call it. `Modal`'s behaviour must not change: `node scripts/shell-behaviour.mjs` (desktop focus trap and Escape checks) proves it in Step 4.

In `popover.tsx`, when `native && open`, render `createPortal(<><scrim onClick={close}/><BottomSheetSurface ref={sheetRef} role="dialog" aria-modal="true" aria-labelledby={triggerId} id={contentId} tabIndex={-1} onKeyDown={onSheetKeyDown} detents={["content"]} onDismiss={() => setOpen(false)}>{children}</BottomSheetSurface></>, document.body)`, where `onSheetKeyDown` runs `useDialogFocus(sheetRef, native && open)`'s handler and closes on Escape. Add `useDialogHistory({ open: native && open, dismissible: true, onClose: () => setOpen(false) })` and `lockScroll` while it is open on native. The outside-click and Escape logic stays for desktop. `triggerProps` gains an `id` (`triggerId`). `triggerProps["aria-haspopup"]` stays `"dialog"`.

In `select.tsx`, add to the doc comment: `Native frame D4 (docs/superpowers/plans/2026-11-08-native-mobile-frame.md): on iOS and Android phones the native picker already is the platform's sheet or wheel, so this stays native there too.`

- [ ] **Step 3: Behaviour check**

Append a check on student Notifications (`/student/notifications`), one of the three `Popover` call sites (`Notifications.tsx`, `flashcards/FlashcardDecks.tsx`, `ui/question-row.tsx`). Open its popover trigger on iOS, expect `getByRole("dialog")` with class `lm-sheet` and focus inside it, press Escape, and expect it detached with focus back on the trigger. Show it can go red the same way as Task 7 (force `native` false).

- [ ] **Step 4: Verify and commit**

```bash
cd web && npx vitest run tests/unit/nativeSheets.test.ts tests/unit/a11yRules.test.ts tests/unit/overlayExit.test.ts && npm run build && node scripts/shell-behaviour.mjs && node scripts/home-drift.mjs --scene student-,teacher-
```

Expected: all behaviour checks pass, the desktop `SHELL_CHECKS` included (they cover `Modal`'s focus trap after the hook move).

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/student-home-variants
FILES="web/src/components/ui/use-dialog-focus.ts web/src/components/ui/modal.tsx web/src/components/ui/popover.tsx web/src/components/ui/select.tsx web/tests/unit/nativeSheets.test.ts web/scripts/drift/checks-native.mjs"
/home/sico/Code/Lemely/.venv/bin/pre-commit run --files $FILES
SKIP=import-linter git commit -S -m "feat(web): Popover opens as a native sheet on phones; Select stays native" -- $FILES
```

---

### Task 10: Grouped-list primitives and edge-to-edge cards

**Files:**
- Create: `web/src/components/ui/list-group.tsx`, `web/tests/unit/listGroup.test.ts`
- Modify: `web/src/components/ui/card.tsx` (`lm-native-card`), `web/src/components/shell/PortalShell.tsx` (`lm-native-page` on the root; `lm-native-main` from Task 5 gets the iOS margin), `web/src/components/shell/NotificationsPanel.tsx` and `AccountPanel.tsx` (sheet rows use `ListRow`), `web/src/portals/settings/SettingsRows.tsx` (sections take the group look on native), `web/src/components/ui/route-skeleton.tsx` (list skeleton in the group shape on native), `web/src/index.css`, `web/scripts/drift/justifications.json`

**Interfaces:**
- Produces:
  - `ListGroup(props: { label?: string; footer?: ReactNode; children: ReactNode; className?: string })`: a `<section>` with an optional label header (the `label` style) and a rows container.
  - `ListRow(props: { title: ReactNode; subtitle?: ReactNode; leading?: ReactNode; trailing?: ReactNode; to?: string; onClick?: () => void; lines?: 1 | 2 | 3 })`: a `Link` when `to`, a `button` when `onClick`, otherwise a `div`.
  - Unlayered native classes (phone width on iOS/Android only, so an Android tablet or a desktop never sees them): `.lm-native-page` (page ground), `.lm-native-card`, `.lm-native-group`, `.lm-native-group-label`, `.lm-native-row[data-lines]`. Classes, not `native:`/`ios:`/`android:` utilities, because they must beat the base `border`/`rounded-lg`/`px-3.5` utilities regardless of build order, and because a bare `ios:`/`android:` utility is not width-gated.

Layout from the preview (`variant-a.css` section 4): iOS groups are inset-grouped, 12px radius, inside a 16px page margin (`lm-native-main` goes from 14px to 16px on iOS). Android groups are full-bleed with no radius, but the page keeps its 14px gutter: a 16px Android padding would push the 390px-wide `@container/home` past its 376px query, and the preview found the same. So an Android card bleeds with a negative 14px margin and gives the 14px back as a transparent inline border, which shows the card's own background (`background-clip` defaults to `border-box`), so its content keeps its width and nothing rewraps. Android list groups bleed the same way with no border, because their rows already carry the 16px Material list inset.

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
  it("rows carry the native class and their line count", () => {
    const out = html(createElement(ListGroup, null, createElement(ListRow, { title: "A", subtitle: "B" })))
    expect(out).toContain("lm-native-group")
    expect(out).toMatch(/class="[^"]*\blm-list-row\b[^"]*\blm-native-row\b[^"]*" data-lines="2"/)
  })
})

describe("grouped-list CSS (preview 4447a571, variant-a.css section 4)", () => {
  const css = readFileSync(join(SRC, "index.css"), "utf8")
  const start = css.indexOf("/* ── Native frame: grouped lists")
  const block = css.slice(start, css.indexOf("/* ── Native frame:", start + 1))
  it("every native rule sits inside the phone-width media block", () => {
    const media = block.indexOf("@media (max-width: 720px) {")
    expect(media).toBeGreaterThan(-1)
    expect(block.slice(0, media)).not.toContain("lm-native-")
  })
  it("page ground per platform and theme", () => {
    expect(block).toMatch(/:root\[data-platform="ios"\] \.lm-native-page \{[^}]*background-color: var\(--md-surface-container\)/)
    expect(block).toMatch(/:root\[data-theme="dark"\]\[data-platform="ios"\] \.lm-native-page \{[^}]*background-color: var\(--md-surface-container-lowest\)/)
    expect(block).toMatch(/:root\[data-platform="android"\] \.lm-native-page \{[^}]*background-color: var\(--md-surface-container-low\)/)
    expect(block).toMatch(/:root\[data-theme="dark"\]\[data-platform="android"\] \.lm-native-page \{[^}]*background-color: var\(--md-surface\)/)
  })
  it("iOS: 16px page margin, 12px groups, 44px rows, hairline separators inset 16px", () => {
    expect(block).toMatch(/:root\[data-platform="ios"\] \.lm-native-main \{[^}]*padding-inline: var\(--native-group-inset-ios\)/)
    expect(block).toMatch(/:root\[data-platform="ios"\] :is\(\.lm-native-card, \.lm-native-group\) \{[^}]*border-radius: var\(--native-group-radius-ios\)/)
    expect(block).toMatch(/:root\[data-platform="ios"\] \.lm-native-row \{[^}]*min-height: var\(--native-row-min-ios\)/)
    expect(block).toMatch(/:root\[data-platform="ios"\] \.lm-native-row \+ \.lm-native-row::before \{[^}]*inset-inline: var\(--native-sep-inset-ios\) 0;[^}]*block-size: var\(--native-hairline\);[^}]*background: var\(--md-outline\)/)
  })
  it("Android: full-bleed, square, 14px gutter kept as a transparent border on cards, 56/72/88 rows, no separators", () => {
    expect(block).toMatch(/:root\[data-platform="android"\] \.lm-native-card \{[^}]*margin-inline: calc\(-1 \* var\(--native-gutter-android\)\);[^}]*border-inline: var\(--native-gutter-android\) solid transparent/)
    expect(block).toMatch(/:root\[data-platform="android"\] \.lm-native-group \{[^}]*margin-inline: calc\(-1 \* var\(--native-gutter-android\)\)/)
    for (const n of [1, 2, 3]) {
      expect(block).toMatch(new RegExp(`:root\\[data-platform="android"\\] \\.lm-native-row\\[data-lines="${n}"\\] \\{[^}]*min-height: var\\(--native-row-${n}-android\\)`))
    }
    expect(block).toMatch(/:root\[data-platform="android"\] \.lm-list-row \+ \.lm-list-row \{[^}]*border-top: 0/)
  })
})

describe("Card on the native frame", () => {
  const card = readFileSync(join(SRC, "components/ui/card.tsx"), "utf8")
  it("carries the native card class; design A classes unchanged", () => {
    expect(card).toContain('"bg-surface-container-lowest border border-outline-variant rounded-lg lm-native-card"')
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
export function ListGroup({ label, footer, children, className }: { label?: string; footer?: ReactNode; children: ReactNode; className?: string }) {
  const id = useId()
  return (
    <section aria-labelledby={label ? id : undefined} className={cn("flex flex-col gap-2", className)}>
      {label ? (
        <h2 id={id} className="lm-native-group-label px-1 text-label text-on-surface-variant">
          {label}
        </h2>
      ) : null}
      <div className="lm-native-group overflow-hidden rounded-lg border border-outline-variant bg-surface-container-lowest dark:bg-surface-container-high">
        {children}
      </div>
      {footer ? <div className="lm-native-group-label px-1 text-body-sm text-on-surface-variant">{footer}</div> : null}
    </section>
  )
}

export function ListRow({
  title, subtitle, leading, trailing, to, onClick, lines = subtitle ? 2 : 1,
}: {
  title: ReactNode; subtitle?: ReactNode; leading?: ReactNode; trailing?: ReactNode
  to?: string; onClick?: () => void; lines?: 1 | 2 | 3
}) {
  const cls = "lm-list-row lm-native-row lm-press flex w-full items-center gap-3 px-4 py-2.5 text-start"
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
  if (to) return <Link to={to} viewTransition className={cls} data-lines={lines}>{inner}</Link>
  if (onClick) return <button type="button" onClick={onClick} className={cls} data-lines={lines}>{inner}</button>
  return <div className={cls} data-lines={lines}>{inner}</div>
}
```

`lm-press` gets its native rules in Task 11. `utilityExistence.test.ts` needs every `lm-` class defined, so this task adds the marker rule `.lm-press { --lm-press: 1; }` below. It has no visual effect; Task 11 keeps it and adds the native rules after it.

CSS (`index.css`, new block):

```css
/* ── Native frame: grouped lists (native frame Task 10; preview variant-a.css section 4). */
/* Opt-in marker for press feedback; Task 11 adds the native rules. */
.lm-press { --lm-press: 1; }
.lm-list-row + .lm-list-row { border-top: 1px solid var(--md-outline-variant); }
@media (max-width: 720px) {
  /* Page ground. */
  :root[data-platform="ios"] .lm-native-page { background-color: var(--md-surface-container); }
  :root[data-theme="dark"][data-platform="ios"] .lm-native-page { background-color: var(--md-surface-container-lowest); }
  :root[data-platform="android"] .lm-native-page { background-color: var(--md-surface-container-low); }
  :root[data-theme="dark"][data-platform="android"] .lm-native-page { background-color: var(--md-surface); }
  /* Cards and list groups lose the floating outline. */
  :root:is([data-platform="ios"], [data-platform="android"]) :is(.lm-native-card, .lm-native-group) {
    border: 0;
    box-shadow: none;
  }
  /* iOS: inset-grouped inside a 16px page margin. */
  :root[data-platform="ios"] .lm-native-main { padding-inline: var(--native-group-inset-ios); }
  :root[data-platform="ios"] :is(.lm-native-card, .lm-native-group) { border-radius: var(--native-group-radius-ios); }
  :root[data-platform="ios"] .lm-native-group-label { padding-inline: var(--space-4); }
  :root[data-platform="ios"] .lm-native-row { position: relative; min-height: var(--native-row-min-ios); }
  :root[data-platform="ios"] .lm-list-row + .lm-list-row { border-top: 0; }
  :root[data-platform="ios"] .lm-native-row + .lm-native-row::before {
    content: "";
    position: absolute;
    inset-block-start: 0;
    inset-inline: var(--native-sep-inset-ios) 0;
    block-size: var(--native-hairline);
    background: var(--md-outline);
    pointer-events: none;
  }
  /* Android: full-bleed and square; the 14px page gutter stays (container query). */
  :root[data-platform="android"] .lm-native-card {
    border-radius: 0;
    margin-inline: calc(-1 * var(--native-gutter-android));
    border-inline: var(--native-gutter-android) solid transparent;
  }
  :root[data-platform="android"] .lm-native-group {
    border-radius: 0;
    margin-inline: calc(-1 * var(--native-gutter-android));
  }
  :root[data-platform="android"] .lm-native-group-label { padding-inline: calc(var(--space-4) - var(--native-gutter-android)); }
  :root[data-platform="android"] .lm-native-row[data-lines="1"] { min-height: var(--native-row-1-android); }
  :root[data-platform="android"] .lm-native-row[data-lines="2"] { min-height: var(--native-row-2-android); }
  :root[data-platform="android"] .lm-native-row[data-lines="3"] { min-height: var(--native-row-3-android); }
  :root[data-platform="android"] .lm-list-row + .lm-list-row { border-top: 0; }
}
```

The iOS separator is a `::before` hairline with logical insets, so it mirrors in RTL. The Android card's border is `transparent` on purpose: the card's own background paints under it, so the 14px reads as card, whatever surface the card uses.

- [ ] **Step 3: Card and PortalShell**

`card.tsx` class string (design A's classes unchanged; the native look is the unlayered rule above):

```ts
"bg-surface-container-lowest border border-outline-variant rounded-lg lm-native-card"
```

Data-heavy blocks (charts, mark tables, the grade ladder) already sit in one `Card`, so they become one full-width group. No per-screen change is needed for that.

In `PortalShell.tsx`: the root `div` gets `lm-native-page` (it keeps `bg-surface-container` for design A). `<main>` already has `lm-native-main` (Task 5); the rule above gives it the iOS margin and leaves Android's 14px.

- [ ] **Step 4: Roll out to shell-owned and shared surfaces**

- `NotificationsBody` and `AccountBody` (Task 8): when rendered in the sheet, rows become `ListRow` inside one `ListGroup`. The menu rows are untouched.
- `SettingsRows.tsx`: each settings section's container gets the group look on native. Add `lm-native-group` to its section wrapper and `lm-native-row` (with `data-lines`) to its rows; do not change its desktop classes. Read the file first, and change only the section wrapper and row classes.
- `route-skeleton.tsx`: the `list` skeleton's container gets `lm-native-group` and its rows `lm-native-row`, so loading looks like the group on native and is unchanged elsewhere.

Run: `cd web && npx vitest run tests/unit/listGroup.test.ts tests/unit/routeSkeleton.test.ts tests/unit/settingsTabs.test.ts tests/unit/shellPanels.test.ts tests/unit/utilityExistence.test.ts tests/unit/rtlSafety.test.ts tests/unit/darkConsumers.test.ts tests/unit/contrastRules.test.ts`
Expected: PASS.

- [ ] **Step 5: Drift and commit**

```bash
cd web && npm run build && node scripts/home-drift.mjs --scene native- && node scripts/home-drift.mjs --scene student-,teacher-
```

Expected: existing scenes are unchanged (no native rule applies without a platform). Native root, detail, bell and settings keys move toward 0 px. Update their entries with any remaining differences (pending).

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
- Modify: `web/src/index.css` (a native press block after Task 10's grouped-lists block), `web/src/components/ui/button.tsx` (recipe base gets `lm-press lm-press-scale`), `web/src/components/ui/nav-shells.tsx` (tab and row cells get `lm-press`), `web/src/components/shell/shellStyles.ts` (`SHELL_ICON_BUTTON` gets `lm-press lm-press-scale`), `web/src/components/shell/PortalShell.tsx` (install once)

Preview behaviour (`variant-a.css` section 5): one layer drawn as a background image, so it follows the element's radius and never clips a badge (no `overflow: hidden`). iOS dims 8% toward black in light and white in dark, and scales buttons (not rows or tabs) to 0.97; iOS tab items dim their glyph and label (opacity 0.55) instead of drawing a layer. Android draws a 10% `currentColor` state layer that ripples out from the touch point over 450ms with `cubic-bezier(0.2, 0, 0, 1)`.

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

describe("press CSS (preview 4447a571, variant-a.css section 5)", () => {
  const block = css.slice(css.indexOf("/* ── Native frame: press states"))
  it("one background-image layer, so it follows the radius and never clips a badge", () => {
    expect(block).toMatch(/\.lm-press\[data-pressed\] \{[^}]*background-image: radial-gradient\(circle at var\(--lm-press-x\) var\(--lm-press-y\), color-mix\(in oklch, var\(--lm-press-ink\) var\(--lm-press-layer\), transparent\) var\(--lm-press-rr\)/)
    expect(block).not.toMatch(/\.lm-press[^{]*\{[^}]*overflow: hidden/)
  })
  it("iOS: 8% toward black in light and white in dark; buttons scale to 0.97", () => {
    expect(block).toMatch(/:root\[data-platform="ios"\] \{[^}]*--lm-press-ink: var\(--native-press-ink-light\);[^}]*--lm-press-layer: var\(--native-press-dim\)/)
    expect(block).toMatch(/:root\[data-theme="dark"\]\[data-platform="ios"\] \{[^}]*--lm-press-ink: var\(--native-press-ink-dark\)/)
    expect(block).toMatch(/\[data-platform="ios"\] \.lm-press-scale\[data-pressed\] \{[^}]*scale: var\(--native-press-scale\)/)
    expect(block).toMatch(/\[data-platform="ios"\] \.lm-native-tabbar \.lm-press\[data-pressed\] \{[^}]*background-image: none;[^}]*opacity: var\(--native-tab-press-opacity-ios\)/)
  })
  it("Android: a 10% currentColor layer rippling out over 450ms", () => {
    expect(block).toMatch(/:root\[data-platform="android"\] \{[^}]*--lm-press-ink: currentColor;[^}]*--lm-press-layer: var\(--native-state-pressed\)/)
    expect(block).toMatch(/\[data-platform="android"\] \.lm-press\[data-pressed\] \{[^}]*animation: lm-ripple var\(--native-ripple-dur\) var\(--ease-m3-emphasized\)/)
  })
  it("visible in under 50ms: no transition delay on the press-in", () => {
    expect(block).not.toMatch(/\.lm-press[^{]*\{[^}]*transition-delay/)
  })
})

describe("press is applied to the primitives", () => {
  it("buttons and shell icon buttons scale; tabs and list rows only dim", () => {
    expect(read("components/ui/button.tsx")).toContain("lm-press lm-press-scale")
    expect(read("components/shell/shellStyles.ts")).toContain("lm-press lm-press-scale")
    expect(read("components/ui/nav-shells.tsx")).toContain("lm-press")
    expect(read("components/ui/nav-shells.tsx")).not.toContain("lm-press-scale")
    expect(read("components/ui/list-group.tsx")).toContain("lm-press")
    expect(read("components/ui/list-group.tsx")).not.toContain("lm-press-scale")
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

- [ ] **Step 3: CSS (a new block after Task 10's grouped-lists block)**

```css
/* ── Native frame: press states (native frame Task 11; preview variant-a.css section 5).
   Phone width on iOS/Android; design A keeps its own active:scale-[0.98] rules.
   One layer drawn as a background image (no ::after, no overflow: hidden), so it
   follows the element's radius and never clips a badge. */
@property --lm-press-rr { syntax: "<length-percentage>"; inherits: false; initial-value: 0px; }
@media (max-width: 720px) {
  :root[data-platform="ios"] { --lm-press-ink: var(--native-press-ink-light); --lm-press-layer: var(--native-press-dim); }
  :root[data-theme="dark"][data-platform="ios"] { --lm-press-ink: var(--native-press-ink-dark); }
  :root[data-platform="android"] { --lm-press-ink: currentColor; --lm-press-layer: var(--native-state-pressed); }
  :root:is([data-platform="ios"], [data-platform="android"]) .lm-press {
    transition: scale var(--dur-instant) var(--ease-out-soft);
  }
  :root:is([data-platform="ios"], [data-platform="android"]) .lm-press[data-pressed] {
    --lm-press-rr: var(--lm-press-r);
    background-image: radial-gradient(circle at var(--lm-press-x) var(--lm-press-y), color-mix(in oklch, var(--lm-press-ink) var(--lm-press-layer), transparent) var(--lm-press-rr), transparent var(--lm-press-rr));
  }
  :root[data-platform="ios"] .lm-press-scale[data-pressed] { scale: var(--native-press-scale); }
  /* iOS tab items dim their glyph and label instead of drawing a layer. */
  :root[data-platform="ios"] .lm-native-tabbar .lm-press[data-pressed] {
    background-image: none;
    opacity: var(--native-tab-press-opacity-ios);
  }
  /* Android: the layer ripples out from the touch point. */
  :root[data-platform="android"] .lm-press[data-pressed] {
    animation: lm-ripple var(--native-ripple-dur) var(--ease-m3-emphasized);
  }
}
@keyframes lm-ripple { from { --lm-press-rr: 0px; } }
```

In the reduced-motion block, add `.lm-press { transition: none; animation: none; }`. The state layer still shows at full size, but the ripple does not grow and the scale is instant.

The press-in has no delay. `data-pressed` is set on `pointerdown`, before `:active`, so the layer shows in the first frame (under 50ms). If an element already paints a `background-image` of its own (a gradient button), the press layer replaces it while pressed; check `button.tsx`'s variants and, if one uses a gradient, leave `lm-press` off that variant.

- [ ] **Step 4: Apply and install**

- `button.tsx`: add `lm-press lm-press-scale` to the `cva` base string.
- `nav-shells.tsx`: add `lm-press` to the `BottomNav` cell and both `SidebarNav` row recipes.
- `shellStyles.ts`: add `lm-press lm-press-scale` to `SHELL_ICON_BUTTON` (next to Task 4's `lm-native-iconbtn`).
- `index.css`: `.lm-press-scale` needs a definition outside the media block for `utilityExistence`: add `.lm-press-scale { --lm-press-scale: 1; }` beside Task 10's `.lm-press` marker.
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
FILES="web/src/lib/pressFeedback.ts web/src/index.css web/src/components/ui/button.tsx web/src/components/ui/nav-shells.tsx web/src/components/shell/shellStyles.ts web/src/components/shell/PortalShell.tsx web/tests/unit/pressFeedback.test.ts"
# Append each file Step 1's hover-only scan made you change (FILES="$FILES <that path>"); none if the scan was clean.
/home/sico/Code/Lemely/.venv/bin/pre-commit run --files $FILES
SKIP=import-linter git commit -S -m "feat(web): native press states, iOS dim and scale, Android state layer and ripple" -- $FILES
```

---

### Task 12: Interactive edge swipe-back (standalone on iOS and Android, D5)

The gate does not change: the edge swipe runs in standalone display on both platforms, as it does today, and stays off in browser tabs (Safari's own swipe, Chrome's own back). This task makes the gesture interactive: the column follows the finger with a parallax underlay, and the release commits at 35% width or a fast fling.

**Files:**
- Modify: `web/src/lib/nav/edgeSwipeBack.ts` (`markSwipeNav`, `consumeSwipeNav`), `web/src/components/edge-swipe-back.tsx` (interactive transform, parallax, release), `web/src/components/root-outlet.tsx` (`data-direction="swipe"` for one navigation), `web/src/components/shell/PortalShell.tsx` (`data-shell-column` on the column div), `web/src/index.css` (swipe underlay and `data-direction="swipe"`), `web/scripts/drift/harness.mjs` (`app.init`), `web/scripts/drift/checks-native.mjs`, `web/tests/unit/edgeSwipeBack.test.ts` (exists; extend it)

**Interfaces:**
- Consumes: `swipeBackRelease` (Task 6), `useDragGesture` (its `onProgress`, `transformTarget` and `touchAction` options exist), `isStandaloneDisplay` (unchanged gate).
- Produces: `markSwipeNav(): void` and `consumeSwipeNav(): boolean` in `edgeSwipeBack.ts` (a one-shot flag: the next navigation is a swipe). `edgeSwipeDecision` and `EdgeSwipeInput` keep their `standalone` field and behaviour.

- [ ] **Step 1: Failing tests**

```ts
// web/tests/unit/edgeSwipeBack.test.ts (append)
import { consumeSwipeNav, edgeSwipeDecision, markSwipeNav } from "@/lib/nav/edgeSwipeBack"

describe("the swipe navigation flag is one-shot (Task 12)", () => {
  it("consumes once, then reads false", () => {
    expect(consumeSwipeNav()).toBe(false)
    markSwipeNav()
    expect(consumeSwipeNav()).toBe(true)
    expect(consumeSwipeNav()).toBe(false)
  })
})

describe("edge swipe-back runs in standalone only, whatever the platform (native frame D5)", () => {
  const base = { startX: 4, dx: 200, dy: 2, viewportWidth: 390, dir: 1 as const }
  it("standalone: back", () => expect(edgeSwipeDecision({ ...base, standalone: true })).toBe("back"))
  it("browser tab: none", () => expect(edgeSwipeDecision({ ...base, standalone: false })).toBe("none"))
})
```

Keep the existing `edgeSwipeDecision` tests as they are. Merge the imports with the file's existing ones (one `vitest` import, one import from `@/lib/nav/edgeSwipeBack`). If the file already has both standalone cases, skip the second `describe`.

- [ ] **Step 2: Logic**

In `edgeSwipeBack.ts`, add:

```ts
let swipeNavPending = false
/** Native frame Task 12: the next navigation comes from a committed edge swipe. */
export function markSwipeNav(): void {
  swipeNavPending = true
}
/** Read once by RootOutlet's direction effect; the flag clears as it is read. */
export function consumeSwipeNav(): boolean {
  const pending = swipeNavPending
  swipeNavPending = false
  return pending
}
```

Do not change `edgeSwipeDecision`, `EdgeSwipeInput` or the `standalone` gate (D5).

- [ ] **Step 3: Interactive component**

In `edge-swipe-back.tsx`:
- `enabled` stays `standalone`, computed as today (`isStandaloneDisplay`), on every platform.
- `transformTarget`: a ref to `document.querySelector("[data-shell-column]")`.
- `touchAction: "pan-y"`.
- `onProgress(dx)`: set `--lm-swipe-progress` (0..1) on `html` and `data-swiping` on `html`. The column follows the finger through `useDragGesture`'s own transform. The underlay is drawn by CSS (below).
- `onCommit(dx, dy)`: compute the velocity from the last two progress samples, kept in a ref with `performance.now()`. If `swipeBackRelease({ dx: dx * dir, velocity, width })` is `"commit"` and `edgeSwipeDecision(...)` is `"back"`, call `markSwipeNav()` and navigate exactly as today. Otherwise let the hook spring back. Always clear `data-swiping` and `--lm-swipe-progress`.

`RootOutlet` (`web/src/components/root-outlet.tsx`) sets `data-direction` in a layout effect on navigation. After a swipe it must use `"swipe"` for that one navigation: `document.documentElement.dataset.direction = consumeSwipeNav() ? "swipe" : navigationDirection(type)`.

CSS (`index.css`):

```css
/* ── Native frame: swipe-back (native frame Task 12). The column follows the
   finger; the shell ground under it shows a dimmed parallax strip. */
html[data-swiping] [data-shell-column] {
  box-shadow: calc(-1 * var(--space-4)) 0 var(--space-4) color-mix(in oklch, var(--md-shadow) 18%, transparent);
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
    id: "native-android-standalone-swipe-back",
    platform: "android",
    app: { ...NATIVE_HOME, path: "/student", init: STANDALONE },
    async run(page) {
      await page.getByRole("link", { name: "Classes" }).first().click()
      await page.waitForURL(/\/student\/classes/)
      await page.mouse.move(4, 400)
      await page.mouse.down()
      await page.mouse.move(60, 402, { steps: 4 })
      if (!(await page.evaluate(() => document.documentElement.hasAttribute("data-swiping")))) throw new Error("Android standalone did not start an interactive swipe (D5 keeps it)")
      await page.mouse.move(250, 404, { steps: 6 })
      await page.mouse.up()
      await page.waitForURL(/\/student$/)
    },
  },
  ...["ios", "android"].map((platform) => ({
    id: `native-${platform}-browser-tab-no-swipe-back`,
    platform,
    // No STANDALONE init: a browser tab, where Safari's swipe and Chrome's back take over.
    app: { ...NATIVE_HOME, path: "/student" },
    async run(page) {
      await page.getByRole("link", { name: "Classes" }).first().click()
      await page.waitForURL(/\/student\/classes/)
      await page.mouse.move(4, 400)
      await page.mouse.down()
      await page.mouse.move(250, 402, { steps: 6 })
      const swiping = await page.evaluate(() => document.documentElement.hasAttribute("data-swiping"))
      await page.mouse.up()
      await page.waitForTimeout(400)
      if (swiping || !/\/student\/classes/.test(page.url())) throw new Error("the in-app swipe-back ran in a browser tab")
    },
  })),
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

Show it can go red: force `enabled: false` in `edge-swipe-back.tsx`, rebuild, and expect `native-ios-standalone-swipe-back` and `native-android-standalone-swipe-back` to FAIL "did not start". Then force `enabled: true`, rebuild, and expect both `browser-tab-no-swipe-back` checks to FAIL. Restore it and rebuild.

- [ ] **Step 5: Verify and commit**

```bash
cd web && npx vitest run tests/unit/edgeSwipeBack.test.ts tests/unit/navigationDirection.test.ts tests/unit/rtlSafety.test.ts tests/unit/motionDefaults.test.ts && npm run build && node scripts/shell-behaviour.mjs && node scripts/home-drift.mjs --scene student-,teacher-
```

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/student-home-variants
FILES="web/src/lib/nav/edgeSwipeBack.ts web/src/components/edge-swipe-back.tsx web/src/components/root-outlet.tsx web/src/components/shell/PortalShell.tsx web/src/index.css web/scripts/drift/harness.mjs web/scripts/drift/checks-native.mjs web/tests/unit/edgeSwipeBack.test.ts"
/home/sico/Code/Lemely/.venv/bin/pre-commit run --files $FILES
SKIP=import-linter git commit -S -m "feat(web): interactive swipe-back with parallax in standalone on iOS and Android" -- $FILES
```

---

### Task 13: Shell pull-to-refresh on every root (D6) and Android-only haptics

Before starting, check the open question "Pull-to-refresh indicator". This task as written keeps the existing `PullIndicator` and takes only the preview's 64px threshold; if the user chose to port the preview's per-platform indicators, that port is added here first.

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
import { PULL_THRESHOLD_PX } from "@/components/shell/ShellPullToRefresh"
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
  it("arms at the preview's 64px on both platforms, one number shared with the token block", () => {
    const token = read("index.css").match(/--native-ptr-threshold:\s*(\d+)px/)?.[1]
    expect(PULL_THRESHOLD_PX).toBe(Number(token))
    expect(read("components/shell/ShellPullToRefresh.tsx")).toContain("threshold: PULL_THRESHOLD_PX")
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

/** The preview's arm distance on both platforms (`--pf-ptr-threshold`); the
 * same number as `--native-ptr-threshold`, pinned by shellPullToRefresh.test.ts. */
export const PULL_THRESHOLD_PX = 64

/** Native frame D6: one pull-to-refresh on every root page of both portals.
 * It refetches whatever the page is showing (active queries), so no screen
 * has to wire its own. */
export function ShellPullToRefresh({ enabled, children }: { enabled: boolean; children: ReactNode }) {
  const surface = useRef<HTMLDivElement>(null)
  const queryClient = useQueryClient()
  const { pulling, refreshing } = usePullToRefresh(surface, {
    enabled,
    threshold: PULL_THRESHOLD_PX,
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
    await page.route("**/api/student/overview", (route) => { calls++; return route.fallback() })
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

The glob is the one `studentShellMocks` registers (`**/api/student/overview`, `mocks.mjs`); a later `page.route` runs first and `route.fallback()` hands the request on to the mock. Add the same check for a teacher root (`app: NATIVE_TEACHER_HOME`, counting the teacher dashboard's API path). Show it can go red: pass `enabled={false}` and expect FAIL.

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

Add a check `native-android-review-list-and-table` on `/teacher/review`. `teacherShellMocks` serves the queue as `{ items: [], total: 3 }`, which has no rows to assert on, so the check's `app.mocks` runs `teacherShellMocks(page)` and then registers its own `**/api/teacher/review?**` route returning two items in the shape `Review.tsx` reads (take the item type from the screen's query). Expect one `ListRow` link per item (two), click "View table", and expect `getByRole("region", { name: "Review queue" })` to contain a `table` with two body rows. Reload and expect the table view to persist (`sessionStorage`).

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

Expected: branch `design/student-home-variants`, with the Task 0 to 15 commits present (5b included). Untracked `.impeccable/` folders and designer preview edits are left alone and listed in the report.

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
- **Header:** tab roots show a large title (Bricolage 800, 34/41) under an actions-only bar (44px iOS, 64px Android). As the large title scrolls away it fades, and a 17px Schibsted 600 inline title (centred on iOS, start-aligned on Android) and the bar's surface fade in over the last 30% of its exit. iOS: transparent to glass (86% `surface-container-lowest`, dark `surface-container-low`, `--blur-nav`, saturate 1.6) with a 0.5px `outline-variant` hairline. Android: transparent to `surface-container`, no shadow, no hairline. Detail pages use the compact bar from the start: back (iOS chevron plus the parent's title, Android arrow), title, one action.
- **Page heading:** on phones the large title replaces a screen's own heading when it repeats the title. Screens render their top heading with `PageHeading`, which is visually hidden on the native frame and stays the page's one `h1` for screen readers; the large title is `aria-hidden`.
- **Tab bar:** iOS 49px plus the home indicator, glass, 10px labels, 24px outline icons at rest and filled when selected, tinted `primary`. Android 80dp, 12px labels, 24px icons, with a 64x32 `secondary-container` pill. The raised Correct button stays. Tapping the active tab scrolls to the top, then pops to the tab root. Camera, the correction run, paper review and review-a-mark hide it.
- **Sheets, not dialogs or popovers:** `Modal`, `ConfirmModal`, settings, bell, account and popovers open as bottom sheets on `surface-container-low` with a grabber (36x5 iOS, 32x4 Android), `--radius-card` top corners, a scrim and drag to dismiss. The bell and account panels fit their content; settings and long modals open at medium (50dvh) and drag up to large. iOS: 320ms spring, and the page scales back to 0.94 at the large detent. Android: 300ms M3 emphasized decelerate, no scale-back. Destructive confirms are an action sheet on iOS (Cancel separate) and an M3 dialog-style sheet on Android. Selects stay native: the OS picker is the platform sheet.
- **Grouped content:** cards drop their outline and become groups on the group surface (`surface-container-lowest`, dark `surface-container-high`). iOS: inset-grouped, 12px radius, 16px page margins, 44px rows, hairline separators inset 16px from the leading edge, on a `surface-container` ground (dark `surface-container-lowest`). Android: full-bleed and square, keeping the 14px page gutter inside each card, 56/72/88 rows with 16px padding, no separators, on a `surface-container-low` ground (dark `surface`). Dense teacher tables read as list rows with "View table".
- **Touch:** every tappable element has a press state. iOS: an 8% dim toward black (white in dark), and buttons scale to 0.97; tabs dim to 55% instead. Android: a 10% `currentColor` state layer that ripples from the touch point over 450ms. No hover-only affordances. 44px targets (48px icon buttons on Android). Android-only haptics on commit gestures.
- **Gestures:** pull-to-refresh on every root (shell-owned), arming at 64px. Swipe-back in a home-screen app on iOS and Android (browser tabs use the browser's own back), with 30% parallax, committing at 35% width or a fast fling. Pushes slide with M3 emphasized easing on Android and a spring on iOS. Reduced motion turns it all off.
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
- **Task 18 (StudentHome):** drop its own `usePullToRefresh` and `PullIndicator`; the shell's `ShellPullToRefresh` already covers root pages (native frame D6). On phones the page title is the shell's large title ("Overview"). The home's top heading must be a `PageHeading` (`web/src/components/ui/page-heading.tsx`, native frame D11): `repeatsTitle` when it names the page (visually hidden on phones), `repeatsTitle={false}` for a greeting such as "Hi, Mariam" (stays visible). A raw `<h1>` fails `pageHeading.test.ts`, and the native frame's `native-*-one-heading-/student` checks fail on a visible duplicate or on anything but one `h1`. The hero height is unchanged by the native frame.
- **Task 19:** the old `Overview.tsx` no longer has a pull-to-refresh to remove (native frame Task 13 did it).
- **Task 20 (sweep):** include `--scene native-`, the behaviour runner's `native-` checks, and `tests/unit/pageHeading.test.ts`.
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
3. **Gestures vs text selection.** Sheet drags start only on `[data-sheet-drag-region]` (grabber and header, `select-none`). Swipe-back starts only in the 24px leading edge zone and skips interactive targets. Pull-to-refresh starts only at scroll top on a vertical drag. Content keeps `user-select: auto`, which Task 12's check asserts. Remaining risk: a long-press text selection that starts within 24px of the edge. Standalone gives the gesture priority there, which matches native apps.
4. **View transitions on iOS earlier than 18.** `document.startViewTransition` does not exist there. react-router's `viewTransition` falls back to an instant swap, so the push slide and the swipe-in parallax do not run. That is acceptable, because navigation still works, and the swipe gesture's own finger-following transform still runs. Do not polyfill.
5. **`transform`/`scale` on `#root` for the iOS scale-back** re-anchors `position: fixed` descendants (the tab bar, banners) to `#root` while a large sheet is open. They scale with the page, which is the intended look. Sticky elements in the scaled tree also stop sticking for the duration. That is invisible, because the scroll is locked.
6. **The status bar flip (D7)** affects every standalone route at once, including screens this plan does not otherwise touch. Task 3 Step 4 is a grep-driven audit; a route it misses will draw under the clock. Check: launch standalone on a real iPhone and walk auth, onboarding and the camera.
7. **Platform emulation in drift.** Playwright's UA override does not change `navigator.userAgentData.platform` on a Linux host. The resolver therefore trusts UA-CH only for "Android" and parses the UA string otherwise. `openApp` asserts `data-platform` after load, so a resolver regression fails loudly instead of silently capturing design A.
8. **Bundle budget.** `BottomSheetSurface`, `PanelSheet` and the list primitives join shared chunks. `check:bundle` may fail at Task 16; the remedy is lazy `PanelSheet`, the same pattern as the panels.
9. **A screen's own `<h1>` repeating the large title** (D11, Task 5b). The risk is a wrong `repeatsTitle` call: a heading marked as repeating that actually says more (hidden on phones, content lost visually), or the reverse (a visible duplicate). The behaviour check catches the duplicate on every tab root and the sampled detail pages; the inventory table in Task 5b's commit body is the review point for the rest. A screen added later cannot skip the decision: the source scan rejects a raw `<h1>`.
10. **The preview gap.** The native scenes depend on the designer's preview supporting `platform` and `page`. If the preview lacks a state (for example the settings sheet on Android), mark that scene log-only with a justification. Do not invent a reference.
11. **Android gesture navigation and the edge swipe (D5).** On Android with gesture navigation, the OS claims edge swipes for its own back before the page sees them, so the in-app swipe-back mostly serves three-button navigation and devices that pass the pointer through. Both paths go back, so a lost race costs nothing. If testing on a real Android phone shows the two fighting (a double back), report it to the user rather than changing D5.

## Self-review against the brief

- §3.1 header: Task 4, plus the one-heading rule (D11, Task 5b). §3.2 tab bar: Task 5. §3.3 sheets: Tasks 6 to 9 (selects per D4). §3.4 grouped content: Tasks 10, 14 and 15. §3.5 touch feedback: Tasks 3, 11 and 13. §3.6 gestures and motion: Tasks 12 and 13. Sheet easing is in Task 6. Per-platform push easing on the existing `data-direction` slides, and the swipe-in parallax, are in Task 12's CSS. Tab crossfade is unchanged (existing view transition). §3.7 platform switch: Task 1.
- §5 states: long titles (Task 4 line clamp and truncate), badges (unchanged `BottomNav` badge), keyboard (Task 6), list states (Task 10 skeleton, Task 14 states), banners between the bar and content (the large title sits directly under the bar, and banners stay in `<main>` under it), standalone vs tab (Tasks 3 and 12).
- §7 decisions 1 to 5: preview first (Task 0), before P2 (sequencing, Task 17 note), brand fonts (Global Constraints), teachers (Tasks 4, 14 and 15, teacher scenes), DESIGN.md (Task 17).
- §2 proof: Task 16 Step 6.
