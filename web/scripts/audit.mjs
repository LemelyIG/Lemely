#!/usr/bin/env node
/**
 * Puppeteer audit runner — standalone from the Playwright E2E/screenshot
 * suite (web/e2e/screenshots.spec.ts), per BUILD/MISSION.md §11's division of
 * labour: Playwright owns behaviour + the screenshot corpus, Puppeteer owns
 * audit + measurement (axe-core, Lighthouse, console-error collection,
 * responsive/horizontal-scroll) so it can run against a *built* preview
 * independently of the E2E suite.
 *
 * Runs against `vite preview` (not `vite dev`) because Lighthouse's PWA-
 * adjacent checks need the real built service worker (vite-plugin-pwa only
 * generates it during `npm run build`), and `vite preview` needs its own
 * `preview.proxy` block to reach the backend (see web/vite.config.ts).
 *
 * ── Scope (P3.10 chunk b — supersedes D2.10's 4-route scope) ──────────────
 * D2.10 fixed this at exactly 4 student routes; every teacher/parent screen
 * built in P3.7–P3.9 was outside it, so the gate passed by never looking (it
 * is how `text-t3`'s 4.36:1 contrast and a parent-shell `button-name`
 * violation both shipped undetected — see BUILD/STATE.md's P3.10 section).
 * `ROUTE_REGISTRY` below is the full Phase-3 inventory — a declarative
 * table, not a hardcoded journey — covering (counts as of P3.10 chunk e2a):
 *   - 4 unauthenticated/student routes carried over from D2.10, run through
 *     `runStudentMainJourney()` because they are inherently a stateful
 *     sequence (sign up -> log in -> upload a real scan -> get a real
 *     paperId), not a bare navigation: /login (G-04), /student (S-06,
 *     non-empty), /student/correct (S-10), /student/result/:paperId
 *     (S-15/S-17).
 *   - 22 registry entries run through the generic `visitRoute()` runner,
 *     reached by injecting a real session (a genuine access token from
 *     `scripts/seed_e2e.py`, decoded server-side exactly as a real login
 *     would produce — see `injectSession`) into `localStorage` and
 *     navigating directly, rather than re-driving each role's login UI for
 *     every route: G-05 (unauthenticated), 15 teacher entries (two of them
 *     `T-01`, one populated one `emptyTeacher`), 5 parent entries (two of
 *     them `P-01`, same split), and the student's `/student/parents`. Several
 *     entries carry more than one `states[]` capture (see below), so the
 *     actual number of axe passes this run performs is higher than 22 — see
 *     `main()`'s end-of-run log for the honest total.
 * Deliberately still NOT in this registry (P4/P5 screens still on mock data):
 *   /student/subject/:code, /student/plan, /student/board, /student/onboard,
 *   /student/landing, /student/directions.
 * Note "no *populated* fixture" is NOT on its own a reason to leave a route
 * out: /teacher/grading and /teacher/schemes are audited in their genuinely
 * empty state, because an unlooked-at route is exactly how this gate became
 * vacuous.
 *
 * ── States (P3.10 chunk e2a — per-route `states[]`) ────────────────────────
 * A registry route may carry an optional `states: [{state, slug, setup?,
 * ready?, teardown?, waitUntil?, lighthouse?}]` array. No `states` means
 * exactly what it always meant: one implicit `"default"` state using the
 * route's own top-level `slug`/`ready` — every route that predates this
 * chunk is unchanged. `setup(page)` runs once before that state's captures
 * (screenshots + axe); `teardown(page)` runs once after, in a `finally` so a
 * capture failure can't leak request interception / offline mode into the
 * next state or route sharing this session's page. `lighthouse` defaults
 * `true`; every non-canonical state in a multi-state array sets it `false`
 * explicitly (see the decision note at `visitRoute`, below).
 * Three new zero-coverage routes were the point of this chunk (T-08/
 * T-09-detail/T-10 — see BUILD/STATE.md's P3.10 section for why they were
 * unreachable before e1 seeded a real review item and a real quiz), each
 * with real `loading`/`error` states via request interception (reusing the
 * pattern `main()`'s G-04 section already proved, not a second one), plus
 * T-08's real `low-confidence`/`teacher-corrected` pair driven through the
 * actual UI. `empty` (a genuinely empty seeded account, never a stubbed
 * payload) needs its own session, so it is a *separate* registry entry
 * sharing the primary route's `screenId`, not a `states[]` entry — see the
 * `emptyTeacher`/`emptyParent` entries below. `offline` (CDP) is a `states[]`
 * entry (same session, same context) on T-01.
 *
 * Usage: `npm run audit` (from web/), or `node scripts/audit.mjs` directly.
 * Builds the frontend, runs `scripts/seed_e2e.py` for the multi-role
 * fixture, boots the real backend (scripts/e2e_server.py, only the
 * Gemini-vision seam mocked) and a `vite preview` server, then walks every
 * route in `ROUTE_REGISTRY`, regenerating the contact sheet from whatever is
 * actually in `$LEMELY_REPORT_DIR/screens/` (both this script's captures and
 * the existing Playwright ones) at the end.
 *
 * Output (under `$LEMELY_REPORT_DIR`, default `reports/.scratch`, kept out
 * of this script's own stdout per MISSION §11 — "never let a Lighthouse or
 * axe JSON dump land in context"):
 *   axe/<route-slug>.json, axe/_summary.json
 *   lighthouse/<route-slug>.json, lighthouse/_summary.json
 *   responsive-summary.json      (horizontal-scroll violations, empty = clean)
 *   screens/<screen-id>/<state>--<bp>.png
 *   console-errors.json
 *   contact-sheet.html
 */

import { spawn, execSync, spawnSync } from "node:child_process"
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
const RESPONSIVE_SUMMARY_PATH = path.join(REPORTS_DIR, "responsive-summary.json")
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

/** Full-page capture at `$LEMELY_REPORT_DIR/screens/<screenId>/<state>--<bp>.png`
 * — same path convention as web/e2e/screenshots.spec.ts's `shoot`. */
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

