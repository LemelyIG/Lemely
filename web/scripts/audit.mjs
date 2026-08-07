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
 * `ROUTE_REGISTRY` below is the full 21-route Phase-3 inventory — a
 * declarative table, not a hardcoded journey — covering:
 *   - 4 unauthenticated/student routes carried over from D2.10, run through
 *     `runStudentMainJourney()` because they are inherently a stateful
 *     sequence (sign up -> log in -> upload a real scan -> get a real
 *     paperId), not a bare navigation: /login (G-04), /student (S-06,
 *     non-empty), /student/correct (S-10), /student/result/:paperId
 *     (S-15/S-17).
 *   - 17 new routes run through the generic `visitRoute()` runner, reached by
 *     injecting a real session (a genuine access token from
 *     `scripts/seed_e2e.py`, decoded server-side exactly as a real login
 *     would produce — see `injectSession`) into `localStorage` and
 *     navigating directly, rather than re-driving each role's login UI for
 *     every route: G-05 (unauthenticated), the teacher's 11 routes, the
 *     parent's 4 routes, and the student's `/student/parents`.
 * Deliberately still NOT in this registry (P4/P5 screens still on mock data,
 * or Phase-3 routes that need a fixture the seed does not create — see the
 * end-of-run "not yet covered" log line):
 *   /student/subject/:code, /student/plan, /student/board, /student/onboard,
 *   /student/landing, /student/directions (P4/P5, mock data),
 *   /teacher/review/:itemId (no item needs review in the seed — every
 *   correction is HIGH-confidence by construction), and
 *   /teacher/quizzes/:quizId plus its results route (the seed creates no
 *   quiz, so both would 404 rather than render an empty state).
 * Note "no *populated* fixture" is NOT on its own a reason to leave a route
 * out: /teacher/grading and /teacher/schemes are audited in their genuinely
 * empty state, because an unlooked-at route is exactly how this gate became
 * vacuous.
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

/** Generic runner for one `ROUTE_REGISTRY` entry: screenshots the route's
 * current (real, not stubbed) state at all 3 breakpoints, checks each for
 * horizontal overflow, then runs one axe + Lighthouse pass at the desktop
 * viewport — the same shape `main()`'s G-04 section already used, pulled out
 * so the 15 new routes are data, not 15 more copies of that shape. */
/** `goto` + the route's readiness wait, with one retry on a detached-frame
 * error. The very first navigation on a freshly-created page in an origin
 * that already has an active PWA service worker (every route after the
 * first) can race a `controllerchange`-driven reload, which detaches the
 * frame mid-`waitForFunction` — a real Puppeteer/vite-plugin-pwa
 * interaction, not a flaky test to paper over with a longer timeout. One
 * clean re-navigation resolves it; a second failure is a real bug and still
 * throws. */
async function gotoReady(page, url, ready) {
  try {
    await page.goto(url, { waitUntil: "networkidle0" })
    if (ready) await ready(page)
  } catch (err) {
    if (!/detached/i.test(String(err?.message))) throw err
    await page.goto(url, { waitUntil: "networkidle0" })
    if (ready) await ready(page)
  }
}

async function visitRoute(page, route, { axeSummary, lighthouseSummary, responsiveViolations }) {
  const url = `${PREVIEW_URL}${route.path}`
  log(`${route.screenId} ${route.path} — screenshots + responsive check (3 breakpoints)...`)
  for (const bp of BREAKPOINTS) {
    await page.setViewport(bp)
    await gotoReady(page, url, route.ready)
    const violation = await checkNoHorizontalScroll(page, route.slug, bp.width)
    if (violation) responsiveViolations.push(violation)
    await shoot(page, route.screenId, route.state ?? "default", bp.width)
  }

  log(`${route.screenId} ${route.path} — axe + Lighthouse...`)
  await page.setViewport(AUDIT_VIEWPORT)
  await gotoReady(page, url, route.ready)
  axeSummary.push(await runAxe(page, route.slug))
  lighthouseSummary.push(
    await runLighthouseAudit(url, page, route.slug, { authed: route.authed }),
  )
}

/**
 * The 15 routes reached via `visitRoute()` (session injection + plain
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
  const classId = seed.class.classId
  // The parent's one linked child (D3.11) is the "declining" student — same
  // account for both sessions above, just wearing a different role's token.
  const childId = seed.students.declining.userId
  const subjectCode = "0625" // scripts/seed_e2e.py's SUBJECT_CODE — every declining-student attempt is this subject.

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
    // ── Teacher (9 routes) ─────────────────────────────────────────────────
    {
      screenId: "T-01",
      slug: "teacher-overview",
      path: "/teacher",
      session: teacherSession,
      ready: (page) => waitForText(page, "Good morning"),
      authed: true,
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
      // sr-only h1, so wait on the loaded-only eyebrow line instead. Empty
      // queue is the genuine state here — every seeded correction is
      // HIGH-confidence by construction (D3.9), so nothing needs review.
      ready: (page) => waitForText(page, "core recurring task"),
      authed: true,
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
    // ── Parent (4 routes) ────────────────────────────────────────────────
    {
      // With exactly one linked child (D3.11's spec-mandated behaviour —
      // Children.tsx `<Navigate replace>`s straight to P-02), /parent never
      // actually renders P-01's list UI for this seed; it renders P-02. That
      // is the real, spec-correct behaviour for a one-child parent, not a
      // gap in this registry — genuinely visiting /parent, not faking it.
      screenId: "P-01",
      slug: "parent-children",
      path: "/parent",
      session: parentSession,
      ready: (page) => waitForText(page, "Subjects"),
      authed: true,
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
    const routes = buildRouteRegistry(seed)
    const sessionsSeen = new Map()
    for (const route of routes) {
      const sessionKey = route.session
        ? `${route.session.role}:${route.session.userId}`
        : "unauth"
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
        await visitRoute(routePage, route, {
          axeSummary,
          lighthouseSummary,
          responsiveViolations,
        })
      } catch (err) {
        log(`!! ${route.screenId} ${route.path} FAILED: ${err?.message ?? err}`)
        routeFailures.push({ screenId: route.screenId, path: route.path, error: String(err?.message ?? err) })
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
  log(`Routes audited: ${axeSummary.length} (4 D2.10-era + 17 P3.10 chunk b)`)
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
    "Not covered by this registry (P4/P5 mock-data screens, or a route the seed cannot " +
      "reach at all): /student/subject/:code, /student/plan, /student/board, " +
      "/student/onboard, /student/landing, /student/directions, /teacher/review/:itemId, " +
      "/teacher/quizzes/:quizId(+/assignments/:id/results).",
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
