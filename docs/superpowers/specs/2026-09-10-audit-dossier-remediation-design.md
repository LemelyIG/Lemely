# Audit Dossier Remediation — Design Spec

Date: 2026-09-10 · Status: draft for review · Approved plan-mode design copied verbatim; ledger lives beside it.


Source: artifact `https://claude.ai/code/artifact/37885ce6-4f48-4b00-a763-38d555c0a17e`
("Lemely Audit Dossier", 9 Sep 2026). Local copy of the HTML:
`~/.claude/projects/-home-sico-Code-Lemely/459a483f-eff5-4286-a616-5593319861ac/tool-results/artifact-37885ce6-1788972132-84eb.html`
(301 `<article class="f …" id="…">` cards + 12 tells + roadmap sections). Finding
ids in this plan are the article `id` attributes.

## Context

Three audits (native feel 66, PWA checklist 89, production-vs-design-canvas 146)
were run against worktree `.claude/worktrees/ui-audit-pwa`, which is **227
commits behind `develop`**. Verified today on develop that the core mechanics
still hold (0 hits for `tap-highlight`, `safe-area-inset`, `touch-action`,
`overscroll`, `viewTransition`, `ScrollRestoration`, `dvh`, `fs-field`,
`enterKeyHint`, `vibrate`; no `public/_headers`; manifest lacks `id`,
`shortcuts`, `screenshots`, `share_target`). Two dossier items are already fixed
on develop (`ToastProvider` mounted at `web/src/main.tsx:74`; parent
`Notifications.tsx` exists). Every packet therefore starts with a re-verify
step.

User decisions (this session):

- Scope = **all 301**, overriding the dossier's own skips where feasible and
  safe.
- Exploration-only artboards: build **daily quests, achievement badges, dark
  mode**; skip marketplace/bookings/checkout, live video, video library,
  QR/face check-in, fraud toggles, WhatsApp, geo-IP, BusinessStats.
- Fabricated-metric class: build **predicted class average** only (honest
  derivation); skip hours-saved KPI, cover stat trio, italic hero,
  grade-guarantee headline, hype copy.
- "Harmful" overrides: implement **red-pen wrong-answer register** (narrowly
  scoped) and **long-press context menus**; skip black-translucent status bar,
  flashcard rollback, haptic-per-grade, popover history entries, portrait lock.
- Manifest members: add `prefer_related_applications`, `display_override`,
  `categories`, `widgets`, `note_taking`, `edge_side_panel`, `scope_extensions`,
  `handle_links`, `protocol_handlers`; skip `iarc_rating_id`,
  `related_applications`, periodicsync, widening `PRECACHE_HOSTS`.
- XL backend gaps: build backlog #13–#19; skip #20 national benchmark.
- Auth-funnel and admin-portal audit lanes: skip (new audits, not fixes).
  Forms migration: include.
- Orchestration: **switch main session to sonnet, run OMC ralph per phase**;
  sonnet implementers, opus reviewers.
- Delivery: **4 branches, one PR each**, into `develop`.
- BottomNav tabs: student `Overview · Correct · Classes · Profile · More`;
  teacher `Overview · Grading · Review · Classes · More`.
- Never run the full pytest suite locally (memory `no-full-test-suite-locally`).

## Orchestration protocol