/** Fails loudly (throws) if the page has horizontal overflow at its current
 * viewport — MISSION §11's "no horizontal scroll at any breakpoint from
 * 320px up" as a real, non-optional check rather than something only a
 * screenshot review would catch. 1px tolerance for sub-pixel rounding. */
async function checkNoHorizontalScroll(page, slug, bpWidth) {
  const { scrollWidth, clientWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }))
  if (scrollWidth <= clientWidth + 1) return null

  // Only walk the DOM once we know there IS a violation — naming the
  // offending elements is the difference between a fixable report and
  // "something on this page is 10px too wide", but it is wasted work on the
  // (overwhelmingly common) clean case.
  const offenders = await page.evaluate(() => {
    const clientWidth = document.documentElement.clientWidth
    const offenders = []
    for (const el of document.querySelectorAll("body *")) {
      const rect = el.getBoundingClientRect()
      if (rect.width === 0 && rect.height === 0) continue
      const overhang = Math.round(rect.right - clientWidth)
      if (overhang <= 1) continue
      const cls = typeof el.className === "string" ? el.className : ""
      offenders.push({
        overhang,
        tag: el.tagName.toLowerCase(),
        id: el.id || null,
        className: cls.slice(0, 200) || null,
        width: Math.round(rect.width),
        left: Math.round(rect.left),
        text: (el.textContent || "").trim().slice(0, 60) || null,
      })
    }
    offenders.sort((a, b) => b.overhang - a.overhang)
    return offenders.slice(0, 8)
  })
  return { slug, bpWidth, scrollWidth, clientWidth, offenders }
}

/** Runs `scripts/seed_e2e.py` (P3.10 chunk a) and returns its parsed JSON
 * output contract — the one seeding path this script and the Playwright
 * suite share. Called with `supabaseEnv` already resolved so the script
 * never needs to shell out to `supabase status` itself. Progress goes to
 * the child's stderr (piped through when `AUDIT_VERBOSE` is set); stdout is
 * the JSON contract only, per the script's own docstring. */
function runSeedScript(supabaseEnv) {
  log("Seeding the multi-role fixture (scripts/seed_e2e.py)...")
  const result = spawnSync(
    path.join(repoRoot, ".venv/bin/python"),
    ["scripts/seed_e2e.py"],
    {
      cwd: repoRoot,
      env: { ...process.env, ...supabaseEnv },
      encoding: "utf-8",
      maxBuffer: 16 * 1024 * 1024,
    },
  )
  if (process.env.AUDIT_VERBOSE) process.stderr.write(result.stderr ?? "")
  if (result.status !== 0) {
    throw new Error(`scripts/seed_e2e.py failed (exit ${result.status}):\n${result.stderr}`)
  }
  const seed = JSON.parse(result.stdout)
  log(`Seed run ${seed.runTag} ready: class ${seed.class.classId}, ` +
    `parent linked to declining student ${seed.students.declining.userId}.`)
  return seed
}

/** Injects a real session (a genuine access token minted by `seed_e2e.py`
 * through the actual `AuthService`, not a fabricated one) into `localStorage`
 * before the page's own scripts run, so the app treats it exactly as it
 * would a session produced by its own login UI (see
 * `web/src/lib/auth/storage.ts`'s `Session` shape and
 * `web/src/lib/auth/RequireAuth.tsx`). Avoids re-driving each role's login
 * flow (already covered by G-04/G-05's own audited states, and by chunk d's
 * Playwright E2E) for every one of the 15 routes that just need to *be*
 * signed in as some role to render. `refreshToken: null` is fine — this
 * script never lives long enough to need a refresh, and `lib/api.ts` has no
 * refresh-on-401 path that would care. */
async function injectSession(page, { accessToken, userId, role }) {
  await page.evaluateOnNewDocument(
    (session) => {
      // `evaluateOnNewDocument` fires for EVERY document this page loads,
      // including the `about:blank` Lighthouse navigates to between its own
      // passes. That is an opaque origin with no accessible storage, so the
      // write throws `SecurityError` — which `watchConsole` then records as a
      // page error, one per authenticated route, failing the console-error
      // gate on an artifact of the harness rather than a defect in the app.
      // Skipping opaque origins explicitly (rather than swallowing the throw
      // in a bare try/catch) keeps a genuine storage failure on a real origin
      // loud.
      if (window.location.origin === "null") return
      window.localStorage.setItem("lemely.session", JSON.stringify(session))
    },
    { accessToken, refreshToken: null, userId, role },
  )
}

/** `goto` + the route's readiness wait, with one retry on a detached-frame
 * error. The very first navigation on a freshly-created page in an origin
 * that already has an active PWA service worker (every route after the
 * first) can race a `controllerchange`-driven reload, which detaches the
 * frame mid-`waitForFunction` — a real Puppeteer/vite-plugin-pwa
 * interaction, not a flaky test to paper over with a longer timeout. One
 * clean re-navigation resolves it; a second failure is a real bug and still
 * throws. */
async function gotoReady(page, url, ready, waitUntil = "networkidle0") {
  try {
    await page.goto(url, { waitUntil })
    if (ready) await ready(page)
  } catch (err) {
    if (!/detached/i.test(String(err?.message))) throw err
    await page.goto(url, { waitUntil })
    if (ready) await ready(page)
  }
}

/** Races `promise` against a plain timer — `page.evaluate()` has no timeout
 * of its own, so a promise that never resolves (e.g. a service worker that
 * never activates) would otherwise hang the whole run rather than surfacing
 * as the diagnostic route failure it actually is. */
function withTimeout(promise, ms, label) {
  let timer
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(`Timed out waiting for ${label}`)), ms)
  })
  return Promise.race([promise, timeout]).finally(() => clearTimeout(timer))
}

/** `setup`/`teardown` pair for a `loading` state: holds the route's own API
 * request open for `delayMs` before letting it through, so the screen's real
 * pending UI (its `isPending` render, not a stub) is what gets captured.
 * Exactly the mechanism `main()`'s G-04 loading-state capture already used
 * (request interception + a delayed `continue()`) — pulled out so registry
 * routes reuse it instead of reinventing it. Callers must navigate with
 * `waitUntil: "domcontentloaded"` (see the `waitUntil` state field): the
 * held request means the page is never actually network-idle, so
 * `networkidle0` would block until the delay elapses and defeat the capture
 * — the pending UI renders immediately from the query's initial state,
 * before the delayed response ever arrives, so `domcontentloaded` +
 * `ready`'s own explicit text wait is enough. */
