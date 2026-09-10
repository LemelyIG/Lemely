# Audit Dossier Remediation — Phase A (`feat/native-and-pwa`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land every Phase A row of the remediation ledger (87 rows, packets A1–A8): the mechanical native-feel fixes, manifest/asset completeness, security headers, share target, service-worker lifecycle, and the CI guards that keep them true.

**Architecture:** Pure additive changes to the existing Vite/React PWA (`web/`), the Cloudflare Worker (`web/worker/index.ts`), `web/nginx.conf`, and DESIGN.md. No new runtime dependency except `@tanstack`-free hooks; `virtual:pwa-register` already ships with `vite-plugin-pwa`. Each packet is one commit; the ledger row status is updated in the same commit.

**Tech Stack:** React 19 + react-router-dom 7.18, Tailwind 4.3, vite-plugin-pwa (`injectManifest`, workbox), Vitest, Playwright, Cloudflare Workers Static Assets (`_headers`), FastAPI backend (one endpoint in A5).

**Spec:** `docs/superpowers/specs/2026-09-10-audit-dossier-remediation-design.md` · **Ledger:** `docs/superpowers/specs/2026-09-10-audit-dossier-remediation-ledger.md`

## Global Constraints

- Branch `feat/native-and-pwa` (exists, commit `b765220`), PR into `develop`, never `main`.
- Signed commits: `git commit -S`; conventional scopes; `pre-commit run --all-files` (inside `source .venv/bin/activate`) before every commit; trailer `Claude-Session: https://claude.ai/code/session_01CxbrmXri2Fm1p2KFgjL3rr`.
- **Never run the full test suite locally.** Web: `npm run typecheck && npm run lint && npx vitest run <named files> && npm run build`. Backend: `pytest --no-cov tests/<named file>` + `ruff check`. CI runs everything.
- Implementers are `executor` model=sonnet; reviewers `code-reviewer` model=opus; verifier `verifier` model=opus. Main session (sonnet, ralph + `Skill(orchestrator)`) never writes code.
- Every implementer brief starts with: `Skill(superpowers:test-driven-development)`, `Skill(superpowers:verification-before-completion)`, `Skill(vitest-testing-patterns)`, `Skill(react-best-practices)`, `Skill(checklist-discipline)` + the task's domain skills. Invoke before writing code; follow; do not summarise.
- DESIGN.md §14 rule 3: tokens only, no arbitrary Tailwind values (`text-[16px]` forbidden → add a token first).
- `vite.config.ts` `injectManifest.globIgnores` is a single array (line 133). Never add a second `globIgnores` key (TS1117).
- `sw.ts` `PRECACHE_HOSTS` stays `lemelyig.com`, `www.lemelyig.com`. Never widen.
- Line numbers below were read on develop at `ee8991b`; re-grep before editing (step 1 of every task).
- Ledger update in every commit: set the row's `status` to `done A<n>` and `evidence` to the verification command that passed. The verifier replaces `done A<n>` with `done <short sha>` at phase close (Task 9).
- Copy rules: no em-dashes in user-facing strings (`npm run check:copy` must stay at 0 findings); DESIGN.md error-copy voice (specific, no "Something went wrong").

---

### Task 0: Branch bootstrap and ledger wiring

**Files:**
- Modify: `docs/superpowers/specs/2026-09-10-audit-dossier-remediation-ledger.md` (status column only)

**Skills:** none beyond process skills.

- [ ] **Step 1: Confirm branch state**

Run: `git status --short --branch && git log --oneline -1`
Expected: `## feat/native-and-pwa`, clean tree, HEAD `b765220`.

- [ ] **Step 2: Re-verify the two "already fixed" candidates**