1. Main session: `/model sonnet`, then `/oh-my-claudecode:ralph` with this plan
   path + phase letter. Inside the loop the sonnet session invokes
   `Skill(orchestrator)` (user skill `~/.claude/skills/orchestrator`) as the
   coordinator: it decomposes the phase into packets, picks the specialist
   skills per packet from the table below, dispatches `executor`/`code-reviewer`/
   `verifier` agents, synthesises results into the ledger, and — when a packet
   needs a capability no listed skill covers — invokes `Skill(skill-coach)` to
   create it before implementing (orchestrator's gap rule). Ralph supplies
   persistence; orchestrator supplies decomposition/delegation/synthesis. Ralph
   exits a phase only when the ledger has zero `pending` rows for it and
   verifier evidence is recorded.
2. Branch per phase from fresh `develop` (`superpowers:using-git-worktrees`).
3. Per packet:
   a. Re-verify on develop (tokensave MCP / `haiku` scout). Already fixed →
      ledger `already-fixed`, stop.
   b. `executor` model=sonnet implements. Brief lists: files owned, behaviours,
      test file names, skills to invoke (below), "run only `<named tests>`,
      never the full suite".
   c. `code-reviewer` model=opus adversarial review of the combined diff
      (`superpowers:requesting-code-review`, skill `code-review-checklist`).
   d. sonnet fixes (`superpowers:receiving-code-review`); loop c–d until no
      critical/high.
   e. `verifier` model=opus runs the packet's verification commands
      (`superpowers:verification-before-completion`), writes evidence to the
      ledger row.
   Up to 3 packets in parallel when file ownership is disjoint
   (`superpowers:dispatching-parallel-agents`).
4. Commits: `git commit -S`, conventional scopes (`feat(web):`, `fix(pwa):`,
   `feat(api):`, `feat(db):`, `docs(design):`), `pre-commit run --all-files`
   first, one commit per packet, trailer
   `Claude-Session: https://claude.ai/code/session_01CxbrmXri2Fm1p2KFgjL3rr`.
5. Phase end: `superpowers:finishing-a-development-branch` → push + PR to
   `develop` (body ends with the session URL), `merge-readiness` skill report.
   User merges. Next phase branches from merged develop.
6. Local test commands (only these):
   - web: `npm run typecheck && npm run lint && npx vitest run <touched files> && npm run build`
   - backend: `pytest --no-cov tests/<touched file>` ; `ruff check`
   - CI runs the full suite on the PR.
7. Ledger `docs/superpowers/specs/2026-09-10-audit-dossier-remediation-ledger.md`:
   301 rows `id | lane | phase | packet | status | evidence`; status ∈
   `pending` / `done <sha>` / `already-fixed` / `skipped <reason>` /
   `no-action <reason>`. Generated mechanically from the artifact HTML, then
   hand-assigned per this plan. Ralph reads it as its task list.
8. Post-merge manual checks (user): `curl -sI https://staging.lemelyig.com/`
   headers; Android share-sheet → Lemely opens `/student/correct` with photo;
   iOS installed splash; standalone safe-area on a notched device; camera flow
   under CSP.

## Skills per implementer (invoke via `Skill` tool at packet start)

Process, every packet: `superpowers:test-driven-development`,
`superpowers:verification-before-completion`, `vitest-testing-patterns` (web
unit), `react-best-practices` (any `.tsx`), `checklist-discipline`.

| Packet family | Domain skills |
|---|---|
| CSS/HTML mechanics, safe-area, standalone, dvh (A1, A2) | `pwa-expert`, `mobile-ux-optimizer`, `native-app-designer` |
| a11y tokens, contrast, pressed states (A3, C3 red-pen) | `color-contrast-auditor`, `design-accessibility-auditor`, `web-design-guidelines` |
| Manifest, icons, screenshots, robots (A5) | `pwa-expert` |
| Headers, CSP, worker, nginx (A6) | `security-auditor`, `cloudflare-worker-dev` |
| share_target, file_handlers, SW lifecycle, install/update prompts (A6, A7) | `pwa-expert`, `caching-strategies` |
| Guards + bundle budget (A8, B6 prefetch) | `performance-profiling`, `react-performance-optimizer`, `github-actions-pipeline-builder` |
| Pre-mount shell, skeletons, splashes (B1) | `pwa-expert`, `react-performance-optimizer` |
| History trap, scroll lock, ScrollRestoration, back control, View Transitions, exits (B2) | `react-view-transitions` (project-vendored), `mobile-ux-optimizer`, `react-best-practices` |
| BottomNav, SidebarNav retrofit, bottom CTA bar (B3) | `native-app-designer`, `mobile-ux-optimizer`, `ux-heuristics` |
| Gestures, long-press (B4) | `mobile-ux-optimizer`, `native-app-designer`, `error-handling-patterns` |
| Optimistic grading, haptics, Wake Lock, Web Share, Badging (B5) | `error-handling-patterns`, `pwa-expert` |
| Camera scanner quality (B5) | `computer-vision-pipeline`, `performance-profiling` |
| Offline queue, Background Sync, persisted cache, idempotency (B6) | `pwa-expert`, `caching-strategies`, `rest-api-design`, `error-handling-patterns` |
| Review-queue pagination backend (B6) | `rest-api-design`, `postgresql-optimization` |
| e2e native-feel spec (B7) | `playwright-e2e-tester`, `webapp-testing` |
| Kit primitives + table/form migrations (C1, C2) | `composition-patterns`, `ui-refactor`, `form-validation-architect`, `design-system` |
| Screen-level UI (C3) | `ui-refactor`, `ux-heuristics`, `web-design-guidelines`, `impeccable` (designer audit/normalize/polish on touched screens) |
| Print, perf floor, reduced-motion test, copy gate (C4) | `playwright-screenshot-inspector`, `vitest-testing-patterns` |
| Dark mode (C5) | `dark-mode-design-expert`, `color-contrast-auditor`, `design-system`, `typography-expert` |
| Gamification tables + quests (D1) | `database-design-patterns`, `postgresql-optimization`, `rest-api-design` |
| DTO gaps (D2) | `rest-api-design`, `react-best-practices` |
| Batch ingest, crops, transcript, marking points (D3) | `database-design-patterns`, `rest-api-design`, `background-job-orchestrator`, `error-handling-patterns` |
| Gemini-backed remediation quiz, lesson plan (D3) | `prompt-engineer`, `llm-streaming-response-handler`, `rest-api-design` |
| DESIGN.md / docs edits (all phases) | `technical-writer`, `writing-guidelines` |
| Phase-end cleanup | `ai-slop-cleaner`, `merge-readiness` |
| Reviewers (opus) | `code-review-checklist`, `security-auditor` (A6, D3), `design-accessibility-auditor` (C) |

Skill invocation is mandatory in each brief: "Invoke `Skill(<name>)` before
writing code; follow it; do not summarise it back."

## Phase A — `feat/native-and-pwa` (87 ledger rows, 8 packets)

**A1 Mechanics** — `web/index.html:15` viewport `viewport-fit=cover,
interactive-widget=resizes-content`; `web/src/index.css:561` `html,body`
`-webkit-tap-highlight-color: transparent; overscroll-behavior-y: contain`;
`touch-action: manipulation` in the `@media (pointer: coarse)` block (~:615);
`.lm-scroll` (~:1059) + `components/ui/table.tsx:36` overscroll contain;
`.lm-nav-chrome` (`-webkit-touch-callout:none; user-select:none`) on drawer
panel, `NavDrawerTrigger`, `nav-shells.tsx:77`, 4 top bars (student:526,
teacher:339, admin:312, marketing:73); `--fs-field: 16px` (DESIGN.md §4.2
first, then token, `text-field` utility, `input.tsx:110`, `textarea.tsx:113`;
check `NotificationSettings.tsx` `w-36` fields and `JoinWithCode.tsx` mono
field); `min-h-screen min-h-dvh` at all 11 `min-h-screen` sites (leave
desktop-only sidebars); `@media (display-mode: standalone)` `.lm-app-header
{padding-top: env(safe-area-inset-top)}` on 4 headers; `padding-bottom:
env(safe-area-inset-bottom)` on `nav-shells.tsx:77` and the toast rail
(`toast.tsx:110`).
Findings: tap-highlight-color, double-tap-zoom-unneutralized,
overscroll-behavior-absent, no-overscroll-behavior, touch-callout-select-on-chrome,
kb-1, input-font-14px-ios-zoom, min-h-screen-no-dvh-fallback,
no-safe-area-insets, safe-area-viewport-cover, no-standalone-media-query, kb-6,
status-bar-style-default-mismatch (resolved: keep `default` + inset; document).

**A2 Input attributes** — `ParentLogin.tsx` PhoneStep onto shared
`Input`/`Select`; `enterKeyHint` go/go/send on Login, JoinWithCode,
ParentLogin; `SignupDetails.tsx` Name `autoCapitalize="words"
autoCorrect="off"`; `Login.tsx:112` `LINK_CLASS` → `inline-flex min-h-11
items-center …`. Findings: kb-2, kb-3, kb-4, login-links-under-44px-tap-target.

**A3 Pressed states + tokens** — `active:` on `question-row.tsx`,
`confidence-indicator.tsx`, `role-switcher.tsx`, `error-state.tsx`;
`CameraCapture.tsx:310` `text-accent` → `text-accent-ink`; `nav-shells.tsx:94`
`text-white` → `text-accent-on`, fix :88/:111; `ReviewItem.tsx:445-453` →
`<Kbd>`; `processing-state.tsx` `StageProgressBar` → `<ProgressBar>`; RTL leaks
`ml-auto`→`ms-auto`, `text-left`→`text-start` (4 components); `--info` hue moved
off subject pastels + assertion in `test_design_tokens.py`; drop
`@fontsource/instrument-serif`, `@fontsource-variable/work-sans`, relock, fix
`web/README.md:13`. Findings: no-active-state-question-row-confidence,
role-switcher-no-active-state, x-a11y-prod-accent-small-text-below-own-floor,
x-dark-nav-badge-raw-white, x-completeness-kbd-primitive-bypassed,
x-motion-width-transition-gate-violation, x-completeness-rtl-unwireable,
x-tokens-sky-info-subject-collision-persists, x-type-dead-font-packages-stale-docs.

**A4 Offline/perf small** — `kind={err instanceof ApiError && err.status === 0
? "offline" : "error"}` at Overview/Subject/Friends/Notifications/Parents error
branches; shared query-error renderer routes `TypeError`/status 0 →
`OfflineState`; `CorrectPaper.tsx:241` default `camera` when `(pointer:
coarse)`; `Grading.tsx:184` `decoding="async"`. Findings: offline-2, offline-4,
x-completeness-offline-state-dead, correct-paper-defaults-to-file-not-camera,
grading-thumbnail-no-decoding-async.

**A5 Manifest + assets** — one `web/vite.config.ts` manifest edit: `id:"/"`,
`dir:"ltr"`, `launch_handler:{client_mode:"navigate-existing"}`, `shortcuts`
×3 (+ generated 96px icons via `generate_icons.mjs`), `screenshots` (copy
`scripts/manifest_screenshots.mjs` + `public/screenshots/*.jpg` from
`.claude/worktrees/ui-audit-pwa/web`, add `screenshots:manifest` npm script),
`orientation:"any"`, `prefer_related_applications:false`,
`display_override:["standalone","minimal-ui"]`,
`categories:["education","productivity"]`, `handle_links:"preferred"`,
`protocol_handlers:[{protocol:"web+lemely",url:"/join/%s"}]` (+ `/join/:code`
accepts the `web+lemely://` payload), `edge_side_panel:{preferred_width:400}`,
`scope_extensions:[{origin:"https://staging.lemelyig.com"}]` +
`public/.well-known/web-app-origin-association`,
`note_taking:{new_note_url:"/student/practice"}`, `widgets` (one Adaptive Card
template `public/widgets/streak.json` + `GET /api/student/widget` returning
streak + next session, behind `VITE_ENABLE_WIDGETS`); merge `screenshots/**`,
`widgets/**`, store icon into the existing `globIgnores` array (never a second
key). Icons: `apple-touch-icon.png` 180 in `ICONS`, `favicon.ico` from
`brand/mark-favicon.svg` (sharp → ico, no new dep if sharp suffices),
`store-icon-1024.png` (no alpha variant). `tests/unit/brandTokens.test.ts`
asserting `MASKABLE_SCALE ≤ 0.8/Math.SQRT2`, delete the false comment at
`generate_icons.mjs:82-86`. `public/robots.txt`: allow `/`, marketing routes;
disallow `/api`, `/student`, `/teacher`, `/parent`, `/admin`, `/settings`,
`/join`. Findings: all `manifest-*`, `Id`, `Screenshots`, `Orientation`,
`manifest-orientation`, `Screenshot*`, `ShortcutIcon*`, `capture-pipeline-choice`,
`form-factor-wide-and-narrow`, `screenshots-*`, `precache-glob-cost`,
`apple-touch-icon-reuses-192`, `no-favicon-ico-fallback`, `no-1024-store-icon`,
`emp-robots-txt-spa-fallback`, `no-launch-handler`, `MaskableSafeZone`
(comment fix), `emp-lighthouse-scores` (seo delta).

**A6 Delivery + security** — `web/public/_headers` (`/*`: HSTS
`max-age=31536000; includeSubDomains`, no preload; nosniff;
`Referrer-Policy: strict-origin-when-cross-origin`; `Permissions-Policy:
camera=(self), microphone=(), geolocation=(), interest-cohort=()`; CSP
`default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline';
img-src 'self' data: blob:; media-src 'self' blob:; font-src 'self';
connect-src 'self'; worker-src 'self'; manifest-src 'self'; base-uri 'none';
form-action 'self'; frame-ancestors 'none'; object-src 'none'`); same block in
`web/nginx.conf` with `always` repeated in the 3 `add_header` locations,
verified by `curl -I` against a local container; `worker/index.ts` wraps
`/api/*` responses (`new Response(res.body, res)` + nosniff + Referrer-Policy),
SSE correction run verified on staging after deploy; `share_target` (manifest
POST multipart `scan`; `sw.ts` denylist `/^\/share-target/`; file-scope fetch
handler stashing to Cache `lemely-share-target`; `CorrectPaper.tsx` mount
consumer with 10-min TTL feeding `chooseScan`); `file_handlers` (manifest +
`window.launchQueue.setConsumer` in CorrectPaper). Findings: sec-05…sec-12,
manifest-share-target, manifest-file-handlers, sec-03 (no change).

**A7 SW lifecycle** — `virtual:pwa-register` `useRegisterSW` with
`onNeedRefresh` → toast "Update ready · Reload"; `sw.ts:95` `skipWaiting()`
only on `SKIP_WAITING` message; `visibilitychange` + 60-min `update()` poll;
dynamic-import failure of a route chunk → one guarded `location.reload()`;
`useInstallPrompt` (captures `beforeinstallprompt`, iOS instructional sheet
when `navigator.standalone === false` and iOS UA), entry in student/teacher
settings + dismissible banner, hidden under `(display-mode: standalone)`; 401
`/api/notifications/push/config` root-caused via Network initiator, then gate
`usePushConfig` on auth or make the endpoint anonymous-safe — cold load must
log zero failed requests. Findings: silent-update-swap,
no-periodic-update-check, no-install-affordance,
emp-beforeinstallprompt-not-observed, silent-401-push-config-every-load,
emp-console-401, sw-registers-on-staging-but-no-fetch-handling (documented),
sw-push-listener-real (no change).

**A8 Guards + docs** — `web/scripts/check-native-invariants.mjs` (viewport
meta, tap-highlight, overscroll, touch-action, `.lm-scroll`, `--fs-field`, no
`text-body-md` on native inputs, safe-area + standalone present, zero
`fallback={<RouteFallback` after Phase B, `min-h-dvh` pairing, hover⇒active in
`components/ui`, no `document.body.style.overflow = "hidden"` after Phase B,
no unconditional `skipWaiting`); `check-bundle-budget.mjs` (gzip every
`dist/assets/*.js`, print top 5, ceiling 200KB now → 150KB in Phase B); both in
`npm run lint` and CI; Lighthouse/Playwright navigation retry wrapper (2–3
attempts) in `scripts/audit.mjs`; DESIGN.md §15 "Device envelope" (install,
update, offline, safe areas, standalone, orientation, gestures, capability).
Findings: emp-env-navigation-flakiness, x-completeness-perf-floor-student-only
(part), tell T5 (motion compliance guard), dossier "How to measure it".

## Phase B — `feat/native-structural-capability` (42 ledger rows, 7 packets)

**B1 Launch + loading** — inline pre-mount shell in `index.html` (top-bar
silhouette, colour from `vite/themeColor.ts` build-time `--paper`), removed by a
2-line script once `#root` has children; route `handle.skeleton` selects
`PageHeaderSkeleton`/`CardGridSkeleton`/`ListSkeleton` from
`loading-shapes.tsx` at the 14 `routes.tsx` sites + 3 portal Outlets; student
shell (sidebar + header) renders on cold load instead of blanking; `SPLASHES`
array in `scripts/generate_icons.mjs` (same sharp pipeline, `MARK` + `PAPER`,
exhaustive iPhone/iPad classes) + `apple-touch-startup-image` links with media
queries. Findings: route-fallback-not-a-skeleton, no-pre-mount-shell, tell T2,
T2 (article: cold start no pre-mount shell), student-shell-blanks-on-cold-load,
no-ios-splash-screens,
practice-create-spinner-acceptable-but-note (Button `loading` prop).

**B2 Navigation model** — `Modal`/`NavDrawer`: push
`navigate(location, {state:{...state, lemelyDialog:true}})` on open when
`dismissible !== false`, `popstate` closes, programmatic `onClose` unwinds;
`ConfirmModal` re-pushes on popstate without `onCancel`; `Popover` untouched.
Scroll lock → saved `scrollY` + `position:fixed` (shared helper used by both).
`<ScrollRestoration/>` in `main.tsx` (POP keeps, PUSH/REPLACE resets to 0).
`RequireAuth.tsx:81` `state={{from}}`, `Login.tsx:131` honours it after
validating against `portalPathForRole`. `BackControl` component (`navigate(-1)`
or fallback route when `history.state?.idx === 0`) in student sub-screen
headers. `.lm-screen` moved to Outlet wrapper keyed by `location.key`; parent,
admin, auth, marketing, misc, settings get an entrance. View Transitions:
`viewTransition` on portal-internal `<Link>`/`navigate`, `data-direction` from
`useNavigationType`, `::view-transition-old/new(root)` translateX ±, `.lm-screen`
suppressed on VT-driven mounts, PaperResult excluded; reduced motion
`::view-transition-group(*) {animation:none !important}`. Exits: `isClosing`
phase + `lm-out` keyframe on `--ease-in-soft`/`--dur-fast`, unmount on
`animationend`, synchronous when `prefersReducedMotion()`; scroll-lock/focus-trap
keyed on `open || isClosing`. DESIGN.md §9 exits clause + §9.4 explicit VT rule.
Findings: nav-1, T1 (transitions), tell T3, T3 (article: no exit transition),
tell T4, T4 (article: `.lm-screen` fires on state swaps, not navigation),
nav-3, nav-4, nav-6, modal-drawer-scroll-lock-fragile,
gesture-standalone-pwa-no-back-replacement.

**B3 Reach** — bottom action bar with "Correct a paper" below `min-[820px]`
(+ `main` bottom padding); `BottomNav` real tabs (student Overview · Correct ·
Classes · Profile · More; teacher Overview · Grading · Review · Classes · More;
More opens `NavDrawer`), `nav-drawer.tsx:32-40` comment updated with the
ranking decision; per-tab scroll + state memory keyed by tab root (nav-5);
`NavShellItem` gains `NavLink` semantics, 3 portal sidebars retrofit onto
`SidebarNav`, shared `SIDEBAR_WIDTH = 252` / `SIDEBAR_BREAKPOINT` constants;
edge-swipe-back (standalone only, 24px left edge, `|dx|>10 && |dx|>2|dy|`).
Findings: TT-1, nav-2, nav-5, x-navshells-dead-code,
x-ia-navshells-unused-abstraction, x-ia-sidebar-cross-portal-mismatch.

**B4 Gestures** — `lib/gestures/useDragGesture.ts` (pointer capture, refs
off render path, commit when `|dx|>10 && |dx|>2|dy|`, imperative transform,
spring back on `--dur-base`/`--ease-spring`); FlashcardReview swipe up/right
reveal (~60px), left/right grade again/good (~80px), buttons + keyboard kept;
NavDrawer drag-dismiss, RTL-aware via `--lm-dir`; `usePullToRefresh` (sets
`overscroll-behavior-y: contain` on its container) on Notifications,
Announcements, Overview; QuizTaker swipe Previous/Next excluding `role=radio`,
`textarea`, `input`, flushing the 600ms autosave before page turn, disabled in
timed mode's last 60s; `useLongPress` (500ms, cancels on move >10px) opening
existing `Popover`: `QuestionRow` (Practice this topic · Share), notification
row (Mark read), flashcard deck row (Rename · Delete if API exists). Visible
buttons stay. Findings: gesture-flashcard-no-swipe, tell T8,
gesture-navdrawer-no-swipe-dismiss, gesture-no-pull-to-refresh,
gesture-quiztaker-no-swipe-honest-tradeoff, gesture-no-long-press-and-thats-fine
(override).

**B5 Feedback + capability** — optimistic flashcard advance: `onMutate`
advances, no rollback, react-query retry with backoff, non-blocking banner
naming the failed card with Retry, `results` includes only settled grades;
`lib/haptics.ts` (`navigator.vibrate` feature-detected) on
`confirm-modal.tsx:87` confirm + flashcard session end; Wake Lock in
`CameraCapture` multi-shot, re-acquire on `visibilitychange`; Web Share on
`PaperResult` (share URL + summary; download fallback); Badging
`navigator.setAppBadge` from `useNotificationCounts`, cleared on inbox open, +
`badge` count in the push payload (backend `push` sender); `@media
(orientation: landscape)` guidance overlay in CameraCapture; scanner quality:
frame-stability auto-capture (motion delta over 3 frames), perspective
correction (document quad detect — sonnet chooses hand-rolled Sobel/contour vs
lazy-loaded `opencv.js`; reviewer checks bundle budget), torch via
`track.getCapabilities().torch` + `applyConstraints` (button only when
supported); multi-file picker (`file-drop.tsx` `multiple`, `assemblePagesToPdf`
extracted to `lib/pdf/assemblePages.ts`). Findings:
no-optimistic-flashcard-grading, tell T10, zero-haptics-anywhere,
wake-lock-unused-during-multi-shot-capture, web-share-unused-on-result-screen,
badging-api-unused-despite-ready-data, no-orientation-policy,
camera-scanner-basics-only, file-picker-single-file-no-multiple.

**B6 Offline + perf** — backend: `Idempotency-Key` header on
`POST /student/uploads` (`uploadRun.ts` race documented; repo dedupes by key
per user, 24h); web: IndexedDB queue (`lib/offline/uploadQueue.ts`) for
captured pages + pending upload, `BackgroundSyncPlugin` inside the
`precacheEnabled` block, `online` listener + next-launch retry fallback,
`OfflineState` + queued banner in CorrectPaper; persisted query cache
(`@tanstack/react-query-persist-client` + IDB persister, allowlist by field,
exclude `["student","overview"]`, `["student","subject",*]` grade/pct/trend);
prefetch-on-intent (`onPointerEnter`/`onTouchStart`/`focus` on the CTA →
`import()` of the CorrectPaper chunk) + `pdf-lib` dynamic import, budget →
150KB; review-queue pagination: `review_repo.py:227` LIMIT + cursor,
`useTeacherApi.ts:337` `limit`/`cursor`, `Review.tsx` load-more, no
virtualization. Findings: offline-1, offline-3,
sw-background-sync-upload-candidate, correct-paper-chunk-no-prefetch,
review-queue-unbounded-unvirtualized, sw-offline-production-trace,
emp-offline-staging-by-design (documented), tell T12.

**B7 Tests** — `web/e2e/native-feel.spec.ts` with `devices['iPhone 15']` and
`devices['Pixel 7']`: input font ≥16px on /login /signup /reset /join
/settings/notifications; tap targets ≥44 on same + student overview; chrome
suppression computed styles; safe-area rule count > 0 + meta string; back
dismisses drawer and modal with URL unchanged, ConfirmModal survives back;
scroll restoration; deep-link return; reduced-motion durations ≤10ms and
modal unmount within one frame; zero failed requests on cold load. Lighthouse
against a production-hostname build asserting installability. Findings:
dossier "How to measure it", x-motion-reduced-motion-e2e-narrow-scope (e2e half).

## Phase C — `feat/ui-kit-and-dark-mode` (36 ledger rows, 5 packets)

**C1 Kit primitives** — `components/ui/brand-lockup.tsx` (mark + wordmark,
`aria-hidden` + text contract) replacing the 5 copies; `section-head.tsx`
(Eyebrow + Display + kicker + action slot), migrate the highest-traffic
screens; `subject-glyph.tsx` (pastel tile + Phosphor glyph) + optional leading
icon on `SubjectTag`; `progress-ring.tsx` extracted from `Grading.tsx:387-409`
(API mirrors `progress-bar.tsx`: value, tone, label); `<Th>`/`<Td>` operate
cell padding primitive. Findings: x-brandlockup-duplicated-5x,
x-sectionhead-no-equivalent, x-motifs-subjectglyph-tile-missing,
brand-subject-glyph-vs-subject-tag, x-progressring-inline-duplication-risk,
x-motifs-progress-ring-not-systematized,
x-motion-progress-ring-no-production-equivalent,
x-density-operate-row-rhythm-matches-but-uncodified.

**C2 Migrations** — 8 teacher tables (Review, ClassRoster first, then
ClassDetail, StudentDetail, AtRiskList, ClassAnalytics, Classes, MarkSchemes) →
`Table/THead/TBody/TR/TH/TD`, sticky default, explicit `sticky={false}`,
`ClassAnalytics.tsx:241` header surface; 29 raw `<input>` sites → kit
`Input/Select/Textarea` starting with `teacher/Classes.tsx`; hand-rolled-input
assertion in `scripts/audit.mjs`. Findings:
x-completeness-teacher-tables-bypass-table-primitive,
x-completeness-forms-dimension-unaudited.

**C3 Screen-level** — PaperResult All/Lost/Flagged filter (client-side from
`markState`/`confidenceTier`); red-pen register on the per-question wrong-answer
explanation only (`--mark-wrong` ink at stronger weight + left rule; no red
backgrounds, no Caveat; PRODUCT.md:118 caveat recorded in DESIGN.md §3.6);
streak chip beside greeting on Overview below 640px; `SessionRow` icon by
`activityType`; StudyPlanWeek countdown header (target grade + session date
from `SubjectsStep`, reuse `daysUntil`/`formatCountdown` from
Announcements.tsx); session-length chips 20m/45m/1h+ mapped to weekly hours;
QuizBuilder settings-so-far rail beside the stepper; quiz length `Slider` +
`~N min` (2.5 min/q) + upper bound; practice `filters.source` segmented control
(verify backend `source` param first); per-topic mark-loss stat beside topic
checkboxes in PracticeGenerator; `CameraCapture` as third source in
`Grading.tsx`; top-grade caption on GradeDistributionPanel; review-queue count
pill on teacher `SidebarNavItem` (`GET /teacher/review` query, deduped);
marketing hero/feature cards `p-8` (Landing.tsx:214, DataHandling.tsx:79);
`docs/design-canvas-notes.md` annotating superseded canvas facts (device limit
3, subject colours, Instrument Serif, Academic Warmth); compact prev/next queue
strip in `ReviewItem` reusing the already-fetched `queueQuery` (route model
kept per `ReviewItem.tsx:30-40`). Findings:
paper-no-question-filter-tabs, paper-red-pen-register-missing,
student-home-streak-hidden-on-phone,
onboarding-plan-rows-no-icon-coding-no-live-type,
onboarding-14day-framing-vs-perpetual-week,
onboarding-session-length-chips-vs-weekly-hours-slider,
teacher-tools-quizbuilder-structure-divergence,
teacher-tools-quiz-length-slider-vs-input,
content-practice-source-filter-dead-in-ui,
content-classified-practice-mental-model,
teacher-flow-no-camera-capture-on-upload,
teacher-analytics-no-headline-top-grade-count, teacher-flow-no-nav-badge-counts,
x-density-card-padding-knob-underused, trust-ops-device-limit-count-divergence,
brand-subject-color-mapping-mismatch, x-type-instrument-serif-rejected,
brand-color-system-superseded, student-home-no-hero-grade (decision
recorded in DESIGN.md), teacher-flow-no-queue-rail-during-review.

**C4 Cross-cutting** — global `@media print` hiding portal shells; PaperResult
print layout (`break-inside: avoid` on question rows); one print-media capture
in `audit.mjs`; Lighthouse perf floor extended to ClassAnalytics + Review in
`check_ui_gates.py`; unit test mocking `matchMedia` reduced-motion for
`useCountUp`/`Flourish`; `scripts/check_copy.mjs` in CI; DESIGN.md §13
card-padding range corrected; P3.4 logical-property rule in DESIGN.md §14 gate
list. Findings: x-completeness-print-only-one-screen,
x-completeness-perf-floor-student-only, x-motion-reduced-motion-e2e-narrow-scope
(unit half), x-copy-friendly-tone-em-dash (gate wiring, M17).

**C5 Dark mode** — token inversion per DESIGN.md §3.2 item 8 under
`:root[data-theme="dark"]` and `@media (prefers-color-scheme: dark)
:root:not([data-theme="light"])`; every `--paper*`, `--ink*`, `--rule*`, 6
subject pastels, 4 semantic families, `--focus-ring`, `--accent*` re-measured
for AA against dark surfaces, table recorded in DESIGN.md §3; Theme toggle
(System/Light/Dark) in `ProfileSettings.tsx`, `localStorage` key + inline
pre-mount script in `index.html` to avoid flash; `theme-color` meta swapped at
runtime; `ChartFrame`/Nivo theme, skeletons, `celebration.tsx` colours
token-driven; `tests/unit/design-tokens.test.ts` + `test_design_tokens.py`
assert the dark ladder; screenshot harness dark variant for Overview,
PaperResult, Review, ClassAnalytics, Login; DESIGN.md:70-73 updated. Findings:
x-dark-deliberately-deferred, x-dark-retrofit-token-surface,
x-tokens-dark-theme-deferred, x-a11y-dark-theme-exploration-correctly-unshipped.

## Phase D — `feat/gamification-and-backend-gaps` (25 ledger rows, 3 packets, backend first)

**D1 Gamification** — `previousRank` on both leaderboard DTOs
(`leaderboard_repo.py`, computed at weekly reset boundary) → viewer's own row
animates via `Celebrate`/`CountUp`; `isFrozenToday` on streak DTO →
`XPStreak frozen`; achievements: Alembic migration `mastery_events` (user,
kind, subject_code, earned_at, evidence JSON), honest triggers only (subject
mastery ≥ threshold across N papers; weekly top-3; comeback after ≥14-day
gap), `GET /student/achievements`, sticker-badge register (DESIGN.md §8) on
Profile + parent activity row; daily quests: `quests` + `quest_progress`
tables, 3 per day generated from real activity types (mark a paper, review N
cards, complete one practice set), progress from existing `xp_events`, XP
reward via existing pipeline, restrained copy (no "crush", no multipliers, no
friend-rivalry), Overview card + Profile list, PRODUCT.md line added.
Findings: gamification-no-leaderboard-climb-celebration,
gamification-frozen-streak-unwired, gamification-no-achievement-badges,
gamification-no-daily-quests, x-ia-quests-badges-not-built,
parent-activity-feed-badges-not-built.

**D2 DTO gaps** — `subjectCode` + `topicId` on `WeakThreadDTO`
(`lemely/web/schemas_student.py`, `studentTypes.ts:38-44`) → Overview rows
become plain inline links to `/student/practice/:subjectCode?topic=`;
"Practice this" in `QuestionRow` expanded detail with `source` provenance;
weekly window on `GET /parent/children/{id}` (papers this week, minutes this
week) → ChildOverview strip; `StatCardDTO.foot`/`footTone` for Group mean
(prior 30d vs current) in `routers/teacher.py`; near-boundary students list on
ClassDetail reusing boundary-distance calc; real `{grade,minMark}` boundaries
in `ResultDTO` → `BoundaryBar` on PaperResult + parent SubjectDetail;
`recentPapers` on the overview endpoint → Overview list (3–5 rows linking to
`/student/result/:paperId`); per-grade predicted interval from ease factor →
flashcard button hints; QuizBuilder predicted class mean = mean of enrolled
students' `predictedGrade` for that subject, labelled "based on current
predicted grades"; `poolSource` list support if backend accepts (verify; else
skip with reason); `GET /student/study-plan/calendar.ics` export of plan
sessions (Apple/Google Calendar) + Download link on StudyPlanWeek. Findings:
student-home-weak-topic-no-cta,
paper-no-ai-remediation-quiz (cheap half), parent-weekly-digest-framing-lost,
teacher-analytics-group-mean-no-trend, teacher-analytics-bubble-students-missing,
paper-no-boundary-proximity, student-home-no-recent-activity-feed,
content-flashcard-interval-hints-omitted,
teacher-tools-predicted-class-average-fabricated,
teacher-tools-pool-source-single-select, parent-no-notifications-inbox
(verify already-fixed), onboarding-plan-calendar-sync-not-built.

