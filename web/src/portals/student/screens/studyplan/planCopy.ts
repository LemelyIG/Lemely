/*
 * L9 · every string and date rule the study plan shows. Pure: no React and
 * no DOM. Vitest runs it in node.
 *
 * Copy follows the approved mock (`.impeccable/mocks/student-r2/sp.js`) with
 * two deliberate edits, both listed in the PR:
 *   - no "!" anywhere, because `npm run check:copy` bans it in product copy;
 *   - "Cost you 9 marks", not "on Paper 4", because the reason is summed over
 *     every paper and naming one would be false precision.
 */

import type { StudentExamCalendar } from "@/lib/announcementTypes"
import { daysUntil } from "@/lib/countdown"
import type { ActivityType, SessionReasonDTO } from "@/lib/studyPlanTypes"

const plural = (n: number, one: string, many: string) => (n === 1 ? one : many)

const ACTIVITY_LABELS: Record<ActivityType, string> = {
  practice: "Practice set",
  flashcards: "Flashcards",
  past_paper: "Past paper",
  review: "Review",
}

/** An unknown activity from a newer backend renders verbatim, never remapped. */
export function activityLabel(activity: string): string {
  return ACTIVITY_LABELS[activity as ActivityType] ?? activity
}

export function formatMinutes(minutes: number): string {
  if (minutes < 60) return `${minutes} min`
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  return rest === 0 ? `${hours} h` : `${hours} h ${rest} min`
}

/** Binny's spoken form ("15 minutes today."). */
export function spokenMinutes(minutes: number): string {
  return minutes < 60 ? `${minutes} ${plural(minutes, "minute", "minutes")}` : formatMinutes(minutes)
}

/** A bare `YYYY-MM-DD` as LOCAL midnight. `new Date("2026-08-06")` is UTC
 * midnight, which shows as the 5th west of Greenwich (K21). */
export function parseDay(iso: string): Date {
  return new Date(`${iso}T00:00:00`)
}

/* A fixed table, not `toLocaleDateString`: a small-ICU runtime or a stripped
 * browser locale answers with its own names, and the copy is English only. */
const WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"] as const

function weekday(iso: string, style: "short" | "long"): string {
  const d = parseDay(iso)
  if (Number.isNaN(d.getTime())) return iso
  const name = WEEKDAYS[d.getDay()]
  return style === "long" ? name : name.slice(0, 3)
}

export const weekdayShort = (iso: string) => weekday(iso, "short")
export const weekdayLong = (iso: string) => weekday(iso, "long")

export function addDays(iso: string, days: number): string {
  const d = parseDay(iso)
  d.setDate(d.getDate() + days)
  const mm = String(d.getMonth() + 1).padStart(2, "0")
  const dd = String(d.getDate()).padStart(2, "0")
  return `${d.getFullYear()}-${mm}-${dd}`
}

export function daysAgo(n: number): string {
  if (n <= 0) return "today"
  if (n === 1) return "yesterday"
  return `${n} days ago`
}

/** The short reason under a row. `null` when nothing proves one. */
export function reasonLine(reason: SessionReasonDTO | null | undefined): string | null {
  if (!reason) return null
  switch (reason.kind) {
    case "marks_lost":
      return `Cost you ${reason.count} ${plural(reason.count, "mark", "marks")}`
    case "cards_due":
      return `${reason.count} ${plural(reason.count, "card", "cards")} due`
    case "last_paper":
      return `Your last paper was ${daysAgo(reason.count)}`
  }
}

/** The sheet's "Why this?" body. The no-reason line is true by
 * construction: with no weakness behind it, the planner's other two inputs
 * are placement and ratings, and which one is not recorded (K26). */
export function whyBody(input: {
  reason: SessionReasonDTO | null | undefined
  topic: string
  targetGrade: string | null
}): string {
  const { reason, topic, targetGrade } = input
  if (!reason) return "Picked from your placement test or your topic ratings."
  switch (reason.kind) {
    case "marks_lost": {
      const base = `${topic} has cost you ${reason.count} ${plural(reason.count, "mark", "marks")} so far.`
      return targetGrade ? `${base} Win them back on the way to your ${targetGrade}.` : base
    }
    case "cards_due":
      return reason.count === 1
        ? `1 ${topic} card is due today.`
        : `${reason.count} ${topic} cards are due today.`
    case "last_paper":
      return `A full paper keeps your timing sharp. Your last one was ${daysAgo(reason.count)}.`
  }
}

export interface StartAction {
  label: string
  path: string
}

/** `null` for review: nothing in the product renders revision material, so a
 * Start button would go nowhere (K28). */
export function startAction(
  activity: string,
  subjectCode: string,
  reason: SessionReasonDTO | null | undefined,
): StartAction | null {
  switch (activity) {
    case "practice":
      return {
        label:
          reason?.kind === "marks_lost"
            ? `Start · +${reason.count} ${plural(reason.count, "mark", "marks")}`
            : "Start",
        path: `/student/practice/${subjectCode}`,
      }
    case "flashcards":
      return {
        label: reason?.kind === "cards_due" ? `Start · ${reason.count} ${plural(reason.count, "card", "cards")}` : "Start",
        path: `/student/flashcards/${subjectCode}`,
      }
    case "past_paper":
      return { label: "Start", path: "/student/correct" }
    default:
      return null
  }
}

