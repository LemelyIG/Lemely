/*
 * Batched surface capture for the redesign's Hard Gate §9.5.
 *
 * WHAT THIS IS, AND WHAT IT IS NOT.
 *
 * `e2e/screenshots.spec.ts` is the product's real screenshot corpus: it drives
 * the actual FastAPI backend with only the Gemini-vision seam mocked, so its
 * images are evidence about behaviour. This script is not that, and must not be
 * read as that. It stubs the API at the network boundary and renders the
 * screen, so its images are evidence about *layout* — which is what a surface
 * design review needs, and all it needs.
 *
 * It exists because both of the alternatives were worse:
 *
 *   - The real corpus is blocked by BUILD/BLOCKERS.md B4: a `python -m
 *     lemely.web` process belonging to another local user has held port 8000
 *     since Aug 12, and `reuseExistingServer` makes Playwright adopt it instead
 *     of starting `scripts/e2e_server.py`. Killing another user's process
 *     unattended is not something this build does.
 *   - Signing a fresh student up against that adopted backend would only ever
 *     render the zero-paper first-run view. The populated ledger, and the
 *     one-paper state where the momentum panel is legitimately empty, are the
 *     two states this surface's changes are actually about, and neither is
 *     reachable without seeded history.
 *
 * Stubbing makes every state deterministic and reproducible, including the
 * loading and error states, which no amount of real seeding can trigger on
 * demand. The fixture below is shaped field-for-field like `OverviewDTO`
 * (`lemely/web/schemas_student.py`) and its numbers are invented for the
 * capture — they are not product data, they are never shipped, and no claim in
 * any report is derived from them.
 *
 * Usage:  node scripts/capture_surface.mjs [outDir]
 * Assumes `npm run build` has run; serves `dist/` on a local port.
 */

import { spawn } from "node:child_process"
import { createHash } from "node:crypto"
import fs from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"
import { chromium } from "@playwright/test"

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.resolve(__dirname, "..", "..")
const outDir = path.resolve(
  process.argv[2] ?? path.join(repoRoot, "reports", "redesign", "p4-student-dashboard"),
)
const PORT = 4319
const BASE = `http://127.0.0.1:${PORT}`

/** Widths the gate requires per surface milestone: desktop plus 375. */
const VIEWPORTS = [
  { name: "1440", width: 1440, height: 1000 },
  { name: "375", width: 375, height: 900 },
]

/**
 * An unsigned JWT with a far-future `exp`.
 *
 * The client only ever *decodes* this (`lib/auth/jwt.ts` reads `exp`); it is
 * the server that verifies signatures, and no request in this run reaches a
 * server. A real token would be a credential in the repo, which is the thing
 * not to do.
 */
function fakeJwt(hoursAhead = 24) {
  const header = Buffer.from(JSON.stringify({ alg: "none", typ: "JWT" })).toString("base64url")
  const payload = Buffer.from(
    JSON.stringify({ sub: "capture-student", exp: Math.floor(Date.now() / 1000) + hoursAhead * 3600 }),
  ).toString("base64url")
  return `${header}.${payload}.`
}

const SESSION = {
  accessToken: fakeJwt(),
  refreshToken: fakeJwt(72),
  userId: "capture-student",
  role: "student",
}

const PROFILE = {
  userId: "capture-student",
  email: "amina@example.com",
  displayName: "Amina Farouk",
  role: "student",
}

/** Field-for-field `OverviewDTO`. Numbers are invented for the capture. */
function overview({ subjects, momentumPoints, weak }) {
  const series = momentumPoints
  const mx = (i) => (series.length < 2 ? 0 : (i / (series.length - 1)) * 300)
  const my = (v) => 88 - ((v - 55) / 45) * 78
  const path2 =
    series.length < 2
      ? ""
      : series.map((v, i) => `${i ? "L" : "M"}${mx(i).toFixed(1)} ${my(v).toFixed(1)}`).join(" ")
  const last = series.length - 1
  return {
    studentName: "Amina",
    forecast: subjects.map((s) => s.grade).join(" "),
    subjects,
    weakGlobal: weak,
    momentum: {
      path: path2,
      area: path2 === "" ? "" : `${path2} L300 88 L0 88 Z`,
      lastX: series.length < 2 ? "0.0" : mx(last).toFixed(1),
      lastY: series.length < 2 ? "88.0" : my(series[last]).toFixed(1),
      labels: series.length < 2 ? [] : series.map((_, i) => `2026-0${i + 1}`),
    },
  }
}

const SUBJECTS_FULL = [
  {
    code: "0625",
    name: "0625",
    detail: "4 papers corrected",
    pct: 72,
    papers: 4,
    trend: "+9",
    grade: "B",
    barColor: "ok",
    trendUp: true,
  },
  {
    code: "0580",
    name: "0580",
    detail: "3 papers corrected",
    pct: 64,
    papers: 3,
    trend: "-4",
    grade: "C",
    barColor: "warn",
    trendUp: false,
  },
  {
    code: "0606",
    name: "0606",
    detail: "1 paper corrected",
    pct: 51,
    papers: 1,
    trend: "+0",
    grade: "E",
    barColor: "warn",
    trendUp: true,
  },
]

const WEAK = [
  { topic: "Moments and equilibrium", acc: "41%", width: 41, color: "warn" },
  { topic: "Thermal energy transfer", acc: "55%", width: 55, color: "warn" },
  { topic: "Electromagnetic induction", acc: "62%", width: 62, color: "accent" },
  { topic: "Kinematics graphs", acc: "68%", width: 68, color: "accent" },
]

