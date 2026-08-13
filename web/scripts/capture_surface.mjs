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
 * Usage:  node scripts/capture_surface.mjs <surface> [outDir]
 *         surface ∈ the keys of SURFACES below.
 * Assumes `npm run build` has run; serves `dist/` on a local port.
 *
 * P4.2 generalised this from the one screen it was written for. The harness
 * (server, session, viewports, the catch-all route, the duplicate check, the
 * console-error log) is now surface-agnostic; what each surface supplies is a
 * route, a set of states, the stubs those states need, and optionally an
 * interaction to perform before the shutter. Copying the file per surface was
 * the alternative, and eight copies of a duplicate-detector is how the
 * detector ends up disabled in seven of them.
 */

import { spawn } from "node:child_process"
import { createHash } from "node:crypto"
import fs from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"
import { chromium } from "@playwright/test"

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.resolve(__dirname, "..", "..")
const surfaceName = process.argv[2] ?? "student-dashboard"
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
const OVERVIEW_STATES = {
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

/* ── Surface 2 (P4.2): the correct-a-paper flow ──────────────────────────── */

/**
 * A stand-in scan. `setInputFiles` needs bytes, and a real PDF is not
 * required: nothing in these captures reaches a parser, because every request
 * is stubbed. The name is a real CAIE filename so the chosen-file row is
 * photographed at a realistic length rather than at "a.pdf".
 */
const SCAN_FIXTURE = {
  name: "0625_w24_qp_41.pdf",
  mimeType: "application/pdf",
  buffer: Buffer.alloc(1_487_232, 0),
}

/** One SSE frame, in the wire format `streamActivity` parses. */
function sse(frame) {
  return `data: ${JSON.stringify(frame)}\n\n`
}

/**
 * Frames that walk the panel through extraction and scheme resolution and
 * into marking, WITHOUT the terminal `phase: "complete"` frame.
 *
 * That omission is the point, not a shortcut. It is exactly the condition
 * P4.2 found unhandled: the stream closes having said nothing about a result,
 * and the screen used to fall silently back to "Ready when you are" with two
 * ticks and a half-drawn third stage. These captures are how that state is
 * looked at rather than reasoned about.
 */
const STALLED_STREAM =
  sse({ type: "extraction_progress", message: "Reading page 4 of 6", index: 4, total: 6 }) +
  sse({ type: "mark_scheme_progress", message: "Matched 0625 w24 paper 41" }) +
  sse({ type: "marking_progress", question_id: "3(b)", index: 3, total: 21 })

const CORRECT_STATES = {
  /** The screen as a student first meets it: nothing chosen, nothing running. */
  ready: {},
  /** A scan picked but not yet sent. The primary action becomes available. */
  "scan-chosen": { pickScan: true },
  /**
   * Marking in flight. The correct stream is left hanging, which is the real
   * first second of every run: `running` is true and no frame has arrived, so
   * every stage is still pending. It is not a claim about mid-run progress —
   * Playwright fulfils a body in one piece, so a partially-delivered stream
   * cannot be staged honestly here.
   */
  marking: { pickScan: true, mark: true, correct: { hang: true } },
  /** The service refuses the run. The failure names itself and offers retry. */
  failed: {
    pickScan: true,
    mark: true,
    correct: { status: 503, body: { detail: "The marking service is busy. Try again shortly." } },
  },
  /** The stream ends without a result. Used to be silent; now it is a failure. */
  stalled: { pickScan: true, mark: true, correct: { sse: STALLED_STREAM } },
}

/* ── Surface 2b: the result screen the flow lands on ─────────────────────── */

/** Field-for-field `ResultDTO`. Numbers are invented for the capture. */
const RESULT_FIXTURE = {
  code: "0625",
  paper: "Paper 41",
  session: "Nov 2024",
  markerLabel: "Marked by Lemely",
  headline: "63 out of 80, a grade B on this paper.",
  summary:
    "Method marks carried most of this paper. The marks that got away are clustered in two topics rather than spread across the paper.",
  awarded: 63,
  max: 80,
  pct: 79,
  grade: "B",
  boundaryYear: "2024",
  railLeft: 79,
  railFoot: "63/80",
  railNote: "Four marks below the A boundary for this session.",
  theory: [],
  integrity: [
    { mark: "check", color: "ok", label: "Handwriting legible", detail: "Every page read on the first pass." },
    { mark: "dash", color: "t2", label: "No integrity flags", detail: "Nothing on this paper was flagged for review." },
  ],
  provenance: "0625_w24_qp_41.pdf\nmarked 2026-08-13T18:04:11Z",
}

const RESULT_STATES = {
  /** History view: no per-question detail is stored, and it says so. */
  history: { result: { body: RESULT_FIXTURE } },
  loading: { result: { delayMs: 8_000 } },
  missing: { result: { status: 404, body: { detail: "No such paper." } } },
  error: { result: { status: 500, body: { detail: "Result store unavailable." } } },
}

/* ── P4.3, surface 3: the study surfaces (Read lane) ───────────────────────
 *
 * Same rule as everything above: these numbers are invented for the capture.
 * They are shaped field-for-field like the real DTOs (`flashcardTypes.ts`,
 * `studyPlanTypes.ts`, `practiceTypes.ts`) so the layout under test is the
 * layout that ships, and they are never product data and never quoted as a
 * result anywhere.
 */

const DECKS_FIXTURE = [
  {
    id: "deck-1",
    subjectCode: "0625",
    topic: "1.2 Motion",
    title: "Speed, velocity and acceleration",
    description: null,
    origin: "topic",
    cardCount: 18,
    dueCount: 6,
    createdAt: "2026-08-01T09:00:00Z",
  },
  {
    id: "deck-2",
    subjectCode: "0625",
    topic: "1.2 Motion",
    title: "Distance-time graphs",
    description: null,
    origin: "manual",
    cardCount: 9,
    dueCount: 0,
    createdAt: "2026-08-04T09:00:00Z",
  },
  {
    id: "deck-3",
    subjectCode: "0625",
    topic: "2.1 Thermal physics",
    title: "Specific heat capacity",
    description: null,
    origin: "weakness",
    cardCount: 24,
    dueCount: 11,
    createdAt: "2026-08-06T09:00:00Z",
  },
]

function dueCard(n, source) {
  return {
    id: `card-${n}`,
    front:
      n === 1
        ? "A car accelerates uniformly from 5 m/s to 25 m/s in 8 s. What is its acceleration?"
        : `Front of card ${n}`,
    back: n === 1 ? "2.5 m/s²" : `Back of card ${n}`,
    position: n,
    source,
    sourceQuestionId: null,
    repetitions: 2,
    easeFactor: 2.5,
    intervalDays: 4,
    lapses: 0,
    dueAt: "2026-08-13T00:00:00Z",
    lastReviewedAt: "2026-08-09T00:00:00Z",
  }
}

const DUE_FIXTURE = {
  cards: [dueCard(1, "ai"), dueCard(2, "manual"), dueCard(3, "ai")],
  totalDue: 17,
  nextDueAt: null,
}

const NOTHING_DUE_FIXTURE = { cards: [], totalDue: 0, nextDueAt: "2026-08-15T08:00:00Z" }

const DECKS_STATES = {
  /** The populated case: three decks over two topics, cards due today. */
  populated: { decks: DECKS_FIXTURE, due: DUE_FIXTURE },
  /** Up to date. This is the state that used to draw a warn-coloured border. */
  nothingDue: { decks: DECKS_FIXTURE, due: NOTHING_DUE_FIXTURE },
  /** The composed empty state, marginalia and all. */
  empty: { decks: [], due: NOTHING_DUE_FIXTURE },
  /** The skeleton. Never fulfilled; the context is torn down first. */
  loading: { delayMs: 8_000 },
  error: { decks: null, status: 500, due: NOTHING_DUE_FIXTURE },
}

const REVIEW_STATES = {
  /** Card face, answer hidden — the screen's resting state. */
  question: { due: DUE_FIXTURE },
  /** Answer shown, with the four grade buttons and their Kbd hints. */
  revealed: { due: DUE_FIXTURE, reveal: true },
  nothingDue: { due: NOTHING_DUE_FIXTURE },
}

const PLAN_SESSIONS = [
  {
    id: "s1",
    date: "2026-08-13",
    topic: "1.2 Motion",
    activityType: "practice",
    durationMinutes: 45,
    focus: "Practice on 1.2 Motion",
    completedAt: "2026-08-13T10:00:00Z",
  },
  {
    id: "s2",
    date: "2026-08-13",
    topic: "2.1 Thermal physics",
    activityType: "flashcards",
    durationMinutes: 20,
    focus: "Flashcards on 2.1 Thermal physics",
    completedAt: null,
  },
  {
    id: "s3",
    date: "2026-08-14",
    topic: "3.3 Electrical circuits",
    activityType: "practice",
    durationMinutes: 60,
    focus: "Practice on 3.3 Electrical circuits",
    completedAt: null,
  },
]

const PLAN_FIXTURE = {
  generated: true,
  plan: {
    id: "plan-1",
    subjectCode: "0625",
    weekStart: "2026-08-10",
    weeklyHours: 4,
    available: true,
    reason: null,
    generatedAt: "2026-08-10T08:00:00Z",
    sessions: PLAN_SESSIONS,
  },
}

const PLAN_STATES = {
  /* One of three sessions done, and it is the 45-minute one — so the session
     count (1 of 3) and the minutes bar (45 of 125) genuinely disagree. This
     state exists to make that visible: it is the case whose two numbers used
     to look like one number rendered twice. */
  populated: { plan: PLAN_FIXTURE },
  notGenerated: { plan: { generated: false, plan: null } },
  refused: {
    plan: {
      generated: true,
      plan: { ...PLAN_FIXTURE.plan, available: false, reason: "insufficient_signal", sessions: [] },
    },
  },
}

const PRACTICE_RESULT_STATES = {
  marked: {
    result: {
      body: {
        assignmentId: "assign-1",
        quizId: "quiz-1",
        subjectCode: "0625",
        marked: true,
        submissionStatus: "marked",
        awardedMarks: 14,
        maximumMarks: 20,
        questions: [
          { questionRef: "q1", position: 1, topic: "1.2 Motion", totalMarks: 4, awardedMarks: 4, confidenceBand: "high", confidenceScore: 0.97 },
          { questionRef: "q2", position: 2, topic: "1.2 Motion", totalMarks: 5, awardedMarks: 3, confidenceBand: "medium", confidenceScore: 0.84 },
          { questionRef: "q3", position: 3, topic: "2.1 Thermal physics", totalMarks: 5, awardedMarks: 5, confidenceBand: "high", confidenceScore: 0.95 },
          { questionRef: "q4", position: 4, topic: "3.3 Electrical circuits", totalMarks: 6, awardedMarks: 2, confidenceBand: "low", confidenceScore: 0.61 },
        ],
      },
    },
  },
  /** The wait. This is the state that was a bare spinning glyph. */
  marking: {
    result: {
      body: {
        assignmentId: "assign-1",
        quizId: "quiz-1",
        subjectCode: "0625",
        marked: false,
        submissionStatus: "submitted",
        awardedMarks: null,
        maximumMarks: null,
        questions: [],
      },
    },
  },
  notSubmitted: {
    result: {
      body: {
        assignmentId: "assign-1",
        quizId: "quiz-1",
        subjectCode: "0625",
        marked: false,
        submissionStatus: "in_progress",
        awardedMarks: null,
        maximumMarks: null,
        questions: [],
      },
    },
  },
}

/**
 * The surface registry. Each entry owns its route, its file prefix, its states
 * and the stubbing those states need; everything else is the shared harness.
 */
const SURFACES = {
  "student-dashboard": {
    prefix: "overview",
    route: "/student",
    states: OVERVIEW_STATES,
    async stub(page, state) {
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
    },
  },

  "correct-paper": {
    prefix: "correct",
    route: "/student/correct",
    states: CORRECT_STATES,
    async stub(page, state) {
      await page.route("**/api/student/uploads", (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ paperId: "capture-paper-1" }),
        }),
      )
      await page.route("**/api/student/correct", async (route) => {
        const spec = state.correct ?? {}
        if (spec.hang) {
          // Held open for longer than the capture takes. This is what "marking
          // now" actually is from the client's side.
          await new Promise((r) => setTimeout(r, 30_000))
          return
        }
        if (spec.sse !== undefined) {
          await route.fulfill({
            status: 200,
            contentType: "text/event-stream",
            body: spec.sse,
          })
          return
        }
        await route.fulfill({
          status: spec.status ?? 200,
          contentType: "application/json",
          body: JSON.stringify(spec.body ?? {}),
        })
      })
    },
    async act(page, state) {
      if (!state.pickScan) return
      await page.setInputFiles("#scan-file", SCAN_FIXTURE)
      if (!state.mark) return
      await page.getByRole("button", { name: "Mark this paper" }).click()
      // Long enough for the upload stub to resolve and the stream to either
      // fail or be seen hanging. Short enough that the hanging state is still
      // hanging.
      await page.waitForTimeout(1_200)
    },
    /** The hanging state never settles, so a full-page shot would wait on it. */
    fullPage: (state) => !state.correct?.hang,
  },

  "paper-result": {
    prefix: "result",
    route: "/student/result/capture-paper-1",
    states: RESULT_STATES,
    async stub(page, state) {
      await page.route("**/api/student/result/**", async (route) => {
        const spec = state.result
        if (spec.delayMs) {
          await new Promise((r) => setTimeout(r, spec.delayMs))
          return
        }
        await route.fulfill({
          status: spec.status ?? 200,
          contentType: "application/json",
          body: JSON.stringify(spec.body ?? {}),
        })
      })
    },
    fullPage: (state) => !state.result?.delayMs,
  },

  /* ── P4.3, surface 3 ─────────────────────────────────────────────────── */

  "flashcard-decks": {
    prefix: "decks",
    route: "/student/flashcards/0625",
    states: DECKS_STATES,
    async stub(page, state) {
      await page.route("**/api/student/flashcards/due**", (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(state.due ?? NOTHING_DUE_FIXTURE),
        }),
      )
      await page.route("**/api/student/flashcards/decks**", async (route) => {
        if (state.delayMs) {
          await new Promise((r) => setTimeout(r, state.delayMs))
          return
        }
        await route.fulfill({
          status: state.status ?? 200,
          contentType: "application/json",
          body: JSON.stringify(state.decks ?? []),
        })
      })
    },
    fullPage: (state) => !state.delayMs,
  },

  "flashcard-review": {
    prefix: "review",
    route: "/student/flashcards/review/0625",
    states: REVIEW_STATES,
    async stub(page, state) {
      await page.route("**/api/student/flashcards/due**", (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(state.due),
        }),
      )
    },
    async act(page, state) {
      if (!state.reveal) return
      // The button, not the Space shortcut: clicking is the path every user
      // has, and the keyboard path sets the same state.
      await page.getByRole("button", { name: /Reveal answer/ }).click()
      await page.waitForTimeout(400)
    },
  },

  "study-plan-week": {
    prefix: "plan",
    route: "/student/plan/0625",
    states: PLAN_STATES,
    async stub(page, state) {
      await page.route("**/api/student/study-plan/**", (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(state.plan),
        }),
      )
    },
  },

  "practice-result": {
    prefix: "practice-result",
    route: "/student/practice/result/assign-1",
    states: PRACTICE_RESULT_STATES,
    async stub(page, state) {
      await page.route("**/api/student/practice/**/result", (route) =>
        route.fulfill({
          status: state.result.status ?? 200,
          contentType: "application/json",
          body: JSON.stringify(state.result.body),
        }),
      )
    },
  },
}