export interface NextExam {
  date: string
  paperNumber: number
}

/** The soonest future exam date for one subject, from the same calendar the
 * Announcements countdown reads (K9).
 *
 * `today` must be built with `parseDay(response.today)` (the server's day,
 * local midnight), never `new Date(iso)` (UTC midnight, a day off west of UTC)
 * or `new Date()` (the device clock, a second source of truth).
 */
export function nextExamForSubject(
  calendar: StudentExamCalendar | undefined,
  subjectCode: string,
  today: Date,
): NextExam | null {
  if (!calendar) return null
  let best: (NextExam & { days: number }) | null = null
  for (const entry of calendar.entries) {
    if (entry.subjectCode !== subjectCode) continue
    for (const d of entry.dates) {
      const days = daysUntil(d.examDate, today)
      if (days < 0) continue
      if (best === null || days < best.days) best = { date: d.examDate, paperNumber: entry.paperNumber, days }
    }
  }
  return best ? { date: best.date, paperNumber: best.paperNumber } : null
}

/**
 * Countdown line for one exam.
 *
 * `today` must be built with `parseDay(response.today)` (the server's day,
 * local midnight), never `new Date(iso)` (UTC midnight, a day off west of UTC)
 * or `new Date()` (the device clock, a second source of truth).
 */
export function examLine(exam: NextExam, today: Date): string {
  const days = daysUntil(exam.date, today)
  const when = days === 0 ? "today" : days === 1 ? "tomorrow" : `in ${days} days`
  return `Paper ${exam.paperNumber} ${when}`
}

export function basedOnLine(paperCount: number): string {
  return paperCount > 0
    ? `Built from your ${paperCount} ${plural(paperCount, "paper", "papers")} and weak topics`
    : "Built from your weak topics and ratings"
}

export function whyTopicsHint(subjectName: string, paperCount: number): string {
  return paperCount > 0
    ? `Your weakest ${subjectName} topics from ${paperCount} ${plural(paperCount, "paper", "papers")}.`
    : `Your weakest ${subjectName} topics so far.`
}

export interface RefusalCopy {
  heading: string
  body: string
}

/** One message per refusal reason. An unknown reason still gets its own
 * heading, never the no-signal one (K4). */
export function refusalCopy(reason: string | null): RefusalCopy {
  if (reason === "no_signal") {
    return {
      heading: "I need a paper first",
      body: "Mark one past paper, or take the 10-minute placement test, and I’ll plan your week.",
    }
  }
  return { heading: "I couldn’t plan this week", body: "Mark a paper or take the placement test, then rebuild." }
}

/** Every fixed string on the screen, in one place for review and the copy gate. */
export const COPY = {
  title: "This week",
  noPlanSub: "No plan yet",
  anyDay: "Any day this week",
  later: "Later this week",
  whyTopics: "Why these topics",
  whyThis: "Why this?",
  markDone: "Mark done",
  saving: "Saving…",
  tryAgain: "Try again",
  done: "Done",
  move: "Move",
  moveToday: "Move to today",
  moveAllToday: "Move all to today",
  moving: "Moving…",
  rebuild: "Rebuild",
  rebuilding: "Rebuilding…",
  rebuildingTitle: "Rebuilding your week…",
  rebuildingBody: "Using your latest papers.",
  completeError: "Couldn’t mark this done. Check your connection and try again.",
  moveError: "Couldn’t move it. Try again.",
  moveSuperseded: "Your plan was rebuilt. Here’s the new one.",
  moveCompleted: "That one’s already done.",
  notInWeek: "That session isn’t in this week’s plan. Your plan was rebuilt.",
  firstRunTitle: "Let’s plan your week",
  firstRunBody: "Lemely builds it from your papers and weak topics. Takes a second.",
  firstRunCta: "Build my week",
  building: "Building…",
  /** Spoken only: the visible button says "Building…", which says nothing of what is being built. */
  buildingAnnounce: "Building your week…",
  walk: [
    { title: "Short sessions", body: "10 minutes of practice, 5 of flashcards." },
    { title: "Weakest topics first", body: "The ones that cost you the most marks." },
    { title: "Rebuilt each week", body: "Every new paper sharpens the plan." },
  ],
  needPaperCta: "Scan a paper",
  placementCta: "Take the placement test",
  nothingTitle: "Nothing to plan this week",
  nothingBody: "You’re on top of it. Practise to stay sharp.",
  nothingCta: "Practise",
  noSubjectsTitle: "Pick your subjects",
  noSubjectsBody: "Your plan is built per subject.",
  noSubjectsCta: "Add subjects",
  weekDoneTitle: "Week done.",
  planNextWeek: "Plan next week",
  nextWeekReady: "Next week is ready for Monday",
  bonusPractice: "Bonus practice",
  loadErrorTitle: "We couldn’t load your week",
  loadErrorBody: "Check your connection, then try again.",
  backHome: "Back to Home",
  rebuildConfirmTitle: "Rebuild your week?",
  rebuildConfirmBody: "Your plan starts fresh. Done sessions keep their XP.",
  rebuildConfirmCta: "Rebuild",
  rebuildKeep: "Keep this week",
} as const
