#!/usr/bin/env node
/*
 * Generates the two PWA-manifest install screenshots (S-06 Overview, the
 * student dashboard) for the recommended manifest, wide + narrow.
 *
 * WHY A SEPARATE SCRIPT, NOT A NEW STATE ON capture_surface.mjs's OWN LOOP.
 *
 * `capture_surface.mjs` is the UI-review corpus and its two invariants both
 * work against a manifest screenshot: (1) its VIEWPORTS are 1440x1000 /
 * 375x900, and 900/375 = 2.4 already exceeds Chromium's manifest-screenshot
 * aspect-ratio ceiling of 2.3 before a single pixel of content is added; (2)
 * every capture in that corpus is deliberately `fullPage` (the whole
 * scrollable document, so a reviewer sees the entire screen), and a
 * fullPage capture of a dashboard is even taller still. A manifest
 * screenshot has to be the opposite: one unscrolled viewport, at an aspect
 * ratio a real device actually has. Bending the shared harness to produce a
 * third, incompatible kind of image was worse than a second small script.
 *
 * WHAT IS REUSED, DELIBERATELY.
 *
 * `SURFACES["student-dashboard"]`, `PORT` and `BASE` are imported from
 * `capture_surface.mjs`, not restated — its own header made itself
 * importable for exactly this reason ("a second hand-maintained list is a
 * list that drifts"). The `populated` state is the dashboard with real
 * content in every panel (three subjects, a momentum chart, weakest
 * topics) — the state most representative of the product, and already
 * built.
 *
 * WHY .jpg, NOT .png.
 *
 * `vite.config.ts`'s `injectManifest.globPatterns` is
 * `**\/*.{js,css,html,ico,png,svg,woff,woff2}` — every file under `public/`
 * with one of those extensions is swept into the service worker's precache
 * manifest and pushed to every visitor on their first load, forever, for an
 * image whose only consumer is a browser's own install dialog and that the
 * running app itself never fetches. `.jpg`/`.jpeg` is not in that list, so
 * shipping these as JPEG opts them out of the precache by construction
 * rather than by a `globIgnores` exception someone has to remember not to
 * delete. It also happens to be far smaller for this content (measured:
 * ~915KB PNG vs ~150KB JPEG q82 at 2880x1800; ~552KB vs ~62KB at 780x1688 —
 * PNG would have added roughly 1.5MB, a ~65% increase, to the current
 * ~2.27MB / 144-entry precache for images nothing in the app ever reads).
 * The manifest spec accepts both formats (MDN screenshots reference); there
 * is no store requirement forcing PNG.
 *
 * SEQUENCING — read before running.
 *
 *   1. npm run build            (dist/ has to exist to be photographed)
 *   2. node scripts/manifest_screenshots.mjs
 *      -> writes public/screenshots/dashboard-{wide,narrow}.jpg
 *      -> prints the `screenshots` array to paste into vite.config.ts
 *   3. Paste that array into vite.config.ts's `manifest:` block.
 *   4. npm run build            (this build ships the JPEGs + the updated
 *                                 manifest.webmanifest together)
 *
 * Re-run only when the populated dashboard's visual design changes
 * meaningfully — same lifecycle as `npm run icons` (scripts/generate_icons.mjs),
 * not a step in every CI build.
 */

import { spawn } from "node:child_process"
import fs from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"
import { chromium } from "@playwright/test"
import sharp from "sharp"
import { SURFACES, PORT, BASE } from "./capture_surface.mjs"
import { assertPortFree } from "./serve_guard.mjs"

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const OUT_DIR = path.resolve(__dirname, "../public/screenshots")

/*
 * Chromium's own manifest-screenshot validator (cited in full in the audit
 * report this script was written for): each side 320-3840px, and the long
 * side no more than 2.3x the short side. These are real, common device/
 * viewport aspect ratios that clear both bounds with room to spare —
 * 1440x900 = 1.6:1, 390x844 (iPhone 12/13 CSS size) = 2.164:1 — asserted
 * below rather than trusted, the same way generate_icons.mjs asserts its
 * own safe-zone arithmetic instead of eyeballing it.
 */
const MIN_SIDE = 320
const MAX_SIDE = 3840
const MAX_RATIO = 2.3

const MANIFEST_SHOTS = [
  {
    name: "dashboard-wide",
    formFactor: "wide",
    width: 1440,
    height: 900,
    label:
      "The student dashboard: subjects this session with predicted grades, a momentum chart, and weakest topics.",
  },
  {
    name: "dashboard-narrow",
    formFactor: "narrow",
    width: 390,
    height: 844,
    label: "The student dashboard on a phone: subjects this session and predicted grades.",
  },
]
const DPR = 2