**D3 XL gaps** — transcript field on student `QuestionResult` DTO, rendered
in `QuestionRow` with "Lemely's transcription, not the scan"; per-marking-point
breakdown: persist point award state + scheme wording from the mark-scheme
parse (new table or JSON column on question results + migration), rows
B1/C1/A1 in ReviewItem + PaperResult, teacher can toggle a point; batch
ingest: `POST /teacher/uploads/batch` (multi-file, one run per file, per-file
status endpoint, Gemini budget guard sequential), Grading multi-drop UI with
per-file status; scan crops in review: persist per-question crop coords +
image in GCS (per 2026-09-03 uploads design), `<img>` in "What Lemely saw"
with the existing honest fallback; AI remediation quiz: Gemini generates
mistake-targeted questions from a paper's lost marks, stored as a practice set,
`source="ai_remediation"`, diagrams explicitly out of scope; lesson-plan CTA:
Gemini outline per class weakness, stored, teacher-editable, honesty banner
("draft, review before use"); learning-style axes: questionnaire preference
fields persisted, difficulty-ramp threaded into `StudyPlanService.generate`
as a fourth signal, `PlanBasis` copy updated; live-coach mode: distinct
`QuizTaker` mode for remediation practice (per-question feedback), exam mode
untouched. Findings: paper-no-student-transcript,
teacher-flow-no-per-point-marking-breakdown, teacher-flow-no-batch-ingest,
teacher-flow-no-scan-image-in-review, paper-no-ai-remediation-quiz (full),
teacher-analytics-no-lesson-plan-action,
onboarding-semantic-sliders-no-personalization-signal,
quiz-live-coach-vs-exam-model.