function loadingStateHooks(urlSubstring, delayMs = 2_000) {
  let handler
  return {
    setup: async (page) => {
      await page.setRequestInterception(true)
      handler = (req) => {
        if (req.url().includes(urlSubstring)) {
          setTimeout(() => req.continue().catch(() => {}), delayMs)
        } else {
          req.continue().catch(() => {})
        }
      }
      page.on("request", handler)
    },
    teardown: async (page) => {
      page.off("request", handler)
      await page.setRequestInterception(false)
    },
  }
}

/** `setup`/`teardown` pair for an `error` state: fulfils the route's own API
 * request with a real 500 + FastAPI-shaped `{"detail": ...}` body (matching
 * what `lib/api.ts`'s `request()` actually parses), so the screen's real
 * `isError`/`ErrorState` branch renders — never a stubbed error payload
 * baked into the DOM by hand. Same interception mechanism as
 * `loadingStateHooks`, just an immediate `respond()` instead of a delayed
 * `continue()` — no `waitUntil` override needed, the response is never held
 * open. */
function errorStateHooks(urlSubstring) {
  let handler
  return {
    setup: async (page) => {
      await page.setRequestInterception(true)
      handler = (req) => {
        if (req.url().includes(urlSubstring)) {
          req
            .respond({
              status: 500,
              contentType: "application/json",
              body: JSON.stringify({ detail: "Simulated failure (web/scripts/audit.mjs)" }),
            })
            .catch(() => {})
        } else {
          req.continue().catch(() => {})
        }
      }
      page.on("request", handler)
    },
    teardown: async (page) => {
      page.off("request", handler)
      await page.setRequestInterception(false)
    },
  }
}

/** Drives ReviewItem.tsx's real "Adjust marks instead" -> "Save correction"
 * flow so T-08's `teacher-corrected` state (`isOverridden`) is reached
 * through the actual UI and `ReviewService.resolve`, never a stubbed
 * payload. Marks are always set to 0 — valid for any item regardless of its
 * real `maximumMarks` (0 is in `[0, max]` whenever `max >= 0`), so this needs
 * no knowledge of the specific seeded item's mark scheme. This mutates real
 * backend state and cannot be undone through this UI, which is why the
 * registry entry below orders `teacher-corrected` after `low-confidence`. */
async function resolveReviewItemViaAdjustForm(page, url) {
  await gotoReady(page, url, (p) => waitForText(p, "← Back to queue"))
  await clickButtonByText(page, "Adjust marks instead")
  const marksInput = await page.waitForSelector('input[type="number"]', { timeout: 15_000 })
  await marksInput.click({ clickCount: 3 })
  await marksInput.type("0")
  await clickButtonByText(page, "^save correction$")
  await waitForText(page, "Teacher correction on record")
}

/** Generic runner for one `ROUTE_REGISTRY` entry: for each of its `states`
 * (one implicit `"default"` state when the route carries no `states[]` — see
 * the file header), screenshots the route's current (real, not stubbed)
 * state at all 3 breakpoints, checks each for horizontal overflow, then runs
 * axe at the desktop viewport — the same shape `main()`'s G-04 section
 * already used, pulled out so registry routes are data, not copies of that
 * shape.
 *
 * **Decision (P3.10 chunk e2a): axe on every state, Lighthouse on the
 * canonical state only** (`state.lighthouse !== false`, defaulting `true`).
 * axe is ~1s and empty/error states are exactly where violations hide (chunk
 * b's `page-has-heading-one` finding was on an empty screen); Lighthouse is
 * ~30s per pass and its performance/best-practices/SEO scores are a property
 * of the route's shipped code, not of which fixture state happens to be on
 * screen this run. Concretely: this means a multi-state route's
 * `lighthouse/_summary.json` has ONE row (the canonical state), while its
 * `axe/_summary.json` has one row per state — do not read
 * `lighthouse/_summary.json`'s row count as "how many states were audited";
 * see `main()`'s end-of-run log for the honest per-kind counts. */
async function visitRoute(page, route, { axeSummary, lighthouseSummary, responsiveViolations }) {
  const url = `${PREVIEW_URL}${route.path}`
  const states = route.states ?? [
    { state: route.state ?? "default", slug: route.slug, ready: route.ready },
  ]

  for (const st of states) {
    const ready = st.ready ?? route.ready
    const waitUntil = st.waitUntil ?? "networkidle0"
    try {
      if (st.setup) {
        log(`${route.screenId} ${route.path} [${st.state}] — setup...`)
        await st.setup(page)
      }

      log(`${route.screenId} ${route.path} [${st.state}] — screenshots + responsive check (3 breakpoints)...`)
      for (const bp of BREAKPOINTS) {
        await page.setViewport(bp)
        await gotoReady(page, url, ready, waitUntil)
        const violation = await checkNoHorizontalScroll(page, st.slug, bp.width)
        if (violation) responsiveViolations.push(violation)
        await shoot(page, route.screenId, st.state, bp.width)
      }

      log(`${route.screenId} ${route.path} [${st.state}] — axe...`)
      await page.setViewport(AUDIT_VIEWPORT)
      await gotoReady(page, url, ready, waitUntil)
      axeSummary.push(await runAxe(page, st.slug))

      if (st.lighthouse !== false) {
        log(`${route.screenId} ${route.path} [${st.state}] — Lighthouse...`)
        lighthouseSummary.push(
          await runLighthouseAudit(url, page, st.slug, { authed: route.authed }),
        )
      }
    } finally {
      if (st.teardown) {
        log(`${route.screenId} ${route.path} [${st.state}] — teardown...`)
        await st.teardown(page)
      }
    }
  }
}