const surface = SURFACES["student-dashboard"]
const state = surface.states.populated

function serveDist() {
  return spawn(
    "npx",
    ["vite", "preview", "--port", String(PORT), "--strictPort", "--host", "127.0.0.1"],
    { cwd: path.resolve(__dirname, ".."), stdio: ["ignore", "pipe", "pipe"] },
  )
}

async function waitForServer(timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    try {
      const res = await fetch(BASE, { signal: AbortSignal.timeout(2000) })
      if (res.ok) return
    } catch {
      /* not up yet */
    }
    await new Promise((r) => setTimeout(r, 300))
  }
  throw new Error(`vite preview did not answer on ${BASE} within ${timeoutMs}ms`)
}

async function main() {
  fs.mkdirSync(OUT_DIR, { recursive: true })
  await assertPortFree(BASE, PORT, "the manifest-screenshot capture")
  const server = serveDist()
  const manifestEntries = []
  try {
    await waitForServer()
    const browser = await chromium.launch()

    for (const shot of MANIFEST_SHOTS) {
      const context = await browser.newContext({
        viewport: { width: shot.width, height: shot.height },
        deviceScaleFactor: DPR,
      })
      await context.addInitScript(() => {
        window.localStorage.setItem(
          "lemely.session",
          JSON.stringify({
            accessToken: "capture",
            refreshToken: "capture",
            userId: "capture-student",
            role: "student",
          }),
        )
        window.localStorage.setItem("lemely.deviceId", "capture-device")
      })
      const page = await context.newPage()
      // Same registration order as capture_surface.mjs's main() and for the
      // same reason (see its P4.5 comment): catch-all first, specific stubs
      // after, so Playwright's most-recently-registered-wins semantics land
      // on the specific ones.
      await page.route("**/api/**", (route) =>
        route.fulfill({ status: 200, contentType: "application/json", body: "{}" }),
      )
      await page.route("**/api/me/profile", (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            userId: "capture-student",
            email: "amina@example.com",
            displayName: "Amina Farouk",
            role: "student",
          }),
        }),
      )
      await page.route("**/api/me/student-profile", (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            profile: {
              qualificationLevel: "igcse",
              gradeLevel: null,
              schoolName: "Nile International",
              hasExternalLessons: false,
              weeklyStudyHours: 6,
              onboardingCompletedAt: "2026-01-01T00:00:00Z",
              leaderboardOptOut: false,
            },
            enrolments: [],
          }),
        }),
      )
      await surface.stub(page, state)
      await page.goto(`${BASE}${surface.route}`, { waitUntil: "domcontentloaded" })
      await page.waitForTimeout(1400)

      const rawPath = path.join(OUT_DIR, `.${shot.name}-raw.png`)
      // fullPage: false — deliberately, see header. A manifest screenshot is
      // one unscrolled viewport, not the review corpus's whole document.
      await page.screenshot({ path: rawPath, fullPage: false })
      await context.close()

      const meta = await sharp(rawPath).metadata()
      const long = Math.max(meta.width, meta.height)
      const short = Math.min(meta.width, meta.height)
      if (short < MIN_SIDE || long > MAX_SIDE) {
        throw new Error(
          `${shot.name}: ${meta.width}x${meta.height} falls outside the ${MIN_SIDE}-${MAX_SIDE}px bound`,
        )
      }
      if (long / short > MAX_RATIO) {
        throw new Error(
          `${shot.name}: ${meta.width}x${meta.height} ratio ${(long / short).toFixed(3)} exceeds the ${MAX_RATIO} ceiling`,
        )
      }

      const outPath = path.join(OUT_DIR, `${shot.name}.jpg`)
      await sharp(rawPath).jpeg({ quality: 82, mozjpeg: true }).toFile(outPath)
      const bytes = fs.statSync(outPath).size
      fs.unlinkSync(rawPath)

      manifestEntries.push({
        src: `screenshots/${shot.name}.jpg`,
        sizes: `${meta.width}x${meta.height}`,
        type: "image/jpeg",
        form_factor: shot.formFactor,
        label: shot.label,
      })
      console.log(
        `wrote public/screenshots/${shot.name}.jpg  ${meta.width}x${meta.height}  ` +
          `ratio ${(long / short).toFixed(3)}  ${bytes} bytes`,
      )
    }
    await browser.close()
  } finally {
    server.kill("SIGTERM")
  }

  console.log("\nPaste into vite.config.ts's manifest: { ... screenshots: <this> }\n")
  console.log(JSON.stringify(manifestEntries, null, 2))
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
