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
import { assertPortFree } from "./serve_guard.mjs"

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.resolve(__dirname, "..", "..")

/*
 * P6.1 made this file importable as well as runnable. `scripts/adapt_audit.mjs`
 * needs the same 35-surface registry, the same stubs and the same identities,
 * and the one thing this build has learned repeatedly is that a second
 * hand-maintained list is a list that drifts (P4.10: "a screen no surface
 * claims is a screen no gate reads"). So the adapt gate imports `SURFACES`
 * from here rather than restating it.
 *
 * Everything below the registry is CLI-only and runs behind `isMain`. Without
 * that guard, importing this module would start a capture round.
 */
const isMain = path.resolve(process.argv[1] ?? "") === fileURLToPath(import.meta.url)
const surfaceName = (isMain && process.argv[2]) || "student-dashboard"
/*
 * EXPORTED, and P6.5 is why.
 *
 * Six of the `act` callbacks in the registry below navigate by absolute URL
 * (`page.goto(`${BASE}/landing`)`) rather than by path, because they check
 * routing itself: that `/` renders the landing page for a signed-out visitor,
 * and that both 404 surfaces answer on their own path. An absolute URL needs a
 * host, and the host was written here as a private constant.
 *
 * `adapt_audit.mjs` imports this registry ("imported, never restated", its own
 * header) and then served `dist/` on **4321** while these callbacks kept
 * navigating to **4319**. The result is not a wrong measurement, it is worse:
 * the goto fails with `ERR_CONNECTION_REFUSED` and the whole run dies at the
 * eighth surface of thirty-five, so twenty-seven surfaces were never measured
 * at any width. The one way it does not die is if *something else* happens to
 * be listening on 4319, which is when a stranger's server answers a question
 * about our build (BLOCKERS.md B4, in a second place).
 *
 * So the port is now defined once and imported, which is the same rule the
 * registry itself already followed. D6.7's question, asked of a third file:
 * what re-states a value, and what checks that the two still agree?
 */
export const PORT = 4319
export const BASE = `http://127.0.0.1:${PORT}`

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

/**
 * Field-for-field `OverviewDTO`. Numbers are invented for the capture.
 *
 * This function used to carry its own copy of the momentum coordinate
 * transform — the third copy, after `lemely/web/routers/student.py` and
 * `portals/student/data.ts` — because the DTO shipped pre-rendered SVG path
 * data and a stub had to render one to produce a chart. P5.3 moved the
 * geometry into the chart component, so a stub now supplies what the wire
 * actually carries: percentages and timestamps.
 *
 * The `< 2` rule is the backend's and is reproduced deliberately, because it
 * is what the panel's empty state keys off: fewer than two grade-bearing
 * papers means no points at all, not one lonely point.
 */
