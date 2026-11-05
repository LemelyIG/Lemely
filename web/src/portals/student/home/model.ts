/*
 * Student home decision logic (spec 2026-11-05-student-home-design.md §3–4).
 * Pure functions only: no React, no fetching, no clock reads (`now` is passed
 * in), so every branch is a unit test. The dev preview and the React home
 * both call these, so the preview cannot drift from the product.
 */

export const GRADE_ORDER = ["U", "E", "D", "C", "B", "A", "A*"] as const

export interface UpcomingSession {
  sessionId: string
  subjectCode: string
  title: string
  minutes: number
  /** ISO date, YYYY-MM-DD. */
  scheduledFor: string
}

export interface HomeSubject {
  code: string
  papers: number
  grade: string
  previousGrade: string | null
  /** ISO date, YYYY-MM-DD. */
  nextExamOn: string | null
}

export interface WeakTopic {
  topic: string
  subjectCode: string
  /** Accuracy as a whole percentage, 0–100. */
  acc: number
}

export interface LatestResult {
  subjectCode: string
  grade: string
  paperId: string
  /** Display label, e.g. "0580/42 · m/j 2024". */
  paperLabel: string
  /** True once the student has opened the result. An unseen result takes over the hero. */
  seen: boolean
  /** UTC ISO-8601 timestamp. */
  recordedAt: string
}

export interface XpDay {
  /** ISO date, YYYY-MM-DD. */
  day: string
  xp: number
}

export interface HomeFacts {
  now: Date
  activeUpload: { paperLabel: string } | null
  subjects: readonly HomeSubject[]
  upcomingSessions: readonly UpcomingSession[]
  weakTopics: readonly WeakTopic[]
  latestResult: LatestResult | null
  calendar: readonly XpDay[]
}

export type NextAction =
  | { kind: "marking"; paperLabel: string; to: string }
  | { kind: "result"; result: LatestResult; to: string }
  | { kind: "session"; session: UpcomingSession; to: string }
  | { kind: "first-paper"; to: string }
  | { kind: "practice"; topic: WeakTopic; to: string }
  | { kind: "correct"; to: string }

export type NextActionKind = NextAction["kind"]

export type BinnyMood = "marking" | "grade-improved" | "paper-marked" | "streak-kept" | "idle"

export interface StreakDay {
  day: string
  xp: number
  earned: boolean
  isToday: boolean
}

export interface NextActionOptions {
  /** Variant B: among due sessions and weak topics, prefer the subject with the closest exam. */
  preferClosestExam?: boolean
}

const CORRECT_ROUTE = "/student/correct"
const DAY_MS = 86_400_000
const NO_EXAM = "9999-12-31"

export function localISODate(d: Date): string {
  const m = String(d.getMonth() + 1).padStart(2, "0")
  const day = String(d.getDate()).padStart(2, "0")
  return `${d.getFullYear()}-${m}-${day}`
}

function hasPapers(f: HomeFacts): boolean {
  return f.subjects.some((s) => s.papers > 0)
}

function dueSessions(f: HomeFacts): UpcomingSession[] {
  const today = localISODate(f.now)
  return f.upcomingSessions.filter((s) => s.scheduledFor <= today)
}

function weakestFirst(f: HomeFacts): WeakTopic[] {
  return [...f.weakTopics].sort((a, b) => a.acc - b.acc)
}

function examDate(f: HomeFacts, code: string): string {
  return f.subjects.find((s) => s.code === code)?.nextExamOn ?? NO_EXAM
}

/** Stable sort, so items for the same subject keep their order. */
function byClosestExam<T>(f: HomeFacts, items: T[], codeOf: (item: T) => string): T[] {
  return [...items].sort((a, b) => examDate(f, codeOf(a)).localeCompare(examDate(f, codeOf(b))))
}

const markingAction = (paperLabel: string): NextAction => ({ kind: "marking", paperLabel, to: CORRECT_ROUTE })
const resultAction = (r: LatestResult): NextAction => ({ kind: "result", result: r, to: `/student/result/${r.paperId}` })
const sessionAction = (s: UpcomingSession): NextAction => ({
  kind: "session",
  session: s,
  to: `/student/plan/${s.subjectCode}/session/${s.sessionId}`,
})
const practiceAction = (t: WeakTopic): NextAction => ({ kind: "practice", topic: t, to: `/student/practice/${t.subjectCode}` })
const FIRST_PAPER: NextAction = { kind: "first-paper", to: CORRECT_ROUTE }
const CORRECT_ANOTHER: NextAction = { kind: "correct", to: CORRECT_ROUTE }

export function deriveNextAction(f: HomeFacts, opts: NextActionOptions = {}): NextAction {
  if (f.activeUpload) return markingAction(f.activeUpload.paperLabel)
  if (f.latestResult && f.latestResult.seen === false) return resultAction(f.latestResult)
  let due = dueSessions(f)
  if (opts.preferClosestExam) due = byClosestExam(f, due, (s) => s.subjectCode)
  if (due.length > 0) return sessionAction(due[0])
  if (!hasPapers(f)) return FIRST_PAPER
  let weak = weakestFirst(f)
  if (opts.preferClosestExam) weak = byClosestExam(f, weak, (t) => t.subjectCode)
  if (weak.length > 0) return practiceAction(weak[0])
  return CORRECT_ANOTHER
}

/** Variant C's "today" list. Its first item always equals `deriveNextAction(f)`. */
export function todayList(f: HomeFacts, max = 3): NextAction[] {
  const out: NextAction[] = []
  if (f.activeUpload) out.push(markingAction(f.activeUpload.paperLabel))
  if (f.latestResult && f.latestResult.seen === false) out.push(resultAction(f.latestResult))
  out.push(...dueSessions(f).map(sessionAction))
  if (!hasPapers(f)) {
    if (!f.activeUpload) out.push(FIRST_PAPER)
    return out.slice(0, max)
  }
  const weakest = weakestFirst(f)[0]
  if (weakest) out.push(practiceAction(weakest))
  out.push(CORRECT_ANOTHER)
  return out.slice(0, max)
}

function gradeRank(grade: string): number {
  return (GRADE_ORDER as readonly string[]).indexOf(grade)
}

export function binnyMood(f: HomeFacts): BinnyMood {
  if (f.activeUpload) return "marking"
  const r = f.latestResult
  if (r && f.now.getTime() - Date.parse(r.recordedAt) < DAY_MS) {
    const previous = f.subjects.find((s) => s.code === r.subjectCode)?.previousGrade ?? null
    if (previous !== null && gradeRank(previous) >= 0 && gradeRank(r.grade) > gradeRank(previous)) {
      return "grade-improved"
    }
    return "paper-marked"
  }
  const today = localISODate(f.now)
  if (f.calendar.some((d) => d.day === today && d.xp > 0)) return "streak-kept"
  return "idle"
}

export function streakStrip(calendar: readonly XpDay[], now: Date): StreakDay[] {
  const xpByDay = new Map(calendar.map((d) => [d.day, d.xp]))
  const today = localISODate(now)
  return Array.from({ length: 7 }, (_, i) => {
    const day = localISODate(new Date(now.getFullYear(), now.getMonth(), now.getDate() - (6 - i)))
    const xp = xpByDay.get(day) ?? 0
    return { day, xp, earned: xp > 0, isToday: day === today }
  })
}
