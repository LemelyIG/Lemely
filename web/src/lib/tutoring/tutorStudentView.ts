/*
 * What the tutor's two student screens say and show (T-19, T-20; SPEC §d, §e.2).
 *
 * Pure: no React, no network. The screens in
 * `portals/teacher/screens/tutoring/{MyStudents,TutorStudentDetail}.tsx` read
 * their copy, links and date formats from here, and `tutorStudentView.test.ts`
 * pins them.
 *
 * ── Dates only ──────────────────────────────────────────────────────────────
 *
 * The tutor projection (`lemely/web/student_detail_view.py`) cuts every instant
 * to its calendar day in the tutor's zone before it leaves the server, because
 * the student is promised that a tutor never sees "the time of day you used
 * Lemely". This module is the second lock on the same door. `dayLabel` shows a
 * `YYYY-MM-DD` day as it is (no `Date`, so the browser's zone cannot move it a
 * day), and if an instant ever arrived anyway it is cut to the tutor-zone day
 * here rather than formatted with its clock time. There is no relative
 * formatting at all: "active 3 hours ago" would be the time of day again.
 *
 * ── One ended state ─────────────────────────────────────────────────────────
 *
 * A grant that stopped being valid is a 403 `access_ended` whatever stopped it:
 * the student revoked it, it expired, a block or a sanction ended it (SC-11).
 * Nothing here takes the reason, so nothing here can say it.
 */

import { ApiError } from "@/lib/api"
import type { TutorStudentItem } from "@/lib/tutoringTypes"
import { tutoringErrorOf } from "./apiErrors"
import { tutorLoadFailureMessage } from "./tutorSessionActions"
import { SESSION_ZONE, formatTutorDate } from "./sessionView"

// ── Paths and copy ──────────────────────────────────────────────────────────

export const TUTORING_HOME_PATH = "/teacher/tutoring"
export const TUTOR_STUDENTS_PATH = "/teacher/tutoring/students"

/**
 * T-20's one name (SPEC §d): the route title, the hidden h1 of every state and
 * the screen's own wording agree on it. The visible h1 of a loaded page is the
 * student's name; the crumb stands in for that name where a breadcrumb needs a
 * label before the student is known.
 */
export const TUTOR_STUDENT_TITLE = "Student progress"
export const TUTOR_STUDENT_CRUMB = "This student"

/** T-20 for one student. */
export function tutorStudentPath(studentId: string): string {
  return `${TUTOR_STUDENTS_PATH}/${encodeURIComponent(studentId)}`
}

/** T-19, under the heading (SPEC §d). */
export const MY_STUDENTS_INTRO =
  "Students choose to share their progress with you. They can stop at any time, and they can see each time you look."

/** T-19, when no grant is live (SPEC §d). */
export const NO_STUDENTS_LINE = "No students are sharing their progress with you yet."

/** T-20, the consent line under the student's name (SPEC §d). */
export function sharedLine(name: string, grantedAt: string, zone: string = SESSION_ZONE): string {
  return `${name} shared this with you on ${dayLabel(grantedAt, { zone })}. They can stop sharing at any time. Each visit is recorded and they can see it.`
}

/**
 * T-20, the one sentence for an ended grant (SPEC §d, SC-11). The name comes from
 * the link the tutor followed, so it is a name the tutor already had; without it
 * the sentence says "This student".
 */
export function accessEndedHeading(name: string | null): string {
  return `${name ?? TUTOR_STUDENT_CRUMB}'s progress is no longer shared with you.`
}

/** Longest name taken from the link's state; a student label is a first name and an initial. */
const NAME_MAX = 120

/** The student's name from the router state the T-19 row passed, or null for anything else. */
export function studentNameFromState(state: unknown): string | null {
  if (state === null || typeof state !== "object") return null
  const name = (state as { studentName?: unknown }).studentName
  if (typeof name !== "string") return null
  const trimmed = name.trim()
  return trimmed.length > 0 && trimmed.length <= NAME_MAX ? trimmed : null
}

/** Why a tutor-student screen could not load: the API's own sentence when it sent one, else the shared one. */
export function studentLoadFailureMessage(error: unknown): string {
  return tutorLoadFailureMessage(error)
}

/**
 * Whether a failure is the API saying it does not know this student: its own
 * `not_found`, or a 422 because the address's id is not an id at all (FastAPI's
 * validation list, which carries no code). Any other 404, such as
 * `no_tutor_profile`, is a different problem and gets the failure state.
 */
