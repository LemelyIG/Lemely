#!/usr/bin/env node
/**
 * P2.5.6 Puppeteer audit runner — standalone from the Playwright E2E/
 * screenshot suite (web/e2e/screenshots.spec.ts), per BUILD/MISSION.md §11's
 * division of labour: Playwright owns behaviour + the screenshot corpus,
 * Puppeteer owns audit + measurement (axe-core, Lighthouse, console-error
 * collection) so it can run against a *built* preview independently of the
 * E2E suite.
 *
 * Runs against `vite preview` (not `vite dev`) because Lighthouse's PWA-
 * adjacent checks need the real built service worker (vite-plugin-pwa only
 * generates it during `npm run build`), and `vite preview` needs its own
 * `preview.proxy` block to reach the backend (see web/vite.config.ts).
 *
 * Scope (BUILD/DECISIONS.md D2.10 — do not expand): exactly the 4 routes
 * Phase 2.5 retrofitted onto the token system + component library:
 *   /login                    (G-04)
 *   /student                  (S-06, audited non-empty — after the upload)
 *   /student/correct           (S-10 entry)
 *   /student/result/:paperId   (S-15/S-17, needs a real paperId)
 *
 * Usage: `npm run audit` (from web/), or `node scripts/audit.mjs` directly.
 * Builds the frontend, boots the real backend (scripts/e2e_server.py, only
 * the Gemini-vision seam mocked) and a `vite preview` server, signs up a
 * fresh student, logs in through the real UI, uploads
 * tests/golden/0625_m20_qp_12_mcq/scan.pdf to reach a real corrected-paper
 * state, then audits all 4 routes and regenerates the contact sheet from
 * whatever is actually in reports/phase-2.5/screens/ (both this script's
 * captures and the existing Playwright ones).
 *
 * Output (all under reports/phase-2.5/, kept out of this script's own
 * stdout per MISSION §11 — "never let a Lighthouse or axe JSON dump land in
 * context"):
 *   axe/<route-slug>.json, axe/_summary.json
 *   lighthouse/<route-slug>.json, lighthouse/_summary.json
 *   screens/G-04/<state>--<bp>.png              (only route with no existing
 *                                                 Playwright capture)
 *   console-errors.json
 *   contact-sheet.html
 */

import { spawn, execSync } from "node:child_process"
import fs from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"
import puppeteer from "puppeteer"
import lighthouse from "lighthouse"

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const webRoot = path.resolve(__dirname, "..")
const repoRoot = path.resolve(webRoot, "..")

const BACKEND_URL = "http://127.0.0.1:8000"
const PREVIEW_PORT = 4173
const PREVIEW_URL = `http://127.0.0.1:${PREVIEW_PORT}`
const PASSWORD = "CorrectHorseBattery9!"
const SCAN_PATH = path.resolve(repoRoot, "tests/golden/0625_m20_qp_12_mcq/scan.pdf")
const AXE_SCRIPT = path.resolve(webRoot, "node_modules/axe-core/axe.min.js")

// Where this run's artifacts land. Defaults to a gitignored scratch dir so a
// routine `./scripts/check.sh` never overwrites a committed phase baseline —
// that would destroy the very reference MISSION §11's "an unintended diff is a
// blocker" rule compares against. Re-baselining is explicit:
//   LEMELY_REPORT_DIR=reports/phase-3 npm run audit
// Keep this default in sync with scripts/check_ui_gates.py's.
const REPORT_DIR_SETTING = process.env.LEMELY_REPORT_DIR || "reports/.scratch"
const REPORTS_DIR = path.isAbsolute(REPORT_DIR_SETTING)
  ? REPORT_DIR_SETTING
  : path.resolve(repoRoot, REPORT_DIR_SETTING)
const AXE_DIR = path.join(REPORTS_DIR, "axe")
const LH_DIR = path.join(REPORTS_DIR, "lighthouse")
const SCREENS_DIR = path.join(REPORTS_DIR, "screens")
const CONSOLE_ERRORS_PATH = path.join(REPORTS_DIR, "console-errors.json")
const CONTACT_SHEET_PATH = path.join(REPORTS_DIR, "contact-sheet.html")

const BREAKPOINTS = [
  { width: 380, height: 844 },
  { width: 768, height: 1024 },
  { width: 1440, height: 900 },
]
const AUDIT_VIEWPORT = { width: 1440, height: 900 }

