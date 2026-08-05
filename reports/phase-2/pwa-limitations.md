# P2.9 PWA — carried environment limitations

Recorded 2026-08-05, orchestrator session. Two things P2.9's task wording asks for
could not be *live*-verified in this headless build sandbox. Both were verified as
thoroughly as the environment allows; neither is silently marked passing. This note
exists so P2.10's DELIVERY.md can cite it directly instead of re-deriving.

## 1. Lighthouse PWA checks — not run live

**Why:** No Chromium/Chrome binary is present in this sandbox. `npx puppeteer
browsers install chrome` was attempted and timed out after 90s (large binary
download over a constrained/slow egress path). A live Lighthouse audit needs a
real Chrome instance to drive; there is none available here, and downloading one
is not viable in this environment.

**What was verified instead (by inspection of the actual build output, not
assumed):**
- `dist/manifest.webmanifest` — built and inspected directly. Contains real
  `name`/`short_name`/`description`, `start_url: "/"`, `display: "standalone"`,
  `theme_color`/`background_color` (computed from the app's real design tokens via
  a verified oklch->sRGB conversion, independently re-derived by the orchestrator
  and matched exactly), and an `icons` array with 192×192, 512×512, and a maskable
  512×512 variant — all three genuinely rasterized from the real brand mark
  (`public/favicon.svg`), not placeholders.
- `dist/sw.js` + `dist/workbox-*.js` — generated Workbox service worker, confirmed
  to register a `fetch` event handler, precache the app shell (28 entries: JS/CSS/
  fonts/icons/HTML), and explicitly deny-list `/^\/api/` from both the navigation
  fallback and any runtime caching, so live grading/marks data is never served
  stale from cache.
- `index.html` carries the manifest link (auto-injected by `vite-plugin-pwa`) plus
  `apple-touch-icon`/`theme-color`/`apple-mobile-web-app-*` meta tags added by hand
  for iOS/Android install polish.

This satisfies the installability *criteria* Lighthouse's PWA category checks
(valid manifest, icons at the right sizes, registered service worker with a fetch
handler, offline-capable app shell) by direct inspection. It is not the same as a
live Lighthouse score, and should not be reported as one. A session with a real
Chromium available (or a real device) should run an actual Lighthouse audit before
this is claimed as a hard pass.

## 2. Camera capture UX — not live-tested end-to-end

**Why:** No camera device and no real browser exist in this sandbox — `getUserMedia`
cannot be meaningfully exercised headlessly.

**What was verified instead:**
- `npm run typecheck` / `npm run lint` / `npm run build` all clean against the new
  `web/src/components/CameraCapture.tsx` and its wiring into
  `web/src/portals/student/screens/CorrectPaper.tsx`.
- The orchestrator manually traced (not just trusted the implementer's report):
  the `getUserMedia` acquire/release `useEffect` (keyed on `[phase, retryToken]`,
  whose cleanup fires on both phase change and unmount, with a `cancelled` guard
  so a stream resolving after teardown is stopped immediately rather than leaking
  — closing the "camera stays on after navigating away" failure mode); the
  `pdf-lib` page-assembly call sequence (`PDFDocument.create()` ->
  `embedJpg()` -> `addPage([w,h])` -> `drawImage()` -> `save()`), which matches
  `pdf-lib`'s documented usage; the object-URL lifecycle (revoked on per-page
  delete and in bulk on unmount); and the tab-toggle state resets in
  `CorrectPaper.tsx` (switching between "Upload a file" and "Scan with camera"
  clears `scanFile` so a stale file from the other source can't be silently
  submitted).
- Specific, actionable error messages are shown for every `getUserMedia` failure
  mode reachable via `DOMException.name` (permission denied, no camera found,
  camera in use, insecure context, aborted) — verified by reading the mapping
  function directly, not assumed.

**Not verified, and cannot be in this environment:** the actual browser permission
prompt/grant flow, live video frame capture fidelity, the real UI states under an
actual denied-permission or no-camera device, and that the assembled PDF opens
correctly outside this sandbox. This needs a real device/browser pass before
P2.10's Playwright acceptance suite can treat the camera-capture flow as proven —
Playwright itself can grant fake camera permissions in a real Chromium context,
which is not available here either.

## Scope note

Camera capture was wired into the student `CorrectPaper.tsx` flow only (the
MISSION-flagship "photograph an attempted paper" loop). The teacher `Grading.tsx`
upload panel (P2.8 step 3) was deliberately left as file-input-only — teacher batch
uploads are more realistically scanner-sourced PDFs than phone photos, so extending
camera capture there was out of scope for this pass, not an oversight.