export function isStudentNotFound(error: unknown): boolean {
  if (error instanceof ApiError && error.status === 422) return true
  const known = tutoringErrorOf(error)
  return known !== null && known.status === 404 && known.code === "not_found"
}

// ── Dates ───────────────────────────────────────────────────────────────────

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"] as const
const DAY = /^(\d{4})-(\d{2})-(\d{2})$/

/**
 * A calendar date as "20 Oct 2026" (or "20 Oct" with `year: false`), and never a
 * time. A `YYYY-MM-DD` day is read as written. An instant is cut to its day in
 * the tutor's zone (`zone`, the v1 zone unless the profile says otherwise).
 * Anything else, including a day that is not on the calendar, gives "".
 */
export function dayLabel(
  value: string,
  { year = true, zone = SESSION_ZONE }: { year?: boolean; zone?: string } = {},
): string {
  const match = DAY.exec(value)
  if (match) {
    const [, y, m, d] = match
    const month = Number(m)
    const day = Number(d)
    // Round-trip through UTC to reject 30 February without touching the browser's zone.
    const check = new Date(Date.UTC(Number(y), month - 1, day))
    const real = check.getUTCFullYear() === Number(y) && check.getUTCMonth() === month - 1 && check.getUTCDate() === day
    if (!real || month < 1 || month > 12) return ""
    return year ? `${day} ${MONTHS[month - 1]} ${y}` : `${day} ${MONTHS[month - 1]}`
  }
  // Only a full ISO instant is cut to a day; "20 Oct" would parse as a date in 2001.
  if (!/^\d{4}-\d{2}-\d{2}T/.test(value)) return ""
  const full = formatTutorDate(value, zone)
  if (full === "") return ""
  return year ? full : full.replace(/ \d{4}$/, "")
}

/**
 * How `StudentDetailView` writes dates for a tutor (the slots are
 * `StudentDetailDates` in `StudentDetail.tsx`; typed structurally so this
 * module does not import a screen).
 */
export interface TutorStudentDates {
  activeSummary(lastActiveAt: string | null): string
  lastActive(lastActiveAt: string | null): string
  chartLabel(recordedAt: string): string
  tableDate(recordedAt: string): string
  recorded(recordedAt: string): string
}

/** Shown where the projection had an activity it could not place on a day. Not "Never": the student was active. */
const UNPLACED = "\u2014"

/**
 * The tutor's date slots, cut in `zone`. `null` is a student who has never been
 * active; any other value `dayLabel` cannot place (the projection sends "" for an
 * instant it could not put on a day) is a dash, because saying "Never" would be false.
 */
export function tutorStudentDatesIn(zone: string): TutorStudentDates {
  const day = (value: string) => dayLabel(value, { zone })
  return {
    activeSummary: (lastActiveAt) => {
      if (lastActiveAt === null) return "never active"
      const label = day(lastActiveAt)
      return label === "" ? `last active ${UNPLACED}` : `active ${label}`
    },
    lastActive: (lastActiveAt) => {
      if (lastActiveAt === null) return "Never"
      const label = day(lastActiveAt)
      return label === "" ? UNPLACED : label
    },
    chartLabel: (recordedAt) => dayLabel(recordedAt, { year: false, zone }),
    tableDate: day,
    recorded: day,
  }
}

/** The v1 zone; T-20 passes the tutor's own when the profile is known. */
export const tutorStudentDates: TutorStudentDates = tutorStudentDatesIn(SESSION_ZONE)

// ── T-19 rows ───────────────────────────────────────────────────────────────

export interface StudentRowView {
  studentId: string
  name: string
  /** T-20 for this student. */
  href: string
  sinceLine: string
  upcomingLine: string
  ariaLabel: string
}

/** "No upcoming sessions", "1 upcoming session", "3 upcoming sessions". */
export function upcomingLine(count: number): string {
  if (count <= 0) return "No upcoming sessions"
  return count === 1 ? "1 upcoming session" : `${count} upcoming sessions`
}

/** One T-19 row: the label, since when, and how many sessions are coming. No analytics. */
export function studentRowView(item: TutorStudentItem): StudentRowView {
  const sinceLine = `Sharing since ${dayLabel(item.grantedAt)}`
  const upcoming = upcomingLine(item.upcomingSessions)
  return {
    studentId: item.studentId,
    name: item.displayName,
    href: tutorStudentPath(item.studentId),
    sinceLine,
    upcomingLine: upcoming,
    ariaLabel: `${item.displayName}. ${sinceLine}. ${upcoming}.`,
  }
}
