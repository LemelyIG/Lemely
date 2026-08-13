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

const TEACHER_REVIEW_STATES = {
  /** The queue with all three reason kinds, oldest first. */
  populated: { queue: { items: REVIEW_ITEMS } },
  /** Empty, which on this screen is good news and must read as such. */
  empty: { queue: { items: [] } },
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

const SURFACES = {
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
        const session = { ...SESSION, ...(surface.session ?? {}) }
        await context.addInitScript(
          ([sess, key]) => {
            window.localStorage.setItem(key, JSON.stringify(sess))
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

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