/**
 * The routes reached via `visitRoute()` (session injection + plain
 * navigation) — see the file header for why the other 4 (G-04 + the student
 * main journey) are not in this table. `session` is a function of the seed
 * payload so the registry can be defined once, before the seed has run, and
 * evaluated after; `null` means unauthenticated (G-05).
 *
 * Screen ids are `docs/LEMELY_UI_SPEC.md`'s (S-xx/T-xx/P-xx/G-xx), except
 * `/student/parents`: P3.9 chunk d built it ahead of a spec update and it has
 * no assigned id yet, so it is labelled `S-32-provisional` here — the next
 * free slot after S-31, flagged as provisional rather than silently reusing
 * or inventing a spec-sanctioned one.
 *
 * `emptyTeacherSession`/`emptyParentSession` (P3.10 chunk e1's
 * `emptyTeacher`/`emptyParent`) back the `empty` captures — real accounts
 * with genuinely no data, never a stubbed empty payload. They get their own
 * registry entries below (same `screenId` as the populated route, distinct
 * slug, `state: "empty"`), not a `states[]` entry on the populated one,
 * because the session-context driver in `main()` keys its incognito
 * contexts by `role:userId` — a different account needs a different entry
 * to land in a different context in the first place.
 */
function buildRouteRegistry(seed) {
  const teacherSession = {
    accessToken: seed.teacher.accessToken,
    userId: seed.teacher.userId,
    role: "teacher",
  }
  const parentSession = {
    accessToken: seed.parent.accessToken,
    userId: seed.parent.userId,
    role: "parent",
  }
  const decliningStudentSession = {
    accessToken: seed.students.declining.accessToken,
    userId: seed.students.declining.userId,
    role: "student",
  }
  const emptyTeacherSession = {
    accessToken: seed.emptyTeacher.accessToken,
    userId: seed.emptyTeacher.userId,
    role: "teacher",
  }
  const emptyParentSession = {
    accessToken: seed.emptyParent.accessToken,
    userId: seed.emptyParent.userId,
    role: "parent",
  }
  const classId = seed.class.classId
  // The parent's one linked child (D3.11) is the "declining" student — same
  // account for both sessions above, just wearing a different role's token.
  const childId = seed.students.declining.userId
  const subjectCode = "0625" // scripts/seed_e2e.py's SUBJECT_CODE — every declining-student attempt is this subject.
  const reviewItemUrl = `/teacher/review/${seed.reviewItem.itemId}`
  const reviewItemReady = (page) => waitForText(page, "← Back to queue")
  const quizDetailUrl = `/teacher/quizzes/${seed.quiz.quizId}`
  const quizResultsUrl = `/teacher/quizzes/${seed.quiz.quizId}/assignments/${seed.quiz.assignmentId}/results`

  return [
    // ── G-05 · Parent log in (phone + OTP) — unauthenticated ──────────────
    {
      screenId: "G-05",
      slug: "parent-login",
      path: "/login/parent",
      session: null,
      ready: (page) => waitForText(page, "Check on your child"),
      authed: false,
    },
    // ── Teacher (15 entries — several carry more than one `states[]`) ──────
    {
      screenId: "T-01",
      path: "/teacher",
      session: teacherSession,
      authed: true,
      states: [
        {
          state: "default",
          slug: "teacher-overview",
          ready: (page) => waitForText(page, "Good morning"),
        },
        // Honest CDP `offline` capture. `web/src/components/ui/state-views.tsx`
        // defines an `OfflineState` primitive but nothing under `portals/`
        // ever imports it (verified — no importer anywhere but the file
        // itself), so going offline today just falls into this route's
        // ordinary `overviewQuery.isError` branch via a failed `fetch()` — a
        // real product gap, not something this harness should paper over
        // with a bespoke "offline" screenshot. `lighthouse: false`: this is
        // a state of T-01, not a second route — T-01's Lighthouse score
        // already ran against the `default` state above.
        {
          state: "offline",
          slug: "teacher-overview-offline",
          lighthouse: false,
          ready: (page) => waitForText(page, "Couldn't load the overview"),
          setup: async (page) => {
            // Wait for the service worker to be active before flipping
            // offline — `vite.config.ts`'s `navigateFallback` only serves
            // the app shell offline once a worker controls navigations for
            // this origin, and this session's page has already navigated
            // here once (the `default` state above), giving it time to
            // install.
            await withTimeout(
              page.evaluate(() => navigator.serviceWorker.ready),
              15_000,
              "service worker ready (T-01 offline capture)",
            )
            await page.setOfflineMode(true)
          },
          teardown: (page) => page.setOfflineMode(false),
        },
      ],
    },
    {
      screenId: "T-02",
      slug: "teacher-classes",
      path: "/teacher/classes",
      session: teacherSession,
      // "Classes" is also the sr-only h1 shown while the list is still
      // pending, so waiting on it alone can resolve before real data has
      // rendered — the "New class" toggle only exists once the loaded view
      // mounts. (Not "Create class": that is the *submit* button inside the
      // create form, which only renders after the toggle is clicked.)
      ready: (page) => waitForText(page, "New class"),
      authed: true,
    },
    {
      screenId: "T-03",
      slug: "teacher-class-roster",
      path: `/teacher/classes/${classId}`,
      session: teacherSession,
      ready: (page) => waitForText(page, "All classes"),
      authed: true,
    },
    {
      screenId: "T-04",
      slug: "teacher-class-analytics",
      path: `/teacher/classes/${classId}/analytics`,
      session: teacherSession,
      ready: (page) => waitForText(page, "Topic weakness heatmap"),
      authed: true,
    },
    {
      screenId: "T-05",
      slug: "teacher-student-detail",
      path: `/teacher/students/${seed.students.declining.userId}`,
      session: teacherSession,
      // The student's display name is the visible h1, but it's a seeded,
      // per-run-unique value — "At-risk flags" is the stable panel heading
      // below it (declining fires D3.3 rule 1, so this panel is populated).
      ready: (page) => waitForText(page, "At-risk flags"),
      authed: true,
    },
    {
      screenId: "T-06",
      slug: "teacher-at-risk",
      path: "/teacher/at-risk",
      session: teacherSession,
      // "At-risk students" is also the pending/error sr-only h1 — the eyebrow
      // line above the real h1 only renders once the list has loaded.
      ready: (page) => waitForText(page, "Flagged by trajectory"),
      authed: true,
    },
    {
      screenId: "T-07",
      slug: "teacher-review",
      path: "/teacher/review",
      session: teacherSession,
      // Same shape as T-06: "Review queue" duplicates into the pending
      // sr-only h1, so wait on the loaded-only eyebrow line instead. Not
      // empty since P3.10 chunk e1: the seed now deliberately persists one
      // LOW-confidence attempt (`seed.reviewItem`, D3.9's queueing path) so
      // T-08 below has a real item to drill into — this list shows exactly
      // that one row.
      ready: (page) => waitForText(page, "core recurring task"),
      authed: true,
    },
    // ── T-08 · Review item detail — zero coverage before e1 seeded a real
    // LOW-confidence item (scripts/seed_e2e.py's `reviewItem`, linked to
    // `AttemptRepository`'s real fan-out, never a hand-inserted
    // `review_queue` row). Two states from that ONE real item:
    // `low-confidence` is how it renders untouched (its actual queued
    // reason); `teacher-corrected` is reached by really driving
    // ReviewItem.tsx's "Adjust marks instead" -> "Save correction" flow
    // (`resolveReviewItemViaAdjustForm`), never a stubbed `isOverridden`
    // payload. That mutation is real and irreversible through this UI, so
    // `teacher-corrected` MUST stay ordered after `low-confidence` here.
    {
      screenId: "T-08",
      path: reviewItemUrl,
      session: teacherSession,
      authed: true,
      states: [
        {
          state: "low-confidence",
          slug: "teacher-review-detail",
          ready: reviewItemReady,
        },
        {
          state: "teacher-corrected",
          slug: "teacher-review-detail-corrected",
          lighthouse: false,
          ready: reviewItemReady,
          setup: (page) => resolveReviewItemViaAdjustForm(page, `${PREVIEW_URL}${reviewItemUrl}`),
        },
        {
          state: "loading",
          slug: "teacher-review-detail-loading",
          lighthouse: false,
          waitUntil: "domcontentloaded",
          ready: (page) => waitForText(page, "Loading review item"),
          ...loadingStateHooks(`/api${reviewItemUrl}`),
        },
        {
          state: "error",
          slug: "teacher-review-detail-error",
          lighthouse: false,
          // Distinguish from the *loaded* state's own "← Back to queue" —
          // the error state's secondary action reads "Back to queue", no
          // arrow (see ReviewItem.tsx).
          ready: (page) => waitForText(page, "Couldn't load this review item"),
          ...errorStateHooks(`/api${reviewItemUrl}`),
        },
      ],
    },
    {
      // Screen table has no separate id for the quiz *list* — STATE.md's own
      // P3.8c commit treats Quizzes.tsx as part of T-09 ("quiz builder")'s
      // umbrella, so this reuses that id rather than inventing a new one.
      screenId: "T-09",
      slug: "teacher-quizzes",
      path: "/teacher/quizzes",
      session: teacherSession,
      ready: (page) => waitForText(page, "New quiz"),
      authed: true,
    },
    // ── T-09-detail · Quiz builder detail — zero coverage before e1 seeded a
    // real quiz (scripts/seed_e2e.py's `quiz`). The seeded quiz is
    // `status: "marked"` (submitted + marked, not draft), so this exercises
    // QuizBuilder.tsx's real read-only path, genuinely — not staged.
    {
      screenId: "T-09-detail",
      path: quizDetailUrl,
      session: teacherSession,
      authed: true,
      states: [
        {
          state: "default",
          slug: "teacher-quiz-detail",
          ready: (page) => waitForText(page, "← All quizzes"),
        },
        {
          state: "loading",
          slug: "teacher-quiz-detail-loading",
          lighthouse: false,
          waitUntil: "domcontentloaded",
          ready: (page) => waitForText(page, "Loading quiz"),
          ...loadingStateHooks(`/api${quizDetailUrl}`),
        },
        {
          state: "error",
          slug: "teacher-quiz-detail-error",
          lighthouse: false,
          // Error state's secondary action reads "Back to quizzes" (no
          // arrow, no "All") — distinct from the loaded state's own text.
          ready: (page) => waitForText(page, "Couldn't load this quiz"),
          ...errorStateHooks(`/api${quizDetailUrl}`),
        },
      ],
    },
    // ── T-10 · Quiz results (per assignment) — zero coverage before e1
    // seeded a real quiz assignment + submission (scripts/seed_e2e.py's
    // `quiz`, marked through `QuizMarkingService`'s real path). Ready
    // predicate is the completion line, never "Back to quizzes": that text
    // is the *error* state's secondary-action label
    // (`QuizResults.tsx`), and the loaded header instead reads "Back to the
    // quiz" (no "quizzes") — waiting on the wrong one would silently resolve
    // on either state.
    {
      screenId: "T-10",
      path: quizResultsUrl,
      session: teacherSession,
      authed: true,
      states: [
        {
          state: "default",
          slug: "teacher-quiz-results",
          ready: (page) =>
            waitForText(page, "on the current roster|No students on the roster yet"),
        },
        {
          state: "loading",
          slug: "teacher-quiz-results-loading",
          lighthouse: false,
          waitUntil: "domcontentloaded",
          ready: (page) => waitForText(page, "Loading results"),
          ...loadingStateHooks(`/api${quizResultsUrl}`),
        },
        {
          state: "error",
          slug: "teacher-quiz-results-error",
          lighthouse: false,
          ready: (page) => waitForText(page, "Couldn't load these results"),
          ...errorStateHooks(`/api${quizResultsUrl}`),
        },
      ],
    },
    {
      screenId: "T-12",
      slug: "teacher-announcements",
      path: "/teacher/announcements",
      session: teacherSession,
      ready: (page) => waitForText(page, "Announcements"),
      authed: true,
    },
    // The two Phase-2 grading-console screens. Neither has a spec id:
    // `docs/LEMELY_UI_SPEC.md`'s teacher table runs T-01..T-12 and enumerates
    // neither — the grading console predates it, and the mark-scheme library
    // is NOT T-11 (which mandates a parsing preview and an editable
    // question/mark mapping this screen has none of). Labelled provisional
    // rather than annexed to T-11, following the `S-32-provisional`
    // precedent. They are audited in their real, genuinely-empty state: the
    // seed uploads no scheme and corrects no paper through this console, and
    // an empty state is exactly where an axe violation hides (the known
    // `EmptyState`-heading gap is one). Auditing an empty state is honest;
    // leaving a live route out of the registry is what made this gate
    // vacuous in the first place.
    {
      screenId: "T-13-provisional",
      slug: "teacher-grading",
      path: "/teacher/grading",
      // "Grading" alone matches the always-rendered sidebar nav item, so it
      // resolves during the pending state; the "Grading console" eyebrow
      // only exists once the loaded view mounts.
      ready: (page) => waitForText(page, "Grading console"),
      session: teacherSession,
      authed: true,
    },
    {
      screenId: "T-14-provisional",
      slug: "teacher-schemes",
      path: "/teacher/schemes",
      // Same shape: "Mark schemes" is the sidebar nav label too. "Library"
      // is the loaded-only eyebrow.
      ready: (page) => waitForText(page, "Library"),
      session: teacherSession,
      authed: true,
    },
    // Honest `empty` capture (P3.10 chunk e2a): `seed.emptyTeacher` is a real
    // second teacher account with zero classes, ever — not a states[] entry
    // on T-01 above, because `empty` needs its OWN session/incognito context
    // (see this file's `buildRouteRegistry` doc comment). `lighthouse:
    // false` — this is a state of the T-01 *screen*, not a second route to
    // score.
    {
      screenId: "T-01",
      path: "/teacher",
      session: emptyTeacherSession,
      authed: true,
      states: [
        {
          state: "empty",
          slug: "teacher-overview-empty",
          lighthouse: false,
          ready: (page) => waitForText(page, "Good morning"),
        },
      ],
    },
    // ── Parent (5 entries — P-01 twice: populated + `emptyParent`) ───────
    {
      // With exactly one linked child (D3.11's spec-mandated behaviour —
      // Children.tsx `<Navigate replace>`s straight to P-02), /parent never
      // actually renders P-01's list UI for this seed; it renders P-02. That
      // is the real, spec-correct behaviour for a one-child parent, not a
      // gap in this registry — genuinely visiting /parent, not faking it.
      // (The `empty` entry right below IS how P-01's real list UI — its
      // `NoChildrenLinked` branch — actually gets audited: `seed.emptyParent`
      // has zero linked children, so Children.tsx's one-child `<Navigate>`
      // never fires for it.)
      screenId: "P-01",
      slug: "parent-children",
      path: "/parent",
      session: parentSession,
      ready: (page) => waitForText(page, "Subjects"),
      authed: true,
    },
    {
      screenId: "P-01",
      path: "/parent",
      session: emptyParentSession,
      authed: true,
      states: [
        {
          state: "empty",
          slug: "parent-children-empty",
          lighthouse: false,
          ready: (page) => waitForText(page, "one step to go"),
        },
      ],
    },
    {
      screenId: "P-02",
      slug: "parent-child-overview",
      path: `/parent/children/${childId}`,
      session: parentSession,
      ready: (page) => waitForText(page, "Subjects"),
      authed: true,
    },
    {
      screenId: "P-03",
      slug: "parent-subject-detail",
      path: `/parent/children/${childId}/subjects/${subjectCode}`,
      session: parentSession,
      ready: (page) => waitForText(page, "Papers they've done"),
      authed: true,
    },
    {
      screenId: "P-04",
      slug: "parent-weaknesses",
      path: `/parent/children/${childId}/weaknesses`,
      session: parentSession,
      ready: (page) => waitForText(page, "What to work on next"),
      authed: true,
    },
    // ── Student — parent-link management (P3.9 chunk d, no spec id yet) ───
    {
      screenId: "S-32-provisional",
      slug: "student-parents",
      path: "/student/parents",
      session: decliningStudentSession,
      ready: (page) => waitForText(page, "Your parents"),
      authed: true,
    },
  ]
}