Run: `grep -n 'ToastProvider' web/src/main.tsx; ls web/src/portals/parent/screens/Notifications.tsx`
Expected: `main.tsx:74` mounts `ToastProvider`; parent `Notifications.tsx` exists. Set ledger row `parent-no-notifications-inbox` to `already-fixed` with evidence `web/src/portals/parent/screens/Notifications.tsx present on develop ee8991b` (final confirmation of the route + nav link happens in Phase D D2).

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-09-10-audit-dossier-remediation-ledger.md
git commit -S -m "docs(ledger): confirm parent notifications inbox already on develop"
```

---

### Task 1 (A1): Touch, scroll, viewport and safe-area mechanics

**Files:**
- Modify: `web/index.html:15` (viewport meta)
- Modify: `web/src/index.css` — `html, body` rule (~:576-580), `@media (pointer: coarse)` block (~:629), `.lm-scroll` (~:1140), `--fs-*` token block (~:209-216), new `.lm-nav-chrome`, new `.lm-app-header` standalone rule
- Modify: `web/src/components/ui/input.tsx:110`, `web/src/components/ui/textarea.tsx:113` (`text-body-md` → `text-field`)
- Modify: `web/src/components/ui/table.tsx:36`
- Modify: `web/src/components/ui/nav-drawer.tsx` (panel + trigger get `lm-nav-chrome`), `web/src/components/ui/nav-shells.tsx:77` (`lm-nav-chrome` + safe-area bottom padding class), `web/src/components/ui/toast.tsx:111` (safe-area bottom)
- Modify: 4 top bars: `web/src/portals/student/index.tsx:569`, `web/src/portals/teacher/index.tsx:438`, `web/src/portals/admin/index.tsx:317`, `web/src/portals/marketing/index.tsx:73` (add `lm-app-header lm-nav-chrome`)
- Modify: all 11 `min-h-screen` sites (`git grep -n min-h-screen web/src`) → `min-h-screen min-h-dvh` except `aside` sidebars
- Modify: `DESIGN.md` §4.2 (add `--fs-field` row, documented as a platform floor, not a type rung); §5 note that `apple-mobile-web-app-status-bar-style="default"` is deliberate
- Test: `web/tests/unit/nativeMechanics.test.ts` (new), `web/tests/unit/design-tokens.test.ts` (extend)

**Interfaces:**
- Produces: CSS utility `.text-field { font-size: var(--fs-field) }` (Tailwind 4 `@utility text-field` in `index.css`, matching how `text-body-md` is declared — read the existing `@utility` block first); class `.lm-nav-chrome`; class `.lm-app-header` (only styled inside `@media (display-mode: standalone)`); token `--fs-field: 16px`.
- Consumed by: A2 (PhoneStep inherits `text-field` via shared `Input`), A8 guard script.

**Skills:** `pwa-expert`, `mobile-ux-optimizer`, `native-app-designer`.

**Behaviours:**
1. Viewport meta becomes exactly `width=device-width, initial-scale=1.0, viewport-fit=cover, interactive-widget=resizes-content`.
2. `html, body` gains `-webkit-tap-highlight-color: transparent; overscroll-behavior-y: contain;` (keep `overflow-x: clip`).
3. Coarse-pointer selector list gains `touch-action: manipulation;` — same selector list, no new selectors.
4. `.lm-scroll` gains `overscroll-behavior: contain;`; `table.tsx:36` wrapper gains Tailwind `overscroll-x-contain`.
5. `.lm-nav-chrome { -webkit-touch-callout: none; user-select: none; }` applied to drawer panel (`role="dialog"` element), `NavDrawerTrigger`, `BottomNav` root, 4 top bars.
6. `--fs-field: 16px` beside the other `--fs-*`; `text-field` utility; `input.tsx`/`textarea.tsx` use it. Visually confirm `NotificationSettings.tsx` `wrapperClassName="w-36"` fields and `JoinWithCode.tsx` mono field do not overflow at 320px (Playwright screenshot or manual note in commit body).
7. `@media (display-mode: standalone) { .lm-app-header { padding-top: env(safe-area-inset-top); } }`; `nav-shells.tsx:77` root gets `pb-[env(safe-area-inset-bottom)]` — arbitrary value is forbidden by §14 → add utility `.lm-safe-bottom { padding-bottom: env(safe-area-inset-bottom) }` in `index.css` and use it on BottomNav and the toast rail.
8. `min-h-screen min-h-dvh` pairing at every non-sidebar site (11 found: parent/index:322, state-views:402, route-error:241, marketing/index:71, Login:68 and :92, student/index:715, misc/FullPageState:282, admin/index:343, teacher/index:544, settings/SettingsFrame:144).

- [ ] **Step 1: Re-grep every line reference above; record actual lines in the commit body.**
- [ ] **Step 2: Write failing tests** in `web/tests/unit/nativeMechanics.test.ts` — read `web/index.html` and `web/src/index.css` as text (pattern: `tests/unit/fontPreload.test.ts` already reads `index.html`) and assert: viewport string; `-webkit-tap-highlight-color: transparent` inside the `html, body` rule; `overscroll-behavior-y: contain`; `touch-action: manipulation` inside the `(pointer: coarse)` block; `.lm-scroll` contains `overscroll-behavior: contain`; `--fs-field: 16px` defined; `input.tsx` and `textarea.tsx` source contain `text-field` and not `text-body-md` on the native element; at least one `env(safe-area-inset-` and one `@media (display-mode: standalone)`; no file under `web/src` has `min-h-screen` without `min-h-dvh` on the same line except lines containing `<aside`. Extend `design-tokens.test.ts` to include `--fs-field` in the token inventory it already checks.
- [ ] **Step 3: Run** `npx vitest run tests/unit/nativeMechanics.test.ts tests/unit/design-tokens.test.ts` → expect FAIL on every new assertion.
- [ ] **Step 4: Implement behaviours 1–8; DESIGN.md §4.2 row first.**
- [ ] **Step 5: Run** the two test files → PASS; `npm run typecheck && npm run lint && npm run build`.
- [ ] **Step 6: Update ledger rows** (tap-highlight-color, double-tap-zoom-unneutralized, overscroll-behavior-absent, no-overscroll-behavior, touch-callout-select-on-chrome, kb-1, input-font-14px-ios-zoom, min-h-screen-no-dvh-fallback, no-safe-area-insets, safe-area-viewport-cover, no-standalone-media-query, kb-6, status-bar-style-default-mismatch) → `done A1`.
- [ ] **Step 7: Commit** `feat(web): native touch, viewport and safe-area mechanics (A1)`.

---

### Task 2 (A2): Input attributes and tap targets

**Files:**
- Modify: `web/src/portals/auth/SignupParent.tsx` (PhoneStep: hand-rolled `<select>`/`<input>` → kit `Select`/`Input`; `enterKeyHint="send"` on the phone field)
- Modify: `web/src/portals/auth/Login.tsx:113` (`LINK_CLASS` gains `inline-flex min-h-11 items-center`), password field `enterKeyHint="go"`
- Modify: `web/src/portals/auth/JoinWithCode.tsx` code field `enterKeyHint="go"`
- Modify: `web/src/portals/auth/SignupDetails.tsx:295` Name field `autoCapitalize="words" autoCorrect="off"`
- Test: `web/tests/unit/authInputAttributes.test.tsx` (new; render with `@testing-library/react` — check `tests/unit/joinWithCode.test.ts` for the existing render helper)

**Interfaces:** `InputProps` already spreads native attributes (`input.tsx:16`, `:120`) — no component change.

**Skills:** `mobile-ux-optimizer`, `form-validation-architect`.

- [ ] **Step 1: Re-grep** `PhoneStep`, `LINK_CLASS`, `autoComplete="name"`.
- [ ] **Step 2: Failing tests:** render Login → password input has `enterkeyhint="go"`; every `<a>` rendered from `LINK_CLASS` has classes `inline-flex` and `min-h-11`; render JoinWithCode → code input `enterkeyhint="go"`; render SignupDetails → name input `autocapitalize="words"` and `autocorrect="off"`; render SignupParent phone step → phone input rendered by kit `Input` (has the kit's `data-slot` or wrapper class — read `input.tsx` to pick the stable marker) and `enterkeyhint="send"`.
- [ ] **Step 3: Run** `npx vitest run tests/unit/authInputAttributes.test.tsx` → FAIL.
- [ ] **Step 4: Implement.** PhoneStep migration must keep the existing validation and error-copy paths (read `signupParentLogic.ts`).
- [ ] **Step 5: Run** test file → PASS; `npm run typecheck && npm run lint && npm run build`.
- [ ] **Step 6: Ledger:** kb-2, kb-3, kb-4, login-links-under-44px-tap-target → `done A2`.
- [ ] **Step 7: Commit** `fix(web): field keyboard hints, phone step on kit inputs, 44px auth links (A2)`.

---

### Task 3 (A3): Pressed states, a11y tokens, RTL leaks, dead fonts

**Files:**
- Modify: `web/src/components/ui/question-row.tsx:83,105`, `confidence-indicator.tsx:49,145`, `role-switcher.tsx:70,98`, `state-views.tsx` retry buttons (~:307-312) — add `active:bg-surface-2` (or `active:scale-[0.98]` where `Button` already uses it; match the kit)
- Modify: `web/src/components/CameraCapture.tsx` (~:310) `text-accent` → `text-accent-ink`
- Modify: `web/src/components/ui/nav-shells.tsx:94` `text-white` → `text-accent-on`; :88/:111 per dossier (`x-a11y-prod-accent-small-text-below-own-floor` evidence: small accent text on the badge label)
- Modify: `web/src/portals/teacher/screens/ReviewItem.tsx` (~:445-453) three `<kbd>` → `<Kbd>` from `components/ui/kbd.tsx`
- Modify: `web/src/components/ui/processing-state.tsx` `StageProgressBar` → `<ProgressBar value={pct} tone="accent" ariaLabel=… />` from `progress-bar.tsx`; delete the width transition
- Modify: RTL leaks — `git grep -n 'ml-auto\|text-left' web/src/components/ui` → `ms-auto` / `text-start` (dossier: 5 leaks in 4 components)
- Modify: `web/src/index.css:117` `--info` hue → a hue not used by any `--pastel-*` (read the §3.8 subject table in `index.css` ~:150-161; `--focus-ring` hue 240 collides with `--info` today, pick a hue that no subject pastel uses and record it in DESIGN.md §3)
- Modify: `web/package.json` remove `@fontsource/instrument-serif`, `@fontsource-variable/work-sans`; `npm install` to relock; `web/README.md:13` font list → Newsreader / Geist / JetBrains Mono / Caveat
- Test: extend `web/tests/unit/hoverTransition.test.ts` (or new `pressedStates.test.ts`): every file in `components/ui/*.tsx` containing `onClick` and `hover:` also contains `active:`; `tests/unit/design-tokens.test.ts`: `--info` hue differs from every subject pastel hue; `tests/unit/motionDefaults.test.ts`: no `transition-[width]`/`transition: width` in `components/ui`; `tests/unit/a11yRules.test.ts`: no `text-white` in `web/src`; `tests/unit/contrastRules.test.ts`: no `text-accent` paired with `text-dense-sm`/`text-metadata`; RTL: no `ml-auto`/`text-left` in `components/ui`.

**Skills:** `color-contrast-auditor`, `design-accessibility-auditor`, `web-design-guidelines`.

- [ ] **Step 1: Re-grep** all sites; list them in the commit body.
- [ ] **Step 2: Failing tests** as listed.
- [ ] **Step 3: Run** the 5 test files → FAIL.
- [ ] **Step 4: Implement.**
- [ ] **Step 5: Run** → PASS; `npm run typecheck && npm run lint && npm run build && npm run check:copy`.
- [ ] **Step 6: Ledger:** no-active-state-question-row-confidence, role-switcher-no-active-state, x-a11y-prod-accent-small-text-below-own-floor, x-dark-nav-badge-raw-white, x-completeness-kbd-primitive-bypassed, x-motion-width-transition-gate-violation, x-completeness-rtl-unwireable, x-tokens-sky-info-subject-collision-persists, x-type-dead-font-packages-stale-docs → `done A3`.
- [ ] **Step 7: Commit** `fix(web): pressed states, AA tokens, RTL logical props, drop dead font packages (A3)`.

---

### Task 4 (A4): Offline state wiring and small perf

**Files:**
- Modify: `web/src/components/ui/query-state.tsx` (shared query-error renderer — read it first; this is the "shared isError rendering path" the dossier could not find) — classify `err instanceof ApiError && err.status === 0`, or `err instanceof TypeError`, → render `OfflineState`; else `ErrorState`
- Modify: the five screens' error branches (`Overview.tsx`, `Subject.tsx`, `Friends.tsx`, `Notifications.tsx`, `Parents.tsx` under `web/src/portals/student/screens/`) to pass the error object through the shared path (or `kind` prop) — re-grep `ErrorState` usages there
- Modify: `web/src/portals/student/screens/CorrectPaper.tsx:335` `useState<ScanSource>(() => window.matchMedia?.("(pointer: coarse)").matches ? "camera" : "file")`
- Modify: `web/src/portals/teacher/screens/Grading.tsx:185` `<img … decoding="async" />`
- Test: `web/tests/unit/offlineClassification.test.tsx` (new): renders the shared error renderer with `new ApiError(0, …)` → `role="status"` + WifiSlash offline copy; with `new ApiError(500, …)` → `role="alert"`; `tests/unit/correctionOutcome.test.ts` untouched. `tests/unit/correctPaperSource.test.tsx` (new): `matchMedia` mocked `matches:true` → initial source `camera`; `false` → `file`.

**Skills:** `error-handling-patterns`, `pwa-expert`.

- [ ] **Step 1: Re-grep** `ApiError` class (`web/src/lib/api.ts`) and `status === 0` classification; confirm `OfflineState` signature at `state-views.tsx:331`.
- [ ] **Step 2: Failing tests.**
- [ ] **Step 3: Run** → FAIL.
- [ ] **Step 4: Implement.**
- [ ] **Step 5: Run** → PASS; `npm run typecheck && npm run lint && npm run build`.
- [ ] **Step 6: Ledger:** offline-2, offline-4, x-completeness-offline-state-dead, correct-paper-defaults-to-file-not-camera, grading-thumbnail-no-decoding-async → `done A4`.
- [ ] **Step 7: Commit** `feat(web): route offline failures to OfflineState, camera-first scan source (A4)`.

---

### Task 5 (A5): Manifest members, icons, screenshots, robots, widget endpoint

**Files:**
- Modify: `web/vite.config.ts:70-133` (manifest block + `globIgnores`)
- Create: `web/scripts/manifest_screenshots.mjs` (copy verbatim from `.claude/worktrees/ui-audit-pwa/web/scripts/manifest_screenshots.mjs`), `web/public/screenshots/dashboard-wide.jpg`, `web/public/screenshots/dashboard-narrow.jpg` (copy from the same worktree; regenerate with `npm run screenshots:manifest` if the dashboard changed)
- Modify: `web/package.json` scripts: `"screenshots:manifest": "node scripts/manifest_screenshots.mjs"`
- Modify: `web/scripts/generate_icons.mjs` — `ICONS` gains `{ file: "apple-touch-icon.png", size: 180, scale: SQUARE_SCALE }`, `{ file: "store-icon-1024.png", size: 1024, scale: SQUARE_SCALE, alpha: false }`, three `shortcut-<name>-96.png` (mark + `PAPER`), and emit `favicon.ico` from `public/brand/mark-favicon.svg` (sharp can output PNG; ico needs `png-to-ico` — prefer generating a 32×32 PNG and writing a minimal ICO container in the script, no new dependency; if impossible, add `png-to-ico` as a devDependency and note it in the commit body); delete the false comment at :82-86
- Modify: `web/index.html:14` `apple-touch-icon` → `/apple-touch-icon.png`; add `<link rel="icon" href="/favicon.ico" sizes="32x32">` after the SVG icon
- Create: `web/public/robots.txt`, `web/public/.well-known/web-app-origin-association`, `web/public/widgets/streak.json` (Adaptive Card 1.6 template: streak count, next study session title/time), `web/public/widgets/streak-data.json` (empty defaults)
- Create: backend `lemely/web/routers/widget.py` — `GET /api/student/widget` (auth-required, returns `{ "streak": int, "nextSession": {"title": str, "startsAt": iso} | null }`), register in the router index; `tests/test_widget_router.py`
- Modify: `web/src/routes.tsx` `/join/:code` — accept `web+lemely://join/<code>` payload (`protocol_handlers` passes the full URL as `%s`; parse `code` from either a bare code or the `web+lemely:` URL)
- Test: `web/tests/unit/brandTokens.test.ts` (new): `expect(MASKABLE_SCALE).toBeLessThanOrEqual(0.8 / Math.SQRT2)` — export `MASKABLE_SCALE` from `generate_icons.mjs` or move the constants to `vite/brandTokens.ts`; `web/tests/unit/manifest.test.ts` (new): import the manifest object from `vite.config.ts` (factor the manifest into `web/vite/manifest.ts` exporting `manifest` so tests do not import the whole config) and assert every key listed in Behaviours; `web/tests/unit/joinProtocol.test.ts` (new): `parseJoinCode("web+lemely://join/ABC123") === "ABC123"`.

**Behaviours (manifest, exact):**
```ts
id: "/",
dir: "ltr",
orientation: "any",
prefer_related_applications: false,
display_override: ["standalone", "minimal-ui"],
categories: ["education", "productivity"],
launch_handler: { client_mode: "navigate-existing" },
handle_links: "preferred",
protocol_handlers: [{ protocol: "web+lemely", url: "/join/%s" }],
edge_side_panel: { preferred_width: 400 },
scope_extensions: [{ origin: "https://staging.lemelyig.com" }],
note_taking: { new_note_url: "/student/practice" },
shortcuts: [
  { name: "Mark a paper", short_name: "Mark", url: "/student/correct", icons: [{ src: "shortcut-mark-96.png", sizes: "96x96", type: "image/png" }] },
  { name: "Dashboard", url: "/student", icons: [{ src: "shortcut-dashboard-96.png", sizes: "96x96", type: "image/png" }] },
  { name: "Notifications", url: "/student/notifications", icons: [{ src: "shortcut-notifications-96.png", sizes: "96x96", type: "image/png" }] },
],
screenshots: [ /* exact array printed by scripts/manifest_screenshots.mjs — never hand-typed */ ],
widgets: [{ name: "Streak", tag: "lemely-streak", ms_ac_template: "widgets/streak.json", data: "widgets/streak-data.json", description: "Your study streak and next session", screenshots: [{ src: "screenshots/dashboard-narrow.jpg", sizes: "780x1688", label: "Streak widget preview" }] }],
```
`globIgnores` (single array): existing font entry + `"screenshots/**"`, `"widgets/**"`, `"store-icon-1024.png"`. `web-app-origin-association` content: `{ "web_apps": [{ "web_app_identity": "https://lemelyig.com/" }] }`. `robots.txt`: `User-agent: *`, `Allow: /`, `Disallow:` for `/api/`, `/student`, `/teacher`, `/parent`, `/admin`, `/settings`, `/join`, plus `Sitemap:` only if one exists (grep `sitemap` first; else omit).

**Skills:** `pwa-expert`; backend part `rest-api-design`.

- [ ] **Step 1: Re-read** `vite.config.ts:53-133`, `generate_icons.mjs`, `routes.tsx` join route, `.claude/worktrees/ui-audit-pwa/web/scripts/manifest_screenshots.mjs`.
- [ ] **Step 2: Failing tests** (`brandTokens`, `manifest`, `joinProtocol`, `tests/test_widget_router.py`).
- [ ] **Step 3: Run** `npx vitest run tests/unit/brandTokens.test.ts tests/unit/manifest.test.ts tests/unit/joinProtocol.test.ts` and `pytest --no-cov tests/test_widget_router.py` → FAIL.
- [ ] **Step 4: Implement**; `npm run icons`; `npm run build && npm run screenshots:manifest` and paste the printed array.
- [ ] **Step 5: Run** tests → PASS; then built-output assertions:
```bash
npm run typecheck && npm run lint && npm run build
python3 - <<'PY'
import json;m=json.load(open("dist/manifest.webmanifest"))
for k in ["id","dir","orientation","prefer_related_applications","display_override","categories","launch_handler","handle_links","protocol_handlers","edge_side_panel","scope_extensions","note_taking","shortcuts","screenshots","widgets"]: assert k in m,k
assert sorted(s["form_factor"] for s in m["screenshots"])==["narrow","wide"]; print("manifest OK")
PY
file dist/screenshots/*.jpg dist/apple-touch-icon.png dist/store-icon-1024.png dist/favicon.ico dist/shortcut-*-96.png
grep -c 'screenshots/\|widgets/\|store-icon' dist/sw.js   # must be 0
ls dist/.well-known/web-app-origin-association dist/robots.txt
```
- [ ] **Step 6: Ledger:** every `manifest-*` row except `manifest-share-target`/`manifest-file-handlers`, `Id`, `Screenshots`, `Orientation`, `manifest-orientation`, `ScreenshotSizesAreValid`, `ScreenshotTypesAreValid`, `ScreenshotsAreFetchable`, `ShortcutIconsAreFetchable`, `ShortcutIconSizesAreValid`, `ShortcutIconTypesAreValid`, `capture-pipeline-choice`, `form-factor-wide-and-narrow`, `screenshots-label-field`, `screenshots-member-absent`, `precache-glob-cost`, `apple-touch-icon-reuses-192`, `no-favicon-ico-fallback`, `no-1024-store-icon`, `emp-robots-txt-spa-fallback`, `no-launch-handler`, `MaskableSafeZone`, `emp-lighthouse-scores` → `done A5` (verifier re-checks the exact row list against the ledger's `A5` packet).
- [ ] **Step 7: Commits** (two): `feat(pwa): manifest identity, shortcuts, screenshots, capability members (A5)` and `feat(api): student widget endpoint for manifest widgets (A5)`.

---

### Task 6 (A6): Security headers, share target, file handlers

**Files:**
- Create: `web/public/_headers`
- Modify: `web/nginx.conf` (server block + the 3 `add_header` locations at :47, :54, :60 — repeat the security block with `always`)
- Modify: `web/worker/index.ts:52` — wrap the proxied response
- Modify: `web/vite/manifest.ts` (from A5) — `share_target`, `file_handlers`
- Modify: `web/src/sw.ts:73` denylist + file-scope share-target fetch listener
- Modify: `web/src/portals/student/screens/CorrectPaper.tsx` — mount consumer (Cache Storage, 10-min TTL) + `launchQueue.setConsumer`
- Test: `web/tests/unit/headers.test.ts` (new): parse `public/_headers`, assert the five header names and `camera=(self)`, `frame-ancestors 'none'`, `style-src 'self' 'unsafe-inline'`, no `preload`; `web/tests/unit/manifest.test.ts` (extend): `share_target.method === "POST"`, `enctype === "multipart/form-data"`, `params.files[0].name === "scan"`, `file_handlers[0].action === "/file-handler"`; `web/tests/unit/swShareTarget.test.ts` (new): extract the share-target handler into `web/src/sw/shareTarget.ts` exporting `handleShareTargetFetch(event)` and `SHARE_CACHE`/`SHARE_KEY`, unit-test it with a fake `FetchEvent`/`caches`; `web/tests/unit/sharedScanConsumer.test.ts` (new): `readSharedScan()` returns the File when `x-shared-at` is within 10 min, deletes the entry, returns null when stale.

**Exact header values:**
```
/*
  Strict-Transport-Security: max-age=31536000; includeSubDomains
  X-Content-Type-Options: nosniff
  Referrer-Policy: strict-origin-when-cross-origin
  Permissions-Policy: camera=(self), microphone=(), geolocation=(), interest-cohort=()
  Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' blob:; font-src 'self'; connect-src 'self'; worker-src 'self'; manifest-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'; object-src 'none'
```
Worker: `const res = await fetch(proxyRequest); const out = new Response(res.body, res); out.headers.set("X-Content-Type-Options","nosniff"); out.headers.set("Referrer-Policy","strict-origin-when-cross-origin"); return out;` — SSE (`text/event-stream`) must stream; verifier runs one correction on staging after deploy (manual, recorded in ledger evidence as "pending staging verification").
Manifest: `share_target: { action: "/share-target", method: "POST", enctype: "multipart/form-data", params: { files: [{ name: "scan", accept: ["image/*", "application/pdf"] }] } }`, `file_handlers: [{ action: "/file-handler", accept: { "image/*": [".png", ".jpg", ".jpeg"], "application/pdf": [".pdf"] } }]`.
SW: `denylist: [/^\/api/, /^\/share-target/]`; listener at file scope (outside `if (precacheEnabled)`), POST + pathname check, stash to cache `lemely-share-target` key `/__shared-scan` with headers `content-type`, `x-shared-name`, `x-shared-at`, `Response.redirect("/student/correct", 303)`. `/file-handler` route → redirect to `/student/correct` in `routes.tsx`; consumer reads `window.launchQueue` files via `chooseScan`.

**Skills:** `security-auditor`, `cloudflare-worker-dev`, `pwa-expert`, `caching-strategies`. Reviewer additionally: `security-auditor`.

- [ ] **Step 1: Re-read** `wrangler.jsonc` (`run_worker_first`, `assets.directory`), `worker/index.ts`, `sw.ts:60-100`, `CorrectPaper.tsx` `chooseScan` (~:295-300 in dossier; re-grep).
- [ ] **Step 2: Failing tests** (4 files).
- [ ] **Step 3: Run** → FAIL.
- [ ] **Step 4: Implement.**
- [ ] **Step 5: Run** → PASS; `npm run typecheck && npm run lint && npm run build`; `grep -o 'share-target' dist/sw.js | sort -u` shows the literal; `grep -c denylist dist/sw.js` ≥ 1; nginx: `docker build -t lemely-web-test web && docker run --rm -d -p 8089:80 lemely-web-test && curl -sI http://localhost:8089/ | grep -iE 'strict-transport|content-security|x-content-type|referrer|permissions'` (5 lines) and the same for `/sw.js` and `/assets/`; stop the container.
- [ ] **Step 6: Ledger:** sec-05-headers-missing, sec-06…sec-12, manifest-share-target, manifest-file-handlers → `done A6`; sec-03-mixed-content stays no-action.
- [ ] **Step 7: Commits** (three, separate risk): `feat(pwa): security headers for static assets, nginx and worker (A6)`, `feat(pwa): web share target into the marking flow (A6)`, `feat(pwa): file handlers into the marking flow (A6)`.

---

### Task 7 (A7): Service-worker lifecycle, install prompt, console hygiene

**Files:**
- Create: `web/src/lib/pwa/useServiceWorkerUpdate.ts` (wraps `virtual:pwa-register/react` `useRegisterSW`; exposes `{ needRefresh, applyUpdate }`; polls `registration.update()` on `visibilitychange` → visible and every 60 min)
- Create: `web/src/lib/pwa/useInstallPrompt.ts` (captures `beforeinstallprompt`, exposes `{ canInstall, promptInstall, isIos, isStandalone, dismissed, dismiss }`; `dismissed` persisted in `localStorage` key `lemely.installPromptDismissedAt`, 14-day cooldown)
- Create: `web/src/components/UpdateToast.tsx` (uses `useToast` — toast with action "Reload"), `web/src/components/InstallBanner.tsx` (student + teacher shells; iOS variant shows the Share → Add to Home Screen steps), `web/src/portals/settings/InstallSettings.tsx` (entry "Install Lemely" in settings nav)
- Modify: `web/src/sw.ts:95` — remove unconditional `self.skipWaiting()`; add `self.addEventListener("message", e => { if (e.data?.type === "SKIP_WAITING") self.skipWaiting() })`; keep `clientsClaim()`
- Modify: `web/vite.config.ts` — `injectRegister: false` if the plugin's own register script conflicts with `useRegisterSW` (read the plugin docs via Context7 before deciding; document in commit body)
- Modify: `web/src/components/route-error.tsx` (or the lazy boundary) — on `TypeError: Failed to fetch dynamically imported module` / `ChunkLoadError` reload once, guarded by `sessionStorage` key `lemely.chunkReload`
- Modify: `web/src/lib/hooks/useNotificationApi.ts:100` `usePushConfig` → `enabled: isAuthenticated` (from `AuthContext`) **only after** root-causing: run `npm run dev`, open Chrome DevTools Network, filter `push/config`, read the Initiator column, record the initiator file:line in the commit body. If the initiator is the service worker's push bridge (`registerPushClientBridge` at `main.tsx:8`), gate the bridge instead.
- Modify: `web/src/main.tsx` — mount `UpdateToast`
- Test: `web/tests/unit/serviceWorkerUpdate.test.ts` (mock `virtual:pwa-register/react`; `needRefresh` true → toast rendered; `applyUpdate` posts `SKIP_WAITING` and reloads); `web/tests/unit/installPrompt.test.ts` (fires `beforeinstallprompt` → `canInstall`; standalone `matchMedia` → hidden; iOS UA → `isIos`; dismissal cooldown); `web/tests/unit/chunkReload.test.ts` (reloads once, not twice); `web/tests/unit/swSource.test.ts` (new): `sw.ts` source has no `self.skipWaiting()` outside a `message` listener; `web/e2e/console-errors.ts` helper already exists — add an assertion in `_smoke.spec.ts` that a cold `/login` load records zero failed requests.

**Skills:** `pwa-expert`, `caching-strategies`, `error-handling-patterns`.

- [ ] **Step 1: Re-read** `sw.ts:90-110`, `main.tsx`, `toast.tsx` `useToast` API, `AuthContext.tsx` session read.
- [ ] **Step 2: Failing tests.**
- [ ] **Step 3: Run** → FAIL.
- [ ] **Step 4: Implement**; root-cause the 401 first and paste the initiator in the commit body.
- [ ] **Step 5: Run** → PASS; `npm run typecheck && npm run lint && npm run build`; `npx playwright test e2e/_smoke.spec.ts` if the backend is up (else record "e2e deferred to CI").
- [ ] **Step 6: Ledger:** silent-update-swap, no-periodic-update-check, no-install-affordance, emp-beforeinstallprompt-not-observed, silent-401-push-config-every-load, emp-console-401, sw-registers-on-staging-but-no-fetch-handling → `done A7`; sw-push-listener-real stays no-action.
- [ ] **Step 7: Commits:** `feat(pwa): gated service-worker updates with reload prompt (A7)`, `feat(pwa): install prompt and iOS install sheet (A7)`, `fix(web): stop unauthenticated push-config requests on cold load (A7)`.

---

### Task 8 (A8): CI guards, bundle budget, navigation retry, DESIGN.md §15

**Files:**
- Create: `web/scripts/check-native-invariants.mjs` — exits 1 on any failed assertion, prints each check; assertions: `index.html` viewport contains `viewport-fit=cover` and `interactive-widget=resizes-content`; `index.css` contains `-webkit-tap-highlight-color: transparent`, `overscroll-behavior-y: contain` in the `html, body` rule, `touch-action: manipulation` inside `@media (pointer: coarse)`, `overscroll-behavior: contain` on `.lm-scroll`, `--fs-field`, ≥1 `env(safe-area-inset-`, ≥1 `@media (display-mode: standalone)`; `input.tsx`/`textarea.tsx` contain no `text-body-md`; no `min-h-screen` without `min-h-dvh` on the same line (excluding `<aside`); every `components/ui/*.tsx` with `onClick` and `hover:` also has `active:`; `sw.ts` has no `self.skipWaiting()` outside a `message` listener; **deferred to Phase B (assert only when the flag `--phase-b` is passed):** zero `fallback={<RouteFallback` in `routes.tsx`, no `document.body.style.overflow = "hidden"`.
- Create: `web/scripts/check-bundle-budget.mjs` — after `vite build`, gzip each `dist/assets/*.js`, print top 5, fail if any chunk > `BUDGET_KB` (default 200; Phase B lowers to 150), read `process.env.BUNDLE_BUDGET_KB` override.
- Modify: `web/package.json` scripts: `"check:native": "node scripts/check-native-invariants.mjs"`, `"check:bundle": "node scripts/check-bundle-budget.mjs"`, and `"lint": "oxlint && npm run check:native"`; `"build"` unchanged; add `"postbuild": "npm run check:bundle"`.
- Modify: `.github/workflows/*.yml` web job — ensure `npm run lint` and `npm run build` run (grep first; add `npm run check:bundle` if `postbuild` is not honoured by the CI invocation).
- Modify: `web/scripts/audit.mjs` — wrap `page.goto` in a `gotoWithRetry(page, url, attempts = 3)` helper (also used by Lighthouse launch), exported from `web/scripts/serve_guard.mjs` or a new `web/scripts/nav_retry.mjs`.
- Modify: `DESIGN.md` — new §15 "Device envelope": install/update lifecycle (gated skipWaiting, reload prompt), offline behaviour (PRECACHE_HOSTS rule, OfflineState classification), safe areas (`viewport-fit=cover`, standalone-gated insets, default status bar), orientation (`any`; landscape overlay lands in Phase B), gestures (disambiguation rule `|dx| > 10 && |dx| > 2*|dy|`, list of gestures Phase B ships), capability register (share target, file handlers, badging, haptics one call site, wake lock), and the guard script as the enforcement.
- Test: `web/tests/unit/checkNativeInvariants.test.ts` (run the script against fixture strings via an exported `runChecks({ indexHtml, indexCss, files })` function; one failing fixture per assertion); `web/tests/unit/bundleBudget.test.ts` (exported `overBudget(entries, budgetKb)`).

**Skills:** `performance-profiling`, `github-actions-pipeline-builder`, `technical-writer`, `writing-guidelines`.

- [ ] **Step 1: Re-read** `audit.mjs` navigation sites, CI workflow web job, `package.json` scripts.
- [ ] **Step 2: Failing tests.**
- [ ] **Step 3: Run** → FAIL.
- [ ] **Step 4: Implement**; run `npm run lint` (now includes the guard) and `npm run build` (runs the budget).
- [ ] **Step 5: Run** → PASS; paste the budget's top-5 output in the commit body (`CorrectPaper-*.js` gzip size recorded for Phase B).
- [ ] **Step 6: Ledger:** emp-env-navigation-flakiness, x-completeness-perf-floor-student-only → `done A8` (perf-floor extension itself is C4; A8 evidence = "guard scripts + retry wrapper").
- [ ] **Step 7: Commit** `ci(web): native-invariant and bundle-budget guards, navigation retry, DESIGN.md §15 (A8)`.

---

### Task 9: Phase close — review, verification, PR

- [ ] **Step 1: Opus review of the whole branch diff** (`code-reviewer`, skills `code-review-checklist`, `security-auditor`): `git diff develop...HEAD`. Fix critical/high in follow-up commits per packet scope.
- [ ] **Step 2: `ai-slop-cleaner` pass** on the diff (comments that restate code, dead flags, placeholder copy).
- [ ] **Step 3: Verifier** (`verifier`, opus): re-run every Step 5 command above, confirm ledger has no `pending` row with `phase = A`, fill `done <sha>` per row.
- [ ] **Step 4: `merge-readiness` skill report**; `superpowers:finishing-a-development-branch`.
- [ ] **Step 5: Push and open PR** into `develop`:
```bash
git push -u origin feat/native-and-pwa
gh pr create --base develop --title "feat: native-feel mechanics, PWA completeness, security headers (audit remediation phase A)" --body-file /tmp/claude-1000/-home-sico-Code-Lemely/459a483f-eff5-4286-a616-5593319861ac/scratchpad/pr-a.md
```
PR body: packet list A1–A8 with ledger row counts, the manual staging checklist (headers `curl -sI`, Android share sheet, camera under CSP, SSE run through the worker, iOS install sheet), and the session URL as the last line.
- [ ] **Step 6: Hand off** — user merges; Phase B plan is written against merged develop.

---

## Self-review (done while writing)

- Spec coverage: A1–A8 packets all present; every Phase A ledger id named in a task's Step 6.
- Placeholders: none — each step names files, values, tests and commands. Code bodies intentionally absent (memory `delegate-by-model`): implementers author code, opus reviews.
- Type consistency: `manifest` exported from `web/vite/manifest.ts` (A5) is what A6 extends; `readSharedScan` (A6) and `chooseScan` (existing) are the only cross-task names; `runChecks`/`overBudget` (A8) are test seams only.
- Deferred by design: `--phase-b` assertions in the guard script; bundle budget 200 → 150 in Phase B.