// Lighthouse 13.4.1 (the pinned devDependency) has no PWA category at all —
// Google removed the PWA category and its audits (installable-manifest,
// splash-screen, themed-omnibox, service-worker, ...) upstream around
// Lighthouse v11/v12; there is no config path that brings it back without a
// different major version. Confirmed by grepping
// node_modules/lighthouse/core/config/default-config.js and
// core/audits/ for any 'pwa' category or PWA-specific audit — none exist.
// Auditing the 3 categories that remain (+ seo, which is free) rather than
// silently dropping the requirement; see the final report for this gap.
const LIGHTHOUSE_CATEGORIES = ["performance", "accessibility", "best-practices", "seo"]

/** Resolve local Supabase stack keys the same way web/playwright.config.ts
 * does — this sandbox's non-interactive shells don't have `supabase` (at
 * ~/.local/bin) on PATH otherwise. */
function resolveSupabaseEnv() {
  const raw = execSync("supabase status -o json", {
    stdio: ["ignore", "pipe", "ignore"],
    env: { ...process.env, PATH: `${process.env.HOME}/.local/bin:${process.env.PATH}` },
  }).toString()
  const status = JSON.parse(raw)
  return {
    LEMELY_SUPABASE__SERVICE_ROLE_KEY: status.SERVICE_ROLE_KEY,
    LEMELY_SUPABASE__ANON_KEY: status.ANON_KEY,
  }
}

function log(msg) {
  process.stdout.write(`[audit] ${msg}\n`)
}

function uniqueEmail(tag) {
  return `puppet-audit-${tag}-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`
}

function pipeChildLogs(child, label) {
  child.stdout?.on("data", (chunk) => {
    if (process.env.AUDIT_VERBOSE) process.stdout.write(`[${label}] ${chunk}`)
  })
  child.stderr?.on("data", (chunk) => {
    if (process.env.AUDIT_VERBOSE) process.stderr.write(`[${label}] ${chunk}`)
  })
}

async function waitForHttp(url, timeoutMs) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    try {
      const res = await fetch(url, { signal: AbortSignal.timeout(2_000) })
      // Any real HTTP response (even 404) means the server is up.
      void res.status
      return
    } catch {
      await new Promise((resolve) => setTimeout(resolve, 500))
    }
  }
  throw new Error(`Timed out waiting for ${url} to respond`)
}

/** Collects console `error` messages and uncaught page errors for the whole
 * run, so every route's console-error gate (QUALITY-BAR.md: zero tolerance)
 * can be checked. Excludes the browser's own "Failed to load resource: ...
 * 4xx/5xx" logging for the one route (/login, wrong-password) where this
 * suite deliberately triggers a real 401 to capture the error state — same
 * justified exclusion as web/e2e/screenshots.spec.ts's watchConsole. */
function watchConsole(page, errors) {
  page.on("console", (msg) => {
    if (msg.type() === "error" && !/^Failed to load resource:/.test(msg.text())) {
      errors.push({ type: "console", text: msg.text(), url: page.url() })
    }
  })
  page.on("pageerror", (err) => {
    errors.push({ type: "pageerror", text: err.message, url: page.url() })
  })
}

async function waitForText(page, pattern, timeout = 15_000) {
  await page.waitForFunction(
    (source) => new RegExp(source, "i").test(document.body.innerText),
    { timeout },
    pattern,
  )
}

async function clickButtonByText(page, pattern, timeout = 15_000) {
  const handle = await page.waitForFunction(
    (source) => {
      const re = new RegExp(source, "i")
      return (
        Array.from(document.querySelectorAll("button")).find(
          (b) => re.test(b.textContent || "") && !b.disabled,
        ) ?? null
      )
    },
    { timeout },
    pattern,
  )
  const element = handle.asElement()
  if (!element) throw new Error(`No enabled button matching ${pattern}`)
  await element.click()
}

/** Full-page capture at reports/phase-2.5/screens/<screenId>/<state>--<bp>.png
 * — same path convention as web/e2e/screenshots.spec.ts's `shoot`. Only used
 * for G-04 (login), which has no existing Playwright capture; S-06/S-10/
 * S-15/S-17 are already covered by that suite and are not re-captured here. */
async function shoot(page, screenId, state, bpWidth) {
  const dir = path.join(SCREENS_DIR, screenId)
  fs.mkdirSync(dir, { recursive: true })
  await page.screenshot({ path: path.join(dir, `${state}--${bpWidth}.png`), fullPage: true })
}