// ── Chromium lifecycle ────────────────────────────────────────────────────
//
// Chromium dying mid-run is NOT a route failure, and must never be reported
// as one. When the browser process goes away, every remaining route throws a
// CDP protocol error ("Session closed", "detached Frame", "Target closed")
// and the run's output reads as a dozen simultaneous product defects — which
// is exactly how two P3.10 e2a verification runs were first misread. Capture
// the real exit code/signal here (a SIGKILL means the OS killed it, i.e.
// memory; a SIGSEGV/SIGABRT means Chromium crashed) so the run diagnoses
// itself, and abort the walk at the first sign rather than accumulating
// phantom failures. Same class of finding as the `reuseExistingServer` one
// recorded in BUILD/STATE.md: a gate whose failure mode is undiagnostic is
// barely better than no gate.
//
// These live at module scope rather than inside `main` because the registry
// walk *recycles* the browser (see `RECYCLE_EVERY`), so the death watch has
// to be re-armable against a new process.
let browserExit = null

function watchBrowserExit(browser) {
  browserExit = null
  browser.process()?.once("exit", (code, signal) => {
    browserExit = { code, signal }
  })
}

function browserDeath(context) {
  return new Error(
    `Chromium died mid-run (${browserExit ? `exit code ${browserExit.code}, signal ${browserExit.signal}` : "still connected per the process handle — see the underlying error"}) ${context}. ` +
      "This is a harness/environment failure, not a route defect: every route after this " +
      "point would report a spurious CDP protocol error. Re-run; if it recurs, check " +
      "memory pressure (free -m) while the audit runs.",
  )
}