## Ledger buckets (counts approximate; exact rows generated from the HTML)

- **pending (build)** 187 (assigned above)
- **no-action** 92: PWA PASS checks, `canvas-regression` findings
  (production already better), informational notes, `charts-well-deferred-positive`,
  `tell T5`, `sec-01…04`, `emp-sw-registers-and-controls`, etc.
- **already-fixed**: `parent-no-notifications-inbox` (confirm)
- **skipped** 21 with reason (items below that carry a PWA N/A verdict land as `no-action` instead): marketplace/bookings/checkout/paid-tutoring bar;
  live video; video library; QR/face + fraud toggles; WhatsApp + geo-IP;
  BusinessStats; hours-saved KPI; cover stat trio + italic hero;
  grade-guarantee + hype copy; status-bar black-translucent; flashcard
  rollback; haptic per grade; popover history; portrait lock; national
  benchmark; `iarc_rating_id`; `related_applications`; periodicsync; widen
  `PRECACHE_HOSTS`; PushNotifications regex chase; description shortening;
  auth-funnel + admin audit lanes; virtualize before paginate; `inputMode` on
  invite code; Tabs/RadioGroup dead code; mastery-garden visual; 5-pip progress
  bar; `x-ia-tutoring-center-cluster-unscoped`; `center-commerce-*`;
  `parent-add-child-affordance-rejected`; `trust-ops-suspicious-login-geoip-rejected`.