async function runAxe(page, slug) {
  await page.addScriptTag({ path: AXE_SCRIPT })
  const results = await page.evaluate(() => window.axe.run())
  fs.writeFileSync(path.join(AXE_DIR, `${slug}.json`), JSON.stringify(results, null, 2))
  const counts = { critical: 0, serious: 0, moderate: 0, minor: 0 }
  for (const v of results.violations) {
    if (v.impact && counts[v.impact] !== undefined) counts[v.impact] += 1
  }
  return { slug, url: results.url, violationCount: results.violations.length, counts }
}

async function runLighthouseAudit(url, page, slug, { authed }) {
  const result = await lighthouse(
    url,
    {
      onlyCategories: LIGHTHOUSE_CATEGORIES,
      logLevel: "error",
      // Preserve the localStorage session across the audit's own internal
      // navigation for authenticated routes — Lighthouse clears all origin
      // storage before each run by default (Storage.clearDataForOrigin).
      disableStorageReset: authed,
    },
    undefined,
    page,
  )
  const lhr = result.lhr
  fs.writeFileSync(path.join(LH_DIR, `${slug}.json`), JSON.stringify(lhr, null, 2))
  const scores = {}
  for (const cat of LIGHTHOUSE_CATEGORIES) {
    scores[cat] = lhr.categories[cat] ? Math.round(lhr.categories[cat].score * 100) : null
  }
  return { slug, scores }
}

