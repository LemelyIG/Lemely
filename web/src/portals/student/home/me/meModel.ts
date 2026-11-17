/*
 * Me view model (lane L1). Pure. The first four exports moved verbatim from
 * the old `screens/Profile.tsx` (see its history for the reasoning on each):
 * the window comes from the server, absent days are zero, the level curve is
 * read from the wire and never recomputed here.
 */
import type { Profile } from "@/lib/meTypes"
import type { StudentHome } from "@/lib/studentHomeTypes"
import type { XpDay, XpProfile, XpSource } from "@/lib/xpTypes"
import { gradeGapLabel, plural, relativeDay, shortSubject } from "../model"
import { homeRoutes, practiceTarget } from "../routes"

const GRADE_ORDER = ["U", "G", "F", "E", "D", "C", "B", "A", "A*"]

export function gradeRank(grade: string): number {
  return GRADE_ORDER.indexOf(grade)
}

/* ── moved from Profile.tsx (unchanged) ───────────────────────────────── */

export function calendarDays(start: string, end: string): string[] {
  const days: string[] = []
  const cursor = new Date(`${start}T00:00:00`)
  const last = new Date(`${end}T00:00:00`)
  while (cursor.getTime() <= last.getTime()) {
    const year = cursor.getFullYear()
    const month = String(cursor.getMonth() + 1).padStart(2, "0")
    const day = String(cursor.getDate()).padStart(2, "0")
    days.push(`${year}-${month}-${day}`)
    cursor.setDate(cursor.getDate() + 1)
  }
  return days
}

export function fillCalendar(profile: XpProfile): { day: string; xp: number }[] {
  const earned = new Map(profile.calendar.map((d: XpDay) => [d.day, d.xp]))
  return calendarDays(profile.calendarStart, profile.calendarEnd).map((day) => ({
    day,
    xp: earned.get(day) ?? 0,
  }))
}

export function levelProgress(profile: XpProfile): number {
  const span = profile.nextLevelXp - profile.levelStartXp
  if (span <= 0) return 0
  const into = profile.totalXp - profile.levelStartXp
  return Math.max(0, Math.min(100, (into / span) * 100))
}

const SOURCE_LABELS: Record<XpSource, string> = {
  paper_corrected: "Papers corrected",
  quiz_completed: "Quizzes",
  flashcard_reviewed: "Flashcards",
  study_session_completed: "Study sessions",
}

export function sourceLabel(source: XpSource | string): string {
  return SOURCE_LABELS[source as XpSource] ?? source.replace(/_/g, " ")
}

/* ── Me ───────────────────────────────────────────────────────────────── */

export function displayName(profile: Pick<Profile, "displayName" | "email"> | undefined): string {
  return profile?.displayName ?? profile?.email.split("@")[0] ?? "You"
}

export function levelLine(xp: XpProfile): string {
  const remaining = Math.max(0, xp.nextLevelXp - xp.totalXp)
  return `Level ${xp.level} · ${remaining.toLocaleString()} XP to level ${xp.level + 1}`
}

export function streakStrip(xp: XpProfile, days = 14): { day: string; on: boolean; now: boolean }[] {
  const filled = fillCalendar(xp).slice(-days)
  return filled.map((d, i) => ({ day: d.day, on: d.xp > 0, now: i === filled.length - 1 }))
}

export function streakLine(xp: XpProfile): { main: string; best: string | null } {
  const { current, longest } = xp.streak
  if (current === 0 && longest === 0) return { main: "Start a streak today", best: null }
  return { main: `${current}-day streak`, best: longest > 0 ? `best ${longest}` : null }
}

export function statsVm(home: StudentHome) {
  const last = home.recentPapers[0]
  const best = home.stats.bestGrade
  return [
    { value: String(home.stats.papersMarked), label: "papers marked", to: last ? homeRoutes.subject(last.subjectCode) : homeRoutes.scan, grade: null },
    {
      value: home.stats.marksWonBack > 0 ? `+${home.stats.marksWonBack}` : "0",
      label: "marks won back",
      to: practiceTarget(home),
      grade: null,
    },
    { value: best?.grade ?? "–", label: "best grade", to: best ? homeRoutes.subject(best.subjectCode) : homeRoutes.scan, grade: best?.grade ?? null },
  ]
}