/*
 * The five states this surface has to be right in. `populated` and `onePaper`
 * are the two the P4.1 changes are about: `onePaper` is the exact state that
 * used to render an empty plot box with a stray dot in the corner.
 */
const STATES = {
  populated: {
    body: overview({ subjects: SUBJECTS_FULL, momentumPoints: [58, 63, 61, 72], weak: WEAK }),
  },
  /*
   * Exactly one grade-bearing paper, so the momentum panel is legitimately
   * empty. The subject row must agree — an earlier version of this fixture
   * paired "4 papers corrected" with a single momentum point, which the real
   * endpoint can never produce and which made the capture argue for a state
   * that does not exist.
   */
  "one-paper": {
    body: overview({
      subjects: [
        { ...SUBJECTS_FULL[0], detail: "1 paper corrected", papers: 1, trend: "+0", trendUp: true },
      ],
      momentumPoints: [58],
      weak: [],
    }),
  },
  "first-run": {
    body: overview({ subjects: [], momentumPoints: [], weak: [] }),
  },
  loading: { delayMs: 8_000 },
  error: { status: 500, body: { detail: "Overview is temporarily unavailable." } },
}

function serveDist() {
  const child = spawn(
    "npx",
    ["vite", "preview", "--port", String(PORT), "--strictPort", "--host", "127.0.0.1"],
    { cwd: path.join(repoRoot, "web"), stdio: ["ignore", "pipe", "pipe"] },
  )
  return child
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
  fs.mkdirSync(outDir, { recursive: true })
  const server = serveDist()
  const consoleErrors = []
  try {
    await waitForServer()
    const browser = await chromium.launch()

    for (const vp of VIEWPORTS) {
      for (const [stateName, state] of Object.entries(STATES)) {
        const context = await browser.newContext({
          viewport: { width: vp.width, height: vp.height },
          deviceScaleFactor: 2,
        })
        await context.addInitScript(
          ([session, key]) => {
            window.localStorage.setItem(key, JSON.stringify(session))
            window.localStorage.setItem("lemely.deviceId", "capture-device")
          },
          [SESSION, "lemely.session"],
        )

        const page = await context.newPage()
        page.on("console", (msg) => {
          if (msg.type() === "error") consoleErrors.push(`[${vp.name}/${stateName}] ${msg.text()}`)
        })

        /*
         * Registration order is load-bearing and cost one bad capture round:
         * Playwright matches the MOST RECENTLY registered route first, so with
         * the catch-all added last it swallowed `/api/me/profile` too, the
         * profile came back as `{}`, and `data.role.split("_")` threw. Every
         * one of the ten images was then the same error screen — which is why
         * the file sizes being byte-identical per viewport was the tell.
         *
         * The catch-all therefore goes FIRST and the specific stubs after it.
         * Its job is to make sure nothing here can silently reach the real
         * port-8000 process B4 describes.
         */
        await page.route("**/api/**", (route) =>
          route.fulfill({ status: 200, contentType: "application/json", body: "{}" }),
        )
        await page.route("**/api/me/profile", (route) =>
          route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(PROFILE) }),
        )
        await page.route("**/api/student/overview", async (route) => {
          if (state.delayMs) {
            // Never fulfilled: this is how the skeleton is captured. The
            // context is torn down before the delay elapses.
            await new Promise((r) => setTimeout(r, state.delayMs))
            return
          }
          await route.fulfill({
            status: state.status ?? 200,
            contentType: "application/json",
            body: JSON.stringify(state.body),
          })
        })
        await page.goto(`${BASE}/student`, { waitUntil: "domcontentloaded" })
        // The screen's own entry animation is 320ms (`--dur-base`); settle past
        // it so a capture never catches a half-faded page.
        await page.waitForTimeout(state.delayMs ? 900 : 1400)

        const file = path.join(outDir, `overview--${stateName}--${vp.name}.png`)
        await page.screenshot({ path: file, fullPage: !state.delayMs })
        console.log(`captured ${path.relative(repoRoot, file)}`)
        await context.close()
      }
    }
    await browser.close()
  } finally {
    server.kill("SIGTERM")
  }

  /*
   * Five distinct states must produce five distinct images. The first run of
   * this script produced ten files that were byte-identical per viewport,
   * because a route-ordering mistake made every state render the same error
   * screen — and nothing said so. A capture round that silently photographs
   * the same screen five times is worse than no capture round, because it
   * looks like evidence. So this is asserted rather than eyeballed.
   */
  const duplicates = []
  for (const vp of VIEWPORTS) {
    const seen = new Map()
    for (const stateName of Object.keys(STATES)) {
      const file = path.join(outDir, `overview--${stateName}--${vp.name}.png`)
      const digest = createHash("sha256").update(fs.readFileSync(file)).digest("hex")
      if (seen.has(digest)) duplicates.push(`${vp.name}: ${seen.get(digest)} == ${stateName}`)
      else seen.set(digest, stateName)
    }
  }
  if (duplicates.length) {
    throw new Error(
      `identical captures for states that must differ:\n  ${duplicates.join("\n  ")}`,
    )
  }
  console.log(`\n${VIEWPORTS.length * Object.keys(STATES).length} captures, all distinct`)

  const logPath = path.join(outDir, "console-errors.txt")
  fs.writeFileSync(
    logPath,
    consoleErrors.length ? consoleErrors.join("\n") + "\n" : "none\n",
    "utf8",
  )
  console.log(
    consoleErrors.length
      ? `\n${consoleErrors.length} console error(s) — see ${path.relative(repoRoot, logPath)}`
      : "\nno console errors",
  )
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