async function main() {
  fs.mkdirSync(AXE_DIR, { recursive: true })
  fs.mkdirSync(LH_DIR, { recursive: true })
  fs.mkdirSync(SCREENS_DIR, { recursive: true })

  log("Resolving local Supabase stack keys...")
  const supabaseEnv = resolveSupabaseEnv()

  log("Building frontend (npm run build) so the PWA service worker + built assets are real...")
  execSync("npm run build", { cwd: webRoot, stdio: process.env.AUDIT_VERBOSE ? "inherit" : "ignore" })

  log("Starting backend (scripts/e2e_server.py)...")
  const backend = spawn(path.join(repoRoot, ".venv/bin/python"), ["scripts/e2e_server.py"], {
    cwd: repoRoot,
    env: { ...process.env, ...supabaseEnv },
  })
  pipeChildLogs(backend, "backend")
  await waitForHttp(`${BACKEND_URL}/docs`, 30_000)
  log("Backend up.")

  log("Starting preview server (vite preview)...")
  const preview = spawn(
    path.join(webRoot, "node_modules/.bin/vite"),
    ["preview", "--host", "127.0.0.1", "--port", String(PREVIEW_PORT), "--strictPort"],
    { cwd: webRoot },
  )
  pipeChildLogs(preview, "preview")
  await waitForHttp(PREVIEW_URL, 30_000)
  log("Preview server up.")

  const shutdown = () => {
    backend.kill("SIGTERM")
    preview.kill("SIGTERM")
  }

  const axeSummary = []
  const lighthouseSummary = []
  const consoleErrors = []

  let browser
  try {
    browser = await puppeteer.launch({ headless: true })
    const page = await browser.newPage()
    watchConsole(page, consoleErrors)

    // ── G-04 · Log in — unaudited/unauthenticated, must run before any
    // login so /login doesn't self-redirect away from an existing session
    // (App.tsx's LoginRoute navigates to the portal home if session is set).
    log("G-04 /login — default state (3 breakpoints)...")
    for (const bp of BREAKPOINTS) {
      await page.setViewport(bp)
      await page.goto(`${PREVIEW_URL}/login`, { waitUntil: "networkidle0" })
      await waitForText(page, "Lemely")
      await shoot(page, "G-04", "default", bp.width)
    }

    log("G-04 /login — error state (invalid credentials, 3 breakpoints)...")
    for (const bp of BREAKPOINTS) {
      await page.setViewport(bp)
      await page.goto(`${PREVIEW_URL}/login`, { waitUntil: "networkidle0" })
      const emailInput = await page.$("input[type=email]")
      const passwordInput = await page.$("input[type=password]")
      await emailInput.type("nonexistent-audit-user@example.com")
      await passwordInput.type("WrongPassword1!")
      await clickButtonByText(page, "^sign in$")
      await page.waitForSelector("form p", { timeout: 15_000 })
      await shoot(page, "G-04", "error", bp.width)
    }

    log("G-04 /login — loading state (delayed submit, 3 breakpoints)...")
    for (const bp of BREAKPOINTS) {
      await page.setViewport(bp)
      await page.goto(`${PREVIEW_URL}/login`, { waitUntil: "networkidle0" })
      await page.setRequestInterception(true)
      const onRequest = (req) => {
        if (req.url().includes("/api/auth/login")) {
          setTimeout(() => req.continue().catch(() => {}), 2_000)
        } else {
          req.continue().catch(() => {})
        }
      }
      page.on("request", onRequest)
      const emailInput = await page.$("input[type=email]")
      const passwordInput = await page.$("input[type=password]")
      await emailInput.type("nonexistent-audit-user@example.com")
      await passwordInput.type("WrongPassword1!")
      await clickButtonByText(page, "^sign in$")
      await waitForText(page, "Signing in")
      await shoot(page, "G-04", "loading", bp.width)
      page.off("request", onRequest)
      await page.setRequestInterception(false)
    }

    log("G-04 /login — axe + Lighthouse (default state)...")
    await page.setViewport(AUDIT_VIEWPORT)
    await page.goto(`${PREVIEW_URL}/login`, { waitUntil: "networkidle0" })
    await waitForText(page, "Lemely")
    axeSummary.push(await runAxe(page, "login"))
    lighthouseSummary.push(
      await runLighthouseAudit(`${PREVIEW_URL}/login`, page, "login", { authed: false }),
    )

    // ── Authenticated flow: sign up (direct API, matches
    // web/e2e/screenshots.spec.ts's apiSignUp), log in through the real UI,
    // upload the golden fixture to reach a real corrected-paper state. ──
    const email = uniqueEmail("main")
    log(`Signing up ${email} via direct API POST...`)
    const signupRes = await fetch(`${BACKEND_URL}/api/auth/signup`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ email, password: PASSWORD, role: "student" }),
    })
    if (!signupRes.ok) {
      throw new Error(`signup failed: ${signupRes.status} ${await signupRes.text()}`)
    }

    log("Logging in through the real UI...")
    await page.setViewport(AUDIT_VIEWPORT)
    await page.goto(`${PREVIEW_URL}/login`, { waitUntil: "networkidle0" })
    const emailInput = await page.$("input[type=email]")
    const passwordInput = await page.$("input[type=password]")
    await emailInput.type(email)
    await passwordInput.type(PASSWORD)
    await clickButtonByText(page, "^sign in$")
    await page.waitForFunction(() => location.pathname.startsWith("/student"), { timeout: 15_000 })
    log("Logged in.")

    // ── S-10 · Correct a paper — entry/default state audit, before upload ──
    log("S-10 /student/correct — axe + Lighthouse (entry state)...")
    await page.goto(`${PREVIEW_URL}/student/correct`, { waitUntil: "networkidle0" })
    await waitForText(page, "Correct a paper")
    axeSummary.push(await runAxe(page, "student-correct"))
    lighthouseSummary.push(
      await runLighthouseAudit(`${PREVIEW_URL}/student/correct`, page, "student-correct", {
        authed: true,
      }),
    )

    log("Uploading the golden fixture to reach a real corrected-paper state...")
    await page.goto(`${PREVIEW_URL}/student/correct`, { waitUntil: "networkidle0" })
    const fileInput = await page.$("#scan-file")
    await fileInput.uploadFile(SCAN_PATH)
    await clickButtonByText(page, "mark this paper")
    await page.waitForFunction(() => location.pathname.includes("/student/result/"), {
      timeout: 60_000,
    })
    const resultUrl = page.url()
    const paperId = new URL(resultUrl).pathname.split("/student/result/")[1]
    log(`Corrected paper reached: ${resultUrl} (paperId=${paperId})`)

    // ── S-15/S-17 · Paper result — real paperId, real marked data ──────────
    log("S-15/S-17 /student/result/:paperId — axe + Lighthouse...")
    // MarkDisplay (C-2) renders "5/8" as visible text and puts "5 out of 8
    // marks, ..." only in an aria-label — document.body.innerText (what
    // waitForText checks) never surfaces aria-label content, so wait on the
    // accessible attribute directly instead (mirrors Playwright's
    // getByLabel(/out of .* marks/) in web/e2e/screenshots.spec.ts).
    await page.waitForSelector('[aria-label*="out of"]', { timeout: 15_000 })
    axeSummary.push(await runAxe(page, "student-result"))
    lighthouseSummary.push(
      await runLighthouseAudit(resultUrl, page, "student-result", { authed: true }),
    )

    // ── S-06 · Student overview — now non-empty (one corrected paper) ──────
    log("S-06 /student — axe + Lighthouse (non-empty, after correction)...")
    await page.goto(`${PREVIEW_URL}/student`, { waitUntil: "networkidle0" })
    await waitForText(page, "Subjects this session")
    axeSummary.push(await runAxe(page, "student-overview"))
    lighthouseSummary.push(
      await runLighthouseAudit(`${PREVIEW_URL}/student`, page, "student-overview", {
        authed: true,
      }),
    )
  } finally {
    if (browser) await browser.close()
    shutdown()
  }

  fs.writeFileSync(
    path.join(AXE_DIR, "_summary.json"),
    JSON.stringify(axeSummary, null, 2),
  )
  fs.writeFileSync(
    path.join(LH_DIR, "_summary.json"),
    JSON.stringify(lighthouseSummary, null, 2),
  )
  fs.writeFileSync(CONSOLE_ERRORS_PATH, JSON.stringify(consoleErrors, null, 2))

  generateContactSheet()

  log("─────────────────────────────────────────────")
  log("axe violation counts by severity (critical/serious/moderate/minor):")
  for (const r of axeSummary) {
    log(
      `  ${r.slug.padEnd(20)} ${r.counts.critical}/${r.counts.serious}/${r.counts.moderate}/${r.counts.minor}  (total ${r.violationCount})`,
    )
  }
  log("Lighthouse scores (performance/accessibility/best-practices/seo):")
  for (const r of lighthouseSummary) {
    log(
      `  ${r.slug.padEnd(20)} ${r.scores.performance}/${r.scores.accessibility}/${r.scores["best-practices"]}/${r.scores.seo}`,
    )
  }
  log(`Console errors collected: ${consoleErrors.length}`)
  log(`Contact sheet: ${CONTACT_SHEET_PATH}`)
}

