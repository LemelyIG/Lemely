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
 *   - 6 entries / 7 captured states added by P4.8 chunk C for the Phase-4
 *     onboarding/placement screens, on four distinct seeded student accounts:
 *     S-01, S-02 (twice — the questionnaire, AND a *skipped* question, which
 *     is where D4.5's "a skipped answer is NULL and must not render as an
 *     answer the student gave" is actually visible), S-03 twice (available
 *     AND the honest `no_questions` refusal), S-04, S-05. These shipped in
 *     P4.8 chunks A/B with no registry entry at all, so `ui-thresholds`
 *     passed over them without ever loading one.
 *     Entry order matters for the two that share the `unonboarded` account:
 *     S-01 claims a genuinely first-run state (no profile, no enrolment) and
 *     S-02's drive really persists an enrolment, so S-01 must stay ahead of
 *     it in this array.
 *   - 13 entries / 14 captured states added by P4.9 chunk C for the practice
 *     and flashcard screens (S-20..S-23), on three distinct seeded student
 *     accounts (`seed.practice.*` — `active`/`settled`/`bare`, none wearing
 *     two hats: a student with recorded weaknesses cannot also demonstrate
 *     the honest `no_weaknesses` refusal, and a student with cards due today
 *     cannot also demonstrate "nothing due today"): S-20 three times (the
 *     default `insufficient_pool` shortfall — the normal state given this
 *     seed's small bank, not a corner case — the honest `no_questions`
 *     refusal on 0580, and `no_weaknesses` driven live through the "Weak
 *     topics only" checkbox), S-21 five times (working view, `not_submitted`,
 *     `marking`, `marked`, and print/export — three distinct practice sets
 *     on the `active` account, per `scripts/seed_e2e.py`'s `practice` block),
 *     S-22 four times (cards due today, `settled`'s "nothing due", `bare`'s
 *     genuinely empty deck list, and `bare`'s free `no_weaknesses` 409 driven
 *     live through the "Generate from a weakness" mode), S-23 twice (a card
 *     front with the reveal + four grade buttons — never graded, since
 *     grading is irreversible and would destroy this capture's own
 *     repeatability — and `settled`'s "nothing due"). These shipped in P4.9
 *     chunks A/B with no registry entry at all, the same vacuous-pass shape
 *     P4.8 chunk C's own header note warns about.
 *   - 6 entries / 6 captured states added by P4.10 chunk C for the study-plan
 *     screens (S-24/S-25), composing accounts that already exist rather than
 *     seeding new ones: S-24 four times (the populated week on `active`, the
 *     persisted `no_signal` refusal on `settled`, the ungenerated week on
 *     `bare`, and the fully-completed week on
 *     `placement.students.completed`) and S-25 twice (the session detail on
 *     its *provable* recorded-weakness rationale, and a session id that is
 *     not in the current week). The first three S-24 states are mutually
 *     exclusive per account per week by construction — see the session block
 *     below — which is why they cannot be collapsed onto one account, and the
 *     fourth is on a different account again because completing `active`'s
 *     sessions would destroy the populated-week capture.
 * Deliberately still NOT in this registry (P5 screens still on mock data):
 *   /student/subject/:code, /student/board, /student/landing,
 *   /student/directions.
 *   (`/student/onboard` was on this list until P4.8 chunk C — chunk A made it
 *   real, and the list had gone stale, which is precisely how a route stays
 *   unaudited: the exclusion note outlives the exclusion.
 *   It happened a second time: `/student/plan` sat on this list through
 *   P4.10 chunks A and B, which rewrote it onto the real
 *   `/api/student/study-plan` backend and moved it to `/student/plan/:code`.
 *   Removed in chunk C, along with the same claim in the run's own closing
 *   `log()` — fixing only the comment would have left the false statement in
 *   the operator-facing output, where it is actually read.)
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

// ── Keep Chromium's scratch off tmpfs ────────────────────────────────────────
// This host mounts /tmp as a 3.9 GB **tmpfs**, i.e. RAM, and unrelated stale
// build junk keeps it ~70% full (≈1.2 GB free). Puppeteer puts each browser's
// user-data-dir under os.tmpdir(), and Lighthouse spills traces there too, so a
// long run can hit ENOSPC on the profile dir. Chromium dies *instantly and
// silently* when that happens — no kernel OOM entry, nothing in dmesg, and
// /dev/shm untouched — which is exactly the signature sessions 2–4 chased as
// generic "memory pressure". It also explains why each successive run died
// earlier than the last: every crashed run leaked another profile into the
// tmpfs, shrinking the headroom for the next one.
//
// Fixed to a path independent of LEMELY_REPORT_DIR: the re-baseline run points
// that at the committed `reports/phase-3/`, and browser scratch must never land
// in a committed directory. `reports/.scratch/` is gitignored.
const AUDIT_TMP_DIR = path.resolve(repoRoot, "reports/.scratch/audit-tmp")
fs.rmSync(AUDIT_TMP_DIR, { recursive: true, force: true })
fs.mkdirSync(AUDIT_TMP_DIR, { recursive: true })
process.env.TMPDIR = AUDIT_TMP_DIR

/** The main audit browser: screenshots, axe, responsive checks.
 *
 * Frugal flags are applied **here only, never to Lighthouse's browser.**
 * Capping renderer processes or the JS heap would change the very numbers
 * Lighthouse reports, and the run gates on performance ≥ 80 — a cheaper score
 * bought by throttling the browser we measure in would be a dishonest gate.
 * Nothing on this page's critical path is timed, so constraining it is free.
 *
 * `--disable-dev-shm-usage` is deliberately NOT set: it would redirect shared
 * memory back onto TMPDIR. /dev/shm here is 3.9 GB and empty, which is the
 * better home for it.
 */
function launchAuditBrowser() {
  return puppeteer.launch({
    headless: true,
    args: [
      "--disable-gpu",
      "--disable-extensions",
      "--disable-background-networking",
      "--renderer-process-limit=2",
      "--js-flags=--max-old-space-size=512",
    ],
  })
}

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

/**
 * Click an `aria-pressed` toggle button ONLY if it is not already pressed.
 *
 * This exists because `visitRoute` drives a state once but navigates to it
 * four times (three breakpoints + axe), so any drive written into `ready`
 * runs repeatedly against an account whose server-side state the previous
 * run already changed. S-01's "Continue" really does `PUT /api/me/
 * student-profile/enrolments`, and Onboarding.tsx's seeding effect restores
 * that enrolment on the next load — so an unconditional click would
 * *deselect* Physics on pass two, leaving `Continue` disabled
 * (`SubjectsStep.tsx`: `disabled={selectedCount === 0}`) and hanging the run
 * on a timeout that reads as a product defect rather than a harness one.
 *
 * `aria-pressed` is what distinguishes the two cases, and it is on the real
 * button already (`SubjectsStep.tsx:92`) for accessibility reasons — this
 * reads the product's own state, it does not add a test-only hook.
 */
async function pressToggleOnce(page, pattern, timeout = 15_000) {
  const handle = await page.waitForFunction(
    (source) => {
      const re = new RegExp(source, "i")
      return (
        Array.from(document.querySelectorAll("button[aria-pressed]")).find(
          (b) => re.test(b.textContent || "") && !b.disabled,
        ) ?? null
      )
    },
    { timeout },
    pattern,
  )
  const element = handle.asElement()
  if (!element) throw new Error(`No enabled aria-pressed button matching ${pattern}`)
  const alreadyPressed = await element.evaluate((b) => b.getAttribute("aria-pressed") === "true")
  if (!alreadyPressed) await element.click()
  await page.waitForFunction(
    (source) => {
      const re = new RegExp(source, "i")
      const b = Array.from(document.querySelectorAll("button[aria-pressed]")).find((el) =>
        re.test(el.textContent || ""),
      )
      return Boolean(b) && b.getAttribute("aria-pressed") === "true"
    },
    { timeout },
    pattern,
  )
}

/**
 * Check a native `<input type="checkbox">` (C-14, `components/ui/checkbox.tsx`)
 * ONLY if it is not already checked, keyed on the visible `<label>` text
 * beside it — same idempotent shape as `pressToggleOnce`, for the one
 * control that renders as a real checkbox input rather than an
 * `aria-pressed` button (S-20's "Weak topics only").
 *
 * `visitRoute` re-navigates for every breakpoint plus axe, so any drive
 * written into `ready` runs repeatedly. The state this checkbox controls is
 * local React state (`useState`, `PracticeGenerator.tsx`) rather than
 * anything the server persists, and every `page.goto` is a real full
 * navigation that remounts the app from scratch — so in practice a plain
 * click would be idempotent-safe here too, but this mirrors
 * `pressToggleOnce`'s defensive check-before-click shape rather than relying
 * on that distinction staying true.
 */
async function pressCheckboxOnce(page, labelPattern, timeout = 15_000) {
  const handle = await page.waitForFunction(
    (source) => {
      const re = new RegExp(source, "i")
      const label = Array.from(document.querySelectorAll("label")).find((l) =>
        re.test(l.textContent || ""),
      )
      return label ? label.querySelector('input[type="checkbox"]') : null
    },
    { timeout },
    labelPattern,
  )
  const element = handle.asElement()
  if (!element) throw new Error(`No checkbox found under a label matching ${labelPattern}`)
  const alreadyChecked = await element.evaluate((el) => el.checked)
  if (!alreadyChecked) await element.click()
  await page.waitForFunction(
    (source) => {
      const re = new RegExp(source, "i")
      const label = Array.from(document.querySelectorAll("label")).find((l) =>
        re.test(l.textContent || ""),
      )
      const input = label ? label.querySelector('input[type="checkbox"]') : null
      return Boolean(input) && input.checked
    },
    { timeout },
    labelPattern,
  )
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

/** Copies the app session out of `page`'s localStorage verbatim, so an
 * isolated Lighthouse browser can authenticate as exactly the same user
 * without re-deriving the session shape. Returns the raw string (or null for
 * an unauthenticated page / an origin with no session). */
async function sessionSnapshot(page) {
  try {
    return await page.evaluate(() => window.localStorage.getItem("lemely.session"))
  } catch {
    return null
  }
}

/**
 * Runs Lighthouse in its **own throwaway Chromium process**, never in the
 * audit's main browser.
 *
 * This is load-bearing, not tidiness. Lighthouse's default config collects a
 * full performance trace and a full-page screenshot per run; driven through a
 * shared page, that cost accumulates in the one renderer that also holds every
 * injected session, and past runs (`/tmp/audit_v4.log`, `/tmp/audit_v5.log`)
 * died mid-walk with `Target closed`/`Session closed` at or immediately after
 * a Lighthouse call — the browser process itself dying, which then made every
 * later route report a phantom CDP error. Isolating Lighthouse bounds peak
 * memory to one run and, just as importantly, makes a Lighthouse-induced crash
 * survivable: it can no longer take the authenticated contexts with it.
 *
 * The signature is deliberately unchanged (`page` is now the *source of the
 * session*, not the audit target), so all call sites keep working as-is.
 *
 * A failure here is recorded as null scores + the error, never swallowed:
 * `scripts/check_ui_gates.py` already fails on a null accessibility score, so
 * a Lighthouse that could not run fails the gate rather than passing by
 * omission — while the remaining ~11 minutes of the run still complete.
 */
async function runLighthouseAudit(url, page, slug, { authed }) {
  const rawSession = authed ? await sessionSnapshot(page) : null
  let lhBrowser
  try {
    lhBrowser = await puppeteer.launch({ headless: true })
    const lhPage = await lhBrowser.newPage()
    if (rawSession) {
      await lhPage.evaluateOnNewDocument((raw) => {
        // Same opaque-origin guard as `injectSession` — Lighthouse navigates
        // to `about:blank` between its own passes.
        if (window.location.origin === "null") return
        window.localStorage.setItem("lemely.session", raw)
      }, rawSession)
    }

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
      lhPage,
    )
    const lhr = result.lhr
    fs.writeFileSync(path.join(LH_DIR, `${slug}.json`), JSON.stringify(lhr, null, 2))
    const scores = {}
    for (const cat of LIGHTHOUSE_CATEGORIES) {
      scores[cat] = lhr.categories[cat] ? Math.round(lhr.categories[cat].score * 100) : null
    }
    return { slug, scores }
  } catch (err) {
    const message = String(err?.message ?? err)
    log(`  !! Lighthouse FAILED for ${slug}: ${message}`)
    const scores = {}
    for (const cat of LIGHTHOUSE_CATEGORIES) scores[cat] = null
    return { slug, scores, error: message }
  } finally {
    if (lhBrowser) await lhBrowser.close().catch(() => {})
  }
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

/**
 * Drives Onboarding.tsx's real S-01 -> S-02 transition: select Physics, then
 * Continue (which really calls `PUT /api/me/student-profile/enrolments`).
 *
 * Idempotent by construction, because it is called from `ready` and `ready`
 * runs after EVERY navigation `visitRoute` makes for a state — see
 * `pressToggleOnce`. Physics specifically because it is the one subject with
 * a viable placement bank (0625), so the S-02 -> S-03 exit this drive sets up
 * lands on the available invite rather than the refusal.
 */
async function driveToQuestionnaire(page) {
  await waitForText(page, "What are you studying?")
  await pressToggleOnce(page, "Physics")
  await clickButtonByText(page, "^continue$")
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

  // Clear before typing, and PROVE the field holds what we meant. A
  // `click({ clickCount: 3 })` does NOT select the contents of an
  // `input[type=number]` in headless Chromium, so the original
  // triple-click-then-type *appended*: the seeded item's 75 became "750".
  // That is above the question's `max`, so the browser's own constraint
  // validation refused to submit the form — no request, no visible error —
  // and the run died 15s later waiting for a panel that could never appear.
  // Ctrl+A does select inside a number input.
  await marksInput.click()
  await page.keyboard.down("Control")
  await page.keyboard.press("KeyA")
  await page.keyboard.up("Control")
  await marksInput.type("0")
  const typed = await marksInput.evaluate((el) => el.value)
  if (typed !== "0") {
    throw new Error(
      `T-08 marks field holds ${JSON.stringify(typed)}, expected "0" — clear-before-type ` +
        `failed, so the form would be refused as out of range rather than saved`,
    )
  }

  await clickButtonByText(page, "^save correction$")

  // Wait for the mutation's actual outcome rather than for one hoped-for
  // string. A successful resolve calls ReviewItem.tsx's `goNext`, which — with
  // no later item in the queue — navigates to /teacher/review, so the override
  // panel never renders on *this* page even on success. And a refusal (server
  // error, or the client-side range check) leaves the page in place, which as a
  // bare `waitForText` was indistinguishable from a slow save. Reporting the
  // refusal text is what turns the next failure of this kind into one line.
  const itemPath = new URL(url).pathname
  const outcomeHandle = await page.waitForFunction(
    (path) => {
      if (window.location.pathname !== path) return "navigated"
      const text = document.body.innerText
      if (/Teacher correction on record/i.test(text)) return "panel"
      const refusal =
        text.match(/Couldn't save:[^\n]*/i) ?? text.match(/Enter a whole number of marks[^\n]*/i)
      return refusal ? refusal[0] : null
    },
    { timeout: 15_000 },
    itemPath,
  )
  const outcome = await outcomeHandle.jsonValue()
  if (outcome !== "navigated" && outcome !== "panel") {
    throw new Error(`T-08 "Save correction" was refused: ${outcome}`)
  }

  // Come back to the item so the state this route is here to capture is the
  // one on screen. `visitRoute` re-navigates per breakpoint anyway; this makes
  // the setup self-verifying — if the override did not persist, it fails here
  // rather than silently screenshotting an un-corrected item as "corrected".
  await gotoReady(page, url, (p) => waitForText(p, "Teacher correction on record"))
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
  // ── P4.8 chunk C · the four S-01..S-05 sessions ──────────────────────────
  // Four DISTINCT student accounts, one per state, because
  // `PlacementService.availability` excludes a student's own prior placement
  // questions for the same subject (D4.6 §4): reusing one account across
  // "invite available" and "already completed" would report the pool
  // exhausted on the very screen meant to show it available. The seed builds
  // them that way deliberately — see scripts/seed_e2e.py's `placement` block.
  const placementUnonboardedSession = {
    accessToken: seed.placement.students.unonboarded.accessToken,
    userId: seed.placement.students.unonboarded.userId,
    role: "student",
  }
  const placementAvailableSession = {
    accessToken: seed.placement.students.available.accessToken,
    userId: seed.placement.students.available.userId,
    role: "student",
  }
  const placementInProgressSession = {
    accessToken: seed.placement.students.inProgress.accessToken,
    userId: seed.placement.students.inProgress.userId,
    role: "student",
  }
  const placementCompletedSession = {
    accessToken: seed.placement.students.completed.accessToken,
    userId: seed.placement.students.completed.userId,
    role: "student",
  }
  const placementSubject = seed.placement.subjectCode
  const placementTestUrl = `/student/placement/test/${seed.placement.students.inProgress.assignmentId}`
  const placementResultUrl = `/student/placement/result/${seed.placement.students.completed.assignmentId}`

  // ── P4.9 chunk C · the S-20..S-23 sessions ───────────────────────────────
  // Three DISTINCT student accounts, none wearing two hats: a student with
  // recorded weaknesses cannot also demonstrate the honest `no_weaknesses`
  // refusal, and a student with cards due today cannot also demonstrate
  // "nothing due today". The seed builds them that way deliberately — see
  // scripts/seed_e2e.py's `practice` block.
  const practiceActiveSession = {
    accessToken: seed.practice.students.active.accessToken,
    userId: seed.practice.students.active.userId,
    role: "student",
  }
  const practiceSettledSession = {
    accessToken: seed.practice.students.settled.accessToken,
    userId: seed.practice.students.settled.userId,
    role: "student",
  }
  const practiceBareSession = {
    accessToken: seed.practice.students.bare.accessToken,
    userId: seed.practice.students.bare.userId,
    role: "student",
  }
  const practiceSubject = seed.practice.subjectCode

  // ── P4.10 chunk C · the S-24/S-25 sessions ───────────────────────────────
  // S-24 has four states and two of them provably cannot share an account:
  // `generated: false` (no plan row this ISO week) and `available: false /
  // no_signal` (a plan row that IS a persisted refusal) are mutually exclusive
  // per account per week. The three practice accounts above already split that
  // way, so no new account is created. The fourth state — a week with every
  // session complete — goes on `placement.students.completed`, because
  // completing `active`'s sessions would destroy the populated-week capture.
  const planCompleteSession = {
    accessToken: seed.placement.students.completed.accessToken,
    userId: seed.placement.students.completed.userId,
    role: "student",
  }
  const studyPlanSubject = seed.studyPlan.subjectCode
  const studyPlanWeekUrl = `/student/plan/${studyPlanSubject}`
  const studyPlanSessionUrl = `/student/plan/${studyPlanSubject}/session/${seed.studyPlan.activeSessionId}`
  // A well-formed id that is deliberately not in anyone's current week. The
  // route must reach S-25's `notInCurrentWeek` arm, not a 422 on the id shape.
  const studyPlanAbsentSessionUrl = `/student/plan/${studyPlanSubject}/session/00000000-0000-4000-8000-000000000000`
  const practiceUnsubmittedSetUrl = `/student/practice/set/${seed.practice.students.active.unsubmittedAssignmentId}`
  const practiceUnsubmittedResultUrl = `/student/practice/result/${seed.practice.students.active.unsubmittedAssignmentId}`
  const practiceMarkingResultUrl = `/student/practice/result/${seed.practice.students.active.markingAssignmentId}`
  const practiceMarkedResultUrl = `/student/practice/result/${seed.practice.students.active.markedAssignmentId}`
  const practiceMarkedPrintUrl = `/student/practice/print/${seed.practice.students.active.markedAssignmentId}`

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
    // ── G-11 · Account & devices — the devices section (P5.7 chunk B) ─────
    // Authed but portal-agnostic: the route is one screen for all five roles,
    // so auditing it under one session covers it for every role. The student
    // session is used because it is the one every other student entry already
    // builds. G-10 (the device-limit challenge) is NOT here: it needs an
    // account already holding three live devices, which is a seed precondition
    // rather than a navigation — P5.11's job, recorded so it is not mistaken
    // for covered.
    {
      screenId: "G-11",
      slug: "settings-devices",
      path: "/settings/devices",
      session: decliningStudentSession,
      ready: (page) => waitForText(page, "Signed-in devices"),
      authed: true,
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
    // ── Student onboarding + placement (P4.8 chunk C · S-01..S-05) ────────
    // These five screens shipped in P4.8 chunks A and B with NO registry
    // entry, so `ui-thresholds` was green over them without ever loading
    // one — the same vacuous pass this file's header warns about, and the
    // reason the header's "deliberately NOT in this registry" list is
    // corrected above rather than left to rot.
    {
      // S-01 · the subjects step, on a genuinely un-onboarded account (no
      // profile, no enrolment) — the real first-run state, not a reset one.
      screenId: "S-01",
      slug: "student-onboard-subjects",
      path: "/student/onboard",
      session: placementUnonboardedSession,
      ready: (page) => waitForText(page, "What are you studying?"),
      authed: true,
    },
    {
      // S-02 · the questionnaire step. Only reachable by actually completing
      // S-01, so the drive works the real UI (pick Physics, Continue) rather
      // than deep-linking a state the product cannot get into on its own.
      // `lighthouse: false` — these are further states of the onboarding
      // *screen*, not further routes to score.
      //
      // The drive lives in `ready`, NOT in `setup`, and that is load-bearing:
      // `visitRoute` calls `setup` once but then calls `gotoReady` again for
      // every breakpoint and once more for axe, and `Onboarding.tsx` holds
      // `wizardStep` in component state that remounts as `"subjects"` on
      // every load (its seeding effect restores the *answers* from the
      // server but never which step you were on). A `setup`-driven wizard
      // state is therefore undone by the first reload, and every capture
      // after the first would have been the subjects step wearing the
      // questionnaire's slug. See `pressToggleOnce` for why re-running the
      // drive against an account the previous pass already mutated is safe.
      screenId: "S-02",
      path: "/student/onboard",
      session: placementUnonboardedSession,
      authed: true,
      states: [
        {
          state: "questionnaire",
          slug: "student-onboard-questionnaire",
          lighthouse: false,
          ready: async (page) => {
            await driveToQuestionnaire(page)
            await waitForText(page, "Which school")
          },
        },
        {
          // S-02 · a question the student has SKIPPED, which is the one
          // rendering D4.5 turns on and the one the entry above does not
          // reach: `SkippableSlider` shows `unsetLabel` ("Not set") while
          // the thumb sits at `min`, because an untouched field is `NULL`
          // and must never render as an answer the student gave. A
          // regression to `formatValue(min)` would print "0 hours/week" —
          // invented precision that screenshots perfectly clean — so this
          // state is captured on its own rather than trusted to the unit
          // tests. Reached by skipping the two questions before it, which
          // is also how a real student gets here.
          state: "questionnaire-skipped",
          slug: "student-onboard-questionnaire-skipped",
          lighthouse: false,
          ready: async (page) => {
            await driveToQuestionnaire(page)
            await waitForText(page, "Which school")
            await clickButtonByText(page, "^skip$")
            await waitForText(page, "outside school")
            await clickButtonByText(page, "^skip$")
            await waitForText(page, "hours can you study each week")
            // The assertion, not decoration: the slider reports "Not set",
            // not the value its thumb is resting on.
            await waitForText(page, "Not set")
          },
        },
      ],
    },
    {
      // S-03 · placement invite, AVAILABLE. 0625 is the only subject with a
      // viable bank, and the seed guarantees it (a pinned Paper-2 bank of its
      // own MCQ rows — see scripts/seed_e2e.py's PLACEMENT_PAPER_NUMBER).
      screenId: "S-03",
      slug: "student-placement-invite",
      path: `/student/placement/${placementSubject}`,
      session: placementAvailableSession,
      ready: (page) => waitForText(page, "Get a real starting picture"),
      authed: true,
    },
    {
      // S-03 · placement invite, UNAVAILABLE — and this is not a second-class
      // capture. 0580/0606 genuinely have zero ingested questions (D4.6 §5),
      // so the honest `no_questions` refusal is real product behaviour P4.8
      // exists to keep on screen, and auditing only the happy path would be
      // the vacuous pass again. Same screen, own session-free state.
      screenId: "S-03",
      path: "/student/placement/0580",
      session: placementAvailableSession,
      authed: true,
      states: [
        {
          state: "unavailable",
          slug: "student-placement-invite-unavailable",
          lighthouse: false,
          ready: (page) => waitForText(page, "No placement test yet for this subject"),
        },
      ],
    },
    {
      // S-04 · placement test in progress — the product's FIRST question-
      // rendering + answer-input surface, and the one that owns the answer-
      // persistence behaviour four separate defects were fixed in (D4.15).
      // The seed leaves this assignment created and never submitted.
      screenId: "S-04",
      slug: "student-placement-test",
      path: placementTestUrl,
      session: placementInProgressSession,
      ready: (page) => waitForText(page, "Question 1 of"),
      authed: true,
    },
    {
      // S-05 · placement result, really marked: the seed takes and submits
      // this one through the unmodified quiz take/submit/mark path, with
      // exactly one deliberately wrong answer, so the topic breakdown is
      // backed by a real WeaknessRecord rather than a stubbed payload.
      //
      // `ready` deliberately does NOT match "starting picture": that phrase
      // renders on PlacementInvite too ("Get a real starting picture in X"),
      // so it would have been satisfied by the invite screen and this entry
      // would have passed without ever loading the result — the vacuous pass
      // again, on the one screen whose whole point is the honesty framing.
      // The string below is unique to PlacementResult's *marked* branch and
      // is the UI-spec framing itself (a baseline, never a grade), so a
      // regression that dropped it would fail this gate rather than hide.
      screenId: "S-05",
      slug: "student-placement-result",
      path: placementResultUrl,
      session: placementCompletedSession,
      ready: (page) => waitForText(page, "This is a baseline, not a grade"),
      authed: true,
    },
    // ── Student practice + flashcards (P4.9 chunk C · S-20..S-23) ─────────
    // These four screens shipped in P4.9 chunks A and B with NO registry
    // entry, so `ui-thresholds` was green over them without ever loading
    // one — the same vacuous pass P4.8 chunk C's own header note warns
    // about. Every `ready` string below was grepped across `web/src` before
    // use to confirm it targets the branch it claims (see the P4.9 chunk C
    // report for the grep counts); where a heading's literal copy is
    // deliberately shared across two screens (`"No weak topics recorded
    // yet"`, S-20 and S-22's own `no_weaknesses` refusals), the two land on
    // different routes so there is no route-collision risk, only shared
    // vocabulary.
    {
      // S-20 · practice generator, `active` session, DEFAULT route state.
      // `insufficient_pool` is not a corner case here — it is the state this
      // seed's small hermetic bank reaches at S-20's own frontend default
      // count (10), reachable by URL alone with no created set required
      // (`PracticeGenerator.tsx`'s shortfall panel renders off the live
      // preview query). Topic chips nested by syllabus group and the
      // weak-topic prefill (from set A's one deliberate wrong answer) are
      // both on this same render — see scripts/seed_e2e.py's `practice`
      // block for how set A produces the WeaknessRecord this prefill reads.
      screenId: "S-20",
      slug: "student-practice-generator",
      path: `/student/practice/${practiceSubject}`,
      session: practiceActiveSession,
      ready: (page) => waitForText(page, "Only \\d+ of \\d+ requested questions match"),
      authed: true,
    },
    {
      // S-20 · the honest `no_questions` refusal — 0580 genuinely has zero
      // ingested questions, same real product behaviour P4.8 chunk C's S-03
      // capture already established for placement.
      screenId: "S-20",
      path: "/student/practice/0580",
      session: practiceActiveSession,
      authed: true,
      states: [
        {
          state: "no-questions",
          slug: "student-practice-generator-no-questions",
          lighthouse: false,
          ready: (page) => waitForText(page, "No practice material for this filter set"),
        },
      ],
    },
    {
      // S-20 · the honest `no_weaknesses` refusal, on the `bare` account
      // that has none. Driven live through the real "Weak topics only"
      // checkbox (`pressCheckboxOnce` — tolerant of already being checked,
      // since `visitRoute` re-navigates this same drive four times) rather
      // than deep-linked, because the refusal only renders once that filter
      // is actually applied.
      screenId: "S-20",
      path: `/student/practice/${practiceSubject}`,
      session: practiceBareSession,
      authed: true,
      states: [
        {
          state: "no-weaknesses",
          slug: "student-practice-generator-no-weaknesses",
          lighthouse: false,
          ready: async (page) => {
            await pressCheckboxOnce(page, "Weak topics only")
            await waitForText(page, "No weak topics recorded yet")
          },
        },
      ],
    },
    {
      // S-21 · working view — the reusable QuizTaker, same component S-04
      // already Lighthouse-scores, hence `lighthouse: false` here. Set B is
      // created but never touched.
      screenId: "S-21",
      path: practiceUnsubmittedSetUrl,
      session: practiceActiveSession,
      authed: true,
      states: [
        {
          state: "working",
          slug: "student-practice-set-working",
          lighthouse: false,
          ready: (page) => waitForText(page, "Question 1 of"),
        },
      ],
    },
    {
      // S-21 · finish summary, `not_submitted` — set B again, this time via
      // its result route (`submissionStatus` is `not_started`).
      screenId: "S-21",
      path: practiceUnsubmittedResultUrl,
      session: practiceActiveSession,
      authed: true,
      states: [
        {
          state: "not-submitted",
          slug: "student-practice-result-not-submitted",
          lighthouse: false,
          ready: (page) => waitForText(page, "This practice set hasn't been submitted yet"),
        },
      ],
    },
    {
      // S-21 · finish summary, `marking` — set C: answered and submitted,
      // but scripts/seed_e2e.py deliberately never calls
      // QuizMarkingService.mark_submission for it (the real HTTP route
      // marks on a background thread; the service does not, which is what
      // makes this state seedable rather than a race — see the seed's own
      // comment at set C).
      screenId: "S-21",
      path: practiceMarkingResultUrl,
      session: practiceActiveSession,
      authed: true,
      states: [
        {
          state: "marking",
          slug: "student-practice-result-marking",
          lighthouse: false,
          ready: (page) => waitForText(page, "Marking your .*practice set"),
        },
      ],
    },
    {
      // S-21 · finish summary, `marked` — set A: one deliberate mistake,
      // submitted, and marked through the unmodified quiz-taking/marking
      // repos. The richest of S-21's five captures, so this is the one
      // Lighthouse-scored (no `states` wrapper -> `lighthouse` defaults
      // true). The ready string is `"{awarded} of {maximum} marks."`,
      // deliberately not a heading shared with any other screen's summary
      // copy (PlacementResult's own "X of Y marks." paragraph is a
      // different code fragment entirely — grepped to confirm).
      screenId: "S-21",
      slug: "student-practice-result-marked",
      path: practiceMarkedResultUrl,
      session: practiceActiveSession,
      ready: (page) => waitForText(page, "\\d+ of \\d+ marks?\\."),
      authed: true,
    },
    {
      // S-21 · print/export view for the same marked set — the answer-free
      // worksheet payload (D3.8: no model answer/mark scheme/MCQ answer
      // field exists on this DTO by construction).
      screenId: "S-21",
      path: practiceMarkedPrintUrl,
      session: practiceActiveSession,
      authed: true,
      states: [
        {
          state: "print",
          slug: "student-practice-print",
          lighthouse: false,
          ready: (page) => waitForText(page, "Answer on screen instead"),
        },
      ],
    },
    {
      // S-22 · flashcard decks, `active` session — cards due today. The
      // richest of S-22's four captures (due-today summary AND the new-deck
      // form both render), so this is the one Lighthouse-scored.
      screenId: "S-22",
      slug: "student-flashcards-due",
      path: `/student/flashcards/${practiceSubject}`,
      session: practiceActiveSession,
      ready: (page) => waitForText(page, "\\d+ cards? due today"),
      authed: true,
    },
    {
      // S-22 · flashcard decks, `settled` session — "nothing due today"
      // carrying the real next-due date a genuine SM-2 `good` review
      // produced (scripts/seed_e2e.py asserts this against `due_session`
      // itself before ever handing the seed payload to this harness).
      // Combined with "Decks grouped by topic" (FlashcardDecks' own fixed
      // intro copy) so this ready string cannot be satisfied by S-23's
      // identical "Nothing due today" heading on a different route.
      screenId: "S-22",
      path: `/student/flashcards/${practiceSubject}`,
      session: practiceSettledSession,
      authed: true,
      states: [
        {
          state: "settled",
          slug: "student-flashcards-settled",
          lighthouse: false,
          ready: (page) =>
            waitForText(page, "(?=[\\s\\S]*Nothing due today)(?=[\\s\\S]*Decks grouped by topic)"),
        },
      ],
    },
    {
      // S-22 · flashcard decks, `bare` session — two states of one genuinely
      // empty account: the empty deck list itself, and the free
      // `no_weaknesses` 409 driven live through "Generate from a weakness"
      // (`generate_deck` resolves the topic, and raises, before ever
      // calling the generator — verified by reading `flashcard_repo.py`, so
      // this costs $0.00 Gemini). `pressToggleOnce` (already built for
      // S-02's aria-pressed drive) is reused verbatim for the mode button;
      // the submit click itself is naturally idempotent — a `bare` account
      // never gains a weakness, so re-driving it on every `visitRoute` pass
      // reproduces the identical 409 every time.
      screenId: "S-22",
      path: `/student/flashcards/${practiceSubject}`,
      session: practiceBareSession,
      authed: true,
      states: [
        {
          state: "empty",
          slug: "student-flashcards-empty",
          lighthouse: false,
          ready: (page) => waitForText(page, "No decks yet for"),
        },
        {
          state: "no-weaknesses",
          slug: "student-flashcards-no-weaknesses",
          lighthouse: false,
          ready: async (page) => {
            await pressToggleOnce(page, "Generate from a weakness")
            await clickButtonByText(page, "^Generate deck$")
            await waitForText(page, "No weak topics recorded yet")
          },
        },
      ],
    },
    {
      // S-23 · flashcard review, `active` session — a card front with the
      // reveal control and, once revealed, all four grade buttons.
      // Revealing is local UI state only (no request fired) and always
      // starts unrevealed on a fresh navigation, so driving it in `ready` is
      // safe across `visitRoute`'s repeated re-navigation. Grading is
      // NEVER driven here — it is irreversible (reschedules the card via
      // real SM-2) and would destroy this capture's own repeatability, plus
      // S-22 `active`'s "N cards due today" capture depends on these same
      // cards staying due.
      screenId: "S-23",
      slug: "student-flashcard-review",
      path: `/student/flashcards/review/${practiceSubject}`,
      session: practiceActiveSession,
      ready: async (page) => {
        await waitForText(page, "Reveal answer")
        await clickButtonByText(page, "^Reveal answer")
        await waitForText(page, "Again")
      },
      authed: true,
    },
    {
      // S-23 · flashcard review, `settled` session — "nothing due today".
      // Combined with "Back to decks" (rendered in this exact branch, and
      // in the never-driven end-of-session summary, but never on S-22's own
      // "nothing due" render) so this ready string cannot be satisfied by
      // S-22's identical heading on a different route.
      screenId: "S-23",
      path: `/student/flashcards/review/${practiceSubject}`,
      session: practiceSettledSession,
      authed: true,
      states: [
        {
          state: "settled",
          slug: "student-flashcard-review-settled",
          lighthouse: false,
          ready: (page) =>
            waitForText(page, "(?=[\\s\\S]*Nothing due today)(?=[\\s\\S]*Back to decks)"),
        },
      ],
    },
    {
      // S-24 · the study-plan week, `active` session, DEFAULT route state —
      // the real populated week. `active` is the only practice account with a
      // WeaknessRecord (the seed's deliberately-wrong marked set), which is
      // the signal `generate` needs.
      //
      // The ready predicate reads the seeded session count rather than a
      // loose `\d+ of \d+`, so a week that came back short or partly complete
      // fails the gate instead of screenshotting cleanly under this name.
      screenId: "S-24",
      slug: "student-study-plan-week",
      path: studyPlanWeekUrl,
      session: practiceActiveSession,
      ready: (page) =>
        waitForText(page, `0 of ${seed.studyPlan.activeSessionCount} sessions? done`),
      authed: true,
    },
    {
      // S-24 · the persisted honest refusal (`generated: true`,
      // `available: false`, `reason: "no_signal"`). `settled` has none of the
      // planner's three signals, so this refusal is real, not forced.
      // D4.13's whole point is that this is NOT the same state as the one
      // below it, and both used to arrive as an empty `sessions` list.
      screenId: "S-24",
      path: studyPlanWeekUrl,
      session: practiceSettledSession,
      authed: true,
      states: [
        {
          state: "refused",
          slug: "student-study-plan-week-refused",
          lighthouse: false,
          ready: (page) => waitForText(page, "Not enough to plan from yet"),
        },
      ],
    },
    {
      // S-24 · no plan generated this ISO week (`generated: false`). The seed
      // deliberately makes no call for `bare` — the state is the absence of
      // one, which is why it cannot share an account with the refusal above.
      screenId: "S-24",
      path: studyPlanWeekUrl,
      session: practiceBareSession,
      authed: true,
      states: [
        {
          state: "not-generated",
          slug: "student-study-plan-week-not-generated",
          lighthouse: false,
          ready: (page) => waitForText(page, "No plan for this week yet"),
        },
      ],
    },
    {
      // S-24 · every session in the week complete. Asserted as N of N off the
      // seeded count: a partially-completed week is the one failure mode here
      // that would still render — and screenshot — as a perfectly good
      // populated week.
      screenId: "S-24",
      path: studyPlanWeekUrl,
      session: planCompleteSession,
      authed: true,
      states: [
        {
          state: "week-complete",
          slug: "student-study-plan-week-complete",
          lighthouse: false,
          ready: (page) =>
            waitForText(
              page,
              `${seed.studyPlan.completedSessionCount} of ${seed.studyPlan.completedSessionCount} sessions? done`,
            ),
        },
      ],
    },
    {
      // S-25 · session detail, DEFAULT route state. The seed picks the session
      // whose topic really is in `active`'s recorded weak topics, so the arm
      // that renders here is the *provable* one. Asserting the weak-topic
      // sentence rather than the shared "Why this is in your plan" heading is
      // the point: all three rationale arms carry that heading, so matching it
      // would pass on the honest-absence arm too and name the capture for a
      // state it is not.
      screenId: "S-25",
      slug: "student-study-plan-session",
      path: studyPlanSessionUrl,
      session: practiceActiveSession,
      ready: (page) => waitForText(page, "is one of your recorded weak topics for this subject"),
      authed: true,
    },
    {
      // S-25 · a session id that is not in the current week. Not a 404 and not
      // an error: a rebuild supersedes the previous week rather than editing
      // it, so a bookmarked link lands here legitimately and must say that.
      screenId: "S-25",
      path: studyPlanAbsentSessionUrl,
      session: practiceActiveSession,
      authed: true,
      states: [
        {
          state: "not-in-current-week",
          slug: "student-study-plan-session-not-in-week",
          lighthouse: false,
          ready: (page) => waitForText(page, "has been rebuilt since this link was made"),
        },
      ],
    },
    // ── S-28 · Announcements & exam calendar (P5.8 chunk B) ───────────────
    // The `ready` probe deliberately targets the *announcements* heading and
    // not the countdown or a date row: `exam_dates` ships empty in every
    // environment this build produces (P5.5 chunk C built the ingestion path
    // and populated nothing), so the countdown legitimately does not render
    // and a probe waiting on it would hang and be misread as a route failure.
    //
    // The calendar half is therefore audited in its `no_timetable`/
    // `no_enrolment` state, which is the state it genuinely ships in — that is
    // coverage of the real screen, not a gap. When a timetable is ingested,
    // add a `dated` state here rather than replacing this one.
    {
      screenId: "S-28",
      slug: "student-announcements",
      path: "/student/announcements",
      session: practiceActiveSession,
      ready: (page) => waitForText(page, "From your teachers"),
      authed: true,
    },
    // ── S-29 · Leaderboards (P5.8 chunk C) ────────────────────────────────
    // `/student/board` has never been in this registry — the honest-empty
    // placeholder that stood here since P2.7 was never audited, so this is the
    // route's first coverage, not a re-audit.
    //
    // The `ready` probe targets the screen's own heading rather than a board
    // row, deliberately and for the same reason S-28's targets the
    // announcements heading: the seed awards no XP, so every scope
    // legitimately renders its empty state and a probe waiting on a ranked row
    // would hang and be misread as a route failure. The empty board IS the
    // state this ships in, so auditing it is coverage of the real screen.
    //
    // The default scope is `friends`, which needs no class and no school, so
    // this state exercises the board panel without depending on seeded
    // enrolment. When the seed grows XP events, add a populated state here
    // rather than replacing this one.
    {
      screenId: "S-29",
      slug: "student-standings",
      path: "/student/board",
      session: practiceActiveSession,
      ready: (page) => waitForText(page, "Effort, not marks"),
      authed: true,
    },
    // ── S-30 · Friends (P5.8 chunk C) ─────────────────────────────────────
    // The friend code is minted lazily on first read, so this route always has
    // one real thing to render regardless of seed state — the probe targets
    // the heading anyway, so a slow mint cannot be mistaken for a route
    // failure. The friends list itself renders its empty state (the seed
    // creates no friendships), which is the state this ships in.
    {
      screenId: "S-30",
      slug: "student-friends",
      path: "/student/friends",
      session: practiceActiveSession,
      ready: (page) => waitForText(page, "Who you are studying with"),
      authed: true,
    },
    // ── S-31 · Profile / XP / streak (P5.8 chunk D) ───────────────────────
    // The probe targets the screen's static intro line rather than the level
    // number or a calendar cell: the seed awards no XP, so this student is
    // level 1 with a 28-cell calendar of zeros and an all-zero weekly
    // breakdown. That is a fully-rendered screen, not an empty state — the
    // panels are all present with real zeros — so it is genuine coverage.
    //
    // Deliberately NOT probed: lifetime stats and achievements. They do not
    // exist on this screen and will not appear later (D5.13 §3); a future
    // session adding a probe for them would be building a state the product
    // decided against, not restoring a missing one.
    {
      screenId: "S-31",
      slug: "student-profile",
      path: "/student/profile",
      session: practiceActiveSession,
      ready: (page) =>
        waitForText(page, "Everything here measures work done"),
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
    browser = await launchAuditBrowser()
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
        browser = await launchAuditBrowser()
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
    "Not covered by this registry (P5 screens still on mock data): " +
      "/student/subject/:code, /student/board, " +
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