function overview({ subjects, momentumPoints, weak }) {
  return {
    studentName: "Amina",
    forecast: subjects.map((s) => s.grade).join(" "),
    subjects,
    weakGlobal: weak,
    momentum: {
      points:
        momentumPoints.length < 2
          ? []
          : momentumPoints.map((percentage, i) => ({
              // One a month, ascending, so the tooltip dates read plausibly
              // and no two points share a timestamp.
              recordedAt: `2026-0${i + 1}-14T10:00:00+00:00`,
              percentage,
            })),
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
  /*
   * P6.2, the two states a reader reaches without doing anything: a run that was
   * already going when the page loaded. Neither is reachable by acting on this
   * screen, which is the point — they are what a reload, a backgrounded tab, or
   * a dropped signal leaves behind, and before P6.2 the screen had no idea any
   * of it had happened.
   *
   * Note what `recovered` must NOT show: the three-stage panel. The SSE frames
   * go to a process-global bus with no replay, so this reader knows the run is
   * going and nothing else, and ticking stages off from a status word would be
   * the invented progress S-14 rules out by name. The capture is the evidence
   * for that, since it is a claim about what is on screen.
   */
  recovered: { activeRun: { status: "processing", stale: false } },
  /** The same run, old enough that nobody is going to finish it. */
  "recovered-stale": { activeRun: { status: "processing", stale: true } },
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

/* ── P4.4, surface 4: gamification ─────────────────────────────────────── */

/*
 * `XpProfile`, `Leaderboard`, `FriendsPage` and `StandingsDTO`, field for
 * field. Every number here is invented for the capture and none of it is
 * product data — same rule as the overview fixture above.
 *
 * `XP_FIXTURE` is also stubbed on the two surfaces that do not display it,
 * because P4.4 put the streak pill in the student header, so `/api/student/xp`
 * is now fetched above every student route. Leaving it to the catch-all's `{}`
 * would render those captures without the pill and hide a component that is
 * genuinely on screen.
 */
const XP_FIXTURE = {
  totalXp: 4820,
  level: 7,
  levelStartXp: 4500,
  nextLevelXp: 5400,
  streak: { current: 21, longest: 34, lastActiveOn: "2026-08-12", freezesAvailable: 2 },
  week: {
    start: "2026-08-10",
    end: "2026-08-16",
    total: 410,
    bySource: [
      { source: "paper_corrected", xp: 180 },
      { source: "quiz_completed", xp: 90 },
      { source: "flashcard_reviewed", xp: 85 },
      { source: "study_session_completed", xp: 55 },
    ],
  },
  calendar: [
    { day: "2026-07-20", xp: 40 }, { day: "2026-07-22", xp: 120 },
    { day: "2026-07-23", xp: 65 }, { day: "2026-07-26", xp: 150 },
    { day: "2026-07-29", xp: 30 }, { day: "2026-08-01", xp: 95 },
    { day: "2026-08-03", xp: 140 }, { day: "2026-08-05", xp: 60 },
    { day: "2026-08-08", xp: 110 }, { day: "2026-08-10", xp: 75 },
    { day: "2026-08-11", xp: 180 }, { day: "2026-08-12", xp: 155 },
  ],
  calendarStart: "2026-07-16",
  calendarEnd: "2026-08-12",
}

/** A streak below the first milestone, so the sticker's absence is captured. */
const XP_NO_MILESTONE = {
  ...XP_FIXTURE,
  totalXp: 90,
  level: 1,
  levelStartXp: 0,
  nextLevelXp: 250,
  streak: { current: 2, longest: 2, lastActiveOn: "2026-08-12", freezesAvailable: 0 },
  week: {
    start: "2026-08-10",
    end: "2026-08-16",
    total: 90,
    bySource: [
      { source: "paper_corrected", xp: 90 },
      { source: "quiz_completed", xp: 0 },
      { source: "flashcard_reviewed", xp: 0 },
      { source: "study_session_completed", xp: 0 },
    ],
  },
  calendar: [{ day: "2026-08-12", xp: 90 }],
}

const STUDENT_PROFILE_FIXTURE = {
  profile: { leaderboardOptOut: false },
  enrolments: [{ subjectCode: "0625" }, { subjectCode: "0580" }],
}

const SUBJECT_RANKS_FIXTURE = {
  streakDays: 21,
  subjectRanks: [
    { code: "0625", name: "Physics", papers: 9, rank: 3, color: "lilac" },
    { code: "0580", name: "Mathematics", papers: 12, rank: 1, color: "sky" },
  ],
}

function boardRow(userId, displayName, xp, rank, streak) {
  return { userId, displayName, xp, rank, streak }
}

const BOARD_POPULATED = {
  status: "ok",
  unavailableReason: null,
  weekStart: "2026-08-10",
  weekEnd: "2026-08-16",
  rows: [
    boardRow("u1", "Nour El-Sayed", 640, 1, 31),
    boardRow("u2", "Yusuf Kamal", 585, 2, 12),
    boardRow("u3", "Habiba Adel", 520, 3, null),
    boardRow("u4", "Omar Tarek", 470, 4, 0),
    boardRow("u5", "Salma Ragab", 415, 5, 8),
  ],
  // Outside the top five, so the pinned row renders — the "where am I"
  // affordance this screen is built around.
  viewer: { userId: "capture-student", displayName: "Amina Farouk", xp: 410, rank: 9, streak: 21 },
  viewerOptedOut: false,
}

const BOARD_EMPTY = {
  ...BOARD_POPULATED,
  rows: [],
  viewer: { userId: "capture-student", displayName: "Amina Farouk", xp: 0, rank: null, streak: 21 },
}

const BOARD_UNAVAILABLE = {
  status: "unavailable",
  unavailableReason: "no_school",
  weekStart: "2026-08-10",
  weekEnd: "2026-08-16",
  rows: [],
  viewer: null,
  viewerOptedOut: false,
}

const STANDINGS_STATES = {
  populated: { board: BOARD_POPULATED },
  empty: { board: BOARD_EMPTY },
  "no-school": { board: BOARD_UNAVAILABLE },
  "opted-out": {
    board: {
      ...BOARD_POPULATED,
      viewerOptedOut: true,
      viewer: { userId: "capture-student", displayName: "Amina Farouk", xp: 410, rank: null, streak: 21 },
    },
    profile: { ...STUDENT_PROFILE_FIXTURE, profile: { leaderboardOptOut: true } },
  },
  loading: { delayMs: 30_000 },
  error: { status: 503, board: { detail: "unavailable" } },
}

const FRIENDS_PAGE = {
  friendCode: "K7P4RQ29",
  friends: [
    { friendshipId: "f1", displayName: "Nour El-Sayed", xp: 640, streak: 31, optedOut: false, friendsSince: "2026-03-04T10:00:00Z" },
    { friendshipId: "f2", displayName: "Yusuf Kamal", xp: 585, streak: 12, optedOut: false, friendsSince: "2026-05-19T10:00:00Z" },
    { friendshipId: "f3", displayName: "Habiba Adel", xp: null, streak: null, optedOut: true, friendsSince: "2026-06-30T10:00:00Z" },
  ],
  incoming: [{ friendshipId: "r1", displayName: "Omar Tarek", status: "pending" }],
  outgoing: [{ friendshipId: "r2", displayName: "Salma Ragab", status: "pending" }],
}

const FRIENDS_STATES = {
  populated: { page: FRIENDS_PAGE },
  empty: { page: { friendCode: "K7P4RQ29", friends: [], incoming: [], outgoing: [] } },
  "send-refused": {
    page: { friendCode: "K7P4RQ29", friends: [], incoming: [], outgoing: [] },
    sendBadCode: true,
  },
  loading: { delayMs: 30_000 },
  error: { status: 503, page: { detail: "unavailable" } },
}

const PROFILE_STATES = {
  populated: { xp: XP_FIXTURE },
  "below-first-milestone": { xp: XP_NO_MILESTONE },
  loading: { delayMs: 30_000 },
  error: { status: 503, xp: { detail: "unavailable" } },
}


/* ── Surface 10 fixtures (P4.10: 404 / misc, settings, the unclaimed screens) ─ */

const DEVICES_FIXTURE = {
  maxDevices: 3,
  devices: [
    {
      deviceId: "capture-device",
      label: null,
      userAgent:
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
      lastActiveAt: "2026-08-14T01:40:00Z",
      isCurrent: true,
    },
    {
      deviceId: "dev-2",
      label: null,
      userAgent:
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
      lastActiveAt: "2026-08-13T18:00:00Z",
      isCurrent: false,
    },
    {
      deviceId: "dev-3",
      label: null,
      userAgent: null,
      lastActiveAt: "2026-08-11T09:12:00Z",
      isCurrent: false,
    },
  ],
}

const DEVICES_STATES = {
  populated: { devices: DEVICES_FIXTURE },
  empty: { devices: { maxDevices: 3, devices: [] } },
  loading: { delayMs: 30_000 },
  error: { status: 503, devices: { detail: "unavailable" } },
  // The surface's headline finding, photographed: a 200 that removed nothing.
  // Before P4.10 this state was indistinguishable from a successful sign-out,
  // because the screen rendered neither.
  "already-gone": { devices: DEVICES_FIXTURE, revoke: { removed: false }, signOutRow: 1 },
  // The one confirmation on the screen, and only for the current device.
  "confirm-current": { devices: DEVICES_FIXTURE, signOutRow: 0, stopAtConfirm: true },
}

const PREFS_FIXTURE = {
  gradeReady: true,
  announcement: true,
  streakWarning: false,
  studyPlanReminder: false,
  atRiskAlert: null,
  quietHoursStart: "21:00",
  quietHoursEnd: "07:00",
}

const NOTIFICATION_PREF_STATES = {
  populated: { prefs: PREFS_FIXTURE },
  loading: { delayMs: 30_000 },
  error: { status: 503, prefs: { detail: "unavailable" } },
  // A failed toggle has to name the preference it failed on. Before P4.10 the
  // message rendered under the whole list.
  "save-failed": { prefs: PREFS_FIXTURE, saveStatus: 422, toggleRow: 0 },
}

/*
 * The teacher portal's 404 is a SEPARATE surface, not a state here: the
 * harness switches identity per surface (P4.5), so a `session` on a state
 * object is silently ignored — which is exactly what happened on the first
 * run of this round, and the in-harness assertion caught it rather than
 * quietly photographing a redirect.
 */
const NOT_FOUND_TEACHER_STATES = {
  "in-portal": { route: "/teacher/nonsense-path", expectSidebar: true },
}

const NOT_FOUND_STATES = {
  // Outside every portal: the full-screen frame, its own skip link and main.
  "top-level": { route: "/nonsense-path" },
  // Inside the student portal: the sidebar, header and trail all survive.
  // This is the state that did not exist before P4.10 — the path fell through
  // to the top-level catch-all and the reader lost the app around them.
  "in-portal": { route: "/student/nonsense-path", expectSidebar: true },
}

const ONBOARDING_PROFILE_FIXTURE = {
  profile: {
    qualificationLevel: null,
    schoolName: null,
    hasExternalLessons: null,
    weeklyStudyHours: null,
    gradeLevel: null,
  },
  enrolments: [],
}

const ONBOARDING_STATES = {
  subjects: { profile: ONBOARDING_PROFILE_FIXTURE },
  "subject-expanded": { profile: ONBOARDING_PROFILE_FIXTURE, pickSubject: true },
}

const SUBJECT_FIXTURE = {
  header: {
    meta: "0625 · Physics · June 2027",
    title: "Physics",
    intro: "9 papers corrected.",
    forecast: "B",
    weightedMean: "68",
    weightedMeanDelta: "+7 since first paper",
  },
  papersBreakdown: [
    {
      title: "Paper 2",
      sub: "Multiple choice",
      mean: "74%",
      positionOk: true,
      boundary: "62 for a B",
      position: "8 marks clear",
      bars: [
        { label: "s23", value: 62, highlight: false },
        { label: "w23", value: 71, highlight: false },
        { label: "s24", value: 78, highlight: true },
      ],
    },
    {
      title: "Paper 4",
      sub: "Theory, method marks",
      mean: "61%",
      positionOk: false,
      boundary: "66 for a B",
      position: "5 marks short",
      bars: [
        { label: "s23", value: 55, highlight: false },
        { label: "w23", value: 58, highlight: false },
        { label: "s24", value: 61, highlight: true },
      ],
    },
  ],
  topicMap: [
    { name: "Forces and motion", acc: "81%", color: "ok", weak: false },
    { name: "Thermal physics", acc: "44%", color: "accent", weak: true },
    { name: "Waves", acc: "67%", color: "warn", weak: false },
    { name: "Electricity", acc: "72%", color: "ok", weak: false },
  ],
  paperHistory: [
    { id: "p1", paper: "0625/42 s24", note: "Theory", marks: "49/80", pct: "61%", grade: "C", gradeColor: "warn" },
    { id: "p2", paper: "0625/22 s24", note: "Multiple choice", marks: "31/40", pct: "78%", grade: "B", gradeColor: "ok" },
  ],
}

const SUBJECT_STATES = {
  populated: { subject: SUBJECT_FIXTURE },
  // A 404 is a subject with no corrected papers yet, which is every subject on
  // a new account. It gets the empty state, not the error state.
  "nothing-yet": { status: 404, subject: { detail: "no papers" } },
  loading: { delayMs: 30_000 },
  error: { status: 503, subject: { detail: "unavailable" } },
}

/**
 * Shared by both 404 surfaces: navigate to the state's own path, then assert
 * the DOM shape no screenshot can distinguish. See the note inside.
 */
async function notFoundAct(page, state) {
    await page.goto(`${BASE}${state.route}`, { waitUntil: "domcontentloaded" })
    await page.waitForTimeout(900)

    /*
     * The assertion no image can make, and the surface's whole point.
     *
     * A portal 404 has to keep the portal around it, and a top-level one has
     * to render its own frame. Both look like a reasonable 404 in a
     * screenshot; only the DOM says which subtree answered. `<main>` count is
     * the load-bearing half — the split between `NotFound` and
     * `PortalNotFound` exists precisely so a portal 404 does not end up with
     * two `<main>` landmarks and two elements carrying MAIN_CONTENT_ID.
     */
    const shape = await page.evaluate(() => ({
      mains: document.querySelectorAll("main").length,
      navs: document.querySelectorAll("nav").length,
      h1: document.querySelector("h1")?.textContent ?? null,
    }))
    if (shape.mains !== 1) {
      throw new Error(`expected exactly one <main>, found ${shape.mains} at ${state.route}`)
    }
    if (state.expectSidebar && shape.navs === 0) {
      throw new Error(`a 404 inside a portal lost its navigation at ${state.route}`)
    }
    if (!state.expectSidebar && shape.navs > 0) {
      throw new Error(`a top-level 404 rendered portal navigation at ${state.route}`)
    }
    if (!shape.h1 || !shape.h1.includes("find that page")) {
      throw new Error(`404 heading was ${JSON.stringify(shape.h1)} at ${state.route}`)
    }
    console.log(`verified: ${state.route} -> 1 main, ${shape.navs} nav(s), correct heading`)
}

/**
 * The surface registry. Each entry owns its route, its file prefix, its states
 * and the stubbing those states need; everything else is the shared harness.
 */

/* ── Teacher fixtures (P4.5, surface 5) ──────────────────────────────────── */

/*
 * The teacher identity. `RequireAuth` gates `/teacher` to teacher/school_admin/
 * platform_admin, so without this every teacher capture would be a redirect to
 * the student dashboard.
 */
const TEACHER_SESSION = { userId: "capture-teacher", role: "teacher" }
const TEACHER_PROFILE = {
  userId: "capture-teacher",
  email: "h.sabry@example.com",
  displayName: "Hana Sabry",
  role: "teacher",
}

/** Field-for-field `StatCardDTO`. Invented numbers, real shape. */
const TEACHER_STATS = [
  { key: "Papers graded", value: "128", unit: "this term", foot: null, valueTone: "t1", footTone: "t2" },
  { key: "Need your eyes", value: "6", unit: "items", foot: "oldest waiting 2 days", valueTone: "err", footTone: "err" },
  { key: "Group mean", value: "64", unit: "%", foot: "up 3 since last paper", valueTone: "t1", footTone: "ok" },
  { key: "At risk", value: "2", unit: "students", foot: null, valueTone: "err", footTone: "t2" },
]

const TEACHER_AT_RISK = [
  {
    name: "Yusuf Rahman",
    grade: "D",
    delta: -7,
    weakTopic: "Thermal physics",
    flags: [
      {
        reason: "declining_trend",
        summary: "Down 7 marks across the last three papers, all in thermal physics.",
        evidence: {},
        acknowledged: null,
      },
    ],
  },
  {
    name: "Mariam Adel",
    grade: "E",
    delta: -3,
    weakTopic: "Electricity",
    flags: [
      {
        reason: "below_target",
        summary: "Two grades below the A she is aiming for in physics.",
        evidence: {},
        acknowledged: { acknowledgedAt: "2026-08-12T09:00:00Z", acknowledgedBy: "capture-teacher", note: "Spoke to her on Tuesday." },
      },
      { reason: "inactive", summary: "No submissions in 16 days.", evidence: {}, acknowledged: null },
    ],
  },
]

const TEACHER_ACTIVITY = [
  { studentId: "s1", studentName: "Amina Farouk", subjectCode: "0625", percentage: 78, grade: "B", recordedAt: "2026-08-13T14:10:00Z", origin: "past_paper" },
  { studentId: "s2", studentName: "Yusuf Rahman", subjectCode: "0625", percentage: 41, grade: null, recordedAt: "2026-08-13T11:02:00Z", origin: "quiz" },
  { studentId: "s3", studentName: "Mariam Adel", subjectCode: "0580", percentage: 55, grade: "D", recordedAt: "2026-08-12T16:40:00Z", origin: "past_paper" },
]

const TEACHER_CLASSES = {
  classes: [
    { id: "c1", label: "Y11 Physics A", studentCount: 24, average: 64.2, subjectCode: "0625", schoolId: null, joinCode: "PHY11A", atRiskCount: 2, lastActivityAt: "2026-08-13T14:10:00Z", topWeakness: "Thermal physics" },
    { id: "c2", label: "Y11 Physics B", studentCount: 22, average: 58.9, subjectCode: "0625", schoolId: null, joinCode: "PHY11B", atRiskCount: 1, lastActivityAt: "2026-08-11T09:30:00Z", topWeakness: "Electricity" },
    { id: "c3", label: "Y10 Maths", studentCount: 28, average: null, subjectCode: "0580", schoolId: null, joinCode: "MTH10", atRiskCount: 0, lastActivityAt: null, topWeakness: null },
  ],
}

const TEACHER_OVERVIEW = {
  stats: TEACHER_STATS,
  atRisk: TEACHER_AT_RISK,
  retention: [],
  recentActivity: TEACHER_ACTIVITY,
}

/*
 * The first-run state is BOTH conditions, not just one: `Overview.tsx` shows
 * `GettingStarted` only when there are no classes AND no activity, because a
 * teacher who archived their last class mid-year should get their dashboard
 * back rather than an onboarding screen.
 */
const TEACHER_OVERVIEW_FIRST_RUN = { stats: TEACHER_STATS, atRisk: [], retention: [], recentActivity: [] }

const TEACHER_OVERVIEW_STATES = {
  /** The populated dashboard: at-risk students, four stats, three classes. */
  populated: { overview: TEACHER_OVERVIEW, classes: TEACHER_CLASSES },
  /** Nothing flagged. The "no students flagged" line, and the zeroed stats. */
  nothingFlagged: {
    overview: { ...TEACHER_OVERVIEW, atRisk: [], stats: TEACHER_STATS.map((s) => (s.key === "Need your eyes" ? { ...s, value: "0", foot: null, valueTone: "t1", footTone: "t2" } : s)) },
    classes: TEACHER_CLASSES,
  },
  /** A genuinely new account: the composed first-run view, not a wall of zeroes. */
  firstRun: { overview: TEACHER_OVERVIEW_FIRST_RUN, classes: { classes: [] } },
  /** The skeleton. Never fulfilled; the context is torn down first. */
  loading: { delayMs: 8_000 },
  /** The error state, with its own sentence rather than a raw message. */
  error: { overview: null, status: 500, classes: TEACHER_CLASSES },
}

const REVIEW_ITEMS = [
  { itemId: "r1", attemptId: "a1", questionResultId: "q1", studentId: "s1", studentDisplayName: "Amina Farouk", classId: "c1", className: "Y11 Physics A", subjectCode: "0625", paperNumber: 4, paperVariant: 1, sessionMonth: "Nov", sessionYear: 2024, questionId: "3(b)(ii)", reason: "low_confidence", status: "open", createdAt: "2026-08-11T08:00:00Z", waitingHours: 52, aiAwardedMarks: 2, maximumMarks: 3, confidenceScore: 0.62 },
  /* 0.85: below the 0.90 review floor that put it here, and above the 0.8 the
     queue used to call confident. This row is the capture of the chunk-D
     finding. */
  { itemId: "r2", attemptId: "a2", questionResultId: "q2", studentId: "s2", studentDisplayName: "Yusuf Rahman", classId: "c1", className: "Y11 Physics A", subjectCode: "0625", paperNumber: 4, paperVariant: 1, sessionMonth: "Nov", sessionYear: 2024, questionId: "5(a)", reason: "low_confidence", status: "open", createdAt: "2026-08-12T10:30:00Z", waitingHours: 26, aiAwardedMarks: 1, maximumMarks: 2, confidenceScore: 0.85 },
  { itemId: "r3", attemptId: "a3", questionResultId: null, studentId: "s3", studentDisplayName: "Mariam Adel", classId: "c2", className: "Y11 Physics B", subjectCode: null, paperNumber: null, paperVariant: null, sessionMonth: null, sessionYear: null, questionId: "2", reason: "ai_detection_flag", status: "open", createdAt: "2026-08-13T07:15:00Z", waitingHours: 5, aiAwardedMarks: null, maximumMarks: null, confidenceScore: null },
]

/*
 * P6.2's long-content pass, and it is aimed at a specific change rather than at
 * "long strings generally".
 *
 * §6.2 asks for a long-content pass, and the adapt gate does not give one: its
 * `badWrap` rule checks that display headers *carry* `overflow-wrap`, which is
 * a statement about CSS, not about what a long string does to a layout. Nothing
 * in the capture corpus had ever rendered one.
 *
 * This row is the one most likely to break, because P6.1 moved its `truncate`.
 * The student link went from `block truncate` to a flex row with `min-h-11`,
 * and on a flex container the text is an anonymous flex item that
 * `text-overflow` has nothing to apply to — so the ellipsis was re-homed onto
 * an inner span. A name long enough to need it is the only thing that can show
 * whether that landed, and a name is user-supplied data: "Amina Farouk" proves
 * nothing.
 */
const LONG_NAME_ITEM = {
  ...REVIEW_ITEMS[0],
  itemId: "r-long",
  studentDisplayName: "Abdurrahman Muhammad Al-Sayyid Abdel-Rahman Ibrahim El-Masry",
  className: "Y11 Physics Set A (upper), Thursday double period, Mr Okonkwo",
}

const TEACHER_REVIEW_STATES = {
  /** The queue with all three reason kinds, oldest first. */
  populated: { queue: { items: REVIEW_ITEMS } },
  /** Empty, which on this screen is good news and must read as such. */
  empty: { queue: { items: [] } },
  /** A name and a class name far past the column they sit in. */
  "long-content": { queue: { items: [LONG_NAME_ITEM, ...REVIEW_ITEMS.slice(1)] } },
  loading: { delayMs: 8_000 },
  error: { queue: null, status: 500 },
}

const TEACHER_QUIZZES = {
  quizzes: [
    { id: "q1", title: "Y11 Thermal physics catch-up", subjectCode: "0625", status: "draft", questionCount: 0, targetGrade: "C", builderStep: 3 },
    { id: "q2", title: "Electricity end-of-unit", subjectCode: "0625", status: "assigned", questionCount: 12, targetGrade: "B", builderStep: 6 },
    { id: "q3", title: "Forces recap", subjectCode: "0625", status: "closed", questionCount: 8, targetGrade: null, builderStep: 6 },
  ],
}

/* ── Class analytics + student detail (P5.3's two chart screens) ──────────── */

const CLASS_STUDENT_IDS = ["s-amina", "s-omar", "s-hana", "s-yusuf"]

/** `ClassDetailDTO`. Only the roster is read by the analytics tab, via context. */
const CLASS_DETAIL = {
  id: "c-y11-physics",
  label: "Y11 Physics",
  subjectCode: "0625",
  schoolId: "sch-1",
  joinCode: "PHY-2K4",
  atRiskCount: 1,
  lastActivityAt: "2026-08-11T09:20:00+00:00",
  topWeakness: "Moments and equilibrium",
  stats: [],
  mastery: [],
  distribution: [],
  students: [
    { name: "Amina Farouk", grade: "B", mark: "72%", delta: 4, weakTopic: "Moments and equilibrium", gradeAtRisk: false, studentId: "s-amina", paperCount: 4, lastActiveAt: "2026-08-11T09:20:00+00:00", flags: [] },
    { name: "Omar Said", grade: "C", mark: "64%", delta: -3, weakTopic: "Thermal energy transfer", gradeAtRisk: false, studentId: "s-omar", paperCount: 3, lastActiveAt: "2026-08-09T14:02:00+00:00", flags: [] },
    { name: "Hana Nabil", grade: "A", mark: "88%", delta: 2, weakTopic: null, gradeAtRisk: false, studentId: "s-hana", paperCount: 5, lastActiveAt: "2026-08-12T11:40:00+00:00", flags: [] },
    { name: "Yusuf Adel", grade: "E", mark: "44%", delta: -9, weakTopic: "Kinematics graphs", gradeAtRisk: true, studentId: "s-yusuf", paperCount: 2, lastActiveAt: "2026-07-28T08:10:00+00:00", flags: [] },
  ],
}

/**
 * Every rung of the grade ladder, zero counts included — which is what the real
 * `grade_distribution` returns, and the reason the panel's empty test is "every
 * count is zero" rather than "no rows". A fixture that shipped only the
 * non-zero grades would quietly make that bug untestable.
 */
// Mirrors `lemely.core.history.GRADE_ORDER` exactly, highest first. Seven
// rungs, not the nine an IGCSE grade sheet might suggest: this product's ladder
// has no F or G. A fixture that invents rungs the wire never sends is a fixture
// that can be wrong and look like a bug.
const GRADE_LADDER = ["A*", "A", "B", "C", "D", "E", "U"]
const gradeBuckets = (counts) =>
  GRADE_LADDER.map((grade) => ({ grade, count: counts[grade] ?? 0 }))

/** `ClassAnalyticsDTO`. Numbers are invented for the capture. */
const CLASS_ANALYTICS = {
  topicWeaknesses: [
    { topic: "Moments and equilibrium", lostMarks: 46, maximumMarks: 78, accuracy: 0.41, studentIds: CLASS_STUDENT_IDS },
    { topic: "Kinematics graphs", lostMarks: 31, maximumMarks: 72, accuracy: 0.57, studentIds: ["s-omar", "s-yusuf"] },
    { topic: "Thermal energy transfer", lostMarks: 22, maximumMarks: 64, accuracy: 0.66, studentIds: ["s-omar"] },
  ],
  heatmap: [
    { topic: "Moments and equilibrium", studentId: "s-amina", accuracy: 0.52 },
    { topic: "Moments and equilibrium", studentId: "s-omar", accuracy: 0.38 },
    { topic: "Moments and equilibrium", studentId: "s-hana", accuracy: 0.81 },
    { topic: "Moments and equilibrium", studentId: "s-yusuf", accuracy: 0.0 },
    { topic: "Kinematics graphs", studentId: "s-amina", accuracy: 0.74 },
    { topic: "Kinematics graphs", studentId: "s-omar", accuracy: 0.49 },
    // Deliberately absent for `s-hana`, so the no-data cell (an en-dash, not a
    // 0%) appears in at least one capture. The two must never look alike.
    { topic: "Kinematics graphs", studentId: "s-yusuf", accuracy: null },
    { topic: "Thermal energy transfer", studentId: "s-amina", accuracy: 0.69 },
    { topic: "Thermal energy transfer", studentId: "s-omar", accuracy: 0.55 },
    { topic: "Thermal energy transfer", studentId: "s-hana", accuracy: 0.9 },
    { topic: "Thermal energy transfer", studentId: "s-yusuf", accuracy: 0.42 },
  ],
  gradeDistribution: gradeBuckets({ A: 1, B: 1, C: 1, E: 1 }),
  trend: [
    { timestamp: "2026-05-14T10:00:00+00:00", label: "2026-05-14T10:00:00+00:00", meanPercentage: 58.5, sampleSize: 2 },
    { timestamp: "2026-06-02T10:00:00+00:00", label: "2026-06-02T10:00:00+00:00", meanPercentage: 63.25, sampleSize: 3 },
    { timestamp: "2026-06-24T10:00:00+00:00", label: "2026-06-24T10:00:00+00:00", meanPercentage: 61.0, sampleSize: 4 },
    { timestamp: "2026-07-19T10:00:00+00:00", label: "2026-07-19T10:00:00+00:00", meanPercentage: 66.75, sampleSize: 4 },
    { timestamp: "2026-08-11T10:00:00+00:00", label: "2026-08-11T10:00:00+00:00", meanPercentage: 67.0, sampleSize: 4 },
  ],
  paperComparison: [
    { paperId: "0625-2-2", subjectCode: "0625", paperNumber: 2, paperVariant: 2, meanPercentage: 64.5, attemptCount: 6, studentCount: 4 },
    { paperId: "0625-4-1", subjectCode: "0625", paperNumber: 4, paperVariant: 1, meanPercentage: 58.0, attemptCount: 4, studentCount: 3 },
  ],
  engagement: {
    submissionsLast7Days: 5,
    submissionsLast30Days: 14,
    activeStudentsLast7Days: 3,
    activeStudentsLast30Days: 4,
    neverActiveCount: 0,
    medianDaysSinceLastSubmission: 3,
  },
}

const TEACHER_ANALYTICS_STATES = {
  /** Both charts with real series behind them. */
  populated: { analytics: CLASS_ANALYTICS },
  /**
   * A class that exists and has marked nothing. **This is the state P5.3 added
   * the grade panel's empty case for**: the ladder is still nine rows of zero,
   * so the old `length === 0` test never fired and the panel drew nine empty
   * tracks. The trend is genuinely `[]`, so the two empty states differ in
   * kind, and both have to read as "nothing yet" rather than as "broken".
   */
  "nothing-marked": {
    analytics: {
      ...CLASS_ANALYTICS,
      topicWeaknesses: [],
      heatmap: [],
      gradeDistribution: gradeBuckets({}),
      trend: [],
      paperComparison: [],
    },
  },
  /** One point, which a line cannot be drawn through but a chart must survive. */
  "one-point": {
    analytics: { ...CLASS_ANALYTICS, trend: CLASS_ANALYTICS.trend.slice(0, 1) },
  },
  loading: { delayMs: 8_000 },
  error: { analytics: null, status: 500 },
}

/** `StudentDetailDTO`. Numbers are invented for the capture. */
const STUDENT_DETAIL = {
  studentId: "s-yusuf",
  displayName: "Yusuf Adel",
  subjects: [
    { subjectCode: "0625", predictedGrade: "E", latestPercentage: 44.0, paperCount: 2 },
  ],
  attempts: [
    { paperId: "0625-4-1", subjectCode: "0625", paperNumber: 4, paperVariant: 1, awardedMarks: 35, maximumMarks: 80, percentage: 43.75, grade: "E", recordedAt: "2026-07-28T08:10:00+00:00" },
    { paperId: "0625-2-2", subjectCode: "0625", paperNumber: 2, paperVariant: 2, awardedMarks: 21, maximumMarks: 40, percentage: 52.5, grade: "D", recordedAt: "2026-06-15T09:00:00+00:00" },
  ],
  weaknesses: [
    { topic: "Kinematics graphs", lostMarks: 18, maximumMarks: 30, accuracy: 0.4, questionIds: ["q3", "q7"] },
    { topic: "Moments and equilibrium", lostMarks: 12, maximumMarks: 24, accuracy: 0.5, questionIds: ["q11"] },
  ],
  /*
   * Descending, and deliberately so: this is the at-risk trend, and the whole
   * question a teacher opens it to answer is whether the flag describes a slide
   * or one bad morning. A capture of a flat line would not exercise the panel's
   * actual job.
   */
  trend: [
    { recordedAt: "2026-06-15T09:00:00+00:00", percentage: 52.5 },
    { recordedAt: "2026-07-28T08:10:00+00:00", percentage: 43.75 },
  ],
  isAtRisk: true,
  atRiskFlags: [
    {
      reason: "declining_trend",
      summary: "Dropped from 53% to 44% across their last two papers.",
      evidence: { percentages: [52.5, 43.75], paperCount: 2 },
      acknowledged: null,
    },
  ],
  engagement: {
    totalPapers: 2,
    lastActiveAt: "2026-07-28T08:10:00+00:00",
    daysSinceLastSubmission: 17,
  },
}

const TEACHER_STUDENT_STATES = {
  populated: { student: STUDENT_DETAIL },
  /** A student on the roster who has never submitted: the empty trend. */
  "no-papers": {
    student: {
      ...STUDENT_DETAIL,
      subjects: [],
      attempts: [],
      weaknesses: [],
      trend: [],
      isAtRisk: false,
      atRiskFlags: [],
      engagement: { totalPapers: 0, lastActiveAt: null, daysSinceLastSubmission: null },
    },
  },
  loading: { delayMs: 8_000 },
  error: { student: null, status: 500 },
}

const TEACHER_QUIZZES_STATES = {
  populated: { quizzes: TEACHER_QUIZZES },
  /** The composed empty state, which is where a teacher starts. */
  empty: { quizzes: { quizzes: [] } },
  loading: { delayMs: 8_000 },
  error: { quizzes: null, status: 500 },
}

/* ── Parent (P4.6, surface 6) ──────────────────────────────────────────────
 *
 * Field-for-field `lemely/web/schemas_parent.py` (camelCase, as
 * `lib/parentTypes.ts` mirrors it). Every number and name here is invented for
 * the capture: these are not product data, they are never shipped, and no
 * claim in any report is derived from them.
 *
 * Two children, not one, on purpose. `screens/Children.tsx` redirects a
 * single-child parent straight past P-01, and both the header's child switcher
 * and the breadcrumb's "Your children" rung are conditional on there being a
 * list to go back to — so a one-child fixture would photograph three of this
 * surface's changes in their hidden state.
 */
const PARENT_SESSION = { userId: "capture-parent", role: "parent" }
const PARENT_PROFILE = {
  userId: "capture-parent",
  email: "n.farouk@example.com",
  displayName: "Nadia Farouk",
  role: "parent",
}

const PARENT_CHILDREN = {
  children: [
    {
      childId: "child-1",
      displayName: "Amina Farouk",
      classes: [{ name: "Physics 11B", subjectCode: "0625", schoolName: "Nile International" }],
      statusLine: "Working steadily. Physics is her strongest subject and her marks are holding.",
      trend: 4.2,
      lastActivityAt: "2026-08-12T18:20:00Z",
    },
    {
      childId: "child-2",
      displayName: "Omar Farouk",
      classes: [{ name: "Maths 10A", subjectCode: "0580", schoolName: null }],
      statusLine: "Nothing marked in the last three weeks, and his last two papers were lower.",
      trend: -6.8,
      lastActivityAt: null,
    },
  ],
}

const PARENT_WEAK_TOPICS = [
  { topic: "Thermal physics", lostMarks: 14, maximumMarks: 22, accuracy: 0.36 },
  { topic: "Moments and equilibrium", lostMarks: 9, maximumMarks: 18, accuracy: 0.5 },
  { topic: "Electromagnetic induction", lostMarks: 6, maximumMarks: 20, accuracy: 0.7 },
  { topic: "Waves", lostMarks: 3, maximumMarks: 16, accuracy: 0.81 },
]

const PARENT_OVERVIEW = {
  childId: "child-1",
  displayName: "Amina Farouk",
  activity: {
    totalPapers: 11,
    lastActiveAt: "2026-08-12T18:20:00Z",
    daysSinceLastActivity: 2,
  },
  atRiskFlags: [
    {
      reason: "declining_trend",
      summary: "Declining over the last 3 papers: 62% -> 55% -> 48% (14pp drop)",
      evidence: { percentages: [62, 55, 48] },
    },
  ],
  subjects: [
    {
      subjectCode: "0625",
      subjectName: "Physics",
      predictedGrade: "B",
      target: null,
      latestPercentage: 68.4,
      paperCount: 7,
      trend: [
        { recordedAt: "2026-05-02T10:00:00Z", percentage: 58 },
        { recordedAt: "2026-06-14T10:00:00Z", percentage: 64 },
        { recordedAt: "2026-08-01T10:00:00Z", percentage: 68 },
      ],
    },
    {
      subjectCode: "0580",
      subjectName: "Mathematics",
      predictedGrade: "C",
      target: null,
      latestPercentage: 54,
      paperCount: 4,
      trend: [
        { recordedAt: "2026-06-01T10:00:00Z", percentage: 61 },
        { recordedAt: "2026-07-20T10:00:00Z", percentage: 54 },
      ],
    },
  ],
  recentPapers: [
    {
      paperId: "0625/42",
      subjectCode: "0625",
      subjectName: "Physics",
      marks: "55 / 80",
      grade: "B",
      recordedAt: "2026-08-12T18:20:00Z",
    },
    {
      paperId: "0580/22",
      subjectCode: "0580",
      subjectName: "Mathematics",
      marks: "38 / 70",
      grade: "C",
      recordedAt: "2026-07-20T09:05:00Z",
    },
  ],
  weakTopics: PARENT_WEAK_TOPICS,
}

/** The same child before anything has been marked. Not a trimmed copy of the
 * populated fixture: the whole point is the empty branches, so every list is
 * genuinely empty and the nullable activity fields are null rather than 0. */
const PARENT_OVERVIEW_NEW = {
  childId: "child-1",
  displayName: "Amina Farouk",
  activity: { totalPapers: 0, lastActiveAt: null, daysSinceLastActivity: null },
  atRiskFlags: [],
  subjects: [],
  recentPapers: [],
  weakTopics: [],
}

const PARENT_SUBJECT = {
  childId: "child-1",
  subjectCode: "0625",
  subjectName: "Physics",
  predictedGrade: "B",
  papers: [
    { paperId: "0625/42", marks: "55 / 80", grade: "B", recordedAt: "2026-08-12T18:20:00Z" },
    { paperId: "0625/22", marks: "31 / 40", grade: "A", recordedAt: "2026-06-14T11:00:00Z" },
    { paperId: "0625/41", marks: "44 / 80", grade: "C", recordedAt: "2026-05-02T10:00:00Z" },
  ],
  boundaryDistance: {
    nextGrade: "A",
    marksNeeded: 6,
    summary: "On the June 2026 boundaries an A started at 61 of 80 on this paper.",
  },
  weakTopics: PARENT_WEAK_TOPICS.slice(0, 3),
}

/** Already on the top grade, so the backend computes no distance and the panel
 * is omitted rather than rendered as "0 marks from". */
const PARENT_SUBJECT_TOP = {
  ...PARENT_SUBJECT,
  predictedGrade: "A*",
  boundaryDistance: null,
  weakTopics: [],
}

const PARENT_WEAKNESSES = { childId: "child-1", weakTopics: PARENT_WEAK_TOPICS }
const PARENT_WEAKNESSES_EMPTY = { childId: "child-1", weakTopics: [] }

const PARENT_CHILDREN_STATES = {
  populated: { children: PARENT_CHILDREN },
  unlinked: { children: { children: [] } },
  loading: { delayMs: 8_000 },
  error: { status: 500, children: { detail: "Parent service unavailable." } },
}

const PARENT_OVERVIEW_STATES = {
  populated: { overview: PARENT_OVERVIEW },
  "nothing-marked": { overview: PARENT_OVERVIEW_NEW },
  loading: { delayMs: 8_000 },
  "not-linked": { status: 403, overview: { detail: "Child 6f2c is not linked to this parent" } },
}

const PARENT_SUBJECT_STATES = {
  populated: { subject: PARENT_SUBJECT },
  "top-grade": { subject: PARENT_SUBJECT_TOP },
  loading: { delayMs: 8_000 },
  error: { status: 500, subject: { detail: "Boundary store unavailable." } },
}

const PARENT_WEAKNESSES_STATES = {
  populated: { weaknesses: PARENT_WEAKNESSES },
  empty: { weaknesses: PARENT_WEAKNESSES_EMPTY },
  loading: { delayMs: 8_000 },
  error: { status: 500, weaknesses: { detail: "Weakness store unavailable." } },
}

/* ── Auth (P4.7, surface 8) ────────────────────────────────────────────────
 *
 * The signed-out surfaces are the one place the harness's session fixture must
 * NOT apply: `/login` with a live session in localStorage is a redirect, not a
 * screen. `session: null` on these entries clears it.
 *
 * Field-for-field `DeviceLimitChallenge` (`lib/deviceTypes.ts`). Invented
 * device names, real shape.
 */
const DEVICE_CHALLENGE = {
  /* `reason` is not decoration: `isDeviceLimitChallenge` narrows on it, and the
     first draft of this fixture omitted it, so the 409 fell through to the
     generic sign-in failure and the capture photographed the login form where
     the device notice should have been. The harness caught its own fixture,
     which is what a state that must differ is for. */
  reason: "device_limit_reached",
  maxDevices: 3,
  oldestDeviceId: "dev-oldest",
  devices: [
    {
      deviceId: "dev-oldest",
      label: null,
      isCurrent: false,
      userAgent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/141.0",
      lastActiveAt: "2026-06-02T08:30:00Z",
    },
    {
      deviceId: "dev-phone",
      label: null,
      isCurrent: true,
      userAgent: "Mozilla/5.0 (Linux; Android 14; SM-A546B) Chrome/141.0",
      lastActiveAt: "2026-08-13T21:10:00Z",
    },
    {
      deviceId: "dev-tablet",
      label: null,
      isCurrent: false,
      userAgent: "Mozilla/5.0 (iPad; CPU OS 18_2) Safari/605.1.15",
      lastActiveAt: "2026-08-11T17:45:00Z",
    },
  ],
}

const LOGIN_STATES = {
  empty: {},
  /* The two failure branches are reached by submitting, because that is the
   * only way a person reaches them either. */
  "bad-credentials": {
    submit: true,
    status: 401,
    body: { detail: "Invalid credentials" },
  },
  "device-limit": {
    submit: true,
    status: 409,
    body: { detail: DEVICE_CHALLENGE },
  },
  offline: {
    submit: true,
    abort: true,
  },
}

const PARENT_LOGIN_STATES = {
  phone: {},
  code: { sendCode: true, otp: { devCode: null } },
  "dev-code": { sendCode: true, otp: { devCode: "418209" } },
  /* The defect this surface fixed: the wire form is an enum member, and what
   * must appear on screen is a sentence. */
  "wrong-code": {
    sendCode: true,
    otp: { devCode: null },
    typeCode: "111111",
    verifyStatus: 401,
    verifyBody: { detail: "OTP verification failed: wrong_code" },
  },
}

/* ── Sign-up flows (issue #10, Task 23) ───────────────────────────────────
 *
 * All nine surfaces below are the nine public routes design spec §4.4 lists
 * (`/signup`, `/signup/student`, `/signup/teacher`, `/verify-email(/:token)`,
 * `/reset(/:token)`, `/join(/:code)`). Every one of them is signed-out by
 * construction except `verify-email-pending`, which needs a live-but-
 * unverified session to reach its real content (D8.4/D8.5) — see that
 * surface's own `session` field. States are kept to what actually renders
 * differently, matching this file's own established restraint (`landing`,
 * `not-found`) rather than manufacturing a fifth near-duplicate state per
 * screen.
 */

const SIGNUP_STUDENT_STATES = {
  empty: {},
  // `signUpFailureMessage` renders for any 400; a conflict body is the
  // realistic one (D8.1/D8.11's own anti-enumeration rule keeps the sentence
  // itself vague, so the body content here does not have to be exact).
  conflict: { submit: true, status: 400, body: { detail: "conflict" } },
}

const SIGNUP_TEACHER_STATES = {
  // One state: the only thing this variant needs to show that the student
  // one does not is the "this creates an independent account" banner
  // (D8.2), which is static copy with no request behind it.
  empty: {},
}

const VERIFY_EMAIL_PENDING_STATES = {
  idle: {},
  // The developer-only link panel (D8.6): what the screen shows with the
  // mock provider wired, which is every deployment of this build.
  devLink: { resend: true, devLink: "/verify-email/capture-dev-token" },
}

const VERIFY_EMAIL_CONFIRM_STATES = {
  verifying: { delayMs: 8_000 },
  invalid: { status: 400, body: { detail: "invalid or expired token" } },
}

const RESET_REQUEST_STATES = {
  empty: {},
  // D8.6's anti-enumeration UI rule: this is the SAME confirmation screen
  // regardless of whether the address exists, so one state stands in for
  // both — a second "unknown address" state would be visually identical by
  // design and the duplicate-hash check would (correctly) refuse it.
  sent: { submit: true, devLink: "/reset/capture-dev-token" },
}

const RESET_CONFIRM_STATES = {
  empty: {},
  // Requirement 2 (D8.7): the success screen states plainly that every
  // device was signed out.
  success: { submit: true },
}

const JOIN_CODE_ENTRY_STATES = {
  default: {},
}

// `describeInvitePreview`'s three fields, chosen to render the exact example
// UI spec §G-08 itself quotes ("Al-Nasr Language School — Mr Hassan's
// Physics 0625 class"), so this capture is checkable against the spec by eye.
const INVITE_PREVIEW_FIXTURE = {
  role: "student",
  schoolName: "Al-Nasr Language School",
  className: "Physics 0625",
  teacherName: "Mr Hassan",
}

const JOIN_CODE_PREVIEW_STATES = {
  populated: { preview: INVITE_PREVIEW_FIXTURE },
  // Both "invalid" and "expired" resolve to the same 404 panel (D8.3's own
  // `InviteService._find_live_invite` reasoning, quoted in
  // `useInvitesApi.ts`'s `previewErrorCopy`) — one state stands in for both,
  // same reasoning as `RESET_REQUEST_STATES.sent` above.
  notFound: { status: 404, body: { detail: "invite not found" } },
}

/*
 * A marketing page has no loading, empty or error branch to photograph, so
 * this surface's states are not request outcomes like every other one here.
 *
 * The first attempt made them scroll positions, and the duplicate detector
 * failed the round — correctly. Captures are `fullPage`, so scrolling changes
 * nothing about the image, and six "sections" were six copies of one picture.
 * That is precisely the "looks like evidence" failure the detector exists for,
 * and it caught it on the first run.
 *
 * What genuinely renders differently is: the whole page, the same page with
 * motion off, and the viewport-cropped top where the sticky header sits over
 * paper.
 *
 * `/` is deliberately NOT a state. It renders the same component as
 * `/landing`, so its capture would be byte-identical — which is the fix
 * working, and something the duplicate detector cannot distinguish from the
 * fix being broken. It is verified in `act` as an assertion instead, which is
 * the stronger check anyway: an image of the right page proves nothing about
 * which URL produced it.
 */
const LANDING_STATES = {
  full: { checkRoot: true, checkReducedMotion: true },
  /* Viewport-only, for the one `backdrop-blur` in the product. */
  header: { viewportOnly: true },
}

/* ── Admin (P4.7, surface 7) ─────────────────────────────────────────────── */

const SCHOOL_ADMIN_SESSION = {
  accessToken: fakeJwt(),
  refreshToken: fakeJwt(72),
  userId: "capture-school-admin",
  role: "school_admin",
}

const SCHOOL_ADMIN_PROFILE = {
  userId: "capture-school-admin",
  email: "registrar@nasrschool.example",
  displayName: "Dalia Mansour",
  role: "school_admin",
}

const PLATFORM_ADMIN_SESSION = {
  accessToken: fakeJwt(),
  refreshToken: fakeJwt(72),
  userId: "capture-platform-admin",
  role: "platform_admin",
}

const PLATFORM_ADMIN_PROFILE = {
  userId: "capture-platform-admin",
  email: "ops@lemely.example",
  displayName: "Ops",
  role: "platform_admin",
}

/** Field-for-field `SchoolOverviewDTO`. Invented numbers, real shape. */
const SCHOOL_OVERVIEW = {
  schools: [
    {
      schoolId: "sch-1",
      schoolName: "Nasr International School",
      quota: 120,
      seatsUsed: 87,
      seatsAvailable: 33,
      teacherCount: 9,
      classCount: 14,
      enrolledStudentCount: 84,
      studentsWithAPaper: 61,
      averageLatestPercentage: 63.4,
    },
  ],
}

/** Field-for-field `SeatUsageListDTO`. */
const SEAT_USAGE = {
  schools: [
    {
      schoolId: "sch-1",
      schoolName: "Nasr International School",
      quota: 120,
      used: 3,
      available: 117,
      seats: [
        {
          seatId: "seat-1",
          status: "assigned",
          assignedUserId: "stu-1",
          assignedEmail: "amina@nasrschool.example",
          assignedDisplayName: "Amina Farouk",
          assignedAt: "2026-02-11T09:00:00Z",
          classes: [{ classId: "c1", name: "10A Physics", teacherName: "Hana Sabry" }],
          lastAttemptAt: "2026-08-11T18:20:00Z",
        },
        {
          seatId: "seat-2",
          status: "assigned",
          assignedUserId: "stu-2",
          assignedEmail: "yusuf@nasrschool.example",
          assignedDisplayName: "Yusuf Kamal",
          assignedAt: "2026-02-11T09:00:00Z",
          classes: [
            { classId: "c1", name: "10A Physics", teacherName: "Hana Sabry" },
            { classId: "c2", name: "10B Maths", teacherName: "Omar Reda" },
          ],
          lastAttemptAt: null,
        },
        {
          seatId: "seat-3",
          status: "assigned",
          assignedUserId: "stu-3",
          assignedEmail: "nour@nasrschool.example",
          assignedDisplayName: null,
          assignedAt: "2026-06-02T09:00:00Z",
          classes: [],
          lastAttemptAt: "2026-08-01T07:05:00Z",
        },
      ],
    },
  ],
}

const SEAT_USAGE_AT_QUOTA = {
  schools: [
    { ...SEAT_USAGE.schools[0], quota: 3, used: 3, available: 0 },
  ],
}

const SCHOOL_TEACHERS = {
  schools: [
    {
      schoolId: "sch-1",
      schoolName: "Nasr International School",
      teachers: [
        {
          userId: "t-1",
          email: "h.sabry@nasrschool.example",
          displayName: "Hana Sabry",
          classCount: 3,
          studentCount: 71,
        },
        {
          userId: "t-2",
          email: "o.reda@nasrschool.example",
          displayName: "Omar Reda",
          classCount: 2,
          studentCount: 48,
        },
        {
          userId: "t-3",
          email: "newstarter@nasrschool.example",
          displayName: null,
          classCount: 0,
          studentCount: 0,
        },
      ],
    },
  ],
}

const SCHOOL_CLASSES = {
  classes: [
    {
      id: "c1",
      label: "10A Physics",
      studentCount: 28,
      average: 64.2,
      subjectCode: "0625",
      schoolId: "sch-1",
      joinCode: null,
      atRiskCount: 3,
      lastActivityAt: "2026-08-12T10:00:00Z",
      topWeakness: null,
    },
    {
      id: "c2",
      label: "10B Maths",
      studentCount: 26,
      average: null,
      subjectCode: "0580",
      schoolId: "sch-1",
      joinCode: null,
      atRiskCount: null,
      lastActivityAt: null,
      topWeakness: null,
    },
  ],
}

const PLATFORM_OVERVIEW = {
  counts: {
    students: 1842,
    parents: 611,
    teachers: 96,
    schoolAdmins: 14,
    platformAdmins: 2,
    schools: 12,
    classes: 143,
    papersMarkedTotal: 9127,
    papersMarkedLast24Hours: 41,
    papersMarkedLast7Days: 318,
    openReviewItems: 23,
    uploadsByStatus: { pending: 2, processing: 1, complete: 9104, failed: 6 },
  },
  spend: {
    cumulativeUsd: 1.2874,
    ceilingUsd: 8,
    remainingUsd: 6.7126,
    thresholdsUsd: [4, 6],
  },
  health: { databaseReachable: true, geminiKeyConfigured: true, version: "0.9.3" },
  recentSignups: [
    {
      userId: "u-1",
      email: "farida@example.com",
      displayName: "Farida Ehab",
      role: "student",
      createdAt: "2026-08-14T05:12:00Z",
    },
    {
      userId: "u-2",
      email: "head@newschool.example",
      displayName: null,
      role: "school_admin",
      createdAt: "2026-08-13T15:40:00Z",
    },
  ],
}

const ACTIVATION_QUEUE = {
  pending: [
    {
      subscriptionId: "sub-1",
      userId: "u-9",
      email: "parent@example.com",
      displayName: "Mona Adel",
      role: "parent",
      planCode: "family_monthly",
      planName: "Family monthly",
      priceMinor: 24900,
      currency: "EGP",
      requestedAt: "2026-08-09T11:00:00Z",
    },
    {
      subscriptionId: "sub-2",
      userId: "u-10",
      email: "head@newschool.example",
      displayName: null,
      role: "school_admin",
      planCode: "school_term",
      planName: "School term",
      priceMinor: 1200000,
      currency: "EGP",
      requestedAt: "2026-08-13T15:41:00Z",
    },
  ],
}

const PIPELINE_HEALTH = {
  subjects: [
    { subjectCode: "0625", papers: 46, papersWithScheme: 39, papersWithoutScheme: 7 },
    { subjectCode: "0580", papers: 51, papersWithScheme: 51, papersWithoutScheme: 0 },
  ],
  boundarySourceCounts: { exact: 5120, subject_default: 2110, global_default: 640 },
  exactBoundaryKeys: 74,
  subjectDefaultBoundaryKeys: 4,
  uploadsByStatus: { pending: 2, processing: 1, complete: 9104, failed: 6 },
  recentFailedUploadIds: [
    "a3f1c2d4-0000-4000-8000-000000000001",
    "a3f1c2d4-0000-4000-8000-000000000002",
  ],
  markingAccuracyNote:
    "Marking accuracy is measured by the accuracy harness against the golden fixture set, not by this service. Run the harness and read reports/ for the current figures.",
}

const SCHOOL_DASHBOARD_STATES = {
  populated: { overview: SCHOOL_OVERVIEW },
  // The state the denominator exists for: a mean over nobody is not 0%.
  "no-papers": {
    overview: {
      schools: [
        {
          ...SCHOOL_OVERVIEW.schools[0],
          studentsWithAPaper: 0,
          averageLatestPercentage: null,
        },
      ],
    },
  },
  // The accent is this palette's alert register, so it appears here and on no
  // other seat state. Worth a picture precisely because getting it wrong looks
  // fine in code.
  "at-quota": {
    overview: {
      schools: [{ ...SCHOOL_OVERVIEW.schools[0], quota: 87, seatsUsed: 87, seatsAvailable: 0 }],
    },
  },
  "no-school": { overview: { schools: [] } },
  loading: { delayMs: 30_000 },
  error: { status: 503, overview: { detail: "unavailable" } },
}

const SEATS_STATES = {
  populated: { seats: SEAT_USAGE },
  "at-quota": { seats: SEAT_USAGE_AT_QUOTA },
  empty: {
    seats: { schools: [{ ...SEAT_USAGE.schools[0], used: 0, available: 120, seats: [] }] },
  },
  loading: { delayMs: 30_000 },
  error: { status: 503, seats: { detail: "unavailable" } },
  "revoke-confirm": { seats: SEAT_USAGE, revokeRow: 0 },
}

const TEACHERS_STATES = {
  populated: { teachers: SCHOOL_TEACHERS },
  empty: {
    teachers: { schools: [{ schoolId: "sch-1", schoolName: "Nasr International School", teachers: [] }] },
  },
  loading: { delayMs: 30_000 },
  error: { status: 503, teachers: { detail: "unavailable" } },
  // K-03's whole requirement, photographed: the successor field, and a submit
  // button that stays disabled until one is chosen.
  "remove-needs-successor": { teachers: SCHOOL_TEACHERS, removeRow: 0 },
  // The teacher who owns nothing: no select at all, because there is nothing
  // to reassign.
  "remove-no-classes": { teachers: SCHOOL_TEACHERS, removeRow: 2 },
}

const ADMIN_CLASSES_STATES = {
  populated: { classes: SCHOOL_CLASSES },
  empty: { classes: { classes: [] } },
  loading: { delayMs: 30_000 },
  error: { status: 503, classes: { detail: "unavailable" } },
}

const PLATFORM_CONSOLE_STATES = {
  populated: { overview: PLATFORM_OVERVIEW },
  // Past the first configured threshold, which is the only condition that
  // turns the spend panel's meter to the alert register.
  "spend-warning": {
    overview: {
      ...PLATFORM_OVERVIEW,
      spend: { cumulativeUsd: 5.42, ceilingUsd: 8, remainingUsd: 2.58, thresholdsUsd: [4, 6] },
    },
  },
  // A real configuration state, and distinct from a ceiling of zero.
  "no-ceiling": {
    overview: {
      ...PLATFORM_OVERVIEW,
      spend: { cumulativeUsd: 1.2874, ceilingUsd: null, remainingUsd: null, thresholdsUsd: [] },
    },
  },
  quiet: {
    overview: {
      ...PLATFORM_OVERVIEW,
      counts: {
        ...PLATFORM_OVERVIEW.counts,
        openReviewItems: 0,
        uploadsByStatus: { pending: 0, processing: 0, complete: 9104, failed: 0 },
      },
      recentSignups: [],
    },
  },
  loading: { delayMs: 30_000 },
  error: { status: 503, overview: { detail: "unavailable" } },
}

const ACTIVATIONS_STATES = {
  populated: { queue: ACTIVATION_QUEUE },
  empty: { queue: { pending: [] } },
  loading: { delayMs: 30_000 },
  error: { status: 503, queue: { detail: "unavailable" } },
  // The note requirement, photographed: the confirm button is disabled until
  // something is written, which is the whole reason migration 0019 exists.
  "activate-needs-note": { queue: ACTIVATION_QUEUE, decideRow: 0, activate: true },
  "reject-needs-note": { queue: ACTIVATION_QUEUE, decideRow: 0, activate: false },
}

const PIPELINE_STATES = {
  populated: { pipeline: PIPELINE_HEALTH },
  // The state the panel exists to make visible: most predictions running on a
  // substituted boundary rather than a published one.
  "mostly-estimated": {
    pipeline: {
      ...PIPELINE_HEALTH,
      boundarySourceCounts: { exact: 400, subject_default: 2110, global_default: 3200 },
    },
  },
  "nothing-marked": {
    pipeline: {
      ...PIPELINE_HEALTH,
      boundarySourceCounts: {},
      uploadsByStatus: { pending: 0, processing: 0, complete: 0, failed: 0 },
      recentFailedUploadIds: [],
    },
  },
  loading: { delayMs: 30_000 },
  error: { status: 503, pipeline: { detail: "unavailable" } },
}

/**
 * Stub one JSON route, honouring a state's `delayMs`/`status`.
 *
 * The six admin surfaces each read one endpoint, so their `stub` functions were
 * six copies of the same eight lines. One helper instead: a delay that never
 * fulfils is how the loading state is captured, and it is exactly the detail a
 * copy would get subtly wrong on the sixth surface.
 */
function jsonRoute(page, pattern, state, body) {
  return page.route(pattern, async (route) => {
    if (state.delayMs) {
      await new Promise((r) => setTimeout(r, state.delayMs))
      return
    }
    await route.fulfill({
      status: state.status ?? 200,
      contentType: "application/json",
      body: JSON.stringify(body ?? {}),
    })
  })
}

const SURFACES = {
  /* ── Admin (P4.7, surface 7) ──────────────────────────────────────────── */

  /*
   * Both admin lanes carry `session` and `profile`, because the harness
   * switches identity per **surface** and not per state (the lesson surface 10
   * recorded the hard way). A `school_admin` session on a `/platform` route
   * would be bounced by `RequireAuth` and photograph as the login screen, which
   * looks like a broken capture rather than a working guard.
   */
  "school-dashboard": {
    prefix: "school-dashboard",
    route: "/school",
    states: SCHOOL_DASHBOARD_STATES,
    session: SCHOOL_ADMIN_SESSION,
    profile: SCHOOL_ADMIN_PROFILE,
    fullPage: (state) => !state.delayMs,
    async stub(page, state) {
      await jsonRoute(page, "**/api/school/overview", state, state.overview)
    },
  },

  "school-seats": {
    prefix: "school-seats",
    route: "/school/seats",
    states: SEATS_STATES,
    session: SCHOOL_ADMIN_SESSION,
    profile: SCHOOL_ADMIN_PROFILE,
    fullPage: (state) => !state.delayMs && state.revokeRow === undefined,
    async stub(page, state) {
      await jsonRoute(page, "**/api/school/seats", state, state.seats)
    },
    async act(page, state) {
      if (state.revokeRow === undefined) return
      await page.getByRole("button", { name: "Revoke seat" }).nth(state.revokeRow).click()
      await page.waitForTimeout(600)
    },
  },

  "school-teachers": {
    prefix: "school-teachers",
    route: "/school/teachers",
    states: TEACHERS_STATES,
    session: SCHOOL_ADMIN_SESSION,
    profile: SCHOOL_ADMIN_PROFILE,
    fullPage: (state) => !state.delayMs && state.removeRow === undefined,
    async stub(page, state) {
      await jsonRoute(page, "**/api/school/teachers", state, state.teachers)
    },
    async act(page, state) {
      if (state.removeRow === undefined) return
      await page.getByRole("button", { name: "Remove", exact: true }).nth(state.removeRow).click()
      await page.waitForTimeout(600)
    },
  },

  "school-classes": {
    prefix: "school-classes",
    route: "/school/classes",
    states: ADMIN_CLASSES_STATES,
    session: SCHOOL_ADMIN_SESSION,
    profile: SCHOOL_ADMIN_PROFILE,
    fullPage: (state) => !state.delayMs,
    async stub(page, state) {
      await jsonRoute(page, "**/api/teacher/classes", state, state.classes)
    },
  },

  "platform-console": {
    prefix: "platform-console",
    route: "/platform",
    states: PLATFORM_CONSOLE_STATES,
    session: PLATFORM_ADMIN_SESSION,
    profile: PLATFORM_ADMIN_PROFILE,
    fullPage: (state) => !state.delayMs,
    async stub(page, state) {
      await jsonRoute(page, "**/api/admin/overview", state, state.overview)
    },
  },

  "platform-activations": {
    prefix: "platform-activations",
    route: "/platform/activations",
    states: ACTIVATIONS_STATES,
    session: PLATFORM_ADMIN_SESSION,
    profile: PLATFORM_ADMIN_PROFILE,
    fullPage: (state) => !state.delayMs && state.decideRow === undefined,
    async stub(page, state) {
      await jsonRoute(page, "**/api/admin/activations", state, state.queue)
    },
    async act(page, state) {
      if (state.decideRow === undefined) return
      const label = state.activate ? "Activate" : "Turn down"
      await page.getByRole("button", { name: label, exact: true }).nth(state.decideRow).click()
      await page.waitForTimeout(600)
    },
  },

  "platform-pipeline": {
    prefix: "platform-pipeline",
    route: "/platform/pipeline",
    states: PIPELINE_STATES,
    session: PLATFORM_ADMIN_SESSION,
    profile: PLATFORM_ADMIN_PROFILE,
    fullPage: (state) => !state.delayMs,
    async stub(page, state) {
      await jsonRoute(page, "**/api/admin/pipeline", state, state.pipeline)
    },
  },

  /* ── Marketing (P4.9, surface 9) ──────────────────────────────────────── */

  /*
   * `session: null`, and that is the entire point of the surface. Captured
   * signed-out because signed-out is who the page is now for: until P4.9 it
   * was mounted behind a student-only guard, where a session was the only way
   * to see it at all.
   */
  landing: {
    prefix: "landing",
    route: "/landing",
    states: LANDING_STATES,
    session: null,
    fullPage: (state) => !state.viewportOnly,
    async stub() {
      // Nothing to stub. The page makes no API call, which is itself worth
      // knowing: a marketing page that needed the backend to render would be
      // a marketing page that goes down with it.
    },
    async act(page, state) {
      if (state.checkReducedMotion) {
        /*
         * The reduced-motion path, asserted rather than photographed.
         *
         * It WAS a capture state, and the duplicate detector removed it: once
         * the ordinary capture scrolls the page (see below), the two settle to
         * byte-identical images — which is the correct behaviour and something
         * no picture can distinguish from the feature being absent.
         *
         * The assertion is stronger anyway. `Reveal` starts every section at
         * `opacity: 0` and clears it on intersection, so the failure mode of
         * getting reduced motion wrong is not a page that moves too much, it
         * is a **blank page** for the reader least able to tolerate one. This
         * loads with the preference set, scrolls nothing at all, and requires
         * the last section on the page to already be opaque.
         */
        await page.emulateMedia({ reducedMotion: "reduce" })
        await page.goto(`${BASE}/landing`, { waitUntil: "domcontentloaded" })
        await page.waitForTimeout(900)
        const opacity = await page.evaluate(() => {
          const headings = Array.from(document.querySelectorAll("h2"))
          const last = headings[headings.length - 1]
          if (!last) return null
          // The Reveal wrapper is the ancestor carrying the opacity.
          let node = last
          for (let i = 0; i < 6 && node.parentElement; i += 1) {
            const o = Number(getComputedStyle(node).opacity)
            if (o < 1) return o
            node = node.parentElement
          }
          return 1
        })
        if (opacity === null || opacity < 1) {
          throw new Error(
            `reduced motion left the foot of the page hidden (opacity ${opacity}); a reduced-motion reader would see a blank page`,
          )
        }
        console.log("verified: reduced motion renders the whole page without scrolling")
        await page.emulateMedia({ reducedMotion: "no-preference" })
      }

      if (state.checkRoot) {
        /*
         * The surface's headline fix, asserted rather than photographed. Until
         * P4.9, `/` sent every signed-out visitor to `/login` and the landing
         * page sat behind a student-only auth guard, so the product had no
         * public page at all. If that regresses, this throws and the round
         * fails — which is more than any image of this page could tell you,
         * because the image would look identical either way.
         */
        await page.goto(`${BASE}/`, { waitUntil: "domcontentloaded" })
        await page.waitForTimeout(900)
        const heading = await page.locator("h1").first().innerText()
        if (!heading.includes("Thirty papers")) {
          throw new Error(
            `/ did not render the landing page for a signed-out visitor (h1 was ${JSON.stringify(heading)})`,
          )
        }
        console.log("verified: / renders the landing page for a signed-out visitor")
        await page.goto(`${BASE}/landing`, { waitUntil: "domcontentloaded" })
        await page.waitForTimeout(1400)
        /*
         * Scroll the whole page before the shutter, and the first round proved
         * why. `fullPage` captures the document without scrolling it, so
         * `Reveal`'s IntersectionObserver never fires for anything below the
         * fold and every section after the proof band photographed as blank
         * paper. The image was not evidence of a broken page — a reader who
         * scrolls sees all of it — but it was not evidence of a working one
         * either, and a capture round that photographs an empty page is the
         * failure mode the duplicate detector exists to prevent, arriving by a
         * different door.
         */
        await page.evaluate(async () => {
          const step = window.innerHeight
          for (let y = 0; y < document.body.scrollHeight; y += step) {
            window.scrollTo(0, y)
            await new Promise((r) => setTimeout(r, 120))
          }
          window.scrollTo(0, 0)
        })
        await page.waitForTimeout(900)
      }
    },
  },

  /*
   * The data page (P6.5, D6.8 option A), registered here rather than left to
   * the landing surface's coat-tails.
   *
   * It is a second route with a second layout, and this phase has now twice
   * recorded what happens to a screen that no list claims (P4.10's two admin
   * portals, in none of the three gate lists). One entry here puts it in front
   * of the adapt gate at all five widths and in the screenshot rounds, both of
   * which import this registry.
   *
   * `session: null` because it is public, and no `stub`: like the landing page
   * it makes no API call, which is the property worth keeping. Running prose is
   * also the page most likely to break the 44px touch floor on a 320px screen,
   * since its only controls are the footer's four inline links sitting close
   * together in a wrapped row, so the width sweep is the point rather than a
   * formality.
   */
  "data-handling": {
    prefix: "data-handling",
    route: "/data",
    states: { full: { checkReducedMotion: true } },
    session: null,
    fullPage: () => true,
    async stub() {},
    /*
     * Both halves of this are lifted from the landing surface, and the first
     * capture round proved they were needed here too rather than assumed.
     *
     * The first attempt registered this surface with no `act` at all, and the
     * 375px capture came back with the top two sections rendered and **the
     * bottom two thirds of the page blank paper**. `Reveal` starts every
     * section at `opacity: 0` and clears it on intersection, and `fullPage`
     * photographs the document without scrolling it, so nothing below the fold
     * ever intersected. The page was fine; the picture was not evidence about
     * it — which is precisely what the landing surface's own comment says, one
     * screen further down this file, written after the identical mistake.
     */
    async act(page, state) {
      if (state.checkReducedMotion) {
        /*
         * Asserted, not photographed, for the same reason as the landing page:
         * once the ordinary capture scrolls, the two settle to byte-identical
         * images. The failure mode of getting reduced motion wrong here is not
         * a page that moves too much, it is a **blank page**, and on this
         * particular page a blank page is a reader being told nothing about
         * what happens to their work.
         */
        await page.emulateMedia({ reducedMotion: "reduce" })
        await page.goto(`${BASE}/data`, { waitUntil: "domcontentloaded" })
        await page.waitForTimeout(900)
        const opacity = await page.evaluate(() => {
          const headings = Array.from(document.querySelectorAll("h2"))
          const last = headings[headings.length - 1]
          if (!last) return null
          let node = last
          for (let i = 0; i < 6 && node.parentElement; i += 1) {
            const o = Number(getComputedStyle(node).opacity)
            if (o < 1) return o
            node = node.parentElement
          }
          return 1
        })
        if (opacity === null || opacity < 1) {
          throw new Error(
            `reduced motion left the foot of /data hidden (opacity ${opacity}); a reduced-motion reader would see a blank page`,
          )
        }
        console.log("verified: /data renders the whole page without scrolling")
        await page.emulateMedia({ reducedMotion: "no-preference" })
        await page.goto(`${BASE}/data`, { waitUntil: "domcontentloaded" })
        await page.waitForTimeout(700)
      }

      await page.evaluate(async () => {
        const step = window.innerHeight
        for (let y = 0; y < document.body.scrollHeight; y += step) {
          window.scrollTo(0, y)
          await new Promise((r) => setTimeout(r, 120))
        }
        window.scrollTo(0, 0)
      })
      await page.waitForTimeout(900)
    },
  },

  /* ── Auth (P4.7, surface 8) ───────────────────────────────────────────── */

  login: {
    prefix: "login",
    route: "/login",
    states: LOGIN_STATES,
    session: null,
    async stub(page, state) {
      await page.route("**/api/auth/login", async (route) => {
        if (state.abort) return route.abort("failed")
        await route.fulfill({
          status: state.status ?? 200,
          contentType: "application/json",
          body: JSON.stringify(state.body ?? {}),
        })
      })
    },
    async act(page, state) {
      if (!state.submit) return
      await page.getByLabel("Email").fill("amina@example.com")
      await page.getByLabel("Password").fill("not-the-real-one")
      await page.getByRole("button", { name: "Sign in" }).click()
      await page.waitForTimeout(700)
    },
  },

  "parent-login": {
    prefix: "parent-login",
    route: "/login/parent",
    states: PARENT_LOGIN_STATES,
    session: null,
    async stub(page, state) {
      await page.route("**/api/auth/otp/request", (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(state.otp ?? { devCode: null }),
        }),
      )
      await page.route("**/api/auth/otp/verify", (route) =>
        route.fulfill({
          status: state.verifyStatus ?? 200,
          contentType: "application/json",
          body: JSON.stringify(state.verifyBody ?? {}),
        }),
      )
    },
    async act(page, state) {
      if (!state.sendCode) return
      await page.getByLabel("Phone number").fill("01012345678")
      await page.getByRole("button", { name: "Send code" }).click()
      await page.waitForTimeout(600)
      if (!state.typeCode) return
      // Typing into the first box auto-advances, so one fill per digit is the
      // path a parent takes and the one that exercises the auto-submit.
      for (const digit of state.typeCode) {
        await page.keyboard.type(digit)
      }
      await page.waitForTimeout(700)
    },
  },

  /* ── Sign-up flows (issue #10, Task 23) ───────────────────────────────── */

  "signup-role-select": {
    prefix: "signup-role-select",
    route: "/signup",
    states: { default: {} },
    session: null,
    async stub() {
      /* Three links and no request of its own (G-02's own docstring: "no
       * field and no submission"). Nothing to stub. */
    },
  },

  "signup-student": {
    prefix: "signup-student",
    route: "/signup/student",
    states: SIGNUP_STUDENT_STATES,
    session: null,
    async stub(page, state) {
      await page.route("**/api/auth/signup", (route) =>
        route.fulfill({
          status: state.status ?? 200,
          contentType: "application/json",
          body: JSON.stringify(state.body ?? {}),
        }),
      )
    },
    async act(page, state) {
      if (!state.submit) return
      await page.getByLabel("Name").fill("Amina Farouk")
      await page.getByLabel("Email").fill("amina@example.com")
      await page.getByLabel("Password").fill("a-strong-passphrase")
      await page.getByRole("checkbox").check()
      await page.getByRole("button", { name: "Create account" }).click()
      await page.waitForTimeout(700)
    },
  },

  "signup-teacher": {
    prefix: "signup-teacher",
    route: "/signup/teacher",
    states: SIGNUP_TEACHER_STATES,
    session: null,
    async stub(page) {
      await page.route("**/api/auth/signup", (route) =>
        route.fulfill({ status: 200, contentType: "application/json", body: "{}" }),
      )
    },
  },

  "verify-email-pending": {
    prefix: "verify-email-pending",
    route: "/verify-email",
    states: VERIFY_EMAIL_PENDING_STATES,
    // Signed in but unverified is the ordinary case this screen exists for
    // (D8.4/D8.5) — the common path lands here straight from signup, still
    // holding the fresh session `AuthService.signup` minted. `session: null`
    // would only ever render `SignedOutPending`'s two-link fallback.
    session: SESSION,
    profile: PROFILE,
    async stub(page, state) {
      await page.route("**/api/auth/verify-email/resend", (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ devLink: state.devLink ?? null }),
        }),
      )
    },
    async act(page, state) {
      if (!state.resend) return
      await page.getByRole("button", { name: "Resend verification link" }).click()
      await page.waitForTimeout(500)
    },
  },

  "verify-email-confirm": {
    prefix: "verify-email-confirm",
    route: "/verify-email/capture-token",
    states: VERIFY_EMAIL_CONFIRM_STATES,
    session: null,
    async stub(page, state) {
      await page.route("**/api/auth/verify-email", async (route) => {
        if (state.delayMs) {
          await new Promise((r) => setTimeout(r, state.delayMs))
          return
        }
        await route.fulfill({
          status: state.status ?? 200,
          contentType: "application/json",
          body: JSON.stringify(state.body ?? { status: "verified" }),
        })
      })
    },
  },

  "reset-request": {
    prefix: "reset-request",
    route: "/reset",
    states: RESET_REQUEST_STATES,
    session: null,
    async stub(page, state) {
      await page.route("**/api/auth/password-reset/request", (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ devLink: state.devLink ?? null }),
        }),
      )
    },
    async act(page, state) {
      if (!state.submit) return
      await page.getByLabel("Email").fill("amina@example.com")
      await page.getByRole("button", { name: "Send reset link" }).click()
      await page.waitForTimeout(600)
    },
  },

  "reset-confirm": {
    prefix: "reset-confirm",
    route: "/reset/capture-token",
    states: RESET_CONFIRM_STATES,
    session: null,
    async stub(page) {
      await page.route("**/api/auth/password-reset/confirm", (route) =>
        route.fulfill({ status: 200, contentType: "application/json", body: "{}" }),
      )
    },
    async act(page, state) {
      if (!state.submit) return
      await page.getByLabel("New password").fill("a-different-strong-passphrase")
      await page.getByRole("button", { name: "Set new password" }).click()
      await page.waitForTimeout(600)
    },
  },

  "join-code-entry": {
    prefix: "join-code-entry",
    route: "/join",
    states: JOIN_CODE_ENTRY_STATES,
    session: null,
    async stub() {
      /* No code is active yet, so `useInvitePreview` never fires (`enabled`
       * is tied to a non-empty code) — nothing to stub. */
    },
  },

  "join-code-preview": {
    prefix: "join-code-preview",
    route: "/join/capture-preview-code",
    states: JOIN_CODE_PREVIEW_STATES,
    session: null,
    async stub(page, state) {
      await page.route("**/api/invites/capture-preview-code", (route) =>
        route.fulfill({
          status: state.status ?? 200,
          contentType: "application/json",
          body: JSON.stringify(state.status ? (state.body ?? {}) : state.preview),
        }),
      )
    },
  },

  /* ── Parent (P4.6, surface 6) ─────────────────────────────────────────── */

  "parent-children": {
    prefix: "parent-children",
    route: "/parent",
    states: PARENT_CHILDREN_STATES,
    session: PARENT_SESSION,
    profile: PARENT_PROFILE,
    async stub(page, state) {
      await page.route("**/api/parent/children", async (route) => {
        if (state.delayMs) {
          await new Promise((r) => setTimeout(r, state.delayMs))
          return
        }
        await route.fulfill({
          status: state.status ?? 200,
          contentType: "application/json",
          body: JSON.stringify(state.children ?? {}),
        })
      })
    },
  },

  "parent-overview": {
    prefix: "parent-overview",
    route: "/parent/children/child-1",
    states: PARENT_OVERVIEW_STATES,
    session: PARENT_SESSION,
    profile: PARENT_PROFILE,
    /*
     * The child list is stubbed unconditionally and successfully on the three
     * child screens, because the shell reads it for the switcher and for the
     * breadcrumb's first rung. Registration order is load-bearing in the same
     * way the runner's catch-all is: Playwright matches the most recently
     * registered route first, so the list goes on before the detail route that
     * has to win.
     */
    async stub(page, state) {
      await page.route("**/api/parent/children", (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(PARENT_CHILDREN),
        }),
      )
      await page.route("**/api/parent/children/*", async (route) => {
        if (state.delayMs) {
          await new Promise((r) => setTimeout(r, state.delayMs))
          return
        }
        await route.fulfill({
          status: state.status ?? 200,
          contentType: "application/json",
          body: JSON.stringify(state.overview ?? {}),
        })
      })
    },
  },

  "parent-subject": {
    prefix: "parent-subject",
    route: "/parent/children/child-1/subjects/0625",
    states: PARENT_SUBJECT_STATES,
    session: PARENT_SESSION,
    profile: PARENT_PROFILE,
    async stub(page, state) {
      await page.route("**/api/parent/children", (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(PARENT_CHILDREN),
        }),
      )
      await page.route("**/api/parent/children/*/subjects/*", async (route) => {
        if (state.delayMs) {
          await new Promise((r) => setTimeout(r, state.delayMs))
          return
        }
        await route.fulfill({
          status: state.status ?? 200,
          contentType: "application/json",
          body: JSON.stringify(state.subject ?? {}),
        })
      })
    },
  },

  "parent-weaknesses": {
    prefix: "parent-weaknesses",
    route: "/parent/children/child-1/weaknesses",
    states: PARENT_WEAKNESSES_STATES,
    session: PARENT_SESSION,
    profile: PARENT_PROFILE,
    async stub(page, state) {
      await page.route("**/api/parent/children", (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(PARENT_CHILDREN),
        }),
      )
      await page.route("**/api/parent/children/*/weaknesses", async (route) => {
        if (state.delayMs) {
          await new Promise((r) => setTimeout(r, state.delayMs))
          return
        }
        await route.fulfill({
          status: state.status ?? 200,
          contentType: "application/json",
          body: JSON.stringify(state.weaknesses ?? {}),
        })
      })
    },
  },

  /* ── Teacher (P4.5, surface 5) ─────────────────────────────────────────── */

  "teacher-overview": {
    prefix: "teacher-overview",
    route: "/teacher",
    states: TEACHER_OVERVIEW_STATES,
    session: TEACHER_SESSION,
    profile: TEACHER_PROFILE,
    async stub(page, state) {
      await page.route("**/api/teacher/classes", (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(state.classes ?? TEACHER_CLASSES),
        }),
      )
      await page.route("**/api/teacher/overview", async (route) => {
        if (state.delayMs) {
          await new Promise((r) => setTimeout(r, state.delayMs))
          return
        }
        await route.fulfill({
          status: state.status ?? 200,
          contentType: "application/json",
          body: JSON.stringify(state.overview ?? {}),
        })
      })
    },
  },

  "teacher-review": {
    prefix: "teacher-review",
    route: "/teacher/review",
    states: TEACHER_REVIEW_STATES,
    session: TEACHER_SESSION,
    profile: TEACHER_PROFILE,
    async stub(page, state) {
      await page.route("**/api/teacher/classes", (route) =>
        route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(TEACHER_CLASSES) }),
      )
      await page.route("**/api/teacher/review**", async (route) => {
        if (state.delayMs) {
          await new Promise((r) => setTimeout(r, state.delayMs))
          return
        }
        await route.fulfill({
          status: state.status ?? 200,
          contentType: "application/json",
          body: JSON.stringify(state.queue ?? {}),
        })
      })
    },
  },

  "teacher-quizzes": {
    prefix: "teacher-quizzes",
    route: "/teacher/quizzes",
    states: TEACHER_QUIZZES_STATES,
    session: TEACHER_SESSION,
    profile: TEACHER_PROFILE,
    async stub(page, state) {
      await page.route("**/api/teacher/classes", (route) =>
        route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(TEACHER_CLASSES) }),
      )
      await page.route("**/api/teacher/quizzes", async (route) => {
        if (state.delayMs) {
          await new Promise((r) => setTimeout(r, state.delayMs))
          return
        }
        await route.fulfill({
          status: state.status ?? 200,
          contentType: "application/json",
          body: JSON.stringify(state.quizzes ?? {}),
        })
      })
    },
  },

  /*
   * P5.3 registered these two. Both screens carry a chart this phase rebuilt on
   * Nivo, and **neither had a capture surface of any kind** — which is P4.10's
   * finding arriving again: the gate lists only grow by hand, so a screen no
   * surface claims is a screen no gate reads. The cohort trend and the at-risk
   * trend were, until now, the two charts in the product that no image had ever
   * been taken of.
   */
  "teacher-analytics": {
    prefix: "teacher-analytics",
    route: `/teacher/classes/${CLASS_DETAIL.id}/analytics`,
    states: TEACHER_ANALYTICS_STATES,
    session: TEACHER_SESSION,
    profile: TEACHER_PROFILE,
    async stub(page, state) {
      await page.route("**/api/teacher/classes", (route) =>
        route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(TEACHER_CLASSES) }),
      )
      // The class header is a separate fetch made by the parent route
      // (`ClassDetail`), and the analytics tab reads the roster out of its
      // context — so it has to succeed even in this screen's error state, or
      // the error under test is the wrong one.
      await page.route(`**/api/classes/${CLASS_DETAIL.id}`, (route) =>
        route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(CLASS_DETAIL) }),
      )
      await page.route(`**/api/classes/${CLASS_DETAIL.id}/analytics`, async (route) => {
        if (state.delayMs) {
          await new Promise((r) => setTimeout(r, state.delayMs))
          return
        }
        await route.fulfill({
          status: state.status ?? 200,
          contentType: "application/json",
          body: JSON.stringify(state.analytics ?? {}),
        })
      })
    },
  },

  "teacher-student": {
    prefix: "teacher-student",
    route: `/teacher/students/${STUDENT_DETAIL.studentId}`,
    states: TEACHER_STUDENT_STATES,
    session: TEACHER_SESSION,
    profile: TEACHER_PROFILE,
    async stub(page, state) {
      await page.route("**/api/teacher/classes", (route) =>
        route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(TEACHER_CLASSES) }),
      )
      await page.route("**/api/teacher/students/**", async (route) => {
        if (state.delayMs) {
          await new Promise((r) => setTimeout(r, state.delayMs))
          return
        }
        await route.fulfill({
          status: state.status ?? 200,
          contentType: "application/json",
          body: JSON.stringify(state.student ?? {}),
        })
      })
    },
  },

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
      /*
       * P6.2's recovery read. Registered AFTER the POST route above because
       * Playwright matches the most recently registered handler first, and
       * `**\/api/student/uploads` would otherwise swallow these two paths.
       *
       * `null` is the ordinary answer and is what every other state gets: most
       * of the time no run is going, and a screen that thought one was would
       * lock its own form.
       */
      const activeRun = state.activeRun
        ? {
            paperId: "capture-paper-1",
            filename: "0625_w24_qp_41.pdf",
            startedAt: "2026-08-14T09:12:00Z",
            ...state.activeRun,
          }
        : null
      await page.route("**/api/student/uploads/active", (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(activeRun),
        }),
      )
      await page.route("**/api/student/uploads/capture-paper-1", (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(activeRun ?? { detail: "Unknown paper" }),
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

  /* ── P4.4, surface 4: gamification ───────────────────────────────────── */

  standings: {
    prefix: "standings",
    route: "/student/board",
    states: STANDINGS_STATES,
    async stub(page, state) {
      await page.route("**/api/student/xp", (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(XP_FIXTURE),
        }),
      )
      await page.route("**/api/me/student-profile", (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(state.profile ?? STUDENT_PROFILE_FIXTURE),
        }),
      )
      await page.route("**/api/student/classes", (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(state.classes ?? { classes: [] }),
        }),
      )
      await page.route("**/api/student/standings", (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(state.standings ?? SUBJECT_RANKS_FIXTURE),
        }),
      )
      await page.route("**/api/student/leaderboard**", async (route) => {
        if (state.delayMs) {
          await new Promise((r) => setTimeout(r, state.delayMs))
          return
        }
        await route.fulfill({
          status: state.status ?? 200,
          contentType: "application/json",
          body: JSON.stringify(state.board ?? {}),
        })
      })
    },
    fullPage: (state) => !state.delayMs,
  },

  friends: {
    prefix: "friends",
    route: "/student/friends",
    states: FRIENDS_STATES,
    async stub(page, state) {
      await page.route("**/api/student/xp", (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(XP_FIXTURE),
        }),
      )
      await page.route("**/api/student/friends/requests", (route) =>
        route.fulfill({
          status: 422,
          contentType: "application/json",
          body: JSON.stringify({ detail: "No student has that code. Check it and try again." }),
        }),
      )
      await page.route("**/api/student/friends", async (route) => {
        if (state.delayMs) {
          await new Promise((r) => setTimeout(r, state.delayMs))
          return
        }
        await route.fulfill({
          status: state.status ?? 200,
          contentType: "application/json",
          body: JSON.stringify(state.page ?? {}),
        })
      })
    },
    /**
     * The send-failure state is reached by typing a code and pressing the
     * button, because that is the only way a student reaches it too. The
     * request stub above always refuses, so what is captured is the inline
     * field error in its real position — the thing this surface moved.
     */
    async act(page, state) {
      if (!state.sendBadCode) return
      await page.getByLabel("Add someone by their code").fill("K7P4RQ29")
      await page.getByRole("button", { name: "Send request" }).click()
      await page.waitForTimeout(600)
    },
    fullPage: (state) => !state.delayMs,
  },

  profile: {
    prefix: "profile",
    route: "/student/profile",
    states: PROFILE_STATES,
    async stub(page, state) {
      await page.route("**/api/student/xp", async (route) => {
        if (state.delayMs) {
          await new Promise((r) => setTimeout(r, state.delayMs))
          return
        }
        await route.fulfill({
          status: state.status ?? 200,
          contentType: "application/json",
          body: JSON.stringify(state.xp ?? XP_FIXTURE),
        })
      })
    },
    fullPage: (state) => !state.delayMs,
  },


  /* ── Surface 10 (P4.10) ─────────────────────────────────────────────────── */

  "settings-devices": {
    prefix: "settings-devices",
    route: "/settings/devices",
    states: DEVICES_STATES,
    fullPage: (state) => !state.delayMs,
    async stub(page, state) {
      await page.route("**/api/me/devices", async (route) => {
        if (state.delayMs) {
          await new Promise((r) => setTimeout(r, state.delayMs))
          return
        }
        await route.fulfill({
          status: state.status ?? 200,
          contentType: "application/json",
          body: JSON.stringify(state.devices),
        })
      })
      await page.route("**/api/me/devices/*", (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(state.revoke ?? { removed: true, wasCurrent: false }),
        }),
      )
    },
    async act(page, state) {
      if (state.signOutRow === undefined) return
      const buttons = page.getByRole("button", { name: /^Sign out/ })
      await buttons.nth(state.signOutRow).click()
      // The current device opens a confirmation; the others do not. Both are
      // states worth a picture, so this stops at whichever one the row implies.
      await page.waitForTimeout(state.stopAtConfirm ? 600 : 1200)
    },
  },

  "settings-notifications": {
    prefix: "settings-notifications",
    route: "/settings/notifications",
    states: NOTIFICATION_PREF_STATES,
    fullPage: (state) => !state.delayMs,
    async stub(page, state) {
      await page.route("**/api/notifications/push/config", (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ available: false, publicKey: null }),
        }),
      )
      await page.route("**/api/me/notification-preferences", async (route) => {
        if (route.request().method() !== "GET") {
          await route.fulfill({
            status: state.saveStatus ?? 200,
            contentType: "application/json",
            body: JSON.stringify(
              state.saveStatus ? { detail: "atRiskAlert is only settable for the teacher and parent roles." } : state.prefs,
            ),
          })
          return
        }
        if (state.delayMs) {
          await new Promise((r) => setTimeout(r, state.delayMs))
          return
        }
        await route.fulfill({
          status: state.status ?? 200,
          contentType: "application/json",
          body: JSON.stringify(state.prefs),
        })
      })
    },
    async act(page, state) {
      if (state.toggleRow === undefined) return
      await page.getByRole("switch").nth(state.toggleRow).click()
      await page.waitForTimeout(1000)
    },
  },

  "not-found": {
    prefix: "not-found",
    // The route is per state here, unlike every other surface: the whole point
    // is that the same screen answers differently depending on which subtree
    // the unmatched path fell in.
    route: "/nonsense-path",
    states: NOT_FOUND_STATES,
    async stub() {
      /* Nothing to stub: neither branch makes an API call. */
    },
    act: notFoundAct,
  },

  "not-found-teacher": {
    prefix: "not-found-teacher",
    route: "/teacher/nonsense-path",
    states: NOT_FOUND_TEACHER_STATES,
    session: TEACHER_SESSION,
    profile: TEACHER_PROFILE,
    async stub(page) {
      /*
       * The 404 body makes no API call, but the teacher LAYOUT does: its
       * sidebar renders "Your classes" from `GET /teacher/classes`. Left
       * unstubbed the sidebar still mounts, so the assertion would pass either
       * way — it is stubbed so the picture shows the real chrome rather than a
       * permanent "Loading…" in the one region this state exists to prove is
       * still there.
       */
      await page.route("**/api/teacher/classes", (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(TEACHER_CLASSES),
        }),
      )
    },
    act: notFoundAct,
  },

  onboarding: {
    prefix: "onboarding",
    route: "/student/onboard",
    states: ONBOARDING_STATES,
    async stub(page, state) {
      await page.route("**/api/me/student-profile", (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(state.profile),
        }),
      )
    },
    async act(page, state) {
      if (!state.pickSubject) return
      // Expanding a subject is what reveals the three kit form controls that
      // replaced the hand-rolled ones, so it needs its own picture.
      await page.getByRole("button", { pressed: false }).nth(1).click()
      await page.waitForTimeout(600)
    },
  },

  subject: {
    prefix: "subject",
    route: "/student/subject/0625",
    states: SUBJECT_STATES,
    fullPage: (state) => !state.delayMs,
    async stub(page, state) {
      await page.route("**/api/student/subject/**", async (route) => {
        if (state.delayMs) {
          await new Promise((r) => setTimeout(r, state.delayMs))
          return
        }
        await route.fulfill({
          status: state.status ?? 200,
          contentType: "application/json",
          body: JSON.stringify(state.subject),
        })
      })
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

export { SURFACES, SESSION, PROFILE }

const surface = SURFACES[surfaceName]
if (!surface && isMain) {
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
  // P7.1: see scripts/serve_guard.mjs. A capture of a server this process did
  // not start is a picture of an unknown build.
  await assertPortFree(BASE, PORT, "the capture harness")
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
        /*
         * P4.5 made the identity per-surface. `SESSION`/`PROFILE` were both
         * hardcoded to `role: "student"`, which is fine while every registered
         * surface lives under `/student` and useless the moment one does not:
         * `RequireAuth` gates `/teacher` to teacher/school_admin/platform_admin
         * and redirects a student straight back to `/student`, so a teacher
         * capture would have produced ten pictures of the student dashboard.
         * That is exactly the failure the duplicate-hash check below exists to
         * catch, and it is cheaper to not cause it.
         */
        /*
         * `surface.session === null` means the signed-out surfaces (P4.7):
         * `/login` with a live session in storage is a redirect, not a screen,
         * so the fixture has to be *cleared* rather than overridden. `?? {}`
         * alone would have merged null into the student session and captured
         * eight pictures of the student dashboard — the same failure the
         * duplicate-hash check below exists to catch, and cheaper not to cause.
         */
        const session = surface.session === null ? null : { ...SESSION, ...(surface.session ?? {}) }
        await context.addInitScript(
          ([sess, key]) => {
            if (sess === null) window.localStorage.removeItem(key)
            else window.localStorage.setItem(key, JSON.stringify(sess))
            window.localStorage.setItem("lemely.deviceId", "capture-device")
          },
          [session, "lemely.session"],
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
          route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({ ...PROFILE, ...(surface.profile ?? {}) }),
          }),
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

if (isMain) {
  main().catch((err) => {
    console.error(err)
    process.exit(1)
  })
}