/** Recycle the browser process every N registry routes.
 *
 * Closing each session's context after its last route (below) bounds how many
 * contexts are open at once, but it does NOT bound the lifetime of the busiest
 * one: the teacher session owns ~14 of the ~21 registry routes, so a single
 * renderer accumulates every screenshot, axe injection and Lighthouse trace
 * across that whole span. On this host (7.8 GB RAM, ~3.4 GB swap already in
 * use before the run) that is what kills the process — the first three
 * verification runs died progressively later as the per-context hygiene
 * improved, which is the signature of a ceiling being approached, not of a
 * route defect. Recycling puts a hard bound on peak RSS regardless of how the
 * registry is ordered.
 *
 * This is safe precisely because sessions are *injected*, never logged into:
 * a recycled browser re-creates the context on the next route and calls
 * `injectSession` again, so nothing is lost but the memory. Override with
 * LEMELY_AUDIT_RECYCLE_EVERY=0 to disable (useful when bisecting whether a
 * failure is memory-related at all).
 */
const RECYCLE_EVERY = Number(process.env.LEMELY_AUDIT_RECYCLE_EVERY ?? 4)

/** MemAvailable in MB, or null where /proc is not readable. Logged per route
 * so a death leaves behind the evidence for its own diagnosis instead of
 * needing a second instrumented run. */