export const BADGES = [
  { id: "first-paper", label: "First paper", hint: "Mark your first paper" },
  { id: "streak-7", label: "7-day streak", hint: "Earn XP seven days in a row" },
  { id: "grade-up", label: "Grade up", hint: "Move a subject up a grade" },
  { id: "streak-30", label: "30-day streak", hint: "Earn XP thirty days in a row" },
  { id: "a-star", label: "A* paper", hint: "Score an A* on a paper" },
] as const

export type BadgeId = (typeof BADGES)[number]["id"]

export function deriveBadges(home: StudentHome, xp: XpProfile) {
  const earned: Record<BadgeId, boolean> = {
    "first-paper": home.stats.papersMarked >= 1,
    "streak-7": xp.streak.longest >= 7,
    "grade-up": home.floor.some((f) => f.previousGrade !== null && gradeRank(f.grade) > gradeRank(f.previousGrade)),
    "streak-30": xp.streak.longest >= 30,
    "a-star": home.stats.bestGrade?.grade === "A*",
  }
  return BADGES.map((b) => ({ ...b, earned: earned[b.id] }))
}

export function ordinal(n: number): string {
  const tens = n % 100
  if (tens >= 11 && tens <= 13) return `${n}th`
  return `${n}${({ 1: "st", 2: "nd", 3: "rd" } as Record<number, string>)[n % 10] ?? "th"}`
}

export function peopleVm(input: {
  classes: number | undefined
  rank: number | null | undefined
  friends: number | undefined
  parents: number | undefined
}) {
  const sub = <T,>(v: T | undefined, f: (v: T) => string) => (v === undefined ? null : f(v))
  return [
    { id: "classes", label: "Classes", sub: sub(input.classes, (n) => `${n} ${n === 1 ? "class" : "classes"}`), to: homeRoutes.classes },
    { id: "standings", label: "Standings", sub: input.rank === undefined ? null : input.rank === null ? "Join a class" : ordinal(input.rank), to: homeRoutes.standings },
    { id: "friends", label: "Friends", sub: sub(input.friends, (n) => (n === 0 ? "Add a friend" : plural(n, "friend"))), to: homeRoutes.friends },
    { id: "parents", label: "Parents", sub: sub(input.parents, (n) => (n === 0 ? "Invite a parent" : `${n} linked`)), to: homeRoutes.parents },
  ] as const
}

export function subjectsVm(home: StudentHome) {
  return home.floor.map((f) => ({
    grade: f.grade,
    title: f.name,
    sub: [
      f.code,
      plural(f.papers, "paper"),
      gradeGapLabel(f),
    ].join(" · "),
    to: homeRoutes.subject(f.code),
  }))
}

export function activityVm(home: StudentHome) {
  return home.activity.map((a) => ({ kind: a.kind, title: a.title, sub: a.sub, when: relativeDay(a.at, home.localDate) }))
}

export function accountRows(input: { deletedCount: number | undefined; placementCode: string | null }) {
  const rows: { id: string; label: string; sub: string | null; to: string; overlay?: boolean }[] = [
    { id: "tutoring", label: "Tutoring", sub: "Book a session", to: homeRoutes.tutoring },
  ]
  if (input.placementCode) {
    rows.push({ id: "placement", label: "Placement test", sub: "Find your starting level", to: homeRoutes.placement(input.placementCode) })
  }
  rows.push(
    { id: "settings", label: "Profile and settings", sub: null, to: homeRoutes.settings, overlay: true },
    { id: "notifications", label: "Notifications", sub: null, to: homeRoutes.notifications },
    {
      id: "deleted",
      label: "Recently deleted",
      sub: input.deletedCount ? plural(input.deletedCount, "paper") : null,
      to: homeRoutes.recentlyDeleted,
    },
  )
  return rows
}

export { shortSubject }