const surface = SURFACES[surfaceName]
if (!surface) {
  console.error(
    `unknown surface "${surfaceName}". Known: ${Object.keys(SURFACES).join(", ")}`,
  )
  process.exit(2)
}
const STATES = surface.states
const outDir = path.resolve(
  process.argv[3] ?? path.join(repoRoot, "reports", "redesign", `p4-${surfaceName}`),
)

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
        await surface.stub(page, state)
        await page.goto(`${BASE}${surface.route}`, { waitUntil: "domcontentloaded" })
        // The screen's own entry animation is 320ms (`--dur-base`); settle past
        // it so a capture never catches a half-faded page.
        await page.waitForTimeout(state.delayMs ? 900 : 1400)

        // Surfaces whose states are reached by doing something rather than by
        // answering a request differently (picking a file, pressing the
        // primary action) put that here.
        if (surface.act) await surface.act(page, state)

        const file = path.join(outDir, `${surface.prefix}--${stateName}--${vp.name}.png`)
        await page.screenshot({
          path: file,
          fullPage: surface.fullPage ? surface.fullPage(state) : !state.delayMs,
        })
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
      const file = path.join(outDir, `${surface.prefix}--${stateName}--${vp.name}.png`)
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
  console.log(
    `\n${surfaceName}: ${VIEWPORTS.length * Object.keys(STATES).length} captures, all distinct`,
  )

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