## Verification (per phase, before PR)

- `node web/scripts/check-native-invariants.mjs`, `check-bundle-budget.mjs`,
  `check_copy.mjs` green (each added in the phase that introduces it).
- `npm run typecheck && npm run lint && npx vitest run <touched> && npm run build`.
- `pytest --no-cov tests/<touched>` only; `ruff check`.
- `npx playwright test e2e/native-feel.spec.ts` (from Phase B) + touched specs
  when the backend is available.
- Built-output assertions from the dossier (manifest keys, screenshot sizes,
  `grep -c 'screenshots/' dist/sw.js == 0`, `share-target` in `dist/sw.js`).
- Opus verifier evidence line per ledger row; ledger has no `pending` for the
  phase.
- CI full suite on the PR; user's post-merge staging checklist.

## After approval (out of plan mode)

1. Write spec `docs/superpowers/specs/2026-09-10-audit-dossier-remediation-design.md`
   (this design) + generate the 301-row ledger from the artifact HTML; spec
   self-review; ask user to review; commit spec + ledger only after user OK
   (CLAUDE.md: no commits unless asked).
2. `superpowers:writing-plans` → `docs/superpowers/plans/2026-09-10-audit-dossier-remediation.md`
   with packet briefs (interfaces, files, tests, skills — no code bodies, per
   memory `delegate-by-model`).
3. `/model sonnet`, `/oh-my-claudecode:ralph` Phase A → `Skill(orchestrator)`
   coordinates packets per the protocol above.
