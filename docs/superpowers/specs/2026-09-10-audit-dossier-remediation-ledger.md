# Audit Dossier Remediation — Ledger

Source artifact: https://claude.ai/code/artifact/37885ce6-4f48-4b00-a763-38d555c0a17e
("Lemely Audit Dossier", 9 Sep 2026) · Generated: 2026-09-10

Companion design spec: `docs/superpowers/specs/2026-09-10-audit-dossier-remediation-design.md`.
Generated mechanically from the artifact HTML (301 `<article>` findings), then
hand-assigned to phase/packet per the design's `Findings:` lists and ledger-bucket rules.

## Status legend

- `pending` — assigned to a Phase A–D packet; not yet implemented. Ralph reads these as its task list.
- `no-action` — PWA-checklist PASS/NOT-APPLICABLE result, a UI `canvas-regression` (production already better than the exploration canvas), or an explicit dossier "no change needed" verdict.
- `skipped` — explicitly out of scope per the design's user decisions, with a one-line reason.
- `already-fixed?` — dossier flagged it broken, but it appears already fixed on `develop`; needs a quick confirm, not a full packet.

## Ledger

| # | id | lane | severity/verdict | phase | packet | status | evidence |
|---|---|---|---|---|---|---|---|
| 1 | `no-optimistic-flashcard-grading` | native | critical | B | B5 | pending |  |
| 2 | `gesture-flashcard-no-swipe` | native | critical | B | B4 | pending |  |
| 3 | `silent-update-swap` | native | critical | A | A7 | done A7 | `npx vitest run tests/unit/swSource.test.ts tests/unit/serviceWorkerUpdate.test.ts` |
| 4 | `kb-1` | native | critical | A | A1 | done A1 | `npx vitest run tests/unit/nativeMechanics.test.ts tests/unit/design-tokens.test.ts` |
| 5 | `nav-1` | native | critical | B | B2 | pending |  |
| 6 | `offline-1` | native | critical | B | B6 | pending |  |
| 7 | `input-font-14px-ios-zoom` | native | critical | A | A1 | done A1 | `npx vitest run tests/unit/nativeMechanics.test.ts tests/unit/design-tokens.test.ts` |
| 8 | `tap-highlight-color` | native | critical | A | A1 | done A1 | `npx vitest run tests/unit/nativeMechanics.test.ts tests/unit/design-tokens.test.ts` |
| 9 | `T1` | native | critical | B | B2 | pending |  |
| 10 | `no-active-state-question-row-confidence` | native | high | A | A3 | done A3 | `npx vitest run tests/unit/hoverTransition.test.ts` — pass |
| 11 | `zero-haptics-anywhere` | native | high | B | B5 | pending |  |
| 12 | `gesture-navdrawer-no-swipe-dismiss` | native | high | B | B4 | pending |  |
| 13 | `no-install-affordance` | native | high | A | A7 | done A7 | `npx vitest run tests/unit/installPrompt.test.ts` |
| 14 | `route-fallback-not-a-skeleton` | native | high | B | B1 | pending |  |
| 15 | `kb-2` | native | high | A | A2 | done A2 | `npx vitest run tests/unit/authInputAttributes.test.ts` — Login/JoinWithCode enterKeyHint=go, SignupDetails autoCapitalize/autoCorrect; design doc's "ParentLogin.tsx PhoneStep" is stale (phone-OTP parent login retired, commit f7fa328) — enterKeyHint=send applied to SignupParent's email-step field instead |
| 16 | `nav-2` | native | high | B | B3 | pending |  |
| 17 | `nav-3` | native | high | B | B2 | pending |  |
| 18 | `nav-4` | native | high | B | B2 | pending |  |
| 19 | `offline-2` | native | high | A | A4 | done A4 | `npx vitest run tests/unit/offlineClassification.test.ts` — `isOfflineFailure` predicate tested directly (ApiError status 0 only, per review MEDIUM 1); QueryState's error-branch wiring to it verified by source-level check (no jsdom/RTL in this repo — see test file header) |
| 20 | `offline-3` | native | high | B | B6 | pending |  |
| 21 | `correct-paper-chunk-no-prefetch` | native | high | B | B6 | pending |  |
| 22 | `no-pre-mount-shell` | native | high | B | B1 | pending |  |
| 23 | `review-queue-unbounded-unvirtualized` | native | high | B | B6 | pending |  |
| 24 | `student-shell-blanks-on-cold-load` | native | high | B | B1 | pending |  |
| 25 | `badging-api-unused-despite-ready-data` | native | high | B | B5 | pending |  |
| 26 | `camera-scanner-basics-only` | native | high | B | B5 | pending |  |
| 27 | `web-share-unused-on-result-screen` | native | high | B | B5 | pending |  |
| 28 | `login-links-under-44px-tap-target` | native | high | A | A2 | done A2 | `npx vitest run tests/unit/authInputAttributes.test.ts` — Login.tsx LINK_CLASS gains `inline-flex min-h-11 items-center` |
| 29 | `no-safe-area-insets` | native | high | A | A1 | done A1 | `npx vitest run tests/unit/nativeMechanics.test.ts tests/unit/design-tokens.test.ts` |
| 30 | `no-ios-splash-screens` | native | high | B | B1 | pending |  |
| 31 | `safe-area-viewport-cover` | native | high | A | A1 | done A1 | `npx vitest run tests/unit/nativeMechanics.test.ts tests/unit/design-tokens.test.ts` |
| 32 | `status-bar-style-default-mismatch` | native | high | A | A1 | done A1 | `npx vitest run tests/unit/nativeMechanics.test.ts tests/unit/design-tokens.test.ts` |
| 33 | `double-tap-zoom-unneutralized` | native | high | A | A1 | done A1 | `npx vitest run tests/unit/nativeMechanics.test.ts tests/unit/design-tokens.test.ts` |
| 34 | `modal-drawer-scroll-lock-fragile` | native | high | B | B2 | pending |  |
| 35 | `overscroll-behavior-absent` | native | high | A | A1 | done A1 | `npx vitest run tests/unit/nativeMechanics.test.ts tests/unit/design-tokens.test.ts` |
| 36 | `TT-1` | native | high | B | B3 | pending |  |
| 37 | `T2` | native | high | B | B1 | pending |  |
| 38 | `T3` | native | high | B | B2 | pending |  |
| 39 | `role-switcher-no-active-state` | native | medium | A | A3 | done A3 | `npx vitest run tests/unit/hoverTransition.test.ts` — pass |
| 40 | `gesture-no-pull-to-refresh` | native | medium | B | B4 | pending |  |
| 41 | `gesture-quiztaker-no-swipe-honest-tradeoff` | native | medium | B | B4 | pending |  |
| 42 | `gesture-standalone-pwa-no-back-replacement` | native | medium | B | B2 | pending |  |
| 43 | `no-launch-handler` | native | medium | A | A5 | done A5 | `npx vitest run tests/unit/manifest.test.ts` + dist/manifest.webmanifest key check — vite/manifest.ts (launch_handler) |
| 44 | `no-periodic-update-check` | native | medium | A | A7 | done A7 | `npx vitest run tests/unit/serviceWorkerUpdate.test.ts (scheduleUpdateChecks: visibilitychange + 60min interval)` |
| 45 | `kb-3` | native | medium | A | A2 | done A2 | `npx vitest run tests/unit/authInputAttributes.test.ts` — see kb-2 evidence; same commit |
| 46 | `kb-4` | native | medium | A | A2 | done A2 | `npx vitest run tests/unit/authInputAttributes.test.ts` — see kb-2 evidence; same commit |
| 47 | `nav-5` | native | medium | B | B3 | pending |  |
| 48 | `offline-4` | native | medium | A | A4 | done A4 | `npx vitest run tests/unit/offlineClassification.test.ts` — `isOfflineFailure` predicate tested directly (ApiError status 0 only, per review MEDIUM 1); QueryState's error-branch wiring to it verified by source-level check (no jsdom/RTL in this repo — see test file header) |
| 49 | `correct-paper-defaults-to-file-not-camera` | native | medium | A | A4 | done A4 | `npx vitest run tests/unit/correctPaperSource.test.ts tests/unit/cameraAutoStart.test.ts` — CorrectPaper opens to camera on a coarse (touch) pointer, but per review HIGH finding does not auto-acquire the device on that unprompted mount: `shouldAutoStartCamera` predicate tested directly, gesture-gating wiring (CorrectPaper→CameraCapture `autoStart` prop, CameraCapture's getUserMedia effect gated on `started`) verified by source-level check |
| 50 | `wake-lock-unused-during-multi-shot-capture` | native | medium | B | B5 | pending |  |
| 51 | `no-overscroll-behavior` | native | medium | A | A1 | done A1 | `npx vitest run tests/unit/nativeMechanics.test.ts tests/unit/design-tokens.test.ts` |
| 52 | `no-orientation-policy` | native | medium | B | B5 | pending |  |
| 53 | `no-standalone-media-query` | native | medium | A | A1 | done A1 | `npx vitest run tests/unit/nativeMechanics.test.ts tests/unit/design-tokens.test.ts` |
| 54 | `touch-callout-select-on-chrome` | native | medium | A | A1 | done A1 | `npx vitest run tests/unit/nativeMechanics.test.ts tests/unit/design-tokens.test.ts` |
| 55 | `T4` | native | medium | B | B2 | pending |  |
| 56 | `practice-create-spinner-acceptable-but-note` | native | low | B | B1 | pending |  |
| 57 | `gesture-no-long-press-and-thats-fine` | native | low | B | B4 | pending |  |
| 58 | `kb-6` | native | low | A | A1 | done A1 | `npx vitest run tests/unit/nativeMechanics.test.ts tests/unit/design-tokens.test.ts` |
| 59 | `nav-6` | native | low | B | B2 | pending |  |
| 60 | `charts-well-deferred-positive` | native | low |  |  | no-action | dossier: verification only, no fix needed |
| 61 | `grading-thumbnail-no-decoding-async` | native | low | A | A4 | done A4 | `npm run build` (web/) — `Grading.tsx` thumbnail `<img>` now has `decoding="async"` |
| 62 | `file-picker-single-file-no-multiple` | native | low | B | B5 | pending |  |
| 63 | `silent-401-push-config-every-load` | native | low | A | A7 | done A7 | `npx vitest run tests/unit/pushConfigColdLoad.test.ts; chrome-devtools live check on cold /login: 0 requests to push/config (was 2)` |
| 64 | `sw-registers-on-staging-but-no-fetch-handling` | native | low | A | A7 | done A7 | `already satisfied by A6's unconditional share-target fetch listener (sw.ts, outside precacheEnabled) — verified via tests/unit/swSource.test.ts` |
| 65 | `min-h-screen-no-dvh-fallback` | native | low | A | A1 | done A1 | `npx vitest run tests/unit/nativeMechanics.test.ts tests/unit/design-tokens.test.ts` |
| 66 | `T5` | native | low |  |  | no-action | dossier: motion-rule compliance verified; regression guard lands in A8 check-native-invariants |
| 67 | `auth-gated-capture-method-sound` | pwa | PASS |  |  | no-action | PASS check |
| 68 | `capture-pipeline-choice` | pwa | PARTIAL | A | A5 | done A5 | `npm run screenshots:manifest` — scripts/manifest_screenshots.mjs; dist/screenshots/*.jpg form_factor sorted == [narrow, wide] |
| 69 | `form-factor-wide-and-narrow` | pwa | FAIL | A | A5 | done A5 | `npm run screenshots:manifest` — scripts/manifest_screenshots.mjs; dist/screenshots/*.jpg form_factor sorted == [narrow, wide] |
| 70 | `screenshots-label-field` | pwa | NOT-APPLICABLE | A | A5 | pending |  |
| 71 | `screenshots-member-absent` | pwa | FAIL (unchanged on staging), but the fix pathway already half-exists in-repo, untracked and unwired. | A | A5 | pending |  |
| 72 | `sec-05-headers-missing` | pwa | FAIL | A | A6 | done A6 | `npx vitest run tests/unit/headers.test.ts tests/unit/headerParity.test.ts (A6 review fix); docker: curl -sI /, /sw.js, /manifest.webmanifest, /robots.txt, /shell-init.js, /assets/*, /api/* all show all 5 headers (was 3 of 7 paths before the fix)` |
| 73 | `sec-06-header-hsts` | pwa | FAIL | A | A6 | done A6 | `npx vitest run tests/unit/headers.test.ts tests/unit/headerParity.test.ts (A6 review fix); docker: curl -sI /, /sw.js, /manifest.webmanifest, /robots.txt, /shell-init.js, /assets/*, /api/* all show all 5 headers (was 3 of 7 paths before the fix)` |
| 74 | `sec-07-header-x-content-type-options` | pwa | FAIL | A | A6 | done A6 | `npx vitest run tests/unit/headers.test.ts tests/unit/headerParity.test.ts (A6 review fix); docker: curl -sI /, /sw.js, /manifest.webmanifest, /robots.txt, /shell-init.js, /assets/*, /api/* all show all 5 headers (was 3 of 7 paths before the fix)` |
| 75 | `sec-08-header-referrer-policy` | pwa | FAIL | A | A6 | done A6 | `npx vitest run tests/unit/headers.test.ts tests/unit/headerParity.test.ts (A6 review fix); docker: curl -sI /, /sw.js, /manifest.webmanifest, /robots.txt, /shell-init.js, /assets/*, /api/* all show all 5 headers (was 3 of 7 paths before the fix)` |
| 76 | `sec-09-header-permissions-policy` | pwa | FAIL | A | A6 | done A6 | `npx vitest run tests/unit/headers.test.ts tests/unit/headerParity.test.ts (A6 review fix); docker: curl -sI /, /sw.js, /manifest.webmanifest, /robots.txt, /shell-init.js, /assets/*, /api/* all show all 5 headers (was 3 of 7 paths before the fix)` |
| 77 | `sec-10-csp-discrepancy-resolved` | pwa | FAIL | A | A6 | done A6 | `npx vitest run tests/unit/headers.test.ts tests/unit/headerParity.test.ts (A6 review fix); docker: curl -sI /, /sw.js, /manifest.webmanifest, /robots.txt, /shell-init.js, /assets/*, /api/* all show all 5 headers (was 3 of 7 paths before the fix)` |
| 78 | `sec-11-header-delivery-mechanism` | pwa | FAIL | A | A6 | done A6 | `npx vitest run tests/unit/headers.test.ts tests/unit/headerParity.test.ts (A6 review fix); docker: curl -sI /, /sw.js, /manifest.webmanifest, /robots.txt, /shell-init.js, /assets/*, /api/* all show all 5 headers (was 3 of 7 paths before the fix)` |
| 79 | `manifest-dir` | pwa | PARTIAL | A | A5 | done A5 | `npx vitest run tests/unit/manifest.test.ts` + dist/manifest.webmanifest key check — vite/manifest.ts (dir) |
| 80 | `manifest-id` | pwa | PARTIAL | A | A5 | done A5 | `npx vitest run tests/unit/manifest.test.ts` + dist/manifest.webmanifest key check — vite/manifest.ts (id) |
| 81 | `manifest-launch-handler` | pwa | PARTIAL | A | A5 | done A5 | `npx vitest run tests/unit/manifest.test.ts` + dist/manifest.webmanifest key check — vite/manifest.ts (launch_handler) |
| 82 | `manifest-share-target` | pwa | PARTIAL | A | A6 | done A6 | `npx vitest run tests/unit/manifest.test.ts` |
| 83 | `manifest-shortcuts` | pwa | PARTIAL | A | A5 | done A5 | `npx vitest run tests/unit/manifest.test.ts` + dist/manifest.webmanifest key check — vite/manifest.ts (shortcuts) + `npm run icons` for shortcut-*-96.png |
| 84 | `MaskableSafeZone` | pwa | PASS | A | A5 | done A5 | `npx vitest run tests/unit/brandTokens.test.ts` — MASKABLE_SCALE <= MAX_MASKABLE_SCALE, now in vite/brandTokens.ts |
| 85 | `precache-glob-cost` | pwa | PASS-by-construction today (jpg extension already excludes these files); recommend the explicit globIgnores as documented hardening. | A | A5 | done A5 | `grep -c 'screenshots/\|widgets/\|store-icon' dist/sw.js` == 0 — vite.config.ts globIgnores |
| 86 | `emp-lighthouse-scores` | pwa | PARTIAL | A | A5 | pending |  |
| 87 | `apple-touch-icon-reuses-192` | pwa | PARTIAL | A | A5 | done A5 | `npm run icons` — scripts/generate_icons.mjs; verified via `file dist/apple-touch-icon.png dist/store-icon-1024.png dist/favicon.ico` — real 180px cut, index.html apple-touch-icon link updated |
| 88 | `Id` | pwa | FAIL | A | A5 | done A5 | `npx vitest run tests/unit/manifest.test.ts` + dist/manifest.webmanifest key check — vite/manifest.ts (id) |
| 89 | `Screenshots` | pwa | FAIL | A | A5 | done A5 | `npm run screenshots:manifest` — scripts/manifest_screenshots.mjs; dist/screenshots/*.jpg form_factor sorted == [narrow, wide] |
| 90 | `emp-env-navigation-flakiness` | pwa | PARTIAL | A | A8 | done A8 | `scripts/nav_retry.mjs`'s `withRetry`/`gotoWithRetry` (3 attempts), wired into every `audit.mjs` page.goto (13 sites) + `gotoReady` + the Lighthouse pass; `npx vitest run tests/unit/navRetry.test.ts` (6/6) |
| 91 | `emp-robots-txt-spa-fallback` | pwa | FAIL | A | A5 | done A5 | `ls dist/robots.txt` — web/public/robots.txt |
| 92 | `no-favicon-ico-fallback` | pwa | PARTIAL | A | A5 | done A5 | `npm run icons` — scripts/generate_icons.mjs; verified via `file dist/apple-touch-icon.png dist/store-icon-1024.png dist/favicon.ico` + `file dist/favicon.ico` — index.html favicon.ico link added |
| 93 | `manifest-categories` | pwa | PARTIAL | A | A5 | done A5 | `npx vitest run tests/unit/manifest.test.ts` + dist/manifest.webmanifest key check — vite/manifest.ts (categories) |
| 94 | `manifest-file-handlers` | pwa | PARTIAL | A | A6 | done A6 | `npx vitest run tests/unit/manifest.test.ts` |
| 95 | `sec-12-worker-api-response-headers` | pwa | FAIL | A | A6 | done A6 | `npx vitest run tests/unit/headerParity.test.ts (A6 review fix addendum L1 — worker/index.ts now sets all 5 headers, was 2 of 5); npm run build` |
| 96 | `sw-background-sync-upload-candidate` | pwa | NOT-APPLICABLE | B | B6 | pending |  |
| 97 | `sw-offline-production-trace` | pwa | PARTIAL | B | B6 | pending |  |
| 98 | `any-vs-maskable-distinct-art` | pwa | PASS |  |  | no-action | PASS check |
| 99 | `icon-sizes-match-reality` | pwa | PASS |  |  | no-action | PASS check |
| 100 | `maskable-safe-zone-verified` | pwa | PASS |  |  | no-action | PASS check |
| 101 | `HasHttps` | pwa | PASS |  |  | no-action | PASS check |
| 102 | `HasManifest` | pwa | PASS |  |  | no-action | PASS check |
| 103 | `HasSquare192PngAny` | pwa | PASS |  |  | no-action | PASS check |
| 104 | `IconTypesAreNotIcos` | pwa | PASS |  |  | no-action | PASS check |
| 105 | `IconTypesAreValid` | pwa | PASS |  |  | no-action | PASS check |
| 106 | `Icons-Array` | pwa | PASS |  |  | no-action | PASS check |
| 107 | `IconsAreFetchable` | pwa | PASS |  |  | no-action | PASS check |
| 108 | `ImagesAreNotBase64Encoded` | pwa | PASS |  |  | no-action | PASS check |
| 109 | `Name` | pwa | PASS |  |  | no-action | PASS check |
| 110 | `ServesHtml` | pwa | PASS |  |  | no-action | PASS check |
| 111 | `ShortName` | pwa | PASS |  |  | no-action | PASS check |
| 112 | `ShortcutIconsAreFetchable` | pwa | NOT-APPLICABLE | A | A5 | pending |  |
| 113 | `StartUrl` | pwa | PASS |  |  | no-action | PASS check |
| 114 | `sec-01-https-scheme` | pwa | PASS |  |  | no-action | PASS check |
| 115 | `emp-sw-registers-and-controls` | pwa | PASS |  |  | no-action | PASS check |
| 116 | `manifest-orientation` | pwa | NOT-APPLICABLE | A | A5 | done A5 | `npx vitest run tests/unit/manifest.test.ts` + dist/manifest.webmanifest key check — vite/manifest.ts (orientation) |
| 117 | `BackgroundColor` | pwa | PASS |  |  | no-action | PASS check |
| 118 | `Description` | pwa | PASS |  |  | no-action | PASS check |
| 119 | `Display` | pwa | PASS |  |  | no-action | PASS check |
| 120 | `HasServiceWorker` | pwa | PASS |  |  | no-action | PASS check |
| 121 | `HasSquare512PngAny` | pwa | PASS |  |  | no-action | PASS check |
| 122 | `IconSizesAreValid` | pwa | PASS |  |  | no-action | PASS check |
| 123 | `Lang` | pwa | PASS |  |  | no-action | PASS check |
| 124 | `Orientation` | pwa | FAIL | A | A5 | pending |  |
| 125 | `ScreenshotSizesAreValid` | pwa | NOT-APPLICABLE | A | A5 | pending |  |
| 126 | `ScreenshotTypesAreValid` | pwa | NOT-APPLICABLE | A | A5 | pending |  |
| 127 | `ScreenshotsAreFetchable` | pwa | NOT-APPLICABLE | A | A5 | pending |  |
| 128 | `ServiceWorkerIsNotEmpty` | pwa | PASS |  |  | no-action | PASS check |
| 129 | `ShortcutIconSizesAreValid` | pwa | NOT-APPLICABLE | A | A5 | pending |  |
| 130 | `ShortcutIconTypesAreValid` | pwa | NOT-APPLICABLE | A | A5 | pending |  |
| 131 | `ThemeColor` | pwa | PASS |  |  | no-action | PASS check |
| 132 | `sec-02-cert-validity` | pwa | PASS |  |  | no-action | PASS check |
| 133 | `sec-03-mixed-content` | pwa | PASS | A | A6 | no-action | dossier: no change — sec-03 already correct on develop (A6 re-verify) |
| 134 | `emp-beforeinstallprompt-not-observed` | pwa | PARTIAL | A | A7 | done A7 | `npx vitest run tests/unit/installPrompt.test.ts` |
| 135 | `emp-lighthouse-no-pwa-audits` | pwa | NOT-APPLICABLE |  |  | no-action | N/A check |
| 136 | `emp-offline-staging-by-design` | pwa | FAILS-ON-STAGING-ONLY | B | B6 | pending |  |
| 137 | `brand-assets-og-card` | pwa | PASS |  |  | no-action | PASS check |
| 138 | `no-1024-store-icon` | pwa | FAIL | A | A5 | done A5 | `npm run icons` — scripts/generate_icons.mjs; verified via `file dist/apple-touch-icon.png dist/store-icon-1024.png dist/favicon.ico` — 1024px, alpha removed |
| 139 | `manifest-display-override` | pwa | NOT-APPLICABLE | A | A5 | done A5 | `npx vitest run tests/unit/manifest.test.ts` + dist/manifest.webmanifest key check — vite/manifest.ts (display_override) |
| 140 | `manifest-edge-side-panel` | pwa | NOT-APPLICABLE | A | A5 | done A5 | `npx vitest run tests/unit/manifest.test.ts` + dist/manifest.webmanifest key check — vite/manifest.ts (edge_side_panel) |
| 141 | `manifest-handle-links` | pwa | NOT-APPLICABLE | A | A5 | done A5 | `npx vitest run tests/unit/manifest.test.ts` + dist/manifest.webmanifest key check — vite/manifest.ts (handle_links) |
| 142 | `manifest-iarc-rating-id` | pwa | NOT-APPLICABLE |  |  | no-action | N/A check |
| 143 | `manifest-note-taking` | pwa | NOT-APPLICABLE | A | A5 | done A5 | `npx vitest run tests/unit/manifest.test.ts` + dist/manifest.webmanifest key check — vite/manifest.ts (note_taking) |
| 144 | `manifest-prefer-related-applications` | pwa | NOT-APPLICABLE | A | A5 | done A5 | `npx vitest run tests/unit/manifest.test.ts` + dist/manifest.webmanifest key check — vite/manifest.ts (prefer_related_applications) |
| 145 | `manifest-protocol-handlers` | pwa | NOT-APPLICABLE | A | A5 | done A5 | `npx vitest run tests/unit/manifest.test.ts` + dist/manifest.webmanifest key check — vite/manifest.ts (protocol_handlers) + `npx vitest run tests/unit/joinProtocol.test.ts` |
| 146 | `manifest-related-applications` | pwa | NOT-APPLICABLE |  |  | no-action | N/A check |
| 147 | `manifest-scope-extensions` | pwa | NOT-APPLICABLE | A | A5 | done A5 | `npx vitest run tests/unit/manifest.test.ts` + dist/manifest.webmanifest key check — vite/manifest.ts (scope_extensions) |
| 148 | `manifest-widgets` | pwa | NOT-APPLICABLE | A | A5 | done A5 | `npx vitest run tests/unit/manifest.test.ts` + dist/manifest.webmanifest key check — vite/manifest.ts (widgets) + `pytest --no-cov tests/test_widget_router.py` |
| 149 | `Scope` | pwa | PASS |  |  | no-action | PASS check |
| 150 | `sec-04-fonts-self-hosted` | pwa | PASS |  |  | no-action | PASS check |
| 151 | `sw-offline-staging-proof` | pwa | FAIL |  |  | skipped | skip: widening PRECACHE_HOSTS / offline-on-staging explicitly excluded |
| 152 | `sw-periodic-background-sync` | pwa | NOT-APPLICABLE |  |  | no-action | N/A check |
| 153 | `sw-push-currently-unavailable` | pwa | NOT-APPLICABLE |  |  | no-action | N/A check |
| 154 | `sw-push-listener-real` | pwa | PASS | A | A7 | no-action | dossier: no change — push listener already correctly implemented (A7 re-verify) |
| 155 | `emp-console-401` | pwa | FAIL (401s in console confirmed via Lighthouse artifact) — root cause confirmed: `PushAutoEnable` (mounted unconditionally in `main.tsx`, above the router) called `usePushConfig()` with no auth gate, firing `GET /api/notifications/push/config` on a cold, logged-out `/login` load | A | A7 | done A7 | `npx vitest run tests/unit/pushConfigColdLoad.test.ts; chrome-devtools live check on cold /login: 0 requests to push/config (was 2)` |
| 156 | `parent-paid-tutoring-marketplace-ui` | ui | critical |  |  | skipped | exploration-only paid tutoring marketplace — skip marketplace/bookings/checkout |
| 157 | `brand-color-system-superseded` | ui | high | C | C3 | pending |  |
| 158 | `brand-cover-headline-and-stats-fabricated` | ui | high |  |  | skipped | skip: cover stat trio / fabricated headline not built |
| 159 | `content-classified-practice-mental-model` | ui | high | C | C3 | pending |  |
| 160 | `x-completeness-admin-portals-uncovered` | ui | high |  |  | no-action | production already better |
| 161 | `x-completeness-auth-funnel-uncovered` | ui | high |  |  | no-action | production already better |
| 162 | `x-completeness-offline-state-dead` | ui | high | A | A4 | done A4 | `npx vitest run tests/unit/offlineClassification.test.ts` — `isOfflineFailure` predicate tested directly; `OfflineState` reachability from QueryState's error branch verified by source-level check (no jsdom/RTL in this repo — see test file header) |
| 163 | `x-completeness-teacher-tables-bypass-table-primitive` | ui | high | C | C2 | pending |  |
| 164 | `gamification-no-leaderboard-climb-celebration` | ui | high | D | D1 | pending |  |
| 165 | `onboarding-semantic-sliders-no-personalization-signal` | ui | high | D | D3 | pending |  |
| 166 | `parent-no-notifications-inbox` | ui | high | D | D2 | already-fixed | web/src/portals/parent/screens/Notifications.tsx exists on develop, ToastProvider mounted main.tsx:14/toast.tsx:90 — confirmed A-Task0 |
| 167 | `student-home-weak-topic-no-cta` | ui | high | D | D2 | pending |  |
| 168 | `paper-no-ai-remediation-quiz` | ui | high | D | D3 | pending | split: D2 ships the cheap DTO half, D3 ships the full Gemini-backed quiz (assigned here to D3) |
| 169 | `paper-no-student-transcript` | ui | high | D | D3 | pending |  |
| 170 | `teacher-analytics-bubble-students-missing` | ui | high | D | D2 | pending |  |
| 171 | `teacher-flow-no-batch-ingest` | ui | high | D | D3 | pending |  |
| 172 | `teacher-flow-no-per-point-marking-breakdown` | ui | high | D | D3 | pending |  |
| 173 | `teacher-flow-no-scan-image-in-review` | ui | high | D | D3 | pending |  |
| 174 | `teacher-tools-business-stats-out-of-scope` | ui | high |  |  | skipped | skip: BusinessStats explicitly out of scope |
| 175 | `trust-ops-qr-attendance-feature-gap` | ui | high |  |  | skipped | skip: QR/face check-in out of scope |
| 176 | `trust-ops-whatsapp-feature-gap` | ui | high |  |  | skipped | skip: WhatsApp integration out of scope |
| 177 | `x-a11y-canvas-ink-tokens-fail-aa` | ui | high |  |  | no-action | production already better |
| 178 | `x-a11y-canvas-no-focus-visible` | ui | high |  |  | no-action | production already better |
| 179 | `x-brandlockup-duplicated-5x` | ui | high | C | C1 | pending |  |
| 180 | `x-copy-fabricated-metrics-must-not-adopt` | ui | high |  |  | no-action | production already better |
| 181 | `x-copy-onboarding-grade-guarantee` | ui | high |  |  | skipped | skip: grade-guarantee headline not built |
| 182 | `x-ia-tutoring-center-cluster-unscoped` | ui | high |  |  | skipped | skip: tutoring-center cluster explicitly unscoped |
| 183 | `x-motion-width-transition-gate-violation` | ui | high | A | A3 | done A3 | `npx vitest run tests/unit/motionDefaults.test.ts` — pass |
| 184 | `x-responsive-canvas-blind-production-full-breakpoint-system` | ui | high |  |  | no-action | production already better |
| 185 | `x-tokens-canvas-accents-fail-wcag` | ui | high |  |  | no-action | production already better |
| 186 | `brand-corner-tick-vs-texture-budget` | ui | medium |  |  | no-action | dossier: no production change |
| 187 | `brand-subject-color-mapping-mismatch` | ui | medium | C | C3 | pending |  |
| 188 | `center-commerce-deliberately-out-of-scope` | ui | medium |  |  | skipped | skip: center-commerce explicitly out of scope |
| 189 | `content-flashcard-interval-hints-omitted` | ui | medium | D | D2 | pending |  |
| 190 | `content-practice-source-filter-dead-in-ui` | ui | medium | C | C3 | pending |  |
| 191 | `x-completeness-forms-dimension-unaudited` | ui | medium | C | C2 | pending |  |
| 192 | `x-completeness-perf-floor-student-only` | ui | medium | A | A8 | done A8 | `scripts/check-bundle-budget.mjs` (200KB gzip/chunk, wired into `npm run build` via `postbuild`) is the mechanical floor this packet owns; primary C4 (full extension to ClassAnalytics+Review) remains open. Real build: `CorrectPaper-*.js` 180.03KB gzip (top chunk) — B6's baseline |
| 193 | `x-completeness-print-only-one-screen` | ui | medium | C | C4 | pending |  |
| 194 | `x-completeness-rtl-unwireable` | ui | medium | A | A3 | done A3 | `npx vitest run tests/unit/a11yRules.test.ts` — pass |
| 195 | `gamification-no-achievement-badges` | ui | medium | D | D1 | pending |  |
| 196 | `gamification-no-daily-quests` | ui | medium | D | D1 | pending |  |
| 197 | `gamification-production-states-exceed-canvas` | ui | medium |  |  | no-action | production already better |
| 198 | `onboarding-plan-rows-no-icon-coding-no-live-type` | ui | medium | C | C3 | pending |  |
| 199 | `parent-add-child-affordance-rejected` | ui | medium |  |  | skipped | skip: parent add-child affordance explicitly rejected |
| 200 | `parent-weekly-digest-framing-lost` | ui | medium | D | D2 | pending |  |
| 201 | `student-home-streak-hidden-on-phone` | ui | medium | C | C3 | pending |  |
| 202 | `paper-no-boundary-proximity` | ui | medium | D | D2 | pending |  |
| 203 | `quiz-live-coach-vs-exam-model` | ui | medium | D | D3 | pending |  |
| 204 | `teacher-analytics-group-mean-no-trend` | ui | medium | D | D2 | pending |  |
| 205 | `teacher-analytics-hours-saved-kpi-absent` | ui | medium |  |  | skipped | skip: fabricated hours-saved KPI not built |
| 206 | `teacher-analytics-national-benchmark-absent` | ui | medium |  |  | skipped | skip: backlog #20 national benchmark excluded |
| 207 | `teacher-analytics-no-lesson-plan-action` | ui | medium | D | D3 | pending |  |
| 208 | `teacher-flow-canvas-fake-progress-ring` | ui | medium |  |  | no-action | production already better |
| 209 | `teacher-flow-no-camera-capture-on-upload` | ui | medium | C | C3 | pending |  |
| 210 | `teacher-flow-no-queue-rail-during-review` | ui | medium | C | C3 | pending | compact prev/next queue strip in ReviewItem reusing queueQuery; route model kept (ReviewItem.tsx:30-40) |
| 211 | `teacher-tools-pool-source-single-select` | ui | medium | D | D2 | pending |  |
| 212 | `teacher-tools-predicted-class-average-fabricated` | ui | medium | D | D2 | pending |  |
| 213 | `teacher-tools-quizbuilder-structure-divergence` | ui | medium | C | C3 | pending |  |
| 214 | `trust-ops-device-limit-count-divergence` | ui | medium | C | C3 | pending |  |
| 215 | `trust-ops-suspicious-login-geoip-rejected` | ui | medium |  |  | skipped | skip: suspicious-login geo-IP explicitly rejected |
| 216 | `x-a11y-canvas-icon-buttons-unlabeled` | ui | medium |  |  | no-action | production already better |
| 217 | `x-a11y-canvas-touch-targets-undersized` | ui | medium |  |  | no-action | production already better |
| 218 | `x-a11y-prod-accent-small-text-below-own-floor` | ui | medium | A | A3 | done A3 | `npx vitest run tests/unit/contrastRules.test.ts` — pass |
| 219 | `x-confidence-weakness-superset` | ui | medium |  |  | no-action | production already better |
| 220 | `x-imageplaceholder-vs-honest-fallback` | ui | medium |  |  | no-action | production already better |
| 221 | `x-mark-grade-boundary-family-superset` | ui | medium |  |  | no-action | production already better |
| 222 | `x-navshells-dead-code` | ui | medium | B | B3 | pending |  |
| 223 | `x-sectionhead-no-equivalent` | ui | medium | C | C1 | pending |  |
| 224 | `x-copy-gamification-hype-voice` | ui | medium |  |  | skipped | skip: hype copy not adopted |
| 225 | `x-dark-deliberately-deferred` | ui | medium | C | C5 | pending |  |
| 226 | `x-density-card-padding-knob-underused` | ui | medium | C | C3 | pending |  |
| 227 | `x-ia-breadcrumbs-canvas-regression` | ui | medium |  |  | no-action | production already better |
| 228 | `x-ia-sidebar-cross-portal-mismatch` | ui | medium | B | B3 | pending |  |
| 229 | `x-motifs-subject-color-remap` | ui | medium |  |  | no-action | dossier: no production change |
| 230 | `x-motifs-subjectglyph-tile-missing` | ui | medium | C | C1 | pending |  |
| 231 | `x-motion-reduced-motion-e2e-narrow-scope` | ui | medium | B | B7 | pending | split: B7 adds e2e half, C4 adds unit half (assigned here to B7) |
| 232 | `x-responsive-phone-locked-surfaces-get-real-desktop-containers` | ui | medium |  |  | no-action | production already better |
| 233 | `x-responsive-teacher-dense-tables-scoped-overflow` | ui | medium |  |  | no-action | production already better |
| 234 | `x-tokens-card-pure-white` | ui | medium |  |  | no-action | production already better |
| 235 | `x-tokens-sky-info-subject-collision-persists` | ui | medium | A | A3 | done A3 | `npx vitest run tests/unit/design-tokens.test.ts` — pass |
| 236 | `x-tokens-subject-remap-collision` | ui | medium |  |  | no-action | dossier: no production change |
| 237 | `x-type-dead-font-packages-stale-docs` | ui | medium | A | A3 | done A3 | `npm install && npm run build` — pass |
| 238 | `x-type-instrument-serif-rejected` | ui | medium | C | C3 | pending |  |
| 239 | `brand-mark-a11y-canvas-regression` | ui | low |  |  | no-action | production already better |
| 240 | `brand-mark-geometry-diverges` | ui | low |  |  | no-action | dossier: no production change |
| 241 | `brand-subject-glyph-vs-subject-tag` | ui | low | C | C1 | pending |  |
| 242 | `center-activation-queue-more-honest-than-canvas-checkout` | ui | low |  |  | no-action | production already better |
| 243 | `classes-naming-collision-caveat` | ui | low |  |  | no-action | dossier: no production change |
| 244 | `classes-no-live-video-tutoring` | ui | low |  |  | skipped | skip: live video tutoring out of scope |
| 245 | `classes-no-recorded-video-library` | ui | low |  |  | skipped | skip: video library out of scope |
| 246 | `content-flashcard-card-stack-visual-simplified` | ui | low |  |  | no-action | dossier: no production change |
| 247 | `content-flashcard-session-summary-canvas-regression` | ui | low |  |  | no-action | production already better |
| 248 | `content-tutor-marketplace-absent` | ui | low |  |  | skipped | skip: paid tutoring marketplace out of scope |
| 249 | `x-completeness-kbd-primitive-bypassed` | ui | low | A | A3 | done A3 | `npm run typecheck && npm run build` — pass |
| 250 | `gamification-frozen-streak-unwired` | ui | low | D | D1 | pending |  |
| 251 | `gamification-restrained-visual-register` | ui | low |  |  | no-action | dossier: no production change |
| 252 | `onboarding-14day-framing-vs-perpetual-week` | ui | low | C | C3 | pending |  |
| 253 | `onboarding-plan-calendar-sync-not-built` | ui | low | D | D2 | pending | .ics export of study-plan sessions (Apple/Google Calendar); WhatsApp channel skipped |
| 254 | `onboarding-production-exceeds-canvas-state-handling` | ui | low |  |  | no-action | production already better |
| 255 | `onboarding-progress-indicator-pattern-mismatch` | ui | low |  |  | skipped | skip: 5-pip progress bar pattern not adopted |
| 256 | `onboarding-session-length-chips-vs-weekly-hours-slider` | ui | low | C | C3 | pending |  |
| 257 | `parent-activity-feed-badges-not-built` | ui | low | D | D1 | pending |  |
| 258 | `parent-weakness-panel-tone-canvas-regression` | ui | low |  |  | no-action | production already better |
| 259 | `student-home-first-run-state-better-than-canvas` | ui | low |  |  | no-action | production already better |
| 260 | `student-home-mastery-garden-not-adopted` | ui | low |  |  | skipped | skip: mastery-garden visual not adopted |
| 261 | `student-home-no-hero-grade` | ui | low | C | C3 | pending |  |
| 262 | `student-home-no-recent-activity-feed` | ui | low | D | D2 | pending |  |
| 263 | `paper-no-question-filter-tabs` | ui | low | C | C3 | pending |  |
| 264 | `paper-quiz-robustness-regression` | ui | low |  |  | no-action | production already better |
| 265 | `paper-red-pen-register-missing` | ui | low | C | C3 | pending |  |
| 266 | `teacher-analytics-chart-register-exceeds-canvas` | ui | low |  |  | no-action | production already better |
| 267 | `teacher-analytics-heatmap-exceeds-canvas` | ui | low |  |  | no-action | production already better |
| 268 | `teacher-analytics-no-headline-top-grade-count` | ui | low | C | C3 | pending |  |
| 269 | `teacher-flow-no-nav-badge-counts` | ui | low | C | C3 | pending |  |
| 270 | `teacher-flow-real-keyboard-shortcuts` | ui | low |  |  | no-action | production already better |
| 271 | `teacher-flow-review-promoted-to-nav` | ui | low |  |  | no-action | production already better |
| 272 | `teacher-flow-safer-bulk-approve` | ui | low |  |  | no-action | production already better |
| 273 | `teacher-tools-quiz-length-slider-vs-input` | ui | low | C | C3 | pending |  |
| 274 | `trust-ops-device-mgmt-canvas-regression` | ui | low |  |  | no-action | production already better |
| 275 | `trust-ops-fraud-toggles-unbuilt` | ui | low |  |  | skipped | skip: fraud toggles out of scope |
| 276 | `x-a11y-dark-theme-exploration-correctly-unshipped` | ui | low | C | C5 | pending |  |
| 277 | `x-celebration-stepper-production-only` | ui | low |  |  | no-action | production already better |
| 278 | `x-chip-badge-taxonomy-split` | ui | low |  |  | no-action | dossier: no production change |
| 279 | `x-progressring-inline-duplication-risk` | ui | low | C | C1 | pending |  |
| 280 | `x-copy-bulk-approve-honesty` | ui | low |  |  | no-action | production already better |
| 281 | `x-copy-error-state-canvas-gap` | ui | low |  |  | no-action | production already better |
| 282 | `x-copy-friendly-tone-em-dash` | ui | low | C | C4 | pending |  |
| 283 | `x-dark-nav-badge-raw-white` | ui | low | A | A3 | done A3 | `npx vitest run tests/unit/a11yRules.test.ts` — pass |
| 284 | `x-dark-retrofit-token-surface` | ui | low | C | C5 | pending |  |
| 285 | `x-density-canvas-knob-is-decorative` | ui | low |  |  | no-action | dossier: no production change |
| 286 | `x-density-operate-row-rhythm-matches-but-uncodified` | ui | low | C | C1 | pending |  |
| 287 | `x-ia-navshells-unused-abstraction` | ui | low | B | B3 | pending |  |
| 288 | `x-ia-quests-badges-not-built` | ui | low | D | D1 | pending |  |
| 289 | `x-ia-student-home-abc-exploration` | ui | low |  |  | no-action | dossier: no production change |
| 290 | `x-motifs-avatar-circle-vs-squircle` | ui | low |  |  | no-action | dossier: no production change |
| 291 | `x-motifs-lemely-mark-superseded` | ui | low |  |  | no-action | dossier: no production change |
| 292 | `x-motifs-margin-note-vs-caveat-rule` | ui | low |  |  | no-action | production already better |
| 293 | `x-motifs-marking-glyph-system` | ui | low |  |  | no-action | production already better |
| 294 | `x-motifs-progress-ring-not-systematized` | ui | low | C | C1 | pending |  |
| 295 | `x-motion-canvas-static-production-elaborate` | ui | low |  |  | no-action | production already better |
| 296 | `x-motion-progress-ring-no-production-equivalent` | ui | low | C | C1 | pending |  |
| 297 | `x-tokens-canvas-honey-hierarchy-inversion` | ui | low |  |  | no-action | dossier: no production change |
| 298 | `x-tokens-dark-theme-deferred` | ui | low | C | C5 | pending |  |
| 299 | `x-type-canvas-italic-heading` | ui | low |  |  | skipped | skip: italic hero heading not adopted |
| 300 | `x-type-scale-discipline` | ui | low |  |  | no-action | production already better |
| 301 | `x-type-tabular-nums-scope` | ui | low |  |  | no-action | dossier: no production change |

## Counts

### By status

| status | rows |
|---|---|
| pending | 187 |
| no-action | 92 |
| skipped | 21 |
| already-fixed? | 1 |
| **total** | **301** |

### By lane

| lane | rows |
|---|---|
| native | 66 |
| pwa | 89 |
| ui | 146 |
| **total** | **301** |

### By phase

| phase | rows |
|---|---|
| A | 87 |
| B | 42 |
| C | 36 |
| D | 25 |
| *(none — no-action/skipped)* | 111 |

### By packet

| packet | rows |
|---|---|
| A1 | 13 |
| A2 | 4 |
| A3 | 9 |
| A4 | 5 |
| A5 | 35 |
| A6 | 11 |
| A7 | 8 |
| A8 | 2 |
| B1 | 6 |
| B2 | 9 |
| B3 | 6 |
| B4 | 5 |
| B5 | 8 |
| B6 | 7 |
| B7 | 1 |
| C1 | 8 |
| C2 | 2 |
| C3 | 20 |
| C4 | 2 |
| C5 | 4 |
| D1 | 6 |
| D2 | 11 |
| D3 | 8 |