function memAvailableMb() {
  try {
    const meminfo = fs.readFileSync("/proc/meminfo", "utf8")
    const match = /^MemAvailable:\s+(\d+) kB$/m.exec(meminfo)
    return match ? Math.round(Number(match[1]) / 1024) : null
  } catch {
    return null
  }
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

  // scripts/seed_e2e.py talks straight to Supabase Auth/Postgres through
  // lemely.web.deps' singletons — it doesn't need the backend HTTP server up,
  // but doing it here (once the stack is confirmed reachable) keeps the log
  // in a sensible order: data exists before anything tries to read it.
  const seed = runSeedScript(supabaseEnv)

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
  const responsiveViolations = []
  const routeFailures = []

  let browser
  let routes = []
  try {
    browser = await puppeteer.launch({ headless: true })
    watchBrowserExit(browser)

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
      const violation = await checkNoHorizontalScroll(page, "login", bp.width)
      if (violation) responsiveViolations.push(violation)
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
      const violation = await checkNoHorizontalScroll(page, "login-error", bp.width)
      if (violation) responsiveViolations.push(violation)
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
      const violation = await checkNoHorizontalScroll(page, "login-loading", bp.width)
      if (violation) responsiveViolations.push(violation)
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
    log("S-10 /student/correct — responsive check (380px) + axe + Lighthouse (entry state)...")
    await page.setViewport({ width: 380, height: 844 })
    await page.goto(`${PREVIEW_URL}/student/correct`, { waitUntil: "networkidle0" })
    await waitForText(page, "Correct a paper")
    const correctViolation = await checkNoHorizontalScroll(page, "student-correct", 380)
    if (correctViolation) responsiveViolations.push(correctViolation)

    await page.setViewport(AUDIT_VIEWPORT)
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
    await page.setViewport({ width: 380, height: 844 })
    await page.goto(resultUrl, { waitUntil: "networkidle0" })
    await page.waitForSelector('[aria-label*="out of"]', { timeout: 15_000 })
    const resultViolation = await checkNoHorizontalScroll(page, "student-result", 380)
    if (resultViolation) responsiveViolations.push(resultViolation)

    await page.setViewport(AUDIT_VIEWPORT)
    await page.goto(resultUrl, { waitUntil: "networkidle0" })
    await page.waitForSelector('[aria-label*="out of"]', { timeout: 15_000 })
    axeSummary.push(await runAxe(page, "student-result"))
    lighthouseSummary.push(
      await runLighthouseAudit(resultUrl, page, "student-result", { authed: true }),
    )

    // ── S-06 · Student overview — now non-empty (one corrected paper) ──────
    log("S-06 /student — responsive check (380px) + axe + Lighthouse (non-empty, after correction)...")
    await page.setViewport({ width: 380, height: 844 })
    await page.goto(`${PREVIEW_URL}/student`, { waitUntil: "networkidle0" })
    await waitForText(page, "Subjects this session")
    const overviewViolation = await checkNoHorizontalScroll(page, "student-overview", 380)
    if (overviewViolation) responsiveViolations.push(overviewViolation)

    await page.setViewport(AUDIT_VIEWPORT)
    await page.goto(`${PREVIEW_URL}/student`, { waitUntil: "networkidle0" })
    await waitForText(page, "Subjects this session")
    axeSummary.push(await runAxe(page, "student-overview"))
    lighthouseSummary.push(
      await runLighthouseAudit(`${PREVIEW_URL}/student`, page, "student-overview", {
        authed: true,
      }),
    )
    // ── The 15 declaratively-registered routes (teacher/parent/G-05/
    // student-parents) — each role gets its own fresh page with a real
    // session injected (see `injectSession`), rather than re-driving 4
    // different login flows for every route. ──────────────────────────────
    //
    // Each session key gets its own **incognito browser context**, not just
    // its own page: `localStorage` is per-origin, so pages in the default
    // context all share one `lemely.session`. That is not a hypothetical —
    // G-05 (`/login/parent`, deliberately unauthenticated) failed on the
    // first run of this registry because the student main journey above had
    // left a real student session behind, and `App.tsx`'s `LoginRoute`
    // correctly `<Navigate>`s an already-authenticated visitor away from
    // every login route. An isolated context is what makes "unauthenticated"
    // actually unauthenticated, and it also removes the registry's implicit
    // dependency on route ordering for the authenticated roles.
    routes = buildRouteRegistry(seed)
    // The student journey above is finished with this page, and it is the
    // heaviest one in the run (a real upload + a full marking pass). Closing
    // it frees its renderer before the registry walk opens five more
    // contexts, rather than holding ~22 routes' worth of extra memory for
    // nothing.
    await page.close()

    const sessionsSeen = new Map()
    // Each session's context is closed after the LAST route that uses it,
    // for the same reason: peak memory is what kills a long run, and a
    // context whose routes are all done is pure overhead.
    const lastRouteIndexBySession = new Map()
    const sessionKeyOf = (route) =>
      route.session ? `${route.session.role}:${route.session.userId}` : "unauth"
    routes.forEach((route, i) => lastRouteIndexBySession.set(sessionKeyOf(route), i))

    for (const [routeIndex, route] of routes.entries()) {
      if (!browser.connected) throw browserDeath(`before ${route.screenId} ${route.path}`)

      if (RECYCLE_EVERY > 0 && routeIndex > 0 && routeIndex % RECYCLE_EVERY === 0) {
        for (const openPage of sessionsSeen.values()) {
          await openPage.browserContext().close().catch(() => {})
        }
        sessionsSeen.clear()
        await browser.close().catch(() => {})
        browser = await puppeteer.launch({ headless: true })
        watchBrowserExit(browser)
        log(
          `recycled Chromium before route ${routeIndex} (every ${RECYCLE_EVERY}) — ` +
            `MemAvailable ${memAvailableMb() ?? "?"} MB`,
        )
      }

      const sessionKey = sessionKeyOf(route)
      let routePage = sessionsSeen.get(sessionKey)
      if (!routePage) {
        const context = await browser.createBrowserContext()
        routePage = await context.newPage()
        if (route.session) await injectSession(routePage, route.session)
        watchConsole(routePage, consoleErrors)
        sessionsSeen.set(sessionKey, routePage)
      }
      // One unreachable route must not hide the other fourteen. A registry
      // entry that throws (a `ready` predicate that never matches, a route
      // that redirects, a screen that crashes) is recorded and the walk
      // continues; `routeFailures` is non-empty at the end, which is a hard
      // non-zero exit below — scripts/check.sh's `puppeteer-audit` gate fails
      // on it. This makes the run diagnostic, never more permissive: a route
      // that fails here also contributes no axe/Lighthouse summary row, and
      // check_ui_gates.py can only check rows that exist.
      try {
        log(
          `[mem] before ${route.screenId} (${route.states?.length ?? 1} state(s)): ` +
            `MemAvailable ${memAvailableMb() ?? "?"} MB`,
        )
        await visitRoute(routePage, route, {
          axeSummary,
          lighthouseSummary,
          responsiveViolations,
        })
      } catch (err) {
        if (!browser.connected) throw browserDeath(`during ${route.screenId} ${route.path}`)
        log(`!! ${route.screenId} ${route.path} FAILED: ${err?.message ?? err}`)
        routeFailures.push({ screenId: route.screenId, path: route.path, error: String(err?.message ?? err) })
      }

      if (lastRouteIndexBySession.get(sessionKey) === routeIndex && browser.connected) {
        await routePage.browserContext().close().catch(() => {})
        sessionsSeen.delete(sessionKey)
      }
    }
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
  fs.writeFileSync(RESPONSIVE_SUMMARY_PATH, JSON.stringify(responsiveViolations, null, 2))

  generateContactSheet()

  log("─────────────────────────────────────────────")
  log(
    `Registry routes: ${routes.length} declarative + 4 D2.10-era inline. ` +
      `axe passes: ${axeSummary.length} (one per audited STATE — a multi-state route ` +
      `contributes more than one row). Lighthouse passes: ${lighthouseSummary.length} ` +
      "(one per route's canonical state only — P3.10 chunk e2a's decision: Lighthouse " +
      "scores a route's shipped code, not which fixture state is on screen; axe runs on " +
      "every state because that's exactly where violations like an empty-screen missing " +
      "h1 hide). Do not read this run as \"every state got a full Lighthouse pass\" — it " +
      "didn't, deliberately.",
  )
  log("axe violation counts by severity (critical/serious/moderate/minor):")
  for (const r of axeSummary) {
    log(
      `  ${r.slug.padEnd(24)} ${r.counts.critical}/${r.counts.serious}/${r.counts.moderate}/${r.counts.minor}  (total ${r.violationCount})`,
    )
  }
  log("Lighthouse scores (performance/accessibility/best-practices/seo):")
  for (const r of lighthouseSummary) {
    log(
      `  ${r.slug.padEnd(24)} ${r.scores.performance}/${r.scores.accessibility}/${r.scores["best-practices"]}/${r.scores.seo}`,
    )
  }
  log(`Console errors collected: ${consoleErrors.length}`)
  log(`Horizontal-scroll violations: ${responsiveViolations.length}`)
  for (const v of responsiveViolations) {
    log(`  ${v.slug} @ ${v.bpWidth}px — scrollWidth ${v.scrollWidth} > clientWidth ${v.clientWidth}`)
    for (const o of v.offenders ?? []) {
      log(
        `      +${o.overhang}px  <${o.tag}${o.id ? `#${o.id}` : ""} class="${o.className ?? ""}">` +
          ` w=${o.width} left=${o.left}${o.text ? `  “${o.text}”` : ""}`,
      )
    }
  }
  log(
    "Not covered by this registry (P4/P5 screens still on mock data): " +
      "/student/subject/:code, /student/plan, /student/board, /student/onboard, " +
      "/student/landing, /student/directions.",
  )
  log(`Contact sheet: ${CONTACT_SHEET_PATH}`)

  if (routeFailures.length) {
    log(`${routeFailures.length} registry route(s) could not be audited at all:`)
    for (const f of routeFailures) {
      log(`  ${f.screenId} ${f.path} — ${f.error}`)
    }
    throw new Error(
      `${routeFailures.length} route(s) in ROUTE_REGISTRY were unreachable — ` +
        "the gate cannot pass on routes it never managed to look at",
    )
  }
}

/** Regenerates `$LEMELY_REPORT_DIR/contact-sheet.html` from whatever is
 * actually under `$LEMELY_REPORT_DIR/screens/` at generation time (both this
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
<title>Lemely — visual QA contact sheet</title>
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
  <h1>Lemely — visual QA contact sheet</h1>
  <p class="meta">Generated ${new Date().toISOString()} from ${path.relative(repoRoot, SCREENS_DIR)}/. ${screenIds.length} screen(s), ${screenIds.reduce((n, id) => n + fs.readdirSync(path.join(SCREENS_DIR, id)).filter((f) => f.endsWith(".png")).length, 0)} screenshot(s).</p>
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