/** Regenerates reports/phase-2.5/contact-sheet.html from whatever is
 * actually under reports/phase-2.5/screens/ at generation time (both this
 * script's captures and the Playwright screenshot corpus), so it stays
 * valid as the corpus grows in later phases. No external network calls, no
 * build step — a single static file, open it directly. */
function generateContactSheet() {
  const screenIds = fs.existsSync(SCREENS_DIR)
    ? fs.readdirSync(SCREENS_DIR, { withFileTypes: true })
        .filter((d) => d.isDirectory())
        .map((d) => d.name)
        .sort()
    : []

  const sections = screenIds.map((screenId) => {
    const dir = path.join(SCREENS_DIR, screenId)
    const files = fs
      .readdirSync(dir)
      .filter((f) => f.endsWith(".png"))
      .sort()
    const thumbs = files
      .map((f) => {
        const label = f.replace(/\.png$/, "")
        const src = `screens/${screenId}/${f}`
        return `
        <figure class="thumb">
          <a href="${src}" target="_blank" rel="noopener noreferrer">
            <img src="${src}" alt="${screenId} — ${label}" loading="lazy" />
          </a>
          <figcaption>${label}</figcaption>
        </figure>`
      })
      .join("\n")
    return `
    <section class="screen">
      <h2>${screenId} <span class="count">(${files.length})</span></h2>
      <div class="grid">${thumbs}
      </div>
    </section>`
  })

  const html = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>Lemely — Phase 2.5 contact sheet</title>
<style>
  :root { color-scheme: light; }
  body { font-family: system-ui, sans-serif; margin: 0; padding: 24px 32px 64px; background: #faf4f2; color: #1e1310; }
  h1 { font-size: 22px; margin-bottom: 4px; }
  .meta { color: #6b5b54; font-size: 13px; margin-bottom: 32px; }
  h2 { font-size: 16px; border-bottom: 1px solid #e3d5cf; padding-bottom: 6px; margin-top: 40px; }
  .count { font-weight: 400; color: #9a877d; font-size: 13px; }
  .grid { display: flex; flex-wrap: wrap; gap: 16px; margin-top: 12px; }
  figure.thumb { margin: 0; width: 220px; }
  figure.thumb img { width: 100%; height: auto; border: 1px solid #e3d5cf; border-radius: 6px; display: block; background: #fff; }
  figcaption { font-size: 11.5px; color: #6b5b54; margin-top: 4px; word-break: break-all; text-align: center; }
</style>
</head>
<body>
  <h1>Lemely — Phase 2.5 visual QA contact sheet</h1>
  <p class="meta">Generated ${new Date().toISOString()} from reports/phase-2.5/screens/. ${screenIds.length} screen(s), ${screenIds.reduce((n, id) => n + fs.readdirSync(path.join(SCREENS_DIR, id)).filter((f) => f.endsWith(".png")).length, 0)} screenshot(s).</p>
  ${sections.join("\n")}
</body>
</html>
`
  fs.writeFileSync(CONTACT_SHEET_PATH, html)
}

main().catch((err) => {
  console.error("[audit] FAILED:", err)
  process.exitCode = 1
})
